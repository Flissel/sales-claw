#!/usr/bin/env bash
# deploy/gateway-saat.sh — das openclaw.json eines Ladens ins Gateway-Volumen legen.
#
# WARUM ES DAS GIBT (Befund 22.09.2026): `config/openclaw.json` liegt als Saat
# im Repository, aber KEIN Skript spielte sie je in ein Volumen. Fuer den ersten
# Laden ist sie vor Monaten von Hand hineingekommen; ein zweiter startete
# deshalb mit leerem Volumen und meldete „Missing config. Run `openclaw setup`"
# in einer Neustartschleife (78 Versuche, gemessen).
#
# UND WARUM NICHT EINFACH KOPIEREN: die Saat ist NICHT generisch. In
# `channels.whatsapp.allowFrom` stehen die Nummern des ersten Betreibers, und
# `dmPolicy` ist `allowlist` — wer sie unveraendert saet, gibt dem neuen
# Agenten die Erlaubnisliste des alten. Der neue Mensch koennte seinen eigenen
# Agenten nicht ansprechen, der alte schon. Deshalb ist die Nummernliste ein
# Pflichtargument.
#
# Die Saat im Repository bleibt unberuehrt: dieses Skript liest sie und
# schreibt eine angepasste Fassung ins Volumen. Eine Quelle, keine zweite
# Vorlage, die auseinanderlaufen koennte.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAAT="$WURZEL/config/openclaw.json"
ZIEL="/home/node/.openclaw/openclaw.json"

if [ $# -lt 2 ]; then
  cat >&2 <<'HILFE'
Aufruf: deploy/gateway-saat.sh <gateway-container> <nummern> [--wirklich]

  <gateway-container>  z. B. ivan-claw
  <nummern>            wer diesen Agenten anschreiben darf, kommagetrennt,
                       E.164:  +49170...,+49160...
                       Das sind die Nummern DIESES Menschen, nicht die des
                       ersten Betreibers.
  --wirklich           ohne dieses Wort wird nur gezeigt, was geschaehe

Ohne --wirklich aendert dieses Skript nichts.
HILFE
  exit 2
fi

CONTAINER="$1"; NUMMERN="$2"; WIRKLICH="${3:-}"

[ -r "$SAAT" ] || { echo "ABBRUCH: Saat fehlt: $SAAT" >&2; exit 1; }
docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "ABBRUCH: Container '$CONTAINER' gibt es nicht." >&2; exit 1; }

# Jede Nummer einzeln pruefen. Der haeufigste Fehler waere, hier den
# Laden-Namen oder eine Nummer ohne Landesvorwahl zu uebergeben.
IFS=',' read -r -a LISTE <<< "$NUMMERN"
for n in "${LISTE[@]}"; do
  case "$n" in
    +[0-9][0-9]*) : ;;
    *) echo "ABBRUCH: '$n' ist keine E.164-Nummer (erwartet: +49...)." >&2; exit 1 ;;
  esac
done

# DIE WICHTIGSTE SPERRE: ein Gateway, das bereits konfiguriert ist, wird NICHT
# ueberschrieben. Das Volumen ist laut Config-Grenze (deploy/update.sh) der
# EIGENTUEMER von openclaw.json — dort stehen Allowlist, Kanaele und die
# WhatsApp-Kopplung. Ein versehentliches `gateway-saat.sh sales-claw ...`
# haette sonst die gewachsene Konfiguration des laufenden Ladens zerstoert.
if docker exec "$CONTAINER" test -f "$ZIEL" 2>/dev/null \
   || docker run --rm -v "${CONTAINER}-state:/v" busybox test -f /v/openclaw.json 2>/dev/null; then
  echo "ABBRUCH: '$CONTAINER' hat bereits ein openclaw.json — nicht angefasst." >&2
  echo "         Das Volumen besitzt diese Datei (Config-Grenze, deploy/update.sh)." >&2
  echo "         Wer sie wirklich ersetzen will, sichert sie vorher von Hand." >&2
  exit 1
fi

