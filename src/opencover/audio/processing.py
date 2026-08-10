from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf


class AudioError(RuntimeError):
    pass


def ffmpeg_path(root: Path) -> Path | None:
    local = root / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local.is_file():
        return local
    nested = next((path for path in (root / "ffmpeg").glob("*/bin/ffmpeg.exe") if path.is_file()), None)
    if nested:
        return nested
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def normalize_input(source: Path, target: Path, ffmpeg: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s24le", str(target)],
        capture_output=True, text=True, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not target.is_file() or target.stat().st_size < 1024:
        raise AudioError(result.stderr.strip() or "FFmpeg 标准化失败")
    return target


def validate_audio(path: Path) -> tuple[int, int, float]:
    try:
        info = sf.info(path)
    except RuntimeError as exc:
        raise AudioError("无法读取音频") from exc
    if info.frames <= 0 or info.samplerate < 8000 or info.channels not in {1, 2}:
        raise AudioError("音频参数不受支持")
    return info.samplerate, info.channels, info.duration


def mix_tracks(vocal_path: Path, accompaniment_path: Path, output: Path, balance: str = "均衡") -> Path:
    vocal, sr_v = sf.read(vocal_path, always_2d=True, dtype="float32")
    accompaniment, sr_a = sf.read(accompaniment_path, always_2d=True, dtype="float32")
    if sr_v != sr_a:
        raise AudioError("混音前采样率必须一致")
    channels = max(vocal.shape[1], accompaniment.shape[1])
    if vocal.shape[1] == 1 and channels == 2:
        vocal = np.repeat(vocal, 2, axis=1)
    if accompaniment.shape[1] == 1 and channels == 2:
        accompaniment = np.repeat(accompaniment, 2, axis=1)
    length = max(len(vocal), len(accompaniment))
    vocal = np.pad(vocal, ((0, length - len(vocal)), (0, 0)))
    accompaniment = np.pad(accompaniment, ((0, length - len(accompaniment)), (0, 0)))
    gains = {"人声更突出": (1.0, 0.70), "均衡": (0.92, 0.82), "伴奏更突出": (0.72, 1.0)}
    vocal_gain, accompaniment_gain = gains.get(balance, gains["均衡"])
    meter = pyln.Meter(sr_v)
    try:
        vocal_lufs = meter.integrated_loudness(vocal)
        accompaniment_lufs = meter.integrated_loudness(accompaniment)
        if np.isfinite(vocal_lufs):
            vocal *= 10.0 ** ((-18.0 - vocal_lufs) / 20.0)
        if np.isfinite(accompaniment_lufs):
            accompaniment *= 10.0 ** ((-20.0 - accompaniment_lufs) / 20.0)
    except (ValueError, OverflowError):
        pass
    mixed = vocal * vocal_gain + accompaniment * accompaniment_gain
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.98:
        mixed *= 0.98 / peak
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, mixed, sr_v, subtype="PCM_24")
    validate_audio(output)
    return output


def export_audio(source: Path, target: Path, ffmpeg: Path) -> Path:
    """Export a verified WAV mix without ever replacing the user's input."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".wav":
        shutil.copy2(source, target)
    else:
        codec = {".flac": ["-c:a", "flac"], ".mp3": ["-c:a", "libmp3lame", "-b:a", "320k"]}.get(target.suffix.lower())
        if codec is None:
            raise AudioError(f"不支持的输出格式：{target.suffix}")
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *codec, str(target)],
            capture_output=True, text=True, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise AudioError(result.stderr.strip() or "FFmpeg 导出失败")
    validate_audio(target)
    return target
