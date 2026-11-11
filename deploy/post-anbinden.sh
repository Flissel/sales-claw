#!/usr/bin/env bash
# deploy/post-anbinden.sh — bindet die Post-Sammelstelle (sales-post) an das
# OpenClaw-Gateway EINES Ladens an (Stufe 1, 03.11.2026; Pruefer-Agent v2,
# 04.11.2026). Wiederholbar.
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
#   4. Agenten `post` UND `post-pruefer` in agents.list (je tools.deny ["*"],
#      eigener Arbeitsordner, eigenes Modell ohne Rueckfall: post
#      anthropic/claude-haiku-5-5, post-pruefer anthropic/claude-sonnet-5-5,
#      beide fallbacks [] - nie ein Rueckfall auf openrouter/free). Beide gehen
#      in EINEM config set hinein; lehnt das Gateway das ab, ABBRUCH ohne
#      einen von beiden (ein unbekannter Agent bekaeme ALLE Werkzeuge)
#   5. workspace-post/AGENTS.md und workspace-post-pruefer/AGENTS.md (fast
#      leer, die Regeln schickt sales-post mit)
#   6. Probe: GET /v1/models muss openclaw/post UND openclaw/post-pruefer
#      zeigen (bis 30 s)
#   7. Funktionsprobe: EIN echter Aufruf an openclaw/post-pruefer mit festem
#      Dummy-Text (keine Mail). /v1/models zeigt nur den Eintrag; ob das
#      Gateway das Modell claude-sonnet-5-5 wirklich annimmt, zeigt erst der
#      Aufruf (Ruling 2). Ausgabe nur "ok" oder der Fehlertyp; sonst Code 6.
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
echo "4) Agenten post + post-pruefer + Arbeitsordner in $CONTAINER"
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
  // Der Pruefer bekommt ein eigenes, staerkeres Modell (Ruling 2), aus demselben
  // Grund ohne fallbacks und ohne Werkzeuge. Ob das Live-Gateway claude-sonnet-5-5
  // annimmt, zeigt erst dieser Lauf - dann Abbruch, nicht Eintrag ohne Modell.
  const soll = [
    { id: "post", workspace: "/home/node/.openclaw/workspace-post", tools: { deny: ["*"] },
      model: { primary: "anthropic/claude-haiku-5-5", fallbacks: [] } },
    { id: "post-pruefer", workspace: "/home/node/.openclaw/workspace-post-pruefer", tools: { deny: ["*"] },
      model: { primary: "anthropic/claude-sonnet-5-5", fallbacks: [] } },
  ];
  // Vergleich unabhaengig von der Schluesselreihenfolge (sonst unnoetiges config set).
  const norm = (v) => Array.isArray(v) ? v.map(norm) : (v && typeof v === "object")
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])])) : v;
  const neu = liste.slice();
  let geaendert = false;
  for (const s of soll) {
    const i = neu.findIndex((a) => a && a.id === s.id);
    if (i !== -1 && JSON.stringify(norm(neu[i])) === JSON.stringify(norm(s))) {
      console.log("   Agent " + s.id + " war schon da (Modell " + s.model.primary.split("/")[1] + ", ohne Rueckfall)");
    } else {
      // Auch ein vorhandener Eintrag ohne eigenes Modell (alter Stand) wird hochgezogen.
      if (i === -1) neu.push(s); else neu[i] = s;
      geaendert = true;
    }
  }
  if (geaendert) {
    // EIN config set fuer beide: scheitert es, ist keiner von beiden eingetragen.
    try {
      lauf(["config", "set", "agents.list", JSON.stringify(neu)]);
    } catch (e) {
      // KEIN Rueckfall ohne Modell: dann liefe der Agent auf der Vorgabe des Ladens
      // samt fallbacks [openrouter/free]. Lieber gar nicht anbinden.
      const text = String(e && e.stderr || "") + " " + String(e && e.message || "");
      console.error("   ABBRUCH: das Gateway hat die Agenten post/post-pruefer mit eigenem Modell abgelehnt");
      console.error("   (agents.list[].model = {primary: anthropic/claude-haiku-5-5 bzw. claude-sonnet-5-5, fallbacks: []}).");
      console.error("   Ohne dieses Feld liefe die Einordnung auf dem Standardmodell MIT Rueckfall auf");
      console.error("   ein Fremdmodell - darum nichts eingetragen. Meldung: " +
        text.replace(/\s+/g, " ").slice(0, 300));
      process.exit(5);
    }
    console.log("   Agenten post und post-pruefer eingetragen (tools.deny [*], eigenes Modell, fallbacks [])");
  }
  const regeln = "\n\nDu ordnest Mails ein und antwortest ausschliesslich ueber die Funktion, " +
    "die jede Anfrage mitschickt. Die Regeln stehen in der Systemnachricht. Du hast keine Werkzeuge.\n";
  for (const [ordner, name] of [["workspace-post", "sales-post"], ["workspace-post-pruefer", "sales-post-pruefer"]]) {
    fs.mkdirSync("/home/node/.openclaw/" + ordner, { recursive: true });
    fs.writeFileSync("/home/node/.openclaw/" + ordner + "/AGENTS.md", "# " + name + regeln);
    console.log("   " + ordner + "/AGENTS.md geschrieben");
  }
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
      const da = zuletzt.split(" ");
      if (da.includes("openclaw/post") && da.includes("openclaw/post-pruefer")) break;
      await new Promise((ok) => setTimeout(ok, 1000));
    }
    console.log(zuletzt);
  })();' 2>&1)"
