# Proxmox-Pilot: fail-closed Cutover

Dieses Runbook ist ein einmaliger, operatorgefuehrter Cutover. Jede Phase endet
mit einem Stop-Gate. Ein rotes Gate, eine unerwartete Ressource oder eine
fehlende ausdrueckliche Freigabe bedeutet: anhalten und keine spaetere Phase
ausfuehren.

Alle Inventar- und Statusausgaben zeigen ausschliesslich IDs, Status, Kanal und
Anzahl. Nachrichtentexte und sonstige Nachrichteninhalte, E-Mail-Adressen, Telefonnummern, Tokens und Secretlaengen duerfen nie ausgegeben werden.

## 1. Preflight (read-only)

Aus dem lokalen Repository ausfuehren und das metadata-only JSON im Prozess
halten:

```powershell
$PreflightJson = python scripts/proxmox_preflight.py --host offload-vm --min-free-gib 10 --ui-port 8791
$PreflightJson
$Preflight = $PreflightJson | ConvertFrom-Json
$VmTailscaleIp = $Preflight.tailscale_ipv4
```

Der Preflight akzeptiert nur genau eine IPv4 aus Tailscales `100.64.0.0/10`,
einen freien Port, mindestens 10 GiB und einen Zielpfad, der weder existiert
noch ein auch nur dangling Symlink ist.

**Stop-Gate:** Bei Exit-Code ungleich null oder fehlendem Feld endet der
Cutover. Weder Verzeichnis noch Transfer oder lokaler Stopp beginnen.

## 2. Lokale Backups

Frische Sicherungen erzeugen und die neu entstandenen Ordner explizit setzen:

```powershell
$OpenwaBackup = "backups\openwa-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
scripts/backup-state.ps1
scripts/backup-openwa.ps1 -StillgelegtLassen -Ziel $OpenwaBackup
$StateBackup = (Get-ChildItem -LiteralPath backups -Directory -Filter 'sales-claw-*' |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).FullName
scripts/restore-state.ps1 -Quelle $StateBackup -NurPruefen
scripts/verify-openwa-backup.ps1 -Quelle $OpenwaBackup
```

`backup-state.ps1` muss bei `stop_exit_code=137` hart abbrechen und darf dann
kein Abschlussmanifest liefern. Die beiden Pruefbefehle entpacken alle drei
Archive lokal probeweise und vergleichen Bytezahl, SHA-256 und Eintragszahl.

**Stop-Gate:** Fehlendes Manifest, harter Container-Kill, Hash-, Byte-,
Eintrags- oder Entpackfehler beendet den Cutover. OpenWA bleibt gestoppt.

## 3. Lokale Stilllegung

UI und alle restlichen Projektcontainer geordnet stoppen. Die exakte
Soll-Namensliste ist `openwa`, `sales-mcp`, `sales-inbox`, `sales-ui`,
`sales-dispatch`, `sales-mail`, `sales-linkedin`, `sales-claw` und
`sales-auto`. Mit `docker ps --format '{{.Names}}'` nur die Namen abgleichen.

**Stop-Gate:** Solange ein Sollname laeuft, beginnt weder Paketierung noch
Transfer. Windows/OpenWA wird nicht erneut gestartet.

## 4. Quellpaket

Jeder Cutover nutzt einen frischen, zeitgestempelten Ausgabeordner:

```powershell
$Quellpaket = "artifacts/proxmox-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if (Test-Path -LiteralPath $Quellpaket) { throw "Stop-Gate: Ausgabe existiert." }
$ReviewedSourceCommit = git rev-parse --verify "HEAD^{commit}"
$ReviewedOpenwaCommit = git -C openwa/upstream rev-parse --verify "HEAD^{commit}"
if ($ReviewedSourceCommit -cnotmatch '^[0-9a-f]{40}([0-9a-f]{24})?$' -or
    $ReviewedOpenwaCommit -cnotmatch '^[0-9a-f]{40}([0-9a-f]{24})?$') {
  throw "Stop-Gate: Commit-Pin ist ungueltig."
}
python scripts/package_proxmox.py `
  --source . `
  --output $Quellpaket `
  --nested-source "openwa/upstream=$ReviewedOpenwaCommit"
