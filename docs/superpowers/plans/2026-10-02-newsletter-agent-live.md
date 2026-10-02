# Newsletter-Agent live – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Gestaltungs-Agent schreibt live mit (jede fertige Änderung sofort im Editor sichtbar), die nächste Nachricht lässt sich vormerken, ein Stopp bricht ab – über eine eigene, gestreamte Modell-Tür des Marketing-Claws.

**Architecture:** Eigener Shim `claw/shim/marketing_shim.py` (Kopie des geteilten Shims, plus echtes SSE-Streaming aus `claude -p --output-format stream-json --include-partial-messages`) auf :8117. Der Chat-Arbeiter liest den Stream mit einem inkrementellen Leser (`claw/agent_strom.py`), wendet jede vollständige Änderung an und schickt gedrosselte Zwischenstände an die VM (`chat_auftraege.zwischenstand`, Migration 061). Der Editor zeigt den Zwischenstand live, Vormerken/Stopp laufen über neue Pult-Routen.

**Tech Stack:** Python 3.11/3.12 (http.server-Shim, FastAPI, urllib), PostgreSQL plpgsql, Starlette (sales-ui), React 18 + MUI 5 + zustand, vitest.

**Spec:** `docs/superpowers/specs/2026-10-02-newsletter-agent-live-design.md` (sales-claw)

## Repos und Arbeitsorte

- **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (Branch `master`), Pfade relativ zu `spaces/marketing/`. NIE im Haupt-Checkout committen; fremde Dirty-Dateien nicht anfassen.
- **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (Branch `feat/stufe-1-fundament`); `.superpowers/` nie stagen.
- Vor jedem Commit `git rev-parse --show-toplevel` + `git branch --show-current` prüfen; Git über PowerShell; kein stash/push.
- MOS-Tests: `$env:SALES_CLAW_DIR="<SC>"; C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces/marketing/<pfad> -q -p no:cacheprovider` (bekannt unabhängig rot: test_integrations, test_send_paranoid, test_hand_bridge, test_cockpit_contract).
- SC-Tests: Postgres :55432 (bash `nohup pg_ctl … start`, danach `stop -m immediate`), `SALES_DB_SCHEMA=sales_test`, venv-sales; Editor `npx vitest run`, `npx tsc --noEmit`, `npm run build` im Ordner `editor/`, Bundle mit-committen.
- Migration nur per `python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/061_chat_live.sql spaces/marketing/db/verify_061.sql` (ROLLBACK) – anwenden erst in Task 8.
- Bekannte Falle: in SQL über `sync/_db` keinen Spaltennamen `t` verwenden (JSON-Wrapper aliasiert `t`).

## Global Constraints

- Kein Modell auf der VM. Claude nur am PC über den eigenen Marketing-Shim :8117. Der geteilte Shim `~/.local/bin/claude_code_openai_shim.py` und :8114 werden NICHT angefasst.
- Marketing-Shim: gleiche Routen und Nicht-Stream-Antworten wie bisher; `stream: true` ⇒ OpenAI-SSE `chat.completion.chunk` mit `delta.content` je Text-Stück, Abschluss `finish_reason: "stop"` + `data: [DONE]`; CLI-Fehler ⇒ letzter Chunk `finish_reason: "error"` mit Meldung im `delta.content`.
- Jede Änderung darf ein Feld `schritt` (String ≤ 80 Zeichen) tragen; der Prompt verlangt es; `anwenden` akzeptiert und ignoriert es.
- Zwischenstand: höchstens 1×/s (letzter Stand vor `fertig` immer), Größe ≤ 256 KB, nie gespeichert als Fassung, nicht vom Validator geprüft; nach `fertig`/`fehler`/Stopp geleert.
- Vormerken: höchstens ein `wartet`-Auftrag je Inhalt, erneutes Vormerken ersetzt den Text; Freigabe `wartet`→`offen` nur nach `fertig`; nach `fehler`/Stopp bleibt er `wartet` (Start/Verwerfen von Hand); `wartet` sperrt das Handspeichern nicht.
- Stopp: `behalten` | `verwerfen`; Arbeiter erfährt es beim Zwischenstand (`{weiter:false, grund:"stopp"}`); Behalten ⇒ letzter Zwischenstand wird Fassung (Urheber `agent`, Notiz „gestoppt nach Schritt N“) mit Flächen-Rechnen + Validator, ungültig ⇒ wie Verwerfen mit Hinweis; VM schließt nach 15 s selbst ab.
- Editor: 1-s-Abfrage nur während eines Laufs; Hervorhebung ≤ 600 ms in Akzent `#5b8cff`; Schritt-Zeile „Schritt N · <schritt>“; Sperre bleibt; Stil wie das Gestaltungsfenster.

