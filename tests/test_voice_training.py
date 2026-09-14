import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QObject, Signal

from opencover.audio.processing import ffmpeg_path
from opencover.core.worker_protocol import WorkerEvent
from opencover.pipelines.voice_training import audio_sources, merge_audio, validate_options
from opencover.ui.training_page import TrainingPage


def test_merge_resamples_orders_and_preserves_sources(tmp_path):
    ffmpeg = ffmpeg_path(Path(__file__).resolve().parents[1])
    if not ffmpeg: pytest.skip("ffmpeg unavailable")
    folder = tmp_path / "素材"; folder.mkdir()
    sf.write(folder / "soyo (10).wav", np.full((16000, 2), .2), 16000)
    sf.write(folder / "soyo (2).wav", np.full(8000, .1), 8000)
    (folder / "notes.txt").write_text("ignore me")
    sources = audio_sources(folder)
    assert sources[0].name == "soyo (2).wav"
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    target = tmp_path / "output/merged.wav"
    manifest = merge_audio(sources, target, ffmpeg)
    output, sr = sf.read(target)
    assert sr == 40000 and output.ndim == 1
    assert len(output) == 96000
    assert np.allclose(output[100:39900], .1, atol=1e-4)
    assert np.max(np.abs(output[40000:56000])) == 0
    assert np.allclose(output[56100:-100], .2, atol=1e-4)
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    assert manifest["sources"][1]["start_frame"] == 56000
    assert not (target.parent / "decoded.wav").exists()


def test_silent_audio_fails(tmp_path):
    ffmpeg = ffmpeg_path(Path(__file__).resolve().parents[1])
    if not ffmpeg: pytest.skip("ffmpeg unavailable")
    source = tmp_path / "silent.wav"; sf.write(source, np.zeros(16000), 16000)
    with pytest.raises(ValueError, match="静音"):
        merge_audio([source], tmp_path / "out/merged.wav", ffmpeg)


@pytest.mark.parametrize("field,value", [("epochs", 0), ("epochs", True), ("batch_size", 17), ("slice_seconds", 1), ("action", "other"), ("display_name", " ")])
def test_invalid_training_options(field, value):
    with pytest.raises(ValueError): validate_options({"display_name": "爽世", field: value})


def test_training_page_submits_and_handles_cancel(qtbot, tmp_path, monkeypatch):
    class Jobs(QObject):
        event = Signal(str, object)
        finished = Signal(str, bool)
        database = None
        def running(self): return False
        def submit_training(self, payload): self.payload = payload; return "test-training"
        def cancel(self, job_id): self.cancelled = job_id
    jobs = Jobs()
    page = TrainingPage(tmp_path, jobs); qtbot.addWidget(page)
    monkeypatch.setattr("opencover.ui.training_page.VoiceTrainingPipeline.preflight", lambda *args: None)
    page.source.setText("素材.wav"); page.name.setText("长崎爽世")
    page.actions[-1].click()
    assert jobs.payload["options"]["action"] == "train"
    assert jobs.payload["options"]["display_name"] == "长崎爽世"
    assert all(not button.isEnabled() for button in page.actions)
    jobs.event.emit("test-training", WorkerEvent(type="progress", value=70, message="训练 50/100 轮"))
    assert page.progress.value() == 70
    page.cancel.click(); assert jobs.cancelled == "test-training"
