#!/usr/bin/env bash
# deploy/wiederherstellen.sh <sicherungsordner> <laden> — stellt die vier
# Zustands-Volumes EINES Ladens aus einer Sicherung her, nach
# Pruefsummen-Kontrolle. Fasst nichts an, dessen Name nicht mit diesem
# Praefix beginnt (Tor 13 der Spec 2026-09-16-zweiter-laden-getrennt: eine
# Wiederherstellung stellt EINEN Laden her, ohne die anderen anzufassen).
#
# Verweigert die Arbeit, solange <laden>-openwa oder <laden>-claw laufen:
# eine Wiederherstellung unter laufendem Betrieb hinterlaesst genau die
# halb geschriebenen Profile, gegen die sie helfen soll.
set -euo pipefail

# Feste Locale wie in deploy/laden-anlegen.sh: unter z. B. de_DE.UTF-8
# kollationiert bash Bereiche wie [a-z] GROSS- und Kleinschreibung
# durcheinander — "Ivan" bestuende die Pruefung unten dann faelschlich
# (nachgemessen 16.09.2026: `[[ "Ivan" =~ ^[a-z]... ]]` matcht ohne
# LC_ALL=C unter de_DE.UTF-8). Genau das darf hier nicht passieren, das
# ist Tor 13.
export LC_ALL=C

QUELLE="${1:?Aufruf: wiederherstellen.sh <sicherungsordner> <laden>}"
LADEN="${2:?Aufruf: wiederherstellen.sh <sicherungsordner> <laden>}"

# Ohne Ladennamen wird NICHT geraten: eine Wiederherstellung, die den
# falschen Laden trifft, ist genau der Schaden, den Tor 13 ausschliesst.
if ! [[ "$LADEN" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "ABBRUCH: '$LADEN' ist kein gueltiger Ladenname." >&2
  exit 1
fi

UNTERORDNER="$QUELLE/$LADEN"
[ -d "$UNTERORDNER" ] || { echo "ABBRUCH: $UNTERORDNER fehlt." >&2; exit 1; }

# sales-sprachnachrichten wurde bisher GESICHERT, aber nie
# WIEDERHERGESTELLT (gefunden 16.09.2026: sicherung.sh sichert vier
# Volumes, wiederherstellen.sh kannte nur drei). Kundeninhalt gehoert in
# beide Listen.
VOLUMES="$LADEN-openwa-data $LADEN-claw-state $LADEN-claw-keys $LADEN-sprachnachrichten"

for c in "$LADEN-openwa" "$LADEN-claw"; do
  if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || true)" = "running" ]; then
    echo "ABBRUCH: $c laeuft. Erst stoppen: docker stop $LADEN-openwa $LADEN-claw" >&2
    exit 1
  fi
done

( cd "$UNTERORDNER" && sha256sum -c <(grep "./$LADEN/" "$QUELLE/MANIFEST.sha256" | sed "s#\./$LADEN/##") )

# Wie bei der Sicherung (deploy/sicherung.sh): ein fehlendes Volume darf
# NICHT stillschweigend uebersprungen werden — das ist der gefaehrlichste
# Fehler in diesem Bereich, spiegelbildlich zur Sicherung selbst: eine
# Wiederherstellung, die einen Teil auslaesst und trotzdem
# "wiederhergestellt" meldet, merkt niemand, bis er ihn braucht.
#
# Fehlt die Sicherung dieses Ladens VOLLSTAENDIG (kein einziges der vier
# *.tar.gz), gibt es nichts wiederherzustellen — das ist ein Abbruch, kein
# stiller Nop, denn "wiederhergestellt" waere hier schlicht falsch. Fehlt
# NUR EINES der vier, obwohl andere da sind, ist das eine unvollstaendige
# Sicherung (z. B. durch einen fruehen sicherung.sh-Fehlschlag) — auch das
# bricht ab, statt einen Laden nur halb wiederherzustellen.
VORHANDEN=0
for vol in $VOLUMES; do
  [ -f "$UNTERORDNER/$vol.tar.gz" ] && VORHANDEN=$((VORHANDEN + 1))
done
if [ "$VORHANDEN" -eq 0 ]; then
  echo "ABBRUCH: $UNTERORDNER enthaelt keines der erwarteten Volumes ($VOLUMES) - nichts wiederherzustellen." >&2
  exit 1
fi

FEHLER=0
for vol in $VOLUMES; do
  if [ ! -f "$UNTERORDNER/$vol.tar.gz" ]; then
    echo "FEHLER: $UNTERORDNER/$vol.tar.gz fehlt, obwohl andere Volumes dieses Ladens gesichert wurden." >&2
    FEHLER=$((FEHLER + 1))
    continue
  fi
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/ziel -v "$UNTERORDNER":/quelle:ro alpine \
    sh -c "find /ziel -mindepth 1 -delete && tar xzf /quelle/$vol.tar.gz -C /ziel"
done

if [ "$FEHLER" -gt 0 ]; then
  echo "ABBRUCH: $FEHLER erwartete Volume(s) fehlten in der Sicherung - Wiederherstellung ist UNVOLLSTAENDIG." >&2
  exit 1
fi

echo "Laden '$LADEN' wiederhergestellt aus $UNTERORDNER."
echo "Kein anderer Laden wurde angefasst."
echo "Naechster Schritt: Dienste in der Cutover-Reihenfolge starten"
echo "(docs/04_BETRIEB_MINIPC.md)."
