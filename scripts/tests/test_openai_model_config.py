from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SALES_CLAW_ENV_NAMES = {
    "OPENCLAW_STATE_DIR",
    "TZ",
}
SALES_AUTO_ENV_NAMES = {
    "AUTO_INTERVAL_S",
    "AUTO_SAMMELFENSTER_S",
    "OPENAI_API_KEY",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_MODEL",
    "SALES_DB_URL",
    "TZ",
}
ENV_EXAMPLE_NAMES = {
    "APIFY_TOKEN",
    "EMAIL_ABSENDER",
    "INBOX_UNBEKANNT_LEAD_ID",
    "INBOX_WEBHOOK_SECRET",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_API_VERSION",
    "LINKEDIN_PERSON_URN",
    "LINKEDIN_POST_LEAD_ID",
    "OPENAI_API_KEY",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_MODEL",
    "OPENWA_API_KEY",
    "OPENWA_SESSION_ID",
    "RECHERCHE_LEAD_ID",
    "SMTP_HOST",
    "SMTP_PASSWORT",
    "SMTP_PORT",
    "SMTP_USER",
    "TZ",
    "UI_TAILSCALE_IP",
}


def _active_assignments(path: Path) -> list[tuple[str, str]]:
    assignments: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        assert separator == "=", f"Ungueltige aktive .env-Zeile: {raw_line!r}"
        assignments.append((name, value))
    return assignments


def _assert_compose_model_environment(compose: dict[str, object]) -> None:
    services = compose["services"]
    claw_env = set(services["sales-claw"]["environment"])
    auto_env = set(services["sales-auto"]["environment"])
    claw_names = {item.partition("=")[0] for item in claw_env}
    auto_names = {item.partition("=")[0] for item in auto_env}
    assert not any(item.startswith("OPENAI_API_KEY=") for item in claw_env)
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in auto_env
    assert "OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.6-luna}" in auto_env
    assert "OPENAI_MAX_OUTPUT_TOKENS=${OPENAI_MAX_OUTPUT_TOKENS:-1500}" in auto_env
    assert claw_names == SALES_CLAW_ENV_NAMES
    assert auto_names == SALES_AUTO_ENV_NAMES


def _assert_env_example_model_assignments(
    assignments: list[tuple[str, str]],
) -> None:
    assert assignments.count(("OPENAI_API_KEY", "")) == 1
    assert assignments.count(("OPENAI_MODEL", "gpt-5.6-luna")) == 1
    assert assignments.count(("OPENAI_MAX_OUTPUT_TOKENS", "1500")) == 1
    names = {name for name, _ in assignments}
    assert names == ENV_EXAMPLE_NAMES


def _assert_openclaw_subscription_route(config: dict[str, object]) -> None:
    model = config["agents"]["defaults"]["model"]
    assert model == {"primary": "openai/gpt-5.6-terra", "fallbacks": []}
    providers = config["models"]["providers"]
    assert providers == {"openai": {"agentRuntime": {"id": "codex"}}}
    plugins = config["plugins"]
    assert set(plugins["allow"]) == {"codex", "whatsapp"}
    assert plugins["entries"]["codex"] == {"enabled": True}
    serialized = json.dumps(config)
    assert "anthropic" not in serialized.lower()
    assert "openrouter" not in serialized.lower()
    assert "api_key" not in serialized.lower()
    assert "baseurl" not in serialized.lower()


def test_openclaw_uses_codex_subscription_route_without_fallbacks() -> None:
    config = json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))
    _assert_openclaw_subscription_route(config)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda config: config["plugins"]["allow"].remove("codex"),
        lambda config: config["plugins"]["entries"]["codex"].update(
            {"enabled": False}
        ),
        lambda config: config["models"]["providers"]["openai"][
            "agentRuntime"
        ].update({"id": "openclaw"}),
        lambda config: config["agents"]["defaults"]["model"]["fallbacks"].append(
            "openai/gpt-5.6-luna"
        ),
        lambda config: config["models"]["providers"]["openai"].update(
            {"baseUrl": "https://api.openai.com/v1"}
        ),
    ),
    ids=(
        "codex-not-allowed",
        "codex-disabled",
        "runtime-not-codex",
        "fallback-added",
        "custom-base-url-added",
    ),
)
def test_openclaw_subscription_gate_rejects_route_mutations(mutation) -> None:
    config = json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(config)
    mutated["models"]["providers"] = {
        "openai": {"agentRuntime": {"id": "codex"}}
    }
    mutated["plugins"]["allow"] = ["codex", "whatsapp"]
    mutated["plugins"]["entries"]["codex"] = {"enabled": True}
    mutation(mutated)

    with pytest.raises(AssertionError):
        _assert_openclaw_subscription_route(mutated)


def test_compose_passes_only_openai_model_credentials() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    _assert_compose_model_environment(compose)


