# Freie Fläche – Stufe 3: Assistent für Collagen – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Newsletter-Assistent gestaltet und ändert Collage-Newsletter (`format = 'seite'`). Er rendert sein Ergebnis als Bild, beurteilt es wie ein Art Director und bessert bis zu 3 Runden nach, bevor der Betreiber es sieht. Im Collage-Editor (PC und Handy) gibt es dafür den Chat.

**Architecture:**
- **Eigener Seiten-Zweig neben dem Block-Weg, ohne Umbau des Block-Wegs.**
  - Werkzeuge: `claw/seite_werkzeuge.py`
  - Prompt: `claw/seite_prompt.py`
  - Prüfbild: `workers/seite_pruefbild.py`, rendert `seite_html.html` mit Playwright in Kacheln
  - Ablauf: im Chat-Arbeiter ein Zweig `_bearbeiten_seite`
- **Datenbank:** Migration 079 bekommt Speicher- und Stopp-Funktionen für Seiten, Bildaufträge für Seiten-Ebenen und eine Abfrage der letzten Kompositionen.
- **API:** Die API hebt die Chat-Sperre für Collagen auf. Einreichen und Versand bleiben gesperrt bis Stufe 4.
- **Editor:** Der Editor hängt den vorhandenen Chat (`ChatLeiste`) in `SeiteApp` ein.

**Tech Stack:** Python 3.11, FastAPI, Postgres (Mini-PC), Playwright/Chromium (PC-venv), Claude über den Shim `:8117` (Bilder als `image_url`-Data-URLs, höchstens 6 je Anfrage). Editor: React/TS/Vitest.

**Spec:** sales-claw `docs/superpowers/specs/2026-10-20-freie-flaeche-newsletter-design.md`, Abschnitte 4.4, 4.7, 5. Stufe 1 (vibemind-os `58cb7e72`) und Stufe 2 (sales-claw `1f80e06`) sind live.

**Repos:**
- Tasks 1–6 in vibemind-os, `master`, Pfade relativ zu `spaces/marketing/`.
- Task 7 in sales-claw, `feat/stufe-1-fundament`.
- Jeweils eigener Worktree unter `C:/Users/User/ClaudeWork/`.

**Befehle:**
- Marketing-Tests (Repo-Root): `C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests/<f> spaces/marketing/claw/tests/<f> -q -p no:cacheprovider`. Vorbestehend rot: `test_cockpit_contract`, dazu im Worktree ohne Submodul `test_abschnitte`, `test_formular_entwurf`, `test_gestaltung_pruefen`.
- DB-Probe: `SUPABASE_SSH_HOST=offload-vm SUPABASE_DB_CONTAINER=debian-supabase-db-1 … -m spaces.marketing.scripts.migration_probe <dateien>` (immer ROLLBACK).
- Editor und Server sales-claw: wie im Stufe-2-Plan.

## Global Constraints

- **Seitenregeln wie Stufe 1** (`claw/seite.py`): Jede vom Assistenten erzeugte Seite muss `seite.pruefen` bestehen, sonst wird sie nicht gespeichert. Gespeichert wird das normalisierte Dokument.
- **Qualitätsregeln (Spec 4.4), wörtlich in den Prompt:**
  - Schriftgrößen-Stufung: höchstens 3 Größen pro Seite, Fließtext 15–19, Überschrift ≥ 2× Fließtext.
  - Markenfarben und -schriften aus der Marke.
  - Mindestkontrast 4,5:1 für Fließtext und 3:1 für Text ab 24, auch gegen Bilder darunter.
  - Ruhezone 24 Einheiten an den Seitenrändern für Text.
  - Höchstens 2 „laute“ Elemente (Sticker, gedrehte Großschrift) pro Ausgabe.
  - Klarer Blickverlauf: Aufmacher → Inhalt → Knopf.
  - Mindestens ein Knopf.
  - Fließtext mindestens 15, damit er bei 375 px Handybreite lesbar bleibt (Spec 4.7).
- **Anrede und Links (Entscheidung 10):** `{vorname}` und Textlinks nur in Rolle `TEXT`, Drehung 0, ohne Überlappung mit anderen Ebenen. Stufe 3 prüft die Überlappung im Werkzeug-Abschluss als Hinweis an das Modell, nicht als Speichersperre. Die harte Sperre kommt in Stufe 5.
- **Ansehen und nachbessern:**
  - Nach jedem Entwurf ein Prüfbild, höchstens **3** Nachbesserungsrunden. Der Assistent darf früher aufhören („fertig“).
  - Jede Runde ist für den Betreiber im Chat sichtbar (Schritt-Text „Prüfe Entwurf (Runde n/3)“).
