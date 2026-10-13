"""Mode 4: Smooth Spectrum - Spectral balance mapped to continuously blending HSV hue."""

from typing import Tuple

from src.audio.analyzer import AudioMetrics
from src.effects.base import BaseMusicEffect, EffectSettings
from src.sync.state import LightingState


class SmoothSpectrumEffect(BaseMusicEffect):
    """Gradually shifts hue according to spectral frequency balance while tracking loudness.

    Prevents abrupt color jumping by interpolating hue along the circular color wheel.
    """

    name: str = "Smooth Spectrum"
    description: str = "Smooth hue shifts guided by spectral balance with loudness brightness"

    def __init__(self, settings: EffectSettings | None = None) -> None:
        super().__init__(settings)
        self._current_hue: float = 0.60  # Start at calm blue
        self._current_saturation: float = 0.90

    def reset(self) -> None:
        super().reset()
        self._current_hue = 0.60
        self._current_saturation = 0.90

    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        dt = max(0.001, current_time - self._last_time)
        self._last_time = current_time

        if metrics.is_silent:
            # Smoothly decay brightness towards resting level, maintain current hue
            target_b = float(self.settings.min_brightness)
            decay = min(1.0, self.settings.release_speed * dt * 20.0)
            self._current_brightness += decay * (target_b - self._current_brightness)
        else:
            # Calculate spectral balance / centroid estimate [0.0 - 1.0]
            # Bass gives warm/red (0.0), Mid gives green/cyan (0.35), Treble gives blue/violet (0.7)
            b = metrics.bass * self.settings.sensitivity
            m = metrics.mid * self.settings.sensitivity
            t = metrics.treble * self.settings.sensitivity
            total = b + m + t

            if total > 1e-4:
                # Weighted center: 0.0 (bass) -> 0.35 (mid) -> 0.70 (treble)
                target_hue = (b * 0.02 + m * 0.35 + t * 0.70) / total
            else:
                target_hue = self._current_hue

            # Circular shortest-distance interpolation for hue
            diff = (target_hue - self._current_hue + 0.5) % 1.0 - 0.5
            # Heavy smoothing for seamless transitions without jumps
            hue_speed = min(1.0, (1.0 - self.settings.color_smoothing * 0.8) * dt * 4.0)
            self._current_hue = (self._current_hue + diff * hue_speed) % 1.0

            # Loudness modulates brightness with attack/release smoothing
            target_b = float(self.clamp_brightness(metrics.loudness * self.settings.sensitivity))
            if target_b > self._current_brightness:
                b_smooth = min(1.0, self.settings.attack_speed * dt * 35.0)
            else:
                b_smooth = min(1.0, self.settings.release_speed * dt * 20.0)
            self._current_brightness += b_smooth * (target_b - self._current_brightness)

        rgb = self.hsv_to_rgb(self._current_hue, self._current_saturation, 1.0)
        final_b = max(0, min(255, int(round(self._current_brightness))))

        return LightingState(rgb=rgb, brightness=final_b, is_on=True, timestamp=current_time)
