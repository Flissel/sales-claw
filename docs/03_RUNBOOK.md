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

### Anmelde-Trigger und Neustart-Regel — Stand und Zusammenhang

Der lokale Gateway läuft nicht als freier Prozess, sondern als
**Windows-Aufgabe `\OpenClaw Gateway`**. Deren Anmelde-Trigger ist
inzwischen **deaktiviert**:

```powershell
Get-ScheduledTask -TaskName 'OpenClaw Gateway' |
    ForEach-Object { $_.Triggers } |
    Select-Object @{n='Typ';e={$_.CimClass.CimClassName}}, Enabled
# MSFT_TaskLogonTrigger   False
```

Die Aufgabe selbst existiert weiter und steht auf `Ready`. Sie startet aber
nicht mehr von allein, wenn sich jemand an Windows anmeldet.

**Der Container steht auf `restart: "no"`** (Begründung in
`docker-compose.yml`: Demo-Betrieb an der persönlichen Nummer des Betreibers).
Beide Einstellungen gehören zusammen:

| Kommt nach einer Windows-Anmeldung von selbst hoch? | lokale Aufgabe | Container |
|---|---|---|
| | nein — Trigger `Enabled=False` | nein — `restart: "no"` |

Nach einer Anmeldung läuft also **keine** der beiden Instanzen. Wer eine
braucht, startet sie bewusst, und genau dieser bewusste Schritt ist die
Stelle, an der die Reihenfolge-Regel oben greift.

**Warum die frühere Empfehlung nicht trug.** Hier stand bisher, man solle
„nach jeder Windows-Anmeldung zuerst prüfen, ob der lokale Gateway wieder
läuft, bevor der Container gestartet wird". Das setzte voraus, dass der
Container-Start ein von Hand gesetzter Zeitpunkt ist. Solange
`restart: unless-stopped` galt, war er das nicht: Aufgabe und Container kamen
**beide automatisch** hoch, in nicht festgelegter Reihenfolge und ohne
Zeitfenster dazwischen. Es gab keinen Moment, in dem jemand die Prüfung hätte
ausführen können. Ein Ratschlag, der ein Zeitfenster voraussetzt, das es nicht
gibt, ist kein Schutz — er sieht nur wie einer aus.

**Was daraus für die Umstellung folgt.** `restart: "no"` ist eine
Demo-Einstellung. Sobald `sales-claw` eine eigene Nummer hat und dauerhaft
bedienen soll, wird daraus `unless-stopped`. Dann startet der Container
automatisch — **und dann ist der deaktivierte Anmelde-Trigger keine
Bequemlichkeit mehr, sondern Voraussetzung.** Wird er wieder eingeschaltet,
während der Container auf `unless-stopped` steht, kommen nach der nächsten
Anmeldung zwei Baileys-Sitzungen auf denselben Credentials hoch, und die
Kopplung ist weg (`05_DISASTER_RECOVERY.md`, Fall 1). Die beiden Schalter
dürfen deshalb nie einzeln umgelegt werden.

Der Stand lässt sich jederzeit ohne Eingriff nachsehen:

```powershell
Get-ScheduledTask -TaskName 'OpenClaw Gateway' |
    ForEach-Object { $_.Triggers } | Select-Object Enabled    # erwartet: False
pwsh -Command ". ./scripts/lib/ports.ps1; Test-PortFrei -Port 18793"   # erwartet: True
```

Ist der lokale Gateway wider Erwarten doch hochgekommen (Port 18793 belegt),
gilt weiterhin: `pwsh -File scripts/stop-local-openclaw.ps1`, und erst danach
`docker compose up -d`.

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

Gemessene Zeiten bis `healthy` (Task 9, mit geladenem WhatsApp-Plugin): 21–23 s
nach `down`/`up`, aber **98 s** nach `docker compose restart` — dort baut der
Kanal seine Web-Verbindung parallel zum Hochlauf auf. Zwei Minuten Geduld sind
also wirklich die Grenze, nicht 35 s.

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

**Immer `--json`, und immer über `channelOrder`** — nie über den Fließtext:

```powershell
openclaw --container sales-claw channels status --json
```

Maßgeblich sind vier Felder:

| Feld | Soll | Bedeutung |
|---|---|---|
| `channelOrder` | enthält `whatsapp` | Ein geladenes Plugin **besitzt** den Kanal. Der positive Anker — ohne ihn ist alles Weitere wertlos |
| `channels.whatsapp.statusState` | `linked` | Gekoppelt. `qr`/Pairing-Zustände fallen hier durch |
| `channels.whatsapp.connected` | `true` | Verbindung steht gerade |
| `channels.whatsapp.lastDisconnect.loggedOut` | `false` oder `null` | Serverseitige Abmeldung — **der Wert zählt, nicht das Vorkommen des Wortes** |

Warum das so pedantisch steht: siehe „Warum Kriterium 2 nicht per Textsuche
geprüft wird". Beide naheliegenden Textprüfungen sind gemessen falsch — die eine
meldete Grün ohne Kanal, die andere Rot am gesunden Kanal.

**Direkt nach einem Neustart Geduld:** Der Kanal baut erst seine
Web-Verbindung auf; `channels status` brauchte dabei gemessen 14,9 s und lief in
den 10-s-Timeout der CLI (`Gateway not reachable: gateway timeout after
10000ms`). Das ist **kein** Kanalfehler. Erst `healthy` abwarten, dann noch
einmal abfragen. `scripts/smoke-test.ps1` versucht es aus demselben Grund
genau zweimal.

Klartextfassung (zum Mitlesen, nicht zum Prüfen) und tiefere Sonde:

