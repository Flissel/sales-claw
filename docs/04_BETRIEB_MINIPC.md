# 04 — Betrieb auf dem MiniPC

Stand 27.08.2026. Gilt ab dem Cutover auf die Proxmox-VM `vibemind-offload-1`
(VM 100, Benutzer `debian`, Checkout `~/sales-claw`). Bis dahin beschreibt
[03_RUNBOOK.md](03_RUNBOOK.md) den PC-Betrieb; danach bleibt es als
Nachschlagewerk für die Diagnose-Kommandos gültig.

Der vollständige Umzugsplan mit allen Aufgaben und Messungen:
[superpowers/plans/2026-08-26-proxmox-umzug-und-updates.md](superpowers/plans/2026-08-26-proxmox-umzug-und-updates.md).

## Das Grundgesetz: die Config-Grenze Git ↔ Volume

**Git besitzt:** Code, Compose-Dateien, `deploy/`, Doku, `config/workspace/`
(die Saat des Agenten-Workspace, inkl. AGENTS.md und künftiger Skills).

**Die Volumes besitzen:** `openclaw.json` (Allowlist, Kanal-Kopplung,
Cron-Jobs), die WhatsApp-Profile (openwa-data) und die Schlüssel.

Folgen:

* Ein Update spielt `config/workspace/` automatisch in den laufenden
  Workspace ein (per `docker cp`, danach Gateway-Neustart). **Ein neuer
  Agent-Skill ist damit ein normaler Git-Commit.**
* Änderungen an `config/openclaw*` (der Saat-Konfiguration) wendet das
  Update NIE automatisch an — es meldet sie nur. Sonst würde ein
  `git pull` die zur Laufzeit gesetzte Allowlist oder die Kopplung
  zerstören. Nachziehen von Hand: `openclaw config set …` im Container.
* Auf der VM wird im Checkout NIE editiert. Der Rechner des Betreibers ist
  die Werkbank, die VM ist Laufzeit. `update.sh` bricht ab, sobald
  nachgeführte Dateien verändert sind.

## Update einspielen

Drei gleichwertige Auslöser, ein Mechanismus (`deploy/update.sh`):

