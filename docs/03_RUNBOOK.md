# 03 — Runbook

Der Alltagsbetrieb von `sales-claw`: starten, stoppen, nachsehen, diagnostizieren.
Für Sicherung und Wiederherstellung siehe `docs/04_BACKUP_RESTORE.md`, für den
Ernstfall `docs/05_DISASTER_RECOVERY.md`.

## Die Regel, die über allen anderen steht

**Es darf immer nur eine Instanz die WhatsApp-Kopplung benutzen.**

Die Kopplung liegt als Baileys-Session unter `credentials/whatsapp/default`.
Melden sich zwei Prozesse mit denselben Session-Dateien bei WhatsApp an, wertet
WhatsApp das als Sitzungskonflikt und **meldet das verknüpfte Gerät ab**. Die
Kopplung ist dann weg und lässt sich nur per QR-Scan am gekoppelten Telefon
wiederherstellen (`docs/05_DISASTER_RECOVERY.md`, Fall 1). Kein Skript und kein
Restore holt sie zurück.

Auf dieser Maschine gibt es genau zwei Kandidaten, die das auslösen können:

| Instanz | Zustand | Gateway |
|---|---|---|
| Lokale Installation (Host, npm, 2026.5.18) | **gestoppt** — seit Task 4 | `127.0.0.1:18793` |
| Container `sales-claw` (2026.7.1-slim) | der produktive Weg | `127.0.0.1:18894` |

Daraus folgt die Reihenfolge-Regel für jeden Eingriff, der beide Seiten berührt:

1. **Erst sichern.** `openclaw backup create` auf dem Host **und**
   `openclaw backup verify <archiv>`. Schlägt die Verifikation fehl, wird
   nichts gestoppt und nichts übernommen.
2. **Dann stoppen.** Die Instanz, die die Credentials abgibt, muss stehen —
   und der Stillstand wird **geprüft, nicht angenommen**
   (`scripts/stop-local-openclaw.ps1`).
3. **Dann erst übernehmen.** Credentials kopieren
   (`scripts/migrate-credentials.ps1`).

Diese Reihenfolge umzudrehen kostet die Kopplung. Sie ist kein Vorschlag.

### ⚠ Offener Punkt: die lokale Installation startet sich beim Anmelden selbst

Der lokale Gateway läuft nicht als freier Prozess, sondern als
**Windows-Aufgabe `\OpenClaw Gateway`** — und diese Aufgabe hat einen
**aktiven Anmelde-Trigger**:

```powershell
Get-ScheduledTask -TaskName 'OpenClaw Gateway' |
    ForEach-Object { $_.Triggers } |
    Select-Object @{n='Typ';e={$_.CimClass.CimClassName}}, Enabled
# MSFT_TaskLogonTrigger   True
```

`openclaw daemon stop` beendet den **laufenden** Task, entfernt aber den
Trigger nicht. Stand heute ist die Aufgabe `Ready` (gestoppt) — **bei der
nächsten Windows-Anmeldung startet sie von selbst wieder**, mit denselben
Credentials, die inzwischen auch im Volume `sales-claw-state` liegen.

Läuft in diesem Moment der Container, ist das exakt der Doppelbetrieb aus der
Regel oben: zwei Baileys-Sitzungen auf denselben Session-Dateien, und die
Kopplung ist weg.

**Das ist bewusst nicht eigenmächtig geändert worden** — den Autostart einer
produktiv genutzten Installation abzuschalten ist eine Entscheidung des
Betreibers. Er muss sie aber treffen, bevor der Container dauerhaft läuft.
Zur Auswahl stehen:

```powershell
# Variante A: nur den Trigger abschalten, Aufgabe bleibt bestehen
Disable-ScheduledTask -TaskName 'OpenClaw Gateway'

# Variante B: den Dienst regulär deinstallieren (OpenClaws eigener Weg)
openclaw daemon uninstall
```

Bis dahin gilt: **nach jeder Windows-Anmeldung zuerst prüfen**, ob der lokale
Gateway wieder läuft, bevor der Container gestartet wird.

```powershell
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18793"   # muss True sein
```

Ist er hochgekommen: `pwsh -File scripts/stop-local-openclaw.ps1`, und erst
danach `docker compose up -d`.

### Was in diesem Zusammenhang niemals getan wird

