"""Windows screen capture engine with multi-monitor support, downsampling, and robust fallback."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Optional, Tuple
import numpy as np

from src.screen.devices import ScreenMonitor, get_available_monitors, get_monitor_by_index

logger = logging.getLogger(__name__)


@dataclass
class CaptureStats:
    """Telemetry statistics for screen capture thread."""

    actual_fps: float = 0.0
    frames_captured: int = 0
    dropped_frames: int = 0
    capture_time_ms: float = 0.0
    is_capturing: bool = False
    backend_name: str = "None"
    monitor_name: str = "Default"


class BaseCaptureBackend(ABC):
    """Abstract interface for screen capture implementations."""

    name: str = "Base"

    @abstractmethod
    def start(self, monitor_index: int = 0) -> bool:
        """Initialize and start capture for specified monitor."""
        pass

    @abstractmethod
    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        """Capture and return downsampled RGB frame as uint8 array (H, W, 3)."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Release capture resources."""
        pass


class QtCaptureBackend(BaseCaptureBackend):
    """Reliable screen capture using Qt platform integration with DWM."""

    name = "Qt Desktop Capture"

    def __init__(self) -> None:
        self.monitor_index: int = 0
        self._screen = None

    def start(self, monitor_index: int = 0) -> bool:
        self.monitor_index = monitor_index
        try:
            import sys
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QGuiApplication

            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv if sys.argv else ["WiZScreenCapture"])

            screens = QGuiApplication.screens()
            if not screens:
                logger.warning("QtCaptureBackend: No Qt screens available")
                return False

            if 0 <= monitor_index < len(screens):
                self._screen = screens[monitor_index]
            else:
                self._screen = QGuiApplication.primaryScreen() or screens[0]

            logger.info("QtCaptureBackend initialized for screen: %s", self._screen.name())
            return True
        except Exception as exc:
            logger.error("QtCaptureBackend failed to initialize: %s", exc)
            return False

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if self._screen is None:
            return None

        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage

            # Grab full screen pixmap
            pixmap = self._screen.grabWindow(0)
            if pixmap.isNull():
                return None

            dw, dh = downsample_size
            # Fast downsampling in Qt
            scaled = pixmap.scaled(
                dw,
                dh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )

            qimg = scaled.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            h = qimg.height()
            w = qimg.width()
            bpl = qimg.bytesPerLine()

            ptr = qimg.bits()
            # View as uint8 array without copying
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl // 4, 4))
            # Slice active width and drop alpha channel -> RGB
            rgb_frame = np.ascontiguousarray(arr[:h, :w, :3])
            return rgb_frame
        except Exception as exc:
            logger.debug("QtCaptureBackend grab error: %s", exc)
            return None

    def stop(self) -> None:
        self._screen = None


