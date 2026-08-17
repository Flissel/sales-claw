# sales-openclaw — Stufe 1: Fundament

**Datum:** 2026-08-17
**Status:** Entwurf zur Freigabe
**Umfang:** Stufe 1 von 5 (siehe *Einordnung*)

## 1. Kontext

Für eine Vertriebsassistenz im Finanzvertrieb (MH Consulting, Regensburg) soll ein
Arbeitswerkzeug entstehen, das über WhatsApp mit Kunden kommuniziert, eine
Wissensdatenbank über Kontakte aufbaut, eine Bedarfsanalyse führt, Dokumente und
Verträge verwaltet und der Assistentin eine Zusammenfassung ihrer offenen Aktionen
liefert.

Kanal und Agentenlaufzeit stellt **OpenClaw**. Die Betriebs-Infrastruktur wird aus
`Flissel/hotel-feltzinger` übernommen — einem produktiv gehärteten Sync-Dienst mit
Container-, Reverse-Proxy-, fail2ban-, systemd- und Provisionierungs-Setup sowie
einer vollständigen Betriebsdokumentation.

### Einordnung in das Gesamtvorhaben

| Stufe | Inhalt | Status |
|---|---|---|
| **1 — Fundament** | OpenClaw containerisiert, Hotel-Infra drumherum | **dieses Dokument** |
| 2 — Sales-Core | Datenmodell + MCP-Werkzeuge (Kontakt, Profil, Präferenzen, Aktivitäten) | offen |
| 3 — Bedarfsanalyse | Geführter Fragenkatalog über WhatsApp, Sende-Kill-Switch | offen |
| 4 — Dokumente & Verträge | Ablage, Auslesen, Retrieval für akkurate Antworten | offen |
| 5 — Digest | Benachrichtigung und Zusammenfassung offener Aktionen | offen |

## 2. Ziel dieser Stufe

Ein zweiter, vollständig von der bestehenden Installation getrennter
OpenClaw-Container namens **`sales-openclaw`**, der zunächst lokal auf Docker Desktop
läuft und an der WhatsApp-Nummer des Betreibers hängt (+49 160 344 9761).

Alles, was den Container ausmacht — Image-Version, Zustand, Secrets, Netzwerk,
Konfiguration — liegt in Dateien im Repository, nicht in der Maschine. Der spätere
Umzug auf die Proxmox-VM (192.168.178.65) ist dadurch ein Kopieren des Zustands plus
`docker compose up`, kein Neuaufbau.

### Nicht Gegenstand dieser Stufe

- Keine Fachlogik, kein Datenmodell, keine MCP-Werkzeuge
- Keine Bedarfsanalyse, kein Fragenkatalog
- Keine automatischen Antworten an Dritte — ausschließlich Selbst-Chat
- Kein Umzug auf die Proxmox-VM (nur dessen Vorbereitung)
- Keine Übernahme der bestehenden MCP-Server (`secondbrain`, `brain-dispatch`,
  `rowboat-ui`) — sie zeigen auf Windows-Pfade und gehören in Stufe 2

## 3. Ausgangslage (verifiziert am 2026-08-17)

| Fakt | Wert | Quelle |
|---|---|---|
| Lokale OpenClaw-Installation | 2026.5.18 (npm, global) | `openclaw --version` |
| Zustandsverzeichnis | `C:\Users\User\.openclaw` | Dateisystem |
| Gateway-Port lokal | 18793, `bind: loopback`, Token-Auth | `openclaw.json` |
| WhatsApp | gekoppelt, `credentials/whatsapp` vorhanden | Dateisystem |
| WhatsApp-Policy | `dmPolicy: allowlist`, `selfChatMode: true`, `allowFrom: [+491603449761]`, `groupPolicy: disabled` | `openclaw.json` |
| Aktive Plugins | whatsapp, supermemory, discord, telegram, voice-call, llm-task, openai, anthropic, browser | `openclaw.json` |
| Speicher-Slot | `openclaw-supermemory`; zusätzlich `memory/main.sqlite` | `openclaw.json` |
| Primärmodell | `openai/gpt-5.5` | `openclaw.json` |
| Docker | 29.5.3, 23 Container laufen | `docker version` / `docker ps` |
| Volume-Altlast | `openclaw-festival-state` (Rückweg vom VM-Umzug 2026-08-04) | `docker volume ls` |

### Container-Image (verifiziert gegen die Registry)

