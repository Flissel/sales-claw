# Editor: mehrere Runden gleichzeitig, breiterer Chat, Markierungen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber gibt dem Newsletter-Agenten sofort die nächste Bitte, auch für denselben Entwurf (bis zu 3 Runden gleichzeitig, 5 in der Warteschlange); die Runden werden beim Fertigwerden auf die neueste Fassung nachgespielt; die Chat-Leiste ist breiter und ziehbar; liegengebliebene Markierungen reisen nicht mehr unbemerkt mit, gescheiterte Bildaufträge erscheinen als Hinweis.

**Architecture:**
- Migration 067 ersetzt „ein laufender Auftrag + eine Vormerkung je Inhalt“ durch Grenzen in den DB-Funktionen (3 `offen`/`in_arbeit`, 5 `wartet`), ein DB-seitiges Nachrücken beim Ende jeder Runde und eine Basis-Fassung beim Speichern (`p_basis`); die Vormerk-Funktionen entfallen.
- Der Chat-Arbeiter am PC bekommt 3 Editor-Plätze (Threads). Verliert das Speichern das Rennen, holt er die neueste Fassung (`GET …/neueste`), spielt die Änderungsliste einzeln mit `agent_werkzeuge.nachspielen` darauf nach (gleiche Prüfungen, neue IDs für `neu:<n>`), prüft und speichert erneut, höchstens 3-mal.
- Der Editor (sales-claw) sendet immer, zeigt jede Runde als eigenen Eintrag mit eigenem Stopp, die Fläche wechselt erst beim Fertigwerden; die rechte Leiste ist ziehbar (440 px, 360 px bis 50 %); Markierungen gehen nur mit, wenn sie seit dem letzten Senden gesetzt oder angeklickt wurden.

**Tech Stack:**
- Python 3.11: FastAPI (Marketing-API), http.server/threading (Chat-Arbeiter), Starlette (sales-ui), pytest.
- PostgreSQL / plpgsql (Supabase auf der VM), Migrationen nur über `migration_probe`.
- React 18 + MUI 5 + zustand 4 (Editor), vitest, `renderToStaticMarkup` für Render-Tests, TypeScript strict.

**Spec:** `docs/superpowers/specs/2026-10-09-editor-parallele-runden-design.md` (sales-claw)

## Repos und Arbeitsweise

- **MOS** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent`, Branch `master`.
  - Dateien liegen unter `spaces/marketing/...`.
  - Vor **jedem** Commit (PowerShell):
    ```
    git -C C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent rev-parse --show-toplevel
    git -C C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent branch --show-current
    ```
    Erwartet: `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent` und `master`. Niemals im Haupt-Checkout `C:/Users/User/Desktop/Vibemind_V1/vibemind-os` committen.
  - Tests (PowerShell, aus dem MOS-Root):
    ```
    cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent
    & C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/<pfad> -q
    ```
  - Migrationen nur über `migration_probe` (eine Transaktion + ROLLBACK):
    ```
    $env:SUPABASE_SSH_HOST = 'offload-vm'; $env:SUPABASE_DB_CONTAINER = 'debian-supabase-db-1'
    & C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe <dateien …>
    ```
- **SC** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`.
  - Vor jedem Commit `git -C <SC> rev-parse --show-toplevel` und `git -C <SC> branch --show-current` (erwartet `feat/stufe-1-fundament`).
  - sales-ui-Tests (PowerShell, Test-Postgres :55432):
    ```
    cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/sales-mcp
    $env:SALES_DB_URL = 'postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA = 'sales_test'
    & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q
    ```
  - Editor (PowerShell): `cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run; npx tsc --noEmit; npm run build`. `npm run build` schreibt `sales-mcp/static/editor` (editor.js, editor.css, MANIFEST.json); das Bundle wird **in jedem Editor-Task mit committet**. Nur `cd editor && npx tsc --noEmit` zählt als Typprüfung (nie `npx --prefix`).
- Git nur über PowerShell. Commits: Conventional Commits auf Deutsch, als letzter Absatz der Trailer, z. B.:
  ```
  git commit -m "feat(marketing): …" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
  ```
  - Nur eigene Dateien einzeln stagen. Nie `git add -A`, nie `.superpowers/` stagen.
  - Nie stash, force oder `--no-verify`.
- Kein Deploy, keine Migration gegen echte DBs, kein Neustart von Diensten. Das macht der Controller in Task 11 nach Freigabe des Betreibers.
- Reihenfolge der Tasks einhalten: Task 2 braucht die Funktionen aus 067 (Task 1), Task 4 braucht `nachspielen` (Task 3) und die Routen aus Task 2, Tasks 8–10 bauen aufeinander auf.

## Global Constraints

- Höchstens **3** Runden `offen`/`in_arbeit` je Inhalt; eine Warteschlange von höchstens **5** Runden `wartet` je Inhalt; die Anlege-Funktion setzt beides unter Sperre der Inhaltszeile durch, darüber hinaus „Bitte warten, bis eine Runde fertig ist“.
- Die bisherige Vormerkung geht in der Warteschlange auf. Eine `wartet`-Runde rückt automatisch nach, sobald ein Platz frei wird; Auslöser ist das Ende einer Runde in der DB-Funktion, ohne Arbeiter-Logik.
- Vergabe an den PC: älteste zuerst, bis zu 3 gleichzeitig. Der Arbeiter holt so lange, wie er freie Plätze hat.
- Stopp bleibt pro Auftrags-ID.
- Editor-Faden = Pool mit **3** Plätzen (3 Threads). Marken-Faden und Wissens-Faden bleiben unverändert.
- Start einer Runde von der neuesten Fassung beim Beginn (`fassung_vorher`).
- Nachspielen beim Fertigwerden, wenn die neueste Fassung neuer ist als `fassung_vorher`: Fassung holen, `aenderungen` einzeln mit `agent_werkzeuge.anwenden` anwenden (gleiche Prüfungen), Übersprungenes melden („Übersprungen, weil eine andere Runde inzwischen … geändert hat: <schritt>“), `neu:<n>` neu auflösen, dann `pruefen` und Speichern mit `fassung_vorher` = nachgespielte Fassung; verlorenes Rennen → erneut nachspielen, **höchstens 3-mal**, danach Rückgabe „Zu viele gleichzeitige Änderungen – bitte noch einmal senden“.
- Bildaufträge: Platzbezüge über dieselbe Zuordnung; fehlt ein Platz, wird der Auftrag mit Hinweis verworfen.
- Rückgängig nur für die Runde, deren Fassung noch die **neueste** ist.
- Bei widersprüchlichen Bitten gewinnt die zuletzt fertige Runde, mit Hinweis.
- Chat-Leiste startet mit **440 px**, ziehbar am linken Rand zwischen **360 px** und **50 %** der Fensterbreite; Breite in `localStorage` unter `vibemind.editor.chatbreite`, jeder Zugriff in try/catch, ohne Speicher gilt die Vorgabe. Eingabefeld wächst bis **8 Zeilen**.
- Knopf heißt immer **„Senden“**; „Vormerken“ entfällt. 4. Runde → im Verlauf „wartet auf freien Platz“; darüber hinaus „Bitte warten, bis eine Runde fertig ist“.
- Jede laufende Runde: eigener Verlaufseintrag mit „Denkt nach …“, Schritten und eigenem Stopp-Knopf.
- Die Fläche wechselt erst beim Fertigwerden einer Runde; Live-Zwischenstände entfallen, sobald mehr als eine Runde läuft; bei genau einer bleibt er wie heute.
- Übersprungene Änderungen als Hinweise am Eintrag der Runde. Solange irgendeine Runde läuft, ist der Entwurf für Handbearbeitung gesperrt.
- Markierungen: nur Auswahl-Chips, die seit dem letzten Senden neu gesetzt oder angeklickt wurden, gehen mit; eine liegengebliebene erscheint ausgegraut mit „aus der letzten Nachricht“ und geht nur mit, wenn man sie anklickt.
- Prompt-Regel: ohne Markierung beziehen sich „das“ / „so nicht“ auf die eigene letzte Runde; ist der Bezug nicht eindeutig, kurz nachfragen und nichts ändern.
- Gescheiterter Bildauftrag (`fehler`) erscheint am Eintrag der beauftragenden Runde: „Bild für <Platz> nicht erzeugt: <Befund>“.
- Fehlerfälle: keine Änderung passt mehr → „fertig, nichts umgesetzt“ mit Liste, keine Fassung; Schönheitsprüfung nach dem Nachspielen schlägt an → Korrekturrunde von der neuesten Fassung; Stopp wirkt nur auf diese Runde, „Behalten“ spielt nach demselben Verfahren nach; Entwurf eingereicht/freigegeben → Runden enden wie heute ohne Fassung, mit Hinweis; PC aus → offene und wartende Runden verfallen nach der bestehenden Frist.
- Nicht Teil: parallele Runden im Marken-Chat, Handbearbeitung während laufender Runden, Live-Zwischenstände mehrerer Runden auf der Fläche, Drei-Wege-Zusammenführen ganzer Fassungen.

## Review Focus

1. **Der Betreiber tippt die nächste Bitte, während eine andere Runde fertig wird (die Seite lädt dann neu):** Der Text im Eingabefeld bleibt erhalten. Test: Task 8 `Entwurf im Eingabefeld überlebt das Neuladen nach einer fertigen Runde`.
2. **Nachspielen einer Liste, deren erste `flaeche_anlegen` übersprungen wird:** `neu:2` zeigt weiter auf die zweite angelegte Fläche (die Nummerierung verrutscht nicht), `neu:1` wird übersprungen statt eine falsche Fläche zu treffen. Test: Task 3 `test_uebersprungene_flaeche_haelt_die_nummerierung`.
3. **Rückgängig an einer nachgespielten Runde:** dreht nur deren Änderungen zurück (Basis = die Fassung, auf die nachgespielt wurde), nicht die Arbeit der anderen Runde. Test: Task 1 `verify_067.sql` Abschnitt 3 (3g/3h).
4. **PC aus, während Runden in der Warteschlange stehen:** Stirbt eine nie abgeholte Runde nach 2 min, enden die wartenden Runden desselben Entwurfs mit derselben Meldung, statt ewig zu warten. Test: Task 1 `verify_067.sql` Abschnitt 5.
5. **Stopp „Behalten“, nachdem eine andere Runde inzwischen gespeichert hat:** Die gültigen Schritte werden auf die neueste Fassung nachgespielt und gespeichert, statt als „inzwischen gespeichert – verworfen“ verloren zu gehen. Test: Task 4 `test_stopp_behalten_spielt_die_gueltigen_schritte_auf_die_neueste_fassung`.

---

### Task 1: Migration 067 — Runden-Grenzen, Warteschlange, Nachrücken, Basis

**Files:**
- Create: `spaces/marketing/db/067_parallele_runden.sql` (MOS)
- Create: `spaces/marketing/db/verify_067.sql`
- Modify: `spaces/marketing/db/verify_060.sql` (Abschnitt 4, Z. 101–103)
- Modify: `spaces/marketing/db/verify_063.sql` (Abschnitt 3, Z. 131–133)

**Interfaces:**
- Produces:
  - Spalte `marketing.chat_auftraege.bereit_am timestamptz` (seit wann eine Runde abholbereit ist; NULL = `erstellt_am` gilt). Indizes `chat_auftraege_ein_laufender` und `chat_auftraege_eine_vormerkung` entfallen.
  - Entfernt: `pult_chat_vormerken(uuid, text, jsonb)`, `pult_chat_vormerkung_loeschen(uuid)`, `pult_chat_vormerkung_starten(uuid)`.
  - `marketing._chat_laufend(p_inhalt uuid) RETURNS int`, `marketing._chat_nachruecken(p_inhalt uuid) RETURNS int`.
  - `marketing.pult_chat_anlegen(uuid, text, text, jsonb) RETURNS uuid` — chat: `offen` bei < 3 laufenden und leerer Warteschlange, sonst `wartet`; mehr als 5 wartende → `'Bitte warten, bis eine Runde fertig ist'`; ein Export läuft allein (`'Der Assistent arbeitet gerade'`).
  - `marketing.pult_chat_senden(p_inhalt uuid, p_nachricht text, p_kontext jsonb) RETURNS jsonb` → `{"id": uuid, "status": "offen"|"wartet"}`.
  - `marketing.pult_chat_fertig(p_auftrag uuid, p_antwort text, p_bloecke jsonb, p_hinweise jsonb, p_ergebnis jsonb, p_basis int DEFAULT NULL) RETURNS jsonb` — speichert auf `coalesce(p_basis, fassung_vorher)`, setzt danach `fassung_vorher` = diese Basis; `p_basis < fassung_vorher` → `'Basis-Fassung % passt nicht zu diesem Auftrag'`; verlorenes Rennen → `'Inzwischen gibt es Fassung % - …'` (aus 053), der Auftrag bleibt `in_arbeit`.
  - `marketing.pult_chat_stopp_abschliessen(p_auftrag uuid, p_bloecke jsonb, p_hinweis text, p_basis int DEFAULT NULL) RETURNS jsonb` (gleiche Basis-Regel).
  - `marketing.pult_chat_stoppen(p_inhalt uuid, p_art text, p_auftrag uuid DEFAULT NULL) RETURNS jsonb` — mit ID: diese Runde (`offen`/`in_arbeit`/`wartet`), sonst `{abgeschlossen:false, veraltet:true}`; ohne ID: die eine laufende, bei mehreren `'Mehrere Runden laufen – bitte die Runde wählen'`.
  - `marketing.pult_chat_zurueck(uuid, text)`, `pult_chat_aufraeumen(uuid)`, `pult_bloecke_speichern(...)` neu (s. SQL); jede Funktion, die eine Runde beendet, ruft `_chat_nachruecken`.
  - `marketing.pult_chat_bild_ids(p_auftrag uuid, p_ids jsonb) RETURNS boolean` (merkt `ergebnis.bild_ids` an einer fertigen Runde), `marketing.pult_chat_bild_hinweise(p_ergebnis jsonb) RETURNS jsonb` (Liste „Bild für <platz> nicht erzeugt: <befund>“ der gescheiterten Bildaufträge).

- [ ] **Step 1: verify_067.sql (der Test) schreiben**

```sql
-- Nachweise fuer 067, nur ueber migration_probe (eine Transaktion + ROLLBACK). In der Probe ist now() konstant.
-- Eigene Probe-Newsletter. Offene, laufende und wartende Runden echter Entwuerfe in DIESER Transaktion beiseite
-- (pult_chat_naechster holt den aeltesten offenen ALLER Inhalte, eine abgelaufene Vergabe wuerde wieder offen);
-- der ROLLBACK stellt sie wieder her.
UPDATE marketing.chat_auftraege SET status = 'fehler' WHERE status IN ('offen', 'in_arbeit', 'wartet');
CREATE TEMP TABLE _p067 ON COMMIT DROP AS SELECT NULL::text AS k, NULL::uuid AS id LIMIT 0;

DO $$ DECLARE v_i uuid; v_j uuid; v_k uuid; d jsonb; BEGIN
  d := '{"root":{"type":"EmailLayout","data":{"childrenIds":["held","t"]}},
         "held":{"type":"Image","data":{"style":{},"props":{"url":"medien:platzhalter-2x1.png","alt":"Team","width":600,"height":300}}},
         "t":{"type":"Text","data":{"style":{},"props":{"text":"eins","markdown":false}}}}'::jsonb;
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES ('vibemind', 'newsletter', 'Probe 067') RETURNING id INTO v_i;
  PERFORM marketing.pult_bloecke_speichern(v_i, 0, 'Probe 067', '', d, 'betreiber', false);
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES ('vibemind', 'newsletter', 'Probe 067 J') RETURNING id INTO v_j;
  PERFORM marketing.pult_bloecke_speichern(v_j, 0, 'Probe 067 J', '', d, 'betreiber', false);
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES ('vibemind', 'newsletter', 'Probe 067 K') RETURNING id INTO v_k;
  PERFORM marketing.pult_bloecke_speichern(v_k, 0, 'Probe 067 K', '', d, 'betreiber', false);
  INSERT INTO _p067 VALUES ('i', v_i), ('j', v_j), ('k', v_k);
END $$;

-- 0) Struktur
DO $$ BEGIN
  ASSERT to_regclass('marketing.chat_auftraege_ein_laufender') IS NULL, '0: Index ein laufender entfernt';
  ASSERT to_regclass('marketing.chat_auftraege_eine_vormerkung') IS NULL, '0: Index Vormerkung entfernt';
  ASSERT to_regprocedure('marketing.pult_chat_vormerken(uuid, text, jsonb)') IS NULL, '0: vormerken entfernt';
  ASSERT to_regprocedure('marketing.pult_chat_vormerkung_loeschen(uuid)') IS NULL, '0: vormerkung_loeschen entfernt';
  ASSERT to_regprocedure('marketing.pult_chat_vormerkung_starten(uuid)') IS NULL, '0: vormerkung_starten entfernt';
  ASSERT to_regprocedure('marketing.pult_chat_senden(uuid, text, jsonb)') IS NOT NULL, '0: senden';
  ASSERT to_regprocedure('marketing._chat_nachruecken(uuid)') IS NOT NULL, '0: nachruecken';
  ASSERT to_regprocedure('marketing._chat_laufend(uuid)') IS NOT NULL, '0: laufend';
  ASSERT to_regprocedure('marketing.pult_chat_bild_ids(uuid, jsonb)') IS NOT NULL, '0: bild_ids';
  ASSERT to_regprocedure('marketing.pult_chat_bild_hinweise(jsonb)') IS NOT NULL, '0: bild_hinweise';
  ASSERT (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'marketing' AND p.proname = 'pult_chat_fertig') = 1, '0: genau eine pult_chat_fertig';
  ASSERT to_regprocedure('marketing.pult_chat_fertig(uuid, text, jsonb, jsonb, jsonb, int)') IS NOT NULL, '0: fertig mit Basis';
  ASSERT (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'marketing' AND p.proname = 'pult_chat_stopp_abschliessen') = 1,
         '0: genau eine pult_chat_stopp_abschliessen';
  ASSERT to_regprocedure('marketing.pult_chat_stopp_abschliessen(uuid, jsonb, text, int)') IS NOT NULL,
         '0: stopp_abschliessen mit Basis';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'marketing'
                  AND table_name = 'chat_auftraege' AND column_name = 'bereit_am'), '0: bereit_am';
END $$;

-- 1) Grenzen: 3 laufen, 5 warten, die 6. wartende wird abgelehnt; Handbearbeitung gesperrt
DO $$ DECLARE v_i uuid := (SELECT id FROM _p067 WHERE k = 'i'); j jsonb; v_fehler text; n int; BEGIN
  FOR n IN 1..8 LOOP
    j := marketing.pult_chat_senden(v_i, 'Runde ' || n, '{}');
    ASSERT j->>'status' = CASE WHEN n <= 3 THEN 'offen' ELSE 'wartet' END, format('1a: Runde %s: %s', n, j);
    -- eindeutige Reihenfolge (in der Probe ist now() konstant), alle juenger als 2 min
    UPDATE marketing.chat_auftraege SET erstellt_am = now() - make_interval(secs => 100 - n) WHERE id = (j->>'id')::uuid;
    INSERT INTO _p067 VALUES ('r' || n, (j->>'id')::uuid);
  END LOOP;
  ASSERT (SELECT fassung_vorher FROM marketing.chat_auftraege WHERE id = (SELECT id FROM _p067 WHERE k = 'r4')) IS NULL,
         '1b: wartende Runde hat noch keine Basis';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_senden(v_i, 'Runde 9', '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Bitte warten, bis eine Runde fertig ist', format('1c: sechste wartende: %s', v_fehler);
  ASSERT marketing._chat_laufend(v_i) = 3, '1d: drei laufen';
  ASSERT (SELECT count(*) FROM marketing.chat_auftraege WHERE inhalt = v_i AND status = 'wartet') = 5, '1e: fuenf warten';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_bloecke_speichern(v_i, 1, 'Probe 067', '',
          (SELECT bloecke FROM marketing.inhalt_fassungen WHERE inhalt = v_i AND fassung = 1), 'betreiber', false);
  EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Der Assistent arbeitet gerade', format('1f: Handbearbeitung gesperrt: %s', v_fehler);
END $$;

-- 2) Vergabe aelteste zuerst; ein frei werdender Platz startet die naechste wartende Runde
DO $$ DECLARE j jsonb; r record; BEGIN
  j := marketing.pult_chat_naechster('5 minutes');
  ASSERT (j->>'id')::uuid = (SELECT id FROM _p067 WHERE k = 'r1') AND (j->>'fassung')::int = 1, format('2a: %s', j);
  j := marketing.pult_chat_naechster('5 minutes');
  ASSERT (j->>'id')::uuid = (SELECT id FROM _p067 WHERE k = 'r2'), format('2b: %s', j);
  j := marketing.pult_chat_naechster('5 minutes');
  ASSERT (j->>'id')::uuid = (SELECT id FROM _p067 WHERE k = 'r3'), format('2c: %s', j);
  ASSERT marketing.pult_chat_naechster('5 minutes') IS NULL, '2d: wartende Runden werden nicht vergeben';
  ASSERT marketing.pult_chat_zurueck((SELECT id FROM _p067 WHERE k = 'r1'), 'probe') = 'fehler', '2e: r1 gibt auf';
  SELECT * INTO r FROM marketing.chat_auftraege WHERE id = (SELECT id FROM _p067 WHERE k = 'r4');
  ASSERT r.status = 'offen' AND r.bereit_am = now() AND r.fassung_vorher = 1 AND r.erstellt_am < now(),
         format('2f: r4 rueckt nach, erstellt_am bleibt: %s', row_to_json(r));
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = (SELECT id FROM _p067 WHERE k = 'r5')) = 'wartet',
         '2g: nur eine rueckt nach';
  j := marketing.pult_chat_naechster('5 minutes');
  ASSERT (j->>'id')::uuid = r.id, format('2h: die nachgerueckte wird vergeben: %s', j);
END $$;

-- 3) Rennen und Basis; Review Focus 3: Rueckgaengig-Basis = die Fassung, auf die nachgespielt wurde
DO $$ DECLARE v_i uuid := (SELECT id FROM _p067 WHERE k = 'i'); a2 uuid := (SELECT id FROM _p067 WHERE k = 'r2');
  a3 uuid := (SELECT id FROM _p067 WHERE k = 'r3'); b jsonb; j jsonb; v_fehler text; r record; BEGIN
  SELECT bloecke INTO b FROM marketing.inhalt_fassungen WHERE inhalt = v_i AND fassung = 1;
  j := marketing.pult_chat_fertig(a2, 'zwei', jsonb_set(b, '{t,data,props,text}', '"zwei"'), '[]', '{}');
  ASSERT (j->>'fassung')::int = 2, format('3a: %s', j);
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = (SELECT id FROM _p067 WHERE k = 'r5')) = 'offen',
         '3b: fertig laesst r5 nachruecken';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_fertig(a3, 'drei', jsonb_set(b, '{held,data,props,alt}', '"Drei"'), '[]', '{}');
  EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler LIKE 'Inzwischen gibt es Fassung 2%', format('3c: Rennen auf alter Basis verloren: %s', v_fehler);
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = a3) = 'in_arbeit', '3d: bleibt in Arbeit';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_fertig(a3, 'drei', b, '[]', '{}', 0); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Basis-Fassung 0 passt nicht zu diesem Auftrag', format('3e: %s', v_fehler);
  SELECT bloecke INTO b FROM marketing.inhalt_fassungen WHERE inhalt = v_i AND fassung = 2;
  j := marketing.pult_chat_fertig(a3, 'drei', jsonb_set(b, '{held,data,props,alt}', '"Drei"'), '[]', '{}', 2);
  ASSERT (j->>'fassung')::int = 3, format('3f: %s', j);
  SELECT * INTO r FROM marketing.chat_auftraege WHERE id = a3;
  ASSERT r.fassung_vorher = 2 AND r.fassung_nachher = 3, format('3g: Basis gemerkt: %s', row_to_json(r));
  ASSERT (SELECT bloecke #>> '{t,data,props,text}' FROM marketing.inhalt_fassungen WHERE inhalt = v_i AND fassung = 3)
         = 'zwei', '3h: die Arbeit von Runde 2 bleibt in Fassung 3';
END $$;

-- 4) Stopp pro Runde
DO $$ DECLARE v_i uuid := (SELECT id FROM _p067 WHERE k = 'i');
  r4 uuid := (SELECT id FROM _p067 WHERE k = 'r4'); r5 uuid := (SELECT id FROM _p067 WHERE k = 'r5');
  r6 uuid := (SELECT id FROM _p067 WHERE k = 'r6'); r7 uuid := (SELECT id FROM _p067 WHERE k = 'r7');
  r8 uuid := (SELECT id FROM _p067 WHERE k = 'r8'); b jsonb; j jsonb; v_fehler text; BEGIN
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = r6) = 'offen', '4a: r6 nach 3f nachgerueckt';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_stoppen(v_i, 'behalten'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Mehrere Runden laufen – bitte die Runde wählen', format('4b: %s', v_fehler);
  j := marketing.pult_chat_stoppen(v_i, 'behalten', r4);
  ASSERT j->>'abgeschlossen' = 'false' AND (j->>'id')::uuid = r4, format('4c: %s', j);
  ASSERT (SELECT stopp FROM marketing.chat_auftraege WHERE id = r4) = 'behalten'
     AND (SELECT stopp FROM marketing.chat_auftraege WHERE id = r5) IS NULL
     AND (SELECT status FROM marketing.chat_auftraege WHERE id = r5) = 'offen', '4d: nur diese Runde';
  j := marketing.pult_chat_stoppen(v_i, 'verwerfen', r7);
  ASSERT j->>'abgeschlossen' = 'true'
     AND (SELECT status || '|' || antwort FROM marketing.chat_auftraege WHERE id = r7)
         = 'fehler|Gestoppt, bevor der Assistent begonnen hat', '4e: wartende Runde endet sofort';
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = r8) = 'wartet', '4f: kein Platz frei, r8 wartet';
  j := marketing.pult_chat_stoppen(v_i, 'verwerfen', r5);
  ASSERT j->>'abgeschlossen' = 'true', format('4g: %s', j);
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = r8) = 'offen', '4h: Platz frei, r8 rueckt nach';
  j := marketing.pult_chat_stoppen(v_i, 'verwerfen', r7);
  ASSERT j->>'veraltet' = 'true', format('4i: erledigte Runde ist veraltet: %s', j);
  SELECT bloecke INTO b FROM marketing.inhalt_fassungen WHERE inhalt = v_i AND fassung = 3;
  j := marketing.pult_chat_stopp_abschliessen(r4, jsonb_set(b, '{t,data,props,text}', '"vier"'), '', 3);
  ASSERT j->>'status' = 'fertig' AND (j->>'fassung')::int = 4, format('4j: %s', j);
  ASSERT (SELECT fassung_vorher FROM marketing.chat_auftraege WHERE id = r4) = 3, '4k: Basis gemerkt';
END $$;

-- 5) Review Focus 4: PC aus - die Warteschlange verfaellt mit der nie abgeholten Runde
DO $$ DECLARE v_j uuid := (SELECT id FROM _p067 WHERE k = 'j'); w uuid; r record; n int; BEGIN
  FOR n IN 1..3 LOOP PERFORM marketing.pult_chat_anlegen(v_j, 'chat', 'J' || n, '{}'); END LOOP;
  w := (marketing.pult_chat_senden(v_j, 'J4', '{}')->>'id')::uuid;
  ASSERT (SELECT status FROM marketing.chat_auftraege WHERE id = w) = 'wartet', '5a';
  UPDATE marketing.chat_auftraege SET erstellt_am = now() - interval '3 minutes' WHERE inhalt = v_j AND status = 'offen';
  PERFORM marketing.pult_chat_aufraeumen(v_j);
  SELECT * INTO r FROM marketing.chat_auftraege WHERE id = w;
  ASSERT r.status = 'fehler' AND r.antwort = 'Der Assistent läuft am PC und ist gerade aus',
         format('5b: wartende Runde verfaellt mit: %s', row_to_json(r));
  ASSERT NOT EXISTS (SELECT 1 FROM marketing.chat_auftraege WHERE inhalt = v_j AND status IN ('offen','in_arbeit','wartet')),
         '5c: nichts lebt weiter';
END $$;

-- 6) Ein Newsletter-Export laeuft allein
DO $$ DECLARE v_k uuid := (SELECT id FROM _p067 WHERE k = 'k'); a uuid; e uuid; v_fehler text; BEGIN
  a := marketing.pult_chat_anlegen(v_k, 'chat', 'K1', '{}');
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_anlegen(v_k, 'export', '', '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Der Assistent arbeitet gerade', format('6a: Export neben Chat: %s', v_fehler);
  PERFORM marketing.pult_chat_zurueck(a, 'probe');
  e := marketing.pult_chat_anlegen(v_k, 'export', '', '{}');
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_senden(v_k, 'K2', '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Der Assistent arbeitet gerade', format('6b: Chat neben Export: %s', v_fehler);
  PERFORM marketing.pult_chat_zurueck(e, 'probe');
END $$;

-- 7) Gescheiterte Bildauftraege einer Runde als Hinweis
DO $$ DECLARE v_k uuid := (SELECT id FROM _p067 WHERE k = 'k'); a uuid; bi uuid; j jsonb; v_fehler text; BEGIN
  a := marketing.pult_chat_anlegen(v_k, 'chat', 'Bild bitte', '{}');
  UPDATE marketing.chat_auftraege SET status = 'in_arbeit', versuche = 1, vergeben_bis = now() + interval '5 minutes',
         fassung_vorher = 1 WHERE id = a;
  PERFORM marketing.pult_chat_fertig(a, 'ok', NULL, '[]', '{}');
  bi := marketing.pult_bild_auftrag(v_k, 'held', false, 'Kerzen', 'agent');
  UPDATE marketing.bild_auftraege SET status = 'fehler', befund = 'Zeitüberschreitung beim Laden' WHERE id = bi;
  ASSERT marketing.pult_chat_bild_ids(a, jsonb_build_array(bi::text)), '7a: gemerkt';
  j := marketing.pult_chat_bild_hinweise((SELECT ergebnis FROM marketing.chat_auftraege WHERE id = a));
  ASSERT j = jsonb_build_array('Bild für held nicht erzeugt: Zeitüberschreitung beim Laden'), format('7b: %s', j);
  ASSERT marketing.pult_chat_bild_hinweise('{}') = '[]'::jsonb, '7c: ohne Bilder leer';
  ASSERT NOT marketing.pult_chat_bild_ids(gen_random_uuid(), '[]'), '7d: unbekannte Runde';
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_bild_ids(a, '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Bild-Ids muessen eine Liste mit hoechstens 10 Eintraegen sein', format('7e: %s', v_fehler);
END $$;

SELECT 'verify_067 ok' AS ergebnis;
```

