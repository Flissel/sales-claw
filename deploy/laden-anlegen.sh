#!/usr/bin/env bash
# Einen weiteren Laden anlegen — Schale um db/laden-anlegen.sql und
# db/pruefe-laden.sql, siehe .superpowers/sdd/2026-09-16-zweiter-laden-
# getrennt/task-4-brief.md.
#
#   deploy/laden-anlegen.sh ivan 18895 8792 12786 8444
#
# Laeuft auf der VM (Debian, bash, ss, openssl, docker) — NICHT auf Windows.
#
# Was dieses Skript TUT: Namen und Ports pruefen, die Umgebungsdatei
# deploy/laeden/<name>.env erzeugen (Passwort erzeugt, nur dort
# hineingeschrieben, nie auf dem Bildschirm und nie in der Prozessliste),
# und die naechsten Schritte ausgeben.
#
# Was dieses Skript NICHT TUT: die Datenbankrolle auf der Produktion
# anlegen (dafuer braucht es die Kennung von supabase_admin, die bewusst
# nirgends im Repository liegt und am 15.09.2026 ausdruecklich nicht
# gelesen, angezeigt oder transportiert wurde) und die Container starten.
# Beides bleibt Handarbeit — die Hinweise unten nennen die Befehle.
set -euo pipefail

# Feste Locale fuer das ganze Skript: unter z.B. de_DE.UTF-8 kollationiert
# bash Bereiche wie [a-z] GROSS- und Kleinschreibung durcheinander — ein
# Name wie "Ivan" besteht die Pruefung unten dann faelschlich (gemessen).
# server.py prueft mit Pythons re-Modul, das immer ASCII-fest ist; ohne
# LC_ALL=C liefe die Bash-Pruefung hier lockerer als die, die sie
# nachbilden soll, und ein durchgerutschter Name wuerde erst beim Start
# von sales-mcp im neuen Laden auffallen.
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:?Aufruf: laden-anlegen.sh <name> <port-gateway> <port-ui> <port-openwa> <port-serve>}"
PORT_GATEWAY="${2:?}"; PORT_UI="${3:?}"; PORT_OPENWA="${4:?}"
# Fuenftes Argument, PFLICHT — kein Rueckfall, kein Raten. Das ist NICHT
# PORT_UI: PORT_UI ist der Docker-Host-Port dieses Ladens, PORT_SERVE ist
# der Port, den `sudo tailscale serve --bg --https <port> ...` spaeter von
# Hand bekommt (RUNBOOK, Abschnitt "Zugang: eigener Serve-Port"). Beide
# Zahlen sind frei waehlbar und muessen sich NICHT gleichen — im
# dokumentierten Beispiel "ivan" ist PORT_UI=8792 und der Serve-Port 8444.
# Ein Skript, das PORT_SERVE aus PORT_UI raet, hat schon einmal eine
# UI_BASIS_URL erzeugt, die still auf den falschen Port zeigte — deshalb
# hier ein Pflichtargument statt einer Ableitung.
PORT_SERVE="${5:?Aufruf: laden-anlegen.sh <name> <port-gateway> <port-ui> <port-openwa> <port-serve> — <port-serve> ist NICHT <port-ui>, sondern der spaeter frei gewaehlte Port fuer 'tailscale serve --https', siehe RUNBOOK Abschnitt 'Zugang: eigener Serve-Port'}"

