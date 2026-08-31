#!/usr/bin/env bash
# deploy/smoke.sh — Abnahme des laufenden Stacks. NUR Lesezugriffe.
# Jede Pruefung entspricht einer am 26.08.2026 gemessenen Diagnose.
# Exit 0 = gesund, sonst Anzahl roter Pruefungen.
#
# Laeuft identisch auf dem PC (Git Bash) und auf der VM: nur Docker-CLI,
# curl und grep. Die UI-Adresse kommt aus UI_TAILSCALE_IP in der .env —
# es wird NUR diese eine Variable extrahiert, nie die Datei angezeigt.
set -uo pipefail

ROT=0
melde() { printf '%-32s %s\n' "$1" "$2"; }
fehl()  { melde "$1" "ROT: $2"; ROT=$((ROT+1)); }
gut()   { melde "$1" "ok"; }

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIND="$(grep -E '^UI_TAILSCALE_IP=' "$WURZEL/.env" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
BIND="${BIND:-127.0.0.1}"

# 1) Container laufen.
for c in sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw openwa; do
  z="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo fehlt)"
  [ "$z" = "running" ] && gut "container $c" || fehl "container $c" "$z"
done

# 2) Oberflaeche antwortet. Gemessen 27.08.2026: auf Docker-Desktop/Windows
# ist die Bindung an die Tailscale-IP vom eigenen Rechner aus NICHT
# erreichbar (Timeout trotz sichtbarem Mapping) — Loopback ist deshalb die
# verlaessliche Innenpruefung auf beiden Plattformen. Ob die Tailscale-
# Adresse von aussen traegt, prueft einmalig ein Geraet im Tailnet.
code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:8791/" || true)"
if [ "$code" = "200" ]; then
  gut "ui http"
elif [ "$code" = "303" ]; then
  # Anmeldung scharf (E1): / leitet Unangemeldete auf /login — gesund ist
  # das nur, wenn die Anmeldeseite selbst antwortet.
  login="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:8791/login" || true)"
  [ "$login" = "200" ] && gut "ui http" || fehl "ui http" "/login HTTP ${login:-000}"
else
  fehl "ui http" "HTTP ${code:-000} an 127.0.0.1"
fi

# 3) Datenbank erreichbar (Produktionsschema, reine Leseabfrage).
if docker exec -e SALES_DB_SCHEMA=sales sales-mcp python -c \
  "import sys;sys.path.insert(0,'/app');import server;server._q('select 1')" \
  >/dev/null 2>&1; then gut "datenbank"; else fehl "datenbank" "select 1 scheitert"; fi

# 4) Gateway kennt den MCP-Server UND hatte juengst keinen Startfehler.
# grep hier NIE mit -q: -q beendet beim ersten Treffer, docker bekommt
# EPIPE, und pipefail macht daraus ein falsches ROT (gemessen 27.08.2026).
if docker exec sales-claw sh -c "openclaw mcp list --json 2>/dev/null" | grep '"sales"' >/dev/null; then
  gut "mcp konfiguriert"
else
  fehl "mcp konfiguriert" "'sales' fehlt in mcp list"
fi
if docker logs --since 10m sales-claw 2>&1 | grep -i "failed to start server" >/dev/null; then
  fehl "mcp verbindung" "Startfehler in den letzten 10 Min."
else
  gut "mcp verbindung"
fi

# 5) OpenWA-Session ist ready (der Weg zum Kunden).
s="$(docker exec sales-dispatch python -c "import os,json,urllib.request as u;q=u.Request(os.environ['OPENWA_URL']+'/api/sessions',headers={'X-Api-Key':os.environ['OPENWA_API_KEY']});print(json.loads(u.urlopen(q,timeout=20).read())[0]['status'])" 2>/dev/null || echo unerreichbar)"
[ "$s" = "ready" ] && gut "openwa session" || fehl "openwa session" "$s"

# 6) OpenClaw-Kanal: keine Abmeldung in den letzten 10 Minuten.
if docker logs --since 10m sales-claw 2>&1 | grep -i "session logged out" >/dev/null; then
  fehl "whatsapp kanal" "Abmeldung in den letzten 10 Min."
else
  gut "whatsapp kanal"
fi

# 7) Der zusammengelegte Cron-Job ist aktiv (cron list zeigt nur aktive Jobs).
if docker exec sales-claw sh -c "openclaw cron list 2>/dev/null" | grep "antworten-pruefen" >/dev/null; then
  gut "cron antworten-pruefen"
