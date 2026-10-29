"""deploy/pm-token-eintragen.sh (29.10.2026): PM_TOKEN_SALES verdeckt eintragen.

Laeuft das Skript wirklich - gegen eine Wegwerf-.env und einen Ersatz fuer
deploy/pm-anbinden.sh, der jeden Aufruf mitschreibt. Kein Netz, kein Docker.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
SKRIPT = WURZEL / "deploy" / "pm-token-eintragen.sh"
TOKEN = "pmtok_Ab12-cd34_EF56.gh78~ij90+kl/mn="


@pytest.fixture
def umgebung(tmp_path):
    env_datei = tmp_path / ".env"
    env_datei.write_text("SMTP_HOST=mail.example.org\nPM_TOKEN_SALES=alt-token-0000000000\nANDERES=1",
                         encoding="utf-8")
    protokoll = tmp_path / "anbinden.log"
    ersatz = tmp_path / "pm-anbinden.sh"
    ersatz.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "aufgerufen $*" >> "{protokoll}"\n'
        'env >> "' + str(protokoll) + '"\n'
        'exit "${ANBINDEN_EXIT:-0}"\n', encoding="utf-8")
    ersatz.chmod(0o755)
    return {"env": env_datei, "protokoll": protokoll,
            "vars": {**os.environ, "SALES_ENV_DATEI": str(env_datei), "PM_ANBINDEN": str(ersatz)}}


def _lauf(umgebung, eingabe, *args, **zusatz):
    return subprocess.run(["bash", str(SKRIPT), *args], input=eingabe, text=True,
                          capture_output=True, env={**umgebung["vars"], **zusatz}, timeout=30)


def test_traegt_ein_ersetzt_den_alten_und_bindet_an(umgebung):
    r = _lauf(umgebung, f"{TOKEN}\n")
    assert r.returncode == 0, r.stderr
    text = umgebung["env"].read_text(encoding="utf-8")
    assert f"PM_TOKEN_SALES={TOKEN}\n" in text
    assert "alt-token" not in text
    assert "SMTP_HOST=mail.example.org\n" in text and "ANDERES=1\n" in text
    assert stat.S_IMODE(umgebung["env"].stat().st_mode) == 0o600
    sicherungen = list(umgebung["env"].parent.glob(".env.vor-pm-token-*"))
    assert len(sicherungen) == 1 and "alt-token" in sicherungen[0].read_text(encoding="utf-8")
    assert stat.S_IMODE(sicherungen[0].stat().st_mode) == 0o600
    protokoll = umgebung["protokoll"].read_text(encoding="utf-8")
    assert protokoll.startswith("aufgerufen \n")
    # Der Token steht nie in einer Ausgabe, nie als Argument und nicht in der
    # Umgebung des Anbinde-Skripts (das liest ihn selbst aus der .env).
    assert TOKEN not in r.stdout + r.stderr + protokoll


def test_ohne_anbinden_schreibt_nur(umgebung):
    r = _lauf(umgebung, f"{TOKEN}\n", "--ohne-anbinden")
    assert r.returncode == 0, r.stderr
    assert f"PM_TOKEN_SALES={TOKEN}\n" in umgebung["env"].read_text(encoding="utf-8")
    assert not umgebung["protokoll"].exists()


def test_crlf_vom_einfuegen_wird_abgeschnitten(umgebung):
    r = _lauf(umgebung, f"{TOKEN}\r\n", "--ohne-anbinden")
    assert r.returncode == 0, r.stderr
    assert f"PM_TOKEN_SALES={TOKEN}\n" in umgebung["env"].read_text(encoding="utf-8")


def test_fehlende_zeile_wird_angehaengt(umgebung):
    umgebung["env"].write_text("ANDERES=1\n", encoding="utf-8")
    r = _lauf(umgebung, f"{TOKEN}\n", "--ohne-anbinden")
    assert r.returncode == 0, r.stderr
    assert umgebung["env"].read_text(encoding="utf-8") == f"ANDERES=1\nPM_TOKEN_SALES={TOKEN}\n"


@pytest.mark.parametrize("eingabe", ["\n", "x1y2z3\n","mit leerzeichen 1234567890\n",
                                     "mit$dollar_1234567890abc\n", "mit'quote_1234567890abc\n",
                                     'mit"quote_1234567890abc\n', "mit#raute_1234567890abc\n"])
def test_unbrauchbare_eingaben_aendern_nichts(umgebung, eingabe):
    vorher = umgebung["env"].read_text(encoding="utf-8")
    r = _lauf(umgebung, eingabe)
    assert r.returncode == 3
    assert "nichts geändert" in r.stderr
    assert umgebung["env"].read_text(encoding="utf-8") == vorher
    assert not list(umgebung["env"].parent.glob(".env.vor-pm-token-*"))
    assert not umgebung["protokoll"].exists()
    assert eingabe.strip() == "" or eingabe.strip() not in r.stdout + r.stderr


def test_rote_anbindung_meldet_sich_und_behaelt_den_token(umgebung):
    r = _lauf(umgebung, f"{TOKEN}\n", ANBINDEN_EXIT="2")
    assert r.returncode == 2
    assert "erneut" in r.stderr
    assert f"PM_TOKEN_SALES={TOKEN}\n" in umgebung["env"].read_text(encoding="utf-8")
    assert TOKEN not in r.stdout + r.stderr


def test_fehlende_env_datei(umgebung, tmp_path):
    r = _lauf(umgebung, f"{TOKEN}\n", SALES_ENV_DATEI=str(tmp_path / "gibtsnicht" / ".env"))
    assert r.returncode == 1


def test_kein_set_x_und_kein_echo_des_tokens():
    code = "\n".join(z for z in SKRIPT.read_text(encoding="utf-8").splitlines()
                     if not z.lstrip().startswith("#"))
    assert "set -x" not in code
    assert "read -r -s" in code
    assert 'echo "$token' not in code and "echo $token" not in code
    assert "pm-claw/.env" not in code      # der Token wird NICHT aus pm-claw gelesen
