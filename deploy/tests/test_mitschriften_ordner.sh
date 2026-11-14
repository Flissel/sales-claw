#!/usr/bin/env bash
# Prueft den Mitschriften-Ordner je Laden (Mitschriften-Ablage, 14.11.2026)
# ohne Docker-Start: Compose haengt /mitschriften an sales-termine, sales-ui
# und sales-mcp (Loeschantrag) ein (beschreibbar), update.sh weist Laeden
# ohne eigenen oder mit geteiltem Ordner ab, laden-anlegen.sh und
# beispiel.env schreiben die Zeile, sicherung.sh sichert den Ordner,
# wiederherstellen.sh stellt ihn her.
# `docker compose config` laeuft nur, wenn `docker compose` am Ort vorhanden
# ist (mit .env.example, nie mit einer echten .env); sonst wird dieser Teil
# uebersprungen (und gemeldet). update.sh laeuft in einer Wegwerf-Kopie
# (WURZEL = Elternordner des Skripts) mit einer Attrappe fuer flock.
#
#   bash deploy/tests/test_mitschriften_ordner.sh
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$WURZEL/docker-compose.yml"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

fehler() { echo "FEHLER: $*" >&2; exit 1; }

# --- Compose ----------------------------------------------------------------
# Statisch (CR-tolerant): Umgebungsvariable und Einhaengung je Dienst.
AKTIV="$(sed -e 's/\r$//' -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$COMPOSE")"
block() {
  echo "$AKTIV" | awk -v d="$1" '
    /^[^[:space:]]/ { in_services = ($0 == "services:") ; next }
    in_services && /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") ; next }
    in_services && aktiv { print }'
}
for d in sales-termine sales-ui sales-mcp; do
  b="$(block "$d")"
  echo "$b" | grep -qE '^      (- )?MITSCHRIFTEN_PFAD[=:][[:space:]]*/mitschriften[[:space:]]*$' \
    || fehler "$d: MITSCHRIFTEN_PFAD=/mitschriften fehlt"
  echo "$b" | grep -qE '^      - \$\{MITSCHRIFTEN_ORDNER:-\./laeden-daten/\$\{LADEN_PRAEFIX:-sales\}/mitschriften\}:/mitschriften[[:space:]]*$' \
    || fehler "$d: Volume \${MITSCHRIFTEN_ORDNER:-./laeden-daten/\${LADEN_PRAEFIX:-sales}/mitschriften}:/mitschriften (rw) fehlt"
