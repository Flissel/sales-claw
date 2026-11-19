# Kursmitschrift und Kurs-Handbuch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aus Mitschriften der Rubrik „Kurse“ entstehen eine Kursmitschrift je Termin (Felix- und Lernenden-Fassung, Lernenden-PDF) und ein mitwachsendes Kurs-Handbuch je von Felix gewähltem Lernenden – alles zum Herunterladen in sales-ui, ohne Versand.

**Architecture:** Neuer Taktgeber-Schritt `kurs` (nach `ablage`) mit höchstens einem KI-Auftrag je Runde. `kurs_mitschrift.py` erzeugt die Kursmitschrift (KI-JSON → HTML/PDF), `kurs_handbuch.py` pflegt Kapitel mit Fassungen (B1: zuordnen, betroffene Kapitel fortschreiben, Quelle zurückrollen + neu einarbeiten), `kurs_pdf.py` lässt HTML von sales-auge (Chromium, neuer Endpunkt `POST /pdf`) zu PDF machen. sales-ui zeigt alles unter „Mitschriften → Kurse“ und „Handbücher“.

**Tech Stack:** Python 3 (sales-mcp), Postgres (Supabase, Schema je Laden), Starlette (sales-ui), Playwright/Chromium (sales-auge), Docker Compose, pytest gegen Test-DB.

**Spec:** `docs/superpowers/specs/2026-11-16-kursmitschrift-handbuch-design.md` (Fassung 2 vom 19.11.; baut auf `2026-11-14-mitschriften-ablage-design.md`).

## Global Constraints

- Auslöser: `termin_mitschriften.rubrik` = „Kurse“ (Vergleich ohne Groß/Klein), `auswertung_status = 'fertig'`, `bericht_pfad is not null`.
- **Kein Versand, keine Entwürfe:** kein Aufruf von `entwurf_erstellen` o. Ä., keine Zeile in `drafts`.
- KI nur über `ollama.chat` (sales-ki). Je Taktrunde höchstens **ein** KI-Auftrag im Schritt `kurs`; keiner, wenn `termin_takt._termin_steht_an(jetzt)` oder `not termin_takt._ollama_da()`.
- Fehler: bis zu 3 Versuche (`MAX_VERSUCHE = 3`) im Abstand `NEUVERSUCH_NACH = timedelta(hours=1)`, danach `kurs_status = 'fehler'`.
- Bilder nur aus `bildschirm.bilder(uid)` (geprüft, nicht heikel); höchstens 6 je Abschnitt (Kursmitschrift), höchstens 3 je Kapitel (Handbuch, die jüngsten); in HTML/PDF höchstens 800 px lange Kante, JPEG q60.
- Lernenden-Fassung und Handbuch: **kein** Rohtranskript, **kein** Teil „Offen“, keine internen Auswertungsteile. Felix-Fassung = Lernenden-Fassung + „Offen / nachfragen“ + Kennzeichnung „Intern – enthält Kundendaten, nicht weitergeben“.
- Kein Maskieren von Text (Felix: Variante A).
- Lernender nur per Wahl von Felix (`termin_mitschriften.kurs_lead_id`); private Kontakte erlaubt.
- Ablage nur im Mitschriften-Ordner (`mitschrift_bericht.ordner()`): Kursmitschrift im Rubrik-Unterordner, Handbuch in `_handbuecher/`.
- Logs nur Anzahlen, Typnamen, uid8 – keine Titel, Namen, Adressen, Texte.
- Auslieferung in sales-ui: nur angemeldet, `Cache-Control: private, no-store`, CSP ohne Skripte, Pfade nur aus der DB und nur unter dem Ordner (wie `ui_mitschriften`). Schreibende Aktionen mit CSRF, nicht für Rollen `lesen`/`kalender`.
- Neue `.py`-Dateien CRLF, `.sh` LF. Commits: Conventional Commits, Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests auf der VM gegen `meeting_test`/`sales_test`: `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh [--provision] tests/<datei>.py`. Prod `~/sales-claw` nie anfassen.

## Review Focus

1. **Alte Sitzung kommt nachträglich dazu** (älterer Termin wird nach „Kurse“ verschoben oder bekommt erst später den Lernenden): Kapitel auf den Stand vor ihrem Datum zurück, spätere Sitzungen neu einarbeiten. Test in Task 5 (`test_aeltere_sitzung_wird_an_datumsstelle_eingefuegt`).
2. **KI liefert kaputtes oder halbes JSON** (fehlende `abschnitte`, unbekannte `bild_id`, Kapitel-id eines anderen Lernenden): kein Absturz, Versuch zählt, nichts Fremdes geschrieben. Tests in Task 3 (`test_kaputtes_json_zaehlt_versuch`, `test_unbekannte_bild_id_wird_verworfen`) und Task 4 (`test_kapitel_eines_anderen_lernenden_wird_abgewiesen`).
3. **Lernenden-Wechsel** von Kontakt A zu B: Sitzung verschwindet aus A's Handbuch (Fassungen gelöscht), wird bei B eingearbeitet. Test in Task 5 (`test_lernenden_wechsel_verschiebt_quelle`).
4. **Mitschrift wird gelöscht** (Akte verwerfen oder Löschantrag): Kursmitschrift-Dateien weg, Kapitelfassungen mit ihrem Inhalt gelöscht, Handbuch-Dateien neu ausgegeben. Test in Task 5 (`test_loeschen_raeumt_dateien_und_fassungen`).
5. **Lernender-Kontakt wird gelöscht** (Löschantrag): ganzes Handbuch samt Dateien weg, `kurs_lead_id` der Mitschriften `null`. Test in Task 5 (`test_lead_loeschantrag_entfernt_handbuch`).

