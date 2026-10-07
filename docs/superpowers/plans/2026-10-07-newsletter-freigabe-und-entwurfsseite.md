# Newsletter in den Sales-Freigaben, Entwurfsseite, Marke, Vorlagen – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Newsletter werden ausdrücklich eingereicht, in den Sales-Freigaben freigegeben (Flächen + Newsletter-Bilder in die Medien) oder mit Kommentar zurückgegeben (Feedback für Mensch und Agent); dazu eine aufgeräumte Entwurfsseite, „Marke“ statt „Layouts“ und eine lazy Vorlagen-Galerie.

**Architecture:** Der Freigabe-Zustand lebt in `marketing.inhalte` (neuer Status `eingereicht`, Tabelle `marketing.rueckmeldungen`, Regeln in DB-Funktionen aus Migration 063). Die Marketing-API bekommt einen eigenen Router `api/freigabe.py`; sales-ui zeigt eingereichte Newsletter in `/freigaben` über ein eigenes Modul `ui_freigabe_newsletter.py` (ui.py bekommt nur zwei Haken). Editor und Agent lesen Status und offene Rückmeldungen aus den Startdaten bzw. dem Chat-Auftrag.

**Tech Stack:** PostgreSQL (plpgsql), FastAPI, Starlette (sales-ui, ohne JavaScript), React 18 + MUI + zustand, vitest.

**Spec:** `docs/superpowers/specs/2026-10-07-newsletter-freigabe-und-entwurfsseite-design.md` (sales-claw)

## Repos und Arbeitsorte

- **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (master), Pfade relativ zu `spaces/marketing/`. NIE im Haupt-Checkout committen; vor jedem Commit `git rev-parse --show-toplevel` + Branch prüfen.
- **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (`feat/stufe-1-fundament`); `.superpowers/` nie stagen; `sales-mcp/ui.py` hat oft fremde Hunks → nur eigene Hunks stagen.
- Git über PowerShell; kein stash/push/force/--no-verify.
- MOS-Tests (aus MOS-Wurzel): `$env:SALES_CLAW_DIR="<SC>"; C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces/marketing/<pfad> -q -p no:cacheprovider` (bekannt unabhängig rot: test_integrations, test_send_paranoid, test_hand_bridge, test_cockpit_contract).
- SC-Tests: Postgres :55432 (`pg_ctl -D <scratchpad>\pgdata -o "-p 55432" start`, danach `stop -m immediate`; Start kann 10–20 min dauern), `SALES_DB_URL=postgresql://postgres@127.0.0.1:55432/postgres`, `SALES_DB_SCHEMA=sales_test`, venv-sales aus dem Scratchpad; bekannt unabhängig rot: 199 failed / 67 errors im Vollauf (compliance_test fehlt) – nur fokussierte Dateien zählen. Editor: in `editor/` `npx vitest run`, `npx tsc --noEmit`, `npm run build`, Bundle `sales-mcp/static/editor/` mit-committen.
- Migrationen nur per `python -m spaces.marketing.scripts.migration_probe <dateien>` (Transaktion + ROLLBACK) prüfen; NIE gegen die Live-DB anwenden (zielt auf die VM!). Ohne Test-DB: Stub-Cluster wie in Task 1 des Vorgänger-Plans, im Report sagen.
- SQL über `sync/_db`: keinen Alias/Spaltennamen `t`; data-modifying CTEs gehen nicht durch `_schreiben` (Unterabfrage) → Schreiben über DB-Funktionen.

## Global Constraints

