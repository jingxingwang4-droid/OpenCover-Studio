from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opencover.core.download_manager import DownloadError, download_file, safe_extract_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCover Studio 可审计资源下载器")
    parser.add_argument("resource_id", nargs="?", help="resource_manifest.yaml 中的 resource_id")
    parser.add_argument("--list", action="store_true", help="列出资源")
    parser.add_argument("--install", action="store_true", help="ZIP 校验后安全解压到安装目录")
    args = parser.parse_args()
    manifest = yaml.safe_load((ROOT / "config" / "resource_manifest.yaml").read_text(encoding="utf-8"))
    resources = {item["resource_id"]: item for item in manifest["resources"]}
    if args.list or not args.resource_id:
        for item in resources.values():
            print(f"{item['resource_id']:<30} {item['status']:<28} {item['name']}")
        return 0
    if args.resource_id not in resources:
        parser.error("未知 resource_id")
    item = resources[args.resource_id]
    if not item.get("download_url"):
        raise SystemExit("资源没有经核验的下载地址，已拒绝下载")
    cache = ROOT / "downloads" / (args.resource_id + Path(item["download_url"]).suffix)
    print(f"下载 {item['name']} -> {cache}")
    try:
        download_file(item["download_url"], cache, expected_sha256=item.get("sha256") or None,
                      progress=lambda done, total: print(f"\r{done / 1024**2:.1f} / {(total or 0) / 1024**2:.1f} MB", end="", flush=True))
        print()
        digest = hashlib.sha256(cache.read_bytes()).hexdigest()
        print(f"SHA256 {digest}")
        if args.install:
            if cache.suffix.lower() != ".zip":
                raise DownloadError("当前自动安装仅支持 ZIP")
            destination = ROOT / item["install_directory"]
            if destination.exists() and any(destination.iterdir()):
                raise DownloadError("安装目录非空，不会覆盖")
            safe_extract_zip(cache, destination)
            print(f"已安全解压到 {destination}；未执行包内脚本")
    except DownloadError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
