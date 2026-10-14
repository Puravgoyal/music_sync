"""Temporal color smoothing, circular hue boundary interpolation, and presets."""

import colorsys
from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Optional, Tuple


class SmoothingPresetType(Enum):
    """Named preset profiles for screen color and brightness smoothing."""

    CINEMATIC = "cinematic"
    BALANCED = "balanced"
    RESPONSIVE = "responsive"


@dataclass
class SmoothingParams:
    """Configurable parameters governing temporal smoothing."""

    color_smoothing: float  # [0.0, 0.95]
    attack_speed: float     # [0.01, 1.0] for rising brightness
    release_speed: float    # [0.01, 1.0] for falling brightness
    scene_cut_threshold: float = 0.40  # Euclidean RGB delta to trigger scene cut acceleration
    scene_cut_multiplier: float = 2.5


PRESET_CONFIGS = {
    SmoothingPresetType.CINEMATIC: SmoothingParams(
        color_smoothing=0.65,
        attack_speed=0.35,
        release_speed=0.15,
        scene_cut_threshold=0.38,
        scene_cut_multiplier=2.5,
    ),
    SmoothingPresetType.BALANCED: SmoothingParams(
        color_smoothing=0.40,
        attack_speed=0.55,
        release_speed=0.25,
        scene_cut_threshold=0.42,
        scene_cut_multiplier=2.2,
    ),
    SmoothingPresetType.RESPONSIVE: SmoothingParams(
        color_smoothing=0.15,
        attack_speed=0.85,
        release_speed=0.45,
        scene_cut_threshold=0.45,
        scene_cut_multiplier=1.8,
    ),
}


def get_smoothing_params(preset: str) -> SmoothingParams:
    """Retrieve smoothing parameter set for preset name."""
    try:
        p_enum = SmoothingPresetType(preset.strip().lower())
    except Exception:
        p_enum = SmoothingPresetType.CINEMATIC
    return PRESET_CONFIGS[p_enum]


class TemporalColorSmoother:
    """Smooths color and brightness transitions temporally with shortest-path hue wrapping."""

    def __init__(
        self,
        params: Optional[SmoothingParams] = None,
        initial_rgb: Tuple[int, int, int] = (255, 255, 255),
        initial_brightness: float = 25.0,
    ) -> None:
        self.params = params or PRESET_CONFIGS[SmoothingPresetType.CINEMATIC]
        self._current_rgb: Tuple[float, float, float] = (
            float(initial_rgb[0]),
            float(initial_rgb[1]),
            float(initial_rgb[2]),
        )
        self._current_brightness: float = float(initial_brightness)
        self._last_time: float = time.perf_counter()

    @property
    def current_rgb(self) -> Tuple[int, int, int]:
        return (
            max(0, min(255, int(round(self._current_rgb[0])))),
            max(0, min(255, int(round(self._current_rgb[1])))),
            max(0, min(255, int(round(self._current_rgb[2])))),
        )

    @property
    def current_brightness(self) -> int:
        return max(0, min(255, int(round(self._current_brightness))))

    def set_preset(self, preset: str) -> None:
        """Switch active smoothing preset."""
        self.params = get_smoothing_params(preset)

    def reset(
        self,
        rgb: Tuple[int, int, int] = (255, 255, 255),
        brightness: float = 25.0,
    ) -> None:
        """Reset internal filter state."""
        self._current_rgb = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
        self._current_brightness = float(brightness)
        self._last_time = time.perf_counter()

    def update(
        self,
        target_rgb: Tuple[int, int, int],
        target_brightness: int,
        now: Optional[float] = None,
    ) -> Tuple[Tuple[int, int, int], int]:
        """Apply temporal smoothing to target RGB and brightness.

        Returns:
            (smoothed_rgb, smoothed_brightness).
        """
        t = now if now is not None else time.perf_counter()
        dt = max(0.001, min(0.5, t - self._last_time))
        self._last_time = t

        # Normalized current and target colors
        r_c, g_c, b_c = [c / 255.0 for c in self._current_rgb]
        r_t, g_t, b_t = [c / 255.0 for c in target_rgb]

        # Calculate Euclidean RGB distance for scene cut detection
        delta_rgb = math.sqrt((r_t - r_c) ** 2 + (g_t - g_c) ** 2 + (b_t - b_c) ** 2)
        is_scene_cut = delta_rgb >= self.params.scene_cut_threshold

        # Base alpha: (1.0 - smoothing) scaled by time
        smoothing_factor = self.params.color_smoothing
        if is_scene_cut:
            smoothing_factor = max(0.05, smoothing_factor / self.params.scene_cut_multiplier)

        # Rate of convergence towards target
        alpha = max(0.05, min(1.0, (1.0 - smoothing_factor) * (dt / 0.066)))

        # Convert to HSV for hue-aware circular interpolation
        h_c, s_c, v_c = colorsys.rgb_to_hsv(r_c, g_c, b_c)
        h_t, s_t, v_t = colorsys.rgb_to_hsv(r_t, g_t, b_t)

        # Circular shortest-path delta on hue [0.0, 1.0)
        delta_h = ((h_t - h_c + 0.5) % 1.0) - 0.5
        new_h = (h_c + alpha * delta_h) % 1.0

        # Linear interpolation for saturation and value
        new_s = s_c + alpha * (s_t - s_c)
        new_v = v_c + alpha * (v_t - v_c)

        # Convert back to RGB
        r_next, g_next, b_next = colorsys.hsv_to_rgb(
            new_h,
            max(0.0, min(1.0, new_s)),
            max(0.0, min(1.0, new_v)),
        )

        self._current_rgb = (r_next * 255.0, g_next * 255.0, b_next * 255.0)

        # Asymmetrical attack / release brightness smoothing
        target_b = float(target_brightness)
        if target_b > self._current_brightness:
            b_rate = max(0.02, min(1.0, self.params.attack_speed * (dt / 0.066)))
        else:
            b_rate = max(0.02, min(1.0, self.params.release_speed * (dt / 0.066)))

        if is_scene_cut:
            b_rate = min(1.0, b_rate * self.params.scene_cut_multiplier)

        self._current_brightness += b_rate * (target_b - self._current_brightness)

        return self.current_rgb, self.current_brightness
