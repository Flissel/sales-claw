# Podcast-Seite im Marketing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber sieht unter Marketing eine Seite `/marketing/podcast` mit allen Folgen seiner Firma (Status, Abspielen, Skript) und kann dort eine Folge bestellen oder abbrechen.

**Architecture:** Die Podcast-Kette (Migration 069/070, `api/ton.py`, `workers/ton_worker.py`, `claw/ton_dienst.py`) besteht und bleibt unveraendert; es fehlen nur Pult-Routen (`/api/pult/ton`; heute gibt es Ton nur als Agent-Route `/api/ton/auftraege` ohne Mandantenfilter und ohne Skript) und eine sales-ui-Seite. Die Seite ist ein Modul `ui_podcast.py` analog `ui_reels.py` (Starlette, server-gerendert, ohne JavaScript, Mandant-Umschalter ueber `marketing_mandant`). Den Freigabe-Stand holt sich die Seite aus den eigenen Entwuerfen (`drafts.media_ref`), nicht aus der Marketing-DB.

**Tech Stack:** FastAPI + psql-Funktionen (MOS `spaces/marketing`), Starlette/psycopg (sales-ui), pytest.

**Spec:** keine - Entscheidungen E1..E9 unten, Quelle: Wunschliste C:/Users/User/Desktop/Vibemind_V1/tasks/2026-10-19-ui-marketing-wunschliste.md

## Entscheidungen (vom Betreiber zu bestaetigen)

Ist-Befund: Folgen erscheinen nur in den Freigaben (`sales-mcp/ui.py:1869-1874`, `_entwurf_kopf` spielt `pod-*.mp3` ab) und als Art "Podcast" im Plan (`sales-mcp/ui_plan.py:21`). `GET /api/ton/auftraege` (`spaces/marketing/api/ton.py`, `auftraege_lesen`) ist nur mit Agent-Key erreichbar, kennt weder Mandant-Filter noch Skript. `marketing.ton_auftraege` hat keinen Abbrechen-Weg und keine Angabe, wer bestellt hat.