```powershell
openclaw --container sales-claw channels status
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

**Der Lauf stoppt den Container** und startet ihn danach wieder — das ist
beabsichtigt, weil ein `tar` über laufende Schreibvorgänge im Session-Store
eine strukturell einwandfreie Sicherung mit einer toten WhatsApp-Sitzung
erzeugen kann. Vollständige Begründung, Manifest, Aufbewahrung und der
empfohlene tägliche Termin: `docs/04_BACKUP_RESTORE.md`.

**Die Ausfallzeit ist mit dem Volume gewachsen: gemessen 42 s** (Task 10, bei
12 045 Einträgen und 87,8 MB `state.tar`). Die früher hier genannten 3,5 s
stammen aus einem Volume mit 39 Einträgen, vor Kopplung und Kanal-Plugin —
diese Zahl ist überholt und war nie eine Eigenschaft des Skripts, sondern
eine des Datenbestands. Den täglichen Termin entsprechend außerhalb der
Geschäftszeiten legen.

Exit-Codes des Skripts:

| Code | Bedeutung |
|---|---|
| `0` | Sicherung vollständig **und** Container läuft wieder |
| `1` | Sicherung fehlgeschlagen (Ausnahme) — es gibt kein `MANIFEST.json` |
| `2` | Sicherung vollständig, **aber der Wiederanlauf ist gescheitert** — der Dienst ist unten und braucht einen Menschen |

Ein geplanter Lauf muss auf den Exit-Code hören, nicht auf die Bildschirmfarbe.

**Eine vorhandene Sicherung prüfen, ohne etwas zu verändern** — der Container
darf dabei laufen:

```powershell
pwsh -File scripts/restore-state.ps1 -Quelle backups\sales-claw-<zeitstempel> -NurPruefen
```

Läuft die Prüfschleife durch (Manifest-Abgleich und Entpackprobe beider
Archive), steigt das Skript mit Exit `0` aus, **bevor** ein Volume angefasst
wird. So stellt sich die Tauglichkeit einer Sicherung heraus, solange sie noch
niemand braucht.

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

**Und die Gegenprobe gehört auf Felder, nicht auf den Wortlaut des JSON.** Die
erste Fassung dieser Gegenprobe suchte im serialisierten JSON nach
`logged.?out|not.?connected|disconnected|needsPairing|pairing|"qr"`. Sobald der
Kanal existiert, meldet sie **Rot am gesunden Kanal**: das Muster trifft den
Feld*namen* `loggedOut` in `lastDisconnect` — dessen Wert `false` ist, also der
Beweis des Gegenteils. Gemessen in Task 9 an einem Kanal mit
`statusState: "linked"`, `connected: true`.

Damit ist die Lehre nicht „Textsuche zu lasch" und auch nicht „Textsuche zu
streng", sondern: **ein Textmuster kann Feldname und Feldwert nicht
unterscheiden.** Eine Zustandsprüfung muss den Wert lesen. `smoke-test.ps1`
wertet deshalb `statusState`, `linked`, `connected` und
`lastDisconnect.loggedOut` einzeln aus.

Ein kurzer Reconnect direkt nach dem Start (`status 408`, `reconnectAttempts: 1`,
`loggedOut: false`) ist normal und heilt sich selbst; er kann die Prüfung für
wenige Sekunden auf `connected: false` schicken. Dann wiederholen — **nicht**
neu koppeln.

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

**Seit der Kanal lebt, ist diese Prüfsumme kein Fixwert mehr.** Eine aktive
Baileys-Sitzung schreibt im Betrieb in `credentials/whatsapp` — beim ersten
Laden unter 2026.7.1 wanderte die Bytesumme von 1 977 634 auf 1 977 639, bei
unveränderten 8003 Dateien. Das ist der erwartete Beleg dafür, dass die Sitzung
benutzt wird, kein Schaden. Aussagekräftig ist die Prüfsumme deshalb nur noch
als Vergleich **unmittelbar vor und nach** einem Neustart, nicht gegen einen in
einem älteren Bericht notierten Wert.

**Auch die Dateizahl ist inzwischen kein Fixwert mehr.** In Task 10 stieg sie
im laufenden Betrieb innerhalb weniger Minuten von 8003 auf 8011, ohne dass
irgendetwas eingegriffen hätte — die Sitzung legt im Normalbetrieb neue
Session-Dateien an. Ein Zuwachs ist also kein Befund. Ein **Rückgang** wäre
einer.

### Kriterium 2 von Hand — der Selbst-Chat

Erst sinnvoll, **wenn Kriterium 2a grün ist**. Solange kein Plugin den Kanal
besitzt, kann keine Nachricht ankommen, und ein ausbleibender Umlauf beweist
nichts. Seit Task 9 ist er grün.

**Von welchem Gerät gesendet werden muss.** Das verknüpfte WhatsApp-Konto (Feld
`channels.whatsapp.self.e164` in `channels status --json`) ist **eine andere
Nummer** als der einzige Eintrag in `channels.whatsapp.allowFrom`. Der Plan ging
davon aus, beide seien dieselbe. Praktisch heißt das:

- Der Selbst-Chat („Nachricht an mich selbst") funktioniert nur vom
  **verknüpften** Gerät aus. Er wird zugelassen, weil das Plugin den Absender
  dynamisch zulässt, wenn er mit dem verknüpften Konto identisch ist
  (`maybeSamePhoneDmAllowFrom`) — die Allowlist muss dafür nicht angepasst
  werden.
- Eine Nachricht von der Nummer aus der Allowlist ist **kein** Selbst-Chat,
  sondern eine normale Direktnachricht. Sie wird ebenfalls zugelassen, weil die
  Nummer in `allowFrom` steht.
- Beide Nummern kommen also durch. Ob das gewollt ist, entscheidet der
  Betreiber; `docs/01_OVERVIEW.md` sagt „ausschließlich mit der Nummer des
  Betreibers".

Vom verknüpften Telefon eine Nachricht an die eigene Nummer senden
(`selfChatMode`), zum Beispiel `ping sales-claw`, und mitlesen:

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

Stand nach Task 9:

| Kriterium | Stand |
|---|---|
| 1 Start / healthy | erfüllt |
| 2 Kopplung | **Kanal erfüllt** — `channelOrder` führt `whatsapp`, `statusState: linked`, `connected: true`, kein QR. Der Selbst-Chat-Umlauf bleibt von Hand zu führen |
| 3 Neustart | erfüllt — Kanal, Plugin und Kopplungsdateien überstehen `down`/`up`; Plugin und Workspace liegen im Volume |
| 4 Versionssprung | **erfüllt** — die aus 2026.5.18 übernommenen Credentials tragen unter 2026.7.1: der Kanal meldet sich ohne Neukopplung als `linked` |
| 5 Restore | offen (Task 6) |
| 6 Keine Kollateralschäden | erfüllt |

### Das Kanal-Plugin nach einem Neuaufbau aus frischem Volume

Das WhatsApp-Plugin ist ein **externes** Plugin (`clawhub:@openclaw/whatsapp`)
und in keinem der beiden Images enthalten — `-slim` und Nicht-Slim sind identisch
groß. Installiert wird es **ins Volume**
(`/home/node/.openclaw/extensions/whatsapp`); es übersteht damit `down`/`up` und
wird von einem Restore mit zurückgespielt. Erneut nötig ist der Schritt nur,
wenn `sales-claw-state` neu aufgebaut wird:

```powershell
docker compose exec -e npm_config_cache=/tmp/.npm sales-claw `
    openclaw plugins install clawhub:@openclaw/whatsapp
docker compose restart sales-claw
openclaw --container sales-claw plugins doctor      # erwartet: keine Install-Tree-Probleme
openclaw --container sales-claw channels status --json
```

