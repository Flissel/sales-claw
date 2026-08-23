from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterator

ALLOWED_ROOT_FILES = (".env.example", "docker-compose.yml", "docker-compose.openwa.yml", "docker-compose.proxmox.yml")
ALLOWED_ROOT_DIRS = ("config", "db", "docs", "media", "reports", "sales-mcp", "scripts", "openwa/upstream")
EXCLUDED_PARTS = {".git", ".pytest_cache", ".superpowers", "__pycache__", "backups", "dist", "graphify-out", "node_modules"}
ARCHIVE_NAME = "sales-claw-proxmox-source.tar.gz"
MANIFEST_NAME = "sales-claw-proxmox-source.MANIFEST.json"
SECRET_SUFFIXES = (".pem", ".key", ".p12")
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class _Identity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _Candidate:
    relative_path: str
    path: Path
    identity: _Identity


def build_package(source_root: Path, output_dir: Path) -> tuple[Path, Path]:
    """Create a tar.gz and JSON manifest without following symlinks."""
    source_root, output_dir = source_root.absolute(), output_dir.absolute()
    _require_source_root(source_root)
    _require_output_dir(output_dir)
    archive_path, manifest_path = output_dir / ARCHIVE_NAME, output_dir / MANIFEST_NAME
    archive_fd, archive_temp = _temp_file(output_dir)
    manifest_fd, manifest_temp = _temp_file(output_dir)
    published = False
    try:
        records: list[dict[str, int | str]] = []
        candidates = sorted(_iter_allowed_files(source_root), key=lambda item: item.relative_path)
        with os.fdopen(archive_fd, "w+b") as archive_handle:
            archive_fd = -1
            with tarfile.open(fileobj=archive_handle, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
                for candidate in candidates:
                    records.append(_add_regular_file(archive, candidate))
            archive_handle.flush(); os.fsync(archive_handle.fileno()); archive_handle.seek(0)
            _probe_archive_handle(archive_handle)
            archive_bytes = os.fstat(archive_handle.fileno()).st_size
            archive_handle.seek(0)
            archive_sha256 = _sha256_handle(archive_handle)
        manifest = {"archive": archive_path.name, "archive_bytes": archive_bytes, "archive_sha256": archive_sha256, "files": records}
        with os.fdopen(manifest_fd, "wb") as manifest_handle:
            manifest_fd = -1
            manifest_handle.write((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            manifest_handle.flush(); os.fsync(manifest_handle.fileno())
        _publish_pair(archive_temp, manifest_temp, archive_path, manifest_path)
        published = True
        return archive_path, manifest_path
    finally:
        if archive_fd >= 0: os.close(archive_fd)
        if manifest_fd >= 0: os.close(manifest_fd)
        if not published:
            _remove_temp(archive_temp); _remove_temp(manifest_temp)


def _require_source_root(source_root: Path) -> None:
    git_dir = source_root / ".git"
    if source_root.is_symlink() or not source_root.is_dir() or git_dir.is_symlink() or not git_dir.is_dir():
        raise ValueError("source_root must contain a non-symlink .git directory")


def _require_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    entry = output_dir.lstat()
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
        raise ValueError("output_dir must be a non-symlink directory")


def _temp_file(output_dir: Path) -> tuple[int, Path]:
    descriptor, path = tempfile.mkstemp(prefix=".sales-claw-proxmox-", suffix=".tmp", dir=output_dir)
    return descriptor, Path(path)


def _iter_allowed_files(root: Path) -> Iterator[_Candidate]:
    for name in ALLOWED_ROOT_FILES:
        candidate = _candidate(root / name, root)
        if candidate: yield candidate
    for relative_dir in ALLOWED_ROOT_DIRS:
        yield from _walk(root, root.joinpath(*relative_dir.split("/")))


def _walk(root: Path, directory: Path) -> Iterator[_Candidate]:
    if directory.is_symlink() or not directory.is_dir() or _is_rejected(directory, root): return
    for entry in sorted(os.scandir(directory), key=lambda item: item.name):
        path = Path(entry.path)
        if entry.is_symlink() or _is_rejected(path, root): continue
        if entry.is_dir(follow_symlinks=False): yield from _walk(root, path)
        elif entry.is_file(follow_symlinks=False):
            candidate = _candidate(path, root)
            if candidate: yield candidate


def _candidate(path: Path, root: Path) -> _Candidate | None:
    if path.is_symlink() or _is_rejected(path, root): return None
    try: file_stat = path.lstat()
    except FileNotFoundError: return None
    except OSError as error: raise ValueError(f"source file is unavailable: {path.relative_to(root).as_posix()}") from error
    if not stat.S_ISREG(file_stat.st_mode): return None
    return _Candidate(path.relative_to(root).as_posix(), path, _identity(file_stat))


def _is_rejected(path: Path, root: Path) -> bool:
    parts = tuple(part.lower() for part in path.relative_to(root).parts)
    return any(part in EXCLUDED_PARTS or part.startswith("credentials-sicherung-") for part in parts) or parts[-1] == ".env" or parts[-1].endswith(SECRET_SUFFIXES)


def _add_regular_file(archive: tarfile.TarFile, candidate: _Candidate) -> dict[str, int | str]:
    with _open_verified(candidate) as handle:
        info = tarfile.TarInfo(candidate.relative_path); info.size = candidate.identity.size; info.mode = 0o644; info.mtime = 0
        digest = hashlib.sha256(); archive.addfile(info, _HashingReader(handle, digest))
    return {"path": candidate.relative_path, "bytes": candidate.identity.size, "sha256": digest.hexdigest()}


def _open_verified(candidate: _Candidate) -> BinaryIO:
    try: descriptor = os.open(candidate.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error: raise ValueError(f"source file changed or is a symlink: {candidate.relative_path}") from error
    handle = os.fdopen(descriptor, "rb")
    opened = os.fstat(handle.fileno())
    if not stat.S_ISREG(opened.st_mode) or _identity(opened) != candidate.identity:
        handle.close(); raise ValueError(f"source file changed or is a symlink: {candidate.relative_path}")
    return handle


def _identity(file_stat: os.stat_result) -> _Identity:
    return _Identity(file_stat.st_dev, file_stat.st_ino, file_stat.st_size, file_stat.st_mtime_ns, file_stat.st_ctime_ns)


def _probe_archive_handle(handle: BinaryIO) -> None:
    with tarfile.open(fileobj=handle, mode="r:gz") as archive: archive.getmembers()


def _sha256_handle(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""): digest.update(chunk)
    return digest.hexdigest()


def _publish_pair(archive_temp: Path, manifest_temp: Path, archive_path: Path, manifest_path: Path) -> None:
    for path in (archive_temp, manifest_temp, archive_path, manifest_path): _require_regular_or_missing(path)
    backups = [(path, _backup_path(path.parent), path.exists()) for path in (archive_path, manifest_path)]
    moved: set[Path] = set()
    try:
        for path, backup, exists in backups:
            if exists:
                os.replace(path, backup)
                moved.add(path)
        os.replace(archive_temp, archive_path); os.replace(manifest_temp, manifest_path)
    except BaseException:
        for path, backup, exists in backups:
            if path in moved and path.exists() and not path.is_symlink(): path.unlink()
            if path in moved and exists: os.replace(backup, path)
        raise
    finally:
        for _, backup, _ in backups: _remove_temp(backup)


def _backup_path(output_dir: Path) -> Path:
    descriptor, path = _temp_file(output_dir)
    os.close(descriptor)
    return path


def _require_regular_or_missing(path: Path) -> None:
    try: entry = path.lstat()
    except FileNotFoundError: return
    if stat.S_ISLNK(entry.st_mode): raise ValueError(f"refusing symlink output target: {path.name}")
    if not stat.S_ISREG(entry.st_mode): raise ValueError(f"output target must be a regular file: {path.name}")


def _remove_temp(path: Path) -> None:
    try:
        if path.exists() and not path.is_symlink(): path.unlink()
    except OSError: pass


class _HashingReader:
    def __init__(self, handle: BinaryIO, digest: object) -> None: self._handle, self._digest = handle, digest
    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size); self._digest.update(chunk)  # type: ignore[attr-defined]
        return chunk


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a safe Sales-Claw Proxmox source package.")
    parser.add_argument("--source", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(); archive_path, manifest_path = build_package(arguments.source, arguments.output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(json.dumps({"archive": str(archive_path), "archive_bytes": manifest["archive_bytes"], "archive_sha256": manifest["archive_sha256"], "file_count": len(manifest["files"]), "manifest": str(manifest_path)}, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
