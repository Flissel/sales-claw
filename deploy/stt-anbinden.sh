#!/usr/bin/env bash
# deploy/stt-anbinden.sh - Sprachnachrichten im Selbst-Chat abschreiben
# (11.11.2026). Wiederholbar, nur der Basis-Laden (sales-claw).
#
#   bash deploy/stt-anbinden.sh
#
# Was es tut (alles im laufenden Gateway, ohne Neustart):
#   1. liest STT_URL und STT_SCHLUESSEL aus der .env (dieselben Werte, mit
#      denen sales-mcp Kunden-Sprachnachrichten abschreibt)
#   2. legt im Volume stt/sprachnotiz.mjs (CLI) und stt/zugang.json (0600)
#      an - beides per stdin, der Schluessel steht in keiner Kommandozeile
#   3. setzt tools.media.audio aus deploy/stt/media-audio.json (config set,
#      das Gateway laedt neu)
#   4. Probe: /gesundheit, dann ein Abschreibelauf mit 1 s Stille ueber
#      genau die CLI, die OpenClaw aufruft (erwartet: "keine Sprache erkannt";
#      401 = falscher Schluessel, nicht erreichbar = PC aus)
#
# Warum nur der Basis-Laden: sales-stt laeuft am PC des Betreibers. Die
# Sprachnachrichten eines anderen Ladens schickt dieses Skript nicht dorthin.
# Startet nichts, baut nichts, gibt den Schluessel nie aus.
set +x
set -euo pipefail
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"
CONTAINER="sales-claw"
ENV_DATEI="$WURZEL/.env"
ORDNER="/home/node/.openclaw/stt"
[ -f "$ENV_DATEI" ] || { echo "FEHLT: $ENV_DATEI" >&2; exit 1; }
for f in deploy/stt/sprachnotiz.mjs deploy/stt/media-audio.json; do
  [ -f "$WURZEL/$f" ] || { echo "FEHLT: $f" >&2; exit 1; }
done
if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo fehlt)" != "running" ]; then
  echo "ABBRUCH: $CONTAINER laeuft nicht." >&2; exit 1
fi