---

### Task 1: Schema und Lernenden-Wahl

**Files:**
- Modify: `db/provision.sql` (bei den `termin_mitschriften`-Ergänzungen ~Z. 373–380, Schleife über alle Laden-Schemata wie dort)
- Create: `sales-mcp/kurs_mitschrift.py` (in diesem Task nur Konstanten, Lernenden-Funktionen, Stand)
- Test: `sales-mcp/tests/test_kurs_schema.py`, `sales-mcp/tests/test_kurs_lernende.py`

**Interfaces:**
- Produces (Schema):
  - `termin_mitschriften` + `kurs_json jsonb`, `kurs_stand text`, `kurs_status text` (null | `'fertig'` | `'fehler'`), `kurs_am timestamptz`, `kurs_versuche integer not null default 0`, `kurs_pfad text` (Felix-HTML, relativ zum Ordner), `kurs_pfad_lernend text`, `kurs_pdf text` (relativ), `kurs_lead_id uuid references leads(id) on delete set null`.
  - `kurs_handbuch_kapitel(id uuid pk default gen_random_uuid(), lead_id uuid not null references leads(id) on delete cascade, titel text not null, reihenfolge integer not null, aktuelle_fassung uuid, erstellt_am timestamptz not null default now())`
  - `kurs_handbuch_fassung(id uuid pk default gen_random_uuid(), kapitel_id uuid not null references kurs_handbuch_kapitel(id) on delete cascade, text_md text not null, bild_ids text[] not null default '{}', quellen text[] not null, erstellt_am timestamptz not null default now())`
  - `kurs_handbuch_quelle(lead_id uuid not null references leads(id) on delete cascade, uid text not null, beginn timestamptz not null, stand text not null, zuordnung jsonb not null, eingearbeitet_am timestamptz, primary key (lead_id, uid))`
  - `kurs_handbuch(lead_id uuid pk references leads(id) on delete cascade, pfad text, pdf text, stand_am timestamptz, fassungen_stand timestamptz)`
- Produces (Python, `kurs_mitschrift.py`):
  - `RUBRIK_KURSE = "Kurse"`, `MAX_VERSUCHE = 3`, `NEUVERSUCH_NACH = timedelta(hours=1)`, `MAX_BILDER_ABSCHNITT = 6`, `BILD_KANTE = 800`, `BILD_QUALITAET = 60`
  - `ist_kurs(rubrik: str | None) -> bool`
  - `vorschlaege(uid: str) -> list[dict]` → `[{"lead_id": str, "name": str}]`: Teilnehmer des Termins mit `lead_id` oder mit Adresse = genau einem `leads.email` (ohne `rolle = 'organisator'`), danach die zuletzt in anderen Mitschriften gewählten `kurs_lead_id` (höchstens 5), eindeutig, private erlaubt.
  - `lernender_setzen(uid: str, lead_id: str | None) -> bool` – nur für Kurs-Mitschriften (sonst `False`), Lead muss existieren (sonst `False`); schreibt `kurs_lead_id`. (Die Handbuch-Folgen – alte Quelle entfernen – hängt Task 5 hier ein.)
  - `KURS_STAND_SQL: str` – SQL-Ausdruck über Alias `m` wie `mitschrift_bericht.STAND_SQL`, zusätzlich mit `lower(m.rubrik)`; `kurs_stand(uid: str) -> str | None`.

- [ ] **Step 1: Failing tests**
```python
# test_kurs_schema.py
def test_spalten_und_tabellen_da():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns where table_schema = current_schema() "
        "and table_name = 'termin_mitschriften'")}
    assert {"kurs_json", "kurs_stand", "kurs_status", "kurs_am", "kurs_versuche",
            "kurs_pfad", "kurs_pfad_lernend", "kurs_pdf", "kurs_lead_id"} <= spalten
    for t in ("kurs_handbuch_kapitel", "kurs_handbuch_fassung", "kurs_handbuch_quelle", "kurs_handbuch"):
        assert server._q("select to_regclass(%s) is not null as da", (t,))[0]["da"]
def test_lead_loeschen_kaskadiert_und_setzt_null(lead_mit_kapitel_und_mitschrift):
    server._q("delete from leads where id = %s", (lead,))
    assert not server._q("select 1 from kurs_handbuch_kapitel where lead_id = %s", (lead,))
    assert _zeile(uid)["kurs_lead_id"] is None

# test_kurs_lernende.py
def test_vorschlag_aus_teilnehmer_mit_lead(kurs_mitschrift_gast_mit_lead): assert [v["lead_id"] for v in km.vorschlaege(uid)] == [lead]
def test_vorschlag_ueber_adresse(kurs_mitschrift_gast_nur_adresse): assert len(km.vorschlaege(uid)) == 1
def test_organisator_kein_vorschlag(...): assert km.vorschlaege(uid) == []
def test_zuletzt_gewaehlte_werden_vorgeschlagen(zweite_kurs_mitschrift_mit_lernender_diana):
    assert diana in [v["lead_id"] for v in km.vorschlaege(neue_uid)]
def test_privater_kontakt_waehlbar(kurs_mitschrift, privater_lead): assert km.lernender_setzen(uid, privater_lead)
def test_nur_fuer_kurse(notiz_mitschrift, lead): assert not km.lernender_setzen(uid, lead)
def test_ist_kurs(): assert km.ist_kurs("kurse") and km.ist_kurs("Kurse") and not km.ist_kurs("Notizen") and not km.ist_kurs(None)
def test_kurs_stand_aendert_sich_mit_rubrik_und_auswertung(kurs_mitschrift): ...
```
Fixtures nach dem Muster von `tests/test_mitschrift_bericht.py` (Akte, Mitschrift, Teilnehmer, Leads per SQL; privat = `enrichment` wie `server._privat` es erkennt).

