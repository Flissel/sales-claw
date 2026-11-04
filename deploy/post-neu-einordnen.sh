#!/usr/bin/env bash
# deploy/post-neu-einordnen.sh — Neu-Sortierung des Post-Altbestands (Plan
# Post-Einordnung v2, Task 7) im Container sales-post des Ladens.
#
#   bash deploy/post-neu-einordnen.sh vorschau [--alle] [--grenze N]   # Basis-Laden
#   bash deploy/post-neu-einordnen.sh bericht
#   bash deploy/post-neu-einordnen.sh anwenden
#   bash deploy/post-neu-einordnen.sh ivan vorschau                    # Laden ivan
#
# Reihenfolge: vorschau (echte Spalten bleiben unberuehrt, Modellaufrufe zaehlen
# zur Tagesgrenze) -> bericht (nur Zahlen und Domains) -> anwenden (ohne Modell).
# Mail-Inhalte erscheinen nirgends in der Ausgabe. Startet keinen Container.
set +x
set -euo pipefail
export LC_ALL=C

case "${1:-}" in
  vorschau|bericht|anwenden) PRAEFIX=sales ;;     # kein Laden-Argument: Basis-Laden
  "") echo "Aufruf: $0 [laden-praefix] vorschau [--alle] | bericht | anwenden" >&2; exit 2 ;;
  *) PRAEFIX="$1"; shift ;;
esac
if ! [[ $PRAEFIX =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "Aufruf: $0 [laden-praefix] vorschau [--alle] | bericht | anwenden" >&2; exit 2
fi
CONTAINER="${PRAEFIX}-post"

if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo fehlt)" != "running" ]; then
  echo "post-neu-einordnen: $CONTAINER laeuft nicht." >&2; exit 1
fi
exec docker exec "$CONTAINER" python -m post_neu_einordnen "$@"