- **E1 Eigene Seite `/marketing/podcast`, Menue "Podcast" direkt nach "Reels"** (`ui.py:1464`). Begruendung: Reels sind die gleiche Art Auftrag (Agent oder Betreiber bestellt, PC baut, Datei in Medien); gleiche Form = bekannte Bedienung. `/marketing/*` ist ueber `_ADMIN_BASIS_PFADE` (`ui.py:546`) bereits nur fuer Rolle `freigeben` im Basis-Laden offen, keine neue Berechtigungslogik.
- **E2 Lesen ueber neue Pult-Route `GET /api/pult/ton?mandant=` (X-Pult-Key)** mit Skript, Dauer, Befund, `angelegt_von`. Begruendung: sales-ui spricht nur ueber `/api/pult/*` mit Marketing (`marketing_pult.py`, `anfrage`); der Agent-Pfad bleibt unveraendert.
- **E3 Status-Anzeige in zwei Stufen.** Bau-Stand aus `ton_auftraege.status`: offen = "wartet", in_arbeit = "wird gesprochen", fertig = "fertig", fehler = "Fehler", abgebrochen = "abgebrochen". Freigabe-Stand nur bei fertigen Folgen, abgeleitet aus sales-`drafts` ueber `media_ref`: kein Entwurf = "noch kein Entwurf", pending = "zur Freigabe", approved = "freigegeben", sent = "gesendet", rejected/failed = "abgelehnt"/"fehlgeschlagen" (Woerter aus `ZUSTAND_TITEL`, `ui.py:1718`). Begruendung: Die Freigabe lebt in der Sales-DB; die Marketing-API kennt sie nicht, ein Rueckkanal waere neue Kopplung ohne Not.
- **E4 Bestellen im Pult per Formular** (Titel, Sprache, Standardsprecher, ein Textfeld Skript). Zeilenformat `Sprecher: Text`; Zeilen ohne `Name:` gehen an den Standardsprecher. Geprueft wird nur in der API (`_skript_pruefen`, eine Wahrheit). Hinweis im Formular: "Oder den Assistenten bitten". Begruendung: die DB-Funktion `ton_auftrag_anlegen` existiert, der Pult-Teil ist klein; ein KI-Entwurf des Skripts waere YAGNI (das kann der Assistent).
- **E5 Abbrechen fuer offen/in_arbeit** (wie Reels). Dafuer Migration **074 (reserviert, vor Nutzung pruefen; 073 ist belegt)**: Status `abgebrochen`, Spalte `angelegt_von` ('agent'|'betreiber', Standard 'agent'), `ton_abbrechen(uuid)`, `ton_auftrag_anlegen` mit 5. Parameter `p_von`. Der Ton-Arbeiter braucht keine Aenderung: `ton_abschliessen` und `arbeiter_datei` wirken nur auf `in_arbeit` (069, `api/ton.py`), bei einem abgebrochenen Auftrag liefern sie NULL bzw. 409.
- **E6 Skript und "Beschreibung":** Skript je Folge aufklappbar (`<details>`, kein JavaScript), je Abschnitt "Sprecher: Text". Ein eigenes Beschreibungsfeld gibt es nicht (keine Spalte); Titel, Sprache, Dauer, Sprecherliste und Skript sind die Beschreibung. Begruendung: kein Schema-Zuwachs ohne Bedarf.
- **E7 Abspielen** ueber `<audio controls preload="none">` mit `/medien/datei/<datei>` (vorhandene Auslieferung, `server.py:2648` laesst `.mp3` zu, `_medien_vorschau` `ui.py:2213` nutzt dasselbe). Der Player erscheint nur, wenn der Dateiname auf `^pod-[0-9a-f]{8}-[a-z0-9-]{1,60}\.mp3$` passt. Dauer als "m:ss".
- **E8 Kein Knopf "Zur Freigabe vorbereiten".** Der einzige Weg hinaus ist `versand_beauftragen` (Kanal + Empfaenger + Anhang); eine Folge hat keinen natuerlichen Empfaenger, und LinkedIn nimmt kein MP3. Die Seite zeigt stattdessen den Hinweis "Zum Versenden den Assistenten bitten" und danach den Stand aus E3. Offene Frage 1.
- **E9 Plan-Verweis:** Ein Plan-Eintrag der Art "Podcast" bekommt einen Link "Folgen ansehen" auf `/marketing/podcast`. Klein, hilft beim Finden (Betreiber: "ich sehe nicht wo Podcast in Marketing drin ist").

## Global Constraints

- sales-ui-Seiten haben KEIN JavaScript (CSP `default-src 'none'`); Interaktion nur ueber Formulare/Links (GET/POST mit `csrf`-Feld wie `ui_reels.py`).
- Anzeigetexte Deutsch mit echten Umlauten (`tests/test_darstellung.py` verbietet ASCII-Umschreibungen wie "zurueck", "fuer" in Literalen und Seiten).
- Keine `<img`-Tags mit Fremddaten; die Podcast-Seite braucht keine Bilder. Alle Fremdtexte (Titel, Sprecher, Skript, Befund) laufen durch `ui._e`.
- Farben nur ueber CSS-Variablen aus `ui.py :root` (`--akzent`, `--gut`, `--achtung`, `--fehler`); keine festen Hexwerte in neuem CSS. Tabellen ueber `_tabelle(...)` oder die Reels-Tabellenform; Touch-Ziele >= 44px.
- sales-ui spricht mit Marketing nur ueber `marketing_pult.anfrage` (X-Pult-Key, `/api/pult/*`).
- Migrationen idempotent, eine Transaktion, `verify_NNN.sql` daneben; naechste freie Nummer 074 reserviert (`ls db` vor Nutzung pruefen).
- Tests zuerst. sales-ui: `cd sales-mcp; SALES_DB_URL=postgresql://postgres:ci@127.0.0.1:55432/postgres SALES_DB_SCHEMA=sales_test E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`. MOS: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/<pfad> -q`. Migrationsprobe: `$env:SUPABASE_SSH_HOST='offload-vm'; $env:SUPABASE_DB_CONTAINER='debian-supabase-db-1'; python -m spaces.marketing.scripts.migration_probe <dateien>` (Rollback).
- Deploy-Reihenfolge: Migration -> API (VM `deploy/update.sh`, PC-Haupt-Checkout restore) -> Arbeiter -> sales-ui. Deploy nur nach Betreiber-OK (Task 6).
- Commits Conventional, Ende `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; SC direkt auf `feat/stufe-1-fundament`, MOS direkt auf master im Worktree `.worktrees/setup-agent`; nur eigene Dateien stagen; vor Commit `git pull --no-rebase`.

