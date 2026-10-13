"""Music-reactive effects selection and tuning controls widget."""

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.effects import EffectSettings, list_effects


class EffectsPanel(QGroupBox):
    """Panel managing music-reactive lighting effects and DSP sensitivity parameters."""

    effect_changed = Signal(str)  # effect_name
    settings_changed = Signal(object)  # EffectSettings

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Music Reactive Effect & Tuning", parent)
        self._effects_data = list_effects()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Mode Selector
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Lighting Effect:")
        mode_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumHeight(32)
        for eff in self._effects_data:
            self.mode_combo.addItem(f"{eff['name']}", eff["id"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo, stretch=2)
        layout.addLayout(mode_layout)

        # Effect Description Box
        self.desc_label = QLabel()
        self.desc_label.setStyleSheet(
            "background-color: #121316; border: 1px solid #28292e; border-radius: 6px; padding: 8px; color: #94a3b8; font-size: 11px;"
        )
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        # Sliders Grid
        grid = QGridLayout()
        grid.setSpacing(10)

        # 1. Sensitivity (0.1 - 3.0)
        self.sens_slider, self.sens_val = self._create_slider(grid, 0, "Audio Sensitivity:", 10, 300, 100, "x")
        # 2. Max Brightness (0 - 255)
        self.max_b_slider, self.max_b_val = self._create_slider(grid, 1, "Max Brightness:", 10, 255, 255, "/255")
        # 3. Min Brightness (0 - 255)
        self.min_b_slider, self.min_b_val = self._create_slider(grid, 2, "Min Brightness:", 0, 255, 25, "/255")
        # 4. Color Smoothing (0.0 - 0.95)
        self.smooth_slider, self.smooth_val = self._create_slider(grid, 3, "Color Smoothing:", 0, 95, 30, "%")
        # 5. Attack Speed (0.01 - 1.0)
        self.attack_slider, self.attack_val = self._create_slider(grid, 4, "Attack Speed:", 1, 100, 45, "%")
        # 6. Release Speed (0.01 - 1.0)
        self.release_slider, self.release_val = self._create_slider(grid, 5, "Release Speed:", 1, 100, 10, "%")
        # 7. Beat Strength (0.0 - 2.0)
        self.beat_slider, self.beat_val = self._create_slider(grid, 6, "Beat Intensity:", 0, 200, 100, "%")
        # 8. Command Update Rate (1.0 - 10.0 Hz)
        self.rate_slider, self.rate_val = self._create_slider(grid, 7, "Bulb Update Rate:", 10, 100, 40, " Hz")

        layout.addLayout(grid)
        self._update_description()

    def _create_slider(
        self,
        grid: QGridLayout,
        row: int,
        label_text: str,
        min_val: int,
        max_val: int,
        default_val: int,
        unit: str,
    ) -> tuple[QSlider, QLabel]:
        name_lbl = QLabel(label_text)
        name_lbl.setStyleSheet("color: #cbd5e1;")

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)

        val_lbl = QLabel()
        val_lbl.setMinimumWidth(60)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_lbl.setStyleSheet("color: #6366f1; font-weight: 600;")

        grid.addWidget(name_lbl, row, 0)
        grid.addWidget(slider, row, 1)
        grid.addWidget(val_lbl, row, 2)

        def _on_change(val: int) -> None:
            if unit == "x":
                val_lbl.setText(f"{val / 100.0:.2f}x")
            elif unit == " Hz":
                val_lbl.setText(f"{val / 10.0:.1f} Hz")
            elif unit == "%":
                val_lbl.setText(f"{val}%")
            else:
                val_lbl.setText(f"{val}{unit}")
            self._notify_settings_changed()

        slider.valueChanged.connect(_on_change)
        _on_change(default_val)
        return slider, val_lbl

    def _on_mode_changed(self) -> None:
        self._update_description()
        eff_id = self.mode_combo.currentData()
        if eff_id:
            self.effect_changed.emit(eff_id)

    def _update_description(self) -> None:
        eff_id = self.mode_combo.currentData()
        for eff in self._effects_data:
            if eff["id"] == eff_id:
                self.desc_label.setText(eff["description"])
                break

    def get_selected_effect(self) -> str:
        data = self.mode_combo.currentData()
        return str(data) if data else "spectrum"

    def set_selected_effect(self, effect_name: str) -> None:
        for idx in range(self.mode_combo.count()):
            if self.mode_combo.itemData(idx) == effect_name:
                self.mode_combo.setCurrentIndex(idx)
                break

    def get_settings(self) -> EffectSettings:
        min_b = self.min_b_slider.value()
        max_b = self.max_b_slider.value()
        if min_b > max_b:
            min_b = max_b

        return EffectSettings(
            sensitivity=self.sens_slider.value() / 100.0,
            max_brightness=max_b,
            min_brightness=min_b,
            color_smoothing=self.smooth_slider.value() / 100.0,
            attack_speed=self.attack_slider.value() / 100.0,
            release_speed=self.release_slider.value() / 100.0,
            beat_strength=self.beat_slider.value() / 100.0,
            update_rate_hz=self.rate_slider.value() / 10.0,
        )

    def set_settings(self, settings: EffectSettings) -> None:
        self.sens_slider.setValue(int(settings.sensitivity * 100))
        self.max_b_slider.setValue(settings.max_brightness)
        self.min_b_slider.setValue(settings.min_brightness)
        self.smooth_slider.setValue(int(settings.color_smoothing * 100))
        self.attack_slider.setValue(int(settings.attack_speed * 100))
        self.release_slider.setValue(int(settings.release_speed * 100))
        self.beat_slider.setValue(int(settings.beat_strength * 100))
        self.rate_slider.setValue(int(settings.update_rate_hz * 10))

    def _notify_settings_changed(self) -> None:
        try:
            settings = self.get_settings()
            self.settings_changed.emit(settings)
        except Exception:
            pass
