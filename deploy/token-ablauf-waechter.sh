#!/usr/bin/env bash
# Meldet per Telegram, wann der Tailscale-API-Token fuer "Team-Mitglied
# einladen" (tailscale-admin.env) erneuert werden muss: 5 bis 1 Tag(e)
# vorher und am Ablauftag; danach taeglich, solange der eingetragene Token
# ungueltig ist.
#
# Laeuft ueber deploy/systemd/sales-token-waechter.timer taeglich 09:00.
# Das Ablaufdatum wird bei JEDEM Lauf frisch aus der Tailscale-API gelesen:
# steht nach dem Erneuern ein neuer Token in tailscale-admin.env, gilt
# automatisch dessen Datum — alle 90 Tage muss nichts neu eingerichtet werden.
#
# `--probe`: schickt unabhaengig vom Datum eine Nachricht (Test des Wegs).
set -Eeuo pipefail
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

PROBE=0
if [ "${1:-}" = "--probe" ]; then
  PROBE=1
fi

# Nur diese eine Zeile aus der Compose-.env — die ganze Datei per
# EnvironmentFile= zu laden hiesse, jedes Geheimnis des Ladens in diesen
# Dienst zu holen.
BOT_TOKEN="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' .env | head -1 | tr -d '\r"')"
if [ -z "$BOT_TOKEN" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "FEHLER: TELEGRAM_BOT_TOKEN (.env) oder TELEGRAM_CHAT_ID" \
       "(tailscale-admin.env) fehlt — der Waechter kann niemanden erreichen." >&2
  exit 1
fi

telegram() {
  # Der Bot-Token steckt in der URL — deshalb ueber `curl -K -` per stdin,
  # nie als Argument (sonst in ps//proc sichtbar; dieselbe Leck-Klasse wie
  # beim Einladen, siehe admin-auftrag-ausfuehren.sh).
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$BOT_TOKEN" \
    | curl -sS --max-time 15 -K - -o /dev/null -w '%{http_code}' \
        --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
        --data-urlencode "text=$1"
}

# Oeffentliche Schluessel-ID aus dem Token (tskey-api-<id>-<geheim>) — kein
# Geheimnis, sie steht so auch in der Tailscale-Verwaltung.
KEY_ID=""
HTTP_CODE="kein-token"
RUMPF=""
if [ -n "${TAILSCALE_API_KEY:-}" ]; then
  KEY_ID="${TAILSCALE_API_KEY#tskey-api-}"
  KEY_ID="${KEY_ID%%-*}"
  ANTWORT="$(printf 'header = "Authorization: Bearer %s"\n' "$TAILSCALE_API_KEY" \
    | curl -sS --max-time 15 -K - \
        "https://api.tailscale.com/api/v2/tailnet/${TAILSCALE_TAILNET:--}/keys?all=true" \
        -w $'\n%{http_code}')" || ANTWORT=$'\n000'
  HTTP_CODE="${ANTWORT##*$'\n'}"
  RUMPF="${ANTWORT%$'\n'*}"
fi

NACHRICHT="$(HTTP_CODE="$HTTP_CODE" RUMPF="$RUMPF" KEY_ID="$KEY_ID" \
  PROBE="$PROBE" python3 - <<'PY'
import datetime, json, os, zoneinfo

code, rumpf = os.environ["HTTP_CODE"], os.environ["RUMPF"]
key_id, probe = os.environ["KEY_ID"], os.environ["PROBE"] == "1"
KOPF = "Tailscale-Token für „Team-Mitglied einladen“ (sales-claw)"
SCHRITTE = (
    "\n\nNeu setzen:\n"
    "1. Tailscale-Verwaltung → Settings → Keys → API access tokens → Generate\n"
    "2. VM: ~/sales-claw/tailscale-admin.env, Zeile TAILSCALE_API_KEY= ersetzen"
    " (kein Neustart nötig)\n"
    "3. Credential-System bzw. lokale .env (TAILNET_API_KEY) nachziehen\n"
    "4. Alten Token in der Tailscale-Verwaltung widerrufen")

def melden(text):
    print(text)
    raise SystemExit

if code == "kein-token":
    melden(f"{KOPF}: in tailscale-admin.env ist kein Token eingetragen." + SCHRITTE)
if code in ("401", "403"):
    melden(f"{KOPF} ist abgelaufen oder widerrufen — Einladungen scheitern gerade."
           + SCHRITTE)
if not code.startswith("2"):
    melden(f"{KOPF}: Ablaufdatum heute nicht prüfbar (HTTP {code}). "
           "Der Wächter versucht es morgen wieder.")
try:
    schluessel = json.loads(rumpf).get("keys", [])
except (ValueError, AttributeError):
    melden(f"{KOPF}: Antwort der Tailscale-API unlesbar — Ablauf nicht prüfbar.")
treffer = [k for k in schluessel if isinstance(k, dict)
           and str(k.get("id", "")).startswith(key_id)]
if not key_id or not treffer or not treffer[0].get("expires"):
    melden(f"{KOPF}: der eingetragene Token steht nicht in der Schlüsselliste — "
           "Ablauf nicht prüfbar.")

ablauf = datetime.datetime.fromisoformat(treffer[0]["expires"].replace("Z", "+00:00"))
tage = (ablauf - datetime.datetime.now(datetime.timezone.utc)).days
wann_lokal = ablauf.astimezone(zoneinfo.ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
if tage < 0:
    melden(f"{KOPF} ist am {wann_lokal} abgelaufen." + SCHRITTE)
if tage <= 5:
    wann = {0: "heute", 1: "morgen"}.get(tage, f"in {tage} Tagen")
    melden(f"{KOPF} läuft {wann} ab ({wann_lokal})." + SCHRITTE)
if probe:
    melden(f"Probe: {KOPF} läuft in {tage} Tagen ab ({wann_lokal}). "
           "Erinnerungen kommen 5 bis 1 Tag vorher, jeweils um 9 Uhr.")
PY
)"

if [ -n "$NACHRICHT" ]; then
  CODE="$(telegram "$NACHRICHT")"
  if [ "$CODE" != "200" ]; then
    echo "FEHLER: Telegram antwortete HTTP $CODE — Erinnerung nicht zugestellt." >&2
    exit 1
  fi
  echo "gemeldet: ${NACHRICHT%%$'\n'*}"
else
  echo "nichts zu melden (Ablauf mehr als 5 Tage entfernt)"
fi
