#!/usr/bin/env bash
# deploy/post-schluessel.sh — erzeugt das Schluesselpaar fuer versiegelte
# Postfach-Zugaenge (Post-Sammelstelle, 03.11.2026). Einmalig; wiederholbar.
#
#   bash ~/sales-claw/deploy/post-schluessel.sh
#
# Schreibt POST_SCHLUESSEL_OEFFENTLICH (fuer die UI) und POST_SCHLUESSEL_PRIVAT
# (nur fuer den Abholdienst) als base64 des PEM, eine Zeile je Variable, in die
# .env. Steht POST_SCHLUESSEL_PRIVAT dort schon mit Wert, passiert nichts
# ("schon vorhanden") - ein zweites Paar wuerde alle versiegelten Zugaenge
# unlesbar machen.
#
# Sicherheit (wie deploy/auto-anbinden.sh): Schluessel erscheinen NIRGENDS -
# weder Ausgabe noch Argument; sie wandern nur ueber Shell-Variablen und printf
# (eingebaut) in die Datei. Kein set -x. Sicherung (600), neue Datei im selben
# Ordner (600), mv darueber. Startet nichts neu.
set +x
set -euo pipefail

ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

if grep -Eq '^POST_SCHLUESSEL_PRIVAT=.+' "$ENV_DATEI"; then
  echo "POST_SCHLUESSEL_PRIVAT schon vorhanden – nichts geändert."
  exit 0
fi

command -v openssl >/dev/null || { echo "openssl fehlt – abgebrochen, nichts geändert." >&2; exit 1; }

# 1) Paar erzeugen (RSA-3072); nur in Variablen, base64 ohne Zeilenumbruch.
PRIVAT="$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 2>/dev/null)"
OEFFENTLICH="$(printf '%s\n' "$PRIVAT" | openssl pkey -pubout 2>/dev/null | base64 | tr -d '\n')"
PRIVAT="$(printf '%s\n' "$PRIVAT" | base64 | tr -d '\n')"
if [ -z "$PRIVAT" ] || [ -z "$OEFFENTLICH" ]; then
  echo "Schlüsselerzeugung fehlgeschlagen – abgebrochen, nichts geändert." >&2
  exit 1
fi

# 2) Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
SICHERUNG="$ENV_DATEI.vor-post-schluessel-$(date +%Y%m%d-%H%M%S)"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"; chmod 600 "$SICHERUNG"
NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev '^(POST_SCHLUESSEL_PRIVAT|POST_SCHLUESSEL_OEFFENTLICH)=' "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then printf '\n' >> "$NEU"; fi
printf 'POST_SCHLUESSEL_OEFFENTLICH=%s\n' "$OEFFENTLICH" >> "$NEU"
printf 'POST_SCHLUESSEL_PRIVAT=%s\n' "$PRIVAT" >> "$NEU"
unset PRIVAT OEFFENTLICH
chmod 600 "$NEU"; mv -f "$NEU" "$ENV_DATEI"; trap - EXIT
echo "Schlüsselpaar eingetragen (Sicherung: $(basename "$SICHERUNG"))."
echo "Die Dienste lesen die .env erst nach Neustart – mit dem Betreiber abstimmen."