| Fakt | Wert |
|---|---|
| Registry | `ghcr.io/openclaw/openclaw` (Spiegel: `openclaw/openclaw` auf Docker Hub) |
| `latest` entspricht | `2026.7.1-1`, gebaut 2026-08-04T00:45:59Z |
| Basis-Image | `node:24-bookworm-slim`, Node 24.16.0 |
| Varianten | `-slim`, `-browser`; Versionstags wie `2026.7.1`, `2026.7.1-slim` |
| Zustandspfade im Container | `/home/node/.openclaw`, `/home/node/.config/openclaw` |
| Pairing-Befehl | `docker compose run --rm openclaw-cli channels login` |

**Wichtig:** Der Container läuft mit **2026.7.1**, die lokale Installation mit
**2026.5.18**. Diese Stufe ist damit nicht nur eine Containerisierung, sondern
gleichzeitig ein Versionssprung über zwei Minor-Versionen. Die Abnahmekriterien
tragen dem Rechnung (§9, Kriterium 4).

## 4. Erfahrungen, die in dieses Design eingeflossen sind

Aus dem maschinenweiten Koordinations-Board
(`secondbrain/00_Meta/002_Koordination_Live.md`, Einträge vom 2026-08-04) und aus dem
Incident-Bericht des Hotel-Repos (`docs/14_INCIDENT_2026-05-12.md`):

1. **Die WhatsApp-Kopplung ist umziehbar.** Sie liegt in `credentials/whatsapp`,
   außerhalb des Plugin-Verzeichnisses, und hat den Umzug von Docker Desktop auf die
   Proxmox-VM ohne neuen QR-Scan überlebt.
2. **Der Umzug brach die Kopplung dennoch zunächst**, weil die Installationsspur des
   WhatsApp-Plugins noch auf den alten Pfad `/home/node/...` zeigte — Fehlerbild
   `openKeyedStore is only available for trusted plugins`. Behoben durch
   Neuinstallation des Plugins mit `npm_config_cache=/tmp/.npm`.
3. **`plugins.allow` reduzierte das Laden von 11 auf 2 Plugins.** Für einen Dienst,
   der später Kundendaten verarbeitet, ist das Angriffsfläche, nicht Performance.
4. **Die Agenten-Sandbox schützte nicht**, obwohl `runtime: sandboxed` gemeldet wurde:
   Der Agent konnte `openclaw.json` lesen und sah den `OPENAI_API_KEY`. Die Sandbox
   steht auf der VM deshalb auf `mode: off`. **Konsequenz für dieses Design: Secrets
   dürfen nicht in der Konfigurationsdatei stehen.**
5. **Kill-Switches sind Pflicht für Systeme, die nach außen schreiben.** Im Hotel-Repo
   gingen 793 ungewollte Mails raus, weil dieser Schalter fehlte. Für Stufe 1 ist das
   noch nicht relevant (keine Antworten an Dritte), das Muster wird aber in der
   Konfiguration vorbereitet.

## 5. Architektur

Stufe 1 hat genau eine bewegliche Komponente. Der Datenfluss ist entsprechend kurz:

```text
WhatsApp (Baileys, verknüpftes Gerät)
        │
        ▼
┌───────────────────────────────────────────────┐
│ Container  sales-openclaw                     │
│ ghcr.io/openclaw/openclaw:2026.7.1-slim       │
│                                               │
│   Gateway  ──►  Agent (openai/gpt-5.5)        │
│      │                                        │
│      ├── Volume  sales-openclaw-state         │
│      │     → /home/node/.openclaw             │
│      │       (Config, credentials/, memory/)  │
│      └── Volume  sales-openclaw-keys          │
│            → /home/node/.config/openclaw      │
│              (Verschlüsselungsschlüssel)      │
└───────────────────────────────────────────────┘
        │
        ▼  nur 127.0.0.1:<port>
   Host (Docker Desktop)
```

Kein eigener Dienst, keine Datenbank, kein Reverse-Proxy im lokalen Betrieb. Der
Reverse-Proxy und die Härtung werden mitgeliefert, aber erst beim Umzug auf die VM
aktiv (§10).

### Warum zwei Volumes

`/home/node/.openclaw` enthält Konfiguration, Agenten, `credentials/` und `memory/`.
`/home/node/.config/openclaw` enthält die Verschlüsselungsschlüssel. Wer nur das
erste sichert, hat beim Restore verschlüsselte Daten ohne Schlüssel. Beide gehören
zusammen gesichert und zusammen zurückgespielt.

## 6. Repository-Layout

