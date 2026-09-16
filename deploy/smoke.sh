#!/usr/bin/env bash
# deploy/smoke.sh — Abnahme des laufenden Stacks. NUR Lesezugriffe.
# Jede Pruefung entspricht einer am 26.08.2026 gemessenen Diagnose.
# Exit 0 = gesund, sonst Anzahl roter Pruefungen.
#
# Laeuft identisch auf dem PC (Git Bash) und auf der VM: nur Docker-CLI,
# curl und grep. Die UI-Adresse kommt aus UI_TAILSCALE_IP in der .env —
# es wird NUR diese eine Variable extrahiert, nie die Datei angezeigt.
set -uo pipefail

ROT=0
melde() { printf '%-32s %s\n' "$1" "$2"; }
fehl()  { melde "$1" "ROT: $2"; ROT=$((ROT+1)); }
gut()   { melde "$1" "ok"; }

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIND="$(grep -E '^UI_TAILSCALE_IP=' "$WURZEL/.env" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
BIND="${BIND:-127.0.0.1}"

# 1) Container laufen.
for c in sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw openwa; do
  z="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo fehlt)"
  [ "$z" = "running" ] && gut "container $c" || fehl "container $c" "$z"
done

# 2) Oberflaeche antwortet. Gemessen 27.08.2026: auf Docker-Desktop/Windows
# ist die Bindung an die Tailscale-IP vom eigenen Rechner aus NICHT
# erreichbar (Timeout trotz sichtbarem Mapping) — Loopback ist deshalb die
# verlaessliche Innenpruefung auf beiden Plattformen. Ob die Tailscale-
# Adresse von aussen traegt, prueft einmalig ein Geraet im Tailnet.
code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:8791/" || true)"
if [ "$code" = "200" ]; then
  gut "ui http"
elif [ "$code" = "303" ]; then
  # Anmeldung scharf (E1): / leitet Unangemeldete auf /login — gesund ist
  # das nur, wenn die Anmeldeseite selbst antwortet.
  login="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:8791/login" || true)"
  [ "$login" = "200" ] && gut "ui http" || fehl "ui http" "/login HTTP ${login:-000}"
else
  fehl "ui http" "HTTP ${code:-000} an 127.0.0.1"
fi

# 3) Datenbank erreichbar (Produktionsschema, reine Leseabfrage).
if docker exec -e SALES_DB_SCHEMA=sales sales-mcp python -c \
  "import sys;sys.path.insert(0,'/app');import server;server._q('select 1')" \
  >/dev/null 2>&1; then gut "datenbank"; else fehl "datenbank" "select 1 scheitert"; fi

# 4) Gateway kennt BEIDE MCP-Server UND hatte juengst keinen Startfehler.
# Seit 01.09.2026 zwei Server: `sales` (Werkzeugdienst des Hauses) und
# `rowboat` (VibeMind-Wissensbasis, angebunden per deploy/rowboat-anbinden.sh
# — die Saat kennt den Eintrag, der Schluessel kommt erst durch das Skript;
# fehlt er, faellt genau diese Pruefung, und das ist gewollt).
# grep hier NIE mit -q: -q beendet beim ersten Treffer, docker bekommt
# EPIPE, und pipefail macht daraus ein falsches ROT (gemessen 27.08.2026).
mcp_liste="$(docker exec sales-claw sh -c "openclaw mcp list --json 2>/dev/null" || true)"
for server in sales rowboat; do
  if printf '%s' "$mcp_liste" | grep "\"$server\"" >/dev/null; then
    gut "mcp $server"
  else
    fehl "mcp $server" "'$server' fehlt in mcp list"
  fi
done
if docker logs --since 10m sales-claw 2>&1 | grep -i "failed to start server" >/dev/null; then
  fehl "mcp verbindung" "Startfehler in den letzten 10 Min."
else
  gut "mcp verbindung"
fi

