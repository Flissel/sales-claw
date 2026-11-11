"""Portal-Fenster: das Netz bewerbung-fenster haengt NUR an der sales-ui des Basis-Ladens.

Der Portal-Container surft auf fremden Seiten; haengte die Vorlage docker-compose.yml (gilt fuer
JEDEN Laden) die sales-ui an dieses Netz, saehen auch zweite Laeden den Container. Deshalb steht
das Netz in docker-compose.fenster.yml, die nur die Deploy-Skripte fuer den Basis-Laden dazunehmen.
Rein: liest Dateien und startet bash mit Attrappen, kein Docker, keine DB."""
import os
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


# --- SC-M4: ein vorhandenes, NICHT internes Netz wird nicht hingenommen -------------------------------

_FALSCHES_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
if [ "$1 $2" = "network inspect" ]; then
  [ "${FAKE_NETZ:-da}" = "fehlt" ] && exit 1
  [ "$3" = "-f" ] && echo "${FAKE_INTERN-true}"
fi
exit 0
"""


def _mit_falschem_docker(tmp_path, skripte: list[str], **env_extra):
    """Kopiert die Skripte (LF) nach tmp_path/deploy, legt ein falsches `docker` vorn in den PATH und gibt
    (Prozess, Docker-Aufrufe) zurueck. Kein echtes Docker."""
    (tmp_path / "deploy").mkdir(exist_ok=True)
    for rel in skripte:
        (tmp_path / rel).write_text(_lesen(rel).replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    (tmp_path / "docker-compose.fenster.yml").write_text("services: {}\n", encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "docker").write_text(_FALSCHES_DOCKER, encoding="utf-8", newline="\n")
    # Ueber PATH aufgerufen: ohne Ausfuehrungsrecht scheitert bash unter Linux mit 126.
    (bin_ / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(log), **env_extra}
    return env, log


@pytest.mark.skipif(BASH is None, reason="braucht bash")
@pytest.mark.parametrize("netz,intern,ok", [
    ("fehlt", "true", True),      # wird angelegt
    ("da", "true", True),         # intern: nichts zu tun
    ("da", "false", False),       # vorhanden, aber nicht intern: Fehler
    ("da", "", False),            # Antwort unlesbar: Fehler
])
def test_netz_skript_verlangt_ein_internes_netz(tmp_path, netz, intern, ok):
    env, log = _mit_falschem_docker(tmp_path, ["deploy/fenster-netz-anlegen.sh"],
                                    FAKE_NETZ=netz, FAKE_INTERN=intern)
    r = subprocess.run([BASH, "deploy/fenster-netz-anlegen.sh"], capture_output=True, text=True,
                       cwd=tmp_path, env=env)
    aufrufe = log.read_text(encoding="utf-8")
    assert (r.returncode == 0) is ok, (r.stdout, r.stderr)
    assert ("network create --internal bewerbung-fenster" in aufrufe) is (netz == "fehlt")
    if not ok:
        assert "NICHT intern" in r.stderr and "bewerbung-fenster" in r.stderr
        assert "network create" not in aufrufe
    if netz == "da":
        assert "network inspect -f {{.Internal}} bewerbung-fenster" in aufrufe


def test_netz_skript_prueft_internal_im_text():
    s = _lesen("deploy/fenster-netz-anlegen.sh")
    assert "docker network inspect -f '{{.Internal}}' bewerbung-fenster" in s and '!= "true"' in s
    assert "exit 1" in s


# --- SC-I2: die Basis-sales-ui wird nie ohne das Netz neu erzeugt ----------------------------------------

def test_sales_ui_neu_ist_der_eine_weg_fuer_die_basis_sales_ui():
    s = _lesen("deploy/sales-ui-neu.sh")
    assert s.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in s
    assert "bash deploy/fenster-netz-anlegen.sh" in s and "[ -f docker-compose.fenster.yml ]" in s
    assert 'docker compose "${DATEIEN[@]}" up -d --no-deps --force-recreate sales-ui' in s
    assert "DATEIEN=(-f docker-compose.yml)" in s and "DATEIEN+=(-f docker-compose.fenster.yml)" in s
    assert "env-file" not in s.replace("zweite Laeden behalten ihren Befehl mit --env-file", "")


@pytest.mark.skipif(BASH is None, reason="braucht bash")
@pytest.mark.parametrize("netz_ok,datei,erwartet", [
    (True, True, "compose -f docker-compose.yml -f docker-compose.fenster.yml up -d --no-deps --force-recreate sales-ui"),
    (False, True, "compose -f docker-compose.yml up -d --no-deps --force-recreate sales-ui"),
    (True, False, "compose -f docker-compose.yml up -d --no-deps --force-recreate sales-ui"),
])
def test_sales_ui_neu_nimmt_den_override_nur_mit_netz_und_datei(tmp_path, netz_ok, datei, erwartet):
    env, log = _mit_falschem_docker(tmp_path, ["deploy/sales-ui-neu.sh"])
    (tmp_path / "deploy" / "fenster-netz-anlegen.sh").write_text(
        f"#!/usr/bin/env bash\nexit {0 if netz_ok else 1}\n", encoding="utf-8", newline="\n")
    if not datei:
        (tmp_path / "docker-compose.fenster.yml").unlink()
    r = subprocess.run([BASH, "deploy/sales-ui-neu.sh"], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr             # ein Fehlschlag des Netz-Skripts ist nicht tragisch
    assert log.read_text(encoding="utf-8").strip() == erwartet
    assert ("HINWEIS" in r.stderr) is not (netz_ok and datei)


@pytest.mark.skipif(BASH is None, reason="braucht bash")
def test_sales_ui_neu_ohne_netz_skript_laeuft_ohne_override(tmp_path):
    env, log = _mit_falschem_docker(tmp_path, ["deploy/sales-ui-neu.sh"])      # fenster-netz-anlegen.sh fehlt
    r = subprocess.run([BASH, "deploy/sales-ui-neu.sh"], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    assert "fenster.yml" not in log.read_text(encoding="utf-8")


def test_hinweis_und_doku_verweisen_auf_das_skript():
    p = _lesen("deploy/post-anbinden.sh")
    assert 'if [ "$PRAEFIX" = "sales" ]; then' in p and 'echo "  bash deploy/sales-ui-neu.sh"' in p
    assert 'echo "  docker compose up -d --no-deps --force-recreate sales-ui"' not in p
    # andere Laeden behalten ihren Befehl
    assert "--env-file deploy/laeden/$PRAEFIX.env up -d --no-deps --force-recreate sales-ui" in p
    b = _lesen("docs/04_BETRIEB_MINIPC.md")
    assert "bash deploy/sales-ui-neu.sh" in b
    assert "docker compose up -d sales-ui'" not in b                     # Zeile ~336: ohne Skript-Weg
    karte = b[b.index("## Rückfahrkarte"):b.index("## Sicherung")]
    assert "docker compose build sales-ui && bash deploy/sales-ui-neu.sh" in karte
    flach = " ".join(karte.split())
    assert "ohne `docker-compose.fenster.yml` und ohne dieses Skript" in flach and "alte schlichte Befehl" in flach
    r = _lesen("docs/03_RUNBOOK.md")
    assert r.count("bash deploy/sales-ui-neu.sh") >= 2
    assert "`docker compose up -d --no-deps --force-recreate sales-ui` (andere Laeden" not in r
    assert "Ist unklar, ob sie raus ist, vermerkst du" in _lesen("docs/05_BEDIENUNG.md")


# R64: ein schlichter Basis-Recreate von sales-ui in den Betriebsdokus verliert still das Netz bewerbung-fenster.
_PLAIN_UI = re.compile(r"docker compose(?![^`\n&]*--env-file)[^`\n&]*\bup\b[^`\n&]*\bsales-ui(?![-\w])")
# bewusst stehengelassen (Datei, genauer Zeilentext): die Warnung selbst und der alte Rueckfahr-Befehl fuer einen
# vor-update-Stand ohne Portal-Fenster
_PLAIN_UI_ERLAUBT = {
    ("docs/04_BETRIEB_MINIPC.md",
     "schlichtes `docker compose up -d sales-ui` verlöre es. Liegt `vor-update` vor dem Portal-Fenster, also ohne"),
    ("docs/04_BETRIEB_MINIPC.md",
     "`docker compose up -d --build sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw`."),
}


def _logische_zeilen(text: str):
    """(Zeilennummer, Text): ein Befehl, der per Backslash oder in einem offenen Backtick-Bereich ueber
    Zeilenumbrueche laeuft, zaehlt als eine Zeile (Umbruch + Einrueckung -> ein Leerzeichen)."""
    puffer, start = "", 0
    for n, z in enumerate(text.splitlines(), 1):
        if not puffer:
            start = n
        puffer = f"{puffer} {z.strip()}" if puffer else z
        offen = puffer.rstrip().endswith("\\") or (
            puffer.count("`") % 2 == 1 and not puffer.lstrip().startswith("```"))
        if offen:
            continue
        yield start, puffer
        puffer = ""
    if puffer:
        yield start, puffer


@pytest.mark.parametrize("rel", ["docs/03_RUNBOOK.md", "docs/04_BETRIEB_MINIPC.md", "docs/11_INBETRIEBNAHME.md",
                                 "README.md"])
def test_doku_hat_keinen_schlichten_basis_recreate_von_sales_ui(rel):
    schlecht = [
        f"{rel}:{n}: {z.strip()}"
        for n, z in _logische_zeilen(_lesen(rel))
        if _PLAIN_UI.search(z) and (rel, z.strip()) not in _PLAIN_UI_ERLAUBT
    ]
    assert not schlecht, "\n".join(schlecht)


def test_umgebrochener_befehl_wird_gefunden():
    text = ("x `docker compose up -d --no-deps --force-recreate\nsales-post sales-ui` y\n"
            "docker compose up -d " + chr(92) + "\n  sales-ui\n")
    treffer = [n for n, z in _logische_zeilen(text) if _PLAIN_UI.search(z)]
    assert treffer == [1, 3]


def test_plain_recreate_regex_trifft_die_bekannten_formen():
    for z in (
        "docker compose up -d sales-ui",
        "`docker compose up -d --no-deps --force-recreate sales-post sales-ui`.",
        "`docker compose up -d --no-deps --force-recreate sales-ui sales-kalender`",
        "docker compose up -d --build sales-ui",
    ):
        assert _PLAIN_UI.search(z), z
    for z in (
        "`docker compose --env-file deploy/laeden/<laden>.env up -d --no-deps --force-recreate sales-ui`.",
        "docker compose up -d --no-deps --force-recreate sales-post && bash deploy/sales-ui-neu.sh",
        "docker compose build sales-ui && bash deploy/sales-ui-neu.sh",
    ):
        assert not _PLAIN_UI.search(z), z
