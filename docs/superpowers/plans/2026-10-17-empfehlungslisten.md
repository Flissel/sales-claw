# C4 Empfehlungslisten Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pole-Position- und Mitarbeitervorschlags-Listen lassen sich per Foto/Diktat anlegen, digital führen (Ergebnis, Notiz, Einwilligung, Termin) und als PDF im Vordruck-Aufbau ausgeben.

**Architecture:**
- **Daten:** Die neue Tabelle `empfehlungslisten` trägt den Kopf. Jede Zeile ist ein normaler Kontakt mit `enrichment.empfehlung`.
- **Logik:** Das neue Modul `sales-mcp/empfehlungen.py` hält Anlegen, Ändern, Lesen und PDF. `server.py` bekommt nur zwei Werkzeug-Hüllen, `sales-mcp/ui_empfehlungen.py` die Seiten (eingehängt wie `ui_kalender`).
- **Kalender:** Er kann per `/kalender?neu=kunde&lead_id=…` den Kundentermin-Dialog vorbelegt öffnen.

**Tech Stack:** Python 3.12, psycopg 3, Starlette, reportlab + pypdf (vorhanden), TypeScript/Vite/vitest (kalender/), pytest mit Test-Postgres.

**Spec:** `docs/superpowers/specs/2026-10-17-empfehlungslisten-design.md`

## Global Constraints

- **Repo und Branch:**
  - `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`, direkt committen.
  - Vor jedem Commit `git rev-parse --show-toplevel` und Branch prüfen, dann `git pull --no-rebase origin feat/stufe-1-fundament`.
  - Conventional Commits auf Deutsch, Trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Nur eigene Dateien stagen, nie `.superpowers/`, nie stashen, keine Hooks umgehen.
- **Neue Testdateien:** Vor dem Anlegen prüfen, dass der Name frei ist (`ls sales-mcp/tests/<name>`).
- **Kommentare** auf Deutsch mit ae/oe/ue. UI-Texte mit echten Umlauten wie in ui.py.
- **Tests:**
  - venv `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe`, aus `sales-mcp/`.
  - Umgebung: `SALES_DB_URL` (Test-Postgres :55432) und `SALES_DB_SCHEMA=sales_test`.
  - Läuft der Server nicht: Datenverzeichnis `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/pgdata2`, Start per `pg_ctl -o "-p 55432 -c fsync=off -c synchronous_commit=off -c full_page_writes=off"`, verwaiste `postmaster.pid` vorher löschen.
  - Bekannte, schon vorher rote Tests:
    - 2 Medienordner-Fehler in `test_werkzeuge`;
    - `test_anker_deckt_alle_gelesenen_caldav_und_verwandten_variablen_ab`;
    - 2 in `test_recherche` (`test_report_ordner_fehlt_kostet_nicht_das_ergebnis`, `test_beide_werkzeuge_sind_registriert`);
    - Datumsfehler in `test_termin_einladen`;
    - 12 in `test_darstellung`.
  - Jedes andere Rot gegen BASE in einem Wegwerf-Worktree prüfen.
- **Vordrucke** (Schlüssel wörtlich):
  - `pole_position`: Titel „Pole Position“, Untertitel „Konzept für den Aufbau von Empfehlungen“, höchstens 15 Zeilen. Spalten: Name, Vorname, Beruf, Alter, Ort, Telefon, Termin, Ergebnis.
  - `mitarbeitervorschlaege`: Titel „Mitarbeitervorschläge“, höchstens 25 Zeilen. Spalten: Vorname, Name · Alter (ab 22) · Beruf · Telefon · Was zeichnet aus · Was interessiert · Termin.
- **Ergebnis** (Schlüssel → Anzeige): `offen` → offen, `nicht_erreicht` → nicht erreicht, `termin` → Termin vereinbart, `kein_interesse` → kein Interesse, `abschluss` → Abschluss.
- **Grenzen:** Textfelder höchstens 200 Zeichen. `alter` int 16–99 oder leer (bei Mitarbeitervorschlägen unter 22 nur ein Hinweis). `empfohlen_von_name` 1–120 Zeichen.
- **Einwilligung:**
  - Buchen über `server.einwilligung_erfassen(lead, "opt_in", quelle="Empfehlung: vorab gefragt von <Name> (Liste <TT.MM.JJJJ>)")`.
  - Entfernen über `server.einwilligung_widerrufen(lead, "Empfehlung: Häkchen entfernt")`.
  - Gebucht wird nur, wenn der Kontakt nicht schon `opt_in` oder `existing_customer` hat.
- **Einordnung (C1)** per `server._einordnen`: Mitarbeitervorschläge → `person` + `mitarbeiter`; Pole Position → Bereiche der Liste; Firmenzeile → `firma` + `bav`. Bei verknüpften bestehenden Kontakten bleibt die Art (`art=None`), es kommen nur Bereiche dazu.
- **Privat markierte Kontakte** (`server._privat`) werden nie verknüpft (Zeile abgewiesen). Sammelkontakte (`server._sammelkontakt`) ebenso.
- **Listen werden nie gelöscht.**
- **Rollen:** `lesen` sieht alles ohne Formulare. `kalender` hat keinen Zugriff (Pfad nicht in `_KALENDER_ROLLE_PFADE`).
- **Ruling:** PDF-Adresse `/empfehlungen/{liste_id}/pdf` statt `{id}.pdf`, weil die Seiten-Route sonst die Endung fängt.
- **Ruling:** „In einer Transaktion“ heißt hier: Alle Zeilen werden vor dem ersten Schreiben geprüft. Ein Prüffehler legt nichts an.

## Review Focus

- **Handschrift-Unsinn in Feldern** (Alter „ca. 30“, Telefon „0171/ 23 45“, leerer Name in einer Zeile mitten in der Liste): Gültiges wird angelegt, Alter „ca. 30“ ergibt einen Prüffehler mit Zeilennummer, eine kaputte Telefonnummer führt zu Zeile ohne Telefon mit Hinweis (Tests in Task 2).
- **Dieselbe Person zweimal auf einer Liste** (gleiche Nummer): Nur ein Kontakt entsteht, die zweite Zeile wird als „doppelt in der Liste“ abgewiesen (Test in Task 2).
- **Häkchen hin und her:** Die Folge Buchung, Widerruf, Buchung, nochmal Buchung endet mit `consent_status` opt_in und genau zwei Einwilligungs-Buchungen, nie mit einem doppelten Opt-in ohne Widerruf dazwischen (Test in Task 2).
- **Name mit `<script>` oder `&`:** Die Liste zeigt ihn escaped, das PDF transliteriert ihn ohne Absturz (Tests in Task 3 und Task 5).
- **Mehr Zeilen als der Vordruck fasst** (über `zeile_hinzufuegen`): Das PDF bekommt eine Folgeseite, und die UI erlaubt es bis 50 Zeilen (Tests in Task 2 und Task 3).

---

### Task 1: Tabelle `empfehlungslisten` (provision.sql, laden-anlegen.sql)

**Files:**
- Modify: `db/provision.sql`. Im Schema-Loop direkt nach dem `eigene_termine`-Block (~212-236) und hinter dem Loop neben `grant ... sales.eigene_termine to sales_app` (~504).
- Modify: `db/laden-anlegen.sql` (~31 und ~128)
- Create: `sales-mcp/tests/test_empfehlungslisten_schema.py`

**Interfaces:**
- Produces: Tabelle `<schema>.empfehlungslisten` mit den Spalten `id uuid pk`, `art text`, `empfohlen_von_lead uuid null`, `empfohlen_von_name text`, `datum date`, `berater_name text`, `struktur text`, `bereiche jsonb`, `einwilligung boolean`, `einwilligung_am timestamptz null`, `erstellt_am timestamptz`.

- [ ] **Step 1: Failing test** (`sales-mcp/tests/test_empfehlungslisten_schema.py`)

```python
"""Schema der Empfehlungslisten (Spec C4 §3.1) — Text von provision.sql und
die Tabelle in sales_test."""
import os
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
PROVISION = (WURZEL / "db" / "provision.sql").read_text(encoding="utf-8")
LADEN = (WURZEL / "db" / "laden-anlegen.sql").read_text(encoding="utf-8")


def test_provision_legt_tabelle_im_loop_an_und_gibt_rechte():
    assert "%I.empfehlungslisten" in PROVISION
    assert "check (art in ('pole_position', 'mitarbeitervorschlaege'))" in PROVISION
    assert ("grant select, insert, update on %I.empfehlungslisten to %I" in PROVISION)
    assert "grant select, insert, update on sales.empfehlungslisten to sales_app" in PROVISION
    assert "delete on sales.empfehlungslisten" not in PROVISION


def test_laden_anlegen_kennt_die_tabelle():
    assert 'create table if not exists :"schema".empfehlungslisten (like sales.empfehlungslisten including all);' in LADEN
    assert 'grant select, insert, update on :"schema".empfehlungslisten to :"rolle";' in LADEN


def test_tabelle_in_sales_test():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name='empfehlungslisten'")}
    assert spalten == {"id", "art", "empfohlen_von_lead", "empfohlen_von_name", "datum",
                       "berater_name", "struktur", "bereiche", "einwilligung",
                       "einwilligung_am", "erstellt_am"}
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_empfehlungslisten_schema.py`. Expected: FAIL (Text fehlt, Tabelle fehlt).

- [ ] **Step 3: provision.sql** (im Loop direkt nach dem `eigene_termine`-Block):

