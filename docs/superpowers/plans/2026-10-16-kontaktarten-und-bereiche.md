# C1 Kontaktarten & Bereiche Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jeder Kontakt bekommt eine Art (Person/Firma) und Bereiche (bAV, Mitarbeiter, Vorsorge, Immobilien, IT, Homelab). Die Kontaktliste filtert, sucht und blättert danach, Betreiber und Agent pflegen die Einordnung, und der Bestand wird einmal automatisch eingeordnet.

**Architecture:**
- Art und Bereiche liegen in `leads.enrichment` (`art`, `bereiche`). Einziger Schreibweg ist `server._einordnen`, das jede Änderung als Aktivität `einordnung` bucht.
- Lesend leitet `server._einordnung` die wirksame Art ab (ohne `art`: Firmenfeld → firma, sonst person).
- Die Oberfläche filtert in SQL mit denselben Regeln. Der Agent schreibt über das Werkzeug `kontakt_einordnen`.

**Tech Stack:** Python 3.12, psycopg 3, Starlette (ui.py), pytest mit Test-Postgres (Schema `sales_test`).

**Spec:** `docs/superpowers/specs/2026-10-16-kontaktarten-und-bereiche-design.md`

## Global Constraints

- **Repo und Branch:** `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`, direkt committen. Vorher `git rev-parse --show-toplevel` und `git branch --show-current` prüfen. Vor dem Commit `git pull --no-rebase origin feat/stufe-1-fundament`, weil andere Sessions auf denselben Branch pushen.
- **Commits:** Conventional Commits auf Deutsch mit Trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Nur eigene Dateien stagen, nie `.superpowers/`, nie stashen, keine Hooks umgehen.
- **Kommentare** auf Deutsch mit ae/oe/ue. UI-Texte folgen dem Stil der Datei, ui.py nutzt echte Umlaute.
- **Tests:**
  - venv `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe`, Aufruf aus `sales-mcp/` mit `python -m pytest -q tests/<datei>`.
  - Test-Postgres auf :55432, Datenverzeichnis `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/pgdata2`. Läuft er nicht, mit `pg_ctl` und `-o "-p 55432 -c fsync=off -c synchronous_commit=off -c full_page_writes=off"` losgelöst starten. Eine verwaiste `postmaster.pid` vorher löschen.
  - `SALES_DB_URL` wie in den bestehenden DB-Tests setzen.
  - Bekannte, schon vorher rote Tests: 2 Medienordner-Fehler in `test_werkzeuge`, `test_anker_deckt_alle_gelesenen_caldav_und_verwandten_variablen_ab`, Datumsfehler in `test_termin_einladen`, 12 in `test_darstellung`. Jedes andere Rot gegen BASE in einem Wegwerf-Worktree prüfen.
- **Art** wörtlich: `person`, `firma`.
- **Bereiche** wörtlich, in dieser Reihenfolge: `bav` „bAV“, `mitarbeiter` „Mitarbeiter“, `vorsorge` „Private Vorsorge/Versicherung“, `immobilien` „Immobilien“, `it` „IT-Lösung“, `homelab` „Homelab“.
- **Wirksame Art ohne `art`:** Firmenfeld nicht leer → `firma`, sonst `person`.
- **Ansichten:**
  - „Nicht eingeordnet“ = `bereiche` fehlt oder ist leer.
  - „Mitarbeiter-Kandidaten“ = wirksame Art person und `mitarbeiter` in `bereiche`.
- **Aktivität** `einordnung` mit Nutzlast `{"art_vorher", "art", "bereiche_vorher", "bereiche", "weg": "ui"|"agent"|"bestand"}`. Actor: ui → `human`, agent → `agent`, bestand → `cron`.
- **Nie einordnen:** Privat markierte Kontakte (`server._privat(enrichment)`) und Sammelkontakte (`UNBEKANNT_LEAD_ID`, `LINKEDIN_POST_LEAD_ID`, `RECHERCHE_LEAD_ID`). Archivierte Kontakte dürfen eingeordnet werden.
- **Liste:** 100 Kontakte je Seite, Suche höchstens 100 Zeichen, `company` höchstens 200 Zeichen.
- Am DB-Schema ändert sich nichts.

## Review Focus

- **Suchbegriff mit `%`, `_`, `\` oder `'`:** Er wird als Text gesucht, ohne SQL-Fehler und ohne Wildcard-Wirkung (Test in Task 3).
- **`enrichment.bereiche` kaputt** (kein Array, z. B. String oder `null`): Liste, Kontaktseite und `_einordnung` fallen nicht um, der Kontakt gilt als nicht eingeordnet (Tests in Task 1 und Task 3).
- **Mehr als 500 Kontakte:** Jeder ist über die Seiten erreichbar, `seite=0`, `seite=-3`, `seite=abc` und eine zu große Seite geben keinen Fehler (Test in Task 3).
- **Einordnungsformular mit manipulierten Feldern** (unbekannte Art, unbekannter `bereich_xy`): Es wird nichts gespeichert, Antwort 422 (Test in Task 4).
- **Bestandslauf zweimal:** Der zweite Lauf ändert und protokolliert nichts (Test in Task 2).

---

### Task 1: Kern — Modell, `_einordnen`, Werkzeug `kontakt_einordnen`, `profil_lesen`

**Files:**
- Modify: `sales-mcp/server.py`. Neuer Block „Einordnung“ direkt nach `_archiv_sql` (~1136-1156). Das Werkzeug kommt in `WERKZEUGE`. `profil_lesen` (~2092-2164) bekommt die Rückgabeschlüssel `art` und `bereiche`.
- Modify: `sales-mcp/tests/test_werkzeuge.py:701-719` (93 → 94, Changelog-Kommentar)
- Create: `sales-mcp/tests/test_einordnung.py`

**Interfaces:**
- Produces:
  - `server.ARTEN: tuple[str, ...]`
  - `server.BEREICHE: dict[str, str]` (geordnet)
  - `server._sammelkontakt(lead_id) -> bool`
  - `server._einordnung(enrichment, company) -> tuple[str, list[str]]`
  - `server._einordnen(lead_id, art=None, hinzu=(), weg=(), quelle="agent") -> dict` mit Rückgabe `{"art","bereiche"}`, zusätzlich `"unveraendert": True`, oder `{"fehler"}`
  - `server.kontakt_einordnen(lead_id: str, art: str = "", bereiche_hinzu: list | None = None, bereiche_weg: list | None = None) -> str` (JSON)

