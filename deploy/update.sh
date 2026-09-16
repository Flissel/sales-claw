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
#
# telegram/linkedin/stt fehlten hier bis zum 16.09.2026 — ein Update hat
# sie stillschweigend uebersprungen, obwohl sie seit dem 12.09.2026 laufen.
KERN_ALLE="sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw sales-telegram sales-linkedin sales-stt"

# Praefix und --env-file-Argument je Laden, PARALLELE Arrays (Index i
# gehoert zusammen). Der bestehende Laden ("sales", Vorgabewerte aus den
# Compose-Dateien) hat keine Umgebungsdatei — die leere Zeichenkette steht
# fuer ihn, Index 0 ist deshalb immer "sales". Ohne --env-file loest
# LADEN_PRAEFIX/LADEN_PROJEKT auf ihre Defaults ("sales"/"sales-claw") auf,
# also GENAU den bisherigen Stand.
LADEN_PRAEFIXE=("sales")
LADEN_ENVARGS=("")
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  LADEN_PRAEFIXE+=("$(sed -n 's/^LADEN_PRAEFIX=//p' "$e")")
  LADEN_ENVARGS+=("--env-file $e")
done

# Bildet einen Dienstschluessel (z. B. sales-mcp, aus KERN_ALLE) auf den
# tatsaechlichen Containernamen eines Ladens ab: <praefix>-<rest>, wobei
# <rest> der Dienstschluessel ohne sein fuehrendes "sales-" ist. Fuer den
# Basis-Laden (Praefix "sales") kommt dabei exakt der bisherige Name
# heraus (sales-mcp -> sales-mcp) — das Verhalten des bestehenden Ladens
# aendert sich nicht.
#
# KORREKTURRUNDE 1 (16.09.2026): laufende_kerndienste() fragte vorher
# direkt "docker inspect $dienst" ab, also den DIENSTSCHLUESSEL statt des
# Containernamens. Das ging fuer den Basis-Laden nur zufaellig gut, weil
# dessen Container genauso heissen. Fuer jeden weiteren Laden (Container
# "ivan-mcp" statt "sales-mcp") lieferte das immer "nicht gefunden" — der
# so ermittelte EINE $KERN-Wert (aus dem Basis-Laden) wurde danach fuer
# ALLE Laeden wiederverwendet und haette bei einem Laden mit absichtlich
# nur zwei laufenden Diensten (z. B. frisch angelegt, wartet auf
# Zugangsdaten) alle neun erzwungen — genau das, was der Kommentar unten
# ("Ein Update darf nur anfassen, was VORHER lief") verhindern soll.
containername() { # dienst praefix
  printf '%s-%s' "$2" "${1#sales-}"
}

# GEMESSEN 30.08.2026, Aufgabe 12: ein Update auf der frisch aufgesetzten
# VM lief in den Rueckbau — und der startete mit der vollen Kernliste die
# Dienste MIT NEBENWIRKUNGEN (dispatch, inbox, mail, claw), obwohl dort
# bewusst nur mcp und ui liefen und der Kundenverkehr noch am alten
# Standort hing. Kein Schaden entstanden (nachgeprueft: kein failed-
# Entwurf, kein Versand), aber es war genau die Lage, die die
# Cutover-Regel „nie zwei Standorte gleichzeitig" verbietet.
#
# Ein Update darf deshalb nur anfassen, was VORHER lief. Was absichtlich
# stand, bleibt stehen — auch im Rueckbau. Seit 16.09.2026 gilt das PRO
# LADEN: ein Laden mit Umgebungsdatei, in dem gerade gar nichts laeuft
# (z. B. frisch angelegt, wartet auf Zugangsdaten), ist dabei KEIN Fehler
# — fuer ihn gibt es dann schlicht nichts anzufassen, ein Update darf ihn
# nicht von sich aus hochziehen.
laufende_kerndienste() { # praefix
  local praefix="$1" laufend="" dienst c
  for dienst in $KERN_ALLE; do
    c="$(containername "$dienst" "$praefix")"
    if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" = "running" ]; then
      laufend="$laufend $dienst"
    fi
  done
  printf '%s' "${laufend# }"
}