```sql
    -- Empfehlungslisten (C4, Spec 2026-10-17): Kopf je Vordruck-Blatt;
    -- die Zeilen sind Kontakte (enrichment.empfehlung). Kein Delete.
    execute format($ddl$
      create table if not exists %I.empfehlungslisten (
        id uuid primary key default gen_random_uuid(),
        art text not null check (art in ('pole_position', 'mitarbeitervorschlaege')),
        empfohlen_von_lead uuid null references %I.leads(id) on delete set null,
        empfohlen_von_name text not null check (char_length(empfohlen_von_name) between 1 and 120),
        datum date not null,
        berater_name text not null default '',
        struktur text not null default '',
        bereiche jsonb not null default '[]'::jsonb,
        einwilligung boolean not null default false,
        einwilligung_am timestamptz null,
        erstellt_am timestamptz not null default now()
      )$ddl$, s, s);
    execute format('create index if not exists empfehlungslisten_datum_idx '
                   'on %I.empfehlungslisten (datum desc)', s);
    if s = 'sales' then
      execute 'grant select, insert, update on sales.empfehlungslisten to sales_app';
    elsif s <> 'sales_test' and exists (
        select 1 from pg_roles where rolname = 'sales_app_' || substr(s, 7)) then
      execute format('grant select, insert, update on %I.empfehlungslisten to %I',
                     s, 'sales_app_' || substr(s, 7));
    end if;
```

Hinter dem Loop neben ~504: `grant select, insert, update on sales.empfehlungslisten to sales_app;`. Das `sales_test`-Grant (~510, „all tables“) deckt die Tabelle ab.

`db/laden-anlegen.sql`: nach Zeile ~31
`create table if not exists :"schema".empfehlungslisten (like sales.empfehlungslisten including all);`
und nach ~128
`grant select, insert, update on :"schema".empfehlungslisten to :"rolle";`

Hinweis: `like ... including all` übernimmt den Fremdschlüssel nicht. Das ist gewollt, `empfohlen_von_lead` bleibt dann eine unverknüpfte uuid. Kommentar dazu in laden-anlegen.sql.

- [ ] **Step 4: Lokal anwenden.** Nur auf die Test-DB: den Block für `s='sales_test'` ausführen (psql bzw. `server.pool` mit `create table if not exists sales_test.empfehlungslisten (...)` gleichen Inhalts und `references sales_test.leads(id)`). Danach `grant select, insert, update, delete, truncate on all tables in schema sales_test to sales_app;` wie in provision.sql.

- [ ] **Step 5: Grün sehen.** Run: `python -m pytest -q tests/test_empfehlungslisten_schema.py`. Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add db/provision.sql db/laden-anlegen.sql sales-mcp/tests/test_empfehlungslisten_schema.py
git commit -m "feat(db): Tabelle empfehlungslisten je Laden-Schema"
```

---

### Task 2: Kern `sales-mcp/empfehlungen.py`

**Files:**
- Create: `sales-mcp/empfehlungen.py`
- Create: `sales-mcp/tests/test_empfehlungen.py`

**Interfaces:**
- Consumes:
  - Tabelle aus Task 1;
  - `server._q`, `server._json`, `server._einordnen`, `server._privat`, `server._sammelkontakt`, `server._lead_mit_gleicher_nummer`, `server._termin_abgesagt`, `server.einwilligung_erfassen`, `server.einwilligung_widerrufen`;
  - `nummern.normalisiere_empfaenger`.
- Produces:
  - Konstanten `VORDRUCKE: dict` (art → {"titel","untertitel","max"}) und `ERGEBNISSE: dict` (schlüssel → anzeige).
  - `liste_anlegen(art, empfohlen_von_name, datum, zeilen, empfohlen_von_lead=None, berater_name=None, struktur=None, bereiche=(), einwilligung=False, quelle="agent") -> dict` mit Rückgabe `{"liste_id","neu","verknuepft","abgewiesen":[{"zeile","grund"}],"hinweise":[...]}` oder `{"fehler"}`.
  - `listen() -> list[dict]` mit `id, art, datum, empfohlen_von_name, empfohlen_von_lead, anzahl, offen, termin, abschluss`.
  - `liste(liste_id) -> dict | None` mit `kopf: dict` und `zeilen: [ {lead_id, name, vorname, nachname, telefon, beruf, alter, ort, zeichnet_aus, interessiert, ergebnis, ergebnis_text, notiz, einwilligung, termin_datum} ]`.
  - `zeile_setzen(lead_id, ergebnis=None, notiz=None, einwilligung=None, quelle="ui") -> dict`
  - `zeile_hinzufuegen(liste_id, zeile, quelle="ui") -> dict`
  - `wirksames_ergebnis(lead_id, gespeichert) -> tuple[str, str | None]` mit (ergebnis, termin_datum ISO)

- [ ] **Step 1: Failing tests** (`sales-mcp/tests/test_empfehlungen.py`; Name prüfen)

```python
"""Empfehlungslisten-Kern (Spec C4 §3/§4.1)."""
import json
import os
from datetime import date, timedelta

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import empfehlungen as em  # noqa: E402
import server  # noqa: E402

HEUTE = date.today().isoformat()


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.empfehlungslisten, sales_test.activities, "
                     "sales_test.drafts, sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    monkeypatch.delenv("RECHERCHE_LEAD_ID", raising=False)


def Z(vorname="Anna", name="Beispiel", telefon="+491701234567", **kw):
    return {"vorname": vorname, "name": name, "telefon": telefon, **kw}


def _lead(lid):
    return server._q("select name, phone, consent_status, enrichment from leads where id=%s",
                     (lid,))[0]


def _anlegen(**kw):
    a = dict(art="mitarbeitervorschlaege", empfohlen_von_name="Klaus Kunde",
             datum=HEUTE, zeilen=[Z()], berater_name="Felix Baumann", struktur="Team Nord")
    a.update(kw)
    return em.liste_anlegen(**a)


def test_mitarbeitervorschlag_legt_kontakt_an_und_ordnet_ein():
    r = _anlegen(zeilen=[Z(beruf="Koch", alter=30, zeichnet_aus="zuverlässig",
                          interessiert="Selbstständigkeit")])
    assert r["neu"] == 1 and r["verknuepft"] == 0 and r["abgewiesen"] == []
    l = em.liste(r["liste_id"])
    z = l["zeilen"][0]
    assert z["name"] == "Anna Beispiel" and z["beruf"] == "Koch" and z["alter"] == 30
    assert z["ergebnis"] == "offen" and z["einwilligung"] is False
    e = _lead(z["lead_id"])["enrichment"]
    assert e["art"] == "person" and e["bereiche"] == ["mitarbeiter"]
    assert e["empfehlung"]["liste_id"] == r["liste_id"]
    assert l["kopf"]["berater_name"] == "Felix Baumann" and l["kopf"]["struktur"] == "Team Nord"


def test_pole_position_bereiche_und_firmenzeile():
    r = _anlegen(art="pole_position", bereiche=["vorsorge", "immobilien"],
                 zeilen=[Z(), Z(vorname="", name="Bäckerei Huber", telefon="+4989123456",
                              firma=True)])
    zs = {z["name"]: z for z in em.liste(r["liste_id"])["zeilen"]}
    p = _lead(zs["Anna Beispiel"]["lead_id"])["enrichment"]
    f = _lead(zs["Bäckerei Huber"]["lead_id"])["enrichment"]
    assert p["art"] == "person" and p["bereiche"] == ["vorsorge", "immobilien"]
    assert f["art"] == "firma" and f["bereiche"] == ["bav"]


def test_grenzen_und_pruefung_vor_dem_schreiben():
    assert "fehler" in _anlegen(art="pole_position", zeilen=[Z(telefon="")] * 16)
    r = _anlegen(zeilen=[Z(), Z(vorname="", name=""), Z()])
    assert "fehler" in r and "Zeile 2" in r["fehler"]
    r = _anlegen(zeilen=[Z(alter="ca. 30")])
    assert "fehler" in r and "Zeile 1" in r["fehler"]
    assert "fehler" in _anlegen(zeilen=[Z(beruf="x" * 201)])
    assert "fehler" in _anlegen(art="quatsch")
    assert "fehler" in _anlegen(empfohlen_von_name="")
    assert server._q("select count(*) n from leads")[0]["n"] == 0
    assert server._q("select count(*) n from empfehlungslisten")[0]["n"] == 0


def test_alter_unter_22_nur_hinweis():
    r = _anlegen(zeilen=[Z(alter=19)])
    assert r["neu"] == 1 and any("22" in h for h in r["hinweise"])


def test_kaputte_telefonnummer_zeile_ohne_telefon():
    r = _anlegen(zeilen=[Z(telefon="0171/ 23 45 x")])
    assert r["neu"] == 1 and any("Telefon" in h for h in r["hinweise"])
    assert _lead(em.liste(r["liste_id"])["zeilen"][0]["lead_id"])["phone"] is None


def test_dublette_verknuepft_privat_abgewiesen_doppelt_in_liste():
    alt = server.json.loads(server.kontakt_anlegen("Anna Alt", phone="+491701234567"))["lead_id"]
    privat = server._q("insert into leads (name, phone, enrichment) values ('Pia Privat', "
                       "'+491709999999', '{\"_privat\": {\"privat\": true}}') returning id")[0]["id"]
    r = _anlegen(zeilen=[Z(), Z(vorname="Pia", name="Privat", telefon="+491709999999"),
                         Z(vorname="Anna", name="Doppelt", telefon="+491701234567")])
    assert r["verknuepft"] == 1 and r["neu"] == 0
    gruende = {a["zeile"]: a["grund"] for a in r["abgewiesen"]}
    assert 2 in gruende and "privat" in gruende[2].lower()
    assert 3 in gruende and "doppelt" in gruende[3].lower()
    assert _lead(alt)["enrichment"]["empfehlung"]["liste_id"] == r["liste_id"]
    assert "empfehlung" not in (_lead(str(privat))["enrichment"] or {})


def test_fremde_empfehlung_bleibt():
    r1 = _anlegen()
    r2 = _anlegen(empfohlen_von_name="Zweiter")
    lid = em.liste(r1["liste_id"])["zeilen"][0]["lead_id"]
    assert _lead(lid)["enrichment"]["empfehlung"]["liste_id"] == r1["liste_id"]
    assert r2["verknuepft"] == 1
    assert [z["lead_id"] for z in em.liste(r2["liste_id"])["zeilen"]] == [lid]


