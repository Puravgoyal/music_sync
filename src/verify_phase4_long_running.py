"""WiZ Music Sync — Phase 4.2 10-Minute Long-Running Verification Session.

Performs a 10-minute (600s) continuous live synchronization session against the physical WiZ bulb:
- Uses a conservative command rate (~3.5 Hz) to respect bulb firmware rate limits.
- Cycles through all 5 music-reactive lighting effects (2 minutes per effect).
- Measures and records:
  * CPU utilization (%)
  * Initial and final memory consumption (WorkingSet MB)
  * Audio frames processed
  * Dropped audio frames
  * Total network commands sent and failed
  * Average command duration (ms)
  * Effective bulb update rate (Hz)
  * Unexpected exceptions
- Stops synchronization and verifies accurate pre-sync bulb state restoration.
- Writes detailed verification results to disk.
"""

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
import logging
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional

from src.audio.devices import get_default_output_device
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.wiz.controller import WizBulbController
from src.wiz.discovery import discover_devices

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("long_running_verify")

psapi = ctypes.WinDLL("psapi")
kernel32 = ctypes.WinDLL("kernel32")


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def get_current_memory_mb() -> float:
    """Retrieve current process Working Set memory usage in MB."""
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return counters.WorkingSetSize / (1024.0 * 1024.0)
    return 0.0


async def resolve_bulb_ip(target_ip: Optional[str] = None) -> str:
    if target_ip:
        return target_ip
    print("Discovering WiZ bulbs on local network...")
    devices = await discover_devices(timeout=3.0, fetch_details=True)
    if not devices:
        print("[!] No bulbs found.")
        sys.exit(1)
    print(f" -> Found bulb: {devices[0].ip}")
    return devices[0].ip


