"""deploy/postfach-zugang.sh (28.10.2026): GMX/Gmail eintragen.

Laeuft das Skript wirklich - mit einem Docker-Ersatz, der die Probe-Anmeldung
spielt und jeden Aufruf mitschreibt. Kein Netz, kein echtes Docker.
"""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

import postfach

WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = WURZEL / "deploy" / "postfach-zugang.sh"
GEHEIM = "Ab$c#1!x y"   # Sonderzeichen, die Compose sonst aufloesen oder abschneiden wuerde


@pytest.fixture
def umgebung(tmp_path):
    env_datei = tmp_path / ".env"
    env_datei.write_text("SMTP_HOST=mail.example.org\nPOSTFACH_GMX_ADRESSE=alt@gmx.de\n"
                         "POSTFACH_GMX_PASSWORT='alt'\nANDERES=1", encoding="utf-8")
    protokoll = tmp_path / "docker.log"
    ersatz = tmp_path / "docker"
    # exec: stdin lesen (Adresse, Passwort) und das Ergebnis der Probe spielen.
    ersatz.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$1 $2 $3 $4 $5 $6 $7 $8" >> "{protokoll}"\n'
        'if [ "$1" = exec ]; then cat > /dev/null; '
        '  if [ -n "$PROBE_FEHLER" ]; then echo "IMAP-Anmeldung abgelehnt (error): b\'AUTHENTICATIONFAILED\'"; exit 4; fi; '
        '  echo ok; fi\n', encoding="utf-8")
    ersatz.chmod(0o755)
    return {"env": env_datei, "protokoll": protokoll,
            "vars": {**os.environ, "SALES_ENV_DATEI": str(env_datei), "DOCKER": str(ersatz)}}


def _lauf(umgebung, kennung, eingabe, **zusatz):
    return subprocess.run(["bash", str(SKRIPT), kennung], input=eingabe, text=True,
                          capture_output=True, env={**umgebung["vars"], **zusatz}, timeout=30)


def test_traegt_ein_und_erzeugt_nur_die_beiden_dienste_neu(umgebung):
    r = _lauf(umgebung, "gmx", f"felix@gmx.de\n{GEHEIM}\n")
    assert r.returncode == 0, r.stderr
    text = umgebung["env"].read_text(encoding="utf-8")
    assert "POSTFACH_GMX_ADRESSE=felix@gmx.de\n" in text
    assert f"POSTFACH_GMX_PASSWORT='{GEHEIM}'\n" in text
    assert "alt@gmx.de" not in text and "ANDERES=1\n" in text and "SMTP_HOST=mail.example.org" in text
    assert stat.S_IMODE(umgebung["env"].stat().st_mode) == 0o600
    sicherungen = list(umgebung["env"].parent.glob(".env.vor-postfach-gmx-*"))
    assert len(sicherungen) == 1 and "alt@gmx.de" in sicherungen[0].read_text(encoding="utf-8")
    aufrufe = umgebung["protokoll"].read_text(encoding="utf-8")
    assert "exec -i sales-mcp python -c" in aufrufe
    assert "compose up -d --no-deps --force-recreate sales-mcp sales-mail" in aufrufe
    # Das Passwort steht nie in einer Ausgabe und nie in einer Kommandozeile.
    assert GEHEIM not in r.stdout + r.stderr + aufrufe


def test_abgelehnte_anmeldung_aendert_nichts(umgebung):
    vorher = umgebung["env"].read_text(encoding="utf-8")
    r = _lauf(umgebung, "gmail", f"felix@gmail.com\n{GEHEIM}\n", PROBE_FEHLER="1")
    assert r.returncode == 4
    assert "App-Passwort" in r.stderr and "Nichts geändert" in r.stderr
    assert umgebung["env"].read_text(encoding="utf-8") == vorher
    assert "compose" not in umgebung["protokoll"].read_text(encoding="utf-8")


@pytest.mark.parametrize("eingabe", ["keine-adresse\ngeheim\n", "a@gmx.de\n\n", "a@gmx.de\nmit'quote\n"])
def test_unbrauchbare_eingaben_brechen_ab(umgebung, eingabe):
    vorher = umgebung["env"].read_text(encoding="utf-8")
    r = _lauf(umgebung, "gmx", eingabe)
    assert r.returncode == 3
    assert umgebung["env"].read_text(encoding="utf-8") == vorher


def test_unbekanntes_postfach(umgebung):
    assert _lauf(umgebung, "yahoo", "").returncode == 2


def test_compose_eingetragen_wo_gebraucht_und_namen_wie_im_code():
    compose = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    beispiel = (WURZEL / ".env.example").read_text(encoding="utf-8")
    skript = SKRIPT.read_text(encoding="utf-8")
    for kennung, info in postfach.ANBIETER.items():
        assert re.search(rf"^\s*{kennung}\)\s+IMAP={re.escape(info['imap'])};\s+SMTP={re.escape(info['smtp'])}",
                         skript, re.M), kennung
        for teil in ("ADRESSE", "PASSWORT"):
            name = f"POSTFACH_{kennung.upper()}_{teil}"
            assert f"  {name}: ${{{name}:-}}" in compose          # Anker sales-mcp & Co.
            assert f"      - {name}=${{{name}:-}}" in compose     # sales-mail
            assert re.search(rf"^{name}=$", beispiel, re.M)
    assert "read -r -s" in skript and not re.search(r"^\s*set -[a-z]*x", skript, re.M)
