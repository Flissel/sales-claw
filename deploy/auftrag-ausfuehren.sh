#!/usr/bin/env bash
# deploy/auftrag-ausfuehren.sh — Waechter des Auftrags-Spools.
# Von der systemd-path-Unit gestartet, sobald ein auftrag-*.json erscheint.
#
# Der Bot BESTELLT nur (sales-mcp: update_anfordern bzw.
# linkedin_versand_anfordern schreiben die Datei); ausgefuehrt wird HIER,
# auf dem Wirt. Der Waechter kennt GENAU ZWEI Auftragstypen:
#   update    -> deploy/update.sh (git pull, Staffelung, Abnahme, Rueckbau)
#   linkedin  -> Einmal-Versender mit GENAU der bestellten Entwurfs-Kennung
# Alles andere wird mit Ergebnis "abgelehnt" beantwortet — nie ausgefuehrt.
# Dateinamen tragen den Typ (auftrag-<typ>-<stempel>.json), Ergebnisse
# ebenso — die Ergebnis-Leser der Typen ueberdecken einander nie.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPOOL="$WURZEL/auftraege"
BETRIEB="${SALES_BETRIEB:-$HOME/sales-betrieb}"
FRIST_S=900   # aeltere Auftraege sind verfallen — niemand wartet mehr

mkdir -p "$BETRIEB"
shopt -s nullglob

ergebnis_schreiben() { # datei typ ergebnis hinweis
  printf '{"zeitpunkt":"%s","typ":"%s","ergebnis":"%s","hinweis":"%s"}\n' \
    "$(date -Is)" "$2" "$3" "$4" > "$1"
}

for auftrag in "$SPOOL"/auftrag-*.json; do
  stempel="$(date +%Y%m%d-%H%M%S)"
  name="$(basename "$auftrag")"
  # auftrag-<typ>-<stempel>.json — der Typ steht im Namen UND im Inhalt;
  # stimmen beide nicht ueberein, wird abgelehnt.
  typ_name="$(printf '%s' "$name" | cut -d- -f2)"
  typ_inhalt="$(grep -o '"typ"[[:space:]]*:[[:space:]]*"[a-z_]*"' "$auftrag" \
                | grep -o '[a-z_]*"$' | tr -d '"' || true)"
  draft_id="$(grep -o '"draft_id"[[:space:]]*:[[:space:]]*"[0-9a-f-]*"' "$auftrag" \
              | grep -oE '[0-9a-f-]{36}' || true)"
  alter=$(( $(date +%s) - $(stat -c %Y "$auftrag") ))
  ergebnis="$SPOOL/ergebnis-${typ_name}-$stempel.json"
  # Abgeholt ist abgeholt — egal, wie es ausgeht. Sonst wuerde ein
  # scheiternder Auftrag bei jedem Trigger erneut ausgefuehrt.
  rm -f "$auftrag"

  if [ "${typ_inhalt:-}" != "$typ_name" ]; then
    ergebnis_schreiben "$ergebnis" "${typ_name:-leer}" "abgelehnt" \
      "Typ im Namen (${typ_name:-leer}) und Inhalt (${typ_inhalt:-leer}) widersprechen sich"
    continue
  fi
  if [ "$alter" -gt "$FRIST_S" ]; then
    ergebnis_schreiben "$ergebnis" "$typ_name" "verfallen" \
      "Auftrag war aelter als $FRIST_S Sekunden"
    continue
  fi

  case "$typ_name" in
    update)
      if bash "$WURZEL/deploy/update.sh" >> "$BETRIEB/update-lauf.log" 2>&1; then
        :
      fi
      # update.sh schreibt seine Statusdatei in JEDEM Ausgang — sie IST
      # das Ergebnis.
      if [ -f "$BETRIEB/update-status.json" ]; then
        cp "$BETRIEB/update-status.json" "$ergebnis"
      else
        ergebnis_schreiben "$ergebnis" "update" "fehler" \
          "update.sh hinterliess keine Statusdatei"
      fi
      ;;
    linkedin)
      if ! printf '%s' "$draft_id" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; then
        ergebnis_schreiben "$ergebnis" "linkedin" "abgelehnt" \
          "draft_id ist keine UUID"
        continue
      fi
      # Einmal-Versender: exakt EINE Kennung, exit 0 heisst nur
      # "verarbeitet" — der wirkliche Ausgang steht in der Logzeile
      # "Ausgang: <wort>" (gemessen 27.08.2026). KEIN --remove-orphans.
      lauf_log="$BETRIEB/linkedin-lauf.log"
      ausgang="$(cd "$WURZEL" && docker compose --profile linkedin run --rm \
          -e LINKEDIN_DRAFT_ID="$draft_id" sales-linkedin 2>&1 \
          | tee -a "$lauf_log" \
          | grep -oE 'Ausgang: [a-z_]+' | tail -1 | cut -d' ' -f2 || true)"
      printf '{"zeitpunkt":"%s","typ":"linkedin","ergebnis":"%s","draft_id":"%s","hinweis":"%s"}\n' \
        "$(date -Is)" "${ausgang:-fehler}" "$draft_id" \
        "${ausgang:+Logzeile Ausgang gelesen}${ausgang:-keine Ausgang-Zeile im Log — Mensch pruefen}" \
        > "$ergebnis"
      ;;
  esac
done