@pytest.mark.parametrize(
    ("service", "assignment"),
    (
        ("sales-claw", "OPENAI_BASE_URL=http://localhost:11434/v1"),
        ("sales-auto", "AUTO_MODELL=legacy-model"),
        ("sales-claw", "OLLAMA_MODEL=local-model"),
        ("sales-auto", "ACME_PROVIDER_MODEL=unreviewed-model"),
    ),
)
def test_compose_gate_rejects_forbidden_model_assignments(
    service: str, assignment: str
) -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(compose)
    mutated["services"][service]["environment"].append(assignment)

    with pytest.raises(AssertionError):
        _assert_compose_model_environment(mutated)


def test_env_example_has_only_openai_model_assignments() -> None:
    assignments = _active_assignments(ROOT / ".env.example")
    _assert_env_example_model_assignments(assignments)


@pytest.mark.parametrize(
    "assignment",
    (
        ("OPENAI_BASE_URL", "http://localhost:11434/v1"),
        ("AUTO_MODELL", "legacy-model"),
        ("OLLAMA_MODEL", "local-model"),
        ("ACME_PROVIDER_MODEL", "unreviewed-model"),
    ),
)
def test_env_example_gate_rejects_forbidden_model_assignments(
    assignment: tuple[str, str],
) -> None:
    assignments = _active_assignments(ROOT / ".env.example")

    with pytest.raises(AssertionError):
        _assert_env_example_model_assignments([*assignments, assignment])


def test_seed_script_recovers_only_openai_credentials(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh")
    assert powershell is not None, "PowerShell 7 ist fuer seed-env.ps1 erforderlich"

    openai_key = "sk-test-openai-key-must-not-be-printed"
    legacy_openrouter_key = "sk-or-v1-legacy-key-must-not-be-printed"
    source = tmp_path / "openclaw.json"
    target = tmp_path / "generated.env"
    source.write_text(
        json.dumps(
            {
                "env": {"OPENAI_API_KEY": openai_key},
                "skills": {
                    "entries": {
                        "legacy-provider": {"apiKey": legacy_openrouter_key}
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(ROOT / "scripts/seed-env.ps1"),
            "-Quelle",
            str(source),
            "-Ziel",
            str(target),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert _active_assignments(target) == [
        ("TZ", "Europe/Berlin"),
        ("OPENAI_API_KEY", openai_key),
        ("OPENAI_MODEL", "gpt-5.6-luna"),
    ]
    assert "OPENAI_API_KEY:" in completed.stdout
    assert "uebernommen" in completed.stdout
    assert "OPENROUTER" not in output.upper()
    assert "ANTHROPIC" not in output.upper()
    assert openai_key not in output
    assert legacy_openrouter_key not in output

    acl_environment = os.environ.copy()
    acl_environment["SEED_ACL_TARGET"] = str(target)
    acl_completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            """
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:SEED_ACL_TARGET
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rules = @($acl.GetAccessRules(
    $true,
    $true,
    [System.Security.Principal.SecurityIdentifier]
) | ForEach-Object {
    [pscustomobject]@{
        identity = $_.IdentityReference.Value
        inherited = $_.IsInherited
        type = $_.AccessControlType.ToString()
        canRead = (($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Read) -eq [System.Security.AccessControl.FileSystemRights]::Read)
        canWrite = (($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Write) -eq [System.Security.AccessControl.FileSystemRights]::Write)
    }
})
[pscustomobject]@{
    protected = $acl.AreAccessRulesProtected
    currentSid = $currentSid
    rules = $rules
} | ConvertTo-Json -Depth 4 -Compress
""",
        ],
        env=acl_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert acl_completed.returncode == 0, acl_completed.stderr
    acl = json.loads(acl_completed.stdout)
    assert acl["protected"] is True
    assert acl["rules"]
    assert all(rule["inherited"] is False for rule in acl["rules"])
    allow_rules = [rule for rule in acl["rules"] if rule["type"] == "Allow"]
    assert allow_rules
    assert {rule["identity"] for rule in allow_rules} == {acl["currentSid"]}
    assert any(rule["canRead"] and rule["canWrite"] for rule in allow_rules)


def test_seed_script_removes_target_when_acl_hardening_fails(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("pwsh")
    assert powershell is not None, "PowerShell 7 ist fuer seed-env.ps1 erforderlich"

    openai_key = "sk-test-acl-failure-key-must-not-be-printed"
    source = tmp_path / "legacy-openclaw.json"
    target = tmp_path / "generated.env"
    source.write_text(
        json.dumps({"env": {"OPENAI_API_KEY": openai_key}}),
        encoding="utf-8",
    )
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    (shim_dir / "icacls.cmd").write_text(
        "@echo off\r\nexit /b 5\r\n",
        encoding="ascii",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(shim_dir) + os.pathsep + environment["PATH"]

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(ROOT / "scripts/seed-env.ps1"),
            "-Quelle",
            str(source),
            "-Ziel",
            str(target),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert not target.exists()
    assert "Geschrieben nach" not in completed.stdout
    assert openai_key not in output
