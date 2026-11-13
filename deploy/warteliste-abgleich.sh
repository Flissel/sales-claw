#!/usr/bin/env bash
# deploy/warteliste-abgleich.sh [--trocken] [--hoechstens N]
#
# Warteliste von vibemind.space -> Kontakte (seit 13.11.2026). Vom Timer
# sales-warteliste-abgleich einmal in der Nacht gestartet, nur Basis-Laden.
# Holt die Warteliste bei der Website ab und reicht sie auf der
# Standardeingabe an sales-mcp (warteliste_abgleich.py), das abgleicht.
# Kein Sprachmodell. Ausgegeben werden nur Zahlen, keine Adressen.
#
# Zugang (.env, eingetragen von deploy/warteliste-anbinden.sh):
#   WARTELISTE_URL               Adresse der Website-Datenbank (https://…)
#   WARTELISTE_API_SCHLUESSEL    ihr oeffentlicher Schluessel (steht auch im
#                                Browser jedes Besuchers)
#   WARTELISTE_ABHOL_SCHLUESSEL  geheim; darf dort genau eine Funktion
#                                aufrufen, die die Warteliste LIEST
#
# Sicherheit:
#   - Der Abholschluessel steht in keinem Argument (weder curl noch docker):
#     er geht ueber printf (eingebaut) und eine Pipe in den Rumpf der Anfrage.
#     Die Anfrage ist ein POST; der Schluessel steht in keiner Adresse.
#   - Das Dokument liegt nie auf der Platte: curl schreibt in eine Pipe,
#     sales-mcp liest sie. Der Container bekommt den Schluessel nicht.
#   - Scheitert das Abholen (Netz, Schluessel entzogen, Zeitlimit), kommt bei
#     sales-mcp nichts an und es aendert nichts (Exit 2 dort).
#   - Kein set -x.
set +x
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
CURL="${CURL:-curl}"
ZEITLIMIT="${ZEITLIMIT-timeout 300}"
read -r -a ZL <<< "$ZEITLIMIT"
ENV_DATEI="${WURZEL_ENV:-$WURZEL/.env}"

ARGUMENTE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --trocken) ARGUMENTE+=(--trocken); shift ;;
    --hoechstens)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "FEHLER: --hoechstens braucht eine Zahl." >&2; exit 2; }
      ARGUMENTE+=(--hoechstens "$2"); shift 2 ;;
    *) echo "FEHLER: unbekanntes Argument $1" >&2; exit 2 ;;
  esac
done

wert() {
  { grep -E "^$1=" "$ENV_DATEI" 2>/dev/null || true; } | head -1 | cut -d= -f2- | tr -d '\r" '
}
URL="${WARTELISTE_URL-$(wert WARTELISTE_URL)}"
API="${WARTELISTE_API_SCHLUESSEL-$(wert WARTELISTE_API_SCHLUESSEL)}"
ABHOL="${WARTELISTE_ABHOL_SCHLUESSEL-$(wert WARTELISTE_ABHOL_SCHLUESSEL)}"

if ! [[ "$URL" =~ ^https://[A-Za-z0-9.-]+$ ]]; then
  echo "FEHLER: WARTELISTE_URL fehlt oder ist keine https-Adresse ohne Pfad (.env)." >&2; exit 2
fi
if ! [[ "$API" =~ ^[A-Za-z0-9._-]{20,}$ ]]; then
  echo "FEHLER: WARTELISTE_API_SCHLUESSEL fehlt (.env)." >&2; exit 2
fi
if ! [[ "$ABHOL" =~ ^[0-9a-f]{64}$ ]]; then
  echo "FEHLER: WARTELISTE_ABHOL_SCHLUESSEL fehlt oder hat nicht 64 Hex-Zeichen (.env)." >&2; exit 2
fi

# --fail: bei einer Ablehnung (403) liefert curl nichts weiter und endet
# ungleich 0; pipefail traegt das bis zum Exit dieses Skripts.
printf '{"p_key":"%s"}' "$ABHOL" \
  | ${ZL[@]+"${ZL[@]}"} "$CURL" --silent --show-error --fail --max-time 120 \
      --request POST "$URL/rest/v1/rpc/waitlist_export" \
      --header "apikey: $API" --header "Authorization: Bearer $API" \
      --header "Content-Type: application/json" --data-binary @- \
  | ${ZL[@]+"${ZL[@]}"} "$DOCKER" exec -i sales-mcp python warteliste_abgleich.py abgleichen \
      ${ARGUMENTE[@]+"${ARGUMENTE[@]}"}
