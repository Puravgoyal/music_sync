"""Automated GUI integration tests using pytest-qt."""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from src.audio.analyzer import AudioMetrics
from src.audio.devices import AudioDevice
from src.config.preferences import AppPreferences, PreferencesManager
from src.sync.state import LightingState, SyncStatus
from src.ui.main_window import MainWindow
from src.ui.widgets.audio_panel import AudioPanel
from src.ui.widgets.device_panel import DevicePanel
from src.ui.widgets.effects_panel import EffectsPanel
from src.ui.widgets.spectrum_view import SpectrumView
from src.ui.widgets.status_panel import StatusPanel
from src.wiz.discovery import DiscoveredDevice


@pytest.fixture
def dummy_preferences(tmp_path) -> PreferencesManager:
    config_file = tmp_path / "ui_test_prefs.json"
    mgr = PreferencesManager(filepath=config_file)
    mgr.preferences.last_bulb_ip = "192.168.1.4"
    mgr.preferences.preferred_effect = "spectrum"
    return mgr


def test_device_panel_selection(qtbot) -> None:
    panel = DevicePanel()
    qtbot.addWidget(panel)

    bulbs = [
        DiscoveredDevice(ip="192.168.1.4", mac="cc4085d19ea0", model="ESP25_SHRGB_01"),
        DiscoveredDevice(ip="192.168.1.10", mac="aabbccddeeff", model="WiZ Filament"),
    ]
    panel.set_discovered_bulbs(bulbs, default_ip="192.168.1.4")
    assert panel.get_selected_ip() == "192.168.1.4"

    # Manual IP overrides dropdown
    panel.set_manual_ip("192.168.1.99")
    assert panel.get_selected_ip() == "192.168.1.99"


def test_audio_panel_enumeration(qtbot) -> None:
    panel = AudioPanel()
    qtbot.addWidget(panel)

    dev = panel.get_selected_device()
    # If system has audio devices, it shouldn't crash
    panel.set_controls_enabled(False)
    assert not panel.device_combo.isEnabled()
    panel.set_controls_enabled(True)
    assert panel.device_combo.isEnabled()


def test_effects_panel_controls(qtbot) -> None:
    panel = EffectsPanel()
    qtbot.addWidget(panel)

    panel.set_selected_effect("beat")
    assert panel.get_selected_effect() == "beat"

    # Change sensitivity slider
    panel.sens_slider.setValue(220)
    settings = panel.get_settings()
    assert settings.sensitivity == 2.2


def test_spectrum_view_metrics_update(qtbot) -> None:
    view = SpectrumView()
    qtbot.addWidget(view)

    metrics = AudioMetrics(
        rms=0.5,
        loudness=0.8,
        bass=0.9,
        mid=0.4,
        treble=0.2,
        spectral_flux=0.1,
        is_onset=True,
        onset_strength=0.8,
        is_silent=False,
    )
    view.update_metrics(metrics)

    assert view.bass_bar.value() == 90
    assert view.mid_bar.value() == 40
    assert view.treble_bar.value() == 20
    assert view.vol_bar.value() == 80
    assert "BEAT" in view.beat_badge.text()

    # Clear metrics
    view.update_metrics(None)
    assert view.bass_bar.value() == 0