# 1) Nur diese zwei Variablen aus der .env (CR und Anfuehrungszeichen weg).
wert() { grep -E "^$1=" "$ENV_DATEI" | tail -n 1 | cut -d= -f2- | tr -d '\r"' || true; }
URL="$(wert STT_URL)"
SCHLUESSEL="$(wert STT_SCHLUESSEL)"
URL="${URL%/}"
if ! [[ $URL =~ ^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
  echo "ABBRUCH: STT_URL in .env fehlt oder hat ein unerwartetes Format - nichts geaendert." >&2; exit 1
fi
if [ -z "$SCHLUESSEL" ]; then
  echo "ABBRUCH: STT_SCHLUESSEL in .env ist leer (am PC Pflicht) - nichts geaendert." >&2; exit 1
fi
echo "1) Zugang aus .env gelesen (STT_URL gesetzt, Schluessel gesetzt)"

# 2) CLI und Zugang ins Volume - als Nutzer node, per stdin.
echo "2) $ORDNER/sprachnotiz.mjs + zugang.json (0600)"
docker exec -i "$CONTAINER" sh -c "umask 077 && mkdir -p '$ORDNER' && cat > '$ORDNER/sprachnotiz.mjs'" \
  < "$WURZEL/deploy/stt/sprachnotiz.mjs"
printf '%s\n%s\n' "$URL" "$SCHLUESSEL" | docker exec -i "$CONTAINER" node -e '
  const fs = require("node:fs");
  const [url, schluessel] = fs.readFileSync(0, "utf8").split("\n");
  const ziel = "/home/node/.openclaw/stt/zugang.json";
  fs.writeFileSync(ziel + ".neu", JSON.stringify({ url, schluessel }) + "\n", { mode: 0o600 });
  fs.chmodSync(ziel + ".neu", 0o600);
  fs.renameSync(ziel + ".neu", ziel);
'
unset SCHLUESSEL

# 3) tools.media.audio setzen (nur wenn anders - sonst kein unnoetiges Neuladen).
echo "3) tools.media.audio aus deploy/stt/media-audio.json"
docker exec -i "$CONTAINER" node -e '
  const fs = require("node:fs");
  const { execFileSync } = require("node:child_process");
  const soll = JSON.parse(fs.readFileSync(0, "utf8"));
  const c = JSON.parse(fs.readFileSync("/home/node/.openclaw/openclaw.json", "utf8"));
  const norm = (v) => Array.isArray(v) ? v.map(norm) : (v && typeof v === "object")
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])])) : v;
  if (JSON.stringify(norm(c?.tools?.media?.audio)) === JSON.stringify(norm(soll))) {
    console.log("   war schon gesetzt");
  } else {
    try {
      execFileSync("openclaw", ["config", "set", "tools.media.audio", JSON.stringify(soll)],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    } catch (e) {
      const text = String(e && e.stderr || "") + " " + String(e && e.message || "");
      console.error("   ABBRUCH: das Gateway hat tools.media.audio abgelehnt: " + text.replace(/\s+/g, " ").slice(0, 300));
      process.exit(5);
    }
    console.log("   gesetzt");
  }
' < "$WURZEL/deploy/stt/media-audio.json"

# 4) Probe aus dem Gateway: erst Erreichbarkeit, dann die CLI selbst mit Stille.
echo "4) Probe (sales-stt am PC; der erste Lauf laedt das Modell, bis ~60 s)"
GESUND="$(docker exec "$CONTAINER" node -e '
  const z = JSON.parse(require("node:fs").readFileSync("/home/node/.openclaw/stt/zugang.json", "utf8"));
  fetch(z.url + "/gesundheit", { signal: AbortSignal.timeout(10000) })
    .then((r) => r.json()).then((d) => console.log(d && d.bereit === true ? "ok" : "nicht bereit"))
    .catch((e) => console.log("nicht erreichbar " + String((e && e.cause && e.cause.code) || (e && e.name) || "")));
' 2>/dev/null | tr -cd 'A-Za-z0-9 ._-' | cut -c1-80 || true)"
if [ "$GESUND" != "ok" ]; then
  echo "   ROT: /gesundheit: ${GESUND:-keine Antwort} - ist der PC an (Aufgabe VibeMind Sales-STT)?" >&2
  echo "   Eingerichtet ist alles; Sprachnachrichten bleiben Anhang, bis sales-stt erreichbar ist." >&2
  exit 3
fi
echo "   ok: /gesundheit"
RC=0
LAUF="$(docker exec "$CONTAINER" sh -c "node -e '
  const k = 16000, d = Buffer.alloc(44 + 2 * k);
  d.write(\"RIFF\", 0); d.writeUInt32LE(36 + 2 * k, 4); d.write(\"WAVEfmt \", 8);
  d.writeUInt32LE(16, 16); d.writeUInt16LE(1, 20); d.writeUInt16LE(1, 22);
  d.writeUInt32LE(k, 24); d.writeUInt32LE(2 * k, 28); d.writeUInt16LE(2, 32);
  d.writeUInt16LE(16, 34); d.write(\"data\", 36); d.writeUInt32LE(2 * k, 40);
  require(\"node:fs\").writeFileSync(\"/tmp/stt-probe.wav\", d);
' && node '$ORDNER/sprachnotiz.mjs' /tmp/stt-probe.wav; r=\$?; rm -f /tmp/stt-probe.wav; exit \$r" 2>&1)" || RC=$?
LAUF="$(printf '%s' "$LAUF" | tr -cd 'A-Za-z0-9 ():._-' | cut -c1-120)"
# Stille: Code 5 ("keine Sprache erkannt") ist das erwartete Ergebnis, 0 auch in Ordnung.
if [ "$RC" != 0 ] && [ "$RC" != 5 ]; then
  echo "   ROT: Abschreibelauf (Code $RC): $LAUF" >&2
  echo "   HTTP 401 = STT_SCHLUESSEL passt nicht zum PC (Vibemind_V1/.env)." >&2
  exit 4
fi
echo "   ok: Abschreibelauf ueber die CLI (Code $RC)"
echo "Fertig. Test: im Selbst-Chat eine Sprachnachricht an den Salesman schicken."
