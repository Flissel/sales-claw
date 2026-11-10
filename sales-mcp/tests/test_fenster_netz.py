"""Portal-Fenster: das Netz bewerbung-fenster haengt NUR an der sales-ui des Basis-Ladens.

Der Portal-Container surft auf fremden Seiten; haengte die Vorlage docker-compose.yml (gilt fuer
JEDEN Laden) die sales-ui an dieses Netz, saehen auch zweite Laeden den Container. Deshalb steht
das Netz in docker-compose.fenster.yml, die nur die Deploy-Skripte fuer den Basis-Laden dazunehmen.
Rein: liest Dateien und startet bash mit Attrappen, kein Docker, keine DB."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WURZEL = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
OVERRIDE = "-f docker-compose.yml -f docker-compose.fenster.yml"


def _lesen(rel: str) -> str:
    return (WURZEL / rel).read_text(encoding="utf-8")


def test_vorlage_kennt_das_netz_nicht():
    assert "bewerbung-fenster" not in _lesen("docker-compose.yml")
    doc = yaml.safe_load(_lesen("docker-compose.yml"))
    assert "bewerbung-fenster" not in (doc.get("networks") or {})
    assert "bewerbung-fenster" not in str(doc["services"]["sales-ui"].get("networks"))


def test_vorlage_reicht_nur_adresse_und_schluessel_durch():
    env = doc_env = yaml.safe_load(_lesen("docker-compose.yml"))["services"]["sales-ui"]["environment"]
    assert "BEWERBUNG_FENSTER_WS=${BEWERBUNG_FENSTER_WS:-}" in env
    assert "BEWERBUNG_FENSTER_SCHLUESSEL=${BEWERBUNG_FENSTER_SCHLUESSEL:-}" in doc_env


def test_override_haengt_nur_sales_ui_an_das_externe_netz():
    doc = yaml.safe_load(_lesen("docker-compose.fenster.yml"))
    assert list(doc["services"]) == ["sales-ui"]
    assert doc["services"]["sales-ui"] == {"networks": ["default", "bewerbung-fenster"]}
    assert doc["networks"] == {"bewerbung-fenster": {"external": True, "name": "bewerbung-fenster"}}
    assert set(doc) == {"services", "networks"}


def test_netz_skript_ist_idempotent_und_intern():
    s = _lesen("deploy/fenster-netz-anlegen.sh")
    assert "set -euo pipefail" in s
    assert "docker network inspect bewerbung-fenster >/dev/null 2>&1" in s
    assert "docker network create --internal bewerbung-fenster >/dev/null" in s
    assert "||" in s


def test_update_kennt_das_netz_nur_ueber_das_skript():
    u = _lesen("deploy/update.sh")
    assert "docker network" not in u                       # nicht mehr inline
    assert 'LADEN_DATEIEN=("-f docker-compose.yml -f docker-compose.fenster.yml")' in u
    assert u.count('LADEN_DATEIEN+=("")') == 1             # zweite Laeden: leer
    ups = re.findall(r"^\s*docker compose .*$", u, re.M)
    mit_override = [z for z in ups if "compose_dateien" in z]
    openwa = [z for z in ups if "docker-compose.openwa.yml" in z]
    assert len(mit_override) == 2 and len(openwa) == 1 and len(ups) == 3
    assert "compose_dateien" not in openwa[0]
    # Vor jedem `up` (Bau UND Rueckbau) wird das Netz gesichert.
    for z in mit_override:
        vorher = u[: u.index(z)].rstrip().splitlines()
        assert any(l.strip() == 'fenster_netz_sichern "$i"' for l in vorher[-4:]), z


@pytest.mark.skipif(BASH is None, reason="braucht bash")
@pytest.mark.parametrize("skript_ok,laden,erwartet", [
    (True, 0, OVERRIDE), (True, 1, ""), (False, 0, ""), (False, 1, ""),
])
def test_update_gibt_den_override_nur_dem_basis_laden_und_nur_mit_netz(
        tmp_path, skript_ok, laden, erwartet):
    u = _lesen("deploy/update.sh").replace("\r\n", "\n")
    a = u.index("FENSTER_NETZ_OK=false")
    b = u.index("gateway_neustarten() {")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "fenster-netz-anlegen.sh").write_text(
        f"#!/usr/bin/env bash\nexit {0 if skript_ok else 1}\n", encoding="utf-8")
    (tmp_path / "docker-compose.fenster.yml").write_text("services: {}\n", encoding="utf-8")
    skript = (f'set -euo pipefail\nWURZEL="{tmp_path.as_posix()}"\n'
              f'LADEN_DATEIEN=("{OVERRIDE}" "")\n{u[a:b]}\n'
              f'fenster_netz_sichern {laden}\nx="$(compose_dateien {laden})"\necho "[$x]"\n')
    r = subprocess.run([BASH, "-c", skript], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr          # ein Fehlschlag des Skripts bricht nichts ab
    assert r.stdout.strip() == f"[{erwartet}]"
    if not skript_ok and laden == 0:
        assert "HINWEIS" in r.stderr


def test_bootstrap_und_benutzer_anlegen_nehmen_den_override_nur_fuer_den_basis_laden():
    b = _lesen("deploy/bootstrap.sh")
    assert "bash deploy/fenster-netz-anlegen.sh" in b
    assert f"docker compose {OVERRIDE} up -d sales-mcp sales-ui" in b
    assert "docker compose up -d sales-mcp sales-ui" in b       # Rueckfall ohne Netz
    n = _lesen("deploy/benutzer-anlegen.sh")
    assert 'if [ -z "$ENVARG" ] && bash "$REPO/deploy/fenster-netz-anlegen.sh"' in n
    assert "docker compose $ENVARG $DATEIEN up -d" in n
    # admin-auftrag-ausfuehren.sh legt nur NEUE (zweite) Laeden an: unveraendert, ohne Fenster.
    assert "fenster" not in _lesen("deploy/admin-auftrag-ausfuehren.sh")
