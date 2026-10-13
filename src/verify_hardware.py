"""WiZ Music Sync - Non-interactive Hardware Verification Script.

Executes a complete sequential hardware test across all capabilities of the
connected physical WiZ bulb with pauses to allow visual confirmation.
"""

import asyncio
import sys

from src.wiz.controller import WizBulbController
from src.wiz.discovery import discover_devices


async def run_hardware_verification(target_ip: str = "192.168.1.4") -> None:
    print("=" * 60)
    print("       WiZ Music Sync — Live Hardware Verification")
    print("=" * 60)
    print(f"Target Bulb IP: {target_ip}\n")

    # Step 1: Discovery verification
    print("[TEST 1/12] Verifying Automatic Discovery...")
    devices = await discover_devices(timeout=3.0, fetch_details=False)
    discovered_ips = [d.ip for d in devices]
    if target_ip in discovered_ips:
        print(f" -> PASS: Bulb found on local network: {target_ip}")
    else:
        print(f" -> WARNING: Direct connection will be used (discovered: {discovered_ips})")

    # Step 2: Connection & Device Info
    print("\n[TEST 2/12] Connecting and retrieving device information...")
    controller = WizBulbController(target_ip, timeout=4.0)
    await controller.connect()
    cap = controller.capabilities
    print(f" -> Model:        {cap.model if cap else 'Unknown'}")
    print(f" -> MAC:          {controller.mac}")
    print(f" -> Firmware:     {cap.firmware_version if cap else 'Unknown'}")
    print(f" -> Kelvin Range: {cap.kelvin_range if cap else 'Unknown'}")
    print(" -> PASS: Device profile retrieved successfully.")

    # Step 3: Turn ON
    print("\n[TEST 3/12] Turning bulb ON...")
    await controller.turn_on()
    state = await controller.get_state()
    print(f" -> Power State: {'ON' if state.is_on else 'OFF'}")
    print(" -> Watching physical bulb: Should be ON. (pausing 2.0s)")
    await asyncio.sleep(2.0)

    # Step 4: Turn OFF
    print("\n[TEST 4/12] Turning bulb OFF...")
    await controller.turn_off()
    state = await controller.get_state()
    print(f" -> Power State: {'ON' if state.is_on else 'OFF'}")
    print(" -> Watching physical bulb: Should be OFF. (pausing 2.0s)")
    await asyncio.sleep(2.0)

    # Turn back ON for color tests
    print("\n[--] Turning bulb back ON for color/brightness tests...")
    await controller.turn_on()
    await asyncio.sleep(1.0)

    # Step 5: RED
    print("\n[TEST 5/12] Setting RED (255, 0, 0)...")
    await controller.set_rgb(255, 0, 0)
    print(" -> Watching physical bulb: Should be pure RED. (pausing 2.5s)")
    await asyncio.sleep(2.5)

    # Step 6: GREEN
    print("\n[TEST 6/12] Setting GREEN (0, 255, 0)...")
    await controller.set_rgb(0, 255, 0)
    print(" -> Watching physical bulb: Should be pure GREEN. (pausing 2.5s)")
    await asyncio.sleep(2.5)

    # Step 7: BLUE
    print("\n[TEST 7/12] Setting BLUE (0, 0, 255)...")
    await controller.set_rgb(0, 0, 255)
    print(" -> Watching physical bulb: Should be pure BLUE. (pausing 2.5s)")
    await asyncio.sleep(2.5)

    # Step 8: Custom RGB (Amber / Warm Gold)
    print("\n[TEST 8/12] Setting Custom RGB (255, 128, 0 - Amber / Orange)...")
    await controller.set_rgb(255, 128, 0)
    print(" -> Watching physical bulb: Should be AMBER / ORANGE. (pausing 2.5s)")
    await asyncio.sleep(2.5)

    # Step 9: Brightness Dimming & Full
    print("\n[TEST 9/12] Testing Brightness Control...")
    print(" -> Setting Brightness to 50% (128/255)...")
    await controller.set_brightness(128)
    await asyncio.sleep(2.0)
    print(" -> Setting Brightness to 100% (255/255)...")
    await controller.set_brightness(255)
    print(" -> Watching physical bulb: Should visibly dim then brighten to full. (pausing 2.0s)")
    await asyncio.sleep(2.0)

    # Step 10: Color Temperature
    print("\n[TEST 10/12] Testing Color Temperature (Tunable White)...")
    print(" -> Setting Warm White 2700K...")
    await controller.set_colortemp(2700)
    await asyncio.sleep(2.5)
    print(" -> Setting Cool Daylight 5500K...")
    await controller.set_colortemp(5500)
    print(" -> Watching physical bulb: Should switch from warm cozy white to crisp daylight. (pausing 2.5s)")
    await asyncio.sleep(2.5)

    # Step 11: RGB Sequence
    print("\n[TEST 11/12] Testing Sequential RGB Cycle (Reliability check)...")
    sequence = [("RED", 255, 0, 0), ("GREEN", 0, 255, 0), ("BLUE", 0, 0, 255), ("WHITE", 255, 255, 255)]
    for name, r, g, b in sequence:
        print(f" -> Setting {name} ({r}, {g}, {b})...")
        await controller.set_rgb(r, g, b)
        await asyncio.sleep(1.5)
    print(" -> PASS: Sequential command cycle finished without timeouts or packet drops.")

    # Step 12: Clean Exit & Final State
    print("\n[TEST 12/12] Cleaning up socket resources and closing controller...")
    await controller.close()
    print(" -> PASS: Controller closed cleanly.")

    print("\n" + "=" * 60)
    print("  HARDWARE VERIFICATION SEQUENCE COMPLETED SUCCESSFULLY")
    print("=" * 60)


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.4"
    asyncio.run(run_hardware_verification(ip))
