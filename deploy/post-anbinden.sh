#!/usr/bin/env bash
# deploy/post-anbinden.sh — bindet die Post-Sammelstelle (sales-post) an das
# OpenClaw-Gateway EINES Ladens an (Stufe 1, 03.11.2026). Wiederholbar.
#
#   bash deploy/post-anbinden.sh            # Basis-Laden (sales-claw, .env)
#   bash deploy/post-anbinden.sh ivan       # Laden ivan (deploy/laeden/ivan.env)
#
# Voraussetzung: deploy/auto-anbinden.sh lief schon (Endpunkt + Token in der
# .env). Der Token wird hier NICHT neu geschrieben, nur wiederverwendet.
#
# Was es tut:
#   0. bricht ab, wenn POST_BESITZER in der .env leer ist (ohne Besitzer waere
#      jede Mail niemandem zugeordnet - privat heisst "nur der Besitzer")
#   1. deploy/post-schluessel.sh, falls POST_SCHLUESSEL_PRIVAT fehlt
#   2. db/post-sammelstelle.sql fuer das Schema des Ladens (idempotent)
#   3. benutzer.leitung = true fuer POST_BESITZER; Env-Postfaecher uebernehmen
#      (post_konten.env_konten_uebernehmen) - beides im sales-mcp-Container
#   4. Agent `post` in agents.list (tools.deny ["*"], eigener Arbeitsordner,
#      Modell anthropic/claude-haiku-5-5; lehnt `config set` das Feld ab, wird
#      OHNE Modell eingetragen = Standardmodell des Ladens, mit klarem Hinweis)
#   5. workspace-post/AGENTS.md (fast leer, die Regeln schickt sales-post mit)
#   6. Probe: GET /v1/models muss openclaw/post zeigen (bis 30 s)
#
# Der Token erscheint nirgends (nur im Container gelesen, per -e an die Probe).
# Startet NICHTS und startet sales-post nicht: Rollout-Reihenfolge und
# Betreiber-OK stehen im Runbook (Abschnitt Post-Sammelstelle).
set +x
set -euo pipefail
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"
PRAEFIX="${1:-sales}"
if ! [[ $PRAEFIX =~ ^[a-z][a-z0-9-]{0,30}$ ]]; then
  echo "Aufruf: $0 [laden-praefix]  (Kleinbuchstaben, z. B. ivan)" >&2; exit 2
fi
CONTAINER="${PRAEFIX}-claw"
MCP_CONTAINER="${PRAEFIX}-mcp"
if [ "$PRAEFIX" = "sales" ]; then
  ENV_DATEI="$WURZEL/.env"; SCHEMA="sales"
else
  ENV_DATEI="$WURZEL/deploy/laeden/$PRAEFIX.env"; SCHEMA="sales_${PRAEFIX//-/_}"
fi
[ -f "$ENV_DATEI" ] || { echo "FEHLT: $ENV_DATEI" >&2; exit 1; }

# 0) Besitzer: nur diese eine Variable aus der .env lesen.
BESITZER="$(grep -E '^POST_BESITZER=' "$ENV_DATEI" | tail -n 1 | cut -d= -f2- | tr -d '\r[:space:]"' || true)"
if [ -z "$BESITZER" ]; then
  echo "ABBRUCH: POST_BESITZER ist in $(basename "$ENV_DATEI") leer - nichts geaendert." >&2
  echo "         Benutzername des Betreibers eintragen (z. B. POST_BESITZER=anna) und erneut starten." >&2
  exit 1
fi
if ! [[ $BESITZER =~ ^[A-Za-z0-9._@-]{1,64}$ ]]; then
  echo "ABBRUCH: POST_BESITZER hat ein unerwartetes Format - nichts geaendert." >&2; exit 1
fi
for c in "$CONTAINER" "$MCP_CONTAINER"; do
  if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo fehlt)" != "running" ]; then
    echo "ABBRUCH: $c laeuft nicht." >&2; exit 1
  fi
done

# 1) Schluesselpaar fuer versiegelte Postfach-Zugaenge (nur wenn es fehlt).
if ! grep -Eq '^POST_SCHLUESSEL_PRIVAT=.+' "$ENV_DATEI"; then
  echo "1) POST_SCHLUESSEL_PRIVAT fehlt -> deploy/post-schluessel.sh"
  SALES_ENV_DATEI="$ENV_DATEI" bash "$WURZEL/deploy/post-schluessel.sh"
else
  echo "1) Schluesselpaar schon vorhanden"
fi

# 2) Tabellen im Schema dieses Ladens (idempotent, wie db/laden-anlegen.sql).
echo "2) db/post-sammelstelle.sql -> Schema $SCHEMA"
docker exec -i debian-supabase-db-1 psql -q -U supabase_admin -d postgres \
  -v ON_ERROR_STOP=1 -v "schema=$SCHEMA" < "$WURZEL/db/post-sammelstelle.sql" >/dev/null

