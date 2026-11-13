#!/usr/bin/env bash
# Prueft den Compose-Dienst sales-auge (Beobachter "Laura (Bildschirm)",
# Bildauswertung live, Task 6) statisch: Dienst vorhanden, harte Grenzen,
# kein Port nach aussen, AUGE_URL an sales-ui und sales-mcp, Dockerfile.auge
# mit fest gepinnten Paketen. `docker compose config` laeuft zusaetzlich,
# wenn `docker compose` am Ort vorhanden ist (mit .env.example, nie mit einer
# echten .env); sonst wird dieser Teil uebersprungen (und gemeldet).
#
#   bash deploy/tests/test_auge_compose.sh
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$WURZEL/docker-compose.yml"
BEISPIEL="$WURZEL/.env.example"
DOCKERFILE="$WURZEL/sales-mcp/Dockerfile.auge"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

[ -f "$COMPOSE" ]    || fehler "docker-compose.yml fehlt"
[ -f "$BEISPIEL" ]   || fehler ".env.example fehlt"
[ -f "$DOCKERFILE" ] || fehler "sales-mcp/Dockerfile.auge fehlt"
[ -f "$WURZEL/sales-mcp/auge.py" ] || fehler "sales-mcp/auge.py fehlt"
[ -f "$WURZEL/sales-mcp/auge_jitsi.js" ] || fehler "sales-mcp/auge_jitsi.js fehlt"

# Kommentare und Leerzeilen weg (CR mit): geprueft wird nur, was Compose liest.
AKTIV="$(sed -e 's/\r$//' -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$COMPOSE")"

block() {
  echo "$AKTIV" | awk -v d="$1" '
    /^[^[:space:]]/ { in_services = ($0 == "services:") ; next }
    in_services && /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") ; next }
    in_services && aktiv { print }'
}

AUGE="$(block sales-auge)"
[ -n "$AUGE" ] || fehler "Dienst sales-auge fehlt"

hat() { echo "$AUGE" | grep -qE "$1" || fehler "sales-auge: $2"; }
hat '^    build:[[:space:]]*$'                                       "build: als Block fehlt"
hat '^      context:[[:space:]]*\./sales-mcp[[:space:]]*$'           "build.context ./sales-mcp fehlt"
hat '^      dockerfile:[[:space:]]*Dockerfile\.auge[[:space:]]*$'    "build.dockerfile Dockerfile.auge fehlt"
hat '^    image:[[:space:]]*sales-claw-sales-auge:local[[:space:]]*$' "eigener Image-Tag sales-claw-sales-auge:local fehlt"
hat '^    container_name:[[:space:]]*\$\{LADEN_PRAEFIX:-sales\}-auge[[:space:]]*$' "container_name \${LADEN_PRAEFIX:-sales}-auge fehlt"
hat '^    command:[[:space:]]*python auge\.py[[:space:]]*$'          "command: python auge.py fehlt"
hat '^    restart:[[:space:]]*unless-stopped[[:space:]]*$'           "restart: unless-stopped fehlt"
hat '^    cpus:[[:space:]]*"1\.5"[[:space:]]*$'                      'cpus: "1.5" fehlt'
hat '^    mem_limit:[[:space:]]*1536m[[:space:]]*$'                  "mem_limit: 1536m fehlt"
hat '^      <<:[[:space:]]*\*sales_mcp_umgebung[[:space:]]*$'        "Anker sales_mcp_umgebung fehlt"
hat '^      OLLAMA_URL:[[:space:]]*\$\{OLLAMA_URL:-\}[[:space:]]*$'  "OLLAMA_URL fehlt"
hat '^      AUGE_PORT:[[:space:]]*\$\{AUGE_PORT:-8790\}[[:space:]]*$' "AUGE_PORT (Vorgabe 8790) fehlt"
hat '^      AUGE_RUNDE_S:[[:space:]]*\$\{AUGE_RUNDE_S:-2\}[[:space:]]*$' "AUGE_RUNDE_S (Vorgabe 2) fehlt"
hat '^      KI_BILD_TIMEOUT_S:[[:space:]]*\$\{KI_BILD_TIMEOUT_S:-60\}[[:space:]]*$' "KI_BILD_TIMEOUT_S fehlt"
hat '^      JITSI_BASIS:'                                             "JITSI_BASIS fehlt (Link-Pruefung)"
hat '^      JITSI_HOSTS:'                                             "JITSI_HOSTS fehlt (Link-Pruefung)"
hat '^    logging:'                                                 "logging-Begrenzung fehlt"
for verboten in '^    ports:' '^    expose:' '^    network_mode:' '^    profiles:' '^    privileged:' \
                'docker\.sock' 'VEXA_API_KEY' 'CLAUDE_CODE_OAUTH_TOKEN' 'TELEGRAM_BOT_TOKEN'; do
  if echo "$AUGE" | grep -qE "$verboten"; then fehler "sales-auge: verboten gefunden: $verboten"; fi