- [ ] **Step 1: Failing tests** (`sales-mcp/tests/test_einordnung.py`)

```python
"""Einordnung Art + Bereiche (Spec 2026-10-16 C1)."""
import inspect
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    monkeypatch.delenv("RECHERCHE_LEAD_ID", raising=False)


def _lead(name="Max Muster", company=None, enrichment=None, source="whatsapp"):
    return str(server._q(
        "insert into leads (name, company, source, enrichment) values "
        "(%s, %s, %s, %s::jsonb) returning id",
        (name, company, source, json.dumps(enrichment or {})))[0]["id"])


def _enrichment(lead):
    return server._q("select enrichment from leads where id=%s", (lead,))[0]["enrichment"]


def _protokoll(lead):
    return server._q("select payload, actor from activities where lead_id=%s "
                     "and type='einordnung' order by created_at", (lead,))


def test_konstanten():
    assert server.ARTEN == ("person", "firma")
    assert list(server.BEREICHE) == ["bav", "mitarbeiter", "vorsorge",
                                     "immobilien", "it", "homelab"]
    assert server.BEREICHE["it"] == "IT-Lösung"


@pytest.mark.parametrize("enr,company,erwartet", [
    ({}, None, ("person", [])),
    ({}, "ACME GmbH", ("firma", [])),
    ({"art": "person"}, "ACME GmbH", ("person", [])),
    ({"art": "quatsch"}, "", ("person", [])),
    ({"bereiche": ["homelab", "bav", "unbekannt", "bav"]}, None, ("person", ["bav", "homelab"])),
    ({"bereiche": "bav"}, None, ("person", [])),
    ({"bereiche": None}, None, ("person", [])),
    (None, None, ("person", [])),
])
def test_einordnung_wirksam(enr, company, erwartet):
    assert server._einordnung(enr, company) == erwartet


def test_einordnen_setzt_und_protokolliert():
    lead = _lead(enrichment={"profil": {"beruf": "Koch"}})
    r = server._einordnen(lead, "person", ["vorsorge", "mitarbeiter"], (), quelle="agent")
    assert r == {"art": "person", "bereiche": ["mitarbeiter", "vorsorge"]}
    e = _enrichment(lead)
    assert e["art"] == "person" and e["bereiche"] == ["mitarbeiter", "vorsorge"]
    assert e["profil"] == {"beruf": "Koch"}          # andere Schluessel unberuehrt
    p = _protokoll(lead)
    assert len(p) == 1 and p[0]["actor"] == "agent"
    assert p[0]["payload"] == {"art_vorher": None, "art": "person",
                               "bereiche_vorher": [], "bereiche": ["mitarbeiter", "vorsorge"],
                               "weg": "agent"}


def test_weg_entfernt_und_actor_je_quelle():
    lead = _lead(enrichment={"art": "person", "bereiche": ["bav", "it"]})
    r = server._einordnen(lead, None, (), ["bav"], quelle="ui")
    assert r["bereiche"] == ["it"]
    assert _protokoll(lead)[-1]["actor"] == "human"


def test_unveraendert_ohne_protokoll():
    lead = _lead(enrichment={"art": "firma", "bereiche": ["bav"]})
    r = server._einordnen(lead, "firma", ["bav"], ())
    assert r.get("unveraendert") is True
    assert _protokoll(lead) == []


@pytest.mark.parametrize("art,hinzu,weg", [
    ("kunde", [], []), (None, ["rente"], []), (None, [], ["x"]), (None, ["bav"], ["bav"])])
def test_ungueltig(art, hinzu, weg):
    lead = _lead()
    assert "fehler" in server._einordnen(lead, art, hinzu, weg)
    assert _protokoll(lead) == []


def test_privat_und_sammel_gesperrt(monkeypatch):
    privat = _lead(enrichment={"_privat": {"privat": True}})
    assert "fehler" in server._einordnen(privat, "person", ["bav"], ())
    sammel = _lead(name="LINKEDIN (Eigenes Profil)")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", sammel)
    assert "fehler" in server._einordnen(sammel, "person", (), ())
    unb = _lead(name="Unbekannte Eingaenge")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", unb)
    assert server._sammelkontakt(unb)
    rech = _lead(name="RECHERCHE")
    monkeypatch.setenv("RECHERCHE_LEAD_ID", rech)
    assert server._sammelkontakt(rech)


def test_unbekannte_id():
    assert "fehler" in server._einordnen("00000000-0000-0000-0000-000000000000", "person")
    assert "fehler" in server._einordnen("kaputt", "person")


def test_werkzeug_registriert_und_signatur():
    assert server.kontakt_einordnen in server.WERKZEUGE
    assert list(inspect.signature(server.kontakt_einordnen).parameters) == [
        "lead_id", "art", "bereiche_hinzu", "bereiche_weg"]
    lead = _lead()
    r = json.loads(server.kontakt_einordnen(lead, "person", ["immobilien"]))
    assert r == {"art": "person", "bereiche": ["immobilien"]}


def test_profil_lesen_zeigt_einordnung():
    lead = _lead(company="ACME GmbH", enrichment={"bereiche": ["bav"]})
    p = json.loads(server.profil_lesen(lead))
    assert p["art"] == "firma" and p["bereiche"] == ["bav"]
```

(Heißt der Parameter von `profil_lesen` nicht `lead_id`, einfach positional aufrufen. Speichert die Privat-Markierung anders als `{"_privat": {"privat": True}}`, die Form aus `server._privat_schreiben` übernehmen.)

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_einordnung.py`
Expected: FAIL mit `AttributeError: module 'server' has no attribute 'ARTEN'`

- [ ] **Step 3: Implementieren** (`server.py`, nach `_archiv_sql`)

```python
# ---------------------------------------------------------------------------
# Einordnung (C1, Spec 2026-10-16): Art + Bereiche je Kontakt. Liegt in
# leads.enrichment ("art", "bereiche") — kein DDL. Einziger Schreibweg ist
# _einordnen; jede Aenderung wird als Aktivitaet 'einordnung' gebucht.
# ---------------------------------------------------------------------------

