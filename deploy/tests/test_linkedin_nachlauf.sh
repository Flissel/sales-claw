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
  *"linkedin_nachlauf.py liste"*) printf 'd-1\n' ;;
  *"linkedin_nachlauf.py text d-1"*) printf 'LinkedIn-Post ist online: https://x/\n- @A & "B" $HOME `id`\n' ;;
  *"linkedin_nachlauf.py gemeldet d-1"*) echo gebucht >> "$T/gebucht" ;;
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

echo "OK linkedin-nachlauf"
