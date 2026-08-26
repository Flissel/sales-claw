#!/usr/bin/env bash
# deploy/wiederherstellen.sh <sicherungsordner> — stellt die drei
# Zustands-Volumes aus einer Sicherung her, nach Pruefsummen-Kontrolle.
#
# Verweigert die Arbeit, solange openwa oder sales-claw laufen: eine
# Wiederherstellung unter laufendem Betrieb hinterlaesst genau die halb
# geschriebenen Profile, gegen die sie helfen soll.
set -euo pipefail

QUELLE="${1:?Aufruf: wiederherstellen.sh <sicherungsordner>}"
VOLUMES="openwa-data sales-claw-state sales-claw-keys"

for c in openwa sales-claw; do
  if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || true)" = "running" ]; then
    echo "ABBRUCH: $c laeuft. Erst stoppen: docker stop openwa sales-claw" >&2
    exit 1
  fi
done

( cd "$QUELLE" && sha256sum -c MANIFEST.sha256 )

for vol in $VOLUMES; do
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/ziel -v "$QUELLE":/quelle:ro alpine \
    sh -c "find /ziel -mindepth 1 -delete && tar xzf /quelle/$vol.tar.gz -C /ziel"
done

echo "Wiederhergestellt aus $QUELLE."
echo "Naechster Schritt: Dienste in der Cutover-Reihenfolge starten"
echo "(docs/04_BETRIEB_MINIPC.md)."