ARTEN = ("person", "firma")
BEREICHE = {
    "bav": "bAV",
    "mitarbeiter": "Mitarbeiter",
    "vorsorge": "Private Vorsorge/Versicherung",
    "immobilien": "Immobilien",
    "it": "IT-Lösung",
    "homelab": "Homelab",
}
_EINORDNUNG_ACTOR = {"ui": "human", "agent": "agent", "bestand": "cron"}


def _sammelkontakt(lead_id) -> bool:
    """Einer der Sammelkontakte (Unbekannte Eingaenge, LinkedIn-Profil,
    Recherche) — kein Mensch, also nie einzuordnen."""
    ids = {str(x).strip() for x in (
        UNBEKANNT_LEAD_ID, LINKEDIN_POST_LEAD_ID,
        os.environ.get("RECHERCHE_LEAD_ID", "")) if str(x or "").strip()}
    return str(lead_id) in ids


def _einordnung(enrichment, company) -> tuple:
    """(wirksame Art, Bereiche in fester Reihenfolge) — rein, ohne DB.
    Ohne gesetzte Art entscheidet das Firmenfeld; kaputte Werte zaehlen als
    nicht gesetzt."""
    e = enrichment if isinstance(enrichment, dict) else {}
    art = e.get("art")
    if art not in ARTEN:
        art = "firma" if (company or "").strip() else "person"
    roh = e.get("bereiche")
    roh = roh if isinstance(roh, list) else []
    return art, [b for b in BEREICHE if b in roh]


def _einordnen(lead_id, art=None, hinzu=(), weg=(), quelle="agent") -> dict:
    try:
        uuid.UUID(str(lead_id))
    except ValueError:
        return {"fehler": f"'{lead_id}' ist keine gueltige lead_id."}
    hinzu, weg = list(hinzu or []), list(weg or [])
    if art and art not in ARTEN:
        return {"fehler": f"Unbekannte Art '{art}' — erlaubt: {', '.join(ARTEN)}."}
    for b in hinzu + weg:
        if b not in BEREICHE:
            return {"fehler": f"Unbekannter Bereich '{b}' — erlaubt: "
                              f"{', '.join(BEREICHE)}."}
    if set(hinzu) & set(weg):
        return {"fehler": "Ein Bereich kann nicht zugleich hinzu und weg."}
    if _sammelkontakt(lead_id):
        return {"fehler": "Sammelkontakte werden nicht eingeordnet."}
    z = _q("select enrichment, company from leads where id = %s", (str(lead_id),))
    if not z:
        return {"fehler": f"Kein Kontakt mit lead_id {lead_id}."}
    e = z[0]["enrichment"] or {}
    if _privat(e):
        return {"fehler": "Privat markierte Kontakte werden nicht eingeordnet."}
    art_vorher = e.get("art") if e.get("art") in ARTEN else None
    wirksam, bereiche_vorher = _einordnung(e, z[0]["company"])
    art_neu = art or art_vorher or wirksam
    neu = [b for b in BEREICHE if (b in bereiche_vorher or b in hinzu) and b not in weg]
    if art_neu == art_vorher and neu == bereiche_vorher:
        return {"art": art_neu, "bereiche": neu, "unveraendert": True}
    _q("update leads set enrichment = jsonb_set(jsonb_set("
       "coalesce(enrichment, '{}'::jsonb), '{art}', to_jsonb(%s::text), true), "
       "'{bereiche}', %s::jsonb, true), updated_at = now() where id = %s returning id",
       (art_neu, json.dumps(neu), str(lead_id)))
    _q("insert into activities (lead_id, type, payload, actor) values "
       "(%s, 'einordnung', %s, %s) returning id",
       (str(lead_id), _json({"art_vorher": art_vorher, "art": art_neu,
                             "bereiche_vorher": bereiche_vorher, "bereiche": neu,
                             "weg": quelle}), _EINORDNUNG_ACTOR[quelle]))
    return {"art": art_neu, "bereiche": neu}


@_gesichert
def kontakt_einordnen(lead_id: str, art: str = "", bereiche_hinzu: list | None = None,
                      bereiche_weg: list | None = None) -> str:
    """Kontakt einordnen: Art ('person'|'firma') und Bereiche hinzufuegen/
    entfernen — bav, mitarbeiter, vorsorge (Private Vorsorge/Versicherung),
    immobilien, it (IT-Loesung), homelab. Nur auf Zuruf des Betreibers oder
    bei EINDEUTIGEM Gespraechsinhalt; nie raten. Die Aenderung dem Betreiber
    im Chat nennen. Privat markierte Kontakte und Sammelkontakte lehnt das
    Werkzeug ab. Sendet nichts."""
    return _json(_einordnen(lead_id, art or None, bereiche_hinzu or [],
                            bereiche_weg or [], quelle="agent"))
```

Prüfen:
- `_privat(e)` erwartet das ganze `enrichment`, wie `ui.py` `server._privat(z["enrichment"])`. Sonst `_privat(e.get(PRIVAT_SCHLUESSEL))`.
- `uuid` und `os` sind importiert.
- `UNBEKANNT_LEAD_ID` und `LINKEDIN_POST_LEAD_ID` werden weiter unten im Modul definiert. Zur Laufzeit ist das egal, weil `_sammelkontakt` erst später aufgerufen wird.

In `WERKZEUGE` direkt nach `kontakt_aktualisieren` (bzw. bei den Kontakt-Werkzeugen) eintragen:

```python
    # Einordnung Art + Bereiche (16.10.2026), Vertraege: tests/test_einordnung.py.
    kontakt_einordnen,
```

In `profil_lesen` neben `"firma": e.get("firma", {})` einfügen:

```python
        "art": _einordnung(e, leads[0].get("company"))[0],
        "bereiche": _einordnung(e, leads[0].get("company"))[1],
