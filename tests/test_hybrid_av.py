"""Unit tests for Hybrid AV synchronization fusing screen video with audio loudness and rhythm."""

import numpy as np
import pytest

from src.audio.analyzer import AudioMetrics
from src.audio.beat_detector import AudioFocus
from src.effects.hybrid_av import HybridAVProcessor, HybridAVSettings, HybridType
from src.sync.state import LightingState


def _make_dummy_metrics(
    loudness: float = 0.5,
    is_percussion: bool = False,
    is_kick: bool = False,
    is_silent: bool = False,
) -> AudioMetrics:
    return AudioMetrics(
        rms=loudness * 0.8,
        loudness=loudness,
        bass=0.7 if is_kick else 0.2,
        mid=0.3,
        treble=0.2,
        spectral_flux=0.1,
        is_onset=is_percussion or is_kick,
        onset_strength=0.85 if (is_percussion or is_kick) else 0.0,
        is_percussion=is_percussion,
        percussion_strength=0.9 if is_percussion else 0.0,
        is_kick=is_kick,
        kick_strength=0.9 if is_kick else 0.0,
        is_silent=is_silent,
    )


class TestHybridAVProcessor:
    """Verify primary principle: Video determines RGB; audio determines subtle brightness modulation."""

    def test_zero_audio_contribution_equals_screen_sync(self) -> None:
        processor = HybridAVProcessor(
            settings=HybridAVSettings(
                hybrid_type=HybridType.CINEMATIC,
                audio_contribution=0.0,  # 0% audio contribution
                min_brightness=25,
                max_brightness=255,
            )
        )

        video_state = LightingState(rgb=(220, 80, 40), brightness=140)
        loud_metrics = _make_dummy_metrics(loudness=0.95, is_percussion=True)

        fused, is_beat, _ = processor.process(video_state, loud_metrics)

        # Output must be identical to video state
        assert fused.rgb == (220, 80, 40)
        assert fused.brightness == 140
        assert not is_beat

    def test_silent_audio_colorful_video(self) -> None:
        processor = HybridAVProcessor(
            settings=HybridAVSettings(
                hybrid_type=HybridType.CINEMATIC,
                audio_contribution=0.5,
                min_brightness=25,
                max_brightness=255,
            )
        )

        video_state = LightingState(rgb=(10, 200, 180), brightness=150)
        silent_metrics = _make_dummy_metrics(loudness=0.0, is_silent=True)

        fused, _, _ = processor.process(video_state, silent_metrics)

        # RGB strictly preserves video color
        assert fused.rgb == (10, 200, 180)
        # Brightness is modulated downward by silence: (0.5 * 150) + (0.5 * 25) = ~88
        assert fused.brightness < video_state.brightness
        assert fused.brightness >= 25

    def test_loud_audio_increases_brightness(self) -> None:
        processor = HybridAVProcessor(
            settings=HybridAVSettings(
                hybrid_type=HybridType.CINEMATIC,
                audio_contribution=0.5,
                min_brightness=25,
                max_brightness=255,
            )
        )

        video_state = LightingState(rgb=(50, 120, 240), brightness=100)
        quiet_metrics = _make_dummy_metrics(loudness=0.1)
        loud_metrics = _make_dummy_metrics(loudness=0.9)

        fused_quiet, _, _ = processor.process(video_state, quiet_metrics)
        fused_loud, _, _ = processor.process(video_state, loud_metrics)

        # Both preserve video RGB
        assert fused_quiet.rgb == (50, 120, 240)
        assert fused_loud.rgb == (50, 120, 240)
        # Loud audio must produce significantly higher brightness than quiet
        assert fused_loud.brightness > fused_quiet.brightness

    def test_rhythm_hybrid_percussion_accents(self) -> None:
        processor = HybridAVProcessor(
            settings=HybridAVSettings(
                hybrid_type=HybridType.RHYTHM,
                audio_contribution=0.6,
                beat_intensity=1.2,
                min_brightness=25,
                max_brightness=255,
            )
        )

        video_state = LightingState(rgb=(200, 100, 50), brightness=100)
        t0 = 10.0

        # Non-percussion frame (vocals/melodic)
        vocal_metrics = _make_dummy_metrics(loudness=0.6, is_percussion=False)
        fused_vocal, is_beat_vocal, _ = processor.process(video_state, vocal_metrics, current_time=t0)
        assert not is_beat_vocal
        assert fused_vocal.brightness == 100

        # Percussion onset frame (drum hit)
        drum_metrics = _make_dummy_metrics(loudness=0.8, is_percussion=True)
        fused_drum, is_beat_drum, beat_str = processor.process(video_state, drum_metrics, current_time=t0 + 0.05)
        assert is_beat_drum
        assert beat_str > 0.0
        # Percussion hit creates brightness accent
        assert fused_drum.brightness > 100
        assert fused_drum.rgb == (200, 100, 50)

    def test_kick_hybrid_bass_hits(self) -> None:
        processor = HybridAVProcessor(
            settings=HybridAVSettings(
                hybrid_type=HybridType.KICK,
                audio_contribution=0.5,
                beat_intensity=1.0,
                min_brightness=25,
                max_brightness=255,
            )
        )

        video_state = LightingState(rgb=(255, 180, 0), brightness=80)
        t0 = 5.0

        # Kick hit frame
        kick_metrics = _make_dummy_metrics(loudness=0.85, is_kick=True)
        fused_kick, is_beat_kick, _ = processor.process(video_state, kick_metrics, current_time=t0)
        assert is_beat_kick
        assert fused_kick.brightness > 80
        assert fused_kick.rgb == (255, 180, 0)

    def test_missing_audio_metrics_fallback(self) -> None:
        processor = HybridAVProcessor()
        video_state = LightingState(rgb=(100, 100, 100), brightness=120)

        # If audio stream is unavailable or paused, video state is returned intact
        fused, is_beat, _ = processor.process(video_state, None)
        assert fused.rgb == (100, 100, 100)
        assert fused.brightness == 120
        assert not is_beat
