from __future__ import annotations

import json
import os
import re
import shutil
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
BINDING_GATE = ROOT / "scripts" / "check-compose-bindings.py"


def _committed_file(relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def rendered_config(tmp_path: Path) -> dict[str, object]:
    compose_root = tmp_path / "committed-compose"
    compose_root.mkdir()
    (compose_root / "docker-compose.yml").write_text(
        _committed_file("docker-compose.yml"), encoding="utf-8"
    )
    (compose_root / "docker-compose.openwa.yml").write_text(
        _committed_file("docker-compose.openwa.yml"), encoding="utf-8"
    )
    shutil.copyfile(
        ROOT / "docker-compose.proxmox.yml",
        compose_root / "docker-compose.proxmox.yml",
    )
    (compose_root / ".env.example").write_text(
        _committed_file(".env.example"), encoding="utf-8"
    )
    (compose_root / ".env").write_text("", encoding="utf-8")
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
    command = ["docker", "compose", "--env-file", str(compose_root / ".env.example")]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", str(compose_root / compose_file.name)))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        cwd=compose_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, "Compose-Konfiguration ist ungueltig"
    return json.loads(completed.stdout)


def test_clean_committed_compose_has_no_startable_linkedin_service(tmp_path: Path) -> None:
    services = rendered_config(tmp_path)["services"]
    automatic = {
        "openwa",
        "sales-mcp",
        "sales-ui",
        "sales-inbox",
        "sales-dispatch",
        "sales-mail",
        # sales-stt (01.09.2026): Dauerdienst, aber inert — das Modell
        # wird erst beim ersten Auftrag geladen.
        "sales-stt",
    }
    assert all(services[name]["restart"] == "unless-stopped" for name in automatic)
    assert services["sales-claw"]["restart"] == "no"
    assert services["sales-auto"]["restart"] == "no"
    # UMGEDREHT am 30.08.2026 auf Betreiber-Entscheid „freigabe soll gleich
    # versand machen": sales-linkedin ist ein DAUERDIENST und steht damit
    # in der Konfiguration. Das Sperrgate des Piloten (kein startbarer
    # LinkedIn-Dienst) war die Lehre aus dem Doppelpost vom 26.08.; die
    # Sorge faengt jetzt der Dienst selbst ab — hoechstens einer pro Tag,
    # nichts laenger als LINKEDIN_FRISCHE_TAGE Freigegebenes
    # (sales-mcp/tests/test_linkedin_dispatch.py).
    assert services["sales-linkedin"]["restart"] == "unless-stopped"
    assert services["openwa"]["environment"]["AUTO_START_SESSIONS"] == "true"


def test_ui_has_only_loopback_and_tailscale_bindings(tmp_path: Path) -> None:
    ports = rendered_config(tmp_path)["services"]["sales-ui"]["ports"]
    host_ips = {port["host_ip"] for port in ports}
    assert host_ips == {"127.0.0.1", "100.64.0.10"}
    assert all(port["published"] == "8791" for port in ports)


def test_ui_receives_the_session_secret_wiring(tmp_path: Path) -> None:
    """E1 (31.08.2026): sales-ui hat KEIN env_file (T5a) — ohne diese
    ausdrueckliche Leitung kaeme ein in die .env geschriebenes
    UI_SESSION_SECRET nie im Container an, und benutzer-anlegen.sh
    schaltete die Anmeldung nur scheinbar scharf."""
    umgebung = rendered_config(tmp_path)["services"]["sales-ui"]["environment"]
    assert "UI_SESSION_SECRET" in umgebung


def test_ui_extra_hosts_traegt_ip_und_serve_namen(tmp_path: Path) -> None:
    """F4 (31.08.2026): hinter `tailscale serve` kommt der ts.net-Name als
    Host-Header an — ohne diese Leitung antwortet die HTTPS-Adresse 421
    (gemessen). Die IP bleibt fuer den direkten Handy-Zugriff."""
    umgebung = rendered_config(tmp_path)["services"]["sales-ui"]["environment"]
    # Der Name kommt aus ${UI_SERVE_HOST:-} — hier ungesetzt, also endet
    # der Wert auf ',' (ui.py filtert leere Glieder).
    assert umgebung["UI_EXTRA_HOSTS"] == "100.64.0.10,"


def _run_binding_gate(
    config: dict[str, object], expected: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(BINDING_GATE), "--expected-tailscale", expected],
        input=json.dumps(config),
        text=True,
        capture_output=True,
        check=False,
    )


