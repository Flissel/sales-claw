#!/usr/bin/env bash
# Bindet den selbst betriebenen Vexa-Stack (deploy/vexa/, Compose-Projekt
# "vexa") an sales-claw an: legt bei Bedarf deploy/vexa/.env an, richtet in
# Vexa den Nutzer "sales" mit einem Token (Rechte bot,tx) ein und traegt ihn
# als VEXA_API_KEY in die .env von sales-claw ein.
#
#   bash ~/sales-claw/deploy/vexa-anbinden.sh
#
# Zweimal aufrufen (idempotent):
#   1. Aufruf: legt deploy/vexa/.env mit Zufallswerten an (Rechte 600) und
#      meldet, dass Vexa noch nicht laeuft (Exit 4). Dann
#      `docker compose -p vexa up -d` (nach Felix' OK).
#   2. Aufruf: Nutzer sales (gibt es ihn schon, wird er wiederverwendet),
#      Token (ein noch gueltiger VEXA_API_KEY aus der sales-claw-.env wird
#      behalten), PUT /user/transcription mit Platzhalter-Token, dann
#      VEXA_API_KEY= in die sales-claw-.env.
#   sales-termine liest die .env erst nach einem Neuerzeugen:
#   `docker compose up -d --no-deps --force-recreate sales-termine`.
#
# Admin-API (Vexa v0.12.28, core/identity/services/admin-api/.../app/main.py),
# Aufruf im Container direkt an die Admin-API (Port 8001, Fallback 8057):
#   POST /admin/users                       Kopf X-Admin-API-Key, legt an oder gibt vorhandenen zurueck
#   GET  /admin/users/email/{email}         Kopf X-Admin-API-Key
#   POST /admin/users/{id}/tokens?scopes=bot,tx   Kopf X-Admin-API-Key
#   PUT  /user/transcription                Kopf X-API-Key (Nutzer-Token)
# Spike: ohne einen hinterlegten Token in /user/transcription scheitert die
# Spracherkennung; die URL kommt aus der Umgebung des Containers
# (TRANSCRIPTION_SERVICE_URL), hier steht nur der Platzhalter-Token.
#
# Sicherheit (wie kanal-zugang-eintragen.sh):
# * Auf stdout steht nur "ok"-Text, Fehler gehen nach stderr. Kein set -x.
#   Tokens, Passwoerter und Schluessel werden nie ausgegeben, auch nicht teilweise.
# * Geheimnisse gehen nie als Argument an ein Programm (ps zeigt sie sonst):
#   der Admin-Token kommt im Container aus dessen eigener Umgebung, der
#   vorhandene Nutzer-Token wird per `docker exec -e NAME` (ohne Wert)
#   weitergereicht, geschrieben wird nur mit eingebautem printf.
# * Schreiben: Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
set +x
set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEXA_ENV="${VEXA_ENV_DATEI:-$HIER/vexa/.env}"
ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
DOCKER="${DOCKER:-docker}"
CONTAINER="${VEXA_CONTAINER:-vexa-lite}"
NUTZER_EMAIL="sales@localhost"
NUTZER_NAME="sales"
PLATZHALTER_TOKEN="lokal"
ERLAUBT='^[A-Za-z0-9_]+$'

zufall() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

umask 077

# 1) deploy/vexa/.env anlegen, falls sie fehlt (Datei 600).
if [ ! -f "$VEXA_ENV" ]; then
  mkdir -p "$(dirname "$VEXA_ENV")"
  neu_vexa="$(mktemp "$(dirname "$VEXA_ENV")/.env.neu.XXXXXX")"
  trap 'rm -f "$neu_vexa"' EXIT
  {
    printf 'ADMIN_TOKEN=%s\n' "$(zufall)"
    printf 'VEXA_DB_PASSWORD=%s\n' "$(zufall)"
    printf 'VEXA_S3_ACCESS_KEY=%s\n' "$(zufall | head -c 20)"
    printf 'VEXA_S3_SECRET_KEY=%s\n' "$(zufall)"
  } > "$neu_vexa"
  chmod 600 "$neu_vexa"
  mv -f "$neu_vexa" "$VEXA_ENV"
  trap - EXIT
  echo "deploy/vexa/.env angelegt (Rechte 600)."
fi
if grep -q '^ADMIN_TOKEN=PLATZHALTER' "$VEXA_ENV"; then
  echo "$VEXA_ENV enthaelt noch Platzhalter – Datei loeschen und das Skript neu aufrufen, abgebrochen." >&2
  exit 1
fi

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

# Vexa muss laufen, sonst gibt es nichts anzubinden.
laeuft="$($DOCKER inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [ "$laeuft" != "true" ]; then
  echo "Container $CONTAINER läuft nicht – erst 'docker compose -p vexa up -d' in deploy/vexa, dann dieses Skript noch einmal." >&2
  exit 4
fi

