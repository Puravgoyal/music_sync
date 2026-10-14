"""Hybrid Audio/Video synchronization configuration widget."""

from typing import Optional

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


class HybridPanel(QGroupBox):
    """Panel managing Hybrid AV synchronization parameters: video color + audio rhythm/loudness."""

    hybrid_settings_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Hybrid Audio + Video Fusion Settings", parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Principle summary
        info = QLabel(
            "Principle: Screen video determines bulb RGB color; Windows audio modulates subtle rhythmic brightness."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(info)

        # Hybrid Type Row
        type_layout = QHBoxLayout()
        type_label = QLabel("Hybrid Style:")
        type_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.type_combo = QComboBox()
        self.type_combo.setMinimumHeight(32)
        self.type_combo.addItem("Cinematic Hybrid (Gentle Loudness, Movies & TV)", "cinematic")
        self.type_combo.addItem("Rhythm Hybrid (Percussion Hits, Vocals Filtered)", "rhythm")
        self.type_combo.addItem("Kick Hybrid (Bass & Sub-bass Pulses)", "kick")
        self.type_combo.currentIndexChanged.connect(lambda: self.hybrid_settings_changed.emit())

        type_layout.addWidget(type_label)
        type_layout.addWidget(self.type_combo, stretch=2)
        layout.addLayout(type_layout)

        # Audio Focus Row
        focus_layout = QHBoxLayout()
        focus_label = QLabel("Audio Focus:")
        focus_label.setStyleSheet("font-weight: 600; color: #f8fafc;")

        self.focus_combo = QComboBox()
        self.focus_combo.setMinimumHeight(32)
        self.focus_combo.addItem("Full Music (All Bands & Onsets)", "full")
        self.focus_combo.addItem("Rhythm Focus (Drum & Percussion Isolation)", "rhythm")
        self.focus_combo.addItem("Kick Focus (Low-Frequency Bass Hits)", "kick")
        self.focus_combo.currentIndexChanged.connect(lambda: self.hybrid_settings_changed.emit())

        focus_layout.addWidget(focus_label)
        focus_layout.addWidget(self.focus_combo, stretch=2)
        layout.addLayout(focus_layout)

        # Sliders Grid
        sliders_grid = QGridLayout()
        sliders_grid.setHorizontalSpacing(10)
        sliders_grid.setVerticalSpacing(8)

        # Audio Contribution Slider
        contrib_lbl = QLabel("Audio Modulation Strength:")
        contrib_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.contrib_val = QLabel("35%")
        self.contrib_val.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        self.contrib_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrib_slider.setRange(0, 100)
        self.contrib_slider.setValue(35)
        self.contrib_slider.valueChanged.connect(self._on_contrib_changed)
        sliders_grid.addWidget(contrib_lbl, 0, 0)
        sliders_grid.addWidget(self.contrib_slider, 0, 1)
        sliders_grid.addWidget(self.contrib_val, 0, 2)

        # Beat Intensity Slider
        beat_lbl = QLabel("Rhythmic Pulse Intensity:")
        beat_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.beat_val = QLabel("1.0x")
        self.beat_val.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        self.beat_slider = QSlider(Qt.Orientation.Horizontal)
        self.beat_slider.setRange(0, 20)  # 0.0 to 2.0 in steps of 0.1
        self.beat_slider.setValue(10)
        self.beat_slider.valueChanged.connect(self._on_beat_changed)
        sliders_grid.addWidget(beat_lbl, 1, 0)
        sliders_grid.addWidget(self.beat_slider, 1, 1)
        sliders_grid.addWidget(self.beat_val, 1, 2)

        layout.addLayout(sliders_grid)

    def _on_contrib_changed(self, val: int) -> None:
        self.contrib_val.setText(f"{val}%")
        self.hybrid_settings_changed.emit()

    def _on_beat_changed(self, val: int) -> None:
        self.beat_val.setText(f"{val / 10.0:.1f}x")
        self.hybrid_settings_changed.emit()

    # Getters and Setters
    def get_hybrid_type(self) -> str:
        return str(self.type_combo.currentData() or "cinematic")

    def set_hybrid_type(self, h_type: str) -> None:
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == h_type:
                self.type_combo.setCurrentIndex(i)
                return

    def get_audio_focus(self) -> str:
        return str(self.focus_combo.currentData() or "full")

    def set_audio_focus(self, focus: str) -> None:
        for i in range(self.focus_combo.count()):
            if self.focus_combo.itemData(i) == focus:
                self.focus_combo.setCurrentIndex(i)
                return

    def get_audio_contribution(self) -> float:
        return float(self.contrib_slider.value()) / 100.0

    def set_audio_contribution(self, contrib: float) -> None:
        val = int(round(contrib * 100))
        self.contrib_slider.setValue(max(0, min(100, val)))
        self.contrib_val.setText(f"{self.contrib_slider.value()}%")

    def get_beat_intensity(self) -> float:
        return float(self.beat_slider.value()) / 10.0

    def set_beat_intensity(self, intensity: float) -> None:
        val = int(round(intensity * 10))
        self.beat_slider.setValue(max(0, min(20, val)))
        self.beat_val.setText(f"{self.beat_slider.value() / 10.0:.1f}x")
