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
#      `docker compose -f ~/sales-claw/deploy/vexa/docker-compose.yml -p vexa up -d`
#      (nach Felix' OK; ohne -f laedt Compose die Datei des Basis-Stacks).
#   2. Aufruf: Nutzer sales (gibt es ihn schon, wird er wiederverwendet),
#      Token (ein noch gueltiger VEXA_API_KEY aus der sales-claw-.env wird
#      behalten), PUT /user/transcription mit Platzhalter-Token, dann
#      VEXA_API_KEY= in die sales-claw-.env.
#   sales-termine liest die .env erst nach einem Neuerzeugen:
#   `docker compose up -d --no-deps --force-recreate sales-termine`.
#
# Admin-API (Vexa v0.12.28, core/identity/services/admin-api/src/admin_api/
# app/main.py), Aufruf im Container direkt an die Admin-API (Port 8001, Fallback 8057):
#   POST /admin/users                       Kopf X-Admin-API-Key, legt an oder gibt vorhandenen zurueck (Z. 428)
#   GET  /admin/users/email/{email}         Kopf X-Admin-API-Key (Z. 520)
#   POST /admin/users/{id}/tokens?scopes=bot,tx   Kopf X-Admin-API-Key (Z. 567)
#   PUT  /user/transcription                Kopf X-API-Key (Nutzer-Token), Body {url?, token?} (Z. 855)
# Token-Format vxa_<scope>_<32 Zeichen aus A-Za-z0-9> (token_scope.py), die E-Mail
# ist ein einfaches str (kein EmailStr). Ein vorhandener VEXA_API_KEY gilt als
# gueltig, wenn das idempotente PUT /user/transcription mit ihm 2xx liefert; dann
# wird weder ein Token neu geholt noch die .env angefasst.
# Spike: ohne einen hinterlegten Token in /user/transcription scheitert die
# Spracherkennung; die URL kommt aus der Umgebung des Containers
# (TRANSCRIPTION_SERVICE_URL), hier steht nur der Platzhalter-Token.
#
# Sicherheit (wie kanal-zugang-eintragen.sh):
# * Auf stdout steht nur "ok"-Text, Fehler gehen nach stderr. Kein set -x.
#   Tokens, Passwoerter und Schluessel werden nie ausgegeben, auch nicht teilweise.
# * Geheimnisse stehen nie in der Argumentliste eines Programms (ps zeigt sie
#   sonst). Im Container kommt der Admin-Token aus dessen eigener Umgebung und
#   geht zusammen mit dem Nutzer-Token ueber `curl -K -` (Kopfzeilen per Pipe aus
#   dem eingebauten printf) an curl. Ein vorhandener Nutzer-Token wird per
#   `docker exec -e NAME` (ohne Wert) weitergereicht, geschrieben wird nur mit
#   eingebautem printf.
# * Schreiben: Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
# * deploy/vexa/.env wird nicht neu erzeugt, solange das Volume vexa-pgdata
#   existiert (neues Datenbankpasswort passte nicht zu den alten Daten).
set +x
set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEXA_ENV="${VEXA_ENV_DATEI:-$HIER/vexa/.env}"
ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
DOCKER="${DOCKER:-docker}"
CONTAINER="${VEXA_CONTAINER:-vexa-lite}"
NUTZER_EMAIL="sales@vexa.lokal"
NUTZER_NAME="sales"
PLATZHALTER_TOKEN="lokal"
ERLAUBT='^[A-Za-z0-9_-]+$'   # Vexa: vxa_<scope>_<A-Za-z0-9>; "-" zusaetzlich fuer Fremdformate

zufall() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

umask 077

# 1) deploy/vexa/.env anlegen, falls sie fehlt (Datei 600).
if [ ! -f "$VEXA_ENV" ]; then
  if $DOCKER volume inspect vexa-pgdata >/dev/null 2>&1; then
    echo "Volume vexa-pgdata existiert, aber $VEXA_ENV fehlt – eine neue .env bekäme ein anderes Datenbankpasswort als die vorhandenen Daten. Alte .env wiederherstellen oder (Datenverlust!) das Volume einzeln entfernen, abgebrochen." >&2
    exit 5
  fi
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
if grep -q 'PLATZHALTER' "$VEXA_ENV"; then
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
  echo "Container $CONTAINER läuft nicht – erst 'docker compose -f $HIER/vexa/docker-compose.yml -p vexa up -d', dann dieses Skript noch einmal." >&2
  exit 4
