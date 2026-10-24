#!/usr/bin/env bash
# Test: deploy/smoke.sh behandelt einen nie angelegten sales-kanaele als
# Hinweis, einen angelegten aber nicht laufenden als ROT. Gefaelschtes
# docker/curl im PATH; nur die Zeile "container sales-kanaele" zaehlt.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fehler() { echo "FEHLER: $*"; exit 1; }
cat > "$T/docker" <<'EOF2'
#!/usr/bin/env bash
if [ "${1:-}" = inspect ]; then
  for a in "$@"; do last="$a"; done
  if [ "$last" = sales-kanaele ]; then
    [ -n "${KANAELE:-}" ] || { echo; exit 1; }  # wie das echte docker: leere Zeile + rc=1
    echo "$KANAELE"; exit 0
  fi
  echo running; exit 0
fi
exit 1
EOF2
printf '#!/usr/bin/env bash\necho 000\nexit 7\n' > "$T/curl"
chmod +x "$T/docker" "$T/curl"
lauf() { PATH="$T:$PATH" KANAELE="$1" bash "$WURZEL/deploy/smoke.sh" --nur-basis 2>&1 || true; }

a="$(lauf "")"
echo "$a" | grep -q 'container sales-kanaele *HINWEIS: .*docker compose up -d --no-deps sales-kanaele' || fehler "nie angelegt: kein Hinweis"
echo "$a" | grep -q 'container sales-kanaele *ROT' && fehler "nie angelegt darf nicht ROT sein"
b="$(lauf exited)"
echo "$b" | grep -q 'container sales-kanaele *ROT: exited' || fehler "exited muss ROT sein"
c="$(lauf running)"
echo "$c" | grep -q 'container sales-kanaele *ok' || fehler "running muss ok sein"
# Ein anderer fehlender Container bleibt ROT.
echo "OK"