done
# Keine Einhaengungen: Bilder gehen nur in die DB, nie auf Platte.
if echo "$AUGE" | grep -qE '^    volumes:'; then fehler "sales-auge: volumes: gesetzt"; fi

# AUGE_URL bei sales-ui (Listenform) und sales-mcp (Abbildung).
block sales-ui | grep -qE '^      - AUGE_URL=http://\$\{LADEN_PRAEFIX:-sales\}-auge:8790[[:space:]]*$' \
  || fehler "sales-ui: AUGE_URL fehlt"
block sales-mcp | grep -qE '^      AUGE_URL:[[:space:]]*http://\$\{LADEN_PRAEFIX:-sales\}-auge:8790[[:space:]]*$' \
  || fehler "sales-mcp: AUGE_URL fehlt"
# Das KI-Tor kennt dieselbe Zeitgrenze der Bild-Spur.
block sales-ki | grep -qE '^      KI_BILD_TIMEOUT_S:[[:space:]]*\$\{KI_BILD_TIMEOUT_S:-60\}[[:space:]]*$' \
  || fehler "sales-ki: KI_BILD_TIMEOUT_S fehlt"

# .env.example kennt die neuen Werte.
# (CR-tolerant: im Windows-Arbeitsstand traegt die Datei CRLF.)
BEISPIEL_LF="$(mktemp)"
trap 'rm -f "$BEISPIEL_LF"' EXIT
sed 's/\r$//' "$BEISPIEL" > "$BEISPIEL_LF"
for name in AUGE_PORT AUGE_RUNDE_S KI_BILD_TIMEOUT_S; do
  grep -qE "^$name=$" "$BEISPIEL_LF" || fehler ".env.example kennt $name nicht (leer)"
done

# Dockerfile.auge: Basis wie sales-mcp, gepinnte Pakete, Chromium, Modelle im Abbild.
DF="$(sed -e 's/\r$//' "$DOCKERFILE")"
echo "$DF" | grep -qE '^FROM python:3\.12-slim[[:space:]]*$'               || fehler "Dockerfile.auge: FROM python:3.12-slim fehlt"
echo "$DF" | grep -qE 'pip install .*-r requirements\.txt'                 || fehler "Dockerfile.auge: requirements.txt fehlt"
echo "$DF" | grep -qE 'pip install .*-r requirements-auge\.txt'            || fehler "Dockerfile.auge: requirements-auge.txt fehlt"
echo "$DF" | grep -qE 'playwright install --with-deps chromium'            || fehler "Dockerfile.auge: playwright install --with-deps chromium fehlt"
echo "$DF" | grep -qE 'FASTEMBED_CACHE_PATH'                               || fehler "Dockerfile.auge: Modell-Cache im Abbild fehlt"
echo "$DF" | grep -qE 'HF_HUB_OFFLINE=1'                                   || fehler "Dockerfile.auge: HF_HUB_OFFLINE=1 fehlt (kein Nachladen zur Laufzeit)"
if echo "$DF" | grep -qE '^EXPOSE'; then fehler "Dockerfile.auge: EXPOSE nicht noetig"; fi
REQ="$WURZEL/sales-mcp/requirements-auge.txt"
[ -f "$REQ" ] || fehler "sales-mcp/requirements-auge.txt fehlt"
for paket in playwright fastembed onnxruntime; do
  grep -qE "^$paket==[0-9][0-9.]*[[:space:]]*\$" <(sed 's/\r$//' "$REQ") || fehler "requirements-auge.txt: $paket nicht fest gepinnt"
