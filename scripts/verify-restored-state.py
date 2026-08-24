from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


VERIFY_SCRIPT = r"""
set -eu
archive="$1"
entry_kind="$2"
manifest_entries="$3"
mkdir -p /expected
tar -xf "/source/$archive" -C /expected
case "$entry_kind" in
  all) extracted_entries="$(find /expected -mindepth 1 | wc -l)" ;;
  files) extracted_entries="$(find /expected -type f | wc -l)" ;;
  *) exit 64 ;;
esac
test "$extracted_entries" -eq "$manifest_entries"
inventory() {
  root="$1"
  (cd "$root" && find . -type f -exec sha256sum {} \; | LC_ALL=C sort)
}
inventory /expected > /tmp/expected.sha256
inventory /actual > /tmp/actual.sha256
expected_files="$(find /expected -type f | wc -l)"
actual_files="$(find /actual -type f | wc -l)"
test "$expected_files" -eq "$actual_files"
cmp -s /tmp/expected.sha256 /tmp/actual.sha256
printf 'RESTORE_VERIFY expected_files=%s actual_files=%s status=ok\n' "$expected_files" "$actual_files"
""".strip()

ALPINE_IMAGE = "alpine:3.20"
RESULT_PATTERN = re.compile(
    r"RESTORE_VERIFY expected_files=(?P<expected>[0-9]+) "
    r"actual_files=(?P<actual>[0-9]+) status=ok"
)


class RestoreVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VolumeEvidence:
    volume: str
    source_dir: Path
    archive_name: str
    archive_bytes: int
    archive_sha256: str
    manifest_entries: int
    entry_kind: str


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RestoreVerificationError(f"{label} is invalid")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RestoreVerificationError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise RestoreVerificationError(f"{label} is invalid")
    return value.lower()


def _source_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        entry = absolute.lstat()
    except OSError:
        raise RestoreVerificationError(f"{label} is unavailable") from None
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
        raise RestoreVerificationError(f"{label} is unsafe")
    if any(character in str(absolute) for character in (",", "\r", "\n")):
        raise RestoreVerificationError(f"{label} cannot be mounted safely")
    return absolute


def _json_manifest(source: Path) -> Mapping[str, object]:
    path = source / "MANIFEST.json"
    try:
        entry = path.lstat()
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            raise RestoreVerificationError("manifest is unsafe")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except RestoreVerificationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RestoreVerificationError("manifest is invalid") from None
    return _mapping(value, "manifest")


def _archive_evidence(
    *,
    source: Path,
    volume: str,
    record: Mapping[str, object],
    archive_name: str,
    entries_field: str,
    entry_kind: str,
) -> VolumeEvidence:
    if record.get("datei", archive_name) != archive_name:
        raise RestoreVerificationError("archive name is invalid")
    expected_bytes = _nonnegative_integer(record.get("bytes"), "archive bytes")
    expected_sha256 = _sha256(record.get("sha256"), "archive hash")
    expected_entries = _nonnegative_integer(record.get(entries_field), "archive entries")
    archive_path = source / archive_name
    try:
        entry = archive_path.lstat()
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            raise RestoreVerificationError("archive is unsafe")
        digest = hashlib.sha256()
        size = 0
        with archive_path.open("rb") as archive:
            while chunk := archive.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except RestoreVerificationError:
        raise
    except OSError:
        raise RestoreVerificationError("archive is unavailable") from None
    if size != expected_bytes or digest.hexdigest() != expected_sha256:
        raise RestoreVerificationError("archive does not match manifest")
    return VolumeEvidence(
        volume=volume,
        source_dir=source,
        archive_name=archive_name,
        archive_bytes=expected_bytes,
        archive_sha256=expected_sha256,
        manifest_entries=expected_entries,
        entry_kind=entry_kind,
    )


