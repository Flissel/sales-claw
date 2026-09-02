#!/usr/bin/env bash
# deploy/openwa-patch-anwenden.sh — die lokalen OpenWA-Patches auf das
# Nested-Repo openwa/upstream anwenden. Idempotent: ein schon angewendeter
# Patch wird erkannt (reverse-check) und uebersprungen; ein nicht
# anwendbarer bricht ab, BEVOR etwas halb eingespielt ist.
set -euo pipefail

WURZEL="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM="$WURZEL/openwa/upstream"
PATCHES="$WURZEL/deploy/openwa-patches"

if [ ! -d "$UPSTREAM/.git" ]; then
  echo "FEHLER: $UPSTREAM ist kein Git-Checkout — erst klonen (Pin siehe docs/04)." >&2
  exit 1
fi

for patch in "$PATCHES"/*.patch; do
  name="$(basename "$patch")"
  if git -C "$UPSTREAM" apply --check --reverse "$patch" >/dev/null 2>&1; then
    echo "uebersprungen (schon drin): $name"
    continue
  fi
  if ! git -C "$UPSTREAM" apply --check "$patch"; then
    echo "FEHLER: $name passt nicht auf den aktuellen Upstream-Stand — nichts angewendet." >&2
    exit 1
  fi
  git -C "$UPSTREAM" apply "$patch"
  echo "angewendet: $name"
done

echo "Stand des Nested-Repos:"
git -C "$UPSTREAM" status --short