# Dasselbe Muster wie SCHEMA_MUSTER in sales-mcp/server.py:87
#   SCHEMA_MUSTER = re.compile(r"sales(_[a-z][a-z0-9_]{0,30})?")
# Das dortige Muster erlaubt fuer den Teil nach "sales_" genau
# [a-z][a-z0-9_]{0,30} — und SALES_DB_SCHEMA unten wird "sales_$NAME".
# Passt NAME hier nicht auf dasselbe Muster, weist server.py das Schema
# beim Start des neuen Ladens zurueck, egal was hier durchgeht.
if ! [[ "$NAME" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "FEHLER: '$NAME' passt nicht zum Schema-Muster aus server.py" >&2
  exit 1
fi

ENVDATEI="$WURZEL/deploy/laeden/$NAME.env"
if [ -e "$ENVDATEI" ]; then
  echo "FEHLER: $ENVDATEI existiert bereits — nichts geaendert." >&2
  exit 1
fi

# Kollidierende Ports abfangen, BEVOR irgendetwas angelegt wird — nicht
# erst, wenn ein Container schon halb hochkommt. Dieselbe `ss`-Pruefung
# fuer PORT_SERVE wie fuer die anderen drei; sie fragt nur den lokalen
# Zustand dieses Rechners ab. Ob PORT_SERVE bei `tailscale serve` selbst
# schon vergeben ist, prueft `tailscale serve status` separat, von Hand
# (RUNBOOK, Abschnitt "Zugang: eigener Serve-Port") — das ist ausserhalb
# dessen, was dieses Skript ohne `tailscale`-Zugriff wissen kann.
for p in "$PORT_GATEWAY" "$PORT_UI" "$PORT_OPENWA" "$PORT_SERVE"; do
  if ss -tlnH "sport = :$p" | grep -q .; then
    echo "FEHLER: Port $p ist belegt." >&2
    exit 1
  fi
done

PASSWORT="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"

# Rechnername fuer UI_BASIS_URL unten — dasselbe Muster wie UI_TAILSCALE_IP
# oben: aus der Umgebung, mit Rueckfall, falls sie fehlt. Anders als bei der
# IP gibt es hier noch keinen "leer = nur Loopback"-Ausweg (die Mail braucht
# eine echte Adresse), deshalb faellt es auf den heute einzigen bekannten
# Rechner dieses Hauses zurueck. Ein Laden auf einer ANDEREN Maschine: vor
# dem Aufruf UI_SERVE_HOST in der Umgebung setzen.
if [ -n "${UI_SERVE_HOST:-}" ]; then
  UI_SERVE_HOST_HERKUNFT="aus der Umgebung uebernommen"
else
  UI_SERVE_HOST_HERKUNFT="GERATEN (UI_SERVE_HOST war beim Aufruf nicht gesetzt)"
fi
UI_SERVE_HOST="${UI_SERVE_HOST:-vibemind-offload-1.tail6c7d61.ts.net}"

mkdir -p "$WURZEL/deploy/laeden"
# umask VOR dem Anlegen der Datei, nicht chmod danach: so existiert kein
# Zeitfenster, in dem die Datei mit den Standardrechten (world-readable)
# daliegt. Ergebnis: -rw------- (nur der Eigentuemer liest das Passwort).
umask 077
cat > "$ENVDATEI" <<EOF
LADEN_PRAEFIX=$NAME
LADEN_PROJEKT=$NAME-claw
PORT_GATEWAY=$PORT_GATEWAY
PORT_UI=$PORT_UI
PORT_OPENWA=$PORT_OPENWA
# Schlussfix D, Punkt 6: docker-compose.yml (Dienst sales-ui) faellt ohne
# diese Zeile auf "http://127.0.0.1:12785" zurueck — den OpenWA-Port des
# ERSTEN Ladens ("sales"), nicht auf $PORT_OPENWA dieses Ladens. Gemessen an
# "ivan" (PORT_OPENWA=12786, ohne diese Zeile): die /whatsapp-Seite verlinkte
# tatsaechlich auf :12785. Deshalb hier direkt aus PORT_OPENWA abgeleitet,
# statt es der Vorgabe zu ueberlassen.
OPENWA_DASHBOARD_URL=http://127.0.0.1:$PORT_OPENWA
SALES_DB_SCHEMA=sales_$NAME
SALES_DB_URL=postgresql://sales_app_$NAME:$PASSWORT@192.168.178.65:54322/postgres
UI_TAILSCALE_IP=${UI_TAILSCALE_IP:-127.0.0.1}
# Rechnername ist $UI_SERVE_HOST_HERKUNFT (Rueckfall siehe oben). Der
# Port ist PORT_SERVE ($PORT_SERVE), das fuenfte Skript-Argument — NICHT
# PORT_UI ($PORT_UI): PORT_UI ist der Docker-Host-Port dieses Ladens,
# PORT_SERVE der spaeter frei gewaehlte Port fuer
# 'tailscale serve --https' (RUNBOOK, Abschnitt "Zugang: eigener
# Serve-Port"). Stimmt PORT_SERVE nicht mit dem tatsaechlich benutzten
# 'tailscale serve'-Aufruf fuer diesen Laden ueberein, zeigt der Link in
# der Passwort-vergessen-Mail ins Leere — vor dem ersten Versand
# gegenpruefen.
UI_BASIS_URL=https://$UI_SERVE_HOST:$PORT_SERVE
EOF

echo "Umgebungsdatei geschrieben: $ENVDATEI (nur fuer den Eigentuemer lesbar)"
echo
echo "NAECHSTER SCHRITT — von Hand, als supabase_admin auf der VM."
echo "Das Passwort steht in $ENVDATEI und wird ueber die UMGEBUNG"
echo "uebergeben (nie ueber psql -v/argv), damit es nicht in der"
echo "Prozessliste landet:"
echo
echo "  PW=\$(sed -n 's#.*sales_app_$NAME:\\([^@]*\\)@.*#\\1#p' $ENVDATEI)"
echo "  docker exec -i -e LADEN_PASSWORT=\"\$PW\" debian-supabase-db-1 \\"
echo "    psql -U supabase_admin -d postgres -v laden=$NAME \\"
echo "    < $WURZEL/db/laden-anlegen.sql"
echo "  unset PW"
echo
echo "Danach pruefen (Tor 1 der Spec — Erwartung: 1 Zahl, 2 permission"
echo "denied, 3 Zahl, 4 permission denied):"
echo
echo "  docker exec -i debian-supabase-db-1 psql \\"
echo "    \"postgresql://sales_app_$NAME:<passwort>@127.0.0.1:5432/postgres\" \\"
echo "    -v laden=$NAME < $WURZEL/db/pruefe-laden.sql"
echo
echo "Dann die Dienste starten — NIEMALS nacktes 'docker compose up -d':"
echo "das wuerde $NAME-auto mitstarten, einen Dienst, der bewusst nie"
echo "laeuft (siehe deploy/update.sh:17). Immer namentlich:"
echo
echo "ERSTER START — nur die zwei Dienste, die keine externen Zugangsdaten"
echo "brauchen (die uebrigen sieben warten auf Postfach, Telegram-Token,"
echo "LinkedIn-Zugang bzw. WhatsApp-Pairing, die es fuer '$NAME' noch"
echo "nicht gibt):"
echo
echo "  docker compose --env-file $ENVDATEI up -d --build sales-mcp sales-ui"
echo
echo "SPAETER, sobald diese Zugangsdaten vorliegen — alle neun Dienste des"
echo "Hauptstacks (weiterhin ohne $NAME-auto):"
echo
echo "  docker compose --env-file $ENVDATEI up -d --build \\"
echo "    sales-mcp sales-ui sales-inbox sales-dispatch sales-mail \\"
echo "    sales-claw sales-telegram sales-linkedin sales-stt"
echo
echo "WhatsApp (openwa) ist eine eigene Compose-Datei und braucht das"
echo "WhatsApp-Pairing (neuer QR-Code) — folgt separat, siehe Runbook-"
echo "Abschnitt 'Einen zweiten Laden anlegen':"
echo
echo "  docker compose --env-file $ENVDATEI -f docker-compose.openwa.yml \\"
echo "    up -d --build openwa"