- [ ] **Step 2: FAIL** – `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh tests/test_kurs_schema.py tests/test_kurs_lernende.py`
- [ ] **Step 3: Implementieren** (`provision.sql` idempotent mit `add column if not exists` / `create table if not exists`).
- [ ] **Step 4: PASS** – derselbe Befehl mit `--provision`.
- [ ] **Step 5: Commit** – `feat(kurs): Schema und Lernenden-Wahl`

---

### Task 2: PDF über sales-auge

**Files:**
- Modify: `sales-mcp/auge.py` (`http_dienst`: `POST /pdf`; Ausführung im Hauptthread über eine Warteschlange, weil die Playwright-Sync-API an den Browser-Thread gebunden ist; `main()` arbeitet die Warteschlange zwischen den Takt-Schritten ab)
- Create: `sales-mcp/kurs_pdf.py`
- Modify: `docker-compose.yml` (`sales-termine`: `AUGE_URL: http://${LADEN_PRAEFIX:-sales}-auge:8790`)
- Test: `sales-mcp/tests/test_kurs_pdf.py`, `sales-mcp/tests/test_auge_pdf.py`

**Interfaces:**
- Produces:
  - sales-auge `POST /pdf` – Body `text/html; charset=utf-8` (höchstens 20 MB, sonst `413`), Antwort `200 application/pdf` (A4, `print_background=True`, Ränder 15 mm) oder `503` (Browser weg) / `504` (60 s Zeitlimit); eigener Browser-Kontext mit `java_script_enabled=False`, Seite immer schließen; nur im Compose-Netz (wie `/suche`).
  - `kurs_pdf.pdf_aus_html(html: str, zeitlimit_s: float = 90) -> bytes` – wirft `kurs_pdf.PdfFehler` bei jedem Nicht-200 oder Netzfehler.
  - `kurs_pdf.schreiben(ziel: pathlib.Path, inhalt: bytes | str) -> None` – atomar (tmp im selben Ordner + `os.replace`), legt Ordner an; `ziel` muss unter `mitschrift_bericht.ordner()` liegen (sonst `ValueError`).

