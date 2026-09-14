from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QFormLayout, QSpinBox, QComboBox, QMessageBox, QProgressBar)

from opencover.pipelines.voice_training import VoiceTrainingPipeline


class TrainingPage(QWidget):
    start_requested = Signal(dict)

    def __init__(self, root: Path, jobs):
        super().__init__()
        self.root = root
        self.jobs = jobs
        self.job_id = None
        self.setObjectName("ContentPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(14)
        title = QLabel("音色训练"); title.setObjectName("PageTitle"); layout.addWidget(title)
        hint = QLabel("选择同一角色的清晰干声素材，合并、切片并训练专属音色。训练完成后可在原词翻唱中选用。"); hint.setWordWrap(True); layout.addWidget(hint)
        self.source = QLineEdit(); self.source.setPlaceholderText("选择音频文件或素材文件夹")
        source_row = QHBoxLayout(); source_row.addWidget(self.source)
        for label, directory in (("选择音频", False), ("选择文件夹", True)):
            button = QPushButton(label); button.clicked.connect(lambda checked=False, d=directory: self.browse(d)); source_row.addWidget(button)
        layout.addLayout(source_row)
        form = QFormLayout()
        self.name = QLineEdit(); self.name.setPlaceholderText("例如：长崎爽世")
        self.gender = QComboBox(); self.gender.addItem("未知", "unknown"); self.gender.addItem("女声", "female"); self.gender.addItem("男声", "male")
        self.seconds = QSpinBox(); self.seconds.setRange(2, 10); self.seconds.setValue(4); self.seconds.setSuffix(" 秒")
        self.epochs = QSpinBox(); self.epochs.setRange(1, 1000); self.epochs.setValue(100)
        self.batch = QSpinBox(); self.batch.setRange(1, 16); self.batch.setValue(4)
        self.batch.setToolTip("显存不足时调低；默认 4。训练与翻唱请依次运行。")
        form.addRow("音色名称", self.name); form.addRow("目标声部", self.gender)
        form.addRow("切片长度", self.seconds); form.addRow("训练轮数", self.epochs); form.addRow("每批切片数", self.batch)
        layout.addLayout(form)
        explanation = QLabel("切片工具会先将素材按文件名自然顺序合并，片段间保留 0.4 秒静音，再按停顿切片；长句带少量重叠。训练采用 RVC v2 / 40 kHz，需要 NVIDIA 显卡。请使用无伴奏、无其他角色声音的素材。"); explanation.setWordWrap(True); layout.addWidget(explanation)
        buttons = QHBoxLayout(); self.actions = []
        for label, action in (("仅合并音频", "merge"), ("合并并切片", "slice"), ("切片并开始训练", "train")):
            button = QPushButton(label); button.clicked.connect(lambda checked=False, a=action: self.start(a)); buttons.addWidget(button); self.actions.append(button)
        self.actions[-1].setObjectName("Primary")
        layout.addLayout(buttons)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.status = QLabel("尚未开始。训练输出、素材清单和日志保存在项目任务目录。"); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.cancel = QPushButton("取消当前任务"); self.cancel.setEnabled(False); self.cancel.clicked.connect(lambda: jobs.cancel(self.job_id) if self.job_id else None); layout.addWidget(self.cancel)
        layout.addStretch()
        jobs.event.connect(self.on_event); jobs.finished.connect(self.on_finished)

    def browse(self, directory):
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择训练素材文件夹")
        else:
            value, _ = QFileDialog.getOpenFileName(self, "选择音频", "", "音频 (*.wav *.flac *.mp3 *.m4a *.ogg *.aac)")
        if value:
            self.source.setText(value)

    def start(self, action):
        if self.jobs.running():
            QMessageBox.warning(self, "请等待当前任务", "请先完成或取消当前任务，再开始音色训练或切片。"); return
        options = {"action": action, "display_name": self.name.text().strip(), "voice_gender": self.gender.currentData(), "epochs": self.epochs.value(), "batch_size": self.batch.value(), "slice_seconds": self.seconds.value()}
        try:
            if not self.source.text().strip():
                raise ValueError("请选择训练素材")
            VoiceTrainingPipeline(self.root).preflight(Path(self.source.text().strip()), options)
            self.job_id = self.jobs.submit_training({"input_path": self.source.text().strip(), "options": options})
        except Exception as exc:
            QMessageBox.warning(self, "无法开始", str(exc)); return
        for button in self.actions: button.setEnabled(False)
        self.cancel.setEnabled(True); self.progress.setValue(0)
        self.status.setText(f"任务 {self.job_id[:8]} 已启动，可在任务记录查看日志与输出。")

    def on_event(self, job_id, event):
        if job_id == self.job_id:
            if event.value is not None: self.progress.setValue(event.value)
            if event.message: self.status.setText(event.message)

    def on_finished(self, job_id, success):
        if job_id != self.job_id: return
        for button in self.actions: button.setEnabled(True)
        self.cancel.setEnabled(False)
        job = self.jobs.database.get_job(job_id)
        self.status.setText(("完成：" + str(job.get("output_path"))) if success else ("任务未完成：" + str(job.get("error"))))
        if success: self.progress.setValue(100)
