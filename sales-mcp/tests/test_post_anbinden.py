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


@pytest.mark.parametrize("skript", ["post-anbinden.sh", "post-sitzungen-aufraeumen.sh"])
def test_skript_hat_gueltige_bash_syntax(skript):
    # Skript ueber stdin: auf Windows ist `bash` mitunter WSL und kennt keine C:-Pfade.
    try:
        r = subprocess.run(["bash", "-n"], input=(WURZEL / "deploy" / skript).read_bytes(),
                           capture_output=True)
    except FileNotFoundError:
        pytest.skip("kein bash")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_sitzungen_aufraeumen_loescht_nur_alte_post_sitzungen():
    """I3 / R17: das Gateway legt je eingeordneter Mail eine Sitzungsdatei mit
    dem Mailinhalt an. Das Skript loescht die von Agent post nach 10 min - nur
    dort, nie Inhalte ausgeben, nichts starten."""
    code = _code("deploy/post-sitzungen-aufraeumen.sh")
    assert "/home/node/.openclaw/agents/post/sessions" in code
    assert "-mmin +10" in code and "-delete" in code and "-type f" in code
    assert "agents/main" not in code and "agents/auto" not in code
    assert "-name '*.jsonl*'" in code
    # Index-Eintraege ohne Datei raeumt OpenClaw selbst weg (nur Agent post).
    assert "sessions cleanup --agent post --fix-missing" in code
    for verboten in ("cat ", "head ", "tail ", "grep ", "less ", "docker restart",
                     "compose", "set -x"):
        assert verboten not in code, verboten
    assert "^[a-z][a-z0-9_]{0,30}$" in code
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    abschnitt = rb[rb.index("## Post-Sammelstelle"):]
    assert "*/5 * * * *" in abschnitt and "post-sitzungen-aufraeumen.sh" in abschnitt


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


def test_skript_agent_ohne_werkzeuge_eigenes_modell_ohne_rueckfall():
    """I2: Agent post darf nie auf die Vorgabe des Ladens (fallbacks
    [openrouter/free]) fallen - weder per Modell-Rueckfall noch per Eintrag
    ohne Modell."""
    code = _code("deploy/post-anbinden.sh")
    assert 'deny: ["*"]' in code
    assert "workspace-post" in code
    assert 'model: { primary: "anthropic/claude-haiku-5-5", fallbacks: [] }' in code
    assert "ohneModell" not in code and "OHNE Modell" not in code
    # Ein alter Eintrag ohne Modell zaehlt nicht als "schon da" - er wird ersetzt.
    assert code.count('config", "set", "agents.list"') == 1
    assert "neu[i] = soll" in code


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


def test_abgelehntes_modell_bricht_ab():
    """I2: lehnt das Gateway agents.list[].model ab, bricht das Skript ab -
    nach dem einzigen config set kommt im Fehlerzweig nur noch exit(5)."""
    code = _code("deploy/post-anbinden.sh")
    i = code.index('lauf(["config", "set", "agents.list"')
    fang = code[i:code.index("process.exit(5)", i)]
    assert "catch (e)" in fang and "ABBRUCH" in fang
    assert "lauf(" not in fang[5:]                     # kein zweiter Versuch im Fehlerzweig


def test_saat_agent_post_ohne_fallbacks():
    """I2: die Vorgabe des Ladens hat fallbacks [openrouter/free]; post hat ein
    eigenes Modell mit leerer Liste (OpenClaw: [] ersetzt die Vorgabe)."""
    c = json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))
    post = {a["id"]: a for a in c["agents"]["list"]}["post"]
    assert post["model"] == {"primary": "anthropic/claude-haiku-5-5", "fallbacks": []}
    assert "openrouter/free" in c["agents"]["defaults"]["model"]["fallbacks"]   # darum
    # Saat und Skript setzen denselben Eintrag (sonst zieht das Skript staendig nach).
    code = _code("deploy/post-anbinden.sh")
    assert post["workspace"] in code and "anthropic/claude-haiku-5-5" in code


def test_neues_schluesselpaar_gibt_ui_neuerzeugen_aus_ohne_es_zu_tun():
    code = _code("deploy/post-anbinden.sh")
    assert "NEUES_PAAR=1" in code
    assert code.count("force-recreate sales-ui") == 2           # nur als Echo
    assert not any(z.lstrip().startswith("docker compose") for z in code.splitlines())
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    assert "up -d --no-deps --force-recreate sales-ui" in rb[rb.index("## Post-Sammelstelle"):]


def test_aufraeum_timer_ruft_das_skript_alle_5_minuten():
    """Die Gateway-Kopien jeder eingeordneten Mail (agents/post/sessions) sollen
    nicht liegen bleiben - der Hauptagent hat Dateiwerkzeuge (Ruling R17)."""
    dienst = (WURZEL / "deploy" / "systemd" / "sales-post-aufraeumen.service").read_text(encoding="utf-8")
    zeit = (WURZEL / "deploy" / "systemd" / "sales-post-aufraeumen.timer").read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/post-sitzungen-aufraeumen.sh" in dienst
    assert "User=debian" in dienst and "Type=oneshot" in dienst
    assert "OnCalendar=*:0/5" in zeit and "WantedBy=timers.target" in zeit