- [ ] **Step 1: Failing tests**
```python
# test_kurs_pdf.py (sales-auge per monkeypatch auf urllib-Ebene ersetzt)
def test_pdf_aus_html_liefert_bytes(auge_liefert_pdf): assert kp.pdf_aus_html("<p>x</p>").startswith(b"%PDF")
def test_auge_fehler_wird_pdffehler(auge_antwortet_503):
    with pytest.raises(kp.PdfFehler): kp.pdf_aus_html("<p>")
def test_schreiben_atomar(ablage): kp.schreiben(ablage / "Kurse" / "a_kurs.pdf", b"%PDF-1"); assert not list(ablage.rglob("*.tmp"))
def test_schreiben_ausserhalb_abgelehnt(ablage, tmp_path):
    with pytest.raises(ValueError): kp.schreiben(tmp_path.parent / "x.pdf", b"x")
# test_auge_pdf.py: Warteschlange ohne echten Browser (Fake-Browser mit new_context/new_page/pdf) –
#   Auftrag wird im Hauptthread erledigt → 200 + Bytes; Browser weg → 503; Zeitlimit → 504; >20 MB → 413.
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_pdf.py tests/test_auge_pdf.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu `bash deploy/tests/test_auge_compose.sh`
- [ ] **Step 5: Commit** – `feat(kurs): PDF-Erzeugung ueber sales-auge`

---

### Task 3: Kursmitschrift erzeugen (A)

**Files:**
- Modify: `sales-mcp/kurs_mitschrift.py`
- Test: `sales-mcp/tests/test_kurs_mitschrift.py`

**Interfaces:**
- Consumes: Task 1, Task 2 (`kurs_pdf.pdf_aus_html`, `schreiben`, `PdfFehler`), `mitschrift_bericht` (`ordner()`, `dateiname`, `uid8`, `sicherer_pfad`, `datei_entfernen`, `CSS`, `_zeit`), `bildschirm.bilder`, `bildschirm.bild_daten`, `ollama.chat(..., als_json=True)`, `ui_termin._e`.
- Produces:
  - `KURS_SYSTEM: str` – Regeln: Lernende direkt ansprechen (Du), kein Fachjargon, je Bild zusammenfassen, was gesprochen wurde, während es zu sehen war; `schritte` nur bei Vorgeführtem; `offen` = Fragen der Lernenden, Hänger, Nacharbeit; Abschnittstitel sprechend; nur `bild_id`s aus der Eingabe; Antwort exakt im JSON der Spec (Ziel 1).
  - `kurs_eingabe(uid: str) -> dict` – Titel, Datum, Segmente (Zeit, Sprecher, Text), Bilder `[{"bild_id", "von", "bis", "beschreibung"}]`.
  - `pruefen(roh: object, bild_ids: set[str]) -> dict` – wirft `ValueError`, wenn `abschnitte` fehlt/leer oder kein Abschnitt einen Titel hat; verwirft unbekannte `bild_id`s; kürzt auf `MAX_BILDER_ABSCHNITT` je Abschnitt (gleichmäßig); erzwingt Listen/Strings.
  - `erzeugen(uid: str, jetzt: datetime) -> dict` – KI-Aufruf + `pruefen`, speichert `kurs_json`, `kurs_stand`, `kurs_am`, `kurs_versuche = 0`; bei Fehler `kurs_versuche + 1`, `kurs_am = jetzt`, nach `MAX_VERSUCHE` `kurs_status = 'fehler'`, Ausnahme weiterreichen.
  - `kurs_html(uid: str, fassung: str) -> str` – `fassung in ("felix", "lernend")`, sonst `ValueError`.
  - `ablegen(uid: str) -> str` – schreibt `<Rubrik>/<dateiname ohne .html>_kurs-intern.html`, `..._kurs.html`, `..._kurs.pdf` (PDF aus der Lernenden-Fassung), dann DB (`kurs_pfad`, `kurs_pfad_lernend`, `kurs_pdf`, `kurs_status = 'fertig'`); entfernt Dateien eines früheren Stands/Ordners; Rückgabe `kurs_status`.
  - `entfernen_dateien(uid: str) -> None` – löscht die drei Dateien, leert `kurs_pfad*`, `kurs_pdf`, `kurs_json`, `kurs_stand`, `kurs_status`.

- [ ] **Step 1: Failing tests** (KI per `monkeypatch.setattr(ollama, "chat", ...)`, sales-auge per Fake aus Task 2)
```python
def test_erzeugen_speichert_json_und_stand(kurs_mitschrift, ki_liefert_gutes_json):
    j = km.erzeugen(uid, JETZT); assert j["abschnitte"][0]["titel"] and _zeile(uid)["kurs_stand"] == km.kurs_stand(uid)
def test_kaputtes_json_zaehlt_versuch(kurs_mitschrift, ki_liefert_text):
    with pytest.raises(ValueError): km.erzeugen(uid, JETZT)
    assert _zeile(uid)["kurs_versuche"] == 1
def test_nach_drei_versuchen_fehler(...): assert _zeile(uid)["kurs_status"] == "fehler"
def test_unbekannte_bild_id_wird_verworfen():
    j = km.pruefen({"ueberblick": "x", "abschnitte": [{"titel": "A", "bilder": [{"bild_id": "fremd"}], "merken": []}], "offen": []}, {"b1"})
    assert j["abschnitte"][0]["bilder"] == []
def test_hoechstens_sechs_bilder_je_abschnitt(): ...
def test_lernenden_fassung_ohne_offen_und_transkript(kurs_fertig):
    h = km.kurs_html(uid, "lernend"); assert "Offen" not in h and "Transkript" not in h and "Intern" not in h and "Merken" in h
def test_felix_fassung_mit_offen_und_intern(kurs_fertig):
    h = km.kurs_html(uid, "felix"); assert "Offen / nachfragen" in h and "Intern" in h
