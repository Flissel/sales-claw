#!/usr/bin/env bash
# deploy/chat-eingang-anlegen.sh [--env-file <laden>.env]
#
# Legt im Gateway-Volume eines Ladens den Ordner media/inbound an, falls er
# fehlt (Besitzer node, 1000:1000). Idempotent: liegt er schon, passiert
# nichts.
#
# WARUM (14.10.2026): sales-mcp haengt genau diesen Unterordner nur lesend
# als /chat-eingang ein (docker-compose.yml, `volume.subpath`). Docker
# verweigert den Start eines Containers, dessen subpath im Volume nicht
# existiert — und der Gateway legt media/inbound erst an, wenn zum ersten
# Mal ein Bild im Chat ankommt (gemessen: ivan-claw-state hatte keinen).
# Ohne diesen Schritt startete sales-mcp eines solchen Ladens nicht mehr.
#
# WIE: ueber `docker compose run` des Dienstes sales-claw selbst, nicht ueber
# ein nacktes `docker run -v <praefix>-claw-state:…`. So loest Compose den
# Volume-Namen je Laden genauso auf wie fuer den Agenten (LADEN_PRAEFIX aus
# der Umgebungsdatei), und ein noch nicht vorhandenes Volume (neuer Laden)
# entsteht mit den Compose-Etiketten statt als fremdes Volume. Als root
# (0:0), weil die Wurzel eines frischen Volumes root gehoert; danach wird
# nur das NEU Angelegte an node uebergeben, Bestehendes bleibt unberuehrt.
# Kein anderer Ordner des Volumes wird gelesen oder veraendert.
#
# Aufrufer: deploy/update.sh (vor jedem `up`), deploy/admin-auftrag-
# ausfuehren.sh (neuer Laden, vor dem ersten Start), von Hand laut
# deploy/laden-anlegen.sh.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

# shellcheck disable=SC2016
docker compose "$@" run --rm --no-deps -T --user 0:0 --entrypoint sh \
  sales-claw -c '
    d=/home/node/.openclaw/media/inbound
    if [ ! -d "$d" ]; then
      neu_media=0
      [ -d /home/node/.openclaw/media ] || neu_media=1
      mkdir -p "$d"
      chown 1000:1000 "$d"
      [ "$neu_media" = 1 ] && chown 1000:1000 /home/node/.openclaw/media
      echo "chat-eingang angelegt"
    fi
    true'
