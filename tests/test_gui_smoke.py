from pathlib import Path
import zipfile

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

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
    database.create_job({"id": "interrupted", "kind": "original", "input_path": "中断.wav", "engine": "rvc", "model_id": "voice", "options": {}})
    database.update_job("interrupted", status="running", progress=30)
    (paths.assets / "背景1.jpg").write_bytes(b"local-background")
    settings = Settings(minimize_to_tray=False)
    window = MainWindow(paths, settings, hardware, database)
    qtbot.addWidget(window)
    assert window.windowTitle() == "OpenCover Studio"
    assert window.jobs.root == tmp_path
    assert window.jobs.recovered_jobs == 1
    assert "rgba(248, 249, 247, 174)" in window.stack.styleSheet()
    assert database.get_job("interrupted")["status"] == "failed"
    assert set(window.pages) == {"首页", "原词翻唱", "改词翻唱 Beta", "音色管理", "音色训练", "任务记录", "组件管理", "设置"}
    history = window.pages["任务记录"]
    labels = {button.text() for button in history.findChildren(QPushButton)}
    assert {"重新生成", "更换音色生成"} <= labels
    home = window.pages["首页"]
    assert "中文歌曲.wav" in home.recent.text()
    cover = window.pages["原词翻唱"]
    selected = tmp_path / "输入.wav"; selected.write_bytes(b"exists")
    cover.drop.set_path(selected)
    assert cover.input_player.play.isEnabled()
    assert cover.source_voice.currentData() == "auto"
    lyric = window.pages["改词翻唱 Beta"]
    lyric.drop.set_path(selected)
    assert lyric.input_player.play.isEnabled()
    assert lyric.generator_label.text() == "GAME + DiffSinger"
    assert '均衡句间音量' in lyric.workflow_note.text()
    assert lyric.engine.currentData() == "native"
    assert lyric.voice.currentData() == "diffsinger_native"
    assert not hasattr(lyric, "auto_lyrics")
    assert lyric.recognize.text() == "自动识别歌词"
    lyric.apply_recognized_lyrics("白马过了离原\n三月的天")
    assert lyric.original.toPlainText() == "白马过了离原\n三月的天"
    assert lyric.new.toPlainText() == lyric.original.toPlainText()
    assert not hasattr(lyric, "midi_file")
    assert not hasattr(lyric, "soulx_prompt_file")
    assert not hasattr(lyric, "soulx_target_file")
    settings_page = window.pages["设置"]
    settings_page.profile.setCurrentText("低")
    assert settings.memory_profile == "低"
    assert Settings.load(paths.workspace / "settings.json").memory_profile == "低"
    job_dir = paths.workspace / "jobs" / "recent"; job_dir.mkdir(parents=True)
    (job_dir / "request.json").write_text('{"kind":"original"}', encoding="utf-8")
    window.jobs._append_log("recent", "stderr", "测试错误\n")
    assert "[stderr] 测试错误" in (job_dir / "worker.log").read_text(encoding="utf-8")
    archive = tmp_path / "日志.zip"
    history._write_log_bundle(database.get_job("recent"), archive)
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"job.json", "request.json", "worker.log"}


def test_audio_player_exposes_working_volume_slider(qtbot) -> None:  # type: ignore[no-untyped-def]
    player = AudioPlayer()
    qtbot.addWidget(player)
    assert player.volume.value() == 65
    player.volume.setValue(20)
    assert abs(player.output.volume() - 0.2) < 0.001


def test_private_edition_replaces_lyric_feature_with_development_page(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths(
        tmp_path, tmp_path / "workspace", tmp_path / "weights", tmp_path / "assets",
        tmp_path / "config", tmp_path / "external_backends", tmp_path / "ffmpeg",
    )
    paths.ensure()
    (tmp_path / "PRIVATE_EDITION").write_text("v0.1测试版", encoding="utf-8")
    database = Database(paths.workspace / "db.sqlite")
    hardware = HardwareInfo("Windows", "CPU", 16, "Test GPU", 8, "1", "12.1", None, "标准")
    window = MainWindow(paths, Settings(minimize_to_tray=False), hardware, database)
    qtbot.addWidget(window)

    lyric = window.pages["改词翻唱 Beta"]
    assert lyric.__class__.__name__ == "LyricDevelopmentPage"
    assert "正在开发中" in {label.text() for label in lyric.findChildren(QLabel)}
    assert window.nav_buttons["改词翻唱 Beta"].text() == "改词翻唱"
    components = window.pages["组件管理"]
    assert components.table.rowCount() == 4


def test_clear_cache_preserves_legacy_uv_python(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths(
        tmp_path, tmp_path / "workspace", tmp_path / "weights", tmp_path / "assets",
        tmp_path / "config", tmp_path / "external_backends", tmp_path / "ffmpeg",
    )
    paths.ensure()
    database = Database(paths.workspace / "db.sqlite")
    hardware = HardwareInfo("Windows", "CPU", 16, "Test GPU", 8, "1", "12.1", None, "标准")
    window = MainWindow(paths, Settings(minimize_to_tray=False), hardware, database)
    qtbot.addWidget(window)
    cache = paths.workspace / "cache"
    (cache / "uv-python").mkdir()
    (cache / "uv-python" / "python.exe").write_bytes(b"runtime")
    (cache / "separation").mkdir()
    (cache / "separation" / "vocals.wav").write_bytes(b"cache")
    (cache / "voice_conversion").mkdir()
    (cache / "temporary.bin").write_bytes(b"cache")
    monkeypatch.setattr(
        "opencover.ui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr("opencover.ui.main_window.QMessageBox.information", lambda *args, **kwargs: None)

    history = window.pages["任务记录"]
    history._clear_cache()

    assert (cache / "uv-python" / "python.exe").read_bytes() == b"runtime"
    assert not (cache / "separation").exists()
    assert not (cache / "voice_conversion").exists()
    assert not (cache / "temporary.bin").exists()