```

Dazu `company` in die Spaltenliste des `select` von `profil_lesen` aufnehmen (`select id, name, status, consent_status, enrichment, notes, company ...`).

`tests/test_werkzeuge.py`: Changelog `# 16.10.2026: kontakt_einordnen (C1 Einordnung), 93 -> 94.` und `assert len(namen) == 94`.

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_einordnung.py tests/test_werkzeuge.py`
Expected: grün bis auf die 2 bekannten Medienordner-Fehler.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_einordnung.py sales-mcp/tests/test_werkzeuge.py
git commit -m "feat(kontakte): Einordnung Art und Bereiche mit Werkzeug kontakt_einordnen"
```

---

### Task 2: `kontakt_anlegen` setzt die Art, Firmenfeld bearbeitbar, Bestandslauf

**Files:**
- Modify: `sales-mcp/server.py`: `kontakt_anlegen` (~377-408), `KONTAKT_FELDER` (~419) und `kontakt_aktualisieren` (~411-463), neue Funktion `einordnung_bestand()` nach `kontakt_einordnen`
- Modify: `sales-mcp/ui.py`: Feldtitel und Eingabetyp für `company` in `KONTAKT_FELD_TITEL` / `KONTAKT_FELD_EINGABE` (~314)
- Test: `sales-mcp/tests/test_einordnung.py` (anhängen), bestehende UI-Formulartests prüfen

**Interfaces:**
- Consumes: `server._einordnen`, `server._sammelkontakt`, `server._privat` (Task 1).
- Produces: `server.einordnung_bestand() -> dict` mit den Schlüsseln `firmen`, `personen`, `bav`, `uebersprungen` (ints); `KONTAKT_FELDER == ("phone", "email", "name", "company")`.

- [ ] **Step 1: Failing tests** (an `tests/test_einordnung.py` anhängen)

```python
@pytest.mark.parametrize("name,art", [
    ("Mario Ries (Conrad Electronic SE)", "firma"),
    ("Anna Beispiel", "person"),
    ("Jörg (privat)", "firma"),
])
def test_anlegen_setzt_art(name, art):
    r = json.loads(server.kontakt_anlegen(name, source="visitenkarte"))
    assert r["angelegt"] is True
    assert _enrichment(r["lead_id"])["art"] == art
    assert _protokoll(r["lead_id"]) == []


def test_company_bearbeitbar_mit_grenze():
    lead = _lead()
    assert "company" in server.KONTAKT_FELDER
    r = json.loads(server.kontakt_aktualisieren(lead, "company", "ACME GmbH"))
    assert r == {"gesetzt": {"company": "ACME GmbH"}}
    assert "fehler" in json.loads(server.kontakt_aktualisieren(lead, "company", "x" * 201))


def test_bestand_ordnet_ein_und_ist_idempotent(monkeypatch):
    rech = _lead("Steuerkanzlei Huber", company="Steuerkanzlei Huber", source="recherche")
    firma = _lead("Max (ACME)", company="ACME GmbH", source="visitenkarte")
    person = _lead("Erika Muster")
    schon = _lead("Schon da", enrichment={"art": "person", "bereiche": ["it"]})
    privat = _lead("Freund", enrichment={"_privat": {"privat": True}})
    sammel = _lead("Unbekannte Eingaenge")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", sammel)
    r = server.einordnung_bestand()
    assert r == {"firmen": 2, "personen": 1, "bav": 1, "uebersprungen": 2}
    assert _enrichment(rech)["bereiche"] == ["bav"]
    assert _enrichment(firma) ["art"] == "firma" and _enrichment(firma)["bereiche"] == []
    assert _enrichment(person)["art"] == "person"
    assert _enrichment(schon)["bereiche"] == ["it"]
    assert "art" not in _enrichment(privat) and "art" not in _enrichment(sammel)
    assert _protokoll(rech)[0]["payload"]["weg"] == "bestand"
    assert _protokoll(rech)[0]["actor"] == "cron"
    vorher = server._q("select count(*) n from activities where type='einordnung'")[0]["n"]
    assert server.einordnung_bestand() == {"firmen": 0, "personen": 0, "bav": 0,
                                           "uebersprungen": 2}
    assert server._q("select count(*) n from activities where type='einordnung'")[0]["n"] == vorher
```

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_einordnung.py -k "anlegen or company or bestand"`
Expected: FAIL (`KeyError: 'art'`, `company` nicht in `KONTAKT_FELDER`, `einordnung_bestand` fehlt)

- [ ] **Step 3: Implementieren**

`kontakt_anlegen`: Das Insert schreibt die Art gleich mit. Die SQL-Zeile wird zu:

```python
    art = "firma" if re.search(r"\([^()]+\)\s*$", name or "") else "person"
    zeilen = _q("insert into leads (name, email, phone, source, notes, enrichment) "
                "values (%s, nullif(%s,''), nullif(%s,''), %s, nullif(%s,''), "
                "jsonb_build_object('art', %s::text)) returning id",
                (name, email, phone, source, notes, art))
```

(Dazu `import re` prüfen. Der Kommentar dazu: Eine Firma in Klammern am Namensende zeigt eine Firmenvisitenkarte an, Spec C1 §4.1.)

`KONTAKT_FELDER = ("phone", "email", "name", "company")`. In `kontakt_aktualisieren` nach der Feldprüfung ergänzen:

```python
    if feld == "company" and len(wert.strip()) > 200:
        return _json({"fehler": "Firma ist laenger als 200 Zeichen."})
```

`einordnung_bestand` (nach `kontakt_einordnen`, kein Werkzeug):

```python
def einordnung_bestand() -> dict:
    """Einmalige Einordnung des Bestands (C1 §4.1, NICHT in WERKZEUGE):
    Kontakte OHNE gesetzte Art bekommen sie nach dem Firmenfeld;
    Recherche-Firmen zusaetzlich bAV. Privat markierte und Sammelkontakte
    bleiben unberuehrt. Ein zweiter Lauf aendert nichts."""
    zahl = {"firmen": 0, "personen": 0, "bav": 0, "uebersprungen": 0}
    for z in _q("select id::text as id, company, source, enrichment from leads "
                "where not (coalesce(enrichment, '{}'::jsonb) ? 'art') "
                "order by created_at"):
        if _sammelkontakt(z["id"]) or _privat(z["enrichment"] or {}):
            zahl["uebersprungen"] += 1
            continue
        firma = bool((z["company"] or "").strip())
        hinzu = ["bav"] if firma and z["source"] == "recherche" else []
        r = _einordnen(z["id"], "firma" if firma else "person", hinzu, (),
                       quelle="bestand")
        if "fehler" in r:
            zahl["uebersprungen"] += 1
            continue
        zahl["firmen" if firma else "personen"] += 1
        zahl["bav"] += len(hinzu)
    return zahl
