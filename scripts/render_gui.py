from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from opencover.config import Settings
from opencover.core.hardware_detector import detect_hardware
from opencover.paths import AppPaths
from opencover.storage.database import Database
from opencover.ui.main_window import MainWindow
from opencover.ui.styles import APP_QSS


def main() -> int:
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(APP_QSS)
    paths = AppPaths.discover(); paths.ensure()
    ffmpeg = next(paths.ffmpeg.glob("*/bin/ffmpeg.exe"), None)
    window = MainWindow(paths, Settings(), detect_hardware(str(ffmpeg) if ffmpeg else None), Database(paths.workspace / "render.sqlite"))
    window.resize(1180, 760); window.show()
    output = paths.workspace / "gui-home.png"
    def capture() -> None:
        window.grab().save(str(output), "PNG")
        print(output)
        app.quit()
    QTimer.singleShot(800, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