else
  fehl "cron antworten-pruefen" "nicht in der aktiven Liste"
fi

# 8+9) Die Bootstrap-Dateien passen in IHRE BEIDEN Grenzen.
#
# Die Falle ist die stille Kuerzung: OpenClaw schneidet zu grosse Dateien
# beim Einspritzen ab und meldet das nur im JSON-Bericht eines Laufs
# (bootstrapTruncation), nicht im Log. Am 22.08.2026 blieben so von 47000
# Zeichen nur 19184 uebrig — abgeschnitten wurde alles ab "Kundenchats",
# DARUNTER "Verbote - ohne Ausnahme". Der Agent kannte seine eigenen
# absoluten Verbote nicht.
#
# Bis 31.08. pruefte diese Stelle NUR AGENTS.md gegen NUR bootstrapMaxChars.
# Zwei Luecken, beide gemessen:
#
#   a) Gebootstrappt wird mehr als AGENTS.md — laut OpenClaw-Doku
#      (concepts/agent-workspace) auch HEARTBEAT.md, BOOT.md, BOOTSTRAP.md,
#      MEMORY.md, skills/ und memory/JJJJ-MM-TT.md. Der Tagesspeicher waechst
#      von selbst; niemand fasst dafuer AGENTS.md an.
#   b) Es gibt ZWEI Grenzen. bootstrapTotalMaxChars galt bisher ungeprueft.
#      Gemessen 31.08.2026 in der Saat: 66164 Zeichen gesamt gegen 150000 —
#      viel Luft, aber sie schrumpft mit jedem Tagesspeicher.
#
# Geprueft wird der LAUFZEIT-Workspace im Container, nicht die Saat: dort
# liegen memory/ und die uebernommenen Skills.
lese="$(docker exec sales-claw sh -c '
  cd /home/node/.openclaw/workspace 2>/dev/null || { echo KEINWS; exit 0; }
  gesamt=0; groesste=0; gname=""
  for f in $(ls -1 AGENTS.md HEARTBEAT.md BOOT.md BOOTSTRAP.md MEMORY.md 2>/dev/null; \
             find skills memory -name "*.md" 2>/dev/null); do
    n=$(wc -c < "$f" | tr -d "[:space:]")
    gesamt=$((gesamt+n))
    if [ "$n" -gt "$groesste" ]; then groesste=$n; gname=$f; fi
  done
  echo "$gesamt $groesste ${gname:-–}"' 2>/dev/null)"

je_max="$(docker exec sales-claw sh -c "openclaw config get agents.defaults.bootstrapMaxChars 2>/dev/null" | grep -oE '[0-9]+' | head -1)"
ges_max="$(docker exec sales-claw sh -c "openclaw config get agents.defaults.bootstrapTotalMaxChars 2>/dev/null" | grep -oE '[0-9]+' | head -1)"
ges="$(echo "$lese" | awk '{print $1}')"
gr="$(echo "$lese"  | awk '{print $2}')"
gname="$(echo "$lese" | awk '{print $3}')"

if [ "$lese" = "KEINWS" ] || [ -z "${ges:-}" ]; then
  fehl "bootstrap je datei" "Workspace im Container nicht lesbar"
  fehl "bootstrap gesamt"   "Workspace im Container nicht lesbar"
else
  # 8) Groesste Einzeldatei gegen bootstrapMaxChars.
  if [ -n "${je_max:-}" ] && [ "$gr" -gt "$je_max" ] 2>/dev/null; then
    fehl "bootstrap je datei" "$gname $gr Zeichen > bootstrapMaxChars $je_max — wird still gekuerzt"
  else
    gut "bootstrap je datei"
  fi
  # 9) Summe aller Bootstrap-Dateien gegen bootstrapTotalMaxChars.
  if [ -n "${ges_max:-}" ] && [ "$ges" -gt "$ges_max" ] 2>/dev/null; then
    fehl "bootstrap gesamt" "$ges Zeichen > bootstrapTotalMaxChars $ges_max — wird still gekuerzt"
  else
    gut "bootstrap gesamt"
  fi
fi

echo "---"
if [ "$ROT" -eq 0 ]; then echo "ALLE PRUEFUNGEN GRUEN"; else echo "$ROT PRUEFUNG(EN) ROT"; fi
exit "$ROT"