```

Hinweis: Privat und Sammelkontakte bekommen nie ein `art`. Deshalb zählen sie bei jedem Lauf erneut als übersprungen. Das ist gewollt, siehe Test.

`ui.py`: In `KONTAKT_FELD_TITEL` `"company": "Firma"` ergänzen, in `KONTAKT_FELD_EINGABE` `"company": "text"` (bzw. im Stil der Datei). Prüfen bestehende Formulartests in `tests/test_ui.py` (ab ~1458) die Feldmenge oder -reihenfolge, die neue Reihenfolge `name, phone, email, company` übernehmen und das im Report nennen.

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_einordnung.py tests/test_werkzeuge.py tests/test_ui.py`
Expected: grün bis auf die bekannten Roten.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/server.py sales-mcp/ui.py sales-mcp/tests/test_einordnung.py sales-mcp/tests/test_ui.py
git commit -m "feat(kontakte): Art beim Anlegen, Firmenfeld bearbeitbar, Bestandseinordnung"
```

---

### Task 3: Kontaktliste — Reiter, Bereich-Filter, Suche, Blättern

**Files:**
- Modify: `sales-mcp/ui.py`: `kontakte()` (~3185-3259), Konstante `KONTAKTE_SEITE = 100` neben `KONTAKTE_MAX` (297; `KONTAKTE_MAX` bleibt für ~5749 bestehen)
- Test: `sales-mcp/tests/test_kontakte_liste.py` (anhängen, Helfer der Datei nutzen)

**Interfaces:**
- Consumes: `server.ARTEN`, `server.BEREICHE`, `server._einordnung` (Task 1).
- Produces: GET `/kontakte?ansicht=alle|personen|firmen|mitarbeiter|offen&bereich=<schluessel>&q=<text>&seite=<n>&archiv=1`.

- [ ] **Step 1: Failing tests** (an `tests/test_kontakte_liste.py` anhängen. Schreibt der Helfer `_lead` dort keine `company`/`enrichment`, einen lokalen Helfer `_lead_e` per Insert anlegen.)

```python
import json as _json_t


def _lead_e(name, company=None, enrichment=None, phone=None):
    return str(server._q(
        "insert into leads (name, company, phone, enrichment) values (%s, %s, %s, %s::jsonb) "
        "returning id", (name, company, phone, _json_t.dumps(enrichment or {})))[0]["id"])


def test_reiter_und_anzahlen():
    _lead_e("Pia Person", enrichment={"art": "person", "bereiche": ["mitarbeiter"]})
    _lead_e("Firma Alpha", company="Alpha GmbH", enrichment={"bereiche": ["bav"]})
    _lead_e("Offen Otto")
    seite = _get("/kontakte?ansicht=mitarbeiter").text
    assert "Pia Person" in seite and "Firma Alpha" not in seite and "Offen Otto" not in seite
    assert "Firma Alpha" in _get("/kontakte?ansicht=firmen").text
    offen = _get("/kontakte?ansicht=offen").text
    assert "Offen Otto" in offen and "Pia Person" not in offen
    alle = _get("/kontakte").text
    assert "Mitarbeiter-Kandidaten (1)" in alle and "Nicht eingeordnet (1)" in alle


def test_bereich_filter():
    _lead_e("Ina IT", enrichment={"bereiche": ["it"]})
    _lead_e("Hans Homelab", enrichment={"bereiche": ["homelab"]})
    seite = _get("/kontakte?bereich=it").text
    assert "Ina IT" in seite and "Hans Homelab" not in seite


def test_unbekannte_ansicht_und_bereich_gelten_als_alle():
    _lead_e("Zora Ziel")
    assert _get("/kontakte?ansicht=quatsch&bereich=quatsch").status_code == 200


def test_suche_name_firma_telefon_und_sonderzeichen():
    _lead_e("Klara Klee", company="Blumen 100% GmbH", phone="+49 171 2345678")
    _lead_e("Bert Andere")
    assert "Klara Klee" in _get("/kontakte?q=klee").text
    assert "Klara Klee" in _get("/kontakte?q=blumen").text
    assert "Klara Klee" in _get("/kontakte?q=2345678").text
    r = _get("/kontakte?q=100%25")
    assert r.status_code == 200 and "Klara Klee" in r.text and "Bert Andere" not in r.text
    for q in ("%25", "_", "%27", "%5C"):
        assert _get(f"/kontakte?q={q}").status_code == 200
    assert "Bert Andere" not in _get("/kontakte?q=%25").text


def test_kaputte_bereiche_gelten_als_offen():
    _lead_e("Kaputt Karl", enrichment={"bereiche": "bav"})
    assert "Kaputt Karl" in _get("/kontakte?ansicht=offen").text


def test_blaettern_ueber_500():
    with server.pool.connection() as conn:
        conn.execute("insert into sales_test.leads (name) select 'Massen ' || "
                     "lpad(g::text, 4, '0') from generate_series(1, 567) g")
    namen = set()
    for s in range(1, 7):
        t = _get(f"/kontakte?seite={s}").text
        namen |= {n for n in (f"Massen {i:04d}" for i in range(1, 568)) if n in t}
    assert len(namen) == 567
    for s in ("0", "-3", "abc", "999"):
        assert _get(f"/kontakte?seite={s}").status_code == 200


def test_einordnung_spalte_zeigt_chips():
    _lead_e("Chip Chen", enrichment={"art": "person", "bereiche": ["vorsorge"]})
    seite = _get("/kontakte").text
    assert "Private Vorsorge/Versicherung" in seite
