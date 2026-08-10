from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml
from PIL import Image, ImageDraw, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opencover.core.download_manager import download_file
from opencover.workers.preview_worker import main as generate_preview


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundled_resources() -> dict[str, dict[str, object]]:
    manifest = yaml.safe_load((ROOT / "config" / "resource_manifest.yaml").read_text(encoding="utf-8"))
    return {
        str(item["voice_id"]): item
        for item in manifest["resources"]
        if item.get("type") == "voice_model" and item.get("bundled_default") is True
    }


def ensure_download(item: dict[str, object]) -> Path:
    voice_id = str(item["voice_id"])
    cache = ROOT / "downloads" / "bundled_voices" / f"{voice_id}.pth"
    expected_hash = str(item["sha256"])
    expected_size = int(item["file_size"])
    if cache.is_file():
        if cache.stat().st_size != expected_size or sha256(cache) != expected_hash:
            raise RuntimeError(f"下载缓存校验失败，不会覆盖：{cache}")
        print(f"复用已校验缓存：{cache.name}")
        return cache
    download_file(
        str(item["download_url"]), cache,
        expected_sha256=expected_hash, expected_size=expected_size, retries=5,
        progress=lambda done, total: print(
            f"\r{voice_id}: {done / 1024**2:.1f}/{(total or expected_size) / 1024**2:.1f} MiB",
            end="", flush=True,
        ),
    )
    print()
    return cache


def scan_checkpoint(path: Path) -> None:
    runtime = ROOT / "external_backends" / "rvc" / "runtime" / "Scripts" / "python.exe"
    if not runtime.is_file():
        raise RuntimeError("缺少 RVC 独立运行时，无法执行 checkpoint 安全扫描")
    code = (
        "import sys,torch; p=sys.argv[1]; "
        "u=torch.serialization.get_unsafe_globals_in_checkpoint(p); "
        "assert not u, f'unsafe globals: {u}'; "
        "d=torch.load(p,map_location='cpu',weights_only=True); "
        "assert isinstance(d,dict) and 'weight' in d and 'config' in d; print('checkpoint_safe')"
    )
    process = subprocess.run(
        [str(runtime), "-X", "utf8", "-c", code, str(path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, shell=False, timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode or "checkpoint_safe" not in process.stdout:
        raise RuntimeError((process.stderr or process.stdout or "checkpoint 安全扫描失败")[-4000:])


def ensure_avatar(target: Path, letter: str) -> Path:
    avatar = target / "avatar.webp"
    if avatar.is_file():
        try:
            with Image.open(avatar) as image:
                image.verify()
            return avatar
        except (UnidentifiedImageError, OSError) as exc:
            raise RuntimeError(f"已有头像损坏，不会覆盖：{avatar}") from exc
    image = Image.new("RGB", (512, 512), "#536B78")
    ImageDraw.Draw(image).text((256, 256), letter, fill="white", anchor="mm", font_size=220)
    image.save(avatar, "WEBP", quality=90)
    return avatar


def preview_evidence(path: Path, source: Path) -> dict[str, object]:
    audio, sample_rate = sf.read(path, always_2d=True)
    duration = len(audio) / sample_rate
    evidence = {
        "sha256": sha256(path), "seconds": duration, "sample_rate": sample_rate,
        "channels": audio.shape[1], "peak": float(np.max(np.abs(audio))),
        "rms": float(np.sqrt(np.mean(audio * audio))),
    }
    if not np.isfinite(audio).all() or not np.any(audio != 0) or not 8 <= duration <= 15:
        raise RuntimeError(f"试听音频数值无效：{path}")
    if evidence["sha256"] == sha256(source):
        raise RuntimeError(f"试听与标准干声完全相同，拒绝冒充推理结果：{path}")
    return evidence


def install_voice(item: dict[str, object], generate: bool) -> None:
    voice_id = str(item["voice_id"])
    metadata = dict(item["voice_metadata"])
    cache = ensure_download(item)
    scan_checkpoint(cache)
    target = ROOT / "weights" / "rvc" / "bundled" / voice_id
    target.mkdir(parents=True, exist_ok=True)
    weight = target / "model.pth"
    if weight.is_file():
        if weight.stat().st_size != int(item["file_size"]) or sha256(weight) != str(item["sha256"]):
            raise RuntimeError(f"已有内置权重不匹配，不会覆盖：{weight}")
    else:
        partial = weight.with_suffix(".pth.part")
        shutil.copy2(cache, partial)
        partial.replace(weight)
    avatar = ensure_avatar(target, str(item["avatar_letter"]))
    source = ROOT / "assets" / "preview_sources" / "neutral_melody.wav"
    preview = target / "preview.wav"
    hashes = {"model.pth": sha256(weight), "avatar.webp": sha256(avatar)}
    preview_ok = False
    if preview.is_file():
        evidence = preview_evidence(preview, source)
        hashes["preview.wav"] = str(evidence["sha256"])
        preview_ok = True
    model_data = {
        **metadata,
        "id": voice_id, "engine": "rvc", "model_files": ["model.pth"],
        "index_files": [], "config_files": [], "avatar": "avatar.webp",
        "preview": "preview.wav" if preview_ok else None,
        "preview_source": "generated" if preview_ok else "none",
        "preview_source_audio": source.name if preview_ok else None,
        "source": item["source_page"], "author": item["author"], "license": item["license"],
        "redistribution_allowed": True, "sha256": hashes, "bundled": True,
    }
    metadata_path = target / "model.json"
    partial_metadata = metadata_path.with_suffix(".json.part")
    partial_metadata.write_text(json.dumps(model_data, ensure_ascii=False, indent=2), encoding="utf-8")
    partial_metadata.replace(metadata_path)
    if generate and not preview_ok:
        request_dir = ROOT / "workspace" / "test_outputs" / "bundled_voice_install"
        request_dir.mkdir(parents=True, exist_ok=True)
        request = request_dir / f"{voice_id}.json"
        request.write_text(json.dumps({
            "kind": "preview", "root": str(ROOT), "model_id": voice_id,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if generate_preview(str(request)):
            raise RuntimeError(f"{voice_id} 真实试听推理失败")
    if generate:
        evidence = preview_evidence(preview, source)
        print(f"{voice_id}: 安装与真实试听通过 {json.dumps(evidence, ensure_ascii=False)}")
    else:
        print(f"{voice_id}: 安装与 checkpoint 安全扫描通过；尚未生成试听")


def main() -> int:
    parser = argparse.ArgumentParser(description="安装并核验可再分发的 OpenCover Studio 内置 RVC 音色")
    parser.add_argument("--voice", action="append", help="只安装指定 voice_id，可重复")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--generate-previews", action="store_true", help="使用标准干声运行真实 RVC 推理")
    args = parser.parse_args()
    os.environ["HTTP_PROXY"] = args.proxy
    os.environ["HTTPS_PROXY"] = args.proxy
    resources = bundled_resources()
    selected = args.voice or list(resources)
    unknown = [voice for voice in selected if voice not in resources]
    if unknown:
        parser.error("未知或不可再分发的内置音色：" + ", ".join(unknown))
    for voice_id in selected:
        install_voice(resources[voice_id], args.generate_previews)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
