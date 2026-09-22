#!/usr/bin/env bash
# deploy/webhook-anbinden.sh — den Posteingangs-Webhook eines Ladens bei
# seinem openwa registrieren. Der letzte Schritt nach der WhatsApp-Kopplung.
#
# WARUM ES EINEN EIGENEN SCHRITT BRAUCHT (Befund 22.09.2026): das
# `INBOX_WEBHOOK_SECRET` ist ein GEMEINSAMES Geheimnis zweier Seiten —
# `<laden>-inbox` prueft damit die HMAC-Signatur, und openwa muss es beim
# Registrieren des Webhooks mitbekommen. `laden-anlegen.sh` erzeugt es, aber
# die zweite Haelfte kann erst laufen, wenn openwa eine Session HAT: API-
# Schluessel und Session-Kennung entstehen mit der Kopplung. Deshalb ist
# dies der einzige Schritt, der nach dem Telefon kommt.
#
# Ohne ihn laufen alle Dienste, und der Posteingang bleibt trotzdem leer:
# openwa nimmt Nachrichten an und schickt sie nirgendwohin.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ $# -lt 1 ]; then
  cat >&2 <<'HILFE'
Aufruf: deploy/webhook-anbinden.sh <laden> [--wirklich]

  <laden>      Praefix des Ladens, z. B. ivan  (fuer den ersten: sales)
  --wirklich   ohne dieses Wort wird nur geprueft und gezeigt

Voraussetzung: WhatsApp ist gekoppelt, und OPENWA_API_KEY sowie
OPENWA_SESSION_ID stehen in der Umgebungsdatei des Ladens.
HILFE
  exit 2
fi

LADEN="$1"; WIRKLICH="${2:-}"
if [ "$LADEN" = "sales" ]; then ENVDATEI="$WURZEL/.env"; else ENVDATEI="$WURZEL/deploy/laeden/$LADEN.env"; fi
[ -r "$ENVDATEI" ] || { echo "ABBRUCH: $ENVDATEI nicht lesbar." >&2; exit 1; }

# `|| true` ist hier kein Schoenheitsfehler, sondern Pflicht: dieses Skript
# laeuft mit `set -o pipefail`, und ein `grep`, das nichts findet, liefert 1.
# Die Zuweisung scheitert damit, `set -e` beendet das Skript — BEVOR die
# Fehlermeldung ueber den fehlenden Wert geschrieben wird. Gemessen
# 22.09.2026 gegen Ivans ungekoppelten Laden: null Ausgabe statt der
# Erklaerung, was fehlt. Dieselbe Falle hatte schon cron-saat.sh.
wert() { grep -E "^$1=" "$ENVDATEI" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]' || true; }
GEHEIMNIS="$(wert INBOX_WEBHOOK_SECRET)"
SCHLUESSEL="$(wert OPENWA_API_KEY)"
SITZUNG="$(wert OPENWA_SESSION_ID)"
CONTAINER="$LADEN-openwa"
ZIEL="http://$LADEN-inbox:8790/webhook"

fehlt=""
[ -n "$GEHEIMNIS" ] || fehlt="$fehlt INBOX_WEBHOOK_SECRET"
[ -n "$SCHLUESSEL" ] || fehlt="$fehlt OPENWA_API_KEY"
[ -n "$SITZUNG" ]    || fehlt="$fehlt OPENWA_SESSION_ID"
if [ -n "$fehlt" ]; then
  echo "ABBRUCH: in $ENVDATEI fehlt:$fehlt" >&2
  echo "         OPENWA_API_KEY und OPENWA_SESSION_ID entstehen mit der" >&2
  echo "         WhatsApp-Kopplung — erst koppeln, dann diesen Schritt." >&2
  exit 1
fi
[ "${#GEHEIMNIS}" -ge 16 ] || {
  echo "ABBRUCH: INBOX_WEBHOOK_SECRET ist kuerzer als 16 Zeichen — der" >&2
  echo "         Posteingang wuerde es ohnehin ablehnen." >&2; exit 1; }

docker inspect -f '{{.State.Status}}' "$CONTAINER" >/dev/null 2>&1 || {
  echo "ABBRUCH: Container '$CONTAINER' gibt es nicht." >&2; exit 1; }
[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" = "running" ] || {
  echo "ABBRUCH: '$CONTAINER' laeuft nicht." >&2; exit 1; }

echo "  Laden:      $LADEN"
echo "  openwa:     $CONTAINER (Sitzung ${SITZUNG:0:6}…)"
echo "  Ziel:       $ZIEL"
echo "  Geheimnis:  ${#GEHEIMNIS} Zeichen (wird nie angezeigt)"

# SSRF-Sperre zuerst: openwa weist private Adressen bei der Registrierung ab,
# und die Ausnahme steht je Laden im Compose. Steht dort der falsche Laden,
# gingen die Nachrichten DIESES Menschen an den Posteingang eines ANDEREN —
# genau das war bis zum 22.09.2026 der Fall (SSRF_ALLOWED_HOSTS stand fest
# auf `sales-inbox`, auch in Ivans Container).
ERLAUBT="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" \
           | grep -E '^SSRF_ALLOWED_HOSTS=' | cut -d= -f2- | tr -d '[:space:]' || true)"
if [ "$ERLAUBT" != "$LADEN-inbox" ]; then
  echo "ABBRUCH: '$CONTAINER' erlaubt '$ERLAUBT', gebraucht wird '$LADEN-inbox'." >&2
  echo "         Sonst gingen die Nachrichten dieses Menschen an einen" >&2
  echo "         FREMDEN Posteingang. Container mit der Umgebungsdatei des" >&2
  echo "         Ladens neu erzeugen:" >&2
  echo "           docker compose --env-file $ENVDATEI \\" >&2
  echo "             -f docker-compose.openwa.yml up -d --force-recreate openwa" >&2
  exit 1
fi
echo "  SSRF-Sperre: $ERLAUBT — passt"

if [ "$WIRKLICH" != "--wirklich" ]; then
  echo
  echo "== PROBELAUF — nichts registriert (mit --wirklich ausfuehren) =="
  exit 0
fi

# Der Schluessel geht ueber die UMGEBUNG in den Container, nie ueber argv:
# Argumente stehen in der Prozessliste (dieselbe Regel wie beim DSN im
# RUNBOOK, Abschnitt „psql-Gegenproben").
ANTWORT="$(docker exec -e OW_KEY="$SCHLUESSEL" -e OW_SECRET="$GEHEIMNIS" "$CONTAINER" \
  sh -lc 'curl -s -o /tmp/aw -w "%{http_code}" -X POST \
     -H "x-api-key: $OW_KEY" -H "Content-Type: application/json" \
     -d "{\"url\":\"'"$ZIEL"'\",\"events\":[\"message.received\",\"message.sent\"],\"secret\":\"$OW_SECRET\",\"retryCount\":3}" \
     "http://127.0.0.1:2785/api/sessions/'"$SITZUNG"'/webhooks"; echo; cat /tmp/aw; rm -f /tmp/aw')"

CODE="$(printf '%s' "$ANTWORT" | head -1)"
RUMPF="$(printf '%s' "$ANTWORT" | tail -n +2 | head -c 300)"
case "$CODE" in
  2*) echo "  registriert (HTTP $CODE)" ;;
  *)  echo "  FEHLER: HTTP $CODE — $RUMPF" >&2; exit 1 ;;
esac

echo
echo "Gegenprobe — eine eingehende Nachricht muss jetzt im Log auftauchen:"
echo "  docker logs --tail 20 $LADEN-inbox"