def test_ablegen_legt_drei_dateien(kurs_fertig, ablage, auge_liefert_pdf):
    assert km.ablegen(uid) == "fertig"; z = _zeile(uid)
    assert z["kurs_pfad"].endswith("_kurs-intern.html") and z["kurs_pfad_lernend"].endswith("_kurs.html") and z["kurs_pdf"].endswith("_kurs.pdf")
    assert all((ablage / z[k]).exists() for k in ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf"))
def test_ablegen_pdf_fehler_laesst_keine_halben_dateien(kurs_fertig, ablage, auge_antwortet_503): ...
def test_keine_drafts(kurs_fertig, ...): assert not server._q("select 1 from drafts")   # gegen leere Test-DB-Tabelle vor/nach vergleichen
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_mitschrift.py`
- [ ] **Step 3: Implementieren** (HTML im Stil von `mitschrift_bericht.CSS`: Kopf, Inhaltsverzeichnis mit Ankern, Überblick, je Abschnitt Bild + „Zu sehen“ + „Erklärt“ + `<ol>` + Kasten „Merken“; alles escapen).
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** – `feat(kurs): Kursmitschrift aus KI-Gliederung, zwei Fassungen, PDF`

---

### Task 4: Kurs-Handbuch – Zuordnen, Fortschreiben, Ausgabe (B1)

**Files:**
- Create: `sales-mcp/kurs_handbuch.py`
- Test: `sales-mcp/tests/test_kurs_handbuch.py`

**Interfaces:**
- Consumes: Task 1 (Tabellen, `kurs_lead_id`), Task 2 (`kurs_pdf`), Task 3 (`kurs_json`).
- Produces:
  - `MAX_BILDER_KAPITEL = 3`; `ORDNER_NAME = "_handbuecher"`
  - `ZUORDNUNG_SYSTEM`, `KAPITEL_SYSTEM: str`. Zuordnung: Eingabe = Kapitel des Lernenden `[{"kapitel_id", "titel", "kurz": erste 400 Zeichen, "juengste_quelle": Datum}]` + Abschnitte der Sitzung mit Datum; Antwort `{"zuordnung": [{"abschnitt": int, "entscheidung": "ergaenzen"|"neu"|"ersetzen", "kapitel_id": str|null, "titel": str|null}]}`. Fortschreiben: Eingabe = alter Kapiteltext + neue Abschnitte + Entscheidung; Antwort `{"text_md": str, "bild_ids": [str]}`; unveränderte Teile wortgleich.
  - `zuordnen(lead_id: str, uid: str) -> dict` – ein KI-Auftrag; prüft: `kapitel_id` gehört zu `lead_id` (sonst `ValueError`, nichts gespeichert), Indizes gültig, `ersetzen` von einer Sitzung, die nicht jünger ist als alle Quellen des Kapitels → `ergaenzen`; speichert `kurs_handbuch_quelle` (`stand` = `kurs_stand`, `eingearbeitet_am = null`).
  - `offene_auftraege(lead_id: str) -> list[tuple[str, str]]` – `(uid, ziel)` mit `ziel` = `kapitel_id` oder `"neu:<abschnitt>"`, für zugeordnete, nicht eingearbeitete Quellen, in Datumsfolge.
  - `fortschreiben(lead_id: str, uid: str, ziel: str) -> str` – ein KI-Auftrag; neue `kurs_handbuch_fassung` (`quellen` = alte ∪ {uid}, `bild_ids` ≤ 3 jüngste geprüfte), `aktuelle_fassung` setzen; neues Kapitel `reihenfolge = max + 1`; Quelle `eingearbeitet_am`, sobald alle ihre Ziele erledigt. Rückgabe `kapitel_id`.
  - `handbuch_html(lead_id: str) -> str` – Inhaltsverzeichnis, Kapitel nach `reihenfolge`, „aus Sitzung(en) vom …“, Kopf „Stand: <Datum>, <n> Sitzungen“; kein „Offen“.
  - `ausgeben(lead_id: str) -> None` – `_handbuecher/handbuch-<lead8>.html` und `.pdf` schreiben (atomar), `kurs_handbuch` upsert (`pfad`, `pdf`, `stand_am`, `fassungen_stand` = jüngste Fassung); ohne Kapitel: Dateien und Zeile entfernen.
  - `ausgabe_faellig(lead_id: str) -> bool` – keine offenen Aufträge und `fassungen_stand` ≠ jüngste Fassung (oder Kapitel umbenannt/umsortiert, s. Task 7).

- [ ] **Step 1: Failing tests**
```python
def test_erste_sitzung_legt_kapitel_an(lernender, sitzung1, ki_zuordnung_alle_neu, ki_kapitel):
    kh.zuordnen(lernender, sitzung1)
    for uid, ziel in kh.offene_auftraege(lernender): kh.fortschreiben(lernender, uid, ziel)
    assert _kapitel_titel(lernender) == ["Termin anlegen", "Kontakt suchen"] and not kh.offene_auftraege(lernender)
def test_ergaenzen_aendert_nur_betroffenes_kapitel(handbuch_nach_sitzung1, sitzung2, ki_ergaenzt_kapitel_1):
    ...; assert _texte(lernender)["Kontakt suchen"] == vorher["Kontakt suchen"] and len(_fassungen("Termin anlegen")) == 2
def test_kapitel_eines_anderen_lernenden_wird_abgewiesen(zwei_lernende, ki_zuordnung_fremdes_kapitel):
    with pytest.raises(ValueError): kh.zuordnen(lernender_a, sitzung_a)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender_a,))
def test_ersetzen_durch_aeltere_sitzung_wird_ergaenzen(...): ...
def test_hoechstens_drei_bilder_je_kapitel(...): assert len(_aktuell("Termin anlegen")["bild_ids"]) <= 3
def test_handbuch_html_ohne_offen_mit_quellen(handbuch_nach_sitzung1):
    h = kh.handbuch_html(lernender); assert "aus Sitzung" in h and "Offen" not in h and "Stand:" in h
def test_ausgeben_schreibt_html_und_pdf(handbuch_nach_sitzung1, ablage, auge_liefert_pdf):
    kh.ausgeben(lernender); z = server._q("select * from kurs_handbuch where lead_id = %s", (lernender,))[0]
    assert (ablage / z["pfad"]).exists() and (ablage / z["pdf"]).exists() and not kh.ausgabe_faellig(lernender)
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_handbuch.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** – `feat(kurs): Kurs-Handbuch mit Kapiteln und Fassungen (B1)`