done

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  sed 's/\r$//' "$WURZEL/.env.example" > "$T/compose.env"
  echo "MITSCHRIFTEN_ORDNER=./laeden-daten/probe/mitschriften" >> "$T/compose.env"
  ( cd "$WURZEL" && docker compose -f "$COMPOSE" --env-file "$T/compose.env" config ) \
    > "$T/config.yml" 2> "$T/config.err" \
    || fehler "docker compose config schlaegt fehl: $(grep -v 'variable is not set' "$T/config.err" | head -5)"
  for d in sales-termine sales-ui sales-mcp; do
    # Gerenderter Dienstblock, darin die Einhaengung mit Ziel /mitschriften.
    sed 's/\r$//' "$T/config.yml" | awk -v d="$d" '
      /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") }
      aktiv { print }' > "$T/dienst.yml"
    grep -qE '^      MITSCHRIFTEN_PFAD: /mitschriften$' "$T/dienst.yml" \
      || fehler "$d: gerendert ohne MITSCHRIFTEN_PFAD=/mitschriften"
    eintrag="$(awk '
      /^      - type: / { if (blk ~ /target: \/mitschriften\n/) { print blk; exit } blk = "" }
      { blk = blk $0 "\n" }
      END { if (blk ~ /target: \/mitschriften\n/) print blk }' "$T/dienst.yml")"
    [ -n "$eintrag" ] || fehler "$d: gerendert ohne Volume mit Ziel /mitschriften"
    echo "$eintrag" | grep -q 'read_only' && fehler "$d: /mitschriften ist read_only (muss beschreibbar sein)"
    echo "$eintrag" | grep -q 'laeden-daten.probe.mitschriften' \
      || fehler "$d: Quelle folgt MITSCHRIFTEN_ORDNER nicht: $(echo "$eintrag" | grep source)"
  done
  # Fehlt MITSCHRIFTEN_ORDNER in der .env (erstes Update nach dem Merge, update.sh
  # prueft noch mit den alten Regeln), faellt Compose auf den Ordner des EIGENEN
  # Ladens zurueck, nie auf den des Basis-Ladens.
  quelle() { # env-datei dienst -> gerenderte Quelle des /mitschriften-Volumes
    ( cd "$WURZEL" && docker compose -f "$COMPOSE" --env-file "$1" config ) 2>/dev/null \
      | sed 's/\r$//' | awk -v d="$2" '
          /^  [A-Za-z0-9_-]+:[[:space:]]*$/ { aktiv = ($1 == d ":") }
          aktiv && /^      - type: / { blk = "" }
          aktiv { blk = blk $0 "\n"; if ($0 ~ /target: \/mitschriften$/ && !fertig) { print blk; fertig = 1 } }' \
      | sed -n 's/^ *source: //p'
  }
  grep -v '^MITSCHRIFTEN_ORDNER=\|^LADEN_PRAEFIX=' "$T/compose.env" > "$T/ohne.env"
  cp "$T/ohne.env" "$T/ivan.env"; echo "LADEN_PRAEFIX=ivan" >> "$T/ivan.env"
  for d in sales-termine sales-ui sales-mcp; do
    q="$(quelle "$T/ivan.env" "$d")"
    case "$q" in */laeden-daten/ivan/mitschriften) ;; *) fehler "$d: ohne MITSCHRIFTEN_ORDNER, mit LADEN_PRAEFIX=ivan ist die Quelle '$q' (erwartet .../laeden-daten/ivan/mitschriften)";; esac
    q="$(quelle "$T/ohne.env" "$d")"
    case "$q" in */laeden-daten/sales/mitschriften) ;; *) fehler "$d: Basis-Laden ohne Angaben: Quelle '$q' (erwartet .../laeden-daten/sales/mitschriften)";; esac
  done
  echo "OK: docker compose config gueltig"
else
  echo "HINWEIS: docker compose nicht vorhanden, config-Pruefung uebersprungen"
fi

