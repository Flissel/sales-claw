from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import stat
import tarfile
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

if os.name == "nt":
    import msvcrt


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
JOURNAL_NAME = ".sales-claw-proxmox-source.TRANSACTION.json"
SECRET_SUFFIXES = (".pem", ".key", ".p12")
EXECUTABLE_FILES = frozenset(
    {
        "openwa/upstream/backup.sh",
        "openwa/upstream/restore.sh",
    }
)
CHUNK_SIZE = 1024 * 1024

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_FILE_RENAME_INFO_CLASS = 3
_MOVEFILE_WRITE_THROUGH = 0x00000008
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", _FileTime),
        ("last_access_time", _FileTime),
        ("last_write_time", _FileTime),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


class _FileRenameInformation(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("root_directory", ctypes.c_void_p),
        ("file_name_length", ctypes.c_uint32),
        ("file_name", ctypes.c_wchar * 1),
    ]


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    _CREATE_FILE.restype = ctypes.c_void_p
    _GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandle
    _GET_FILE_INFORMATION.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _GET_FILE_INFORMATION.restype = ctypes.c_int
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
    _CLOSE_HANDLE.restype = ctypes.c_int
    _SET_FILE_INFORMATION = _KERNEL32.SetFileInformationByHandle
    _SET_FILE_INFORMATION.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _SET_FILE_INFORMATION.restype = ctypes.c_int
    _MOVE_FILE_EX = _KERNEL32.MoveFileExW
    _MOVE_FILE_EX.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    _MOVE_FILE_EX.restype = ctypes.c_int


@dataclass(frozen=True)
class _Identity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _HandleInfo:
    attributes: int
    device: int
    inode: int
    size: int


@dataclass(frozen=True)
class _ObjectIdentity:
    device: int
    inode: int


@dataclass
class _PinnedArtifact:
    path: Path
    handle: BinaryIO
    identity: _ObjectIdentity

    def seal(self) -> None:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.verify()

    def verify(self) -> None:
        info = _get_windows_handle_info(msvcrt.get_osfhandle(self.handle.fileno()))
        if (
            info.attributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY)
            or info.device != self.identity.device
            or info.inode != self.identity.inode
        ):
            raise ValueError(f"temporary artifact identity changed: {self.path.name}")

    def rename(self, destination: Path) -> None:
        _require_missing(destination)
        self.verify()
        _rename_open_file(self.handle, destination)
        self.path = destination
        self.verify()
        _verify_named_artifact(self)

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.close()


@dataclass(frozen=True)
class _Candidate:
    relative_path: str
    path: Path
    identity: _Identity


@dataclass
class _PinnedDirectory:
    path: Path
    handle: int | None

    def close(self) -> None:
        if self.handle is not None:
            _close_windows_handle(self.handle)
            self.handle = None


@dataclass
class _PinnedChain:
    directories: list[_PinnedDirectory]

    @property
    def path(self) -> Path:
        return self.directories[-1].path

    @classmethod
    def open(cls, path: Path, *, create: bool, label: str) -> _PinnedChain:
        directories: list[_PinnedDirectory] = []
        current = Path(path.anchor)
        try:
            for index, part in enumerate(path.parts):
                if index:
                    current /= part
                try:
                    entry = current.lstat()
                except FileNotFoundError:
                    if not create:
                        raise ValueError(f"{label} directory is unavailable: {current}") from None
                    try:
                        os.mkdir(current)
                    except FileExistsError:
                        pass
                    entry = current.lstat()
                if _stat_is_reparse(entry) or not stat.S_ISDIR(entry.st_mode):
                    raise ValueError(f"{label} must contain only non-reparse directories: {current}")
                directories.append(
                    _pin_directory(current, _identity(entry), f"{label} directory changed or is a reparse point")
                )
            return cls(directories)
        except BaseException:
            for directory in reversed(directories):
                directory.close()
            raise

    def pin_child(self, path: Path, expected: _Identity, label: str) -> _PinnedDirectory:
        pinned = _pin_directory(path, expected, label)
        self.directories.append(pinned)
        return pinned

    def close(self) -> None:
        for directory in reversed(self.directories):
            directory.close()


