#!/usr/bin/env bash
# Baut das Patch-Abbild sales-vexa-lite:v0.12.28-pause1 (Dockerfile.pause) und
# prueft es IN einem Wegwerf-Container des neuen Abbilds (--network none):
#   1. Jede Patch-Datei liegt byteweise gleich an ALLEN Zielorten im Abbild
#      (Laufzeit und Test-Baum, sha256), das Bot-dist/ ist genau der tsc-Bau
#      der gepatchten Quellen, und Meeting-API und Gateway importieren mit der
#      supervisord-Umgebung die gepatchten Module.
#   2. Bot:         npm test, tsc --noEmit, check:isolation
#   3. Meeting-API: pytest (ohne Postgres: die PG-Tests werden uebersprungen)
#   4. Gateway:     pytest
# Letzte Zeile "ABBILD OK" nur, wenn alles gruen ist; sonst Exit != 0.
# Der Wegwerf-Container wird in jedem Fall entfernt (trap). Laufende Container
# (vexa-lite usw.) werden nicht angefasst; es wird nichts gestartet ausser dem
# Pruef-Container und nichts aufgeraeumt ausser ihm.
#
# Aufruf (auf dem Docker-Host, aus einem Checkout - NICHT aus dem Prod-Checkout
# bauen, solange Task 9 nicht freigegeben ist):
#   bash deploy/vexa/vexa-pause-bauen.sh
set -euo pipefail

TAG="sales-vexa-lite:v0.12.28-pause1"
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$HIER/patch"
DOCKERFILE="$HIER/Dockerfile.pause"
PRUEF="vexa-pause-bau-$$"
# Untergrenzen (Stand v0.12.28 + pause1): weniger heisst, Tests wurden nicht
# gefunden oder nicht ausgefuehrt. Erwartet sind genau diese Zahlen.
MIN_BOT_OK=759          # ✅-Zeilen: 758 aus npm test + 1 check:isolation, 0 ❌
MIN_MA_PASSED=1458      # Meeting-API ohne PG: 1458 passed, 5 skipped
MIN_GW_PASSED=386       # Gateway: 386 passed, 1 xfailed

fehler() { echo "FEHLER: $*" >&2; exit 1; }

for befehl in docker sha256sum timeout find sort; do
  command -v "$befehl" >/dev/null 2>&1 || fehler "$befehl fehlt"
done
[ -f "$DOCKERFILE" ] || fehler "Dockerfile.pause fehlt"
[ -d "$PATCH" ] || fehler "patch/ fehlt"

LOGS="$(mktemp -d)"
aufraeumen() {
  docker rm -f "$PRUEF" >/dev/null 2>&1 || true
  rm -rf "$LOGS"
}
trap aufraeumen EXIT

