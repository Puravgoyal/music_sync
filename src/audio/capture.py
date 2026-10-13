"""Windows WASAPI audio loopback stream capture and worker pipeline."""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from src.audio.analyzer import AudioAnalyzer, AudioMetrics
from src.audio.devices import AudioDevice, get_default_output_device

logger = logging.getLogger("wiz_music_sync.audio.capture")

try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None  # type: ignore[assignment]
    PYAUDIO_AVAILABLE = False


@dataclass
class CaptureStats:
    """Real-time performance and latency telemetry."""

    sample_rate: int
    buffer_size: int
    buffer_duration_ms: float  # Buffer chunk duration: (buffer_size / sample_rate) * 1000
    fps: float  # Audio frames analyzed per second
    analysis_time_ms: float  # DSP execution time per frame (windowing, FFT, flux)
    estimated_latency_ms: float  # Estimated audio-to-analysis pipeline latency
    frames_processed: int
    dropped_frames: int
    queue_delay_ms: float = 0.0  # Buffer dwell time in bounded queue before worker dispatch

    @property
    def dsp_execution_time_ms(self) -> float:
        """Alias for analysis_time_ms."""
        return self.analysis_time_ms

    @property
    def estimated_audio_latency_ms(self) -> float:
        """Alias for estimated_latency_ms."""
        return self.estimated_latency_ms


class AudioCapture:
    """Manages WASAPI loopback audio stream capture, bounded queueing, and DSP worker thread."""

    def __init__(
        self,
        device: Optional[AudioDevice] = None,
        frames_per_buffer: int = 1024,
        queue_maxsize: int = 16,
        on_metrics: Optional[Callable[[AudioMetrics, CaptureStats], None]] = None,
    ) -> None:
        """Initialize AudioCapture.

        Args:
            device: AudioDevice to capture from. If None, uses default output device.
            frames_per_buffer: Number of samples per buffer (default 1024).
            queue_maxsize: Maximum queued frames before oldest is dropped (default 16).
            on_metrics: Optional callback invoked with (metrics, stats) for each analyzed frame.
        """
        self.device = device
        self.frames_per_buffer = int(frames_per_buffer)
        self.queue_maxsize = int(queue_maxsize)
        self.on_metrics = on_metrics

        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._queue: queue.Queue = queue.Queue(maxsize=self.queue_maxsize)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._analyzer: Optional[AudioAnalyzer] = None

        # Telemetry
        self._frames_processed: int = 0
        self._dropped_frames: int = 0
        self._fps: float = 0.0
        self._last_analysis_time_ms: float = 0.0
        self._last_stats: Optional[CaptureStats] = None
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """Whether audio capture and worker are currently running."""
        return self._is_running

    @property
    def last_stats(self) -> Optional[CaptureStats]:
        """Most recently calculated CaptureStats."""
        return self._last_stats

    def _audio_callback(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict,
        status: int,
    ) -> tuple:
        """Lightweight PortAudio callback.

        Copies raw PCM buffer into the bounded queue without performing DSP.
        """
        capture_time = time.perf_counter()
        if self._is_running and in_data:
            try:
                # Interpret raw byte buffer as float32 PCM samples
                samples = np.frombuffer(in_data, dtype=np.float32)
                # Enqueue sample array with timestamp
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                        self._dropped_frames += 1
                    except queue.Empty:
                        pass
                self._queue.put_nowait((samples, capture_time))
            except Exception as exc:
                logger.debug("Error in audio callback: %s", exc)

        return (None, pyaudio.paContinue if PYAUDIO_AVAILABLE else 0)

    def _worker_loop(self) -> None:
        """Worker thread processing queued frames through DSP analyzer."""
        fps_frame_count = 0
        fps_start_time = time.perf_counter()
        buffer_duration_ms = (self.frames_per_buffer / self.sample_rate) * 1000.0

        while not self._stop_event.is_set():
            try:
                samples, capture_time = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue

            dsp_start = time.perf_counter()
            queue_delay_ms = (dsp_start - capture_time) * 1000.0

            # Execute real-time DSP analysis
            assert self._analyzer is not None
            metrics = self._analyzer.analyze_frame(samples, channels=self.channels)

            dsp_end = time.perf_counter()
            self._last_analysis_time_ms = (dsp_end - dsp_start) * 1000.0
            self._frames_processed += 1
            fps_frame_count += 1

            # Update FPS measurement every 0.5s
            now = time.perf_counter()
            elapsed_fps = now - fps_start_time
            if elapsed_fps >= 0.5:
                self._fps = fps_frame_count / elapsed_fps
                fps_frame_count = 0
                fps_start_time = now

            # Estimated latency: buffer duration + time waiting in queue + DSP compute
            estimated_latency_ms = buffer_duration_ms + max(0.0, queue_delay_ms) + self._last_analysis_time_ms

            stats = CaptureStats(
                sample_rate=self.sample_rate,
                buffer_size=self.frames_per_buffer,
                buffer_duration_ms=buffer_duration_ms,
                fps=self._fps,
                analysis_time_ms=self._last_analysis_time_ms,
                estimated_latency_ms=estimated_latency_ms,
                frames_processed=self._frames_processed,
                dropped_frames=self._dropped_frames,
                queue_delay_ms=max(0.0, queue_delay_ms),
            )
            self._last_stats = stats

            if self.on_metrics:
                try:
                    self.on_metrics(metrics, stats)
                except Exception as exc:
                    logger.debug("Exception in on_metrics callback: %s", exc)

    def start(self) -> None:
        """Open WASAPI loopback stream and launch worker processing thread."""
        if self._is_running:
            logger.warning("AudioCapture is already running.")
            return

        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudioWPatch is required for Windows WASAPI loopback capture.")

        if self.device is None:
            self.device = get_default_output_device()
            if self.device is None:
                raise RuntimeError("No compatible Windows audio output loopback device was found.")

        self.sample_rate = self.device.sample_rate
        self.channels = self.device.channels

        logger.info(
            "Starting WASAPI loopback capture on '%s' (Device %d: %dch @ %dHz, buffer: %d)",
            self.device.clean_name(),
            self.device.index,
            self.channels,
            self.sample_rate,
            self.frames_per_buffer,
        )

        self._analyzer = AudioAnalyzer(
            sample_rate=self.sample_rate,
            buffer_size=self.frames_per_buffer,
        )

        self._pyaudio = pyaudio.PyAudio()

        try:
            self._stream = self._pyaudio.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device.index,
                frames_per_buffer=self.frames_per_buffer,
                stream_callback=self._audio_callback,
            )
        except Exception as exc:
            self._cleanup_audio()
            raise RuntimeError(
                f"Failed to open WASAPI loopback stream on device '{self.device.name}': {exc}"
            ) from exc

        self._stop_event.clear()
        self._is_running = True
        self._frames_processed = 0
        self._dropped_frames = 0

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AudioAnalyzerWorker",
            daemon=True,
        )
        self._worker_thread.start()
        self._stream.start_stream()

    def stop(self) -> None:
        """Stop capture stream and join the worker thread cleanly."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()

        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as exc:
                logger.debug("Exception stopping stream: %s", exc)
            finally:
                self._stream = None

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        self._cleanup_audio()

        # Clear remaining queue items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        logger.info("WASAPI loopback capture stopped successfully.")

    def _cleanup_audio(self) -> None:
        """Terminate PyAudio instance safely."""
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception as exc:
                logger.debug("Exception terminating PyAudio: %s", exc)
            finally:
                self._pyaudio = None

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()
