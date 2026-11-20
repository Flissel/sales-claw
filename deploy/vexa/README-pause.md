# Vexa-Patch-Abbild `sales-vexa-lite:v0.12.28-pause1`

## Wozu

Die Meeting-Steuerseite (Spec `docs/superpowers/specs/2026-11-20-meeting-steuerseite-design.md`)
braucht **Pause/Weiter** fuer die Mitschrift: In der Pause geht kein Ton an
Whisper, und was ab der Klickzeit schon erkannt war, wird verworfen bzw.
geloescht. Upstream-Vexa (`vexaai/vexa-lite:v0.12.28`) kann das nicht. Statt
eines Forks liegt hier ein **duennes Abbild ueber dem offiziellen**: dieselbe
Basis, nur die Dateien unter `patch/` darueber.

| Teil | Was der Patch tut |
|---|---|
| Bot (`patch/bot/`) | Acts `pause`/`resume`, Pausen-Tor (`pause-gate.ts`): kein Aufruf von Whisper, Stille statt Ton in der Lane, Segmente, die das Pausenfenster beruehren, werden verworfen bzw. zurueckgezogen; Bestaetigung per Lifecycle `aufnahme_pause`. |
| Meeting-API (`patch/meeting-api/`) | `POST /bots/{platform}/{native_meeting_id}/pause` (`{"at_ms": <int>}`) und `/resume`, Pausenzustand in `meeting.data.aufnahme_pause`, Sicherheitsloeschung (DB, Hash, Feed, Bus `transcription_segments`). |
| Gateway (`patch/gateway/`) | Weiterleitung der beiden Routen an die Meeting-API, Scope `bot` in `routes.v1.json`. |

Jede Aenderung in einer Upstream-Datei ist mit `sales-claw pause patch`
markiert. Die Originale stehen unveraendert in eigenen Commits
(`chore(vexa): Originale ...`), so zeigt `git diff <Originale-Commit> HEAD -- deploy/vexa/patch`
genau den Patch.

**Lizenz:** Vexa steht unter Apache-2.0. Die gepatchten Upstream-Dateien haben
keine Lizenzkoepfe (es gab nichts zu erhalten); neue Dateien (`pause-gate.ts`,
`pause_router.py`, die neuen Tests) tragen einen Herkunftshinweis mit
Apache-2.0. Das Abbild traegt `org.opencontainers.image.licenses=Apache-2.0`.

## Bauen und pruefen

```bash
# auf dem Docker-Host, aus einem Test-Checkout (nicht aus ~/sales-claw, solange
# die Umstellung nicht freigegeben ist):
bash deploy/vexa/vexa-pause-bauen.sh
```

Das Skript baut `Dockerfile.pause` (Kontext ist nur `patch/`, die `.env` mit
den Geheimnissen geht nie an den Daemon) und prueft dann in einem
Wegwerf-Container **des neuen Abbilds** (`--network none`, wird immer entfernt):

1. Jede Datei aus `patch/` liegt byteweise gleich an **allen** Zielorten
   (sha256), das Bot-`dist/` ist genau der tsc-Bau der gepatchten Quellen,
   Meeting-API und Gateway importieren mit der supervisord-Umgebung die
   gepatchten Module.
2. Bot: `npm test`, `tsc --noEmit`, `check:isolation`.
3. Meeting-API: `pytest` ohne Postgres (die PG-Tests werden uebersprungen).
4. Gateway: `pytest`.

Erwartet (Stand pause1): Bot 759 ✅ (758 aus `npm test` + 1 Isolation) / 0 ❌, Meeting-API **1458 passed, 5 skipped**,
Gateway **386 passed, 1 xfailed**. Die letzte Zeile ist `ABBILD OK`, sonst
endet das Skript mit Exit != 0. Die Untergrenzen stehen oben im Skript.

## Wo die Dateien im Abbild landen (wichtig)

