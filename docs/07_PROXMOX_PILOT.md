# Proxmox-Pilot: fail-closed Cutover

Dieses Runbook ist ein einmaliger, operatorgefuehrter Cutover. Es ist kein Automatisierungsskript. Jede Phase endet mit einem Stop-Gate. Ein rotes Gate, ein unerwarteter Name, eine fehlende pruefbare Ausgabe oder eine nicht explizit erteilte Betreiberfreigabe bedeutet: **hier anhalten, nichts in der naechsten Phase ausfuehren.**

Alle Inventar- und Statusausgaben zeigen ausschliesslich IDs, Status, Kanal und Anzahl. Nachrichtentexte, E-Mail-Adressen, Telefonnummern, Tokens und Secretlaengen duerfen nie ausgegeben werden.

## 1. Preflight (read-only)

Aus dem lokalen Repository ausfuehren:

```powershell
python scripts/proxmox_preflight.py --host offload-vm --min-free-gib 10 --ui-port 8791
```

Das JSON muss mindestens 10 GiB freien Speicher, genau eine Tailscale-IPv4, einen freien UI-Port sowie freie Projektpfad-, Container- und Volume-Namen bestaetigen.

**Stop-Gate:** Bei Exit-Code ungleich null, fehlender Tailscale-IPv4, weniger als 10 GiB oder einer Kollision endet der Cutover hier. Weder Transfer noch lokale Stilllegung beginnen.

## 2. Lokale Backups

Erst nach gruenem Preflight die lokalen Sicherungen erzeugen:

```powershell
$OpenwaBackup = "backups\openwa-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
scripts/backup-state.ps1
scripts/backup-openwa.ps1 -StillgelegtLassen -Ziel $OpenwaBackup
```

Beide erzeugten Manifeste lokal vollstaendig gegen Archive und SHA-256-Werte pruefen. `-StillgelegtLassen` ist bindend: OpenWA wird durch das Backup nicht wieder gestartet.

**Stop-Gate:** Bei fehlendem Backup, Manifest, Hash oder Vollstaendigkeitsnachweis endet der Cutover. Nichts wird uebertragen; eine durch `-StillgelegtLassen` gestoppte OpenWA bleibt gestoppt.

## 3. Lokale Stilllegung

UI und danach alle verbleibenden Projektcontainer geordnet stoppen. Die Soll-Namensliste lautet `openwa`, `sales-mcp`, `sales-inbox`, `sales-ui`, `sales-dispatch`, `sales-mail`, `sales-linkedin`, `sales-claw` und `sales-auto`. Mit einer reinen Namen-Abfrage (`docker ps --format '{{.Names}}'`) beweisen, dass keiner dieser Namen mehr laeuft. OpenWA in Windows danach nicht wieder starten.

**Stop-Gate:** Ein noch laufender Sollname oder ein nicht eindeutig stoppbarer Projektcontainer beendet den Cutover. Vor diesem Nachweis darf nichts zur VM uebertragen werden.

## 4. Quellpaket

Das Paket mit `scripts/package_proxmox.py` in das noch nicht vorhandene lokale Ausgabeverzeichnis erzeugen:

```powershell
$Quellpaket = "artifacts/proxmox"
if (Test-Path -LiteralPath $Quellpaket) { throw "Stop-Gate: $Quellpaket ist nicht frisch." }
python scripts/package_proxmox.py --source . --output $Quellpaket
```

Es liefert `sales-claw-proxmox-source.tar.gz` und `sales-claw-proxmox-source.MANIFEST.json`. Anschliessend Archiv gegen Manifest (Dateiname, Bytezahl, SHA-256) pruefen. Fuer diese Phase sind nur dieses Archiv und dieses Manifest uebertragbar.

**Stop-Gate:** Bei fehlendem Paar, Manifestabweichung, Hashfehler oder einem zusaetzlichen Quellartefakt endet der Cutover. Keine Secrets und keine Volumes werden uebertragen oder veraendert.

## 5. Secrets-Gate

Jetzt und erst jetzt eine **frische** Betreiberbestaetigung fuer den separaten `.env`-Transfer einholen. Ohne diese zeitnahe Bestaetigung keine SCP-Aktion ausfuehren. Nach Bestaetigung `.env` separat per SCP in den bereits geprueften VM-Projektpfad uebertragen und unmittelbar remote setzen:

```bash
chmod 600 .env
test -s .env && stat -c '%a %n' .env
```

Die Kontrolle prueft nur Existenz/Nichtleerheit und Dateimodus; keinen Inhalt, Token oder Secretlaenge.

**Stop-Gate:** Ohne frische Freigabe, bei SCP-Fehler, fehlendem `.env` oder anderem Modus als `600` endet der Cutover. Das Secret wird nicht erneut kopiert und kein Dienst wird gestartet.

## 6. Archiv-Transfer

Drei Artefaktgruppen samt ihren Manifesten einzeln uebertragen: Quellpaket, State/Keys-Backup und `openwa-data`-Backup. Das State/Keys-Backup umfasst dabei sowohl `state.tar` fuer `sales-claw-state` als auch `keys.tar` fuer `sales-claw-keys`; kein Bestandteil darf ausgelassen werden. Vor jeder Volume-Mutation remote SHA-256 gegen das jeweilige Manifest vergleichen. Transferziel ist ausschliesslich ein frisches Staging-Verzeichnis im geprueften VM-Projektpfad.

