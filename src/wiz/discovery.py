"""WiZ smart bulb discovery over local network via UDP broadcast."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from pywizlight import wizlight
from pywizlight.exceptions import WizLightConnectionError, WizLightTimeOutError

from src.utils.network import get_subnet_broadcast_addresses

logger = logging.getLogger("wiz_music_sync.discovery")

WIZ_PORT = 38899

# WiZ registration probe payload
REGISTRATION_MESSAGE = (
    b'{"method":"registration","params":'
    b'{"phoneMac":"AAAAAAAAAAAA","register":false,"phoneIp":"1.2.3.4","id":"1"}}'
)


@dataclass
class DiscoveredDevice:
    """Represents a discovered WiZ device and its capabilities."""
    
    ip: str
    mac: Optional[str] = None
    model: Optional[str] = None
    fw_version: Optional[str] = None
    bulb_type: Optional[str] = None
    is_on: Optional[bool] = None
    brightness: Optional[int] = None  # 0-255 scale
    rgb: Optional[Tuple[Optional[int], Optional[int], Optional[int]]] = None
    colortemp: Optional[int] = None  # Kelvin
    kelvin_range: Optional[Tuple[int, int]] = None  # (min, max)
    features: Dict[str, bool] = field(default_factory=dict)
    
    def summary(self) -> str:
        """Format device details as a human-readable summary string."""
        lines = [
            f"  IP:                 {self.ip}",
            f"  MAC Address:        {self.mac or 'Unknown'}",
            f"  Model:              {self.model or 'Unknown'}",
            f"  Firmware:           {self.fw_version or 'Unknown'}",
            f"  Device Class:       {self.bulb_type or 'Unknown'}",
            f"  Power State:        {'ON' if self.is_on else ('OFF' if self.is_on is False else 'Unknown')}",
            f"  Brightness:         {self.brightness if self.brightness is not None else 'Unknown'}/255",
            f"  RGB:                {self.rgb if self.rgb else 'None/Unsupported'}",
            f"  Color Temp:         {f'{self.colortemp} K' if self.colortemp else 'None/Unsupported'}",
        ]
        if self.kelvin_range:
            lines.append(f"  Kelvin Range:       {self.kelvin_range[0]}K - {self.kelvin_range[1]}K")
        if self.features:
            feat_str = ", ".join(k for k, v in self.features.items() if v)
            lines.append(f"  Supported Features: {feat_str}")
        return "\n".join(lines)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Internal DatagramProtocol to listen for WiZ UDP broadcast responses."""
    
    def __init__(self) -> None:
        self.discovered: Dict[str, Optional[str]] = {}  # ip -> mac
        self.transport: Optional[asyncio.DatagramTransport] = None
        
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        
    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        ip = addr[0]
        try:
            payload = json.loads(data.decode("utf-8", errors="ignore"))
            # WiZ bulbs reply with a "result" object containing their MAC
            result = payload.get("result")
            if isinstance(result, dict) and "mac" in result:
                mac = result["mac"]
                if mac and mac.upper() != "AAAAAAAAAAAA":
                    self.discovered[ip] = mac
                    logger.debug("Discovered WiZ device response from %s (MAC: %s)", ip, mac)
        except Exception as exc:
            logger.debug("Non-WiZ or malformed packet from %s: %s", ip, exc)
            
    def error_received(self, exc: Exception) -> None:
        logger.debug("UDP Discovery error received: %s", exc)


