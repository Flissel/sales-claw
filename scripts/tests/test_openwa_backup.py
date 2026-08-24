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
BACKUP_SCRIPT = Path(__file__).resolve().parents[1] / "backup-openwa.ps1"
BACKUP_STATE_SCRIPT = Path(__file__).resolve().parents[1] / "backup-state.ps1"


class FakeDocker:
    def __init__(self, log_path: Path, state_path: Path) -> None:
        self.log_path = log_path
        self.state_path = state_path

    def reset(
        self,
        *,
        running: bool,
        fail_verify: bool = False,
        state_stop_exit_code: int = 0,
    ) -> None:
        self.log_path.write_text("", encoding="utf-8")
        self.state_path.write_text(
            json.dumps(
                {
                    "running": running,
                    "stopped_by_backup": False,
                    "fail_verify": fail_verify,
                    "state_stop_exit_code": state_stop_exit_code,
                }
            ),
            encoding="utf-8",
        )

    def transcript(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]

    def state(self) -> dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))


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
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    docker_bin = tmp_path / "docker-bin"
    docker_bin.mkdir()
    log_path = tmp_path / "docker-transcript.jsonl"
    state_path = tmp_path / "docker-state.json"
    fake_script = docker_bin / "docker_fake.py"
    fake_script.write_text(
        """\
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path


args = sys.argv[1:]
log_path = Path(os.environ["FAKE_DOCKER_LOG"])
state_path = Path(os.environ["FAKE_DOCKER_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))


def record(event, **details):
    entry = {"event": event, "argv": args, **details}
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\\n")


def save_state():
    state_path.write_text(json.dumps(state), encoding="utf-8")


def reject():
    record("unexpected")
    print("unexpected docker invocation", file=sys.stderr)
    raise SystemExit(90)


if args == ["version", "--format", "{{.Server.Version}}"]:
    record("version")
    print("27.0.0")
    raise SystemExit(0)

if args == ["volume", "inspect", "--format", "{{.Name}}", "openwa-data"]:
    record("volume_inspect", volume="openwa-data")
    print("openwa-data")
    raise SystemExit(0)

if args == [
    "container",
    "ls",
    "--all",
    "--filter",
    "name=^openwa$",
    "--format",
    "{{.Names}}",
]:
    record("container_ls", container="openwa")
    print("openwa")
    raise SystemExit(0)

if args == ["inspect", "--format", "{{.State.Running}}", "openwa"]:
    record("inspect_running", container="openwa", running=state["running"])
    print(str(state["running"]).lower())
    raise SystemExit(0)

if args == ["stop", "--time", "30", "openwa"]:
    if not state["running"]:
        reject()
    state["running"] = False
    state["stopped_by_backup"] = True
    save_state()
    record("stop", container="openwa")
    print("openwa")
    raise SystemExit(0)

if args == ["inspect", "--format", "{{.State.ExitCode}}", "openwa"]:
    if not state["stopped_by_backup"]:
        reject()
    record("inspect_exit_code", container="openwa")
    print("0")
    raise SystemExit(0)

if args == ["start", "openwa"]:
    state["running"] = True
    state["stopped_by_backup"] = False
    save_state()
    record("start", container="openwa")
    print("openwa")
    raise SystemExit(0)

if args == ["ps", "--filter", "name=^sales-claw$", "--format", "{{.Names}}"]:
    record("state_container_ps", container="sales-claw")
    print("sales-claw")
    raise SystemExit(0)

if args == ["exec", "sales-claw", "openclaw", "backup", "create"]:
    record("state_semantic_backup", container="sales-claw")
    print("semantic backup fixture")
    raise SystemExit(0)

if args == ["stop", "-t", "30", "sales-claw"]:
    record("state_stop", container="sales-claw")
    raise SystemExit(0)

if args == ["inspect", "--format", "{{.State.ExitCode}}", "sales-claw"]:
    record("state_inspect_exit", container="sales-claw")
    print(state["state_stop_exit_code"])
    raise SystemExit(0)

if args == ["start", "sales-claw"]:
    record("state_start", container="sales-claw")
    raise SystemExit(0)

if args == ["inspect", "--format", "{{.State.Status}}", "sales-claw"]:
    record("state_inspect_status", container="sales-claw")
    print("running")
    raise SystemExit(0)

archive_prefix = [
    "run",
    "--rm",
    "--mount",
    "type=volume,source=openwa-data,target=/quelle,readonly",
    "--mount",
]
archive_suffix = [
    "alpine:3.20",
    "tar",
    "-cf",
    "/ziel/openwa.tar",
    "-C",
    "/quelle",
    ".",
]
if len(args) == 13 and args[:5] == archive_prefix and args[6:] == archive_suffix:
    bind = re.fullmatch(r"type=bind,source=(.*),target=/ziel", args[5])
    if bind is None:
        reject()
    target = Path(bind.group(1))
    if not target.is_absolute() or not target.is_dir():
        reject()
    payload = b"temporary openwa backup fixture\\n"
    with tarfile.open(target / "openwa.tar", "w") as archive:
        entry = tarfile.TarInfo("session.json")
        entry.size = len(payload)
        entry.mode = 0o600
        archive.addfile(entry, io.BytesIO(payload))
    record(
        "archive",
        volume="openwa-data",
        source_readonly=True,
        target=str(target),
        manifest_present=(target / "MANIFEST.json").exists(),
    )
    raise SystemExit(0)

expected_verify_script = '''
set -eu
mkdir -p /probe
tar -xf /quelle/openwa.tar -C /probe
anzahl="$(find /probe -type f | wc -l)"
printf 'OPENWA_ENTRIES=%s\\\\n' "$anzahl"
'''.strip()
verify_prefix = ["run", "--rm", "--mount"]
verify_suffix = ["alpine:3.20", "sh", "-c"]
if len(args) == 8 and args[:3] == verify_prefix and args[4:7] == verify_suffix:
    bind = re.fullmatch(
        r"type=bind,source=(.*),target=/quelle,readonly", args[3]
    )
    command = args[7].replace("\\r\\n", "\\n").strip()
    if bind is None or command != expected_verify_script:
        reject()
    source = Path(bind.group(1))
    if not source.is_absolute() or not source.is_dir():
        reject()
    manifest_present = (source / "MANIFEST.json").exists()
    record(
        "verify",
        image="alpine:3.20",
        source=str(source),
        source_readonly=True,
        manifest_present=manifest_present,
        exact_tar_command=True,
    )
    if state["fail_verify"] and manifest_present:
        raise SystemExit(72)
    try:
        with tarfile.open(source / "openwa.tar", "r") as archive:
            entries = sum(member.isfile() for member in archive.getmembers())
    except (OSError, tarfile.TarError):
        raise SystemExit(66)
    print(f"OPENWA_ENTRIES={entries}")
    raise SystemExit(0)

reject()
""",
        encoding="utf-8",
    )
    launcher = docker_bin / "docker.ps1"
    powershell_python = sys.executable.replace("'", "''")
    launcher.write_text(
        (
            f"$python = '{powershell_python}'\n"
            "& $python (Join-Path $PSScriptRoot 'docker_fake.py') @args\n"
            "exit $LASTEXITCODE\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", f"{docker_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log_path))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state_path))
    harness = FakeDocker(log_path=log_path, state_path=state_path)
    harness.reset(running=False)
    return harness


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


def _run_backup(
    target: Path, *, leave_stopped: bool = False
) -> subprocess.CompletedProcess[str]:
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(BACKUP_SCRIPT),
        "-Ziel",
        str(target.resolve()),
    ]
    if leave_stopped:
        command.append("-StillgelegtLassen")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_state_backup(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(BACKUP_STATE_SCRIPT),
            "-Ziel",
            str(target.resolve()),
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


def test_valid_backup_is_verified_with_exact_read_only_alpine_command(
    backup_dir: Path, fake_docker: FakeDocker
) -> None:
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
    transcript = fake_docker.transcript()
    assert [entry["event"] for entry in transcript] == ["verify"]
    assert transcript[0]["image"] == "alpine:3.20"
    assert transcript[0]["source_readonly"] is True
    assert transcript[0]["exact_tar_command"] is True


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


def _event_names(fake_docker: FakeDocker) -> list[object]:
    return [entry["event"] for entry in fake_docker.transcript()]


def _assert_exact_names(fake_docker: FakeDocker) -> None:
    transcript = fake_docker.transcript()
    assert {
        entry["volume"] for entry in transcript if "volume" in entry
    } == {"openwa-data"}
    assert {
        entry["container"] for entry in transcript if "container" in entry
    } == {"openwa"}


def test_backup_restarts_initially_running_openwa_after_verified_success(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    fake_docker.reset(running=True)
    target = tmp_path / "running-success"

    result = _run_backup(target)

    assert result.returncode == 0, result.stderr
    assert (target / "openwa.tar").is_file()
    assert (target / "MANIFEST.json").is_file()
    assert _event_names(fake_docker) == [
        "version",
        "volume_inspect",
        "container_ls",
        "inspect_running",
        "stop",
        "inspect_exit_code",
        "archive",
        "verify",
        "verify",
        "start",
        "inspect_running",
    ]
    verify_events = [
        entry for entry in fake_docker.transcript() if entry["event"] == "verify"
    ]
    assert [entry["manifest_present"] for entry in verify_events] == [False, True]
    assert fake_docker.state()["running"] is True
    _assert_exact_names(fake_docker)


def test_backup_leaves_initially_running_openwa_stopped_when_requested(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    fake_docker.reset(running=True)
    target = tmp_path / "leave-stopped"

    result = _run_backup(target, leave_stopped=True)

    assert result.returncode == 0, result.stderr
    assert (target / "MANIFEST.json").is_file()
    assert "stop" in _event_names(fake_docker)
    assert "start" not in _event_names(fake_docker)
    assert fake_docker.state()["running"] is False
    _assert_exact_names(fake_docker)


def test_backup_does_not_restart_initially_stopped_openwa(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    fake_docker.reset(running=False)
    target = tmp_path / "already-stopped"

    result = _run_backup(target)

    assert result.returncode == 0, result.stderr
    assert (target / "MANIFEST.json").is_file()
    assert "stop" not in _event_names(fake_docker)
    assert "start" not in _event_names(fake_docker)
    assert fake_docker.state()["running"] is False
    _assert_exact_names(fake_docker)


def test_backup_verification_failure_removes_manifest_and_restarts_openwa(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    fake_docker.reset(running=True, fail_verify=True)
    target = tmp_path / "verification-failure"

    result = _run_backup(target)

    assert result.returncode != 0
    assert (target / "openwa.tar").is_file()
    assert not (target / "MANIFEST.json").exists()
    assert _event_names(fake_docker) == [
        "version",
        "volume_inspect",
        "container_ls",
        "inspect_running",
        "stop",
        "inspect_exit_code",
        "archive",
        "verify",
        "verify",
        "start",
        "inspect_running",
    ]
    assert fake_docker.state()["running"] is True
    _assert_exact_names(fake_docker)


def test_state_backup_hard_stop_never_publishes_archives_or_manifest(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    fake_docker.reset(running=True, state_stop_exit_code=137)
    target = tmp_path / "state-hard-stop"

    result = _run_state_backup(target)

    assert result.returncode != 0
    transcript = fake_docker.transcript()
    assert [entry["event"] for entry in transcript] == [
        "state_container_ps",
        "state_semantic_backup",
        "state_stop",
        "state_inspect_exit",
        "state_start",
        "state_inspect_status",
    ]
    assert list(target.rglob("state.tar")) == []
    assert list(target.rglob("keys.tar")) == []
    assert list(target.rglob("MANIFEST.json")) == []