```

Das Paket enthaelt keine `.env`-Varianten, keine benannten Credential-JSONs,
keine Dateien mit den gesperrten Secret-Endungen, keine `reports/` und keine
Kundenmedien. Es wird
ausschliesslich aus dem geprueften, getrackten `HEAD`-Inventar des aeusseren
Repositories und dem exakten `HEAD`-Baum des separat gepinnten Git-Worktrees
`openwa/upstream` erzeugt. Dessen Manifesteintrag bindet Pfad und vollen
Commit. Nur regulaere Git-Blobs werden inventarisiert; `.git` sowie beliebige
ignorierte oder ungetrackte Arbeitskopie-Inhalte bleiben ausserhalb. Jede
dirty, untracked oder ignored Datei innerhalb eines der beiden Paketbereiche
sperrt den Lauf. Ein sauberer aeusserer Klon allein reicht deshalb nicht: Auch
das lokale OpenWA-Repository muss am gepinnten Commit vorhanden und vollstaendig
sauber sein. Der aktuelle Pilot-Checkout ist wegen des fremd geaenderten
`openwa/upstream/Dockerfile` absichtlich paketgeschlossen; hier wird kein
erfolgreicher Paketlauf behauptet.
`media/` ist kein Quellpaket-Bestandteil und braucht bei spaeterem Bedarf eine
eigene Datenfreigabe und einen getrennten Transfer. Nur
`openwa/upstream/scripts/backup.sh` und
`openwa/upstream/scripts/restore.sh` erhalten Modus `0755`; alle anderen Dateien
erhalten `0644`.

**Stop-Gate:** Fehlendes Paar, unerwarteter Zusatz, Manifestabweichung oder
ein sensibler Pfad beendet den Cutover.

## 5. Quelltransfer und Projektbaum

Zuerst auf der VM ein frisches Staging-Verzeichnis erzeugen und den
zurueckgegebenen absoluten Pfad festhalten:

```bash
REMOTE_STAGE="$(mktemp -d /home/debian/.sales-claw-staging.XXXXXX)"
test ! -L "$REMOTE_STAGE"
test "$(stat -c '%U:%G' "$REMOTE_STAGE")" = "debian:debian"
chmod 700 "$REMOTE_STAGE"
```

Der Installer wird **nicht** aus dem noch ungeprueften Archiv gelesen. Lokal
seine Arbeitskopie zuerst mechanisch an den reviewten Commit binden und den
separaten Transporthash festhalten:

```powershell
$InstallerPfad = "scripts/install_proxmox_package.py"
$ReviewedInstallerBlob = git rev-parse "HEAD:$InstallerPfad"
$WorkingInstallerBlob = git hash-object -- $InstallerPfad
if ($LASTEXITCODE -ne 0 -or $WorkingInstallerBlob -cne $ReviewedInstallerBlob) {
  throw "Stop-Gate: Installer entspricht nicht HEAD."
}
$TrustedInstallerSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPfad).Hash.ToLowerInvariant()
```

`sales-claw-proxmox-source.MANIFEST.json`,
`sales-claw-proxmox-source.tar.gz` und diese separat gepinnte
`install_proxmox_package.py` per SCP in genau das Staging-Verzeichnis
uebertragen. Den 64-stelligen `$TrustedInstallerSha256` und den exakten
`$ReviewedSourceCommit` und `$ReviewedOpenwaCommit` als Metadaten ueber den
bestehenden SSH-Kanal in `TRUSTED_INSTALLER_SHA256`,
`EXPECTED_SOURCE_COMMIT` und `EXPECTED_OPENWA_COMMIT` setzen. Den Installer
**vor jeder Python-Ausfuehrung** pruefen:

```bash
test "$TRUSTED_INSTALLER_SHA256" = "$(sha256sum "$REMOTE_STAGE/install_proxmox_package.py" | cut -d ' ' -f 1)"
```

Erst der so unabhaengig vertraute Python-3-Prueflauf darf ohne Inhaltsausgabe
Archivname, Bytezahl und SHA-256 pruefen, dann jedes Archivmitglied gegen die Dateiliste im Manifest
abgleichen, absolute/`..`-Pfade, Links, Devices und unbekannte Modi ablehnen
und beide vom Betreiber gelieferten Commit-Pins gegen das Manifest pruefen.
`openwa/upstream/Dockerfile`, `scripts/backup.sh` und `scripts/restore.sh` muessen im
manifestierten Snapshot vorhanden sein. Vor Abschluss dieser Pruefungen wird
kein archivgelieferter Code ausgefuehrt. Erst danach darf der Installer in
einen frischen Unterordner sicher entpacken. Anschliessend prueft er jede
entpackte Datei erneut nach Bytezahl und SHA-256. Erst der vollstaendig gruene Baum wird ohne Glob nach
`/home/debian/sales-claw` umbenannt; Eigentum bleibt `debian:debian`.

Der vertrauenswuerdige Installer verifiziert das gesamte im Arbeitsspeicher
gepinnte Archiv und erzeugt den Zielbaum erst nach dem vollstaendigen
Soll-Abgleich:

```bash
python3 "$REMOTE_STAGE/install_proxmox_package.py" \
  --archive "$REMOTE_STAGE/sales-claw-proxmox-source.tar.gz" \
  --manifest "$REMOTE_STAGE/sales-claw-proxmox-source.MANIFEST.json" \
  --expected-commit "$EXPECTED_SOURCE_COMMIT" \
  --expected-nested-source "openwa/upstream=$EXPECTED_OPENWA_COMMIT" \
  --destination "$REMOTE_STAGE/source"
