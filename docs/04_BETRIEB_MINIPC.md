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
   **LinkedIn-Versand** („post den freigegebenen LinkedIn-Beitrag") —
   `linkedin_versand_anfordern()` bestellt nur, was in der Oberfläche
   FREIGEGEBEN ist, der Wächter startet den Einmal-Versender mit exakt
   dieser Entwurfs-Kennung und liest den wahren Ausgang aus der
   `Ausgang:`-Logzeile (der Versender endet auch bei Fehlschlägen mit
   Exit 0 — gemessen). Dateinamen tragen den Typ
   (`auftrag-update-…` / `auftrag-linkedin-…`), damit die
   Ergebnis-Leser einander nie überdecken.
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
* fährt die Abnahme `deploy/smoke.sh` (acht Prüfungen, alle gemessen);
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
8. VM: `bash deploy/smoke.sh` → alle acht grün.
9. Von einer ZWEITEN Nummer eine WhatsApp schicken → muss als
   `kundenantwort` in der Datenbank und im Posteingang erscheinen.
10. Cron prüfen (`openclaw cron list`), Timer/Wächter aktivieren
    (Plan, Aufgabe 13 Schritt 11).

Der PC-Stack bleibt danach 7 Tage GESTOPPT liegen (Rückfahrkarte), dann
`docker compose down` ohne `-v` — die Volumes bleiben 30 Tage Kaltreserve.

## Bekannte Fallen (alle gemessen)

| Falle | Folge | Regel |
|---|---|---|
| Nacktes `docker compose up -d` | startet `sales-auto` → doppelte Antworten an Menschen | Dienste IMMER namentlich |
| `sales-mcp`-Neustart | trennt still die MCP-Verbindung des Gateways | danach immer `docker restart sales-claw` |
| `docker-compose.proxmox.yml` mitverwenden | setzt sales-claw auf `restart: no` → Bot nach Reboot tot | zur Laufzeit NUR die zwei Basis-Dateien |
| AGENTS.md wächst über `bootstrapMaxChars` | wird still gekürzt, Bot kennt seine Regeln nicht | smoke.sh Prüfung 8 wacht darüber |
| `grep -q` hinter Docker-Pipes bei `pipefail` | falsches ROT durch EPIPE | in Skripten grep ohne `-q` |
| Live getartes Chromium-Profil | beschädigte WhatsApp-Session | openwa vor dem Sichern stoppen |
