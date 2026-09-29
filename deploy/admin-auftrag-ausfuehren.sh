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
FEHLER_TEXT=""
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
  local grund="${FEHLER_TEXT:-Abbruch nach Schritt '$letzter' (Exit $exit_code)}"
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

# freier_port, freier_serve_port und zugang_einrichten (29.09.2026): eigene
# Datei, damit deploy/tests/test_ports_und_zugang.sh sie mit Attrappen
# pruefen kann.
# shellcheck source=ports-und-zugang.sh
. "$WURZEL/deploy/ports-und-zugang.sh"

# --- 0. Haengende Auftraege aus einem fruehen Absturz zurueckholen --------
# Spec §2.4 (Laden anlegen) / Spec 2026-09-22-tailscale-einladung-design
# §2.4 (Tailscale-Einladungen): ein 'laeuft', das laenger als 10 Minuten
# steht, ist kein laufender Auftrag mehr, sondern ein Rest eines
# abgebrochenen Laufs (Neustart, systemctl stop, OOM, ein haengender
# Tailscale-API-Aufruf trotz --max-time — keiner davon laesst den ERR-Trap
# feuern). Gilt fuer BEIDE Auftragsarten, sonst gibt es fuer die neuere
# keinen Weg zurueck: sales_app hat kein update/delete auf admin_auftraege.
psql_admin <<'SQL'
update sales.admin_auftraege
   set status = 'fehler',
       fehler = 'Haengender Auftrag: laenger als 10 Minuten auf ''laeuft'' '
                'stehengeblieben, vom naechsten Durchlauf zurueckgesetzt.',
       erledigt_am = now()
 where art in ('laden_anlegen', 'tailscale_einladen') and status = 'laeuft'
   and erstellt_am < now() - interval '10 minutes';
SQL

# --- 1. Naechsten offenen Auftrag holen, sofort auf 'laeuft' setzen -------
# Getrennt per ASCII Unit Separator chr(31) — weder '|' noch Tab reichen:
# eine E-Mail-Adresse darf laut mailadresse.py im lokalen Teil ein '|'
# enthalten (RFC-5322-atext), und Tab ist zwar selbst nirgends in einem
# Ladennamen ([a-z0-9_]) oder einer zulaessigen Adresse erlaubt, scheitert
# hier aber aus einem anderen Grund: Tab gehoert zu bashs Standard-IFS
# ("IFS-Whitespace"), und `read` fasst dabei mehrere aufeinanderfolgende
# Trenner zusammen und schneidet sie an Wortgrenzen ab — ein LEERES
# mittleres Feld (bei 'tailscale_einladen' ist `name` immer NULL, also
# coalesce(name,'') = '') verschwindet dann komplett, statt als leeres
# Feld erhalten zu bleiben, und alle nachfolgenden Felder ruecken eine
# Position nach vorn (EINLADEN_EMAIL landet faelschlich in LADEN_NAME,
# EINLADEN_EMAIL selbst bleibt leer). Nachgemessen. chr(31) ist NICHT Teil
# von IFS-Whitespace — `read` splittet dort ausschliesslich woertlich,
# ohne Zusammenfassen/Abschneiden leerer Felder. chr(31) kommt in einem
# Ladennamen ([a-z0-9_]) nie vor. In einer E-Mail-Adresse schliesst nur
# mailadresse.pys eigene Whitelist Steuerzeichen wie chr(31) aus — die
# CHECK-Constraint der Datenbank selbst (`[^@[:space:]]`) tut das NICHT,
# chr(31) zaehlt dort nicht als Leerraum. Unschaedlich bleibt es trotzdem:
# EINLADEN_EMAIL ist das LETZTE Feld dieses `read`, ein darin eingebettetes
# chr(31) wuerde also Teil des E-Mail-Inhalts, nicht ein Feld verschieben.
ZEILE="$(psql_admin -tAc \
  "select id || chr(31) || art || chr(31) || coalesce(name, '') || chr(31) \
          || coalesce(email, '') \
   from sales.admin_auftraege \
   where art in ('laden_anlegen', 'tailscale_einladen') and status = 'offen' \
   order by erstellt_am limit 1")"
if [ -z "$ZEILE" ]; then
  exit 0
fi
IFS=$'\037' read -r AUFTRAG_ID ART LADEN_NAME EINLADEN_EMAIL <<< "$ZEILE"
psql_admin -v id="$AUFTRAG_ID" <<'SQL'
update sales.admin_auftraege set status = 'laeuft' where id = :'id'::uuid;
SQL
ERLEDIGT+=("aufnahme")