def test_einwilligung_pro_liste_und_umstellen():
    r = _anlegen(einwilligung=True)
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    assert _lead(lid)["consent_status"] == "opt_in"
    q = server._q("select payload from activities where lead_id=%s and type='werbe_einwilligung'",
                  (lid,))
    assert "vorab gefragt von Klaus Kunde" in q[0]["payload"]["quelle"]
    em.zeile_setzen(lid, einwilligung=False)
    assert _lead(lid)["consent_status"] == "unknown"
    em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "opt_in"
    em.zeile_setzen(lid, einwilligung=True)            # nichts doppelt
    assert len(server._q("select 1 from activities where lead_id=%s and "
                         "type='werbe_einwilligung'", (lid,))) == 2


def test_kopf_vorbelegung_aus_letzter_liste():
    _anlegen()
    r = _anlegen(berater_name=None, struktur=None)
    k = em.liste(r["liste_id"])["kopf"]
    assert k["berater_name"] == "Felix Baumann" and k["struktur"] == "Team Nord"


def test_ergebnis_setzen_und_termin_wirkt():
    r = _anlegen()
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    assert "fehler" in em.zeile_setzen(lid, ergebnis="quatsch")
    em.zeile_setzen(lid, ergebnis="nicht_erreicht", notiz="AB besprochen")
    tag = (date.today() + timedelta(days=3)).isoformat()
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin',%s) "
              "returning id", (lid, json.dumps({"uid": "u1@x", "datum": tag, "uhrzeit": "10:00"})))
    z = em.liste(r["liste_id"])["zeilen"][0]
    assert z["ergebnis"] == "termin" and z["termin_datum"] == tag and z["notiz"] == "AB besprochen"
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin_abgesagt',%s) "
              "returning id", (lid, json.dumps({"uid": "u1@x"})))
    assert em.liste(r["liste_id"])["zeilen"][0]["ergebnis"] == "nicht_erreicht"
    em.zeile_setzen(lid, ergebnis="abschluss")
    assert em.listen()[0]["abschluss"] == 1


def test_zeile_hinzufuegen_bis_50():
    r = _anlegen()
    for i in range(49):
        assert "fehler" not in em.zeile_hinzufuegen(r["liste_id"], Z(vorname=f"N{i}",
                                                                    telefon=""))
    assert "fehler" in em.zeile_hinzufuegen(r["liste_id"], Z(vorname="zuviel", telefon=""))
    assert len(em.liste(r["liste_id"])["zeilen"]) == 50


def test_unbekannte_liste():
    assert em.liste("00000000-0000-0000-0000-000000000000") is None
    assert "fehler" in em.zeile_hinzufuegen("kaputt", Z())
```

(`server.json` existiert, da server.py `json` importiert. Sonst `import json` lokal nutzen. Weicht die Privat-Form ab, die aus `server._privat_schreiben` nehmen.)

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py`. Expected: FAIL (`ModuleNotFoundError: empfehlungen`)

- [ ] **Step 3: Implementieren** (`sales-mcp/empfehlungen.py`)

```python
"""Empfehlungslisten (C4, Spec docs/superpowers/specs/2026-10-17-
empfehlungslisten-design.md): Pole Position und Mitarbeitervorschlaege.

Kopf in der Tabelle empfehlungslisten, jede Zeile ist ein Kontakt mit
enrichment.empfehlung. Erst wird ALLES geprueft, dann geschrieben — ein
Fehler in Zeile 7 legt nichts an. Listen werden nie geloescht.
"""
import json
import uuid
from datetime import date

import server
from nummern import normalisiere_empfaenger

VORDRUCKE = {
    "pole_position": {"titel": "Pole Position",
                      "untertitel": "Konzept für den Aufbau von Empfehlungen", "max": 15},
    "mitarbeitervorschlaege": {"titel": "Mitarbeitervorschläge", "untertitel": "", "max": 25},
}
ERGEBNISSE = {"offen": "offen", "nicht_erreicht": "nicht erreicht",
              "termin": "Termin vereinbart", "kein_interesse": "kein Interesse",
              "abschluss": "Abschluss"}
TEXT_MAX = 200
NAME_MAX = 120
ZEILEN_HART_MAX = 50
_TEXTFELDER = ("vorname", "name", "beruf", "ort", "zeichnet_aus", "interessiert")


def _uuid(wert):
    try:
        return str(uuid.UUID(str(wert)))
    except (ValueError, TypeError):
        return None


def _zeile_pruefen(nr: int, z, art: str):
    """-> (saubere Zeile, hinweise) oder raise ValueError('Zeile n: ...')."""
    if not isinstance(z, dict):
        raise ValueError(f"Zeile {nr}: keine Zeile.")
    sauber = {}
    for f in _TEXTFELDER:
        w = z.get(f) or ""
        if not isinstance(w, str):
            raise ValueError(f"Zeile {nr}: {f} ist kein Text.")
        if len(w.strip()) > TEXT_MAX:
            raise ValueError(f"Zeile {nr}: {f} ist laenger als {TEXT_MAX} Zeichen.")
        sauber[f] = " ".join(w.split())
    if not (sauber["vorname"] or sauber["name"]):
        raise ValueError(f"Zeile {nr}: Name fehlt.")
    alter = z.get("alter")
    if alter in ("", None):
        sauber["alter"] = None
    else:
        try:
            alter = int(alter)
        except (ValueError, TypeError):
            raise ValueError(f"Zeile {nr}: Alter '{z.get('alter')}' ist keine Zahl.") from None
        if not 16 <= alter <= 99:
            raise ValueError(f"Zeile {nr}: Alter {alter} liegt nicht zwischen 16 und 99.")
        sauber["alter"] = alter
    hinweise = []
    if art == "mitarbeitervorschlaege" and sauber["alter"] is not None and sauber["alter"] < 22:
        hinweise.append(f"Zeile {nr}: Alter {sauber['alter']} — Vordruck verlangt ab 22.")
    tel = str(z.get("telefon") or "").strip()
    sauber["chat_id"] = None
    sauber["telefon"] = ""
    if tel:
        chat_id, fehler = normalisiere_empfaenger(tel)
        if chat_id is None:
            hinweise.append(f"Zeile {nr}: Telefon '{tel}' nicht lesbar — ohne Telefon angelegt, bitte prüfen.")
        else:
            sauber["chat_id"], sauber["telefon"] = chat_id, tel
    sauber["firma"] = bool(z.get("firma"))
    return sauber, hinweise
```

Weiter in derselben Datei:

```python
def _anzeigename(z) -> str:
    return " ".join(t for t in (z["vorname"], z["name"]) if t)


def _empfehlung_setzen(lead_id: str, daten: dict) -> None:
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "'{empfehlung}', %s::jsonb, true), updated_at = now() where id = %s returning id",
              (json.dumps(daten, ensure_ascii=False), lead_id))


def _quelle_einwilligung(kopf) -> str:
    return (f"Empfehlung: vorab gefragt von {kopf['empfohlen_von_name']} "
            f"(Liste {kopf['datum']:%d.%m.%Y})")


def _einwilligung(lead_id: str, an: bool, kopf) -> None:
    status = server._q("select consent_status from leads where id = %s", (lead_id,))[0]["consent_status"]
    if an and status not in ("opt_in", "existing_customer"):
        server.einwilligung_erfassen(lead_id, "opt_in", _quelle_einwilligung(kopf))
    elif not an and status == "opt_in":
        server.einwilligung_widerrufen(lead_id, "Empfehlung: Häkchen entfernt")


def _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen: set):
    """-> ('neu'|'verknuepft', lead_id) oder ('abgewiesen', grund)."""
    if z["chat_id"] and z["chat_id"] in gesehen:
        return "abgewiesen", "doppelt in der Liste"
    if z["chat_id"]:
        gesehen.add(z["chat_id"])
    bestehend = server._lead_mit_gleicher_nummer(z["chat_id"]) if z["chat_id"] else None
    if bestehend is not None:
        lid = str(bestehend["id"])
        e = server._q("select enrichment from leads where id = %s", (lid,))[0]["enrichment"] or {}
        if server._privat(e) or server._sammelkontakt(lid):
            return "abgewiesen", "privat markierter Kontakt — nicht verknüpft"
        art = None
        status = "verknuepft"
    else:
        r = json.loads(server.kontakt_anlegen(_anzeigename(z), phone=z["telefon"],
                                              source="empfehlung"))
        if "fehler" in r:
            return "abgewiesen", r["fehler"]
        lid, e, status = str(r["lead_id"]), {}, "neu"
        art = "firma" if z["firma"] else "person"
    if "empfehlung" not in e:
        _empfehlung_setzen(lid, {"liste_id": kopf["id"], "beruf": z["beruf"], "alter": z["alter"],
                                 "ort": z["ort"], "zeichnet_aus": z["zeichnet_aus"],
                                 "interessiert": z["interessiert"], "ergebnis": "offen",
                                 "notiz": "", "einwilligung": bool(einwilligung),
                                 "vorname": z["vorname"], "nachname": z["name"]})
    hinzu = ["bav"] if z["firma"] else list(bereiche)
    server._einordnen(lid, art if status == "neu" else None, hinzu, (), quelle=quelle)
    server._q("insert into activities (lead_id, type, payload) values (%s, 'empfehlung', %s) "
              "returning id", (lid, json.dumps({"liste_id": kopf["id"],
                                                "empfohlen_von_name": kopf["empfohlen_von_name"]},
                                               ensure_ascii=False)))
    if einwilligung:
        _einwilligung(lid, True, kopf)
    return status, lid


def liste_anlegen(art, empfohlen_von_name, datum, zeilen, empfohlen_von_lead=None,
                  berater_name=None, struktur=None, bereiche=(), einwilligung=False,
                  quelle="agent") -> dict:
    if art not in VORDRUCKE:
        return {"fehler": f"Unbekannter Vordruck '{art}' — erlaubt: {', '.join(VORDRUCKE)}."}
    name = " ".join(str(empfohlen_von_name or "").split())
    if not 1 <= len(name) <= NAME_MAX:
        return {"fehler": f"Empfehlungsgeber fehlt oder ist laenger als {NAME_MAX} Zeichen."}
    try:
        tag = date.fromisoformat(str(datum))
    except ValueError:
        return {"fehler": f"Datum '{datum}' ist kein ISO-Datum (JJJJ-MM-TT)."}
    bereiche = list(bereiche or [])
    for b in bereiche:
        if b not in server.BEREICHE:
            return {"fehler": f"Unbekannter Bereich '{b}'."}
    if art == "mitarbeitervorschlaege":
        bereiche = ["mitarbeiter"]
    if not isinstance(zeilen, list) or not zeilen:
        return {"fehler": "Die Liste hat keine Zeilen."}
    if len(zeilen) > VORDRUCKE[art]["max"]:
        return {"fehler": f"Der Vordruck fasst hoechstens {VORDRUCKE[art]['max']} Zeilen."}
    sauber, hinweise = [], []
    try:
        for nr, z in enumerate(zeilen, 1):
            s, h = _zeile_pruefen(nr, z, art)
            sauber.append(s)
            hinweise += h
    except ValueError as e:
        return {"fehler": str(e)}
    lead = _uuid(empfohlen_von_lead) if empfohlen_von_lead else None
    if lead and not server._q("select 1 from leads where id = %s", (lead,)):
        lead = None
    if berater_name is None or struktur is None:
        letzte = server._q("select berater_name, struktur from empfehlungslisten "
                           "order by erstellt_am desc limit 1")
        if berater_name is None:
            berater_name = letzte[0]["berater_name"] if letzte else ""
        if struktur is None:
            struktur = letzte[0]["struktur"] if letzte else ""
    kopf = server._q(
        "insert into empfehlungslisten (art, empfohlen_von_lead, empfohlen_von_name, datum, "
        "berater_name, struktur, bereiche, einwilligung, einwilligung_am) values "
        "(%s, %s, %s, %s, %s, %s, %s::jsonb, %s, case when %s then now() end) "
        "returning id::text as id, empfohlen_von_name, datum",
        (art, lead, name, tag, str(berater_name)[:NAME_MAX], str(struktur)[:NAME_MAX],
         json.dumps(bereiche), bool(einwilligung), bool(einwilligung)))[0]
    zahl = {"neu": 0, "verknuepft": 0}
    abgewiesen, gesehen = [], set()
    for nr, z in enumerate(sauber, 1):
        status, wert = _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen)
        if status == "abgewiesen":
            abgewiesen.append({"zeile": nr, "grund": wert})
        else:
            zahl[status] += 1
            _mitglied_buchen(kopf["id"], wert)
    return {"liste_id": kopf["id"], **zahl, "abgewiesen": abgewiesen, "hinweise": hinweise}
```

