from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccompanimentGuardResult:
    muted: bool
    source_correlation: float
    vocal_correlation: float
    accompaniment_source_ratio: float
    vocal_source_ratio: float


@dataclass(frozen=True)
class RhythmComparison:
    score: float
    envelope_correlation: float
    onset_correlation: float
    reliable: bool


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


def fit_audio_duration(
    source: Path,
    target: Path,
    ffmpeg: Path,
    target_duration: float,
    *,
    minimum_tempo: float = 0.80,
    maximum_tempo: float = 1.25,
    tolerance_seconds: float = 0.04,
) -> Path:
    """Fit a generated phrase without changing its pitch or formants.

    ``tempo`` is input duration divided by requested output duration.  Large
    corrections are rejected instead of turning a bad generation into a
    pitch-correct but badly smeared phrase.  Padding/trimming after Rubber Band
    only absorbs encoder and window rounding at the phrase boundary.
    """
    if target_duration <= 0:
        raise AudioError("目标短句时长无效")
    try:
        source_duration = sf.info(source).duration
    except (OSError, RuntimeError) as exc:
        raise AudioError("无法读取待校时的生成短句") from exc
    if source_duration <= 0:
        raise AudioError("生成短句没有有效时长")
    tempo = source_duration / target_duration
    if not minimum_tempo <= tempo <= maximum_tempo:
        raise AudioError(
            f"生成短句与目标时长相差过大（{source_duration:.2f}s / {target_duration:.2f}s）；"
            "为避免严重拉伸失真，请缩短新歌词或重新生成"
        )

    filters: list[str] = []
    if abs(source_duration - target_duration) > tolerance_seconds:
        filters.append(
            "rubberband="
            f"tempo={tempo:.9f}:pitch=1:transients=smooth:detector=soft:"
            "phase=independent:window=long:smoothing=on:formant=preserved:pitchq=quality"
        )
    filters.extend([
        "aresample=44100",
        "aformat=sample_fmts=fltp:channel_layouts=mono",
        "apad",
        f"atrim=duration={target_duration:.9f}",
    ])
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", ",".join(filters), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s24le", str(target)],
        capture_output=True, text=True, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not target.is_file() or target.stat().st_size < 1024:
        raise AudioError(result.stderr.strip() or "生成短句保音高时长校正失败")
    _, _, actual_duration = validate_audio(target)
    if abs(actual_duration - target_duration) > max(0.03, 2 / 44100):
        raise AudioError(
            f"生成短句校时结果异常（{actual_duration:.3f}s / {target_duration:.3f}s）"
        )
    return target


def restore_vocal_detail(
    converted: Path,
    source_vocal: Path,
    target: Path,
    ffmpeg: Path,
    *,
    detail_mix: float = 0.0,
    detail_cutoff_hz: int = 4000,
    treble_db: float = 0.0,
    converted_gain: float = 1.0,
) -> Path:
    """Restore presence and air without synthesizing new harmonics.

    A steep high-passed copy of the source restores consonants and upper-formant
    transients. The converted signal still owns the fundamental, melody, vowels,
    and most of the vocal identity. Harmonic exciters are avoided because their
    added distortion can exaggerate metallic artifacts in converted vocals.
    """
    if detail_mix <= 0 and abs(treble_db) < 1e-6 and abs(converted_gain - 1.0) < 1e-6:
        return normalize_input(converted, target, ffmpeg)
    target.parent.mkdir(parents=True, exist_ok=True)
    main_filters = ["aresample=44100", "aformat=channel_layouts=mono"]
    if abs(treble_db) >= 1e-6:
        main_filters.append(f"treble=g={treble_db:g}:f=4200")
    main_filters.append(f"volume={converted_gain:g}")
    detail_filter = (
        "aresample=44100,aformat=channel_layouts=mono,"
        f"highpass=f={detail_cutoff_hz}:p=2,lowpass=f=16000:p=2,volume={detail_mix:g}"
    )
    graph = (
        f"[0:a]{','.join(main_filters)}[main];"
        f"[1:a]{detail_filter}[detail];"
        "[main][detail]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95:level=0[out]"
    )
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(converted), "-i", str(source_vocal), "-filter_complex", graph,
         "-map", "[out]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s24le", str(target)],
        capture_output=True, text=True, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or not target.is_file() or target.stat().st_size < 1024:
        raise AudioError(result.stderr.strip() or "人声细节恢复失败")
    validate_audio(target)
    return target


def validate_audio(path: Path) -> tuple[int, int, float]:
    try:
        info = sf.info(path)
    except RuntimeError as exc:
        raise AudioError("无法读取音频") from exc
    if info.frames <= 0 or info.samplerate < 8000 or info.channels not in {1, 2}:
        raise AudioError("音频参数不受支持")
    return info.samplerate, info.channels, info.duration


