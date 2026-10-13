"""Audio loudness normalization, baseline tracking, and attack/release smoothing."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalizerConfig:
    """Configuration for adaptive audio normalization and smoothing."""

    noise_floor: float = 0.003  # Below this threshold, signal is considered silence (~ -50 dBFS)
    attack_factor: float = 0.40  # Speed at which level rises on transients (0.0 < attack <= 1.0)
    release_factor: float = 0.08  # Speed at which level decays during release (0.0 < release <= 1.0)
    peak_decay_rate: float = 0.002  # Gradual decay rate of adaptive peak reference per frame
    min_peak_reference: float = 0.04  # Minimum reference peak to avoid amplifying pure silence


class LoudnessNormalizer:
    """Maintains an adaptive loudness baseline and applies attack/release smoothing.

    Prevents over-amplification of silence while ensuring responsive, smooth
    level tracking across varying genres and master playback volumes.
    """

    def __init__(self, config: Optional[NormalizerConfig] = None) -> None:
        self.config = config or NormalizerConfig()
        self._current_level: float = 0.0
        self._peak_reference: float = self.config.min_peak_reference

    @property
    def current_level(self) -> float:
        """Current smoothed output level in range [0.0, 1.0]."""
        return self._current_level

    @property
    def peak_reference(self) -> float:
        """Current adaptive peak reference."""
        return self._peak_reference

    def reset(self) -> None:
        """Reset internal envelope and adaptive baseline."""
        self._current_level = 0.0
        self._peak_reference = self.config.min_peak_reference

    def process(self, raw_value: float) -> float:
        """Process an instantaneous raw amplitude or band energy value.

        Args:
            raw_value: Instantaneous non-negative energy or RMS value.

        Returns:
            Normalized and smoothed value in range [0.0, 1.0].
        """
        raw_val = max(0.0, float(raw_value))

        # Check silence threshold
        if raw_val <= self.config.noise_floor:
            # Smoothly decay towards silence
            self._current_level *= (1.0 - self.config.release_factor)
            if self._current_level < 1e-4:
                self._current_level = 0.0
            return self._current_level

        # Update adaptive peak reference
        if raw_val > self._peak_reference:
            # Fast tracking upwards on new peaks
            self._peak_reference = raw_val
        else:
            # Slow leaky decay downwards to adapt to quieter passages
            decayed = self._peak_reference * (1.0 - self.config.peak_decay_rate)
            self._peak_reference = max(self.config.min_peak_reference, decayed)

        # Calculate normalized target ratio
        normalized_target = min(1.0, raw_val / self._peak_reference)

        # Apply asymmetric attack/release envelope
        if normalized_target > self._current_level:
            # Fast attack
            self._current_level += self.config.attack_factor * (normalized_target - self._current_level)
        else:
            # Slower release
            self._current_level += self.config.release_factor * (normalized_target - self._current_level)

        self._current_level = max(0.0, min(1.0, self._current_level))
        return self._current_level
