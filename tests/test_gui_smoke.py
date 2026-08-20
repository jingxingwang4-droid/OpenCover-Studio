from pathlib import Path
import struct
import zipfile

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

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
    assert cover.source_voice.currentData() == "auto"
    lyric = window.pages["改词翻唱 Beta"]
    lyric.drop.set_path(selected)
    assert lyric.input_player.play.isEnabled()
    midi_events = b"\x00\x90\x3c\x64\x83\x60\x80\x3c\x00\x00\xff\x2f\x00"
    midi = tmp_path / "旋律.mid"
    midi.write_bytes(
        b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
        + b"MTrk" + struct.pack(">I", len(midi_events)) + midi_events
    )
    lyric.midi_path = midi; lyric.midi_file.setText(str(midi))
    assert lyric.midi_file.text() == str(midi)
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
