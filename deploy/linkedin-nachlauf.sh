#!/usr/bin/env bash
# deploy/linkedin-nachlauf.sh [--trocken]
#
# Meldung nach dem Posten (Spec 2026-10-15 §4.4). Vom Timer
# sales-linkedin-nachlauf alle 2 Minuten gestartet, nur Basis-Laden.
# Holt aus sales-mcp die unmeldeten LinkedIn-Veroeffentlichungen samt
# Meldetext, schickt ihn ueber den WhatsApp-Kanal des Gateways an den
# Betreiber und bucht ERST NACH erfolgreichem Senden "gemeldet". Scheitert
# das Senden, bleibt die Meldung offen und der naechste Lauf versucht es
# erneut (Fenster 24 h, siehe linkedin_nachlauf.py). Kein Sprachmodell.
#
# Der Text geht als EIN Argument (Array) an docker — keine Shell-
# Interpolation von Namen mit $, Backticks oder Anfuehrungszeichen.
#
# Jeder docker-Aufruf laeuft unter `timeout 60` (ZEITLIMIT, im Test
# ersetzbar): ein haengendes Senden darf die oneshot-Unit nicht ewig
# "activating" halten, sonst startet der Timer sie nie wieder (die Unit hat
# zusaetzlich TimeoutStartSec=90).
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
ZEITLIMIT="${ZEITLIMIT-timeout 60}"
read -r -a ZL <<< "$ZEITLIMIT"
# Zeitlimit + docker als Array-Praefix; der Text bleibt EIN Argument.
dk() { ${ZL[@]+"${ZL[@]}"} "$DOCKER" "$@"; }
ENV_DATEI="${WURZEL_ENV:-$WURZEL/.env}"
TROCKEN=0
[ "${1:-}" = "--trocken" ] && TROCKEN=1

NUMMER="${SALES_BETREIBER_WHATSAPP-}"
if [ -z "$NUMMER" ]; then
  NUMMER="$({ grep -E '^SALES_BETREIBER_WHATSAPP=' "$ENV_DATEI" 2>/dev/null || true; } \
            | head -1 | cut -d= -f2- | tr -d '\r" ')"
fi
if ! [[ "$NUMMER" =~ ^\+[0-9]{8,15}$ ]]; then
  echo "FEHLER: SALES_BETREIBER_WHATSAPP fehlt oder ist keine E.164-Nummer (.env)." >&2
  exit 2
fi

offen="$(dk exec sales-mcp python linkedin_nachlauf.py liste)"
while IFS= read -r draft_id; do
  [ -n "$draft_id" ] || continue
  text="$(dk exec sales-mcp python linkedin_nachlauf.py text "$draft_id")" || continue
  if [ "$TROCKEN" = 1 ]; then
    printf 'TROCKEN %s an %s:\n%s\n\n' "$draft_id" "$NUMMER" "$text"
    continue
  fi
  befehl=(exec sales-claw openclaw message send --channel whatsapp
          --target "$NUMMER" -m "$text")
  if dk "${befehl[@]}" >/dev/null 2>&1; then
    # Scheitert das Buchen, ist die Meldung trotzdem raus: laut warnen und
    # mit dem naechsten Treffer weitermachen (kein Abbruch durch set -e).
    if dk exec sales-mcp python linkedin_nachlauf.py gemeldet "$draft_id"; then
      echo "gemeldet: $draft_id"
    else
      echo "WARNUNG: Meldung fuer $draft_id gesendet aber nicht gebucht – naechster Lauf sendet doppelt." >&2
    fi
  else
    echo "WARNUNG: Meldung fuer $draft_id nicht gesendet - naechster Lauf versucht es erneut." >&2
  fi
done <<< "$offen"
