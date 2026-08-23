from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

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


PHASE_HEADING = re.compile(
    r"^## (?P<number>[0-9]+)\. (?P<title>[^\r\n]+)$", re.MULTILINE
)
EXPECTED_PHASES = (
    "Preflight (read-only)",
    "Lokale Backups",
    "Lokale Stilllegung",
    "Quellpaket",
    "Secrets-Gate",
    "Archiv-Transfer",
    "Restore",
    "Compose-Check",
    "Core-Start",
    "Dispatcher-Gates",
    "LinkedIn-Aktions-Gate",
    "Autostart-Abnahme",
    "Rollback",
)
COMPOSE_ASSIGNMENT = (
    'COMPOSE="docker compose -f docker-compose.yml '
    '-f docker-compose.openwa.yml -f docker-compose.proxmox.yml"'
)
PREFLIGHT_COMMAND = (
    "python scripts/proxmox_preflight.py --host offload-vm "
    "--min-free-gib 10 --ui-port 8791"
)
BACKUP_STATE_COMMAND = "scripts/backup-state.ps1"
BACKUP_OPENWA_COMMAND = (
    "scripts/backup-openwa.ps1 -StillgelegtLassen -Ziel $OpenwaBackup"
)
GLOBAL_OUTPUT_PROHIBITION = (
    "Nachrichtentexte und sonstige Nachrichteninhalte, E-Mail-Adressen, "
    "Telefonnummern, Tokens und Secretlaengen duerfen nie ausgegeben werden."
)
LINKEDIN_CORRELATION = (
    "Genehmigter Draft, Betreiberfreigabe, Workerstart, Beitrags-URN, "
    "DB-Status und Aktivitaetsbeleg muessen dieselbe Draft-ID referenzieren."
)
CORE_START = "$COMPOSE up -d openwa sales-mcp sales-inbox sales-ui"
DISPATCH_START = "$COMPOSE up -d sales-dispatch"
MAIL_START = "$COMPOSE up -d sales-mail"
LINKEDIN_START = "$COMPOSE up -d sales-linkedin"


def _phase_sections(text: str) -> dict[int, str]:
    headings = list(PHASE_HEADING.finditer(text))
    actual = tuple(
        (int(match.group("number")), match.group("title")) for match in headings
    )
    expected = tuple(enumerate(EXPECTED_PHASES, start=1))
    assert actual == expected
    assert text.count("**Stop-Gate:**") == len(EXPECTED_PHASES)

    sections: dict[int, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end() : end]
        assert section.count("**Stop-Gate:**") == 1
        sections[int(heading.group("number"))] = section
    return sections


def _assert_ordered(section: str, *fragments: str) -> None:
    positions = [section.find(fragment) for fragment in fragments]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(set(positions))


def _compose_starts(text: str) -> list[str]:
    return re.findall(r"^\$COMPOSE up -d[^\r\n]*$", text, flags=re.MULTILINE)


def _raw_compose_starts(text: str) -> list[str]:
    return re.findall(r"^docker compose up -d[^\r\n]*$", text, flags=re.MULTILINE)


def _assert_exact_service_starts(text: str) -> None:
    starts = _compose_starts(text)
    assert starts == [CORE_START, DISPATCH_START, MAIL_START, LINKEDIN_START]
    assert "$COMPOSE up -d" not in starts
    assert _raw_compose_starts(text) == []


def _assert_exact_command_line(section: str, command: str) -> None:
    lines = [line.strip() for line in section.splitlines()]
    assert lines.count(command) == 1


def _assert_required_commands(text: str) -> None:
    phases = _phase_sections(text)
    _assert_exact_command_line(phases[1], PREFLIGHT_COMMAND)
    _assert_exact_command_line(phases[2], BACKUP_STATE_COMMAND)
    _assert_exact_command_line(phases[2], BACKUP_OPENWA_COMMAND)


def _assert_global_output_prohibition(text: str) -> None:
    first_phase = PHASE_HEADING.search(text)
    assert first_phase is not None
    preamble = text[: first_phase.start()]
    assert preamble.count(GLOBAL_OUTPUT_PROHIBITION) == 1


def _assert_linkedin_action_contract(phase: str) -> None:
    action, marker, remainder = phase.partition(
        "Bei externer Veroeffentlichung ohne DB-Buchung"
    )
    assert marker
    _assert_ordered(
        action,
        "bereits genehmigten Draft",
        "Draft-ID",
        "Medienname",
        "explizite Betreiberfreigabe",
        LINKEDIN_START,
        "externe Beitrags-URN",
        "DB-Status " + chr(96) + "sent" + chr(96),
        "genau ein Aktivitaetsbeleg",
        LINKEDIN_CORRELATION,
    )
    assert action.count(LINKEDIN_CORRELATION) == 1

    failure = (marker + remainder).partition("**Stop-Gate:**")[0]
    _assert_ordered(
        failure,
        "Bei externer Veroeffentlichung ohne DB-Buchung",
        "Worker sofort stoppen",
        "**kein erneuter Versand**",
        "kein Retry",
    )


def _assert_count_before_start(
    section: str, channel: str, queue_label: str, start_command: str
) -> None:
    _assert_ordered(
        section,
        f"channel = '{channel}';",
        queue_label,
        start_command,
    )


def _move_fragment_before(text: str, fragment: str, anchor: str) -> str:
    assert text.count(fragment) == 1
    assert text.count(anchor) == 1
    without_fragment = text.replace(fragment, "", 1)
    return without_fragment.replace(anchor, f"{fragment}\n{anchor}", 1)


def test_runbook_has_exactly_thirteen_ordered_phases_with_stop_gates() -> None:
    _phase_sections(RUNBOOK.read_text(encoding="utf-8"))


