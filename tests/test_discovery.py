"""Automated Software Tests: WiZ Discovery Logic.

These tests mock network datagrams and query operations to verify discovery
behavior, filtering of self-echoed packets, and graceful handling of missing fields.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.network import get_subnet_broadcast_addresses, validate_ip
from src.wiz.discovery import (
    DiscoveredDevice,
    _DiscoveryProtocol,
    fetch_device_details,
)


def test_discovery_protocol_valid_datagram() -> None:
    """Protocol should register device when valid response with MAC arrives."""
    proto = _DiscoveryProtocol()
    data = b'{"method":"registration","env":"pro","result":{"mac":"cc4085d19ea0","success":true}}'
    proto.datagram_received(data, ("192.168.1.100", 38899))

    assert "192.168.1.100" in proto.discovered
    assert proto.discovered["192.168.1.100"] == "cc4085d19ea0"


def test_discovery_protocol_ignores_self_echo() -> None:
    """Protocol should ignore broadcast probe echo (which lacks 'result')."""
    proto = _DiscoveryProtocol()
    # Outgoing probe payload echoed back to the local host
    probe_echo = (
        b'{"method":"registration","params":'
        b'{"phoneMac":"AAAAAAAAAAAA","register":false,"phoneIp":"1.2.3.4","id":"1"}}'
    )
    proto.datagram_received(probe_echo, ("192.168.1.7", 38899))
    assert "192.168.1.7" not in proto.discovered


def test_discovery_protocol_ignores_malformed_packets() -> None:
    """Protocol should gracefully ignore corrupted or non-JSON UDP packets."""
    proto = _DiscoveryProtocol()
    proto.datagram_received(b"Not valid json payload", ("192.168.1.200", 38899))
    proto.datagram_received(b'{"no_result_key": 123}', ("192.168.1.201", 38899))
    assert len(proto.discovered) == 0


@pytest.mark.asyncio
async def test_fetch_device_details_complete() -> None:
    """fetch_device_details should assemble model, firmware, power, and color data."""
    mock_wiz = MagicMock()
    mock_bulbtype = MagicMock()
    mock_bulbtype.name = "ESP25_SHRGB_01"
    mock_bulbtype.fw_version = "1.38.0"
    mock_bulbtype.bulb_type = MagicMock(value="RGB Tunable")
    mock_bulbtype.kelvin_range = MagicMock(min=2200, max=6500)
    mock_bulbtype.features = MagicMock(color=True, color_tmp=True, effect=True, brightness=True)
    mock_wiz.get_bulbtype = AsyncMock(return_value=mock_bulbtype)
    mock_wiz.getMac = AsyncMock(return_value="cc4085d19ea0")

    mock_parser = MagicMock()
    mock_parser.get_brightness.return_value = 255
    mock_parser.get_rgb.return_value = (255, 0, 0)
    mock_parser.get_colortemp.return_value = None
    mock_wiz.updateState = AsyncMock(return_value=[mock_parser])
    mock_wiz.status = True
    mock_wiz.async_close = AsyncMock()

    with patch("src.wiz.discovery.wizlight", return_value=mock_wiz):
        device = await fetch_device_details("192.168.1.100", timeout=2.0)
        assert device.ip == "192.168.1.100"
        assert device.mac == "cc4085d19ea0"
        assert device.model == "ESP25_SHRGB_01"
        assert device.fw_version == "1.38.0"
        assert device.is_on is True
        assert device.brightness == 255
        assert device.rgb == (255, 0, 0)
        assert device.kelvin_range == (2200, 6500)
        assert "color" in device.features


@pytest.mark.asyncio
async def test_fetch_device_details_graceful_on_timeout() -> None:
    """fetch_device_details should return partial info without crashing if queries fail."""
    mock_wiz = MagicMock()
    mock_wiz.get_bulbtype = AsyncMock(side_effect=TimeoutError("Bulb did not reply"))
    mock_wiz.getMac = AsyncMock(side_effect=TimeoutError("Bulb did not reply"))
    mock_wiz.updateState = AsyncMock(side_effect=TimeoutError("Bulb did not reply"))
    mock_wiz.async_close = AsyncMock()

    with patch("src.wiz.discovery.wizlight", return_value=mock_wiz):
        device = await fetch_device_details("192.168.1.100", mac="aabbccddeeff", timeout=1.0)
        assert device.ip == "192.168.1.100"
        assert device.mac == "aabbccddeeff"
        assert device.model is None
        assert device.is_on is None


def test_broadcast_addresses_format() -> None:
    """get_subnet_broadcast_addresses should return valid IPv4 broadcast strings."""
    broadcasts = get_subnet_broadcast_addresses()
    assert len(broadcasts) >= 1
    assert "255.255.255.255" in broadcasts
    for addr in broadcasts:
        validated = validate_ip(addr)
        assert validated == addr


def test_discovered_device_summary() -> None:
    """DiscoveredDevice.summary() should produce clean formatted output without error."""
    dev = DiscoveredDevice(
        ip="192.168.1.4",
        mac="cc4085d19ea0",
        model="ESP25_SHRGB_01",
        fw_version="1.38.0",
        bulb_type="RGB Tunable",
        is_on=True,
        brightness=255,
        rgb=(255, 128, 0),
        colortemp=2700,
        kelvin_range=(2200, 6500),
        features={"color": True, "brightness": True},
    )
    summary = dev.summary()
    assert "192.168.1.4" in summary
    assert "cc4085d19ea0" in summary
    assert "ESP25_SHRGB_01" in summary
    assert "ON" in summary
    assert "255/255" in summary
    assert "2700 K" in summary