## Review Focus

1. Claude schreibt ein `}` oder `]` innerhalb eines Strings, oder ein Chunk endet mitten in `\"` → der inkrementelle Leser meldet eine Änderung erst, wenn sie wirklich vollständig ist (Test in Task 3).
2. Stopp kommt, während der Arbeiter gerade im Korrekturversuch ist oder zwischen zwei Zwischenständen → Stopp gewinnt, keine Fassung bei „verwerfen“, keine doppelte Fassung bei „behalten“ (Tests in Task 4 und 5).
3. Der Arbeiter stirbt mitten im Lauf → nach Vergabeablauf läuft die bestehende Wiederholungslogik; ein gesetzter Stopp wird nach 15 s von der VM abgeschlossen (verify_061 in Task 2, API-Test in Task 4).
4. Vormerken während kein Lauf aktiv ist → die Nachricht startet sofort als normaler Auftrag statt `wartet` (Test in Task 2/4).
5. Shim-Stream bricht nach der Hälfte ab (CLI stirbt) → Arbeiter behandelt es wie einen Shim-Fehler (Wiederholung bis 3 min), Live-Stand bleibt beim letzten gültigen Schritt (Test in Task 5).

---

### Task 1: Eigener Marketing-Shim mit echtem Streaming (MOS)

**Files:**
- Create: `claw/shim/marketing_shim.py` (Kopie von `C:\Users\User\.local\bin\claude_code_openai_shim.py`, Kopfkommentar: „Kopie vom 02.10.2026 aus ~/.local/bin/claude_code_openai_shim.py; gehört ab jetzt dem Marketing-Claw“)
- Modify: `claw/scripts/marketing-dienste-starten.ps1` (Eintrag `marketing_claw_shim`: Args auf `(Join-Path $SpaceRoot 'claw\shim\marketing_shim.py')`, sonst unverändert)
- Test: `claw/shim/tests/test_marketing_shim.py` (+ `claw/shim/tests/__init__.py`, `claw/shim/tests/falsche_cli.py`)

**Interfaces:**
- Produces: `marketing_shim.stream_argv(cli, model, ...) -> list[str]` (fügt `--output-format stream-json --include-partial-messages --verbose` statt `json` ein); `marketing_shim.text_stuecke(zeilen: Iterable[str]) -> Iterator[str]` (aus stream-json-Zeilen: für `{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":...}}}` den Text; ignoriert alles andere; wirft `ShimError` bei `{"type":"result","is_error":true}`); im Handler `stream: true` ⇒ `subprocess.Popen(..., stdout=PIPE, text=True, encoding="utf-8")`, je Stück sofort ein SSE-Chunk + `flush()`.
- Env/Optionen/Prompt-Aufbau identisch zur Kopie (gleiches `render_messages`, gleiche Umgebungsbereinigung, `SHIM_EXTRA_MCP_CONFIG`, `SHIM_NEUTRALIZE_DOUBLE_BRACKETS`).

- [ ] **Step 1: Kopie anlegen** (byte-identisch) und Kopfkommentar ergänzen; bestehende Nicht-Stream-Logik nicht verändern.
- [ ] **Step 2: Failing tests**
  - `text_stuecke` über fest kodierte Zeilen (aus einem echten Lauf, siehe unten) liefert `["eins", " zwei", " drei"]`; `result` mit `is_error: true` ⇒ `ShimError`; unbekannte/kaputte Zeilen werden übersprungen.
  - End-to-End: Shim-Server auf freiem Port starten mit `CLAUDE_CODE_CLI=<python falsche_cli.py>` (die falsche CLI gibt bei `stream-json` drei Delta-Zeilen mit 50 ms Pause und eine `result`-Zeile aus, bei `json` ein normales JSON-Ergebnis). Anfrage `stream: true` ⇒ mindestens 3 `data:`-Chunks, Reihenfolge stimmt, letzter `[DONE]`, der erste Chunk kommt an, bevor die CLI fertig ist (Zeitstempel). Ohne `stream` ⇒ eine normale `chat.completion` wie bisher.
  - CLI-Exit ≠ 0 im Stream ⇒ letzter Chunk `finish_reason: "error"`.
  - Beispielzeilen (gekürzt, echtes Format): `{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"eins"}}}` und `{"type":"result","subtype":"success","is_error":false,"result":"eins zwei drei"}`.
