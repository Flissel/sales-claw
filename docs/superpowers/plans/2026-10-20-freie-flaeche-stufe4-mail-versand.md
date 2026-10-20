# Freie Fläche – Stufe 4: Mail-Fassung, Einreichen und Versand – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collage-Newsletter bekommen eine echte Mail-Fassung (Textstreifen und Bildstücke) und lassen sich einreichen, freigeben und über sales-claw versenden. Der Collage-Editor wird beim Status „eingereicht“ schreibgeschützt.

**Architecture:**
- **Streifen-Plan:** Ein reiner Planer `claw/seite_streifen.py` zerlegt die Seite in waagrechte Bänder („text“ oder „bild“).
- **Mail-Bau:** `claw/seite_mail.py` baut daraus MJML (mrml, wie `bloecke_mjml`), die Textfassung und die Medienliste.
- **Bilder auf der VM:** `claw/seite_bilder.py` rendert die Seite in Chromium mit Gerätefaktor 2. Medien und Schriften kommen von der lokalen Platte, Bänder werden zu JPEG-Stücken.
- **Speicherung:** Die API erzeugt die Mail-Fassung einmal je (Inhalt, Fassung) und speichert sie in einer neuen Tabelle. Die Stücke liegen in `MARKETING_BILD_ORDNER`, den sales-claw als `/media-erzeugt` liest.
- **Einreichen:** Beim Einreichen wird die Mail-Fassung erzeugt und geprüft (8 MB). Versand und Mail-Vorschau lesen sie danach.

**Tech Stack:** Python 3.11, mjml-python (mrml) 1.4.2, Playwright/Chromium in `~/marketing-os/.venv` auf der VM (schon für PDF im Einsatz), Pillow, Postgres. Editor: React/TS.

**Spec:** sales-claw `docs/superpowers/specs/2026-10-20-freie-flaeche-newsletter-design.md`, Abschnitte 4.3, 4.6, 5 sowie die Entscheidungen 9, 10 und 11. Stufen 1–3 sind live (vibemind-os bis `09e38077`, sales-claw bis `f369943`).

**Repos:**
- Tasks 1–4 in vibemind-os `master`, Pfade relativ zu `spaces/marketing/`.
- Task 5 in sales-claw `feat/stufe-1-fundament`.
- Jeweils eigener Worktree unter `C:/Users/User/ClaudeWork/`.

## Global Constraints

- **Mail-Breite 600.** Stücke werden mit Gerätefaktor 2 gerendert, sind also 1200 Pixel breit und werden in der Mail mit `width=600` gezeigt.
- **Ein Band ist „text“, wenn alle Ebenen, die es schneidet, text-tauglich sind:**
  - **Fließtext:** Textebene mit `rolle = TEXT`, `drehung = 0`, `deckkraft = 1`, `hintergrund = null`, deren Rahmen keine andere Ebene schneidet.
  - **Knopf:** Knopf-Ebene mit `drehung = 0`, die keine andere Ebene schneidet.
  - **Kein Seiten-Hintergrundbild:** `hintergrund.bild = null`.
  - Alles andere wird „bild“.