## Review Focus

1. Folge einer anderen Firma darf nie erscheinen: `GET /api/pult/ton?mandant=fin2gether` liefert nur deren Auftraege; ungueltiger Mandant (`../x`, Grossbuchstaben) = 422 (Task 2).
2. Titel/Sprecher/Skript/Befund mit `<script>` oder `"` werden escaped; ein manipulierter `datei`-Wert (`../x.mp3`) bekommt keinen Player (Task 4).
3. Leeres Skript, nur Leerzeilen, Zeile ohne Sprecher, Abschnitt > 1000 Zeichen: verstaendliche Fehlermeldung statt 500 (Task 4; Grenzen kommen aus der API).
4. Marketing-API nicht erreichbar/Schluessel falsch: Fehlerseite wie bei Reels, Sales laeuft weiter (Task 4).
5. Abbrechen einer schon fertigen oder schon abgebrochenen Folge: klare Ablehnung, kein Statuswechsel (Task 1/2); Abbrechen, waehrend der Arbeiter spricht: der spaetere `fertig`-Aufruf des Arbeiters aendert nichts (Task 1).
6. Zwei Entwuerfe zur selben Datei (einer abgelehnt, einer freigegeben): Anzeige zeigt den "weitesten" Stand, nicht zufaellig einen (Task 3).

---

## Dateien im Ueberblick

| Datei | Repo | Aufgabe |
|---|---|---|
| `spaces/marketing/db/074_ton_pult.sql`, `verify_074.sql` | MOS | Status `abgebrochen`, `angelegt_von`, `ton_abbrechen`, `ton_auftrag_anlegen` mit `p_von` |
| `spaces/marketing/api/ton.py` | MOS | `pult_router` (GET/POST/abbrechen) |
| `spaces/marketing/api/server.py` (bei `include_router(_ton.router)`, Z. 3497) | MOS | `include_router(_ton.pult_router)` |
| `spaces/marketing/tests/test_ton_api.py` | MOS | Tests der Pult-Routen |
| `sales-mcp/server.py` (bei `post_entwurf_erstellen`, Z. 2805) | SC | `entwurf_staende_zu_medien(namen)` |
| `sales-mcp/ui_podcast.py` (neu) | SC | Seite, Bestellen, Abbrechen, Skript-Parser |
| `sales-mcp/ui.py` (Z. 216, 1464, 7212) | SC | Import, Menue, Routen |
| `sales-mcp/ui_plan.py` | SC | Link "Folgen ansehen" |
| `sales-mcp/tests/test_podcast.py` (neu) | SC | Seitentests mit gefaelschtem Pult |

---

### Task 1: Migration 074 - Abbrechen und Urheber (MOS)

**Files:**
- Create: `spaces/marketing/db/074_ton_pult.sql`, `spaces/marketing/db/verify_074.sql`
- Test: Migrationsprobe (Rollback), danach `verify_074.sql`

