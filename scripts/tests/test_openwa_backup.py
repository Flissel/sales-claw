import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest


VERIFY_SCRIPT = Path(__file__).resolve().parents[1] / "verify-openwa-backup.ps1"


def _write_archive(path: Path) -> int:
    payload = b"temporary openwa fixture\n"
    with tarfile.open(path, "w") as archive:
        directory = tarfile.TarInfo("session")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)

        message = tarfile.TarInfo("session/message.txt")
        message.size = len(payload)
        message.mode = 0o600
        archive.addfile(message, io.BytesIO(payload))

    with tarfile.open(path, "r") as archive:
        return sum(member.isfile() for member in archive.getmembers())


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    source = tmp_path / "backup"
    source.mkdir()
    archive_path = source / "openwa.tar"
    entries = _write_archive(archive_path)
    archive_bytes = archive_path.read_bytes()
    manifest = {
        "schema": 1,
        "created_utc": "2026-08-23T12:00:00Z",
        "volume": "openwa-data",
        "archive": {
            "name": "openwa.tar",
            "bytes": len(archive_bytes),
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "entries": entries,
        },
    }
    (source / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return source


@pytest.fixture(autouse=True)
def isolated_docker_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docker_bin = tmp_path / "docker-bin"
    docker_bin.mkdir()
    fake_script = docker_bin / "docker_fake.py"
    fake_script.write_text(
        """\
import re
import sys
import tarfile
from pathlib import Path


args = sys.argv[1:]
if not args or args[0] != "run" or "alpine:3.20" not in args:
    raise SystemExit(64)

mounts = [args[index + 1] for index, arg in enumerate(args[:-1]) if arg == "--mount"]
source_mounts = [
    re.fullmatch(r"type=bind,source=(.*),target=/quelle,readonly", mount)
    for mount in mounts
]
matches = [match for match in source_mounts if match is not None]
if len(matches) != 1:
    raise SystemExit(65)

archive_path = Path(matches[0].group(1)) / "openwa.tar"
try:
    with tarfile.open(archive_path, "r") as archive:
        entries = sum(member.isfile() for member in archive.getmembers())
except (OSError, tarfile.TarError):
    raise SystemExit(66)

print(f"OPENWA_ENTRIES={entries}")
""",
        encoding="utf-8",
    )
    launcher = docker_bin / "docker.cmd"
    launcher.write_bytes(
        (
            "@echo off\r\n"
            f'"{sys.executable}" "%~dp0docker_fake.py" %*\r\n'
        ).encode("utf-8")
    )
    monkeypatch.setenv("PATH", f"{docker_bin}{os.pathsep}{os.environ['PATH']}")


def _run_verifier(source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(VERIFY_SCRIPT),
            "-Quelle",
            str(source.resolve()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _read_manifest(backup_dir: Path) -> dict[str, object]:
    return json.loads((backup_dir / "MANIFEST.json").read_text(encoding="utf-8"))


def _write_manifest(backup_dir: Path, manifest: dict[str, object]) -> None:
    (backup_dir / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_valid_backup_is_verified_with_metadata_only(backup_dir: Path) -> None:
    manifest = _read_manifest(backup_dir)
    archive = manifest["archive"]
    assert isinstance(archive, dict)

    result = _run_verifier(backup_dir)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "openwa-data: verifiziert",
        f"Bytezahl: {archive['bytes']}",
        f"Dateizahl: {archive['entries']}",
        f"SHA-256: {archive['sha256']}",
    ]


def test_changed_archive_bytes_are_rejected(backup_dir: Path) -> None:
    with (backup_dir / "openwa.tar").open("ab") as archive:
        archive.write(b"changed")

    result = _run_verifier(backup_dir)

    assert result.returncode != 0


def test_wrong_manifest_volume_is_rejected(backup_dir: Path) -> None:
    manifest = _read_manifest(backup_dir)
    manifest["volume"] = "sales-claw-state"
    _write_manifest(backup_dir, manifest)

    result = _run_verifier(backup_dir)

    assert result.returncode != 0


@pytest.mark.parametrize("missing_name", ["MANIFEST.json", "openwa.tar"])
def test_missing_required_file_is_rejected(
    backup_dir: Path, missing_name: str
) -> None:
    (backup_dir / missing_name).unlink()

    result = _run_verifier(backup_dir)

    assert result.returncode != 0


@pytest.mark.parametrize("missing_field", ["bytes", "sha256", "entries"])
def test_missing_archive_metadata_is_rejected(
    backup_dir: Path, missing_field: str
) -> None:
    manifest = _read_manifest(backup_dir)
    archive = manifest["archive"]
    assert isinstance(archive, dict)
    del archive[missing_field]
    _write_manifest(backup_dir, manifest)

    result = _run_verifier(backup_dir)

    assert result.returncode != 0


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("bytes", 1),
        ("sha256", "0" * 64),
        ("entries", 2),
    ],
)
def test_incorrect_archive_metadata_is_rejected(
    backup_dir: Path, field: str, wrong_value: object
) -> None:
    manifest = _read_manifest(backup_dir)
    archive = manifest["archive"]
    assert isinstance(archive, dict)
    if field == "bytes":
        assert archive[field] != wrong_value
    archive[field] = wrong_value
    _write_manifest(backup_dir, manifest)

    result = _run_verifier(backup_dir)

    assert result.returncode != 0


def test_additional_archive_is_rejected(backup_dir: Path) -> None:
    (backup_dir / "other.tar").write_bytes(b"not allowed")

    result = _run_verifier(backup_dir)

    assert result.returncode != 0