if [ "$ART" = "laden_anlegen" ]; then
  # --- 2. Vier freie Ports suchen -------------------------------------------
  PORT_GATEWAY="$(freier_port 18894 18950)"
  PORT_UI="$(freier_port 8791 8850)"
  PORT_OPENWA="$(freier_port 12785 12850)"
  PORT_SERVE="$(freier_serve_port 8446 8500)"
  ERLEDIGT+=("ports")

  # --- 3. deploy/laden-anlegen.sh — unveraendert, wie von Hand --------------
  bash deploy/laden-anlegen.sh "$LADEN_NAME" "$PORT_GATEWAY" "$PORT_UI" \
    "$PORT_OPENWA" "$PORT_SERVE" >/dev/null
  ERLEDIGT+=("umgebungsdatei")

  ENVDATEI="deploy/laeden/$LADEN_NAME.env"
  DB_PW="$(sed -n "s#.*sales_app_$LADEN_NAME:\\([^@]*\\)@.*#\\1#p" "$ENVDATEI")"
  if [ -z "$DB_PW" ]; then
    # `false` statt `exit 1`: AUFTRAG_ID ist an dieser Stelle bereits gesetzt
    # (Schritt 1 lief), also loest `false` den ERR-Trap aus und schreibt
    # sofort status='fehler' mit dem echten Grund und der bisherigen
    # ERLEDIGT-Liste. `exit 1` würde den Trap umgehen — der Auftrag bliebe
    # bis zu 10 Minuten lang faelschlich als "wird gerade angelegt" sichtbar,
    # bis Schritt 0 ihn beim naechsten Durchlauf mit einem generischen Grund
    # zurueckstuft (nachgemessen in der Schlusspruefung der Schlusspruefung).
    echo "FEHLER: Datenbank-Passwort konnte nicht aus $ENVDATEI gelesen werden." >&2
    false
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

  # --- 5. Die drei Dienste ohne Kundenzugangsdaten --------------------------
  # sales-mail seit 24.09.2026: er verschickt Konto-Mails ueber die
  # Betreiber-Identitaet (SYSTEM_*), Kundenentwuerfe erst, wenn das Postfach
  # des Ladens eingetragen ist. DIENSTSCHLUESSEL bleiben woertlich.
  docker compose --env-file "$ENVDATEI" up -d --build sales-mcp sales-ui sales-mail \
    >/dev/null
  ERLEDIGT+=("container")

  # --- 6. Konto mit Wegwerf-Passwort ----------------------------------------
  KONTO_PW="Probe-$(openssl rand -base64 9 | tr -d '/+=' | head -c 10)"
  printf '%s\n%s\n%s\n%s\n' "$LADEN_NAME" "freigeben" "$KONTO_PW" "$KONTO_PW" \
    | bash deploy/benutzer-anlegen.sh "$LADEN_NAME" >/dev/null
  ERLEDIGT+=("konto")

  # --- 6a. Tailscale-Zugang (29.09.2026) ------------------------------------
  # VOR der Willkommensmail: ihr Link zeigt auf diesen Port und soll schon
  # funktionieren, wenn die Mail ankommt. Scheitert es, geht keine Mail
  # raus — der Auftrag endet mit 'fehler' und nennt den Befehl zum
  # Nachholen. Der Laden selbst steht dann bereits (ERLEDIGT sagt, bis wo).
  FEHLER_TEXT="Laden angelegt, aber der Tailscale-Zugang auf Port $PORT_SERVE liess sich nicht einrichten; die Willkommensmail wurde NICHT verschickt. Von Hand: sudo tailscale serve --bg --https $PORT_SERVE http://127.0.0.1:$PORT_UI"
  zugang_einrichten "$PORT_SERVE" "$PORT_UI"
  FEHLER_TEXT=""
  ERLEDIGT+=("zugang")

  # --- 6b. Willkommensmail (24.09.2026) -------------------------------------
  # Nur mit Adresse. Geschrieben wird ins Schema des NEUEN Ladens - das darf
  # nur der Wirt (supabase_admin), nie die Oberflaeche des Basis-Ladens.
  # Der Name ist kein Geheimnis und bleibt per -v (psql quotet ihn per
  # :'…'). Die Adresse dagegen ist ein Personenbezug — anders als Name/
  # Schema geht sie deshalb NIE ueber argv (Spec §2.2: "Werte ueber
  # \getenv, nie ueber Argv"; Schlussfix-Welle 24.09.2026, Befund 2 — vorher
  # stand sie per "-v mail=..." woertlich sowohl im Argv des AEUSSEREN
  # docker-Aufrufs als auch in dem von psql selbst, sichtbar per `ps` fuer
  # jeden, der waehrend der laufenden Abfrage hinsah). Sie geht stattdessen
  # ueber die Prozessumgebung des docker-exec-Aufrufs (blosse Namensform
  # "-e MAIL") und "\getenv mail MAIL" als erste Heredoc-Zeile — dasselbe
  # Muster wie ERGEBNIS/DATEN weiter unten in dieser Datei. :'mail' bleibt
  # in der SQL selbst unveraendert, nur die Herkunft des Werts aendert sich.
  # Deshalb hier bewusst NICHT psql_admin (das ruft docker exec ohne -e
  # auf) — ON_ERROR_STOP=1 wird darum unten selbst gesetzt.
  WILLKOMMEN_STATUS=""
  if [ -n "$EINLADEN_EMAIL" ]; then
    ZETTEL_ID="$(MAIL="$EINLADEN_EMAIL" docker exec -i -e MAIL \
        debian-supabase-db-1 psql -U supabase_admin -d postgres \
        -v ON_ERROR_STOP=1 -tAq -v schema="sales_$LADEN_NAME" \
        -v name="$LADEN_NAME" <<'SQL' | head -n1
