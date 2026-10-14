"""Display and monitor enumeration with multi-monitor and DPI scaling support."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScreenMonitor:
    """Represents a physical or virtual display monitor."""

    index: int
    name: str
    x: int
    y: int
    width: int
    height: int
    device_pixel_ratio: float = 1.0
    is_primary: bool = False
    physical_width: Optional[int] = None
    physical_height: Optional[int] = None

    @property
    def display_name(self) -> str:
        """Formatted user-friendly monitor name."""
        primary_tag = " (Primary)" if self.is_primary else ""
        scale_tag = f" @ {int(self.device_pixel_ratio * 100)}%" if self.device_pixel_ratio != 1.0 else ""
        res_tag = f"{self.width}x{self.height}"
        return f"Display {self.index}: {self.name} [{res_tag}{scale_tag}]{primary_tag}"


def _get_monitors_via_qt() -> List[ScreenMonitor]:
    """Enumerate monitors using PySide6 QGuiApplication screens."""
    try:
        from PySide6.QtGui import QGuiApplication

        screens = QGuiApplication.screens()
        if not screens:
            return []

        primary_screen = QGuiApplication.primaryScreen()
        monitors: List[ScreenMonitor] = []

        for idx, screen in enumerate(screens):
            geo = screen.geometry()
            dpr = float(screen.devicePixelRatio())
            is_pri = (screen == primary_screen) or (idx == 0 and primary_screen is None)
            
            # Physical pixel dimensions
            size = screen.size()
            phys_w = int(size.width() * dpr)
            phys_h = int(size.height() * dpr)

            monitors.append(
                ScreenMonitor(
                    index=idx,
                    name=screen.name() or f"Display {idx}",
                    x=int(geo.x()),
                    y=int(geo.y()),
                    width=int(geo.width()),
                    height=int(geo.height()),
                    device_pixel_ratio=dpr,
                    is_primary=is_pri,
                    physical_width=phys_w,
                    physical_height=phys_h,
                )
            )
        return monitors
    except Exception as exc:
        logger.debug("Qt screen enumeration failed or not in GUI context: %s", exc)
        return []


def _get_monitors_via_win32() -> List[ScreenMonitor]:
    """Enumerate monitors using Windows Win32 API as pure ctypes fallback."""
    monitors: List[ScreenMonitor] = []
    try:
        user32 = ctypes.windll.user32

        # Make process DPI aware if possible
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32),
            ]

        MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )

        def _enum_proc(hmonitor, hdc, lprect, lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                r = info.rcMonitor
                w = int(r.right - r.left)
                h = int(r.bottom - r.top)
                is_pri = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY
                dev_name = info.szDevice or f"DISPLAY{len(monitors) + 1}"
                monitors.append(
                    ScreenMonitor(
                        index=len(monitors),
                        name=dev_name,
                        x=int(r.left),
                        y=int(r.top),
                        width=w,
                        height=h,
                        device_pixel_ratio=1.0,
                        is_primary=is_pri,
                        physical_width=w,
                        physical_height=h,
                    )
                )
            return True

        user32.EnumDisplayMonitors(0, None, MONITOR_ENUM_PROC(_enum_proc), 0)
    except Exception as exc:
        logger.debug("Win32 monitor enumeration failed: %s", exc)

    if not monitors:
        # Fallback default monitor
        monitors.append(
            ScreenMonitor(
                index=0,
                name="Primary Display",
                x=0,
                y=0,
                width=1920,
                height=1080,
                device_pixel_ratio=1.0,
                is_primary=True,
                physical_width=1920,
                physical_height=1080,
            )
        )
    return monitors


def get_available_monitors() -> List[ScreenMonitor]:
    """Retrieve all active display monitors, preferring Qt screens when available."""
    mons = _get_monitors_via_qt()
    if mons:
        return mons
    return _get_monitors_via_win32()


def get_monitor_by_index(index: int) -> ScreenMonitor:
    """Retrieve monitor by index, falling back to primary/first if index is out of bounds."""
    monitors = get_available_monitors()
    for m in monitors:
        if m.index == index:
            return m
    # Return primary if found
    for m in monitors:
        if m.is_primary:
            return m
    return monitors[0] if monitors else ScreenMonitor(0, "Default Display", 0, 0, 1920, 1080, is_primary=True)
