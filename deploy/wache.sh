#!/usr/bin/env bash
# deploy/wache.sh — die Betriebs-Wache (F3, 31.08.2026).
#
# Alle 15 Minuten (systemd-Timer) laeuft die Abnahme. Bei GRUEN passiert
# nichts. Bei ROT landet ein Befund im Auftrags-Spool (Typ wache), den
# der 2-h-Takt des Bots dem Betreiber meldet — hoechstens EIN Befund je
# zwei Stunden, damit ein andauernder Ausfall nicht stapelt.
#
# EHRLICHE GRENZE (steht auch im Plan): faellt der Gateway selbst oder
# die WhatsApp-Strecke, kann auf diesem Weg niemand alarmieren — der
# Befund liegt dann bereit, bis der Kanal wiederkommt. Ein Aussenkanal
# ist ein eigener spaeterer Schritt (Teil F, offen).
set -uo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPOOL="$WURZEL/auftraege"
RUHE_S=7200

AUSGABE="$(bash "$WURZEL/deploy/smoke.sh" 2>&1)"
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
  exit 0
fi

# Ruhe halten, wenn der juengste Befund noch frisch ist.
juengster="$(ls -1t "$SPOOL"/ergebnis-wache-*.json 2>/dev/null | head -1)"
if [ -n "$juengster" ]; then
  alter=$(( $(date +%s) - $(stat -c %Y "$juengster") ))
  if [ "$alter" -lt "$RUHE_S" ]; then
    exit 0
  fi
fi

mkdir -p "$SPOOL"
stempel="$(date +%Y%m%d-%H%M%S)"
rote="$(printf '%s\n' "$AUSGABE" | grep "ROT" | head -8 | sed 's/"/\\"/g' | paste -sd '; ' -)"
printf '{"zeitpunkt":"%s","typ":"wache","ergebnis":"rot","rot_anzahl":%d,"rote_pruefungen":"%s"}\n' \
  "$(date -Is)" "$STATUS" "${rote:-unbekannt}" \
  > "$SPOOL/ergebnis-wache-$stempel.json"
echo "Wache: $STATUS rote Pruefung(en), Befund abgelegt."
