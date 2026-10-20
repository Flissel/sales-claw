# Freie Fläche – Stufe 5: Schönheitsprüfung, Collage-Vorlagen, nur noch Collagen – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Collagen werden vor dem Einreichen auf Lesbarkeit geprüft. Unleserlicher Text blockiert das Einreichen, alles andere sind Hinweise.
- Der Assistent sieht dieselben Befunde.
- Es gibt 8 Collage-Vorlagen, die der Betreiber freigibt und die beim Anlegen mit der Marke der Firma gefüllt werden.
- Sobald eine Collage-Vorlage freigegeben ist, entstehen keine neuen Block-Newsletter mehr.

**Architecture:**
- **Prüfung:** Eine reine Prüfung `claw/seite_schoenheit.py` nimmt Seite, Maße und zwei Renderings: einmal komplett, einmal ohne Text- und Knopf-Ebenen. Sie misst den Kontrast jeder Textebene gegen die tatsächlichen Pixel darunter.
  - Auf der VM berechnet die API die Prüfung pro Fassung, legt das Ergebnis in den Speicher und blockiert damit das Einreichen.
  - Am PC rechnet der Chat-Arbeiter sie in den Nachbesserungsrunden mit.
- **Vorlagen:** Sie bekommen in `newsletter_vorlagen` ein Format `seite` und eine Rollentabelle (welche Farbe Akzent, Grund oder Text ist, welche Ebene das Logo ist, welche Bildebene ein Motiv mit Beschreibung ist).
  - `claw/seite_vorlagen.py` füllt eine Vorlage mit der Marke und repariert den Kontrast.
  - Ein Skript erzeugt die 8 Vorlagen mit dem Assistenten als Vorschläge. Der Betreiber gibt sie in sales frei.

**Tech Stack:** wie Stufen 1–4: Python, FastAPI, Postgres, Playwright/Chromium, Pillow, React/TS.

**Spec:** sales-claw `docs/superpowers/specs/2026-10-20-freie-flaeche-newsletter-design.md`, Abschnitte 4.5, 4.6, 4.8. Stufen 1–4 sind live (vibemind-os bis `d4f62f35`, sales-claw bis `0dd0417`).

**Repos:**
- Tasks 1–6 in vibemind-os `master`, Pfade relativ zu `spaces/marketing/`.
- Task 7 in sales-claw `feat/stufe-1-fundament`.
- Jeweils eigene Worktrees.

## Global Constraints

- **Harte Befunde (blockieren das Einreichen):**
  - Textkontrast unter **4,5:1**. Bei Schriftgröße ≥ 24 gilt **3:1**.
  - Gemessen wird die Textfarbe gegen den Median der Hintergrundpixel innerhalb der gemessenen Hülle der Ebene, aus dem Rendering ohne Text- und Knopfebenen.
  - Bei einer Textebene mit `hintergrund` gilt die Hintergrundfarbe statt der Pixel.
  - Anrede oder Link im Bildbereich bleibt wie in Stufe 4 hart.
- **Weiche Befunde (Hinweise):**
  - Fließtext (`TEXT`) unter 15.
  - Mehr als 3 verschiedene Schriftgrößen auf der Seite.
  - Kein Knopf.
  - Mehr als 2 laute Elemente: gedrehte Ebenen mit |drehung| ≥ 2 sowie `HAND`-Text.
  - Text, der die Ruhezone verletzt (gemessene Hülle näher als 24 Einheiten an der linken oder rechten Seitenkante).
- **Befund-Form** wie `claw/schoenheit.befund`: `{schwere: 'hart'|'weich', punkt: <ebene-id|'seite'>, satz: <deutscher Text>}`. Die Sätze sind kurz, nennen die Ebene und den Wert, zum Beispiel „titel: Kontrast 2,1:1 auf dem Bild – mindestens 3:1“.
- **Vorlagen-Rollen:**
  - Farbrollen: `akzent`, `zweitfarbe`, `grund`, `text`, `auf_akzent` (lesbare Farbe auf Akzent).
  - Ebenenrollen: `logo` (Bild-Ebene, bekommt das Markenlogo), `motiv:<Beschreibung>` (Bild-Ebene, beim Anlegen per `bild_erzeugen` neu erzeugt), `name` (Text-Ebene, bekommt den Firmennamen).
  - Gespeichert als `rollen jsonb` neben der Seite, nie in der Seite selbst.
