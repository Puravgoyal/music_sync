"""Audio output loopback device selection panel widget."""

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.audio.devices import AudioDevice, get_audio_output_devices, get_default_output_device


class AudioPanel(QGroupBox):
    """Panel managing Windows WASAPI system loopback audio output device selection."""

    device_changed = Signal(object)  # Optional[AudioDevice]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Audio Capture Source (Windows WASAPI Loopback)", parent)
        self._devices: List[AudioDevice] = []
        self._setup_ui()
        self.refresh_devices()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        top_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumHeight(32)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

        self.refresh_btn = QPushButton("Refresh Audio")
        self.refresh_btn.setMinimumHeight(32)
        self.refresh_btn.clicked.connect(self.refresh_devices)

        top_layout.addWidget(self.device_combo, stretch=3)
        top_layout.addWidget(self.refresh_btn, stretch=1)
        layout.addLayout(top_layout)

        # Device details label (Sample rate, channels, loopback mode)
        self.info_label = QLabel("Detecting audio outputs...")
        self.info_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.info_label)

    def refresh_devices(self, preferred_name: Optional[str] = None) -> None:
        """Enumerate active Windows output devices and update dropdown."""
        self._devices = get_audio_output_devices()
        default_dev = get_default_output_device()

        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if not self._devices:
            self.device_combo.addItem("No WASAPI loopback devices found", None)
            self.info_label.setText("No compatible output devices detected. Connect headphones or speakers.")
            self.info_label.setStyleSheet("color: #ef4444; font-size: 11px;")
            self.device_combo.blockSignals(False)
            return

        selected_idx = 0
        for idx, dev in enumerate(self._devices):
            is_def = default_dev and dev.index == default_dev.index
            tag = " [DEFAULT]" if is_def else ""
            label = f"{dev.name}{tag} ({dev.sample_rate}Hz, {dev.channels}ch)"
            self.device_combo.addItem(label, dev)

            if preferred_name and preferred_name.lower() in dev.name.lower():
                selected_idx = idx
            elif not preferred_name and is_def:
                selected_idx = idx

        self.device_combo.setCurrentIndex(selected_idx)
        self.device_combo.blockSignals(False)
        self._on_device_changed()

    def get_selected_device(self) -> Optional[AudioDevice]:
        """Return the currently selected AudioDevice object."""
        data = self.device_combo.currentData()
        if isinstance(data, AudioDevice):
            return data
        return None

    def _on_device_changed(self) -> None:
        dev = self.get_selected_device()
        if dev:
            self.info_label.setText(
                f"Loopback active on '{dev.name}' — {dev.sample_rate} Hz, {dev.channels} channel(s) (Zero mic capture)"
            )
            self.info_label.setStyleSheet("color: #10b981; font-size: 11px;")
            self.device_changed.emit(dev)
        else:
            self.info_label.setText("No output device selected.")
            self.info_label.setStyleSheet("color: #64748b; font-size: 11px;")
            self.device_changed.emit(None)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.device_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
