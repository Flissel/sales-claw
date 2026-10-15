#!/usr/bin/env bash
# Test fuer deploy/linkedin-nachlauf.sh mit gefaelschtem docker.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/linkedin-nachlauf.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# Falsches docker: protokolliert jeden Aufruf (ein Argument je Zeile, NUL-
# frei), beantwortet die Nachlauf-CLI und laesst das Senden je nach
# $T/senden_scheitert scheitern.
cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/log"
case "$*" in
  *"linkedin_nachlauf.py liste"*)
    if [ -f "$T/zwei" ]; then printf 'd-1\nd-2\n'; else printf 'd-1\n'; fi ;;
  *"linkedin_nachlauf.py text d-1"*) printf 'LinkedIn-Post ist online: https://x/\n- @A & "B" $HOME `id`\n' ;;
  *"linkedin_nachlauf.py text d-2"*) printf 'LinkedIn-Post ist online: https://y/\n' ;;
  *"linkedin_nachlauf.py gemeldet "*)
    [ -f "$T/buchen_scheitert" ] && exit 1
    echo gebucht >> "$T/gebucht" ;;
  *"message send"*) [ -f "$T/senden_scheitert" ] && exit 1; exit 0 ;;
esac
EOF
chmod +x "$T/docker"

fehler() { echo "FEHLER: $*"; exit 1; }

# 1. Ohne Nummer: Abbruch, nichts gesendet
leer="$T/leer"; mkdir -p "$leer"
if DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="" WURZEL_ENV="$leer/.env" bash "$SKRIPT" >/dev/null 2>&1; then
  fehler "ohne Nummer haette das Skript abbrechen muessen"
fi
[ ! -f "$T/log" ] || ! grep -q "message send" "$T/log" || fehler "ohne Nummer gesendet"

# 2. Senden scheitert: nicht gebucht
touch "$T/senden_scheitert"
DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" >/dev/null 2>&1 || true
[ ! -f "$T/gebucht" ] || fehler "trotz Sendefehler gebucht"
rm "$T/senden_scheitert"; : > "$T/log"

# 3. Erfolg: Text woertlich als EIN Argument, danach gebucht
DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" >/dev/null
grep -q '^<+491749708452>$' "$T/log" || fehler "Nummer nicht als eigenes Argument"
# Der Text ist mehrzeilig: das Protokoll zeigt ihn als "<Zeile1" ... "Zeile2>",
# also Anfangs- und Endmarke pruefen. Beide stehen nur dann so im Protokoll,
# wenn der Text als ein einziges Argument ankam (zwischen < und >).
grep -qF -- '<LinkedIn-Post ist online: https://x/' "$T/log" || fehler "Textanfang nicht uebergeben"
grep -qF -- '- @A & "B" $HOME `id`>' "$T/log" || fehler "Text nicht woertlich uebergeben"
[ "$(cat "$T/gebucht")" = "gebucht" ] || fehler "nach Erfolg nicht gebucht"

# 4. --trocken: zeigt, sendet nicht, bucht nicht
rm -f "$T/gebucht"; : > "$T/log"
aus="$(DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" --trocken)"
echo "$aus" | grep -q "LinkedIn-Post ist online" || fehler "--trocken zeigt keinen Text"
! grep -q "message send" "$T/log" || fehler "--trocken hat gesendet"
[ ! -f "$T/gebucht" ] || fehler "--trocken hat gebucht"

# 5. Jeder docker-Aufruf laeuft unter dem Zeitlimit (Final-Review I3):
#    ZEITLIMIT ersetzt "timeout 60" durch einen protokollierenden Wrapper.
rm -f "$T/gebucht"; : > "$T/log"
cat > "$T/zeit" <<'EOF'
#!/usr/bin/env bash
printf 'ZEITLIMIT %s\n' "$1" >> "$(dirname "$0")/log"
shift; exec "$@"
EOF
chmod +x "$T/zeit"
ZEITLIMIT="$T/zeit 60" DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" >/dev/null
aufrufe="$(grep -c '^AUFRUF' "$T/log")"
limits="$(grep -c '^ZEITLIMIT 60$' "$T/log" || true)"
[ "$aufrufe" = 4 ] || fehler "erwartet 4 docker-Aufrufe, waren $aufrufe"
[ "$limits" = "$aufrufe" ] || fehler "nicht jeder docker-Aufruf unter Zeitlimit ($limits/$aufrufe)"
grep -qF -- '- @A & "B" $HOME `id`>' "$T/log" || fehler "Text mit Zeitlimit nicht woertlich"
grep -qF 'ZEITLIMIT="${ZEITLIMIT-timeout 60}"' "$SKRIPT" || fehler "Vorgabe timeout 60 fehlt"
grep -q '^TimeoutStartSec=90$' "$WURZEL/deploy/systemd/sales-linkedin-nachlauf.service" \
  || fehler "Unit ohne TimeoutStartSec=90"

# 6. Gesendet, aber Buchen scheitert: laute WARNUNG, Schleife laeuft weiter
rm -f "$T/gebucht"; : > "$T/log"; touch "$T/zwei" "$T/buchen_scheitert"
fehl="$(DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" 2>&1 >/dev/null)" \
  || fehler "Buchungsfehler hat das Skript abgebrochen"
echo "$fehl" | grep -q 'WARNUNG: .*d-1.*gesendet aber nicht gebucht' || fehler "keine WARNUNG fuer d-1"
echo "$fehl" | grep -q 'WARNUNG: .*d-2.*gesendet aber nicht gebucht' || fehler "Schleife nach d-1 abgebrochen"
[ "$(grep -c -- '^<-m>$' "$T/log")" = 2 ] || fehler "nicht beide Meldungen gesendet"
rm -f "$T/zwei" "$T/buchen_scheitert"

echo "OK linkedin-nachlauf"
