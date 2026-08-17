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
# nur im Notfall: pwsh -File scripts/backup-state.ps1 -OhneStopp
```

Legt `<Ziel>/sales-claw-<zeitstempel>/` an mit:

- `state.tar` — wortgetreues tar-Archiv des Volumes `sales-claw-state`
- `keys.tar` — wortgetreues tar-Archiv des Volumes `sales-claw-keys`
- `openclaw-backup/create.log` — Log von `openclaw backup create`, ausgeführt
  im laufenden Container (nur wenn der Container läuft)
- `MANIFEST.json` — die Sollwerte je Archiv (`sha256`, `bytes`, `eintraege`)
  plus `container_gestoppt`. **Wird zuletzt geschrieben**: fehlt die Datei,
  war der Lauf unvollständig, und `restore-state.ps1` lehnt die Sicherung ab.

**Der Container wird für die Dauer des tar-Laufs gestoppt** und danach wieder
gestartet (Begründung unten, „Härtung (Fix-Runde 4)"). Die Ausfallzeit liegt
bei wenigen Sekunden. `-OhneStopp` unterdrückt das, warnt dafür deutlich und
setzt `container_gestoppt: false` im Manifest — worauf `restore-state.ps1`
später erneut warnt.

Gibt den vollen Pfad des Sicherungsordners auf stdout aus, Exit `0`.

### `scripts/restore-state.ps1`

```powershell
pwsh -File scripts/restore-state.ps1 -Quelle backups/sales-claw-20260817-174858
```

Voraussetzung: der Container muss **gestoppt** sein (`docker compose down`).
Das Skript prüft das selbst und bricht mit Fehler ab, wenn er noch läuft —
damit niemand versehentlich in ein offenes Volume schreibt. Bevor überhaupt
ein Volume angefasst wird, gleicht das Skript **beide** Archive gegen
`MANIFEST.json` ab — Größe, SHA-256 und Eintragszahl — und entpackt sie
zusätzlich probeweise (siehe „Härtung (Fix-Runde 4)" unten). Fehlt das
Manifest, bricht es ab, ohne ein Volume anzufassen. Erst wenn beide Archive
bestehen, leert es die Ziel-Volumes und spielt die tar-Archive ein.
Anschließend `docker compose up -d`.

**Sicherungen aus der Zeit vor Fix-Runde 4 enthalten kein `MANIFEST.json` und
werden abgelehnt.** Das ist Absicht: für sie gibt es keine Sollwerte, also
lässt sich nicht feststellen, ob sie noch das sind, was gesichert wurde.

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

### Betrieblicher Nebenbefund aus Fix-Runde 2 — inzwischen behoben (siehe Fix-Runde 3)

Die Fix-Runde-2-Prüfung zog eine Konsequenz, die dort nicht auffiel:
`find /probe -mindepth 1` zählt nur Einträge **unterhalb** des
Entpack-Ziels — ein Archiv, dessen einziger Eintrag das Wurzelverzeichnis
selbst ist (wie `keys.tar`, solange das Keys-Volume noch keine echten
Schlüssel enthält), lieferte danach `0` und wurde als „Ohne Eintraege"
**abgelehnt** — ein Abbruch, obwohl nichts beschädigt war. Dieses Verhalten
ist mit Fix-Runde 3 korrigiert (siehe unten): ein leeres, aber unversehrtes
Archiv ist jetzt zulässig. Der Abschnitt bleibt hier stehen, weil er den
Fehler dokumentiert, der zu Fix-Runde 3 geführt hat.

### Namensschutz: gross-/kleinschreibungsempfindlich

`-notmatch` ist in PowerShell standardmäßig gross-/kleinschreibungsunempfindlich
und hätte `SALES-CLAW-STATE` durchgelassen — für Docker ein anderer,
tatsächlich nicht existierender Volume-Name. Beide Skripte verwenden jetzt
`-cnotmatch` (case-sensitive) für den Namensschutz.

## Härtung (Fix-Runde 3)

Eine Nachprüfung von Fix-Runde 2 ergab: das Bedenken, das im Fix-Runde-2-Bericht
gemeldet wurde, war kein Randfall, sondern ein echter Defekt. Die Prüfung
brach bei null Einträgen ab (`Ohne Eintraege: $name.tar — nichts wurde
angefasst.`) — aber ein leeres Volume ist ein **gültiger Zustand**, kein
Defekt. `sales-claw-keys` ist seit Projektbeginn leer. Mit der
Fix-Runde-2-Fassung hätte ein Restore aus einer völlig intakten Sicherung
grundsätzlich fehlschlagen müssen, solange das Keys-Volume leer ist — ein
Schutz, der unversehrte Sicherungen pauschal für unbrauchbar erklärt, richtet
mehr Schaden an als die Lücke, die er schließen sollte.

### Die Korrektur: Eintragszahl ist Information, kein Kriterium

Die Unversehrtheit ist bereits durch das erfolgreiche probeweise Entpacken
belegt (siehe Fix-Runde 2). Bei null Einträgen gibt das Skript jetzt einen
gelben Hinweis aus, bricht aber **nicht** ab:

```powershell
$anzahl = [int]$eintraege.Trim()
if ($anzahl -lt 1) {
    Write-Host "HINWEIS: $name.tar ist unversehrt, aber leer — das Volume enthielt nichts." -ForegroundColor Yellow
}
Write-Host "probeweise entpackt: $name.tar ($groesse Byte, $anzahl Eintraege)"
```

Der Beschädigt-Fall (`$LASTEXITCODE -ne 0` von `tar -xf`) bleibt unverändert
ein Abbruch — nur die künstliche Untergrenze „mindestens 1 Eintrag" ist
entfallen.

### Nachweis 1: der zuletzt fehlschlagende Fall läuft jetzt durch

Sicherung erzeugt, während `sales-claw-keys` leer war, beide Volumes gelöscht,
wiederhergestellt (volle Ausgaben in
`.superpowers/sdd/2026-08-17-sales-claw-fundament/task-3-report.md`,
Abschnitt „Fix-Runde 3"):

```
probeweise entpackt: state.tar (1782272 Byte, 39 Eintraege)
HINWEIS: keys.tar ist unversehrt, aber leer - das Volume enthielt nichts.
probeweise entpackt: keys.tar (1536 Byte, 0 Eintraege)
Beide Archive in Ordnung. Jetzt erst werden die Volumes geleert.
wiederhergestellt: state.tar -> sales-claw-state
wiederhergestellt: keys.tar -> sales-claw-keys
Wiederherstellung abgeschlossen.
```

Exit `0`, `docker compose ps` danach `healthy`, Markierung und
`openclaw.json`-Prüfsumme (inkl. Gateway-Token-Länge und
OpenRouter-Katalogeintrag) vollständig wiederhergestellt. Genau dieser Ablauf
war mit der Fix-Runde-2-Fassung nicht möglich.

### Nachweis 2: Trunkierungsschutz aus Fix-Runde 2 bleibt erhalten

Dieselben zwei Trunkierungsfälle aus Fix-Runde 2 gegen die neue Fassung
wiederholt: eine auf 16 KB abgeschnittene `state.tar` (isoliert) und dieselbe
Datei zusammen mit einem auf 256 Byte abgeschnittenen `keys.tar`
(asymmetrisch). Beide brechen weiterhin mit `Beschaedigt: ... laesst sich
nicht entpacken — nichts wurde angefasst.` ab, beide Volumes blieben in
beiden Fällen bit-identisch zur Baseline (SHA-256-Vergleich, siehe Report).
Die Lockerung aus Fix-Runde 3 betrifft ausschließlich den Fall „leer, aber
unversehrt" — Beschädigung wird weiterhin zuverlässig erkannt.

## Härtung (Fix-Runde 4) — Manifest mit Sollwerten und Container-Stopp

Drei Fassungen der Archivprüfung (Fix-Runde 1 bis 3) sind an derselben Sache
gescheitert: Sie fragten **„lässt sich das entpacken"** statt **„ist das noch
das, was gesichert wurde"**. Ohne einen beim Sichern festgehaltenen Sollwert
kann eine Prüfung das prinzipiell nicht beantworten.

### Was jede reine Entpack-Prüfung durchlässt — an diesem Projekt gemessen

Alle drei Fälle wurden an der echten `state.tar` dieses Projekts
(1 539 584 Byte, 39 Einträge) reproduziert; volle Ausgaben im Report,
Abschnitt „Fix-Runde 4":

1. **Trunkierung auf tar-Blockgrenze.** Busybox-`tar` liest eine an einer
   Blockgrenze abgeschnittene Datei als reguläres Archivende und meldet
   Erfolg. Gemessen: **24 von 24** geprüften Header-Blockgrenzen lieferten
   `tar -xf` Exit `0` — von 0 bis 38 Einträgen. Die Fix-Runde-3-Prüfung hätte
   jede einzelne davon durchgewunken.
2. **Nullgefüllte Datei.** Eine `state.tar` aus 1 539 584 Nullbytes — also mit
   **exakt der Größe der echten Sicherung** — entpackt fehlerfrei zu null
   Einträgen. Mit Fix-Runde 3 hätte das den gelben Hinweis „unversehrt, aber
   leer" ausgelöst und die Volumes **geleert**, ohne etwas zurückzuspielen.
3. **Bitfäule im Nutzdatenbereich.** `tar` prüft Header-Prüfsummen, nicht
   Dateiinhalte. Ein einziges gekipptes Bit in den Nutzdaten (Offset 1 205 760,
   `0x6D` → `0x4D`, Größe unverändert) entpackte mit Exit `0` und **39
   Einträgen — dem exakten Manifest-Sollwert**. Die Markierungsdatei kam dabei
   als `Markierung-task3-fix4` statt `markierung-task3-fix4` heraus: still
   verfälschte Nutzdaten, von jeder Entpack-Prüfung als in Ordnung gemeldet.

### Die Korrektur: Sollwerte beim Sichern, Abgleich beim Wiederherstellen

`backup-state.ps1` schreibt `MANIFEST.json` mit `sha256`, `bytes` und
`eintraege` je Archiv — **zuletzt**, sodass sein Fehlen einen abgebrochenen
Lauf kennzeichnet. `restore-state.ps1` gleicht beide Archive dagegen ab,
bevor es irgendein Volume berührt, und entpackt sie zusätzlich probeweise
(zweite Verteidigungslinie für den Fall, dass ein Archiv schon beim Sichern
beschädigt war und das Manifest die Beschädigung mitbeurkundet hat).

Belegt mit fünf Fehlerfällen, jeder mit Volume-Fingerabdruck vor und nach dem
Versuch (`find . -type f | sort | xargs sha256sum | sha256sum`), alle
unverändert:

| Fall | Erkennt | Meldung |
|---|---|---|
| `MANIFEST.json` fehlt | Manifest-Pflicht | `Kein MANIFEST.json … nichts wurde angefasst.` |
| 1 Bit gekippt, Größe gleich | **nur** SHA-256 | `Pruefsumme weicht ab fuer state.tar …` |
| Trunkierung auf Blockgrenze | Größe | `Groesse weicht ab fuer state.tar — Soll 1539584 Byte, Ist 1536512.` |
| `state.tar` nullgefüllt, Größe gleich | **nur** SHA-256 | `Pruefsumme weicht ab fuer state.tar …` |
| `keys.tar` nullgefüllt (Größe **und** Eintragszahl stimmen) | **nur** SHA-256 | `geprueft: state.tar (…)`, danach `Pruefsumme weicht ab fuer keys.tar …` |

Der letzte Fall belegt zugleich, dass die Reihenfolge aus Befund 1 erhalten
bleibt: `state.tar` wurde als gültig bestätigt, geschrieben wurde trotzdem
nichts.

### Namensschutz: Erlaubnisliste statt Muster (ersetzt Fix-Runde 1/2)

Das Muster `^sales-claw-[a-z]+$` aus Fix-Runde 1/2 ist durch eine
ausdrückliche Erlaubnisliste ersetzt: `sales-claw-state` und
`sales-claw-keys`, sonst nichts. Grund: ein formtreuer Tippfehler
(`sales-claw-stat`) passt auf das Muster, meint aber ein anderes Volume —
`restore-state.ps1` legte es still an und meldete Erfolg, während das echte
Volume unberührt blieb. Zusätzlich wird jetzt auch der **Containername**
geprüft; ohne das macht ein Tippfehler dort die Laufend-Prüfung wirkungslos.

### Der Befund, der schwerer wiegt als jede Archivprüfung: tar über laufende Schreibvorgänge

Die bisherige Sicherung tarrte die Volumes, **während der Container lief**.
Der Session-Store — dort liegt die WhatsApp-Kopplung — wird im Betrieb
geschrieben. Ein tar über laufende Schreibvorgänge liefert ein strukturell
einwandfreies Archiv mit einem Zustand mitten im Schreiben: Prüfsumme,
Größe, Eintragszahl und Entpackprobe stimmen alle, und die zurückgespielte
Sitzung ist trotzdem tot. Keine Archivprüfung der Welt kann das bemerken,
weil das Archiv nicht beschädigt ist — es bildet nur einen Zustand ab, den es
so nie gab.

OpenClaws eigenes `backup create` zieht dieselbe Konsequenz und meldet bei
jedem Lauf:

```
Backup skipped 5 volatile files (live sessions, cron logs, queues, sockets, pid/tmp).
```

Unser wortgetreues tar würde genau diese Dateien mitnehmen. Deshalb stoppt
`backup-state.ps1` den Container jetzt für die Dauer des tar-Laufs:

```
Stoppe sales-claw fuer die Dauer der Sicherung…
gesichert: sales-claw-state -> state.tar (1539584 Byte, 39 Eintraege)
gesichert: sales-claw-keys -> keys.tar (1536 Byte, 0 Eintraege)
MANIFEST.json geschrieben — Sicherung vollstaendig.
Starte sales-claw wieder…
```

Gemessene Ausfallzeit: `docker inspect` meldete Stopp um `17:49:03.237Z` und
Wiederanlauf um `17:49:06.697Z` — **3,5 Sekunden**, `docker compose ps`
danach wieder `Up … (healthy)`. Das Manifest hält `container_gestoppt: true`
fest.

`-OhneStopp` bleibt für Notfälle vorhanden, warnt aber laut und setzt
`container_gestoppt: false`; `restore-state.ps1` warnt dann beim Zurückspielen
erneut (`WARNUNG: Diese Sicherung entstand bei laufendem Container …`) — beides
gemessen, siehe Report.

### Der `finally`-Block: der Container kommt auch nach einem Fehlschlag zurück

Ein Sicherungsskript, das den Container stoppt, darf ihn nicht gestoppt
zurücklassen, wenn es mittendrin scheitert. Der Wiederanlauf steht deshalb in
einem `finally`-Block. Belegt mit einer Sicherung, die **nach** dem Stopp
fehlschlug (Ziel auf einem Laufwerk, das Windows anlegen kann, Docker aber
nicht mounten):

```
Stoppe sales-claw fuer die Dauer der Sicherung…
docker: Error response from daemon: mkdir Q:\backup: The system cannot find the path specified.
Starte sales-claw wieder…
Exception: … tar fuer Volume sales-claw-state fehlgeschlagen
```

`docker inspect` bestätigte Stopp (`17:50:39.507Z`) **und** Wiederanlauf
(`17:50:40.141Z`); `docker compose ps` danach wieder `Up … (healthy)`. Der
abgebrochene Lauf hinterließ **kein** `MANIFEST.json` — die unvollständige
Sicherung ist damit als solche gekennzeichnet und wird beim Wiederherstellen
abgelehnt.

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

Nach Fix-Runde 3 (leeres Archiv zulässig) erneut gefahren — diesmal mit
**leerem** `sales-claw-keys` (dem Normalzustand des Projekts, ohne
künstliche Markierung dort), um genau den Fall zu belegen, der mit
Fix-Runde 2 gescheitert wäre: Markierung `markierung-task3-fix3` in
`sales-claw-state`, Sicherung, Löschung, Wiederherstellung mit gelbem
Hinweis auf das leere `keys.tar`, `docker compose ps` wieder `healthy`,
Markierung und `openclaw.json`-Prüfsumme (inkl. Token-Länge und
OpenRouter-Katalogeintrag) vollständig intakt.

Nach Fix-Runde 4 (Manifest und Container-Stopp) erneut vollständig gefahren,
Markierung `markierung-task3-fix4`: Sicherung mit gestopptem Container
(`container_gestoppt: true`), beide Volumes gelöscht — Markierung weg,
`openclaw.json` weg, Container in der Neustart-Schleife (`Restarting (78)`) —,
danach Wiederherstellung mit Manifest-Abgleich (`geprueft: state.tar
(Groesse, Pruefsumme und 39 Eintraege stimmen mit dem Manifest ueberein)`),
`docker compose ps` wieder `Up … (healthy)`, Markierung zurück,
`openclaw.json`-Prüfsumme identisch (`6f089752…`), Gateway-Token-Länge 48,
OpenRouter-Katalogeintrag 1 — alles unverändert.

Die zu diesem Zeitpunkt im Volume liegende WhatsApp-Konfiguration ist reine
Policy (`enabled`, `dmPolicy`, `allowFrom`, …) — noch **keine** Kopplung
(keine Session, kein QR-Pairing). Sie wurde beim Test nicht verändert und ist
nicht Gegenstand dieses Tasks.

## Empfehlung: geplanter täglicher Lauf

`scripts/backup-state.ps1` ohne Parameter aufrufen (Standardziel
`backups/` im Repo, bereits gitignored) — z. B. über die Windows-Aufgaben­planung
oder ein äquivalentes Scheduling auf der Ziel-VM, einmal täglich außerhalb
der Geschäftszeiten. **Der Lauf stoppt den Container für wenige Sekunden**
(gemessen 3,5 s) — das ist der Preis für eine Sicherung, die die
WhatsApp-Sitzung tatsächlich überlebt, und der Grund, den Termin außerhalb
der Geschäftszeiten zu legen. `-OhneStopp` ist kein Betriebsmodus, sondern
ein Notbehelf. Aufbewahrung z. B. 7 tägliche + 4 wöchentliche Archive;
Löschung älterer Sicherungsordner ist bewusst **nicht** Teil dieses Skripts
und sollte separat (Cron/Aufgabenplanung mit Alters-Filter) erfolgen, damit
`backup-state.ps1` selbst niemals löschend wirkt. Sicherungsordner enthalten
Schlüssel und Konfiguration im Klartext-Archiv — Zugriff auf `backups/`
entsprechend einschränken und niemals versionieren (`.gitignore` deckt
`backups/`, `*.tar`, `*.tar.gz` bereits ab).
