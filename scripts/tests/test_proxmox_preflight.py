from __future__ import annotations

from collections.abc import Callable
import json
from types import SimpleNamespace

import pytest

import scripts.proxmox_preflight as preflight
from scripts.proxmox_preflight import PreflightError, evaluate


Probe = Callable[[str], str]

EXPECTED_COMMANDS = [
    "docker version --format '{{.Server.Version}}'",
    "docker compose version --short",
    "df -Pk / | awk 'NR==2 {print $4}'",
    "command -v tailscale >/dev/null && tailscale ip -4",
    "ss -H -ltn 'sport = :8791'",
    "test ! -e /home/debian/sales-claw && test ! -L /home/debian/sales-claw && echo absent",
    "docker ps -a --format '{{.Names}}'",
    "docker volume ls --format '{{.Name}}'",
]

TARGET_CONTAINERS = (
    "sales-claw",
    "sales-mcp",
    "sales-ui",
    "sales-inbox",
    "sales-dispatch",
    "sales-mail",
    "sales-linkedin",
    "sales-auto",
    "openwa",
)
TARGET_VOLUMES = ("sales-claw-state", "sales-claw-keys", "openwa-data")


def healthy_answers(*, ui_port: int = 8791) -> dict[str, str]:
    return {
        "docker version --format '{{.Server.Version}}'": "29.6.1\n",
        "docker compose version --short": "5.3.1\n",
        "df -Pk / | awk 'NR==2 {print $4}'": "20971520\n",
        "command -v tailscale >/dev/null && tailscale ip -4": "100.64.0.10\n",
        f"ss -H -ltn 'sport = :{ui_port}'": "",
        "test ! -e /home/debian/sales-claw && test ! -L /home/debian/sales-claw && echo absent": "absent\n",
        "docker ps -a --format '{{.Names}}'": "foreign-service\n",
        "docker volume ls --format '{{.Name}}'": "foreign-volume\n",
    }


def probe_from(answers: dict[str, str]) -> Probe:
    return answers.__getitem__


def with_answer(command: str, value: str) -> Probe:
    answers = healthy_answers()
    answers[command] = value
    return probe_from(answers)


def test_healthy_host_uses_only_exact_read_only_probes() -> None:
    seen: list[str] = []
    answers = healthy_answers()

    def record_probe(command: str) -> str:
        seen.append(command)
        return answers[command]

    report = evaluate(record_probe, min_free_gib=10, ui_port=8791)

    assert seen == EXPECTED_COMMANDS
    assert report == preflight.PreflightReport(
        docker_version="29.6.1",
        compose_version="5.3.1",
        free_gib=20.0,
        tailscale_ipv4="100.64.0.10",
        foreign_container_count=1,
        foreign_volume_count=1,
    )