Neues, eigenständiges Repository `sales-openclaw` (zunächst lokal, ohne Remote).
Die Infrastrukturdateien werden aus dem Hotel-Repo übernommen und angepasst; der
Hotel-Clone bleibt unter `../hotel-feltzinger` als Referenz für Stufe 2 liegen, wo
sein TypeScript-Gerüst (`lib/env`, `logger`, `retry`, `health`, `idempotency`,
Fastify-Server) tatsächlich gebraucht wird.

```text
sales-openclaw/
├── docker-compose.yml              # Dienst `sales-openclaw` (Volumes, Netz, Healthcheck,
│                                   # Logging) plus Einweg-Dienst `openclaw-cli` für
│                                   # `docker compose run --rm openclaw-cli …`
├── docker-compose.proxmox.yml      # Override für den VM-Betrieb
├── .env.example                    # Vorlage; echte .env ist gitignoriert
├── .gitignore                      # aus dem Hotel-Repo
├── config/
│   └── openclaw.json               # Basis-Konfiguration, ohne Secrets
├── deploy/                         # erst für die VM relevant
│   ├── nginx/sales-openclaw.conf
│   ├── nginx/limits.conf
│   ├── fail2ban/sales-openclaw.local
│   ├── fail2ban/sales-openclaw-filter.conf
│   ├── systemd/sales-openclaw.service
│   └── provision.sh
├── scripts/
│   ├── backup-state.ps1  /  backup-state.sh
│   ├── restore-state.ps1 /  restore-state.sh
│   ├── migrate-credentials.ps1     # einmalig: lokale Kopplung → Container
│   └── smoke-test.ps1              # Abnahme nach §9
└── docs/
    ├── 01_OVERVIEW.md
    ├── 02_ARCHITECTURE.md
    ├── 03_RUNBOOK.md
    ├── 04_BACKUP_RESTORE.md
    ├── 05_DISASTER_RECOVERY.md
    ├── 06_SECURITY.md
    ├── 07_PROXMOX_MIGRATION.md
    └── superpowers/specs/…
```

## 7. Konfigurationsentscheidungen

| Entscheidung | Wert | Begründung |
|---|---|---|
| Image | `ghcr.io/openclaw/openclaw:2026.7.1-slim` | Gepinnt statt `latest`. Ein stiller Versionssprung beim Neustart ist genau das, was eine WhatsApp-Kopplung zerlegt. Das Hotel-Repo pinnt aus demselben Grund `tsx@4.19.0` |
| Variante | `-slim` | `browser`-Plugin bleibt aus; kein Chromium im Image |
| Container-Name | `sales-openclaw` | Vom Betreiber vorgegeben |
| Gateway-Port | **18894**, ausdrücklich nicht 18793 | 18793 ist von der bestehenden lokalen Installation belegt. Der Doku-Wert (18789) widerspricht ihr ohnehin — welcher Port im Container tatsächlich lauscht, wird bei der Umsetzung am laufenden Container verifiziert und der Wert hier gegebenenfalls korrigiert |
| Port-Veröffentlichung | `127.0.0.1:18894:18894` | Muster aus dem Hotel-Repo. Der Gateway hält WhatsApp-Session und API-Schlüssel und darf nie direkt aus dem Netz erreichbar sein |
| Neustart | `restart: unless-stopped` | Wie bei `openclaw-festival` |
| Plugins | `plugins.allow: ["whatsapp"]` | Minimale Ladefläche; discord, telegram, voice-call, browser bleiben aus |
| Speicher | `memory-core` aktiv (`memory/main.sqlite`), `openclaw-supermemory` **nicht** geladen | Supermemory ist ein externer Dienst; Kundendaten dorthin zu schicken ist eine Entscheidung für Stufe 2, keine Nebenwirkung von Stufe 1. Abweichung zur bestehenden lokalen Konfiguration, wo der Speicher-Slot auf supermemory zeigt und `memory-core` abgeschaltet ist |
| Logging | `json-file`, `max-size=10m`, `max-file=3` | Auf `C:` war der Platz bereits zweimal knapp |
| Healthcheck | HTTP-Prüfung gegen den Gateway-Port | Voraussetzung für `depends_on: service_healthy` später |
| Zeitzone | `TZ=Europe/Berlin` | Termin- und Digest-Logik in späteren Stufen hängt daran |

### Secrets

