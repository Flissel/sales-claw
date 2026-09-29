# Newsletter-Editor E1 (Editor und Format) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber baut Newsletter im Marketing-Pult mit einem Baukasten-Editor (Email Builder JS) aus 5 Startvorlagen; jede Speicherung ist eine geprüfte Fassung im Blockformat, die Vorschau rendert die Marketing-API über MJML.

**Architecture:** Das Blockdokument von Email Builder JS wird eine zweite Fassungsart (`format='bloecke'`) in `marketing.inhalt_fassungen`, geprüft von einer DB-Funktion. Ein Übersetzer in `spaces/marketing/claw/` macht daraus MJML und rendert mit `mjml-python`. Die Pult-API bekommt Endpunkte für Blöcke und Vorlagen. sales-ui liefert eine eigene Editor-Seite (einzige Route mit Skript, eingebautes Paket), signierte Bild-Adressen für die abgeschottete Vorschau und „Neu aus Vorlage".

**Tech Stack:** PostgreSQL (plpgsql), Python 3.11/3.12, FastAPI, Starlette, `mjml-python==1.4.2` (MIT, abi3-Wheels), React 18 + MUI + Vite (Email Builder JS, MIT, Stand `ce3e610`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-newsletter-editor-design.md` (sales-claw), Plan E1 aus §6. Baut auf `docs/superpowers/specs/2026-09-29-marketing-pult-design.md` und dem ausgelieferten Plan `docs/superpowers/plans/2026-09-29-marketing-pult-stufe-1.md` auf.

## Global Constraints

- Ein Format für Editor und Agent: Email-Builder-JSON `{ "root": {"type":"EmailLayout","data":{...,"childrenIds":[...]}}, "<id>": {"type": ..., "data": {"style": {...}, "props": {...}}} }`.
- Erlaubte Blocktypen: `EmailLayout` (nur als `root`), `Heading`, `Text`, `Button`, `Image`, `Divider`, `Spacer`, `Container`, `ColumnsContainer`. **Nicht** erlaubt: `Html`, `Avatar`.
- Bilder im Dokument nur als `medien:<dateiname>` (Dateiname `^[A-Za-z0-9._-]{1,120}$`); keine fremden Bild-Adressen.
- Links (Button `url`, Image `linkHref`, Markdown-Links in Text) nur `https://`.
- Farben nur `#rrggbb`.
- Grenzen: höchstens 150 Blöcke, Verschachtelung höchstens 4 Ebenen unter `root`, Dokument höchstens 262144 Bytes (JSON-Text), jeder Block genau einmal referenziert (keine Waisen, keine Mehrfachverweise, keine Zyklen).
- Eine Render-Stelle: Marketing-API (`claw/bloecke_mjml.py` + `mjml-python`). Der Editor-eigene Renderer wird nie für Vorschau oder Versand benutzt.
- Pflichtteil des Mandanten (Impressum, Abmeldehinweis) wird beim Rendern fest angehängt; fehlendes Impressum → sichtbarer Hinweis „Impressum fehlt – im Mandanten hinterlegen".
- sales-ui bleibt skriptfrei — **einzige Ausnahme** `GET /marketing/editor/{iid}` mit CSP `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. Das Skript ist nur das eingebaute Paket `sales-mcp/static/editor/editor.js`.
- Editor-Paket: Quelle unter `sales-claw/editor/` (Fork der Beispiel-App, MIT-Lizenz beibehalten), gebautes Paket unter `sales-mcp/static/editor/` mit `MANIFEST.json` (Quell-Commit, SHA-256 je Datei); keine Adresse zu `cdnjs`, `googleapis`, `gstatic`, `unpkg`, `jsdelivr` im Paket.
- Speichern mit Grundlage: Speichern auf veralteter Fassung wird abgelehnt mit „Inzwischen gibt es Fassung N – neu laden oder als Kopie behalten"; `als_kopie=true` speichert trotzdem als neueste.
- Rolle wie das ganze Pult: `freigeben` im Basis-Laden. Die signierte Bild-Route `/marketing/bild/{token}/{name}` ist die **einzige** Pult-Route ohne Anmeldung; sie liefert nur Bilddateien aus den Medien des Ladens und nur mit gültigem, höchstens 15 Minuten altem Token.
- Nur Newsletter bekommen Blöcke; Posts/Material bleiben `format='felder'`.
- Commits: nur eigene Pfade, explizit, per PowerShell. sales-claw `feat/stufe-1-fundament`; vibemind-os nur im Worktree `vibemind-os/.worktrees/setup-agent` (`master`). Kein Push vor Task 7.
- Tests Marketing (Worktree-Wurzel): `C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest <datei> -q`, Umgebung `SALES_CLAW_DIR=C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw`. `mjml-python==1.4.2` muss in diesem `.venv` installiert sein (Task 2 installiert es).
- Tests Sales (Host, eine Datei je Lauf): `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\venv-sales\Scripts\python.exe E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\test_host.py C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw tests/<datei>`.
- VM-DB: `ssh offload-vm 'docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1' < datei`. Migration 053 ist additiv und wird in Task 1 eingespielt (wie 050–052).

## Review Focus

1. **Editor und Agent speichern fast gleichzeitig**: wer auf veralteter Fassung speichert, bekommt die Konflikt-Meldung mit beiden Wegen; „als Kopie" legt eine neue Fassung an, nichts wird still überschrieben. Test in Task 1 (DB) und Task 6 (UI-Endpunkt liefert 409 mit Text).
2. **Bild aus den Medien in der abgeschotteten Vorschau**: erscheint (signierte Adresse), während die Datei ohne gültiges Token 404 liefert; abgelaufenes Token (> 15 min) → 404; Name mit `../` → 404. Test in Task 6.
3. **Dokument vom Editor mit `Html`- oder `Avatar`-Block, `javascript:`-Link, fremder Bild-URL, Waisen-Block**: Speichern wird mit deutschem Grund abgelehnt, die letzte gute Fassung bleibt. Test in Task 1.
4. **Text mit `<script>` oder Markdown-Link auf `http://`**: rendert als Text bzw. ohne Link. Test in Task 2.
5. **Editor-Seite auf dem Handy**: zeigt den Hinweis statt eines kaputten Editors; alle anderen Pult-Seiten bleiben skriptfrei (CSP ohne `script-src`). Test in Task 6.

---

### Task 0: Korrekturen aus dem Browser-Durchlauf vom 29.09.2026 (Pult Stufe 1)

Gefunden beim echten Durchlauf im Browser (Betreiber angemeldet). Vier Fehler, in beiden Repos.

**Files:**
- Modify: `spaces/marketing/claw/pult_render.py` (Worktree) + Test `spaces/marketing/claw/tests/test_pult_render.py`
- Modify: `sales-mcp/ui.py` (sales-claw) + Tests `sales-mcp/tests/test_marketing_pult.py`, `sales-mcp/tests/test_seitenleiste.py`

**Interfaces:**
- Produces: Farbbedeutung, die ab jetzt überall gilt (auch für Task 1/2/4): **`grund`** = Seiten-/Inhaltsfläche, darauf **`text`** (Fließtext) und **`text_hell`** (Überschriften); **`flaeche`** = Kopf- und Fußband, darauf eine Schriftfarbe, die gegen `flaeche` genug Kontrast hat (siehe 0a); **`akzent`/`handlung_text`** = Knopf. Das ist die Bedeutung aus `claw/pdf.py` (`_kopf_und_grund`, `_stile`).

**0a — Layouts „hell" und „warm-sand" unlesbar (`pult_render.mail_html`).** Heute liegt der Inhalt auf `flaeche` (in „hell"/„warm-sand" das dunkle Band) mit dunklem `text` → unlesbar. Neu:
- äußerer Hintergrund und Inhaltskarte: `grund`; Fließtext `text`; Überschriften (`h1`, Abschnittstitel) `text_hell`; Knopf `akzent` mit `handlung_text`.
- Kopfband (nur wenn `kopf_text` oder `logo` gesetzt) und Fußband (Pflichtteil + `fuss_text`) auf `flaeche`; Schriftfarbe im Band = die von `text_hell`, `#ffffff`, `#111111`, die gegen `flaeche` den höchsten Kontrast hat (`schoenheit.kontrast(vorne, hinten)` benutzen), gedämpfte Bandschrift entsprechend `text_leise` oder dieselbe Wahl.
- Tests (in `test_pult_render.py`, mit den echten Gestalten von „dunkel" und „hell" aus `pdf.LAYOUTS`): für jede Gestalt hat der Fließtext gegen seinen Hintergrund mindestens Kontrast 4.5 (`schoenheit.kontrast(text, grund) >= 4.5`, aus dem gerenderten HTML die tatsächlich verwendeten `color`/`background`-Paare der Absätze und des Bandes herauslesen — ein kleiner Regex über `style="…color:#…"` im jeweiligen Container genügt); die bestehenden Tests bleiben grün. Zusätzlich einmal live gegen die VM-DB (lesend) alle drei Layouts rendern und die Kontrastwerte in den Report.
- Das `pdf_bytes`-Rendern bleibt unverändert (es hat die Bedeutung schon richtig).

**0b — Vorschau-Rahmen nur ~140 px hoch.** Die CSS-Regel `.pult-rechts iframe.vorschau { height: 80vh … }` (`ui.py` ~944) existiert, wirkt aber im Browser nicht. Erst messen, dann ändern: im laufenden Test-Client-HTML bzw. per Playwright gegen eine lokale sales-ui die berechnete Höhe (`getComputedStyle(iframe).height`) und die siegende Regel bestimmen (vermutlich eine spätere Regel, z. B. für `iframe.layout-bild`, oder ein fehlender Klassenname am `<iframe>`). Fix so, dass der Rahmen mindestens `min(80vh, 1100px)` hoch ist und am Handy (≤ 767 px) mindestens `70vh`. Test: das gerenderte Entwurfs-HTML trägt `class="vorschau"` am iframe, und im CSS kommt nach der `iframe.vorschau`-Regel keine Regel mehr, die dessen `height` für `.pult-rechts iframe` überschreibt (Test über den CSS-Text von `ui.py`: Reihenfolge der Selektoren). Im Report: gemessene Höhe vorher/nachher.

**0c — Menü markiert „Übersicht" auf allen Marketing-Seiten.** `_seitenleiste` (`ui.py` ~1328/1335) markiert jeden Eintrag, dessen Pfad Vorsilbe des aktuellen ist. Neu: **nur der längste passende Eintrag** ist aktiv, und Detailseiten gehören zu ihrer Liste: Zuordnung `{"/marketing/entwurf": "/marketing/entwuerfe", "/marketing/layout": "/marketing/layouts", "/marketing/layout-bild": "/marketing/layouts"}` (als Konstante neben `_GRUPPEN`, mit Kommentar). Tests in `test_seitenleiste.py` (über `_AKTIVER_PFAD` + `_seitenleiste`, ohne DB-Abhängigkeit — die Zähler fallen leise aus): auf `/marketing` genau „Übersicht" aktiv; auf `/marketing/entwuerfe` und `/marketing/entwurf/<uuid>` genau „Entwürfe"; auf `/marketing/layout/dunkel` genau „Layouts"; auf `/kontakte` weiterhin genau „Kontakte" (Regression).

**0d — Handy-Tableiste mit 6 Reitern bricht um.** In der Handy-Regel für `nav.tabs a` Beschriftung einzeilig: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0` und unter 400 px Breite `font-size: .62rem; letter-spacing: 0`. Test: der CSS-Text enthält diese Eigenschaften im `nav.tabs`-Block der Handy-Regel. Im Report ein Screenshot bei 390×844 (lokal oder nach Auslieferung in Task 7).

- [ ] **Step 1:** Failing tests für 0a–0d schreiben (Marketing im Worktree, Sales im Repo), rot sehen.
- [ ] **Step 2:** 0a–0d umsetzen, grün sehen: `…pytest spaces\marketing\claw	ests	est_pult_render.py -q`; Host-Runner `tests/test_marketing_pult.py`, `tests/test_seitenleiste.py` (2 bekannte Rote bleiben, keine neuen), `tests/test_ui.py`.
- [ ] **Step 3:** Commits je Repo (PowerShell, explizite Pfade):
  - Worktree: `fix(marketing): Mail-Vorschau nutzt die Farbbedeutung der Layouts (grund/flaeche)`
  - sales-claw: `fix(ui): Pult-Vorschau hoch genug, Menue markiert die richtige Seite, Handy-Reiter einzeilig`

---

### Task 1: Blockformat, Prüfung, Vorlagen-Tabelle (Migration 053)

Arbeitsort: Worktree `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent`, `spaces/marketing/db/`.

**Files:**
- Create: `spaces/marketing/db/053_newsletter_bloecke.sql`
- Create: `spaces/marketing/db/verify_053.sql`

**Interfaces:**
- Produces (Spalten): `marketing.inhalt_fassungen.format text NOT NULL DEFAULT 'felder' CHECK (format IN ('felder','bloecke'))`, `marketing.inhalt_fassungen.bloecke jsonb` (Pflicht genau bei `format='bloecke'`).
- Produces (Tabellen): `marketing.newsletter_vorlagen(name text pk ^[a-z][a-z0-9-]{1,40}$, mandant text fk, beschreibung text, bloecke jsonb, status text in ('vorschlag','freigegeben'), fassung int, erstellt_von text, erstellt_am timestamptz)`, `marketing.newsletter_vorlagen_fassungen(vorlage text fk, fassung int, bloecke jsonb, erstellt_von text, erstellt_am, pk(vorlage,fassung))` (unveränderlich per Trigger `marketing._fassung_unveraenderlich`).
- Produces (Funktionen):
  - `marketing.pult_bloecke_fehler(p jsonb) → text|null` (deutscher Grund oder NULL)
  - `marketing.pult_bloecke_speichern(p_inhalt uuid, p_basis int, p_betreff text, p_vorschautext text, p_bloecke jsonb, p_urheber text, p_als_kopie boolean) → int` (neue Fassungsnummer)
  - `marketing.pult_vorlage_speichern(p_name text, p_beschreibung text, p_bloecke jsonb, p_von text, p_status text) → int` (neue Vorlagen-Fassung; legt die Vorlage an, falls neu; Mandant `vibemind`)
  - `marketing.pult_inhalt_aus_vorlage(p_vorlage text, p_titel text, p_mandant text) → uuid` (neuer Newsletter-Entwurf, Fassung 1 `format='bloecke'`, Betreff = Titel)
- Datenregel: eine `format='bloecke'`-Fassung hat `felder = {"betreff": …, "vorschautext": …}` (damit bestehende Leser `felder->>'betreff'` weiter funktionieren) und `layout` = Layout, dessen Farben die Startwerte lieferten (Übernahme: `dunkel`).

- [ ] **Step 1: verify_053.sql schreiben (rot)** — `BEGIN … ROLLBACK`, `PROBE:`-Sätze, Stil `verify_050.sql`.

```sql
-- verify_053.sql — Proben fuer 053_newsletter_bloecke.sql. Aendert nichts.
BEGIN;
CREATE TEMP TABLE _gut AS SELECT '{
 "root":{"type":"EmailLayout","data":{"backdropColor":"#0f2422","canvasColor":"#1d3b39","textColor":"#cfe3df","fontFamily":"MODERN_SANS","childrenIds":["b1","b2","b3","b4"]}},
 "b1":{"type":"Heading","data":{"style":{"padding":{"top":24,"bottom":8,"left":24,"right":24}},"props":{"text":"Neuigkeiten","level":"h1"}}},
 "b2":{"type":"Text","data":{"style":{},"props":{"text":"Hallo **Welt** [mehr](https://vibemind.space)","markdown":true}}},
 "b3":{"type":"Image","data":{"style":{},"props":{"url":"medien:logo.png","alt":"Logo","linkHref":"https://vibemind.space"}}},
 "b4":{"type":"ColumnsContainer","data":{"style":{},"props":{"columnsCount":2,"columns":[{"childrenIds":["b5"]},{"childrenIds":["b6"]},{"childrenIds":[]}]}}},
 "b5":{"type":"Button","data":{"style":{},"props":{"text":"Jetzt","url":"https://vibemind.space","buttonBackgroundColor":"#5eead4"}}},
 "b6":{"type":"Spacer","data":{"style":{},"props":{"height":16}}}
}'::jsonb AS d;
DO $$ DECLARE v text; BEGIN
  v := marketing.pult_bloecke_fehler((SELECT d FROM _gut));
  IF v IS NOT NULL THEN RAISE EXCEPTION 'PROBE: gueltiges Dokument abgelehnt: %', v; END IF;
