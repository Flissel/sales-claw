# sales-claw Stufe 1 (Fundament) — Implementierungsplan

> **Für agentische Umsetzer:** ERFORDERLICHE SUB-SKILL: Nutze
> `superpowers:subagent-driven-development` (empfohlen) oder
> `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen.
> Schritte verwenden Checkbox-Syntax (`- [ ]`) zur Verfolgung.

**Ziel:** Ein eigenständiger, reproduzierbar deploybarer OpenClaw-Container
`sales-claw` mit übernommener WhatsApp-Kopplung, dessen Zustand nachweislich
gesichert und wiederhergestellt werden kann.

**Architektur:** Ein Container aus dem offiziellen, gepinnten OpenClaw-Image mit zwei
Named Volumes für Zustand und Schlüssel, Port nur auf Loopback veröffentlicht. Keine
eigene Anwendung, kein eigenes Dockerfile. Die Betriebsmuster (Loopback-Bindung,
Env-Datei für Secrets, getrennte Health-Prüfung, Reverse-Proxy und Härtung für den
späteren Serverbetrieb) stammen aus `Flissel/hotel-feltzinger`.

**Tech-Stack:** Docker Compose, `ghcr.io/openclaw/openclaw:2026.7.1-slim`, OpenClaw-CLI
(2026.5.18 auf dem Host, 2026.7.1 im Container), PowerShell 7 für Host-Skripte, Bash
für die Server-Artefakte.

## Globale Randbedingungen

Diese gelten für **jede** Aufgabe. Werte wörtlich aus der Spec
(`docs/superpowers/specs/2026-08-17-sales-claw-fundament-design.md`).

- Image gepinnt auf `ghcr.io/openclaw/openclaw:2026.7.1-slim` — niemals `latest`.
- Container- und Compose-Dienstname: `sales-claw`.
- Gateway-Port im Container: `18894`. Ausdrücklich **nicht** 18793 — der ist vom
  laufenden lokalen Gateway (PID zur Laufzeit ermitteln) belegt.
- Port-Veröffentlichung ausschließlich `127.0.0.1:18894:18894`.
- Volumes: `sales-claw-state` → `/home/node/.openclaw`,
  `sales-claw-keys` → `/home/node/.config/openclaw`.
- `restart: unless-stopped`.
- Logging `json-file` mit `max-size: 10m`, `max-file: 3`.
- `TZ=Europe/Berlin`.
- `plugins.allow: ["whatsapp"]` — discord, telegram, voice-call, browser bleiben aus.
- **Kein lokales Modell.** Weder im Container noch auf dem Host darf eine
  Modell-Laufzeit gestartet werden (Ollama, vLLM, llama.cpp, LM Studio o. ä.). Das
  Modell wird ausschließlich über die API des Anbieters angesprochen. Begründung: Die
  Maschine trägt bereits 23 Container; eine lokale Modell-Laufzeit legt sie lahm. Auf
  der VM musste das Ollama-Plugin aus demselben Grund ausdrücklich abgeschaltet
  werden (Koordinations-Board, 2026-08-04). `plugins.allow` schließt es implizit aus;
  zusätzlich steht `ollama` explizit auf `enabled: false`, damit die Absicht auch bei
  einer späteren Änderung von `plugins.allow` sichtbar bleibt. `OPENAI_BASE_URL` darf
  nicht auf einen lokalen Endpunkt zeigen.
- `memory-core` aktiv, `openclaw-supermemory` **nicht** geladen.
- **Keine Secrets in `config/openclaw.json` im Repository.** API-Schlüssel kommen über
  `.env` → `env_file`; der Gateway-Token wird im Container erzeugt und liegt nur im
  Volume.
- **Unberührt lassen:** der Container `openclaw-festival`, das Volume
  `openclaw-festival-state` und die 23 übrigen laufenden Container.
- **Vor jedem Schritt, der die lokale OpenClaw-Installation berührt, muss ein
  nachgewiesener Rückweg existieren.**

---

## Dateistruktur

| Datei | Verantwortung |
|---|---|
| `.gitignore` | `.env`, Backups, Betriebsartefakte aus der Versionierung halten |
| `.env.example` | Vorlage der benötigten Umgebungsvariablen, ohne Werte |
| `docker-compose.yml` | Container, Volumes, Netz, Healthcheck, Logging (lokaler Betrieb) |
| `docker-compose.proxmox.yml` | Override für die VM: Pfade, rootless Socket, kein Port-Publish |
| `config/openclaw.json` | Saat-Konfiguration ohne Secrets; wird einmalig ins Volume kopiert |
| `scripts/preflight.ps1` | Prüft Voraussetzungen, bevor irgendetwas angefasst wird |
| `scripts/seed-volume.ps1` | Legt Volumes an und spielt die Saat-Konfiguration ein |
| `scripts/backup-state.ps1` | Sichert beide Volumes plus OpenClaw-eigenes Backup-Archiv |
| `scripts/restore-state.ps1` | Spielt eine Sicherung zurück |
| `scripts/stop-local-openclaw.ps1` | Stoppt den lokalen Gateway und weist Stillstand nach |
| `scripts/migrate-credentials.ps1` | Sichert und überträgt die WhatsApp-Kopplung |
| `scripts/smoke-test.ps1` | Abnahmeprüfung nach §9 der Spec |
| `deploy/nginx/sales-claw.conf` | Reverse-Proxy mit Rate-Limits (nur VM) |
| `deploy/nginx/limits.conf` | `limit_req_zone`-Deklarationen für den `http`-Block |
| `deploy/fail2ban/sales-claw.local` | Jail gegen wiederholte 401/403 |
| `deploy/fail2ban/sales-claw-filter.conf` | Filter für den Jail |
| `deploy/systemd/sales-claw.service` | Gehärtete Unit für den Compose-Stack |
| `deploy/provision.sh` | Frischer Debian-Host → betriebsbereit |
| `docs/01_OVERVIEW.md` … `07_PROXMOX_MIGRATION.md` | Betriebsdokumentation |

**Warum PowerShell für die Host-Skripte und Bash nur unter `deploy/`:** Stufe 1 läuft
auf Windows. Die `deploy/`-Artefakte laufen ausschließlich auf dem Debian-Host und
werden dort nie von PowerShell aufgerufen.

---

## Task 1: Repo-Gerüst und Preflight-Prüfung

**Dateien:**
- Neu: `C:\Users\User\Desktop\Sabine\sales-claw\.gitignore`
- Neu: `C:\Users\User\Desktop\Sabine\sales-claw\.env.example`
- Neu: `C:\Users\User\Desktop\Sabine\sales-claw\scripts\lib\ports.ps1`
- Neu: `C:\Users\User\Desktop\Sabine\sales-claw\scripts\preflight.ps1`
- Neu: `C:\Users\User\Desktop\Sabine\sales-claw\docs\01_OVERVIEW.md`

**Schnittstellen:**
- Konsumiert: nichts.
- Produziert: `scripts/lib/ports.ps1` — stellt `Test-PortFrei -Port <int>` bereit,
  gibt `$true` zurück, wenn auf dem Port **kein** Listener aktiv ist, und wirft bei
  echten Abfragefehlern. Wird von `preflight.ps1` (Task 1),
  `stop-local-openclaw.ps1` und `migrate-credentials.ps1` (Task 4) sowie
  `smoke-test.ps1` (Task 5) per Dot-Sourcing eingebunden.
- Produziert: `scripts/preflight.ps1` — Exit-Code `0` wenn alle Prüfungen bestehen,
  `1` sonst. Gibt je Prüfung eine Zeile `[OK] …` oder `[FEHLER] …` aus. Parameter:
  `-GatewayPort <int>` (Vorgabe `18894`), `-MinFreeGb <int>` (Vorgabe `5`).
  Wird von Task 2 und Task 5 aufgerufen.

- [ ] **Schritt 1: `.gitignore` anlegen**

```gitignore
# Secrets
.env
*.env
# .env.example passt auf keins der Muster oben (es endet nicht auf ".env")
# und bleibt damit versioniert. Eine !-Negation waere hier wirkungslos.

# Sicherungen und Betriebsartefakte
backups/
*.tar
*.tar.gz
credentials-sicherung-*/

# Betriebssystem
Thumbs.db
desktop.ini
.DS_Store
```

- [ ] **Schritt 2: `.env.example` anlegen**

```bash
# ---------------------------------------------------------------------------
# Modellanbieter. Der Agent im Container liest diese Variable aus der Umgebung,
# NICHT aus config/openclaw.json — siehe Spec §7 "Secrets".
# ---------------------------------------------------------------------------
OPENAI_API_KEY=sk-...

# ---------------------------------------------------------------------------
# Zeitzone des Containers. Termin- und Digest-Logik späterer Stufen hängt daran.
# ---------------------------------------------------------------------------
TZ=Europe/Berlin

# ---------------------------------------------------------------------------
# OPENAI_BASE_URL wird bewusst NICHT gesetzt. Ein lokal laufendes Modell ist
# für dieses Projekt ausgeschlossen — die Maschine trägt es nicht. Zeigt diese
# Variable je auf einen lokalen Endpunkt, ist das ein Fehler, keine Option.
# ---------------------------------------------------------------------------
```

- [ ] **Schritt 2b: `scripts/lib/ports.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Gemeinsame Port-Pruefung fuer alle Skripte dieses Repos.
.NOTES
  Bewusst NICHT Get-NetTCPConnection: das Cmdlet meldet "kein Treffer" als
  Fehler. Mit -ErrorAction SilentlyContinue laesst sich dann ein freier Port
  nicht mehr von einem ausgefallenen Cmdlet unterscheiden — beide liefern
  $null, beide werden zu "frei". GetActiveTcpListeners liefert stattdessen
  eine Liste; ein echter Ausfall wirft und wird vom Aufrufer als Fehler
  gewertet statt als Entwarnung.
#>

function Test-PortFrei {
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Port)

    $listener = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return -not ($listener | Where-Object { $_.Port -eq $Port })
}
```

- [ ] **Schritt 3: `scripts/preflight.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Prüft alle Voraussetzungen, bevor am Container oder an der lokalen
  OpenClaw-Installation etwas verändert wird.
