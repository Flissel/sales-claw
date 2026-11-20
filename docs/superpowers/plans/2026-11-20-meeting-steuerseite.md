# Meeting-Steuerseite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Waehrend eines Jitsi-Termins auf `/termine/<uid>/live` live Transkript und Bilder sehen und die Aufnahme (Ton + Bild) pausieren/fortsetzen, wobei der Vexa-Bot im Raum bleibt und in der Pause keinen Text erzeugt.

**Architecture:** Ein Patch-Abbild auf `vexaai/vexa-lite:v0.12.28` gibt dem Bot die Acts `pause`/`resume` (kein Ton an Whisper, Ergebnisse ab Klickzeit verworfen/zurueckgezogen) und der Meeting-API Endpunkte dafuer. Unsere Seite schreibt nur den Wunsch in die DB; ein schneller 1-s-Weg in `sales-termine` (einziger Vexa-Sprecher) setzt ihn um, holt live Segmente und bestaetigt; `sales-auge` stoppt Bilder schon ab dem Wunsch.

**Tech Stack:** Python 3 / Starlette / psycopg (sales-mcp), Postgres (provision.sql), TypeScript/Node (`@vexa/bot`, tsx-Tests), Python (Vexa meeting-api), Docker.

**Spec:** `docs/superpowers/specs/2026-11-20-meeting-steuerseite-design.md`

## Global Constraints

- Nur `sales-termine` spricht mit Vexa (Final-Review C1); UI/MCP haben keinen `VEXA_API_KEY`.
- Seiten-CSP ohne Inline-Skript; Skript als Datei ueber gesicherte Route (Vorbild `ui_kalender.csp_kalender`, `static/mitschriften/ziehen.js`). Kein iframe, kein Fremd-Skript.
- Meeting oeffnet per Knopf in eigenem Tab (`target="_blank"`, `rel="noopener"`).
- Reaktionszeit Pause/Weiter/Notbremse: ≤ 2 s (Wunsch → Act an Vexa; Wunsch → `sales-auge` stoppt Bilder).
- Bestaetigung durch den Bot binnen 10 s, sonst Zustand „Pause nicht bestaetigt“ laut auf der Seite + Betreiber-Hinweis.
- Pausenbeginn = Klickzeit; nichts mit Beginn ≥ Klickzeit (bis „Weiter“) darf in Vexa, Live-Ablage, Mitschrift, Briefing, Bericht, Kursmitschrift oder Logs landen.
- Live-Segmente alle 5 s holen; Seite fragt alle 3 s ab.
- Live-Transkript in eigener Ablage, NICHT in `termin_mitschriften`; nach Terminende geleert.
- Pausen nur auf der Akte (aus `termin_pausen`), nicht in Kontakt-Historie/CRM.
- Notbremse: Bot verlaesst Raum ≤ 2 s, Material VOR der Pause bleibt (nicht `aufnahme_beenden`).
- Patch-Abbild: `FROM vexaai/vexa-lite:v0.12.28`, Tag `sales-vexa-lite:v0.12.28-pause1`, Dateien unter `deploy/vexa/`. Vexa-Lizenzhinweise in gepatchten Dateien erhalten.
- Keine Inhalte, keine Namen in Logs (uids nur gehasht via vorhandenes `_h`).
- Tests sales-mcp nur ueber `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh [--provision] <pytest-args>` (Test-DB `meeting_test`, nie zwei Laeufe parallel).
- Alle drei Laeden (`sales`, `sales_ivan`, `sales_sophie`) ueber den Schema-Loop in `db/provision.sql`.

## Review Focus

