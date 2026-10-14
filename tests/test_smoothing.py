"""Unit tests for temporal color smoothing, circular hue interpolation, and presets."""

import colorsys
import pytest

from src.screen.smoothing import (
    PRESET_CONFIGS,
    SmoothingParams,
    SmoothingPresetType,
    TemporalColorSmoother,
    get_smoothing_params,
)


class TestTemporalColorSmoother:
    """Verify temporal smoothing math, circular hue interpolation, and presets."""

    def test_presets_configuration(self) -> None:
        cinematic = get_smoothing_params("cinematic")
        balanced = get_smoothing_params("balanced")
        responsive = get_smoothing_params("responsive")

        # Responsive must be more immediate than Cinematic
        assert responsive.color_smoothing < cinematic.color_smoothing
        assert responsive.attack_speed > cinematic.attack_speed
        assert responsive.release_speed > cinematic.release_speed

        # Balanced sits between Cinematic and Responsive
        assert responsive.color_smoothing < balanced.color_smoothing < cinematic.color_smoothing

    def test_circular_hue_boundary_wrapping(self) -> None:
        """Verify that transitioning from 355 deg to 5 deg traverses 0 deg directly.

        It must NOT take the long detour through cyan, yellow, and green.
        """
        # Starting color: Hue = 0.98 (~353 deg, magenta-red)
        r0, g0, b0 = [int(round(c * 255)) for c in colorsys.hsv_to_rgb(0.98, 1.0, 1.0)]
        # Target color: Hue = 0.02 (~7 deg, orange-red)
        rt, gt, bt = [int(round(c * 255)) for c in colorsys.hsv_to_rgb(0.02, 1.0, 1.0)]

        smoother = TemporalColorSmoother(
            params=SmoothingParams(color_smoothing=0.5, attack_speed=0.5, release_speed=0.5),
            initial_rgb=(r0, g0, b0),
            initial_brightness=100.0,
        )

        # Single step transition
        next_rgb, _ = smoother.update((rt, gt, bt), 100, now=smoother._last_time + 0.05)

        # Compute resulting hue
        h_next, s_next, v_next = colorsys.rgb_to_hsv(
            next_rgb[0] / 255.0, next_rgb[1] / 255.0, next_rgb[2] / 255.0
        )

        # Hue must stay close to the red boundary (either > 0.95 or < 0.05)
        # It must NOT end up near 0.50 (cyan)
        assert (h_next > 0.95 or h_next < 0.05), f"Hue jumped to {h_next} across color wheel!"
        assert s_next > 0.85, "Saturation collapsed during hue boundary wrapping!"

    def test_asymmetrical_attack_release_brightness(self) -> None:
        """Verify that attack speed (rising) responds faster than release speed (decay)."""
        params = SmoothingParams(color_smoothing=0.3, attack_speed=0.80, release_speed=0.10)

        # 1. Rising brightness test: 20 -> 220
        smoother_rise = TemporalColorSmoother(
            params=params,
            initial_rgb=(200, 200, 200),
            initial_brightness=20.0,
        )
        t0 = smoother_rise._last_time
        _, b_rise = smoother_rise.update((200, 200, 200), 220, now=t0 + 0.066)
        rise_delta = b_rise - 20.0

        # 2. Falling brightness test: 220 -> 20
        smoother_fall = TemporalColorSmoother(
            params=params,
            initial_rgb=(200, 200, 200),
            initial_brightness=220.0,
        )
        _, b_fall = smoother_fall.update((200, 200, 200), 20, now=t0 + 0.066)
        fall_delta = 220.0 - b_fall

        # Attack rate (rising) must be substantially faster than release rate (falling)
        assert rise_delta > fall_delta * 2.0

    def test_scene_cut_acceleration(self) -> None:
        """Verify that large sudden color cuts accelerate the smoothing rate."""
        params = SmoothingParams(
            color_smoothing=0.85,  # Heavy smoothing
            attack_speed=0.20,
            release_speed=0.20,
            scene_cut_threshold=0.30,
            scene_cut_multiplier=3.0,
        )

        # 1. Small change: (200, 200, 200) -> (210, 210, 210)
        smoother_small = TemporalColorSmoother(params=params, initial_rgb=(200, 200, 200), initial_brightness=100.0)
        t0 = smoother_small._last_time
        small_next, _ = smoother_small.update((210, 210, 210), 100, now=t0 + 0.066)
        small_step_ratio = (small_next[0] - 200) / 10.0

        # 2. Scene cut change: Black (0, 0, 0) -> Pure Red (255, 0, 0)
        smoother_cut = TemporalColorSmoother(params=params, initial_rgb=(0, 0, 0), initial_brightness=100.0)
        cut_next, _ = smoother_cut.update((255, 0, 0), 100, now=t0 + 0.066)
        cut_step_ratio = cut_next[0] / 255.0

        # Scene cut step ratio must be accelerated compared to the small step ratio
        assert cut_step_ratio > small_step_ratio
