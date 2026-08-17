# 05 — Notfallwiederherstellung

Vier Fälle, die in diesem Vorhaben realistisch eintreten können, jeweils mit
konkreten Befehlen. Für den Alltagsbetrieb siehe `docs/03_RUNBOOK.md`, für die
Sicherungsmechanik `docs/04_BACKUP_RESTORE.md`.

## Vor jedem Fall: die Reihenfolge-Regel

Es darf immer nur **eine** Instanz die WhatsApp-Kopplung benutzen. Zwei
Baileys-Sitzungen auf denselben Session-Dateien melden das verknüpfte Gerät ab
— und danach hilft kein Restore mehr, sondern nur noch Fall 1. Deshalb gilt in
jedem Notfall: **erst die eine Seite nachweislich stoppen, dann die andere
starten.** Nie umgekehrt, nie gleichzeitig.

## Was an Rückwegen vorliegt

| Rückweg | Pfad | Enthält |
|---|---|---|
| OpenClaw-Archiv der lokalen Installation | `2026-08-17T19-16-40.033Z-openclaw-backup.tar.gz` (Repo-Wurzel) | vollständiger Host-Zustand inkl. `credentials/whatsapp` (8003 Dateien), mit `openclaw backup verify` geprüft |
| Rohkopie vor dem Stopp | `credentials-sicherung-host-20260817-211935/` | `credentials/` des Hosts, im laufenden Betrieb kopiert |
| Rohkopie nach dem Stopp | `credentials-sicherung-20260817-212343/` | `credentials/` des Hosts, **stillgelegt** kopiert — der belastbarere der beiden |
| Volume-Sicherungen | `backups/sales-claw-<zeitstempel>/` | `state.tar`, `keys.tar`, `MANIFEST.json` |

Alle vier sind gitignored und enthalten Sitzungsdaten im Klartext.

**Die Rohkopie nach dem Stopp ist der bevorzugte Weg für alles, was die
Kopplung betrifft.** Eine im laufenden Betrieb erstellte Kopie kann eine
halb geschriebene Session-Datei enthalten — strukturell fehlerfrei, inhaltlich
tot, und keine Prüfung bemerkt das.

---

## Fall 1 — Kopplung verloren

**Symptom:** `channels status` meldet WhatsApp als nicht angemeldet; im Log
stehen Sitzungskonflikte oder `logged out`; Nachrichten kommen nicht mehr an.

**Ursache in aller Regel:** Doppelbetrieb (zwei Instanzen auf denselben
Credentials), ein `channels logout`, oder Abmeldung im WhatsApp-Menü
„Verknüpfte Geräte" am Telefon.

**Wichtig:** Ist die Kopplung serverseitig beendet, hilft **kein** Restore der
Session-Dateien. Die Dateien beschreiben eine Sitzung, die es bei WhatsApp
nicht mehr gibt. Der einzige Weg ist neu koppeln — und dafür wird das Telefon
gebraucht.

```powershell
# 1. Sicherstellen, dass NUR der Container läuft
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18793"   # muss True sein
docker compose ps                                                       # sales-claw: Up (healthy)

# 2. Zustand ansehen, bevor irgendetwas neu gekoppelt wird
openclaw --container sales-claw channels status
openclaw --container sales-claw channels logs

# 3. Erst wenn der Verlust bestätigt ist: neu koppeln, QR am Telefon scannen
openclaw --container sales-claw channels login --channel whatsapp
```

`channels login` zeigt einen QR-Code, der im WhatsApp-Menü
„Verknüpfte Geräte → Gerät verknüpfen" gescannt wird. Danach unbedingt sofort
sichern, damit die neue Kopplung einen Rückweg hat:

```powershell
pwsh -File scripts/backup-state.ps1
```

**Nicht auf Verdacht neu koppeln.** Ein `channels login` auf eine noch intakte
Kopplung ersetzt sie — der Befund aus Schritt 2 muss vorliegen.

---

## Fall 2 — Zustand verloren

