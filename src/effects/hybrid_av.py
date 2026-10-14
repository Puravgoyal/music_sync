"""Hybrid Audio + Video synchronization processor fusing screen colors with rhythmic audio."""

from dataclasses import dataclass
from enum import Enum
import logging
import threading
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
    """Thread-safe fusion coordinator blending screen color RGB with audio loudness and rhythm events."""

    def __init__(self, settings: Optional[HybridAVSettings] = None) -> None:
        self.settings = settings or HybridAVSettings()
        self.settings.validate()

        self._lock = threading.Lock()
        self._max_audio_age_s: float = 0.35  # Audio older than 350 ms expires and returns to video-only

        # Video state tracking
        self._last_video_state: LightingState = LightingState()
        self._last_video_time: float = 0.0

        # Audio state tracking
        self._last_audio_metrics: Optional[AudioMetrics] = None
        self._last_audio_time: float = 0.0
        self._last_beat_metric_id: Optional[int] = None

        # Beat transient envelope
        self._beat_decay_start: float = 0.0
        self._beat_accent_boost: float = 0.0

        # Output state caching
        self._last_fused_state: LightingState = LightingState()

    def update_settings(self, settings: HybridAVSettings) -> None:
        settings.validate()
        with self._lock:
            self.settings = settings

    def reset(self) -> None:
        with self._lock:
            self._last_video_state = LightingState()
            self._last_video_time = 0.0
            self._last_audio_metrics = None
            self._last_audio_time = 0.0
            self._last_beat_metric_id = None
            self._beat_decay_start = 0.0
            self._beat_accent_boost = 0.0
            self._last_fused_state = LightingState()

    def fuse_video(
        self,
        video_state: LightingState,
        current_time: Optional[float] = None,
    ) -> Tuple[LightingState, bool, float]:
        """Atomic fusion invoked on arrival of a new screen video frame (~10-15 FPS).

        Video updates never re-trigger audio beats, completely preventing duplicate beats.
        """
        now = current_time if current_time is not None else time.perf_counter()
        with self._lock:
            self._last_video_state = video_state
            self._last_video_time = now
            fused = self._compute_fused(now)
            return fused, False, 0.0

    def fuse_audio(
        self,
        metrics: AudioMetrics,
        current_time: Optional[float] = None,
    ) -> Tuple[LightingState, bool, float]:
        """Atomic fusion invoked on arrival of a new audio frame (~46 FPS).

        Detects and consumes beat triggers once per unique audio metric ID.
        """
        now = current_time if current_time is not None else time.perf_counter()
        with self._lock:
            self._last_audio_metrics = metrics
            self._last_audio_time = now

            is_beat = False
            beat_str = 0.0

            h_type = self._resolve_hybrid_type()
            min_b = float(self.settings.min_brightness)
            max_b = float(self.settings.max_brightness)
            b_range = max(1.0, max_b - min_b)

            metric_id = id(metrics)

            if h_type == HybridType.RHYTHM:
                candidate = metrics.is_percussion or (
                    self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset
                )
                if candidate and metric_id != self._last_beat_metric_id:
                    is_beat = True
                    beat_str = metrics.percussion_strength if metrics.is_percussion else metrics.onset_strength
                    accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.30)
                    self._beat_accent_boost = accent
                    self._beat_decay_start = now
                    self._last_beat_metric_id = metric_id

            elif h_type == HybridType.KICK:
                candidate = metrics.is_kick or (
                    self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset
                )
                if candidate and metric_id != self._last_beat_metric_id:
                    is_beat = True
                    beat_str = metrics.kick_strength if metrics.is_kick else metrics.onset_strength
                    accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.40)
                    self._beat_accent_boost = accent
                    self._beat_decay_start = now
                    self._last_beat_metric_id = metric_id

            fused = self._compute_fused(now)
            return fused, is_beat, beat_str

    def process(
        self,
        video_state: LightingState,
        metrics: Optional[AudioMetrics],
        current_time: Optional[float] = None,
    ) -> Tuple[LightingState, bool, float]:
        """Thread-safe unified process method for backward compatibility and testing."""
        now = current_time if current_time is not None else time.perf_counter()
        with self._lock:
            self._last_video_state = video_state
            self._last_video_time = now

            is_beat = False
            beat_str = 0.0

            if metrics is not None:
                self._last_audio_metrics = metrics
                self._last_audio_time = now

                metric_id = id(metrics)
                h_type = self._resolve_hybrid_type()
                min_b = float(self.settings.min_brightness)
                max_b = float(self.settings.max_brightness)
                b_range = max(1.0, max_b - min_b)

                if h_type == HybridType.RHYTHM:
                    candidate = metrics.is_percussion or (
                        self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset
                    )
                    if candidate and metric_id != self._last_beat_metric_id:
                        is_beat = True
                        beat_str = metrics.percussion_strength if metrics.is_percussion else metrics.onset_strength
                        accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.30)
                        self._beat_accent_boost = accent
                        self._beat_decay_start = now
                        self._last_beat_metric_id = metric_id

                elif h_type == HybridType.KICK:
                    candidate = metrics.is_kick or (
                        self.settings.audio_focus == AudioFocus.FULL_MUSIC and metrics.is_onset
                    )
                    if candidate and metric_id != self._last_beat_metric_id:
                        is_beat = True
                        beat_str = metrics.kick_strength if metrics.is_kick else metrics.onset_strength
                        accent = (beat_str * self.settings.beat_intensity) * (b_range * 0.40)
                        self._beat_accent_boost = accent
                        self._beat_decay_start = now
                        self._last_beat_metric_id = metric_id

            fused = self._compute_fused(now)
            return fused, is_beat, beat_str

    def _resolve_hybrid_type(self) -> HybridType:
        h_type = self.settings.hybrid_type
        if isinstance(h_type, str):
            try:
                return HybridType(h_type.lower())
            except Exception:
                return HybridType.CINEMATIC
        return h_type

    def _compute_fused(self, now: float) -> LightingState:
        """Internal fusion calculation under self._lock."""
        # RGB is strictly driven by the latest video screen color
        r = self._last_video_state.r
        g = self._last_video_state.g
        b = self._last_video_state.b
        video_brightness = float(self._last_video_state.brightness)

        contrib = self.settings.audio_contribution
        metrics = self._last_audio_metrics

        # Audio freshness check: expired audio returns cleanly to video-only
        audio_age = now - self._last_audio_time
        if contrib <= 1e-4 or metrics is None or audio_age > self._max_audio_age_s:
            self._last_fused_state = LightingState(
                r=r,
                g=g,
                b=b,
                brightness=int(round(video_brightness)),
                is_on=True,
            )
            return self._last_fused_state

        min_b = float(self.settings.min_brightness)
        max_b = float(self.settings.max_brightness)
        b_range = max(1.0, max_b - min_b)

        h_type = self._resolve_hybrid_type()

        if h_type == HybridType.CINEMATIC:
            # Cinematic Hybrid: overall loudness provides gentle, smooth modulation
            loudness = max(0.0, min(1.0, metrics.loudness))
            audio_target_b = min_b + (loudness ** 0.8) * b_range
            fused_b = (1.0 - contrib) * video_brightness + contrib * audio_target_b

        elif h_type == HybridType.RHYTHM:
            # Rhythm Hybrid: percussion hits create subtle brightness accents decaying over ~180 ms
            dt = now - self._beat_decay_start
            decay_factor = max(0.0, 1.0 - (dt / 0.18))
            accent_val = self._beat_accent_boost * decay_factor
            fused_b = video_brightness + (contrib * accent_val)

        elif h_type == HybridType.KICK:
            # Kick Hybrid: low-frequency kicks drive pulses decaying over ~220 ms
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
        return self._last_fused_state
