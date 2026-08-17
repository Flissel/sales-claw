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

### Secrets

Wie in Spec §7 festgelegt: `config/openclaw.json` enthält keine Schlüssel.
`OPENAI_API_KEY` kommt über `.env` (aktuell absichtlich leer — ein eigener
Schlüssel für `sales-claw` wird erst ab Task 5 benötigt und vom Betreiber separat
angelegt). Der Gateway-Token entsteht im Container und liegt ausschließlich im
Volume `sales-claw-state`, nie im Repository.

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