- [ ] **Step 2: Probe, sie schlägt fehl**

Run (MOS-Root, PowerShell):
```
$env:SUPABASE_SSH_HOST = 'offload-vm'; $env:SUPABASE_DB_CONTAINER = 'debian-supabase-db-1'
& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe spaces/marketing/db/verify_067.sql
```
Expected: FAIL (`0: Index ein laufender entfernt`).

- [ ] **Step 3: 067_parallele_runden.sql schreiben**

```sql
-- RUNBOOK: 067 ersetzt pult_chat_aufraeumen, pult_chat_anlegen (063), pult_chat_fertig (061, jetzt mit p_basis),
-- pult_chat_zurueck (061), pult_chat_stoppen (061), pult_chat_stopp_abschliessen (061, jetzt mit p_basis) und
-- pult_bloecke_speichern (Huelle aus 063); es entfernt pult_chat_vormerken, pult_chat_vormerkung_loeschen und
-- pult_chat_vormerkung_starten. Nach einem Replay von 060, 061 oder 063 IMMER 067 erneut einspielen; danach
-- verify_060, verify_062 .. verify_067 zusammen ueber migration_probe. verify_061 prueft das Vormerk-Modell von
-- 061 und gilt nach 067 nicht mehr (Stopp und Zwischenstand je Runde: verify_067 Abschnitt 4).
-- 067: Editor - mehrere Runden gleichzeitig (sales-claw Spec 2026-10-09-editor-parallele-runden-design.md §1).
-- Idempotent, eine Transaktion.
--   1) je Inhalt hoechstens 3 Runden offen/in_arbeit und 5 wartende (durchgesetzt in pult_chat_anlegen unter
--      Sperre der Inhaltszeile); ein Newsletter-Export laeuft allein
--   2) das Ende einer Runde (fertig, zurueck, Stopp, Aufraeumen) laesst die aelteste wartende nachruecken
--      (_chat_nachruecken; bereit_am = jetzt, Basis = neueste Fassung)
--   3) pult_chat_fertig / pult_chat_stopp_abschliessen speichern auf p_basis (die Fassung, auf die der Arbeiter
--      nachgespielt hat) und merken sie als fassung_vorher (Rueckgaengig nimmt sie)
--   4) Bild-Hinweise: pult_chat_bild_ids merkt die Bildauftraege einer Runde, pult_chat_bild_hinweise nennt die
--      gescheiterten
-- Sperrreihenfolge wie 061: erst marketing.inhalte, dann marketing.chat_auftraege. _chat_nachruecken sperrt den
-- Inhalt mit SKIP LOCKED: haelt ihn ein anderer, ruft der selbst nachruecken auf, sobald er seine Runde beendet.
BEGIN;

-- 1) Spalte und Indizes
ALTER TABLE marketing.chat_auftraege ADD COLUMN IF NOT EXISTS bereit_am timestamptz;
DROP INDEX IF EXISTS marketing.chat_auftraege_ein_laufender;
DROP INDEX IF EXISTS marketing.chat_auftraege_eine_vormerkung;
CREATE INDEX IF NOT EXISTS chat_auftraege_inhalt_status_idx ON marketing.chat_auftraege (inhalt, status);

-- 2) Vormerken geht in der Warteschlange auf
DROP FUNCTION IF EXISTS marketing.pult_chat_vormerken(uuid, text, jsonb);
DROP FUNCTION IF EXISTS marketing.pult_chat_vormerkung_loeschen(uuid);
DROP FUNCTION IF EXISTS marketing.pult_chat_vormerkung_starten(uuid);

-- 3) Zaehler und Nachruecken
CREATE OR REPLACE FUNCTION marketing._chat_laufend(p_inhalt uuid) RETURNS int
LANGUAGE sql STABLE AS $$
  SELECT count(*)::int FROM marketing.chat_auftraege WHERE inhalt = p_inhalt AND status IN ('offen','in_arbeit')
$$;

CREATE OR REPLACE FUNCTION marketing._chat_nachruecken(p_inhalt uuid) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_status text; v_neueste int; v_frei int; v_n int;
BEGIN
  SELECT status INTO v_status FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE SKIP LOCKED;
  IF NOT FOUND OR v_status IS DISTINCT FROM 'entwurf' THEN RETURN 0; END IF;
  v_frei := 3 - marketing._chat_laufend(p_inhalt);
  IF v_frei <= 0 THEN RETURN 0; END IF;
  SELECT max(fassung) INTO v_neueste FROM marketing.inhalt_fassungen WHERE inhalt = p_inhalt;
  UPDATE marketing.chat_auftraege
     SET status = 'offen', bereit_am = now(), fassung_vorher = v_neueste, geaendert_am = now()
   WHERE id IN (SELECT id FROM marketing.chat_auftraege
                 WHERE inhalt = p_inhalt AND status = 'wartet'
                 ORDER BY erstellt_am, id LIMIT v_frei FOR UPDATE);
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;

-- 4) Aufraeumen: nicht abgeholt (2 min seit bereit) => fehler, die wartenden Runden desselben Entwurfs mit
--    (der PC ist aus); Vergabe abgelaufen => einmal neu, dann fehler; danach rueckt nach, wer kann.
CREATE OR REPLACE FUNCTION marketing.pult_chat_aufraeumen(p_inhalt uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_i uuid;
BEGIN
  WITH tot AS (
    UPDATE marketing.chat_auftraege
       SET status = 'fehler', antwort = 'Der Assistent läuft am PC und ist gerade aus',
           vergeben_bis = NULL, geaendert_am = now()
     WHERE status = 'offen' AND coalesce(bereit_am, erstellt_am) < now() - interval '2 minutes'
       AND (p_inhalt IS NULL OR inhalt = p_inhalt)
    RETURNING inhalt)
  UPDATE marketing.chat_auftraege w
     SET status = 'fehler', antwort = 'Der Assistent läuft am PC und ist gerade aus', geaendert_am = now()
    FROM (SELECT DISTINCT inhalt FROM tot) t
   WHERE w.inhalt = t.inhalt AND w.status = 'wartet';
  UPDATE marketing.chat_auftraege
     SET status = CASE WHEN versuche < 2 THEN 'offen' ELSE 'fehler' END,
         antwort = CASE WHEN versuche < 2 THEN antwort ELSE 'Der Assistent ist nicht fertig geworden' END,
         bereit_am = CASE WHEN versuche < 2 THEN now() ELSE bereit_am END,
         zwischenstand = NULL, schritt = '',
         vergeben_bis = NULL, geaendert_am = now()
   WHERE status = 'in_arbeit' AND vergeben_bis < now() AND stopp IS NULL
     AND (p_inhalt IS NULL OR inhalt = p_inhalt);
  FOR v_i IN SELECT DISTINCT inhalt FROM marketing.chat_auftraege
              WHERE status = 'wartet' AND (p_inhalt IS NULL OR inhalt = p_inhalt) LOOP
    PERFORM marketing._chat_nachruecken(v_i);
  END LOOP;
END $$;

-- 5) Anlegen (aus 063): Grenzen statt "ein laufender"; ein Export laeuft allein
CREATE OR REPLACE FUNCTION marketing.pult_chat_anlegen(
    p_inhalt uuid, p_art text, p_nachricht text, p_kontext jsonb) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_art text; v_status text; v_neueste int; v_id uuid; v_wartend int;
BEGIN
  SELECT art, status INTO v_art, v_status FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE;
  IF v_art = 'newsletter' AND v_status = 'eingereicht' AND p_art IS DISTINCT FROM 'export' THEN
    RAISE EXCEPTION 'Liegt zur Freigabe – erst zurückziehen'; END IF;
  IF v_art IS DISTINCT FROM 'newsletter'
     OR NOT (v_status = 'entwurf' OR (p_art = 'export' AND v_status IN ('eingereicht','freigegeben'))) THEN
    RAISE EXCEPTION 'Nur Newsletter-Entwürfe'; END IF;
  PERFORM marketing.pult_chat_aufraeumen(p_inhalt);
  IF p_art IS NULL OR p_art NOT IN ('chat','export') THEN RAISE EXCEPTION 'Art muss chat oder export sein'; END IF;
  IF p_art = 'chat' AND length(btrim(coalesce(p_nachricht, ''))) = 0 THEN
    RAISE EXCEPTION 'Ohne Nachricht kein Auftrag'; END IF;
  IF length(coalesce(p_nachricht, '')) > 2000 THEN
    RAISE EXCEPTION 'Die Nachricht ist zu lang (hoechstens 2000 Zeichen)'; END IF;
  IF p_kontext IS NOT NULL AND jsonb_typeof(p_kontext) <> 'object' THEN
    RAISE EXCEPTION 'Kontext muss ein Objekt sein'; END IF;
  IF EXISTS (SELECT 1 FROM marketing.chat_auftraege
              WHERE inhalt = p_inhalt AND art = 'export' AND status IN ('offen','in_arbeit'))
     OR (p_art = 'export' AND marketing._chat_laufend(p_inhalt) > 0) THEN
    RAISE EXCEPTION 'Der Assistent arbeitet gerade'; END IF;
  SELECT max(fassung) INTO v_neueste FROM marketing.inhalt_fassungen WHERE inhalt = p_inhalt;
  IF p_art = 'chat' THEN
    SELECT count(*) INTO v_wartend FROM marketing.chat_auftraege WHERE inhalt = p_inhalt AND status = 'wartet';
    IF marketing._chat_laufend(p_inhalt) >= 3 OR v_wartend > 0 THEN
      IF v_wartend >= 5 THEN RAISE EXCEPTION 'Bitte warten, bis eine Runde fertig ist'; END IF;
      INSERT INTO marketing.chat_auftraege (inhalt, art, nachricht, kontext, status)
      VALUES (p_inhalt, 'chat', btrim(p_nachricht), coalesce(p_kontext, '{}'::jsonb), 'wartet')
      RETURNING id INTO v_id;
      RETURN v_id;
    END IF;
  END IF;
  INSERT INTO marketing.chat_auftraege (inhalt, art, nachricht, kontext, fassung_vorher)
  VALUES (p_inhalt, p_art, btrim(coalesce(p_nachricht, '')), coalesce(p_kontext, '{}'::jsonb), v_neueste)
  RETURNING id INTO v_id;
  RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_chat_senden(p_inhalt uuid, p_nachricht text, p_kontext jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE v_id uuid;
BEGIN
  v_id := marketing.pult_chat_anlegen(p_inhalt, 'chat', p_nachricht, p_kontext);
  RETURN jsonb_build_object('id', v_id, 'status', (SELECT status FROM marketing.chat_auftraege WHERE id = v_id));
END $$;

-- 6) fertig mit Basis (aus 061; die Vormerk-Freigabe entfaellt, statt dessen nachruecken)
DROP FUNCTION IF EXISTS marketing.pult_chat_fertig(uuid, text, jsonb, jsonb, jsonb);
CREATE OR REPLACE FUNCTION marketing.pult_chat_fertig(
    p_auftrag uuid, p_antwort text, p_bloecke jsonb, p_hinweise jsonb, p_ergebnis jsonb, p_basis int DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a marketing.chat_auftraege; f record; v_n int; v_inhalt uuid; v_basis int;
BEGIN
  SELECT inhalt INTO v_inhalt FROM marketing.chat_auftraege WHERE id = p_auftrag;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unbekannter Auftrag'; END IF;
  PERFORM 1 FROM marketing.inhalte WHERE id = v_inhalt FOR UPDATE;
  SELECT * INTO a FROM marketing.chat_auftraege WHERE id = p_auftrag FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unbekannter Auftrag'; END IF;
  IF a.status <> 'in_arbeit' OR a.vergeben_bis IS NULL OR a.vergeben_bis <= now() THEN
    RAISE EXCEPTION 'Auftrag ist nicht (mehr) in Arbeit'; END IF;
  IF a.stopp IS NOT NULL THEN RAISE EXCEPTION 'Auftrag wurde gestoppt'; END IF;
  IF p_hinweise IS NOT NULL AND jsonb_typeof(p_hinweise) <> 'array' THEN
    RAISE EXCEPTION 'Hinweise muessen ein Array sein'; END IF;
  IF p_ergebnis IS NOT NULL AND jsonb_typeof(p_ergebnis) <> 'object' THEN
    RAISE EXCEPTION 'Ergebnis muss ein Objekt sein'; END IF;
  IF p_basis IS NOT NULL AND p_basis < coalesce(a.fassung_vorher, 0) THEN
    RAISE EXCEPTION 'Basis-Fassung % passt nicht zu diesem Auftrag', p_basis; END IF;
  v_basis := coalesce(p_basis, a.fassung_vorher);
  IF p_bloecke IS NOT NULL THEN
    SELECT felder INTO f FROM marketing.inhalt_fassungen WHERE inhalt = a.inhalt ORDER BY fassung DESC LIMIT 1;
    v_n := marketing.pult_bloecke_speichern(a.inhalt, v_basis, f.felder->>'betreff',
             coalesce(f.felder->>'vorschautext', ''), p_bloecke, 'agent', false);
  END IF;
  UPDATE marketing.chat_auftraege
     SET status = 'fertig', antwort = left(coalesce(p_antwort, ''), 4000),
         hinweise = coalesce(p_hinweise, '[]'::jsonb), ergebnis = coalesce(p_ergebnis, '{}'::jsonb),
         fassung_vorher = CASE WHEN p_bloecke IS NOT NULL THEN v_basis ELSE fassung_vorher END,
         fassung_nachher = v_n, vergeben_bis = NULL,
         zwischenstand = NULL, schritt = '', geaendert_am = now()
   WHERE id = a.id;
  PERFORM marketing._chat_nachruecken(a.inhalt);
  RETURN jsonb_build_object('fassung', v_n);
END $$;

-- 7) zurueck (aus 061) + Sperre des Inhalts zuerst + nachruecken
CREATE OR REPLACE FUNCTION marketing.pult_chat_zurueck(p_auftrag uuid, p_antwort text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE a marketing.chat_auftraege; v_inhalt uuid;
BEGIN
  SELECT inhalt INTO v_inhalt FROM marketing.chat_auftraege WHERE id = p_auftrag;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unbekannter Auftrag'; END IF;
  PERFORM 1 FROM marketing.inhalte WHERE id = v_inhalt FOR UPDATE;
  SELECT * INTO a FROM marketing.chat_auftraege WHERE id = p_auftrag FOR UPDATE;
  IF a.status NOT IN ('offen','in_arbeit') THEN RETURN a.status; END IF;   -- schon erledigt: nichts zu tun
  UPDATE marketing.chat_auftraege
     SET status = 'fehler', antwort = left(coalesce(p_antwort, ''), 4000),
         vergeben_bis = NULL, zwischenstand = NULL, schritt = '', geaendert_am = now()
   WHERE id = a.id;
  PERFORM marketing._chat_nachruecken(a.inhalt);
  RETURN 'fehler';
END $$;

-- 8) Stopp pro Runde (aus 061)
CREATE OR REPLACE FUNCTION marketing.pult_chat_stoppen(
    p_inhalt uuid, p_art text, p_auftrag uuid DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE a marketing.chat_auftraege; v_n int;
BEGIN
  IF p_art IS NULL OR p_art NOT IN ('behalten','verwerfen') THEN
    RAISE EXCEPTION 'Stopp muss behalten oder verwerfen sein'; END IF;
  PERFORM 1 FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE;
  PERFORM marketing.pult_chat_aufraeumen(p_inhalt);
  IF p_auftrag IS NULL THEN
    v_n := marketing._chat_laufend(p_inhalt);
    IF v_n = 0 THEN RAISE EXCEPTION 'Der Assistent arbeitet gerade nicht'; END IF;
    IF v_n > 1 THEN RAISE EXCEPTION 'Mehrere Runden laufen – bitte die Runde wählen'; END IF;
    SELECT * INTO a FROM marketing.chat_auftraege
     WHERE inhalt = p_inhalt AND status IN ('offen','in_arbeit') FOR UPDATE;
  ELSE
    SELECT * INTO a FROM marketing.chat_auftraege
     WHERE id = p_auftrag AND inhalt = p_inhalt AND status IN ('offen','in_arbeit','wartet') FOR UPDATE;
    IF NOT FOUND THEN RETURN jsonb_build_object('abgeschlossen', false, 'veraltet', true); END IF;
  END IF;
  IF a.status IN ('offen','wartet') THEN
    UPDATE marketing.chat_auftraege
       SET status = 'fehler', antwort = 'Gestoppt, bevor der Assistent begonnen hat',
           stopp = p_art, stopp_am = now(), vergeben_bis = NULL,
           zwischenstand = NULL, schritt = '', geaendert_am = now()
     WHERE id = a.id;
    PERFORM marketing._chat_nachruecken(p_inhalt);
    RETURN jsonb_build_object('abgeschlossen', true, 'id', a.id);
  END IF;
  UPDATE marketing.chat_auftraege
     SET stopp = p_art, stopp_am = coalesce(stopp_am, now()), geaendert_am = now()
   WHERE id = a.id;
  RETURN jsonb_build_object('abgeschlossen', false, 'id', a.id);
END $$;

-- 9) Stopp abschliessen mit Basis (aus 061)
DROP FUNCTION IF EXISTS marketing.pult_chat_stopp_abschliessen(uuid, jsonb, text);
CREATE OR REPLACE FUNCTION marketing.pult_chat_stopp_abschliessen(
    p_auftrag uuid, p_bloecke jsonb, p_hinweis text, p_basis int DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE a marketing.chat_auftraege; f record; v_n int; v_hinweise jsonb; v_inhalt uuid; v_basis int;
BEGIN
  SELECT inhalt INTO v_inhalt FROM marketing.chat_auftraege WHERE id = p_auftrag;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unbekannter Auftrag'; END IF;
  PERFORM 1 FROM marketing.inhalte WHERE id = v_inhalt FOR UPDATE;
  SELECT * INTO a FROM marketing.chat_auftraege WHERE id = p_auftrag FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unbekannter Auftrag'; END IF;
  IF a.status <> 'in_arbeit' THEN
    RETURN jsonb_strip_nulls(jsonb_build_object('status', a.status, 'fassung', a.fassung_nachher)); END IF;
  IF a.stopp IS NULL THEN RAISE EXCEPTION 'Auftrag wurde nicht gestoppt'; END IF;
  v_hinweise := CASE WHEN coalesce(btrim(p_hinweis), '') = '' THEN '[]'::jsonb
                     ELSE jsonb_build_array(left(p_hinweis, 500)) END;
  IF p_bloecke IS NULL OR a.stopp = 'verwerfen' THEN
    UPDATE marketing.chat_auftraege
       SET status = 'fehler', antwort = 'Gestoppt – nichts übernommen', hinweise = v_hinweise,
           zwischenstand = NULL, schritt = '', vergeben_bis = NULL, geaendert_am = now()
     WHERE id = a.id;
    PERFORM marketing._chat_nachruecken(a.inhalt);
    RETURN jsonb_build_object('status', 'fehler');
  END IF;
  IF p_basis IS NOT NULL AND p_basis < coalesce(a.fassung_vorher, 0) THEN
    RAISE EXCEPTION 'Basis-Fassung % passt nicht zu diesem Auftrag', p_basis; END IF;
  v_basis := coalesce(p_basis, a.fassung_vorher);
  SELECT felder INTO f FROM marketing.inhalt_fassungen WHERE inhalt = a.inhalt ORDER BY fassung DESC LIMIT 1;
  v_n := marketing.pult_bloecke_speichern(a.inhalt, v_basis, f.felder->>'betreff',
           coalesce(f.felder->>'vorschautext', ''), p_bloecke, 'agent', false);
  UPDATE marketing.chat_auftraege
     SET status = 'fertig',
         antwort = format('Gestoppt nach Schritt %s – bisherige Schritte übernommen', a.schritt_nr),
         hinweise = v_hinweise,
         ergebnis = a.ergebnis || jsonb_build_object('notiz', format('gestoppt nach Schritt %s', a.schritt_nr)),
         fassung_vorher = v_basis, fassung_nachher = v_n, zwischenstand = NULL, schritt = '',
         vergeben_bis = NULL, geaendert_am = now()
   WHERE id = a.id;
  PERFORM marketing._chat_nachruecken(a.inhalt);
  RETURN jsonb_build_object('status', 'fertig', 'fassung', v_n);
END $$;

-- 10) Speichern (Huelle aus 063, woertlich bis auf bereit_am): Betreiber gesperrt, solange eine Runde laeuft
CREATE OR REPLACE FUNCTION marketing.pult_bloecke_speichern(
    p_inhalt uuid, p_basis int, p_betreff text, p_vorschautext text,
    p_bloecke jsonb, p_urheber text, p_als_kopie boolean) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE v_status text;
BEGIN
  SELECT status INTO v_status FROM marketing.inhalte WHERE id = p_inhalt FOR UPDATE;
  IF v_status = 'eingereicht' THEN RAISE EXCEPTION 'Liegt zur Freigabe – erst zurückziehen'; END IF;
  IF p_urheber = 'betreiber' THEN
    IF EXISTS (SELECT 1 FROM marketing.chat_auftraege
                WHERE inhalt = p_inhalt AND status IN ('offen','in_arbeit')
                  AND (vergeben_bis IS NULL OR vergeben_bis > now())
                  AND NOT (status = 'offen' AND coalesce(bereit_am, erstellt_am) < now() - interval '2 minutes')) THEN
      RAISE EXCEPTION 'Der Assistent arbeitet gerade'; END IF;
  END IF;
  RETURN marketing._pult_bloecke_speichern_053(p_inhalt, p_basis, p_betreff, p_vorschautext,
                                               p_bloecke, p_urheber, p_als_kopie);
END $$;

-- 11) Bild-Hinweise einer Runde
CREATE OR REPLACE FUNCTION marketing.pult_chat_bild_ids(p_auftrag uuid, p_ids jsonb) RETURNS boolean
LANGUAGE plpgsql AS $$
BEGIN
  IF p_ids IS NULL OR jsonb_typeof(p_ids) <> 'array' OR jsonb_array_length(p_ids) > 10 THEN
    RAISE EXCEPTION 'Bild-Ids muessen eine Liste mit hoechstens 10 Eintraegen sein'; END IF;
  UPDATE marketing.chat_auftraege SET ergebnis = ergebnis || jsonb_build_object('bild_ids', p_ids)
   WHERE id = p_auftrag AND status = 'fertig';
  RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_chat_bild_hinweise(p_ergebnis jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT coalesce(jsonb_agg('Bild für ' || coalesce(b.platz, 'alle Plätze') || ' nicht erzeugt: '
                            || coalesce(nullif(btrim(b.befund), ''), 'ohne Befund') ORDER BY b.erstellt_am), '[]'::jsonb)
    FROM marketing.bild_auftraege b
   WHERE b.status = 'fehler'
     AND b.id::text IN (SELECT jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(p_ergebnis->'bild_ids') = 'array' THEN p_ergebnis->'bild_ids' ELSE '[]'::jsonb END))
$$;

COMMIT;
```

- [ ] **Step 4: verify_060 und verify_063 an 067 anpassen**

`verify_060.sql`, Abschnitt 4 (Z. 101–103), alt:
```sql
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_anlegen(v_i, 'chat', 'Nochmal', '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler LIKE '%arbeitet gerade%', format('4: zweiter Auftrag nicht abgelehnt: %s', v_fehler);
```
neu:
```sql
  -- 067: bis zu drei Runden je Entwurf - die zweite wird angelegt; fuer die folgenden Abschnitte wieder entfernt
  v_a2 := marketing.pult_chat_anlegen(v_i, 'chat', 'Nochmal', '{}');
  ASSERT v_a2 IS NOT NULL AND v_a2 <> v_a, '4: zweite Runde angelegt (067)';
  DELETE FROM marketing.chat_auftraege WHERE id = v_a2;
```

`verify_063.sql`, Abschnitt 3 (Z. 131–133), alt:
```sql
  v_fehler := NULL;
  BEGIN PERFORM marketing.pult_chat_vormerken(v_i, 'Noch was', '{}'); EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END;
  ASSERT v_fehler = 'Liegt zur Freigabe – erst zurückziehen', format('3e: chat_vormerken: %s', v_fehler);
```
neu:
```sql
  -- 067: Vormerken gibt es nicht mehr (die Warteschlange laeuft ueber pult_chat_anlegen, 3d deckt sie ab)
  ASSERT to_regprocedure('marketing.pult_chat_vormerken(uuid, text, jsonb)') IS NULL, '3e: Vormerken entfernt (067)';
```

- [ ] **Step 5: Probe grün, 067 zweifach angewendet**