**Symptom:** `docker compose ps` meldet `Restarting`; `openclaw.json` fehlt im
Volume; Konfiguration, Gateway-Token oder Modellkatalog sind weg. Typische
Ursachen: versehentlich gelöschtes Volume, defekter Schreibvorgang, misslungene
Migration.

```powershell
# 1. Container anhalten — restore-state.ps1 weigert sich sonst
docker compose down

# 2. Verfügbare Sicherungen ansehen (nur Ordner MIT MANIFEST.json sind brauchbar)
Get-ChildItem backups\ -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'MANIFEST.json') } |
    Sort-Object Name -Descending | Select-Object Name

# 3. Zurückspielen
pwsh -File scripts/restore-state.ps1 -Quelle backups\sales-claw-<zeitstempel>

# 4. Hochfahren und abwarten
docker compose up -d
docker compose ps        # erwartet nach ~35 s: Up ... (healthy)
```

`restore-state.ps1` prüft **beide** Archive vollständig gegen `MANIFEST.json`
(Größe, SHA-256, Eintragszahl) und entpackt sie probeweise, **bevor** es
irgendein Volume anfasst. Schlägt eine Prüfung fehl, bricht es ab und lässt
beide Volumes unverändert — dann die nächstältere Sicherung nehmen. Eine
Sicherung ohne `MANIFEST.json` wird abgelehnt; das betrifft alle Ordner aus
Läufen vor Fix-Runde 4 (Begründung in `docs/04_BACKUP_RESTORE.md`).

Warnt das Skript mit `Diese Sicherung entstand bei laufendem Container`, dann
kann die enthaltene WhatsApp-Sitzung tot sein, obwohl alle Prüfungen bestehen.
Wenn möglich eine Sicherung mit `container_gestoppt: true` wählen.

---

## Fall 3 — Rückweg zur lokalen Installation

**Wann:** Der Container-Weg funktioniert nicht und der Betrieb muss zurück auf
die lokale Installation (Host, npm, 2026.5.18, Gateway `127.0.0.1:18793`).

**Die Reihenfolge ist hier die Sicherheit — sie ist die exakte Umkehrung der
Übernahme aus Task 4.** Der Container muss **zuerst** stehen. Wer den lokalen
Gateway startet, während der Container läuft, erzeugt genau den Doppelbetrieb,
der die Kopplung kostet — und landet dann in Fall 1.

```powershell
# 1. ZUERST den Container stoppen und den Stillstand prüfen
docker compose down
docker ps --filter "name=^sales-claw$" --format '{{.Names}}'   # muss leer sein
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18894"   # muss True sein

# 2. Vorhandenen (womöglich defekten) Stand beiseitelegen statt überschreiben.
#    Copy-Item -Force verschmilzt zwei Verzeichnisse, statt das Ziel zu
#    ersetzen — dabei überleben alte Session-Dateien, die nicht mehr zur
#    zurückgespielten Sitzung passen. Nichts löschen, nur umbenennen.
$ziel = "$env:USERPROFILE\.openclaw\credentials\whatsapp"
if (Test-Path $ziel) { Rename-Item $ziel "whatsapp-alt-$(Get-Date -Format yyyyMMdd-HHmmss)" }

# 3. Credentials zurückspielen (bevorzugt die im Stillstand erstellte Rohkopie)
Copy-Item -Recurse `
    'credentials-sicherung-20260817-212343\whatsapp' `
    "$env:USERPROFILE\.openclaw\credentials\whatsapp"

# 4. Gegenprobe: Dateizahl muss zur Sicherung passen
(Get-ChildItem -Recurse -File -Force $ziel).Count
(Get-ChildItem -Recurse -File -Force 'credentials-sicherung-20260817-212343\whatsapp').Count

# 5. ERST JETZT den lokalen Gateway starten
openclaw daemon start

# 6. Nachweisen, dass er wirklich läuft
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18793"   # muss False sein
Get-NetTCPConnection -LocalPort 18793 -State Listen | Select-Object LocalPort, OwningProcess
openclaw daemon status
openclaw channels status
```

