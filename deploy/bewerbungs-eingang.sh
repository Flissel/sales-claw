#!/usr/bin/env bash
# deploy/bewerbungs-eingang.sh [--trocken]
#
# Bewerbungs-Eingang (29.10.2026, sales-mcp/bewerbungs_eingang.py). Vom Timer
# sales-bewerbungs-eingang taeglich um 19:45 Europe/Berlin gestartet, vor
# Hermes' Auswertung um 20:00, nur Basis-Laden. Holt die Warteliste der
# Zentrale, liest die Mails NUR LESEND aus der Datenbank der Post-Sammelstelle
# (post_mails/post_konten, kein IMAP) und meldet passende an /api/eingang/mails.
# Kein Sprachmodell, kein Versand.
#
# Die Arbeit macht das Modul im laufenden Werkzeugdienst (dort liegen die
# Datenbankanbindung und BEWERBUNG_EINGANG_KEY) - dieses Skript startet es nur
# und reicht den Exit-Code durch: 0 vollstaendig (auch "Warteliste leer",
# "keine postfaecher" und "nicht eingerichtet"), 1 unvollstaendig (der
# naechste Lauf prueft dasselbe Fenster noch einmal, die Zentrale ist
# idempotent), 2 Aufruf falsch. sales-post muss laufen, sonst fehlen die
# neuesten Mails.
#
# `timeout` (ZEITLIMIT, im Test ersetzbar): ein haengender Lauf darf die
# oneshot-Unit nicht ewig "activating" halten (die Unit hat zusaetzlich
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