- **Rahmen:** Ein Rahmen ist die achsenparallele Hülle der gedrehten Ebene.
- **Bildbänder:** höchstens **600 Einheiten** hoch, also 1200 Pixel. Längere Bildbänder werden geteilt.
- **Textbänder in MJML:** echter Text in `mj-text` mit dem mail-sicheren Stapel (`schriften.REGISTER[id]["stapel"]`), Größe, Gewicht, Zeilenabstand, Farbe, Ausrichtung, Großbuchstaben und Kursiv wie in `seite_html`. Der seitliche Versatz folgt dem Rahmen der Ebene (`padding-left = x − breite/2`), der Abstand nach oben ergibt sich aus den y-Abständen.
- **Knöpfe:** in Textbändern als `mj-button`. In Bildbändern ist das ganze Stück mit dem Link des ersten Knopfs in diesem Band verlinkt, und der Alt-Text nennt den Knopftext.
- **Alt-Text** jedes Stücks: der Text aller Text- und Knopf-Ebenen, die das Stück schneidet, in Lesereihenfolge (y, dann x), höchstens 300 Zeichen. Ohne Text: „Bild“.
- **Textfassung** (`text`): alle Text- und Knopf-Ebenen in Lesereihenfolge. Knöpfe als „Text: url“. Danach `--`, Impressum, Abmelde-Hinweis, wie `bloecke_mjml.text_fassung`.
- **Platzhalter:** In der Versandfassung bleiben `{vorname}` und `{abmeldelink}` stehen, in der Vorschau werden sie zu `[Vorname]` und `[Abmeldelink]`, wie bei Blöcken. Ein `{vorname}` in einem Bildstück ist ein Fehler, der das Einreichen blockiert: „Die Anrede steht in einem Bildbereich – sie muss in frei stehendem Fließtext stehen“.
- **Größe:** Summe aller Stücke höchstens **8 MB**. Darüber blockiert das Einreichen mit „Die Mail wäre zu groß (X,Y MB, höchstens 8 MB) – weniger oder kleinere Bildbereiche“. JPEG-Qualität beginnt bei 82 und sinkt bis 60, bevor die Grenze greift.
- **Dateinamen der Stücke:** `ms-<inhalt 8 hex>-<fassung>-<nr 2-stellig>.jpg`. Sie werden **nicht** von der `gs-`-Müllabfuhr gelöscht und der Firma zugeordnet wie Export-Dateien (`_ablegen_und_zuordnen`).
- **Pflicht-Fuß** wie `bloecke_mjml` (Impressum, Abmelde-Hinweis, Kontrastfarbe).
- **Block-Newsletter unverändert.** Einreichen, Freigabe und Versand für Blöcke behalten jedes Verhalten.
- Collage-Editor bei `eingereicht` schreibgeschützt (Ruling aus Stufe 2).
- Livegang nur in der Reihenfolge Migration → API → Editor. Die neue Migration hat die **nächste freie Nummer ≥ 081**, vorher auf `origin/master` prüfen.

## Review Focus

1. **Text, der zwischen zwei Bildbereichen eingeklemmt ist und sie berührt:** Er wird Teil des Bildbands, nicht doppelt gerendert (als Bild und als Text). Test: `test_text_an_bild_wird_bild` (Task 1).
2. **Seite ganz ohne Bildbänder** (nur Fließtext und Knopf): Die Mail hat null Stücke und ist reines MJML. Test: `test_nur_text_ohne_stuecke` (Task 2).
3. **Seite mit Hintergrundbild:** Alles wird zu Bildbändern, und die Anrede blockiert mit dem Fehlertext. Test: `test_hintergrundbild_alles_bild` (Task 1), `test_anrede_im_bild_blockiert` (Task 4).
4. **Gleiche Fassung zweimal einreichen oder versenden:** Die Mail-Fassung wird nur einmal erzeugt und wiederverwendet. Test: `test_mailfassung_einmal` (Task 4).
5. **Medium fehlt beim Rendern:** Einreichen bricht mit deutschem Grund ab, es entsteht keine halbe Mail. Test: `test_fehlendes_medium_blockiert` (Task 3/4).

---

### Task 1: Streifen-Planer `claw/seite_streifen.py`

**Files:** Create `claw/seite_streifen.py`, `claw/tests/test_seite_streifen.py`

**Interfaces – Produces:**
- `rahmen(e: dict) -> tuple[float, float, float, float]`: links, oben, rechts, unten der achsenparallelen Hülle nach Drehung.
- `text_tauglich(e: dict, alle: list[dict], seite: dict) -> bool`: Regeln aus den Global Constraints.
- `@dataclass Band(art: Literal["text", "bild"], oben: float, unten: float, ebenen: list[str])`
- `plan(seite: dict) -> list[Band]`
  - Deckt 0..hoehe lückenlos ab, sortiert nach `oben`.
  - Bildbänder sind höchstens 600 hoch.
  - Leere Bereiche ohne Ebenen hängen am Nachbarband: Ein Band mit nur Seitenhintergrund ist „text“ mit leerer Ebenenliste und wird als Abstand gerendert.
  - Eine text-taugliche Ebene, deren Rahmen in ein Bildband ragt, macht das ganze Band zu „bild“.
  - Bänder werden an Grenzen geschnitten, die keine Ebene durchschneiden. Lässt sich ein Bildband nur mitten durch eine Ebene teilen, wird mitten durch geschnitten, das ist für Bilder unschädlich.
