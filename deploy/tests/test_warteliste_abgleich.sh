#!/usr/bin/env bash
# Test fuer deploy/warteliste-abgleich.sh mit gefaelschtem curl und docker.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/warteliste-abgleich.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

SCHLUESSEL="$(printf 'ab%.0s' $(seq 32))"          # 64 Hex-Zeichen
API="sb_publishable_0123456789abcdefghij"

# Falsches curl: protokolliert die Argumente (eines je Zeile) und den Rumpf
# von der Standardeingabe getrennt; liefert das Dokument oder scheitert.
cat > "$T/curl" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/curl.log"
cat > "$T/curl.rumpf"
[ -f "$T/abholen_scheitert" ] && exit 22
printf '{"count":0,"rows":[]}'
EOF
# Falsches docker: protokolliert die Argumente und was auf der Standardeingabe ankam.
cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/docker.log"
cat > "$T/docker.eingabe"
[ -s "$T/docker.eingabe" ] || exit 2
echo '{"angelegt": 0}'
EOF
chmod +x "$T/curl" "$T/docker"

fehler() { echo "FEHLER: $*"; exit 1; }
lauf() {
  CURL="$T/curl" DOCKER="$T/docker" ZEITLIMIT="" WURZEL_ENV="$T/.env" bash "$SKRIPT" "$@"
}
env_schreiben() {
  printf 'WARTELISTE_URL=%s\nWARTELISTE_API_SCHLUESSEL=%s\nWARTELISTE_ABHOL_SCHLUESSEL=%s\n' \
    "$1" "$2" "$3" > "$T/.env"
}

# 1. Ohne Zugang: Abbruch, nichts abgeholt
: > "$T/.env"
if lauf >/dev/null 2>&1; then fehler "ohne Zugang haette das Skript abbrechen muessen"; fi
[ ! -f "$T/curl.log" ] || fehler "ohne Zugang abgeholt"

# 2. Kaputte Werte: http statt https, Adresse mit Pfad, Schluessel zu kurz
env_schreiben "http://x.example" "$API" "$SCHLUESSEL"
if lauf >/dev/null 2>&1; then fehler "http-Adresse angenommen"; fi
env_schreiben "https://x.example/rest" "$API" "$SCHLUESSEL"
if lauf >/dev/null 2>&1; then fehler "Adresse mit Pfad angenommen"; fi
env_schreiben "https://x.example" "$API" "abc"
if lauf >/dev/null 2>&1; then fehler "kurzer Abholschluessel angenommen"; fi
[ ! -f "$T/curl.log" ] || fehler "mit kaputten Werten abgeholt"

# 3. Erfolg: POST an die eine Funktion, Schluessel NUR im Rumpf, Dokument an sales-mcp
env_schreiben "https://x.example" "$API" "$SCHLUESSEL"
aus="$(lauf)"
[ "$aus" = '{"angelegt": 0}' ] || fehler "Ausgabe von sales-mcp nicht durchgereicht: $aus"
grep -q '^<https://x.example/rest/v1/rpc/waitlist_export>$' "$T/curl.log" || fehler "falsche Adresse"
grep -q '^<POST>$' "$T/curl.log" || fehler "kein POST"
grep -q '^<--fail>$' "$T/curl.log" || fehler "curl ohne --fail"
! grep -q "$SCHLUESSEL" "$T/curl.log" || fehler "Abholschluessel steht in den curl-Argumenten"
! grep -q "$SCHLUESSEL" "$T/docker.log" || fehler "Abholschluessel steht in den docker-Argumenten"
[ "$(cat "$T/curl.rumpf")" = "{\"p_key\":\"$SCHLUESSEL\"}" ] || fehler "Rumpf der Anfrage falsch"
[ "$(cat "$T/docker.eingabe")" = '{"count":0,"rows":[]}' ] || fehler "Dokument kam nicht bei sales-mcp an"
grep -q '^<exec>$' "$T/docker.log" && grep -q '^<-i>$' "$T/docker.log" \
  && grep -q '^<sales-mcp>$' "$T/docker.log" && grep -q '^<warteliste_abgleich.py>$' "$T/docker.log" \
  && grep -q '^<abgleichen>$' "$T/docker.log" || fehler "docker-Aufruf falsch"
! grep -q '^<--trocken>$' "$T/docker.log" || fehler "--trocken ohne Auftrag"

# 4. --trocken und --hoechstens werden als eigene Argumente durchgereicht
: > "$T/docker.log"
lauf --trocken --hoechstens 20 >/dev/null
grep -q '^<--trocken>$' "$T/docker.log" || fehler "--trocken nicht durchgereicht"
grep -q '^<--hoechstens>$' "$T/docker.log" && grep -q '^<20>$' "$T/docker.log" \
  || fehler "--hoechstens nicht durchgereicht"
if lauf --hoechstens viele >/dev/null 2>&1; then fehler "--hoechstens ohne Zahl angenommen"; fi
if lauf --loeschen >/dev/null 2>&1; then fehler "unbekanntes Argument angenommen"; fi

# 5. Abholen scheitert: bei sales-mcp kommt nichts an, das Skript endet ungleich 0
touch "$T/abholen_scheitert"; rm -f "$T/docker.eingabe"
if lauf >/dev/null 2>&1; then fehler "gescheitertes Abholen endete mit 0"; fi
[ ! -s "$T/docker.eingabe" ] || fehler "trotz gescheitertem Abholen kam ein Dokument an"
rm "$T/abholen_scheitert"

# 6. Das Zeitlimit steht vor curl UND docker
cat > "$T/zl" <<'EOF'
#!/usr/bin/env bash
echo "$1" >> "$(dirname "$0")/zl.log"; shift; exec "$@"
EOF
chmod +x "$T/zl"
CURL="$T/curl" DOCKER="$T/docker" ZEITLIMIT="$T/zl marke" WURZEL_ENV="$T/.env" bash "$SKRIPT" >/dev/null
[ "$(wc -l < "$T/zl.log")" = 2 ] || fehler "Zeitlimit nicht vor beiden Aufrufen"

# 7. Kein set -x: der Schluessel erscheint auch auf stderr nicht
err="$(lauf 2>&1 >/dev/null || true)"
case "$err" in *"$SCHLUESSEL"*) fehler "Abholschluessel auf stderr" ;; esac

echo "OK: warteliste-abgleich.sh"
