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
# scheitert, endet mit status='fehler'"). Betrifft hier konkret die beiden
# direkten (nicht per "$(...)" aufgerufenen) `psql_admin`-Heredoc-Aufrufe
# weiter unten: die Markierung auf 'laeuft' und die Erfolgsmeldung.
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

AUFTRAG_ID=""
ERLEDIGT=()

psql_admin() {
  docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres "$@"
}

# Wird ueber `trap ... ERR` aufgerufen — nach JEDEM fehlschlagenden Befehl
# ab dem Punkt, an dem AUFTRAG_ID gesetzt ist. Schreibt 'fehler', NIE
# 'erfolg', und haelt fest, was bereits fertig war (Spec §2.4).
fehler_melden() {
  local exit_code=$?
  if [ -z "$AUFTRAG_ID" ]; then
    return 0
  fi
  local grund="Abbruch nach Schritt '${ERLEDIGT[-1]:-Start}' (Exit $exit_code)"
  local erledigt_json
  erledigt_json="$(python3 -c '
import json, sys
print(json.dumps({"erledigt": sys.argv[1:]}))' "${ERLEDIGT[@]:-}")"
  psql_admin -v id="$AUFTRAG_ID" -v ergebnis="$erledigt_json" \
             -v grund="$grund" <<'SQL'
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
  while [ "$kandidat" -le "$hoechstens" ]; do
    if ! ss -tlnH "sport = :$kandidat" | grep -q .; then
      echo "$kandidat"
      return 0
    fi
    kandidat=$((kandidat + 1))
  done
  echo "FEHLER: kein freier Port zwischen $1 und $hoechstens." >&2
  return 1
}

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

# --- 4. db/laden-anlegen.sql — Schema, Tabellen, Rolle, Rechte ------------
docker exec -i -e LADEN_PASSWORT="$DB_PW" debian-supabase-db-1 \
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
# argv (Global Constraints: "Passwoerter nie ueber argv"). Der Brief-Entwurf
# reichte es als sys.argv[1] durch — das haette waehrend der Laufzeit von
# python3 kurz in dessen Kommandozeile gestanden (sichtbar z.B. ueber
# /proc/<pid>/cmdline oder `ps aux`), genau die Umgehung, die
# db/laden-anlegen.sql fuer LADEN_PASSWORT bewusst vermeidet ("ein
# `-v passwort=...` stuende in der Prozessliste"). Hier stattdessen dieselbe
# Umgebungsvariablen-Uebergabe wie bei `docker exec -e LADEN_PASSWORT=...`
# oben: nur fuer den einen Aufruf gesetzt, danach wieder verworfen.
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
psql_admin -v id="$AUFTRAG_ID" -v ergebnis="$ERGEBNIS_JSON" <<'SQL'
update sales.admin_auftraege
   set status = 'erfolg', ergebnis = :'ergebnis'::jsonb, erledigt_am = now()
 where id = :'id'::uuid;
SQL

trap - ERR