class DXCamCaptureBackend(BaseCaptureBackend):
    """High-performance DirectX Desktop Duplication backend using DXcam."""

    name = "DXcam (Desktop Duplication)"

    def __init__(self) -> None:
        self.monitor_index: int = 0
        self._camera = None

    def start(self, monitor_index: int = 0) -> bool:
        self.monitor_index = monitor_index
        try:
            import dxcam

            # Attempt creating DXcam instance on target output
            self._camera = dxcam.create(output_idx=monitor_index)
            logger.info("DXCamCaptureBackend initialized on output %d", monitor_index)
            return True
        except Exception as exc:
            logger.warning("DXcam initialization failed (will fallback): %s", exc)
            self._camera = None
            return False

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if self._camera is None:
            return None

        try:
            # Grabs raw frame in RGB
            frame = self._camera.grab()
            if frame is None:
                return None

            # Fast downsample with numpy striding or slicing
            h, w, _ = frame.shape
            dw, dh = downsample_size
            step_y = max(1, h // dh)
            step_x = max(1, w // dw)
            downsampled = frame[::step_y, ::step_x, :3][:dh, :dw, :]
            return np.ascontiguousarray(downsampled)
        except Exception as exc:
            logger.debug("DXcam grab error: %s", exc)
            return None

    def stop(self) -> None:
        if self._camera:
            try:
                del self._camera
            except Exception:
                pass
            self._camera = None


class MockCaptureBackend(BaseCaptureBackend):
    """Synthetic test backend for injecting controlled test frames."""

    name = "Mock Capture Backend"

    def __init__(self, initial_frame: Optional[np.ndarray] = None) -> None:
        self.monitor_index: int = 0
        self._frame: Optional[np.ndarray] = initial_frame
        self._is_running = False

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame

    def start(self, monitor_index: int = 0) -> bool:
        self.monitor_index = monitor_index
        self._is_running = True
        return True

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if not self._is_running or self._frame is None:
            return None
        dw, dh = downsample_size
        h, w, _ = self._frame.shape
        step_y = max(1, h // dh)
        step_x = max(1, w // dw)
        downsampled = self._frame[::step_y, ::step_x, :3][:dh, :dw, :]
        return np.ascontiguousarray(downsampled)

    def stop(self) -> None:
        self._is_running = False


class ScreenCaptureManager:
    """Coordinates threaded screen capture at controlled FPS (10-15 Hz) with safe fallbacks."""

    def __init__(
        self,
        monitor_index: int = 0,
        target_fps: float = 12.0,
        downsample_size: Tuple[int, int] = (64, 36),
        on_frame: Optional[Callable[[np.ndarray, float], None]] = None,
        preferred_backend: str = "auto",  # 'auto', 'dxcam', 'qt', 'mock'
        custom_backend: Optional[BaseCaptureBackend] = None,
    ) -> None:
        self.monitor_index = monitor_index
        self.target_fps = max(5.0, min(30.0, float(target_fps)))
        self.downsample_size = downsample_size
        self.on_frame = on_frame
        self.preferred_backend = preferred_backend
        self._custom_backend = custom_backend

        self._backend: Optional[BaseCaptureBackend] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats_lock = threading.Lock()

        self._stats = CaptureStats()
        self._last_frame_time = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    @property
    def stats(self) -> CaptureStats:
        with self._stats_lock:
            return CaptureStats(
                actual_fps=self._stats.actual_fps,
                frames_captured=self._stats.frames_captured,
                dropped_frames=self._stats.dropped_frames,
                capture_time_ms=self._stats.capture_time_ms,
                is_capturing=self._stats.is_capturing,
                backend_name=self._stats.backend_name,
                monitor_name=self._stats.monitor_name,
            )

    def _select_backend(self) -> BaseCaptureBackend:
        if self._custom_backend:
            return self._custom_backend

        if self.preferred_backend == "dxcam":
            dx = DXCamCaptureBackend()
            if dx.start(self.monitor_index):
                return dx
            logger.info("DXcam unavailable, falling back to QtCaptureBackend")
            return QtCaptureBackend()

        if self.preferred_backend == "qt":
            return QtCaptureBackend()

        # 'auto': Attempt DXcam first, fallback cleanly to Qt
        dx = DXCamCaptureBackend()
        if dx.start(self.monitor_index):
            return dx
        return QtCaptureBackend()

    def start(self) -> bool:
        """Start the background capture loop."""
        if self.is_running:
            logger.warning("ScreenCaptureManager is already running")
            return True

        self._stop_event.clear()
        backend = self._select_backend()
        if not backend.start(self.monitor_index):
            logger.error("Failed to start screen capture backend %s", backend.name)
            return False

        self._backend = backend
        mon = get_monitor_by_index(self.monitor_index)

        with self._stats_lock:
            self._stats = CaptureStats(
                is_capturing=True,
                backend_name=backend.name,
                monitor_name=mon.name,
            )

        self._thread = threading.Thread(target=self._capture_worker, name="ScreenCaptureWorker", daemon=True)
        self._thread.start()
        logger.info("ScreenCaptureManager started using %s for monitor %d", backend.name, self.monitor_index)
        return True

    def stop(self) -> None:
        """Cleanly stop background capture loop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

        if self._backend:
            try:
                self._backend.stop()
            except Exception as exc:
                logger.debug("Error stopping capture backend: %s", exc)
            self._backend = None

        with self._stats_lock:
            self._stats.is_capturing = False

        logger.info("ScreenCaptureManager stopped")

    def _capture_worker(self) -> None:
        """High-precision timed worker thread grabbing frames at target FPS."""
        frame_interval = 1.0 / self.target_fps
        fps_timer = time.perf_counter()
        fps_count = 0

        while not self._stop_event.is_set():
            t_start = time.perf_counter()

            if self._backend:
                try:
                    frame = self._backend.grab_frame(downsample_size=self.downsample_size)
                    t_grab = (time.perf_counter() - t_start) * 1000.0

                    if frame is not None and frame.size > 0:
                        fps_count += 1
                        now = time.perf_counter()
                        with self._stats_lock:
                            self._stats.frames_captured += 1
                            self._stats.capture_time_ms = t_grab

                        if self.on_frame:
                            try:
                                self.on_frame(frame, now)
                            except Exception as cb_exc:
                                logger.error("Error in on_frame callback: %s", cb_exc)
                    else:
                        with self._stats_lock:
                            self._stats.dropped_frames += 1
                except Exception as exc:
                    logger.debug("Capture loop iteration error: %s", exc)
                    with self._stats_lock:
                        self._stats.dropped_frames += 1

            # Update FPS estimate once per second
            t_now = time.perf_counter()
            if t_now - fps_timer >= 1.0:
                elapsed = t_now - fps_timer
                with self._stats_lock:
                    self._stats.actual_fps = fps_count / elapsed
                fps_count = 0
                fps_timer = t_now

            # Precise frame interval sleep
            t_elapsed = time.perf_counter() - t_start
            sleep_needed = frame_interval - t_elapsed
            if sleep_needed > 0.002:
                time.sleep(sleep_needed)
