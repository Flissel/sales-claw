#!/usr/bin/env bash
# Prueft den Mitschriften-Ordner je Laden (Mitschriften-Ablage, 14.11.2026)
# ohne Docker-Start: Compose haengt /mitschriften an sales-termine und
# sales-ui ein (beschreibbar), update.sh weist Laeden ohne eigenen oder mit
# geteiltem Ordner ab, laden-anlegen.sh und beispiel.env schreiben die Zeile,
# sicherung.sh sichert den Ordner, wiederherstellen.sh stellt ihn her.
# `docker compose config` laeuft nur, wenn `docker compose` am Ort vorhanden
# ist (mit .env.example, nie mit einer echten .env); sonst wird dieser Teil
# uebersprungen (und gemeldet). update.sh laeuft in einer Wegwerf-Kopie
# (WURZEL = Elternordner des Skripts) mit einer Attrappe fuer flock.
#
#   bash deploy/tests/test_mitschriften_ordner.sh
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$WURZEL/docker-compose.yml"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

fehler() { echo "FEHLER: $*" >&2; exit 1; }

# --- Compose ----------------------------------------------------------------
# Statisch (CR-tolerant): Umgebungsvariable und Einhaengung je Dienst.
AKTIV="$(sed -e 's/\r$//' -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$COMPOSE")"
block() {
  echo "$AKTIV" | awk -v d="$1" '
    /^[^[:space:]]/ { in_services = ($0 == "services:") ; next }
    in_services && /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") ; next }
    in_services && aktiv { print }'
}
for d in sales-termine sales-ui; do
  b="$(block "$d")"
  echo "$b" | grep -qE '^      (- )?MITSCHRIFTEN_PFAD[=:][[:space:]]*/mitschriften[[:space:]]*$' \
    || fehler "$d: MITSCHRIFTEN_PFAD=/mitschriften fehlt"
  echo "$b" | grep -qE '^      - \$\{MITSCHRIFTEN_ORDNER:-\./laeden-daten/sales/mitschriften\}:/mitschriften[[:space:]]*$' \
    || fehler "$d: Volume \${MITSCHRIFTEN_ORDNER:-./laeden-daten/sales/mitschriften}:/mitschriften (rw) fehlt"
done

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  sed 's/\r$//' "$WURZEL/.env.example" > "$T/compose.env"
  echo "MITSCHRIFTEN_ORDNER=./laeden-daten/probe/mitschriften" >> "$T/compose.env"
  ( cd "$WURZEL" && docker compose -f "$COMPOSE" --env-file "$T/compose.env" config ) \
    > "$T/config.yml" 2> "$T/config.err" \
    || fehler "docker compose config schlaegt fehl: $(grep -v 'variable is not set' "$T/config.err" | head -5)"
  for d in sales-termine sales-ui; do
    # Gerenderter Dienstblock, darin die Einhaengung mit Ziel /mitschriften.
    sed 's/\r$//' "$T/config.yml" | awk -v d="$d" '
      /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") }
      aktiv { print }' > "$T/dienst.yml"
    grep -qE '^      MITSCHRIFTEN_PFAD: /mitschriften$' "$T/dienst.yml" \
      || fehler "$d: gerendert ohne MITSCHRIFTEN_PFAD=/mitschriften"
    eintrag="$(awk '
      /^      - type: / { if (blk ~ /target: \/mitschriften\n/) { print blk; exit } blk = "" }
      { blk = blk $0 "\n" }
      END { if (blk ~ /target: \/mitschriften\n/) print blk }' "$T/dienst.yml")"
    [ -n "$eintrag" ] || fehler "$d: gerendert ohne Volume mit Ziel /mitschriften"
    echo "$eintrag" | grep -q 'read_only' && fehler "$d: /mitschriften ist read_only (muss beschreibbar sein)"
    echo "$eintrag" | grep -q 'laeden-daten.probe.mitschriften' \
      || fehler "$d: Quelle folgt MITSCHRIFTEN_ORDNER nicht: $(echo "$eintrag" | grep source)"
  done
  echo "OK: docker compose config gueltig"
else
  echo "HINWEIS: docker compose nicht vorhanden, config-Pruefung uebersprungen"
fi

