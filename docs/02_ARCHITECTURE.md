# 02 — Architektur

Quelle: `docs/superpowers/specs/2026-08-17-sales-claw-fundament-design.md` §5, §7.
Diese Fassung ergänzt die dort beschriebene Soll-Architektur um die bei der
Umsetzung von Task 2 **tatsächlich gemessenen** Werte und zwei reale
Abweichungen vom Ablauf, den der Task-2-Brief unterstellt hat.

## Architektur (Stufe 1)

Stufe 1 hat genau eine bewegliche Komponente. Der Datenfluss ist entsprechend kurz:

```text
WhatsApp (Baileys, verknüpftes Gerät)
        │
        ▼
┌───────────────────────────────────────────────┐
│ Container  sales-claw                          │
│ ghcr.io/openclaw/openclaw:2026.7.1-slim        │
│                                                 │
│   Gateway  ──►  Agent (openai/gpt-5.5)         │
│      │                                         │
│      ├── Volume  sales-claw-state              │
│      │     → /home/node/.openclaw              │
│      │       (Config, credentials/, memory/)   │
│      └── Volume  sales-claw-keys                │
│            → /home/node/.config/openclaw       │
│              (Verschlüsselungsschlüssel)       │
└───────────────────────────────────────────────┘
        │
        ▼  nur 127.0.0.1:18894
   Host (Docker Desktop)
```

Kein eigener Dienst, keine Datenbank, kein Reverse-Proxy im lokalen Betrieb. Der
Reverse-Proxy und die Härtung werden mitgeliefert, aber erst beim Umzug auf die VM
aktiv (Spec §10).

**Stand Task 2:** Das WhatsApp-Plugin ist im `-slim`-Image nicht vorinstalliert
(`plugins.entries.whatsapp: plugin not installed`, siehe unten). Der Kanal ist in
`config/openclaw.json` konfiguriert, aber noch nicht angebunden — das ist
beabsichtigt, WhatsApp-Kopplung ist Gegenstand eines späteren Tasks.

**Stand Task 9:** Das Plugin ist nachinstalliert, der Kanal ist angebunden. Wie
das zusammenhängt, steht im Abschnitt „Das Kanal-Plugin steckt nicht im Image".

### Warum zwei Volumes

`/home/node/.openclaw` enthält Konfiguration, Agenten, `credentials/` und `memory/`.
`/home/node/.config/openclaw` enthält die Verschlüsselungsschlüssel. Wer nur das
erste sichert, hat beim Restore verschlüsselte Daten ohne Schlüssel. Beide gehören
zusammen gesichert und zusammen zurückgespielt.

## Konfigurationsentscheidungen (mit gemessenen Werten)

| Entscheidung | Wert | Begründung |
|---|---|---|
| Image | `ghcr.io/openclaw/openclaw:2026.7.1-slim` | Gepinnt statt `latest`. Ein stiller Versionssprung beim Neustart ist genau das, was eine WhatsApp-Kopplung zerlegt. Das Hotel-Repo pinnt aus demselben Grund `tsx@4.19.0` |
| Variante | `-slim` | `browser`-Plugin bleibt aus; kein Chromium im Image |
| Container-Name | `sales-claw` | Vom Betreiber vorgegeben; verifiziert via `docker compose ps` |
| Gateway-Port (konfiguriert) | `18894` | `docker compose exec sales-claw openclaw config get gateway.port` → `18894` |
| Gateway-Port (tatsächlich lauschend) | `0.0.0.0:18894` | Gemessen über `/proc/net/tcp` im Container (lokale Adresse `00000000:49CE`, Status `0A` = LISTEN; `49CE`hex = `18894`dez). **Keine Abweichung** zum konfigurierten Wert — Doku (18789) und lokale Installation (18793) widersprechen sich weiterhin, betreffen aber nicht diesen Container |
| Host-seitige Erreichbarkeit | bestätigt | `openclaw --container sales-claw health` (vom Host) liefert Gateway-Event-Loop, Agent- und Heartbeat-Status ohne Verbindungsfehler |
| Port-Veröffentlichung | `127.0.0.1:18894:18894` | Muster aus dem Hotel-Repo. Der Gateway hält WhatsApp-Session und API-Schlüssel und darf nie direkt aus dem Netz erreichbar sein |
| Neustart | `restart: unless-stopped` | Wie bei `openclaw-festival` |
| Plugins | `plugins.allow: ["whatsapp"]` | Minimale Ladefläche; discord, telegram, voice-call, browser bleiben aus. Im `-slim`-Image sind discord, voice-call und whatsapp derzeit nicht vorinstalliert (Config-Warnung beim Start, siehe unten) — Installation ist nicht Teil von Task 2 |
| Speicher | `memory-core` aktiv (`memory/main.sqlite`), `openclaw-supermemory` **nicht** geladen | Supermemory ist ein externer Dienst; Kundendaten dorthin zu schicken ist eine Entscheidung für Stufe 2, keine Nebenwirkung von Stufe 1. Verifiziert im Startlog: `http server listening (1 plugin: memory-core; …)` |
| Logging | `json-file`, `max-size=10m`, `max-file=3` | Auf `C:` war der Platz bereits zweimal knapp |
| Healthcheck | `CMD openclaw health` gegen den Gateway-Port | Erreicht `healthy` unabhängig vom Modellschlüssel — `openclaw health` prüft nur den Gateway-Prozess (Event-Loop, Agenten, Sessions), nicht das Modell. Mit leerem `OPENAI_API_KEY` (siehe Secrets) trotzdem `healthy` |
| Zeitzone | `TZ=Europe/Berlin` | Termin- und Digest-Logik in späteren Stufen hängt daran |

