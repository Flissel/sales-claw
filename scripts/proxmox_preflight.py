from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import ipaddress
import json
import re
import subprocess


Runner = Callable[[str], str]

_HOST_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_VERSION_PATTERN = re.compile(r"[vV]?\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.-]+)?")
_TARGET_CONTAINERS = frozenset(
    {
        "sales-claw",
        "sales-mcp",
        "sales-ui",
        "sales-inbox",
        "sales-dispatch",
        "sales-mail",
        "sales-linkedin",
        "sales-auto",
        "openwa",
    }
)
_TARGET_VOLUMES = frozenset({"sales-claw-state", "sales-claw-keys", "openwa-data"})


@dataclass(frozen=True)
class PreflightReport:
    docker_version: str
    compose_version: str
    free_gib: float
    tailscale_ipv4: str
    foreign_container_count: int
    foreign_volume_count: int


class PreflightError(RuntimeError):
    pass


def _probe(run_remote: Runner, command: str, label: str) -> str:
    try:
        output = run_remote(command)
    except PreflightError:
        raise
    except Exception:
        raise PreflightError(f"{label} probe failed") from None
    if not isinstance(output, str):
        raise PreflightError(f"{label} probe returned invalid output")
    return output.strip()


def _nonempty_probe(run_remote: Runner, command: str, label: str) -> str:
    output = _probe(run_remote, command, label)
    if not output:
        raise PreflightError(f"{label} is unavailable")
    return output


def _version_probe(run_remote: Runner, command: str, label: str) -> str:
    output = _nonempty_probe(run_remote, command, label)
    if _VERSION_PATTERN.fullmatch(output) is None:
        raise PreflightError(f"{label} version probe returned invalid output")
    return output


def _resource_names(output: str) -> set[str]:
    return {line.strip() for line in output.splitlines() if line.strip()}


def evaluate(run_remote: Runner, *, min_free_gib: int, ui_port: int) -> PreflightReport:
    """Evaluate exact read-only probes and raise on the first unsafe gate."""
    if isinstance(min_free_gib, bool) or not isinstance(min_free_gib, int) or min_free_gib < 0:
        raise PreflightError("minimum free storage must be a non-negative integer")
    if isinstance(ui_port, bool) or not isinstance(ui_port, int) or not 1 <= ui_port <= 65535:
        raise PreflightError("UI port must be between 1 and 65535")

    docker_version = _version_probe(
        run_remote,
        "docker version --format '{{.Server.Version}}'",
        "Docker",
    )
    compose_version = _version_probe(
        run_remote,
        "docker compose version --short",
        "Docker Compose",
    )

    free_kib_output = _probe(
        run_remote,
        "df -Pk / | awk 'NR==2 {print $4}'",
        "free storage",
    )
    try:
        free_kib = int(free_kib_output)
    except ValueError:
        raise PreflightError("free storage probe returned invalid output") from None
    if free_kib < 0:
        raise PreflightError("free storage probe returned invalid output")
    free_gib = free_kib / (1024 * 1024)
    if free_gib < min_free_gib:
        raise PreflightError(f"at least {min_free_gib} GiB free storage is required")

    tailscale_output = _probe(
        run_remote,
        "command -v tailscale >/dev/null && tailscale ip -4",
        "Tailscale IPv4",
    )
    tailscale_addresses = [line.strip() for line in tailscale_output.splitlines() if line.strip()]
    if len(tailscale_addresses) != 1:
        raise PreflightError("exactly one Tailscale IPv4 address is required")
    tailscale_ipv4 = tailscale_addresses[0]
    try:
        parsed_address = ipaddress.ip_address(tailscale_ipv4)
    except ValueError:
        raise PreflightError("Tailscale IPv4 probe returned invalid output") from None
    if parsed_address.version != 4:
        raise PreflightError("Tailscale IPv4 probe returned invalid output")

    port_output = _probe(
        run_remote,
        f"ss -H -ltn 'sport = :{ui_port}'",
        "UI port",
    )
    if port_output:
        raise PreflightError(f"UI port {ui_port} already has a listener")

    target_path_status = _probe(
        run_remote,
        "test ! -e /home/debian/sales-claw && echo absent",
        "target path",
    )
    if target_path_status != "absent":
        raise PreflightError("target path is not absent for initial cutover")

    container_output = _probe(
        run_remote,
        "docker ps -a --format '{{.Names}}'",
        "container inventory",
    )
    container_names = _resource_names(container_output)
    if container_names & _TARGET_CONTAINERS:
        raise PreflightError("target container collision detected")

    volume_output = _probe(
        run_remote,
        "docker volume ls --format '{{.Name}}'",
        "volume inventory",
    )
    volume_names = _resource_names(volume_output)
    if volume_names & _TARGET_VOLUMES:
        raise PreflightError("target volume collision detected")

    return PreflightReport(
        docker_version=docker_version,
        compose_version=compose_version,
        free_gib=free_gib,
        tailscale_ipv4=tailscale_ipv4,
        foreign_container_count=len(container_names),
        foreign_volume_count=len(volume_names),
    )


def _require_host_token(host: str) -> str:
    if _HOST_PATTERN.fullmatch(host) is None:
        raise argparse.ArgumentTypeError("host must be one SSH alias or hostname token")
    return host


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _ui_port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def ssh_runner(host: str) -> Runner:
    """Build a metadata-safe SSH runner using an argument array and no shell."""
    try:
        safe_host = _require_host_token(host)
    except argparse.ArgumentTypeError:
        raise PreflightError("invalid SSH host token") from None

    def run_remote(command: str) -> str:
        try:
            completed = subprocess.run(
                ["ssh", safe_host, command],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except OSError:
            raise PreflightError("SSH probe could not be started") from None
        if completed.returncode != 0:
            raise PreflightError("SSH probe failed")
        if not isinstance(completed.stdout, str):
            raise PreflightError("SSH probe returned invalid output")
        return completed.stdout

    return run_remote


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Proxmox pilot preflight")
    parser.add_argument("--host", required=True, type=_require_host_token)
    parser.add_argument("--min-free-gib", required=True, type=_nonnegative_int)
    parser.add_argument("--ui-port", required=True, type=_ui_port)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report = evaluate(
        ssh_runner(arguments.host),
        min_free_gib=arguments.min_free_gib,
        ui_port=arguments.ui_port,
    )
    print(
        json.dumps(
            {
                "docker_version": report.docker_version,
                "compose_version": report.compose_version,
                "free_gib": report.free_gib,
                "tailscale_ipv4": report.tailscale_ipv4,
                "ui_port_status": "available",
                "foreign_container_count": report.foreign_container_count,
                "foreign_volume_count": report.foreign_volume_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