# 3) Leitung + Env-Konten im sales-mcp-Container (Name per Umgebung, nie in SQL).
echo "3) Leitung fuer $BESITZER, Env-Postfaecher uebernehmen"
docker exec -e "SALES_DB_SCHEMA=$SCHEMA" -e "POST_BESITZER=$BESITZER" "$MCP_CONTAINER" python -c '
import os, sys
sys.path.insert(0, "/app")
import server, post_konten
b = os.environ["POST_BESITZER"]
n = server._q("update benutzer set leitung = true where name = %s returning name", (b,))
if not n:
    print("   FEHLER: Benutzer nicht gefunden - erst deploy/benutzer-anlegen.sh"); sys.exit(4)
print("   leitung = true gesetzt")
print("   Env-Konten neu uebernommen:", post_konten.env_konten_uebernehmen(b))
'

# 4+5) Agent post und Arbeitsordner im Gateway-Container (node ist dort).
echo "4) Agent post + Arbeitsordner in $CONTAINER"
docker exec -i "$CONTAINER" node -e '
  const fs = require("node:fs");
  const { execFileSync } = require("node:child_process");
  const pfad = "/home/node/.openclaw/openclaw.json";
  const c = JSON.parse(fs.readFileSync(pfad, "utf8"));
  const lauf = (args) => execFileSync("openclaw", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const liste = Array.isArray(c?.agents?.list) ? c.agents.list : [{ id: "main" }];
  const ohneModell = { id: "post", workspace: "/home/node/.openclaw/workspace-post", tools: { deny: ["*"] } };
  const mitModell = { ...ohneModell, model: "anthropic/claude-haiku-5-5" };
  const i = liste.findIndex((a) => a && a.id === "post");
  const gleich = (a) => i !== -1 && JSON.stringify(liste[i]) === JSON.stringify(a);
  if (gleich(mitModell)) console.log("   Agent post war schon da (mit Modell claude-haiku-5-5)");
  else if (gleich(ohneModell)) console.log("   Agent post war schon da (OHNE Modell - Standardmodell des Ladens)");
  else {
    const setze = (a) => {
      const neu = liste.slice();
      if (i === -1) neu.push(a); else neu[i] = a;
      lauf(["config", "set", "agents.list", JSON.stringify(neu)]);
    };
    try { setze(mitModell); console.log("   Agent post eingetragen (tools.deny [*], Modell claude-haiku-5-5)"); }
    catch (e) {
      // Aeltere/strengere Schemata lehnen das Feld ab: dann ohne Modell.
      setze(ohneModell);
      console.log("   HINWEIS: agents.list[].model wurde abgelehnt - Agent post OHNE Modell eingetragen;");
      console.log("            es gilt das Standardmodell des Ladens (im Bericht vermerken).");
    }
  }
  fs.mkdirSync("/home/node/.openclaw/workspace-post", { recursive: true });
  fs.writeFileSync("/home/node/.openclaw/workspace-post/AGENTS.md",
    "# sales-post\n\nDu ordnest Mails ein und antwortest ausschliesslich ueber die Funktion, " +
    "die jede Anfrage mitschickt. Die Regeln stehen in der Systemnachricht. Du hast keine Werkzeuge.\n");
  console.log("   workspace-post/AGENTS.md geschrieben");
'

# 6) Probe aus dem Gateway selbst (Token aus dem Volume, nie ausgegeben).
echo "5) Probe (bis 30 s)"
TOKEN="$(docker exec "$CONTAINER" node -e '
  const c = JSON.parse(require("node:fs").readFileSync("/home/node/.openclaw/openclaw.json", "utf8"));
  process.stdout.write(String(c?.gateway?.auth?.token || ""));')"
if ! [[ $TOKEN =~ ^[A-Za-z0-9._-]{16,}$ ]]; then
  echo "ABBRUCH: gateway.auth.token fehlt - erst deploy/auto-anbinden.sh." >&2; exit 1
fi
ERGEBNIS="$(docker exec -e T="$TOKEN" "$CONTAINER" node -e '
  const frage = () => fetch("http://127.0.0.1:18894/v1/models", { headers: { Authorization: "Bearer " + process.env.T } })
    .then(async (r) => { if (r.status !== 200) return "HTTP " + r.status;
      const d = await r.json(); return (d.data || []).map((m) => m.id).join(" "); })
    .catch((e) => "FEHLER " + e.message);
  (async () => {
    let zuletzt = "";
    for (let i = 0; i < 30; i++) {
      zuletzt = await frage();
      if (zuletzt.split(" ").includes("openclaw/post")) break;
      await new Promise((ok) => setTimeout(ok, 1000));
    }
    console.log(zuletzt);
  })();' 2>&1 | sed "s#${TOKEN}#<token>#g")"
unset TOKEN
if printf '%s' "$ERGEBNIS" | grep -w "openclaw/post" >/dev/null; then
  echo "   ok: $ERGEBNIS"
  echo "Fertig. sales-post starten erst mit Betreiber-OK: docker compose up -d sales-post (bzw. mit --env-file)."
else
  echo "   ROT: $ERGEBNIS" >&2
  echo "   Agent noch nicht aktiv - das Gateway braucht vermutlich einen Neustart" >&2
  echo "   (docker restart $CONTAINER, mit dem Betreiber abstimmen), dann dieses Skript erneut." >&2
  exit 3
fi