**Interfaces:**
- Produces: Spalte `marketing.ton_auftraege.angelegt_von text NOT NULL DEFAULT 'agent' CHECK (angelegt_von IN ('agent','betreiber'))`; Status-CHECK um `'abgebrochen'` erweitert; `marketing.ton_abbrechen(p_id uuid) RETURNS text` (aus offen/in_arbeit, sonst `RAISE EXCEPTION 'Auftrag ist nicht mehr offen'`, setzt `befund = 'Im Pult abgebrochen'`, `vergeben_bis = NULL`); `marketing.ton_auftrag_anlegen(p_mandant text, p_titel text, p_sprache text, p_skript jsonb, p_von text DEFAULT 'agent') RETURNS uuid` (die 4-Parameter-Fassung aus 070 wird zuvor mit `DROP FUNCTION IF EXISTS` entfernt, sonst waeren zwei Ueberladungen mehrdeutig).

- [ ] **Step 1: `ls spaces/marketing/db | tail -3` - ist 074 frei? Sonst naechste Nummer nehmen und den Plan anpassen.**
- [ ] **Step 2: `verify_074.sql` zuerst schreiben** (Vorbild `verify_072.sql`): prueft Spalte `angelegt_von`; `ton_abbrechen` auf einen offenen Test-Auftrag liefert `abgebrochen`, ein zweiter Aufruf wirft; ein `fertig`-Auftrag ist nicht abbrechbar; `ton_auftrag_anlegen(..., 'betreiber')` setzt die Spalte, der Aufruf mit 4 Argumenten ergibt weiter `'agent'`; `ton_abschliessen` auf einen abgebrochenen Auftrag liefert NULL.
- [ ] **Step 3: Migrationsprobe nur mit `verify_074.sql` gegen den Stand 073, erwarte FAIL (Spalte/Funktion fehlt).**
- [ ] **Step 4: `074_ton_pult.sql` schreiben** (Kopf "RUNBOOK: nach 073", `BEGIN/COMMIT`, `ADD COLUMN IF NOT EXISTS`, Status-CHECK per `DROP CONSTRAINT IF EXISTS ton_auftraege_status_check` + `ADD CONSTRAINT`, Funktionen `CREATE OR REPLACE`, `REVOKE ALL ... FROM PUBLIC` wie 072).
- [ ] **Step 5: Migrationsprobe `074_ton_pult.sql` + `verify_074.sql`; erwarte PASS, ein zweiter Lauf ebenfalls (idempotent).**
- [ ] **Step 6: Commit** `feat(marketing): Podcast-Auftraege abbrechbar, Urheber je Auftrag (Migration 074)`.

### Task 2: Pult-Routen fuer Ton (MOS)

**Files:**
- Modify: `spaces/marketing/api/ton.py` (neuer `pult_router = APIRouter(prefix="/api/pult/ton")`, Vorbild `api/video.py` Z. 35 und 141-185), `spaces/marketing/api/server.py` (zweite `include_router`-Zeile neben Z. 3497)
- Test: `spaces/marketing/tests/test_ton_api.py` (vorhandene Fake-DB-Fixture dort wiederverwenden)

**Interfaces:**
- Consumes: `_schluessel` aus `api/pult.py` (X-Pult-Key), `_lesen`, `_schreiben`, `lit`, `_skript_pruefen`, `_auftrag_id` (wie in `api/video.py` die `_uuid_oder_404`-Nutzung).
- Produces: `GET /api/pult/ton?mandant=<id>&limit=50` -> `{"auftraege": [{id, mandant, titel, sprache, skript, status, datei, dauer_s, befund, angelegt_von, erstellt_am, geaendert_am}]}` (neueste zuerst, nur dieser Mandant); `POST /api/pult/ton` mit `{mandant, titel, sprache?, skript}` -> `{"auftrag": "<uuid>"}` (ruft `ton_auftrag_anlegen(..., 'betreiber')`); `POST /api/pult/ton/{aid}/abbrechen` -> `{"status": "abgebrochen"}`. Der Agent-Pfad `/api/ton/auftraege` bleibt unveraendert.

