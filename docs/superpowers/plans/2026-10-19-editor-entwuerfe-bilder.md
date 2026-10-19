# Editor, Entwürfe und Bilder – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entwürfe lassen sich aus der Liste löschen, benutzte Bilder lassen sich löschen (Plätze werden Platzhalter), der Editor hat Vorlagen eingebaut und bekommt fünf konkrete Verbesserungen.

**Architecture:** Regeln liegen wie bisher in der Marketing-DB bzw. Marketing-API (MOS `spaces/marketing`): neue DB-Funktion `pult_inhalt_loeschen` (Migration 075), neue Pult-Endpunkte für Löschen, Platzhalter, Vorlage anwenden und Fassung wiederherstellen. sales-ui (SC `sales-mcp`) reicht nur weiter und zeigt server-gerendert (ohne JS) Bestätigungsseiten; der Editor (SC `editor/`, React/MUI) spricht nur mit sales-ui-Routen unter `/marketing/editor/{iid}/…`.

**Tech Stack:** PostgreSQL/plpgsql, FastAPI (Marketing-API), Starlette (sales-ui), React 18 + MUI + zustand + vitest (Editor).

**Spec:** keine – Entscheidungen E1..E14 unten, Quelle: Wunschliste C:/Users/User/Desktop/Vibemind_V1/tasks/2026-10-19-ui-marketing-wunschliste.md (Abschnitt C), Design-Review E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/design/review-notizen.md

## Entscheidungen (vom Betreiber zu bestätigen)

**Entwürfe löschen**
- **E1 Löschbar sind nur `entwurf` (auch „zurückgegeben“) und `abgelehnt` („verworfen“).** `eingereicht` → „Liegt zur Freigabe – erst zurückziehen“; `freigegeben` → nie (die freigegebene Fassung ist versendbar, Sales-Entwürfe je Kontakt tragen ihre id in `drafts.newsletter`). Verworfene dürfen weg, weil sie keinen Versandweg mehr haben und die Liste heute mit Testleichen voll ist (Screenshot `marketing_entwuerfe_d.png`: 9 × „test“). „Verwerfen“ (mit Grund, bleibt sichtbar) gibt es schon (`ui_marketing.py:315`, `/marketing/entwurf/{iid}/verwerfen`) und bleibt der dokumentierte Weg; Löschen ist das Aufräumen.
- **E2 Echtes Löschen über eine DB-Funktion** `marketing.pult_inhalt_loeschen(p_inhalt uuid, p_mandant text, p_von text) RETURNS text` in **Migration 075** (074 ist vom Podcast-Plan `2026-10-19-podcast-seite.md` reserviert). Die Unveränderlichkeit der Fassungen (Trigger `trg_inhalt_fassung_unveraenderlich`, 050) bleibt; eine Ausnahme gilt nur für DELETE innerhalb dieser Funktion über die transaktionslokale Einstellung `marketing.inhalt_loeschen = <inhalt-id>`. Sperren (Klartext-Ausnahmen): fremde Firma, laufender Assistent (`chat_auftraege` `in_arbeit` mit gültiger Vergabe), laufendes Bild (`bild_auftraege` `in_arbeit` mit gültiger Vergabe), alter Freigabeweg noch offen (`broadcast_proposals.status IN ('draft','pending_approval')`). Mitgelöscht: Fassungen, Bild-/Chat-Aufträge, Rückmeldungen (CASCADE seit 063); Kampagnenplan verliert nur die Verknüpfung (`ON DELETE SET NULL`, 071). Erzeugte Bilder bleiben in der Medienbibliothek.
- **E3 Bedienung ohne JS, zweistufig wie `/medien`:** In `/marketing/entwuerfe` bekommt jede löschbare Zeile einen Haken (Formular um die Tabelle) plus Knopf „Ausgewählte löschen …“; auf der Entwurfsseite steht „Löschen …“ in der Gefahr-Karte neben „Verwerfen“. Schritt 1 zeigt eine Bestätigungsseite mit allen Titeln (nichts gelöscht), Schritt 2 löscht nach Haken „Ja, endgültig löschen“. Höchstens 50 je Durchgang; was die DB ablehnt, steht mit Grund auf der Ergebnisseite. Die Liste wird dabei auf `ui._tabelle` umgestellt (Wortbrüche/Handy-Karten).

**Bilder löschen**
- **E4 Benutzte Bilder sind löschbar, wenn sie nur in Entwürfen stecken.** Für jeden Inhalt mit Status `entwurf`, Editor-Format (`bloecke`) und eigener Firma, dessen NEUESTE Fassung das Bild trägt, legt die API VOR dem Löschen eine neue Fassung an (Urheber `betreiber`), in der jeder Platz mit diesem Bild zum passenden Platzhalter wird: Image-Block → `medien:platzhalter-AxB.png` nach `bildplaetze.platzhalter_name(width, height)` (ohne Maße `platzhalter-4x3.png`), Container-Hintergrund → `props.url` entfernt. Leere Plätze erkennt der Bild-Agent schon (`bildplaetze.ist_leer`). Ältere Fassungen bleiben unverändert (unveränderlich; ihre Vorschau zeigt dann ein fehlendes Bild). Die Warnung sagt „wird in N Entwürfen verwendet“ mit Titeln.
- **E5 Weiter gesperrt** (mit Klartext): eingereicht („erst zurückziehen“), freigegebene Fassung (Versand liest die Datei beim Senden, `api/pult.py:499`), alte Feld-Newsletter (`format = 'felder'`, kein Platzmodell), Entwürfe einer anderen Firma, Sales-Entwürfe `approved` – heute nur über `drafts.media_ref` geprüft (`ui.py:2286`); **neu auch `drafts.newsletter_medien`** (Lücke: `mail_dispatch.py:347` scheitert sonst beim Zustellen). Abgelehnte Inhalte sperren wie heute nicht.
- **E6 Mandantentrennung:** `/medien/verweise` bekommt `mandant`; Treffer anderer Firmen kommen ohne Titel (`eigen: false`). Ein für die Firma fremdes Bild (`medien_mandant.ist_fremd`) ist dort nicht löschbar (403). Die Editor-Bildwahl nutzt die Firma des Newsletters, `/medien` die Firma des Ladens (`MARKETING_MANDANT`, Rückfall `marketing_mandant.VORGABE`). Nach dem Löschen wird die Zeile in `marketing.medien_mandant` entfernt – sonst erbte eine spätere Datei gleichen Namens die alte Firma.
- **E7 Reihenfolge, fail-closed:** prüfen → Platzhalter-Fassungen → Datei löschen → Zuordnung vergessen. Scheitert eine Platzhalter-Fassung (Assistent arbeitet, Konflikt), wird die Datei NICHT gelöscht; schon umgestellte Entwürfe tragen harmlose Platzhalter und die Meldung nennt sie. Scheitert nur „vergessen“, wird geloggt (verwaiste Zeile, kein Schaden).