async def fetch_device_details(
    ip: str,
    mac: Optional[str] = None,
    timeout: float = 4.0,
) -> DiscoveredDevice:
    """Connect to a WiZ bulb and extract full device information gracefully.
    
    Args:
        ip: Target IP address.
        mac: Optional pre-discovered MAC address.
        timeout: Maximum seconds to wait for bulb queries.
        
    Returns:
        DiscoveredDevice populated with whatever properties could be retrieved.
    """
    device = DiscoveredDevice(ip=ip, mac=mac)
    light = wizlight(ip, mac=mac)
    
    try:
        # Retrieve bulb type and hardware features
        try:
            bulb_type = await asyncio.wait_for(light.get_bulbtype(), timeout=timeout)
            if bulb_type:
                device.model = bulb_type.name
                device.fw_version = bulb_type.fw_version
                device.bulb_type = bulb_type.bulb_type.value if hasattr(bulb_type.bulb_type, "value") else str(bulb_type.bulb_type)
                if bulb_type.kelvin_range:
                    device.kelvin_range = (bulb_type.kelvin_range.min, bulb_type.kelvin_range.max)
                if hasattr(bulb_type, "features") and bulb_type.features:
                    device.features = {
                        "color": bool(getattr(bulb_type.features, "color", False)),
                        "color_tmp": bool(getattr(bulb_type.features, "color_tmp", False)),
                        "effect": bool(getattr(bulb_type.features, "effect", False)),
                        "brightness": bool(getattr(bulb_type.features, "brightness", False)),
                    }
        except (asyncio.TimeoutError, WizLightTimeOutError):
            logger.warning("Timeout retrieving bulb type/features from %s", ip)
        except Exception as exc:
            logger.warning("Could not retrieve bulb type from %s: %s", ip, exc)

        # Retrieve MAC address if not already known
        if not device.mac:
            try:
                device.mac = await asyncio.wait_for(light.getMac(), timeout=timeout)
            except Exception as exc:
                logger.debug("Could not retrieve MAC from %s: %s", ip, exc)

        # Retrieve current power and state
        try:
            states = await asyncio.wait_for(light.updateState(), timeout=timeout)
            device.is_on = light.status
            if states and states[0]:
                primary = states[0]
                device.brightness = primary.get_brightness()
                device.rgb = primary.get_rgb()
                device.colortemp = primary.get_colortemp()
        except (asyncio.TimeoutError, WizLightTimeOutError):
            logger.warning("Timeout retrieving state from %s", ip)
        except Exception as exc:
            logger.warning("Could not retrieve state from %s: %s", ip, exc)

    finally:
        try:
            await light.async_close()
        except Exception:
            pass

    return device


async def discover_devices(
    timeout: float = 4.0,
    broadcast_address: Optional[str] = None,
    fetch_details: bool = True,
) -> List[DiscoveredDevice]:
    """Scan local network for WiZ devices via UDP broadcast.
    
    Args:
        timeout: Total time in seconds to wait for responses.
        broadcast_address: Explicit broadcast address. If None, auto-detects
                           subnet broadcasts and uses 255.255.255.255.
        fetch_details: If True, queries each discovered bulb for full details.
        
    Returns:
        List of DiscoveredDevice instances.
    """
    logger.info("Starting WiZ bulb discovery (timeout: %.1fs)...", timeout)
    
    if broadcast_address:
        target_broadcasts = [broadcast_address]
    else:
        target_broadcasts = get_subnet_broadcast_addresses()
        
    logger.debug("Broadcasting discovery probes to: %s", target_broadcasts)
    
    loop = asyncio.get_running_loop()
    
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Bind to ephemeral or WIZ_PORT. Port 38899 allows receiving replies sent to 38899.
    try:
        sock.bind(("", WIZ_PORT))
    except OSError:
        # If port 38899 is in use, bind to any available port
        sock.bind(("", 0))
    sock.setblocking(False)
    
    protocol = _DiscoveryProtocol()
    transport, _ = await loop.create_datagram_endpoint(lambda: protocol, sock=sock)
    
    try:
        start_time = asyncio.get_event_loop().time()
        # Broadcast probe every 1.0 second until timeout
        while asyncio.get_event_loop().time() - start_time < timeout:
            for bcast in target_broadcasts:
                try:
                    transport.sendto(REGISTRATION_MESSAGE, (bcast, WIZ_PORT))
                except Exception as exc:
                    logger.debug("Failed sending broadcast to %s: %s", bcast, exc)
            await asyncio.sleep(min(1.0, max(0.1, timeout - (asyncio.get_event_loop().time() - start_time))))
    finally:
        transport.close()
        
    discovered_raw = protocol.discovered
    logger.info("Discovery phase complete. Found %d WiZ device(s).", len(discovered_raw))
    
    results: List[DiscoveredDevice] = []
    
    if not fetch_details:
        for ip, mac in discovered_raw.items():
            results.append(DiscoveredDevice(ip=ip, mac=mac))
        return results
        
    for ip, mac in discovered_raw.items():
        logger.info("Querying device details for %s...", ip)
        device = await fetch_device_details(ip, mac=mac, timeout=timeout)
        results.append(device)
        
    return results