- **Kein `openclaw daemon start` auf dem Host, solange der Container läuft.**
  Das ist genau der Doppelbetrieb, den die Regel oben verhindert. Wer den
  Rückweg antreten will, stoppt **zuerst** den Container
  (`docker compose down`) — siehe `05_DISASTER_RECOVERY.md`, Fall 3.
- **Kein `openclaw channels logout`.** Der Befehl beendet die Kopplung
  serverseitig; auch ein Restore der Session-Dateien holt sie danach nicht
  zurück.
- **Keine Prozesse gewaltsam beenden** (`Stop-Process`, `taskkill`). Bleibt
  Port 18793 nach `openclaw daemon stop` belegt, ist das eine Entscheidung des
  Betreibers, keine des Skripts — `stop-local-openclaw.ps1` legt den Prozess
  vor und bricht mit Exit `1` ab.
- **Keine Sammelbefehle.** Kein `docker volume prune`, kein
  `docker system prune`. Auf dieser Maschine laufen 23 fremde Container; das
  Volume `openclaw-festival-state` gehört einem anderen Vorhaben und ist tabu.

## Starten

```powershell
cd C:\Users\User\Desktop\Sabine\sales-claw
docker compose up -d
```

Danach den Hochlauf abwarten — der Healthcheck hat eine `start_period` von 60 s,
`healthy` erscheint typischerweise nach rund 35 s:

```powershell
docker compose ps
# erwartet: sales-claw   Up ... (healthy)
```

Ist der Status nach zwei Minuten noch nicht `healthy` oder steht dort
`Restarting`, dann fehlt dem Container in aller Regel seine Konfiguration —
weiter bei „Diagnose" und `05_DISASTER_RECOVERY.md`, Fall 2.

## Stoppen

```powershell
docker compose down
```

Entfernt Container und Netzwerk, **behält die Volumes**
(`sales-claw-state`, `sales-claw-keys`). Das ist der reguläre Weg vor jedem
Eingriff, der ins Volume schreibt (`restore-state.ps1`,
`migrate-credentials.ps1`) — beide Skripte prüfen selbst, dass der Container
steht, und brechen sonst ab.

Nur anhalten, ohne zu entfernen:

```powershell
docker stop sales-claw
docker start sales-claw
```

## Logs

Container-Logs (stdout/stderr, rotierend, 3 × 10 MB — siehe
`docker-compose.yml`):

```powershell
docker compose logs -f sales-claw
```

Gateway-eigene Logdatei, über die CLI **im Container**:

```powershell
openclaw --container sales-claw logs
openclaw --container sales-claw logs --follow
```

Beides ergänzt sich: `docker compose logs` zeigt, was der Prozess nach außen
schreibt (inklusive Startfehlern, bevor der Gateway überhaupt läuft),
`openclaw ... logs` zeigt die Gateway-Logdatei über RPC — das setzt einen
laufenden Gateway voraus. Bei einem Container in der Neustart-Schleife hilft
nur der erste Weg.

Nur Kanal-Ereignisse:

```powershell
openclaw --container sales-claw channels logs
```

## Kanalstatus

```powershell
openclaw --container sales-claw channels status
```

Zeigt die konfigurierten Kanäle und ihren Anmeldezustand. Das ist der Befehl,
mit dem sich beantworten lässt, ob die WhatsApp-Kopplung steht — ohne eine
Nachricht zu senden.

Tiefer, mit aktiven Prüfungen:

```powershell
openclaw --container sales-claw channels status --probe
```

## Diagnose

```powershell
openclaw --container sales-claw doctor
```

Prüft Konfiguration, Gateway, Plugins und Kanäle und benennt konkrete
Reparaturen. **`doctor --fix` bzw. `--repair` nicht ungeprüft ausführen** — die
Reparaturen greifen in Konfiguration und Dienstinstallation ein. Erst den
Befund lesen, dann entscheiden.

Kurzer Gesamtstatus und Gesundheitsabfrage:

```powershell
openclaw --container sales-claw status
openclaw --container sales-claw health
docker inspect --format '{{.State.Health.Status}}' sales-claw
```

`openclaw --container <name>` führt die CLI **innerhalb** des laufenden
Containers aus. Läuft der Container nicht, schlägt jeder dieser Befehle fehl —
das ist kein Defekt, sondern die Voraussetzung. Maßgeblich ist dann die Version
im Container (2026.7.1), nicht die des Host-CLI (2026.5.18).

## Sicherung im Alltag

```powershell
pwsh -File scripts/backup-state.ps1
```

