# Sales-Claw Proxmox-Pilot – Design

**Datum:** 23.08.2026

**Status:** vom Betreiber fachlich freigegeben, technische Umsetzung noch nicht begonnen

**Zielhost:** Docker-VM `offload-vm` (`192.168.178.65`), nicht der Proxmox-Hypervisor

## 1. Ziel

Sales-Claw wird als persönlicher Pilot des Betreibers dauerhaft auf der
Proxmox-Docker-VM betrieben. Der Betreiber arbeitet dort zunächst mit seinem
bestehenden Kontext, seinen informierten Mitgliedern und seinen eigenen
Kanälen. Regeln, Leitfaden und Arbeitsabläufe werden in dieser Phase praktisch
geschärft. Erst ein späterer, ausdrücklich beauftragter Schritt erzeugt daraus
eine bereinigte Fin2Move-Instanz.

Der Pilot soll Rechner- und Docker-Neustarts überstehen. Dienste, die nur
bereits freigegebene Entwürfe zustellen, dürfen automatisch laufen. Dienste,
die ohne einzelne Betreiberfreigabe selbst neue Aktionen anstoßen können,
bleiben während der Nutzung der persönlichen WhatsApp-Nummer manuell.

## 2. Nicht-Ziele

- Keine Fin2Move-Freigabe, kein externer Benutzerzugang und keine öffentliche
  URL in diesem Cutover.
- Keine Mandantentrennung oder Übertragung persönlicher Secrets an Fin2Move.
- Keine Umstellung auf WhatsApp Business.
- Keine Datenbankmigration: Die vorhandene Supabase-Datenbank auf der
  Proxmox-Infrastruktur bleibt die Datenquelle.
- Keine parallele lokale und VM-seitige WhatsApp/OpenWA-Instanz.
- Keine Bereinigung fremder Docker-Ressourcen auf der Ziel-VM.
- Kein ungeprüftes `docker compose up -d` über alle Dienste.

## 3. Verifizierter Ausgangszustand

### Lokal

- Branch `feat/stufe-1-fundament`, gegenüber Origin einen Commit voraus.
- Der Arbeitsbaum enthält uncommittete LinkedIn- und Stack-Änderungen. Sie
  gehören zum Pilotstand und dürfen weder verworfen noch pauschal committet
  werden.
- Volumes `sales-claw-state`, `sales-claw-keys` und `openwa-data` existieren.
- `sales-ui` läuft noch lokal; die übrigen Stack-Container endeten am
  23.08.2026 mit Exit 255.
- Der jüngste manifestierte Sales-Claw-Backupstand ist vom 18.08.2026 und ist
  für den Cutover zu alt. `openwa-data` ist nicht Bestandteil des bestehenden
  Zwei-Volume-Backupskripts.
- Ein LinkedIn-Videopost ist freigegeben (`approved`) und darf laut Betreiber
  veröffentlicht werden. Der gezielte Vertragstest steht bei 33 bestandenen
  Tests gegen `sales_test`; echte LinkedIn-Aufrufe sind dabei dreifach
  blockiert.

### Ziel-VM

- SSH-Alias `offload-vm` zeigt auf `192.168.178.65`, Benutzer `debian`.
- Docker 29.6.1 und Docker Compose 5.3.1 sind vorhanden.
- `/home/debian/sales-claw` sowie projektspezifische Container und Volumes
  existieren noch nicht.
- Port 8791 ist frei.
- Tailscale ist noch nicht installiert.
- Auf `/` sind nur 3,9 GB frei. Vor Build oder Image-Transfer müssen mindestens
  10 GB frei sein. Speicherfreigabe oder Plattenerweiterung ist ein eigenes,
  explizit bestätigtes Infrastruktur-Gate; fremde Images, Volumes oder
  Container werden nicht automatisch entfernt.

## 4. Zielarchitektur

```text
Betreibergerät
  │
  ├─ Tailscale ──> offload-vm:8791 ──> sales-ui
  │
  └─ SSH ────────> /home/debian/sales-claw
                              │
                              ├─ sales-mcp / sales-inbox
                              ├─ approval-gated Dispatcher
                              ├─ OpenWA + persistentes openwa-data
                              ├─ OpenClaw + state/keys
                              └─ bestehende Supabase-DB auf 192.168.178.65
```

Die UI bleibt an Loopback und die Tailscale-IP der VM gebunden. Es gibt kein
Binding auf `0.0.0.0` und keine Router-Portfreigabe. Bis Tailscale installiert
und interaktiv durch den Betreiber verbunden wurde, ist die UI ausschließlich
per SSH-Portweiterleitung erreichbar.

