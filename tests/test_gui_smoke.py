from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

from opencover.config import Settings
from opencover.core.hardware_detector import HardwareInfo
from opencover.paths import AppPaths
from opencover.storage.database import Database
from opencover.ui.main_window import MainWindow
from opencover.ui.widgets import AudioPlayer


def test_main_window_constructs(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths(tmp_path, tmp_path / "workspace", tmp_path / "weights", tmp_path / "assets", tmp_path / "config", tmp_path / "external_backends", tmp_path / "ffmpeg")
    paths.ensure()
    hardware = HardwareInfo("Windows", "CPU", 16, "Test GPU", 8, "1", "12.1", None, "标准")
    window = MainWindow(paths, Settings(), hardware, Database(paths.workspace / "db.sqlite"))
    qtbot.addWidget(window)
    assert window.windowTitle() == "OpenCover Studio"
    assert window.jobs.root == tmp_path
    assert set(window.pages) == {"首页", "原词翻唱", "改词翻唱 Beta", "音色管理", "任务记录", "组件管理", "设置"}
    history = window.pages["任务记录"]
    labels = {button.text() for button in history.findChildren(QPushButton)}
    assert {"重新生成", "更换音色生成"} <= labels


def test_audio_player_exposes_working_volume_slider(qtbot) -> None:  # type: ignore[no-untyped-def]
    player = AudioPlayer()
    qtbot.addWidget(player)
    assert player.volume.value() == 65
    player.volume.setValue(20)
    assert abs(player.output.volume() - 0.2) < 0.001
