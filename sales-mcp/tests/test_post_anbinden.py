"""Anbindung der Post-Sammelstelle (Task 10): reine Textpruefungen, keine DB.

Das Skript laeuft nur gegen echte Container; hier wird geprueft, dass es nichts
ausgibt, nichts startet, ohne Besitzer abbricht und die Saat den Agenten `post`
ohne Werkzeuge kennt.
"""
import json
import os
import re
import shutil
import subprocess
import sys
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
    assert "/home/node/.openclaw/agents/$AGENT/sessions" in code
    assert "-mmin +10" in code and "-delete" in code and "-type f" in code
    assert "agents/main" not in code and "agents/auto" not in code
    assert "-name '*.jsonl*'" in code
    # Index-Eintraege ohne Datei raeumt OpenClaw selbst weg (nur Agent post).
    assert 'sessions cleanup --agent "$AGENT" --fix-missing' in code
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
    assert 'model: { primary: "anthropic/claude-sonnet-5-5", fallbacks: [] }' in code
    assert "ohneModell" not in code and "OHNE Modell" not in code
    # Ein alter Eintrag ohne Modell zaehlt nicht als "schon da" - er wird ersetzt.
    assert code.count('config", "set", "agents.list"') == 1
    assert "neu[i] = s;" in code


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


def _saat():
    return json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))


def test_saat_kennt_pruefer_ohne_werkzeuge_ohne_rueckfall():
    """Task 6: der Pruefer liest dieselben Mails wie `post` - gleiche Regeln:
    keine Werkzeuge, eigenes Modell, [] ersetzt die Rueckfall-Vorgabe des Ladens."""
    c = _saat()
    agenten = {a["id"]: a for a in c["agents"]["list"]}
    pruefer = agenten["post-pruefer"]
    assert pruefer["tools"] == {"deny": ["*"]}
    assert pruefer["workspace"] == "/home/node/.openclaw/workspace-post-pruefer"
    assert pruefer["workspace"] != agenten["post"]["workspace"]
    assert pruefer["workspace"] != agenten["auto"]["workspace"]
    assert pruefer["model"] == {"primary": "anthropic/claude-sonnet-5-5", "fallbacks": []}
    ids = [a["id"] for a in c["agents"]["list"]]
    assert ids[0] == "main" and ids.index("post-pruefer") > ids.index("post")
    # Eigener Modelleintrag, wie bei claude-haiku-5-5.
    modelle = [m["id"] for m in c["models"]["providers"]["anthropic"]["models"]]
    assert "claude-sonnet-5-5" in modelle


def test_skript_traegt_beide_agenten_ein():
    """Ein unbekannter Gateway-Agent bekommt ALLE Werkzeuge: beide Agenten
    gehen in EINEM config set hinein, die Probe verlangt beide."""
    code = _code("deploy/post-anbinden.sh")
    assert '"post-pruefer"' in code
    assert code.count('deny: ["*"]') == 2
    assert code.count("fallbacks: []") >= 2
    assert "workspace-post-pruefer" in code
    assert code.count('config", "set", "agents.list"') == 1
    assert "openclaw/post-pruefer" in code and "openclaw/post" in code
    # Der Abbruch (exit 5) gilt weiter fuer beide - kein Eintrag ohne eigenes Modell.
    assert "process.exit(5)" in code
    # Die Probe darf `openclaw/post` nicht mit dem Praefix von `openclaw/post-pruefer` verwechseln.
    assert 'grep -w "openclaw/post"' not in code


def test_aufraeumen_kennt_beide_agenten():
    code = _code("deploy/post-sitzungen-aufraeumen.sh")
    assert "for AGENT in post post-pruefer" in code
    assert "agents/main" not in code and "agents/auto" not in code


_DOCKER_ATTRAPPE = """#!/usr/bin/env bash
# Attrappe: protokolliert jeden Aufruf; das Loeschen bei Agent post scheitert.
printf '%s\\n' "$*" >> "$PROTOKOLL"
case "$1" in
  inspect) echo running ;;
  exec)
    if [ "$3" = sh ]; then
      case "$5" in
        */agents/post/sessions*) echo "kaputt" >&2; exit 1 ;;
        *) echo 4 ;;
      esac
    fi ;;
esac
"""


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="braucht bash mit POSIX-Pfaden")
def test_aufraeumen_fehler_beim_ersten_agenten_ueberspringt_den_zweiten_nicht(tmp_path):
    """M2: unter `set -e` brach ein scheiterndes `docker exec` beim ersten Agenten die
    Schleife ab - die Sitzungskopien (mit Mailinhalt) des Pruefers blieben liegen."""
    attrappe = tmp_path / "docker"
    attrappe.write_text(_DOCKER_ATTRAPPE, encoding="utf-8")
    attrappe.chmod(0o755)
    protokoll = tmp_path / "protokoll"
    r = subprocess.run(
        ["bash", str(WURZEL / "deploy" / "post-sitzungen-aufraeumen.sh")],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
             "PROTOKOLL": str(protokoll)})
    aufrufe = protokoll.read_text(encoding="utf-8")
    assert "agents/post-pruefer/sessions" in aufrufe                 # zweiter Agent geloescht
    assert "cleanup --agent post " in aufrufe and "cleanup --agent post-pruefer " in aufrufe
    assert "post-Sitzungen: Loeschen fehlgeschlagen" in r.stdout
    assert "post-pruefer-Sitzungen: 4 Datei(en)" in r.stdout
    assert r.returncode == 1                                          # Fehler bleibt sichtbar
    assert "kaputt" not in r.stdout + r.stderr                        # nichts aus dem Container