async def run_ten_minute_test(target_ip: str, total_seconds: float = 600.0) -> Dict:
    print("=" * 70)
    print(" WiZ Music Sync — Phase 4.2 10-Minute Real-World Verification Session")
    print(f" Target Bulb: {target_ip} | Duration: {total_seconds:.0f}s ({total_seconds/60:.1f} min)")
    print("=" * 70)

    # 1. Capture initial pre-sync bulb state
    ctrl = WizBulbController(target_ip)
    await ctrl.connect()
    initial_state = await ctrl.get_state()
    print(f"\n[1/5] Initial pre-sync bulb state captured: {initial_state}")
    await ctrl.disconnect()

    # 2. Audio Device & Metrics Baseline
    dev = get_default_output_device()
    dev_name = dev.name if dev else "Default Audio Device"
    print(f"[2/5] Selected Audio Output Device: {dev_name}")

    mem_initial = get_current_memory_mb()
    t_start = time.perf_counter()
    cpu_proc_start = time.process_time()

    print(f"[3/5] Starting MusicSyncEngine (Update rate: 3.5 Hz, Initial Memory: {mem_initial:.2f} MB)...")
    engine = MusicSyncEngine(
        bulb_ip=target_ip,
        audio_device_index=dev.index if dev else None,
        effect_name="spectrum",
        update_rate_hz=3.5,
        restore_state=True,
    )
    await engine.start()
    assert engine.is_running, "Engine failed to report running state!"

    effects = [
        ("spectrum", "Spectrum RGB", 0, 120),
        ("beat", "Beat Pulse", 120, 240),
        ("bass", "Bass Reactive", 240, 360),
        ("smooth", "Smooth Spectrum", 360, 480),
        ("ambient", "Ambient Flow", 480, 600),
    ]

    current_effect_idx = 0
    engine.set_effect(effects[0][0])

    samples: List[Dict] = []
    unexpected_exceptions = []
    last_sample_time = t_start

    print(f"\n[4/5] Executing continuous sync session across 5 effects...")

    try:
        while True:
            elapsed = time.perf_counter() - t_start
            if elapsed >= total_seconds:
                break

            # Check effect rotation (every 2 minutes / 120s)
            target_idx = min(int(elapsed // 120), len(effects) - 1)
            if target_idx != current_effect_idx:
                current_effect_idx = target_idx
                eff_key, eff_name, _, _ = effects[current_effect_idx]
                engine.set_effect(eff_key)
                print(f"\n -> [{elapsed:4.0f}s] Switched to effect {current_effect_idx + 1}/5: {eff_name}")

            # Sample every 10 seconds
            if time.perf_counter() - last_sample_time >= 10.0:
                last_sample_time = time.perf_counter()
                status = engine.get_status()
                stats = engine.last_stats
                metrics = engine.last_metrics
                cur_mem = get_current_memory_mb()

                sample_entry = {
                    "elapsed_sec": round(elapsed, 1),
                    "effect": engine.current_effect.name,
                    "memory_mb": round(cur_mem, 2),
                    "commands_sent": status.commands_sent,
                    "commands_failed": status.commands_failed,
                    "update_rate_hz": round(status.updates_per_second, 2),
                    "latency_ms": round(status.last_command_duration_ms, 2),
                    "audio_frames": stats.frames_processed if stats else 0,
                    "dropped_frames": stats.dropped_frames if stats else 0,
                }
                samples.append(sample_entry)

                vol = f"Vol={metrics.loudness:.2f}" if metrics else "Vol=N/A"
                sys.stdout.write(
                    f"\r  [{elapsed:4.0f}s / {total_seconds:.0f}s] "
                    f"Effect: {engine.current_effect.name:<16} | "
                    f"Rate: {status.updates_per_second:3.1f} Hz | "
                    f"Commands: {status.commands_sent:4d} (err: {status.commands_failed}) | "
                    f"Lat: {status.last_command_duration_ms:4.1f}ms | "
                    f"Mem: {cur_mem:4.1f}MB"
                )
                sys.stdout.flush()

            await asyncio.sleep(0.5)

    except Exception as exc:
        unexpected_exceptions.append(str(exc))
        logger.error("Unexpected exception during long running sync: %s", exc, exc_info=True)

    print("\n\n[5/5] Stopping synchronization and assessing restoration...")
    resto_report = await engine.stop()
    elapsed_total = time.perf_counter() - t_start
    cpu_proc_total = time.process_time() - cpu_proc_start
    cpu_percent = (cpu_proc_total / elapsed_total) * 100.0
    mem_final = get_current_memory_mb()

    # Verify bulb state
    await asyncio.sleep(1.0)
    ctrl_post = WizBulbController(target_ip)
    await ctrl_post.connect()
    restored_state = await ctrl_post.get_state()
    await ctrl_post.disconnect()

    final_status = engine.get_status()
    final_stats = engine.last_stats

    # State restoration assertions
    power_restored = (restored_state.is_on == initial_state.is_on)
    mode_restored = (restored_state.active_mode == initial_state.active_mode) if initial_state.is_on else True

    # Compute average latency across samples
    latencies = [s["latency_ms"] for s in samples if s["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    rates = [s["update_rate_hz"] for s in samples if s["update_rate_hz"] > 0]
    avg_rate = sum(rates) / len(rates) if rates else 0.0

    report_data = {
        "target_bulb_ip": target_ip,
        "duration_seconds": round(elapsed_total, 1),
        "initial_memory_mb": round(mem_initial, 2),
        "final_memory_mb": round(mem_final, 2),
        "memory_delta_mb": round(mem_final - mem_initial, 2),
        "cpu_utilization_percent": round(cpu_percent, 2),
        "audio_frames_processed": final_stats.frames_processed if final_stats else 0,
        "dropped_frames": final_stats.dropped_frames if final_stats else 0,
        "total_commands_sent": final_status.commands_sent,
        "total_commands_failed": final_status.commands_failed,
        "command_failure_rate_percent": round(
            (final_status.commands_failed / max(1, final_status.commands_sent)) * 100.0, 2
        ),
        "average_command_duration_ms": round(avg_latency, 2),
        "effective_update_rate_hz": round(avg_rate, 2),
        "unexpected_exceptions": unexpected_exceptions,
        "restoration_result": resto_report.result.value,
        "restoration_details": resto_report.details,
        "power_state_restored": power_restored,
        "lighting_mode_restored": mode_restored,
        "sample_count": len(samples),
        "samples": samples,
    }

    # Save report
    out_file = Path("long_running_session_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print("\n" + "=" * 70)
    print(" 10-MINUTE VERIFICATION SESSION SUMMARY")
    print("=" * 70)
    print(f" Duration:                   {elapsed_total:.1f} s")
    print(f" CPU Utilization:            {cpu_percent:.2f} %")
    print(f" Memory (Initial -> Final):  {mem_initial:.2f} MB -> {mem_final:.2f} MB (Delta: {mem_final - mem_initial:+.2f} MB)")
    print(f" Audio Frames Processed:     {report_data['audio_frames_processed']}")
    print(f" Dropped Audio Frames:       {report_data['dropped_frames']}")
    print(f" Network Commands Sent:      {final_status.commands_sent}")
    print(f" Network Errors:             {final_status.commands_failed}")
    print(f" Average Command Duration:   {avg_latency:.2f} ms")
    print(f" Effective Bulb Update Rate: {avg_rate:.2f} Hz")
    print(f" Unexpected Exceptions:      {len(unexpected_exceptions)}")
    print(f" Restoration Result:         {resto_report}")
    print(f" Power Restored:             {power_restored}")
    print(f" Mode Restored:              {mode_restored}")
    print(f" Report Saved To:            {out_file.resolve()}")
    print("=" * 70 + "\n")

    return report_data


async def main() -> None:
    parser = argparse.ArgumentParser(description="WiZ Music Sync 10-Minute Long-Running Verification")
    parser.add_argument("ip", nargs="?", default=None, help="Bulb IP address (auto-discovers if omitted)")
    parser.add_argument("--duration", type=float, default=600.0, help="Test duration in seconds (default: 600)")
    args = parser.parse_args()

    ip = await resolve_bulb_ip(args.ip)
    data = await run_ten_minute_test(ip, total_seconds=args.duration)
    success = (len(data["unexpected_exceptions"]) == 0 and data["power_state_restored"])
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
