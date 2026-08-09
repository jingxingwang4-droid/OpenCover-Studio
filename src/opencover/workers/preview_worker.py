from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from opencover.adapters.backends import DDSPAdapter, RVCAdapter
from opencover.models.registry import ModelRegistry


def emit(kind: str, **data: object) -> None:
    print(json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(request_file: str) -> int:
    partial: Path | None = None
    try:
        data = json.loads(Path(request_file).read_text(encoding="utf-8"))
        root = Path(data["root"]).resolve()
        model = ModelRegistry(root / "weights").get(str(data["model_id"]))
        if model is None:
            raise RuntimeError("找不到所选音色")
        source = root / "assets" / "preview_sources" / "neutral_melody.wav"
        if not source.is_file():
            raise RuntimeError("标准试听干声未安装")
        model_dir = model.directory(root / "weights")
        weight = model_dir / model.model_files[0]
        partial = model_dir / "preview.part.wav"
        output = model_dir / "preview.wav"
        partial.unlink(missing_ok=True)
        emit("status", message="正在使用标准干声生成试听")
        emit("progress", stage="convert", value=15)
        if model.engine == "rvc":
            adapter = RVCAdapter(root / "external_backends" / "rvc")
            index = model_dir / model.index_files[0] if model.index_files else None
            adapter.convert(source, partial, weight, model.recommended_pitch, index)
        else:
            adapter = DDSPAdapter(root / "external_backends" / "ddsp")
            config = model_dir / model.config_files[0] if model.config_files else None
            adapter.convert(source, partial, weight, model.recommended_pitch, config)
        emit("progress", stage="validate", value=90)
        if not partial.is_file() or partial.stat().st_size < 1024:
            raise RuntimeError("试听推理未生成有效 WAV")
        partial.replace(output)
        metadata_path = model_dir / "model.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["preview"] = "preview.wav"
        metadata["preview_source"] = "generated"
        metadata["preview_source_audio"] = source.name
        metadata.setdefault("sha256", {})["preview.wav"] = _sha256(output)
        metadata_partial = model_dir / "model.json.part"
        metadata_partial.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata_partial.replace(metadata_path)
        emit("progress", stage="export", value=100)
        emit("result", path=str(output))
        return 0
    except Exception as exc:
        if partial is not None:
            partial.unlink(missing_ok=True)
        emit("error", code="PREVIEW_WORKER_ERROR", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
