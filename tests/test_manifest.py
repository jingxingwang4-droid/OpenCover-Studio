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
        if resource["status"] == "installed_verified" and resource["file_size"] is not None:
            assert resource["sha256"]
            assert resource["file_size"] > 0
        if resource["status"] == "installed_verified" and resource["file_size"] is None:
            assert resource["commit"]


def test_ddsp_resources_are_pinned_and_not_publicly_redistributed() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "config" / "resource_manifest.yaml").read_text(encoding="utf-8"))
    resources = {item["resource_id"]: item for item in manifest["resources"]}
    expected = {
        "ddsp_svc_source", "ddsp_contentvec", "ddsp_nsf_hifigan", "ddsp_rmvpe",
        "toyokawa_sakiko_ddsp", "kokkoro_ddsp_community",
    }
    assert expected <= resources.keys()
    for resource_id in expected:
        item = resources[resource_id]
        assert item["backend"] == "ddsp"
        assert item["redistribution_allowed"] is False or resource_id == "ddsp_svc_source"
        assert item["commit"] or item["tag"]
    for resource_id in expected - {"ddsp_svc_source"}:
        assert len(resources[resource_id]["sha256"]) == 64
        assert resources[resource_id]["file_size"] > 50 * 1024**2