test "$(stat -c '%U:%G' "$REMOTE_STAGE/source")" = "debian:debian"
mv -T "$REMOTE_STAGE/source" /home/debian/sales-claw
```

**Stop-Gate:** Unsicherer Pfad, falscher Owner, Manifestabweichung,
unerwarteter Tar-Typ, Extraktionsfehler oder bereits vorhandener Zielbaum
beendet den Cutover. `.env` wird noch nicht uebertragen.

## 6. Secrets- und Archiv-Transfer

Jetzt und erst jetzt eine **frische** Betreiberbestaetigung fuer die lokale
`.env` einholen. Danach `.env` separat per SCP nach
`/home/debian/sales-claw/.env` uebertragen und remote unmittelbar pruefen:

```bash
chmod 600 .env
test -s .env && stat -c '%a %n' .env
```

Die Kontrolle prueft nur Existenz/Nichtleerheit und Dateimodus; keinen Inhalt, Token oder Secretlaenge.

Die Windows-Adresse aus `.env` ist nicht autoritativ. Aus dem bereits
validierten Preflightwert lokal eine Einzeilen-Datei mit
`UI_TAILSCALE_IP=$VmTailscaleIp` erzeugen, als `.env.proxmox` separat
uebertragen, Modus `600` setzen und remote bestaetigen, dass der Wert exakt mit
`tailscale ip -4` uebereinstimmt. Danach State/Keys- und OpenWA-Archive samt
Manifesten in ein frisches Staging-Verzeichnis uebertragen.

**Stop-Gate:** Ohne frische Secret-Freigabe, bei Modusabweichung, fehlender
Datei, abweichender Tailscale-IP oder Transferfehler wird nichts restored und
kein Dienst gestartet.

## 7. Verifikation und Restore

Remote alle drei Archive erneut gegen ihre Manifeste pruefen und probeweise vollstaendig entpacken. Erst danach exakt die drei benannten Volumes
`sales-claw-state`, `sales-claw-keys` und `openwa-data` anlegen und aus dem
jeweils gleichnamigen, verifizierten Archiv befuellen. Keine Globs oder
praefixbasierten Treffer verwenden.

Nach dem Restore den getesteten, fest auf diese drei Volumes begrenzten Helfer
mit den zuvor festgehaltenen absoluten Backup-Pfaden ausfuehren:

```bash
python3 scripts/verify-restored-state.py \
  --state-backup "$REMOTE_STATE_BACKUP" \
  --openwa-backup "$REMOTE_OPENWA_BACKUP"
