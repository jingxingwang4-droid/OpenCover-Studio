"""Run real workers through JobManager and retain auditable acceptance artifacts.

Uses installed backends; no downloads or substitutions. Run with the project venv.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import soundfile as sf
from PySide6.QtCore import QCoreApplication, QTimer

from opencover.audio.processing import validate_audio, normalize_input, ffmpeg_path
from opencover.core.job_manager import JobManager
from opencover.storage.database import Database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lyrics-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rvc-voice", default="toyokawa_sakiko_rvc")
    parser.add_argument("--ddsp-voice", default="toyokawa_sakiko_ddsp_local_v1")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "source.wav"
    shutil.copyfile(args.source, source)
    duration = validate_audio(source, require_signal=True)[2]
    reference = destination / "normalized_reference.wav"
    normalize_input(source, reference, ffmpeg_path(root))
    lyric = json.loads(args.lyrics_request.read_text(encoding="utf-8"))
    cases = [
        ("original_rvc", dict(input_path=str(source), engine="rvc", model_id=args.rvc_voice, options={"output_format": "flac"})),
        ("original_ddsp", dict(input_path=str(source), engine="ddsp", model_id=args.ddsp_voice, options={"output_format": "wav"})),
        ("lyric_native", {**lyric, "input_path": str(source)}),
        ("lyric_rvc", {**lyric, "input_path": str(source), "engine": "rvc", "model_id": args.rvc_voice}),
    ]
    app = QCoreApplication([])
    db = Database(destination / "acceptance.sqlite")
    manager = JobManager(db, root)
    results = []
    current = {}

    def save():
        (destination / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def start():
        if not cases:
            app.quit()
            return
        label, payload = cases.pop(0)
        current.update(label=label, started=time.monotonic())
        print("START", label, flush=True)
        submit = manager.submit_lyric if label.startswith("lyric") else manager.submit_original
        current["id"] = submit(payload)

    def finished(jid, success):
        row = db.get_job(jid)
        result = dict(case=current["label"], job_id=jid, worker_success=success,
                      elapsed_seconds=round(time.monotonic() - current["started"], 2),
                      job_dir=str(root / "workspace/jobs" / jid), listening_accepted=False)
        try:
            if not success:
                raise RuntimeError(row["error"] or "worker failed")
            output = Path(row["output_path"])
            rate, channels, actual_duration = validate_audio(output, require_signal=True, expected_duration=duration)
            audio, _ = sf.read(output, always_2d=True, dtype="float32")
            result.update(output=str(output), rate=rate, channels=channels, duration=actual_duration,
                          peak=float(np.max(np.abs(audio))), rms=float(np.sqrt(np.mean(audio.astype(np.float64)**2))))
            job = root / "workspace/jobs" / jid
            if current["label"].startswith("lyric"):
                intervals = json.loads((job / "edit_intervals.json").read_text(encoding="utf-8"))
                validation = json.loads((job / "validation.json").read_text(encoding="utf-8"))
                original, source_rate = sf.read(reference, always_2d=True, dtype="float32")
                if validation['workflow'] == 'consistent_voice_v1':
                    assembly = validation['mixing']['assembly']
                    original, source_rate = sf.read(assembly['source'], always_2d=True, dtype='float32')
                    audio, rate = sf.read(assembly['assembled'], always_2d=True, dtype='float32')
                    result['preservation_scope'] = 'original vocal performance before full-track voice conversion'
                assert source_rate == rate and original.shape == audio.shape, "normalized source and output formats differ"
                mask = np.ones(len(audio), dtype=bool)
                for start_time, end_time in intervals:
                    mask[round(start_time * rate):round(end_time * rate)] = False
                result["unchanged_samples_identical"] = bool(np.array_equal(original[mask], audio[mask]))
                assert result["unchanged_samples_identical"], "unmodified audio changed"
                result["lyric_validation"] = validation
            result["technical_passed"] = True
        except Exception as exc:
            result.update(technical_passed=False, error=str(exc))
        results.append(result)
        save()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        QTimer.singleShot(0, start)

    manager.finished.connect(finished)
    manager.event.connect(lambda jid, event: print(jid, event.model_dump_json(), flush=True) if event.type in {"status", "error"} else None)
    QTimer.singleShot(0, start)
    app.exec()
    return 0 if len(results) == 4 and all(r["technical_passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
