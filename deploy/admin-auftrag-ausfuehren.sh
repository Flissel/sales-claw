#!/usr/bin/env bash
# Holt den naechsten offenen "Laden anlegen"-Auftrag aus
# sales.admin_auftraege und fuehrt ihn aus — Schale um bestehende,
# geprueft Skripte, KEINE zweite Fassung ihrer Logik.
#
# Laeuft ueber deploy/systemd/sales-admin-auftraege.timer alle 20 Sekunden.
# Findet er keinen offenen Auftrag, endet er sofort mit Exit 0.
set -Eeuo pipefail
# -E (errtrace) ist hier NICHT optional: `psql_admin` unten ist eine
# Shell-Funktion, und ohne -E wird `trap ... ERR` fuer einen fehlschlagenden
# Befehl INNERHALB einer Funktion nicht ausgeloest, wenn die Funktion direkt
# aufgerufen wird (nicht ueber eine Kommandosubstitution) — laut bash(1),
# Abschnitt zu `set -o errtrace`: "The ERR trap is normally not inherited"
# von Shell-Funktionen, Kommandosubstitutionen und Subshells. Nachgemessen
# (bash 4.4): ein direkter Aufruf `psql_admin ... <<'SQL' ... SQL`, der
# fehlschlaegt, loeste OHNE -E die `fehler_melden`-Falle NICHT aus — das
# Skript brach per `set -e` einfach ab, der Auftrag blieb auf 'laeuft'
# haengen, nie 'fehler'. Genau das verletzt Spec §2.4 ("jeder Auftrag, der
# scheitert, endet mit status='fehler'"). Betrifft hier konkret den
# direkten (nicht per "$(...)" aufgerufenen) `psql_admin`-Heredoc-Aufruf
# weiter unten, der den Auftrag auf 'laeuft' setzt.
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

AUFTRAG_ID=""
ERLEDIGT=()

# ON_ERROR_STOP=1: ohne das kann psql einen SQL-Fehler auf stderr melden und
# trotzdem mit Exit 0 enden — dann faende weder `set -e` noch der ERR-Trap
# je etwas zum Reagieren, der Auftrag bliebe unbemerkt haengen. Das Repo
# setzt das ueberall sonst, wo psql ein Skript/Heredoc von stdin liest
# (db/laden-anlegen.sql:13, db/provision.sql:5, deploy/wiederherstellen.sh:
# 129) — hier zentral in der Funktion, damit es fuer jeden Aufruf gilt statt
# an jeder Aufrufstelle einzeln vergessen zu werden.
psql_admin() {
  docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres \
    -v ON_ERROR_STOP=1 "$@"
}