`npm_config_cache=/tmp/.npm` ist zwingend — ohne beschreibbaren Cache entsteht
eine Installationsspur auf einen Pfad außerhalb des Containers, und das Ergebnis
ist `openKeyedStore is only available for trusted plugins`
(`05_DISASTER_RECOVERY.md`, Fall 4).

**Die Installation ist kein Routineschritt.** Beim ersten Laden öffnet sie eine
echte WhatsApp-Sitzung auf den Credentials des Betreibers. Sie gehört deshalb
nicht in einen unbeaufsichtigten Lauf, sondern an den Anfang eines Termins, an
dem der Anmelde-Trigger der lokalen Aufgabe nachweislich aus und der lokale
Gateway gestoppt ist (Port 18793 frei, siehe oben).

## Stufe 2: sales-mcp und die Datenbank

Ergänzt den Alltagsbetrieb um den zweiten Container (`sales-mcp`) und die
VM-Datenbank. Architektur, Werkzeugliste und Rechtematrix stehen in
`docs/02_ARCHITECTURE.md`, Abschnitt „Architektur (Stufe 2)".

### Start und Stopp beider Container

`sales-claw` und `sales-mcp` stehen im selben `docker-compose.yml` und
starten/stoppen zusammen:

```powershell
docker compose up -d
docker compose ps
# erwartet: sales-claw ... (healthy), sales-mcp ... Up
docker compose down
```

`sales-mcp` steht wie `sales-claw` auf `restart: "no"` (Demo-Betrieb, dieselbe
Begründung — siehe Kommentar in `docker-compose.yml`) und hat **keinen**
`HEALTHCHECK`; sein Startzustand wird über die Logs geprüft (siehe unten), nicht
über die Health-Spalte von `docker compose ps`.

Nur `sales-mcp` betreffen, ohne `sales-claw` anzufassen:

```powershell
docker compose up -d sales-mcp
docker compose stop sales-mcp
```

### sales-mcp-Logs

```powershell
docker compose logs -f sales-mcp
```

Sauberer Start sieht so aus (gemessen, Task 4):

```
sales-mcp  | INFO:     Started server process [1]
sales-mcp  | INFO:     Waiting for application startup.
sales-mcp  | StreamableHTTP session manager started
sales-mcp  | INFO:     Application startup complete.
sales-mcp  | INFO:     Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit)
```

Kein `ports:`-Eintrag für `sales-mcp` — der Dienst ist absichtlich nicht vom Host
aus erreichbar; nur `docker compose exec`/`logs` sowie der Aufruf aus `sales-claw`
im Compose-Netz funktionieren.

### psql-Gegenproben

**Die DSN gehört niemals in eine Kommandozeile (argv).** Wer eine DSN direkt in
`docker run ... psql "$dsn"` einsetzt, schreibt sie in die Prozessliste des Hosts —
sichtbar für jeden, der Kommandozeilen auslesen kann. Das in den Task-Berichten
durchgehend verwendete Muster, hier wörtlich übernommen: DSN als
Host-Umgebungsvariable setzen, **ohne Wert** an den Container durchreichen,
Auflösung erst in der Container-Shell:

```bash
export SALES_DSN=$(grep '^SALES_DB_URL=' .env | sed 's/^SALES_DB_URL=//')
docker run --rm -e SALES_DSN -i postgres:17-alpine sh -c \
  'psql "$SALES_DSN" -c "select name, source, created_at from sales.leads order by created_at desc limit 5;"'
unset SALES_DSN
```

Wichtig für die Sicherheit dieses Musters: `-e SALES_DSN` **ohne** `=wert` reicht
die bereits gesetzte Host-Variable unverändert durch — der eigentliche
DSN-Wert taucht dadurch in keiner sichtbaren Kommandozeile auf, weder auf dem Host
noch im Container (`sh -c '...'` ist einfach gequotet, `$SALES_DSN` wird erst *im*
Container aufgelöst). `.env` selbst wird an keiner Stelle mit `cat` oder
`Get-Content` ausgegeben, nur die eine `SALES_DB_URL`-Zeile maschinell extrahiert;
die Variable danach wieder aus der Umgebung entfernen (`unset` bzw. unter
PowerShell `Remove-Item Env:SALES_DSN`).

Für den SQLSTATE-Nachweis der Append-only-Garantie (nicht nur der Fehlertext,
sondern der Code `42501`) braucht `psql` zusätzlich `\set VERBOSITY verbose` **vor**
der SQL-Anweisung, über stdin zugeführt — mit reinem `-c` zeigt psql den Code nicht
an (Task 1, Schritt 6). Der so tatsächlich beobachtete Fehlertext steht in
`docs/02_ARCHITECTURE.md`, Abschnitt „Datenbank: Schema `sales`/`sales_test` und die
Rechtematrix".

### Leitfaden ändern

`sales-mcp/leitfaden.yaml` bearbeiten, dann:

```powershell
docker compose build sales-mcp
docker compose up -d sales-mcp
```

