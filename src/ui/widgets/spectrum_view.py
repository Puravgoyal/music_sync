"""Live audio spectrum frequency bars and beat onset visualizer widget."""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.audio.analyzer import AudioMetrics


class SpectrumView(QGroupBox):
    """Compact live audio frequency bars and musical beat onset visualization."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Live Audio Spectrum & Rhythm", parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(6)

        # Bass bar
        b_lbl = QLabel("Bass (20-250 Hz):")
        b_lbl.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 11px;")
        self.bass_bar = QProgressBar()
        self.bass_bar.setRange(0, 100)
        self.bass_bar.setStyleSheet("QProgressBar::chunk { background-color: #ef4444; }")
        grid.addWidget(b_lbl, 0, 0)
        grid.addWidget(self.bass_bar, 0, 1)

        # Mid bar
        m_lbl = QLabel("Mid (250-4000 Hz):")
        m_lbl.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
        self.mid_bar = QProgressBar()
        self.mid_bar.setRange(0, 100)
        self.mid_bar.setStyleSheet("QProgressBar::chunk { background-color: #10b981; }")
        grid.addWidget(m_lbl, 1, 0)
        grid.addWidget(self.mid_bar, 1, 1)

        # Treble bar
        t_lbl = QLabel("Treble (4-16 kHz):")
        t_lbl.setStyleSheet("color: #3b82f6; font-weight: 600; font-size: 11px;")
        self.treble_bar = QProgressBar()
        self.treble_bar.setRange(0, 100)
        self.treble_bar.setStyleSheet("QProgressBar::chunk { background-color: #3b82f6; }")
        grid.addWidget(t_lbl, 2, 0)
        grid.addWidget(self.treble_bar, 2, 1)

        # Volume / Loudness bar
        v_lbl = QLabel("Master Loudness:")
        v_lbl.setStyleSheet("color: #f59e0b; font-weight: 600; font-size: 11px;")
        self.vol_bar = QProgressBar()
        self.vol_bar.setRange(0, 100)
        self.vol_bar.setStyleSheet("QProgressBar::chunk { background-color: #f59e0b; }")
        grid.addWidget(v_lbl, 3, 0)
        grid.addWidget(self.vol_bar, 3, 1)

        layout.addLayout(grid)

        # Beat Onset Badge
        beat_layout = QHBoxLayout()
        beat_layout.addStretch()
        self.beat_badge = QLabel("Rhythm Steady")
        self.beat_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.beat_badge.setStyleSheet(
            "background-color: #1c1d22; color: #64748b; border: 1px solid #2d2f36; "
            "border-radius: 4px; padding: 4px 14px; font-weight: 700; font-size: 11px;"
        )
        beat_layout.addWidget(self.beat_badge)
        beat_layout.addStretch()
        layout.addLayout(beat_layout)

    def update_metrics(self, metrics: Optional[AudioMetrics]) -> None:
        """Update live progress bars and beat badge from current AudioMetrics."""
        if not metrics:
            self.bass_bar.setValue(0)
            self.mid_bar.setValue(0)
            self.treble_bar.setValue(0)
            self.vol_bar.setValue(0)
            self._set_beat_inactive()
            return

        self.bass_bar.setValue(min(100, int(metrics.bass * 100)))
        self.mid_bar.setValue(min(100, int(metrics.mid * 100)))
        self.treble_bar.setValue(min(100, int(metrics.treble * 100)))
        self.vol_bar.setValue(min(100, int(metrics.loudness * 100)))

        focus = getattr(metrics, "audio_focus", "full")
        focus_val = getattr(focus, "value", str(focus))

        if not metrics.is_silent:
            if focus_val == "kick" and getattr(metrics, "is_kick", False):
                self.beat_badge.setText("⚡ KICK HIT!")
                self.beat_badge.setStyleSheet(
                    "background-color: #ef4444; color: #ffffff; border: 1px solid #f87171; "
                    "border-radius: 4px; padding: 4px 14px; font-weight: 800; font-size: 11px;"
                )
                return
            elif focus_val == "rhythm" and getattr(metrics, "is_percussion", False):
                self.beat_badge.setText("⚡ PERCUSSION HIT!")
                self.beat_badge.setStyleSheet(
                    "background-color: #8b5cf6; color: #ffffff; border: 1px solid #a78bfa; "
                    "border-radius: 4px; padding: 4px 14px; font-weight: 800; font-size: 11px;"
                )
                return
            elif metrics.is_onset:
                self.beat_badge.setText("⚡ BEAT DETECTED!")
                self.beat_badge.setStyleSheet(
                    "background-color: #f59e0b; color: #000000; border: 1px solid #fbbf24; "
                    "border-radius: 4px; padding: 4px 14px; font-weight: 800; font-size: 11px;"
                )
                return

        self._set_beat_inactive(focus_val)

    def _set_beat_inactive(self, focus_name: str = "full") -> None:
        title = f"Tracking ({focus_name.capitalize()})" if focus_name != "full" else "Rhythm Tracking"
        self.beat_badge.setText(title)
        self.beat_badge.setStyleSheet(
            "background-color: #18191d; color: #64748b; border: 1px solid #28292e; "
            "border-radius: 4px; padding: 4px 14px; font-weight: 600; font-size: 11px;"
        )
