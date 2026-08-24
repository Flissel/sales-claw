from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


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


def test_openclaw_uses_openai_without_fallbacks() -> None:
    config = json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))
    model = config["agents"]["defaults"]["model"]
    assert model == {"primary": "openai/gpt-5.6-terra", "fallbacks": []}
    providers = config["models"]["providers"]
    assert set(providers) == {"openai"}
    assert providers["openai"]["models"] == [
        {"id": "gpt-5.6-terra", "name": "gpt-5.6-terra"}
    ]
    serialized = json.dumps(config)
    assert "anthropic" not in serialized.lower()
    assert "openrouter" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_compose_passes_only_openai_model_credentials() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    claw_env = set(compose["services"]["sales-claw"]["environment"])
    auto_env = set(compose["services"]["sales-auto"]["environment"])
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in claw_env
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in auto_env
    assert "OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.6-luna}" in auto_env
    assert not any(
        "ANTHROPIC" in item or "OPENROUTER" in item
        for item in claw_env | auto_env
    )


def test_env_example_has_only_openai_model_assignments() -> None:
    assignments = _active_assignments(ROOT / ".env.example")
    assert assignments.count(("OPENAI_API_KEY", "")) == 1
    assert assignments.count(("OPENAI_MODEL", "gpt-5.6-luna")) == 1
    names = {name for name, _ in assignments}
    assert "OPENROUTER_API_KEY" not in names
    assert "ANTHROPIC_API_KEY" not in names


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