**`sales-claw` muss dafür nicht neu gestartet werden.** Der Leitfaden lebt
ausschließlich im `sales-mcp`-Image (zur Modulladezeit aus der Datei gelesen); ein
Rebuild und Austausch von `sales-mcp` lässt `sales-claw` unberührt — belegt in
Fix-Runde 1 (Task 3): `sales-claw`s `StartedAt` war vor und nach einem
`sales-mcp`-Rebuild identisch.

### Agent-Regeln ändern (`AGENTS.md`)

`config/workspace/AGENTS.md` bearbeiten, dann direkt ins laufende Volume kopieren —
es gibt keinen Build-Schritt dafür:

```powershell
docker compose cp config/workspace/AGENTS.md sales-claw:/home/node/.openclaw/workspace/AGENTS.md
```

**Kein Neustart von `sales-claw` nötig** — verifiziert (Task 5) über zwei
Agentenläufe mit frischem `--session-key` direkt nach dem Kopieren:
`injectedWorkspaceFiles` zeigte die neue Datei vollständig geladen
(`rawChars == injectedChars`, `truncated: false`). Zum Prüfen, ob die Datei
tatsächlich angekommen ist:

```powershell
docker compose exec sales-claw sh -lc 'md5sum /home/node/.openclaw/workspace/AGENTS.md'
```

und lokal vergleichen. **Bekannte Nebenwirkung:** `docker compose cp` setzt
Owner/Rechte der kopierten Datei auf `root:root`/`rwxr-xr-x` statt
`node:node`/`rw-r--r--` wie die übrigen Workspace-Dateien. Funktional unkritisch —
der `node`-Prozess kann über das „other"-Read-Bit weiterhin lesen (geprüft) —, aber
für spätere Audits vermerkt.

### Testsuite

```powershell
docker build -t sales-mcp:dev sales-mcp
docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest -q
```

**`python -m pytest`, nicht `pytest -q` direkt.** Ohne `conftest.py`/`__init__.py`
setzt pytests Standard-Importmodus nur das Verzeichnis der Testdatei
(`/app/tests`) auf `sys.path`, nicht das Arbeitsverzeichnis `/app`, in dem
`server.py` liegt — `pytest -q` allein scheitert deshalb mit
`ModuleNotFoundError: No module named 'server'`, obwohl die Datei existiert
(Task 2, Befund 3). `python -m pytest` stellt das Arbeitsverzeichnis voran auf
`sys.path`.

**Ausschließlich gegen `sales_test`** (`SALES_DB_SCHEMA=sales_test`) —
`db/provision.sql` sagt es wörtlich: „Die Testsuite darf NIE gegen `sales` laufen."
Der Schema-Wächter in `server.py` bricht bei jedem anderen Wert als
`sales`/`sales_test` sofort mit `SystemExit` ab, noch vor jedem DB-Zugriff.

### Modellwahl im Demo-Betrieb: openrouter/free bleibt

Betreiberentscheidung (Kostenpräferenz, Prototyp ohne echte Kunden):
`agents.defaults.model.primary` bleibt auf `openrouter/free`, trotz drei
gemessener Schwächen aus den Tasks 3–5:

- **Schwankende Antwortzeiten.** Gemessene Laufzeiten reichten von 34 s
  (Fix-Runde 1, Task 3) über 152,6 s und 453,5 s (Task 5, zwei Proben) bis zu
  einem vollständigen 600-s-Provider-Timeout (Task 4, erster Smoke-Versuch).
- **Sitzungs-Verheddern.** Die fortlaufende `main`-Sitzung akkumuliert Text aus
  früheren fehlgeschlagenen Werkzeugaufrufen; das Modell kann sich daran
  festbeißen, statt einen frischen Versuch zu starten — im genannten
  600-s-Timeout-Fall rief es laut `toolSummary` **kein einziges Mal** ein
  Werkzeug auf.
- **Inkonsistente Regeltreue.** Dieselbe Verbotsregel (keine Produktempfehlung,
  Verweis an die Beraterin), zwei Läufe kurz hintereinander: Ein Lauf riss die
  Verweisregel im Antworttext (kündigte stattdessen an, selbst eine
  „ETF-Strategie" zu entwickeln — bei korrekt geloggtem `offener_punkt` im
  Hintergrund), der nächste befolgte dieselbe Regel proaktiv und korrekt
  (Task 5, Proben 1 und 2).

**Gegenmittel im Demo-Betrieb:** eine frische, eindeutige `--session-key` statt der
fortlaufenden `main`-Sitzung verwenden, bei auffälligem Verhalten wiederholen:

```powershell
docker compose exec sales-claw openclaw agent --agent main `
    --session-key "agent:main:<eindeutige-bezeichnung>" `
    -m "..." --json
```

