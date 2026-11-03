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
#      model {primary anthropic/claude-haiku-5-5, fallbacks []} - nie ein
#      Rueckfall auf openrouter/free; lehnt `config set` das ab, ABBRUCH)
#   5. workspace-post/AGENTS.md (fast leer, die Regeln schickt sales-post mit)
#   6. Probe: GET /v1/models muss openclaw/post zeigen (bis 30 s)
#
# Der Token erscheint nirgends (nur im Container von der Probe selbst gelesen).
# Startet NICHTS und startet sales-post nicht: Rollout-Reihenfolge und
# Betreiber-OK stehen im Runbook (Abschnitt Post-Sammelstelle).
set +x
set -euo pipefail
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"
PRAEFIX="${1:-sales}"
if ! [[ $PRAEFIX =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "Aufruf: $0 [laden-praefix]  (Kleinbuchstaben, z. B. ivan)" >&2; exit 2
fi
CONTAINER="${PRAEFIX}-claw"
MCP_CONTAINER="${PRAEFIX}-mcp"
if [ "$PRAEFIX" = "sales" ]; then
  ENV_DATEI="$WURZEL/.env"
else
  ENV_DATEI="$WURZEL/deploy/laeden/$PRAEFIX.env"
fi
[ -f "$ENV_DATEI" ] || { echo "FEHLT: $ENV_DATEI" >&2; exit 1; }
# Schema aus der Umgebung des Ladens (wie die Container es bekommen); Basis-Laden: sales.
SCHEMA="$(grep -E '^SALES_DB_SCHEMA=' "$ENV_DATEI" | tail -n 1 | cut -d= -f2- | tr -d '\r[:space:]"' || true)"
SCHEMA="${SCHEMA:-sales}"
if ! [[ $SCHEMA =~ ^sales(_[a-z][a-z0-9_]{0,30})?$ ]]; then
  echo "ABBRUCH: SALES_DB_SCHEMA='$SCHEMA' passt nicht zum Schema-Muster - nichts geaendert." >&2; exit 1
fi

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
NEUES_PAAR=0
if ! grep -Eq '^POST_SCHLUESSEL_PRIVAT=.+' "$ENV_DATEI"; then
  echo "1) POST_SCHLUESSEL_PRIVAT fehlt -> deploy/post-schluessel.sh"
  SALES_ENV_DATEI="$ENV_DATEI" bash "$WURZEL/deploy/post-schluessel.sh"
  NEUES_PAAR=1
else
  echo "1) Schluesselpaar schon vorhanden"
fi

# 2) Tabellen im Schema dieses Ladens (idempotent, wie db/laden-anlegen.sql).
echo "2) db/post-sammelstelle.sql -> Schema $SCHEMA"
docker exec -i debian-supabase-db-1 psql -q -U supabase_admin -d postgres \
  -v ON_ERROR_STOP=1 -v "schema=$SCHEMA" < "$WURZEL/db/post-sammelstelle.sql" >/dev/null

# 3) Leitung + Env-Konten im sales-mcp-Container (Name per Umgebung, nie in SQL).
echo "3) Leitung fuer $BESITZER, Env-Postfaecher uebernehmen"
docker exec -e "POST_BESITZER=$BESITZER" "$MCP_CONTAINER" python -c '
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
docker exec "$CONTAINER" node -e '
  const fs = require("node:fs");
  const { execFileSync } = require("node:child_process");
  const pfad = "/home/node/.openclaw/openclaw.json";
  const c = JSON.parse(fs.readFileSync(pfad, "utf8"));
  const lauf = (args) => execFileSync("openclaw", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const liste = Array.isArray(c?.agents?.list) ? c.agents.list : [{ id: "main" }];
  // Eigenes Modell OHNE fallbacks: die Vorgabe des Ladens faellt auf
  // openrouter/free zurueck - Mailinhalte duerfen nie an ein kostenloses
  // Fremdmodell gehen. Gemessen (OpenClaw 2026.7.1,
  // resolveSelectedModelFallbacksOverride): fallbacks [] am Agenten ersetzt
  // die Vorgabe, es gibt dann keinen Rueckfall.
  const soll = { id: "post", workspace: "/home/node/.openclaw/workspace-post", tools: { deny: ["*"] },
                 model: { primary: "anthropic/claude-haiku-5-5", fallbacks: [] } };
  const i = liste.findIndex((a) => a && a.id === "post");
  // Vergleich unabhaengig von der Schluesselreihenfolge (sonst unnoetiges config set).
  const norm = (v) => Array.isArray(v) ? v.map(norm) : (v && typeof v === "object")
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])])) : v;
  if (i !== -1 && JSON.stringify(norm(liste[i])) === JSON.stringify(norm(soll))) {
    console.log("   Agent post war schon da (Modell claude-haiku-5-5, ohne Rueckfall)");
  } else {
    // Auch ein vorhandener Eintrag ohne eigenes Modell (alter Stand) wird hochgezogen.
    const neu = liste.slice();
    if (i === -1) neu.push(soll); else neu[i] = soll;
    try {
      lauf(["config", "set", "agents.list", JSON.stringify(neu)]);
    } catch (e) {
      // KEIN Rueckfall ohne Modell: dann liefe post auf der Vorgabe des Ladens
      // samt fallbacks [openrouter/free]. Lieber gar nicht anbinden.
      const text = String(e && e.stderr || "") + " " + String(e && e.message || "");
      console.error("   ABBRUCH: das Gateway hat den Agenten post mit eigenem Modell abgelehnt");
      console.error("   (agents.list[].model = {primary: anthropic/claude-haiku-5-5, fallbacks: []}).");
      console.error("   Ohne dieses Feld liefe die Einordnung auf dem Standardmodell MIT Rueckfall auf");
      console.error("   ein Fremdmodell - darum nichts eingetragen. Meldung: " +
        text.replace(/\s+/g, " ").slice(0, 300));
      process.exit(5);
    }
    console.log("   Agent post eingetragen (tools.deny [*], Modell claude-haiku-5-5, fallbacks [])");
  }
  fs.mkdirSync("/home/node/.openclaw/workspace-post", { recursive: true });
  fs.writeFileSync("/home/node/.openclaw/workspace-post/AGENTS.md",
    "# sales-post\n\nDu ordnest Mails ein und antwortest ausschliesslich ueber die Funktion, " +
    "die jede Anfrage mitschickt. Die Regeln stehen in der Systemnachricht. Du hast keine Werkzeuge.\n");
  console.log("   workspace-post/AGENTS.md geschrieben");
