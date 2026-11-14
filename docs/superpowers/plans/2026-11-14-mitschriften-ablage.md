# Mitschriften-Ablage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nach jeder fertigen Auswertung entsteht ein interner HTML-Bericht als Datei, eine KI ordnet ihn in eine Rubrik (Ordner) ein, und sales-ui zeigt alle Berichte unter dem neuen Hauptpunkt „Mitschriften“ mit einem Reiter je Rubrik.

**Architecture:** Zwei neue Module in `sales-mcp/`: `mitschrift_bericht.py` (HTML erzeugen, Datei ablegen/verschieben/löschen, Abgleich) und `mitschrift_einordnung.py` (KI wählt die Rubrik). Der Taktgeber `termin_takt.py` bekommt einen Schritt `ablage` nach `auswerten` (je Runde höchstens eine Einordnung und ein Bericht; stündlich der Datei-Abgleich). sales-ui bekommt `ui_mitschriften.py` (Liste mit Reitern, Ausliefern, Verschieben). Die Dateien liegen je Laden unter `MITSCHRIFTEN_ORDNER` (Host) = `/mitschriften` (Container); die Datenbank führt Buch.

**Tech Stack:** Python 3 (Starlette, psycopg über `server._q`, Pillow), PostgreSQL (`db/provision.sql`, Schema je Laden), Docker Compose, Bash (deploy).

**Spec:** `docs/superpowers/specs/2026-11-14-mitschriften-ablage-design.md` (Vorlage des HTML: `docs/superpowers/specs/2026-11-14-mitschriften-ablage-bericht-vorlage.py`)

## Global Constraints