# Wird ueber `trap ... ERR` aufgerufen — nach JEDEM fehlschlagenden Befehl
# ab dem Punkt, an dem AUFTRAG_ID gesetzt ist. Schreibt 'fehler', NIE
# 'erfolg', und haelt fest, was bereits fertig war (Spec §2.4).
fehler_melden() {
  local exit_code=$?
  if [ -z "$AUFTRAG_ID" ]; then
    return 0
  fi
  # KEIN "${ERLEDIGT[-1]:-Start}": ein negativer Index in ein noch LEERES
  # Array ist unter `set -u` kein Fall, den `:-` rettet — der Zugriff
  # selbst scheitert schon ("bad array subscript"), bevor der Rueckfallwert
  # zum Zug kaeme. Nachgemessen: genau dieser Ausdruck in einer
  # `local`-Zuweisung unter `set -Eeuo pipefail` bricht die Funktion sofort
  # ab (Exit 1), OHNE die Update-Anweisung unten je zu erreichen. Erreichbar
  # ist das genau dann, wenn der ALLERERSTE psql_admin-Aufruf (Status auf
  # 'laeuft' setzen, weiter unten) fehlschlaegt — ERLEDIGT ist zu dem
  # Zeitpunkt noch `()`, das `+=("aufnahme")` kommt erst danach. Ohne diesen
  # Schutz wuerde fehler_melden selbst abstuerzen, BEVOR es 'fehler'
  # schreiben kann — der Auftrag bliebe fuer immer unsichtbar auf 'offen'.
  local letzter="Start"
  if [ "${#ERLEDIGT[@]}" -gt 0 ]; then
    letzter="${ERLEDIGT[-1]}"
  fi
  local grund="Abbruch nach Schritt '$letzter' (Exit $exit_code)"
  # W1 (Schlusspruefung): bewusst OHNE python3 — dieser Pfad ist die letzte
  # Verteidigungslinie, falls python3 selbst die Abbruchursache war (der
  # letzte Schritt vor dem Erfolgs-Update oben ruft selbst python3 auf).
  # Scheitert python3, meldet fehler_melden sonst selbst nichts, und der
  # Auftrag bliebe fuer immer auf 'laeuft' stehen. ERLEDIGT enthaelt
  # ausschliesslich fest verdrahtete, alphanumerische Bezeichner
  # ("aufnahme", "ports", ...) — kein Escaping noetig.
  local erledigt_json="[" sep="" schritt
  for schritt in "${ERLEDIGT[@]:-}"; do
    [ -z "$schritt" ] && continue
    erledigt_json+="$sep\"$schritt\""
    sep=","
  done
  erledigt_json+="]"
  erledigt_json="{\"erledigt\": $erledigt_json}"
  # ergebnis/grund enthalten kein Geheimnis, aber aus Konsistenz zum Fix
  # beim Erfolgs-Update unten (dieselbe docker-exec/psql-Angriffsflaeche):
  # blosse -e-Namensform statt -v, damit hier nie versehentlich Nutzdaten
  # (z.B. eine SQL-Fehlermeldung mit eingebettetem Geheimnis) im Argv
  # landen. Siehe die ausfuehrliche Begruendung beim Erfolgs-Update.
  ERLEDIGT_JSON="$erledigt_json" GRUND="$grund" \
    docker exec -i -e ERLEDIGT_JSON -e GRUND debian-supabase-db-1 \
    psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 \
    -v id="$AUFTRAG_ID" <<'SQL'
\getenv ergebnis ERLEDIGT_JSON
\getenv grund GRUND
update sales.admin_auftraege
   set status = 'fehler', ergebnis = :'ergebnis'::jsonb,
       fehler = :'grund', erledigt_am = now()
 where id = :'id'::uuid;
SQL
}
trap fehler_melden ERR

# Freien Port zwischen $1 und $2 suchen; gibt ihn auf stdout aus.
freier_port() {
  local kandidat="$1" hoechstens="$2"
  local ss_ausgabe
  while [ "$kandidat" -le "$hoechstens" ]; do
    # `ss`s EIGENEN Exit-Code separat pruefen, bevor dem grep-Ergebnis
    # getraut wird: `ss ... | grep -q .` allein ist unter `pipefail` nicht
    # sicher — scheitert `ss` (z.B. Exit 2, Programm fehlt/keine
    # Berechtigung), liefert `grep -q .` auf der dadurch leeren Eingabe
    # ebenfalls "kein Treffer" (Exit 1), und `pipefail` nimmt den Exit-Code
    # des RECHTESTEN fehlschlagenden Befehls — hier grep, nicht ss. Das `!`
    # davor drehte das zu "Port frei". Nachgemessen mit einer ss-Attrappe,
    # die mit Exit 2 scheitert: die alte Fassung lieferte trotzdem einen
    # Port zurueck, als waere er frei.
    if ! ss_ausgabe="$(ss -tlnH "sport = :$kandidat")"; then
      echo "FEHLER: 'ss' selbst ist fehlgeschlagen — Portpruefung nicht verlaesslich." >&2
      return 1
    fi
    if ! echo "$ss_ausgabe" | grep -q .; then
      echo "$kandidat"
      return 0
    fi
    kandidat=$((kandidat + 1))
  done
  echo "FEHLER: kein freier Port zwischen $1 und $hoechstens." >&2
  return 1
}

