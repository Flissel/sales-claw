#!/usr/bin/env bash
# deploy/pm-anbinden.sh — haengt pm-claw (Projektverwaltung) als MCP-Server
# `pm` an das laufende sales-claw-Gateway. Wiederholbar.
#
# WOZU: Sales Claw ist die Tuerklingel zu pm-claw (pm-claw Stufe 2 §8):
# "mach Projektaufnahme mit X" legt dort Akte und Entwurf der ersten
# Fragerunde an. Sichtbar sind genau zwei Werkzeuge, aufnahme_anstossen und
# aufnahme_status — toolFilter in der Saat plus Rollentor in pm-mcp.
#
# WARUM EIN SKRIPT: wie bei deploy/rowboat-anbinden.sh. config/openclaw.json
# traegt den Eintrag mcp.servers.pm (URL, Transport, Timeouts, toolFilter),
# aber nicht den Bearer-Token: openclaw 2026.7.1 kennt fuer
# mcp.servers.*.headers keine Env-Referenz. Der Token darf nicht ins Git und
# nicht dauerhaft in die Umgebung des Dienstes sales-claw, also setzt ihn
# dieses Skript aus der .env (PM_TOKEN_SALES, von Hand aus ~/pm-claw/.env
# kopiert) ins Laufzeit-Volume (sales-claw-state).
#
# DER TOKEN ERSCHEINT NIRGENDS: er geht per `-e` als Umgebungsvariable in
# einen Einmal-Aufruf im Container, nie als Argument dieses Skripts; jede
# Ausgabe wird vor dem Drucken durchgesiebt. Innerhalb des Containers steht
# er fuer die Dauer von `openclaw mcp set` in dessen Argumenten.
#
# VORAUSSETZUNG: der Dienst sales-claw haengt im Netz pm-claw_default
# (docker-compose.yml) — also pm-claw-Stack laeuft, sales-claw danach neu
# erzeugt. Sonst loest pm-mcp nicht auf und die Probe unten wird rot.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

for werkzeug in docker; do
  command -v "$werkzeug" >/dev/null || { echo "FEHLT: $werkzeug" >&2; exit 1; }
done
[ -f .env ] || { echo "FEHLT: $WURZEL/.env" >&2; exit 1; }

# Nur diese eine Variable wird gelesen — die Datei nie angezeigt.
TOKEN="$(grep -E '^PM_TOKEN_SALES=' .env | cut -d= -f2- | tr -d '[:space:]"' || true)"
if [ -z "$TOKEN" ]; then
  echo "FEHLT: PM_TOKEN_SALES in .env — von Hand aus ~/pm-claw/.env kopieren" >&2
  echo "       (gleicher Name, .env Modus 600). Nicht erfinden." >&2
  exit 1
fi

if [ "$(docker inspect -f '{{.State.Status}}' sales-claw 2>/dev/null || echo fehlt)" != "running" ]; then
  echo "ABBRUCH: sales-claw laeuft nicht — das Gateway muss stehen, bevor es Server lernt." >&2
  exit 1
fi
if ! docker inspect -f '{{json .NetworkSettings.Networks}}' sales-claw | grep '"pm-claw_default"' >/dev/null; then
  echo "ABBRUCH: sales-claw haengt nicht im Netz pm-claw_default." >&2
  echo "         pm-claw-Stack starten, dann sales-claw neu erzeugen (mit Felix abgestimmt)." >&2
  exit 1
fi

sieb() { sed "s#${TOKEN}#<token>#g"; }

# 1) Saat-Eintrag lesen, Token ergaenzen, im Gateway setzen, neu laden.
echo "1) Eintrag mcp.servers.pm aus der Saat + Token -> Laufzeit-Volume"
docker compose exec -T -e PM_TOKEN_SALES="$TOKEN" sales-claw node -e '
  const { execFileSync } = require("node:child_process");
  const saat = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
  const eintrag = saat?.mcp?.servers?.pm;
  if (!eintrag) { console.error("Saat ohne mcp.servers.pm"); process.exit(1); }
  eintrag.headers = { Authorization: "Bearer " + process.env.PM_TOKEN_SALES };
  const lauf = (args) => execFileSync("openclaw", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  process.stdout.write(lauf(["mcp", "set", "pm", JSON.stringify(eintrag)]));
  process.stdout.write(lauf(["mcp", "reload"]));
' < config/openclaw.json 2>&1 | sieb

# 2) Beweis: Verbindung steht, genau die zwei Werkzeuge sind sichtbar.
echo "2) Probe"
PROBE="$(docker compose exec -T sales-claw openclaw mcp probe pm --json 2>&1 | sieb || true)"
ROT=0
for w in aufnahme_anstossen aufnahme_status; do
  if printf '%s' "$PROBE" | grep -q "pm__$w"; then echo "   ok   $w"; else echo "   FEHL $w"; ROT=$((ROT+1)); fi
done
ANZAHL="$(printf '%s' "$PROBE" | grep -o 'pm__[a-z_]*' | sort -u | wc -l | tr -d ' ')"
if [ "$ANZAHL" != "2" ]; then
  echo "   FEHL $ANZAHL pm-Werkzeuge sichtbar statt 2 — toolFilter greift nicht"; ROT=$((ROT+1))
fi
if [ "$ROT" -ne 0 ]; then
  echo "--- Probe-Ausgabe (gesiebt):"; printf '%s\n' "$PROBE" | head -40
  echo "ROT: $ROT — pm-mcp antwortet nicht wie erwartet. HTTP 401 oder 'darf ... nicht aufrufen':" >&2
  echo "     Token stimmt nicht, oder pm-mcp lief beim Anlegen des Tokens schon (dann auf pm-claw:" >&2
  echo "     docker compose up -d pm-mcp)." >&2
  exit "$ROT"
fi
echo "pm-claw ist angebunden. Naechster Schritt im Selbst-Chat (schreibt nichts):"
echo "  aufnahme_status('pm-anbindung-test-nie-vergeben') -> muss {\"fehler\": \"unbekannt: ...\"} liefern."
echo "  KEIN Test mit einer gueltigen Mailadresse - das legt eine echte Akte an."
