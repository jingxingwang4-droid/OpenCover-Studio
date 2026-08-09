from __future__ import annotations

import hashlib
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Callable

import requests


class DownloadError(RuntimeError):
    pass


def safe_extract_zip(
    archive: Path, destination: Path, *, max_total: int = 20 * 1024**3,
    max_ratio: int = 200, max_entries: int = 100_000,
) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        entries = handle.infolist()
        if len(entries) > max_entries:
            raise DownloadError("压缩包文件数量超过限制")
        total = sum(item.file_size for item in entries)
        if total > max_total:
            raise DownloadError("压缩包解压后体积超过限制")
        for item in entries:
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise DownloadError("压缩包包含符号链接，已拒绝解压")
            parts = PurePosixPath(item.filename.replace("\\", "/")).parts
            if item.filename.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise DownloadError("压缩包包含路径穿越")
            if item.compress_size and item.file_size / item.compress_size > max_ratio:
                raise DownloadError("压缩比异常，疑似压缩炸弹")
            target = (destination / Path(*parts)).resolve()
            if destination != target and destination not in target.parents:
                raise DownloadError("解压目标越界")
        destination.mkdir(parents=True, exist_ok=True)
        handle.extractall(destination)


def download_file(
    url: str, target: Path, *, expected_sha256: str | None = None,
    progress: Callable[[int, int | None], None] | None = None, cancel: Event | None = None,
    expected_size: int | None = None, retries: int = 2,
) -> Path:
    if not url.lower().startswith(("https://", "http://")):
        raise DownloadError("只允许 HTTP/HTTPS 下载")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise DownloadError("不会覆盖已存在文件")
    partial = target.with_suffix(target.suffix + ".part")
    if expected_size and shutil.disk_usage(target.parent).free < expected_size + 512 * 1024**2:
        raise DownloadError("磁盘空间不足（安装前至少保留 512 MiB 余量）")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        downloaded = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "OpenCoverStudio/0.1 (local desktop resource downloader; https://github.com/)"}
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        digest = hashlib.sha256()
        if downloaded:
            with partial.open("rb") as existing:
                for block in iter(lambda: existing.read(1024 * 1024), b""):
                    digest.update(block)
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, 60), allow_redirects=True) as response:
                if response.status_code not in {200, 206}:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise requests.HTTPError(f"HTTP {response.status_code}")
                    raise DownloadError(f"HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    raise DownloadError("服务器返回了网页而不是资源文件")
                if downloaded and response.status_code == 200:
                    downloaded = 0
                    digest = hashlib.sha256()
                    partial.unlink(missing_ok=True)
                remaining = int(response.headers.get("content-length", 0)) or None
                total = downloaded + remaining if remaining is not None else None
                with partial.open("ab") as handle:
                    for block in response.iter_content(1024 * 1024):
                        if cancel and cancel.is_set():
                            raise DownloadError("下载已取消")
                        if not block:
                            continue
                        handle.write(block)
                        digest.update(block)
                        downloaded += len(block)
                        if progress:
                            progress(downloaded, total)
            if expected_size and downloaded != expected_size:
                partial.unlink(missing_ok=True)
                raise DownloadError(f"文件大小异常：应为 {expected_size} bytes，实际为 {downloaded} bytes")
            if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
                partial.unlink(missing_ok=True)
                raise DownloadError("SHA256 校验失败")
            shutil.move(str(partial), str(target))
            return target
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2 ** attempt, 4))
    raise DownloadError(str(last_error or "下载失败")) from last_error
