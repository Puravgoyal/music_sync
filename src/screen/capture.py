"""Windows screen capture engine with multi-monitor support, downsampling, and robust fallback."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple
import numpy as np

from src.screen.cinematic import CaptureHealth
from src.screen.devices import ScreenMonitor, get_available_monitors, get_monitor_by_index

logger = logging.getLogger(__name__)


class BackendState(Enum):
    """Lifecycle states for capture backends."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class FrameStatus(Enum):
    """Per-frame capture status outcomes."""

    NEW_FRAME = "new_frame"
    UNCHANGED = "unchanged"
    TIMEOUT = "timeout"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class CaptureStats:
    """Telemetry statistics for screen capture thread."""

    actual_fps: float = 0.0
    frames_captured: int = 0
    dropped_frames: int = 0
    capture_time_ms: float = 0.0
    is_capturing: bool = False
    backend_name: str = "None"
    backend_state: str = "created"
    monitor_name: str = "Default"
    health: str = "OK"
    last_valid_frame_time: float = 0.0
    consecutive_errors: int = 0


class BaseCaptureBackend(ABC):
    """Abstract interface for screen capture implementations."""

    name: str = "Base"

    def __init__(self) -> None:
        self.state: BackendState = BackendState.CREATED
        self.last_status: FrameStatus = FrameStatus.UNCHANGED

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


def ensure_default_desktop() -> None:
    """Ensure current thread is attached to the interactive Windows 'Default' desktop."""
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass


_qt_grabber_instance = None
_qt_grabber_lock = threading.Lock()