**Vorlagen im Editor**
- **E8 Linke Leiste mit Reitern „Abschnitte | Vorlagen“.** Der Reiter zeigt die freigegebenen Vorlagen der Firma des Newsletters (nicht des Cookies) mit Mini-Vorschau (gesandboxter, verkleinerter Rahmen) und zwei Knöpfen: „Als neuer Entwurf“ (heutiger Weg `/inhalte/aus_vorlage`, fragt Titel, öffnet den neuen Entwurf) und „Auf diesen Entwurf anwenden …“. `/marketing/vorlagen` bleibt als Einstieg ohne Entwurf.
- **E9 „Anwenden“ ersetzt Aufbau, Gestaltung, Texte und Bilder vollständig** (Vorlage mit Marke gefüllt wie „Neu aus Vorlage“, `pult._vorlage_fuellen`) und legt eine NEUE Fassung an; Betreff und Vorschautext bleiben. Keine automatische Textübernahme: Abschnitte verschiedener Vorlagen lassen sich nicht verlässlich zuordnen, eine halbe Übernahme wäre schlimmer als keine. Rückweg ist E12 (alte Fassung wiederherstellen). Nur im Status `entwurf`, nur ohne ungespeicherte Änderungen, mit Bestätigungsdialog.

**Editor-Verbesserungen** (aus Review + Code; Handy-Editor ist S4, Marken-Theme ist S2 – beide nicht hier)
- **E10 (V1) Kompakte Abschnittskarten:** heute sieht man bei 900 px Höhe nur 4 von 13 Abschnitten (`editor_neu_1440.png`). Karten im 2-Spalten-Raster, Skizze + Titel, Beschreibung als Tooltip, Klick = „Einfügen“ am Ende, Ziehen bleibt.
- **E11 (V2) Rückgängig/Wiederholen** im Newsletter: es gibt heute keins (`EditorContext.tsx` hat kein History). 50 Schritte, Änderungen innerhalb von 500 ms zählen als ein Schritt (Tippen), Strg+Z / Strg+Umschalt+Z / Strg+Y außerhalb von Textfeldern, zwei Knöpfe in der Werkzeugleiste. `resetDocument` (Laden, Agent-Fassung) leert den Verlauf.
- **E12 (V3) Fassungsverlauf im Editor:** Menü „Verlauf“ in der Pult-Leiste mit den letzten 30 Fassungen (Nummer, du/Agent, Zeit), je „Ansehen“ (Pult-Vorschau im neuen Tab) und „Wiederherstellen“ (legt die alte Fassung als neue Fassung an; nur Editor-Format, nur `entwurf`).
- **E13 (V4) Zähler für Betreff und Vorschautext:** Betreff Hinweis ab 61 Zeichen („Mailprogramme kürzen ab etwa 60 Zeichen“); Vorschautext leer → „Ohne Vorschautext zeigen Mailprogramme den Anfang der Mail“, ab 101 Zeichen → „Mailprogramme zeigen etwa 40–100 Zeichen“. Nur Hinweis, keine Sperre.
- **E14 (V5) Bild-Löschdialog im Editor** als MUI-Dialog statt `window.confirm` (`ImageSidebarPanel.tsx:104`): nennt E4-Warnung mit Titeln, die Sperre aus E5 und Sales-Entwürfe; Knopf „Endgültig löschen“.

## Global Constraints

- sales-ui-Seiten haben KEIN JavaScript (CSP `default-src 'none'`); Interaktion über Formulare mit CSRF (`<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">`, Prüfung `ui._csrf_ok(form)`). Editor-JSON-Routen prüfen den Kopf `X-CSRF` mit `hmac.compare_digest` wie `ui_editor.medien_loeschen`.
- Anzeigetexte Deutsch mit echten Umlauten (`tests/test_darstellung.py` verbietet „zurueck“, „fuer“ u. ä. in Literalen und Seiten).
- Keine `<img`-Tags mit Fremddaten in sales-ui-Seiten; Vorschauen nur als gesandboxte Rahmen wie `/marketing/vorlage-bild/{name}`.
- Farben nur über CSS-Variablen aus `ui.py :root` (`--akzent`, `--gut`, `--achtung`, `--fehler`, `--blush`); im Editor nur über das MUI-Theme (`theme.ts`). Keine festen Hexwerte in neuem CSS.
- Tabellen über `ui._tabelle(spalten, zeilen, filterzeile=None, leer=None)`; Touch-Ziele ≥ 44 px.
- Migrationen idempotent, eine Transaktion, `verify_NNN.sql` daneben; **075 reserviert** (vor Nutzung `ls spaces/marketing/db | tail -4` – ist 075 belegt, nächste freie nehmen und Plan anpassen).
- Tests TDD. sales-ui: `cd sales-mcp; SALES_DB_URL=postgresql://postgres:ci@127.0.0.1:55432/postgres SALES_DB_SCHEMA=sales_test E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`. Editor: `cd editor && npx tsc --noEmit && npx vitest run && npm run build` (Bundle nach `sales-mcp/static/editor` mitcommitten – `tests/test_editor_paket.py` prüft das). MOS: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/<pfad> -q`. Migration: `$env:SUPABASE_SSH_HOST='offload-vm'; $env:SUPABASE_DB_CONTAINER='debian-supabase-db-1'; python -m spaces.marketing.scripts.migration_probe <dateien>` (Rollback).
- Repos: SC = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw` (Branch `feat/stufe-1-fundament`); MOS = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent` (`master`).
- Commits: Conventional Commits, Ende `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; nur eigene Dateien stagen; vor Commit `git pull --no-rebase`.
- Deploy-Reihenfolge: Migration → API (VM via `deploy/update.sh`, PC-Haupt-Checkout restore) → sales-ui. Nur Task 12, nur nach Betreiber-OK.

## Review Focus

