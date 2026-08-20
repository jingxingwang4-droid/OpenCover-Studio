from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = PROJECT_ROOT / "downloads" / "ddsp_restore"

RESOURCES = {
    "contentvec": {
        "name": "contentvec-pytorch_model.bin",
        "url": "https://huggingface.co/lengyue233/content-vec-best/resolve/ab04aa7067b99ee05cc82499bc64916b980a1967/pytorch_model.bin",
        "size": 378_342_945,
        "sha256": "d8dd400e054ddf4e6be75dab5a2549db748cc99e756a097c496c099f65a4854e",
    },
    "nsf_hifigan": {
        "name": "pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip",
        "url": "https://github.com/openvpi/vocoders/releases/download/pc-nsf-hifigan-44.1k-hop512-128bin-2025.02/pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip",
        "size": 52_675_337,
        "sha256": "9d98ba73727f2abb75172cf8249d75182237e8472fc3b6ed09c721ae8b0e83c6",
    },
    "rmvpe": {
        "name": "rmvpe.zip",
        "url": "https://github.com/yxlllc/RMVPE/releases/download/230917/rmvpe.zip",
        "size": 340_638_958,
        "sha256": "54ae40d9c066d998b94574f6ef0deea19ed1565bd655b3f0d9b1ad612fb5309c",
    },
    "sakiko": {
        "name": "sakiko.pt",
        "url": "https://huggingface.co/TogetsuDo/sakiko-ddsp-svc-6.3/resolve/4b77b1a9004c1a86cc8b06d1d118d0c49243a614/sakiko.pt",
        "size": 219_737_603,
        "sha256": "3023012dfe0d0a5034cec8e2394788c16c10bd8d226d81f3b037e3158a3ceadf",
    },
    "kokkoro": {
        "name": "model_500.pt",
        "url": "https://huggingface.co/yuier0721/DDSP-SVC_6.3_pcr-kokkoro_2.0/resolve/aca068709a3b5b119edc19b173cbb213f03d7854/model_500.pt",
        "size": 219_737_099,
        "sha256": "cca82132a952f9fd236246ab1e91e02ba86bda13c768a1ec58b6675911a64dbb",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def opener(proxy: str) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )


def download_part(
    client: urllib.request.OpenerDirector,
    resource: dict[str, object],
    part_path: Path,
    start: int,
    end: int,
    retries: int,
) -> None:
    expected = end - start + 1
    if part_path.is_file() and part_path.stat().st_size == expected:
        return
    part_path.unlink(missing_ok=True)
    temporary = part_path.with_suffix(".tmp")
    for attempt in range(1, retries + 1):
        temporary.unlink(missing_ok=True)
        request = urllib.request.Request(
            str(resource["url"]),
            headers={"Range": f"bytes={start}-{end}", "User-Agent": "OpenCoverStudio-DDSP-Restore/1.0"},
        )
        try:
            with client.open(request, timeout=240) as response:
                status = getattr(response, "status", None)
                content_range = response.headers.get("Content-Range", "")
                if status != 206 or not content_range.startswith(f"bytes {start}-{end}/"):
                    raise RuntimeError(f"unexpected range response status={status} range={content_range!r}")
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output, 1024 * 1024)
            actual = temporary.stat().st_size
            if actual != expected:
                raise RuntimeError(f"part length {actual}, expected {expected}")
            temporary.replace(part_path)
            return
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"range {start}-{end} failed after {retries} attempts: {exc}") from exc
            time.sleep(min(2 * attempt, 10))


def restore(resource_id: str, *, proxy: str, chunk_mib: int, workers: int, retries: int) -> Path:
    resource = RESOURCES[resource_id]
    destination = DOWNLOAD_ROOT / str(resource["name"])
    expected_size = int(resource["size"])
    expected_hash = str(resource["sha256"])
    if destination.is_file() and destination.stat().st_size == expected_size and sha256(destination) == expected_hash:
        print(f"[OK] {resource_id} already verified", flush=True)
        return destination
    destination.unlink(missing_ok=True)

    parts_root = destination.with_suffix(destination.suffix + ".parts")
    parts_root.mkdir(parents=True, exist_ok=True)
    chunk_size = chunk_mib * 1024 * 1024
    ranges: list[tuple[int, int, int, Path]] = []
    for index, start in enumerate(range(0, expected_size, chunk_size)):
        end = min(start + chunk_size - 1, expected_size - 1)
        ranges.append((index, start, end, parts_root / f"{index:05d}.part"))

    client = opener(proxy)
    initial_complete = {
        index for index, start, end, path in ranges
        if path.is_file() and path.stat().st_size == end - start + 1
    }
    missing_ranges = [item for item in ranges if item[0] not in initial_complete]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_part, client, resource, path, start, end, retries): (index, start, end)
            for index, start, end, path in missing_ranges
        }
        completed = len(initial_complete)
        print(f"[{resource_id}] {completed}/{len(ranges)} verified parts before download", flush=True)
        for future in concurrent.futures.as_completed(futures):
            index, start, end = futures[future]
            future.result()
            completed += 1
            print(f"[{resource_id}] {completed}/{len(ranges)} part {index + 1} bytes {start}-{end}", flush=True)

    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.unlink(missing_ok=True)
    with partial.open("xb") as output:
        for _, start, end, path in ranges:
            if path.stat().st_size != end - start + 1:
                raise RuntimeError(f"invalid cached part: {path}")
            with path.open("rb") as source:
                shutil.copyfileobj(source, output, 1024 * 1024)
    actual_size = partial.stat().st_size
    actual_hash = sha256(partial)
    if actual_size != expected_size or actual_hash != expected_hash:
        raise RuntimeError(
            f"final verification failed for {resource_id}: size={actual_size} sha256={actual_hash}"
        )
    partial.replace(destination)
    shutil.rmtree(parts_root)
    print(f"[OK] {resource_id} size={actual_size} sha256={actual_hash}", flush=True)
    return destination


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if target != destination and destination not in target.parents:
                raise RuntimeError(f"unsafe archive path: {info.filename}")
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise RuntimeError(f"archive symlink rejected: {info.filename}")
        archive.extractall(destination)