class QtScreenGrabber:
    """QObject component executing QScreen.grabWindow solely on the Qt GUI/main thread."""

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, QTimer, Slot, QThread

        class _GrabberQObject(QObject):
            def __init__(self, parent_wrapper: "QtScreenGrabber") -> None:
                super().__init__()
                self._w = parent_wrapper
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._on_timer_tick)

            @Slot()
            def _start_slot(self) -> None:
                self._w._do_start()

            @Slot()
            def _stop_slot(self) -> None:
                self._w._do_stop()

            @Slot()
            def _grab_single_slot(self) -> None:
                self._w._do_grab(self._w._dw, self._w._dh)

            def _on_timer_tick(self) -> None:
                self._w._do_grab(self._w._dw, self._w._dh)

        self._QObjectCls = _GrabberQObject
        self._qobj: Optional[QObject] = None
        self._lock = threading.Lock()

        self._screen = None
        self._dw: int = 64
        self._dh: int = 36
        self._fps: float = 12.0

        self._latest_frame: Optional[np.ndarray] = None
        self._latest_timestamp: float = 0.0
        self._frame_id: int = 0
        self._last_grab_thread_id: Optional[int] = None
        self._is_active: bool = False

    def _ensure_qobject(self) -> bool:
        """Ensure the internal QObject exists on the QApplication GUI thread."""
        ensure_default_desktop()
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QThread

            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv if sys.argv else ["WiZScreenCapture"])

            if self._qobj is None:
                # Must be created on or moved to app.thread()
                current_thread = QThread.currentThread()
                app_thread = app.thread()
                if current_thread == app_thread:
                    self._qobj = self._QObjectCls(self)
                else:
                    # Created in current thread, must move to GUI thread
                    self._qobj = self._QObjectCls(self)
                    self._qobj.moveToThread(app_thread)
            return True
        except Exception as exc:
            logger.warning("Could not instantiate QtScreenGrabber QObject: %s", exc)
            return False

    def _do_start(self, mon_idx: Optional[int] = None, fps: Optional[float] = None, dw: Optional[int] = None, dh: Optional[int] = None) -> None:
        """Executes strictly on Qt GUI thread."""
        ensure_default_desktop()
        from PySide6.QtGui import QGuiApplication
        import threading

        self._last_grab_thread_id = threading.get_ident()
        if mon_idx is not None:
            self._mon_idx = mon_idx
        if fps is not None:
            self._fps = fps
        if dw is not None:
            self._dw = dw
        if dh is not None:
            self._dh = dh

        m_idx = getattr(self, "_mon_idx", 0)
        screens = QGuiApplication.screens()
        if not screens:
            logger.warning("QtScreenGrabber: No QGuiApplication screens found")
            return

        if 0 <= m_idx < len(screens):
            self._screen = screens[m_idx]
        else:
            self._screen = QGuiApplication.primaryScreen() or screens[0]

        interval_ms = max(20, int(round(1000.0 / max(1.0, self._fps))))
        if self._qobj and hasattr(self._qobj, "_timer"):
            self._qobj._timer.start(interval_ms)
        self._is_active = True
        logger.info(
            "QtScreenGrabber started on screen '%s' at %d ms interval (Thread ID: %d)",
            self._screen.name(),
            interval_ms,
            self._last_grab_thread_id,
        )

    def _do_stop(self) -> None:
        """Executes strictly on Qt GUI thread."""
        if self._qobj and hasattr(self._qobj, "_timer"):
            self._qobj._timer.stop()
        self._is_active = False
        self._screen = None

    def _do_grab(self, dw: int, dh: int) -> None:
        """Executes strictly on Qt GUI thread to grab QScreen pixmap."""
        ensure_default_desktop()
        if self._screen is None:
            return

        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
            import threading

            self._last_grab_thread_id = threading.get_ident()
            pixmap = self._screen.grabWindow(0)
            if pixmap.isNull():
                return

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
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl // 4, 4))
            rgb_frame = np.ascontiguousarray(arr[:h, :w, :3])

            with self._lock:
                self._latest_frame = rgb_frame
                self._latest_timestamp = time.perf_counter()
                self._frame_id += 1
        except Exception as exc:
            logger.debug("QtScreenGrabber._do_grab error: %s", exc)

    def start(self, mon_idx: int, fps: float, dw: int, dh: int) -> bool:
        """Thread-safe start ensuring Qt GUI thread handles the operation."""
        if not self._ensure_qobject():
            return False

        from PySide6.QtCore import QMetaObject, Qt, QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False

        self._mon_idx = mon_idx
        self._fps = fps
        self._dw = dw
        self._dh = dh

        if QThread.currentThread() == app.thread():
            self._do_start(mon_idx, fps, dw, dh)
        else:
            QMetaObject.invokeMethod(
                self._qobj,
                "_start_slot",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        return self._is_active

    def stop(self) -> None:
        """Thread-safe stop ensuring Qt GUI thread handles the operation."""
        if self._qobj is None:
            return

        from PySide6.QtCore import QMetaObject, Qt, QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            self._do_stop()
        elif app is not None:
            QMetaObject.invokeMethod(
                self._qobj,
                "_stop_slot",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        else:
            self._do_stop()

    def grab_single_frame(self, dw: int, dh: int) -> Optional[np.ndarray]:
        """Trigger an on-demand frame capture on the GUI thread."""
        if not self._ensure_qobject():
            return None

        from PySide6.QtCore import QMetaObject, Qt, QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None

        self._dw = dw
        self._dh = dh

        if QThread.currentThread() == app.thread():
            self._do_grab(dw, dh)
        else:
            QMetaObject.invokeMethod(
                self._qobj,
                "_grab_single_slot",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def get_latest_frame(self) -> Tuple[Optional[np.ndarray], float, int]:
        """Thread-safe read of the latest frame captured by the GUI thread."""
        with self._lock:
            return (
                self._latest_frame.copy() if self._latest_frame is not None else None,
                self._latest_timestamp,
                self._frame_id,
            )

    @property
    def last_grab_thread_id(self) -> Optional[int]:
        return self._last_grab_thread_id


def get_shared_qt_grabber() -> QtScreenGrabber:
    """Return shared singleton QtScreenGrabber instance."""
    global _qt_grabber_instance
    with _qt_grabber_lock:
        if _qt_grabber_instance is None:
            _qt_grabber_instance = QtScreenGrabber()
        return _qt_grabber_instance


class QtCaptureBackend(BaseCaptureBackend):
    """Reliable screen capture using Qt platform integration with DWM and GUI thread affinity."""

    name = "Qt Desktop Capture"

    def __init__(self, grabber: Optional[QtScreenGrabber] = None) -> None:
        super().__init__()
        self.monitor_index: int = 0
        self._grabber = grabber or get_shared_qt_grabber()
        self._last_read_frame_id: int = -1

    def start(self, monitor_index: int = 0) -> bool:
        if self.state == BackendState.RUNNING:
            return True
        self.state = BackendState.STARTING
        self.monitor_index = monitor_index

        success = self._grabber.start(
            mon_idx=monitor_index,
            fps=15.0,
            dw=64,
            dh=36,
        )
        if success:
            self.state = BackendState.RUNNING
            self.last_status = FrameStatus.NEW_FRAME
            logger.info("QtCaptureBackend started successfully (State: RUNNING)")
            return True
        else:
            self.state = BackendState.FAILED
            self.last_status = FrameStatus.ERROR
            logger.warning("QtCaptureBackend failed to start (State: FAILED)")
            return False

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if self.state != BackendState.RUNNING:
            return None

        dw, dh = downsample_size
        frame, ts, f_id = self._grabber.get_latest_frame()

        if frame is None or f_id == self._last_read_frame_id:
            # If timer hasn't ticked yet or on-demand is needed, try single grab
            if frame is None:
                frame = self._grabber.grab_single_frame(dw, dh)
                if frame is not None:
                    self.last_status = FrameStatus.NEW_FRAME
                    return frame
            self.last_status = FrameStatus.UNCHANGED
            return frame  # Return cached frame without considering it a failure

        self._last_read_frame_id = f_id
        self.last_status = FrameStatus.NEW_FRAME
        return frame

    def stop(self) -> None:
        if self.state == BackendState.STOPPED:
            return
        self.state = BackendState.STOPPING
        try:
            self._grabber.stop()
        except Exception as exc:
            logger.debug("Error stopping QtScreenGrabber: %s", exc)
        self.state = BackendState.STOPPED
        logger.info("QtCaptureBackend stopped cleanly")

    @property
    def last_grab_thread_id(self) -> Optional[int]:
        return self._grabber.last_grab_thread_id


# -------------------------------------------------------------------------
# DXcam (DirectX Desktop Duplication Backend)
# -------------------------------------------------------------------------

class DXCamCaptureBackend(BaseCaptureBackend):
    """High-performance DirectX Desktop Duplication backend using DXcam."""

    name = "DXcam (Desktop Duplication)"

    def __init__(self) -> None:
        super().__init__()
        self.monitor_index: int = 0
        self._camera = None
        self._last_frame: Optional[np.ndarray] = None

    def start(self, monitor_index: int = 0) -> bool:
        if self.state == BackendState.RUNNING:
            return True
        self.state = BackendState.STARTING
        self.monitor_index = monitor_index

        try:
            import dxcam

            self._camera = dxcam.create(output_idx=monitor_index)
            if self._camera is None:
                raise RuntimeError(f"dxcam.create returned None for output {monitor_index}")

            # Trial grab to verify DXcam backend can actually produce frames (e.g. cv2 is present, DXGI surface is accessible)
            trial = self._camera.grab()
            self._last_frame = None

            self.state = BackendState.RUNNING
            self.last_status = FrameStatus.NEW_FRAME
            logger.info("DXCamCaptureBackend initialized on output %d", monitor_index)
            return True
        except Exception as exc:
            logger.warning("DXcam initialization failed: %s", exc)
            if self._camera is not None:
                try:
                    import dxcam
                    if hasattr(dxcam, "_cameras"):
                        dxcam._cameras.clear()
                except Exception:
                    pass
            self._camera = None
            self.state = BackendState.FAILED
            self.last_status = FrameStatus.ERROR
            return False

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if self.state != BackendState.RUNNING or self._camera is None:
            return None

        try:
            frame = self._camera.grab()
            if frame is None:
                # DXcam returns None when display hasn't updated (unchanged screen content)
                self.last_status = FrameStatus.UNCHANGED
                return self._last_frame

            h, w, _ = frame.shape
            dw, dh = downsample_size
            step_y = max(1, h // dh)
            step_x = max(1, w // dw)
            downsampled = np.ascontiguousarray(frame[::step_y, ::step_x, :3][:dh, :dw, :])
            self._last_frame = downsampled
            self.last_status = FrameStatus.NEW_FRAME
            return downsampled
        except Exception as exc:
            logger.debug("DXcam grab error: %s", exc)
            self.last_status = FrameStatus.ERROR
            return None

    def stop(self) -> None:
        if self.state == BackendState.STOPPED:
            return
        self.state = BackendState.STOPPING
        if self._camera:
            try:
                import dxcam
                if hasattr(dxcam, "_cameras"):
                    dxcam._cameras.clear()
            except Exception:
                pass
            try:
                del self._camera
            except Exception:
                pass
            self._camera = None
        self._last_frame = None
        self.state = BackendState.STOPPED
        logger.info("DXCamCaptureBackend stopped")


# -------------------------------------------------------------------------
# Mock Test Backend
# -------------------------------------------------------------------------

class MockCaptureBackend(BaseCaptureBackend):
    """Synthetic test backend for injecting controlled test frames."""

    name = "Mock Capture Backend"

    def __init__(self, initial_frame: Optional[np.ndarray] = None) -> None:
        super().__init__()
        self.monitor_index: int = 0
        self._frame: Optional[np.ndarray] = initial_frame

    def set_frame(self, frame: Optional[np.ndarray]) -> None:
        self._frame = frame

    def start(self, monitor_index: int = 0) -> bool:
        self.monitor_index = monitor_index
        self.state = BackendState.RUNNING
        self.last_status = FrameStatus.NEW_FRAME
        return True

    def grab_frame(self, downsample_size: Tuple[int, int] = (64, 36)) -> Optional[np.ndarray]:
        if self.state != BackendState.RUNNING:
            return None

        if self._frame is None:
            self.last_status = FrameStatus.TIMEOUT
            return None

        dw, dh = downsample_size
        h, w, _ = self._frame.shape
        step_y = max(1, h // dh)
        step_x = max(1, w // dw)
        downsampled = self._frame[::step_y, ::step_x, :3][:dh, :dw, :]
        self.last_status = FrameStatus.NEW_FRAME
        return np.ascontiguousarray(downsampled)

    def stop(self) -> None:
        self.state = BackendState.STOPPED


# -------------------------------------------------------------------------
# ScreenCaptureManager
# -------------------------------------------------------------------------

class ScreenCaptureManager:
    """Coordinates screen capture at controlled FPS (10-15 Hz) with safe fallbacks and real health tracking."""

    def __init__(
        self,
        monitor_index: int = 0,
        target_fps: float = 12.0,
        downsample_size: Tuple[int, int] = (64, 36),
        on_frame: Optional[Callable[[Optional[np.ndarray], float], None]] = None,
        preferred_backend: str = "auto",  # 'auto', 'dxcam', 'qt', 'mock'
        custom_backend: Optional[BaseCaptureBackend] = None,
        stale_timeout_s: float = 1.2,
    ) -> None:
        self.monitor_index = monitor_index
        self.target_fps = max(5.0, min(30.0, float(target_fps)))
        self.downsample_size = downsample_size
        self.on_frame = on_frame
        self.preferred_backend = preferred_backend
        self._custom_backend = custom_backend
        self.stale_timeout_s = stale_timeout_s

        self._backend: Optional[BaseCaptureBackend] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats_lock = threading.Lock()

        self._stats = CaptureStats()
        self._health: CaptureHealth = CaptureHealth.OK
        self._last_valid_frame_time: float = 0.0
        self._last_valid_frame: Optional[np.ndarray] = None
        self._consecutive_errors: int = 0
        self.state: BackendState = BackendState.CREATED

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    @property
    def health(self) -> CaptureHealth:
        return self._health

    @property
    def backend(self) -> Optional[BaseCaptureBackend]:
        return self._backend

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
                backend_state=self._stats.backend_state,
                monitor_name=self._stats.monitor_name,
                health=self._health.name,
                last_valid_frame_time=self._last_valid_frame_time,
                consecutive_errors=self._consecutive_errors,
            )

    def _get_candidate_backends(self) -> List[BaseCaptureBackend]:
        """Return candidate backends for initial attempt and fallback WITHOUT initializing them."""
        if self._custom_backend:
            return [self._custom_backend]

        pref = self.preferred_backend.lower()
        if pref == "mock":
            return [MockCaptureBackend()]
        elif pref == "dxcam":
            return [DXCamCaptureBackend(), QtCaptureBackend()]
        elif pref == "qt":
            return [QtCaptureBackend()]
        else:
            # 'auto': Attempt DXcam first, fallback cleanly to QtCaptureBackend
            return [DXCamCaptureBackend(), QtCaptureBackend()]

    def start(self) -> bool:
        """Start the background capture loop with clean single-initialization and fallback."""
        ensure_default_desktop()
        if self.is_running:
            logger.warning("ScreenCaptureManager is already running")
            return True

        self._stop_event.clear()
        candidates = self._get_candidate_backends()

        started_backend: Optional[BaseCaptureBackend] = None
        for candidate in candidates:
            logger.info("Attempting to initialize capture backend: %s...", candidate.name)
            try:
                if candidate.start(self.monitor_index):
                    started_backend = candidate
                    break
                else:
                    logger.warning("Backend %s start returned False. Releasing...", candidate.name)
                    candidate.stop()
            except Exception as exc:
                logger.warning("Backend %s threw exception during start: %s. Releasing...", candidate.name, exc)
                try:
                    candidate.stop()
                except Exception:
                    pass

        if started_backend is None:
            self.state = BackendState.FAILED
            self._health = CaptureHealth.ERROR
            logger.error("All candidate screen capture backends failed to start")
            return False

        self._backend = started_backend
        self.state = BackendState.RUNNING
        self._health = CaptureHealth.OK
        self._consecutive_errors = 0
        self._last_valid_frame_time = time.perf_counter()

        mon = get_monitor_by_index(self.monitor_index)
        with self._stats_lock:
            self._stats = CaptureStats(
                is_capturing=True,
                backend_name=started_backend.name,
                backend_state=started_backend.state.value,
                monitor_name=mon.name,
                health="OK",
                last_valid_frame_time=self._last_valid_frame_time,
            )

        self._thread = threading.Thread(
            target=self._capture_worker,
            name="ScreenCaptureWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "ScreenCaptureManager started using '%s' for monitor %d",
            started_backend.name,
            self.monitor_index,
        )
        return True

    def stop(self) -> None:
        """Cleanly stop background capture loop and release resources."""
        self.state = BackendState.STOPPING
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

        self.state = BackendState.STOPPED
        with self._stats_lock:
            self._stats.is_capturing = False
            self._stats.backend_state = BackendState.STOPPED.value

        logger.info("ScreenCaptureManager stopped cleanly")

    def _capture_worker(self) -> None:
        """High-precision timed worker thread grabbing frames at target FPS with health tracking."""
        ensure_default_desktop()
        frame_interval = 1.0 / self.target_fps
        fps_timer = time.perf_counter()
        fps_count = 0

        while not self._stop_event.is_set():
            t_start = time.perf_counter()
            frame: Optional[np.ndarray] = None
            t_grab = 0.0

            if self._backend:
                try:
                    frame = self._backend.grab_frame(downsample_size=self.downsample_size)
                    t_grab = (time.perf_counter() - t_start) * 1000.0
                except Exception as exc:
                    logger.debug("Backend grab exception: %s", exc)
                    frame = None

            now = time.perf_counter()

            # Process frame outcome
            if frame is not None and frame.size > 0:
                fps_count += 1
                self._consecutive_errors = 0
                self._last_valid_frame = frame
                self._last_valid_frame_time = now
                self._health = CaptureHealth.OK

                with self._stats_lock:
                    self._stats.frames_captured += 1
                    self._stats.capture_time_ms = t_grab
                    self._stats.health = "OK"
                    self._stats.consecutive_errors = 0
                    self._stats.last_valid_frame_time = now

                if self.on_frame:
                    try:
                        self.on_frame(frame, now)
                    except Exception as cb_exc:
                        logger.error("Error in on_frame callback: %s", cb_exc)

            else:
                # Frame is None: distinguish unchanged content vs error/disconnection
                status = self._backend.last_status if self._backend else FrameStatus.ERROR
                with self._stats_lock:
                    self._stats.dropped_frames += 1

                if status == FrameStatus.UNCHANGED and self._last_valid_frame is not None:
                    # Unchanged static screen content is NOT an error
                    fps_count += 1
                    self._health = CaptureHealth.OK
                    if self.on_frame:
                        try:
                            self.on_frame(self._last_valid_frame, now)
                        except Exception as cb_exc:
                            logger.error("Error in on_frame callback: %s", cb_exc)
                else:
                    self._consecutive_errors += 1
                    # Check monitor connectivity
                    monitors = get_available_monitors()
                    mon_indices = [m.index for m in monitors]
                    if self.monitor_index not in mon_indices and self.monitor_index != 0:
                        self._health = CaptureHealth.DISCONNECTED
                    elif (now - self._last_valid_frame_time) > self.stale_timeout_s:
                        self._health = CaptureHealth.STALE

                    # Automatic fallback if DXcam repeatedly fails during runtime
                    if (
                        self._consecutive_errors >= 5
                        and self._backend
                        and self._backend.name.startswith("DXcam")
                        and not self._stop_event.is_set()
                    ):
                        logger.warning("DXcam continuous errors detected. Attempting live fallback to QtCaptureBackend...")
                        try:
                            self._backend.stop()
                            fallback = QtCaptureBackend()
                            if fallback.start(self.monitor_index):
                                self._backend = fallback
                                self._consecutive_errors = 0
                                self._health = CaptureHealth.OK
                                logger.info("Live fallback to QtCaptureBackend succeeded")
                        except Exception as fb_exc:
                            logger.warning("Live fallback to Qt failed: %s", fb_exc)

                    # Notify analyzer of missing/stale frame so fallback logic executes
                    if self.on_frame and (now - self._last_valid_frame_time) > self.stale_timeout_s:
                        try:
                            self.on_frame(None, now)
                        except Exception as cb_exc:
                            logger.error("Error in on_frame (stale fallback) callback: %s", cb_exc)

            # Update FPS estimate once per second
            t_now = time.perf_counter()
            if t_now - fps_timer >= 1.0:
                elapsed = t_now - fps_timer
                with self._stats_lock:
                    self._stats.actual_fps = fps_count / elapsed
                fps_count = 0
                fps_timer = t_now

            # Precise interval sleep
            t_elapsed = time.perf_counter() - t_start
            sleep_needed = frame_interval - t_elapsed
            if sleep_needed > 0.002:
                time.sleep(sleep_needed)