# --- update.sh: Laden-.env pruefen -----------------------------------------
mkdir -p "$T/w/deploy/laeden" "$T/stub" "$T/betrieb"
cp "$WURZEL/deploy/update.sh" "$T/w/deploy/update.sh"
printf '#!/bin/sh\nexit 0\n' > "$T/stub/flock"; chmod +x "$T/stub/flock"
laden_env() { # datei praefix mitschriften-zeile(leer = keine)
  { echo "LADEN_PRAEFIX=$2"
    echo "MEDIEN_ORDNER=./laeden-daten/$2/media"
    echo "MEDIEN_ERZEUGT_ORDNER=./laeden-daten/$2/media-erzeugt"
    [ -z "$3" ] || echo "$3"; } > "$T/w/deploy/laeden/$1.env"
}
update_ausgabe() {
  PATH="$T/stub:$PATH" SALES_BETRIEB="$T/betrieb" bash "$T/w/deploy/update.sh" 2>&1 </dev/null || true
}
abgewiesen() { # beschreibung  (erwartet FEHLER mit MITSCHRIFTEN_ORDNER)
  local aus
  aus="$(update_ausgabe)"
  echo "$aus" | grep -qE '^FEHLER: .*MITSCHRIFTEN_ORDNER' \
    || fehler "update.sh weist nicht ab: $1 (Ausgabe: $(echo "$aus" | head -3))"
  echo "$aus" | grep -q '^ABBRUCH: ' || fehler "update.sh bricht nicht ab: $1"
}
for wert in "" "MITSCHRIFTEN_ORDNER=" "MITSCHRIFTEN_ORDNER=./laeden-daten/sales/mitschriften" \
            "MITSCHRIFTEN_ORDNER=laeden-daten/sales/mitschriften/" \
            "MITSCHRIFTEN_ORDNER=$T/w/laeden-daten/sales/mitschriften"; do
  rm -f "$T"/w/deploy/laeden/*.env
  laden_env ivan ivan "$wert"
  abgewiesen "Wert '${wert:-<fehlt>}'"
done
# Zwei Laeden, derselbe Ordner: der erste Laden besteht, der zweite wird abgewiesen.
rm -f "$T"/w/deploy/laeden/*.env
laden_env anna anna "MITSCHRIFTEN_ORDNER=./laeden-daten/geteilt/mitschriften"
laden_env ivan ivan "MITSCHRIFTEN_ORDNER=./laeden-daten/geteilt/mitschriften"
aus="$(update_ausgabe)"
echo "$aus" | grep -qE "^FEHLER: .*ivan\.env teilt MITSCHRIFTEN_ORDNER" \
  || fehler "update.sh weist geteilten Ordner nicht ab (Ausgabe: $(echo "$aus" | head -3))"
echo "$aus" | grep -qE "anna\.env.*MITSCHRIFTEN_ORDNER" \
  && fehler "update.sh weist den ersten Laden mit eigenem Ordner faelschlich ab"

# --- laden-anlegen.sh / beispiel.env / sicherung.sh / wiederherstellen.sh -----
LF() { sed 's/\r$//' "$1"; }
LF "$WURZEL/deploy/laden-anlegen.sh" | grep -qxF 'MITSCHRIFTEN_ORDNER=./laeden-daten/$NAME/mitschriften' \
  || fehler "laden-anlegen.sh schreibt MITSCHRIFTEN_ORDNER=./laeden-daten/<name>/mitschriften nicht"
LF "$WURZEL/deploy/laeden/beispiel.env" | grep -qxF 'MITSCHRIFTEN_ORDNER=./laeden-daten/beispiel/mitschriften' \
  || fehler "beispiel.env: MITSCHRIFTEN_ORDNER fehlt"
LF "$WURZEL/deploy/sicherung.sh" | grep -qF 'MITSCHRIFTEN_ORDNER:mitschriften' \
  || fehler "sicherung.sh: Paar MITSCHRIFTEN_ORDNER:mitschriften fehlt"
LF "$WURZEL/deploy/sicherung.sh" | grep -qF 'laeden-daten/sales/mitschriften' \
  || fehler "sicherung.sh: Vorgabe ./laeden-daten/sales/mitschriften des Basis-Ladens fehlt"
LF "$WURZEL/deploy/wiederherstellen.sh" | grep -qF 'mitschriften.tar.gz' \
  || fehler "wiederherstellen.sh: mitschriften.tar.gz wird nicht behandelt"

echo "OK: mitschriften-ordner"
