#!/usr/bin/env bash
# deploy/fenster-netz-anlegen.sh
#
# Legt das interne Docker-Netz `bewerbung-fenster` an, falls es fehlt. Idempotent: existiert es,
# passiert nichts.
#
# WARUM: docker-compose.fenster.yml haengt die sales-ui des Basis-Ladens als `external` an dieses
# Netz; fehlt es, scheitert jedes `up` von sales-ui laut. `--internal`: das Netz hat keinen Weg
# nach draussen, nur sales-ui und der Portal-Container (anderes Repo) sind darin.
#
# Aufrufer: deploy/update.sh (vor jedem `up` des Basis-Ladens, auch im Rueckbau),
# deploy/bootstrap.sh, deploy/benutzer-anlegen.sh (Basis-Laden). Nie fuer zweite Laeden.
set -euo pipefail

docker network inspect bewerbung-fenster >/dev/null 2>&1 \
  || docker network create --internal bewerbung-fenster >/dev/null
