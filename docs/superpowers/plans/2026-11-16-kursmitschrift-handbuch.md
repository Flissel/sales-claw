# Kursmitschrift und Kurs-Handbuch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aus Mitschriften der Rubrik „Kurse“ entstehen eine Kursmitschrift je Termin (Felix- und Diana-Fassung, Diana-PDF) und ein mitwachsendes Kurs-Handbuch je Lernendem; beides geht nur nach Felix' Freigabe per Mail mit PDF an den Lernenden.

**Architecture:** Neuer Taktgeber-Schritt `kurs` (nach `ablage`) mit höchstens einem KI-Auftrag je Runde. `kurs_mitschrift.py` erzeugt die Kursmitschrift (KI-JSON → HTML), `kurs_handbuch.py` pflegt Kapitel mit Fassungen (B1: zuordnen, betroffene Kapitel fortschreiben, Quelle zurückrollen + neu einarbeiten), `kurs_pdf.py` lässt HTML von sales-auge (Chromium, neuer Endpunkt `POST /pdf`) zu PDF machen und legt es im Ordner für erzeugte Unterlagen ab, `kurs_versand.py` legt Entwürfe über `server.entwurf_erstellen` an. sales-ui zeigt alles unter „Mitschriften → Kurse“ und „Handbücher“.

**Tech Stack:** Python 3 (sales-mcp), Postgres (Supabase, Schema je Laden), Starlette (sales-ui), Playwright/Chromium (sales-auge), Docker Compose, pytest gegen Test-DB.

**Spec:** `docs/superpowers/specs/2026-11-16-kursmitschrift-handbuch-design.md` (baut auf `2026-11-14-mitschriften-ablage-design.md`).

## Global Constraints

- Auslöser: `termin_mitschriften.rubrik` = „Kurse“ (Vergleich ohne Groß/Klein), `auswertung_status = 'fertig'`, `bericht_pfad is not null`.
- KI nur über `ollama.chat` (sales-ki), kein neues Modell, kein API-Budget. Je Taktrunde höchstens **ein** KI-Auftrag im Schritt `kurs`; keiner, wenn `termin_takt._termin_steht_an(jetzt)` oder `not termin_takt._ollama_da()`.
- Fehler: bis zu 3 Versuche (`MAX_VERSUCHE = 3`) im Abstand `NEUVERSUCH_NACH = timedelta(hours=1)`, danach `kurs_status = 'fehler'`.
- Bilder nur aus `bildschirm.bilder(uid)` (geprüft, nicht heikel); höchstens 6 je Abschnitt (Kursmitschrift), höchstens 3 je Kapitel (Handbuch, die jüngsten); im PDF/HTML höchstens 800 px lange Kante, JPEG q60.
- Diana-Fassung und Handbuch: **kein** Rohtranskript, **kein** Teil „Offen“, keine internen Auswertungsteile. Felix-Fassung = Diana-Fassung + „Offen / nachfragen“ + Kennzeichnung „Intern – enthält Kundendaten, nicht weitergeben“.
- Kein Maskieren von Text (Felix: Variante A) – Schutz ist die Freigabe.
- Versand nur über Entwürfe (`drafts`, Status `pending`) mit PDF-Anhang; PDF höchstens `mail_dispatch.ANHANG_MAX_BYTES` (8 MB), sonst kein Entwurf und Status-Hinweis „PDF zu groß“.
- Lernender: Teilnehmer mit `rolle <> 'organisator'`, deren `lead_id` gesetzt ist oder deren Adresse (lower) genau einem `leads.email` (lower) entspricht.
- Logs nur Anzahlen, Typnamen, uid8 – keine Titel, Namen, Adressen, Texte.
- Auslieferung in sales-ui: nur angemeldet, `Cache-Control: private, no-store`, CSP ohne Skripte, Pfade nur aus der DB und nur unter dem jeweiligen Ordner (wie `ui_mitschriften`).
- Neue `.py`-Dateien CRLF, `.sh` LF (wie bisher im Repo). Commits: Conventional Commits, Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests laufen auf der VM gegen `meeting_test`/`sales_test`: `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh [--provision] tests/<datei>.py` (Prod `~/sales-claw` nie anfassen).

## Review Focus

1. **Alte Sitzung kommt nachträglich nach „Kurse“** (Verschieben eines älteren Termins): Kapitel müssen auf den Stand vor ihrem Datum zurück und spätere Sitzungen neu eingearbeitet werden, nicht hinten angehängt. Test in Task 5 (`test_aeltere_sitzung_wird_an_datumsstelle_eingefuegt`).
2. **KI liefert kaputtes oder halbes JSON** (fehlende `abschnitte`, unbekannte `bild_id`, `kapitel` verweist auf fremdes Kapitel eines anderen Lernenden): kein Absturz, Versuch zählt, nichts Fremdes wird geschrieben. Tests in Task 3 (`test_kaputtes_json_zaehlt_versuch`, `test_unbekannte_bild_id_wird_verworfen`) und Task 4 (`test_kapitel_eines_anderen_lernenden_wird_abgewiesen`).
3. **Entwurf schon freigegeben oder versendet, dann Neu-Auswertung**: alter Entwurf bleibt unangetastet, neuer entsteht. Test in Task 6 (`test_freigegebener_entwurf_bleibt_bei_neuauswertung`).
4. **Mitschrift wird gelöscht, während ihr Kursmitschrift-Entwurf `pending` ist**: Entwurf wird abgelehnt, PDF und HTML weg, Kapitelfassungen mit ihrem Inhalt gelöscht. Test in Task 5 (`test_loeschen_raeumt_entwurf_pdf_und_fassungen`).
5. **Lernender nicht eindeutig** (Adresse passt zu zwei Leads, oder nur Organisator im Termin): Kursmitschrift entsteht, kein Handbuch, kein Entwurf, UI-Hinweis. Test in Task 1 (`test_adresse_mit_zwei_leads_ist_kein_lernender`).