# --- update.sh: Laden-.env pruefen -----------------------------------------
mkdir -p "$T/w/deploy/laeden" "$T/stub" "$T/betrieb"
cp "$WURZEL/deploy/update.sh" "$T/w/deploy/update.sh"
printf '#!/bin/sh\nexit 0\n' > "$T/stub/flock"; chmod +x "$T/stub/flock"
laden_env() { # datei praefix mitschriften-zeile(leer = keine)
  { echo "LADEN_PRAEFIX=$2"
    echo "MEDIEN_ORDNER=./laeden-daten/$2/media"
    echo "MEDIEN_ERZEUGT_ORDNER=./laeden-daten/$2/media-erzeugt"
    [ -z "$3" ] || echo "$3"; } > "$T/w/deploy/laeden/$1.env"
}
update_ausgabe() {
  PATH="$T/stub:$PATH" SALES_BETRIEB="$T/betrieb" bash "$T/w/deploy/update.sh" 2>&1 </dev/null || true
}
abgewiesen() { # beschreibung  (erwartet FEHLER mit MITSCHRIFTEN_ORDNER)
  local aus
  aus="$(update_ausgabe)"
  echo "$aus" | grep -qE '^FEHLER: .*MITSCHRIFTEN_ORDNER' \
    || fehler "update.sh weist nicht ab: $1 (Ausgabe: $(echo "$aus" | head -3))"
  echo "$aus" | grep -q '^ABBRUCH: ' || fehler "update.sh bricht nicht ab: $1"
}
for wert in "" "MITSCHRIFTEN_ORDNER=" "MITSCHRIFTEN_ORDNER=./laeden-daten/sales/mitschriften" \
            "MITSCHRIFTEN_ORDNER=laeden-daten/sales/mitschriften/" \
            "MITSCHRIFTEN_ORDNER=$T/w/laeden-daten/sales/mitschriften"; do
  rm -f "$T"/w/deploy/laeden/*.env
  laden_env ivan ivan "$wert"
  abgewiesen "Wert '${wert:-<fehlt>}'"
done
# Zwei Laeden, derselbe Ordner: der erste Laden besteht, der zweite wird abgewiesen.
rm -f "$T"/w/deploy/laeden/*.env
laden_env anna anna "MITSCHRIFTEN_ORDNER=./laeden-daten/geteilt/mitschriften"
laden_env ivan ivan "MITSCHRIFTEN_ORDNER=./laeden-daten/geteilt/mitschriften"
aus="$(update_ausgabe)"
echo "$aus" | grep -qE "^FEHLER: .*ivan\.env teilt MITSCHRIFTEN_ORDNER" \
  || fehler "update.sh weist geteilten Ordner nicht ab (Ausgabe: $(echo "$aus" | head -3))"
echo "$aus" | grep -qE "anna\.env.*MITSCHRIFTEN_ORDNER" \
  && fehler "update.sh weist den ersten Laden mit eigenem Ordner faelschlich ab"

# --- laden-anlegen.sh / beispiel.env / sicherung.sh / wiederherstellen.sh -----
LF() { sed 's/\r$//' "$1"; }
LF "$WURZEL/deploy/laden-anlegen.sh" | grep -qxF 'MITSCHRIFTEN_ORDNER=./laeden-daten/$NAME/mitschriften' \
  || fehler "laden-anlegen.sh schreibt MITSCHRIFTEN_ORDNER=./laeden-daten/<name>/mitschriften nicht"
LF "$WURZEL/deploy/laeden/beispiel.env" | grep -qxF 'MITSCHRIFTEN_ORDNER=./laeden-daten/beispiel/mitschriften' \
  || fehler "beispiel.env: MITSCHRIFTEN_ORDNER fehlt"
LF "$WURZEL/deploy/sicherung.sh" | grep -qF 'MITSCHRIFTEN_ORDNER:mitschriften' \
  || fehler "sicherung.sh: Paar MITSCHRIFTEN_ORDNER:mitschriften fehlt"
LF "$WURZEL/deploy/sicherung.sh" | grep -qF 'laeden-daten/sales/mitschriften' \
  || fehler "sicherung.sh: Vorgabe ./laeden-daten/sales/mitschriften des Basis-Ladens fehlt"
LF "$WURZEL/deploy/wiederherstellen.sh" | grep -qF 'mitschriften.tar.gz' \
  || fehler "wiederherstellen.sh: mitschriften.tar.gz wird nicht behandelt"

# --- Verhalten: wiederherstellen.sh (Mitschriften-Teil) und sicherung.sh -------
# Wegwerf-Baum mit Kopien der Skripte (WURZEL = Elternordner des Skripts) und
# einer docker-Attrappe, die nichts tut und Erfolg meldet. Die Volume-Archive
# sind leere Dateien (die Attrappe entpackt nichts).
mkdir -p "$T/bin"
printf '#!/bin/sh\nexit 0\n' > "$T/bin/docker"; chmod +x "$T/bin/docker"
neuer_baum() { # name
  B="$T/$1"; rm -rf "$B"; mkdir -p "$B/deploy/laeden" "$B/q/ivan"
  cp "$WURZEL/deploy/wiederherstellen.sh" "$WURZEL/deploy/sicherung.sh" "$B/deploy/"
  sed -i 's/\r$//' "$B/deploy/wiederherstellen.sh" "$B/deploy/sicherung.sh"
  for v in ivan-openwa-data ivan-claw-state ivan-claw-keys ivan-sprachnachrichten; do : > "$B/q/ivan/$v.tar.gz"; done
  : > "$B/q/ivan/schema.sql.gz"
}
archiv() { # baum quellordner  -> q/ivan/mitschriften.tar.gz + Manifest
  mkdir -p "$T/inhalt"; rm -rf "$T/inhalt"/*; echo neu > "$T/inhalt/neu.html"
  tar czf "$1/q/ivan/mitschriften.tar.gz" -C "$T/inhalt" .
}
manifest() { ( cd "$1/q" && find . -name '*.gz' | sort | xargs sha256sum > MANIFEST.sha256 ); }
wiederherstellen() { # baum
  PATH="$T/bin:$PATH" bash "$1/deploy/wiederherstellen.sh" "$1/q" ivan 2>&1 </dev/null || true
}
fremd() { mkdir -p "$1"; echo alt > "$1/alt.html"; }

# 1. Laden ohne Zeile in seiner .env: Ordner des Basis-Ladens bleibt unberuehrt.
neuer_baum r1; archiv "$B"; manifest "$B"
echo "LADEN_PRAEFIX=ivan" > "$B/deploy/laeden/ivan.env"
fremd "$B/laeden-daten/sales/mitschriften"
aus="$(wiederherstellen "$B")"
echo "$aus" | grep -q '^FEHLER: kein MITSCHRIFTEN_ORDNER' || fehler "wiederherstellen: Laden ohne Zeile nicht gemeldet ($aus)"
[ -f "$B/laeden-daten/sales/mitschriften/alt.html" ] && [ ! -e "$B/laeden-daten/sales/mitschriften/neu.html" ] \
  || fehler "wiederherstellen: Ordner des Basis-Ladens wurde angefasst"

# 2. Pfad ./ bzw . : nichts ausserhalb wird geloescht.
for pfad in ./ . / ../; do
  neuer_baum r2; archiv "$B"; manifest "$B"
  printf 'LADEN_PRAEFIX=ivan\nMITSCHRIFTEN_ORDNER=%s\n' "$pfad" > "$B/deploy/laeden/ivan.env"
  echo wichtig > "$B/deploy/wichtig.txt"
  aus="$(wiederherstellen "$B")"
  echo "$aus" | grep -q "^FEHLER: MITSCHRIFTEN_ORDNER ergibt" || fehler "wiederherstellen: Pfad '$pfad' nicht abgewiesen ($aus)"
  [ -f "$B/deploy/wichtig.txt" ] && [ -f "$B/deploy/wiederherstellen.sh" ] || fehler "wiederherstellen: Pfad '$pfad' loeschte Dateien"
done

# 3. Kaputtes Archiv: Ordnerinhalt bleibt.
neuer_baum r3; echo "kein tar" > "$B/q/ivan/mitschriften.tar.gz"; manifest "$B"
printf 'LADEN_PRAEFIX=ivan\nMITSCHRIFTEN_ORDNER=./laeden-daten/ivan/mitschriften\n' > "$B/deploy/laeden/ivan.env"
fremd "$B/laeden-daten/ivan/mitschriften"
aus="$(wiederherstellen "$B")"
echo "$aus" | grep -q 'ist nicht lesbar' || fehler "wiederherstellen: kaputtes Archiv nicht gemeldet ($aus)"
[ -f "$B/laeden-daten/ivan/mitschriften/alt.html" ] || fehler "wiederherstellen: kaputtes Archiv leerte den Ordner"

# 4. Gutfall: Inhalt wird ersetzt, Meldung kommt, Basis-Ordner unberuehrt.
neuer_baum r4; archiv "$B"; manifest "$B"
printf 'LADEN_PRAEFIX=ivan\nMITSCHRIFTEN_ORDNER=./laeden-daten/ivan/mitschriften\n' > "$B/deploy/laeden/ivan.env"
fremd "$B/laeden-daten/ivan/mitschriften"; fremd "$B/laeden-daten/sales/mitschriften"
aus="$(wiederherstellen "$B")"
echo "$aus" | grep -q '^Mitschriften-Ordner .* wiederhergestellt' || fehler "wiederherstellen: Gutfall ohne Meldung ($aus)"
[ -f "$B/laeden-daten/ivan/mitschriften/neu.html" ] && [ ! -e "$B/laeden-daten/ivan/mitschriften/alt.html" ] \
  || fehler "wiederherstellen: Gutfall ersetzte den Inhalt nicht"
[ -f "$B/laeden-daten/sales/mitschriften/alt.html" ] || fehler "wiederherstellen: Gutfall beruehrte den Basis-Laden"

# 5. sicherung.sh: Laden ohne Zeile sichert NICHT den Ordner des Basis-Ladens.
neuer_baum s1
echo "LADEN_PRAEFIX=ivan" > "$B/deploy/laeden/ivan.env"
fremd "$B/laeden-daten/sales/mitschriften"
aus="$(PATH="$T/bin:$PATH" bash "$B/deploy/sicherung.sh" "$B/z" 2>&1 </dev/null || true)"
echo "$aus" | grep -q '^FEHLER: ivan hat kein MITSCHRIFTEN_ORDNER' || fehler "sicherung: Laden ohne Zeile nicht gemeldet ($aus)"
ls "$B"/z/*/sales/mitschriften.tar.gz >/dev/null 2>&1 || fehler "sicherung: Basis-Laden ohne mitschriften.tar.gz"
ls "$B"/z/*/ivan/mitschriften.tar.gz >/dev/null 2>&1 && fehler "sicherung: Laden ohne Zeile sicherte den Ordner des Basis-Ladens"

# 6. sicherung.sh: tar Exit 1 ("Datei geaendert") ist kein Abbruch, Exit 2 zaehlt als FEHLER.
mkdir -p "$T/tarbin"
cat > "$T/tarbin/tar" <<'STUB'
#!/bin/sh
# Echtes tar, danach fuer das Mitschriften-Archiv den Code aus TAR_RC melden.
/usr/bin/tar "$@"; rc=$?
case "$*" in *mitschriften.tar.gz*) [ "$rc" -eq 0 ] && exit "${TAR_RC:-0}" ;; esac
exit "$rc"
STUB
chmod +x "$T/tarbin/tar"
for rc in 1 2; do
  neuer_baum s2; fremd "$B/laeden-daten/sales/mitschriften"
  aus="$(TAR_RC=$rc PATH="$T/tarbin:$T/bin:$PATH" bash "$B/deploy/sicherung.sh" "$B/z" 2>&1 </dev/null && echo "RC=0" || echo "RC=$?")"
  ls "$B"/z/*/sales/mitschriften.tar.gz >/dev/null 2>&1 || fehler "sicherung: tar-Exit $rc: Archiv fehlt ($aus)"
  if [ "$rc" = 1 ]; then
    echo "$aus" | grep -q '^HINWEIS: sales/mitschriften' || fehler "sicherung: tar-Exit 1 nicht als Hinweis gemeldet ($aus)"
    echo "$aus" | grep -q '^ABBRUCH' && fehler "sicherung: tar-Exit 1 brach die Sicherung ab ($aus)"
    echo "$aus" | grep -q '^FEHLER: tar fuer' && fehler "sicherung: tar-Exit 1 als Fehler gezaehlt ($aus)"
  else
    echo "$aus" | grep -q '^FEHLER: tar fuer sales/mitschriften endete mit Code 2' || fehler "sicherung: tar-Exit 2 nicht als FEHLER gemeldet ($aus)"
  fi
done

echo "OK: mitschriften-ordner"