def test_binding_gate_accepts_only_loopback_plus_exact_tailscale_ip() -> None:
    config = {
        "services": {
            "sales-ui": {
                "environment": {"UI_EXTRA_HOSTS": "100.64.0.10"},
                "ports": [
                    {"host_ip": "127.0.0.1", "published": "8791", "target": 8791},
                    {"host_ip": "100.64.0.10", "published": "8791", "target": 8791},
                ],
            }
        },
        "secret_sentinel": "must-not-leak",
    }

    accepted = _run_binding_gate(config, "100.64.0.10")
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "sales-ui bindings: verified"
    assert "must-not-leak" not in accepted.stdout + accepted.stderr

    for wrong_ip in ("0.0.0.0", "192.168.178.65", "100.64.0.11"):
        mutated = json.loads(json.dumps(config))
        mutated["services"]["sales-ui"]["ports"][1]["host_ip"] = wrong_ip
        rejected = _run_binding_gate(mutated, "100.64.0.10")
        assert rejected.returncode != 0
        assert "must-not-leak" not in rejected.stdout + rejected.stderr


PHASE_HEADING = re.compile(
    r"^## (?P<number>[0-9]+)\. (?P<title>[^\r\n]+)$", re.MULTILINE
)
EXPECTED_PHASES = (
    "Preflight (read-only)",
    "Lokale Backups",
    "Lokale Stilllegung",
    "Quellpaket",
    "Quelltransfer und Projektbaum",
    "Secrets- und Archiv-Transfer",
    "Verifikation und Restore",
    "Compose-Check",
    "Core-Start",
    "Dispatcher-Gates",
    "LinkedIn-Sperrgate",
    "Autostart-Abnahme",
    "Rollback",
)
COMPOSE_ASSIGNMENT = (
    'COMPOSE="docker compose --env-file .env --env-file .env.proxmox -f docker-compose.yml '
    '-f docker-compose.openwa.yml -f docker-compose.proxmox.yml"'
)
PREFLIGHT_COMMAND = (
    "$PreflightJson = python scripts/proxmox_preflight.py --host offload-vm "
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
    return re.findall(
        r"^[ \t]*docker compose up -d(?:[ \t]+[^\r\n]*)?$",
        text,
        flags=re.MULTILINE,
    )


def _assert_exact_service_starts(text: str) -> None:
    starts = _compose_starts(text)
    assert starts == [CORE_START, DISPATCH_START, MAIL_START]
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


def _assert_linkedin_blocked_contract(phase: str) -> None:
    assert LINKEDIN_START not in phase
    _assert_ordered(
        phase,
        "sales-linkedin bleibt gestoppt",
        "exakt eine Draft-ID",
        "nicht wiederholbarer Zustand fuer unklare Veroeffentlichungsergebnisse",
        "separat implementiert und verhaltensgeprueft",
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
    assert LINKEDIN_START not in phases[11]


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
        "Der Start bleibt bis zum LinkedIn-Sperrgate in Phase 11 gesperrt",
    )
    assert LINKEDIN_START not in phases[10]
    assert LINKEDIN_START not in phases[11]


def test_runbook_secret_gate_is_reconfirmed_separate_and_metadata_only() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[6]

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


def test_runbook_linkedin_action_is_fail_closed_until_exact_id_runtime_exists() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[11]
    _assert_linkedin_blocked_contract(phase)


def test_runbook_installs_and_verifies_source_before_secret_transfer() -> None:
    phases = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))
    package_phase = phases[4]
    source_phase = phases[5]
    secret_phase = phases[6]

    _assert_ordered(
        package_phase,
        '$ReviewedSourceCommit = git rev-parse --verify "HEAD^{commit}"',
        '$ReviewedOpenwaCommit = git -C openwa/upstream rev-parse --verify "HEAD^{commit}"',
        '--nested-source "openwa/upstream=$ReviewedOpenwaCommit"',
    )
    _assert_ordered(
        source_phase,
        "mktemp -d /home/debian/.sales-claw-staging.XXXXXX",
        'git rev-parse "HEAD:$InstallerPfad"',
        "git hash-object -- $InstallerPfad",
        "Get-FileHash -Algorithm SHA256",
        "sales-claw-proxmox-source.MANIFEST.json",
        "sales-claw-proxmox-source.tar.gz",
        'sha256sum "$REMOTE_STAGE/install_proxmox_package.py"',
        "jedes Archivmitglied gegen die Dateiliste im Manifest",
        "beide vom Betreiber gelieferten Commit-Pins",
        "kein archivgelieferter Code ausgefuehrt",
        "sicher entpacken",
        "/home/debian/sales-claw",
        '--expected-commit "$EXPECTED_SOURCE_COMMIT"',
        '--expected-nested-source "openwa/upstream=$EXPECTED_OPENWA_COMMIT"',
    )
    assert "tar -xOf" not in source_phase
    assert "separat per SCP" not in source_phase
    assert "separat per SCP" in secret_phase