---

### Task 1: Schema, Lernende, Kurs-Stand

**Files:**
- Modify: `db/provision.sql` (bei den `termin_mitschriften`-Ergänzungen ~Z. 373–380, alle Laden-Schemata wie dort)
- Create: `sales-mcp/kurs_mitschrift.py` (nur Konstanten + Lernende + Stand in diesem Task)
- Test: `sales-mcp/tests/test_kurs_schema.py`, `sales-mcp/tests/test_kurs_lernende.py`

**Interfaces:**
- Produces (Schema):
  - `termin_mitschriften` + `kurs_json jsonb`, `kurs_stand text`, `kurs_status text` (null | `'fertig'` | `'fehler'` | `'pdf_zu_gross'`), `kurs_am timestamptz`, `kurs_versuche integer not null default 0`, `kurs_pfad text` (Felix-HTML, relativ zu `MITSCHRIFTEN_ORDNER`), `kurs_pfad_diana text`, `kurs_pdf text` (Dateiname in `MEDIEN_ERZEUGT_ORDNER`).
  - `kurs_handbuch_kapitel(id uuid pk default gen_random_uuid(), lead_id uuid not null references leads(id) on delete cascade, titel text not null, reihenfolge integer not null, aktuelle_fassung uuid, erstellt_am timestamptz default now())`
  - `kurs_handbuch_fassung(id uuid pk, kapitel_id uuid not null references kurs_handbuch_kapitel(id) on delete cascade, text_md text not null, bild_ids text[] not null default '{}', quellen text[] not null, erstellt_am timestamptz default now())`
  - `kurs_handbuch_quelle(lead_id uuid references leads(id) on delete cascade, uid text not null, beginn timestamptz not null, stand text not null, zuordnung jsonb not null, eingearbeitet_am timestamptz, primary key (lead_id, uid))` – die gespeicherte Zuordnung je Sitzung.
  - `kurs_handbuch(lead_id uuid pk references leads(id) on delete cascade, pfad text, pdf text, stand_am timestamptz, status text)`
  - `kurs_entwuerfe(draft_id uuid pk, art text not null check (art in ('kursmitschrift','handbuch')), uid text, lead_id uuid not null, erstellt_am timestamptz default now())`
- Produces (Python, `kurs_mitschrift.py`):
  - `RUBRIK_KURSE = "Kurse"`, `MAX_VERSUCHE = 3`, `NEUVERSUCH_NACH = timedelta(hours=1)`, `MAX_BILDER_ABSCHNITT = 6`, `BILD_KANTE = 800`, `BILD_QUALITAET = 60`
  - `ist_kurs(rubrik: str | None) -> bool`
  - `lernende(uid: str) -> list[dict]` → `[{"lead_id": str, "adresse": str, "name": str}]`, eindeutig je lead_id
  - `KURS_STAND_SQL: str` – SQL-Ausdruck über Alias `m` wie `mitschrift_bericht.STAND_SQL`, zusätzlich mit `m.rubrik`; `kurs_stand(uid: str) -> str | None`

- [ ] **Step 1: Failing tests schreiben**

```python
# test_kurs_schema.py
def test_spalten_und_tabellen_da():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns where table_schema = current_schema() "
        "and table_name = 'termin_mitschriften'")}
    assert {"kurs_json", "kurs_stand", "kurs_status", "kurs_am", "kurs_versuche",
            "kurs_pfad", "kurs_pfad_diana", "kurs_pdf"} <= spalten
    for t in ("kurs_handbuch_kapitel", "kurs_handbuch_fassung", "kurs_handbuch_quelle",
              "kurs_handbuch", "kurs_entwuerfe"):
        assert server._q("select to_regclass(%s) is not null as da", (t,))[0]["da"]

def test_lead_loeschen_kaskadiert_handbuch(lead_mit_kapitel):
    server._q("delete from leads where id = %s", (lead_mit_kapitel,))
    assert not server._q("select 1 from kurs_handbuch_kapitel where lead_id = %s", (lead_mit_kapitel,))

# test_kurs_lernende.py
def test_lead_id_am_teilnehmer(akte_mit_gast):          # gast mit lead_id
    assert [l["lead_id"] for l in km.lernende(akte_mit_gast.uid)] == [akte_mit_gast.lead_id]
def test_adresse_ohne_lead_id_findet_lead(akte_gast_nur_adresse):   # Diana-Fall
    assert len(km.lernende(akte_gast_nur_adresse.uid)) == 1
def test_organisator_ist_kein_lernender(akte_nur_organisator):
    assert km.lernende(akte_nur_organisator.uid) == []
def test_adresse_mit_zwei_leads_ist_kein_lernender(akte_adresse_zwei_leads):
    assert km.lernende(akte_adresse_zwei_leads.uid) == []
def test_ist_kurs():
    assert km.ist_kurs("kurse") and km.ist_kurs("Kurse") and not km.ist_kurs("Kundentermine") and not km.ist_kurs(None)
def test_kurs_stand_aendert_sich_mit_rubrik_und_auswertung(mitschrift_kurs): ...
```
Fixtures nach dem Muster von `tests/test_mitschrift_bericht.py` (Akte, Mitschrift, Teilnehmer, Leads direkt per SQL).

- [ ] **Step 2: Laufen lassen, FAIL erwarten** – `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh tests/test_kurs_schema.py tests/test_kurs_lernende.py` → Fehler wegen fehlender Spalten/Modul.
- [ ] **Step 3: `provision.sql` ergänzen** (idempotent, `add column if not exists` / `create table if not exists`, Schleife über alle Laden-Schemata wie bestehende Blöcke) **und `kurs_mitschrift.py`** mit obigen Konstanten und Funktionen.
- [ ] **Step 4: PASS** – derselbe Befehl mit `--provision`.
- [ ] **Step 5: Commit** – `feat(kurs): Schema und Lernende fuer Kursmitschrift`

