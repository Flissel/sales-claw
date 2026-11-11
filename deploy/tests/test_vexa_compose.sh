#!/usr/bin/env bash
# Prueft deploy/vexa/ (Vexa als eigenes Compose-Projekt, Meeting-Mittelpunkt
# Task 15) ohne Docker-Daemon und ohne Netz: statische Pruefung der Dateien.
# `docker compose config` laeuft zusaetzlich, wenn `docker compose` am Ort
# vorhanden ist; sonst wird dieser Teil uebersprungen (und gemeldet).
#
#   bash deploy/tests/test_vexa_compose.sh
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$WURZEL/deploy/vexa/docker-compose.yml"
BEISPIEL="$WURZEL/deploy/vexa/.env.example"
SKRIPT="$WURZEL/deploy/vexa-anbinden.sh"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

[ -f "$COMPOSE" ]  || fehler "deploy/vexa/docker-compose.yml fehlt"
[ -f "$BEISPIEL" ] || fehler "deploy/vexa/.env.example fehlt"
[ -f "$SKRIPT" ]   || fehler "deploy/vexa-anbinden.sh fehlt"

# CRLF wuerde Compose und bash gleichermassen stoeren.
for d in "$COMPOSE" "$BEISPIEL" "$SKRIPT"; do
  if grep -q $'\r' "$d"; then fehler "$(basename "$d") hat CRLF-Zeilenenden"; fi
done

# Kommentare und Leerzeilen weg: geprueft wird nur, was Compose liest.
AKTIV="$(sed -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$COMPOSE")"

# Projektname
echo "$AKTIV" | grep -qx 'name: vexa' || fehler "Projektname ist nicht 'name: vexa'"

# Jedes image: per Digest gepinnt (@sha256: + 64 Hex), mindestens vier Dienste.
n_image=0
while IFS= read -r zeile; do
  n_image=$((n_image + 1))
  [[ $zeile =~ @sha256:[0-9a-f]{64}[[:space:]\"\']*$ ]] || fehler "image ohne Digest: $zeile"
done < <(echo "$AKTIV" | grep -E '^[[:space:]]+image:')
[ "$n_image" -ge 4 ] || fehler "erwartet mindestens 4 image-Zeilen, gefunden $n_image"

# Kein 0.0.0.0 irgendwo (auch nicht als Kommentar).
if grep -q '0\.0\.0\.0' "$COMPOSE"; then fehler "0.0.0.0 in docker-compose.yml"; fi

# Jeder ports:-Eintrag beginnt mit 127.0.0.1:, und es gibt genau einen (Gateway).
n_ports=0
in_ports=0
while IFS= read -r zeile; do
  if [[ $zeile =~ ^[[:space:]]+ports:[[:space:]]*$ ]]; then in_ports=1; continue; fi
  if [ "$in_ports" = 1 ]; then
    if [[ $zeile =~ ^[[:space:]]+-[[:space:]]+(.*)$ ]]; then
      eintrag="${BASH_REMATCH[1]//[\"\']/}"
      n_ports=$((n_ports + 1))
      [[ $eintrag == 127.0.0.1:* ]] || fehler "ports-Eintrag nicht auf 127.0.0.1: $eintrag"
      [ "$eintrag" = "127.0.0.1:8056:8056" ] || fehler "unerwarteter Port: $eintrag"
    else
      in_ports=0
    fi
  fi
done <<< "$AKTIV"
[ "$n_ports" -eq 1 ] || fehler "erwartet genau 1 ports-Eintrag (Gateway), gefunden $n_ports"

# Dienstebloecke herausziehen: Zeilen von "  <dienst>:" bis zum naechsten Dienst.
block() {
  echo "$AKTIV" | awk -v d="$1" '
    /^[^[:space:]]/ { in_services = ($0 == "services:") ; next }
    in_services && /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") ; next }
    in_services && aktiv { print }'
}
for dienst in vexa-lite vexa-lite-whisper vexa-lite-postgres vexa-lite-storage; do
  [ -n "$(block "$dienst")" ] || fehler "Dienst $dienst fehlt"
done

# vexa-lite: Prozess-Backend, Jitsi-Host, Port, Netz sales-claw_default.
LITE="$(block vexa-lite)"
echo "$LITE" | grep -qE 'RUNTIME_BACKEND:[[:space:]]*"?process"?[[:space:]]*$' || fehler "RUNTIME_BACKEND: process fehlt"
echo "$LITE" | grep -qE 'VEXA_JITSI_HOSTS:[[:space:]]*"?meet\.ffmuc\.net"?[[:space:]]*$' || fehler "VEXA_JITSI_HOSTS fehlt"
echo "$LITE" | grep -qE '^[[:space:]]+-[[:space:]]*salesclaw[[:space:]]*$' || fehler "vexa-lite haengt nicht an sales-claw_default (Netz-Schluessel salesclaw)"
echo "$LITE" | grep -qE '^[[:space:]]+-[[:space:]]*default[[:space:]]*$' || fehler "vexa-lite haengt nicht (mehr) an vexa_default"
if echo "$LITE" | grep -qE 'ANTHROPIC_|HOST_CLAUDE_CREDENTIALS|docker\.sock'; then
  fehler "vexa-lite: Agent-Schluessel oder Docker-Socket gesetzt (Spec 5.4: Agent aus)"
fi
# Whisper: Modell, kein Port.
block vexa-lite-whisper | grep -qE 'WHISPER__MODEL:[[:space:]]*"?Systran/faster-whisper-small"?[[:space:]]*$' || fehler "Whisper-Modell nicht Systran/faster-whisper-small"
# Nur vexa-lite darf an sales-claw_default; Postgres/Speicher/Whisper nur vexa_default.
for dienst in vexa-lite-whisper vexa-lite-postgres vexa-lite-storage; do
  if block "$dienst" | grep -q 'sales-claw_default\|salesclaw'; then
    fehler "$dienst darf nicht an sales-claw_default"
  fi
done

# Netz sales-claw_default ist extern deklariert.
echo "$AKTIV" | grep -qE '^[[:space:]]+name:[[:space:]]*sales-claw_default[[:space:]]*$' || fehler "Netz sales-claw_default nicht deklariert"
echo "$AKTIV" | grep -qE '^[[:space:]]+external:[[:space:]]*true[[:space:]]*$' || fehler "Netz sales-claw_default nicht external: true"

# Volumes: Namen mit Praefix vexa-, genau die drei erwarteten, keine Bind-Mounts.
for v in vexa-pgdata vexa-storagedata vexa-whisper-modelle; do
  echo "$AKTIV" | grep -qE "^[[:space:]]+name:[[:space:]]*$v[[:space:]]*$" || fehler "Volume-Name $v fehlt"
done
while IFS= read -r zeile; do
  [[ $zeile =~ name:[[:space:]]*(.*)$ ]] || continue
  w="${BASH_REMATCH[1]}"
  case "$w" in vexa-*|sales-claw_default|vexa_default|vexa) ;; *) fehler "Name ohne vexa-Praefix: $w" ;; esac
done < <(echo "$AKTIV" | grep -E '^[[:space:]]+name:')
if echo "$AKTIV" | grep -qE '^[[:space:]]+-[[:space:]]+["'\'']?(\.|/|~)'; then
  fehler "Bind-Mount oder absoluter Pfad in der Compose-Datei"
