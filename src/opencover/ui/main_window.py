from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from opencover import __version__
from opencover.adapters.backends import DDSPAdapter, MSSTAdapter, MarkerBackendAdapter, RVCAdapter
from opencover.config import Settings
from opencover.core.hardware_detector import HardwareInfo
from opencover.core.job_manager import JobManager
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


class HomePage(QWidget):
    navigate = Signal(str)
    import_requested = Signal()

    def __init__(self, hardware: HardwareInfo):
        super().__init__()
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
        status_layout.addWidget(QLabel("尚未完整安装"), 1, 2)
        install = QPushButton("查看组件")
        install.clicked.connect(lambda: self.navigate.emit("组件管理"))
        import_voice = QPushButton("导入音色")
        import_voice.clicked.connect(self.import_requested)
        status_layout.addWidget(install, 2, 0); status_layout.addWidget(import_voice, 2, 1)
        layout.addWidget(status)
        layout.addStretch()


class CoverPage(QWidget):
    start_requested = Signal(dict)
    import_requested = Signal()

    def __init__(self, registry: ModelRegistry):
        super().__init__(); self.registry = registry; self.selected_model: str | None = None
        page, layout = panel_layout("原词翻唱", "拖入歌曲，选择引擎和音色，然后生成。推理在独立工作进程运行。")
        QVBoxLayout(self).addWidget(page)
        self.drop = AudioDropArea(); layout.addWidget(self.drop)
        controls = QFrame(); controls.setObjectName("Panel")
        form = QGridLayout(controls); form.setContentsMargins(18, 16, 18, 16)
        self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.voice = QComboBox(); self.pitch = QSpinBox(); self.pitch.setRange(-12, 12); self.pitch.setSpecialValueText("自动")
        self.balance = QComboBox(); self.balance.addItems(["均衡", "人声更突出", "伴奏更突出"])
        self.output_format = QComboBox(); self.output_format.addItems(["WAV", "FLAC", "MP3"])
        form.addWidget(QLabel("引擎"), 0, 0); form.addWidget(self.engine, 0, 1)
        form.addWidget(QLabel("音色"), 0, 2); form.addWidget(self.voice, 0, 3)
        form.addWidget(QLabel("升降调"), 1, 0); form.addWidget(self.pitch, 1, 1)
        form.addWidget(QLabel("混音"), 1, 2); form.addWidget(self.balance, 1, 3)
        form.addWidget(QLabel("输出"), 2, 0); form.addWidget(self.output_format, 2, 1)
        self.import_button = QPushButton("导入音色"); self.start = QPushButton("开始翻唱"); self.start.setObjectName("Primary")
        form.addWidget(self.import_button, 2, 2); form.addWidget(self.start, 2, 3)
        self.engine.currentTextChanged.connect(self.refresh_models); self.import_button.clicked.connect(self.import_requested)
        self.start.clicked.connect(self._start); layout.addWidget(controls); layout.addStretch(); self.refresh_models()

    def refresh_models(self) -> None:
        self.voice.clear(); models = self.registry.scan(self.engine.currentText().lower())
        for model in models: self.voice.addItem(model.display_name, model.id)
        self.voice.setPlaceholderText("请先导入音色" if not models else "选择音色")

    def _start(self) -> None:
        if not self.drop.path: QMessageBox.warning(self, "缺少歌曲", "请先拖入或选择歌曲。"); return
        if self.voice.currentData() is None: QMessageBox.warning(self, "缺少音色", "当前引擎没有可用音色，请先导入。"); return
        self.start_requested.emit({"input_path": str(self.drop.path), "engine": self.engine.currentText().lower(),
            "model_id": self.voice.currentData(), "options": {"pitch": self.pitch.value(),
            "balance": self.balance.currentText(), "output_format": self.output_format.currentText().lower()}})


class LyricPage(QWidget):
    def __init__(self):
        super().__init__(); page, layout = panel_layout("改词翻唱 Beta", "Beta：复杂歌词可能出现咬字、节奏或旋律偏差。")
        QVBoxLayout(self).addWidget(page); drop = AudioDropArea(); layout.addWidget(drop)
        fields = QFrame(); fields.setObjectName("Panel"); form = QFormLayout(fields); form.setContentsMargins(18, 16, 18, 16)
        original = QTextEdit(); original.setPlaceholderText("粘贴原歌词，或导入 TXT/LRC"); original.setMaximumHeight(105)
        new = QTextEdit(); new.setPlaceholderText("粘贴新歌词"); new.setMaximumHeight(105)
        form.addRow("原歌词", original); form.addRow("新歌词", new)
        disabled = QPushButton("安装改词扩展后生成"); disabled.setEnabled(False); form.addRow("", disabled)
        note = QLabel("Vevo2、GAME 与 DiffSinger 尚未在本机完成真实推理验证，因此不会标记为可用。")
        note.setWordWrap(True); note.setObjectName("Muted"); form.addRow("当前状态", note)
        layout.addWidget(fields); layout.addStretch()