1. **Bild steckt zweimal im selben Entwurf (zwei Plätze, oder Image + Container-Hintergrund):** beide werden Platzhalter in EINER neuen Fassung, und danach kommt `"medien:<name>"` im Dokument nicht mehr vor – sonst Inhalt sperren statt halb umstellen. Test in Task 3.
2. **Gross-/Kleinschreibung des Dateinamens (`FOTO.JPG` vs. `foto.jpg`):** die Verweissuche ist exakt (`strpos`), die Firmenprüfung faltet (`ist_fremd`). Löschen von `Foto.jpg` darf eine fremde `foto.jpg` nicht treffen; Test in Task 3 (fremd trotz anderer Schreibung → 403).
3. **Doppelklick / zweiter Tab beim Löschen eines Entwurfs:** der zweite Aufruf trifft keinen Inhalt mehr → „Unbekannter Inhalt“ als Zeile auf der Ergebnisseite, kein 500. Test in Task 5.
4. **Vorlage anwenden, während der Assistent arbeitet oder eine Agent-Fassung neuer ist:** `pult_bloecke_speichern` lehnt ab („Der Assistent arbeitet gerade“ / veraltete Basis) → Editor zeigt den Grund, lädt nichts neu. Test in Task 4 (API reicht 422 durch) und Task 8 (Dialog zeigt Grund).
5. **Rückgängig nach einem Neuladen durch Agent-Fassung:** Verlauf ist leer, Strg+Z tut nichts (kein Sprung in einen Stand vor der Agent-Fassung). Test in Task 9.

---

## Dateien

| Datei | Repo | Verantwortung |
|---|---|---|
| `spaces/marketing/db/075_inhalt_loeschen.sql`, `verify_075.sql` | MOS | `pult_inhalt_loeschen`, Trigger-Ausnahme |
| `spaces/marketing/api/pult.py` | MOS | `/inhalte/{iid}/loeschen`, `/inhalte/{iid}/vorlage`, `/inhalte/{iid}/wiederherstellen`, `/medien/verweise?mandant=` |
| `spaces/marketing/claw/bildplaetze.py` | MOS | `platzhalter_einsetzen` |
| `spaces/marketing/api/medien_mandant.py` | MOS | `/medien/platzhalter`, `/medien/vergessen` |
| `spaces/marketing/tests/test_pult_api.py`, `tests/test_medien_mandant.py`, `claw/tests/test_bildplaetze.py` | MOS | Tests |
| `sales-mcp/marketing_pult.py` | SC | Aufrufhelfer |
| `sales-mcp/ui_marketing.py` | SC | Liste mit Haken, Bestätigung, Löschen auf Entwurfsseite |
| `sales-mcp/ui.py` | SC | `medien_loeschsperre` neu, `medien_endgueltig_loeschen`, `/medien`-Warnseite |
| `sales-mcp/ui_editor.py` | SC | Editor-Routen Vorlagen/Verlauf, Start-JSON, CSP, Bild-Löschen |
| `editor/src/pult.ts`, `zaehler.ts` (neu), `documents/editor/EditorContext.tsx`, `App/AbschnittLeiste.tsx`, `App/VorlagenReiter.tsx` (neu), `App/PultLeiste.tsx`, `App/TemplatePanel/index.tsx`, `App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.tsx` | SC | Editor |

---

### Task 1: Migration 075 – Inhalt löschen (MOS)

**Files:**
- Create: `spaces/marketing/db/075_inhalt_loeschen.sql`, `spaces/marketing/db/verify_075.sql`

**Interfaces:**
- Produces: `marketing.pult_inhalt_loeschen(p_inhalt uuid, p_mandant text, p_von text) RETURNS text` – gibt den Titel zurück; Ausnahmen (Klartext, werden von der API zu 422): `Unbekannter Inhalt`, `Gehört einer anderen Firma`, `Liegt zur Freigabe – erst zurückziehen`, `Freigegebene Inhalte bleiben erhalten`, `Der Assistent arbeitet gerade`, `Ein Bild wird gerade erzeugt`, `Liegt noch im alten Freigabeweg – dort erst ablehnen`.
- Produces: `marketing._inhalt_fassung_unveraenderlich()` (Trigger-Funktion nur für `inhalt_fassungen`; `layout_fassungen` behält `_fassung_unveraenderlich`).

- [ ] **Step 1:** `ls spaces/marketing/db | tail -4` – 075 frei? Sonst nächste Nummer, Plan anpassen.
- [ ] **Step 2: `verify_075.sql` zuerst schreiben** (Vorbild `verify_063.sql`, alles in `BEGIN … ROLLBACK`-fähigen DO-Blöcken): legt Test-Inhalt (mandant `vibemind`, `entwurf`) mit 2 Fassungen, einem `bild_auftraege`- und `chat_auftraege`-Eintrag (`fertig`), einer Rückmeldung und einem `kampagnen_plan`-Eintrag an; prüft: (a) `DELETE FROM marketing.inhalt_fassungen` direkt wirft weiter „Fassungen sind unveraenderlich“; (b) `pult_inhalt_loeschen(id,'fin2gether','t')` wirft `Gehört einer anderen Firma`; (c) mit `chat_auftraege.status='in_arbeit'`, `vergeben_bis = now()+interval '5 min'` wirft `Der Assistent arbeitet gerade`; (d) Status `eingereicht` wirft `Liegt zur Freigabe – erst zurückziehen`, `freigegeben` wirft `Freigegebene Inhalte bleiben erhalten`; (e) Erfolg liefert den Titel, danach 0 Zeilen in `inhalte`, `inhalt_fassungen`, `bild_auftraege`, `chat_auftraege`, `rueckmeldungen` für die id und `kampagnen_plan.inhalt IS NULL`; (f) `abgelehnt` ist löschbar; (g) `current_setting('marketing.inhalt_loeschen', true)` ist nach der Funktion nicht mehr die id (transaktionslokal, `set_config(…, true)` und am Ende auf `''` zurück).
- [ ] **Step 3:** Migrationsprobe nur mit `verify_075.sql` gegen Stand 073/074 → erwartet FAIL (Funktion fehlt).
- [ ] **Step 4: `075_inhalt_loeschen.sql` schreiben.** Kopf-RUNBOOK: „Nach 075 NIE 050 erneut einspielen (setzt den Trigger auf `_fassung_unveraenderlich` zurück – Löschen scheitert dann fail-closed).“ Inhalt: neue Trigger-Funktion (DELETE erlaubt nur wenn `TG_OP = 'DELETE' AND current_setting('marketing.inhalt_loeschen', true) = OLD.inhalt::text`), Trigger `trg_inhalt_fassung_unveraenderlich` neu auf sie; Funktion sperrt zuerst `inhalte … FOR UPDATE` (Sperrreihenfolge wie 061), prüft die Regeln aus E2 in der Reihenfolge der Interfaces-Liste, löscht `chat_auftraege`, `bild_auftraege`, setzt die Einstellung, löscht Fassungen und Inhalt, setzt die Einstellung zurück. Vor dem Schreiben per `grep -n "REFERENCES marketing.inhalte" spaces/marketing/db/*.sql` und in der Probe per `pg_constraint` (confrelid = `marketing.inhalte`) prüfen, dass keine weitere Tabelle ohne CASCADE/SET NULL auf `inhalte` zeigt – sonst dort ebenfalls löschen.
- [ ] **Step 5:** Probe `075_inhalt_loeschen.sql verify_075.sql verify_063.sql` → PASS.
- [ ] **Step 6: Commit** (MOS) `feat(marketing): Entwürfe endgültig löschen (075)`.