- **Prüfbild:**
  - Seite 600 breit bei Gerätefaktor 1, in Kacheln von höchstens 1200 px Höhe, höchstens **4** Kacheln.
  - Längere Seiten werden für das Prüfbild auf 4 Kacheln herunterskaliert, dabei bleibt die Breite ≥ 300.
  - JPEG q85.
  - Zusammen mit Anhängen höchstens 6 Bilder je Modellanfrage. Anhänge haben Vorrang, die Kacheln werden passend gekürzt.
- **Abwechslung:**
  - Der Assistent bekommt die Kompositionen der letzten **5** Collagen derselben Firma in Kurzform, ohne die aktuelle.
  - Er soll keine davon wiederholen: andere Aufmacherposition und andere Anordnung der Hauptelemente.
- **Bilder:** `bild_erzeugen`, `bild_aendern` und `bild_aus_medien` zielen auf eine Bild-Ebene (`ebene`-ID). Erzeugte Bilder kommen wie heute als neue Fassung: `pult_bild_einsetzen` setzt `quelle` der Ebene.
- Der Block-Weg (Werkzeuge, Prompt, Arbeiter, DB-Funktionen) bleibt unverändert.
- Einreichen und Versand bleiben für Collagen gesperrt (Stufe 4).
- Prompt für Seiten höchstens **14000** Zeichen (eigener Test). Der Block-Prompt bleibt bei 13000.
- Fehlermeldungen und Schritt-Texte auf Deutsch mit echten Umlauten.
- Livegang (Migration auf der VM, Marketing-API, PC-Arbeiter, sales `update.sh`) nur mit User-OK. **079 muss vor dem Code live sein. Die Nummer 078 belegt der Marken-Chat (cc-marken-chat); 079 ist davon unabhängig.**

## Review Focus

1. **Das Modell liefert eine Änderung, die die Seite ungültig macht** (Ebene 81, Anrede in Anzeige-Schrift, unbekannte Ebenen-ID): Diese Änderung wird verworfen, der Rest bleibt, und das Modell bekommt den Grund in der nächsten Runde. Es wird nie eine ungültige Seite gespeichert. Test: `test_anwenden_verwirft_ungueltige_aenderung` (Task 3).
2. **Prüfbild schlägt fehl** (Chromium fehlt, Zeitlimit, Medium nicht ladbar): Die Runde endet mit dem bisherigen Entwurf, gespeichert und mit Hinweis „Prüfbild nicht möglich – ohne Nachbesserung gespeichert“. Kein Absturz und kein Hängen. Test: `test_pruefbild_fehler_speichert_ohne_nachbesserung` (Task 6).
3. **Der Betreiber stoppt mitten in Runde 2:** „Behalten“ speichert den Stand nach der letzten vollständig angewendeten Runde, „Verwerfen“ nichts. Test: `test_stopp_in_nachbesserung` (Task 6).
4. **Inzwischen hat der Betreiber eine neue Fassung gespeichert** (`veraltet`): Die Änderungen werden auf die neueste Seite nachgespielt, wie im Block-Weg, höchstens 3 Versuche. Test: `test_nachspielen_auf_neueste_seite` (Task 3) und `test_veraltet_spielt_nach` (Task 6).
5. **Sehr hohe Seite (6000) mit Anhängen:** Höchstens 6 Bilder gehen an den Shim, Kacheln werden gekürzt, kein HTTP 400. Test: `test_bildbudget_mit_anhaengen` (Task 5).

---

### Task 1: Migration 079 – Speichern, Stopp, Bildaufträge und Kompositionen für Seiten

**Files:** Create `db/079_seite_assistent.sql`, `db/verify_079.sql`

**Interfaces – Produces:**
- `marketing.pult_chat_fertig_seite(p_auftrag uuid, p_antwort text, p_seite jsonb, p_hinweise jsonb, p_ergebnis jsonb, p_basis int DEFAULT NULL) RETURNS jsonb`
  - Gleiches Verhalten und gleiche Rückgabeform wie `pult_chat_fertig` (067:166), auch für `{"status":"veraltet"}`.
  - Gespeichert wird aber über `pult_seite_speichern(..., 'agent', false)`.
