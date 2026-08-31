#!/usr/bin/env bash
# UI-Anmeldung scharf schalten / Benutzer anlegen (E1) — der Menschen-Schritt.
#
# Laeuft auf der VM als Betriebsnutzer:  bash ~/sales-claw/deploy/benutzer-anlegen.sh
# Fragt Name, Rolle und Passwort ab (Passwort unsichtbar, nie in der
# Prozessliste), legt den Benutzer in der Produktions-Tabelle an und setzt
# beim ERSTEN Mal das UI_SESSION_SECRET in die .env — ab dann verlangt die
# Oberflaeche eine Anmeldung. Derselbe Aufruf setzt auch Passwoerter zurueck.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_DATEI="$REPO/.env"

if ! docker inspect -f '{{.State.Status}}' sales-mcp 2>/dev/null | grep -qx running; then
  echo "FEHLER: Container sales-mcp laeuft nicht — erst den Stack starten." >&2
  exit 1
fi

read -r -p "Benutzername: " NAME
read -r -p "Rolle (lesen|freigeben): " ROLLE
read -r -s -p "Passwort (min. 10 Zeichen): " PASSWORT; echo
read -r -s -p "Passwort wiederholen: " PASSWORT2; echo
if [ "$PASSWORT" != "$PASSWORT2" ]; then
  echo "FEHLER: Passwoerter stimmen nicht ueberein — nichts getan." >&2
  exit 1
fi

# Passwort ueber STDIN in den Container — nie als Argument.
printf '%s' "$PASSWORT" | docker exec -i sales-mcp \
  python benutzer_anlegen.py "$NAME" "$ROLLE"
unset PASSWORT PASSWORT2

if ! grep -q '^UI_SESSION_SECRET=' "$ENV_DATEI"; then
  # Erstes Scharfschalten: Secret erzeugen (nie anzeigen), sales-ui neu
  # aufsetzen, damit es die neue Umgebung liest.
  SECRET="$(docker exec sales-mcp python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf 'UI_SESSION_SECRET=%s\n' "$SECRET" >> "$ENV_DATEI"
  unset SECRET
  echo "UI_SESSION_SECRET gesetzt — Anmeldung wird scharf."
  (cd "$REPO" && docker compose up -d sales-ui >/dev/null)
  echo "sales-ui neu gestartet. Ab jetzt: erst anmelden, dann freigeben."
else
  echo "Anmeldung war schon scharf — Benutzer angelegt/aktualisiert."
fi