- `lesereihenfolge(ebenen: list[dict]) -> list[dict]`: sortiert nach (oben, links).

- [ ] **Step 1:** Tests:
  - nur Fließtext und Knopf → nur Textbänder
  - gedrehte Überschrift → Bildband über ihrem Rahmen
  - Bild unter Text → beides Bild
  - `test_text_an_bild_wird_bild`
  - Bildband über 1400 Höhe → 3 Bänder je ≤ 600
  - `test_hintergrundbild_alles_bild`
  - Lücken werden lückenlos abgedeckt
  - `rahmen` einer um 90° gedrehten 100×50-Ebene ist 50×100
- [ ] **Step 2–4:** Rot, umsetzen, grün.
- [ ] **Step 5:** Commit `feat(marketing): Streifen-Planer fuer die Mail-Fassung von Collagen`

### Task 2: Mail-Bau `claw/seite_mail.py`

**Files:** Create `claw/seite_mail.py`, `claw/tests/test_seite_mail.py`

**Interfaces:**
- Consumes: `seite_streifen.plan/lesereihenfolge`, `seite_html`-Hilfen für Inline-Auszeichnung (wiederverwenden, nicht kopieren), `bloecke_mjml` (Fuß, `RenderFehler`, Platzhalter-Ersetzung wiederverwenden).
- Produces:
  - `@dataclass Stueck(nr: int, oben: float, unten: float, alt: str, link: str | None)`
  - `stuecke(seite: dict) -> list[Stueck]` (aus den Bildbändern)
  - `mjml(seite: dict, stuecke_namen: list[str], *, betreff: str, vorschautext: str, pflichtteil: dict, bild_adresse: Callable[[str], str], fuer_versand: bool) -> str`
  - `rendern(...) -> str` (MJML zu HTML über mrml, gleiche Fehlerbehandlung wie `bloecke_mjml.rendern`)
  - `text_fassung(seite: dict, pflichtteil: dict) -> str`
  - `versand_medien(stuecke_namen: list[str]) -> list[dict]` (Form wie `bloecke_mjml.versand_medien`: `{name, cid, sw: False}`)

- [ ] **Step 1:** Tests:
  - `test_nur_text_ohne_stuecke`
  - Textband erzeugt `mj-text` mit Arial-Stapel, ohne Webschrift
  - `{vorname}` bleibt bei `fuer_versand=True`, sonst `[Vorname]`
  - `**fett**` wird `<strong>`, Link nur https
  - Knopf im Textband wird `mj-button` mit href
  - Bildband wird `mj-image` mit `width="600px"`, Alt-Text aus dem Text und href des ersten Knopfs
  - Fuß mit Impressum und Abmelden
  - `text_fassung`-Reihenfolge
  - gerendertes HTML enthält `mso` (Outlook-Kommentare)
  - kein `<script`
- [ ] **Step 2–4:** Rot, umsetzen, grün.
- [ ] **Step 5:** Commit `feat(marketing): Mail-Fassung fuer Collagen (MJML, Text, Medien)`

### Task 3: Stücke rendern `claw/seite_bilder.py` (läuft auf der VM)

**Files:** Create `claw/seite_bilder.py`, `tests/test_seite_bilder.py`

**Interfaces – Produces:**
- `class StueckFehler(RuntimeError)`
- `render_png(seite: dict, medien_lesen: Callable[[str], bytes | None], *, faktor: int = 2) -> bytes`
  - Rendert `seite_html.html(seite, betreff="", pflichtteil={}, bild_basis=BASIS+"medien/", schrift_basis=BASIS+"schrift/")` in Chromium (Playwright sync, JavaScript aus) mit `device_scale_factor=faktor`.
  - Die Route-Weiche liefert `/medien/*` aus `medien_lesen`, `/schrift/*` aus `claw/schriftdateien` und `schriften.css` wie `export_worker`. Alles andere wird abgebrochen.
  - Ein fehlendes Medium oder ein Platzhalter-Name führt zu `StueckFehler("Bild <name> fehlt")`. In einer Mail darf kein Platzhalter stehen.
  - Fotografiert nur den Seitencontainer.