- Status `marketing.inhalte.status`: `entwurf` (Anzeige „in Arbeit“, mit offener Rückmeldung „zurückgegeben“) · `eingereicht` („zur Freigabe“) · `freigegeben` („freigegeben“) · `abgelehnt` („verworfen“).
- Übergänge (nur diese): entwurf→eingereicht (einreichen); entwurf|eingereicht→abgelehnt (verwerfen, Grund Pflicht); eingereicht→entwurf (zurückziehen, ohne Rückmeldung); eingereicht→entwurf + Rückmeldung (zurückgeben, Kommentar 1–2000 Zeichen Pflicht); eingereicht→freigegeben (freigeben, nur die eingereichte Fassung).
- Meldungen wörtlich: „Der Assistent arbeitet gerade“, „Liegt zur Freigabe – erst zurückziehen“, „Inzwischen gibt es Fassung n – bitte neu laden“, „Schon entschieden (…)“, „Bitte sag kurz, was fehlt“, „Marketing gerade nicht erreichbar“, „Export läuft“, „Export offen – erneut anstoßen“.
- Freigeben = Fassung festschreiben, dann alle Gestaltungsflächen der Fassung × 3 Geräte in die Medien der Firma (bestehende Export-Logik inkl. Firmenzuordnung) + ein Newsletter-Export-Auftrag (`art=export`); ein Export-Fehler macht die Freigabe NICHT ungültig.
- Offene Rückmeldungen gehen bei jeder Chat-Bitte an den Agenten (Abschnitt „Offenes Feedback aus der Freigabe (vom Betreiber, bitte berücksichtigen):“) – keine automatische Überarbeitung. Beim Einreichen werden offene Rückmeldungen erledigt.
- Sales-Freigaben zeigen eingereichte Newsletter **aller Firmen** mit Firmen-Etikett.
- sales-ui-Seiten ohne JavaScript (Seiten-CSP `default-src 'none'`); Aufklappen per `<details>`.
- Pfade `/marketing/layouts…` bleiben; nur Anzeige „Marke“.
- Kein Modell auf der VM; Claude nur über :8117; :8114/ComfyUI unberührt.

## Rulings (Präzisierungen gegenüber der Spec)

- R1: Einreichen ist auch abgelehnt, solange ein **Bild-Auftrag** offen/in Arbeit ist („Der Assistent arbeitet gerade“ → für Bilder „Ein Bild wird gerade erzeugt“); `pult_bild_einsetzen` lehnt bei `eingereicht`/`freigegeben` ab – sonst entstünde nach dem Einreichen still eine neue Fassung.
- R2: Der Seitenleisten-Zähler `/freigaben` addiert die eingereichten Newsletter aus einem 60-s-Zwischenspeicher; ist die Marketing-API weg, zählt er nur die Sales-Entwürfe (keine Fehlerseite, keine Verzögerung > 2 s).
- R3: Für Feld-Newsletter (Format `felder`, Arten post/material) gilt derselbe Ablauf; deren Freigabe exportiert keine Flächen/Bilder (es gibt keine), nur die Fassung wird festgeschrieben.

## Review Focus

1. Eingereichter Newsletter, während am PC noch ein Bild-Auftrag fertig wird → keine neue Fassung, Auftrag scheitert sauber (Test in Task 1).
2. Freigeben im zweiten Tab, nachdem im ersten zurückgezogen und neu gespeichert wurde → Ablehnung „Inzwischen gibt es Fassung n …“, nichts exportiert (Test in Task 2).
3. Zurückgeben mit nur Leerzeichen als Kommentar → „Bitte sag kurz, was fehlt“, Status bleibt eingereicht (Tests in Task 1 und 4).
4. Freigaben-Seite, wenn die Marketing-API nicht antwortet → übrige Arten unverändert, Abschnitt Newsletter mit Hinweis, Seite lädt in < 10 s (Test in Task 4).
5. Editor in einem alten Tab, Newsletter inzwischen eingereicht → Speichern lehnt mit „Liegt zur Freigabe – erst zurückziehen“ ab, keine Fassung verloren (Test in Task 1 + Task 7).

---

### Task 1: Migration 063 – Freigabe-Zustände, Rückmeldungen, Sperren (MOS)

**Files:** Create `db/063_freigabe.sql`, `db/verify_063.sql`.

