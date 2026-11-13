#!/usr/bin/env bash
# Test fuer deploy/warteliste-bestaetigung.sh mit gefaelschtem curl und docker.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/warteliste-bestaetigung.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

SCHLUESSEL="$(printf 'ab%.0s' $(seq 32))"          # 64 Hex-Zeichen
TOKEN="$(printf 'c3%.0s' $(seq 32))"
API="sb_publishable_0123456789abcdefghij"
LEER='{"rows": [], "count": 0, "generated_at": "2026-11-13T18:00:00+00:00"}'
EINER="{\"rows\": [{\"email\": \"a@example.org\", \"token\": \"$TOKEN\"}], \"count\": 1, \"generated_at\": \"2026-11-13T18:00:00+00:00\"}"

# Falsches curl: protokolliert die Argumente (eines je Zeile) und je Funktion
# den Rumpf von der Standardeingabe; liefert das Dokument aus $T/dokument.
cat > "$T/curl" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/curl.log"
funktion=""; for a in "$@"; do case "$a" in */rest/v1/rpc/*) funktion="${a##*/}" ;; esac; done
cat > "$T/curl.rumpf.$funktion"
[ -f "$T/abholen_scheitert" ] && exit 22
case "$funktion" in
  waitlist_mail_queue) cat "$T/dokument" ;;
  waitlist_mail_requeue) printf '1' ;;
esac
EOF
# Falsches docker: `inspect` meldet, ob der Container laeuft; `exec` protokolliert
# Argumente und Standardeingabe und antwortet wie warteliste_bestaetigung.py.
cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
if [ "$1" = inspect ]; then
  [ -f "$T/container_aus" ] && { echo false; exit 0; }
  echo true; exit 0
fi
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/docker.log"
cat > "$T/docker.eingabe"
if [ -f "$T/versand_antwort" ]; then cat "$T/versand_antwort"; else echo '[]'; fi
[ -f "$T/versand_code" ] && exit "$(cat "$T/versand_code")"
exit 0
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
aufraeumen() { rm -f "$T"/curl.log "$T"/curl.rumpf.* "$T"/docker.log "$T"/docker.eingabe; }

# 1. Ohne Zugang oder mit kaputten Werten: Abbruch, nichts abgeholt
: > "$T/.env"
if lauf >/dev/null 2>&1; then fehler "ohne Zugang haette das Skript abbrechen muessen"; fi
env_schreiben "http://x.example" "$API" "$SCHLUESSEL"
if lauf >/dev/null 2>&1; then fehler "http-Adresse angenommen"; fi
env_schreiben "https://x.example" "$API" "abc"
if lauf >/dev/null 2>&1; then fehler "kurzer Abholschluessel angenommen"; fi
env_schreiben "https://x.example" "$API" "$SCHLUESSEL"
echo "WARTELISTE_BESTAETIGUNG_SEITE=http://x.example/confirm" >> "$T/.env"
if lauf >/dev/null 2>&1; then fehler "http-Bestaetigungsseite angenommen"; fi
if lauf --trocken >/dev/null 2>&1; then fehler "unbekanntes Argument angenommen"; fi
[ ! -f "$T/curl.log" ] || fehler "mit kaputten Werten abgeholt"

# 2. Versender laeuft nicht: nichts abholen (Abholen verbraucht die Token)
env_schreiben "https://x.example" "$API" "$SCHLUESSEL"
printf '%s' "$EINER" > "$T/dokument"
touch "$T/container_aus"
if lauf >/dev/null 2>&1; then fehler "ohne laufenden Versender endete das Skript mit 0"; fi
[ ! -f "$T/curl.log" ] || fehler "ohne laufenden Versender abgeholt"
rm "$T/container_aus"

# 3. Niemand wartet: ein Abruf, Schluessel NUR im Rumpf, Container nicht angefasst
printf '%s' "$LEER" > "$T/dokument"
aus="$(lauf 2>&1)"
[ -z "$aus" ] || fehler "leerer Lauf gibt etwas aus: $aus"
grep -q '^<https://x.example/rest/v1/rpc/waitlist_mail_queue>$' "$T/curl.log" || fehler "falsche Adresse"
grep -q '^<POST>$' "$T/curl.log" || fehler "kein POST"
grep -q '^<--fail>$' "$T/curl.log" || fehler "curl ohne --fail"
! grep -q "$SCHLUESSEL" "$T/curl.log" || fehler "Abholschluessel steht in den curl-Argumenten"
[ "$(cat "$T/curl.rumpf.waitlist_mail_queue")" = "{\"p_key\":\"$SCHLUESSEL\"}" ] || fehler "Rumpf der Anfrage falsch"
[ ! -f "$T/docker.log" ] || fehler "bei leerer Warteschlange den Container gestartet"
aufraeumen