- `zuschneiden(png: bytes, stuecke: list[Stueck], faktor: int = 2, max_bytes: int = 8 * 1024 * 1024) -> list[bytes]`: JPEG je Stück, Qualität 82 → 60, sonst `StueckFehler` mit der MB-Meldung aus den Global Constraints.

- [ ] **Step 1:** Tests:
  - mit gefälschtem PNG: Zuschnitt-Höhen = (unten − oben) × 2, Breite 1200
  - Größengrenze greift mit verständlicher Meldung
  - `test_fehlendes_medium_blockiert`
  - Platzhalter blockiert
  - Ein echter Playwright-Rauchtest, markiert `browser`: Seite mit Text und einer Form ergibt PNG 1200 breit.
- [ ] **Step 2–4:** Rot, umsetzen, grün. Den Rauchtest einmal am PC laufen lassen und berichten.
- [ ] **Step 5:** Commit `feat(marketing): Bildstuecke der Collage-Mail rendern`

### Task 4: Migration, API-Dienst, Einreichen und Versand für Collagen

**Files:**
- Create `db/0NN_seite_mail.sql`, `db/verify_0NN.sql` (NN = nächste freie Nummer)
- Modify `api/pult.py` (Vorschau mail/handy für `seite`, Versand für `seite`, `_festgeschrieben`), `api/freigabe.py` (Einreichen)
- Create `api/seite_mail_dienst.py`
- Modify `api/gestaltung.py`, falls die Müllabfuhr `ms-` treffen könnte (sie darf es nicht)
- Tests `tests/test_seite_mail_dienst.py`, `tests/test_pult_api.py`, `tests/test_freigabe_api.py`

**Interfaces:**
- Tabelle `marketing.seite_mailfassungen(inhalt uuid, fassung int, html_versand text, html_vorschau_mjml text, text text, medien jsonb, bytes int, erstellt_am timestamptz, PRIMARY KEY (inhalt, fassung))`, FK auf `inhalt_fassungen`. Funktionen:
  - `pult_seite_mail_speichern(...)`, idempotent mit `ON CONFLICT DO NOTHING`
  - `pult_seite_mail_lesen(inhalt, fassung)`
  - Rechte wie 077
- `seite_mail_dienst.erzeugen(i: str, fassung: int) -> dict`
  - Holt die Seite der Fassung und gibt eine vorhandene Mail-Fassung zurück, wenn es sie schon gibt.
  - Sonst `plan`, `stuecke`, `render_png` (Medien aus `MARKETING_MEDIEN_ORDNER` und `MARKETING_BILD_ORDNER`), `zuschneiden` und Dateien `ms-…jpg` schreiben (Zuordnung zur Firma wie `_ablegen_und_zuordnen`). Danach das MJML für den Versand mit `cid:` und für die Vorschau mit signierter `bild_basis` erzeugen, `text_fassung` erstellen und speichern.
  - Die Anrede-im-Bild-Prüfung läuft vorher.
  - Fehler werden als `HTTPException(422, Grund)` gemeldet.
- **Einreichen** (`api/freigabe.py`): Die Collage-Sperre `COLLAGE_EINREICHEN` entfällt. Ist die neueste Fassung `seite`, wird zuerst `erzeugen(i, neueste)` aufgerufen, dann `pult_einreichen` wie heute.
- **Versand** (`GET /inhalte/{iid}/versand`): Bei `format = 'seite'` kommt `{…, html, text, medien}` aus der Mail-Fassung der freigegebenen Fassung, erzeugt sie bei Bedarf. Form der Antwort identisch zu Blöcken.
- **Vorschau** `format=mail|handy` für `seite`: Mail-HTML mit `bild_basis` (bei Bedarf erzeugt, Fehler sind 422 mit Grund). `pdf` bleibt die Seite.