- **Bot:** Der Starter `/usr/local/bin/vexa-bot-launch` fuehrt
  `node dist/index.js` in `/app/core/meetings/services/bot` aus, also das
  kompilierte `dist/`, nicht `src/`. Das Dockerfile kopiert die Quellen und baut
  mit dem `build`-Skript des Pakets neu (tsc und esbuild sind im Abbild; ohne
  Netz). Der Bau des **ungepatchten** Pakets ergibt `dist/` byteweise gleich dem
  Original, die Werkzeugkette ist also dieselbe.
- **Meeting-API, zwei Kopien:** Laufzeit ist `/app/meeting-api/src`
  (supervisord `PYTHONPATH`), die Tests laufen in
  `/app/core/meetings/services/meeting-api`. `src/` muss an **beide** Orte,
  sonst testet man das eine und startet das andere.
- **Gateway, `app.py` und `routes.v1.json` nur zusammen:** Das Gateway
  verweigert den Start, wenn eine Route aus `app.py` im Manifest fehlt (und
  ohne Manifest-Eintrag antworten neue Routen mit 403/404). Laufzeit:
  `/app/gateway/src/gateway/app.py` + `/app/gateway/core/meetings/routes.v1.json`;
  Test-Baum: `/app/core/gateway/services/gateway/...` + `/app/core/meetings/routes.v1.json`.

Die Zuordnung steht zweimal: in den `COPY`-Zeilen von `Dockerfile.pause` und in
`ziele()` in `vexa-pause-bauen.sh`. Eine neue Datei unter `patch/` ohne
Zielort laesst das Skript abbrechen.

## Auf eine neue Vexa-Version heben

1. Neue Basis ziehen und Digest notieren:
   `docker pull vexaai/vexa-lite:<neu>` → `docker image inspect ... --format '{{index .RepoDigests 0}}'`.
2. Die neuen **Originale** derselben Dateien aus dem Abbild holen (nur lesen,
   Wegwerf-Container, kein Netz), z. B.
   `docker run --rm --network none --entrypoint cat vexaai/vexa-lite:<neu> /app/core/meetings/services/bot/src/pipeline.ts`.
   Pfade wie oben; vorher pruefen, ob Starter (`vexa-bot-launch`) und
   supervisord-Pfade noch dieselben sind.
3. Unseren Patch als Diff sichern
   (`git diff <Originale-Commits> HEAD -- deploy/vexa/patch > pause.diff`),
   die neuen Originale als eigenen Commit `chore(vexa): Originale ... aus vexa-lite <neu>`
   einspielen, dann den Diff wieder anwenden (`git apply -3 pause.diff`) und
   Konflikte von Hand loesen. Neue Dateien (`pause-gate.ts`, `pause_router.py`,
   `test_pause_*.py`) bleiben einfach liegen.
4. `FROM` in `Dockerfile.pause` (Tag + Digest) und das LABEL anpassen, Tag im
   Skript auf `sales-vexa-lite:<neu>-pause1` setzen, Vorgabe in
   `docker-compose.yml` bleibt das Upstream-Abbild.
5. `bash deploy/vexa/vexa-pause-bauen.sh` – erst bei `ABBILD OK` weiter. Haben
   sich die Upstream-Testzahlen geaendert, die Untergrenzen im Skript
   nachziehen (und hier eintragen).
6. Danach wie beim Einschalten (unten) mit Live-Test.

## Einschalten und zurueck (nur mit Felix' OK, Plan Task 9)

`docker-compose.yml` nimmt das Abbild aus `VEXA_LITE_IMAGE`; ohne Variable
bleibt es `vexaai/vexa-lite:v0.12.28@sha256:9eeb...` (Prod unveraendert).

```bash
# in ~/sales-claw/deploy/vexa/.env:
VEXA_LITE_IMAGE=sales-vexa-lite:v0.12.28-pause1
docker compose -f docker-compose.yml -p vexa up -d --no-deps vexa-lite   # nur dieser Dienst
```

Zurueck: Zeile aus der `.env` nehmen, denselben Befehl noch einmal. Das
Patch-Abbild liegt nur lokal (keine Registry) – nach einem neuen Host erst
mit dem Skript bauen.