```

(Leert die Datei die Tabellen nicht autouse, in jedem Test truncaten wie in den bestehenden Tests der Datei. Die Namen in `test_blaettern_ueber_500` werden mit 4 Stellen erzeugt, damit „Massen 0001“ nicht in „Massen 00011“ steckt. Kommt ein Name doch in mehreren Spalten vor, ist das für die Mengenprüfung egal.)

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_kontakte_liste.py`
Expected: FAIL (Reiter und Anzahlen fehlen, ab 500 abgeschnitten)

- [ ] **Step 3: Implementieren** (`ui.py`)

```python
KONTAKTE_SEITE = 100
KONTAKTE_ANSICHTEN = {"alle": "Alle", "personen": "Personen", "firmen": "Firmen",
                      "mitarbeiter": "Mitarbeiter-Kandidaten",
                      "offen": "Nicht eingeordnet"}
# Dieselbe Regel wie server._einordnung, als SQL (Spec C1 §3).
_ART_SQL = ("coalesce(case when l.enrichment->>'art' in ('person','firma') "
            "then l.enrichment->>'art' end, case when coalesce(l.company,'') <> '' "
            "then 'firma' else 'person' end)")
_BEREICHE_SQL = ("(case when jsonb_typeof(l.enrichment->'bereiche') = 'array' "
                 "then l.enrichment->'bereiche' else '[]'::jsonb end)")
_ANSICHT_SQL = {
    "alle": "true",
    "personen": f"{_ART_SQL} = 'person'",
    "firmen": f"{_ART_SQL} = 'firma'",
    "mitarbeiter": f"{_ART_SQL} = 'person' and {_BEREICHE_SQL} ? 'mitarbeiter'",
    "offen": f"jsonb_array_length({_BEREICHE_SQL}) = 0",
}


def _like_muster(text: str) -> str:
    """Suchtext woertlich fuer ILIKE ... ESCAPE '\\'."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _einordnung_chips(enrichment, company) -> str:
    art, bereiche = server._einordnung(enrichment, company)
    teile = [f'<span class="badge">{_e("Firma" if art == "firma" else "Person")}</span>']
    teile += [f'<span class="badge archiv">{_e(server.BEREICHE[b])}</span>' for b in bereiche]
    return " ".join(teile)
```

In `kontakte(request)`:
- Parameter lesen: `ansicht` (sonst `"alle"`), `bereich` (nur Schlüssel aus `server.BEREICHE`, sonst ignorieren), `q` (strip, `[:100]`), `seite` (int, sonst 1), `archiv`.
- Die Basisbedingung als Liste `bed` mit benannten Parametern `p` (`%(name)s`) aufbauen:
  - Archiv wie bisher.
  - Bereich: `{_BEREICHE_SQL} ? %(bereich)s`.
  - Suche: `(l.name ilike %(muster)s escape '\\' or coalesce(l.company,'') ilike %(muster)s escape '\\' or (%(ziffern)s <> '' and regexp_replace(coalesce(l.phone,''), '[^0-9]', '', 'g') like %(ziffern_muster)s))`.
  - `ziffern` = nur die Ziffern aus `q`, wenn es mindestens 3 sind, sonst `""`. `ziffern_muster` = `"%" + ziffern + "%"`. Ziffern brauchen kein Escaping.
- Anzahlen je Reiter in einer Abfrage: `select count(*) filter (where <ansicht_sql>) as <name>, ... from leads l where <bed>`.
- `gesamt = anzahl[ansicht]`, `letzte = max(1, -(-gesamt // KONTAKTE_SEITE))`, `seite = min(max(seite, 1), letzte)`.
- Die Zeilenabfrage bleibt wie bisher (Spalten plus `l.company`), mit `where <bed> and <_ANSICHT_SQL[ansicht]>`, `limit %(lim)s offset %(off)s`.
- Kopf: Reiter als Links `"<Label> (<Anzahl>)"`, der aktive mit `aria-current="page"`. Darunter Bereich-Chips als Links (aktiver hervorgehoben, „alle Bereiche“ zum Zurücksetzen) und ein GET-Suchformular (`q`, mit versteckten `ansicht`/`bereich`/`archiv`). Unten Blätterleiste „Seite s von letzte“ mit Zurück/Weiter-Links. Alle Links behalten die übrigen Parameter, gebaut mit `urllib.parse.urlencode`.
- Neue Spalte „Einordnung“ (`_einordnung_chips(z["enrichment"], z["company"])`) hinter „Name“. Die Überschriftenliste von `_tabelle` passend erweitern.
- Titel: `f"Kontakte ({gesamt})"`.

In der SQL keine `%`-Literale verwenden, alles läuft über Parameter. `'[^0-9]'` enthält kein `%`.

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_kontakte_liste.py tests/test_ui.py`
Expected: grün. Prüft ein bestehender Test die alte Spaltenliste oder den alten Titel, anpassen und im Report nennen.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_kontakte_liste.py
git commit -m "feat(ui): Kontaktliste mit Reitern, Bereich-Filter, Suche und Seiten"
```

---

### Task 4: Kontaktseite — Kasten „Einordnung“ und POST `/kontakte/einordnen`

**Files:**
- Modify: `sales-mcp/ui.py`:
  - neuer Helfer `_einordnung_bereich(lead)`, eingehängt in `kontakt_detail` (~5278-5498) direkt nach `_kontakt_formular(lead)` (~5327)
  - neuer Handler `aktion_kontakt_einordnen`
  - Route vor `Route("/kontakte/{lead_id}", ...)` (~6679-6720)
  - Feld „Einordnung“ in den `stammdaten` (~5296)
- Test: `sales-mcp/tests/test_ui.py` (anhängen; `_lead`, `_get`, `_post`, `ui.CSRF_TOKEN`)

**Interfaces:**
- Consumes: `server._einordnen`, `server._einordnung`, `server._sammelkontakt`, `server._privat`, `server.BEREICHE`, `server.ARTEN` (Task 1).
- Produces: POST `/kontakte/einordnen` mit den Formularfeldern `csrf`, `lead_id`, `art`, `bereich_<schluessel>=1`.

- [ ] **Step 1: Failing tests**