- `marketing.pult_chat_stopp_abschliessen_seite(p_auftrag uuid, p_seite jsonb, p_hinweis text, p_basis int DEFAULT NULL) RETURNS jsonb`: analog zu 067:258.
- `marketing.pult_bild_auftrag` und `marketing.pult_bild_einsetzen` bekommen einen Seiten-Zweig über das Hüllen-Muster von 060/068 (umbenennen und neue gleichnamige Hülle):
  - Bei neuester Fassung `seite` ist `platz` eine Ebenen-ID einer Bild-Ebene in `seite.ebenen`.
  - `einsetzen` setzt `quelle = 'medien:<datei>'` dieser Ebene und speichert über `pult_seite_speichern(..., 'agent', false)`.
  - Der Block-Zweig bleibt unverändert.
- `marketing.pult_seite_kompositionen(p_mandant text, p_ausser uuid) RETURNS jsonb`
  - Liefert die Seiten der neuesten Fassung der letzten 5 Collage-Inhalte dieser Firma (nach `erstellt_am` absteigend), ohne `p_ausser`.
  - Form: `[{"inhalt": uuid, "seite": {...}}]`.

- [ ] **Step 1:** `verify_079.sql` schreiben, mit eigenen Probe-Inhalten nach dem Muster von `verify_077.sql`.
  - **Fertig:** speichert eine neue Seiten-Fassung mit `urheber = 'agent'`. Mit veralteter Basis kommt `veraltet`.
  - **Stopp-Abschluss:** speichert.
  - **Bildauftrag:** wird für eine Bild-Ebene angelegt, für eine Text-Ebene oder unbekannte ID gibt es eine Ausnahme mit deutschem Grund.
  - **Einsetzen:** setzt `quelle`.
  - **Kompositionen:** liefert höchstens 5 Einträge, ohne den eigenen, nur für dieselbe Firma.
  - **Block-Wege unverändert:** `pult_chat_fertig` und Block-Bildauftrag laufen wie vorher.
- [ ] **Step 2:** Probe mit nur `verify_079.sql`. Expected: FAIL.
- [ ] **Step 3:** `079_seite_assistent.sql` schreiben. RUNBOOK-Kopf „nach 077, unabhängig von 078 (Marken-Chat)“, idempotent, Rechte wie 077.
- [ ] **Step 4:** Probe `079 verify_079 079 verify_079`. Expected: `PROBE OK`.
- [ ] **Step 5:** Commit `feat(marketing): Migration 079 Assistent fuer Collagen (Speichern, Stopp, Bilder, Kompositionen)`

### Task 2: API – Chat für Collagen freigeben, Arbeiter-Routen seitenfähig

**Files:** Modify `api/chat.py`, `api/bilder.py`. Test `tests/test_chat_api.py`, `tests/test_pult_api.py`.

**Interfaces:**
- `_chat_senden` sperrt Collagen nicht mehr. `mit_formatsperre` bleibt für Einreichen, Versand, `/bloecke`, `/vorlage` usw.
- `GET arbeiter_naechster`: Bei Fassungsformat `seite` enthält die Antwort zusätzlich `format: "seite"`, `seite` (Seite der Basisfassung) und `kompositionen` (aus `pult_seite_kompositionen`). Bei Blöcken ist `format: "bloecke"` gesetzt, die Antwort sonst unverändert.
- `arbeiter_neueste`: liefert für Seiten `{fassung, seite}`.
- **`arbeiter_pruefen`, `arbeiter_fertig`, `zwischenstand`, `gestoppt`:** Sie nehmen statt `bloecke` den Schlüssel `seite` an, genau einer von beiden ist Pflicht.
  - Bei `seite` wird `seite.pruefen` aufgerufen, bei Fehler kommt 422 mit Grund. `_rechnen_und_pruefen` (Gestaltung, Logo, Schönheit) wird für Seiten **nicht** aufgerufen.
  - Gespeichert wird über die Funktionen aus Task 1.
- `chat_rueckgaengig`: Für Seiten wird die Fassung vor der Runde über `pult_seite_speichern(..., 'betreiber', false)` wiederhergestellt.
- `bilder._anlegen`: reicht Seiten-Plätze unverändert an `pult_bild_auftrag` durch. Der DB-Zweig kommt aus Task 1.