def test_runbook_uses_vm_local_tailscale_override_and_verifies_final_bindings() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    phases = _phase_sections(text)

    _assert_ordered(
        phases[1],
        "$Preflight = $PreflightJson | ConvertFrom-Json",
        "$VmTailscaleIp = $Preflight.tailscale_ipv4",
    )
    _assert_ordered(
        phases[6],
        "UI_TAILSCALE_IP=$VmTailscaleIp",
        ".env.proxmox",
    )
    assert "--env-file .env --env-file .env.proxmox" in COMPOSE_ASSIGNMENT
    _assert_ordered(
        phases[8],
        "$COMPOSE config --quiet",
        "$COMPOSE config --format json",
        "exakt `127.0.0.1` und `$VmTailscaleIp`",
        "Wildcard-, LAN- oder abweichende Adresse",
    )


def test_runbook_trial_verifies_all_backups_and_checks_restored_state() -> None:
    phases = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))

    assert "scripts/restore-state.ps1 -Quelle $StateBackup -NurPruefen" in phases[2]
    assert "scripts/verify-openwa-backup.ps1 -Quelle $OpenwaBackup" in phases[2]
    _assert_ordered(
        phases[7],
        "probeweise vollstaendig entpacken",
        "exakt die drei benannten Volumes",
        "python3 scripts/verify-restored-state.py",
        '--state-backup "$REMOTE_STATE_BACKUP"',
        '--openwa-backup "$REMOTE_OPENWA_BACKUP"',
        "SHA-256-Inventar aller regulaeren Dateien",
        "--network none",
        "Startpfad",
        "Exit-Code `0` erlaubt Phase 8",
    )


def test_runbook_package_gate_requires_clean_reviewed_provenance_and_excludes_media() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[4]
    _assert_ordered(
        phase,
        "getrackten",
        "`HEAD`-Inventar",
        "exakten `HEAD`-Baum",
        "dirty, untracked oder ignored Datei",
        "sauberer aeusserer Klon allein reicht",
        "absichtlich paketgeschlossen",
        "`media/` ist kein Quellpaket-Bestandteil",
        "eigene Datenfreigabe und einen getrennten Transfer",
    )


def test_runbook_uses_fresh_timestamped_package_output() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[4]
    assert 'artifacts/proxmox-$(Get-Date -Format \'yyyyMMdd-HHmmss\')' in phase
    assert '"artifacts/proxmox"' not in phase


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