```

Der Helfer prueft die gepinnten Manifestwerte und Archivhashes. Vor dem ersten
Wegwerfcontainer prueft er alle drei Volumes einzeln mit exakten
`docker volume inspect`-Argumentarrays und akzeptiert je Probe nur genau den
angeforderten Namen. Ein fehlendes, leeres, mehrdeutiges oder abweichendes
Ergebnis beendet die Phase, ohne dass `docker run` ein Volume erzeugen kann.
Erst danach entpackt er jedes Archiv vollstaendig in einem Wegwerfcontainer und mountet nur
`sales-claw-state`, `sales-claw-keys` und `openwa-data` read-only und vergleicht
deterministisch Dateianzahl sowie SHA-256-Inventar aller regulaeren Dateien.
Das ist strenger als einzelne Key-Konfigurationshashes. Er nutzt
`--network none`, gibt nur Volume-Status und Anzahlen aus und besitzt keinen
Startpfad. Erst sein Exit-Code `0` erlaubt Phase 8; dieser Nachweis liegt vor
jedem Dienststart.

**Stop-Gate:** Vorherige Probe, Volume-Allowlist, Restore oder nachgelagerter
Soll-/Ist-Vergleich rot: alle Dienste bleiben gestoppt; fremde Volumes bleiben
unangetastet.

## 8. Compose-Check

Im VM-Projektpfad immer beide Env-Dateien und alle drei Compose-Dateien
verwenden:

```bash
COMPOSE="docker compose --env-file .env --env-file .env.proxmox -f docker-compose.yml -f docker-compose.openwa.yml -f docker-compose.proxmox.yml"
VmTailscaleIp="$(tailscale ip -4)"
test "$(cat .env.proxmox)" = "UI_TAILSCALE_IP=$VmTailscaleIp"
$COMPOSE config --quiet
$COMPOSE config --format json | python3 scripts/check-compose-bindings.py --expected-tailscale "$VmTailscaleIp"
```

Der metadata-only Binding-Gate muss fuer `sales-ui:8791` exakt `127.0.0.1` und `$VmTailscaleIp` bestaetigen. Jede Wildcard-, LAN- oder abweichende Adresse ist
ein Fehler. Das JSON darf nicht auf dem Terminal ausgegeben werden.

**Stop-Gate:** Config-Fehler, fehlender Binding-Gate oder andere Bindings
verhindern jede Compose-Startaktion.

## 9. Core-Start

Nur die vier Kernservices starten:

```bash
$COMPOSE up -d openwa sales-mcp sales-inbox sales-ui
```

Danach nur Statusnamen, OpenWA-Health, einen DB-Lesezugriff ohne Kundendaten,
die Session-ID samt Status und die UI ueber Tailscale pruefen.

**Stop-Gate:** Fehlender Health-, DB-, Session- oder UI-Nachweis stoppt die
Kernservices und sperrt alle Dispatcher.

## 10. Dispatcher-Gates

WhatsApp und E-Mail separat zaehlen und separat freigeben:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'whatsapp';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (WhatsApp); erst danach:

```bash
$COMPOSE up -d sales-dispatch
```

Danach dieselbe Reihenfolge fuer E-Mail:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'email';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (E-Mail); erst danach:

```bash
$COMPOSE up -d sales-mail
```

LinkedIn wird nur inventarisiert:

```sql
SELECT count(*) AS approved_count FROM sales.drafts
WHERE status = 'approved' AND channel = 'linkedin';
```

Die Ausgabe ist die **approved-Queue nur als Anzahl** (LinkedIn). Der Start bleibt bis zum LinkedIn-Sperrgate in Phase 11 gesperrt.

**Stop-Gate:** Fehlende kanalspezifische Freigabe, unerwartete Anzahl oder ein
anderer vorgeschlagener Dienst stoppt den jeweiligen Workerstart.

## 11. LinkedIn-Sperrgate

`sales-linkedin bleibt gestoppt`. Der aktuelle Worker verarbeitet einen Batch
und kann die Autorisierung nicht auf exakt eine Draft-ID begrenzen. Ausserdem
fehlt ein nicht wiederholbarer Zustand fuer unklare Veroeffentlichungsergebnisse.
Exact-ID-One-Shot, Retry-Sperre und der unbekannte externe Erfolgszustand
muessen separat implementiert und verhaltensgeprueft werden. Erst ein neuer,
eigens freigegebener Runbook-Stand darf diesen Worker starten.

**Stop-Gate:** In diesem Runbook ist jeder LinkedIn-Start unzulaessig. Der
genehmigte Beitrag bleibt unveroeffentlicht; es gibt keinen Retry.

### Stand 25.08.2026 — die drei Mangelpunkte sind adressiert

Das Gate BLEIBT ZU. Diese Notiz hebt es nicht auf; sie legt nur die Fakten
fuer den bereit, der den naechsten Runbook-Stand prueft und freigibt.

Die drei oben genannten Punkte sind in `sales-mcp/linkedin_dispatch.py` und
`sales-mcp/linkedin_api.py` umgesetzt und verhaltensgeprueft:

1. **Exact-ID-One-Shot.** Der Stapellauf ist weg. Der Dienst liest
   `LINKEDIN_DRAFT_ID`, veroeffentlicht genau diesen Entwurf und beendet
   sich. Ohne Kennung listet er nur, was freigegeben waere, und tut nichts.
   Test: `test_nur_der_genannte_entwurf_geht_raus`.
2. **Retry-Sperre.** `bereits_veroeffentlicht()` fragt `activities` — nicht
   `drafts.status`, denn der laesst sich ueber
   `entwurf_erneut_freigeben(bestaetigt=True)` zuruecksetzen, `activities`
   dagegen ist append-only. Der Beleg entsteht VOR der Statusbuchung, damit
   er auch bei gescheiterter Buchung existiert. Tests:
   `test_erneute_freigabe_postet_nicht_ein_zweites_mal`,
   `test_beleg_steht_vor_der_buchung`.
3. **Unbekannter externer Erfolgszustand.** `LinkedInFehler` traegt jetzt
   `ungewiss`. Zeitueberschreitung, Netzabbruch, 408 und 5xx gelten als
   ungewiss (bei 4xx hat LinkedIn geantwortet und abgelehnt). Ein ungewisser
   Ausgang schreibt denselben sperrenden Beleg — mit `ungewiss: true` und
   `beitrag: null` — und bucht den Entwurf mit einem `UNGEWISS:`-Text, der
   sagt, dass der Beitrag oeffentlich stehen KANN. Tests:
   `test_ungewisser_ausgang_sperrt_jede_wiederholung`,
   `test_ungewissheit_wird_am_status_erkannt`,
   `test_zeitueberschreitung_ist_ungewiss`.

Was ein kuenftiger Runbook-Stand zusaetzlich klaeren muss, bevor der Worker
laufen darf:

* Der Bezug `media/` ist nicht Teil des Quellpakets (Abschnitt 4). Ohne
  eigene Datenfreigabe und getrennten Transfer gibt es auf der VM keine
  Bild- und Videodateien — Beitraege mit `media_ref` scheitern dort
  zwangslaeufig, und zwar erst nach der Freigabe.
* Ein ungewisser Ausgang verlangt einen Menschen, der auf dem Profil
  nachsieht. Fuer den Pilotbetrieb gehoert festgelegt, wer das tut und
  woran er den Fall bemerkt.

## 12. Autostart-Abnahme

Nach erfolgreicher Kern- und Dispatcher-Abnahme VM und Docker kontrolliert
neu starten. OpenWA, MCP, Inbox, UI sowie nur die freigegebenen WhatsApp- und
Mail-Worker duerfen zurueckkehren; `sales-linkedin`, sales-claw und sales-auto bleiben gestoppt.

**Stop-Gate:** Kehrt ein manueller Dienst zurueck oder fehlt ein erwarteter
Kernservice, Abnahme als fehlgeschlagen markieren und nicht weiter betreiben.

## 13. Rollback

Bei einem roten Gate alle VM-Projektcontainer vollstaendig stoppen und deren Stillstand per Namensliste nachweisen. Erst danach darf Windows/OpenWA wieder gestartet werden. Niemals beide OpenWA-Instanzen parallel betreiben. Ist
VM-OpenWA noch aktiv, darf Windows/OpenWA nicht starten.

**Stop-Gate:** Bei unklarem Zustand beide Seiten gestoppt lassen und die
Ursache vor jeder Wiederaufnahme klaeren.
