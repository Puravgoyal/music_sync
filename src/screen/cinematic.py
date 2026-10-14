"""Cinematic image processing improvements: black-bar detection, dark scene scaling, and capture fallbacks."""

from enum import Enum, auto
import time
from typing import Optional, Tuple
import numpy as np


class CaptureHealth(Enum):
    """Health status of the screen capture pipeline."""

    OK = auto()
    STALE = auto()
    ERROR = auto()
    DISCONNECTED = auto()


def detect_black_bars(
    frame: np.ndarray,
    luminance_threshold: float = 0.045,
    max_crop_ratio: float = 0.35,
) -> Tuple[int, int, int, int]:
    """Detect persistent letterbox (top/bottom) and pillarbox (left/right) black borders.

    Args:
        frame: Image array of shape (H, W, 3) in RGB uint8.
        luminance_threshold: Maximum luminance [0.0, 1.0] to consider as black border.
        max_crop_ratio: Maximum fraction of dimension to crop (safety limit, default 0.35).

    Returns:
        (top_crop, bottom_crop, left_crop, right_crop) in pixels.
    """
    if frame is None or frame.ndim != 3 or frame.shape[0] < 4 or frame.shape[1] < 4:
        return (0, 0, 0, 0)

    h, w, _ = frame.shape
    # Compute 2D luminance map
    lum = (
        0.2126 * (frame[..., 0].astype(np.float32) / 255.0)
        + 0.7152 * (frame[..., 1].astype(np.float32) / 255.0)
        + 0.0722 * (frame[..., 2].astype(np.float32) / 255.0)
    )

    max_h_crop = int(round(h * max_crop_ratio))
    max_w_crop = int(round(w * max_crop_ratio))

    # Row-wise mean luminance
    row_means = np.mean(lum, axis=1)
    # Column-wise mean luminance
    col_means = np.mean(lum, axis=0)

    # If the ENTIRE scene is black or dark, don't crop away the whole image!
    if np.mean(lum) <= luminance_threshold:
        return (0, 0, 0, 0)

    # Top crop
    top_crop = 0
    for r in range(max_h_crop):
        if row_means[r] <= luminance_threshold:
            top_crop = r + 1
        else:
            break

    # Bottom crop
    bottom_crop = 0
    for r in range(h - 1, h - 1 - max_h_crop, -1):
        if row_means[r] <= luminance_threshold:
            bottom_crop = h - r
        else:
            break

    # Left crop
    left_crop = 0
    for c in range(max_w_crop):
        if col_means[c] <= luminance_threshold:
            left_crop = c + 1
        else:
            break

    # Right crop
    right_crop = 0
    for c in range(w - 1, w - 1 - max_w_crop, -1):
        if col_means[c] <= luminance_threshold:
            right_crop = w - c
        else:
            break

    # Ensure remaining area has at least 30% of each dimension
    if (h - top_crop - bottom_crop) < (h * 0.30):
        top_crop = 0
        bottom_crop = 0
    if (w - left_crop - right_crop) < (w * 0.30):
        left_crop = 0
        right_crop = 0

    return (top_crop, bottom_crop, left_crop, right_crop)


def crop_frame_borders(frame: np.ndarray, borders: Tuple[int, int, int, int]) -> np.ndarray:
    """Crop detected letterbox and pillarbox borders from frame."""
    top, bottom, left, right = borders
    h, w, _ = frame.shape
    y_end = h - bottom if bottom > 0 else h
    x_end = w - right if right > 0 else w
    if top >= y_end or left >= x_end:
        return frame
    return frame[top:y_end, left:x_end]


def scale_scene_brightness(
    luminance: float,
    min_brightness: int = 25,
    max_brightness: int = 255,
    gamma: float = 0.85,
) -> int:
    """Scale detected scene luminance to bulb brightness [min_brightness, max_brightness].

    During dark scenes, smoothly rests at min_brightness without abrupt power cycling.
    """
    lum_clamped = max(0.0, min(1.0, float(luminance)))
    # Gentle gamma curve to keep dark/dim scenes subtle and bright explosions punchy
    scaled_lum = lum_clamped ** gamma
    target_b = min_brightness + scaled_lum * (max_brightness - min_brightness)
    return max(0, min(255, int(round(target_b))))


class CaptureFallbackManager:
    """Monitors screen capture health, avoids stale transmission, and performs graceful fallback."""

    def __init__(
        self,
        stale_timeout_s: float = 1.2,
        fade_duration_s: float = 2.0,
        safe_fallback_rgb: Tuple[int, int, int] = (255, 214, 170),  # Warm ambient white
        min_brightness: int = 25,
    ) -> None:
        self.stale_timeout_s = stale_timeout_s
        self.fade_duration_s = fade_duration_s
        self.safe_fallback_rgb = safe_fallback_rgb
        self.min_brightness = min_brightness

        self._last_valid_time: float = time.perf_counter()
        self._last_valid_rgb: Tuple[int, int, int] = safe_fallback_rgb
        self._last_valid_brightness: int = min_brightness
        self._health: CaptureHealth = CaptureHealth.OK

    @property
    def health(self) -> CaptureHealth:
        return self._health

    @property
    def is_fallback_active(self) -> bool:
        return self._health != CaptureHealth.OK

    def record_frame(self, rgb: Tuple[int, int, int], brightness: int, now: Optional[float] = None) -> None:
        """Record successful capture frame arrival."""
        t = now if now is not None else time.perf_counter()
        self._last_valid_time = t
        self._last_valid_rgb = rgb
        self._last_valid_brightness = brightness
        self._health = CaptureHealth.OK

    def record_error(self, is_disconnected: bool = False) -> None:
        """Record capture error or device disconnection."""
        self._health = CaptureHealth.DISCONNECTED if is_disconnected else CaptureHealth.ERROR

    def get_state_or_fallback(
        self,
        now: Optional[float] = None,
    ) -> Tuple[Tuple[int, int, int], int, bool]:
        """Return (rgb, brightness, is_fallback).

        If healthy, returns current valid state.
        If stale or error, smoothly fades towards safe ambient fallback.
        """
        t = now if now is not None else time.perf_counter()
        elapsed = t - self._last_valid_time

        if elapsed <= self.stale_timeout_s and self._health == CaptureHealth.OK:
            return self._last_valid_rgb, self._last_valid_brightness, False

        # In stale or error state
        if self._health == CaptureHealth.OK:
            self._health = CaptureHealth.STALE

        stale_elapsed = elapsed - self.stale_timeout_s
        fade_ratio = max(0.0, min(1.0, stale_elapsed / max(0.1, self.fade_duration_s)))

        # Interpolate color towards safe warm ambient
        r0, g0, b0 = self._last_valid_rgb
        rf, gf, bf = self.safe_fallback_rgb
        r = int(round(r0 + fade_ratio * (rf - r0)))
        g = int(round(g0 + fade_ratio * (gf - g0)))
        b = int(round(b0 + fade_ratio * (bf - b0)))

        # Decay brightness towards min_brightness
        curr_b = int(round(self._last_valid_brightness + fade_ratio * (self.min_brightness - self._last_valid_brightness)))

        return (r, g, b), curr_b, True