Muss statt einzelner Credentials der **komplette** Host-Zustand zurück, führt
der Weg über das geprüfte OpenClaw-Archiv:

```powershell
openclaw backup verify 2026-08-17T19-16-40.033Z-openclaw-backup.tar.gz
```

Das Archiv liegt unter `payload/windows/...` und enthält `state: ~\.openclaw`
sowie `workspace: ~\clawd`. Es wird **bei gestopptem lokalem Gateway**
ausgepackt, nie im laufenden Betrieb.

Solange die lokale Installation den Betrieb trägt, bleibt der Container unten.
Beide gleichzeitig gibt es nicht.

---

## Fall 4 — `openKeyedStore is only available for trusted plugins`

**Symptom:** Der WhatsApp-Kanal startet nicht; im Log steht
`openKeyedStore is only available for trusted plugins`.

**Ursache** (Koordinations-Board, 2026-08-04): Die Installationsspur des
WhatsApp-Plugins zeigt auf einen alten Pfad. Das Plugin gilt dem Gateway
dadurch als nicht vertrauenswürdig und bekommt keinen Zugriff auf den
Schlüsselspeicher — obwohl Credentials und Konfiguration in Ordnung sind.

**Ohne diesen Eintrag kostet die Diagnose Stunden**, weil das Fehlerbild nach
einem Credential- oder Rechteproblem aussieht und man an der falschen Stelle
sucht. Es ist keines.

**Erst den Befund erheben** — die Installationsspur steht in der persistierten
Plugin-Registry, und daraus ergibt sich die genaue Bezeichnung, die im
Reparaturbefehl einzusetzen ist:

```powershell
openclaw --container sales-claw plugins doctor      # meldet Ladeprobleme
openclaw --container sales-claw plugins list        # Name/Spec und Pfad
openclaw --container sales-claw plugins registry    # die gespeicherte Spur
```

Zeigt der Pfad in `plugins list`/`registry` auf ein Verzeichnis, das es im
Container nicht gibt, ist die Ursache bestätigt.

**Behebung — Plugin im Container neu installieren, mit gesetztem npm-Cache.**
`<spec>` ist dabei die Bezeichnung aus `plugins list` (Paketname oder Pfad),
nicht geraten:

```powershell
docker exec -e npm_config_cache=/tmp/.npm sales-claw `
    openclaw plugins install <spec> --force

docker compose restart sales-claw
docker compose logs -f sales-claw
openclaw --container sales-claw plugins doctor
openclaw --container sales-claw channels status
```

`npm_config_cache=/tmp/.npm` ist der entscheidende Teil: ohne einen
beschreibbaren Cache-Pfad bricht die Installation im Container ab oder
hinterlässt erneut eine Installationsspur, die auf einen Pfad außerhalb des
Containers zeigt — und das Fehlerbild kehrt unverändert zurück.

**Die Credentials werden dabei nicht angefasst.** Es ist ein Plugin-Problem,
kein Kopplungsproblem — `channels login` ist hier die falsche Antwort und
würde eine intakte Kopplung wegwerfen.

---

## Wenn keiner der vier Fälle passt

Nichts erraten und nichts „mal ausprobieren", solange die Kopplung im Spiel
ist. Der Zustand ist gesichert (siehe Tabelle oben) — den Befund aufnehmen und
dem Betreiber vorlegen:

```powershell
docker compose ps
docker compose logs --tail 200 sales-claw
openclaw --container sales-claw doctor
openclaw --container sales-claw channels status
pwsh -Command ". ./scripts/lib/ports.ps1; 'Port 18793 frei: ' + (Test-PortFrei -Port 18793); 'Port 18894 frei: ' + (Test-PortFrei -Port 18894)"
```

Ausgaben dieser Befehle können Kanal- und Kontaktkennungen enthalten — vor dem
Weitergeben durchsehen. Schlüssel- und Token-**Inhalte** gehören in keinen
Bericht; Dateinamen, Größen und Zähler genügen.
