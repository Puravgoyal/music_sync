"""Deterministic unit tests for color extraction, linear sRGB, dominant color, and edge ambience."""

import numpy as np
import pytest

from src.screen.cinematic import (
    crop_frame_borders,
    detect_black_bars,
    scale_scene_brightness,
)
from src.screen.color_extraction import (
    extract_average_color,
    extract_dominant_color,
    extract_edge_color,
    linear_to_srgb,
    srgb_to_linear,
)


class TestLinearColorConversions:
    """Verify IEC 61966-2-1 linear sRGB conversions."""

    def test_srgb_linear_roundtrip(self) -> None:
        values = np.linspace(0.0, 1.0, 100, dtype=np.float32)
        linear = srgb_to_linear(values)
        recovered = linear_to_srgb(linear)
        np.testing.assert_allclose(recovered, values, atol=1e-4)

    def test_extreme_values(self) -> None:
        zeros = np.zeros(3, dtype=np.float32)
        ones = np.ones(3, dtype=np.float32)
        np.testing.assert_allclose(srgb_to_linear(zeros), zeros, atol=1e-5)
        np.testing.assert_allclose(srgb_to_linear(ones), ones, atol=1e-5)


class TestColorExtractionStrategies:
    """Verify Strategy 1 (Average), Strategy 2 (Dominant), and Strategy 3 (Edge)."""

    def test_solid_colors_average(self) -> None:
        # Solid Red
        red_frame = np.full((36, 64, 3), [255, 0, 0], dtype=np.uint8)
        rgb, lum = extract_average_color(red_frame)
        assert rgb == (255, 0, 0)
        assert pytest.approx(lum, abs=0.02) == 0.2126

        # Solid Green
        green_frame = np.full((36, 64, 3), [0, 255, 0], dtype=np.uint8)
        rgb, lum = extract_average_color(green_frame)
        assert rgb == (0, 255, 0)
        assert pytest.approx(lum, abs=0.02) == 0.7152

        # Solid Blue
        blue_frame = np.full((36, 64, 3), [0, 0, 255], dtype=np.uint8)
        rgb, lum = extract_average_color(blue_frame)
        assert rgb == (0, 0, 255)
        assert pytest.approx(lum, abs=0.02) == 0.0722

    def test_pure_black_and_white(self) -> None:
        black_frame = np.zeros((36, 64, 3), dtype=np.uint8)
        rgb, lum = extract_average_color(black_frame)
        assert rgb == (0, 0, 0)
        assert lum == 0.0

        white_frame = np.full((36, 64, 3), 255, dtype=np.uint8)
        rgb, lum = extract_average_color(white_frame)
        assert rgb == (255, 255, 255)
        assert pytest.approx(lum, abs=0.02) == 1.0

    def test_anti_gray_saturation_boost(self) -> None:
        # Multi-color frame: equal split of vibrant red, green, blue
        frame = np.zeros((36, 60, 3), dtype=np.uint8)
        frame[:, :20] = [255, 0, 0]
        frame[:, 20:40] = [0, 255, 0]
        frame[:, 40:] = [0, 0, 255]

        rgb_boost, _ = extract_average_color(frame, saturation_boost=True)
        # Saturated colors should not collapse to flat muddy gray
        max_c = max(rgb_boost)
        min_c = min(rgb_boost)
        assert (max_c - min_c) >= 15

    def test_dominant_color_sunset_scene(self) -> None:
        # Sunset scenario: 70% warm orange/red sky, 30% dark foreground
        frame = np.zeros((36, 64, 3), dtype=np.uint8)
        frame[:25, :] = [240, 100, 20]   # Warm sunset orange
        frame[25:, :] = [15, 10, 12]      # Dark mountains/silhouette

        rgb, lum = extract_dominant_color(frame)
        # Dominant color must be in the warm orange/red spectrum (R > G > B)
        assert rgb[0] > rgb[1] > rgb[2]
        assert rgb[0] >= 180
        assert rgb[2] <= 50

    def test_dominant_color_underwater_scene(self) -> None:
        # Underwater scenario: 75% deep blue/cyan water, 25% sand
        frame = np.zeros((36, 64, 3), dtype=np.uint8)
        frame[:28, :] = [10, 140, 210]   # Cyan/blue ocean
        frame[28:, :] = [80, 70, 50]     # Sand/rocks

        rgb, lum = extract_dominant_color(frame)
        # Dominant color must be blue/cyan (B > R and G > R)
        assert rgb[2] > rgb[0]
        assert rgb[1] > rgb[0]
        assert rgb[2] >= 160

    def test_subtitle_resistance(self) -> None:
        # Dark movie frame with prominent white subtitles in the bottom center
        frame = np.full((40, 80, 3), [15, 20, 35], dtype=np.uint8)  # Night scene
        # Subtitle overlay in bottom 15%
        frame[34:38, 20:60] = [255, 255, 255]

        # Dominant color extraction should not be tricked into flashing pure white
        rgb, lum = extract_dominant_color(frame, exclude_subtitles=True)
        assert rgb[0] < 100 and rgb[1] < 100
        # Should stay dark / ambient
        assert lum < 0.25

    def test_edge_extraction_regions(self) -> None:
        # Left edge test
        frame_l = np.zeros((40, 60, 3), dtype=np.uint8)
        frame_l[:, :15] = [255, 0, 0]      # Left edge: Red
        rgb_l, _ = extract_edge_color(frame_l, edge="left", thickness_ratio=0.20)
        assert rgb_l[0] > 180 and rgb_l[1] < 50

        # Right edge test
        frame_r = np.zeros((40, 60, 3), dtype=np.uint8)
        frame_r[:, -15:] = [0, 255, 0]     # Right edge: Green
        rgb_r, _ = extract_edge_color(frame_r, edge="right", thickness_ratio=0.20)
        assert rgb_r[1] > 180 and rgb_r[0] < 50

        # Top edge test
        frame_t = np.zeros((40, 60, 3), dtype=np.uint8)
        frame_t[:10, :] = [0, 0, 255]      # Top edge: Blue
        rgb_t, _ = extract_edge_color(frame_t, edge="top", thickness_ratio=0.20)
        assert rgb_t[2] > 180 and rgb_t[0] < 50

        # Bottom edge test
        frame_b = np.zeros((40, 60, 3), dtype=np.uint8)
        frame_b[-10:, :] = [255, 255, 0]   # Bottom edge: Yellow
        rgb_b, _ = extract_edge_color(frame_b, edge="bottom", thickness_ratio=0.20)
        assert rgb_b[0] > 180 and rgb_b[1] > 180 and rgb_b[2] < 50

    def test_edge_thickness_scaling(self) -> None:
        frame = np.zeros((40, 100, 3), dtype=np.uint8)
        frame[:, 90:] = [200, 50, 50]  # Only the outer 10% is red

        # Thin 5% slice -> captures red
        rgb_thin, _ = extract_edge_color(frame, edge="right", thickness_ratio=0.08)
        assert rgb_thin[0] > 150

        # Thick 35% slice -> averages red with black interior
        rgb_thick, _ = extract_edge_color(frame, edge="right", thickness_ratio=0.35)
        assert rgb_thick[0] < rgb_thin[0]


