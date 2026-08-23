from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.openwa.yml",
    ROOT / "docker-compose.proxmox.yml",
)
RUNBOOK = ROOT / "docs" / "07_PROXMOX_PILOT.md"


def rendered_config() -> dict[str, object]:
    env = os.environ.copy()
    env.update(
        {
            "SALES_DB_URL": "postgresql://pilot:pilot@db.invalid:5432/pilot",
            "OPENROUTER_API_KEY": "test-only",
            "OPENWA_API_KEY": "test-only",
            "OPENWA_SESSION_ID": "00000000-0000-0000-0000-000000000000",
            "INBOX_WEBHOOK_SECRET": "test-only",
            "LINKEDIN_ACCESS_TOKEN": "test-only",
            "LINKEDIN_PERSON_URN": "urn:li:person:test-only",
            "LINKEDIN_API_VERSION": "202608",
            "UI_TAILSCALE_IP": "100.64.0.10",
        }
    )
    command = ["docker", "compose", "--env-file", str(ROOT / ".env.example")]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", str(compose_file)))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, "Compose-Konfiguration ist ungueltig"
    return json.loads(completed.stdout)


def test_restart_matrix_is_fail_closed() -> None:
    services = rendered_config()["services"]
    automatic = {
        "openwa",
        "sales-mcp",
        "sales-ui",
        "sales-inbox",
        "sales-dispatch",
        "sales-mail",
        "sales-linkedin",
    }
    assert all(services[name]["restart"] == "unless-stopped" for name in automatic)
    assert services["sales-claw"]["restart"] == "no"
    assert services["sales-auto"]["restart"] == "no"
    assert services["openwa"]["environment"]["AUTO_START_SESSIONS"] == "true"


def test_ui_has_only_loopback_and_tailscale_bindings() -> None:
    ports = rendered_config()["services"]["sales-ui"]["ports"]
    host_ips = {port["host_ip"] for port in ports}
    assert host_ips == {"127.0.0.1", "100.64.0.10"}
    assert all(port["published"] == "8791" for port in ports)


def test_runbook_contains_all_safety_gates() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    required = (
        "python scripts/proxmox_preflight.py --host offload-vm --min-free-gib 10 --ui-port 8791",
        "scripts/backup-state.ps1",
        "scripts/backup-openwa.ps1",
        "chmod 600 .env",
        "docker-compose.proxmox.yml",
        "openwa sales-mcp sales-inbox sales-ui",
        "sales-dispatch",
        "sales-mail",
        "sales-linkedin",
        "sales-claw und sales-auto bleiben gestoppt",
    )
    assert all(fragment in text for fragment in required)
    assert "docker compose up -d" not in text


def test_runbook_requires_queue_inventory_before_each_dispatcher() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert text.count("approved-Queue nur als Anzahl") >= 3
    assert "LinkedIn-Aktions-Gate" in text
    assert "kein erneuter Versand" in text
