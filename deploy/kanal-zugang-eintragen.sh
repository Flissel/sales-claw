#!/usr/bin/env bash
# Traegt den Zugang eines eigenen Kanals (Bluesky, Mastodon, Telegram-Kanal,
# Discord, dev.to) in die .env des Basis-Ladens ein und erzeugt NUR den
# Dienst sales-kanaele neu.
#
#   bash ~/sales-claw/deploy/kanal-zugang-eintragen.sh <kanal>
#   kanal: bluesky | mastodon | telegram_kanal | discord | devto
#
# Regelweg ist der PC-Befehl `kanal-zugang speichern <kanal>` (Vibemind_V1,
# scripts/kanal_zugang.py): der OpenFang-Tresor am PC ist die Wahrheit, der
# Befehl reicht die Werte ueber ssh-stdin an dieses Skript. Von Hand
# aufgerufen ist es der Notweg (PC aus) — danach den Wert auch im Tresor
# speichern, sonst ueberschreibt der naechste Abgleich ihn.
#
# Abfragen ohne Geheimnis (fuer den PC-Befehl, lesen nichts, schreiben nichts):
#   --kanaele          alle Kanaele, durch Leerzeichen getrennt
#   --namen <kanal>    die Env-Namen des Kanals in Eingabe-Reihenfolge
#
# Sicherheit (Plan 2026-10-24-kanaele-posten, Task 9):
# * Werte werden verdeckt gelesen (read -s) und NIE ausgegeben, auch nicht
#   teilweise — weder in Meldungen noch im Fehlerfall. Kein set -x.
# * Werte gehen nie als Argument an ein Programm (ps zeigte sie sonst),
#   nur ueber eingebaute Befehle (printf) direkt in die Datei.
# * Nur Zeichen aus [A-Za-z0-9._:/@+=~%?&-] — alles andere (vor allem `$`,
#   Leerzeichen, `#`, Anfuehrungszeichen) wuerde Compose beim Lesen der
#   .env interpolieren oder abschneiden. Dann Abbruch, nichts geschrieben.
# * Erst wenn ALLE Werte gelesen und geprueft sind, wird die .env angefasst:
#   Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
#
# Die Namen stehen woertlich wie in sales-mcp/kanaele.py (KANAELE[*].env_namen);
# sales-mcp/tests/test_kanal_deploy.py prueft den Gleichlauf.
set +x
set -euo pipefail

ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"
DOCKER="${DOCKER:-docker}"
ERLAUBT='^[A-Za-z0-9._:/@+=~%?&-]+$'
KANAL_LISTE="bluesky mastodon telegram_kanal discord devto"

if [ "${1:-}" = "--kanaele" ]; then
  echo "$KANAL_LISTE"
  exit 0
fi
nur_namen=0
if [ "${1:-}" = "--namen" ]; then
  nur_namen=1
  shift
fi

kanal="${1:-}"
case "$kanal" in
  bluesky)        NAMEN=(BLUESKY_HANDLE BLUESKY_APP_PASSWORD) ;;
  mastodon)       NAMEN=(MASTODON_INSTANCE MASTODON_TOKEN) ;;
  telegram_kanal) NAMEN=(TELEGRAM_KANAL_ID TELEGRAM_KANAL_BOT_TOKEN) ;;
  discord)        NAMEN=(DISCORD_ANKUENDIGUNG_WEBHOOK) ;;
  devto)          NAMEN=(DEVTO_API_KEY) ;;
  *)
    echo "Aufruf: $0 <kanal> — bekannte Kanäle: $KANAL_LISTE" >&2
    exit 2 ;;
esac

if [ "$nur_namen" = 1 ]; then
  echo "${NAMEN[*]}"
  exit 0
fi

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

# 1) Alle Werte lesen und pruefen, bevor irgendetwas geschrieben wird.
WERTE=()
for name in "${NAMEN[@]}"; do
  wert=""
  # read liefert bei EOF ohne Zeilenende != 0, der gelesene Rest zaehlt
  # trotzdem; ein leerer Wert faellt gleich darunter auf.
  IFS= read -r -s -p "$name: " wert || true
  [ -t 0 ] && echo >&2
  wert="${wert%$'\r'}"
  if [ -z "$wert" ]; then
    echo "$name ist leer – abgebrochen, nichts geändert." >&2
    exit 3
  fi
  if ! [[ $wert =~ $ERLAUBT ]]; then
    echo "$name enthält unzulässige Zeichen – abgebrochen, nichts geändert." >&2
    exit 3
  fi
  WERTE+=("$wert")
done
unset wert

# 2) Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
stempel="$(date +%Y%m%d-%H%M%S)"
SICHERUNG="$ENV_DATEI.vor-$kanal-$stempel"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"
chmod 600 "$SICHERUNG"

NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
muster="^($(IFS='|'; echo "${NAMEN[*]}"))="
# grep: Exit 1 = keine Zeile uebrig (kein Fehler), 2 = echter Fehler
grep -Ev "$muster" "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
# Alte Datei ohne Zeilenende am Schluss: sonst klebte der erste neue
# Eintrag an der letzten alten Zeile.
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then
  printf '\n' >> "$NEU"
fi
for i in "${!NAMEN[@]}"; do
  printf '%s=%s\n' "${NAMEN[$i]}" "${WERTE[$i]}" >> "$NEU"
done
unset WERTE
chmod 600 "$NEU"
mv -f "$NEU" "$ENV_DATEI"
trap - EXIT

# 3) Nur sales-kanaele neu erzeugen — erst `up` liest die Umgebung neu.
# shellcheck disable=SC2086
if ! ( cd "$PROJEKT" && $DOCKER compose up -d --no-deps --force-recreate sales-kanaele ); then
  echo "${#NAMEN[@]} Wert(e) für $kanal eingetragen (Sicherung: $(basename "$SICHERUNG")), aber sales-kanaele ließ sich nicht neu erzeugen – siehe Meldung oben." >&2
  exit 1
fi
echo "${#NAMEN[@]} Wert(e) für $kanal eingetragen, Sicherung: $(basename "$SICHERUNG"). sales-kanaele neu erzeugt – Stand unter /einstellungen/kanaele."