# --- 0. Haengende Auftraege aus einem fruehen Absturz zurueckholen --------
# Spec §2.4: ein 'laeuft', das laenger als 10 Minuten steht, ist kein
# laufender Auftrag mehr, sondern ein Rest eines abgebrochenen Laufs
# (Neustart, systemctl stop, OOM — keiner davon laesst den ERR-Trap
# feuern). Ohne diesen Schritt gibt es aus der Oberflaeche KEINEN Weg
# zurueck: sales_app hat kein update/delete auf admin_auftraege.
psql_admin <<'SQL'
update sales.admin_auftraege
   set status = 'fehler',
       fehler = 'Haengender Auftrag: laenger als 10 Minuten auf ''laeuft'' '
                'stehengeblieben, vom naechsten Durchlauf zurueckgesetzt.',
       erledigt_am = now()
 where art = 'laden_anlegen' and status = 'laeuft'
   and erstellt_am < now() - interval '10 minutes';
SQL

# --- 1. Naechsten offenen Auftrag holen, sofort auf 'laeuft' setzen -------
ZEILE="$(psql_admin -tAc \
  "select id || '|' || name from sales.admin_auftraege \
   where art = 'laden_anlegen' and status = 'offen' \
   order by erstellt_am limit 1")"
if [ -z "$ZEILE" ]; then
  exit 0
fi
AUFTRAG_ID="${ZEILE%%|*}"
LADEN_NAME="${ZEILE#*|}"
psql_admin -v id="$AUFTRAG_ID" <<'SQL'
update sales.admin_auftraege set status = 'laeuft' where id = :'id'::uuid;
SQL
ERLEDIGT+=("aufnahme")

# --- 2. Vier freie Ports suchen -------------------------------------------
PORT_GATEWAY="$(freier_port 18894 18950)"
PORT_UI="$(freier_port 8791 8850)"
PORT_OPENWA="$(freier_port 12785 12850)"
PORT_SERVE="$(freier_port 8446 8500)"
ERLEDIGT+=("ports")

# --- 3. deploy/laden-anlegen.sh — unveraendert, wie von Hand --------------
bash deploy/laden-anlegen.sh "$LADEN_NAME" "$PORT_GATEWAY" "$PORT_UI" \
  "$PORT_OPENWA" "$PORT_SERVE" >/dev/null
ERLEDIGT+=("umgebungsdatei")

ENVDATEI="deploy/laeden/$LADEN_NAME.env"
DB_PW="$(sed -n "s#.*sales_app_$LADEN_NAME:\\([^@]*\\)@.*#\\1#p" "$ENVDATEI")"
if [ -z "$DB_PW" ]; then
  echo "FEHLER: Datenbank-Passwort konnte nicht aus $ENVDATEI gelesen werden." >&2
  exit 1
fi

# --- 4. db/laden-anlegen.sql — Schema, Tabellen, Rolle, Rechte ------------
# W2 (Schlusspruefung): bewusst die vorangestellte Zuweisung statt
# "-e LADEN_PASSWORT=$DB_PW" — letzteres traegt den Wert woertlich im Argv
# des AEUSSEREN `docker`-Aufrufs (sichtbar z.B. ueber `ps aux`). Dasselbe
# bereits geprüfte Muster wie beim Erfolgs-Update weiter unten (ERGEBNIS).
LADEN_PASSWORT="$DB_PW" docker exec -i -e LADEN_PASSWORT debian-supabase-db-1 \
  psql -U supabase_admin -d postgres -v laden="$LADEN_NAME" \
  < db/laden-anlegen.sql >/dev/null
unset DB_PW
ERLEDIGT+=("schema")

# --- 5. Nur die zwei Dienste ohne externe Zugangsdaten --------------------
# DIENSTSCHLUESSEL bleiben "sales-mcp"/"sales-ui" — das Env-File entscheidet
# per LADEN_PRAEFIX-Interpolation, welcher Laden tatsaechlich entsteht.
docker compose --env-file "$ENVDATEI" up -d --build sales-mcp sales-ui \
  >/dev/null