def test_runbook_rejects_indented_raw_compose_start_mutation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    _assert_exact_service_starts(text)

    mutated = text.replace(
        CORE_START,
        CORE_START + "\n  docker compose up -d sales-ui",
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


def test_runbook_rejects_linkedin_start_mutation() -> None:
    phase = _phase_sections(RUNBOOK.read_text(encoding="utf-8"))[11]
    _assert_linkedin_blocked_contract(phase)

    mutated = phase + "\n" + LINKEDIN_START
    with pytest.raises(AssertionError):
        _assert_linkedin_blocked_contract(mutated)


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


def test_stt_hat_keine_geheimnisse_und_keinen_port(tmp_path: Path) -> None:
    """sales-stt (01.09.2026) bekommt Audio und gibt Text — mehr nicht.
    Kein env_file, keine Datenbank, kein Port nach draussen (dieselbe
    T5a-Haltung wie bei sales-ui, nur strenger: hier gibt es nicht einmal
    einen Viewer-Schluessel)."""
    dienst = rendered_config(tmp_path)["services"]["sales-stt"]
    umgebung = dienst.get("environment") or {}
    verboten = ("SALES_DB_URL", "OPENWA_API_KEY", "OPENWA_VIEWER_KEY",
                "INBOX_WEBHOOK_SECRET", "SMTP_PASSWORT", "APIFY_TOKEN",
                "LINKEDIN_ACCESS_TOKEN", "UI_SESSION_SECRET")
    assert not [k for k in verboten if k in umgebung]
    assert not dienst.get("ports")
    # Das Modell liegt im Volume, nicht im Image.
    ziele = [str(v.get("target")) for v in (dienst.get("volumes") or [])]
    assert "/modelle" in ziele


def test_sprachnachrichten_werden_nur_von_der_inbox_geschrieben(
        tmp_path: Path) -> None:
    """Gegenlaeufige Rechte wie bei media/reports: sales-inbox schreibt
    die Audiodateien, sales-mcp liest sie zum Transkribieren."""
    dienste = rendered_config(tmp_path)["services"]

    def bind(name):
        return next((v for v in (dienste[name].get("volumes") or [])
                     if str(v.get("target")) == "/sprachnachrichten"), None)

    inbox = bind("sales-inbox")
    mcp = bind("sales-mcp")
    assert inbox is not None and not inbox.get("read_only")
    assert mcp is not None and mcp.get("read_only") is True


def test_ui_bekommt_den_kalender_aber_keine_sendemacht(tmp_path: Path) -> None:
    """01.09.2026: der Kalender-Tab liest CalDAV — dafuer braucht sales-ui
    die Zugangsdaten. Die Ausnahme ist eng: KEIN Schluessel, der senden
    koennte (dieselbe T5a-Grenze wie beim OPENWA_VIEWER_KEY)."""
    umgebung = rendered_config(tmp_path)["services"]["sales-ui"]["environment"]
    for noetig in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT"):
        assert noetig in umgebung
    for verboten in ("OPENWA_API_KEY", "SMTP_PASSWORT", "APIFY_TOKEN",
                     "LINKEDIN_ACCESS_TOKEN", "INBOX_WEBHOOK_SECRET"):
        assert verboten not in umgebung


def test_openwa_bekommt_die_frame_ancestors_leitung(tmp_path: Path) -> None:
    """02.09.2026: das Dashboard darf nur aus derselben Origin eingebettet
    werden (frame-ancestors 'self', hart in helmet). Der lokale Patch
    0002 liest DASHBOARD_FRAME_ANCESTORS — ohne diese Leitung bliebe der
    Patch wirkungslos und der WhatsApp-Tab zeigte einen leeren Rahmen."""
    umgebung = rendered_config(tmp_path)["services"]["openwa"]["environment"]
    assert "DASHBOARD_FRAME_ANCESTORS" in umgebung


def test_openwa_vertraut_dem_serve_proxy_und_weitet_die_ratenfenster(
        tmp_path: Path) -> None:
    """02.09.2026 gemessen: hinter `tailscale serve` sieht openwa JEDEN
    Browser als das Bridge-Gateway (172.22.0.1) — Dashboard, sales-ui und
    Betriebsskripte teilten sich EIN Ratenfenster von 10/s, und das
    Dashboard blieb nach dem Login im 429 (ThrottlerException) haengen.
    Mit TRUSTED_PROXIES liest openwa X-Forwarded-For des Proxys und zaehlt
    pro Browser; die Fenster sind fuer eine Oberflaeche bemessen, die beim
    Laden einen Schwall Anfragen schickt — und bleiben ein Schutz."""
    umgebung = rendered_config(tmp_path)["services"]["openwa"]["environment"]
    assert umgebung["TRUSTED_PROXIES"] == "172.16.0.0/12"
    assert umgebung["RATE_LIMIT_SHORT_LIMIT"] == "40"
    assert umgebung["RATE_LIMIT_MEDIUM_LIMIT"] == "400"
    assert umgebung["RATE_LIMIT_LONG_LIMIT"] == "4000"


def test_media_erzeugt_schreiben_nur_mcp_und_inbox(tmp_path: Path) -> None:
    """UI-Plan 4b (02.09.2026): der erzeugte Medienordner wird von sales-mcp
    (Termine) und sales-inbox (Upload per WhatsApp an sich selbst)
    geschrieben — alle anderen lesen nur."""
    dienste = rendered_config(tmp_path)["services"]

    def bind(name):
        return next((v for v in (dienste[name].get("volumes") or [])
                     if str(v.get("target")) == "/media-erzeugt"), None)

    for schreiber in ("sales-mcp", "sales-inbox"):
        b = bind(schreiber)
        assert b is not None and not b.get("read_only"), schreiber
    for leser in ("sales-ui", "sales-linkedin"):
        b = bind(leser)
        assert b is not None and b.get("read_only") is True, leser