- [ ] **Step 1:** Failing tests mit der `_db`-Fälschung:
  - `test_chat_auf_collage_erlaubt` (kein 409 mehr, SQL ruft `pult_chat_senden`)
  - `test_einreichen_collage_bleibt_gesperrt`
  - `test_naechster_liefert_seite_und_kompositionen`
  - `test_fertig_seite_prueft_und_speichert` (ungültige Seite → 422 ohne SQL; gültige → `pult_chat_fertig_seite`)
  - `test_fertig_bloecke_unveraendert`
  - `test_zwischenstand_seite`
  - `test_gestoppt_seite`
  - `test_rueckgaengig_seite`
  - Den bisherigen Test, der 409 für Chat auf Collagen erwartet, umdrehen.
- [ ] **Step 2–4:** Rot, umsetzen, grün. Danach die volle Marketing-Suite, keine neuen Fehler.
- [ ] **Step 5:** Commit `feat(marketing): Chat-API fuer Collagen`

### Task 3: Werkzeuge für Seiten `claw/seite_werkzeuge.py`

**Files:** Create `claw/seite_werkzeuge.py`, `claw/tests/test_seite_werkzeuge.py`

**Interfaces – Produces:**
- `WERKZEUGE` mit genau diesen Werkzeugen. Jede Änderung darf `schritt` (≤ 80 Zeichen) tragen.

  | Werkzeug | Parameter |
  |---|---|
  | `seite_hoehe` | `{hoehe}` |
  | `seite_hintergrund` | `{farbe?, bild?}` (`bild` = `medien:…` oder `null`) |
  | `schriften_setzen` | `{anzeige?, text?}` |
  | `ebene_hinzufuegen` | `{ebene, nach?}` (`ebene` = vollständige Ebene ohne `id` oder mit eigener ID; `nach` = ID, über der sie liegt, sonst ganz oben) |
  | `ebene_aendern` | `{id, felder}` |
  | `ebene_reihenfolge` | `{ids}` (vollständige neue Reihenfolge) |
  | `ebene_loeschen` | `{id}` |
  | `bild_erzeugen` | `{ebene, hinweis, vorlagen?≤3}` |
  | `bild_aendern` | `{ebene, anweisung, vorlagen?≤2}` |
  | `bild_freistellen` | `{ebene}` |
  | `bild_aus_medien` | `{ebene, quelle}` |
  | `logo_einsetzen` | `{ebene, quelle}` |
  | `fertig` | `{notiz}` (nur in Nachbesserungsrunden: keine weiteren Änderungen) |
- `MAX_AENDERUNGEN = 40`
- `@dataclass ErgebnisSeite(seite: dict, geaendert: bool, bildauftraege: list[dict], hinweise: list[str], fertig: bool, notiz: str)`
- `anwenden(seite: dict, aenderungen: list, medien: set[str]) -> ErgebnisSeite`
  - Jede Änderung wird einzeln auf eine Kopie angewendet und mit `seite.pruefen` geprüft.
  - Ist sie ungültig, wird sie verworfen und ihr Grund kommt mit Nummer in `hinweise`, alle übrigen gelten.
  - Neue Ebenen ohne ID bekommen `a-<6 hex>`.
  - Bildquellen nur aus `medien`.
  - Abschluss:
    - Überlappungshinweis für Anrede und Links (Global Constraints).
    - Hinweis „Kein Knopf auf der Seite“, wenn keiner da ist.
    - Hinweis, wenn eine Bild-Ebene ohne gültige Quelle bleibt und kein Bildauftrag für sie besteht.
- `nachspielen(seite_neu: dict, aenderungen: list, medien: set[str]) -> ErgebnisSeite`: dieselbe Logik auf einer neueren Seite. Änderungen an inzwischen gelöschten Ebenen werden mit Hinweis übersprungen.

- [ ] **Step 1:** Tests:
  - jedes Werkzeug einmal positiv
  - `test_anwenden_verwirft_ungueltige_aenderung` (81. Ebene, `{vorname}` in ANZEIGE, unbekannte ID → je ein Hinweis, gültige Änderungen bleiben)
  - `test_bild_erzeugen_nur_fuer_bild_ebene`
  - `test_nachspielen_auf_neueste_seite` (eine Ebene inzwischen gelöscht → übersprungen mit Hinweis, Rest angewendet)
  - `test_hinweis_ohne_knopf`
  - `test_hinweis_anrede_ueberlappt`
  - `test_max_aenderungen`
  - `test_fertig_ohne_aenderungen`
