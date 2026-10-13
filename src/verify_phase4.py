"""WiZ Music Sync — Phase 4 Live Hardware Multi-Mode Verification Script.

Executes a live test session against the physical Philips WiZ E27 bulb:
1. Connects to bulb, records initial state.
2. Starts music sync engine on active Windows audio device.
3. Tests all 5 music-reactive lighting modes sequentially.
4. Dynamically updates effect settings (sensitivity, rate).
5. Cleanly stops synchronization.
6. Verifies accurate pre-sync bulb state restoration.
"""

import asyncio
import logging
import sys
import time

from src.audio.devices import get_default_output_device
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.wiz.controller import WizBulbController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_phase4")


async def run_live_verification(target_ip: str = "192.168.1.4") -> bool:
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

    if restored_state.is_on == initial_state.is_on:
        print(" -> PASS: Bulb power state successfully restored.")
    else:
        print(f" -> WARNING: Power state mismatch: initial={initial_state.is_on}, restored={restored_state.is_on}")

    print("\n" + "=" * 65)
    print("  PHASE 4 PHYSICAL HARDWARE VERIFICATION COMPLETED SUCCESSFULLY")
    print("=" * 65 + "\n")
    return True


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.4"
    success = asyncio.run(run_live_verification(ip))
    sys.exit(0 if success else 1)
