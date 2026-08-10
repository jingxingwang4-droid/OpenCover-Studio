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
    database = Database(paths.workspace / "db.sqlite")
    database.create_job({"id": "recent", "kind": "original", "input_path": "中文歌曲.wav", "engine": "rvc", "model_id": "voice", "options": {}})
    database.update_job("recent", status="completed", progress=100, output_path="result.wav")
    settings = Settings(minimize_to_tray=False)
    window = MainWindow(paths, settings, hardware, database)
    qtbot.addWidget(window)
    assert window.windowTitle() == "OpenCover Studio"
    assert window.jobs.root == tmp_path
    assert set(window.pages) == {"首页", "原词翻唱", "改词翻唱 Beta", "音色管理", "任务记录", "组件管理", "设置"}
    history = window.pages["任务记录"]
    labels = {button.text() for button in history.findChildren(QPushButton)}
    assert {"重新生成", "更换音色生成"} <= labels
    home = window.pages["首页"]
    assert "中文歌曲.wav" in home.recent.text()
    cover = window.pages["原词翻唱"]
    selected = tmp_path / "输入.wav"; selected.write_bytes(b"exists")
    cover.drop.set_path(selected)
    assert cover.input_player.play.isEnabled()
    lyric = window.pages["改词翻唱 Beta"]
    lyric.drop.set_path(selected)
    assert lyric.input_player.play.isEnabled()
    settings_page = window.pages["设置"]
    settings_page.profile.setCurrentText("低")
    assert settings.memory_profile == "低"
    assert Settings.load(paths.workspace / "settings.json").memory_profile == "低"


def test_audio_player_exposes_working_volume_slider(qtbot) -> None:  # type: ignore[no-untyped-def]
    player = AudioPlayer()
    qtbot.addWidget(player)
    assert player.volume.value() == 65
    player.volume.setValue(20)
    assert abs(player.output.volume() - 0.2) < 0.001