# 5) OpenWA-Session ist ready (der Weg zum Kunden).
s="$(docker exec sales-dispatch python -c "import os,json,urllib.request as u;q=u.Request(os.environ['OPENWA_URL']+'/api/sessions',headers={'X-Api-Key':os.environ['OPENWA_API_KEY']});print(json.loads(u.urlopen(q,timeout=20).read())[0]['status'])" 2>/dev/null || echo unerreichbar)"
[ "$s" = "ready" ] && gut "openwa session" || fehl "openwa session" "$s"

# 6) OpenClaw-Kanal: keine Abmeldung in den letzten 10 Minuten.
if docker logs --since 10m sales-claw 2>&1 | grep -i "session logged out" >/dev/null; then
  fehl "whatsapp kanal" "Abmeldung in den letzten 10 Min."
else
  gut "whatsapp kanal"
fi

# 7) Der zusammengelegte Cron-Job ist aktiv (cron list zeigt nur aktive Jobs).
if docker exec sales-claw sh -c "openclaw cron list 2>/dev/null" | grep "antworten-pruefen" >/dev/null; then
  gut "cron antworten-pruefen"
else
  fehl "cron antworten-pruefen" "nicht in der aktiven Liste"
fi

# 8+9) Die Bootstrap-Dateien passen in IHRE BEIDEN Grenzen.
#
# Die Falle ist die stille Kuerzung: OpenClaw schneidet zu grosse Dateien
# beim Einspritzen ab und meldet das nur im JSON-Bericht eines Laufs
# (bootstrapTruncation), nicht im Log. Am 22.08.2026 blieben so von 47000
# Zeichen nur 19184 uebrig — abgeschnitten wurde alles ab "Kundenchats",
# DARUNTER "Verbote - ohne Ausnahme". Der Agent kannte seine eigenen
# absoluten Verbote nicht.
#
# Bis 31.08. pruefte diese Stelle NUR AGENTS.md gegen NUR bootstrapMaxChars.
# Zwei Luecken, beide gemessen:
#
#   a) Gebootstrappt wird mehr als AGENTS.md — laut OpenClaw-Doku
#      (concepts/agent-workspace) auch HEARTBEAT.md, BOOT.md, BOOTSTRAP.md,
#      MEMORY.md, skills/ und memory/JJJJ-MM-TT.md. Der Tagesspeicher waechst
#      von selbst; niemand fasst dafuer AGENTS.md an.
#   b) Es gibt ZWEI Grenzen. bootstrapTotalMaxChars galt bisher ungeprueft.
#      Gemessen 31.08.2026 in der Saat: 66164 Zeichen gesamt gegen 150000 —
#      viel Luft, aber sie schrumpft mit jedem Tagesspeicher.
#
# Geprueft wird der LAUFZEIT-Workspace im Container, nicht die Saat: dort
# liegen memory/ und die uebernommenen Skills.
lese="$(docker exec sales-claw sh -c '
  cd /home/node/.openclaw/workspace 2>/dev/null || { echo KEINWS; exit 0; }
  gesamt=0; groesste=0; gname=""
  for f in $(ls -1 AGENTS.md HEARTBEAT.md BOOT.md BOOTSTRAP.md MEMORY.md 2>/dev/null; \
             find skills memory -name "*.md" 2>/dev/null); do
    n=$(wc -c < "$f" | tr -d "[:space:]")
    gesamt=$((gesamt+n))
    if [ "$n" -gt "$groesste" ]; then groesste=$n; gname=$f; fi
  done
  echo "$gesamt $groesste ${gname:-–}"' 2>/dev/null)"

je_max="$(docker exec sales-claw sh -c "openclaw config get agents.defaults.bootstrapMaxChars 2>/dev/null" | grep -oE '[0-9]+' | head -1)"
ges_max="$(docker exec sales-claw sh -c "openclaw config get agents.defaults.bootstrapTotalMaxChars 2>/dev/null" | grep -oE '[0-9]+' | head -1)"
ges="$(echo "$lese" | awk '{print $1}')"
gr="$(echo "$lese"  | awk '{print $2}')"
gname="$(echo "$lese" | awk '{print $3}')"