Die Konfigurationsdatei `config/openclaw.json` im Repository enthält **keine
Schlüssel**. Alle Geheimnisse — `OPENAI_API_KEY`, Gateway-Token, spätere
Dienst-Schlüssel — kommen über `.env` in die Container-Umgebung.

Begründung ist nicht theoretisch: Auf der Proxmox-VM konnte der Agent seine eigene
Konfigurationsdatei lesen und den `OPENAI_API_KEY` sehen, obwohl die Sandbox als aktiv
gemeldet wurde. Was in der Konfiguration steht, hat der Agent. Das Hotel-Repo hält
Secrets deshalb in `/etc/<dienst>/env` mit `chmod 750` und injiziert sie per
`EnvironmentFile` — dasselbe Muster gilt hier, lokal über `.env` mit restriktiven
Rechten, auf der VM über die Env-Datei.

`.env` ist gitignoriert. Im Repository liegt nur `.env.example` mit Platzhaltern.

## 8. WhatsApp-Kopplung: Übernahme statt Neu-Pairing

Entscheidung des Betreibers: die bestehenden Credentials werden kopiert, die lokale
Installation wird gestoppt. Kein zweites verknüpftes Gerät.

**Warum die lokale Instanz zwingend gestoppt werden muss:** Zwei Baileys-Sitzungen,
die gleichzeitig mit denselben Credentials laufen, erzeugen Sitzungskonflikte bis hin
zum Logout des verknüpften Geräts. Das ist kein theoretisches Risiko — die Kopplung
wäre dann weg und müsste per QR neu hergestellt werden.

Ablauf (`scripts/migrate-credentials.ps1`):

