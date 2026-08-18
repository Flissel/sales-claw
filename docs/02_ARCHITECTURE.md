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
