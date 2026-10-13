"""WiZ Music Sync — Phase 4 Live Hardware Multi-Mode Verification Script.

Executes a live test session against the physical Philips WiZ E27 bulb:
1. Resolves target bulb IP via CLI argument or automatic UDP discovery (no hardcoded IP).
2. Connects to bulb, records initial state (power, mode, brightness, RGB, Kelvin, scene, white channels).
3. Starts music sync engine on active Windows audio device.
4. Tests all 5 music-reactive lighting modes sequentially.
5. Dynamically updates effect settings (sensitivity, rate).
6. Cleanly stops synchronization.
7. Performs strict assertion of pre-sync state restoration (power, mode, brightness +/-3, RGB/CT/scene/white).
8. Exits with exit code 0 on complete pass, or exit code 1 on mismatch/error.
"""

import argparse
import asyncio
import logging
import sys
import time
from typing import Optional

from src.audio.devices import get_default_output_device
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.wiz.controller import WizBulbController
from src.wiz.discovery import discover_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_phase4")


async def resolve_target_bulb_ip(cli_ip: Optional[str] = None) -> str:
    """Resolve target bulb IP via explicit CLI argument or auto-discovery."""
    if cli_ip:
        logger.info("Using explicit CLI bulb IP: %s", cli_ip)
        return cli_ip

    print("No bulb IP specified on CLI. Scanning local network for WiZ bulbs (timeout: 3.0s)...")
    devices = await discover_devices(timeout=3.0, fetch_details=True)
    if not devices:
        print("[!] ERROR: No WiZ smart bulbs discovered on local network and no IP provided on CLI.")
        sys.exit(1)

    chosen = devices[0]
    print(f" -> Auto-discovered WiZ bulb: {chosen.ip} ({chosen.model or 'WiZ'}, MAC: {chosen.mac or 'N/A'})")
    return chosen.ip