# 2) Nutzer, Token und Transkriptions-Vorgabe — alles im Container.
# Das Skript unten enthaelt keine Geheimnisse; der Admin-Token steht dort in
# $ADMIN_API_TOKEN (Umgebung des Containers), ein vorhandener Nutzer-Token
# kommt ueber ALTER_KEY. Ausgabe: nur der Token (stdout), Fehler auf stderr.
# (Einfache Anfuehrungszeichen sind Absicht: die Variablen loest die Shell im Container auf.)
# shellcheck disable=SC2016
IM_CONTAINER='
set -eu
ADMIN=""
i=0
while [ "$i" -lt 24 ] && [ -z "$ADMIN" ]; do
  for p in 8001 8057; do
    code="$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://localhost:$p/admin/users/email/'"$NUTZER_EMAIL"'" -H "X-Admin-API-Key: $ADMIN_API_TOKEN" 2>/dev/null || true)"
    case "$code" in 2*|404) ADMIN="http://localhost:$p"; break ;; esac
  done
  [ -n "$ADMIN" ] || { i=$((i + 1)); sleep 5; }
done
[ -n "$ADMIN" ] || { echo "Admin-API im Container nicht erreichbar (8001/8057)" >&2; exit 11; }
uid="$(curl -s "$ADMIN/admin/users/email/'"$NUTZER_EMAIL"'" -H "X-Admin-API-Key: $ADMIN_API_TOKEN" | sed -n "s/.*\"id\":\([0-9]*\).*/\1/p")"
if [ -z "$uid" ]; then
  uid="$(curl -s -X POST "$ADMIN/admin/users" -H "X-Admin-API-Key: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
         -d "{\"email\":\"'"$NUTZER_EMAIL"'\",\"name\":\"'"$NUTZER_NAME"'\",\"max_concurrent_bots\":3}" | sed -n "s/.*\"id\":\([0-9]*\).*/\1/p")"
fi
[ -n "$uid" ] || { echo "Nutzer sales liess sich nicht anlegen" >&2; exit 12; }
key=""
if [ -n "${ALTER_KEY:-}" ]; then
  code="$(curl -s -o /dev/null -w "%{http_code}" "$ADMIN/user/transcription" -H "X-API-Key: $ALTER_KEY" || true)"
  [ "$code" = "200" ] && key="$ALTER_KEY"
fi
if [ -z "$key" ]; then
  key="$(curl -s -X POST "$ADMIN/admin/users/$uid/tokens?scopes=bot,tx" -H "X-Admin-API-Key: $ADMIN_API_TOKEN" | sed -n "s/.*\"token\":\"\([^\"]*\)\".*/\1/p")"
fi
[ -n "$key" ] || { echo "Token (bot,tx) liess sich nicht holen" >&2; exit 13; }
code="$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$ADMIN/user/transcription" -H "X-API-Key: $key" \
        -H "Content-Type: application/json" -d "{\"token\":\"'"$PLATZHALTER_TOKEN"'\"}" || true)"
[ "$code" = "200" ] || { echo "PUT /user/transcription antwortete HTTP $code" >&2; exit 14; }
printf "%s\n" "$key"
'

ALTER_KEY="$(grep -E '^VEXA_API_KEY=' "$ENV_DATEI" | tail -n 1 | cut -d= -f2- || true)"
ALTER_KEY="${ALTER_KEY%$'\r'}"
if [ -n "$ALTER_KEY" ] && ! [[ $ALTER_KEY =~ $ERLAUBT ]]; then
  ALTER_KEY=""
fi
export ALTER_KEY

if ! KEY="$($DOCKER exec -e ALTER_KEY "$CONTAINER" sh -c "$IM_CONTAINER")"; then
  unset ALTER_KEY KEY
  echo "Anbinden an Vexa fehlgeschlagen (Meldung oben) – sales-claw-.env unverändert." >&2
  exit 1
fi
unset ALTER_KEY
KEY="${KEY%$'\r'}"
if [ -z "$KEY" ] || ! [[ $KEY =~ $ERLAUBT ]]; then
  unset KEY
  echo "Vexa lieferte keinen brauchbaren Token – sales-claw-.env unverändert." >&2
  exit 1
fi

# 3) VEXA_API_KEY in die sales-claw-.env (Sicherung, Temp-Datei 600, mv).
if grep -qxF "VEXA_API_KEY=$KEY" "$ENV_DATEI"; then
  unset KEY
  echo "Vexa angebunden: Nutzer sales, VEXA_API_KEY steht schon in $(basename "$ENV_DATEI") (nichts geändert)."
  exit 0
fi
PROJEKT="$(dirname "$ENV_DATEI")"
stempel="$(date +%Y%m%d-%H%M%S)"
SICHERUNG="$ENV_DATEI.vor-vexa-$stempel"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"
chmod 600 "$SICHERUNG"

NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
# grep: Exit 1 = keine Zeile uebrig (kein Fehler), 2 = echter Fehler
grep -Ev '^VEXA_API_KEY=' "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then
  printf '\n' >> "$NEU"
fi
printf 'VEXA_API_KEY=%s\n' "$KEY" >> "$NEU"
unset KEY
chmod 600 "$NEU"
mv -f "$NEU" "$ENV_DATEI"
trap - EXIT

echo "Vexa angebunden: Nutzer sales, VEXA_API_KEY in $(basename "$ENV_DATEI") eingetragen, Sicherung: $(basename "$SICHERUNG"). Zum Wirksamwerden sales-termine neu erzeugen."