**Interfaces – Produces:**
- `marketing.inhalte`: Status-CHECK um `eingereicht`; die CHECK „status = 'entwurf' OR (entschieden_von … )“ so ändern, dass `eingereicht` ohne Entscheidung erlaubt ist; Spalten `eingereichte_fassung int`, `eingereicht_am timestamptz`, `eingereicht_von text`.
- `marketing.rueckmeldungen (id uuid PK DEFAULT gen_random_uuid(), inhalt uuid NOT NULL REFERENCES marketing.inhalte(id) ON DELETE CASCADE, fassung int NOT NULL, text text NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 2000), von text NOT NULL, am timestamptz NOT NULL DEFAULT now(), erledigt_am timestamptz)`, Index `(inhalt) WHERE erledigt_am IS NULL`.
- `marketing.pult_einreichen(p_inhalt uuid, p_von text) RETURNS int` (eingereichte Fassung): nur aus `entwurf`; offen/in_arbeit Chat-Auftrag ⇒ „Der Assistent arbeitet gerade“; offener/in_arbeit Bild-Auftrag ⇒ „Ein Bild wird gerade erzeugt“; ohne Fassung ⇒ „Ohne Fassung gibt es nichts einzureichen“; setzt Felder, erledigt offene Rückmeldungen. Sperrreihenfolge wie 061: erst `inhalte`, dann Aufträge.
- `marketing.pult_zurueckziehen(p_inhalt uuid, p_von text) RETURNS text`: nur aus `eingereicht` → `entwurf`, Einreich-Felder NULL.
- `marketing.pult_zurueckgeben(p_inhalt uuid, p_fassung int, p_von text, p_text text) RETURNS uuid` (Rückmeldungs-id): nur aus `eingereicht`, `p_fassung` = eingereichte Fassung (sonst „Inzwischen gibt es Fassung n – bitte neu laden“); leerer Text ⇒ „Bitte sag kurz, was fehlt“; → `entwurf`.
- `marketing.pult_entscheiden` (5-arg, wie 051): `freigeben` nur aus `eingereicht` und nur für `eingereichte_fassung` (= neueste); `ablehnen` aus `entwurf` und `eingereicht`; sonst „Schon entschieden (…)“.
- Sperren: `pult_bloecke_speichern` (aktuelle Hülle aus 060), `pult_fassung_speichern`, `pult_chat_anlegen` (Art `chat`), `pult_chat_vormerken`, `pult_bild_auftrag` lehnen bei `eingereicht` mit „Liegt zur Freigabe – erst zurückziehen“ ab; `pult_chat_anlegen` Art `export` zusätzlich bei `freigegeben` erlaubt; `pult_bild_einsetzen` lehnt bei `eingereicht`/`freigegeben` ab (R1).
- Vorgehen bei geänderten Funktionen: jeweils die **zuletzt gültige Definition** (grep über `db/0*.sql`, höchste Nummer gewinnt; 060-Hüllen beachten!) wörtlich übernehmen und nur die Status-Prüfung ergänzen; Kopfkommentar listet jede ersetzte Funktion und ihre Herkunftsdatei. RUNBOOK-Zeile: „Nach 063 NIE 051/053/056-061 erneut einspielen.“

- [ ] Failing `verify_063.sql` (nur über migration_probe, eigener Probe-Newsletter wie verify_061): jeder erlaubte Übergang; jeder verbotene (z. B. einreichen aus freigegeben, zurückgeben aus entwurf, freigeben aus entwurf, freigeben einer älteren Fassung); Kommentar „  “ ⇒ Fehler, Status bleibt; Sperren bei eingereicht (bloecke_speichern, chat_anlegen chat, bild_auftrag) mit genauer Meldung; export-Auftrag bei freigegeben erlaubt; **Review Focus 1:** in_arbeit-Bild-Auftrag ⇒ einreichen abgelehnt; bild_einsetzen bei eingereicht abgelehnt; erneutes Einreichen erledigt offene Rückmeldungen. Zusammen mit `verify_060`, `verify_061`, `verify_062` in EINER Probe laufen lassen (alles grün).
- [ ] Commit `feat(marketing): Migration 063 Freigabe-Zustaende und Rueckmeldungen`.

### Task 2: Pult-API für Freigabe (MOS)

**Files:** Create `api/freigabe.py`; Modify `api/server.py` (Router einhängen wie `_chat.pult_router`), `api/pult.py` (`GET /inhalte/{iid}`: Einreich-Felder + `rueckmeldungen`), `api/chat.py` (Export-Kern als Funktion herausziehen; `/naechster` liefert `rueckmeldungen_offen`); Test Create `tests/test_freigabe_api.py`, Modify `tests/test_chat_api.py`, `tests/test_pult_api.py`.