.NOTES
  Verändert nichts. Exit 0 = alles bereit, Exit 1 = mindestens eine Prüfung fehlgeschlagen.
#>
[CmdletBinding()]
param(
    [int]$GatewayPort = 18894,
    [int]$MinFreeGb   = 5
)

$ErrorActionPreference = 'Continue'
$script:Fehler = 0

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

function Pruefe {
    param([string]$Name, [scriptblock]$Test, [string]$Hinweis = '')
    try {
        $ergebnis = & $Test
        if ($ergebnis) { Write-Host "[OK]     $Name" -ForegroundColor Green }
        else {
            Write-Host "[FEHLER] $Name" -ForegroundColor Red
            if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
            $script:Fehler++
        }
    } catch {
        Write-Host "[FEHLER] $Name — $($_.Exception.Message)" -ForegroundColor Red
        if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
        $script:Fehler++
    }
}

Write-Host "== Preflight sales-claw ==" -ForegroundColor Cyan

Pruefe "Docker-Daemon erreichbar" {
    $null = docker version --format '{{.Server.Version}}' 2>$null
    $LASTEXITCODE -eq 0
} "Docker Desktop starten."

Pruefe "Gateway-Port $GatewayPort ist frei" {
    Test-PortFrei -Port $GatewayPort
} "Anderen Port wählen oder belegenden Prozess beenden."

Pruefe "mindestens $MinFreeGb GB frei auf C:" {
    $frei = (Get-PSDrive -Name C).Free / 1GB
    Write-Host ("         frei: {0:N1} GB" -f $frei) -ForegroundColor DarkGray
    $frei -ge $MinFreeGb
} "Docker-Image und Volumes brauchen Platz; C: war hier schon zweimal knapp."

Pruefe "lokales OpenClaw-Zustandsverzeichnis vorhanden" {
    Test-Path "$env:USERPROFILE\.openclaw\openclaw.json"
} "Ohne die lokale Installation gibt es keine Kopplung zum Übernehmen."

Pruefe "WhatsApp-Kopplung lokal vorhanden" {
    Test-Path "$env:USERPROFILE\.openclaw\credentials\whatsapp"
} "Ohne credentials/whatsapp muss im Container per QR neu gepairt werden."

Pruefe "Image-Tag in der Registry abrufbar" {
    $null = docker manifest inspect ghcr.io/openclaw/openclaw:2026.7.1-slim 2>$null
    $LASTEXITCODE -eq 0
} "Netzwerk prüfen oder Tag korrigieren."

Pruefe "kein fremder Container belegt den Namen sales-claw" {
    # Exakter Filter. Docker filtert sonst per Teilzeichenkette, wodurch die
    # Pruefung Container mitzaehlt, die uns nichts angehen.
    -not (docker ps -a --filter "name=^sales-claw$" --format '{{.Names}}')
} "Es existiert bereits ein Container namens sales-claw — Namenskollision klaeren, bevor irgendetwas gestartet wird."

Pruefe "openclaw-festival gehoert nicht zu unserem Compose-Projekt" {
    # Das ist die reale Gefahr: traegt ein fremder Container unser
    # Compose-Projektlabel, raeumt ihn ein 'docker compose down' in diesem
    # Verzeichnis mit ab. Existiert er nicht, kann nichts kollidieren.
    $festival = docker ps -a --filter "name=^openclaw-festival$" --format '{{.Names}}'
    if (-not $festival) { return $true }
    $projekt = docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' openclaw-festival
    $projekt -ne 'sales-claw'
} "openclaw-festival traegt unser Compose-Projektlabel — 'docker compose down' wuerde ihn mit abraeumen."

Write-Host ""
if ($script:Fehler -gt 0) {
    Write-Host "$($script:Fehler) Prüfung(en) fehlgeschlagen." -ForegroundColor Red
    exit 1
}
Write-Host "Alle Prüfungen bestanden." -ForegroundColor Green
exit 0
```

- [ ] **Schritt 4: Preflight rot laufen lassen (Nachweis, dass er wirklich prüft)**

Ausführen:

```bash
pwsh -File scripts/preflight.ps1 -GatewayPort 18793
```

Erwartet: `[FEHLER] Gateway-Port 18793 ist frei`, Exit-Code `1`. Port 18793 ist vom
laufenden lokalen Gateway belegt — ein Preflight, der hier grün meldet, prüft nicht.

Exit-Code prüfen:

```bash
pwsh -File scripts/preflight.ps1 -GatewayPort 18793; echo "exit=$LASTEXITCODE"
```

Erwartet: `exit=1`.

- [ ] **Schritt 5: Preflight grün laufen lassen**

```bash
pwsh -File scripts/preflight.ps1
```

Erwartet: alle Zeilen `[OK]`, Abschluss `Alle Prüfungen bestanden.`, Exit-Code `0`.

Schlägt „mindestens 5 GB frei auf C:" fehl, ist das ein **echter Befund**, kein
Skriptfehler — dann erst Platz schaffen, nicht die Schwelle senken.

- [ ] **Schritt 6: `docs/01_OVERVIEW.md` schreiben**

```markdown
# 01 — Überblick

`sales-claw` ist eine eigenständige OpenClaw-Instanz für den Vertriebsarbeitsplatz.
Sie läuft als Container neben der persönlichen lokalen Installation und neben
`openclaw-festival` auf der Proxmox-VM.

## Was diese Stufe leistet

- OpenClaw läuft reproduzierbar im Container, gepinnt auf eine feste Version
- Der Zustand (Konfiguration, WhatsApp-Kopplung, Gedächtnis) liegt in zwei Volumes
- Sicherung und Wiederherstellung sind nachgewiesen, nicht behauptet
- Der Umzug auf die Proxmox-VM ist vorbereitet, aber nicht ausgeführt

## Was diese Stufe nicht leistet

Keine Fachlogik, kein Datenmodell, keine Bedarfsanalyse, keine Antworten an Dritte.
Der Container spricht ausschließlich mit der Nummer des Betreibers (Selbst-Chat).

## Einstiegspunkte

| Ich will … | … dann |
|---|---|
| prüfen, ob alles bereit ist | `pwsh -File scripts/preflight.ps1` |
| den Container starten | `docker compose up -d` |
| den Zustand sichern | `pwsh -File scripts/backup-state.ps1` |
| die Abnahme fahren | `pwsh -File scripts/smoke-test.ps1` |
| auf die VM umziehen | `docs/07_PROXMOX_MIGRATION.md` |
```

- [ ] **Schritt 7: Committen**

```bash
git add .gitignore .env.example scripts/lib/ports.ps1 scripts/preflight.ps1 docs/01_OVERVIEW.md
git commit -m "feat(preflight): Repo-Gerüst und Voraussetzungsprüfung"
```

---

## Task 2: Container hochziehen (ohne WhatsApp)

**Dateien:**
- Neu: `docker-compose.yml`
- Neu: `config/openclaw.json`
- Neu: `scripts/seed-volume.ps1`
- Neu: `docs/02_ARCHITECTURE.md`

**Schnittstellen:**
- Konsumiert: `scripts/preflight.ps1` aus Task 1.
- Produziert: Compose-Dienst und Container mit Namen `sales-claw`; Volumes
  `sales-claw-state` und `sales-claw-keys`. `scripts/seed-volume.ps1` — Exit `0` bei
  Erfolg, legt Volumes an und kopiert `config/openclaw.json` nach
  `/home/node/.openclaw/openclaw.json`, **überschreibt eine vorhandene Datei nicht**.
  Task 3 bis 6 setzen den laufenden Container `sales-claw` voraus.

- [ ] **Schritt 1: `config/openclaw.json` schreiben**

Bewusst minimal. Keine Secrets, kein Gateway-Token — der entsteht in Schritt 6.

```json
{
  "gateway": {
    "port": 18894,
    "mode": "local",
    "bind": "lan",
    "auth": { "mode": "token" }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "openai/gpt-5.5" },
      "workspace": "/home/node/workspace"
    },
    "list": [{ "id": "main" }]
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "dmPolicy": "allowlist",
      "selfChatMode": true,
      "allowFrom": ["+491603449761"],
      "groupPolicy": "disabled",
      "mediaMaxMb": 50
    }
  },
  "plugins": {
    "allow": ["whatsapp"],
    "slots": { "memory": "memory-core" },
    "entries": {
      "whatsapp": { "enabled": true },
      "memory-core": { "enabled": true },
      "openclaw-supermemory": { "enabled": false },
      "discord": { "enabled": false },
      "telegram": { "enabled": false },
      "voice-call": { "enabled": false },
      "browser": { "enabled": false },
      "ollama": { "enabled": false }
    }
  },
  "tools": {
    "web": { "search": { "enabled": false }, "fetch": { "enabled": false } }
  }
}
```

`bind: "lan"` statt `loopback`: Der Gateway muss innerhalb des Containers auf
`0.0.0.0` lauschen, damit Docker den Port auf den Host abbilden kann. Die Absicherung
passiert eine Ebene höher durch `127.0.0.1:18894:18894` — genau das Muster aus
`hotel-feltzinger/docker-compose.yml:61`.

- [ ] **Schritt 2: `docker-compose.yml` schreiben**

```yaml
# Lokaler Betrieb auf Docker Desktop. Für die Proxmox-VM zusätzlich
# docker-compose.proxmox.yml als Override verwenden (siehe docs/07).
services:
  sales-claw:
    image: ghcr.io/openclaw/openclaw:2026.7.1-slim
    container_name: sales-claw
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - OPENCLAW_STATE_DIR=/home/node/.openclaw
    volumes:
      - sales-claw-state:/home/node/.openclaw
      - sales-claw-keys:/home/node/.config/openclaw
    ports:
      # Nur Loopback. Der Gateway hält WhatsApp-Session und Modellschlüssel.
      - "127.0.0.1:18894:18894"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "openclaw", "health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

volumes:
  # Das `name:`-Feld ist Pflicht, nicht Kosmetik: ohne es stellt Compose dem
  # Volume den Projektnamen voran (`sales-claw_sales-claw-state`). Die
  # Sicherungs- und Wiederherstellungsskripte greifen jedoch per
  # `docker run -v sales-claw-state:/…` auf die literalen Namen zu — ohne
  # `name:` liefen gemountetes und gesichertes Volume auseinander.
  sales-claw-state:
    name: sales-claw-state
  sales-claw-keys:
    name: sales-claw-keys
