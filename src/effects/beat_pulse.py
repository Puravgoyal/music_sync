"""Mode 2: Beat Pulse - Base ambiance with smooth brightness expansion on musical onsets."""

from typing import Optional, Tuple

from src.audio.analyzer import AudioMetrics
from src.effects.base import BaseMusicEffect, EffectSettings
from src.sync.state import LightingState


class BeatPulseEffect(BaseMusicEffect):
    """Maintains a steady base color and pulses brightness on rhythm onsets."""

    name: str = "Beat Pulse"
    description: str = "Pulsing brightness on detected musical beats and onsets"

    def __init__(
        self,
        settings: Optional[EffectSettings] = None,
        base_color: Tuple[int, int, int] = (25, 60, 255),  # Deep ocean blue base
        pulse_color: Tuple[int, int, int] = (255, 230, 200),  # Bright warm highlight
    ) -> None:
        super().__init__(settings)
        self.base_color = base_color
        self.pulse_color = pulse_color
        self._pulse_energy: float = 0.0

    def process(self, metrics: AudioMetrics, current_time: float) -> LightingState:
        dt = max(0.001, current_time - self._last_time)
        self._last_time = current_time

        focus = getattr(metrics, "audio_focus", self.settings.audio_focus)
        if focus == "rhythm" or getattr(focus, "value", None) == "rhythm":
            is_beat = metrics.is_percussion
            beat_str = metrics.percussion_strength
        elif focus == "kick" or getattr(focus, "value", None) == "kick":
            is_beat = metrics.is_kick
            beat_str = metrics.kick_strength
        else:
            is_beat = metrics.is_onset
            beat_str = metrics.onset_strength

        # If an onset is triggered, inject pulse energy scaled by onset strength
        if is_beat and not metrics.is_silent:
            boost = min(1.0, beat_str * self.settings.beat_strength)
            # Additive kick with saturation limit to prevent excessive strobing
            self._pulse_energy = min(1.0, self._pulse_energy + boost * 0.75)

        # Exponential decay of pulse energy
        decay = min(1.0, self.settings.release_speed * dt * 30.0)
        self._pulse_energy = max(0.0, self._pulse_energy * (1.0 - decay))

        # Base brightness:
        # In Full Music mode, loudness modulates baseline.
        # In Rhythm/Kick modes, baseline stays firmly at min_brightness during vocals
        # to eliminate vocal pumping, gently rising only on sustained rhythm energy.
        if focus == "full" or getattr(focus, "value", None) == "full":
            base_b = float(self.clamp_brightness(metrics.loudness * 0.5 * self.settings.sensitivity))
        else:
            base_b = float(self.settings.min_brightness)
            if (focus == "rhythm" or getattr(focus, "value", None) == "rhythm") and metrics.is_percussion:
                base_b += (self.settings.max_brightness - self.settings.min_brightness) * 0.15 * metrics.percussion_strength
            elif (focus == "kick" or getattr(focus, "value", None) == "kick") and metrics.is_kick:
                base_b += (self.settings.max_brightness - self.settings.min_brightness) * 0.20 * metrics.kick_strength

        pulse_boost = self._pulse_energy * (self.settings.max_brightness - base_b)
        target_b = min(float(self.settings.max_brightness), base_b + pulse_boost)

        # Smooth brightness envelope (fast attack, smooth decay)
        if target_b > self._current_brightness:
            b_rate = min(1.0, self.settings.attack_speed * dt * 50.0)
        else:
            b_rate = min(1.0, self.settings.release_speed * dt * 25.0)
        self._current_brightness += b_rate * (target_b - self._current_brightness)
        self._current_brightness = max(float(self.settings.min_brightness), min(float(self.settings.max_brightness), self._current_brightness))

        # Blend color from base towards pulse highlight during hits
        blend_factor = min(0.65, self._pulse_energy * 0.65)
        blended = self.blend_rgb(
            (float(self.base_color[0]), float(self.base_color[1]), float(self.base_color[2])),
            (float(self.pulse_color[0]), float(self.pulse_color[1]), float(self.pulse_color[2])),
            blend_factor,
        )

        final_rgb = (
            max(0, min(255, int(round(blended[0])))),
            max(0, min(255, int(round(blended[1])))),
            max(0, min(255, int(round(blended[2])))),
        )
        final_b = max(0, min(255, int(round(self._current_brightness))))

        return LightingState(rgb=final_rgb, brightness=final_b, is_on=True, timestamp=current_time)
