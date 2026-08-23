from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "package_proxmox.py"
SPEC = importlib.util.spec_from_file_location("package_proxmox_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
build_package = MODULE.build_package


def test_package_uses_allowlist_and_excludes_secrets(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = tmp_path / "out"
    (root / ".git").mkdir(parents=True)
    (root / "sales-mcp").mkdir()
    (root / "openwa" / "upstream").mkdir(parents=True)
    (root / "graphify-out").mkdir()
    (root / "sales-mcp" / "linkedin_dispatch.py").write_text("pilot", encoding="utf-8")
    (root / "openwa" / "upstream" / "package.json").write_text("{}", encoding="utf-8")
    (root / ".env").write_text("SECRET=real", encoding="utf-8")
    (root / "graphify-out" / "graph.json").write_text("private", encoding="utf-8")

    archive_path, manifest_path = build_package(root, output)

    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "sales-mcp/linkedin_dispatch.py" in names
    assert "openwa/upstream/package.json" in names
    assert ".env" not in names
    assert not any(name.startswith((".git/", "graphify-out/")) for name in names)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["archive_sha256"]
    assert manifest["archive_bytes"] == archive_path.stat().st_size
    assert manifest["files"] == sorted(manifest["files"], key=lambda record: record["path"])


def test_manifest_exactly_describes_sorted_archive_inventory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = tmp_path / "out"
    (root / ".git").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "sales-mcp" / "nested").mkdir(parents=True)
    (root / "docker-compose.proxmox.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "config" / "pilot.json").write_text('{"safe": true}\n', encoding="utf-8")
    payload = b"untracked but allowed"
    (root / "sales-mcp" / "nested" / "pilot.py").write_bytes(payload)
    (root / "sales-mcp" / "nested" / "operator.key").write_text("secret", encoding="utf-8")
    (root / "sales-mcp" / "credentials-sicherung-old").mkdir()
    (root / "sales-mcp" / "credentials-sicherung-old" / "state.json").write_text(
        "private", encoding="utf-8"
    )

    archive_path, manifest_path = build_package(root, output)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        names = [member.name for member in members]
        archive_payloads = {member.name: archive.extractfile(member).read() for member in members}
    assert names == sorted(names)
    assert names == [record["path"] for record in manifest["files"]]
    assert all("\\" not in record["path"] for record in manifest["files"])
    assert all(
        record == {
            "path": record["path"],
            "bytes": len(archive_payloads[record["path"]]),
            "sha256": hashlib.sha256(archive_payloads[record["path"]]).hexdigest(),
        }
        for record in manifest["files"]
    )
    assert "sales-mcp/nested/pilot.py" in names
    assert "sales-mcp/nested/operator.key" not in names
    assert not any("credentials-sicherung-" in name for name in names)


def test_package_requires_git_anchor_and_ignores_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = tmp_path / "out"
    root.mkdir()

    with pytest.raises(ValueError, match="\\.git"):
        build_package(root, output)

    (root / ".git").mkdir()
    (root / "sales-mcp").mkdir()
    (root / "sales-mcp" / "safe.py").write_text("safe", encoding="utf-8")
    external = tmp_path / "external.txt"
    external.write_text("must not be read", encoding="utf-8")
    try:
        (root / "sales-mcp" / "link.py").symlink_to(external)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    archive_path, _ = build_package(root, output)

    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
    assert names == ["sales-mcp/safe.py"]
