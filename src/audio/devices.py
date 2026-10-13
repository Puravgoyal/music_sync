"""Windows WASAPI audio output loopback device enumeration."""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("wiz_music_sync.audio.devices")

try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None  # type: ignore[assignment]
    PYAUDIO_AVAILABLE = False


@dataclass
class AudioDevice:
    """Represents a Windows audio output loopback device."""

    index: int
    name: str
    sample_rate: int
    channels: int
    is_loopback: bool = True
    is_default: bool = False

    def clean_name(self) -> str:
        """Return a cleaner device name without the [Loopback] tag."""
        return self.name.replace(" [Loopback]", "").strip()

    def __str__(self) -> str:
        default_tag = " (Default)" if self.is_default else ""
        return (
            f"[{self.index}] {self.clean_name()}{default_tag} - "
            f"{self.channels}ch @ {self.sample_rate}Hz"
        )


def get_audio_output_devices() -> List[AudioDevice]:
    """Enumerate all available Windows audio output loopback devices.

    Returns:
        List of AudioDevice instances. Empty if WASAPI or devices are unavailable.
    """
    if not PYAUDIO_AVAILABLE:
        logger.error("PyAudioWPatch is not installed. Loopback capture is unavailable.")
        return []

    p = pyaudio.PyAudio()
    devices: List[AudioDevice] = []

    try:
        try:
            default_loopback = p.get_default_wasapi_loopback()
            default_index = default_loopback["index"] if default_loopback else None
        except (OSError, ValueError) as exc:
            logger.debug("Could not resolve default WASAPI loopback device: %s", exc)
            default_index = None

        for dev in p.get_loopback_device_info_generator():
            idx = int(dev["index"])
            device = AudioDevice(
                index=idx,
                name=str(dev["name"]),
                sample_rate=int(dev["defaultSampleRate"]),
                channels=int(dev["maxInputChannels"]),
                is_loopback=bool(dev.get("isLoopbackDevice", True)),
                is_default=(idx == default_index),
            )
            devices.append(device)

    except Exception as exc:
        logger.error("Error enumerating audio loopback devices: %s", exc)
    finally:
        p.terminate()

    # Sort so default device is first, then by index
    devices.sort(key=lambda d: (not d.is_default, d.index))
    return devices


def get_default_output_device() -> Optional[AudioDevice]:
    """Retrieve the current active Windows output loopback device.

    Returns:
        AudioDevice for the default output device, or None if unavailable.
    """
    devices = get_audio_output_devices()
    for dev in devices:
        if dev.is_default:
            return dev
    return devices[0] if devices else None


def get_device_by_index(index: int) -> Optional[AudioDevice]:
    """Retrieve an AudioDevice by its PyAudio device index.

    Args:
        index: Device index to search for.

    Returns:
        Matching AudioDevice or None if not found.
    """
    devices = get_audio_output_devices()
    for dev in devices:
        if dev.index == index:
            return dev
    return None
