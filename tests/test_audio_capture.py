"""Automated Software Tests: AudioCapture Pipeline & Bounded Queueing.

Verifies thread lifecycle, bounded queue buffer overflow handling,
callback invocation, and stream error recovery without requiring live WASAPI hardware.
"""

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audio.analyzer import AudioMetrics
from src.audio.capture import AudioCapture, CaptureStats
from src.audio.devices import AudioDevice


@pytest.fixture
def dummy_device() -> AudioDevice:
    """Fixture returning a mock AudioDevice."""
    return AudioDevice(
        index=1,
        name="Mock Speakers [Loopback]",
        sample_rate=48000,
        channels=2,
        is_loopback=True,
        is_default=True,
    )


def test_bounded_queue_drops_stale_frames(dummy_device: AudioDevice) -> None:
    """Queue overflow must drop oldest frame and increment dropped_frames count."""
    cap = AudioCapture(device=dummy_device, queue_maxsize=3)
    cap._is_running = True

    # Audio callback simulates incoming float32 frames
    frame_bytes = np.zeros(1024, dtype=np.float32).tobytes()

    # Fill queue to capacity (maxsize=3)
    for _ in range(3):
        cap._audio_callback(frame_bytes, 1024, {}, 0)
    assert cap._queue.qsize() == 3
    assert cap._dropped_frames == 0

    # Next frame should overflow and drop oldest frame
    cap._audio_callback(frame_bytes, 1024, {}, 0)
    assert cap._queue.qsize() == 3
    assert cap._dropped_frames == 1


def test_capture_lifecycle_mocked(dummy_device: AudioDevice) -> None:
    """Capture must initialize, start worker thread, and stop cleanly."""
    mock_pyaudio_cls = MagicMock()
    mock_pa = MagicMock()
    mock_stream = MagicMock()
    mock_pyaudio_cls.PyAudio.return_value = mock_pa
    mock_pa.open.return_value = mock_stream
    mock_stream.is_active.return_value = True

    received_data = []

    def on_metrics(metrics: AudioMetrics, stats: CaptureStats) -> None:
        received_data.append((metrics, stats))

    with patch("src.audio.capture.pyaudio", mock_pyaudio_cls), patch(
        "src.audio.capture.PYAUDIO_AVAILABLE", True
    ):
        capture = AudioCapture(
            device=dummy_device,
            frames_per_buffer=1024,
            on_metrics=on_metrics,
        )

        assert not capture.is_running
        capture.start()
        assert capture.is_running
        mock_stream.start_stream.assert_called_once()

        # Simulate one audio callback frame
        frame_data = np.full(2048, 0.5, dtype=np.float32).tobytes()
        capture._audio_callback(frame_data, 1024, {}, 0)

        # Allow worker thread to process frame
        time.sleep(0.1)
        capture.stop()

        assert not capture.is_running
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pa.terminate.assert_called_once()
        assert len(received_data) >= 1
        metrics, stats = received_data[0]
        assert isinstance(metrics, AudioMetrics)
        assert isinstance(stats, CaptureStats)
        assert stats.sample_rate == 48000


def test_stream_initialization_failure(dummy_device: AudioDevice) -> None:
    """Failed stream open must raise RuntimeError and clean up PyAudio instance."""
    mock_pyaudio_cls = MagicMock()
    mock_pa = MagicMock()
    mock_pyaudio_cls.PyAudio.return_value = mock_pa
    mock_pa.open.side_effect = OSError("Device unavailable")

    with patch("src.audio.capture.pyaudio", mock_pyaudio_cls), patch(
        "src.audio.capture.PYAUDIO_AVAILABLE", True
    ):
        capture = AudioCapture(device=dummy_device)
        with pytest.raises(RuntimeError, match="Failed to open WASAPI loopback stream"):
            capture.start()

        assert not capture.is_running
        mock_pa.terminate.assert_called_once()
