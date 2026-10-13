"""Onset and musical transient detection using spectral flux and adaptive thresholding."""

from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class BeatDetectorConfig:
    """Configuration for spectral flux onset detection."""

    history_size: int = 25  # Number of past frames for moving adaptive threshold
    threshold_multiplier: float = 1.35  # Multiplier above moving average to trigger onset
    min_threshold: float = 0.015  # Minimum flux value to avoid detecting silence/noise
    refractory_frames: int = 4  # Minimum frames (~85ms at 48kHz/1024) between consecutive onsets
    bass_weight: float = 1.5  # Weight multiplier for low frequencies (kicks/basses)
    mid_weight: float = 1.0  # Weight multiplier for mid frequencies (snares/vocals)
    treble_weight: float = 0.5  # Weight multiplier for high frequencies (hi-hats/cymbals)


class BeatDetector:
    """Detects musical transients and rhythm onsets via spectral flux.

    Uses half-wave rectified spectral difference across frequency bins with an
    adaptive moving threshold and a refractory cooldown to reject sustained tones.
    """

    def __init__(self, config: Optional[BeatDetectorConfig] = None) -> None:
        self.config = config or BeatDetectorConfig()
        self._prev_spectrum: Optional[np.ndarray] = None
        self._flux_history: deque = deque(maxlen=self.config.history_size)
        self._frames_since_last_onset: int = self.config.refractory_frames
        self._last_flux: float = 0.0

    @property
    def last_flux(self) -> float:
        """Instantaneous spectral flux from the most recent frame."""
        return self._last_flux

    def reset(self) -> None:
        """Reset internal history and state."""
        self._prev_spectrum = None
        self._flux_history.clear()
        self._frames_since_last_onset = self.config.refractory_frames
        self._last_flux = 0.0

    def process(
        self,
        magnitude_spectrum: np.ndarray,
        freq_bins: Optional[np.ndarray] = None,
    ) -> Tuple[bool, float]:
        """Process a frame's magnitude spectrum to detect onsets.

        Args:
            magnitude_spectrum: 1D array of positive FFT magnitude values.
            freq_bins: Optional 1D array of frequency values corresponding to bins.

        Returns:
            Tuple of (is_onset: bool, onset_strength: float).
        """
        if magnitude_spectrum is None or len(magnitude_spectrum) == 0:
            return False, 0.0

        current_spectrum = np.asarray(magnitude_spectrum, dtype=np.float32)

        # First frame initialization
        if self._prev_spectrum is None or len(self._prev_spectrum) != len(current_spectrum):
            self._prev_spectrum = current_spectrum.copy()
            self._flux_history.append(0.0)
            return False, 0.0

        # Half-wave rectified difference: only positive increases count as onsets
        diff = current_spectrum - self._prev_spectrum
        rectified_diff = np.maximum(0.0, diff)

        # Apply frequency weighting if frequency bins are supplied
        if freq_bins is not None and len(freq_bins) == len(current_spectrum):
            weights = np.ones_like(current_spectrum)
            weights[freq_bins < 250.0] = self.config.bass_weight
            weights[(freq_bins >= 250.0) & (freq_bins < 4000.0)] = self.config.mid_weight
            weights[freq_bins >= 4000.0] = self.config.treble_weight
            rectified_diff *= weights

        flux = float(np.sum(rectified_diff))
        self._last_flux = flux
        self._prev_spectrum = current_spectrum.copy()

        # Update adaptive history
        self._flux_history.append(flux)
        self._frames_since_last_onset += 1

        # Calculate adaptive threshold: mean + multiplier * std
        if len(self._flux_history) >= 5:
            history_arr = np.array(self._flux_history)
            mean_flux = float(np.mean(history_arr))
            std_flux = float(np.std(history_arr))
            adaptive_threshold = max(
                self.config.min_threshold,
                mean_flux * self.config.threshold_multiplier + (0.5 * std_flux),
            )
        else:
            adaptive_threshold = self.config.min_threshold

        # Check onset trigger conditions:
        # 1. Flux exceeds adaptive threshold
        # 2. Refractory period has elapsed
        # 3. Flux is above absolute noise minimum
        is_onset = False
        onset_strength = 0.0

        if (
            flux > adaptive_threshold
            and flux > self.config.min_threshold
            and self._frames_since_last_onset >= self.config.refractory_frames
        ):
            is_onset = True
            self._frames_since_last_onset = 0
            excess = flux - adaptive_threshold
            onset_strength = min(1.0, max(0.1, excess / (adaptive_threshold + 1e-5)))

        return is_onset, float(onset_strength)
