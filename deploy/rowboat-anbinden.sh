#!/usr/bin/env bash
# deploy/rowboat-anbinden.sh — haengt die VibeMind-Wissensbasis (Rowboat) als
# zweiten MCP-Server an das laufende sales-claw-Gateway. Wiederholbar.
#
# WARUM EIN SKRIPT UND NICHT NUR DIE SAAT. config/openclaw.json traegt den
# Eintrag mcp.servers.rowboat (URL, Transport, Timeouts, toolFilter) — aber
# nicht den Bearer-Schluessel: openclaw 2026.7.1 kennt fuer
# mcp.servers.*.headers keine Env-Referenz (Schema geprueft am 01.09.2026,
# nur Klartext). Der Schluessel darf nicht ins Git, also setzt ihn dieses
# Skript aus der .env ins Laufzeit-Volume (sales-claw-state). Das ist
# dieselbe Config-Grenze wie bei `sales` (docs/04): Git besitzt die
# Struktur, das Volume den Zustand — nur dass der Schritt hier ein Skript
# ist und kein von Hand getippter `openclaw mcp add` (Lehre vom 31.08.:
# von Hand Registriertes fehlt in der Saat, bis es jemand vermisst).
#
# DER SCHLUESSEL ERSCHEINT NIRGENDS: er geht per `-e` als Umgebungs-
# variable in den Container, nie als Argument dieses Skripts; jede Ausgabe
# wird vor dem Drucken durchgesiebt. Innerhalb des Containers steht er fuer
# die Dauer von `openclaw mcp set` in dessen Argumenten — im PID-Namensraum
# des Containers, nicht auf dem Wirt.
#
# NUR LESEND gegenueber Rowboat: das Gateway bekommt drei Lese-Werkzeuge.
# Schreibwege gibt es im Endpunkt bewusst nicht (Phase 2.2 offen, und die
# braucht die Freigabe-Schiene ueber OpenFang).
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

for werkzeug in docker; do
  command -v "$werkzeug" >/dev/null || { echo "FEHLT: $werkzeug" >&2; exit 1; }
done
[ -f .env ] || { echo "FEHLT: $WURZEL/.env" >&2; exit 1; }

# Nur diese eine Variable wird gelesen — die Datei nie angezeigt.
SCHLUESSEL="$(grep -E '^ROWBOAT_API_KEY=' .env | cut -d= -f2- | tr -d '[:space:]"' || true)"
if [ -z "$SCHLUESSEL" ]; then
  echo "FEHLT: ROWBOAT_API_KEY in .env (Projekt-Schluessel aus der Rowboat-UI," >&2
  echo "       derselbe wie in der VibeMind-.env — ein System, ein Schluessel)." >&2
  exit 1
fi

if [ "$(docker inspect -f '{{.State.Status}}' sales-claw 2>/dev/null || echo fehlt)" != "running" ]; then
  echo "ABBRUCH: sales-claw laeuft nicht — das Gateway muss stehen, bevor es Server lernt." >&2
  exit 1
fi

sieb() { sed "s#${SCHLUESSEL}#<schluessel>#g"; }

# 1) Saat-Eintrag lesen, Schluessel ergaenzen, im Gateway setzen, neu laden.
#    Alles im Container (node ist dort, python auf dem Wirt nicht garantiert).
echo "1) Eintrag mcp.servers.rowboat aus der Saat + Schluessel -> Laufzeit-Volume"
docker compose exec -T -e ROWBOAT_API_KEY="$SCHLUESSEL" sales-claw node -e '
  const { execFileSync } = require("node:child_process");
  const saat = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
  const eintrag = saat?.mcp?.servers?.rowboat;
  if (!eintrag) { console.error("Saat ohne mcp.servers.rowboat"); process.exit(1); }
  eintrag.headers = { Authorization: "Bearer " + process.env.ROWBOAT_API_KEY };
  const lauf = (args) => execFileSync("openclaw", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  process.stdout.write(lauf(["mcp", "set", "rowboat", JSON.stringify(eintrag)]));
  process.stdout.write(lauf(["mcp", "reload"]));
' < config/openclaw.json 2>&1 | sieb

# 2) Beweis: Verbindung steht und die drei Werkzeuge sind sichtbar.
echo "2) Probe"
PROBE="$(docker compose exec -T sales-claw openclaw mcp probe rowboat --json 2>&1 | sieb || true)"
ROT=0
for w in rowboat_wissensquellen rowboat_wissensquelle rowboat_dokumente; do
  if printf '%s' "$PROBE" | grep -q "\"$w\""; then echo "   ok   $w"; else echo "   FEHL $w"; ROT=$((ROT+1)); fi
done
if printf '%s' "$PROBE" | grep -q '"rowboat_datei_url"'; then
  echo "   FEHL rowboat_datei_url ist sichtbar — toolFilter greift nicht"; ROT=$((ROT+1))
fi
if [ "$ROT" -ne 0 ]; then
  echo "--- Probe-Ausgabe (gesiebt):"; printf '%s\n' "$PROBE" | head -40
  echo "ROT: $ROT — Rowboat antwortet nicht wie erwartet. Erreichbarkeit pruefen:" >&2
  echo "     docker exec sales-claw node -e 'fetch(\"http://192.168.178.65:3100/api/mcp\",{method:\"POST\",body:\"{}\"}).then(r=>r.text()).then(console.log)'" >&2
  exit "$ROT"
fi
echo "Rowboat ist angebunden. Naechster Schritt: deploy/smoke.sh (Pruefung 4 erwartet jetzt sales UND rowboat)."