1. Pause, waehrend der Bot noch in der Lobby wartet (`wartet_auf_einlass`): Wunsch bleibt stehen und wird angewandt, sobald der Bot aktiv ist; Bilder entstehen trotzdem keine. (Test in Task 5)
2. Bot/Vexa startet waehrend einer Pause neu (Bot kennt seine Pause nicht mehr): die Wache sieht Abweichung zwischen Wunsch und Vexa-Zustand und schickt `pause` erneut. (Test in Task 5)
3. Termin endet waehrend einer Pause: offene Pause wird mit `bis = Ende` geschlossen, die finale Mitschrift enthaelt kein Segment aus dem Fenster. (Test in Task 5)
4. Doppelklick / „Pause“ waehrend schon pausiert: idempotent, keine zweite offene Pausenzeile. (Test in Task 4)
5. `/termine/<uid>/live` darf nicht vom Catch-all `/termine/{kennung:path}` geschluckt werden; Lese-Rolle sieht keine Knoepfe, POST ohne Schreibrecht/CSRF wird abgewiesen. (Test in Task 7)

---

### Task 1: Vexa-Bot – Acts `pause`/`resume` und Pausen-Tor

**Files:**
- Create: `deploy/vexa/patch/bot/src/pause-gate.ts`, `deploy/vexa/patch/bot/src/pause-gate.test.ts`
- Modify (Kopien aus dem Abbild, dann gepatcht): `deploy/vexa/patch/bot/src/contracts.ts`, `deploy/vexa/patch/bot/src/orchestrator.ts`, `deploy/vexa/patch/bot/src/pipeline.ts`, `deploy/vexa/patch/bot/package.json` (Testskript um `tsx src/pause-gate.test.ts` erweitern)
- Quelle der Originale: `docker cp vexa-lite:/app/core/meetings/services/bot/src/<datei> …` (auf der VM, Container `vexa-lite`).

**Interfaces:**
- Produces (Act-Kontrakt): `{ action: 'pause'; at: number }` (epoch ms, Klickzeit) und `{ action: 'resume' }` in `Act`/`ACT_ACTIONS`.
- Produces (Lifecycle): Bot meldet nach Anwenden ein Lifecycle-Ereignis ueber den vorhandenen `lifecycle-http`-Adapter mit `data.aufnahme_pause = { pausiert: boolean, seit_ms: number | null }`.
- Produces (`pause-gate.ts`): `class PauseGate { pause(atMs: number): void; resume(): void; get pausedSince(): number | null; allowsAudio(): boolean; allowsSegment(startEpochS: number): boolean }`.

- [ ] **Step 1:** Originale holen, Testbefehl pruefen: `ssh offload-vm 'docker exec vexa-lite sh -c "cd /app/core/meetings/services/bot && pnpm test"'` (oder `npm test`). Expected: bestehende Bot-Tests gruen. Ergebnis + genauer Befehl in den Ledger.
- [ ] **Step 2: Failing tests `pause-gate.test.ts`** (tsx, Stil der Nachbartests):
  - `pause(1000)`: `allowsAudio()` false, `allowsSegment(0.999)` true, `allowsSegment(1.0)` false, `allowsSegment(5)` false.
  - nach `resume()`: `allowsAudio()` true, `allowsSegment(5)` true; Segmente mit Beginn im Fenster [1.0, Resume-Zeit) bleiben verboten (`allowsSegment(1.5)` false, wenn Resume bei 3000 ms).
  - `pause` zweimal: `pausedSince` bleibt die erste Klickzeit.
  - `pipeline`-Test: mit Mock-Transcribe wird waehrend Pause `transcribe` nicht aufgerufen; ein Ergebnis eines VOR der Pause gestarteten Aufrufs mit `start ≥ at` wird nicht `publish`t; bereits publizierte Segmente mit `start ≥ at` werden per `sink.retract([...ids])` zurueckgezogen.
  - `orchestrator`-Test: Act `{action:'pause', at}` ruft Gate auf und emittiert Lifecycle mit `aufnahme_pause.pausiert === true`; unbekannte Felder werden ignoriert.
- [ ] **Step 3:** Tests laufen lassen (im Abbild von Task 3 oder per `docker cp` + `tsx` im laufenden Container in einem Wegwerf-Verzeichnis). Expected: FAIL (Modul/Act fehlt).
- [ ] **Step 4:** Implementieren: Gate an der stt-Naht (`Transcribe`-Wrapper: in Pause kein Aufruf, leeres Ergebnis) und im Sink-Adapter (`forward`: `allowsSegment(seg.start)` sonst verwerfen; gemerkte IDs publizierter Segmente der letzten 30 s mit `start ≥ at` → `retract`). Gilt fuer zoom/jitsi-Lane (mixed) und gmeet-Lane gleich.
- [ ] **Step 5:** Tests gruen, gesamtes `test`-Skript gruen.
- [ ] **Step 6: Commit** `feat(vexa): Bot-Acts pause/resume mit Pausen-Tor`

