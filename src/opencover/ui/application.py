from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from opencover.config import Settings
from opencover.core.hardware_detector import detect_hardware
from opencover.logging_config import configure_logging
from opencover.paths import AppPaths
from opencover.storage.database import Database
from .main_window import MainWindow
from .styles import APP_QSS


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QCoreApplication.setOrganizationName("OpenCover Studio")
    QCoreApplication.setApplicationName("OpenCover Studio")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion"); app.setStyleSheet(APP_QSS)
    paths = AppPaths.discover(); paths.ensure(); configure_logging(paths.workspace / "logs")
    settings = Settings.load(paths.workspace / "settings.json")
    local_ffmpeg = paths.ffmpeg / "bin" / "ffmpeg.exe"
    if not local_ffmpeg.exists():
        local_ffmpeg = next(paths.ffmpeg.glob("*/bin/ffmpeg.exe"), local_ffmpeg)
    hardware = detect_hardware(str(local_ffmpeg) if local_ffmpeg.exists() else None)
    database = Database(paths.workspace / "opencover.db")
    window = MainWindow(paths, settings, hardware, database); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
