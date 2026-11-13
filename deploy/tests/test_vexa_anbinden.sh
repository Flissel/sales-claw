#!/usr/bin/env bash
# Verhaltenstest fuer deploy/vexa-anbinden.sh mit gefaelschtem docker und
# gefaelschtem curl (Admin-API von Vexa als Attrappe, Zustand in Dateien).
# Fasst nie echtes Docker, nie Vexa und nie eine echte .env an.
#
#   bash deploy/tests/test_vexa_anbinden.sh
#
# Das Container-Skript aus vexa-anbinden.sh laeuft dabei lokal in `sh -c`, mit
# der Attrappe als curl im PATH — so wird auch seine Logik geprueft.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/vexa-anbinden.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

fehler() { echo "FEHLER: $*"; exit 1; }
[ -f "$SKRIPT" ] || fehler "deploy/vexa-anbinden.sh fehlt"

# --- Attrappen (gemeinsam fuer alle Faelle) -------------------------------
mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
# Attrappe: inspect/volume/exec. Zustand in $STATE (Dateien up, volume).
echo "docker $*" >> "$STATE/docker-argv.log"
case "$1" in
  volume) [ "$2" = inspect ] && [ -e "$STATE/volume" ] && exit 0; exit 1 ;;
  inspect) if [ -e "$STATE/up" ]; then echo true; else echo false; fi; exit 0 ;;
  exec)
    shift
    while [ "$1" = "-e" ]; do shift 2; done   # Umgebungsnamen ohne Wert, die Werte sind schon exportiert
    shift                                      # Containername
    [ "$1" = sh ] && [ "$2" = -c ] || { echo "unerwartet: $*" >&2; exit 2; }
    ADMIN_API_TOKEN="$(sed -n 's/^ADMIN_TOKEN=//p' "$VEXA_ENV_DATEI")"
    export ADMIN_API_TOKEN
    # Umgebung des admin-api-Prozesses (NUL-getrennt wie /proc/<pid>/environ)
    printf 'PATH=/x\0INTERNAL_API_SECRET=%s\0' "$INTERN_GEHEIM" > "$STATE/environ"
    ADMIN_ENVIRON_DATEI="$STATE/environ"; export ADMIN_ENVIRON_DATEI
    PATH="$BIN:$PATH" exec sh -c "$3"
    ;;
  *) echo "unerwartet: $*" >&2; exit 2 ;;
esac
EOF
cat > "$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
# Attrappe fuer Vexas Admin-API: -K - (Kopfzeilen von stdin), -o, -w, -X, -d, -H, URL.
echo "curl $*" >> "$STATE/curl-argv.log"
konf=0; ausgabe=""; fmt=""; methode=GET; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -K) konf=1; shift 2 ;;
    -o) ausgabe="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -X) methode="$2"; shift 2 ;;
    -d|-H|-m) shift 2 ;;
    -s) shift ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
adm=""; usr=""; intern=""
if [ "$konf" = 1 ]; then
  while IFS= read -r z; do
    z="${z#header = \"}"; z="${z%\"}"
    case "$z" in
      X-Admin-API-Key:*) adm="${z#X-Admin-API-Key: }" ;;
      X-API-Key:*) usr="${z#X-API-Key: }" ;;
      X-Internal-Secret:*) intern="${z#X-Internal-Secret: }" ;;
    esac
  done
fi
pfad="${url#http://localhost:}"; pfad="${pfad#*/}"; pfad="/${pfad%%\?*}"
code=404; body='{"detail":"Not Found"}'
admin_ok=0; [ -n "$adm" ] && [ "$adm" = "$ADMIN_API_TOKEN" ] && admin_ok=1
benutzer='{"id":7,"email":"sales@vexa.lokal","name":"sales","max_concurrent_bots":3,"data":{"id":99}}'
case "$methode $pfad" in
  "GET /admin/users/email/"*)
    if [ "$admin_ok" != 1 ]; then code=403; body='{"detail":"Invalid or missing admin token."}'
    elif [ -e "$STATE/user" ]; then code=200; body="$benutzer"
    else code=404; body='{"detail":"User not found"}'; fi ;;
  "POST /admin/users")
    if [ "$admin_ok" != 1 ]; then code=403; body='{}'
    else : > "$STATE/user"; code=201; body="$benutzer"; fi ;;
  "POST /admin/users/7/tokens")
    if [ "$admin_ok" != 1 ]; then code=403; body='{}'
    else
      tok="vxa_bot_$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 32)"
      echo "$tok" >> "$STATE/tokens"; echo x >> "$STATE/mint-count"
      code=201; body="{\"id\":1,\"token\":\"$tok\",\"user_id\":7,\"scopes\":[\"bot\",\"tx\"]}"
    fi ;;
  "PUT /internal/settings/diagnostics")
    if [ -n "$intern" ] && [ "$intern" = "$INTERN_GEHEIM" ] && [ "${DIAG_KAPUTT:-}" != 1 ]; then
      echo x >> "$STATE/diag-count"; code=200; body='{"key":"diagnostics","value":{"capture_signal":"false"}}'
    else code=403; body='{"detail":"bad internal secret"}'; fi ;;
  "PUT /user/transcription")
    if [ -n "$usr" ] && grep -qxF "$usr" "$STATE/tokens" 2>/dev/null; then
      echo x >> "$STATE/put-count"; code=200; body='{"url":null,"token_set":true,"token":null}'
    else code=403; body='{"detail":"Invalid API Key"}'; fi ;;