### Task 2: Vexa-Meeting-API – Pause-Endpunkte, Zustand, Sicherheitsloeschung

**Files:**
- Modify (Kopien aus dem Abbild, gepatcht) unter `deploy/vexa/patch/meeting-api/…` – zuerst feststellen, welcher Pfad zur Laufzeit importiert wird (`/opt/venvs/meeting/bin/python -c "import meeting_api,sys;print(meeting_api.__file__)"`), nur diesen patchen.
- Neue Tests neben den vorhandenen (`tests/test_pause_route.py`, Stil `test_stop_route.py`).

**Interfaces:**
- Produces: `POST /bots/{platform}/{native_meeting_id}/pause` Body `{"at_ms": int}` → 202; publiziert `{"action":"pause","at":at_ms,"meeting_id":id}` auf `leave_command_channel(meeting_id)`; loescht aus `transcriptions` (und der Redis-Live-Ablage, falls vorhanden) alle Segmente dieses Meetings mit Beginn ≥ `at_ms`.
- Produces: `POST /bots/{platform}/{native_meeting_id}/resume` → 202; publiziert `{"action":"resume","meeting_id":id}`.
- Produces: Lifecycle-Ereignis mit `aufnahme_pause` wird in `meeting.data["aufnahme_pause"]` gespeichert; `GET /meetings/{id}` liefert es.
- Auth wie `DELETE /bots/...` (API-Key, eigener Nutzer); 404 fuer fremdes/unbekanntes Meeting.

- [ ] **Step 1: Failing tests:** publiziertes Payload exakt wie oben; 404 fremdes Meeting; Segmente mit `start ≥ at` geloescht, aeltere bleiben; Lifecycle mit `aufnahme_pause` landet in `data`.
- [ ] **Step 2:** FAIL bestaetigen (Testbefehl des Pakets, im Ledger festhalten).
- [ ] **Step 3:** Implementieren (Muster `lifecycle/stop.py` + `stop_router.py`).
- [ ] **Step 4:** Tests gruen, Paket-Tests gruen.
- [ ] **Step 5: Commit** `feat(vexa): Meeting-API pause/resume und Pausenzustand`

### Task 3: Patch-Abbild bauen

**Files:**
- Create: `deploy/vexa/Dockerfile.pause` (`FROM vexaai/vexa-lite:v0.12.28`; Patch-Dateien an die Originalpfade kopieren; Bot-Paket neu bauen mit dessen `build`-Skript; falls die Werkzeugkette im Abbild fehlt: `dist/` vorab bauen und mitkopieren – Entscheid im Ledger), `deploy/vexa/vexa-pause-bauen.sh` (baut `sales-vexa-lite:v0.12.28-pause1` und laesst Bot- + Meeting-API-Tests IM Abbild laufen), `deploy/vexa/README-pause.md` (Wozu, Update-Weg: Patch auf neue Version anwenden + Tests).
- Modify: `deploy/vexa/docker-compose.yml` – Abbild ueber Variable `VEXA_LITE_IMAGE` mit Vorgabe `vexaai/vexa-lite:v0.12.28` (Prod bleibt unveraendert, bis Task 9 umstellt).

- [ ] **Step 1:** `ssh offload-vm 'cd ~/meeting-test/src/deploy/vexa && bash vexa-pause-bauen.sh'` (Quelle per `vm_test.sh`-Sync). Expected: Abbild gebaut, beide Testlaeufe gruen, Ausgabe endet mit `ABBILD OK`.
- [ ] **Step 2:** `docker compose config` mit und ohne `VEXA_LITE_IMAGE` zeigt das jeweils richtige Abbild.
- [ ] **Step 3: Commit** `build(vexa): Patch-Abbild sales-vexa-lite pause1`

