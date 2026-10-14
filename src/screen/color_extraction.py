"""Color extraction algorithms for screen ambilight analysis.

Implements:
1. Average Screen Color in linear-light sRGB with chromatic preservation.
2. Dominant Color via fast saturation-luminance weighted hue binning with subtitle resistance.
3. Edge-Based Ambience for directional single-bulb bias lighting.
"""

from typing import Tuple
import numpy as np


def srgb_to_linear(rgb_norm: np.ndarray) -> np.ndarray:
    """Convert normalized sRGB [0.0, 1.0] to linear light RGB (IEC 61966-2-1)."""
    return np.where(
        rgb_norm <= 0.04045,
        rgb_norm / 12.92,
        np.power(np.maximum((rgb_norm + 0.055) / 1.055, 0.0), 2.4),
    )


def linear_to_srgb(lin_norm: np.ndarray) -> np.ndarray:
    """Convert linear light RGB [0.0, 1.0] back to gamma-corrected display sRGB."""
    lin_clamped = np.maximum(lin_norm, 0.0)
    return np.where(
        lin_clamped <= 0.0031308,
        lin_clamped * 12.92,
        1.055 * np.power(lin_clamped, 1.0 / 2.4) - 0.055,
    )


def calculate_perceived_luminance(rgb_uint8: np.ndarray) -> float:
    """Calculate perceived photometric luminance Y [0.0, 1.0] using ITU-R BT.709."""
    r = float(rgb_uint8[0]) / 255.0
    g = float(rgb_uint8[1]) / 255.0
    b = float(rgb_uint8[2]) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb_to_hsv_numpy(rgb_norm: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fast vectorized RGB [0.0, 1.0] to HSV [0.0, 1.0] conversion."""
    r = rgb_norm[..., 0]
    g = rgb_norm[..., 1]
    b = rgb_norm[..., 2]

    v = np.maximum(np.maximum(r, g), b)
    m = np.minimum(np.minimum(r, g), b)
    delta = v - m

    # Saturation
    s = np.zeros_like(v)
    non_zero_v = v > 1e-5
    s[non_zero_v] = delta[non_zero_v] / v[non_zero_v]

    # Hue
    h = np.zeros_like(v)
    non_zero_d = delta > 1e-5

    idx_r = non_zero_d & (v == r)
    idx_g = non_zero_d & (v == g) & (~idx_r)
    idx_b = non_zero_d & (v == b) & (~idx_r) & (~idx_g)

    h[idx_r] = ((g[idx_r] - b[idx_r]) / delta[idx_r]) % 6.0
    h[idx_g] = ((b[idx_g] - r[idx_g]) / delta[idx_g]) + 2.0
    h[idx_b] = ((r[idx_b] - g[idx_b]) / delta[idx_b]) + 4.0
    h = (h / 6.0) % 1.0

    return h, s, v


def extract_average_color(
    frame: np.ndarray,
    saturation_boost: bool = True,
) -> Tuple[Tuple[int, int, int], float]:
    """Compute representative average color in linear light with anti-gray chromatic preservation.

    Args:
        frame: Downsampled image array of shape (H, W, 3) in RGB uint8 [0-255].
        saturation_boost: If True, prevents multi-colored frames from canceling into flat gray.

    Returns:
        ((r, g, b), luminance) where r,g,b in [0, 255] and luminance in [0.0, 1.0].
    """
    if frame is None or frame.size == 0:
        return (0, 0, 0), 0.0

    # Ensure shape (N, 3)
    pixels = frame.reshape(-1, 3).astype(np.float32) / 255.0
    n_pixels = len(pixels)
    if n_pixels == 0:
        return (0, 0, 0), 0.0

    # Linear light conversion
    lin_pixels = srgb_to_linear(pixels)

    if saturation_boost and n_pixels > 1:
        # Calculate pixel saturation S = (max - min) / max
        max_c = np.max(pixels, axis=1)
        min_c = np.min(pixels, axis=1)
        sat = np.zeros(n_pixels, dtype=np.float32)
        valid = max_c > 1e-4
        sat[valid] = (max_c[valid] - min_c[valid]) / max_c[valid]

        mean_sat = float(np.mean(sat))
        # If scene has moderate chromatic content, weight towards saturated pixels
        if mean_sat > 0.15:
            weights = (sat ** 1.3) + 0.12
            weight_sum = np.sum(weights)
            if weight_sum > 1e-5:
                lin_avg = np.sum(lin_pixels * weights[:, np.newaxis], axis=0) / weight_sum
            else:
                lin_avg = np.mean(lin_pixels, axis=0)
        else:
            lin_avg = np.mean(lin_pixels, axis=0)
    else:
        lin_avg = np.mean(lin_pixels, axis=0)

    # Convert back to display sRGB
    srgb_avg = linear_to_srgb(lin_avg)
    srgb_avg = np.clip(srgb_avg, 0.0, 1.0)

    # Protection against washed-out gray when scene contains vibrant colors
    if saturation_boost and n_pixels > 1 and mean_sat > 0.20:
        max_avg = float(np.max(srgb_avg))
        min_avg = float(np.min(srgb_avg))
        avg_sat = (max_avg - min_avg) / (max_avg + 1e-5)
        if avg_sat < 0.18:
            import colorsys
            h_val, s_val, v_val = colorsys.rgb_to_hsv(float(srgb_avg[0]), float(srgb_avg[1]), float(srgb_avg[2]))
            if s_val < 0.05:
                # Disambiguate hue using the most prominent chromatic pixels
                h_all, s_all, v_all = rgb_to_hsv_numpy(pixels)
                chr_idx = np.where(s_all > 0.3)[0]
                if len(chr_idx) > 0:
                    h_val = float(h_all[chr_idx[0]])
            new_sat = min(1.0, max(s_val, 0.35 * mean_sat))
            rb, gb, bb = colorsys.hsv_to_rgb(h_val, new_sat, v_val)
            srgb_avg = np.array([rb, gb, bb], dtype=np.float32)

    r = int(round(float(srgb_avg[0]) * 255.0))
    g = int(round(float(srgb_avg[1]) * 255.0))
    b = int(round(float(srgb_avg[2]) * 255.0))

    lum = 0.2126 * (r / 255.0) + 0.7152 * (g / 255.0) + 0.0722 * (b / 255.0)
    return (r, g, b), lum


def extract_dominant_color(
    frame: np.ndarray,
    exclude_subtitles: bool = True,
    num_hue_bins: int = 16,
) -> Tuple[Tuple[int, int, int], float]:
    """Extract visually dominant color using saturation/luminance weighted hue binning.

    Resistant to white subtitles, dark letterbox bars, and small noisy UI elements.

    Args:
        frame: Image array of shape (H, W, 3) in RGB uint8.
        exclude_subtitles: If True, suppresses bright desaturated text in the bottom region.
        num_hue_bins: Number of discrete hue bins (default 16, 22.5 deg each).

    Returns:
        ((r, g, b), luminance) representing dominant screen color.
    """
    if frame is None or frame.size == 0:
        return (0, 0, 0), 0.0

    h_img, w_img, _ = frame.shape
    pixels_rgb = frame.astype(np.float32) / 255.0

    # Convert to HSV
    h, s, v = rgb_to_hsv_numpy(pixels_rgb)

    # Flatten coordinates for spatial masking
    h_flat = h.ravel()
    s_flat = s.ravel()
    v_flat = v.ravel()
    rgb_flat = pixels_rgb.reshape(-1, 3)

    # Subtitle suppression: filter out high-brightness low-saturation pixels in bottom 25%
    valid_mask = np.ones(len(h_flat), dtype=bool)

    if exclude_subtitles and h_img >= 4:
        sub_start_row = int(h_img * 0.75)
        # Create 2D mask for subtitles
        subtitle_2d = np.zeros((h_img, w_img), dtype=bool)
        subtitle_2d[sub_start_row:, :] = (v[sub_start_row:, :] > 0.80) & (s[sub_start_row:, :] < 0.20)
        valid_mask &= (~subtitle_2d.ravel())

    # Exclude near-black pixels from chromatic search (shadows/dark letterbox)
    valid_mask &= (v_flat > 0.08)

    # Identify chromatic pixels: requires minimum saturation and brightness
    chromatic_mask = valid_mask & (s_flat >= 0.16) & (v_flat >= 0.10)
    num_chromatic = int(np.count_nonzero(chromatic_mask))
    total_valid = int(np.count_nonzero(valid_mask))

    # If chromatic pixels represent at least 5% of non-black pixels, find dominant hue bin
    if total_valid > 0 and (num_chromatic / total_valid) >= 0.05:
        chr_h = h_flat[chromatic_mask]
        chr_s = s_flat[chromatic_mask]
        chr_v = v_flat[chromatic_mask]
        chr_rgb = rgb_flat[chromatic_mask]

        # Weight each chromatic pixel by saturation^1.5 * value (visual saliency)
        weights = (chr_s ** 1.5) * chr_v

        # Bin hues into discrete buckets
        bin_indices = np.clip((chr_h * num_hue_bins).astype(int), 0, num_hue_bins - 1)
        bin_weights = np.zeros(num_hue_bins, dtype=np.float32)
        np.add.at(bin_weights, bin_indices, weights)

        # Winning hue bin
        best_bin = int(np.argmax(bin_weights))
        in_best_bin = (bin_indices == best_bin)

        if np.any(in_best_bin):
            best_rgb = chr_rgb[in_best_bin]
            best_w = weights[in_best_bin]
            w_sum = np.sum(best_w)
            if w_sum > 1e-5:
                dom_rgb = np.sum(best_rgb * best_w[:, np.newaxis], axis=0) / w_sum
            else:
                dom_rgb = np.mean(best_rgb, axis=0)

            # Preserve overall scene luminance while using dominant chromatic hue
            dom_rgb = np.clip(dom_rgb, 0.0, 1.0)
            r = int(round(float(dom_rgb[0]) * 255.0))
            g = int(round(float(dom_rgb[1]) * 255.0))
            b = int(round(float(dom_rgb[2]) * 255.0))

            # Scene luminance for brightness scaling
            lum = float(np.mean(0.2126 * rgb_flat[:, 0] + 0.7152 * rgb_flat[:, 1] + 0.0722 * rgb_flat[:, 2]))
            return (r, g, b), lum

    # Monochromatic or neutral scene (e.g. grayscale film, snow, fog):
    # Fall back to linear-average calculation
    return extract_average_color(frame, saturation_boost=False)


def extract_edge_color(
    frame: np.ndarray,
    edge: str = "all",
    thickness_ratio: float = 0.15,
    method: str = "average",
) -> Tuple[Tuple[int, int, int], float]:
    """Extract representative color for a specified perimeter region.

    Args:
        frame: Image array of shape (H, W, 3).
        edge: One of 'left', 'right', 'top', 'bottom', 'all'.
        thickness_ratio: Width/height fraction of edge zone [0.02, 0.45] (default 0.15).
        method: Extraction algorithm ('average' or 'dominant').

    Returns:
        ((r, g, b), luminance) for the chosen edge zone.
    """
    if frame is None or frame.size == 0:
        return (0, 0, 0), 0.0

    h, w, _ = frame.shape
    th = max(0.02, min(0.45, float(thickness_ratio)))
    edge_key = edge.strip().lower()

    th_w = max(1, int(round(w * th)))
    th_h = max(1, int(round(h * th)))

    if edge_key == "left":
        sub_frame = frame[:, :th_w, :]
    elif edge_key == "right":
        sub_frame = frame[:, -th_w:, :]
    elif edge_key == "top":
        sub_frame = frame[:th_h, :, :]
    elif edge_key == "bottom":
        sub_frame = frame[-th_h:, :, :]
    elif edge_key == "all":
        # Perimeter mask
        mask = np.zeros((h, w), dtype=bool)
        mask[:th_h, :] = True
        mask[-th_h:, :] = True
        mask[:, :th_w] = True
        mask[:, -th_w:] = True
        edge_pixels = frame[mask]  # shape (N, 3)
        sub_frame = edge_pixels.reshape(1, -1, 3)
    else:
        # Default to full frame
        sub_frame = frame

    if method == "dominant":
        return extract_dominant_color(sub_frame)
    return extract_average_color(sub_frame)