Das Repo erhält ein `docker-compose.proxmox.yml`. Der Override enthält nur
VM-spezifische Unterschiede: Restart-Policies, Tailscale-Bindung und
`AUTO_START_SESSIONS=true` für OpenWA. Secrets bleiben in einer nicht
versionierten `.env` mit Modus 600.

## 5. Dienst- und Autostart-Matrix

| Dienst | Pilotstart | Begründung |
|---|---|---|
| `openwa` | `unless-stopped` | Gateway muss nach VM-/Docker-Neustart wieder verfügbar sein. |
| OpenWA-Sessions | automatisch | `AUTO_START_SESSIONS=true`; gekoppelte Sessions mit gesetzter Telefonnummer werden wieder aufgenommen. |
| `sales-mcp` | `unless-stopped` | Werkzeug- und Datenzugriff, selbst kein Versand. |
| `sales-ui` | `unless-stopped` | Bedienoberfläche, kein eigener Versandweg. |
| `sales-inbox` | `unless-stopped` | Eingang und Protokollierung müssen dauerhaft verfügbar sein. |
| `sales-dispatch` | `unless-stopped` | Zustellt nur in der DB bereits freigegebene WhatsApp-Entwürfe. |
| `sales-mail` | `unless-stopped` | Zustellt nur bereits freigegebene E-Mail-Entwürfe. |
| `sales-linkedin` | `unless-stopped` | Veröffentlicht nur freigegebene Profilbeiträge; der aktuell freigegebene Post ist genehmigt. |
| `sales-claw` | `restart: "no"` | Persönliche Nummer plus Self-Chat-Modus; nur während bewusster Pilot-Sitzungen. |
| `sales-auto` | `restart: "no"` | Erzeugt ohne Einzelklick neue freigegebene Antworten; bis WhatsApp Business manuell. |

Die Matrix ist die Sicherheitsgrenze des Piloten. Eine spätere Änderung der
letzten beiden Zeilen erfordert eine eigene Entscheidung nach Umstellung auf
WhatsApp Business.

## 6. Zustands- und Dateimigration

Vor jeder Remote-Mutation werden lokale Zustände frisch gesichert:

1. `sales-claw-state` und `sales-claw-keys` mit dem bestehenden
   `scripts/backup-state.ps1`; der Lauf muss ein vollständiges
   `MANIFEST.json` erzeugen.
2. `openwa-data` separat als Tar-Archiv mit Dateiliste, Bytezahl und SHA-256.
3. Die Archive werden lokal vollständig probeentpackt, bevor auf der VM ein
   Zielvolume angelegt oder beschrieben wird.
4. Der lokale OpenWA-Container bleibt ab Beginn des stillen Exports gestoppt.
5. Auf der VM werden exakt die drei benannten Volumes angelegt und aus den
   geprüften Archiven befüllt.
6. Nach Restore werden Dateianzahl und SHA-256 der maßgeblichen
   Konfigurationsdateien gegen die Exportwerte geprüft.

Projektdateien werden über eine Positivliste übertragen. Enthalten sind
Compose-Dateien, `config/`, `db/`, `docs/`, `sales-mcp/`, `scripts/`, `media/`
und die notwendigen Root-Konfigurationen. Der von
`docker-compose.openwa.yml` tatsächlich verwendete Buildkontext
`openwa/upstream/` wird als Quell-Snapshot mitübertragen, jedoch ohne dessen
`.git/`, `node_modules/`, Buildausgaben oder lokale Laufzeitdaten.
Ausgeschlossen sind außerdem `.superpowers/`, `graphify-out/`, `backups/`,
`credentials-sicherung-*/`, Python-Caches und sonstige Betriebsaltlasten.

## 7. Secrets

Die lokale `.env` wird nie in Git, Logs, Chat-Ausgaben oder ein allgemeines
Projektarchiv aufgenommen. Für die VM wird sie separat über den bestehenden
SSH-Kanal übertragen, sofort auf Modus 600 gesetzt und anschließend nur über
Präsenz-/Längenprüfungen validiert. Werte werden nicht ausgegeben.

`UI_TAILSCALE_IP` wird nicht von Windows übernommen. Nach Installation und
interaktivem `tailscale up` wird ausschließlich die tatsächliche IPv4-Adresse
der VM eingetragen. Bis dahin bleibt die Variable leer und die UI nur an
Loopback gebunden.

## 8. Kontrollierter Cutover

Der Cutover erfolgt in dieser Reihenfolge und stoppt beim ersten roten Gate:

1. Mindestens 10 GB freien Speicher auf der VM belegen.
2. Tailscale installieren; der Betreiber authentifiziert die VM interaktiv.
3. Frische lokale Backups und `openwa-data`-Export erstellen und vollständig
   verifizieren.
4. Lokal auch `sales-ui` stoppen; bestätigen, dass kein Projektcontainer mehr
   läuft.