- [ ] **Step 1:** verify für die Migration und Python-Tests mit gefälschter DB, gefälschtem Renderer und tmp-Ordnern:
  - `test_mailfassung_einmal`
  - `test_einreichen_collage_erzeugt_mail_dann_einreichen`
  - `test_anrede_im_bild_blockiert`
  - `test_zu_gross_blockiert`
  - `test_versand_collage_form_wie_bloecke`
  - `test_vorschau_mail_collage`
  - `test_bloecke_unveraendert` (bestehende Tests grün)
  - `ms-` wird nicht aufgeräumt
- [ ] **Step 2:** Probe `0NN verify_0NN 0NN verify_0NN`. Expected: `PROBE OK`.
- [ ] **Step 3–4:** Rot, umsetzen, grün. Volle Marketing-Suite.
- [ ] **Step 5:** Commit `feat(marketing): Collagen einreichen und versenden (Mail-Fassung)`

### Task 5: Oberfläche (sales-claw)

**Files:**
- Modify `sales-mcp/ui_marketing.py`: Entwurf-Seite mit Einreichen für Collagen, ohne den Satz „… in einer späteren Stufe.“, veralteten PDF-Kommentar korrigieren
- Modify `sales-mcp/ui_freigabe_newsletter.py`: „An Kontakte senden“ auch für `seite`. „Export anstoßen“ bleibt nur für Blöcke.
- Modify `sales-mcp/medien.py`, falls `pruefe_anzeige` oder `newsletter_bilder` `ms-*` ablehnen
- Modify `editor/src/App/Seite/*`: Einreichen-Knopf in der Leiste (`start.einreichen_url`, Muster `PultLeiste.tsx:208-220`); bei `nurLesen` schreibgeschützt (Fläche, Ebenen, Eigenschaften, Tasten, Speichern, Chat gesperrt), Hinweis „Liegt zur Freigabe – erst zurückziehen“. Veraltete Kopf-Kommentare korrigieren.
- Tests in sales-mcp und Editor; Bundle.

- [ ] **Step 1:** Tests:
  - Entwurf-Seite einer Collage zeigt das Einreichen-Formular.
  - Freigabe-Seite einer freigegebenen Collage zeigt „An Kontakte senden“.
  - `newsletter_bilder(['ms-0c80e26a-2-01.jpg'])` liest die Datei aus `/media-erzeugt`.
  - SeiteApp mit `status = eingereicht` hat `disabled` für Speichern und Rückgängig, keine Griffe, und einen Hinweis.
  - Einreichen-Knopf ruft `einreichenAuftrag`, Fehlertext (422-Grund) wird angezeigt.
- [ ] **Step 2–4:** Rot, umsetzen, grün. tsc, vitest, build, Python-Tests einzeln.
- [ ] **Step 5:** Commit `feat(marketing-ui): Collagen einreichen, freigeben und versenden`

### Task 6: Livegang und Abnahme

- [ ] Claims (WORKBOARD, Koordinationsdatei für die VM-Datenbank).
- [ ] Rebase und Tests. Migration auf der VM nach Sicherung einspielen und verify prüfen.
- [ ] vibemind-os pushen, dann `marketing-aktualisieren.sh` und PC `:5510` neu starten, nach dem Byte-Vergleich-Muster im Haupt-Checkout.
- [ ] sales-claw pushen und `update.sh` ausführen.
- [ ] **Abnahme:**
  - Probe-Collage über API anlegen, mit Bild-, Text- und Knopf-Ebenen, Anrede im Fließtext.
  - Mail-Vorschau holen und mit Playwright fotografieren: einmal mit Bildern, einmal ohne (Bilder blockiert → Text muss lesbar sein).
  - Einreichen, freigeben (Pult-API `entscheiden` als Betreiber), Versandfassung holen.
  - Prüfen: Größe, Anzahl der Stücke, `cid`s passen zur Medienliste, alle Stücke existieren in `/media-erzeugt`.
  - Keine echte Mail an Kontakte senden. Die Probe danach löschen.
- [ ] Claims schließen, Worktrees entfernen.
