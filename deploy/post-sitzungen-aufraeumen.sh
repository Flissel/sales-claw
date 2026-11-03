#!/usr/bin/env bash
# deploy/post-sitzungen-aufraeumen.sh — loescht die Sitzungsdateien des
# Gateway-Agenten `post` (Einordnung der Post-Sammelstelle), die aelter als
# 10 Minuten sind (Ruling R17, 03.11.2026). Wiederholbar, fuer cron gedacht.
#
#   bash deploy/post-sitzungen-aufraeumen.sh            # Basis-Laden (sales-claw)
#   bash deploy/post-sitzungen-aufraeumen.sh ivan       # Laden ivan (ivan-claw)
#
# Warum: OpenClaw schreibt je Anfrage ein Protokoll nach
# <state>/agents/<agent>/sessions/<sitzung>.jsonl - fuer `post` also je
# eingeordneter Mail eine Kopie von Absender, Betreff und Text. Die Spec
# (Abschnitt 5/9) erlaubt dem Cloud-Modell, den Inhalt EINMAL zu lesen; eine
# dauerhafte Kopie im Gateway, an die der Hauptagent mit seinen
# Dateiwerkzeugen kaeme, ist nicht gedeckt.
#
# Was es tut:
#   1. im Gateway-Container: Dateien `*.jsonl*` (auch die .reset./.deleted.-
#      Kopien, die OpenClaw beim Zuruecksetzen anlegt) direkt in
#      agents/post/sessions, die laenger als 10 min nicht geaendert wurden,
#      loeschen. Eine laufende Einordnung (Sekunden) bleibt unberuehrt.
#      NICHT geloescht: sessions.json (der Index, vom Gateway laufend
#      geschrieben) und Unterordner wie skills-prompts/ (kein Mailinhalt).
#   2. `openclaw sessions cleanup --agent post --fix-missing --enforce`:
#      OpenClaw entfernt selbst die Index-Eintraege, deren Datei fehlt. Der
#      Index haelt je Sitzung nur Schluessel (agent:post:mail:<id>), Zeiten,
#      Modell und ein kurzes Label - kein Mailtext. Scheitert der Schritt,
#      bleibt es bei Schritt 1 (Meldung, kein Abbruch).
#
# Gibt nur Zahlen aus - nie Dateinamen oder Inhalte. Startet und stoppt nichts.
# Regelmaessiger Lauf (alle 5 min) steht im Runbook, Abschnitt
# Post-Sammelstelle; der Betreiber richtet ihn beim Ausrollen ein.
set +x
set -euo pipefail
export LC_ALL=C

PRAEFIX="${1:-sales}"
if ! [[ $PRAEFIX =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "Aufruf: $0 [laden-praefix]  (Kleinbuchstaben, z. B. ivan)" >&2; exit 2
fi
CONTAINER="${PRAEFIX}-claw"
ORDNER="/home/node/.openclaw/agents/post/sessions"

if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo fehlt)" != "running" ]; then
  # Laeuft das Gateway nicht, entstehen auch keine neuen Sitzungen.
  echo "post-Sitzungen: $CONTAINER laeuft nicht - nichts getan."
  exit 0
fi

# 1) Alte Sitzungsdateien loeschen; gezaehlt wird im Container, heraus kommt nur die Zahl.
ANZAHL="$(docker exec "$CONTAINER" sh -c "[ -d $ORDNER ] || { echo 0; exit 0; }; find $ORDNER -maxdepth 1 -type f -name '*.jsonl*' -mmin +10 -print -delete | wc -l")"
ANZAHL="$(printf '%s' "$ANZAHL" | tr -dc '0-9')"

# 2) Index-Eintraege ohne Datei entfernen lassen (Ausgabe nennt Sitzungsschluessel - verworfen).
if docker exec "$CONTAINER" openclaw sessions cleanup --agent post --fix-missing --enforce >/dev/null 2>&1; then
  INDEX="bereinigt"
else
  INDEX="nicht bereinigt (openclaw sessions cleanup fehlgeschlagen)"
fi
echo "post-Sitzungen: ${ANZAHL:-0} Datei(en) aelter als 10 min geloescht; Index $INDEX."
