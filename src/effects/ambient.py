"""Mode 5: Ambient Flow - Slow, atmospheric color drift gently modulated by audio energy."""

from typing import Tuple

from src.audio.analyzer import AudioMetrics
from src.effects.base import BaseMusicEffect, EffectSettings
from src.sync.state import LightingState


class AmbientFlowEffect(BaseMusicEffect):
    """Slow atmospheric color transitions influenced gently by music spectrum and volume.

    Designed for relaxing background illumination without flashing or abrupt shifts.
    """

    name: str = "Ambient Flow"
    description: str = "Slow, atmospheric color transitions gently modulated by music"

    def __init__(self, settings: EffectSettings | None = None) -> None:
        super().__init__(settings)
        self._current_hue: float = 0.55  # Serene cyan-blue
        self._drift_rate: float = 0.02  # Baseline revolutions per second

    def reset(self) -> None:
        super().reset()
        self._current_hue = 0.55

    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        dt = max(0.001, current_time - self._last_time)
        self._last_time = current_time

        # Baseline gentle hue drift
        speed_factor = 1.0 + (metrics.loudness * self.settings.sensitivity * 1.5 if not metrics.is_silent else 0.0)
        self._current_hue = (self._current_hue + self._drift_rate * speed_factor * dt) % 1.0

        if metrics.is_silent:
            # Very slow decay towards min brightness
            target_b = float(self.settings.min_brightness)
            decay = min(1.0, self.settings.release_speed * dt * 10.0)
            self._current_brightness += decay * (target_b - self._current_brightness)
            saturation = 0.70
        else:
            # Brightness undulates gently between min and max based on smoothed loudness
            energy = min(1.0, metrics.loudness * self.settings.sensitivity)
            target_b = float(self.clamp_brightness(energy))
            # Extremely smooth brightness response
            smooth_rate = min(1.0, 0.15 * dt * 20.0)
            self._current_brightness += smooth_rate * (target_b - self._current_brightness)

            # High bass adds warmth (pulls towards deeper saturation), treble softens
            saturation = 0.75 + 0.20 * min(1.0, metrics.bass) - 0.10 * min(1.0, metrics.treble)
            saturation = max(0.5, min(1.0, saturation))

        rgb = self.hsv_to_rgb(self._current_hue, saturation, 1.0)
        final_b = max(0, min(255, int(round(self._current_brightness))))

        return LightingState(rgb=rgb, brightness=final_b, is_on=True, timestamp=current_time)
