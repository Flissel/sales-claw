#!/usr/bin/env bash
# deploy/warteliste-anbinden.sh <WARTELISTE_URL> <WARTELISTE_API_SCHLUESSEL>
#
# Richtet den Zugang fuer den Wartelisten-Abgleich ein (seit 13.11.2026).
# Einmalig; wiederholbar.
#
#   bash ~/sales-claw/deploy/warteliste-anbinden.sh https://<projekt>.supabase.co <oeffentlicher-schluessel>
#
# Die beiden Argumente sind oeffentlich (sie stehen im Browser jedes
# Besuchers der Website). Der geheime Abholschluessel entsteht HIER und
# verlaesst die Maschine nie: in die Website-Datenbank kommt nur sein
# SHA-256, den dieses Skript ausgibt.
#
# Steht WARTELISTE_ABHOL_SCHLUESSEL schon mit Wert in der .env, wird kein
# neuer erzeugt; das Skript zeigt nur noch einmal den Hash. Ein neuer
# Schluessel (Rotation): Zeile in der .env loeschen, Skript erneut starten,
# neuen Hash eintragen, alten in der Website-Datenbank entziehen.
#
# Sicherheit (wie deploy/post-schluessel.sh): der Schluessel erscheint
# NIRGENDS - weder Ausgabe noch Argument; er wandert nur ueber Shell-Variablen
# und printf (eingebaut). Kein set -x. Sicherung (600), neue Datei im selben
# Ordner (600), mv darueber. Startet nichts neu.
set +x
set -euo pipefail

ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"
URL="${1:-}"
API="${2:-}"

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi
if ! [[ "$URL" =~ ^https://[A-Za-z0-9.-]+$ ]]; then
  echo "Erstes Argument muss die https-Adresse der Website-Datenbank sein (ohne Pfad) – abgebrochen, nichts geändert." >&2
  exit 1
fi
if ! [[ "$API" =~ ^[A-Za-z0-9._-]{20,}$ ]]; then
  echo "Zweites Argument muss der öffentliche Schlüssel der Website sein – abgebrochen, nichts geändert." >&2
  exit 1
fi
command -v openssl >/dev/null || { echo "openssl fehlt – abgebrochen, nichts geändert." >&2; exit 1; }

hash_zeigen() {
  # sha256 ueber die 64 Hex-Zeichen, wie waitlist_export() in der Website-Datenbank rechnet.
  printf '%s' "$1" | openssl dgst -sha256 -r | cut -d' ' -f1
}

VORHANDEN="$({ grep -E '^WARTELISTE_ABHOL_SCHLUESSEL=' "$ENV_DATEI" || true; } | head -1 | cut -d= -f2- | tr -d '\r" ')"
if [[ "$VORHANDEN" =~ ^[0-9a-f]{64}$ ]]; then
  ABHOL="$VORHANDEN"
  NEU_ERZEUGT=0
else
  ABHOL="$(openssl rand -hex 32)"
  NEU_ERZEUGT=1
  if ! [[ "$ABHOL" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Schlüsselerzeugung fehlgeschlagen – abgebrochen, nichts geändert." >&2
    exit 1
  fi
fi
unset VORHANDEN

# Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
SICHERUNG="$ENV_DATEI.vor-warteliste-$(date +%Y%m%d-%H%M%S)"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"; chmod 600 "$SICHERUNG"
NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev '^(WARTELISTE_URL|WARTELISTE_API_SCHLUESSEL|WARTELISTE_ABHOL_SCHLUESSEL)=' "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then printf '\n' >> "$NEU"; fi
printf 'WARTELISTE_URL=%s\n' "$URL" >> "$NEU"
printf 'WARTELISTE_API_SCHLUESSEL=%s\n' "$API" >> "$NEU"
printf 'WARTELISTE_ABHOL_SCHLUESSEL=%s\n' "$ABHOL" >> "$NEU"
chmod 600 "$NEU"; mv -f "$NEU" "$ENV_DATEI"; trap - EXIT

HASH="$(hash_zeigen "$ABHOL")"
unset ABHOL
if [ "$NEU_ERZEUGT" = 1 ]; then
  echo "Abholschlüssel erzeugt und eingetragen (Sicherung: $(basename "$SICHERUNG"))."
else
  echo "Abholschlüssel war schon vorhanden; Adresse und öffentlicher Schlüssel eingetragen (Sicherung: $(basename "$SICHERUNG"))."
fi
echo
echo "In der Website-Datenbank einmal ausführen (der Hash ist kein Geheimnis):"
echo "  INSERT INTO private.waitlist_export_keys (key_hash, label) VALUES ('$HASH', 'sales-claw $(hostname)');"
echo
echo "Danach prüfen:  bash $PROJEKT/deploy/warteliste-abgleich.sh --trocken"