def test_low_disk_space_fails_closed() -> None:
    probe = with_answer("df -Pk / | awk 'NR==2 {print $4}'", "4194304")

    with pytest.raises(PreflightError, match="10 GiB"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


@pytest.mark.parametrize(
    ("command", "label"),
    [
        ("docker version --format '{{.Server.Version}}'", "Docker"),
        ("docker compose version --short", "Docker Compose"),
    ],
)
def test_non_version_probe_text_fails_without_disclosure(command: str, label: str) -> None:
    secret = "29.6.1\nREMOTE_SECRET_SENTINEL"
    probe = with_answer(command, secret)

    with pytest.raises(PreflightError, match=label) as captured:
        evaluate(probe, min_free_gib=10, ui_port=8791)

    assert "REMOTE_SECRET_SENTINEL" not in str(captured.value)


@pytest.mark.parametrize(
    "tailscale_output",
    [
        "",
        "not-an-ip",
        "100.64.0.10\n100.64.0.11",
        "0.0.0.0",
        "127.0.0.1",
        "10.0.0.10",
        "192.168.178.65",
        "203.0.113.10",
    ],
)
def test_missing_or_invalid_tailscale_ipv4_fails_closed(tailscale_output: str) -> None:
    probe = with_answer(
        "command -v tailscale >/dev/null && tailscale ip -4",
        tailscale_output,
    )

    with pytest.raises(PreflightError, match="Tailscale IPv4"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


def test_failed_tailscale_probe_fails_closed_without_leaking_output() -> None:
    secret = "REMOTE_SECRET_SENTINEL"

    def failed_probe(command: str) -> str:
        if command == "command -v tailscale >/dev/null && tailscale ip -4":
            raise RuntimeError(secret)
        return healthy_answers()[command]

    with pytest.raises(PreflightError) as captured:
        evaluate(failed_probe, min_free_gib=10, ui_port=8791)

    assert secret not in str(captured.value)


def test_listener_on_requested_ui_port_fails_closed() -> None:
    probe = with_answer("ss -H -ltn 'sport = :8791'", "LISTEN 0 4096 *:8791 *:*")

    with pytest.raises(PreflightError, match="8791"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


def test_existing_target_path_fails_initial_cutover() -> None:
    probe = with_answer(
        "test ! -e /home/debian/sales-claw && test ! -L /home/debian/sales-claw && echo absent",
        "",
    )

    with pytest.raises(PreflightError, match="target path"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


@pytest.mark.parametrize("container_name", TARGET_CONTAINERS)
def test_exact_target_container_collision_fails_closed(container_name: str) -> None:
    probe = with_answer("docker ps -a --format '{{.Names}}'", f"foreign\n{container_name}\n")

    with pytest.raises(PreflightError, match="container collision"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


@pytest.mark.parametrize("volume_name", TARGET_VOLUMES)
def test_exact_target_volume_collision_fails_closed(volume_name: str) -> None:
    probe = with_answer("docker volume ls --format '{{.Name}}'", f"foreign\n{volume_name}\n")

    with pytest.raises(PreflightError, match="volume collision"):
        evaluate(probe, min_free_gib=10, ui_port=8791)


def test_unrelated_resources_are_counted_without_disclosing_names() -> None:
    secret_container = "customer-secret-container"
    secret_volume = "customer-secret-volume"
    answers = healthy_answers()
    answers["docker ps -a --format '{{.Names}}'"] = f"{secret_container}\nforeign-two\n"
    answers["docker volume ls --format '{{.Name}}'"] = f"{secret_volume}\nforeign-two\n"

    report = evaluate(probe_from(answers), min_free_gib=10, ui_port=8791)

    assert report.foreign_container_count == 2
    assert report.foreign_volume_count == 2
    assert secret_container not in repr(report)
    assert secret_volume not in repr(report)


def test_cli_uses_ssh_argument_array_without_shell_and_emits_metadata_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = healthy_answers()
    answers["docker ps -a --format '{{.Names}}'"] = "SECRET_CONTAINER_NAME\n"
    answers["docker volume ls --format '{{.Name}}'"] = "SECRET_VOLUME_NAME\n"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout=answers[arguments[2]], stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    result = preflight.main(["--host", "offload-vm", "--min-free-gib", "10", "--ui-port", "8791"])

    output = capsys.readouterr().out
    assert result == 0
    assert [arguments for arguments, _ in calls] == [
        ["ssh", "offload-vm", command] for command in EXPECTED_COMMANDS
    ]
    assert all(
        kwargs == {"capture_output": True, "text": True, "check": False, "shell": False}
        for _, kwargs in calls
    )
    assert set(json.loads(output)) == {
        "compose_version",
        "docker_version",
        "foreign_container_count",
        "foreign_volume_count",
        "free_gib",
        "tailscale_ipv4",
        "ui_port_status",
    }
    assert "SECRET_CONTAINER_NAME" not in output
    assert "SECRET_VOLUME_NAME" not in output


@pytest.mark.parametrize("invalid_host", ["offload vm", "offload-vm;whoami", "user@offload-vm", ""])
def test_cli_rejects_non_token_host_before_ssh(
    invalid_host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid host must not invoke subprocess")

    monkeypatch.setattr(preflight.subprocess, "run", forbid_run)

    with pytest.raises(SystemExit) as captured:
        preflight.main(["--host", invalid_host, "--min-free-gib", "10", "--ui-port", "8791"])

    assert captured.value.code == 2


def test_ssh_failure_does_not_echo_remote_stdout_or_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_run(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=255,
            stdout="REMOTE_STDOUT_SECRET",
            stderr="REMOTE_STDERR_SECRET",
        )

    monkeypatch.setattr(preflight.subprocess, "run", failed_run)
    runner = preflight.ssh_runner("offload-vm")

    with pytest.raises(PreflightError) as captured:
        runner(EXPECTED_COMMANDS[0])

    message = str(captured.value)
    assert "REMOTE_STDOUT_SECRET" not in message
    assert "REMOTE_STDERR_SECRET" not in message
