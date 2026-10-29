#!/usr/bin/env bash
# Traegt PM_TOKEN_SALES (Token des Ladens sales bei pm-claw, 29.10.2026) in die
# .env des Basis-Ladens ein und bindet danach pm-claw an
# (deploy/pm-anbinden.sh, das den Token selbst aus der .env liest).
#
#   bash ~/sales-claw/deploy/pm-token-eintragen.sh                  # eintragen + anbinden
#   bash ~/sales-claw/deploy/pm-token-eintragen.sh --ohne-anbinden  # nur eintragen
#
# Den Token kopiert der Betreiber selbst aus ~/pm-claw/.env und fuegt ihn hier
# ein. Dieses Skript liest pm-claw nicht (Auftrag: nicht erfinden, nicht aus
# dem pm-claw-Repo lesen).
#
# Sicherheit (wie deploy/postfach-zugang.sh):
# * Verdeckt gelesen (read -s), NIE ausgegeben, auch nicht teilweise. Kein set -x.
# * Nie als Argument an ein Programm; in die Datei schreibt printf (eingebaut).
#   pm-anbinden.sh bekommt ihn weder als Argument noch in der Umgebung.
# * Nur Zeichen, die Compose woertlich nimmt ([A-Za-z0-9._~+/=-]); sonst Abbruch.
# * Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
#
# sales-mcp/tests/test_pm_token_eintragen.py prueft den Ablauf.
set +x
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"
PM_ANBINDEN="${PM_ANBINDEN:-$WURZEL/deploy/pm-anbinden.sh}"
NAME="PM_TOKEN_SALES"

anbinden=true
case "${1:-}" in
  "") ;;
  --ohne-anbinden) anbinden=false ;;
  *) echo "Aufruf: $0 [--ohne-anbinden]" >&2; exit 2 ;;
esac

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

# 1) Lesen und pruefen.
token=""
IFS= read -r -s -p "PM_TOKEN_SALES aus ~/pm-claw/.env einfügen (Eingabe bleibt unsichtbar): " token || true
[ -t 0 ] && echo >&2
token="${token%$'\r'}"
if [ -z "$token" ]; then
  echo "Eingabe ist leer – abgebrochen, nichts geändert." >&2
  exit 3
fi
if [ "${#token}" -lt 20 ] || [ "${#token}" -gt 512 ]; then
  echo "Die Eingabe hat ${#token} Zeichen – ein Token hat 20 bis 512. Abgebrochen, nichts geändert." >&2
  exit 3
fi
if ! [[ $token =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
  echo "Die Eingabe enthält Leerzeichen, Anführungszeichen, \$, # oder andere Sonderzeichen – so lässt sie sich nicht sicher speichern. Abgebrochen, nichts geändert." >&2
  exit 3
fi

# 2) Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
stempel="$(date +%Y%m%d-%H%M%S)"
SICHERUNG="$ENV_DATEI.vor-pm-token-$stempel"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"
chmod 600 "$SICHERUNG"

NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev "^$NAME=" "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then
  printf '\n' >> "$NEU"
fi
printf '%s=%s\n' "$NAME" "$token" >> "$NEU"
unset token
chmod 600 "$NEU"
mv -f "$NEU" "$ENV_DATEI"
trap - EXIT
echo "$NAME eingetragen (Sicherung: $(basename "$SICHERUNG"))."

# 3) Anbinden. pm-anbinden.sh liest den Token selbst aus der .env.
$anbinden || exit 0
echo "Binde pm-claw an …"
rc=0
bash "$PM_ANBINDEN" || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "Anbindung rot (siehe oben). Der Token steht in der .env. War er falsch: dieses Skript einfach erneut ausführen." >&2
  exit "$rc"
fi