Kein `--deliver` in Diagnose-/Testläufen, damit keine Testnachricht tatsächlich
über WhatsApp hinausgeht. Vor einer Vorführung bei MH Consulting die Modellfrage
erneut stellen — die Ausnahme von der sonstigen Pin-Regel gilt ausdrücklich nur für
den Prototyp ohne echte Kundengespräche (`docs/02_ARCHITECTURE.md`, Abschnitt
„Modellanbieter").

## Stufe 3: Versand mit Approval

Ergänzt den Alltagsbetrieb um zwei weitere Container: `openwa`
(WhatsApp-Gateway) und `sales-dispatch` (der einzige Dienst, der
tatsächlich versendet). Architektur, die fünf Grundsatzentscheidungen,
Claim-Mechanik und Nummern-Regeln stehen in `docs/02_ARCHITECTURE.md`,
Abschnitt „Architektur (Stufe 3)". Pairing-Anleitung: siehe
`docs/08_PAIRING_ANLEITUNG.md`.

### Start und Stopp aller vier Container

Zwei Compose-Dateien, ein gemeinsames Projekt (`name: sales-claw`, explizit
in beiden Dateien gepinnt — dadurch teilen sich alle vier Container
dasselbe Netz, und `openwa` ist unter dem DNS-Namen `openwa` erreichbar):

```powershell
# Hauptstack: sales-claw, sales-mcp, sales-dispatch
docker compose up -d
docker compose ps
# erwartet: sales-claw (healthy), sales-mcp Up, sales-dispatch Up

# OpenWA — eigene Compose-Datei, gleiches Projekt
docker compose -f docker-compose.openwa.yml up -d --build
docker compose -f docker-compose.openwa.yml ps
# erwartet: openwa (healthy)
```

Stoppen:

```powershell
docker compose down
docker compose -f docker-compose.openwa.yml down
```

**`--remove-orphans` ist in diesem Repo TABU — in JEDER Form, mit JEDER
Compose-Datei.** Weil beide Compose-Dateien dasselbe Projekt teilen, meldet
jeder Befehl mit der Hauptdatei „Found orphan containers ([openwa])" — das
ist harmlos und erwartet, solange nichts weiter passiert. Mit
`--remove-orphans` würde genau dieser als „verwaist" gemeldete
`openwa`-Container entfernt — inklusive seiner laufenden
Session-Verbindung. Ob eine im Volume `openwa-data` gespeicherte Pairing
das automatisch übersteht, ist **nicht geprüft** — genau deshalb gilt die
Regel kategorisch und ungetestet: `--remove-orphans` wird auf diesem Stack
nie verwendet, auch nicht „nur um die Warnung loszuwerden". Umgekehrt gilt
dasselbe für `docker-compose.openwa.yml`: ein Befehl damit meldet
`sales-claw`, `sales-mcp` und `sales-dispatch` als verwaist.

Nur einen der vier Dienste betreffen:

```powershell
docker compose up -d sales-dispatch
docker compose stop sales-dispatch
docker compose logs -f sales-dispatch
docker compose -f docker-compose.openwa.yml logs -f openwa
```

`sales-dispatch` hat wie `sales-mcp` keinen `HEALTHCHECK` — Startzustand
über die Logs prüfen (Startzeile nennt Schema, OpenWA-URL, Session,
Intervall, Pause). `openwa` hat einen Healthcheck gegen
`/api/health/ready`.

### Status eines Entwurfs lesen

Über den Agenten: „zeig die Entwürfe" → `entwuerfe_offen()` liefert zwei
Blöcke — `entwuerfe` (offene Freigaben: `pending` sowie freigegebene
LinkedIn-Entwürfe, die auf Handversand warten) und `fehlgeschlagen` (bis zu
20 Einträge, `anzahl_fehlgeschlagen` nennt die tatsächliche Zahl daneben).
Fünf mögliche `status`-Werte in `drafts` (CHECK constraint,
`db/provision.sql`):

| Status | Bedeutung |
|---|---|
| `pending` | Entwurf erstellt, wartet auf Freigabe/Ablehnung |
| `approved` | Freigegeben — WhatsApp: wird vom Dispatcher binnen ~10 s abgeholt; LinkedIn: wartet auf Handversand |
| `failed` | Zustellung gescheitert **oder** gerade unterwegs — `error` unterscheidet, siehe unten |
| `sent` | Zugestellt (WhatsApp: Dispatcher-Erfolg) oder quittiert (LinkedIn: `entwurf_manuell_gesendet`) |
| `rejected` | Vom Betreiber abgelehnt |

**`failed` mit der Marke „in Zustellung seit …" ist ein Zwischenzustand,
kein Endzustand.** Der Dispatcher setzt diese Marke **vor** dem
Sendeversuch (der Claim, `docs/02_ARCHITECTURE.md`, Abschnitt
„Claim-Mechanik"). Steht sie noch da, wenn `entwuerfe_offen` erneut
abgefragt wird, ist entweder der Versand gerade unterwegs (Sekunden) —
oder der Dispatcher ist **genau während dieses Versands gestorben**. Im
zweiten Fall ist unklar, ob die Nachricht den Empfänger schon erreicht
hat. Deshalb verweigert `entwurf_erneut_freigeben` eine erneute Freigabe,
solange `error` mit „in Zustellung" beginnt, **ohne** den zusätzlichen
Parameter `bestaetigt=True` — und der Agent ist angewiesen
(`config/workspace/AGENTS.md`), in diesem Fall ausdrücklich vor einem
möglichen Doppelversand zu warnen und eine zweite, ausdrückliche
Bestätigung einzuholen, bevor er
`entwurf_erneut_freigeben(draft_id, bestaetigt=True)` aufruft.
**Re-Approve eines hängenden Claims also nur mit dieser Bestätigung** —
nie automatisch, nie „einfach nochmal freigeben".

Jeder andere `failed`-Fehlertext (z. B. `kein zustellbarer Empfaenger`,
die Nummern-Härtung aus `docs/02_ARCHITECTURE.md`, oder ein echtes
`OpenWA HTTP 409: …`) ist ein abgeschlossener Fehlschlag ohne
Doppelversand-Risiko — Re-Approve funktioniert dort ohne `bestaetigt`,
verlangt aber trotzdem eine ausdrückliche Betreiber-Anweisung.

### Freigabe-Ablauf (Betreibersicht)

1. „Zeig die Entwürfe" → der Agent listet über `entwuerfe_offen`: die
   **vollständige** draft_id, Kanal, Empfänger, Zielnummer (die
   tatsächliche Chat-ID, oder `null` mit dem Hinweis „nicht zustellbar"),
   Einwilligungsstand, Textanfang.
2. Für einen konkreten Entwurf: „Gib den Entwurf für … frei." Der Agent
   zeigt den **vollständigen** Text wörtlich und fragt zurück: „Diesen
   Text an … freigeben?" — er gibt nichts frei, bevor diese Rückfrage
   bestätigt wurde (`AGENTS.md`, Abschnitt „Freigabe").
3. Nach der Bestätigung: `entwurf_freigeben(draft_id)` →
   `status='approved'`.
   - **WhatsApp:** der Agent sagt ausdrücklich, dass der Dispatcher
     automatisch übernimmt. Die Schleife läuft alle 10 s
     (`DISPATCH_INTERVAL_S`) — Zustellung oder Fehlschlag stehen binnen
     weniger Sekunden bis knapp über 10 s in `drafts`.
   - **LinkedIn:** siehe unten.

### LinkedIn-Ablauf (Handversand)

1. Freigabe wie oben — der Agent weist ausdrücklich darauf hin, dass der
   Betreiber **selbst** senden muss (kein automatischer Versand, keine
   API-Anbindung, Grundsatzentscheidung 3).
2. Betreiber sendet die Nachricht von Hand über LinkedIn.
3. Betreiber meldet das dem Agenten zurück (z. B. „Entwurf … ist raus").
4. **Erst danach** ruft der Agent `entwurf_manuell_gesendet(draft_id)`
   auf — quittiert `status='sent'`, versendet selbst nichts. Funktioniert
   ausschließlich für `channel='linkedin'` **und** nur aus `approved`;
   jeder andere Kanal liefert den Fehlertext „nur für LinkedIn — WhatsApp
   versendet der Dispatcher".

### `DISPATCH_ONCE` — Testmodus

`sales-dispatch` läuft normalerweise als Dauerschleife (alle
`DISPATCH_INTERVAL_S`, Vorgabe 10 s). Für einen einzelnen, kontrollierten
Testlauf statt der Dauerschleife:

```powershell
docker compose run --rm -e SALES_DB_SCHEMA=sales_test -e DISPATCH_ONCE=1 sales-dispatch
```

Eine Runde (bis zu 5 Entwürfe, `STAPEL` in `dispatch.py`), dann Exit 0.
**`SALES_DB_SCHEMA=sales_test` nicht vergessen** — sonst läuft der Testlauf
gegen die echten Kundendaten in `sales`. Genau dieser Weg wurde in T3/T5a
für den Live-Beleg gegen das echte, ungepairte OpenWA verwendet (Ergebnis:
HTTP 409 → `failed`, dokumentiert in `docs/02_ARCHITECTURE.md`).

### psql-Gegenproben für `drafts`

Gleiches Muster wie in Stufe 2 (Abschnitt oben) — DSN nur als
Host-Umgebungsvariable, **ohne Wert** an den Container durchgereicht:

```bash
export SALES_DSN=$(grep '^SALES_DB_URL=' .env | sed 's/^SALES_DB_URL=//')
docker run --rm -e SALES_DSN -i postgres:17-alpine sh -c \
  'psql "$SALES_DSN" -c "select id, channel, status, recipient, left(error,60) as error from sales.drafts order by created_at desc limit 10;"'
unset SALES_DSN
```

`.env` wird dabei nicht gelesen oder ausgegeben — nur die eine
`SALES_DB_URL`-Zeile maschinell extrahiert (vollständige Begründung des
Musters: Abschnitt „psql-Gegenproben" oben, Stufe 2).

### Warmup-Regeln für frische Nummern

Aus OpenWAs eigener Risiko-Dokumentation (Upstream-Repo,
`docs/16-risk-management.md` und `docs/12-troubleshooting-faq.md`) — gilt
für die dedizierte `openwa`-Nummer ab dem QR-Pairing
(`docs/08_PAIRING_ANLEITUNG.md`):

- **Erst menschlich verhalten.** Ein bis zwei Wochen normale Nutzung
  (Nachrichten auch empfangen und beantworten, nicht nur senden), bevor
  Vertriebsvolumen über die Nummer läuft.
- **Nicht am ersten Tag senden.** Eine frisch verknüpfte Nummer, die
  sofort bulk-artige Nachrichten verschickt, ist genau das Muster, das
  WhatsApps Spam-Erkennung sucht.
- **Wenige Nachrichten pro Minute, nicht mehr.** OpenWAs eigene
  Empfehlung nennt grob 100–200 Nachrichten/Tag als Obergrenze für neue
  Nummern und rät zu zufälligen Pausen zwischen Sendungen sowie dazu,
  keine identischen Textbausteine an viele Empfänger zu schicken.
  `sales-dispatch` hat dafür `SENDE_PAUSE_S` (Vorgabe 1 s zwischen zwei
  tatsächlichen Sendungen einer Runde, einstellbar über
  `DISPATCH_SENDE_PAUSE_S`) — das ist eine Mindestbremse, **kein**
  Rate-Limit im eigentlichen Sinn: kein Tages- oder Stunden-Deckel auf
  unserer Seite. OpenWAs eigener Rate-Limiter (100 Anfragen/60 s) greift
  als zweite Schicht davor. Für Demo-Volumen ausreichend, vor echtem
  Volumenbetrieb ausbaufähig.
- **Nicht an Nummern senden, die nie zuerst geschrieben haben** — deckt
  sich mit der ohnehin bestehenden Consent-Erwartung des Prototyps.

## Stufe 4: Eingehende Kundenantworten (`sales-inbox`)

Die Gegenrichtung des Dispatchers. OpenWA stellt das Ereignis
`message.received` der Session `sales` an `http://sales-inbox:8790/webhook`
zu; jede angenommene Nachricht wird zu einer `activities`-Zeile vom Typ
`kundenantwort` beim passenden Kontakt. **Es wird nichts versendet und kein
`drafts`-Satz angefasst** — das Freigabe-Gate bleibt unberührt.

```powershell
docker compose up -d sales-inbox
docker compose logs -f sales-inbox
# Startzeile nennt Schema, Bind-Adresse, Pfad und Sammel-Lead.
```

Der Dienst hat **keinen Host-Port** — er ist ausschließlich im Compose-Netz
erreichbar. Ohne `INBOX_WEBHOOK_SECRET` (≥ 16 Zeichen) und ohne
`INBOX_UNBEKANNT_LEAD_ID` startet er nicht, sondern beendet sich mit Exit 2
und einer Zeile, die sagt warum.

### Was der Eingang annimmt und was nicht

| Fall | Antwort | Wirkung |
|---|---|---|
| Signatur ungültig oder fehlt | `401` | nichts geschrieben, Fehlversuchszähler im Log |
| Rumpf > 1,06 MB | `413` | Rumpf wird nicht gelesen |
| `fromMe: true` | `200 verworfen` | eigene Nachricht |
| Gruppe/Broadcast (`@g.us`, `isGroup`) | `200 verworfen` | kein Kundendialog |
| anderes Ereignis als `message.received` | `200 verworfen` | — |
| bekannte `message_id` schon gespeichert | `200 doppelt` | Dedup gegen OpenWA-Wiederholungen |
| Absender im CRM | `200 gespeichert` | Aktivität beim Kontakt |
| Absender unbekannt | `200 gespeichert` | Aktivität am Sammel-Lead „Unbekannte Eingänge" |
| Datenbank weg | `503` | OpenWA wiederholt (`retryCount`, Default 3) |

Absender werden über `nummern.py` normalisiert — dieselbe Regel wie im
Versand. Unbekannte Absender werden **nicht** automatisch als Kontakt
angelegt (Spam-Schutz); wer aufgenommen werden soll, wird vom Betreiber
ausdrücklich benannt.

### Webhook registrieren — und warum er es (noch) nicht ist

**Stand F1: der Webhook ist NICHT registriert.** OpenWA prüft die
Webhook-URL schon bei der Registrierung gegen einen SSRF-Filter und weist
jede private Adresse ab. Das Compose-Netz liegt auf `192.168.144.0/20`,
`sales-inbox` also mittendrin — gemessen:

```
POST /api/sessions/{id}/webhooks  {"url":"http://sales-inbox:8790/webhook",…}
-> 400 {"message":"Destination address is not allowed"}
```

Die vorgesehene Ausnahme ist `SSRF_ALLOWED_HOSTS=sales-inbox`. Die Zeile
steht bereits in `docker-compose.openwa.yml`, **wirkt aber erst nach einem
Recreate von `openwa`** — der in F1 bewusst unterblieben ist. Der Weg, wenn
der Betreiber ihn gehen will (Reihenfolge einhalten):

```powershell
# 1. openwa neu erzeugen — NIEMALS mit --remove-orphans
docker compose -f docker-compose.openwa.yml up -d openwa
docker compose -f docker-compose.openwa.yml logs --tail 50 openwa
# 2. Kanalstatus prüfen, BEVOR weitergemacht wird: Session muss wieder
#    verbunden sein (die Kopplung liegt im Volume openwa-data).
# 3. Webhook registrieren (Schlüssel und Geheimnis nur maschinell in
#    Variablen, nie anzeigen):
$w = @{}; foreach ($z in [IO.File]::ReadAllLines('.env')) {
  if ($z -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $w[$Matches[1]] = $Matches[2].Trim() } }
$rumpf = @{ url = 'http://sales-inbox:8790/webhook'
            events = @('message.received')
            secret = $w['INBOX_WEBHOOK_SECRET']
            filters = @{ conditions = @(@{ field='fromMe'; operator='is'; value=$false }) }
            retryCount = 3 } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:2785/api/sessions/$($w['OPENWA_SESSION_ID'])/webhooks" `
  -Headers @{ 'X-API-Key' = $w['OPENWA_API_KEY']; 'Content-Type' = 'application/json' } -Body $rumpf
# 4. Gegenprobe (die Antwort enthält das Geheimnis NICHT — by design):
Invoke-RestMethod -Uri "http://127.0.0.1:2785/api/sessions/$($w['OPENWA_SESSION_ID'])/webhooks" `
  -Headers @{ 'X-API-Key' = $w['OPENWA_API_KEY'] }
```

Der Filter `fromMe is false` ist eine zweite, serverseitige Schicht vor der
Prüfung im Eingang selbst — beide bleiben.

### Geheimnis wechseln

`INBOX_WEBHOOK_SECRET` in `.env` ersetzen, `sales-inbox` neu erzeugen
(`docker compose up -d sales-inbox`) **und** den registrierten Webhook
nachziehen (`PUT /api/sessions/{id}/webhooks/{webhookId}` mit dem neuen
`secret`). Wird nur eine Seite gewechselt, kommt nichts mehr an — sichtbar
als wachsender Fehlversuchszähler im `sales-inbox`-Log und als
`webhook_delivery_failed` bei OpenWA.

## Morgen-Digest

Werktags (Mo–Fr) 08:00 Europe/Berlin stellt der Agent unaufgefordert einen
kompakten Digest (offene Entwürfe, fällige Wiedervorlagen, unvollständige
Bedarfsanalysen — `digest()` aus Stufe 2/F3) in den WhatsApp-Chat des
Betreibers zu. **Kein neuer Versandweg:** OpenWA ist nicht beteiligt, die
Nachricht geht über denselben Antwortkanal, über den der Bot ohnehin
antwortet; das Freigabe-Gate der `drafts`-Tabelle bleibt unberührt.

**Mechanik: nativer `openclaw cron` (Gateway-Scheduler), keine eigene
Infrastruktur.** Gemessen über `openclaw cron --help` — der Container bringt
Cron bereits mit, kein Fallback-Skript nötig.

Job-Details (Stand F2):

| Feld | Wert |
|---|---|
| Job-ID | `221a69d7-4b52-471c-92e4-f86a42005b8e` |
| Name | `morgen-digest` |
| Schedule | `0 8 * * 1-5` @ `Europe/Berlin` (Mo–Fr 08:00 = 06:00 UTC im Sommer) |
| Session | `isolated` (frischer Kontext je Lauf, kein Vermischen mit dem laufenden Chat — das eigene `cron.md`-Beispiel für „Morning brief" nutzt dasselbe Muster) |
| Agent | `main` |
| Zustellung | `announce -> whatsapp:+491603449761` |

### Wichtiger Messbefund: Zustellung braucht die `allowFrom`-Nummer, nicht `self.e164`

Ein erster Versuch, an `+491749708452` zuzustellen (das ist `self.e164` aus
`openclaw channels status --json` — die verknüpfte Nummer, über die der
Selbst-Chat läuft), schlug **hart fehl**, nicht nur als Warnung:

```
Target "+491749708452" is not listed in the configured WhatsApp allowFrom policy.
```

Befund: Der Selbst-Chat-Sonderfall (`maybeSamePhoneDmAllowFrom`, siehe
„Kriterium 2 von Hand" oben) gilt nur für **eingehende** Nachrichten von der
verknüpften Nummer. Für **ausgehende** Cron-/Announce-Zustellung prüft
OpenClaw das Ziel strikt gegen die konfigurierte
`channels.whatsapp.default.allowFrom`-Liste. Zustellbares Ziel ist also die
dort gelistete Nummer (`+491603449761`) — dieselbe Nummer, die laut
Stufe-1-Runbook auch normale Direktnachrichten an den Bot schicken darf. Der
Job wurde entsprechend auf dieses Ziel korrigiert (`openclaw cron edit ...
--to "+491603449761"`).

### Probelauf — belegt

```powershell
docker compose exec sales-claw openclaw cron run 221a69d7-4b52-471c-92e4-f86a42005b8e --wait --wait-timeout 5m
```

Dritter Versuch erfolgreich (`"status": "ok"`, `"delivered": true`,
`"deliveryStatus": "delivered"`) — der erste scheiterte an der oben
beschriebenen `allowFrom`-Prüfung (vor der Korrektur), der zweite an einem
transienten `openrouter/free`-Fehler (`FailoverError: ... inference
generation failed` — bekannte Schwäche, siehe „Modellwahl im Demo-Betrieb"
oben; kein Konfigurationsfehler, einfach wiederholen). Log-Beleg der
tatsächlichen WhatsApp-Zustellung:

```
sales-claw | [whatsapp] Sending message -> sha256:775db645c879
sales-claw | [whatsapp] Sent message 3EB0332F532A532946C9F0 -> sha256:775db645c879 (220ms)
```

Zugestellter Text (vom Agenten aus `digest()` erzeugt, kompakt gemäß der
bestehenden AGENTS.md-Digest-Regel):

```
Morgen-Digest:
- 3 Entwürfe zur Freigabe (2 WhatsApp: Lisa Probekunde, 1 LinkedIn: Lisa Probekunde)
- 8 offene Bedarfsanalysen (Lisa Probekunde: 20+ Fragen)
- Keine fälligen Wiedervorlagen
```

### Zeitpunkt ändern

```powershell
docker compose exec sales-claw openclaw cron edit 221a69d7-4b52-471c-92e4-f86a42005b8e --cron "0 7 * * 1-5" --tz "Europe/Berlin"
```

### Abschalten / wieder aktivieren

```powershell
docker compose exec sales-claw openclaw cron disable 221a69d7-4b52-471c-92e4-f86a42005b8e
docker compose exec sales-claw openclaw cron enable 221a69d7-4b52-471c-92e4-f86a42005b8e
```

`disable` behält die Job-Definition (kein `rm`) — nur der Scheduler pausiert
sie.

### Nachsehen

```powershell
docker compose exec sales-claw openclaw cron list
docker compose exec sales-claw openclaw cron show 221a69d7-4b52-471c-92e4-f86a42005b8e
docker compose exec sales-claw openclaw cron runs --id 221a69d7-4b52-471c-92e4-f86a42005b8e --limit 10
```

### Persistenz — kein Repo-Artefakt, sondern eine Zeile im Volume

Die Job-Definition liegt **nicht** im Repo, sondern als Zeile in der
SQLite-Zustandsdatenbank des Gateways:

```
/home/node/.openclaw/state/openclaw.sqlite   (Tabelle cron_jobs, Zeile job_id=221a69d7-…)
```

Das ist derselbe Pfad wie `openclaw cron status` als `sqlitePath` meldet, und
derselbe Mountpunkt, dessen Neustart-Festigkeit in Stufe 1 nachgewiesen
wurde („Kriterium 3" oben). `sales-claw` wurde für diesen F2-Nachweis
bewusst **nicht** neu gestartet (laufender Betreiber-Chat, siehe „Die Regel,
die über allen anderen steht") — der Beleg stützt sich auf den Speicherort:

```powershell
docker inspect sales-claw --format '{{range .Mounts}}{{.Type}} {{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'
# volume sales-claw-state -> /home/node/.openclaw
```

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

## Medien anhängen (Stufe 4, F4)

Dateien per Explorer nach `sales-claw\media\` legen — **kein Neustart
nötig**, der Bind ist live. Zugelassen: `pdf, jpg, jpeg, png, mp3, ogg`,
höchstens 15 MB, nicht leer. Im Chat zeigt `medien_liste`, was anhängbar
ist; ein Entwurf mit Anhang entsteht wie jeder andere (`pending`) und geht
erst nach Freigabe raus — Text und Anhang in **einer** Nachricht (der Text
ist die Bildunterschrift, deshalb bei Anhängen höchstens 1024 Zeichen; das
Werkzeug lehnt Längeres schon beim Erstellen ab).

Zwei Regeln aus der Konstruktion:

* **Die Datei muss bis zur Zustellung liegen bleiben.** Gelöscht zwischen
  Freigabe und Versand ⇒ Entwurf wird `failed` (ohne Anhang geht nichts
  raus). Datei wieder hinlegen, dann `entwurf_erneut_freigeben`.
* **Nicht austauschen zwischen Freigabe und Versand.** Freigegeben ist der
  Name, nicht der Inhalt (Restrisiko-Begründung in `docs/02`, Stufe 4) —
  wer eine Datei ändern will, legt sie neu ab und erstellt einen neuen
  Entwurf.

`media/` ist **unversioniert** (bis auf `.gitkeep`): dort liegen
perspektivisch Kundenunterlagen, die in kein Repo gehören. Die drei
Muster-PDFs der Demo sind lokale Artefakte; bei einem Umzug den Ordner von
Hand mitnehmen oder neu befüllen.

## LinkedIn-Posts (Stufe 6)

Im Chat: „Entwirf mir einen Post zum Thema Quereinstieg" →
`post_entwurf_erstellen` legt ihn als LinkedIn-Entwurf in die Queue
(Betreff `Post: <thema>`, Empfänger `eigenes-profil`, Sammelkontakt
„LINKEDIN (Eigenes Profil)"). Nach der Freigabe: Text von linkedin.com
selbst posten (kopieren, ggf. Bild aus `media\` mit hochladen), dann im
Chat mit `entwurf_manuell_gesendet` quittieren.

**Warum kein Auto-Posting:** LinkedIn verbietet automatisierte Nutzung
über Bots — Kontosperr-Risiko. Der saubere Ausbauweg wäre die offizielle
Posts-API (OAuth-Scope `w_member_social`, eigene LinkedIn-Developer-App
nötig) — bewusst nicht gebaut, solange der Handversand reicht. Nachrichten
an Personen bleiben in jedem Fall Handversand.