if [ "$lese" = "KEINWS" ] || [ -z "${ges:-}" ]; then
  fehl "bootstrap je datei" "Workspace im Container nicht lesbar"
  fehl "bootstrap gesamt"   "Workspace im Container nicht lesbar"
else
  # 8) Groesste Einzeldatei gegen bootstrapMaxChars.
  if [ -n "${je_max:-}" ] && [ "$gr" -gt "$je_max" ] 2>/dev/null; then
    fehl "bootstrap je datei" "$gname $gr Zeichen > bootstrapMaxChars $je_max — wird still gekuerzt"
  else
    gut "bootstrap je datei"
  fi
  # 9) Summe aller Bootstrap-Dateien gegen bootstrapTotalMaxChars.
  if [ -n "${ges_max:-}" ] && [ "$ges" -gt "$ges_max" ] 2>/dev/null; then
    fehl "bootstrap gesamt" "$ges Zeichen > bootstrapTotalMaxChars $ges_max — wird still gekuerzt"
  else
    gut "bootstrap gesamt"
  fi
fi

# 10) Compose-Aufloesung: der Instanzname ist seit 16.09.2026 ein Parameter
# (Plan 2026-09-16-zweiter-laden-getrennt, T1). Dieselbe Behauptung wie in
# sales-mcp/tests/test_laden_parameter.py (das bleibt die Pruefung fuer
# Entwicklungsrechner), hier aber OHNE pytest und ohne `python`: auf der VM
# ist kein pytest installiert und es gibt dort nur `python3`, kein `python`
# (Befund Koordinator, 16.09.2026, gemessen per `python3 -c "import pytest"`
# -> ModuleNotFoundError). Ein pytest-Aufruf haette hier IMMER Exit!=0
# geliefert und ueber sales-wache.timer alle zwei Stunden einen Fehlalarm
# ausgeloest, ohne dass etwas kaputt war. Dieser Abschnitt braucht deshalb
# nur, was auf der VM tatsaechlich vorhanden ist: docker und python3 mit
# der Standardbibliothek (json, os, subprocess) — kein pip-Paket, keine
# Datei aus sales-mcp/tests/.
# Ans Ende dieser Datei gehaengt statt hinter das bestehende `exit "$ROT"`
# (das haette den Aufruf nie erreicht) und ueber fehl/gut/ROT eingebunden,
# damit ein rotes Ergebnis auch im Exit-Code dieses Skripts ankommt, statt
# die uebrigen Pruefungen darunter stumm abzuschneiden.
echo "== Compose-Aufloesung =="
compose_out="$(python3 - "$WURZEL" <<'PYEOF' 2>&1
import json
import os
import subprocess
import sys

wurzel = sys.argv[1]

# Dieselben sechs Variablen wie in sales-mcp/tests/test_laden_parameter.py:
# aus der eigenen Umgebung entfernen, bevor gezielt ueberschrieben wird —
# sonst faelscht ein auf der VM zufaellig gesetztes LADEN_PRAEFIX das
# Ergebnis, und die Pruefung waere gruen, ohne etwas zu pruefen.
LADEN_VARIABLEN = ("LADEN_PRAEFIX", "LADEN_PROJEKT", "PORT_GATEWAY",
                    "PORT_UI", "PORT_OPENWA", "UI_TAILSCALE_IP")


def aufgeloest(datei, umgebung=None):
    basis = dict(os.environ)
    for k in LADEN_VARIABLEN:
        basis.pop(k, None)
    roh = subprocess.run(
        ["docker", "compose", "-f", datei, "config", "--format", "json"],
        cwd=wurzel, capture_output=True, text=True,
        env={**basis, **(umgebung or {})})
    if roh.returncode != 0:
        raise SystemExit(
            "docker compose config (%s) Exit %d: %s"
            % (datei, roh.returncode, roh.stderr))
    return json.loads(roh.stdout)