def test_anbinden_funktionsprobe_an_den_pruefer():
    """M4: /v1/models zeigt nur den Eintrag. Erst ein echter Aufruf zeigt, ob das
    Gateway das Pruefer-Modell annimmt - mit Dummy-Text, Ausgabe nur ok/Fehlertyp."""
    code = _code("deploy/post-anbinden.sh")
    modelle = code.index('/v1/models"')
    probe = code.index("/v1/chat/completions")
    assert modelle < probe
    teil = code[code.index('PROBE="$(docker exec'):]
    assert teil.index("/v1/chat/completions") < 1000
    assert 'model: "openclaw/post-pruefer"' in teil
    assert '"x-openclaw-session-key": "agent:post-pruefer:' in teil
    assert '"x-openclaw-agent-id": "post-pruefer"' in teil
    assert "tool_choice" in teil and "keine Mail" in teil
    # Ausgabe: nur ok oder Fehlertyp - nie die Antwort, nie der Token.
    assert "console.log(s)" in teil and "JSON.stringify(d" not in teil
    assert "r.text()" not in teil and "e.message" not in teil[:teil.index("exit 6")]
    assert "gateway?.auth?.token" in teil and "TOKEN" not in code
    assert 'if [ "$PROBE" != "ok" ]' in teil and "exit 6" in teil
    # Die Probe steht vor dem Hinweis "Fertig" (ein rotes Ergebnis darf nicht gruen enden).
    assert probe < code.index('echo "Fertig.')


def test_runbook_v2_reihenfolge_migration_vor_update():
    """C1: neuer Code liest Spalten, die erst die Migration anlegt. Also: sales-post
    stoppen, Migration aus dem NEUEN Stand per `git show` (der Checkout darf nicht
    vorgezogen werden, sonst meldet update.sh "Bereits aktuell" und baut nichts),
    dann update.sh, dann post-anbinden.sh in der neuen Fassung (Migration noch
    einmal + Pruefer), erst danach sales-post starten."""
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    start = rb.index("Rollout v2")
    abschnitt = rb[start:rb.index("\nR13:", start)]
    stopp = abschnitt.index("compose stop sales-post")
    migration = abschnitt.index("git show origin/feat/stufe-1-fundament:db/post-sammelstelle.sql", stopp)
    update = abschnitt.index("bash deploy/update.sh", migration)
    anbinden = abschnitt.index("bash deploy/post-anbinden.sh", update)
    start_post = abschnitt.index("up -d sales-post", anbinden)
    vorschau = abschnitt.index("post-neu-einordnen.sh [laden] vorschau")
    assert abschnitt.index("POST_KONTEXT") < stopp < migration < update < anbinden < start_post < vorschau
    # Den Checkout vor update.sh von Hand vorzuziehen, waere die Falle selbst.
    assert "git merge" not in abschnitt[:update] and "git pull" not in abschnitt[:update]
    assert "bash deploy/post-neu-einordnen.sh [laden] anwenden" in abschnitt
    assert "Task 7" not in abschnitt and "Aufruf laut Skript-Hilfe" not in abschnitt


def test_pruefer_id_im_code_gleich_saat():
    """Tippfehler in der ID legte im Gateway einen Agenten mit allen Werkzeugen an."""
    import sys
    sys.path.insert(0, str(WURZEL / "sales-mcp"))
    import post_einordnung
    ids = {a["id"] for a in _saat()["agents"]["list"]}
    assert post_einordnung.PRUEFER in ids and post_einordnung.AGENT in ids
    code = _code("deploy/post-anbinden.sh")
    assert f'"{post_einordnung.PRUEFER}"' in code


def test_runbook_beschreibt_v2_ausrollen():
    rb = (WURZEL / "docs" / "03_RUNBOOK.md").read_text(encoding="utf-8")
    abschnitt = rb[rb.index("## Post-Sammelstelle"):]
    for stichwort in ("post-pruefer", "POST_KONTEXT", "post-neu-einordnen.sh", "vorschau"):
        assert stichwort in abschnitt
