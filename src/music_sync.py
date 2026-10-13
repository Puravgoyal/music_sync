"""WiZ Music Sync - Real-Time Music-to-Light Synchronization CLI.

Usage:
    python -m src.music_sync --ip 192.168.1.4 --effect spectrum
    python -m src.music_sync --dry-run --effect beat
    python -m src.music_sync --list-devices
    python -m src.music_sync --list-effects
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from typing import Optional

from src.audio.devices import get_audio_output_devices, get_default_output_device
from src.effects import EffectSettings, list_effects
from src.sync.engine import MusicSyncEngine
from src.wiz.discovery import discover_devices

logger = logging.getLogger("wiz_music_sync")


def _render_bar(value: float, length: int = 14) -> str:
    """Render a text bar meter for values between 0.0 and 1.0."""
    clamped = max(0.0, min(1.0, value))
    filled = int(round(clamped * length))
    return f"[{'#' * filled}{'.' * (length - filled)}] {clamped:.2f}"


def _format_rgb_box(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"({r:3d}, {g:3d}, {b:3d})"


async def run_sync_cli(args: argparse.Namespace) -> int:
    """Main asynchronous execution loop for the music sync CLI."""
    if args.list_effects:
        print("\nAvailable Music-Reactive Effects:")
        print("-" * 55)
        for eff in list_effects():
            print(f"  * {eff['id']:<10} : {eff['name']} - {eff['description']}")
        print()
        return 0

    if args.list_devices:
        devices = get_audio_output_devices()
        print("\nAvailable Windows Audio Output Loopback Devices:")
        print("-" * 65)
        default_dev = get_default_output_device()
        for dev in devices:
            marker = " (DEFAULT)" if (default_dev and dev.index == default_dev.index) else ""
            print(f"  [{dev.index:2d}] {dev.name} ({dev.sample_rate} Hz, {dev.channels}ch){marker}")
        print()
        return 0

    # Bulb IP resolution
    target_ip = args.ip
    if not target_ip and not args.dry_run:
        print("[*] No bulb IP provided. Scanning local Wi-Fi for WiZ bulbs...")
        discovered = await discover_devices(timeout=1.8)
        if discovered:
            target_ip = discovered[0].ip
            print(f"[*] Found WiZ bulb at {target_ip} ({discovered[0].mac or 'Unknown MAC'}).")
        else:
            print("[!] No WiZ bulb discovered on local network. Use --ip <IP> or --dry-run.")
            return 1

    # Configure effect settings
    settings = EffectSettings(
        sensitivity=args.sensitivity,
        min_brightness=args.min_brightness,
        max_brightness=args.max_brightness,
        update_rate_hz=args.rate,
    )

    engine = MusicSyncEngine(
        bulb_ip=target_ip,
        audio_device_index=args.device,
        effect_name=args.effect,
        effect_settings=settings,
        update_rate_hz=args.rate,
        dry_run=args.dry_run,
        restore_state=not args.no_restore,
    )

    stop_event = asyncio.Event()

    def handle_signal(*_: object) -> None:
        stop_event.set()

    # Set up signal handlers for graceful shutdown on Windows & POSIX
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # signal handler not implemented for event loop on Windows
                signal.signal(sig, handle_signal)
    except Exception:
        pass

    try:
        await engine.start()
    except Exception as exc:
        print(f"\n[!] Failed to start MusicSyncEngine: {exc}")
        return 1

    mode_label = "DRY-RUN (Simulated)" if args.dry_run else f"LIVE UDP ({target_ip})"
    print(f"\n" + "=" * 68)
    print(f" WiZ Music Sync | Effect: {engine.current_effect.name} | Mode: {mode_label}")
    print(f" Rate: {args.rate:.1f} Hz | Sensitivity: {args.sensitivity:.2f} | Ctrl+C to Stop")
    print("=" * 68 + "\n")

    start_time = time.perf_counter()
    try:
        while not stop_event.is_set():
            if args.duration and (time.perf_counter() - start_time) >= args.duration:
                print("\n[*] Specified duration completed.")
                break

            status = engine.get_status()
            metrics = engine.last_metrics
            stats = engine.last_stats

            if metrics and stats:
                beat_tag = " [BEAT!]" if metrics.is_onset else "        "
                audio_fps = stats.fps
                dsp_ms = stats.analysis_time_ms
                target_rgb = status.target_state.rgb
                target_b = status.target_state.brightness
                applied_rgb = status.applied_state.rgb if status.applied_state else (0, 0, 0)
                applied_b = status.applied_state.brightness if status.applied_state else 0

                # Formatted single-line status dashboard
                line = (
                    f"\rB:{_render_bar(metrics.bass, 6)} "
                    f"M:{_render_bar(metrics.mid, 6)} "
                    f"T:{_render_bar(metrics.treble, 6)} "
                    f"Vol:{_render_bar(metrics.loudness, 6)}{beat_tag} | "
                    f"Tgt:{_format_rgb_box(target_rgb)}@{target_b:3d} | "
                    f"Bulb:{_format_rgb_box(applied_rgb)}@{applied_b:3d} | "
                    f"Rate:{status.updates_per_second:4.1f}Hz "
                    f"({status.commands_sent} sent, {status.commands_failed} err)"
                )
                sys.stdout.write(line)
                sys.stdout.flush()

            await asyncio.sleep(0.1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\n\n[*] Stopping music sync and restoring bulb state...")
        await engine.stop()
        print("[*] Music sync stopped cleanly.")

    return 0


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="WiZ Music Sync - Real-Time Windows Audio to WiZ Bulb Synchronization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--ip", type=str, default=None, help="Target WiZ bulb IP address (auto-discovers if omitted)")
    parser.add_argument("--device", type=int, default=None, help="Windows audio output device index")
    parser.add_argument(
        "--effect",
        type=str,
        default="spectrum",
        choices=["spectrum", "beat", "bass", "smooth", "ambient"],
        help="Lighting effect mode",
    )
    parser.add_argument("--sensitivity", type=float, default=1.0, help="Audio responsiveness sensitivity [0.1 - 3.0]")
    parser.add_argument("--min-brightness", type=int, default=25, help="Resting / silence brightness [0 - 255]")
    parser.add_argument("--max-brightness", type=int, default=255, help="Peak brightness [0 - 255]")
    parser.add_argument("--rate", type=float, default=4.0, help="Target WiZ bulb update rate in Hz [1.0 - 10.0]")
    parser.add_argument("--duration", type=float, default=None, help="Run duration in seconds (indefinite if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate effects without sending network packets")
    parser.add_argument("--no-restore", action="store_true", help="Do not restore pre-sync bulb state on exit")
    parser.add_argument("--list-devices", action="store_true", help="List available audio loopback devices and exit")
    parser.add_argument("--list-effects", action="store_true", help="List available lighting effects and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # In non-verbose mode, silence external loggers
    if not args.verbose:
        logging.getLogger("pywizlight").setLevel(logging.ERROR)
        logging.getLogger("wiz_music_sync").setLevel(logging.INFO)

    exit_code = asyncio.run(run_sync_cli(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
