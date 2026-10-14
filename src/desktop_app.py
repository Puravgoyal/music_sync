import asyncio
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Optional

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.screen.capture import ensure_default_desktop
from src.sync.state import RestorationResult
from src.ui.main_window import MainWindow
from src.ui.workers.sync_worker import SyncState
from src.wiz.controller import WizBulbController

logger = logging.getLogger("wiz_music_sync")


def load_stylesheet() -> str:
    """Load dark theme stylesheet from UI resources, checking PyInstaller bundle directory."""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    candidates = [
        base_dir / "src" / "ui" / "themes" / "dark.qss",
        base_dir / "ui" / "themes" / "dark.qss",
        Path(__file__).parent / "ui" / "themes" / "dark.qss",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as exc:
                logger.warning("Could not load stylesheet from %s: %s", candidate, exc)
    return ""


def run_gui_smoke_test(diag_file: Optional[Path] = None) -> int:
    """Execute a comprehensive GUI smoke test in packaged or dev environments:

    - Initializes QApplication
    - Loads bundled stylesheet
    - Constructs MainWindow
    - Confirms primary widgets initialize
    - Processes Qt events
    - Closes window cleanly
    - Verifies background worker thread shutdown
    - Writes diagnostic report to disk (essential for windowed executables without stdout)
    - Returns exit code 0 on success, 1 on failure
    """
    diagnostics = {
        "status": "failed",
        "qapp_initialized": False,
        "stylesheet_loaded": False,
        "main_window_created": False,
        "widgets_verified": False,
        "events_processed": False,
        "window_closed": False,
        "threads_terminated": False,
        "error": None,
    }

    try:
        ensure_default_desktop()
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication.instance() or QApplication([sys.argv[0]])
        diagnostics["qapp_initialized"] = True

        qss = load_stylesheet()
        if qss:
            app.setStyleSheet(qss)
            diagnostics["stylesheet_loaded"] = True

        # Construct MainWindow without auto-starting hardware sync
        window = MainWindow()
        diagnostics["main_window_created"] = True

        # Confirm all primary widgets initialized properly
        assert window.device_panel is not None, "device_panel not initialized"
        assert window.screen_panel is not None, "screen_panel not initialized"
        assert window.audio_panel is not None, "audio_panel not initialized"
        assert window.status_panel is not None, "status_panel not initialized"
        assert window.spectrum_view is not None, "spectrum_view not initialized"
        assert window.effects_panel is not None, "effects_panel not initialized"
        assert window.hybrid_panel is not None, "hybrid_panel not initialized"
        diagnostics["widgets_verified"] = True

        window.show()
        # Process pending Qt events to ensure geometry and layout complete
        app.processEvents()
        diagnostics["events_processed"] = True

        # Cleanly close window
        window.close()
        for _ in range(5):
            app.processEvents()
            time.sleep(0.02)
        diagnostics["window_closed"] = True

        # Verify background worker thread shutdown
        worker_thread = window.worker.thread
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=2.0)
            assert not worker_thread.is_alive(), "Worker thread failed to terminate after window close!"
        diagnostics["threads_terminated"] = True
        diagnostics["status"] = "passed"

    except Exception as exc:
        diagnostics["error"] = str(exc)
        logger.error("GUI smoke test failed: %s", exc, exc_info=True)

    if diag_file:
        try:
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, indent=2)
        except Exception as e:
            logger.warning("Failed writing smoke test diagnostics to %s: %s", diag_file, e)

    try:
        if diagnostics["status"] == "passed":
            print("GUI SMOKE TEST PASSED: All primary widgets and thread termination verified.")
        else:
            print(f"GUI SMOKE TEST FAILED: {diagnostics['error']}")
    except Exception:
        pass

    return 0 if diagnostics["status"] == "passed" else 1