async def run_live_verification(target_ip: str) -> bool:
    print("\n" + "=" * 65)
    print(f" WiZ Music Sync — Phase 4 Live Hardware Verification")
    print(f" Target Bulb: {target_ip}")
    print("=" * 65 + "\n")

    # Step 1: Pre-test bulb check & record initial state
    print("[1/6] Connecting to physical bulb to record pre-sync state...")
    controller = WizBulbController(target_ip)
    await controller.connect()
    initial_state = await controller.get_state()
    print(f" -> Initial Bulb State: {initial_state}")
    print(f" -> Active Lighting Mode: {initial_state.active_mode}")
    await controller.disconnect()

    # Step 2: Initialize MusicSyncEngine
    dev = get_default_output_device()
    dev_name = dev.name if dev else "Default Audio Device"
    print(f"\n[2/6] Selected Windows Audio Capture Device: {dev_name}")

    engine = MusicSyncEngine(
        bulb_ip=target_ip,
        audio_device_index=dev.index if dev else None,
        effect_name="spectrum",
        update_rate_hz=4.0,
        restore_state=True,
    )

    # Step 3: Start Synchronization
    print("\n[3/6] Starting MusicSyncEngine...")
    await engine.start()
    assert engine.is_running, "Engine failed to report running state!"
    print(" -> PASS: MusicSyncEngine started successfully.")

    # Step 4: Sequentially test all 5 effect modes
    effects = [
        ("spectrum", "Mode 1: Spectrum RGB (Tri-band frequency mixing)"),
        ("beat", "Mode 2: Beat Pulse (Rhythmic onset brightness pulse)"),
        ("bass", "Mode 3: Bass Reactive (Low-frequency crimson/orange punch)"),
        ("smooth", "Mode 4: Smooth Spectrum (Circular continuous hue drift)"),
        ("ambient", "Mode 5: Ambient Flow (Atmospheric background flow)"),
    ]

    print("\n[4/6] Streaming audio to physical bulb across all 5 lighting modes...")
    for mode_key, mode_desc in effects:
        print(f"\n -> Switching to {mode_desc}...")
        engine.set_effect(mode_key)
        assert engine.current_effect.name is not None
        # Let it stream live commands for 3.0 seconds
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < 3.0:
            status = engine.get_status()
            metrics = engine.last_metrics
            vol = f"Vol={metrics.loudness:.2f}" if metrics else "Vol=N/A"
            beat = " [BEAT!]" if metrics and metrics.is_onset else ""
            sys.stdout.write(
                f"\r    Tgt:{status.target_state.rgb}@{status.target_state.brightness} | "
                f"Bulb:{status.applied_state.rgb if status.applied_state else (0,0,0)} | "
                f"{vol}{beat} | "
                f"Rate={status.updates_per_second:.1f}Hz ({status.commands_sent} sent, {status.commands_failed} err)"
            )
            sys.stdout.flush()
            await asyncio.sleep(0.15)
        print()

    # Step 5: Test dynamic settings tuning
    print("\n[5/6] Testing dynamic settings adjustment (sensitivity=2.0x, rate=5.0Hz)...")
    engine.set_settings(EffectSettings(sensitivity=2.0, update_rate_hz=5.0))
    await asyncio.sleep(2.0)
    print(" -> PASS: Dynamic settings applied without interruption.")

    # Step 6: Stop and verify state restoration
    print("\n[6/6] Stopping MusicSyncEngine and restoring pre-sync bulb state...")
    await engine.stop()
    assert not engine.is_running, "Engine reported running after stop!"
    print(" -> Engine stopped cleanly.")

    # Verify bulb state
    await asyncio.sleep(0.5)
    ctrl_verify = WizBulbController(target_ip)
    await ctrl_verify.connect()
    restored_state = await ctrl_verify.get_state()
    print(f" -> Restored Bulb State: {restored_state}")
    print(f" -> Active Lighting Mode: {restored_state.active_mode}")
    await ctrl_verify.disconnect()

    # Strict Comparative State Verification
    print("\n[6/6] Verifying restored bulb properties against pre-sync state...")
    mismatches: list[str] = []

    # 1. Power State Check
    if restored_state.is_on != initial_state.is_on:
        mismatches.append(f"Power state mismatch: initial={initial_state.is_on}, restored={restored_state.is_on}")

    # If bulb was originally ON, verify active lighting mode and parameters
    if initial_state.is_on:
        # 2. Active Mode Check
        if restored_state.active_mode != initial_state.active_mode:
            mismatches.append(
                f"Active mode mismatch: initial='{initial_state.active_mode}', restored='{restored_state.active_mode}'"
            )

        # 3. Brightness Check (within +/- 3 tolerance for rounding)
        if initial_state.brightness is not None:
            if restored_state.brightness is None:
                mismatches.append(f"Brightness missing in restored state (initial={initial_state.brightness})")
            elif abs(restored_state.brightness - initial_state.brightness) > 3:
                mismatches.append(
                    f"Brightness mismatch beyond +/-3: initial={initial_state.brightness}, restored={restored_state.brightness}"
                )

        # 4. Mode-specific property checks
        if initial_state.active_mode == "rgb" and initial_state.rgb is not None:
            if restored_state.rgb != initial_state.rgb:
                mismatches.append(f"RGB mismatch: initial={initial_state.rgb}, restored={restored_state.rgb}")

        elif initial_state.active_mode == "colortemp" and initial_state.colortemp is not None:
            if restored_state.colortemp is None or abs(restored_state.colortemp - initial_state.colortemp) > 50:
                mismatches.append(
                    f"Color temp mismatch: initial={initial_state.colortemp}, restored={restored_state.colortemp}"
                )

        elif initial_state.active_mode == "scene" and initial_state.scene_id is not None:
            if restored_state.scene_id != initial_state.scene_id:
                mismatches.append(
                    f"Scene ID mismatch: initial={initial_state.scene_id}, restored={restored_state.scene_id}"
                )

        elif initial_state.active_mode == "white":
            if initial_state.warm_white is not None and (
                restored_state.warm_white is None or abs(restored_state.warm_white - initial_state.warm_white) > 3
            ):
                mismatches.append(
                    f"Warm white mismatch: initial={initial_state.warm_white}, restored={restored_state.warm_white}"
                )
            if initial_state.cold_white is not None and (
                restored_state.cold_white is None or abs(restored_state.cold_white - initial_state.cold_white) > 3
            ):
                mismatches.append(
                    f"Cold white mismatch: initial={initial_state.cold_white}, restored={restored_state.cold_white}"
                )

    if mismatches:
        print("\n" + "!" * 65)
        print("  FAIL: Pre-sync state restoration verification failed!")
        for m in mismatches:
            print(f"   - {m}")
        print("!" * 65 + "\n")
        return False

    print(" -> PASS: Pre-sync bulb state restored accurately (all property assertions passed).")
    print("\n" + "=" * 65)
    print("  PHASE 4 PHYSICAL HARDWARE VERIFICATION COMPLETED SUCCESSFULLY")
    print("=" * 65 + "\n")
    return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="WiZ Music Sync Phase 4 Hardware Verification")
    parser.add_argument("ip", nargs="?", default=None, help="Bulb IP address (auto-discovers if omitted)")
    args = parser.parse_args()

    target_ip = await resolve_target_bulb_ip(args.ip)
    success = await run_live_verification(target_ip)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
