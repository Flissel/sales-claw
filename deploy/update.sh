#!/usr/bin/env bash
# deploy/update.sh — spielt den Stand von origin/<aktueller Zweig> ein.
# Gestaffelt nach gemessenen Regeln, mit Rueckfahrkarte. Gedacht fuer den
# Laufzeit-Checkout auf der VM; auf dem PC bricht es absichtlich ab, sobald
# nachgefuehrte Dateien veraendert sind.
#
# Config-Grenze (docs/04_BETRIEB_MINIPC.md):
#   Git besitzt Code, Compose, config/workspace (Saat).
#   Das Volume besitzt openclaw.json (Allowlist, Kanaele, Cron) und die
#   WhatsApp-Kopplung — Aenderungen an config/openclaw* werden deshalb NUR
#   GEMELDET, nie automatisch angewendet.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BETRIEB="${SALES_BETRIEB:-$HOME/sales-betrieb}"
STATUS="$BETRIEB/update-status.json"
# NIEMALS nacktes `docker compose up -d`: es wuerde sales-auto starten
# (zweiter Antwortpfad neben dem Cron-Job). Dienste immer namentlich.
KERN_ALLE="sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw"

# GEMESSEN 30.08.2026, Aufgabe 12: ein Update auf der frisch aufgesetzten
# VM lief in den Rueckbau — und der startete mit der vollen Kernliste die
# Dienste MIT NEBENWIRKUNGEN (dispatch, inbox, mail, claw), obwohl dort
# bewusst nur mcp und ui liefen und der Kundenverkehr noch am alten
# Standort hing. Kein Schaden entstanden (nachgeprueft: kein failed-
# Entwurf, kein Versand), aber es war genau die Lage, die die
# Cutover-Regel „nie zwei Standorte gleichzeitig" verbietet.
#
# Ein Update darf deshalb nur anfassen, was VORHER lief. Was absichtlich
# stand, bleibt stehen — auch im Rueckbau.
laufende_kerndienste() {
  local laufend=""
  for dienst in $KERN_ALLE; do
    if [ "$(docker inspect -f '{{.State.Status}}' "$dienst" 2>/dev/null)" = "running" ]; then
      laufend="$laufend $dienst"
    fi
  done
  printf '%s' "${laufend# }"
}

KERN="$(laufende_kerndienste)"
if [ -z "$KERN" ]; then
  echo "ABBRUCH: kein Kerndienst laeuft — hier ist nichts zu aktualisieren." >&2
  exit 1
fi

mkdir -p "$BETRIEB"
cd "$WURZEL"

status_schreiben() { # ergebnis von auf hinweis
  printf '{"zeitpunkt":"%s","ergebnis":"%s","von":"%s","auf":"%s","hinweis":"%s"}\n' \
    "$(date -Is)" "$1" "$2" "$3" "$4" > "$STATUS"
}

# Unversionierte Dateien (.env, media/, auftraege/) gehoeren zum Betrieb und
# stoeren einen ff-Merge nicht — geprueft werden nur nachgefuehrte Dateien.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  status_schreiben fehler "-" "-" "nachgefuehrte Dateien veraendert - auf der VM wird nicht editiert"
  echo "ABBRUCH: Aenderungen an nachgefuehrten Dateien (git status)." >&2
  exit 1
fi

ZWEIG="$(git rev-parse --abbrev-ref HEAD)"
ALT="$(git rev-parse HEAD)"
git fetch origin "$ZWEIG" --quiet
NEU="$(git rev-parse "origin/$ZWEIG")"

if [ "$ALT" = "$NEU" ]; then
  status_schreiben aktuell "$ALT" "$NEU" "keine Aenderung"
  echo "Bereits aktuell: $ALT"
  exit 0
fi

git tag -f vor-update "$ALT" >/dev/null
git merge --ff-only "origin/$ZWEIG"
GEAENDERT="$(git diff --name-only "$ALT" "$NEU")"
echo "Eingespielt $ALT -> $NEU. Geaendert:"
echo "$GEAENDERT" | sed 's/^/  /'

BAUEN=""; OPENWA_BAUEN=false; GATEWAY_NEU=false; HINWEIS=""

