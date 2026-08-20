from __future__ import annotations

import os
import json
import shutil
import zipfile
from pathlib import Path

import yaml

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QCheckBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QInputDialog,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)

from opencover import __version__
from opencover.adapters.backends import AlignmentAdapter, DDSPAdapter, DiffSingerLegacyAdapter, EspnetVisinger2Adapter, GameAdapter, MSSTAdapter, RVCAdapter, Vevo2Adapter
from opencover.adapters.base import BackendStatus
from opencover.config import Settings
from opencover.core.hardware_detector import HardwareInfo
from opencover.core.job_manager import JobManager
from opencover.audio.processing import ffmpeg_path
from opencover.lyrics.midi import load_midi
from opencover.lyrics.processing import decode_lyrics_file
from opencover.models.importer import ModelImporter
from opencover.models.registry import ModelRegistry
from opencover.paths import AppPaths
from opencover.storage.database import Database
from .widgets import AudioDropArea, AudioPlayer, VoiceCard


NAV_ITEMS = ["首页", "原词翻唱", "改词翻唱 Beta", "音色管理", "任务记录", "组件管理", "设置"]


def panel_layout(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    page.setObjectName("ContentPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(14)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return page, layout


def pitch_selector() -> QComboBox:
    selector = QComboBox(); selector.addItem("自动（音色推荐）", None)
    for value in range(-12, 13):
        selector.addItem(f"{value:+d} 半音" if value else "0 半音", value)
    return selector


class HomePage(QWidget):
    navigate = Signal(str)
    import_requested = Signal()

    def __init__(self, hardware: HardwareInfo, paths: AppPaths, database: Database, registry: ModelRegistry):
        super().__init__(); self.database = database; self.registry = registry
        page, layout = panel_layout("OpenCover Studio", "本地、可审计的 AI 歌曲翻唱工作台")
        QVBoxLayout(self).addWidget(page)
        hero = QFrame(); hero.setObjectName("Hero")
        grid = QGridLayout(hero); grid.setContentsMargins(22, 20, 22, 20); grid.setSpacing(12)
        original = QPushButton("原词翻唱\n保留歌词，只更换演唱音色")
        original.setMinimumHeight(92); original.setObjectName("Primary")
        lyric = QPushButton("改词翻唱 Beta\n尽量保留旋律，替换歌词")
        lyric.setMinimumHeight(92)
        original.clicked.connect(lambda: self.navigate.emit("原词翻唱"))
        lyric.clicked.connect(lambda: self.navigate.emit("改词翻唱 Beta"))
        grid.addWidget(original, 0, 0); grid.addWidget(lyric, 0, 1)
        layout.addWidget(hero)
        status = QFrame(); status.setObjectName("Panel")
        status_layout = QGridLayout(status); status_layout.setContentsMargins(18, 16, 18, 16)
        status_layout.addWidget(QLabel("当前硬件"), 0, 0)
        status_layout.addWidget(QLabel(hardware.gpu or "未检测到 NVIDIA GPU"), 1, 0)
        status_layout.addWidget(QLabel("显存模式"), 0, 1)
        status_layout.addWidget(QLabel(f"{hardware.memory_profile}（{hardware.vram_gb or '?'} GB）"), 1, 1)
        status_layout.addWidget(QLabel("基础组件"), 0, 2)
        core = [MSSTAdapter(paths.external_backends / "msst").status(), RVCAdapter(paths.external_backends / "rvc").status(), DDSPAdapter(paths.external_backends / "ddsp").status()]
        ready = bool(ffmpeg_path(paths.root)) and all(item.runnable for item in core)
        status_layout.addWidget(QLabel("全部可用" if ready else "需要安装或修复"), 1, 2)
        install = QPushButton("查看组件")
        install.clicked.connect(lambda: self.navigate.emit("组件管理"))
        import_voice = QPushButton("导入音色")
        import_voice.clicked.connect(self.import_requested)
        status_layout.addWidget(install, 2, 0); status_layout.addWidget(import_voice, 2, 1)
        layout.addWidget(status)
        overview = QGridLayout()
        recent_panel = QFrame(); recent_panel.setObjectName("Panel"); recent_layout = QVBoxLayout(recent_panel)
        recent_title = QLabel("最近生成"); recent_title.setObjectName("CardTitle"); self.recent = QLabel(); self.recent.setWordWrap(True)
        recent_layout.addWidget(recent_title); recent_layout.addWidget(self.recent)
        voice_panel = QFrame(); voice_panel.setObjectName("Panel"); voice_layout = QVBoxLayout(voice_panel)
        voice_title = QLabel("推荐音色"); voice_title.setObjectName("CardTitle"); self.recommended = QLabel(); self.recommended.setWordWrap(True)
        voice_layout.addWidget(voice_title); voice_layout.addWidget(self.recommended)
        overview.addWidget(recent_panel, 0, 0); overview.addWidget(voice_panel, 0, 1)
        layout.addLayout(overview)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        jobs = [job for job in self.database.list_jobs(20) if job.get("status") == "completed" and job.get("kind") in {"original", "lyric"}][:3]
        self.recent.setText("\n".join(
            f"{Path(str(job['input_path'])).name}  ·  {job['engine'].upper()}  ·  {str(job['created_at'])[:10]}"
            for job in jobs
        ) or "暂无已完成任务")
        voices = self.registry.selectable()[:3]
        self.recommended.setText("\n".join(
            f"{model.display_name}  ·  {model.engine.upper()}  ·  {'可试听' if model.preview else '待生成试听'}"
            for model in voices
        ) or "暂无已导入音色")


class CoverPage(QWidget):
    start_requested = Signal(dict)
    import_requested = Signal()

    def __init__(self, registry: ModelRegistry, settings: Settings):
        super().__init__(); self.registry = registry; self.settings = settings; self.selected_model: str | None = None
        page, layout = panel_layout("原词翻唱", "拖入歌曲，选择引擎和音色，然后生成。推理在独立工作进程运行。")
        QVBoxLayout(self).addWidget(page)
        self.drop = AudioDropArea(); layout.addWidget(self.drop)
        self.input_player = AudioPlayer(); layout.addWidget(self.input_player)
        self.drop.path_changed.connect(lambda value: self.input_player.set_source(Path(value)))
        controls = QFrame(); controls.setObjectName("Panel")
        form = QGridLayout(controls); form.setContentsMargins(18, 16, 18, 16)
        self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.voice = QComboBox(); self.pitch = pitch_selector()
        self.source_voice = QComboBox()
        self.source_voice.addItem("自动检测（推荐）", "auto")
        self.source_voice.addItem("男声原唱", "male")
        self.source_voice.addItem("女声原唱", "female")
        self.source_voice.setToolTip("用于自动匹配原唱与目标音色的音域；手动升降调时不会额外转调。")
        self.balance = QComboBox(); self.balance.addItems(["均衡", "人声更突出", "伴奏更突出"])
        self.output_format = QComboBox(); self.output_format.addItems(["WAV", "FLAC", "MP3"])
        self.output_format.setCurrentText(settings.output_format.upper())
        form.addWidget(QLabel("引擎"), 0, 0); form.addWidget(self.engine, 0, 1)
        form.addWidget(QLabel("音色"), 0, 2); form.addWidget(self.voice, 0, 3)
        form.addWidget(QLabel("原唱声部"), 1, 0); form.addWidget(self.source_voice, 1, 1)
        form.addWidget(QLabel("升降调"), 1, 2); form.addWidget(self.pitch, 1, 3)
        form.addWidget(QLabel("混音"), 2, 0); form.addWidget(self.balance, 2, 1)
        form.addWidget(QLabel("输出"), 2, 2); form.addWidget(self.output_format, 2, 3)
        self.import_button = QPushButton("导入音色"); self.start = QPushButton("开始翻唱"); self.start.setObjectName("Primary")
        form.addWidget(self.import_button, 3, 2); form.addWidget(self.start, 3, 3)
        self.engine.currentTextChanged.connect(self.refresh_models); self.import_button.clicked.connect(self.import_requested)
        self.start.clicked.connect(self._start); layout.addWidget(controls); layout.addStretch(); self.refresh_models()

    def refresh_models(self) -> None:
        self.voice.clear(); models = self.registry.selectable(self.engine.currentText().lower())
        for model in models: self.voice.addItem(model.display_name, model.id)
        self.voice.setPlaceholderText("请先导入音色" if not models else "选择音色")

    def _start(self) -> None:
        if not self.drop.path: QMessageBox.warning(self, "缺少歌曲", "请先拖入或选择歌曲。"); return
        if self.voice.currentData() is None: QMessageBox.warning(self, "缺少音色", "当前引擎没有可用音色，请先导入。"); return
        model = self.registry.get(str(self.voice.currentData())); selected_pitch = self.pitch.currentData()
        pitch = int(selected_pitch) if selected_pitch is not None else int(model.recommended_pitch if model else 0)
        self.start_requested.emit({"input_path": str(self.drop.path), "engine": self.engine.currentText().lower(),
            "model_id": self.voice.currentData(), "options": {"pitch": pitch, "pitch_mode": "auto" if selected_pitch is None else "manual",
            "source_voice": self.source_voice.currentData(),
            "balance": self.balance.currentText(), "output_format": self.output_format.currentText().lower(),
            "memory_profile": self.settings.memory_profile}})


class LyricPage(QWidget):
    start_requested = Signal(dict)
    import_requested = Signal()

    def __init__(self, registry: ModelRegistry, paths: AppPaths, settings: Settings):
        super().__init__(); self.registry = registry; self.paths = paths; self.settings = settings; self.midi_path: Path | None = None
        page, layout = panel_layout("改词翻唱 Beta", "Beta：无时间戳原歌词会优先自动强制对齐；复杂歌声仍可改用带时间戳的 LRC。")
        QVBoxLayout(self).addWidget(page); self.drop = AudioDropArea(); layout.addWidget(self.drop)
        self.input_player = AudioPlayer(); layout.addWidget(self.input_player)
        self.drop.path_changed.connect(lambda value: self.input_player.set_source(Path(value)))
        fields = QFrame(); fields.setObjectName("Panel"); form = QFormLayout(fields); form.setContentsMargins(18, 16, 18, 16)
        self.original = QTextEdit(); self.original.setPlaceholderText("粘贴原歌词，或导入 TXT/LRC"); self.original.setMaximumHeight(92)
        self.new = QTextEdit(); self.new.setPlaceholderText("粘贴新歌词，建议逐行对应原歌词"); self.new.setMaximumHeight(92)
        form.addRow("原歌词", self._lyric_editor(self.original)); form.addRow("新歌词", self._lyric_editor(self.new))
        self.midi_file = QLineEdit(); self.midi_file.setReadOnly(True); self.midi_file.setPlaceholderText("可选；未上传时自动从原唱提取旋律")
        form.addRow("旋律 MIDI（可选）", self._midi_picker())
        selectors = QWidget(); grid = QGridLayout(selectors); grid.setContentsMargins(0, 0, 0, 0)
        self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"]); self.voice = QComboBox()
        self.strategy = QComboBox(); self.strategy.addItems(["均衡", "保守", "强制"])
        self.pitch = pitch_selector()
        self.balance = QComboBox(); self.balance.addItems(["均衡", "人声更突出", "伴奏更突出"])
        self.output_format = QComboBox(); self.output_format.addItems(["WAV", "FLAC", "MP3"])
        self.output_format.setCurrentText(settings.output_format.upper())
        for column, (label, widget) in enumerate((("引擎", self.engine), ("音色", self.voice), ("适配", self.strategy))):
            grid.addWidget(QLabel(label), 0, column * 2); grid.addWidget(widget, 0, column * 2 + 1)
        for column, (label, widget) in enumerate((("升降调", self.pitch), ("混音", self.balance), ("输出", self.output_format))):
            grid.addWidget(QLabel(label), 1, column * 2); grid.addWidget(widget, 1, column * 2 + 1)
        form.addRow("生成设置", selectors)
        score = EspnetVisinger2Adapter(paths.external_backends / "espnet_visinger2").status()
        status = Vevo2Adapter(paths.external_backends / "vevo2").status()
        fallback = [GameAdapter(paths.external_backends / "game").status(), DiffSingerLegacyAdapter(paths.external_backends / "diffsinger").status()]
        ready = (score.runnable and fallback[0].runnable) or status.runnable or all(item.runnable for item in fallback)
        self._default_generator_ready = ready
        self._diffsinger_ready = score.runnable or fallback[1].runnable
        if score.runnable and fallback[0].runnable:
            detail = "默认使用 GAME + 44.1 kHz VISinger2，按提取出的音符音高和时值重新演唱；之后再由所选 RVC/DDSP 音色转换。"
        elif status.runnable:
            detail = "VISinger2 未就绪；Vevo2 可生成歌声，但不保证逐音符复刻原曲。"
        elif ready:
            detail = "现代乐谱模型未就绪；只能使用 GAME + legacy DiffSinger，音质会受限。"
        else:
            detail = "VISinger2、Vevo2 与 legacy DiffSinger 均未就绪，请先到组件管理检查。"
        self.note = QLabel(detail)
        self.note.setWordWrap(True); self.note.setObjectName("Muted"); form.addRow("当前状态", self.note)
        actions = QWidget(); row = QHBoxLayout(actions); row.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("导入音色"); self.start = QPushButton("开始改词翻唱"); self.start.setObjectName("Primary"); self.start.setEnabled(ready)
        row.addWidget(add); row.addStretch(); row.addWidget(self.start); form.addRow("", actions)
        self.engine.currentTextChanged.connect(self.refresh_models); add.clicked.connect(self.import_requested); self.start.clicked.connect(self._start)
        layout.addWidget(fields); layout.addStretch(); self.refresh_models()

    def _lyric_editor(self, editor: QTextEdit) -> QWidget:
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); button = QPushButton("导入 TXT/LRC")
        button.clicked.connect(lambda: self._load_lyrics(editor)); row.addWidget(editor, 1); row.addWidget(button); return box

    def _load_lyrics(self, editor: QTextEdit) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "导入歌词", "", "歌词 (*.lrc *.txt);;所有文件 (*)")
        if not filename:
            return
        try:
            editor.setPlainText(decode_lyrics_file(Path(filename)))
        except Exception as exc:
            QMessageBox.critical(self, "歌词导入失败", str(exc))

    def _midi_picker(self) -> QWidget:
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("上传 MIDI"); clear = QPushButton("清除")
        choose.clicked.connect(self._load_midi); clear.clicked.connect(self._clear_midi)
        row.addWidget(self.midi_file, 1); row.addWidget(choose); row.addWidget(clear)
        return box

    def _load_midi(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "上传旋律 MIDI", "", "MIDI 文件 (*.mid *.midi)")
        if not filename:
            return
        path = Path(filename)
        try:
            midi = load_midi(path)
        except ValueError as exc:
            QMessageBox.critical(self, "MIDI 导入失败", str(exc))
            return
        self.midi_path = path
        self.midi_file.setText(str(path))
        self.midi_file.setToolTip(str(path))
        self.start.setEnabled(self._diffsinger_ready)
        self.note.setText(
            f"已读取 MIDI：{midi.track_count} 条轨道、{midi.note_count} 个音符、约 {midi.duration:.1f} 秒。"
            + ("生成时会自动选择主旋律轨道并与 LRC 时间轴对齐，再交给 VISinger2 乐谱合成；不会再用 GAME 猜音高。" if self._diffsinger_ready
               else "文件有效，但 VISinger2/legacy DiffSinger 尚未就绪，请先到组件管理修复。")
        )

    def _clear_midi(self) -> None:
        self.midi_path = None
        self.midi_file.clear(); self.midi_file.setToolTip("")
        self.start.setEnabled(self._default_generator_ready)
        self.note.setText("未上传 MIDI：默认由 GAME 提取原唱音符，再用 VISinger2 按音高和时值重新演唱；自动提取仍可能出现个别音符边界误差。")

    def refresh_models(self) -> None:
        current = self.voice.currentData(); self.voice.clear()
        models = self.registry.selectable(self.engine.currentText().lower())
        for model in models:
            self.voice.addItem(model.display_name, model.id)
        index = self.voice.findData(current)
        if index >= 0:
            self.voice.setCurrentIndex(index)
        self.voice.setPlaceholderText("请先导入音色" if not models else "选择音色")

    def _start(self) -> None:
        if not self.drop.path:
            QMessageBox.warning(self, "缺少歌曲", "请先拖入或选择歌曲。")
            return
        if self.voice.currentData() is None:
            QMessageBox.warning(self, "缺少音色", "当前引擎没有可用音色，请先导入。")
            return
        if not self.original.toPlainText().strip() or not self.new.toPlainText().strip():
            QMessageBox.warning(self, "缺少歌词", "请填写原歌词和新歌词。")
            return
        if self.midi_path is not None:
            try:
                load_midi(self.midi_path)
            except ValueError as exc:
                QMessageBox.warning(self, "MIDI 无效", str(exc))
                return
            score = EspnetVisinger2Adapter(self.paths.external_backends / "espnet_visinger2").status()
            legacy = DiffSingerLegacyAdapter(self.paths.external_backends / "diffsinger").status()
            if not score.runnable and not legacy.runnable:
                QMessageBox.warning(self, "乐谱模型不可用", "上传 MIDI 后需要 VISinger2 或 legacy DiffSinger：" + score.detail)
                return
        model = self.registry.get(str(self.voice.currentData())); selected_pitch = self.pitch.currentData()
        pitch = int(selected_pitch) if selected_pitch is not None else int(model.recommended_pitch if model else 0)
        self.start_requested.emit({
            "input_path": str(self.drop.path), "engine": self.engine.currentText().lower(), "model_id": self.voice.currentData(),
            "options": {"original_lyrics": self.original.toPlainText(), "new_lyrics": self.new.toPlainText(),
            "strategy": self.strategy.currentText(), "pitch": pitch, "pitch_mode": "auto" if selected_pitch is None else "manual", "balance": self.balance.currentText(),
            "output_format": self.output_format.currentText().lower(), "memory_profile": self.settings.memory_profile,
            "midi_path": str(self.midi_path) if self.midi_path is not None else ""},
        })