\getenv mail MAIL
update :"schema".benutzer set email = :'mail' where name = :'name';
insert into :"schema".benutzer_mails (benutzer, art)
  values (:'name', 'willkommen') returning id;
SQL
)"
    ERLEDIGT+=("willkommen-zettel")
    # Der Dienst wurde eben erst gestartet und fragt alle 10 s ab. Bis zu
    # 60 s warten; was danach noch offen ist, meldet die Seite ehrlich so.
    WILLKOMMEN_STATUS="noch unterwegs"
    # Abfrage als Heredoc, nicht per -c: psql setzt :"schema"/:'id' nur in
    # Eingabe von stdin/Datei ein, nicht in einem -c-Befehl.
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      STAND="$(psql_admin -tAq -v schema="sales_$LADEN_NAME" -v id="$ZETTEL_ID" \
        2>/dev/null <<'SQL' || true
select status || chr(31) || grund from :"schema".benutzer_mails where id = :'id'::uuid;
SQL
)"
      case "${STAND%%$'\037'*}" in
        gesendet) WILLKOMMEN_STATUS="verschickt"; break ;;
        fehler)   WILLKOMMEN_STATUS="fehlgeschlagen: ${STAND#*$'\037'}"; break ;;
      esac
      sleep 5
    done
  fi

  # --- 6c. WhatsApp vorbereiten (29.09.2026) --------------------------------
  # OpenWA starten, Schluessel und Sitzung in die Umgebungsdatei. NICHT
  # fatal: der Laden steht und die Mail ist raus; was hier fehlt, holt der
  # Knopf "WhatsApp verbinden" (deploy/whatsapp_wirt.py koppeln) von selbst
  # nach. `if !` loest den ERR-Trap bewusst nicht aus.
  WHATSAPP_STATUS="vorbereitet"
  if ! python3 deploy/whatsapp_wirt.py einrichten "$LADEN_NAME" >/dev/null 2>&1; then
    WHATSAPP_STATUS="nicht vorbereitet"
  fi
  ERLEDIGT+=("whatsapp")

  # --- 7. Erfolg melden ------------------------------------------------------
  # KONTO_PW geht hier ueber die PROZESSUMGEBUNG von python3, NICHT ueber
  # argv (Global Constraints: "Passwoerter nie ueber argv"). sys.argv haette
  # es waehrend der Laufzeit von python3 kurz in dessen Kommandozeile
  # getragen (sichtbar z.B. ueber /proc/<pid>/cmdline oder `ps aux`).
  ERGEBNIS_JSON="$(KONTO_PW="$KONTO_PW" WILLKOMMEN_AN="$EINLADEN_EMAIL" \
    WILLKOMMEN_STATUS="$WILLKOMMEN_STATUS" WHATSAPP_STATUS="$WHATSAPP_STATUS" python3 -c '
