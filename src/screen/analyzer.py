"""Screen color analysis coordinator combining extraction, cinematic filters, and temporal smoothing."""

from dataclasses import dataclass
import logging
import time
from typing import Optional, Tuple
import numpy as np

from src.screen.cinematic import (
    CaptureFallbackManager,
    crop_frame_borders,
    detect_black_bars,
    scale_scene_brightness,
)
from src.screen.color_extraction import (
    extract_average_color,
    extract_dominant_color,
    extract_edge_color,
)
from src.screen.smoothing import TemporalColorSmoother, get_smoothing_params
from src.sync.state import LightingState

logger = logging.getLogger(__name__)


@dataclass
class ScreenAnalyzerSettings:
    """Configurable settings for screen color analysis."""

    color_strategy: str = "average"       # 'average', 'dominant', 'edge'
    edge_region: str = "all"              # 'all', 'left', 'right', 'top', 'bottom'
    edge_thickness: float = 0.15          # [0.05, 0.40]
    smoothing_preset: str = "cinematic"   # 'cinematic', 'balanced', 'responsive'
    detect_black_bars: bool = True        # Auto letterbox/pillarbox removal
    min_brightness: int = 25              # [0, 255]
    max_brightness: int = 255             # [0, 255]
    gamma: float = 0.85                   # Brightness scaling exponent

    def validate(self) -> None:
        if self.color_strategy not in ("average", "dominant", "edge"):
            self.color_strategy = "average"
        if self.edge_region not in ("all", "left", "right", "top", "bottom"):
            self.edge_region = "all"
        self.edge_thickness = max(0.02, min(0.45, float(self.edge_thickness)))
        if self.smoothing_preset not in ("cinematic", "balanced", "responsive"):
            self.smoothing_preset = "cinematic"
        self.min_brightness = max(0, min(255, int(self.min_brightness)))
        self.max_brightness = max(0, min(255, int(self.max_brightness)))
        if self.min_brightness > self.max_brightness:
            self.min_brightness = self.max_brightness


class ScreenColorAnalyzer:
    """Processes downsampled screen frames into perceptually smoothed bulb LightingState."""

    def __init__(self, settings: Optional[ScreenAnalyzerSettings] = None) -> None:
        self.settings = settings or ScreenAnalyzerSettings()
        self.settings.validate()

        params = get_smoothing_params(self.settings.smoothing_preset)
        self._smoother = TemporalColorSmoother(
            params=params,
            initial_rgb=(255, 214, 170),
            initial_brightness=float(self.settings.min_brightness),
        )
        self._fallback_mgr = CaptureFallbackManager(
            safe_fallback_rgb=(255, 214, 170),
            min_brightness=self.settings.min_brightness,
        )

        self._last_raw_rgb: Tuple[int, int, int] = (255, 214, 170)
        self._last_raw_luminance: float = 0.2
        self._last_target_state: LightingState = LightingState()

    @property
    def last_raw_rgb(self) -> Tuple[int, int, int]:
        return self._last_raw_rgb

    @property
    def last_raw_luminance(self) -> float:
        return self._last_raw_luminance

    @property
    def last_target_state(self) -> LightingState:
        return self._last_target_state

    def update_settings(self, settings: ScreenAnalyzerSettings) -> None:
        """Update analyzer parameters dynamically."""
        settings.validate()
        self.settings = settings
        self._smoother.set_preset(settings.smoothing_preset)
        self._fallback_mgr.min_brightness = settings.min_brightness

    def reset(self) -> None:
        """Reset internal filter and temporal history."""
        self._smoother.reset(
            rgb=(255, 214, 170),
            brightness=float(self.settings.min_brightness),
        )
        self._last_raw_rgb = (255, 214, 170)
        self._last_raw_luminance = 0.2
        self._last_target_state = LightingState()

    def process_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> LightingState:
        """Process captured frame into target LightingState."""
        now = timestamp if timestamp is not None else time.perf_counter()

        if frame is None or frame.size == 0:
            # Stale or unavailable frame: fallback gracefully
            fb_rgb, fb_b, _ = self._fallback_mgr.get_state_or_fallback(now)
            smoothed_rgb, smoothed_b = self._smoother.update(fb_rgb, fb_b, now)
            self._last_target_state = LightingState(
                r=smoothed_rgb[0],
                g=smoothed_rgb[1],
                b=smoothed_rgb[2],
                brightness=smoothed_b,
                is_on=True,
            )
            return self._last_target_state

        # Step 1: Black-bar removal (if enabled)
        active_frame = frame
        if self.settings.detect_black_bars:
            borders = detect_black_bars(frame)
            if any(borders):
                active_frame = crop_frame_borders(frame, borders)

        # Step 2: Color extraction strategy
        strategy = self.settings.color_strategy
        if strategy == "dominant":
            raw_rgb, lum = extract_dominant_color(active_frame, exclude_subtitles=True)
        elif strategy == "edge":
            raw_rgb, lum = extract_edge_color(
                active_frame,
                edge=self.settings.edge_region,
                thickness_ratio=self.settings.edge_thickness,
                method="average",
            )
        else:
            raw_rgb, lum = extract_average_color(active_frame, saturation_boost=True)

        self._last_raw_rgb = raw_rgb
        self._last_raw_luminance = lum

        # Step 3: Brightness scaling based on scene luminance
        target_brightness = scale_scene_brightness(
            lum,
            min_brightness=self.settings.min_brightness,
            max_brightness=self.settings.max_brightness,
            gamma=self.settings.gamma,
        )

        # Step 4: Record healthy frame in fallback manager
        self._fallback_mgr.record_frame(raw_rgb, target_brightness, now)

        # Step 5: Temporal smoothing (circular hue + attack/release brightness)
        smoothed_rgb, smoothed_b = self._smoother.update(raw_rgb, target_brightness, now)

        self._last_target_state = LightingState(
            r=smoothed_rgb[0],
            g=smoothed_rgb[1],
            b=smoothed_rgb[2],
            brightness=smoothed_b,
            is_on=True,
        )
        return self._last_target_state
