"""Unit and integration tests for screen capture backends, monitor enumeration, and fallbacks."""

import time
import numpy as np
import pytest

from src.screen.capture import (
    CaptureStats,
    MockCaptureBackend,
    ScreenCaptureManager,
)
from src.screen.cinematic import CaptureFallbackManager, CaptureHealth
from src.screen.devices import ScreenMonitor, get_available_monitors, get_monitor_by_index


class TestScreenDevices:
    """Verify monitor enumeration, coordinates, and DPI scaling."""

    def test_get_available_monitors_returns_valid_displays(self) -> None:
        monitors = get_available_monitors()
        assert len(monitors) >= 1
        m0 = monitors[0]
        assert isinstance(m0, ScreenMonitor)
        assert m0.width > 0
        assert m0.height > 0
        assert m0.device_pixel_ratio >= 1.0
        assert isinstance(m0.name, str) and len(m0.name) > 0

    def test_get_monitor_by_index_fallback(self) -> None:
        # Requesting out-of-range index should fall back to a valid monitor
        mon = get_monitor_by_index(999)
        assert mon is not None
        assert mon.width > 0
        assert mon.height > 0


class TestMockCaptureBackend:
    """Verify downsampling and frame grabbing on mock capture backend."""

    def test_mock_backend_downsamples_correctly(self) -> None:
        # Create full 1920x1080 mock frame
        raw_frame = np.full((1080, 1920, 3), [120, 80, 240], dtype=np.uint8)
        backend = MockCaptureBackend(initial_frame=raw_frame)
        assert backend.start(monitor_index=0)

        # Grab with standard 64x36 downsample
        downsampled = backend.grab_frame(downsample_size=(64, 36))
        assert downsampled is not None
        assert downsampled.shape == (36, 64, 3)
        assert downsampled.dtype == np.uint8
        assert np.all(downsampled == [120, 80, 240])

        backend.stop()
        assert backend.grab_frame() is None


class TestScreenCaptureManager:
    """Verify background capture worker, frame callback dispatch, and clean termination."""

    def test_capture_manager_dispatches_frames(self) -> None:
        mock_backend = MockCaptureBackend(initial_frame=np.full((720, 1280, 3), [200, 100, 50], dtype=np.uint8))
        frames_received = []

        def on_frame_cb(frame: np.ndarray, timestamp: float) -> None:
            frames_received.append((frame, timestamp))

        manager = ScreenCaptureManager(
            target_fps=15.0,
            downsample_size=(64, 36),
            on_frame=on_frame_cb,
            custom_backend=mock_backend,
        )

        assert manager.start()
        assert manager.is_running

        # Allow worker thread to capture several frames (~200ms at 15 FPS = ~3 frames)
        time.sleep(0.25)

        manager.stop()
        assert not manager.is_running
        assert len(frames_received) >= 2

        frame0, ts0 = frames_received[0]
        assert frame0.shape == (36, 64, 3)
        assert ts0 > 0.0

        stats = manager.stats
        assert stats.frames_captured >= 2
        assert not stats.is_capturing


class TestCaptureFallbackManager:
    """Verify stale frame detection and gradual fade towards safe ambient white."""

    def test_healthy_frame_retention(self) -> None:
        mgr = CaptureFallbackManager(stale_timeout_s=1.0, safe_fallback_rgb=(255, 214, 170), min_brightness=25)
        mgr.record_frame(rgb=(200, 50, 50), brightness=180, now=10.0)

        rgb, b, is_fallback = mgr.get_state_or_fallback(now=10.5)
        assert not is_fallback
        assert rgb == (200, 50, 50)
        assert b == 180
        assert mgr.health == CaptureHealth.OK

    def test_stale_frame_transition_and_fade(self) -> None:
        mgr = CaptureFallbackManager(
            stale_timeout_s=1.0,
            fade_duration_s=2.0,
            safe_fallback_rgb=(255, 200, 150),
            min_brightness=25,
        )
        mgr.record_frame(rgb=(0, 0, 255), brightness=225, now=10.0)

        # At t=11.1s (0.1s past stale timeout): is_fallback becomes True
        rgb_early, b_early, is_fallback = mgr.get_state_or_fallback(now=11.1)
        assert is_fallback
        assert mgr.health == CaptureHealth.STALE

        # At t=13.1s (past fade duration): fully decayed to safe fallback and min_brightness
        rgb_decayed, b_decayed, is_fallback = mgr.get_state_or_fallback(now=13.1)
        assert is_fallback
        assert rgb_decayed == (255, 200, 150)
        assert b_decayed == 25