---

### Task 5: Quelle entfernen, Reihenfolge, Löschen, Verschieben, Lernenden-Wechsel

**Files:**
- Modify: `sales-mcp/kurs_handbuch.py`, `sales-mcp/kurs_mitschrift.py`
- Modify: `sales-mcp/termin_akte.py` (`mitschrift_entfernen` ~Z. 445), `sales-mcp/server.py` (`_mitschriften_abraeumen` ~Z. 8885), `sales-mcp/mitschrift_bericht.py` (`verschieben` ~Z. 273, `abgleichen` ~Z. 311)
- Test: `sales-mcp/tests/test_kurs_quelle.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `kurs_handbuch.quelle_entfernen(lead_id: str, uid: str) -> int` – jedes Kapitel mit einer Fassung, die `uid` in `quellen` trägt, auf die jüngste Fassung **ohne** `uid` zurücksetzen (gibt es keine, Kapitel löschen); alle Fassungen mit `uid` löschen; `kurs_handbuch_quelle`-Zeile löschen; bei jüngeren Quellen dieser Kapitel deren Fassungen ebenfalls zurückrollen und `eingearbeitet_am = null` (gespeicherte `zuordnung` bleibt; nicht mehr existierende `kapitel_id` → `neu`). Rückgabe: Anzahl betroffener Kapitel.
  - `kurs_handbuch.einfuegen_vorbereiten(lead_id: str, uid: str, beginn: datetime) -> None` – sind jüngere Quellen schon eingearbeitet, diese wie oben zurückrollen, damit `uid` an ihrer Datumsstelle eingearbeitet wird.
  - `kurs_handbuch.alles_entfernen(lead_id: str) -> None` – Handbuch-Dateien löschen, Kapitel/Fassungen/Quellen/`kurs_handbuch` des Leads löschen.
  - `kurs_mitschrift.entfernen(uid: str) -> None` – `entfernen_dateien(uid)` + für den Lernenden mit Quelle `uid`: `quelle_entfernen` (das Handbuch wird danach vom Takt neu ausgegeben).
  - `lernender_setzen` (Task 1) ruft bei Wechsel `quelle_entfernen(alter_lead, uid)`.
  - `mitschrift_entfernen` und `_mitschriften_abraeumen` rufen **vor** dem Löschen der Zeile `kurs_mitschrift.entfernen(uid)`; `_mitschriften_abraeumen` ruft zusätzlich `kurs_handbuch.alles_entfernen(lead_id)` (Löschantrag des Lernenden).
  - `verschieben`: Wechsel **aus** „Kurse“ → `kurs_mitschrift.entfernen(uid)`.
  - `abgleichen`: `*_kurs.html`, `*_kurs-intern.html`, `*_kurs.pdf` gelten als gebucht, wenn ihr Pfad in `kurs_pfad`/`kurs_pfad_lernend`/`kurs_pdf` steht; `_handbuecher/` nur über `kurs_handbuch.pfad/pdf`; Waisen nach Schonfrist löschen. `_handbuecher` ist kein Rubrik-Ordner (darf nicht als Rubrik erscheinen oder geleert werden, solange gebucht).

- [ ] **Step 1: Failing tests**
```python
def test_quelle_entfernen_setzt_kapitel_zurueck(handbuch_1_und_2):
    kh.quelle_entfernen(lernender, sitzung2)
    assert _aktuell("Termin anlegen")["quellen"] == [sitzung1]
    assert not server._q("select 1 from kurs_handbuch_fassung where %s = any(quellen)", (sitzung2,))
def test_kapitel_nur_aus_entfernter_quelle_verschwindet(...): ...
def test_juengere_quellen_werden_neu_eingearbeitet(handbuch_1_2_3):
    kh.quelle_entfernen(lernender, sitzung2); assert sitzung3 in [u for u, _ in kh.offene_auftraege(lernender)]
def test_aeltere_sitzung_wird_an_datumsstelle_eingefuegt(handbuch_nach_sitzung2, sitzung1_spaet):
    kh.einfuegen_vorbereiten(lernender, sitzung1, beginn_1)
    kh.zuordnen(lernender, sitzung1)                       # (KI-Fake)
    assert [u for u, _ in kh.offene_auftraege(lernender)][0] == sitzung1
def test_lernenden_wechsel_verschiebt_quelle(handbuch_a_mit_sitzung1, lead_b):
    km.lernender_setzen(sitzung1, lead_b)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lead_a,))
def test_loeschen_raeumt_dateien_und_fassungen(kurs_fertig_im_handbuch, ablage):
    termin_akte.mitschrift_entfernen(uid)
    assert not any(ablage.rglob("*_kurs*")) and not server._q("select 1 from kurs_handbuch_fassung where %s = any(quellen)", (uid,))
def test_verschieben_aus_kurse_raeumt_auf(kurs_fertig): mb.verschieben(uid, "Notizen"); assert _zeile(uid)["kurs_pfad"] is None
def test_lead_loeschantrag_entfernt_handbuch(handbuch_ausgegeben, ablage):
    server._mitschriften_abraeumen(lernender)
    assert not (ablage / "_handbuecher").exists() or not any((ablage / "_handbuecher").iterdir())