if echo "$GEAENDERT" | grep -E '^sales-mcp/' >/dev/null; then
  BAUEN="$KERN"
  GATEWAY_NEU=true  # Gemessene Falle (26.08.2026): ein sales-mcp-Neustart
                    # trennt die MCP-Verbindung des Gateways stillschweigend.
fi
if echo "$GEAENDERT" | grep -E '^docker-compose' >/dev/null; then
  BAUEN="$KERN"; OPENWA_BAUEN=true
fi
if echo "$GEAENDERT" | grep -E '^openwa/upstream/' >/dev/null; then
  OPENWA_BAUEN=true
fi
if echo "$GEAENDERT" | grep -E '^config/workspace/' >/dev/null; then
  GATEWAY_NEU=true
fi
if echo "$GEAENDERT" | grep -E '^config/openclaw' >/dev/null; then
  HINWEIS="config/openclaw geaendert: wirkt nur auf frische Volumes; laufende Instanz manuell mit openclaw config set nachziehen"
  echo "HINWEIS: $HINWEIS"
fi

gateway_neustarten() {
  # Nur anfassen, was laeuft — KERN enthaelt sales-claw nur dann.
  case " $KERN " in
    *" sales-claw "*) docker restart sales-claw >/dev/null ;;
  esac
}

rueckbau() {
  echo "Abnahme rot — Rueckbau auf $ALT." >&2
  git reset --hard "$ALT" >/dev/null
  docker compose up -d --build $KERN
  gateway_neustarten
  sleep 30
  if bash "$WURZEL/deploy/smoke.sh"; then
    status_schreiben rollback "$ALT" "$NEU" "Update fehlerhaft; alter Stand laeuft wieder"
    echo "Rueckbau erfolgreich — alter Stand laeuft, Abnahme gruen."
  else
    status_schreiben notfall "$ALT" "$NEU" "Rollback-Abnahme ebenfalls rot - Mensch noetig"
    echo "NOTFALL: auch der Rueckbau meldet rot. Mensch noetig." >&2
  fi
  exit 1
}

if [ -n "$BAUEN" ]; then
  docker compose up -d --build $BAUEN
fi
if $OPENWA_BAUEN; then
  docker compose -f docker-compose.openwa.yml up -d --build openwa
fi
if echo "$GEAENDERT" | grep -E '^config/workspace/' >/dev/null; then
  # Saat einspielen: Git ist Quelle der Wahrheit fuer den Workspace.
  # Auch in einen gestoppten Container kopierbar; existiert er gar nicht
  # (Aufbauphase), ist das kein Grund, das ganze Update abzubrechen.
  docker cp "$WURZEL/config/workspace/." \
    sales-claw:/home/node/.openclaw/workspace/ 2>/dev/null || \
    echo "HINWEIS: Workspace-Saat nicht eingespielt — sales-claw fehlt noch."
fi
if $GATEWAY_NEU; then
  gateway_neustarten
  sleep 30   # Gateway, Kanal und MCP brauchen einen Moment (gemessen 5-20s).
fi

# Die Abnahme prueft den VOLLEN Stack — auf einem absichtlich unvollstaendigen
# (Aufbauphase vor dem Cutover: nur mcp und ui) ist sie zwangslaeufig rot, und
# ein Rueckbau waere dort sinnlos: die Roete kommt nicht vom Update. Gemessen
# am 30.08.2026, als genau das passierte.
if [ "$KERN" = "$KERN_ALLE" ]; then
  bash "$WURZEL/deploy/smoke.sh" || rueckbau
  status_schreiben eingespielt "$ALT" "$NEU" "${HINWEIS:-glatt durchgelaufen}"
  echo "Update eingespielt und Abnahme gruen."
else
  echo "Abnahme UEBERSPRUNGEN: unvollstaendiger Stack (Aufbauphase). Es "
  echo "laeuft: $KERN. Der neue Stand bleibt eingespielt; die volle Abnahme"
  echo "gilt erst nach dem Cutover."
  status_schreiben eingespielt "$ALT" "$NEU" \
    "${HINWEIS:+$HINWEIS; }Abnahme uebersprungen - unvollstaendiger Stack"
fi
