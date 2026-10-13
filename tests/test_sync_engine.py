"""Tests for MusicSyncEngine lifecycle, effect switching, and bulb state restoration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audio.analyzer import AudioMetrics
from src.audio.capture import CaptureStats
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.sync.state import LightingState
from src.wiz.controller import BulbCapabilities, BulbState, WizBulbController


def _make_dummy_metrics() -> AudioMetrics:
    return AudioMetrics(
        rms=0.4,
        loudness=0.5,
        bass=0.7,
        mid=0.3,
        treble=0.2,
        spectral_flux=0.1,
        is_onset=True,
        onset_strength=0.8,
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
        frames_processed=100,
        dropped_frames=0,
    )


@pytest.mark.asyncio
class TestMusicSyncEngine:
    """Test MusicSyncEngine coordination and lifecycle."""

    async def test_engine_initialization_defaults(self) -> None:
        engine = MusicSyncEngine(dry_run=True)
        assert engine.effect_name == "spectrum"
        assert engine.update_rate_hz == 4.0
        assert engine.dry_run is True
        assert not engine.is_running

    async def test_dynamic_effect_switching(self) -> None:
        engine = MusicSyncEngine(dry_run=True, effect_name="spectrum")
        assert engine.current_effect.name == "Spectrum RGB"

        engine.set_effect("beat")
        assert engine.current_effect.name == "Beat Pulse"
        assert engine.effect_name == "beat"

        engine.set_effect("bass")
        assert engine.current_effect.name == "Bass Reactive"

    async def test_dynamic_settings_update(self) -> None:
        engine = MusicSyncEngine(dry_run=True)
        new_settings = EffectSettings(sensitivity=2.5, max_brightness=200, update_rate_hz=6.0)
        engine.set_settings(new_settings)
        assert engine.settings.sensitivity == 2.5
        assert engine.settings.max_brightness == 200

    async def test_audio_metric_routing_to_scheduler(self) -> None:
        engine = MusicSyncEngine(dry_run=True, effect_name="spectrum")
        engine._scheduler = MagicMock()

        metrics = _make_dummy_metrics()
        stats = _make_dummy_stats()

        engine._handle_audio_metrics(metrics, stats)

        assert engine.last_metrics == metrics
        assert engine.last_stats == stats
        engine._scheduler.submit.assert_called_once()
        submitted_state = engine._scheduler.submit.call_args[0][0]
        assert isinstance(submitted_state, LightingState)
        assert submitted_state.is_on is True

    @patch("src.sync.engine.AudioCapture")
    async def test_engine_lifecycle_dry_run(self, mock_capture_cls: MagicMock) -> None:
        mock_capture_inst = MagicMock()
        mock_capture_cls.return_value = mock_capture_inst

        engine = MusicSyncEngine(dry_run=True, update_rate_hz=5.0)
        await engine.start()

        assert engine.is_running
        mock_capture_inst.start.assert_called_once()
        assert engine.scheduler is not None
        assert engine.scheduler.is_running

        status = engine.get_status()
        assert status.is_running is True
        assert status.is_dry_run is True

        await engine.stop()
        assert not engine.is_running
        mock_capture_inst.stop.assert_called_once()

    @patch("src.sync.engine.AudioCapture")
    @patch("src.sync.engine.WizBulbController")
    async def test_preserves_and_restores_pre_sync_bulb_state(
        self, mock_controller_cls: MagicMock, mock_capture_cls: MagicMock
    ) -> None:
        mock_controller = MagicMock(spec=WizBulbController)
        mock_controller.is_connected = True
        mock_controller.is_on = True
        mock_controller.capabilities = BulbCapabilities(supports_rgb=True, supports_colortemp=True)
        mock_controller.connect = AsyncMock()
        mock_controller.disconnect = AsyncMock()
        mock_controller.set_light_state = AsyncMock()
        mock_controller.set_colortemp = AsyncMock()
        mock_controller.set_brightness = AsyncMock()
        mock_controller.turn_off = AsyncMock()
        mock_controller.turn_on = AsyncMock()

        # Bulb was originally on at warm white 2700K and brightness 120
        saved_state = BulbState(is_on=True, brightness=120, colortemp=2700, rgb=None)
        mock_controller.get_state = AsyncMock(return_value=saved_state)
        mock_controller_cls.return_value = mock_controller

        engine = MusicSyncEngine(bulb_ip="192.168.1.4", dry_run=False, restore_state=True)
        await engine.start()

        assert engine._pre_sync_state == saved_state
        mock_controller.connect.assert_awaited_once()

        # Stop engine: should restore colortemp 2700 and brightness 120
        await engine.stop()
        mock_controller.set_colortemp.assert_awaited_once_with(2700)
        mock_controller.set_brightness.assert_awaited_once_with(120)
        mock_controller.disconnect.assert_awaited_once()