**Stop-Gate:** Ein fehlendes Paar, nicht uebereinstimmender SHA-256 oder ein unklarer Transferpfad beendet den Cutover. Es wird kein Volume angelegt oder befuellt.

## 7. Restore

Erst nach allen drei Hash-Nachweisen exakt diese Docker-Volumes anlegen: `sales-claw-state`, `sales-claw-keys`, `openwa-data`. Die verifizierten Archive jeweils nur in ihr gleichnamiges Zielvolume entpacken. Keine Globs, keine praefixbasierten Treffer und keine fremden Volumes verwenden. Namen vor und nach dem Entpacken gegen die Dreierliste abgleichen.

**Stop-Gate:** Bei einem Fehler beim Anlegen, Namenabgleich oder Befuellen keinen Dienst starten. Fremde Volumes bleiben unberuehrt.

## 8. Compose-Check

Im VM-Projektpfad immer alle drei Compose-Dateien benutzen. Die einzig zulaessige Standardbefehlsvariable lautet:

```bash
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.openwa.yml -f docker-compose.proxmox.yml"
```

Vor jedem Start nur Konfiguration validieren:

```bash
$COMPOSE config --quiet
```

**Stop-Gate:** Bei einem Config-Fehler keine Compose-Aktion ausfuehren. Nur Metadaten korrigieren; Inhalte von `.env` werden nicht angezeigt.

## 9. Core-Start

Nach gruenem Compose-Check ausschliesslich die vier Kernservices starten:

```bash
$COMPOSE up -d openwa sales-mcp sales-inbox sales-ui
```

Danach nur Statusnamen/Status pruefen, OpenWA-Health pruefen, einen Datenbank-Lesezugriff ohne Kundendaten ausfuehren und die UI ueber Tailscale pruefen. Die OpenWA-Session wird nur als Session-ID und Status geprueft.

**Stop-Gate:** Fehlender Health-Status, nicht erreichbarer DB-Lesezugriff, nicht verifizierbare OpenWA-Session oder nicht erreichbare Tailscale-UI: Kernservices stoppen und nicht zu Dispatchern wechseln.

## 10. Dispatcher-Gates

Vor jedem einzelnen Worker die Betreiberfreigabe fuer genau diesen Kanal einholen und die passende Abfrage auf eine Anzahl begrenzen:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'whatsapp';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (WhatsApp); dann und nur dann:

```bash
$COMPOSE up -d sales-dispatch
```

Danach dieselbe Reihenfolge separat fuer E-Mail:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'email';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (E-Mail); erst danach:

```bash
$COMPOSE up -d sales-mail
```

Vor LinkedIn erneut separat zaehlen:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'linkedin';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (LinkedIn); erst nach dem folgenden zusaetzlichen Gate:

```bash
$COMPOSE up -d sales-linkedin
```

**Stop-Gate:** Fehlt die kanalspezifische Freigabe, ist die Anzahl unerwartet oder wird ein anderer Dienst vorgeschlagen, den einzelnen Worker nicht starten.

## 11. LinkedIn-Aktions-Gate

Vor dem LinkedIn-Worker den bereits genehmigten Draft nur durch Draft-ID und, falls vorhanden, Medienname identifizieren; keinen Nachrichtentext und keine Kontaktinformation anzeigen. Die explizite Betreiberfreigabe wird mit dieser ID referenziert. Nach dem Worker-Start genau einen Beitrag pruefen: externe Beitrags-URN, DB-Status `sent` und genau ein Aktivitaetsbeleg, alle bezogen auf dieselbe Draft-ID.

Bei externer Veroeffentlichung ohne DB-Buchung den Worker sofort stoppen, Artefakte sichern und **kein erneuter Versand**. Die Abweichung wird manuell untersucht; kein Retry, kein neuer Workerstart und kein zweiter Beitrag sind erlaubt.

**Stop-Gate:** Bei fehlender Draft-ID/Freigabe, mehr als einem Aktivitaetsbeleg, fehlender URN oder jeder DB-Abweichung endet diese Aktion.

## 12. Autostart-Abnahme

Nach erfolgreicher Kern- und gegebenenfalls Dispatcher-Abnahme VM und Docker kontrolliert neu starten. Danach nur den erwarteten automatischen Zustand gegen die Namensliste pruefen: OpenWA, MCP, Inbox, UI und freigegebene Pilotdienste kehren gemaess Proxmox-Compose zurueck; `sales-claw und sales-auto bleiben gestoppt`.

**Stop-Gate:** Wenn die beiden zuletzt genannten Dienste laufen, sie stoppen und die Autostart-Abnahme als fehlgeschlagen markieren. Keine weitere Pilotfreigabe bis der Restart-Grund behoben und erneut nachgewiesen ist.

## 13. Rollback

Vor einem Rollback zuerst alle VM-Projektcontainer vollstaendig stoppen und deren Stillstand per Namensliste nachweisen. Erst danach darf Windows/OpenWA wieder gestartet werden. Niemals beide OpenWA-Instanzen parallel betreiben.

**Stop-Gate:** Ist irgendein VM-Projektcontainer oder VM-OpenWA noch aktiv, darf Windows/OpenWA nicht starten. Bei unklarem Zustand beide Seiten gestoppt lassen und die Ursache vor jeder Wiederaufnahme klaeren.