@dataclass
class _SourceTree:
    root: Path
    chain: _PinnedChain

    @classmethod
    def open(cls, root: Path) -> _SourceTree:
        chain = _PinnedChain.open(root, create=False, label="source_root")
        try:
            git_dir = root / ".git"
            try:
                git_stat = git_dir.lstat()
            except FileNotFoundError:
                raise ValueError("source_root must contain a non-reparse .git directory") from None
            if _stat_is_reparse(git_stat) or not stat.S_ISDIR(git_stat.st_mode):
                raise ValueError("source_root must contain a non-reparse .git directory")
            chain.pin_child(
                git_dir,
                _identity(git_stat),
                "source_root .git directory changed or is a reparse point",
            )
            return cls(root, chain)
        except BaseException:
            chain.close()
            raise

    def pin_directory(self, path: Path, expected: _Identity, relative_path: str) -> _PinnedDirectory:
        return self.chain.pin_child(
            path,
            expected,
            f"source directory changed or is a reparse point: {relative_path}",
        )

    def close(self) -> None:
        self.chain.close()


@dataclass(frozen=True)
class _Transaction:
    transaction_id: str
    had_old_pair: bool
    archive_temp_name: str
    manifest_temp_name: str

    @property
    def archive_backup_name(self) -> str:
        return f".sales-claw-proxmox-source.{self.transaction_id}.archive.backup"

    @property
    def manifest_backup_name(self) -> str:
        return f".sales-claw-proxmox-source.{self.transaction_id}.manifest.backup"

    @property
    def retired_journal_name(self) -> str:
        return f".sales-claw-proxmox-source.DONE.{self.transaction_id}.json"


class _Digest(Protocol):
    def update(self, data: bytes) -> object:
        ...