- Tests laufen auf der VM gegen `meeting_test`/`sales_test`: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh [--provision] <pytest-Argumente>` (nach Schema-Änderung `--provision`). Python-Dateien des Repos sind CRLF – Zeilenenden beibehalten.
- Dateien sind die Ablage, die Datenbank führt Buch. Schreiben immer: Datei temporär schreiben + `os.replace`, dann Datenbank; alte Datei danach entfernen.
- Nur Bilder mit `beschreibung_status = 'fertig'` in einen Bericht (`bildschirm.bilder(uid)` / `bildschirm.bild_daten(uid, id)` ohne `auch_ungeprueft`). Höchstens 6 Bilder je Verlaufseintrag, max. 1000 px, JPEG q70.
- Kennzeichnung oben im Bericht wörtlich: „Intern – enthält Kundendaten, nicht weitergeben“.
- Dateiname: `JJJJ-MM-TT_HHMM_<titel-kurz>_<uid8>.html` (Datum/Zeit Berlin). `uid8` = `hashlib.sha256(uid.encode()).hexdigest()[:8]` (wie `_h` in `bild_arbeit.py`; die rohe uid steht nie im Dateinamen).
- Rubrik-Namen: nur Buchstaben inkl. Umlaute/ß, Ziffern, Leerzeichen, Bindestrich; Leerraum zusammengefasst; max. 40 Zeichen; Vergleich gegen vorhandene ohne Groß/Klein. Rückfall-Rubrik: `Unsortiert`.
- Höchstens 12 Rubriken je Laden – bindet nur die KI; `Unsortiert` zählt nicht; gezählt aus der Datenbank (Rubriken mit ≥ 1 Mitschrift). Felix darf beim Verschieben jederzeit eine neue anlegen.
- KI: dieselbe wie die Auswertung, `ollama.chat(system, nutzer, als_json=True, timeout_s=…)`; nicht laufen lassen, wenn ein Termin ansteht (`termin_takt._termin_steht_an`) oder `ollama.erreichbar()` falsch ist. Fehlschlag → `Unsortiert`, Neuversuch höchstens 3-mal, je 1 h Abstand (wie `MAX_AUSWERTUNGEN`/`NEUVERSUCH_NACH`).
- Eine von Hand gesetzte Rubrik (`rubrik_manuell = true`) überschreibt die KI nie.
- Ausliefern nur angemeldet, `Cache-Control: private, no-store`; Download mit `Content-Disposition: attachment; filename="<dateiname>"`.
- Logs: nur gekürzte uid (`uid8`), Anzahlen, Fehlerart (`type(e).__name__`). Nie Titel, Namen, Rubrik-Namen aus der KI, Text.
- Jeder Weg, der eine Mitschrift löscht, löscht die Bericht-Datei mit.
- `MITSCHRIFTEN_ORDNER` ist Pflicht je Laden; nur der Basis-Laden hat die Vorgabe `./laeden-daten/sales/mitschriften`.
- Keine neuen Abhängigkeiten (Pillow ist schon im Abbild).

## Review Focus

1. **Rubrik-Name als Pfad:** KI-Antwort oder Formular mit `../x`, `a/b`, nur Satzzeichen, leer, 200 Zeichen, „kurse“ statt „Kurse“ → wird normalisiert (kein Pfadtrenner, keine Punkte), leer fällt auf `Unsortiert` zurück, Groß/Klein-Gleiches landet in der vorhandenen Rubrik. Jede Auslieferung prüft zusätzlich, dass der aufgelöste Pfad unter `/mitschriften` liegt. (Tests in Task 2 und Task 5.)
2. **Ordner fehlt oder falsch eingehängt** (leeres Verzeichnis, nicht beschreibbar): Abgleich löscht nichts und warnt; Erzeugen hinterlässt keine halbe Datei und keine DB-Buchung; die Oberfläche zeigt „Bericht fehlt“ (404), keinen 500. (Tests in Task 2, 4, 5.)
3. **Löschen während des Erzeugens:** Die Mitschrift wird gelöscht, während `ablegen` die Datei schreibt → das DB-Update trifft keine Zeile, die frisch geschriebene Datei wird sofort entfernt. (Test in Task 2.)
4. **Von Hand eingeordnet bleibt eingeordnet:** Nach „Verschieben“ ordnet der Takt nie neu ein, auch nicht nach `neu_auswerten`; eine neue Auswertung erzeugt den Bericht neu im selben Ordner. (Tests in Task 3, 4.)
5. **Titel mit Sonderzeichen / leer / sehr lang, zwei Termine gleicher Minute und gleichen Titels:** Dateiname bleibt ASCII-sicher (Umlaute transliteriert), `titel-kurz` ≤ 40 Zeichen, Rückfall `termin`; `uid8` trennt die zwei. Titel und Text im HTML sind maskiert. (Tests in Task 2.)

---

### Task 1: Schema, Ordner und Betrieb (Compose, Deploy, Sicherung)

**Files:**
- Modify: `db/provision.sql` (bei den `termin_mitschriften`-Spalten, ~Z. 370)
- Modify: `docker-compose.yml` (Dienste `sales-termine` ~Z. 800, `sales-ui` ~Z. 1020/`volumes:` ~Z. 1171)
- Modify: `deploy/laden-anlegen.sh` (~Z. 205-208), `deploy/update.sh` (~Z. 105-125), `deploy/laeden/beispiel.env` (~Z. 212), `deploy/sicherung.sh` (~Z. 79), `deploy/wiederherstellen.sh`
- Modify: `docs/04_BACKUP_RESTORE.md` (ein Absatz: Mitschriften-Ordner je Laden wird gesichert/wiederhergestellt)
- Test: `sales-mcp/tests/test_termin_schema.py`, Create: `deploy/tests/test_mitschriften_ordner.sh`

**Interfaces:**
- Produces: Spalten auf `termin_mitschriften`: `rubrik text null`, `rubrik_manuell boolean not null default false`, `bericht_pfad text null` (relativ zu `/mitschriften`, Form `<Rubrik>/<dateiname>`), `bericht_am timestamptz null`, `bericht_stand text null`, `einordnung_versuche integer not null default 0`, `einordnung_am timestamptz null`.
- Produces: in beiden Containern `sales-termine` und `sales-ui` Umgebungsvariable `MITSCHRIFTEN_PFAD=/mitschriften` und Volume `${MITSCHRIFTEN_ORDNER:-./laeden-daten/sales/mitschriften}:/mitschriften` (rw).

- [ ] **Step 1: Failing tests schreiben**
  - `test_termin_schema.py`: die erwartete Spaltenmenge für `termin_mitschriften` um die sieben Spalten erweitern (gleiches Muster wie Z. 20/33); `test_mitschriften_spalten_vorgaben`: neue Zeile einfügen → `rubrik_manuell is False`, `einordnung_versuche == 0`, `rubrik/bericht_pfad/bericht_am/bericht_stand/einordnung_am is None`.
  - `deploy/tests/test_mitschriften_ordner.sh` (Muster wie `test_auge_compose.sh`, ohne Docker-Start): `docker compose config` mit einer Laden-.env zeigt für `sales-termine` und `sales-ui` je ein Volume mit Ziel `/mitschriften` ohne `read_only`; `update.sh` (Prüfteil) weist eine Laden-.env ohne `MITSCHRIFTEN_ORDNER`, mit `./laeden-daten/sales/mitschriften` und mit einem Wert, den ein zweiter Laden schon nutzt, jeweils mit `FEHLER:` ab; `laden-anlegen.sh` schreibt `MITSCHRIFTEN_ORDNER=./laeden-daten/<name>/mitschriften`; `sicherung.sh` enthält das Paar `MITSCHRIFTEN_ORDNER:mitschriften`.

- [ ] **Step 2: Tests laufen lassen – sie scheitern**
  Run: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh --provision tests/test_termin_schema.py` und `bash deploy/tests/test_mitschriften_ordner.sh`
  Expected: FAIL (Spalten fehlen / Volume fehlt).