class ImportVoiceDialog(QDialog):
    imported = Signal()
    preview_requested = Signal(str)

    def __init__(self, importer: ModelImporter, parent: QWidget | None = None):
        super().__init__(parent); self.importer = importer; self.setWindowTitle("导入音色"); self.resize(560, 440)
        form = QFormLayout(self); self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.weight = QLineEdit(); self.extra = QLineEdit(); self.name = QLineEdit(); self.description = QLineEdit()
        self.avatar = QLineEdit(); self.preview = QLineEdit(); self.preview_mode = QComboBox()
        self.voice_gender = QComboBox(); self.voice_gender.addItem("未知 / 通用", "unknown"); self.voice_gender.addItem("女声音色", "female"); self.voice_gender.addItem("男声音色", "male")
        self.preview_mode.addItem("自动生成（推荐）", "auto"); self.preview_mode.addItem("上传试听音频", "upload"); self.preview_mode.addItem("暂不生成", "none")
        form.addRow("引擎", self.engine); form.addRow("模型权重", self._picker(self.weight, "权重 (*.pth *.pt *.ckpt)"))
        form.addRow("索引 / 配置", self._picker(self.extra, "RVC 索引或 DDSP 配置 (*.index *.yaml *.yml)"))
        form.addRow("名称", self.name); form.addRow("简介", self.description); form.addRow("音色声部", self.voice_gender)
        form.addRow("头像（可选）", self._picker(self.avatar, "图片 (*.png *.jpg *.jpeg *.webp)"))
        form.addRow("试听方式", self.preview_mode); self.preview_picker = self._picker(self.preview, "音频 (*.wav *.flac *.mp3 *.m4a)"); form.addRow("试听音频", self.preview_picker)
        hint = QLabel("自动生成会在导入后提交独立真实推理任务；暂不生成时卡片显示“生成试听”。标准干声不会直接冒充音色试听。")
        hint.setWordWrap(True); hint.setObjectName("Muted"); form.addRow("", hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导入")
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self._import); form.addRow(buttons)
        self.preview_mode.currentIndexChanged.connect(self._preview_mode_changed); self._preview_mode_changed()

    def _preview_mode_changed(self) -> None:
        upload = self.preview_mode.currentData() == "upload"
        self.preview_picker.setEnabled(upload)

    def _picker(self, target: QLineEdit, file_filter: str) -> QWidget:
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); button = QPushButton("选择")
        button.clicked.connect(lambda: self._choose(target, file_filter)); row.addWidget(target, 1); row.addWidget(button); return box

    def _choose(self, target: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if path: target.setText(path)

    def _import(self) -> None:
        try:
            if not self.name.text().strip(): raise ValueError("请填写名称")
            opt = lambda field: Path(field.text()) if field.text().strip() else None
            mode = str(self.preview_mode.currentData())
            if mode == "upload" and not self.preview.text().strip(): raise ValueError("请选择要上传的试听音频")
            model = self.importer.import_model(engine=self.engine.currentText().lower(), weight=Path(self.weight.text()),
                display_name=self.name.text(), description=self.description.text(), index_or_config=opt(self.extra),
                avatar=opt(self.avatar), preview=opt(self.preview) if mode == "upload" else None,
                voice_gender=str(self.voice_gender.currentData()))
        except Exception as exc: QMessageBox.critical(self, "导入失败", str(exc)); return
        self.imported.emit()
        if mode == "auto" and not model.preview:
            self.preview_requested.emit(model.id)
        self.accept()


class EditVoiceDialog(QDialog):
    changed = Signal()
    regenerate_requested = Signal(str)

    def __init__(self, importer: ModelImporter, model, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        super().__init__(parent); self.importer = importer; self.model = model; self.setWindowTitle(f"管理音色 · {model.display_name}"); self.resize(560, 430)
        self.directory = model.directory(importer.weights_root); form = QFormLayout(self)
        self.name = QLineEdit(model.display_name); self.description = QLineEdit(model.description); self.pitch = QSpinBox(); self.pitch.setRange(-12, 12); self.pitch.setValue(model.recommended_pitch)
        self.voice_gender = QComboBox(); self.voice_gender.addItem("未知 / 通用", "unknown"); self.voice_gender.addItem("女声音色", "female"); self.voice_gender.addItem("男声音色", "male"); self.voice_gender.setCurrentIndex(max(0, self.voice_gender.findData(model.voice_gender)))
        self.languages = QLineEdit(", ".join(model.languages)); self.avatar = QLineEdit(); self.preview = QLineEdit(); self.remove_preview = QCheckBox("删除现有试听并自动重新生成")
        self.featured = QCheckBox("置顶此音色"); self.featured.setChecked(model.featured)
        form.addRow("名称", self.name); form.addRow("简介", self.description); form.addRow("音色声部", self.voice_gender); form.addRow("推荐升降调", self.pitch); form.addRow("适合语言", self.languages)
        form.addRow("更换头像", self._picker(self.avatar, "图片 (*.png *.jpg *.jpeg *.webp)")); form.addRow("更换试听", self._picker(self.preview, "音频 (*.wav *.flac *.mp3 *.m4a)")); form.addRow("", self.remove_preview); form.addRow("", self.featured)
        tools = QWidget(); row = QHBoxLayout(tools); row.setContentsMargins(0, 0, 0, 0); open_dir = QPushButton("打开模型目录"); delete = QPushButton("删除用户模型"); delete.setEnabled(not model.bundled)
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(self.directory.as_uri())); delete.clicked.connect(self._delete); row.addWidget(open_dir); row.addWidget(delete); row.addStretch(); form.addRow("", tools)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save); buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self._save); form.addRow(buttons)

    def _picker(self, target: QLineEdit, file_filter: str) -> QWidget:
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); button = QPushButton("选择")
        button.clicked.connect(lambda: self._choose(target, file_filter)); row.addWidget(target, 1); row.addWidget(button); return box

    def _choose(self, target: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if path: target.setText(path)

    def _save(self) -> None:
        try:
            updated = self.importer.update_model(
                self.model.id, display_name=self.name.text(), description=self.description.text(), recommended_pitch=self.pitch.value(),
                voice_gender=str(self.voice_gender.currentData()),
                languages=[item for item in self.languages.text().replace("，", ",").split(",")],
                avatar=Path(self.avatar.text()) if self.avatar.text().strip() else None,
                preview=Path(self.preview.text()) if self.preview.text().strip() else None,
                remove_preview=self.remove_preview.isChecked(), featured=self.featured.isChecked(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc)); return
        self.changed.emit()
        if self.remove_preview.isChecked() and not updated.preview:
            self.regenerate_requested.emit(updated.id)
        self.accept()

    def _delete(self) -> None:
        if QMessageBox.question(self, "删除用户模型", "将删除该用户模型目录和其中权重，且无法从任务记录恢复。是否继续？") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.importer.delete_user_model(self.model.id)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc)); return
        self.changed.emit(); self.accept()


