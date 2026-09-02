#!/usr/bin/env bash
# deploy/openwa-patch-anwenden.sh — die lokalen OpenWA-Patches auf das
# Nested-Repo openwa/upstream anwenden.
#
# Grundsatz: der Stand des Nested-Repos ist IMMER "Pin + Patches", nichts
# anderes. Darum werden zuerst alle nachgefuehrten Aenderungen auf den Pin
# zurueckgesetzt und dann alle Patches der Reihe nach frisch angewendet.
# So greift auch ein GEAENDERTER Patch (02.09.2026: 0002 wuchs von zwei auf
# vier Dateien — die alte Fassung waere weder rueckwaerts noch vorwaerts
# anwendbar gewesen, und ein "uebersprungen" haette den Fehler versteckt).
# Jeder Patch wird mit --check geprueft, BEVOR etwas halb eingespielt ist.
set -euo pipefail

WURZEL="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM="$WURZEL/openwa/upstream"
PATCHES="$WURZEL/deploy/openwa-patches"

if [ ! -d "$UPSTREAM/.git" ]; then
  echo "FEHLER: $UPSTREAM ist kein Git-Checkout — erst klonen (Pin siehe docs/04)." >&2
  exit 1
fi

geaendert="$(git -C "$UPSTREAM" status --short --untracked-files=no)"
if [ -n "$geaendert" ]; then
  echo "setze nachgefuehrte Aenderungen auf den Pin zurueck:"
  echo "$geaendert"
  git -C "$UPSTREAM" checkout -- .
fi

for patch in "$PATCHES"/*.patch; do
  name="$(basename "$patch")"
  if ! git -C "$UPSTREAM" apply --check "$patch"; then
    echo "FEHLER: $name passt nicht auf den Pin — Stand ist jetzt der nackte Pin, nichts angewendet." >&2
    exit 1
  fi
  git -C "$UPSTREAM" apply "$patch"
  echo "angewendet: $name"
done

echo "Stand des Nested-Repos (Pin + Patches):"
git -C "$UPSTREAM" status --short --untracked-files=no