- [ ] **Step 1: Tests schreiben** in `test_ton_api.py`: `test_pult_liste_filtert_mandant_und_liefert_skript` (SQL enthaelt `WHERE mandant = 'vibemind'` und `skript`), `test_pult_liste_ohne_schluessel_abgewiesen`, `test_pult_liste_mandant_ungueltig_422` (`"../x"`, `"Vibemind"`), `test_pult_anlegen_nutzt_betreiber_und_prueft_skript` (SQL enthaelt `ton_auftrag_anlegen(` und `'betreiber'`; Abschnitt mit 1001 Zeichen = 422), `test_pult_abbrechen_ruft_funktion` (SQL enthaelt `ton_abbrechen(`), `test_pult_abbrechen_unbekannte_id_404`.
- [ ] **Step 2: `pytest spaces/marketing/tests/test_ton_api.py -q` - erwarte FAIL (404 auf die neuen Pfade).**
- [ ] **Step 3: Routen in `api/ton.py` implementieren;** Mandant-Regex `^[a-z][a-z0-9_-]{0,40}$` wie `video._MANDANT`; Spaltenliste als Konstante `_SPALTEN_PULT`; `server.py` bekommt `app.include_router(_ton.pult_router)`.
- [ ] **Step 4: Tests PASS; ausserdem `pytest spaces/marketing/tests/test_ton_worker.py spaces/marketing/tests/test_pult_api.py -q` (keine Regression).**
- [ ] **Step 5: Commit** `feat(marketing): Pult-Routen fuer Podcast-Folgen (/api/pult/ton)`.

### Task 3: Freigabe-Stand zu Mediendateien (SC)

**Files:**
- Modify: `sales-mcp/server.py` (neue Funktion neben `post_entwurf_erstellen`, Z. 2805; nur lesend, `_q` wie dort)
- Test: `sales-mcp/tests/test_podcast.py` (Abschnitt "Stand")

**Interfaces:**
- Produces: `entwurf_staende_zu_medien(namen: list[str]) -> dict[str, str]`: je Dateiname der weiteste Entwurfszustand aus `drafts.status` in der Reihenfolge `sent > approved > pending > failed > rejected`; Namen ohne Entwurf fehlen im Ergebnis. Treffer nur bei exaktem Namen in der Komma-Liste von `media_ref`.

- [ ] **Step 1: Tests schreiben** gegen die Test-DB (`sales_test`, Entwurf-Fixture wie in `tests/test_ui.py`): `test_stand_weitester_gewinnt` (zwei Entwuerfe, `rejected` und `approved` -> `approved`), `test_stand_exakter_name` (`pod-aaaaaaaa-x.mp3` trifft weder `pod-aaaaaaaa-x.mp3.bak` noch `xpod-aaaaaaaa-x.mp3`), `test_stand_leere_liste_ohne_abfrage`.
- [ ] **Step 2: Test laufen lassen, erwarte FAIL (Funktion fehlt).**
- [ ] **Step 3: Implementieren:** ein `select status, media_ref from drafts where media_ref ilike any(%s)` mit Parametern `%name%` (LIKE-Zeichen in Namen entschaerfen), danach in Python exakt gegen die Komma-Liste pruefen. Keine Schreibzugriffe.
- [ ] **Step 4: Test PASS.**
- [ ] **Step 5: Commit** `feat(sales): Freigabe-Stand zu Mediendateien (Grundlage Podcast-Seite)`.

### Task 4: Seite `/marketing/podcast` (SC)

**Files:**
- Create: `sales-mcp/ui_podcast.py`
- Modify: `sales-mcp/ui.py` (Import bei Z. 216, Menue Z. 1464 nach `("/marketing/reels", "Reels")`, Routen bei Z. 7212 `*ui_podcast.routen(sys.modules[__name__])`)
- Test: `sales-mcp/tests/test_podcast.py` (Muster `tests/test_reels.py`: `Falsch`-Pult, Fixture `pult`, `angemeldet`, `HOST`)