class ImportVoiceDialog(QDialog):
    imported = Signal()
    preview_requested = Signal(str)

    def __init__(self, importer: ModelImporter, parent: QWidget | None = None):
        super().__init__(parent); self.importer = importer; self.setWindowTitle("导入音色"); self.resize(560, 440)
        form = QFormLayout(self); self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.weight = QLineEdit(); self.extra = QLineEdit(); self.name = QLineEdit(); self.description = QLineEdit()
        self.avatar = QLineEdit(); self.preview = QLineEdit()
        form.addRow("引擎", self.engine); form.addRow("模型权重", self._picker(self.weight, "权重 (*.pth *.pt *.ckpt)"))
        form.addRow("索引 / 配置", self._picker(self.extra, "索引或配置 (*.index *.yaml *.yml *.json)"))
        form.addRow("名称", self.name); form.addRow("简介", self.description)
        form.addRow("头像（可选）", self._picker(self.avatar, "图片 (*.png *.jpg *.jpeg *.webp)"))
        form.addRow("试听 WAV（可选）", self._picker(self.preview, "WAV (*.wav)"))
        hint = QLabel("未上传头像时生成首字母占位图。未上传试听时不显示“试听”，也不会用标准干声冒充结果。")
        hint.setWordWrap(True); hint.setObjectName("Muted"); form.addRow("", hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导入")
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self._import); form.addRow(buttons)

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
            model = self.importer.import_model(engine=self.engine.currentText().lower(), weight=Path(self.weight.text()),
                display_name=self.name.text(), description=self.description.text(), index_or_config=opt(self.extra),
                avatar=opt(self.avatar), preview=opt(self.preview))
        except Exception as exc: QMessageBox.critical(self, "导入失败", str(exc)); return
        self.imported.emit()
        if not model.preview:
            self.preview_requested.emit(model.id)
        self.accept()


class VoiceManagerPage(QWidget):
    import_requested = Signal()
    generate_requested = Signal(str)
    model_selected = Signal(str, str)
    def __init__(self, registry: ModelRegistry):
        super().__init__(); self.registry = registry; page, layout = panel_layout("音色管理", "音色按 RVC / DDSP 分开显示；元数据与权重文件分离保存。")
        QVBoxLayout(self).addWidget(page); tools = QHBoxLayout(); self.engine = QComboBox(); self.engine.addItems(["RVC", "DDSP"])
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索音色"); add = QPushButton("导入音色"); add.setObjectName("Primary")
        tools.addWidget(self.engine); tools.addWidget(self.search, 1); tools.addWidget(add); layout.addLayout(tools)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); layout.addWidget(self.scroll, 1)
        self.player = AudioPlayer(); layout.addWidget(self.player)
        self.engine.currentTextChanged.connect(self.refresh); self.search.textChanged.connect(self.refresh); add.clicked.connect(self.import_requested); self.refresh()
    def refresh(self) -> None:
        host = QWidget(); column = QVBoxLayout(host); needle = self.search.text().casefold()
        models = [m for m in self.registry.scan(self.engine.currentText().lower()) if needle in m.display_name.casefold()]
        if not models:
            if not needle or "丰川祥子" in needle or "祥子" in needle:
                pending = QFrame(); pending.setObjectName("Panel"); row = QHBoxLayout(pending)
                avatar = QLabel(); avatar.setFixedSize(72, 72)
                avatar_path = self.registry.weights_root.parent / "assets" / "祥子音色头像.jpg"
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
    def __init__(self, database: Database):
        super().__init__(); self.database = database; page, layout = panel_layout("任务记录", "本地 SQLite 记录；失败不会被隐藏。")
        QVBoxLayout(self).addWidget(page); self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["歌曲", "引擎", "音色", "状态", "进度", "输出"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1); refresh = QPushButton("刷新"); refresh.clicked.connect(self.refresh); layout.addWidget(refresh); self.refresh()
    def refresh(self) -> None:
        rows = self.database.list_jobs(); self.table.setRowCount(len(rows))
        for r, job in enumerate(rows):
            values = [Path(str(job["input_path"])).name, job["engine"], job["model_id"], job["status"], f"{job['progress']}%", job["output_path"] or "—"]
            for c, value in enumerate(values): self.table.setItem(r, c, QTableWidgetItem(str(value)))


