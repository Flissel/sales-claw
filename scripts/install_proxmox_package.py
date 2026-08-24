from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
from collections.abc import Mapping, Sequence


ARCHIVE_NAME = "sales-claw-proxmox-source.tar.gz"
EXECUTABLE_FILES = frozenset(
    {
        "openwa/upstream/backup.sh",
        "openwa/upstream/restore.sh",
    }
)


class InstallError(ValueError):
    pass


def _regular_file_bytes(path: Path, label: str) -> bytes:
    try:
        entry = path.lstat()
    except OSError:
        raise InstallError(f"{label} is unavailable") from None
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise InstallError(f"{label} is not a regular file")
    try:
        return path.read_bytes()
    except OSError:
        raise InstallError(f"{label} is unreadable") from None


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstallError("manifest contains an unsafe path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in ("", ".", "..") for part in parsed.parts):
        raise InstallError("manifest contains an unsafe path")
    return value


def _file_records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InstallError("manifest file inventory is invalid")
    records: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "bytes", "sha256"}:
            raise InstallError("manifest file record is invalid")
        path = _safe_path(raw["path"])
        size = raw["bytes"]
        digest = raw["sha256"]
        if type(size) is not int or size < 0:
            raise InstallError("manifest file size is invalid")
        if not isinstance(digest, str) or len(digest) != 64:
            raise InstallError("manifest file hash is invalid")
        try:
            int(digest, 16)
        except ValueError:
            raise InstallError("manifest file hash is invalid") from None
        records.append({"path": path, "bytes": size, "sha256": digest.lower()})
    paths = [str(record["path"]) for record in records]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise InstallError("manifest file inventory is not unique and sorted")
    return records


def _commit_id(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) not in (40, 64):
        raise InstallError(f"{label} is invalid")
    try:
        int(value, 16)
    except ValueError:
        raise InstallError(f"{label} is invalid") from None
    return value.lower()


def _manifest(
    manifest_blob: bytes,
    archive_blob: bytes,
    expected_commit: str,
) -> list[dict[str, object]]:
    try:
        value = json.loads(manifest_blob.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InstallError("manifest is invalid") from None
    if not isinstance(value, Mapping):
        raise InstallError("manifest is invalid")
    if value.get("archive") != ARCHIVE_NAME:
        raise InstallError("manifest archive name is invalid")
    source_commit = _commit_id(value.get("source_commit"), "manifest source commit")
    if source_commit != _commit_id(expected_commit, "expected source commit"):
        raise InstallError("manifest source commit does not match reviewed commit")
    if type(value.get("archive_bytes")) is not int or value["archive_bytes"] != len(archive_blob):
        raise InstallError("manifest archive size does not match")
    digest = value.get("archive_sha256")
    if not isinstance(digest, str) or digest.lower() != hashlib.sha256(archive_blob).hexdigest():
        raise InstallError("manifest archive hash does not match")
    return _file_records(value.get("files"))


def _verified_members(
    archive_blob: bytes, records: list[dict[str, object]]
) -> list[tarfile.TarInfo]:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_blob), mode="r:gz") as archive:
            members = archive.getmembers()
            if [member.name for member in members] != [record["path"] for record in records]:
                raise InstallError("archive inventory does not match manifest")
            for member, record in zip(members, records, strict=True):
                path = _safe_path(member.name)
                expected_mode = 0o755 if path in EXECUTABLE_FILES else 0o644
                if not member.isfile() or member.mode != expected_mode:
                    raise InstallError("archive contains an unsafe member")
                source = archive.extractfile(member)
                if source is None:
                    raise InstallError("archive member is unreadable")
                payload = source.read()
                if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
                    raise InstallError("archive member does not match manifest")
    except (OSError, tarfile.TarError):
        raise InstallError("archive is invalid") from None
    return members


def _require_fresh_destination(destination: Path) -> None:
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise InstallError("destination is unavailable") from None
    else:
        raise InstallError("destination must not exist")
    parent = destination.parent
    try:
        parent_stat = parent.lstat()
    except OSError:
        raise InstallError("destination parent is unavailable") from None
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise InstallError("destination parent is unsafe")
    if os.name != "nt" and parent_stat.st_uid != os.geteuid():
        raise InstallError("destination parent has the wrong owner")


def install_package(
    archive_path: Path,
    manifest_path: Path,
    destination: Path,
    *,
    expected_commit: str,
) -> int:
    archive_blob = _regular_file_bytes(archive_path, "archive")
    manifest_blob = _regular_file_bytes(manifest_path, "manifest")
    records = _manifest(manifest_blob, archive_blob, expected_commit)
    members = _verified_members(archive_blob, records)
    _require_fresh_destination(destination)

    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_blob), mode="r:gz") as archive:
            for member, record in zip(members, records, strict=True):
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                source = archive.extractfile(member)
                if source is None:
                    raise InstallError("archive member is unreadable")
                digest = hashlib.sha256()
                size = 0
                with target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if size != record["bytes"] or digest.hexdigest() != record["sha256"]:
                    raise InstallError("installed file does not match manifest")
                target.chmod(member.mode)
    except Exception:
        shutil.rmtree(destination)
        raise
    return len(records)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and install a Proxmox source package")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        count = install_package(
            arguments.archive,
            arguments.manifest,
            arguments.destination,
            expected_commit=arguments.expected_commit,
        )
    except InstallError:
        print("source package: rejected")
        return 1
    print(f"source package: installed ({count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