fi

# .env.example: nur Platzhalter, kein echtes Geheimnis; Namen wie im Compose.
for name in ADMIN_TOKEN VEXA_DB_PASSWORD VEXA_S3_ACCESS_KEY VEXA_S3_SECRET_KEY; do
  grep -qE "^$name=" "$BEISPIEL" || fehler ".env.example kennt $name nicht"
  grep -q "\${$name" "$COMPOSE" || fehler "Compose nutzt $name nicht"
done

# Anbinde-Skript: Syntax, kein set -x, Muster der Kanal-Skripte.
bash -n "$SKRIPT" || fehler "bash -n deploy/vexa-anbinden.sh"
if grep -qE '^[[:space:]]*set[[:space:]]+-[a-z]*x' "$SKRIPT"; then fehler "vexa-anbinden.sh: set -x"; fi
grep -q 'chmod 600' "$SKRIPT" || fehler "vexa-anbinden.sh setzt keine 600er Rechte"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -S warning "$SKRIPT" || fehler "shellcheck deploy/vexa-anbinden.sh"
else
  echo "HINWEIS: shellcheck nicht vorhanden, uebersprungen"
fi

# docker compose config nur, wenn es lokal laeuft (braucht keinen Daemon).
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ausgabe="$(docker compose -f "$COMPOSE" --env-file "$BEISPIEL" config 2>&1)" \
    || fehler "docker compose config: $ausgabe"
  if echo "$ausgabe" | grep -q '0\.0\.0\.0'; then fehler "gerendert enthaelt 0.0.0.0"; fi
  echo "$ausgabe" | grep -q 'host_ip: 127.0.0.1' || fehler "gerendert: kein host_ip 127.0.0.1"
  echo "OK: docker compose config gueltig"
else
  echo "HINWEIS: docker compose nicht vorhanden, config-Pruefung uebersprungen"
fi

echo "OK: vexa-compose"
