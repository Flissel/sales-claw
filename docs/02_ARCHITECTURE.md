# 02 — Architektur

Quelle Stufe 1: `docs/superpowers/specs/2026-08-17-sales-claw-fundament-design.md` §5, §7.
Diese Fassung ergänzt die dort beschriebene Soll-Architektur um die bei der
Umsetzung von Task 2 **tatsächlich gemessenen** Werte und zwei reale
Abweichungen vom Ablauf, den der Task-2-Brief unterstellt hat.

Quelle Stufe 2 (Abschnitt weiter unten): `docs/superpowers/specs/2026-08-18-sales-claw-stufe2-prototyp-design.md`
§1–§9, ergänzt um die bei der Umsetzung der Tasks 1–5 tatsächlich gemessenen Werte
(`.superpowers/sdd/2026-08-18-sales-claw-stufe2-prototyp/task-{1..5}-report.md`).

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

**Primärmodell: `anthropic/claude-sonnet-5`, gepinnt (seit 19.08.2026).**
`agents.defaults.model.primary` steht auf einem einzeln gepinnten Claude-Modell;
authentifiziert wird nicht per API-Schlüssel, sondern über ein Abo-Token aus dem
Claude-Abo des Betreibers (Auth-Profil `anthropic:manual`, Einrichtung und
Token-Lage: `docs/03_RUNBOOK.md`, Abschnitt „Modellwahl"). Damit ist die
Pin-Regel des Projekts wieder erfüllt. Für Produktivbetrieb mit Dritten ist
weiterhin ein API-Schlüssel mit eigener Abrechnung vorgesehen — ein
persönliches Abo darf nicht Backend für Dritte sein.

**`openrouter/free` als Fallback — die frühere Pin-Ausnahme, jetzt Reserve.**
In der Fundament-Stufe war `openrouter/free` das Primärmodell (bewusste Ausnahme
von der Pin-Regel: OpenRouters „Free Models Router" wählt automatisch unter
mehreren kostenlosen Modellen, wodurch der Rauchtest nicht am Tageskontingent
eines einzelnen Modells hing). Seit 19.08.2026 steht er nur noch in
`agents.defaults.model.fallbacks`: Ist das Abo-Kontingent erschöpft, antwortet
der Agent weiter — mit den unten dokumentierten Qualitätsschwankungen statt gar
nicht. Das Freigabe-Gate ist davon unabhängig.

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

**Der Fallback ist nicht für echte Beratungsgespräche geeignet.** `openrouter/free`
routet automatisch und ohne Kontrolle darüber, welches konkrete Modell eine gegebene
Anfrage beantwortet; Qualität, Kontextverhalten und Verfügbarkeit schwanken zwischen
den darunterliegenden Modellen. Greift der Fallback während eines realen
Kundengesprächs, ist das an der Antwortqualität erkennbar — Entwürfe aus solchen
Phasen vor der Freigabe besonders kritisch lesen.

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

## Architektur (Stufe 2): sales-mcp und die Datenbank

Stufe 2 fügt eine zweite bewegliche Komponente hinzu: einen eigenen Werkzeugdienst
(`sales-mcp`) zwischen dem Agenten und einer Postgres-Datenbank auf der Proxmox-VM.
Warum ein eigener Dienst statt OpenClaw-Skills, steht in der Spec §3 begründet
(unabhängig testbar, überlebt OpenClaw-Updates, aus Claude Code heraus mitbenutzbar,
spätere Versand-App arbeitet gegen dieselbe DB).

```text
WhatsApp (Nummer des Betreibers, Selbst-Chat-Demo)
        │
        ▼
┌──────────────────────────────┐        ┌───────────────────────────────────┐
│ Container sales-claw         │  MCP   │ Container sales-mcp                │
│ OpenClaw 2026.7.1-slim       │◄──────►│ Python, 9 Werkzeuge                 │
│ Agent "main"                 │streamable-http, http://sales-mcp:8765/mcp   │
│ + config/workspace/AGENTS.md │        │ kontakt_*, aktivitaet_*, profil_*,  │
│   (Leitfaden, Verbote)       │        │ bedarf_*, entwurf_*, digest         │
│                               │        │ kein ports:-Eintrag (Host-seitig    │
│                               │        │ nicht erreichbar)                   │
└──────────────────────────────┘        └────────────────┬────────────────────┘
                                                          │ SQL (Rolle sales_app,
                                                          │ kein DDL)
                                                          ▼
                                        Supabase-Postgres, Proxmox-VM 192.168.178.65:54322
                                        Schema `sales` (+ `sales_test`)
                                        Eigentümer aller Objekte: supabase_admin
```

Beide Container stehen auf `restart: "no"` — Demo-Betrieb, dieselbe Begründung wie bei
`sales-claw` (Kommentar in `docker-compose.yml`): sie laufen nur, wenn ausdrücklich
gestartet.

### sales-mcp: Werkzeugdienst

Neun Werkzeuge, alle deutsch benannt, kein Send-Werkzeug (`sales-mcp/server.py`):

| Werkzeug | Zweck |
|---|---|
| `kontakt_suchen(text)` | Kontakt per Name/E-Mail/Telefon finden |
| `kontakt_anlegen(name, email="", phone="", source="whatsapp", notes="")` | Neuen Kontakt anlegen |
| `aktivitaet_loggen(lead_id, typ, inhalt)` | Interaktion unveränderlich protokollieren |
| `profil_lesen(lead_id)` | Kundenprofil + letzte Aktivitäten lesen |
| `profil_aktualisieren(lead_id, feld, wert)` | Ein Profilfeld setzen, kumulativ |
| `bedarf_speichern(lead_id, frage_id, antwort)` | Leitfaden-Antwort strukturiert ablegen |
| `bedarf_offen(lead_id)` | Fehlende Leitfaden-Punkte |
| `entwurf_erstellen(lead_id, kanal, text, betreff="")` | Entwurf mit `status='pending'` anlegen |
| `digest()` | Offene Entwürfe, unvollständige Analysen, letzte Aktivitäten |

Transport: `streamable-http`, gebunden an `0.0.0.0:8765` im Container. **Port 8765 ist
nicht veröffentlicht** — `docker-compose.yml` hat für `sales-mcp` bewusst keinen
`ports:`-Eintrag; der Dienst kennt die Kundendaten-DB und ist deshalb ausschließlich im
Compose-Netz erreichbar, nicht vom Host aus.

**Bibliotheksversion abweichend vom Brief, gemessen (Task 2):** `requirements.txt`
verlangte zunächst `mcp>=1.2`, aufgelöst wurde beim Build `mcp==2.0.0` — ein
Major-Sprung. Die dort erwartete Klasse `mcp.server.fastmcp.FastMCP` existiert in
dieser Version nicht mehr; sie heißt jetzt `MCPServer`
(`mcp.server.mcpserver.MCPServer`), ihr Konstruktor nimmt kein `host`/`port` mehr
entgegen — beides wandert zu `.run(transport=..., host=..., port=...)`.
`transport="streamable-http"` selbst blieb unverändert. `requirements.txt` ist seit
Task 3 auf `mcp>=2.0,<3` gepinnt, damit ein künftiger Major-Bump denselben Bruch nicht
wiederholt.

### Datenbank: Schema `sales`/`sales_test` und die Rechtematrix

Vier Tabellen (`db/provision.sql`), identisch in beiden Schemata: `leads`,
`activities`, `drafts`, `personas`. Rolle `sales_app`:
`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`, Eigentümer aller Objekte ist
`supabase_admin` — `sales_app` hat **keine DDL-Rechte**.

Wirksame Rechte, gemessen gegen `information_schema.table_privileges` (Task 1,
Schritt 3/4):

| Tabelle | `sales` (Demo/Produktion) | `sales_test` |
|---|---|---|
| `leads` | SELECT, INSERT, UPDATE | + DELETE, TRUNCATE |
| `activities` | **SELECT, INSERT — sonst nichts** | + UPDATE, DELETE, TRUNCATE |
| `drafts` | SELECT, INSERT, UPDATE | + DELETE, TRUNCATE |
| `personas` | SELECT, INSERT, UPDATE | + DELETE, TRUNCATE |

`sales.activities` ist damit **append-only als Datenbank-Garantie**, nicht nur als
Konvention im Code: Selbst ein Bug oder ein kompromittierter Agent kann die
protokollierte Historie nicht nachträglich verändern. Nachgewiesen (Task 1,
Schritt 6, `\set VERBOSITY verbose` gegen die VM-Datenbank, Rolle `sales_app`):

```
update sales.activities set type='geaendert';
ERROR:  42501: permission denied for table activities

delete from sales.activities;
ERROR:  42501: permission denied for table activities

create table sales.hack (id int);
ERROR:  42501: permission denied for schema sales
```

Beide Schreibverbote — **UPDATE und DELETE**, nicht nur das im Brief geforderte
UPDATE — sind mit SQLSTATE 42501 belegt, ebenso das fehlende DDL-Recht (`create
table` scheitert am Schema selbst, nicht erst an der Tabelle).

**`sales_test`-Grants sind eine Momentaufnahme (bekannte Falle).** `grant ... on all
tables in schema sales_test to sales_app` wirkt nur auf die zum
Provisionierungszeitpunkt vorhandenen vier Tabellen — es gibt kein `alter default
privileges`. Eine später in `sales_test` neu angelegte Tabelle erbt die Rechte nicht
automatisch; die Testsuite schlägt dann mit 42501 fehl, an einer Stelle, die wie ein
Testfehler aussieht und keiner ist. Wer `db/provision.sql` erweitert, muss den Grant
für neue Tabellen manuell nachziehen.

### MCP-Registrierung: Fall A bestätigt

Spec §8 hatte offengelassen, ob OpenClaw 2026.7.1 HTTP-MCP-Server direkt spricht
(Fall A) oder eine `mcp-remote`-Brücke braucht (Fall B). Gemessen (Task 4,
Schritt 2): `openclaw mcp add --help` zeigt `--url <url>` direkt — **Fall A**, keine
Brücke nötig. Registrierungsbefehl, wörtlich:

```powershell
docker compose exec sales-claw openclaw mcp add sales `
    --url http://sales-mcp:8765/mcp --transport streamable-http
```

`--transport` wurde bewusst explizit gesetzt statt sich auf einen ungeprüften Default
zu verlassen, weil `server.py` `transport="streamable-http"` fest einträgt. Ausgabe:
`Saved MCP server "sales" to /home/node/.openclaw/openclaw.json.` Kein Neustart von
`sales-claw` für die Registrierung selbst nötig. Die Registrierung liegt im Volume
`sales-claw-state` und überlebt `down`/`up` (Task 4, Schritt 4: `openclaw mcp list`
zeigt `sales` unverändert nach einem Neustart).

### Architektur-Lehre: der functools.wraps-Vorfall

Ein Bug, der die gesamte Werkzeuganbindung lahmlegte, ohne dass Verbindung oder
Registrierung einen Fehler zeigten — festgehalten, weil das Muster in jedem
künftigen MCP-Dienst wiederkehren kann.

`_gesichert`, der Fehlerbehandlungs-Dekorator um alle neun Werkzeuge, kopierte
ursprünglich von Hand nur `__name__` und `__doc__` von der eingepackten Funktion,
statt `functools.wraps` zu verwenden. Die MCP-Registrierung (`mcp.tool()`, in
`mcp==2.0.0`) baut das JSON-Schema eines Werkzeugs aber aus `inspect.signature()` —
und diese Introspektion sieht nur die äußere Wrapper-Funktion `def innen(*a,
**kw)`, nicht die echten Parameter der eingepackten Funktion. Gemessen (Task 4):
**für alle neun Werkzeuge** lieferte `inspect.signature()` dieselbe leere Signatur
`(*a, **kw)` — auch für `digest()` ohne echte Parameter und für
`kontakt_suchen(text)` mit einem. Das erzeugte MCP-Schema kannte damit für jedes
Werkzeug nur zwei bedeutungslose Parameternamen (`a`, `kw`); jeder Agentenaufruf mit
den echten Parameternamen (z. B. `name=...`) scheiterte mit `kontakt_suchen() got an
unexpected keyword argument 'a'`. Die Anbindung selbst (Container läuft, `openclaw
mcp list` zeigt `sales`, Verbindung steht) blieb dabei unauffällig — sichtbar wurde
der Fehler erst beim tatsächlichen Werkzeugaufruf.

**Warum die elf Tests aus Task 2/3 das nicht auffingen:** Sie rufen die
Werkzeug-Funktionen direkt in Python auf (`server.kontakt_anlegen(name=...)`), nie
über den `mcp.tool()`-Registrierungspfad — der Bug existiert nur auf der
Introspektionsebene, die die Tests nie durchlaufen.

Fix (Fix-Runde 1, Commit `81a727b`): `@functools.wraps(fn)` statt der manuellen
Attributkopie. Regressionstest ergänzt
(`test_werkzeug_signaturen_ueberleben_den_dekorator`, prüft `"name" in
inspect.signature(server.kontakt_anlegen).parameters`), rot vor dem Fix, grün
danach. Dienst per `docker compose build sales-mcp && docker compose up -d
sales-mcp` ausgetauscht — `sales-claw` dabei nachweislich **nicht** neu gestartet
(`StartedAt` identisch). End-to-End-Nachweis über einen Agentenlauf mit frischem
`--session-key`: Der Agent rief `sales__kontakt_anlegen` mit dem echten Parameter
`name=...` auf, erhielt eine `lead_id` zurück; DB-Gegenprobe bestätigte genau eine
neue Zeile.

**Die Lehre, allgemein:** Jeder Dekorator, der vor der MCP-Registrierung auf eine
Werkzeugfunktion gelegt wird, muss deren Signatur erhalten — per `functools.wraps`
oder explizitem `__signature__` —, weil das MCP-Schema aus genau der Introspektion
der (möglicherweise verpackten) registrierten Funktion entsteht, nicht aus einer
separat „wahren" inneren Funktion. Der Quellcode-Kommentar in `sales-mcp/server.py`
(`_gesichert`) hält das jetzt direkt am Ort des Risikos fest.

### Bedarfsanalyse-Leitfaden: Struktur bindend, Inhalt Platzhalter

`sales-mcp/leitfaden.yaml` (acht Fragengruppen) ist fachlich ein **Platzhalter aus
Branchenwissen** — Reihenfolge, Pflichtfelder und Formulierungen brauchen Input von
MH Consulting (Spec §5, offener Punkt). Die Datei markiert das im Kopfkommentar
selbst: „Struktur ist bindend, Inhalte sind austauschbar." Laut Agent-Instruktionen
(`config/workspace/AGENTS.md`) gibt der Bot grundsätzlich **keine**
Produktempfehlungen und keine Aussagen zu Rendite, Steuern oder Konditionen — bei
solchen Fragen: aufnehmen, als `offener_punkt` loggen, an die Beraterin verweisen.

### Produktgrenze: nichts wird versendet

Bindend seit der Spec (§1): Der Prototyp versendet nichts. Kein LinkedIn-Versand,
kein WhatsApp-Outbound über den Demo-Selbst-Chat hinaus. `entwurf_erstellen` legt
Entwürfe ausschließlich mit `status='pending'` in `drafts` ab — dort bleiben sie.
Die Tabelle `drafts` ist die Schnittstelle zu einer **später** zu bauenden,
separaten Versand-App, die dieselbe Datenbank liest; `sales-mcp` selbst enthält kein
Send-Werkzeug (verifiziert: keine der neun Funktionen liefert irgendeine Form von
Zustellung). Der LinkedIn-Dev-Account des Betreibers dient nur als
Absender-Persona der Beispieltexte, nicht als API-Anbindung.

**Kandidat für die Versand-App (geprüft 2026-08-18, noch nicht entschieden):**
[OpenWA](https://github.com/rmyndharis/OpenWA) — ein selbstgehostetes
WhatsApp-REST-Gateway (Multi-Session, Webhooks mit HMAC, Rate-Limiter). Für eine
Pilotphase mit dedizierter Nummer geeignet, der `whatsapp-web.js`-Motor gilt als
sperr-risikoärmer als Baileys — aber OpenWAs eigene Compliance-Dokumentation
erklärt sich für Finanz-/EU-regulierte Umgebungen ausdrücklich für **„not
approved"** und verweist auf Metas offizielle Cloud API. Für den Echtbetrieb bei MH
Consulting bleibt der offizielle Weg gesetzt.

### Netzausfall-Verhalten (definiert, nicht nur beabsichtigt)

Ist die VM-Datenbank nicht erreichbar, antwortet der Bot weiter — aber sagt
ausdrücklich, dass Protokoll und Profil gerade nicht gespeichert werden. Kein
stilles Weiterarbeiten mit Gedächtnisverlust. Implementiert in `_gesichert`:
`psycopg.OperationalError` (dazu zählt, geprüft, auch `psycopg_pool.PoolTimeout` —
dessen `__mro__` enthält `OperationalError`) wird in den festen Fehlertext
übersetzt:

> „Datenbank nicht erreichbar — Protokoll und Profil werden gerade NICHT
> gespeichert. Sag das dem Gespraechspartner ausdruecklich und versuche es spaeter
> erneut."

(Wortlaut inklusive ASCII-Schreibweise wie im Quellcode, `sales-mcp/server.py`,
Konstante `DB_FEHLER`.) Nachgewiesen mit einer absichtlich kaputten DSN (Task 2):
`kontakt_suchen`/`kontakt_anlegen` liefern exakt diesen Text als JSON, kein
Traceback, kein falsches Grün.

### Offene Punkte vor Stufe 3 (Spec §9.6/§9.7)

Zwei Konstruktionsentscheidungen sind im Prototyp folgenlos, aber vor dem ersten
echten Kundenkontakt zwingend zu klären:

1. **Consent-Heuristik.** `bedarf_speichern` erkennt Einwilligung per Präfix-Match
   auf die Antwort (`"ja"`, `"gern"`, `"ok"`, `"einverstanden"`). Empirisch belegt
   (Task-3-Review): „Ja, aber bitte nicht per WhatsApp", „Jain" und „ja nicht"
   werden **fälschlich als `opt_in`** gewertet. Im Prototyp folgenlos (nichts wird
   versendet, keine echten Kunden) — vor Stufe 3 muss die Erkennung Negationen
   verstehen, oder die Normalisierung wird an das Modell ausgelagert.
2. **Entwurfs-Empfänger.** Fehlt für einen Kanal die passende Adresse (`whatsapp` →
   Telefon, `email` → E-Mail), fällt `entwurf_erstellen` auf den Namen als
   `recipient` zurück. Eine spätere Versand-App muss damit rechnen — oder das
   Werkzeug lehnt kanalunpassende Empfänger ab, sobald echte Zustellung existiert.

## Architektur (Stufe 3): Versand mit Approval (OpenWA)

Quelle: `docs/superpowers/plans/2026-08-18-sales-claw-stufe3-versand.md` (die fünf
Grundsatzentscheidungen), Berichte `t1`–`t5a` unter
`.superpowers/sdd/2026-08-18-sales-claw-stufe3-versand/`, Ledger `progress.md`
ebenda.

Stufe 3 fügt zwei weitere bewegliche Komponenten hinzu: einen eigenen
Versand-Dienst (`sales-dispatch` — gleiches Image wie `sales-mcp`, zweites
Kommando `python dispatch.py`) und ein selbstgehostetes WhatsApp-Gateway
(`openwa`, [rmyndharis/OpenWA](https://github.com/rmyndharis/OpenWA), eigene
`docker-compose.openwa.yml`). LinkedIn bleibt bewusst Handversand: der Agent
legt einen Entwurf an, der Betreiber sendet ihn selbst und quittiert das nur.

### Die Kette: Agent → drafts → Freigabe → Dispatcher → OpenWA

```text
Betreiber (WhatsApp, dedizierte sales-Nummer)
   │ Nachricht                                     ▲ Antwort/Rückfrage
   ▼                                                │
┌───────────────────────────────────────────────────┴─┐
│ Container sales-claw — Agent                          │
│   KEIN Send-Werkzeug. entwurf_erstellen(kanal, text)  │
└──────────────────────────┬─────────────────────────────┘
                            │ INSERT status='pending'
                            ▼
                 ┌────────────────────────┐
                 │ Tabelle sales.drafts    │  ← das Gate ist die Datenbank,
                 └────────────┬────────────┘    nicht das Modellverhalten
                            │
                            │ Betreiber sagt im Chat AUSDRÜCKLICH „gib frei"
                            │ → entwurf_freigeben(draft_id)
                            │   [einzige Funktion, die 'approved' setzt]
                            ▼
              status='approved', channel='whatsapp'
                            │
                            │ sales-dispatch: alle 10 s
                            │ SELECT … WHERE status='approved' LIMIT 5
                            ▼
┌─────────────────────────────────────────────────────┐
│ Container sales-dispatch — die einzige sendende       │
│ Komponente des gesamten Systems                       │
│  1. claim(): approved → failed + Marke „in Zustellung │
│     seit …" (atomarer UPDATE, DDL-frei, siehe unten)  │
│  2. Kontakt-Freigabe? leads.enrichment→               │
│     whatsapp_freigabe (kontakt_freigeben, Runbook)     │
│     — fehlt/entzogen → failed mit Grund, kein Netz     │
│  3. normalisiere_empfaenger() — nummern.py            │
│  4. POST /api/sessions/{id}/messages/send-text         │
│     (Header X-API-Key)                                 │
│  5. Erfolg → sent · Fehler → failed + echter Fehlertext│
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
                            ▼
                 ┌────────────────────────┐
                 │ Container openwa         │  Session „sales"
                 │ eigener MCP-Server AUS   │  bis QR-Scan: HTTP 409
                 │ (MCP_ENABLED ungesetzt)  │  „Session not connected"
                 └────────────┬─────────────┘
                            ▼
                    WhatsApp (dedizierte Nummer)

LinkedIn — paralleler Zweig, vom Dispatcher NIE angefasst:
  drafts(channel='linkedin', status='approved')
      → Betreiber sendet von Hand → meldet „Entwurf … ist raus"
      → entwurf_manuell_gesendet(draft_id) quittiert (status='sent')
        (versendet selbst nichts, kein HTTP-Aufruf)
```

### Die fünf Grundsatzentscheidungen (bindend, aus dem Plan)

1. **Der Agent bekommt keine Send-Werkzeuge.** OpenWAs eingebauter
   MCP-Server bleibt aus (`MCP_ENABLED` in `docker-compose.openwa.yml`
   bewusst ungesetzt, nicht nur `false`). Versand macht ausschließlich
   `sales-dispatch`, der nur `drafts.status='approved'` liest. Das Gate ist
   die Datenbank, nicht das Verhalten eines Sprachmodells.
2. **OpenWA bekommt nie die persönliche Nummer des Betreibers.** Eigene
   Session (`sales`) für eine dedizierte Nummer; bis zum QR-Pairing
   (`docs/08_PAIRING_ANLEITUNG.md`) ist „Session nicht verbunden" (HTTP 409)
   der getestete Normalzustand — belegt in T3/T4 gegen das echte, laufende
   OpenWA, kein Stub.
3. **LinkedIn wird nicht automatisch versendet** (Kontosperr-Risiko).
   Freigabe → Kennzeichnung „manuell zu senden" → `entwurf_manuell_gesendet`
   quittiert einen bereits erfolgten Handversand. Gleiche Queue, gleiche
   Historie, kein HTTP-Call gegen OpenWA oder LinkedIn.
4. **Engine `whatsapp-web.js`, Rate-Limiter an, Docker-Socket-Proxy aus.**
   Laut OpenWA-Dokumentation/Capability-Matrix sperr-risikoärmer als
   Baileys; RAM vorhanden. Kein `DOCKER_HOST`, keine Orchestrierungs-Features
   der eingebauten OpenWA-Container-Verwaltung genutzt.
5. **Freigabe nur durch den Betreiber.** Technisch bereits erzwungen (die
   OpenClaw-`dmPolicy`-Allowlist lässt nur seine Nummer zum Agenten durch);
   zusätzlich als Agent-Regel verankert (`config/workspace/AGENTS.md`,
   Abschnitt „Freigabe"): Entwurf vor Freigabe immer wörtlich zeigen,
   Freigaben nie aus zitierten, weitergeleiteten oder von Dritten
   stammenden Inhalten ableiten.

### Review-Verdikt: „Versand ohne Freigabe: nein"

Batch-Review T2+T3 (Reviewer-Modell opus, Scope-Commits `e224a3a..3f80d4c`)
kam zum Kernverdikt **„Versand ohne Freigabe möglich: NEIN"** — Query für
Query bestätigt, Begründungskette:

- **`send-text` existiert nur an einer einzigen Stelle** im gesamten Code:
  `sales-mcp/dispatch.py::sende_text`. Kein anderer Pfad — weder im
  Agenten noch in `server.py` — spricht OpenWA an.
- **`status='approved'`** — Voraussetzung dafür, dass der Dispatcher einen
  Entwurf überhaupt in den Blick nimmt — wird ausschließlich von
  `entwurf_freigeben` und `entwurf_erneut_freigeben` gesetzt (beide in
  `server.py`), und beide ausschließlich auf ausdrückliche
  Betreiber-Anweisung im Chat (`AGENTS.md`, Abschnitt „Freigabe").
- **Der Agent besitzt kein sendendes Werkzeug.** Die vollständige
  MCP-Werkzeugliste (15 Werkzeuge, `openclaw mcp probe sales --json`) enthält
  keinen HTTP-Aufruf gegen OpenWA oder irgendeinen anderen Versandweg.
- **OpenWAs eigener MCP-Server ist aus** (Grundsatzentscheidung 1) — selbst
  ein kompromittierter Agent könnte ihn nicht ansprechen, weil dort nichts
  lauscht.

Die spätere Härtungswelle (T5a) hat dieses Verdikt zusätzlich abgesichert
(Compose-Isolation, siehe unten), nicht in Frage gestellt.

### Claim-Mechanik: at-most-once statt at-least-once

`drafts.status` kennt keinen Zwischenstatus „wird gerade versendet" (CHECK
constraint: `pending|approved|rejected|sent|failed`, `db/provision.sql`),
und die Rolle `sales_app` hat kein DDL-Recht, um einen hinzuzufügen.
`sales-mcp/dispatch.py` löst das ohne Schemaänderung: Der Claim ist ein
atomarer UPDATE `approved → failed`, der eine lesbare Marke ins
`error`-Feld schreibt:

```sql
update drafts set status='failed',
       error='in Zustellung seit <UTC> (dispatcher <token>)'
 where id=%s and status='approved' and channel='whatsapp'
 returning id, lead_id, recipient, subject, body;
```

Zwei nebenläufige Dispatcher können denselben Entwurf nie beide gewinnen:
der zweite UPDATE sieht nach dem Commit des ersten `status='failed'` und
liefert null Zeilen (READ COMMITTED + Zeilensperre). Buchung von Erfolg und
Fehler läuft ausschließlich gegen die **eigene** Marke (`error = <exakte
Marke>` in der WHERE-Klausel) — ein Dispatcher löst nie den Claim eines
anderen auf.

**Bewusst at-most-once, nicht at-least-once.** Die naheliegende Alternative
— `select … for update skip locked` mit einer über den HTTP-Aufruf hinweg
offen gehaltenen Transaktion — wurde geprüft und verworfen: Sie liefert
at-least-once. Ein Absturz *nach* erfolgreichem Senden, aber vor dem
Commit, gäbe die Zeile wieder als `approved` frei, und die nächste Runde
schickt dieselbe Vertriebsnachricht ein zweites Mal an einen echten
Menschen. Der Claim ist deshalb **vor** dem Senden committet: Stirbt der
Prozess mitten im Versand, bleibt der Entwurf als `failed` mit der Marke
liegen und wird **nie** automatisch erneut versucht — ein liegengebliebener
Entwurf ist das kleinere Übel als ein Doppelversand.

**Dokumentierter Restfall.** Ein Absturz zwischen erfolgreichem Senden und
der Buchung auf `sent` (`_als_gesendet_buchen`) ist die eine Lücke, die
diese Konstruktion strukturell nicht schließen kann: Die Nachricht ist beim
Empfänger angekommen, aber der Entwurf trägt weiter die Claim-Marke. Für
genau diesen Fall verweigert `entwurf_erneut_freigeben` eine erneute
Freigabe, solange der `error`-Text mit „in Zustellung" beginnt — nur mit dem
ausdrücklichen Parameter `bestaetigt=True` lässt sich das überschreiben,
nachdem der Betreiber vor dem Risiko eines Doppelversands gewarnt wurde
(`server.py`, Schutzkante über `_CLAIM_MARKE_PRAEFIX`; Ablauf im Runbook,
Abschnitt „Stufe 3"). Der Absturz-Fall selbst ist nur unit-/mutationsgetestet
(`sales-mcp/tests/test_dispatch.py`), nicht live gegen einen echten
Prozessabsturz erzwungen — das ließe sich nur durch ein absichtliches
Kill-mitten-im-Senden nachstellen, was gegen den laufenden Container ein
unnötiges Risiko wäre und deshalb unterblieben ist.

### Nummern-Regeln (`sales-mcp/nummern.py`) und die Amtsnull-Geschichte

Zustellbar ist nur eine Nummer, die ihre Landesvorwahl **selbst mitbringt**
— es wird nicht geraten:

| Eingabe (nach Bereinigung) | Ergebnis |
|---|---|
| `+<vorwahl><nummer>` | `<ziffern>@c.us` |
| `00<vorwahl><nummer>` | `<ziffern>@c.us` |
| `49<nummer>` — blank, ohne `+`/`00`, 11–15 Stellen | `<ziffern>@c.us` |
| blanke Ziffernfolge ohne `49`-Präfix (kein `+`, kein `00`) | **failed** — `Landesvorwahl nicht erkennbar — Empfaenger mit +Vorwahl erfassen` |
| `0…` ohne `00` (nationale Schreibweise) | **failed** — `Empfaenger ohne Landesvorwahl ('0…') — mit +Vorwahl erfassen, nationaler Schreibweise wird nicht vertraut` |
| Name, E-Mail, Mischform, zu kurz/lang, leer | **failed** — `kein zustellbarer Empfaenger` |

**Zwei Befunde derselben Klasse — beide durch Review, keiner durch eigenen
Vorschlag.** Bis zur Batch-Review (T2+T3) galt eine bequemere
„Amtsnull-Regel": eine führende `0` ohne Landesvorwahl wurde als
**deutsche** Nummer gelesen (`0170…` → `49170…`) — naheliegend, weil das
die mit Abstand häufigste Schreibweise ist, die ein Betreiber oder Kunde
nennt. Die Review deckte den Preis auf: Die Regel griff für **jede**
national geschriebene Nummer, auch für eine österreichische
(`0664 1234567` → `496641234567@c.us`) — eine wohlgeformte, echte deutsche
Mobilnummer eines am Vorgang gänzlich unbeteiligten Menschen. Eine
Vertriebsnachricht wäre dorthin gegangen, und der Versand hätte `sent`
gemeldet, ohne dass irgendwo ein Fehler sichtbar geworden wäre. T5a hat
diese Regel entfernt: eine führende `0` ohne `00` wird seither ausnahmslos
zurückgewiesen (`FEHLER_NATIONALE_SCHREIBWEISE`).

**Ein zweiter, gleichartiger Befund folgte in der Fix-Runde nach T5b**
(Commit `63c8978`, Review-Fund): T5a hatte die Prüfung auf blanke
Ziffernfolgen — Eingaben **ohne** `+`, **ohne** `00` und **ohne** führende
`0` — auf „mindestens 10 Stellen" verkürzt, unter der unausgesprochenen
Annahme, eine so lange Folge bringe ihre Landesvorwahl schon selbst mit.
Geprüft wurde das nie. Live belegt: `1701234567` ist eine deutsche
Mobilnummer ohne `+49` und ohne führende `0` — gelesen wurde sie jedoch als
US-Vorwahl `1` + `701`, ein realer, existierender Vorwahlbereich in North
Dakota. Genau dieselbe Fehlerklasse wie die Amtsnull-Falle, nur eine Ebene
tiefer: aus einer unvollständigen Eingabe wurde still eine wohlgeformte
**fremde** Nummer, und der Versand hätte auch hier `sent` gemeldet, ohne
sichtbaren Fehler.

**Die daraus resultierende, jetzt gültige Regel:** Eine blanke Ziffernfolge
(ohne `+`, ohne `00`) ist nur noch zustellbar, wenn sie mit `49` beginnt
und 11–15 Stellen lang ist — `49` ist die einzige Landesvorwahl, der dieser
Einsatz (deutscher Finanzvertrieb) ohne ausdrückliches `+`/`00`-Zeichen
vertraut. Jede andere blanke Ziffernfolge liefert `failed` mit
`Landesvorwahl nicht erkennbar — Empfaenger mit +Vorwahl erfassen`, statt
geraten zu werden. Die Lehre aus beiden Funden zusammen: **nur explizit
markierte Landesvorwahlen (`+`/`00`) werden über alle Präfixe hinweg
vertraut; ohne dieses Zeichen vertraut das System ausschließlich der einen
Vorwahl, die im Einsatzland gilt (`49`) — nirgends sonst wird aus einer
"lang genug aussehenden" Ziffernfolge eine Landesvorwahl unterstellt.**

Zwei Teile der ursprünglichen Amtsnull-Behandlung sind bewusst geblieben,
weil ihr Wegfall eine **neue** Fehlzustellung erzeugt hätte statt eine zu
verhindern: der Einschub `(0)` (`+49 (0)170…`, die übliche, ausdrückliche
Notation für „Amtsnull hier weglassen") wird entfernt, und eine Amtsnull
direkt hinter einer bereits **ausgeschriebenen** `49` wird gestrichen
(`+49 0170…` → `49170…`) — dort steht die Landesvorwahl schon da, es kann
also nichts verwechselt werden. Beides betrifft ausschließlich Eingaben,
die bereits eine Landesvorwahl nennen; die `49`-Sonderregel ist bewusst
nicht auf andere Vorwahlen übertragen (`+43 0664…` bleibt unkorrigiert und
scheitert sichtbar bei OpenWA statt jemanden Falschen zu erreichen).

Mutationsprobe (alte Amtsnull-Regel testweise zurückgebaut): genau elf
Tests brechen, angeführt vom AT-Fall
(`assert '496641234567@c.us' is None` schlägt fehl, weil die alte Regel
wieder eine Nummer liefert) — die Regel trägt das Gewicht, das ihr
zugeschrieben wird.

`nummern.py` ist ein eigenständiges, abhängigkeitsfreies Modul, das sowohl
`dispatch.py` (entscheidet, wohin tatsächlich zugestellt wird) als auch
`server.py` (`entwuerfe_offen` zeigt die `zielnummer` vor der Freigabe an)
importieren — ein Test hält fest, dass beide **dieselbe** Funktion benutzen
(`dispatch.normalisiere_empfaenger is nummern.normalisiere_empfaenger`),
damit eine Freigabe nie die Freigabe für etwas anderes ist als das, was
tatsächlich passiert.

### Compose-Isolation: Der Agent-Container erbt keine Versand-Secrets

`docker-compose.yml`, Dienst `sales-claw`, hatte ursprünglich
`env_file: .env` — und erbte damit `OPENWA_API_KEY` und `SALES_DB_URL`,
obwohl der Agent keines von beidem braucht (er versendet nichts, spricht
die Datenbank nur über `sales-mcp` an). Mit diesen Schlüsseln im
Agent-Container hätte ein `curl` gegen OpenWA WhatsApp-Nachrichten ohne
jeden Umweg über `drafts` versendet, und ein `psql` mit der DSN hätte
`status='approved'` selbst setzen können — das Freigabe-Gate wäre nur noch
so stark wie die Exec-Freigabeliste des Gateways gewesen, nicht mehr die
Datenbank (Grundsatzentscheidung 1 unterlaufen). Batch-Review-Befund, mit
T5a behoben: `sales-claw` bekommt jetzt eine ausdrückliche, benannte
`environment:`-Liste statt der Vererbung über `env_file`:

```yaml
environment:
  - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
  - TZ=${TZ:-Europe/Berlin}
  - OPENCLAW_STATE_DIR=/home/node/.openclaw
```

`sales-mcp` und `sales-dispatch` behalten `env_file: .env`: sie **sind** die
Vertrauensdomäne für diese Geheimnisse — der eine hält die Kundendaten-DB,
der andere ist die einzige Komponente, die versenden darf.

**Wichtig: der Fix war bis zum nächsten Recreate inert.** Ein laufender
Container behält die Umgebungsvariablen seines Erzeugungszeitpunkts; die
Änderung in `docker-compose.yml` allein hat nichts sofort bewirkt. **Scharf
seit dem tatsächlichen Recreate von `sales-claw` am 2026-08-18, gemessen
14:16:25 UTC** (`docker inspect sales-claw --format '{{.State.StartedAt}}'`
→ `2026-08-18T14:16:25…Z`). Verifiziert danach, ohne einen Wert auszugeben:

```
$ docker exec sales-claw sh -lc \
    'test -n "$OPENWA_API_KEY" && echo gesetzt || echo fehlt; \
     test -n "$SALES_DB_URL"  && echo gesetzt || echo fehlt'
fehlt
fehlt
```

`OPENROUTER_API_KEY` bleibt gesetzt (der Agent braucht ihn fürs Modell); der
Kanal (WhatsApp-Kopplung aus Stufe 1/2, `linked`/`connected`) überlebte den
Recreate unverändert.

**Nicht verwendet zur Verifikation: `docker compose config`.** Der Befehl
inlined `env_file`-Inhalte in seine Ausgabe — genau das führte in T5a zu
einem gemeldeten Secret-Vorfall (ein Schlüssel unbekannten Namens landete
im Sitzungsprotokoll eines Subagenten, außerhalb jeder Datei/jedes
Commits). Für diese Dokumentation wie für jede künftige Prüfung gilt
deshalb: Isolation über den **laufenden** Container prüfen (`docker exec …
test -n "$VAR"`, nie den Wert ausgeben), nicht über die aufgelöste
Compose-Konfiguration. `docker compose config` bleibt in diesem Repo
gesperrt.

## Architektur (Stufe 4, F4): Medien durch die Freigabe-Queue

Anhänge nehmen exakt denselben Weg wie Text: `entwurf_erstellen` legt den
Entwurf mit `media_ref` (nur der Dateiname, nie ein Pfad) als `pending` an,
ein Mensch gibt frei, der Dispatcher versendet — **ein** OpenWA-Aufruf je
Entwurf, der Text reist als Bildunterschrift mit (gemessen: `send-image`/
`send-audio`/`send-document` nehmen dasselbe DTO `{chatId, base64, mimetype,
filename, caption}`; Grenzen 1024 Zeichen Caption, 25 MB Rumpf → Dateigrenze
15 MB mit ~20 % Marge). Es gibt keinen zweiten Sendepfad und keinen
Medien-Sonderweg am Claim vorbei.

Die Prüfregel lebt in **einem** Modul (`sales-mcp/medien.py`) und läuft
**beidseitig**: beim Erstellen und unmittelbar vor dem Senden erneut — der
Medienordner ist ein Host-Bind, zwischen Freigabe und Zustellung kann eine
Datei verschwinden, und dann scheitert der Entwurf (`failed`), statt ohne
Anhang rauszugehen. Reihenfolge der Prüfung ist Absicht: Name (Traversal in
beiden Pfadkonventionen, NUL), dann Endungs-Whitelist, dann erst das
Dateisystem (Symlink-Auflösung per `realpath`, Größe, Lesbarkeit) — ein
Traversal-Versuch berührt nie einen Pfad außerhalb, auch nicht lesend.
`medien_liste` filtert über dieselbe Kette: die Liste verspricht nichts,
was die Prüfung ablehnt.

Der Ordner ist an `sales-mcp` und `sales-dispatch` **read-only** gebunden
(`rw=false`, per `touch`-Probe belegt); der Agent-Container hat keinen
Media-Bind — Dateiinhalte verlassen das System ausschließlich über den
Dispatcher, hinter dem Claim. Review-Verdikt (Commit `675421e`, geprüft
adversarial): **„Versand ohne Freigabe möglich: NEIN."**

**Dokumentiertes Restrisiko (Review-Befund B1):** Freigegeben wird der
Datei**name**, nicht der Datei**inhalt**. Wer die Datei zwischen Freigabe
und Zustellung unter gleichem Namen austauscht, versendet den neuen Inhalt.
Das Bedrohungsmodell ist der eigene Ordner des Betreibers auf seinem
eigenen Host — wer dort schreiben kann, kann ohnehin alles. Bewusst
akzeptiert statt gelöst; falls das Modell später kippt (mehrere Bediener,
Netzfreigabe auf `media/`), ist die vorgesehene Lösung ein
Inhalts-Fingerabdruck (sha256 bei Erstellung in die `freigabe`-Aktivität,
Vergleich im Dispatcher) — ohne DDL machbar.

## Architektur (Stufe 9): E-Mail-Zwilling, Termine, ICS

### `sales-mail` — derselbe Bau, anderer Kanal

`sales-mcp/mail_dispatch.py` ist der Zwilling von `dispatch.py`. Er liest
ausschließlich `drafts(status='approved', channel='email')` und stellt über
SMTP zu. Die Kanaltrennung steht in jeder Query — `channel = 'email'` hier,
`channel = 'whatsapp'` dort —, und beide Dienste greifen deshalb nie nach
demselben Entwurf (Test in beide Richtungen: `test_mail_dispatch.py`).

Claim-Marke, Erfolgs- und Fehlerbuchung werden **importiert, nicht
kopiert** (`dispatch._claim_marke`, `_als_gesendet_buchen`,
`_als_fehler_buchen`). Das ist keine Sparsamkeit: `entwurf_erneut_freigeben`
erkennt einen hängengebliebenen Versand daran, dass `drafts.error` mit
`CLAIM_PRAEFIX` („in Zustellung seit …") beginnt. Eine zweite, ähnliche
Marke hätte diese Schutzkante gegen Doppelversand für E-Mail-Entwürfe still
ausgehebelt. Importrichtung `mail_dispatch → dispatch → server`, kein
Zirkel.

Eigen ist nur, was kanalspezifisch ist: der Claim mit `channel='email'`, die
Empfängerprüfung (`mailadresse.py` statt `nummern.py`) und der Versandweg
(`smtplib` statt OpenWA-HTTP). `mailadresse.py` existiert aus demselben
Grund wie `nummern.py`: `entwuerfe_offen` zeigt dem Betreiber vor der
Freigabe die `zieladresse` an, die `sales-mail` dann tatsächlich anspricht —
Anzeige und Versand dürfen nie zwei verschiedene Regeln benutzen.

Die Adressprüfung ist eine **Whitelist**, keine RFC-5322-Grammatik. Der
Empfänger geht in den `To:`-Kopf einer echten Mail; ein `\r`/`\n` darin ist
eine Kopfzeilen-Injektion, ein Komma macht aus einem Empfänger still zwei —
also einen zweiten, ungenannten Empfänger einer freigegebenen Nachricht. Aus
demselben Grund wird der Betreff (er stammt aus einem Sprachmodell) vor dem
Setzen von Umbrüchen und Steuerzeichen befreit.

**TLS entscheidet der Port**, und einen blanken Ausgang gibt es nicht: 465 →
implizites TLS (`SMTP_SSL`), alles andere → `STARTTLS`, jeweils mit
`ssl.create_default_context()` (Zertifikats- und Hostnamen-Prüfung). Der
konfigurierte Anbieter (PrivateEmail) spricht 465; der Stufe-9-Plan hatte
nur 587/STARTTLS vorgesehen — gebaut sind beide.

**Keine Anhänge, und deshalb auch kein stiller Versand ohne sie.** Diese
Fassung schickt `text/plain`. Trägt ein Entwurf ein `media_ref`, wird er
ausdrücklich `failed` gebucht statt ohne die Unterlage zugestellt. Der Plan
sah vor, `media_ref` bei E-Mail „wie bisher als Merkposten zu ignorieren" —
das galt, solange E-Mail ein reiner Handversand-Kanal war. Seit dieser Stufe
geht die Mail automatisch raus, und dann ist Ignorieren genau der Fehler,
den der WhatsApp-Weg ausdrücklich nicht macht: *freigegeben wurde eine
Nachricht MIT Unterlage.* `entwurf_erstellen` warnt bereits beim Erstellen.

**Gemessener Fallstrick (Testbefund):** ohne ausdrückliches
`cte="quoted-printable"` wählt `EmailMessage.set_content` für kurze Texte
mit Umlauten die Transfer-Kodierung `8bit` (`policy.default` hat
`cte_type='8bit'`). Die Verbindung handelt aber kein 8BITMIME aus; `smtplib`
serialisiert den Rumpf dann mit ASCII-Ersatzzeichen, und beim Empfänger
steht „Gr??e" statt „Grüße". Quoted-Printable ist überall 7-bit-sicher.

### Termine: `termin_bestaetigen`, ICS und der optionale Kalender

Das Werkzeug **hält fest**, worauf sich zwei Menschen mündlich geeinigt
haben. Es lädt niemanden ein, fragt keinen Kalender nach freien Zeiten und
versendet nichts: es schreibt eine ICS-Datei nach `/reports`, legt — falls
konfiguriert — denselben Termin per CalDAV in den Kalender des Betreibers,
erzeugt eine Wiedervorlage „Terminerinnerung" am Vortag und gibt einen
fertigen Bestätigungstext zurück. Ob daraus eine Nachricht wird, entscheidet
der Betreiber über `entwurf_erstellen` und die Freigabe — **das Gate bleibt
unberührt, es entsteht kein zweiter Egress-Pfad zum Kunden.**

Die Erinnerung erinnert den **Betreiber** (Digest), nicht den Kunden. Eine
automatische Kundenerinnerung wäre genau der Weg am Gate vorbei, den es hier
nicht gibt.

ICS-Erzeugung und CalDAV liegen in `sales-mcp/kalender.py` — ein Modul ohne
Datenbank und ohne Rückimport, wie `recherche.py`. Der ICS-Text ist damit
ohne DB testbar, und der einzige neue ausgehende Pfad dieser Stufe steht an
einer Stelle, an der man ihn ansehen kann. Gegen die Norm gebaut und per
Textzusicherungen geprüft (ein Kalenderprogramm gibt es im Container nicht):
CRLF-Zeilenenden, Faltung auf 75 **Oktette** (ein „ü" sind zwei Bytes, und
Umlaute in Kundennamen sind der Normalfall), maskierte TEXT-Werte nach
§3.3.11, und ein eingebetteter **VTIMEZONE**-Block zur `TZID`-Referenz —
ohne ihn lehnen Outlook-Varianten die Referenz ab. Der Block steht fest im
Modul statt aus `zoneinfo` abgeleitet: die Datei soll beim Empfänger
dasselbe bedeuten wie bei uns, unabhängig von der tzdata-Fassung eines
Containers.

Die `DESCRIPTION` ist bewusst nichtssagend, und der Grund ist nicht Stil:
die Datei kann beim Kunden landen. Bedarfsangaben oder Notizen hätten dort
nichts verloren.

Die Datei entsteht in `/reports`, nicht in `/media`. `media/` bleibt für
alle Container `:ro` — was versendet werden kann, legt ausschließlich ein
Mensch ab. Wer eine Einladung mitschicken will, kopiert sie von Hand nach
`media\`; dafür steht `.ics` seit dieser Stufe in der Anhang-Whitelist
(`send-document`, `text/calendar`).

**CalDAV ist ein neuer ausgehender HTTP-Pfad** — und ausdrücklich einer ohne
Fremddatenbezug: Ziel ist ausschließlich die konfigurierte `CALDAV_URL` aus
der `.env`, nie eine Adresse aus Lead- oder Kundendaten. Ohne die drei
`CALDAV_*`-Werte ist der Weg inert (nur die Datei entsteht). `PUT` mit
`If-None-Match: *` heißt „nur anlegen, nie überschreiben": unter derselben
UID (eine uuid4) läge sonst ein fremder Termin, und den still zu ersetzen
wäre Datenverlust im Kalender eines Menschen. Ein Tippfehler in der URL kann
kein `file:`-PUT werden (Schema-Whitelist), Zugangsdaten reisen im
Authorization-Header statt in der URL, und jeder Fehlertext läuft durch
denselben Geheimnisfilter wie beim SMTP-Weg.

**Die WAF-Kante (gemessen 2026-08-19).** `dav.privateemail.com` steht hinter
einer Web Application Firewall, die Anfragen mit der **Vorgabe-Kennung von
urllib** pauschal mit HTTP 403 beantwortet — unabhängig von den
Zugangsdaten. Ein früherer Messdurchgang las dieses 403 als „das
App-Passwort deckt DAV nicht ab"; falsch — es deckt DAV, und es ist dasselbe
Passwort wie für SMTP.

Siebenmal dieselbe PROPFIND-Anfrage, nur der `User-Agent` verschieden:
`Python-urllib/3.12` (bzw. gar kein Header) → **403**; `python-requests`,
`curl/8.5.0`, `sales-claw/1.0 (CalDAV)`, ein Mozilla-Präfix und sogar das
einzelne Zeichen `X` → **207**. Gesperrt ist also genau diese eine Kennung,
nicht „Nicht-Browser".

Der `User-Agent` in `kalender.py` ist damit **Funktion, nicht Kosmetik**:
fällt er weg, ist der Kalenderweg tot, und der Fehlertext deutet auf ein
Zugangsproblem, das es nicht gibt. Ein Test hält ihn fest. Weil jede eigene
Kennung genügt, steht dort die **sprechende Kennung des Hauses** in
derselben Form wie `FIRMA_USER_AGENT` — und ausdrücklich nicht die eines
fremden Kalenderprogramms: eine fremde Produktkennung vorzutäuschen hätte
hier keinen Gegenwert, und wer im Serverlog nachsieht, wer da schreibt, soll
es beantwortet bekommen.
