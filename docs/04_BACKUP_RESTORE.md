# 04 — Sicherung und Wiederherstellung

Diese Mechanik wurde **nicht behauptet, sondern bewiesen**: an einer
Wegwerf-Markierungsdatei, nicht an der echten WhatsApp-Kopplung des Betreibers.
Der Grund dafür steht in `.superpowers/sdd/2026-08-17-sales-claw-fundament/task-3-brief.md`:
ein ungeprüftes Restore-Skript zum ersten Mal an der echten Kopplung zu testen
hieße, diese Kopplung als Testobjekt zu verwenden. Also erst hier, wo nichts
Wertvolles verloren geht, falls das Skript einen Fehler hat.

## Die beiden Skripte

### `scripts/backup-state.ps1`

```powershell
pwsh -File scripts/backup-state.ps1
# optional: pwsh -File scripts/backup-state.ps1 -Ziel D:\anderer\ordner
```

Legt `<Ziel>/sales-claw-<zeitstempel>/` an mit:

- `state.tar` — wortgetreues tar-Archiv des Volumes `sales-claw-state`
- `keys.tar` — wortgetreues tar-Archiv des Volumes `sales-claw-keys`
- `openclaw-backup/create.log` — Log von `openclaw backup create`, ausgeführt
  im laufenden Container (nur wenn der Container läuft)

Gibt den vollen Pfad des Sicherungsordners auf stdout aus, Exit `0`.

### `scripts/restore-state.ps1`

```powershell
pwsh -File scripts/restore-state.ps1 -Quelle backups/sales-claw-20260817-174858
```