### Task 4: DB und Akten-Funktionen

**Files:**
- Modify: `db/provision.sql` (Schema-Loop, Rechte wie `termin_bilder`)
- Modify: `sales-mcp/termin_akte.py`
- Test: `sales-mcp/tests/test_termin_pause.py`

**Interfaces:**
- `termin_akten`: `aufnahme_wunsch text not null default 'an' check (aufnahme_wunsch in ('an','pause','notbremse'))`, `aufnahme_wunsch_am timestamptz null`, `aufnahme_pausiert_seit timestamptz null`, `aufnahme_pause_fehler text null`.
- `termin_pausen(id bigserial pk, uid text not null references termin_akten(uid) on delete cascade, von timestamptz not null, bis timestamptz null, angefordert_von text not null, bestaetigt_am timestamptz null)`; Index `(uid, von)`; hoechstens eine offene Zeile je uid (partieller Unique-Index `where bis is null`).
- `termin_live_segmente(uid text references termin_akten(uid) on delete cascade, segment_id text, beginn timestamptz not null, sprecher text, text text not null, primary key (uid, segment_id))`.
- `termin_akte.aufnahme_wuenschen(uid: str, wunsch: str, wer: str, jetzt: datetime) -> bool` – setzt Wunsch; bei `'pause'` legt es (idempotent) die offene `termin_pausen`-Zeile mit `von = jetzt` an; bei `'an'` schliesst es sie (`bis = jetzt`); nur fuer Akten in `wartet_auf_einlass`/`laeuft`, sonst False.
- `termin_akte.pausen(uid: str) -> list[dict]` (von, bis, angefordert_von, bestaetigt_am; sortiert).
- `termin_akte.in_pause(beginn: datetime, pausen: list[dict]) -> bool` (von ≤ beginn < bis, offene Pause = unendlich).

- [ ] **Step 1: Failing tests:** `test_pause_legt_eine_offene_zeile_an`, `test_pause_doppelt_bleibt_eine_zeile` (Review Focus 4), `test_weiter_schliesst_die_pause`, `test_wunsch_nur_bei_laufender_akte`, `test_in_pause_grenzen` (von inklusive, bis exklusiv, offen = unendlich).
- [ ] **Step 2:** `bash …/vm_test.sh --provision tests/test_termin_pause.py -q` → FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Gleicher Befehl → PASS.
- [ ] **Step 5: Commit** `feat(termine): Pausen-Wunsch, Pausenzeilen, Live-Ablage`

### Task 5: `vexa.py` + schneller Weg in `sales-termine`

**Files:**
- Modify: `sales-mcp/vexa.py`
- Create: `sales-mcp/termin_pause.py`
- Modify: `sales-mcp/termin_takt.py` (`main()` startet den schnellen Weg als Thread; `_mitschrift_ablegen` filtert Pausenfenster; nach `fertig` Live-Ablage leeren)
- Test: `sales-mcp/tests/test_vexa.py` (erweitern), `sales-mcp/tests/test_termin_pause_wache.py`

**Interfaces:**
- `vexa.pause_setzen(plattform: str, native_id: str, ab: datetime | None) -> None` (`ab` gesetzt → POST …/pause mit `at_ms`; `None` → POST …/resume); `VexaFehler` bei Fehler.
- `vexa.pause_zustand(meeting_id: int) -> dict | None` – `data["aufnahme_pause"]` aus `GET /meetings/{id}`.
- `termin_pause.wache_runde(jetzt: datetime) -> int` – fuer Akten mit Vexa-Ids in `wartet_auf_einlass`/`laeuft`: Wunsch ≠ bestaetigter Vexa-Zustand → Act senden (Pause mit `ab = aufnahme_wunsch_am`); bestaetigt → `aufnahme_pausiert_seit`/`termin_pausen.bestaetigt_am` setzen bzw. leeren; > 10 s unbestaetigt → `aufnahme_pause_fehler = 'nicht_bestaetigt'` + Betreiber-Hinweis (einmal je Pause, Muster `betreiber_hinweis.senden`); `notbremse` → `vexa.bot_stoppen` sofort. Rueckgabe: Anzahl gesendeter Acts.
- `termin_pause.live_runde(jetzt: datetime) -> int` – fuer laufende Akten Segmente holen und in `termin_live_segmente` upserten, Segmente `in_pause` nie.
- Thread: Schleife mit `_STOPP.wait(1.0)`, `wache_runde` jede Sekunde, `live_runde` alle 5 s; Fehler je Runde loggen (ohne Inhalte), Thread stirbt nie.

