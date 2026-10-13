"""WiZ Music Sync — Desktop Application Entrypoint."""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow

logger = logging.getLogger("wiz_music_sync")


def load_stylesheet() -> str:
    """Load dark theme stylesheet from UI resources."""
    qss_path = Path(__file__).parent / "ui" / "themes" / "dark.qss"
    if qss_path.exists():
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.warning("Could not load stylesheet: %s", exc)
    return ""


def main() -> None:
    """Launch the WiZ Music Sync desktop GUI application."""
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