1. **Sicherung zuerst.** `C:\Users\User\.openclaw\credentials\` vollständig nach
   `credentials-sicherung-<zeitstempel>` kopieren. Auf der VM wurde genau so
   verfahren; das ist der Rückweg.
2. Lokalen OpenClaw-Dienst stoppen (Daemon/Gateway), Stillstand verifizieren.
3. Volume `sales-openclaw-state` anlegen und `credentials/whatsapp` hineinkopieren.
4. Container starten, Kopplung prüfen.
5. Rückweg dokumentiert: Sicherung zurückspielen, lokalen Dienst wieder starten.

**Bekanntes Fehlerbild aus dem Board:** Zeigt die Installationsspur des Plugins noch
auf einen alten Pfad, erscheint `openKeyedStore is only available for trusted
plugins`. Gegenmittel: Plugin im Container mit `npm_config_cache=/tmp/.npm` neu
installieren. Da hier ein frischer Container mit frischer Plugin-Installation
entsteht und nur `credentials/whatsapp` übernommen wird, sollte der Fall nicht
eintreten — er steht trotzdem im Runbook, weil die Diagnose sonst Stunden kostet.

## 9. Abnahmekriterien

Stufe 1 gilt als erledigt, wenn alle sechs Punkte nachgewiesen sind — nachgewiesen
heißt: Befehl ausgeführt, Ausgabe gesehen, nicht „sollte funktionieren".

1. **Start.** `docker compose up -d` bringt `sales-openclaw` hoch, Healthcheck meldet
   `healthy`.
2. **Kopplung.** WhatsApp ist verbunden; im Selbst-Chat geht eine Nachricht rein und
   eine Antwort raus.
3. **Neustart.** `docker compose down && docker compose up -d` — die Kopplung
   überlebt, kein neuer QR-Code.
4. **Versionssprung.** Die aus 2026.5.18 übernommenen Credentials funktionieren im
   Container mit 2026.7.1. Falls nicht: Fehlerbild dokumentieren, Rückweg gehen,
   Pin auf eine nähere Version prüfen.
5. **Restore.** Backup ziehen, beide Volumes löschen, Restore einspielen — die
   Kopplung überlebt. *Dies ist das wichtigste Kriterium: der Restore-Vorgang **ist**
   die Migrationsprobe. Ist er grün, ist der Umzug auf die VM risikoarm.*
6. **Keine Kollateralschäden.** `openclaw-festival` und die 23 laufenden Container
   sind unberührt; die lokale OpenClaw-Installation ist per dokumentiertem Rückweg
   wiederherstellbar.

## 10. Vorbereitung des Proxmox-Umzugs

Wird in dieser Stufe **geschrieben, aber nicht ausgeführt**. `docker-compose.proxmox.yml`
als Override plus `docs/07_PROXMOX_MIGRATION.md` mit den bekannten Stolpersteinen:

- **DooD-Pfadbedingung:** Der Docker-Daemon der VM löst Bind-Quellen in seinem eigenen
  Namensraum auf und kann `/home/node` nicht anlegen. Auf der VM liegt der Zustand
  deshalb unter `/home/debian/...`.
- **Rootless Docker** läuft für User `debian` über `/run/user/1000/docker.sock`, neben
  dem System-Daemon. Der CLI-Kontext steht bewusst auf `default` — Befehle treffen
  sonst den falschen Daemon.
- **Plugin-Neuinstallation** mit `npm_config_cache=/tmp/.npm` (siehe §8).
- **Erreichbarkeit:** `openclaw-festival` hängt an einem Cloudflare-*Quick*-Tunnel,
  dessen URL sich bei jedem Neustart ändert. Für `sales-openclaw` ist zu entscheiden,
  ob überhaupt externe Erreichbarkeit nötig ist. Falls ja, greift die Hotel-Infra
  (nginx + Certbot + fail2ban + ufw); ein Named Tunnel wäre die Alternative und
  braucht einen Cloudflare-Login.
- **Claim-Protokoll:** Vor dem Umzug ist ein Eintrag unter *In Arbeit* in
  `secondbrain/00_Meta/002_Koordination_Live.md` zu setzen und sofort zu committen.

## 11. Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| Zwei Baileys-Sitzungen gleichzeitig | Kopplung wird abgemeldet | Lokale Instanz vor dem Containerstart stoppen und Stillstand verifizieren (§8) |
| Versionssprung 2026.5.18 → 2026.7.1 | Konfigurations- oder Zustandsformat inkompatibel | Abnahmekriterium 4; Credentials-Sicherung als Rückweg |
| Zustandsverlust | WhatsApp-Kopplung weg, neuer QR nötig | Beide Volumes im Backup; Restore als Abnahmekriterium 5 getestet |
| Agent liest seine Konfiguration | Secrets kompromittiert | Keine Schlüssel in `config/openclaw.json`; alles über Umgebung (§7) |
| Plattenplatz auf `C:` | Container oder Docker-Daemon fallen aus | Log-Rotation konfiguriert; Plattenplatz vor dem Start prüfen |
| `latest` statt Pin | Stiller Versionssprung beim Neustart | Image-Tag gepinnt |

## 12. Offene Punkte und Annahmen

Diese Punkte sind bewusst nicht Teil von Stufe 1, müssen aber vor dem Produktivbetrieb
mit echten Kundendaten geklärt sein:

1. **Auftragsverarbeitung.** Sobald die KI Kundendaten aus dem Finanzvertrieb
   verarbeitet, fließen personenbezogene Finanzdaten zum Modellanbieter (derzeit
   `openai/gpt-5.5`). Das braucht einen AVV und die Zustimmung von MH Consulting.
   Diese Frage entscheidet, ob das System je produktiv laufen darf — sie ist keine
   Code-Frage und wird hier nur festgehalten.
2. **WhatsApp-Zugangsweg.** OpenClaw koppelt über Baileys, also die inoffizielle
   Web-Anbindung. Metas Nutzungsbedingungen sehen das nicht vor; die OpenClaw-Doku
   empfiehlt selbst eine Zweitnummer. Für eine Nummer, an der Kundenbeziehungen
   hängen, ist das ein reales Sperr-Risiko. Eine Cloud-API-Brücke existiert als
   Alternative. Zu entscheiden, bevor echte Kunden angebunden werden.
3. **Sabines Nummer.** Stufe 1 läuft auf der Nummer des Betreibers. Wann und wie die
   Zielnutzerin ihre eigene Nummer einbringt, ist offen.
4. **MCP-Server.** `secondbrain`, `brain-dispatch` und `rowboat-ui` zeigen auf
   Windows-Pfade und funktionieren im Container nicht. Pro Server ist zu entscheiden:
   mitcontainern, über Netzwerk erreichbar machen, oder weglassen. Gehört zu Stufe 2.
5. **Repository-Ziel.** `sales-openclaw` ist zunächst ein lokales Repository ohne
   Remote. Ein echter GitHub-Fork des Hotel-Repos ist nicht möglich, weil der Betreiber
   dessen Eigentümer ist; Alternativen wären die Organisation `vibemind-space`, der
   Zweitaccount `Vibemind-LAB` oder ein eigenständiges Repository.
6. **Gateway-Port.** Doku (18789) und lokale Konfiguration (18793) widersprechen sich.
   Bei der Umsetzung am laufenden Container zu verifizieren.
