# Marketing-Pult Stufe 1 (Grundgerüst) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In der Sales-Oberfläche gibt es den Bereich „Marketing" mit Übersicht, Entwürfen (Vorschau, Bearbeiten als neue Fassung, Freigeben „nur ablegen", Ablehnen) und einer Layout-Galerie mit Reglern und Live-Vorschau — gerendert von der Marketing-API.

**Architecture:** Neue Tabellen im Schema `marketing` (Mandanten, Inhalte, unveränderliche Fassungen, Layout-Fassungen). Ein Render-Modul in `spaces/marketing/claw/` baut Mail-HTML, Handy-HTML und PDF aus einer Fassung plus Layout-Gestalt. Die Marketing-API bekommt einen Router `/api/pult/*`, geschützt durch `X-Pult-Key`. sales-ui spricht nur mit diesem Router (Client-Modul) und zeigt die Seiten aus einem eigenen Modul `ui_marketing.py`.

**Tech Stack:** PostgreSQL (plpgsql), Python 3.11/3.12, FastAPI (Marketing-API), Starlette (sales-ui), reportlab (bestehendes `claw/pdf.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-marketing-pult-design.md` (sales-claw) — Stufe 1 aus §6.

## Global Constraints

- Nur Ergänzungen im Schema `marketing`; `broadcast_proposals` und die Formular-Vorlagen (Art `formular`) bleiben unverändert.
- Mandanten: `vibemind` (aktiv), `fin2gether` (angelegt, `aktiv = false`). Erlaubte Verteiler VibeMind: nur Laden `sales`.
- Fassungen sind unveränderlich: jede Speicherung ist eine neue Zeile; UPDATE/DELETE auf Fassungen lehnt die Datenbank ab.
- Menüpunkt „Marketing" nur für Rolle `freigeben` und `server.SCHEMA in ("sales", "sales_test")` (Sperre wie `_ADMIN_BASIS_PFADE`).
- sales-ui greift nie direkt auf `marketing.*` zu, nur über `MARKETING_PULT_URL` + Header `X-Pult-Key`.
- Gemessen 29.09.2026: aus dem Container `sales-ui` ist die Marketing-API NUR über `https://vibemind-offload-1.tail6c7d61.ts.net:8446` erreichbar (127.0.0.1 und 172.17.0.1 → Connection refused). `MARKETING_PULT_URL` ist diese Adresse.
- Schlüssel `MARKETING_PULT_KEY`: nur in `/home/debian/marketing-api.env` (VM-Instanz, Rechte 600), in der PC-`.env` und in der Haupt-`.env` des Basis-Ladens; nie in argv, nie im Repo, nie in Logs.
- Fehlt `MARKETING_PULT_KEY` in der API: jeder `/api/pult/*`-Aufruf → 503 „misconfigured" (nie offen). Falscher/fehlender Header → 401.
- Die bestehenden offenen Routen der API bleiben in Stufe 1 unverändert (Schließen = Stufe 5).
- Der Schalter Sales ↔ Marketing vom 25.09. (`MARKETING_URL`, `_marketing_link`, `.schalter`) wird durch den Menüpunkt ersetzt und entfernt.
- Deutsche Texte in der Oberfläche; keine englischen Reste.
- Commits: nur eigene Pfade, explizit, per PowerShell. sales-claw auf `feat/stufe-1-fundament`; vibemind-os nur im Worktree `vibemind-os/.worktrees/setup-agent` (`master`). Kein Push vor Task 6.
- Tests Marketing (Worktree-Wurzel): `C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest <datei> -q`, Umgebung `SALES_CLAW_DIR=C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw`.
- Tests Sales (Host): `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\venv-sales\Scripts\python.exe E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\test_host.py C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw tests/<datei>` (Pfade relativ zu `sales-mcp`). Ist die Test-DB (`127.0.0.1:55432`) aus, laufen Seiten trotzdem (Menü-Zähler fallen leise aus), aber langsam — Tests der neuen Seiten dürfen die DB nicht brauchen (Client wird ersetzt).

## Review Focus

1. **Mandant ohne Impressum** (VibeMind hat heute keins hinterlegt): Vorschau zeigt einen deutlichen Hinweis „Impressum fehlt" im Pflichtteil statt einer leeren Fußzeile. Test in Task 2.
2. **Bearbeiten einer älteren Fassung**: Speichern aus Fassung 2, während Fassung 4 die neueste ist, erzeugt Fassung 5 — nie eine Überschreibung, nie eine Lücke. Test in Task 1 (DB) und Task 3 (API).
3. **HTML/Skript im Entwurfstext** (`<script>`, `onerror=`): wird in der Vorschau als Text gezeigt, nie ausgeführt. Test in Task 2.
4. **Marketing-API nicht erreichbar oder Schlüssel falsch**: Pult-Seiten zeigen „Marketing gerade nicht erreichbar" bzw. „Marketing nicht verbunden", der Rest von Sales bleibt bedienbar. Test in Task 4.
5. **Ungültige Reglerwerte** (Farbe `rot`, Rundung 999, Schrift nicht in der Liste, Logo > 150 KB): Speichern wird mit deutschem Grund abgewiesen, die gespeicherte Fassung bleibt unverändert. Test in Task 1 (DB-Prüffunktion) und Task 5.

---

### Task 1: Datenmodell (Migration 050)

Arbeitsort: Worktree `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent`, Pfade `spaces/marketing/db/`.

**Files:**
- Create: `spaces/marketing/db/050_marketing_pult.sql`
- Create: `spaces/marketing/db/verify_050.sql`

**Interfaces:**
- Produces (Tabellen): `marketing.mandanten(id text pk, name text, aktiv bool, verteiler text[], pflichtteil jsonb)`; `marketing.inhalte(id uuid pk, mandant text fk, art text in ('newsletter','post','material'), titel text, status text in ('entwurf','freigegeben','abgelehnt'), freigegebene_fassung int, entschieden_von text, entschieden_am timestamptz, grund text, herkunft_proposal uuid unique, erstellt_am timestamptz)`; `marketing.inhalt_fassungen(inhalt uuid fk, fassung int, felder jsonb, layout text, layout_fassung int, urheber text in ('agent','betreiber'), erstellt_am timestamptz, pk(inhalt,fassung))`; `marketing.layout_fassungen(layout text fk, fassung int, gestalt jsonb, erstellt_von text, erstellt_am, pk(layout,fassung))`; Spalten `marketing.layout_vorlagen.mandant text`, `.inhaltsart text`, `.fassung int`, `.standard bool`.
- Produces (Funktionen): `marketing.pult_gestalt_fehler(jsonb) → text|null`; `marketing.pult_fassung_speichern(p_inhalt uuid, p_felder jsonb, p_layout text, p_urheber text) → int` (neue Fassungsnummer); `marketing.pult_entscheiden(p_inhalt uuid, p_urteil text, p_von text, p_grund text) → text` (neuer Status); `marketing.pult_layout_speichern(p_name text, p_gestalt jsonb, p_von text) → int`; `marketing.pult_layout_als_standard(p_name text) → void`.

- [ ] **Step 1: verify_050.sql schreiben (rot)** — `BEGIN … ROLLBACK`, jede Probe als `DO`-Block mit `PROBE:`-Satz, Muster `verify_046.sql`:

```sql
-- verify_050.sql — Proben fuer 050_marketing_pult.sql. Aendert nichts (ROLLBACK).
BEGIN;
DO $$ BEGIN
  IF (SELECT count(*) FROM marketing.mandanten WHERE id IN ('vibemind','fin2gether')) <> 2 THEN
    RAISE EXCEPTION 'PROBE: Mandanten fehlen'; END IF;
  IF (SELECT verteiler FROM marketing.mandanten WHERE id='vibemind') <> ARRAY['sales'] THEN
    RAISE EXCEPTION 'PROBE: VibeMind-Verteiler ist nicht genau {sales}'; END IF;
  IF (SELECT count(*) FROM marketing.inhalte WHERE herkunft_proposal IS NOT NULL)
     <> (SELECT count(*) FROM marketing.broadcast_proposals) THEN
    RAISE EXCEPTION 'PROBE: nicht jeder broadcast_proposal wurde uebernommen'; END IF;
  IF EXISTS (SELECT 1 FROM marketing.inhalte i
             WHERE NOT EXISTS (SELECT 1 FROM marketing.inhalt_fassungen f
                               WHERE f.inhalt=i.id AND f.fassung=1)) THEN
    RAISE EXCEPTION 'PROBE: Inhalt ohne Fassung 1'; END IF;
  IF (SELECT count(*) FROM marketing.layout_vorlagen
      WHERE art='layout' AND mandant='vibemind' AND inhaltsart IS NOT NULL) < 3 THEN
    RAISE EXCEPTION 'PROBE: Layouts nicht VibeMind zugeordnet'; END IF;
END $$;
-- Fassungen: aus Fassung 1 speichern ergibt die naechste freie Nummer
DO $$ DECLARE v_i uuid; v_n int; BEGIN
  SELECT id INTO v_i FROM marketing.inhalte ORDER BY erstellt_am LIMIT 1;
  v_n := marketing.pult_fassung_speichern(v_i, '{"betreff":"x","abschnitte":[{"titel":"","text":"y"}]}', 'dunkel', 'betreiber');
  IF v_n <> (SELECT max(fassung) FROM marketing.inhalt_fassungen WHERE inhalt=v_i) THEN
    RAISE EXCEPTION 'PROBE: neue Fassung ist nicht die hoechste'; END IF;
  v_n := marketing.pult_fassung_speichern(v_i, '{"betreff":"z","abschnitte":[{"titel":"","text":"w"}]}', 'dunkel', 'betreiber');
  IF v_n <> (SELECT max(fassung) FROM marketing.inhalt_fassungen WHERE inhalt=v_i) THEN
    RAISE EXCEPTION 'PROBE: zweite Speicherung nicht lueckenlos'; END IF;
END $$;
-- Fassungen sind unveraenderlich
DO $$ BEGIN
  UPDATE marketing.inhalt_fassungen SET felder='{}' WHERE fassung=1;
  RAISE EXCEPTION 'PROBE: UPDATE auf Fassung ging durch';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
  IF SQLERRM NOT LIKE '%unveraenderlich%' THEN RAISE EXCEPTION 'PROBE: falscher Grund: %', SQLERRM; END IF;
END $$;
DO $$ BEGIN
  DELETE FROM marketing.inhalt_fassungen WHERE fassung=1;
  RAISE EXCEPTION 'PROBE: DELETE auf Fassung ging durch';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
END $$;
-- Felder ohne Betreff oder ohne Abschnitte werden abgewiesen
DO $$ DECLARE v_i uuid; BEGIN
  SELECT id INTO v_i FROM marketing.inhalte LIMIT 1;
  PERFORM marketing.pult_fassung_speichern(v_i, '{"abschnitte":[]}', 'dunkel', 'betreiber');
  RAISE EXCEPTION 'PROBE: Fassung ohne Betreff ging durch';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
END $$;
-- Entscheiden: freigeben setzt die neueste Fassung, zweimal entscheiden geht nicht
DO $$ DECLARE v_i uuid; v_s text; BEGIN
  SELECT id INTO v_i FROM marketing.inhalte WHERE status='entwurf' LIMIT 1;
  v_s := marketing.pult_entscheiden(v_i, 'freigeben', 'felix', NULL);
  IF v_s <> 'freigegeben' OR (SELECT freigegebene_fassung FROM marketing.inhalte WHERE id=v_i)
     <> (SELECT max(fassung) FROM marketing.inhalt_fassungen WHERE inhalt=v_i) THEN
    RAISE EXCEPTION 'PROBE: Freigabe setzt nicht die neueste Fassung'; END IF;
  BEGIN
    PERFORM marketing.pult_entscheiden(v_i, 'ablehnen', 'felix', 'x');
    RAISE EXCEPTION 'PROBE: zweites Urteil ging durch';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
  END;
END $$;
-- Gestalt-Pruefung der Regler
DO $$ BEGIN
  IF marketing.pult_gestalt_fehler('{"grund":"#000000","text":"#ffffff","akzent":"#5eead4","flaeche":"#111111","text_hell":"#ffffff","text_leise":"#999999","gold":"#fbbf24","handlung_text":"#000000","schrift":"serif","rundung":8,"abstand":"mittel"}') IS NOT NULL THEN
    RAISE EXCEPTION 'PROBE: gueltige Gestalt abgewiesen'; END IF;
  IF marketing.pult_gestalt_fehler('{"grund":"rot"}') IS NULL THEN
    RAISE EXCEPTION 'PROBE: Farbe rot angenommen'; END IF;
  IF marketing.pult_gestalt_fehler('{"grund":"#000000","text":"#ffffff","akzent":"#5eead4","flaeche":"#111111","text_hell":"#ffffff","text_leise":"#999999","gold":"#fbbf24","handlung_text":"#000000","rundung":999}') IS NULL THEN
    RAISE EXCEPTION 'PROBE: Rundung 999 angenommen'; END IF;
  IF marketing.pult_gestalt_fehler('{"grund":"#000000","text":"#ffffff","akzent":"#5eead4","flaeche":"#111111","text_hell":"#ffffff","text_leise":"#999999","gold":"#fbbf24","handlung_text":"#000000","schrift":"comic"}') IS NULL THEN
    RAISE EXCEPTION 'PROBE: unbekannte Schrift angenommen'; END IF;
  IF marketing.pult_gestalt_fehler(jsonb_build_object('grund','#000000','text','#ffffff','akzent','#5eead4','flaeche','#111111','text_hell','#ffffff','text_leise','#999999','gold','#fbbf24','handlung_text','#000000','logo', 'data:image/png;base64,' || repeat('A', 210000))) IS NULL THEN
    RAISE EXCEPTION 'PROBE: Logo ueber 150 KB angenommen'; END IF;
END $$;
-- Layout speichern: neue Fassung, Gestalt uebernommen; ungueltige Gestalt abgewiesen
DO $$ DECLARE v_n int; v_g jsonb; BEGIN
  SELECT gestalt INTO v_g FROM marketing.layout_vorlagen WHERE name='dunkel';
  v_n := marketing.pult_layout_speichern('dunkel', v_g || '{"rundung":4}', 'felix');
  IF (SELECT fassung FROM marketing.layout_vorlagen WHERE name='dunkel') <> v_n
     OR (SELECT gestalt->>'rundung' FROM marketing.layout_vorlagen WHERE name='dunkel') <> '4' THEN
    RAISE EXCEPTION 'PROBE: Layout-Fassung nicht uebernommen'; END IF;
  BEGIN
    PERFORM marketing.pult_layout_speichern('dunkel', '{"grund":"rot"}', 'felix');
    RAISE EXCEPTION 'PROBE: ungueltige Layout-Gestalt gespeichert';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE 'PROBE:%' THEN RAISE; END IF;
  END;
END $$;
-- Standard: genau einer je Mandant und Inhaltsart
DO $$ BEGIN
  PERFORM marketing.pult_layout_als_standard('hell');
  PERFORM marketing.pult_layout_als_standard('dunkel');
  IF (SELECT count(*) FROM marketing.layout_vorlagen
      WHERE standard AND mandant='vibemind'
        AND inhaltsart=(SELECT inhaltsart FROM marketing.layout_vorlagen WHERE name='dunkel')) <> 1 THEN
    RAISE EXCEPTION 'PROBE: nicht genau ein Standard'; END IF;
END $$;
ROLLBACK;
```

- [ ] **Step 2: Rot sehen auf der VM**

```bash
scp spaces/marketing/db/verify_050.sql offload-vm:/tmp/verify_050.sql
ssh offload-vm 'docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < /tmp/verify_050.sql'
```

Expected: FEHLER `relation "marketing.mandanten" does not exist`.

- [ ] **Step 3: 050_marketing_pult.sql schreiben**

```sql
-- 050_marketing_pult.sql — Datenmodell des Marketing-Pults (Spec sales-claw
-- docs/superpowers/specs/2026-09-29-marketing-pult-design.md §3.3). Nur
-- Ergaenzungen; broadcast_proposals und Formular-Vorlagen bleiben unberuehrt.
-- Idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS marketing.mandanten (
    id          text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$'),
    name        text NOT NULL,
    aktiv       boolean NOT NULL DEFAULT false,
    verteiler   text[] NOT NULL DEFAULT '{}',
    pflichtteil jsonb NOT NULL DEFAULT '{}'::jsonb
);
INSERT INTO marketing.mandanten (id, name, aktiv, verteiler, pflichtteil) VALUES
  ('vibemind',   'VibeMind',   true,  ARRAY['sales'],
   '{"impressum": "", "abmelde_hinweis": "Du bekommst diese Mail, weil du dich eingetragen hast. Abmelden: {abmeldelink}"}'),
  ('fin2gether', 'fin2gether', false, ARRAY[]::text[],
   '{"impressum": "", "abmelde_hinweis": "", "vermittlerangaben": ""}')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS marketing.inhalte (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mandant              text NOT NULL REFERENCES marketing.mandanten(id),
    art                  text NOT NULL CHECK (art IN ('newsletter','post','material')),
    titel                text NOT NULL CHECK (length(btrim(titel)) > 0),
    status               text NOT NULL DEFAULT 'entwurf'
                         CHECK (status IN ('entwurf','freigegeben','abgelehnt')),
    freigegebene_fassung int,
    entschieden_von      text,
    entschieden_am       timestamptz,
    grund                text,
    herkunft_proposal    uuid UNIQUE REFERENCES marketing.broadcast_proposals(id),
    erstellt_am          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT inhalte_entscheid_hat_urheber
      CHECK (status = 'entwurf' OR (entschieden_von IS NOT NULL AND entschieden_am IS NOT NULL)),
    CONSTRAINT inhalte_freigabe_hat_fassung
      CHECK (status <> 'freigegeben' OR freigegebene_fassung IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS inhalte_mandant_status_idx ON marketing.inhalte (mandant, status, art);

CREATE TABLE IF NOT EXISTS marketing.inhalt_fassungen (
    inhalt         uuid NOT NULL REFERENCES marketing.inhalte(id),
    fassung        int  NOT NULL CHECK (fassung >= 1),
    felder         jsonb NOT NULL,
    layout         text NOT NULL,
    layout_fassung int,
    urheber        text NOT NULL CHECK (urheber IN ('agent','betreiber')),
    erstellt_am    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (inhalt, fassung)
);

CREATE OR REPLACE FUNCTION marketing._fassung_unveraenderlich() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Fassungen sind unveraenderlich - speichern legt eine neue an';
END $$;
DROP TRIGGER IF EXISTS trg_inhalt_fassung_unveraenderlich ON marketing.inhalt_fassungen;
CREATE TRIGGER trg_inhalt_fassung_unveraenderlich
  BEFORE UPDATE OR DELETE ON marketing.inhalt_fassungen
  FOR EACH ROW EXECUTE FUNCTION marketing._fassung_unveraenderlich();

ALTER TABLE marketing.layout_vorlagen ADD COLUMN IF NOT EXISTS mandant text REFERENCES marketing.mandanten(id);
ALTER TABLE marketing.layout_vorlagen ADD COLUMN IF NOT EXISTS inhaltsart text
  CHECK (inhaltsart IS NULL OR inhaltsart IN ('newsletter','post','material'));
ALTER TABLE marketing.layout_vorlagen ADD COLUMN IF NOT EXISTS fassung int NOT NULL DEFAULT 1;
ALTER TABLE marketing.layout_vorlagen ADD COLUMN IF NOT EXISTS standard boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS layout_standard_je_art
  ON marketing.layout_vorlagen (mandant, inhaltsart) WHERE standard;

CREATE TABLE IF NOT EXISTS marketing.layout_fassungen (
    layout      text NOT NULL REFERENCES marketing.layout_vorlagen(name),
    fassung     int  NOT NULL CHECK (fassung >= 1),
    gestalt     jsonb NOT NULL,
    erstellt_von text NOT NULL,
    erstellt_am timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (layout, fassung)
);
DROP TRIGGER IF EXISTS trg_layout_fassung_unveraenderlich ON marketing.layout_fassungen;
CREATE TRIGGER trg_layout_fassung_unveraenderlich
  BEFORE UPDATE OR DELETE ON marketing.layout_fassungen
  FOR EACH ROW EXECUTE FUNCTION marketing._fassung_unveraenderlich();

-- Bestand: die drei Gewaender sind VibeMind-Layouts fuer Newsletter,
-- 'dunkel' ist Standard. Fassung 1 = heutige Gestalt.
UPDATE marketing.layout_vorlagen SET mandant='vibemind', inhaltsart='newsletter'
 WHERE art='layout' AND mandant IS NULL;
UPDATE marketing.layout_vorlagen SET standard=true
 WHERE name='dunkel' AND art='layout'
   AND NOT EXISTS (SELECT 1 FROM marketing.layout_vorlagen
                   WHERE standard AND mandant='vibemind' AND inhaltsart='newsletter');
INSERT INTO marketing.layout_fassungen (layout, fassung, gestalt, erstellt_von)
SELECT name, 1, gestalt, coalesce(vorgeschlagen_von, 'bestand')
  FROM marketing.layout_vorlagen WHERE art='layout'
ON CONFLICT DO NOTHING;

-- Bestand: jeder broadcast_proposal wird ein VibeMind-Newsletter mit Fassung 1.
INSERT INTO marketing.inhalte (mandant, art, titel, status, herkunft_proposal, erstellt_am)
SELECT 'vibemind', 'newsletter',
       coalesce(nullif(btrim(p.draft_subject), ''), left(p.draft_body_text, 60)),
       'entwurf', p.id, p.created_at
  FROM marketing.broadcast_proposals p
ON CONFLICT (herkunft_proposal) DO NOTHING;
INSERT INTO marketing.inhalt_fassungen (inhalt, fassung, felder, layout, layout_fassung, urheber, erstellt_am)
SELECT i.id, 1,
       jsonb_build_object(
         'betreff', coalesce(p.draft_subject, ''),
         'vorschautext', '',
         'abschnitte', jsonb_build_array(jsonb_build_object('titel', '', 'text', p.draft_body_text)),
         'knopf_text', '', 'knopf_link', ''),
       'dunkel', 1, 'agent', p.created_at
  FROM marketing.inhalte i JOIN marketing.broadcast_proposals p ON p.id = i.herkunft_proposal
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION marketing.pult_gestalt_fehler(p jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_f text;
BEGIN
  v_f := marketing.gestalt_pruefen(p);           -- acht Farben, #rrggbb, Kontrastregeln (044)
  IF v_f IS NOT NULL THEN RETURN v_f; END IF;
  IF p ? 'schrift' AND NOT (p->>'schrift' IN ('system','serif','mono')) THEN
    RETURN 'schrift muss system, serif oder mono sein'; END IF;
  IF p ? 'abstand' AND NOT (p->>'abstand' IN ('eng','mittel','weit')) THEN
    RETURN 'abstand muss eng, mittel oder weit sein'; END IF;
  IF p ? 'rundung' AND (jsonb_typeof(p->'rundung') <> 'number'
                        OR (p->>'rundung')::numeric < 0 OR (p->>'rundung')::numeric > 24) THEN
    RETURN 'rundung muss eine Zahl von 0 bis 24 sein'; END IF;
  IF p ? 'kopf_text' AND length(p->>'kopf_text') > 120 THEN
    RETURN 'kopf_text hoechstens 120 Zeichen'; END IF;
  IF p ? 'fuss_text' AND length(p->>'fuss_text') > 300 THEN
    RETURN 'fuss_text hoechstens 300 Zeichen'; END IF;
  IF p ? 'logo' AND (p->>'logo' !~ '^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$'
                     OR length(p->>'logo') > 204800) THEN
    RETURN 'logo muss ein PNG/JPEG unter 150 KB sein'; END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_fassung_speichern(
    p_inhalt uuid, p_felder jsonb, p_layout text, p_urheber text) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_n int;
BEGIN
  IF jsonb_typeof(p_felder) IS DISTINCT FROM 'object'
     OR length(btrim(coalesce(p_felder->>'betreff', ''))) = 0 THEN
    RAISE EXCEPTION 'Ohne Betreff gibt es keine Fassung'; END IF;
  IF jsonb_typeof(p_felder->'abschnitte') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_felder->'abschnitte') = 0 THEN
    RAISE EXCEPTION 'Mindestens ein Abschnitt ist noetig'; END IF;
  IF NOT EXISTS (SELECT 1 FROM marketing.layout_vorlagen WHERE name = p_layout AND art = 'layout') THEN
    RAISE EXCEPTION 'Layout % gibt es nicht', p_layout; END IF;
  PERFORM 1 FROM marketing.inhalte WHERE id = p_inhalt AND status = 'entwurf' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Nur Entwuerfe lassen sich bearbeiten'; END IF;
  SELECT coalesce(max(fassung), 0) + 1 INTO v_n FROM marketing.inhalt_fassungen WHERE inhalt = p_inhalt;
  INSERT INTO marketing.inhalt_fassungen (inhalt, fassung, felder, layout, layout_fassung, urheber)
  VALUES (p_inhalt, v_n, p_felder, p_layout,
          (SELECT fassung FROM marketing.layout_vorlagen WHERE name = p_layout), p_urheber);
  RETURN v_n;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_entscheiden(
    p_inhalt uuid, p_urteil text, p_von text, p_grund text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v_status text;
BEGIN
  IF p_urteil NOT IN ('freigeben','ablehnen') THEN
    RAISE EXCEPTION 'Urteil muss freigeben oder ablehnen sein'; END IF;
  IF length(btrim(coalesce(p_von, ''))) = 0 THEN
    RAISE EXCEPTION 'Ohne Namen kein Urteil'; END IF;
  SELECT status INTO v_status FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE;
  IF v_status IS DISTINCT FROM 'entwurf' THEN
    RAISE EXCEPTION 'Schon entschieden (%)', coalesce(v_status, 'unbekannt'); END IF;
  UPDATE marketing.inhalte
     SET status = CASE p_urteil WHEN 'freigeben' THEN 'freigegeben' ELSE 'abgelehnt' END,
         freigegebene_fassung = CASE p_urteil WHEN 'freigeben'
           THEN (SELECT max(fassung) FROM marketing.inhalt_fassungen WHERE inhalt = p_inhalt) END,
         entschieden_von = p_von, entschieden_am = now(), grund = p_grund
   WHERE id = p_inhalt
  RETURNING status INTO v_status;
  RETURN v_status;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_layout_speichern(
    p_name text, p_gestalt jsonb, p_von text) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_f text; v_n int;
BEGIN
  v_f := marketing.pult_gestalt_fehler(p_gestalt);
  IF v_f IS NOT NULL THEN RAISE EXCEPTION 'Layout ungueltig: %', v_f; END IF;
  PERFORM 1 FROM marketing.layout_vorlagen WHERE name = p_name AND art = 'layout' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Layout % gibt es nicht', p_name; END IF;
  SELECT coalesce(max(fassung), 0) + 1 INTO v_n FROM marketing.layout_fassungen WHERE layout = p_name;
  INSERT INTO marketing.layout_fassungen (layout, fassung, gestalt, erstellt_von)
  VALUES (p_name, v_n, p_gestalt, p_von);
  UPDATE marketing.layout_vorlagen SET gestalt = p_gestalt, fassung = v_n WHERE name = p_name;
  RETURN v_n;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_layout_als_standard(p_name text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_m text; v_a text;
BEGIN
  SELECT mandant, inhaltsart INTO v_m, v_a FROM marketing.layout_vorlagen
   WHERE name = p_name AND art = 'layout' FOR UPDATE;
  IF v_m IS NULL THEN RAISE EXCEPTION 'Layout % gibt es nicht', p_name; END IF;
  UPDATE marketing.layout_vorlagen SET standard = false
   WHERE mandant = v_m AND inhaltsart = v_a AND standard AND name <> p_name;
  UPDATE marketing.layout_vorlagen SET standard = true WHERE name = p_name;
END $$;

COMMIT;
```

Vor dem Festschreiben: `044_layout_vorlagen.sql` lesen und prüfen, ob `layout_vorlagen` einen Trigger hat, der UPDATEs von `gestalt` auf freigegebenen Zeilen verbietet (Muster `trg_freigabe_unveraenderlich` aus 045). Falls ja: `pult_layout_speichern` setzt vor dem UPDATE dieselbe transaktionslokale Flagge, die 044/046 dafür vorsehen, und setzt sie danach zurück — im Report belegen, welche.

- [ ] **Step 4: Einspielen und grün sehen**

```bash
scp spaces/marketing/db/050_marketing_pult.sql offload-vm:/tmp/050.sql
ssh offload-vm 'docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < /tmp/050.sql'
ssh offload-vm 'for v in 045 046 047 048 049 050; do docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -q < /tmp/verify_$v.sql && echo verify_$v gruen; done'
```

(`verify_045…049` vorher per `scp` nach `/tmp` kopieren.) Expected: alle sechs „gruen". Dann 050 ein zweites Mal einspielen (Idempotenz) und verify_050 erneut grün.

- [ ] **Step 5: Commit** (PowerShell, Worktree)

```powershell
git add -- spaces/marketing/db/050_marketing_pult.sql spaces/marketing/db/verify_050.sql
git commit -m "feat(marketing): Datenmodell des Marketing-Pults (050)"
```

---

### Task 2: Render-Modul (Mail, Handy, PDF)

Arbeitsort: Worktree, `spaces/marketing/claw/`.

**Files:**
- Create: `spaces/marketing/claw/pult_render.py`
- Test: `spaces/marketing/claw/tests/test_pult_render.py`

**Interfaces:**
- Produces:
  - `pult_render.mail_html(felder: dict, gestalt: dict, pflichtteil: dict, breite: int = 600) -> str` — vollständiges HTML-Dokument, tabellenbasiert, Inline-CSS.
  - `pult_render.handy_html(felder, gestalt, pflichtteil) -> str` = `mail_html(..., breite=380)`.
  - `pult_render.pdf_bytes(felder: dict, gestalt: dict) -> bytes` — über `pdf.bauen(titel=betreff, text=Abschnitte, untertitel=vorschautext, handlung=knopf_text, gestalt=nur die acht Farben)`.
  - `pult_render.BEISPIEL_FELDER: dict` — Beispielinhalt für Layout-Vorschauen.
  - Felder-Schema: `{"betreff": str, "vorschautext": str, "abschnitte": [{"titel": str, "text": str}], "knopf_text": str, "knopf_link": str}`.

- [ ] **Step 1: Failing tests**

```python
"""Render-Modul des Marketing-Pults (Spec §3.4). Eine Quelle fuer Vorschau
und Ergebnis."""
from spaces.marketing.claw import pult_render as r

GESTALT = {"grund": "#0f2422", "text": "#cfe3df", "akzent": "#5eead4",
           "flaeche": "#1d3b39", "text_hell": "#e9fbf6", "text_leise": "#8aa3a0",
           "gold": "#fbbf24", "handlung_text": "#0f2422"}
PFLICHT = {"impressum": "VibeMind, Musterstr. 1, 12345 Stadt",
           "abmelde_hinweis": "Abmelden: {abmeldelink}"}
FELDER = {"betreff": "Early Access", "vorschautext": "Kurz vorab",
          "abschnitte": [{"titel": "Warum", "text": "Erster Absatz.\n\nZweiter Absatz."}],
          "knopf_text": "Jetzt eintragen", "knopf_link": "https://vibemind.space/warteliste"}


def test_mail_traegt_inhalt_farben_und_pflichtteil():
    html = r.mail_html(FELDER, GESTALT, PFLICHT)
    assert html.startswith("<!doctype html>")
    for teil in ("Early Access", "Warum", "Erster Absatz.", "Zweiter Absatz.",
                 "Jetzt eintragen", 'href="https://vibemind.space/warteliste"',
                 "#0f2422", "#5eead4", "Musterstr. 1", "Abmelden:"):
        assert teil in html, teil
    assert "{abmeldelink}" not in html          # Platzhalter sichtbar ersetzt


def test_handy_ist_schmaler():
    assert 'width="380"' in r.handy_html(FELDER, GESTALT, PFLICHT)
    assert 'width="600"' in r.mail_html(FELDER, GESTALT, PFLICHT)


def test_skript_im_text_wird_nie_ausgefuehrt():
    boese = dict(FELDER, abschnitte=[{"titel": "<script>alert(1)</script>",
                                      "text": '<img src=x onerror="alert(2)">'}],
                 betreff='"><b>x')
    html = r.mail_html(boese, GESTALT, PFLICHT)
    assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_knopf_nur_mit_https_link():
    html = r.mail_html(dict(FELDER, knopf_link="javascript:alert(1)"), GESTALT, PFLICHT)
    assert "javascript:" not in html
    assert "Jetzt eintragen" not in html          # ohne gueltigen Link kein Knopf


def test_fehlendes_impressum_ist_sichtbar():
    html = r.mail_html(FELDER, GESTALT, dict(PFLICHT, impressum=""))
    assert "Impressum fehlt" in html


def test_regler_wirken():
    g = dict(GESTALT, schrift="serif", rundung=12, abstand="weit",
             kopf_text="VibeMind Neuigkeiten", fuss_text="Danke fuers Lesen")
    html = r.mail_html(FELDER, g, PFLICHT)
    assert "Georgia" in html and "border-radius:12px" in html
    assert "VibeMind Neuigkeiten" in html and "Danke fuers Lesen" in html


def test_logo_nur_als_daten_bild():
    g = dict(GESTALT, logo="data:image/png;base64,iVBORw0KGgo=")
    assert '<img src="data:image/png;base64,iVBORw0KGgo="' in r.mail_html(FELDER, g, PFLICHT)
    g = dict(GESTALT, logo="https://boese.de/x.png")
    assert "boese.de" not in r.mail_html(FELDER, g, PFLICHT)


def test_pdf_entsteht():
    daten = r.pdf_bytes(FELDER, dict(GESTALT, rundung=4))
    assert daten.startswith(b"%PDF")


def test_beispiel_felder_sind_vollstaendig():
    assert r.BEISPIEL_FELDER["betreff"] and r.BEISPIEL_FELDER["abschnitte"]
    assert r.mail_html(r.BEISPIEL_FELDER, GESTALT, PFLICHT)
```

- [ ] **Step 2: Rot sehen**

Run: `…\.venv\Scripts\python.exe -m pytest spaces\marketing\claw\tests\test_pult_render.py -q`
Expected: FAIL `ImportError … pult_render`

- [ ] **Step 3: Implementieren**

```python
"""Render-Modul des Marketing-Pults (sales-claw Spec 2026-09-29-marketing-
pult-design.md §3.4): EINE Stelle baut Mail-HTML, Handy-HTML und PDF aus einer
Fassung und einer Layout-Gestalt — Vorschau und Ergebnis kommen aus derselben
Quelle.

Alles Fremde (Entwurfstext, Kopf/Fuss, Impressum) wird escaped; Links nur
https; Logos nur als data:-Bild (kein Nachladen fremder Server beim Oeffnen).
"""
from __future__ import annotations

import html
import re

from spaces.marketing.claw import pdf

SCHRIFTEN = {
    "system": "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "serif": "Georgia, 'Times New Roman', serif",
    "mono": "'SFMono-Regular', Consolas, 'Courier New', monospace",
}
ABSTAENDE = {"eng": 12, "mittel": 20, "weit": 32}
_LOGO = re.compile(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$")

BEISPIEL_FELDER = {
    "betreff": "Neuigkeiten aus der Werkstatt",
    "vorschautext": "Was sich diesen Monat getan hat",
    "abschnitte": [
        {"titel": "Das Wichtigste", "text": "Ein kurzer Absatz, der zeigt, wie Text in diesem Layout wirkt.\n\nUnd ein zweiter Absatz darunter."},
        {"titel": "Als Naechstes", "text": "Noch ein Abschnitt, damit man Abstaende und Ueberschriften sieht."},
    ],
    "knopf_text": "Mehr erfahren",
    "knopf_link": "https://vibemind.space",
}


def _e(wert) -> str:
    return html.escape(str(wert if wert is not None else ""), quote=True)


def _absaetze(text: str, farbe: str, abstand: int) -> str:
    teile = [t.strip() for t in re.split(r"\n\s*\n", text or "") if t.strip()]
    return "".join(
        f'<p style="margin:0 0 {abstand // 2}px 0;color:{farbe};line-height:1.55">'
        f'{_e(t).replace(chr(10), "<br>")}</p>' for t in teile)


def mail_html(felder: dict, gestalt: dict, pflichtteil: dict, breite: int = 600) -> str:
    g = gestalt
    schrift = SCHRIFTEN.get(g.get("schrift", "system"), SCHRIFTEN["system"])
    abstand = ABSTAENDE.get(g.get("abstand", "mittel"), ABSTAENDE["mittel"])
    rundung = int(g.get("rundung", 8))
    kopf, fuss = g.get("kopf_text", ""), g.get("fuss_text", "")
    logo = g.get("logo", "")
    logo_html = (f'<img src="{_e(logo)}" alt="" height="40" style="display:block;margin:0 0 {abstand}px 0">'
                 if isinstance(logo, str) and _LOGO.match(logo) else "")
    abschnitte = "".join(
        (f'<h2 style="margin:0 0 8px 0;color:{g["text_hell"]};font-size:18px">{_e(a.get("titel"))}</h2>'
         if (a.get("titel") or "").strip() else "")
        + _absaetze(a.get("text", ""), g["text"], abstand)
        for a in felder.get("abschnitte") or [])
    link = (felder.get("knopf_link") or "").strip()
    knopf = ""
    if link.startswith("https://") and (felder.get("knopf_text") or "").strip():
        knopf = (f'<a href="{_e(link)}" style="display:inline-block;background:{g["akzent"]};'
                 f'color:{g["handlung_text"]};padding:12px 22px;border-radius:{rundung}px;'
                 f'text-decoration:none;font-weight:600">{_e(felder["knopf_text"])}</a>')
    impressum = (pflichtteil.get("impressum") or "").strip()
    impressum_html = (_e(impressum) if impressum else
                      '<strong style="color:#ef4444">Impressum fehlt &ndash; im Mandanten hinterlegen</strong>')
    abmelden = _e((pflichtteil.get("abmelde_hinweis") or "").replace("{abmeldelink}", "[Abmeldelink]"))
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        f'<title>{_e(felder.get("betreff"))}</title></head>'
        f'<body style="margin:0;padding:0;background:{g["grund"]};font-family:{schrift}">'
        f'<span style="display:none">{_e(felder.get("vorschautext"))}</span>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{g["grund"]}"><tr><td align="center" style="padding:{abstand}px 8px">'
        f'<table role="presentation" width="{int(breite)}" cellpadding="0" cellspacing="0" '
        f'style="max-width:{int(breite)}px;background:{g["flaeche"]};border-radius:{rundung}px">'
        f'<tr><td style="padding:{abstand}px">'
        f'{logo_html}'
        + (f'<div style="color:{g["text_leise"]};font-size:13px;margin-bottom:{abstand // 2}px">{_e(kopf)}</div>' if kopf else "")
        + f'<h1 style="margin:0 0 {abstand}px 0;color:{g["text_hell"]};font-size:24px">{_e(felder.get("betreff"))}</h1>'
        f'{abschnitte}'
        + (f'<div style="margin:{abstand}px 0">{knopf}</div>' if knopf else "")
        + (f'<p style="color:{g["text_leise"]};font-size:13px;margin:{abstand}px 0 0 0">{_e(fuss)}</p>' if fuss else "")
        + f'</td></tr></table>'
        f'<div style="max-width:{int(breite)}px;color:{g["text_leise"]};font-size:11px;line-height:1.5;padding:{abstand}px 8px">'
        f'{impressum_html}<br>{abmelden}</div>'
        '</td></tr></table></body></html>')


def handy_html(felder: dict, gestalt: dict, pflichtteil: dict) -> str:
    return mail_html(felder, gestalt, pflichtteil, breite=380)


def pdf_bytes(felder: dict, gestalt: dict) -> bytes:
    farben = {k: gestalt[k] for k in pdf.GESTALT_SCHLUESSEL}
    text = "\n\n".join(
        ((a.get("titel") or "").strip() + "\n" if (a.get("titel") or "").strip() else "")
        + (a.get("text") or "") for a in felder.get("abschnitte") or [])
    return pdf.bauen(titel=felder.get("betreff") or "", text=text,
                     untertitel=felder.get("vorschautext") or "",
                     handlung=felder.get("knopf_text") or "", gestalt=farben)
```

Vor dem Festschreiben prüfen, dass `pdf.GESTALT_SCHLUESSEL` genau die acht Farbnamen enthält (`claw/pdf.py`); falls der Name anders lautet, den tatsächlichen verwenden und im Report nennen.

- [ ] **Step 4: Grün sehen** — derselbe Befehl, alle Tests PASS; danach `spaces\marketing\claw\tests -q` einmal ganz (keine neuen Roten).

- [ ] **Step 5: Commit**

```powershell
git add -- spaces/marketing/claw/pult_render.py spaces/marketing/claw/tests/test_pult_render.py
git commit -m "feat(marketing): Render-Modul des Pults - Mail, Handy und PDF aus einer Quelle"
```

---

### Task 3: Pult-Router der Marketing-API

Arbeitsort: Worktree, `spaces/marketing/api/`.

**Files:**
- Create: `spaces/marketing/api/pult.py`
- Modify: `spaces/marketing/api/server.py` — Router einbinden (nach den bestehenden Routen, vor dem Mockup-Static-Mount); `MARKETING_PULT_KEY` in `_ENV_KEYS` aufnehmen
- Test: `spaces/marketing/tests/test_pult_api.py`

**Interfaces:**
- Consumes: Task 1 (Tabellen, Funktionen), Task 2 (`pult_render.*`, `BEISPIEL_FELDER`).
- Produces (alle mit Header `X-Pult-Key`, Antworten JSON außer Vorschau):
  - `GET /api/pult/uebersicht?mandant=vibemind` → `{"mandanten": [{id,name,aktiv}], "zaehler": {"entwurf": n, "freigegeben": n, "abgelehnt": n}}`
  - `GET /api/pult/inhalte?mandant=&art=&status=` → `{"inhalte": [{id, art, titel, status, erstellt_am, fassungen, layout}]}` (neueste zuerst)
  - `GET /api/pult/inhalte/{id}` → `{"inhalt": {...}, "fassungen": [{fassung, felder, layout, urheber, erstellt_am}]}`
  - `POST /api/pult/inhalte/{id}/fassungen` Body `{felder, layout, von}` → `{"fassung": n}`
  - `GET /api/pult/inhalte/{id}/vorschau?fassung=n&format=mail|handy|pdf` → `text/html` bzw. `application/pdf`
  - `POST /api/pult/inhalte/{id}/entscheiden` Body `{urteil, von, grund}` → `{"status": "..."}`
  - `GET /api/pult/layouts?mandant=vibemind` → `{"layouts": [{name, beschreibung, inhaltsart, fassung, standard, status, gestalt}]}`
  - `POST /api/pult/layouts/vorschau` Body `{gestalt, mandant, format}` → `text/html` (Beispielinhalt, NICHT gespeichert; ungültige Gestalt → 422 mit deutschem Grund aus `pult_gestalt_fehler`)
  - `POST /api/pult/layouts/{name}/fassungen` Body `{gestalt, von}` → `{"fassung": n}`
  - `POST /api/pult/layouts/{name}/standard` → `{"ok": true}`
  - Fehler: 401 `{"detail": "Pult-Schluessel fehlt oder falsch"}`, 503 wenn `MARKETING_PULT_KEY` leer, 404 unbekannte ID, 422 bei DB-Ablehnung (Text der DB-Meldung).

- [ ] **Step 1: Failing tests** — `spaces/marketing/tests/test_pult_api.py`, ohne echte DB: `_db.query_via_docker`/`query_one` werden durch eine kleine Fälschung ersetzt, die SQL-Aufrufe protokolliert und vorbereitete Zeilen liefert.

```python
"""Pult-Router der Marketing-API (Spec §3.4). Ohne echte Datenbank: _db wird
gefaelscht; geprueft werden Schluesselpflicht, Formen und Weitergabe an die
DB-Funktionen aus 050."""
import pytest
from fastapi.testclient import TestClient

from spaces.marketing.api import pult, server
from spaces.marketing.sync import _db

KEY = "test-pult-key"
GESTALT = {"grund": "#0f2422", "text": "#cfe3df", "akzent": "#5eead4",
           "flaeche": "#1d3b39", "text_hell": "#e9fbf6", "text_leise": "#8aa3a0",
           "gold": "#fbbf24", "handlung_text": "#0f2422"}
FELDER = {"betreff": "B", "vorschautext": "", "abschnitte": [{"titel": "", "text": "T"}],
          "knopf_text": "", "knopf_link": ""}


class FalscheDB:
    def __init__(self):
        self.sql = []
        self.antworten = []          # Liste von Listen (Zeilen) in Aufrufreihenfolge

    def query(self, sql, params=None, container=None, streng=False):
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else []

    def one(self, sql, params=None, container=None, streng=False):
        zeilen = self.query(sql, params, container, streng)
        return zeilen[0] if zeilen else None


@pytest.fixture
def db(monkeypatch):
    f = FalscheDB()
    monkeypatch.setattr(_db, "query_via_docker", f.query)
    monkeypatch.setattr(_db, "query_one", f.one)
    monkeypatch.setenv("MARKETING_PULT_KEY", KEY)
    return f


@pytest.fixture
def c():
    return TestClient(server.app)


H = {"X-Pult-Key": KEY}


def test_ohne_schluessel_401(db, c):
    assert c.get("/api/pult/inhalte").status_code == 401
    assert c.get("/api/pult/inhalte", headers={"X-Pult-Key": "falsch"}).status_code == 401
    assert db.sql == []                          # nichts erreicht die DB


def test_ohne_konfiguration_503(monkeypatch, c):
    monkeypatch.delenv("MARKETING_PULT_KEY", raising=False)
    assert c.get("/api/pult/inhalte", headers=H).status_code == 503


def test_inhalte_liste(db, c):
    db.antworten = [[{"id": "a1", "art": "newsletter", "titel": "X", "status": "entwurf",
                      "erstellt_am": "2026-09-04", "fassungen": 1, "layout": "dunkel"}]]
    r = c.get("/api/pult/inhalte?mandant=vibemind&status=entwurf", headers=H)
    assert r.status_code == 200 and r.json()["inhalte"][0]["id"] == "a1"
    assert "mandant = 'vibemind'" in db.sql[0] and "status = 'entwurf'" in db.sql[0]


def test_filter_wird_nicht_blind_eingesetzt(db, c):
    r = c.get("/api/pult/inhalte?art=newsletter';drop table x;--", headers=H)
    assert r.status_code == 422 and db.sql == []


def test_fassung_speichern_ruft_db_funktion(db, c):
    db.antworten = [[{"fassung": 5}]]
    r = c.post("/api/pult/inhalte/11111111-1111-1111-1111-111111111111/fassungen",
               headers=H, json={"felder": FELDER, "layout": "dunkel", "von": "felix"})
    assert r.status_code == 200 and r.json() == {"fassung": 5}
    assert "marketing.pult_fassung_speichern(" in db.sql[0] and "'betreiber'" in db.sql[0]


def test_ungueltige_id_404_ohne_db(db, c):
    assert c.get("/api/pult/inhalte/keine-uuid", headers=H).status_code == 404
    assert db.sql == []


def test_db_ablehnung_wird_422_mit_grund(db, c, monkeypatch):
    def wirft(*a, **k):
        raise RuntimeError("ERROR:  Nur Entwuerfe lassen sich bearbeiten")
    monkeypatch.setattr(_db, "query_one", wirft)
    r = c.post("/api/pult/inhalte/11111111-1111-1111-1111-111111111111/fassungen",
               headers=H, json={"felder": FELDER, "layout": "dunkel", "von": "felix"})
    assert r.status_code == 422 and "Nur Entwuerfe" in r.json()["detail"]


def test_vorschau_html_und_pdf(db, c):
    iid = "11111111-1111-1111-1111-111111111111"
    zeile = {"felder": FELDER, "gestalt": GESTALT,
             "pflichtteil": {"impressum": "I", "abmelde_hinweis": "A"}}
    db.antworten = [[zeile]]
    r = c.get(f"/api/pult/inhalte/{iid}/vorschau?fassung=1&format=mail", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    db.antworten = [[zeile]]
    r = c.get(f"/api/pult/inhalte/{iid}/vorschau?fassung=1&format=pdf", headers=H)
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")


def test_layout_vorschau_prueft_gestalt(db, c):
    db.antworten = [[{"fehler": "rundung muss eine Zahl von 0 bis 24 sein"}]]
    r = c.post("/api/pult/layouts/vorschau", headers=H,
               json={"gestalt": dict(GESTALT, rundung=999), "mandant": "vibemind", "format": "mail"})
    assert r.status_code == 422 and "rundung" in r.json()["detail"]


def test_layout_vorschau_nutzt_beispiel(db, c):
    db.antworten = [[{"fehler": None}], [{"pflichtteil": {"impressum": "I", "abmelde_hinweis": ""}}]]
    r = c.post("/api/pult/layouts/vorschau", headers=H,
               json={"gestalt": GESTALT, "mandant": "vibemind", "format": "handy"})
    assert r.status_code == 200 and "Neuigkeiten aus der Werkstatt" in r.text
    assert 'width="380"' in r.text


def test_entscheiden(db, c):
    db.antworten = [[{"status": "freigegeben"}]]
    r = c.post("/api/pult/inhalte/11111111-1111-1111-1111-111111111111/entscheiden",
               headers=H, json={"urteil": "freigeben", "von": "felix", "grund": ""})
    assert r.json() == {"status": "freigegeben"}
    assert "marketing.pult_entscheiden(" in db.sql[0]
```

- [ ] **Step 2: Rot sehen** — `…python.exe -m pytest spaces\marketing\tests\test_pult_api.py -q` → FAIL (`ImportError … pult`).

- [ ] **Step 3: Implementieren** — `spaces/marketing/api/pult.py`:

```python
"""Pult-Router der Marketing-API (sales-claw Spec 2026-09-29-marketing-pult-
design.md §3.4). Einziger Gespraechspartner: die Sales-Oberflaeche, mit Header
X-Pult-Key. Ohne konfigurierten Schluessel ist der Router zu (503), nie offen.
Regeln (Fassungen unveraenderlich, ein Urteil, Gestalt-Pruefung) stehen in den
DB-Funktionen aus 050 — hier nur Formen und Weitergabe."""
from __future__ import annotations

import hmac
import json
import os
import re
import uuid as _uuid

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from spaces.marketing.claw import pult_render
from spaces.marketing.sync import _db

router = APIRouter(prefix="/api/pult")
_ARTEN = ("newsletter", "post", "material")
_STATUS = ("entwurf", "freigegeben", "abgelehnt")
_FORMATE = ("mail", "handy", "pdf")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def _schluessel(x_pult_key: str | None) -> None:
    erwartet = os.environ.get("MARKETING_PULT_KEY", "").strip()
    if not erwartet:
        raise HTTPException(503, "misconfigured: MARKETING_PULT_KEY fehlt")
    if not x_pult_key or not hmac.compare_digest(x_pult_key.strip(), erwartet):
        raise HTTPException(401, "Pult-Schluessel fehlt oder falsch")


def _uuid_oder_404(wert: str) -> str:
    try:
        return str(_uuid.UUID(wert))
    except ValueError:
        raise HTTPException(404, "Unbekannter Inhalt")


def _auswahl(wert: str | None, erlaubt: tuple, name: str) -> str | None:
    if wert is None or wert == "":
        return None
    if wert not in erlaubt:
        raise HTTPException(422, f"{name} muss eines von {', '.join(erlaubt)} sein")
    return wert


def _mandant(wert: str | None) -> str:
    wert = wert or "vibemind"
    if not _NAME.match(wert):
        raise HTTPException(422, "Unbekannter Mandant")
    return wert


def _db_grund(fehler: Exception) -> str:
    text = str(fehler)
    treffer = re.search(r"ERROR:\s*(.+)", text)
    return (treffer.group(1) if treffer else text).strip().splitlines()[0][:300]


def _db_einer(sql: str) -> dict | None:
    try:
        return _db.query_one(sql, streng=True)
    except Exception as e:  # DB lehnt ab -> deutscher Grund an den Aufrufer
        raise HTTPException(422, _db_grund(e))


lit = _db._sql_literal


@router.get("/uebersicht")
def uebersicht(mandant: str | None = None, x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    m = _mandant(mandant)
    mandanten = _db.query_via_docker(
        "SELECT id, name, aktiv FROM marketing.mandanten ORDER BY aktiv DESC, name")
    zahlen = _db.query_via_docker(
        f"SELECT status, count(*)::int AS n FROM marketing.inhalte WHERE mandant = {lit(m)} GROUP BY status")
    zaehler = {s: 0 for s in _STATUS}
    zaehler.update({z["status"]: z["n"] for z in zahlen})
    return {"mandanten": mandanten, "zaehler": zaehler}


@router.get("/inhalte")
def inhalte(mandant: str | None = None, art: str | None = None, status: str | None = None,
            x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    m = _mandant(mandant)
    wo = [f"i.mandant = {lit(m)}"]
    if (a := _auswahl(art, _ARTEN, "art")):
        wo.append(f"i.art = {lit(a)}")
    if (s := _auswahl(status, _STATUS, "status")):
        wo.append(f"i.status = {lit(s)}")
    zeilen = _db.query_via_docker(
        "SELECT i.id, i.art, i.titel, i.status, i.erstellt_am::text AS erstellt_am, "
        "  (SELECT count(*) FROM marketing.inhalt_fassungen f WHERE f.inhalt = i.id)::int AS fassungen, "
        "  (SELECT f.layout FROM marketing.inhalt_fassungen f WHERE f.inhalt = i.id "
        "     ORDER BY f.fassung DESC LIMIT 1) AS layout "
        f"FROM marketing.inhalte i WHERE {' AND '.join(wo)} ORDER BY i.erstellt_am DESC")
    return {"inhalte": zeilen}


@router.get("/inhalte/{iid}")
def inhalt(iid: str, x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    kopf = _db.query_one(
        "SELECT id, mandant, art, titel, status, freigegebene_fassung, entschieden_von, "
        f"entschieden_am::text AS entschieden_am, grund FROM marketing.inhalte WHERE id = {lit(i)}::uuid")
    if not kopf:
        raise HTTPException(404, "Unbekannter Inhalt")
    fassungen = _db.query_via_docker(
        "SELECT fassung, felder, layout, urheber, erstellt_am::text AS erstellt_am "
        f"FROM marketing.inhalt_fassungen WHERE inhalt = {lit(i)}::uuid ORDER BY fassung DESC")
    return {"inhalt": kopf, "fassungen": fassungen}


@router.post("/inhalte/{iid}/fassungen")
def fassung_speichern(iid: str, payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    felder = payload.get("felder")
    if not isinstance(felder, dict):
        raise HTTPException(422, "felder fehlt")
    zeile = _db_einer(
        f"SELECT marketing.pult_fassung_speichern({lit(i)}::uuid, "
        f"{lit(json.dumps(felder, ensure_ascii=False))}::jsonb, "
        f"{lit(str(payload.get('layout') or ''))}, 'betreiber') AS fassung")
    return {"fassung": int(zeile["fassung"])}


@router.get("/inhalte/{iid}/vorschau")
def vorschau(iid: str, fassung: int = Query(..., ge=1), format: str = "mail",
             x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    fmt = _auswahl(format, _FORMATE, "format")
    zeile = _db.query_one(
        "SELECT f.felder, l.gestalt, m.pflichtteil FROM marketing.inhalt_fassungen f "
        "JOIN marketing.inhalte i ON i.id = f.inhalt "
        "JOIN marketing.mandanten m ON m.id = i.mandant "
        "JOIN marketing.layout_vorlagen l ON l.name = f.layout "
        f"WHERE f.inhalt = {lit(i)}::uuid AND f.fassung = {int(fassung)}")
    if not zeile:
        raise HTTPException(404, "Unbekannte Fassung")
    return _rendern(zeile["felder"], zeile["gestalt"], zeile["pflichtteil"], fmt)


def _rendern(felder: dict, gestalt: dict, pflichtteil: dict, fmt: str) -> Response:
    if fmt == "pdf":
        return Response(pult_render.pdf_bytes(felder, gestalt), media_type="application/pdf")
    baue = pult_render.handy_html if fmt == "handy" else pult_render.mail_html
    return HTMLResponse(baue(felder, gestalt, pflichtteil))


@router.post("/inhalte/{iid}/entscheiden")
def entscheiden(iid: str, payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    zeile = _db_einer(
        f"SELECT marketing.pult_entscheiden({lit(i)}::uuid, {lit(str(payload.get('urteil') or ''))}, "
        f"{lit(str(payload.get('von') or ''))}, {lit(str(payload.get('grund') or ''))}) AS status")
    return {"status": zeile["status"]}


@router.get("/layouts")
def layouts(mandant: str | None = None, x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    m = _mandant(mandant)
    return {"layouts": _db.query_via_docker(
        "SELECT name, beschreibung, inhaltsart, fassung, standard, status, gestalt "
        f"FROM marketing.layout_vorlagen WHERE art = 'layout' AND mandant = {lit(m)} "
        "ORDER BY inhaltsart, standard DESC, name")}


@router.post("/layouts/vorschau")
def layout_vorschau(payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    gestalt = payload.get("gestalt")
    if not isinstance(gestalt, dict):
        raise HTTPException(422, "gestalt fehlt")
    fmt = _auswahl(payload.get("format") or "mail", _FORMATE, "format")
    fehler = _db.query_one(
        f"SELECT marketing.pult_gestalt_fehler({lit(json.dumps(gestalt, ensure_ascii=False))}::jsonb) AS fehler")
    if fehler and fehler.get("fehler"):
        raise HTTPException(422, fehler["fehler"])
    m = _db.query_one(
        f"SELECT pflichtteil FROM marketing.mandanten WHERE id = {lit(_mandant(payload.get('mandant')))}")
    return _rendern(pult_render.BEISPIEL_FELDER, gestalt, (m or {}).get("pflichtteil") or {}, fmt)


@router.post("/layouts/{name}/fassungen")
def layout_speichern(name: str, payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    if not _NAME.match(name):
        raise HTTPException(404, "Unbekanntes Layout")
    zeile = _db_einer(
        f"SELECT marketing.pult_layout_speichern({lit(name)}, "
        f"{lit(json.dumps(payload.get('gestalt') or {}, ensure_ascii=False))}::jsonb, "
        f"{lit(str(payload.get('von') or 'betreiber'))}) AS fassung")
    return {"fassung": int(zeile["fassung"])}


@router.post("/layouts/{name}/standard")
def layout_standard(name: str, x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    if not _NAME.match(name):
        raise HTTPException(404, "Unbekanntes Layout")
    _db_einer(f"SELECT marketing.pult_layout_als_standard({lit(name)}) IS NULL AS ok")
    return {"ok": True}
```

In `server.py`: `from spaces.marketing.api import pult as _pult` und `app.include_router(_pult.router)` direkt vor dem Block „Static-serve of the mockup"; `"MARKETING_PULT_KEY"` an `_ENV_KEYS` anhängen.

Vor dem Festschreiben prüfen: (a) ob `_db.query_one` den Parameter `streng` kennt (`sync/_db.py:189`); falls nicht, ohne `streng` aufrufen und im Report nennen; (b) ob `query_via_docker` jsonb-Spalten als dict zurückgibt (bestehende Route `layout_vorlagen` liefert `gestalt` als Objekt — bestätigen). Der Test `test_filter_wird_nicht_blind_eingesetzt` muss grün sein: der Filter `art` wird vor jedem SQL gegen `_ARTEN` geprüft.

- [ ] **Step 4: Grün sehen** — `test_pult_api.py` PASS; dann `spaces\marketing\tests -q` (bekannter Rotstand: nur `test_cockpit_contract`).

- [ ] **Step 5: Commit**

```powershell
git add -- spaces/marketing/api/pult.py spaces/marketing/api/server.py spaces/marketing/tests/test_pult_api.py
git commit -m "feat(marketing): Pult-Router der API mit X-Pult-Key"
```

---

### Task 4: Menüpunkt Marketing, Übersicht und Entwürfe in sales-ui

Arbeitsort: `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw`.

**Files:**
- Create: `sales-mcp/marketing_pult.py` (Client)
- Create: `sales-mcp/ui_marketing.py` (Seiten)
- Modify: `sales-mcp/ui.py` — `_ADMIN_BASIS_PFADE` um `"/marketing"` erweitern; Gruppe „Marketing" in `_GRUPPEN`; Routen aus `ui_marketing.routen(...)` in die Routenliste; Schalter vom 25.09. entfernen (`_marketing_url_lesen`, `MARKETING_URL`, `_marketing_link`, `.schalter`-CSS, beide `if marketing:`-Blöcke in `_seitenleiste`)
- Modify: `docker-compose.yml` (Dienst `sales-ui`): `MARKETING_URL` ersetzen durch `MARKETING_PULT_URL=${MARKETING_PULT_URL:-}` und `MARKETING_PULT_KEY=${MARKETING_PULT_KEY:-}`
- Modify: `.env.example` — `MARKETING_URL`-Block ersetzen durch `MARKETING_PULT_URL`/`MARKETING_PULT_KEY` (Kommentar: nur Basis-Laden; Schlüssel nie ausgeben)
- Delete: `sales-mcp/tests/test_marketing_schalter.py`
- Test: `sales-mcp/tests/test_marketing_pult.py`

**Interfaces:**
- Consumes: Task 3 (Endpunkte, Formen).
- Produces:
  - `marketing_pult.PultFehler(Exception)` mit Attribut `art` ∈ `{"nicht_verbunden", "nicht_erreichbar", "abgelehnt", "unbekannt"}` und `grund: str`.
  - `marketing_pult.anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False) -> dict | tuple[bytes, str]` — `roh=True` liefert `(bytes, content_type)`.
  - `marketing_pult.eingerichtet() -> bool` (URL und Schlüssel gesetzt).
  - `ui_marketing.routen(ui) -> list[Route]` — Seiten `/marketing`, `/marketing/entwuerfe`, `/marketing/entwurf/{iid}`, `/marketing/entwurf/{iid}/vorschau`, POST `/marketing/entwurf/{iid}/speichern`, POST `/marketing/entwurf/{iid}/entscheiden`.

- [ ] **Step 1: Failing tests** — `sales-mcp/tests/test_marketing_pult.py`. Der Client wird durch eine Fälschung ersetzt; keine DB, kein Netz.

```python
"""Marketing-Pult in sales-ui (Spec 2026-09-29-marketing-pult-design.md §3.1,
Stufe 1). Der Client zur Marketing-API wird gefaelscht."""
import pytest
from starlette.testclient import TestClient

import marketing_pult
import server
import ui

HOST = {"host": "127.0.0.1:8791"}
IID = "11111111-1111-1111-1111-111111111111"
FELDER = {"betreff": "Early Access", "vorschautext": "", "abschnitte": [{"titel": "", "text": "Hallo"}],
          "knopf_text": "", "knopf_link": ""}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
        if self.fehler:
            raise self.fehler
        if roh:
            return (b"<!doctype html><p>Vorschau</p>", "text/html")
        if pfad.startswith("/uebersicht"):
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": False}],
                    "zaehler": {"entwurf": 7, "freigegeben": 0, "abgelehnt": 0}}
        if pfad.startswith("/inhalte?"):
            return {"inhalte": [{"id": IID, "art": "newsletter", "titel": "Early Access",
                                 "status": "entwurf", "erstellt_am": "2026-09-04", "fassungen": 2,
                                 "layout": "dunkel"}]}
        if pfad == f"/inhalte/{IID}":
            return {"inhalt": {"id": IID, "art": "newsletter", "titel": "Early Access",
                               "status": "entwurf", "mandant": "vibemind"},
                    "fassungen": [{"fassung": 2, "felder": FELDER, "layout": "dunkel",
                                   "urheber": "betreiber", "erstellt_am": "x"},
                                  {"fassung": 1, "felder": FELDER, "layout": "dunkel",
                                   "urheber": "agent", "erstellt_am": "y"}]}
        if pfad == "/layouts?mandant=vibemind":
            return {"layouts": [{"name": "dunkel", "inhaltsart": "newsletter"},
                                {"name": "hell", "inhaltsart": "newsletter"}]}
        if pfad.endswith("/fassungen"):
            return {"fassung": 3}
        if pfad.endswith("/entscheiden"):
            return {"status": "freigegeben"}
        return {}


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    return f


def test_menue_nur_fuer_freigeben_im_basis_laden(monkeypatch):
    for rolle, sichtbar in (("freigeben", True), ("lesen", False), ("kalender", False), ("", False)):
        t = ui._AKTIVE_ROLLE.set(rolle)
        try:
            assert ('href="/marketing"' in ui._seitenleiste("")) is sichtbar, rolle
        finally:
            ui._AKTIVE_ROLLE.reset(t)
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/marketing/entwuerfe") is False


def test_schalter_ist_weg():
    assert not hasattr(ui, "_marketing_link")
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert 'class="schalter"' not in ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)
```

Weiter in derselben Datei die Seitentests. Weil die Anmeldewache ohne `UI_SESSION_SECRET` durchlässig ist und die Rolle dann leer bleibt, sperrt `_pfad_erlaubt` die Pult-Seiten für den Testclient. Die Tests laufen deshalb mit **scharfer Anmeldung** wie in `tests/test_laden_anlegen_seite.py` (`scharf`-Fixture, Benutzer `mira` mit Rolle `freigeben`, Login per POST `/login`). Die Test-DB ist dafür nötig; ist sie aus, werden diese Tests mit `pytest.skip("Test-DB aus")` übersprungen, und der Report sagt es.

```python
@pytest.fixture
def angemeldet(pult):
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus - Seitentests brauchen die Anmeldung")
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", "freigeben", ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               headers=HOST, follow_redirects=False)
    assert r.status_code == 303
    yield c
    ui.UI_SESSION_SECRET = vorher


def test_uebersicht(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    assert "VibeMind" in s and "fin2gether" in s and "kommt" in s
    assert "Zur Freigabe" in s and ">7<" in s


def test_entwuerfe_liste(angemeldet):
    s = angemeldet.get("/marketing/entwuerfe", headers=HOST).text
    assert "Early Access" in s and f'href="/marketing/entwurf/{IID}"' in s and "Newsletter" in s


def test_entwurf_zeigt_felder_und_vorschau(angemeldet):
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert 'name="betreff"' in s and "Early Access" in s
    assert f'src="/marketing/entwurf/{IID}/vorschau?fassung=2&amp;format=mail"' in s
    assert "Fassung 2" in s and "Fassung 1" in s
    assert 'value="dunkel"' in s and 'value="hell"' in s


def test_vorschau_wird_durchgereicht_mit_sandbox(angemeldet):
    r = angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    assert r.status_code == 200 and b"Vorschau" in r.content
    assert "sandbox" in r.headers.get("content-security-policy", "")


def test_speichern_legt_fassung_an(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "betreff": "Neu", "vorschautext": "",
                              "abschnitt_titel": ["", "Zwei"], "abschnitt_text": ["Eins", "Text zwei"],
                              "knopf_text": "", "knopf_link": "", "layout": "hell"})
    assert r.status_code == 303
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", f"/inhalte/{IID}/fassungen")
    assert d["felder"]["betreff"] == "Neu" and d["layout"] == "hell"
    assert d["felder"]["abschnitte"] == [{"titel": "", "text": "Eins"}, {"titel": "Zwei", "text": "Text zwei"}]
    assert d["von"] == "mira"


def test_speichern_ohne_csrf_abgewiesen(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST,
                        data={"betreff": "x"})
    assert r.status_code == 403 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_freigeben(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/entscheiden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "urteil": "freigeben", "grund": ""})
    assert r.status_code == 303
    assert pult.aufrufe[-1][2] == {"urteil": "freigeben", "von": "mira", "grund": ""}


def test_marketing_nicht_erreichbar(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "timeout")
    r = angemeldet.get("/marketing/entwuerfe", headers=HOST)
    assert r.status_code == 503 and "Marketing gerade nicht erreichbar" in r.text
    assert 'href="/kontakte"' in r.text                       # Rest von Sales bleibt bedienbar


def test_schluessel_falsch(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_verbunden", "401")
    assert "Marketing nicht verbunden" in angemeldet.get("/marketing", headers=HOST).text


def test_db_ablehnung_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Nur Entwuerfe lassen sich bearbeiten")
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "betreff": "x", "abschnitt_titel": [""],
                              "abschnitt_text": ["y"], "layout": "dunkel"})
    assert r.status_code == 422 and "Nur Entwuerfe lassen sich bearbeiten" in r.text
```

- [ ] **Step 2: Rot sehen** — Host-Runner mit `tests/test_marketing_pult.py` → FAIL (`ModuleNotFoundError: marketing_pult`).

- [ ] **Step 3: Implementieren**

`sales-mcp/marketing_pult.py`:

```python
"""Client zur Marketing-API (Pult-Router, Spec 2026-09-29-marketing-pult-
design.md §3.4). Einzige Stelle, an der sales-ui mit Marketing spricht.
Schluessel nur aus der Umgebung, nie im Log."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

URL = os.environ.get("MARKETING_PULT_URL", "").strip().rstrip("/")
KEY = os.environ.get("MARKETING_PULT_KEY", "").strip()
ZEITLIMIT_S = 8


class PultFehler(Exception):
    def __init__(self, art: str, grund: str = ""):
        super().__init__(f"{art}: {grund}")
        self.art, self.grund = art, grund


def eingerichtet() -> bool:
    return bool(URL and KEY)


def anfrage(methode: str, pfad: str, daten: dict | None = None, roh: bool = False):
    if not eingerichtet():
        raise PultFehler("nicht_verbunden", "MARKETING_PULT_URL/KEY fehlt")
    koerper = json.dumps(daten).encode("utf-8") if daten is not None else None
    req = urllib.request.Request(
        f"{URL}/api/pult{pfad}", data=koerper, method=methode,
        headers={"X-Pult-Key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=ZEITLIMIT_S) as r:
            inhalt = r.read()
            if roh:
                return inhalt, r.headers.get("Content-Type", "application/octet-stream")
            return json.loads(inhalt or b"{}")
    except urllib.error.HTTPError as e:
        try:
            grund = json.loads(e.read() or b"{}").get("detail", "")
        except ValueError:
            grund = ""
        if e.code in (401, 503):
            raise PultFehler("nicht_verbunden", str(e.code))
        if e.code in (404, 422):
            raise PultFehler("abgelehnt", str(grund) or str(e.code))
        raise PultFehler("unbekannt", str(e.code))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PultFehler("nicht_erreichbar", type(e).__name__)
```

`sales-mcp/ui_marketing.py` — Seiten; bekommt das `ui`-Modul übergeben, damit kein Zirkelimport entsteht:

```python
"""Seiten des Marketing-Pults (Spec 2026-09-29-marketing-pult-design.md
§3.1, Stufe 1): Uebersicht, Entwuerfe, Entwurf. Alle Daten kommen ueber
marketing_pult; diese Datei kennt keine Marketing-Tabelle."""
from __future__ import annotations

import urllib.parse

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import marketing_pult

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
STATUS = {"entwurf": "Zur Freigabe", "freigegeben": "Freigegeben", "abgelehnt": "Abgelehnt"}


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schluessel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht moeglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales laeuft normal weiter.")

    def von(request) -> str:
        return str(request.scope.get("benutzer_name") or "betreiber")

    @ui._gesichert_seite
    async def uebersicht(request):
        try:
            d = marketing_pult.anfrage("GET", "/uebersicht?mandant=vibemind")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        mandanten = "".join(
            f'<span class="mandant{"" if m["aktiv"] else " aus"}">{e(m["name"])}'
            f'{"" if m["aktiv"] else " &middot; kommt"}</span>' for m in d["mandanten"])
        z = d["zaehler"]
        karten = "".join(
            f'<a class="kachel" href="/marketing/entwuerfe?status={k}"><b>{int(z.get(k, 0))}</b>'
            f'<span>{e(t)}</span></a>' for k, t in STATUS.items())
        return ui._seite("Marketing", f'<h1>Marketing</h1><div class="mandanten">{mandanten}</div>'
                                      f'<div class="kacheln">{karten}</div>')

    @ui._gesichert_seite
    async def entwuerfe(request):
        art = request.query_params.get("art", "")
        status = request.query_params.get("status", "")
        q = urllib.parse.urlencode({k: v for k, v in (("mandant", "vibemind"), ("art", art), ("status", status)) if v})
        try:
            d = marketing_pult.anfrage("GET", f"/inhalte?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        filter_ = "".join(
            f'<a class="{"aktiv" if art == k else ""}" href="/marketing/entwuerfe?art={k}">{e(t)}</a>'
            for k, t in ARTEN.items())
        zeilen = "".join(
            f'<tr><td><a href="/marketing/entwurf/{e(i["id"])}">{e(i["titel"])}</a></td>'
            f'<td>{e(ARTEN.get(i["art"], i["art"]))}</td><td>{e(STATUS.get(i["status"], i["status"]))}</td>'
            f'<td>{e(i["layout"] or "")}</td><td>{int(i["fassungen"])}</td><td>{e(i["erstellt_am"][:10])}</td></tr>'
            for i in d["inhalte"]) or '<tr><td colspan="6">Keine Entwuerfe.</td></tr>'
        return ui._seite("Entwuerfe", f'<h1>Entwürfe</h1><div class="filter">{filter_}</div>'
                         '<table><tr><th>Titel</th><th>Art</th><th>Status</th><th>Layout</th>'
                         f'<th>Fassungen</th><th>Datum</th></tr>{zeilen}</table>')

    @ui._gesichert_seite
    async def entwurf(request):
        iid = request.path_params["iid"]
        try:
            d = marketing_pult.anfrage("GET", f"/inhalte/{urllib.parse.quote(iid)}")
            lay = marketing_pult.anfrage("GET", "/layouts?mandant=vibemind")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        i, fassungen = d["inhalt"], d["fassungen"]
        wahl = int(request.query_params.get("fassung") or fassungen[0]["fassung"])
        akt = next((f for f in fassungen if f["fassung"] == wahl), fassungen[0])
        fe = akt["felder"]
        abschnitte = "".join(
            f'<fieldset><input name="abschnitt_titel" value="{e(a.get("titel"))}" placeholder="Ueberschrift">'
            f'<textarea name="abschnitt_text" rows="6">{e(a.get("text"))}</textarea></fieldset>'
            for a in fe.get("abschnitte") or [{"titel": "", "text": ""}])
        layouts = "".join(
            f'<option value="{e(l["name"])}"{" selected" if l["name"] == akt["layout"] else ""}>{e(l["name"])}</option>'
            for l in lay["layouts"])
        verlauf = "".join(
            f'<li><a href="?fassung={f["fassung"]}">Fassung {int(f["fassung"])}</a> '
            f'&middot; {"Agent" if f["urheber"] == "agent" else "du"} &middot; {e(f["erstellt_am"][:16])}</li>'
            for f in fassungen)
        offen = i["status"] == "entwurf"
        csrf = f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
        basis = f"/marketing/entwurf/{e(i['id'])}"
        formular = (
            f'<form method="post" action="{basis}/speichern" class="pult-felder">{csrf}'
            f'<label>Betreff <input name="betreff" value="{e(fe.get("betreff"))}"></label>'
            f'<label>Vorschautext <input name="vorschautext" value="{e(fe.get("vorschautext"))}"></label>'
            f'{abschnitte}'
            f'<label>Knopf-Text <input name="knopf_text" value="{e(fe.get("knopf_text"))}"></label>'
            f'<label>Knopf-Link <input name="knopf_link" value="{e(fe.get("knopf_link"))}"></label>'
            f'<label>Layout <select name="layout">{layouts}</select></label>'
            f'<button type="submit">Als neue Fassung speichern</button></form>'
            f'<form method="post" action="{basis}/entscheiden">{csrf}'
            f'<input type="hidden" name="urteil" value="freigeben"><button type="submit">Freigeben (ablegen)</button></form>'
            f'<form method="post" action="{basis}/entscheiden">{csrf}'
            f'<input type="hidden" name="urteil" value="ablehnen"><input name="grund" placeholder="Grund">'
            f'<button type="submit">Ablehnen</button></form>') if offen else (
            f'<p>{e(STATUS.get(i["status"], i["status"]))}.</p>')
        vorschau = "".join(
            f'<a href="#" data-format="{k}">{t}</a>' for k, t in (("mail", "Mail"), ("handy", "Handy"), ("pdf", "PDF")))
        rumpf = (
            f'<h1>{e(i["titel"])}</h1><p class="meta">{e(ARTEN.get(i["art"], i["art"]))} &middot; '
            f'{e(STATUS.get(i["status"], i["status"]))}</p>'
            f'<div class="pult"><div class="pult-links">{formular}<h2>Fassungen</h2><ul>{verlauf}</ul></div>'
            f'<div class="pult-rechts"><div class="vorschau-wahl">{vorschau}</div>'
            f'<iframe class="vorschau" sandbox src="{basis}/vorschau?fassung={int(akt["fassung"])}&amp;format=mail"></iframe>'
            f'</div></div>'
            '<script>document.querySelectorAll(".vorschau-wahl a").forEach(a=>a.onclick=(ev)=>{'
            'ev.preventDefault();const f=document.querySelector("iframe.vorschau");'
            'f.src=f.src.replace(/format=\\w+/,"format="+a.dataset.format);});</script>')
        return ui._seite(i["titel"], rumpf)

    @ui._gesichert_seite
    async def vorschau(request):
        iid = urllib.parse.quote(request.path_params["iid"])
        q = urllib.parse.urlencode({"fassung": request.query_params.get("fassung", "1"),
                                    "format": request.query_params.get("format", "mail")})
        try:
            inhalt, typ = marketing_pult.anfrage("GET", f"/inhalte/{iid}/vorschau?{q}", roh=True)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return Response(inhalt, media_type=typ,
                        headers={"Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"})

    @ui._gesichert_seite
    async def speichern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        titel, texte = form.getlist("abschnitt_titel"), form.getlist("abschnitt_text")
        felder = {
            "betreff": str(form.get("betreff") or "").strip(),
            "vorschautext": str(form.get("vorschautext") or "").strip(),
            "abschnitte": [{"titel": str(t).strip(), "text": str(x).strip()}
                           for t, x in zip(titel, texte) if str(t).strip() or str(x).strip()],
            "knopf_text": str(form.get("knopf_text") or "").strip(),
            "knopf_link": str(form.get("knopf_link") or "").strip(),
        }
        iid = urllib.parse.quote(request.path_params["iid"])
        try:
            r = marketing_pult.anfrage("POST", f"/inhalte/{iid}/fassungen",
                                       {"felder": felder, "layout": str(form.get("layout") or ""), "von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}?fassung={int(r['fassung'])}", status_code=303)

    @ui._gesichert_seite
    async def entscheiden(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        iid = urllib.parse.quote(request.path_params["iid"])
        try:
            marketing_pult.anfrage("POST", f"/inhalte/{iid}/entscheiden",
                                   {"urteil": str(form.get("urteil") or ""), "von": von(request),
                                    "grund": str(form.get("grund") or "").strip()})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/entwurf/{iid}", status_code=303)

    return [
        Route("/marketing", uebersicht),
        Route("/marketing/entwuerfe", entwuerfe),
        Route("/marketing/entwurf/{iid}", entwurf),
        Route("/marketing/entwurf/{iid}/vorschau", vorschau),
        Route("/marketing/entwurf/{iid}/speichern", speichern, methods=["POST"]),
        Route("/marketing/entwurf/{iid}/entscheiden", entscheiden, methods=["POST"]),
    ]
```

Vor dem Festschreiben in `ui.py` prüfen und im Report belegen:
1. Wie `_fehlerseite` heißt und welche Signatur es hat (`ui._fehlerseite(status, titel, text)` wird oben so benutzt); welcher Scope-Schlüssel den Benutzernamen trägt (`benutzer_name` ist eine Annahme — `_ui_akteur(request)` aus `ui.py` nutzen, falls vorhanden, und `von()` darauf umstellen).
2. Die Routenliste in `ui.py` (`Route("/medien", medien)` ~Zeile 6192): dort `*ui_marketing.routen(sys.modules[__name__])` einfügen; `import sys` und `import ui_marketing` oben ergänzen.
3. `_GRUPPEN`: neue Gruppe direkt vor „Admin": `("Marketing", (("/marketing", "Übersicht"), ("/marketing/entwuerfe", "Entwürfe"), ("/marketing/layouts", "Layouts")))`. `/marketing/layouts` entsteht in Task 5; bis dahin endet der Link in 404 — Task 5 folgt direkt.
4. `_ADMIN_BASIS_PFADE` um `"/marketing"` erweitern (Präfixprüfung deckt Unterpfade).
5. CSS für `.pult` (zwei Spalten ≥ 768 px, darunter eine), `.pult-rechts iframe.vorschau` (Breite 100 %, Höhe 80vh, Rahmen `var(--linie)`), `.mandant.aus` (gedämpft), `.filter a.aktiv`, `.vorschau-wahl a` — mit den vorhandenen CSS-Variablen aus `ui.py` (`--linie`, `--gedaempft`, `--aktiv`, `--gut`).
6. Schalter-Rückbau: alles, was Commit `c2ca646`/`ef208cb`/`73b3d86` für den Schalter in `ui.py` eingeführt hat, wieder entfernen; `git diff d3bd1fe -- sales-mcp/ui.py` nach dem Rückbau darf nur noch Pult-Änderungen zeigen.

- [ ] **Step 4: Grün sehen** — Host-Runner: `tests/test_marketing_pult.py` (Seitentests nur mit laufender Test-DB, sonst übersprungen — im Report sagen), `tests/test_seitenleiste.py`, `tests/test_laden_anlegen_seite.py` (Vergleich mit Vorher-Lauf).

- [ ] **Step 5: Commit** (PowerShell, sales-claw)

```powershell
git add -- sales-mcp/marketing_pult.py sales-mcp/ui_marketing.py sales-mcp/ui.py sales-mcp/tests/test_marketing_pult.py docker-compose.yml .env.example
git rm -- sales-mcp/tests/test_marketing_schalter.py
git commit -m "feat(ui): Marketing-Pult - Uebersicht und Entwuerfe mit Vorschau, Fassungen und Freigabe"
```

---

### Task 5: Layout-Galerie und Layout-Editor mit Reglern

Arbeitsort: sales-claw.

**Files:**
- Modify: `sales-mcp/ui_marketing.py` — Seiten `/marketing/layouts`, `/marketing/layout/{name}`, POST `/marketing/layout/{name}/speichern`, POST `/marketing/layout/{name}/standard`, POST `/marketing/layout-vorschau`
- Modify: `sales-mcp/ui.py` — CSS für Galerie und Editor
- Test: `sales-mcp/tests/test_marketing_pult.py` (erweitern)

**Interfaces:**
- Consumes: Task 3 (`/layouts`, `/layouts/vorschau`, `/layouts/{name}/fassungen`, `/layouts/{name}/standard`), Task 4 (`marketing_pult`, `routen`, `fehler`, `von`).
- Produces: Reglerfelder im Formular: `grund`, `text`, `akzent`, `flaeche`, `text_hell`, `text_leise`, `gold`, `handlung_text` (Farbwähler `type="color"`), `schrift` (`system|serif|mono`), `abstand` (`eng|mittel|weit`), `rundung` (0–24, `type="range"`), `kopf_text`, `fuss_text`, `logo` (Datei-Upload PNG/JPEG ≤ 150 KB → data-URI; Häkchen „Logo entfernen").

- [ ] **Step 1: Failing tests** (anhängen; nutzen `angemeldet` und `pult`; die Fälschung `Falsch.anfrage` um diese Pfade erweitern: `/layouts?mandant=vibemind` liefert zwei Layouts mit vollständiger `gestalt`, `inhaltsart` und `standard`; `/layouts/vorschau` mit `roh=True` → `(b"<p>Beispiel</p>", "text/html")`; `/layouts/dunkel/fassungen` → `{"fassung": 3}`)

```python
GESTALT = {"grund": "#0f2422", "text": "#cfe3df", "akzent": "#5eead4", "flaeche": "#1d3b39",
           "text_hell": "#e9fbf6", "text_leise": "#8aa3a0", "gold": "#fbbf24",
           "handlung_text": "#0f2422", "rundung": 8, "schrift": "system", "abstand": "mittel"}


def test_galerie_zeigt_alle_layouts_mit_vorschau(angemeldet):
    s = angemeldet.get("/marketing/layouts", headers=HOST).text
    assert "dunkel" in s and "hell" in s and "Standard" in s
    assert s.count('<iframe class="layout-bild"') == 2
    assert 'href="/marketing/layout/dunkel"' in s


def test_editor_hat_alle_regler(angemeldet):
    s = angemeldet.get("/marketing/layout/dunkel", headers=HOST).text
    for feld in ("grund", "text", "akzent", "flaeche", "text_hell", "text_leise", "gold",
                 "handlung_text", "schrift", "abstand", "rundung", "kopf_text", "fuss_text", "logo"):
        assert f'name="{feld}"' in s, feld
    assert 'value="#0f2422"' in s


def test_speichern_schickt_gestalt(angemeldet, pult):
    daten = {"csrf": ui.CSRF_TOKEN, **{k: v for k, v in GESTALT.items() if k not in ("rundung",)},
             "rundung": "4", "kopf_text": "Hallo", "fuss_text": ""}
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=daten,
                        follow_redirects=False)
    assert r.status_code == 303
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", "/layouts/dunkel/fassungen")
    assert d["gestalt"]["rundung"] == 4 and d["gestalt"]["kopf_text"] == "Hallo"
    assert "fuss_text" not in d["gestalt"]          # leer = nicht gesetzt


def test_live_vorschau(angemeldet, pult):
    r = angemeldet.post("/marketing/layout-vorschau", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, **{k: str(v) for k, v in GESTALT.items()},
                              "format": "handy"})
    assert r.status_code == 200 and b"Beispiel" in r.content
    assert pult.aufrufe[-1][1] == "/layouts/vorschau" and pult.aufrufe[-1][2]["format"] == "handy"


def test_ungueltiger_regler_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "rundung muss eine Zahl von 0 bis 24 sein")
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, **{k: str(v) for k, v in GESTALT.items()},
                              "rundung": "999"})
    assert r.status_code == 422 and "rundung muss eine Zahl" in r.text


def test_zu_grosses_logo_abgewiesen_ohne_api(angemeldet, pult):
    gross = b"\x89PNG\r\n\x1a\n" + b"0" * 160_000
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, **{k: str(v) for k, v in GESTALT.items()}},
                        files={"logo": ("logo.png", gross, "image/png")})
    assert r.status_code == 422 and "150 KB" in r.text
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)


def test_logo_falscher_typ_abgewiesen(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, **{k: str(v) for k, v in GESTALT.items()}},
                        files={"logo": ("logo.png", b"GIF89a....", "image/png")})
    assert r.status_code == 422 and "PNG oder JPEG" in r.text


def test_als_standard(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/hell/standard", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and pult.aufrufe[-1][:2] == ("POST", "/layouts/hell/standard")
```

- [ ] **Step 2: Rot sehen** — Host-Runner `tests/test_marketing_pult.py` → die neuen Tests FAIL (404).

- [ ] **Step 3: Implementieren** — in `ui_marketing.routen(ui)` ergänzen (Hilfsfunktion zum Lesen der Regler, gemeinsam für Speichern und Vorschau):

```python
    FARBEN = ("grund", "text", "akzent", "flaeche", "text_hell", "text_leise", "gold", "handlung_text")
    FARB_NAMEN = {"grund": "Grund", "text": "Text", "akzent": "Akzent", "flaeche": "Flaeche",
                  "text_hell": "Text hell", "text_leise": "Text leise", "gold": "Hervorhebung",
                  "handlung_text": "Knopf-Text"}
    LOGO_MAX = 150 * 1024

    async def regler_lesen(form, bisher: dict | None = None) -> tuple[dict | None, str]:
        import base64
        g = {k: str(form.get(k) or "").strip().lower() for k in FARBEN}
        g["schrift"] = str(form.get("schrift") or "system")
        g["abstand"] = str(form.get("abstand") or "mittel")
        try:
            g["rundung"] = int(str(form.get("rundung") or "8"))
        except ValueError:
            return None, "Rundung muss eine Zahl sein."
        for k in ("kopf_text", "fuss_text"):
            if (w := str(form.get(k) or "").strip()):
                g[k] = w
        datei = form.get("logo")
        if getattr(datei, "filename", ""):
            roh = await datei.read()
            if len(roh) > LOGO_MAX:
                return None, "Das Logo ist groesser als 150 KB."
            if roh.startswith(b"\x89PNG\r\n\x1a\n"):
                typ = "png"
            elif roh.startswith(b"\xff\xd8\xff"):
                typ = "jpeg"
            else:
                return None, "Das Logo muss ein PNG oder JPEG sein."
            g["logo"] = f"data:image/{typ};base64," + base64.b64encode(roh).decode("ascii")
        elif bisher and bisher.get("logo") and not form.get("logo_entfernen"):
            g["logo"] = bisher["logo"]
        return g, ""

    def layout_von(lay: dict, name: str) -> dict | None:
        return next((l for l in lay["layouts"] if l["name"] == name), None)

    @ui._gesichert_seite
    async def layouts(request):
        try:
            lay = marketing_pult.anfrage("GET", "/layouts?mandant=vibemind")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        karten = "".join(
            f'<a class="layout-karte" href="/marketing/layout/{e(l["name"])}">'
            f'<iframe class="layout-bild" sandbox tabindex="-1" '
            f'src="/marketing/layout-bild/{e(l["name"])}"></iframe>'
            f'<b>{e(l["name"])}</b><span>{e(ARTEN.get(l.get("inhaltsart") or "", ""))}'
            f'{" &middot; Standard" if l.get("standard") else ""} &middot; Fassung {int(l.get("fassung") or 1)}</span></a>'
            for l in lay["layouts"])
        return ui._seite("Layouts", f'<h1>Layouts</h1><div class="galerie">{karten}</div>')

    @ui._gesichert_seite
    async def layout_bild(request):
        try:
            lay = marketing_pult.anfrage("GET", "/layouts?mandant=vibemind")
            l = layout_von(lay, request.path_params["name"])
            if not l:
                return ui._fehlerseite(404, "Unbekanntes Layout", "")
            inhalt, typ = marketing_pult.anfrage("POST", "/layouts/vorschau",
                                                 {"gestalt": l["gestalt"], "mandant": "vibemind", "format": "mail"},
                                                 roh=True)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return Response(inhalt, media_type=typ,
                        headers={"Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"})

    @ui._gesichert_seite
    async def layout_editor(request):
        name = request.path_params["name"]
        try:
            l = layout_von(marketing_pult.anfrage("GET", "/layouts?mandant=vibemind"), name)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if not l:
            return ui._fehlerseite(404, "Unbekanntes Layout", "")
        g = l["gestalt"]
        csrf = f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
        farben = "".join(
            f'<label>{FARB_NAMEN[k]} <input type="color" name="{k}" value="{e(g.get(k, "#000000"))}"></label>'
            for k in FARBEN)
        def auswahl(feld, werte, aktuell):
            return (f'<select name="{feld}">' + "".join(
                f'<option value="{w}"{" selected" if w == aktuell else ""}>{t}</option>' for w, t in werte) + "</select>")
        regler = (
            f'{farben}'
            f'<label>Schrift {auswahl("schrift", (("system", "Klar"), ("serif", "Klassisch"), ("mono", "Technisch")), g.get("schrift", "system"))}</label>'
            f'<label>Abstaende {auswahl("abstand", (("eng", "eng"), ("mittel", "mittel"), ("weit", "weit")), g.get("abstand", "mittel"))}</label>'
            f'<label>Rundung <input type="range" min="0" max="24" name="rundung" value="{int(g.get("rundung", 8))}"></label>'
            f'<label>Kopfzeile <input name="kopf_text" maxlength="120" value="{e(g.get("kopf_text", ""))}"></label>'
            f'<label>Fusszeile <input name="fuss_text" maxlength="300" value="{e(g.get("fuss_text", ""))}"></label>'
            f'<label>Logo (PNG/JPEG, max. 150 KB) <input type="file" name="logo" accept="image/png,image/jpeg"></label>'
            + ('<label><input type="checkbox" name="logo_entfernen" value="1"> Logo entfernen</label>' if g.get("logo") else ""))
        rumpf = (
            f'<h1>Layout {e(name)}</h1><p class="meta">{e(l.get("beschreibung") or "")}</p>'
            f'<div class="pult"><div class="pult-links">'
            f'<form id="regler" method="post" enctype="multipart/form-data" action="/marketing/layout/{e(name)}/speichern">{csrf}'
            f'{regler}<button type="submit">Als neue Fassung speichern</button></form>'
            f'<form method="post" action="/marketing/layout/{e(name)}/standard">{csrf}'
            f'<button type="submit">Als Standard fuer diese Art</button></form></div>'
            f'<div class="pult-rechts"><div class="vorschau-wahl"><a href="#" data-format="mail">Mail</a>'
            f'<a href="#" data-format="handy">Handy</a></div>'
            f'<iframe class="vorschau" sandbox src="/marketing/layout-bild/{e(name)}"></iframe>'
            f'<p class="meta" id="regler-fehler"></p></div></div>'
            '<script>(()=>{const f=document.getElementById("regler");const fr=document.querySelector("iframe.vorschau");'
            'const fe=document.getElementById("regler-fehler");let fmt="mail",t;'
            'async function neu(){const d=new FormData(f);d.delete("logo");d.set("format",fmt);'
            'const r=await fetch("/marketing/layout-vorschau",{method:"POST",body:d});'
            'if(r.ok){fr.removeAttribute("src");fr.srcdoc=await r.text();fe.textContent="";}'
            'else{fe.textContent=(await r.text()).replace(/<[^>]+>/g," ").trim().slice(0,200);}}'
            'f.addEventListener("input",()=>{clearTimeout(t);t=setTimeout(neu,300);});'
            'document.querySelectorAll(".vorschau-wahl a").forEach(a=>a.onclick=(ev)=>{ev.preventDefault();fmt=a.dataset.format;neu();});'
            '})();</script>')
        return ui._seite(f"Layout {name}", rumpf)

    @ui._gesichert_seite
    async def layout_vorschau(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        g, grund = await regler_lesen(form)
        if g is None:
            return ui._fehlerseite(422, "Regler ungueltig", e(grund))
        fmt = "handy" if form.get("format") == "handy" else "mail"
        try:
            inhalt, typ = marketing_pult.anfrage("POST", "/layouts/vorschau",
                                                 {"gestalt": g, "mandant": "vibemind", "format": fmt}, roh=True)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return Response(inhalt, media_type=typ)

    @ui._gesichert_seite
    async def layout_speichern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        name = request.path_params["name"]
        try:
            bisher = layout_von(marketing_pult.anfrage("GET", "/layouts?mandant=vibemind"), name) or {}
        except marketing_pult.PultFehler as f:
            return fehler(f)
        g, grund = await regler_lesen(form, bisher.get("gestalt"))
        if g is None:
            return ui._fehlerseite(422, "Regler ungueltig", e(grund))
        try:
            marketing_pult.anfrage("POST", f"/layouts/{urllib.parse.quote(name)}/fassungen",
                                   {"gestalt": g, "von": von(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(f"/marketing/layout/{urllib.parse.quote(name)}", status_code=303)

    @ui._gesichert_seite
    async def layout_standard(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        name = urllib.parse.quote(request.path_params["name"])
        try:
            marketing_pult.anfrage("POST", f"/layouts/{name}/standard", {})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse("/marketing/layouts", status_code=303)
```

und die Routen anhängen:

```python
        Route("/marketing/layouts", layouts),
        Route("/marketing/layout-bild/{name}", layout_bild),
        Route("/marketing/layout/{name}", layout_editor),
        Route("/marketing/layout/{name}/speichern", layout_speichern, methods=["POST"]),
        Route("/marketing/layout/{name}/standard", layout_standard, methods=["POST"]),
        Route("/marketing/layout-vorschau", layout_vorschau, methods=["POST"]),
```

Der Test `test_speichern_schickt_gestalt` erwartet `fuss_text` ohne Schlüssel, wenn leer (oben umgesetzt). Die Vorschau-Antwort von `/marketing/layout-vorschau` wird per `srcdoc` in ein `sandbox`-iframe gesetzt — kein Skript läuft darin. CSS: `.galerie` (Raster 2–3 Spalten, am Handy 1), `.layout-karte` (Rahmen, Titel, Zeile darunter), `iframe.layout-bild` (Höhe 260 px, `pointer-events:none`, verkleinert per `transform: scale(.5)`, Breite 200 %, Ursprung oben links, in einem Container mit `overflow:hidden`).

- [ ] **Step 4: Grün sehen** — Host-Runner `tests/test_marketing_pult.py` (Seitentests mit Test-DB).

- [ ] **Step 5: Commit**

```powershell
git add -- sales-mcp/ui_marketing.py sales-mcp/ui.py sales-mcp/tests/test_marketing_pult.py
git commit -m "feat(ui): Layout-Galerie und Layout-Editor mit Reglern und Live-Vorschau"
```

---

### Task 6: Ausliefern (NUR nach ausdrücklichem Go des Betreibers)

WORKBOARD-Claim `cc-marketing-pult-1` eintragen und committen.

- [ ] **Step 1: Schlüssel erzeugen und verteilen, ohne Ausgabe.** Auf dem PC in eine Scratchpad-Datei: `python -c "import secrets;print('MARKETING_PULT_KEY='+secrets.token_urlsafe(32))"`. Anhängen: an die PC-`.env` (Vibemind_V1), per `scp` an `~/marketing-api.env` (VM, danach `chmod 600`) und an `~/sales-claw/.env` (VM, Haupt-.env), dort zusätzlich `MARKETING_PULT_URL=https://vibemind-offload-1.tail6c7d61.ts.net:8446`. Scratchpad-Datei löschen. `MARKETING_URL` in `~/sales-claw/.env` entfernen.
- [ ] **Step 2: Push** — vibemind-os `master` (Worktree), sales-claw `feat/stufe-1-fundament`; vorher `git log origin/<zweig>..HEAD` prüfen: nur eigene oder freigegebene Commits.
- [ ] **Step 3: Migrationen 050/051/052** sind in Task 1 schon auf der VM-DB; `verify_050`, `verify_051` und `verify_052` einmal erneut grün.
- [ ] **Step 4: VM:** `bash ~/sales-claw/deploy/update.sh` (zieht auch den Marketing-Checkout nach und startet `marketing-api` neu); danach `sudo systemctl restart marketing-api` (neue Umgebungsdatei), `docker compose up -d sales-ui` namentlich. Beweise: `docker exec sales-ui printenv MARKETING_PULT_URL` gesetzt, `docker exec ivan-ui printenv MARKETING_PULT_URL` leer; `curl -s -o /dev/null -w "%{http_code}" https://…:8446/api/pult/inhalte` → 401.
- [ ] **Step 5: PC:** Haupt-Checkout auf den neuen `master` (fremde Änderungen unberührt, Überschneidung vorher prüfen), Marketing-API :5510 neu starten.
- [ ] **Step 6: Echter Durchlauf** (Playwright gegen die Sales-Adresse, angemeldet als Betreiber): Menü „Marketing" sichtbar; Übersicht zeigt die Live-Zahlen: 10 zur Freigabe (4 Newsletter + 6 Posts), 18 abgelehnt, 2 freigegeben (Stand 29.09.2026 — weichen sie ab, vor dem Weiterklicken per `SELECT art, status, count(*) FROM marketing.inhalte GROUP BY 1,2` klären, nicht einfach übernehmen); ein Entwurf: Vorschau Mail/Handy/PDF, Betreff ändern → Fassung 2, Vorschau zeigt den neuen Betreff; Layouts: Galerie mit drei Karten; im Editor Rundung ändern → „Vorschau aktualisieren" → Vorschau ändert sich; als neue Fassung speichern. Denselben Durchlauf zusätzlich im Handy-Viewport (390×844), einschließlich der gesandboxten Layout-Vorschau über „Vorschau aktualisieren" (Rahmen zeigt das Beispiel, kein leerer Rahmen, keine CSP-Meldung in der Konsole). Screenshots in den Report. In Ivans Laden: kein Menüpunkt.
- [ ] **Step 6b: Warnung alter Freigabeweg.** Einen der 3 Vorschläge öffnen, die im alten Weg noch `pending_approval` sind (`SELECT i.id, p.channel FROM marketing.inhalte i JOIN marketing.broadcast_proposals p ON p.id = i.herkunft_proposal WHERE p.status = 'pending_approval'`): über den Aktionen steht der Kasten „Dieser Entwurf liegt noch im alten Freigabeweg ({kanal}) …". NICHT dort ablehnen oder freigeben — nur ansehen. Ein Inhalt ohne Herkunftsvorschlag zeigt keinen Kasten.
- [ ] **Step 7:** WORKBOARD-Eintrag, Claim schließen.

Hinweis: Die Betriebsdoku (`docs/04_BETRIEB_MINIPC.md`, Abschnitt „Marketing-Seite auf der VM": `MARKETING_PULT_URL`/`MARKETING_PULT_KEY` statt Schalter und `MARKETING_URL`) ist schon im Build angepasst (Final-Fix M6) — hier kein eigener Doku-Schritt nötig.

---

## Self-Review (erledigt)

- Spec-Abdeckung Stufe 1 (§6.1): Datenmodell → Task 1; API mit Schlüssel → Task 3; Menüpunkt → Task 4; Entwürfe mit Vorschau/Bearbeiten/Fassungen/Freigabe „ablegen" → Task 2 + 4; Layout-Galerie mit Reglern → Task 5. §3.3 `campaigns`-Spalten, `rueckmeldungen`, `stil_notizen` gehören zu Stufe 2/3 und fehlen hier bewusst. „Agent überarbeiten lassen" ist Stufe 2 (kein Knopf in Stufe 1).
- Abweichung von Spec §3.7 („`:8446` schließen"): gemessen ist `:8446` der einzige Weg aus dem Container zur API; Stufe 5 schließt daher nicht das Tor, sondern die offenen Routen (Schlüssel für alles außer `/api/health`). In Global Constraints festgehalten.
- Namen durchgehend: `pult_fassung_speichern`, `pult_entscheiden`, `pult_gestalt_fehler`, `pult_layout_speichern`, `pult_layout_als_standard`, `pult_render.mail_html/handy_html/pdf_bytes/BEISPIEL_FELDER`, `marketing_pult.anfrage/eingerichtet/PultFehler`, `ui_marketing.routen`, `MARKETING_PULT_URL`, `MARKETING_PULT_KEY`, Header `X-Pult-Key`.