Voraussetzung: der Container muss **gestoppt** sein (`docker compose down`).
Das Skript prüft das selbst und bricht mit Fehler ab, wenn er noch läuft —
damit niemand versehentlich in ein offenes Volume schreibt. Bevor überhaupt
ein Volume angefasst wird, prüft das Skript **beide** Archive vollständig
(siehe „Archivprüfung vor dem Schreiben" unten). Erst danach leert es beide
Ziel-Volumes und spielt die tar-Archive aus der Quelle ein. Anschließend
`docker compose up -d`.

## Warum zwei Sicherungswege

Mit Absicht zwei unterschiedliche Mechanismen, nicht einer:

1. **tar-Archiv** (`state.tar`, `keys.tar`) — byteidentische Kopie der
   Volume-Inhalte. Kennt keine Semantik, ist aber der eigentliche
   Sicherungsweg: unabhängig davon, ob OpenClaw selbst korrekt läuft, lässt
   sich damit jeder Zustand exakt wiederherstellen.
2. **`openclaw backup create`** — OpenClaws eigenes Archiv, das die Semantik
   kennt (Konfiguration, Credentials, Sessions, Workspaces) und sich mit
   `openclaw backup verify` prüfen lässt. Es läuft nur, wenn der Container
   läuft, und ergänzt das tar-Archiv — ersetzt es aber nicht.

Beim Testlauf für diesen Task lief `openclaw backup create` fehlerfrei
(kein erwarteter Stolperstein trat ein). Das Archiv selbst entsteht im
Container unter `/app/...-openclaw-backup.tar.gz` und wird vom Skript
bewusst nicht aus dem Container kopiert — nur das Log wird gesichert. Für den
eigentlichen Restore ist ohnehin das tar-Archiv der Volumes maßgeblich.

## Härtung (Fix-Runde 1)

Ein Review der ersten Fassung ergab zwei Befunde. Beide stammten aus dem
ursprünglichen Brief-Code, nicht aus einer eigenmächtigen Abweichung — sie
sind hier trotzdem als Verhalten der jetzigen Skripte dokumentiert, weil sie
den Betrieb betreffen.

### Archivprüfung vor dem Schreiben (Befund 1, kritisch)

Vorher prüfte `restore-state.ps1` nur, ob `state.tar`/`keys.tar` **existieren**
(`Test-Path`). Eine abgebrochene Kopie, eine volle Platte oder ein
dazwischenfunkender Virenscanner hinterlassen aber eine Datei, die existiert
und trotzdem nichts taugt. Da Leeren und Entpacken in derselben Kommandokette
liefen, wäre das Zielvolume schon geleert gewesen, bevor ein Entpack-Fehler
auffiel — bei zwei Volumes nacheinander sogar ein asymmetrischer Halbausfall
möglich: Volume 1 überschrieben, Volume 2 nur noch geleert.

Jetzt prüft das Skript **beide** Archive vollständig, bevor es **irgendein**
Volume berührt: Datei vorhanden, Größe > 0 Byte, probeweise **vollständig
entpackt** in ein Wegwerf-Verzeichnis im Container, mindestens ein Eintrag
danach vorhanden (siehe „Härtung (Fix-Runde 2)" unten — die erste Fassung
prüfte nur mit `tar -tf`, das reicht nicht). Schlägt eine der beiden Prüfungen
fehl, bricht das Skript ab, bevor die Schreibschleife überhaupt beginnt — auch
wenn das erste Archiv bereits als gültig bestätigt wurde.

Belegt mit drei absichtlich kaputten Sicherungen (volle Ausgaben und
Prüfsummen-Vergleich in
`.superpowers/sdd/2026-08-17-sales-claw-fundament/task-3-report.md`,
Abschnitt „Fix-Runde 1"):

1. **Der eigentliche Zielfall:** `state.tar` gültig, `keys.tar` mit 0 Byte.
   Ausgabe: `geprueft: state.tar (3591680 Byte, 40 Eintraege)`, danach Abbruch
   mit `Leer: keys.tar hat 0 Byte — nichts wurde angefasst.` Trotz bereits
   bestätigt gültigem `state.tar` blieben **beide** Volumes unverändert
   (SHA-256 von `openclaw.json` vor und nach dem Versuch identisch, Keys-Volume
   weiterhin leer — per read-only-Mount kontrolliert, ohne den Container zu
   starten).
2. `state.tar` mit 0 Byte (der im Review wörtlich genannte Fall): Abbruch mit
   `Leer: state.tar hat 0 Byte — nichts wurde angefasst.`
3. `state.tar` nicht leer, aber kein gültiges tar (Textmüll): Abbruch mit
   `Ohne Eintraege: state.tar — nichts wurde angefasst.` — deckt den
   Prüfpfad ab, der nicht über die Größe, sondern über den Archivinhalt geht.

### Namensschutz (Befund 2, wichtig)

Beide Skripte lehnen jetzt jeden Volume-Namen ab, der nicht dem Muster
`sales-claw-[a-z]+` entspricht — geprüft ganz am Anfang, vor jedem
Docker-Befehl. Grund: die Volume-Namen kommen aus Parametern ohne
Beschränkung; ein Tippfehler beim Aufruf hätte sonst ein fremdes Volume
treffen können. Auf dieser Maschine liegt `openclaw-festival-state` direkt
daneben — ein fremdes Vorhaben, das nie Ziel eines Aufrufs sein darf.

Getestet mit erfundenen Namen (`test-fremd-volume`, `test-fremd-volume-2`),
**nie** mit einem real existierenden Volume: Aufruf mit `-StateVolume
test-fremd-volume` bzw. `-KeysVolume test-fremd-volume-2` bricht bei beiden
Skripten sofort ab mit `Verweigert: '<name>' gehoert nicht zu diesem Projekt.
Erlaubt sind nur Namen der Form sales-claw-*.`

### Stiller Fehlschlag bei `openclaw backup create` (Befund 3, geringfügig)

`backup-state.ps1` prüft jetzt den Exit-Code von `openclaw backup create`.
Bei Fehlschlag bricht das Skript **nicht** ab (die tar-Archive sind der
maßgebliche Sicherungsweg und bereits geschrieben), gibt aber eine deutliche
Warnung aus, damit ein fehlendes semantisches Archiv nicht unbemerkt bleibt.

## Härtung (Fix-Runde 2)

Eine Nachprüfung der Fix-Runde-1-Härtung ergab, dass Befund 1 **nicht**
tatsächlich behoben war — nur anders formuliert.

### Die Archivprüfung aus Fix-Runde 1 war wirkungslos gegen Trunkierung

Der Code aus Fix-Runde 1 prüfte so:

```sh
tar -tf /quelle/$name.tar 2>/dev/null | wc -l
```

Der Exit-Code einer Pipe in einer POSIX-Shell ist der Exit-Code des
**letzten** Glieds — hier `wc -l`, das immer `0` liefert, egal was `tar`
gemacht hat. Busybox-`sh` im `alpine:3.20`-Image kennt kein `pipefail`. Ein
**abgeschnittenes** Archiv lässt sich mit `tar -tf` oft noch teilweise
auflisten (die gelesenen Header sind ja intakt), scheitert aber beim
tatsächlichen Entpacken mit `tar: short read`. Die Prüfung aus Fix-Runde 1
hätte ein solches Archiv als „geprueft: N Eintraege" durchgewunken — und
damit Vertrauen suggeriert, das nicht gerechtfertigt war.

**Belegt** (volle Ausgaben in
`.superpowers/sdd/2026-08-17-sales-claw-fundament/task-3-report.md`,
Abschnitt „Fix-Runde 2"): eine echte `state.tar` wurde auf die ersten 16 KB
abgeschnitten. Die alte Prüfung (`tar -tf | wc -l`) lieferte `4` Einträge bei
Pipe-Exit-Code `0` — wäre also durchgegangen. Der tatsächliche
Entpackversuch (`tar -xf`) auf derselben Datei scheiterte mit
`tar: short read`, Exit-Code `1`. Das ist exakt die Lücke: Auflisten ≠
Entpacken-Können.

### Die neue Prüfung: probeweise vollständig entpacken

```sh
mkdir -p /probe && tar -xf /quelle/$name.tar -C /probe && find /probe -mindepth 1 | wc -l
```

Die `&&`-Kette sorgt dafür, dass ein Fehlschlag von `tar` den Exit-Code des
gesamten Befehls bestimmt — `find` läuft dann gar nicht erst an. Das prüft,
was tatsächlich zählt: lässt sich das Archiv entpacken, nicht nur auflisten.

Gegen dieselbe trunkierte `state.tar` bricht `restore-state.ps1` jetzt korrekt
ab: `Beschaedigt: state.tar laesst sich nicht entpacken — nichts wurde
angefasst.` Der asymmetrische Fall aus Befund 1 wurde mit Trunkierung
(statt 0 Byte) erneut geprüft: gültiges `state.tar`, auf 256 Byte
abgeschnittenes `keys.tar` — `state.tar` wurde probeweise entpackt und als
gültig bestätigt, danach Abbruch bei `keys.tar` (`invalid tar magic`), **bevor**
die Schreibschleife begann. Beide Volumes blieben in beiden Fällen
bit-identisch zur Baseline (SHA-256-Vergleich, siehe Report).

### Betrieblicher Nebenbefund: echte Leer-Archive fallen jetzt durch

Die neue Prüfung zieht eine Konsequenz, die in Fix-Runde 1 nicht auffiel:
`find /probe -mindepth 1` zählt nur Einträge **unterhalb** des
Entpack-Ziels — ein Archiv, dessen einziger Eintrag das Wurzelverzeichnis
selbst ist (wie `keys.tar`, solange das Keys-Volume noch keine echten
Schlüssel enthält), liefert danach `0` und wird als „Ohne Eintraege"
abgelehnt. Die alte `tar -tf`-Zählung hatte diesen Wurzel-Eintrag noch
mitgezählt (`1 Eintraege`) und wäre durchgegangen.

Praktisch bedeutet das: solange `sales-claw-keys` inhaltlich leer ist (Stand
Task 2 — noch keine WhatsApp-Kopplung, keine Schlüssel), lässt sich aus einem
in diesem Zustand erzeugten Backup **nicht** restaurieren, ohne dass im
Keys-Volume mindestens eine echte Datei liegt. Für den Nachweis in
Fix-Runde 2 wurde deshalb — genau wie mit `PROBE.txt` im State-Volume —
zusätzlich eine Wegwerf-Markierung `PROBE_KEYS.txt` ins Keys-Volume gelegt,
vor der Sicherung geschrieben und nach der Verifikation wieder entfernt. Das
ist kein Skriptfehler, sondern eine Verschärfung mit echtem Kollateraleffekt
auf den aktuellen (leeren) Projektzustand — sobald reale Schlüssel im Volume
liegen, verschwindet der Effekt von selbst.

### Namensschutz: gross-/kleinschreibungsempfindlich

`-notmatch` ist in PowerShell standardmäßig gross-/kleinschreibungsunempfindlich
und hätte `SALES-CLAW-STATE` durchgelassen — für Docker ein anderer,
tatsächlich nicht existierender Volume-Name. Beide Skripte verwenden jetzt
`-cnotmatch` (case-sensitive) für den Namensschutz.

## Warum beide Volumes zusammengehören (Spec §5)

`docs/02_ARCHITECTURE.md` (Abschnitt „Warum zwei Volumes") hält fest:
`/home/node/.openclaw` (Volume `sales-claw-state`) enthält Konfiguration,
Agenten, `credentials/` und `memory/`. `/home/node/.config/openclaw` (Volume
`sales-claw-keys`) enthält die Verschlüsselungsschlüssel dazu. Wer nur das
erste sichert, hat beim Restore verschlüsselte Daten ohne Schlüssel — ein
Restore, der nur eines der beiden Volumes zurückspielt, ist kein
vollständiger Restore. Beide Skripte behandeln die Volumes deshalb immer als
Paar, nie einzeln.

## Der Rot/Grün-Beweis (gemessen, nicht behauptet)

Ablauf und tatsächliche Ausgaben stehen vollständig in
`.superpowers/sdd/2026-08-17-sales-claw-fundament/task-3-report.md`. Kurzfassung:

1. Markierungsdatei `PROBE.txt` mit Inhalt `markierung-task3` ins Volume
   `sales-claw-state` geschrieben.
2. Sicherung gefahren (`state.tar` mit 40 Einträgen inkl. `PROBE.txt` und
   `openclaw.json`, `keys.tar` als gültiges — zu diesem Zeitpunkt inhaltlich
   leeres — Archiv, da im Keys-Volume noch keine Schlüssel liegen).
3. **Rot:** `docker compose down`, `docker volume rm sales-claw-state
   sales-claw-keys` (ausschließlich diese zwei, exakter Namensabgleich),
   `docker compose up -d`. Danach: `cat PROBE.txt` → `No such file or
   directory`. Der Container lief ohne Konfiguration sogar in eine
   Neustart-Schleife (`Restarting`) — der Verlust war vollständig, nicht nur
   die Markierung fehlte.
4. **Grün:** `docker compose down`, `restore-state.ps1 -Quelle <Sicherungspfad>`,
   `docker compose up -d`. Danach: `cat PROBE.txt` → `markierung-task3`.
   `docker compose ps` → `Up ... (healthy)`.
5. Zusätzlich geprüft (nicht nur die Markierung — auch das, was den Test
   eigentlich überleben musste): SHA-256-Prüfsumme von `openclaw.json` vor
   dem Löschen und nach dem Restore war **identisch**. Länge des
   Gateway-Tokens (`gateway.auth.token`) und Anzahl der OpenRouter-Modelleinträge
   (`models.providers.openrouter.models`) stimmten vor und nach dem Restore
   überein. Werte selbst wurden zu keinem Zeitpunkt ausgegeben.
6. Markierungsdatei danach wieder entfernt (Aufräumen, kein Produktionsartefakt).

Nach der Härtung (Fix-Runde 1) wurde dieser Zyklus mit den gehärteten Skripten
und einer neuen Markierung (`markierung-task3-fix1`) erneut komplett gefahren:
gleiches Ergebnis — Verlust nach dem Löschen, vollständige Wiederherstellung
inkl. identischer `openclaw.json`-Prüfsumme, `docker compose ps` wieder
`healthy`. Die Verschärfung hat den Normalfall nicht beeinträchtigt.

Nach Fix-Runde 2 (Entpack-Probe statt Auflisten) erneut gefahren, diesmal mit
Markierungen in **beiden** Volumes (`markierung-task3-fix2` in
`sales-claw-state`, `markierung-keys-fix2` in `sales-claw-keys` — siehe
betrieblichen Nebenbefund oben, warum das für diesen Lauf nötig war). Gleiches
Ergebnis: beide Markierungen weg nach dem Löschen, beide zurück nach dem
Restore, `openclaw.json`-Prüfsumme identisch, `docker compose ps` wieder
`healthy`. Beide Markierungen danach entfernt.

Die zu diesem Zeitpunkt im Volume liegende WhatsApp-Konfiguration ist reine
Policy (`enabled`, `dmPolicy`, `allowFrom`, …) — noch **keine** Kopplung
(keine Session, kein QR-Pairing). Sie wurde beim Test nicht verändert und ist
nicht Gegenstand dieses Tasks.

## Empfehlung: geplanter täglicher Lauf

`scripts/backup-state.ps1` ohne Parameter aufrufen (Standardziel
`backups/` im Repo, bereits gitignored) — z. B. über die Windows-Aufgaben­planung
oder ein äquivalentes Scheduling auf der Ziel-VM, einmal täglich außerhalb
der Geschäftszeiten. Aufbewahrung z. B. 7 tägliche + 4 wöchentliche Archive;
Löschung älterer Sicherungsordner ist bewusst **nicht** Teil dieses Skripts
und sollte separat (Cron/Aufgabenplanung mit Alters-Filter) erfolgen, damit
`backup-state.ps1` selbst niemals löschend wirkt. Sicherungsordner enthalten
Schlüssel und Konfiguration im Klartext-Archiv — Zugriff auf `backups/`
entsprechend einschränken und niemals versionieren (`.gitignore` deckt
`backups/`, `*.tar`, `*.tar.gz` bereits ab).
