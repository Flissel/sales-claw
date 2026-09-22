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
kanaele = saat.setdefault("channels", {}).setdefault("whatsapp", {})
vorher = kanaele.get("allowFrom", [])
kanaele["allowFrom"] = nummern
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
docker exec "$CONTAINER" sh -c "chown node:node $ZIEL 2>/dev/null || true"
echo "  gesaet: $CONTAINER:$ZIEL"
echo
echo "Jetzt starten und nachsehen, ob er durchkommt:"
echo "  docker start $CONTAINER && sleep 8 && docker logs --tail 5 $CONTAINER"