5. Projektdateien, Secrets und Archive übertragen; Rechte und Prüfsummen
   kontrollieren.
6. Zielvolumes wiederherstellen, ohne andere VM-Volumes anzufassen.
7. Compose-Konfiguration ohne aufgelöste Secret-Ausgabe validieren.
8. Zuerst `openwa`, `sales-mcp`, `sales-inbox` und `sales-ui` starten.
9. Health, DB-Lesezugriff, UI über SSH/Tailscale und OpenWA-Sessionstatus
   prüfen. Es wird noch nichts gesendet.
10. Approval-gated Dispatcher einzeln starten: WhatsApp, Mail, danach
    LinkedIn. Vor jedem Start wird die jeweilige `approved`-Queue ohne
    Nachrichtentext gezählt und dem Betreiber angezeigt.
11. Der Start von `sales-linkedin` ist das Aktions-Gate für den bereits
    freigegebenen echten Post. Die vorliegende fachliche Genehmigung erlaubt
    diesen einen Post; unmittelbar danach werden Beitrags-URN, DB-Status
    `sent` und Aktivitätsbeleg geprüft.
12. `sales-claw` und `sales-auto` bleiben gestoppt. Ihre Funktion wird später
    in einer bewusst begonnenen Pilot-Sitzung geprüft.

## 9. Fehler- und Rollback-Verhalten

- Vor dem ersten Remote-Start bleibt der lokale Zustand unverändert und ist
  die Rückfallquelle.
- Scheitert Restore oder Compose-Validierung, werden keine Dienste gestartet.
- Scheitert ein Kerndienst, bleiben alle Dispatcher gestoppt.
- Scheitert ein Dispatcher vor externem Erfolg, bleibt sein DB-Fehlerzustand
  sichtbar; es gibt keinen automatischen Text-Ersatz für freigegebene Medien.
- Ist ein LinkedIn-Beitrag extern veröffentlicht, aber die DB-Buchung
  gescheitert, wird nicht erneut veröffentlicht. Der Claim bleibt fail-closed
  und der externe Beleg wird manuell mit dem Entwurf abgeglichen.
- Ein Rückfall auf Windows erfolgt nur, nachdem alle VM-Projektcontainer
  nachweislich gestoppt sind. OpenWA/WhatsApp darf niemals gleichzeitig auf
  beiden Hosts aktiv sein.

## 10. Abnahmekriterien

Der persönliche Pilot gilt als technisch bereit, wenn alle folgenden Punkte
belegt sind:

- VM-Speicher-Gate erfüllt und keine fremde Docker-Ressource verändert.
- Drei frische Volume-Archive lokal und remote durch Manifest, Dateizahl und
  SHA-256 belegt.
- Projektdateien stimmen mit dem ausgewählten lokalen Arbeitsstand überein;
  `.env` besitzt Modus 600.
- `openwa`, `sales-mcp`, `sales-ui` und `sales-inbox` sind healthy bzw.
  funktional erreichbar.
- Die WhatsApp-Session kommt durch `AUTO_START_SESSIONS=true` ohne neuen
  QR-Scan auf `ready`, oder der Cutover stoppt ohne Versand.
- UI ist über die Tailscale-IP erreichbar und über LAN-/Wildcard-Bindings
  nicht exponiert.
- DB-Lesezugriff zeigt denselben realen Datenbestand wie vor dem Cutover.
- Jeder approval-gated Dispatcher wurde separat mit Queue-Inventar gestartet.
- Der genehmigte LinkedIn-Post besitzt nach Veröffentlichung eine externe URN,
  `drafts.status='sent'` und genau einen Versand-Aktivitätsbeleg.
- `sales-claw` und `sales-auto` sind nach dem Cutover weiterhin gestoppt.
- Ein VM-/Docker-Neustart wurde getestet: automatische Dienste kehren zurück,
  OpenWA-Session wird wieder `ready`, manuelle Dienste bleiben aus.

## 11. Spätere Fin2Move-Übergabe

Die Übergabe ist ein eigenes Projekt. Sie beginnt nicht mit dem Kopieren
dieser Pilotinstanz, sondern mit einer bereinigten Ableitung:

- eigene WhatsApp-Business-Nummer und eigene Kanalzugänge,
- neue Secrets und getrennte persistente Volumes,
- definierter Fin2Move-Datenbestand und dokumentierte Einwilligungen,
- eigener Tailscale-Zugriff,
- überprüfte Marken-, Rollen- und Verbotsregeln,
- erneute Entscheidung über den Autostart von `sales-claw` und `sales-auto`.

Persönliche Secrets, private WhatsApp-Sitzungen und nicht ausdrücklich für
Fin2Move bestimmte Daten werden niemals Bestandteil dieser Ableitung.