- [ ] **Step 3: Run – FAIL. Step 4: implementieren. Step 5: Run – PASS** (prüfen, wie die Kopie `CLAUDE_CODE_CLI` auflöst; die falsche CLI muss als Kommando mit Python-Interpreter startbar sein – notfalls eine `.cmd`-Hülle im tmp-Ordner).
- [ ] **Step 6: Commit** – `feat(marketing): eigener Marketing-Shim mit echtem Streaming`.

### Task 2: Migration 061 – Zwischenstände, Vormerken, Stopp (MOS)

**Files:**
- Create: `db/061_chat_live.sql`, `db/verify_061.sql`

**Interfaces:**
- Produces (SQL, alle idempotent):
  - `chat_auftraege`: Spalten `zwischenstand jsonb`, `schritt text NOT NULL DEFAULT ''`, `schritt_nr int NOT NULL DEFAULT 0`, `zwischen_am timestamptz`, `stopp text CHECK (stopp IS NULL OR stopp IN ('behalten','verwerfen'))`, `stopp_am timestamptz`; Status-Check erweitert um `wartet`; zusätzlicher Unique-Index `(inhalt) WHERE status = 'wartet'`. Der bestehende Unique-Index für `offen|in_arbeit` bleibt.
  - `marketing.pult_chat_vormerken(p_inhalt uuid, p_nachricht text, p_kontext jsonb) RETURNS jsonb` – läuft gerade nichts (`offen|in_arbeit`) ⇒ wie `pult_chat_anlegen(..., 'chat', ...)` und `{id, status:'offen'}`; sonst Insert/Update des einen `wartet`-Auftrags ⇒ `{id, status:'wartet'}`. Gleiche Prüfungen wie `pult_chat_anlegen` (Newsletter-Entwurf, Nachricht 1..2000).
  - `marketing.pult_chat_vormerkung_loeschen(p_inhalt uuid) RETURNS boolean`.
  - `marketing.pult_chat_vormerkung_starten(p_inhalt uuid) RETURNS uuid` – `wartet`→`offen` (nur wenn nichts läuft; sonst Fehler „Der Assistent arbeitet gerade“), `erstellt_am = now()`.
  - `marketing.pult_chat_zwischenstand(p_auftrag uuid, p_bloecke jsonb, p_schritt text, p_nr int, p_frist interval) RETURNS jsonb` – nur bei `in_arbeit` mit gültiger Vergabe (sonst `{weiter:false, grund:'verloren'}`); `stopp IS NOT NULL` ⇒ `{weiter:false, grund:'stopp', stopp:<wert>}` (Zwischenstand trotzdem speichern); sonst speichern (`length(p_bloecke::text) <= 262144`, sonst Fehler „Zwischenstand zu groß“), Vergabe verlängern, `{weiter:true}`.
  - `marketing.pult_chat_stoppen(p_inhalt uuid, p_art text) RETURNS jsonb` – setzt `stopp`, `stopp_am` am laufenden Auftrag; `offen` (noch nicht abgeholt) ⇒ sofort `fehler` mit Antwort „Gestoppt, bevor der Assistent begonnen hat“ und `{abgeschlossen:true}`; sonst `{abgeschlossen:false, id}`.
  - `pult_chat_fertig` (aus 060) wird in 061 ersetzt: gleiches Verhalten + am Ende `zwischenstand=NULL, schritt=''`; und danach Freigabe eines `wartet`-Auftrags desselben Inhalts (`wartet`→`offen`, `erstellt_am=now()`).
  - `pult_chat_zurueck` (aus 060) ersetzt: + Zwischenstand leeren; KEINE Freigabe.
  - `marketing.pult_chat_stopp_faellig() RETURNS SETOF uuid` – Aufträge `in_arbeit` mit `stopp_am < now() - interval '15 seconds'` (die API schließt sie ab, weil Behalten Flächen rechnen muss).
  - `marketing.pult_chat_stopp_abschliessen(p_auftrag uuid, p_bloecke jsonb, p_hinweis text) RETURNS jsonb` – `p_bloecke` NULL ⇒ `fehler` „Gestoppt – nichts übernommen“; sonst `pult_bloecke_speichern(..., 'agent', false)` + `fertig` mit Antwort „Gestoppt nach Schritt N – bisherige Schritte übernommen“ + Notiz in `ergebnis`; leert Zwischenstand; KEINE Freigabe der Vormerkung.
  - `pult_chat_aufraeumen` (060) unverändert lassen, aber ein `in_arbeit` mit `stopp` wird dort NICHT requeued (sonst würde ein gestoppter Auftrag neu starten) – den Requeue-Zweig um `AND stopp IS NULL` ergänzen (Funktion in 061 neu definieren).
