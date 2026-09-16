#!/usr/bin/env bash
# deploy/sicherung.sh [zielordner] — sichert die Zustands-Volumes JEDES
# Ladens als tar.gz mit Pruefsummen-Manifest, je Laden in einen eigenen
# Unterordner. Rotation: die juengsten 7 Zeitstempel-Ordner bleiben.
#
# openwa wird je Laden fuer die Dauer der Sicherung gestoppt: ein live
# getartes Chromium-Profil ist genau die Beschaedigungsklasse, die am
# 26.08.2026 die WhatsApp-Session gekostet hat. *-claw-state wird live
# gesichert (kleine JSON/SQLite-Dateien, vertretbares Risiko, kein
# Kanal-Ausfall).
set -euo pipefail

# Wie in deploy/laden-anlegen.sh und deploy/wiederherstellen.sh: ohne
# LC_ALL=C kollationiert bash Bereiche wie [a-z] unter z. B. de_DE.UTF-8
# GROSS- und Kleinschreibung durcheinander. Gehoert zu Tor 13
# (Schlussprüfung 2026-09-16, Bereich B, W3).
export LC_ALL=C

ZIEL="${1:-${SALES_BETRIEB:-$HOME/sales-betrieb}/sicherungen}"
STEMPEL="$(date +%Y%m%d-%H%M%S)"
ORDNER="$ZIEL/$STEMPEL"

mkdir -p "$ORDNER"

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Zaehlt fehlende, aber erwartete Volumes/Laeden ueber alle Laeden hinweg.
# Ein fehlendes Volume darf NICHT stillschweigend uebersprungen werden —
# das ist der gefaehrlichste Fehler in diesem Bereich: eine Sicherung, die
# einen Laden auslaesst und trotzdem "fertig" meldet, merkt niemand, bis
# er sie braucht. Deshalb laeuft die Schleife unten trotz eines Fehlers
# weiter (die anderen Laeden sollen trotzdem gesichert werden), aber das
# Skript endet am Schluss mit einem Rueckgabewert ungleich null. Vor die
# Ladenerkennung gezogen (war vorher erst danach deklariert), weil die
# Erkennung selbst jetzt schon FEHLER zaehlen kann (W3).
FEHLER=0

