#!/usr/bin/env bash
# UI-Anmeldung scharf schalten / Benutzer anlegen (E1) — der Menschen-Schritt.
#
# Laeuft auf der VM als Betriebsnutzer:
#   bash ~/sales-claw/deploy/benutzer-anlegen.sh          # Basis-Laden "sales"
#   bash ~/sales-claw/deploy/benutzer-anlegen.sh ivan     # der Laden "ivan"
#
# Fragt Name, Rolle und Passwort ab (Passwort unsichtbar, nie in der
# Prozessliste), legt den Benutzer in der Produktions-Tabelle DES
# GENANNTEN LADENS an und setzt beim ERSTEN Mal dessen UI_SESSION_SECRET —
# ab dann verlangt dessen Oberflaeche eine Anmeldung. Derselbe Aufruf setzt
# auch Passwoerter zurueck.
#
# W7 (Schlussprüfung-Korrekturwelle 2026-09-16, Bereich C): bis hierher war
# dieses Skript durchgehend auf den Basis-Laden "sales"/sales-mcp
# verdrahtet — fuer einen zweiten Laden gab es damit keinen Weg, ueberhaupt
# ein Konto anzulegen, und dessen Oberflaeche liefe dauerhaft im
# Uebergangszustand OHNE Anmeldepflicht (leeres UI_SESSION_SECRET, siehe
# docker-compose.yml, Dienst sales-ui). Fix: ein optionales erstes
# Argument, Laden-Erkennung nach demselben Muster wie
# deploy/laden-anlegen.sh (Namensmuster) und deploy/update.sh
# (containername(), Basis-Laden ohne Umgebungsdatei == Index/Praefix
# "sales"). OHNE Argument bleibt alles beim Basis-Laden — der bisherige,
# im Runbook (docs/04_BETRIEB_MINIPC.md, docs/05_BEDIENUNG.md) dokumentierte
# Aufruf ohne Argument funktioniert dadurch unveraendert weiter.
set -euo pipefail

# Wie in deploy/laden-anlegen.sh/update.sh/wiederherstellen.sh: ohne
# LC_ALL=C kollationiert bash Bereiche wie [a-z] unter z. B. de_DE.UTF-8
# GROSS- und Kleinschreibung durcheinander — ein Ladenname wie "Ivan"
# bestuende die Pruefung unten dann faelschlich.
export LC_ALL=C

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Laden-Erkennung — dasselbe Namensmuster wie SCHEMA_MUSTER in
# sales-mcp/server.py (auch in deploy/laden-anlegen.sh/update.sh geprueft):
# "sales" OHNE Umgebungsdatei ist der Basis-Laden (Vorgabewerte aus
# docker-compose.yml, wie bisher), jeder andere Name braucht eine bereits
# von deploy/laden-anlegen.sh erzeugte deploy/laeden/<name>.env.
LADEN="${1:-sales}"
if ! [[ "$LADEN" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "FEHLER: '$LADEN' passt nicht zum Schema-Muster aus server.py" >&2
  exit 1
fi

if [ "$LADEN" = sales ]; then
  # Der bestehende Laden: exakt der bisherige Pfad, keine Verhaltensaenderung.
  ENV_DATEI="$REPO/.env"
  ENVARG=""
else
  ENV_DATEI="$REPO/deploy/laeden/$LADEN.env"
  if [ ! -e "$ENV_DATEI" ]; then
    echo "FEHLER: $ENV_DATEI fehlt — erst deploy/laden-anlegen.sh $LADEN <port-gateway> <port-ui> <port-openwa> <port-serve> ausfuehren." >&2
    exit 1
  fi
  ENVARG="--env-file $ENV_DATEI"
fi

# Containername dieses Ladens — dasselbe Muster wie containername() in
# deploy/update.sh: <praefix>-<dienst ohne "sales-">. Fuer den Basis-Laden
# kommt dabei exakt "sales-mcp" heraus, der bisherige Wert.
MCP_CONTAINER="$LADEN-mcp"
# Compose-DIENSTSCHLUESSEL bleibt fuer jeden Laden "sales-ui" — nur
# container_name interpoliert den Praefix (docker-compose.yml); das ist
# der Name, den `docker compose ... up -d <dienst>` erwartet, nicht der
# Containername.
UI_DIENST="sales-ui"

if ! docker inspect -f '{{.State.Status}}' "$MCP_CONTAINER" 2>/dev/null | grep -qx running; then
  echo "FEHLER: Container $MCP_CONTAINER laeuft nicht — erst den Stack fuer Laden '$LADEN' starten." >&2
  exit 1
fi

read -r -p "Benutzername: " NAME
read -r -p "Rolle (lesen|freigeben|kalender): " ROLLE
read -r -s -p "Passwort (min. 10 Zeichen): " PASSWORT; echo
read -r -s -p "Passwort wiederholen: " PASSWORT2; echo
if [ "$PASSWORT" != "$PASSWORT2" ]; then
  echo "FEHLER: Passwoerter stimmen nicht ueberein — nichts getan." >&2
  exit 1
fi

# Passwort ueber STDIN in den Container — nie als Argument.
printf '%s' "$PASSWORT" | docker exec -i "$MCP_CONTAINER" \
  python benutzer_anlegen.py "$NAME" "$ROLLE"
unset PASSWORT PASSWORT2

# Der AKTUELLE WERT zaehlt, nicht nur, ob die Zeile existiert: eine aus
# deploy/laeden/beispiel.env kopierte Datei traegt UI_SESSION_SECRET seit
# W8 bereits als LEERE Zeile (Vorlage, kein Geheimnis darin) — ein reines
# `grep -q '^UI_SESSION_SECRET='` haette das faelschlich als "schon
# scharf" gelesen und nie ein Secret erzeugt. Nur die LETZTE passende
# Zeile zaehlt, falls je zwei existieren sollten.
AKTUELL="$(sed -n 's/^UI_SESSION_SECRET=//p' "$ENV_DATEI" 2>/dev/null | tail -n1 | tr -d '[:space:]')"
if [ -z "$AKTUELL" ]; then
  # Erstes Scharfschalten dieses Ladens: Secret erzeugen (nie anzeigen),
  # <laden>-ui neu aufsetzen, damit es die neue Umgebung liest.
  SECRET="$(docker exec "$MCP_CONTAINER" python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  if grep -q '^UI_SESSION_SECRET=' "$ENV_DATEI" 2>/dev/null; then
    # Die leere Vorlagen-Zeile ERSETZEN statt ein Duplikat anzuhaengen —
    # zwei Zeilen mit demselben Schluessel waeren fragil (welche zaehlt,
    # haengt von der Compose-Version ab) und schwer wieder zu finden.
    sed -i "s/^UI_SESSION_SECRET=.*/UI_SESSION_SECRET=$SECRET/" "$ENV_DATEI"
  else
    printf 'UI_SESSION_SECRET=%s\n' "$SECRET" >> "$ENV_DATEI"
  fi
  unset SECRET
  echo "UI_SESSION_SECRET gesetzt — Anmeldung wird scharf (Laden '$LADEN')."
  # shellcheck disable=SC2086
  (cd "$REPO" && docker compose $ENVARG up -d "$UI_DIENST" >/dev/null)
  echo "$LADEN-ui neu gestartet. Ab jetzt: erst anmelden, dann freigeben."
else
  echo "Anmeldung war schon scharf — Benutzer angelegt/aktualisiert (Laden '$LADEN')."
fi