esac
if [ -n "$ausgabe" ] && [ "$ausgabe" != /dev/null ]; then printf '%s' "$body" > "$ausgabe"
elif [ -z "$ausgabe" ]; then printf '%s' "$body"; fi
if [ -n "$fmt" ]; then printf '%s' "${fmt//%\{http_code\}/$code}"; fi
exit 0
EOF
chmod +x "$T/bin/docker" "$T/bin/curl"

# Je Fall ein frischer Ordner: sales-.env, Vexa-.env-Pfad, Zustand.
fall() { # name [keine-sales-env]
  F="$T/$1"; mkdir -p "$F/state" "$F/vexa"
  [ "${2:-}" = keine-sales-env ] || printf 'ANDERES=1\n' > "$F/.env"
  : > "$F/state/docker-argv.log"; : > "$F/state/curl-argv.log"
  rm -f "$T/bin/python3"
}
lauf() { # setzt RC
  set +e
  INTERN_GEHEIM="intern-$(printf 'e%.0s' {1..24})" STATE="$F/state" BIN="$T/bin" VEXA_ENV_DATEI="$F/vexa/.env" SALES_ENV_DATEI="$F/.env" \
    DOCKER="$T/bin/docker" bash "$SKRIPT" >"$F/out" 2>"$F/err"
  RC=$?
  set -e
}
sicherungen() { find "$F" -maxdepth 1 -name '.env.vor-vexa-*' | wc -l | tr -d ' '; }
zaehle() { if [ -e "$F/state/$1" ]; then wc -l < "$F/state/$1" | tr -d ' '; else echo 0; fi; }
# Keinerlei Geheimnis (Tokens, Admin-Token, Passwoerter) in Ausgabe oder argv-Protokollen.
ohne_geheimnisse() {
  local geheim=() w
  [ -f "$F/state/tokens" ] && while IFS= read -r w; do geheim+=("$w"); done < "$F/state/tokens"
  if [ -f "$F/vexa/.env" ]; then
    while IFS= read -r w; do w="${w#*=}"; [ -n "$w" ] && geheim+=("$w"); done < "$F/vexa/.env"
  fi
  [ "${#geheim[@]}" -gt 0 ] || return 0
  for w in "${geheim[@]}"; do
    if grep -qF -- "$w" "$F/out" "$F/err" "$F/state/docker-argv.log" "$F/state/curl-argv.log"; then
      fehler "Geheimnis in Ausgabe oder Argumentliste ($1)"
    fi
  done
}

# === 1. Erster Aufruf: legt die Vexa-.env an, Vexa laeuft nicht -> Exit 4 ===
fall a
lauf
[ "$RC" = 4 ] || fehler "1. Aufruf: Exit $RC statt 4 ($(cat "$F/err"))"
[ -f "$F/vexa/.env" ] || fehler "deploy/vexa/.env nicht angelegt"
for n in ADMIN_TOKEN VEXA_DB_PASSWORD VEXA_S3_ACCESS_KEY VEXA_S3_SECRET_KEY; do
  [ "$(grep -c "^$n=.\{16,\}$" "$F/vexa/.env")" = 1 ] || fehler "$n fehlt oder zu kurz in der neuen .env"
done
! grep -q PLATZHALTER "$F/vexa/.env" || fehler "Platzhalter in der neuen .env"
if [ "$(uname -s)" = Linux ]; then
  [ "$(stat -c %a "$F/vexa/.env")" = 600 ] || fehler "vexa/.env nicht 600"
