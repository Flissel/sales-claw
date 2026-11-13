#!/usr/bin/env bash
# Test fuer deploy/warteliste-anbinden.sh (braucht openssl).
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/warteliste-anbinden.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
ENVD="$T/.env"
URL="https://abc.example.co"
API="sb_publishable_0123456789abcdefghij"

fehler() { echo "FEHLER: $*"; exit 1; }
lauf() { SALES_ENV_DATEI="$ENVD" bash "$SKRIPT" "$@"; }
schluessel() { grep -E '^WARTELISTE_ABHOL_SCHLUESSEL=' "$ENVD" | cut -d= -f2-; }

# 1. Ohne .env, ohne oder mit kaputten Argumenten: Abbruch, nichts geschrieben
if lauf "$URL" "$API" >/dev/null 2>&1; then fehler "ohne .env angenommen"; fi
printf 'ANDERES=bleibt\nWARTELISTE_URL=https://alt.example\n' > "$ENVD"
vorher="$(cat "$ENVD")"
if lauf >/dev/null 2>&1; then fehler "ohne Argumente angenommen"; fi
if lauf "http://abc.example.co" "$API" >/dev/null 2>&1; then fehler "http angenommen"; fi
if lauf "$URL/rest/v1" "$API" >/dev/null 2>&1; then fehler "Adresse mit Pfad angenommen"; fi
if lauf "$URL" "kurz" >/dev/null 2>&1; then fehler "kurzer oeffentlicher Schluessel angenommen"; fi
[ "$(cat "$ENVD")" = "$vorher" ] || fehler "trotz Abbruch geschrieben"
[ -z "$(ls "$T" | grep -v '^\.env$' || true)" ] || fehler "trotz Abbruch Dateien hinterlassen"

# 2. Erster Lauf: drei Werte, fremde Zeilen bleiben, alte Adresse ersetzt, Sicherung da
aus="$(lauf "$URL" "$API")"
grep -qx 'ANDERES=bleibt' "$ENVD" || fehler "fremde Zeile verloren"
grep -qx "WARTELISTE_URL=$URL" "$ENVD" || fehler "Adresse nicht eingetragen"
[ "$(grep -c '^WARTELISTE_URL=' "$ENVD")" = 1 ] || fehler "Adresse doppelt"
grep -qx "WARTELISTE_API_SCHLUESSEL=$API" "$ENVD" || fehler "oeffentlicher Schluessel nicht eingetragen"
K1="$(schluessel)"
[[ "$K1" =~ ^[0-9a-f]{64}$ ]] || fehler "Abholschluessel hat nicht 64 Hex-Zeichen"
ls "$T"/.env.vor-warteliste-* >/dev/null 2>&1 || fehler "keine Sicherung"
[ -z "$(ls "$T"/.env.neu.* 2>/dev/null || true)" ] || fehler "Zwischendatei liegen geblieben"

# 3. Der Schluessel steht nicht in der Ausgabe, sein Hash schon
case "$aus" in *"$K1"*) fehler "Abholschluessel in der Ausgabe" ;; esac
H1="$(printf '%s' "$K1" | openssl dgst -sha256 -r | cut -d' ' -f1)"
case "$aus" in *"VALUES ('$H1', "*) : ;; *) fehler "Hash fehlt in der Ausgabe oder ist falsch" ;; esac
case "$aus" in *"private.waitlist_export_keys"*) : ;; *) fehler "Eintrage-Befehl fehlt" ;; esac

# 4. Zweiter Lauf: derselbe Schluessel, derselbe Hash
aus2="$(lauf "$URL" "$API")"
[ "$(schluessel)" = "$K1" ] || fehler "zweiter Lauf hat einen neuen Schluessel erzeugt"
case "$aus2" in *"$H1"*) : ;; *) fehler "zweiter Lauf zeigt einen anderen Hash" ;; esac
case "$aus2" in *"$K1"*) fehler "Abholschluessel in der Ausgabe (zweiter Lauf)" ;; esac
[ "$(grep -c '^WARTELISTE_ABHOL_SCHLUESSEL=' "$ENVD")" = 1 ] || fehler "Schluessel doppelt"

# 5. Rotation: Zeile entfernt -> neuer Schluessel, neuer Hash
grep -v '^WARTELISTE_ABHOL_SCHLUESSEL=' "$ENVD" > "$T/ohne"; mv "$T/ohne" "$ENVD"
aus3="$(lauf "$URL" "$API")"
K2="$(schluessel)"
[ "$K2" != "$K1" ] || fehler "Rotation hat denselben Schluessel geliefert"
case "$aus3" in *"$H1"*) fehler "Rotation zeigt den alten Hash" ;; esac

echo "OK: warteliste-anbinden.sh"
