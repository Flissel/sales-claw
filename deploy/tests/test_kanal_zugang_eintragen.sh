#!/usr/bin/env bash
# Test fuer deploy/kanal-zugang-eintragen.sh mit gefaelschtem docker und
# einer Wegwerf-.env. Fasst nie die echte .env und nie echte Dienste an.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/kanal-zugang-eintragen.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

fehler() { echo "FEHLER: $*"; exit 1; }

# Je Fall ein frischer Ordner mit .env und protokollierendem docker.
fall() { # name
  F="$T/$1"; mkdir -p "$F"
  printf 'ANDERES=1\nBLUESKY_HANDLE=alt.bsky.social\n' > "$F/.env"
  cat > "$F/docker" <<'EOF'
#!/usr/bin/env bash
{ printf 'PWD=%s ARGS=' "$PWD"; printf '%s ' "$@"; printf '\n'; } >> "$(dirname "$0")/log"
EOF
  chmod +x "$F/docker"
}
lauf() { # kanal (Eingabe aus $F/in); setzt RC
  set +e
  DOCKER="$F/docker" SALES_ENV_DATEI="$F/.env" bash "$SKRIPT" "$1" <"$F/in" >"$F/out" 2>"$F/err"
  RC=$?
  set -e
}
sicherungen() { find "$F" -maxdepth 1 -name '.env.vor-*' | wc -l | tr -d ' '; }

# 1.-4. Erfolg
fall gut
printf 'neu.bsky.social\nabcd-efgh-ijkl-mnop\n' > "$F/in"; lauf bluesky
[ "$RC" = 0 ] || fehler "Erfolg: Exit $RC ($(cat "$F/err"))"
[ "$(grep -c '^BLUESKY_HANDLE=' "$F/.env")" = 1 ] || fehler "BLUESKY_HANDLE nicht genau einmal"
grep -qx 'BLUESKY_HANDLE=neu.bsky.social' "$F/.env" || fehler "Handle nicht eingetragen"
grep -qx 'BLUESKY_APP_PASSWORD=abcd-efgh-ijkl-mnop' "$F/.env" || fehler "Passwort nicht eingetragen"
grep -qx 'ANDERES=1' "$F/.env" || fehler "fremde Zeile verloren"
# 2. kein Wert in der Ausgabe (auch nicht teilweise)
! grep -q 'abcd-efgh' "$F/out" "$F/err" || fehler "Passwort in der Ausgabe"
! grep -q 'neu.bsky' "$F/out" "$F/err" || fehler "Handle in der Ausgabe"
grep -q '^2 Wert(e) für bluesky eingetragen, Sicherung: .env.vor-bluesky-' "$F/out" \
  || fehler "Erfolgsmeldung fehlt: $(cat "$F/out")"
grep -q 'sales-kanaele neu erzeugt – Stand unter /einstellungen/kanaele.' "$F/out" \
  || fehler "Erfolgsmeldung unvollstaendig"
# 3. genau eine Sicherung mit altem Inhalt, Rechte 600 (nur Linux messbar)
[ "$(sicherungen)" = 1 ] || fehler "erwartet genau eine Sicherung, sind $(sicherungen)"
S="$(find "$F" -maxdepth 1 -name '.env.vor-bluesky-*')"
[ "$(cat "$S")" = "$(printf 'ANDERES=1\nBLUESKY_HANDLE=alt.bsky.social')" ] || fehler "Sicherung nicht der alte Stand"
if [ "$(uname -s)" = Linux ]; then
  [ "$(stat -c %a "$F/.env")" = 600 ] || fehler ".env nicht 600"
  [ "$(stat -c %a "$S")" = 600 ] || fehler "Sicherung nicht 600"
fi
[ -z "$(find "$F" -maxdepth 1 -name '.env.neu*')" ] || fehler "Zwischendatei liegen geblieben"
# 4. genau ein docker-Aufruf, nur sales-kanaele, im Projektordner
[ "$(wc -l < "$F/log" | tr -d ' ')" = 1 ] || fehler "erwartet einen docker-Aufruf"
grep -q 'ARGS=compose up -d --no-deps --force-recreate sales-kanaele $' "$F/log" \
  || fehler "falscher docker-Aufruf: $(cat "$F/log")"
grep -qF "PWD=$(cd "$F" && pwd) " "$F/log" || fehler "docker nicht im Projektordner"
! grep -q 'abcd-efgh' "$F/log" || fehler "Passwort an docker uebergeben"