fi

# 2) Nutzer, Token und Transkriptions-Vorgabe — alles im Container.
# Das Skript unten enthaelt keine Geheimnisse; der Admin-Token steht dort nur als
# $ADMIN_API_TOKEN (Umgebung des Containers), ein vorhandener Nutzer-Token kommt
# ueber ALTER_KEY. Ausgabe: nur der Token (stdout), Fehler auf stderr.
# (Einfache Anfuehrungszeichen im Heredoc sind Absicht: die Shell im Container loest auf.)
IM_CONTAINER="$(cat <<'EOS'
set -eu
hdr() { printf 'header = "%s: %s"\n' "$1" "$2"; }
cadm() { hdr X-Admin-API-Key "$ADMIN_API_TOKEN" | curl -s -K - "$@"; }
cusr() { k="$1"; shift; hdr X-API-Key "$k" | curl -s -K - "$@"; }
# JSON-Feld lesen: python3 wenn vorhanden, sonst erster Treffer per grep.
jget() {
  eing="$(cat)"
  v="$(printf '%s' "$eing" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin)[sys.argv[1]])
except Exception:
    pass' "$1" 2>/dev/null || true)"
  if [ -z "$v" ]; then
    v="$(printf '%s' "$eing" | grep -o "\"$1\":\"\{0,1\}[^\",}]*" | head -n 1 | sed "s/^\"$1\":\"\{0,1\}//" || true)"
  fi
  printf '%s' "$v"
}
put_tx() { cusr "$1" -o /dev/null -w '%{http_code}' -X PUT "$ADMIN/user/transcription" -H 'Content-Type: application/json' -d "{\"token\":\"$PLATZHALTER_TOKEN\"}" || true; }

ADMIN=""
i=0
while [ "$i" -lt 24 ] && [ -z "$ADMIN" ]; do
  for p in 8001 8057; do
    code="$(cadm -o /dev/null -w '%{http_code}' "http://localhost:$p/admin/users/email/$NUTZER_EMAIL" 2>/dev/null || true)"
    case "$code" in 2*|404) ADMIN="http://localhost:$p"; break ;; esac
  done
  [ -n "$ADMIN" ] || { i=$((i + 1)); sleep 5; }
done
[ -n "$ADMIN" ] || { echo "Admin-API im Container nicht erreichbar (8001/8057)" >&2; exit 11; }

# Vorhandener Token: gueltig, wenn das idempotente PUT 2xx liefert.
if [ -n "${ALTER_KEY:-}" ]; then
  case "$(put_tx "$ALTER_KEY")" in 2*) printf '%s\n' "$ALTER_KEY"; exit 0 ;; esac
fi

uid="$(cadm "$ADMIN/admin/users/email/$NUTZER_EMAIL" | jget id)"
if [ -z "$uid" ]; then
  uid="$(cadm -X POST "$ADMIN/admin/users" -H 'Content-Type: application/json'          -d "{\"email\":\"$NUTZER_EMAIL\",\"name\":\"$NUTZER_NAME\",\"max_concurrent_bots\":3}" | jget id)"
fi
[ -n "$uid" ] || { echo "Nutzer sales liess sich nicht anlegen" >&2; exit 12; }
key="$(cadm -X POST "$ADMIN/admin/users/$uid/tokens?scopes=bot,tx" | jget token)"
[ -n "$key" ] || { echo "Token (bot,tx) liess sich nicht holen" >&2; exit 13; }
code="$(put_tx "$key")"
case "$code" in 2*) ;; *) echo "PUT /user/transcription antwortete HTTP $code" >&2; exit 14 ;; esac
printf '%s\n' "$key"
EOS
)"

ALTER_KEY="$(grep -E '^VEXA_API_KEY=' "$ENV_DATEI" | tail -n 1 | cut -d= -f2- || true)"
ALTER_KEY="${ALTER_KEY%$'\r'}"
if [ -n "$ALTER_KEY" ] && ! [[ $ALTER_KEY =~ $ERLAUBT ]]; then
  ALTER_KEY=""
fi
export ALTER_KEY NUTZER_EMAIL NUTZER_NAME PLATZHALTER_TOKEN

if ! KEY="$($DOCKER exec -e ALTER_KEY -e NUTZER_EMAIL -e NUTZER_NAME -e PLATZHALTER_TOKEN "$CONTAINER" sh -c "$IM_CONTAINER")"; then
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