### Task 2: API – Inhalt löschen und Verweise je Firma (MOS)

**Files:**
- Modify: `spaces/marketing/api/pult.py` (neue Route nach `entscheiden`, ~Z. 586; `_VERWEISE_SQL`/`medien_verweise` Z. 645-672)
- Test: `spaces/marketing/tests/test_pult_api.py`

**Interfaces:**
- Consumes: `pult_inhalt_loeschen` (Task 1).
- Produces: `POST /api/pult/inhalte/{iid}/loeschen` Body `{"mandant": str, "von": str}` → `{"geloescht": iid, "titel": str}`; DB-Ablehnung → 422 mit Grund; fehlender/unbekannter Mandant → 422 ohne SQL (Mandant Pflicht, kein Rückfall).
- Produces: `GET /api/pult/medien/verweise?name=&mandant=` → je Eintrag zusätzlich `"format"` (`bloecke`|`felder`), `"eigen"` (bool) und `"fassung"` (int, neueste bzw. freigegebene). Mit `mandant`: Einträge anderer Firmen haben `"titel": ""`, `"eigen": false`. Ohne `mandant`: wie heute, `eigen` immer true (Altaufrufer).

- [ ] **Step 1: Tests schreiben:** `test_loeschen_ruft_db_funktion_mit_mandant` (SQL enthält `pult_inhalt_loeschen(` und `'vibemind'`, Antwort `{"geloescht": IID, "titel": "T"}`); `test_loeschen_ohne_mandant_422_ohne_sql` (`db.sql == []`); `test_loeschen_db_ablehnung_422` (Fehler mit `ERROR:  Liegt zur Freigabe – erst zurückziehen` → 422, Text im `detail`); `test_verweise_maskiert_fremde_titel` (zwei Zeilen, mandant `fin2gether` und `vibemind`, Abfrage mit `mandant=vibemind` → fremde `titel == ""`, `eigen is False`); `test_verweise_ohne_mandant_wie_bisher`.
- [ ] **Step 2:** Tests laufen → FAIL.
- [ ] **Step 3:** Implementieren. Verweis-SQL liefert zusätzlich `i.mandant`, `n.format`/`f.format`, `n.fassung`/`f.fassung`; maskiert wird in Python.
- [ ] **Step 4:** Tests → PASS; ganze Datei `tests/test_pult_api.py` grün.
- [ ] **Step 5: Commit** `feat(marketing): Pult-Endpunkt Inhalt löschen, Medienverweise je Firma`.

### Task 3: Platzhalter statt Bild – API (MOS)

**Files:**
- Modify: `spaces/marketing/claw/bildplaetze.py`, `spaces/marketing/api/medien_mandant.py`
- Test: `spaces/marketing/claw/tests/test_bildplaetze.py`, `spaces/marketing/tests/test_medien_mandant.py`

**Interfaces:**
- Produces: `bildplaetze.platzhalter_einsetzen(dok: dict, name: str) -> tuple[dict, int]` – neue Kopie; Image-Blöcke mit `props.url == "medien:"+name` → `"medien:" + platzhalter_name(width, height)` (fehlen/0 → `platzhalter-4x3.png`), Container mit dieser `props.url` → Schlüssel `url` entfernt; zählt ersetzte Plätze.
- Produces: `POST /api/pult/medien/platzhalter` Body `{"name": str, "mandant": str, "von": str}` → `{"umgestellt": [{"id","titel","fassung"}], "gesperrt": [{"id","titel","grund"}]}`. 403 `"Das Bild gehört einer anderen Firma"` wenn `ist_fremd(name, mandant, sicht(mandant))`. Umgestellt wird nur `status='entwurf'`, `format='bloecke'`, eigene Firma, neueste Fassung trägt den Wert; alles andere mit Treffer landet in `gesperrt` (Gründe wie E5). Je Inhalt: `pult_bloecke_speichern(i, neueste, betreff, vorschautext, neu, 'betreiber', false)`; DB-Ablehnung → Eintrag in `gesperrt` mit DB-Grund, weiter mit dem nächsten.
- Produces: `POST /api/pult/medien/vergessen` Body `{"name": str}` → `{"entfernt": int}` (DELETE aus `marketing.medien_mandant`, exakter Name).

- [ ] **Step 1: Tests schreiben** (`test_bildplaetze.py`): `test_platzhalter_nach_seitenverhaeltnis` (Image 552×311 → `medien:platzhalter-16x9.png`, Zähler 1); `test_zwei_plaetze_und_container_in_einem_dokument` (Image + Container mit demselben Namen → Zähler 2, Container ohne `url`, `"medien:a.jpg"` nicht mehr in `json.dumps(neu)`); `test_aehnlicher_name_bleibt` (`aa.jpg` bleibt bei Name `a.jpg`); `test_original_unveraendert`.
- [ ] **Step 2: Tests schreiben** (`test_medien_mandant.py`): `test_platzhalter_fremdes_bild_403_ohne_schreiben` (Sicht: `Foto.jpg` gehört `fin2gether`, Aufruf `name=foto.jpg`, `mandant=vibemind` → 403, kein `pult_bloecke_speichern` im SQL); `test_platzhalter_stellt_nur_eigene_entwuerfe_um` (Verweise: entwurf/bloecke/eigen, eingereicht, freigegeben, fremd → genau ein `pult_bloecke_speichern`-Aufruf, drei Einträge in `gesperrt`); `test_platzhalter_db_ablehnung_wird_gesperrt` (`ERROR:  Der Assistent arbeitet gerade` → Eintrag in `gesperrt`, Status 200); `test_platzhalter_rest_im_dokument_sperrt` (Dokument trägt den Namen zusätzlich in einem Text-Link → kein Speichern, Grund „Das Bild steckt an einer Stelle, die kein Bildplatz ist“); `test_vergessen_loescht_zuordnung`.
- [ ] **Step 3:** Tests → FAIL.
- [ ] **Step 4:** Implementieren; die Verweisabfrage aus Task 2 wiederverwenden (gemeinsame Hilfsfunktion `verweise_lesen(name: str, mandant: str | None) -> list[dict]` in `pult.py`, von `medien_verweise` und `medien_platzhalter` genutzt). Für die Umstellung neueste Fassung mit `bloecke, felder, fassung` lesen.
- [ ] **Step 5:** Tests → PASS (beide Dateien komplett).
- [ ] **Step 6: Commit** `feat(marketing): benutzte Bilder durch Platzhalter ersetzen`.

### Task 4: API – Vorlage anwenden und Fassung wiederherstellen (MOS)