**Interfaces – Produces (alle `X-Pult-Key`, Fehler wie pult.py: DB-Ablehnung 422 mit Grund, DB weg 503):**
- `POST /api/pult/inhalte/{iid}/einreichen {von}` → `{"status": "eingereicht", "fassung": n}`
- `POST /api/pult/inhalte/{iid}/zurueckziehen {von}` → `{"status": "entwurf"}`
- `POST /api/pult/inhalte/{iid}/zurueckgeben {fassung, von, text}` → `{"status": "entwurf", "rueckmeldung": id}`; `text` leer/nur Leerraum ⇒ 422 „Bitte sag kurz, was fehlt“ ohne SQL; > 2000 ⇒ 422.
- `POST /api/pult/inhalte/{iid}/freigeben {fassung, von}` → `{"status": "freigegeben", "flaechen": [dateinamen], "export_auftrag": id|null, "export_fehler": str|null}`: erst `pult_entscheiden(…,'freigeben',…)`; danach in `try`: Flächen-Export aller Image-Blöcke mit `props.gestaltung` der Fassung (×3 Geräte, gleicher Code wie `/export`, ausgelagert als `export_ausfuehren(i, flaechen_ids, newsletter) -> dict`), Newsletter-Auftrag nur für Format `bloecke`; jede Exception dort ⇒ `export_fehler` gesetzt, HTTP 200.
- `POST /api/pult/inhalte/{iid}/export_nachholen {}` → wie oben ohne Entscheidung; nur bei `freigegeben`, sonst 422.
- `GET /api/pult/freigaben?status=eingereicht|entschieden&limit=20` → `{"freigaben": [{id, mandant, mandant_name, art, titel, betreff, status, eingereichte_fassung, eingereicht_am, eingereicht_von, entschieden_von, entschieden_am, grund, rueckmeldungen: [{text, von, am, fassung, erledigt}] (≤ 3 neueste), export: {"auftrag_status": str|null}}]}`; `entschieden` = freigegeben/abgelehnt + zurückgegebene der letzten 30 Tage (aus `rueckmeldungen`), neueste zuerst.
- `GET /api/pult/inhalte/{iid}` zusätzlich `inhalt.eingereichte_fassung/eingereicht_am/eingereicht_von` und `rueckmeldungen` (alle, neueste zuerst).
- `/api/chat/arbeiter/naechster`: Auftrag trägt `rueckmeldungen_offen: [{text, von, am, fassung}]` (eine zusätzliche Abfrage; Fehler ⇒ leere Liste, nie Auftragsverlust).

- [ ] Failing tests: jede Route Erfolg + DB-Ablehnung (422 mit Grund) + 401 ohne Schlüssel; zurueckgeben Leerraum ⇒ 422 ohne SQL (**Review Focus 3**); freigeben ruft zuerst `pult_entscheiden`, dann Flächen-Export (Dateien liegen, Zuordnung im SQL), dann `pult_chat_anlegen(...'export'...)`; Flächen-Export wirft ⇒ 200 mit `export_fehler`, Status freigegeben; **Review Focus 2:** `pult_entscheiden` lehnt „Inzwischen gibt es Fassung 4 …“ ab ⇒ 422, KEIN Export-SQL; export_nachholen bei entwurf ⇒ 422; `/freigaben` Form + Mandanten-Name; `/inhalte/{iid}` mit Rückmeldungen; `/naechster` mit `rueckmeldungen_offen` und bei deren Lesefehler leere Liste. Bestehende Warteschlangen der Chat-/Pult-Tests ergänzen, nicht abschwächen.
- [ ] FAIL → implementieren → PASS (`tests/test_freigabe_api.py`, `tests/test_chat_api.py`, `tests/test_pult_api.py`).
- [ ] Commit `feat(marketing): Pult-API fuer Einreichen, Zurueckgeben und Freigeben`.

### Task 3: Agent bekommt offenes Feedback (MOS)

**Files:** Modify `claw/agent_prompt.py`, `workers/chat_worker.py`; Test `claw/tests/test_agent_prompt.py`, `tests/test_chat_worker.py`.

**Interfaces – Consumes:** Auftragsfeld `rueckmeldungen_offen` (Task 2). **Produces:** `nutzer_text(..., feedback: list[dict] = ())`.