def run_gui_hardware_test(target_ip: str, diag_file: Optional[Path] = None, run_duration: float = 6.0) -> int:
    """Execute an end-to-end GUI hardware test against physical bulb with packaged/dev app."""
    diagnostics = {
        "status": "failed",
        "target_ip": target_ip,
        "qapp_initialized": False,
        "stylesheet_loaded": False,
        "main_window_created": False,
        "connection_tested": False,
        "sync_started": False,
        "audio_frames_processed": 0,
        "commands_sent": 0,
        "effect_switched": False,
        "sync_stopped": False,
        "restoration_result": "NONE",
        "restoration_details": "",
        "restoration_verified": False,
        "threads_terminated": False,
        "error": None,
    }

    try:
        ensure_default_desktop()
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv if sys.argv else ["WiZMusicSync"])
        diagnostics["qapp_initialized"] = True

        qss = load_stylesheet()
        if qss:
            app.setStyleSheet(qss)
            diagnostics["stylesheet_loaded"] = True

        window = MainWindow()
        diagnostics["main_window_created"] = True

        # Capture initial state for post-test restoration verification
        async def _query_state(ip: str):
            c = WizBulbController(ip)
            await c.connect()
            st = await c.get_state()
            await c.disconnect()
            return st

        initial_state = asyncio.run(_query_state(target_ip))

        # Configure bulb IP
        window.device_panel.set_manual_ip(target_ip)
        window.show()
        app.processEvents()

        # Test UDP connection
        window.worker.test_connection(target_ip)
        t_wait_test = time.perf_counter()
        while time.perf_counter() - t_wait_test < 4.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.last_test_success is not None:
                if window.worker.last_test_success is True:
                    diagnostics["connection_tested"] = True
                break
        assert diagnostics["connection_tested"] is True, f"Bulb connection test failed or timed out: {window.worker.last_test_message}"

        # Ensure default loopback device is selected on audio panel
        from src.audio.devices import get_default_output_device
        def_dev = get_default_output_device()
        if def_dev:
            window.audio_panel.refresh_devices(preferred_name=def_dev.name)
        selected_dev = window.audio_panel.get_selected_device()
        clean_name = selected_dev.clean_name() if selected_dev else None

        # Feed test audio pulses so loopback capture has active audio frames during test
        stop_audio = threading.Event()
        def _feed_test_audio():
            try:
                import pyaudiowpatch as pyaudio
                import numpy as np
                pa = pyaudio.PyAudio()
                target_idx = None
                for i in range(pa.get_device_count()):
                    d = pa.get_device_info_by_index(i)
                    if d.get("maxOutputChannels", 0) > 0 and (not clean_name or clean_name.lower() in d["name"].lower()):
                        target_idx = i
                        break
                if target_idx is None:
                    target_idx = pa.get_default_output_device_info()["index"]

                out_info = pa.get_device_info_by_index(target_idx)
                rate = int(out_info["defaultSampleRate"])
                channels = min(2, int(out_info.get("maxOutputChannels", 2)))
                st = pa.open(format=pyaudio.paFloat32, channels=channels, rate=rate, output=True, output_device_index=target_idx)
                t_tone = np.linspace(0, 0.1, int(rate * 0.1), endpoint=False)
                mono = (0.25 * np.sin(2 * np.pi * 100.0 * t_tone)).astype(np.float32)
                samples = np.column_stack([mono, mono]).ravel() if channels == 2 else mono
                while not stop_audio.is_set():
                    st.write(samples.tobytes())
                st.stop_stream()
                st.close()
                pa.terminate()
            except Exception as e:
                logger.error("Test audio playback error: %s", e)

        audio_th = threading.Thread(target=_feed_test_audio, daemon=True)
        audio_th.start()

        # Ensure initial effect is Spectrum RGB
        window.effects_panel.set_selected_effect("spectrum")

        # Start sync
        window._on_start_sync()
        t_wait_start = time.perf_counter()
        while time.perf_counter() - t_wait_start < 8.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.RUNNING:
                diagnostics["sync_started"] = True
                break

        assert window.worker.state == SyncState.RUNNING, "Worker failed to reach RUNNING state"

        # Let it run for half duration
        half = max(2.0, run_duration / 2.0)
        t_run1 = time.perf_counter()
        while time.perf_counter() - t_run1 < half:
            app.processEvents()
            time.sleep(0.05)

        # Switch effect to "beat"
        window.effects_panel.set_selected_effect("beat")
        t_wait_eff = time.perf_counter()
        while time.perf_counter() - t_wait_eff < 3.0:
            app.processEvents()
            time.sleep(0.05)
            engine = getattr(window.worker, "_engine", None)
            if engine:
                eff = getattr(engine, "current_effect", None)
                if eff and getattr(eff, "name", "") == "Beat Pulse":
                    diagnostics["effect_switched"] = True
                    break
        assert diagnostics["effect_switched"] is True, "Engine did not verify active effect changed to Beat Pulse"

        # Switch focus to "rhythm"
        window.effects_panel.set_audio_focus("rhythm")
        diagnostics["focus_mode"] = window.effects_panel.get_audio_focus()

        t_run2 = time.perf_counter()
        while time.perf_counter() - t_run2 < half:
            app.processEvents()
            time.sleep(0.05)

        # Verify real audio frames processed & commands sent
        status, metrics, stats = window.worker.get_telemetry_snapshot()
        frames_proc = stats.frames_processed if stats else 0
        cmds_sent = status.commands_sent if status else 0
        diagnostics["audio_frames_processed"] = frames_proc
        diagnostics["commands_sent"] = cmds_sent
        assert frames_proc > 0, f"No audio frames were processed during sync (frames: {frames_proc})"
        assert cmds_sent > 0, f"No WiZ network commands were sent during sync (commands: {cmds_sent})"

        # Stop Music sync
        stop_audio.set()
        window._on_stop_sync()
        t_wait_stop = time.perf_counter()
        while time.perf_counter() - t_wait_stop < 5.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.IDLE:
                diagnostics["sync_stopped"] = True
                break
        assert window.worker.state == SyncState.IDLE, "Worker failed to return to IDLE state"

        # Phase 2: Screen Sync Mode
        screen_idx = window.source_combo.findData("screen")
        if screen_idx >= 0:
            window.source_combo.setCurrentIndex(screen_idx)
        window._on_start_sync()
        t_wait_scr = time.perf_counter()
        while time.perf_counter() - t_wait_scr < 6.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.RUNNING:
                diagnostics["screen_sync_started"] = True
                break
        assert window.worker.state == SyncState.RUNNING, "Worker failed to reach RUNNING state in Screen mode"

        t_scr_run = time.perf_counter()
        while time.perf_counter() - t_scr_run < 3.0:
            app.processEvents()
            time.sleep(0.05)

        scr_status, _, _ = window.worker.get_telemetry_snapshot()
        diagnostics["screen_frames_analyzed"] = scr_status.frames_analyzed if scr_status else 0
        diagnostics["screen_commands_sent"] = scr_status.commands_sent if scr_status else 0
        assert (scr_status and scr_status.commands_sent > 0), "No commands sent in Screen mode"

        window._on_stop_sync()
        t_wait_stop = time.perf_counter()
        while time.perf_counter() - t_wait_stop < 5.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.IDLE:
                break
        assert window.worker.state == SyncState.IDLE

        # Phase 3: Hybrid AV Sync Mode
        hyb_idx = window.source_combo.findData("hybrid")
        if hyb_idx >= 0:
            window.source_combo.setCurrentIndex(hyb_idx)
        window.hybrid_panel.set_audio_focus("kick")
        window.hybrid_panel.set_beat_intensity(1.8)
        window._on_start_sync()
        t_wait_hyb = time.perf_counter()
        while time.perf_counter() - t_wait_hyb < 6.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.RUNNING:
                diagnostics["hybrid_sync_started"] = True
                break
        assert window.worker.state == SyncState.RUNNING, "Worker failed to reach RUNNING state in Hybrid mode"

        t_hyb_run = time.perf_counter()
        while time.perf_counter() - t_hyb_run < 3.0:
            app.processEvents()
            time.sleep(0.05)

        hyb_status, _, _ = window.worker.get_telemetry_snapshot()
        diagnostics["hybrid_frames_analyzed"] = hyb_status.frames_analyzed if hyb_status else 0
        diagnostics["hybrid_commands_sent"] = hyb_status.commands_sent if hyb_status else 0
        assert (hyb_status and hyb_status.commands_sent > 0), "No commands sent in Hybrid mode"

        window._on_stop_sync()
        t_wait_stop = time.perf_counter()
        while time.perf_counter() - t_wait_stop < 5.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.IDLE:
                break
        assert window.worker.state == SyncState.IDLE

        resto = window.worker.last_restoration_report
        assert resto is not None and resto.result == RestorationResult.SUCCESS, f"Restoration report indicated non-success: {resto}"
        diagnostics["restoration_result"] = resto.result.value
        diagnostics["restoration_details"] = resto.details

        # Verify restored state matches initial
        post_state = asyncio.run(_query_state(target_ip))
        assert post_state.is_on == initial_state.is_on, f"Restored power state ({post_state.is_on}) does not match initial ({initial_state.is_on})"
        if initial_state.is_on:
            assert post_state.active_mode == initial_state.active_mode, f"Restored mode ({post_state.active_mode}) does not match initial ({initial_state.active_mode})"
        diagnostics["restoration_verified"] = True

        # Close window
        window.close()
        for _ in range(5):
            app.processEvents()
            time.sleep(0.02)

        worker_thread = window.worker.thread
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=2.0)
            assert not worker_thread.is_alive(), "Worker thread failed to terminate after window close"
        diagnostics["threads_terminated"] = True
        diagnostics["status"] = "passed"

    except Exception as exc:
        diagnostics["error"] = str(exc)
        logger.error("GUI hardware test failed: %s", exc, exc_info=True)

    if diag_file:
        try:
            out_diag = dict(diagnostics)
            if "target_ip" in out_diag and out_diag["target_ip"]:
                parts = str(out_diag["target_ip"]).split(".")
                if len(parts) == 4:
                    out_diag["target_ip"] = f"{parts[0]}.{parts[1]}.{parts[2]}.X"
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(out_diag, f, indent=2)
        except Exception as e:
            logger.warning("Failed writing hardware test diagnostics to %s: %s", diag_file, e)

    try:
        if diagnostics["status"] == "passed":
            print("GUI HARDWARE TEST PASSED: Discovery, capture, sync, mode switch, stop, and restoration verified.")
        else:
            print(f"GUI HARDWARE TEST FAILED: {diagnostics['error']}")
    except Exception:
        pass

    return 0 if diagnostics["status"] == "passed" else 1