```

- [ ] **Schritt 3: `scripts/seed-volume.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Legt die Volumes an und spielt die Saat-Konfiguration ein.
.NOTES
  Idempotent: eine bereits vorhandene openclaw.json im Volume wird NICHT
  überschrieben. Das Volume ist die Wahrheit, das Repo nur die Saat.
#>
[CmdletBinding()]
param(
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$ConfigFile  = "$PSScriptRoot\..\config\openclaw.json"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ConfigFile)) { throw "Saat-Konfiguration nicht gefunden: $ConfigFile" }

foreach ($v in @($StateVolume, $KeysVolume)) {
    if (-not (docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq $v })) {
        docker volume create $v | Out-Null
        Write-Host "Volume angelegt: $v"
    } else {
        Write-Host "Volume vorhanden: $v"
    }
}

# Prüfen, ob im Volume bereits eine Konfiguration liegt.
$vorhanden = docker run --rm -v "${StateVolume}:/state" alpine:3.20 `
    sh -c 'test -f /state/openclaw.json && echo ja || echo nein'

if ($vorhanden.Trim() -eq 'ja') {
    Write-Host "openclaw.json liegt bereits im Volume — nicht überschrieben." -ForegroundColor Yellow
    exit 0
}

$konfig = Get-Item $ConfigFile
docker run --rm -v "${StateVolume}:/state" -v "$($konfig.DirectoryName):/saat:ro" alpine:3.20 `
    sh -c "cp /saat/$($konfig.Name) /state/openclaw.json && chown 1000:1000 /state/openclaw.json"

Write-Host "Saat-Konfiguration eingespielt." -ForegroundColor Green
exit 0
```

- [ ] **Schritt 4: Rot — Container ohne Saat starten und scheitern sehen**

```bash
pwsh -File scripts/preflight.ps1
```

Erwartet: Exit `0`.

Dann `.env` aus der Vorlage anlegen und den echten Schlüssel eintragen (der Wert
gehört **nicht** ins Repository):

```bash
cp .env.example .env
```

Starten:

```bash
docker compose up -d
```

Nach etwa 90 Sekunden:

```bash
docker compose ps
```

Erwartet: Status `unhealthy` **oder** `restarting` — der Container hat keine
Konfiguration. Ist er hier bereits `healthy`, hat OpenClaw sich selbst eine
Vorgabekonfiguration erzeugt; dann in Schritt 5 prüfen, ob die eigenen Werte greifen.

Log ansehen:

```bash
docker compose logs --tail 40 sales-claw
```

- [ ] **Schritt 5: Grün — Saat einspielen, Token setzen, dann starten**

**Die Reihenfolge ist zwingend.** `bind: lan` mit `auth.mode: token` und *ohne*
gesetzten Token lässt den Gateway beim Start abbrechen (`Refusing to bind gateway to
lan without auth.`) und in eine Neustartschleife gehen. Ein `docker compose exec`
trifft dann nie einen laufenden Container (`Container … is restarting`) — der Token
muss also gesetzt sein, **bevor** der Dauerdienst startet.

```bash
docker compose down
pwsh -File scripts/seed-volume.ps1
```

Token über einen Einweg-Container erzeugen, der auf denselben Volumes arbeitet, aber
keine Ports veröffentlicht und sich danach selbst entfernt:

```bash
docker compose run --rm --entrypoint sh sales-claw -lc 'openclaw config set gateway.auth.token "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d " \n")"'
```

24 zufällige Bytes ergeben 48 Hex-Zeichen, also 192 Bit Entropie. Der Token landet
ausschließlich im Volume `sales-claw-state`, nie in einer versionierten Datei.

Jetzt erst den Dauerdienst starten:

```bash
docker compose up -d
```

Warten, dann:

```bash
docker compose ps
```

Erwartet: `Up … (healthy)`.

- [ ] **Schritt 6: Token verifizieren**

```bash
docker compose exec sales-claw openclaw config get gateway.auth.token
```

Erwartet: eine 48-stellige Hex-Zeichenkette. **Die Ausgabe ist ein Geheimnis** — nicht
in Berichte, Dokumente oder Commit-Nachrichten kopieren.

- [ ] **Schritt 7: Tatsächlichen Gateway-Port verifizieren**

Die Spec hält fest, dass Doku (18789) und lokale Konfiguration (18793) sich
widersprechen. Deshalb wird der Wert gemessen, nicht geglaubt:

```bash
docker compose exec sales-claw openclaw config get gateway.port
```

Erwartet: `18894`.

```bash
docker compose exec sales-claw sh -lc 'ss -ltnp 2>/dev/null || netstat -ltn'
```

Erwartet: ein Listener auf `0.0.0.0:18894` (oder `:::18894`).

Vom Host aus:

```bash
openclaw --container sales-claw health
```

Erwartet: eine Health-Ausgabe des Gateways, kein Verbindungsfehler.

**Weicht der lauschende Port ab**, ist das ein echter Befund: `docker-compose.yml`,
`config/openclaw.json` und Spec §7 auf den gemessenen Wert korrigieren und die
Abweichung in `docs/02_ARCHITECTURE.md` festhalten.

- [ ] **Schritt 8: Nachweisen, dass nichts anderes angefasst wurde**

```bash
docker ps --format "{{.Names}}" | Select-String -Pattern "festival"
```

Erwartet: `openclaw-festival` erscheint unverändert, falls er lokal lief — bzw. keine
Ausgabe, falls er nur auf der VM läuft. In beiden Fällen darf sich sein Status nicht
geändert haben.

- [ ] **Schritt 9: `docs/02_ARCHITECTURE.md` schreiben**

Inhalt: das Diagramm aus Spec §5, die Tabelle der Konfigurationsentscheidungen aus
Spec §7 mit den in Schritt 7 **gemessenen** Werten, sowie der Abschnitt „Warum zwei
Volumes" aus der Spec.

- [ ] **Schritt 10: Committen**

```bash
git add docker-compose.yml config/openclaw.json scripts/seed-volume.ps1 docs/02_ARCHITECTURE.md
git commit -m "feat(container): sales-claw als gepinnter OpenClaw-Container"
```

---

## Task 3: Sicherung und Wiederherstellung — bewiesen mit Wegwerf-Daten

Diese Aufgabe steht **vor** dem Umzug der WhatsApp-Kopplung. Der Grund ist wichtig
genug, um ihn hier auszuschreiben: Ein ungeprüftes Wiederherstellungsskript zum ersten
Mal mit der echten Kopplung zu testen, heißt, die Kopplung als Testobjekt zu verwenden.
Wir beweisen die Mechanik zuerst an einer Markierungsdatei.

**Dateien:**
- Neu: `scripts/backup-state.ps1`
- Neu: `scripts/restore-state.ps1`
- Neu: `docs/04_BACKUP_RESTORE.md`

**Schnittstellen:**
- Konsumiert: Volumes und Container aus Task 2.
- Produziert: `scripts/backup-state.ps1 [-Ziel <Pfad>]` → legt
  `<Ziel>/sales-claw-<zeitstempel>/` mit `state.tar`, `keys.tar` und
  `openclaw-backup/` an, gibt den Pfad auf stdout aus, Exit `0`.
  `scripts/restore-state.ps1 -Quelle <Pfad>` → stellt beide Volumes wieder her,
  Exit `0`. Beide Skripte werden von Task 6 verwendet.

- [ ] **Schritt 1: `scripts/backup-state.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Sichert beide Volumes als tar-Archive und zusätzlich OpenClaws eigenes,
  verifizierbares Backup-Archiv.
.NOTES
  Zwei Wege mit Absicht: das tar-Archiv ist wortgetreu, das OpenClaw-Archiv
  kennt die Semantik (Konfiguration, Credentials, Sessions, Workspaces) und
  lässt sich mit `openclaw backup verify` prüfen.
#>
[CmdletBinding()]
param(
    [string]$Ziel        = "$PSScriptRoot\..\backups",
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw'
)

$ErrorActionPreference = 'Stop'

# Namensschutz, spiegelbildlich zum Wiederherstellungsskript. Hier wird nur
# lesend gemountet (:ro), das Risiko ist also kleiner — aber ein Skript, das
# gegen echte Kopplungsdaten laeuft, soll gar nicht erst auf fremde Volumes
# zeigen koennen.
foreach ($v in @($StateVolume, $KeysVolume)) {
    # -cnotmatch: gross-/kleinschreibungsempfindlich. Das vorgabemaessige
    # -notmatch liesse 'SALES-CLAW-STATE' durch — Docker-Volumenamen sind aber
    # gross-/kleinschreibungsempfindlich, das waere ein anderes Volume.
    if ($v -cnotmatch '^sales-claw-[a-z]+$') {
        throw "Verweigert: '$v' gehoert nicht zu diesem Projekt. Erlaubt sind nur Namen der Form sales-claw-*."
    }
}

$zeitstempel = Get-Date -Format 'yyyyMMdd-HHmmss'
$ordner = Join-Path $Ziel "sales-claw-$zeitstempel"
New-Item -ItemType Directory -Force -Path $ordner | Out-Null
$ordnerVoll = (Resolve-Path $ordner).Path

foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    docker run --rm -v "${vol}:/quelle:ro" -v "${ordnerVoll}:/ziel" alpine:3.20 `
        tar -cf "/ziel/$name.tar" -C /quelle .
    if ($LASTEXITCODE -ne 0) { throw "tar für Volume $vol fehlgeschlagen" }
    Write-Host "gesichert: $vol -> $name.tar"
}

# OpenClaws eigenes Archiv, nur wenn der Container läuft.
$laeuft = docker ps --filter "name=$Container" --format '{{.Names}}'
if ($laeuft -contains $Container) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ordnerVoll 'openclaw-backup') | Out-Null
    docker exec $Container openclaw backup create 2>&1 | Tee-Object -FilePath (Join-Path $ordnerVoll 'openclaw-backup\create.log')
    if ($LASTEXITCODE -ne 0) {
        # Kein Abbruch: die tar-Archive sind der massgebliche Sicherungsweg.
        # Aber still schlucken darf man einen Fehlschlag nicht — wer spaeter
        # eine Wiederherstellung braucht, muss wissen, was fehlt.
        Write-Host "WARNUNG: 'openclaw backup create' endete mit Code $LASTEXITCODE. Die tar-Archive sind vorhanden; das semantische Archiv fehlt. Siehe create.log." -ForegroundColor Yellow
    } else {
        Write-Host "OpenClaw-Backup erstellt (Pfad siehe create.log)."
    }
} else {
    Write-Host "Container laeuft nicht — OpenClaw-eigenes Backup uebersprungen." -ForegroundColor Yellow
}

Write-Host $ordnerVoll
exit 0
```