def test_runbook_uses_exact_preflight_and_backup_commands() -> None:
    _assert_required_commands(RUNBOOK.read_text(encoding="utf-8"))


def test_runbook_globally_forbids_sensitive_output() -> None:
    _assert_global_output_prohibition(RUNBOOK.read_text(encoding="utf-8"))


def test_runbook_compose_commands_are_exact_and_section_scoped() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    phases = _phase_sections(text)

    assert text.count(COMPOSE_ASSIGNMENT) == 1
    assert COMPOSE_ASSIGNMENT in phases[8]
    _assert_exact_service_starts(text)
    assert CORE_START in phases[9]
    assert DISPATCH_START in phases[10]
    assert MAIL_START in phases[10]
    assert LINKEDIN_START not in phases[10]
    assert LINKEDIN_START in phases[11]


def test_runbook_counts_each_queue_before_its_individual_start() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    phases = _phase_sections(text)

    _assert_count_before_start(
        phases[10],
        "whatsapp",
        "approved-Queue nur als Anzahl** (WhatsApp)",
        DISPATCH_START,
    )
    _assert_count_before_start(
        phases[10],
        "email",
        "approved-Queue nur als Anzahl** (E-Mail)",
        MAIL_START,
    )
    _assert_ordered(
        phases[10],
        "channel = 'linkedin';",
        "approved-Queue nur als Anzahl** (LinkedIn)",
        "Der Start bleibt bis zum LinkedIn-Aktions-Gate in Phase 11 gesperrt",
    )
    assert LINKEDIN_START not in phases[10]
    assert LINKEDIN_START in phases[11]


def test_runbook_secret_gate_is_reconfirmed_separate_and_metadata_only() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[5]

    _assert_ordered(
        phase,
        "**frische** Betreiberbestaetigung",
        "separat per SCP",
        "chmod 600 .env",
        "test -s .env",
        "stat -c '%a %n' .env",
        "prueft nur Existenz/Nichtleerheit und Dateimodus",
    )
    assert "keinen Inhalt, Token oder Secretlaenge" in phase


def test_runbook_linkedin_action_and_failure_gates_are_ordered() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[11]
    _assert_linkedin_action_contract(phase)


def test_runbook_keeps_manual_services_stopped_and_openwa_exclusive() -> None:
    phases = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))

    assert "sales-claw und sales-auto bleiben gestoppt" in phases[12]
    _assert_ordered(
        phases[13],
        "alle VM-Projektcontainer vollstaendig stoppen",
        "deren Stillstand per Namensliste nachweisen",
        "Erst danach darf Windows/OpenWA wieder gestartet werden",
        "Niemals beide OpenWA-Instanzen parallel",
    )
    assert "VM-OpenWA noch aktiv, darf Windows/OpenWA nicht starten" in phases[13]


@pytest.mark.parametrize(
    ("required", "replacement"),
    (
        (PREFLIGHT_COMMAND, ""),
        (BACKUP_STATE_COMMAND, "scripts/backup-state.ps1 -OhneStopp"),
        (
            BACKUP_OPENWA_COMMAND,
            "scripts/backup-openwa.ps1 -Ziel $OpenwaBackup",
        ),
    ),
)
def test_runbook_rejects_required_command_mutations(
    required: str, replacement: str
) -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _assert_required_commands(text)
    assert text.count(required) == 1

    mutated = text.replace(required, replacement, 1)
    with pytest.raises(AssertionError):
        _assert_required_commands(mutated)


def test_runbook_rejects_raw_docker_compose_start_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _assert_exact_service_starts(text)

    mutated = text.replace(
        CORE_START,
        CORE_START + "\ndocker compose up -d sales-ui",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_exact_service_starts(mutated)


def test_runbook_rejects_extra_global_stop_gate_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _phase_sections(text)

    mutated = text.replace(
        "## 1. Preflight (read-only)",
        "**Stop-Gate:** Ungebundenes Gate.\n\n## 1. Preflight (read-only)",
        1,
    )
    with pytest.raises(AssertionError):
        _phase_sections(mutated)


def test_runbook_rejects_weakened_output_prohibition_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _assert_global_output_prohibition(text)

    weakened = GLOBAL_OUTPUT_PROHIBITION.replace("nie ausgegeben", "ausgegeben")
    mutated = text.replace(GLOBAL_OUTPUT_PROHIBITION, weakened, 1)
    with pytest.raises(AssertionError):
        _assert_global_output_prohibition(mutated)


def test_runbook_rejects_wrong_draft_id_correlation_mutation() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[11]
    _assert_linkedin_action_contract(phase)

    wrong_id = LINKEDIN_CORRELATION.replace("dieselbe", "eine andere")
    mutated = phase.replace(LINKEDIN_CORRELATION, wrong_id, 1)
    with pytest.raises(AssertionError):
        _assert_linkedin_action_contract(mutated)


def test_runbook_rejects_count_after_dispatch_start_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    phase = _phase_sections(text)[10]
    _assert_count_before_start(
        phase,
        "email",
        "approved-Queue nur als Anzahl** (E-Mail)",
        MAIL_START,
    )

    mutated = _move_fragment_before(text, MAIL_START, "channel = 'email';")
    with pytest.raises(AssertionError):
        _assert_count_before_start(
            _phase_sections(mutated)[10],
            "email",
            "approved-Queue nur als Anzahl** (E-Mail)",
            MAIL_START,
        )


def test_runbook_rejects_bare_compose_start_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _assert_exact_service_starts(text)

    mutated = text.replace(MAIL_START, "$COMPOSE up -d", 1)
    with pytest.raises(AssertionError):
        _assert_exact_service_starts(mutated)
