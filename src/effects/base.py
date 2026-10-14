"""Base classes, configuration, and color math for music-reactive lighting effects."""

import colorsys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple

from src.audio.analyzer import AudioMetrics
from src.audio.beat_detector import AudioFocus
from src.sync.state import LightingState


@dataclass
class EffectSettings:
    """Configurable parameters governing music-to-light effect behavior."""

    sensitivity: float = 1.0  # Overall audio reactivity scale [0.1, 3.0]
    attack_speed: float = 0.45  # Rate of transition towards higher energy [0.01, 1.0]
    release_speed: float = 0.10  # Rate of decay towards baseline [0.01, 1.0]
    min_brightness: int = 25  # Minimum resting brightness [0, 255]
    max_brightness: int = 255  # Maximum peak brightness [0, 255]
    beat_strength: float = 1.0  # Multiplier for musical onset triggers [0.0, 2.0]
    color_smoothing: float = 0.30  # Exponential smoothing for RGB color transitions [0.0, 0.95]
    update_rate_hz: float = 4.0  # Target bulb command frequency [1.0, 10.0]
    audio_focus: AudioFocus = AudioFocus.FULL_MUSIC  # Audio focus mode (full, rhythm, kick)

    def validate(self) -> None:
        """Validate parameter ranges and relationships."""
        if not (0.1 <= self.sensitivity <= 3.0):
            raise ValueError(f"Sensitivity must be in range [0.1, 3.0], got {self.sensitivity}")
        if not (0.01 <= self.attack_speed <= 1.0):
            raise ValueError(f"Attack speed must be in range [0.01, 1.0], got {self.attack_speed}")
        if not (0.01 <= self.release_speed <= 1.0):
            raise ValueError(f"Release speed must be in range [0.01, 1.0], got {self.release_speed}")
        if not (0 <= self.min_brightness <= 255):
            raise ValueError(f"Min brightness must be in range [0, 255], got {self.min_brightness}")
        if not (0 <= self.max_brightness <= 255):
            raise ValueError(f"Max brightness must be in range [0, 255], got {self.max_brightness}")
        if self.min_brightness > self.max_brightness:
            raise ValueError(f"min_brightness ({self.min_brightness}) cannot exceed max_brightness ({self.max_brightness})")
        if not (0.0 <= self.beat_strength <= 2.0):
            raise ValueError(f"Beat strength must be in range [0.0, 2.0], got {self.beat_strength}")
        if not (0.0 <= self.color_smoothing <= 0.95):
            raise ValueError(f"Color smoothing must be in range [0.0, 0.95], got {self.color_smoothing}")
        if not (1.0 <= self.update_rate_hz <= 10.0):
            raise ValueError(f"Update rate must be in range [1.0, 10.0], got {self.update_rate_hz}")


class BaseMusicEffect(ABC):
    """Abstract base class for all music-reactive lighting effects."""

    name: str = "Base Effect"
    description: str = "Abstract base music effect"

    def __init__(self, settings: Optional[EffectSettings] = None) -> None:
        self.settings = settings or EffectSettings()
        self.settings.validate()
        self._current_rgb: Tuple[float, float, float] = (255.0, 255.0, 255.0)
        self._current_brightness: float = float(self.settings.min_brightness)
        self._last_time: float = time.perf_counter()

    @abstractmethod
    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        """Calculate target lighting state based on audio metrics.

        Args:
            metrics: Current frame AudioMetrics.
            current_time: High-precision timestamp.

        Returns:
            LightingState containing RGB and brightness.
        """
        pass

    def reset(self) -> None:
        """Reset internal envelope and color state."""
        self._current_rgb = (255.0, 255.0, 255.0)
        self._current_brightness = float(self.settings.min_brightness)
        self._last_time = time.perf_counter()

    @staticmethod
    def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
        """Convert HSV color [0.0-1.0] to 8-bit integer RGB tuple [0-255]."""
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
        return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))

    @staticmethod
    def blend_rgb(
        c1: Tuple[float, float, float],
        c2: Tuple[float, float, float],
        factor: float,
    ) -> Tuple[float, float, float]:
        """Linearly interpolate between two RGB color tuples."""
        f = max(0.0, min(1.0, factor))
        return (
            c1[0] + f * (c2[0] - c1[0]),
            c1[1] + f * (c2[1] - c1[1]),
            c1[2] + f * (c2[2] - c1[2]),
        )

    def clamp_brightness(self, value: float) -> int:
        """Scale and clamp brightness within configured min and max limits."""
        val = max(0.0, min(1.0, value))
        b = self.settings.min_brightness + val * (self.settings.max_brightness - self.settings.min_brightness)
        return max(0, min(255, int(round(b))))