def test_abgleich_laesst_gebuchte_kursdateien_und_handbuch_stehen(...): ...
def test_abgleich_loescht_verwaiste_kursdatei_nach_schonfrist(...): ...
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_quelle.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu Regression `vm_test.sh tests/test_mitschrift_bericht.py tests/test_termin_takt.py tests/test_ui_mitschriften.py`
- [ ] **Step 5: Commit** – `feat(kurs): Quelle entfernen, Reihenfolge, Loeschen, Verschieben, Lernenden-Wechsel`

---

### Task 6: Taktgeber-Schritt `kurs` und Bestand

**Files:**
- Modify: `sales-mcp/termin_takt.py` (`SCHRITTE` ~Z. 671: `("kurs", _kurs)` nach `("ablage", _ablage)`)
- Test: `sales-mcp/tests/test_termin_takt_kurs.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `_kurs(jetzt: datetime) -> int` – je Runde, Ablage-Ordner nicht beschreibbar → 0 (wie `_ablage`):
  1. **Veraltet (ohne KI):** Kurs-Mitschriften mit `kurs_json is not null` und `kurs_stand` ≠ `KURS_STAND_SQL` → `kurs_mitschrift.entfernen(uid)` (läuft dann wie neu).
  2. **Höchstens ein KI-Auftrag, in dieser Priorität:** (a) Kursmitschrift für die älteste fällige Kurs-Mitschrift (`kurs_json is null`, `kurs_status` nicht `'fehler'`, Neuversuch fällig) → `erzeugen` und im selben Schritt `ablegen`; (b) sonst Zuordnung für die älteste (nach `termin_akten.beginn`) Mitschrift mit `kurs_status = 'fertig'`, gesetztem `kurs_lead_id` und ohne `kurs_handbuch_quelle` – vorher `einfuegen_vorbereiten`; (c) sonst ein `fortschreiben` aus `offene_auftraege` (älteste Quelle zuerst, über alle Lernenden). Fehler bei (b)/(c) → Pause je `(lead, uid)` für `NEUVERSUCH_NACH` (In-Memory wie `_bericht_pause`), nach 3 Fehlern `kurs_status = 'fehler'` an der Mitschrift.
  3. **Ausgabe (ohne KI):** jeder Lernende mit `kurs_handbuch.ausgabe_faellig` → `ausgeben` (höchstens einer je Runde).
  - Kein KI-Auftrag, wenn `_termin_steht_an(jetzt)` oder `not _ollama_da()`; Mitschriften mit `kurs_status = 'fehler'` überspringen. Log nur `uid8` und Zähler.

- [ ] **Step 1: Failing tests**
```python
def test_hoechstens_ein_ki_auftrag_je_runde(zwei_kurs_mitschriften, ki_zaehler):
    termin_takt._kurs(JETZT); assert ki_zaehler.n == 1
def test_kein_ki_wenn_termin_ansteht(...): assert ki_zaehler.n == 0
def test_ohne_lernenden_nur_kursmitschrift(kurs_mitschrift_ohne_lernenden, ki_fake, auge_fake):
    for _ in range(5): termin_takt._kurs(JETZT)
    assert _zeile(uid)["kurs_status"] == "fertig" and not server._q("select 1 from kurs_handbuch_quelle")
def test_bestand_zwei_sitzungen_ein_handbuch(diana_bestand_mit_lernender, ki_fake, auge_fake):
    for _ in range(30): termin_takt._kurs(JETZT)
    assert len(server._q("select 1 from kurs_handbuch where lead_id = %s", (diana,))) == 1
    assert _quellen_reihenfolge(diana) == [sitzung_14_11_frueh, sitzung_14_11_spaet]
def test_fehler_sitzung_wird_uebersprungen(...): ...
def test_neuauswertung_baut_neu(...): ...
def test_nicht_kurs_rubrik_wird_ignoriert(...): ...
def test_keine_drafts_im_ganzen_ablauf(...): assert not server._q("select 1 from drafts where body ilike '%Kurs%'")
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_termin_takt_kurs.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu `vm_test.sh tests/test_termin_takt.py`
- [ ] **Step 5: Commit** – `feat(kurs): Taktgeber-Schritt kurs`

---

### Task 7: Oberfläche – „Kurse“ und „Handbücher“

