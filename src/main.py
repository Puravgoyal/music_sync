"""WiZ Music Sync - Phase 1 CLI Entrypoint.

Provides automatic bulb discovery, manual IP fallback, and an interactive
hardware test utility for WiZ smart bulbs.
"""

import argparse
import asyncio
import sys
from typing import List, Optional

from src.utils.logging_config import setup_logging
from src.utils.network import validate_ip
from src.wiz.controller import (
    UnsupportedFeatureError,
    ValidationError,
    WizBulbController,
    WizConnectionError,
    WizControllerError,
    WizTimeoutError,
)
from src.wiz.discovery import DiscoveredDevice, discover_devices


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="WiZ Music Sync (Phase 1) - Bulb Discovery & LAN Control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main
  python -m src.main --ip 192.168.1.4
  python -m src.main --timeout 5.0
  python -m src.main --discover-only
        """,
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=None,
        help="Target bulb IP address for direct connection (manual fallback mode).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.5,
        help="Network timeout in seconds for discovery and commands (default: 3.5s).",
    )
    parser.add_argument(
        "--broadcast",
        type=str,
        default=None,
        help="Optional explicit broadcast address for discovery (e.g. 192.168.1.255).",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Discover bulbs, display their status, and exit without opening the test menu.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )
    return parser.parse_args()


async def prompt_user(text: str) -> str:
    """Read user input asynchronously without blocking the event loop."""
    return await asyncio.to_thread(input, text)


async def run_rgb_test_sequence(controller: WizBulbController) -> None:
    """Run conservative sequential color test: RED -> GREEN -> BLUE -> WHITE."""
    print("\n--- Running RGB Test Sequence ---")
    sequence = [
        ("RED", 255, 0, 0),
        ("GREEN", 0, 255, 0),
        ("BLUE", 0, 0, 255),
        ("WHITE", 255, 255, 255),
    ]
    for name, r, g, b in sequence:
        print(f"Setting {name} (RGB: {r}, {g}, {b})...")
        await controller.set_rgb(r, g, b)
        await asyncio.sleep(1.5)
    print("RGB test sequence complete.\n")


async def hardware_test_menu(controller: WizBulbController) -> None:
    """Run interactive CLI test utility."""
    cap = controller.capabilities
    k_range_str = f"{cap.kelvin_range[0]}K - {cap.kelvin_range[1]}K" if cap and cap.kelvin_range else "Unknown"

    print("\n=======================================================")
    print("           WiZ Music Sync — Hardware Test")
    print("=======================================================")
    print(f"Target Bulb:  {controller.ip} (MAC: {controller.mac or 'Unknown'})")
    if cap:
        print(f"Model:        {cap.model or 'Unknown'} ({cap.bulb_class or 'WiZ Bulb'})")
        print(f"Firmware:     {cap.firmware_version or 'Unknown'}")
        print(f"Kelvin Range: {k_range_str}")
    print("=======================================================")

    while True:
        print("\nOptions:")
        print(" 1.  Get bulb state")
        print(" 2.  Turn bulb ON")
        print(" 3.  Turn bulb OFF")
        print(" 4.  Set RED")
        print(" 5.  Set GREEN")
        print(" 6.  Set BLUE")
        print(" 7.  Set WHITE")
        print(" 8.  Set brightness")
        print(" 9.  Set custom RGB")
        print(" 10. Test color temperature")
        print(" 11. Run RGB test sequence")
        print(" 12. Device information & capabilities")
        print(" 0.  Exit")

        try:
            choice = (await prompt_user("\nEnter selection [0-12]: ")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting hardware test.")
            break

        if choice == "0":
            print("Exiting hardware test.")
            break

        try:
            if choice == "1":
                state = await controller.get_state()
                print(f"\n[Bulb State] {state}")

            elif choice == "2":
                await controller.turn_on()
                print("[OK] Bulb turned ON.")

            elif choice == "3":
                await controller.turn_off()
                print("[OK] Bulb turned OFF.")

            elif choice == "4":
                await controller.set_rgb(255, 0, 0)
                print("[OK] Bulb set to RED (255, 0, 0).")

            elif choice == "5":
                await controller.set_rgb(0, 255, 0)
                print("[OK] Bulb set to GREEN (0, 255, 0).")

            elif choice == "6":
                await controller.set_rgb(0, 0, 255)
                print("[OK] Bulb set to BLUE (0, 0, 255).")

            elif choice == "7":
                await controller.set_rgb(255, 255, 255)
                print("[OK] Bulb set to WHITE (255, 255, 255).")

            elif choice == "8":
                raw_b = await prompt_user("Enter brightness (0 - 255, where 0=OFF): ")
                try:
                    brightness = int(raw_b.strip())
                except ValueError:
                    print("[ERROR] Brightness must be a whole integer between 0 and 255.")
                    continue
                await controller.set_brightness(brightness)
                pct = round((brightness / 255.0) * 100)
                print(f"[OK] Brightness set to {brightness}/255 ({pct}%).")

            elif choice == "9":
                raw_rgb = await prompt_user("Enter R G B values separated by spaces (0-255 each): ")
                parts = raw_rgb.strip().split()
                if len(parts) != 3:
                    print("[ERROR] Please provide exactly 3 integer values: Red Green Blue (e.g. 255 128 0).")
                    continue
                try:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    print("[ERROR] RGB components must be integers.")
                    continue
                await controller.set_rgb(r, g, b)
                print(f"[OK] Custom RGB set to ({r}, {g}, {b}).")

            elif choice == "10":
                min_k, max_k = cap.kelvin_range if cap and cap.kelvin_range else (2200, 6500)
                raw_ct = await prompt_user(f"Enter color temperature in Kelvin [{min_k} - {max_k}]: ")
                try:
                    kelvin = int(raw_ct.strip())
                except ValueError:
                    print(f"[ERROR] Color temperature must be an integer between {min_k} and {max_k}.")
                    continue
                await controller.set_colortemp(kelvin)
                print(f"[OK] Color temperature set to {kelvin}K.")

            elif choice == "11":
                await run_rgb_test_sequence(controller)

            elif choice == "12":
                print("\n[Device Information & Capabilities]")
                print(f"  IP Address:       {controller.ip}")
                print(f"  MAC Address:      {controller.mac or 'Unknown'}")
                if cap:
                    print(f"  Model:            {cap.model or 'Unknown'}")
                    print(f"  Firmware:         {cap.firmware_version or 'Unknown'}")
                    print(f"  Device Class:     {cap.bulb_class or 'Unknown'}")
                    print(f"  Supports RGB:     {cap.supports_rgb}")
                    print(f"  Supports White:   {cap.supports_colortemp}")
                    print(f"  Supports Dimming: {cap.supports_brightness}")
                    print(f"  Kelvin Range:     {k_range_str}")
                else:
                    print("  No hardware profile cached.")

            else:
                print(f"[WARNING] Invalid option '{choice}'. Please select a number from 0 to 12.")

        except ValidationError as err:
            print(f"[VALIDATION ERROR] {err}")
        except UnsupportedFeatureError as err:
            print(f"[FEATURE NOT SUPPORTED] {err}")
        except WizTimeoutError as err:
            print(f"[TIMEOUT ERROR] {err}")
        except WizConnectionError as err:
            print(f"[CONNECTION ERROR] {err}")
        except WizControllerError as err:
            print(f"[CONTROLLER ERROR] {err}")
        except Exception as err:
            print(f"[UNEXPECTED ERROR] {type(err).__name__}: {err}")


async def select_or_discover_bulb(
    target_ip: Optional[str],
    timeout: float,
    broadcast: Optional[str],
    discover_only: bool,
) -> Optional[str]:
    """Execute discovery or manual IP resolution."""
    if target_ip:
        try:
            clean_ip = validate_ip(target_ip)
            print(f"\nManual IP mode: connecting to {clean_ip}...")
            return clean_ip
        except ValueError as err:
            print(f"[ERROR] Invalid IP address: {err}")
            return None

    # Automatic discovery mode
    print("\nSearching for WiZ devices...")
    devices: List[DiscoveredDevice] = await discover_devices(
        timeout=timeout,
        broadcast_address=broadcast,
        fetch_details=True,
    )

    if not devices:
        print("\nNo WiZ devices found on the local network.")
        print("Troubleshooting tips:")
        print("  1. Verify your WiZ bulb is powered ON at the light switch.")
        print("  2. Ensure this computer is connected to the same 2.4 GHz Wi-Fi network.")
        print("  3. If your router blocks UDP broadcast, run with manual fallback:")
        print("     python -m src.main --ip <bulb-ip>")
        return None

    count = len(devices)
    print(f"\nFound {count} WiZ device{'s' if count != 1 else ''}:\n")
    for idx, dev in enumerate(devices, 1):
        print(f"[{idx}] {dev.ip} (MAC: {dev.mac or 'Unknown'})")
        print(dev.summary())
        print("-" * 55)

    if discover_only:
        return None

    if count == 1:
        chosen = devices[0].ip
        print(f"\nAutomatically selecting bulb at {chosen}.")
        return chosen

    # Multiple devices: allow selection
    while True:
        try:
            choice = (await prompt_user(f"Select a bulb [1-{count}] or 0 to exit: ")).strip()
            if choice == "0":
                return None
            idx = int(choice)
            if 1 <= idx <= count:
                return devices[idx - 1].ip
            print(f"Please enter a number between 1 and {count}.")
        except (ValueError, IndexError):
            print("Invalid input. Please enter a valid number.")
        except (KeyboardInterrupt, EOFError):
            return None


async def async_main() -> int:
    """Async application main function."""
    args = parse_arguments()
    setup_logging(verbose=args.verbose)

    chosen_ip = await select_or_discover_bulb(
        target_ip=args.ip,
        timeout=args.timeout,
        broadcast=args.broadcast,
        discover_only=args.discover_only,
    )

    if not chosen_ip:
        if args.discover_only:
            return 0
        return 1

    # Connect to selected bulb
    controller = WizBulbController(ip=chosen_ip, timeout=args.timeout)
    try:
        await controller.connect()
    except WizControllerError as err:
        print(f"\n[ERROR] Failed to connect to WiZ bulb at {chosen_ip}: {err}")
        return 1
    except Exception as err:
        print(f"\n[ERROR] Unexpected error connecting to {chosen_ip}: {err}")
        return 1

    try:
        await hardware_test_menu(controller)
    finally:
        await controller.close()

    return 0


def main() -> None:
    """Synchronous entrypoint."""
    try:
        exit_code = asyncio.run(async_main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
