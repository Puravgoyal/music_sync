"""Data structures representing lighting states and synchronization telemetry."""

import time
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class LightingState:
    """Represents an instantaneous target or applied bulb lighting state."""

    rgb: Tuple[int, int, int] = (255, 255, 255)
    brightness: int = 128  # 0 to 255
    is_on: bool = True
    timestamp: float = 0.0

    def __init__(
        self,
        rgb: Optional[Tuple[int, int, int]] = None,
        brightness: int = 128,
        is_on: bool = True,
        timestamp: float = 0.0,
        r: Optional[int] = None,
        g: Optional[int] = None,
        b: Optional[int] = None,
    ) -> None:
        if r is not None and g is not None and b is not None:
            self.rgb = (r, g, b)
        elif rgb is not None:
            self.rgb = rgb
        else:
            self.rgb = (255, 255, 255)
        self.brightness = brightness
        self.is_on = is_on
        self.timestamp = timestamp if timestamp != 0.0 else time.perf_counter()
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.perf_counter()
        # Clamp RGB and brightness to safe bounds
        r = max(0, min(255, int(self.rgb[0])))
        g = max(0, min(255, int(self.rgb[1])))
        b = max(0, min(255, int(self.rgb[2])))
        self.rgb = (r, g, b)
        self.brightness = max(0, min(255, int(self.brightness)))

    @property
    def r(self) -> int:
        return self.rgb[0]

    @property
    def g(self) -> int:
        return self.rgb[1]

    @property
    def b(self) -> int:
        return self.rgb[2]

    def is_similar_to(
        self,
        other: Optional["LightingState"],
        rgb_threshold: int = 4,
        brightness_threshold: int = 4,
    ) -> bool:
        """Deadband filter to detect if change between two states is perceptually negligible."""
        if other is None:
            return False
        if self.is_on != other.is_on:
            return False
        if abs(self.brightness - other.brightness) > brightness_threshold:
            return False
        if (
            abs(self.rgb[0] - other.rgb[0]) > rgb_threshold
            or abs(self.rgb[1] - other.rgb[1]) > rgb_threshold
            or abs(self.rgb[2] - other.rgb[2]) > rgb_threshold
        ):
            return False
        return True

    def __str__(self) -> str:
        state_str = "ON" if self.is_on else "OFF"
        return f"RGB{self.rgb} @ {self.brightness}/255 ({state_str})"


@dataclass
class SyncStatus:
    """Telemetry report of live music synchronization."""

    is_running: bool
    current_effect: str
    bulb_ip: Optional[str]
    audio_device: Optional[str]
    target_state: LightingState
    applied_state: Optional[LightingState]
    updates_per_second: float  # Actual measured bulb update rate
    commands_sent: int
    commands_failed: int
    last_command_duration_ms: float
    is_dry_run: bool = False
    pending_states_count: int = 0
    audio_focus: str = "full"
    adaptive_rate: bool = False
    p95_duration_ms: float = 0.0
    sync_mode: str = "music"
    screen_fps: float = 0.0
    screen_color: Optional[Tuple[int, int, int]] = None
    screen_monitor: Optional[str] = None
    capture_health: str = "OK"


from enum import Enum


class RestorationResult(Enum):
    """Explicit result category for bulb state restoration on stop."""

    SUCCESS = "Successfully restored"
    SKIPPED = "Restoration skipped by user preference"
    UNAVAILABLE = "Restoration unavailable due to missing initial state"
    FAILED = "Restoration failed"


@dataclass
class RestorationReport:
    """Explicit report of bulb state restoration result and details."""

    result: RestorationResult
    details: str = ""

    def __str__(self) -> str:
        if self.details:
            return f"{self.result.value} ({self.details})"
        return self.result.value