```python
def _einordnung_von(lead):
    return ui.server._q("select enrichment from leads where id=%s", (lead,))[0]["enrichment"]


def test_kontaktseite_zeigt_einordnung_und_firma():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert 'id="einordnung"' in seite and 'name="bereich_vorsorge"' in seite
    assert 'name="company"' in seite


def test_einordnen_speichert_und_protokolliert():
    lead = _lead()
    r = _post("/kontakte/einordnen", {"csrf": ui.CSRF_TOKEN, "lead_id": lead,
                                     "art": "person", "bereich_mitarbeiter": "1",
                                     "bereich_immobilien": "1"})
    assert r.status_code == 303
    e = _einordnung_von(lead)
    assert e["art"] == "person" and e["bereiche"] == ["mitarbeiter", "immobilien"]
    p = ui.server._q("select payload, actor from activities where lead_id=%s and "
                     "type='einordnung'", (lead,))
    assert p[0]["actor"] == "human" and p[0]["payload"]["weg"] == "ui"
    # Haekchen weg = Bereich weg
    _post("/kontakte/einordnen", {"csrf": ui.CSRF_TOKEN, "lead_id": lead,
                                 "art": "person", "bereich_immobilien": "1"})
    assert _einordnung_von(lead)["bereiche"] == ["immobilien"]


def test_einordnen_ohne_csrf_403():
    lead = _lead()
    assert _post("/kontakte/einordnen", {"lead_id": lead, "art": "person"}).status_code == 403


def test_einordnen_privat_403_und_kein_kasten():
    lead = _lead()
    ui.server._q("update leads set enrichment = jsonb_set(coalesce(enrichment,'{}'::jsonb), "
                 "'{_privat}', '{\"privat\": true}'::jsonb, true) where id=%s returning id",
                 (lead,))
    assert 'id="einordnung"' not in _get(f"/kontakte/{lead}").text
    r = _post("/kontakte/einordnen", {"csrf": ui.CSRF_TOKEN, "lead_id": lead, "art": "person"})
    assert r.status_code == 403


def test_einordnen_manipuliert_422():
    lead = _lead()
    for daten in ({"art": "kunde"}, {"art": "person", "bereich_rente": "1"}):
        r = _post("/kontakte/einordnen", {"csrf": ui.CSRF_TOKEN, "lead_id": lead, **daten})
        assert r.status_code == 422
    assert "art" not in _einordnung_von(lead)
```

(Ist bei `_lead` in `test_ui.py` die Privat-Form anders, sie aus `server._privat_schreiben` nehmen. Lässt sich das Rollen-Verhalten über eine bestehende Hilfe testen, z. B. einen Test, der Rolle `lesen` setzt, dort einen Test „kein Speichern-Knopf bei Rolle lesen“ ergänzen.)

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_ui.py -k einordn`
Expected: FAIL (404 bzw. Kasten fehlt)

- [ ] **Step 3: Implementieren**

```python
def _einordnung_bereich(lead) -> str:
    """Kasten 'Einordnung' (Spec C1 §4.2). Nicht fuer privat markierte und
    Sammelkontakte; Rollen ohne Schreibrecht sehen nur den Stand."""
    if server._sammelkontakt(lead["id"]) or server._privat(lead["enrichment"] or {}):
        return ""
    art, bereiche = server._einordnung(lead["enrichment"], lead.get("company"))
    stand = (("Firma" if art == "firma" else "Person") + " · " +
             (", ".join(server.BEREICHE[b] for b in bereiche) or "kein Bereich"))
    if _AKTIVE_ROLLE.get() in ("lesen", "kalender"):
        return (f'<h2 id="einordnung">Einordnung</h2><div class="karte">'
                f'{_e(stand)}</div>')
    arten = "".join(
        f'<label><input type="radio" name="art" value="{a}"'
        f'{" checked" if a == art else ""}> {_e("Firma" if a == "firma" else "Person")}'
        f'</label> ' for a in server.ARTEN)
    haken = "".join(
        f'<label><input type="checkbox" name="bereich_{b}" value="1"'
        f'{" checked" if b in bereiche else ""}> {_e(t)}</label> '
        for b, t in server.BEREICHE.items())
    return (f'<h2 id="einordnung">Einordnung</h2><div class="karte">'
            f'<form method="post" action="/kontakte/einordnen">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
            f'<p>{arten}</p><p>{haken}</p><button type="submit">Speichern</button>'
            f'</form></div>')


@_gesichert_seite
async def aktion_kontakt_einordnen(request):
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    zeilen = server._q("select enrichment from leads where id = %s", (lead_id,))
    if not zeilen:
        return _fehlerseite(404, "Nicht gefunden", "Diesen Kontakt gibt es nicht.")
    enrichment = zeilen[0]["enrichment"] or {}
    if server._sammelkontakt(lead_id) or server._privat(enrichment):
        return _fehlerseite(403, "Nicht einzuordnen",
                            "Privat markierte Kontakte und Sammelkontakte werden "
                            "nicht eingeordnet. Nichts wurde gespeichert.")
    unbekannt = [k for k in form.keys() if k.startswith("bereich_")
                 and k[len("bereich_"):] not in server.BEREICHE]
    art = str(form.get("art") or "")
    if unbekannt or (art and art not in server.ARTEN):
        return _fehlerseite(422, "Nicht gespeichert", "Unbekannte Art oder unbekannter Bereich.")
    gewaehlt = [b for b in server.BEREICHE if form.get(f"bereich_{b}") == "1"]
    _, vorher = server._einordnung(enrichment, None)
    r = server._einordnen(lead_id, art or None,
                          [b for b in gewaehlt if b not in vorher],
                          [b for b in vorher if b not in gewaehlt], quelle="ui")
    if "fehler" in r:
        return _fehlerseite(422, "Nicht gespeichert", r["fehler"])
    return RedirectResponse(f"/kontakte/{lead_id}#einordnung", status_code=303)