fi
[ "$(cat "$F/.env")" = "ANDERES=1" ] || fehler "sales-.env im 1. Aufruf veraendert"
[ -z "$(find "$F/vexa" -maxdepth 1 -name '.env.neu*')" ] || fehler "Zwischendatei in vexa/ liegen geblieben"
ohne_geheimnisse "1. Aufruf"

# === 2. Nach dem Start: Nutzer, Token, VEXA_API_KEY in die sales-.env ===
: > "$F/state/up"
lauf
[ "$RC" = 0 ] || fehler "2. Aufruf: Exit $RC ($(cat "$F/err"))"
[ "$(grep -c '^VEXA_API_KEY=' "$F/.env")" = 1 ] || fehler "VEXA_API_KEY nicht genau einmal"
grep -qE '^VEXA_API_KEY=vxa_bot_[A-Za-z0-9]{32}$' "$F/.env" || fehler "VEXA_API_KEY hat nicht das Vexa-Format"
grep -qx 'ANDERES=1' "$F/.env" || fehler "fremde Zeile der sales-.env verloren"
[ "$(sicherungen)" = 1 ] || fehler "erwartet genau eine Sicherung, sind $(sicherungen)"
S="$(find "$F" -maxdepth 1 -name '.env.vor-vexa-*')"
[ "$(cat "$S")" = "ANDERES=1" ] || fehler "Sicherung nicht der alte Stand"
if [ "$(uname -s)" = Linux ]; then
  [ "$(stat -c %a "$F/.env")" = 600 ] || fehler "sales-.env nicht 600"
  [ "$(stat -c %a "$S")" = 600 ] || fehler "Sicherung nicht 600"
fi
[ -z "$(find "$F" -maxdepth 1 -name '.env.neu*')" ] || fehler "Zwischendatei liegen geblieben"
[ "$(zaehle mint-count)" = 1 ] || fehler "erwartet 1 Token-Anlage, sind $(zaehle mint-count)"
[ "$(zaehle put-count)" = 1 ] || fehler "erwartet 1 PUT /user/transcription, sind $(zaehle put-count)"
[ -e "$F/state/user" ] || fehler "Nutzer sales nicht angelegt"
ohne_geheimnisse "2. Aufruf"
grep -q 'Vexa angebunden' "$F/out" || fehler "keine Erfolgsmeldung"
[ "$(zaehle diag-count)" = 1 ] || fehler "Mitschnitt-Not-Aus nicht gesetzt (diag-count $(zaehle diag-count))"
! grep -qF "intern-eeee" "$F/out" "$F/err" "$F/state/docker-argv.log" "$F/state/curl-argv.log"   || fehler "internes Geheimnis in Ausgabe oder Argumentliste"

# === 3. Zweiter Lauf mit gueltigem Schluessel: nichts neu, nichts geschrieben ===
cp "$F/.env" "$F/.env.stand"
lauf
[ "$RC" = 0 ] || fehler "3. Aufruf: Exit $RC ($(cat "$F/err"))"
cmp -s "$F/.env" "$F/.env.stand" || fehler "sales-.env im 3. Aufruf veraendert (nicht byte-gleich)"
[ "$(sicherungen)" = 1 ] || fehler "3. Aufruf legte eine Sicherung an"
[ "$(zaehle mint-count)" = 1 ] || fehler "3. Aufruf holte einen neuen Token"
[ "$(zaehle put-count)" = 2 ] || fehler "3. Aufruf: PUT-Pruefung fehlt (put-count $(zaehle put-count))"
grep -q 'schon' "$F/out" || fehler "3. Aufruf meldet nicht 'steht schon'"
[ "$(zaehle diag-count)" = 2 ] || fehler "3. Aufruf: Not-Aus nicht erneut gesetzt"
ohne_geheimnisse "3. Aufruf"

# === 4. Ungueltiger Schluessel in der sales-.env: neuer Token ===
grep -v '^VEXA_API_KEY=' "$F/.env" > "$F/.env.x"; printf 'VEXA_API_KEY=vxa_bot_veraltet0000\n' >> "$F/.env.x"; mv "$F/.env.x" "$F/.env"
lauf
[ "$RC" = 0 ] || fehler "4. Aufruf: Exit $RC ($(cat "$F/err"))"
[ "$(zaehle mint-count)" = 2 ] || fehler "ungueltiger Schluessel: erwartet neuen Token, mint-count $(zaehle mint-count)"
! grep -q veraltet "$F/.env" || fehler "alter Schluessel steht noch in der .env"
[ "$(grep -c '^VEXA_API_KEY=' "$F/.env")" = 1 ] || fehler "VEXA_API_KEY nach Erneuerung nicht genau einmal"
[ "$(sicherungen)" = 2 ] || fehler "erwartet 2 Sicherungen, sind $(sicherungen)"
ohne_geheimnisse "4. Aufruf"

