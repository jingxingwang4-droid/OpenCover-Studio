from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from opencover.audio.processing import validate_audio


OOM_MARKERS = (
    "cuda out of memory", "cuda error: out of memory", "cudnn_status_alloc_failed",
    "cublas_status_alloc_failed", "hip out of memory", "显存不足", "内存分配失败",
)

PROFILE_CHUNKS: dict[str, tuple[float, ...]] = {
    "极低": (15.0, 8.0), "低": (20.0, 10.0), "标准": (30.0, 15.0), "高质量": (45.0, 20.0),
}


def chunk_sizes_for_profile(profile: str) -> tuple[float, ...]:
    return PROFILE_CHUNKS.get(profile, PROFILE_CHUNKS["标准"])


def is_cuda_oom(error: BaseException | str) -> bool:
    message = str(error).casefold()
    return any(marker in message for marker in OOM_MARKERS)


def _chunked_conversion(
    input_audio: Path,
    output_audio: Path,
    converter: Callable[[Path, Path], object],
    chunk_seconds: float,
) -> Path:
    source, input_rate = sf.read(input_audio, always_2d=True, dtype="float32")
    if not len(source):
        raise RuntimeError("无法对空音频执行显存降级")
    chunk_frames = max(input_rate * 2, round(chunk_seconds * input_rate))
    overlap_frames = min(round(0.10 * input_rate), chunk_frames // 8)
    retry_dir = output_audio.parent / f"oom_retry_{int(chunk_seconds)}s"
    retry_dir.mkdir(parents=True, exist_ok=True)
    combined: np.ndarray | None = None
    output_rate: int | None = None
    cursor = 0
    index = 0
    while cursor < len(source):
        begin = max(0, cursor - overlap_frames if cursor else 0)
        end = min(len(source), cursor + chunk_frames)
        chunk_input = retry_dir / f"input_{index:04d}.wav"
        chunk_output = retry_dir / f"output_{index:04d}.wav"
        sf.write(chunk_input, source[begin:end], input_rate, subtype="PCM_24")
        converter(chunk_input, chunk_output)
        values, rate = sf.read(chunk_output, always_2d=True, dtype="float32")
        if output_rate is None:
            output_rate = rate
        if rate != output_rate or (combined is not None and values.shape[1] != combined.shape[1]):
            raise RuntimeError("显存降级分段输出的采样率或声道不一致")
        if combined is None:
            combined = values
        else:
            overlap = min(round(overlap_frames * rate / input_rate), len(combined), len(values))
            if overlap:
                fade = np.linspace(0.0, 1.0, overlap, endpoint=False, dtype=np.float32)[:, None]
                combined[-overlap:] = combined[-overlap:] * (1.0 - fade) + values[:overlap] * fade
            combined = np.concatenate((combined, values[overlap:]), axis=0)
        cursor = end
        index += 1
    assert combined is not None and output_rate is not None
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_audio, combined, output_rate, subtype="PCM_24")
    validate_audio(output_audio)
    return output_audio


def convert_with_oom_retry(
    input_audio: Path,
    output_audio: Path,
    converter: Callable[[Path, Path], object],
    notify: Callable[[str], None] | None = None,
    chunk_sizes: tuple[float, ...] = (30.0, 15.0),
) -> Path:
    """Run conversion once, then retry OOM failures with two bounded chunk sizes.

    Each backend invocation is a child process. A failed invocation exits before the
    retry begins, which releases its CUDA context instead of retaining a poisoned model.
    """
    try:
        converter(input_audio, output_audio)
        validate_audio(output_audio)
        return output_audio
    except Exception as exc:
        if not is_cuda_oom(exc):
            raise
        last_error: Exception = exc
    for attempt, seconds in enumerate(chunk_sizes, start=1):
        if notify:
            notify(f"检测到显存不足；后端进程已退出，正在以 {seconds:g} 秒分段重试（{attempt}/{len(chunk_sizes)}）")
        try:
            return _chunked_conversion(input_audio, output_audio, converter, seconds)
        except Exception as exc:
            last_error = exc
            if not is_cuda_oom(exc):
                raise
    raise RuntimeError(f"CUDA_OOM：已完成 {len(chunk_sizes)} 次分段降级重试，仍然显存不足：{last_error}") from last_error