Die Zugehörigkeit einer Zeile zur Liste wird unabhängig von `enrichment.empfehlung` gespeichert, denn ein verknüpfter Kontakt mit fremder Empfehlung soll auch in der neuen Liste stehen. Das läuft über die Aktivität `empfehlung` (Nutzlast mit `liste_id`). `_mitglied_buchen` ist deshalb ein No-op-Helfer, `liste()` liest die Mitglieder aus den `empfehlung`-Aktivitäten:

```python
def _mitglied_buchen(liste_id: str, lead_id: str) -> None:
    """Mitgliedschaft steht in der Aktivitaet 'empfehlung' (in _zeile_schreiben
    gebucht) — hier nichts weiter; eigener Name, damit liste_anlegen und
    zeile_hinzufuegen dieselbe Reihenfolge haben."""
    return None


def _mitglieder(liste_id: str) -> list:
    return server._q(
        "select distinct on (a.lead_id) a.lead_id::text as lead_id, a.created_at "
        "from activities a where a.type = 'empfehlung' and a.payload->>'liste_id' = %s "
        "order by a.lead_id, a.created_at", (liste_id,))


def wirksames_ergebnis(lead_id: str, gespeichert: str):
    """(ergebnis, naechster Termin ISO|None): ein nicht abgesagter Kundentermin
    macht aus offen/nicht_erreicht 'termin' — gerechnet, nicht gespeichert."""
    termine = server._q("select payload->>'uid' as uid, payload->>'datum' as datum from activities "
                        "where lead_id = %s and type = 'termin' order by payload->>'datum'",
                        (lead_id,))
    gueltig = [t for t in termine if not server._termin_abgesagt(lead_id, t["uid"])]
    datum = gueltig[-1]["datum"] if gueltig else None
    if gueltig and gespeichert in ("offen", "nicht_erreicht"):
        return "termin", datum
    return gespeichert, datum


def liste(liste_id) -> dict | None:
    lid = _uuid(liste_id)
    if not lid:
        return None
    k = server._q("select id::text as id, art, empfohlen_von_lead::text as empfohlen_von_lead, "
                  "empfohlen_von_name, datum, berater_name, struktur, bereiche, einwilligung, "
                  "einwilligung_am from empfehlungslisten where id = %s", (lid,))
    if not k:
        return None
    zeilen = []
    for m in sorted(_mitglieder(lid), key=lambda m: m["created_at"]):
        l = server._q("select name, phone, enrichment from leads where id = %s", (m["lead_id"],))
        if not l:
            continue
        e = (l[0]["enrichment"] or {}).get("empfehlung") or {}
        ergebnis, termin = wirksames_ergebnis(m["lead_id"], e.get("ergebnis") or "offen")
        zeilen.append({"lead_id": m["lead_id"], "name": l[0]["name"],
                       "vorname": e.get("vorname", ""), "nachname": e.get("nachname", ""),
                       "telefon": l[0]["phone"] or "", "beruf": e.get("beruf", ""),
                       "alter": e.get("alter"), "ort": e.get("ort", ""),
                       "zeichnet_aus": e.get("zeichnet_aus", ""),
                       "interessiert": e.get("interessiert", ""), "ergebnis": ergebnis,
                       "ergebnis_text": ERGEBNISSE.get(ergebnis, ergebnis),
                       "notiz": e.get("notiz", ""), "einwilligung": bool(e.get("einwilligung")),
                       "termin_datum": termin})
    return {"kopf": k[0], "zeilen": zeilen}


def listen() -> list:
    aus = []
    for k in server._q("select id::text as id, art, datum, empfohlen_von_name, "
                       "empfohlen_von_lead::text as empfohlen_von_lead from empfehlungslisten "
                       "order by datum desc, erstellt_am desc"):
        zs = liste(k["id"])["zeilen"]
        aus.append({**k, "anzahl": len(zs),
                    **{s: sum(1 for z in zs if z["ergebnis"] == s)
                       for s in ("offen", "termin", "abschluss")}})
    return aus


def zeile_setzen(lead_id, ergebnis=None, notiz=None, einwilligung=None, quelle="ui") -> dict:
    lid = _uuid(lead_id)
    l = server._q("select enrichment from leads where id = %s", (lid,)) if lid else []
    if not l or "empfehlung" not in (l[0]["enrichment"] or {}):
        return {"fehler": "Kein Kontakt aus einer Empfehlungsliste."}
    e = dict(l[0]["enrichment"]["empfehlung"])
    if ergebnis is not None:
        if ergebnis not in ERGEBNISSE:
            return {"fehler": f"Unbekanntes Ergebnis '{ergebnis}'."}
        e["ergebnis"] = ergebnis
    if notiz is not None:
        if len(notiz) > TEXT_MAX:
            return {"fehler": f"Notiz ist laenger als {TEXT_MAX} Zeichen."}
        e["notiz"] = notiz.strip()
    if einwilligung is not None and bool(einwilligung) != bool(e.get("einwilligung")):
        k = server._q("select empfohlen_von_name, datum from empfehlungslisten where id = %s",
                      (e["liste_id"],))
        if k:
            _einwilligung(lid, bool(einwilligung), k[0])
        e["einwilligung"] = bool(einwilligung)
    _empfehlung_setzen(lid, e)
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'empfehlung_geaendert', %s, %s) returning id",
              (lid, json.dumps({k: e[k] for k in ("ergebnis", "notiz", "einwilligung")},
                               ensure_ascii=False), "human" if quelle == "ui" else "agent"))
    return {"lead_id": lid, "ergebnis": e["ergebnis"], "notiz": e["notiz"],
            "einwilligung": e["einwilligung"]}


def zeile_hinzufuegen(liste_id, zeile, quelle="ui") -> dict:
    l = liste(liste_id)
    if l is None:
        return {"fehler": "Diese Liste gibt es nicht."}
    if len(l["zeilen"]) >= ZEILEN_HART_MAX:
        return {"fehler": f"Eine Liste fasst hoechstens {ZEILEN_HART_MAX} Zeilen."}
    k = l["kopf"]
    try:
        s, hinweise = _zeile_pruefen(len(l["zeilen"]) + 1, zeile, k["art"])
    except ValueError as e:
        return {"fehler": str(e)}
    gesehen = {normalisiere_empfaenger(z["telefon"])[0] for z in l["zeilen"] if z["telefon"]}
    status, wert = _zeile_schreiben(k, s, k["bereiche"] or [], k["einwilligung"], quelle, gesehen)
    if status == "abgewiesen":
        return {"fehler": wert}
    return {"lead_id": wert, "status": status, "hinweise": hinweise}
```

Hinweise:
- `kontakt_anlegen` liefert bei bekannter Nummer `angelegt: False` mit der lead_id. Der Fall wird vorher über `_lead_mit_gleicher_nummer` abgefangen.
- `kontakt_anlegen(name, phone="")` mit leerem Telefon ist erlaubt.
- Nach dem `kontakt_anlegen` setzt C1 die Art per Klammer-Regel. Der folgende `_einordnen`-Aufruf mit expliziter Art überschreibt das (Firmenzeile → firma).
- `zeile_setzen` nennt in der Fehlermeldung bewusst nur „Kontakt aus einer Empfehlungsliste“, Verknüpfte ohne eigene `empfehlung` sind nicht editierbar. Der Test „fremde Empfehlung bleibt“ prüft nur die Zugehörigkeit.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py`. Expected: alle grün. Schlägt ein Test wegen einer abweichenden Helfer-Signatur fehl (`einwilligung_widerrufen`, `_lead_mit_gleicher_nummer`), den Aufruf an die echte Signatur anpassen, nicht den Test.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/empfehlungen.py sales-mcp/tests/test_empfehlungen.py
git commit -m "feat(empfehlungen): Kern fuer Pole Position und Mitarbeitervorschlaege"
```

