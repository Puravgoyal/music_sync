"""Automated Software Tests: Real-Time Audio DSP Spectrum Analyzer.

Uses synthetic mathematical audio signals (pure tones, transients, combinations)
to verify frequency band isolation, RMS calculation, and normalization.
"""

import numpy as np
import pytest

from src.audio.analyzer import AudioAnalyzer, AudioMetrics


def generate_sine(frequency: float, duration: float, sample_rate: int, amplitude: float = 0.8) -> np.ndarray:
    """Generate a synthetic pure sine wave."""
    t = np.linspace(0.0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
    return amplitude * np.sin(2.0 * np.pi * frequency * t)


def test_empty_and_none_input() -> None:
    """Empty or None input should return zeroed silent metrics without crashing."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    metrics_none = analyzer.analyze_frame(None)  # type: ignore[arg-type]
    assert metrics_none.is_silent is True
    assert metrics_none.rms == 0.0
    assert metrics_none.loudness == 0.0

    metrics_empty = analyzer.analyze_frame(np.array([], dtype=np.float32))
    assert metrics_empty.is_silent is True
    assert metrics_empty.bass == 0.0


def test_pure_silence() -> None:
    """Buffer of exact zeros should produce zero RMS and is_silent=True."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    silence = np.zeros(1024, dtype=np.float32)
    metrics = analyzer.analyze_frame(silence)

    assert metrics.is_silent is True
    assert metrics.rms == 0.0
    assert metrics.loudness == 0.0
    assert metrics.bass == 0.0
    assert metrics.mid == 0.0
    assert metrics.treble == 0.0


def test_low_amplitude_noise_floor() -> None:
    """Signal below noise floor (~0.003) must be flagged as silence."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024, noise_floor=0.003)
    quiet_signal = np.full(1024, 0.001, dtype=np.float32)
    metrics = analyzer.analyze_frame(quiet_signal)

    assert metrics.is_silent is True
    assert metrics.loudness == 0.0


def test_bass_band_isolation_80hz() -> None:
    """An 80 Hz sine wave must dominate the Bass band (20-250 Hz)."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    sig = generate_sine(frequency=80.0, duration=1024 / 48000, sample_rate=48000, amplitude=0.8)

    # Process multiple frames so normalizer converges
    for _ in range(5):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.is_silent is False
    assert metrics.rms > 0.4
    assert metrics.bass > 0.4  # Bass must be high
    assert metrics.bass > metrics.mid * 5.0  # Bass must vastly exceed Mid
    assert metrics.bass > metrics.treble * 10.0  # Bass must vastly exceed Treble


def test_mid_band_isolation_1000hz() -> None:
    """A 1000 Hz sine wave must dominate the Mid band (250-4000 Hz)."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    sig = generate_sine(frequency=1000.0, duration=1024 / 48000, sample_rate=48000, amplitude=0.8)

    for _ in range(5):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.is_silent is False
    assert metrics.mid > 0.4
    assert metrics.mid > metrics.bass * 5.0
    assert metrics.mid > metrics.treble * 5.0


def test_treble_band_isolation_8000hz() -> None:
    """An 8000 Hz sine wave must dominate the Treble band (4000-16000 Hz)."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    sig = generate_sine(frequency=8000.0, duration=1024 / 48000, sample_rate=48000, amplitude=0.8)

    for _ in range(5):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.is_silent is False
    assert metrics.treble > 0.4
    assert metrics.treble > metrics.bass * 5.0
    assert metrics.treble > metrics.mid * 5.0


def test_combined_frequency_signal() -> None:
    """A signal with both 80 Hz and 1000 Hz should activate Bass and Mid, with low Treble."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    bass_sig = generate_sine(80.0, 1024 / 48000, 48000, amplitude=0.5)
    mid_sig = generate_sine(1000.0, 1024 / 48000, 48000, amplitude=0.5)
    combined = bass_sig + mid_sig

    for _ in range(5):
        metrics = analyzer.analyze_frame(combined)

    assert metrics.bass > 0.2
    assert metrics.mid > 0.2
    assert metrics.bass > metrics.treble * 3.0
    assert metrics.mid > metrics.treble * 3.0


def test_stereo_interleaved_input() -> None:
    """Stereo interleaved audio (2x buffer size) should be converted to mono and analyzed correctly."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    mono_sig = generate_sine(1000.0, 1024 / 48000, 48000, amplitude=0.7)
    # Create interleaved stereo: Left = mono_sig, Right = mono_sig
    stereo_interleaved = np.empty(2048, dtype=np.float32)
    stereo_interleaved[0::2] = mono_sig
    stereo_interleaved[1::2] = mono_sig

    for _ in range(4):
        metrics = analyzer.analyze_frame(stereo_interleaved, channels=2)

    assert metrics.is_silent is False
    assert metrics.mid > 0.3


@pytest.mark.parametrize("sr", [44100, 48000, 96000])
def test_different_sample_rates(sr: int) -> None:
    """Analyzer must adapt frequency bins accurately across different sample rates."""
    analyzer = AudioAnalyzer(sample_rate=sr, buffer_size=1024)
    sig = generate_sine(80.0, 1024 / sr, sr, amplitude=0.8)

    for _ in range(4):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.bass > 0.3
    assert metrics.bass > metrics.mid * 4.0


@pytest.mark.parametrize("buf_size", [512, 1024, 2048])
def test_different_buffer_sizes(buf_size: int) -> None:
    """Analyzer must support dynamic buffer lengths."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=buf_size)
    sig = generate_sine(1000.0, buf_size / 48000, 48000, amplitude=0.8)

    for _ in range(4):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.mid > 0.3


def test_analyzer_reset() -> None:
    """Resetting analyzer should clear normalizer envelope state."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    sig = generate_sine(1000.0, 1024 / 48000, 48000, amplitude=0.9)
    for _ in range(5):
        analyzer.analyze_frame(sig)

    assert analyzer.loudness_norm.current_level > 0.5
    analyzer.reset()
    assert analyzer.loudness_norm.current_level == 0.0


@pytest.mark.parametrize("freq", [6000.0, 8000.0, 12000.0])
@pytest.mark.parametrize("amplitude", [0.05, 0.2, 0.8])
def test_treble_synthetic_signals_at_amplitudes(freq: float, amplitude: float) -> None:
    """Treble band must detect 6kHz, 8kHz, 12kHz signals reliably across amplitudes."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024)
    sig = generate_sine(freq, 1024 / 48000, 48000, amplitude=amplitude)

    for _ in range(5):
        metrics = analyzer.analyze_frame(sig)

    assert metrics.is_silent is False
    assert metrics.treble > 0.1
    assert metrics.treble > metrics.bass * 5.0
    assert metrics.treble > metrics.mid * 5.0


@pytest.mark.parametrize("freq", [6000.0, 8000.0, 12000.0])
def test_treble_sub_threshold_noise_rejection(freq: float) -> None:
    """Sub-noise-floor high-frequency signals (<0.002 amplitude) must be treated as silence."""
    analyzer = AudioAnalyzer(sample_rate=48000, buffer_size=1024, noise_floor=0.003)
    quiet_sig = generate_sine(freq, 1024 / 48000, 48000, amplitude=0.001)

    for _ in range(5):
        metrics = analyzer.analyze_frame(quiet_sig)

    assert metrics.is_silent is True
    assert metrics.treble == 0.0
