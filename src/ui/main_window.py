"""Main desktop application window for WiZ Music Sync."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.audio.devices import AudioDevice
from src.config.preferences import AppPreferences, PreferencesManager
from src.effects import EffectSettings
from src.sync.state import RestorationReport, RestorationResult
from src.ui.widgets.audio_panel import AudioPanel
from src.ui.widgets.device_panel import DevicePanel
from src.ui.widgets.effects_panel import EffectsPanel
from src.ui.widgets.spectrum_view import SpectrumView
from src.ui.widgets.status_panel import StatusPanel
from src.ui.workers.sync_worker import SyncState, SyncWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main graphical interface window for WiZ Music Sync."""

    def __init__(self, prefs_manager: Optional[PreferencesManager] = None) -> None:
        super().__init__()
        self.setWindowTitle("WiZ Music Sync")
        self.resize(800, 840)
        self.setMinimumSize(680, 700)

        self._is_closing = False
        self._is_closed = False

        self.prefs_mgr = prefs_manager or PreferencesManager()
        self.prefs = self.prefs_mgr.preferences

        self.worker = SyncWorker(self)

        # GUI-owned QTimer for telemetry updates (~30 Hz)
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(33)
        self._telemetry_timer.timeout.connect(self._on_telemetry_tick)

        self._setup_ui()
        self._connect_signals()
        self._load_preferences()

        # Trigger initial background discovery scan
        self.worker.discover_bulbs(timeout=2.0)

    @property
    def telemetry_timer(self) -> QTimer:
        """Expose GUI-thread owned telemetry QTimer for inspection and testing."""
        return self._telemetry_timer

    def _setup_ui(self) -> None:
        # Central Scroll Area to handle compact screen resolutions gracefully
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # Header Title
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)

        title_lbl = QLabel("WiZ Music Sync")
        title_lbl.setObjectName("headingLabel")
        sub_lbl = QLabel("Real-Time Windows WASAPI System Audio to Philips WiZ Smart Lighting")
        sub_lbl.setObjectName("subheadingLabel")

        header_layout.addWidget(title_lbl)
        header_layout.addWidget(sub_lbl)
        main_layout.addLayout(header_layout)

        # Two-column layout for controls and visualizer
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(14)

        # Left Column (Device, Audio Source, Primary Controls)
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        self.device_panel = DevicePanel(self)
        self.audio_panel = AudioPanel(self)
        self.status_panel = StatusPanel(self)

        left_col.addWidget(self.device_panel)
        left_col.addWidget(self.audio_panel)
        left_col.addWidget(self.status_panel)
        left_col.addStretch()

        # Right Column (Live Spectrum, Rhythm Onset, Effect Tuning)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        self.spectrum_view = SpectrumView(self)
        self.effects_panel = EffectsPanel(self)

        right_col.addWidget(self.spectrum_view)
        right_col.addWidget(self.effects_panel)
        right_col.addStretch()

        columns_layout.addLayout(left_col, stretch=1)
        columns_layout.addLayout(right_col, stretch=1)
        main_layout.addLayout(columns_layout)

        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Initialized WiZ Music Sync. Ready.")

    def _connect_signals(self) -> None:
        # Device Panel signals
        self.device_panel.scan_requested.connect(self._on_scan_requested)
        self.device_panel.test_requested.connect(self._on_test_requested)
        self.device_panel.bulb_selected.connect(self._on_bulb_selected)

        # Audio Panel signals
        self.audio_panel.device_changed.connect(self._on_audio_device_changed)

        # Effects Panel signals
        self.effects_panel.effect_changed.connect(self._on_effect_changed)
        self.effects_panel.settings_changed.connect(self._on_settings_changed)

        # Status Panel signals
        self.status_panel.start_clicked.connect(self._on_start_sync)
        self.status_panel.stop_clicked.connect(self._on_stop_sync)
        self.status_panel.restore_toggled.connect(self._on_restore_toggled)
        self.status_panel.dry_run_toggled.connect(self._on_dry_run_toggled)

        # Worker signals
        self.worker.bulbs_discovered.connect(self._on_bulbs_discovered)
        self.worker.bulb_tested.connect(self._on_bulb_tested)
        self.worker.sync_started.connect(self._on_sync_started)
        self.worker.sync_stopped.connect(self._on_sync_stopped)
        self.worker.sync_error.connect(self._on_sync_error)
        self.worker.state_changed.connect(self._on_state_changed)
        self.worker.closed.connect(self._on_worker_closed)

    def _load_preferences(self) -> None:
        """Apply persisted preferences to UI elements."""
        # Bulb IP
        if self.prefs.last_bulb_ip:
            self.device_panel.set_manual_ip(self.prefs.last_bulb_ip)

        # Audio Device
        if self.prefs.last_audio_device_name:
            self.audio_panel.refresh_devices(preferred_name=self.prefs.last_audio_device_name)

        # Effects and Sliders
        self.effects_panel.set_selected_effect(self.prefs.preferred_effect)
        settings = EffectSettings(
            sensitivity=self.prefs.sensitivity,
            min_brightness=self.prefs.min_brightness,
            max_brightness=self.prefs.max_brightness,
            color_smoothing=self.prefs.color_smoothing,
            attack_speed=self.prefs.attack_speed,
            release_speed=self.prefs.release_speed,
            beat_strength=self.prefs.beat_strength,
            update_rate_hz=self.prefs.update_rate_hz,
        )
        self.effects_panel.set_settings(settings)

        # Toggles
        self.status_panel.restore_chk.setChecked(self.prefs.restore_on_stop)
        self.status_panel.dry_run_chk.setChecked(self.prefs.dry_run)

    def _save_preferences(self) -> None:
        """Save current UI state to preferences manager."""
        self.prefs.last_bulb_ip = self.device_panel.get_selected_ip()
        dev = self.audio_panel.get_selected_device()
        self.prefs.last_audio_device_name = dev.name if dev else None

        self.prefs.preferred_effect = self.effects_panel.get_selected_effect()
        settings = self.effects_panel.get_settings()
        self.prefs.sensitivity = settings.sensitivity
        self.prefs.min_brightness = settings.min_brightness
        self.prefs.max_brightness = settings.max_brightness
        self.prefs.color_smoothing = settings.color_smoothing
        self.prefs.attack_speed = settings.attack_speed
        self.prefs.release_speed = settings.release_speed
        self.prefs.beat_strength = settings.beat_strength
        self.prefs.update_rate_hz = settings.update_rate_hz

        self.prefs.restore_on_stop = self.status_panel.restore_chk.isChecked()
        self.prefs.dry_run = self.status_panel.dry_run_chk.isChecked()

        self.prefs_mgr.save(self.prefs)

    # ------------------ Action Handlers ------------------

    def _on_scan_requested(self) -> None:
        self.statusBar.showMessage("Scanning local network for WiZ smart bulbs...")
        self.device_panel.set_status("Scanning local Wi-Fi for bulbs...")
        self.worker.discover_bulbs(timeout=2.5)

    def _on_test_requested(self, ip: str) -> None:
        self.statusBar.showMessage(f"Testing UDP communication to bulb at {ip}...")
        self.worker.test_connection(ip)

    def _on_bulb_selected(self, ip: str, mac: str) -> None:
        self.prefs.last_bulb_ip = ip
        if mac:
            self.prefs.last_bulb_mac = mac

    def _on_audio_device_changed(self, device: Optional[AudioDevice]) -> None:
        if device:
            self.prefs.last_audio_device_name = device.name

    def _on_effect_changed(self, effect_name: str) -> None:
        self.prefs.preferred_effect = effect_name
        self.worker.set_effect(effect_name)

    def _on_settings_changed(self, settings: EffectSettings) -> None:
        self.worker.set_settings(settings)

    def _on_restore_toggled(self, checked: bool) -> None:
        self.prefs.restore_on_stop = checked

    def _on_dry_run_toggled(self, checked: bool) -> None:
        self.prefs.dry_run = checked

    def _on_start_sync(self) -> None:
        if self.worker.state != SyncState.IDLE:
            logger.warning("Start ignored: worker is currently in state %s", self.worker.state.name)
            return

        bulb_ip = self.device_panel.get_selected_ip()
        dry_run = self.status_panel.dry_run_chk.isChecked()

        if not dry_run and not bulb_ip:
            QMessageBox.warning(
                self,
                "No Bulb Selected",
                "Please scan and select a WiZ bulb or enter an IP address manually before starting.",
            )
            return

        dev = self.audio_panel.get_selected_device()
        dev_idx = dev.index if dev else None

        effect_name = self.effects_panel.get_selected_effect()
        settings = self.effects_panel.get_settings()
        restore_state = self.status_panel.restore_chk.isChecked()

        self.status_panel.set_busy_state("Connecting...", allow_cancel=True)
        self.statusBar.showMessage(f"Starting music sync ({effect_name})...")

        # Disable device and audio selection during active sync
        self.device_panel.set_controls_enabled(False)
        self.audio_panel.set_controls_enabled(False)

        self.worker.start_sync(
            bulb_ip=bulb_ip,
            audio_device_index=dev_idx,
            effect_name=effect_name,
            settings=settings,
            restore_state=restore_state,
            dry_run=dry_run,
        )

    def _on_stop_sync(self) -> None:
        self.status_panel.set_busy_state("Stopping...", allow_cancel=False)
        self.statusBar.showMessage("Stopping music sync and restoring bulb state...")
        self.worker.stop_sync()

    # ------------------ Worker Event Callbacks ------------------

    def _on_bulbs_discovered(self, bulbs: list) -> None:
        self.device_panel.set_discovered_bulbs(bulbs, default_ip=self.prefs.last_bulb_ip)
        self.statusBar.showMessage(f"Discovered {len(bulbs)} WiZ bulb(s) on local network.", 5000)

    def _on_bulb_tested(self, success: bool, message: str) -> None:
        self.device_panel.set_status(message, is_error=not success, is_success=success)
        self.statusBar.showMessage(message, 5000)

    def _on_state_changed(self, state: SyncState) -> None:
        """Handle worker state transitions."""
        logger.debug("MainWindow received worker state transition: %s", state.name)
        if state == SyncState.STARTING:
            self.device_panel.set_controls_enabled(False)
            self.audio_panel.set_controls_enabled(False)
            self.status_panel.set_busy_state("Connecting...", allow_cancel=True)
            self.statusBar.showMessage("Starting music sync...")
        elif state == SyncState.RUNNING:
            if not self._telemetry_timer.isActive():
                self._telemetry_timer.start()
        elif state == SyncState.STOPPING:
            self._telemetry_timer.stop()
            self.status_panel.set_busy_state("Stopping...", allow_cancel=False)
            self.statusBar.showMessage("Stopping music sync and restoring bulb state...")
        elif state == SyncState.IDLE:
            self._telemetry_timer.stop()
            self.status_panel.set_sync_state(False)
            self.status_panel.reset_button_enabled()
            self.device_panel.set_controls_enabled(True)
            self.audio_panel.set_controls_enabled(True)
            self.spectrum_view.update_metrics(None)
        elif state == SyncState.CLOSED:
            self._telemetry_timer.stop()

    def _on_sync_started(self, bulb_ip: str) -> None:
        dry_run = self.status_panel.dry_run_chk.isChecked()
        mode_text = "DRY-RUN" if dry_run else bulb_ip
        self.status_panel.set_sync_state(True, mode_text)
        self.status_panel.reset_button_enabled()
        if not self._telemetry_timer.isActive():
            self._telemetry_timer.start()
        self.statusBar.showMessage(f"Live music synchronization active with {mode_text}.")

    def _on_sync_stopped(self) -> None:
        self._telemetry_timer.stop()
        self.status_panel.set_sync_state(False)
        self.status_panel.reset_button_enabled()
        self.device_panel.set_controls_enabled(True)
        self.audio_panel.set_controls_enabled(True)
        self.spectrum_view.update_metrics(None)

        report = self.worker.last_restoration_report
        if report:
            if report.result == RestorationResult.SUCCESS:
                msg = f"Music sync stopped. {report.result.value} ({report.details})."
            elif report.result == RestorationResult.SKIPPED:
                msg = f"Music sync stopped. {report.result.value}."
            elif report.result == RestorationResult.UNAVAILABLE:
                msg = f"Music sync stopped. {report.result.value}."
            else:  # FAILED
                msg = f"Music sync stopped. {report.result.value}: {report.details}."
            self.statusBar.showMessage(msg, 7000)
            logger.info("Sync stopped: %s", msg)
        else:
            self.statusBar.showMessage("Music sync stopped.", 5000)

    def _on_sync_error(self, error_msg: str) -> None:
        self._telemetry_timer.stop()
        self.status_panel.set_sync_state(False)
        self.status_panel.reset_button_enabled()
        self.device_panel.set_controls_enabled(True)
        self.audio_panel.set_controls_enabled(True)
        self.spectrum_view.update_metrics(None)
        self.statusBar.showMessage(f"Sync error: {error_msg}")
        QMessageBox.critical(self, "Synchronization Error", f"Failed to start music sync:\n\n{error_msg}")

    def _on_telemetry_tick(self) -> None:
        """Periodic timer tick executing strictly on Qt GUI main thread (~30 Hz)."""
        status, metrics, stats = self.worker.get_telemetry_snapshot()
        if status:
            self.status_panel.update_telemetry(status)
        if metrics:
            self.spectrum_view.update_metrics(metrics)

    def _on_worker_closed(self) -> None:
        """Slot invoked once background worker finishes stopping and terminates cleanly."""
        self._is_closed = True
        self.worker.shutdown_loop(timeout=1.0)
        if self._is_closing:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close: gracefully stop active sync, save preferences, and release resources."""
        if self._is_closed or self.worker.state == SyncState.CLOSED:
            self._telemetry_timer.stop()
            self._save_preferences()
            self.worker.shutdown_loop(timeout=1.0)
            event.accept()
            return

        if self.worker.state == SyncState.IDLE:
            self._is_closed = True
            self._telemetry_timer.stop()
            self._save_preferences()
            self.worker.shutdown_loop(timeout=1.0)
            event.accept()
            return

        # Active synchronization or transitioning (STARTING, RUNNING, STOPPING)
        event.ignore()
        self._is_closing = True
        self.setEnabled(False)
        self.statusBar.showMessage("Closing application and restoring bulb state...")
        self._telemetry_timer.stop()
        self.worker.request_close()