---

### Task 2: PDF über sales-auge und Ablage im Ordner für erzeugte Unterlagen

**Files:**
- Modify: `sales-mcp/auge.py` (`http_dienst`: neuer `POST /pdf`; Ausführung im Hauptthread über eine Warteschlange, weil die Playwright-Sync-API an den Thread des Browsers gebunden ist; `main()`-Schleife arbeitet die Warteschlange zwischen den Takt-Schritten ab)
- Create: `sales-mcp/kurs_pdf.py`
- Modify: `docker-compose.yml` (`sales-termine`: `AUGE_URL: http://${LADEN_PRAEFIX:-sales}-auge:8790` und Mount `${MEDIEN_ERZEUGT_ORDNER:-./media-erzeugt}:/media-erzeugt` **rw**; Kommentar warum)
- Modify: `sales-mcp/tests/test_kanal_deploy.py` bzw. der Test, der festhält, welche Dienste `/media-erzeugt` rw haben (Builder sucht per `grep -rn "media-erzeugt" sales-mcp/tests deploy/tests`)
- Test: `sales-mcp/tests/test_kurs_pdf.py`, `sales-mcp/tests/test_auge_pdf.py`

**Interfaces:**
- Produces:
  - sales-auge `POST /pdf` – Body `text/html; charset=utf-8` (höchstens 20 MB), Antwort `200 application/pdf` (A4, `print_background=True`, Ränder 15 mm) oder `413`/`503` (Browser weg)/`504` (Zeitlimit 60 s); nur im Compose-Netz.
  - `kurs_pdf.pdf_aus_html(html: str, zeitlimit_s: float = 90) -> bytes` – wirft `kurs_pdf.PdfFehler` bei jedem Nicht-200.
  - `kurs_pdf.ablegen(name: str, html: str) -> int` – schreibt `medien.erzeugt_wurzel()/name` atomar (tmp + `os.replace`), gibt Bytezahl zurück; `name` muss `^(kurs|handbuch)-[0-9a-f-]{8,}[0-9a-z-]*\.pdf$` erfüllen, sonst `ValueError`.
  - `kurs_pdf.entfernen(name: str | None) -> None` – löscht nur Namen nach obigem Muster in `erzeugt_wurzel()`.
  - `kurs_pdf.zu_gross(n: int) -> bool` – `n > mail_dispatch.ANHANG_MAX_BYTES`.

- [ ] **Step 1: Failing tests**
```python
# test_kurs_pdf.py (sales-auge per monkeypatch auf urllib-Ebene ersetzt)
def test_ablegen_schreibt_atomar(erzeugt_ordner, auge_liefert_pdf):
    n = kp.ablegen("kurs-3c9afada.pdf", "<html><body>x</body></html>")
    assert n > 0 and (erzeugt_ordner / "kurs-3c9afada.pdf").read_bytes().startswith(b"%PDF")
    assert not list(erzeugt_ordner.glob("*.tmp"))
def test_name_ausserhalb_muster_abgelehnt(erzeugt_ordner):
    with pytest.raises(ValueError): kp.ablegen("../x.pdf", "<p>")
    with pytest.raises(ValueError): kp.ablegen("muster-a-f1-r1.pdf", "<p>")
def test_auge_fehler_wird_pdffehler(auge_antwortet_503):
    with pytest.raises(kp.PdfFehler): kp.pdf_aus_html("<p>")
def test_zu_gross_grenze():
    assert not kp.zu_gross(8 * 1024 * 1024) and kp.zu_gross(8 * 1024 * 1024 + 1)
def test_abgelegtes_pdf_besteht_pruefe_anhang(erzeugt_ordner, auge_liefert_pdf):
    kp.ablegen("handbuch-ef0207e8-20261116.pdf", "<p>x</p>")
    assert medien.pruefe_anhang("handbuch-ef0207e8-20261116.pdf")[1] is None
# test_auge_pdf.py: Warteschlangen-Logik ohne Browser (Fake-Seite mit .pdf()) –
#   Auftrag wird im Hauptthread erledigt, Antwort 200 + Bytes; ohne Browser 503; Zeitlimit 504.
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_pdf.py tests/test_auge_pdf.py`
- [ ] **Step 3: Implementieren** (auge: `page = browser.new_page(); page.set_content(html, wait_until="load"); page.pdf(format="A4", print_background=True, margin=...)`, Seite immer schließen; JavaScript in der Seite deaktiviert – `browser.new_context(java_script_enabled=False)`).
- [ ] **Step 4: PASS**, dazu `bash deploy/tests/test_auge_compose.sh` und den Compose-Vertragstest.
- [ ] **Step 5: Commit** – `feat(kurs): PDF ueber sales-auge, Ablage in media-erzeugt`

---

### Task 3: Kursmitschrift erzeugen (A)

**Files:**
- Modify: `sales-mcp/kurs_mitschrift.py`
- Test: `sales-mcp/tests/test_kurs_mitschrift.py`

