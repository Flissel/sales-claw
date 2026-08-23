from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path
from typing import BinaryIO, Iterator


ALLOWED_ROOT_FILES = (
    ".env.example",
    "docker-compose.yml",
    "docker-compose.openwa.yml",
    "docker-compose.proxmox.yml",
)
ALLOWED_ROOT_DIRS = (
    "config",
    "db",
    "docs",
    "media",
    "reports",
    "sales-mcp",
    "scripts",
    "openwa/upstream",
)
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".superpowers",
    "__pycache__",
    "backups",
    "dist",
    "graphify-out",
    "node_modules",
}

ARCHIVE_NAME = "sales-claw-proxmox-source.tar.gz"
MANIFEST_NAME = "sales-claw-proxmox-source.MANIFEST.json"
SECRET_SUFFIXES = (".pem", ".key", ".p12")
CHUNK_SIZE = 1024 * 1024


def build_package(source_root: Path, output_dir: Path) -> tuple[Path, Path]:
    """Create a tar.gz and JSON manifest without following symlinks."""
    source_root = source_root.absolute()
    output_dir = output_dir.absolute()
    if source_root.is_symlink() or not source_root.is_dir():
        raise ValueError("source_root must be a non-symlink directory")
    if not (source_root / ".git").is_dir() or (source_root / ".git").is_symlink():
        raise ValueError("source_root must contain a non-symlink .git directory")

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("output_dir must be a non-symlink directory")

    archive_path = output_dir / ARCHIVE_NAME
    manifest_path = output_dir / MANIFEST_NAME
    files = sorted(_iter_allowed_files(source_root), key=lambda item: item[0])
    records: list[dict[str, int | str]] = []

    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for relative_path, file_path in files:
            record = _add_regular_file(archive, file_path, relative_path)
            records.append(record)

    _probe_archive(archive_path)
    archive_bytes = archive_path.stat().st_size
    manifest = {
        "archive": archive_path.name,
        "archive_bytes": archive_bytes,
        "archive_sha256": _sha256_file(archive_path),
        "files": records,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return archive_path, manifest_path


def _iter_allowed_files(source_root: Path) -> Iterator[tuple[str, Path]]:
    candidates = [source_root / name for name in ALLOWED_ROOT_FILES]
    for relative_dir in ALLOWED_ROOT_DIRS:
        directory = source_root.joinpath(*relative_dir.split("/"))
        yield from _walk_allowed_directory(source_root, directory)

    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file() or _is_rejected(candidate, source_root):
            continue
        yield candidate.relative_to(source_root).as_posix(), candidate


def _walk_allowed_directory(source_root: Path, directory: Path) -> Iterator[tuple[str, Path]]:
    if directory.is_symlink() or not directory.is_dir() or _is_rejected(directory, source_root):
        return

    for entry in sorted(os.scandir(directory), key=lambda item: item.name):
        path = Path(entry.path)
        if entry.is_symlink() or _is_rejected(path, source_root):
            continue
        if entry.is_dir(follow_symlinks=False):
            yield from _walk_allowed_directory(source_root, path)
        elif entry.is_file(follow_symlinks=False):
            yield path.relative_to(source_root).as_posix(), path


def _is_rejected(path: Path, source_root: Path) -> bool:
    relative_parts = path.relative_to(source_root).parts
    lowered_parts = tuple(part.lower() for part in relative_parts)
    if any(part in EXCLUDED_PARTS for part in lowered_parts):
        return True
    if any(part.startswith("credentials-sicherung-") for part in lowered_parts[:-1]):
        return True
    file_name = lowered_parts[-1]
    return file_name == ".env" or file_name.endswith(SECRET_SUFFIXES)


def _add_regular_file(
    archive: tarfile.TarFile, file_path: Path, relative_path: str
) -> dict[str, int | str]:
    with _open_regular_file(file_path) as handle:
        file_stat = os.fstat(handle.fileno())
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"refusing non-regular file: {relative_path}")
        tar_info = tarfile.TarInfo(relative_path)
        tar_info.size = file_stat.st_size
        tar_info.mode = stat.S_IMODE(file_stat.st_mode)
        tar_info.mtime = 0
        digest = hashlib.sha256()
        archive.addfile(tar_info, _HashingReader(handle, digest))
    return {
        "path": relative_path,
        "bytes": file_stat.st_size,
        "sha256": digest.hexdigest(),
    }


def _open_regular_file(path: Path) -> BinaryIO:
    flags = os.O_RDONLY
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags | no_follow)
    except OSError as error:
        raise ValueError(f"refusing unreadable file: {path}") from error
    return os.fdopen(descriptor, "rb")


def _probe_archive(archive_path: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.getmembers()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _HashingReader:
    def __init__(self, handle: BinaryIO, digest: hashlib._Hash) -> None:
        self._handle = handle
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        self._digest.update(chunk)
        return chunk


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a safe Sales-Claw Proxmox source package.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    archive_path, manifest_path = build_package(arguments.source, arguments.output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "archive": str(archive_path),
                "archive_bytes": manifest["archive_bytes"],
                "archive_sha256": manifest["archive_sha256"],
                "file_count": len(manifest["files"]),
                "manifest": str(manifest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
