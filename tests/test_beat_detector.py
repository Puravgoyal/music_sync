"""Automated Software Tests: Beat & Onset Detection Engine.

Verifies spectral flux calculations, adaptive thresholding, refractory periods,
and sustained tone rejection.
"""

import numpy as np
import pytest

from src.audio.beat_detector import BeatDetector, BeatDetectorConfig


def create_spectrum(peak_bin: int, size: int = 513, amplitude: float = 1.0) -> np.ndarray:
    """Create a synthetic magnitude spectrum with an energy peak at a specific bin."""
    spec = np.zeros(size, dtype=np.float32)
    spec[peak_bin] = amplitude
    return spec


def test_empty_spectrum() -> None:
    """Empty or None spectrum should return False onset."""
    detector = BeatDetector()
    is_onset, strength = detector.process(np.array([]))
    assert is_onset is False
    assert strength == 0.0


def test_silence_produces_no_onsets() -> None:
    """Continuous silence should never trigger onsets."""
    detector = BeatDetector()
    silent_spec = np.zeros(513, dtype=np.float32)

    for _ in range(20):
        is_onset, _ = detector.process(silent_spec)
        assert is_onset is False


def test_sudden_transient_triggers_onset() -> None:
    """A sudden high-energy burst following silence must trigger an onset."""
    detector = BeatDetector()
    silent_spec = np.zeros(513, dtype=np.float32)

    # Establish baseline silence
    for _ in range(10):
        detector.process(silent_spec)

    # Sudden loud burst (e.g. kick drum hit at bin 5)
    burst_spec = create_spectrum(peak_bin=5, amplitude=5.0)
    is_onset, strength = detector.process(burst_spec)

    assert is_onset is True
    assert strength > 0.1


def test_sustained_tone_does_not_continuously_trigger() -> None:
    """A steady sustained tone must not produce repeated false onsets."""
    detector = BeatDetector()
    steady_spec = create_spectrum(peak_bin=20, amplitude=2.0)

    onsets = []
    for _ in range(25):
        is_onset, _ = detector.process(steady_spec)
        onsets.append(is_onset)

    # At most the initial transient triggers; sustained frames must not trigger
    num_triggers = sum(1 for o in onsets if o)
    assert num_triggers <= 1  # Sustained tones do not repeatedly trigger onsets


def test_refractory_period_enforcement() -> None:
    """Two bursts within the refractory window (<4 frames) must not trigger back-to-back onsets."""
    cfg = BeatDetectorConfig(refractory_frames=4)
    detector = BeatDetector(cfg)
    silent_spec = np.zeros(513, dtype=np.float32)

    for _ in range(10):
        detector.process(silent_spec)

    # First burst
    burst1 = create_spectrum(5, amplitude=3.0)
    is_onset1, _ = detector.process(burst1)
    assert is_onset1 is True

    # Immediate second burst next frame (within refractory period)
    burst2 = create_spectrum(5, amplitude=6.0)
    is_onset2, _ = detector.process(burst2)
    assert is_onset2 is False  # Refractory period blocked the immediate consecutive trigger


def test_detector_reset() -> None:
    """Resetting detector must clear prior spectrum and flux history."""
    detector = BeatDetector()
    burst = create_spectrum(10, amplitude=2.0)
    detector.process(burst)
    assert detector._prev_spectrum is not None

    detector.reset()
    assert detector._prev_spectrum is None
    assert len(detector._flux_history) == 0
