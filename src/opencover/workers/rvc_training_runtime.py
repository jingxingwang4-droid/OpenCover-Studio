"""Isolated bridge to pinned upstream RVC training code; single NVIDIA GPU."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    stage = sys.argv[2]
    root = Path(request["root"])
    source = root / "external_backends/rvc_training/source"
    work = Path(request["work"])
    experiment = work / "logs/voice"
    sys.path.insert(0, str(source))
    os.chdir(work)
    os.environ["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    import torch
    torch.set_num_threads(4)
    if stage != "slice" and not torch.cuda.is_available():
        raise RuntimeError("训练需要可用的 NVIDIA CUDA GPU")

    def upstream(relative: str, args: list[str]) -> None:
        script = source / relative
        sys.argv = [str(script), *map(str, args)]
        runpy.run_path(str(script), run_name="__main__")

    if stage == "slice":
        upstream("infer/modules/train/preprocess.py", [str(work / "input"), "40000", "1", str(experiment), "True", str(request["slice_seconds"])])
        import soundfile as sf
        import numpy as np
        clips = sorted((experiment / "0_gt_wavs").glob("*.wav"))
        if not clips:
            raise RuntimeError("未得到有效切片，请检查素材是否含有清晰人声")
        for clip in clips:
            data, sr = sf.read(clip)
            if not np.isfinite(data).all() or np.max(np.abs(data)) < 1e-5 or len(data) < sr * .3:
                raise RuntimeError(f"无效切片：{clip.name}")
        print(json.dumps({"slices": len(clips), "seconds": sum(sf.info(p).duration for p in clips)}), flush=True)
    elif stage == "f0":
        upstream("infer/modules/train/extract/extract_f0_rmvpe.py", ["1", "0", "0", str(experiment), "True"])
    elif stage == "features":
        upstream("infer/modules/train/extract_feature_print.py", ["cuda:0", "1", "0", "0", str(experiment), "v2", "True"])
    elif stage == "index":
        import numpy as np
        import faiss
        rows = []
        files = []
        for clip in sorted((experiment / "0_gt_wavs").glob("*.wav")):
            feature = experiment / "3_feature768" / (clip.stem + ".npy")
            pitch = experiment / "2a_f0" / (clip.name + ".npy")
            nsf = experiment / "2b-f0nsf" / (clip.name + ".npy")
            feat, f0, continuous = (np.load(p, allow_pickle=False) for p in (feature, pitch, nsf))
            if feat.ndim != 2 or feat.shape[1] != 768 or not all(np.isfinite(x).all() for x in (feat, f0, continuous)):
                raise RuntimeError(f"特征无效：{clip.name}")
            if len(f0) != len(continuous) or abs(len(f0) - len(feat) * 2) > 6:
                raise RuntimeError(f"音高与特征长度不一致：{clip.name}")
            rows.append(feat)
            files.append("|".join(str(p.relative_to(work)).replace("\\", "/") for p in (clip, feature, pitch, nsf)) + "|0")
        if not rows or not any(np.any(np.load(p) > 0) for p in (experiment / "2b-f0nsf").glob("*.npy")):
            raise RuntimeError("训练素材没有有效音高")
        (experiment / "filelist.txt").write_text("\n".join(files), encoding="utf-8")
        features = np.concatenate(rows).astype("float32")
        index = faiss.IndexFlatL2(768)
        index.add(features)
        # Serialization via bytes supports Chinese project paths on Windows.
        (work / "voice.index").write_bytes(faiss.serialize_index(index).tobytes())
        print(json.dumps({"features": len(features), "clips": len(rows)}), flush=True)
    elif stage == "train":
        # One GPU does not need Gloo, whose Windows CUDA reductions are unreliable.
        # Keep upstream loss/optimizer/checkpoint logic intact.
        import torch.distributed as dist
        import torch.nn.parallel
        dist.init_process_group = lambda **kwargs: None
        torch.nn.parallel.DistributedDataParallel = lambda model, **kwargs: model
        original_loader = torch.utils.data.DataLoader
        def loader(*args, **kwargs):
            kwargs.update(num_workers=0, persistent_workers=False)
            kwargs.pop("prefetch_factor", None)
            return original_loader(*args, **kwargs)
        torch.utils.data.DataLoader = loader
        script = source / "infer/modules/train/train.py"
        pretrained = root / "external_backends/rvc_training/pretrained"
        sys.argv = [str(script), "-e", "voice", "-sr", "40k", "-f0", "1", "-bs", str(request["batch_size"]), "-g", "0", "-te", str(request["epochs"]), "-se", "25", "-pg", str(pretrained / "f0G40k.pth"), "-pd", str(pretrained / "f0D40k.pth"), "-l", "1", "-c", "0", "-sw", "0", "-v", "v2"]
        namespace = runpy.run_path(str(script), run_name="opencover_training")
        # Upstream exits with a nonzero magic code even on success.
        def finish(code):
            if code != 2333333:
                raise SystemExit(code)
            raise SystemExit(0)
        os._exit = finish
        namespace["run"](0, 1, namespace["hps"], namespace["utils"].get_logger(str(experiment)))
    elif stage == "verify":
        checkpoint = torch.load(work / "assets/weights/voice.pth", map_location="cpu", weights_only=False)
        if checkpoint.get("version") != "v2" or checkpoint.get("f0") != 1 or checkpoint["config"][-1] != 40000:
            raise RuntimeError("训练输出不是 RVC v2 40k 音高模型")
        if checkpoint.get("info") != f'{request["epochs"]}epoch':
            raise RuntimeError("训练未完成指定轮数")
        if not all(torch.isfinite(t).all() for t in checkpoint["weight"].values()):
            raise RuntimeError("训练权重包含非有限数值")
        print("TRAINING_WEIGHTS_VALID", flush=True)
    else:
        raise ValueError(stage)


if __name__ == "__main__":
    main()
