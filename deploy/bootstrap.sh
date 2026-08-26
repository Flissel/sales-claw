#!/usr/bin/env bash
# deploy/bootstrap.sh — von frischem Checkout zu laufendem Grundstack.
# Startet BEWUSST nur sales-mcp und sales-ui: alles mit Nebenwirkungen
# (openwa, sales-claw, inbox, dispatch, mail) kommt erst im Cutover, damit
# niemals zwei Standorte gleichzeitig Kundennachrichten verarbeiten.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

for werkzeug in docker git curl; do
  command -v "$werkzeug" >/dev/null || { echo "FEHLT: $werkzeug" >&2; exit 1; }
done
docker compose version >/dev/null || { echo "FEHLT: docker compose v2" >&2; exit 1; }

if [ ! -f .env ]; then
  echo "FEHLT: $WURZEL/.env — vom alten Standort per scp holen (nie per Git)." >&2
  echo "Noetig sind mindestens: SALES_DB_URL, OPENWA_API_KEY, OPENWA_SESSION_ID," >&2
  echo "INBOX_WEBHOOK_SECRET, UI_TAILSCALE_IP (Tailscale-IP DIESER Maschine)." >&2
  exit 1
fi

docker volume create openwa-data >/dev/null
docker volume create sales-claw-state >/dev/null
docker volume create sales-claw-keys >/dev/null

docker compose build sales-mcp
docker compose -f docker-compose.openwa.yml build openwa
docker compose up -d sales-mcp sales-ui

echo "Grundstack laeuft. Naechste Schritte:"
echo "  1. Zustand einspielen:  deploy/wiederherstellen.sh <sicherung>"
echo "  2. Cutover-Reihenfolge: docs/04_BETRIEB_MINIPC.md"