```

Prüfen:
- Signatur von `_kontakt_vorspann`: async? Liefert sie `(form, lead_id, abbruch)`? Und `_fehlerseite(status, titel, text)` gibt eine Response zurück. Nötigenfalls an die echte Form anpassen.
- `lead` in `kontakt_detail` ist ein dict mit `id`, `enrichment` und `company` (die Spaltenliste ~5285 enthält `company`).

Einhängen in `kontakt_detail`: `teile.append(_einordnung_bereich(lead))` direkt nach `_kontakt_formular(lead)`. In `stammdaten` eine Zeile `("Einordnung", _einordnung_chips(lead["enrichment"], lead["company"]))` ergänzen. Erwartet `_paar_tabelle` escapten Text statt HTML, stattdessen den Klartext `stand` übergeben.

Route: `Route("/kontakte/einordnen", aktion_kontakt_einordnen, methods=["POST"]),` zu den anderen `/kontakte/...`-POST-Routen, vor `Route("/kontakte/{lead_id}", ...)`.

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_ui.py tests/test_kontakte_liste.py tests/test_privat.py`
Expected: grün bis auf vorbestehende Rote.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_ui.py
git commit -m "feat(ui): Kontaktseite mit Einordnung (Art und Bereiche)"
```

---

### Task 5: Agenten-Prompt

**Files:**
- Modify: `config/workspace/AGENTS.md`: neuer Abschnitt `## Einordnung (Art und Bereiche)` direkt vor `## Kontakt-Freigabe (WhatsApp)` (~386), dazu die Tabu-Liste (~596)
- Modify: `sales-mcp/tests/test_agents_regeln.py`

- [ ] **Step 1: Failing tests** (`test_agents_regeln.py`, Stil der Datei)

```python
def test_einordnung_abschnitt():
    assert "## Einordnung (Art und Bereiche)" in TEXT
    abschnitt = TEXT.split("## Einordnung (Art und Bereiche)")[1].split("\n## ")[0]
    assert "kontakt_einordnen(" in abschnitt
    for b in ("bav", "mitarbeiter", "vorsorge", "immobilien", "it", "homelab"):
        assert f"`{b}`" in abschnitt
    assert "nie raten" in abschnitt.lower()


def test_einordnen_im_kundenchat_tabu():
    assert "`kontakt_einordnen`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
```

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_agents_regeln.py -k einordn`
Expected: FAIL

- [ ] **Step 3: Abschnitt einfügen** (vor `## Kontakt-Freigabe (WhatsApp)`)

```markdown
## Einordnung (Art und Bereiche)

Jeder Kontakt hat eine **Art** — `person` oder `firma` — und beliebig
viele **Bereiche**, fuer die er in Frage kommt:

| Bereich | Bedeutung |
|---|---|
| `bav` | betriebliche Altersversorgung (meist Firmen) |
| `mitarbeiter` | kommt als Mitarbeiter/Vertriebspartner in Frage |
| `vorsorge` | Private Vorsorge/Versicherung (private Rente u. a.) |
| `immobilien` | Immobilien |
| `it` | IT-Loesung / Software-Projekt |
| `homelab` | Homelab-Loesung |

`kontakt_einordnen(lead_id, art='', bereiche_hinzu=[...], bereiche_weg=[...])`
setzt das. Nur auf Zuruf des Betreibers oder bei EINDEUTIGEM
Gespraechsinhalt („interessiert sich fuer private Rente" → `vorsorge`) —
nie raten. Nenne jede Aenderung im Chat in einer Zeile, z. B.
„eingeordnet: Person · Vorsorge". `profil_lesen` zeigt `art` und
`bereiche`. Privat markierte Kontakte und Sammelkontakte werden nie
eingeordnet (das Werkzeug lehnt ab). Neue Kontakte bekommen ihre Art
beim Anlegen automatisch (Firma in Klammern am Namen → `firma`).
```

In der Tabu-Liste `` `post_markierungen_setzen` sowie jede Recherche `` ersetzen durch `` `post_markierungen_setzen`, `kontakt_einordnen` sowie jede Recherche ``.

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_agents_regeln.py tests/test_skill_linkedin_post.py`
Expected: grün

- [ ] **Step 5: Commit**

```bash
git add config/workspace/AGENTS.md sales-mcp/tests/test_agents_regeln.py
git commit -m "docs(agent): Einordnung Art und Bereiche im Prompt"
```

---

### Task 6: Deploy und Bestandseinordnung (Controller, nicht Subagent)

Braucht das Go des Betreibers (VM-Mutation: Bestandslauf schreibt 567 Kontakte).

- [ ] **Step 1:** Claims in WORKBOARD und Vault setzen, jeweils nur die eigene Zeile committen.
- [ ] **Step 2:** `git pull --no-rebase`, push, dann `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Erwartet: `ALLE PRUEFUNGEN GRUEN`. Danach im WORKBOARD prüfen, ob dabei fremde, noch nicht deployte Commits mitgehen. Wenn ja, vorher fragen.
- [ ] **Step 3: Probelauf, nur zählen:**

  ```
  docker exec sales-mcp python -c "import server; print(server._q(\"select count(*) filter (where coalesce(company,'')<>'') f, count(*) filter (where coalesce(company,'')<>'' and source='recherche') r, count(*) g from leads where not (coalesce(enrichment,'{}'::jsonb) ? 'art')\"))"
  ```

  Mit der Messung vergleichen (567 gesamt, 477 mit Firmenfeld).
- [ ] **Step 4:** `docker exec sales-mcp python -c "import server; print(server.einordnung_bestand())"`. Die Zahlen notieren, dann ein zweiter Lauf: Er muss überall 0 außer `uebersprungen` liefern.
- [ ] **Step 5:** HTTP-Probe im Container `sales-ui` (selbst signierter Sitzungs-Cookie wie in der Kalender-Probe). `/kontakte`, `?ansicht=firmen|mitarbeiter|offen`, `?q=…` und `?seite=6` liefern 200, die Summe der Reiteranzahlen ist plausibel, Kontakt Nr. 567 ist erreichbar.
- [ ] **Step 6:** Im Agenten prüfen: `grep -c kontakt_einordnen /home/node/.openclaw/workspace/AGENTS.md` ≥ 1.
- [ ] **Step 7:** Claims schließen, Gedächtnis aktualisieren, SDD-Arbeitsbereich löschen.
