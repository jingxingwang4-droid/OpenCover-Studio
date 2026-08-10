from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from opencover.core.retry_policy import convert_with_oom_retry, is_cuda_oom


def test_cuda_oom_classification_is_specific() -> None:
    assert is_cuda_oom("RuntimeError: CUDA out of memory. Tried to allocate 2 GiB")
    assert is_cuda_oom("CUDNN_STATUS_ALLOC_FAILED")
    assert not is_cuda_oom("模型文件不存在")


def test_conversion_retries_cuda_oom_with_bounded_chunks(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    sf.write(source, np.sin(np.linspace(0, 100, 20000)).astype(np.float32), 8000)
    calls: list[str] = []

    def converter(input_path: Path, output_path: Path) -> None:
        calls.append(input_path.name)
        if input_path == source:
            raise RuntimeError("CUDA out of memory")
        values, rate = sf.read(input_path, always_2d=True, dtype="float32")
        sf.write(output_path, values * 0.5, rate)

    messages: list[str] = []
    result = convert_with_oom_retry(source, output, converter, messages.append, chunk_sizes=(1.0,))
    values, rate = sf.read(result, dtype="float32")
    assert rate == 8000
    assert len(values) == 20000
    assert np.max(np.abs(values)) > 0.4
    assert calls[0] == "source.wav" and len(calls) > 2
    assert "1 秒分段重试（1/1）" in messages[0]