- **Füllen:**
  - Markenschriften setzen (`schriften.anzeige/text`).
  - Farben nach Rollen ersetzen.
  - Logo einsetzen, oder die Ebene entfernen, wenn die Firma keins hat.
  - Für jede `motiv`-Ebene einen Bildauftrag nach dem Anlegen anstoßen.
  - Danach Kontrast reparieren: Jede Textfarbe, die gegen ihre bekannte Unterlage (Rollenfarbe der darunterliegenden Form oder des Seitengrunds) unter der Schwelle liegt, wird auf die lesbarere von `text` und `#ffffff` gesetzt.
- **Freigabe:** Vorlagen entstehen als `vorschlag`, der Betreiber stellt sie in sales auf `freigegeben` oder `zurueckgezogen`. Nur freigegebene Vorlagen werden beim Anlegen angeboten (wie heute).
- **Nur noch Collagen:**
  - Gibt es für eine Firma mindestens eine freigegebene Collage-Vorlage (eigene oder `fuer_alle`), lehnt die API das Anlegen neuer Block-Newsletter aus Vorlagen mit 409 ab: „Neue Newsletter entstehen als Collage – bitte eine Collage-Vorlage wählen“.
  - Die sales-Oberfläche bietet dann nur noch Collage-Vorlagen und „Neue Collage“.
  - Bestehende Block-Newsletter bleiben bearbeitbar und versendbar (Entscheidung 11).
- **Vorlagen-Erzeugung:** 8 Vorlagen mit unterschiedlichen Grundformen. Es sind die 6 aus dem Collage-Prompt (Split, randloser Aufmacher mit Titelband, Schrift-Plakat, versetztes Zwei-Bild-Raster, Polaroid-Streuung, Farbbühne mit freigestelltem Motiv) plus „Magazin-Titel“ und „Zitat-Bühne“. Sie werden mit der Marke vibemind gestaltet und als `fuer_alle = true` vorgeschlagen.
- Block-Newsletter- und Block-Vorlagenverhalten bleiben sonst unverändert.
- Die Migration hat die nächste freie Nummer ≥ 082. Ausgerollt wird in der Reihenfolge Migration → Arbeiter → API → sales.

## Review Focus

1. **Text auf einem Foto**, gemessene Hintergrund-Pixel sehr unruhig: Gemessen wird gegen den Median, damit kein Ausreißer zählt. Test: `test_kontrast_gegen_median_unruhiges_bild` (Task 1).
2. **Vorlage für eine Firma ohne Logo:** Die Logo-Ebene entfällt, keine kaputte Bildquelle. Test: `test_fuellen_ohne_logo` (Task 3).
3. **Helle Akzentfarbe** (z. B. Gelb) mit weißer Knopfschrift: Die Reparatur setzt die Knopfschrift auf die Textfarbe. Test: `test_kontrast_reparatur_heller_akzent` (Task 3).
4. **Prüfung schlägt technisch fehl** (Chromium weg): Das Einreichen wird nicht blockiert, nur der Inhalt blockiert. Die Prüfung meldet 503 und das Einreichen läuft wie in Stufe 4 weiter, weil die Mail-Erzeugung ohnehin Chromium braucht und dann selbst 503 gibt. Test: `test_pruefung_503_blockiert_nicht_inhaltlich` (Task 4).
5. **Firma hat Block-Vorlagen, aber keine freigegebene Collage-Vorlage:** Das Anlegen aus Block-Vorlage geht weiter. Test: `test_block_anlegen_ohne_collage_vorlage_erlaubt` (Task 4).

---

### Task 1: Prüfung `claw/seite_schoenheit.py`

**Files:** Create `claw/seite_schoenheit.py`, `claw/tests/test_seite_schoenheit.py`

