"""Comprehensive tests for Audio Focus modes, percussion/vocal suppression, kick attack slope,
beat event preservation, and adaptive update rate.
"""

import time
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.audio.analyzer import AudioAnalyzer, AudioMetrics
from src.audio.beat_detector import AudioFocus, BeatDetector, BeatDetectorConfig
from src.effects import EffectSettings, get_effect
from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState


def make_sine(freq: float, duration_s: float = 0.05, sample_rate: int = 48000, amplitude: float = 0.5) -> np.ndarray:
    """Generate a pure sine tone buffer."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def make_noise_burst(duration_s: float = 0.02, sample_rate: int = 48000, amplitude: float = 0.6) -> np.ndarray:
    """Generate a white noise burst (percussive transient like snare/hat)."""
    return (amplitude * np.random.uniform(-1.0, 1.0, int(sample_rate * duration_s))).astype(np.float32)


class TestAudioFocusDSP:
    """Tests synthetic signals across Full Music, Rhythm Focus, and Kick Focus modes."""

    def test_rhythm_focus_suppresses_steady_vocal_tone(self):
        """A steady 440 Hz harmonic vocal tone must be suppressed in Rhythm Focus."""
        analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024, audio_focus=AudioFocus.RHYTHM)

        # Feed 15 frames of steady 440 Hz tone (simulating sustained vocal)
        vocal_frame = make_sine(440.0, duration_s=1024 / 48000, amplitude=0.4)
        for _ in range(15):
            metrics = analyzer.analyze_frame(vocal_frame)

        # Steady harmonic tone must not be flagged as a percussive onset
        assert metrics.is_percussion is False

        # Now inject a sudden percussive transient (snare/clap noise burst)
        snare_frame = make_noise_burst(duration_s=1024 / 48000, amplitude=0.8)
        burst_metrics = analyzer.analyze_frame(snare_frame)

        # Percussive transient MUST be detected
        assert burst_metrics.is_percussion is True
        assert burst_metrics.percussion_strength > 0.0

    def test_kick_focus_rejects_sustained_bass_and_detects_kick(self):
        """Sustained 60 Hz bassline should not repeatedly trigger kick, while a sudden kick attack must trigger."""
        analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024, audio_focus=AudioFocus.KICK)

        # Sustained low-frequency bass drone (e.g. 60 Hz steady synth)
        sub_drone = make_sine(60.0, duration_s=1024 / 48000, amplitude=0.5)
        kick_triggers = 0
        for _ in range(15):
            m = analyzer.analyze_frame(sub_drone)
            if m.is_kick:
                kick_triggers += 1

        # Sustained bass should establish a baseline and not continuously trigger
        assert kick_triggers <= 1

        # Reset / quiet pause
        silent_frame = np.zeros(1024, dtype=np.float32)
        for _ in range(10):
            analyzer.analyze_frame(silent_frame)

        # Sudden punchy kick drum attack (0 -> 0.8 amplitude burst at 70 Hz)
        kick_punch = make_sine(70.0, duration_s=1024 / 48000, amplitude=0.85)
        punch_metrics = analyzer.analyze_frame(kick_punch)
        assert punch_metrics.is_kick is True
        assert punch_metrics.kick_strength > 0.0

    def test_full_music_backward_compatibility(self):
        """Full Music mode preserves spectral flux onset detection across all audible bands."""
        analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024, audio_focus=AudioFocus.FULL_MUSIC)

        # Silence
        m_silence = analyzer.analyze_frame(np.zeros(1024, dtype=np.float32))
        assert m_silence.is_onset is False
        assert m_silence.is_silent is True

        # Warm up history
        quiet = make_sine(300.0, duration_s=1024 / 48000, amplitude=0.05)
        for _ in range(10):
            analyzer.analyze_frame(quiet)

        # High-energy sudden attack
        loud = make_sine(1000.0, duration_s=1024 / 48000, amplitude=0.8)
        m_loud = analyzer.analyze_frame(loud)
        assert m_loud.is_onset is True


class TestBeatPulseAudioFocus:
    """Verifies Beat Pulse effect responds cleanly to focus modes and keeps resting baseline during vocals."""

    def test_beat_pulse_rests_during_vocals_in_rhythm_focus(self):
        effect = get_effect("beat", EffectSettings(min_brightness=25, max_brightness=255, audio_focus=AudioFocus.RHYTHM))

        # Metrics with high loudness and mid energy (vocal) but is_percussion=False
        vocal_metrics = AudioMetrics(
            rms=0.4,
            loudness=0.8,
            bass=0.1,
            mid=0.9,
            treble=0.2,
            spectral_flux=0.01,
            is_onset=True,  # General onset may trigger in full band, but is_percussion is False
            onset_strength=0.5,
            is_silent=False,
            audio_focus=AudioFocus.RHYTHM,
            is_percussion=False,
            percussion_strength=0.0,
            is_kick=False,
            kick_strength=0.0,
        )

        t = time.perf_counter()
        state = effect.process(vocal_metrics, t)
        # Because is_percussion is False, brightness must stay near min_brightness
        assert state.brightness <= 35  # Close to min_brightness 25

        # Now simulate a percussive beat
        beat_metrics = AudioMetrics(
            rms=0.6,
            loudness=0.7,
            bass=0.8,
            mid=0.3,
            treble=0.5,
            spectral_flux=0.1,
            is_onset=True,
            onset_strength=0.9,
            is_silent=False,
            audio_focus=AudioFocus.RHYTHM,
            is_percussion=True,
            percussion_strength=0.95,
            is_kick=True,
            kick_strength=0.9,
        )
        beat_state = effect.process(beat_metrics, t + 0.05)
        # On percussion hit, brightness must spike up significantly
        assert beat_state.brightness > 80


class TestBeatPreservation:
    """Verifies that fast beat arrivals between network ticks are preserved and not lost."""

    def test_beat_event_is_preserved_over_subsequent_decay_frame(self):
        scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0, max_beat_age_s=0.18)

        beat_state = LightingState(rgb=(255, 0, 0), brightness=255)
        decay_state = LightingState(rgb=(50, 0, 0), brightness=30)

        # 1. Submit a beat frame
        scheduler.submit(beat_state, is_beat=True, beat_intensity=0.9)

        # 2. Immediately submit a decay frame (simulating next audio buffer 21ms later before network tick)
        scheduler.submit(decay_state, is_beat=False, beat_intensity=0.0)

        # 3. Simulate tick execution: scheduler must prioritize the preserved beat state!
        now = time.perf_counter()
        with scheduler._state_lock:
            # Check what target _process_tick would pick
            if scheduler._pending_beat is not None and (now - scheduler._pending_beat.timestamp <= scheduler.max_beat_age_s):
                chosen = scheduler._pending_beat.state
            else:
                chosen = scheduler._pending_state

        assert chosen.brightness == 255
        assert chosen.rgb == (255, 0, 0)

    def test_stale_beat_event_expires(self):
        scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0, max_beat_age_s=0.05)

        beat_state = LightingState(rgb=(255, 0, 0), brightness=255)
        decay_state = LightingState(rgb=(50, 0, 0), brightness=30)

        # Submit beat frame
        scheduler.submit(beat_state, is_beat=True, beat_intensity=0.9)
        # Sleep past max_beat_age_s
        time.sleep(0.06)

        # Submit a normal state
        scheduler.submit(decay_state, is_beat=False)

        now = time.perf_counter()
        with scheduler._state_lock:
            if scheduler._pending_beat is not None and (now - scheduler._pending_beat.timestamp <= scheduler.max_beat_age_s):
                chosen = scheduler._pending_beat.state
            else:
                chosen = scheduler._pending_state

        # Stale beat expired, decay state is chosen instead
        assert chosen.brightness == 30


class TestAdaptiveRateController:
    """Verifies rate adjustment on healthy link and packet loss/latency."""

    def test_adaptive_rate_steps_up_on_low_latency_successes(self):
        scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0, adaptive_rate=True, min_rate_hz=3.5, max_rate_hz=8.0)

        # Simulate 12 fast successful dispatches (p95 = 20ms < 55ms)
        scheduler._consecutive_successes = 12
        for _ in range(12):
            scheduler._duration_history.append(20.0)
        scheduler._p95_duration_ms = 20.0

        initial_rate = scheduler.rate_hz
        scheduler._adapt_rate_on_success()
        assert scheduler.rate_hz > initial_rate
        assert scheduler.rate_hz <= 8.0

    def test_adaptive_rate_steps_down_on_failure(self):
        scheduler = BulbCommandScheduler(dry_run=True, rate_hz=6.0, adaptive_rate=True, min_rate_hz=3.5, max_rate_hz=8.0)

        scheduler._adapt_rate_on_failure()
        assert scheduler.rate_hz == 5.0

        # Cannot drop below min_rate_hz
        scheduler.rate_hz = 3.5
        scheduler._adapt_rate_on_failure()
        assert scheduler.rate_hz == 3.5

    def test_adaptive_rate_steps_down_on_high_latency(self):
        scheduler = BulbCommandScheduler(dry_run=True, rate_hz=6.0, adaptive_rate=True, min_rate_hz=3.5, max_rate_hz=8.0)

        scheduler._consecutive_successes = 10
        for _ in range(10):
            scheduler._duration_history.append(140.0)
        scheduler._p95_duration_ms = 140.0

        scheduler._adapt_rate_on_success()
        assert scheduler.rate_hz < 6.0