- [ ] **Step 2–4:** Rot, umsetzen, grün.
- [ ] **Step 5:** Commit `feat(marketing): Werkzeuge des Assistenten fuer Collage-Seiten`

### Task 4: Prompt für Seiten `claw/seite_prompt.py`

**Files:** Create `claw/seite_prompt.py`, `claw/tests/test_seite_prompt.py`

**Interfaces – Produces:**
- `system_seite(marke: bool) -> str`. Inhalt:
  - Rolle („Art Director und Gestalter für High-End-Newsletter“)
  - das Seitenmodell kurz (Felder, Mittelpunkt-Koordinaten, Reihenfolge)
  - die Werkzeugliste mit Parametern
  - die Qualitätsregeln aus den Global Constraints
  - die Anrede- und Link-Regel
  - Abwechslung
  - das JSON-Antwortformat wie `agent_prompt` (`{antwort, aenderungen, notizen}`)
  - den Marken-Absatz wie `agent_prompt.system(marke)`
- `nutzer_text_seite(*, nachricht, auswahl, titel, betreff, firma, marke_zeilen: list[str], medien: list[str], seite: dict, verlauf: list, kompositionen: list[str], anhaenge_zeilen: list[str], hinweise: list[str]) -> str`. Es enthält `SEITE (JSON)` statt `BLÖCKE`. Die übrigen Zeilen haben dieselben Namen wie `agent_prompt.nutzer_text`, soweit vorhanden.
- `pruef_text(runde: int, hinweise: list[str]) -> str`: Auftrag für die Nachbesserungsrunde. Inhalt:
  - Die Bilder zeigen den aktuellen Entwurf.
  - Beurteile ihn streng nach den Qualitätsregeln: Lesbarkeit, Hierarchie, Luft, Marke, Blickverlauf, Abwechslung.
  - Liefere Änderungen oder `fertig`.
  - Die offenen Hinweise kommen dazu.
- `komposition_kurz(seite: dict) -> str`: eine Zeile, zum Beispiel `Höhe 1400; Aufmacher Bild links oben 60%; Titel rechts gedreht; Text mittig; Knopf unten mitte; 7 Ebenen`. Abgeleitet aus Position und Größe der größten Ebenen.
- `antwort_lesen` wird aus `agent_prompt` wiederverwendet, nicht kopiert.

- [ ] **Step 1:** Tests:
  - `len(system_seite(True)) + len(nutzer_text_seite(<typische Seite mit 20 Ebenen>)) <= 14000`
  - Der System-Text enthält jede Qualitätsregel (Schlüsselwörter: `4,5:1`, `24 Einheiten`, `höchstens 2`, `Knopf`, `{vorname}`).
  - `komposition_kurz` ist für zwei unterschiedlich aufgebaute Seiten verschieden und für dieselbe gleich.
  - `pruef_text(2, ["x"])` enthält `Runde 2/3` und `x`.
- [ ] **Step 2–4:** Rot, umsetzen, grün.
- [ ] **Step 5:** Commit `feat(marketing): Prompt des Assistenten fuer Collage-Seiten`

### Task 5: Prüfbild `workers/seite_pruefbild.py`

**Files:** Create `workers/seite_pruefbild.py`, `tests/test_seite_pruefbild.py`. Modify `workers/export_worker.py` nur, um `_Routen` und `_EchterBrowser` als gemeinsam nutzbare Bausteine freizugeben (Umbenennung ohne Unterstrich plus Alias), nicht kopieren.

**Interfaces – Produces:**
- `class PruefbildFehler(RuntimeError)`
- `kacheln(seite: dict, html_render, max_kacheln: int = 4) -> list[bytes]`
  - Rendert `seite_html.html(seite, betreff="", pflichtteil={}, bild_basis=BASIS+"medien/", schrift_basis=BASIS+"schrift/")` und fotografiert **nur den Seitencontainer** (600 × hoehe).
  - Danach in JPEG-Kacheln (q85) von höchstens 1200 px Höhe geschnitten. Bei mehr als `max_kacheln` wird vorher skaliert (Global Constraints).
  - `html_render` ist injizierbar: im Test eine Fälschung, die ein PNG liefert, sonst der echte Browser mit den Routen aus `export_worker` (Medien über `api.medium(aid, name)`, Schriften lokal).
