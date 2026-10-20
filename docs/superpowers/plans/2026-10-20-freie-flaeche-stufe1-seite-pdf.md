# Freie Fläche – Stufe 1: Seitenmodell, Darstellung, PDF – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Einen Newsletter als freie Seite (`format = 'seite'`) speichern, versionieren, als HTML ansehen und als exaktes PDF holen. Die Grundlage für Editor (Stufe 2), Assistent (3), Mail (4) sowie Prüfung und Vorlagen (5).

**Architecture:** Ein neues Python-Modul `claw/seite.py` prüft und normalisiert das Seitendokument. `claw/seite_html.py` baut daraus absolut positioniertes HTML, die einzige Darstellung für Vorschau, PDF und später Prüfbild und Mail-Stücke. Migration 077 legt die Spalte `seite`, eine Datenbank-Prüfung und die Speicher- und Anlage-Funktionen an. Die Pult-API bekommt Anlegen und Speichern und zeigt Seiten in `vorschau`. Einreichen und Versand bleiben für Seiten gesperrt, bis Stufe 4 die Mail baut.

**Tech Stack:** Python 3.11, FastAPI, Postgres (Supabase auf dem Mini-PC, Schema `marketing`), Playwright/Chromium (`claw/pdf_druck.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-freie-flaeche-newsletter-design.md` (sales-claw, Commit d3ae7dd). Abschnitte 4.1, 4.2 und 5 sind hier maßgeblich.

**Repo für alle Tasks:** vibemind-os, Branch `master`, eigener Worktree unter `C:/Users/User/ClaudeWork/`. Pfade unten sind relativ zu `spaces/marketing/`. Tests: `C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest <datei> -q -p no:cacheprovider` aus dem Repo-Root des Worktrees.

## Global Constraints

- Breite der Seite fest **600**. Höhe **400–6000**. Höchstens **80** Ebenen. Dokument höchstens **256 KB** (JSON-Text).
- Ebenenarten genau: `bild`, `text`, `form`, `knopf`. Reihenfolge im Array ist die Ebenenreihenfolge (erste = ganz unten).
- `x`/`y` bezeichnen den **Mittelpunkt** der Ebene, wie in der bestehenden Gestaltung (`gestaltung.py`, `editor/src/gestaltung.ts`), damit Stufe 2 die Editor-Rechenhilfen weiterverwenden kann.
- Bilder nur `medien:<datei>` (Regex wie `gestaltung._QUELLE`). Links nur `https://`. Farben nur `#rrggbb`.
- **Schriftrollen (Entscheidung 9):** `ANZEIGE` und `HAND` sind Webschriften und werden in der Mail später zu Bildern. `TEXT` ist **Fließtext** und wird überall, also Fläche, PDF und Mail, im mail-sicheren Stapel der Markenschrift gesetzt (`schriften.REGISTER[id]["stapel"]`), **nie** als Webschrift.
- **Anrede und Links (Entscheidung 10):** `{vorname}` und Links im Text sind nur in Textebenen mit Rolle `TEXT`, Drehung 0 und ohne Überlappung erlaubt. Stufe 1 prüft Rolle und Drehung. Die Überlappung prüft Stufe 5 (Schönheitsprüfung).
- Aus Nutzerwerten wird nie rohes CSS oder HTML übernommen. CSS entsteht nur aus geprüften Zahlen, Farben und Aufzählungswerten. Text wird HTML-escaped, Auszeichnung nur `**fett**`, `*kursiv*`, `[text](https://…)` und Zeilenumbrüche.
- Fehlermeldungen an Nutzer auf Deutsch mit echten Umlauten, wie im Rest der Pult-API.
- Kein INSERT in API-Routen. Schreiben nur über `marketing.*`-Funktionen (Muster der Pult-API).
- Migrationen idempotent, in einer Transaktion, mit `verify_077.sql` über `python -m spaces.marketing.scripts.migration_probe` (ROLLBACK). Einspielen auf der VM und Livegang nur mit User-OK.
- Alte Block-Newsletter dürfen sich durch diesen Plan in keinem Verhalten ändern (Entscheidung 11).

## Review Focus

1. **Text mit `<`, `"`, `</style>` oder `javascript:` in einer Textebene** muss als Text erscheinen und darf kein Markup und keinen Link erzeugen. Test: `test_text_wird_escaped_und_links_nur_https` (Task 3).
2. **Schriftrolle `TEXT` mit einer Markenschrift, die es nicht gibt** (Marke gewechselt, alte Seite): Die Seite darf weder 422 noch 500 liefern, sie fällt auf den DM-Sans-Stapel zurück. Test: `test_unbekannte_markenschrift_faellt_zurueck` (Task 3).
3. **Ebene weit außerhalb der Seite oder eine 6000 hohe Seite im PDF:** Das PDF ist eine durchgehende Seite in voller Höhe, kein A4-Sprung bis 19 000 px, und Überstand wird abgeschnitten. Tests: `test_pdf_hoehe_folgt_der_seite` (Task 4) und `test_ueberstand_wird_abgeschnitten` (Task 3).
4. **Speichern einer Seite, während der Assistent arbeitet oder der Inhalt eingereicht ist:** gleiche Sperren und gleiche Texte wie bei Blöcken. Test: Abschnitt „Sperren“ in `verify_077.sql` (Task 2).
5. **Ein Block-Newsletter und eine Seite im selben Inhalt** (Fassung 1 Blöcke, Fassung 2 Seite) zeigen in der Vorschau je Fassung das richtige Format. `GET inhalt` liefert für die neueste Fassung `seite` oder `bloecke`, nie beides. Test: `test_vorschau_waehlt_format_je_fassung` (Task 4).

---

### Task 1: Seitenmodell `claw/seite.py`

**Files:**
- Create: `claw/seite.py`
- Test: `tests/test_seite.py`

**Interfaces:**
- Produces:
  - `class SeiteFehler(ValueError)`
  - `BREITE = 600`, `HOEHE_MIN = 400`, `HOEHE_MAX = 6000`, `MAX_EBENEN = 80`, `MAX_BYTES = 256 * 1024`, `MAX_TEXT = 3000`
  - `pruefen(s: object) -> dict`: gibt eine normalisierte Kopie zurück (fehlende Wahlfelder mit Vorgabe aufgefüllt, unbekannte Schlüssel → `SeiteFehler`) oder wirft `SeiteFehler("<deutscher Grund>")`
  - `leer(marke: dict | None) -> dict`: Startseite, die `pruefen` besteht
  - `rolle_schrift(s: dict, rolle: str) -> str`: Schrift-ID für `ANZEIGE`/`TEXT`/`HAND` aus `s["schriften"]` bzw. `schriften.HAND_ROLLE`

**Dokument (genau diese Schlüssel):**

```text
seite   = {version: 1, breite: 600, hoehe: int 400..6000,
           hintergrund: {farbe: "#rrggbb", bild: "medien:…" | null},
           schriften: {anzeige: <REGISTER-id>, text: <REGISTER-id>},
           ebenen: [ebene, …≤80]}
ebene   = {id: ^[A-Za-z0-9_-]{1,32}$ eindeutig, art, x: -600..1200, y: -1000..7000,
           breite: 1..1200, hoehe: 1..6000, drehung: -180..180 (Vorgabe 0), deckkraft: 0..1 (Vorgabe 1), …art-Felder}
bild    = {quelle: "medien:…", passung: "fuellen"|"einpassen" (Vorgabe fuellen), rundung: 0..600 (0),
           kreis: bool (false), rahmen_breite: 0..20 (0), rahmen_farbe: "#rrggbb" ("#ffffff"), schatten: bool (false)}
form    = {form: "rechteck"|"kreis", farbe: "#rrggbb", rundung: 0..600 (0)}
text    = {text: str 1..3000, rolle: "ANZEIGE"|"TEXT"|"HAND", gewicht: 300..900 (400), groesse: 10..160,
           zeilenabstand: 0.8..2.5 (1.3), buchstabenabstand: -0.1..0.5 (0), farbe: "#rrggbb",
           ausrichtung: "links"|"mitte"|"rechts" ("links"), grossbuchstaben: bool (false), kursiv: bool (false),
           hintergrund: "#rrggbb" | null (null)}      # hoehe bei text = Mindesthöhe, Text darf darüber wachsen
knopf   = {text: str 1..60, link: "https://…", farbe: "#rrggbb", textfarbe: "#rrggbb", rundung: 0..60 (6),
           rolle: "ANZEIGE"|"TEXT" ("TEXT"), groesse: 10..40 (16), gewicht: 300..900 (600)}
```

- [ ] **Step 1: Write the failing tests** in `tests/test_seite.py`:
  - `test_leere_seite_ist_gueltig`: `pruefen(leer({"schrift_anzeige": "montserrat", "schrift_text": "dm-sans", "akzent": "#f66c1e"}))` liefert ein dict mit `breite == 600`, `400 <= hoehe <= 6000`, `schriften == {"anzeige": "montserrat", "text": "dm-sans"}`. `leer(None)` nutzt `{"anzeige": "dm-sans", "text": "dm-sans"}`.
  - `test_vorgaben_werden_ergaenzt`: Eine Textebene ohne `drehung`, `deckkraft` und `ausrichtung` kommt mit `0`, `1` und `"links"` zurück.
  - `test_grenzen` (parametrisiert, jeder Fall wirft `SeiteFehler`): `breite: 599`, `hoehe: 399`, `hoehe: 6001`, 81 Ebenen, doppelte Ebenen-ID, `art: "video"`, `quelle: "https://x/y.png"`, `link: "http://x"`, `farbe: "red"`, Textlänge 3001, unbekannter Schlüssel `"style"` in einer Ebene, `drehung: 181`, JSON größer als 256 KB.
  - `test_anrede_und_links_nur_in_fliesstext`: Textebene mit `{vorname}` und `rolle: "ANZEIGE"` → `SeiteFehler` mit `"Anrede"` in der Meldung. Mit `rolle: "TEXT"` und `drehung: 5` → `SeiteFehler`. Mit `rolle: "TEXT"` und `drehung: 0` → ok. Dasselbe für `[x](https://a.de)`.
  - `test_schriften_nur_aus_register`: `schriften.anzeige = "comic"` → `SeiteFehler`. `rolle_schrift(s, "HAND") == "caveat"`.
- [ ] **Step 2: Run** `…pytest spaces/marketing/tests/test_seite.py -q`. Expected: FAIL (`ModuleNotFoundError: spaces.marketing.claw.seite`).
- [ ] **Step 3: Implement `claw/seite.py`.** Regex für Quelle und ID aus `gestaltung.py` übernehmen (importieren, nicht kopieren). Die Größe prüfen über `len(json.dumps(s, ensure_ascii=False).encode())`. `leer()` legt eine Seite der Höhe 1200 an, Hintergrund `#ffffff`, mit einer Überschrift (ANZEIGE, 48), einem Fließtext (TEXT, 17) und einem Knopf (Farbe = Akzent der Marke, sonst `#5b3fd6`). Der Knopf-Link ist ein Platzhalter-https-Link der Firma, falls bekannt, sonst `https://example.com`.
- [ ] **Step 4: Run** the same command. Expected: all PASS.
- [ ] **Step 5: Commit** `git add spaces/marketing/claw/seite.py spaces/marketing/tests/test_seite.py && git commit -m "feat(marketing): Seitenmodell fuer freie Newsletter-Flaeche"`

### Task 2: Migration 077 – Spalte, Prüfung, Speichern, Anlegen

**Files:**
- Create: `db/077_seite.sql`, `db/verify_077.sql`

**Interfaces:**
- Consumes: Regeln aus Task 1 (dieselben Grenzen; die Datenbank ist die zweite Wache, Python bleibt die ausführliche Prüfung).
- Produces:
  - `marketing.inhalt_fassungen.seite jsonb`
  - Constraint `inhalt_fassungen_format_check`: `format IN ('felder','bloecke','seite') AND ((format='bloecke') = (bloecke IS NOT NULL)) AND ((format='seite') = (seite IS NOT NULL))`
  - `marketing.pult_seite_fehler(p jsonb) RETURNS text` (NULL = gültig), IMMUTABLE
  - Constraint `inhalt_fassungen_seite_gueltig CHECK (format <> 'seite' OR marketing.pult_seite_fehler(seite) IS NULL)`
  - `marketing.pult_seite_speichern(p_inhalt uuid, p_basis int, p_betreff text, p_vorschautext text, p_seite jsonb, p_urheber text, p_als_kopie boolean) RETURNS int`
  - `marketing.pult_collage_anlegen(p_mandant text, p_titel text, p_betreff text, p_seite jsonb, p_von text) RETURNS uuid`

- [ ] **Step 1: Write `db/verify_077.sql`.** Muster wie `verify_076.sql`/`verify_075.sql`, mit `RAISE EXCEPTION` bei jeder Abweichung. Abschnitte:
  - **Gültig:** Eine Minimal-Seite mit je einer Ebene jeder Art ergibt `pult_seite_fehler(...) IS NULL`.
  - **Ungültig:** Jeder Fall ergibt NOT NULL: `breite` 599, `hoehe` 6001, 81 Ebenen, `art` `video`, Quelle `https:`, Link `http:`, Farbe `red`, unbekannter Ebenen-Schlüssel, Dokument über 256 KB.
  - **Anlegen:** `pult_collage_anlegen('vibemind', 'Probe 077', 'Betreff', <seite>, 'probe')` erzeugt einen Inhalt `art = 'newsletter'`, `status = 'entwurf'` mit Fassung 1 `format = 'seite'`.
  - **Speichern:** `pult_seite_speichern(i, 1, …, 'betreiber', false)` gibt 2 zurück. `basis = 1` noch einmal → Ausnahme `Inzwischen gibt es Fassung 2`.
  - **Sperren:** Inhalt auf `eingereicht` gesetzt → Ausnahme `Liegt zur Freigabe – erst zurückziehen`. Ein offener `chat_auftraege`-Eintrag (`status = 'in_arbeit'`, `vergeben_bis = now() + 5 min`) und `urheber = 'betreiber'` → `Der Assistent arbeitet gerade`. Mit `urheber = 'agent'` → ok.
  - **Unverändert:** `pult_bloecke_speichern` auf einem Block-Newsletter funktioniert wie vorher. Die CHECKs `inhalt_fassungen_bloecke_gueltig` bleiben vorhanden.
- [ ] **Step 2: Run** `python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/verify_077.sql` mit `SUPABASE_SSH_HOST=offload-vm SUPABASE_DB_CONTAINER=debian-supabase-db-1`. Expected: FAIL (Funktion fehlt).
- [ ] **Step 3: Write `db/077_seite.sql`.**
  - RUNBOOK-Kopf wie 075/076, mit dem Satz „nach 076“.
  - Spalte und Constraint ersetzen (DROP IF EXISTS, ADD).
  - `pult_seite_fehler` in plpgsql nach den Grenzen aus Task 1: Typen, Bereiche, Aufzählungen, Regexe, erlaubte Schlüssel je Art über `jsonb_object_keys`, Größe über `length(p::text)`.
  - `pult_seite_speichern` vereint die Regeln von `_pult_bloecke_speichern_053` (Betreff nicht leer, nur `art = 'newsletter'`, nur `status = 'entwurf'`, `basis`-Prüfung, Layout `dunkel` wie dort) mit den Sperren von `pult_bloecke_speichern` aus 067 (eingereicht; Assistent arbeitet nur für `betreiber`, mit der `bereit_am`/`_chat_pc_lebt`-Ausnahme wörtlich übernommen).
  - Es schreibt `format = 'seite'`, `seite = p_seite`, `bloecke = NULL`.
  - `pult_collage_anlegen` legt den Inhalt an wie die bestehende Anlage aus Vorlagen. Muster: die Funktion hinter `POST /inhalte/aus_vorlage` in `api/pult.py:427`. Danach ruft sie `pult_seite_speichern(id, 0, …, 'betreiber', false)` auf.
  - Rechte wie 071/074/075: EXECUTE nicht für PUBLIC.
- [ ] **Step 4: Run** `migration_probe spaces/marketing/db/077_seite.sql spaces/marketing/db/verify_077.sql spaces/marketing/db/077_seite.sql spaces/marketing/db/verify_077.sql` (zweimal hintereinander, damit Idempotenz geprüft ist). Expected: `PROBE OK (zurueckgerollt)`.
- [ ] **Step 5: Commit** `git add spaces/marketing/db/077_seite.sql spaces/marketing/db/verify_077.sql && git commit -m "feat(marketing): Migration 077 Seitenformat fuer Newsletter"`

### Task 3: Darstellung `claw/seite_html.py`

**Files:**
- Create: `claw/seite_html.py`
- Test: `tests/test_seite_html.py`

**Interfaces:**
- Consumes: `seite.pruefen`, `seite.rolle_schrift`, `schriften.REGISTER`, `schriften.EBENEN_SCHRIFTEN`, `pdf_druck.BREITE_PX`
- Produces: `html(s: dict, *, betreff: str, pflichtteil: dict, bild_basis: str, schrift_basis: str) -> str`. Ein vollständiges Dokument: Seite 600 breit, zentriert auf `BREITE_PX`, darunter der Pflicht-Fuß.

- [ ] **Step 1: Write the failing tests** in `tests/test_seite_html.py`, mit einer Seite aus `seite.leer(...)` plus Zusatzebenen:
  - `test_ebenen_absolut_mit_mittelpunkt_und_drehung`: Eine Ebene `x=300, y=200, breite=100, hoehe=50, drehung=12` erzeugt `left:250px`, `top:175px`, `width:100px`, `height:50px` und `transform:rotate(12deg)`. Die Reihenfolge im HTML entspricht dem Array, jede Ebene bekommt `z-index` nach ihrem Index.
  - `test_seite_schneidet_ab_und_hat_hoehe`: Der Seitencontainer hat `width:600px`, `height:<hoehe>px`, `position:relative` und `overflow:hidden`.
  - `test_ueberstand_wird_abgeschnitten`: Eine Ebene mit `x=1100` steht im HTML, liegt aber im Container mit `overflow:hidden`.
  - `test_bilder_ueber_bild_basis`: `medien:a.jpg` mit `bild_basis="https://h/marketing/bild/1.abc/"` ergibt `src="https://h/marketing/bild/1.abc/a.jpg"`. `passung: "einpassen"` ergibt `object-fit:contain`. `kreis: true` ergibt `border-radius:50%`.
  - `test_fliesstext_im_mailstapel_anzeige_als_webschrift`: Rolle `TEXT` mit `schriften.text = "dm-sans"` setzt `font-family:Arial, Helvetica, sans-serif` **ohne** `'DM Sans'`. Rolle `ANZEIGE` mit `montserrat` setzt `font-family:'Montserrat', Arial, Helvetica, sans-serif`. Der Kopf enthält `<link rel="stylesheet" href="<schrift_basis>schriften.css">`, wenn `schrift_basis` gesetzt ist, sonst keinen Link.
  - `test_text_wird_escaped_und_links_nur_https`: Der Text `<b>x</b> **fett** *kursiv* [hier](https://a.de) [böse](javascript:alert(1))` ergibt `&lt;b&gt;`, `<strong>fett</strong>`, `<em>kursiv</em>`, `<a href="https://a.de"`, und **kein** `javascript:` als href. Zeilenumbrüche werden zu `<br>`.
  - `test_unbekannte_markenschrift_faellt_zurueck`: `s["schriften"]["text"] = "weg"`, vor dem Rendern direkt gesetzt (nicht über `pruefen`), ergibt den Stapel von `dm-sans` und keine Ausnahme.
  - `test_knopf_ist_link`: Eine Knopf-Ebene ergibt ein `<a href="https://…">` mit Hintergrund `farbe` und Text `textfarbe`.
  - `test_pflicht_fuss`: Bei `pflichtteil={"impressum": "Firma X", "abmelde_hinweis": "Abmelden: {abmeldelink}"}` stehen beide Texte escaped unter der Seite, außerhalb des Seitencontainers.
  - `test_kein_script`: Das Ergebnis enthält kein `<script` und kein `on…=`-Attribut.
- [ ] **Step 2: Run** `…pytest spaces/marketing/tests/test_seite_html.py -q`. Expected: FAIL (Modul fehlt).
- [ ] **Step 3: Implement `claw/seite_html.py`.** Erst `seite.pruefen(s)` aufrufen, mit einer Ausnahme für unbekannte Schriften-IDs: der Fallback aus Review Focus 2 passiert vor der Prüfung, indem unbekannte IDs auf `dm-sans` gesetzt werden. Danach CSS nur aus den geprüften Werten bauen und `html.escape` für alle Texte verwenden. Inline-Auszeichnung zuerst escapen, dann die drei Muster per Regex ersetzen, Links nur bei `^https://[^\s"<>]+$`. Bei Textebenen ist `hoehe` die `min-height`.
- [ ] **Step 4: Run** the same command. Expected: all PASS.
- [ ] **Step 5: Commit** `git add spaces/marketing/claw/seite_html.py spaces/marketing/tests/test_seite_html.py && git commit -m "feat(marketing): HTML-Darstellung der freien Seite"`

### Task 4: Pult-API – Anlegen, Speichern, Lesen, Vorschau, PDF, Sperren

**Files:**
- Modify: `api/pult.py` (neue Routen nach `bloecke_speichern` :554; `inhalt` :580; `vorschau` :681; neue Hilfsfunktion neben `_bloecke_html` :275)
- Modify: `api/freigabe.py` (`einreichen` :35)
- Test: `tests/test_pult_api.py` (bestehende Fälschung von `_db` aus dem Kopf der Datei verwenden)

**Interfaces:**
- Consumes: `seite.pruefen`, `seite.leer`, `seite_html.html`, `pdf_druck.html_zu_pdf`, `_pdf_erlaubt`, `schrift_basis_aus`, die SQL-Funktionen aus Task 2.
- Produces (HTTP, alle mit `X-Pult-Key`):
  - `POST /api/pult/inhalte/collage` mit Body `{mandant, titel, betreff?}` → `{"inhalt": "<uuid>", "fassung": 1}`. Die Startseite kommt aus `seite.leer(<Marke des Mandanten>)`. Die Marke wird so gelesen wie in `_vorlage_fuellen` / `_laden_lesen`.
  - `POST /api/pult/inhalte/{iid}/seite` mit Body `{basis_fassung, seite, betreff, vorschautext, urheber?, als_kopie?}` → `{"fassung": n}`. Die Seite durchläuft vorher `seite.pruefen`, bei Fehler 422 mit dem deutschen Grund. Das normalisierte Dokument wird gespeichert.
  - `GET /api/pult/inhalte/{iid}`: Jede Fassung trägt zusätzlich `seite`, nur bei der neuesten, sonst `null`, wie `bloecke`.
  - `GET /api/pult/inhalte/{iid}/vorschau?fassung=n&format=mail|handy|pdf&bild_basis=…`:
    - Bei `format = 'seite'` liefern `mail` und `handy` das HTML aus `seite_html.html` (in Stufe 1 ist das die Ansicht der Seite; die echte Mail baut Stufe 4).
    - `pdf` liefert `pdf_druck.html_zu_pdf(html, _pdf_erlaubt(bild_basis, schrift_basis))`. Bei `PdfDruckFehler` kommt 503.
  - `POST /api/pult/inhalte/{iid}/einreichen`: Ist die neueste Fassung `seite`, kommt 409 `"Collage-Newsletter lassen sich noch nicht einreichen"`, ohne die Datenbank-Funktion aufzurufen.
  - `GET /versand` bleibt unverändert, lehnt `seite` also schon mit 422 ab. Ein Test hält das fest.

- [ ] **Step 1: Write the failing tests** in `tests/test_pult_api.py`:
  - `test_collage_anlegen_ruft_db_funktion`: Das protokollierte SQL enthält `marketing.pult_collage_anlegen(` und ein JSON, das `seite.pruefen` besteht.
  - `test_seite_speichern_prueft_vorher`: Eine Seite mit `breite: 599` ergibt 422 und keinen SQL-Aufruf. Eine gültige Seite führt zu `marketing.pult_seite_speichern(`.
  - `test_inhalt_liefert_seite_der_neuesten_fassung`.
  - `test_vorschau_waehlt_format_je_fassung`: Fassung 1 hat `bloecke` → Antwort aus dem MJML-Weg. Fassung 2 hat `seite` → Antwort enthält `position:relative;width:600px`.
  - `test_pdf_hoehe_folgt_der_seite`: `pdf_druck.html_zu_pdf` wird per monkeypatch ersetzt. Bei einer Seite mit `hoehe: 6000` bekommt es HTML mit `height:6000px` im Seitencontainer. Die Antwort hat `media_type == "application/pdf"`. Dass die Seite durchgehend bleibt, deckt `seitenmass` mit seinen eigenen Tests ab (bis 19 000 px kein A4).
  - `test_einreichen_sperrt_seite`: 409 mit dem genauen Text, kein `pult_einreichen` im SQL-Protokoll.
  - `test_versand_lehnt_seite_ab`: 422.
- [ ] **Step 2: Run** `…pytest spaces/marketing/tests/test_pult_api.py -q`. Expected: die neuen Tests FAIL, die alten PASS.
- [ ] **Step 3: Implement** die Routen und Änderungen wie oben. Im SELECT von `vorschau` kommt `f.seite` dazu. Die neue Hilfsfunktion `_seite_antwort(dok, betreff, pflichtteil, fmt, bild_basis) -> Response` ist parallel zu `_bloecke_html` aufgebaut.
- [ ] **Step 4: Run** `…pytest spaces/marketing/tests/test_pult_api.py spaces/marketing/tests/test_seite.py spaces/marketing/tests/test_seite_html.py -q`. Expected: all PASS. Dann die übrige Marketing-Suite: `…pytest spaces/marketing/tests -q`. Expected: keine neuen Fehler gegenüber der Basis. Vorbestehend rot sind `test_cockpit_contract` und die drei Tests, denen im Worktree das Submodul fehlt.
- [ ] **Step 5: Commit** `git add spaces/marketing/api/pult.py spaces/marketing/api/freigabe.py spaces/marketing/tests/test_pult_api.py && git commit -m "feat(marketing): Pult-API fuer Collage-Newsletter (anlegen, speichern, Vorschau, PDF)"`

### Task 5: Echter Durchlauf und Livegang (nur mit User-OK)

**Files:**
- Create: `scripts/seite_probe.py`. Es legt über die API eine Collage an, speichert eine zweite Fassung mit Bild, gedrehtem ANZEIGE-Text, Form und Knopf, holt das PDF und schreibt es in eine Datei. Es löscht den Inhalt danach über `POST /inhalte/{id}/loeschen` (075).

- [ ] **Step 1:** Vorher WORKBOARD-Claim setzen (eigene Zeile, nur die eigene Zeile stagen). Für die Datenbank auf der VM zusätzlich ein Claim in `secondbrain/00_Meta/002_Koordination_Live.md`.
- [ ] **Step 2:** User um OK für den Livegang fragen (Migration 077 auf der VM, Marketing-API aktualisieren).
- [ ] **Step 3:** Mit OK: 077 über `_db._run_psql(..., streng=True)` einspielen, dann `migration_probe verify_077.sql`. Expected: `PROBE OK`.
- [ ] **Step 4:** `ssh offload-vm 'bash ~/sales-claw/deploy/marketing-aktualisieren.sh'`, dann die PC-Dienste `:5510` mit dem Wächter-Muster neu starten (`dienst_waechter.beende_dienst`, danach `marketing-dienste-starten.ps1 -Nur`).
- [ ] **Step 5:** `scripts/seite_probe.py` gegen die VM-API laufen lassen. Dann das PDF ansehen, als Bild über die Scratch-venv mit pymupdf. Expected: Alle Ebenen stehen an ihrer Stelle, der gedrehte Text erscheint in Markenschrift, der Fließtext im Arial-Stapel, der Fuß steht unten, alles auf einer Seite.
- [ ] **Step 6:** Claims schließen. Commit `git add spaces/marketing/scripts/seite_probe.py && git commit -m "chore(marketing): Probe fuer Collage-Seite und PDF"` und auf `master` pushen.

## Folgepläne (je ein eigener Plan nach Abschluss dieser Stufe)

- **Stufe 2, Editor am PC** (sales-claw `editor/`): Seitenansicht als Hauptansicht für `format = 'seite'`, Griffe, Text direkt auf der Fläche, Höhe ziehen, Speichern über `POST /inhalte/{iid}/seite`, „Neue Collage“ über `POST /inhalte/collage`. Handy-Vorschau mit `format=handy`.
- **Stufe 3, Assistent:** Ebenen-Werkzeuge für Seiten, Prüfbild per Playwright-Screenshot von `seite_html.html`, bis zu 3 Nachbesserungsrunden mit Bild an den Shim `:8117`, Qualitätsregeln und Abwechslung im Prompt.
- **Stufe 4, Mail und Versand:** Streifen-Zerlegung, Bildstücke (600 @2×), Textstreifen in MJML mit Ersatzstapel, Knöpfe anklickbar, Alt-Texte, `text_fassung`, 8-MB-Grenze. Danach Einreichen und Versand für `seite` freigeben.
- **Stufe 5, Schönheitsprüfung und Vorlagen:** Pixel-Kontrast, Überlappung bei Anrede und Links, 8 Collage-Vorlagen mit Freigabe, danach kein Neuanlegen von Block-Newslettern mehr.