# === 5. Ohne python3 im Container (grep-Rueckfall beim JSON-Lesen) ===
fall b
printf '#!/bin/sh\nexit 127\n' > "$T/bin/python3"; chmod +x "$T/bin/python3"
lauf; [ "$RC" = 4 ] || fehler "ohne python3, 1. Aufruf: Exit $RC"
: > "$F/state/up"; lauf
[ "$RC" = 0 ] || fehler "ohne python3, 2. Aufruf: Exit $RC ($(cat "$F/err"))"
grep -qE '^VEXA_API_KEY=vxa_bot_[A-Za-z0-9]{32}$' "$F/.env" || fehler "ohne python3: Schluessel nicht eingetragen"
rm -f "$T/bin/python3"

# === 6. Volume vexa-pgdata existiert, .env fehlt: nicht neu erzeugen (Exit 5) ===
fall c
: > "$F/state/volume"
lauf
[ "$RC" = 5 ] || fehler "Volume ohne .env: Exit $RC statt 5"
[ ! -e "$F/vexa/.env" ] || fehler "Volume ohne .env: .env wurde trotzdem angelegt"

# === 7. Platzhalter in irgendeiner Zeile der Vexa-.env: Abbruch ===
fall d
printf 'ADMIN_TOKEN=%s\nVEXA_DB_PASSWORD=PLATZHALTER-x\nVEXA_S3_ACCESS_KEY=%s\nVEXA_S3_SECRET_KEY=%s\n' \
  "$(printf 'a%.0s' {1..32})" "$(printf 'b%.0s' {1..20})" "$(printf 'c%.0s' {1..32})" > "$F/vexa/.env"
: > "$F/state/up"
lauf
[ "$RC" = 1 ] || fehler "Platzhalter: Exit $RC statt 1"
[ "$(zaehle mint-count)" = 0 ] || fehler "Platzhalter: trotzdem Token geholt"

# === 8. sales-.env fehlt: Abbruch, nichts angelegt ===
fall e keine-sales-env
: > "$F/state/up"
printf 'ADMIN_TOKEN=%s\nVEXA_DB_PASSWORD=%s\nVEXA_S3_ACCESS_KEY=%s\nVEXA_S3_SECRET_KEY=%s\n' \
  "$(printf 'a%.0s' {1..32})" "$(printf 'b%.0s' {1..32})" "$(printf 'c%.0s' {1..20})" "$(printf 'd%.0s' {1..32})" > "$F/vexa/.env"
lauf
[ "$RC" = 1 ] || fehler "ohne sales-.env: Exit $RC statt 1"
[ ! -e "$F/.env" ] || fehler "ohne sales-.env: Datei angelegt"
[ "$(zaehle mint-count)" = 0 ] || fehler "ohne sales-.env: trotzdem Token geholt"

# === 9. Not-Aus scheitert: Abbruch, kein Token, sales-.env unveraendert ===
fall f
printf 'ADMIN_TOKEN=%s
VEXA_DB_PASSWORD=%s
VEXA_S3_ACCESS_KEY=%s
VEXA_S3_SECRET_KEY=%s
'   "$(printf 'a%.0s' {1..32})" "$(printf 'b%.0s' {1..32})" "$(printf 'c%.0s' {1..20})" "$(printf 'd%.0s' {1..32})" > "$F/vexa/.env"
: > "$F/state/up"
DIAG_KAPUTT=1; export DIAG_KAPUTT
lauf
unset DIAG_KAPUTT
[ "$RC" = 1 ] || fehler "Not-Aus kaputt: Exit $RC statt 1"
grep -q 'capture_signal' "$F/err" || fehler "Not-Aus kaputt: keine Meldung"
[ "$(cat "$F/.env")" = "ANDERES=1" ] || fehler "Not-Aus kaputt: sales-.env veraendert"
[ "$(zaehle mint-count)" = 0 ] || fehler "Not-Aus kaputt: trotzdem Token geholt"

echo "OK: vexa-anbinden"