def test_status_panel_telemetry(qtbot) -> None:
    panel = StatusPanel()
    qtbot.addWidget(panel)

    status = SyncStatus(
        is_running=True,
        current_effect="Beat Pulse",
        bulb_ip="192.168.1.4",
        audio_device="Headphones",
        target_state=LightingState(rgb=(200, 50, 50), brightness=180),
        applied_state=LightingState(rgb=(198, 52, 48), brightness=180),
        updates_per_second=4.2,
        commands_sent=25,
        commands_failed=0,
        last_command_duration_ms=28.4,
    )
    panel.update_telemetry(status)
    assert "4.2 Hz" in panel.telemetry_label.text()
    assert "25 sent" in panel.telemetry_label.text()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_main_window_lifecycle_and_actions(mock_discover, qtbot, dummy_preferences) -> None:
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=dummy_preferences)
    qtbot.addWidget(window)

    assert window.windowTitle() == "WiZ Music Sync"
    assert window.device_panel.get_selected_ip() == "192.168.1.4"

    # Mock the worker start/stop
    window.worker.start_sync = MagicMock()
    window.worker.stop_sync = MagicMock()

    # Trigger Start
    window.status_panel.start_clicked.emit()
    window.worker.start_sync.assert_called_once()

    # Simulate sync_started signal from worker
    window.worker.sync_started.emit("192.168.1.4")
    assert "STOP" in window.status_panel.toggle_btn.text()
    assert not window.device_panel.device_combo.isEnabled()

    # Trigger Stop
    window.status_panel.stop_clicked.emit()
    window.worker.stop_sync.assert_called_once()

    # Simulate sync_stopped signal
    window.worker.sync_stopped.emit()
    assert "START" in window.status_panel.toggle_btn.text()
    assert window.device_panel.device_combo.isEnabled()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_rapid_start_stop_transitions(mock_discover, qtbot, dummy_preferences) -> None:
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=dummy_preferences)
    qtbot.addWidget(window)

    window.worker.start_sync = MagicMock()
    window.worker.stop_sync = MagicMock()

    # Rapid cycles
    for _ in range(5):
        window.status_panel.start_clicked.emit()
        window.worker.sync_started.emit("192.168.1.4")
        window.status_panel.stop_clicked.emit()
        window.worker.sync_stopped.emit()

    assert window.status_panel.toggle_btn.isEnabled()
    assert window.device_panel.device_combo.isEnabled()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_hybrid_panel_controls_propagate_to_worker_and_preferences(mock_discover, qtbot, dummy_preferences) -> None:
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=dummy_preferences)
    qtbot.addWidget(window)

    window.worker.set_hybrid_settings = MagicMock()
    window.worker.set_audio_focus = MagicMock()
    window.worker.start_sync = MagicMock()

    # Switch to Hybrid mode
    idx = window.source_combo.findData("hybrid")
    window.source_combo.setCurrentIndex(idx)
    assert window.prefs.sync_mode == "hybrid"

    # Change hybrid focus to 'kick'
    focus_idx = window.hybrid_panel.focus_combo.findData("kick")
    window.hybrid_panel.focus_combo.setCurrentIndex(focus_idx)

    assert window.prefs.hybrid_audio_focus == "kick"
    window.worker.set_audio_focus.assert_called_with("kick")
    window.worker.set_hybrid_settings.assert_called()
    call_args = window.worker.set_hybrid_settings.call_args[1]
    assert call_args["audio_focus"] == "kick"

    # Change beat intensity slider (value 18 = 1.8x)
    window.hybrid_panel.beat_slider.setValue(18)
    assert window.prefs.hybrid_beat_intensity == pytest.approx(1.8, 0.05)
    call_args = window.worker.set_hybrid_settings.call_args[1]
    assert call_args["beat_intensity"] == pytest.approx(1.8, 0.05)

    # Change audio contribution slider (value 60 = 0.60)
    window.hybrid_panel.contrib_slider.setValue(60)
    assert window.prefs.audio_contribution == pytest.approx(0.60, 0.05)
    call_args = window.worker.set_hybrid_settings.call_args[1]
    assert call_args["audio_contribution"] == pytest.approx(0.60, 0.05)

    # Trigger start_sync in hybrid mode and verify worker.start_sync receives hybrid focus and beat
    window.status_panel.start_clicked.emit()
    window.worker.start_sync.assert_called_once()
    start_kwargs = window.worker.start_sync.call_args[1]
    assert start_kwargs["sync_mode"] == "hybrid"
    assert start_kwargs["audio_focus"] == "kick"
    assert start_kwargs["hybrid_audio_focus"] == "kick"
    assert start_kwargs["hybrid_beat_intensity"] == pytest.approx(1.8, 0.05)

