"""Screen capture monitor selection and ambilight tuning panel widget."""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.screen.devices import ScreenMonitor, get_available_monitors


class ScreenPanel(QGroupBox):
    """Panel managing Windows screen capture source, color extraction, edge zones, and smoothing."""

    monitor_changed = Signal(int)
    settings_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Screen Ambience & Capture Controls", parent)
        self._monitors: List[ScreenMonitor] = []
        self._setup_ui()
        self.refresh_monitors()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Monitor Selector Row
        mon_layout = QHBoxLayout()
        mon_label = QLabel("Display:")
        mon_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumHeight(32)
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)

        self.refresh_btn = QPushButton("Refresh Displays")
        self.refresh_btn.setMinimumHeight(32)
        self.refresh_btn.clicked.connect(self.refresh_monitors)

        mon_layout.addWidget(mon_label)
        mon_layout.addWidget(self.monitor_combo, stretch=3)
        mon_layout.addWidget(self.refresh_btn, stretch=1)
        layout.addLayout(mon_layout)

        # Monitor details
        self.monitor_info = QLabel("Detecting displays...")
        self.monitor_info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.monitor_info)

        # Extraction Strategy Row
        strat_layout = QHBoxLayout()
        strat_label = QLabel("Color Strategy:")
        strat_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.strat_combo = QComboBox()
        self.strat_combo.setMinimumHeight(32)
        self.strat_combo.addItem("Average Screen Color (Linear sRGB)", "average")
        self.strat_combo.addItem("Dominant Color (Saliency-Weighted)", "dominant")
        self.strat_combo.addItem("Edge-Based Ambience (Directional Bias)", "edge")
        self.strat_combo.currentIndexChanged.connect(self._on_strategy_changed)

        strat_layout.addWidget(strat_label)
        strat_layout.addWidget(self.strat_combo, stretch=2)
        layout.addLayout(strat_layout)

        # Edge Configuration Container (shown when 'edge' is selected)
        self.edge_widget = QWidget()
        edge_layout = QVBoxLayout(self.edge_widget)
        edge_layout.setContentsMargins(0, 4, 0, 4)
        edge_layout.setSpacing(8)

        edge_row = QHBoxLayout()
        edge_row_lbl = QLabel("Screen Edge:")
        edge_row_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")

        self.edge_combo = QComboBox()
        self.edge_combo.setMinimumHeight(28)
        self.edge_combo.addItem("All Edges (Perimeter)", "all")
        self.edge_combo.addItem("Right Edge (Bulb right of screen)", "right")
        self.edge_combo.addItem("Left Edge (Bulb left of screen)", "left")
        self.edge_combo.addItem("Top Edge", "top")
        self.edge_combo.addItem("Bottom Edge", "bottom")
        self.edge_combo.currentIndexChanged.connect(lambda: self.settings_changed.emit())

        edge_row.addWidget(edge_row_lbl)
        edge_row.addWidget(self.edge_combo, stretch=2)
        edge_layout.addLayout(edge_row)

        thick_row = QHBoxLayout()
        thick_lbl = QLabel("Edge Thickness:")
        thick_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.thick_val_lbl = QLabel("15%")
        self.thick_val_lbl.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        self.thick_slider = QSlider(Qt.Orientation.Horizontal)
        self.thick_slider.setRange(5, 40)
        self.thick_slider.setValue(15)
        self.thick_slider.valueChanged.connect(self._on_thickness_changed)

        thick_row.addWidget(thick_lbl)
        thick_row.addWidget(self.thick_slider, stretch=2)
        thick_row.addWidget(self.thick_val_lbl)
        edge_layout.addLayout(thick_row)

        layout.addWidget(self.edge_widget)
        self.edge_widget.setVisible(False)

        # Smoothing Preset Row
        smooth_layout = QHBoxLayout()
        smooth_label = QLabel("Motion Smoothing:")
        smooth_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.smooth_combo = QComboBox()
        self.smooth_combo.setMinimumHeight(32)
        self.smooth_combo.addItem("Cinematic Smooth (Filmic & Gentle)", "cinematic")
        self.smooth_combo.addItem("Balanced (Standard Videos & Streaming)", "balanced")
        self.smooth_combo.addItem("Responsive (Fast Games & Action)", "responsive")
        self.smooth_combo.currentIndexChanged.connect(lambda: self.settings_changed.emit())

        smooth_layout.addWidget(smooth_label)
        smooth_layout.addWidget(self.smooth_combo, stretch=2)
        layout.addLayout(smooth_layout)

        # Black-Bar Detection Checkbox
        self.black_bar_chk = QCheckBox("Exclude black letterbox/pillarbox borders")
        self.black_bar_chk.setChecked(True)
        self.black_bar_chk.toggled.connect(lambda: self.settings_changed.emit())
        layout.addWidget(self.black_bar_chk)

        # Sliders Grid (Min / Max Brightness)
        sliders_grid = QGridLayout()
        sliders_grid.setHorizontalSpacing(10)
        sliders_grid.setVerticalSpacing(8)

        # Min Brightness
        min_b_lbl = QLabel("Resting Brightness (Dark Scenes):")
        min_b_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.min_b_val = QLabel("25")
        self.min_b_val.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        self.min_b_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_b_slider.setRange(0, 100)
        self.min_b_slider.setValue(25)
        self.min_b_slider.valueChanged.connect(self._on_min_b_changed)
        sliders_grid.addWidget(min_b_lbl, 0, 0)
        sliders_grid.addWidget(self.min_b_slider, 0, 1)
        sliders_grid.addWidget(self.min_b_val, 0, 2)

        # Max Brightness
        max_b_lbl = QLabel("Maximum Peak Brightness:")
        max_b_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.max_b_val = QLabel("255")
        self.max_b_val.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        self.max_b_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_b_slider.setRange(50, 255)
        self.max_b_slider.setValue(255)
        self.max_b_slider.valueChanged.connect(self._on_max_b_changed)
        sliders_grid.addWidget(max_b_lbl, 1, 0)
        sliders_grid.addWidget(self.max_b_slider, 1, 1)
        sliders_grid.addWidget(self.max_b_val, 1, 2)

        layout.addLayout(sliders_grid)

    def refresh_monitors(self, preferred_index: Optional[int] = None) -> None:
        """Enumerate display monitors and update dropdown."""
        self._monitors = get_available_monitors()

        self.monitor_combo.blockSignals(True)
        self.monitor_combo.clear()

        selected_idx = 0
        for i, mon in enumerate(self._monitors):
            self.monitor_combo.addItem(mon.display_name, mon.index)
            if preferred_index is not None and mon.index == preferred_index:
                selected_idx = i
            elif preferred_index is None and mon.is_primary:
                selected_idx = i

        if self._monitors:
            self.monitor_combo.setCurrentIndex(selected_idx)
            self._update_monitor_info(self._monitors[selected_idx])
        else:
            self.monitor_info.setText("No active displays detected.")

        self.monitor_combo.blockSignals(False)

    def _on_monitor_changed(self, combo_idx: int) -> None:
        if 0 <= combo_idx < len(self._monitors):
            mon = self._monitors[combo_idx]
            self._update_monitor_info(mon)
            self.monitor_changed.emit(mon.index)
            self.settings_changed.emit()

    def _update_monitor_info(self, mon: ScreenMonitor) -> None:
        scale_pct = int(round(mon.device_pixel_ratio * 100))
        pri_str = "Yes" if mon.is_primary else "No"
        self.monitor_info.setText(
            f"Bounds: ({mon.x}, {mon.y}, {mon.width}x{mon.height}) | Scale: {scale_pct}% | Primary: {pri_str}"
        )

    def _on_strategy_changed(self, idx: int) -> None:
        strat = self.strat_combo.currentData()
        self.edge_widget.setVisible(strat == "edge")
        self.settings_changed.emit()

    def _on_thickness_changed(self, val: int) -> None:
        self.thick_val_lbl.setText(f"{val}%")
        self.settings_changed.emit()

    def _on_min_b_changed(self, val: int) -> None:
        if val > self.max_b_slider.value():
            self.max_b_slider.setValue(val)
        self.min_b_val.setText(str(val))
        self.settings_changed.emit()

    def _on_max_b_changed(self, val: int) -> None:
        if val < self.min_b_slider.value():
            self.min_b_slider.setValue(val)
        self.max_b_val.setText(str(val))
        self.settings_changed.emit()

    # Getters and Setters
    def get_selected_monitor_index(self) -> int:
        data = self.monitor_combo.currentData()
        return int(data) if data is not None else 0

    def set_selected_monitor_index(self, index: int) -> None:
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == index:
                self.monitor_combo.setCurrentIndex(i)
                return

    def get_color_strategy(self) -> str:
        return str(self.strat_combo.currentData() or "average")

    def set_color_strategy(self, strat: str) -> None:
        for i in range(self.strat_combo.count()):
            if self.strat_combo.itemData(i) == strat:
                self.strat_combo.setCurrentIndex(i)
                self.edge_widget.setVisible(strat == "edge")
                return

    def get_edge_region(self) -> str:
        return str(self.edge_combo.currentData() or "all")

    def set_edge_region(self, region: str) -> None:
        for i in range(self.edge_combo.count()):
            if self.edge_combo.itemData(i) == region:
                self.edge_combo.setCurrentIndex(i)
                return

    def get_edge_thickness(self) -> float:
        return float(self.thick_slider.value()) / 100.0

    def set_edge_thickness(self, thickness: float) -> None:
        val = int(round(thickness * 100))
        self.thick_slider.setValue(max(5, min(40, val)))
        self.thick_val_lbl.setText(f"{self.thick_slider.value()}%")

    def get_smoothing_preset(self) -> str:
        return str(self.smooth_combo.currentData() or "cinematic")

    def set_smoothing_preset(self, preset: str) -> None:
        for i in range(self.smooth_combo.count()):
            if self.smooth_combo.itemData(i) == preset:
                self.smooth_combo.setCurrentIndex(i)
                return

    def get_detect_black_bars(self) -> bool:
        return self.black_bar_chk.isChecked()

    def set_detect_black_bars(self, enabled: bool) -> None:
        self.black_bar_chk.setChecked(enabled)

    def get_min_brightness(self) -> int:
        return self.min_b_slider.value()

    def get_max_brightness(self) -> int:
        return self.max_b_slider.value()

    def set_brightness_range(self, min_b: int, max_b: int) -> None:
        self.min_b_slider.setValue(min_b)
        self.max_b_slider.setValue(max_b)
        self.min_b_val.setText(str(min_b))
        self.max_b_val.setText(str(max_b))

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable monitor selection during active sync."""
        self.monitor_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