# Schnappschuss VOR jeder Aenderung, je Laden einzeln (nicht ein einziger
# Wert fuer alle) — Grundlage sowohl fuer den Build- als auch fuer den
# Rueckbau-Pfad. Bewusst ALS SCHNAPPSCHUSS und nicht live bei jedem
# Zugriff neu abgefragt: ein Rueckbau soll den Zustand VOR dem
# Update-Versuch wiederherstellen, nicht einen moeglicherweise durch den
# fehlgeschlagenen Build schon angeschlagenen Zwischenzustand (ein Dienst
# koennte nach einem missglueckten Rebuild kurzzeitig "exited" statt
# "running" sein, obwohl er restauriert werden soll) — dieselbe Logik wie
# im bisherigen Skript, das $KERN ebenfalls einmal ermittelte und fuer
# Update UND Rueckbau gleichermassen nutzte, jetzt korrekt PRO LADEN statt
# einmal global.
LADEN_KERN=()
ETWAS_LAEUFT=false
for i in "${!LADEN_PRAEFIXE[@]}"; do
  k="$(laufende_kerndienste "${LADEN_PRAEFIXE[$i]}")"
  LADEN_KERN+=("$k")
  [ -n "$k" ] && ETWAS_LAEUFT=true
done
if ! $ETWAS_LAEUFT; then
  echo "ABBRUCH: in keinem Laden laeuft ein Kerndienst — hier ist nichts zu aktualisieren." >&2
  exit 1
fi

# Gateway-Neustart-Kurzschluss und die volle Abnahme (weiter unten) waren
# schon vor Mehrladen-Unterstuetzung ausschliesslich fuer den Basis-Laden
# gedacht (smoke.sh prueft nur dessen Container) und bleiben das hier
# bewusst weiterhin — NICHT Teil dieser Korrektur. Ein eigener Name statt
# des jetzt pro Laden ermittelten $KERN, damit diese beiden Stellen nicht
# versehentlich den Rest-Wert der LETZTEN Schleifen-Iteration eines
# ANDEREN Ladens sehen.
KERN_BASIS="${LADEN_KERN[0]}"

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

# Diese Flags sind global (haengen nur vom Diff ab, nicht vom Laden). Die
# eigentliche $BAUEN-Liste je Laden entsteht weiter unten, in der
# Build-Schleife, aus diesen Flags UND dem laden-eigenen $KERN-Schnappschuss.
BAUEN_BEI_MCP=false; BAUEN_BEI_COMPOSE=false
OPENWA_BAUEN=false; GATEWAY_NEU=false; HINWEIS=""
STT_GEAENDERT=false; MCP_GEAENDERT=false

if echo "$GEAENDERT" | grep -E '^sales-mcp/' >/dev/null; then
  BAUEN_BEI_MCP=true
  MCP_GEAENDERT=true
  GATEWAY_NEU=true  # Gemessene Falle (26.08.2026): ein sales-mcp-Neustart
                    # trennt die MCP-Verbindung des Gateways stillschweigend.
fi
if echo "$GEAENDERT" | grep -E '^docker-compose' >/dev/null; then
  BAUEN_BEI_COMPOSE=true; OPENWA_BAUEN=true
fi
if echo "$GEAENDERT" | grep -E '^openwa/upstream/' >/dev/null; then
  OPENWA_BAUEN=true
fi
# sales-stt (01.09.2026) hat ein EIGENES Image (faster-whisper, 431 MB) und
# steht seit 16.09.2026 in KERN_ALLE, aber BAUEN_BEI_MCP/BAUEN_BEI_COMPOSE
# greifen nur bei sales-mcp/ bzw. docker-compose* — eine Aenderung NUR an
# sales-stt/ wuerde ohne diese Zeile nie gebaut. In der Build-Schleife
# unten wird das je Laden NUR angewendet, wenn sales-stt dort tatsaechlich
# laeuft (KORREKTURRUNDE 1: vorher unbedingt, ohne Laufend-Pruefung —
# haette einen Laden, in dem sales-stt nie lief, von sich aus hochgezogen).
if echo "$GEAENDERT" | grep -E '^sales-stt/' >/dev/null; then
  STT_GEAENDERT=true
fi
if echo "$GEAENDERT" | grep -E '^config/workspace/' >/dev/null; then
  GATEWAY_NEU=true
fi
if echo "$GEAENDERT" | grep -E '^config/openclaw' >/dev/null; then
  HINWEIS="config/openclaw geaendert: wirkt nur auf frische Volumes; laufende Instanz manuell mit openclaw config set nachziehen"
  echo "HINWEIS: $HINWEIS"
fi

