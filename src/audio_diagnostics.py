"""WiZ Music Sync - Phase 2 Audio Diagnostics CLI Utility.

Continuously captures and displays real-time Windows WASAPI loopback audio metrics:
RMS, Bass, Mid, Treble, Musical Onset detection, and pipeline latency telemetry.
"""

import argparse
import sys
import time
from typing import Optional

from src.audio.analyzer import AudioMetrics
from src.audio.capture import AudioCapture, CaptureStats
from src.audio.devices import (
    AudioDevice,
    get_audio_output_devices,
    get_default_output_device,
    get_device_by_index,
)
from src.utils.logging_config import setup_logging


def make_bar(value: float, width: int = 24) -> str:
    """Render a visual ASCII progress bar for energy levels in [0.0, 1.0]."""
    clamped = max(0.0, min(1.0, float(value)))
    filled = int(round(clamped * width))
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {clamped:4.2f}"


def format_diagnostics(metrics: AudioMetrics, stats: CaptureStats, device_name: str) -> str:
    """Format live audio metrics into a clean terminal status block."""
    onset_tag = ">>> [BEAT] <<<" if metrics.is_onset else "    [ -- ]    "
    silent_tag = " (SILENCE)" if metrics.is_silent else ""

    lines = [
        f"Device:       {device_name}",
        f"Loudness:     {make_bar(metrics.loudness)}{silent_tag}",
        f"RMS:          {make_bar(metrics.rms)}",
        f"Bass (20-250) {make_bar(metrics.bass)}",
        f"Mid (250-4k)  {make_bar(metrics.mid)}",
        f"Treble (4-16k){make_bar(metrics.treble)}",
        f"Onset:        {onset_tag} (Strength: {metrics.onset_strength:.2f})",
        (
            f"Telemetry:    {stats.sample_rate}Hz | "
            f"FPS: {stats.fps:4.1f} | "
            f"Latency: {stats.estimated_latency_ms:4.1f}ms | "
            f"DSP: {stats.analysis_time_ms:3.1f}ms | "
            f"Dropped: {stats.dropped_frames}"
        ),
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WiZ Music Sync — Real-Time Windows Audio Diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio output device index to capture. Defaults to active system output.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all compatible Windows audio output loopback devices and exit.",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=1024,
        help="Audio buffer size in frames (default: 1024).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )
    return parser.parse_args()


def select_device(preferred_index: Optional[int]) -> Optional[AudioDevice]:
    devices = get_audio_output_devices()
    if not devices:
        print("[ERROR] No compatible Windows audio output loopback devices found.")
        print("        Ensure Windows Audio service is running and audio hardware is enabled.")
        return None

    if preferred_index is not None:
        target = get_device_by_index(preferred_index)
        if target:
            return target
        print(f"[WARNING] Device index {preferred_index} not found. Available devices:\n")

    print("\nAvailable Windows Audio Output Loopback Devices:")
    print("-" * 65)
    default_dev: Optional[AudioDevice] = None
    for dev in devices:
        if dev.is_default:
            default_dev = dev
        print(f"  {dev}")
    print("-" * 65)

    if preferred_index is not None:
        return None

    if default_dev:
        print(f"\nDefault active device: {default_dev.clean_name()} (Index {default_dev.index})")
    
    try:
        user_choice = input(
            f"\nEnter device index to capture [Press Enter for default ({default_dev.index if default_dev else 0})]: "
        ).strip()
        if not user_choice and default_dev:
            return default_dev
        if user_choice:
            idx = int(user_choice)
            chosen = get_device_by_index(idx)
            if chosen:
                return chosen
            print(f"[ERROR] Invalid device index: {idx}")
            return None
    except (ValueError, EOFError, KeyboardInterrupt):
        return default_dev

    return default_dev


def main() -> int:
    args = parse_args()
    setup_logging(verbose=args.verbose)

    if args.list_devices:
        devices = get_audio_output_devices()
        print("\nAvailable Windows Audio Output Loopback Devices:")
        print("=" * 65)
        for dev in devices:
            print(f"  {dev}")
        print("=" * 65)
        return 0

    target_device = select_device(args.device)
    if not target_device:
        print("[ERROR] Could not select a valid audio output device.")
        return 1

    print("\n" + "=" * 65)
    print("      WiZ Music Sync — Real-Time Audio Diagnostics")
    print("=" * 65)
    print(f"Selected Device:  {target_device.clean_name()}")
    print(f"Sample Rate:      {target_device.sample_rate} Hz")
    print(f"Channels:         {target_device.channels}")
    print(f"Buffer Size:      {args.buffer_size} frames")
    print("Press Ctrl+C to stop capture.")
    print("=" * 65 + "\n")

    latest_data = {"metrics": None, "stats": None}

    def on_metrics_received(metrics: AudioMetrics, stats: CaptureStats) -> None:
        latest_data["metrics"] = metrics
        latest_data["stats"] = stats

    capture = AudioCapture(
        device=target_device,
        frames_per_buffer=args.buffer_size,
        on_metrics=on_metrics_received,
    )

    try:
        capture.start()
        last_render_time = time.perf_counter()
        refresh_interval = 0.05  # ~20 Hz display refresh

        while True:
            time.sleep(0.01)
            now = time.perf_counter()
            if now - last_render_time >= refresh_interval:
                m = latest_data["metrics"]
                s = latest_data["stats"]
                if m is not None and s is not None:
                    # Move cursor up 8 lines and rewrite
                    block = format_diagnostics(m, s, target_device.clean_name())
                    # Write block with carriage returns
                    sys.stdout.write(f"\r\033[K{block}\n\033[8A")
                    sys.stdout.flush()
                last_render_time = now

    except KeyboardInterrupt:
        print("\n\nStopping audio capture...")
    finally:
        capture.stop()
        print("Audio diagnostics stopped cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
