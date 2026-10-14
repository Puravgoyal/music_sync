"""Integration and lifecycle tests for UnifiedSyncEngine across Music, Screen, and Hybrid modes."""

from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest

from src.audio.analyzer import AudioMetrics
from src.screen.capture import MockCaptureBackend
from src.sync.engine import MusicSyncEngine, SyncMode, UnifiedSyncEngine
from src.sync.state import LightingState, RestorationResult
from src.wiz.controller import BulbCapabilities, BulbState, WizBulbController


def _make_dummy_metrics() -> AudioMetrics:
    return AudioMetrics(
        rms=0.4,
        loudness=0.6,
        bass=0.5,
        mid=0.3,
        treble=0.2,
        spectral_flux=0.1,
        is_onset=True,
        onset_strength=0.8,
        is_silent=False,
    )


@pytest.mark.asyncio
class TestUnifiedSyncEngine:
    """Verify single-scheduler lifecycle, mode switching, and state restoration."""

    async def test_screen_sync_engine_initialization(self) -> None:
        mock_backend = MockCaptureBackend()
        engine = UnifiedSyncEngine(
            dry_run=True,
            sync_mode=SyncMode.SCREEN,
            color_strategy="dominant",
            smoothing_preset="balanced",
            custom_capture_backend=mock_backend,
        )

        assert engine.sync_mode == SyncMode.SCREEN
        assert engine.color_strategy == "dominant"
        assert engine.smoothing_preset == "balanced"
        assert not engine.is_running

    async def test_screen_mode_lifecycle_and_scheduler_routing(self) -> None:
        green_frame = np.full((36, 64, 3), [10, 220, 50], dtype=np.uint8)
        mock_backend = MockCaptureBackend(initial_frame=green_frame)
        engine = UnifiedSyncEngine(
            dry_run=True,
            sync_mode=SyncMode.SCREEN,
            color_strategy="average",
            smoothing_preset="responsive",
            custom_capture_backend=mock_backend,
        )

        await engine.start()
        assert engine.is_running
        assert engine.screen_capture is not None
        assert engine.scheduler is not None
        assert engine.capture is None  # Audio capture not started in pure screen mode

        # Mock scheduler submit to spy on routed states
        engine._scheduler.submit = MagicMock()

        # Simulate incoming screen frames allowing smoother to converge
        t0 = 10.0
        for i in range(5):
            engine._handle_screen_frame(green_frame, timestamp=t0 + i * 0.05)

        # Scheduler must have received the state
        engine._scheduler.submit.assert_called()
        submitted_state = engine._scheduler.submit.call_args[0][0]
        assert isinstance(submitted_state, LightingState)
        # RGB must reflect the green frame (G > R and G > B)
        assert submitted_state.rgb[1] > submitted_state.rgb[0]
        assert submitted_state.rgb[1] > submitted_state.rgb[2]

        # Stop engine
        report = await engine.stop()
        assert not engine.is_running
        assert report.result in (RestorationResult.SUCCESS, RestorationResult.SKIPPED)

    async def test_hybrid_mode_lifecycle_and_fusion(self) -> None:
        blue_frame = np.full((36, 64, 3), [10, 50, 240], dtype=np.uint8)
        mock_backend = MockCaptureBackend(initial_frame=blue_frame)
        engine = UnifiedSyncEngine(
            dry_run=True,
            sync_mode=SyncMode.HYBRID,
            hybrid_type="cinematic",
            smoothing_preset="responsive",
            audio_contribution=0.5,
            custom_capture_backend=mock_backend,
        )

        with patch("src.sync.engine.AudioCapture") as mock_audio_cls:
            mock_audio = MagicMock()
            mock_audio_cls.return_value = mock_audio

            await engine.start()
            assert engine.is_running
            assert engine.screen_capture is not None
            assert engine.capture is not None
            assert engine.scheduler is not None

            # Spy on scheduler
            engine._scheduler.submit = MagicMock()

            # Process several screen frames to converge onto blue
            t0 = 1.0
            for i in range(5):
                engine._handle_screen_frame(blue_frame, timestamp=t0 + i * 0.05)

            # Process audio frame
            metrics = _make_dummy_metrics()
            engine._handle_audio_metrics(metrics, stats=None)

            engine._scheduler.submit.assert_called()
            fused_state = engine._scheduler.submit.call_args[0][0]
            # Primary principle: RGB is driven by screen video (blue dominant)
            assert fused_state.rgb[2] > fused_state.rgb[0]
            assert fused_state.rgb[2] > fused_state.rgb[1]

            await engine.stop()
            assert not engine.is_running

    async def test_single_scheduler_invariant(self) -> None:
        """Verify that exactly one scheduler is instantiated and transmitted through."""
        mock_backend = MockCaptureBackend()
        engine = UnifiedSyncEngine(dry_run=True, sync_mode=SyncMode.SCREEN, custom_capture_backend=mock_backend)
        await engine.start()

        sched1 = engine.scheduler
        assert sched1 is not None

        # Re-calling start does not spawn competing schedulers
        await engine.start()
        assert engine.scheduler is sched1

        await engine.stop()
        assert engine.scheduler is None

    async def test_screen_mode_bulb_state_restoration(self) -> None:
        initial_state = BulbState(
            is_on=True,
            brightness=120,
            active_mode="color",
            rgb=(100, 150, 200),
            raw_pilot={"result": {}},
        )

        mock_ctrl = MagicMock(spec=WizBulbController)
        mock_ctrl.is_connected = True
        mock_ctrl.is_on = True
        mock_ctrl.connect = AsyncMock()
        mock_ctrl.disconnect = AsyncMock()
        mock_ctrl.get_state = AsyncMock(return_value=initial_state)
        mock_ctrl.restore_state = AsyncMock()
        mock_ctrl.capabilities = BulbCapabilities(model="ESP25_SHRGB_01")

        mock_backend = MockCaptureBackend(initial_frame=np.full((36, 64, 3), [200, 50, 50], dtype=np.uint8))

        with patch("src.sync.engine.WizBulbController", return_value=mock_ctrl):
            engine = UnifiedSyncEngine(
                bulb_ip="192.168.1.50",
                dry_run=False,
                sync_mode=SyncMode.SCREEN,
                restore_state=True,
                custom_capture_backend=mock_backend,
            )

            await engine.start()
            assert engine._pre_sync_state == initial_state

            report = await engine.stop()
            assert report.result == RestorationResult.SUCCESS
            # Verify exact restoration call with initial state
            mock_ctrl.restore_state.assert_called_once_with(initial_state)
            mock_ctrl.disconnect.assert_called_once()

    async def test_transactional_rollback_on_screen_startup_failure(self) -> None:
        mock_ctrl = MagicMock(spec=WizBulbController)
        mock_ctrl.is_connected = True
        mock_ctrl.is_on = False
        mock_ctrl.connect = AsyncMock()
        mock_ctrl.turn_on = AsyncMock()
        mock_ctrl.get_state = AsyncMock(return_value=BulbState(is_on=False, raw_pilot={}))
        mock_ctrl.restore_state = AsyncMock()
        mock_ctrl.disconnect = AsyncMock()

        # Failing capture backend
        failing_backend = MockCaptureBackend()
        failing_backend.start = MagicMock(return_value=False)

        with patch("src.sync.engine.WizBulbController", return_value=mock_ctrl):
            engine = UnifiedSyncEngine(
                bulb_ip="192.168.1.50",
                dry_run=False,
                sync_mode=SyncMode.SCREEN,
                custom_capture_backend=failing_backend,
            )

            with pytest.raises(RuntimeError):
                await engine.start()

            # Transactional rollback should safely release controller and restore state
            assert not engine.is_running
            mock_ctrl.restore_state.assert_called_once()
            mock_ctrl.disconnect.assert_called_once()

    async def test_hybrid_audio_focus_and_beat_intensity_propagation(self) -> None:
        """Verify modifying Hybrid settings propagates to AudioCapture, Analyzer, and Processor."""
        from src.audio.beat_detector import AudioFocus

        mock_backend = MockCaptureBackend(initial_frame=np.full((36, 64, 3), [10, 50, 240], dtype=np.uint8))
        engine = UnifiedSyncEngine(
            dry_run=True,
            sync_mode=SyncMode.HYBRID,
            hybrid_type="rhythm",
            hybrid_audio_focus="rhythm",
            hybrid_beat_intensity=1.5,
            custom_capture_backend=mock_backend,
        )

        with patch("src.sync.engine.AudioCapture") as mock_audio_cls:
            mock_audio = MagicMock()
            mock_audio_cls.return_value = mock_audio

            await engine.start()
            assert engine.audio_focus == AudioFocus.RHYTHM
            assert engine.hybrid_processor.settings.audio_focus == AudioFocus.RHYTHM
            assert engine.hybrid_processor.settings.beat_intensity == 1.5

            # Dynamically switch to Kick Focus with new beat intensity
            engine.set_hybrid_settings(audio_focus="kick", beat_intensity=0.8)
            assert engine.audio_focus == AudioFocus.KICK
            assert mock_audio.audio_focus == AudioFocus.KICK
            assert engine.hybrid_processor.settings.audio_focus == AudioFocus.KICK
            assert engine.hybrid_processor.settings.beat_intensity == 0.8

            # Dynamically switch back to Full Music
            engine.set_hybrid_settings(audio_focus="full", beat_intensity=1.2)
            assert engine.audio_focus == AudioFocus.FULL_MUSIC
            assert mock_audio.audio_focus == AudioFocus.FULL_MUSIC
            assert engine.hybrid_processor.settings.audio_focus == AudioFocus.FULL_MUSIC
            assert engine.hybrid_processor.settings.beat_intensity == 1.2

            await engine.stop()

    async def test_screen_capture_failure_and_recovery_in_engine(self) -> None:
        """Verify sending None frame initiates fallback and subsequent frame recovers."""
        mock_backend = MockCaptureBackend(initial_frame=np.full((36, 64, 3), [240, 20, 20], dtype=np.uint8))
        engine = UnifiedSyncEngine(
            dry_run=True,
            sync_mode=SyncMode.SCREEN,
            smoothing_preset="responsive",
            custom_capture_backend=mock_backend,
        )
        await engine.start()

        # Step 1: establish initial red video state
        t0 = 10.0
        for i in range(5):
            engine._handle_screen_frame(np.full((36, 64, 3), [240, 20, 20], dtype=np.uint8), timestamp=t0 + i * 0.05)

        status1 = engine.get_status()
        assert status1.target_state.rgb[0] > 180

        # Step 2: send prolonged None frame (capture failure / stale event) past full fade duration (3.2s)
        for i in range(25):
            engine._handle_screen_frame(None, timestamp=t0 + 1.5 + i * 0.1)

        status_stale = engine.get_status()
        # Fallback towards warm ambient (255, 214, 170) and min_brightness
        assert status_stale.target_state.brightness == engine.settings.min_brightness

        # Step 3: valid frame resumes (recovery)
        for i in range(8):
            engine._handle_screen_frame(np.full((36, 64, 3), [20, 240, 20], dtype=np.uint8), timestamp=t0 + 5.0 + i * 0.05)

        status_recovered = engine.get_status()
        # Green is dominant after recovery
        assert status_recovered.target_state.rgb[1] > status_recovered.target_state.rgb[0]

        await engine.stop()