def _load_evidence(state_backup: Path, openwa_backup: Path) -> tuple[VolumeEvidence, ...]:
    state_source = _source_directory(state_backup, "state backup")
    openwa_source = _source_directory(openwa_backup, "OpenWA backup")
    state_manifest = _json_manifest(state_source)
    if state_manifest.get("container_gestoppt") is not True:
        raise RestoreVerificationError("state backup is not from a stopped container")
    if state_manifest.get("stop_exit_code") == 137:
        raise RestoreVerificationError("state backup was hard-stopped")
    state_archives = _mapping(state_manifest.get("archive"), "state archives")

    openwa_manifest = _json_manifest(openwa_source)
    if openwa_manifest.get("schema") != 1 or openwa_manifest.get("volume") != "openwa-data":
        raise RestoreVerificationError("OpenWA manifest is invalid")
    openwa_archive = _mapping(openwa_manifest.get("archive"), "OpenWA archive")
    if openwa_archive.get("name", "openwa.tar") != "openwa.tar":
        raise RestoreVerificationError("OpenWA archive name is invalid")

    return (
        _archive_evidence(
            source=state_source,
            volume="sales-claw-state",
            record=_mapping(state_archives.get("state"), "state archive"),
            archive_name="state.tar",
            entries_field="eintraege",
            entry_kind="all",
        ),
        _archive_evidence(
            source=state_source,
            volume="sales-claw-keys",
            record=_mapping(state_archives.get("keys"), "keys archive"),
            archive_name="keys.tar",
            entries_field="eintraege",
            entry_kind="all",
        ),
        _archive_evidence(
            source=openwa_source,
            volume="openwa-data",
            record=openwa_archive,
            archive_name="openwa.tar",
            entries_field="entries",
            entry_kind="files",
        ),
    )


def _default_runner(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise RestoreVerificationError("Docker verification could not be started")
    try:
        return subprocess.run(
            [executable, *arguments[1:]],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError:
        raise RestoreVerificationError("Docker verification could not be started") from None


def _verify_volume(evidence: VolumeEvidence, run: Runner) -> int:
    completed = run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--mount",
            f"type=bind,source={evidence.source_dir},target=/source,readonly",
            "--mount",
            f"type=volume,source={evidence.volume},target=/actual,readonly",
            ALPINE_IMAGE,
            "sh",
            "-c",
            VERIFY_SCRIPT,
            "verify-restored-state",
            evidence.archive_name,
            evidence.entry_kind,
            str(evidence.manifest_entries),
        ]
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise RestoreVerificationError("restored volume comparison failed")
    lines = completed.stdout.splitlines()
    if len(lines) != 1:
        raise RestoreVerificationError("restored volume result is invalid")
    match = RESULT_PATTERN.fullmatch(lines[0])
    if match is None:
        raise RestoreVerificationError("restored volume result is invalid")
    expected = int(match.group("expected"))
    actual = int(match.group("actual"))
    if expected != actual:
        raise RestoreVerificationError("restored volume file count differs")
    return actual


def _require_existing_volume(volume: str, run: Runner) -> None:
    completed = run(
        [
            "docker",
            "volume",
            "inspect",
            "--format",
            "{{.Name}}",
            volume,
        ]
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise RestoreVerificationError("restored volume is unavailable")
    if completed.stdout.splitlines() != [volume]:
        raise RestoreVerificationError("restored volume identity is invalid")


def verify_restored_state(
    state_backup: Path,
    openwa_backup: Path,
    *,
    run: Runner = _default_runner,
) -> tuple[tuple[str, int], ...]:
    evidence = _load_evidence(state_backup, openwa_backup)
    for item in evidence:
        _require_existing_volume(item.volume, run)
    return tuple((item.volume, _verify_volume(item, run)) for item in evidence)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the three restored Sales-Claw volumes")
    parser.add_argument("--state-backup", required=True, type=Path)
    parser.add_argument("--openwa-backup", required=True, type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Runner = _default_runner,
) -> int:
    arguments = _parser().parse_args(argv)
    try:
        results = verify_restored_state(
            arguments.state_backup,
            arguments.openwa_backup,
            run=run,
        )
    except RestoreVerificationError:
        print("restore verification: rejected", file=sys.stderr)
        return 1
    for volume, count in results:
        print(f"{volume}: verified ({count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
