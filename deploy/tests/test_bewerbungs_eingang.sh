#!/usr/bin/env bash
# Test fuer deploy/bewerbungs-eingang.sh mit gefaelschtem docker.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/bewerbungs-eingang.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# Falsches docker: protokolliert jeden Aufruf (ein Argument je Zeile),
# meldet den Container als laufend (ausser $T/gestoppt) und endet mit dem
# Code aus $T/code (Vorgabe 0).
cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/log"
if [ "$1" = "inspect" ]; then
  [ -f "$T/gestoppt" ] && { echo exited; exit 0; }
  echo running; exit 0
fi
exit "$(cat "$T/code" 2>/dev/null || echo 0)"
EOF
chmod +x "$T/docker"
cat > "$T/zeitlimit" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
echo "ZEITLIMIT $1" >> "$T/log"; shift; exec "$@"
EOF
chmod +x "$T/zeitlimit"

fehler() { echo "FEHLER: $*"; exit 1; }
lauf() { DOCKER="$T/docker" ZEITLIMIT="$T/zeitlimit 900" bash "$SKRIPT" "$@"; }

# 1. Normaler Lauf: exec in sales-mcp, unter dem Zeitlimit, ohne -i/-t
lauf >/dev/null
grep -q '^ZEITLIMIT 900$' "$T/log" || fehler "kein Zeitlimit"
tr '\n' ' ' < "$T/log" | grep -q 'AUFRUF <exec> <sales-mcp> <python> <bewerbungs_eingang.py> <lauf> *$' \
  || fehler "falscher Aufruf: $(cat "$T/log")"
! grep -qE '^<-(i|t|it)>$' "$T/log" || fehler "interaktives exec in einer Unit"

# 2. --trocken wird durchgereicht
: > "$T/log"; lauf --trocken >/dev/null
grep -q '^<--trocken>$' "$T/log" || fehler "--trocken nicht durchgereicht"

# 3. Unbekanntes Argument: Exit 2, kein exec
: > "$T/log"; rc=0; lauf --wirklich >/dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] || fehler "unbekanntes Argument gab $rc statt 2"
! grep -q '^<exec>$' "$T/log" || fehler "trotz falschem Aufruf gestartet"

# 4. Exit-Code des Moduls kommt durch (1 = unvollstaendig)
echo 1 > "$T/code"; rc=0; lauf >/dev/null 2>&1 || rc=$?
[ "$rc" = 1 ] || fehler "Exit-Code nicht durchgereicht ($rc)"
rm "$T/code"

# 5. Container gestoppt: Exit 1, kein exec
touch "$T/gestoppt"; : > "$T/log"; rc=0; lauf >/dev/null 2>&1 || rc=$?
[ "$rc" = 1 ] || fehler "gestoppter Container gab $rc statt 1"
! grep -q '^<exec>$' "$T/log" || fehler "exec in gestopptem Container"

echo "OK test_bewerbungs_eingang.sh"
