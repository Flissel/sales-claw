#!/usr/bin/env bash
# deploy/marketing-aktualisieren.sh — zieht den schlanken vibemind-os-
# Checkout der Marketing-Seite nach und startet marketing-api neu, wenn sich
# unter spaces/marketing etwas geaendert hat (Spec 2026-09-25-marketing-
# schalter-design.md §3.1). Aufgerufen am Ende von update.sh, NICHT fatal
# fuer den Sales-Laden: ein Fehler hier rollt Sales nie zurueck.
set -euo pipefail
export LC_ALL=C
MARKETING_OS="${MARKETING_OS:-$HOME/marketing-os}"
SYSTEMCTL="${SYSTEMCTL:-sudo systemctl}"

if [ ! -d "$MARKETING_OS/.git" ]; then
  echo "Marketing-Seite: nicht eingerichtet ($MARKETING_OS fehlt) - uebersprungen."
  exit 0
fi
cd "$MARKETING_OS"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ABBRUCH Marketing-Seite: lokale Aenderungen in $MARKETING_OS." >&2
  exit 1
fi
ALT="$(git rev-parse HEAD)"
git fetch origin master --quiet
git merge --ff-only --quiet origin/master
NEU="$(git rev-parse HEAD)"
if [ "$ALT" = "$NEU" ]; then
  echo "Marketing-Seite: aktuell ($NEU)."
  exit 0
fi
if git diff --name-only "$ALT" "$NEU" | grep -qE '^spaces/(__init__\.py|marketing/)'; then
  $SYSTEMCTL restart marketing-api
  echo "Marketing-Seite: $ALT -> $NEU, neu gestartet."
else
  echo "Marketing-Seite: $ALT -> $NEU, nichts Relevantes geaendert."
fi
