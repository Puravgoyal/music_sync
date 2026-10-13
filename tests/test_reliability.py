"""Regression tests for Phase 4 Reliability Audit: startup rollback, state restoration, and thread safety."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audio.analyzer import AudioMetrics
from src.audio.capture import CaptureStats
from src.sync.engine import MusicSyncEngine
from src.wiz.controller import BulbCapabilities, BulbState, WizBulbController, WizConnectionError


def _make_dummy_metrics() -> AudioMetrics:
    return AudioMetrics(
        rms=0.4,
        loudness=0.5,
        bass=0.7,
        mid=0.3,
        treble=0.2,
        spectral_flux=0.1,
        is_onset=False,
        onset_strength=0.0,
        is_silent=False,
    )


def _make_dummy_stats() -> CaptureStats:
    return CaptureStats(
        sample_rate=48000,
        buffer_size=1024,
        buffer_duration_ms=21.3,
        fps=46.8,
        analysis_time_ms=0.3,
        estimated_latency_ms=21.6,
        frames_processed=10,
        dropped_frames=0,
    )


@pytest.mark.asyncio
class TestTransactionalStartupRollback:
    """Fix A: Verify failure at any initialization stage safely releases acquired resources and allows clean retry."""

    @patch("src.sync.engine.WizBulbController")
    async def test_startup_failure_at_controller_connection(self, mock_ctrl_cls: MagicMock) -> None:
        mock_ctrl = MagicMock(spec=WizBulbController)
        mock_ctrl.connect = AsyncMock(side_effect=WizConnectionError("Unreachable bulb"))
        mock_ctrl.disconnect = AsyncMock()
        mock_ctrl_cls.return_value = mock_ctrl

        engine = MusicSyncEngine(bulb_ip="192.168.1.99", dry_run=False)
        with pytest.raises(WizConnectionError):
            await engine.start()

        assert not engine.is_running
        assert engine.capture is None
        assert engine.scheduler is None
        mock_ctrl.disconnect.assert_awaited()

    @patch("src.sync.engine.BulbCommandScheduler")
    @patch("src.sync.engine.WizBulbController")
    async def test_startup_failure_at_scheduler_stage(
        self, mock_ctrl_cls: MagicMock, mock_sched_cls: MagicMock
    ) -> None:
        mock_ctrl = MagicMock(spec=WizBulbController)
        mock_ctrl.is_connected = True
        mock_ctrl.is_on = False
        mock_ctrl.connect = AsyncMock()
        mock_ctrl.disconnect = AsyncMock()
        mock_ctrl.turn_on = AsyncMock()
        mock_ctrl.restore_state = AsyncMock()
        saved_state = BulbState(is_on=False)
        mock_ctrl.get_state = AsyncMock(return_value=saved_state)
        mock_ctrl_cls.return_value = mock_ctrl

        mock_sched = MagicMock()
        mock_sched.start = AsyncMock(side_effect=RuntimeError("Scheduler start failed"))
        mock_sched.stop = AsyncMock()
        mock_sched_cls.return_value = mock_sched

        engine = MusicSyncEngine(bulb_ip="192.168.1.4", dry_run=False, restore_state=True)
        with pytest.raises(RuntimeError, match="Scheduler start failed"):
            await engine.start()

        assert not engine.is_running
        assert engine.capture is None
        # Scheduler stopped, bulb restored to OFF, controller disconnected
        mock_sched.stop.assert_awaited()
        mock_ctrl.restore_state.assert_awaited_with(saved_state)
        mock_ctrl.disconnect.assert_awaited()

    @patch("src.sync.engine.AudioCapture")
    @patch("src.sync.engine.BulbCommandScheduler")
    @patch("src.sync.engine.WizBulbController")
    async def test_startup_failure_at_audio_capture_permits_clean_retry(
        self, mock_ctrl_cls: MagicMock, mock_sched_cls: MagicMock, mock_capture_cls: MagicMock
    ) -> None:
        mock_ctrl = MagicMock(spec=WizBulbController)
        mock_ctrl.is_connected = True
        mock_ctrl.is_on = True
        mock_ctrl.connect = AsyncMock()
        mock_ctrl.disconnect = AsyncMock()
        mock_ctrl.turn_on = AsyncMock()
        mock_ctrl.restore_state = AsyncMock()
        saved_state = BulbState(is_on=True, brightness=100, active_mode="dimming")
        mock_ctrl.get_state = AsyncMock(return_value=saved_state)
        mock_ctrl_cls.return_value = mock_ctrl

        mock_sched = MagicMock()
        mock_sched.start = AsyncMock()
        mock_sched.stop = AsyncMock()
        mock_sched_cls.return_value = mock_sched

        # First attempt: AudioCapture fails
        mock_capture_fail = MagicMock()
        mock_capture_fail.start.side_effect = OSError("WASAPI loopback device inaccessible")
        mock_capture_fail.stop = MagicMock()
        mock_capture_cls.return_value = mock_capture_fail

        engine = MusicSyncEngine(bulb_ip="192.168.1.4", dry_run=False, restore_state=True)
        with pytest.raises(OSError, match="WASAPI loopback"):
            await engine.start()

        assert not engine.is_running
        mock_sched.stop.assert_awaited()
        mock_ctrl.disconnect.assert_awaited()

        # Second attempt: AudioCapture succeeds -> Clean retry succeeds
        mock_capture_success = MagicMock()
        mock_capture_cls.return_value = mock_capture_success
        await engine.start()

        assert engine.is_running
        mock_capture_success.start.assert_called_once()
        await engine.stop()
        assert not engine.is_running


@pytest.mark.asyncio
class TestAccurateBulbStateRestoration:
    """Fix B: Verify restoration accurately identifies and restores active lighting mode."""

    async def test_restore_off_bulb(self) -> None:
        ctrl = WizBulbController("192.168.1.4")
        ctrl._is_connected = True
        ctrl._light = MagicMock()
        ctrl._safe_call = AsyncMock()

        state = BulbState(is_on=False, active_mode="off")
        await ctrl.restore_state(state)

        ctrl._safe_call.assert_awaited_once()

    async def test_restore_rgb_mode(self) -> None:
        ctrl = WizBulbController("192.168.1.4")
        ctrl._is_connected = True
        ctrl._light = MagicMock()
        ctrl.capabilities = BulbCapabilities(supports_rgb=True)
        ctrl.set_light_state = AsyncMock()

        state = BulbState(
            is_on=True,
            rgb=(255, 100, 50),
            brightness=200,
            colortemp=None,
            active_mode="rgb",
        )
        await ctrl.restore_state(state)

        ctrl.set_light_state.assert_awaited_once_with(255, 100, 50, 200)

    async def test_restore_colortemp_mode(self) -> None:
        ctrl = WizBulbController("192.168.1.4")
        ctrl._is_connected = True
        ctrl._light = MagicMock()
        ctrl.capabilities = BulbCapabilities(supports_colortemp=True)
        ctrl._safe_call = AsyncMock()

        state = BulbState(
            is_on=True,
            colortemp=3200,
            brightness=180,
            rgb=None,
            active_mode="colortemp",
        )
        await ctrl.restore_state(state)

        ctrl._safe_call.assert_awaited_once()

    async def test_restore_scene_mode(self) -> None:
        ctrl = WizBulbController("192.168.1.4")
        ctrl._is_connected = True
        ctrl._light = MagicMock()
        ctrl._safe_call = AsyncMock()

        state = BulbState(
            is_on=True,
            scene_id=12,  # e.g., Sunset scene
            brightness=150,
            active_mode="scene",
        )
        await ctrl.restore_state(state)

        ctrl._safe_call.assert_awaited_once()

    async def test_restore_white_channel_mode(self) -> None:
        ctrl = WizBulbController("192.168.1.4")
        ctrl._is_connected = True
        ctrl._light = MagicMock()
        ctrl._safe_call = AsyncMock()

        state = BulbState(
            is_on=True,
            warm_white=128,
            cold_white=0,
            brightness=255,
            active_mode="white",
        )
        await ctrl.restore_state(state)

        ctrl._safe_call.assert_awaited_once()


class TestThreadSafetyAndConcurrency:
    """Fix C: Verify thread safety across concurrent callbacks, GUI changes, and status snapshots."""

    def test_concurrent_effect_switching_and_audio_processing(self) -> None:
        engine = MusicSyncEngine(dry_run=True)
        metrics = _make_dummy_metrics()
        stats = _make_dummy_stats()
        stop_threads = threading.Event()

        errors = []

        def audio_worker() -> None:
            try:
                while not stop_threads.is_set():
                    engine._handle_audio_metrics(metrics, stats)
            except Exception as e:
                errors.append(e)

        def gui_worker() -> None:
            effects = ["spectrum", "beat", "bass", "smooth", "ambient"]
            try:
                for i in range(100):
                    engine.set_effect(effects[i % len(effects)])
                    status = engine.get_status()
                    assert status.target_state is not None
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=audio_worker)
        t2 = threading.Thread(target=gui_worker)

        t1.start()
        t2.start()

        t2.join(timeout=3.0)
        stop_threads.set()
        t1.join(timeout=3.0)

        assert not errors, f"Concurrency errors encountered: {errors}"