import json, os, sys
ui_port, serve_port = sys.argv[1], sys.argv[2]
ergebnis = {
    "port_ui": int(ui_port),
    "port_serve": int(serve_port),
    # Der Zugang auf serve_port steht seit Schritt 6a schon; WhatsApp
    # verbindet der neue Mensch seit 6c selbst. Von Hand bleiben die
    # Zugriffsregel und drei Kanaele.
    "hinweis": ("Als naechstes von Hand: die Zugriffsregel fuer den neuen "
                "Menschen (Port " + serve_port + ") und die Kanaele "
                "Postfach, Telegram, LinkedIn. WhatsApp verbindet er selbst "
                "auf seiner WhatsApp-Seite."),
    "whatsapp": os.environ["WHATSAPP_STATUS"],
}
# Mit Willkommensmail kennt NIEMAND das Wegwerf-Passwort - es wird nicht
# angezeigt, der Mensch setzt sein eigenes ueber den Link.
if os.environ["WILLKOMMEN_AN"]:
    # Der Link funktioniert fuer jeden, der schon im Tailnet ist und fuer
    # den die Zugriffsregel gilt - fuer den Betreiber also sofort.
    ergebnis["hinweis"] += (" Der Link in der Willkommensmail gilt 7 Tage; "
                             "der neue Mensch kann ihn oeffnen, sobald "
                             "seine Zugriffsregel steht.")
    ergebnis["willkommen"] = {"an": os.environ["WILLKOMMEN_AN"],
                              "status": os.environ["WILLKOMMEN_STATUS"]}
else:
    ergebnis["passwort"] = os.environ["KONTO_PW"]
print(json.dumps(ergebnis))' "$PORT_UI" "$PORT_SERVE")"
  unset KONTO_PW

  # ERGEBNIS_JSON traegt das frische Kontopasswort im Klartext (Feld
  # "passwort") weiter — das gilt NUR, wenn keine Adresse angegeben wurde
  # (siehe python3-Block oben: mit WILLKOMMEN_AN gesetzt steht dort
  # ergebnis["willkommen"], nie ein "passwort"-Feld; ohne Adresse bleibt es
  # beim Wegwerf-Passwort wie vor der Willkommensmail, Schlussfix-Welle
  # 24.09.2026, Befund 3). Der folgende Absatz gilt fuer beide Faelle
  # gleichermassen, weil ERGEBNIS_JSON so oder so ueber die Umgebung statt
  # argv geht — nur der INHALT unterscheidet sich. Ein "-v ergebnis=..." an
  # psql_admin haette es in PSQLS EIGENEM argv getragen — innerhalb des
  # Containers per `ps` sichtbar,
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

elif [ "$ART" = "tailscale_einladen" ]; then
  # --- 2. Zugangsdaten aus der Wirt-Umgebung lesen -------------------------
  # Niemals aus einem Container — siehe Spec §1.3 (T5a-Prinzip). Die Datei
  # deploy/systemd/sales-admin-auftraege.service traegt sie per
  # EnvironmentFile= in die Prozessumgebung DIESES Skripts, siehe
  # tailscale-admin.env.example.
  if [ -z "${TAILSCALE_API_KEY:-}" ] || [ -z "${TAILSCALE_TAILNET:-}" ]; then
    FEHLER_TEXT="TAILSCALE_API_KEY/TAILSCALE_TAILNET nicht gesetzt (siehe tailscale-admin.env.example)."
    echo "FEHLER: $FEHLER_TEXT" >&2
    false
  fi
  ERLEDIGT+=("zugangsdaten")

  # --- 3. Anfrage-Rumpf ueber python3 bauen, nicht per printf/Verkettung ---
  # EINLADEN_EMAIL besteht die Datenbank-CHECK-Pruefung (Aufgabe 1), die
  # etwas WEITER ist als mailadresse.pruefes eigene Whitelist (die
  # Datenbank-Pruefung schliesst nur '@'/Leerraum aus, nicht z. B. ein
  # Anfuehrungszeichen). Ein direkt verkettetes '{"email":"%s",...}' waere
  # angreifbar, sollte je eine Zeile diese Pruefung umgehen (z. B. ein
  # direkter SQL-Insert ausserhalb der Oberflaeche). json.dumps() entkommt
  # korrekt, unabhaengig vom Inhalt.
  #
  # Eine LISTE, kein einzelnes Objekt: /user-invites nimmt mehrere
  # Einladungen auf einmal an. Gemessen am 23.09.2026 im ersten echten Lauf —
  # ein einzelnes Objekt beantwortet Tailscale mit "invalid request body,
  # expected a list of invitation requests".
  ANFRAGE_JSON="$(EINLADEN_EMAIL="$EINLADEN_EMAIL" python3 -c '
