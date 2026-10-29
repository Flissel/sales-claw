#!/usr/bin/env bash
# deploy/bewerbungs-eingang.sh [--trocken]
#
# Bewerbungs-Eingang (29.10.2026, sales-mcp/bewerbungs_eingang.py). Vom Timer
# sales-bewerbungs-eingang taeglich um 19:45 Europe/Berlin gestartet, vor
# Hermes' Auswertung um 20:00, nur Basis-Laden. Holt die Warteliste der
# Zentrale, liest die Postfaecher NUR LESEND und meldet passende Mails an
# /api/eingang/mails. Kein Sprachmodell, kein Versand.
#
# Die Arbeit macht das Modul im laufenden Werkzeugdienst (dort liegen die
# Postfach-Zugaenge und BEWERBUNG_EINGANG_KEY) - dieses Skript startet es nur
# und reicht den Exit-Code durch: 0 vollstaendig (auch "Warteliste leer" und
# "nicht eingerichtet"), 1 unvollstaendig (Cursor bleibt, der naechste Lauf
# holt dieselben Mails noch einmal), 2 Aufruf falsch.
#
# `timeout` (ZEITLIMIT, im Test ersetzbar): ein haengendes IMAP-Postfach darf
# die oneshot-Unit nicht ewig "activating" halten (die Unit hat zusaetzlich
# TimeoutStartSec). Die Ausgabe enthaelt nur Zahlen, nie Betreff oder Absender.
set -euo pipefail
DOCKER="${DOCKER:-docker}"
ZEITLIMIT="${ZEITLIMIT-timeout 900}"
DIENST="${BEWERBUNGS_EINGANG_DIENST:-sales-mcp}"
read -r -a ZL <<< "$ZEITLIMIT"

case "${1:-}" in
  "") argumente=(lauf) ;;
  --trocken) argumente=(lauf --trocken) ;;
  *) echo "Aufruf: deploy/bewerbungs-eingang.sh [--trocken]" >&2; exit 2 ;;
esac

if [ "$("$DOCKER" inspect -f '{{.State.Status}}' "$DIENST" 2>/dev/null || true)" != "running" ]; then
  echo "FEHLER: Container $DIENST laeuft nicht - Lauf uebersprungen, Cursor bleibt." >&2
  exit 1
fi

exec ${ZL[@]+"${ZL[@]}"} "$DOCKER" exec "$DIENST" python bewerbungs_eingang.py "${argumente[@]}"
