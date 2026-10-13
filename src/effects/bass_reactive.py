"""Mode 3: Bass Reactive - Low-frequency energy driving dynamic brightness and warm hue shifts."""

from typing import Tuple

from src.audio.analyzer import AudioMetrics
from src.effects.base import BaseMusicEffect
from src.sync.state import LightingState


class BassReactiveEffect(BaseMusicEffect):
    """Sub-bass and kick-drum focused effect with dynamic red-to-amber-to-magenta hue shifting."""

    name: str = "Bass Reactive"
    description: str = "Responds dynamically to low-frequency kick drums and basslines"

    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        dt = max(0.001, current_time - self._last_time)
        self._last_time = current_time

        bass_energy = min(1.0, metrics.bass * self.settings.sensitivity)

        if metrics.is_silent or bass_energy < 0.02:
            target_b = float(self.settings.min_brightness)
            decay = min(1.0, self.settings.release_speed * dt * 25.0)
            self._current_brightness += decay * (target_b - self._current_brightness)
            # Resting soft violet
            resting_rgb = (120.0, 30.0, 180.0)
            self._current_rgb = self.blend_rgb(self._current_rgb, resting_rgb, decay)
        else:
            # Map bass intensity to brightness
            target_b = float(self.clamp_brightness(bass_energy))
            if target_b > self._current_brightness:
                b_smooth = min(1.0, self.settings.attack_speed * dt * 55.0)
            else:
                b_smooth = min(1.0, self.settings.release_speed * dt * 25.0)
            self._current_brightness += b_smooth * (target_b - self._current_brightness)

            # Map bass intensity to hue:
            # Low bass -> Crimson/Magenta (0.95), High punch -> Fiery Orange/Red (0.02 to 0.08)
            hue = 0.95 - (bass_energy * 0.90)
            if hue < 0.0:
                hue += 1.0
            r, g, b = self.hsv_to_rgb(hue, 1.0, 1.0)
            target_rgb = (float(r), float(g), float(b))

            smooth = min(1.0, max(0.05, 1.0 - self.settings.color_smoothing))
            self._current_rgb = self.blend_rgb(self._current_rgb, target_rgb, smooth)

        final_rgb = (
            max(0, min(255, int(round(self._current_rgb[0])))),
            max(0, min(255, int(round(self._current_rgb[1])))),
            max(0, min(255, int(round(self._current_rgb[2])))),
        )
        final_b = max(0, min(255, int(round(self._current_brightness))))

        return LightingState(rgb=final_rgb, brightness=final_b, is_on=True, timestamp=current_time)
