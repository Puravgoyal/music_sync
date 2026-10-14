"""WiZ Bulb Network Rate Benchmark Tool.

Systematically measures achievable UDP command update rates, packet loss,
and round-trip latency at 4.0, 5.0, 6.0, and 8.0 Hz against a physical WiZ bulb.
Uses conservative, smooth lighting transitions and adequately sampled test runs.
Safely captures and restores initial bulb state.
"""

import argparse
import asyncio
import colorsys
import json
import logging
from pathlib import Path
import sys
import time
from dataclasses import asdict, dataclass
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
    latency_p50_ms: float
    latency_avg_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    long_tail_count_250ms: int
    long_tail_pct_250ms: float
    stable: bool


async def run_benchmark(
    bulb_ip: str,
    rates: Optional[List[float]] = None,
    test_duration_per_rate: float = 10.0,
    output_file: Optional[Path] = None,
) -> List[RateBenchmarkResult]:
    """Execute update rate benchmarks across specified frequencies."""
    if rates is None:
        rates = [4.0, 5.0, 6.0, 8.0]

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

    print(f"\n==========================================================================================")
    print(f"  WiZ UDP Update Rate Benchmark (Adequately Sampled: {test_duration_per_rate}s / tier)")
    print(f"  Target Rates: {rates} Hz | Smooth Transitions | Bulb IP: {bulb_ip}")
    print(f"==========================================================================================\n")

    try:
        for target_hz in rates:
            logger.info("Benchmarking target rate: %.1f Hz for %.1f s...", target_hz, test_duration_per_rate)
            interval = 1.0 / target_hz
            end_time = time.perf_counter() + test_duration_per_rate

            latencies_ms: List[float] = []
            succeeded = 0
            failed = 0
            step_idx = 0
            t_start = time.perf_counter()

            while time.perf_counter() < end_time:
                t_dispatch = time.perf_counter()

                # Conservative, smooth lighting transitions (gentle HSV hue modulation)
                hue = (step_idx * 0.035) % 1.0
                step_idx += 1
                r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 0.60, 0.55)
                r, g, b = int(r_f * 255), int(g_f * 255), int(b_f * 255)

                try:
                    await controller.set_light_state(r=r, g=g, b=b, brightness=140, timeout=1.2)
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
                l_p50 = float(np.median(latencies_ms))
                l_avg = float(np.mean(latencies_ms))
                l_p95 = float(np.percentile(latencies_ms, 95))
                l_max = float(np.max(latencies_ms))
                long_tail_count = sum(1 for d in latencies_ms if d > 250.0)
                long_tail_pct = (long_tail_count / len(latencies_ms)) * 100.0
            else:
                l_min = l_p50 = l_avg = l_p95 = l_max = 0.0
                long_tail_count = 0
                long_tail_pct = 0.0

            # Rigorous Stability criteria:
            # 1. Packet success rate >= 95.0%
            # 2. Achieved rate within 12% of target rate
            # 3. p95 latency < 250 ms (predictable bounded delivery)
            # 4. Long tail delays (> 250ms) < 5.0%
            is_stable = (
                (success_pct >= 95.0)
                and (achieved_rate >= 0.88 * target_hz)
                and (l_p95 < 250.0)
                and (long_tail_pct < 5.0)
            )

            res = RateBenchmarkResult(
                target_rate_hz=target_hz,
                duration_s=round(total_elapsed, 2),
                commands_attempted=attempted,
                commands_succeeded=succeeded,
                commands_failed=failed,
                achieved_rate_hz=round(achieved_rate, 2),
                success_rate_pct=round(success_pct, 1),
                latency_min_ms=round(l_min, 1),
                latency_p50_ms=round(l_p50, 1),
                latency_avg_ms=round(l_avg, 1),
                latency_p95_ms=round(l_p95, 1),
                latency_max_ms=round(l_max, 1),
                long_tail_count_250ms=long_tail_count,
                long_tail_pct_250ms=round(long_tail_pct, 1),
                stable=is_stable,
            )
            results.append(res)
            logger.info(
                "Result %.1f Hz: Achieved %.2f Hz | Success: %.1f%% | p50: %.1f ms | p95: %.1f ms | Long-tail (>250ms): %d (%.1f%%) | Stable: %s",
                target_hz,
                achieved_rate,
                success_pct,
                l_p50,
                l_p95,
                long_tail_count,
                long_tail_pct,
                is_stable,
            )
            # Brief cooldown between rate tiers to let bulb network queue clear
            await asyncio.sleep(1.0)

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
    print("\n" + "=" * 115)
    print(f"{'Target (Hz)':<12} {'Achieved (Hz)':<14} {'Success %':<12} {'p50 Lat (ms)':<14} {'p95 Lat (ms)':<14} {'Tail >250ms %':<16} {'Stable?':<12}")
    print("-" * 115)
    for r in results:
        stable_str = "YES (Reliable)" if r.stable else "NO (Degraded)"
        print(f"{r.target_rate_hz:<12.1f} {r.achieved_rate_hz:<14.2f} {r.success_rate_pct:<12.1f} {r.latency_p50_ms:<14.1f} {r.latency_p95_ms:<14.1f} {r.long_tail_pct_250ms:<16.1f} {stable_str:<12}")
    print("=" * 115 + "\n")

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
        logger.info("Saved benchmark report to %s", output_file)

    return results


def main():
    parser = argparse.ArgumentParser(description="WiZ Bulb Update Rate Benchmark")
    parser.add_argument("--ip", type=str, default="192.168.1.4", help="Bulb IP address (default: 192.168.1.4)")
    parser.add_argument("--duration", type=float, default=10.0, help="Test duration per rate in seconds (default: 10.0)")
    parser.add_argument("--out", type=str, default="rate_benchmark_results.json", help="Output JSON results path")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.ip, test_duration_per_rate=args.duration, output_file=Path(args.out)))


if __name__ == "__main__":
    main()