**Interfaces:**
- Consumes: Task 1 (`lernende`, `kurs_stand`, Konstanten), Task 2 (`kurs_pdf.ablegen/entfernen/zu_gross/PdfFehler`), `mitschrift_bericht` (`ordner()`, `dateiname`, `uid8`, `sicherer_pfad`, `datei_entfernen`, `CSS`, `_zeit`), `bildschirm.bilder`, `bildschirm.bild_daten`, `ollama.chat(..., als_json=True)`.
- Produces:
  - `KURS_SYSTEM: str` (Prompt) – Regeln: Diana direkt ansprechen (Du), kein Fachjargon, je Bild zusammenfassen, was gesprochen wurde, während es zu sehen war; `schritte` nur bei Vorgeführtem; `offen` = Fragen der Lernenden, Hänger, Nacharbeit; Abschnittstitel sprechend; nur `bild_id`s aus der Eingabe; Antwort exakt im JSON der Spec (Ziel 1).
  - `kurs_eingabe(uid: str) -> dict` – Titel, Datum, Segmente (Zeit, Sprecher, Text), Bilder `[{"bild_id", "von", "bis", "beschreibung"}]`.
  - `pruefen(roh: object, bild_ids: set[str]) -> dict` – normalisiert die KI-Antwort: wirft `ValueError`, wenn `abschnitte` fehlt/leer oder kein Abschnitt einen Titel hat; verwirft unbekannte `bild_id`s; kürzt auf `MAX_BILDER_ABSCHNITT` je Abschnitt (gleichmäßig); erzwingt Listen/Strings.
  - `erzeugen(uid: str) -> dict` – KI-Aufruf + `pruefen`, speichert `kurs_json`, `kurs_stand`, `kurs_am`; bei Fehler `kurs_versuche + 1`, nach `MAX_VERSUCHE` `kurs_status = 'fehler'`; Rückgabe das geprüfte JSON.
  - `kurs_html(uid: str, fassung: str) -> str` – `fassung in ("felix", "diana")`; Bilder eingebettet (≤ 800 px, q60).
  - `ablegen(uid: str) -> str` – schreibt Felix-HTML `<Rubrik>/<dateiname ohne .html>_kurs-intern.html` und Diana-HTML `..._kurs.html` im Mitschriften-Ordner (tmp + replace, dann DB), Diana-PDF `kurs-<uid8>.pdf` über `kurs_pdf.ablegen`; ist es zu groß → PDF entfernen, `kurs_status = 'pdf_zu_gross'`, sonst `'fertig'`; alte Dateien eines früheren Stands entfernen; Rückgabe `kurs_status`.

- [ ] **Step 1: Failing tests** (KI per `monkeypatch.setattr(ollama, "chat", ...)`, sales-auge per Fake aus Task 2)
```python
def test_erzeugen_speichert_json_und_stand(kurs_mitschrift, ki_liefert_gutes_json): 
    j = km.erzeugen(kurs_mitschrift); z = _zeile(kurs_mitschrift)
    assert j["abschnitte"][0]["titel"] and z["kurs_stand"] == km.kurs_stand(kurs_mitschrift)
def test_kaputtes_json_zaehlt_versuch(kurs_mitschrift, ki_liefert("kein json")):
    with pytest.raises(ValueError): km.erzeugen(kurs_mitschrift)
    assert _zeile(kurs_mitschrift)["kurs_versuche"] == 1
def test_nach_drei_versuchen_fehler(...): assert _zeile(uid)["kurs_status"] == "fehler"
def test_unbekannte_bild_id_wird_verworfen():
    j = km.pruefen({"ueberblick": "x", "abschnitte": [{"titel": "A", "bilder": [{"bild_id": "fremd"}], "merken": []}], "offen": []}, {"b1"})
    assert j["abschnitte"][0]["bilder"] == []
def test_hoechstens_sechs_bilder_je_abschnitt(): ...
def test_diana_fassung_ohne_offen_und_transkript(kurs_fertig):
    h = km.kurs_html(kurs_fertig, "diana")
    assert "Offen" not in h and "Transkript" not in h and "Intern" not in h and "Merken" in h
def test_felix_fassung_mit_offen_und_intern(kurs_fertig):
    h = km.kurs_html(kurs_fertig, "felix"); assert "Offen / nachfragen" in h and "Intern" in h
def test_ablegen_legt_zwei_html_und_pdf(kurs_fertig, ablage, erzeugt_ordner, auge_liefert_pdf):
    assert km.ablegen(kurs_fertig) == "fertig"
    z = _zeile(kurs_fertig)
    assert z["kurs_pfad"].endswith("_kurs-intern.html") and z["kurs_pfad_diana"].endswith("_kurs.html")
    assert (erzeugt_ordner / z["kurs_pdf"]).exists()
def test_pdf_zu_gross(kurs_fertig, auge_liefert_riesig):
    assert km.ablegen(kurs_fertig) == "pdf_zu_gross" and _zeile(kurs_fertig)["kurs_pdf"] is None
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_mitschrift.py`
- [ ] **Step 3: Implementieren** (HTML im Stil von `mitschrift_bericht.CSS`: Kopf, Inhaltsverzeichnis mit Ankern, Überblick, je Abschnitt Bild + „Zu sehen“ + „Erklärt“ + `<ol>` Schritte + Kasten „Merken“; Felix-Fassung zusätzlich „Offen / nachfragen“; alles über `ui_termin._e` escapen).
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** – `feat(kurs): Kursmitschrift aus KI-Gliederung, zwei Fassungen, Diana-PDF`

---

### Task 4: Kurs-Handbuch – Zuordnen, Fortschreiben, Ausgabe (B1)

**Files:**
- Create: `sales-mcp/kurs_handbuch.py`
- Test: `sales-mcp/tests/test_kurs_handbuch.py`