- [ ] **Step 1: verify_061.sql** mit Asserts: Vormerken ohne Lauf ⇒ `offen`; mit Lauf ⇒ `wartet`; zweites Vormerken ersetzt (ein Datensatz); `wartet` blockiert `pult_bloecke_speichern(..,'betreiber',..)` NICHT; Zwischenstand speichert und verlängert; Stopp setzt `weiter:false`; `fertig` leert Zwischenstand und gibt die Vormerkung frei; `zurueck` gibt nicht frei; `stopp_abschliessen` mit Blöcken ⇒ neue Fassung Urheber `agent`, ohne ⇒ keine Fassung; `stopp_faellig` findet einen auf `now()-20s` gesetzten Stopp; Stopp auf `offen` ⇒ sofort `fehler`; Requeue überspringt gestoppte Aufträge. Ende `SELECT 'verify_061 ok'`.
- [ ] **Step 2: Probe – FAIL. Step 3: 061 schreiben. Step 4: Probe (060+061 sind live bzw. jetzt) – `verify_061 ok`.** Zusätzlich `verify_060` mit 061 zusammen in einer Probe laufen lassen (`migration_probe 061 verify_060 verify_061`) – beide ok.
- [ ] **Step 5: Commit** – `feat(marketing): Migration 061 Live-Zwischenstaende, Vormerken und Stopp`.

### Task 3: Schritt-Feld und inkrementeller Leser (MOS, rein)

**Files:**
- Create: `claw/agent_strom.py`, `claw/tests/test_agent_strom.py`
- Modify: `claw/agent_werkzeuge.py` (`schritt` in jedem Werkzeug als optionaler Schlüssel: String ≤ 80, sonst `WerkzeugFehler`), `claw/agent_prompt.py` (SYSTEM: jede Änderung beginnt mit `"schritt": "<was du gerade tust, ≤ 80 Zeichen, Deutsch>"`; Reihenfolge der Änderungen so, dass sie einzeln Sinn ergeben – zuerst Struktur, dann Inhalt, dann Feinschliff), Tests dazu.

**Interfaces:**
- Produces:
```python
class StromLeser:
    """Füttert Text-Stücke; liefert jede vollständige Änderung aus "aenderungen" genau einmal."""
    def __init__(self): ...
    def futter(self, stueck: str) -> list[dict]   # neue vollständige Änderungen (geparst)
    @property
    def text(self) -> str                          # gesamter bisheriger Text (für antwort_lesen am Ende)
```
- Verhalten: ignoriert Text vor dem ersten `{` und Codezäune; findet den Schlüssel `"aenderungen"` im obersten Objekt und das folgende `[`; zählt Tiefe nur außerhalb von Strings (mit `\"`-Escapes über Chunk-Grenzen); jedes Element auf Tiefe 1 des Arrays wird beim schließenden `}` als JSON geparst und ausgegeben; ein nicht parsebares Element ⇒ wird übersprungen und in `fehler: list[str]` gemerkt (der Arbeiter macht dann am Ende den Korrekturversuch über `antwort_lesen`).
- [ ] **Step 1: Failing tests** (`test_agent_strom.py`): ganzer Text in einem Stück ⇒ alle Änderungen; Zeichen für Zeichen gefüttert ⇒ dieselben Änderungen in derselben Reihenfolge; `"text": "a } b ] c"` und `"text": "er sagte \"hi\""` über Chunk-Grenzen; Codezaun + Vortext; zwei Änderungen in einem Stück; `antwort` NACH `aenderungen` im Objekt; leeres Array; Element ohne schließende Klammer bis zum Ende ⇒ nichts ausgegeben. `test_agent_werkzeuge`: `schritt` wird akzeptiert und verändert das Ergebnis nicht; `schritt` 81 Zeichen ⇒ Fehler. `test_agent_prompt`: SYSTEM enthält `"schritt"` und die Reihenfolge-Regel.
- [ ] **Step 2–4: FAIL → implementieren → PASS.**
- [ ] **Step 5: Commit** – `feat(marketing): Schritt-Feld und inkrementeller Leser fuer den Live-Agenten`.