---

### Task 3: PDF im Vordruck-Aufbau

**Files:**
- Modify: `sales-mcp/empfehlungen.py` (Funktion `pdf`)
- Test: `sales-mcp/tests/test_empfehlungen.py` (anhängen)

**Interfaces:**
- Consumes: `liste(liste_id)` (Task 2), `formular._druckbar`, `formular._zeilen`.
- Produces: `pdf(liste_id) -> bytes | None` (None bei unbekannter Liste)

- [ ] **Step 1: Failing tests** (anhängen)

```python
import io as _io
from pypdf import PdfReader


def _pdf_text(b):
    return "".join(s.extract_text() for s in PdfReader(_io.BytesIO(b)).pages)


def test_pdf_pole_position_quer_mit_kopf_und_spalten():
    r = _anlegen(art="pole_position", bereiche=["vorsorge"],
                 zeilen=[Z(vorname="Jörg", name="Müßig <script>", ort="München")])
    b = em.pdf(r["liste_id"])
    seiten = PdfReader(_io.BytesIO(b)).pages
    assert len(seiten) == 1 and seiten[0].mediabox.width > seiten[0].mediabox.height
    t = _pdf_text(b)
    for s in ("Pole Position", "Konzept für den Aufbau von Empfehlungen", "Name", "Vorname",
              "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis", "Felix", "Team Nord",
              "Klaus Kunde", "Jörg", "München", "offen"):
        assert s in t, s


def test_pdf_mitarbeitervorschlaege_spalten_und_folgeseite():
    r = _anlegen(zeilen=[Z(vorname=f"P{i}", telefon="") for i in range(25)])
    em.zeile_hinzufuegen(r["liste_id"], Z(vorname="Nummer26", telefon=""))
    b = em.pdf(r["liste_id"])
    assert len(PdfReader(_io.BytesIO(b)).pages) == 2
    t = _pdf_text(b)
    for s in ("Mitarbeitervorschläge", "Alter (ab 22)", "Was zeichnet aus", "Was interessiert",
              "Nummer26"):
        assert s in t, s


def test_pdf_unbekannt():
    assert em.pdf("00000000-0000-0000-0000-000000000000") is None
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py -k pdf`. Expected: FAIL (`AttributeError: pdf`)

- [ ] **Step 3: Implementieren** (in `empfehlungen.py`)

```python
import io

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

import formular

_SPALTEN = {
    # (Ueberschrift, Breite mm, Feld) — Reihenfolge wie der Papier-Vordruck
    "pole_position": [("Name", 34, "nachname"), ("Vorname", 30, "vorname"),
                      ("Beruf", 34, "beruf"), ("Alter", 13, "alter"), ("Ort", 30, "ort"),
                      ("Telefon", 36, "telefon"), ("Termin", 24, "termin_datum"),
                      ("Ergebnis", 50, "ergebnis_text")],
    "mitarbeitervorschlaege": [("Vorname, Name", 46, "name"), ("Alter (ab 22)", 20, "alter"),
                               ("Beruf", 32, "beruf"), ("Telefon", 34, "telefon"),
                               ("Was zeichnet aus", 52, "zeichnet_aus"),
                               ("Was interessiert", 52, "interessiert"),
                               ("Termin", 24, "termin_datum")],
}
_ZEILE_H = 9 * mm
_PT = 8


def _zelle(z, feld) -> str:
    w = z.get(feld)
    if feld == "termin_datum" and w:
        return f"{w[8:10]}.{w[5:7]}.{w[0:4]}"
    return "" if w is None else str(w)


def pdf(liste_id) -> bytes | None:
    l = liste(liste_id)
    if l is None:
        return None
    k, art = l["kopf"], l["kopf"]["art"]
    vd, spalten = VORDRUCKE[art], _SPALTEN[art]
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=landscape(A4))
    breite, hoehe = landscape(A4)
    links = (breite - sum(s[1] for s in spalten) * mm) / 2
    zeilen = list(l["zeilen"])
    seiten_zeilen = []
    while zeilen or not seiten_zeilen:
        seiten_zeilen.append(zeilen[:vd["max"]])
        zeilen = zeilen[vd["max"]:]
    for teil in seiten_zeilen:
        y = hoehe - 18 * mm
        c.setFont(formular.FETT, 18)
        c.drawCentredString(breite / 2, y, formular._druckbar(vd["titel"]))
        if vd["untertitel"]:
            y -= 7 * mm
            c.setFont(formular.SCHRIFT, 12)
            c.drawCentredString(breite / 2, y, formular._druckbar(vd["untertitel"]))
        y -= 9 * mm
        c.setFont(formular.SCHRIFT, 10)
        kopf = (f"Name: {k['berater_name']}    Struktur: {k['struktur']}    "
                f"Empfohlen von: {k['empfohlen_von_name']}    Datum: {k['datum']:%d.%m.%Y}")
        c.drawString(links, y, formular._druckbar(kopf))
        y -= 8 * mm
        x = links + 8 * mm
        c.setFont(formular.FETT, _PT)
        for titel, b, _ in spalten:
            c.rect(x, y - _ZEILE_H, b * mm, _ZEILE_H)
            c.drawString(x + 1.5 * mm, y - 6 * mm, formular._druckbar(titel))
            x += b * mm
        y -= _ZEILE_H
        c.setFont(formular.SCHRIFT, _PT)
        for nr in range(vd["max"]):
            z = teil[nr] if nr < len(teil) else {}
            c.drawRightString(links + 6 * mm, y - 6 * mm, f"{nr + 1}.")
            x = links + 8 * mm
            for _, b, feld in spalten:
                c.rect(x, y - _ZEILE_H, b * mm, _ZEILE_H)
                text = formular._druckbar(_zelle(z, feld)) if z else ""
                zeilen_txt = formular._zeilen(text, b * mm - 3 * mm, _PT)[:2] if text else []
                for i, t in enumerate(zeilen_txt):
                    c.drawString(x + 1.5 * mm, y - 4 * mm - i * 3.4 * mm, t)
                x += b * mm
            y -= _ZEILE_H
        c.showPage()
    c.save()
    return puffer.getvalue()
```

Prüfen:
- Die Signatur von `formular._zeilen(text, breite, pt)`: Liefert sie eine Liste von Zeilen? Sonst anpassen.
- `formular.FETT` und `formular.SCHRIFT` sind die Modulkonstanten.
- Bei Mitarbeitervorschlägen steht „Vorname, Name“ aus `name` (der Anzeigename „Vorname Name“).
- Bei Pole Position kommen Name und Vorname aus `nachname`/`vorname`. Sind beide leer, weil der Kontakt nur verknüpft wurde, wird `name` in die Spalte „Name“ gesetzt: `_zelle` mit Fallback `z.get("name")` für `nachname`, wenn `vorname` und `nachname` leer sind.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py`. Expected: alle grün.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/empfehlungen.py sales-mcp/tests/test_empfehlungen.py
git commit -m "feat(empfehlungen): PDF im Aufbau des Papier-Vordrucks"
```

---

### Task 4: Agent — Werkzeuge, Skill, Prompt

**Files:**
- Modify: `sales-mcp/server.py`: zwei Werkzeuge nach `kontakt_einordnen`, dazu `WERKZEUGE`
- Modify: `sales-mcp/tests/test_werkzeuge.py` (94 → 96), `sales-mcp/tests/test_recherche.py` (veralteter Zähler, siehe unten)
- Create: `config/workspace/skills/empfehlungsliste/SKILL.md`
- Modify: `config/workspace/AGENTS.md` (Verweis + Tabu-Liste)
- Create: `sales-mcp/tests/test_skill_empfehlungsliste.py`
- Modify: `sales-mcp/tests/test_agents_regeln.py`

**Interfaces:**
- Consumes: `empfehlungen.liste_anlegen`, `empfehlungen.listen`, `empfehlungen.liste` (Task 2).
- Produces:
  - `server.empfehlungsliste_anlegen(art: str, empfohlen_von: str, datum: str, zeilen: list, einwilligung: bool, bereiche: list | None = None, berater_name: str = "", struktur: str = "") -> str`
  - `server.empfehlungslisten_zeigen(liste_id: str = "") -> str`

- [ ] **Step 1: Failing tests**

`tests/test_empfehlungen.py` (anhängen):

```python
import inspect


def test_werkzeuge_registriert():
    for f, p in ((server.empfehlungsliste_anlegen,
                  ["art", "empfohlen_von", "datum", "zeilen", "einwilligung", "bereiche",
                   "berater_name", "struktur"]),
                 (server.empfehlungslisten_zeigen, ["liste_id"])):
        assert f in server.WERKZEUGE
        assert list(inspect.signature(f).parameters) == p


def test_werkzeug_empfohlen_von_lead_oder_name():
    geber = json.loads(server.kontakt_anlegen("Klaus Kunde", phone="+491705555555"))["lead_id"]
    r = json.loads(server.empfehlungsliste_anlegen("mitarbeitervorschlaege", geber, HEUTE,
                                                   [Z()], False))
    k = em.liste(r["liste_id"])["kopf"]
    assert k["empfohlen_von_lead"] == geber and k["empfohlen_von_name"] == "Klaus Kunde"
    r2 = json.loads(server.empfehlungsliste_anlegen("pole_position", "Frau Nachbarin", HEUTE,
                                                    [Z(telefon="")], True, ["immobilien"],
                                                    "Felix", "Nord"))
    assert em.liste(r2["liste_id"])["kopf"]["empfohlen_von_lead"] is None
    z = json.loads(server.empfehlungslisten_zeigen())
    assert len(z["listen"]) == 2
    d = json.loads(server.empfehlungslisten_zeigen(r2["liste_id"]))
    assert d["kopf"]["empfohlen_von_name"] == "Frau Nachbarin" and len(d["zeilen"]) == 1
```