**Der Lauf stoppt den Container für wenige Sekunden** (gemessen 3,5 s) und
startet ihn danach wieder — das ist beabsichtigt, weil ein `tar` über laufende
Schreibvorgänge im Session-Store eine strukturell einwandfreie Sicherung mit
einer toten WhatsApp-Sitzung erzeugen kann. Vollständige Begründung, Manifest,
Aufbewahrung und der empfohlene tägliche Termin: `docs/04_BACKUP_RESTORE.md`.

## Zustand nachsehen, ohne etwas anzufassen

```powershell
# Läuft der lokale Host-Gateway? (soll: nein)
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18793"

# Liegt die Kopplung im Volume?
docker run --rm -v sales-claw-state:/state:ro alpine:3.20 `
    sh -c 'ls -ld /state/credentials/whatsapp; find /state/credentials/whatsapp -type f | wc -l'
```

`Test-PortFrei` aus `scripts/lib/ports.ps1` ist bewusst **nicht**
`Get-NetTCPConnection -ErrorAction SilentlyContinue`: dieses Cmdlet meldet
„kein Treffer" als Fehler, und mit unterdrücktem Fehler ist ein freier Port
nicht mehr von einem ausgefallenen Cmdlet zu unterscheiden — beide liefern
`$null`, beide würden zu „frei". Bei der Frage „darf ich jetzt die Credentials
anfassen?" ist das der Unterschied zwischen einer Prüfung und einem Ratespiel.

## Abnahme

Die sechs Kriterien aus Spec §9. Vier davon prüft `scripts/smoke-test.ps1`
selbst, zwei brauchen einen Menschen oder einen eigenen Ablauf.

```powershell
pwsh -File scripts/smoke-test.ps1
# Exit 0 = alle automatisch prüfbaren Kriterien erfüllt, Exit 1 = mindestens eines nicht
```

| # | Kriterium | Wie geprüft | Befehl |
|---|---|---|---|
| 1 | Start, Healthcheck `healthy` | automatisch | `docker inspect --format '{{.State.Health.Status}}' sales-claw` |
| 1b | Gateway lauscht auf 18894 | automatisch | `Test-PortFrei -Port 18894` → muss `False` sein |
| 2a | Gateway **kennt** den Kanal whatsapp | automatisch | `openclaw --container sales-claw channels status --json` |
| 2 | Kopplung verbunden | automatisch (Vorprüfung) | dieselbe JSON-Ausgabe |
| 2 | Selbst-Chat: Nachricht rein, Antwort raus | **von Hand** | siehe unten |
| 3 | Neustart-Festigkeit | halbautomatisch | Skript vor **und** nach `down`/`up` |
| 4 | Versionssprung 2026.5.18 → 2026.7.1 | einmalig | `docker compose exec sales-claw openclaw --version` |
| 5 | Restore-Roundtrip | eigener Ablauf | `docs/04_BACKUP_RESTORE.md`, Task 6 |
| 6 | Keine Kollateralschäden | automatisch | Projektlabel von `openclaw-festival`, Port 18793 frei |

### Warum Kriterium 2 nicht per Textsuche geprüft wird

Naheliegend wäre, den Klartext von `channels status` nach `whatsapp` zu
durchsuchen und das Fehlen von `logged out` als Entwarnung zu werten. **Das
liefert ein falsches Grün.** Ist das WhatsApp-Plugin gar nicht installiert,
enthält die Ausgabe trotzdem das Wort `whatsapp` — nämlich im Warnblock
`plugin not installed: whatsapp` — und mangels Kanal auch kein `logged out`.
Beide Teilbedingungen sind erfüllt, der Kanal existiert nicht. Gemessen am
2026.7.1-Container: der Ausdruck liefert `True`, während `channels status`
überhaupt keinen Kanal auflistet.

`--json` beantwortet die Frage stattdessen positiv: `channelOrder` führt nur
Kanäle, die ein geladenes Plugin tatsächlich besitzt. Erst wenn `whatsapp`
dort steht, wird auf Abmelde- und Pairing-Zustände gegengeprüft.

```powershell
openclaw --container sales-claw channels status --json
# "channelOrder": []  -> kein Plugin besitzt den Kanal
```

### Kriterium 3 — Neustart-Festigkeit

```powershell
pwsh -File scripts/smoke-test.ps1        # vorher
docker compose down
docker compose up -d                     # bis healthy warten
pwsh -File scripts/smoke-test.ps1        # nachher: gleiches Ergebnis
```

Ein neuer QR-Code darf dabei **nicht** erscheinen. Zusätzlich lässt sich
belegen, dass die Kopplung die Runde unverändert überstanden hat — gleiche
Dateizahl, gleiche Aggregat-Prüfsumme vor und nach dem Neustart:

```powershell
docker run --rm -v sales-claw-state:/state:ro alpine:3.20 sh -c `
    'find /state/credentials/whatsapp -type f | sort | xargs sha256sum | sha256sum'
```

