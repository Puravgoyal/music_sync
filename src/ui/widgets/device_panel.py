"""Device connection and bulb discovery panel widget."""

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.wiz.discovery import DiscoveredDevice


class DevicePanel(QGroupBox):
    """Panel managing WiZ bulb network discovery, selection, and connection status."""

    scan_requested = Signal()
    test_requested = Signal(str)  # bulb_ip
    bulb_selected = Signal(str, str)  # (ip, mac)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("WiZ Smart Bulb Connection", parent)
        self._discovered_bulbs: List[DiscoveredDevice] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Dropdown selection + Scan button
        drop_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumHeight(32)
        self.device_combo.currentIndexChanged.connect(self._on_combo_changed)

        self.scan_btn = QPushButton("Scan Network")
        self.scan_btn.setMinimumHeight(32)
        self.scan_btn.clicked.connect(self.scan_requested.emit)

        drop_layout.addWidget(self.device_combo, stretch=3)
        drop_layout.addWidget(self.scan_btn, stretch=1)
        layout.addLayout(drop_layout)

        # Manual IP input + Test button
        manual_layout = QHBoxLayout()
        manual_label = QLabel("Manual IP:")
        manual_label.setStyleSheet("color: #94a3b8;")
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("e.g. 192.168.1.4")
        self.ip_edit.setMinimumHeight(30)
        self.ip_edit.textChanged.connect(self._on_manual_ip_changed)

        self.test_btn = QPushButton("Test")
        self.test_btn.setMinimumHeight(30)
        self.test_btn.clicked.connect(self._on_test_clicked)

        manual_layout.addWidget(manual_label)
        manual_layout.addWidget(self.ip_edit, stretch=2)
        manual_layout.addWidget(self.test_btn, stretch=1)
        layout.addLayout(manual_layout)

        # Status and Profile Information Label
        self.status_label = QLabel("Ready to connect. Click Scan to discover local WiZ bulbs.")
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def set_discovered_bulbs(self, bulbs: List[DiscoveredDevice], default_ip: Optional[str] = None) -> None:
        """Populate the dropdown with newly discovered bulbs."""
        self._discovered_bulbs = bulbs
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if not bulbs:
            self.device_combo.addItem("No bulbs found (use manual IP below)", "")
            self.status_label.setText("No bulbs found via broadcast. Check 2.4GHz Wi-Fi or enter IP manually.")
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
        else:
            selected_idx = 0
            for idx, bulb in enumerate(bulbs):
                model = bulb.model or "WiZ Bulb"
                mac_str = f" [{bulb.mac}]" if bulb.mac else ""
                label = f"{bulb.ip} — {model}{mac_str}"
                self.device_combo.addItem(label, bulb.ip)
                if default_ip and bulb.ip == default_ip:
                    selected_idx = idx

            self.device_combo.setCurrentIndex(selected_idx)
            self.status_label.setText(f"Found {len(bulbs)} WiZ bulb(s) on local network.")
            self.status_label.setStyleSheet("color: #10b981; font-size: 11px;")

        self.device_combo.blockSignals(False)
        self._on_combo_changed()

    def get_selected_ip(self) -> Optional[str]:
        """Return the active bulb IP (manual edit takes priority if entered)."""
        manual = self.ip_edit.text().strip()
        if manual:
            return manual
        data = self.device_combo.currentData()
        if data and isinstance(data, str) and data:
            return data
        return None

    def set_manual_ip(self, ip: str) -> None:
        self.ip_edit.setText(ip)

    def set_status(self, text: str, is_error: bool = False, is_success: bool = False) -> None:
        self.status_label.setText(text)
        if is_error:
            self.status_label.setStyleSheet("color: #ef4444; font-size: 11px;")
        elif is_success:
            self.status_label.setStyleSheet("color: #10b981; font-size: 11px;")
        else:
            self.status_label.setStyleSheet("color: #94a3b8; font-size: 11px;")

    def _on_combo_changed(self) -> None:
        ip = self.device_combo.currentData()
        if ip:
            mac = ""
            for b in self._discovered_bulbs:
                if b.ip == ip and b.mac:
                    mac = b.mac
                    break
            self.bulb_selected.emit(ip, mac)

    def _on_manual_ip_changed(self, text: str) -> None:
        ip = text.strip()
        if ip:
            self.bulb_selected.emit(ip, "")

    def _on_test_clicked(self) -> None:
        target = self.get_selected_ip()
        if target:
            self.set_status(f"Testing connection to {target}...")
            self.test_requested.emit(target)
        else:
            self.set_status("Please specify a bulb IP address to test.", is_error=True)

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable device configuration during active synchronization."""
        self.device_combo.setEnabled(enabled)
        self.scan_btn.setEnabled(enabled)
        self.ip_edit.setEnabled(enabled)
        self.test_btn.setEnabled(enabled)