**Files:**
- Modify: `spaces/marketing/api/pult.py` (neben `inhalt_aus_vorlage`, Z. 347)
- Test: `spaces/marketing/tests/test_pult_api.py`

**Interfaces:**
- Produces: `POST /api/pult/inhalte/{iid}/vorlage` Body `{"vorlage": str, "basis_fassung": int, "von": str}` → `{"fassung": int}`. Liest Inhalt (Mandant, Status, Art, neueste Fassung inkl. `felder`), verlangt `art='newsletter'` und `status='entwurf'` (sonst 422 „Vorlagen lassen sich nur auf Newsletter-Entwürfe anwenden“), Vorlage freigegeben und für den Mandanten des INHALTS (`mandant = m OR fuer_alle`, sonst 422 wie `inhalt_aus_vorlage`), `_vorlage_fuellen(v["bloecke"], m, _laden_lesen(m))`, dann `pult_bloecke_speichern(i, basis, betreff, vorschautext, fertig, 'betreiber', false)` mit Betreff/Vorschautext der neuesten Fassung.
- Produces: `POST /api/pult/inhalte/{iid}/wiederherstellen` Body `{"fassung": int, "basis_fassung": int, "von": str}` → `{"fassung": int}`. Alte Fassung muss `format='bloecke'` haben (sonst 422 „Nur Editor-Fassungen lassen sich wiederherstellen“); speichert deren `bloecke` und deren Betreff/Vorschautext als neue Fassung.

- [ ] **Step 1: Tests schreiben:** `test_vorlage_anwenden_nutzt_mandant_des_inhalts` (Inhalt `fin2gether`, SQL der Vorlagenabfrage enthält `'fin2gether'`, Speichern mit `basis` 7 und dem alten Betreff); `test_vorlage_anwenden_nicht_im_entwurf_422_ohne_speichern` (Status `eingereicht`); `test_vorlage_anwenden_veraltete_basis_reicht_db_grund_durch` (422); `test_wiederherstellen_speichert_alte_bloecke` (SQL enthält Bloecke der Fassung 3 und Betreff der Fassung 3); `test_wiederherstellen_feldfassung_422`; `test_basis_fassung_kein_int_422_ohne_sql`.
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS, ganze Datei grün.
- [ ] **Step 5: Commit** `feat(marketing): Vorlage auf Entwurf anwenden, Fassung wiederherstellen`.

### Task 5: Entwürfe löschen in sales-ui (SC)

**Files:**
- Modify: `sales-mcp/marketing_pult.py` (nach `medien_verweise`, Z. 69), `sales-mcp/ui_marketing.py` (`entwuerfe` Z. 178-221, `entwurf` Z. 312-347, Routen Z. 537-550)
- Test: `sales-mcp/tests/test_marketing_pult.py`

**Interfaces:**
- Consumes: `POST /inhalte/{iid}/loeschen` (Task 2).
- Produces: `marketing_pult.inhalt_loeschen(iid: str, mandant: str, von: str) -> dict` (wirft `PultFehler`).
- Produces: Routen `POST /marketing/entwuerfe/loeschen` (Formfeld `iid` mehrfach; Schritt 1, löscht nichts) und `POST /marketing/entwuerfe/loeschen-bestaetigen` (Felder `iid` mehrfach, `bestaetigt=ja`).
- Produces: Konstante `LOESCHBAR = ("entwurf", "abgelehnt")` in `ui_marketing.py`.

- [ ] **Step 1: Tests schreiben:** `test_liste_hat_haken_nur_fuer_loeschbare` (Zeilen `entwurf`, `eingereicht`, `abgelehnt` → genau 2 `name="iid"`-Haken, Knopf „Ausgewählte löschen …“); `test_liste_nutzt_tabelle` (Seite enthält die Karten-Klasse von `ui._tabelle`); `test_loeschen_schritt1_zeigt_titel_und_loescht_nicht` (Pult-Fälschung: kein POST auf `/loeschen`, Seite zeigt beide Titel und `name="bestaetigt"`); `test_loeschen_ohne_haken_400_ohne_aufruf`; `test_loeschen_mehr_als_50_400`; `test_loeschen_bestaetigt_ruft_je_iid_mit_mandant_des_cookies` (zwei POSTs mit `{"mandant": "vibemind", "von": …}`, 303 auf `/marketing/entwuerfe`); `test_loeschen_teilweise_abgelehnt_zeigt_grund` (zweiter Aufruf `PultFehler("abgelehnt", "Unbekannter Inhalt")` → Seite „1 Entwurf gelöscht“ + „Unbekannter Inhalt“); `test_entwurfsseite_hat_loeschen_nur_bei_entwurf_und_verworfen` (eingereicht/freigegeben ohne Löschen-Form); `test_loeschen_ohne_csrf_403`; ungültige UUID in `iid` → 400 ohne Aufruf.
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementieren. Liste: ein `<form method="post" action="/marketing/entwuerfe/loeschen">` um `ui._tabelle([" ", "Titel", "Art", "Status", "Layout", "Fassungen", "Datum"], zeilen, leer="Keine Entwürfe.")`; erste Spalte Haken mit `aria-label="Auswählen: <Titel>"`. Schritt 1 lädt Titel per `GET /inhalte/{iid}` (nur Anzeige; nicht löschbare Status gleich als „nicht löschbar: zur Freigabe/freigegeben“ ausweisen und nicht weitergeben). Mandant aus `marketing_mandant.firma(request)`. Texte: Überschrift „Entwürfe löschen“, Hinweis „Das ist ein echtes Löschen: Fassungen, Rückmeldungen und Aufträge dieser Entwürfe verschwinden. Erzeugte Bilder bleiben in den Medien.“, Haken „Ja, endgültig löschen“, Knopf `class="gefahr"` „Löschen“, Link „Abbrechen, nichts tun“. Log `ui.LOG.warning("Marketing: Entwurf %s gelöscht von %s", iid, von)`.
- [ ] **Step 4:** → PASS; zusätzlich `tests/test_darstellung.py` und `tests/test_ui.py` grün.
- [ ] **Step 5: Commit** (SC) `feat(marketing): Entwürfe aus der Liste löschen`.

### Task 6: Bilder löschen trotz Verwendung (SC)

**Files:**
- Modify: `sales-mcp/marketing_pult.py`, `sales-mcp/ui.py` (`_medien_verweise` Z. 2275, `_newsletter_verweise` Z. 2286, `medien_loeschsperre` Z. 2304, `_medien_loeschen_warnseite` Z. 2342, `aktion_medien_loeschen*` Z. 2392-2436), `sales-mcp/ui_editor.py` (`medien_loeschen` Z. 528-570)
- Test: `sales-mcp/tests/test_ui.py`, `sales-mcp/tests/test_editor_seite.py` (bestehender `test_bild_im_newsletter_sperrt` Z. 993 wird zu `test_bild_im_entwurf_wird_platzhalter`)