- [ ] `nutzer_text`: wenn `feedback`: Abschnitt `Offenes Feedback aus der Freigabe (vom Betreiber, bitte berücksichtigen):` und je Eintrag `- <JJJJ-MM-TT> <von> zu Fassung <n>: <text>` (Text auf 2000 gekürzt), platziert direkt nach `NACHRICHT`/`FENSTER`-Zeilen. SYSTEM ergänzt einen Satz: „Offenes Feedback aus der Freigabe ist eine Vorgabe des Betreibers: setz es um, wenn die Bitte es betrifft, und sag kurz, was du davon berücksichtigt hast.“
- [ ] `chat_worker._bearbeiten` reicht `auftrag.get("rueckmeldungen_offen") or []` (nur dicts mit str `text`) an `nutzer_text` durch.
- [ ] Failing tests: Abschnitt erscheint mit allen Einträgen, ohne Feedback kein Abschnitt (byte-gleich zu vorher), SYSTEM enthält den Satz; Arbeiter gibt das Feld aus dem Auftrag in den Prompt.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Gestaltungs-Agent bekommt offenes Freigabe-Feedback`.

### Task 4: Newsletter in den Sales-Freigaben (SC)

**Files:** Create `sales-mcp/ui_freigabe_newsletter.py`; Modify `sales-mcp/ui.py` (nur: Abschnitt in `inbox` einhängen, Zähler `_ZAEHLER_OFFEN`/Zählerabfrage `/freigaben` addieren, Routen registrieren, ggf. CSS-Zeilen), `sales-mcp/marketing_pult.py` (nichts Neues nötig, nur nutzen); Test Create `sales-mcp/tests/test_freigabe_newsletter.py`.

**Interfaces – Consumes:** Pult-Routen aus Task 2. **Produces:**
```python
async def abschnitt(ui) -> str            # HTML des Abschnitts „Newsletter“ (offene Karten + Verlauf)
def anzahl_offen() -> int                 # 60-s-Zwischenspeicher, Fehler => 0, Zeitlimit 2 s (R2)
def routen(ui) -> list                    # POST /freigaben/newsletter/{iid}/freigeben|zurueckgeben|export-nachholen
```
- [ ] Karte je eingereichtem Newsletter: Firmen-Etikett, Titel, Betreff, „Fassung n · eingereicht von … vor …“, Vorschau-Rahmen Mail (Standard) mit Verweis „Handy“ (lädt `?nl_format=handy` – ohne JS), Rahmenquelle `/marketing/entwurf/{iid}/vorschau?fassung=n&format=…` (bestehende Route); Link „Im Editor ansehen“; bis zu 3 erledigte Rückmeldungen in `<details>`.
- [ ] Aktionen wie die übrigen Freigaben (`_formular`-Stil, CSRF): „Freigeben“ mit Bestätigungshaken; „Zurückgeben“ mit `<textarea name="kommentar" required maxlength="2000">`. Nach Aktion Redirect 303 `/freigaben#newsletter`; PultFehler „abgelehnt“ ⇒ Fehlerseite mit Grund; freigeben mit `export_fehler` ⇒ Redirect + Hinweis im Verlauf.
- [ ] Verlauf (≤ 10): freigegeben („Medien: n Flächen“ + „Export läuft“/„Newsletter-Bilder fertig“ je Auftragsstatus / „Export offen – erneut anstoßen“ als Knopf), zurückgegeben (Kommentar), verworfen (Grund).
- [ ] API weg ⇒ Abschnitt mit „Marketing gerade nicht erreichbar“; Seite sonst unverändert.
- [ ] Failing tests (Falsch-Client wie test_marketing_pult): Abschnitt mit Karte und beiden Firmen-Etiketten; Zähler addiert; Freigeben/Zurückgeben schicken die richtigen Pult-Aufrufe mit `fassung`, `von`, Kommentar; ohne CSRF 403; Zurückgeben ohne Kommentar ⇒ 422-Seite ohne Pult-Aufruf (**Review Focus 3**); **Review Focus 4:** Pult wirft nicht_erreichbar ⇒ /freigaben 200, Hinweis im Abschnitt, Sales-Arten da; `anzahl_offen` nutzt den Zwischenspeicher (zweiter Aufruf ohne Pult-Aufruf) und gibt bei Fehler 0; alle Pult-Aufrufe im Threadpool.
- [ ] FAIL → implementieren → PASS (`tests/test_freigabe_newsletter.py` + bestehende Freigaben-Tests). Commit `feat(ui): Newsletter in den Freigaben`.

