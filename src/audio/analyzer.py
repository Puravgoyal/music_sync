"""Real-time audio DSP spectrum analyzer, band energy, and loudness extractor."""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from src.audio.beat_detector import BeatDetector, BeatDetectorConfig
from src.audio.normalization import LoudnessNormalizer, NormalizerConfig


@dataclass
class AudioMetrics:
    """Metrics produced by analyzing a single frame of audio."""

    rms: float  # Raw Root-Mean-Square amplitude [0.0, 1.0]
    loudness: float  # Normalized, attack/release smoothed volume [0.0, 1.0]
    bass: float  # Normalized low-frequency energy (20 - 250 Hz) [0.0, 1.0]
    mid: float  # Normalized mid-frequency energy (250 - 4000 Hz) [0.0, 1.0]
    treble: float  # Normalized high-frequency energy (4000 - 16000 Hz) [0.0, 1.0]
    spectral_flux: float  # Instantaneous rate of spectral change
    is_onset: bool  # True when an attack/beat transient is detected
    onset_strength: float  # Magnitude of the detected transient [0.0, 1.0]
    is_silent: bool  # True when signal is below noise floor


class AudioAnalyzer:
    """Real-time audio DSP pipeline converting PCM audio frames into musical metrics."""

    def __init__(
        self,
        sample_rate: int = 48000,
        buffer_size: int = 1024,
        bass_range: Tuple[float, float] = (20.0, 250.0),
        mid_range: Tuple[float, float] = (250.0, 4000.0),
        treble_range: Tuple[float, float] = (4000.0, 16000.0),
        noise_floor: float = 0.003,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.buffer_size = int(buffer_size)
        self.bass_range = bass_range
        self.mid_range = mid_range
        self.treble_range = treble_range
        self.noise_floor = noise_floor

        # Precompute window function and FFT frequency bins
        self._init_dsp_tables(self.buffer_size)

        # Independent adaptive normalizers for overall volume and each frequency band
        norm_cfg = NormalizerConfig(noise_floor=noise_floor)
        self.loudness_norm = LoudnessNormalizer(norm_cfg)
        self.bass_norm = LoudnessNormalizer(NormalizerConfig(noise_floor=noise_floor, attack_factor=0.45, release_factor=0.10))
        self.mid_norm = LoudnessNormalizer(NormalizerConfig(noise_floor=noise_floor, attack_factor=0.40, release_factor=0.08))
        self.treble_norm = LoudnessNormalizer(NormalizerConfig(noise_floor=noise_floor, attack_factor=0.50, release_factor=0.12))

        # Onset / Beat detector
        self.beat_detector = BeatDetector(BeatDetectorConfig())

    def _init_dsp_tables(self, size: int) -> None:
        """Initialize or update Hann window and frequency bin masks."""
        self.buffer_size = size
        self.window = np.hanning(size).astype(np.float32)
        self.freqs = np.fft.rfftfreq(size, d=1.0 / self.sample_rate)

        nyquist = self.sample_rate / 2.0
        treble_upper = min(self.treble_range[1], nyquist)

        self.bass_mask = (self.freqs >= self.bass_range[0]) & (self.freqs < self.bass_range[1])
        self.mid_mask = (self.freqs >= self.mid_range[0]) & (self.freqs < self.mid_range[1])
        self.treble_mask = (self.freqs >= self.treble_range[0]) & (self.freqs <= treble_upper)

    def reset(self) -> None:
        """Reset internal normalizers and onset detector."""
        self.loudness_norm.reset()
        self.bass_norm.reset()
        self.mid_norm.reset()
        self.treble_norm.reset()
        self.beat_detector.reset()

    def analyze_frame(self, audio_data: np.ndarray, channels: int = 1) -> AudioMetrics:
        """Analyze a single PCM audio frame.

        Args:
            audio_data: Float32 NumPy array of audio samples. Can be 1D mono or interleaved stereo.
            channels: Number of audio channels (1 for mono, 2 for stereo).

        Returns:
            AudioMetrics containing RMS, band energies, onset state, and silence flag.
        """
        if audio_data is None or len(audio_data) == 0:
            return AudioMetrics(
                rms=0.0,
                loudness=0.0,
                bass=0.0,
                mid=0.0,
                treble=0.0,
                spectral_flux=0.0,
                is_onset=False,
                onset_strength=0.0,
                is_silent=True,
            )

        samples = np.asarray(audio_data, dtype=np.float32)

        # Convert multi-channel / interleaved audio to mono
        if channels > 1 and len(samples) >= channels:
            samples = samples.reshape(-1, channels).mean(axis=1)
        elif samples.ndim > 1:
            samples = samples.mean(axis=1)

        frame_len = len(samples)
        if frame_len != self.buffer_size:
            # Recompute window & masks if buffer length changed dynamically
            self._init_dsp_tables(frame_len)

        # 1. Calculate instantaneous RMS
        rms = float(np.sqrt(np.mean(samples ** 2)))
        is_silent = rms <= self.noise_floor

        # 2. Apply Hann window and compute real FFT
        windowed = samples * self.window
        fft_complex = np.fft.rfft(windowed)
        magnitudes = np.abs(fft_complex) / (frame_len / 2.0)

        # 3. Calculate raw energy in each frequency band
        raw_bass = float(np.sqrt(np.mean(magnitudes[self.bass_mask] ** 2))) if np.any(self.bass_mask) else 0.0
        raw_mid = float(np.sqrt(np.mean(magnitudes[self.mid_mask] ** 2))) if np.any(self.mid_mask) else 0.0
        raw_treble = float(np.sqrt(np.mean(magnitudes[self.treble_mask] ** 2))) if np.any(self.treble_mask) else 0.0

        # 4. Normalize and apply attack/release smoothing
        loudness = self.loudness_norm.process(rms)
        bass = self.bass_norm.process(raw_bass)
        mid = self.mid_norm.process(raw_mid)
        treble = self.treble_norm.process(raw_treble)

        # 5. Onset / beat detection
        is_onset, onset_strength = self.beat_detector.process(magnitudes, self.freqs)
        spectral_flux = self.beat_detector.last_flux

        return AudioMetrics(
            rms=rms,
            loudness=loudness,
            bass=bass,
            mid=mid,
            treble=treble,
            spectral_flux=spectral_flux,
            is_onset=is_onset,
            onset_strength=onset_strength,
            is_silent=is_silent,
        )
