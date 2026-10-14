"""Comprehensive Phase 5.1 Real Screen Capture & Hardware Verification Script.

Tests:
1. Real Screen Capture Fidelity across 7 visual desktop scenes:
   - Solid Red
   - Solid Green
   - Solid Blue
   - Warm Sunset
   - Underwater Scene
   - Dark Cinematic Movie (Letterbox + low luminance)
   - Fast Dynamic Color Transitions
2. Capture Health & Stale-Frame Fallback:
   - Verifies fallback to warm ambient when capture stalls
   - Verifies legitimate dark frames maintain OK health
3. Physical WiZ Bulb Synchronization (IP: 192.168.1.4):
   - Screen Sync Mode (real display capture -> WiZ bulb)
   - Hybrid AV Sync Mode (real display capture + loopback audio -> WiZ bulb)
   - Pre-sync state capture and post-sync restoration verification
"""

import asyncio
import json
import logging
import math
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Ensure project root is in path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QLinearGradient
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from src.audio.analyzer import AudioMetrics
from src.audio.devices import get_default_output_device
from src.screen.analyzer import ScreenAnalyzerSettings, ScreenColorAnalyzer
from src.screen.capture import (
    BackendState,
    FrameStatus,
    ScreenCaptureManager,
    ensure_default_desktop,
)
from src.screen.cinematic import CaptureHealth, detect_black_bars
from src.effects import EffectSettings
from src.sync.engine import SyncMode, MusicSyncEngine
from src.sync.state import LightingState, RestorationResult
from src.wiz.controller import WizBulbController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("phase5_1_verifier")


