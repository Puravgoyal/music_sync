"""Settings persistence and user preferences management."""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AppPreferences:
    """User configuration preferences persisted to local disk."""

    last_bulb_ip: Optional[str] = None
    last_bulb_mac: Optional[str] = None
    last_audio_device_name: Optional[str] = None
    preferred_effect: str = "spectrum"
    sensitivity: float = 1.0
    min_brightness: int = 25
    max_brightness: int = 255
    color_smoothing: float = 0.30
    attack_speed: float = 0.45
    release_speed: float = 0.10
    beat_strength: float = 1.0
    update_rate_hz: float = 4.0
    restore_on_stop: bool = True
    dry_run: bool = False
    window_geometry: Optional[str] = None
    audio_focus: str = "full"
    adaptive_rate: bool = False
    safe_max_rate_hz: float = 8.0
    sync_mode: str = "music"
    screen_monitor_index: int = 0
    color_strategy: str = "average"
    edge_region: str = "all"
    edge_thickness: float = 0.15
    smoothing_preset: str = "cinematic"
    detect_black_bars: bool = True
    hybrid_type: str = "cinematic"
    audio_contribution: float = 0.35
    hybrid_audio_focus: str = "full"
    hybrid_beat_intensity: float = 1.0

    def validate(self) -> None:
        """Validate and clamp settings to safe limits."""
        self.sensitivity = max(0.1, min(3.0, float(self.sensitivity)))
        self.min_brightness = max(0, min(255, int(self.min_brightness)))
        self.max_brightness = max(0, min(255, int(self.max_brightness)))
        if self.min_brightness > self.max_brightness:
            self.min_brightness = self.max_brightness
        self.color_smoothing = max(0.0, min(0.95, float(self.color_smoothing)))
        self.attack_speed = max(0.01, min(1.0, float(self.attack_speed)))
        self.release_speed = max(0.01, min(1.0, float(self.release_speed)))
        self.beat_strength = max(0.0, min(2.0, float(self.beat_strength)))
        self.update_rate_hz = max(1.0, min(10.0, float(self.update_rate_hz)))
        if self.preferred_effect not in ("spectrum", "beat", "bass", "smooth", "ambient"):
            self.preferred_effect = "spectrum"
        if self.audio_focus not in ("full", "rhythm", "kick"):
            self.audio_focus = "full"
        self.safe_max_rate_hz = max(4.0, min(10.0, float(self.safe_max_rate_hz)))
        if self.sync_mode not in ("music", "screen", "hybrid"):
            self.sync_mode = "music"
        self.screen_monitor_index = max(0, int(self.screen_monitor_index))
        if self.color_strategy not in ("average", "dominant", "edge"):
            self.color_strategy = "average"
        if self.edge_region not in ("all", "left", "right", "top", "bottom"):
            self.edge_region = "all"
        self.edge_thickness = max(0.02, min(0.45, float(self.edge_thickness)))
        if self.smoothing_preset not in ("cinematic", "balanced", "responsive"):
            self.smoothing_preset = "cinematic"
        self.detect_black_bars = bool(self.detect_black_bars)
        if self.hybrid_type not in ("cinematic", "rhythm", "kick"):
            self.hybrid_type = "cinematic"
        self.audio_contribution = max(0.0, min(1.0, float(self.audio_contribution)))
        if self.hybrid_audio_focus not in ("full", "rhythm", "kick"):
            self.hybrid_audio_focus = "full"
        self.hybrid_beat_intensity = max(0.0, min(2.0, float(self.hybrid_beat_intensity)))


def get_preferences_path() -> Path:
    """Determine OS-appropriate configuration file path in user AppData directory."""
    appdata = os.getenv("APPDATA")
    if appdata:
        base_dir = Path(appdata) / "WiZMusicSync"
    else:
        base_dir = Path.home() / ".config" / "wiz_music_sync"

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "preferences.json"


class PreferencesManager:
    """Loads, saves, and migrates local application preferences."""

    def __init__(self, filepath: Optional[Path] = None) -> None:
        self.filepath = filepath or get_preferences_path()
        self.preferences = self.load()

    def load(self) -> AppPreferences:
        """Load settings from JSON file with fallback to validated defaults."""
        if not self.filepath.exists():
            logger.info("Preferences file does not exist. Using defaults.")
            prefs = AppPreferences()
            return prefs

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Preferences root must be a JSON object")

            # Filter valid fields to permit forwards/backwards compatibility
            valid_keys = AppPreferences.__dataclass_fields__.keys()
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            prefs = AppPreferences(**filtered)
            prefs.validate()
            logger.info("Loaded preferences from %s", self.filepath)
            return prefs
        except Exception as exc:
            logger.warning("Error reading preferences (%s). Falling back to safe defaults.", exc)
            fallback = AppPreferences()
            return fallback

    def save(self, preferences: Optional[AppPreferences] = None) -> bool:
        """Atomically persist preferences to JSON file."""
        if preferences is not None:
            self.preferences = preferences

        self.preferences.validate()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.filepath.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self.preferences), f, indent=2)
            temp_file.replace(self.filepath)
            logger.debug("Saved preferences to %s", self.filepath)
            return True
        except Exception as exc:
            logger.error("Failed to save preferences to %s: %s", self.filepath, exc)
            return False