### Task 5: Entwurfsseite neu, Einreichen/Zurückziehen/Verwerfen, Status in Worten (SC)

**Files:** Modify `sales-mcp/ui_marketing.py` (Seite `entwurf`, neue POST-Routen `/marketing/entwurf/{iid}/einreichen|zurueckziehen|verwerfen`, `STATUS`-Anzeige, `uebersicht`/`entwuerfe`), `sales-mcp/ui.py` (nur CSS für `.pult`, `.status-pill`, `.feedback-band`, Karten); Test `sales-mcp/tests/test_marketing_pult.py`.

- [ ] Anzeige-Status (eine Funktion `status_wort(inhalt) -> str`): entwurf + offene Rückmeldung ⇒ „zurückgegeben“, entwurf ⇒ „in Arbeit“, eingereicht ⇒ „zur Freigabe“, freigegeben ⇒ „freigegeben“, abgelehnt ⇒ „verworfen“. Übersicht-Kacheln und Entwurfsliste nutzen ihn (Filter-Status `eingereicht` zusätzlich).
- [ ] Entwurfsseite gemäß Spec §6: Kopf (Titel, Firmen-Etikett, Status-Pill, Fassung), Feedback-Band (neueste offen, ältere in `<details>`), Aktionskarte (Im Editor öffnen | Zur Freigabe einreichen bzw. Zurückziehen; Verwerfen in `<details class="gefahr">` mit Pflicht-Grund), Karte Bilder (nur in Arbeit), Karte Fassungen (Zeitleiste, freigegebene markiert). Der Knopf „Freigeben (ablegen)“ entfällt; die Route `/entscheiden` bleibt nur für `verwerfen` (urteil=ablehnen) erreichbar – `urteil=freigeben` ⇒ 422-Seite „Freigeben geht über die Freigaben“.
- [ ] Rand-Fehler: Ursache des links abgeschnittenen Inhalts finden (vermutlich Grid/Überlauf in `.pult`) und beheben; Test prüft die CSS-Regel (min-width/overflow) als Textbeleg + Browser-Probe im Report (Screenshot-Beschreibung).
- [ ] Failing tests: Status-Pill je Zustand (5 Fälle); Band mit Kommentar; Einreichen/Zurückziehen/Verwerfen senden die Pult-Aufrufe (CSRF, `von`), Verwerfen ohne Grund ⇒ 422 ohne Pult-Aufruf; kein „Freigeben (ablegen)“ mehr im HTML; eingereicht zeigt „Zurückziehen“ statt „Einreichen“ und keine Bild-Karte.
- [ ] FAIL → implementieren → PASS. Commit `feat(ui): Entwurfsseite neu mit Einreichen und Feedback`.

### Task 6: „Marke“ statt „Layouts“, Vorlagen lazy (SC)

**Files:** Modify `sales-mcp/ui_marketing.py` (Seiten `layouts`, `layout_editor`: Titel/Texte „Marke“, Einleitungssatz), `sales-mcp/ui.py` (nur Navigationseintrag „Layouts“ → „Marke“), `sales-mcp/ui_editor.py` (`vorlagen_seite`: `loading="lazy"`, Platzhalter, feste Kartenhöhe); Test `tests/test_marketing_pult.py`, `tests/test_editor_seite.py`.

- [ ] Einleitungssatz wörtlich: „Diese Einstellungen (Farben, Schrift, Logo, Kopf- und Fußzeile) füllen neue Newsletter aus Vorlagen.“; Pfade unverändert.
- [ ] Vorlagen: jedes `<iframe class="layout-bild">` mit `loading="lazy"`; Rahmen-Container mit fester Höhe und Platzhaltertext (Vorlagenname) als Hintergrund-Text.
- [ ] Failing tests: Navigation/Seitentitel „Marke“, Satz vorhanden, alte URL liefert 200; Vorlagen-HTML enthält `loading="lazy"` je Karte.
- [ ] FAIL → implementieren → PASS. Commit `feat(ui): Marke statt Layouts, Vorlagen laden lazy`.