- [ ] **Step 3: Umsetzen**
  - `provision.sql`: sieben `alter table %I.termin_mitschriften add column if not exists …` im bestehenden `execute format`-Muster.
  - Compose: Volume + `MITSCHRIFTEN_PFAD` an beiden Diensten; Kommentar wie bei Medien („Vorgabe gehört dem Basis-Laden; update.sh weist andere Läden ohne eigenen Ordner ab“). Container laufen als root (kein `USER` im Dockerfile) – keine Rechte-Anpassung nötig; Dateien bleiben bei Standard-umask lesbar für `sicherung.sh`.
  - `update.sh`: `MITSCHRIFTEN_ORDNER` in die vorhandene Prüfschleife aufnehmen; abgewiesen werden leer, `./laeden-daten/sales/mitschriften`, `laeden-daten/sales/mitschriften`, `$WURZEL/laeden-daten/sales/mitschriften` und doppelt genutzte Werte.
  - `laden-anlegen.sh` und `beispiel.env`: Zeile `MITSCHRIFTEN_ORDNER=./laeden-daten/<name>/mitschriften` mit einem Kommentar „Terminberichte je Laden (Mitschriften-Ablage, 14.11.2026)“.
  - `sicherung.sh`: Paar `MITSCHRIFTEN_ORDNER:mitschriften`; für den Basis-Laden ist die Vorgabe `./laeden-daten/sales/mitschriften` (nicht `./mitschriften`) – die Schleife braucht dafür je Paar eine eigene Vorgabe.
  - `wiederherstellen.sh`: liegt `mitschriften.tar.gz` im Sicherungsordner des Ladens, wird der Ordner aus der Laden-.env (bzw. Basis-Vorgabe) geleert und entpackt; fehlt die Datei, nur Hinweis, kein Fehler.

- [ ] **Step 4: Tests laufen lassen – grün**
  Run: wie Step 2. Expected: PASS.

- [ ] **Step 5: Commit**
  `git commit -m "feat(mitschriften): Spalten und Ordner je Laden fuer die Bericht-Ablage"`

---

### Task 2: Bericht erzeugen und ablegen (`mitschrift_bericht.py`)

**Files:**
- Create: `sales-mcp/mitschrift_bericht.py`
- Test: Create `sales-mcp/tests/test_mitschrift_bericht.py`

**Interfaces:**
- Consumes: Spalten aus Task 1; `bildschirm.bilder(uid)`, `bildschirm.bild_daten(uid, id)`, `bildschirm.bilder_zu_abschnitt(seg, von, bis, bilder)`, `ui_termin._md`, `ui_termin._e`, `server._q`.
- Produces:
  - `UNSORTIERT = "Unsortiert"`
  - `ordner() -> pathlib.Path` – `Path(os.environ.get("MITSCHRIFTEN_PFAD", "/mitschriften"))`
  - `uid8(uid: str) -> str`
  - `rubrik_normalisieren(name: object) -> str | None` – normalisiert nach Global Constraints; `None`, wenn nichts übrig bleibt.
  - `rubrik_angleichen(name: str, vorhandene: list[str]) -> str` – liefert die vorhandene Schreibweise bei Groß/Klein-Gleichheit, sonst `name`.
  - `dateiname(titel: str | None, beginn: datetime | None, uid: str) -> str`
  - `STAND_SQL: str` – SQL-Ausdruck über Alias `m` (termin_mitschriften): `md5(coalesce(m.auswertung_am::text,'') || '|' || coalesce((select string_agg(b.id::text, ',' order by b.id) from termin_bilder b where b.uid = m.uid and b.beschreibung_status = 'fertig'), ''))`
  - `stand(uid: str) -> str | None` – derselbe Ausdruck für eine uid.
  - `bericht_html(uid: str) -> str` – HTML wie die Vorlage; `ValueError`, wenn keine fertige Auswertung.
  - `ablegen(uid: str) -> str | None` – erzeugt und legt ab, gibt den relativen Pfad zurück; `None`, wenn die Mitschrift inzwischen weg ist oder `rubrik` leer ist.
  - `datei_entfernen(pfad: str | None) -> None` – entfernt eine Datei unter `ordner()` (relativ), still bei fehlender Datei; verweigert Pfade außerhalb von `ordner()`.
  - `sicherer_pfad(pfad: str) -> pathlib.Path | None` – aufgelöster Pfad nur, wenn er unter `ordner()` liegt.

