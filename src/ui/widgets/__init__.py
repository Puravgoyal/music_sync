"""UI widget components for WiZ Music Sync."""

from src.ui.widgets.audio_panel import AudioPanel
from src.ui.widgets.device_panel import DevicePanel
from src.ui.widgets.effects_panel import EffectsPanel
from src.ui.widgets.hybrid_panel import HybridPanel
from src.ui.widgets.screen_panel import ScreenPanel
from src.ui.widgets.spectrum_view import SpectrumView
from src.ui.widgets.status_panel import StatusPanel

__all__ = [
    "DevicePanel",
    "AudioPanel",
    "EffectsPanel",
    "ScreenPanel",
    "HybridPanel",
    "SpectrumView",
    "StatusPanel",
]
