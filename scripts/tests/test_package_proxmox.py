from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts.install_proxmox_package import InstallError, install_package


MODULE_PATH = Path(__file__).resolve().parents[1] / "package_proxmox.py"
SPEC = importlib.util.spec_from_file_location("package_proxmox_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
build_package = MODULE.build_package


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    output = tmp_path / "out"
    (root / ".git").mkdir(parents=True)
    (root / "sales-mcp").mkdir()
    (root / "sales-mcp" / "safe.py").write_text("safe", encoding="utf-8")
    return root, output


def _write_valid_package_pair(archive_path: Path, manifest_path: Path, payload: bytes) -> None:
    info = tarfile.TarInfo("sales-mcp/substituted.py")
    info.size = len(payload)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
    archive_bytes = archive_path.read_bytes()
    manifest_path.write_text(
        json.dumps(
            {
                "archive": MODULE.ARCHIVE_NAME,
                "archive_bytes": len(archive_bytes),
                "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
                "files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")


def _require_directory_symlink_support(tmp_path: Path) -> None:
    target = tmp_path / "symlink-probe-target"
    link = tmp_path / "symlink-probe"
    target.mkdir()
    _symlink_or_skip(link, target)
    link.unlink()
    target.rmdir()


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


def test_package_excludes_customer_reports_and_preserves_only_required_executables(
    tmp_path: Path,
) -> None:
    root, output = _workspace(tmp_path)
    (root / "reports").mkdir()
    (root / "reports" / "customer.md").write_text("customer PII", encoding="utf-8")
    upstream = root / "openwa" / "upstream"
    upstream.mkdir(parents=True)
    for name in ("backup.sh", "restore.sh", "entrypoint.sh", "helper.sh"):
        (upstream / name).write_text("#!/bin/sh\n", encoding="utf-8")

    archive_path, _ = build_package(root, output)

    with tarfile.open(archive_path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
    assert not any(name == "reports" or name.startswith("reports/") for name in members)
    assert members["openwa/upstream/backup.sh"].mode == 0o755
    assert members["openwa/upstream/restore.sh"].mode == 0o755
    assert members["openwa/upstream/entrypoint.sh"].mode == 0o644
    assert members["openwa/upstream/helper.sh"].mode == 0o644


def test_installer_verifies_pair_and_extracts_exact_manifest_inventory(
    tmp_path: Path,
) -> None:
    root, output = _workspace(tmp_path)
    (root / "config").mkdir()
    (root / "config" / "pilot.json").write_text('{"safe": true}\n', encoding="utf-8")
    archive_path, manifest_path = build_package(root, output)
    destination = tmp_path / "installed"

    count = install_package(archive_path, manifest_path, destination)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert count == len(manifest["files"])
    extracted = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    assert extracted == [record["path"] for record in manifest["files"]]
    assert (destination / "config" / "pilot.json").read_text(encoding="utf-8") == '{"safe": true}\n'


def test_installer_rejects_manifest_mismatch_without_leaving_destination(
    tmp_path: Path,
) -> None:
    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    destination = tmp_path / "rejected"

    with pytest.raises(InstallError):
        install_package(archive_path, manifest_path, destination)

    assert not destination.exists()


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


def test_documented_scripts_package_import_resolves_local_builder() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.package_proxmox import build_package; print(build_package.__name__)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "build_package"


def test_timestamped_proxmox_artifact_directories_are_git_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "check-ignore", "--no-index", "artifacts/proxmox-20260824-120000/probe"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_refuses_symlinked_archive_target_before_publishing_either_output(tmp_path: Path) -> None:
    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    manifest_before = manifest_path.read_bytes()
    target = tmp_path / "archive-target.bin"
    target.write_bytes(b"archive target remains untouched")
    archive_path.unlink()
    _symlink_or_skip(archive_path, target)

    with pytest.raises(ValueError, match="symlink"):
        build_package(root, output)

    assert target.read_bytes() == b"archive target remains untouched"
    assert manifest_path.read_bytes() == manifest_before


def test_refuses_symlinked_manifest_target_before_replacing_archive(tmp_path: Path) -> None:
    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    archive_before = archive_path.read_bytes()
    target = tmp_path / "manifest-target.json"
    target.write_bytes(b"manifest target remains untouched")
    manifest_path.unlink()
    _symlink_or_skip(manifest_path, target)

    with pytest.raises(ValueError, match="symlink"):
        build_package(root, output)

    assert archive_path.read_bytes() == archive_before
    assert target.read_bytes() == b"manifest target remains untouched"


def test_source_swap_to_file_symlink_fails_before_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, output = _workspace(tmp_path)
    source_file = root / "sales-mcp" / "safe.py"
    external = tmp_path / "external.py"
    external.write_text("external", encoding="utf-8")
    def swap_before_open(point: str, path: Path | None = None) -> None:
        if point == "before_source_file_open" and path == source_file and source_file.exists():
            source_file.unlink()
            _symlink_or_skip(source_file, external)

    monkeypatch.setattr(MODULE, "_inject_fault", swap_before_open)

    with pytest.raises(ValueError, match="changed or is a symlink"):
        build_package(root, output)

    assert not (output / MODULE.ARCHIVE_NAME).exists()
    assert not (output / MODULE.MANIFEST_NAME).exists()


def test_source_directory_is_pinned_before_enumeration_and_external_content_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_directory_symlink_support(tmp_path)
    root, output = _workspace(tmp_path)
    nested = root / "sales-mcp" / "nested"
    nested.mkdir()
    source_file = nested / "safe.py"
    source_file.write_text("legitimate", encoding="utf-8")
    external_dir = tmp_path / "external-dir"
    external_dir.mkdir()
    external_file = external_dir / "safe.py"
    external_file.write_text("external sentinel", encoding="utf-8")
    displaced = tmp_path / "displaced-nested"
    swap_outcome: list[str | OSError] = []

    def swap_before_enumeration(point: str, path: Path | None = None) -> None:
        if point != "before_directory_enumeration" or path != nested:
            return
        try:
            nested.rename(displaced)
            nested.symlink_to(external_dir, target_is_directory=True)
            swap_outcome.append("swapped")
        except OSError as error:
            swap_outcome.append(error)

    monkeypatch.setattr(MODULE, "_inject_fault", swap_before_enumeration)

    archive_path, _ = build_package(root, output)

    assert swap_outcome and isinstance(swap_outcome[0], OSError)
    with tarfile.open(archive_path, "r:gz") as archive:
        archived = archive.extractfile("sales-mcp/nested/safe.py")
        assert archived is not None
        assert archived.read() == b"legitimate"
    assert external_file.read_text(encoding="utf-8") == "external sentinel"


@pytest.mark.parametrize("fault_point", ["before_temp_creation", "before_publication"])
def test_output_directory_is_pinned_against_swap_to_external_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault_point: str
) -> None:
    _require_directory_symlink_support(tmp_path)
    root, output = _workspace(tmp_path)
    output.mkdir()
    external = tmp_path / "external-output"
    external.mkdir()
    external_archive = external / MODULE.ARCHIVE_NAME
    external_manifest = external / MODULE.MANIFEST_NAME
    external_archive.write_bytes(b"external archive sentinel")
    external_manifest.write_bytes(b"external manifest sentinel")
    displaced = tmp_path / "displaced-output"
    swap_outcome: list[str | OSError] = []

    def swap_output(point: str, path: Path | None = None) -> None:
        if point != fault_point or path != output:
            return
        try:
            output.rename(displaced)
            output.symlink_to(external, target_is_directory=True)
            for temporary in displaced.glob(".sales-claw-proxmox-*.tmp"):
                temporary.replace(external / temporary.name)
            swap_outcome.append("swapped")
        except OSError as error:
            swap_outcome.append(error)

    monkeypatch.setattr(MODULE, "_inject_fault", swap_output)

    archive_path, manifest_path = build_package(root, output)

    assert swap_outcome and isinstance(swap_outcome[0], OSError)
    assert archive_path.parent == output
    assert manifest_path.parent == output
    assert external_archive.read_bytes() == b"external archive sentinel"
    assert external_manifest.read_bytes() == b"external manifest sentinel"


def test_temp_artifacts_cannot_be_substituted_at_publication_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, output = _workspace(tmp_path)
    malicious_archive = tmp_path / "malicious.tar.gz"
    malicious_manifest = tmp_path / "malicious.MANIFEST.json"
    _write_valid_package_pair(malicious_archive, malicious_manifest, b"malicious sentinel")
    malicious_archive_before = malicious_archive.read_bytes()
    malicious_manifest_before = malicious_manifest.read_bytes()
    created_temps: list[Path] = []
    substitution_errors: list[OSError] = []
    real_temp_file = MODULE._temp_file

    def track_temp(path: Path):
        artifact = real_temp_file(path)
        temporary = artifact[1] if isinstance(artifact, tuple) else artifact.path
        created_temps.append(temporary)
        return artifact

    def substitute(point: str, path: Path | None = None) -> None:
        if point != "before_publication":
            return
        assert len(created_temps) == 2
        for malicious, temporary in zip(
            (malicious_archive, malicious_manifest), created_temps, strict=True
        ):
            try:
                malicious.replace(temporary)
            except OSError as error:
                substitution_errors.append(error)

    monkeypatch.setattr(MODULE, "_temp_file", track_temp)
    monkeypatch.setattr(MODULE, "_inject_fault", substitute)

    archive_path, manifest_path = build_package(root, output)

    assert len(substitution_errors) == 2
    assert malicious_archive.read_bytes() == malicious_archive_before
    assert malicious_manifest.read_bytes() == malicious_manifest_before
    with tarfile.open(archive_path, "r:gz") as archive:
        assert archive.getnames() == ["sales-mcp/safe.py"]
        archived = archive.extractfile("sales-mcp/safe.py")
        assert archived is not None
        assert archived.read() == b"safe"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["archive_sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()


def test_failed_build_preserves_existing_archive_and_manifest_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    archive_before = archive_path.read_bytes()
    manifest_before = manifest_path.read_bytes()
    source_file = root / "sales-mcp" / "safe.py"
    external = tmp_path / "external.py"
    external.write_text("external", encoding="utf-8")
    def swap_before_open(point: str, path: Path | None = None) -> None:
        if point == "before_source_file_open" and path == source_file and source_file.exists():
            source_file.unlink()
            _symlink_or_skip(source_file, external)

    monkeypatch.setattr(MODULE, "_inject_fault", swap_before_open)

    with pytest.raises(ValueError, match="changed or is a symlink"):
        build_package(root, output)

    assert archive_path.read_bytes() == archive_before
    assert manifest_path.read_bytes() == manifest_before


@pytest.mark.parametrize(
    "fault_point",
    [
        "journal_durable",
        "old_archive_moved",
        "old_manifest_moved",
        "new_archive_published",
        "new_manifest_published",
        "before_journal_commit",
    ],
)
def test_interrupted_publication_recovers_old_authoritative_pair_before_new_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault_point: str
) -> None:
    class SimulatedInterruption(BaseException):
        pass

    class StopAfterRecovery(Exception):
        pass

    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    archive_before = archive_path.read_bytes()
    manifest_before = manifest_path.read_bytes()
    (root / "sales-mcp" / "safe.py").write_text("new package", encoding="utf-8")

    def interrupt(point: str, path: Path | None = None) -> None:
        if point == fault_point:
            raise SimulatedInterruption(point)

    monkeypatch.setattr(MODULE, "_inject_fault", interrupt)

    with pytest.raises(SimulatedInterruption, match=fault_point):
        build_package(root, output)

    journal_path = output / ".sales-claw-proxmox-source.TRANSACTION.json"
    assert journal_path.is_file()
    monkeypatch.setattr(MODULE, "_inject_fault", lambda point, path=None: None)

    def stop_before_new_temp(*args: object, **kwargs: object):
        raise StopAfterRecovery(args, kwargs)

    monkeypatch.setattr(MODULE, "_temp_file", stop_before_new_temp)
    with pytest.raises(StopAfterRecovery):
        build_package(root, output)

    assert archive_path.read_bytes() == archive_before
    assert manifest_path.read_bytes() == manifest_before
    recovered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert recovered_manifest["archive_sha256"] == hashlib.sha256(archive_before).hexdigest()
    assert not journal_path.exists()
    assert {path.name for path in output.iterdir()} == {MODULE.ARCHIVE_NAME, MODULE.MANIFEST_NAME}


def test_interruption_after_journal_commit_keeps_new_pair_and_cleans_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SimulatedInterruption(BaseException):
        pass

    class StopAfterRecovery(Exception):
        pass

    root, output = _workspace(tmp_path)
    archive_path, manifest_path = build_package(root, output)
    old_archive = archive_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    (root / "sales-mcp" / "safe.py").write_text("committed new package", encoding="utf-8")

    def interrupt(point: str, path: Path | None = None) -> None:
        if point == "after_journal_commit":
            raise SimulatedInterruption(point)

    monkeypatch.setattr(MODULE, "_inject_fault", interrupt)

    with pytest.raises(SimulatedInterruption, match="after_journal_commit"):
        build_package(root, output)

    committed_archive = archive_path.read_bytes()
    committed_manifest = manifest_path.read_bytes()
    assert committed_archive != old_archive
    assert committed_manifest != old_manifest
    committed_value = json.loads(committed_manifest)
    assert committed_value["archive_sha256"] == hashlib.sha256(committed_archive).hexdigest()
    assert not (output / MODULE.JOURNAL_NAME).exists()
    assert any(path.name.startswith(".sales-claw-proxmox-source.DONE.") for path in output.iterdir())

    monkeypatch.setattr(MODULE, "_inject_fault", lambda point, path=None: None)

    def stop_before_new_temp(*args: object, **kwargs: object):
        raise StopAfterRecovery(args, kwargs)

    monkeypatch.setattr(MODULE, "_temp_file", stop_before_new_temp)
    for _ in range(2):
        with pytest.raises(StopAfterRecovery):
            build_package(root, output)
        assert archive_path.read_bytes() == committed_archive
        assert manifest_path.read_bytes() == committed_manifest
        assert {path.name for path in output.iterdir()} == {
            MODULE.ARCHIVE_NAME,
            MODULE.MANIFEST_NAME,
        }


def test_replaces_an_existing_published_pair(tmp_path: Path) -> None:
    root, output = _workspace(tmp_path)
    build_package(root, output)

    archive_path, manifest_path = build_package(root, output)

    assert archive_path.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["archive_bytes"] == archive_path.stat().st_size


def test_credentials_backup_directory_is_pruned_before_scanning_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, output = _workspace(tmp_path)
    excluded = root / "sales-mcp" / "credentials-sicherung-old"
    excluded.mkdir()
    (excluded / "state.json").write_text("private", encoding="utf-8")
    real_scandir = os.scandir

    def fail_if_excluded(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        if Path(path) == excluded:
            raise AssertionError("excluded credentials directory was scanned")
        return real_scandir(path)

    monkeypatch.setattr(MODULE.os, "scandir", fail_if_excluded)

    archive_path, _ = build_package(root, output)

    assert archive_path.exists()