import json, os
print(json.dumps([{"email": os.environ["EINLADEN_EMAIL"], "role": "member"}]))')"
  ERLEDIGT+=("anfrage-aufbau")

  # --- 4. Tailscale-Einladung anfordern -------------------------------------
  # Der persoenliche API-Schluessel geht NIE ueber curls eigenes -H/--Argv
  # (dort woertlich im Argv des Aufrufs sichtbar, dieselbe Leck-Klasse wie
  # LADEN_PASSWORT/ERGEBNIS oben) — stattdessen per stdin an `curl -K -`,
  # das eine kleine Konfigurationszeile liest statt eines
  # Kommandozeilenarguments. --max-time 15: der einzige Schritt in dieser
  # Datei, der ueber das lokale Netz hinausgeht und deshalb wirklich
  # haengen kann — die anderen sind alle localhost (docker exec/psql).
  ANTWORT="$(printf 'header = "Authorization: Bearer %s"\n' \
      "$TAILSCALE_API_KEY" | \
    curl -sS --max-time 15 -K - \
      -X POST \
      "https://api.tailscale.com/api/v2/tailnet/$TAILSCALE_TAILNET/user-invites" \
      -H "Content-Type: application/json" \
      -d "$ANFRAGE_JSON" \
      -w $'\n%{http_code}')"
  HTTP_CODE="${ANTWORT##*$'\n'}"
  ANTWORT_RUMPF="${ANTWORT%$'\n'*}"
  ERLEDIGT+=("api-aufruf")

  # --- 5. Ergebnis auswerten -------------------------------------------------
  # Tailscales genaues Fehler-JSON-Format war zum Entwurfszeitpunkt nicht
  # zweifelsfrei zu klaeren (Spec §1.2) — deshalb defensiv: sowohl
  # "message" als auch "error" versuchen, sonst der rohe Antwortkoerper
  # (gekuerzt). Ein einziger python3-Aufruf gibt STATUS und Nutzlast
  # tab-getrennt zurueck (derselbe Trenner-Grund wie beim Einlesen des
  # Auftrags in Schritt 1).
  AUSWERTUNG="$(HTTP_CODE="$HTTP_CODE" ANTWORT_RUMPF="$ANTWORT_RUMPF" \
    python3 -c '
import json, os
code = os.environ["HTTP_CODE"]
rumpf = os.environ["ANTWORT_RUMPF"]
try:
    daten = json.loads(rumpf)
except (ValueError, TypeError):
    daten = {}
# Erfolg kommt als Liste (eine Einladung je Anfrage-Eintrag, wir schicken
# genau einen), ein Fehler als Objekt mit "message".
if isinstance(daten, list):
    daten = daten[0] if daten and isinstance(daten[0], dict) else {}
if not isinstance(daten, dict):
    daten = {}
if code.startswith("2"):
    print("erfolg\t" + json.dumps({"inviteUrl": daten.get("inviteUrl", "")}))
else:
    grund = (daten.get("message") or daten.get("error")
             or "HTTP " + code + ": " + rumpf[:200])
    print("fehler\t" + str(grund))
')"
  STATUS="${AUSWERTUNG%%$'\t'*}"
  NUTZLAST="${AUSWERTUNG#*$'\t'}"
  ERLEDIGT+=("auswertung")

  if [ "$STATUS" = "fehler" ]; then
    FEHLER_TEXT="Tailscale: $NUTZLAST"
    echo "FEHLER: Tailscale-Einladung fehlgeschlagen — $NUTZLAST" >&2
    false
  fi

  # --- 6. Erfolg melden -------------------------------------------------------
  DATEN="$NUTZLAST" docker exec -i -e DATEN debian-supabase-db-1 \
    psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 \
    -v id="$AUFTRAG_ID" <<'SQL'
\getenv ergebnis DATEN
update sales.admin_auftraege
   set status = 'erfolg', ergebnis = :'ergebnis'::jsonb, erledigt_am = now()
 where id = :'id'::uuid;
SQL
else
  FEHLER_TEXT="Unbekannte Auftragsart '$ART'."
  echo "FEHLER: $FEHLER_TEXT" >&2
  false
fi

trap - ERR