- [ ] **Step 1: Failing tests schreiben** (Fixture: `monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(tmp_path))`, Akte + Mitschrift mit `auswertung_status='fertig'` wie in `test_neu_auswertung.py` anlegen)
  - `test_rubrik_normalisieren`: `"  interne   Besprechungen "` → `"interne Besprechungen"`; `"../Kurse/x"` → `"Kurse x"` (Punkte/Schrägstriche entfernt, Leerraum zusammengefasst); `"Übungen-Ä 2"` bleibt; `"!!!"` → `None`; `None` → `None`; Länge 200 → 40 Zeichen, ohne End-Leerzeichen.
  - `test_rubrik_angleichen`: `rubrik_angleichen("kurse", ["Kurse"]) == "Kurse"`; `rubrik_angleichen("Neu", ["Kurse"]) == "Neu"`.
  - `test_dateiname`: `dateiname("Kurs: Übung/1 – Teil", datetime(2026,11,14,9,5,tzinfo=UTC), "abc")` == `f"2026-11-14_1005_kurs-uebung-1-teil_{uid8('abc')}.html"`; leerer Titel → `…_termin_…`; 300-Zeichen-Titel → `titel-kurz` ≤ 40; zwei uids, gleicher Titel/Minute → verschiedene Namen.
  - `test_bericht_nur_gepruefte_bilder`: ein `fertig`- und ein `offen`-Bild im Verlaufsbereich → genau ein `<img` im HTML.
  - `test_bericht_maskiert_und_kennzeichnet`: Titel `<script>x</script>` und Segmenttext `<b>` erscheinen maskiert; HTML enthält „Intern – enthält Kundendaten, nicht weitergeben“; keine `<script`-Marke.
  - `test_ablegen_schreibt_datei_und_bucht`: `rubrik='Kurse'` → Datei `tmp_path/Kurse/<dateiname>` existiert, DB `bericht_pfad == "Kurse/<dateiname>"`, `bericht_am` gesetzt, `bericht_stand == stand(uid)`; keine `*.tmp`-Reste.
  - `test_ablegen_verschiebt_alte_datei`: zweites `ablegen` nach Rubrikwechsel → alte Datei weg, neue da.
  - `test_ablegen_mitschrift_inzwischen_geloescht`: `bericht_html` per monkeypatch so umhüllen, dass es vor der Rückgabe die Mitschrift löscht → `ablegen` gibt `None`, kein `*.html` unter `tmp_path`.
  - `test_ablegen_ordner_nicht_beschreibbar`: `MITSCHRIFTEN_PFAD` auf eine Datei statt eines Ordners → `ablegen` wirft `OSError`, `bericht_pfad` bleibt `None`.
  - `test_stand_aendert_sich_bei_bildloeschung`: `stand` vorher ≠ nachher, wenn ein fertiges Bild gelöscht wird.
  - `test_sicherer_pfad`: `"../x.html"` → `None`; `"Kurse/a.html"` → Pfad unter `tmp_path`.