**Interfaces:**
- Consumes: Task 1 (Tabellen, `lernende`), Task 2 (`kurs_pdf`), Task 3 (`kurs_json` einer Mitschrift).
- Produces:
  - `MAX_BILDER_KAPITEL = 3`
  - `ZUORDNUNG_SYSTEM`, `KAPITEL_SYSTEM: str` (Prompts). Zuordnung: Eingabe = Kapitel des Lernenden `[{"kapitel_id", "titel", "kurz": erste 400 Zeichen}]` + Abschnitte der neuen Sitzung mit Datum; Antwort `{"zuordnung": [{"abschnitt": int, "entscheidung": "ergaenzen"|"neu"|"ersetzen", "kapitel_id": str|null, "titel": str|null}]}`; `ersetzen` nur, wenn die Sitzung jünger ist als alle Quellen des Kapitels. Fortschreiben: Eingabe = alter Kapiteltext + neue Abschnitte + Entscheidung; Antwort `{"text_md": str, "bild_ids": [str]}`; unveränderte Teile wortgleich übernehmen.
  - `zuordnen(lead_id: str, uid: str) -> dict` – ein KI-Auftrag; prüft: `kapitel_id` muss zu `lead_id` gehören (sonst `ValueError`), Abschnittsindizes gültig; speichert in `kurs_handbuch_quelle` (`stand = kurs_stand`, `eingearbeitet_am = null`).
  - `offene_kapitel_auftraege(lead_id: str) -> list[tuple[str, str]]` – `(uid, ziel)` mit `ziel` = `kapitel_id` oder `"neu:<abschnitt>"`, die für zugeordnete, noch nicht eingearbeitete Quellen noch fehlen (in Datumsfolge der Quellen).
  - `fortschreiben(lead_id: str, uid: str, ziel: str) -> str` – ein KI-Auftrag; legt eine neue `kurs_handbuch_fassung` an (`quellen` = alte Quellen ∪ {uid}, `bild_ids` ≤ 3 jüngste geprüfte), setzt `aktuelle_fassung`; neues Kapitel bekommt `reihenfolge = max + 1`; markiert die Quelle `eingearbeitet_am`, sobald alle ihre Ziele erledigt sind. Rückgabe `kapitel_id`.
  - `handbuch_html(lead_id: str) -> str` – Inhaltsverzeichnis, Kapitel nach `reihenfolge`, je Kapitel „aus Sitzung(en) vom …“, Kopf „Stand: <Datum>, <n> Sitzungen“; kein „Offen“.
  - `ausgeben(lead_id: str) -> str` – HTML nach `MITSCHRIFTEN_ORDNER/_handbuecher/handbuch-<lead8>.html`, PDF `handbuch-<lead8>-<JJJJMMTT-HHMM>.pdf` über `kurs_pdf`; altes PDF entfernen (wenn an keinem nicht-abgelehnten Entwurf mehr hängend); `kurs_handbuch.status` = `'fertig'` | `'pdf_zu_gross'`; Rückgabe Status.

- [ ] **Step 1: Failing tests**
```python
def test_erste_sitzung_legt_kapitel_an(lernender, sitzung1_kurs_json, ki_zuordnung_alle_neu, ki_kapitel):
    kh.zuordnen(lernender, sitzung1)
    for uid, ziel in kh.offene_kapitel_auftraege(lernender): kh.fortschreiben(lernender, uid, ziel)
    assert _kapitel_titel(lernender) == ["Termin anlegen", "Kontakt suchen"]
    assert not kh.offene_kapitel_auftraege(lernender)
def test_ergaenzen_aendert_nur_betroffenes_kapitel(handbuch_nach_sitzung1, sitzung2, ki_ergaenzt_kapitel_1):
    vorher = _texte(lernender); ...  # nach Sitzung 2
    assert _texte(lernender)["Kontakt suchen"] == vorher["Kontakt suchen"]      # wortgleich
    assert len(_fassungen("Termin anlegen")) == 2
def test_kapitel_eines_anderen_lernenden_wird_abgewiesen(zwei_lernende, ki_zuordnung_fremdes_kapitel):
    with pytest.raises(ValueError): kh.zuordnen(lernender_a, sitzung_a)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender_a,))
def test_ersetzen_nur_durch_juengere_sitzung(...): ...   # 'ersetzen' von älterer Sitzung → als 'ergaenzen' behandelt
def test_hoechstens_drei_bilder_je_kapitel(...): assert len(_aktuell("Termin anlegen")["bild_ids"]) <= 3
def test_handbuch_html_ohne_offen_mit_quellen(handbuch_nach_sitzung1):
    h = kh.handbuch_html(lernender); assert "aus Sitzung" in h and "Offen" not in h and "Stand:" in h
def test_ausgeben_pdf_zu_gross(handbuch_nach_sitzung1, auge_liefert_riesig):
    assert kh.ausgeben(lernender) == "pdf_zu_gross"
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_handbuch.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** – `feat(kurs): Kurs-Handbuch mit Kapiteln und Fassungen (B1)`

---

### Task 5: Quelle entfernen, Reihenfolge, Löschen und Verschieben

**Files:**
- Modify: `sales-mcp/kurs_handbuch.py`, `sales-mcp/kurs_mitschrift.py`
- Modify: `sales-mcp/termin_akte.py` (`mitschrift_entfernen` ~Z. 445), `sales-mcp/server.py` (`_mitschriften_abraeumen` ~Z. 8885), `sales-mcp/mitschrift_bericht.py` (`verschieben` ~Z. 273, `abgleichen` ~Z. 311)
- Test: `sales-mcp/tests/test_kurs_quelle.py`

**Interfaces:**
- Consumes: Task 3, Task 4, Task 6 (`kurs_versand.offene_verwerfen`) – Task 6 wird vor Task 5 umgesetzt (Hinweis unten).
- Produces:
  - `kurs_handbuch.quelle_entfernen(lead_id: str, uid: str) -> int` – setzt jedes Kapitel, das eine Fassung mit `uid` in `quellen` hat, auf die jüngste Fassung **ohne** `uid` zurück (Kapitel ohne solche Fassung wird gelöscht), löscht alle Fassungen mit `uid` in `quellen`, löscht die `kurs_handbuch_quelle`-Zeile, setzt `eingearbeitet_am = null` bei allen jüngeren Quellen derselben Kapitel (sie werden neu eingearbeitet; ihre gespeicherte `zuordnung` bleibt, Kapitel-ids, die nicht mehr existieren, werden zu `neu`). Rückgabe: Anzahl betroffener Kapitel.
  - `kurs_handbuch.einfuegen_vorbereiten(lead_id: str, uid: str, beginn: datetime) -> None` – kommt eine Sitzung, die älter ist als schon eingearbeitete: alle jüngeren Quellen wie oben zurückrollen (ihre Fassungen löschen, `eingearbeitet_am = null`), damit die Reihenfolge stimmt.
  - `kurs_mitschrift.entfernen(uid: str) -> None` – Dateien (`kurs_pfad`, `kurs_pfad_diana`, `kurs_pdf`) löschen, Spalten leeren, `kurs_versand.offene_verwerfen(uid=uid)`, für jeden Lernenden mit Quelle `uid`: `kurs_handbuch.quelle_entfernen`.
  - `mitschrift_entfernen` und `_mitschriften_abraeumen` rufen **vor** dem Löschen der Zeile `kurs_mitschrift.entfernen(uid)`; Lead-Löschung entfernt zusätzlich `kurs_handbuch`-Dateien des Leads (`kurs_handbuch.alles_entfernen(lead_id: str) -> None`, löscht HTML/PDF; Zeilen fallen per Kaskade).
  - `verschieben`: wechselt eine Mitschrift **aus** „Kurse“ heraus → `kurs_mitschrift.entfernen(uid)`.
  - `abgleichen`: erkennt `*_kurs.html`/`*_kurs-intern.html` als zu einer Mitschrift gehörig (Pfad aus `kurs_pfad`/`kurs_pfad_diana`), Waisen nach Schonfrist löschen; `_handbuecher/` und `kurs-*.pdf`/`handbuch-*.pdf` ohne Buchung (in `termin_mitschriften.kurs_pdf`, `kurs_handbuch.pdf` oder an einem nicht-abgelehnten Entwurf) ebenso.

> **Ausführungsreihenfolge:** Task 6 (Versand) wird **vor** Task 5 umgesetzt; die Nummern bleiben für die Querverweise.

- [ ] **Step 1: Failing tests**
```python
def test_quelle_entfernen_setzt_kapitel_zurueck(handbuch_nach_sitzung_1_und_2):
    kh.quelle_entfernen(lernender, sitzung2)
    assert _aktuell("Termin anlegen")["quellen"] == [sitzung1]
    assert not server._q("select 1 from kurs_handbuch_fassung where %s = any(quellen)", (sitzung2,))
