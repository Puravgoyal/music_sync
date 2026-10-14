"""Synchronization control panel, live RGB preview swatches, and telemetry display widget."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.sync.state import LightingState, SyncStatus


class StatusPanel(QGroupBox):
    """Panel managing primary Start/Stop controls, live RGB color preview swatches, and network telemetry."""

    start_clicked = Signal()
    stop_clicked = Signal()
    restore_toggled = Signal(bool)
    dry_run_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Synchronization Control & Lighting Preview", parent)
        self._current_mode = "music"
        self._is_running = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Main Start / Stop Button
        self.toggle_btn = QPushButton("▶  START MUSIC SYNC")
        self.toggle_btn.setObjectName("startSyncButton")
        self.toggle_btn.setMinimumHeight(44)
        self.toggle_btn.clicked.connect(self._on_button_clicked)
        layout.addWidget(self.toggle_btn)

        # Status Badge & Options
        opts_layout = QHBoxLayout()
        self.status_badge = QLabel("STATUS: STOPPED")
        self.status_badge.setStyleSheet(
            "background-color: #1e2025; color: #94a3b8; border: 1px solid #2d2f36; "
            "border-radius: 4px; padding: 4px 10px; font-weight: 700; font-size: 11px;"
        )

        self.restore_chk = QCheckBox("Restore bulb state on Stop")
        self.restore_chk.setChecked(True)
        self.restore_chk.toggled.connect(self.restore_toggled.emit)

        self.dry_run_chk = QCheckBox("Dry-run (Simulate)")
        self.dry_run_chk.setChecked(False)
        self.dry_run_chk.toggled.connect(self.dry_run_toggled.emit)

        opts_layout.addWidget(self.status_badge)
        opts_layout.addStretch()
        opts_layout.addWidget(self.restore_chk)
        opts_layout.addWidget(self.dry_run_chk)
        layout.addLayout(opts_layout)

        # Color Preview Swatches (Screen -> Target -> Bulb Output)
        swatch_layout = QHBoxLayout()
        swatch_layout.setSpacing(10)

        # 1. Screen Swatch Card (Captured representative screen pixel color)
        self.screen_card = QWidget()
        screen_card_layout = QVBoxLayout(self.screen_card)
        screen_card_layout.setContentsMargins(0, 0, 0, 0)
        screen_card_layout.setSpacing(4)
        screen_title = QLabel("Captured Screen:")
        screen_title.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.screen_swatch = QFrame()
        self.screen_swatch.setMinimumHeight(40)
        self.screen_swatch.setStyleSheet("background-color: #24262c; border: 1px solid #383a42; border-radius: 6px;")
        self.screen_text = QLabel("RGB(---, ---, ---)")
        self.screen_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_text.setStyleSheet("font-size: 10px; color: #cbd5e1;")
        screen_card_layout.addWidget(screen_title)
        screen_card_layout.addWidget(self.screen_swatch)
        screen_card_layout.addWidget(self.screen_text)
        swatch_layout.addWidget(self.screen_card)

        # 2. Target Swatch Card (Smoothed / Fused computed lighting state)
        tgt_card = QVBoxLayout()
        tgt_card.setSpacing(4)
        tgt_title = QLabel("Target Bulb Color:")
        tgt_title.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.tgt_swatch = QFrame()
        self.tgt_swatch.setMinimumHeight(40)
        self.tgt_swatch.setStyleSheet("background-color: #24262c; border: 1px solid #383a42; border-radius: 6px;")
        self.tgt_text = QLabel("RGB(0, 0, 0) @ 0/255")
        self.tgt_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tgt_text.setStyleSheet("font-size: 10px; color: #cbd5e1;")
        tgt_card.addWidget(tgt_title)
        tgt_card.addWidget(self.tgt_swatch)
        tgt_card.addWidget(self.tgt_text)
        swatch_layout.addLayout(tgt_card)

        # 3. Applied Swatch Card (Acknowledged bulb hardware state)
        app_card = QVBoxLayout()
        app_card.setSpacing(4)
        app_title = QLabel("Bulb Output:")
        app_title.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.app_swatch = QFrame()
        self.app_swatch.setMinimumHeight(40)
        self.app_swatch.setStyleSheet("background-color: #24262c; border: 1px solid #383a42; border-radius: 6px;")
        self.app_text = QLabel("RGB(0, 0, 0) @ 0/255")
        self.app_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.app_text.setStyleSheet("font-size: 10px; color: #cbd5e1;")
        app_card.addWidget(app_title)
        app_card.addWidget(self.app_swatch)
        app_card.addWidget(self.app_text)
        swatch_layout.addLayout(app_card)

        layout.addLayout(swatch_layout)

        # Telemetry Summary Line
        self.telemetry_label = QLabel("Rate: 0.0 Hz | Commands: 0 sent, 0 failed | Latency: 0.0 ms")
        self.telemetry_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.telemetry_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.telemetry_label)

    def set_mode(self, mode: str) -> None:
        """Update active mode to adjust button labels and swatch visibility."""
        self._current_mode = mode.lower()
        self.screen_card.setVisible(self._current_mode in ("screen", "hybrid"))
        if not self._is_running:
            if self._current_mode == "screen":
                self.toggle_btn.setText("▶  START SCREEN SYNC")
            elif self._current_mode == "hybrid":
                self.toggle_btn.setText("▶  START HYBRID AV SYNC")
            else:
                self.toggle_btn.setText("▶  START MUSIC SYNC")

    def _on_button_clicked(self) -> None:
        if self._is_running:
            self.stop_clicked.emit()
        else:
            self.start_clicked.emit()

    def set_sync_state(self, running: bool, mode_text: str = "") -> None:
        """Update button text, styling, and status badge."""
        self._is_running = running
        if running:
            self.toggle_btn.setText("⏹  STOP SYNCHRONIZATION")
            self.toggle_btn.setObjectName("stopSyncButton")
            self.toggle_btn.setStyle(self.toggle_btn.style())
            tag = f" ({mode_text})" if mode_text else ""
            self.status_badge.setText(f"STATUS: SYNCING LIVE{tag}")
            self.status_badge.setStyleSheet(
                "background-color: #064e3b; color: #34d399; border: 1px solid #059669; "
                "border-radius: 4px; padding: 4px 10px; font-weight: 700; font-size: 11px;"
            )
            self.dry_run_chk.setEnabled(False)
        else:
            self.set_mode(self._current_mode)
            self.toggle_btn.setObjectName("startSyncButton")
            self.toggle_btn.setStyle(self.toggle_btn.style())
            self.status_badge.setText("STATUS: STOPPED")
            self.status_badge.setStyleSheet(
                "background-color: #1e2025; color: #94a3b8; border: 1px solid #2d2f36; "
                "border-radius: 4px; padding: 4px 10px; font-weight: 700; font-size: 11px;"
            )
            self.dry_run_chk.setEnabled(True)

    def set_busy_state(self, text: str, allow_cancel: bool = False) -> None:
        """Set transitory state (e.g. Connecting...)."""
        self.status_badge.setText(f"STATUS: {text.upper()}")
        self.status_badge.setStyleSheet(
            "background-color: #78350f; color: #fbbf24; border: 1px solid #b45309; "
            "border-radius: 4px; padding: 4px 10px; font-weight: 700; font-size: 11px;"
        )
        if allow_cancel:
            self.toggle_btn.setText("⏹  CANCEL STARTUP")
            self.toggle_btn.setObjectName("stopSyncButton")
            self.toggle_btn.setStyle(self.toggle_btn.style())
            self.toggle_btn.setEnabled(True)
            self._is_running = True
        else:
            self.toggle_btn.setEnabled(False)

    def reset_button_enabled(self) -> None:
        self.toggle_btn.setEnabled(True)

    def update_telemetry(self, status: Optional[SyncStatus]) -> None:
        """Update color swatches and network command metrics."""
        if not status:
            return

        # Screen swatch (raw captured screen color)
        if hasattr(status, "screen_color") and status.screen_color and len(status.screen_color) == 3:
            sr, sg, sb = status.screen_color
            self.screen_swatch.setStyleSheet(
                f"background-color: rgb({sr}, {sg}, {sb}); border: 1px solid #4b5563; border-radius: 6px;"
            )
            self.screen_text.setText(f"RGB({sr:3d}, {sg:3d}, {sb:3d})")

        # Target swatch
        tgt = status.target_state
        if tgt and hasattr(tgt, "rgb") and hasattr(tgt.rgb, "__len__") and len(tgt.rgb) == 3:
            r, g, b = tgt.rgb
            self.tgt_swatch.setStyleSheet(
                f"background-color: rgb({r}, {g}, {b}); border: 1px solid #4b5563; border-radius: 6px;"
            )
            self.tgt_text.setText(f"RGB({r:3d}, {g:3d}, {b:3d}) @ {tgt.brightness}/255")

        # Applied swatch
        app = status.applied_state
        if app and hasattr(app, "rgb") and hasattr(app.rgb, "__len__") and len(app.rgb) == 3:
            ar, ag, ab = app.rgb
            self.app_swatch.setStyleSheet(
                f"background-color: rgb({ar}, {ag}, {ab}); border: 1px solid #4b5563; border-radius: 6px;"
            )
            self.app_text.setText(f"RGB({ar:3d}, {ag:3d}, {ab:3d}) @ {app.brightness}/255")

        # Telemetry metrics
        dur = status.last_command_duration_ms
        mode_str = " (Adaptive)" if getattr(status, "adaptive_rate", False) else ""
        p95_dur = getattr(status, "p95_duration_ms", 0.0)
        p95_str = f" (p95: {p95_dur:4.1f} ms)" if p95_dur > 0 else ""

        fps_str = ""
        if getattr(status, "sync_mode", "music") in ("screen", "hybrid"):
            fps = getattr(status, "screen_fps", 0.0)
            fps_str = f"Capture: {fps:4.1f} FPS | "

        self.telemetry_label.setText(
            f"{fps_str}Rate: {status.updates_per_second:4.1f} Hz{mode_str} | "
            f"Commands: {status.commands_sent} sent, {status.commands_failed} failed | "
            f"Latency: {dur:4.1f} ms{p95_str}"
        )
