# Freie Fläche – Stufe 2: Editor am PC – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collage-Newsletter (`format = 'seite'`) im Editor öffnen, anlegen, frei bearbeiten (verschieben, drehen, skalieren, Text direkt ändern, Höhe ziehen, Ebenen ordnen) und als neue Fassung speichern. Am Handy erscheint die Vorschau.

**Architecture:**
- **Gemeinsames Bundle:** Der Editor-Start erkennt das Format. Bei `seite` startet eine eigene Oberfläche `App/Seite/SeiteApp.tsx` im selben Bundle, der Block-Editor bleibt unberührt.
- **Modell und Darstellung:** Seitenmodell, Textauszeichnung und Schriftwahl liegen in `seite.ts` und `seiteText.tsx`. Sie spiegeln genau die Regeln von `claw/seite.py` und `claw/seite_html.py` aus Stufe 1, damit Editor, PDF und Mail gleich aussehen.
- **Geometrie:** Die Rechenhilfen in `seiteGeometrie.ts` sind reine Funktionen und testbar. Das Rückgängig-Machen nutzt `verlauf` aus `gestaltung.ts`.
- **Server:** sales-mcp öffnet die Editor-Seite für `seite`, leitet das Speichern an `POST /api/pult/inhalte/{iid}/seite` weiter und legt Collagen über `POST /api/pult/inhalte/collage` an.

