#!/usr/bin/env bash
# deploy/auto-anbinden.sh — bereitet das OpenClaw-Gateway EINES Ladens fuer
# sales-auto vor (29.10.2026). Wiederholbar.
#
#   bash deploy/auto-anbinden.sh            # Basis-Laden (sales-claw, .env)
#   bash deploy/auto-anbinden.sh ivan       # Laden ivan (ivan-claw, deploy/laeden/ivan.env)
#
# Was es tut (alles im Laufzeit-Volume des Gateways, die Saat bleibt Saat):
#   1. gateway.http.endpoints.chatCompletions.enabled = true
#   2. Agent `auto` in agents.list: eigener Arbeitsordner, tools.deny ["*"]
#      (gemessen: KEIN Werkzeug, auch nicht exec/message; die von sales-auto
#      mitgeschickte Funktion antwort_abgeben bleibt)
#   3. workspace-auto/AGENTS.md: fast leer - die Regeln schickt sales-auto mit
#   4. OPENCLAW_GATEWAY_TOKEN in die .env des Ladens (Modus 600, Sicherung)
#   5. Probe: GET /v1/models muss openclaw/auto zeigen
#
# DER TOKEN ERSCHEINT NIRGENDS: er liegt im Volume (gateway.auth.token, von
# deploy/gateway-saat.sh erzeugt), wird im Container gelesen und landet ueber
# eine Shell-Variable direkt in der .env - nie in einer Ausgabe, nie als
# Argument. Er ist laut OpenClaw-Doku Operator-Zugriff auf das Gateway; nur
# der Dienst sales-auto bekommt ihn (docker-compose.yml).
#
# Startet NICHTS neu und startet sales-auto nicht: braucht das Gateway fuer
# den Endpunkt einen Neustart, sagt die Probe es - das stimmt der Betreiber
# ab (der Container ist die Gegenstelle des WhatsApp-Selbst-Chats).
set +x
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"
PRAEFIX="${1:-sales}"
if ! [[ $PRAEFIX =~ ^[a-z][a-z0-9-]{0,30}$ ]]; then
  echo "Aufruf: $0 [laden-praefix]  (Kleinbuchstaben, z. B. ivan)" >&2; exit 2
fi
CONTAINER="${PRAEFIX}-claw"
if [ "$PRAEFIX" = "sales" ]; then ENV_DATEI="$WURZEL/.env"; else ENV_DATEI="$WURZEL/deploy/laeden/$PRAEFIX.env"; fi
[ -f "$ENV_DATEI" ] || { echo "FEHLT: $ENV_DATEI" >&2; exit 1; }
if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo fehlt)" != "running" ]; then
  echo "ABBRUCH: $CONTAINER laeuft nicht." >&2; exit 1
fi

# 1-3) Konfiguration und Arbeitsordner im Container (node ist dort).
echo "1) Endpunkt + Agent auto + Arbeitsordner in $CONTAINER"
docker exec -i "$CONTAINER" node -e '
  const fs = require("node:fs");
  const { execFileSync } = require("node:child_process");
  const pfad = "/home/node/.openclaw/openclaw.json";
  const c = JSON.parse(fs.readFileSync(pfad, "utf8"));
  const lauf = (args) => execFileSync("openclaw", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (c?.gateway?.http?.endpoints?.chatCompletions?.enabled !== true) {
    lauf(["config", "set", "gateway.http.endpoints.chatCompletions.enabled", "true"]);
    console.log("   Endpunkt /v1/chat/completions eingeschaltet");
  } else console.log("   Endpunkt war schon an");
  const liste = Array.isArray(c?.agents?.list) ? c.agents.list : [{ id: "main" }];
  const auto = { id: "auto", workspace: "/home/node/.openclaw/workspace-auto", tools: { deny: ["*"] } };
  const i = liste.findIndex((a) => a && a.id === "auto");
  if (i === -1 || JSON.stringify(liste[i]) !== JSON.stringify(auto)) {
    if (i === -1) liste.push(auto); else liste[i] = auto;
    lauf(["config", "set", "agents.list", JSON.stringify(liste)]);
    console.log("   Agent auto eingetragen (tools.deny [*])");
  } else console.log("   Agent auto war schon da");
  fs.mkdirSync("/home/node/.openclaw/workspace-auto", { recursive: true });
  fs.writeFileSync("/home/node/.openclaw/workspace-auto/AGENTS.md",
    "# sales-auto\n\nDu antwortest ausschliesslich ueber die Funktion antwort_abgeben. " +
    "Die Regeln stehen in der Systemnachricht jeder Anfrage. Du hast keine Werkzeuge.\n");
  console.log("   workspace-auto/AGENTS.md geschrieben");
'

# 4) Token aus dem Volume in die .env des Ladens (nie ausgeben).
echo "2) OPENCLAW_GATEWAY_TOKEN -> $(basename "$ENV_DATEI")"
TOKEN="$(docker exec "$CONTAINER" node -e '
  const c = JSON.parse(require("node:fs").readFileSync("/home/node/.openclaw/openclaw.json", "utf8"));
  process.stdout.write(String(c?.gateway?.auth?.token || ""));')"
if ! [[ $TOKEN =~ ^[A-Za-z0-9._-]{16,}$ ]]; then
  echo "ABBRUCH: gateway.auth.token fehlt oder hat ein unerwartetes Format - nichts geaendert." >&2; exit 1
fi
umask 077
SICHERUNG="$ENV_DATEI.vor-auto-$(date +%Y%m%d-%H%M%S)"
cp "$ENV_DATEI" "$SICHERUNG"; chmod 600 "$SICHERUNG"
NEU="$(mktemp "$(dirname "$ENV_DATEI")/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev '^OPENCLAW_GATEWAY_TOKEN=' "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then printf '\n' >> "$NEU"; fi
printf 'OPENCLAW_GATEWAY_TOKEN=%s\n' "$TOKEN" >> "$NEU"
chmod 600 "$NEU"; mv -f "$NEU" "$ENV_DATEI"; trap - EXIT
echo "   eingetragen (Sicherung: $(basename "$SICHERUNG"))"

# 5) Probe aus dem Gateway selbst: listet /v1/models den Agenten auto?
echo "3) Probe"
ERGEBNIS="$(docker exec -e T="$TOKEN" "$CONTAINER" node -e '
  fetch("http://127.0.0.1:18894/v1/models", { headers: { Authorization: "Bearer " + process.env.T } })
    .then(async (r) => { if (r.status !== 200) { console.log("HTTP " + r.status); return; }
      const d = await r.json(); console.log((d.data || []).map((m) => m.id).join(" ")); })
    .catch((e) => console.log("FEHLER " + e.message));' 2>&1 | sed "s#${TOKEN}#<token>#g")"
unset TOKEN
if printf '%s' "$ERGEBNIS" | grep -w "openclaw/auto" >/dev/null; then
  echo "   ok: $ERGEBNIS"
  echo "Fertig. sales-auto starten erst mit Betreiber-OK: docker compose up -d sales-auto (bzw. mit --env-file)."
else
  echo "   ROT: $ERGEBNIS" >&2
  echo "   Endpunkt noch nicht aktiv - das Gateway braucht vermutlich einen Neustart" >&2
  echo "   (docker restart $CONTAINER, mit dem Betreiber abstimmen), dann dieses Skript erneut." >&2
  exit 3
fi