**Interfaces:**
- Consumes: `marketing_pult.anfrage` (Task 2), `server.entwurf_staende_zu_medien` (Task 3), `marketing_mandant.firma/umschalter`, `ui._seite/_fehlerseite/_csrf_ok/_gesichert_seite/_e`.
- Produces: `skript_aus_text(text: str, standard: str) -> list[dict[str, str]]` (Zeilen `Name: Text`, Leerzeilen ignoriert, Zeile ohne `Name:` -> `standard`; als Name gilt nur, was vor dem ersten `:` steht, hoechstens 30 Zeichen lang ist und aus Buchstaben/Punkt/Bindestrich/Leerzeichen besteht - sonst geht die ganze Zeile an `standard`); `STATUS` und `STAND` (Woerter nach E3); `routen(ui) -> list[Route]` mit `GET /marketing/podcast`, `POST /marketing/podcast/neu`, `POST /marketing/podcast/{aid}/abbrechen`.

- [ ] **Step 1: Tests schreiben:** `test_menue_hat_podcast_nach_reels` (`href="/marketing/podcast"` in `_seitenleiste`, Position nach Reels); `test_skript_aus_text` (Faelle `"Anna: Hallo\nBen: Hi"`, Zeile ohne Sprecher, Leerzeilen, `"Siehe https://x"` wird NICHT als Sprecher "Siehe https" gelesen); `test_seite_zeigt_folgen_status_player_skript` (fertige Folge mit `<audio controls preload="none" src="/medien/datei/pod-0123abcd-herbst.mp3">`, Dauer "2:05", Stand "zur Freigabe" aus gefaelschtem `entwurf_staende_zu_medien`, `<details>` mit "Anna: Hallo", laufende Folge "wird gesprochen" mit `http-equiv="refresh"`, Abbrechen-Formular nur bei offen/in_arbeit); `test_xss_und_manipulierte_datei` (Titel `<script>x</script>` escaped, `datei="../x.mp3"` ohne Player); `test_andere_firma_nutzt_cookie` (Cookie `mk_mandant=fin2gether` -> Pult-Aufruf `/ton?mandant=fin2gether`); `test_neu_bestellt_beim_pult` (POST -> 303 nach `/marketing/podcast`, Pult-Aufruf `POST /ton` mit `{mandant, titel, sprache, skript}`); `test_neu_leeres_skript_422_ohne_pult_aufruf`; `test_neu_api_lehnt_ab_zeigt_grund` (`PultFehler("abgelehnt", "text: 1 bis 1000 Zeichen je Abschnitt")`); `test_abbrechen_und_csrf` (alle POSTs ohne CSRF = 403); `test_pult_ausfall_fehlerseite` (`nicht_verbunden` und `nicht_erreichbar` je 503); `test_hinweis_versand_per_assistent`.
- [ ] **Step 2: Tests laufen lassen, erwarte FAIL (Modul fehlt).**
- [ ] **Step 3: `ui_podcast.py` nach dem Gerippe von `ui_reels.py` bauen** (`fehler()`, `csrf()`, Zeilenfunktion, `refresh=30` nur wenn eine Folge offen/in_arbeit ist). Spalten: Folge (Titel, Datum, Sprache, Urheber "Agent"/"Betreiber", Sprecher), Stand (Bau-Stand plus Freigabe-Stand), Anhoeren/Skript (Player, `<details><summary>Skript</summary>`, Befund bei Fehler). Datei-Regex wie E7. Formular "Neue Folge" (Titel max 120, Sprache Standard `de`, Standardsprecher, Skript `textarea`) mit Hinweisen zu Laenge ("bis etwa 12 Minuten, 1000 Zeichen je Absatz"), "Stimme: KI" und Versand per Assistent (E8). Alle Anzeigetexte mit echten Umlauten.
- [ ] **Step 4: Tests PASS; zusaetzlich `pytest tests/test_darstellung.py tests/test_reels.py tests/test_ui.py -q` (Menue-/Darstellungs-Regressionen).**
- [ ] **Step 5: Sichtpruefung** Desktop und Handy (Screenshot: Tabelle wird Karten, Player passt in 400 px, Knoepfe >= 44 px).
- [ ] **Step 6: Commit** `feat(ui): Podcast-Seite im Marketing (Folgen, Abspielen, Skript, Bestellen)`.