def test_kapitel_nur_aus_entfernter_quelle_verschwindet(...): ...
def test_juengere_quellen_werden_neu_eingearbeitet(handbuch_1_2_3):
    kh.quelle_entfernen(lernender, sitzung2)
    assert (sitzung3, ...) in kh.offene_kapitel_auftraege(lernender)
def test_aeltere_sitzung_wird_an_datumsstelle_eingefuegt(handbuch_nach_sitzung2, sitzung1_kommt_spaet):
    kh.einfuegen_vorbereiten(lernender, sitzung1, beginn_1)
    auftraege = kh.offene_kapitel_auftraege(lernender)
    assert [u for u, _ in auftraege][0] == sitzung1      # ältere zuerst
def test_loeschen_raeumt_entwurf_pdf_und_fassungen(kurs_mit_entwurf_pending, erzeugt_ordner):
    termin_akte.mitschrift_entfernen(uid)
    assert _draft_status(draft) == "rejected" and not (erzeugt_ordner / pdf).exists()
    assert not server._q("select 1 from kurs_handbuch_fassung where %s = any(quellen)", (uid,))
def test_verschieben_aus_kurse_raeumt_auf(kurs_fertig): mb.verschieben(uid, "Notizen"); assert _zeile(uid)["kurs_pfad"] is None
def test_lead_loeschantrag_entfernt_handbuchdateien(...): ...
def test_abgleich_laesst_gebuchte_kursdateien_stehen_und_loescht_waisen(...): ...
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_quelle.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu Regression `vm_test.sh tests/test_mitschrift_bericht.py tests/test_termin_takt.py tests/test_ui_mitschriften.py`
- [ ] **Step 5: Commit** – `feat(kurs): Quelle entfernen, Reihenfolge, Loeschen und Verschieben`

---

### Task 6: Versand – Entwürfe zur Freigabe

**Files:**
- Create: `sales-mcp/kurs_versand.py`
- Test: `sales-mcp/tests/test_kurs_versand.py`

**Interfaces:**
- Consumes: `server.entwurf_erstellen(lead_id, "email", text, betreff=..., medien_datei=<pdf>, thema="kurs")` (Rückgabe auswerten wie bestehende Aufrufer; Fehlertext → kein Eintrag in `kurs_entwuerfe`), `server.entwurf_ablehnen(draft_id)`; Tasks 1, 3, 4.
- Produces:
  - `BETREFF_KURS = "Kursmitschrift {titel} vom {datum}"`, `BETREFF_HANDBUCH = "Dein Kurs-Handbuch, Stand {datum}"`; feste Mailtexte:
    - Kurs: `"Hallo {vorname},\n\nanbei die Kursmitschrift zu unserer Sitzung vom {datum} zum Wiederholen.\n\nViele Grüße\nFelix"`
    - Handbuch: `"Hallo {vorname},\n\nanbei dein Kurs-Handbuch auf dem Stand vom {datum} – zum Nachschlagen, falls du etwas vergisst.\n\nViele Grüße\nFelix"`
    (`vorname` aus `leads.vorname`, sonst `name`, sonst „Hallo,“).
  - `kurs_entwurf(uid: str, lernender: dict) -> str | None` – verwirft offene (`pending`) Kursmitschrift-Entwürfe derselben `uid`+Lernender, legt neuen an, trägt in `kurs_entwuerfe` ein; `None`, wenn `kurs_status <> 'fertig'`.
  - `handbuch_entwurf(lead_id: str) -> str | None` – verwirft offene Handbuch-Entwürfe des Leads, legt neuen an (`None` bei `kurs_handbuch.status <> 'fertig'`).
  - `offene_verwerfen(uid: str | None = None, lead_id: str | None = None) -> int` – lehnt `pending`-Entwürfe aus `kurs_entwuerfe` ab (über `server.entwurf_ablehnen`); nie `approved`/`sending`/`sent`.
  - `entwurf_status(uid: str) -> str | None` – jüngster Status (`pending`/`approved`/`sent`/`rejected`/…) für die UI.