class VoiceManagerPage(QWidget):
    import_requested = Signal()
    generate_requested = Signal(str)
    model_selected = Signal(str, str)
    edit_requested = Signal(str)
    def __init__(self, registry: ModelRegistry, database: Database):
        super().__init__(); self.registry = registry; self.database = database; page, layout = panel_layout("音色管理", "音色按 RVC / DDSP 分开显示；元数据与权重文件分离保存。")
        QVBoxLayout(self).addWidget(page); tools = QHBoxLayout(); self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索名称、简介或语言")
        self.sort = QComboBox(); self.sort.addItems(["推荐优先", "名称排序", "最近使用"])
        self.hide_bundled = QCheckBox("隐藏内置")
        add = QPushButton("导入音色"); add.setObjectName("Primary")
        tools.addWidget(self.engine); tools.addWidget(self.search, 1); tools.addWidget(self.sort); tools.addWidget(self.hide_bundled); tools.addWidget(add); layout.addLayout(tools)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); layout.addWidget(self.scroll, 1)
        self.player = AudioPlayer(); layout.addWidget(self.player)
        self.engine.currentTextChanged.connect(self.refresh); self.search.textChanged.connect(self.refresh); self.sort.currentTextChanged.connect(self.refresh); self.hide_bundled.toggled.connect(self.refresh); add.clicked.connect(self.import_requested); self.refresh()
    def refresh(self) -> None:
        host = QWidget(); column = QVBoxLayout(host); needle = self.search.text().casefold()
        models = [
            model for model in self.registry.scan(self.engine.currentText().lower())
            if needle in " ".join((model.display_name, model.description, *model.languages)).casefold()
            and not (self.hide_bundled.isChecked() and model.bundled)
        ]
        if self.sort.currentText() == "名称排序":
            models.sort(key=lambda model: model.display_name.casefold())
        elif self.sort.currentText() == "最近使用":
            recent = [str(job["model_id"]) for job in self.database.list_jobs(100) if job.get("kind") in {"original", "lyric", "preview"}]
            order: dict[str, int] = {}
            for model_id in recent:
                order.setdefault(model_id, len(order))
            models.sort(key=lambda model: (order.get(model.id, len(recent)), model.display_name.casefold()))
        if not models:
            if not needle or "丰川祥子" in needle or "祥子" in needle:
                pending = QFrame(); pending.setObjectName("Panel"); row = QHBoxLayout(pending)
                avatar = QLabel(); avatar.setFixedSize(72, 72)
                avatar_path = self.registry.weights_root.parent / "assets" / "祥子音色图标.jpg"
                if avatar_path.is_file():
                    avatar.setPixmap(QPixmap(str(avatar_path)).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                text = QVBoxLayout(); title = QLabel("丰川祥子"); title.setObjectName("CardTitle")
                detail = QLabel(f"{self.engine.currentText()} 固定 ID 已保留 · 模型来源与许可尚未核验")
                detail.setObjectName("Muted"); text.addWidget(title); text.addWidget(detail)
                disabled = QPushButton("模型未安装"); disabled.setEnabled(False)
                row.addWidget(avatar); row.addLayout(text, 1); row.addWidget(disabled); column.addWidget(pending)
            column.addWidget(QLabel("点击“导入音色”添加得到授权的模型。祥子头像素材不代表模型已安装。"))
        for model in models:
            directory = model.directory(self.registry.weights_root)
            card = VoiceCard(model, directory)
            card.preview_requested.connect(lambda model_id, m=model, d=directory: self._preview(m, d))
            card.selected.connect(lambda model_id, engine=model.engine: self.model_selected.emit(engine, model_id))
            card.manage_requested.connect(self.edit_requested)
            column.addWidget(card)
        column.addStretch(); self.scroll.setWidget(host)

    def _preview(self, model, directory: Path) -> None:  # type: ignore[no-untyped-def]
        path = directory / model.preview if model.preview else None
        if path and path.is_file():
            self.player.set_source(path)
            self.player.player.play()
            self.player.play.setText("暂停")
        else:
            self.generate_requested.emit(model.id)


class HistoryPage(QWidget):
    cancel_requested = Signal(str)
    rerun_requested = Signal(dict)

    def __init__(self, database: Database, paths: AppPaths, registry: ModelRegistry):
        super().__init__(); self.database = database; self.paths = paths; self.registry = registry; page, layout = panel_layout("任务记录", "本地 SQLite 记录；失败与取消不会被隐藏。")
        QVBoxLayout(self).addWidget(page); self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["歌曲", "类型", "引擎", "音色", "状态", "进度", "时间", "输出"])
        self.table.setIconSize(QSize(28, 28))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.player = AudioPlayer(); layout.addWidget(self.player)
        actions = QGridLayout(); refresh = QPushButton("刷新"); play = QPushButton("播放输出"); open_output = QPushButton("打开目录")
        rerun = QPushButton("重新生成"); change_voice = QPushButton("更换音色生成")
        cancel = QPushButton("取消任务"); delete = QPushButton("删除记录"); clear = QPushButton("清缓存"); export = QPushButton("导出日志包")
        refresh.clicked.connect(self.refresh); play.clicked.connect(self._play); open_output.clicked.connect(self._open_output)
        rerun.clicked.connect(self._rerun); change_voice.clicked.connect(self._change_voice)
        cancel.clicked.connect(self._cancel); delete.clicked.connect(self._delete); clear.clicked.connect(self._clear_cache); export.clicked.connect(self._export)
        for index, button in enumerate((refresh, play, open_output, rerun, change_voice, cancel, delete, clear, export)):
            actions.addWidget(button, index // 5, index % 5)
        layout.addLayout(actions); self.refresh()

    def _selected(self) -> dict[str, object] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return self.database.get_job(str(item.data(Qt.ItemDataRole.UserRole))) if item else None

    def _play(self) -> None:
        job = self._selected(); path = Path(str(job["output_path"])) if job and job.get("output_path") else None
        if not path or not path.is_file():
            QMessageBox.warning(self, "无法播放", "所选任务没有可播放的输出文件。")
            return
        self.player.set_source(path); self.player.player.play(); self.player.play.setText("暂停")

    def _open_output(self) -> None:
        job = self._selected(); path = Path(str(job["output_path"])) if job and job.get("output_path") else self.paths.workspace / "outputs"
        target = path.parent if path.is_file() else self.paths.workspace / "outputs"
        QDesktopServices.openUrl(target.as_uri())

    def _cancel(self) -> None:
        job = self._selected()
        if not job or job.get("status") not in {"pending", "running"}:
            QMessageBox.information(self, "无需取消", "请选择正在运行的任务。")
            return
        self.cancel_requested.emit(str(job["id"]))

    def _rerun_payload(self, job: dict[str, object]) -> dict[str, object]:
        try:
            options = json.loads(str(job.get("options_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("任务设置记录已损坏，无法重新生成") from exc
        if not isinstance(options, dict):
            raise ValueError("任务设置记录格式无效")
        return {
            "_kind": str(job["kind"]), "input_path": str(job["input_path"]),
            "engine": str(job["engine"]), "model_id": str(job["model_id"]), "options": options,
        }

    def _rerun(self) -> None:
        job = self._selected()
        if not job:
            QMessageBox.information(self, "请选择任务", "请先选择要重新生成的任务记录。")
            return
        if job.get("status") in {"pending", "running"}:
            QMessageBox.information(self, "任务仍在运行", "请等待任务完成或先取消。")
            return
        try:
            self.rerun_requested.emit(self._rerun_payload(job))
        except ValueError as exc:
            QMessageBox.warning(self, "无法重新生成", str(exc))

    def _change_voice(self) -> None:
        job = self._selected()
        if not job or job.get("kind") not in {"original", "lyric", "preview"}:
            QMessageBox.information(self, "无法更换音色", "请选择原词、改词或试听任务。")
            return
            models = self.registry.selectable(str(job["engine"]))
        if not models:
            QMessageBox.warning(self, "没有可用音色", "当前引擎没有已导入且有效的音色。")
            return
        labels = [f"{model.display_name}  ·  {model.id}" for model in models]
        current = next((index for index, model in enumerate(models) if model.id == job.get("model_id")), 0)
        selected, accepted = QInputDialog.getItem(self, "更换音色生成", "选择新音色：", labels, current, False)
        if not accepted:
            return
        try:
            payload = self._rerun_payload(job)
        except ValueError as exc:
            QMessageBox.warning(self, "无法重新生成", str(exc)); return
        model = models[labels.index(selected)]
        payload["model_id"] = model.id
        payload["engine"] = model.engine
        self.rerun_requested.emit(payload)

    def _delete(self) -> None:
        job = self._selected()
        if not job:
            return
        if job.get("status") == "running":
            QMessageBox.warning(self, "无法删除", "请先取消正在运行的任务。")
            return
        if QMessageBox.question(self, "删除记录", "只删除任务记录，不删除输出音频。是否继续？") == QMessageBox.StandardButton.Yes:
            self.database.delete_job(str(job["id"])); self.refresh()

    def _clear_cache(self) -> None:
        cache = (self.paths.workspace / "cache").resolve()
        if cache.parent != self.paths.workspace.resolve():
            raise RuntimeError("缓存目录越界")
        if QMessageBox.question(self, "清理缓存", "将删除分离与推理缓存，但保留模型、任务记录和输出。是否继续？") != QMessageBox.StandardButton.Yes:
            return
        cache.mkdir(parents=True, exist_ok=True)
        # Older local installations may keep uv's base interpreter here. Backend
        # virtual environments depend on it, so deleting the whole cache makes
        # every launcher look installed while it can no longer start Python.
        for child in cache.iterdir():
            if child.name.casefold() == "uv-python":
                continue
            if child.is_symlink() or child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                shutil.rmtree(child)
        QMessageBox.information(self, "缓存已清理", "下次任务将重新执行分离和推理。")

    def _export(self) -> None:
        job = self._selected()
        if not job:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "导出任务日志包", f"opencover-job-{str(job['id'])[:8]}.zip", "ZIP (*.zip)")
        if filename:
            target = Path(filename)
            if target.suffix.lower() != ".zip":
                target = target.with_suffix(".zip")
            self._write_log_bundle(job, target)

    def _write_log_bundle(self, job: dict[str, object], target: Path) -> None:
        job_dir = self.paths.workspace / "jobs" / str(job["id"])
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("job.json", json.dumps(job, ensure_ascii=False, indent=2))
            for name in ("request.json", "worker.log"):
                source = job_dir / name
                if source.is_file():
                    archive.write(source, name)

    def refresh(self) -> None:
        rows = self.database.list_jobs(); self.table.setRowCount(len(rows))
        for r, job in enumerate(rows):
            kinds = {"original": "原词", "lyric": "改词", "preview": "试听"}
            model = self.registry.get(str(job["model_id"]))
            voice_name = model.display_name if model else str(job["model_id"])
            values = [Path(str(job["input_path"])).name, kinds.get(str(job["kind"]), job["kind"]), job["engine"], voice_name, job["status"], f"{job['progress']}%", str(job["created_at"])[:19].replace("T", " "), job["output_path"] or "—"]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 0: item.setData(Qt.ItemDataRole.UserRole, job["id"])
                if c == 3 and model and model.avatar:
                    avatar = model.directory(self.registry.weights_root) / model.avatar
                    if avatar.is_file(): item.setIcon(QIcon(str(avatar)))
                self.table.setItem(r, c, item)


class ComponentPage(QWidget):
    def __init__(self, paths: AppPaths, jobs: JobManager, database: Database):
        super().__init__(); self.paths = paths; page, layout = panel_layout("组件管理", "仅通过本机文件和真实 smoke test 判定状态；不会执行下载包内的未知脚本。")
        self.jobs = jobs; self.database = database; self.active_job: str | None = None
        QVBoxLayout(self).addWidget(page); self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["组件", "状态", "版本", "说明"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.download_status = QLabel("可从已核验资源清单下载；安装后仍须通过上方 smoke test 才会显示为可用。")
        self.download_status.setWordWrap(True); self.download_progress = QProgressBar(); self.download_progress.setRange(0, 100); self.download_progress.setValue(0)
        layout.addWidget(self.download_status); layout.addWidget(self.download_progress)
        actions = QHBoxLayout(); refresh = QPushButton("重新检测"); install = QPushButton("下载并安装资源"); download = QPushButton("仅下载到缓存"); cancel = QPushButton("取消下载"); open_folder = QPushButton("打开组件目录"); sources = QPushButton("查看资源与许可证")
        refresh.clicked.connect(self.refresh); open_folder.clicked.connect(lambda: QDesktopServices.openUrl(Path(paths.external_backends).as_uri())); sources.clicked.connect(lambda: QDesktopServices.openUrl((paths.root / "RESOURCE_SOURCES.md").as_uri()))
        install.clicked.connect(lambda: self.start_resource(True)); download.clicked.connect(lambda: self.start_resource(False)); cancel.clicked.connect(self.cancel_resource)
        actions.addWidget(refresh); actions.addWidget(install); actions.addWidget(download); actions.addWidget(cancel); actions.addWidget(open_folder); actions.addWidget(sources); actions.addStretch(); layout.addLayout(actions)
        jobs.event.connect(self.on_job_event); jobs.finished.connect(self.on_job_finished); self.refresh()

    def _resources(self) -> list[dict[str, object]]:
        try:
            data = yaml.safe_load((self.paths.config / "resource_manifest.yaml").read_text(encoding="utf-8"))
            excluded = {"voice_model", "preview_source_audio", "test_audio"}
            return [
                item for item in data["resources"]
                if item.get("download_url") and item.get("type") not in excluded
                and item.get("download_method", "http") == "http"
            ]
        except (OSError, KeyError, TypeError, yaml.YAMLError):
            return []

    def start_resource(self, install: bool) -> None:
        if self.active_job and self.active_job in self.jobs.processes:
            QMessageBox.information(self, "已有下载任务", "请等待当前资源任务完成或先取消。")
            return
        resources = self._resources()
        if not resources:
            QMessageBox.warning(self, "资源清单不可用", "没有可下载且经过核验的组件资源。")
            return
        labels = [f"{item['name']}  ·  {float(item.get('file_size') or 0) / 1024**2:.1f} MiB" for item in resources]
        selected, accepted = QInputDialog.getItem(self, "选择组件资源", "资源（下载不等于后端已可运行）：", labels, 0, False)
        if not accepted:
            return
        item = resources[labels.index(selected)]
        permission = "允许再分发" if item.get("redistribution_allowed") else "仅本机下载/权利需自行确认"
        detail = (
            f"名称：{item['name']}\n许可证：{item.get('license') or '未明确'}\n权利：{permission}\n"
            f"目标：{item['install_directory']}\n来源：{item.get('source_page') or item['download_url']}\n\n"
            + ("将校验 SHA256 后安全安装；不会执行包内脚本。" if install else "只下载到 downloads 缓存，不安装。")
        )
        if QMessageBox.question(self, "确认资源任务", detail) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.active_job = self.jobs.submit_resource(str(item["resource_id"]), install=install)
        except Exception as exc:
            self.active_job = None; QMessageBox.critical(self, "无法启动下载", str(exc)); return
        self.download_progress.setValue(0); self.download_status.setText(f"任务 {self.active_job[:8]} 已启动：{item['name']}")

    def cancel_resource(self) -> None:
        if self.active_job:
            self.jobs.cancel(self.active_job)

    def on_job_event(self, job_id: str, event: object) -> None:
        if job_id != self.active_job:
            return
        message = getattr(event, "message", None)
        value = getattr(event, "value", None)
        if message:
            self.download_status.setText(str(message))
        if value is not None:
            self.download_progress.setValue(int(value))

    def on_job_finished(self, job_id: str, success: bool) -> None:
        if job_id != self.active_job:
            return
        job = self.database.get_job(job_id); self.active_job = None; self.refresh()
        if success:
            self.download_status.setText(f"资源任务完成：{job.get('output_path') if job else ''}")
        else:
            self.download_status.setText(f"资源任务未完成：{job.get('error') if job else '未知错误'}")

    def refresh(self) -> None:
        ffmpeg = ffmpeg_path(self.paths.root)
        statuses = [BackendStatus("ffmpeg", "FFmpeg", bool(ffmpeg), bool(ffmpeg), str(ffmpeg or "未安装"), "本地可执行文件已找到" if ffmpeg else "基础音频运行时缺失")]
        statuses += [MSSTAdapter(self.paths.external_backends / "msst").status(), RVCAdapter(self.paths.external_backends / "rvc").status(), DDSPAdapter(self.paths.external_backends / "ddsp").status()]
        statuses += [
            EspnetVisinger2Adapter(self.paths.external_backends / "espnet_visinger2").status(),
            Vevo2Adapter(self.paths.external_backends / "vevo2").status(),
            GameAdapter(self.paths.external_backends / "game").status(),
            DiffSingerLegacyAdapter(self.paths.external_backends / "diffsinger").status(),
            AlignmentAdapter(self.paths.external_backends / "alignment").status(),
        ]
        self.table.setRowCount(len(statuses))
        for r, item in enumerate(statuses):
            state = "可用" if item.runnable else ("未就绪" if item.installed else "未安装")
            for c, value in enumerate([item.name, state, item.version, item.detail]): self.table.setItem(r, c, QTableWidgetItem(str(value)))


class SettingsPage(QWidget):
    def __init__(self, settings: Settings, hardware: HardwareInfo, settings_path: Path):
        super().__init__(); page, layout = panel_layout("设置", "硬件信息来自本机检测，CUDA 版本是驱动报告值，不代表 PyTorch 运行时已安装。")
        QVBoxLayout(self).addWidget(page); frame = QFrame(); frame.setObjectName("Panel"); form = QFormLayout(frame); form.setContentsMargins(18, 16, 18, 16)
        self.profile = QComboBox(); self.profile.addItems(["极低", "低", "标准", "高质量"]); self.profile.setCurrentText(settings.memory_profile)
        self.output_format = QComboBox(); self.output_format.addItems(["WAV", "FLAC", "MP3"]); self.output_format.setCurrentText(settings.output_format.upper())
        self.minimize = QCheckBox("无任务时关闭窗口也最小化到托盘"); self.minimize.setChecked(settings.minimize_to_tray)
        form.addRow("显存模式", self.profile); form.addRow("下次启动默认输出", self.output_format); form.addRow("关闭行为", self.minimize)
        form.addRow("GPU", QLabel(hardware.gpu or "未检测到")); form.addRow("显存", QLabel(f"{hardware.vram_gb or '?'} GB")); form.addRow("Compute Capability", QLabel(hardware.compute_capability or "未知")); form.addRow("驱动", QLabel(hardware.driver or "未知")); form.addRow("CUDA（驱动）", QLabel(hardware.cuda_reported or "未知")); form.addRow("CUDA 实测", QLabel("通过" if hardware.cuda_smoke else "未通过或未安装运行时")); form.addRow("FP16 实测", QLabel("通过" if hardware.fp16_supported else "未验证")); form.addRow("磁盘可用", QLabel(f"{hardware.disk_free_gb} GB" if hardware.disk_free_gb is not None else "未知")); form.addRow("FFmpeg", QLabel(hardware.ffmpeg or "未安装")); form.addRow("版本", QLabel(__version__)); layout.addWidget(frame); layout.addStretch()
        def persist() -> None:
            settings.memory_profile = self.profile.currentText()  # type: ignore[assignment]
            settings.output_format = self.output_format.currentText().lower()  # type: ignore[assignment]
            settings.minimize_to_tray = self.minimize.isChecked()
            settings.save(settings_path)
        self.profile.currentTextChanged.connect(persist); self.output_format.currentTextChanged.connect(persist); self.minimize.toggled.connect(persist)


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths, settings: Settings, hardware: HardwareInfo, database: Database):
        super().__init__(); self.paths = paths; self.app_settings = settings; self.hardware = hardware; self.database = database
        self.registry = ModelRegistry(paths.weights); self.importer = ModelImporter(paths.weights, ffmpeg_path(paths.root)); self.jobs = JobManager(database, paths.root, self)
        self.setWindowTitle("OpenCover Studio")
        icon_path = paths.assets / "图标.jpg"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(900, 620); self.resize(settings.window_width, settings.window_height)
        root = QWidget(); root.setObjectName("Root"); self.setCentralWidget(root); shell = QHBoxLayout(root); shell.setContentsMargins(0, 0, 0, 0); shell.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(204); nav = QVBoxLayout(sidebar); nav.setContentsMargins(0, 0, 0, 0)
        brand = QLabel("OpenCover\nStudio"); brand.setObjectName("Brand"); nav.addWidget(brand); self.nav_buttons: dict[str, QPushButton] = {}
        for name in NAV_ITEMS:
            button = QPushButton(name); button.setObjectName("NavButton"); button.setCheckable(True); button.clicked.connect(lambda checked=False, n=name: self.navigate(n)); nav.addWidget(button); self.nav_buttons[name] = button
        nav.addStretch(); status = QLabel(f"{hardware.gpu or '未检测到 GPU'}\n{hardware.memory_profile}显存 · v{__version__}"); status.setWordWrap(True); status.setObjectName("SidebarStatus"); nav.addWidget(status); shell.addWidget(sidebar)
        self.stack = QStackedWidget(); shell.addWidget(self.stack, 1); self.pages: dict[str, QWidget] = {}
        self._apply_background()
        self._add_pages(); self.navigate(settings.last_page if settings.last_page in self.pages else "首页"); self._tray()

    def _apply_background(self) -> None:
        candidates = [self.paths.assets / f"背景{index}{suffix}" for index in range(1, 4) for suffix in (".png", ".jpg", ".jpeg", ".webp")]
        selected = next((path for path in candidates if path.is_file()), None)
        if not selected:
            return
        url = selected.as_posix().replace("'", "\\'")
        self.stack.setObjectName("BackgroundStack")
        self.stack.setStyleSheet(
            f"QStackedWidget#BackgroundStack {{ border-image: url('{url}') 0 0 0 0 stretch stretch; }}"
            " QWidget#ContentPage { background-color: rgba(248, 249, 247, 174); }"
        )

    def _add_pages(self) -> None:
        home = HomePage(self.hardware, self.paths, self.database, self.registry); cover = CoverPage(self.registry, self.app_settings); lyric = LyricPage(self.registry, self.paths, self.app_settings); voices = VoiceManagerPage(self.registry, self.database); history = HistoryPage(self.database, self.paths, self.registry)
        home.navigate.connect(self.navigate); home.import_requested.connect(self.import_voice); cover.import_requested.connect(self.import_voice); cover.start_requested.connect(self.start_job); voices.import_requested.connect(self.import_voice)
        lyric.import_requested.connect(self.import_voice); lyric.start_requested.connect(self.start_lyric_job)
        voices.generate_requested.connect(self.start_preview_job); voices.model_selected.connect(self.select_model)
        voices.edit_requested.connect(self.edit_voice)
        history.cancel_requested.connect(self.jobs.cancel); history.rerun_requested.connect(self.rerun_job); self.jobs.event.connect(lambda job_id, event: history.refresh())
        self.jobs.event.connect(self._job_event)
        self.jobs.finished.connect(self._job_finished)
        pages = {"首页": home, "原词翻唱": cover, "改词翻唱 Beta": lyric, "音色管理": voices, "任务记录": history, "组件管理": ComponentPage(self.paths, self.jobs, self.database), "设置": SettingsPage(self.app_settings, self.hardware, self.paths.workspace / "settings.json")}
        for name, page in pages.items(): self.pages[name] = page; self.stack.addWidget(page)

    def navigate(self, name: str) -> None:
        self.stack.setCurrentWidget(self.pages[name]); [button.setChecked(key == name) for key, button in self.nav_buttons.items()]; self.app_settings.last_page = name

    def import_voice(self) -> None:
        dialog = ImportVoiceDialog(self.importer, self)
        dialog.imported.connect(self._models_changed)
        dialog.preview_requested.connect(self.start_preview_job)
        dialog.exec()

    def edit_voice(self, model_id: str) -> None:
        model = self.registry.get(model_id)
        if model is None:
            QMessageBox.warning(self, "找不到音色", "音色可能已被删除。")
            return
        dialog = EditVoiceDialog(self.importer, model, self)
        dialog.changed.connect(self._models_changed)
        dialog.regenerate_requested.connect(self.start_preview_job)
        dialog.exec()

    def _models_changed(self) -> None:
        home = self.pages["首页"]
        if isinstance(home, HomePage): home.refresh()
        page = self.pages["原词翻唱"]
        if isinstance(page, CoverPage): page.refresh_models()
        lyric = self.pages["改词翻唱 Beta"]
        if isinstance(lyric, LyricPage): lyric.refresh_models()
        manager = self.pages["音色管理"]
        if isinstance(manager, VoiceManagerPage): manager.refresh()

    def start_job(self, payload: dict) -> None:
        model = self.registry.get(str(payload["model_id"])); missing = []
        if not model: missing.append("音色不存在")
        pipeline_status = [MSSTAdapter(self.paths.external_backends / "msst").status(), (RVCAdapter(self.paths.external_backends / "rvc") if payload["engine"] == "rvc" else DDSPAdapter(self.paths.external_backends / "ddsp")).status()]
        missing.extend(item.detail for item in pipeline_status if not item.runnable)
        if not self.hardware.ffmpeg: missing.append("FFmpeg 未安装")
        if missing: QMessageBox.warning(self, "组件尚未就绪", "无法开始真实推理：\n\n" + "\n".join(f"• {item}" for item in missing) + "\n\n请在“组件管理”查看真实状态。"); return
        payload["root"] = str(self.paths.root); job_id = self.jobs.submit_original(payload); QMessageBox.information(self, "任务已创建", f"任务 {job_id[:8]} 已在独立进程启动。"); self.navigate("任务记录")

    def rerun_job(self, payload: dict) -> None:
        kind = str(payload.pop("_kind", ""))
        if kind == "original":
            self.start_job(payload)
        elif kind == "lyric":
            self.start_lyric_job(payload)
        elif kind == "preview":
            self.start_preview_job(str(payload["model_id"])); self.navigate("任务记录")
        elif kind == "resource":
            options = payload.get("options", {})
            install = bool(options.get("install", True)) if isinstance(options, dict) else True
            job_id = self.jobs.submit_resource(str(payload["input_path"]), install=install)
            QMessageBox.information(self, "资源任务已创建", f"任务 {job_id[:8]} 已重新启动。")
            self.navigate("任务记录")
        else:
            QMessageBox.warning(self, "无法重新生成", f"不支持的历史任务类型：{kind or '未知'}")

    def start_preview_job(self, model_id: str) -> None:
        model = self.registry.get(model_id)
        if model is None:
            QMessageBox.warning(self, "无法生成试听", "找不到所选音色。")
            return
        adapter = RVCAdapter(self.paths.external_backends / "rvc") if model.engine == "rvc" else DDSPAdapter(self.paths.external_backends / "ddsp")
        if not adapter.status().runnable:
            QMessageBox.warning(self, "无法生成试听", adapter.status().detail)
            return
        try:
            job_id = self.jobs.submit_preview(model_id)
        except Exception as exc:
            QMessageBox.critical(self, "无法生成试听", str(exc))
            return
        QMessageBox.information(self, "试听任务已创建", f"任务 {job_id[:8]} 正在后台使用真实模型生成试听。")

    def start_lyric_job(self, payload: dict) -> None:
        model = self.registry.get(str(payload["model_id"])); missing = []
        if model is None:
            missing.append("音色不存在")
        options = payload.get("options", {})
        has_midi = isinstance(options, dict) and bool(str(options.get("midi_path", "")).strip())
        statuses = [MSSTAdapter(self.paths.external_backends / "msst").status()]
        vevo = Vevo2Adapter(self.paths.external_backends / "vevo2").status()
        score = EspnetVisinger2Adapter(self.paths.external_backends / "espnet_visinger2").status()
        fallback = [GameAdapter(self.paths.external_backends / "game").status(), DiffSingerLegacyAdapter(self.paths.external_backends / "diffsinger").status()]
        if has_midi and not score.runnable and not fallback[1].runnable:
            missing.append("上传 MIDI 后需要 VISinger2 或 legacy DiffSinger 乐谱合成组件")
        elif not has_midi and not (score.runnable and fallback[0].runnable) and not vevo.runnable and not all(item.runnable for item in fallback):
            missing.append("VISinger2、Vevo2 与 legacy DiffSinger 均未就绪")
        statuses.append((RVCAdapter(self.paths.external_backends / "rvc") if payload["engine"] == "rvc" else DDSPAdapter(self.paths.external_backends / "ddsp")).status())
        missing.extend(item.detail for item in statuses if not item.runnable)
        if not self.hardware.ffmpeg:
            missing.append("FFmpeg 未安装")
        if missing:
            QMessageBox.warning(self, "改词组件尚未就绪", "无法开始真实推理：\n\n" + "\n".join(f"• {item}" for item in missing))
            return
        payload["root"] = str(self.paths.root)
        try:
            job_id = self.jobs.submit_lyric(payload)
        except Exception as exc:
            QMessageBox.critical(self, "无法创建改词任务", str(exc))
            return
        QMessageBox.information(self, "改词任务已创建", f"任务 {job_id[:8]} 已在独立进程启动。")
        self.navigate("任务记录")

    def select_model(self, engine: str, model_id: str) -> None:
        page = self.pages.get("原词翻唱")
        if not isinstance(page, CoverPage):
            return
        page.engine.setCurrentText(engine.upper())
        index = page.voice.findData(model_id)
        if index >= 0:
            page.voice.setCurrentIndex(index)
        self.navigate("原词翻唱")

    def _job_finished(self, job_id: str, success: bool) -> None:
        self._models_changed()
        history = self.pages.get("任务记录")
        if isinstance(history, HistoryPage):
            history.refresh()
        job = self.database.get_job(job_id)
        title = "任务完成" if success else "任务未完成"
        detail = Path(str(job.get("output_path"))).name if success and job and job.get("output_path") else str(job.get("error", "请查看任务记录")) if job else "请查看任务记录"
        self.tray.setToolTip("OpenCover Studio · 当前无任务")
        self.tray_status_action.setText("当前无任务")
        self.tray.showMessage(title, detail, QSystemTrayIcon.MessageIcon.Information if success else QSystemTrayIcon.MessageIcon.Warning, 5000)

    def _job_event(self, job_id: str, event: object) -> None:
        job = self.database.get_job(job_id)
        if not job:
            return
        value = int(job.get("progress") or 0)
        stage = str(job.get("stage") or "运行中")
        label = f"任务 {job_id[:8]} · {value}% · {stage}"
        self.tray.setToolTip(f"OpenCover Studio · {label}")
        self.tray_status_action.setText(label)

    def _tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        tray_icon = self.windowIcon()
        self.tray.setIcon(tray_icon if not tray_icon.isNull() else self.style().standardIcon(self.style().StandardPixmap.SP_MediaVolume))
        menu = self.tray.contextMenu() or None
        from PySide6.QtWidgets import QMenu
        menu = QMenu(); self.tray_status_action = QAction("当前无任务", self); self.tray_status_action.setEnabled(False); show = QAction("打开 OpenCover Studio", self); show.triggered.connect(self.showNormal); output = QAction("打开输出目录", self); output.triggered.connect(lambda: QDesktopServices.openUrl(self.paths.workspace.joinpath("outputs").as_uri())); cancel = QAction("取消全部任务", self); cancel.triggered.connect(lambda: [self.jobs.cancel(job_id) for job_id in list(self.jobs.processes)]); quit_action = QAction("退出", self); quit_action.triggered.connect(QApplication.quit); menu.addActions([self.tray_status_action, show, output, cancel, quit_action]); self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None); self.tray.show()
        if self.jobs.recovered_jobs:
            self.tray.showMessage("已恢复任务记录", f"检测到 {self.jobs.recovered_jobs} 个上次中断的任务，已标记失败；可在任务记录中重新生成。", QSystemTrayIcon.MessageIcon.Warning, 6000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.app_settings.window_width = self.width(); self.app_settings.window_height = self.height(); self.app_settings.save(self.paths.workspace / "settings.json")
        if self.jobs.running():
            dialog = QMessageBox(QMessageBox.Icon.Question, "任务仍在运行", "当前任务仍在运行。请选择处理方式。", parent=self)
            background = dialog.addButton("继续后台运行", QMessageBox.ButtonRole.AcceptRole); cancel = dialog.addButton("取消任务并退出", QMessageBox.ButtonRole.DestructiveRole); back = dialog.addButton("返回软件", QMessageBox.ButtonRole.RejectRole)
            dialog.exec(); clicked = dialog.clickedButton()
            if clicked is background: self.hide(); event.ignore(); return
            if clicked is back: event.ignore(); return
            if clicked is cancel:
                for job_id in list(self.jobs.processes): self.jobs.cancel(job_id)
        elif self.app_settings.minimize_to_tray:
            self.hide(); self.tray.showMessage("OpenCover Studio", "软件仍在系统托盘运行。可从托盘菜单退出。", QSystemTrayIcon.MessageIcon.Information, 3000); event.ignore(); return
        event.accept()