### Task 5: Plan-Eintrag verweist auf die Seite (SC)

**Files:**
- Modify: `sales-mcp/ui_plan.py` (die Stelle, an der ein Eintrag mit seiner `art` dargestellt wird; vor dem Edit `grep -n "ARTEN" ui_plan.py`, nicht die Konstante in Z. 21 aendern)
- Test: der vorhandene Plan-Test (`grep -ln "ui_plan" tests/`), sonst `tests/test_podcast.py`

**Interfaces:** Consumes die bestehende Eintragsdarstellung; Produces nichts Neues.

- [ ] **Step 1: Test:** Plan-Eintrag `art="podcast"` enthaelt `href="/marketing/podcast"` mit Text "Folgen ansehen"; Eintrag `art="post"` nicht.
- [ ] **Step 2: Erwarte FAIL.**
- [ ] **Step 3: Link nur fuer `art == "podcast"` ergaenzen.**
- [ ] **Step 4: Plan-Tests PASS.**
- [ ] **Step 5: Commit** `feat(ui): Plan-Eintraege der Art Podcast verweisen auf die Podcast-Seite`.

### Task 6: Deploy (nur nach Betreiber-OK)

**Files:** keine Codeaenderung.

- [ ] **Step 1: Betreiber-OK einholen** (Migration auf der VM-DB, API-Neustart, sales-ui-Neustart).
- [ ] **Step 2: Migration 074 auf der VM replayen, `verify_074.sql` ausfuehren (PASS).**
- [ ] **Step 3: API: MOS-master auf die VM (`deploy/update.sh`) und PC-Haupt-Checkout restore (bei Abweichung im Haupt-Checkout abbrechen und melden).** Probe: `GET /api/pult/ton?mandant=vibemind` mit Pult-Key liefert JSON.
- [ ] **Step 4: sales-ui deployen, `/marketing/podcast` im Browser pruefen:** Liste, Player bei der vorhandenen Folge, Mandant-Umschalter, Folge bestellen und am Ton-Arbeiter (PC, Dienst :8138) fertig werden sehen, offene Folge abbrechen.
- [ ] **Step 5: Betreiber informieren; Hinweis, dass der Ton-Arbeiter laufen muss (sonst bleibt die Folge "wartet").**

---

## Self-Review

- **Spec-Abdeckung:** Folgen-Liste mit Status (E3, Task 4), Abspielen (E7), Skript/Beschreibung (E6), Mandant-Umschalter (Task 4, `marketing_mandant`), Weg zum Erstellen (E4, Task 1/2/4), fehlende API-Routen als eigene MOS-Tasks (Task 1, 2).
- **Typen:** `entwurf_staende_zu_medien` (Task 3) wird in Task 4 so genutzt; `skript_aus_text` nur in Task 4; Pult-Pfade `/ton`, `/ton?mandant=`, `/ton/{aid}/abbrechen` aus Task 2 entsprechen den Aufrufen in Task 4 (`marketing_pult.anfrage` setzt `/api/pult` selbst davor).
- **Proportion:** Plan bewusst ohne Funktionskoerper; Tests nennen Namen und Pruefwerte.

## Offene Fragen an den Betreiber

1. Soll eine fertige Folge einen Versand-Knopf bekommen (z. B. per Mail an eine Kontaktliste)? Heute nur per Assistent (E8), weil jeder Versand einen Empfaenger braucht und LinkedIn kein MP3 nimmt.
2. Reicht ein Skript-Textfeld (E4), oder soll der Assistent das Skript immer schreiben und die Seite nur anzeigen?
3. Sollen Folgen loeschbar sein (Datei und Auftrag)? Plan: nein.
