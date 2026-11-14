# Abnahme-Befunde Bildauswertung (14.11.2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die fünf Schwächen aus den zwei Abnahme-Terminen vom 14.11.2026 beheben und beide Termine danach neu auswerten.

**Architecture:** Auswertung (`auswertung.py`) faltet reine Bild-Stücke in Nachbarstücke und bereinigt „Beteiligte“. Eine neue Bereinigung (`mitschrift_bereinigen.py`) räumt Vexa-Segmente beim Ablegen auf. `sales-auge` prüft jedes neue Bild lokal per CLIP gegen „heikle“ Bildschirmarten (Schicht A) und verwirft Treffer ohne Speicherung; die KI-Beschreibung meldet übersehene Fälle (Schicht B), dann wird das Bild gelöscht. Der Beobachter erfasst mehrere gleichzeitige Freigaben je Quelle.

**Tech Stack:** Python 3.12, psycopg 3, pgvector, fastembed (CLIP ViT-B/32), Playwright-Chromium, Jitsi lib-jitsi-meet (Browser-JS), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-bildauswertung-live-design.md` (bleibt verbindlich). Die Befunde unten sind die Anforderungen dieses Plans; sie stammen aus der Analyse der Termine `3c9afada…` (194 Bilder, 1110 Segmente) und `54ac1821…` (162 Bilder, 793 Segmente).

### Befunde (Anforderungen)

1. **Reines Bild-Stück:** Termin 1 wurde in 3 Stücke geteilt; Stück 3 bestand nur aus `[Bild 10:58]`. Das Modell antwortete „keine Gesprächsinhalte“, `_vereinen` übernahm `stimmung` und `ergebnis.was` des letzten Stücks → Unsinn in der Akte.
2. **Beteiligte:** doppelt („Felix“ / „Felix Baumann“, „Diana“ / „Diana Marx“) und Bots als Teilnehmer („Laura – teilt zeitweise den Bildschirm“, „VibeMind“).
3. **Mitschrift:** 14–18 % Segmente ohne Sprecher, ~35 % Bruchstücke mit ≤ 2 Wörtern, Whisper-Halluzination „Untertitel im Auftrag des ZDF, 2017“, Sprecher „felix“ vs. „Felix Baumann“.
4. **Heikle Bildschirme:** Google-Anmeldeseite mit Konto-Adresse, GMX-Posteingang, Bezahlseite wurden gespeichert und über die KI beschrieben.
5. **Mehrere Freigaben:** Bei zwei gleichzeitigen Freigaben wird nur die erste erfasst (Abnahme 2 bisher nicht bestanden).

## Global Constraints

- Branch `fix/abnahme-befunde` ab `origin/feat/stufe-1-fundament`; PR dorthin, Merge nur mit Felix' OK.
- Tests laufen auf der VM gegen die Test-DB: `.superpowers/sdd/2026-11-13-bildauswertung-live/vm_test.sh [--provision] [--rebuild] <pytest-Dateien einzeln>` (Globs werden nicht expandiert).
- Rulings R5 (Claim per `skip locked`, keine Sperre während KI), R6, R8, R9, R11 aus `.superpowers/sdd/2026-11-13-bildauswertung-live/progress.md` bleiben bindend.
- Logs nie mit Inhalt (Text, Beschreibung, Namen, Adressen); nur gekürzte uid, Zähler, Fehlerart.
- Ein als heikel erkanntes Bild wird **nie** in `termin_bilder` gespeichert (Schicht A) bzw. **vollständig gelöscht** (Schicht B: Bild, Beschreibung, beide Vektoren).
- Oberflächentexte mit echten Umlauten; Bezeichner/Kommentare ASCII-Umschrift.
- Segment-Indizes der gespeicherten Mitschrift sind die Referenz für `verlauf.von/bis` und die Vorschaubilder: Bereinigung nur VOR dem Speichern (oder mit anschließender Neu-Auswertung).

## Review Focus

1. Ein Termin, in dem nur Bilder und kein Wort vorkommen (Mitschrift leer, Bilder da): keine Modellanfrage mit reinen Bildzeilen, Auswertung leer statt Unsinn.
2. Eine echte Teilnehmerin heißt „Laura“ und spricht: sie bleibt in „Beteiligte“ (nur nie sprechende Bot-Namen fallen raus).
3. Ein Segment besteht wirklich nur aus „Danke fürs Zuschauen“ am Ende eines Gesprächs: wird entfernt (bewusst; Verlust ist vertretbar) – aber „Danke, das schau ich mir an“ bleibt.
4. Eine Freigabe zeigt durchgehend eine Bezahlseite: Schicht A verwirft sie einmal je Änderung, nicht alle 2 s erneut (CPU), und der Zähler „übersprungen“ wächst je verworfenem Bild nur einmal.
5. Zwei Freigaben, eine endet: die andere läuft ohne Lücke weiter; ihr Drossel- und Hash-Zustand wird nicht zurückgesetzt.

---

### Task 1: Reine Bild-Stücke falten

**Files:**
- Modify: `sales-mcp/auswertung.py` (`_stuecke`, ~Z. 414; `auswerten`, ~Z. 470)
- Test: `sales-mcp/tests/test_auswertung.py`

**Interfaces:**
- Produces: `_stuecke(zeilen: list[str]) -> list[str]` — kein Stück ohne mindestens eine nummerierte Segmentzeile (`^\[\d+\] `); ein Stück nur aus Bildzeilen wird an das vorige angehängt (das erste an das folgende), auch wenn es dadurch die Zeichengrenze überschreitet. Gibt es gar keine Segmentzeile, ist das Ergebnis `[]` (→ `auswerten` liefert `_leer()` ohne Modellaufruf).

- [ ] **Step 1: Failing tests** in `test_auswertung.py`:
  - `test_stuecke_haengen_reines_bildstueck_ans_vorige`: Zeilen so, dass die Grenze nach der letzten Segmentzeile bricht und genau eine `[Bild 10:58] …`-Zeile übrig bleibt → `len(_stuecke(z)) == 1 + (Anzahl Stücke ohne Falten − 1)` und das letzte Stück endet mit der Bildzeile und enthält eine `[n] `-Zeile.
  - `test_stuecke_erstes_bildstueck_geht_ans_folgende`: führende Bildzeilen, die allein ein Stück füllen → erstes Stück enthält eine Segmentzeile.
  - `test_auswerten_ohne_segmente_fragt_nicht`: `auswerten([], bilder=[(t, "Folie")])` ruft die Modell-Attrappe nicht auf und liefert `_leer()`.
  - `test_auswerten_bildstueck_ueberschreibt_stimmung_nicht`: Attrappe, die für ein Stück ohne Segmentzeile „Keine Aussage möglich“ liefern würde; Ergebnis-`stimmung` stammt aus dem Gesprächsstück.
- [ ] **Step 2:** `vm_test.sh tests/test_auswertung.py` → die vier neuen FAIL.
- [ ] **Step 3:** `_stuecke` wie oben umsetzen (Regex `re.compile(r"^\[\d+\] ")` als Modulkonstante `_SEGMENTZEILE`).
- [ ] **Step 4:** `vm_test.sh tests/test_auswertung.py tests/test_termin_takt.py` → PASS.
- [ ] **Step 5:** Commit `fix(auswertung): reine Bild-Stuecke falten (Stimmung/Ergebnis nicht ueberschreiben)`.

### Task 2: Beteiligte ohne Bots und Doppelte

**Files:**
- Modify: `sales-mcp/auswertung.py` (Prompt-Regel; `_vereinen`; neue Funktion)
- Test: `sales-mcp/tests/test_auswertung.py`

**Interfaces:**
- Produces: `BOT_NAMEN = ("laura (bildschirm)", "laura", "vibemind mitschrift", "vibemind", "vexa")` und `beteiligte_bereinigen(liste: list[str], sprecher: set[str]) -> list[str]`.
  - Name = Text vor dem ersten „ - “ (bzw. „ – “), normalisiert (klein, Leerraum).
  - Entfernt Einträge, deren Name in `BOT_NAMEN` steht **und** nicht (normalisiert) unter `sprecher` vorkommt.
  - Doppelte: Ist die Wortmenge eines Namens Teilmenge eines anderen („felix“ ⊂ „felix baumann“), bleibt ein Eintrag mit dem **längeren Namen** und der Rolle des **ersten** Vorkommens; Reihenfolge = erstes Vorkommen.
- `auswerten` ruft `beteiligte_bereinigen(a["beteiligte"], {Sprecher aller Segmente})` nach `_vereinen` auf.
- Prompt-Regel (wörtlich anhängen): `- "beteiligte": nur Menschen, die am Gespraech teilnehmen. Aufnahme- und Beobachter-Bots (z. B. "Laura (Bildschirm)", "VibeMind Mitschrift") sind keine Beteiligten. Jede Person nur einmal, mit vollem Namen, wenn er vorkommt.`

- [ ] **Step 1: Failing tests:**
  - `test_beteiligte_ohne_bots`: `["Felix - Berater", "Laura - teilt den Bildschirm", "VibeMind - Teilnehmer"]`, Sprecher `{"felix"}` → `["Felix - Berater"]`.
  - `test_beteiligte_sprechende_laura_bleibt`: Sprecher `{"Laura"}` → „Laura - …“ bleibt.
  - `test_beteiligte_doppelte_zusammen`: `["Felix - Berater", "Diana - Kundin", "Felix Baumann - Betreiber", "Diana Marx - Kundin, Horizon Hues"]` → `["Felix Baumann - Berater", "Diana Marx - Kundin"]`.
  - `test_prompt_nennt_bot_regel`: `"keine Beteiligten" in SYSTEM` (bzw. dem Prompt-Namen im Modul).
- [ ] **Step 2:** FAIL bestätigen. **Step 3:** umsetzen. **Step 4:** `vm_test.sh tests/test_auswertung.py` PASS.
- [ ] **Step 5:** Commit `fix(auswertung): Beteiligte ohne Bots und ohne Doppelte`.

### Task 3: Mitschrift beim Ablegen bereinigen

**Files:**
- Create: `sales-mcp/mitschrift_bereinigen.py`
- Modify: `sales-mcp/termin_takt.py` (`_mitschrift_ablegen`, ~Z. 254: Segmente vor dem Insert durch `bereinigen` schicken)
- Test: `sales-mcp/tests/test_mitschrift_bereinigen.py`, `sales-mcp/tests/test_termin_takt.py`

**Interfaces:**
- Produces: `bereinigen(segmente: list[dict], betreiber: str | None = None) -> list[dict]` (Segment-Schema unverändert: `sprecher`, `beginn`, `text`, `sprache`). Reihenfolge der Schritte:
  1. **Halluzinationen raus:** Segment entfällt, wenn sein Text (klein, ohne Satzzeichen am Rand) **vollständig** auf eines dieser Muster passt (`re.fullmatch`): `untertitel(ung)?( im auftrag)? (des|der|von) [\w .\-]+(, \d{4})?`, `untertitel der amara\.org-community`, `(vielen )?dank (fürs|für's|für das) zuschauen`, `copyright [\w .\-]+ \d{4}`, `(swr|wdr|ndr|br|zdf|ard)( \d{4})?`.
  2. **Sprechernamen vereinheitlichen:** Ist `betreiber` gesetzt (Vorgabe aus Umgebung `BETREIBER_NAME`, sonst `"Felix Baumann"`), wird jeder Sprecher, dessen erstes Wort (klein) dem ersten Wort von `betreiber` entspricht, zu `betreiber`. Danach je Mitschrift: Namen, die sich nur in Groß/Klein unterscheiden oder deren Wortmenge Teilmenge eines anderen Sprechers ist, werden auf den längsten abgebildet.
  3. **Fehlenden Sprecher füllen:** Segment mit leerem Sprecher zwischen zwei Segmenten **desselben** Sprechers, beide `beginn`-Abstände ≤ 3 s → dieser Sprecher.
  4. **Bruchstücke zusammenführen:** Aufeinanderfolgende Segmente desselben nicht-leeren Sprechers werden verbunden (Text mit Leerzeichen, `beginn` des ersten), solange der `beginn`-Abstand zum Vorgänger ≤ 6 s ist und der verbundene Text ≤ 400 Zeichen bleibt. Segmente ohne lesbaren `beginn` werden nie verbunden.
- Konstanten: `MAX_LUECKE_FUELLEN_S = 3`, `MAX_LUECKE_VERBINDEN_S = 6`, `MAX_ZEICHEN_VERBUNDEN = 400`.

- [ ] **Step 1: Failing tests** (`test_mitschrift_bereinigen.py`):
  - `test_zdf_halluzination_faellt_weg`: `"Untertitel im Auftrag des ZDF, 2017"` entfällt; `"Das ZDF hat angerufen"` bleibt.
  - `test_danke_fuers_zuschauen_nur_ganz`: `"Vielen Dank fürs Zuschauen!"` entfällt, `"Danke, das schau ich mir an"` bleibt.
  - `test_betreiber_name_vereinheitlicht`: Sprecher `"felix"` → `"Felix Baumann"`.
  - `test_kurzname_auf_langen`: `"Diana"` und `"Diana Marx"` in einer Mitschrift → beide `"Diana Marx"`.
  - `test_luecke_gefuellt`: A(0 s) – ""(2 s) – A(4 s) → alle A; A – "" – B bleibt leer.
  - `test_bruchstuecke_verbunden`: drei A-Segmente bei 0/2/4 s mit „Ja“, „genau“, „so machen wir das“ → ein Segment `"Ja genau so machen wir das"`, `beginn` 0 s; A bei 0 s und 10 s bleiben getrennt; Grenze 400 Zeichen hält.
  - `test_ohne_beginn_nicht_verbunden`.
  - In `test_termin_takt.py`: `test_mitschrift_wird_bereinigt_abgelegt` (Attrappen-Segmente mit ZDF-Zeile → gespeicherte `segmente` ohne sie).
- [ ] **Step 2:** FAIL. **Step 3:** Modul + Aufruf in `_mitschrift_ablegen` (`segmente = mitschrift_bereinigen.bereinigen(segmente)` vor dem Insert; leere Liste bleibt Status `leer`).
- [ ] **Step 4:** `vm_test.sh tests/test_mitschrift_bereinigen.py tests/test_termin_takt.py tests/test_auswertung.py` PASS.
- [ ] **Step 5:** Commit `feat(termine): Mitschrift beim Ablegen bereinigen (Halluzinationen, Sprecher, Bruchstuecke)`.

### Task 4: Heikle Bildschirme lokal erkennen (Schicht A) mit Kalibrierung

**Files:**
- Create: `sales-mcp/heikel.py`, `scripts/heikel_kalibrieren.py`
- Modify: `sales-mcp/auge.py` (`_eine`, nach `soll_aufnehmen`, vor `bild_ablegen`), `db/provision.sql` (`termin_akten.bilder_uebersprungen int not null default 0`), `sales-mcp/bildschirm.py` (`uebersprungen_zaehlen(uid) -> None`)
- Test: `sales-mcp/tests/test_heikel.py`, `sales-mcp/tests/test_auge.py`, `sales-mcp/tests/test_termin_schema.py`

**Interfaces:**
- Produces in `heikel.py`:
  - `KLASSEN_HEIKEL = ("a login page with a password field", "a sign in with Google account chooser", "a payment checkout page with credit card fields", "an email inbox with a list of messages", "an opened email message")`
  - `KLASSEN_NEUTRAL = ("a presentation slide", "a website", "a document in a text editor", "a chat with an AI assistant", "a video call")`
  - `class Pruefer: __init__(einbetter: Einbetter, abstand: float = ABSTAND)`; `heikel(jpeg: bytes) -> tuple[bool, list[float]]` → (heikel?, Bildvektor 512). Heikel, wenn `max(cos(bild, heikel_i)) − max(cos(bild, neutral_j)) > abstand`. Textvektoren werden einmal im Konstruktor per `einbetter.text_clip` berechnet.
  - `ABSTAND` aus Umgebung `AUGE_HEIKEL_ABSTAND`, Vorgabe = der kalibrierte Wert aus Step 2 (im Code mit Datum und Messwerten kommentiert).
- `auge._eine`: Ist `soll_aufnehmen` wahr und `pruefer.heikel(jpeg)[0]`, wird **nicht** abgelegt, `bildschirm.uebersprungen_zaehlen(uid)`, `letzter_hash`/`letzte_zeit` werden trotzdem gesetzt (kein erneutes Prüfen desselben Bildes), `anzahl` bleibt; Log: `Heikles Bild verworfen uid=… (Nr. übersprungen n)`. Der beim Prüfen berechnete Bildvektor wird beim Ablegen mitgegeben (`bild_ablegen(..., vektor_bild=...)` – optionaler Parameter; `bild_arbeit.naechste_beschreiben` rechnet `vektor_bild` nur noch, wenn er NULL ist). Der Prüfer nutzt dieselbe `GesperrterEinbetter`-Instanz wie der Beschreib-Thread (Sperre teilen, kein zweites Modell im Speicher).
- Akte zeigt im Reiter „Bildschirm“ bei `bilder_uebersprungen > 0`: „N heikle Bildschirme (Anmeldung, Bezahlung, Postfach) wurden nicht gespeichert.“ (`termin_akte.lesen` liefert `bilder_uebersprungen`).

- [ ] **Step 1: Kalibrierskript** `scripts/heikel_kalibrieren.py` (nur lesend): lädt alle `termin_bilder` der Akten `3c9afada…` und `54ac1821…`, setzt die Wahrheit aus der Beschreibung per Stichwort (`passwort|anmelde|sign in|login|checkout|zahlung|kreditkarte|bezahl|posteingang|inbox|e-mail-postfach|gmx`), rechnet je Bild die Abstandsgröße und gibt für Abstände 0,00…0,10 (Schritt 0,005) Treffer/Fehlalarme aus. Läuft im Container `sales-auge` auf der VM (`docker exec -i sales-auge python - < scripts/heikel_kalibrieren.py`), gibt nur Zahlen aus.
- [ ] **Step 2:** Lauf auf der VM; Abstand wählen: höchste Trefferquote bei ≤ 2 % Fehlalarmen; Wahl + Tabelle in den Bericht und als Kommentar an `ABSTAND`. Liegt die Trefferquote dabei unter 70 %, Befund melden (Schicht B trägt dann mehr).
- [ ] **Step 3: Failing tests:** `test_heikel.py` mit Attrappen-Einbetter (feste Vektoren): `test_heikel_ueber_abstand`, `test_neutral_unter_abstand`, `test_textvektoren_nur_einmal`; `test_auge.py`: `test_heikles_bild_wird_nicht_abgelegt_und_gezaehlt`, `test_heikles_bild_nicht_alle_runden_neu_geprueft` (gleicher Frame zweimal → Prüfer einmal aufgerufen); `test_termin_schema.py`: Spalte `bilder_uebersprungen` vorhanden.
- [ ] **Step 4:** FAIL bestätigen (`--provision` wegen Spalte). **Step 5:** umsetzen. **Step 6:** `vm_test.sh --provision tests/test_heikel.py tests/test_auge.py tests/test_termin_schema.py tests/test_bildschirm.py tests/test_ui_termin.py tests/test_bild_arbeit.py` PASS.
- [ ] **Step 7:** Commit `feat(auge): heikle Bildschirme lokal erkennen und nicht speichern`.

### Task 5: KI meldet übersehene heikle Bildschirme (Schicht B)

**Files:**
- Modify: `sales-mcp/bild_arbeit.py` (`BILD_PROMPT`, `naechste_beschreiben`)
- Test: `sales-mcp/tests/test_bild_arbeit.py`

**Interfaces:**
- Consumes: `bildschirm.uebersprungen_zaehlen(uid)` (Task 4).
- `BILD_PROMPT` bekommt den Satz (wörtlich): `Zeigt das Bild eine Anmeldung mit Passwort- oder Kontoauswahl, eine Bezahlseite mit Karten- oder Kontodaten oder ein E-Mail-Postfach bzw. eine geöffnete E-Mail, antworte nur mit dem Wort HEIKEL.`
- Antwort beginnt (nach `strip()`, groß/klein egal) mit `HEIKEL` → Zeile wird per `delete from termin_bilder where id = %s` entfernt, `uebersprungen_zaehlen(uid)`, Rückgabe `"heikel"`, Log `Heikles Bild nach Beschreibung entfernt uid=…`. Kein Versuchszähler-Effekt auf andere Bilder.

- [ ] **Step 1: Failing tests:** `test_heikel_antwort_loescht_bild_vollstaendig` (Zeile weg, Zähler +1), `test_heikel_klein_geschrieben`, `test_normale_beschreibung_mit_wort_heikel_im_satz_bleibt` („Eine heikle Folie…“ beginnt nicht mit HEIKEL → bleibt), `test_prompt_enthaelt_heikel_regel`.
- [ ] **Step 2:** FAIL. **Step 3:** umsetzen. **Step 4:** `vm_test.sh tests/test_bild_arbeit.py tests/test_auge.py` PASS.
- [ ] **Step 5:** Commit `feat(bild): KI meldet heikle Bildschirme, Bild wird geloescht`.

### Task 6: Mehrere gleichzeitige Freigaben

**Files:**
- Modify: `sales-mcp/auge_jitsi.js` (`holen`, `standbild`, Rückgabeform), `sales-mcp/auge.py` (`Sitzung`, `_frame`, `_eine`, `_neu_beginnen`)
- Test: `sales-mcp/tests/test_auge.py` (Python-Seite; JS weiter statisch geprüft)

**Interfaces:**
- JS: `window.__lauraBild()` → `{teilt: bool, quellen: [{quelle: string, von: string|null, jpeg: string|null}]}`; je Desktop-Track (ungemutet, `istDesktop`) ein eigenes `<video>` in einer `Map` nach `getSourceName()` (Rückfall: `participantId`); höchstens `MAX_QUELLEN = 3` (sortiert nach Quelle); verschwundene Quellen lösen ihr Video. Gesamtzeit je Aufruf bleibt `HOECHSTENS_MS = 8000`.
- Python: `Sitzung.quellen: dict[str, Quelle]` mit `@dataclass Quelle(von: str | None, letzter_hash: int | None, letzte_zeit: datetime | None)`. Drossel (`MIN_ABSTAND`) und Hash je Quelle; `anzahl`/Obergrenze je Akte (gemeinsam). `freigabe_ende(uid, jetzt)` nur, wenn keine Quelle mehr teilt. Eine neue Quelle beginnt mit `letzter_hash=None` (unter der Obergrenze) bzw. dem Akte-weiten letzten Hash (ab Obergrenze, wie bisher `_neu_beginnen`).
- `_frame` akzeptiert nur die neue Form; alte Form → als „teilt nicht“ behandeln.

- [ ] **Step 1: Failing tests:** `test_zwei_quellen_beide_abgelegt` (zwei Quellen, verschiedene Frames → zwei Bilder mit je eigenem `von`), `test_drossel_je_quelle` (Quelle A legt ab, B im selben Moment auch), `test_quelle_endet_andere_laeuft_weiter` (A verschwindet: kein `freigabe_ende`, B-Zustand unverändert), `test_obergrenze_gemeinsam`, `test_max_drei_quellen_js` (statisch: `MAX_QUELLEN = 3` im JS), `test_kamera_bleibt_ausgeschlossen_js` (statisch: `istDesktop` unverändert genutzt).
- [ ] **Step 2:** FAIL. **Step 3:** umsetzen. **Step 4:** `vm_test.sh tests/test_auge.py` PASS.
- [ ] **Step 5: Probe** (wie Task 6 des Vorgängerplans, Ruling R2): Wegwerf-Raum auf meet.ffmuc.net, zwei Fake-Teilnehmer teilen gleichzeitig verschiedene Testbilder; Test-Abbild `sales-auge-test:dev`; Erwartung: Bilder beider Quellen, Kamera/Ton eingehend 0 B, ausgehend 0 B; Speicherspitze notieren (Grenze 2560m).
- [ ] **Step 6:** Commit `feat(auge): mehrere gleichzeitige Bildschirmfreigaben erfassen`.

### Task 7: Doku, Rollout, Neu-Auswertung, Rest-Abnahme

**Files:**
- Modify: `docs/03_RUNBOOK.md` (Abschnitt Bildauswertung: Schicht A/B, `AUGE_HEIKEL_ABSTAND`, Zähler, mehrere Freigaben, Mitschrift-Bereinigung), `docs/06_DSGVO.md` (heikle Bildschirme werden nicht gespeichert; Schicht B: Bild ging zur Prüfung an das KI-Tor, wird danach gelöscht)
- Create: `scripts/neu_auswerten.py` (`uid` als Argument: Segmente der gespeicherten Mitschrift durch `mitschrift_bereinigen.bereinigen` schicken, `auswertung_status='offen'`, `auswertung_versuche=0`; nur wenn kein Entwurf verschickt ist – sonst Abbruch mit Meldung)

- [ ] **Step 1:** Doku + Skript; Commit `docs: Abnahme-Befunde im Runbook und DSGVO`.
- [ ] **Step 2:** PR gegen `feat/stufe-1-fundament`; CI grün; **Merge nur mit Felix' OK.**
- [ ] **Step 3 (VM, Claim zuerst):** Sicherung Schema `sales`; `provision.sql`; `deploy/update.sh` (baut `sales-mcp`, `sales-ui`, `sales-termine`, `sales-auge` neu); `deploy/smoke.sh` → ALLE PRUEFUNGEN GRUEN.
- [ ] **Step 4:** Neu-Auswertung beider Termine: `scripts/neu_auswerten.py 3c9afada-…` und `54ac1821-…`; Taktgeber wertet aus; prüfen: Stimmung/Ergebnis stimmig, Beteiligte ohne Bots/Doppelte, Anteil `?`-Sprecher und ≤2-Wort-Segmente vorher/nachher im Bericht.
- [ ] **Step 5:** Optional nach Kalibrierung: bereits gespeicherte heikle Bilder der beiden Termine mit dem Prüfer markieren und nach Felix' OK löschen (Liste der ids nur an Felix, nicht ins Log).
- [ ] **Step 6:** Rest-Abnahme mit Felix: §2 (zwei gleichzeitige Freigaben), §6 (Schalter aus → Laura geht binnen einer Runde), §7 (Mitschrift-Löschen an einem Wegwerf-Termin, nicht an Dianas Terminen), plus ein heikler Bildschirm (Testanmeldeseite) → nicht in der Akte, Zähler +1. Ergebnisse in die Abnahme-Tabelle im Runbook.

## Bewusst nicht in diesem Plan

- Sprechererkennung bei Vexa selbst (Diarisierung auf Jitsi): wir füllen nur offensichtliche Lücken.
- Rückwirkendes Bereinigen anderer, älterer Mitschriften (nur die zwei Abnahme-Termine).
- Einladungshinweis und eigene DB-Rolle für Kundentermine (offen aus dem Vorgängerplan).
- Google-Meet-Raumanlage (HTTP 400, eigener Befund).