- [ ] **Step 2: Laufen lassen – scheitern**
  Run: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh tests/test_mitschrift_bericht.py -v`
  Expected: FAIL (`ModuleNotFoundError: mitschrift_bericht`).

- [ ] **Step 3: Umsetzen**
  - HTML: Inhalt und CSS aus der Vorlage übernehmen (Kopf, Auswertung über `ui_termin._md`, „Bilder je Thema“ mit gleichmäßigem Ausdünnen auf 6, „Transkript“-Tabelle mit Berliner Zeit); zusätzlich im Kopf die Rubrik. Die Vorlage selbst bleibt unverändert.
  - `titel-kurz`: Kleinbuchstaben, `ä→ae ö→oe ü→ue ß→ss`, alles außer `[a-z0-9]` → `-`, Mehrfach-`-` zusammengefasst, Ränder gestutzt, ≤ 40, leer → `termin`.
  - `ablegen`: liest `rubrik`, `bericht_pfad`, Titel/Beginn der Akte; `stand` vor dem Erzeugen ermitteln; Datei als `<ziel>.tmp` im Zielordner schreiben, `os.replace`; dann `update termin_mitschriften set bericht_pfad=%s, bericht_am=now(), bericht_stand=%s where uid=%s and auswertung_status='fertig' returning id`. Trifft das keine Zeile → neue Datei entfernen, `None`. Sonst alte Datei entfernen, wenn ihr Pfad ≠ neuer Pfad. Bei Ausnahme die `.tmp` entfernen und weiterwerfen.
  - Log: `log.info("Bericht abgelegt uid=%s", uid8(uid))`.

- [ ] **Step 4: Laufen lassen – grün**
  Run: wie Step 2. Expected: PASS.

- [ ] **Step 5: Commit**
  `git commit -m "feat(mitschriften): HTML-Bericht je Mitschrift als Datei ablegen"`

---

### Task 3: KI-Einordnung (`mitschrift_einordnung.py`)

**Files:**
- Create: `sales-mcp/mitschrift_einordnung.py`
- Test: Create `sales-mcp/tests/test_mitschrift_einordnung.py`

**Interfaces:**
- Consumes: `mitschrift_bericht.UNSORTIERT`, `rubrik_normalisieren`, `rubrik_angleichen`, `uid8`; `ollama.chat`.
- Produces:
  - `MAX_RUBRIKEN = 12`, `MAX_VERSUCHE = 3`, `NEUVERSUCH_NACH = timedelta(hours=1)`, `KI_TIMEOUT_S = 120`
  - `vorhandene_rubriken() -> list[tuple[str, int]]` – Rubriken mit Anzahl aus der DB (`rubrik is not null`), ohne `Unsortiert`, nach Anzahl absteigend, dann Name.
  - `rubrik_waehlen(eingabe: dict, vorhandene: list[tuple[str, int]]) -> str` – KI-Aufruf + Auswertung der Antwort; wirft bei KI-Fehler/unbrauchbarer Antwort.
  - `einordnen(uid: str) -> str` – liest Titel/Kurzfassung/Beteiligte/Art, ruft `rubrik_waehlen`, schreibt `rubrik`, `einordnung_versuche+1`, `einordnung_am=now()` **nur wo `rubrik_manuell = false`** (`returning`); bei Ausnahme → `rubrik = 'Unsortiert'` (gleiche Bedingung), Fehlerart loggen; gibt die gesetzte Rubrik zurück (bei manueller die vorhandene).

- [ ] **Step 1: Failing tests schreiben** (`ollama.chat` per monkeypatch; Prompt-Inhalt über den aufgezeichneten Aufruf prüfen)
  - `test_waehlt_vorhandene_bei_gleichem_namen`: KI antwortet `{"rubrik": "kurse", "neu": false}`, vorhanden `[("Kurse", 2)]` → `"Kurse"`.
  - `test_neue_rubrik`: Antwort `{"rubrik": "Interne Besprechungen", "neu": true}` → `"Interne Besprechungen"`.
  - `test_grenze_erreicht_erzwingt_vorhandene`: 12 vorhandene, KI antwortet mit neuer Rubrik → Ergebnis ist eine der 12 (nicht die neue) – Regel: zweiter KI-Aufruf mit dem Hinweis „wähle eine vorhandene“; ist auch die zweite Antwort keine vorhandene → `ValueError` (führt in `einordnen` zu `Unsortiert`).
  - `test_unsortiert_zaehlt_nicht`: 12 Rubriken plus `Unsortiert` in der DB → `len(vorhandene_rubriken()) == 12`, und `Unsortiert` ist nicht darunter.
  - `test_ki_fehler_setzt_unsortiert`: `ollama.chat` wirft `TimeoutError` → `einordnen` gibt `"Unsortiert"`, DB `rubrik='Unsortiert'`, `einordnung_versuche == 1`.
  - `test_unbrauchbare_antwort`: Antworten `"kein json"`, `{"rubrik": ""}`, `{"rubrik": "../.."}` → jeweils `Unsortiert`.
  - `test_manuelle_rubrik_bleibt`: `rubrik='Kurse', rubrik_manuell=true`, KI antwortet `"Kundentermine"` → DB bleibt `Kurse`.
  - `test_prompt_inhalt`: der Nutzertext enthält Titel, Kurzfassung, Beteiligte, Art und die Liste vorhandener Rubriken mit Anzahl; der Systemtext verlangt JSON `{"rubrik": "...", "neu": true|false}`, vorhandene bevorzugen, 1–3 Wörter, Mehrzahl, deutsch, Beispiele „Kurse“, „Kundentermine“, „Interne Besprechungen“.
  - `test_log_ohne_inhalt` (caplog): nach erfolgreicher und gescheiterter Einordnung kein Titel und kein Rubrik-Name in den Logzeilen.

- [ ] **Step 2: Laufen lassen – scheitern**
  Run: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh tests/test_mitschrift_einordnung.py -v`
  Expected: FAIL (Modul fehlt).

- [ ] **Step 3: Umsetzen**
  Kurzfassung auf 1500 Zeichen kürzen; Beteiligte höchstens 10. Antwort mit `json.loads`, Feld `rubrik` durch `rubrik_normalisieren` + `rubrik_angleichen`. Ein Name gleich `Unsortiert` (ohne Groß/Klein) von der KI gilt als unbrauchbar.

