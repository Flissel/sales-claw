"""Anbindung der Post-Sammelstelle (Task 10): reine Textpruefungen, keine DB.

Das Skript laeuft nur gegen echte Container; hier wird geprueft, dass es nichts
ausgibt, nichts startet, ohne Besitzer abbricht und die Saat den Agenten `post`
ohne Werkzeuge kennt.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]


def _code(pfad: str) -> str:
    skript = (WURZEL / pfad).read_text(encoding="utf-8")
    return "\n".join(z for z in skript.splitlines() if not z.lstrip().startswith("#"))


def test_skript_hat_gueltige_bash_syntax():
    # Skript ueber stdin: auf Windows ist `bash` mitunter WSL und kennt keine C:-Pfade.
    try:
        r = subprocess.run(["bash", "-n"], input=(WURZEL / "deploy" / "post-anbinden.sh").read_bytes(),
                           capture_output=True)
    except FileNotFoundError:
        pytest.skip("kein bash")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_skript_bricht_ohne_besitzer_vor_jeder_aenderung_ab():
    code = _code("deploy/post-anbinden.sh")
    leer = code.index('if [ -z "$BESITZER" ]')
    # Vor dem Abbruch darf nichts geschrieben oder in Container geschickt werden.
    assert "docker exec" not in code[:leer] and "post-schluessel.sh" not in code[:leer]
    assert "exit 1" in code[leer:leer + 400]


def test_skript_gibt_den_token_nie_aus_und_startet_nichts():
    code = _code("deploy/post-anbinden.sh")
    assert not re.search(r"set -[a-z]*x", code)
    assert "echo \"$TOKEN\"" not in code and "echo $TOKEN" not in code
    # Token nie in einer docker-Kommandozeile (ps): die Probe liest ihn im Container selbst.
    assert "TOKEN" not in code and "-e T=" not in code
    assert "gateway?.auth?.token" in code
    assert "docker restart" not in code.replace("(docker restart $CONTAINER, mit dem Betreiber", "")
    ausgefuehrt = chr(10).join(z for z in code.splitlines() if not z.lstrip().startswith("echo"))
    assert "compose" not in ausgefuehrt                         # Hinweise nur als echo, nie ausgefuehrt
    # Der Token wird wiederverwendet, nicht neu in die .env geschrieben.
    assert "OPENCLAW_GATEWAY_TOKEN=" not in code
    # Warteschleife wie bei auto-anbinden (Neuladen kommt Sekunden nach config set).
    assert "for (let i = 0; i < 30; i++)" in code and "setTimeout" in code
    assert "openclaw/post" in code


def test_skript_agent_ohne_werkzeuge_modell_mit_rueckfall():
    code = _code("deploy/post-anbinden.sh")
    assert 'deny: ["*"]' in code
    assert "workspace-post" in code
    assert "anthropic/claude-haiku-5-5" in code
    # Rueckfall ohne Modell, wenn das Feld abgelehnt wird, mit klarem Hinweis.
    assert "ohneModell" in code and "OHNE Modell" in code


def test_skript_schluessel_sql_leitung_und_konten():
    code = _code("deploy/post-anbinden.sh")
    assert "POST_SCHLUESSEL_PRIVAT" in code and "post-schluessel.sh" in code
    assert "db/post-sammelstelle.sql" in code and "-v \"schema=$SCHEMA\"" in code
    # Schema aus der Umgebung des Ladens, nicht aus dem Praefix; kein -e SALES_DB_SCHEMA am mcp-Container.
    assert "^SALES_DB_SCHEMA=" in code and 'SCHEMA="${SCHEMA:-sales}"' in code
    assert "-e \"SALES_DB_SCHEMA" not in code
    assert "^[a-z][a-z0-9_]{0,30}$" in code
    assert "set leitung = true where name = %s" in code
    assert "env_konten_uebernehmen" in code
    # Besitzername geht per Umgebung, nie in SQL-Text oder Kommandozeile von psql.
    assert "POST_BESITZER" in code and "%s" in code


def test_saat_kennt_agent_post_ohne_werkzeuge():
    c = json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))
    liste = c["agents"]["list"]
    agenten = {a["id"]: a for a in liste}
    assert agenten["post"]["tools"] == {"deny": ["*"]}
    assert agenten["post"]["workspace"] == "/home/node/.openclaw/workspace-post"
    assert agenten["post"]["workspace"] != agenten["auto"]["workspace"]
    assert liste[0]["id"] == "main"
    assert [a["id"] for a in liste].index("post") > [a["id"] for a in liste].index("auto")


def test_smoke_hat_abschnitt_sales_post_mit_uebersprungen():
    smoke = (WURZEL / "deploy" / "smoke.sh").read_text(encoding="utf-8")
    i = smoke.index("# 20) Post-Sammelstelle")
    abschnitt = smoke[i:smoke.index('echo "---"', i)]
    assert "sales-post" in abschnitt and "uebersprungen" in abschnitt
    assert "post_mails" in abschnitt
    # Kein Mindest-Alter (update.sh erzeugt neu und prueft ~30 s spaeter -> sonst Rueckbau).
    assert "StartedAt" not in abschnitt and "-lt 120" not in abschnitt
    assert "{{.State.Restarting}} {{.RestartCount}}" in abschnitt and "-ge 3" in abschnitt
    # sales-post gehoert NICHT in die Pflichtliste der Container (sonst rot vor dem Ausrollen).
    pflicht = re.search(r"for c in (sales-mcp[^;]*); do", smoke).group(1)
    assert "sales-post" not in pflicht


def test_runbook_beschreibt_ausrollen_und_rueckweg():
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    i = rb.index("## Post-Sammelstelle")
    abschnitt = rb[i:]
    for stichwort in ("post-anbinden.sh", "update.sh", "up -d sales-post", "R13",
                      "compose stop sales-post", "POST_BESITZER"):
        assert stichwort in abschnitt


def test_modell_rueckfall_nur_bei_schemaablehnung():
    code = _code("deploy/post-anbinden.sh")
    assert "process.exit(5)" in code and "unrecogni" in code and "validation" in code
    assert code.index("process.exit(5)") < code.index("setze(ohneModell);\n      console.log")


def test_neues_schluesselpaar_gibt_ui_neuerzeugen_aus_ohne_es_zu_tun():
    code = _code("deploy/post-anbinden.sh")
    assert "NEUES_PAAR=1" in code
    assert code.count("force-recreate sales-ui") == 2           # nur als Echo
    assert not any(z.lstrip().startswith("docker compose") for z in code.splitlines())
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    assert "up -d --no-deps --force-recreate sales-ui" in rb[rb.index("## Post-Sammelstelle"):]
