#!/usr/bin/env bash
# Prueft deploy/marketing-aktualisieren.sh gegen ein lokales Wegwerf-Repo.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/arbeit" 2>/dev/null
( cd "$T/arbeit" && git checkout -q -b master && mkdir -p spaces/marketing \
  && echo a > spaces/marketing/x && git add . && git -c user.name=t \
  -c user.email=t@t commit -qm eins && git push -q origin master )
git clone -q -b master "$T/origin.git" "$T/marketing-os"

# 1) fehlt der Checkout: 0 und Hinweis
out="$(MARKETING_OS="$T/fehlt" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
echo "$out" | grep -q "nicht eingerichtet"

# 2) nichts Neues: kein Neustart
out="$(MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
if echo "$out" | grep -q "restart marketing-api"; then
  echo "FEHLER: Neustart ohne Aenderung"; exit 1; fi

# 3) neuer Stand unter spaces/marketing: vorspulen und Neustart
( cd "$T/arbeit" && echo b > spaces/marketing/x && git -c user.name=t \
  -c user.email=t@t commit -qam zwei && git push -q origin master )
out="$(MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
echo "$out" | grep -q "restart marketing-api"
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = b ]

# 4) lokale Aenderung: Abbruch mit Nicht-Null, nichts ueberschrieben
echo lokal > "$T/marketing-os/spaces/marketing/x"
if MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh"; then
  echo "FEHLER: lokale Aenderung nicht erkannt"; exit 1; fi
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = lokal ]
echo "OK marketing-aktualisieren"