### Task 4: API – Zwischenstand, Vormerken, Stopp (MOS)

**Files:**
- Modify: `api/chat.py`, Test `tests/test_chat_api.py`

**Interfaces:**
- Consumes: SQL aus Task 2; `gestaltungen_rechnen`, `pult_bloecke_fehler`, `schoenheit` wie in `/fertig`.
- Produces:
  - Arbeiter: `POST /api/chat/arbeiter/{aid}/zwischenstand {bloecke: dict, schritt: str ≤ 80, nr: int ≥ 0}` → `{weiter: bool, grund?: "stopp"|"verloren", stopp?: "behalten"|"verwerfen"}`; Body ≤ 300 KB (Content-Length + gekappt lesen).
  - Arbeiter: `POST /api/chat/arbeiter/{aid}/gestoppt {bloecke|null}` → schließt einen gestoppten Auftrag ab: bei `behalten` und gültigen Blöcken (Flächen rechnen + Validator) ⇒ `pult_chat_stopp_abschliessen(aid, bloecke, hinweis)`, sonst mit NULL; Antwort `{status, fassung?}`.
  - Pult: `PUT /api/pult/inhalte/{iid}/chat/vormerkung {nachricht, kontext}` → `{id, status}`; `DELETE …/chat/vormerkung` → `{geloescht: bool}`; `POST …/chat/vormerkung/starten` → `{auftrag}`; `POST …/chat/stopp {art: "behalten"|"verwerfen"}` → `{abgeschlossen: bool}`.
  - `GET …/chat`: zusätzlich `live: {schritt, schritt_nr, zwischenstand} | null` (nur für den `in_arbeit`-Auftrag) und `vorgemerkt: {id, nachricht} | null`; außerdem vor dem Lesen `_stopps_abschliessen()` (für jede id aus `pult_chat_stopp_faellig()`: letzten Zwischenstand laden, bei `behalten` rechnen/prüfen, `pult_chat_stopp_abschliessen`).
  - Keine Spalte namens `t`.
- [ ] **Step 1: Failing tests** (FalscheDB): Zwischenstand reicht SQL durch und gibt `weiter` zurück; zu groß ⇒ 413/422; ohne Schlüssel ⇒ 401; Vormerken PUT/DELETE/starten; Stopp-Arten validiert; GET enthält `live` und `vorgemerkt`; fälliger Stopp mit `behalten` und gültigen Blöcken ⇒ `pult_chat_stopp_abschliessen(` mit Blöcken; mit ungültigen (Validator meldet Fehler) ⇒ mit NULL und Hinweis; `gestoppt`-Route analog.
- [ ] **Step 2–4: FAIL → implementieren → PASS** (+ bisherige Chat-Tests grün).
- [ ] **Step 5: Commit** – `feat(marketing): Routen fuer Live-Zwischenstaende, Vormerken und Stopp`.

### Task 5: Chat-Arbeiter streamt (MOS)

**Files:**
- Modify: `workers/chat_worker.py`, Test `tests/test_chat_worker.py`

