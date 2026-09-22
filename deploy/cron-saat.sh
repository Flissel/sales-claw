#!/usr/bin/env bash
# deploy/cron-saat.sh — die Cron-Jobs eines Ladens aus deploy/cron/ saeen.
#
# WARUM ES DAS GIBT (Befund 22.09.2026): `openclaw cron list` zeigte neun
# aktive Jobs, und die Spalte `Declaration` war bei ALLEN ein Strich. Sie
# existierten nur im Gateway-Volume — in keiner Datei. Fuer einen zweiten
# Laden gab es damit keine Vorlage, und ein verlorenes Volume haette sie
# ersatzlos mitgenommen.
#
# IDEMPOTENT ueber `--declaration-key`. Das ist nicht Bequemlichkeit: ohne
# ihn legt jeder Lauf dieselben Jobs NOCH EINMAL an, und niemand merkt es,
# bis der Digest dreimal kommt. Mit ihm fuellt sich zugleich die
# `Declaration`-Spalte — man sieht auf einen Blick, welcher Job aus diesem
# Ordner stammt und welcher von Hand gebaut wurde.
#
# `${MELDE_AN}` in den Deklarationen ist der EINE Wert, der sich je Mensch
# unterscheidet. Im laufenden Gateway stand dort die Nummer des Betreibers,
# sechsmal eingebrannt; unveraendert gesaet, meldeten Ivans Laeufe an Felix'
# Telefon.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRONDIR="$WURZEL/deploy/cron"

if [ $# -lt 2 ]; then
  cat >&2 <<'HILFE'
Aufruf: deploy/cron-saat.sh <gateway-container> <melde-an> [--wirklich]

  <gateway-container>  z. B. sales-claw oder ivan-claw
  <melde-an>           WhatsApp-Ziel fuer die Meldungen DIESES Menschen,
                       z. B. +49170.......  (NICHT die des Betreibers)
  --wirklich           ohne dieses Wort wird nur gezeigt, was geschaehe

Ohne --wirklich aendert dieses Skript nichts. Das ist Absicht: es schreibt
in ein laufendes Gateway, und ein Tippfehler in <melde-an> schickt vier
Routinelaeufe taeglich an einen Fremden.
HILFE
  exit 2
fi

CONTAINER="$1"; MELDE_AN="$2"; WIRKLICH="${3:-}"

if ! docker inspect -f '{{.State.Status}}' "$CONTAINER" >/dev/null 2>&1; then
  echo "ABBRUCH: Container '$CONTAINER' gibt es nicht." >&2
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" != "running" ]; then
  echo "ABBRUCH: Container '$CONTAINER' laeuft nicht." >&2
  exit 1
fi
# Eine Nummer, keine Hausnummer. Der haeufigste Fehler waere, hier den
# Laden-Namen statt der Nummer zu uebergeben.
case "$MELDE_AN" in
  +[0-9][0-9]*) : ;;
  *) echo "ABBRUCH: <melde-an> muss mit + beginnen und Ziffern tragen (E.164), war: '$MELDE_AN'" >&2; exit 1 ;;
esac

[ "$WIRKLICH" = "--wirklich" ] || echo "== PROBELAUF — nichts wird geaendert (mit --wirklich ausfuehren) =="

for datei in "$CRONDIR"/*.json; do
  [ -e "$datei" ] || continue
  name="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['name'])" "$datei")"

  # Die Argumentliste baut python3 — ein Auftragstext enthaelt Zeilenumbrueche
  # und Anfuehrungszeichen, und in der Shell zusammengesetzt waere er
  # irgendwann falsch zitiert.
  # `mapfile < <(...)` verschluckt den Exit-Code der Prozessersetzung. Am
  # 22.09.2026 stuerzte python3 fuer eine Datei ab, und das Skript meldete
  # fuer sie trotzdem „wuerde saeen" — ein Fehlschlag, der wie Erfolg
  # aussieht. Deshalb erst in eine Variable, Code pruefen, dann zerlegen.
  if ! ROH="$(python3 - "$datei" "$MELDE_AN" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
melde_an = sys.argv[2]

def ersetze(x):
    if isinstance(x, str):
        return x.replace("${MELDE_AN}", melde_an)
    if isinstance(x, dict):
        return {k: ersetze(v) for k, v in x.items()}
    return x

d = ersetze(d)
plan = d.get("schedule", {})
zustellung = d.get("delivery", {}) or {}
argv = ["cron", "add", "--name", d["name"],
        "--declaration-key", "sales-claw/" + d["name"]]

if plan.get("kind") == "cron":
    argv += ["--cron", plan["expr"]]
    if plan.get("tz"):
        argv += ["--tz", plan["tz"]]
elif plan.get("kind") == "every":
    # `every` traegt `everyMs`, nicht `expr` — der Probelauf am 22.09.2026
    # stuerzte hier ab, weil dieser Zweig `expr` erwartete. `--every` will
    # eine Dauer wie "20m"; Millisekunden werden zurueckgerechnet.
    ms = plan.get("everyMs")
    if not isinstance(ms, int) or ms <= 0:
        raise SystemExit("everyMs fehlt oder ist unbrauchbar in %s: %r"
                         % (sys.argv[1], plan))
    argv += ["--every", "%dm" % (ms // 60000) if ms % 60000 == 0
             else "%ds" % (ms // 1000)]
else:
    raise SystemExit("unbekannter Zeitplan in %s: %r" % (sys.argv[1], plan))

nutzlast = d.get("payload", {})
if nutzlast.get("kind") != "agentTurn":
    raise SystemExit("nur agentTurn wird gesaet, nicht %r" % nutzlast.get("kind"))
argv += ["--message", nutzlast["message"]]

if d.get("agentId"):
    argv += ["--agent", d["agentId"]]
if d.get("sessionTarget"):
    argv += ["--session", d["sessionTarget"]]
if d.get("description"):
    argv += ["--description", d["description"]]
if zustellung.get("mode") == "announce":
    argv += ["--announce", "--channel", zustellung.get("channel", "last")]
    if zustellung.get("to"):
        argv += ["--to", zustellung["to"]]
# Ein abgeschalteter Job wird ABGESCHALTET gesaet. `firmenkontakte-anreichern`
# lief alle 20 Minuten und wurde am 22.09.2026 abgeschaltet, weil er
# Modell-Kontingent frass; wer diesen Ordner saet, soll ihn nicht
# versehentlich zurueckholen.
if d.get("enabled") is False:
    argv += ["--disabled"]

print("\n".join(argv))
PYEOF
)"; then
    echo "  FEHLER     $name — Deklaration nicht uebersetzbar (siehe oben)" >&2
    exit 1
  fi
  mapfile -t ARGS <<< "$ROH"

  if [ "$WIRKLICH" = "--wirklich" ]; then
    if docker exec "$CONTAINER" openclaw "${ARGS[@]}" >/dev/null 2>&1; then
      echo "  gesaet     $name"
    else
      echo "  FEHLER     $name — Aufruf abgelehnt" >&2
    fi
  else
    zustand="aktiv"
    printf '%s\n' "${ARGS[@]}" | grep -qx -- "--disabled" && zustand="abgeschaltet"
    echo "  wuerde saeen  $name ($zustand)"
  fi
done

echo
echo "Danach pruefen — die Spalte 'Declaration' darf nicht mehr leer sein:"
echo "  docker exec $CONTAINER openclaw cron list"