gateway_neustarten() {
  # Nur anfassen, was laeuft — KERN_BASIS enthaelt sales-claw nur dann.
  # Bewusst nur der Basis-Laden, siehe Kommentar bei KERN_BASIS oben.
  case " $KERN_BASIS " in
    *" sales-claw "*) docker restart sales-claw >/dev/null ;;
  esac
}

rueckbau() {
  echo "Abnahme rot — Rueckbau auf $ALT." >&2
  git reset --hard "$ALT" >/dev/null
  # KORREKTURRUNDE 1: vorher lief hier `docker compose $L up -d --build
  # $KERN` fuer JEDEN Laden mit dem EINEN, aus dem Basis-Laden ermittelten
  # $KERN — die Rueckfahrkarte haette damit jeden weiteren Laden auf den
  # vollen Neun-Dienste-Stand hochgezogen. Jetzt je Laden der eigene
  # Schnappschuss aus LADEN_KERN; ein Laden ohne zuvor laufende Dienste
  # bleibt unangetastet (nichts wiederherzustellen).
  for i in "${!LADEN_PRAEFIXE[@]}"; do
    k="${LADEN_KERN[$i]}"
    [ -n "$k" ] || continue
    # shellcheck disable=SC2086
    docker compose ${LADEN_ENVARGS[$i]} up -d --build $k
  done
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

# Build-Schleife: je Laden eigenes $KERN (Schnappschuss von oben) und
# eigenes $BAUEN. Ein Laden ohne zuvor laufende Dienste (leerer Eintrag in
# LADEN_KERN) wird komplett uebersprungen — es gibt fuer ihn nichts
# anzufassen (Tor/Vorgabe aus Korrekturrunde 1), statt ihn von hier aus
# hochzuziehen.
for i in "${!LADEN_PRAEFIXE[@]}"; do
  P="${LADEN_PRAEFIXE[$i]}"
  K="${LADEN_KERN[$i]}"
  [ -n "$K" ] || continue

  BAUEN=""
  if $BAUEN_BEI_MCP || $BAUEN_BEI_COMPOSE; then
    BAUEN="$K"
  fi
  if $STT_GEAENDERT; then
    c="$(containername sales-stt "$P")"
    if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" = "running" ]; then
      BAUEN="$BAUEN sales-stt"
    fi
  fi
  # sales-linkedin und sales-telegram TEILEN SICH das sales-mcp-Image und
  # stehen seit 16.09.2026 auch in KERN_ALLE (damit schon in $K enthalten,
  # wenn sie laufen und BAUEN_BEI_MCP/-COMPOSE zutrifft). Dieser Block
  # bleibt als explizites Gegenlesen derselben Bedingung stehen, jetzt mit
  # containername() PRO LADEN statt — wie vor Korrekturrunde 1 — gegen den
  # bloss fuer den Basis-Laden korrekten Dienstschluessel selbst.
  if $MCP_GEAENDERT; then
    for _dienst in sales-linkedin sales-telegram; do
      c="$(containername "$_dienst" "$P")"
      if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" = "running" ]; then
        BAUEN="$BAUEN $_dienst"
      fi
    done
  fi

  if [ -n "$BAUEN" ]; then
    # shellcheck disable=SC2086
    docker compose ${LADEN_ENVARGS[$i]} up -d --build $BAUEN
  fi
done

if $OPENWA_BAUEN; then
  for i in "${!LADEN_PRAEFIXE[@]}"; do
    # shellcheck disable=SC2086
    docker compose ${LADEN_ENVARGS[$i]} -f docker-compose.openwa.yml up -d --build openwa
  done
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
# am 30.08.2026, als genau das passierte. Bewusst nur der Basis-Laden
# (KERN_BASIS), siehe Kommentar dort — smoke.sh prueft ebenfalls nur ihn.
if [ "$KERN_BASIS" = "$KERN_ALLE" ]; then
  bash "$WURZEL/deploy/smoke.sh" || rueckbau
  status_schreiben eingespielt "$ALT" "$NEU" "${HINWEIS:-glatt durchgelaufen}"
  echo "Update eingespielt und Abnahme gruen."
else
  echo "Abnahme UEBERSPRUNGEN: unvollstaendiger Stack (Aufbauphase). Es "
  echo "laeuft: $KERN_BASIS. Der neue Stand bleibt eingespielt; die volle"
  echo "Abnahme gilt erst nach dem Cutover."
  status_schreiben eingespielt "$ALT" "$NEU" \
    "${HINWEIS:+$HINWEIS; }Abnahme uebersprungen - unvollstaendiger Stack"
fi