class ComponentPage(QWidget):
    def __init__(self, paths: AppPaths):
        super().__init__(); page, layout = panel_layout("组件管理", "仅通过本机文件和真实 smoke test 判定状态。当前阶段不自动执行下载包内脚本。")
        QVBoxLayout(self).addWidget(page); self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["组件", "状态", "版本", "说明"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        statuses = [MSSTAdapter(paths.external_backends / "msst").status(), RVCAdapter(paths.external_backends / "rvc").status(), DDSPAdapter(paths.external_backends / "ddsp").status()]
        statuses += [
            MarkerBackendAdapter(paths.external_backends / "vevo2", "vevo2", "Vevo2").status(),
            MarkerBackendAdapter(paths.external_backends / "game", "game", "GAME").status(),
            MarkerBackendAdapter(paths.external_backends / "diffsinger", "diffsinger", "DiffSinger").status(),
        ]
        self.table.setRowCount(len(statuses))
        for r, item in enumerate(statuses):
            state = "可用" if item.runnable else ("未就绪" if item.installed else "未安装")
            for c, value in enumerate([item.name, state, item.version, item.detail]): self.table.setItem(r, c, QTableWidgetItem(str(value)))
        layout.addWidget(self.table, 1); open_folder = QPushButton("打开组件目录"); open_folder.clicked.connect(lambda: QDesktopServices.openUrl(Path(paths.external_backends).as_uri())); layout.addWidget(open_folder)


class SettingsPage(QWidget):
    def __init__(self, settings: Settings, hardware: HardwareInfo):
        super().__init__(); page, layout = panel_layout("设置", "硬件信息来自本机检测，CUDA 版本是驱动报告值，不代表 PyTorch 运行时已安装。")
        QVBoxLayout(self).addWidget(page); frame = QFrame(); frame.setObjectName("Panel"); form = QFormLayout(frame); form.setContentsMargins(18, 16, 18, 16)
        profile = QComboBox(); profile.addItems(["极低", "低", "标准", "高质量"]); profile.setCurrentText(settings.memory_profile)
        form.addRow("显存模式", profile); form.addRow("GPU", QLabel(hardware.gpu or "未检测到")); form.addRow("显存", QLabel(f"{hardware.vram_gb or '?'} GB")); form.addRow("驱动", QLabel(hardware.driver or "未知")); form.addRow("CUDA（驱动）", QLabel(hardware.cuda_reported or "未知")); form.addRow("FFmpeg", QLabel(hardware.ffmpeg or "未安装")); form.addRow("版本", QLabel(__version__)); layout.addWidget(frame); layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths, settings: Settings, hardware: HardwareInfo, database: Database):
        super().__init__(); self.paths = paths; self.app_settings = settings; self.hardware = hardware; self.database = database
        self.registry = ModelRegistry(paths.weights); self.importer = ModelImporter(paths.weights); self.jobs = JobManager(database, paths.root, self)
        self.setWindowTitle("OpenCover Studio"); self.setMinimumSize(900, 620); self.resize(settings.window_width, settings.window_height)
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
            " QWidget#ContentPage { background-color: rgba(248, 249, 247, 232); }"
        )

    def _add_pages(self) -> None:
        home = HomePage(self.hardware); cover = CoverPage(self.registry); voices = VoiceManagerPage(self.registry); history = HistoryPage(self.database)
        home.navigate.connect(self.navigate); home.import_requested.connect(self.import_voice); cover.import_requested.connect(self.import_voice); cover.start_requested.connect(self.start_job); voices.import_requested.connect(self.import_voice)
        voices.generate_requested.connect(self.start_preview_job); voices.model_selected.connect(self.select_model)
        self.jobs.finished.connect(self._job_finished)
        pages = {"首页": home, "原词翻唱": cover, "改词翻唱 Beta": LyricPage(), "音色管理": voices, "任务记录": history, "组件管理": ComponentPage(self.paths), "设置": SettingsPage(self.app_settings, self.hardware)}
        for name, page in pages.items(): self.pages[name] = page; self.stack.addWidget(page)

    def navigate(self, name: str) -> None:
        self.stack.setCurrentWidget(self.pages[name]); [button.setChecked(key == name) for key, button in self.nav_buttons.items()]; self.app_settings.last_page = name

    def import_voice(self) -> None:
        dialog = ImportVoiceDialog(self.importer, self)
        dialog.imported.connect(self._models_changed)
        dialog.preview_requested.connect(self.start_preview_job)
        dialog.exec()

    def _models_changed(self) -> None:
        page = self.pages["原词翻唱"]
        if isinstance(page, CoverPage): page.refresh_models()
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

    def _tray(self) -> None:
        self.tray = QSystemTrayIcon(self); self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MediaVolume)); menu = self.tray.contextMenu() or None
        from PySide6.QtWidgets import QMenu
        menu = QMenu(); show = QAction("打开 OpenCover Studio", self); show.triggered.connect(self.showNormal); output = QAction("打开输出目录", self); output.triggered.connect(lambda: QDesktopServices.openUrl(self.paths.workspace.joinpath("outputs").as_uri())); quit_action = QAction("退出", self); quit_action.triggered.connect(QApplication.quit); menu.addActions([show, output, quit_action]); self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None); self.tray.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.app_settings.window_width = self.width(); self.app_settings.window_height = self.height(); self.app_settings.save(self.paths.workspace / "settings.json")
        if self.jobs.running():
            result = QMessageBox.question(self, "任务仍在运行", "当前任务仍在运行。是否取消任务并退出？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if result == QMessageBox.StandardButton.No: event.ignore(); return
            for job_id in list(self.jobs.processes): self.jobs.cancel(job_id)
        event.accept()