## Das Kanal-Plugin steckt nicht im Image (Task 9)

`ghcr.io/openclaw/openclaw` bringt **kein** WhatsApp-Plugin mit. WhatsApp ist ein
externes Plugin und wird über ClawHub nachinstalliert:

```bash
docker compose exec -e npm_config_cache=/tmp/.npm sales-claw \
    openclaw plugins install clawhub:@openclaw/whatsapp
```

Drei Punkte, die man sonst teuer wieder herausfindet:

1. **`-slim` ändert daran nichts.** Die naheliegende Vermutung, die
   Nicht-Slim-Variante enthalte die Kanal-Plugins, ist falsch: `2026.7.1` und
   `2026.7.1-slim` sind identisch groß (26 Layer, 345,2 MB). Der Unterschied
   betrifft `browser`/Chromium, nicht die Kanäle. Ein Imagewechsel kostet einen
   Neustart und bringt nichts.
2. **Die Installation landet im Volume, nicht im Image.** Gemessener Zielpfad ist
   `/home/node/.openclaw/extensions/whatsapp` — also unterhalb von
   `/home/node/.openclaw` und damit auf `sales-claw-state`. Sie übersteht
   `docker compose down && up` und wird von einem Restore mit zurückgespielt. Sie
   muss nicht im Image, im Dockerfile oder in `docker-compose.yml` verankert
   werden. Umgekehrt gilt: Wer das Volume neu aufbaut, muss das Plugin erneut
   installieren — der Schritt gehört deshalb in den Runbook-Ablauf für einen
   Neuaufbau aus frischem Volume.
3. **`npm_config_cache=/tmp/.npm` ist kein Zierrat.** Ohne beschreibbaren
   npm-Cache bricht die Installation ab oder hinterlässt eine Installationsspur
   auf einen Pfad, den es im Container nicht gibt — Folgefehler ist dann
   `openKeyedStore is only available for trusted plugins`
   (`docs/05_DISASTER_RECOVERY.md`, Fall 4).

Nach der Installation lädt der Gateway drei statt zwei Plugins
(`http server listening (3 plugins: memory-core, openrouter, whatsapp)`) und der
Kanal erscheint in `channels status --json` unter `channelOrder`.

## Der Agenten-Workspace muss im Volume liegen (Task 9)

`agents.defaults.workspace` stand auf `/home/node/workspace`. Gemountet sind aber
nur `/home/node/.openclaw` und `/home/node/.config/openclaw` — der Pfad lag damit
in der Schreibschicht des Containers und starb mit ihm, während die zugehörige
Attestierung unter `/home/node/.openclaw/workspace-attestations/` im Volume
überlebte. Nach jedem `docker compose down && up` fand OpenClaw eine Attestierung
ohne Workspace und verweigerte **jeden** Agentenlauf:

```
WorkspaceVanishedError: OpenClaw workspace appears to have disappeared after a
recent initialization: /home/node/workspace. Refusing to reseed BOOTSTRAP.md over
a recently attested workspace.
```

Das Fehlerbild ist tückisch, weil der Container dabei `healthy` bleibt und der
Kanal Nachrichten annimmt: Eine Nachricht käme an, aber keine Antwort zurück.

`config/openclaw.json` setzt deshalb `agents.defaults.workspace` auf
`/home/node/.openclaw/workspace` — ein Pfad im Volume. Dort seedet OpenClaw
`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md` und
`BOOTSTRAP.md`, und diese Dateien überleben den Neustart gemeinsam mit ihrer
Attestierung. Ein leeres Verzeichnis anzulegen genügt **nicht** — es gilt weiter
als verschwunden.

### Secrets

Wie in Spec §7 festgelegt: `config/openclaw.json` enthält keine Schlüssel.
`OPENAI_API_KEY` kommt über `.env` (aktuell absichtlich leer — ein eigener
Schlüssel für `sales-claw` wird erst ab Task 5 benötigt und vom Betreiber separat
angelegt). Der Gateway-Token entsteht im Container und liegt ausschließlich im
Volume `sales-claw-state`, nie im Repository.

## Modellanbieter (Task 8)

Bis ein eigener, guthabengedeckter Schlüssel für `sales-claw` existiert, läuft der
Rauchtest über OpenRouter statt über OpenAI.