1. **Doppelklick** auf `scripts/update-server.ps1` (PC).
2. **Den Bot bitten** („spiel das Update ein") — der Bot bestellt per
   `update_anfordern()` eine Auftragsdatei in `auftraege/`; die
   systemd-path-Unit `sales-auftraege.path` startet den Wächter
   `deploy/auftrag-ausfuehren.sh`, der ausführt und das Ergebnis
   zurücklegt. Der Bot liest es mit `update_ergebnis()` und meldet es.
   Der Bot selbst fasst nie git oder docker an.

   Derselbe Spool trägt seit dem 27.08. eine zweite Auftragsart:
   **LinkedIn-Versand** — `linkedin_versand_anfordern()` bestellt nur,
   was FREIGEGEBEN ist, der Wächter startet den Versender mit exakt
   dieser Entwurfs-Kennung und liest den wahren Ausgang aus der
   `Ausgang:`-Logzeile (der Versender endet auch bei Fehlschlägen mit
   Exit 0 — gemessen). Dateinamen tragen den Typ
   (`auftrag-update-…` / `auftrag-linkedin-…`), damit die
   Ergebnis-Leser einander nie überdecken.

   **Seit dem 30.08. ist das der Sonderweg, nicht der Normalweg:**
   `sales-linkedin` läuft dauerhaft und nimmt freigegebene Beiträge
   selbst (höchstens einer pro Tag, nichts älter als sieben Tage
   freigegeben). Die Freigabe ist damit die Veröffentlichung — wie bei
   WhatsApp. Der Auftragsweg bleibt für den Fall, dass ein bestimmter
   Beitrag außer der Reihe raus soll; der Cron-Job „LinkedIn-Tagespost"
   wurde als überflüssig entfernt.
3. **Von Hand auf der VM:** `bash ~/sales-claw/deploy/update.sh`
   (oder `sudo systemctl start sales-update`).

Was `update.sh` tut, in dieser Reihenfolge:

* bricht ab, wenn nachgeführte Dateien lokal verändert sind;
* `git fetch` + `merge --ff-only` — nichts Neues ⇒ Ende (`aktuell`);
* setzt das Tag `vor-update` auf den alten Stand (die Rückfahrkarte);
* staffelt nach den gemessenen Regeln: `sales-mcp/`-Änderungen ⇒ Kern
  neu bauen UND Gateway neu starten (ein mcp-Neustart trennt die
  MCP-Verbindung des Gateways stillschweigend — gemessen 26.08.2026);
  `config/workspace/` ⇒ Saat einspielen + Gateway-Neustart;
  `openwa/upstream/` ⇒ openwa neu bauen;
* fährt die Abnahme `deploy/smoke.sh` (neun Prüfungen, alle gemessen);
* bei Rot: automatischer Rückbau auf `vor-update`, erneute Abnahme,
  Ergebnis `rollback` (oder `notfall`, wenn auch der Rückbau rot ist).

Ergebnis steht in `~/sales-betrieb/update-status.json`
(`eingespielt` | `aktuell` | `rollback` | `notfall` | `fehler`), Log in
`~/sales-betrieb/update-lauf.log`.

Während des Updates startet der Gateway kurz neu — der WhatsApp-Kanal ist
für ~20–60 Sekunden still und verbindet sich selbst wieder. Ein
10-Minuten-Cron-Lauf kann dabei ausfallen; der nächste holt nach.

## Rückfahrkarte (von Hand)

```bash
cd ~/sales-claw
git reset --hard vor-update
docker compose up -d --build sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw
docker restart sales-claw
bash deploy/smoke.sh
```

## Sicherung

* **Nächtlich 04:35** (`sales-sicherung.timer`): die drei Zustands-Volumes
  als tar.gz mit sha256-Manifest nach `~/sales-betrieb/sicherungen/`,
  Rotation 7. openwa wird währenddessen gestoppt (ein live getartes
  Chromium-Profil ist die am 26.08.2026 gemessene Beschädigungsklasse)
  und per trap immer wieder gestartet.
* **Wiederherstellen:** `bash deploy/wiederherstellen.sh <ordner>` —
  verweigert bei laufenden Diensten, prüft das Manifest. Der komplette
  Rundlauf (sichern → Volumes leeren → wiederherstellen → alles grün,
  Kopplungen intakt) wurde am 27.08.2026 auf dem PC gemessen.
* Eine Proxmox-Vollsicherung (vzdump) braucht ein externes Ziel — auf dem
  Wirt sind nur 25 GB frei. Offene Betreiber-Entscheidung.

## Cutover-Reihenfolge (verbindlich, aus dem Plan Aufgabe 13)

Nie zwei Standorte gleichzeitig im Kundenverkehr. Reihenfolge:

1. PC: `bash deploy/sicherung.sh` (frische Sicherung).
2. PC: `docker compose stop && docker compose -f docker-compose.openwa.yml stop`.
3. Sicherung per `scp` zur VM (`~/sales-betrieb/umzug/`).
4. VM: `bash deploy/wiederherstellen.sh ~/sales-betrieb/umzug/<stempel>`.
5. VM: openwa starten; Session-Status prüfen. `ready` = Kopplung hat den
   Wirtswechsel überlebt. `qr_ready` = Kopplungscode anfordern
   (`POST /api/sessions/<id>/pairing-code`), Betreiber tippt ihn ein.
6. VM: sales-claw starten; Log muss `Listening for WhatsApp inbound`
   zeigen. Bei `session logged out`: Control-UI, „Erneut verknüpfen", QR.
7. VM: `docker compose up -d sales-inbox sales-dispatch sales-mail sales-ui sales-mcp`.
8. VM: `bash deploy/smoke.sh` → alle neun grün.
9. Von einer ZWEITEN Nummer eine WhatsApp schicken → muss als
   `kundenantwort` in der Datenbank und im Posteingang erscheinen.
10. Cron prüfen (`openclaw cron list`), Timer/Wächter aktivieren
    (Plan, Aufgabe 13 Schritt 11).

Der PC-Stack bleibt danach 7 Tage GESTOPPT liegen (Rückfahrkarte), dann
`docker compose down` ohne `-v` — die Volumes bleiben 30 Tage Kaltreserve.

## UI-Anmeldung (E1, seit 31.08.2026)

Scharf, sobald `UI_SESSION_SECRET` in der `.env` steht — vorher verhält
sich die Oberfläche wie früher (offen fürs Tailnet). Scharf schalten und
Benutzer anlegen ist EIN Schritt:

    bash ~/sales-claw/deploy/benutzer-anlegen.sh

fragt Name, Rolle (`lesen` sieht alles und darf nichts verändern,
`freigeben` arbeitet wie gewohnt) und Passwort ab (nie in der
Prozessliste), legt beim ersten Mal das Secret an und startet `sales-ui`
neu. Derselbe Aufruf ist auch Passwort-Reset und Reaktivierung.

- Freigaben tragen dann den BENUTZERNAMEN in `approved_by` — wer freigab,
  steht im Beweis ('betreiber-ui' nur noch im Übergangszustand).
- Sitzung: signierter Cookie, 12 h; Rolle und aktiv werden bei jeder
  Anfrage frisch gelesen — `update sales.benutzer set aktiv=false where
  name='…'` wirft eine laufende Sitzung SOFORT raus (Deaktivieren geht
  bewusst nur von Hand, nie über das Skript).
- Fünf Fehlversuche sperren die Anmeldung für eine Minute (global).
- Verträge: `sales-mcp/tests/test_login.py`; smoke akzeptiert die
  Umleitung auf /login als gesund.

## Bekannte Fallen (alle gemessen)

| Falle | Folge | Regel |
|---|---|---|
| Nacktes `docker compose up -d` | startet `sales-auto` → doppelte Antworten an Menschen | Dienste IMMER namentlich |
| `sales-mcp`-Neustart | trennt still die MCP-Verbindung des Gateways | danach immer `docker restart sales-claw` |
| `docker-compose.proxmox.yml` mitverwenden | setzt sales-claw auf `restart: no` → Bot nach Reboot tot | zur Laufzeit NUR die zwei Basis-Dateien |
| Eine Bootstrap-Datei wächst über `bootstrapMaxChars` | wird still gekürzt, Bot kennt seine Regeln nicht | smoke.sh Prüfung 8 wacht darüber (alle Dateien, nicht nur AGENTS.md) |
| Die Bootstrap-Dateien wachsen in **Summe** über `bootstrapTotalMaxChars` | dasselbe, aber ohne dass jemand AGENTS.md anfasst — `memory/` wächst täglich | smoke.sh Prüfung 9 wacht darüber |
| `grep -q` hinter Docker-Pipes bei `pipefail` | falsches ROT durch EPIPE | in Skripten grep ohne `-q` |
| Live getartes Chromium-Profil | beschädigte WhatsApp-Session | openwa vor dem Sichern stoppen |

<!-- Probe-Update fuer den Live-Beweis des Ausrollwegs (30.08.2026, Aufgabe 12). -->

<!-- Zweiter Probelauf des Ausrollwegs (30.08.2026). -->

## OpenWA-Patches (seit 02.09.2026)

`openwa/upstream/` ist ein gitignoriertes Nested-Repo (Pin `97cba60`).
Unsere Änderungen daran liegen versioniert unter `deploy/openwa-patches/`
(README dort) und werden mit `bash deploy/openwa-patch-anwenden.sh`
eingespielt — idempotent, mit `--check` vor jedem Apply. Bis dahin lag
der Dockerfile-Patch nur als unversionierte Arbeitskopie im
Unterordner; ein `git checkout` dort hätte ihn still verloren.

Patch 0002 macht das Dashboard im WhatsApp-Tab einbettbar
(`DASHBOARD_FRAME_ANCESTORS` in der `.env`, eigene Serve-Adresse
`https://<vm>.ts.net:8443` via `tailscale serve --https=8443
http://127.0.0.1:12785`). Wirkt erst nach Neubau des openwa-Images;
ein openwa-Neustart kann die WhatsApp-Session kosten (01.09.2026
gemessen) — also erst fertig bauen, dann einmal `up -d openwa`, dann
Session prüfen und notfalls per Pairing-Code neu koppeln.

## OpenWA-Ratenbegrenzer hinter dem Proxy (seit 02.09.2026)

OpenWA begrenzt Anfragen pro Client-IP in drei Fenstern (short/medium/
long). Hinter `tailscale serve` kommt aber jeder Browser als das
Docker-Bridge-Gateway an — gemessen 02.09.2026: Dashboard, sales-ui und
Betriebsskripte teilten sich EIN 10/s-Fenster, das Dashboard blieb nach
dem Login im 429 (`ThrottlerException: Too Many Requests`) hängen.

Seitdem setzt `docker-compose.openwa.yml` `TRUSTED_PROXIES=172.16.0.0/12`
(openwa liest das X-Forwarded-For des Proxys und zählt pro Browser) und
weitet die Fenster auf 40/s, 400/min, 4000/h. Alle vier Werte sind über
die `.env` überschreibbar. Prüfen: der Warnhinweis
`X-Forwarded-For is present but TRUSTED_PROXIES is empty` darf im
openwa-Log nicht mehr auftauchen, und eine Antwort auf einer gezählten
Route über die Serve-Adresse (z. B. `/api/sessions`, nicht `/api/health`,
das ausgenommen ist) trägt `X-RateLimit-Limit-short: 40` — gemessen
02.09.2026, 25 gleichzeitige Anfragen ohne einen 429.

## Marketing-Seite auf der VM (seit 25.09.2026)

Das Marketing-Pult in sales-ui (`/marketing`, Spec `docs/superpowers/specs/
2026-09-29-marketing-pult-design.md`) spricht mit einer eigenständigen Instanz
der Marketing-API auf `vibemind-offload-1` — ein schlanker `vibemind-os`-
Checkout (nur `spaces/marketing` per `sparse-checkout`), eigener systemd-Dienst
`marketing-api` (`deploy/systemd/marketing-api.service`), erreichbar nur im
Tailnet über `tailscale serve --https=8446`. Die Instanz läuft seit 25.09.2026
(Einrichtung unten). Der frühere Schalter Sales ↔ Marketing und seine Variable
`MARKETING_URL` sind entfallen: sales-ui zeigt die Marketing-Seiten selbst und
liest alles über den Pult-Router `/api/pult/*`.

**`:8446` bleibt nötig:** gemessen 29.09.2026 erreicht der Container
`sales-ui` die Marketing-API NUR über
`https://vibemind-offload-1.tail6c7d61.ts.net:8446` (`127.0.0.1` und
`172.17.0.1` → Connection refused). Genau diese Adresse ist
`MARKETING_PULT_URL`.

**Pult-Schlüssel:** jede `/api/pult/*`-Route verlangt den Header
`X-Pult-Key` (ohne gesetzten Schlüssel antwortet der Router 503, mit falschem
401; der Dienstschlüssel `X-API-Key` gilt dort nicht). Derselbe Wert steht an
drei Stellen, nie im Befehl selbst (Datei-Übertragung wie bei Schritt 4):

- `MARKETING_PULT_URL` + `MARKETING_PULT_KEY` in `~/sales-claw/.env` — der
  Haupt-`.env` des Basis-Ladens, nie in ein Zweit-Laden-Template (Ivans Laden
  bekommt kein Pult);
- `MARKETING_PULT_KEY` in `/home/debian/marketing-api.env` (Rechte 600) für
  die VM-Instanz;
- `MARKETING_PULT_KEY` in der PC-`.env` für die PC-Instanz (Agenten, Tests).

**Voraussetzungen auf der VM (vorher prüfen):**

```bash
ssh offload-vm 'dpkg -s python3-venv >/dev/null 2>&1 || sudo apt-get install -y python3-venv'
ssh offload-vm 'id -nG | tr " " "\n" | grep -qx docker && echo docker-ok'   # Modus B: docker exec als debian
ssh offload-vm 'sudo -n true && echo sudo-ok'   # marketing-aktualisieren.sh ruft sudo -n systemctl
```

Fehlt `docker-ok`: `ssh offload-vm 'sudo usermod -aG docker debian'`, danach
neu anmelden — ohne Gruppe scheitert jede Abfrage der Marketing-API.

**Einrichtung (einmalig, in genau dieser Reihenfolge — Plan Aufgabe 4):**

1. **`update.sh` zuerst, `MARKETING_PULT_URL` noch leer.** Bringt Unit-Datei
   und Skripte nach `~/sales-claw`; das Pult meldet bis Schritt 8
   „Marketing nicht verbunden“.

   ```bash
   ssh offload-vm 'bash ~/sales-claw/deploy/update.sh'
   ```

   Hinweis: Dieser erste Lauf ist noch das **alte** `update.sh` (es zieht
   sich selbst erst nach), der Marketing-Haken läuft also erst **ab dem
   zweiten** `update.sh`-Lauf mit. Und bewusst: Rückfahrkarte und die frühen
   `exit 1`-Pfade von `update.sh` überspringen die Marketing-Aktualisierung.

2. **Leseschlüssel** für `vibemind-os` erzeugen (Anhängen an `~/.ssh/config`
   idempotent), öffentlichen Teil holen und als **schreibgeschützten**
   Deploy-Key an `Flissel/vibemind-os` hängen:

   ```bash
   ssh offload-vm 'test -f ~/.ssh/marketing-os-deploy || ssh-keygen -t ed25519 -N "" -f ~/.ssh/marketing-os-deploy -C offload-vm-marketing-os'
   ssh offload-vm 'grep -q "Host github.com-marketing" ~/.ssh/config 2>/dev/null || cat >> ~/.ssh/config <<EOF

   Host github.com-marketing
     HostName github.com
     User git
     IdentityFile ~/.ssh/marketing-os-deploy
     IdentitiesOnly yes
   EOF'
   ssh offload-vm 'cat ~/.ssh/marketing-os-deploy.pub'
   ```

   Den ausgegebenen öffentlichen Teil anhängen: `gh repo deploy-key add
   <datei> --repo Flissel/vibemind-os --title offload-vm-marketing-os` (ohne
   `--allow-write`; Konto Flissel — Zwei-Konten-Falle beachten: `gh` hat zwei
   Konten, das falsche liefert „Repository not found").

3. **Schlanker Checkout + venv:**

   ```bash
   ssh offload-vm 'git clone --filter=blob:none --no-checkout --branch master git@github.com-marketing:Flissel/vibemind-os.git ~/marketing-os && cd ~/marketing-os && git sparse-checkout set spaces/marketing && git checkout master && python3 -m venv .venv && .venv/bin/pip install -q fastapi uvicorn'
   ssh offload-vm 'cd ~/marketing-os && .venv/bin/python -c "import spaces.marketing.api.server"'
   ```

   Fehlt ein Modul, genau dieses nachinstallieren und hier ergänzen.

4. **Schlüsseldatei** `/home/debian/marketing-api.env` (Rechte 600) mit
   `MARKETING_PROPOSAL_API_KEY`, `MARKETING_N8N_API_KEY`,
   `MARKETING_UNSUB_SECRET` — Werte per Datei-Übertragung aus der PC-`.env`
   (scp einer Scratchpad-Datei, danach dort löschen), nie im Befehl selbst.
   Danach `ssh offload-vm 'chmod 600 ~/marketing-api.env && stat -c %a ~/marketing-api.env'` → `600`.

5. **Dienst** (die Unit kommt aus Schritt 1):

   ```bash
   ssh offload-vm 'sudo install -m644 ~/sales-claw/deploy/systemd/marketing-api.service /etc/systemd/system/ && sudo systemd-analyze verify /etc/systemd/system/marketing-api.service && sudo systemctl daemon-reload && sudo systemctl enable --now marketing-api'
   ```

   Beweis: `ssh offload-vm 'curl -s http://127.0.0.1:5510/api/stats'`
   liefert dieselben Zahlen wie `curl -s http://127.0.0.1:5510/api/stats`
   auf dem PC (die PC-Instanz).

6. **Gate: Ivan-Netzmap-Prüfung — VOR dem Freischalten.** `tailscale debug
   netmap` bzw. die wirksame Paketregel für Ivans Knoten: erreicht er
   `vibemind-offload-1:8446`? Ist Ivans Knoten erreichbar: STOP, Schritt 7
   nicht ausführen, Betreiber fragen — Ivan darf die Marketing-Seite nicht
   über diesen Weg erreichen können.

7. **Tailnet-Freigabe:**

   ```bash
   ssh offload-vm 'sudo tailscale serve --bg --https=8446 http://127.0.0.1:5510 && tailscale serve status'
   ```

   Erwartet: `:8446 (tailnet only)`.

8. **Sales:** `MARKETING_PULT_URL=https://vibemind-offload-1.tail6c7d61.ts.net:8446`
   und `MARKETING_PULT_KEY=…` in `~/sales-claw/.env` (Haupt-`.env`), dazu
   `MARKETING_PULT_KEY` in `~/marketing-api.env` und `sudo systemctl restart
   marketing-api`; dann `sales-ui` namentlich neu erstellen:

   ```bash
   ssh offload-vm 'cd ~/sales-claw && docker compose up -d sales-ui'
   ssh offload-vm 'docker exec sales-ui printenv MARKETING_PULT_URL'              # gesetzt
   ssh offload-vm 'docker exec ivan-ui printenv MARKETING_PULT_URL || echo leer'  # leer
   ```

   Den Schlüssel selbst nie ausgeben: `docker exec sales-ui sh -c 'test -n
   "$MARKETING_PULT_KEY" && echo gesetzt'`.

9. **Echter Klick:** PC-Browser und Handy — `/marketing` zeigt die Zähler,
   eine Entwurfsseite die Vorschau im Rahmen; im Ivan-Laden kein
   Marketing-Menü.

**Bewusst kein `OPENFANG_*` auf der VM-Instanz.** Die
OpenFang-Benachrichtigung beim Anlegen von Vorschlägen läuft über die
PC-Instanz der Marketing-API — die Agenten, die Vorschläge anlegen, laufen
dort. Die Brücke ist ohnehin nicht fatal (`urlopen(..., timeout=5)` in
`try/except`, `api/server.py:2656-2675`). So wandert kein weiterer
Schlüssel auf die VM (Plan, Global Constraints, Abweichung von Spec §3.1).

**Aktualisieren:** läuft ab dem zweiten `update.sh`-Lauf nach der
Einrichtung mit (holt den Marketing-Checkout nach und startet
`marketing-api` bei Bedarf neu, nicht fatal für den Sales-Laden); von Hand:
`bash ~/sales-claw/deploy/marketing-aktualisieren.sh`. Neu gestartet wird
gegen die Standdatei `~/marketing-os/.git/marketing-api-gestartet` (zuletzt
erfolgreich gestarteter Commit): scheitern `restart`, `is-active` oder die
Gesundheitsprobe auf `/api/health`, endet das Skript mit `HINWEIS` und
Nicht-Null, und der nächste Lauf versucht den Neustart erneut.