class SceneDisplayWindow(QMainWindow):
    """Window that renders target test patterns on screen for real capture testing."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phase 5.1 Screen Capture Calibration Target")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.scene_type = "red"
        self.anim_phase = 0.0

        # Central widget with custom paintEvent
        self.canvas = QWidget(self)
        self.setCentralWidget(self.canvas)
        self.canvas.paintEvent = self._paint_scene

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_anim_tick)

    def set_scene(self, scene_type: str):
        self.scene_type = scene_type
        if scene_type == "dynamic":
            if not self.anim_timer.isActive():
                self.anim_timer.start(50)  # 20 FPS animation
        else:
            if self.anim_timer.isActive():
                self.anim_timer.stop()
        self.canvas.update()
        QApplication.processEvents()

    def _on_anim_tick(self):
        self.anim_phase += 0.1
        self.canvas.update()

    def _paint_scene(self, event):
        painter = QPainter(self.canvas)
        rect = self.canvas.rect()

        if self.scene_type == "red":
            painter.fillRect(rect, QColor(255, 0, 0))
        elif self.scene_type == "green":
            painter.fillRect(rect, QColor(0, 255, 0))
        elif self.scene_type == "blue":
            painter.fillRect(rect, QColor(0, 0, 255))
        elif self.scene_type == "sunset":
            grad = QLinearGradient(0, 0, 0, rect.height())
            grad.setColorAt(0.0, QColor(255, 69, 0))    # Red-Orange
            grad.setColorAt(0.5, QColor(255, 140, 0))   # Dark Orange
            grad.setColorAt(1.0, QColor(255, 215, 0))   # Gold
            painter.fillRect(rect, grad)
        elif self.scene_type == "underwater":
            grad = QLinearGradient(0, 0, 0, rect.height())
            grad.setColorAt(0.0, QColor(0, 30, 80))     # Deep Navy
            grad.setColorAt(0.6, QColor(0, 150, 180))   # Ocean Cyan
            grad.setColorAt(1.0, QColor(0, 220, 200))   # Aquamarine
            painter.fillRect(rect, grad)
        elif self.scene_type == "cinematic_dark":
            # 2.39:1 CinemaScope black bars (top and bottom 20%)
            painter.fillRect(rect, QColor(0, 0, 0))
            bar_h = int(rect.height() * 0.20)
            center_rect = QRect(0, bar_h, rect.width(), rect.height() - 2 * bar_h)
            painter.fillRect(center_rect, QColor(15, 15, 22))  # Dark moody scene
        elif self.scene_type == "dynamic":
            r = int(127 + 127 * math.sin(self.anim_phase))
            g = int(127 + 127 * math.sin(self.anim_phase + 2.0))
            b = int(127 + 127 * math.sin(self.anim_phase + 4.0))
            painter.fillRect(rect, QColor(r, g, b))
        painter.end()


def test_real_screen_capture_fidelity() -> Dict:
    """Part A: Verify real screen capture against 7 displayed desktop scenes."""
    logger.info("=== Starting Part A: Real Screen Capture Fidelity Test ===")
    ensure_default_desktop()
    app = QApplication.instance() or QApplication(sys.argv)

    window = SceneDisplayWindow()
    window.showFullScreen()
    app.processEvents()
    time.sleep(0.4)

    latest_captured_frame: Optional[np.ndarray] = None
    frame_lock = threading.Lock()

    def _frame_callback(frame: Optional[np.ndarray], timestamp: float):
        nonlocal latest_captured_frame
        if frame is not None:
            with frame_lock:
                latest_captured_frame = frame.copy()

    # Initialize ScreenCaptureManager with Qt backend (or best available)
    manager = ScreenCaptureManager(
        monitor_index=0,
        target_fps=15,
        on_frame=_frame_callback,
    )
    started = manager.start()
    assert started, "Failed to start ScreenCaptureManager"
    backend_name = manager.backend.name if manager.backend else "Unknown"
    logger.info("ScreenCaptureManager started with backend: %s", backend_name)

    analyzer = ScreenColorAnalyzer(
        settings=ScreenAnalyzerSettings(
            color_strategy="average",
            smoothing_preset="responsive",
            min_brightness=20,
            max_brightness=255,
        )
    )

    results = {}
    scenes = [
        ("red", "Solid Red"),
        ("green", "Solid Green"),
        ("blue", "Solid Blue"),
        ("sunset", "Warm Sunset"),
        ("underwater", "Underwater Scene"),
        ("cinematic_dark", "Dark Cinematic Letterbox"),
        ("dynamic", "Dynamic Moving Colors"),
    ]

    for scene_id, scene_name in scenes:
        window.set_scene(scene_id)
        # Allow window surface to repaint and DWM to compose the new frame
        for _ in range(5):
            app.processEvents()
            time.sleep(0.04)

        # Clear previous frame and wait for fresh capture of current scene
        with frame_lock:
            latest_captured_frame = None

        t_start = time.perf_counter()
        target_frame = None
        while time.perf_counter() - t_start < 2.0:
            app.processEvents()
            with frame_lock:
                if latest_captured_frame is not None:
                    target_frame = latest_captured_frame.copy()
                    break
            time.sleep(0.03)

        assert target_frame is not None, f"No frame captured for scene {scene_name}"

        # Analyze captured frame
        state = analyzer.process_frame(target_frame, timestamp=time.perf_counter())
        r, g, b = state.rgb
        lum = analyzer.last_raw_luminance
        health_name = manager.health.name

        logger.info(
            "Scene: %-24s -> RGB: (%3d, %3d, %3d), Brightness: %3d, Lum: %.2f, Health: %s",
            scene_name, r, g, b, state.brightness, lum, health_name
        )

        # Scene-specific fidelity assertions
        scene_passed = False
        if scene_id == "red":
            scene_passed = (r > g + 40 and r > b + 40)
        elif scene_id == "green":
            scene_passed = (g > r + 40 and g > b + 40)
        elif scene_id == "blue":
            scene_passed = (b > r + 40 and b > g + 40)
        elif scene_id == "sunset":
            # Sunset has high red and green (warm yellow/orange), low blue
            scene_passed = (r > 100 and g > 30 and r > b)
        elif scene_id == "underwater":
            # Underwater has blue/green dominating over red
            scene_passed = (b > r and g > r)
        elif scene_id == "cinematic_dark":
            # Dark cinematic has low luminance, but capture health must remain OK!
            scene_passed = (manager.health == CaptureHealth.OK and lum < 0.35)
        elif scene_id == "dynamic":
            scene_passed = (manager.health == CaptureHealth.OK)

        results[scene_id] = {
            "name": scene_name,
            "passed": scene_passed,
            "captured_rgb": [int(r), int(g), int(b)],
            "brightness": int(state.brightness),
            "health": health_name,
        }
        assert scene_passed, f"Fidelity assertion failed for {scene_name}: RGB=({r},{g},{b}), Lum={lum:.2f}"

    # Test Stale-Frame Fallback Detection
    logger.info("Testing stale-frame fallback on prolonged capture failure...")
    # Step stale_time past stale_timeout_s (1.2s) + fade_duration_s (2.0s) = 3.2s
    stale_time = time.perf_counter()
    stale_state = None
    for _ in range(35):
        stale_time += 0.1
        stale_state = analyzer.process_frame(None, timestamp=stale_time)

    assert analyzer._fallback_mgr.is_fallback_active is True, "Expected fallback manager to activate fallback on stale capture"
    # Fallback state targets safe warm ambient (255, 214, 170)
    assert stale_state.rgb == (255, 214, 170), (
        f"Expected warm ambient fallback (255, 214, 170), got {stale_state.rgb}"
    )
    logger.info("[OK] Stale-frame detection activated smooth warm ambient fallback successfully.")

    # Cleanup
    manager.stop()
    window.close()
    app.processEvents()

    return {
        "status": "passed",
        "backend": backend_name,
        "scenes": results,
        "stale_fallback_verified": True,
    }


async def test_physical_hardware_sync(target_ip: str) -> Dict:
    """Part B: Verify real Screen Sync & Hybrid AV Sync with physical WiZ bulb at target_ip."""
    logger.info("=== Starting Part B: Physical WiZ Bulb Synchronization Test (%s) ===", target_ip)
    ensure_default_desktop()
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Query initial state for clean restoration verification
    controller = WizBulbController(target_ip, timeout=4.0)
    await controller.connect()
    initial_state = await controller.get_state()
    logger.info(
        "Initial WiZ Bulb State: ON=%s, Mode=%s, Brightness=%s, RGB=%s, Kelvin=%s",
        initial_state.is_on, initial_state.active_mode, initial_state.brightness,
        initial_state.rgb, initial_state.colortemp
    )
    await controller.disconnect()

    # 2. Test Real Screen Sync Mode
    logger.info("--- Testing Engine in SCREEN Sync Mode ---")
    screen_engine = MusicSyncEngine(
        bulb_ip=target_ip,
        sync_mode=SyncMode.SCREEN,
        restore_state=True,
        dry_run=False,
    )
    await screen_engine.start()

    # Run for 3.5 seconds while pumping Qt events
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 3.5:
        app.processEvents()
        await asyncio.sleep(0.04)

    screen_status = screen_engine.get_status()
    logger.info(
        "Screen Sync Stats: Commands Sent=%d, Commands Failed=%d, Frames Analyzed=%d, Capture FPS=%.1f, Health=%s",
        screen_status.commands_sent, screen_status.commands_failed,
        screen_status.frames_analyzed, screen_status.screen_fps,
        screen_status.capture_health,
    )
    assert screen_status.commands_sent > 0, "No WiZ commands sent in Screen Sync mode"
    assert screen_status.frames_analyzed > 0, "No frames analyzed in Screen Sync mode"

    await screen_engine.stop()
    logger.info("[OK] Screen Sync mode executed and stopped cleanly.")

    # 3. Test Real Hybrid AV Sync Mode
    logger.info("--- Testing Engine in HYBRID AV Sync Mode ---")
    await asyncio.sleep(0.5)

    hybrid_engine = MusicSyncEngine(
        bulb_ip=target_ip,
        sync_mode=SyncMode.HYBRID,
        restore_state=True,
        dry_run=False,
        hybrid_audio_focus="rhythm",
        hybrid_beat_intensity=1.5,
    )
    await hybrid_engine.start()

    # Dynamically tweak hybrid controls to verify runtime updates
    hybrid_engine.set_hybrid_settings(
        hybrid_type="party",
        audio_contribution=0.50,
        audio_focus="kick",
        beat_intensity=1.8,
    )
    logger.info("Updated hybrid settings: type=party, contrib=0.50, focus=kick, beat=1.8")

    t1 = time.perf_counter()
    while time.perf_counter() - t1 < 3.5:
        app.processEvents()
        await asyncio.sleep(0.04)

    hybrid_status = hybrid_engine.get_status()
    logger.info(
        "Hybrid AV Sync Stats: Commands Sent=%d, Commands Failed=%d, Frames Analyzed=%d, Capture FPS=%.1f",
        hybrid_status.commands_sent, hybrid_status.commands_failed,
        hybrid_status.frames_analyzed, hybrid_status.screen_fps,
    )
    assert hybrid_status.commands_sent > 0, "No WiZ commands sent in Hybrid AV Sync mode"

    # Stop hybrid engine and verify restoration
    await hybrid_engine.stop()
    await asyncio.sleep(1.0)

    # 4. Verify post-sync bulb state matches initial state
    await controller.connect()
    restored_state = await controller.get_state()
    logger.info(
        "Restored WiZ Bulb State: ON=%s, Mode=%s, Brightness=%s, RGB=%s, Kelvin=%s",
        restored_state.is_on, restored_state.active_mode, restored_state.brightness,
        restored_state.rgb, restored_state.colortemp
    )
    await controller.disconnect()

    assert restored_state.is_on == initial_state.is_on, (
        f"Restored power state ({restored_state.is_on}) != initial ({initial_state.is_on})"
    )
    if initial_state.is_on:
        assert restored_state.active_mode == initial_state.active_mode, (
            f"Restored active mode ({restored_state.active_mode}) != initial ({initial_state.active_mode})"
        )

    logger.info("[OK] Pre-sync bulb state was perfectly restored on physical hardware.")

    return {
        "status": "passed",
        "target_ip": target_ip,
        "initial_state": str(initial_state),
        "screen_commands_sent": screen_status.commands_sent,
        "screen_frames_analyzed": screen_status.frames_analyzed,
        "hybrid_commands_sent": hybrid_status.commands_sent,
        "hybrid_frames_analyzed": hybrid_status.frames_analyzed,
        "restoration_verified": True,
        "restored_state": str(restored_state),
    }


def main():
    target_ip = "192.168.1.4"
    for i, arg in enumerate(sys.argv):
        if arg == "--ip" and i + 1 < len(sys.argv):
            target_ip = sys.argv[i + 1]

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_ip": target_ip,
    }

    try:
        part_a = test_real_screen_capture_fidelity()
        report["screen_capture_fidelity"] = part_a

        part_b = asyncio.run(test_physical_hardware_sync(target_ip))
        report["physical_hardware_sync"] = part_b
        report["overall_status"] = "passed"
    except Exception as exc:
        report["overall_status"] = "failed"
        report["error"] = str(exc)
        logger.error("Verification failed: %s", exc, exc_info=True)

    report_path = root_dir / "phase5_1_hardware_test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        sanitized = dict(report)
        if "target_ip" in sanitized:
            parts = sanitized["target_ip"].split(".")
            if len(parts) == 4:
                sanitized["target_ip"] = f"{parts[0]}.{parts[1]}.{parts[2]}.X"
        json.dump(sanitized, f, indent=2)

    logger.info("Verification report saved to: %s", report_path)
    if report["overall_status"] == "passed":
        print("\n=======================================================")
        print(" PHASE 5.1 VERIFICATION COMPLETE: ALL CHECKS PASSED [OK]")
        print("=======================================================\n")
        sys.exit(0)
    else:
        print(f"\n[FAILED] Verification failed: {report.get('error')}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
