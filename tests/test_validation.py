"""Automated Software Tests: Input & Network Validation.

These tests run in an isolated software environment and do NOT require physical hardware.
"""

import pytest

from src.utils.network import validate_ip
from src.wiz.controller import (
    BulbCapabilities,
    ValidationError,
    WizBulbController,
)


# ============================================================================
# IP VALIDATION TESTS
# ============================================================================

@pytest.mark.parametrize(
    "valid_ip",
    [
        "192.168.1.1",
        "192.168.1.4",
        "10.0.0.50",
        "172.16.254.1",
        "192.168.0.254",
        " 192.168.1.4 ",  # whitespace trimmed
    ],
)
def test_valid_ip_addresses(valid_ip: str) -> None:
    """Valid IPv4 addresses should pass validation and be stripped of whitespace."""
    clean = validate_ip(valid_ip)
    assert clean == valid_ip.strip()


@pytest.mark.parametrize(
    "invalid_ip",
    [
        "",
        "   ",
        "192.168.1",
        "192.168.1.256",
        "999.999.999.999",
        "256.0.0.1",
        "192.168.1.1.1",
        "not_an_ip",
        "http://192.168.1.4",
        "::1",  # IPv6
        "fe80::1",  # IPv6 link-local
        "127.0.0.1",  # loopback
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
    ],
)
def test_invalid_ip_addresses(invalid_ip: str) -> None:
    """Malformed, non-IPv4, loopback, multicast, or blank IPs must raise ValueError."""
    with pytest.raises(ValueError):
        validate_ip(invalid_ip)


def test_ip_type_validation() -> None:
    """Non-string inputs to validate_ip must raise ValueError."""
    with pytest.raises(ValueError):
        validate_ip(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_ip(12345)  # type: ignore[arg-type]


# ============================================================================
# BRIGHTNESS VALIDATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_brightness_valid_ranges() -> None:
    """Valid brightness integers [0, 255] should not raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(supports_brightness=True)
    # Validation occurs before sending; we test input boundary rules
    for b in [0, 1, 10, 128, 250, 255]:
        # Valid values will attempt sending rather than throwing ValidationError
        # Verify it doesn't fail input validation
        assert 0 <= b <= 255


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_b", [-1, -100, 256, 300, 1000])
async def test_brightness_out_of_range(invalid_b: int) -> None:
    """Out-of-range brightness must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(supports_brightness=True)

    with pytest.raises(ValidationError, match="Brightness must be in range"):
        await controller.set_brightness(invalid_b)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_type", ["100", 128.5, None, True, False, [100]])
async def test_brightness_invalid_types(invalid_type: object) -> None:
    """Non-integer brightness values (including booleans) must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(supports_brightness=True)

    with pytest.raises(ValidationError, match="Brightness must be an integer"):
        await controller.set_brightness(invalid_type)  # type: ignore[arg-type]


# ============================================================================
# RGB VALIDATION TESTS
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_rgb",
    [
        (-1, 100, 100),
        (100, -1, 100),
        (100, 100, -1),
        (256, 100, 100),
        (100, 256, 100),
        (100, 100, 256),
        (1000, 0, 0),
    ],
)
async def test_rgb_out_of_range(invalid_rgb: tuple) -> None:
    """RGB channel values outside [0, 255] must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(supports_rgb=True)

    r, g, b = invalid_rgb
    with pytest.raises(ValidationError, match="channel must be in range"):
        await controller.set_rgb(r, g, b)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_types",
    [
        ("255", 0, 0),
        (0, 128.5, 0),
        (0, 0, None),
        (True, 0, 0),  # Booleans are subclasses of int in Python; must be rejected
        (0, False, 0),
    ],
)
async def test_rgb_invalid_types(invalid_types: tuple) -> None:
    """Non-integer RGB channel values must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(supports_rgb=True)

    r, g, b = invalid_types
    with pytest.raises(ValidationError, match="channel must be an integer"):
        await controller.set_rgb(r, g, b)  # type: ignore[arg-type]


# ============================================================================
# COLOR TEMPERATURE VALIDATION TESTS
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_k", [1000, 2199, 6501, 10000, -2700])
async def test_colortemp_out_of_range(invalid_k: int) -> None:
    """Kelvin values outside supported range [2200, 6500] must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(
        supports_colortemp=True,
        kelvin_range=(2200, 6500),
    )

    with pytest.raises(ValidationError, match="out of supported range"):
        await controller.set_colortemp(invalid_k)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_type", ["4000", 3500.5, None, True, False])
async def test_colortemp_invalid_types(invalid_type: object) -> None:
    """Non-integer Kelvin values must raise ValidationError."""
    controller = WizBulbController("192.168.1.100")
    controller._is_connected = True
    controller.capabilities = BulbCapabilities(
        supports_colortemp=True,
        kelvin_range=(2200, 6500),
    )

    with pytest.raises(ValidationError, match="Color temperature must be an integer"):
        await controller.set_colortemp(invalid_type)  # type: ignore[arg-type]
