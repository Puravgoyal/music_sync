"""WiZ Bulb Network Rate Benchmark Tool.

Systematically measures achievable UDP command update rates, packet loss,
and round-trip latency at 3.5, 4.0, 5.0, 6.0, 8.0, and 10.0 Hz against a physical WiZ bulb.
Safely captures and restores initial bulb state.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import numpy as np

from src.wiz.controller import BulbState, WizBulbController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wiz_rate_benchmark")


@dataclass
class RateBenchmarkResult:
    target_rate_hz: float
    duration_s: float
    commands_attempted: int
    commands_succeeded: int
    commands_failed: int
    achieved_rate_hz: float
    success_rate_pct: float
    latency_min_ms: float
    latency_avg_ms: float
    latency_median_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    stable: bool


async def run_benchmark(
    bulb_ip: str,
    rates: Optional[List[float]] = None,
    test_duration_per_rate: float = 3.5,
    output_file: Optional[Path] = None,
) -> List[RateBenchmarkResult]:
    """Execute update rate benchmarks across specified frequencies."""
    if rates is None:
        rates = [3.5, 4.0, 5.0, 6.0, 8.0, 10.0]

    controller = WizBulbController(ip=bulb_ip, timeout=1.5)
    logger.info("Connecting to WiZ bulb at %s...", bulb_ip)
    await controller.connect()

    # Capture initial bulb state
    initial_state: Optional[BulbState] = None
    try:
        initial_state = await controller.get_state()
        logger.info("Captured initial bulb state: %s", initial_state)
    except Exception as exc:
        logger.warning("Could not query initial state: %s", exc)

    # Ensure bulb is on for test
    if not controller.is_on:
        await controller.turn_on()

    results: List[RateBenchmarkResult] = []

    # Alternating test colors
    colors = [
        (255, 60, 60),
        (60, 255, 60),
        (60, 60, 255),
        (255, 200, 50),
        (200, 60, 255),
    ]

    print(f"\n=======================================================")
    print(f"  WiZ UDP Update Rate Benchmark: {bulb_ip}")
    print(f"  Testing rates: {rates} Hz")
    print(f"=======================================================\n")

    try:
        for target_hz in rates:
            logger.info("Benchmarking target rate: %.1f Hz...", target_hz)
            interval = 1.0 / target_hz
            end_time = time.perf_counter() + test_duration_per_rate

            latencies_ms: List[float] = []
            succeeded = 0
            failed = 0
            color_idx = 0
            t_start = time.perf_counter()

            while time.perf_counter() < end_time:
                t_dispatch = time.perf_counter()
                r, g, b = colors[color_idx % len(colors)]
                color_idx += 1

                try:
                    await controller.set_light_state(r=r, g=g, b=b, brightness=200, timeout=1.2)
                    duration_ms = (time.perf_counter() - t_dispatch) * 1000.0
                    latencies_ms.append(duration_ms)
                    succeeded += 1
                except Exception as exc:
                    duration_ms = (time.perf_counter() - t_dispatch) * 1000.0
                    latencies_ms.append(duration_ms)
                    failed += 1
                    logger.debug("Command failed at %.1f Hz: %s", target_hz, exc)

                elapsed_command = time.perf_counter() - t_dispatch
                sleep_time = max(0.002, interval - elapsed_command)
                await asyncio.sleep(sleep_time)

            total_elapsed = time.perf_counter() - t_start
            attempted = succeeded + failed
            achieved_rate = succeeded / max(0.1, total_elapsed)
            success_pct = (succeeded / max(1, attempted)) * 100.0

            if latencies_ms:
                l_min = float(np.min(latencies_ms))
                l_avg = float(np.mean(latencies_ms))
                l_med = float(np.median(latencies_ms))
                l_p95 = float(np.percentile(latencies_ms, 95))
                l_max = float(np.max(latencies_ms))
            else:
                l_min = l_avg = l_med = l_p95 = l_max = 0.0

            # Stability criteria: >= 92% success and p95 latency < 120ms
            is_stable = (success_pct >= 92.0) and (l_p95 < 120.0)

            res = RateBenchmarkResult(
                target_rate_hz=target_hz,
                duration_s=round(total_elapsed, 2),
                commands_attempted=attempted,
                commands_succeeded=succeeded,
                commands_failed=failed,
                achieved_rate_hz=round(achieved_rate, 2),
                success_rate_pct=round(success_pct, 1),
                latency_min_ms=round(l_min, 1),
                latency_avg_ms=round(l_avg, 1),
                latency_median_ms=round(l_med, 1),
                latency_p95_ms=round(l_p95, 1),
                latency_max_ms=round(l_max, 1),
                stable=is_stable,
            )
            results.append(res)
            logger.info(
                "Result %.1f Hz: Achieved %.1f Hz | Success: %.1f%% | p95 Latency: %.1f ms | Stable: %s",
                target_hz,
                achieved_rate,
                success_pct,
                l_p95,
                is_stable,
            )
            # Brief cooldown between rate tiers
            await asyncio.sleep(0.5)

    finally:
        # Restore pre-benchmark bulb state
        if initial_state and controller.is_connected:
            logger.info("Restoring pre-benchmark bulb state...")
            try:
                await controller.restore_state(initial_state)
                logger.info("Initial bulb state restored successfully.")
            except Exception as e:
                logger.warning("Error restoring state: %s", e)

        await controller.disconnect()

    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Target (Hz)':<12} {'Achieved (Hz)':<14} {'Success %':<12} {'Avg Lat (ms)':<14} {'p95 Lat (ms)':<14} {'Stable?':<10}")
    print("-" * 90)
    for r in results:
        stable_str = "YES" if r.stable else "NO (Degraded)"
        print(f"{r.target_rate_hz:<12.1f} {r.achieved_rate_hz:<14.2f} {r.success_rate_pct:<12.1f} {r.latency_avg_ms:<14.1f} {r.latency_p95_ms:<14.1f} {stable_str:<10}")
    print("=" * 90 + "\n")

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
        logger.info("Saved benchmark report to %s", output_file)

    return results


def main():
    parser = argparse.ArgumentParser(description="WiZ Bulb Update Rate Benchmark")
    parser.add_argument("--ip", type=str, default="192.168.1.4", help="Bulb IP address (default: 192.168.1.4)")
    parser.add_argument("--duration", type=float, default=3.0, help="Test duration per rate in seconds (default: 3.0)")
    parser.add_argument("--out", type=str, default="rate_benchmark_results.json", help="Output JSON results path")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.ip, test_duration_per_rate=args.duration, output_file=Path(args.out)))


if __name__ == "__main__":
    main()