- `bilder_fuer_modell(anhaenge: list[dict], kacheln: list[bytes], max_bilder: int = 6) -> list[dict]`: Anhänge zuerst, dann Kacheln bis zum Budget, als `image_url`-Teile (Data-URL JPEG).

- [ ] **Step 1:** Tests:
  - 600×900-PNG → 1 Kachel
  - 600×3000 → 3 Kacheln, jede ≤ 1200 hoch
  - 600×6000 → 4 Kacheln, Breite ≥ 300
  - `test_bildbudget_mit_anhaengen` (3 Anhänge + 4 Kacheln → genau 6 Teile, Anhänge vollständig)
  - Render-Fehler → `PruefbildFehler`
  - Ein echter Playwright-Rauchtest, markiert `@pytest.mark.browser` und übersprungen, wenn Chromium fehlt: eine Seite mit Text rendert und hat die erwartete Höhe.
- [ ] **Step 2–4:** Rot, umsetzen, grün. Den echten Rauchtest einmal am PC ausführen und das Ergebnis berichten.
- [ ] **Step 5:** Commit `feat(marketing): Pruefbild der Collage-Seite fuer den Assistenten`

### Task 6: Chat-Arbeiter – Seiten-Runde mit Ansehen und Nachbessern

**Files:** Modify `workers/chat_worker.py`: Zweig in `chat_bearbeiten`, `format == 'seite'` → neue Funktion `_bearbeiten_seite`. `ChatApi`-Methoden bekommen einen Parameter, mit dem `seite` statt `bloecke` gesendet wird. Test `tests/test_chat_worker.py`.

**Ablauf `_bearbeiten_seite`:**
1. Prompt aus `seite_prompt` bauen. Dazu kommen Marke, Medien, Anhänge über `anhaenge_vorbereiten` und Kompositionen über `komposition_kurz`.
2. Modell fragen über `frage_strom`, wie im Block-Weg, mit Live-Zwischenständen (`seite`).
3. Antwort mit `seite_werkzeuge.anwenden` umsetzen.
4. **Runde r = 1..3:**
   - `seite_pruefbild.kacheln` erzeugen.
   - Schritt-Text „Prüfe Entwurf (Runde r/3)“.
   - Modell mit `pruef_text(r, hinweise)`, der aktuellen Seite und `bilder_fuer_modell` fragen und das Ergebnis anwenden.
   - Ende bei `fertig`, bei keinen Änderungen oder nach Runde 3.
   - Bei `PruefbildFehler`: Schleife beenden, Hinweis „Prüfbild nicht möglich – ohne Nachbesserung gespeichert“.
5. `/fertig` mit `seite`. Bei `veraltet` mit `nachspielen` auf `/neueste` erneut, höchstens 3 Versuche. Bildaufträge mitgeben.
6. Antwort an den Betreiber: die Antwort der ersten Runde plus eine kurze Zeile je Nachbesserungsrunde (deren `notiz`).
7. Stopp: wie im Block-Weg, mit dem zuletzt vollständig angewendeten Stand.

- [ ] **Step 1:** Tests mit gefälschtem Modell, gefälschter API und gefälschtem Prüfbild:
  - `test_seiten_runde_speichert_seite`
  - `test_nachbesserung_hoechstens_3_runden` (das Modell liefert immer Änderungen → genau 3 Prüfrunden)
  - `test_nachbesserung_endet_bei_fertig`
  - `test_pruefbild_fehler_speichert_ohne_nachbesserung`
  - `test_stopp_in_nachbesserung`
  - `test_veraltet_spielt_nach`
  - `test_bloecke_runde_unveraendert` (bestehende Block-Tests bleiben grün)
- [ ] **Step 2–4:** Rot, umsetzen, grün. Volle Marketing-Suite.
- [ ] **Step 5:** Commit `feat(marketing): Chat-Arbeiter gestaltet Collagen und bessert nach Pruefbild nach`

### Task 7: Chat im Collage-Editor (sales-claw)