`tests/test_skill_empfehlungsliste.py` (Name prüfen):

```python
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2] / "config" / "workspace" / "skills"
         / "empfehlungsliste" / "SKILL.md")


def test_skill_pflichtschritte():
    t = SKILL.read_text(encoding="utf-8")
    kopf = t.split("---")[1]
    assert "Pole Position" in kopf and "Mitarbeitervorschl" in kopf
    for s in ("(?)", "alle gefragt", "empfehlungsliste_anlegen(", "Nichts raten",
              "nie von sich aus"):
        assert s in t, s
    assert t.index("alle gefragt") < t.index("empfehlungsliste_anlegen(")
```

`tests/test_agents_regeln.py`:

```python
def test_empfehlungslisten_im_prompt_und_tabu():
    assert "Skill `empfehlungsliste`" in TEXT
    tabu = _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
    assert "`empfehlungsliste_anlegen`" in tabu and "`empfehlungslisten_zeigen`" in tabu
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py -k werkzeug tests/test_skill_empfehlungsliste.py tests/test_agents_regeln.py`. Expected: FAIL

- [ ] **Step 3: Werkzeuge** (`server.py`, nach `kontakt_einordnen`; `import empfehlungen` lokal in der Funktion gegen Zirkelimport)

```python
@_gesichert
def empfehlungsliste_anlegen(art: str, empfohlen_von: str, datum: str, zeilen: list,
                             einwilligung: bool, bereiche: list | None = None,
                             berater_name: str = "", struktur: str = "") -> str:
    """Empfehlungsliste anlegen — Vordruck art 'pole_position' (max 15) oder
    'mitarbeitervorschlaege' (max 25). empfohlen_von: lead_id des
    Empfehlungsgebers oder sein Name. zeilen: [{vorname, name, beruf, alter,
    ort, telefon, zeichnet_aus, interessiert, firma: bool}]. einwilligung:
    hat der Empfehlungsgeber ALLE gefragt, ob der Betreiber sich melden darf
    (nur dann wird sie gebucht). bereiche (nur Pole Position): bav,
    mitarbeiter, vorsorge, immobilien, it, homelab. berater_name/struktur leer
    = von der letzten Liste uebernehmen. NUR nach Ok des Betreibers zur
    gezeigten Vorschau. Sendet nichts."""
    import empfehlungen
    lead = None
    try:
        lead = str(uuid.UUID(str(empfohlen_von)))
    except ValueError:
        pass
    name = empfohlen_von
    if lead:
        z = _q("select name from leads where id = %s", (lead,))
        if z:
            name = z[0]["name"]
        else:
            lead = None
    return _json(empfehlungen.liste_anlegen(
        art, name, datum, zeilen, empfohlen_von_lead=lead,
        berater_name=berater_name or None, struktur=struktur or None,
        bereiche=bereiche or [], einwilligung=bool(einwilligung), quelle="agent"))


@_gesichert
def empfehlungslisten_zeigen(liste_id: str = "") -> str:
    """Ohne liste_id: Uebersicht aller Empfehlungslisten (Datum, Vordruck,
    Empfehlungsgeber, Anzahl, offen/Termin/Abschluss). Mit liste_id: Kopf und
    Zeilen dieser Liste. Liest nur."""
    import empfehlungen
    if not liste_id:
        return _json({"listen": empfehlungen.listen()})
    l = empfehlungen.liste(liste_id)
    return _json(l if l else {"fehler": "Diese Liste gibt es nicht."})
```

`WERKZEUGE`: Beide nach `kontakt_einordnen` eintragen, mit Kommentar `# Empfehlungslisten (17.10.2026), Vertraege: tests/test_empfehlungen.py.`. In `tests/test_werkzeuge.py` den Changelog `# 17.10.2026: empfehlungsliste_anlegen, empfehlungslisten_zeigen (C4), 94 -> 96.` ergänzen und `== 96` setzen. Prüfen, ob `tests/test_recherche.py::test_beide_werkzeuge_sind_registriert` eine Gesamtzahl prüft (vorbestehend rot mit 91). Falls ja, auf `len(server.WERKZEUGE) == 96` nachziehen und das im Report nennen.

- [ ] **Step 4: Skill** (`config/workspace/skills/empfehlungsliste/SKILL.md`, vollständig)

```markdown
---
name: empfehlungsliste
description: "Empfehlungsliste erfassen — IMMER nutzen bei Foto oder Diktat einer Pole Position (Konzept fuer den Aufbau von Empfehlungen) oder einer Liste Mitarbeitervorschlaege, oder wenn der Betreiber 'Empfehlungen' bzw. eine 'Wen kennst du'-Liste erfassen will. Ablauf: lesen, Vorschau mit (?), EINE gesammelte Rueckfrage, erst nach Ok anlegen."
metadata: { "openclaw": { "emoji": "📋" } }
---

# Empfehlungsliste — der Ablauf

## Schritt 1 — Lesen

Lies das Foto Zeile fuer Zeile. Zeig die Zeilen nummeriert im Chat:
„1. Vorname Name · Beruf · Alter · Ort · Telefon · (Pole Position) /
Was zeichnet aus · Was interessiert (Mitarbeitervorschlaege)".
Unsichere Felder bekommen ein „(?)". Nichts raten: Unleserliches bleibt leer
und wird genannt.

## Schritt 2 — EINE gesammelte Rueckfrage

1. Welcher Vordruck: Pole Position oder Mitarbeitervorschlaege?
2. Wer hat die Liste gegeben (Name; gibt es ihn im CRM, nimm seine lead_id)?
   Welches Datum?
3. Hat dieser Mensch alle gefragt, ob du dich bei ihnen melden darfst?
   (Ja → Einwilligung fuer alle Zeilen, Nein → keine.)
4. Nur Pole Position: Fuer welche Bereiche ist die Liste (vorsorge,
   immobilien, mitarbeiter, bav …)? Welche Zeilen sind Firmen (die werden
   Firma mit bAV)?
5. Korrekturen an den gelesenen Zeilen?
6. Nur beim allerersten Mal: Name und Struktur fuer den Listenkopf (danach
   werden sie von der letzten Liste uebernommen).

## Schritt 3 — Anlegen, erst nach Ok

`empfehlungsliste_anlegen(art, empfohlen_von, datum, zeilen, einwilligung,
bereiche, berater_name, struktur)` — dann EIN Satz: „Liste angelegt: N neu,
M schon bekannt, K abgewiesen (Grund)", dazu Hinweise (Telefon pruefen,
Alter unter 22) und den Link `/empfehlungen/<liste_id>`.

## Danach

Empfohlene werden nie von sich aus angeschrieben. Ein Entwurf entsteht nur
auf ausdruecklichen Zuruf des Betreibers und nur, wenn die Einwilligung
gebucht ist — wie bei allen Kontakten. Uebersicht und Stand:
`empfehlungslisten_zeigen()`.
```

- [ ] **Step 5: AGENTS.md.** Im Abschnitt `## Einordnung (Art und Bereiche)` (C1) am Ende einen Absatz anhängen:
`Empfehlungslisten (Pole Position, Mitarbeitervorschlaege) erfasst der Skill `empfehlungsliste` — Foto oder Diktat, Vorschau, eine Rueckfrage, erst dann `empfehlungsliste_anlegen`.`
In der Tabu-Liste `` `kontakt_einordnen` sowie jede Recherche `` ersetzen durch `` `kontakt_einordnen`, `empfehlungsliste_anlegen`, `empfehlungslisten_zeigen` sowie jede Recherche ``.

- [ ] **Step 6: Grün sehen.** Run: `python -m pytest -q tests/test_empfehlungen.py tests/test_werkzeuge.py tests/test_skill_empfehlungsliste.py tests/test_agents_regeln.py tests/test_recherche.py`. Expected: grün bis auf die bekannten Roten.

- [ ] **Step 7: Commit**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_empfehlungen.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py sales-mcp/tests/test_skill_empfehlungsliste.py sales-mcp/tests/test_agents_regeln.py config/workspace/skills/empfehlungsliste/SKILL.md config/workspace/AGENTS.md
git commit -m "feat(agent): Empfehlungslisten per Werkzeug und Skill erfassen"
```

---

### Task 5: Oberfläche `/empfehlungen`

**Files:**
- Create: `sales-mcp/ui_empfehlungen.py`
- Modify: `sales-mcp/ui.py`: `import ui_empfehlungen` neben `import ui_kalender` (~209); `*ui_empfehlungen.routen(sys.modules[__name__]),` neben dem Kalender in der Route-Liste (~6926); Nav-Eintrag `("/empfehlungen", "Empfehlungen")` in `_GRUPPEN` „Analyse“ hinter „Kontakte“ (~1409)
- Create: `sales-mcp/tests/test_ui_empfehlungen.py` (Name prüfen)

**Interfaces:**
- Consumes: `empfehlungen.listen/liste/zeile_setzen/zeile_hinzufuegen/pdf/ERGEBNISSE/VORDRUCKE` (Tasks 2/3); `ui._seite`, `ui._e`, `ui._tabelle`, `ui._fehlerseite`, `ui._gesichert_seite`, `ui._kontakt_vorspann`, `ui._AKTIVE_ROLLE`, `ui.CSRF_TOKEN`.
- Produces:
  - GET `/empfehlungen`
  - GET `/empfehlungen/{liste_id}`
  - GET `/empfehlungen/{liste_id}/pdf`
  - POST `/empfehlungen/zeile` (Form: `csrf`, `lead_id`, `liste_id`, `ergebnis`, `notiz`, `einwilligung`=1|leer)
  - POST `/empfehlungen/{liste_id}/zeile` (Form: `csrf`, `vorname`, `name`, `beruf`, `alter`, `ort`, `telefon`, `zeichnet_aus`, `interessiert`, `firma`=1|leer)

- [ ] **Step 1: Failing tests** (`tests/test_ui_empfehlungen.py`; Setup wie `tests/test_ui.py`: Schema `sales_test`, `CLIENT = TestClient(ui.app)`, Host `127.0.0.1:8791`, truncate inkl. `sales_test.empfehlungslisten`)

```python
import os
from datetime import date

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import empfehlungen as em  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST = {"host": "127.0.0.1:8791"}


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.empfehlungslisten, sales_test.activities, "
                     "sales_test.drafts, sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")


