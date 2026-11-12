#!/usr/bin/env bash
# deploy/fenster-netz-anlegen.sh
#
# Legt das interne Docker-Netz `bewerbung-fenster` an, falls es fehlt. Idempotent: existiert es und ist
# intern, passiert nichts. Existiert es, ist aber NICHT intern, bricht das Skript mit Fehler ab (exit 1).
#
# WARUM: docker-compose.fenster.yml haengt die sales-ui des Basis-Ladens als `external` an dieses
# Netz; fehlt es, scheitert jedes `up` von sales-ui laut. `--internal`: das Netz hat keinen Weg
# nach draussen, nur sales-ui und der Portal-Container (anderes Repo) sind darin. Ein vorhandenes,
# nicht internes Netz gleichen Namens wuerde dem Portal-Container (er surft auf fremden Seiten)
# den Weg nach draussen UND zu sales-ui oeffnen - deshalb wird es nicht still hingenommen.
#
# Aufrufer: deploy/update.sh (vor jedem `up` des Basis-Ladens, auch im Rueckbau),
# deploy/bootstrap.sh, deploy/benutzer-anlegen.sh (Basis-Laden), deploy/sales-ui-neu.sh. Alle nehmen
# einen Fehlschlag nicht tragisch: dann gibt es keinen Override und damit kein Fenster. Nie fuer zweite Laeden.
set -euo pipefail

if docker network inspect bewerbung-fenster >/dev/null 2>&1; then
  intern="$(docker network inspect -f '{{.Internal}}' bewerbung-fenster 2>/dev/null || true)"
  if [ "$intern" != "true" ]; then
    echo "FEHLER: Das Docker-Netz bewerbung-fenster gibt es schon, ist aber NICHT intern (Internal=${intern:-?})." >&2
    echo "  Der Portal-Container hat darin einen Weg nach draussen. Netz pruefen/entfernen und neu anlegen:" >&2
    echo "  docker network rm bewerbung-fenster && bash deploy/fenster-netz-anlegen.sh" >&2
    exit 1
  fi
else
  # Festes Subnetz: Auf offload-vm sind die Docker-Standardpools erschoepft ("all predefined
  # address pools have been fully subnetted", 12.11.2026) - ohne --subnet scheitert das Anlegen,
  # und es gaebe still kein Fenster. 10.231.43.0/24 ist dort frei und gleich dem Netz, das
  # cc-portal-abgabe am 12.11. angelegt hat; 10.231.42.0/24 gehoert dem Portal-Ausgang (bewerbung).
  docker network create --internal --subnet 10.231.43.0/24 bewerbung-fenster >/dev/null
fi
