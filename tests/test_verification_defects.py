"""Regression tests for Phase 4.3 verification defects and falsification testing.

Ensures run_gui_hardware_test and validation mechanisms cannot produce false-positive passes
when connection, effect switching, audio frame flow, commands, or state restoration fail.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.desktop_app import run_gui_hardware_test
from src.sync.state import RestorationReport, RestorationResult
from src.ui.workers.sync_worker import SyncState
from src.wiz.controller import BulbState


@pytest.fixture
def mock_bulb_state():
    return BulbState(is_on=True, active_mode="white", brightness=200, rgb=(0, 0, 0), colortemp=2700)


@pytest.fixture(autouse=True)
def mock_audio_capture():
    with patch("src.sync.engine.AudioCapture") as mock_cap_cls:
        mock_cap = MagicMock()
        mock_cap.is_capturing = True
        mock_cap_cls.return_value = mock_cap
        yield mock_cap


@pytest.fixture(autouse=True)
def mock_discovery():
    with patch("src.ui.workers.sync_worker.discover_devices", new_callable=AsyncMock) as mock_disc:
        mock_disc.return_value = []
        yield mock_disc


def test_failed_connection_produces_failed_diagnostic(tmp_path, mock_bulb_state):
    """Verifies that a failed connection test is NOT marked as successful and returns exit code 1."""
    diag_file = tmp_path / "failed_conn_diag.json"

    with patch("src.desktop_app.WizBulbController") as mock_ctrl_cls:
        # Pre-sync state query succeeds
        mock_init_ctrl = AsyncMock()
        mock_init_ctrl.get_state.return_value = mock_bulb_state
        mock_init_ctrl.disconnect = AsyncMock()
        mock_ctrl_cls.return_value = mock_init_ctrl

        with patch("src.ui.workers.sync_worker.WizBulbController") as mock_worker_ctrl_cls:
            mock_worker_ctrl = AsyncMock()
            mock_worker_ctrl.connect.side_effect = Exception("UDP Connection Timed Out")
            mock_worker_ctrl_cls.return_value = mock_worker_ctrl

            exit_code = run_gui_hardware_test("192.168.1.99", diag_file=diag_file, run_duration=0.5)

    assert exit_code == 1
    assert diag_file.exists()
    with open(diag_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "failed"
    assert data["connection_tested"] is False
    assert "connection test failed" in data["error"].lower()


def test_unverified_effect_switch_fails(tmp_path, mock_bulb_state):
    """Verifies that if active effect in engine does not switch, test fails."""
    diag_file = tmp_path / "failed_effect_diag.json"

    with patch("src.desktop_app.WizBulbController") as mock_ctrl_cls:
        mock_init_ctrl = AsyncMock()
        mock_init_ctrl.get_state.return_value = mock_bulb_state
        mock_init_ctrl.disconnect = AsyncMock()
        mock_ctrl_cls.return_value = mock_init_ctrl

        with patch("src.ui.workers.sync_worker.WizBulbController") as mock_worker_ctrl_cls:
            mock_worker_ctrl = AsyncMock()
            mock_worker_ctrl.capabilities = MagicMock(model="ESP25 WiZ Bulb", firmware_version="1.38.0")
            mock_worker_ctrl.mac = "cc4085d19ea0"
            mock_worker_ctrl.get_state.return_value = mock_bulb_state
            mock_worker_ctrl_cls.return_value = mock_worker_ctrl

            # Mock worker set_effect to do nothing (simulate unswitched effect)
            with patch.object(run_gui_hardware_test, "__wrapped__", None, create=True):
                with patch("src.ui.main_window.MainWindow._on_effect_changed"):
                    with patch("src.ui.workers.sync_worker.SyncWorker.get_telemetry_snapshot") as mock_telem:
                        mock_telem.return_value = (
                            make_mock_status(commands_sent=10),
                            None,
                            make_mock_stats(frames_processed=100),
                        )
                        exit_code = run_gui_hardware_test("192.168.1.4", diag_file=diag_file, run_duration=0.5)

    assert exit_code == 1
    assert diag_file.exists()
    with open(diag_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "failed"
    assert data["effect_switched"] is False
    assert "active effect" in data["error"].lower()


from src.audio.capture import CaptureStats
from src.sync.state import LightingState, RestorationReport, RestorationResult, SyncStatus


def make_mock_status(commands_sent=10):
    return SyncStatus(
        is_running=True,
        current_effect="Beat Pulse",
        bulb_ip="192.168.1.4",
        audio_device="Default Output",
        target_state=LightingState(rgb=(255, 255, 255), brightness=128),
        applied_state=LightingState(rgb=(255, 255, 255), brightness=128),
        updates_per_second=3.5,
        commands_sent=commands_sent,
        commands_failed=0,
        last_command_duration_ms=45.0,
    )


def make_mock_stats(frames_processed=100):
    return CaptureStats(
        sample_rate=48000,
        buffer_size=1024,
        buffer_duration_ms=21.3,
        fps=46.8,
        analysis_time_ms=2.5,
        estimated_latency_ms=25.0,
        frames_processed=frames_processed,
        dropped_frames=0,
    )


def test_zero_audio_frames_fails(tmp_path, mock_bulb_state):
    """Verifies that 0 processed audio frames causes validation failure."""
    diag_file = tmp_path / "zero_audio_diag.json"

    with patch("src.desktop_app.WizBulbController") as mock_ctrl_cls:
        mock_init_ctrl = AsyncMock()
        mock_init_ctrl.get_state.return_value = mock_bulb_state
        mock_init_ctrl.disconnect = AsyncMock()
        mock_ctrl_cls.return_value = mock_init_ctrl

        with patch("src.ui.workers.sync_worker.WizBulbController") as mock_worker_ctrl_cls:
            mock_worker_ctrl = AsyncMock()
            mock_worker_ctrl.capabilities = MagicMock(model="ESP25 WiZ Bulb", firmware_version="1.38.0")
            mock_worker_ctrl.mac = "cc4085d19ea0"
            mock_worker_ctrl.get_state.return_value = mock_bulb_state
            mock_worker_ctrl_cls.return_value = mock_worker_ctrl

            # Mock telemetry to report 0 frames
            with patch("src.ui.workers.sync_worker.SyncWorker.get_telemetry_snapshot") as mock_telem:
                mock_telem.return_value = (
                    make_mock_status(commands_sent=10),
                    None,
                    make_mock_stats(frames_processed=0),
                )
                exit_code = run_gui_hardware_test("192.168.1.4", diag_file=diag_file, run_duration=0.5)

    assert exit_code == 1
    assert diag_file.exists()
    with open(diag_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "failed"
    assert data["audio_frames_processed"] == 0
    assert "no audio frames were processed" in data["error"].lower()


def test_restored_state_mismatch_fails(tmp_path, mock_bulb_state):
    """Verifies that if post-sync bulb state fails to match initial state, test fails."""
    diag_file = tmp_path / "resto_mismatch_diag.json"

    with patch("src.desktop_app.WizBulbController") as mock_ctrl_cls:
        # Initial is ON
        mock_init_ctrl = AsyncMock()
        mock_init_ctrl.get_state.return_value = mock_bulb_state
        mock_init_ctrl.disconnect = AsyncMock()

        # Post-sync check returns OFF (mismatch!)
        mismatched_state = BulbState(is_on=False, active_mode="white", brightness=0, rgb=(0, 0, 0))
        mock_post_ctrl = AsyncMock()
        mock_post_ctrl.get_state.return_value = mismatched_state
        mock_post_ctrl.disconnect = AsyncMock()

        # Wire side_effects for sequential controller instances
        mock_ctrl_cls.side_effect = [mock_init_ctrl, mock_post_ctrl]

        with patch("src.ui.workers.sync_worker.WizBulbController") as mock_worker_ctrl_cls:
            mock_worker_ctrl = AsyncMock()
            mock_worker_ctrl.capabilities = MagicMock(model="ESP25 WiZ Bulb", firmware_version="1.38.0")
            mock_worker_ctrl.mac = "cc4085d19ea0"
            mock_worker_ctrl.get_state.return_value = mock_bulb_state
            mock_worker_ctrl_cls.return_value = mock_worker_ctrl

            with patch("src.ui.workers.sync_worker.SyncWorker.get_telemetry_snapshot") as mock_telem:
                mock_telem.return_value = (
                    make_mock_status(commands_sent=10),
                    None,
                    make_mock_stats(frames_processed=100),
                )
                exit_code = run_gui_hardware_test("192.168.1.4", diag_file=diag_file, run_duration=0.5)

    assert exit_code == 1
    assert diag_file.exists()
    with open(diag_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "failed"
    assert data["restoration_verified"] is False
    assert "restored power state" in data["error"].lower()