class TestReliabilityAndThreadAffinity:
    """Targeted reliability tests for Qt thread affinity, single init, fallback, and black frames."""

    def test_qt_screen_capture_thread_affinity(self, qapp) -> None:
        """Verify QScreen.grabWindow executes strictly on the Qt GUI/main thread."""
        import threading
        from src.screen.capture import QtCaptureBackend

        backend = QtCaptureBackend()
        assert backend.start(monitor_index=0)

        # Grab frame
        frame = backend.grab_frame(downsample_size=(64, 36))
        assert frame is not None
        assert frame.shape == (36, 64, 3)

        # Thread check: must match GUI thread where qapp runs
        gui_thread_id = threading.get_ident()
        assert backend.last_grab_thread_id is not None
        assert backend.last_grab_thread_id == gui_thread_id

        backend.stop()

    def test_dxcam_single_initialization_and_fallback(self) -> None:
        """Verify DXcam is initialized once and falls back cleanly without double init."""
        from unittest.mock import patch
        from src.screen.capture import BackendState, DXCamCaptureBackend, QtCaptureBackend, ScreenCaptureManager

        init_counter = {"count": 0}

        def mock_dxcam_start(self, monitor_index=0):
            init_counter["count"] += 1
            return False  # Simulate failure

        with patch.object(DXCamCaptureBackend, "start", mock_dxcam_start):
            mgr = ScreenCaptureManager(preferred_backend="auto")
            assert mgr.start()
            # DXcam should have been tried exactly once
            assert init_counter["count"] == 1
            # Fallback to QtCaptureBackend succeeded
            assert isinstance(mgr.backend, QtCaptureBackend)
            assert mgr.state == BackendState.RUNNING
            mgr.stop()

    def test_unchanged_frames_handled_as_healthy_static_content(self) -> None:
        """Verify static screen content is not classified as an error."""
        from src.screen.capture import FrameStatus

        mock_backend = MockCaptureBackend(initial_frame=np.full((36, 64, 3), [10, 20, 30], dtype=np.uint8))
        mgr = ScreenCaptureManager(
            target_fps=20.0,
            downsample_size=(64, 36),
            custom_backend=mock_backend,
        )
        assert mgr.start()
        time.sleep(0.08)

        # Now simulate screen static (frame=None, last_status=UNCHANGED)
        mock_backend.set_frame(None)
        mock_backend.last_status = FrameStatus.UNCHANGED
        time.sleep(0.12)

        assert mgr.health == CaptureHealth.OK
        mgr.stop()

    def test_stale_frame_notification_on_prolonged_failure(self) -> None:
        """Verify missing frames for > stale_timeout_s dispatches None to trigger analyzer fallback."""
        from src.screen.capture import FrameStatus

        none_received = []

        def on_frame(f, ts):
            if f is None:
                none_received.append(ts)

        mock_backend = MockCaptureBackend(initial_frame=None)
        mock_backend.last_status = FrameStatus.ERROR

        mgr = ScreenCaptureManager(
            target_fps=20.0,
            downsample_size=(64, 36),
            on_frame=on_frame,
            custom_backend=mock_backend,
            stale_timeout_s=0.15,
        )
        assert mgr.start()
        time.sleep(0.35)

        assert mgr.health == CaptureHealth.STALE
        assert len(none_received) >= 1
        mgr.stop()

    def test_black_cinematic_frames_are_healthy(self) -> None:
        """Verify genuine black movie frames are classified as healthy capture, not error."""
        from src.screen.analyzer import ScreenColorAnalyzer

        analyzer = ScreenColorAnalyzer()
        black_frame = np.zeros((36, 64, 3), dtype=np.uint8)

        state = analyzer.process_frame(black_frame, timestamp=time.perf_counter())
        assert state is not None
        assert state.brightness == analyzer.settings.min_brightness
        # Confirm capture health is OK
        assert analyzer._fallback_mgr.health == CaptureHealth.OK