- [ ] **Step 4: Laufen lassen – grün**
  Run: wie Step 2. Expected: PASS.

- [ ] **Step 5: Commit**
  `git commit -m "feat(mitschriften): KI ordnet jede Mitschrift einer Rubrik zu"`

---

### Task 4: Taktgeber, Abgleich und Löschwege

**Files:**
- Modify: `sales-mcp/termin_takt.py` (neuer Schritt nach `auswerten`, `SCHRITTE` ~Z. 568)
- Modify: `sales-mcp/mitschrift_bericht.py` (Abgleich)
- Modify: `sales-mcp/termin_akte.py:445-455` (`mitschrift_entfernen`), `sales-mcp/server.py:8885-8906` (`_mitschriften_abraeumen`, Sicherheitsnetz-Delete)
- Modify: `docs/03_RUNBOOK.md`, `docs/06_DSGVO.md` (Abschnitt Mitschriften-Ablage: was liegt wo, wer löscht, Abgleich stündlich)
- Test: `sales-mcp/tests/test_termin_takt.py`, `sales-mcp/tests/test_termin_akte.py`, `sales-mcp/tests/test_mitschrift_bericht.py`

**Interfaces:**
- Consumes: Task 2 (`ablegen`, `datei_entfernen`, `STAND_SQL`, `ordner`, `uid8`, `UNSORTIERT`), Task 3 (`einordnen`, `MAX_VERSUCHE`, `NEUVERSUCH_NACH`).
- Produces:
  - `mitschrift_bericht.abgleichen() -> dict` – `{"geloescht": int, "neu": int, "ordner_entfernt": int}` oder `{"uebersprungen": "<grund>"}`.
  - `termin_takt._ablage(jetzt: datetime) -> int` – Anzahl erledigter Vorgänge dieser Runde; Eintrag `("ablage", _ablage)` am Ende von `SCHRITTE`.

- [ ] **Step 1: Failing tests schreiben**
  - `test_termin_takt.py::test_ablage_ordnet_ein_und_legt_ab`: fertige Mitschrift ohne Rubrik, KI gemockt `"Kurse"` → nach einer Runde `rubrik='Kurse'`; nach der nächsten Runde (spätestens) `bericht_pfad` gesetzt und Datei vorhanden.
  - `test_ablage_ki_aus_legt_unsortiert_ab`: `ollama.erreichbar` → `False`; Mitschrift ohne Rubrik bleibt ohne Rubrik (keine Einordnung ohne KI), es entsteht kein Bericht. Mit KI-Fehler (erreichbar, `chat` wirft) → `Unsortiert`, Bericht unter `Unsortiert/`.
  - `test_ablage_neuversuch_unsortiert`: `rubrik='Unsortiert'`, `einordnung_versuche=1`, `einordnung_am` vor 2 h, KI jetzt `"Kurse"` → Rubrik `Kurse`, Bericht nach `Kurse/` verschoben; mit `einordnung_versuche=3` → kein Aufruf.
  - `test_ablage_wartet_bei_anstehendem_termin`: `_termin_steht_an` → `True`: keine Einordnung (Bericht-Erzeugung für bereits eingeordnete darf laufen).
  - `test_ablage_neu_bei_geaendertem_stand`: abgelegter Bericht, dann ein fertiges Bild löschen → nächste Runde erzeugt neu (`bericht_am` jünger, `bericht_stand` neu); `neu_auswerten`-Fall: `auswertung_am` ändert sich → neu erzeugt, `rubrik` und `rubrik_manuell=true` bleiben.
  - `test_mitschrift_bericht.py::test_abgleich_loescht_waisen_und_erzeugt_fehlende`: drei Dateien: eine gebuchte, eine `X_deadbeef.html` ohne Buchung im Rubrikordner, eine fremde `notiz.txt`; zweite Mitschrift gebucht, aber Datei fehlt → Waise gelöscht, `notiz.txt` bleibt, fehlende neu erzeugt, leerer Rubrikordner entfernt.
  - `test_abgleich_ueberspringt_ohne_erwartete_datei`: Ordner leer (aber DB hat Buchungen) → `{"uebersprungen": …}`, nichts gelöscht, nichts erzeugt; Ordner fehlt → ebenso.
  - `test_takt_abgleich_hoechstens_stuendlich`: zwei Runden im Abstand von 30 s → `abgleichen` genau einmal aufgerufen; nach 61 min erneut.
  - `test_termin_akte.py::test_mitschrift_entfernen_loescht_bericht`: abgelegter Bericht → `termin_akte.mitschrift_entfernen(uid)` → Datei weg.
  - `test_termin_akte.py::test_loeschantrag_loescht_bericht` (bzw. in der Datei, in der `_mitschriften_abraeumen` getestet wird): Lead-Löschung mit Mitschrift über die Adresse (Sicherheitsnetz-Weg) → Datei weg.