def hostports(dienst):
    return {"%s:%s" % (p.get("host_ip", ""), p["published"])
            for p in dienst.get("ports", [])}


# 1) Der bestehende Laden bleibt ohne gesetzte Variablen unveraendert.
erst = aufgeloest("docker-compose.yml")
assert erst["name"] == "sales-claw", erst["name"]
erwartete_container = {
    "sales-claw", "sales-mcp", "sales-dispatch", "sales-inbox",
    "sales-mail", "sales-telegram", "sales-linkedin", "sales-auto",
    "sales-stt", "sales-ui"}
ist = {d["container_name"] for d in erst["services"].values()}
assert ist == erwartete_container, ist
istv = {v["name"] for v in erst["volumes"].values()}
assert istv == {"sales-claw-state", "sales-claw-keys",
                 "sales-sprachnachrichten", "sales-stt-modelle"}, istv
assert hostports(erst["services"]["sales-claw"]) == {"127.0.0.1:18894"}, \
    hostports(erst["services"]["sales-claw"])
assert hostports(erst["services"]["sales-ui"]) == {"127.0.0.1:8791"}, \
    hostports(erst["services"]["sales-ui"])

# 2) Dasselbe fuer openwa.
erst_wa = aufgeloest("docker-compose.openwa.yml")
assert erst_wa["name"] == "sales-claw", erst_wa["name"]
assert erst_wa["services"]["openwa"]["container_name"] == "sales-openwa", \
    erst_wa["services"]["openwa"]["container_name"]
istv_wa = {v["name"] for v in erst_wa["volumes"].values()}
assert istv_wa == {"sales-openwa-data"}, istv_wa
assert hostports(erst_wa["services"]["openwa"]) == {"127.0.0.1:12785"}, \
    hostports(erst_wa["services"]["openwa"])

# 3) Ein zweiter Laden kollidiert in nichts.
u = {"LADEN_PRAEFIX": "ivan", "LADEN_PROJEKT": "ivan-claw",
     "PORT_GATEWAY": "18895", "PORT_UI": "8792", "PORT_OPENWA": "12786"}
zweit = aufgeloest("docker-compose.yml", u)
zweit_wa = aufgeloest("docker-compose.openwa.yml", u)
assert zweit["name"] == "ivan-claw", zweit["name"]


def namen(c):
    return {d["container_name"] for d in c["services"].values()}


def volumes(c):
    return {v["name"] for v in c["volumes"].values()}


def ports(c):
    return {p for d in c["services"].values() for p in hostports(d)}


ueberschneidung_namen = (namen(erst) | namen(erst_wa)) & (namen(zweit) | namen(zweit_wa))
assert not ueberschneidung_namen, ueberschneidung_namen
ueberschneidung_ports1 = ports(erst) & ports(zweit)
assert not ueberschneidung_ports1, ueberschneidung_ports1
ueberschneidung_ports2 = ports(erst_wa) & ports(zweit_wa)
assert not ueberschneidung_ports2, ueberschneidung_ports2

# sales-stt-modelle ist die AUSNAHME: geteilt, nicht vervielfacht.
gemeinsam = volumes(erst) & volumes(zweit)
assert gemeinsam == {"sales-stt-modelle"}, gemeinsam

print("compose-aufloesung ok")
PYEOF
)"
if [ $? -eq 0 ]; then
  gut "compose parameter"
else
  fehl "compose parameter" "loest nicht wie erwartet auf: $(echo "$compose_out" | tail -3)"
fi

echo "---"
if [ "$ROT" -eq 0 ]; then echo "ALLE PRUEFUNGEN GRUEN"; else echo "$ROT PRUEFUNG(EN) ROT"; fi
exit "$ROT"