**Files:** Modify:
- `editor/src/App/Seite/SeiteApp.tsx`: Chat statt Hinweis, rechte Spalte unter den Eigenschaften
- `editor/src/main.tsx`: für `seite` auch `chatAbfragen` und `chatEntwurfWiederholen`
- `editor/src/pultZustand.ts`: `vorDemStart` mit einsteckbarem Speichern; `zwischenstandZeigen` für Seiten nur zur Anzeige
- `editor/src/chatKontext.ts`: Chips `art: 'ebene'` ohne `flaeche` für Seiten-Ebenen
- `editor/src/App/Handy/HandyApp.tsx`: Assistent für Seiten

Tests: `SeiteApp.test.tsx`, `HandyApp.test.tsx`, `pultZustand`-Tests, `chatKontext`-Tests. Danach Build und Bundle.

**Verhalten:**
- **Chat:** `ChatLeiste` mit `kontext {fenster: 'seite', auswahl}`. Die ausgewählte Ebene wird als Chip angeboten (Kurzname aus Art und Textanfang).
- **Vor dem Senden** speichert `seiteSpeichern` ungespeicherte Änderungen. Bei Konflikt kommt der Konfliktdialog und es wird nichts gesendet.
- **Während einer Runde** zeigt die Fläche den Zwischenstand nur zur Anzeige mit dem Hinweis „Der Assistent arbeitet“. Bearbeiten ist gesperrt, wie im Block-Editor (`Sperre`).
- **Nach der Runde** lädt die Seite neu (`neueFassungLaden`, wie heute).
- **Handy:** `HandyAnsicht` mit Assistent (`ohneAssistent` entfällt für Seiten) und einem Seiten-Chat.
- Der Hinweistext „Der Assistent kommt …“ entfällt, die Tests dazu werden angepasst.

- [ ] **Step 1:** Failing tests:
  - SeiteApp rendert `ChatLeiste` und keinen Hinweistext.
  - Ein Chip für die gewählte Ebene ist vorhanden.
  - `vorDemStart` ruft bei Seiten `seiteSpeichern`, und bei Konflikt wird nicht gesendet (fetch gestubbt).
  - `zwischenstandZeigen` mit Seiten-Daten ändert den Editor-Zustand nicht dauerhaft.
  - Handy zeigt den Reiter „Assistent“.
- [ ] **Step 2–4:** Rot, umsetzen, grün. `tsc`, volle `vitest`, `npm run build`, `test_editor_paket.py`, `test_editor_seite.py`.
- [ ] **Step 5:** Commit `feat(editor): Assistent im Collage-Editor` (mit Bundle).

### Task 8: Livegang und echte Probe (nur mit User-OK)

- [ ] **Step 1:** Claims setzen: WORKBOARD, und `secondbrain/00_Meta/002_Koordination_Live.md` für die VM-Datenbank.
- [ ] **Step 2:** User-OK einholen.
- [ ] **Step 3: Datenbank.**
  - `marketing`-Schema sichern (`pg_dump -n marketing`).
  - 079 einspielen und `verify_079` per Probe prüfen. Expected: `PROBE OK`.
- [ ] **Step 4: Ausrollen.**
  - vibemind-os pushen.
  - `marketing-aktualisieren.sh` auf der VM ausführen.
  - Im PC-Haupt-Checkout die eigenen Dateien nach dem Byte-Vergleich-Muster mit `git restore --source` nachziehen. Bei fremder Abweichung abbrechen.
  - `:5510` und `marketing_chat_arbeiter :8134` mit `beende_dienst` und `-Nur` neu starten.
  - sales-claw pushen und `update.sh` ausführen.
- [ ] **Step 5: Echte Probe.**
  - Eine Probe-Collage über die API anlegen.
  - Eine Chat-Runde mit dem Auftrag „Gestalte einen Herbst-Newsletter für drei neue Kurse, hochwertig und frei“ über die Agent-Route starten.
  - Warten, bis sie fertig ist.
  - Das PDF holen und ansehen. Die Zahl der Nachbesserungsrunden und die Schritt-Texte im Chat-Verlauf festhalten.
  - Probe-Inhalt löschen.
- [ ] **Step 6:** Claims schließen, Worktrees entfernen.

## Folgepläne

- **Stufe 4, Mail und Versand:** Streifen, Bildstücke, Textstreifen, Versand, Einreichen freigeben. Collage-Editor beachtet `nurLesen` (Ruling aus Stufe 2).
- **Stufe 5, Schönheitsprüfung und Vorlagen:** Pixel-Kontrast, harte Überlappungssperre für Anrede und Links, 8 Collage-Vorlagen mit Freigabe.