- [ ] **Step 1: Failing tests (`test_vexa.py`):** `pause_setzen` sendet exakt `POST /bots/jitsi/<id>/pause` mit `{"at_ms": …}` bzw. `/resume`; `pause_zustand` liest `data.aufnahme_pause`.
- [ ] **Step 2: Failing tests (`test_termin_pause_wache.py`, Vexa gefakt):** `test_wunsch_pause_sendet_act_mit_klickzeit`; `test_bestaetigung_setzt_pausiert_seit`; `test_ohne_bestaetigung_nach_10s_fehler_und_ein_hinweis`; `test_lobby_wunsch_wird_nach_aktivierung_gesendet` (Review Focus 1: Akte `wartet_auf_einlass` ohne Vexa-Ids → nichts; mit Ids → Act); `test_vexa_neustart_schickt_pause_erneut` (Review Focus 2: Wunsch `pause`, Vexa-Zustand `pausiert:false` → erneut senden); `test_notbremse_stoppt_bot_sofort_und_behaelt_live_segmente`; `test_live_runde_laesst_pausensegmente_weg`; `test_ende_waehrend_pause_schliesst_pause_und_mitschrift_ohne_fenster` (Review Focus 3, ueber `_mitschrift_ablegen`).
- [ ] **Step 3:** `bash …/vm_test.sh tests/test_vexa.py tests/test_termin_pause_wache.py -q` → FAIL.
- [ ] **Step 4:** Implementieren.
- [ ] **Step 5:** Gleicher Befehl + `tests/test_termin_takt.py tests/test_termin_takt_kurs.py` → PASS.
- [ ] **Step 6: Commit** `feat(termine): schneller Pausenweg und Live-Transkript in sales-termine`

### Task 6: `sales-auge` pausiert Bilder ab dem Wunsch

**Files:**
- Modify: `sales-mcp/bildschirm.py` (`ist_pausiert(uid: str) -> bool`: `aufnahme_wunsch <> 'an'`), `sales-mcp/auge.py` (`_eine`: bei Pause kein Bild aufnehmen, Sitzung bleibt offen; `notbremse` → Sitzung beenden)
- Test: `sales-mcp/tests/test_auge.py` (erweitern)

- [ ] **Step 1: Failing tests:** `test_pause_wunsch_nimmt_kein_bild_auf_bleibt_im_raum`; `test_nach_weiter_wieder_bilder`; `test_notbremse_verlaesst_raum`.
- [ ] **Step 2:** `bash …/vm_test.sh tests/test_auge.py -q` → FAIL.
- [ ] **Step 3:** Implementieren (Pruefung je Runde, Runde = 2 s → ≤ 2 s).
- [ ] **Step 4:** PASS (auch `tests/test_auge_pdf.py`).
- [ ] **Step 5: Commit** `feat(auge): keine Bilder waehrend der Aufnahmepause`

### Task 7: Steuerseite `/termine/<uid>/live`

**Files:**
- Create: `sales-mcp/ui_termin_live.py`, `sales-mcp/static/termine/live.js`
- Modify: `sales-mcp/ui_termin.py` (Link „Live-Ansicht“ im Kopf, solange `wartet_auf_einlass`/`laeuft`; Mitschrift und Bildschirm-Ansicht zeigen Pausen als Zeile „Pause HH:MM–HH:MM“ aus `termin_akte.pausen`; im Kopf der Akte eine Liste „Pausen“ mit von/bis und wer), `sales-mcp/ui.py` (Routen von `ui_termin_live` VOR den Catch-all-Routen von `ui_termin` einhaengen; CSS fuer Zustandsanzeige)
- Test: `sales-mcp/tests/test_ui_termin_live.py`

