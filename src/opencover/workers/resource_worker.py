from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from opencover.core.download_manager import DownloadError, download_file, safe_extract_zip


def emit(kind: str, **data: object) -> None:
    payload = json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8")); sys.stdout.buffer.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_path(root: Path, item: dict[str, object]) -> Path:
    url_name = Path(unquote(urlparse(str(item["download_url"])).path)).name
    suffix = "".join(Path(url_name).suffixes[-2:]) or ".download"
    return root / "downloads" / f"{item['resource_id']}{suffix}"


def install_resource(root: Path, item: dict[str, object], archive: Path) -> Path:
    relative = Path(str(item["install_directory"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise DownloadError("资源清单安装路径越界")
    destination = (root / relative).resolve()
    if root != destination and root not in destination.parents:
        raise DownloadError("资源清单安装路径越界")
    if archive.suffix.lower() == ".zip":
        if destination.exists() and any(destination.iterdir() if destination.is_dir() else [destination]):
            raise DownloadError("安装目录非空；为避免覆盖，请先备份后手动处理或使用检测功能")
        safe_extract_zip(archive, destination)
        return destination
    if not relative.suffix:
        raise DownloadError("该资源还需要模型元数据或专用安装步骤；已完成下载，但拒绝把裸文件冒充可用组件")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) == sha256(archive):
            return destination
        raise DownloadError("安装目标已存在且哈希不同，不会覆盖")
    shutil.copy2(archive, destination)
    return destination


def main(request_file: str) -> int:
    try:
        request = json.loads(Path(request_file).read_text(encoding="utf-8"))
        root = Path(request["root"]).resolve()
        manifest = yaml.safe_load((root / "config" / "resource_manifest.yaml").read_text(encoding="utf-8"))
        resources = {item["resource_id"]: item for item in manifest["resources"]}
        item = resources.get(str(request["model_id"]))
        if item is None:
            raise DownloadError("资源清单中找不到该资源")
        url = str(item.get("download_url") or "")
        if not url.startswith(("https://", "http://")):
            raise DownloadError("资源没有经核验的 HTTP/HTTPS 下载地址")
        target = cache_path(root, item)
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_hash = str(item.get("sha256") or "")
        expected_size = int(item.get("file_size") or 0) or None
        emit("status", message=f"正在下载：{item['name']}")
        started = time.monotonic()

        def progress(done: int, total: int | None) -> None:
            elapsed = max(time.monotonic() - started, 0.1)
            speed = done / elapsed / 1024**2
            percent = min(90, int(done * 90 / total)) if total else 5
            remain = f" / {total / 1024**2:.1f} MiB" if total else ""
            emit("status", message=f"已下载 {done / 1024**2:.1f}{remain}，{speed:.1f} MiB/s")
            emit("progress", stage="download", value=percent)

        reusable = target.is_file() and (not expected_hash or sha256(target).lower() == expected_hash.lower())
        if not reusable:
            download_file(url, target, expected_sha256=expected_hash or None, expected_size=expected_size, progress=progress)
        else:
            emit("status", message="下载缓存哈希匹配，直接复用")
        emit("progress", stage="verify", value=92)
        result = target
        if bool(request.get("options", {}).get("install", True)):
            emit("status", message="校验完成，正在安全安装")
            result = install_resource(root, item, target)
        emit("progress", stage="install", value=100)
        emit("result", path=str(result))
        return 0
    except Exception as exc:
        emit("error", code="RESOURCE_ERROR", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