# 5. unzulaessiges Zeichen ($ wuerde Compose interpolieren): nichts passiert
fall dollar
vorher="$(cat "$F/.env")"
printf '%s\n' 'neu.bsky.social' 'pa$$wort' > "$F/in"; lauf bluesky
[ "$RC" = 3 ] || fehler "\$-Wert: Exit $RC statt 3"
[ "$(cat "$F/.env")" = "$vorher" ] || fehler "\$-Wert: .env veraendert"
[ "$(sicherungen)" = 0 ] || fehler "\$-Wert: Sicherung angelegt"
[ ! -f "$F/log" ] || fehler "\$-Wert: docker aufgerufen"
! grep -q 'wort' "$F/out" "$F/err" || fehler "\$-Wert in der Ausgabe"
grep -q 'BLUESKY_APP_PASSWORD enthält unzulässige Zeichen' "$F/err" || fehler "\$-Wert: Meldung fehlt"
# weitere Zeichen, die Compose oder die Datei zerlegen wuerden
for boese in 'a b' 'a#b' 'a"b' "a'b" 'a`b' 'a\b'; do
  fall boese
  printf '%s\n' 'neu.bsky.social' "$boese" > "$F/in"; lauf bluesky
  [ "$RC" = 3 ] || fehler "Wert mit Sonderzeichen: Exit $RC statt 3"
  [ ! -f "$F/log" ] || fehler "Wert mit Sonderzeichen: docker aufgerufen"
  rm -rf "$F"
done

# 6. leerer Wert -> 3, unbekannter Kanal -> 2
fall leer
printf 'neu.bsky.social\n\n' > "$F/in"; lauf bluesky
[ "$RC" = 3 ] || fehler "leerer Wert: Exit $RC statt 3"
[ "$(sicherungen)" = 0 ] || fehler "leerer Wert: Sicherung angelegt"
[ ! -f "$F/log" ] || fehler "leerer Wert: docker aufgerufen"
fall eof
printf 'neu.bsky.social\n' > "$F/in"; lauf bluesky
[ "$RC" = 3 ] || fehler "fehlende Eingabe: Exit $RC statt 3"
fall unbekannt
printf 'x\n' > "$F/in"; lauf instagram
[ "$RC" = 2 ] || fehler "unbekannter Kanal: Exit $RC statt 2"
grep -q 'telegram_kanal' "$F/err" || fehler "unbekannter Kanal: keine Liste"
[ ! -f "$F/log" ] || fehler "unbekannter Kanal: docker aufgerufen"
fall ohne
printf 'x\n' | { set +e; DOCKER="$F/docker" SALES_ENV_DATEI="$F/.env" bash "$SKRIPT" >/dev/null 2>&1; echo $? > "$F/rc"; }
[ "$(cat "$F/rc")" = 2 ] || fehler "ohne Kanal: Exit $(cat "$F/rc") statt 2"

# 7. Windows-Zeilenende wird entfernt; Kanal mit einem Namen
fall crlf
printf 'https://discord.com/api/webhooks/1/ab_c-d\r\n' > "$F/in"; lauf discord
[ "$RC" = 0 ] || fehler "CRLF: Exit $RC ($(cat "$F/err"))"
grep -qx 'DISCORD_ANKUENDIGUNG_WEBHOOK=https://discord.com/api/webhooks/1/ab_c-d' "$F/.env" \
  || fehler "CRLF: Wert nicht sauber eingetragen"
! grep -q $'\r' "$F/.env" || fehler "CRLF: \\r in .env"
grep -q '^1 Wert(e) für discord eingetragen' "$F/out" || fehler "CRLF: Meldung"

# Alte .env ohne Zeilenende am Schluss: neue Zeile klebt nicht an
fall ohne_nl
printf 'ANDERES=1' > "$F/.env"
printf 'abc123\n' > "$F/in"; lauf devto
[ "$RC" = 0 ] || fehler "ohne Zeilenende: Exit $RC"
grep -qx 'ANDERES=1' "$F/.env" && grep -qx 'DEVTO_API_KEY=abc123' "$F/.env" \
  || fehler "ohne Zeilenende: Zeilen verklebt"

# docker scheitert: Exit != 0, Werte stehen trotzdem (Sicherung vorhanden)
fall docker_rot
printf '#!/usr/bin/env bash\nexit 1\n' > "$F/docker"
printf 'abc123\n' > "$F/in"; lauf devto
[ "$RC" != 0 ] || fehler "docker rot: Exit 0"
grep -qx 'DEVTO_API_KEY=abc123' "$F/.env" || fehler "docker rot: Wert fehlt"
! grep -q 'abc123' "$F/out" "$F/err" || fehler "docker rot: Wert in der Ausgabe"

# Statische Waechter
! grep -Eq '^[^#]*set -[a-z]*x' "$SKRIPT" || fehler "set -x im Skript"
grep -q 'IFS= read -r -s -p' "$SKRIPT" || fehler "read -s fehlt"

echo OK
