#!/usr/bin/env bash
# deploy/warteliste-bestaetigung.sh
#
# Bestaetigungsmails fuer die Warteliste von vibemind.space (seit 13.11.2026).
# Vom Timer sales-warteliste-bestaetigung jede Minute gestartet, nur
# Basis-Laden. Holt bei der Website die Adressen ab, die auf ihre
# Bestaetigungsmail warten, und reicht sie auf der Standardeingabe an
# sales-mail (warteliste_bestaetigung.py), das die Mails verschickt. Was der
# Mailserver nicht angenommen hat, meldet das Skript der Website zurueck.
# Kein Sprachmodell. Im Normalfall wartet niemand; dann endet das Skript
# nach dem Abruf, ohne den Container anzufassen.
#
# Zugang (.env, eingetragen von deploy/warteliste-anbinden.sh - derselbe wie
# beim Wartelisten-Abgleich):
#   WARTELISTE_URL                  Adresse der Website-Datenbank (https://…)
#   WARTELISTE_API_SCHLUESSEL       ihr oeffentlicher Schluessel
#   WARTELISTE_ABHOL_SCHLUESSEL     geheim; darf dort die Warteliste lesen und
#                                   die wartenden Adressen samt Token abholen
#   WARTELISTE_BESTAETIGUNG_SEITE   optional: Adresse der Bestaetigungsseite
#                                   (Vorgabe im Modul: vibemind.space)
#
# Sicherheit:
#   - Der Abholschluessel steht in keinem Argument (weder curl noch docker):
#     er geht ueber printf (eingebaut) und eine Pipe in den Rumpf der Anfrage.
#     Beide Anfragen sind POST; der Schluessel steht in keiner Adresse.
#   - Das Dokument mit den Token liegt nie auf der Platte und steht in keinem
#     Argument: es lebt in einer Variablen dieses Skripts und geht ueber eine
#     Pipe an sales-mail. Der Container bekommt den Schluessel nicht.
#   - ABHOLEN VERBRAUCHT: mit dem Abruf gilt eine Adresse bei der Website als
#     bedient. Deshalb prueft das Skript VORHER, ob sales-mail laeuft - sonst
#     waeren die Token abgeholt und keine Mail ginge raus.
#   - Ausgegeben werden nur Zahlen, keine Adressen und kein Token. Kein set -x.
set +x
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
CURL="${CURL:-curl}"
ZEITLIMIT="${ZEITLIMIT-timeout 240}"
read -r -a ZL <<< "$ZEITLIMIT"
ENV_DATEI="${WURZEL_ENV:-$WURZEL/.env}"
CONTAINER="sales-mail"

[ $# -eq 0 ] || { echo "FEHLER: unbekanntes Argument $1" >&2; exit 2; }

wert() {
  { grep -E "^$1=" "$ENV_DATEI" 2>/dev/null || true; } | head -1 | cut -d= -f2- | tr -d '\r" '
}
URL="${WARTELISTE_URL-$(wert WARTELISTE_URL)}"
API="${WARTELISTE_API_SCHLUESSEL-$(wert WARTELISTE_API_SCHLUESSEL)}"
ABHOL="${WARTELISTE_ABHOL_SCHLUESSEL-$(wert WARTELISTE_ABHOL_SCHLUESSEL)}"
SEITE="${WARTELISTE_BESTAETIGUNG_SEITE-$(wert WARTELISTE_BESTAETIGUNG_SEITE)}"

if ! [[ "$URL" =~ ^https://[A-Za-z0-9.-]+$ ]]; then
  echo "FEHLER: WARTELISTE_URL fehlt oder ist keine https-Adresse ohne Pfad (.env)." >&2; exit 2
fi
if ! [[ "$API" =~ ^[A-Za-z0-9._-]{20,}$ ]]; then
  echo "FEHLER: WARTELISTE_API_SCHLUESSEL fehlt (.env)." >&2; exit 2
fi
if ! [[ "$ABHOL" =~ ^[0-9a-f]{64}$ ]]; then
  echo "FEHLER: WARTELISTE_ABHOL_SCHLUESSEL fehlt oder hat nicht 64 Hex-Zeichen (.env)." >&2; exit 2
fi
SEITE_ARGUMENT=()
if [ -n "$SEITE" ]; then
  if ! [[ "$SEITE" =~ ^https://[a-z0-9.-]+(/[A-Za-z0-9_/-]*)?$ ]]; then
    echo "FEHLER: WARTELISTE_BESTAETIGUNG_SEITE ist keine https-Adresse (.env)." >&2; exit 2
  fi
  SEITE_ARGUMENT=(--seite "$SEITE")
fi

# Vor dem Abruf (siehe Kopf): ohne laufenden Versender nichts abholen.
if [ "$("$DOCKER" inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]; then
  echo "FEHLER: $CONTAINER laeuft nicht - nichts abgeholt, die Adressen warten weiter." >&2; exit 1
fi

aufruf() {   # aufruf <funktion>: Rumpf von der Standardeingabe, Antwort auf die Standardausgabe
  ${ZL[@]+"${ZL[@]}"} "$CURL" --silent --show-error --fail --max-time 60 \
    --request POST "$URL/rest/v1/rpc/$1" \
    --header "apikey: $API" --header "Authorization: Bearer $API" \
    --header "Content-Type: application/json" --data-binary @-
}

# --fail: bei einer Ablehnung (403) liefert curl nichts und endet ungleich 0;
# set -e beendet das Skript dann hier.
DOKUMENT="$(printf '{"p_key":"%s"}' "$ABHOL" | aufruf waitlist_mail_queue)"

# Niemand wartet - der Normalfall.
if [[ "$DOKUMENT" =~ \"rows\":\ ?\[\] ]]; then
  exit 0
fi

CODE=0
ERNEUT="$(printf '%s' "$DOKUMENT" \
  | ${ZL[@]+"${ZL[@]}"} "$DOCKER" exec -i "$CONTAINER" python warteliste_bestaetigung.py senden \
      ${SEITE_ARGUMENT[@]+"${SEITE_ARGUMENT[@]}"})" || CODE=$?
unset DOKUMENT

if [ -n "$ERNEUT" ] && [ "$ERNEUT" != "[]" ]; then
  # Die Liste kommt aus unserem eigenen Modul; trotzdem wird sie nur in den
  # Rumpf gesetzt, wenn sie genau die Form einer Adressliste hat.
  if ! [[ "$ERNEUT" =~ ^\[\"[a-z0-9._%+@-]+\"(,\"[a-z0-9._%+@-]+\")*\]$ ]]; then
    echo "FEHLER: Rueckmeldung von $CONTAINER hat nicht die Form einer Adressliste - nichts zurueckgemeldet." >&2
    exit 1
  fi
  ZURUECK="$(printf '{"p_key":"%s","p_emails":%s}' "$ABHOL" "$ERNEUT" | aufruf waitlist_mail_requeue)"
  if [[ "$ZURUECK" =~ ^[0-9]+$ ]]; then
    echo "zurueck in die Warteschlange: $ZURUECK" >&2
  fi
fi
exit "$CODE"
