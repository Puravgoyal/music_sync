"""Network utilities including IP validation and broadcast discovery."""

import ipaddress
import logging
import re
import socket
import subprocess
import sys
from typing import List, Set

logger = logging.getLogger("wiz_music_sync.network")


def validate_ip(ip_str: str) -> str:
    """Validate that the given string is a valid IPv4 address suitable for WiZ devices.
    
    Args:
        ip_str: String representation of the IP address.
        
    Returns:
        The validated clean IP string.
        
    Raises:
        ValueError: If the IP address is malformed, not IPv4, loopback, or multicast.
    """
    if not isinstance(ip_str, str):
        raise ValueError(f"Expected IP address as string, got {type(ip_str).__name__}")
    
    clean_ip = ip_str.strip()
    if not clean_ip:
        raise ValueError("IP address cannot be empty.")
    
    try:
        addr = ipaddress.ip_address(clean_ip)
    except ValueError as exc:
        raise ValueError(f"Invalid IP address format '{clean_ip}': {exc}") from exc
    
    if addr.version != 4:
        raise ValueError(f"IPv6 addresses ({clean_ip}) are not supported for WiZ local control.")
    
    if addr.is_loopback:
        raise ValueError(f"Loopback IP address ({clean_ip}) cannot be a WiZ device.")
        
    if addr.is_multicast:
        raise ValueError(f"Multicast IP address ({clean_ip}) cannot be used as a target bulb IP.")
        
    if addr.is_unspecified:
        raise ValueError(f"Unspecified IP address ({clean_ip}) cannot be used as a target bulb IP.")
        
    return clean_ip


def get_subnet_broadcast_addresses() -> List[str]:
    """Retrieve broadcast addresses for all active local IPv4 network interfaces.
    
    On Windows, broadcasting only to 255.255.255.255 may not route over the correct
    network adapter if multiple adapters (e.g. Wi-Fi, VirtualBox, WSL) are active.
    Querying the subnet broadcast address (e.g. 192.168.1.255) ensures discovery
    reaches devices across all active physical interfaces.
    
    Returns:
        List of IPv4 broadcast address strings.
    """
    broadcasts: Set[str] = {"255.255.255.255"}
    
    if sys.platform == "win32":
        try:
            output = subprocess.check_output("ipconfig", text=True, stderr=subprocess.DEVNULL)
            current_ip = None
            for raw_line in output.splitlines():
                line = raw_line.strip()
                if "IPv4 Address" in line or "IPv4-Adresse" in line:
                    match = re.search(r":\s*([\d\.]+)", line)
                    if match:
                        current_ip = match.group(1)
                elif "Subnet Mask" in line or "Subnetzmaske" in line:
                    if current_ip:
                        match = re.search(r":\s*([\d\.]+)", line)
                        if match:
                            mask = match.group(1)
                            try:
                                net = ipaddress.IPv4Network(f"{current_ip}/{mask}", strict=False)
                                broadcasts.add(str(net.broadcast_address))
                            except ValueError:
                                pass
                        current_ip = None
        except Exception as exc:
            logger.debug("Failed to detect broadcast addresses via ipconfig: %s", exc)
            
    # Also resolve local hostname IPs as fallback
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        for ip in ip_list:
            if ip.startswith("127."):
                continue
            # Assume typical /24 subnet if mask is unknown
            parts = ip.split(".")
            if len(parts) == 4:
                broadcasts.add(f"{parts[0]}.{parts[1]}.{parts[2]}.255")
    except Exception as exc:
        logger.debug("Failed to resolve hostname interfaces: %s", exc)
        
    return sorted(list(broadcasts))