### Kriterium 2 von Hand — der Selbst-Chat

Erst sinnvoll, **wenn Kriterium 2a grün ist**. Solange kein Plugin den Kanal
besitzt, kann keine Nachricht ankommen, und ein ausbleibender Umlauf beweist
nichts.

Vom Telefon eine Nachricht an die eigene Nummer senden (`selfChatMode`), zum
Beispiel `ping sales-claw`, und mitlesen:

```powershell
docker compose logs -f sales-claw
```

Erwartet: die eingehende Nachricht im Log **und** eine Antwort im WhatsApp-Chat.

### Antwortet das Modell?

Kommt die Nachricht an, bleibt die Antwort aber aus, liegt es meist am Modell,
nicht am Kanal. Diese drei Befehle trennen die beiden Fälle — **ohne**
`--deliver`, es geht also keine Nachricht nach WhatsApp hinaus:

```powershell
docker compose exec sales-claw openclaw infer model providers
# erwartet: {"provider":"openrouter", ... "configured":true,"selected":true}

docker compose exec sales-claw openclaw config get agents.defaults.model.primary
# erwartet: openrouter/free

docker compose exec sales-claw openclaw infer model run --prompt "Antworte ausschliesslich mit dem Wort: pong" --json
# erwartet: "ok": true und "text": "pong"
```

`infer model run` ist hier bewusst der Weg und nicht `openclaw agent`: es
braucht keinen Agent-Workspace und prüft damit genau eine Sache — ob der
Modellschlüssel trägt. Schlägt es mit einem Rate-Limit fehl, ist das kein
Konfigurationsfehler; einmal wiederholen.

Der Schlüssel kommt aus `.env` als `OPENROUTER_API_KEY`. Ob er im Container
ankommt (ohne den Wert auszugeben):

```powershell
docker compose exec sales-claw sh -lc 'test -n "$OPENROUTER_API_KEY" && echo gesetzt || echo fehlt'
```

### Stand der Abnahme

| Kriterium | Stand |
|---|---|
| 1 Start / healthy | erfüllt |
| 2 Kopplung | **offen** — kein WhatsApp-Plugin im Container, Kanal nicht registriert |
| 3 Neustart | erfüllt, soweit ohne Kanal prüfbar: Container und Kopplungsdateien überstehen `down`/`up` unverändert |
| 4 Versionssprung | Version im Container ist 2026.7.1; die Kopplung selbst ist damit **nicht** erprobt, weil sie mangels Plugin nie geladen wurde |
| 5 Restore | offen (Task 6) |
| 6 Keine Kollateralschäden | erfüllt |

Das WhatsApp-Plugin ist ein **externes** Plugin (`clawhub:@openclaw/whatsapp`)
und im Image `2026.7.1-slim` nicht enthalten; `plugins list` führt es nicht,
im Dateisystem des Containers existiert es nicht. Die Installation ist ein
Eingriff, der beim ersten Laden eine echte WhatsApp-Sitzung auf den
Credentials des Betreibers öffnet — sie gehört deshalb **nicht** in einen
unbeaufsichtigten Lauf, sondern an den Anfang eines Termins, an dem der
Betreiber danebensitzt und der Anmelde-Trigger der lokalen Aufgabe
nachweislich aus ist (siehe oben).

## Dateiablage

| Was | Wo |
|---|---|
| Konfiguration, Agenten, `credentials/` | Volume `sales-claw-state` → `/home/node/.openclaw` |
| Verschlüsselungsschlüssel | Volume `sales-claw-keys` → `/home/node/.config/openclaw` |
| Sicherungen | `backups/` (gitignored) |
| Rohkopien der Kopplung | `credentials-sicherung-*/` (gitignored) |
| Host-Archiv von OpenClaw | `*-openclaw-backup.tar.gz` (gitignored) |

Alle vier enthalten Schlüssel und Sitzungsdaten im Klartext. Sie sind
gitignored, und das muss so bleiben — Zugriff auf diese Pfade entsprechend
einschränken.