ERLEDIGT+=("container")

# --- 6. Konto mit Wegwerf-Passwort ----------------------------------------
KONTO_PW="Probe-$(openssl rand -base64 9 | tr -d '/+=' | head -c 10)"
printf '%s\n%s\n%s\n%s\n' "$LADEN_NAME" "freigeben" "$KONTO_PW" "$KONTO_PW" \
  | bash deploy/benutzer-anlegen.sh "$LADEN_NAME" >/dev/null
ERLEDIGT+=("konto")

# --- 7. Erfolg melden ------------------------------------------------------
# KONTO_PW geht hier ueber die PROZESSUMGEBUNG von python3, NICHT ueber
# argv (Global Constraints: "Passwoerter nie ueber argv"). sys.argv haette
# es waehrend der Laufzeit von python3 kurz in dessen Kommandozeile
# getragen (sichtbar z.B. ueber /proc/<pid>/cmdline oder `ps aux`).
ERGEBNIS_JSON="$(KONTO_PW="$KONTO_PW" python3 -c '
import json, os, sys
pw = os.environ["KONTO_PW"]
ui_port, serve_port = sys.argv[1], sys.argv[2]
print(json.dumps({
    "passwort": pw,
    "port_ui": int(ui_port),
    "port_serve": int(serve_port),
    "hinweis": ("Als naechstes von Hand: tailscale serve --https " +
                serve_port + " http://127.0.0.1:" + ui_port +
                " einrichten, danach die Zugriffsregel fuer den neuen "
                "Menschen und die vier Kanaele (Postfach, Telegram, "
                "LinkedIn, WhatsApp).")
}))' "$PORT_UI" "$PORT_SERVE")"
unset KONTO_PW

# ERGEBNIS_JSON traegt das frische Kontopasswort im Klartext (Feld
# "passwort") weiter. Ein "-v ergebnis=..." an psql_admin haette es in
# PSQLS EIGENEM argv getragen — innerhalb des Containers per `ps` sichtbar,
# solange die Abfrage laeuft, dieselbe Umgehung, die db/laden-anlegen.sql
# fuer LADEN_PASSWORT bereits mit `\getenv` vermeidet
# (db/laden-anlegen.sql:80). Nachgemessen mit einer docker-Attrappe: mit
# "-v ergebnis=$ERGEBNIS_JSON" stand das Passwort woertlich im
# aufgezeichneten Argv des `docker exec`-Aufrufs.
#
# WICHTIG — auch "-e ERGEBNIS=$ERGEBNIS_JSON" (der Wert direkt hinter dem
# Flag) reicht dafuer NICHT: ebenfalls nachgemessen — der Wert steht dann
# zwar nicht mehr in PSQLS Argv, aber weiterhin woertlich im Argv des
# AEUSSEREN `docker`-Aufrufs selbst. Deshalb hier bewusst die BLOSSE
# Namensform "-e ERGEBNIS" mit vorangestellter Zuweisung: docker uebernimmt
# den Wert dann aus SEINER EIGENEN (nur fuer diesen einen Aufruf gesetzten)
# Prozessumgebung, nirgends erscheint er als Kommandozeilenargument. (W2,
# Schlusspruefung: `LADEN_PASSWORT` beim db/laden-anlegen.sql-Aufruf oben
# ist inzwischen auf genau dasselbe Muster umgestellt.)
ERGEBNIS="$ERGEBNIS_JSON" docker exec -i -e ERGEBNIS debian-supabase-db-1 \
  psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 \
  -v id="$AUFTRAG_ID" <<'SQL'
\getenv ergebnis ERGEBNIS
update sales.admin_auftraege
   set status = 'erfolg', ergebnis = :'ergebnis'::jsonb, erledigt_am = now()
 where id = :'id'::uuid;
SQL
unset ERGEBNIS_JSON

trap - ERR