def main() -> None:
    """Launch the WiZ Music Sync desktop GUI application."""
    if "--version" in sys.argv:
        print("WiZ Music Sync v1.0.0")
        return

    if "--smoke-test" in sys.argv:
        diag_path = None
        for i, arg in enumerate(sys.argv):
            if arg == "--diag-file" and i + 1 < len(sys.argv):
                diag_path = Path(sys.argv[i + 1])
                break
        if not diag_path:
            diag_path = Path("smoke_test_result.json")
        exit_code = run_gui_smoke_test(diag_path)
        sys.exit(exit_code)

    if "--hardware-test" in sys.argv:
        bulb_ip = None
        diag_path = Path("packaged_hardware_test_report.json")
        for i, arg in enumerate(sys.argv):
            if arg == "--hardware-test" and i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
                bulb_ip = sys.argv[i + 1]
            elif arg == "--diag-file" and i + 1 < len(sys.argv):
                diag_path = Path(sys.argv[i + 1])

        if not bulb_ip:
            from src.wiz.discovery import discover_devices
            print("No bulb IP specified. Discovering WiZ devices on local network...")
            devices = asyncio.run(discover_devices(timeout=2.5))
            if devices:
                bulb_ip = devices[0].ip
                print(f"Found WiZ bulb at {bulb_ip}")
            else:
                print("ERROR: No bulb IP specified and discovery found no WiZ bulbs on local network.")
                sys.exit(1)

        exit_code = run_gui_hardware_test(bulb_ip, diag_path)
        sys.exit(exit_code)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Enable High-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("WiZ Music Sync")
    app.setOrganizationName("Purav Goyal")

    qss = load_stylesheet()
    if qss:
        app.setStyleSheet(qss)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    # Bring window to foreground on Windows desktop
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

    if "--auto-start" in sys.argv or "--sync" in sys.argv:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, window._on_start_sync)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