**Interfaces – Produces:**
- `regeln(seite: dict, masse: dict | None) -> list[dict]`: die rein geometrischen und typografischen Befunde (alle weich).
- `kontraste(seite: dict, masse: dict, png_ohne_text: bytes, faktor: int) -> list[dict]`: harte Kontrastbefunde aus den Pixeln.
- `pruefen(seite: dict, masse: dict, png_ohne_text: bytes, faktor: int) -> list[dict]`: beides zusammen, sortiert nach hart, dann weich.
- `seite_ohne_text(seite: dict) -> dict`: Kopie ohne Text- und Knopfebenen, für das zweite Rendering.
- Wiederverwenden: `schoenheit.kontrast`, `schoenheit.befund`, `KONTRAST_TEXT`, `KONTRAST_GROSS`.

- [ ] Step 1: Tests:
  - weiße Schrift auf dunklem Bild-PNG → kein Befund
  - weiße Schrift auf hellem PNG → hart mit Wert
  - Größe ≥ 24 mit 3,5:1 → kein harter Befund
  - Textebene mit `hintergrund` → deren Farbe zählt
  - `test_kontrast_gegen_median_unruhiges_bild`
  - jede weiche Regel einmal positiv und einmal negativ
  - `seite_ohne_text` entfernt nur Text und Knopf
- [ ] Steps 2–4: Rot, umsetzen, grün.
- [ ] Step 5: Commit `feat(marketing): Schoenheitspruefung fuer Collage-Seiten`

### Task 2: Migration – Collage-Vorlagen und Freigabe

**Files:** Create `db/0NN_seite_vorlagen.sql`, `db/verify_0NN.sql`

**Interfaces – Produces:**
- `newsletter_vorlagen` und `newsletter_vorlagen_fassungen` bekommen `format text NOT NULL DEFAULT 'bloecke'` (`'bloecke'|'seite'`), `seite jsonb`, `rollen jsonb`. Die Block-CHECKs gelten nur noch bei `format = 'bloecke'`, bei `format = 'seite'` gilt `pult_seite_fehler(seite) IS NULL`. `bloecke` wird bei Seiten NULL-fähig, die CHECKs wie in 053/068 werden neu angelegt.
- `pult_vorlage_seite_speichern(p_name, p_beschreibung, p_seite jsonb, p_rollen jsonb, p_von, p_status, p_fuer_alle boolean) RETURNS int`: Upsert und neue Fassung wie `pult_vorlage_speichern`.
- `pult_vorlage_entscheiden(p_name, p_urteil 'freigeben'|'zurueckziehen', p_von) RETURNS text`: nur von `vorschlag` oder `freigegeben` aus, mit deutschen Gründen.
- `pult_collage_aus_vorlage(p_vorlage, p_titel, p_mandant, p_seite jsonb, p_von) RETURNS uuid`: nur freigegebene Seiten-Vorlagen (eigene oder `fuer_alle`). Legt den Inhalt wie `pult_collage_anlegen` mit der schon gefüllten Seite an.
- `pult_hat_collage_vorlage(p_mandant) RETURNS boolean`
- Rechte wie 077/081.

- [ ] Verify-Abschnitte:
  - Seiten-Vorlage speichern und Fassung zählen
  - ungültige Seite abgelehnt
  - Block-Vorlage unverändert speicherbar
  - entscheiden in allen Übergängen
  - aus Vorlage nur bei freigegeben
  - `pult_hat_collage_vorlage`
  - bestehende Zeilen bleiben gültig
- [ ] Probe `0NN verify 0NN verify` → `PROBE OK`. Commit `feat(marketing): Migration Collage-Vorlagen und Vorlagen-Freigabe`

### Task 3: Füllen und Rollen `claw/seite_vorlagen.py`

**Files:** Create `claw/seite_vorlagen.py`, `claw/tests/test_seite_vorlagen.py`

