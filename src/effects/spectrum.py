"""Mode 1: Spectrum RGB - Frequency-mapped color mixing (Bass=Red, Mid=Green, Treble=Blue)."""

from typing import Tuple

from src.audio.analyzer import AudioMetrics
from src.effects.base import BaseMusicEffect, EffectSettings
from src.sync.state import LightingState


class SpectrumRGBEffect(BaseMusicEffect):
    """Maps tri-band audio energy directly to RGB channels with balanced normalization.

    Bass (20-250 Hz)   -> Red
    Mid (250-4000 Hz)  -> Green
    Treble (4000-16000)-> Blue
    """

    name: str = "Spectrum RGB"
    description: str = "Tri-band spectrum: Bass->Red, Mid->Green, Treble->Blue"

    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        dt = max(0.001, current_time - self._last_time)
        self._last_time = current_time

        if metrics.is_silent:
            # Decay smoothly towards resting brightness and warm amber/soft white
            target_b = float(self.settings.min_brightness)
            decay_factor = min(1.0, self.settings.release_speed * dt * 40.0)
            self._current_brightness += decay_factor * (target_b - self._current_brightness)
            # Gentle resting warm color
            resting_color = (255.0, 180.0, 100.0)
            self._current_rgb = self.blend_rgb(self._current_rgb, resting_color, decay_factor)
            return LightingState(
                rgb=(int(round(self._current_rgb[0])), int(round(self._current_rgb[1])), int(round(self._current_rgb[2]))),
                brightness=max(0, min(255, int(round(self._current_brightness)))),
                is_on=True,
                timestamp=current_time,
            )

        # Scale raw bands with sensitivity
        b_raw = metrics.bass * self.settings.sensitivity
        m_raw = metrics.mid * self.settings.sensitivity
        t_raw = metrics.treble * self.settings.sensitivity

        # Proportional balance normalization: prevent one loud band from monopolizing
        sum_energy = b_raw + m_raw + t_raw
        if sum_energy > 1e-4:
            # Mix proportion + raw intensity
            r_target = min(255.0, max(20.0, (b_raw / sum_energy * 0.7 + b_raw * 0.3) * 255.0))
            g_target = min(255.0, max(20.0, (m_raw / sum_energy * 0.7 + m_raw * 0.3) * 255.0))
            b_target = min(255.0, max(20.0, (t_raw / sum_energy * 0.7 + t_raw * 0.3) * 255.0))
        else:
            r_target, g_target, b_target = 128.0, 128.0, 128.0

        # Apply exponential smoothing to RGB channels
        smooth = min(1.0, max(0.05, 1.0 - self.settings.color_smoothing))
        self._current_rgb = self.blend_rgb(self._current_rgb, (r_target, g_target, b_target), smooth)

        # Loudness modulates brightness
        target_b = float(self.clamp_brightness(metrics.loudness * self.settings.sensitivity))
        if target_b > self._current_brightness:
            b_smooth = min(1.0, self.settings.attack_speed * dt * 45.0)
        else:
            b_smooth = min(1.0, self.settings.release_speed * dt * 35.0)
        self._current_brightness += b_smooth * (target_b - self._current_brightness)

        final_rgb = (
            max(0, min(255, int(round(self._current_rgb[0])))),
            max(0, min(255, int(round(self._current_rgb[1])))),
            max(0, min(255, int(round(self._current_rgb[2])))),
        )
        final_b = max(0, min(255, int(round(self._current_brightness))))

        return LightingState(rgb=final_rgb, brightness=final_b, is_on=True, timestamp=current_time)
