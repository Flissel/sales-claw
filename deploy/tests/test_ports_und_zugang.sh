#!/usr/bin/env bash
# Prueft deploy/ports-und-zugang.sh mit Attrappen fuer ss und tailscale.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# ss-Attrappe: meldet einen Lauscher fuer jeden Port in $T/lauscht.
cat > "$T/ss" <<'EOF'
#!/usr/bin/env bash
port="${@: -1}"; port="${port##*:}"
grep -qx "$port" "$(dirname "$0")/lauscht" 2>/dev/null && echo "LISTEN 0 0 *:$port"
exit 0
EOF
# tailscale-Attrappe: "serve status --json" liest $T/serve.json; "serve --bg
# --https P ZIEL" traegt die Regel ein, ausser $T/serve-kaputt existiert oder
# $T/serve-falsch (dann mit falschem Ziel).
cat > "$T/tailscale" <<'EOF'
#!/usr/bin/env bash
d="$(dirname "$0")"
if [ "$1 $2" = "serve status" ]; then cat "$d/serve.json"; exit 0; fi
if [ "$1 $2" = "serve --bg" ]; then
  [ -e "$d/serve-kaputt" ] && { echo "kaputt" >&2; exit 1; }
  port="${3#--https=}"; [ "$3" = "--https" ] && port="$4"
  ziel="${@: -1}"; [ -e "$d/serve-falsch" ] && ziel="http://127.0.0.1:1"
  python3 - "$d/serve.json" "$port" "$ziel" <<'PY'
import json, sys
pfad, port, ziel = sys.argv[1:]
d = json.load(open(pfad))
d.setdefault("TCP", {})[port] = {"HTTPS": True}
d.setdefault("Web", {})["host.ts.net:" + port] = {"Handlers": {"/": {"Proxy": ziel}}}
json.dump(d, open(pfad, "w"))
PY
  exit 0
fi
echo "unerwartet: $*" >&2; exit 2
EOF
chmod +x "$T/ss" "$T/tailscale"
export SS="$T/ss" TAILSCALE="$T/tailscale" SUDO=""
# shellcheck source=../ports-und-zugang.sh
. "$WURZEL/deploy/ports-und-zugang.sh"

pruefe() { if [ "$1" != "$2" ]; then echo "FEHLER: $3 — erwartet '$2', bekam '$1'"; exit 1; fi; }

# 1) freier_port ueberspringt lauschende Ports
printf '8791\n8792\n' > "$T/lauscht"
pruefe "$(freier_port 8791 8800)" 8793 "freier_port"

# 2) freier_serve_port ueberspringt Serve-Ports, auf denen nichts lauscht
#    (genau der Fall, den ss allein nicht sieht)
: > "$T/lauscht"
echo '{"TCP": {"443": {"HTTPS": true}, "8446": {"HTTPS": true}, "8447": {"HTTPS": true}}}' > "$T/serve.json"
pruefe "$(freier_serve_port 8446 8500)" 8448 "freier_serve_port gegen serve"

# 3) ... und Ports, auf denen etwas lauscht
echo 8448 > "$T/lauscht"
pruefe "$(freier_serve_port 8446 8500)" 8449 "freier_serve_port gegen ss"

# 4) leerer Serve-Zustand (tailscale gibt "{}" aus)
: > "$T/lauscht"; echo '{}' > "$T/serve.json"
pruefe "$(freier_serve_port 8446 8500)" 8446 "freier_serve_port leer"

# 5) Bereich erschoepft -> Exit 1
echo '{"TCP": {"8446": {}, "8447": {}}}' > "$T/serve.json"
if freier_serve_port 8446 8447 2>/dev/null; then echo "FEHLER: erschoepft nicht erkannt"; exit 1; fi

# 6) zugang_einrichten setzt die Regel und bestaetigt sie
echo '{}' > "$T/serve.json"
zugang_einrichten 8447 8793
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["Web"]["host.ts.net:8447"]["Handlers"]["/"]["Proxy"]=="http://127.0.0.1:8793"' "$T/serve.json"

# 7) Befehl scheitert -> Exit != 0
echo '{}' > "$T/serve.json"; touch "$T/serve-kaputt"
if zugang_einrichten 8447 8793 2>/dev/null; then echo "FEHLER: gescheiterter serve-Befehl nicht erkannt"; exit 1; fi
rm "$T/serve-kaputt"

# 8) Befehl meldet Erfolg, Regel zeigt aber woandershin -> Exit != 0
touch "$T/serve-falsch"
if zugang_einrichten 8447 8793 2>/dev/null; then echo "FEHLER: falsches Ziel nicht erkannt"; exit 1; fi
rm "$T/serve-falsch"

# 9) Port schon mit ANDEREM Ziel belegt -> nicht ueberschreiben, Exit != 0
echo '{"TCP": {"8447": {}}, "Web": {"h:8447": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5510"}}}}}' > "$T/serve.json"
if zugang_einrichten 8447 8793 2>/dev/null; then echo "FEHLER: fremde Regel ueberschrieben"; exit 1; fi
grep -q 5510 "$T/serve.json" || { echo "FEHLER: fremde Regel veraendert"; exit 1; }

echo "OK: ports-und-zugang"
