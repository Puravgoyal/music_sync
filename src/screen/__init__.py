"""Screen capture, color extraction, and ambience synchronization module."""

from src.screen.analyzer import ScreenAnalyzerSettings, ScreenColorAnalyzer
from src.screen.capture import (
    BaseCaptureBackend,
    CaptureStats,
    DXCamCaptureBackend,
    MockCaptureBackend,
    QtCaptureBackend,
    ScreenCaptureManager,
)
from src.screen.cinematic import (
    CaptureFallbackManager,
    CaptureHealth,
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
from src.screen.devices import ScreenMonitor, get_available_monitors, get_monitor_by_index
from src.screen.smoothing import (
    PRESET_CONFIGS,
    SmoothingParams,
    SmoothingPresetType,
    TemporalColorSmoother,
    get_smoothing_params,
)

__all__ = [
    "ScreenMonitor",
    "get_available_monitors",
    "get_monitor_by_index",
    "srgb_to_linear",
    "linear_to_srgb",
    "extract_average_color",
    "extract_dominant_color",
    "extract_edge_color",
    "detect_black_bars",
    "crop_frame_borders",
    "scale_scene_brightness",
    "CaptureFallbackManager",
    "CaptureHealth",
    "SmoothingPresetType",
    "SmoothingParams",
    "PRESET_CONFIGS",
    "get_smoothing_params",
    "TemporalColorSmoother",
    "BaseCaptureBackend",
    "QtCaptureBackend",
    "DXCamCaptureBackend",
    "MockCaptureBackend",
    "CaptureStats",
    "ScreenCaptureManager",
    "ScreenAnalyzerSettings",
    "ScreenColorAnalyzer",
]