**Interfaces:**
- Consumes: Shim-Streaming (Task 1), `StromLeser` (Task 3), Arbeiter-Routen (Task 4), bestehendes `halten`, `pruefen`, `fertig`, `zurueck`.
- Produces:
  - `ChatApi.zwischenstand(aid, bloecke, schritt, nr) -> dict` und `ChatApi.gestoppt(aid, bloecke) -> dict`.
  - `frage_strom(system, nachrichten, url=LLM_URL, modell=MODELL) -> Iterator[str]` (SSE lesen, `delta.content` liefern; `finish_reason: "error"` oder Abbruch ⇒ `LlmFehler`).
  - `chat_bearbeiten(api, auftrag, fragen_strom=frage_strom, uhr=…, schlafen=…, drossel_s=1.0, …)`: je Stück `StromLeser.futter`; jede neue Änderung einzeln auf die Arbeitskopie anwenden (`anwenden(kopie, [aenderung], medien)` – bei `WerkzeugFehler` Änderung merken und Live-Stand nicht verändern); Zwischenstand senden, wenn seit dem letzten Senden ≥ `drossel_s` vergangen ist (Schritt = `aenderung.get("schritt") or werkzeug`); Antwort `weiter:false` ⇒ Stream abbrechen (Iterator schließen) und bei `grund == "stopp"` `api.gestoppt(aid, letzter_gueltiger_stand if stopp == "behalten" else None)` → Rückgabe `"gestoppt"`; `verloren` ⇒ `"fehler"` ohne weiteren Aufruf.
  - Nach Stream-Ende: `antwort_lesen(leser.text)` für `antwort` + volle Prüfung wie bisher (Gesamtliste über `anwenden` auf das Original, R9-`pruefen`, ein Korrekturversuch – der Korrekturversuch streamt ebenfalls und beginnt den Live-Stand neu vom Original); letzter Zwischenstand vor `fertig` immer senden.
  - Fällt Streaming ganz aus (`LlmFehler` vor dem ersten Stück) ⇒ bisherige Wiederholungslogik (bis 180 s pro Anfrage), dann `NICHT_ERREICHBAR`.
- [ ] **Step 1: Failing tests** mit falschem `fragen_strom` (liefert Stücke) und Fake-Api: Zwischenstände kommen gedrosselt (Fake-Uhr) und der letzte vor `fertig`; Schritte tragen die `schritt`-Texte; Stopp `behalten` ⇒ `gestoppt` mit letztem gültigem Stand, kein `fertig`; Stopp `verwerfen` ⇒ `gestoppt(None)`; ungültige Einzeländerung im Stream ⇒ Live-Stand unverändert, am Ende Korrekturversuch; Stream bricht nach Hälfte ab (`LlmFehler`) ⇒ Wiederholung; Stopp während Korrekturversuch ⇒ Stopp gewinnt.
- [ ] **Step 2–4: FAIL → implementieren → PASS** (alle bisherigen Arbeiter-Tests grün; Export-Pfad unverändert).
- [ ] **Step 5: Commit** – `feat(marketing): Chat-Arbeiter streamt und meldet Zwischenstaende`.

### Task 6: sales-ui – Vormerken und Stopp durchreichen (SC)