- [ ] **Step 1: Failing tests**
```python
def test_kurs_entwurf_mit_pdf(kurs_fertig, lernender):
    d = kv.kurs_entwurf(uid, lernender); z = _draft(d)
    assert z["status"] == "pending" and z["media_ref"] == _zeile(uid)["kurs_pdf"] and z["channel"] == "email"
    assert z["subject"].startswith("Kursmitschrift ")
def test_neuer_ersetzt_offenen(kurs_fertig, lernender):
    a = kv.kurs_entwurf(uid, lernender); b = kv.kurs_entwurf(uid, lernender)
    assert _draft(a)["status"] == "rejected" and _draft(b)["status"] == "pending"
def test_freigegebener_entwurf_bleibt_bei_neuauswertung(kurs_fertig, lernender):
    a = kv.kurs_entwurf(uid, lernender); server._q("update drafts set status='approved' where id=%s", (a,))
    b = kv.kurs_entwurf(uid, lernender)
    assert _draft(a)["status"] == "approved" and b != a
def test_kein_entwurf_bei_pdf_zu_gross(kurs_pdf_zu_gross, lernender): assert kv.kurs_entwurf(uid, lernender) is None
def test_handbuch_entwurf_ersetzt_offenen(...): ...
def test_offene_verwerfen_laesst_versendete(...): ...
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_kurs_versand.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** – `feat(kurs): Entwuerfe fuer Kursmitschrift und Handbuch zur Freigabe`

---

### Task 7: Taktgeber-Schritt `kurs` und Bestand

**Files:**
- Modify: `sales-mcp/termin_takt.py` (`SCHRITTE` ~Z. 671: `("kurs", _kurs)` nach `("ablage", _ablage)`)
- Test: `sales-mcp/tests/test_termin_takt_kurs.py`

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces: `_kurs(jetzt: datetime) -> int` – Reihenfolge je Runde, **höchstens ein KI-Auftrag**, KI-freie Schritte (Ausgabe, Entwürfe) dürfen zusätzlich laufen:
  1. **Veraltet:** Kurs-Mitschriften, deren `kurs_stand` ≠ `KURS_STAND_SQL` und die schon eine Kursmitschrift hatten → `kurs_mitschrift.entfernen(uid)` (Dateien, offene Entwürfe, Handbuch-Quelle) und `kurs_json = null`, damit sie neu laufen (kein KI-Auftrag).
  2. **KI (einer davon, in dieser Priorität):** (a) Kursmitschrift erzeugen für die älteste fällige Kurs-Mitschrift (`kurs_json is null`, Versuche < 3, Neuversuch fällig) → danach im selben Schritt `kurs_mitschrift.ablegen(uid)` und je Lernendem `kurs_versand.kurs_entwurf`; (b) sonst Zuordnung für die älteste Sitzung (nach `termin_akten.beginn`) eines Lernenden mit fertiger Kursmitschrift ohne `kurs_handbuch_quelle` – vorher `einfuegen_vorbereiten`; (c) sonst ein `fortschreiben` aus `offene_kapitel_auftraege` (älteste Quelle zuerst).
  3. **Ausgabe:** Lernende, deren Quellen alle eingearbeitet sind und deren Handbuch-Stand älter ist als die jüngste Fassung → `kurs_handbuch.ausgeben` und `kurs_versand.handbuch_entwurf` (so entsteht beim Bestand nur ein Handbuch-Entwurf nach der letzten Sitzung).
  - Sitzungen mit `kurs_status = 'fehler'` werden bei (b)/(c) übersprungen.
  - Kein KI-Auftrag, wenn `_termin_steht_an(jetzt)` oder `not _ollama_da()`; Ablage-Ordner nicht beschreibbar → Schritt macht nichts (wie `_ablage`). Log nur `uid8` und Zähler.

- [ ] **Step 1: Failing tests**
```python
def test_hoechstens_ein_ki_auftrag_je_runde(zwei_kurs_mitschriften, ki_zaehler):
    termin_takt._kurs(JETZT); assert ki_zaehler.n == 1
def test_kein_ki_wenn_termin_ansteht(...): assert ki_zaehler.n == 0
def test_bestand_zwei_sitzungen_ergibt_zwei_kurs_und_einen_handbuch_entwurf(diana_bestand, ki_fake, auge_fake):
    for _ in range(20): termin_takt._kurs(JETZT)
    arten = [z["art"] for z in server._q("select art from kurs_entwuerfe e join drafts d on d.id = e.draft_id where d.status = 'pending'")]
    assert sorted(arten) == ["handbuch", "kursmitschrift", "kursmitschrift"]
def test_aeltere_sitzung_zuerst_ins_handbuch(...): ...
def test_fehler_sitzung_wird_uebersprungen(...): ...
def test_neuauswertung_baut_neu(...): ...   # Stand ändern → neue Kursmitschrift, neuer Entwurf, alter pending abgelehnt
def test_nicht_kurs_rubrik_wird_ignoriert(...): ...
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_termin_takt_kurs.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu `vm_test.sh tests/test_termin_takt.py`
- [ ] **Step 5: Commit** – `feat(kurs): Taktgeber-Schritt kurs`

---

### Task 8: Oberfläche – Reiter „Kurse“ und „Handbücher“