# ── Patch-Dateien: Zeilenenden und Zielorte ──────────────────────────────────
# Zielorte einer Patch-Datei (relativ zu patch/) im Abbild. Muss zu den COPY-
# Zeilen in Dockerfile.pause passen; eine unbekannte Datei bricht ab.
ziele() {
  case "$1" in
    bot/*)
      echo "/app/core/meetings/services/bot/${1#bot/}" ;;
    meeting-api/src/*)
      echo "/app/meeting-api/src/${1#meeting-api/src/}"
      echo "/app/core/meetings/services/meeting-api/src/${1#meeting-api/src/}" ;;
    meeting-api/tests/*)
      echo "/app/core/meetings/services/meeting-api/tests/${1#meeting-api/tests/}" ;;
    gateway/src/gateway/app.py)
      echo "/app/gateway/src/gateway/app.py"
      echo "/app/core/gateway/services/gateway/src/gateway/app.py" ;;
    gateway/core/meetings/routes.v1.json)
      echo "/app/gateway/core/meetings/routes.v1.json"
      echo "/app/core/meetings/routes.v1.json" ;;
    gateway/tests/*)
      echo "/app/core/gateway/services/gateway/tests/${1#gateway/tests/}" ;;
    *) return 1 ;;
  esac
}

SUMMEN="$LOGS/summen.txt"
n_dateien=0
while IFS= read -r -d '' datei; do
  rel="${datei#./}"
  if grep -q $'\r' "$PATCH/$rel"; then fehler "CRLF in patch/$rel (Repo-Checkout mit autocrlf?)"; fi
  zielorte="$(ziele "$rel")" || fehler "patch/$rel hat keinen Zielort (ziele() und Dockerfile.pause ergaenzen)"
  summe="$(cd "$PATCH" && sha256sum "$rel" | cut -d' ' -f1)"
  while IFS= read -r ziel; do
    printf '%s  %s\n' "$summe" "$ziel" >> "$SUMMEN"
  done <<< "$zielorte"
  n_dateien=$((n_dateien + 1))
done < <(cd "$PATCH" && find . -type f ! -name .dockerignore ! -name '*.pyc' ! -path '*/__pycache__/*' ! -path '*/node_modules/*' -print0 | sort -z)
[ "$n_dateien" -gt 0 ] || fehler "keine Patch-Dateien gefunden"
if grep -q $'\r' "$DOCKERFILE"; then fehler "CRLF in Dockerfile.pause"; fi
echo "== $n_dateien Patch-Dateien, $(wc -l < "$SUMMEN") Zielorte"

# ── Bauen ───────────────────────────────────────────────────────────────────
# Kontext ist patch/ (nicht deploy/vexa: dort liegt die .env mit Geheimnissen).
echo "== baue $TAG"
timeout 1800 docker build -f "$DOCKERFILE" -t "$TAG" "$PATCH"
ID="$(docker image inspect "$TAG" --format '{{.Id}}')"
echo "== Abbild $TAG = $ID"

# ── Wegwerf-Container aus dem NEUEN Abbild ──────────────────────────────────
timeout 120 docker run -d --name "$PRUEF" --network none --entrypoint sleep "$TAG" infinity >/dev/null
[ "$(docker inspect "$PRUEF" --format '{{.Image}}')" = "$ID" ] || fehler "Pruef-Container laeuft nicht auf $ID"

# Fuehrt ein sh-Skript (stdin) im Pruef-Container aus; innen und aussen begrenzt.
im_container() {  # <Sekunden>
  local s="$1"
  timeout "$((s + 30))" docker exec -i "$PRUEF" timeout "$s" sh -s
}

echo "== 1. Patch-Dateien im Abbild (sha256, Laufzeit + Test-Baum)"
im_container 120 < <(printf 'sha256sum -c --quiet - <<"SUMMEN"\n'; cat "$SUMMEN"; printf 'SUMMEN\n') \
  || fehler "Abbild weicht von deploy/vexa/patch ab (siehe oben)"
echo "   $(wc -l < "$SUMMEN") Zielorte gleich dem Repo"

echo "== 1b. Bot-dist/ = tsc-Bau der gepatchten Quellen; Laufzeit-Importe"
im_container 600 <<'PRUEFUNG' || fehler "Laufzeit-Pruefung fehlgeschlagen"
set -e
cd /app/core/meetings/services/bot
rm -rf /tmp/dist-pruef
npx tsc -p . --outDir /tmp/dist-pruef
# .map traegt den Ausgabepfad, browser-utils.global.js baut esbuild (nicht tsc).
diff -r -x '*.map' -x browser-utils.global.js /tmp/dist-pruef dist
grep -q 'pauseGate' dist/index.js
cmp /app/browser-utils.global.js dist/browser-utils.global.js
grep -q 'exec node dist/index.js' /usr/local/bin/vexa-bot-launch
echo "   bot: dist/ entspricht src/ (Starter: node dist/index.js)"
cd /app/meeting-api
PYTHONPATH=/app/meeting-api/src /opt/venvs/meeting/bin/python -c '
import meeting_api, meeting_api.app, meeting_api.lifecycle.pause_router as p
assert p.__file__ == "/app/meeting-api/src/meeting_api/lifecycle/pause_router.py", p.__file__
assert hasattr(p, "build_pause_router")
print("   meeting-api (Laufzeit):", p.__file__)
'
cd /app/gateway
PYTHONPATH=/app/gateway/src /opt/venvs/gateway/bin/python -c '
import gateway.app as a
assert a.__file__ == "/app/gateway/src/gateway/app.py", a.__file__
for r in ("pause", "resume"):
    k = ("POST", "/bots/{platform}/{native_meeting_id}/" + r)
    assert a.ROUTE_SCOPES.get(k) == frozenset({"bot"}), (k, a.ROUTE_SCOPES.get(k))
print("   gateway (Laufzeit):", a.__file__, "Routen mit Scope:", len(a.ROUTE_SCOPES))
'
PRUEFUNG

echo "== 2. Bot-Tests (npm test, tsc --noEmit, check:isolation)"
BOT_LOG="$LOGS/bot.log"
set +e
im_container 1200 > "$BOT_LOG" 2>&1 <<'TEST'
cd /app/core/meetings/services/bot || exit 1
npm test || exit 11
npx tsc --noEmit -p . || exit 12
npm run check:isolation || exit 13
TEST
rc=$?
set -e
tail -n 6 "$BOT_LOG"
bot_ok="$(grep -c '✅' "$BOT_LOG" || true)"
bot_fail="$(grep -c '❌' "$BOT_LOG" || true)"
echo "   bot: ✅ $bot_ok, ❌ $bot_fail, Exit $rc"
[ "$rc" -eq 0 ] || fehler "Bot-Tests rot (Exit $rc)"
[ "$bot_fail" -eq 0 ] || fehler "Bot-Tests: $bot_fail ❌"
[ "$bot_ok" -ge "$MIN_BOT_OK" ] || fehler "Bot-Tests: nur $bot_ok ✅ (erwartet >= $MIN_BOT_OK)"

# pytest-Zusammenfassung pruefen: Exit 0, kein failed/error, genug passed.
pytest_pruefen() {  # <Name> <Log> <rc> <min passed>
  local name="$1" log="$2" rc="$3" min="$4" zeile passed
  zeile="$(grep -E '[0-9]+ (passed|failed)' "$log" | tail -n 1)"
  echo "   $name: $zeile (Exit $rc)"
  [ "$rc" -eq 0 ] || fehler "$name rot (Exit $rc)"
  if echo "$zeile" | grep -qE '[0-9]+ (failed|errors?)'; then fehler "$name: $zeile"; fi
  passed="$(echo "$zeile" | grep -oE '[0-9]+ passed' | cut -d' ' -f1)"
  [ "${passed:-0}" -ge "$min" ] || fehler "$name: nur ${passed:-0} passed (erwartet >= $min)"
}

echo "== 3. Meeting-API-Tests (ohne Postgres)"
MA_LOG="$LOGS/ma.log"
set +e
im_container 900 > "$MA_LOG" 2>&1 <<'TEST'
cd /app/core/meetings/services/meeting-api || exit 1
/opt/venvs/meeting/bin/python -m pytest -q -p no:cacheprovider
TEST
rc=$?
set -e
tail -n 3 "$MA_LOG"
pytest_pruefen meeting-api "$MA_LOG" "$rc" "$MIN_MA_PASSED"

echo "== 4. Gateway-Tests"
GW_LOG="$LOGS/gw.log"
set +e
im_container 600 > "$GW_LOG" 2>&1 <<'TEST'
cd /app/core/gateway/services/gateway || exit 1
/opt/venvs/gateway/bin/python -m pytest -q -p no:cacheprovider
TEST
rc=$?
set -e
tail -n 3 "$GW_LOG"
pytest_pruefen gateway "$GW_LOG" "$rc" "$MIN_GW_PASSED"

echo "== $TAG = $ID"
echo "ABBILD OK"