**Nativer Provider, kein `OPENAI_BASE_URL`.** OpenClaw hat OpenRouter als eigenen,
first-class Provider eingebaut (Modellreferenz `openrouter/<modell>`, Schlüssel über
`OPENROUTER_API_KEY`). Ein Umweg über `OPENAI_BASE_URL` — der auf einen OpenAI-
kompatiblen Endpunkt zeigen würde — ist deshalb nicht nötig. Das ist auch mit der
Randbedingung „kein lokales Modell" vereinbar: `OPENAI_BASE_URL` bleibt ungesetzt,
und OpenRouter ist ein gehosteter Dienst, keine lokale Laufzeit.

**`openrouter/free` als bewusste Ausnahme von der Pin-Regel.** `agents.defaults.model.primary`
steht auf `openrouter/free` statt auf ein einzelnes, gepinntes Modell. OpenRouters
„Free Models Router" wählt automatisch unter mehreren kostenlosen Modellen, wodurch
der Rauchtest nicht am Tageskontingent eines einzelnen Modells hängt. Das
widerspricht der sonstigen Pin-Regel dieses Projekts ausdrücklich — die Ausnahme gilt
**nur für die Fundament-Stufe**, solange niemand mit echten Kunden spricht. Sobald
echte Beratungsgespräche laufen, wird hier ein bezahltes, einzeln gepinntes Modell
eingetragen.

**Damit die Referenz `openrouter/free` überhaupt auflöst**, muss zusätzlich zu
`agents.defaults.model.primary` ein passender Katalogeintrag unter
`models.providers.openrouter.models` existieren — der statische, im Image
mitgelieferte Modellkatalog kennt „Free Models Router" nicht von sich aus (er taucht
nur im Live-Scan von `openclaw models scan` auf, nicht in `openclaw infer model list`).
Ohne diesen Eintrag bricht `openclaw agent` mit `FailoverError: Unknown model` ab.
`config/openclaw.json` enthält den Eintrag deshalb explizit; das ist eine Ergänzung
über die ursprünglich vorgesehene Ein-Zeilen-Änderung hinaus.

**Geteiltes Kontingent.** Das Freikontingent von OpenRouters kostenlosen Modellen wird
pro Schlüssel global geteilt — nicht nur mit anderen Anfragen dieses Projekts, sondern
mit jeder Anwendung, die denselben `OPENROUTER_API_KEY` verwendet. Rate-Limits können
deshalb auch durch fremde Last auf demselben Schlüssel entstehen, nicht nur durch
`sales-claw` selbst.

**Nicht geeignet für echte Beratungsgespräche.** `openrouter/free` routet automatisch
und ohne Kontrolle darüber, welches konkrete Modell eine gegebene Anfrage beantwortet;
Qualität, Kontextverhalten und Verfügbarkeit schwanken zwischen den darunterliegenden
Modellen. Für reale Kundengespräche ist das ausdrücklich **nicht** geeignet — dafür ist
ein bezahltes, einzeln ausgewähltes und gepinntes Modell vorgesehen, sobald ein
guthabengedeckter Schlüssel vorliegt.

## Reale Abweichungen vom in Task 2 unterstellten Ablauf

Diese zwei Punkte hat der Task-2-Brief nicht vorhergesehen. Beide sind bei der
Umsetzung aufgetreten und mussten korrigiert bzw. umgangen werden — Details und
Log-Auszüge stehen im Umsetzungsbericht (`task-2-report.md`).

1. **Volume-Namen brauchen ein explizites `name:`.** Ohne diese Angabe prefixt
   Compose die in `docker-compose.yml` deklarierten Volumes mit dem
   Projektnamen (`sales-claw_sales-claw-state` statt `sales-claw-state`) und
   verfehlt damit die in den Randbedingungen geforderten literalen Namen.
   `docker-compose.yml` setzt deshalb `name: sales-claw-state` /
   `name: sales-claw-keys` explizit.
2. **Bootstrap-Reihenfolge für den Gateway-Token.** `gateway.auth.mode: "token"`
   zusammen mit `bind: "lan"` lässt den Gateway-Prozess mit
   „Refusing to bind gateway to lan without auth." abbrechen, solange kein Token
   im Volume liegt — der Container bleibt dauerhaft im Neustart-Zyklus
   (`Restarting`, niemals `running`). Der im Brief vorgesehene Weg,
   `docker compose exec sales-claw …`, setzt aber einen laufenden Container
   voraus und schlägt deshalb fehl (`Container … is restarting, wait until the
   container is running`). Funktionierender Ablauf: den Token per **Einweg-Container**
   setzen, bevor der Dauerdienst startet:
   ```bash
   docker compose run --rm --entrypoint sh sales-claw \
     -lc 'openclaw config set gateway.auth.token "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d " \n")"'
   docker compose up -d
   ```
   Erst danach erreicht der Dauerdienst `healthy`. Diese Reihenfolge gehört in
   `docs/03_RUNBOOK.md`, sobald dieses Dokument entsteht.

Zusätzliche Beobachtung ohne Handlungsbedarf: `openclaw config get
gateway.auth.token` gibt in dieser Version nicht den Klartext-Token aus, sondern
`__OPENCLAW_REDACTED__` — strenger als der Brief unterstellt hat (der von einer
48-stelligen Hex-Ausgabe ausging), aber keine Regression, sondern zusätzlicher
Schutz gegen versehentliches Kopieren des Tokens in Logs oder Dokumente.