def guard_lyric_accompaniment(
    source_mix_path: Path,
    vocal_path: Path,
    accompaniment_path: Path,
    output: Path,
) -> AccompanimentGuardResult:
    """Remove a separator's fake accompaniment when it is really scaled lead vocal.

    Vocal separators can return a quiet, near-identical copy of a dry vocal in
    their ``Instrumental`` stem.  Loudness normalization would then amplify and
    mix the original singer straight back into a changed-lyrics result.  The
    guard only mutes the stem when both separator outputs still closely follow a
    vocal-dominated source; ordinary music accompaniment is preserved.
    """
    source, source_rate = sf.read(source_mix_path, always_2d=True, dtype="float32")
    vocal, vocal_rate = sf.read(vocal_path, always_2d=True, dtype="float32")
    accompaniment, accompaniment_rate = sf.read(accompaniment_path, always_2d=True, dtype="float32")
    if len({source_rate, vocal_rate, accompaniment_rate}) != 1:
        raise AudioError("伴奏残留检测前采样率必须一致")

    length = min(len(source), len(vocal), len(accompaniment))
    if length <= 0:
        raise AudioError("伴奏残留检测收到空音频")
    source_mono = np.mean(source[:length], axis=1, dtype=np.float32)
    vocal_mono = np.mean(vocal[:length], axis=1, dtype=np.float32)
    accompaniment_mono = np.mean(accompaniment[:length], axis=1, dtype=np.float32)

    def rms(values: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))

    def correlation(left: np.ndarray, right: np.ndarray) -> float:
        left_centered = left.astype(np.float64) - float(np.mean(left))
        right_centered = right.astype(np.float64) - float(np.mean(right))
        denominator = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
        if denominator <= 1e-12:
            return 0.0
        return abs(float(np.dot(left_centered, right_centered) / denominator))

    source_rms = rms(source_mono)
    vocal_rms = rms(vocal_mono)
    accompaniment_rms = rms(accompaniment_mono)
    source_correlation = correlation(source_mono, accompaniment_mono)
    vocal_correlation = correlation(source_mono, vocal_mono)
    vocal_source_ratio = vocal_rms / max(source_rms, 1e-12)
    accompaniment_source_ratio = accompaniment_rms / max(source_rms, 1e-12)
    muted = (
        source_rms > 1e-5
        and source_correlation >= 0.985
        and vocal_correlation >= 0.75
        and vocal_source_ratio >= 0.35
        and accompaniment_source_ratio <= 0.65
    )

    guarded = np.zeros_like(accompaniment) if muted else accompaniment
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, guarded, accompaniment_rate, subtype="PCM_24")
    validate_audio(output)
    return AccompanimentGuardResult(
        muted=muted,
        source_correlation=source_correlation,
        vocal_correlation=vocal_correlation,
        accompaniment_source_ratio=accompaniment_source_ratio,
        vocal_source_ratio=vocal_source_ratio,
    )


def compare_vocal_rhythm(source_path: Path, candidate_path: Path, *, points: int = 500) -> RhythmComparison:
    """Compare phrase-internal energy attacks after normalizing total duration.

    This deliberately ignores waveform phase and timbre.  A changed lyric can
    sound completely different while still placing syllable attacks and rests
    at the same relative times.  Conversely, merely stretching a freely timed
    phrase to the correct total duration cannot inflate this score.
    """
    if points < 50:
        raise ValueError("节奏比较采样点过少")

    def normalized_features(path: Path) -> tuple[np.ndarray, np.ndarray]:
        audio, rate = sf.read(path, always_2d=True, dtype="float32")
        mono = np.mean(audio, axis=1, dtype=np.float32)
        window = max(32, round(rate * 0.040))
        hop = max(1, round(rate * 0.010))
        if len(mono) < window:
            return np.zeros(points, dtype=np.float64), np.zeros(points, dtype=np.float64)
        starts = np.arange(0, len(mono) - window + 1, hop)
        envelope = np.asarray([
            np.sqrt(np.mean(np.square(mono[start:start + window]), dtype=np.float64))
            for start in starts
        ])
        positions = np.linspace(0.0, max(0, len(envelope) - 1), points)
        envelope = np.interp(positions, np.arange(len(envelope)), envelope)
        log_envelope = np.log(envelope + max(1e-6, float(np.max(envelope)) * 1e-4))
        onset = np.maximum(0.0, np.diff(log_envelope, prepend=log_envelope[0]))
        onset = np.convolve(onset, np.ones(3, dtype=np.float64) / 3.0, mode="same")
        return log_envelope, onset

    def correlation(left: np.ndarray, right: np.ndarray) -> float:
        left = left - float(np.mean(left))
        right = right - float(np.mean(right))
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        return float(np.dot(left, right) / denominator) if denominator > 1e-12 else 0.0

    source_envelope, source_onset = normalized_features(source_path)
    candidate_envelope, candidate_onset = normalized_features(candidate_path)
    envelope_correlation = correlation(source_envelope, candidate_envelope)
    onset_correlation = correlation(source_onset, candidate_onset)
    reliable = (
        float(np.std(source_envelope)) >= 0.08
        and float(np.std(candidate_envelope)) >= 0.08
        and float(np.std(source_onset)) >= 0.01
        and float(np.std(candidate_onset)) >= 0.01
    )
    score = 0.25 * envelope_correlation + 0.75 * onset_correlation
    return RhythmComparison(score, envelope_correlation, onset_correlation, reliable)


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
