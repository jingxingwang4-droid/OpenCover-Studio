from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt


AUDIO_FILTER = "音频文件 (*.wav *.flac *.mp3 *.m4a *.aac *.ogg);;所有文件 (*)"


class AudioDropArea(QFrame):
    path_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(116)
        self.setStyleSheet("QFrame { background:#fafbfa; border:1px dashed #9caaac; border-radius:6px; }")
        layout = QVBoxLayout(self)
        self.label = QLabel("拖入歌曲，或点击选择音频")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("border:0; font-size:15px; color:#506066;")
        layout.addWidget(self.label)
        self.path: Path | None = None

    def mousePressEvent(self, event):  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            selected, _ = QFileDialog.getOpenFileName(self, "选择歌曲", "", AUDIO_FILTER)
            if selected:
                self.set_path(Path(selected))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
            path = Path(event.mimeData().urls()[0].toLocalFile())
            if path.suffix.lower() in {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg"}:
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_path(Path(event.mimeData().urls()[0].toLocalFile()))

    def set_path(self, path: Path) -> None:
        self.path = path
        self.label.setText(f"已选择：{path.name}\n{path.parent}")
        self.path_changed.emit(str(path))


class AudioPlayer(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(0.65)
        self.player.setAudioOutput(self.output)
        layout = QHBoxLayout(self)
        self.play = QPushButton("播放")
        self.play.setEnabled(False)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 0)
        self.time = QLabel("00:00 / 00:00")
        layout.addWidget(self.play)
        layout.addWidget(self.position, 1)
        layout.addWidget(self.time)
        self.play.clicked.connect(self.toggle)
        self.player.durationChanged.connect(lambda d: self.position.setRange(0, d))
        self.player.positionChanged.connect(self._position)
        self.position.sliderMoved.connect(self.player.setPosition)

    def set_source(self, path: Path | None) -> None:
        valid = bool(path and path.is_file())
        self.play.setEnabled(valid)
        self.player.setSource(QUrl.fromLocalFile(str(path))) if valid else self.player.setSource(QUrl())

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play.setText("播放")
        else:
            self.player.play()
            self.play.setText("暂停")

    def _position(self, value: int) -> None:
        self.position.setValue(value)
        duration = self.player.duration()
        fmt = lambda ms: f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}"
        self.time.setText(f"{fmt(value)} / {fmt(duration)}")


class VoiceCard(QFrame):
    selected = Signal(str)
    preview_requested = Signal(str)
    manage_requested = Signal(str)

    def __init__(self, model, directory: Path, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QHBoxLayout(self)
        avatar = QLabel()
        avatar.setFixedSize(72, 72)
        avatar.setStyleSheet("background:#dfe5e3; border-radius:5px;")
        if model.avatar and (directory / model.avatar).is_file():
            pixmap = QPixmap(str(directory / model.avatar))
            avatar.setPixmap(pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        text = QVBoxLayout()
        title = QLabel(model.display_name)
        title.setObjectName("CardTitle")
        description = QLabel(model.description or "未填写简介")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        tag = QLabel(f"{model.engine.upper()} · {'内置' if model.bundled else '用户导入'}")
        tag.setObjectName("Muted")
        text.addWidget(title)
        text.addWidget(description)
        text.addWidget(tag)
        buttons = QVBoxLayout()
        preview = QPushButton("试听" if model.preview else "生成试听")
        choose = QPushButton("选择")
        manage = QPushButton("管理")
        choose.setObjectName("Primary")
        preview.clicked.connect(lambda: self.preview_requested.emit(model.id))
        choose.clicked.connect(lambda: self.selected.emit(model.id))
        manage.clicked.connect(lambda: self.manage_requested.emit(model.id))
        buttons.addWidget(preview)
        buttons.addWidget(choose)
        buttons.addWidget(manage)
        layout.addWidget(avatar)
        layout.addLayout(text, 1)
        layout.addLayout(buttons)
