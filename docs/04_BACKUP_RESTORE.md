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
damit niemand versehentlich in ein offenes Volume schreibt. Es leert beide
Ziel-Volumes vollständig und spielt die tar-Archive aus der Quelle ein.
Anschließend `docker compose up -d`.

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