class TestCinematicFilters:
    """Verify black bar detection, border cropping, and dark scene scaling."""

    def test_detect_letterbox_black_bars(self) -> None:
        # 16:9 frame with 2.35:1 movie letterbox bars top and bottom
        h, w = 40, 80
        frame = np.full((h, w, 3), [180, 120, 60], dtype=np.uint8)
        frame[:8, :] = [0, 0, 0]     # Top black bar (8 rows)
        frame[-8:, :] = [0, 0, 0]    # Bottom black bar (8 rows)

        borders = detect_black_bars(frame, luminance_threshold=0.04)
        top, bottom, left, right = borders
        assert top == 8
        assert bottom == 8
        assert left == 0
        assert right == 0

        cropped = crop_frame_borders(frame, borders)
        assert cropped.shape == (24, 80, 3)
        assert np.all(cropped == [180, 120, 60])

    def test_detect_pillarbox_black_bars(self) -> None:
        # 4:3 content on wide display with left/right pillarbox bars
        h, w = 36, 64
        frame = np.full((h, w, 3), [100, 150, 200], dtype=np.uint8)
        frame[:, :10] = [0, 0, 0]    # Left pillarbox (10 cols)
        frame[:, -10:] = [0, 0, 0]   # Right pillarbox (10 cols)

        borders = detect_black_bars(frame, luminance_threshold=0.04)
        top, bottom, left, right = borders
        assert top == 0 and bottom == 0
        assert left == 10 and right == 10

        cropped = crop_frame_borders(frame, borders)
        assert cropped.shape == (36, 44, 3)

    def test_no_crop_on_legitimately_dark_scene(self) -> None:
        # A legitimately dark nighttime scene must NOT crop away everything
        dark_frame = np.full((36, 64, 3), [5, 5, 8], dtype=np.uint8)
        borders = detect_black_bars(dark_frame)
        assert borders == (0, 0, 0, 0)

    def test_brightness_scaling_dark_scenes(self) -> None:
        # Pure black frame rests smoothly at min_brightness, does not shut off
        b_black = scale_scene_brightness(0.0, min_brightness=25, max_brightness=255)
        assert b_black == 25

        # Dim scene (0.10 luminance) scales smoothly above min_brightness
        b_dim = scale_scene_brightness(0.10, min_brightness=25, max_brightness=255)
        assert 25 < b_dim < 100

        # Maximum bright scene reaches max_brightness
        b_bright = scale_scene_brightness(1.0, min_brightness=25, max_brightness=255)
        assert b_bright == 255
