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

# Derselbe Container/Benutzer wie in deploy/sicherung.sh (dort erzeugt).
# Schema-Name: "sales" bleibt "sales", jeder andere Laden ist
# "sales_<praefix>" (Aufgabe 3) — dieselbe ausgeschriebene Fallunterscheidung
# wie dort, damit niemand sie falsch liest.
DB_CONTAINER="debian-supabase-db-1"
if [ "$LADEN" = sales ]; then S=sales; else S="sales_$LADEN"; fi

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
# W6 (Schlussprüfung 2026-09-16, Bereich B): das Datenbankschema
# (schema.sql.gz, von sicherung.sh:90-92 je Laden abgelegt) zaehlt hier
# jetzt GENAUSO als erwarteter Teil wie die vier Volumes — vorher kannte
# diese Pruefung nur die Volumes, die Wiederherstellungsschleife unten
# stellte das Schema gar nicht wieder her, meldete am Ende aber trotzdem
# "wiederhergestellt": Leads, Entwuerfe, Aktivitaeten waren weiterhin weg,
# die Meldung sagte das Gegenteil. Eine Meldung, die mehr behauptet als
# geschehen ist, ist der schlimmere Fehler als ein Abbruch.
#
# Fehlt die Sicherung dieses Ladens VOLLSTAENDIG (kein einziges der vier
# *.tar.gz UND kein schema.sql.gz), gibt es nichts wiederherzustellen —
# das ist ein Abbruch, kein stiller Nop, denn "wiederhergestellt" waere
# hier schlicht falsch. Fehlt NUR EIN TEIL, obwohl andere da sind, ist das
# eine unvollstaendige Sicherung (z. B. durch einen fruehen
# sicherung.sh-Fehlschlag) — auch das bricht ab, statt einen Laden nur
# halb wiederherzustellen.
VORHANDEN=0
for vol in $VOLUMES; do
  [ -f "$UNTERORDNER/$vol.tar.gz" ] && VORHANDEN=$((VORHANDEN + 1))
done
[ -f "$UNTERORDNER/schema.sql.gz" ] && VORHANDEN=$((VORHANDEN + 1))
if [ "$VORHANDEN" -eq 0 ]; then
  echo "ABBRUCH: $UNTERORDNER enthaelt keines der erwarteten Teile (Volumes $VOLUMES, schema.sql.gz) - nichts wiederherzustellen." >&2
  exit 1
fi

FEHLER=0
for vol in $VOLUMES; do
  if [ ! -f "$UNTERORDNER/$vol.tar.gz" ]; then
    echo "FEHLER: $UNTERORDNER/$vol.tar.gz fehlt, obwohl andere Teile dieses Ladens gesichert wurden." >&2
    FEHLER=$((FEHLER + 1))
    continue
  fi
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/ziel -v "$UNTERORDNER":/quelle:ro alpine \
    sh -c "find /ziel -mindepth 1 -delete && tar xzf /quelle/$vol.tar.gz -C /ziel"
done

if [ ! -f "$UNTERORDNER/schema.sql.gz" ]; then
  echo "FEHLER: $UNTERORDNER/schema.sql.gz fehlt, obwohl andere Teile dieses Ladens gesichert wurden - Kundendaten (Leads, Entwuerfe, Aktivitaeten) werden NICHT wiederhergestellt." >&2
  FEHLER=$((FEHLER + 1))
else
  # Existiert das Schema noch (bzw. schon wieder), automatisch per CASCADE
  # zu ueberschreiben waere GENAU der blinde Eingriff, den Tor 13 verbietet
  # ("Fasst nichts an, dessen Name nicht mit diesem Praefix beginnt") — ein
  # Fremdschluessel aus einem ANDEREN Laden-Schema koennte per CASCADE
  # mitgerissen werden, und das laesst sich in diesem Lauf nicht pruefen.
  # In diesem (haeufigeren) Fall bricht die Wiederherstellung deshalb mit
  # den noetigen Befehlen ab, statt sie blind auszufuehren. Existiert das
  # Schema NICHT (der eigentliche Katastrophenfall — genau wofuer dieses
  # Skript da ist), ist ein frisches CREATE SCHEMA gefahrlos: es kann per
  # Definition noch nichts geben, das per CASCADE aus einem anderen Laden
  # mitgerissen wuerde.
  ist_da="$(docker exec "$DB_CONTAINER" psql -U supabase_admin -d postgres -tAc \
    "SELECT 1 FROM information_schema.schemata WHERE schema_name='$S'" 2>/dev/null || true)"
  if [ "$ist_da" = "1" ]; then
    echo "FEHLER: Datenbankschema '$S' existiert bereits - automatisches Ueberschreiben wuerde per CASCADE moeglicherweise andere Laeden treffen (Tor 13). Von Hand entscheiden, z. B.:" >&2
    echo "  docker exec $DB_CONTAINER psql -U supabase_admin -d postgres -c 'DROP SCHEMA \"$S\" CASCADE;'" >&2
    echo "  gunzip -c $UNTERORDNER/schema.sql.gz | docker exec -i $DB_CONTAINER psql -v ON_ERROR_STOP=1 --single-transaction -U supabase_admin -d postgres -f -" >&2
    FEHLER=$((FEHLER + 1))
  else
    # --single-transaction + ON_ERROR_STOP=1: entweder alles oder nichts.
    # Ohne ON_ERROR_STOP setzt psql nach einem Fehler in der Mitte des
    # Dumps einfach fort und beendet sich trotzdem mit Erfolg — dieselbe
    # Falle, die diese ganze Korrekturrunde beheben soll, nur innerhalb von
    # psql statt innerhalb dieses Skripts.
    if ! gunzip -c "$UNTERORDNER/schema.sql.gz" | docker exec -i "$DB_CONTAINER" \
        psql -v ON_ERROR_STOP=1 --single-transaction -U supabase_admin -d postgres -f -; then
      echo "FEHLER: Datenbankschema '$S' aus $UNTERORDNER/schema.sql.gz konnte nicht eingespielt werden." >&2
      FEHLER=$((FEHLER + 1))
    fi
  fi
fi

if [ "$FEHLER" -gt 0 ]; then
  echo "ABBRUCH: $FEHLER erwartete Teil(e) fehlten oder scheiterten - Wiederherstellung ist UNVOLLSTAENDIG." >&2
  exit 1
fi

echo "Laden '$LADEN' wiederhergestellt aus $UNTERORDNER (Volumes und Datenbankschema '$S')."
echo "Kein anderer Laden wurde angefasst."
echo "Naechster Schritt: Dienste in der Cutover-Reihenfolge starten"
echo "(docs/04_BETRIEB_MINIPC.md)."