# Ein Laden je Praefix. Der bestehende heisst "sales" und hat keine
# Umgebungsdatei — seine Werte sind die Vorgaben in den Compose-Dateien.
#
# W3 (Schlussprüfung 2026-09-16, Bereich B): eine Umgebungsdatei ohne
# brauchbares LADEN_PRAEFIX (Tippfehler im Schluessel, auskommentierte
# Zeile, oder unter Debian ein mitkopiertes CRLF -> "ivan\r") ist ein
# FEHLER, keine Leerstelle — sie wurde bisher lautlos aus PRAEFIXE
# ausgelassen, der Laden fehlte dann in der Sicherung, ohne dass "Sicherung:
# ..." das verriet (gemessen: 4 .env-Dateien, 3 erkannte Laeden, exit 0).
# `tr -d '[:space:]'` faengt das CRLF ab, die Regex (identisch zu
# deploy/laden-anlegen.sh/wiederherstellen.sh) alles andere Unbrauchbare.
PRAEFIXE="sales"
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  p="$(sed -n 's/^LADEN_PRAEFIX=//p' "$e" | tr -d '[:space:]')"
  if ! [[ "$p" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
    echo "FEHLER: $e hat kein brauchbares LADEN_PRAEFIX ('${p:-leer}') - dieser Laden fehlt in dieser Sicherung." >&2
    FEHLER=$((FEHLER + 1))
    continue
  fi
  PRAEFIXE="$PRAEFIXE $p"
done

# Jedes gestoppte openwa kommt am Ende IMMER wieder hoch, auch wenn tar
# scheitert. Eine Liste statt einer Variablen, weil es jetzt mehrere sind.
GESTOPPT=""
neustarten() { for c in $GESTOPPT; do docker start "$c" >/dev/null || true; done; }
trap neustarten EXIT

for P in $PRAEFIXE; do
  UNTERORDNER="$ORDNER/$P"
  mkdir -p "$UNTERORDNER"

  # openwa fuer die Dauer der Sicherung stoppen: ein live getartes
  # Chromium-Profil ist die Beschaedigungsklasse, die am 26.08.2026 die
  # WhatsApp-Session gekostet hat.
  #
  # W5 (Schlussprüfung 2026-09-16, Bereich B): "$P-openwa" NICHT GEFUNDEN
  # (Container existiert gar nicht, anders als "existiert und ist nur
  # gestoppt") ist im Regelfall harmlos — ein frisch angelegter Laden, der
  # noch nie gestartet wurde. Hat sein Volume aber schon Inhalt, ist das
  # genau die Uebergangsfenster-Falle: solange auf der VM noch der ALTE
  # Container "openwa" (vor der Umstellung auf mehrere Laeden) laeuft,
  # existiert "sales-openwa" nicht, docker inspect schlaegt fehl, hier wird
  # NICHTS gestoppt — und unten wird trotzdem "sales-openwa-data" getart:
  # eine moeglicherweise veraltete Handkopie, waehrend die lebende Sitzung
  # in "openwa-data" (der ALTE Volume-Name) weiterlaeuft. Eine
  # Wiederherstellung daraus braechte eine abgelaufene WhatsApp-Anmeldung
  # zurueck — spiegelbildlich zur Gefahr im Kommentar oben: dort ein LIVE
  # getartes Profil, hier ein STILL VERALTETES. Deshalb: "nicht gefunden,
  # aber Volume hat Inhalt" wird benannt, nicht verschluckt.
  if status="$(docker inspect -f '{{.State.Status}}' "$P-openwa" 2>/dev/null)"; then
    if [ "$status" = "running" ]; then
      GESTOPPT="$GESTOPPT $P-openwa"
      docker stop "$P-openwa" >/dev/null
    fi
  elif docker volume inspect "$P-openwa-data" >/dev/null 2>&1 && \
       [ -n "$(docker run --rm -v "$P-openwa-data":/v alpine sh -c 'ls -A /v' 2>/dev/null)" ]; then
    echo "FEHLER: Container '$P-openwa' nicht gefunden, aber Volume '$P-openwa-data' hat Inhalt - moeglicherweise eine veraltete Handkopie, waehrend die lebende Sitzung anderswo (z. B. noch unter dem alten Namen 'openwa') weiterlaeuft. Von Hand pruefen (siehe Dateikopf) vor dem Vertrauen auf diese Sicherung." >&2
    FEHLER=$((FEHLER + 1))
  fi

  # sales-stt-modelle fehlt hier BEWUSST: 300 MB Modell, jederzeit neu
  # ladbar, und es ist ohnehin fuer alle Laeden dasselbe Volume.
  #
  # Existiert KEIN einziges der vier Volumes, wurde dieser Laden noch nie
  # gestartet (z. B. frisch per laden-anlegen.sh angelegt, aber noch nicht
  # hochgefahren) — das ist kein Fehler, nur nichts zu sichern. Existiert
  # MINDESTENS eins, muessen ALLE vier da sein: ein fehlendes Volume eines
  # sonst angelegten Ladens waere genau der stillschweigende Datenverlust,
  # den niemand bemerkt, bis er ihn braucht.
  VORHANDEN=0
  for vol in "$P-openwa-data" "$P-claw-state" "$P-claw-keys" "$P-sprachnachrichten"; do
    docker volume inspect "$vol" >/dev/null 2>&1 && VORHANDEN=$((VORHANDEN + 1))
  done

  if [ "$VORHANDEN" -eq 0 ]; then
    echo "Laden '$P': noch nicht angelegt (keine Volumes vorhanden) - uebersprungen." >&2
    continue
  fi

  for vol in "$P-openwa-data" "$P-claw-state" "$P-claw-keys" "$P-sprachnachrichten"; do
    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
      echo "FEHLER: Volume '$vol' fehlt fuer Laden '$P', obwohl andere Volumes dieses Ladens existieren." >&2
      FEHLER=$((FEHLER + 1))
      continue
    fi
    docker run --rm -v "$vol":/quelle:ro -v "$UNTERORDNER":/ziel alpine \
      tar czf "/ziel/$vol.tar.gz" -C /quelle .
  done

  # Das Datenbankschema dieses Ladens. "sales" bleibt "sales", jeder
  # andere Laden ist "sales_<praefix>" (Aufgabe 3) — ausgeschrieben statt
  # als Parametertrick, damit niemand ihn falsch liest.
  if [ "$P" = sales ]; then S=sales; else S="sales_$P"; fi
  docker exec debian-supabase-db-1 pg_dump -U supabase_admin -d postgres \
    --schema="$S" --no-owner \
    | gzip > "$UNTERORDNER/schema.sql.gz"
done

# Der Medienordner (Bind-Mount, gitignored) haengt an KEINEM Volume und
# fehlte deshalb in Sicherung UND Umzug — gefunden 31.08.2026, als nach
# dem Cutover die PDFs weg waren. Er ist Versandmaterial (Checklisten,
# Produktvideos) und gehoert mitgesichert.
MEDIEN="$(cd "$(dirname "$0")/.." && pwd)/media"
if [ -d "$MEDIEN" ]; then
  tar czf "$ORDNER/media.tar.gz" -C "$MEDIEN" .
fi

# -r/--no-run-if-empty: faende find nichts (koennte in einem Testaufbau
# passieren, in dem selbst "sales" noch keine Volumes hat), wuerde xargs
# sonst sha256sum OHNE Argumente starten — das liest von stdin und haengt.
( cd "$ORDNER" && find . -name '*.tar.gz' -o -name '*.sql.gz' | sort | xargs -r sha256sum > MANIFEST.sha256 )

echo "Sicherung: $ORDNER"
ls -lh "$ORDNER"

# W4 (Schlussprüfung 2026-09-16, Bereich B): Rotation UND Spiegelung laufen
# NUR, wenn diese Sicherung fehlerfrei war (Pruefung von $FEHLER, siehe
# oben). Vorher rotierte diese Stelle VOR jeder Fehlerpruefung — eine
# unvollstaendige Sicherung haette damit eine vollstaendige verdraengt: bei
# taeglichem Zeitgeber waeren nach sieben stillen Teilausfaellen alle guten
# Staende weg. Aus demselben Grund jetzt auch die Spiegelung erst hier:
# --delete wuerde sonst auch die gute Spiegelkopie mit dem unvollstaendigen
# Stand ueberschreiben.
if [ "$FEHLER" -eq 0 ]; then
  # Rotation: alles ausser den juengsten 7 Sicherungen entfernen.
  ls -1dt "$ZIEL"/*/ | tail -n +8 | xargs -r rm -rf

  # Spiegel AUSSER HAUS (F2, 31.08.2026): Sicherungen auf der Platte, die
  # sie schuetzen sollen, sind bei einem Plattenausfall wertlos. Steht in
  # $BETRIEB/spiegel.ziel ein rsync-Ziel (z. B. root@192.168.178.64:
  # /root/sales-claw-sicherungen), wird der ganze Sicherungsordner dorthin
  # gespiegelt — maschinenspezifische Laufzeit-Konfiguration, bewusst NICHT
  # in Git. --delete haelt die Rotation auch am Spiegel; ein Fehlschlag
  # bricht die Sicherung NICHT (lokal ist sie da), steht aber im Log.
  SPIEGEL_DATEI="${SALES_BETRIEB:-$HOME/sales-betrieb}/spiegel.ziel"
  if [ -f "$SPIEGEL_DATEI" ]; then
    SPIEGEL_ZIEL="$(head -1 "$SPIEGEL_DATEI" | tr -d '[:space:]')"
    if [ -n "$SPIEGEL_ZIEL" ]; then
      if rsync -a --delete -e "ssh -i $HOME/.ssh/sicherung-spiegel -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
          "$ZIEL"/ "$SPIEGEL_ZIEL"/; then
        echo "Spiegel: $SPIEGEL_ZIEL aktualisiert"
      else
        echo "WARNUNG: Spiegelung nach $SPIEGEL_ZIEL fehlgeschlagen — lokale Sicherung ist unberuehrt." >&2
      fi
    fi
  fi
else
  echo "Rotation und Spiegelung UEBERSPRUNGEN: diese Sicherung ist unvollstaendig (siehe FEHLER-Zeilen oben) - sie soll keine vollstaendige verdraengen." >&2
fi

if [ "$FEHLER" -gt 0 ]; then
  echo "ABBRUCH: $FEHLER erwartete Volume(s)/Laeden fehlten - siehe FEHLER-Zeilen oben. Sicherung ist UNVOLLSTAENDIG." >&2
  exit 1
fi
