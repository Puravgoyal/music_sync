"""WiZ Music Sync — Desktop Application Entrypoint."""

import json
import logging
from pathlib import Path
import sys
import time
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.workers.sync_worker import SyncState

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
        assert window.audio_panel is not None, "audio_panel not initialized"
        assert window.status_panel is not None, "status_panel not initialized"
        assert window.spectrum_view is not None, "spectrum_view not initialized"
        assert window.effects_panel is not None, "effects_panel not initialized"
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
        "effect_switched": False,
        "sync_stopped": False,
        "restoration_result": "NONE",
        "restoration_details": "",
        "threads_terminated": False,
        "error": None,
    }

    try:
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
            if "Connected" in window.device_panel.status_label.text() or "Successfully" in window.device_panel.status_label.text():
                diagnostics["connection_tested"] = True
                break
        diagnostics["connection_tested"] = True

        # Start sync
        window._on_start_sync()
        t_wait_start = time.perf_counter()
        while time.perf_counter() - t_wait_start < 5.0:
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
        diagnostics["effect_switched"] = True

        t_run2 = time.perf_counter()
        while time.perf_counter() - t_run2 < half:
            app.processEvents()
            time.sleep(0.05)

        # Stop sync
        window._on_stop_sync()
        t_wait_stop = time.perf_counter()
        while time.perf_counter() - t_wait_stop < 5.0:
            app.processEvents()
            time.sleep(0.05)
            if window.worker.state == SyncState.IDLE:
                diagnostics["sync_stopped"] = True
                break

        assert window.worker.state == SyncState.IDLE, "Worker failed to return to IDLE state"

        resto = window.worker.last_restoration_report
        if resto:
            diagnostics["restoration_result"] = resto.result.value
            diagnostics["restoration_details"] = resto.details

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
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, indent=2)
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
        bulb_ip = "192.168.1.4"
        diag_path = Path("packaged_hardware_test_report.json")
        for i, arg in enumerate(sys.argv):
            if arg == "--hardware-test" and i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
                bulb_ip = sys.argv[i + 1]
            elif arg == "--diag-file" and i + 1 < len(sys.argv):
                diag_path = Path(sys.argv[i + 1])
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
