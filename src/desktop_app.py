"""WiZ Music Sync — Desktop Application Entrypoint."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow

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


def main() -> None:
    """Launch the WiZ Music Sync desktop GUI application."""
    if "--version" in sys.argv:
        print("WiZ Music Sync v1.0.0")
        return

    if "--smoke-test" in sys.argv:
        print("SMOKE TEST OK")
        return

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