def install_verified() -> None:
    backend = PROJECT_ROOT / "external_backends" / "ddsp" / "DDSP-SVC"
    weights = PROJECT_ROOT / "weights" / "ddsp"
    contentvec = DOWNLOAD_ROOT / "contentvec-pytorch_model.bin"
    nsf_zip = DOWNLOAD_ROOT / "pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip"
    rmvpe_zip = DOWNLOAD_ROOT / "rmvpe.zip"
    sakiko = DOWNLOAD_ROOT / "sakiko.pt"
    kokkoro = DOWNLOAD_ROOT / "model_500.pt"
    expected = {str(item["name"]): item for item in RESOURCES.values()}
    for source in (contentvec, nsf_zip, rmvpe_zip, sakiko, kokkoro):
        item = expected[source.name]
        if not source.is_file() or source.stat().st_size != item["size"] or sha256(source) != item["sha256"]:
            raise RuntimeError(f"refusing to install unverified resource: {source}")

    contentvec_target = backend / "pretrain" / "contentvec" / "pytorch_model.bin"
    contentvec_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(contentvec, contentvec_target)

    nsf_stage = DOWNLOAD_ROOT / "nsf_hifigan_extract"
    shutil.rmtree(nsf_stage, ignore_errors=True)
    safe_extract(nsf_zip, nsf_stage)
    nsf_source = nsf_stage / "pc_nsf_hifigan_44.1k_hop512_128bin_2025.02"
    nsf_target = backend / "pretrain" / "nsf_hifigan"
    nsf_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(nsf_source / "model.ckpt", nsf_target / "model")
    for name in ("config.json", "NOTICE.txt", "NOTICE.zh-CN.txt", "STATEMENTS.txt"):
        shutil.copy2(nsf_source / name, nsf_target / name)
    if sha256(nsf_target / "model") != "d6dd28909d2a1a2dcf74b3e3aa0b82b48695b87979fdf41561940aeecd85c67f":
        raise RuntimeError("installed NSF-HiFiGAN checkpoint hash mismatch")

    rmvpe_stage = DOWNLOAD_ROOT / "rmvpe_extract"
    shutil.rmtree(rmvpe_stage, ignore_errors=True)
    safe_extract(rmvpe_zip, rmvpe_stage)
    candidates = [path for path in rmvpe_stage.rglob("*.pt") if path.is_file()]
    model_source = next((path for path in candidates if sha256(path) == "19dc1809cf4cdb0a18db93441816bc327e14e5644b72eeaae5220560c6736fe2"), None)
    if model_source is None:
        raise RuntimeError("verified RMVPE archive does not contain the expected model.pt")
    rmvpe_target = backend / "pretrain" / "rmvpe" / "model.pt"
    rmvpe_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model_source, rmvpe_target)

    sakiko_target = weights / "bundled" / "toyokawa_sakiko_ddsp" / "model.pt"
    kokkoro_target = weights / "user_models" / "kokkoro_ddsp_community" / "model.pt"
    sakiko_target.parent.mkdir(parents=True, exist_ok=True)
    kokkoro_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sakiko, sakiko_target)
    shutil.copy2(kokkoro, kokkoro_target)
    print("[OK] all verified DDSP resources installed", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore pinned DDSP resources with verified range downloads.")
    parser.add_argument("resources", nargs="*", choices=tuple(RESOURCES), default=list(RESOURCES))
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--chunk-mib", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    results = {}
    for resource_id in args.resources:
        results[resource_id] = str(
            restore(resource_id, proxy=args.proxy, chunk_mib=args.chunk_mib, workers=args.workers, retries=args.retries)
        )
    if args.install:
        install_verified()
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
