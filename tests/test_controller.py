"""Automated Software Tests: WiZ Bulb Controller Logic & Error Handling.

These tests mock underlying network communication to thoroughly verify
controller behavior, state parsing, capability enforcement, and error recovery.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pywizlight.exceptions import (
    WizLightConnectionError,
    WizLightMethodNotFound,
    WizLightTimeOutError,
)

from src.wiz.controller import (
    BulbCapabilities,
    UnsupportedFeatureError,
    WizBulbController,
    WizConnectionError,
    WizTimeoutError,
)


@pytest.fixture
def mock_wizlight():
    """Create a mock pywizlight wizlight instance with realistic bulb profile."""
    mock = MagicMock()
    mock_bulbtype = MagicMock()
    mock_bulbtype.name = "ESP25_SHRGB_01"
    mock_bulbtype.fw_version = "1.38.0"
    mock_bulbtype.bulb_type = MagicMock(value="RGB Tunable")
    mock_bulbtype.kelvin_range = MagicMock(min=2200, max=6500)
    mock_bulbtype.features = MagicMock(color=True, color_tmp=True, brightness=True, effect=True)
    mock.get_bulbtype = AsyncMock(return_value=mock_bulbtype)
    mock.getMac = AsyncMock(return_value="aabbccddeeff")
    mock.updateState = AsyncMock(return_value=[])
    mock.turn_on = AsyncMock()
    mock.turn_off = AsyncMock()
    mock.async_close = AsyncMock()
    mock.status = True
    return mock


@pytest.mark.asyncio
async def test_connect_success(mock_wizlight) -> None:
    """Controller should successfully connect, extract capabilities, and set is_connected."""
    mock_bulbtype = MagicMock()
    mock_bulbtype.name = "ESP25_SHRGB_01"
    mock_bulbtype.fw_version = "1.38.0"
    mock_bulbtype.bulb_type = MagicMock(value="RGB Tunable")
    mock_bulbtype.kelvin_range = MagicMock(min=2200, max=6500)
    mock_bulbtype.features = MagicMock(color=True, color_tmp=True, brightness=True, effect=True)
    mock_wizlight.get_bulbtype.return_value = mock_bulbtype

    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        assert not controller.is_connected
        await controller.connect()
        assert controller.is_connected
        assert controller.mac == "aabbccddeeff"
        assert controller.capabilities is not None
        assert controller.capabilities.supports_rgb is True
        assert controller.capabilities.supports_colortemp is True
        assert controller.capabilities.kelvin_range == (2200, 6500)
        await controller.close()


@pytest.mark.asyncio
async def test_turn_on_and_off(mock_wizlight) -> None:
    """Controller should call underlying turn_on and turn_off methods."""
    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        await controller.turn_on()
        mock_wizlight.turn_on.assert_called_once()

        await controller.turn_off()
        mock_wizlight.turn_off.assert_called_once()
        await controller.close()


@pytest.mark.asyncio
async def test_set_brightness(mock_wizlight) -> None:
    """Setting brightness should call turn_on with PilotBuilder dimming."""
    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        await controller.set_brightness(128)
        assert mock_wizlight.turn_on.call_count == 1

        # Brightness 0 should trigger turn_off
        await controller.set_brightness(0)
        mock_wizlight.turn_off.assert_called_once()
        await controller.close()


@pytest.mark.asyncio
async def test_set_rgb(mock_wizlight) -> None:
    """Setting RGB should pass valid color channels to the bulb."""
    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        await controller.set_rgb(255, 0, 128)
        assert mock_wizlight.turn_on.call_count == 1
        await controller.close()


@pytest.mark.asyncio
async def test_set_colortemp(mock_wizlight) -> None:
    """Setting color temperature within supported range should pass to bulb."""
    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        await controller.set_colortemp(3000)
        assert mock_wizlight.turn_on.call_count == 1
        await controller.close()


@pytest.mark.asyncio
async def test_unsupported_rgb_handling() -> None:
    """Bulb hardware without RGB support must raise UnsupportedFeatureError."""
    controller = WizBulbController("192.168.1.50")
    controller._is_connected = True
    controller._light = MagicMock()
    controller.capabilities = BulbCapabilities(supports_rgb=False)

    with pytest.raises(UnsupportedFeatureError, match="does not support RGB color"):
        await controller.set_rgb(255, 0, 0)


@pytest.mark.asyncio
async def test_unsupported_colortemp_handling() -> None:
    """Bulb hardware without color temperature support must raise UnsupportedFeatureError."""
    controller = WizBulbController("192.168.1.50")
    controller._is_connected = True
    controller._light = MagicMock()
    controller.capabilities = BulbCapabilities(supports_colortemp=False)

    with pytest.raises(UnsupportedFeatureError, match="does not support color temperature"):
        await controller.set_colortemp(4000)


@pytest.mark.asyncio
async def test_connection_error_handling(mock_wizlight) -> None:
    """Network connection errors from pywizlight must raise WizConnectionError."""
    mock_wizlight.turn_on.side_effect = WizLightConnectionError("Socket unreachable")

    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        with pytest.raises(WizConnectionError, match="Connection error to bulb"):
            await controller.turn_on()
        await controller.close()


@pytest.mark.asyncio
async def test_timeout_error_handling(mock_wizlight) -> None:
    """Network timeouts from pywizlight must raise WizTimeoutError."""
    mock_wizlight.turn_on.side_effect = WizLightTimeOutError("No response received")

    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        controller = WizBulbController("192.168.1.50")
        await controller.connect()

        with pytest.raises(WizTimeoutError, match="Operation timed out"):
            await controller.turn_on()
        await controller.close()


@pytest.mark.asyncio
async def test_not_connected_error() -> None:
    """Calling commands on an uninitialized controller must raise WizConnectionError."""
    controller = WizBulbController("192.168.1.50")
    with pytest.raises(WizConnectionError, match="Bulb controller is not connected"):
        await controller.turn_on()


@pytest.mark.asyncio
async def test_async_context_manager(mock_wizlight) -> None:
    """Controller should support 'async with' and clean up upon exit."""
    with patch("src.wiz.controller.wizlight", return_value=mock_wizlight):
        async with WizBulbController("192.168.1.50") as controller:
            assert controller.is_connected
        assert not controller.is_connected
        mock_wizlight.async_close.assert_called_once()