ANGEPASST="$(python3 - "$SAAT" "$NUMMERN" <<'PYEOF'
import json, sys
saat = json.load(open(sys.argv[1], encoding="utf-8"))
nummern = [n.strip() for n in sys.argv[2].split(",") if n.strip()]
# Kommentar-Schluessel raus. Die Saat im Repository erklaert sich selbst
# ueber `_kommentar_*`-Eintraege, und das soll sie auch - aber openclaws
# Schema lehnt sie ab: "Invalid config ... agents.defaults: Invalid input"
# (gemessen 22.09.2026 beim ersten Start eines frisch gesaeten Gateways).
# Also bleiben sie im Repository lesbar und verschwinden beim Schreiben.
def ohne_kommentare(o):
    if isinstance(o, dict):
        return {k: ohne_kommentare(v) for k, v in o.items()
                if not k.startswith("_kommentar")}
    if isinstance(o, list):
        return [ohne_kommentare(x) for x in o]
    return o

saat = ohne_kommentare(saat)

kanaele = saat.setdefault("channels", {}).setdefault("whatsapp", {})
vorher = kanaele.get("allowFrom", [])
kanaele["allowFrom"] = nummern

# Das Gateway-Token: die Saat im Repository deklariert `auth.mode = "token"`
# und traegt KEINEN Token - richtig so, ein Geheimnis gehoert nicht ins Git.
# Nur erzeugte es auch niemand, und ein frisch gesaetes Gateway weigerte
# sich deshalb zu starten: „Refusing to bind gateway to lan without auth"
# (gemessen 22.09.2026, Neustartschleife). Hier entsteht eines, je Laden
# eigen. Es bleibt im Volumen - das besitzt laut Config-Grenze
# (deploy/update.sh) ohnehin diese Datei.
import secrets
auth = saat.setdefault("gateway", {}).setdefault("auth", {})
if auth.get("mode") == "token" and not auth.get("token"):
    auth["token"] = secrets.token_urlsafe(32)
    sys.stderr.write("  gateway.auth.token: neu erzeugt (bleibt im Volumen)" + chr(10))
# Die Erlaubnisliste ist der einzige Wert, der sich je Mensch unterscheidet.
# Faende sich hier je ein weiterer, gehoert er GENAUSO hierher — und nicht in
# eine zweite Vorlage.
sys.stderr.write("  allowFrom: %s  ->  %s\n" % (vorher, nummern))
print(json.dumps(saat, ensure_ascii=False, indent=2))
PYEOF
)"

if [ "$WIRKLICH" != "--wirklich" ]; then
  echo "== PROBELAUF — nichts wird geschrieben (mit --wirklich ausfuehren) =="
  echo "  Ziel: $CONTAINER:$ZIEL  ($(printf '%s' "$ANGEPASST" | wc -c) Zeichen)"
  exit 0
fi

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
printf '%s\n' "$ANGEPASST" > "$TMP"
docker cp "$TMP" "$CONTAINER:$ZIEL"
# Der Eigentuemer stimmt bereits (docker cp uebernimmt die UID der Datei im
# Volumen). Der frueher hier stehende `docker exec ... chown` brach das
# Skript ab, wenn der Container NICHT LAEUFT - und genau dann saet man:
# gemessen 22.09.2026, die Datei war geschrieben, das Skript meldete
# trotzdem einen Fehler und nie „gesaet".
echo "  gesaet: $CONTAINER:$ZIEL"
echo
# Der stille Ausfall, der erst beim ERSTEN Cron-Lauf auffaellt (gemessen
# 22.09.2026): die Saat traegt bewusst KEINE Anmeldung - ein Zugangstoken
# gehoert nicht ins Git. Folge: ein neuer Laden faellt auf das freie Modell
# zurueck, startet sauber, meldet „[gateway] ready", ist healthy - und
# scheitert erst Stunden spaeter mit „All models failed". Deshalb steht es
# hier, nicht im Log.
echo
echo "ACHTUNG — dieser Laden hat noch KEINE eigene Modell-Anmeldung."
echo "Er faellt damit auf das Ausweichmodell zurueck (openrouter/free),"
echo "dessen Tageskontingent sich ALLE Laeden mit demselben Schluessel"
echo "teilen. Der Agent startet trotzdem sauber und scheitert erst beim"
echo "ersten echten Lauf:"
echo "    All models failed (2): ... No API key found for provider \"anthropic\""
echo "Anmeldung einrichten, bevor Cron-Jobs scharf gestellt werden:"
echo "    docker exec -it $CONTAINER openclaw models auth login --provider anthropic"
echo
echo "Jetzt starten und nachsehen, ob er durchkommt:"
echo "  docker start $CONTAINER && sleep 8 && docker logs --tail 5 $CONTAINER"