def build_package(source_root: Path, output_dir: Path) -> tuple[Path, Path]:
    """Create a tar.gz and JSON manifest without following reparse points."""
    _require_secure_platform()
    source_root = _absolute_without_resolving(source_root)
    output_dir = _absolute_without_resolving(output_dir)
    source_tree = _SourceTree.open(source_root)
    output_chain: _PinnedChain | None = None
    archive_temp: _PinnedArtifact | None = None
    manifest_temp: _PinnedArtifact | None = None
    try:
        output_chain = _PinnedChain.open(output_dir, create=True, label="output_dir")
        _cleanup_committed_transactions(output_dir)
        _recover_interrupted_transaction(output_dir)
        _validate_public_pair(output_dir)
        _inject_fault("before_temp_creation", output_dir)
        archive_temp = _temp_file(output_dir)
        manifest_temp = _temp_file(output_dir)
        records: list[dict[str, int | str]] = []
        candidates = sorted(_iter_allowed_files(source_tree), key=lambda item: item.relative_path)
        archive_handle = archive_temp.handle
        with tarfile.open(
            fileobj=archive_handle,
            mode="w:gz",
            format=tarfile.PAX_FORMAT,
        ) as archive:
            for candidate in candidates:
                records.append(_add_regular_file(archive, candidate))
        archive_temp.seal()
        archive_handle.seek(0)
        _probe_archive_handle(archive_handle)
        archive_bytes = os.fstat(archive_handle.fileno()).st_size
        archive_handle.seek(0)
        archive_sha256 = _sha256_handle(archive_handle)
        archive_path = output_dir / ARCHIVE_NAME
        manifest_path = output_dir / MANIFEST_NAME
        manifest = {
            "archive": archive_path.name,
            "archive_bytes": archive_bytes,
            "archive_sha256": archive_sha256,
            "files": records,
        }
        manifest_handle = manifest_temp.handle
        manifest_handle.write(
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        manifest_temp.seal()
        _validate_artifact_pair(archive_temp, manifest_temp)
        _inject_fault("before_publication", output_dir)
        _publish_pair(archive_temp, manifest_temp, output_dir)
        return archive_path, manifest_path
    finally:
        for artifact in (manifest_temp, archive_temp):
            if artifact is not None:
                artifact.close()
                if _valid_temp_name(artifact.path.name):
                    _remove_temp(artifact.path)
        source_tree.close()
        if output_chain is not None:
            output_chain.close()


def _require_secure_platform() -> None:
    if os.name != "nt":
        raise RuntimeError("secure packaging requires Windows no-reparse directory handles")


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _pin_directory(path: Path, expected: _Identity, label: str) -> _PinnedDirectory:
    try:
        handle = _create_windows_handle(
            path,
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        )
    except OSError as error:
        raise ValueError(f"{label}: {path}") from error
    try:
        info = _get_windows_handle_info(handle)
        if (
            info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or not info.attributes & _FILE_ATTRIBUTE_DIRECTORY
            or info.device != expected.device
            or info.inode != expected.inode
        ):
            raise ValueError(f"{label}: {path}")
        return _PinnedDirectory(path, handle)
    except BaseException:
        _close_windows_handle(handle)
        raise


def _create_windows_handle(
    path: Path,
    access: int,
    share: int,
    flags: int,
    *,
    creation: int = _OPEN_EXISTING,
) -> int:
    handle = _CREATE_FILE(
        _windows_api_path(path),
        access,
        share,
        None,
        creation,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _get_windows_handle_info(handle: int) -> _HandleInfo:
    raw = _ByHandleFileInformation()
    if not _GET_FILE_INFORMATION(ctypes.c_void_p(handle), ctypes.byref(raw)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _HandleInfo(
        attributes=int(raw.attributes),
        device=int(raw.volume_serial_number),
        inode=(int(raw.file_index_high) << 32) | int(raw.file_index_low),
        size=(int(raw.file_size_high) << 32) | int(raw.file_size_low),
    )


def _close_windows_handle(handle: int) -> None:
    if not _CLOSE_HANDLE(ctypes.c_void_p(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _windows_api_path(path: Path) -> str:
    value = str(path)
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _iter_allowed_files(tree: _SourceTree) -> Iterator[_Candidate]:
    for name in ALLOWED_ROOT_FILES:
        candidate = _candidate(tree.root / name, tree.root)
        if candidate is not None:
            yield candidate
    for relative_dir in ALLOWED_ROOT_DIRS:
        pinned = _pin_relative_directory(tree, relative_dir)
        if pinned is not None:
            yield from _walk(tree, pinned)


def _pin_relative_directory(tree: _SourceTree, relative_dir: str) -> _PinnedDirectory | None:
    current = tree.root
    pinned: _PinnedDirectory | None = None
    for part in relative_dir.split("/"):
        current /= part
        if _is_rejected(current, tree.root):
            return None
        try:
            entry = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ValueError(
                f"source directory is unavailable: {current.relative_to(tree.root).as_posix()}"
            ) from error
        if _stat_is_reparse(entry) or not stat.S_ISDIR(entry.st_mode):
            return None
        relative_path = current.relative_to(tree.root).as_posix()
        pinned = tree.pin_directory(current, _identity(entry), relative_path)
    return pinned


def _walk(tree: _SourceTree, directory: _PinnedDirectory) -> Iterator[_Candidate]:
    _inject_fault("before_directory_enumeration", directory.path)
    try:
        entries = sorted(os.scandir(directory.path), key=lambda item: item.name)
    except OSError as error:
        relative_path = directory.path.relative_to(tree.root).as_posix()
        raise ValueError(f"source directory is unavailable: {relative_path}") from error
    for entry in entries:
        path = Path(entry.path)
        if _is_rejected(path, tree.root):
            continue
        try:
            entry_stat = path.lstat()
        except OSError as error:
            relative_path = path.relative_to(tree.root).as_posix()
            raise ValueError(f"source entry changed while scanning: {relative_path}") from error
        if _stat_is_reparse(entry_stat):
            continue
        if stat.S_ISDIR(entry_stat.st_mode):
            relative_path = path.relative_to(tree.root).as_posix()
            child = tree.pin_directory(path, _identity(entry_stat), relative_path)
            yield from _walk(tree, child)
        elif stat.S_ISREG(entry_stat.st_mode):
            yield _Candidate(
                path.relative_to(tree.root).as_posix(),
                path,
                _identity(entry_stat),
            )


def _candidate(path: Path, root: Path) -> _Candidate | None:
    if _is_rejected(path, root):
        return None
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"source file is unavailable: {path.relative_to(root).as_posix()}") from error
    if _stat_is_reparse(file_stat) or not stat.S_ISREG(file_stat.st_mode):
        return None
    return _Candidate(path.relative_to(root).as_posix(), path, _identity(file_stat))


def _stat_is_reparse(file_stat: os.stat_result) -> bool:
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return stat.S_ISLNK(file_stat.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _is_rejected(path: Path, root: Path) -> bool:
    parts = tuple(part.lower() for part in path.relative_to(root).parts)
    return (
        any(part in EXCLUDED_PARTS or part.startswith("credentials-sicherung-") for part in parts)
        or parts[-1] == ".env"
        or parts[-1].endswith(SECRET_SUFFIXES)
    )


def _add_regular_file(archive: tarfile.TarFile, candidate: _Candidate) -> dict[str, int | str]:
    with _open_verified(candidate) as handle:
        info = tarfile.TarInfo(candidate.relative_path)
        info.size = candidate.identity.size
        info.mode = 0o755 if candidate.relative_path in EXECUTABLE_FILES else 0o644
        info.mtime = 0
        digest = hashlib.sha256()
        archive.addfile(info, _HashingReader(handle, digest))
    return {
        "path": candidate.relative_path,
        "bytes": candidate.identity.size,
        "sha256": digest.hexdigest(),
    }


def _open_verified(candidate: _Candidate) -> BinaryIO:
    _inject_fault("before_source_file_open", candidate.path)
    return _open_regular_file(
        candidate.path,
        expected=candidate.identity,
        error_message=f"source file changed or is a symlink: {candidate.relative_path}",
    )


def _open_regular_file(
    path: Path,
    *,
    expected: _Identity | None,
    error_message: str,
) -> BinaryIO:
    try:
        handle = _create_windows_handle(
            path,
            _GENERIC_READ,
            _FILE_SHARE_READ,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_SEQUENTIAL_SCAN,
        )
    except OSError as error:
        raise ValueError(error_message) from error
    descriptor = -1
    try:
        info = _get_windows_handle_info(handle)
        if info.attributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY):
            raise ValueError(error_message)
        if expected is not None and (
            info.device != expected.device
            or info.inode != expected.inode
            or info.size != expected.size
        ):
            raise ValueError(error_message)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = -1
        file_handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        opened = _identity(os.fstat(file_handle.fileno()))
        if expected is not None and opened != expected:
            file_handle.close()
            raise ValueError(error_message)
        return file_handle
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if handle >= 0:
            _close_windows_handle(handle)
        raise


def _identity(file_stat: os.stat_result) -> _Identity:
    return _Identity(
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _probe_archive_handle(handle: BinaryIO) -> None:
    with tarfile.open(fileobj=handle, mode="r:gz") as archive:
        archive.getmembers()


def _sha256_handle(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _temp_file(output_dir: Path) -> _PinnedArtifact:
    for _ in range(128):
        path = output_dir / f".sales-claw-proxmox-{secrets.token_hex(16)}.tmp"
        try:
            raw_handle = _create_windows_handle(
                path,
                _GENERIC_READ | _GENERIC_WRITE | _DELETE,
                0,
                _FILE_ATTRIBUTE_NORMAL
                | _FILE_FLAG_OPEN_REPARSE_POINT
                | _FILE_FLAG_WRITE_THROUGH,
                creation=_CREATE_NEW,
            )
        except OSError as error:
            if getattr(error, "winerror", None) in {80, 183}:
                continue
            raise
        descriptor = -1
        try:
            info = _get_windows_handle_info(raw_handle)
            if info.attributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY):
                raise ValueError(f"temporary artifact is not a regular file: {path.name}")
            identity = _ObjectIdentity(info.device, info.inode)
            descriptor = msvcrt.open_osfhandle(raw_handle, os.O_RDWR | os.O_BINARY)
            raw_handle = -1
            handle = os.fdopen(descriptor, "w+b")
            descriptor = -1
            return _PinnedArtifact(path, handle, identity)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            if raw_handle >= 0:
                _close_windows_handle(raw_handle)
            _remove_temp(path)
            raise
    raise FileExistsError("could not allocate a unique pinned temporary artifact")


def _rename_open_file(handle: BinaryIO, destination: Path) -> None:
    encoded_name = _windows_api_path(destination).encode("utf-16-le")
    buffer_size = (
        ctypes.sizeof(_FileRenameInformation)
        - ctypes.sizeof(ctypes.c_wchar)
        + len(encoded_name)
    )
    buffer = ctypes.create_string_buffer(buffer_size)
    information = ctypes.cast(
        buffer,
        ctypes.POINTER(_FileRenameInformation),
    ).contents
    information.flags = 0
    information.root_directory = None
    information.file_name_length = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + _FileRenameInformation.file_name.offset,
        encoded_name,
        len(encoded_name),
    )
    raw_handle = msvcrt.get_osfhandle(handle.fileno())
    if not _SET_FILE_INFORMATION(
        ctypes.c_void_p(raw_handle),
        _FILE_RENAME_INFO_CLASS,
        buffer,
        buffer_size,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    os.fsync(handle.fileno())


def _verify_named_artifact(artifact: _PinnedArtifact) -> None:
    try:
        entry = artifact.path.lstat()
    except OSError as error:
        raise ValueError(f"published artifact is unavailable: {artifact.path.name}") from error
    if (
        _stat_is_reparse(entry)
        or not stat.S_ISREG(entry.st_mode)
        or entry.st_dev != artifact.identity.device
        or entry.st_ino != artifact.identity.inode
    ):
        raise ValueError(f"published artifact identity changed: {artifact.path.name}")


def _open_existing_artifact(path: Path, error_message: str) -> _PinnedArtifact:
    try:
        expected = path.lstat()
    except OSError as error:
        raise ValueError(error_message) from error
    if _stat_is_reparse(expected) or not stat.S_ISREG(expected.st_mode):
        raise ValueError(error_message)
    try:
        raw_handle = _create_windows_handle(
            path,
            _GENERIC_READ | _GENERIC_WRITE | _DELETE,
            0,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_WRITE_THROUGH,
        )
    except OSError as error:
        raise ValueError(error_message) from error
    descriptor = -1
    try:
        info = _get_windows_handle_info(raw_handle)
        if (
            info.attributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY)
            or info.device != expected.st_dev
            or info.inode != expected.st_ino
            or info.size != expected.st_size
        ):
            raise ValueError(error_message)
        descriptor = msvcrt.open_osfhandle(raw_handle, os.O_RDWR | os.O_BINARY)
        raw_handle = -1
        handle = os.fdopen(descriptor, "r+b")
        descriptor = -1
        if _identity(os.fstat(handle.fileno())) != _identity(expected):
            handle.close()
            raise ValueError(error_message)
        artifact = _PinnedArtifact(
            path,
            handle,
            _ObjectIdentity(info.device, info.inode),
        )
        artifact.verify()
        _verify_named_artifact(artifact)
        return artifact
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if raw_handle >= 0:
            _close_windows_handle(raw_handle)
        raise


def _read_json_artifact(artifact: _PinnedArtifact, error_message: str) -> object:
    artifact.verify()
    artifact.handle.seek(0)
    try:
        value = json.loads(artifact.handle.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(error_message) from error
    finally:
        artifact.handle.seek(0)
    artifact.verify()
    return value


def _validate_artifact_pair(
    archive: _PinnedArtifact,
    manifest: _PinnedArtifact,
) -> None:
    archive.verify()
    manifest.verify()
    archive.handle.seek(0)
    archive_stat = os.fstat(archive.handle.fileno())
    archive_sha256 = _sha256_handle(archive.handle)
    manifest.handle.seek(0)
    try:
        value = json.loads(manifest.handle.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("temporary manifest is invalid") from error
    finally:
        archive.handle.seek(0)
        manifest.handle.seek(0)
    if (
        not isinstance(value, dict)
        or value.get("archive") != ARCHIVE_NAME
        or type(value.get("archive_bytes")) is not int
        or value.get("archive_bytes") != archive_stat.st_size
        or not isinstance(value.get("archive_sha256"), str)
        or value.get("archive_sha256") != archive_sha256
    ):
        raise ValueError("temporary manifest does not describe the temporary archive")
    archive.verify()
    manifest.verify()


def _publish_pair(
    archive_temp: _PinnedArtifact,
    manifest_temp: _PinnedArtifact,
    output_dir: Path,
) -> None:
    had_old_pair = _validate_public_pair(output_dir)
    transaction = _Transaction(
        transaction_id=secrets.token_hex(16),
        had_old_pair=had_old_pair,
        archive_temp_name=archive_temp.path.name,
        manifest_temp_name=manifest_temp.path.name,
    )
    journal: _PinnedArtifact | None = None
    try:
        journal = _write_transaction_journal(output_dir, transaction)
        _inject_fault("journal_durable")
        archive_path = output_dir / ARCHIVE_NAME
        manifest_path = output_dir / MANIFEST_NAME
        archive_backup = output_dir / transaction.archive_backup_name
        manifest_backup = output_dir / transaction.manifest_backup_name
        if had_old_pair:
            _move_write_through(archive_path, archive_backup)
            _inject_fault("old_archive_moved")
            _move_write_through(manifest_path, manifest_backup)
            _inject_fault("old_manifest_moved")
        archive_temp.rename(archive_path)
        _inject_fault("new_archive_published")
        manifest_temp.rename(manifest_path)
        _inject_fault("new_manifest_published")
        _validate_artifact_pair(archive_temp, manifest_temp)
        _inject_fault("before_journal_commit")
        journal.rename(output_dir / transaction.retired_journal_name)
        _inject_fault("after_journal_commit")
    finally:
        if journal is not None:
            journal.close()
    _cleanup_committed_transaction(
        output_dir,
        transaction,
        validate_public=False,
    )


def _write_transaction_journal(
    output_dir: Path,
    transaction: _Transaction,
) -> _PinnedArtifact:
    journal_path = output_dir / JOURNAL_NAME
    _require_missing(journal_path)
    temporary = _temp_file(output_dir)
    try:
        payload = {
            "archive_temp": transaction.archive_temp_name,
            "had_old_pair": transaction.had_old_pair,
            "manifest_temp": transaction.manifest_temp_name,
            "transaction_id": transaction.transaction_id,
            "version": 1,
        }
        temporary.handle.write(
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        temporary.seal()
        temporary.rename(journal_path)
        return temporary
    except BaseException:
        temporary.close()
        if _valid_temp_name(temporary.path.name):
            _remove_temp(temporary.path)
        raise


def _recover_interrupted_transaction(output_dir: Path) -> None:
    journal_path = output_dir / JOURNAL_NAME
    if not _regular_file_exists(journal_path):
        return
    journal = _open_existing_artifact(journal_path, "transaction journal is invalid")
    committed = False
    transaction: _Transaction | None = None
    try:
        transaction = _transaction_from_value(
            _read_json_artifact(journal, "transaction journal is invalid")
        )
        archive_path = output_dir / ARCHIVE_NAME
        manifest_path = output_dir / MANIFEST_NAME
        archive_backup = output_dir / transaction.archive_backup_name
        manifest_backup = output_dir / transaction.manifest_backup_name
        if transaction.had_old_pair:
            _restore_old_file(archive_path, archive_backup)
            _restore_old_file(manifest_path, manifest_backup)
            _validate_public_pair(output_dir, journal_must_be_absent=False)
        else:
            _remove_regular_if_exists(archive_path)
            _remove_regular_if_exists(manifest_path)
            if _regular_file_exists(archive_path) or _regular_file_exists(manifest_path):
                raise ValueError("interrupted first publication could not be removed")
        _inject_fault("before_journal_commit")
        journal.rename(output_dir / transaction.retired_journal_name)
        committed = True
        _inject_fault("after_journal_commit")
    finally:
        journal.close()
    if committed and transaction is not None:
        _cleanup_committed_transaction(
            output_dir,
            transaction,
            validate_public=True,
        )


def _restore_old_file(public_path: Path, backup_path: Path) -> None:
    if _regular_file_exists(backup_path):
        _remove_regular_if_exists(public_path)
        _move_write_through(backup_path, public_path)
        return
    if not _regular_file_exists(public_path):
        raise ValueError(f"interrupted transaction lost prior file: {public_path.name}")


def _transaction_from_value(value: object) -> _Transaction:
    if not isinstance(value, dict):
        raise ValueError("transaction journal is invalid")
    transaction_id = value.get("transaction_id")
    had_old_pair = value.get("had_old_pair")
    archive_temp = value.get("archive_temp")
    manifest_temp = value.get("manifest_temp")
    if (
        value.get("version") != 1
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or type(had_old_pair) is not bool
        or not _valid_temp_name(archive_temp)
        or not _valid_temp_name(manifest_temp)
    ):
        raise ValueError("transaction journal is invalid")
    return _Transaction(
        transaction_id=transaction_id,
        had_old_pair=had_old_pair,
        archive_temp_name=archive_temp,
        manifest_temp_name=manifest_temp,
    )


def _valid_temp_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and Path(value).name == value
        and value.startswith(".sales-claw-proxmox-")
        and value.endswith(".tmp")
    )


def _cleanup_committed_transactions(output_dir: Path) -> None:
    prefix = ".sales-claw-proxmox-source.DONE."
    retired: list[Path] = []
    try:
        for entry in os.scandir(output_dir):
            if entry.name.startswith(prefix):
                retired.append(Path(entry.path))
    except OSError as error:
        raise ValueError("output directory is unavailable during transaction recovery") from error
    if len(retired) > 1:
        raise ValueError("multiple committed transaction journals require operator review")
    for journal_path in retired:
        journal = _open_existing_artifact(journal_path, "committed transaction journal is invalid")
        try:
            transaction = _transaction_from_value(
                _read_json_artifact(journal, "committed transaction journal is invalid")
            )
            if journal_path.name != transaction.retired_journal_name:
                raise ValueError("committed transaction journal name is invalid")
        finally:
            journal.close()
        _cleanup_committed_transaction(
            output_dir,
            transaction,
            validate_public=True,
        )


def _cleanup_committed_transaction(
    output_dir: Path,
    transaction: _Transaction,
    *,
    validate_public: bool,
) -> None:
    if validate_public:
        _validate_public_pair(output_dir)
    for path in (
        output_dir / transaction.archive_backup_name,
        output_dir / transaction.manifest_backup_name,
        output_dir / transaction.archive_temp_name,
        output_dir / transaction.manifest_temp_name,
    ):
        _remove_regular_if_exists(path)
    _remove_regular_if_exists(output_dir / transaction.retired_journal_name)


def _validate_public_pair(
    output_dir: Path,
    *,
    journal_must_be_absent: bool = True,
) -> bool:
    journal_path = output_dir / JOURNAL_NAME
    if journal_must_be_absent and _regular_file_exists(journal_path):
        raise ValueError("transaction journal must be recovered before using public artifacts")
    archive_path = output_dir / ARCHIVE_NAME
    manifest_path = output_dir / MANIFEST_NAME
    archive_exists = _regular_file_exists(archive_path)
    manifest_exists = _regular_file_exists(manifest_path)
    if archive_exists != manifest_exists:
        raise ValueError("archive and manifest must exist as one journal-free pair")
    if not archive_exists:
        return False
    manifest = _read_json_file(manifest_path, "published manifest is invalid")
    if not isinstance(manifest, dict):
        raise ValueError("published manifest is invalid")
    with _open_regular_file(
        archive_path,
        expected=None,
        error_message="published archive must be a non-reparse regular file",
    ) as archive_handle:
        archive_stat = os.fstat(archive_handle.fileno())
        archive_sha256 = _sha256_handle(archive_handle)
    if (
        manifest.get("archive") != ARCHIVE_NAME
        or type(manifest.get("archive_bytes")) is not int
        or manifest.get("archive_bytes") != archive_stat.st_size
        or not isinstance(manifest.get("archive_sha256"), str)
        or manifest.get("archive_sha256") != archive_sha256
    ):
        raise ValueError("published manifest does not describe the published archive")
    return True


def _read_json_file(path: Path, error_message: str) -> object:
    try:
        expected_stat = path.lstat()
    except OSError as error:
        raise ValueError(error_message) from error
    if _stat_is_reparse(expected_stat) or not stat.S_ISREG(expected_stat.st_mode):
        raise ValueError(error_message)
    with _open_regular_file(
        path,
        expected=_identity(expected_stat),
        error_message=error_message,
    ) as handle:
        try:
            return json.loads(handle.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(error_message) from error


def _regular_file_exists(path: Path) -> bool:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ValueError(f"output file is unavailable: {path.name}") from error
    if _stat_is_reparse(entry) or not stat.S_ISREG(entry.st_mode):
        raise ValueError(
            f"output target must be a non-reparse regular file; symlinks are rejected: {path.name}"
        )
    with _open_regular_file(
        path,
        expected=_identity(entry),
        error_message=f"output file changed or is a reparse point: {path.name}",
    ):
        pass
    return True


def _require_missing(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise ValueError(f"transaction path already exists: {path.name}")


def _move_write_through(source: Path, destination: Path) -> None:
    if not _MOVE_FILE_EX(
        _windows_api_path(source),
        _windows_api_path(destination),
        _MOVEFILE_WRITE_THROUGH,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _remove_regular_if_exists(path: Path) -> None:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return
    if _stat_is_reparse(entry) or not stat.S_ISREG(entry.st_mode):
        raise ValueError(f"refusing to remove non-regular transaction path: {path.name}")
    path.unlink()


def _remove_temp(path: Path | None) -> None:
    if path is None:
        return
    try:
        _remove_regular_if_exists(path)
    except (OSError, ValueError):
        pass


class _HashingReader:
    def __init__(self, handle: BinaryIO, digest: _Digest) -> None:
        self._handle = handle
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        self._digest.update(chunk)
        return chunk


def _inject_fault(point: str, path: Path | None = None) -> None:
    """Test seam for race attempts and crash-boundary fault injection."""


def _read_published_manifest(manifest_path: Path) -> dict[str, object]:
    output_chain = _PinnedChain.open(
        manifest_path.parent,
        create=False,
        label="output_dir",
    )
    try:
        value = _read_json_file(manifest_path, "published manifest is invalid")
        if not isinstance(value, dict):
            raise ValueError("published manifest is invalid")
        return value
    finally:
        output_chain.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a safe Sales-Claw Proxmox source package."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    archive_path, manifest_path = build_package(arguments.source, arguments.output)
    manifest = _read_published_manifest(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("published manifest is invalid")
    print(
        json.dumps(
            {
                "archive": str(archive_path),
                "archive_bytes": manifest["archive_bytes"],
                "archive_sha256": manifest["archive_sha256"],
                "file_count": len(files),
                "manifest": str(manifest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