- [ ] **Schritt 2: `scripts/restore-state.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Stellt beide Volumes aus einer Sicherung wieder her.
.NOTES
  Der Container muss gestoppt sein. Vorhandene Volume-Inhalte werden geleert.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Quelle,
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw'
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Namensschutz. Dieses Skript LOESCHT Volume-Inhalte. Ein Tippfehler im
# Parameter wuerde sonst ein fremdes Volume treffen — auf dieser Maschine
# liegen fremde Volumes direkt daneben.
# ---------------------------------------------------------------------------
foreach ($v in @($StateVolume, $KeysVolume)) {
    # -cnotmatch: gross-/kleinschreibungsempfindlich. Das vorgabemaessige
    # -notmatch liesse 'SALES-CLAW-STATE' durch — Docker-Volumenamen sind aber
    # gross-/kleinschreibungsempfindlich, das waere ein anderes Volume.
    if ($v -cnotmatch '^sales-claw-[a-z]+$') {
        throw "Verweigert: '$v' gehoert nicht zu diesem Projekt. Erlaubt sind nur Namen der Form sales-claw-*."
    }
}

if (docker ps --filter "name=$Container" --format '{{.Names}}' | Where-Object { $_ -eq $Container }) {
    throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
}

$quelleVoll = (Resolve-Path $Quelle).Path

# ---------------------------------------------------------------------------
# BEIDE Archive vollstaendig pruefen, BEVOR irgendein Volume angefasst wird.
#
# Existenz allein genuegt nicht: eine abgebrochene Kopie, eine volle Platte
# oder ein dazwischenfunkender Virenscanner hinterlassen eine Datei, die da
# ist und trotzdem nichts taugt. Wuerde erst beim Entpacken auffallen — dann
# ist das Zielvolume aber schon geleert. Bei zwei Volumes entstuende sogar ein
# halber Zustand: eines ueberschrieben, eines leer.
# ---------------------------------------------------------------------------
foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    $pfad = Join-Path $quelleVoll "$name.tar"
    if (-not (Test-Path $pfad)) { throw "Fehlt in der Sicherung: $name.tar — nichts wurde angefasst." }
    $groesse = (Get-Item $pfad).Length
    if ($groesse -eq 0) { throw "Leer: $name.tar hat 0 Byte — nichts wurde angefasst." }
    # Probeweise VOLLSTAENDIG entpacken, in ein Wegwerf-Verzeichnis im
    # Container. Ein blosses `tar -tf` genuegt nicht: ein abgeschnittenes
    # Archiv laesst sich oft noch auflisten, aber nicht entpacken. Und der
    # Exit-Code einer Pipe (`tar -tf | wc -l`) ist der des LETZTEN Glieds —
    # also der von `wc`, das immer 0 liefert. Busybox-sh kennt kein pipefail.
    # Genau daran ist die erste Fassung dieser Pruefung gescheitert.
    #
    # Die `&&`-Kette sorgt dafuer, dass ein Fehler von `tar` den Exit-Code
    # bestimmt: bei Misserfolg laeuft `find` gar nicht erst an.
    $eintraege = docker run --rm -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "mkdir -p /probe && tar -xf /quelle/$name.tar -C /probe && find /probe -mindepth 1 | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Beschaedigt: $name.tar laesst sich nicht entpacken — nichts wurde angefasst." }

    # Ein leeres Archiv ist KEIN Defekt. `sales-claw-keys` ist seit
    # Projektbeginn leer, und ein leeres Volume ist ein gueltiger Zustand.
    # Hier abzubrechen wuerde eine voellig intakte Sicherung fuer unbrauchbar
    # erklaeren — ein Schutz, der mehr kaputtmacht als er verhindert. Die
    # Unversehrtheit ist durch das erfolgreiche Entpacken oben bereits belegt;
    # die Eintragszahl ist Information, kein Kriterium.
    $anzahl = [int]$eintraege.Trim()
    if ($anzahl -lt 1) {
        Write-Host "HINWEIS: $name.tar ist unversehrt, aber leer — das Volume enthielt nichts." -ForegroundColor Yellow
    }
    Write-Host "probeweise entpackt: $name.tar ($groesse Byte, $anzahl Eintraege)"
}

Write-Host "Beide Archive in Ordnung. Jetzt erst werden die Volumes geleert." -ForegroundColor Yellow

foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    if (-not (docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq $vol })) {
        docker volume create $vol | Out-Null
    }
    docker run --rm -v "${vol}:/ziel" -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "rm -rf /ziel/..?* /ziel/.[!.]* /ziel/* 2>/dev/null; tar -xf /quelle/$name.tar -C /ziel"
    if ($LASTEXITCODE -ne 0) { throw "Wiederherstellung von $vol fehlgeschlagen" }
    Write-Host "wiederhergestellt: $name.tar -> $vol"
}

Write-Host "Wiederherstellung abgeschlossen." -ForegroundColor Green
exit 0
```

- [ ] **Schritt 3: Markierungsdatei ins Volume legen**

```bash
docker compose exec sales-claw sh -lc 'echo "markierung-task3" > /home/node/.openclaw/PROBE.txt && cat /home/node/.openclaw/PROBE.txt'
```

Erwartet: `markierung-task3`.

- [ ] **Schritt 4: Sichern**

```bash
pwsh -File scripts/backup-state.ps1
```

Erwartet: Zeilen `gesichert: sales-claw-state -> state.tar` und
`gesichert: sales-claw-keys -> keys.tar`, zuletzt der Pfad des Sicherungsordners.
Diesen Pfad notieren.

- [ ] **Schritt 5: Rot — beide Volumes löschen und den Verlust sehen**

```bash
docker compose down
docker volume rm sales-claw-state sales-claw-keys
docker compose up -d
```

Warten, dann:

```bash
docker compose exec sales-claw sh -lc 'cat /home/node/.openclaw/PROBE.txt'
```

Erwartet: `No such file or directory` — die Markierung ist weg. Das ist der Beweis,
dass die anschließende Wiederherstellung wirklich etwas leistet.

- [ ] **Schritt 6: Grün — wiederherstellen**

```bash
docker compose down
pwsh -File scripts/restore-state.ps1 -Quelle <in Schritt 4 notierter Pfad>
docker compose up -d
```

Warten, dann:

```bash
docker compose exec sales-claw sh -lc 'cat /home/node/.openclaw/PROBE.txt'
```

Erwartet: `markierung-task3`.

```bash
docker compose ps
```

Erwartet: `Up … (healthy)`.

- [ ] **Schritt 7: Markierung entfernen**

```bash
docker compose exec sales-claw sh -lc 'rm /home/node/.openclaw/PROBE.txt'
```

- [ ] **Schritt 8: `docs/04_BACKUP_RESTORE.md` schreiben**