**Files:**
- Modify: `sales-mcp/ui_mitschriften.py`
- Test: `sales-mcp/tests/test_ui_kurs.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces (Routen, alle angemeldet, Antwortköpfe wie `/mitschriften/bericht`):
  - Liste `/mitschriften?rubrik=Kurse`: je Eintrag zusätzlich Links „Kursmitschrift (Felix)“ → `/mitschriften/kurs?uid=…&fassung=felix`, „Kursmitschrift (Diana) PDF“ → `/mitschriften/kurs.pdf?uid=…`, Status-Text: „wird erzeugt“ (Kurs ohne `kurs_status`), „fertig“, „Fehler“, „PDF zu groß“, „Kein Lernender zugeordnet“, „zur Freigabe“/„versendet“ (aus `kurs_versand.entwurf_status`).
  - `GET /mitschriften/kurs?uid=&fassung=felix|diana[&download=1]` (HTML aus Datei, Pfad aus DB), `GET /mitschriften/kurs.pdf?uid=` (`application/pdf`, `Content-Disposition: inline`).
  - Reiter **„Handbücher“** `GET /mitschriften/handbuecher`: je Lernendem Name, Stand, Anzahl Sitzungen, Links HTML/PDF (`/mitschriften/handbuch?lead=…`, `/mitschriften/handbuch.pdf?lead=…`), Kapitelliste (Titel, Quellen-Daten, Anzahl Fassungen).
  - `POST /mitschriften/handbuch/kapitel` (CSRF wie `/mitschriften/verschieben`): `aktion=umbenennen` (`kapitel_id`, `titel`, 1–80 Zeichen) | `aktion=hoch`/`runter` (`kapitel_id`) – danach `kurs_handbuch.ausgeben` nicht sofort, sondern beim nächsten „neu zur Freigabe“.
  - `POST /mitschriften/handbuch/freigeben` (CSRF, `lead`): `kurs_handbuch.ausgeben(lead)` + `kurs_versand.handbuch_entwurf(lead)`; Rückmeldung „Liegt in den Freigaben“ oder „PDF zu groß“.
  - Nicht für Rollen `lesen`/`kalender` (wie Verschieben).

- [ ] **Step 1: Failing tests**
```python
def test_kurse_reiter_zeigt_kurslinks_und_status(client_angemeldet, kurs_fertig): 
    r = client.get("/mitschriften?rubrik=Kurse"); assert "Kursmitschrift (Felix)" in r.text and "fertig" in r.text
def test_kurs_html_ohne_anmeldung_umleitung(client): assert client.get("/mitschriften/kurs?uid=x&fassung=felix").status_code in (302, 303)
def test_kurs_html_kopfzeilen(client_angemeldet, kurs_fertig):
    r = client.get(f"/mitschriften/kurs?uid={uid}&fassung=diana")
    assert r.headers["cache-control"] == "private, no-store" and "script-src 'none'" in r.headers["content-security-policy"]
def test_unbekannte_fassung_404(...): ...
def test_kein_lernender_hinweis(...): assert "Kein Lernender zugeordnet" in r.text
def test_handbuecher_liste_und_pdf(...): ...
def test_kapitel_umbenennen_braucht_csrf(...): assert r.status_code == 403
def test_kapitel_eines_anderen_leads_nicht_aenderbar(...): ...
def test_freigeben_legt_entwurf_an(...): ...
def test_rolle_lesen_darf_nicht_umbenennen(...): ...
```
- [ ] **Step 2: FAIL** – `vm_test.sh tests/test_ui_kurs.py`
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: PASS**, dazu `vm_test.sh tests/test_ui_mitschriften.py`
- [ ] **Step 5: Commit** – `feat(kurs): Oberflaeche Kurse und Handbuecher`

---

### Task 9: Doku und Ausrollen

**Files:**
- Modify: `docs/RUNBOOK.md`, `docs/DSGVO.md`, `docs/BEDIENUNG.md` (Pfade wie in PR #38; Builder sucht per `grep -rln "Mitschriften" docs/`)
- Modify: dieser Plan, Abschnitt „Ausrollen“ (Stand nach Umsetzung)

**Interfaces:** keine neuen.

- [ ] **Step 1:** RUNBOOK: Schritt `kurs` im Takt, `POST /pdf` in sales-auge, neuer rw-Mount `media-erzeugt` in sales-termine, Status-Werte, wie man einen Lernenden zuordnet (Teilnehmer-Adresse = Lead-Adresse).
- [ ] **Step 2:** DSGVO: Kursmitschrift/Handbuch enthalten gesprochene Inhalte ohne Maskierung (Felix-Entscheid A, Schutz = Freigabe); Löschwege (Mitschrift, Lead, Verschieben); Aufbewahrung der Kapitelfassungen.
- [ ] **Step 3:** BEDIENUNG: Reiter „Kurse“, „Handbücher“, Freigabe der zwei Entwürfe.
- [ ] **Step 4:** Volle Suite der neuen Tests + Regression: `vm_test.sh tests/test_kurs_*.py tests/test_termin_takt*.py tests/test_ui_mitschriften.py tests/test_ui_kurs.py tests/test_mitschrift_*.py`, dazu `bash deploy/tests/test_auge_compose.sh` und `bash deploy/tests/test_mitschriften_ordner.sh` → alle grün.
- [ ] **Step 5: Commit** – `docs(kurs): Runbook, DSGVO, Bedienung`

## Ausrollen (nach Merge, nur mit Felix' OK)

1. Claim in `00_Meta/002_Koordination_Live.md` setzen und committen.
2. Sicherung `sales` (wie 15.11.).
3. `provision.sql` einspielen (alle Laden-Schemata).
4. `update.sh` (baut sales-auge, sales-termine, sales-ui, sales-mcp neu; Hinweis: es startet weitere Container neu, inkl. openwa – Sitzung danach prüfen).
5. Takt beobachten: zwei Kursmitschriften (Diana), dann Zuordnung/Kapitel, dann ein Handbuch; Entwürfe erscheinen in den Freigaben – **nichts freigeben ohne Felix**.
6. Felix liest Kursmitschrift (Felix-Fassung) und PDFs, gibt frei oder verwirft.