**Interfaces:**
- `GET /termine/{uid}/live` – HTML; CSP `ui_kalender.csp_kalender(ui)`; ein `<script src="/termine/live.js" defer>`; Knopf „Meeting öffnen ↗“ (`target="_blank" rel="noopener"`, nur wenn Link gueltig nach `_link_ok`).
- `GET /termine/{uid}/live.json` → `{"zustand": "an"|"wird_pausiert"|"pausiert"|"wird_fortgesetzt"|"nicht_bestaetigt"|"notbremse", "pausiert_seit": iso|null, "segmente": [{"beginn","sprecher","text"}], "pausen": [{"von","bis"}], "bilder_anzahl": int}`.
- `POST /termine/{uid}/live` Formfeld `aktion` ∈ {`pause`,`weiter`,`notbremse`} + CSRF → `termin_akte.aufnahme_wuenschen` → 303 zurueck auf die Live-Seite.
- `GET /termine/live.js` – Skriptdatei (no-cache, nosniff); fragt alle 3 s `live.json` ab, rendert Zustand gross („● Aufnahme läuft“ / „⏸ Pausiert seit HH:MM“ / „⚠ Pause nicht bestätigt – Notbremse?“), Transkript mit Pausenzeilen, Bilderzahl; Knoepfe per verstecktem Formular; kein `console.log`.

- [ ] **Step 1: Failing tests:** `test_live_route_nicht_vom_catchall_geschluckt` (Review Focus 5); `test_lesen_ohne_knoepfe`; `test_post_ohne_csrf_abgewiesen`; `test_post_pause_setzt_wunsch`; `test_json_zeigt_wird_pausiert_bis_bestaetigt`; `test_json_nicht_bestaetigt`; `test_meeting_knopf_neuer_tab_rel_noopener`; `test_genau_ein_script_csp_self`; `test_mitschrift_zeigt_pausenzeile_ohne_inhalt`.
- [ ] **Step 2:** `bash …/vm_test.sh tests/test_ui_termin_live.py tests/test_ui_termin.py -q` → FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** PASS; dazu die UI-Dateien `tests/test_ui.py tests/test_seitenleiste.py tests/test_ui_kalender.py`.
- [ ] **Step 5: Commit** `feat(termine): Live-Steuerseite mit Pause, Weiter, Notbremse`

### Task 8: Gesamtsuite

- [ ] **Step 1:** `bash …/vm_test.sh --provision -q` (volle Suite). Expected: alles gruen ausser bekannter Test-DB-Drift (`video_uebergabe` fehlt in `meeting_test` – vorher `db/video-uebergabe.sql` in `sales_test` einspielen, dann gruen). Ergebnis in den Ledger.

### Task 9: Rollout (nur mit Felix' OK, nach finishing-a-development-branch)

- [ ] **Step 1:** Claim `cc-meeting-steuerseite` in `00_Meta/002_Koordination_Live.md` (secondbrain), committen.
- [ ] **Step 2:** Fenster ohne Bot-Termine in `sales`, `sales_ivan`, `sales_sophie` (naechste 2 h) pruefen.
- [ ] **Step 3:** Patch-Abbild auf der VM bauen (Task 3), `provision.sql` einspielen, Push + `deploy/update.sh`.
- [ ] **Step 4:** `vexa-lite` mit `VEXA_LITE_IMAGE=sales-vexa-lite:v0.12.28-pause1` gezielt neu erzeugen (nur dieser Dienst). Test-Jitsi-Raum am Selbsttest-Kontakt anlegen, Bot rein, sprechen → Text; Pause → 30 s sprechen → kein Segment in Vexa und Live-Ablage (auch nicht aus den ersten Sekunden); Weiter → Text; Bildschirm teilen in Pause → 0 Bilder. Bei Fehler sofort zurueck auf `vexaai/vexa-lite:v0.12.28`.
- [ ] **Step 5:** Ergebnis an Felix, Claim schliessen.