END $$;
DO $$ DECLARE d jsonb; BEGIN
  d := (SELECT d FROM _gut);
  IF marketing.pult_bloecke_fehler(d || '{"b9":{"type":"Html","data":{"props":{"contents":"<b>x</b>"}}}}'
       || jsonb_build_object('root', jsonb_set(d->'root','{data,childrenIds}', (d#>'{root,data,childrenIds}') || '"b9"'))) IS NULL
    THEN RAISE EXCEPTION 'PROBE: Html-Block angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{b5,data,props,url}','"javascript:alert(1)"')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: javascript-Link angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{b3,data,props,url}','"https://boese.de/x.png"')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: fremde Bildadresse angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{b3,data,props,url}','"medien:../geheim.png"')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: Pfad im Bildnamen angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{b2,data,props,text}','"[x](http://boese.de)"')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: http-Markdown-Link angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(d || '{"waise":{"type":"Spacer","data":{"props":{"height":4}}}}') IS NULL
    THEN RAISE EXCEPTION 'PROBE: Waisen-Block angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{root,data,childrenIds}','["b1","b1","b2","b3","b4"]')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: Mehrfachverweis angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{root,data,childrenIds}','["b1","b2","b3","b4","fehlt"]')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: Verweis auf fehlenden Block angenommen'; END IF;
  IF marketing.pult_bloecke_fehler(jsonb_set(d,'{b5,data,props,buttonBackgroundColor}','"red"')) IS NULL
    THEN RAISE EXCEPTION 'PROBE: Farbe red angenommen'; END IF;
  IF marketing.pult_bloecke_fehler('{"root":{"type":"Text","data":{}}}') IS NULL
    THEN RAISE EXCEPTION 'PROBE: Wurzel ohne EmailLayout angenommen'; END IF;
END $$;
-- Tiefe > 4: Container-Kette
DO $$ DECLARE d jsonb := '{"root":{"type":"EmailLayout","data":{"childrenIds":["c1"]}},
 "c1":{"type":"Container","data":{"props":{"childrenIds":["c2"]}}},
 "c2":{"type":"Container","data":{"props":{"childrenIds":["c3"]}}},
 "c3":{"type":"Container","data":{"props":{"childrenIds":["c4"]}}},
 "c4":{"type":"Container","data":{"props":{"childrenIds":["c5"]}}},
 "c5":{"type":"Container","data":{"props":{"childrenIds":[]}}}}';
BEGIN
  IF marketing.pult_bloecke_fehler(d) IS NULL THEN RAISE EXCEPTION 'PROBE: Tiefe 5 angenommen'; END IF;
END $$;
-- Speichern mit Grundlage
DO $$ DECLARE v_i uuid; v_n int; BEGIN
  v_i := marketing.pult_inhalt_aus_vorlage(
           (SELECT name FROM marketing.newsletter_vorlagen WHERE status='freigegeben' ORDER BY name LIMIT 1),
           'Probe', 'vibemind');
  IF (SELECT format FROM marketing.inhalt_fassungen WHERE inhalt=v_i AND fassung=1) <> 'bloecke' THEN
    RAISE EXCEPTION 'PROBE: aus Vorlage nicht im Blockformat'; END IF;
  v_n := marketing.pult_bloecke_speichern(v_i, 1, 'Betreff', 'Vorab', (SELECT d FROM _gut), 'betreiber', false);
  IF v_n <> 2 THEN RAISE EXCEPTION 'PROBE: erwartet Fassung 2, war %', v_n; END IF;
  BEGIN
    PERFORM marketing.pult_bloecke_speichern(v_i, 1, 'B', '', (SELECT d FROM _gut), 'agent', false);
    RAISE EXCEPTION 'PROBE: veraltete Grundlage angenommen';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
    IF SQLERRM NOT LIKE 'Inzwischen gibt es Fassung 2%' THEN RAISE EXCEPTION 'PROBE: falscher Grund: %', SQLERRM; END IF;
  END;
  v_n := marketing.pult_bloecke_speichern(v_i, 1, 'B', '', (SELECT d FROM _gut), 'betreiber', true);
  IF v_n <> 3 THEN RAISE EXCEPTION 'PROBE: als Kopie nicht Fassung 3'; END IF;
  IF (SELECT felder->>'betreff' FROM marketing.inhalt_fassungen WHERE inhalt=v_i AND fassung=2) <> 'Betreff' THEN
    RAISE EXCEPTION 'PROBE: Betreff nicht in felder gespiegelt'; END IF;
  BEGIN
    PERFORM marketing.pult_bloecke_speichern(v_i, 3, 'B', '', jsonb_set((SELECT d FROM _gut),'{b3,data,props,url}','"https://x.de/a.png"'), 'agent', false);
    RAISE EXCEPTION 'PROBE: ungueltiges Dokument gespeichert';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
  END;
END $$;
-- Posts bekommen keine Bloecke
DO $$ DECLARE v_i uuid; BEGIN
  SELECT id INTO v_i FROM marketing.inhalte WHERE art='post' AND status='entwurf' LIMIT 1;
  PERFORM marketing.pult_bloecke_speichern(v_i,
    (SELECT max(fassung) FROM marketing.inhalt_fassungen WHERE inhalt=v_i), 'x', '', (SELECT d FROM _gut), 'betreiber', false);
  RAISE EXCEPTION 'PROBE: Bloecke fuer einen Post angenommen';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
END $$;
-- Uebernahme: jeder Newsletter-Entwurf hat als neueste Fassung eine Block-Fassung
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM marketing.inhalte i WHERE i.art='newsletter' AND i.status='entwurf'
             AND (SELECT format FROM marketing.inhalt_fassungen f WHERE f.inhalt=i.id
                  ORDER BY fassung DESC LIMIT 1) <> 'bloecke') THEN
    RAISE EXCEPTION 'PROBE: Newsletter-Entwurf nicht uebernommen'; END IF;
  IF EXISTS (SELECT 1 FROM marketing.inhalt_fassungen WHERE format='bloecke'
             AND marketing.pult_bloecke_fehler(bloecke) IS NOT NULL) THEN
    RAISE EXCEPTION 'PROBE: uebernommenes Dokument ungueltig'; END IF;
END $$;
ROLLBACK;
```

Hinweis: Die Probe „aus Vorlage" braucht mindestens eine freigegebene Vorlage. 053 legt dafür die Vorlage `leer` an (Wurzel + eine Überschrift + ein Text, Farben aus `dunkel`, Status `freigegeben`); die 5 Startvorlagen kommen in Task 4.

- [ ] **Step 2: Rot sehen** — `scp` nach `/tmp`, `verify_053.sql` gegen die VM-DB → FEHLER `function marketing.pult_bloecke_fehler(jsonb) does not exist`.

- [ ] **Step 3: 053_newsletter_bloecke.sql schreiben** — idempotent, `BEGIN/COMMIT`.

```sql
-- 053_newsletter_bloecke.sql — Blockformat fuer Newsletter (sales-claw Spec
-- 2026-09-29-newsletter-editor-design.md §3.3/§3.5). Nur Ergaenzungen.
BEGIN;

ALTER TABLE marketing.inhalt_fassungen ADD COLUMN IF NOT EXISTS format text NOT NULL DEFAULT 'felder';
ALTER TABLE marketing.inhalt_fassungen ADD COLUMN IF NOT EXISTS bloecke jsonb;
ALTER TABLE marketing.inhalt_fassungen DROP CONSTRAINT IF EXISTS inhalt_fassungen_format_check;
ALTER TABLE marketing.inhalt_fassungen ADD CONSTRAINT inhalt_fassungen_format_check
  CHECK (format IN ('felder','bloecke') AND ((format = 'bloecke') = (bloecke IS NOT NULL)));