### Task 7: Editor – Einreichen, nur lesend, Feedback-Band (SC)

**Files:** Modify `sales-mcp/ui_editor.py` (`editor_seite` öffnet auch `eingereicht`; Startdaten `status`, `eingereicht_am`, `rueckmeldungen` (offene), `einreichen_url`, `zurueckziehen_url`; JSON-Routen `POST /marketing/editor/{iid}/einreichen|zurueckziehen` mit `X-CSRF`), `editor/src/pult.ts`, `editor/src/pultZustand.ts`, `editor/src/App/PultLeiste.tsx`, `editor/src/App/TemplatePanel/index.tsx`, Chat-Eingabe (Sperre); Tests `editor/src/pult.freigabe.test.ts`, `sales-mcp/tests/test_editor_seite.py`, `sales-mcp/tests/test_editor_paket.py`.

**Interfaces – Produces (TS):** `Start.status?: 'entwurf'|'eingereicht'`, `Start.rueckmeldungen?: {text: string; von: string; am: string; fassung: number}[]`, `einreichen(s): Promise<{ok:true}|{ok:false;grund:string}>`, `zurueckziehen(s)`; Store `nurLesen: boolean`.
- [ ] „Zur Freigabe einreichen“ in der PultLeiste: speichert vorher ungespeicherte Änderungen (bestehende Speichern-Funktion), gesperrt mit Tooltip-Grund solange `useAgentArbeitet()` ≠ null; Erfolg ⇒ `nurLesen = true`, Band erscheint.
- [ ] `nurLesen`: Canvas, Werkzeugleiste, Inspector und Chat-Eingabe gesperrt (vorhandene `useInert`-Sperre wiederverwenden), Band „Liegt zur Freigabe seit … – Zurückziehen“ (Knopf ruft `zurueckziehen`, danach Seite neu laden).
- [ ] Feedback-Band oben, solange `rueckmeldungen` (offen) nicht leer: neueste ausgeklappt, ältere einklappbar.
- [ ] Speichern lehnt der Server bei eingereicht ab (Task 1) ⇒ Fehlermeldung „Liegt zur Freigabe – erst zurückziehen“ sichtbar, Dokument bleibt im Editor (**Review Focus 5**).
- [ ] Failing tests: Python – Startdaten enthalten Status/Rückmeldungen/URLs; editor_seite öffnet eingereicht (200) statt Fehlerseite; Routen leiten weiter (CSRF, PultFehler-Grund). vitest – `einreichen`/`zurueckziehen` (Header, Fehlergrund), Store `nurLesen` aus Start, Einreichen gesperrt bei laufendem Agenten, Speichern-Ablehnung zeigt Grund. Paket-Test: Bundle enthält „Zur Freigabe einreichen“, „Liegt zur Freigabe“.
- [ ] FAIL → implementieren → vitest/tsc/build/Paket-Test PASS. Commit `feat(editor): Einreichen, nur lesend zur Freigabe, Feedback-Band` (inkl. Bundle).

### Task 8: Auslieferung und echter Lauf (Controller, nach Freigabe des Betreibers)

- [ ] Claims (WORKBOARD + Vault), sofort committen.
- [ ] Migration 063: Probe mit verify_060–063 gegen die VM-DB, dann anwenden, verify erneut.
- [ ] MOS pushen (Merge bei fremden Commits im temporären Worktree), SC pushen; VM `update.sh`; Haupt-Checkout per Hash-Vergleich synchronisieren; nur Chat-Arbeiter :8134 neu starten.
- [ ] Echter Lauf: Probe-Newsletter einreichen → in Sales-Freigaben → zurückgeben „Überschrift kürzer“ → Band im Editor, Agent nennt das Feedback → erneut einreichen → freigeben → Flächen + Newsletter-Bilder in den Medien der Firma; Entwurfsseite und „Marke“ im Browser ansehen.
- [ ] Claims schließen, Memory ergänzen.
