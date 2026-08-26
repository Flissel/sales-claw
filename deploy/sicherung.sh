#!/usr/bin/env bash
# deploy/sicherung.sh [zielordner] — sichert die drei Zustands-Volumes als
# tar.gz mit Pruefsummen-Manifest. Rotation: die juengsten 7 bleiben.
#
# openwa wird fuer die Dauer der Sicherung gestoppt: ein live getartes
# Chromium-Profil ist genau die Beschaedigungsklasse, die am 26.08.2026 die
# WhatsApp-Session gekostet hat. sales-claw-state wird live gesichert
# (kleine JSON/SQLite-Dateien, vertretbares Risiko, kein Kanal-Ausfall).
set -euo pipefail

ZIEL="${1:-${SALES_BETRIEB:-$HOME/sales-betrieb}/sicherungen}"
STEMPEL="$(date +%Y%m%d-%H%M%S)"
ORDNER="$ZIEL/$STEMPEL"
VOLUMES="openwa-data sales-claw-state sales-claw-keys"

mkdir -p "$ORDNER"

OPENWA_LIEF=false
if [ "$(docker inspect -f '{{.State.Status}}' openwa 2>/dev/null || true)" = "running" ]; then
  OPENWA_LIEF=true
  docker stop openwa >/dev/null
fi
# openwa kommt am Ende IMMER wieder hoch, auch wenn tar scheitert.
trap '$OPENWA_LIEF && docker start openwa >/dev/null' EXIT

for vol in $VOLUMES; do
  docker run --rm -v "$vol":/quelle:ro -v "$ORDNER":/ziel alpine \
    tar czf "/ziel/$vol.tar.gz" -C /quelle .
done
( cd "$ORDNER" && sha256sum ./*.tar.gz > MANIFEST.sha256 )

# Rotation: alles ausser den juengsten 7 Sicherungen entfernen.
ls -1dt "$ZIEL"/*/ | tail -n +8 | xargs -r rm -rf

echo "Sicherung: $ORDNER"
ls -lh "$ORDNER"
