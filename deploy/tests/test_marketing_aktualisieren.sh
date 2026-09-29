#!/usr/bin/env bash
# Prueft deploy/marketing-aktualisieren.sh gegen ein lokales Wegwerf-Repo.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export GESUNDHEIT=true
SKRIPT="$WURZEL/deploy/marketing-aktualisieren.sh"
STAND="$T/marketing-os/.git/marketing-api-gestartet"
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/arbeit" 2>/dev/null
( cd "$T/arbeit" && git checkout -q -b master && mkdir -p spaces/marketing \
  && echo a > spaces/marketing/x && echo s > sonstwo && git add . \
  && git -c user.name=t -c user.email=t@t commit -qm eins \
  && git push -q origin master )
git clone -q -b master "$T/origin.git" "$T/marketing-os"
commit() { ( cd "$T/arbeit" && echo "$2" > "$1" && git -c user.name=t \
  -c user.email=t@t commit -qam "$2" && git push -q origin master ); }

# Stub fuer systemctl: protokolliert, scheitert bei "restart", solange
# $T/restart-kaputt existiert.
cat > "$T/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*"
if [ "$1" = restart ] && [ -e "$(dirname "$0")/restart-kaputt" ]; then exit 1; fi
exit 0
EOF
chmod +x "$T/systemctl"
export SYSTEMCTL="$T/systemctl"

# 1) fehlt der Checkout: 0 und Hinweis
out="$(MARKETING_OS="$T/fehlt" bash "$SKRIPT")"
echo "$out" | grep -q "nicht eingerichtet"

# 2) nichts Neues: kein Neustart
out="$(MARKETING_OS="$T/marketing-os" bash "$SKRIPT")"
if echo "$out" | grep -q "restart marketing-api"; then
  echo "FEHLER: Neustart ohne Aenderung"; exit 1; fi

# 3) neuer Stand unter spaces/marketing: vorspulen und Neustart
commit spaces/marketing/x b
out="$(MARKETING_OS="$T/marketing-os" bash "$SKRIPT")"
echo "$out" | grep -q "restart marketing-api"
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = b ]
[ "$(cat "$STAND")" = "$(git -C "$T/marketing-os" rev-parse HEAD)" ]

# 4) Aenderung ausserhalb spaces/marketing: vorspulen, kein Neustart
commit sonstwo t
out="$(MARKETING_OS="$T/marketing-os" bash "$SKRIPT")"
if echo "$out" | grep -q "restart marketing-api"; then
  echo "FEHLER: Neustart ohne relevante Aenderung"; exit 1; fi
[ "$(cat "$T/marketing-os/sonstwo")" = t ]

# 5) Neustart scheitert: Nicht-Null, Stand bleibt alt; der NAECHSTE Lauf
#    ohne neue Commits holt den Neustart nach.
commit spaces/marketing/x c
vorher="$(cat "$STAND")"
touch "$T/restart-kaputt"
if out="$(MARKETING_OS="$T/marketing-os" bash "$SKRIPT" 2>&1)"; then
  echo "FEHLER: gescheiterter Neustart ergab Null"; exit 1; fi
echo "$out" | grep -q "HINWEIS"
[ "$(cat "$STAND")" = "$vorher" ]
rm "$T/restart-kaputt"
out="$(MARKETING_OS="$T/marketing-os" bash "$SKRIPT")"
echo "$out" | grep -q "restart marketing-api" || {
  echo "FEHLER: Neustart nicht nachgeholt"; exit 1; }
[ "$(cat "$STAND")" = "$(git -C "$T/marketing-os" rev-parse HEAD)" ]

# 6) Gesundheitsprobe scheitert: Nicht-Null, Stand bleibt alt
commit spaces/marketing/x d
vorher="$(cat "$STAND")"
if MARKETING_OS="$T/marketing-os" GESUNDHEIT=false GESUNDHEIT_PAUSE=0 \
    bash "$SKRIPT" >/dev/null 2>&1; then
  echo "FEHLER: gescheiterte Gesundheitsprobe ergab Null"; exit 1; fi
[ "$(cat "$STAND")" = "$vorher" ]

# 6b) Platzhalter: liegen nach dem Lauf im Medienordner, ein zweiter Lauf
#     aendert nichts, eine abweichende Zieldatei wird ersetzt; fehlt der
#     Ordner, gibt es nur einen Hinweis (Nullstatus).
mkdir -p "$T/arbeit/spaces/marketing/vorlagen/newsletter/platzhalter"
printf 'png1' > "$T/arbeit/spaces/marketing/vorlagen/newsletter/platzhalter/platzhalter-2x1.png"
( cd "$T/arbeit" && git add . && git -c user.name=t -c user.email=t@t commit -qm platzhalter \
  && git push -q origin master )
mkdir -p "$T/medien"
MARKETING_OS="$T/marketing-os" MEDIEN_ERZEUGT="$T/medien" bash "$SKRIPT" >/dev/null
[ "$(cat "$T/medien/platzhalter-2x1.png")" = png1 ]
touch -d '2001-01-01 00:00:00' "$T/medien/platzhalter-2x1.png"
MARKETING_OS="$T/marketing-os" MEDIEN_ERZEUGT="$T/medien" bash "$SKRIPT" >/dev/null
[ "$(date -r "$T/medien/platzhalter-2x1.png" +%Y)" = 2001 ] || {
  echo "FEHLER: unveraenderter Platzhalter neu geschrieben"; exit 1; }
printf 'alt' > "$T/medien/platzhalter-2x1.png"
MARKETING_OS="$T/marketing-os" MEDIEN_ERZEUGT="$T/medien" bash "$SKRIPT" >/dev/null
[ "$(cat "$T/medien/platzhalter-2x1.png")" = png1 ]
out="$(MARKETING_OS="$T/marketing-os" MEDIEN_ERZEUGT="$T/fehlt-medien" bash "$SKRIPT" 2>&1)"
echo "$out" | grep -q "Platzhalter nicht abgelegt"

# 6c) Ablage scheitert (install per Stub im PATH, weil chmod unter Windows-
#     Git-Bash nichts sperrt): nie fatal.
#     Der Lauf endet wie ohne Platzhalter (hier: Neustart nachgeholt, Null),
#     mit HINWEIS auf stderr.
mkdir -p "$T/medien2" "$T/stub"
printf '#!/usr/bin/env bash\nexit 1\n' > "$T/stub/install"; chmod +x "$T/stub/install"
commit spaces/marketing/x e
out="$(PATH="$T/stub:$PATH" MARKETING_OS="$T/marketing-os" MEDIEN_ERZEUGT="$T/medien2" bash "$SKRIPT" 2>&1)" || {
  echo "FEHLER: gescheiterte Ablage machte den Lauf fatal"; exit 1; }
echo "$out" | grep -q "platzhalter-2x1.png nicht abgelegt"
echo "$out" | grep -q "restart marketing-api" || {
  echo "FEHLER: Neustart nach gescheiterter Ablage nicht erreicht"; exit 1; }
[ "$(cat "$STAND")" = "$(git -C "$T/marketing-os" rev-parse HEAD)" ]

# 7) lokale Aenderung: Abbruch mit Nicht-Null, nichts ueberschrieben
echo lokal > "$T/marketing-os/spaces/marketing/x"
if MARKETING_OS="$T/marketing-os" bash "$SKRIPT"; then
  echo "FEHLER: lokale Aenderung nicht erkannt"; exit 1; fi
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = lokal ]
echo "OK marketing-aktualisieren"
