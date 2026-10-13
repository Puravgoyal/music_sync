"""Automated Software Tests: Windows Audio Output Device Enumeration.

These tests verify device discovery, filtering, default device resolution,
and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.audio.devices import (
    AudioDevice,
    get_audio_output_devices,
    get_default_output_device,
    get_device_by_index,
)


def test_audio_device_properties() -> None:
    """AudioDevice dataclass should format clean names and string representations."""
    dev = AudioDevice(
        index=3,
        name="Speakers (Realtek(R) Audio) [Loopback]",
        sample_rate=48000,
        channels=2,
        is_loopback=True,
        is_default=True,
    )
    assert dev.clean_name() == "Speakers (Realtek(R) Audio)"
    assert "Default" in str(dev)
    assert "48000Hz" in str(dev)
    assert "2ch" in str(dev)


def test_get_audio_output_devices_real_or_mock() -> None:
    """Should enumerate loopback devices on Windows."""
    devices = get_audio_output_devices()
    # On a Windows machine with sound card, at least 1 device is found
    assert isinstance(devices, list)
    if devices:
        assert all(isinstance(d, AudioDevice) for d in devices)
        assert all(d.is_loopback for d in devices)


def test_get_default_output_device() -> None:
    """Default output device should be resolved if devices exist."""
    devices = get_audio_output_devices()
    default_dev = get_default_output_device()
    if devices:
        assert default_dev is not None
        assert isinstance(default_dev, AudioDevice)
        assert default_dev.index in [d.index for d in devices]


def test_get_device_by_index_invalid() -> None:
    """Non-existent device index must return None."""
    assert get_device_by_index(-9999) is None


def test_enumeration_mocked_devices() -> None:
    """Device enumeration with mocked PyAudio instance."""
    mock_pyaudio_cls = MagicMock()
    mock_pa = MagicMock()
    mock_pyaudio_cls.PyAudio.return_value = mock_pa

    mock_pa.get_default_wasapi_loopback.return_value = {
        "index": 10,
        "name": "Headphones [Loopback]",
        "defaultSampleRate": 44100.0,
        "maxInputChannels": 2,
    }
    mock_pa.get_loopback_device_info_generator.return_value = [
        {
            "index": 10,
            "name": "Headphones [Loopback]",
            "defaultSampleRate": 44100.0,
            "maxInputChannels": 2,
            "isLoopbackDevice": True,
        },
        {
            "index": 12,
            "name": "Speakers [Loopback]",
            "defaultSampleRate": 48000.0,
            "maxInputChannels": 2,
            "isLoopbackDevice": True,
        },
    ]

    with patch("src.audio.devices.pyaudio", mock_pyaudio_cls), patch(
        "src.audio.devices.PYAUDIO_AVAILABLE", True
    ):
        devices = get_audio_output_devices()
        assert len(devices) == 2
        # Default device should be sorted first
        assert devices[0].index == 10
        assert devices[0].is_default is True
        assert devices[0].sample_rate == 44100
        assert devices[1].index == 12
        assert devices[1].is_default is False


def test_enumeration_when_pyaudio_unavailable() -> None:
    """Should return empty list gracefully when PyAudioWPatch is missing."""
    with patch("src.audio.devices.PYAUDIO_AVAILABLE", False):
        devices = get_audio_output_devices()
        assert devices == []
        assert get_default_output_device() is None