**Files:**
- Modify: `sales-mcp/ui_editor.py`, Test `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Produces (CSRF wie die anderen Schreib-Routen, Fehlerabbildung wie `_agent_post`):
  - `PUT /marketing/editor/{iid}/chat/vormerkung {nachricht 1..2000, kontext ≤ 4 KB}` → Pult PUT; `DELETE` → Pult DELETE; `POST …/chat/vormerkung/starten` → Pult; `POST …/chat/stopp {art}` → Pult.
  - Startdaten: `chat_vormerkung_url`, `chat_vormerkung_starten_url`, `chat_stopp_url`.
  - `chat.json` reicht `live` und `vorgemerkt` unverändert durch (prüfen, dass nichts herausgefiltert wird).
  - `marketing_pult.anfrage` muss `PUT`/`DELETE` können – prüfen und ggf. erweitern (Standard unverändert).
- [ ] **Step 1: Failing tests** (Fake-Pult): Pfade/Methoden/Nutzlasten; CSRF; Validierung; Startdaten-Schlüssel; `live`/`vorgemerkt` kommen durch.
- [ ] **Step 2–4: FAIL → implementieren → PASS.**
- [ ] **Step 5: Commit** – `feat(ui): Vormerken und Stopp fuer den Live-Agenten durchreichen`.

### Task 7: Editor – Live-Ansicht, Vormerken, Stopp (SC)

**Files:**
- Modify: `editor/src/chat.ts` (+ Test), `editor/src/pultZustand.ts` (+ Test), `editor/src/App/Chat/ChatLeiste.tsx`, `editor/src/App/Chat/Sperre.tsx`, Canvas-Einbindung (`editor/src/App/index.tsx`/`TemplatePanel`), `editor/src/App/Gestaltung/GestaltungFenster.tsx` (Chat-Bereich), neu `editor/src/App/Chat/StoppDialog.tsx`, `editor/src/live.ts` (+ `live.test.ts`); Paket-Test `sales-mcp/tests/test_editor_paket.py`.

**Interfaces:**
- Consumes: Task 6 (Startdaten, `live`, `vorgemerkt`).
- Produces:
  - `chat.ts`: Typen `ChatLive = { schritt: string; schritt_nr: number; zwischenstand: Dokument }`, `ChatStand` um `live: ChatLive | null; vorgemerkt: { id: string; nachricht: string } | null`; Funktionen `vormerken(s, nachricht, kontext)`, `vormerkungLoeschen(s)`, `vormerkungStarten(s)`, `stoppen(s, art)`.
  - `live.ts` (rein): `geaenderteBloecke(vorher: Dokument, nachher: Dokument): string[]` (ids mit geändertem JSON, in Dokumentreihenfolge), `zuletztGeaendert(...)`, `schrittText(live)` ⇒ „Schritt 3 · Titel links oben setzen“.
  - `pultZustand`: Takt 1000 ms während `laeuft`, sonst wie bisher; `live` im Store; beim Wechsel des Zwischenstands Dokument im Canvas **nur anzeigen** (separater Anzeigezustand, `resetDocument(zurAnzeige(zwischenstand))` mit Sperre; die echte Fassung wird nach `fertig` wie bisher geladen – Sicherstellen, dass ein Zwischenstand nie als `ungespeichert` zählt und nie gespeichert werden kann).
- Verhalten (Spec §2.3, §3): Hervorhebung des zuletzt geänderten Blocks (Akzent-Rahmen/Glow ≤ 600 ms, `scrollIntoView({behavior:'smooth', block:'nearest'})` nur wenn außerhalb der Sicht); Chat-Leiste mit Schritt-Zeile und dezenter Animation; Eingabe bleibt aktiv, Knopf „Vormerken“ während des Laufs, vorgemerkte Nachricht als eigene Karte (bearbeiten, löschen; nach Fehler/Stopp „Starten“/„Verwerfen“); „Stopp“-Knopf ⇒ `StoppDialog` („Bisherige Schritte behalten“ / „Verwerfen“ / Abbrechen).
- [ ] **Step 1: Failing tests** (vitest): `geaenderteBloecke` (neu, geändert, gelöscht ignoriert, Reihenfolge), `schrittText`; Store: 1-s-Takt nur bei `laeuft`, Zwischenstand setzt nie `ungespeichert`, `fertig` lädt die Fassung (bestehende Logik), Vormerken ruft PUT während `laeuft` und POST `chat_url` wenn nichts läuft; Stopp ruft `chat_stopp_url` mit `art`. Paket-Test: `editor.js` enthält „Vormerken“, „Bisherige Schritte behalten“, „Schritt “.
- [ ] **Step 2–4: FAIL → implementieren → vitest/tsc/build/Paket-Test PASS** (+ `test_editor_seite.py`).
- [ ] **Step 5: Commit** – `feat(editor): Live-Ansicht des Agenten mit Vormerken und Stopp` (inkl. Bundle).

### Task 8: Ausliefern (STOPP – nur nach ausdrücklicher Freigabe des Betreibers)

- [ ] Claims (WORKBOARD + Vault), sofort committen.
- [ ] Volle Tests MOS + SC + Editor.
- [ ] PC zuerst: `spaces/marketing` im Haupt-Checkout per `git restore --source=<MOS-HEAD>` nachziehen (vorher Hash-Vergleich gegen `98d61e55`); den Shim-Prozess auf :8117 gezielt beenden (nur den Python-Prozess, dessen Kommandozeile `claude_code_openai_shim.py --port 8117` enthält – NIE :8114, NIE ComfyUI) und den Chat-Arbeiter :8134 beenden; `marketing-dienste-starten.ps1` startet beide neu (Shim jetzt aus dem Marketing-Repo). Prüfen: `/v1/models` 200, Streaming-Probe mit kurzer Anfrage, Marketing-Agent auf :8117 antwortet weiter (Nicht-Stream).
- [ ] 061: Probe → anwenden → `verify_061` (+ `verify_060`).
- [ ] Push MOS + SC; VM `update.sh`.
- [ ] Echter Lauf (Probe-Newsletter): Umbau per Chat live verfolgen (Zwischenstände im Pult-GET sichtbar, Schritt-Texte sinnvoll), dabei die nächste Nachricht vormerken (startet danach automatisch); einmal Stopp + Behalten, einmal Stopp + Verwerfen; Ergebnisse ansehen. Der Betreiber prüft die Live-Ansicht im Browser.
- [ ] Claims schließen, Memory ergänzen (eigener Marketing-Shim, Live-Agent), Ledger-Rulings berichten, Workspace löschen.