done
if sed 's/\r$//' "$REQ" | grep -vE '^[[:space:]]*(#|$)' | grep -vqE '^[A-Za-z0-9_.-]+(\[[a-z,]+\])?==[0-9][0-9A-Za-z.]*[[:space:]]*$'; then
  fehler "requirements-auge.txt: jede Zeile muss name==version sein"
fi

# Seiten-Skript: nur Desktop-Tracks, keine Netz-/Ablage-Zugriffe.
JS="$WURZEL/sales-mcp/auge_jitsi.js"
grep -q "videoType === 'desktop'" "$JS" || fehler "auge_jitsi.js: Desktop-Filter fehlt"
for verboten in 'fetch(' 'XMLHttpRequest' 'localStorage' 'MediaRecorder'; do
  if grep -qF "$verboten" "$JS"; then fehler "auge_jitsi.js: $verboten"; fi
done

# Smoke-Liste und Laden-Parameter kennen den Container (sonst bricht update.sh ab).
grep -q '"sales-auge"' "$WURZEL/deploy/smoke.sh" || fehler "deploy/smoke.sh: sales-auge fehlt in erwartete_container"
grep -q '"sales-auge"' "$WURZEL/sales-mcp/tests/test_laden_parameter.py" || fehler "test_laden_parameter.py: sales-auge fehlt"
grep -qE '^KERN_OPTIONAL=".* sales-auge( |")' "$WURZEL/deploy/update.sh" || fehler "deploy/update.sh: sales-auge nicht in KERN_OPTIONAL"

# docker compose config nur, wenn es lokal laeuft (braucht keinen Daemon).
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  FEHLERTEXT="$(mktemp)"
  trap 'rm -f "$BEISPIEL_LF" "$FEHLERTEXT"' EXIT
  ausgabe="$(cd "$WURZEL" && docker compose -f "$COMPOSE" --env-file "$BEISPIEL_LF" config --format json 2>"$FEHLERTEXT")" \
    || fehler "docker compose config schlaegt fehl: $(grep -v 'variable is not set' "$FEHLERTEXT" | head -5)"
  for py in python3 python; do
    if "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
      echo "$ausgabe" | "$py" -c '
import json, sys
c = json.load(sys.stdin)["services"]
a = c["sales-auge"]
assert a["container_name"] == "sales-auge", a["container_name"]
assert not a.get("ports"), "sales-auge veroeffentlicht Ports"
assert float(a["cpus"]) == 1.5, a.get("cpus")
assert int(a["mem_limit"]) == 1536 * 1024 * 1024, a.get("mem_limit")
assert a["build"]["dockerfile"] == "Dockerfile.auge"
assert a["build"]["context"].replace("\\", "/").endswith("/sales-mcp")
e = a["environment"]
assert e["AUGE_PORT"] == "8790" and e["AUGE_RUNDE_S"] == "2" and e["KI_BILD_TIMEOUT_S"] == "60"
assert e["SALES_DB_SCHEMA"] == "sales"
for d in ("sales-ui", "sales-mcp"):
    assert c[d]["environment"]["AUGE_URL"] == "http://sales-auge:8790", d
' || fehler "gerenderte Compose-Konfiguration passt nicht"
      break
    fi
  done
  echo "OK: docker compose config gueltig"
else
  echo "HINWEIS: docker compose nicht vorhanden, config-Pruefung uebersprungen"
fi

echo "OK: auge-compose"