- [ ] **Step 2: Laufen lassen – scheitern**
  Run: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh tests/test_termin_takt.py tests/test_termin_akte.py tests/test_mitschrift_bericht.py -v`
  Expected: FAIL (`_ablage`/`abgleichen` fehlen, Dateien bleiben).

- [ ] **Step 3: Umsetzen**
  - `_ablage`: (a) wenn `ordner()` kein beschreibbares Verzeichnis → `_wechsel("mitschriften", False, …)` und `0`; (b) Einordnung: eine fertige Mitschrift mit `rubrik is null` oder (`rubrik='Unsortiert'` und nicht manuell und `einordnung_versuche < MAX_VERSUCHE` und `einordnung_am <= jetzt - NEUVERSUCH_NACH`), älteste zuerst, nur wenn kein Termin ansteht und `ollama.erreichbar()`; (c) Bericht: eine fertige Mitschrift mit `rubrik is not null` und (`bericht_pfad is null` oder `bericht_stand is distinct from STAND_SQL` oder `bericht_pfad` liegt nicht im Ordner der aktuellen Rubrik); (d) Abgleich höchstens stündlich (Modul-Zeitstempel). Jede Einzelaktion über `_je_akte(...)`.
  - Löschwege: in `termin_akte.mitschrift_entfernen` vor dem Delete `bericht_pfad` lesen (`delete … returning bericht_pfad`) und danach `datei_entfernen`; in `server._mitschriften_abraeumen` das Sicherheitsnetz-Delete ebenso `returning bericht_pfad`. Weitere `delete from termin_mitschriften` im Code suchen (Stand: nur diese zwei) – Kaskaden fängt der Abgleich.
  - `abgleichen`: Muster `^.+_[0-9a-f]{8}\.html$` nur in direkten Unterordnern; „erwartet“ = Menge aller `bericht_pfad`; überspringen, wenn der Ordner fehlt, nicht beschreibbar ist oder keine erwartete Datei existiert; löschen = passende Dateien, deren relativer Pfad nicht erwartet ist; danach gebuchte, aber fehlende Dateien über `ablegen` neu; leere Unterordner entfernen. Log nur Anzahlen.

- [ ] **Step 4: Laufen lassen – grün**, dann die Takt- und Akte-Suiten komplett
  Run: wie Step 2, danach `… vm_test.sh tests/test_termin_takt.py tests/test_termin_akte.py tests/test_neu_auswertung.py tests/test_bild_arbeit.py`
  Expected: PASS.

- [ ] **Step 5: Commit**
  `git commit -m "feat(mitschriften): Taktgeber legt ab, Abgleich und Loeschwege raeumen Berichte mit"`

---

### Task 5: Hauptpunkt „Mitschriften“ in sales-ui (`ui_mitschriften.py`)

**Files:**
- Create: `sales-mcp/ui_mitschriften.py`
- Modify: `sales-mcp/ui.py` (`_GRUPPEN` ~Z. 2115: neue Gruppe; Routen-Liste ~Z. 10331: `*ui_mitschriften.routen(sys.modules[__name__])` neben `ui_termin`)
- Modify: `sales-mcp/mitschrift_bericht.py` (`verschieben`)
- Modify: `docs/05_BEDIENUNG.md` (kurzer Abschnitt „Mitschriften“)
- Test: Create `sales-mcp/tests/test_ui_mitschriften.py` (Aufbau wie `test_ui_termin.py`)

**Interfaces:**
- Consumes: Task 2/3/4; `ui._gesichert_seite`, `ui._seite`, `ui._fehlerseite`, `ui._csrf_ok`, `ui._AKTIVE_ROLLE`, `ui._CSP`, `ui_muster.reiter`.
- Produces:
  - `mitschrift_bericht.verschieben(uid: str, rubrik: str) -> str | None` – normalisiert (`rubrik_angleichen` gegen alle vorhandenen inkl. `Unsortiert`), setzt `rubrik`, `rubrik_manuell = true`, ruft `ablegen`; `None` bei ungültigem Namen oder fehlender Mitschrift.
  - Routen: `GET /mitschriften` (`?rubrik=`), `GET /mitschriften/bericht?uid=…[&download=1]`, `POST /mitschriften/verschieben` (Formular: `uid`, `rubrik` aus Auswahl oder `neue_rubrik`, `csrf`).
  - Menü: Gruppe `("Mitschriften", (("/mitschriften", "Mitschriften"),))` zwischen „Analyse“ und „Daten“.

- [ ] **Step 1: Failing tests schreiben**
  - `test_liste_reiter_mit_anzahl`: Mitschriften in `Kurse` (2) und `Kundentermine` (1) → Seite zeigt beide Reiter mit Zahl; `Unsortiert` (falls vorhanden) als letzter Reiter; Liste von `?rubrik=Kurse` zeigt neueste zuerst mit Datum, Titel, Beteiligten, Kurzfassung gekürzt auf 240 Zeichen; Links „Bericht öffnen“, „HTML herunterladen“, „Akte“ (`/termine/<uid>` url-kodiert).
  - `test_ohne_bericht_hinweis`: gebuchte Rubrik ohne `bericht_pfad` → „Bericht wird erstellt“, kein Öffnen-Link.
  - `test_bericht_ausliefern`: `GET /mitschriften/bericht?uid=…` → 200, `text/html`, `Cache-Control: private, no-store`, eigene CSP mit `default-src 'none'`, `img-src data:`, `style-src 'unsafe-inline'`, ohne `script-src`; Inhalt = Dateiinhalt.
  - `test_bericht_download`: `&download=1` → `Content-Disposition: attachment; filename="<dateiname>"`.
  - `test_bericht_fehlt_404`: Datei gelöscht / unbekannte uid / `bericht_pfad` manipuliert auf `../x.html` → 404-Seite, kein 500, keine Datei außerhalb gelesen.
  - `test_verschieben`: POST mit `rubrik=Kurse` → 303 zurück zur Liste, DB `rubrik='Kurse'`, `rubrik_manuell=true`, Datei liegt unter `Kurse/`; mit `neue_rubrik="Workshops"` → neue Rubrik, auch wenn schon 12 bestehen; `neue_rubrik="../.."` → 400-Seite, nichts geändert.
  - `test_verschieben_rechte`: ohne CSRF → 403; Rolle `lesen` → 403; Rolle `kalender` sieht `/mitschriften` nicht (Menü und Route, über `_pfad_erlaubt`).
  - `test_ohne_anmeldung`: mit gesetztem `UI_SESSION_SECRET`, ohne Sitzung → Weiterleitung auf `/login` für Liste und Bericht.
  - `test_menue`: Seitenleiste enthält Gruppe „Mitschriften“ mit Link `/mitschriften`.

- [ ] **Step 2: Laufen lassen – scheitern**
  Run: `bash .superpowers/sdd/2026-11-14-mitschriften-ablage/vm_test.sh tests/test_ui_mitschriften.py -v`
  Expected: FAIL (404 / Modul fehlt).

- [ ] **Step 3: Umsetzen**
  Liste aus der DB (`termin_mitschriften` join `termin_akten`, nur `auswertung_status='fertig'` und `rubrik is not null`, höchstens 200 je Reiter). Ohne `?rubrik=` gilt der erste Reiter. Verschieben-Formular je Eintrag: Auswahl der vorhandenen Rubriken plus Textfeld „neue Rubrik“; nur für schreibende Rollen sichtbar. Auslieferung: Pfad aus der DB über `sicherer_pfad`, Datei lesen, `Response(..., media_type="text/html; charset=utf-8")`.

- [ ] **Step 4: Laufen lassen – grün**, dazu `tests/test_ui_termin.py` und die Menü-/Rollen-Tests von `ui.py`
  Run: `… vm_test.sh tests/test_ui_mitschriften.py tests/test_ui_termin.py -k "" ` und `… vm_test.sh tests -k "seitenleiste or pfad_erlaubt or rolle"`
  Expected: PASS.

- [ ] **Step 5: Commit**
  `git commit -m "feat(mitschriften): Hauptpunkt Mitschriften mit Reitern, Bericht und Verschieben"`

---

## Ausrollen (nach Merge, nur mit Felix' OK; vorher Koordination prüfen und claimen)

1. Claim in `00_Meta/002_Koordination_Live.md` setzen und committen.
2. Sicherung von `sales`.
3. `~/sales-claw/laeden-daten/sales/mitschriften` anlegen; jede weitere Laden-.env (`ivan`, `sophie`, …) um `MITSCHRIFTEN_ORDNER` ergänzen (sonst weist `update.sh` sie ab).
4. `provision.sql`, dann `update.sh` gezielt für `sales-termine` und `sales-ui`; Smoke-Test.
5. Der Takt ordnet den Bestand von allein nacheinander ein (eine Mitschrift je Runde). Danach prüfen: die zwei Diana-Termine (`3c9afada…`, `54ac1821…`) liegen unter „Kurse“; sonst in der Oberfläche verschieben.
6. Felix öffnet einen Bericht unter „Mitschriften“ und druckt ihn testweise als PDF.