'

# 6) Probe aus dem Gateway selbst.
echo "5) Probe (bis 30 s)"
# Der Token wird im selben node-Prozess gelesen, der die Probe fragt: er
# verlaesst den Container nie und steht in keiner docker-Kommandozeile.
ERGEBNIS="$(docker exec "$CONTAINER" node -e '
  const T = String(JSON.parse(require("node:fs").readFileSync("/home/node/.openclaw/openclaw.json", "utf8"))?.gateway?.auth?.token || "");
  if (!T) { console.log("FEHLER Zugangsschluessel fehlt"); process.exit(0); }
  const frage = () => fetch("http://127.0.0.1:18894/v1/models", { headers: { Authorization: "Bearer " + T } })
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
  })();' 2>&1)"
if printf '%s' "$ERGEBNIS" | grep -w "openclaw/post" >/dev/null; then
  echo "   ok: $ERGEBNIS"
  if [ "$NEUES_PAAR" = 1 ]; then
    echo "WICHTIG: neues Schluesselpaar - sales-ui bekommt den oeffentlichen Schluessel erst beim Neuerzeugen:"
    if [ "$PRAEFIX" = "sales" ]; then
      echo "  docker compose up -d --no-deps --force-recreate sales-ui"
    else
      echo "  docker compose --env-file deploy/laeden/$PRAEFIX.env up -d --no-deps --force-recreate sales-ui"
    fi
  fi
  echo "Fertig. sales-post starten erst mit Betreiber-OK: docker compose up -d sales-post (bzw. mit --env-file)."
else
  echo "   ROT: $ERGEBNIS" >&2
  echo "   Agent noch nicht aktiv - das Gateway braucht vermutlich einen Neustart" >&2
  echo "   (docker restart $CONTAINER, mit dem Betreiber abstimmen), dann dieses Skript erneut." >&2
  exit 3
fi