**Interfaces:**
- Consumes: `/medien/verweise?mandant=` (Task 2), `/medien/platzhalter`, `/medien/vergessen` (Task 3).
- Produces: `marketing_pult.medien_verweise(name: str, mandant: str | None = None) -> list`; `marketing_pult.medien_platzhalter(name: str, mandant: str, von: str) -> dict`; `marketing_pult.medien_vergessen(name: str) -> None`.
- Produces: `ui.medien_loeschsperre(basis: str, mandant: str) -> tuple[list, list, str | None]` – Newsletter-Einträge tragen `"umstellbar": bool`; `ui.medien_endgueltig_loeschen(basis: str, mandant: str, von: str) -> tuple[list[dict], str | None]` (umgestellte Entwürfe, Fehlertext) führt E7 aus; `ui.laden_mandant() -> str` (`MARKETING_MANDANT` oder `marketing_mandant.VORGABE`).
- Produces: Editor-JSON (Schritt „prüfen“) zusätzlich `"umstellbar": int` und je Newsletter `"umstellbar": bool`.

- [ ] **Step 1: Tests schreiben** (`test_ui.py`): `test_newsletter_medien_approved_sperrt` (Sales-DB: Draft `approved` mit `newsletter_medien = [{"name": "kopf.jpg", …}]` → Warnseite 409 „Nicht löschbar“); `test_newsletter_medien_pending_nur_warnung`; `test_medien_warnseite_nennt_umstellbare_entwuerfe` (Verweis entwurf/bloecke/eigen → Text „wird in 1 Entwurf verwendet“, „Platzhalter“, Bestätigungsknopf vorhanden); `test_eingereicht_sperrt_mit_zurueckziehen` („erst zurückziehen“); `test_freigegeben_sperrt`; `test_fremde_firma_sperrt_ohne_titel` (Text enthält „einer anderen Firma“, keinen fremden Titel); `test_bestaetigen_stellt_um_dann_loescht_dann_vergisst` (Reihenfolge der Pult-Aufrufe `platzhalter` → Datei weg → `vergessen`); `test_platzhalter_gesperrt_loescht_datei_nicht` (Antwort mit nicht-leerem `gesperrt` → 409, Datei liegt noch, Seite nennt umgestellte Titel); `test_marketing_weg_loescht_nicht` (bleibt).
- [ ] **Step 2: Tests anpassen/schreiben** (`test_editor_seite.py`): `test_bild_im_entwurf_wird_platzhalter` (prüfen: `sperre is None`, `umstellbar == 1`; bestätigt: 200, Datei weg, Pult bekam `platzhalter` mit `mandant` des Newsletters); `test_editor_loeschen_nutzt_firma_des_newsletters`; `test_eingereicht_sperrt_im_editor` (409).
- [ ] **Step 3:** → FAIL.
- [ ] **Step 4:** Implementieren. `_medien_verweise` liefert zusätzlich Zeilen `where d.newsletter_medien @> jsonb_build_array(jsonb_build_object('name', %s))` (Spalte `quelle` = `'newsletter'`), Sperre wie `media_ref` bei `approved`. Sperrtexte wörtlich:
  - eingereicht: `„{titel}“ liegt zur Freigabe und trägt das Bild. Erst zurückziehen, dann löschen.`
  - freigegeben: `Das Bild steckt in der freigegebenen Fassung von „{titel}“. Der Versand liest es beim Senden – freigegebene Newsletter bleiben unverändert.`
  - felder: `Das Bild steckt in „{titel}“ (altes Format). Dort erst ein anderes Bild wählen.`
  - fremd: `Das Bild steckt in {n} Entwurf/Entwürfen einer anderen Firma. Dort zuerst ein anderes Bild wählen.`
  - Warnung (keine Sperre): `Das Bild wird in {n} Entwurf/Entwürfen verwendet: {titel}. Dort wird der Platz zum Platzhalter (neue Fassung); ältere Fassungen bleiben unverändert.`
- [ ] **Step 5:** → PASS; `test_darstellung.py`, `test_medien_haertung.py`, `test_dispatch.py` grün.
- [ ] **Step 6: Commit** `feat(medien): benutzte Bilder löschen, Plätze werden Platzhalter`.

### Task 7: Editor-Routen für Vorlagen und Verlauf (SC)