def _liste(**kw):
    a = dict(art="pole_position", empfohlen_von_name="Klaus <b>Kunde</b>",
             datum=date.today().isoformat(), berater_name="Felix", struktur="Nord",
             zeilen=[{"vorname": "Anna", "name": "Beispiel <script>x</script>",
                      "telefon": "+491701234567", "beruf": "Ärztin"}])
    a.update(kw)
    return em.liste_anlegen(**a)


def _get(p):
    return CLIENT.get(p, headers=HOST)


def _post(p, d):
    return CLIENT.post(p, data=d, headers=HOST, follow_redirects=False)


def test_uebersicht_und_liste_escaped():
    r = _liste()
    u = _get("/empfehlungen").text
    assert "Pole Position" in u and "&lt;b&gt;Kunde&lt;/b&gt;" in u and "<b>Kunde</b>" not in u
    s = _get(f"/empfehlungen/{r['liste_id']}")
    assert s.status_code == 200
    assert "&lt;script&gt;" in s.text and "<script>x" not in s.text
    for spalte in ("Name", "Vorname", "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis"):
        assert spalte in s.text
    assert f'/kalender?neu=kunde&amp;lead_id=' in s.text


def test_zeile_speichern_und_csrf():
    r = _liste()
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    d = {"lead_id": lid, "liste_id": r["liste_id"], "ergebnis": "nicht_erreicht",
         "notiz": "Mailbox", "einwilligung": "1"}
    assert _post("/empfehlungen/zeile", d).status_code == 403
    a = _post("/empfehlungen/zeile", {**d, "csrf": ui.CSRF_TOKEN})
    assert a.status_code == 303
    z = em.liste(r["liste_id"])["zeilen"][0]
    assert z["ergebnis"] == "nicht_erreicht" and z["notiz"] == "Mailbox" and z["einwilligung"]
    bad = _post("/empfehlungen/zeile", {**d, "csrf": ui.CSRF_TOKEN, "ergebnis": "quatsch"})
    assert bad.status_code == 422


def test_zeile_hinzufuegen_ui():
    r = _liste()
    a = _post(f"/empfehlungen/{r['liste_id']}/zeile",
              {"csrf": ui.CSRF_TOKEN, "vorname": "Neu", "name": "Mensch", "telefon": ""})
    assert a.status_code == 303 and len(em.liste(r["liste_id"])["zeilen"]) == 2
    assert _post(f"/empfehlungen/{r['liste_id']}/zeile",
                 {"csrf": ui.CSRF_TOKEN, "vorname": "", "name": ""}).status_code == 422


def test_pdf_route_und_404():
    r = _liste()
    p = _get(f"/empfehlungen/{r['liste_id']}/pdf")
    assert p.status_code == 200 and p.headers["content-type"].startswith("application/pdf")
    assert p.content[:4] == b"%PDF"
    assert _get("/empfehlungen/00000000-0000-0000-0000-000000000000").status_code == 404
    assert _get("/empfehlungen/kaputt").status_code == 404
    assert _get("/empfehlungen/00000000-0000-0000-0000-000000000000/pdf").status_code == 404


def test_nav_und_rolle_kalender_kein_zugriff():
    assert ui._pfad_erlaubt("kalender", "/empfehlungen") is False
    assert '/empfehlungen' in _get("/kontakte").text


def test_rolle_lesen_ohne_formulare(monkeypatch):
    r = _liste()
    monkeypatch.setattr(ui._AKTIVE_ROLLE, "get", lambda *a: "lesen", raising=False)
    s = _get(f"/empfehlungen/{r['liste_id']}").text
    assert 'action="/empfehlungen/zeile"' not in s
```

(Lässt sich `_AKTIVE_ROLLE` so nicht patchen, weil `_gesichert_seite` die Rolle aus dem Scope neu setzt, den Rollen-Test mit dem Anmelde-Muster aus `tests/test_ui_kalender.py` (`_anmelden`, `scharf`) bauen.)

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_ui_empfehlungen.py`. Expected: FAIL (404)

- [ ] **Step 3: Implementieren** (`sales-mcp/ui_empfehlungen.py`)

```python
"""Oberflaeche der Empfehlungslisten (C4): Uebersicht, Liste, PDF, Zeilen."""
import uuid

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import empfehlungen as em

_FELDER_ZEILE = ("vorname", "name", "beruf", "alter", "ort", "telefon",
                 "zeichnet_aus", "interessiert")


def _uuid(w):
    try:
        return str(uuid.UUID(str(w)))
    except (ValueError, TypeError):
        return None


def routen(ui):
    e = ui._e

    @ui._gesichert_seite
    async def uebersicht(request):
        zeilen = [[
            e(f"{l['datum']:%d.%m.%Y}"),
            f'<a href="/empfehlungen/{e(l["id"])}">{e(em.VORDRUCKE[l["art"]]["titel"])}</a>',
            (f'<a href="/kontakte/{e(l["empfohlen_von_lead"])}">{e(l["empfohlen_von_name"])}</a>'
             if l["empfohlen_von_lead"] else e(l["empfohlen_von_name"])),
            e(l["anzahl"]), e(l["offen"]), e(l["termin"]), e(l["abschluss"])]
            for l in em.listen()]
        rumpf = (ui._tabelle(["Datum", "Vordruck", "Empfohlen von", "Anzahl", "offen",
                              "Termin", "Abschluss"], zeilen) if zeilen else
                 '<p class="meta">Noch keine Liste. Schick dem Agenten ein Foto einer '
                 'Pole Position oder einer Liste Mitarbeitervorschläge.</p>')
        return ui._seite("Empfehlungen", rumpf)

    @ui._gesichert_seite
    async def seite(request):
        lid = _uuid(request.path_params["liste_id"])
        l = em.liste(lid) if lid else None
        if l is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Liste gibt es nicht.")
        k, art = l["kopf"], l["kopf"]["art"]
        schreiben = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
        datum_text = f"{k['datum']:%d.%m.%Y}"
        kopf = (f'<p class="meta">{e(em.VORDRUCKE[art]["untertitel"])}</p>'
                f'<p>Empfohlen von <b>{e(k["empfohlen_von_name"])}</b> · '
                f'{e(datum_text)} · '
                f'Name: {e(k["berater_name"])} · Struktur: {e(k["struktur"])} · '
                f'Einwilligung: {"ja" if k["einwilligung"] else "nein"}</p>'
                f'<p><a href="/empfehlungen/{e(lid)}/pdf">PDF</a></p>')
        spalten = (["Name", "Vorname", "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis"]
                   if art == "pole_position" else
                   ["Vorname, Name", "Alter (ab 22)", "Beruf", "Telefon", "Was zeichnet aus",
                    "Was interessiert", "Termin", "Ergebnis"])
        zeilen = []
        for z in l["zeilen"]:
            name = f'<a href="/kontakte/{e(z["lead_id"])}">{e(z["nachname"] or z["name"])}</a>'
            termin = (e(f"{z['termin_datum'][8:10]}.{z['termin_datum'][5:7]}.") if z["termin_datum"]
                      else (f'<a href="/kalender?neu=kunde&amp;lead_id={e(z["lead_id"])}">Termin</a>'
                            if schreiben else ""))
            if schreiben:
                auswahl = "".join(
                    f'<option value="{s}"{" selected" if s == z["ergebnis"] else ""}>{e(t)}</option>'
                    for s, t in em.ERGEBNISSE.items())
                ergebnis = (f'<form method="post" action="/empfehlungen/zeile">'
                            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
                            f'<input type="hidden" name="lead_id" value="{e(z["lead_id"])}">'
                            f'<input type="hidden" name="liste_id" value="{e(lid)}">'
                            f'<select name="ergebnis">{auswahl}</select> '
                            f'<input name="notiz" maxlength="200" value="{e(z["notiz"])}" placeholder="Notiz"> '
                            f'<label><input type="checkbox" name="einwilligung" value="1"'
                            f'{" checked" if z["einwilligung"] else ""}> darf kontaktiert werden</label> '
                            f'<button type="submit">Speichern</button></form>')
            else:
                ergebnis = e(z["ergebnis_text"]) + (f" · {e(z['notiz'])}" if z["notiz"] else "")
            if art == "pole_position":
                zeilen.append([name, e(z["vorname"]), e(z["beruf"]), e(z["alter"] or ""),
                               e(z["ort"]), e(z["telefon"]), termin, ergebnis])
            else:
                zeilen.append([name, e(z["alter"] or ""), e(z["beruf"]), e(z["telefon"]),
                               e(z["zeichnet_aus"]), e(z["interessiert"]), termin, ergebnis])
        neu = ""
        if schreiben:
            felder = "".join(f'<input name="{f}" placeholder="{f}" maxlength="200"> '
                             for f in _FELDER_ZEILE)
            neu = (f'<h2>Zeile hinzufügen</h2><div class="karte"><form method="post" '
                   f'action="/empfehlungen/{e(lid)}/zeile">'
                   f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">{felder}'
                   f'<label><input type="checkbox" name="firma" value="1"> Firma</label> '
                   f'<button type="submit">Hinzufügen</button></form></div>')
        return ui._seite(em.VORDRUCKE[art]["titel"], kopf + ui._tabelle(spalten, zeilen) + neu)

    @ui._gesichert_seite
    async def pdf(request):
        lid = _uuid(request.path_params["liste_id"])
        b = em.pdf(lid) if lid else None
        if b is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Diese Liste gibt es nicht.")
        return Response(b, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="empfehlungsliste-{lid[:8]}.pdf"'})

    @ui._gesichert_seite
    async def zeile(request):
        form, lead_id, abbruch = await ui._kontakt_vorspann(request)
        if abbruch:
            return abbruch
        r = em.zeile_setzen(lead_id, ergebnis=str(form.get("ergebnis") or "offen"),
                            notiz=str(form.get("notiz") or "")[:200],
                            einwilligung=form.get("einwilligung") == "1", quelle="ui")
        if "fehler" in r:
            return ui._fehlerseite(422, "Nicht gespeichert", e(r["fehler"]))
        lid = _uuid(form.get("liste_id"))
        return RedirectResponse(f"/empfehlungen/{lid}" if lid else "/empfehlungen", status_code=303)

    @ui._gesichert_seite
    async def zeile_neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgelehnt", "Fehlende oder falsche CSRF-Marke.")
        lid = _uuid(request.path_params["liste_id"])
        z = {f: str(form.get(f) or "") for f in _FELDER_ZEILE}
        z["firma"] = form.get("firma") == "1"
        r = em.zeile_hinzufuegen(lid, z, quelle="ui") if lid else {"fehler": "Liste unbekannt."}
        if "fehler" in r:
            return ui._fehlerseite(422, "Nicht hinzugefügt", e(r["fehler"]))
        return RedirectResponse(f"/empfehlungen/{lid}", status_code=303)

    return [
        Route("/empfehlungen", uebersicht),
        Route("/empfehlungen/zeile", zeile, methods=["POST"]),
        Route("/empfehlungen/{liste_id}/pdf", pdf),
        Route("/empfehlungen/{liste_id}/zeile", zeile_neu, methods=["POST"]),
        Route("/empfehlungen/{liste_id}", seite),
    ]
```

