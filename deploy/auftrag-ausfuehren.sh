#!/usr/bin/env bash
# deploy/auftrag-ausfuehren.sh — Waechter des Auftrags-Spools.
# Von der systemd-path-Unit gestartet, sobald ein auftrag-*.json erscheint.
#
# Der Bot BESTELLT nur (sales-mcp: update_anfordern schreibt die Datei);
# ausgefuehrt wird HIER, auf dem Wirt. Der Waechter kennt genau EINEN
# Auftragstyp: update. Alles andere wird mit Ergebnis "abgelehnt"
# beantwortet — nie ausgefuehrt.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPOOL="$WURZEL/auftraege"
BETRIEB="${SALES_BETRIEB:-$HOME/sales-betrieb}"
FRIST_S=900   # aeltere Auftraege sind verfallen — niemand wartet mehr

mkdir -p "$BETRIEB"
shopt -s nullglob

for auftrag in "$SPOOL"/auftrag-*.json; do
  stempel="$(date +%Y%m%d-%H%M%S)"
  ergebnis="$SPOOL/ergebnis-$stempel.json"
  alter=$(( $(date +%s) - $(stat -c %Y "$auftrag") ))
  typ="$(grep -o '"typ"[[:space:]]*:[[:space:]]*"[a-z_]*"' "$auftrag" \
         | grep -o '[a-z_]*"$' | tr -d '"' || true)"
  # Abgeholt ist abgeholt — egal, wie es ausgeht. Sonst wuerde ein
  # scheiternder Auftrag bei jedem Trigger erneut ausgefuehrt.
  rm -f "$auftrag"

  if [ "${typ:-}" != "update" ]; then
    printf '{"zeitpunkt":"%s","typ":"%s","ergebnis":"abgelehnt","hinweis":"unbekannter Auftragstyp"}\n' \
      "$(date -Is)" "${typ:-leer}" > "$ergebnis"
    continue
  fi
  if [ "$alter" -gt "$FRIST_S" ]; then
    printf '{"zeitpunkt":"%s","typ":"update","ergebnis":"verfallen","hinweis":"Auftrag war aelter als %s Sekunden"}\n' \
      "$(date -Is)" "$FRIST_S" > "$ergebnis"
    continue
  fi

  if bash "$WURZEL/deploy/update.sh" >> "$BETRIEB/update-lauf.log" 2>&1; then
    :
  fi
  # update.sh schreibt seine Statusdatei in JEDEM Ausgang (eingespielt,
  # aktuell, rollback, notfall, fehler) — sie IST das Ergebnis.
  if [ -f "$BETRIEB/update-status.json" ]; then
    cp "$BETRIEB/update-status.json" "$ergebnis"
  else
    printf '{"zeitpunkt":"%s","typ":"update","ergebnis":"fehler","hinweis":"update.sh hinterliess keine Statusdatei"}\n' \
      "$(date -Is)" > "$ergebnis"
  fi
done