CREATE OR REPLACE FUNCTION marketing._bloecke_farbe_ok(v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT v IS NULL OR jsonb_typeof(v) = 'null'
      OR (jsonb_typeof(v) = 'string' AND v #>> '{}' ~ '^#[0-9a-fA-F]{6}$') $$;

CREATE OR REPLACE FUNCTION marketing._bloecke_zahl_ok(v jsonb, lo numeric, hi numeric) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT v IS NULL OR jsonb_typeof(v) = 'null'
      OR (jsonb_typeof(v) = 'number' AND (v #>> '{}')::numeric BETWEEN lo AND hi) $$;

CREATE OR REPLACE FUNCTION marketing.pult_bloecke_fehler(p jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_id text; v_b jsonb; v_typ text; v_props jsonb; v_style jsonb;
  v_kinder text[]; v_k text; v_n int;
  v_gesehen text[] := ARRAY[]::text[];
  v_front text[]; v_next text[]; v_tiefe int := 0;
  v_farbe text; v_url text;
BEGIN
  IF p IS NULL OR jsonb_typeof(p) <> 'object' THEN RETURN 'Das Dokument muss ein JSON-Objekt sein'; END IF;
  IF length(p::text) > 262144 THEN RETURN 'Das Dokument ist zu gross (hoechstens 256 KB)'; END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(p)) > 151 THEN RETURN 'Hoechstens 150 Bloecke'; END IF;
  IF p->'root'->>'type' IS DISTINCT FROM 'EmailLayout' THEN RETURN 'Die Wurzel muss ein EmailLayout sein'; END IF;

  FOR v_id, v_b IN SELECT key, value FROM jsonb_each(p) LOOP
    IF jsonb_typeof(v_b) <> 'object' THEN RETURN format('Block %s ist kein Objekt', v_id); END IF;
    v_typ := v_b->>'type';
    IF v_id <> 'root' AND v_typ = 'EmailLayout' THEN RETURN 'EmailLayout nur als Wurzel'; END IF;
    IF v_id <> 'root' AND v_id !~ '^[A-Za-z0-9_-]{1,64}$' THEN RETURN format('Ungueltige Block-ID %s', v_id); END IF;
    IF v_typ NOT IN ('EmailLayout','Heading','Text','Button','Image','Divider','Spacer','Container','ColumnsContainer') THEN
      RETURN format('Blocktyp %s ist nicht erlaubt', coalesce(v_typ, '(leer)')); END IF;
    v_props := coalesce(v_b->'data'->'props', v_b->'data', '{}'::jsonb);
    v_style := coalesce(v_b->'data'->'style', '{}'::jsonb);
    -- Farben in style, props und (Wurzel) data
    FOR v_farbe IN SELECT unnest(ARRAY['color','backgroundColor','backdropColor','canvasColor','textColor',
                                       'buttonBackgroundColor','buttonTextColor','lineColor','borderColor']) LOOP
      IF NOT (marketing._bloecke_farbe_ok(v_style->v_farbe) AND marketing._bloecke_farbe_ok(v_props->v_farbe)
              AND marketing._bloecke_farbe_ok(v_b->'data'->v_farbe)) THEN
        RETURN format('Farbe %s in %s muss #rrggbb sein', v_farbe, v_id); END IF;
    END LOOP;
    IF NOT (marketing._bloecke_zahl_ok(v_style->'fontSize', 8, 72)
        AND marketing._bloecke_zahl_ok(v_style->'borderRadius', 0, 32)
        AND marketing._bloecke_zahl_ok(v_props->'width', 1, 600)
        AND marketing._bloecke_zahl_ok(v_props->'height', 0, 600)
        AND marketing._bloecke_zahl_ok(v_props->'lineHeight', 1, 10)
        AND marketing._bloecke_zahl_ok(v_props->'columnsGap', 0, 48)) THEN
      RETURN format('Zahl ausserhalb des erlaubten Bereichs in %s', v_id); END IF;
    IF v_style ? 'padding' AND EXISTS (
         SELECT 1 FROM jsonb_each(v_style->'padding') e
          WHERE NOT marketing._bloecke_zahl_ok(e.value, 0, 80)) THEN
      RETURN format('Abstand in %s muss 0 bis 80 sein', v_id); END IF;
    -- Links
    FOR v_url IN SELECT x FROM unnest(ARRAY[v_props->>'url', v_props->>'linkHref']) x WHERE x IS NOT NULL AND x <> '' LOOP
      IF v_typ = 'Image' AND v_url = v_props->>'url' THEN
        IF v_url !~ '^medien:[A-Za-z0-9._-]{1,120}$' OR v_url ~ '\.\.' THEN
          RETURN format('Bilder nur aus den Medien (medien:<datei>) in %s', v_id); END IF;
      ELSIF v_url !~ '^https://[^\s"<>]+$' THEN
        RETURN format('Links nur mit https:// in %s', v_id); END IF;
    END LOOP;
    IF v_typ = 'Text' AND (v_props->>'text') ~ '\]\((?!https://)' THEN
      RETURN format('Links im Text nur mit https:// in %s', v_id); END IF;
  END LOOP;

  -- Baum: jeder Block genau einmal erreichbar, Tiefe <= 4 unter root
  v_front := ARRAY['root'];
  WHILE array_length(v_front, 1) IS NOT NULL LOOP
    v_next := ARRAY[]::text[];
    FOREACH v_id IN ARRAY v_front LOOP
      v_b := p->v_id;
      IF v_b IS NULL THEN RETURN format('Verweis auf fehlenden Block %s', v_id); END IF;
      IF v_id = ANY(v_gesehen) THEN RETURN format('Block %s mehrfach verwendet', v_id); END IF;
      v_gesehen := v_gesehen || v_id;
      v_kinder := ARRAY(
        SELECT jsonb_array_elements_text(coalesce(v_b->'data'->'childrenIds', v_b->'data'->'props'->'childrenIds', '[]'))
        UNION ALL
        SELECT jsonb_array_elements_text(c->'childrenIds')
          FROM jsonb_array_elements(coalesce(v_b->'data'->'props'->'columns', '[]')) c);
      v_next := v_next || v_kinder;
    END LOOP;
    v_front := v_next;
    IF array_length(v_front, 1) IS NOT NULL THEN v_tiefe := v_tiefe + 1; END IF;
    IF v_tiefe > 4 THEN RETURN 'Hoechstens 4 Ebenen verschachtelt'; END IF;
  END LOOP;
  SELECT count(*) INTO v_n FROM jsonb_object_keys(p);
  IF v_n <> array_length(v_gesehen, 1) THEN RETURN 'Es gibt Bloecke, die nirgends eingebunden sind'; END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_bloecke_speichern(
    p_inhalt uuid, p_basis int, p_betreff text, p_vorschautext text,
    p_bloecke jsonb, p_urheber text, p_als_kopie boolean) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_f text; v_art text; v_status text; v_neueste int;
BEGIN
  v_f := marketing.pult_bloecke_fehler(p_bloecke);
  IF v_f IS NOT NULL THEN RAISE EXCEPTION '%', v_f; END IF;
  IF length(btrim(coalesce(p_betreff, ''))) = 0 THEN RAISE EXCEPTION 'Ohne Betreff gibt es keine Fassung'; END IF;
  SELECT art, status INTO v_art, v_status FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE;
  IF v_art IS NULL THEN RAISE EXCEPTION 'Unbekannter Inhalt'; END IF;
  IF v_art <> 'newsletter' THEN RAISE EXCEPTION 'Bloecke gibt es nur fuer Newsletter'; END IF;
  IF v_status <> 'entwurf' THEN RAISE EXCEPTION 'Nur Entwuerfe lassen sich bearbeiten'; END IF;
  SELECT coalesce(max(fassung), 0) INTO v_neueste FROM marketing.inhalt_fassungen WHERE inhalt = p_inhalt;
  IF p_basis IS DISTINCT FROM v_neueste AND NOT coalesce(p_als_kopie, false) THEN
    RAISE EXCEPTION 'Inzwischen gibt es Fassung % - neu laden oder als Kopie behalten', v_neueste; END IF;
  INSERT INTO marketing.inhalt_fassungen (inhalt, fassung, felder, layout, layout_fassung, urheber, format, bloecke)
  VALUES (p_inhalt, v_neueste + 1,
          jsonb_build_object('betreff', btrim(p_betreff), 'vorschautext', coalesce(p_vorschautext, '')),
          'dunkel', (SELECT fassung FROM marketing.layout_vorlagen WHERE name = 'dunkel'),
          p_urheber, 'bloecke', p_bloecke);
  RETURN v_neueste + 1;
END $$;

CREATE TABLE IF NOT EXISTS marketing.newsletter_vorlagen (
    name         text PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9-]{1,40}$'),
    mandant      text NOT NULL DEFAULT 'vibemind' REFERENCES marketing.mandanten(id),
    beschreibung text NOT NULL DEFAULT '',
    bloecke      jsonb NOT NULL,
    status       text NOT NULL DEFAULT 'vorschlag' CHECK (status IN ('vorschlag','freigegeben')),
    fassung      int  NOT NULL DEFAULT 1,
    erstellt_von text NOT NULL,
    erstellt_am  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS marketing.newsletter_vorlagen_fassungen (
    vorlage      text NOT NULL REFERENCES marketing.newsletter_vorlagen(name),
    fassung      int  NOT NULL,
    bloecke      jsonb NOT NULL,
    erstellt_von text NOT NULL,
    erstellt_am  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vorlage, fassung)
);
DROP TRIGGER IF EXISTS trg_vorlage_fassung_unveraenderlich ON marketing.newsletter_vorlagen_fassungen;
CREATE TRIGGER trg_vorlage_fassung_unveraenderlich
  BEFORE UPDATE OR DELETE ON marketing.newsletter_vorlagen_fassungen
  FOR EACH ROW EXECUTE FUNCTION marketing._fassung_unveraenderlich();

CREATE OR REPLACE FUNCTION marketing.pult_vorlage_speichern(
    p_name text, p_beschreibung text, p_bloecke jsonb, p_von text, p_status text) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_f text; v_n int;
BEGIN
  v_f := marketing.pult_bloecke_fehler(p_bloecke);
  IF v_f IS NOT NULL THEN RAISE EXCEPTION 'Vorlage ungueltig: %', v_f; END IF;
  IF p_status NOT IN ('vorschlag','freigegeben') THEN RAISE EXCEPTION 'Status muss vorschlag oder freigegeben sein'; END IF;
  INSERT INTO marketing.newsletter_vorlagen (name, beschreibung, bloecke, status, fassung, erstellt_von)
  VALUES (p_name, coalesce(p_beschreibung, ''), p_bloecke, p_status, 0, p_von)
  ON CONFLICT (name) DO NOTHING;
  PERFORM 1 FROM marketing.newsletter_vorlagen WHERE name = p_name FOR UPDATE;
  SELECT coalesce(max(fassung), 0) + 1 INTO v_n FROM marketing.newsletter_vorlagen_fassungen WHERE vorlage = p_name;
  INSERT INTO marketing.newsletter_vorlagen_fassungen (vorlage, fassung, bloecke, erstellt_von)
  VALUES (p_name, v_n, p_bloecke, p_von);
  UPDATE marketing.newsletter_vorlagen
     SET bloecke = p_bloecke, beschreibung = coalesce(p_beschreibung, beschreibung),
         status = p_status, fassung = v_n
   WHERE name = p_name;
  RETURN v_n;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_inhalt_aus_vorlage(
    p_vorlage text, p_titel text, p_mandant text) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_b jsonb; v_id uuid;
BEGIN
  IF length(btrim(coalesce(p_titel, ''))) = 0 THEN RAISE EXCEPTION 'Ohne Titel kein Newsletter'; END IF;
  SELECT bloecke INTO v_b FROM marketing.newsletter_vorlagen
   WHERE name = p_vorlage AND status = 'freigegeben' AND mandant = p_mandant;
  IF v_b IS NULL THEN RAISE EXCEPTION 'Vorlage % gibt es nicht oder sie ist nicht freigegeben', p_vorlage; END IF;
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES (p_mandant, 'newsletter', btrim(p_titel))
  RETURNING id INTO v_id;
  INSERT INTO marketing.inhalt_fassungen (inhalt, fassung, felder, layout, layout_fassung, urheber, format, bloecke)
  VALUES (v_id, 1, jsonb_build_object('betreff', btrim(p_titel), 'vorschautext', ''),
          'dunkel', (SELECT fassung FROM marketing.layout_vorlagen WHERE name = 'dunkel'),
          'betreiber', 'bloecke', v_b);
  RETURN v_id;
END $$;

-- Vorlage 'leer' (Grundlage fuer die Probe und fuer "leer anfangen"), Farben aus 'dunkel'
DO $$ DECLARE g jsonb; BEGIN
  IF NOT EXISTS (SELECT 1 FROM marketing.newsletter_vorlagen WHERE name = 'leer') THEN
    SELECT gestalt INTO g FROM marketing.layout_vorlagen WHERE name = 'dunkel';
    PERFORM marketing.pult_vorlage_speichern('leer', 'Leerer Newsletter mit Ueberschrift und Text',
      jsonb_build_object(
        'root', jsonb_build_object('type','EmailLayout','data', jsonb_build_object(
            'backdropColor', g->>'flaeche', 'canvasColor', g->>'grund', 'textColor', g->>'text',
            'fontFamily','MODERN_SANS', 'childrenIds', '["kopf","text"]'::jsonb)),
        'kopf', '{"type":"Heading","data":{"style":{"padding":{"top":32,"bottom":8,"left":24,"right":24}},"props":{"text":"Ueberschrift","level":"h1"}}}'::jsonb,
        'text', '{"type":"Text","data":{"style":{"padding":{"top":8,"bottom":24,"left":24,"right":24}},"props":{"text":"Dein Text.","markdown":true}}}'::jsonb),
      'migration-053', 'freigegeben');
  END IF;
END $$;

-- Uebernahme: jeder Newsletter-Entwurf bekommt eine Block-Fassung aus seiner neuesten Feld-Fassung
DO $$ DECLARE r record; g jsonb; v_kinder jsonb; v_doc jsonb; a jsonb; i int; BEGIN
  SELECT gestalt INTO g FROM marketing.layout_vorlagen WHERE name = 'dunkel';
  FOR r IN
    SELECT i.id, f.fassung, f.felder FROM marketing.inhalte i
      JOIN LATERAL (SELECT * FROM marketing.inhalt_fassungen x WHERE x.inhalt = i.id
                    ORDER BY x.fassung DESC LIMIT 1) f ON true
     WHERE i.art = 'newsletter' AND i.status = 'entwurf' AND f.format = 'felder'
  LOOP
    v_kinder := '[]'::jsonb; v_doc := '{}'::jsonb; i := 0;
    FOR a IN SELECT * FROM jsonb_array_elements(coalesce(r.felder->'abschnitte', '[]')) LOOP
      i := i + 1;
      IF length(btrim(coalesce(a->>'titel', ''))) > 0 THEN
        v_doc := v_doc || jsonb_build_object('h' || i, jsonb_build_object('type','Heading','data',
                   jsonb_build_object('style','{"padding":{"top":16,"bottom":4,"left":24,"right":24}}'::jsonb,
                                      'props', jsonb_build_object('text', a->>'titel', 'level','h2'))));
        v_kinder := v_kinder || to_jsonb('h' || i);
      END IF;
      v_doc := v_doc || jsonb_build_object('t' || i, jsonb_build_object('type','Text','data',
                 jsonb_build_object('style','{"padding":{"top":4,"bottom":12,"left":24,"right":24}}'::jsonb,
                                    'props', jsonb_build_object('text', coalesce(a->>'text',''), 'markdown', false))));
      v_kinder := v_kinder || to_jsonb('t' || i);
    END LOOP;
    IF coalesce(r.felder->>'knopf_link','') ~ '^https://' AND length(btrim(coalesce(r.felder->>'knopf_text',''))) > 0 THEN
      v_doc := v_doc || jsonb_build_object('knopf', jsonb_build_object('type','Button','data',
                 jsonb_build_object('style','{"padding":{"top":12,"bottom":24,"left":24,"right":24}}'::jsonb,
                                    'props', jsonb_build_object('text', r.felder->>'knopf_text', 'url', r.felder->>'knopf_link',
                                                                'buttonBackgroundColor', g->>'akzent', 'buttonTextColor', g->>'handlung_text'))));
      v_kinder := v_kinder || '"knopf"'::jsonb;
    END IF;
    v_doc := v_doc || jsonb_build_object('root', jsonb_build_object('type','EmailLayout','data', jsonb_build_object(
               'backdropColor', g->>'flaeche', 'canvasColor', g->>'grund', 'textColor', g->>'text',
               'fontFamily','MODERN_SANS', 'childrenIds', v_kinder)));
    IF marketing.pult_bloecke_fehler(v_doc) IS NULL THEN
      PERFORM marketing.pult_bloecke_speichern(r.id, r.fassung,
                coalesce(nullif(btrim(r.felder->>'betreff'),''), 'Newsletter'),
                coalesce(r.felder->>'vorschautext',''), v_doc, 'agent', false);
    ELSE
      RAISE NOTICE 'Uebernahme uebersprungen fuer %: %', r.id, marketing.pult_bloecke_fehler(v_doc);
    END IF;
  END LOOP;
END $$;

COMMIT;
```

Vor dem Festschreiben prüfen und im Report belegen: (a) die tatsächliche Struktur von `Container`/`ColumnsContainer` in Email Builder JS (`childrenIds` unter `data.props` bzw. `data.props.columns[].childrenIds`) gegen `packages/block-container` und `packages/block-columns-container` im Scratchpad-Klon `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\pruefung\ebj` und `examples/vite-emailbuilder-mui/src/documents/blocks/*` — die Prüfung liest genau die Pfade, die das Editor-Dokument benutzt; (b) dass Text-Blöcke ohne Markdown-Links nicht fälschlich abgelehnt werden (die Regex prüft nur `](`). Weicht die Struktur ab: Prüfung anpassen, Probe unverändert in ihrer Absicht.

- [ ] **Step 4: Einspielen und grün sehen** — 053 auf der VM, `verify_050…053` grün, 053 ein zweites Mal (idempotent: keine zweite Übernahme, weil die neueste Fassung schon `bloecke` ist), `verify_053` erneut grün. Live-Zählung in den Report: `SELECT format, count(*) FROM marketing.inhalt_fassungen GROUP BY 1`.

- [ ] **Step 5: Commit** (PowerShell, Worktree)

```powershell
git add -- spaces/marketing/db/053_newsletter_bloecke.sql spaces/marketing/db/verify_053.sql
git commit -m "feat(marketing): Blockformat fuer Newsletter, Pruefung und Vorlagen (053)"
```

---

### Task 2: Übersetzer Blöcke → MJML → HTML

Arbeitsort: Worktree, `spaces/marketing/claw/`.

**Files:**
- Create: `spaces/marketing/claw/bloecke_mjml.py`
- Test: `spaces/marketing/claw/tests/test_bloecke_mjml.py`
- Modify: `spaces/marketing/requirements.txt` falls vorhanden (sonst im Report nennen, wo Marketing-Abhängigkeiten stehen) — `mjml-python==1.4.2`

**Interfaces:**
- Produces:
  - `bloecke_mjml.nach_mjml(dokument: dict, betreff: str, vorschautext: str, pflichtteil: dict, bild_basis: str = "", breite: int = 600) -> str`
  - `bloecke_mjml.rendern(dokument: dict, betreff: str, vorschautext: str, pflichtteil: dict, bild_basis: str = "", handy: bool = False) -> str` (HTML über `mjml.mjml2html`; `handy=True` → `breite=380`)
  - `bloecke_mjml.bild_adresse(url: str, bild_basis: str) -> str | None` (`medien:<name>` → `bild_basis + quote(name)`; leeres `bild_basis` → `None`)
  - `bloecke_mjml.RenderFehler(Exception)` (MJML-Fehler, deutsch)

- [ ] **Step 0: `mjml-python` installieren** — `C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pip install mjml-python==1.4.2` (abi3-Wheel, gemessen 29.09.). Im Report die Version aus `pip show mjml-python`.

- [ ] **Step 1: Failing tests**

```python
"""Uebersetzer Bloecke -> MJML -> HTML (Spec 2026-09-29-newsletter-editor-design.md §3.4)."""
from spaces.marketing.claw import bloecke_mjml as b

PFLICHT = {"impressum": "VibeMind, Musterstr. 1", "abmelde_hinweis": "Abmelden: {abmeldelink}"}
DOK = {
    "root": {"type": "EmailLayout", "data": {"backdropColor": "#0f2422", "canvasColor": "#1d3b39",
             "textColor": "#cfe3df", "fontFamily": "BOOK_SERIF", "childrenIds": ["h", "t", "i", "c", "k", "d", "s"]}},
    "h": {"type": "Heading", "data": {"style": {"textAlign": "center"}, "props": {"text": "Neuigkeiten", "level": "h1"}}},
    "t": {"type": "Text", "data": {"style": {}, "props": {"text": "Hallo **Welt** und *mehr* [Link](https://vibemind.space) <script>x</script>", "markdown": True}}},
    "i": {"type": "Image", "data": {"style": {}, "props": {"url": "medien:logo.png", "alt": "Logo", "width": 120}}},
    "c": {"type": "ColumnsContainer", "data": {"style": {}, "props": {"columnsCount": 2,
          "columns": [{"childrenIds": ["c1"]}, {"childrenIds": ["c2"]}, {"childrenIds": []}]}}},
    "c1": {"type": "Text", "data": {"props": {"text": "Links"}}},
    "c2": {"type": "Text", "data": {"props": {"text": "Rechts"}}},
    "k": {"type": "Button", "data": {"style": {}, "props": {"text": "Jetzt", "url": "https://vibemind.space",
          "buttonBackgroundColor": "#5eead4", "buttonTextColor": "#0f2422", "buttonStyle": "pill"}}},
    "d": {"type": "Divider", "data": {"props": {"lineColor": "#8aa3a0", "lineHeight": 1}}},
    "s": {"type": "Spacer", "data": {"props": {"height": 24}}},
}


def test_mjml_hat_alle_bausteine():
    m = b.nach_mjml(DOK, "Betreff", "Vorab", PFLICHT, bild_basis="https://x.ts.net/marketing/bild/t/")
    for teil in ("<mjml", "<mj-preview>Vorab</mj-preview>", "<mj-title>Betreff</mj-title>",
                 'background-color="#0f2422"', "<mj-column", "<mj-image", "<mj-button", "<mj-divider",
                 "<mj-spacer", "Georgia"):
        assert teil in m, teil


def test_html_rendert_und_haelt_outlook():
    html = b.rendern(DOK, "Betreff", "Vorab", PFLICHT, bild_basis="https://x.ts.net/marketing/bild/t/")
    assert html.lower().startswith("<!doctype html") and "mso" in html
    for teil in ("Neuigkeiten", "<strong>Welt</strong>", "<em>mehr</em>", 'href="https://vibemind.space"',
                 "Links", "Rechts", "Jetzt", "https://x.ts.net/marketing/bild/t/logo.png"):
        assert teil in html, teil


def test_skript_bleibt_text():
    html = b.rendern(DOK, "B", "", PFLICHT)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_http_markdown_link_wird_nur_text():
    d = {**DOK, "t": {"type": "Text", "data": {"props": {"text": "[x](http://boese.de)", "markdown": True}}}}
    html = b.rendern(d, "B", "", PFLICHT)
    assert 'href="http://boese.de"' not in html
    assert "x" in html.split("<body")[1]


def test_ohne_markdown_keine_auszeichnung():
    d = {**DOK, "t": {"type": "Text", "data": {"props": {"text": "**nicht fett**", "markdown": False}}}}
    assert "<strong>" not in b.rendern(d, "B", "", PFLICHT)


def test_pflichtteil_immer_am_ende():
    html = b.rendern(DOK, "B", "", PFLICHT)
    assert html.rfind("Musterstr. 1") > html.rfind("Jetzt")
    assert "[Abmeldelink]" in html and "{abmeldelink}" not in html
    ohne = b.rendern(DOK, "B", "", dict(PFLICHT, impressum=""))
    assert "Impressum fehlt" in ohne


def test_handy_ist_schmaler():
    assert 'width="380px"' in b.nach_mjml(DOK, "B", "", PFLICHT, breite=380)


def test_bild_ohne_basis_wird_platzhalter():
    html = b.rendern(DOK, "B", "", PFLICHT, bild_basis="")
    assert "[Bild: logo.png]" in html
    assert 'src="' not in html.split("[Bild: logo.png]")[0].split("Neuigkeiten")[-1]


def test_bild_adresse():
    assert b.bild_adresse("medien:a b.png", "https://h/m/") == "https://h/m/a%20b.png"
    assert b.bild_adresse("medien:a.png", "") is None
    assert b.bild_adresse("https://boese.de/x.png", "https://h/m/") is None


def test_render_fehler_ist_deutsch(monkeypatch):
    import mjml
    def wirft(_):
        raise ValueError("kaputt")
    monkeypatch.setattr(mjml, "mjml2html", wirft)
    try:
        b.rendern(DOK, "B", "", PFLICHT)
    except b.RenderFehler as e:
        assert "Newsletter" in str(e)
    else:
        raise AssertionError("RenderFehler erwartet")
```

- [ ] **Step 2: Rot sehen** — `…python.exe -m pytest spaces\marketing\claw\tests\test_bloecke_mjml.py -q` → `ImportError`.

- [ ] **Step 3: Implementieren** — `spaces/marketing/claw/bloecke_mjml.py`:

```python
"""Uebersetzer Email-Builder-Bloecke -> MJML -> HTML (sales-claw Spec
2026-09-29-newsletter-editor-design.md §3.4). EINE Render-Stelle fuer die
Vorschau und spaeter den Versand. Das Dokument ist vorher von
marketing.pult_bloecke_fehler geprueft; hier trotzdem alles Fremde escapen.
Pflichtteil des Mandanten wird immer am Ende angehaengt."""
from __future__ import annotations

import html
import re
import urllib.parse

import mjml

SCHRIFTEN = {
    "MODERN_SANS": "'Helvetica Neue', Helvetica, Arial, sans-serif",
    "BOOK_SANS": "Optima, Candara, 'Noto Sans', source-sans-pro, sans-serif",
    "ORGANIC_SANS": "Seravek, 'Gill Sans Nova', Ubuntu, Calibri, 'DejaVu Sans', source-sans-pro, sans-serif",
    "GEOMETRIC_SANS": "Avenir, 'Avenir Next LT Pro', Montserrat, Corbel, 'URW Gothic', source-sans-pro, sans-serif",
    "HEAVY_SANS": "Bahnschrift, 'DIN Alternate', 'Franklin Gothic Medium', 'Nimbus Sans Narrow', sans-serif-condensed, sans-serif",
    "ROUNDED_SANS": "ui-rounded, 'Hiragino Maru Gothic ProN', Quicksand, Comfortaa, Manjari, 'Arial Rounded MT Bold', Calibri, source-sans-pro, sans-serif",
    "MODERN_SERIF": "Charter, 'Bitstream Charter', 'Sitka Text', Cambria, serif",
    "BOOK_SERIF": "'Iowan Old Style', 'Palatino Linotype', 'URW Palladio L', P052, Georgia, serif",
    "MONOSPACE": "'Nimbus Mono PS', 'Courier New', 'Cutive Mono', monospace",
}
GROESSE_UEBERSCHRIFT = {"h1": 32, "h2": 24, "h3": 20}
KNOPF_RUNDUNG = {"rectangle": 0, "rounded": 6, "pill": 64}
_FETT = re.compile(r"\*\*(.+?)\*\*")
_KURSIV = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


class RenderFehler(Exception):
    pass


def _a(wert) -> str:
    return html.escape(str(wert if wert is not None else ""), quote=True)


def _polster(style: dict) -> str:
    p = style.get("padding") or {}
    return f'{int(p.get("top", 0))}px {int(p.get("right", 24))}px {int(p.get("bottom", 0))}px {int(p.get("left", 24))}px'


def bild_adresse(url: str, bild_basis: str) -> str | None:
    if not bild_basis or not isinstance(url, str) or not url.startswith("medien:"):
        return None
    return bild_basis + urllib.parse.quote(url[len("medien:"):])


def _text(roh: str, markdown: bool) -> str:
    sicher = _a(roh)
    if markdown:
        def link(m):
            ziel = html.unescape(m.group(2))
            if not ziel.startswith("https://"):
                return m.group(1)
            return f'<a href="{_a(ziel)}" style="color:inherit">{m.group(1)}</a>'
        sicher = _LINK.sub(link, sicher)
        sicher = _FETT.sub(r"<strong>\1</strong>", sicher)
        sicher = _KURSIV.sub(r"<em>\1</em>", sicher)
    return sicher.replace("\n", "<br>")


def _block(dok: dict, bid: str, farben: dict, bild_basis: str) -> str:
    b = dok.get(bid) or {}
    typ = b.get("type")
    data = b.get("data") or {}
    s, p = data.get("style") or {}, data.get("props") or {}
    polster = _polster(s)
    ausr = s.get("textAlign") or "left"
    farbe = s.get("color") or farben["text"]
    if typ == "Heading":
        groesse = GROESSE_UEBERSCHRIFT.get(p.get("level") or "h2", 24)
        return (f'<mj-text padding="{polster}" align="{_a(ausr)}" color="{_a(farbe)}" font-size="{groesse}px" '
                f'font-weight="{_a(s.get("fontWeight") or "bold")}" line-height="1.25">{_text(p.get("text") or "", False)}</mj-text>')
    if typ == "Text":
        groesse = int(s.get("fontSize") or 16)
        return (f'<mj-text padding="{polster}" align="{_a(ausr)}" color="{_a(farbe)}" font-size="{groesse}px" '
                f'font-weight="{_a(s.get("fontWeight") or "normal")}" line-height="1.55">'
                f'{_text(p.get("text") or "", bool(p.get("markdown")))}</mj-text>')
    if typ == "Image":
        ziel = bild_adresse(p.get("url") or "", bild_basis)
        if not ziel:
            name = (p.get("url") or "")[len("medien:"):] or "?"
            return f'<mj-text padding="{polster}" align="center" color="{_a(farben["text"])}">[Bild: {_a(name)}]</mj-text>'
        breite = f' width="{int(p["width"])}px"' if p.get("width") else ""
        link = p.get("linkHref") or ""
        href = f' href="{_a(link)}"' if link.startswith("https://") else ""
        return f'<mj-image padding="{polster}" src="{_a(ziel)}" alt="{_a(p.get("alt") or "")}"{breite}{href} />'
    if typ == "Button":
        url = p.get("url") or ""
        if not url.startswith("https://"):
            return ""
        rund = KNOPF_RUNDUNG.get(p.get("buttonStyle") or "rounded", 6)
        return (f'<mj-button padding="{polster}" href="{_a(url)}" align="{_a(ausr)}" border-radius="{rund}px" '
                f'background-color="{_a(p.get("buttonBackgroundColor") or farben["akzent"])}" '
                f'color="{_a(p.get("buttonTextColor") or "#ffffff")}" font-weight="bold">{_text(p.get("text") or "", False)}</mj-button>')
    if typ == "Divider":
        return (f'<mj-divider padding="{polster}" border-color="{_a(p.get("lineColor") or "#cccccc")}" '
                f'border-width="{int(p.get("lineHeight") or 1)}px" />')
    if typ == "Spacer":
        return f'<mj-spacer height="{int(p.get("height") or 16)}px" />'
    return ""


def _kinder_als_section(dok: dict, ids: list, farben: dict, bild_basis: str) -> str:
    teile, spalte = [], []
    def spalte_schliessen():
        if spalte:
            teile.append(f'<mj-section background-color="{_a(farben["flaeche"])}" padding="0"><mj-column>{"".join(spalte)}</mj-column></mj-section>')
            spalte.clear()
    for bid in ids:
        b = dok.get(bid) or {}
        typ = b.get("type")
        props = (b.get("data") or {}).get("props") or {}
        if typ == "ColumnsContainer":
            spalte_schliessen()
            anzahl = int(props.get("columnsCount") or 2)
            spalten = (props.get("columns") or [])[:anzahl]
            inhalt = "".join(
                "<mj-column>" + "".join(_block(dok, k, farben, bild_basis) for k in (c.get("childrenIds") or [])) + "</mj-column>"
                for c in spalten)
            teile.append(f'<mj-section background-color="{_a(farben["flaeche"])}" padding="0">{inhalt}</mj-section>')
        elif typ == "Container":
            spalte_schliessen()
            stil = (b.get("data") or {}).get("style") or {}
            hg = stil.get("backgroundColor") or farben["flaeche"]
            kinder = props.get("childrenIds") or []
            inhalt = "".join(_block(dok, k, farben, bild_basis) for k in kinder)
            teile.append(f'<mj-section background-color="{_a(hg)}" border-radius="{int(stil.get("borderRadius") or 0)}px" '
                         f'padding="{_polster(stil)}"><mj-column>{inhalt}</mj-column></mj-section>')
        else:
            spalte.append(_block(dok, bid, farben, bild_basis))
    spalte_schliessen()
    return "".join(teile)


def nach_mjml(dokument: dict, betreff: str, vorschautext: str, pflichtteil: dict,
              bild_basis: str = "", breite: int = 600) -> str:
    wurzel = (dokument.get("root") or {}).get("data") or {}
    farben = {"grund": wurzel.get("backdropColor") or "#f2f5f7",
              "flaeche": wurzel.get("canvasColor") or "#ffffff",
              "text": wurzel.get("textColor") or "#242424",
              "akzent": "#5eead4"}
    schrift = SCHRIFTEN.get(wurzel.get("fontFamily") or "MODERN_SANS", SCHRIFTEN["MODERN_SANS"])
    rumpf = _kinder_als_section(dokument, wurzel.get("childrenIds") or [], farben, bild_basis)
    impressum = (pflichtteil.get("impressum") or "").strip()
    impressum_html = (_a(impressum) if impressum else
                      '<strong style="color:#ef4444">Impressum fehlt &ndash; im Mandanten hinterlegen</strong>')
    abmelden = _a((pflichtteil.get("abmelde_hinweis") or "").replace("{abmeldelink}", "[Abmeldelink]"))
    fuss = (f'<mj-section padding="16px 0"><mj-column><mj-text align="center" font-size="11px" '
            f'color="{_a(farben["text"])}" line-height="1.5">{impressum_html}<br>{abmelden}</mj-text></mj-column></mj-section>')
    return (f'<mjml><mj-head><mj-title>{_a(betreff)}</mj-title><mj-preview>{_a(vorschautext)}</mj-preview>'
            f'<mj-attributes><mj-all font-family="{_a(schrift)}" /></mj-attributes></mj-head>'
            f'<mj-body background-color="{_a(farben["grund"])}" width="{int(breite)}px">{rumpf}{fuss}</mj-body></mjml>')


def rendern(dokument: dict, betreff: str, vorschautext: str, pflichtteil: dict,
            bild_basis: str = "", handy: bool = False) -> str:
    quelle = nach_mjml(dokument, betreff, vorschautext, pflichtteil, bild_basis, 380 if handy else 600)
    try:
        return mjml.mjml2html(quelle)
    except Exception as e:  # mrml meldet Englisch; nach aussen deutsch
        raise RenderFehler(f"Der Newsletter liess sich nicht setzen: {e}") from e
```

Vor dem Festschreiben die Schrift-Tabelle gegen `packages/block-text/src/index.tsx` (`getFontFamily`) im Scratchpad-Klon prüfen und die Werte von dort 1:1 übernehmen; im Report nennen. Nach dem Rendern jedes Test-HTML einmal mit `mjml.mjml2html` validieren (Aufruf wirft bei ungültigem MJML).

- [ ] **Step 4: Grün sehen** — `test_bloecke_mjml.py` PASS; `spaces\marketing\claw\tests -q` einmal ganz.

- [ ] **Step 5: Commit**

```powershell
git add -- spaces/marketing/claw/bloecke_mjml.py spaces/marketing/claw/tests/test_bloecke_mjml.py
git commit -m "feat(marketing): Uebersetzer Bloecke -> MJML -> HTML"
```

(requirements-Datei mit aufnehmen, wenn es eine gibt.)

---

### Task 3: Pult-API für Blöcke und Vorlagen

Arbeitsort: Worktree, `spaces/marketing/api/pult.py`, `spaces/marketing/tests/test_pult_api.py`.

**Interfaces:**
- Consumes: Task 1 (Funktionen/Spalten), Task 2 (`bloecke_mjml.rendern`, `RenderFehler`).
- Produces (alle mit `X-Pult-Key`, gleiche Fehlerabbildung wie der bestehende Router — `_lesen`, `_lesen_einer`, `_schreiben`):
  - `GET /api/pult/inhalte/{id}` — `fassungen[]` tragen zusätzlich `format` und `bloecke` (null bei `felder`).
  - `POST /api/pult/inhalte/{id}/bloecke` Body `{basis_fassung:int≥0, betreff, vorschautext, bloecke:dict, als_kopie:bool=false, urheber:"betreiber"|"agent"="betreiber"}` → `{"fassung": n}`. DB-Ablehnung → 422 mit Grund (enthält bei Konflikt „Inzwischen gibt es Fassung …").
  - `GET /api/pult/inhalte/{id}/vorschau?fassung=&format=mail|handy|pdf&bild_basis=` — Fassung mit `format='bloecke'`: `bloecke_mjml.rendern(...)`; `format=pdf` → 422 „PDF gibt es für Editor-Newsletter noch nicht"; `bild_basis` nur akzeptiert, wenn es mit `https://` beginnt, auf `/` endet und keine Anführungszeichen/Leerzeichen enthält, sonst 422; `RenderFehler` → 422 mit Text.
  - `GET /api/pult/vorlagen?mandant=vibemind&status=` → `{"vorlagen":[{name, beschreibung, status, fassung}]}`
  - `GET /api/pult/vorlagen/{name}/vorschau?format=mail|handy&bild_basis=` → HTML (Betreff = Beschreibung, Pflichtteil des Mandanten).
  - `POST /api/pult/inhalte/aus_vorlage` Body `{vorlage, titel, mandant="vibemind"}` → `{"id": "<uuid>"}`.

- [ ] **Step 1: Failing tests** in `test_pult_api.py` (bestehende Fälschung `FalscheDB` weiterverwenden; Vorschau-Tests mit einer Zeile `{"felder": {...}, "format": "bloecke", "bloecke": DOK, "gestalt": GESTALT, "pflichtteil": {...}, "gestalt_fehler": None}` — genau die Spalten, die die Vorschau-Abfrage nach Task 3 liefert):

```python
DOK = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["t"]}},
       "t": {"type": "Text", "data": {"props": {"text": "Hallo Pult"}}}}
IID = "11111111-1111-1111-1111-111111111111"


def test_bloecke_speichern(db, c):
    db.antworten = [[{"fassung": 4}]]
    r = c.post(f"/api/pult/inhalte/{IID}/bloecke", headers=H,
               json={"basis_fassung": 3, "betreff": "B", "vorschautext": "", "bloecke": DOK})
    assert r.status_code == 200 and r.json() == {"fassung": 4}
    sql = db.sql[-1]
    assert "marketing.pult_bloecke_speichern(" in sql and ", 3, " in sql and "'betreiber'" in sql and "false" in sql


def test_bloecke_als_kopie_und_agent(db, c):
    db.antworten = [[{"fassung": 5}]]
    c.post(f"/api/pult/inhalte/{IID}/bloecke", headers=H,
           json={"basis_fassung": 3, "betreff": "B", "vorschautext": "", "bloecke": DOK,
                 "als_kopie": True, "urheber": "agent"})
    assert "true" in db.sql[-1] and "'agent'" in db.sql[-1]


def test_bloecke_ohne_dict_oder_basis_422_ohne_db(db, c):
    for body in ({"basis_fassung": 1, "betreff": "B", "bloecke": "nein"},
                 {"basis_fassung": "x", "betreff": "B", "bloecke": DOK},
                 {"basis_fassung": 1, "betreff": "B", "bloecke": DOK, "urheber": "fremd"}):
        assert c.post(f"/api/pult/inhalte/{IID}/bloecke", headers=H, json=body).status_code == 422
    assert db.sql == []


def test_konflikt_wird_422_mit_text(db, c, monkeypatch):
    def wirft(*a, **k):
        raise RuntimeError("ERROR:  Inzwischen gibt es Fassung 7 - neu laden oder als Kopie behalten")
    monkeypatch.setattr(_db, "query_one", wirft)
    r = c.post(f"/api/pult/inhalte/{IID}/bloecke", headers=H,
               json={"basis_fassung": 3, "betreff": "B", "vorschautext": "", "bloecke": DOK})
    assert r.status_code == 422 and r.json()["detail"].startswith("Inzwischen gibt es Fassung 7")


def test_vorschau_bloecke_nutzt_bild_basis(db, c):
    db.antworten = [[{"felder": {"betreff": "B", "vorschautext": ""}, "format": "bloecke", "bloecke": DOK,
                      "gestalt": GESTALT, "pflichtteil": {"impressum": "I", "abmelde_hinweis": ""}, "gestalt_fehler": None}]]
    r = c.get(f"/api/pult/inhalte/{IID}/vorschau?fassung=1&format=mail&bild_basis=https://h.ts.net/marketing/bild/t/", headers=H)
    assert r.status_code == 200 and "Hallo Pult" in r.text


def test_vorschau_bloecke_pdf_422(db, c):
    db.antworten = [[{"felder": {"betreff": "B"}, "format": "bloecke", "bloecke": DOK, "gestalt": GESTALT,
                      "pflichtteil": {}, "gestalt_fehler": None}]]
    r = c.get(f"/api/pult/inhalte/{IID}/vorschau?fassung=1&format=pdf", headers=H)
    assert r.status_code == 422 and "PDF" in r.json()["detail"]


def test_bild_basis_wird_geprueft(db, c):
    for schlecht in ("http://h/", "https://h/x", 'https://h/"/', "javascript:x/"):
        r = c.get(f"/api/pult/inhalte/{IID}/vorschau?fassung=1&format=mail&bild_basis={schlecht}", headers=H)
        assert r.status_code == 422, schlecht


def test_vorlagen_liste_und_aus_vorlage(db, c):
    db.antworten = [[{"name": "leer", "beschreibung": "L", "status": "freigegeben", "fassung": 1}]]
    r = c.get("/api/pult/vorlagen?mandant=vibemind", headers=H)
    assert r.json()["vorlagen"][0]["name"] == "leer"
    db.antworten = [[{"id": IID}]]
    r = c.post("/api/pult/inhalte/aus_vorlage", headers=H, json={"vorlage": "leer", "titel": "Oktober"})
    assert r.json() == {"id": IID} and "marketing.pult_inhalt_aus_vorlage(" in db.sql[-1]


def test_aus_vorlage_name_geprueft(db, c):
    r = c.post("/api/pult/inhalte/aus_vorlage", headers=H, json={"vorlage": "../x", "titel": "T"})
    assert r.status_code == 422 and db.sql == []
```

- [ ] **Step 2: Rot sehen** — `…pytest spaces\marketing\tests\test_pult_api.py -q` → die neuen Tests FAIL.

- [ ] **Step 3: Implementieren** in `pult.py` (bestehende Hilfen `_schluessel`, `_uuid_oder_404`, `_lesen`, `_lesen_einer`, `_schreiben`, `_rendern`, `lit`, `_NAME`, `_mandant` benutzen — vorher lesen, wie sie heute heißen und was sie zurückgeben):
  - Vorschau-Abfrage um `f.format, f.bloecke` erweitern; bei `format == "bloecke"`: `format=pdf` → 422; sonst `bloecke_mjml.rendern(zeile["bloecke"], felder["betreff"], felder.get("vorschautext",""), pflichtteil, bild_basis=gepruefte_basis, handy=(format=="handy"))` als `HTMLResponse`; `RenderFehler` → 422.
  - `_BILD_BASIS = re.compile(r'^https://[^\s"\'<>]+/$')` für `bild_basis` (leer erlaubt → Platzhalter).
  - `POST /inhalte/{iid}/bloecke`: `basis_fassung` int ≥ 0 (kein bool), `bloecke` dict, `urheber in ("betreiber","agent")`, `als_kopie` bool; SQL `SELECT marketing.pult_bloecke_speichern({lit(i)}::uuid, {int(basis)}, {lit(betreff)}, {lit(vorschautext)}, {lit(json.dumps(bloecke, ensure_ascii=False))}::jsonb, {lit(urheber)}, {'true' if als_kopie else 'false'}) AS fassung` über `_schreiben`.
  - `GET /inhalte/{iid}`: `SELECT fassung, felder, layout, urheber, erstellt_am::text, format, bloecke …`.
  - Vorlagen: `_VORLAGE = re.compile(r'^[a-z][a-z0-9-]{1,40}$')`; Liste per `_lesen`; Vorschau per `_lesen_einer` (`bloecke`, `beschreibung`, `pflichtteil` über Join auf `mandanten`); `aus_vorlage` per `_schreiben`.
  - Die neuen Routen **vor** `/inhalte/{iid}` registrieren, wo Pfade kollidieren (`/inhalte/aus_vorlage` darf nicht als `{iid}` gelesen werden) — Test `test_vorlagen_liste_und_aus_vorlage` deckt das.

- [ ] **Step 4: Grün sehen** — `test_pult_api.py` PASS; `spaces\marketing\tests -q` (bekannt rot nur `test_cockpit_contract`).

- [ ] **Step 5: Commit**

```powershell
git add -- spaces/marketing/api/pult.py spaces/marketing/tests/test_pult_api.py
git commit -m "feat(marketing): Pult-API fuer Bloecke, Vorlagen und Editor-Vorschau"
```

---

### Task 4: Fünf Startvorlagen

Arbeitsort: Worktree, `spaces/marketing/vorlagen/newsletter/`, `spaces/marketing/scripts/`.

**Files:**
- Create: `spaces/marketing/vorlagen/newsletter/{newsletter,ankuendigung,einladung,produkt-neuheit,kurzer-hinweis}.json`
- Create: `spaces/marketing/vorlagen/newsletter/HERKUNFT.md` (Nachweis: nach Mustern aus Email Builder JS, MIT, `ce3e610`, und MJML-Galerie-Aufbau; eigene Texte)
- Create: `spaces/marketing/scripts/vorlagen_einspielen.py`
- Test: `spaces/marketing/claw/tests/test_startvorlagen.py`

**Interfaces:**
- Consumes: Task 1 (`pult_vorlage_speichern`, Blockformat-Regeln), Task 2 (`bloecke_mjml.rendern`).
- Produces: Dateiformat `{"name": "<^[a-z][a-z0-9-]{1,40}$>", "beschreibung": "...", "bloecke": {<Email-Builder-Dokument>}}`; Skript `python -m spaces.marketing.scripts.vorlagen_einspielen [--wirklich]` (ohne `--wirklich` nur Prüfung: ruft `SELECT marketing.pult_bloecke_fehler(...)` je Datei, ändert nichts).

Inhalte (deutsch, VibeMind, Farben aus Layout `dunkel` in der Bedeutung aus Task 0: Inhaltsfläche `canvasColor` = grund `#0f2422`, Außenfläche `backdropColor` = flaeche `#1d3b39`, Fließtext `textColor` = text `#cfe3df`, Überschriften text_hell `#e9fbf6`, Knopf akzent `#5eead4` mit handlung_text `#0f2422`; jede Vorlage mit Logo-Bildblock `medien:vibemind-logo.png`):
1. **newsletter** — Kopf mit Logo, Überschrift, Einleitung, zwei Themenblöcke als Spalten (je Überschrift + Text), Trenner, „Was als Nächstes kommt" (Text), Knopf „Mehr lesen".
2. **ankuendigung** — große Überschrift, kurzer Text, großer Knopf, Abstand, Fußnote.
3. **einladung** — Überschrift „Du bist eingeladen", Container mit Datum/Ort/Uhrzeit (Text mit **fett**), Knopf „Platz sichern", Hinweistext.
4. **produkt-neuheit** — Bild (Produktbild-Platzhalter `medien:produkt.png`), Überschrift, drei Nutzen als 3-Spalten, Knopf.
5. **kurzer-hinweis** — nur Überschrift, zwei Sätze Text, Link im Text (Markdown).

- [ ] **Step 1: Failing test** — `test_startvorlagen.py`:

```python
"""Die fuenf Startvorlagen: vollstaendig, im erlaubten Format, rendern fehlerfrei."""
import json
import pathlib
import re

import pytest

from spaces.marketing.claw import bloecke_mjml

ORDNER = pathlib.Path(__file__).resolve().parents[2] / "vorlagen" / "newsletter"
NAMEN = ["newsletter", "ankuendigung", "einladung", "produkt-neuheit", "kurzer-hinweis"]
ERLAUBT = {"EmailLayout", "Heading", "Text", "Button", "Image", "Divider", "Spacer", "Container", "ColumnsContainer"}


@pytest.mark.parametrize("name", NAMEN)
def test_vorlage_gueltig_und_rendert(name):
    v = json.loads((ORDNER / f"{name}.json").read_text(encoding="utf-8"))
    assert v["name"] == name and v["beschreibung"]
    d = v["bloecke"]
    assert d["root"]["type"] == "EmailLayout"
    for bid, b in d.items():
        assert b["type"] in ERLAUBT, (bid, b["type"])
        props = (b.get("data") or {}).get("props") or {}
        if b["type"] == "Image":
            assert re.match(r"^medien:[A-Za-z0-9._-]+$", props["url"])
        for k in ("url", "linkHref"):
            if b["type"] != "Image" and props.get(k):
                assert props[k].startswith("https://")
    html = bloecke_mjml.rendern(d, v["beschreibung"], "", {"impressum": "I", "abmelde_hinweis": ""},
                                bild_basis="https://h.ts.net/marketing/bild/t/")
    assert html.lower().startswith("<!doctype html")
    (pathlib.Path(__file__).parent / "_ausgabe").mkdir(exist_ok=True)
    (pathlib.Path(__file__).parent / "_ausgabe" / f"{name}.html").write_text(html, encoding="utf-8")


def test_alle_fuenf_da():
    assert sorted(p.stem for p in ORDNER.glob("*.json")) == sorted(NAMEN)
```

`_ausgabe/` in `.gitignore` des Test-Ordners aufnehmen (Datei `spaces/marketing/claw/tests/.gitignore` mit `_ausgabe/`).

- [ ] **Step 2: Rot sehen** — FAIL (Dateien fehlen).
- [ ] **Step 3: Die fünf JSON-Dateien schreiben** (vollständige Dokumente mit festen, sprechenden Block-IDs wie `logo`, `kopf`, `einleitung`, `spalten`, …), `HERKUNFT.md`, und das Skript:

```python
"""Startvorlagen in marketing.newsletter_vorlagen einspielen (sales-claw Spec
2026-09-29-newsletter-editor-design.md §3.5). Ohne --wirklich nur pruefen."""
from __future__ import annotations

import json
import pathlib
import sys

from spaces.marketing.sync import _db

ORDNER = pathlib.Path(__file__).resolve().parents[1] / "vorlagen" / "newsletter"


def main(wirklich: bool) -> int:
    fehler = 0
    for datei in sorted(ORDNER.glob("*.json")):
        v = json.loads(datei.read_text(encoding="utf-8"))
        doc = _db._sql_literal(json.dumps(v["bloecke"], ensure_ascii=False))
        grund = _db.query_one(f"SELECT marketing.pult_bloecke_fehler({doc}::jsonb) AS f", streng=True)["f"]
        if grund:
            print(f"{datei.name}: UNGUELTIG - {grund}")
            fehler += 1
            continue
        if wirklich:
            n = _db.query_one(
                f"SELECT marketing.pult_vorlage_speichern({_db._sql_literal(v['name'])}, "
                f"{_db._sql_literal(v['beschreibung'])}, {doc}::jsonb, 'startvorlagen', 'freigegeben') AS n",
                streng=True)["n"]
            print(f"{datei.name}: eingespielt, Fassung {n}")
        else:
            print(f"{datei.name}: gueltig")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main("--wirklich" in sys.argv))
```

- [ ] **Step 4: Grün sehen** — `test_startvorlagen.py` PASS; dann **nur prüfend** gegen die VM-DB: aus der Worktree-Wurzel mit der Repo-`.env` (Modus A über ssh): `…python.exe -m spaces.marketing.scripts.vorlagen_einspielen` → fünf Zeilen „gueltig". Die erzeugten `_ausgabe/*.html` einmal im Browser öffnen (Playwright-Screenshot je Vorlage in den Report).
- [ ] **Step 5: Commit**

```powershell
git add -- spaces/marketing/vorlagen/newsletter spaces/marketing/scripts/vorlagen_einspielen.py spaces/marketing/claw/tests/test_startvorlagen.py spaces/marketing/claw/tests/.gitignore
git commit -m "feat(marketing): fuenf Startvorlagen fuer den Newsletter-Editor"
```

---

### Task 5: Editor-Paket (Fork der Beispiel-App)

Arbeitsort: sales-claw `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw`.

**Files:**
- Create: `editor/` — Kopie von `examples/vite-emailbuilder-mui` aus dem Klon `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\pruefung\ebj` (Commit `ce3e610`), plus `editor/LICENSE` (MIT-Text des Originals) und `editor/HERKUNFT.md` (Quelle, Commit, Liste der Änderungen)
- Create: `editor/src/pult.ts` (Anbindung ans Pult)
- Modify: `editor/index.html`, `editor/src/main.tsx`, `editor/vite.config.ts`, die Block-Auswahl (Datei im Klon unter `src/documents/editor/` bzw. `src/App/…` — die Stelle, die die Blockliste zum Hinzufügen definiert), die Seitenleiste mit den Beispielvorlagen
- Create: `sales-mcp/static/editor/editor.js`, `sales-mcp/static/editor/editor.css`, `sales-mcp/static/editor/MANIFEST.json` (gebaut)
- Test: `sales-mcp/tests/test_editor_paket.py`

**Interfaces:**
- Consumes (von der Editor-Seite aus Task 6): ein Daten-Element im HTML
  `<script type="application/json" id="editor-start">{"dokument":{…},"betreff":"…","vorschautext":"…","basis_fassung":N,"speichern_url":"/marketing/editor/<id>/speichern","vorschau_url":"/marketing/entwurf/<id>/vorschau","medien_url":"/marketing/editor/medien.json","zurueck_url":"/marketing/entwurf/<id>","csrf":"…"}</script>` (Typ `application/json` wird nicht ausgeführt, verletzt die CSP nicht).
- Produces (Aufrufe an sales-ui):
  - `POST speichern_url`, Header `Content-Type: application/json`, `X-CSRF: <csrf>`, Body `{"basis_fassung": N, "betreff": "…", "vorschautext": "…", "dokument": {…}, "als_kopie": false}` → 200 `{"fassung": M}` | 409 `{"konflikt": true, "grund": "Inzwischen gibt es Fassung …"}` | 422 `{"grund": "…"}` | 503 `{"grund": "…"}`.
  - `GET medien_url` → `{"bilder": ["datei.png", …]}`.
  - Vorschau: öffnet `vorschau_url?fassung=<M>&format=mail|handy` im neuen Tab (erst nach erfolgreichem Speichern; ungespeicherte Änderungen → Hinweis „Erst speichern").

- [ ] **Step 1: Failing test** — `sales-mcp/tests/test_editor_paket.py`:

```python
"""Eingebautes Editor-Paket: Pruefsummen stimmen, keine fremden Quellen."""
import hashlib
import json
import pathlib

ORDNER = pathlib.Path(__file__).resolve().parents[1] / "static" / "editor"
FREMD = ("cdnjs.", "googleapis.", "gstatic.", "unpkg.", "jsdelivr.", "cloudfront.")


def test_manifest_stimmt():
    m = json.loads((ORDNER / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["quelle"] == "usewaypoint/email-builder-js@ce3e610"
    for name in ("editor.js", "editor.css"):
        assert hashlib.sha256((ORDNER / name).read_bytes()).hexdigest() == m["sha256"][name], name


def test_keine_fremden_quellen():
    for name in ("editor.js", "editor.css"):
        text = (ORDNER / name).read_text(encoding="utf-8", errors="replace")
        for f in FREMD:
            assert f not in text, (name, f)


def test_nur_zwei_dateien_ausgeliefert():
    assert sorted(p.name for p in ORDNER.iterdir()) == ["MANIFEST.json", "editor.css", "editor.js"]
```

- [ ] **Step 2: Rot sehen** — Host-Runner `tests/test_editor_paket.py` → FAIL.
- [ ] **Step 3: Fork und Anbindung.**
  1. `editor/` aus dem Klon kopieren (ohne `node_modules`), `package.json` auf `"name": "sales-claw-editor", "private": true` setzen, Abhängigkeiten unverändert lassen.
  2. `index.html`: das `cdnjs`-Stylesheet entfernen; `<div id="root">` behalten.
  3. `vite.config.ts`: `build: { outDir: "../sales-mcp/static/editor", emptyOutDir: true, assetsInlineLimit: 100000000, cssCodeSplit: false, rollupOptions: { output: { entryFileNames: "editor.js", assetFileNames: (a) => a.name?.endsWith(".css") ? "editor.css" : "[name][extname]", inlineDynamicImports: true } } }`, `base: "/static/editor/"`.
  4. Beispielvorlagen und deren Menü entfernen (die Seitenleiste mit `getConfiguration/sample/*`), Blöcke **Html** und **Avatar** aus der Hinzufügen-Liste entfernen; JSON-/HTML-Export- und „Share"-Funktionen entfernen (sie würden den Editor-eigenen Renderer als Ergebnis anbieten).
  5. `editor/src/pult.ts`:

```ts
// Anbindung des Editors an das Marketing-Pult (sales-claw Spec
// 2026-09-29-newsletter-editor-design.md §3.1). Einzige Stelle mit Netzverkehr:
// nur relative Adressen von sales-ui.
export type Start = {
  dokument: Record<string, unknown>; betreff: string; vorschautext: string;
  basis_fassung: number; speichern_url: string; vorschau_url: string;
  medien_url: string; zurueck_url: string; csrf: string;
};

export function startLesen(): Start {
  const el = document.getElementById("editor-start");
  if (!el?.textContent) throw new Error("Startdaten fehlen");
  return JSON.parse(el.textContent) as Start;
}

// Im Dokument stehen Bilder als "medien:<name>"; im Editor-Bild zeigen wir
// die angemeldete Medien-Adresse. Beim Speichern zurueck.
const ANZEIGE = "/medien/datei/";
export function zurAnzeige(doc: any): any {
  return umschreiben(doc, (u) => (u.startsWith("medien:") ? ANZEIGE + encodeURIComponent(u.slice(7)) : u));
}
export function zurSpeicherung(doc: any): any {
  return umschreiben(doc, (u) => (u.startsWith(ANZEIGE) ? "medien:" + decodeURIComponent(u.slice(ANZEIGE.length)) : u));
}
function umschreiben(doc: any, f: (u: string) => string): any {
  const neu = JSON.parse(JSON.stringify(doc));
  for (const b of Object.values<any>(neu)) {
    if (b?.type === "Image" && typeof b?.data?.props?.url === "string") b.data.props.url = f(b.data.props.url);
  }
  return neu;
}

export type Ergebnis = { ok: true; fassung: number } | { ok: false; konflikt: boolean; grund: string };

export async function speichern(s: Start, doc: any, betreff: string, vorschautext: string,
                                basis: number, alsKopie: boolean): Promise<Ergebnis> {
  const r = await fetch(s.speichern_url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF": s.csrf },
    body: JSON.stringify({ basis_fassung: basis, betreff, vorschautext, dokument: zurSpeicherung(doc), als_kopie: alsKopie }),
  });
  const j = await r.json().catch(() => ({}));
  if (r.ok) return { ok: true, fassung: j.fassung };
  return { ok: false, konflikt: r.status === 409, grund: j.grund || "Speichern gerade nicht möglich" };
}

export async function medienListe(s: Start): Promise<string[]> {
  const r = await fetch(s.medien_url, { credentials: "same-origin" });
  if (!r.ok) return [];
  return ((await r.json()).bilder || []) as string[];
}
```

  6. `main.tsx`: statt des Beispiel-Dokuments `zurAnzeige(startLesen().dokument)` in den Editor-Store laden (die Funktion, mit der die App ein Dokument setzt — im Klon `resetDocument`/`setDocument` in `documents/editor/EditorContext.tsx` — benutzen). Oben eine Leiste (MUI) mit Feldern **Betreff**, **Vorschautext**, Knöpfen **Speichern**, **Vorschau Mail**, **Vorschau Handy**, **Zurück zum Entwurf**; Speichern ruft `speichern(...)` mit der gemerkten `basis`; bei Erfolg `basis = fassung` und Meldung „Gespeichert als Fassung N"; bei Konflikt ein Dialog mit dem `grund` und den Knöpfen **Neu laden** (`location.reload()`) und **Als Kopie behalten** (erneut `speichern(..., alsKopie=true)`); bei anderem Fehler Meldung mit `grund`, Änderungen bleiben. Vorschau-Knöpfe nur aktiv, wenn nichts ungespeichert ist; sie öffnen `vorschau_url + "?fassung=" + basis + "&format=mail|handy"` mit `window.open`.
  7. Im Einstellungsfeld des Bild-Blocks eine Auswahl **„Aus den Medien"** (Liste aus `medienListe`), die `url` auf `/medien/datei/<name>` setzt; das freie URL-Feld für Bilder entfernen.
  8. Bauen: `cd editor && npm ci && npx vite build` (Node v24 vorhanden). Danach `MANIFEST.json` schreiben: `{"quelle": "usewaypoint/email-builder-js@ce3e610", "gebaut": "<ISO-Datum>", "sha256": {"editor.js": "…", "editor.css": "…"}}` (Python-Einzeiler mit `hashlib`). `editor/node_modules` nicht committen (`editor/.gitignore`).
- [ ] **Step 4: Grün sehen** — `tests/test_editor_paket.py` PASS. Paketgröße in den Report.
- [ ] **Step 5: Commit**

```powershell
git add -- editor sales-mcp/static/editor sales-mcp/tests/test_editor_paket.py
git commit -m "feat(ui): eingebautes Editor-Paket (Fork Email Builder JS) mit Pult-Anbindung"
```

---

### Task 6: Editor-Seite, signierte Bilder, „Neu aus Vorlage" in sales-ui

Arbeitsort: sales-claw.

**Files:**
- Create: `sales-mcp/ui_editor.py` (Seiten und Endpunkte des Editors; `routen(ui) -> list[Route]` wie `ui_marketing.routen`)
- Modify: `sales-mcp/ui.py` — Routen aus `ui_editor.routen(...)` einhängen; `/marketing/bild/` in der Anmeldewache als offene Präfix-Ausnahme (nur dieser Präfix, Begründung im Kommentar); Route `/static/editor/{datei}`
- Modify: `sales-mcp/ui_marketing.py` — Entwurfsseite: bei `format == "bloecke"` Feldformular ausblenden, Knopf **„Im Editor öffnen"**; Vorschau-Proxy reicht `bild_basis` durch und erlaubt `img-src 'self' data:`; Übersicht: Link **„Neuer Newsletter aus Vorlage"**
- Test: `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Consumes: Task 3 (API-Pfade), Task 5 (Paket-Dateien, Start-Daten, Aufruf-Verträge), `marketing_pult.anfrage`/`PultFehler`, `ui._csrf_ok`-Muster, `ui.UI_SESSION_SECRET`, `ui.UI_BASIS_URL`, `server.medien.pruefe(name)`, `server.medien.liste()`.
- Produces:
  - `ui_editor.bild_token(jetzt: int | None = None) -> str` → `"<ablauf>.<hex-hmac>"` (HMAC-SHA256 über `str(ablauf)` mit `UI_SESSION_SECRET`, Ablauf = jetzt + 900 s).
  - `ui_editor.bild_token_ok(token: str, jetzt: int | None = None) -> bool`.
  - `ui_editor.bild_basis() -> str` → `f"{UI_BASIS_URL}/marketing/bild/{bild_token()}/"` (leer, wenn `UI_SESSION_SECRET` fehlt).
  - Routen: `GET /marketing/editor/{iid}`, `POST /marketing/editor/{iid}/speichern` (JSON, CSRF-Header `X-CSRF`), `GET /marketing/editor/medien.json`, `GET /marketing/bild/{token}/{name}`, `GET /marketing/vorlagen`, `POST /marketing/aus-vorlage`, `GET /static/editor/{datei}`.

- [ ] **Step 1: Failing tests** — `sales-mcp/tests/test_editor_seite.py` (Muster und Fixtures `Falsch`/`angemeldet` aus `tests/test_marketing_pult.py` übernehmen; `Falsch.anfrage` um die neuen Pfade erweitern):

```python
import json
import re
import time

import pytest

import marketing_pult
import ui
import ui_editor

HOST = {"host": "127.0.0.1:8791"}
IID = "11111111-1111-1111-1111-111111111111"
DOK = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["i"]}},
       "i": {"type": "Image", "data": {"props": {"url": "medien:logo.png"}}}}


def test_editor_seite_einzige_mit_skript(angemeldet):
    r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert '<script src="/static/editor/editor.js"' in r.text
    start = json.loads(re.search(r'<script type="application/json" id="editor-start">(.*?)</script>', r.text, re.S).group(1))
    assert start["basis_fassung"] == 2 and start["csrf"] == ui.CSRF_TOKEN
    assert start["dokument"]["i"]["data"]["props"]["url"] == "medien:logo.png"
    assert "Der Editor braucht einen größeren Bildschirm" in r.text


def test_andere_pult_seiten_bleiben_skriptfrei(angemeldet):
    for pfad in ("/marketing", "/marketing/entwuerfe", f"/marketing/entwurf/{IID}", "/marketing/vorlagen"):
        r = angemeldet.get(pfad, headers=HOST)
        assert "script-src" not in r.headers.get("content-security-policy", ""), pfad
        assert "<script" not in r.text.replace('type="application/json"', ""), pfad


def test_startdaten_escapen_schliessendes_tag(angemeldet, pult):
    pult.betreff = "</script><script>alert(1)</script>"
    r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    assert "</script><script>alert(1)" not in r.text


def test_speichern_braucht_csrf_header(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers=HOST,
                        json={"basis_fassung": 2, "betreff": "B", "vorschautext": "", "dokument": DOK})
    assert r.status_code == 403 and not any(a[1].endswith("/bloecke") for a in pult.aufrufe)


def test_speichern_reicht_durch(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"basis_fassung": 2, "betreff": "B", "vorschautext": "", "dokument": DOK})
    assert r.status_code == 200 and r.json() == {"fassung": 3}
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", f"/inhalte/{IID}/bloecke")
    assert d == {"basis_fassung": 2, "betreff": "B", "vorschautext": "", "bloecke": DOK,
                 "als_kopie": False, "urheber": "betreiber"}


def test_konflikt_wird_409(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Inzwischen gibt es Fassung 5 - neu laden oder als Kopie behalten")
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"basis_fassung": 2, "betreff": "B", "vorschautext": "", "dokument": DOK})
    assert r.status_code == 409 and r.json() == {"konflikt": True, "grund": "Inzwischen gibt es Fassung 5 - neu laden oder als Kopie behalten"}


def test_andere_ablehnung_422(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Blocktyp Html ist nicht erlaubt")
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"basis_fassung": 2, "betreff": "B", "vorschautext": "", "dokument": DOK})
    assert r.status_code == 422 and "Html" in r.json()["grund"]


def test_bild_token(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    t = ui_editor.bild_token(jetzt=1000)
    assert ui_editor.bild_token_ok(t, jetzt=1500)
    assert not ui_editor.bild_token_ok(t, jetzt=1000 + 901)
    ablauf, sig = t.split(".")
    assert not ui_editor.bild_token_ok(f"{int(ablauf) + 60}.{sig}", jetzt=1500)
    assert not ui_editor.bild_token_ok("kaputt", jetzt=1500)


def test_bild_route_ohne_anmeldung_nur_mit_token(monkeypatch, tmp_path):
    from starlette.testclient import TestClient
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    gut = ui_editor.bild_token()
    # Die Medien-Pruefung von server wird so gefaelscht, dass logo.png eine echte Datei ist
    datei = tmp_path / "logo.png"
    datei.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 10)
    import server
    monkeypatch.setattr(server.medien, "pruefe", lambda n: (str(datei), None) if n == "logo.png" else (None, "unbekannt"))
    assert c.get(f"/marketing/bild/{gut}/logo.png", headers=HOST).status_code == 200
    assert c.get("/marketing/bild/0.abc/logo.png", headers=HOST).status_code == 404
    assert c.get(f"/marketing/bild/{gut}/..%2Fsecret.png", headers=HOST).status_code == 404
    assert c.get(f"/marketing/bild/{gut}/text.txt", headers=HOST).status_code == 404


def test_vorschau_proxy_gibt_bild_basis_mit(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    r = angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    assert "img-src 'self' data:" in r.headers["content-security-policy"]
    pfad = [a[1] for a in pult.aufrufe if "/vorschau" in a[1]][-1]
    assert "bild_basis=" in pfad and "%2Fmarketing%2Fbild%2F" in pfad


def test_entwurf_mit_bloecken_zeigt_editor_knopf(angemeldet):
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert f'href="/marketing/editor/{IID}"' in s and 'name="abschnitt_text"' not in s


def test_aus_vorlage(angemeldet, pult):
    r = angemeldet.post("/marketing/aus-vorlage", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorlage": "leer", "titel": "Oktober"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/editor/{IID}"


def test_statische_dateien_nur_zwei(angemeldet):
    assert angemeldet.get("/static/editor/editor.js", headers=HOST).status_code == 200
    assert angemeldet.get("/static/editor/MANIFEST.json", headers=HOST).status_code == 404
    assert angemeldet.get("/static/editor/../ui.py", headers=HOST).status_code == 404
```

(Die Fälschung liefert für `/inhalte/{IID}` eine neueste Fassung 2 mit `format: "bloecke"`, `bloecke: DOK`, `felder: {"betreff": pult.betreff}`; für `/inhalte/{IID}/bloecke` → `{"fassung": 3}`; für `/inhalte/aus_vorlage` → `{"id": IID}`; für `/vorlagen?…` eine Vorlage `leer`.)

- [ ] **Step 2: Rot sehen** — Host-Runner `tests/test_editor_seite.py` → FAIL.
- [ ] **Step 3: Implementieren** — `sales-mcp/ui_editor.py`:

```python
"""Editor-Seite des Newsletter-Editors (Spec 2026-09-29-newsletter-editor-
design.md §3.1/§3.2). Die EINZIGE Route von sales-ui mit Skript: nur das
eingebaute Paket /static/editor/editor.js. Dazu signierte Bild-Adressen fuer
die abgeschottete Vorschau (ohne Anmeldung, 15 Minuten gueltig)."""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import time
import urllib.parse
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import marketing_pult

GUELTIG_S = 900
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp")
STATIK = Path(__file__).resolve().parent / "static" / "editor"
STATIK_DATEIEN = {"editor.js": "text/javascript", "editor.css": "text/css"}
CSP_EDITOR = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
              "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _ui():
    import ui
    return ui


def bild_token(jetzt: int | None = None) -> str:
    geheim = _ui().UI_SESSION_SECRET
    ablauf = int(jetzt if jetzt is not None else time.time()) + GUELTIG_S
    sig = hmac.new(geheim.encode(), str(ablauf).encode(), hashlib.sha256).hexdigest()
    return f"{ablauf}.{sig}"


def bild_token_ok(token: str, jetzt: int | None = None) -> bool:
    geheim = _ui().UI_SESSION_SECRET
    if not geheim or "." not in token:
        return False
    ablauf, sig = token.split(".", 1)
    if not ablauf.isdigit():
        return False
    erwartet = hmac.new(geheim.encode(), ablauf.encode(), hashlib.sha256).hexdigest()
    jetzt = int(jetzt if jetzt is not None else time.time())
    return hmac.compare_digest(sig, erwartet) and jetzt <= int(ablauf) <= jetzt + GUELTIG_S


def bild_basis() -> str:
    ui = _ui()
    if not ui.UI_SESSION_SECRET:
        return ""
    return f"{ui.UI_BASIS_URL.rstrip('/')}/marketing/bild/{bild_token()}/"


def _json_im_html(daten: dict) -> str:
    # "</" darf im Daten-Element nie vorkommen, sonst schliesst es das Tag
    return json.dumps(daten, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def routen(ui) -> list:
    e = ui._e
    ...  # Handler siehe unten
```

Die Handler (in `routen`, alle mit `@ui._gesichert_seite` außer `bild` und `statik`; API-Aufrufe über `await run_in_threadpool(marketing_pult.anfrage, …)`; `fehler()` wie in `ui_marketing`):
- `editor_seite`: `GET /inhalte/{iid}` → neueste Fassung; ist sie nicht `format == "bloecke"` oder das Inhalt kein Newsletter-Entwurf → Fehlerseite „Dieser Entwurf lässt sich nicht im Editor öffnen". Sonst Antwort-HTML (eigenständig, **nicht** über `ui._seite`, damit die Seite die ganze Fläche hat): `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Editor – …</title><link rel="stylesheet" href="/static/editor/editor.css"><style>@media (max-width:767px){#root{display:none}.schmal{display:block}} .schmal{display:none;padding:2rem;font-family:system-ui}</style></head><body><p class="schmal">Der Editor braucht einen größeren Bildschirm. <a href="/marketing/entwurf/{iid}">Zurück zum Entwurf</a></p><div id="root"></div><script type="application/json" id="editor-start">{_json_im_html(start)}</script><script src="/static/editor/editor.js" defer></script></body></html>` mit Header `Content-Security-Policy: CSP_EDITOR` (Hinweis: `ui._mit_koepfen` setzt die Standard-CSP — prüfen, ob eine Antwort ihre eigene CSP behält, wie es Task 4 der Pult-Stufe 1 für `X-Frame-Options` eingeführt hat; falls nicht, dieselbe Ausnahme für `Content-Security-Policy` nur für diese Route einbauen und im Report belegen). Das `<style>`-Element ist durch `style-src 'unsafe-inline'` gedeckt.
- `editor_speichern`: CSRF aus Header `X-CSRF` (`hmac.compare_digest` gegen `ui.CSRF_TOKEN`, sonst 403 JSON `{"grund": "Fehlende oder falsche CSRF-Marke"}`); Body-Prüfung (`basis_fassung` int ≥ 0 kein bool, `dokument` dict, `betreff` str, `vorschautext` str, `als_kopie` bool; sonst 422); `POST /inhalte/{iid}/bloecke` mit `{"basis_fassung", "betreff", "vorschautext", "bloecke": dokument, "als_kopie", "urheber": "betreiber"}`; `PultFehler("abgelehnt")` mit Grund, der mit „Inzwischen gibt es Fassung" beginnt → 409 `{"konflikt": true, "grund": …}`; anderes `abgelehnt` → 422 `{"grund": …}`; `nicht_erreichbar`/`nicht_verbunden`/`unbekannt` → 503 `{"grund": "Speichern gerade nicht möglich"}`.
- `medien_json`: `server.medien.liste()` gefiltert auf `BILD_ENDUNGEN` → `{"bilder": [...]}` (Form von `liste()` vorher lesen).
- `bild` (offen, ohne `_gesichert_seite`): `bild_token_ok(token)` sonst 404; Name `urllib.parse.unquote(name)`, muss Endung aus `BILD_ENDUNGEN` haben und `server.medien.pruefe(name)` bestehen (keine Pfadteile), sonst 404; Antwort `FileResponse` mit `media_type` aus `mimetypes`, `Cache-Control: private, max-age=300`, `X-Content-Type-Options: nosniff`, CSP `default-src 'none'; sandbox`.
- `vorlagen_seite`: Liste aus `GET /vorlagen?mandant=vibemind&status=freigegeben`, je Vorlage ein sandboxed iframe mit `/marketing/vorlage-bild/{name}` (Proxy auf `/vorlagen/{name}/vorschau?format=mail&bild_basis=…`, gleiche Vorschau-Köpfe wie der Entwurfs-Proxy) und ein Formular `POST /marketing/aus-vorlage` (`csrf`, `vorlage`, `titel`).
- `aus_vorlage`: CSRF, `POST /inhalte/aus_vorlage` → 303 auf `/marketing/editor/{id}`.
- `statik`: nur Namen in `STATIK_DATEIEN`, `FileResponse` mit Typ, `Cache-Control: no-cache` (das Paket ändert sich nur mit einem Commit), sonst 404.

In `ui_marketing.py`: der bestehende Vorschau-Proxy hängt bei jedem Aufruf `bild_basis=ui_editor.bild_basis()` an die API-Anfrage (leer lassen, wenn leer) und setzt in seiner CSP `img-src 'self' data:` statt `img-src data:`; Entwurfsseite: `format == "bloecke"` → statt Feldformular ein Absatz „Dieser Newsletter wird im Editor bearbeitet." und `<a class="knopf" href="/marketing/editor/{iid}">Im Editor öffnen</a>`; Freigeben/Ablehnen bleiben. Übersicht: Link „Neuer Newsletter aus Vorlage" → `/marketing/vorlagen`.

In `ui.py`: `import ui_editor`; `*ui_editor.routen(sys.modules[__name__])` in die Routenliste **vor** den Marketing-Routen; Anmeldewache: Pfade mit Präfix `/marketing/bild/` durchlassen (Kommentar: signiert, 15 Minuten, nur Bilddateien aus den Medien — Grund: die abgeschottete Vorschau schickt keine Anmelde-Cookies); `_pfad_erlaubt` lässt `/marketing/bild/` für jede Rolle zu (die Signatur ist die Berechtigung). Prüfen und im Report belegen, dass sonst **kein** `/marketing/…`-Pfad ohne Anmeldung erreichbar ist (Test über alle registrierten Routen mit Präfix `/marketing`, ohne Session → 303 auf `/login` außer `/marketing/bild/`).

- [ ] **Step 4: Grün sehen** — Host-Runner `tests/test_editor_seite.py`, `tests/test_marketing_pult.py`, `tests/test_ui.py`, `tests/test_seitenleiste.py` (2 bekannte Rote).
- [ ] **Step 5: Commit**

```powershell
git add -- sales-mcp/ui_editor.py sales-mcp/ui.py sales-mcp/ui_marketing.py sales-mcp/tests/test_editor_seite.py
git commit -m "feat(ui): Newsletter-Editor im Pult - Editor-Seite, signierte Bilder, Neu aus Vorlage"
```

---

### Task 7: Ausliefern (NUR nach ausdrücklichem Go des Betreibers)

WORKBOARD-Claim `cc-newsletter-editor-e1` eintragen und committen.

- [ ] **Step 1: Push** — vibemind-os `master` (Worktree) und sales-claw `feat/stufe-1-fundament`; vorher `git log origin/<zweig>..HEAD`: fremde Commits benennen.
- [ ] **Step 2: VM-venv:** `ssh offload-vm '~/marketing-os/.venv/bin/pip install -q mjml-python==1.4.2 && ~/marketing-os/.venv/bin/python -c "import mjml; print(mjml.mjml2html(\"<mjml><mj-body><mj-section><mj-column><mj-text>ok</mj-text></mj-column></mj-section></mj-body></mjml>\")[:15])"'` → `<!doctype html>`; Runbook (`docs/04_BETRIEB_MINIPC.md`, venv-Zeile) um `mjml-python==1.4.2` ergänzen.
- [ ] **Step 3: VM:** `bash ~/sales-claw/deploy/update.sh` (baut sales-ui mit `static/editor`, zieht den Marketing-Checkout nach und startet `marketing-api` neu). Prüfen: `docker exec sales-ui ls /app/static/editor` bzw. den tatsächlichen Pfad im Image (Dockerfile lesen — wird `static/` mitkopiert? falls nicht: im Plan-Report als Abweichung beheben, bevor ausgeliefert wird); `systemctl is-active marketing-api`; `/api/health` 200.
- [ ] **Step 4: Startvorlagen einspielen:** vom PC aus der Worktree-Wurzel `…python.exe -m spaces.marketing.scripts.vorlagen_einspielen --wirklich` (Modus A, ssh) → fünf Zeilen „eingespielt". Ein Logo `vibemind-logo.png` in die Medien des Basis-Ladens legen (vom Betreiber oder aus dem Repo, falls vorhanden; im Report sagen). Fehlt es, zeigt die Vorschau mit https-`bild_basis` (UI_BASIS_URL = https) ein **kaputtes Bild** (die signierte Adresse antwortet 404) — den Platzhalter „[Bild: vibemind-logo.png]" gibt es nur ohne `bild_basis`. Ein kaputtes Logo in der Vorschau heißt also: Datei fehlt in den Medien.
- [ ] **Step 5: Durchlauf (Betreiber angemeldet, Playwright im geöffneten Fenster):** Pult → „Neuer Newsletter aus Vorlage" → „newsletter" → Editor öffnet sich → Block ziehen, Text ändern → Speichern (Fassung 2) → Vorschau Mail zeigt die Änderung und das Logo → zurück zum Entwurf. Einen der übernommenen alten Newsletter im Editor öffnen. Handy-Breite: Hinweis statt Editor. Screenshots in den Report.
- [ ] **Step 6:** WORKBOARD-Eintrag, Claim schließen.

---

## Self-Review (erledigt)

- Spec-Abdeckung E1: §3.1 Editor-Seite → Task 5+6; §3.2 Skript-Ausnahme → Task 6 (CSP, Test „einzige mit Skript"), Paket mit Prüfsumme → Task 5; §3.3 Format + DB-Prüfung + Übernahme → Task 1; §3.4 Rendern + Pflichtteil + Layout-Voreinstellungen → Task 2 (Farben aus `dunkel` in Übernahme und Vorlagen; Layout-Auswahl beim Anlegen aus Vorlage ist nicht Teil von E1 — Vorlagen tragen die `dunkel`-Farben; die Layout-Galerie bleibt unverändert); §3.5 Vorlagen (Start) → Task 1 (Tabelle, `leer`) + Task 4 (fünf) + Task 6 (Galerie „Neu aus Vorlage"); „aus Vorbildern" ist E2; §3.7 Gleichzeitig → Task 1 (DB) + Task 5 (Dialog) + Task 6 (409); §4 Fehlerfälle → Task 3/6; §5 Tests → je Task; Bilder aus den Medien + signierte Adressen → Task 6 (aus Spec §7 „Folge für die Vorschau").
- Abweichung/Präzisierung gegenüber der Spec: Bilder im Dokument ausschließlich `medien:<name>` (Spec: „erlaubte Adressen (Medien des Ladens)"); die Vorschau lädt sie über signierte, 15 Minuten gültige Adressen, weil die abgeschottete Vorschau keine Anmelde-Cookies mitschickt. „Layouts werden Voreinstellungen" ist in E1 auf die `dunkel`-Farben der Vorlagen und der Übernahme beschränkt; eine Layout-Auswahl beim Anlegen kommt mit E2.
- Namen durchgehend: `pult_bloecke_fehler`, `pult_bloecke_speichern`, `pult_vorlage_speichern`, `pult_inhalt_aus_vorlage`, `bloecke_mjml.nach_mjml/rendern/bild_adresse/RenderFehler`, `ui_editor.bild_token/bild_token_ok/bild_basis/routen`, `pult.ts: startLesen/zurAnzeige/zurSpeicherung/speichern/medienListe`, Header `X-CSRF`, Daten-Element `editor-start`.
