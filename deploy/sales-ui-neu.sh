#!/usr/bin/env bash
# deploy/sales-ui-neu.sh — erzeugt die sales-ui des BASIS-Ladens neu, ohne das Portal-Fenster zu verlieren.
#
#   bash deploy/sales-ui-neu.sh
#
# WARUM: Das Netz bewerbung-fenster haengt nur mit `-f docker-compose.yml -f docker-compose.fenster.yml` an der
# Basis-sales-ui. Ein schlichtes `docker compose up -d [--force-recreate] sales-ui` erzeugt den Container wegen des
# anderen Config-Hashes ohne das Netz neu - das Fenster ist dann still weg, bis zum naechsten update.sh.
# Dieses Skript legt das Netz an (deploy/fenster-netz-anlegen.sh; Fehlschlag ist nicht tragisch: dann ohne
# Override, also ohne Fenster) und nimmt den Override nur mit Netz UND vorhandener Datei dazu. Nur Basis-Laden;
# zweite Laeden behalten ihren Befehl mit --env-file (nie mit Override).
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

DATEIEN=(-f docker-compose.yml)
if bash deploy/fenster-netz-anlegen.sh && [ -f docker-compose.fenster.yml ]; then
  DATEIEN+=(-f docker-compose.fenster.yml)
else
  echo "HINWEIS: ohne Netz bewerbung-fenster bzw. ohne docker-compose.fenster.yml - sales-ui startet ohne Portal-Fenster." >&2
fi
docker compose "${DATEIEN[@]}" up -d --no-deps --force-recreate sales-ui
