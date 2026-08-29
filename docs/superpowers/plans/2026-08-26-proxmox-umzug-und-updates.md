# Umzug auf den MiniPC und automatisches Update-Ausrollen — Implementierungsplan

> **Für ausführende Agenten:** ERFORDERLICHE SUB-SKILL: superpowers:subagent-driven-development
> (empfohlen) oder superpowers:executing-plans, Aufgabe für Aufgabe. Schritte nutzen
> Checkbox-Syntax (`- [ ]`) zur Verfolgung.

**Ziel:** Der komplette sales-claw-Stack läuft dauerhaft auf der Proxmox-VM
`vibemind-offload-1` (VM 100, 192.168.178.65), Updates und Konfigurationen werden
mit einem Befehl (oder automatisch per Timer) aus GitHub ausgerollt, und der
Betreiber kann alles Wesentliche ohne Programmierkenntnisse bedienen.

**Architektur:** Die VM hält einen *Laufzeit-Checkout* des GitHub-Repos
(`Flissel/sales-claw`) — dort wird nie editiert, nur `ff-only` gezogen. Ein
`deploy/`-Werkzeugkasten (update, smoke, sicherung, wiederherstellen, bootstrap)
macht jeden Vorgang zu einem Befehl. Zustand (WhatsApp-Kopplungen, Allowlist,
Cron-Jobs) lebt in drei benannten Volumes und wandert per tar-Sicherung mit;
Code und Saat-Konfiguration leben in Git. Diese Grenze ist die zentrale
Design-Entscheidung (siehe „Config-Grenze" unten).

**Tech-Stack:** Docker Compose (Basis-Dateien, KEIN Proxmox-Overlay zur
Laufzeit), bash-Skripte auf der VM, systemd-Timer, PowerShell-Doppelklick-
Skripte auf dem PC, Tailscale für Handy-Zugriff.

**Spezifikation (Betreiber, 26.08.2026):** *„wir wollen automatische updates
und configs ausrollen können also den kompletten Setup migrieren können ohne
wirklichen Aufwand. […] vielleicht wäre ein OpenClaw skill für neuen
Teammember AI tools geben sinnvoll. Denke gründlich über den Proxmox umzug
nach und wie der Setup für einen Nicht-Programmierer easy zu machen ist."*

## Globale Zwänge

Gelten für JEDE Aufgabe; jede Aufgabe erbt diesen Abschnitt.

- `.env` wird niemals angezeigt oder gelesen — nur maschinelle Extraktion einzelner Variablennamen; Werte erscheinen nie in argv, Ausgaben oder Logs.
- `docker compose config` ist VERBOTEN (expandiert Secrets in die Ausgabe).
- `--remove-orphans` ist TABU (würde fremde Container des Projekts entfernen).
- Tests laufen NUR gegen das Schema `sales_test`; das Produktionsschema `sales` ist außerhalb der Werkzeuge nur lesbar.
- Niemals nacktes `docker compose up -d` ohne Dienstliste: es würde `sales-auto` starten — einen zweiten Antwortpfad neben dem Cron-Job (doppelte Antworten an echte Menschen).
- `sales-linkedin` und `sales-auto` bleiben auf `restart: "no"` — Einmal-Veröffentlicher bzw. Doppelpfad.
- Auf der VM wird nie editiert: `git merge --ff-only`, Abbruch bei schmutzigem Baum.
- Vor JEDER Arbeit an der VM: Claim in `C:\Users\User\Desktop\secondbrain\00_Meta\002_Koordination_Live.md` eintragen und committen (maschinenweite Koordination — auf der VM laufen 26 fremde Container des vibemind-Stacks).
- Konventionelle Commits, Feature-Branch `feat/stufe-1-fundament`, niemals direkt auf main.

## Gemessene Ausgangslage (alle Werte vom 26.08.2026)

| Was | Wert |
|---|---|
| Proxmox-Wirt `pve` (.64) | 16 Kerne, 30 GB RAM (15 frei), `local-lvm` 325 GB frei; SSH als root funktioniert |
| VM 100 `vibemind-offload-1` (.65) | Debian 12, 12 Kerne, 23 GB RAM (15 frei), **Platte 32 GB, nur 5,8 GB frei** |
| VM-Zugang | SSH-Alias `offload-vm`, Benutzer `debian`, sudo ohne Passwort, in `docker`-Gruppe, `growpart` vorhanden |
| VM-Platte | ext4 direkt auf `sda1` (Cloud-Image-Layout, Wurzel physisch letzte Partition) → **online vergrößerbar** |
| VM-Software | Docker 29.6.1, Compose v5.3.1, git; **kein Tailscale** |
| Datenbank | läuft bereits auf der VM (Port 54322, einer der 26 Container) |
| Repo | GitHub `Flissel/sales-claw` (privat), `gh` auf dem PC als `Flissel` angemeldet |
| Pilot-Werkzeuge | package/install (hashgeprüft), seed-volume, seed-env, migrate-credentials, backup-state, restore-state, smoke-test, preflight — alles PowerShell/Python, nie live gelaufen |
| Overlay `docker-compose.proxmox.yml` | referenziert von `scripts/package_proxmox.py`, `scripts/tests/test_package_proxmox.py`, `scripts/tests/test_proxmox_compose.py` — **bleibt bestehen, wird aber zur Laufzeit NICHT benutzt** |
| Workspace-Pfad im Gateway | `/home/node/.openclaw/workspace/AGENTS.md` (bestätigt) |
| Volumes | `openwa-data`, `sales-claw-state` (Konfig, Cron, Kanal-Kopplung), `sales-claw-keys` |
| UI-Bindung | Bereits parametrisiert: `${UI_TAILSCALE_IP:-127.0.0.1}` in der Basis, dokumentiert in `.env.example` Z. 25 — auf der VM genügt das Setzen der Variable (Befund 27.08., Aufgabe 1 entfällt) |
| PC-Stack | 7 Container gesund, WhatsApp-Session `ready`, Cron `antworten-pruefen` alle 10 Min. |

## Entscheidungen (mit Begründung)

1. **Git statt Paket-Transfer.** Der Pilot baute hashgeprüfte Pakete, weil der
   Arbeitsbaum damals schmutzig war. Heute ist er sauber und GitHub ist die
   Herkunftsquelle. Der Paket-Pfad bleibt als dokumentierter Offline-Fallback.
2. **`SALES_DB_URL` bleibt unverändert.** `192.168.178.65:54322` funktioniert
   auch aus Containern auf der VM selbst (Route über die Wirts-IP). Null
   Konfigurationsänderung, Latenz wird trotzdem lokal.
3. **VM nutzt NUR die zwei Basis-Compose-Dateien.** Die Basis trägt seit
   Commit `56d0581` Server-Politik (`unless-stopped`, `AUTO_START_SESSIONS`).
   Das Overlay würde `sales-claw` auf `restart: "no"` zurückdrehen — auf einem
   Server wäre der Bot nach jedem Reboot tot. Overlay bleibt nur für die
   Pilot-Testsuite bestehen.
4. **Tailscale auf die VM.** Löst zugleich den Handy-Zugriff des Betreibers
   („komm da nicht dran vom handy aus") und macht Updates ortsunabhängig.
   Systemeingriff auf geteilter VM → Betreiber führt den Auth-Klick selbst aus.
5. **Config-Grenze Git ↔ Volume.** Git besitzt: Code, Compose, Doku,
   `config/workspace/` (Saat, inkl. AGENTS.md). Das Volume besitzt:
   `openclaw.json` (Allowlist, Kanal-Kopplung, Cron-Jobs) und die
   WhatsApp-Profile. Ein Update spielt `config/workspace/` automatisch ein;
   Änderungen an `config/openclaw*` werden NUR GEMELDET, nie automatisch
   angewendet — sonst würde ein `git pull` die zur Laufzeit gesetzte Allowlist
   oder die Kopplung zerstören.
6. **Update-Staffelung nach gemessenen Regeln.** Runbook Z. 593 belegt:
   Rebuild von `sales-mcp` lässt `sales-claw` unberührt. Gemessene Falle: ein
   `sales-mcp`-Neustart trennt die MCP-Verbindung des Gateways
   stillschweigend → nach jedem mcp-Rebuild wird der Gateway neu gestartet
   (kurzer WhatsApp-Blip, erholt sich von selbst — heute Nacht gemessen).
7. **Updates auf Zuruf, nicht nachts (Betreiber, 27.08.2026).** Kein
   Update-Timer. Zwei Wege: der Doppelklick des Betreibers, und eine Anfrage
   an den Bot im Chat — der Bot schreibt dafür einen Auftrag in einen Spool,
   ein Wächter auf dem Wirt führt aus (Aufgabe 7b). Der Bot fasst nie selbst
   git oder docker an. Die NÄCHTLICHE SICHERUNG (04:35) bleibt; vor jedem
   Update läuft zusätzlich update.sh-intern keine eigene Sicherung — der
   Rettungsanker ist das Git-Tag `vor-update` plus die Nachtsicherung. `openwa` wird für die
   Sicherung kurz gestoppt (ein live getartes Chromium-Profil ist genau die
   Beschädigungsklasse, die die Nacht-Session gekostet hat); `sales-claw-state`
   wird live gesichert (kleine JSON/SQLite-Dateien, vertretbares Risiko).
8. **Cutover mit Session-Mitnahme-Versuch.** Die drei Volumes werden per tar
   übertragen. Beste Erwartung: beide WhatsApp-Kopplungen überleben den
   Wirtswechsel. Falls nicht: openwa per Kopplungscode
   (`POST /api/sessions/:id/pairing-code`, gemessen), OpenClaw-Kanal per QR in
   der Control-UI über Tailscale (gemessen). Beide Wege sind aus dieser Nacht
   bekannt und dokumentiert.

---

# Teil A — Fundament im Repo (auf dem PC, ohne VM-Berührung)

### Aufgabe 1: UI-Bindung parametrisieren — ENTFÄLLT (Befund 27.08.2026)

Die Prüfung vor der Umsetzung ergab: schon gebaut. Die Basis-Compose bindet
die Oberfläche an Loopback PLUS `${UI_TAILSCALE_IP:-127.0.0.1}`; der
Doppelbindungs-Randfall (Variable leer → zweimal Loopback) ist im
Compose-Kommentar ausdrücklich als erlaubt dokumentiert, die Variable steht
in `.env.example` Z. 25 und ist in der PC-.env gesetzt. Auf der VM ist damit
NUR die Variable in der .env zu setzen (Aufgabe 11, Schritt 3).
Keine Änderung nötig. smoke.sh (Aufgabe 3) liest `UI_TAILSCALE_IP`.

### Aufgabe 2: Overlay als historisch markieren

**Dateien:**
- Ändern: `docker-compose.proxmox.yml` (nur Kopfkommentar)

- [ ] **Schritt 1:** Kopfkommentar einfügen:

```yaml
# HISTORISCH: Diese Datei stammt aus dem Proxmox-Piloten (08/2026). Die
# Server-Politik (restart, AUTO_START_SESSIONS) traegt seit Commit 56d0581
# die BASIS. Zur Laufzeit auf der VM werden NUR docker-compose.yml und
# docker-compose.openwa.yml benutzt — dieses Overlay wuerde sales-claw auf
# restart "no" zuruecksetzen (Bot nach Reboot tot). Es bleibt bestehen, weil
# scripts/package_proxmox.py und zwei Testdateien es referenzieren.
```

- [ ] **Schritt 2:** Pilot-Tests laufen lassen (nur die zwei betroffenen):
  `python -m pytest scripts/tests/test_proxmox_compose.py scripts/tests/test_package_proxmox.py -q` → erwartet: grün (Kommentare ändern keine Semantik). Falls rot: Test lesen, NICHT das Overlay inhaltlich ändern.

- [ ] **Schritt 3:** Commit `docs(compose): Proxmox-Overlay als historisch markiert`.

### Aufgabe 3: `deploy/smoke.sh` — die Abnahme als ein Befehl

Läuft auf PC UND VM identisch (nur Docker-CLI + curl). Jede Prüfung ist eine
heute Nacht gemessene Kommandozeile.

**Dateien:**
- Neu: `deploy/smoke.sh`

**Schnittstellen:**
- Produziert: Exit 0 = Stack gesund, Exit >0 = Anzahl roter Prüfungen.
  Konsumiert von update.sh (Aufgabe 4), status-server.ps1 (Aufgabe 7).

- [ ] **Schritt 1:** Datei anlegen:

```bash
#!/usr/bin/env bash
# deploy/smoke.sh — Abnahme des laufenden Stacks. NUR Lesezugriffe.
# Jede Pruefung entspricht einer am 26.08.2026 gemessenen Diagnose.
# Exit 0 = gesund, sonst Anzahl roter Pruefungen.
set -uo pipefail

ROT=0
melde() { printf '%-38s %s\n' "$1" "$2"; }
fehl()  { melde "$1" "ROT: $2"; ROT=$((ROT+1)); }
gut()   { melde "$1" "ok"; }

# .env liefert UI_TAILSCALE_IP, ohne Werte anzuzeigen (nur diese eine Variable).
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIND="$(grep -E '^UI_TAILSCALE_IP=' "$WURZEL/.env" 2>/dev/null | cut -d= -f2)"
BIND="${BIND:-127.0.0.1}"

# 1) Container laufen.
for c in sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw openwa; do
  z="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo fehlt)"
  [ "$z" = "running" ] && gut "container $c" || fehl "container $c" "$z"
done

# 2) Oberflaeche antwortet.
code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://$BIND:8791/" || echo 000)"
[ "$code" = "200" ] && gut "ui http" || fehl "ui http" "HTTP $code"

# 3) Datenbank erreichbar (Produktionsschema, reine Leseabfrage).
docker exec -e SALES_DB_SCHEMA=sales sales-mcp python -c \
  "import sys;sys.path.insert(0,'/app');import server;server._q('select 1')" \
  >/dev/null 2>&1 && gut "datenbank" || fehl "datenbank" "select 1 scheitert"

# 4) Gateway kennt den MCP-Server UND hatte juengst keinen Startfehler.
docker exec sales-claw sh -c "openclaw mcp list --json 2>/dev/null" \
  | grep -q '"sales"' && gut "mcp konfiguriert" || fehl "mcp konfiguriert" "sales fehlt"
if docker logs --since 10m sales-claw 2>&1 | grep -qi "failed to start server"; then
  fehl "mcp verbindung" "Startfehler in den letzten 10 Min."
else
  gut "mcp verbindung"
fi

# 5) OpenWA-Session ist ready (der Weg zum Kunden).
s="$(docker exec sales-dispatch python -c "import os,json,urllib.request as u;q=u.Request(os.environ['OPENWA_URL']+'/api/sessions',headers={'X-Api-Key':os.environ['OPENWA_API_KEY']});print(json.loads(u.urlopen(q,timeout=20).read())[0]['status'])" 2>/dev/null || echo unerreichbar)"
[ "$s" = "ready" ] && gut "openwa session" || fehl "openwa session" "$s"

# 6) OpenClaw-Kanal: keine Abmeldung in den letzten 10 Minuten.
if docker logs --since 10m sales-claw 2>&1 | grep -qi "session logged out"; then
  fehl "whatsapp kanal" "Abmeldung in den letzten 10 Min."
else
  gut "whatsapp kanal"
fi

# 7) Der zusammengelegte Cron-Job ist aktiv (cron list zeigt nur aktive).
docker exec sales-claw sh -c "openclaw cron list 2>/dev/null" \
  | grep -q "antworten-pruefen" && gut "cron antworten-pruefen" \
  || fehl "cron antworten-pruefen" "nicht in der aktiven Liste"

# 8) AGENTS.md passt in die Bootstrap-Grenze (Falle: stille Kuerzung).
gr="$(docker exec sales-claw sh -c "wc -c < /home/node/.openclaw/workspace/AGENTS.md" 2>/dev/null || echo 0)"
max="$(docker exec sales-claw sh -c "openclaw config get agents.defaults.bootstrapMaxChars 2>/dev/null" | grep -oE '[0-9]+' | head -1)"
if [ -n "$max" ] && [ "$gr" -gt "$max" ]; then
  fehl "agents.md groesse" "$gr > bootstrapMaxChars $max — wird still gekuerzt"
else
  gut "agents.md groesse"
fi

echo "---"
[ "$ROT" -eq 0 ] && echo "ALLE PRUEFUNGEN GRUEN" || echo "$ROT PRUEFUNG(EN) ROT"
exit "$ROT"
```

- [ ] **Schritt 2:** `bash -n deploy/smoke.sh` → keine Ausgabe (Syntax sauber).
- [ ] **Schritt 3:** Auf dem PC gegen den laufenden Stack ausführen:
  `bash deploy/smoke.sh` → erwartet `ALLE PRUEFUNGEN GRUEN`, Exit 0.
  (Das ist der eigentliche Test dieser Aufgabe: das Skript muss den real
  laufenden, gesunden Stack grün melden.)
- [ ] **Schritt 4:** Eine Prüfung absichtlich brechen — `docker stop sales-mail`,
  smoke erneut → erwartet Exit 1 mit `ROT` bei sales-mail; danach
  `docker start sales-mail`, smoke → wieder grün.
- [ ] **Schritt 5:** Commit `feat(deploy): smoke.sh — Stack-Abnahme als ein Befehl`.

### Aufgabe 4: `deploy/update.sh` — der Ausrollweg

**Dateien:**
- Neu: `deploy/update.sh`

**Schnittstellen:**
- Konsumiert: `deploy/smoke.sh` (Aufgabe 3).
- Produziert: Statusdatei `~/sales-betrieb/update-status.json` mit
  `{zeitpunkt, ergebnis, von, auf, hinweis}`; `ergebnis` ∈
  {aktuell, eingespielt, rollback, notfall, fehler}. Git-Tag `vor-update`.
  Konsumiert von update-server.ps1 (Aufgabe 7) und der Betriebs-Doku.

- [ ] **Schritt 1:** Datei anlegen:

```bash
#!/usr/bin/env bash
# deploy/update.sh — spielt den Stand von origin/<aktueller Zweig> ein.
# Gestaffelt nach gemessenen Regeln, mit Rueckfahrkarte.
#
# Config-Grenze (docs/04_BETRIEB_MINIPC.md):
#   Git besitzt Code, Compose, config/workspace (Saat).
#   Das Volume besitzt openclaw.json (Allowlist, Kanaele, Cron) und die
#   WhatsApp-Kopplung — Aenderungen an config/openclaw* werden deshalb NUR
#   GEMELDET, nie automatisch angewendet.
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BETRIEB="${SALES_BETRIEB:-$HOME/sales-betrieb}"
STATUS="$BETRIEB/update-status.json"
# NIEMALS nacktes `docker compose up -d`: es wuerde sales-auto starten
# (zweiter Antwortpfad neben dem Cron-Job). Dienste immer namentlich.
KERN="sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw"

mkdir -p "$BETRIEB"
cd "$WURZEL"

status_schreiben() { # ergebnis von auf hinweis
  printf '{"zeitpunkt":"%s","ergebnis":"%s","von":"%s","auf":"%s","hinweis":"%s"}\n' \
    "$(date -Is)" "$1" "$2" "$3" "$4" > "$STATUS"
}

if [ -n "$(git status --porcelain)" ]; then
  status_schreiben fehler "-" "-" "Arbeitsbaum veraendert — auf der VM wird nicht editiert"
  echo "ABBRUCH: lokale Aenderungen im Laufzeit-Checkout (git status)." >&2
  exit 1
fi

ZWEIG="$(git rev-parse --abbrev-ref HEAD)"
ALT="$(git rev-parse HEAD)"
git fetch origin "$ZWEIG" --quiet
NEU="$(git rev-parse "origin/$ZWEIG")"

if [ "$ALT" = "$NEU" ]; then
  status_schreiben aktuell "$ALT" "$NEU" "keine Aenderung"
  echo "Bereits aktuell: $ALT"
  exit 0
fi

git tag -f vor-update "$ALT"
git merge --ff-only "origin/$ZWEIG"
GEAENDERT="$(git diff --name-only "$ALT" "$NEU")"
echo "Eingespielt $ALT -> $NEU. Geaendert:"
echo "$GEAENDERT" | sed 's/^/  /'

BAUEN=""; OPENWA_BAUEN=false; GATEWAY_NEU=false; HINWEIS=""

if echo "$GEAENDERT" | grep -qE '^sales-mcp/'; then
  BAUEN="$KERN"
  GATEWAY_NEU=true  # Gemessene Falle: sales-mcp-Neustart trennt die
                    # MCP-Verbindung des Gateways stillschweigend.
fi
if echo "$GEAENDERT" | grep -qE '^docker-compose'; then
  BAUEN="$KERN"; OPENWA_BAUEN=true
fi
if echo "$GEAENDERT" | grep -qE '^openwa/upstream/'; then
  OPENWA_BAUEN=true
fi
if echo "$GEAENDERT" | grep -qE '^config/workspace/'; then
  GATEWAY_NEU=true
fi
if echo "$GEAENDERT" | grep -qE '^config/openclaw'; then
  HINWEIS="config/openclaw geaendert: wirkt nur auf frische Volumes; laufende Instanz manuell mit 'openclaw config set' nachziehen"
  echo "HINWEIS: $HINWEIS"
fi

rueckbau() {
  echo "Smoke rot — Rueckbau auf $ALT." >&2
  git reset --hard "$ALT"
  docker compose up -d --build $KERN
  docker restart sales-claw >/dev/null
  sleep 30
  if bash "$WURZEL/deploy/smoke.sh"; then
    status_schreiben rollback "$ALT" "$NEU" "Update fehlerhaft; alter Stand laeuft wieder"
  else
    status_schreiben notfall "$ALT" "$NEU" "Rollback-Smoke ebenfalls rot — Mensch noetig"
  fi
  exit 1
}

if [ -n "$BAUEN" ]; then
  docker compose up -d --build $BAUEN
fi
if $OPENWA_BAUEN; then
  docker compose -f docker-compose.openwa.yml up -d --build openwa
fi
if echo "$GEAENDERT" | grep -qE '^config/workspace/'; then
  # Saat einspielen: Git ist Quelle der Wahrheit fuer den Workspace.
  docker cp "$WURZEL/config/workspace/." sales-claw:/home/node/.openclaw/workspace/
fi
if $GATEWAY_NEU; then
  docker restart sales-claw >/dev/null
  sleep 30   # Gateway + Kanal + MCP brauchen einen Moment (gemessen ~5-20s).
fi

bash "$WURZEL/deploy/smoke.sh" || rueckbau
status_schreiben eingespielt "$ALT" "$NEU" "${HINWEIS:-glatt durchgelaufen}"
echo "Update eingespielt und Abnahme gruen."
```

- [ ] **Schritt 2:** `bash -n deploy/update.sh` → keine Ausgabe.
- [ ] **Schritt 3:** Den Kein-Update-Pfad auf dem PC messen:
  `SALES_BETRIEB=/tmp/sales-betrieb-test bash deploy/update.sh` — auf dem PC
  ist der Checkout gleich origin (nach Push) → erwartet „Bereits aktuell",
  Exit 0, Statusdatei mit `"ergebnis":"aktuell"`. Bei schmutzigem Baum
  (der Normalfall auf dem PC vor Commits): erwartet ABBRUCH mit Exit 1 und
  `"ergebnis":"fehler"` — beide Pfade sind damit gemessen.
- [ ] **Schritt 4:** Commit `feat(deploy): update.sh — gestaffeltes Ausrollen mit Rueckfahrkarte`.
  (Der Voll-Pfad wird bewusst erst in Aufgabe 12 auf der VM gemessen.)

### Aufgabe 5: `deploy/sicherung.sh` und `deploy/wiederherstellen.sh`

**Dateien:**
- Neu: `deploy/sicherung.sh`
- Neu: `deploy/wiederherstellen.sh`

**Schnittstellen:**
- Produziert: Sicherungsordner `<ziel>/<JJJJMMTT-HHMMSS>/` mit
  `openwa-data.tar.gz`, `sales-claw-state.tar.gz`, `sales-claw-keys.tar.gz`,
  `MANIFEST.sha256`. Konsumiert vom Cutover (Aufgabe 13) und dem Timer (Aufgabe 7).

- [ ] **Schritt 1:** `deploy/sicherung.sh` anlegen:

```bash
#!/usr/bin/env bash
# deploy/sicherung.sh — sichert die drei Zustands-Volumes als tar.gz.
# openwa wird dafuer kurz gestoppt: ein live getartes Chromium-Profil ist
# genau die Beschaedigungsklasse, die am 26.08.2026 die Session gekostet
# hat. sales-claw-state wird live gesichert (kleine JSON/SQLite-Dateien).
# Rotation: die juengsten 7 Sicherungen bleiben.
set -euo pipefail

ZIEL="${1:-$HOME/sales-betrieb/sicherungen}"
STEMPEL="$(date +%Y%m%d-%H%M%S)"
ORDNER="$ZIEL/$STEMPEL"
VOLUMES="openwa-data sales-claw-state sales-claw-keys"

mkdir -p "$ORDNER"

OPENWA_LIEF=false
if [ "$(docker inspect -f '{{.State.Status}}' openwa 2>/dev/null)" = "running" ]; then
  OPENWA_LIEF=true
  docker stop openwa >/dev/null
fi
# openwa kommt am Ende IMMER wieder hoch, auch wenn tar scheitert.
trap '$OPENWA_LIEF && docker start openwa >/dev/null' EXIT

for vol in $VOLUMES; do
  docker run --rm -v "$vol":/quelle:ro -v "$ORDNER":/ziel alpine \
    tar czf "/ziel/$vol.tar.gz" -C /quelle .
done
(cd "$ORDNER" && sha256sum ./*.tar.gz > MANIFEST.sha256)

# Rotation: alles ausser den juengsten 7 Ordnern entfernen.
ls -1dt "$ZIEL"/*/ | tail -n +8 | xargs -r rm -rf

echo "Sicherung: $ORDNER"
ls -lh "$ORDNER"
```

- [ ] **Schritt 2:** `deploy/wiederherstellen.sh` anlegen:

```bash
#!/usr/bin/env bash
# deploy/wiederherstellen.sh <sicherungsordner> — stellt die drei Volumes
# aus einer Sicherung her. Verweigert die Arbeit, solange ein Dienst laeuft,
# der die Volumes benutzt: eine Wiederherstellung unter laufendem Betrieb
# hinterlaesst genau die halb geschriebenen Profile, gegen die sie helfen soll.
set -euo pipefail

QUELLE="${1:?Aufruf: wiederherstellen.sh <sicherungsordner>}"
VOLUMES="openwa-data sales-claw-state sales-claw-keys"

for c in openwa sales-claw; do
  if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" = "running" ]; then
    echo "ABBRUCH: $c laeuft. Erst stoppen: docker stop openwa sales-claw" >&2
    exit 1
  fi
done

( cd "$QUELLE" && sha256sum -c MANIFEST.sha256 )

for vol in $VOLUMES; do
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/ziel -v "$QUELLE":/quelle:ro alpine \
    sh -c "rm -rf /ziel/* /ziel/..?* /ziel/.[!.]* 2>/dev/null; tar xzf /quelle/$vol.tar.gz -C /ziel"
done

echo "Wiederhergestellt aus $QUELLE. Naechster Schritt: Dienste starten"
echo "(Reihenfolge im Cutover-Kapitel von docs/04_BETRIEB_MINIPC.md)."
```

- [ ] **Schritt 3:** `bash -n` auf beide Dateien → keine Ausgabe.
- [ ] **Schritt 4:** Rundlauf auf dem PC messen, ohne die echten Volumes anzufassen:
  `bash deploy/sicherung.sh /tmp/sicherung-test` → drei Archive + Manifest;
  `sha256sum -c` im Ordner → dreimal OK. Wiederherstellen gegen WEGWERF-Namen
  testen: das Skript einmalig mit `VOLUMES="probe-a"` im Kopf kopiert nach
  `/tmp/wh-test.sh` laufen lassen ist NICHT nötig — stattdessen genügt:
  `docker stop openwa sales-claw`, `bash deploy/wiederherstellen.sh /tmp/sicherung-test/<stempel>`,
  `docker start openwa sales-claw`, danach `bash deploy/smoke.sh` → grün.
  (Das stellt exakt den gesicherten Ist-Zustand wieder her — der einzige
  Wiederherstellungstest, der wirklich etwas beweist.)
- [ ] **Schritt 5:** Prüfen, dass die WhatsApp-Session den Rundlauf überlebt hat:
  Session-Status `ready` (smoke Prüfung 5) UND im OpenClaw-Log keine Abmeldung.
- [ ] **Schritt 6:** Commit `feat(deploy): Sicherung und Wiederherstellung der Zustands-Volumes`.

### Aufgabe 6: `deploy/bootstrap.sh` — frische Maschine zu laufendem Stack

**Dateien:**
- Neu: `deploy/bootstrap.sh`

**Schnittstellen:**
- Konsumiert: `.env` (vom Betreiber/scp bereitgestellt), Basis-Compose-Dateien.
- Produziert: gebaute Images, laufende `sales-mcp` + `sales-ui` (bewusst NUR
  die nebenwirkungsfreien Dienste — der Rest startet erst im Cutover).

- [ ] **Schritt 1:** Datei anlegen:

```bash
#!/usr/bin/env bash
# deploy/bootstrap.sh — von frischem Checkout zu laufendem Grundstack.
# Startet BEWUSST nur sales-mcp und sales-ui: alles mit Nebenwirkungen
# (openwa, sales-claw, inbox, dispatch, mail) kommt erst im Cutover, damit
# niemals zwei Standorte gleichzeitig Kundennachrichten verarbeiten.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

for werkzeug in docker git curl; do
  command -v "$werkzeug" >/dev/null || { echo "FEHLT: $werkzeug" >&2; exit 1; }
done
docker compose version >/dev/null || { echo "FEHLT: docker compose v2" >&2; exit 1; }

if [ ! -f .env ]; then
  echo "FEHLT: $WURZEL/.env — vom alten Standort per scp holen (nie per Git)." >&2
  echo "Noetig sind mindestens: SALES_DB_URL, OPENWA_API_KEY, OPENWA_SESSION_ID," >&2
  echo "INBOX_WEBHOOK_SECRET, UI_TAILSCALE_IP (Tailscale-IP dieser Maschine)." >&2
  exit 1
fi

docker volume create openwa-data >/dev/null
docker volume create sales-claw-state >/dev/null
docker volume create sales-claw-keys >/dev/null

docker compose build sales-mcp
docker compose -f docker-compose.openwa.yml build openwa
docker compose up -d sales-mcp sales-ui

echo "Grundstack laeuft. Naechste Schritte:"
echo "  1. Zustand einspielen:  deploy/wiederherstellen.sh <sicherung>"
echo "  2. Cutover-Reihenfolge: docs/04_BETRIEB_MINIPC.md"
```

- [ ] **Schritt 2:** `bash -n deploy/bootstrap.sh` → keine Ausgabe.
- [ ] **Schritt 3:** Commit `feat(deploy): bootstrap.sh — Grundstack ohne Nebenwirkungen`.
  (Voll-Messung in Aufgabe 11 auf der VM — dort IST die Maschine frisch.)

### Aufgabe 7: Timer und Doppelklick-Bedienung

Geändert am 27.08.2026: KEIN Update-Timer (Betreiber-Entscheidung — Updates
auf Zuruf). Der `sales-update.service` bleibt als manueller systemd-Einstieg
(`systemctl start sales-update`), bekommt aber keinen Timer.

**Dateien:**
- Neu: `deploy/systemd/sales-sicherung.service`
- Neu: `deploy/systemd/sales-sicherung.timer`
- Neu: `deploy/systemd/sales-update.service`
- Neu: `scripts/update-server.ps1`
- Neu: `scripts/status-server.ps1`

**Schnittstellen:**
- Konsumiert: update.sh, sicherung.sh, smoke.sh, Statusdatei aus Aufgabe 4.
- Produziert: nächtliche Sicherung (04:35) und zwei Doppelklick-Dateien
  für den Betreiber.

- [ ] **Schritt 1:** Die vier systemd-Dateien anlegen (Pfade für Benutzer
  `debian` auf der VM, per `systemctl link` aus dem Checkout):

```ini
# deploy/systemd/sales-sicherung.service
[Unit]
Description=sales-claw: naechtliche Sicherung der Zustands-Volumes

[Service]
Type=oneshot
User=debian
ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/sicherung.sh
```

```ini
# deploy/systemd/sales-sicherung.timer
[Unit]
Description=sales-claw: Sicherung taeglich 04:35

[Timer]
OnCalendar=*-*-* 04:35:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# deploy/systemd/sales-update.service
[Unit]
Description=sales-claw: Update aus GitHub einspielen
After=sales-sicherung.service

[Service]
Type=oneshot
User=debian
ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/update.sh
```

  (Ein Update-Timer wird BEWUSST nicht angelegt — Betreiber-Entscheidung
  vom 27.08.2026: Updates nur auf Zuruf.)

- [ ] **Schritt 2:** `scripts/update-server.ps1` anlegen:

```powershell
#requires -Version 7
<#
.SYNOPSIS
Doppelklick-Update: spielt auf der VM den GitHub-Stand ein und zeigt das
Ergebnis an. Fuer den Betreiber gedacht — ein Klick, eine Antwort.
#>
ssh offload-vm 'bash ~/sales-claw/deploy/update.sh'
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nUpdate in Ordnung." -ForegroundColor Green
} else {
    Write-Host "`nUPDATE MELDET EINEN FEHLER - Ausgabe oben lesen." -ForegroundColor Red
}
Read-Host "Enter zum Schliessen"
```

- [ ] **Schritt 3:** `scripts/status-server.ps1` anlegen:

```powershell
#requires -Version 7
<#
.SYNOPSIS
Doppelklick-Status: fuehrt die Abnahme (smoke.sh) auf der VM aus und zeigt
den letzten Update-Status an.
#>
ssh offload-vm 'bash ~/sales-claw/deploy/smoke.sh; echo "--- letztes Update ---"; cat ~/sales-betrieb/update-status.json 2>/dev/null'
Read-Host "Enter zum Schliessen"
```

- [ ] **Schritt 4:** Syntaxprüfung beider ps1:
  `pwsh -NoProfile -Command "[void][scriptblock]::Create((Get-Content scripts/update-server.ps1 -Raw)); [void][scriptblock]::Create((Get-Content scripts/status-server.ps1 -Raw)); 'parse ok'"` → `parse ok`.
- [ ] **Schritt 5:** Commit `feat(deploy): Timer und Doppelklick-Bedienung fuer den Betrieb`.

### Aufgabe 7b: Auftrags-Spool — Updates per Bot-Anfrage

Betreiber-Entscheidung vom 27.08.2026: „update über mich bzw bot anfragen".
Der Bot darf ein Update ANFORDERN, nie ausführen. Mechanik:

1. Der Betreiber bittet den Bot im Chat um ein Update. Nur der Betreiber
   kann das: `channels.whatsapp.allowFrom` enthält seit dem 26.08. NUR noch
   seine Nummer, `dmPolicy=allowlist` — Fremde erreichen den Bot gar nicht.
2. Der Bot ruft das MCP-Werkzeug `update_anfordern` auf. Es schreibt eine
   Auftragsdatei in den Spool `./auftraege/` (im Checkout, gitignoriert,
   als Volume in sales-mcp gemountet). Sperre: höchstens ein Auftrag alle
   10 Minuten.
3. Auf der VM wacht eine systemd-**path-Unit** über dem Spool. Sie startet
   den Ausführer `deploy/auftrag-ausfuehren.sh`, der die Datei prüft
   (bekannter Typ, jünger als 15 Minuten), `deploy/update.sh` fährt und das
   Ergebnis als `ergebnis-<stempel>.json` in den Spool zurücklegt.
4. Der Bot liest das Ergebnis über das MCP-Werkzeug `update_ergebnis` und
   meldet es dem Betreiber. Der zusammengelegte Cron-Job meldet ROTE
   Ergebnisse von sich aus (Erweiterung seines Auftragstexts).

Derselbe Spool trägt später die Allowlist-Anträge des Team-Skills (Teil C) —
gleiche Prüfkette, eigener Auftragstyp.

**Dateien:**
- Ändern: `sales-mcp/server.py` (zwei Werkzeuge: `update_anfordern`, `update_ergebnis`)
- Neu: `sales-mcp/tests/test_auftraege.py`
- Ändern: `docker-compose.yml` (Spool-Mount an sales-mcp, schreibbar)
- Ändern: `.gitignore` (`auftraege/`)
- Neu: `deploy/auftrag-ausfuehren.sh`
- Neu: `deploy/systemd/sales-auftraege.path`, `deploy/systemd/sales-auftraege.service`
- Ändern: `config/workspace/AGENTS.md` (Abschnitt: Update nur auf ausdrückliche Betreiber-Bitte)

**Schnittstellen:**
- Konsumiert: `deploy/update.sh` (Aufgabe 4), Statusdatei-Schema aus Aufgabe 4.
- Produziert: Auftragsschema `{"typ":"update","zeitpunkt":"<ISO>"}` in
  `auftraege/auftrag-<stempel>.json`; Ergebnisschema
  `{"zeitpunkt","typ","ergebnis","hinweis"}` in `auftraege/ergebnis-<stempel>.json`.

- [ ] **Schritt 1:** Tests schreiben (`test_auftraege.py`, Schema sales_test,
  Spool per `AUFTRAG_SPOOL`-Umgebungsvariable auf ein Wegwerfverzeichnis):
  Auftrag wird geschrieben; zweiter Auftrag innerhalb 10 Minuten wird
  abgelehnt; `update_ergebnis` ohne Ergebnisdatei sagt das ehrlich;
  `update_ergebnis` liefert das JÜNGSTE Ergebnis; kaputtes JSON im Spool
  bringt keinen Absturz.
- [ ] **Schritt 2:** Tests rot laufen lassen (Werkzeuge existieren nicht).
- [ ] **Schritt 3:** Werkzeuge implementieren, Tests grün.
- [ ] **Schritt 4:** Compose-Mount + .gitignore; sales-mcp neu bauen; Gateway
  neu starten (bekannte Falle: MCP-Trennung); `openclaw mcp tools` zeigt die
  zwei neuen Werkzeuge.
- [ ] **Schritt 5:** Ausführer + path-Unit schreiben (`bash -n` sauber);
  Live-Messung erst auf der VM (Aufgabe 12/13).
- [ ] **Schritt 6:** AGENTS.md-Abschnitt + Cron-Auftragstext um die
  Rote-Ergebnisse-Meldung erweitern (`openclaw cron edit`).
- [ ] **Schritt 7:** Commit.

### Aufgabe 8: Betriebs-Doku

**Dateien:**
- Neu: `docs/04_BETRIEB_MINIPC.md` — Update-Mechanik, Config-Grenze
  Git↔Volume, Cutover-Reihenfolge (aus Aufgabe 13, dort verbindlich),
  Rollback (`git reset --hard vor-update` + Rebuild), Sicherungs-/Timer-Plan,
  Tailscale-Adressen.
- Neu: `docs/05_BEDIENUNG.md` — die Fünf Handgriffe für Nicht-Programmierer:

| Handgriff | Wie |
|---|---|
| Geht es dem System gut? | Doppelklick `status-server.ps1` — alles „ok" = ja |
| Update einspielen | Doppelklick `update-server.ps1` (nachts passiert es ohnehin automatisch) |
| Oberfläche öffnen | `http://<VM-Tailscale-IP>:8791` — auch vom Handy |
| Etwas ist kaputt | Doppelklick `status-server.ps1`, rote Zeile(n) an Claude geben |
| Notfall-Rollback | In `docs/04` Kapitel „Rückfahrkarte" — zwei Befehle zum Kopieren |

- [ ] **Schritt 1:** Beide Dateien schreiben (Inhalte aus diesem Plan übernehmen,
  Cutover-Kapitel aus Aufgabe 13 spiegeln, Tailscale-IP nach Aufgabe 10 eintragen).
- [ ] **Schritt 2:** Querverweis am Ende von `docs/03_RUNBOOK.md` ergänzen:
  eine Zeile „Betrieb auf dem MiniPC: siehe docs/04_BETRIEB_MINIPC.md".
- [ ] **Schritt 3:** Commit `docs: Betrieb auf dem MiniPC und Bedienung fuer Menschen`.
- [ ] **Schritt 4:** Branch pushen: `git push -u origin feat/stufe-1-fundament`
  (Voraussetzung für alles Weitere — die VM zieht von GitHub).

---

# Teil B — VM und Cutover (Betreiber anwesend, ca. 45–60 Min.)

### Aufgabe 9: Koordination claimen, dann Platte vergrößern (online)

- [ ] **Schritt 1:** Claim eintragen in
  `C:\Users\User\Desktop\secondbrain\00_Meta\002_Koordination_Live.md`:
  „sales-claw-Umzug auf vibemind-offload-1 (VM 100): Platte +50G, Tailscale,
  Stack-Aufbau — <Datum>" und sofort committen. Bei fremdem aktivem Claim
  auf der VM: STOPP, Betreiber fragen.
- [ ] **Schritt 2:** Plattennamen der VM feststellen:
  `ssh pve 'qm config 100 | grep -E "^(scsi|virtio|sata|ide)[0-9]"'` —
  erwartet eine Zeile wie `scsi0: local-lvm:vm-100-disk-0,size=32G`.
- [ ] **Schritt 3:** Vergrößern (Name aus Schritt 2 einsetzen):
  `ssh pve 'qm resize 100 scsi0 +50G'` → kein Fehler.
- [ ] **Schritt 4:** In der VM nachziehen:
  `ssh offload-vm 'sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1 && df -h /'`
  → erwartet: `/` jetzt ≈ 81G, ≈ 75G frei. Kein Reboot nötig (ext4, online).

### Aufgabe 10: Tailscale auf der VM (Betreiber klickt den Auth-Link)

- [ ] **Schritt 1:** Installation nach offizieller Debian-12-Anleitung
  (Paketquelle von pkgs.tailscale.com einrichten, `sudo apt-get install tailscale`).
  Systemeingriff auf geteilter VM — nur mit dem Claim aus Aufgabe 9.
- [ ] **Schritt 2:** `ssh offload-vm 'sudo tailscale up'` — gibt einen
  Anmelde-Link aus; **der Betreiber öffnet ihn im Browser und bestätigt**.
- [ ] **Schritt 3:** `ssh offload-vm 'tailscale ip -4'` → die neue VM-Tailscale-IP
  notieren; sie wird `UI_TAILSCALE_IP` auf der VM und gehört in `docs/05_BEDIENUNG.md`.

### Aufgabe 11: Stack ohne Nebenwirkungen aufsetzen

- [ ] **Schritt 1:** Deploy-Key erzeugen und bei GitHub eintragen:
  `ssh offload-vm 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/sales-claw-deploy -C sales-claw-vm'`
  dann vom PC: `ssh offload-vm 'cat ~/.ssh/sales-claw-deploy.pub' | gh repo deploy-key add - --repo Flissel/sales-claw --title "vibemind-offload-1 (nur lesen)"`
  (gh ist als Flissel angemeldet — gemessen). Auf der VM in `~/.ssh/config`:

```
Host github.com-sales
    HostName github.com
    IdentityFile ~/.ssh/sales-claw-deploy
```

- [ ] **Schritt 2:** Klonen und Zweig auschecken:
  `ssh offload-vm 'git clone git@github.com-sales:Flissel/sales-claw.git ~/sales-claw && cd ~/sales-claw && git checkout feat/stufe-1-fundament'`
- [ ] **Schritt 3:** `.env` übertragen (Secrets nie durch Git):
  `scp "C:/Users/User/Desktop/Sabine/sales-claw/.env" offload-vm:~/sales-claw/.env`
  danach auf der VM NUR die eine Zeile anpassen, ohne Werte anzuzeigen:
  `ssh offload-vm 'cd ~/sales-claw && grep -q "^UI_TAILSCALE_IP=" .env && sed -i "s/^UI_TAILSCALE_IP=.*/UI_TAILSCALE_IP=<VM-Tailscale-IP>/" .env || echo "UI_TAILSCALE_IP=<VM-Tailscale-IP>" >> .env'`
- [ ] **Schritt 4:** `ssh offload-vm 'bash ~/sales-claw/deploy/bootstrap.sh'`
  → baut, startet sales-mcp + sales-ui. Erwartet: die zwei genannten
  Abschlusszeilen des Skripts.
- [ ] **Schritt 5:** Teil-Abnahme: `curl` von PC ODER Handy auf
  `http://<VM-Tailscale-IP>:8791/` → HTTP 200. (Der volle smoke ist hier
  noch rot — dispatch/inbox/claw/openwa laufen absichtlich nicht.)

### Aufgabe 12: Update-Pfad LIVE beweisen (vor dem Cutover)

Der Umzug ist zugleich der erste echte Test der Update-Maschinerie —
in genau dieser Reihenfolge, solange noch kein Kundenverkehr auf der VM liegt.

- [ ] **Schritt 1:** Auf dem PC eine triviale Änderung committen und pushen
  (z. B. Datumszeile in `docs/04_BETRIEB_MINIPC.md`).
- [ ] **Schritt 2:** `ssh offload-vm 'bash ~/sales-claw/deploy/update.sh'`
  → erwartet: „Eingespielt <alt> -> <neu>", Abnahme läuft; die Prüfungen
  für dispatch/inbox/claw/openwa sind ROT (laufen noch nicht) — das ist hier
  korrekt und beweist zugleich, dass smoke ehrlich misst. Statusdatei zeigt
  `"ergebnis":"rollback"` — auch der Rückbau wird damit einmal LIVE gemessen:
  danach steht der Checkout wieder auf <alt> (`git log -1`).
- [ ] **Schritt 3:** Befund festhalten: Update-Mechanik UND Rückfahrkarte je
  einmal live durchlaufen. (Nach dem Cutover, wenn alles läuft, wird
  Schritt 1–2 wiederholt und endet dann grün mit `"ergebnis":"eingespielt"`.)

### Aufgabe 13: Cutover — die verbindliche Reihenfolge

Kundenwirkung: WhatsApp-Bot ist ca. 10–20 Minuten still. Das Handy-WhatsApp
des Betreibers läuft die ganze Zeit normal weiter — nur der Assistent pausiert.

- [ ] **Schritt 1:** PC: frische Sicherung: `bash deploy/sicherung.sh` (Git Bash).
- [ ] **Schritt 2:** PC: geordnet stoppen (Gnadenfristen wirken lassen):
  `docker compose stop && docker compose -f docker-compose.openwa.yml stop`
  Ab jetzt verarbeitet NIEMAND Kundennachrichten — genau eine Seite darf leben.
- [ ] **Schritt 3:** Sicherung zur VM: `scp -r <sicherungsordner> offload-vm:~/sales-betrieb/umzug/`
- [ ] **Schritt 4:** VM: `bash ~/sales-claw/deploy/wiederherstellen.sh ~/sales-betrieb/umzug/<stempel>`
  (verweigert von selbst, falls openwa/sales-claw liefen).
- [ ] **Schritt 5:** VM: `docker compose -f ~/sales-claw/docker-compose.openwa.yml up -d openwa`
  — dann Session-Status abfragen (smoke Prüfung 5 einzeln). `ready` =
  die Kopplung hat den Wirtswechsel überlebt. Falls `qr_ready`: Kopplungscode
  anfordern (`POST /api/sessions/<id>/pairing-code`, Ablauf in docs/03,
  gemessen am 26.08.) und der Betreiber tippt ihn am Handy ein.
- [ ] **Schritt 6:** VM: `docker compose up -d sales-claw` — Kanalstatus im Log:
  `Listening for WhatsApp inbound` = Kopplung überlebt. Falls
  `session logged out`: Control-UI über `http://<VM-Tailscale-IP>:18894`
  öffnen (Token-Übergabe wie in docs/03), „Erneut verknüpfen" → QR im
  PC-Browser anzeigen, Betreiber scannt (gemessener Ablauf vom 26.08.).
- [ ] **Schritt 7:** VM: `docker compose up -d sales-inbox sales-dispatch sales-mail sales-ui sales-mcp`
- [ ] **Schritt 8:** VM: `bash ~/sales-claw/deploy/smoke.sh` → ALLE GRUEN.
- [ ] **Schritt 9:** Der Beweis, der heute Nacht fehlte: von einer ZWEITEN
  Nummer (nicht der Betreiber-Nummer) eine WhatsApp an die Bot-Nummer
  schicken → in der Datenbank erscheint eine `kundenantwort`-Zeile und der
  Posteingang zeigt sie. Erst dieser Schritt beweist die Eingangsrichtung.
- [ ] **Schritt 10:** Cron prüfen: `openclaw cron list` zeigt
  `antworten-pruefen` (kam im Volume mit); einen manuellen Lauf anstoßen
  und das Laufprotokoll lesen.
- [ ] **Schritt 10b:** Den Tagespost-Takt aktivieren (Betreiber-Kadenz
  vom 27.08.: EIN LinkedIn-Beitrag pro Tag, 09:00; bis zum Cutover
  bewusst deaktiviert, weil der Wächter fehlt):
  `openclaw cron edit 3d4f456e-1502-4f90-9a1c-417a8d1e3e69 --enable`
- [ ] **Schritt 11:** Sicherungs-Timer und Auftrags-Wächter scharf schalten
  (KEIN Update-Timer — Betreiber-Entscheidung):
  `ssh offload-vm 'sudo systemctl link ~/sales-claw/deploy/systemd/sales-sicherung.service ~/sales-claw/deploy/systemd/sales-sicherung.timer ~/sales-claw/deploy/systemd/sales-update.service ~/sales-claw/deploy/systemd/sales-auftraege.path ~/sales-claw/deploy/systemd/sales-auftraege.service && sudo systemctl enable --now sales-sicherung.timer sales-auftraege.path && systemctl list-timers | grep sales'`
- [ ] **Schritt 12:** Update-Pfad im Endzustand messen (Wiederholung aus
  Aufgabe 12, jetzt grün erwartet): trivialer Commit + Push auf dem PC,
  `update-server.ps1` doppelklicken → `"ergebnis":"eingespielt"`.

### Aufgabe 14: Beobachtung und Rückbau

- [ ] **Schritt 1:** 7 Tage Parallel-Bereitschaft: der PC-Stack bleibt
  GESTOPPT aber intakt (Rückfahrkarte: `docker compose start` auf dem PC —
  vorher zwingend die VM-Seite stoppen, niemals beide).
- [ ] **Schritt 2:** Nach 7 unauffälligen Tagen: PC-Container entfernen
  (`docker compose down` OHNE `-v` — Volumes bleiben weitere 30 Tage als
  Kaltreserve), Koordinations-Claim austragen und committen.
- [ ] **Schritt 3:** `docs/05_BEDIENUNG.md` final prüfen (stimmen alle
  Adressen?), `lessons.md` um die Umzugs-Erkenntnisse ergänzen.

---

# Teil D — OpenWA-Ausbau (nach dem Cutover, Betreiber-Auftrag 27.08.2026)

Vermessene Grundlage: 191 API-Routen (Routenkarte im Scratchpad erhoben,
Kategorien: messages 27, groups 22, contacts 11, chats 9, status 8,
labels 8, templates 5, automation-rules 5, presence 3, catalog 3).
Reihenfolge nach Hebel; ALLES landet erst nach dem Cutover auf der VM,
weil die Auftrags-Spool-Wege den systemd-Wächter brauchen.

**Zwei Routen sind ausdrücklich TABU:** `automation-rules` (wäre ein
DRITTER Antwortpfad neben Cron und sales-auto — die Doppel-Antwort-Falle)
und `send-bulk` (Massenversand: WhatsApp-Sperr-Risiko plus rechtlich
heikel ohne Einwilligung).

### Aufgabe D1: Chat-Historie importieren — der Hebel

Die Kontaktprofile sehen heute nur Nachrichten seit Inbetriebnahme des
Posteingangs. `GET /api/sessions/:id/messages/:chatId/history` kann die
Vorgeschichte je Kontakt nachladen — danach speisen sich Profile aus dem
GANZEN Verlauf.

**Dateien:** Neu `sales-mcp/history_import.py` (Einmal-Läufer nach dem
Muster des LinkedIn-Versenders: expliziter Start, genau ein Kontakt je
Lauf); neu Auftragstyp `historie` im Spool (Werkzeug
`historie_import_anfordern(lead_id)`, Wächter-Zweig); Tests
`test_history_import.py`.

- [ ] **Schritt 1 — MESSUNG zuerst:** die History-Route an einem eigenen
  Chat abrufen (aus sales-dispatch, wie alle OpenWA-Messungen): welche
  Parameter (limit? cursor?), welche Felder je Nachricht (id, timestamp,
  fromMe, body, type), wie weit zurück reicht sie. Ergebnis als
  Kommentar in history_import.py festhalten.
- [ ] **Schritt 2 — Dedup-Vertrag:** importiert wird NUR, was es noch
  nicht gibt — Abgleich über `payload->>'message_id'` gegen die
  vorhandenen activities des Leads. Ein zweiter Lauf desselben Kontakts
  muss 0 neue Zeilen schreiben (Test).
- [ ] **Schritt 3 — Zeitwahrheit:** der Original-Zeitstempel steht als
  `gesendet_am` im payload; ob `created_at` beim INSERT setzbar ist,
  wird GEMESSEN (append-only-Rolle) — wenn nein, bleibt created_at die
  Importzeit und die Auswertungen lesen `gesendet_am`.
- [ ] **Schritt 4:** Import löst den bestehenden Profil-Takt aus
  (PROFIL_SCHWELLE zählt neue Nachrichten) — nach dem Import entsteht
  das Profil von selbst. Test: Import von N>=5 Nachrichten macht den
  Kontakt profil-fällig.
- [ ] **Schritt 5:** Spool-Anbindung (Typ `historie`, payload lead_id +
  chat_kennung), Wächter-Zweig, AGENTS.md-Absatz (nur auf
  Betreiber-Bitte, je Kontakt), Tests, Commit.

### Aufgabe D2: Terminfindung per Umfrage (`send-poll`)

Drei Terminvorschläge als antippbare Umfrage statt Hin-und-her-Getippe.
Bleibt im Drei-Tore-Modell: Werkzeug `terminumfrage_entwerfen(lead_id,
frage, optionen)` erzeugt einen ENTWURF (Markierung im subject,
Optionen als JSON im body), der Betreiber gibt frei, sales-dispatch
erkennt die Markierung und ruft send-poll statt send-text.

- [ ] **Schritt 1 — MESSUNG:** wie kommen Umfrage-Antworten zurück?
  (Webhook-Ereignistyp an einem Selbsttest messen; erst danach wird der
  Rückkanal — Antwort ins activities-Protokoll — gebaut.)
- [ ] **Schritt 2:** Entwurfs-Format + dispatch-Zweig + Tests (Entwurf
  ohne Freigabe sendet nie; kaputtes Options-JSON scheitert im
  Entwurf, nie erst beim Senden).
- [ ] **Schritt 3:** Rückkanal: eingehende Umfrage-Stimme wird
  `kundenantwort` mit Verweis auf die Umfrage. Wiedervorlage-Vorschlag,
  wenn nach 48h keine Stimme kam.

### Aufgabe D3: WhatsApp-Status als Kanal (`status/send-video`)

Produktvideos zusätzlich als Status — gleiche Zwei-Tore-Mechanik wie
LinkedIn: Entwurf (channel `whatsapp-status`, recipient `status`) →
Freigabe → Spool-Auftrag Typ `status` → Wächter startet den
Einmal-Versender. Wiederverwendet den LinkedIn-Entwurfsfluss samt
Historie/Schablonen-Gedanke (ein Status pro Tag höchstens).

- [ ] **Schritt 1:** Einmal-Versender `status_dispatch.py` nach dem
  LinkedIn-Muster (exakte Entwurfs-ID, Ausgangszeile, Nachweis in
  activities). Schritt 2: Spool-Typ + Wächter-Zweig + Tests. Schritt 3:
  AGENTS.md-Absatz.

### Aufgabe D4–D6: Politur-Paket (je klein, nach D1–D3)

- **D4 Labels als CRM-Spiegel:** Autonomiestufe/Archiv-Zustand als
  Chat-Label auf dem Handy sichtbar. MESSUNG zuerst: Labels setzen
  braucht ein WhatsApp-Business-Konto — ist das Konto eines? Können
  Labels per API erzeugt werden oder nur zugewiesen? Danach: Abgleich im
  dispatch-Takt aus dem leads-Zustand.
- **D5 Lesen + Tippen:** sales-dispatch setzt unmittelbar vor einer
  Auto-Antwort `chats/read` und `chats/typing` — gelesen wird erst
  markiert, wenn wirklich geantwortet wird (ein „gelesen, keine
  Antwort" wäre schlechter als gar kein Haken).
- **D6 Archiv-Symmetrie:** `kontakt_archivieren` schreibt schon eine
  activity — sales-dispatch greift sie auf und archiviert den Chat per
  `chats/archive`. Kein neuer Schreibweg, das Protokoll bleibt die
  einzige Quelle.

### Vorgemerkt (Betreiber, 27.08.2026): LinkedIn-Reaktionen beantworten

Kommentare/Reaktionen lesen und beantworten braucht LinkedIns
Partner-Programm (Community-Management-API, auf Unternehmensseiten
zugeschnitten; 3–4 Monate Verfahren, Zusage ungewiss). Weg, wenn es
soweit ist: Company Page (Fin2gether/VibeMind) als Absender der Serie,
Partner-Antrag ueber die registrierte App, danach Kommentar → Entwurf →
Freigabe wie ueberall. KEINE Scraper/Browser-Automatisierung auf dem
Privatprofil (Sperr-Risiko trifft die ganze Serie).

### Reihenfolge des Gesamtvorhabens (Stand 27.08.2026)

0. **P1 Pipeline + P2 DSGVO** — sofort baubar, kein VM-Bezug.
1. **Teil B — Umzug** (braucht den Betreiber, ~1h). Alles Weitere setzt
   den systemd-Wächter der VM voraus.
2. **D1 Historie-Import** — füttert Profile und damit alles andere.
3. **D2 Terminumfrage** — der sichtbarste Vertriebsnutzen.
4. **D3 Status-Kanal** — Marketing-Zweitverwertung der Videos.
5. **Teil E — Team-Schicht** (E1 Login → E2 Besitzer → E3 Münder → E4
   Onboarding-Skill).
6. **D4–D6 Politur** — klein, unabhängig, in beliebiger Reihenfolge.

# Teil E — Die Team-Schicht (Betreiber-Entscheid 27.08.2026: „go")

**Architektur, beschlossen:** EIN zentraler Bot (ein Gateway, ein Gehirn,
eine Datenbank), je Berater ein eigener WhatsApp-Mund (eigene Nummer als
eigene OpenWA-Session im selben Container). Vertraulichkeit zwischen
Beratern über die ohnehin isolierten DM-Sessions des Gateways plus das
Besitzer-Feld. Ein Bot pro Berater wurde verworfen: Kosten und Pflege
×Teamgröße (allein der Prüf-Takt kostet ~327k Tokens je Lauf, gemessen),
kein geteiltes Wissen. **Offen benannte Grenze:** die Werkzeug-Ebene
erzwingt die Besitzer-Filterung anfangs per AGENTS.md-Anweisung, nicht
hart — harte Identitäten je Berater sind eine spätere Stufe und stehen
hier ehrlich als solche.

Schema-Änderungen laufen als Migrationsdateien unter `db/` und werden
beim Ausrollen von einem MENSCHEN mit der Owner-Rolle eingespielt — die
Produktions-Rolle der Dienste bleibt ohne DDL, `activities` bleibt
append-only.

## Vorgezogen, weil sofort nützlich (kein VM-Bezug — baubar ab jetzt)

### Aufgabe P1: Die Pipeline zum Leben erwecken

Befund 27.08.2026: `leads.status` existiert (samt `score`,
`score_breakdown`), aber alle 34 Leads stehen auf `new` — kein Werkzeug
bewegt je ein Stadium.

**Dateien:** `sales-mcp/server.py` (Werkzeug `kontakt_stufe_setzen`,
Stufen-Konstante), `sales-mcp/ui.py` (Spaltenansicht `/pipeline`,
Stufen-Auswahl in der Kontaktkarte), `sales-mcp/tests/test_pipeline.py`,
AGENTS.md-Abschnitt, Digest-Erweiterung.

- [ ] Stufen-Vertrag: `PIPELINE_STUFEN = ("neu", "kontaktiert", "termin",
  "angebot", "abgeschlossen", "verloren")`; der Alt-Wert `new` wird beim
  Lesen als `neu` gedeutet, geschrieben wird nur noch der neue Satz.
- [ ] Werkzeug `kontakt_stufe_setzen(lead_id, stufe, begruendung)`:
  validiert gegen den Vertrag, schreibt `leads.status` UND eine
  `activities`-Zeile Typ `stufenwechsel` (von, nach, begruendung) — jeder
  Wechsel ist Beweis, kein stiller Feldschreiber. Rueckwaertsgaenge sind
  erlaubt, aber die Begruendung ist PFLICHT.
- [ ] AGENTS.md: der Bot SCHLAEGT Stufenwechsel aus dem Gespraechsverlauf
  vor (Termin vereinbart -> `termin`), setzt sie mit Begruendung und
  nennt sie dem Betreiber im Digest; er erfindet keine Abschluesse —
  `abgeschlossen`/`verloren` nur, wenn der Verlauf es woertlich hergibt
  oder der Betreiber es sagt.
- [ ] UI `/pipeline`: sechs Spalten, je Kontakt Karte mit Wartezeit seit
  letztem Kundenkontakt; Digest zaehlt je Stufe.
- [ ] Tests: Vertrag (nur gueltige Stufen), Beweiszeile, Alt-Wert-Deutung,
  UI-Rendering. Volle Suite, Abnahme, Commit.

### Aufgabe P2: DSGVO-Handwerk (Auskunft und Loeschweg)

- [ ] `kontakt_auskunft(lead_id)`: vollstaendiger Export aller Daten
  eines Kontakts (Stammdaten, enrichment, alle activities, Entwuerfe)
  als Markdown-Report nach `/reports` — der Art.-15-Antwortentwurf.
- [ ] `loeschantrag_vermerken(lead_id, quelle)`: markiert den Kontakt
  (enrichment `_loeschantrag` mit Datum/Quelle), archiviert ihn und
  STOPPT jede weitere Verarbeitung (antworten_faellig/Profile lassen
  markierte Kontakte aus — Tests). Die physische Loeschung bleibt
  BEWUSST ohne Werkzeug: sie laeuft als dokumentierter Runbook-Schritt
  (`docs/06_DSGVO.md`) mit der Owner-Rolle, Vier-Augen, Frist 30 Tage.
- [ ] `docs/06_DSGVO.md`: beide Ablaeufe, Zustaendigkeit, Fristen.

### Aufgabe P3: Privat-Markierung (geplant 29.08.2026 — schaerfer als ignorieren)

Befund am 29.08.: `ignorieren` filterte nur das Antworten; Profile und
Chat-Reports liefen fuer ignorierte (auch private) Kontakte weiter. Die
Faelligkeitslisten sind seit dem 29.08. gefiltert (tests/
test_ignorieren.py), gespeichert wird aber weiterhin ALLES. P3 ist die
Stufe darueber fuer echte Privat-Kontakte (z. B. Lisa):

* Markierung `_privat` je Kontakt (`kontakt_privat_setzen`, nur
  Betreiber, Mechanik wie Archiv: Vermerk + Beweiszeile).
* **sales-inbox speichert fuer private Kontakte KEINEN Inhalt** —
  Datensparsamkeit statt Filterung: was nie gespeichert wurde, kann
  nirgends auftauchen. (Empfehlung: gar keine Zeile, auch kein Zaehler;
  der Kontakt ist dem System dann schlicht still.)
* `chat_verlauf`, Profile, Reports, Auskunftsexport: verweigern mit
  klarem Hinweis „privat markiert".
* Der Historie-Import (D1) respektiert die Markierung.
* UI: Schloss in der Kontaktliste; setzen/entziehen mit Bestaetigung.

Offene Betreiber-Entscheidung: was passiert mit BEREITS gespeicherten
Inhalten eines neu privat markierten Kontakts — behalten (ab jetzt
still) oder Loeschung nach dem DSGVO-Runbook (docs/06)? Kein VM-Bezug,
baubar jederzeit auf Zuruf.

## Die Team-Stufe selbst (nach Umzug und D1)

### Aufgabe E1: UI-Anmeldung mit zwei Rollen

**Dateien:** `db/00X_team.sql` (Tabelle `benutzer`: name, rolle
lesen|freigeben, passwort_hash, aktiv), `sales-mcp/ui.py` (Login-Seite,
signierter Sitzungs-Cookie mit Secret aus `.env`, Rollen-Pruefung an
JEDEM Freigabe-/Schreib-POST), Tests.

- [ ] Migration schreiben; Einspielen dokumentiert als Menschen-Schritt.
- [ ] Login/Logout, Cookie signiert (Secret `UI_SESSION_SECRET` in .env,
  nie im Log), Fehlversuche gebremst.
- [ ] Rolle `lesen`: alle Seiten sichtbar, jeder verändernde POST wird
  abgelehnt. Rolle `freigeben`: wie heute. Tests fuer BEIDE Richtungen.
- [ ] Freigaben tragen kuenftig `approved_by=<benutzername>` statt
  pauschal `betreiber` — wer freigab, steht im Beweis.

### Aufgabe E2: Besitzer-Feld

- [ ] Migration: `leads.berater text` (null = Betreiber). Vergabe in der
  Kontaktkarte und bei der Einordnung; `kontakt_stufe_setzen` und Digest
  filtern optional je Berater.
- [ ] Zuordnung Berater-Handynummer -> Benutzername als Konfigdatei
  (`config/berater.json`, via Git ausgerollt): der Bot erkennt am
  DM-Absender, WER fragt, und haelt sich per AGENTS.md an dessen
  Kontakte. (Die weiche Grenze von oben — hier verankert.)

### Aufgabe E3: Mehrere WhatsApp-Muender

- [ ] MESSUNG zuerst: zweite OpenWA-Session anlegen (Testnummer),
  pruefen, wie der Webhook die Session kennzeichnet und ob
  AUTO_START_SESSIONS alle Sessions startet.
- [ ] `sales-inbox` schreibt die Session-Kennung in jede activity;
  Einordnung nutzt sie fuer den Besitzer-Vorschlag.
- [ ] `sales-dispatch` waehlt die Versand-Session nach `lead.berater`
  ueber `config/berater.json`; ohne Zuordnung wie heute die Hauptnummer.
- [ ] Kopplungs-Runbook je neuer Nummer (Pairing-Code-Ablauf ist
  gemessen und dokumentiert).

### Aufgabe E4: Onboarding-/Offboarding-Skill (ersetzt Teil C)

- [ ] Workspace-Skill `team-onboarding`: auf „richte <Name> ein" sammelt
  der Bot Name/Nummer/Rolle, erzeugt den Begruessungs-Entwurf und nennt
  dem Betreiber die MENSCHEN-Schritte als Checkliste: benutzer-Zeile
  einspielen (Doppelklick `scripts/berater-anlegen.ps1`, fragt Name +
  Rolle + Passwort ab), Nummer in `channels.whatsapp.allowFrom`,
  `config/berater.json`-Eintrag committen. Der Bot erweitert NIEMALS
  selbst Zugriffslisten oder Benutzerkonten.
- [ ] Offboarding: `benutzer.aktiv=false` (Login tot), Kontakte per
  `uebergabe_erstellen` an einen Kollegen, Nummer aus allowFrom.
- [ ] Tests fuer berater-anlegen.ps1 (Parse), Skill-Sichtbarkeit.

# Teil C — AUFGEGANGEN in Teil E (27.08.2026)

Die drei Zuschnitt-Fragen sind beantwortet: zentraler Bot mit eigenen
Nummern je Berater (Teil E), Rollen lesen/freigeben (E1), Offboarding ja
(E4). Der urspruengliche Entwurf bleibt unten als Herkunft stehen.

## Ursprünglicher Spezifikationsentwurf (historisch)

**Noch KEINE Aufgaben** — erst nach den Antworten des Betreibers (unten) wird
daraus ein eigener Plan. Der Rahmen, damit die Richtung steht:

OpenClaw hat ein Skill-System (`openclaw skills`, gemessen); eigene Skills
gehören in den Workspace (`/home/node/.openclaw/workspace/skills/…`) und
wandern damit über die bestehende Update-Maschinerie (`config/workspace/` in
Git → `docker cp` beim Update). **Ein neuer Skill ist damit ein normaler
Git-Commit — genau das gewünschte „Configs ausrollen".**

Entwurf `skills/team-onboarding/SKILL.md`: Wenn der Betreiber schreibt
„richte <Name> mit <Nummer> ein", führt der Bot:
1. Kontakt per MCP anlegen (`kontakt_anlegen`), Autonomie auf `manuell`
   (die sichere Vorgabe für interne Nummern),
2. Begrüßungs-Entwurf mit Zustimmungsfrage erzeugen (durch die Freigabe wie
   jede Nachricht — Tor-Prinzip bleibt),
3. dem Betreiber den EINEN Schritt nennen, den nur ein Mensch tun darf:
   die Nummer in `channels.whatsapp.allowFrom` eintragen (der Bot darf seine
   eigene Zugriffsliste nicht erweitern — dieselbe Klasse Regel wie „der
   Agent erreicht niemals approved von selbst").

**Offene Fragen an den Betreiber (bestimmen den Zuschnitt):**
- Was genau soll ein neues Teammitglied bekommen — Zugriff auf den
  WhatsApp-Assistenten? Die Weboberfläche (dann braucht sie erstmals
  Benutzerkonten!)? Eigene MCP-Werkzeuge?
- Dürfen Teammitglieder nur lesen (Posteingang, Profile) oder auch freigeben?
  Freigabe durch Dritte verändert das Ein-Betreiber-Modell der drei Tore.
- Soll der Skill auch das Entfernen können (Offboarding)?

---

## Offene Fragen an den Betreiber

Beantwortet am 27.08.2026: Tailscale JA · Updates auf Zuruf (Betreiber oder
Bot-Anfrage → Aufgabe 7b) · Allowlist nur auf Anfrage, Eintrag durch Menschen.

Noch offen (Stand 27.08.2026 — Team-Zuschnitt ist entschieden, siehe Teil E):

1. **Cutover-Termin**: 45–60 Minuten, du wirst zweimal kurz gebraucht
   (Tailscale-Klick, ggf. Kopplungscode/QR).
2. **Proxmox-Vollsicherung (vzdump)** der VM zusätzlich zu den Volume-tars?
   `local` auf pve hat nur 25 GB frei — dafür müsste ein Ziel her (USB-Platte,
   NAS). Bis dahin sind die rotierenden Volume-Sicherungen der Stand.

## Selbstprüfung (Plan gegen Spezifikation)

- „Automatische Updates und Configs ausrollen" → Aufgaben 4 (update.sh mit
  Workspace-Seed), 7 (Timer), 12/13.12 (Live-Beweis). Config-Grenze als
  Entscheidung 5 dokumentiert. ✓
- „Kompletten Setup migrieren ohne wirklichen Aufwand" → bootstrap.sh +
  wiederherstellen.sh + Cutover-Reihenfolge = drei Befehle plus zwei
  Betreiber-Momente. Wiederholbar für jede künftige Maschine. ✓
- „OpenClaw-Skill für Teammember" → Teil C mit Mechanik (Skill = Git-Commit)
  und offenen Zuschnitt-Fragen. Bewusst noch ohne Aufgaben. ✓
- „Für Nicht-Programmierer easy" → Fünf Handgriffe (Aufgabe 8), zwei
  Doppelklick-Dateien (Aufgabe 7), Tailscale-URL fürs Handy (Aufgabe 10). ✓
- Platzhalter-Suche: keine TBD/TODO; alle Skripte vollständig; alle
  Prüfbefehle sind gemessene Kommandozeilen dieser Nacht. ✓
- Typ-/Namenskonsistenz: `UI_TAILSCALE_IP`, `~/sales-betrieb/`,
  `update-status.json`, Volume- und Dienstnamen in allen Aufgaben identisch. ✓