**Interfaces – Produces:**
- `rollen_ableiten(seite: dict, marke: dict) -> dict`: ordnet Farben, die exakt (Groß- und Kleinschreibung egal) einer Markenfarbe entsprechen, der Rolle zu. Ebenen, deren Quelle das Markenlogo ist, bekommen `logo`, Bild-Ebenen mit erzeugten Motiven bekommen `motiv:<Beschreibung aus der Ebenen-ID oder dem Bildauftrag>`, eine Textebene mit dem Firmennamen bekommt `name`.
- `fuellen(seite: dict, rollen: dict, marke: dict, logo_medium: str | None) -> tuple[dict, list[dict]]`: gefüllte, mit `seite.pruefen` gültige Seite plus Liste der Bildaufträge `{platz, modus: 'neu', hinweis}` für Motiv-Ebenen.
- `kontrast_reparieren(seite: dict, rollen: dict) -> dict`
- Marken-Eingabe wie `_marke_fuer_seite`, erweitert um `zweitfarbe`, `grund`, `text`, `name`, `logo`, `logo_dunkel`.

- [ ] Tests:
  - Rundlauf: Ableiten, dann mit derselben Marke füllen, ergibt Farben wie vorher.
  - Andere Marke → Akzentfarben getauscht.
  - `test_fuellen_ohne_logo`
  - `test_kontrast_reparatur_heller_akzent`
  - Motiv-Ebenen ergeben Bildaufträge.
  - Ergebnis besteht `seite.pruefen`.
- [ ] Commit `feat(marketing): Collage-Vorlagen fuellen und Rollen ableiten`

### Task 4: API – Prüfung, Einreichen-Sperre, Vorlagen-Routen, nur noch Collagen

**Files:** Modify `api/seite_mail_dienst.py` (Prüfung neben der Mail-Erzeugung, Rendering wiederverwenden), `api/freigabe.py`, `api/pult.py`. Tests.

**Interfaces – Produces:**
- `GET /inhalte/{iid}/pruefung?fassung=n` → `{befunde: [...]}`
  - Rendert auf der VM einmal voll, mit Maßen, und einmal ohne Text, unter derselben Sperre und mit denselben Zeitlimits wie `seite_bilder`.
  - Das Ergebnis liegt pro (Inhalt, Fassung) 10 Minuten im Speicher.
  - Ein technischer Fehler ergibt 503.
- **Einreichen einer Collage:** Erst Prüfung. Gibt es harte Befunde, kommt 422 mit dem ersten harten Satz und dem Zusatz „(weitere: n)“, dann geht es weiter wie in Stufe 4. `test_pruefung_503_blockiert_nicht_inhaltlich`: Bei 503 der Prüfung läuft das Einreichen weiter wie in Stufe 4.
- **Vorlagen:**
  - `GET /vorlagen` liefert `format` (und `status`, auch `vorschlag`, wenn `status=vorschlag` angefragt wird).
  - `GET /vorlagen/{name}/vorschau?format=seite` für Seiten-Vorlagen liefert die gefüllte Seite als HTML.
  - `POST /inhalte/aus_vorlage` erkennt Seiten-Vorlagen: füllen mit der Marke (`seite_vorlagen.fuellen`), dann `pult_collage_aus_vorlage`, dann Bildaufträge über die bestehende Bildkette (`bilder._anlegen`).
  - `POST /vorlagen/{name}/entscheiden {urteil, von}`
- **Nur noch Collagen:** `aus_vorlage` mit einer Block-Vorlage wird mit 409 und dem Text aus den Global Constraints abgelehnt, wenn `pult_hat_collage_vorlage(mandant)`. `test_block_anlegen_ohne_collage_vorlage_erlaubt`.
- [ ] Tests für alles oben. Bestehende Block-Tests bleiben grün. Commit `feat(marketing): Pruefung vor dem Einreichen, Collage-Vorlagen, nur noch Collagen`

### Task 5: Assistent bekommt Befunde

**Files:** Modify `workers/seite_pruefbild.py` (zweites Rendering ohne Text plus Maße am PC; Maße per DOM wie `seite_bilder`), `workers/chat_worker.py` (`_bearbeiten_seite`: Befunde jeder Prüfrunde in `hinweise` für `pruef_text`). Tests.

- [ ] Tests:
  - Prüfrunde mit gefälschtem Renderer liefert harte Kontrastbefunde in den Hinweisen.
  - Fehler im zweiten Rendering → nur Hinweis „Prüfung nicht möglich“, kein Abbruch.
  - Rendering bleibt einzeln (`_PRUEFBILD_SPERRE`).
