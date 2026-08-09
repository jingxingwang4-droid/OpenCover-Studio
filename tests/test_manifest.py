from pathlib import Path

import yaml


def test_resource_manifest_has_required_audit_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "config" / "resource_manifest.yaml").read_text(encoding="utf-8"))
    required = {"resource_id", "type", "name", "author", "official_repository", "source_page",
                "download_url", "version", "tag", "commit", "file_size", "sha256", "license",
                "redistribution_allowed", "install_directory", "backend", "last_verified", "status"}
    ids: set[str] = set()
    for resource in manifest["resources"]:
        assert required <= set(resource)
        assert resource["resource_id"] not in ids
        ids.add(resource["resource_id"])
        if resource["status"] == "installed_verified":
            assert resource["sha256"]
            assert resource["file_size"] > 0