**Files:**
- Modify: `sales-mcp/ui_editor.py` (`CSP_EDITOR` Z. 38; `start`-Dict Z. 259-295; Routen Z. 829-853)
- Test: `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Consumes: `/vorlagen?mandant=&status=freigegeben`, `/vorlagen/{name}/vorschau`, `/inhalte/aus_vorlage`, `/inhalte/{iid}/vorlage`, `/inhalte/{iid}/wiederherstellen` (Task 4).
- Produces Start-Schlüssel: `vorlagen_url` (`/marketing/editor/{iid}/vorlagen.json`), `vorlage_bild_url` (`/marketing/editor/{iid}/vorlage-bild/` – Präfix, Name wird angehängt), `vorlage_url` (`/marketing/editor/{iid}/vorlage`), `wiederherstellen_url` (`/marketing/editor/{iid}/wiederherstellen`), `fassungen` (`[{"fassung": int, "urheber": "agent"|"betreiber", "erstellt_am": str, "format": str}]`, höchstens 30, neueste zuerst).
- Produces Routen: `GET …/vorlagen.json` → `{"vorlagen": [{"name","beschreibung","fassung"}]}` (Mandant des INHALTS; Namen nur wenn `VORLAGE_NAME.match`); `GET …/vorlage-bild/{name}` → gerahmt wie `vorlage_bild` (Z. 780), aber `mandant` = Firma des Inhalts; `POST …/vorlage` JSON `{"vorlage", "art": "anwenden"|"neu", "basis_fassung"?, "titel"?}` mit `X-CSRF` → `anwenden`: `{"fassung": int}`, `neu`: `{"editor_url": "/marketing/editor/<neue id>"}`; `POST …/wiederherstellen` JSON `{"fassung", "basis_fassung"}` → `{"fassung": int}`. Fehler als `{"grund": …}` mit 403/422/503 (`json_grund`).
- `CSP_EDITOR` bekommt `frame-src 'self'`.

- [ ] **Step 1: Tests schreiben:** `test_start_kennt_vorlagen_und_verlauf` (Schlüssel vorhanden, `fassungen` höchstens 30); `test_csp_editor_erlaubt_nur_eigene_rahmen` (`frame-src 'self'` genau einmal, `frame-ancestors 'none'` bleibt); `test_vorlagen_json_nutzt_firma_des_newsletters` (Cookie `mk_mandant=vibemind`, Inhalt `fin2gether` → Pult-Aufruf mit `mandant=fin2gether`); `test_vorlage_anwenden_ohne_csrf_403_ohne_aufruf`; `test_vorlage_anwenden_reicht_basis_weiter`; `test_vorlage_neu_titel_pflicht_422` (leer / > `TITEL_MAX`); `test_vorlage_neu_liefert_editor_url_mit_mandant_des_inhalts`; `test_vorlage_unbekannter_name_422_ohne_aufruf`; `test_wiederherstellen_reicht_ablehnung_als_422_durch`.
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren (Mandant via `GET /inhalte/{iid}` wie `medien_json`, fail-closed ohne Firma → 422). **Step 4:** → PASS, ganze Datei + `test_darstellung.py` grün.
- [ ] **Step 5: Commit** `feat(editor): Routen für Vorlagen und Fassungsverlauf`.

### Task 8: Linke Leiste mit Reitern „Abschnitte | Vorlagen“ (Editor, E8/E9/E10)

**Files:**
- Modify: `editor/src/pult.ts`, `editor/src/App/AbschnittLeiste.tsx`
- Create: `editor/src/App/VorlagenReiter.tsx`, `editor/src/pult.vorlagen.test.ts`, `editor/src/App/VorlagenReiter.test.tsx`

**Interfaces:**
- Consumes: Start-Schlüssel und Routen aus Task 7.
- Produces in `pult.ts`: `type VorlageInfo = { name: string; beschreibung: string; fassung: number }`; `vorlagenListe(s: Start): Promise<VorlageInfo[] | null>` (null = nicht erreichbar); `vorlageAnwenden(s: Start, vorlage: string, basis: number): Promise<Ergebnis>`; `vorlageAlsNeu(s: Start, vorlage: string, titel: string): Promise<{ ok: true; editorUrl: string } | { ok: false; grund: string }>`. Start-Typ um die optionalen Schlüssel aus Task 7 ergänzen (fehlen bei älterem sales-ui → Reiter zeigt „Vorlagen sind hier noch nicht eingerichtet“).

- [ ] **Step 1: Tests schreiben** (`pult.vorlagen.test.ts`, fetch gefälscht wie `pult.medien.test.ts`): Liste filtert Einträge ohne `name`; `vorlageAnwenden` sendet `X-CSRF`, `art: "anwenden"`, `basis_fassung`; 422-Grund kommt als `{ ok: false, grund }`; `vorlageAlsNeu` liefert `editorUrl` nur wenn er mit `/marketing/editor/` beginnt.
- [ ] **Step 2: Tests schreiben** (`VorlagenReiter.test.tsx`, @testing-library wie `Chat/*.test.tsx`): Reiter „Vorlagen“ zeigt je Vorlage Beschreibung und Rahmen mit `sandbox` und `src` = `vorlage_bild_url + name`; „Auf diesen Entwurf anwenden …“ ist deaktiviert bei `ungespeichert` (Tooltip „Erst speichern“) und bei `nurLesen`; Bestätigungsdialog nennt „Aufbau, Gestaltung, Texte und Bilder werden ersetzt. Betreff und Vorschautext bleiben. Deine Fassung {basis} bleibt im Verlauf.“; Ablehnung zeigt den Grund im Dialog und lädt nicht neu; Erfolg ruft `window.location.reload`; „Als neuer Entwurf“ verlangt Titel (1–200 Zeichen) und setzt `window.location.href = editorUrl`.
- [ ] **Step 3:** → FAIL.
- [ ] **Step 4:** Implementieren. `AbschnittLeiste` bekommt MUI-`Tabs` („Abschnitte“, „Vorlagen“), Breite bleibt `ABSCHNITT_LEISTE_BREITE` (240). Abschnittskarten (E10): `display: grid; gridTemplateColumns: '1fr 1fr'; gap: 1`, Karte = Skizze + `subtitle2`-Titel, Beschreibung als `Tooltip`, Klick auf Karte = `abschnittEinsetzen(a.schluessel, Infinity)`, `draggable` bleibt, Karte mit `role="button"`, `aria-label="{Titel} einfügen"`. Vorschau-Rahmen: 600 px breit gerendert, `transform: scale(0.34)`, `transformOrigin: 'top left'`, Box 204×160 mit `overflow: hidden`, `loading="lazy"`, `tabIndex={-1}`. Sperre (`useGesperrt`/`useInert`) gilt für beide Reiter.
- [ ] **Step 5:** `cd editor && npx tsc --noEmit && npx vitest run && npm run build` → grün; danach `sales-mcp`: `tests/test_editor_paket.py` grün.
- [ ] **Step 6: Commit** (inkl. `sales-mcp/static/editor/*`) `feat(editor): Vorlagen im Editor, kompakte Abschnittsleiste`.

### Task 9: Rückgängig/Wiederholen (Editor, E11)

**Files:**
- Modify: `editor/src/documents/editor/EditorContext.tsx`, `editor/src/App/TemplatePanel/index.tsx` (Werkzeugleiste)
- Create: `editor/src/verlauf.test.ts`

**Interfaces:**
- Produces in `EditorContext.tsx`: `rueckgaengig(): boolean`, `wiederholen(): boolean`, `useKannRueckgaengig(): boolean`, `useKannWiederholen(): boolean`; Konstanten `VERLAUF_MAX = 50`, `ZUSAMMENFASSEN_MS = 500`. `setDocument` legt den vorigen Stand ab (innerhalb `ZUSAMMENFASSEN_MS` nach dem letzten Ablegen kein neuer Eintrag) und leert „Wiederholen“; `resetDocument` leert beide Stapel.

- [ ] **Step 1: Tests schreiben** (`verlauf.test.ts`, `vi.useFakeTimers()`): drei `setDocument` im Abstand 600 ms → dreimal `rueckgaengig()` true, Dokument = Ausgang, viertes false; zwei `setDocument` im Abstand 100 ms → ein Schritt; nach `rueckgaengig` + neuem `setDocument` ist `wiederholen()` false; 60 Schritte → nur 50 rückgängig; `resetDocument` → `rueckgaengig()` false (Review Focus 5); `rueckgaengig` löst `onDocumentChange` aus (ungespeichert-Anzeige).
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementieren. Tasten in `TemplatePanel`: `keydown` auf `window`, ignoriert wenn `event.target` ein `input`, `textarea` oder `[contenteditable]` ist oder der Editor gesperrt (`useGesperrt`) bzw. `nurLesen` ist; Strg/Cmd+Z, Strg/Cmd+Umschalt+Z, Strg+Y. Zwei `IconButton` (`UndoOutlined`, `RedoOutlined`) mit Tooltips „Rückgängig (Strg+Z)“ / „Wiederholen (Strg+Umschalt+Z)“, `aria-label` gleich, deaktiviert ohne Schritt.
- [ ] **Step 4:** Editor-Prüfkette grün (tsc, vitest, build), `test_editor_paket.py` grün.
- [ ] **Step 5: Commit** `feat(editor): Rückgängig und Wiederholen`.

### Task 10: Verlauf und Zeichenzähler in der Pult-Leiste (Editor, E12/E13)

**Files:**
- Modify: `editor/src/pult.ts`, `editor/src/App/PultLeiste.tsx`
- Create: `editor/src/zaehler.ts`, `editor/src/zaehler.test.ts`, `editor/src/pult.verlauf.test.ts`

**Interfaces:**
- Consumes: `fassungen`, `wiederherstellen_url`, `vorschau_url` aus dem Start (Task 7).
- Produces: `fassungWiederherstellen(s: Start, fassung: number, basis: number): Promise<Ergebnis>` in `pult.ts`; in `zaehler.ts`: `BETREFF_MAX = 60`, `VORSCHAU_MAX = 100`, `betreffHinweis(text: string): string | null`, `vorschautextHinweis(text: string): string | null` (Texte wörtlich aus E13; gezählt wird `Array.from(text.trim()).length`).

- [ ] **Step 1: Tests schreiben** (`zaehler.test.ts`): 60 Zeichen → null, 61 → Hinweistext; Emoji zählt als 1; Vorschautext `"  "` → Leer-Hinweis, 100 → null, 101 → Längen-Hinweis.
- [ ] **Step 2: Tests schreiben** (`pult.verlauf.test.ts`): sendet `{fassung, basis_fassung}` mit `X-CSRF`; fehlende `wiederherstellen_url` → `{ok:false, grund:'Wiederherstellen ist hier noch nicht eingerichtet'}`.
- [ ] **Step 3:** → FAIL.
- [ ] **Step 4:** Implementieren. Pult-Leiste Zeile 1: Knopf „Verlauf“ (`HistoryOutlined`) öffnet `Menu` mit je Fassung „Fassung N · du|Agent · TT.MM. HH:MM“ (`datumKurz`), Unterpunkte „Ansehen“ (`window.open(vorschau_url + fassung=N&format=mail, '_blank', 'noopener')`) und „Wiederherstellen …“ (nur `format === 'bloecke'`, nicht für die neueste, deaktiviert bei `ungespeichert`/`nurLesen`/Agent; Bestätigung „Fassung N als neue Fassung wiederherstellen? Deine jetzige Fassung {basis} bleibt im Verlauf.“; Erfolg → `window.location.reload()`). Zeile 2: unter Betreff/Vorschautext `helperText` = Zähler „{n}/60“ bzw. „{n}/100“, bei Hinweis `color="warning"`-Text.
- [ ] **Step 5:** Editor-Prüfkette grün, `test_editor_paket.py` grün.
- [ ] **Step 6: Commit** `feat(editor): Fassungsverlauf mit Wiederherstellen, Zähler für Betreff und Vorschautext`.

### Task 11: Bild-Löschdialog mit Platzhalter-Warnung (Editor, E14)

**Files:**
- Modify: `editor/src/pult.ts` (`LoeschInfo`, `medienLoeschen`, `loeschFrage` Z. 393-441), `editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.tsx` (Z. 92-111)
- Test: `editor/src/pult.medien.test.ts`

**Interfaces:**
- Consumes: Editor-JSON aus Task 6 (`umstellbar`, Newsletter mit `umstellbar`).
- Produces: `LoeschInfo = { name; entwuerfe; sperre; umstellbar: number; newsletter: { titel: string; status: string; umstellbar: boolean }[] }`; `loeschFrage(info: LoeschInfo): string` (Warnung aus E4/Task 6 + Sales-Entwürfe + „Das lässt sich nicht rückgängig machen.“).

- [ ] **Step 1: Tests schreiben:** `loeschFrage` mit `umstellbar: 2` und Titeln → enthält „in 2 Entwürfen verwendet“, beide Titel, „Platzhalter“; ältere Antwort ohne `umstellbar` → 0 (kein Absturz); Sperre wird unverändert durchgereicht.
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementieren; `window.confirm` durch MUI-`Dialog` ersetzen (Titel „Bild endgültig löschen?“, Text = `loeschFrage`, Knöpfe „Abbrechen“ / „Endgültig löschen“ `color="error"`). Nach Erfolg mit `umstellbar > 0`: Rückmeldung „„{name}“ gelöscht – {n} Entwürfe zeigen jetzt einen Platzhalter.“ und, wenn der offene Newsletter betroffen ist (sein Titel steht nicht in der Antwort; Prüfung über `standLaden` → neuere Fassung), den bestehenden „neue Fassung“-Weg (`neueFassungLaden`) anstoßen.
- [ ] **Step 4:** Editor-Prüfkette grün, `test_editor_paket.py` grün.
- [ ] **Step 5: Commit** `feat(editor): Löschdialog nennt Entwürfe mit Platzhalter`.

### Task 12: Ausliefern (nur nach Betreiber-OK)

- [ ] **Step 1:** Betreiber-OK für Migration 075 und Deploy einholen; WORKBOARD-Claim eintragen und committen.
- [ ] **Step 2:** Migration 075 auf VM-DB einspielen, danach `verify_063.sql` und `verify_075.sql` über `migration_probe`.
- [ ] **Step 3:** Marketing-API: VM via `deploy/update.sh`, PC-Haupt-Checkout restore (Nachzieh-Prüfung: Abweichung im Haupt-Checkout = abbrechen).
- [ ] **Step 4:** sales-ui mit neuem Editor-Bundle ausliefern.
- [ ] **Step 5:** Rauchprobe am echten System: einen „test“-Entwurf löschen; ein Bild aus einem Test-Entwurf löschen → neue Fassung mit Platzhalter; im Editor Vorlage auf einen Test-Entwurf anwenden und per Verlauf zurückholen; Strg+Z im Canvas.

---

## Offene Fragen an den Betreiber

1. Sollen verworfene (abgelehnte) Entwürfe löschbar sein (E1, so geplant) oder nur „in Arbeit“/„zurückgegeben“ (dein Vorschlag in der Wunschliste)?
2. Vorlage anwenden ohne Textübernahme (E9) – reicht das, oder soll später der Assistent die Texte der alten Fassung in die neue Vorlage übertragen (eigener Plan, braucht Lesezugriff des Agenten auf ältere Fassungen)?
3. Auf `/medien` werden Bilder einer anderen Firma neu gesperrt (E6) – löschen dann nur noch im Editor eines Newsletters dieser Firma. In Ordnung?