Prüfen:
- `_csrf_ok(form)` heißt in ui.py genau so.
- `_kontakt_vorspann` gibt bei fehlender CSRF eine 403-Seite zurück.
- `_tabelle` erwartet bereits escapte Zellen: Alles oben ist escaped, die Formulare sind bewusst HTML.

- [ ] **Step 4: Einhängen** in ui.py (Import, Routen, Nav wie unter Files). Steht die Route-Liste in ui.py vor einem allgemeinen Catch-all, die Empfehlungs-Routen davor einfügen.

- [ ] **Step 5: Grün sehen.** Run: `python -m pytest -q tests/test_ui_empfehlungen.py tests/test_ui.py tests/test_kontakte_liste.py`. Expected: grün.

- [ ] **Step 6: Commit**

```bash
git add sales-mcp/ui_empfehlungen.py sales-mcp/ui.py sales-mcp/tests/test_ui_empfehlungen.py
git commit -m "feat(ui): Empfehlungslisten fuehren und als PDF ausgeben"
```

---

### Task 6: Kalender öffnet den Kundentermin-Dialog vorbelegt

**Files:**
- Modify: `sales-mcp/ui_kalender.py`: `seite` (~246-269). Bei `?neu=kunde&lead_id=<uuid>` eines existierenden, nicht privaten Kontakts kommt `start["neu_kunde"] = {"lead_id", "name"}` dazu.
- Modify: `kalender/src/main.ts` (Interface `Start` ~18-25, `starten` ~92-137): Nach dem Rendern `anlegenOeffnen(...)` mit der Vorgabe öffnen.
- Modify: `kalender/src/fenster.ts`: `Vorgabe` (~188-193) um `art?: 'eigen'|'kunde'` und `kunde?: {lead_id: string, name: string}` erweitern. `formular` (~195) wählt dann `artKunde` vor und füllt die Kundenauswahl. `anlegenOeffnen(start, ende, ganztags, ctx, vorgabe?)` reicht die Vorgabe durch.
- Test: `kalender/src/fenster.test.ts` (vitest), `sales-mcp/tests/test_ui_kalender.py`
- Build: `cd kalender && npm run build` (schreibt `sales-mcp/static/kalender/`)

**Interfaces:**
- Consumes: Link `/kalender?neu=kunde&lead_id=<id>` (Task 5).

- [ ] **Step 1: Failing tests**

`tests/test_ui_kalender.py` (anhängen, Helfer der Datei nutzen):

```python
def test_start_mit_neu_kunde_vorbelegung():
    lead = server._q("insert into leads (name) values ('Anna Vorbelegt') returning id")[0]["id"]
    s = _start(_get(f"/kalender?neu=kunde&lead_id={lead}").text)
    assert s["neu_kunde"] == {"lead_id": str(lead), "name": "Anna Vorbelegt"}
    assert "neu_kunde" not in _start(_get("/kalender?neu=kunde&lead_id=kaputt").text)
    assert "neu_kunde" not in _start(_get(
        "/kalender?neu=kunde&lead_id=00000000-0000-0000-0000-000000000000").text)
```

`kalender/src/fenster.test.ts` (im Stil der Datei, die mit jsdom bzw. happy-dom das Formular rendert):

```ts
it('Vorgabe kunde waehlt Kundentermin und den Kontakt vor', () => {
  const ctx = testKontext()          // Helfer der Datei; sonst minimalen Kontext bauen
  anlegenOeffnen(new Date('2026-10-20T10:00:00'), new Date('2026-10-20T11:00:00'), false, ctx,
                 { art: 'kunde', kunde: { lead_id: 'abc', name: 'Anna Vorbelegt' } })
  const kunde = document.querySelector<HTMLInputElement>('input[value="kunde"]')!
  expect(kunde.checked).toBe(true)
  expect(document.body.textContent).toContain('Anna Vorbelegt')
})
```

(Heißt der Kontext-Helfer in `fenster.test.ts` anders, den vorhandenen nehmen.)

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_ui_kalender.py -k neu_kunde` und `cd kalender && npx vitest run src/fenster.test.ts`. Expected: beide FAIL

- [ ] **Step 3: Implementieren.**

`ui_kalender.seite` (nach dem Bau von `start`):

```python
        if request.query_params.get("neu") == "kunde" and darf_schreiben_rolle:
            try:
                lid = str(uuid.UUID(request.query_params.get("lead_id", "")))
            except ValueError:
                lid = None
            if lid:
                z = server._q("select name, enrichment from leads where id = %s", (lid,))
                if z and not server._privat(z[0]["enrichment"] or {}) \
                        and not server._sammelkontakt(lid):
                    start["neu_kunde"] = {"lead_id": lid, "name": z[0]["name"] or ""}
```

(`darf_schreiben_rolle` = derselbe Ausdruck wie `start["darf_schreiben"]`. `uuid` und `server` sind in ui_kalender schon importiert oder werden ergänzt.)

`fenster.ts`:
- `Vorgabe` bekommt `art?: 'eigen' | 'kunde'` und `kunde?: { lead_id: string; name: string }`.
- In `formular`:
  - Die Startart ist `v.art ?? 'eigen'`, statt fest `'eigen'`.
  - Ist `v.kunde` gesetzt, wird die gewählte Kundenvariable (die die Suche sonst bei Klick auf einen Treffer setzt) mit `{lead_id, name}` belegt.
  - Der Name wird im Treffer-Feld angezeigt.
- `anlegenOeffnen(start, ende, ganztags, ctx, vorgabe: Partial<Vorgabe> = {})` mischt die Vorgabe in die `formular`-Vorgabe.

`main.ts`:
- `interface Start` bekommt `neu_kunde?: { lead_id: string; name: string }`.
- Nach `kalender.render()`: Ist `start.neu_kunde` gesetzt und `start.darf_schreiben`, dann
  `anlegenOeffnen(naechsteVolleStunde(new Date()), plus60, false, ctx, { art: 'kunde', kunde: start.neu_kunde })`.
- Danach die Query per `history.replaceState` entfernen, damit ein Neuladen den Dialog nicht wieder öffnet.

- [ ] **Step 4: Build und Grün sehen.**
  - Run: `cd kalender && npm test && npx tsc --noEmit && npm run build`
  - Dann `python -m pytest -q tests/test_ui_kalender.py tests/test_kalender_paket.py`
  - Expected: grün. `test_kalender_paket` prüft das Manifest des neuen Bundles.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui_kalender.py sales-mcp/tests/test_ui_kalender.py kalender/src/fenster.ts kalender/src/main.ts kalender/src/fenster.test.ts sales-mcp/static/kalender
git commit -m "feat(kalender): Kundentermin-Dialog per Link vorbelegt oeffnen"
```

---

### Task 7: Deploy (Controller, nicht Subagent)

Braucht das Go des Betreibers (DB-Schema per provision.sql, neue Seiten).

- [ ] **Step 1:** Claims in WORKBOARD und Vault setzen, nur die eigene Zeile committen.
- [ ] **Step 2:** `provision.sql` als supabase_admin anwenden: `docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < db/provision.sql`. Dann die Tabelle in `sales`, `sales_ivan` und `sales_test` prüfen, ebenso `has_table_privilege` von `sales_app` (sales) und `sales_app_ivan` (sales_ivan).
- [ ] **Step 3:** Prüfen, ob fremde, noch nicht deployte Commits mitgehen (`git log <VM-Stand>..HEAD`). Dann push und `update.sh`. Erwartet: `ALLE PRUEFUNGEN GRUEN`.
- [ ] **Step 4:** HTTP-Probe in `sales-ui`: `/empfehlungen` liefert 200 (leer). In `sales-mcp` mit `SALES_DB_SCHEMA=sales_test` eine Probeliste anlegen, `liste()` und `pdf()` aufrufen, danach `sales_test` aufräumen (truncate `empfehlungslisten`, die Probe-Leads und deren Aktivitäten).
- [ ] **Step 5:** `grep -c empfehlungsliste_anlegen` in der AGENTS.md des Agenten, `ls skills/empfehlungsliste/SKILL.md` im Container.
- [ ] **Step 6:** Claims schließen, Gedächtnis aktualisieren, SDD-Arbeitsbereich löschen. Dem Betreiber den Testweg nennen: Foto der echten Liste schicken.