# Wortgenau: `grep -w openclaw/post` traefe auch openclaw/post-pruefer (Bindestrich = Wortgrenze).
FEHLEN=""
for m in openclaw/post openclaw/post-pruefer; do
  printf '%s' "$ERGEBNIS" | tr ' ' '\n' | grep -Fx "$m" >/dev/null || FEHLEN="$FEHLEN $m"
done
if [ -n "$FEHLEN" ]; then
  echo "   ROT: $ERGEBNIS" >&2
  echo "   Agent(en) noch nicht aktiv (fehlt:${FEHLEN}) - das Gateway braucht vermutlich einen Neustart" >&2
  echo "   (docker restart $CONTAINER, mit dem Betreiber abstimmen), dann dieses Skript erneut." >&2
  exit 3
fi
echo "   ok: $ERGEBNIS"

# 7) Funktionsprobe: ein echter Aufruf an post-pruefer, wie sales-post ihn macht
# (Sitzungsschluessel agent:post-pruefer:..., fest gepinnte Funktion). Fester
# Dummy-Text, keine Mail - die Sitzungsdatei raeumt post-sitzungen-aufraeumen.sh
# weg. Token wie oben nur im Container; heraus kommt nur "ok" oder ein Fehlertyp
# (HTTP-Status bzw. Name der JS-Ausnahme), nie die Antwort des Gateways.
echo "6) Funktionsprobe openclaw/post-pruefer (Dummy-Text, keine Mail, bis 120 s)"
PROBE="$(docker exec "$CONTAINER" node -e '
  const T = String(JSON.parse(require("node:fs").readFileSync("/home/node/.openclaw/openclaw.json", "utf8"))?.gateway?.auth?.token || "");
  if (!T) { console.log("FEHLER Zugangsschluessel fehlt"); process.exit(0); }
  const name = "probe_abgeben";
  fetch("http://127.0.0.1:18894/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + T,
               "x-openclaw-session-key": "agent:post-pruefer:probe:" + Date.now(),
               "x-openclaw-agent-id": "post-pruefer" },
    body: JSON.stringify({
      model: "openclaw/post-pruefer",
      messages: [{ role: "system", content: "Funktionstest der Anbindung. Rufe die Funktion auf." },
                 { role: "user", content: "Probe: gib ok=true ab. Dies ist ein Testtext, keine Mail." }],
      tools: [{ type: "function", function: { name, description: "Gibt das Ergebnis der Probe ab.",
        parameters: { type: "object", additionalProperties: false, required: ["ok"],
                      properties: { ok: { type: "boolean" } } } } }],
      tool_choice: { type: "function", function: { name } } }),
    signal: AbortSignal.timeout(120000) })
    .then(async (r) => {
      if (r.status !== 200) return "FEHLER HTTP " + r.status;
      const f = (await r.json())?.choices?.[0]?.message?.tool_calls?.[0]?.function;
      return f && f.name === name ? "ok" : "FEHLER ohne Funktionsaufruf";
    })
    .catch((e) => "FEHLER " + String((e && e.name) || "unbekannt"))
    .then((s) => console.log(s));' 2>/dev/null || true)"
# Nur harmlose Zeichen, gekappt: die Zeile besteht ohnehin nur aus Status/Typname.
PROBE="$(printf '%s' "$PROBE" | tr -cd 'A-Za-z0-9 ._-' | cut -c1-80)"
if [ "$PROBE" != "ok" ]; then
  echo "   ROT: Funktionsprobe post-pruefer: ${PROBE:-FEHLER keine Ausgabe}" >&2
  echo "   Der Agent ist eingetragen, antwortet aber nicht mit Funktionsaufruf - vermutlich nimmt das" >&2
  echo "   Gateway das Modell anthropic/claude-sonnet-5-5 nicht an (Ruling 2: dann claude-sonnet-5)." >&2
  echo "   Nicht weiter ausrollen: sonst scheitert jede Pruefung einer Mail." >&2
  exit 6
fi
echo "   ok: openclaw/post-pruefer antwortet mit Funktionsaufruf"

if [ "$NEUES_PAAR" = 1 ]; then
  echo "WICHTIG: neues Schluesselpaar - sales-ui bekommt den oeffentlichen Schluessel erst beim Neuerzeugen:"
  if [ "$PRAEFIX" = "sales" ]; then
    # Basis-Laden: ueber das Skript, sonst verliert sales-ui das Netz bewerbung-fenster (Portal-Fenster).
    echo "  bash deploy/sales-ui-neu.sh"
  else
    echo "  docker compose --env-file deploy/laeden/$PRAEFIX.env up -d --no-deps --force-recreate sales-ui"
  fi
fi
echo "Fertig. sales-post starten erst mit Betreiber-OK: docker compose up -d sales-post (bzw. mit --env-file)."
