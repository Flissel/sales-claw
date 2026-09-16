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

ZIEL="${1:-${SALES_BETRIEB:-$HOME/sales-betrieb}/sicherungen}"
STEMPEL="$(date +%Y%m%d-%H%M%S)"
ORDNER="$ZIEL/$STEMPEL"

mkdir -p "$ORDNER"

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ein Laden je Praefix. Der bestehende heisst "sales" und hat keine
# Umgebungsdatei — seine Werte sind die Vorgaben in den Compose-Dateien.
PRAEFIXE="sales"
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  PRAEFIXE="$PRAEFIXE $(sed -n 's/^LADEN_PRAEFIX=//p' "$e")"
done

# Jedes gestoppte openwa kommt am Ende IMMER wieder hoch, auch wenn tar
# scheitert. Eine Liste statt einer Variablen, weil es jetzt mehrere sind.
GESTOPPT=""
neustarten() { for c in $GESTOPPT; do docker start "$c" >/dev/null || true; done; }
trap neustarten EXIT

# Zaehlt fehlende, aber erwartete Volumes ueber alle Laeden hinweg. Ein
# fehlendes Volume darf NICHT stillschweigend uebersprungen werden — das
# ist der gefaehrlichste Fehler in diesem Bereich: eine Sicherung, die
# einen Laden auslaesst und trotzdem "fertig" meldet, merkt niemand, bis
# er sie braucht. Deshalb laeuft die Schleife unten trotz eines Fehlers
# weiter (die anderen Laeden sollen trotzdem gesichert werden), aber das
# Skript endet am Schluss mit einem Rueckgabewert ungleich null.
FEHLER=0

for P in $PRAEFIXE; do
  UNTERORDNER="$ORDNER/$P"
  mkdir -p "$UNTERORDNER"

  # openwa fuer die Dauer der Sicherung stoppen: ein live getartes
  # Chromium-Profil ist die Beschaedigungsklasse, die am 26.08.2026 die
  # WhatsApp-Session gekostet hat.
  if [ "$(docker inspect -f '{{.State.Status}}' "$P-openwa" 2>/dev/null || true)" = "running" ]; then
    GESTOPPT="$GESTOPPT $P-openwa"
    docker stop "$P-openwa" >/dev/null
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

echo "Sicherung: $ORDNER"
ls -lh "$ORDNER"

if [ "$FEHLER" -gt 0 ]; then
  echo "ABBRUCH: $FEHLER erwartete Volume(s) fehlten - siehe FEHLER-Zeilen oben. Sicherung ist UNVOLLSTAENDIG." >&2
  exit 1
fi