**Tech Stack:** React 18, MUI 5, zustand 4, TypeScript strict, Vite, Vitest (`renderToStaticMarkup`, kein jsdom). Server: Python/Starlette (`sales-mcp/ui_editor.py`, `ui_marketing.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-freie-flaeche-newsletter-design.md`, Abschnitte 4.1, 4.6, 4.7 und 5. Stufe 1 ist live: vibemind-os `58cb7e72`, Plan `docs/superpowers/plans/2026-10-20-freie-flaeche-stufe1-seite-pdf.md`.

**Repo:** sales-claw, Branch `feat/stufe-1-fundament`, eigener Worktree unter `C:/Users/User/ClaudeWork/`. Editor-Pfade sind relativ zu `editor/src/`, Server-Pfade relativ zu `sales-mcp/`.

**Befehle:**
- Python: `cd sales-mcp && SALES_DB_URL=postgresql://postgres:ci@127.0.0.1:55600/postgres SALES_DB_SCHEMA=sales_test E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q -p no:cacheprovider`. Jede Datei einzeln laufen lassen, weil die Test-DB geteilt ist.
- Editor: `cd editor && npm ci --no-audit --no-fund && npx tsc --noEmit -p . && npx vitest run && npm run build`. Der Build schreibt `sales-mcp/static/editor/{editor.js,editor.css,MANIFEST.json}`, alle drei mitcommitten. Nie `npx --prefix`, das prüft nichts.
- Vorbestehend rot: `test_editor_seite.py::test_bild_route_entschluesselt_nur_einmal`.

## Global Constraints

- **Seitenmodell exakt wie Stufe 1 (`claw/seite.py`):**
  - Breite 600, Höhe 400–6000, höchstens 80 Ebenen.
  - Ebenenarten `bild`, `text`, `form`, `knopf`.
  - `x`/`y` = Mittelpunkt, Reihenfolge im Array = Ebenenreihenfolge (erste unten).
  - Feldnamen und Bereiche wie im Stufe-1-Plan, Abschnitt Task 1 „Dokument“.
- **Platzierung wie `seite_html.py`:** `left = x − breite/2`, `top = y − hoehe/2`, `width = breite`, `height = hoehe` (bei Text `min-height`), `transform: rotate(<drehung>deg)`, `opacity = deckkraft`, Seitencontainer mit `overflow: hidden`.
- **Schriftrollen:**
  - `TEXT` ist **nur** der mail-sichere Stapel der Markenschrift, nie die Webschrift.
  - `ANZEIGE` ist die Webschrift der Marke vor dem Stapel.
  - `HAND` ist Caveat vor `'Segoe Print', 'Bradley Hand', cursive`.
  - Die Stapel sind wörtlich aus `vibemind-os/spaces/marketing/claw/schriften.py` übernommen:
    - `cormorant`: `Georgia, 'Times New Roman', serif`
    - `dm-sans`: `Arial, Helvetica, sans-serif`
    - `playfair`: `Georgia, 'Times New Roman', serif`
    - `poppins`: `Arial, Helvetica, sans-serif`
    - `young-serif`: `Georgia, serif`
    - `manrope`: `Arial, Helvetica, sans-serif`
    - `bodoni`: `Didot, Georgia, serif`
    - `montserrat`: `Arial, Helvetica, sans-serif`
    - `josefin`: `'Trebuchet MS', Arial, sans-serif`
    - `oxanium`: `'Trebuchet MS', Arial, sans-serif`
    - `rajdhani`: `'Arial Narrow', Arial, sans-serif`
  - Eine unbekannte ID fällt auf `dm-sans` zurück.
- **Textauszeichnung:** nur `**fett**`, `*kursiv*`, `[text](https://…)` (Linkgrammatik wie `_TEXTLINK` in `seite.py`) und Zeilenumbrüche. Darstellung über React-Elemente, **nie** `dangerouslySetInnerHTML`. Ein Link, der nicht mit https beginnt, zeigt nur seinen Text.
- **Anrede und Links:** `{vorname}` und Textlinks nur in Textebenen mit Rolle `TEXT` und Drehung 0. Der Editor verhindert das Speichern sonst mit dem deutschen Grund. Die API prüft es ebenfalls (422).
- Bilder bleiben im Dokument als `medien:<datei>`. Umgewandelt wird nur beim Anzeigen (Muster `quelleAnzeige` in `App/Gestaltung/hilfen.ts`).
- Kein Assistent für Collagen in Stufe 2 (die API sperrt ihn mit 409). Die Oberfläche zeigt stattdessen: „Der Assistent kommt für Collage-Newsletter in der nächsten Stufe.“
- Einreichen und Versand bleiben für Collagen gesperrt (API). Die Oberfläche bietet beides für `seite` nicht an.
- Der Block-Editor und alle Block-Newsletter verhalten sich unverändert.
- UI-Texte auf Deutsch mit echten Umlauten. Sales-Seiten ohne JavaScript (CSP). Der Editor läuft unter dem unveränderten `CSP_EDITOR`.
- Livegang (VM `update.sh`) nur mit User-OK.

## Review Focus

1. **Speichern nach fremder Änderung** (Fassung inzwischen höher): Erwartet wird ein Konfliktdialog mit „Neu laden“ und „Als Kopie behalten“, wie im Block-Editor. Es darf kein stilles Überschreiben und keinen Datenverlust geben. Test: `test_seite_speichern_konflikt_409` (Task 1) und der Konfliktfall in `seitePult.test.ts` (Task 5).
2. **Eine Ebene ganz aus der Fläche ziehen oder auf 1 px verkleinern:** Die Werte bleiben in den Modellgrenzen (x −600..1200, y −1000..7000, Größe ≥ 1), und die Ebene bleibt in der Ebenenliste auswählbar. Test: `klemmen` (Task 4).
3. **Seitenhöhe kleiner ziehen, als Ebenen hinunterreichen:** Die Höhe bleibt 400–6000, Ebenen bleiben erhalten, auch wenn sie abgeschnitten sind. Test: `hoeheZiehen` (Task 4).
4. **Ein Text mit `<`, `"` oder `javascript:`-Link im Editor** erscheint als Text, nie als Markup oder klickbarer Link. Test: `seiteText` mit diesen Eingaben (Task 3).
5. **Eine Collage öffnen, deren Marke inzwischen eine unbekannte Schrift-ID hat:** Der Editor lädt mit dem Rückfall-Stapel und stürzt nicht ab. Test: `familieFuer` mit unbekannter ID (Task 3).

---

### Task 1: Editor-Seite und Speicher-Weiterleitung für Collagen (Server)

**Files:**
- Modify: `sales-mcp/ui_editor.py`: `editor_seite` :227-320 (Tor :237-240, Start-JSON :260-307); neue Route neben `editor_speichern` :322-376; Routenliste :1026-1055
- Test: `sales-mcp/tests/test_editor_seite.py` (Fälschung `Falsch.anfrage` :32-142 um `format = 'seite'` erweitern)

**Interfaces:**
- Produces (Start-JSON, nur bei `format = 'seite'`): `format: "seite"`, `seite: <dict wie gespeichert, medien: bleibt>`, `dokument: null`, `speichern_url: "/marketing/editor/{iid}/seite"`. Alle übrigen Felder wie bisher.
- Produces (HTTP): `POST /marketing/editor/{iid}/seite`
  - Body `{basis_fassung, seite, betreff, vorschautext, als_kopie}`, Header `X-CSRF`, höchstens 300 KB.
  - Leitet weiter an `marketing_pult.anfrage("POST", f"/inhalte/{iid}/seite", {basis_fassung, seite, betreff, vorschautext, als_kopie, urheber: "betreiber"})`.
  - Antworten:
    - Erfolg: `{"fassung": n}`
    - `abgelehnt` mit Detail, das mit „Inzwischen gibt es Fassung“ beginnt: 409 `{"konflikt": true}`
    - anderes `abgelehnt`: 422 `{"grund": detail}`
    - sonst: 503

- [ ] **Step 1: Write the failing tests:**
  - `test_editor_oeffnet_collage`: Neueste Fassung `format = 'seite'` mit Status `entwurf` gibt 200. Das Start-JSON enthält `"format": "seite"`, das Seiten-Dict und `"speichern_url": "/marketing/editor/<IID>/seite"`.
  - `test_editor_nur_fuer_bloecke_newsletter_entwurf` anpassen: `felder` bleibt 422, `seite` ist jetzt erlaubt.
  - `test_seite_speichern_leitet_weiter`: Die Fälschung protokolliert `("POST", "/inhalte/<IID>/seite")` mit `urheber == "betreiber"` und dem Seiten-Dict unverändert.
  - `test_seite_speichern_konflikt_409`: Ein `abgelehnt`-Detail „Inzwischen gibt es Fassung 3 - neu laden oder als Kopie behalten“ gibt 409 `{"konflikt": true}`.
  - `test_seite_speichern_422_grund`: Ein `abgelehnt`-Detail „Anrede und Links …“ gibt 422 mit demselben Grund.
  - `test_seite_speichern_ohne_csrf_403` (Status wie bei `editor_speichern`) und `test_seite_speichern_zu_gross_413`: Body über 300 KB gibt denselben Status wie bei `editor_speichern`.
- [ ] **Step 2: Run** `pytest tests/test_editor_seite.py -q`. Expected: die neuen Tests FAIL.
- [ ] **Step 3: Implement** Tor, Start-JSON und Route. Die Prüf- und Fehlerabbildung von `editor_speichern` wird geteilt, nicht kopiert: eine Hilfsfunktion, die beide Routen nutzen.
- [ ] **Step 4: Run** `pytest tests/test_editor_seite.py -q` und `pytest tests/test_editor_paket.py -q`. Expected: PASS, außer dem vorbestehenden Fehler.
- [ ] **Step 5: Commit** `git add sales-mcp/ui_editor.py sales-mcp/tests/test_editor_seite.py && git commit -m "feat(editor): Editor-Seite und Speichern fuer Collage-Newsletter"`

### Task 2: Neue Collage anlegen, Entwurfs- und Freigabeseite (Server)

**Files:**
- Modify: `sales-mcp/ui_editor.py`: neue Route `POST /marketing/neue-collage` nach dem Muster von `aus_vorlage` :843-862. Auf der Vorlagenseite `vorlagen_seite` :788-822 kommt eine Karte „Neue Collage“ dazu.
- Modify: `sales-mcp/ui_marketing.py`: in der Galerie :256-261 neben „Neuer Newsletter aus Vorlage“ ein Formular-Knopf „Neue Collage“. Auf der Entwurfsseite :424-474 gilt für `seite`: „Im Editor öffnen“ zeigen, Feldformular und „Ins Editor-Format übernehmen“ ausblenden.
- Modify: `sales-mcp/ui_freigabe_newsletter.py` :193-203: „Export anstoßen“ und „An Kontakte senden“ nur bei `format == "bloecke"`, nicht bei `seite`.
- Test: `sales-mcp/tests/test_editor_seite.py`, `sales-mcp/tests/test_marketing_pult.py` (oder die Testdatei, die heute `/marketing/entwurf` und die Galerie prüft; per grep finden)

**Interfaces:**
- Produces: `POST /marketing/neue-collage`
  - Formular mit `csrf` und `titel` (1–120 Zeichen, getrimmt). Die Firma kommt aus dem Cookie (`marketing_mandant.firma(request)`).
  - Ruft `marketing_pult.anfrage("POST", "/inhalte/collage", {"mandant": firma, "titel": titel})` auf.
  - Erfolg: 303 nach `/marketing/editor/<inhalt>`. Leerer Titel: Fehlerseite „Bitte einen Titel angeben“. Ablehnung oder Fehler: Fehlerseite wie bei `aus_vorlage`.

- [ ] **Step 1: Write the failing tests:**
  - `test_neue_collage_leitet_in_editor`: Die Fälschung gibt `{"inhalt": "<uuid>", "fassung": 1}` zurück. Antwort 303, `location == "/marketing/editor/<uuid>"`, und das protokollierte Mandat entspricht dem Cookie.
  - `test_neue_collage_ohne_titel`: kein Aufruf der API, Fehlerseite mit „Bitte einen Titel angeben“.
  - `test_neue_collage_ohne_csrf`: derselbe Status wie bei `aus_vorlage` ohne CSRF.
  - `test_galerie_hat_knopf_neue_collage`: Das HTML von `/marketing` enthält `action="/marketing/neue-collage"`.
  - `test_entwurf_collage_zeigt_editor_ohne_feldformular`: Bei `seite` enthält die Entwurfsseite den Link `/marketing/editor/<id>`, aber weder „Ins Editor-Format übernehmen“ noch das Feldformular.
  - `test_freigabe_collage_ohne_versand`: Bei `seite` fehlen „Export anstoßen“ und „An Kontakte senden“.
- [ ] **Step 2: Run** die betroffenen Testdateien einzeln. Expected: FAIL.
- [ ] **Step 3: Implement.** Das Formular für den Titel ist ein schlichtes `<form method="post">` mit Textfeld und Knopf, ohne JavaScript.
- [ ] **Step 4: Run** die betroffenen Testdateien einzeln plus `tests/test_seitenleiste.py`, `tests/test_handy.py`, `tests/test_darstellung.py`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(marketing): Neue Collage anlegen, Entwurf und Freigabe kennen Collagen"` (mit expliziten Pfaden).

### Task 3: Seitenmodell, Schriftwahl, Textauszeichnung im Editor

**Files:**
- Create: `editor/src/seite.ts`, `editor/src/seite.test.ts`
- Create: `editor/src/seiteText.tsx`, `editor/src/seiteText.test.tsx`

**Interfaces:**
- Produces (`seite.ts`):
  - Typen `Seite`, `SeitenEbene` (Union `BildEbeneS | TextEbeneS | FormEbeneS | KnopfEbeneS`) mit den Feldnamen aus Stufe 1.
  - Konstanten `BREITE = 600`, `HOEHE_MIN = 400`, `HOEHE_MAX = 6000`, `MAX_EBENEN = 80`, `MAX_TEXT = 3000`, `MAIL_STAPEL: Record<string, string>` (Werte aus Global Constraints).
  - `familieFuer(rolle: 'ANZEIGE' | 'TEXT' | 'HAND', s: Seite): string`
  - `neueEbene(art: SeitenEbene['art'], s: Seite, quelle?: string): SeitenEbene`: neue Ebene in der Seitenmitte mit Vorgaben aus Stufe 1, eindeutige ID über `neueId` aus `gestaltung.ts`. Text ist „Neuer Text“ (TEXT, 17), ein Knopf ist „Mehr erfahren“ mit `https://example.com`.
  - `speicherGrund(s: Seite): string | null`: Grund auf Deutsch oder `null`. Geprüft werden höchstens 80 Ebenen, Textlänge, die Anrede- und Link-Regel und Links nur https. Die Meldungen sind wortgleich mit `seite.py`, wo es dieselbe Regel gibt (dort nachsehen).
  - `ebenenStil(e: SeitenEbene): React.CSSProperties`: Platzierung wie in den Global Constraints, ohne Inhalt.
- Produces (`seiteText.tsx`): `SeiteText({ text }: { text: string }): JSX.Element`. Absätze werden `<br/>`, Fettung `<strong>`, Kursiv `<em>`, Links `<a href target="_blank" rel="noopener noreferrer">` nur bei https.

- [ ] **Step 1: Write the failing tests:**
  - `familieFuer`:
    - `TEXT` mit `schriften.text = 'dm-sans'` → `'Arial, Helvetica, sans-serif'`, ohne `DM Sans`.
    - `ANZEIGE` mit `montserrat` → beginnt mit `'Montserrat'` und endet mit dem Stapel.
    - `HAND` → beginnt mit `'Caveat'`.
    - Unbekannte ID `'weg'` mit `TEXT` → Stapel von `dm-sans`.
  - `ebenenStil`: `x=300, y=200, breite=100, hoehe=50, drehung=12` → `left 250`, `top 175`, `width 100`, `height 50`, `transform 'rotate(12deg)'`. Text bekommt `minHeight` statt `height`.
  - `speicherGrund`:
    - 81 Ebenen → Grund. `{vorname}` in `ANZEIGE` → Grund mit „Anrede“. `[x](https://a.de)` in `TEXT` mit Drehung 5 → Grund.
    - Gültige Seite aus Stufe 1 (`leer()`-Form, im Test nachgebaut) → `null`.
  - `neueEbene`: Die ID ist nicht in der Seite vorhanden, `x == 300`, `y == hoehe / 2`.
  - `seiteText` (über `renderToStaticMarkup`):
    - `'<b>x</b> **fett** *kursiv* [hier](https://a.de) [böse](javascript:alert(1))'` enthält `&lt;b&gt;`, `<strong>fett</strong>`, `<em>kursiv</em>` und `href="https://a.de"`, aber kein `javascript:`.
    - `'a\nb'` enthält `<br/>`.
- [ ] **Step 2: Run** `cd editor && npx vitest run src/seite.test.ts src/seiteText.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.** Die Linkgrammatik ist wörtlich die von `_TEXTLINK`/`_HTTPS` aus `vibemind-os/spaces/marketing/claw/seite.py`, übertragen nach TypeScript.
- [ ] **Step 4: Run** dieselben Tests und `npx tsc --noEmit -p .`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(editor): Seitenmodell, Schriftrollen und Textauszeichnung fuer Collagen"`

### Task 4: Geometrie und Zustand

**Files:**
- Create: `editor/src/seiteGeometrie.ts`, `editor/src/seiteGeometrie.test.ts`
- Create: `editor/src/App/Seite/useSeite.ts`

**Interfaces:**
- Consumes: `Seite`, `SeitenEbene`, Konstanten aus Task 3; `verlauf<T>` aus `gestaltung.ts`.
- Produces (`seiteGeometrie.ts`):
  - `klemmen(e: SeitenEbene): SeitenEbene`: x in −600..1200, y in −1000..7000, breite 1..1200, hoehe 1..6000, drehung auf −180..180 normalisiert.
  - `einrastenSeite(e: SeitenEbene, andere: SeitenEbene[], hoehe: number, schwelle = 6): { x: number; y: number; linien: { art: 'senkrecht' | 'waagrecht'; wert: number }[] }`: rastet Mittelpunkt und Kanten an Seitenrand, Seitenmitte und Mitten bzw. Kanten anderer Ebenen.
  - `griffZiehen(e: SeitenEbene, griff: 'no' | 'nw' | 'so' | 'sw' | 'n' | 's' | 'o' | 'w', dx: number, dy: number, festesVerhaeltnis: boolean): SeitenEbene`: Größe ändern, die gegenüberliegende Kante bleibt stehen. dx und dy sind Seiteneinheiten im ungedrehten Rahmen der Ebene. Für gedrehte Ebenen wird die Mausbewegung vorher in den Ebenenrahmen gedreht. Text ändert Breite und Mindesthöhe, nicht die Schriftgröße.
  - `drehenZu(e: SeitenEbene, mausX: number, mausY: number, einrasten15: boolean): SeitenEbene`: Winkel vom Mittelpunkt zur Maus. Mit `einrasten15` rastet er auf 15°-Schritte.
  - `hoeheZiehen(s: Seite, neueHoehe: number): Seite`: klemmt auf 400–6000, rundet auf ganze Zahlen, Ebenen bleiben unverändert.
- Produces (`useSeite.ts`): `useSeite(anfang: Seite)` → `{ seite, auswahl, waehlen(id | null), ebeneAendern(id, teil: Partial<SeitenEbene>, modus: 'sofort' | 'gleiten' | 'live'), hinzufuegen(e), loeschen(id), nachOben(id), nachUnten(id), hoeheSetzen(h, modus), zurueck(), vor(), geaendert: boolean, gespeichert(): void }`. Die Modi folgen `useGestaltung.ts`: `gleiten` fasst eine Ziehbewegung zu einem Rückgängig-Schritt zusammen, `live` schreibt nichts in den Verlauf. Jede Änderung läuft durch `klemmen`.

- [ ] **Step 1: Write the failing tests** in `seiteGeometrie.test.ts`:
  - `klemmen` mit x=5000, breite=0 und drehung=190 → x 1200, breite 1, drehung −170.
  - `einrastenSeite`: Eine Ebene mit Mitte bei x=297 rastet auf 300 und meldet eine senkrechte Linie bei 300. Eine linke Kante bei 3 rastet auf 0.
  - `griffZiehen`:
    - Griff `so` mit dx=20, dy=10 an einer ungedrehten 100×50-Ebene bei 300/200 → breite 120, hoehe 60, x 310, y 205. Die linke obere Ecke bleibt bei 250/175.
    - Mit `festesVerhaeltnis` bleibt das Verhältnis 2:1.
  - `drehenZu`: Maus genau rechts vom Mittelpunkt → 0. Maus bei 44° mit `einrasten15` → 45.
  - `hoeheZiehen`: 100 → 400, 9000 → 6000, 812.6 → 813. Die Ebenen sind dieselben Objekte.
- [ ] **Step 2: Run** `npx vitest run src/seiteGeometrie.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** beide Dateien.
- [ ] **Step 4: Run** die Tests und `npx tsc --noEmit -p .`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(editor): Geometrie und Verlauf fuer die Collage-Flaeche"`

### Task 5: Collage-Oberfläche, Start und Handy

**Files:**
- Create: `editor/src/App/Seite/SeiteApp.tsx` (Gerüst: Leiste oben, Ebenen links, Fläche Mitte, Eigenschaften rechts)
- Create: `editor/src/App/Seite/SeiteFlaeche.tsx` (Darstellung und Bedienung)
- Create: `editor/src/App/Seite/SeiteEbenen.tsx`, `editor/src/App/Seite/SeiteEigenschaften.tsx`
- Create: `editor/src/seitePult.ts` (Speichern), `editor/src/seitePult.test.ts`, `editor/src/App/Seite/SeiteApp.test.tsx`
- Modify: `editor/src/main.tsx` :42-49. Bei `start.format === 'seite'` werden `resetDocument`, `fensterWiederOeffnen` und `onDocumentChange` übersprungen, und `<SeiteApp start={start} />` wird gerendert.
- Modify: `editor/src/pult.ts` `startLesen` (Typ des Start-JSON um `format?` und `seite?` erweitern).
- Modify: `editor/src/App/Handy/HandyApp.tsx`: `HandyAnsicht` bekommt die Option `ohneAssistent: boolean` (Reiter „Assistent“ ausblenden).

**Interfaces:**
- Consumes: Task 1 (Start-JSON, `speichern_url`), Task 3, Task 4; `Bedienelemente.tsx` (`Abschnitt`, `Zeile`, `Zahl`, `FarbFeld`); `quelleAnzeige` aus `App/Gestaltung/hilfen.ts`; den Mediendialog, mit dem `GestaltungFenster` eine Bild-Ebene hinzufügt (per grep auf `medien_url` finden und wiederverwenden, nicht nachbauen); `useFensterTasten` (Pfeile, Entf, Strg+Z); `HANDY_GRENZE`, `vorschauAdresse` aus `handy.ts`.
- Produces (`seitePult.ts`): `seiteSpeichern(start: Start, seite: Seite, betreff: string, vorschautext: string, basis: number, alsKopie: boolean): Promise<{ ok: true; fassung: number } | { ok: false; konflikt: true } | { ok: false; grund: string }>`. POST an `start.speichern_url` mit `X-CSRF`, Muster `pult.ts` `speichern` :196.

**Verhalten (Spec 4.6):**
- **Leiste oben:** Zurück (`zurueck_url`), Betreff-Feld, Speichern, „Als PDF“ (`vorschau_url?fassung=<basis>&format=pdf`, nur nach dem Speichern aktiv), Rückgängig/Wiederholen und der Hinweis zum Assistenten (Text aus den Global Constraints).
- **Fläche:**
  - Rendert die Seite 1:1 nach `ebenenStil`, `familieFuer` und `SeiteText`, skaliert auf die verfügbare Breite.
  - **Klick** wählt aus. **Ziehen** verschiebt mit Einrasten und Hilfslinien.
  - **Griffe:** Acht Griffe zum Skalieren, Umschalt hält das Verhältnis fest. Ein Drehgriff oberhalb dreht, Umschalt rastet auf 15°.
  - **Doppelklick auf Text oder Knopf** öffnet ein Textfeld genau über der Ebene. Enter mit Strg oder ein Klick daneben übernimmt, Esc verwirft.
  - **Höhe:** Ein Griff am unteren Seitenrand zieht die Höhe.
- **Ebenen links:** Liste von oben nach unten (oberste Ebene zuerst), auswählen, nach oben/unten, löschen. Knöpfe „Text“, „Bild“, „Form“, „Knopf“ fügen hinzu, gesperrt bei 80 Ebenen mit dem Hinweis „Höchstens 80 Ebenen“.
- **Eigenschaften rechts:** Felder je Art mit den Bereichen aus Stufe 1. Der Text wird auch hier in einem mehrzeiligen Feld bearbeitet. Die Rolle ist wählbar, mit dem Hinweis, dass Anrede und Links nur im Fließtext ohne Drehung erlaubt sind.
- **Speichern:**
  - `speicherGrund` blockiert mit Meldung.
  - Bei einem Konflikt öffnet sich der Dialog „Inzwischen gibt es eine neuere Fassung“ mit „Neu laden“ (Seite neu laden) und „Als Kopie behalten“ (`alsKopie = true`).
  - Bei Erfolg wird `basis` auf die neue Fassung gesetzt und `gespeichert()` aufgerufen.
  - Beim Verlassen mit ungespeicherten Änderungen erscheint ein `beforeunload`-Hinweis.
- **Handy (unter `HANDY_GRENZE`):** `HandyAnsicht` mit `ohneAssistent` und der Vorschau `vorschauAdresse(vorschau_url, basis)`.

- [ ] **Step 1: Write the failing tests:**
  - `seitePult.test.ts` (fetch gestubbt):
    - 200 `{fassung: 4}` → `{ok: true, fassung: 4}`.
    - 409 `{konflikt: true}` → `{ok: false, konflikt: true}`.
    - 422 `{grund: 'X'}` → `{ok: false, grund: 'X'}`.
    - Der Request hat den Header `X-CSRF` und einen Body mit `seite`, `basis_fassung` und `als_kopie`.
  - `SeiteApp.test.tsx` (`renderToStaticMarkup` mit einer Start-Fixture, die eine Seite mit je einer Ebene jeder Art enthält):
    - Das Markup enthält die Ebenen in Array-Reihenfolge.
    - Ein Bild hat `src` mit `/medien/datei/`, nicht `medien:`.
    - Der Fließtext hat `font-family:Arial, Helvetica, sans-serif`.
    - Der Hinweis zum Assistenten ist vorhanden.
    - Es gibt keinen Block-Editor (kein `EditorBlock`-Markup).
  - `HandyApp.test.tsx`: `HandyAnsicht` mit `ohneAssistent` rendert keinen Reiter „Assistent“.
- [ ] **Step 2: Run** `npx vitest run src/seitePult.test.ts src/App/Seite src/App/Handy`. Expected: FAIL.
- [ ] **Step 3: Implement** die Dateien und Änderungen. Die Interaktionslogik ruft nur die Funktionen aus Task 4 auf, keine eigene Geometrie in Komponenten.
- [ ] **Step 4: Run** `npx tsc --noEmit -p . && npx vitest run && npm run build`. Danach `pytest tests/test_editor_paket.py -q` und `pytest tests/test_editor_seite.py -q`. Expected: alles PASS, außer dem vorbestehenden Fehler. Bundle-Größe vorher/nachher notieren.
- [ ] **Step 5: Commit** `git commit -m "feat(editor): Collage-Oberflaeche - verschieben, drehen, skalieren, Text, Hoehe, Speichern"` mit allen neuen Dateien plus `sales-mcp/static/editor/editor.js`, `editor.css` und `MANIFEST.json`.

### Task 6: Livegang und Abnahme im Browser (nur mit User-OK)

- [ ] **Step 1:** WORKBOARD-Claim setzen, nur die eigene Zeile stagen.
- [ ] **Step 2:** Auf den neuesten Stand von `origin/feat/stufe-1-fundament` rebasen und die Tests aus Task 1, 2 und 5 erneut laufen lassen. Bei einem Bundle-Konflikt den Build neu erzeugen, nie von Hand mergen.
- [ ] **Step 3:** User um OK fragen. Mit OK: pushen, dann `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Expected: „ALLE PRUEFUNGEN GRUEN“, sales-ui und ivan-ui mit neuem Stand.
- [ ] **Step 4: Abnahme mit Playwright (Scratch-venv) gegen die lokale sales-ui-Testinstanz oder den Test-Client:**
  - Editor-HTML für eine Collage-Fixture laden und bei 1280 px fotografieren.
  - Prüfen: Ebenen sitzen wie im Probe-PDF aus Stufe 1, und es gibt kein seitliches Scrollen.
  - Danach den User bitten, eine echte Collage über „Neue Collage“ anzulegen, eine Ebene zu verschieben und zu speichern.
- [ ] **Step 5:** Claim schließen, Worktree entfernen.

## Folgepläne

- **Stufe 3, Assistent:** Werkzeuge für Seiten, Prüfbild per Screenshot von `seite_html.html`, bis zu 3 Nachbesserungsrunden, Chat-Sperre aufheben, Assistent-Reiter am Handy wieder einblenden.
- **Stufe 4, Mail und Versand.**
- **Stufe 5, Schönheitsprüfung und Vorlagen.**