**Files:**
- Modify: `sales-mcp/ui_mitschriften.py`
- Test: `sales-mcp/tests/test_ui_kurs.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces (Routen, alle angemeldet, Antwortköpfe wie `/mitschriften/bericht`):
  - Liste `/mitschriften?rubrik=Kurse`: je Eintrag „Kursmitschrift (Felix)“ → `/mitschriften/kurs?uid=…&fassung=felix`, „Kursmitschrift PDF“ → `/mitschriften/kurs.pdf?uid=…` (`Content-Disposition: attachment; filename="Kursmitschrift_<JJJJ-MM-TT>.pdf"`), Lernenden-Feld (Auswahl aus `vorschlaege` + Suchfeld über Kontaktname, POST), Status-Text: „wird erzeugt“, „fertig“, „Fehler“, „Lernenden wählen“.
  - `GET /mitschriften/kurs?uid=&fassung=felix|lernend[&download=1]`.
  - `POST /mitschriften/kurs/lernender` (CSRF, `uid`, `lead_id` leer = entfernen) → `kurs_mitschrift.lernender_setzen`.
  - Reiter **„Handbücher“** `GET /mitschriften/handbuecher`: je Lernendem Name, Stand, Anzahl Sitzungen, „Handbuch öffnen“ (`/mitschriften/handbuch?lead=…`), „PDF herunterladen“ (`/mitschriften/handbuch.pdf?lead=…`, attachment `Kurs-Handbuch_<JJJJ-MM-TT>.pdf`), Kapitelliste (Titel, Quellen-Daten, Anzahl Fassungen).
  - `POST /mitschriften/handbuch/kapitel` (CSRF): `aktion=umbenennen` (`kapitel_id`, `titel` 1–80 Zeichen) | `hoch` | `runter`; Kapitel muss zu `lead` gehören; danach gilt die Ausgabe als fällig (Task 4 `ausgabe_faellig` berücksichtigt das, z. B. über `kurs_handbuch.fassungen_stand = null`).
  - `POST /mitschriften/handbuch/ausgeben` (CSRF, `lead`) → `kurs_handbuch.ausgeben(lead)`.
  - Schreibende Routen nicht für Rollen `lesen`/`kalender`.

- [ ] **Step 1: Failing tests**
```python
def test_kurse_reiter_zeigt_kurslinks_und_status(client_angemeldet, kurs_fertig):
    r = client.get("/mitschriften?rubrik=Kurse"); assert "Kursmitschrift (Felix)" in r.text and "Lernenden wählen" in r.text
def test_kurs_html_ohne_anmeldung_umleitung(client): assert client.get("/mitschriften/kurs?uid=x&fassung=felix").status_code in (302, 303)
def test_kurs_kopfzeilen(client_angemeldet, kurs_fertig):
    r = client.get(f"/mitschriften/kurs?uid={uid}&fassung=lernend")
    assert r.headers["cache-control"] == "private, no-store" and "script-src 'none'" in r.headers["content-security-policy"]
def test_kurs_pdf_download(client_angemeldet, kurs_fertig):
    r = client.get(f"/mitschriften/kurs.pdf?uid={uid}"); assert r.headers["content-type"] == "application/pdf" and "attachment" in r.headers["content-disposition"]
def test_unbekannte_fassung_404(...): ...
def test_lernender_setzen_braucht_csrf(...): assert r.status_code == 403
def test_lernender_setzen_privater_kontakt(...): assert _zeile(uid)["kurs_lead_id"] == privat_lead
def test_handbuecher_liste_und_pdf(...): ...
def test_kapitel_eines_anderen_leads_nicht_aenderbar(...): ...
def test_rolle_lesen_darf_nicht_umbenennen(...): ...
def test_keine_versand_knoepfe(client_angemeldet, kurs_fertig): assert "Freigabe" not in client.get("/mitschriften?rubrik=Kurse").text
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_ui_kurs.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu `vm_test.sh tests/test_ui_mitschriften.py`
- [ ] **Step 5: Commit** – `feat(kurs): Oberflaeche Kurse und Handbuecher`

---

### Task 8: Doku und Gesamtlauf

**Files:**
- Modify: `docs/RUNBOOK.md`, `docs/DSGVO.md`, `docs/BEDIENUNG.md` (Builder findet die Abschnitte per `grep -rln "Mitschriften" docs/`)

- [ ] **Step 1:** RUNBOOK: Schritt `kurs`, `POST /pdf` in sales-auge, `AUGE_URL` in sales-termine, Status-Werte, Lernenden wählen.
- [ ] **Step 2:** DSGVO: Kursmitschrift/Handbuch enthalten gesprochene Inhalte ohne Maskierung (Felix-Entscheid A); kein Versand durch sales-claw; Löschwege (Mitschrift, Lead, Verschieben, Lernenden-Wechsel); Kapitelfassungen.
- [ ] **Step 3:** BEDIENUNG: Reiter „Kurse“ (Lernenden wählen, PDF herunterladen), „Handbücher“.
- [ ] **Step 4:** Gesamtlauf: `vm_test.sh tests/test_kurs_*.py tests/test_termin_takt*.py tests/test_ui_mitschriften.py tests/test_ui_kurs.py tests/test_mitschrift_*.py tests/test_auge_pdf.py`, `bash deploy/tests/test_auge_compose.sh`, `bash deploy/tests/test_mitschriften_ordner.sh` → alle grün.
- [ ] **Step 5: Commit** – `docs(kurs): Runbook, DSGVO, Bedienung`

## Ausrollen (nach Merge, nur mit Felix' OK)

1. Claim in `00_Meta/002_Koordination_Live.md` setzen und committen.
2. Sicherung `sales`.
3. `provision.sql` einspielen (alle Laden-Schemata).
4. `update.sh` (baut u. a. sales-auge, sales-termine, sales-ui neu; startet weitere Container neu, inkl. openwa – Sitzung danach prüfen).
5. Takt beobachten: Kursmitschriften für die Kurs-Termine; Felix wählt Diana als Lernende → Handbuch entsteht.
6. Felix lädt Kursmitschrift- und Handbuch-PDF herunter und verschickt selbst.
