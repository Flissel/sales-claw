#!/usr/bin/env bash
# deploy/google-kalender-zugang.sh — traegt die OAuth-Zugangsdaten fuer das
# Verbinden von Google-Kalendern (Kalender verbinden, 08.11.2026) in die .env ein.
#
#   bash ~/sales-claw/deploy/google-kalender-zugang.sh
#
# Vorher in der Google Cloud Console: OAuth-Client "Webanwendung" anlegen, als
# Weiterleitungs-URI <UI_BASIS_URL>/team/kalender/google/zurueck eintragen und
# die Calendar API aktivieren.
#
# Schreibt GOOGLE_KALENDER_CLIENT_ID und GOOGLE_KALENDER_CLIENT_SECRET.
# Wiederholbar: vorhandene Zeilen werden ersetzt, alles andere bleibt.
#
# Sicherheit (wie deploy/postfach-zugang.sh): beide Werte werden verdeckt
# gelesen (read -s) und erscheinen NIRGENDS - weder in einer Ausgabe noch als
# Argument eines Programms; in die Datei schreibt printf (eingebaut). Kein
# set -x. Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
# Startet nichts neu: die Dienste lesen die .env erst nach einem Neustart.
set +x
set -euo pipefail

ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

# 1) Lesen und pruefen. Erlaubt sind nur Zeichen, die in der .env ohne
# Anfuehrungszeichen woertlich bleiben.
client_id=""
IFS= read -r -s -p "Google Client-ID (Eingabe bleibt unsichtbar): " client_id || true
[ -t 0 ] && echo >&2
client_id="${client_id%$'\r'}"
client_secret=""
IFS= read -r -s -p "Google Client-Secret (Eingabe bleibt unsichtbar): " client_secret || true
[ -t 0 ] && echo >&2
client_secret="${client_secret%$'\r'}"
if [ -z "$client_id" ] || [ -z "$client_secret" ]; then
  echo "Client-ID oder Client-Secret ist leer – abgebrochen, nichts geändert." >&2
  exit 3
fi
if ! [[ $client_id =~ ^[A-Za-z0-9._~-]+$ ]] || ! [[ $client_secret =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
  echo "Ein Wert enthält Leerzeichen, Anführungszeichen oder Sonderzeichen – abgebrochen, nichts geändert." >&2
  exit 3
fi

# 2) Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
SICHERUNG="$ENV_DATEI.vor-google-kalender-$(date +%Y%m%d-%H%M%S)"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"
chmod 600 "$SICHERUNG"

NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev '^(GOOGLE_KALENDER_CLIENT_ID|GOOGLE_KALENDER_CLIENT_SECRET)=' "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then
  printf '\n' >> "$NEU"
fi
printf 'GOOGLE_KALENDER_CLIENT_ID=%s\n' "$client_id" >> "$NEU"
printf 'GOOGLE_KALENDER_CLIENT_SECRET=%s\n' "$client_secret" >> "$NEU"
unset client_id client_secret
chmod 600 "$NEU"
mv -f "$NEU" "$ENV_DATEI"
trap - EXIT
echo "Google-Zugangsdaten eingetragen (Sicherung: $(basename "$SICHERUNG"))."
echo "Die Dienste lesen die .env erst nach Neustart – mit dem Betreiber abstimmen."