Inhalt: beide Skripte mit Aufrufbeispielen; die Begründung für zwei Sicherungswege;
der ausdrückliche Hinweis, dass **beide** Volumes zusammengehören (Spec §5, „Warum
zwei Volumes"); die in Schritt 5 und 6 gemessene Rot/Grün-Abfolge als Beleg; sowie
eine Empfehlung für einen geplanten täglichen Lauf.

- [ ] **Schritt 9: Committen**

```bash
git add scripts/backup-state.ps1 scripts/restore-state.ps1 docs/04_BACKUP_RESTORE.md
git commit -m "feat(backup): Sicherung und Wiederherstellung beider Volumes, an Wegwerf-Daten belegt"
```

---

## Task 4: Lokale Instanz stoppen und Kopplung übernehmen

**Dateien:**
- Neu: `scripts/stop-local-openclaw.ps1`
- Neu: `scripts/migrate-credentials.ps1`
- Neu: `docs/03_RUNBOOK.md`
- Neu: `docs/05_DISASTER_RECOVERY.md`

**Schnittstellen:**
- Konsumiert: die in Task 3 belegten Sicherungsskripte.
- Produziert: `scripts/stop-local-openclaw.ps1` → Exit `0`, wenn Port 18793 danach
  frei ist. `scripts/migrate-credentials.ps1` → Exit `0`, wenn
  `/home/node/.openclaw/credentials/whatsapp` im Volume liegt; legt vorher
  `credentials-sicherung-<zeitstempel>/` im Repo-Wurzelverzeichnis an.

**Diese Aufgabe ist die erste, die etwas Bestehendes anfasst.** Zwei
Baileys-Sitzungen mit denselben Credentials führen zu Sitzungskonflikten bis zur
Abmeldung des verknüpften Geräts (Spec §8). Reihenfolge daher zwingend: erst sichern,
dann stoppen, dann übernehmen.

- [ ] **Schritt 1: Rückweg zuerst — vollständige Sicherung der lokalen Installation**

Mit OpenClaws eigenem Befehl auf dem **Host**:

```bash
openclaw backup create
```

Erwartet: Pfad eines Archivs. Diesen notieren.

Verifizieren:

```bash
openclaw backup verify <notierter Archivpfad>
```

Erwartet: Bestätigung, dass Archiv und Manifest gültig sind. **Scheitert das, hier
abbrechen** — ohne geprüften Rückweg wird die lokale Instanz nicht angefasst.

Zusätzlich eine wortgetreue Kopie:

```bash
Copy-Item -Recurse "$env:USERPROFILE\.openclaw\credentials" "credentials-sicherung-host-$(Get-Date -Format yyyyMMdd-HHmmss)"
```

- [ ] **Schritt 2: `scripts/stop-local-openclaw.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Stoppt den lokalen OpenClaw-Gateway und weist nach, dass er wirklich steht.
.NOTES
  Zwei gleichzeitige Baileys-Sitzungen auf denselben Credentials melden das
  verknuepfte Geraet ab. Stillstand wird deshalb geprueft, nicht angenommen.
#>
[CmdletBinding()]
param([int]$LokalerPort = 18793)

$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

Write-Host "Dienststatus vorher:"
openclaw daemon status 2>&1 | Write-Host

Write-Host "Stoppe Gateway-Dienst…"
openclaw daemon stop 2>&1 | Write-Host

Start-Sleep -Seconds 3

# Die Entscheidung faellt ueber Test-PortFrei — dort wird ein Abfragefehler
# geworfen statt als "frei" durchgewinkt. Get-NetTCPConnection kommt nur noch
# fuer die Diagnose zum Einsatz, wenn ohnehin feststeht, dass etwas lauscht.
if (-not (Test-PortFrei -Port $LokalerPort)) {
    Write-Host "Port $LokalerPort lauscht weiterhin." -ForegroundColor Red
    $listener = Get-NetTCPConnection -LocalPort $LokalerPort -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" |
            Select-Object ProcessId, CommandLine | Format-List
    }
    Write-Host "Nicht selbst beenden — Ursache klaeren und dem Betreiber vorlegen." -ForegroundColor Yellow
    exit 1
}

Write-Host "Port $LokalerPort ist frei — lokaler Gateway steht." -ForegroundColor Green
exit 0
```

Das Skript beendet **keine** Prozesse gewaltsam. Steht der Port weiter offen, ist das
eine Entscheidung für den Betreiber, nicht für ein Skript.

- [ ] **Schritt 3: Rot — Stillstandsprüfung gegen den laufenden Gateway**

Vor dem Stoppen prüfen, dass die Prüfung überhaupt anschlägt:

```bash
Get-NetTCPConnection -LocalPort 18793 -State Listen | Select-Object LocalPort, OwningProcess
```

Erwartet: eine Zeile mit `18793` und einer PID. Kommt hier nichts, läuft der lokale
Gateway nicht — dann Schritt 4 überspringen und im Runbook vermerken.

- [ ] **Schritt 4: Grün — lokalen Gateway stoppen**

```bash
pwsh -File scripts/stop-local-openclaw.ps1
```

Erwartet: `Port 18793 ist frei — lokaler Gateway steht.`, Exit `0`.

- [ ] **Schritt 5: `scripts/migrate-credentials.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Uebertraegt die WhatsApp-Kopplung von der lokalen Installation ins Volume.
.NOTES
  Setzt voraus, dass der lokale Gateway steht (stop-local-openclaw.ps1) und
  der Container gestoppt ist.
#>
[CmdletBinding()]
param(
    [string]$LokalerZustand = "$env:USERPROFILE\.openclaw",
    [string]$StateVolume    = 'sales-claw-state',
    [string]$Container      = 'sales-claw',
    [int]$LokalerPort       = 18793
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

$quelle = Join-Path $LokalerZustand 'credentials\whatsapp'
if (-not (Test-Path $quelle)) { throw "Keine WhatsApp-Kopplung unter $quelle" }

if (-not (Test-PortFrei -Port $LokalerPort)) {
    throw "Lokaler Gateway lauscht noch auf $LokalerPort. Erst stop-local-openclaw.ps1 ausfuehren."
}
if (docker ps --filter "name=$Container" --format '{{.Names}}' | Where-Object { $_ -eq $Container }) {
    throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
}

$sicherung = Join-Path (Split-Path $PSScriptRoot -Parent) "credentials-sicherung-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -Recurse -Path (Join-Path $LokalerZustand 'credentials') -Destination $sicherung
Write-Host "Sicherung angelegt: $sicherung"

$elternVoll = (Resolve-Path (Split-Path $quelle -Parent)).Path
docker run --rm -v "${StateVolume}:/state" -v "${elternVoll}:/quelle:ro" alpine:3.20 `
    sh -c 'mkdir -p /state/credentials && cp -a /quelle/whatsapp /state/credentials/ && chown -R 1000:1000 /state/credentials'
if ($LASTEXITCODE -ne 0) { throw "Kopieren der Credentials fehlgeschlagen" }

$pruef = docker run --rm -v "${StateVolume}:/state:ro" alpine:3.20 `
    sh -c 'test -d /state/credentials/whatsapp && echo ja || echo nein'
if ($pruef.Trim() -ne 'ja') { throw "Credentials liegen nach dem Kopieren nicht im Volume" }

Write-Host "WhatsApp-Kopplung ins Volume uebernommen." -ForegroundColor Green
exit 0
```

- [ ] **Schritt 6: Container stoppen und Credentials übernehmen**

```bash
docker compose down
pwsh -File scripts/migrate-credentials.ps1
```

Erwartet: `Sicherung angelegt: …` und `WhatsApp-Kopplung ins Volume uebernommen.`,
Exit `0`.

- [ ] **Schritt 7: `docs/03_RUNBOOK.md` und `docs/05_DISASTER_RECOVERY.md` schreiben**

`03_RUNBOOK.md` enthält: Starten, Stoppen, Logs (`docker compose logs -f sales-claw`
und `openclaw --container sales-claw logs`), Kanalstatus
(`openclaw --container sales-claw channels status`), Diagnose
(`openclaw --container sales-claw doctor`), sowie die Reihenfolge-Regel aus dieser
Aufgabe.

`05_DISASTER_RECOVERY.md` enthält mindestens diese vier Fälle mit konkreten Befehlen:

1. **Kopplung verloren** → `openclaw --container sales-claw channels login`, QR scannen.
2. **Zustand verloren** → `scripts/restore-state.ps1` aus der letzten Sicherung.
3. **Rückweg zur lokalen Installation** → `credentials-sicherung-*` zurückspielen,
   `openclaw daemon start`, Port 18793 prüfen.
4. **Fehlerbild `openKeyedStore is only available for trusted plugins`** → tritt auf,
   wenn die Installationsspur des Plugins auf einen alten Pfad zeigt (Koordinations-Board,
   2026-08-04). Behebung: Plugin im Container mit `npm_config_cache=/tmp/.npm` neu
   installieren. Ohne diesen Eintrag kostet die Diagnose Stunden.

- [ ] **Schritt 8: Committen**

```bash
git add scripts/stop-local-openclaw.ps1 scripts/migrate-credentials.ps1 docs/03_RUNBOOK.md docs/05_DISASTER_RECOVERY.md
git commit -m "feat(kopplung): lokale Instanz stoppen und WhatsApp-Kopplung uebernehmen"
```

---

## Task 5: Kopplung und Neustart-Festigkeit nachweisen

**Dateien:**
- Neu: `scripts/smoke-test.ps1`
- Ändern: `docs/03_RUNBOOK.md` (Abschnitt „Abnahme")

**Schnittstellen:**
- Konsumiert: Container mit übernommenen Credentials aus Task 4.
- Produziert: `scripts/smoke-test.ps1` → prüft Abnahmekriterien 1, 2, 3 und 6 aus
  Spec §9. Exit `0` bei Erfolg, `1` sonst. Task 6 ergänzt Kriterium 5.

- [ ] **Schritt 1: Container starten und Kanalstatus prüfen**

```bash
docker compose up -d
```

Warten, bis `docker compose ps` `healthy` meldet, dann:

```bash
openclaw --container sales-claw channels status
```

Erwartet: WhatsApp erscheint als verbunden. **Erscheint stattdessen ein QR-Code oder
„logged out", ist die Übernahme fehlgeschlagen** — dann Task 4 Schritt 7 Fall 3
(Rückweg) gehen und die Ursache klären, bevor weitergemacht wird.

Version im Container gegenprüfen (Abnahmekriterium 4 der Spec — der Sprung von
2026.5.18 auf 2026.7.1):

```bash
docker compose exec sales-claw openclaw --version
```

Erwartet: `2026.7.1`.

- [ ] **Schritt 2: `scripts/smoke-test.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Abnahme nach Spec §9, Kriterien 1, 2, 3 und 6.
.NOTES
  Kriterium 4 (Versionssprung) und 5 (Wiederherstellung) laufen in Task 5
  Schritt 1 bzw. Task 6 gesondert.
#>
[CmdletBinding()]
param(
    [string]$Container = 'sales-claw',
    [int]$Port         = 18894
)

$ErrorActionPreference = 'Continue'
$script:Fehler = 0

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

function Pruefe {
    param([string]$Name, [scriptblock]$Test)
    try {
        if (& $Test) { Write-Host "[OK]     $Name" -ForegroundColor Green }
        else { Write-Host "[FEHLER] $Name" -ForegroundColor Red; $script:Fehler++ }
    } catch {
        Write-Host "[FEHLER] $Name — $($_.Exception.Message)" -ForegroundColor Red
        $script:Fehler++
    }
}

Write-Host "== Abnahme sales-claw ==" -ForegroundColor Cyan

Pruefe "Kriterium 1: Container laeuft und ist healthy" {
    (docker inspect --format '{{.State.Health.Status}}' $Container 2>$null) -eq 'healthy'
}

Pruefe "Kriterium 1b: Gateway lauscht auf 127.0.0.1:$Port" {
    -not (Test-PortFrei -Port $Port)
}

Pruefe "Kriterium 2: WhatsApp-Kanal verbunden" {
    $status = openclaw --container $Container channels status 2>&1 | Out-String
    $status -match 'whatsapp' -and $status -notmatch 'logged.?out|disconnected'
}

Pruefe "Kriterium 6: openclaw-festival gehoert nicht zu unserem Compose-Projekt" {
    # Existiert er nicht, kann nichts kollidieren. Existiert er, darf er nicht
    # unser Projektlabel tragen — sonst raeumt 'docker compose down' ihn mit ab.
    $festival = docker ps -a --filter "name=^openclaw-festival$" --format '{{.Names}}'
    if (-not $festival) { return $true }
    (docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' openclaw-festival) -ne 'sales-claw'
}

Pruefe "Kriterium 6b: lokaler Gateway steht (Port 18793 frei)" {
    Test-PortFrei -Port 18793
}

Write-Host ""
if ($script:Fehler -gt 0) { Write-Host "$($script:Fehler) Kriterium(en) nicht erfuellt." -ForegroundColor Red; exit 1 }
Write-Host "Automatisch pruefbare Kriterien erfuellt." -ForegroundColor Green
Write-Host "Manuell noch offen: Selbst-Chat-Umlauf (Kriterium 2) — siehe docs/03_RUNBOOK.md." -ForegroundColor Yellow
exit 0
```

- [ ] **Schritt 3: Abnahme laufen lassen**

```bash
pwsh -File scripts/smoke-test.ps1
```

Erwartet: alle Zeilen `[OK]`, Exit `0`.

- [ ] **Schritt 4: Selbst-Chat-Umlauf von Hand prüfen (Kriterium 2)**

Vom Telefon aus eine Nachricht an die eigene Nummer (+49 160 344 9761) senden,
zum Beispiel `ping sales-claw`.

Beobachten:

```bash
docker compose logs -f sales-claw
```

Erwartet: eingehende Nachricht im Log **und** eine Antwort im WhatsApp-Chat. Kommt die
Nachricht an, aber keine Antwort, fehlt in der Regel der Modellschlüssel — dann
`docker compose exec sales-claw sh -lc 'test -n "$OPENAI_API_KEY" && echo gesetzt || echo fehlt'`.

- [ ] **Schritt 5: Neustart-Festigkeit prüfen (Kriterium 3)**

```bash
docker compose down
docker compose up -d
```

Warten, dann:

```bash
openclaw --container sales-claw channels status
```

Erwartet: weiterhin verbunden, **kein** neuer QR-Code.

```bash
pwsh -File scripts/smoke-test.ps1
```

Erwartet: Exit `0`.

- [ ] **Schritt 6: `docs/03_RUNBOOK.md` um den Abschnitt „Abnahme" ergänzen**

Die sechs Kriterien aus Spec §9, je Kriterium der Befehl und die erwartete Ausgabe,
sowie die Unterscheidung zwischen automatisch geprüften und von Hand zu prüfenden
Punkten.

- [ ] **Schritt 7: Committen**

```bash
git add scripts/smoke-test.ps1 docs/03_RUNBOOK.md
git commit -m "feat(abnahme): Kopplung und Neustart-Festigkeit nachweisen"
```

---

## Task 6: Wiederherstellungsprobe mit echter Kopplung

Das wichtigste Abnahmekriterium der Spec (§9.5). Der Vorgang ist identisch mit dem
späteren Umzug auf die Proxmox-VM — ist er grün, ist der Umzug risikoarm.

**Dateien:**
- Ändern: `docs/04_BACKUP_RESTORE.md` (Abschnitt „Probe mit echter Kopplung")

**Schnittstellen:**
- Konsumiert: `scripts/backup-state.ps1`, `scripts/restore-state.ps1` (Task 3),
  `scripts/smoke-test.ps1` (Task 5), gekoppelter Container (Task 4).
- Produziert: keinen Code — einen Nachweis.

- [ ] **Schritt 1: Zweiten Rückweg sicherstellen**

Vor dem absichtlichen Löschen zusätzlich zur regulären Sicherung eine wortgetreue
Kopie der Credentials aus dem Volume ziehen:

```bash
docker run --rm -v sales-claw-state:/state:ro -v "${PWD}:/aus" alpine:3.20 tar -cf /aus/credentials-vor-probe.tar -C /state credentials
```

Erwartet: Datei `credentials-vor-probe.tar` im Repo-Wurzelverzeichnis. Sie ist durch
`.gitignore` (`*.tar`) von der Versionierung ausgenommen.

- [ ] **Schritt 2: Sichern**

```bash
pwsh -File scripts/backup-state.ps1
```

Pfad notieren.

- [ ] **Schritt 3: Rot — beide Volumes löschen**

```bash
docker compose down
docker volume rm sales-claw-state sales-claw-keys
docker compose up -d
```

Warten, dann:

```bash
openclaw --container sales-claw channels status
```

Erwartet: **nicht** verbunden — QR-Code oder „logged out". Das belegt, dass die
anschließende Wiederherstellung tatsächlich die Kopplung zurückbringt und nicht
etwa ein Zwischenspeicher greift.

- [ ] **Schritt 4: Grün — wiederherstellen**

```bash
docker compose down
pwsh -File scripts/restore-state.ps1 -Quelle <in Schritt 2 notierter Pfad>
docker compose up -d
```

Warten, dann:

```bash
openclaw --container sales-claw channels status
```

Erwartet: verbunden, **ohne** neuen QR-Scan.

```bash
pwsh -File scripts/smoke-test.ps1
```

Erwartet: Exit `0`.

- [ ] **Schritt 5: Selbst-Chat erneut prüfen**

Wie Task 5 Schritt 4: Nachricht senden, Antwort erhalten. Erst damit ist bewiesen,
dass nicht nur der Status „verbunden" meldet, sondern der Kanal wirklich trägt.

- [ ] **Schritt 5b: Schlüssel-Volume mit Inhalt nachweisen**

Bis Task 3 war `sales-claw-keys` leer, sein Wiederherstellungsweg also nur
leer-zu-leer geprüft — ein Nulltest, kein Beweis. Prüfe zuerst, ob dort inzwischen
etwas liegt:

```bash
docker compose exec sales-claw sh -lc 'ls -A /home/node/.config/openclaw | wc -l'
```

**Ist das Ergebnis `0`**, bleibt das Volume leer und dieser Schritt entfällt; halte in
`docs/04_BACKUP_RESTORE.md` fest, dass der Weg für dieses Volume weiterhin unbewiesen
ist.

**Ist das Ergebnis größer als `0`**, ist der Roundtrip eigens zu belegen:

```bash
docker compose exec sales-claw sh -lc 'echo "markierung-keys" > /home/node/.config/openclaw/PROBE.txt'
```

Dann Sicherung, Löschen beider Volumes, Wiederherstellung wie in Schritt 2 bis 4 —
und danach:

```bash
docker compose exec sales-claw sh -lc 'cat /home/node/.config/openclaw/PROBE.txt'
```

Erwartet: `markierung-keys`. Zusätzlich prüfen, dass die Dateirechte der echten
Schlüsseldateien den Roundtrip überstanden haben:

```bash
docker compose exec sales-claw sh -lc 'ls -la /home/node/.config/openclaw'
```

Markierung anschließend entfernen.

- [ ] **Schritt 6: Zwischensicherung aufräumen**

```bash
Remove-Item credentials-vor-probe.tar
```

Nur ausführen, wenn Schritt 4 und 5 grün waren.

- [ ] **Schritt 7: `docs/04_BACKUP_RESTORE.md` um den Nachweis ergänzen**

Abschnitt „Probe mit echter Kopplung": Datum der Durchführung, die beobachteten
Ausgaben aus Schritt 3 (nicht verbunden) und Schritt 4 (verbunden), und der Satz,
dass dieser Vorgang identisch zum Proxmox-Umzug ist.

- [ ] **Schritt 8: Committen**

```bash
git add docs/04_BACKUP_RESTORE.md
git commit -m "test(wiederherstellung): Kopplung ueberlebt Volume-Verlust nachgewiesen"
```

---

## Task 7: Artefakte für den Serverbetrieb und Sicherheitsdokumentation

Wird geschrieben und syntaktisch geprüft, aber **nicht ausgeführt**. Der Umzug ist
Stufe 1b und beginnt mit einem Claim im Koordinations-Board.

**Dateien:**
- Neu: `docker-compose.proxmox.yml`
- Neu: `deploy/nginx/sales-claw.conf`, `deploy/nginx/limits.conf`
- Neu: `deploy/fail2ban/sales-claw.local`, `deploy/fail2ban/sales-claw-filter.conf`
- Neu: `deploy/systemd/sales-claw.service`
- Neu: `deploy/provision.sh`
- Neu: `docs/06_SECURITY.md`, `docs/07_PROXMOX_MIGRATION.md`

**Schnittstellen:**
- Konsumiert: `docker-compose.yml` aus Task 2 (als Basis für den Override).
- Produziert: keine Laufzeit-Schnittstelle. Der Override wird auf der VM als
  `docker compose -f docker-compose.yml -f docker-compose.proxmox.yml up -d` verwendet.

- [ ] **Schritt 1: `docker-compose.proxmox.yml` schreiben**

```yaml
# Override für die Proxmox-VM (192.168.178.65), rootless Docker als User debian.
#
# Verwendung auf der VM:
#   docker compose -f docker-compose.yml -f docker-compose.proxmox.yml up -d
#
# Unterschiede zum lokalen Betrieb:
#   • Kein Port-Publish — die Erreichbarkeit regelt nginx oder ein Tunnel.
#   • Zustand liegt unter /home/debian statt in Named Volumes: der Docker-Daemon
#     der VM löst Bind-Quellen im eigenen Namensraum auf und kann /home/node
#     nicht anlegen (DooD-Pfadbedingung, Koordinations-Board 2026-08-04).
services:
  sales-claw:
    ports: !reset []
    volumes:
      - /home/debian/sales-claw/state:/home/node/.openclaw
      - /home/debian/sales-claw/keys:/home/node/.config/openclaw
    networks:
      - sales-net

networks:
  sales-net:
    driver: bridge
```

- [ ] **Schritt 2: Override syntaktisch prüfen**

```bash
docker compose -f docker-compose.yml -f docker-compose.proxmox.yml config
```

Erwartet: die zusammengeführte Konfiguration ohne Fehler; unter `services.sales-claw`
darf **kein** `ports`-Eintrag mehr stehen.

- [ ] **Schritt 3: `deploy/nginx/limits.conf` schreiben**

```nginx
# Gehört nach /etc/nginx/conf.d/limits.conf — limit_req_zone ist nur im
# http{}-Block gültig, nicht im server{}-Block.
limit_req_zone $binary_remote_addr zone=sales_gateway:10m rate=60r/m;
limit_req_zone $binary_remote_addr zone=sales_health:10m  rate=6r/m;
```

- [ ] **Schritt 4: `deploy/nginx/sales-claw.conf` schreiben**

```nginx
# Reverse-Proxy für sales-claw. Nur verwenden, wenn externe Erreichbarkeit
# wirklich gebraucht wird — sonst reicht ein Tunnel ohne offenen Port.
#
# Ablegen unter: /etc/nginx/sites-available/sales-claw.conf
# Verlinken:     /etc/nginx/sites-enabled/sales-claw.conf
# TLS:           sudo certbot --nginx -d <domain>
server {
    listen 80;
    listen [::]:80;
    server_name sales-claw.example.invalid;

    client_max_body_size 64m;      # WhatsApp-Medien bis 50 MB laut Konfiguration
    client_body_timeout 30s;
    client_header_timeout 10s;
    send_timeout 60s;
    keepalive_timeout 30s;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    server_tokens off;

    location = /health {
        limit_req zone=sales_health burst=2 nodelay;
        proxy_pass http://127.0.0.1:18894/health;
        proxy_http_version 1.1;
        access_log off;
    }

    location / {
        limit_req zone=sales_gateway burst=20 nodelay;
        limit_req_status 429;

        proxy_pass http://127.0.0.1:18894;
        proxy_http_version 1.1;
        # Der Gateway spricht WebSocket — ohne diese beiden Zeilen bricht die
        # Verbindung nach dem Handshake ab.
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }

    access_log /var/log/nginx/sales-claw.access.log;
    error_log  /var/log/nginx/sales-claw.error.log warn;
}
```

- [ ] **Schritt 5: nginx-Konfiguration syntaktisch prüfen**

```bash
docker run --rm -v "${PWD}/deploy/nginx/sales-claw.conf:/etc/nginx/conf.d/sales-claw.conf:ro" -v "${PWD}/deploy/nginx/limits.conf:/etc/nginx/conf.d/limits.conf:ro" nginx:alpine nginx -t
```

Erwartet: `syntax is ok` und `test is successful`.

- [ ] **Schritt 6: fail2ban-Dateien schreiben**

`deploy/fail2ban/sales-claw-filter.conf`:

```ini
# Ablegen unter: /etc/fail2ban/filter.d/sales-claw.conf
[Definition]
failregex = ^<HOST> .* "(GET|POST|PUT|DELETE)[^"]*" (401|403) 
ignoreregex =
```

`deploy/fail2ban/sales-claw.local`:

```ini
# Ablegen unter: /etc/fail2ban/jail.d/sales-claw.local
# Neu laden:     sudo systemctl reload fail2ban
[sales-claw-auth]
enabled  = true
filter   = sales-claw
port     = http,https
logpath  = /var/log/nginx/sales-claw.access.log
maxretry = 5
findtime = 300
bantime  = 3600
action   = iptables-multiport[name=sales-claw, port="http,https"]
```

- [ ] **Schritt 7: `deploy/systemd/sales-claw.service` schreiben**

```ini
[Unit]
Description=sales-claw (OpenClaw-Container fuer den Vertriebsarbeitsplatz)
Documentation=https://github.com/Flissel/sales-claw
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=true
User=debian
WorkingDirectory=/home/debian/sales-claw/repo
Environment=DOCKER_HOST=unix:///run/user/1000/docker.sock
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.proxmox.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.proxmox.yml down
TimeoutStartSec=300

# Haertung. Bewusst schwaecher als beim Node-Dienst im Hotel-Repo: hier startet
# systemd nur den Compose-Aufruf, die eigentliche Isolation leistet Docker.
NoNewPrivileges=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

`DOCKER_HOST` zeigt auf den rootless Socket des Users `debian`
(Koordinations-Board, 2026-08-04) — ohne diese Zeile trifft der Aufruf den
System-Daemon und damit die falschen Container.

- [ ] **Schritt 8: `deploy/provision.sh` schreiben**

```bash
#!/usr/bin/env bash
#
# Bereitet einen Debian-Host fuer sales-claw vor.
#
# Aufruf als root:  sudo bash deploy/provision.sh [--with-nginx]
#
# Was das Skript tut:
#   • Verzeichnisse /home/debian/sales-claw/{state,keys,repo,backups} anlegen
#   • Env-Datei /etc/sales-claw/env mit 0640 vorbereiten
#   • systemd-Unit installieren (nicht starten)
#   • optional nginx + fail2ban einrichten
#
# Was es NICHT tut:
#   • Container starten, Zustand kopieren, TLS beantragen, Claim setzen.
#     Das sind Entscheidungen, keine Automatismen.
set -euo pipefail

WITH_NGINX=0
for arg in "$@"; do
  case "$arg" in
    --with-nginx) WITH_NGINX=1 ;;
    -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
    *) echo "Unbekanntes Argument: $arg" >&2; exit 2 ;;
  esac
done

[[ "$EUID" -eq 0 ]] || { echo "Als root ausfuehren." >&2; exit 1; }

BASIS=/home/debian/sales-claw
install -d -o debian -g debian "$BASIS"/{state,keys,repo,backups}
echo "Verzeichnisse unter $BASIS angelegt."

install -d -m 750 /etc/sales-claw
if [[ ! -f /etc/sales-claw/env ]]; then
  cat > /etc/sales-claw/env <<'EOF'
OPENAI_API_KEY=
TZ=Europe/Berlin
EOF
  chmod 640 /etc/sales-claw/env
  echo "/etc/sales-claw/env angelegt — Schluessel eintragen."
else
  echo "/etc/sales-claw/env existiert bereits — unveraendert gelassen."
fi

install -m 644 deploy/systemd/sales-claw.service /etc/systemd/system/sales-claw.service
systemctl daemon-reload
echo "systemd-Unit installiert (nicht aktiviert)."

if [[ "$WITH_NGINX" -eq 1 ]]; then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx fail2ban certbot python3-certbot-nginx
  install -m 644 deploy/nginx/limits.conf     /etc/nginx/conf.d/limits.conf
  install -m 644 deploy/nginx/sales-claw.conf /etc/nginx/sites-available/sales-claw.conf
  ln -sf /etc/nginx/sites-available/sales-claw.conf /etc/nginx/sites-enabled/sales-claw.conf
  install -m 644 deploy/fail2ban/sales-claw-filter.conf /etc/fail2ban/filter.d/sales-claw.conf
  install -m 644 deploy/fail2ban/sales-claw.local       /etc/fail2ban/jail.d/sales-claw.local
  nginx -t
  echo "nginx und fail2ban eingerichtet. Reload und TLS bewusst nicht automatisch."
fi

echo "Fertig. Naechster Schritt: docs/07_PROXMOX_MIGRATION.md."
```

- [ ] **Schritt 9: Bash-Syntax prüfen**

```bash
docker run --rm -v "${PWD}/deploy:/deploy:ro" alpine:3.20 sh -c "apk add --no-cache bash >/dev/null && bash -n /deploy/provision.sh && echo syntax-ok"
```

Erwartet: `syntax-ok`.

- [ ] **Schritt 10: `docs/06_SECURITY.md` schreiben**

Mindestens diese Punkte, jeder mit Begründung:

1. **Secrets liegen nicht in der Konfiguration.** Auf der VM konnte ein Agent
   `openclaw.json` lesen und den `OPENAI_API_KEY` sehen, obwohl die Sandbox als aktiv
   gemeldet wurde. Was in der Konfiguration steht, hat der Agent.
2. **Die Agenten-Sandbox ist kein Nachweis.** `sandbox explain` bestätigt nur die
   Absicht. Nur der Griff des Agenten selbst belegt, ob sie greift.
3. **Port nur auf Loopback.** Der Gateway hält WhatsApp-Session und Modellschlüssel.
4. **`plugins.allow` minimal halten** — jedes geladene Plugin ist Angriffsfläche.
5. **Schlüsselrotation** — Anlass: Personalwechsel, Geräteverlust, Verdacht.
6. **Was noch offen ist:** Auftragsverarbeitung mit dem Modellanbieter,
   WhatsApp-Zugangsweg über Baileys, Prompt-Injection über eingehende Nachrichten und
   Dokumente (Spec §12).

- [ ] **Schritt 11: `docs/07_PROXMOX_MIGRATION.md` schreiben**

Schritt-für-Schritt-Anleitung mit konkreten Befehlen:

1. **Claim setzen** in `secondbrain/00_Meta/002_Koordination_Live.md` unter *In Arbeit*
   und sofort committen.
2. Sicherung lokal ziehen (`scripts/backup-state.ps1`), Archiv auf die VM übertragen.
3. `sudo bash deploy/provision.sh` auf der VM.
4. Zustand nach `/home/debian/sales-claw/{state,keys}` entpacken, Eigentümer setzen.
5. Lokalen Container stoppen — **vorher**, wegen der Sitzungskonflikte bei zwei
   gleichzeitigen Baileys-Verbindungen.
6. Auf der VM starten:
   `docker compose -f docker-compose.yml -f docker-compose.proxmox.yml up -d`.
7. Prüfen: `openclaw --container sales-claw channels status`.
8. Bekannte Stolpersteine: DooD-Pfadbedingung, rootless Socket
   (`DOCKER_HOST=unix:///run/user/1000/docker.sock`), CLI-Kontext auf `default`,
   Plugin-Neuinstallation mit `npm_config_cache=/tmp/.npm` bei
   `openKeyedStore is only available for trusted plugins`.
9. Rückweg: lokal wieder starten, VM-Container stoppen.
10. Claim nach *Erledigt* verschieben und committen.

- [ ] **Schritt 12: Committen**

```bash
git add docker-compose.proxmox.yml deploy docs/06_SECURITY.md docs/07_PROXMOX_MIGRATION.md
git commit -m "feat(deploy): Serverartefakte und Migrationsanleitung fuer die Proxmox-VM"
```

---

## Selbstprüfung des Plans

**Abdeckung gegen die Spec:**

| Spec-Abschnitt | Umgesetzt in |
|---|---|
| §2 Ziel, Abgrenzung | Task 2 (Container), Abgrenzung durchgehend eingehalten |
| §5 Architektur, zwei Volumes | Task 2 Schritt 2, Task 3 (beide Volumes gesichert) |
| §5 Instanz-Zuschnitt | Task 2 Schritt 8, Task 5 Kriterium 6 |
| §6 Repository-Layout | Alle Tasks; Dateistruktur oben |
| §7 Konfiguration (Image-Pin, Port, Volumes, Neustart, Plugins, Speicher, Logging, Healthcheck, Zeitzone) | Task 2 Schritt 1 und 2 |
| §7 Secrets | Task 1 Schritt 2 (`.env.example`), Task 2 Schritt 6 (Token im Container) |
| §8 Kopplung übernehmen | Task 4 |
| §9 Kriterium 1, 2, 3, 6 | Task 5 |
| §9 Kriterium 4 (Versionssprung) | Task 5 Schritt 1 |
| §9 Kriterium 5 (Wiederherstellung) | Task 3 (Mechanik) und Task 6 (echte Kopplung) |
| §10 Proxmox-Vorbereitung | Task 7 |
| §11 Risiken | Task 4 (zwei Sitzungen), Task 2 (Pin), Task 1 (Plattenplatz), Task 7 (Secrets) |
| §12 offene Punkte | `docs/06_SECURITY.md` (Task 7 Schritt 10) |

**Lücke, bewusst offen gelassen:** Spec §12.5 (Gateway-Port-Widerspruch) wird in Task 2
Schritt 7 gemessen statt vorab entschieden. Weicht der Wert ab, korrigiert derselbe
Schritt Plan, Compose und Spec.

**Platzhalter-Prüfung:** Keine „TBD", keine „geeignete Fehlerbehandlung ergänzen",
keine „Tests wie oben". Jeder Code-Schritt enthält den vollständigen Inhalt. Die drei
Dokumentationsschritte, die nur eine Gliederung vorgeben (Task 4 Schritt 7, Task 7
Schritt 10 und 11), nennen die geforderten Punkte einzeln und namentlich.

**Typ- und Namenskonsistenz:** Volume-Namen `sales-claw-state` / `sales-claw-keys`,
Container `sales-claw`, Port `18894` und die Skript-Parameter (`-Quelle`, `-Ziel`,
`-GatewayPort`, `-Container`) sind über alle Tasks hinweg identisch. Die
Sicherungsdateinamen `state.tar` / `keys.tar` werden in Task 3 erzeugt und in Task 3
und 6 unter demselben Namen gelesen.

---

## Task 8: Modellanbieter auf OpenRouter umstellen

Nachträglich eingefügt auf Vorgabe des Betreibers. **Muss vor Task 5 laufen** — dort
wird zum ersten Mal eine echte Antwort erzeugt. Die Nummer folgt der Reihenfolge des
Einfügens, nicht der Ausführung; das Ledger hält die tatsächliche Reihenfolge fest.

**Hintergrund:** Auf dem vorhandenen OpenAI-Schlüssel liegt kein Guthaben. Bis ein
eigener Schlüssel existiert, läuft der Rauchtest über OpenRouters kostenlose Modelle.
OpenClaw hat dafür einen **nativen Provider** — kein Umweg über `OPENAI_BASE_URL`, und
die Randbedingung „kein lokales Modell" bleibt unberührt, weil OpenRouter gehostet ist.

**Dateien:**
- Neu: `scripts/seed-env.ps1`
- Ändern: `.env.example`
- Ändern: `config/openclaw.json`
- Ändern: `docs/02_ARCHITECTURE.md`

**Schnittstellen:**
- Konsumiert: laufender Container `sales-claw` aus Task 2.
- Produziert: `scripts/seed-env.ps1` → schreibt `.env` mit `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY` und `TZ`; Exit `0`. **Gibt niemals einen Schlüsselwert aus**,
  sondern nur „uebernommen" oder „NICHT gefunden".

- [ ] **Schritt 1: `scripts/seed-env.ps1` schreiben**

```powershell
#requires -Version 7
<#
.SYNOPSIS
  Uebernimmt vorhandene API-Schluessel aus der lokalen OpenClaw-Konfiguration
  in die .env dieses Projekts.
.NOTES
  Schluesselwerte werden NIE ausgegeben — weder auf die Konsole, noch in ein
  Log, noch in eine Fehlermeldung. Das Skript meldet ausschliesslich, ob ein
  Schluessel gefunden wurde.
#>
[CmdletBinding()]
param(
    [string]$Quelle = "$env:USERPROFILE\.openclaw\openclaw.json",
    [string]$Ziel   = "$PSScriptRoot\..\.env"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Quelle)) { throw "Quelle nicht gefunden: $Quelle" }
$cfg = Get-Content -Raw -Encoding UTF8 $Quelle | ConvertFrom-Json

# Den OpenRouter-Schluessel am Praefix erkennen, nicht am Ablageort: in dieser
# Installation liegt er unter einem Skill-Eintrag, dessen Name ihn nicht
# erwarten laesst. Das Praefix ist das verlaessliche Merkmal.
$openrouter = $null
foreach ($e in $cfg.skills.entries.PSObject.Properties) {
    if ($e.Value.apiKey -is [string] -and $e.Value.apiKey.StartsWith('sk-or-v1-')) {
        $openrouter = $e.Value.apiKey
        break
    }
}
$openai = $cfg.env.OPENAI_API_KEY

$zeilen = @(
    '# Erzeugt von scripts/seed-env.ps1. Enthaelt Geheimnisse — nicht versionieren.',
    'TZ=Europe/Berlin',
    "OPENROUTER_API_KEY=$openrouter",
    "OPENAI_API_KEY=$openai"
)
$zielVoll = [System.IO.Path]::GetFullPath($Ziel)
Set-Content -Path $zielVoll -Value $zeilen -Encoding utf8

# Vererbte Rechte entfernen, nur der aktuelle Benutzer darf lesen und schreiben.
icacls $zielVoll /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

Write-Host ("OPENROUTER_API_KEY: " + $(if ($openrouter) { 'uebernommen' } else { 'NICHT gefunden' }))
Write-Host ("OPENAI_API_KEY:     " + $(if ($openai)     { 'uebernommen' } else { 'NICHT gefunden' }))
Write-Host "Geschrieben nach $zielVoll"
exit 0
```

- [ ] **Schritt 2: `.env.example` um OpenRouter ergänzen**

Ersetze den Abschnitt zum Modellanbieter durch:

```bash
# ---------------------------------------------------------------------------
# Modellanbieter. Der Agent im Container liest diese Variablen aus der
# Umgebung, NICHT aus config/openclaw.json — siehe Spec §7 "Secrets".
#
# Bis ein eigener, guthabengedeckter Schluessel existiert, laeuft der
# Rauchtest ueber OpenRouters kostenlose Modelle.
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY=sk-or-v1-...
OPENAI_API_KEY=

# ---------------------------------------------------------------------------
# OPENAI_BASE_URL wird bewusst NICHT gesetzt. Ein lokal laufendes Modell ist
# fuer dieses Projekt ausgeschlossen — die Maschine traegt es nicht. Zeigt
# diese Variable je auf einen lokalen Endpunkt, ist das ein Fehler, keine
# Option. OpenRouter braucht sie nicht: OpenClaw hat einen eigenen Provider.
# ---------------------------------------------------------------------------
```

- [ ] **Schritt 3: Primärmodell in `config/openclaw.json` umstellen**

```json
"model": { "primary": "openrouter/free" }
```

`openrouter/free` routet automatisch über die kostenlosen Modelle und ist dadurch
unempfindlich gegen das Rate-Limit eines einzelnen. Das ist eine **bewusste Ausnahme**
von der Pin-Regel dieses Projekts und gilt nur, solange niemand mit echten Kunden
spricht. Sobald echte Beratungsgespräche laufen, wird hier ein bezahltes, gepinntes
Modell eingetragen.

- [ ] **Schritt 4: Rot — nachweisen, dass der Schlüssel noch fehlt**

```bash
docker compose exec sales-claw sh -lc 'test -n "$OPENROUTER_API_KEY" && echo gesetzt || echo fehlt'
```

Erwartet: `fehlt`.

- [ ] **Schritt 5: Grün — Schlüssel übernehmen und Container neu starten**

```bash
pwsh -File scripts/seed-env.ps1
```

Erwartet: `OPENROUTER_API_KEY: uebernommen`. Meldet es `NICHT gefunden`, ist das ein
echter Befund — melden, statt einen Schlüssel von anderswo zu beschaffen.

```bash
docker compose down
pwsh -File scripts/seed-volume.ps1
docker compose up -d
```

Warten, dann:

```bash
docker compose exec sales-claw sh -lc 'test -n "$OPENROUTER_API_KEY" && echo gesetzt || echo fehlt'
```

Erwartet: `gesetzt`. **Den Wert selbst nicht ausgeben.**

- [ ] **Schritt 6: Provider und Modell verifizieren**

```bash
docker compose exec sales-claw openclaw infer model providers
```

Erwartet: `openrouter` erscheint in der Liste.

```bash
docker compose exec sales-claw openclaw config get agents.defaults.model.primary
```

Erwartet: `openrouter/free`.

- [ ] **Schritt 7: Echte Antwort erzeugen — ohne dass etwas nach außen geht**

```bash
docker compose exec sales-claw openclaw agent -m "Antworte ausschliesslich mit dem Wort: pong" --json
```

Erwartet: eine JSON-Antwort, die `pong` enthält. **`--deliver` wird bewusst
weggelassen** — ohne dieses Flag geht keine Nachricht an WhatsApp oder einen anderen
Kanal hinaus. Geprüft wird das Modell, nicht der Versandweg.

Scheitert der Aufruf an einem Rate-Limit, ist das kein Umsetzungsfehler — kostenlose
Modelle haben Tageskontingente. Ausgabe festhalten, erneut versuchen, und wenn es
bestehen bleibt, melden.

- [ ] **Schritt 8: `docs/02_ARCHITECTURE.md` um „Modellanbieter" ergänzen**

Inhalt: der native OpenRouter-Provider und warum kein `OPENAI_BASE_URL` nötig ist; die
Begründung für `openrouter/free` als bewusste Ausnahme von der Pin-Regel; der Hinweis,
dass das Free-Tier-Kontingent mit anderen Nutzern desselben Schlüssels geteilt wird;
und die ausdrückliche Feststellung, dass ein kostenloses, automatisch geroutetes
Modell für echte Beratungsgespräche nicht geeignet ist.

- [ ] **Schritt 9: Committen**

```bash
git add scripts/seed-env.ps1 .env.example config/openclaw.json docs/02_ARCHITECTURE.md
git commit -m "feat(modell): auf OpenRouter umstellen, Rauchtest ueber kostenlose Modelle"
```