- [ ] Commit `feat(marketing): Assistent sieht die Schoenheitspruefung`

### Task 6: Vorlagen erzeugen `scripts/collage_vorlagen_erzeugen.py`

**Files:** Create `scripts/collage_vorlagen_erzeugen.py`, `tests/test_collage_vorlagen_erzeugen.py`

**Verhalten:**
- Für jede der 8 Grundformen:
  1. Eine Probe-Collage (Firma vibemind) über die API anlegen.
  2. Eine Chat-Runde mit einem Auftrag starten. Der Auftrag nennt Grundform, Thema „Vorlage: <Grundform>“ und Platzhalter-Inhalte („Überschrift“, „Kurzer Einleitungstext …“, „Mehr erfahren“) sowie die Bitte, Motive per `bild_erzeugen` mit neutraler, branchenoffener Beschreibung anzulegen.
  3. Auf Rundenende warten, mit Zeitlimit 20 Minuten pro Runde und Status-Erkennung über `chat_auftraege`. Dann auf erzeugte Bilder warten: Fassung 3 Minuten stabil, höchstens 10 Minuten.
  4. Neueste Seite holen, `rollen_ableiten` mit der vibemind-Marke ausführen und als Vorschlag speichern (`pult_vorlage_seite_speichern`, Status `vorschlag`, `fuer_alle = true`, Name `collage-<grundform-slug>`).
  5. Probe löschen.
- `--nur <slug>` für eine einzelne Vorlage, `--trocken` zeigt nur die Aufträge.
- Schlüssel nur aus der Umgebung, mit strip. Fehlermeldungen nie mit Kopfzeilen.
- [ ] Tests mit gefälschter API: Ablauf, Zeitlimits, Aufräumen bei Fehler. Commit `feat(marketing): Skript fuer die 8 Collage-Vorlagen`

### Task 7: Oberfläche (sales-claw)

**Files:**
- `sales-mcp/ui_editor.py`: Vorlagenseite
  - zuerst die Collage-Vorlagen, mit Vorschau `format=seite`
  - Abschnitt „Vorschläge“ mit Freigeben und Verwerfen (Formulare, CSRF)
  - Block-Vorlagen ausblenden, wenn eine Collage-Vorlage freigegeben ist
  - der Editor-Reiter „neu aus Vorlage“ ebenso
- `sales-mcp/ui_marketing.py`: Galerie-Knöpfe wie oben.
- Editor `editor/src/App/Seite/*`: Knopf „Prüfen“ mit Befundliste (hart rot, weich grau, Klick wählt die Ebene). Die Befunde werden über einen neuen sales-Proxy `GET /marketing/editor/{iid}/pruefung` geholt. Der 422-Grund beim Einreichen wird wie bisher gezeigt.
- Tests und Bundle.
- [ ] Commit `feat(marketing-ui): Collage-Vorlagen, Vorlagen-Freigabe und Pruefung im Editor`

### Task 8: Livegang, Vorlagen erzeugen, Abnahme

- [ ] Claims setzen. Migration nach Sicherung einspielen, verify. Ausrollen: Arbeiter → API (VM und PC) → sales.
- [ ] `scripts/collage_vorlagen_erzeugen.py` auf der VM im Hintergrund laufen lassen, die Chat-Runden laufen über den PC-Arbeiter. Die 8 Vorschläge mit PDF-Bildern prüfen.
- [ ] Abnahme:
  - Collage mit absichtlich schlechtem Kontrast → Einreichen 422 mit Satz.
  - Eine eigene **Probe-Vorlage** (nicht eine der 8) vorschlagen, freigeben, mit einer anderen Firma (Ivan, fin2gether) als Probe anlegen → Farben, Schriften und Logo getauscht, Prüfung ohne harte Befunde.
  - Block-Anlegen danach 409.
  - Probe-Vorlage zurückziehen (Block-Anlegen geht wieder), Proben löschen.
  - **Die 8 erzeugten Vorlagen bleiben `vorschlag`.** Freigeben ist die Entscheidung des Betreibers, und erst damit greift „nur noch Collagen“.
- [ ] Claims schließen, Worktrees entfernen.
