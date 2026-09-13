"""Use the same fonts and appearance in the desktop app and GUI validation."""
import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from .styles import APP_QSS


def apply_theme(app: QApplication) -> None:
    # Qt's offscreen plugin does not discover Windows fallback fonts reliably.
    if os.name == "nt":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc"):
            path = fonts / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
