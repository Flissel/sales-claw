#!/usr/bin/env bash
# deploy/marketing-aktualisieren.sh — zieht den schlanken vibemind-os-
# Checkout der Marketing-Seite nach und startet marketing-api neu, wenn sich
# unter spaces/marketing etwas geaendert hat (Spec 2026-09-25-marketing-
# schalter-design.md §3.1). Aufgerufen am Ende von update.sh, NICHT fatal
# fuer den Sales-Laden: ein Fehler hier rollt Sales nie zurueck.
#
# Neustart-Entscheid gegen eine Standdatei (.git/marketing-api-gestartet) mit
# dem Commit, der zuletzt ERFOLGREICH neu gestartet wurde — nicht gegen den
# Stand vor dem Vorspulen. Scheitert ein Neustart, bleibt die Datei alt, und
# der naechste Lauf holt den Neustart nach, auch ohne neue Commits.
set -euo pipefail
export LC_ALL=C
MARKETING_OS="${MARKETING_OS:-$HOME/marketing-os}"
SYSTEMCTL="${SYSTEMCTL:-sudo -n systemctl}"
GESUNDHEIT="${GESUNDHEIT:-curl -fsS --max-time 5 http://127.0.0.1:5510/api/health}"
GESUNDHEIT_PAUSE="${GESUNDHEIT_PAUSE:-2}"

if [ ! -d "$MARKETING_OS/.git" ]; then
  echo "Marketing-Seite: nicht eingerichtet ($MARKETING_OS fehlt) - uebersprungen."
  exit 0
fi
cd "$MARKETING_OS"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ABBRUCH Marketing-Seite: lokale Aenderungen in $MARKETING_OS." >&2
  exit 1
fi
STAND=".git/marketing-api-gestartet"
ALT="$(git rev-parse HEAD)"
# Ohne Standdatei gilt der Stand vor dem Vorspulen als der laufende.
[ -s "$STAND" ] || echo "$ALT" > "$STAND"
BASIS="$(cat "$STAND")"
git fetch origin master --quiet
git merge --ff-only --quiet origin/master
NEU="$(git rev-parse HEAD)"
if [ "$BASIS" = "$NEU" ]; then
  echo "Marketing-Seite: aktuell ($NEU)."
  exit 0
fi

# Ohne Pipe: `git diff | grep -q` bricht unter pipefail bei grossem Diff mit
# SIGPIPE ab und liess den Neustart still aus. 0 = unveraendert, 1 = geaendert,
# alles andere (z. B. unbekannte BASIS) = sicherheitshalber neu starten.
rc=0
git diff --quiet "$BASIS" "$NEU" -- spaces/__init__.py spaces/marketing || rc=$?
if [ "$rc" -eq 0 ]; then
  echo "$NEU" > "$STAND"
  echo "Marketing-Seite: $BASIS -> $NEU, nichts Relevantes geaendert."
  exit 0
fi

gesund() {
  local i
  for i in 1 2 3 4 5; do
    if $GESUNDHEIT >/dev/null 2>&1; then return 0; fi
    [ "$i" -lt 5 ] && sleep "$GESUNDHEIT_PAUSE"
  done
  return 1
}

if ! $SYSTEMCTL restart marketing-api; then
  echo "HINWEIS Marketing-Seite: Neustart von marketing-api gescheitert ($BASIS -> $NEU); naechster Lauf versucht es erneut." >&2
  exit 1
fi
if ! $SYSTEMCTL is-active --quiet marketing-api; then
  echo "HINWEIS Marketing-Seite: marketing-api nach Neustart nicht aktiv ($NEU); naechster Lauf versucht es erneut." >&2
  exit 1
fi
if ! gesund; then
  echo "HINWEIS Marketing-Seite: marketing-api antwortet nicht auf die Gesundheitsprobe ($NEU); naechster Lauf versucht es erneut." >&2
  exit 1
fi
echo "$NEU" > "$STAND"
echo "Marketing-Seite: $BASIS -> $NEU, neu gestartet."