Run:
```
& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe spaces/marketing/db/067_parallele_runden.sql spaces/marketing/db/067_parallele_runden.sql spaces/marketing/db/verify_060.sql spaces/marketing/db/verify_062.sql spaces/marketing/db/verify_063.sql spaces/marketing/db/verify_064.sql spaces/marketing/db/verify_065.sql spaces/marketing/db/verify_066.sql spaces/marketing/db/verify_067.sql
```
Expected: `verify_060 ok`, `verify_062 ok` … `verify_067 ok`, `PROBE OK (zurueckgerollt)`.

- [ ] **Step 6: Commit (MOS)**

```
git add spaces/marketing/db/067_parallele_runden.sql spaces/marketing/db/verify_067.sql spaces/marketing/db/verify_060.sql spaces/marketing/db/verify_063.sql
git commit -m "feat(marketing): Migration 067 parallele Runden, Warteschlange und Basis-Fassung" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Marketing-API — Pult- und Arbeiter-Routen für parallele Runden

**Files:**
- Modify: `spaces/marketing/api/chat.py` (MOS): Z. 1–9 Docstring, Z. 46 `GEAENDERT` entfernen, Z. 126–164 (`chat_anlegen`, `chat_stand`), Z. 167–191 (Vormerk-Routen löschen), Z. 494–510 (`_fremde_neu`), Z. 553–584 (`_abschliessen_sql`, `_stopp_abschliessen`), Z. 639–688 (`arbeiter_fertig`), Z. 771–787 (`arbeiter_gestoppt`); neue Route `GET /{aid}/neueste`.
- Test: `spaces/marketing/tests/test_chat_api.py`

**Interfaces:**
- Consumes (Task 1): `pult_chat_senden`, `pult_chat_fertig(…, p_basis)`, `pult_chat_stopp_abschliessen(…, p_basis)`, `pult_chat_bild_ids`, `pult_chat_bild_hinweise`, Spalten `schritt`, `schritt_nr`, `stopp`.
- Produces:
  - `POST /api/pult/inhalte/{iid}/chat` → `{"auftrag": str, "status": "offen"|"wartet"}`; 422 `"Bitte warten, bis eine Runde fertig ist"` aus der DB.
  - `GET /api/pult/inhalte/{iid}/chat` → `{"laeuft": bool, "verlauf": [...], "live": {...}|null, "neueste_fassung": int|null}`; jeder Verlaufseintrag hat zusätzlich `schritt: str`, `schritt_nr: int`, `stopp: "behalten"|"verwerfen"|null`, `bild_hinweise: list[str]`; `wartet`-Runden stehen im Verlauf; `live` nur bei genau einer laufenden Runde (in Arbeit), sonst `null`. `vorgemerkt` entfällt.
  - Die Routen `PUT|DELETE /inhalte/{iid}/chat/vormerkung` und `POST /inhalte/{iid}/chat/vormerkung/starten` entfallen (404).
  - `GET /api/chat/arbeiter/{aid}/neueste` → `{"fassung": int, "bloecke": dict}` (409, wenn der Auftrag nicht mehr in Arbeit ist).
  - `POST /api/chat/arbeiter/{aid}/fertig` nimmt zusätzlich `basis: int|null` und `hinweise: list[str]` (≤ 40, je ≤ 300 Zeichen); verlorenes Rennen → `{"status": "veraltet"}` (der Auftrag bleibt in Arbeit, kein `zurueck`).
  - `POST /api/chat/arbeiter/{aid}/gestoppt` nimmt zusätzlich `basis` und `hinweise`.

- [ ] **Step 1: Tests schreiben bzw. anpassen**

Löschen (das Vormerk-Modell entfällt): `test_vormerken_put_delete_starten`, `test_vormerken_ohne_lauf_startet_sofort`, `test_vormerken_formen_und_schluessel`, `test_stand_enthaelt_live_und_vorgemerkt`, `test_fertig_neuere_fassung_wird_zurueck`.

In `test_kontext_gueltige_auswahl_und_anhaenge` die drei Zeilen ab `f.antworten.append([{"v": {}}])` löschen; in `test_kontext_ungueltig_422_ohne_sql` die letzten zwei Zeilen (`r = c.put(…/chat/vormerkung …` und das folgende `assert`) löschen.

`test_anlegen_reicht_durch` ersetzen:
```python
def test_anlegen_reicht_durch(umg):
    f, _, c = umg
    f.antworten.append([{"s": {"id": AID, "status": "wartet"}}])
    r = c.post(f"/api/pult/inhalte/{IID}/chat", json={"nachricht": "Mach es wärmer", "kontext": {"fenster": "newsletter"}},
               headers=H)
    assert r.status_code == 200, r.text
    assert r.json() == {"auftrag": AID, "status": "wartet"}
    assert "marketing.pult_chat_senden(" in f.sql[0] and "Mach es wärmer" in f.sql[0] and "newsletter" in f.sql[0]


def test_sechste_wartende_runde_422(umg):
    f, _, c = umg
    f.fehler.append(_db_fehler("Bitte warten, bis eine Runde fertig ist"))
    r = c.post(f"/api/pult/inhalte/{IID}/chat", json={"nachricht": "noch eine"}, headers=H)
    assert r.status_code == 422 and r.json()["detail"] == "Bitte warten, bis eine Runde fertig ist"


def test_vormerk_routen_gibt_es_nicht_mehr(umg):
    f, _, c = umg
    basis = f"/api/pult/inhalte/{IID}/chat/vormerkung"
    assert c.put(basis, json={"nachricht": "x"}, headers=H).status_code in (404, 405)
    assert c.delete(basis, headers=H).status_code in (404, 405)
    assert c.post(basis + "/starten", headers=H).status_code in (404, 405)
    assert f.sql == []
```

`test_stand_raeumt_zuerst_auf` ersetzen und Live-Tests ergänzen (`_lauf` = Verlaufszeile):
```python
def _lauf(id_, status, **extra):
    return {"id": id_, "art": "chat", "nachricht": "n", "antwort": "", "status": status, "hinweise": [], "ergebnis": {},
            "fassung_vorher": 2, "fassung_nachher": None, "denken": "", "schritte": [], "schritt": "", "schritt_nr": 0,
            "stopp": None, "bild_hinweise": [], "erstellt_am": id_, "sortiert_am": id_, **extra}


def test_stand_raeumt_zuerst_auf(umg):
    f, _, c = umg
    fertig = _lauf(BID, "fertig", fassung_nachher=2, bild_hinweise=["Bild für held nicht erzeugt: Zeitüberschreitung"])
    f.antworten += [[{"ok": True}], [], [fertig, _lauf(AID, "wartet")], [{"n": 2}]]
    r = c.get(f"/api/pult/inhalte/{IID}/chat", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "marketing.pult_chat_aufraeumen(" in f.sql[0] and "marketing.pult_chat_stopp_faellig()" in f.sql[1]
    assert "chat_auftraege" in f.sql[2] and "LIMIT 30" in f.sql[2] and "wartet" not in f.sql[2]
    assert "marketing.pult_chat_bild_hinweise(ergebnis)" in f.sql[2] and "max(fassung)" in f.sql[3]
    assert d["live"] is None and "vorgemerkt" not in d and d["neueste_fassung"] == 2
    assert d["laeuft"] is True and [z["id"] for z in d["verlauf"]] == [BID, AID]
    assert d["verlauf"][0]["bild_hinweise"] == ["Bild für held nicht erzeugt: Zeitüberschreitung"]
    assert "sortiert_am" not in d["verlauf"][0] and d["verlauf"][1]["status"] == "wartet"


def test_stand_live_nur_bei_genau_einer_laufenden_runde(umg):
    f, _, c = umg
    eine = _lauf(AID, "in_arbeit", schritt="Titel setzen", schritt_nr=3, stopp="verwerfen", denken="d", schritte=[SCHRITT])
    f.antworten += [[{"ok": True}], [], [eine], [{"n": 5}], [{"zwischenstand": _dok()}]]
    d = c.get(f"/api/pult/inhalte/{IID}/chat", headers=H).json()
    assert d["live"] == {"schritt": "Titel setzen", "schritt_nr": 3, "zwischenstand": _dok(), "stopp": "verwerfen",
                         "denken": "d", "schritte": [SCHRITT]}
    assert "zwischenstand" in f.sql[4] and AID in f.sql[4]
    f.sql.clear()
    f.antworten += [[{"ok": True}], [], [_lauf(AID, "in_arbeit"), _lauf(BID, "offen")], [{"n": 5}]]
    d = c.get(f"/api/pult/inhalte/{IID}/chat", headers=H).json()
    assert d["live"] is None and d["laeuft"] is True and len(f.sql) == 4
    assert [z["schritt_nr"] for z in d["verlauf"]] == [0, 0]
```

`test_chat_stand_liefert_denken_und_schritte` ersetzen:
```python
def test_chat_stand_liefert_denken_und_schritte(umg):
    f, _, c = umg
    alt = _lauf(BID, "fertig", fassung_nachher=2, denken=None, schritte=None)
    neu = _lauf(AID, "in_arbeit", denken="Let me think", schritte=[SCHRITT])
    f.antworten += [[{"ok": True}], [], [alt, neu], [{"n": 2}], [{"zwischenstand": None}]]
    j = c.get(f"/api/pult/inhalte/{IID}/chat", headers=H).json()
    assert j["verlauf"][0]["denken"] == "" and j["verlauf"][0]["schritte"] == []
    assert j["verlauf"][1]["denken"] == "Let me think" and j["verlauf"][1]["schritte"] == [SCHRITT]
    assert j["live"]["denken"] == "Let me think" and j["live"]["schritte"][0]["text"] == "Frage an Claude"
    assert "coalesce(denken, '')" in f.sql[2]
```
(`SCHRITT` steht schon in der Datei; die beiden neuen Tests müssen hinter ihrer Definition stehen — hängen Sie `_lauf` und die Stand-Tests deshalb ans Dateiende.)

Arbeiter-Tests (ans Ende von `test_chat_api.py`):
```python
def test_neueste_liefert_die_neueste_fassung(umg):
    f, _, c = umg
    f.antworten += [[JOB], [{"fassung": 5, "bloecke": _dok()}]]
    r = c.get(f"/api/chat/arbeiter/{AID}/neueste", headers=HB)
    assert r.status_code == 200 and r.json() == {"fassung": 5, "bloecke": _dok()}
    assert "ORDER BY fassung DESC LIMIT 1" in f.sql[1] and IID in f.sql[1]
    assert c.get(f"/api/chat/arbeiter/{AID}/neueste").status_code == 401
    f.antworten.append([dict(JOB, gueltig=False)])
    assert c.get(f"/api/chat/arbeiter/{AID}/neueste", headers=HB).status_code == 409


def test_fertig_neuere_fassung_meldet_veraltet_statt_zurueck(umg):
    f, _, c = umg
    f.antworten += [[JOB], [{"f": None}]]
    f.fehler += [None, None, _db_fehler("Inzwischen gibt es Fassung 9 - neu laden oder als Kopie behalten")]
    body = {"antwort": "x", "bloecke": _dok(), "basis": 8, "hinweise": ["Übersprungen: Titel"]}
    r = c.post(f"/api/chat/arbeiter/{AID}/fertig", json=body, headers=HB)
    assert r.status_code == 200 and r.json() == {"status": "veraltet"}
    assert not any("pult_chat_zurueck(" in s for s in f.sql)
    assert f.sql[-1].rstrip().endswith(", 8) AS e") and "Übersprungen: Titel" in f.sql[-1]


@pytest.mark.parametrize("extra", [{"basis": 0}, {"basis": "5"}, {"basis": True}, {"hinweise": "x"},
                                   {"hinweise": ["x" * 301]}, {"hinweise": ["x"] * 41}, {"hinweise": [5]}])
def test_fertig_basis_und_hinweise_formen_422(umg, extra):
    f, _, c = umg
    r = c.post(f"/api/chat/arbeiter/{AID}/fertig", json={"antwort": "x", **extra}, headers=HB)
    assert r.status_code == 422 and f.sql == []


def test_fertig_merkt_die_bildauftraege_an_der_runde(umg):
    f, _, c = umg
    f.antworten += [[JOB], [{"f": None}], [{"e": {"fassung": 7}}], [{"id": BID}], [{"ok": True}]]
    body = {"antwort": "Fertig", "bloecke": _dok(), "bildauftraege": [{"platz": "held", "modus": "neu", "hinweis": "K"}]}
    r = c.post(f"/api/chat/arbeiter/{AID}/fertig", json=body, headers=HB)
    assert r.status_code == 200 and r.json()["bildauftraege"] == [BID]
    assert "marketing.pult_chat_bild_ids(" in f.sql[-1] and BID in f.sql[-1]


def test_fertig_bildauftraege_merken_scheitert_still(umg):
    f, _, c = umg
    f.antworten += [[JOB], [{"f": None}], [{"e": {"fassung": 7}}], [{"id": BID}]]
    f.fehler += [None, None, None, None, RuntimeError("ssh weg")]
    body = {"antwort": "Fertig", "bloecke": _dok(), "bildauftraege": [{"platz": "held", "modus": "neu", "hinweis": "K"}]}
    r = c.post(f"/api/chat/arbeiter/{AID}/fertig", json=body, headers=HB)
    assert r.status_code == 200 and r.json()["fassung"] == 7


def test_gestoppt_mit_basis_und_hinweisen(umg):
    f, _, c = umg
    f.antworten += [[{"stopp": "behalten", "status": "in_arbeit", "zwischenstand": None}], [{"f": None}],
                    [{"e": {"status": "fertig", "fassung": 9}}]]
    r = c.post(GESTOPPT, json={"bloecke": _dok(), "basis": 7, "hinweise": ["Übersprungen: Titel"]}, headers=HB)
    assert r.status_code == 200 and r.json() == {"status": "fertig", "fassung": 9}
    assert f.sql[-1].rstrip().endswith(", 7) AS e") and "Übersprungen: Titel" in f.sql[-1]
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_api.py -q`
Expected: FAIL (u. a. `test_anlegen_reicht_durch`: `pult_chat_senden(` fehlt; `test_neueste_…`: 404).

- [ ] **Step 3: Implementieren**

Docstring Z. 7–9 ersetzen durch:
```python
Live-Lauf (Spec 2026-10-02-newsletter-agent-live-design.md §2/§3, Migration 061): Zwischenstand und Stopp.
Mehrere Runden (Spec 2026-10-09-editor-parallele-runden-design.md, Migration 067): bis zu 3 laufen, 5 warten;
fertig/gestoppt speichern auf `basis` (Nachspielen am PC), ein verlorenes Rennen meldet {"status": "veraltet"}."""
```

Z. 46 (`GEAENDERT = …`) löschen; unter `SPUR_KOERPER_MAX` ergänzen:
```python
HINWEISE_MAX, HINWEIS_MAX = 40, 300
LAUFEND = ("offen", "in_arbeit")
```

`chat_anlegen` und `chat_stand` (Z. 126–164) ersetzen, die drei Vormerk-Routen (Z. 167–191) löschen:
```python
@pult_router.post("/inhalte/{iid}/chat")
def chat_anlegen(iid: str, payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    nachricht, kontext = _nachricht_und_kontext(payload)
    s = _schreiben(lambda:
        f"SELECT marketing.pult_chat_senden({lit(i)}::uuid, {lit(nachricht)}, "
        f"{lit(json.dumps(kontext, ensure_ascii=False))}::jsonb) AS s").get("s") or {}
    return {"auftrag": str(s.get("id")), "status": "wartet" if s.get("status") == "wartet" else "offen"}


@pult_router.get("/inhalte/{iid}/chat")
def chat_stand(iid: str, x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    i = _uuid_oder_404(iid)
    _schreiben(lambda: f"SELECT marketing.pult_chat_aufraeumen({lit(i)}::uuid) IS NULL AS ok")
    _stopps_abschliessen()
    verlauf = _lesen(lambda:
        "SELECT * FROM (SELECT id, art, nachricht, antwort, status, hinweise, ergebnis, fassung_vorher, "
        "fassung_nachher, coalesce(denken, '') AS denken, coalesce(schritte, '[]'::jsonb) AS schritte, "
        "schritt, schritt_nr, stopp, marketing.pult_chat_bild_hinweise(ergebnis) AS bild_hinweise, "
        "erstellt_am::text AS erstellt_am, erstellt_am AS sortiert_am "
        f"FROM marketing.chat_auftraege WHERE inhalt = {lit(i)}::uuid "
        "ORDER BY erstellt_am DESC LIMIT 30) q ORDER BY sortiert_am")
    for z in verlauf:
        z.pop("sortiert_am", None)
        z["denken"], z["schritte"] = z.get("denken") or "", z.get("schritte") or []
        z["schritt"], z["schritt_nr"] = z.get("schritt") or "", int(z.get("schritt_nr") or 0)
        z["bild_hinweise"] = z.get("bild_hinweise") or []
    neueste = (_lesen_einer(lambda:
        f"SELECT max(fassung) AS n FROM marketing.inhalt_fassungen WHERE inhalt = {lit(i)}::uuid") or {}).get("n")
    # Live-Zwischenstand nur bei genau einer laufenden Runde (Spec §2); bei mehreren wechselt die Flaeche erst
    # beim Fertigwerden.
    laufend = [z for z in verlauf if z.get("status") in LAUFEND]
    live = None
    if len(laufend) == 1 and laufend[0].get("status") == "in_arbeit" and laufend[0].get("art") == "chat":
        z = laufend[0]
        zs = _lesen_einer(lambda:
            f"SELECT zwischenstand FROM marketing.chat_auftraege WHERE id = {lit(str(z['id']))}::uuid") or {}
        live = {"schritt": z["schritt"], "schritt_nr": z["schritt_nr"], "zwischenstand": zs.get("zwischenstand"),
                "stopp": z.get("stopp"), "denken": z["denken"], "schritte": z["schritte"]}
    return {"laeuft": any(z.get("status") in LAUFEND + ("wartet",) for z in verlauf), "verlauf": verlauf,
            "live": live, "neueste_fassung": neueste}
```

`_fremde_neu` (Z. 494–510): Signatur `def _fremde_neu(a: str, job: dict, bloecke: dict, basis: int | None = None) -> str | None:` und die Basis-Abfrage ersetzen durch:
```python
    bedingung = f"f.fassung = {int(basis)}" if basis is not None else "f.fassung = a.fassung_vorher"
    alt_dok = _lesen_einer(lambda:
        "SELECT f.bloecke FROM marketing.chat_auftraege a JOIN marketing.inhalt_fassungen f "
        f"ON f.inhalt = a.inhalt AND {bedingung} WHERE a.id = {lit(a)}::uuid")
    alt = set(_MEDIEN_VERWEIS.findall(json.dumps((alt_dok or {}).get("bloecke"), ensure_ascii=False)))
```

Neue Formprüfung (vor `_bildauftraege_formen`):
```python
def _basis_und_hinweise(payload: dict) -> tuple[int | None, list[str]]:
    """basis (Fassung, auf die der Arbeiter nachgespielt hat) und seine Hinweise (Uebersprungenes)."""
    basis, hinweise = payload.get("basis"), payload.get("hinweise", [])
    if basis is not None and (isinstance(basis, bool) or not isinstance(basis, int) or not 1 <= basis < 2 ** 31):
        raise HTTPException(422, "basis muss eine Fassungsnummer sein")
    if (not isinstance(hinweise, list) or len(hinweise) > HINWEISE_MAX
            or not all(isinstance(h, str) and len(h) <= HINWEIS_MAX for h in hinweise)):
        raise HTTPException(422, f"hinweise muss eine Liste mit hoechstens {HINWEISE_MAX} Texten sein")
    return basis, hinweise
```

`_abschliessen_sql` und `_stopp_abschliessen` (Z. 553–584) ersetzen:
```python
def _abschliessen_sql(a: str, bloecke: dict | None, hinweis: str, basis: int | None = None) -> dict:
    zeile = _schreiben(lambda:
        f"SELECT marketing.pult_chat_stopp_abschliessen({lit(a)}::uuid, "
        + (f"{lit(json.dumps(bloecke, ensure_ascii=False))}::jsonb" if bloecke is not None else "NULL")
        + f", {lit(hinweis)}, {int(basis) if basis is not None else 'NULL'}) AS e")
    return zeile.get("e") or {}


def _stopp_abschliessen(a: str, job: dict, bloecke, basis: int | None = None, extra: list[str] | None = None) -> dict:
    """Schliesst einen gestoppten Auftrag ab. Nur bei 'behalten' (und noch in_arbeit) wird gerechnet und geprueft;
    ungueltig => NULL mit Hinweis. basis/extra: der Arbeiter hat auf eine neuere Fassung nachgespielt. Hat jemand
    inzwischen gespeichert oder lehnt die DB das Speichern ab, zweiter Versuch mit NULL - der Auftrag darf nie
    in_arbeit haengen bleiben."""
    hinweis = ""
    if job.get("status") != "in_arbeit" or job.get("stopp") != "behalten" or not isinstance(bloecke, dict):
        bloecke = None
    else:
        try:
            bloecke, hinweise, fehler = _rechnen_und_pruefen(bloecke)
        except HTTPException:
            raise                      # z.B. 503: DB weg, spaeter erneut versuchen
        except Exception as e:         # noqa: BLE001 - kaputter Zwischenstand darf nie haengen bleiben
            bloecke, hinweise, fehler = None, [], f"{type(e).__name__}: {e}"
        hinweis = STOPP_UNGUELTIG + fehler if fehler else "; ".join(hinweise)
    if extra:
        hinweis = "; ".join([*extra, hinweis] if hinweis else extra)
    try:
        return _abschliessen_sql(a, bloecke, hinweis, basis if bloecke is not None else None)
    except HTTPException as e:
        if bloecke is None or e.status_code != 422:
            raise                      # 503 bleibt wiederholbar
        if str(e.detail).startswith("Inzwischen gibt es Fassung"):
            return _abschliessen_sql(a, None, STOPP_GESPEICHERT)
        return _abschliessen_sql(a, None, STOPP_UNGUELTIG + str(e.detail))
```

`arbeiter_fertig` (Z. 639–688) ersetzen:
```python
@arbeiter_router.post("/{aid}/fertig")
def arbeiter_fertig(aid: str, payload: dict = Body(...), x_bild_key: str | None = Header(None)):
    _bild_schluessel(x_bild_key)
    a = _auftrag_id(aid)
    antwort, bloecke = payload.get("antwort"), payload.get("bloecke")
    export_vorschlag, notiz = payload.get("export_vorschlag"), payload.get("notiz", "")
    if not isinstance(antwort, str):
        raise HTTPException(422, "antwort muss Text sein")
    if bloecke is not None and not isinstance(bloecke, dict):
        raise HTTPException(422, "bloecke muss ein Objekt oder null sein")
    if export_vorschlag is not None and not isinstance(export_vorschlag, dict):
        raise HTTPException(422, "export_vorschlag muss ein Objekt oder null sein")
    if not isinstance(notiz, str) or len(notiz) > 500:
        raise HTTPException(422, "notiz muss Text mit hoechstens 500 Zeichen sein")
    basis, extra = _basis_und_hinweise(payload)
    auftraege = _bildauftraege_formen(payload.get("bildauftraege", []))
    job = _in_arbeit(a)
    hinweise: list[str] = list(extra)
    if bloecke is not None:
        f = _fremde_neu(a, job, bloecke, basis)
        if f:
            return _zurueck(a, NICHT_UMGESETZT + f)
        bloecke, h, fehler = _rechnen_und_pruefen(bloecke)
        if fehler:
            return _zurueck(a, NICHT_UMGESETZT + fehler)
        hinweise += h
    hinweise += [f"{b.get('platz', 'Bild')}: {b['grund']}" for b in auftraege if "grund" in b]
    ergebnis = {"export_vorschlag": export_vorschlag, "notiz": notiz, "bildauftraege": auftraege}
    try:
        zeile = _schreiben(lambda:
            f"SELECT marketing.pult_chat_fertig({lit(a)}::uuid, {lit(antwort[:4000])}, "
            + (f"{lit(json.dumps(bloecke, ensure_ascii=False))}::jsonb" if bloecke is not None else "NULL")
            + f", {lit(json.dumps(hinweise, ensure_ascii=False))}::jsonb, "
            f"{lit(json.dumps(ergebnis, ensure_ascii=False))}::jsonb, "
            f"{int(basis) if basis is not None else 'NULL'}) AS e")
    except HTTPException as e:
        if e.status_code == 422 and str(e.detail).startswith("Inzwischen gibt es Fassung"):
            return {"status": "veraltet"}      # der Arbeiter spielt auf die neueste Fassung nach
        raise
    fassung = (zeile.get("e") or {}).get("fassung")
    ids: list[str | None] = []
    for b in auftraege:
        if "grund" in b:
            ids.append(None)
            continue
        try:
            ids.append(_anlegen(str(job["inhalt"]), {"platz": b["platz"], "hinweis": b["hinweis"],
                                                     "modus": b["modus"]}, "agent")["auftrag"])
        except HTTPException as e:
            ids.append(None)
            hinweise.append(f"{b['platz']}: Bild nicht beauftragt – {e.detail}")
    gemerkt = [i for i in ids if i]
    if gemerkt:
        try:   # nur fuer den Hinweis "Bild nicht erzeugt" an der Runde; darf fertig nie kippen
            _schreiben(lambda: f"SELECT marketing.pult_chat_bild_ids({lit(a)}::uuid, "
                               f"{lit(json.dumps(gemerkt))}::jsonb) AS ok")
        except HTTPException as e:
            log.warning("Bildauftraege nicht an der Runde vermerkt: %s", e.detail)
    return {"fassung": fassung, "hinweise": hinweise, "bildauftraege": ids}
```

Neue Route (hinter `arbeiter_weiter`):
```python
@arbeiter_router.get("/{aid}/neueste")
def arbeiter_neueste(aid: str, x_bild_key: str | None = Header(None)):
    """Neueste Fassung des Entwurfs fuer das Nachspielen (Spec 2026-10-09 §1); nur fuer einen Auftrag in Arbeit."""
    _bild_schluessel(x_bild_key)
    a = _auftrag_id(aid)
    job = _in_arbeit(a)
    z = _lesen_einer(lambda:
        "SELECT fassung, bloecke FROM marketing.inhalt_fassungen "
        f"WHERE inhalt = {lit(str(job['inhalt']))}::uuid ORDER BY fassung DESC LIMIT 1")
    if not z or not isinstance(z.get("bloecke"), dict):
        raise HTTPException(409, "Der Newsletter hat keine Blöcke")
    return {"fassung": int(z["fassung"]), "bloecke": z["bloecke"]}
```

`arbeiter_gestoppt` (Z. 771–787): nach der `bloecke`-Prüfung `basis, extra = _basis_und_hinweise(payload)` ergänzen und in `abschliessen()` aufrufen:
```python
        return _stopp_abschliessen(a, job, bloecke if bloecke is not None else job.get("zwischenstand"), basis, extra)
```

- [ ] **Step 4: Tests grün**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_api.py spaces/marketing/tests/test_freigabe_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/api/chat.py spaces/marketing/tests/test_chat_api.py
git commit -m "feat(marketing): Chat-API fuer parallele Runden (Senden, Stand, neueste Fassung, Basis)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `agent_werkzeuge.nachspielen` — Änderungsliste auf eine neuere Fassung

**Files:**
- Modify: `spaces/marketing/claw/agent_werkzeuge.py` (MOS, ans Ende)
- Modify: `spaces/marketing/workers/chat_worker.py:263-279` (`_neu_aufloesen` wird ein Verweis)
- Test: `spaces/marketing/claw/tests/test_agent_werkzeuge.py`

**Interfaces:**
- Produces:
  - `agent_werkzeuge.UEBERSPRUNGEN: str = "Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: "`
  - `agent_werkzeuge.neu_aufloesen(wert, neu_ids: list) -> Any` (aus dem Arbeiter verschoben, gleiches Verhalten).
  - `@dataclass Nachspiel(bloecke: dict, geaendert: bool, angewandt: list[dict], uebersprungen: list[str], bildauftraege: list[dict], export_vorschlag: dict | None, notiz: str)`
  - `agent_werkzeuge.nachspielen(dok: dict, aenderungen: list, medien: set[str]) -> Nachspiel` — wirft `WerkzeugFehler` nur bei kaputter Liste/kaputtem Dokument; jede einzelne ungültige Änderung wird übersprungen (Hinweis `UEBERSPRUNGEN + <schritt>`), Bildaufträge und Export nur mit Plätzen/Flächen, die es am Ende gibt.

- [ ] **Step 1: Tests schreiben**

```python
# ---- Nachspielen (Spec 2026-10-09-editor-parallele-runden §1) ----------------------------------
def _ohne(dok, bid):
    d = copy.deepcopy(dok)
    d.pop(bid)
    d["root"]["data"]["childrenIds"] = [k for k in d["root"]["data"]["childrenIds"] if k != bid]
    return d


def test_nachspielen_ueberspringt_geloeschten_block_mit_hinweis():
    liste = [{"werkzeug": "block_aendern", "id": "kopf", "props": {"text": "Neu"}, "schritt": "Titel ändern"},
             {"werkzeug": "farben_setzen", "backdropColor": "#000000", "schritt": "Grund dunkel"}]
    n = aw.nachspielen(_ohne(DOK, "kopf"), liste, MEDIEN)
    assert n.uebersprungen == [aw.UEBERSPRUNGEN + "Titel ändern"]
    assert n.geaendert and n.bloecke["root"]["data"]["backdropColor"] == "#000000" and "kopf" not in n.bloecke
    assert n.angewandt == [liste[1]]


def test_nachspielen_neue_flaeche_bekommt_neue_id_und_neu_verweis_folgt():
    liste = [fl(), {"werkzeug": "hintergrund_setzen", "flaeche": "neu:1", "farbe": "#112233"}]
    n = aw.nachspielen(DOK, liste, MEDIEN)
    fid = [k for k, b in n.bloecke.items() if "gestaltung" in b.get("data", {}).get("props", {})][0]
    assert fid.startswith("agent-") and n.bloecke[fid]["data"]["props"]["gestaltung"]["hintergrund"] == "#112233"
    assert "neu:1" not in str(n.bloecke) and n.uebersprungen == []


def test_uebersprungene_flaeche_haelt_die_nummerierung():
    """Review Focus 2: die erste flaeche_anlegen scheitert - neu:2 trifft trotzdem die zweite, neu:1 wird uebersprungen."""
    liste = [{**fl(nach="weg"), "schritt": "Fläche eins"}, {**fl(), "schritt": "Fläche zwei"},
             {"werkzeug": "hintergrund_setzen", "flaeche": "neu:1", "farbe": "#111111", "schritt": "Eins dunkel"},
             {"werkzeug": "hintergrund_setzen", "flaeche": "neu:2", "farbe": "#222222", "schritt": "Zwei dunkel"}]
    n = aw.nachspielen(DOK, liste, MEDIEN)
    flaechen = [k for k, b in n.bloecke.items() if "gestaltung" in b.get("data", {}).get("props", {})]
    assert len(flaechen) == 1
    assert n.bloecke[flaechen[0]]["data"]["props"]["gestaltung"]["hintergrund"] == "#222222"
    assert n.uebersprungen == [aw.UEBERSPRUNGEN + "Fläche eins", aw.UEBERSPRUNGEN + "Eins dunkel"]


def test_nachspielen_bildauftrag_ohne_platz_wird_verworfen():
    liste = [{"werkzeug": "bild_erzeugen", "platz": "held", "hinweis": "Kerzen", "schritt": "Bild beauftragen"},
             {"werkzeug": "farben_setzen", "textColor": "#000000"}]
    assert aw.nachspielen(DOK, liste, MEDIEN).bildauftraege == [{"platz": "held", "modus": "neu", "hinweis": "Kerzen"}]
    n = aw.nachspielen(_ohne(DOK, "held"), liste, MEDIEN)
    assert n.bildauftraege == [] and n.uebersprungen == [aw.UEBERSPRUNGEN + "Bild beauftragen"]


def test_nachspielen_ohne_konflikt_wie_anwenden():
    liste = [{"werkzeug": "block_aendern", "id": "text1", "props": {"text": "Hi"}},
             {"werkzeug": "entwurf_speichern", "notiz": "kurz"},
             {"werkzeug": "export_vorschlagen", "newsletter": True, "flaechen": []}]
    n, e = aw.nachspielen(DOK, liste, MEDIEN), lauf(liste)
    assert n.bloecke == e.bloecke and n.notiz == e.notiz == "kurz" and n.export_vorschlag == e.export_vorschlag
    assert n.uebersprungen == [] and n.angewandt == liste and DOK["text1"]["data"]["props"]["text"] == "Hallo"


def test_nachspielen_nichts_passt_mehr():
    liste = [{"werkzeug": "block_loeschen", "id": "kopf", "schritt": "Kopf weg"}]
    n = aw.nachspielen(_ohne(DOK, "kopf"), liste, MEDIEN)
    assert not n.geaendert and n.angewandt == [] and n.uebersprungen == [aw.UEBERSPRUNGEN + "Kopf weg"]


def test_nachspielen_kaputte_liste_wirft():
    with pytest.raises(WerkzeugFehler):
        aw.nachspielen(DOK, "keine Liste", MEDIEN)
    with pytest.raises(WerkzeugFehler):
        aw.nachspielen({"root": {}}, [], MEDIEN)
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/claw/tests/test_agent_werkzeuge.py -q -k "nachspielen or nummerierung"`
Expected: FAIL (`module … has no attribute 'nachspielen'`).

- [ ] **Step 3: Implementieren**

Ans Ende von `agent_werkzeuge.py`:
```python
# ---- Nachspielen auf eine neuere Fassung (Spec 2026-10-09-editor-parallele-runden §1) ------------------------
UEBERSPRUNGEN = "Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: "
NEU_WERKZEUGE = ("flaeche_anlegen",)


def neu_aufloesen(wert, neu_ids: list):
    """Ersetzt neu:<n> durch die id, die die n-te flaeche_anlegen bekommen hat. Ohne bekannte id bleibt der Verweis
    stehen, dann lehnt anwenden die Aenderung ab."""
    if isinstance(wert, str):
        m = NEU.match(wert)
        if m and int(m.group(1)) <= len(neu_ids) and neu_ids[int(m.group(1)) - 1]:
            return neu_ids[int(m.group(1)) - 1]
        return wert
    if isinstance(wert, dict):
        return {k: v if k == "schritt" else neu_aufloesen(v, neu_ids) for k, v in wert.items()}
    if isinstance(wert, list):
        return [neu_aufloesen(v, neu_ids) for v in wert]
    return wert


@dataclass
class Nachspiel:
    bloecke: dict
    geaendert: bool
    angewandt: list[dict]
    uebersprungen: list[str]
    bildauftraege: list[dict] = field(default_factory=list)
    export_vorschlag: dict | None = None
    notiz: str = ""


def nachspielen(dok: dict, aenderungen: list, medien: set[str]) -> Nachspiel:
    """Spielt eine Aenderungsliste einzeln auf dok nach. Jede Aenderung laeuft durch anwenden (dieselben Pruefungen);
    eine ungueltige wird uebersprungen und gemeldet, der Stand bleibt. neu:<n> zeigt auf die Flaeche, die die n-te
    flaeche_anlegen HIER bekommen hat (neue ids; eine uebersprungene zaehlt mit). Bildauftraege und der
    Export-Vorschlag gelten nur, wenn ihr Platz bzw. ihre Flaechen am Ende noch da sind."""
    if not isinstance(aenderungen, list):
        raise WerkzeugFehler("Die Änderungen müssen eine Liste sein")
    if len(aenderungen) > MAX_AENDERUNGEN:
        raise WerkzeugFehler(f"Höchstens {MAX_AENDERUNGEN} Änderungen je Antwort")
    if not isinstance(dok, dict) or not isinstance((dok.get("root") or {}).get("data", {}).get("childrenIds"), list):
        raise WerkzeugFehler("Newsletter hat kein gültiges root")
    stand, neu_ids = dok, []
    angewandt: list[dict] = []
    weg: list[str] = []
    bild: list[tuple[str, dict]] = []
    export, notiz = None, ""
    for a in aenderungen:
        werkzeug = a.get("werkzeug") if isinstance(a, dict) else None
        schritt = str((a.get("schritt") if isinstance(a, dict) else None) or werkzeug or "Änderung")[:MAX_SCHRITT]
        vorher = set(stand)
        try:
            erg = anwenden(stand, [neu_aufloesen(a, neu_ids)], medien)
        except WerkzeugFehler:
            weg.append(UEBERSPRUNGEN + schritt)
            if werkzeug in NEU_WERKZEUGE:
                neu_ids.append(None)
            continue
        if werkzeug in NEU_WERKZEUGE:
            neue = [k for k in erg.bloecke if k not in vorher]
            neu_ids.append(neue[0] if len(neue) == 1 else None)
        stand = erg.bloecke
        angewandt.append(a)
        bild += [(schritt, b) for b in erg.bildauftraege]
        if erg.export_vorschlag is not None:
            export = erg.export_vorschlag
        if erg.notiz:
            notiz = erg.notiz
    plaetze = {p.id for p in bildplaetze.finde(stand)}
    bildauftraege = []
    for schritt, b in bild:                 # spaetere Aenderungen derselben Liste koennen den Platz geloescht haben
        if b["platz"] in plaetze:
            bildauftraege.append(b)
        else:
            weg.append(UEBERSPRUNGEN + schritt)
    if export is not None:
        pruefer = _Lauf(stand, medien)
        export = {**export, "flaechen": [f for f in export["flaechen"] if pruefer.ist_flaeche(f)]}
    return Nachspiel(bloecke=stand, geaendert=stand != dok, angewandt=angewandt, uebersprungen=weg,
                     bildauftraege=bildauftraege, export_vorschlag=export, notiz=notiz)
```

In `chat_worker.py` Z. 263–279 (`NEU_WERKZEUGE` und `def _neu_aufloesen …`) ersetzen durch:
```python
# Werkzeuge, deren Flaeche Claude spaeter mit neu:<n> anspricht (agent_werkzeuge._Lauf.neu)
NEU_WERKZEUGE = agent_werkzeuge.NEU_WERKZEUGE
_neu_aufloesen = agent_werkzeuge.neu_aufloesen     # Live-Stand und Nachspielen loesen gleich auf
```

- [ ] **Step 4: Tests grün**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/claw/tests/test_agent_werkzeuge.py spaces/marketing/tests/test_chat_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/claw/agent_werkzeuge.py spaces/marketing/claw/tests/test_agent_werkzeuge.py spaces/marketing/workers/chat_worker.py
git commit -m "feat(marketing): Aenderungsliste auf eine neuere Fassung nachspielen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Arbeiter — Nachspielen beim Fertigwerden, Rennen, Stopp-Behalten

**Files:**
- Modify: `spaces/marketing/workers/chat_worker.py` (MOS): `ChatApi` (Z. 52–108), `_Live.__init__` (Z. 308–314), `chat_bearbeiten` (Z. 605–635), `_bearbeiten` Schleife (Z. 701–786); neue Konstanten und Hilfen
- Modify: `spaces/marketing/claw/agent_prompt.py:324-327` (`korrektur_text`)
- Test: `spaces/marketing/tests/test_chat_worker.py`, `spaces/marketing/claw/tests/test_agent_prompt.py`

**Interfaces:**
- Consumes: `GET /{aid}/neueste`, `fertig` mit `basis`/`hinweise` und `{"status": "veraltet"}`, `gestoppt` mit `basis`/`hinweise` (Task 2); `agent_werkzeuge.nachspielen`, `UEBERSPRUNGEN` (Task 3). `naechster` liefert `fassung` (die Basis der Runde, 060).
- Produces:
  - `ChatApi.neueste(aid) -> dict`, `ChatApi.gestoppt(aid, bloecke, basis: int | None = None, hinweise=()) -> dict`.
  - Konstanten `NACHSPIELEN_MAX = 3`, `ZU_VIELE = "Zu viele gleichzeitige Änderungen – bitte noch einmal senden"`, `NICHTS_UMGESETZT = "Fertig, nichts umgesetzt – eine andere Runde hat den Entwurf inzwischen geändert."`, `NACHGESPIELT = "Auf Fassung {n} nachgespielt – eine andere Runde war schneller; bei widersprüchlichen Bitten gilt diese Runde."`.
  - `fertig`-Daten enthalten immer `basis` (Fassung, auf die gespeichert wird) und `hinweise` (Liste).
  - `agent_prompt.korrektur_text(fehler: str, bloecke: dict | None = None) -> str` (mit Blöcken: der neue Stand hängt an).

- [ ] **Step 1: Tests schreiben**

`test_agent_prompt.py`:
```python
def test_korrektur_mit_neuester_fassung():
    t = ap.korrektur_text("u: Kontrast", {"root": {"type": "EmailLayout", "data": {"childrenIds": []}}, "u": {"x": 1}})
    assert t.startswith("Deine letzte Antwort konnte nicht umgesetzt werden: u: Kontrast")
    assert "Eine andere Runde hat den Entwurf inzwischen geändert" in t and 'BLÖCKE (JSON): {"root"' in t
    assert "BLÖCKE" not in ap.korrektur_text("x")
```

`test_chat_worker.py` (ans Ende):
```python
# ---- Nachspielen beim Fertigwerden (Spec 2026-10-09-editor-parallele-runden §1) -----------------------
VERALTET = {"status": "veraltet"}
AUFTRAG4 = {**AUFTRAG, "fassung": 4}
DOC_B = {"root": {"type": "EmailLayout", "data": {"backdropColor": "#ffffff", "childrenIds": ["u"]}},
         "u": {"type": "Text", "data": {"props": {"text": "Neu von Runde B"}}}}


class RennApi(Api):
    """fertig antwortet der Reihe nach (die letzte Antwort wiederholt sich); neueste ebenso."""
    def __init__(self, fertig_folge, neueste_folge, **kw):
        super().__init__(**kw)
        self.fertig_folge, self.neueste_folge = list(fertig_folge), list(neueste_folge)

    def fertig(self, aid, daten):
        self.log.append(("fertig", aid, daten))
        return self.fertig_folge.pop(0) if len(self.fertig_folge) > 1 else self.fertig_folge[0]

    def neueste(self, aid):
        self.log.append(("neueste", aid))
        return self.neueste_folge.pop(0) if len(self.neueste_folge) > 1 else self.neueste_folge[0]


def _fertig_daten(api):
    return [e[2] for e in api.aufrufe("fertig")]


def test_ohne_rennen_speichert_auf_der_eigenen_basis():
    api = Api()
    assert cw.chat_bearbeiten(api, AUFTRAG4, Fragen(GUT)) == "fertig"
    (daten,) = _fertig_daten(api)
    assert daten["basis"] == 4 and daten["hinweise"] == []


def test_rennen_verloren_spielt_auf_neueste_nach_und_meldet_geloeschten_block():
    api = RennApi([VERALTET, {"fassung": 6}], [{"fassung": 5, "bloecke": DOC_B}])
    antwort = json.dumps({"antwort": "Erledigt.", "aenderungen": [text("Eins", "Titel ändern"), farbe("#ff0000", "Rot")]})
    assert cw.chat_bearbeiten(api, AUFTRAG4, Fragen(antwort)) == "fertig"
    erst, zweit = _fertig_daten(api)
    assert erst["basis"] == 4 and erst["bloecke"]["t"]["data"]["props"]["text"] == "Eins"
    assert zweit["basis"] == 5 and "t" not in zweit["bloecke"]
    assert zweit["bloecke"]["root"]["data"]["backdropColor"] == "#ff0000"
    assert zweit["bloecke"]["u"]["data"]["props"]["text"] == "Neu von Runde B"      # die andere Runde bleibt
    assert zweit["hinweise"] == [cw.NACHGESPIELT.format(n=5), cw.agent_werkzeuge.UEBERSPRUNGEN + "Titel ändern"]
    assert api.aufrufe("pruefen")[-1][2] == zweit["bloecke"] and api.aufrufe("zurueck") == []


def test_nachspielen_mit_neuer_flaeche_bekommt_neue_ids():
    neuer = {**DOC, "u": DOC_B["u"], "root": {"type": "EmailLayout", "data": {"childrenIds": ["t", "u"]}}}
    hg = {"werkzeug": "hintergrund_setzen", "flaeche": "neu:1", "farbe": "#000000", "schritt": "Hintergrund"}
    api = RennApi([VERALTET, {"fassung": 6}], [{"fassung": 5, "bloecke": neuer}])
    assert cw.chat_bearbeiten(api, AUFTRAG4, Fragen(json.dumps({"antwort": "Fläche da.", "aenderungen": [FL, hg]}))) == "fertig"
    erst, zweit = [d["bloecke"] for d in _fertig_daten(api)]
    alt_id, (neu_id,) = _agent_ids(erst)[0], _agent_ids(zweit)
    assert neu_id != alt_id and zweit[neu_id]["data"]["props"]["gestaltung"]["hintergrund"] == "#000000"
    assert "u" in zweit and "neu:1" not in json.dumps(zweit)


def test_rennen_dreimal_verloren_gibt_mit_zu_vielen_zurueck():
    api = RennApi([VERALTET], [{"fassung": 5, "bloecke": DOC}, {"fassung": 6, "bloecke": DOC}, {"fassung": 7, "bloecke": DOC}])
    assert cw.chat_bearbeiten(api, AUFTRAG4, Fragen(GUT)) == "fehler"
    assert [d["basis"] for d in _fertig_daten(api)] == [4, 5, 6, 7] and cw.NACHSPIELEN_MAX == 3
    assert api.aufrufe("zurueck")[0][2] == cw.ZU_VIELE


def test_nichts_passt_mehr_endet_fertig_ohne_fassung():
    api = RennApi([VERALTET, {"fassung": None}], [{"fassung": 5, "bloecke": DOC_B}])
    nur_t = json.dumps({"antwort": "Titel geändert.", "aenderungen": [text("Eins", "Titel ändern")]})
    assert cw.chat_bearbeiten(api, AUFTRAG4, Fragen(nur_t)) == "fertig"
    zweit = _fertig_daten(api)[1]
    assert zweit["bloecke"] is None and zweit["antwort"] == cw.NICHTS_UMGESETZT
    assert cw.agent_werkzeuge.UEBERSPRUNGEN + "Titel ändern" in zweit["hinweise"]


def test_bildauftrag_mit_fehlendem_platz_wird_verworfen():
    held = {"type": "Image", "data": {"props": {"url": "medien:nl-12345678-held.jpg", "alt": "Team"}}}
    mit_held = {"root": {"type": "EmailLayout", "data": {"backdropColor": "#ffffff", "childrenIds": ["t", "held"]}},
                "t": DOC["t"], "held": held}
    bild = {"werkzeug": "bild_erzeugen", "platz": "held", "hinweis": "Kerzen", "schritt": "Bild beauftragen"}
    api = RennApi([VERALTET, {"fassung": 6}], [{"fassung": 5, "bloecke": DOC}])
    antwort = json.dumps({"antwort": "Bild kommt.", "aenderungen": [farbe("#ff0000", "Rot"), bild]})
    assert cw.chat_bearbeiten(api, {**AUFTRAG4, "bloecke": mit_held}, Fragen(antwort)) == "fertig"
    erst, zweit = _fertig_daten(api)
    assert erst["bildauftraege"] == [{"platz": "held", "modus": "neu", "hinweis": "Kerzen"}]
    assert zweit["bildauftraege"] == [] and cw.agent_werkzeuge.UEBERSPRUNGEN + "Bild beauftragen" in zweit["hinweise"]


def test_schoenheit_nach_nachspielen_korrekturrunde_von_der_neuesten_fassung():
    api = RennApi([VERALTET, {"fassung": 6}], [{"fassung": 5, "bloecke": DOC_B}], pruefen=[None, "u: Kontrast zu gering"])
    zweite = json.dumps({"antwort": "Korrigiert.", "aenderungen": [farbe("#222222", "Dunkler")]})
    fragen = Fragen(GUT, zweite)
    assert cw.chat_bearbeiten(api, AUFTRAG4, fragen) == "fertig"
    korrektur = fragen.gesehen[1][1][-1]["content"]
    assert "u: Kontrast zu gering" in korrektur and "Neu von Runde B" in korrektur and "BLÖCKE (JSON)" in korrektur
    letzte = _fertig_daten(api)[-1]
    assert letzte["basis"] == 5 and letzte["bloecke"]["root"]["data"]["backdropColor"] == "#222222"
    assert "u" in letzte["bloecke"] and api.aufrufe("zurueck") == []


def test_stopp_behalten_spielt_die_gueltigen_schritte_auf_die_neueste_fassung():
    """Review Focus 5: eine andere Runde hat inzwischen gespeichert - Behalten verliert die Schritte nicht."""
    uhr = Uhr()
    api = RennApi([{"fassung": 9}], [{"fassung": 5, "bloecke": DOC_B}])
    api.zwischen = [{"weiter": True}, {"weiter": False, "grund": "stopp", "stopp": "behalten"}]
    gestoppt = []
    api.gestoppt = lambda aid, bloecke, basis=None, hinweise=(): gestoppt.append((bloecke, basis, list(hinweise))) or {}
    s = stuecke([text("Eins", "Titel"), farbe("#111111", "Farbe"), farbe("#222222", "Noch eine")])
    strom = Strom(uhr, [s[0], 1.0, s[1], 1.0, s[2], s[3]])
    assert cw.chat_bearbeiten(api, AUFTRAG4, strom, uhr, uhr.schlafen, halten_takt_s=60, drossel_s=1.0) == "gestoppt"
    ((bloecke, basis, hinweise),) = gestoppt
    assert basis == 5 and bloecke["root"]["data"]["backdropColor"] == "#111111"
    assert "u" in bloecke and "t" not in bloecke
    assert hinweise == [cw.NACHGESPIELT.format(n=5), cw.agent_werkzeuge.UEBERSPRUNGEN + "Titel"]


def test_stopp_behalten_ohne_fremde_fassung_wie_bisher():
    uhr = Uhr()
    api = RennApi([{"fassung": 9}], [{"fassung": 4, "bloecke": DOC}])
    api.zwischen = [{"weiter": False, "grund": "stopp", "stopp": "behalten"}]
    strom = Strom(uhr, stuecke([text("Eins", "Titel"), farbe("#111111", "Farbe")]))
    assert cw.chat_bearbeiten(api, AUFTRAG4, strom, uhr, uhr.schlafen, halten_takt_s=60, drossel_s=0) == "gestoppt"
    ((_, _, bloecke),) = api.aufrufe("gestoppt")
    assert bloecke["t"]["data"]["props"]["text"] == "Eins"


def test_chatapi_neueste_und_gestoppt_mit_basis(monkeypatch):
    api, g = _api_mit_antwort(monkeypatch, b'{"fassung": 5, "bloecke": {}}')
    assert api.neueste("a1") == {"fassung": 5, "bloecke": {}}
    assert g["url"] == "https://vm/api/chat/arbeiter/a1/neueste" and g["methode"] == "GET"
    api, g = _api_mit_antwort(monkeypatch, b'{"status": "fertig"}')
    api.gestoppt("a1", DOC, 5, ["x"])
    assert json.loads(g["data"]) == {"bloecke": DOC, "basis": 5, "hinweise": ["x"]}
    api.gestoppt("a1", None)
    assert json.loads(g["data"]) == {"bloecke": None}
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_worker.py spaces/marketing/claw/tests/test_agent_prompt.py -q`
Expected: FAIL (`KeyError: 'basis'`, `AttributeError: … NACHGESPIELT`).

- [ ] **Step 3: Implementieren**

`agent_prompt.korrektur_text` ersetzen:
```python
def korrektur_text(fehler: str, bloecke: dict | None = None) -> str:
    text = (f"Deine letzte Antwort konnte nicht umgesetzt werden: {fehler}\n"
            "Nichts wurde geändert. Antworte erneut mit genau einem vollständigen, korrigierten JSON-Objekt "
            '{"antwort": ..., "aenderungen": [...]} und sonst nichts.')
    if bloecke is not None:
        text += ("\nEine andere Runde hat den Entwurf inzwischen geändert. Deine Änderungen werden auf diesen "
                 "aktuellen Stand angewendet – beziehe dich nur auf ihn:\nBLÖCKE (JSON): "
                 + json.dumps(bloecke, ensure_ascii=False, separators=(",", ":")))
    return text
```

`ChatApi` ergänzen bzw. `gestoppt` ersetzen:
```python
    def neueste(self, aid) -> dict:
        return json.loads(self._anfrage("GET", f"/{aid}/neueste") or b"{}")

    def gestoppt(self, aid, bloecke: dict | None, basis: int | None = None, hinweise=()) -> dict:
        daten: dict = {"bloecke": bloecke}
        if basis is not None:
            daten.update(basis=basis, hinweise=list(hinweise))
        return self._post(f"/{aid}/gestoppt", daten)
```

`_Live.__init__`: Parameter `basis: int | None = None` anhängen und `self.basis = basis` setzen (die Fassung, auf der der Live-Stand aufbaut).

Unter `NICHT_UMGESETZT` (Z. 39) die Konstanten:
```python
NACHSPIELEN_MAX = 3
ZU_VIELE = "Zu viele gleichzeitige Änderungen – bitte noch einmal senden"
NICHTS_UMGESETZT = "Fertig, nichts umgesetzt – eine andere Runde hat den Entwurf inzwischen geändert."
NACHGESPIELT = ("Auf Fassung {n} nachgespielt – eine andere Runde war schneller; "
                "bei widersprüchlichen Bitten gilt diese Runde.")
```

Vor `chat_bearbeiten` die Hilfen:
```python
class _Neuer(Exception):
    """Die Schoenheitspruefung schlug nach dem Nachspielen an: Korrekturrunde von der neuesten Fassung."""
    def __init__(self, grund: str, neu: dict):
        super().__init__(grund)
        self.grund, self.neu = grund, neu


def _neueste_lesen(api, aid) -> dict:
    neu = api.neueste(aid)
    if (not isinstance(neu, dict) or not isinstance(neu.get("bloecke"), dict)
            or isinstance(neu.get("fassung"), bool) or not isinstance(neu.get("fassung"), int)):
        raise ValueError("neueste Fassung unlesbar")
    return neu


def _speichern(api, aid, daten: dict, aenderungen: list, medien: set, basis, spur: denkspur.Spur) -> dict:
    """fertig mit Nachspielen (Spec 2026-10-09 §1): verliert das Speichern das Rennen, die Aenderungsliste auf die
    neueste Fassung nachspielen, pruefen und erneut speichern - hoechstens NACHSPIELEN_MAX-mal. -> Antwort der VM,
    {"status": "zu_viele"} nach dem letzten verlorenen Rennen. Wirft _Neuer, wenn die Schoenheitspruefung nach dem
    Nachspielen anschlaegt."""
    hinweise: list[str] = []
    for runde in range(NACHSPIELEN_MAX + 1):
        antwort = api.fertig(aid, {**daten, "basis": basis, "hinweise": hinweise})
        if antwort.get("status") != "veraltet":
            return antwort
        if runde == NACHSPIELEN_MAX:
            break
        if not api.weiter(aid):
            return {"status": "fehler"}
        neu = _neueste_lesen(api, aid)
        spur.schritt(f"Nachspielen auf Fassung {neu['fassung']}")
        ns = agent_werkzeuge.nachspielen(neu["bloecke"], aenderungen, medien)
        basis, hinweise = neu["fassung"], [NACHGESPIELT.format(n=neu["fassung"]), *ns.uebersprungen]
        if not ns.geaendert:      # keine Aenderung passt mehr: fertig ohne Fassung (dann gibt es kein Rennen)
            daten = {**daten, "antwort": NICHTS_UMGESETZT, "bloecke": None, "bildauftraege": [],
                     "export_vorschlag": None}
            continue
        grund = api.pruefen(aid, ns.bloecke)
        if grund:
            spur.schritt(f"Schönheitsprüfung: {grund}")
            raise _Neuer(grund, neu)
        daten = {**daten, "bloecke": ns.bloecke, "bildauftraege": ns.bildauftraege,
                 "export_vorschlag": ns.export_vorschlag, "notiz": ns.notiz or daten.get("notiz", "")}
        spur.ende()
    return {"status": "zu_viele"}
```

`chat_bearbeiten`: `_Live(...)` mit `basis=auftrag.get("fassung")` anlegen und den `_Stopp`-Zweig ersetzen:
```python
    except _Stopp as s:
        spur.ende()
        bloecke, basis, extra = (live.gueltig if s.art == "behalten" else None), None, []
        if s.art == "behalten" and live.angewandt and live.basis is not None:
            try:   # "Behalten" nach demselben Verfahren: auf eine inzwischen neuere Fassung nachspielen
                neu = _neueste_lesen(api, aid)
                if neu["fassung"] != live.basis:
                    ns = agent_werkzeuge.nachspielen(neu["bloecke"], live.angewandt, live.medien)
                    bloecke = ns.bloecke if ns.geaendert else None
                    basis, extra = neu["fassung"], [NACHGESPIELT.format(n=neu["fassung"]), *ns.uebersprungen]
            except (ApiFehler, OSError, ValueError, agent_werkzeuge.WerkzeugFehler):
                pass               # wie bisher: der letzte gueltige Stand, die VM entscheidet
        try:
            if basis is None:
                api.gestoppt(aid, bloecke)
            else:
                api.gestoppt(aid, bloecke, basis, extra)
        except (ApiFehler, OSError, ValueError):
            pass             # die VM schliesst einen gestoppten Auftrag nach 15 s selbst ab
        return "gestoppt"
```

In `_bearbeiten` den Abschnitt ab `if bildauftraege:` (Z. 773) bis zum Schleifenende (Z. 785) ersetzen:
```python
        if bildauftraege:
            spur.schritt(f"Bilder beauftragt: {len(bildauftraege)}")
        if ergebnis.geaendert:
            spur.schritt("Fassung gespeichert")
        spur.ende()
        daten = {"antwort": _mit_hinweisen(hinweise, text_antwort),
                 "bloecke": bloecke if ergebnis.geaendert else None,
                 "bildauftraege": bildauftraege, "export_vorschlag": export, "notiz": ergebnis.notiz}
        try:
            antwort_vm = _speichern(api, aid, daten, antwort["aenderungen"], set(medien), live.basis, spur)
        except _Neuer as n:
            fehler = n.grund
            if versuch == 1:       # Korrekturrunde von der neuesten Fassung
                auftrag = {**auftrag, "bloecke": n.neu["bloecke"], "fassung": n.neu["fassung"]}
                live.original, live.basis = n.neu["bloecke"], n.neu["fassung"]
                spur.korrektur()
                nachrichten += [{"role": "assistant", "content": text},
                                {"role": "user", "content": agent_prompt.korrektur_text(fehler, n.neu["bloecke"])}]
                continue
            return zurueckgeben(NICHT_UMGESETZT + fehler)
        if antwort_vm.get("status") == "zu_viele":
            return zurueckgeben(ZU_VIELE)
        return "fehler" if antwort_vm.get("status") == "fehler" else "fertig"
```
(`auftrag` ist in `_bearbeiten` ein Parameter; die Neuzuweisung wirkt auf das `anwenden(auftrag.get("bloecke") …)` des zweiten Versuchs.)

- [ ] **Step 4: Tests grün**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_worker.py spaces/marketing/claw/tests/test_agent_prompt.py spaces/marketing/claw/tests/test_agent_werkzeuge.py -q`
Expected: PASS (auch alle bisherigen Arbeiter-Tests).

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/workers/chat_worker.py spaces/marketing/claw/agent_prompt.py spaces/marketing/tests/test_chat_worker.py spaces/marketing/claw/tests/test_agent_prompt.py
git commit -m "feat(marketing): Arbeiter spielt Runden auf die neueste Fassung nach" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Arbeiter — drei Editor-Plätze

**Files:**
- Modify: `spaces/marketing/workers/chat_worker.py:831-892` (`main`, neue `editor_schleife`, `editor_starten`, `_warten`)
- Test: `spaces/marketing/tests/test_chat_worker.py` (`test_main_startet_marken_und_wissens_faden` ersetzen, neue Tests)

**Interfaces:**
- Consumes: `schleifenschritt(api, ein, feld)`, `ein_durchlauf`, `marken_starten`, `wissen_starten` (unverändert).
- Produces:
  - `EDITOR_PLAETZE = 3`
  - `editor_schleife(api, ein, stopp: threading.Event, nr: int, takt_s: float = TAKT_S) -> None` (schreibt `STAND[f"editor_{nr}"]` und `STAND["letztes_ergebnis"]`)
  - `editor_starten(api, ein, stopp: threading.Event, plaetze: int = EDITOR_PLAETZE, takt_s: float = TAKT_S) -> list[threading.Thread]` (Daemon-Fäden `editor-1` … `editor-3`)
  - `_warten(stopp: threading.Event) -> None` (Hauptfaden wartet, bis Strg+C oder `stopp`)

- [ ] **Step 1: Tests schreiben**

```python
def test_drei_editor_plaetze_laufen_gleichzeitig(monkeypatch):
    monkeypatch.setattr(cw, "STAND", {"letzter_lauf": None, "letztes_ergebnis": None})
    stopp, schranke = cw.threading.Event(), cw.threading.Barrier(3, timeout=5)

    def ein(api):
        schranke.wait()            # kehrt nur zurueck, wenn drei Plaetze gleichzeitig arbeiten
        stopp.set()
        return "fertig"
    faeden = cw.editor_starten(object(), ein, stopp, takt_s=0.01)
    for f in faeden:
        f.join(5)
    assert cw.EDITOR_PLAETZE == 3 and [f.name for f in faeden] == ["editor-1", "editor-2", "editor-3"]
    assert all(f.daemon and not f.is_alive() for f in faeden)
    assert [cw.STAND[f"editor_{n}"] for n in (1, 2, 3)] == ["fertig"] * 3 and cw.STAND["letztes_ergebnis"] == "fertig"


def test_spur_und_denken_bleiben_je_runde_getrennt():
    schranke, sperre, erg = cw.threading.Barrier(2, timeout=5), cw.threading.Lock(), {}

    class Parallel:
        def __init__(self, gedanke, antwort):
            self.gedanke, self.antwort = gedanke, antwort

        def __call__(self, system, nachrichten, denken=None):
            return self._lauf(denken)

        def _lauf(self, denken):
            denken(self.gedanke)
            schranke.wait()             # beide Runden denken gleichzeitig
            yield self.antwort

    class SpurApi(Api):
        def denken(self, aid, denken, schritte):
            with sperre:
                self.spur.setdefault(aid, []).append((denken, [s["text"] for s in schritte]))
            return {"ok": True}
    api = SpurApi()
    api.spur = {}
    rot = json.dumps({"antwort": "a", "aenderungen": [farbe("#ff0000", "Rot A")]})
    blau = json.dumps({"antwort": "b", "aenderungen": [farbe("#0000ff", "Blau B")]})

    def lauf(aid, gedanke, antwort):
        erg[aid] = cw.chat_bearbeiten(api, {**AUFTRAG, "id": aid}, Parallel(gedanke, antwort))
    faeden = [cw.threading.Thread(target=lauf, args=("a1", "Denke A", rot)),
              cw.threading.Thread(target=lauf, args=("a2", "Denke B", blau))]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(10)
    assert erg == {"a1": "fertig", "a2": "fertig"}
    denken_a, schritte_a = api.spur["a1"][-1]
    denken_b, schritte_b = api.spur["a2"][-1]
    assert "Denke A" in denken_a and "Denke B" not in denken_a and "Rot A" in schritte_a and "Blau B" not in schritte_a
    assert "Denke B" in denken_b and "Denke A" not in denken_b and "Blau B" in schritte_b and "Rot A" not in schritte_b
```

`test_main_startet_marken_und_wissens_faden` ersetzen:
```python
def test_main_startet_editor_plaetze_marke_und_wissen(monkeypatch):
    from spaces.marketing.workers import marken_arbeiter, wissen_arbeiter
    monkeypatch.setattr(cw, "umgebung_laden", lambda: None)
    monkeypatch.setenv("MARKETING_BILD_URL", "https://vm.example")
    monkeypatch.setenv("MARKETING_BILD_KEY", "k")
    gestartet = {}

    class Faden:
        def __init__(self, name):
            self.name, self.gejoint = name, False

        def join(self, timeout=None):
            self.gejoint = True

    def marken(api, abgleich, ein, stopp, takt_s=cw.TAKT_S):
        gestartet["marke"] = (api, ein, stopp, Faden("marke"))
        return gestartet["marke"][3]

    def wissen(api, ein, stopp, takt_s=cw.TAKT_S):
        gestartet["wissen"] = (api, ein, stopp, Faden("wissen"))
        return gestartet["wissen"][3]

    def editor(api, ein, stopp, plaetze=cw.EDITOR_PLAETZE, takt_s=cw.TAKT_S):
        gestartet["editor"] = (api, ein, stopp, plaetze, [Faden(f"editor-{n}") for n in range(1, plaetze + 1)])
        return gestartet["editor"][4]

    class Ende(Exception):
        pass
    monkeypatch.setattr(cw, "marken_starten", marken)
    monkeypatch.setattr(cw, "wissen_starten", wissen)
    monkeypatch.setattr(cw, "editor_starten", editor)
    monkeypatch.setattr(cw, "HTTPServer", lambda *a, **kw: type("S", (), {"serve_forever": lambda self: None})())
    monkeypatch.setattr(cw, "_warten", lambda stopp: (_ for _ in ()).throw(Ende()))
    with pytest.raises(Ende):
        cw.main()
    assert gestartet["marke"][1] is marken_arbeiter.ein_durchlauf
    assert gestartet["wissen"][1] is wissen_arbeiter.ein_durchlauf
    assert isinstance(gestartet["editor"][0], cw.ChatApi) and gestartet["editor"][1] is cw.ein_durchlauf
    assert gestartet["editor"][3] == 3
    assert gestartet["marke"][2].is_set() and gestartet["marke"][2] is gestartet["wissen"][2] is gestartet["editor"][2]
    assert gestartet["marke"][3].gejoint and gestartet["wissen"][3].gejoint
    assert all(f.gejoint for f in gestartet["editor"][4])
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_worker.py -q -k "plaetze or getrennt or main"`
Expected: FAIL (`AttributeError: … editor_starten`).

- [ ] **Step 3: Implementieren**

`main` (Z. 831–851) ersetzen und die neuen Funktionen dahinter einfügen:
```python
EDITOR_PLAETZE = 3


def main() -> None:
    umgebung_laden()
    basis, schluessel = os.environ.get("MARKETING_BILD_URL", ""), os.environ.get("MARKETING_BILD_KEY", "")
    if not basis or not schluessel:
        raise SystemExit("MARKETING_BILD_URL/MARKETING_BILD_KEY fehlen in Vibemind_V1/.env")
    from spaces.marketing.workers import marken_arbeiter, wissen_arbeiter   # importieren dieses Modul selbst
    api = ChatApi(basis, schluessel)
    marke = marken_arbeiter.MarkenApi(basis, schluessel)
    abgleich = marken_arbeiter.Abgleich()                    # erster Schritt = Abgleich beim Start
    threading.Thread(target=HTTPServer(("127.0.0.1", PORT), _Gesundheit).serve_forever, daemon=True).start()
    stopp = threading.Event()
    faeden = [marken_starten(marke, abgleich, marken_arbeiter.ein_durchlauf, stopp),
              wissen_starten(marken_arbeiter.MarkenApi(basis, schluessel), wissen_arbeiter.ein_durchlauf, stopp),
              *editor_starten(api, ein_durchlauf, stopp)]
    try:
        _warten(stopp)
    finally:                 # Strg+C/Ende: alle Faeden beenden ihren Schritt und halten an
        stopp.set()
        for faden in faeden:
            faden.join(timeout=MARKE_ENDE_S)


def _warten(stopp: threading.Event) -> None:
    """Der Hauptfaden wartet nur (kurzer Takt, damit Strg+C unter Windows durchkommt)."""
    while not stopp.wait(1):
        pass


def editor_schleife(api, ein, stopp: threading.Event, nr: int, takt_s: float = TAKT_S) -> None:
    """Ein Editor-Platz (Spec 2026-10-09 §1): holt Runden, solange er frei ist. Drei Plaetze = bis zu drei Runden
    gleichzeitig; die Grenzen je Entwurf setzt die DB durch."""
    feld = f"editor_{nr}"
    while not stopp.is_set():
        schleifenschritt(api, ein, feld)
        STAND["letztes_ergebnis"] = STAND.get(feld)
        stopp.wait(takt_s)


def editor_starten(api, ein, stopp: threading.Event, plaetze: int = EDITOR_PLAETZE,
                   takt_s: float = TAKT_S) -> list[threading.Thread]:
    faeden = []
    for nr in range(1, plaetze + 1):
        faden = threading.Thread(target=editor_schleife, args=(api, ein, stopp, nr, takt_s),
                                 name=f"editor-{nr}", daemon=True)
        faden.start()
        faeden.append(faden)
    return faeden
```
Docstring oben ergänzen: „Drei Editor-Plätze (Spec 2026-10-09-editor-parallele-runden) neben Marken- und Wissens-Faden.“

- [ ] **Step 4: Tests grün**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/test_chat_worker.py spaces/marketing/tests/test_marken_arbeiter.py spaces/marketing/tests/test_wissen_arbeiter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/workers/chat_worker.py spaces/marketing/tests/test_chat_worker.py
git commit -m "feat(marketing): Chat-Arbeiter mit drei Editor-Plaetzen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Prompt-Regel — Bezug ohne Markierung

**Files:**
- Modify: `spaces/marketing/claw/agent_prompt.py:100-105` (Abschnitt MARKIERT)
- Test: `spaces/marketing/claw/tests/test_agent_prompt.py`

**Interfaces:**
- Produces: `agent_prompt.REGEL_BEZUG: str` (der Satz, in `SYSTEM` und `system(marke=True)` enthalten).

- [ ] **Step 1: Test schreiben**

```python
def test_bezugsregel_ohne_markierung():
    assert ap.REGEL_BEZUG == (
        "Ohne Markierung beziehen sich Verweise wie „das“, „hier“ oder „so nicht“ auf deine eigene letzte Runde "
        "(die letzte Antwort unter BISHERIGER CHAT). Ist der Bezug nicht eindeutig, frag kurz nach und ändere "
        'nichts ("aenderungen": []).')
    assert ap.REGEL_BEZUG in ap.SYSTEM and ap.REGEL_BEZUG in ap.system(marke=True)
```

- [ ] **Step 2: Test läuft, er schlägt fehl**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/claw/tests/test_agent_prompt.py -q -k bezugsregel`
Expected: FAIL (`AttributeError: … REGEL_BEZUG`).

- [ ] **Step 3: Implementieren**

Vor `_SYSTEM` definieren:
```python
REGEL_BEZUG = ("Ohne Markierung beziehen sich Verweise wie „das“, „hier“ oder „so nicht“ auf deine eigene letzte Runde "
               "(die letzte Antwort unter BISHERIGER CHAT). Ist der Bezug nicht eindeutig, frag kurz nach und ändere "
               'nichts ("aenderungen": []).')
```
In `_SYSTEM` im Abschnitt MARKIERT direkt nach dem ersten Satz („… fasse dann nur sie an.“) den Platzhalter `__BEZUG__` einfügen:
```
Ebenen; fasse dann nur sie an. __BEZUG__ Mitgeschickte Bilder liegen als Dateien vor, deren Pfad im Text steht: lies sie mit \
```
und `SYSTEM` um die Ersetzung erweitern:
```python
SYSTEM: str = (_SYSTEM.replace("__MAX__", str(MAX_AENDERUNGEN)).replace("__SCHRIFTEN__", _schnitte())
               .replace("__BEZUG__", REGEL_BEZUG))
```

- [ ] **Step 4: Test grün**

Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/claw/tests/test_agent_prompt.py spaces/marketing/tests/test_chat_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/claw/agent_prompt.py spaces/marketing/claw/tests/test_agent_prompt.py
git commit -m "feat(marketing): Editor-Agent bezieht 'das' ohne Markierung auf die eigene letzte Runde" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Editor — breitere, ziehbare Chat-Leiste

**Files:**
- Create: `editor/src/App/Chat/breite.ts`, `editor/src/App/Chat/breite.test.ts`
- Create: `editor/src/App/Chat/SeitenGriff.tsx`, `editor/src/App/Chat/SeitenGriff.test.tsx`
- Modify: `editor/src/App/InspectorDrawer/index.tsx` (Breite als Prop), `editor/src/App/index.tsx:59-76`, `editor/src/App/Chat/ChatLeiste.tsx:47,525` (`EINGABE_ZEILEN`)
- Modify: `sales-mcp/tests/test_editor_paket.py` (neuer Test), Bundle `sales-mcp/static/editor/*`

**Interfaces:**
- Produces:
  - `breite.ts`: `BREITE_START = 440`, `BREITE_MIN = 360`, `BREITE_SCHLUESSEL = 'vibemind.editor.chatbreite'`, `fensterBreite(): number`, `breiteBegrenzen(px: number, fenster: number): number`, `breiteLesen(fenster: number): number`, `breiteSchreiben(px: number): void`.
  - `SeitenGriff.tsx`: `useSeitenBreite(): [number, (px: number) => void]`, `default SeitenGriff({ breite, onBreite })`.
  - `InspectorDrawer({ chat, gesperrt, breite, griff })`; `INSPECTOR_DRAWER_WIDTH` entfällt.
  - `ChatLeiste.EINGABE_ZEILEN = 8`.

- [ ] **Step 1: Tests schreiben**

`breite.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BREITE_MIN, BREITE_SCHLUESSEL, BREITE_START, breiteBegrenzen, breiteLesen, breiteSchreiben } from './breite';

function speicher(werte: Record<string, string> = {}) {
  const m = new Map(Object.entries(werte));
  vi.stubGlobal('localStorage', { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) });
  return m;
}

afterEach(() => vi.unstubAllGlobals());

describe('Breite der Chat-Leiste', () => {
  it('startet mit 440 px ohne gemerkte Breite', () => {
    speicher();
    expect(breiteLesen(1600)).toBe(BREITE_START);
    expect(BREITE_START).toBe(440);
  });
  it('nimmt die gemerkte Breite, begrenzt auf 360 px bis zur halben Fensterbreite', () => {
    speicher({ [BREITE_SCHLUESSEL]: '600' });
    expect(breiteLesen(1600)).toBe(600);
    expect(breiteLesen(1000)).toBe(500);
    expect(breiteBegrenzen(200, 1600)).toBe(BREITE_MIN);
    expect(breiteBegrenzen(Number.NaN, 1600)).toBe(440);
    expect(breiteBegrenzen(500, 600)).toBe(BREITE_MIN);   // schmales Fenster: nie unter 360
  });
  it('kaputter Wert: Vorgabe', () => {
    speicher({ [BREITE_SCHLUESSEL]: 'breit' });
    expect(breiteLesen(1600)).toBe(440);
  });
  it('ohne Speicher (Zugriff wirft): Vorgabe, Schreiben wirft nicht', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('gesperrt'); },
      setItem: () => { throw new Error('gesperrt'); },
    });
    expect(breiteLesen(1600)).toBe(440);
    expect(() => breiteSchreiben(500)).not.toThrow();
  });
  it('schreibt gerundet unter dem Schluessel', () => {
    const m = speicher();
    breiteSchreiben(512.6);
    expect(m.get('vibemind.editor.chatbreite')).toBe('513');
  });
});
```

`SeitenGriff.test.tsx`:
```tsx
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import SeitenGriff from './SeitenGriff';

describe('SeitenGriff', () => {
  it('ist ein ziehbarer, per Tastatur bedienbarer Trenner mit der aktuellen Breite', () => {
    const html = renderToStaticMarkup(<SeitenGriff breite={480} onBreite={() => {}} />);
    expect(html).toContain('role="separator"');
    expect(html).toContain('aria-valuenow="480"');
    expect(html).toContain('aria-valuemin="360"');
    expect(html).toContain('Breite der Seitenleiste');
  });
});
```

`sales-mcp/tests/test_editor_paket.py` ergänzen:
```python
def test_paket_kennt_ziehbare_chat_leiste():
    # 2026-10-09 parallele Runden (Task 7): Breite gemerkt, Trenner beschriftet
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    for s in ("vibemind.editor.chatbreite", "Breite der Seitenleiste"):
        assert s in text, s
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run src/App/Chat/breite.test.ts src/App/Chat/SeitenGriff.test.tsx`
Expected: FAIL (Module fehlen).

- [ ] **Step 3: Implementieren**

`breite.ts`:
```ts
// Breite der rechten Leiste mit dem Editor-Chat (Spec 2026-10-09-editor-parallele-runden §2): Start 440 px,
// ziehbar zwischen 360 px und der halben Fensterbreite, je Browser gemerkt. Ohne Speicher gilt die Vorgabe.
export const BREITE_START = 440;
export const BREITE_MIN = 360;
export const BREITE_SCHLUESSEL = 'vibemind.editor.chatbreite';

export function fensterBreite(): number {
  const w = typeof window !== 'undefined' ? window.innerWidth : NaN;
  return Number.isFinite(w) && w > 0 ? w : 1280;
}

export function breiteBegrenzen(px: number, fenster: number): number {
  const max = Math.max(BREITE_MIN, Math.floor((Number.isFinite(fenster) ? fenster : 1280) / 2));
  const wert = Number.isFinite(px) ? Math.round(px) : BREITE_START;
  return Math.min(max, Math.max(BREITE_MIN, wert));
}

export function breiteLesen(fenster: number): number {
  try {
    const roh = globalThis.localStorage?.getItem(BREITE_SCHLUESSEL);
    const n = roh == null || roh.trim() === '' ? NaN : Number(roh);
    return breiteBegrenzen(n, fenster);
  } catch {
    return breiteBegrenzen(BREITE_START, fenster);
  }
}

export function breiteSchreiben(px: number): void {
  try {
    globalThis.localStorage?.setItem(BREITE_SCHLUESSEL, String(Math.round(px)));
  } catch {
    /* privates Fenster o. ae.: dann gilt beim naechsten Mal die Vorgabe */
  }
}
```

`SeitenGriff.tsx`:
```tsx
// Ziehgriff am linken Rand der rechten Leiste (Spec 2026-10-09 §2): Zeiger ziehen oder Pfeiltasten, gemerkt beim
// Loslassen bzw. je Tastendruck.
import React, { useCallback, useEffect, useState } from 'react';

import { Box } from '@mui/material';

import { BREITE_MIN, breiteBegrenzen, breiteLesen, breiteSchreiben, fensterBreite } from './breite';

const SCHRITT = 16;

export function useSeitenBreite(): [number, (px: number) => void] {
  const [breite, setBreite] = useState(() => breiteLesen(fensterBreite()));
  useEffect(() => {
    const anpassen = () => setBreite((b) => breiteBegrenzen(b, fensterBreite()));
    window.addEventListener('resize', anpassen);
    return () => window.removeEventListener('resize', anpassen);
  }, []);
  const setzen = useCallback((px: number) => setBreite(breiteBegrenzen(px, fensterBreite())), []);
  return [breite, setzen];
}

export default function SeitenGriff({ breite, onBreite }: { breite: number; onBreite: (px: number) => void }) {
  const ziehen = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    const start = e.clientX;
    let zuletzt = breite;
    el.setPointerCapture(e.pointerId);
    const bewegen = (ev: PointerEvent) => {
      zuletzt = breiteBegrenzen(breite + (start - ev.clientX), fensterBreite());
      onBreite(zuletzt);
    };
    const ende = () => {
      el.removeEventListener('pointermove', bewegen);
      el.removeEventListener('pointerup', ende);
      el.removeEventListener('pointercancel', ende);
      breiteSchreiben(zuletzt);
    };
    el.addEventListener('pointermove', bewegen);
    el.addEventListener('pointerup', ende);
    el.addEventListener('pointercancel', ende);
  };
  const tasten = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const neu = breiteBegrenzen(breite + (e.key === 'ArrowLeft' ? SCHRITT : -SCHRITT), fensterBreite());
    onBreite(neu);
    breiteSchreiben(neu);
  };
  return (
    <Box
      role="separator"
      aria-orientation="vertical"
      aria-label="Breite der Seitenleiste"
      aria-valuenow={breite}
      aria-valuemin={BREITE_MIN}
      tabIndex={0}
      onPointerDown={ziehen}
      onKeyDown={tasten}
      sx={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, zIndex: 2, cursor: 'col-resize', touchAction: 'none',
        transition: 'background-color 150ms ease-out',
        '&:hover, &:focus-visible': { bgcolor: 'rgba(91,140,255,0.45)', outline: 'none' },
      }}
    />
  );
}
```

`InspectorDrawer/index.tsx`: `INSPECTOR_DRAWER_WIDTH` entfernen; Signatur
```tsx
export default function InspectorDrawer({ chat, gesperrt = false, breite, griff }: { chat?: React.ReactNode; gesperrt?: boolean; breite: number; griff?: React.ReactNode }) {
```
alle vier `INSPECTOR_DRAWER_WIDTH` durch `breite` ersetzen und als erstes Kind des `<Drawer>` `{griff}` einfügen.

`App/index.tsx`: Import `INSPECTOR_DRAWER_WIDTH` entfernen, `import SeitenGriff, { useSeitenBreite } from './Chat/SeitenGriff';` ergänzen; in `App()`:
```tsx
  const [seitenBreite, setSeitenBreite] = useSeitenBreite();
  const rechts = inspectorDrawerOpen ? seitenBreite : 0;
```
und
```tsx
      <InspectorDrawer
        breite={seitenBreite}
        griff={<SeitenGriff breite={seitenBreite} onBreite={setSeitenBreite} />}
        gesperrt={arbeitet !== null || nurLesen}
        chat={<NewsletterChat exportOeffnen={exportOeffnen} />}
      />
```

`ChatLeiste.tsx`: unter `NACHRICHT_MAX` `export const EINGABE_ZEILEN = 8;` und am `InputBase` `maxRows={EINGABE_ZEILEN}` statt `maxRows={6}`.

- [ ] **Step 4: Tests, Typen, Bundle**

Run:
```
cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run; npx tsc --noEmit; npm run build
cd ../sales-mcp; $env:SALES_DB_URL = 'postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA = 'sales_test'
& E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/test_editor_paket.py -q
```
Expected: alles grün, `tsc` ohne Ausgabe.

- [ ] **Step 5: Commit (SC)**

```
git add editor/src/App/Chat/breite.ts editor/src/App/Chat/breite.test.ts editor/src/App/Chat/SeitenGriff.tsx editor/src/App/Chat/SeitenGriff.test.tsx editor/src/App/InspectorDrawer/index.tsx editor/src/App/index.tsx editor/src/App/Chat/ChatLeiste.tsx sales-mcp/tests/test_editor_paket.py sales-mcp/static/editor
git commit -m "feat(editor): Chat-Leiste 440 px breit, ziehbar und gemerkt; Eingabe bis 8 Zeilen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: sales-ui und Editor-Zustand — Senden statt Vormerken, mehrere Runden

**Files:**
- Modify: `sales-mcp/ui_editor.py:286-287` (Start-URLs), `:534-544` (drei Vormerk-Handler), `:902-904` (drei Routen)
- Modify: `sales-mcp/tests/test_editor_seite.py` (Fake Z. 95–103, Vormerk-Tests Z. 1352–1432), `sales-mcp/tests/test_editor_paket.py:66-71`
- Modify: `editor/src/pult.ts:36-38`, `editor/src/chat.ts`, `editor/src/pultZustand.ts`, `editor/src/main.tsx`, `editor/src/App/Chat/ChatLeiste.tsx`
- Create: `editor/src/pultZustand.runden.test.ts`
- Modify (Tests an die neuen Typen anpassen): `editor/src/chat.test.ts`, `editor/src/pultZustand.chat.test.ts`, `editor/src/pultZustand.kontext.test.ts`, `editor/src/pultZustand.live.test.ts`
- Bundle `sales-mcp/static/editor/*`

**Interfaces:**
- Consumes (Task 2): `POST …/chat` → `{auftrag, status}`; `GET …/chat` mit `neueste_fassung`, Verlaufsfeldern `schritt`, `schritt_nr`, `stopp`, `bild_hinweise`, Status `wartet`.
- Produces (`chat.ts`):
  - `ChatStatus = 'offen' | 'in_arbeit' | 'wartet' | 'fertig' | 'fehler'`
  - `ChatEintrag` zusätzlich `schritt: string; schritt_nr: number; stopp: StoppArt | null; bild_hinweise: string[]`
  - `ChatStand = { laeuft: boolean; verlauf: ChatEintrag[]; live: ChatLive | null; neueste: number | null }` (`vorgemerkt` entfällt)
  - `chatSenden(s, nachricht, kontext) → { ok: true; auftrag: string; status: 'offen' | 'wartet' } | Fehler`
  - `laufendeRunden(chat: Pick<ChatStand, 'verlauf'> | null): ChatEintrag[]` (Chat-Runden `offen`/`in_arbeit`/`wartet`), `exportLaeuft(chat): boolean`
  - `rueckgaengigFuer(verlauf: ChatEintrag[], neueste: number | null): string | null`
  - entfernt: `vormerken`, `vormerkungLoeschen`, `vormerkungStarten`, `Vorgemerkt`
- Produces (`pultZustand.ts`): `chatText: string` im Store, `chatTextSetzen(t: string)`, `chatEntwurfWiederholen()`; entfernt: `chatVormerken`, `vorgemerkteChipsZurueck`, `vormerkungLoeschenAuftrag`, `vormerkungStartenAuftrag`, `vorgemerktChips`.
- Produces (sales-ui): Startdaten ohne `chat_vormerkung_url`/`chat_vormerkung_starten_url`; die Proxy-Routen `…/chat/vormerkung[/starten]` entfallen.

- [ ] **Step 1: Tests schreiben bzw. anpassen**

`sales-mcp/tests/test_editor_seite.py`:
- Im Fake (Z. 95–103): die POST-Antwort für `/chat` wird `{"auftrag": "c1", "status": "wartet"}`, die GET-Antwort `{"laeuft": True, "verlauf": [{"id": "c1"}], "live": None, "neueste_fassung": 3}`; die zwei `if pfad == …/chat/vormerkung…`-Zweige löschen.
- `test_chat_durchreichen`: erwartet `r.json() == {"auftrag": "c1", "status": "wartet"}`.
- `test_chat_stand_json`: erwartet `{"laeuft": True, "verlauf": [{"id": "c1"}], "live": None, "neueste_fassung": 3}`; Kommentar „live und neueste_fassung kommen unverändert durch“.
- Löschen: `test_start_nennt_vormerk_und_stopp_urls`, `test_vormerken_put_durchreichen`, `test_vormerkung_loeschen_durchreichen`, `test_vormerkung_starten_durchreichen`, `test_vormerken_nachricht_ungueltig`, `test_vormerken_kontext_zu_gross_oder_kein_objekt`; in den Parametrisierungen von `test_vormerk_und_stopp_ohne_csrf` und `test_vormerk_und_stopp_fehlerabbildung` die drei `chat/vormerkung`-Zeilen streichen (die Tests heißen jetzt `test_stopp_ohne_csrf` und `test_stopp_fehlerabbildung`).
- Neu:
```python
def test_start_nennt_stopp_url_ohne_vormerkung(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["chat_stopp_url"] == f"/marketing/editor/{IID}/chat/stopp"
    assert "chat_vormerkung_url" not in start and "chat_vormerkung_starten_url" not in start


@pytest.mark.parametrize("methode,ende", [("PUT", "chat/vormerkung"), ("DELETE", "chat/vormerkung"),
                                          ("POST", "chat/vormerkung/starten")])
def test_vormerk_routen_gibt_es_nicht_mehr(angemeldet, pult, methode, ende):
    assert _senden(angemeldet, methode, ende, {"nachricht": "x"} if methode == "PUT" else None).status_code in (404, 405)
    assert not [a for a in pult.aufrufe if "vormerkung" in a[1]]
```

`sales-mcp/tests/test_editor_paket.py`, `test_paket_kennt_live_ansicht` ersetzen:
```python
def test_paket_kennt_live_ansicht():
    # 2026-10-02 Live-Ansicht, seit 2026-10-09 ohne Vormerken: Schritt-Zeile, Stopp-Dialog, Routen
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    for s in ("Bisherige Schritte behalten", "Schritt ", "Wird gestoppt", "chat_stopp_url"):
        assert s in text, s
    for s in ("Vormerken", "chat_vormerkung_url", "chat_vormerkung_starten_url"):
        assert s not in text, s
```

Editor-Tests anpassen (sonst bricht `tsc`):
- In jedem `eintrag(...)`-Helfer (`chat.test.ts`, `pultZustand.chat.test.ts`, `pultZustand.kontext.test.ts`, `pultZustand.live.test.ts`) nach `schritte: [],` ergänzen: `schritt: '', schritt_nr: 0, stopp: null, bild_hinweise: [],`.
- In allen `ChatStand`-Literalen `vorgemerkt: null`/`vorgemerkt: {...}` durch `neueste: null` ersetzen, `vorgemerktChips: null` aus `pultStore.setState(...)` in den `beforeEach` streichen und die Imports `chatVormerken`, `vorgemerkteChipsZurueck`, `vormerkungLoeschenAuftrag`, `vormerkungStartenAuftrag`, `vormerken`, `vormerkungLoeschen`, `vormerkungStarten` entfernen (`npx tsc --noEmit` listet die Stellen).
- Löschen: in `chat.test.ts` die Tests „liest live (…) und die vorgemerkte Nachricht“ (umbenennen in „liest live und neueste_fassung“ und auf `j.neueste_fassung` umstellen, s. u.), „vormerken: …“ (2), „vormerkungLoeschen …“, „vormerkungStarten …“; in `pultZustand.kontext.test.ts` „Vormerken nimmt die Chips mit …“, „Vormerken ebenso“ und den ganzen `describe('Vormerkung verbraucht', …)`; in `pultZustand.live.test.ts` den ganzen `describe('Vormerken', …)` und „fertig und sofort die vorgemerkte Nachricht im Lauf: trotzdem neu laden“.
- `chat.test.ts`, `describe('rueckgaengigFuer')` ersetzen:
```ts
describe('rueckgaengigFuer', () => {
  const f = (id: string, nachher: number | null, teil: Partial<ChatEintrag> = {}) =>
    eintrag({ id, status: 'fertig', fassung_nachher: nachher, ...teil });
  it('die Runde, deren Fassung die neueste ist - auch wenn danach eine Runde ohne Fassung fertig wurde', () => {
    expect(rueckgaengigFuer([f('a', 5), f('b', 6), f('c', null)], 6)).toBe('b');
  });
  it('parallel: eine aeltere Runde, die zuletzt gespeichert hat', () => {
    expect(rueckgaengigFuer([f('spaet', 7), f('frueh', 6)], 7)).toBe('spaet');
    expect(rueckgaengigFuer([f('spaet', 7), f('frueh', 6)], 6)).toBe('frueh');
  });
  it('nichts, wenn die neueste Fassung von niemandem aus dem Chat ist oder unbekannt', () => {
    expect(rueckgaengigFuer([f('a', 5)], 6)).toBeNull();
    expect(rueckgaengigFuer([f('a', 5)], null)).toBeNull();
  });
  it('Fehler und Exporte zaehlen nicht', () => {
    expect(rueckgaengigFuer([f('x', 5, { status: 'fehler' }), f('e', 5, { art: 'export' })], 5)).toBeNull();
  });
});
```
- `chat.test.ts`: im ersten `chatLaden`-Test `expect(r?.vorgemerkt).toBeNull();` durch `expect(r?.neueste).toBeNull();` ersetzen; im Test „kaputtes live/vorgemerkt …“ den Schlüssel `vorgemerkt: { id: 7 }` und `expect(r?.vorgemerkt).toBeNull();` streichen (Name: „kaputtes live wird vorsichtig gelesen“); den Test „liest live (…) und die vorgemerkte Nachricht“ ersetzen:
```ts
  it('liest live, neueste_fassung und die Felder laufender und wartender Runden', async () => {
    const roh = { ...eintrag({ id: 'w', status: 'wartet' }), schritt: 'Titel', schritt_nr: 2, stopp: 'behalten',
      bild_hinweise: ['Bild für held nicht erzeugt: weg', 5] };
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { laeuft: true, verlauf: [roh], live: null, neueste_fassung: 7 })));
    const r = await chatLaden(start);
    expect(r?.neueste).toBe(7);
    expect(r?.verlauf[0]).toMatchObject({ status: 'wartet', schritt: 'Titel', schritt_nr: 2, stopp: 'behalten',
      bild_hinweise: ['Bild für held nicht erzeugt: weg'] });
  });
```
  und im `describe('chatSenden')` den ersten Test auf den Status erweitern:
```ts
  it('sendet POST mit X-CSRF und {nachricht, kontext} und liefert Auftrag und Status', async () => {
    const f = vi.fn(async () => antwort(200, { auftrag: 'a-1', status: 'wartet' }));
    vi.stubGlobal('fetch', f);
    expect(await chatSenden(start, 'Mach es wärmer', { fenster: 'newsletter', auswahl: null })).toEqual({ ok: true, auftrag: 'a-1', status: 'wartet' });
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { auftrag: 'a-2' })));
    expect(await chatSenden(start, 'x', { fenster: 'newsletter', auswahl: null })).toEqual({ ok: true, auftrag: 'a-2', status: 'offen' });
  });
```
  (die bisherigen Prüfungen von Adresse, Methode und `X-CSRF` aus dem alten Test bleiben im neuen stehen).

Neue Datei `pultZustand.runden.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { chatAbfragen, chatAbschicken, chatEntwurfWiederholen, chatTextSetzen, pultStore } from './pultZustand';

const START = { speichern_url: '/s', chat_url: '/c', chat_stand_url: '/c.json', chat_rueckgaengig_url: '/c/r', csrf: 'm' } as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function eintrag(teil: Partial<ChatEintrag>): ChatEintrag {
  return { id: 'a1', art: 'chat', nachricht: 'n', antwort: '', status: 'in_arbeit', hinweise: [], ergebnis: {},
    fassung_vorher: 3, fassung_nachher: null, erstellt_am: 't', denken: '', schritte: [], schritt: '', schritt_nr: 0,
    stopp: null, bild_hinweise: [], ...teil };
}

function netz(antworten: Record<string, Array<[number, unknown]>>) {
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const liste = antworten[url];
    if (!liste) throw new TypeError('unbekannt ' + url);
    const [status, body] = liste.length > 1 ? (liste.shift() as [number, unknown]) : liste[0];
    return antwort(status, body);
  });
  vi.stubGlobal('fetch', f);
  return f;
}

let reload: ReturnType<typeof vi.fn>;
let speicher: Map<string, string>;

beforeEach(() => {
  vi.useFakeTimers();
  reload = vi.fn();
  speicher = new Map();
  vi.stubGlobal('window', { location: { reload } });
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => speicher.get(k) ?? null,
    setItem: (k: string, v: string) => void speicher.set(k, v),
    removeItem: (k: string) => void speicher.delete(k),
  });
  resetDocument({ root: { type: 'EmailLayout', data: { childrenIds: [] } } } as TEditorConfiguration);
  pultStore.setState({ start: START, basis: 3, ungespeichert: false, hinweisOffen: false, gestaltungOffen: null,
    gestaltungGeaendert: false, chat: null, chatText: '', chatAuswahl: [], chatAnhaenge: [] });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Mehrere Runden', () => {
  it('Senden während laufender Runden: POST an chat_url, Eintrag mit dem Status des Servers', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' }), eintrag({ id: 'r2' })], live: null, neueste: 3 } });
    const stand = { laeuft: true, verlauf: [eintrag({ id: 'r1' }), eintrag({ id: 'r2' }), eintrag({ id: 'r3', status: 'wartet' })], neueste_fassung: 3 };
    const f = netz({ '/c': [[200, { auftrag: 'r3', status: 'wartet' }]], '/c.json': [[200, stand]] });
    expect(await chatAbschicken('Noch was', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(f.mock.calls[0][0]).toBe('/c');
    const letzter = pultStore.getState().chat?.verlauf.find((e) => e.id === 'r3');
    expect(letzter?.status).toBe('wartet');
  });

  it('ein laufender Newsletter-Export sperrt weiter', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'x', art: 'export' })], live: null, neueste: 3 } });
    const f = netz({});
    expect(await chatAbschicken('Hallo', { fenster: 'newsletter', auswahl: null })).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
  });

  it('Entwurf im Eingabefeld überlebt das Neuladen nach einer fertigen Runde', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 } });
    chatTextSetzen('Und dann den Fuß kürzer');
    netz({ '/c.json': [[200, { laeuft: false, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 })], neueste_fassung: 4 }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(speicher.get('vibemind-chat-entwurf')).toBe('Und dann den Fuß kürzer');
    pultStore.setState({ chatText: '' });          // neu geladen
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatText).toBe('Und dann den Fuß kürzer');
    expect(speicher.has('vibemind-chat-entwurf')).toBe(false);
  });
});
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run:
```
cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run src/pultZustand.runden.test.ts src/chat.test.ts
cd ../sales-mcp; <venv-sales> -m pytest tests/test_editor_seite.py -q -k "vormerk or chat_durchreichen or chat_stand_json or stopp_url"
```
Expected: FAIL (`chatTextSetzen` fehlt; Startdaten nennen noch die Vormerk-URLs).

- [ ] **Step 3: Implementieren**

`sales-mcp/ui_editor.py`: die Start-Einträge `"chat_vormerkung_url"` und `"chat_vormerkung_starten_url"` (Z. 286–287), die Handler `editor_chat_vormerken`, `editor_chat_vormerkung_loeschen`, `editor_chat_vormerkung_starten` (Z. 534–544) und ihre drei `Route(...)`-Zeilen (Z. 902–904) löschen.

`editor/src/pult.ts` (Z. 36–38):
```ts
  // Live-Lauf (Spec 2026-10-02-newsletter-agent-live §3): Stopp je Runde (seit 2026-10-09 ohne Vormerken).
  chat_stopp_url: string;
```

`editor/src/chat.ts`:
- Kopfkommentar Z. 3: `// Live-Lauf und mehrere Runden (Spec 2026-10-09-editor-parallele-runden §2): Stopp je Runde, Warteschlange.`
- Typen:
```ts
export type ChatStatus = 'offen' | 'in_arbeit' | 'wartet' | 'fertig' | 'fehler';

export type ChatEintrag = {
  id: string;
  art: 'chat' | 'export';
  nachricht: string;
  antwort: string;
  status: ChatStatus;
  hinweise: string[];
  ergebnis: { export_vorschlag?: ExportAuswahl | null; notiz?: string };
  fassung_vorher: number | null;
  fassung_nachher: number | null;
  erstellt_am: string;
  denken: string;
  schritte: SpurSchritt[];
  // Live-Felder der Runde (gefuellt, solange sie laeuft) und gescheiterte Bildauftraege der Runde.
  schritt: string;
  schritt_nr: number;
  stopp: StoppArt | null;
  bild_hinweise: string[];
};

export type ChatStand = { laeuft: boolean; verlauf: ChatEintrag[]; live: ChatLive | null; neueste: number | null };
```
- `Vorgemerkt`, `vorgemerktLesen`, `vormerken`, `vormerkungLoeschen`, `vormerkungStarten` löschen.
- `chatSenden`:
```ts
export async function chatSenden(
  s: Start,
  nachricht: string,
  kontext: ChatKontext,
): Promise<{ ok: true; auftrag: string; status: 'offen' | 'wartet' } | Fehler> {
  const r = await senden(s, s.chat_url, { nachricht, kontext }, 'Der Assistent ist gerade nicht erreichbar');
  if (!r.ok) return r;
  if (typeof r.j.auftrag !== 'string' || !r.j.auftrag) return { ok: false, grund: UNVERSTAENDLICH };
  return { ok: true, auftrag: r.j.auftrag, status: r.j.status === 'wartet' ? 'wartet' : 'offen' };
}
```
- `STATUS` um `'wartet'` erweitern; in `eintragLesen` die vier Felder ergänzen:
```ts
    schritt: typeof v.schritt === 'string' ? v.schritt : '',
    schritt_nr: typeof v.schritt_nr === 'number' && Number.isInteger(v.schritt_nr) && v.schritt_nr > 0 ? v.schritt_nr : 0,
    stopp: v.stopp === 'behalten' || v.stopp === 'verwerfen' ? v.stopp : null,
    bild_hinweise: nurTexte(v.bild_hinweise),
```
- `chatLaden`: `return { laeuft: j.laeuft, verlauf, live: liveLesen(j.live), neueste: typeof j.neueste_fassung === 'number' && Number.isInteger(j.neueste_fassung) ? j.neueste_fassung : null };`
- Konstanten und Hilfen (ersetzen `LAEUFT`, `neueFassungNachChat`, `rueckgaengigFuer`, `laufenderChat`, `stoppDialogOffen`, `sperrText`):
```ts
const LAEUFT: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit'];
const RUNDE: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit', 'wartet'];

// fassung_nachher eines Eintrags, der seit der letzten Abfrage fertig geworden ist (vorher offen/in_arbeit/wartet);
// null, wenn keiner eine neue Fassung gebracht hat.
export function neueFassungNachChat(vorher: ChatEintrag[], nachher: ChatEintrag[]): number | null {
  const lief = new Set(vorher.filter((e) => RUNDE.includes(e.status)).map((e) => e.id));
  let neueste: number | null = null;
  for (const e of nachher) {
    if (e.status !== 'fertig' || e.fassung_nachher === null || !lief.has(e.id)) continue;
    if (neueste === null || e.fassung_nachher > neueste) neueste = e.fassung_nachher;
  }
  return neueste;
}

// Rueckgaengig stellt die Fassung VOR dieser Runde wieder her (bei nachgespielten Runden die Fassung, auf die
// nachgespielt wurde). Erlaubt nur an der Runde, deren Fassung die neueste ist - sonst drehte es fremde Arbeit
// zurueck. Liefert deren id oder null.
export function rueckgaengigFuer(verlauf: ChatEintrag[], neueste: number | null): string | null {
  if (neueste === null) return null;
  const e = verlauf.find((x) => x.art === 'chat' && x.status === 'fertig' && x.fassung_nachher === neueste);
  return e ? e.id : null;
}

// Alle Chat-Runden, die laufen oder auf einen Platz warten, in Verlaufsreihenfolge.
export function laufendeRunden(chat: Pick<ChatStand, 'verlauf'> | null): ChatEintrag[] {
  return (chat?.verlauf ?? []).filter((e) => e.art === 'chat' && RUNDE.includes(e.status));
}

export function exportLaeuft(chat: Pick<ChatStand, 'verlauf'> | null): boolean {
  return (chat?.verlauf ?? []).some((e) => e.art === 'export' && LAEUFT.includes(e.status));
}

// Uebergang bis Task 9: die erste laufende Runde (Stopp in der Kopfzeile).
export function laufenderChat(chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): ChatEintrag | null {
  if (!chat?.laeuft) return null;
  return laufendeRunden(chat).find((e) => e.status !== 'wartet') ?? null;
}

// Der Stopp-Dialog gilt nur fuer die Runde, fuer die er geoeffnet wurde: endet sie, geht er zu.
export function stoppDialogOffen(stoppFuer: string | null, chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): boolean {
  return stoppFuer !== null && laufendeRunden(chat).some((e) => e.id === stoppFuer && e.status !== 'wartet');
}

// Text der Sperre, solange eine Runde laeuft oder wartet (null = frei).
export function sperrText(chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): string | null {
  if (!chat?.laeuft) return null;
  return exportLaeuft(chat) ? 'Newsletter-Bilder werden gerechnet …' : 'Agent arbeitet …';
}
```

`editor/src/pultZustand.ts`:
- Imports aus `./chat`: `vormerken`, `vormerkungLoeschen`, `vormerkungStarten` entfernen, `exportLaeuft` und `laufendeRunden` ergänzen.
- `TPult`: `vorgemerktChips` entfernen (mit Kommentar), `chatText: string;` ergänzen (Kommentar: „Text im Chat-Eingabefeld (überlebt das Neuladen nach einer Agenten-Fassung)“); Startwerte `chatText: ''`.
- In `neueFassungLaden` im `try` vor `window.location.reload()`:
```ts
    const { chatText } = pultStore.getState();
    if (chatText.trim()) sessionStorage.setItem(CHAT_ENTWURF, chatText);
```
  mit `const CHAT_ENTWURF = 'vibemind-chat-entwurf';` neben `FENSTER`, und darunter:
```ts
export function chatTextSetzen(text: string) {
  pultStore.setState({ chatText: text });
}

// Nach dem Neuladen: ein angefangener Chat-Text steht wieder im Eingabefeld.
export function chatEntwurfWiederholen() {
  try {
    const text = sessionStorage.getItem(CHAT_ENTWURF);
    if (text === null) return;
    sessionStorage.removeItem(CHAT_ENTWURF);
    pultStore.setState({ chatText: text });
  } catch {
    /* kein Merkzettel */
  }
}
```
- `chatAbfragen`: `vorgemerkteChipsPruefen(neu);` löschen; Takt `if (jetzt?.laeuft) chatTakt = setTimeout(holen, laufendeRunden(jetzt).length > 0 ? CHAT_TAKT_MS : EXPORT_TAKT_MS);`.
- `auftragEintragen` ersetzen:
```ts
function auftragEintragen(id: string, nachricht: string, status: 'offen' | 'wartet') {
  const eintrag: ChatEintrag = {
    id, art: 'chat', nachricht, antwort: '', status, hinweise: [], ergebnis: {},
    fassung_vorher: status === 'wartet' ? null : pultStore.getState().basis, fassung_nachher: null,
    erstellt_am: new Date().toISOString(), denken: '', schritte: [], schritt: '', schritt_nr: 0, stopp: null,
    bild_hinweise: [],
  };
  const alt = pultStore.getState().chat;
  const verlauf = (alt?.verlauf ?? []).filter((e) => e.id !== id);
  pultStore.setState({ chat: { live: null, neueste: null, ...alt, laeuft: true, verlauf: [...verlauf, eintrag] } });
  chatAbfragen();
}
```
- `chatAbschicken`: `if (chat?.laeuft) return 'Der Assistent arbeitet gerade';` ersetzen durch
```ts
  // Mehrere Runden duerfen laufen (Spec 2026-10-09 §2); nur ein Newsletter-Export am PC laeuft allein.
  if (exportLaeuft(chat)) return 'Der Assistent arbeitet gerade';
```
  den Vormerk-Zweig (`if (pultStore.getState().chat?.vorgemerkt) return vormerkungSetzen(…)`) löschen und `auftragEintragen(r.auftrag, nachricht);` durch `auftragEintragen(r.auftrag, nachricht, r.status);` ersetzen.
- Löschen: `chatVormerken`, `vormerkungSetzen`, `vorgemerkteChipsZurueck`, `vorgemerkteChipsPruefen`, `vormerkungLoeschenAuftrag`, `vormerkungStartenAuftrag`.

`editor/src/main.tsx`: Import um `chatEntwurfWiederholen` ergänzen und nach `fensterWiederOeffnen();` `chatEntwurfWiederholen();` aufrufen.

`editor/src/App/Chat/ChatLeiste.tsx` (Übergang; Task 9 baut die Einträge um):
- Imports: `AttachFileRounded`, `ScheduleRounded` und `Vorgemerkt` entfernen; aus `../../pultZustand` `chatVormerken`, `vorgemerkteChipsZurueck`, `vormerkungLoeschenAuftrag`, `vormerkungStartenAuftrag` entfernen, `chatTextSetzen` ergänzen; aus `../../chat` `exportLaeuft` ergänzen.
- `mehrzahl` und `VorgemerktKarte` löschen.
- `const vorgemerkt = chat?.vorgemerkt ?? null;` löschen; `const [text, setText] = useState('');` ersetzen durch `const text = pultStore((p) => p.chatText); const setText = chatTextSetzen;`; im Scroll-`useEffect` `vorgemerkt?.id, vorgemerkt?.nachricht` aus den Abhängigkeiten nehmen.
- `sendSperre`:
```ts
  // Mehrere Runden duerfen laufen; nur ein Newsletter-Export am PC sperrt das Senden.
  const sendSperre =
    sperre ?? (exportLaeuft(chat) ? 'Der Assistent arbeitet gerade' : hochladenLaeuft ? 'Erst warten, bis die Anhänge hochgeladen sind' : null);
```
- `senden`: `const grund = await chatAbschicken(text.trim(), kontext);`
- `rueckId: rueckgaengigFuer(verlauf, chat?.neueste ?? null),`
- `bearbeiten` und die Zeile `{vorgemerkt && <VorgemerktKarte … />}` löschen.
- Der Senden-Knopf: den ganzen Ausdruck `{chatLauf ? (<Tooltip … Vormerken …>) : (<Tooltip title={sendSperre ?? 'Senden (Enter)'}> … </Tooltip>)}` durch den `Senden`-Zweig allein ersetzen; Platzhalter `placeholder="Nachricht an den Assistenten"`; Fußzeile `<span>Enter senden · Shift+Enter neue Zeile</span>`.

- [ ] **Step 4: Tests, Typen, Bundle**

Run:
```
cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run; npx tsc --noEmit; npm run build
cd ../sales-mcp; $env:SALES_DB_URL = 'postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA = 'sales_test'
& E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/test_editor_seite.py tests/test_editor_paket.py -q
```
Expected: alles grün.

- [ ] **Step 5: Commit (SC)**

```
git add sales-mcp/ui_editor.py sales-mcp/tests/test_editor_seite.py sales-mcp/tests/test_editor_paket.py editor/src/pult.ts editor/src/chat.ts editor/src/pultZustand.ts editor/src/main.tsx editor/src/App/Chat/ChatLeiste.tsx editor/src/pultZustand.runden.test.ts editor/src/chat.test.ts editor/src/pultZustand.chat.test.ts editor/src/pultZustand.kontext.test.ts editor/src/pultZustand.live.test.ts sales-mcp/static/editor
git commit -m "feat(editor): Senden statt Vormerken, mehrere Runden im Zustand, Entwurf ueberlebt das Neuladen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Editor-Oberfläche — eigener Eintrag je Runde, Warteschlange, Hinweise

**Files:**
- Create: `editor/src/App/Chat/Runde.tsx`, `editor/src/App/Chat/Runde.test.tsx`
- Modify: `editor/src/App/Chat/ChatLeiste.tsx` (ganz, s. u.), `editor/src/App/Chat/StoppDialog.tsx` (Prop `auftrag`), `editor/src/App/Chat/Sperre.tsx:36-45` (`useLiveZeile`), `editor/src/App/Chat/Gedanken.tsx:64` (Typ), `editor/src/live.ts:56` (Typ von `schrittText`), `editor/src/chat.ts` (`laufenderChat` löschen), `editor/src/pultZustand.ts` (`chatStoppen`), `editor/src/chat.test.ts` (`describe('laufenderChat')` → `laufendeRunden`), `editor/src/pultZustand.live.test.ts` (`describe('Stopp')`)
- Modify: `sales-mcp/tests/test_editor_paket.py`, Bundle

**Interfaces:**
- Consumes (Task 8): `ChatEintrag` mit `schritt`, `schritt_nr`, `stopp`, `bild_hinweise`; `laufendeRunden`, `exportLaeuft`, `rueckgaengigFuer`, `stoppDialogOffen`.
- Produces:
  - `Runde.tsx`: `WARTET_TEXT = 'wartet auf freien Platz'`, `rundenZeile(e: ChatEintrag, getrennt: boolean): string`, `type RundenAktionen`, `Eintrag({ e, a })`.
  - `chatStoppen(art: StoppArt, auftrag: string): Promise<string | null>` (Pflicht-ID).
  - `StoppDialog({ offen, auftrag, onClose })`.
  - `schrittText(live: Pick<ChatLive, 'schritt' | 'schritt_nr'> | null)`, `GedankenLive({ live: Pick<ChatLive, 'denken' | 'schritte'>, … })`.

- [ ] **Step 1: Tests schreiben**

`Runde.test.tsx`:
```tsx
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ChatEintrag, rueckgaengigFuer } from '../../chat';

import { Eintrag, rundenZeile, RundenAktionen, WARTET_TEXT } from './Runde';

function e(teil: Partial<ChatEintrag>): ChatEintrag {
  return { id: 'a', art: 'chat', nachricht: 'Bitte', antwort: '', status: 'in_arbeit', hinweise: [], ergebnis: {},
    fassung_vorher: 3, fassung_nachher: null, erstellt_am: 't', denken: '', schritte: [], schritt: '', schritt_nr: 0,
    stopp: null, bild_hinweise: [], ...teil };
}

const a = (teil: Partial<RundenAktionen> = {}): RundenAktionen => ({
  rueckSperre: null, rueckId: null, rueckLaeuft: null, fehlerAn: null, onRueckgaengig: () => {}, onExport: () => {},
  onStopp: () => {}, nurLesen: false, getrennt: false, gedankenSichtbar: true, gedankenUmschalten: () => {}, ...teil,
});
const html = (x: ChatEintrag, ak: RundenAktionen = a()) => renderToStaticMarkup(<Eintrag e={x} a={ak} />);

describe('Runden im Verlauf', () => {
  it('mehrere laufende Einträge: jeder mit eigener Schrittzeile, eigenen Gedanken und eigenem Stopp', () => {
    const eins = html(e({ id: 'r1', nachricht: 'Titel kürzer', schritt: 'Titel kürzen', schritt_nr: 2, denken: 'Denke an den Titel' }));
    const zwei = html(e({ id: 'r2', nachricht: 'Farbe wärmer', schritt: 'Farbe setzen', schritt_nr: 1, denken: 'Denke an die Farbe' }));
    expect(eins).toContain('Schritt 2 · Titel kürzen');
    expect(eins).toContain('Denke an den Titel');
    expect(eins).not.toContain('Denke an die Farbe');
    expect(eins).toContain('aria-label="Stopp: Titel kürzer"');
    expect(zwei).toContain('Schritt 1 · Farbe setzen');
    expect(zwei).toContain('aria-label="Stopp: Farbe wärmer"');
  });

  it('„wartet auf freien Platz“ mit eigenem Knopf, ohne Gedanken', () => {
    const w = html(e({ status: 'wartet', nachricht: 'Vierte Bitte' }));
    expect(w).toContain(WARTET_TEXT);
    expect(w).toContain('aria-label="Stopp: Vierte Bitte"');
    expect(w).not.toContain('Denkt nach');
  });

  it('Schrittzeile: gestoppt, getrennt, noch ohne Schritt', () => {
    expect(rundenZeile(e({ stopp: 'behalten' }), false)).toBe('Wird gestoppt …');
    expect(rundenZeile(e({}), true)).toBe('Verbindung …');
    expect(rundenZeile(e({ status: 'offen' }), false)).toBe('Wartet auf den Assistenten …');
    expect(rundenZeile(e({}), false)).toBe('Agent denkt nach …');
  });

  it('Rückgängig nur an der Runde mit der neuesten Fassung', () => {
    const spaet = e({ id: 'spaet', status: 'fertig', fassung_nachher: 7 });
    const frueh = e({ id: 'frueh', status: 'fertig', fassung_nachher: 6 });
    const ak = a({ rueckId: rueckgaengigFuer([spaet, frueh], 7) });
    expect(html(spaet, ak)).toContain('Rückgängig');
    expect(html(frueh, ak)).not.toContain('Rückgängig');
    expect(html(frueh, ak)).toContain('Spätere Änderungen vorhanden');
  });

  it('übersprungene Änderungen und gescheiterte Bildaufträge stehen als Hinweise am Eintrag', () => {
    const x = html(e({ status: 'fertig', antwort: 'Erledigt.', hinweise: ['Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: Titel'],
      bild_hinweise: ['Bild für held nicht erzeugt: Zeitüberschreitung'] }));
    expect(x).toContain('Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: Titel');
    expect(x).toContain('Bild für held nicht erzeugt: Zeitüberschreitung');
  });

  it('nur lesend: kein Stopp', () => {
    expect(html(e({ nachricht: 'X' }), a({ nurLesen: true }))).not.toContain('Stopp: X');
  });
});
```

`chat.test.ts`: `describe('laufenderChat', …)` ersetzen:
```ts
describe('laufendeRunden', () => {
  it('alle Chat-Runden offen, in Arbeit und wartend, nie ein Export', () => {
    const v = [eintrag({ id: 'a', status: 'fertig' }), eintrag({ id: 'b', status: 'in_arbeit' }), eintrag({ id: 'c', status: 'wartet' }),
      eintrag({ id: 'x', art: 'export', status: 'in_arbeit' }), eintrag({ id: 'd', status: 'offen' })];
    expect(laufendeRunden({ verlauf: v }).map((e) => e.id)).toEqual(['b', 'c', 'd']);
  });
});
```
(Import `laufenderChat` durch `laufendeRunden` ersetzen.) In `describe('stoppDialogOffen')` ergänzen:
```ts
  it('eine wartende Runde oeffnet keinen Dialog (sie endet ohne Nachfrage)', () => {
    expect(stoppDialogOffen('w', { laeuft: true, verlauf: [eintrag({ id: 'w', status: 'wartet' })] })).toBe(false);
  });
```

`pultZustand.live.test.ts`, `describe('Stopp')`: Aufrufe `chatStoppen('behalten')` → `chatStoppen('behalten', 'a1')`; der Test „ruft chat_stopp_url mit art und dem laufenden Auftrag …“ erwartet weiterhin den Body `{ art: 'behalten', auftrag: 'a1' }`.

`sales-mcp/tests/test_editor_paket.py`:
```python
def test_paket_kennt_parallele_runden():
    # 2026-10-09 parallele Runden (Task 9): Warteschlange, mehrere Runden in der Sperrzeile
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    for s in ("wartet auf freien Platz", "Runden laufen", "Aus der Warteschlange nehmen"):
        assert s in text, s
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run src/App/Chat/Runde.test.tsx src/chat.test.ts`
Expected: FAIL (`./Runde` fehlt, `laufendeRunden`-Erwartung).

- [ ] **Step 3: Implementieren**

`live.ts`: `export function schrittText(live: Pick<ChatLive, 'schritt' | 'schritt_nr'> | null): string | null {`.

`Gedanken.tsx`: `export function GedankenLive({ live, sichtbar, umschalten }: { live: Pick<ChatLive, 'denken' | 'schritte'>; sichtbar: boolean; umschalten: () => void }) {`.

`Runde.tsx`:
```tsx
// Ein Eintrag im Chat-Verlauf (Spec 2026-10-09-editor-parallele-runden §2): jede Runde mit eigener Schrittzeile,
// eigenen Gedanken und eigenem Stopp; wartende Runden "wartet auf freien Platz"; Hinweise (uebersprungene
// Aenderungen, gescheiterte Bilder) am Eintrag. Rueckgaengig nur an der Runde mit der neuesten Fassung.
import React from 'react';

import { ErrorOutlineRounded, HourglassEmptyRounded, IosShareRounded, PhotoLibraryOutlined, StopRounded, UndoRounded } from '@mui/icons-material';
import { Box, Button, CircularProgress, Tooltip } from '@mui/material';

import { ChatEintrag, ExportAuswahl, exportVorschlag } from '../../chat';
import { schrittText } from '../../live';
import { FARBE } from '../Gestaltung/gestaltungStil';

import { GedankenAufklapp, GedankenLive } from './Gedanken';
import { Punkte } from './Sperre';

export const WARTET_TEXT = 'wartet auf freien Platz';

export type RundenAktionen = {
  rueckSperre: string | null;
  // Die eine Runde, die sich rueckgaengig machen laesst (rueckgaengigFuer).
  rueckId: string | null;
  rueckLaeuft: string | null;
  // Fehler an einem Eintrag (Rueckgaengig oder Stopp einer wartenden Runde).
  fehlerAn: { id: string; grund: string } | null;
  onRueckgaengig: (id: string) => void;
  onExport: (v: ExportAuswahl) => void;
  onStopp: (e: ChatEintrag) => void;
  nurLesen: boolean;
  getrennt: boolean;
  gedankenSichtbar: boolean;
  gedankenUmschalten: () => void;
};

const laeuftNoch = (e: ChatEintrag) => e.status === 'offen' || e.status === 'in_arbeit' || e.status === 'wartet';

export function rundenZeile(e: ChatEintrag, getrennt: boolean): string {
  if (e.status === 'wartet') return WARTET_TEXT;
  if (getrennt) return 'Verbindung …';
  if (e.stopp) return 'Wird gestoppt …';
  return schrittText(e) ?? (e.status === 'offen' ? 'Wartet auf den Assistenten …' : 'Agent denkt nach …');
}

const kleinerKnopf = { height: 24, px: 1, fontSize: 12, fontWeight: 500, color: FARBE.gedaempft, minWidth: 0, '&:hover': { color: FARBE.text, bgcolor: FARBE.hover } } as const;

function Blase({ ich, fehler, children }: { ich: boolean; fehler?: boolean; children: React.ReactNode }) {
  return (
    <Box
      sx={{
        alignSelf: ich ? 'flex-end' : 'flex-start', maxWidth: '88%', px: 1.5, py: 1,
        borderRadius: ich ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
        bgcolor: ich ? FARBE.akzent : FARBE.panel, color: ich ? '#ffffff' : fehler ? FARBE.fehler : FARBE.text,
        border: ich ? 'none' : `1px solid ${FARBE.linie}`, fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      }}
    >
      {children}
    </Box>
  );
}

// Laufende Runde: Punkte, Schrittzeile und eine ruhig wandernde Linie; wartend: Sanduhr, ohne Linie.
function LaufBlase({ text, wartet }: { text: string; wartet: boolean }) {
  return (
    <Box
      sx={{
        position: 'relative', overflow: 'hidden', minWidth: 0, display: 'flex', alignItems: 'center', gap: 1, px: 1.5,
        minHeight: 36, py: 0.75, borderRadius: '12px 12px 12px 4px', bgcolor: FARBE.panel,
        border: `1px ${wartet ? 'dashed' : 'solid'} ${FARBE.linie}`,
      }}
    >
      {wartet ? <HourglassEmptyRounded sx={{ fontSize: 14, color: FARBE.gedaempft }} /> : <Punkte />}
      <Box
        key={text}
        component="span"
        sx={{
          fontSize: 12, lineHeight: 1.4, color: wartet ? FARBE.gedaempft : FARBE.text, fontVariantNumeric: 'tabular-nums',
          '@keyframes schrittAuf': { from: { opacity: 0, transform: 'translateY(3px)' }, to: { opacity: 1, transform: 'none' } },
          animation: 'schrittAuf 220ms cubic-bezier(0.2, 0, 0, 1)', '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      >
        {text}
      </Box>
      {!wartet && (
        <Box
          aria-hidden="true"
          sx={{
            position: 'absolute', left: 0, right: 0, bottom: 0, height: '2px',
            background: `linear-gradient(90deg, transparent 0%, ${FARBE.akzent} 50%, transparent 100%)`,
            backgroundSize: '50% 100%', backgroundRepeat: 'no-repeat', opacity: 0.7,
            '@keyframes schrittLinie': { from: { backgroundPosition: '-100% 0' }, to: { backgroundPosition: '200% 0' } },
            animation: 'schrittLinie 1.8s ease-in-out infinite',
            '@media (prefers-reduced-motion: reduce)': { animation: 'none', opacity: 0.35, backgroundSize: '100% 100%' },
          }}
        />
      )}
    </Box>
  );
}

export function Eintrag({ e, a }: { e: ChatEintrag; a: RundenAktionen }) {
  if (e.art === 'export') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, fontSize: 12, color: e.status === 'fehler' ? FARBE.fehler : FARBE.gedaempft, textAlign: 'center', px: 2 }}>
        <PhotoLibraryOutlined sx={{ fontSize: 14, flexShrink: 0 }} />
        {laeuftNoch(e) ? (
          <>
            <span>Newsletter-Bilder werden am PC gerechnet</span>
            <Punkte />
          </>
        ) : (
          <span>{e.antwort || (e.status === 'fertig' ? 'Export fertig' : 'Export fehlgeschlagen')}</span>
        )}
      </Box>
    );
  }
  const vorschlag = e.status === 'fertig' ? exportVorschlag(e) : null;
  const mitFassung = e.status === 'fertig' && e.fassung_nachher !== null;
  const kannZurueck = mitFassung && a.rueckId === e.id;
  const hinweise = [...e.hinweise, ...e.bild_hinweise];
  const wartet = e.status === 'wartet';
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {e.nachricht && <Blase ich>{e.nachricht}</Blase>}
      {laeuftNoch(e) ? (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, alignSelf: 'flex-start', maxWidth: '100%' }}>
            <LaufBlase text={rundenZeile(e, a.getrennt)} wartet={wartet} />
            {!a.nurLesen && (
              <Tooltip title={wartet ? 'Aus der Warteschlange nehmen' : e.stopp ? 'Wird gestoppt …' : 'Diese Runde anhalten'}>
                <span>
                  <Button
                    size="small"
                    aria-label={`Stopp: ${e.nachricht}`}
                    disabled={e.stopp !== null}
                    onClick={() => a.onStopp(e)}
                    startIcon={<StopRounded sx={{ fontSize: 14 }} />}
                    sx={kleinerKnopf}
                  >
                    Stopp
                  </Button>
                </span>
              </Tooltip>
            )}
          </Box>
          {!wartet && <GedankenLive live={e} sichtbar={a.gedankenSichtbar} umschalten={a.gedankenUmschalten} />}
        </>
      ) : (
        <Blase ich={false} fehler={e.status === 'fehler'}>
          {e.status === 'fehler' && <ErrorOutlineRounded sx={{ fontSize: 14, mr: 0.75, verticalAlign: '-2px' }} />}
          {e.antwort || (e.status === 'fehler' ? 'Das hat nicht geklappt.' : 'Erledigt.')}
          {hinweise.length > 0 && (
            <Box component="ul" sx={{ m: 0, mt: 1, pl: 2, color: FARBE.gedaempft, fontSize: 12, lineHeight: 1.5, '& li::marker': { color: FARBE.warnung } }}>
              {hinweise.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </Box>
          )}
          <GedankenAufklapp denken={e.denken} schritte={e.schritte} />
        </Blase>
      )}
      {(mitFassung || vorschlag) && (
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5, mt: -0.5 }}>
          {e.fassung_nachher !== null && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, mr: 0.5, fontVariantNumeric: 'tabular-nums' }}>
              Fassung {e.fassung_nachher}
              {e.ergebnis.notiz ? ` · ${e.ergebnis.notiz}` : ''}
            </Box>
          )}
          {mitFassung && !kannZurueck && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, fontStyle: 'italic' }}>
              · Spätere Änderungen vorhanden
            </Box>
          )}
          {kannZurueck && (
            <Tooltip title={a.rueckSperre ?? 'Legt die Fassung davor als neue Fassung an'}>
              <span>
                <Button
                  size="small"
                  disabled={a.rueckSperre !== null || a.rueckLaeuft !== null}
                  onClick={() => a.onRueckgaengig(e.id)}
                  startIcon={a.rueckLaeuft === e.id ? <CircularProgress size={12} color="inherit" /> : <UndoRounded sx={{ fontSize: 14 }} />}
                  sx={kleinerKnopf}
                >
                  Rückgängig
                </Button>
              </span>
            </Tooltip>
          )}
          {vorschlag && !a.nurLesen && (
            <Button size="small" onClick={() => a.onExport(vorschlag)} startIcon={<IosShareRounded sx={{ fontSize: 14 }} />} sx={{ ...kleinerKnopf, color: FARBE.akzent }}>
              Exportieren…
            </Button>
          )}
        </Box>
      )}
      {a.fehlerAn?.id === e.id && <Box sx={{ fontSize: 12, color: FARBE.fehler }}>{a.fehlerAn.grund}</Box>}
    </Box>
  );
}
```

`ChatLeiste.tsx` vollständig ersetzen (Breite/`EINGABE_ZEILEN` aus Task 7, Zustand aus Task 8):
```tsx
// Chat mit dem Gestaltungs-Agenten (Spec 2026-10-02 §4): im Newsletter-Editor in der rechten Seitenleiste, im
// Gestaltungsfenster unter den Eigenschaften. Aussehen aus gestaltungStil: Betreiber rechts auf der Akzentflaeche,
// Agent links auf der Panelflaeche, Eingabe unten fest.
// Mehrere Runden (Spec 2026-10-09-editor-parallele-runden §2): "Senden" immer; jede Runde ist ein eigener Eintrag
// (Runde.tsx) mit eigenem Stopp; der Stopp-Dialog gilt der Runde, fuer die er geoeffnet wurde.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ArrowUpwardRounded, AutoAwesomeRounded, ErrorOutlineRounded, ExpandMoreRounded, InfoOutlined } from '@mui/icons-material';
import { Box, ButtonBase, CircularProgress, IconButton, InputBase, ThemeProvider, Tooltip } from '@mui/material';

import { ChatEintrag, ChatKontext, ExportAuswahl, exportLaeuft, rueckgaengigFuer, stoppDialogOffen } from '../../chat';
import { sendenErlaubt } from '../../chatKontext';
import { chatAbschicken, chatHinweisWeg, chatRueckgaengig, chatStoppen, chatTextSetzen, HINWEIS_OFFEN, pultStore } from '../../pultZustand';
import { FARBE, FOKUS, gestaltungThema, uebergang, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import { useAnhangAblage } from './AnhangAblage';
import { useGedankenSichtbar } from './Gedanken';
import KontextChips from './KontextChips';
import { Eintrag, RundenAktionen } from './Runde';
import { LIEGT_ZUR_FREIGABE, useAgentArbeitet, useNurLesen } from './Sperre';
import StoppDialog from './StoppDialog';

export const NACHRICHT_MAX = 2000;
export const EINGABE_ZEILEN = 8;
const KOPF = 40;

export type ChatLeisteProps = {
  kontext: ChatKontext;
  // Grund, warum gerade nichts an den Agenten gehen kann (z. B. ungesicherte Flaeche).
  sperre?: string | null;
  // Hoehe des aufgeklappten Chats (Verlauf + Eingabe).
  hoehe: number | string;
  vorschlaege?: string[];
  onExport: (v: ExportAuswahl) => void;
};

export default function ChatLeiste({ kontext, sperre: sperreVon = null, hoehe, vorschlaege = [], onExport }: ChatLeisteProps) {
  const thema = useMemo(gestaltungThema, []);
  const chat = pultStore((p) => p.chat);
  const getrennt = pultStore((p) => p.chatGetrennt);
  const [gedankenSichtbar, gedankenUmschalten] = useGedankenSichtbar();
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const hinweisOffen = pultStore((p) => p.hinweisOffen);
  const text = pultStore((p) => p.chatText);
  const arbeitet = useAgentArbeitet();
  const nurLesen = useNurLesen();
  const sperre = sperreVon ?? (nurLesen ? LIEGT_ZUR_FREIGABE : null);
  // Stopp-Dialog: id der Runde, fuer die er geoeffnet wurde (null = zu). Endet sie, geht er zu.
  const [stoppFuer, setStoppFuer] = useState<string | null>(null);
  const dialogOffen = stoppDialogOffen(stoppFuer, chat);
  useEffect(() => {
    if (stoppFuer !== null && !dialogOffen) setStoppFuer(null);
  }, [stoppFuer, dialogOffen]);
  const eingabe = useRef<HTMLTextAreaElement>(null);
  const [offen, setOffen] = useState(true);
  const [sendet, setSendet] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [rueckLaeuft, setRueckLaeuft] = useState<string | null>(null);
  const [fehlerAn, setFehlerAn] = useState<{ id: string; grund: string } | null>(null);
  const liste = useRef<HTMLDivElement>(null);
  const hinweis = pultStore((p) => p.chatHinweis);
  const hochladenLaeuft = pultStore((p) => !sendenErlaubt(p.chatAnhaenge));
  const verlauf = chat?.verlauf ?? [];
  const letzter = verlauf[verlauf.length - 1];

  // Neues unten: beim Oeffnen, bei neuen Eintraegen und wenn eine Antwort kommt.
  useEffect(() => {
    const el = liste.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [offen, verlauf.length, letzter?.status, letzter?.schritt_nr]);

  // Mehrere Runden duerfen laufen; nur ein Newsletter-Export am PC sperrt das Senden.
  const sendSperre =
    sperre ?? (exportLaeuft(chat) ? 'Der Assistent arbeitet gerade' : hochladenLaeuft ? 'Erst warten, bis die Anhänge hochgeladen sind' : null);
  const kannSenden = text.trim() !== '' && sendSperre === null && !sendet;

  const { ablage, ablageFlaeche, bueroklammer, beimEinfuegen } = useAnhangAblage({ onGrund: setFehler, onAngehaengt: () => setOffen(true) });

  const senden = async () => {
    if (!kannSenden) return;
    setSendet(true);
    setFehler(null);
    const grund = await chatAbschicken(text.trim(), kontext);
    setSendet(false);
    if (grund) setFehler(grund);
    else chatTextSetzen('');
  };

  const aktionen: RundenAktionen = {
    rueckSperre:
      sperre ??
      (arbeitet ? 'Der Assistent arbeitet gerade' : hinweisOffen ? HINWEIS_OFFEN : ungespeichert ? 'Erst speichern – sonst gingen deine Änderungen verloren' : null),
    rueckId: rueckgaengigFuer(verlauf, chat?.neueste ?? null),
    rueckLaeuft,
    fehlerAn,
    onRueckgaengig: async (id) => {
      setRueckLaeuft(id);
      setFehlerAn(null);
      const grund = await chatRueckgaengig(id);
      setRueckLaeuft(null);
      if (grund) setFehlerAn({ id, grund });
    },
    onExport,
    onStopp: (e: ChatEintrag) => {
      if (e.status !== 'wartet') {
        setStoppFuer(e.id);
        return;
      }
      setFehlerAn(null);
      void chatStoppen('verwerfen', e.id).then((grund) => {
        if (grund) setFehlerAn({ id: e.id, grund });
      });
    },
    nurLesen,
    getrennt,
    gedankenSichtbar,
    gedankenUmschalten,
  };

  return (
    <ThemeProvider theme={thema}>
      <Box {...ablage} sx={{ position: 'relative', display: 'flex', flexDirection: 'column', bgcolor: FARBE.panel, color: FARBE.text, fontFamily: UI_SCHRIFT, minHeight: 0 }}>
        {ablageFlaeche}
        <ButtonBase
          onClick={() => setOffen((o) => !o)}
          aria-expanded={offen}
          sx={{ flexShrink: 0, height: KOPF, px: 2, gap: 1, justifyContent: 'flex-start', fontFamily: UI_SCHRIFT, transition: uebergang('background-color'), '&:hover': { bgcolor: FARBE.hover }, '&.Mui-focusVisible': FOKUS }}
        >
          <AutoAwesomeRounded sx={{ fontSize: 16, color: FARBE.akzent }} />
          <Box component="span" sx={{ fontSize: 13, fontWeight: 600 }}>
            Assistent
          </Box>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, fontSize: 12, color: FARBE.gedaempft, ml: 0.5 }}>
            <Box component="span" sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: arbeitet ? FARBE.akzent : FARBE.linie, transition: uebergang('background-color') }} />
            {arbeitet ? 'arbeitet' : 'bereit'}
          </Box>
          <ExpandMoreRounded sx={{ ml: 'auto', fontSize: 18, color: FARBE.gedaempft, transform: offen ? 'none' : 'rotate(180deg)', transition: uebergang('transform') }} />
        </ButtonBase>
        <StoppDialog offen={dialogOffen} auftrag={stoppFuer} onClose={() => setStoppFuer(null)} />

        {offen && (
          <Box sx={{ height: hoehe, display: 'flex', flexDirection: 'column', minHeight: 0, borderTop: `1px solid ${FARBE.linie}` }}>
            <Box ref={liste} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', bgcolor: FARBE.geruest, p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {verlauf.length === 0 ? (
                <Box sx={{ m: 'auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5, maxWidth: 260 }}>
                  <AutoAwesomeRounded sx={{ fontSize: 24, color: FARBE.akzent }} />
                  <Box sx={{ fontSize: 13, color: FARBE.gedaempft, lineHeight: 1.5 }}>Sag dem Assistenten, was er gestalten oder ändern soll.</Box>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 1 }}>
                    {vorschlaege.map((v) => (
                      <ButtonBase
                        key={v}
                        onClick={() => chatTextSetzen(v)}
                        sx={{ px: 1.25, height: 28, borderRadius: '14px', border: `1px solid ${FARBE.linie}`, fontSize: 12, color: FARBE.text, fontFamily: UI_SCHRIFT, transition: uebergang('background-color', 'border-color'), '&:hover': { bgcolor: FARBE.hover, borderColor: FARBE.gedaempft }, '&.Mui-focusVisible': FOKUS }}
                      >
                        {v}
                      </ButtonBase>
                    ))}
                  </Box>
                </Box>
              ) : (
                verlauf.map((e) => <Eintrag key={e.id} e={e} a={aktionen} />)
              )}
            </Box>

            <Box sx={{ flexShrink: 0, p: 1, borderTop: `1px solid ${FARBE.linie}` }}>
              {(fehler || hinweis || sperre) && (
                <Box role={fehler || hinweis ? 'status' : undefined} sx={{ display: 'flex', gap: 0.75, px: 0.5, pb: 1, fontSize: 12, lineHeight: 1.4, color: fehler ? FARBE.fehler : FARBE.gedaempft }}>
                  {fehler && <ErrorOutlineRounded sx={{ fontSize: 14, mt: '1px' }} />}
                  {!fehler && hinweis && <InfoOutlined sx={{ fontSize: 14, mt: '1px', color: FARBE.warnung }} />}
                  <span>{fehler ?? hinweis ?? sperre}</span>
                </Box>
              )}
              <KontextChips />
              <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, pl: 1.5, pr: 0.5, py: 0.5, borderRadius: '8px', bgcolor: FARBE.feld, border: '1px solid transparent', transition: uebergang('border-color'), '&:focus-within': { borderColor: FARBE.akzent } }}>
                {bueroklammer}
                <InputBase
                  multiline
                  disabled={nurLesen}
                  maxRows={EINGABE_ZEILEN}
                  value={text}
                  inputRef={eingabe}
                  placeholder="Nachricht an den Assistenten"
                  onChange={(ev) => {
                    chatTextSetzen(ev.target.value.slice(0, NACHRICHT_MAX));
                    chatHinweisWeg();
                  }}
                  onPaste={beimEinfuegen}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter' && !ev.shiftKey && !ev.nativeEvent.isComposing) {
                      ev.preventDefault();
                      void senden();
                    }
                  }}
                  inputProps={{ 'aria-label': 'Nachricht an den Assistenten', maxLength: NACHRICHT_MAX }}
                  sx={{ flex: 1, py: 0.5, fontSize: 13, lineHeight: 1.5, color: FARBE.text, '& textarea::placeholder': { color: FARBE.gedaempft, opacity: 1 } }}
                />
                <Tooltip title={sendSperre ?? 'Senden (Enter)'}>
                  <span>
                    <IconButton
                      aria-label="Senden"
                      disabled={!kannSenden}
                      onClick={() => void senden()}
                      sx={{ width: 28, height: 28, mb: '2px', bgcolor: FARBE.akzent, color: '#ffffff', '&:hover': { bgcolor: '#4a7bf0', color: '#ffffff' }, '&.Mui-disabled': { bgcolor: FARBE.linie, color: FARBE.gedaempft } }}
                    >
                      {sendet ? <CircularProgress size={14} color="inherit" /> : <ArrowUpwardRounded sx={{ fontSize: 16 }} />}
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', px: 0.5, pt: 0.5, fontSize: 11, color: FARBE.gedaempft }}>
                <span>Enter senden · Shift+Enter neue Zeile</span>
                {text.length > NACHRICHT_MAX - 200 && <span style={{ fontVariantNumeric: 'tabular-nums' }}>{text.length} / {NACHRICHT_MAX}</span>}
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  );
}
```

`StoppDialog.tsx`: Signatur `export default function StoppDialog({ offen, auftrag, onClose }: { offen: boolean; auftrag: string | null; onClose: () => void })`, `{offen && auftrag && <Inhalt auftrag={auftrag} onClose={onClose} />}`; in `Inhalt({ auftrag, onClose }: { auftrag: string; onClose: () => void })`:
```tsx
  const zeile = pultStore((p) => schrittText(p.chat?.verlauf.find((e) => e.id === auftrag) ?? null));
  …
    const grund = await chatStoppen(art, auftrag);
```

`Sperre.tsx`, `useLiveZeile` ersetzen (Import `laufenderChat` → `laufendeRunden`):
```ts
// Schrittzeile der Sperrschicht (null = keine Chat-Runde laeuft, z. B. Export). Bei mehreren Runden die Anzahl.
export function useLiveZeile(): string | null {
  return pultStore((p) => {
    const runden = laufendeRunden(p.chat).filter((e) => e.status !== 'wartet');
    if (runden.length === 0) return null;
    if (p.chatGetrennt) return 'Verbindung …';
    if (runden.length > 1) return `${runden.length} Runden laufen …`;
    const r = runden[0];
    if (r.stopp) return 'Wird gestoppt …';
    return schrittText(r) ?? (r.status === 'offen' ? 'Wartet auf den Assistenten …' : 'Agent denkt nach …');
  });
}
```

`pultZustand.ts`, `chatStoppen` ersetzen; Import `laufenderChat` entfernen:
```ts
// Stopp genau dieser Runde (Spec 2026-10-09: Stopp wirkt pro Runde); danach zeigt die Abfrage "wird gestoppt …".
export async function chatStoppen(art: StoppArt, auftrag: string): Promise<string | null> {
  const { start } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  const r = await stoppen(start, art, auftrag);
  chatAbfragen();
  return r.ok ? null : r.grund;
}
```

`chat.ts`: `laufenderChat` löschen; `stoppen(s, art, auftrag: string)` (Body immer `{ art, auftrag }`; der Test „stoppen ohne Auftrag schickt nur die Art“ entfällt).

- [ ] **Step 4: Tests, Typen, Bundle**

Run:
```
cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run; npx tsc --noEmit; npm run build
cd ../sales-mcp; <venv-sales> -m pytest tests/test_editor_paket.py tests/test_editor_seite.py -q
```
Expected: alles grün.

- [ ] **Step 5: Commit (SC)**

```
git add editor/src/App/Chat/Runde.tsx editor/src/App/Chat/Runde.test.tsx editor/src/App/Chat/ChatLeiste.tsx editor/src/App/Chat/StoppDialog.tsx editor/src/App/Chat/Sperre.tsx editor/src/App/Chat/Gedanken.tsx editor/src/live.ts editor/src/chat.ts editor/src/chat.test.ts editor/src/pultZustand.ts editor/src/pultZustand.live.test.ts sales-mcp/tests/test_editor_paket.py sales-mcp/static/editor
git commit -m "feat(editor): eigener Verlaufseintrag und Stopp je Runde, Warteschlange und Bild-Hinweise" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Editor — Markierungen gehen nur frisch mit

**Files:**
- Modify: `editor/src/chatKontext.ts` (`AuswahlChip`, `chipHinzu`, `kontextBauen`, neue Hilfen)
- Modify: `editor/src/pultZustand.ts` (`gesendeteAuswahl`, `mitChips`, `chipsVerbraucht`, `auswahlAuffrischen`, `chipAuffrischenAuftrag`)
- Modify: `editor/src/App/Chat/KontextChips.tsx`, `editor/src/App/Chat/ChatLeiste.tsx` (Prop `altform`)
- Test: `editor/src/chatKontext.test.ts`, `editor/src/pultZustand.kontext.test.ts`, Create `editor/src/App/Chat/KontextChips.test.tsx`
- Modify: `sales-mcp/tests/test_editor_paket.py`, Bundle

**Interfaces:**
- Produces:
  - `AuswahlChip` zusätzlich `alt?: boolean` (true = aus der letzten Nachricht, geht nicht mit).
  - `chatKontext.AUS_LETZTER = 'aus der letzten Nachricht'`, `chipsNachSenden(liste, gesendet): AuswahlChip[]`, `chipAuffrischen(liste, chip): AuswahlChip[]`, `altformSchluessel(k: { fenster: string; auswahl: unknown }): string | null`; `kontextBauen` nimmt nur Chips ohne `alt`; `chipHinzu` frischt einen vorhandenen `alt`-Chip auf.
  - Store `gesendeteAuswahl: string | null`; `auswahlAuffrischen()`, `chipAuffrischenAuftrag(chip: AuswahlChip)`.
  - `KontextChips({ altform }: { altform?: { kurz: string } | null })`.

- [ ] **Step 1: Tests schreiben**

`chatKontext.test.ts` (neues `describe`):
```ts
describe('Markierungen aus der letzten Nachricht', () => {
  const t: AuswahlChip = { art: 'block', id: 'titel', kurz: 'Überschrift · Herbst' };
  const b: AuswahlChip = { art: 'block', id: 'bild', kurz: 'Bild · held' };
  it('nach dem Senden bleiben die Chips stehen, aber als alt', () => {
    expect(chipsNachSenden([t, b], [t])).toEqual([{ ...t, alt: true }, b]);
  });
  it('alte Chips gehen nicht mit', () => {
    expect(kontextBauen([{ ...t, alt: true }, b], []).auswahl.map((c) => c.id)).toEqual(['bild']);
  });
  it('Anklicken oder erneutes Setzen frischt auf', () => {
    expect(chipAuffrischen([{ ...t, alt: true }], t)).toEqual([{ ...t, alt: false }]);
    expect(chipHinzu([{ ...t, alt: true }], t)).toEqual([{ ...t, alt: false }]);
    const frisch = [t];
    expect(chipHinzu(frisch, t)).toBe(frisch);
  });
  it('Einzelauswahl als Schluessel je Fenster', () => {
    expect(altformSchluessel({ fenster: 'newsletter', auswahl: 'titel' })).toBe('newsletter|titel');
    expect(altformSchluessel({ fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(altformSchluessel({ fenster: 'newsletter', auswahl: [t] })).toBeNull();
  });
});
```

`pultZustand.kontext.test.ts`:
- Test „chatAbschicken schickt kontext.auswahl und kontext.anhaenge und leert die Chips“: Erwartung am Ende ändern — die Auswahl-Chips stehen danach mit `alt: true` da, Anhänge sind weg (Name: „… und markiert die Chips als aus der letzten Nachricht“).
- Neu:
```ts
describe('Liegengebliebene Markierung', () => {
  it('veraltete Markierung geht nicht mit; Anklicken schickt sie wieder mit', async () => {
    const f = netz({ '/c': [200, { auftrag: 'a', status: 'offen' }], '/c.json': [200, { laeuft: false, verlauf: [] }] });
    const kontext = { fenster: 'newsletter', auswahl: 'titel' };
    expect(await chatAbschicken('Mach das größer', kontext)).toBeNull();
    expect(await chatAbschicken('das aber nicht', kontext)).toBeNull();
    auswahlAuffrischen();
    expect(await chatAbschicken('doch das', kontext)).toBeNull();
    const bodies = f.mock.calls.filter((c) => c[0] === '/c').map((c) => JSON.parse(String((c[1] as RequestInit).body)));
    expect(bodies.map((b) => b.kontext.auswahl)).toEqual(['titel', null, 'titel']);
  });

  it('gesendete Chips gehen beim naechsten Mal nicht mit, angeklickt wieder', async () => {
    const f = netz({ '/c': [200, { auftrag: 'a', status: 'offen' }], '/c.json': [200, { laeuft: false, verlauf: [] }] });
    blockAlsKontext('titel');
    await chatAbschicken('eins', { fenster: 'newsletter', auswahl: null });
    await chatAbschicken('zwei', { fenster: 'newsletter', auswahl: null });
    chipAuffrischenAuftrag(pultStore.getState().chatAuswahl[0]);
    await chatAbschicken('drei', { fenster: 'newsletter', auswahl: null });
    const auswahl = f.mock.calls.filter((c) => c[0] === '/c').map((c) => JSON.parse(String((c[1] as RequestInit).body)).kontext.auswahl);
    expect(auswahl[0]).toEqual([{ art: 'block', id: 'titel', kurz: expect.any(String) }]);
    expect(auswahl[1]).toBeNull();
    expect(auswahl[2]).toEqual([{ art: 'block', id: 'titel', kurz: expect.any(String) }]);
  });
});
```
(Die Datei hat schon ein Dokument mit Block `titel`, `netz` und `START`; Imports um `auswahlAuffrischen`, `chipAuffrischenAuftrag` ergänzen. Im `beforeEach` `gesendeteAuswahl: null` setzen.)

`KontextChips.test.tsx`:
```tsx
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';

import { pultStore } from '../../pultZustand';

import KontextChips from './KontextChips';

beforeEach(() => pultStore.setState({ chatAuswahl: [], chatAnhaenge: [] }));

describe('KontextChips', () => {
  it('veraltete Markierung ausgegraut mit „aus der letzten Nachricht“', () => {
    pultStore.setState({ chatAuswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Herbst', alt: true }] });
    const html = renderToStaticMarkup(<KontextChips />);
    expect(html).toContain('Überschrift · Herbst');
    expect(html).toContain('aus der letzten Nachricht');
    expect(html).toContain('Wieder mitschicken: Überschrift · Herbst');
  });
  it('liegengebliebene Einzelauswahl erscheint ebenso', () => {
    const html = renderToStaticMarkup(<KontextChips altform={{ kurz: 'Text · Hallo' }} />);
    expect(html).toContain('Text · Hallo');
    expect(html).toContain('aus der letzten Nachricht');
  });
  it('frische Chips ohne Vermerk', () => {
    pultStore.setState({ chatAuswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Herbst' }] });
    expect(renderToStaticMarkup(<KontextChips />)).not.toContain('aus der letzten Nachricht');
  });
});
```

`sales-mcp/tests/test_editor_paket.py`:
```python
def test_paket_kennt_veraltete_markierung():
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    for s in ("aus der letzten Nachricht", "Wieder mitschicken"):
        assert s in text, s
```

- [ ] **Step 2: Tests laufen, sie schlagen fehl**

Run: `cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run src/chatKontext.test.ts src/pultZustand.kontext.test.ts src/App/Chat/KontextChips.test.tsx`
Expected: FAIL (`chipsNachSenden` fehlt; zweite Nachricht trägt noch `'titel'`).

- [ ] **Step 3: Implementieren**

`chatKontext.ts`:
```ts
// Markierter Block (Newsletter) oder markierte Ebene (flaeche = Block-id der Gestaltungsflaeche).
// alt: ging mit der letzten Nachricht mit und geht erst nach Anklicken wieder mit (Spec 2026-10-09 §2).
export type AuswahlChip = { art: 'block' | 'ebene'; id: string; flaeche?: string; kurz: string; alt?: boolean };

export const AUS_LETZTER = 'aus der letzten Nachricht';
```
`chipHinzu` ersetzen:
```ts
// Neue Liste mit dem Chip; ein alter gleicher Chip wird aufgefrischt. Unveraendert (dieselbe Liste), wenn er
// frisch schon drin ist, die Liste voll ist oder die id vom Pult abgelehnt wuerde.
export function chipHinzu(liste: AuswahlChip[], chip: AuswahlChip): AuswahlChip[] {
  if (!ID.test(chip.id) || (chip.flaeche !== undefined && !ID.test(chip.flaeche))) return liste;
  const da = liste.find((c) => gleich(c, chip));
  if (da) return da.alt ? chipAuffrischen(liste, da) : liste;
  if (liste.length >= MAX_AUSWAHL) return liste;
  return [...liste, { ...chip, kurz: kappen(chip.kurz, KURZ_MAX) }];
}

export function chipAuffrischen(liste: AuswahlChip[], chip: AuswahlChip): AuswahlChip[] {
  return liste.map((c) => (gleich(c, chip) ? { ...c, alt: false } : c));
}

// Nach dem Senden: die mitgeschickten Chips bleiben als "aus der letzten Nachricht" stehen.
export function chipsNachSenden(liste: AuswahlChip[], gesendet: AuswahlChip[]): AuswahlChip[] {
  return liste.map((c) => (gesendet.some((g) => gleich(g, c)) ? { ...c, alt: true } : c));
}

// Die Einzelauswahl (Altform: markierter Block bzw. ausgewaehlte Ebene) als Schluessel je Fenster.
export function altformSchluessel(k: { fenster: string; auswahl: unknown }): string | null {
  return typeof k.auswahl === 'string' && k.auswahl ? `${k.fenster}|${k.auswahl}` : null;
}
```
In `kontextBauen` `auswahl.slice(0, MAX_AUSWAHL)` durch `auswahl.filter((c) => !c.alt).slice(0, MAX_AUSWAHL)` ersetzen.

`pultZustand.ts`:
- `TPult`: `gesendeteAuswahl: string | null;` (Kommentar: „Einzelauswahl der letzten Nachricht (fenster|id); dieselbe geht erst nach Anklicken wieder mit“), Startwert `null`.
- `MitChips` um `altform: string | null` erweitern; `mitChips` ersetzen:
```ts
function mitChips(kontext: ChatKontext): MitChips | { ok: false; grund: string } {
  const { chatAnhaenge, gesendeteAuswahl } = pultStore.getState();
  if (!sendenErlaubt(chatAnhaenge)) return { ok: false, grund: 'Erst warten, bis die Anhänge hochgeladen sind' };
  const { behalten: chatAuswahl, entfernt } = chipsBereinigen(pultStore.getState().chatAuswahl, getDocument(), null);
  if (entfernt > 0) pultStore.setState({ chatAuswahl, chatHinweis: entferntHinweis(entfernt) });
  const k = kontextBauen(chatAuswahl, chatAnhaenge);
  const neu: ChatKontext = { ...kontext };
  const altform = altformSchluessel(kontext);
  // Liegengeblieben: dieselbe Einzelauswahl wie beim letzten Senden geht nicht noch einmal mit.
  if (altform !== null && altform === gesendeteAuswahl) neu.auswahl = null;
  if (k.auswahl.length > 0) neu.auswahl = k.auswahl;
  if (k.anhaenge.length > 0) neu.anhaenge = k.anhaenge;
  if (kontextBytes(neu) > KONTEXT_MAX) return { ok: false, grund: 'Zu viel Kontext – entferne ein paar Chips' };
  return { ok: true, kontext: neu, auswahl: chatAuswahl.filter((c) => !c.alt), anhaenge: chatAnhaenge, altform };
}

function chipsVerbraucht(mit: MitChips) {
  const { chatAuswahl, chatAnhaenge } = pultStore.getState();
  pultStore.setState({
    chatAuswahl: chipsNachSenden(chatAuswahl, mit.auswahl),
    chatAnhaenge: chatAnhaenge.filter((a) => !mit.anhaenge.some((m) => m.id === a.id)),
    // Die Einzelauswahl dieser Nachricht ist ab jetzt "aus der letzten Nachricht" (auch wenn Chips sie ersetzten).
    ...(mit.altform !== null ? { gesendeteAuswahl: mit.altform } : {}),
  });
}

export function auswahlAuffrischen() {
  pultStore.setState({ gesendeteAuswahl: null });
}

export function chipAuffrischenAuftrag(chip: AuswahlChip) {
  pultStore.setState({ chatAuswahl: chipAuffrischen(pultStore.getState().chatAuswahl, chip) });
}
```
(Imports aus `./chatKontext` um `altformSchluessel`, `chipAuffrischen`, `chipsNachSenden` ergänzen.)

`KontextChips.tsx`:
- Import `AUS_LETZTER` und `auswahlAuffrischen`, `chipAuffrischenAuftrag`; `ButtonBase` aus MUI.
- `Auswahl` ersetzen:
```tsx
function Auswahl({ c }: { c: AuswahlChip }) {
  const Symbol = c.art === 'ebene' ? LayersOutlined : ViewDayOutlined;
  return (
    <Box
      role="listitem"
      title={c.alt ? `${c.kurz} – ${AUS_LETZTER}` : c.kurz}
      sx={{
        ...chipRahmen,
        bgcolor: c.alt ? 'transparent' : 'rgba(91,140,255,0.14)',
        border: c.alt ? `1px dashed ${FARBE.linie}` : '1px solid rgba(91,140,255,0.45)',
        color: c.alt ? FARBE.gedaempft : FARBE.text,
      }}
    >
      {c.alt ? (
        <ButtonBase onClick={() => chipAuffrischenAuftrag(c)} aria-label={`Wieder mitschicken: ${c.kurz}`} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, minWidth: 0, fontSize: 12, color: 'inherit', borderRadius: '6px', '&.Mui-focusVisible': FOKUS }}>
          <Symbol sx={{ fontSize: 14, flexShrink: 0, opacity: 0.6 }} />
          <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {c.kurz} · {AUS_LETZTER}
          </Box>
        </ButtonBase>
      ) : (
        <>
          <Symbol sx={{ fontSize: 14, color: FARBE.akzent, flexShrink: 0 }} />
          <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {c.kurz}
          </Box>
        </>
      )}
      <Weg titel={c.kurz} onClick={() => auswahlEntfernen(c)} />
    </Box>
  );
}

// Die Einzelauswahl der letzten Nachricht: ausgegraut, Anklicken schickt sie wieder mit.
function Liegengeblieben({ kurz }: { kurz: string }) {
  return (
    <ButtonBase
      role="listitem"
      onClick={auswahlAuffrischen}
      aria-label={`Wieder mitschicken: ${kurz}`}
      sx={{ ...chipRahmen, pr: 0.75, border: `1px dashed ${FARBE.linie}`, color: FARBE.gedaempft, fontSize: 12, '&.Mui-focusVisible': FOKUS }}
    >
      <ViewDayOutlined sx={{ fontSize: 14, flexShrink: 0, opacity: 0.6 }} />
      <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {kurz} · {AUS_LETZTER}
      </Box>
    </ButtonBase>
  );
}
```
- `KontextChips` ersetzen:
```tsx
export default function KontextChips({ altform = null }: { altform?: { kurz: string } | null }) {
  const auswahl = pultStore((p) => p.chatAuswahl);
  const anhaenge = pultStore((p) => p.chatAnhaenge);
  if (auswahl.length === 0 && anhaenge.length === 0 && !altform) return null;
  return (
    <Box role="list" aria-label="Kontext für die nächste Nachricht" sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, px: 0.5, pb: 1 }}>
      {altform && <Liegengeblieben kurz={altform.kurz} />}
      {auswahl.map((c) => (
        <Auswahl key={`${c.art}:${c.flaeche ?? ''}:${c.id}`} c={c} />
      ))}
      {anhaenge.map((a) => (
        <Anhang key={a.id} a={a} />
      ))}
      {auswahl.length >= MAX_AUSWAHL && (
        <Box component="span" sx={{ alignSelf: 'center', fontSize: 11, color: FARBE.gedaempft }}>
          Höchstens {MAX_AUSWAHL} markierte Elemente je Nachricht
        </Box>
      )}
    </Box>
  );
}
```

`ChatLeiste.tsx`: Imports `altformSchluessel`, `kurzText` aus `../../chatKontext` und `getDocument` aus `../../documents/editor/EditorContext`; Hilfe oberhalb der Komponente:
```tsx
// Kurztext der Einzelauswahl (Block im Newsletter; im Gestaltungsfenster die Ebenen-id).
function auswahlKurz(k: ChatKontext): string {
  const id = typeof k.auswahl === 'string' ? k.auswahl : '';
  const block = k.fenster === 'newsletter' ? getDocument()[id] : undefined;
  return block ? kurzText(block as { type: string; data?: unknown }) : id;
}
```
in der Komponente:
```tsx
  const gesendeteAuswahl = pultStore((p) => p.gesendeteAuswahl);
  const schluessel = altformSchluessel(kontext);
  const altform = schluessel !== null && schluessel === gesendeteAuswahl ? { kurz: auswahlKurz(kontext) } : null;
```
und `<KontextChips altform={altform} />`.

- [ ] **Step 4: Tests, Typen, Bundle**

Run:
```
cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw/editor; npx vitest run; npx tsc --noEmit; npm run build
cd ../sales-mcp; <venv-sales> -m pytest tests/test_editor_paket.py -q
```
Expected: alles grün.

- [ ] **Step 5: Commit (SC)**

```
git add editor/src/chatKontext.ts editor/src/chatKontext.test.ts editor/src/pultZustand.ts editor/src/pultZustand.kontext.test.ts editor/src/App/Chat/KontextChips.tsx editor/src/App/Chat/KontextChips.test.tsx editor/src/App/Chat/ChatLeiste.tsx sales-mcp/tests/test_editor_paket.py sales-mcp/static/editor
git commit -m "fix(editor): liegengebliebene Markierung geht nur nach Anklicken wieder mit" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Auslieferung und echter Lauf (Controller, nach Freigabe des Betreibers)

Nicht von einem Subagenten. Reihenfolge zwingend:

1. **Claims:** WORKBOARD (`Vibemind_V1/WORKBOARD.md`) und secondbrain (`00_Meta/002_Koordination_Live.md`) eintragen und sofort committen. Beim Stagen nur die eigene Zeile (`git diff` prüfen, fremde Claim-Zeilen nie mitnehmen).
2. **Gesamtläufe:** MOS `pytest spaces/marketing/tests spaces/marketing/claw/tests -q`; SC `cd editor && npx vitest run && npx tsc --noEmit` und die sales-ui-Tests (`tests/test_editor_seite.py tests/test_editor_paket.py`). Alles grün, sonst zurück in den Task.
3. **Migration 067:**
   - Probe: `migration_probe 067 067 verify_060 verify_062 … verify_067` (wie Task 1 Step 5) muss `PROBE OK (zurueckgerollt)` melden.
   - Vorher prüfen, dass gerade keine Editor-Runde läuft (`SELECT count(*) FROM marketing.chat_auftraege WHERE status IN ('offen','in_arbeit','wartet')` = 0), sonst warten.
   - Echt anwenden (PowerShell, MOS-Root, Umgebung wie bei der Probe):
     ```
     & C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -c "import pathlib; from spaces.marketing.sync import _db; print(_db._run_psql(pathlib.Path('spaces/marketing/db/067_parallele_runden.sql').read_text(encoding='utf-8'), None, streng=True)[-2000:])"
     ```
   - Danach `migration_probe spaces/marketing/db/verify_067.sql`.
4. **Push:** MOS `master`, SC `feat/stufe-1-fundament` (kein force).
5. **VM:** `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'` muss mit „ALLE PRUEFUNGEN GRUEN“ enden (update.sh pullt selbst, vorher nicht pullen). Danach `GET /api/pult/inhalte/<iid>/chat` liefert `neueste_fassung`, und der Editor zeigt keinen „Vormerken“-Knopf mehr.
6. **PC:**
   - Haupt-Checkout `spaces/marketing` per Hash-Vergleich und `git restore --source=<sha> --worktree -- spaces/marketing` synchronisieren (vorher `git status`, fremde Änderungen nicht anfassen).
   - Nur den Chat-Arbeiter :8134 neu starten (Prozess beenden, dann `marketing-dienste-starten.ps1`). Shim :8117, :8114 und ComfyUI nicht anfassen.
   - Gesundheit: `GET http://127.0.0.1:8134/` zeigt `editor_1`, `editor_2`, `editor_3` neben `marke` und `wissen`.
   - Budget-Wächter: prüfen, dass jede Editor-Runde einzeln zählt (Stand vor/nach dem echten Lauf vergleichen).
7. **Echter Lauf** an einem VibeMind-Entwurf im Editor (Ergebnisse über die Seite und `GET /api/pult/inhalte/<iid>/chat` prüfen):
   1. Zwei Bitten kurz hintereinander, die verschiedene Blöcke betreffen (z. B. „Titel kürzer“ und „Fußzeile freundlicher“): zwei eigene Einträge mit eigenen Schritten und Stopp; die Fläche wechselt erst beim Fertigwerden; danach enthält die neueste Fassung beide Änderungen (keine überschreibt die andere); an der zweiten Runde steht „Auf Fassung … nachgespielt …“, falls sie das Rennen verloren hat; Rückgängig erscheint nur an der Runde mit der neuesten Fassung.
   2. Danach eine dritte Bitte, die einen von der zweiten gelöschten Block betrifft: die Runde endet mit dem Hinweis „Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: …“ statt mit einem Fehler.
   3. Vier Bitten hintereinander: die vierte steht als „wartet auf freien Platz“ und rückt nach, sobald eine Runde fertig ist.
   4. Chat-Leiste: ziehen (360 px bis halbe Breite), neu laden → Breite gemerkt; Eingabefeld wächst bis 8 Zeilen.
   5. Block markieren, „Mach das größer“ senden, danach „das aber nicht“: die Markierung steht ausgegraut mit „aus der letzten Nachricht“ und geht nicht mit (im Auftrag `kontext.auswahl` = null); der Agent bezieht sich auf seine letzte Runde oder fragt nach.
   - Ergebnis dem Betreiber zur Sichtprüfung im Browser melden (Editor mit laufenden Runden).
8. **Claims schließen**, Memory-Einträge „Marketing-API auf PC+VM“ (Migration 067, `GET …/neueste`) und „Marketing: Vorlagen + Schönheitsprüfung“ (parallele Runden, Nachspielen) ergänzen.