# 4. Eine Adresse wartet: Dokument ueber die Standardeingabe an sales-mail,
#    Token in keinem Argument, keine Rueckmeldung noetig
printf '%s' "$EINER" > "$T/dokument"
aus="$(lauf 2>&1)"
[ -z "$aus" ] || fehler "Lauf ohne Fehler gibt etwas aus: $aus"
[ "$(cat "$T/docker.eingabe")" = "$EINER" ] || fehler "Dokument kam nicht bei sales-mail an"
grep -q '^<exec>$' "$T/docker.log" && grep -q '^<-i>$' "$T/docker.log" \
  && grep -q '^<sales-mail>$' "$T/docker.log" && grep -q '^<warteliste_bestaetigung.py>$' "$T/docker.log" \
  && grep -q '^<senden>$' "$T/docker.log" || fehler "docker-Aufruf falsch"
! grep -q "$TOKEN" "$T/docker.log" "$T/curl.log" || fehler "Token steht in einem Argument"
! grep -q "$SCHLUESSEL" "$T/docker.log" || fehler "Abholschluessel steht in den docker-Argumenten"
! grep -q '^<--seite>$' "$T/docker.log" || fehler "--seite ohne Auftrag"
[ ! -f "$T/curl.rumpf.waitlist_mail_requeue" ] || fehler "Rueckmeldung ohne Anlass"
aufraeumen

# 5. Eigene Bestaetigungsseite wird als Argument durchgereicht
echo "WARTELISTE_BESTAETIGUNG_SEITE=https://staging.example/waitlist/confirm" >> "$T/.env"
lauf >/dev/null 2>&1
grep -q '^<--seite>$' "$T/docker.log" && grep -q '^<https://staging.example/waitlist/confirm>$' "$T/docker.log" \
  || fehler "--seite nicht durchgereicht"
env_schreiben "https://x.example" "$API" "$SCHLUESSEL"
aufraeumen

# 6. Versand gescheitert (Exit 3): Adressen zurueckmelden, Skript endet mit 3
echo '["a@example.org"]' > "$T/versand_antwort"; echo 3 > "$T/versand_code"
code=0; err="$(lauf 2>&1 >/dev/null)" || code=$?
[ "$code" = 3 ] || fehler "gescheiterter Versand endete mit $code statt 3"
[ "$(cat "$T/curl.rumpf.waitlist_mail_requeue")" = "{\"p_key\":\"$SCHLUESSEL\",\"p_emails\":[\"a@example.org\"]}" ] \
  || fehler "Rumpf der Rueckmeldung falsch"
grep -q '^<https://x.example/rest/v1/rpc/waitlist_mail_requeue>$' "$T/curl.log" || fehler "Rueckmeldung an falsche Adresse"
case "$err" in *"zurueck in die Warteschlange: 1"*) ;; *) fehler "Zahl der Rueckmeldung fehlt: $err" ;; esac
case "$err" in *"a@example.org"*) fehler "Adresse auf stderr" ;; esac
aufraeumen

# 7. Rueckmeldung in falscher Form: nichts an die Website, Skript endet ungleich 0
echo '["a@example.org"], "p_key": "x"' > "$T/versand_antwort"
if lauf >/dev/null 2>&1; then fehler "kaputte Rueckmeldung endete mit 0"; fi
[ ! -f "$T/curl.rumpf.waitlist_mail_requeue" ] || fehler "kaputte Rueckmeldung an die Website geschickt"
rm "$T/versand_antwort" "$T/versand_code"
aufraeumen

# 8. Abholen scheitert: Container nicht angefasst, Skript endet ungleich 0
touch "$T/abholen_scheitert"
if lauf >/dev/null 2>&1; then fehler "gescheitertes Abholen endete mit 0"; fi
[ ! -f "$T/docker.log" ] || fehler "trotz gescheitertem Abholen den Container gestartet"
rm "$T/abholen_scheitert"
aufraeumen

# 9. Das Zeitlimit steht vor curl UND docker exec
cat > "$T/zl" <<'EOF'
#!/usr/bin/env bash
echo "$1" >> "$(dirname "$0")/zl.log"; shift; exec "$@"
EOF
chmod +x "$T/zl"
CURL="$T/curl" DOCKER="$T/docker" ZEITLIMIT="$T/zl marke" WURZEL_ENV="$T/.env" bash "$SKRIPT" >/dev/null 2>&1
[ "$(wc -l < "$T/zl.log")" = 2 ] || fehler "Zeitlimit nicht vor beiden Aufrufen"

# 10. Kein set -x: weder Schluessel noch Token auf stdout oder stderr
alles="$(lauf 2>&1 || true)"
case "$alles" in *"$SCHLUESSEL"*|*"$TOKEN"*) fehler "Schluessel oder Token in der Ausgabe" ;; esac

echo "OK: warteliste-bestaetigung.sh"
