"""Hybrid Audio + Video synchronization processor fusing screen colors with rhythmic audio."""

from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import Optional, Tuple

from src.audio.analyzer import AudioMetrics
from src.audio.beat_detector import AudioFocus
from src.sync.state import LightingState

logger = logging.getLogger(__name__)


class HybridType(Enum):
    """Sub-modes for Hybrid AV synchronization."""

    CINEMATIC = "cinematic"
    RHYTHM = "rhythm"
    KICK = "kick"


@dataclass
class HybridAVSettings:
    """Configurable parameters for Hybrid AV synchronization."""

    hybrid_type: HybridType = HybridType.CINEMATIC
    audio_contribution: float = 0.35   # [0.0, 1.0]: 0.0 = pure screen, 1.0 = heavy audio modulation
    beat_intensity: float = 1.0        # Multiplier for rhythmic brightness accents [0.0, 2.0]
    min_brightness: int = 25           # Floor brightness [0, 255]
    max_brightness: int = 255          # Ceiling brightness [0, 255]
    audio_focus: AudioFocus = AudioFocus.FULL_MUSIC

    def validate(self) -> None:
        self.audio_contribution = max(0.0, min(1.0, float(self.audio_contribution)))
        self.beat_intensity = max(0.0, min(2.0, float(self.beat_intensity)))
        self.min_brightness = max(0, min(255, int(self.min_brightness)))
        self.max_brightness = max(0, min(255, int(self.max_brightness)))
        if self.min_brightness > self.max_brightness:
            self.min_brightness = self.max_brightness


class HybridAVProcessor:
    """Fuses screen color RGB with audio loudness and rhythm events to yield single-bulb lighting."""

    def __init__(self, settings: Optional[HybridAVSettings] = None) -> None:
        self.settings = settings or HybridAVSettings()
        self.settings.validate()

        self._beat_decay_start: float = 0.0
        self._beat_accent_boost: float = 0.0
        self._last_fused_state: LightingState = LightingState()

    def update_settings(self, settings: HybridAVSettings) -> None:
        settings.validate()
        self.settings = settings

    def reset(self) -> None:
        self._beat_decay_start = 0.0
        self._beat_accent_boost = 0.0
        self._last_fused_state = LightingState()

    def process(
        self,
        video_state: LightingState,
        metrics: Optional[AudioMetrics],
        current_time: Optional[float] = None,
    ) -> Tuple[LightingState, bool, float]:
        """Fuse video lighting state with audio metrics.

        Returns:
            (fused_state, is_beat, beat_intensity).
        """
        now = current_time if current_time is not None else time.perf_counter()

        # RGB is strictly driven by the video screen color
        r = video_state.r
        g = video_state.g
        b = video_state.b
        video_brightness = float(video_state.brightness)

        contrib = self.settings.audio_contribution

        # If zero audio contribution or metrics missing: pure video screen sync
        if contrib <= 1e-4 or metrics is None:
            self._last_fused_state = LightingState(
                r=r,
                g=g,
                b=b,
                brightness=int(round(video_brightness)),
                is_on=True,
            )
            return self._last_fused_state, False, 0.0

        is_beat = False
        beat_str = 0.0
        h_type = self.settings.hybrid_type
        if isinstance(h_type, str):
            try:
                h_type = HybridType(h_type.lower())
            except Exception:
                h_type = HybridType.CINEMATIC

        min_b = float(self.settings.min_brightness)
        max_b = float(self.settings.max_brightness)
        b_range = max(1.0, max_b - min_b)

        if h_type == HybridType.CINEMATIC:
            # Cinematic Hybrid: overall loudness provides gentle, smooth modulation
            loudness = max(0.0, min(1.0, metrics.loudness))
            audio_target_b = min_b + (loudness ** 0.8) * b_range
            fused_b = (1.0 - contrib) * video_brightness + contrib * audio_target_b

        elif h_type == HybridType.RHYTHM:
            # Rhythm Hybrid: percussion / onset hits create subtle, short brightness accents
            # Vocals are suppressed by the analyzer
            if metrics.is_percussion or (self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset):
                is_beat = True
                beat_str = metrics.percussion_strength if metrics.is_percussion else metrics.onset_strength
                # Subtle brightness accent (+15-35% of dynamic range)
                accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.30)
                self._beat_accent_boost = accent
                self._beat_decay_start = now

            # Fast exponential decay over ~180 ms
            dt = now - self._beat_decay_start
            decay_factor = max(0.0, 1.0 - (dt / 0.18))
            accent_val = self._beat_accent_boost * decay_factor

            # Modulate base video brightness by accent scaled by contribution
            fused_b = video_brightness + (contrib * accent_val)

        elif h_type == HybridType.KICK:
            # Kick Hybrid: low-frequency kicks drive gentle pulses
            if metrics.is_kick or (self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset):
                is_beat = True
                beat_str = metrics.kick_strength if metrics.is_kick else metrics.onset_strength
                accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.40)
                self._beat_accent_boost = accent
                self._beat_decay_start = now

            # Decay over ~220 ms
            dt = now - self._beat_decay_start
            decay_factor = max(0.0, 1.0 - (dt / 0.22))
            accent_val = self._beat_accent_boost * decay_factor

            fused_b = video_brightness + (contrib * accent_val)

        else:
            fused_b = video_brightness

        # Clamp brightness to configured limits
        final_b = max(int(min_b), min(int(max_b), int(round(fused_b))))

        self._last_fused_state = LightingState(
            r=r,
            g=g,
            b=b,
            brightness=final_b,
            is_on=True,
        )
        return self._last_fused_state, is_beat, beat_str
