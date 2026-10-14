"""Onset, musical transient, rhythm, and kick detection with adaptive thresholding."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

import numpy as np


class AudioFocus(str, Enum):
    """Selectable audio focus mode."""

    FULL_MUSIC = "full"
    RHYTHM = "rhythm"
    KICK = "kick"


@dataclass
class OnsetResult:
    """Detailed onset detection results across all focus modes."""

    is_onset: bool
    onset_strength: float
    is_percussion: bool = False
    percussion_strength: float = 0.0
    is_kick: bool = False
    kick_strength: float = 0.0
    spectral_flux: float = 0.0
    rhythm_flux: float = 0.0
    kick_flux: float = 0.0


@dataclass
class BeatDetectorConfig:
    """Configuration for multi-mode onset and transient detection."""

    history_size: int = 25  # Past frames for moving adaptive threshold
    threshold_multiplier: float = 1.35  # Multiplier above moving average for full flux
    min_threshold: float = 0.015  # Minimum flux value to avoid detecting silence/noise
    refractory_frames: int = 4  # Minimum frames (~85ms at 48kHz/1024) between full onsets

    # Full Music mode band weighting
    bass_weight: float = 1.5
    mid_weight: float = 1.0
    treble_weight: float = 0.5

    # Rhythm Focus (percussion & vocal suppression) parameters
    rhythm_threshold_multiplier: float = 1.45
    rhythm_refractory_frames: int = 4  # ~85ms cooldown matching musical transient rate
    rhythm_min_threshold: float = 0.015
    harmonic_smoothing: float = 0.88  # Running background spectrum factor for harmonic suppression

    # Kick Focus parameters (40 - 180 Hz)
    kick_min_freq: float = 40.0
    kick_max_freq: float = 180.0
    kick_threshold_multiplier: float = 1.45
    kick_refractory_frames: int = 5  # ~108ms cooldown prevents double-triggering on tail
    kick_min_threshold: float = 0.010
    kick_baseline_decay: float = 0.82  # Faster decay for distinguishing attack from sustained bass


class BeatDetector:
    """Detects musical transients, rhythmic percussion, and low-frequency kicks.

    Features:
    - Mode A (Full Music): Positive spectral flux across full audible range.
    - Mode B (Rhythm Focus): Real-time harmonic floor subtraction (vocal suppression),
      upweighted drum attack frequencies (snare/hats/kick) and downweighted vocal formants.
    - Mode C (Kick Focus): Sub-band transient analysis (40-180 Hz) with attack slope
      envelope to distinguish sudden kick-drum attacks from sustained 808 basslines.
    """

    def __init__(self, config: Optional[BeatDetectorConfig] = None) -> None:
        self.config = config or BeatDetectorConfig()

        # Full Music state
        self._prev_spectrum: Optional[np.ndarray] = None
        self._flux_history: deque = deque(maxlen=self.config.history_size)
        self._frames_since_last_onset: int = self.config.refractory_frames
        self._last_flux: float = 0.0

        # Rhythm Focus state
        self._harmonic_floor: Optional[np.ndarray] = None
        self._prev_percussive_spectrum: Optional[np.ndarray] = None
        self._rhythm_flux_history: deque = deque(maxlen=self.config.history_size)
        self._frames_since_last_rhythm: int = self.config.rhythm_refractory_frames
        self._last_rhythm_flux: float = 0.0
        self._last_is_percussion: bool = False
        self._last_percussion_strength: float = 0.0

        # Kick Focus state
        self._prev_kick_spectrum: Optional[np.ndarray] = None
        self._kick_energy_baseline: float = 0.0
        self._kick_flux_history: deque = deque(maxlen=self.config.history_size)
        self._frames_since_last_kick: int = self.config.kick_refractory_frames
        self._last_kick_flux: float = 0.0
        self._last_is_kick: bool = False
        self._last_kick_strength: float = 0.0

    @property
    def last_flux(self) -> float:
        """Instantaneous full-band spectral flux from most recent frame."""
        return self._last_flux

    @property
    def last_rhythm_flux(self) -> float:
        """Instantaneous percussive spectral flux from most recent frame."""
        return self._last_rhythm_flux

    @property
    def last_kick_flux(self) -> float:
        """Instantaneous kick-band flux from most recent frame."""
        return self._last_kick_flux

    @property
    def last_is_percussion(self) -> bool:
        return self._last_is_percussion

    @property
    def last_percussion_strength(self) -> float:
        return self._last_percussion_strength

    @property
    def last_is_kick(self) -> bool:
        return self._last_is_kick

    @property
    def last_kick_strength(self) -> float:
        return self._last_kick_strength

    def reset(self) -> None:
        """Reset all internal histories and state baselines."""
        self._prev_spectrum = None
        self._flux_history.clear()
        self._frames_since_last_onset = self.config.refractory_frames
        self._last_flux = 0.0

        self._harmonic_floor = None
        self._prev_percussive_spectrum = None
        self._rhythm_flux_history.clear()
        self._frames_since_last_rhythm = self.config.rhythm_refractory_frames
        self._last_rhythm_flux = 0.0
        self._last_is_percussion = False
        self._last_percussion_strength = 0.0

        self._prev_kick_spectrum = None
        self._kick_energy_baseline = 0.0
        self._kick_flux_history.clear()
        self._frames_since_last_kick = self.config.kick_refractory_frames
        self._last_kick_flux = 0.0
        self._last_is_kick = False
        self._last_kick_strength = 0.0

    def process(
        self,
        magnitude_spectrum: np.ndarray,
        freq_bins: Optional[np.ndarray] = None,
        focus: AudioFocus = AudioFocus.FULL_MUSIC,
    ) -> Tuple[bool, float]:
        """Process a frame and return (is_onset, onset_strength) for the given focus mode.

        Maintains 100% backward compatibility with prior 2-argument calls.
        """
        res = self.process_all(magnitude_spectrum, freq_bins=freq_bins, focus=focus)
        return res.is_onset, res.onset_strength

    def process_all(
        self,
        magnitude_spectrum: np.ndarray,
        freq_bins: Optional[np.ndarray] = None,
        focus: AudioFocus = AudioFocus.FULL_MUSIC,
        high_res_spectrum: Optional[np.ndarray] = None,
        high_res_freqs: Optional[np.ndarray] = None,
    ) -> OnsetResult:
        """Run all detection pipelines and return comprehensive OnsetResult."""
        if magnitude_spectrum is None or len(magnitude_spectrum) == 0:
            return OnsetResult(is_onset=False, onset_strength=0.0)

        current = np.asarray(magnitude_spectrum, dtype=np.float32)

        # 1. Full Music Detection (Mode A)
        is_full, full_strength, full_flux = self._process_full(current, freq_bins)

        # 2. Rhythm Focus Detection (Mode B)
        is_rhythm, rhythm_strength, rhythm_flux = self._process_rhythm(current, freq_bins)

        # 3. Kick Focus Detection (Mode C)
        # Use high_res (2048-pt FFT) if available, otherwise current spectrum
        k_spec = high_res_spectrum if (high_res_spectrum is not None and len(high_res_spectrum) > 0) else current
        k_freqs = high_res_freqs if (high_res_freqs is not None and len(high_res_freqs) > 0) else freq_bins
        is_kick, kick_strength, kick_flux = self._process_kick(k_spec, k_freqs)

        # Store latest values for property access
        self._last_is_percussion = is_rhythm
        self._last_percussion_strength = rhythm_strength
        self._last_is_kick = is_kick
        self._last_kick_strength = kick_strength
        self._last_rhythm_flux = rhythm_flux
        self._last_kick_flux = kick_flux

        # Select primary output based on active focus mode
        if focus == AudioFocus.RHYTHM:
            primary_onset = is_rhythm
            primary_strength = rhythm_strength
        elif focus == AudioFocus.KICK:
            primary_onset = is_kick
            primary_strength = kick_strength
        else:
            primary_onset = is_full
            primary_strength = full_strength

        return OnsetResult(
            is_onset=primary_onset,
            onset_strength=primary_strength,
            is_percussion=is_rhythm,
            percussion_strength=rhythm_strength,
            is_kick=is_kick,
            kick_strength=kick_strength,
            spectral_flux=full_flux,
            rhythm_flux=rhythm_flux,
            kick_flux=kick_flux,
        )

    def _process_full(
        self,
        current: np.ndarray,
        freq_bins: Optional[np.ndarray],
    ) -> Tuple[bool, float, float]:
        """Mode A: Full spectrum flux detection."""
        if self._prev_spectrum is None or len(self._prev_spectrum) != len(current):
            self._prev_spectrum = current.copy()
            self._flux_history.append(0.0)
            return False, 0.0, 0.0

        diff = current - self._prev_spectrum
        rectified = np.maximum(0.0, diff)

        if freq_bins is not None and len(freq_bins) == len(current):
            weights = np.ones_like(current)
            weights[freq_bins < 250.0] = self.config.bass_weight
            weights[(freq_bins >= 250.0) & (freq_bins < 4000.0)] = self.config.mid_weight
            weights[freq_bins >= 4000.0] = self.config.treble_weight
            rectified *= weights

        flux = float(np.sum(rectified))
        self._last_flux = flux
        self._prev_spectrum = current.copy()

        self._flux_history.append(flux)
        self._frames_since_last_onset += 1

        if len(self._flux_history) >= 5:
            arr = np.array(self._flux_history)
            mean_flux = float(np.mean(arr))
            std_flux = float(np.std(arr))
            thresh = max(
                self.config.min_threshold,
                mean_flux * self.config.threshold_multiplier + (0.5 * std_flux),
            )
        else:
            thresh = self.config.min_threshold

        is_onset = False
        onset_strength = 0.0
        if (
            flux > thresh
            and flux > self.config.min_threshold
            and self._frames_since_last_onset >= self.config.refractory_frames
        ):
            is_onset = True
            self._frames_since_last_onset = 0
            excess = flux - thresh
            onset_strength = min(1.0, max(0.1, excess / (thresh + 1e-5)))

        return is_onset, float(onset_strength), flux

    def _process_rhythm(
        self,
        current: np.ndarray,
        freq_bins: Optional[np.ndarray],
    ) -> Tuple[bool, float, float]:
        """Mode B: Rhythm focus via harmonic suppression and percussion weighting."""
        if self._harmonic_floor is None or len(self._harmonic_floor) != len(current):
            self._harmonic_floor = current.copy()
            self._prev_percussive_spectrum = np.zeros_like(current)
            self._rhythm_flux_history.append(0.0)
            return False, 0.0, 0.0

        # Update running stationary/harmonic floor (vocal vowel formants blend in here)
        self._harmonic_floor = (
            self.config.harmonic_smoothing * self._harmonic_floor
            + (1.0 - self.config.harmonic_smoothing) * current
        )

        # Percussive transient spectrum: energy exceeding the stationary harmonic background
        percussive = np.maximum(0.0, current - 1.15 * self._harmonic_floor)

        # Positive spectral difference of percussive components
        if self._prev_percussive_spectrum is not None:
            p_diff = np.maximum(0.0, percussive - self._prev_percussive_spectrum)
        else:
            p_diff = percussive.copy()
        self._prev_percussive_spectrum = percussive.copy()

        # Frequency weighting targeting percussion while suppressing vocal formant band (200 - 2500 Hz)
        if freq_bins is not None and len(freq_bins) == len(current):
            w = np.ones_like(current)
            w[freq_bins < 200.0] = 1.8  # Kicks
            w[(freq_bins >= 200.0) & (freq_bins < 2500.0)] = 0.20  # Strongly suppress vocal fundamentals & formants (F1, F2)
            w[(freq_bins >= 2500.0) & (freq_bins < 6000.0)] = 1.6  # Snares, claps, rimshots
            w[freq_bins >= 6000.0] = 1.3  # Hi-hats, cymbals, crisp transients
            p_diff *= w

        rhythm_flux = float(np.sum(p_diff))
        self._last_rhythm_flux = rhythm_flux

        self._rhythm_flux_history.append(rhythm_flux)
        self._frames_since_last_rhythm += 1

        if len(self._rhythm_flux_history) >= 5:
            arr = np.array(self._rhythm_flux_history)
            mean_f = float(np.mean(arr))
            std_f = float(np.std(arr))
            thresh = max(
                self.config.rhythm_min_threshold,
                mean_f * self.config.rhythm_threshold_multiplier + (0.5 * std_f),
            )
        else:
            thresh = self.config.rhythm_min_threshold

        is_rhythm = False
        rhythm_strength = 0.0
        if (
            rhythm_flux > thresh
            and rhythm_flux > self.config.rhythm_min_threshold
            and self._frames_since_last_rhythm >= self.config.rhythm_refractory_frames
        ):
            is_rhythm = True
            self._frames_since_last_rhythm = 0
            excess = rhythm_flux - thresh
            rhythm_strength = min(1.0, max(0.15, excess / (thresh + 1e-5)))

        return is_rhythm, float(rhythm_strength), rhythm_flux

    def _process_kick(
        self,
        current: np.ndarray,
        freq_bins: Optional[np.ndarray],
    ) -> Tuple[bool, float, float]:
        """Mode C: Kick focus (40-180 Hz) with attack slope vs sustained bass distinction."""
        if freq_bins is None or len(freq_bins) != len(current):
            return False, 0.0, 0.0

        self._frames_since_last_kick += 1

        kick_mask = (freq_bins >= self.config.kick_min_freq) & (freq_bins <= self.config.kick_max_freq)
        if not np.any(kick_mask):
            return False, 0.0, 0.0

        kick_mags = current[kick_mask]
        kick_energy = float(np.sqrt(np.mean(kick_mags ** 2)))

        # Sub-bass concentration guard: kick hits have prominent 40-180 Hz energy (> 0.012).
        # Rejects high-frequency percussion leakage and vocal harmonics without sub-bass presence.
        if kick_energy < 0.012:
            self._kick_flux_history.append(0.0)
            self._prev_kick_spectrum = kick_mags.copy()
            self._kick_energy_baseline = 0.0
            return False, 0.0, 0.0

        if self._prev_kick_spectrum is None or len(self._prev_kick_spectrum) != len(kick_mags):
            self._prev_kick_spectrum = kick_mags.copy()
            self._kick_energy_baseline = kick_energy
            self._kick_flux_history.append(0.0)
            return False, 0.0, 0.0

        # Positive kick spectral flux
        diff = np.maximum(0.0, kick_mags - self._prev_kick_spectrum)
        kick_flux = float(np.sum(diff))
        self._prev_kick_spectrum = kick_mags.copy()

        # Attack slope detection: distinguish sudden hit from steady sustained bass
        kick_attack = max(0.0, kick_energy - self._kick_energy_baseline)
        self._kick_energy_baseline = (
            self.config.kick_baseline_decay * self._kick_energy_baseline
            + (1.0 - self.config.kick_baseline_decay) * kick_energy
        )

        # Combined kick novelty signal
        combined_kick_novelty = 0.60 * kick_flux + 0.40 * kick_attack
        self._last_kick_flux = combined_kick_novelty

        self._kick_flux_history.append(combined_kick_novelty)

        if len(self._kick_flux_history) >= 5:
            arr = np.array(self._kick_flux_history)
            mean_k = float(np.mean(arr))
            std_k = float(np.std(arr))
            thresh = max(
                self.config.kick_min_threshold,
                mean_k * self.config.kick_threshold_multiplier + (0.6 * std_k),
            )
        else:
            thresh = self.config.kick_min_threshold

        is_kick = False
        kick_strength = 0.0

        # Trigger if combined novelty exceeds adaptive threshold,
        # energy attack is distinctly positive, and refractory window elapsed
        if (
            combined_kick_novelty > thresh
            and combined_kick_novelty > self.config.kick_min_threshold
            and kick_attack > (0.15 * thresh)
            and self._frames_since_last_kick >= self.config.kick_refractory_frames
        ):
            is_kick = True
            self._frames_since_last_kick = 0
            excess = combined_kick_novelty - thresh
            kick_strength = min(1.0, max(0.20, excess / (thresh + 1e-5)))

        return is_kick, float(kick_strength), combined_kick_novelty
