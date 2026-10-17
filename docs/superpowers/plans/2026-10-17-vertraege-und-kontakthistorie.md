# C2 Verträge & Projekte · C3 Kontakt-Historie Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Am Kontakt eigene Abschlüsse und Projekte plus fremde Verträge in einer Liste führen. Vor jedem neuen Kundenentwurf warnen, wenn der Kontakt in 90 Tagen schon zum selben Thema angeschrieben wurde. Die Kontakt-Historie zeigen.

**Architecture:**
- **C2:** Das neue Modul `sales-mcp/vertraege.py` normalisiert und schreibt `enrichment.vertraege` (ohne DDL). Dazu kommt das Werkzeug `abschluss_speichern` und ein Kasten auf der Kontaktseite.
- **C3:**
  - Die neue Spalte `drafts.thema` (provision.sql) trägt das Thema.
  - Das Modul `sales-mcp/historie.py` hält `thema_norm`, `doppelt_pruefen` und `kontakt_historie`.
  - Die Agent-Werkzeuge für Kundenentwürfe prüfen vor dem Anlegen. Freigabe-Karte und Kontaktseite zeigen Hinweis bzw. Zeitleiste.

**Tech Stack:** Python 3.12, psycopg 3, Starlette, pytest mit Test-Postgres.

**Spec:** `docs/superpowers/specs/2026-10-17-vertraege-projekte-und-kontakthistorie-design.md`

## Global Constraints

- **Repo und Branch:**
  - `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`, direkt committen.
  - Vor jedem Commit toplevel und Branch prüfen, dann `git pull --no-rebase origin feat/stufe-1-fundament`.
  - Conventional Commits auf Deutsch, Trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Nur eigene Dateien, nie `.superpowers/`, nie stashen.
- **Neue Testdateien:** Name vorher prüfen (`tests/test_vertraege.py` existiert schon und ist der Stand von `vertrag_speichern`).
- **Tests:**
  - Umgebung: `SALES_DB_URL=postgresql://postgres:ci@127.0.0.1:55432/postgres`, `SALES_DB_SCHEMA=sales_test`.
  - venv `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe`, aus `sales-mcp/`.
  - Bekannte, schon vorher rote Tests:
    - 2 Medienordner-Fehler in `test_werkzeuge`;
    - `test_anker_deckt_alle_gelesenen_caldav_und_verwandten_variablen_ab`;
    - `test_report_ordner_fehlt_kostet_nicht_das_ergebnis`;
    - 15 in `test_termin_einladen`, 8 `test_thema_entitaeten`, 5 `test_kollision`, 4 `test_kalenderquellen`, 2 `test_belegungen`, 2 `test_seitenleiste`, 12 `test_darstellung`, je 1 in `test_editor_seite`, `test_handy`, `test_laden_parameter`.
  - Alles andere gegen BASE im Wegwerf-Worktree prüfen.
- **Vertragseintrag** (Schlüssel wörtlich): `id`, `art` (`eigen`|`fremd`), `bereich` (C1-Schlüssel oder `''`), `bezeichnung`, `status` (`angeboten`|`in_arbeit`|`abgeschlossen`|`beendet`|`''`), `status_datum`, `anbieter`, `betrag`, `wiedervorlage_am`, `notiz`, `erfasst`, `wiedervorlage_id`.
  - Die Altform (`sparte`, `gesellschaft`, `ablauf`) wird beim Lesen zu `art: fremd`, `bezeichnung` ← `sparte`, `anbieter` ← `gesellschaft`, `ablauf` bleibt.
- **Status-Anzeige:** angeboten · in Arbeit · abgeschlossen · beendet.
- **Grenzen:** Betrag ≥ 0 mit höchstens 2 Nachkommastellen (EUR, als String mit Punkt gespeichert). Texte ≤ 200 Zeichen. ≤ 50 Einträge je Kontakt.
- **Aktivitäten:** `vertrag_angelegt` und `vertrag_geaendert` mit Nutzlast `{id, vorher?, nachher}`.
- **Wiedervorlage eigen:** genau zu `wiedervorlage_am`. Ein Datum in der Vergangenheit gibt einen Fehler. Bei Änderung wird die alte quittiert. `beendet` quittiert sie.
- **`abgeschlossen`** fügt den `bereich` per `server._einordnen(..., hinzu=[bereich])` hinzu. Kein automatisches `existing_customer`.
- **Thema:**
  - Normalisierung: klein geschrieben, Leerraum zusammengefasst, ≤ 80 Zeichen.
  - Frist 90 Tage. Treffer-Status: `pending`, `approved`, `sent`.
  - `termin` wird nie geprüft.
  - Newsletter-Thema `Newsletter: <Betreff>`.
- **Doppel-Antwort wörtlich:** `{"doppelt": [...], "hinweis": "Schon am TT.MM. per <Kanal> zum Thema <x> angeschrieben — trotzdem anlegen? Dann trotzdem=True."}`
- **Ruling:** LinkedIn-Beiträge auf dem eigenen Profil (`post_entwurf_erstellen`) werden nicht doppelt-geprüft. Sie gehen an keinen Kontakt und haben eine eigene Themen-Sperre. Ihr Thema wird trotzdem in `drafts.thema` gespeichert.
- **Ruling:** Geprüft wird in den Agent-Werkzeugen `entwurf_erstellen`, `antwort_entwerfen` und `mail_beantworten`. Interne Wege (Termine, Absagen, Marketing-Versandaufträge) prüfen nicht.
- **Sperren:** Privat markierte Kontakte und Sammelkontakte bekommen keine Vertragseinträge.

## Review Focus

- **Betrag mit Komma oder Tausenderpunkt** („1.200,50“, „1200,5“, „€ 99“): wird als 1200.50, 1200.50 bzw. 99.00 gespeichert, Unsinn wie „viel“ gibt einen Fehler (Test in Task 1).
- **Thema-Varianten** („bAV Erstansprache“ und „  BAV   erstansprache “): werden als gleich erkannt (Test in Task 3).
- **Kaputte Altform-Einträge** (kein dict, fehlende Felder, `vertraege` ist kein Array): Profil, Kontaktseite und `speichern` fallen nicht um (Tests in Task 1 und Task 2).
- **Abgelehnter Entwurf** (`rejected`) zum selben Thema: zählt nicht als Treffer (Test in Task 3).
- **Viele Handy-Nachrichten** (5000+): Die Historie bleibt eine Monatssumme, die Seite lädt in einer Abfrage (Test in Task 3).

---

### Task 1: C2 Kern — `vertraege.py`, `abschluss_speichern`, `vertrag_speichern` mit id/art

**Files:**
- Create: `sales-mcp/vertraege.py`
- Modify: `sales-mcp/server.py`:
  - `vertrag_speichern` (~1461-1540): der Vertrags-Dict bekommt `id` und `art: "fremd"`;
  - `profil_lesen` (~2317): `"vertraege": vertraege.eintraege_aus(e)`;
  - neues Werkzeug `abschluss_speichern` nach `vertrag_speichern`;
  - `WERKZEUGE` und Tabu-Liste.
- Modify: `sales-mcp/tests/test_werkzeuge.py` und `tests/test_recherche.py` (96 → 97)
- Create: `sales-mcp/tests/test_vertraege_eigen.py`
- Modify: `config/workspace/AGENTS.md` (Abschnitt „Verträge & Projekte“, Tabu-Liste), `tests/test_agents_regeln.py`

**Interfaces:**
- Produces:
  - `vertraege.STATUS: dict`
  - `vertraege.eintraege_aus(enrichment) -> list[dict]` (normalisiert, ohne DB)
  - `vertraege.eintraege(lead_id) -> list[dict]`
  - `vertraege.speichern(lead_id, art, bereich, bezeichnung, status="", status_datum="", anbieter="", betrag="", wiedervorlage_am="", notiz="", eintrag_id="", quelle="agent") -> dict` mit Rückgabe `{"eintrag", "angelegt": bool, "wiedervorlage": {...}|None}` oder `{"fehler"}`
  - `vertraege.betrag_norm(text) -> str | None`
  - `server.abschluss_speichern(lead_id, bereich, bezeichnung, status, status_datum="", anbieter="", betrag="", wiedervorlage_am="", notiz="", eintrag_id="") -> str`

- [ ] **Step 1: Failing tests** (`sales-mcp/tests/test_vertraege_eigen.py`)

```python
"""C2 Vertraege & Projekte (Spec 2026-10-17)."""
import inspect
import json
import os
from datetime import date, timedelta

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402
import vertraege as vt  # noqa: E402

MORGEN = (date.today() + timedelta(days=1)).isoformat()
SPAETER = (date.today() + timedelta(days=30)).isoformat()


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


def _lead(enrichment=None):
    return str(server._q("insert into leads (name, enrichment) values ('Kunde K', %s::jsonb) "
                         "returning id", (json.dumps(enrichment or {}),))[0]["id"])


def _offene_wv(lead):
    return server._q(
        "select w.id::text id, w.payload from activities w where w.lead_id=%s and "
        "w.type='wiedervorlage' and not exists (select 1 from activities e where "
        "e.type='wiedervorlage_erledigt' and e.payload->>'wiedervorlage_id'=w.id::text)", (lead,))


@pytest.mark.parametrize("ein,aus", [("1.200,50", "1200.50"), ("1200,5", "1200.50"),
                                     ("€ 99", "99.00"), ("0", "0.00"), ("", ""),
                                     ("viel", None), ("-5", None), ("1,234", "1.23")])
def test_betrag_norm(ein, aus):
    if aus == "1.23":       # mehr als 2 Nachkommastellen ist ein Fehler
        assert vt.betrag_norm(ein) is None
    else:
        assert vt.betrag_norm(ein) == aus


def test_eigen_anlegen_mit_wiedervorlage_und_bereich():
    lead = _lead()
    r = vt.speichern(lead, "eigen", "homelab", "NAS + Backup", status="abgeschlossen",
                     status_datum=date.today().isoformat(), anbieter="Synology",
                     betrag="1.499,00", wiedervorlage_am=SPAETER, notiz="Wartung jährlich")
    e = r["eintrag"]
    assert r["angelegt"] and e["art"] == "eigen" and e["betrag"] == "1499.00" and e["id"]
    wv = _offene_wv(lead)
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == SPAETER
    assert e["wiedervorlage_id"] == wv[0]["id"]
    enr = server._q("select enrichment from leads where id=%s", (lead,))[0]["enrichment"]
    assert "homelab" in enr["bereiche"]
    assert server._q("select count(*) n from activities where type='vertrag_angelegt'")[0]["n"] == 1


def test_aendern_quittiert_alte_wiedervorlage_und_beendet_quittiert():
    lead = _lead()
    e = vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", wiedervorlage_am=MORGEN)["eintrag"]
    vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", wiedervorlage_am=SPAETER,
                 eintrag_id=e["id"])
    wv = _offene_wv(lead)
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == SPAETER
    vt.speichern(lead, "eigen", "it", "Webshop", status="beendet", eintrag_id=e["id"])
    assert _offene_wv(lead) == []
    assert len(vt.eintraege(lead)) == 1
    assert server._q("select count(*) n from activities where type='vertrag_geaendert'")[0]["n"] == 2


@pytest.mark.parametrize("kw", [dict(art="kunde"), dict(bereich="rente"), dict(status="fertig"),
                                dict(betrag="viel"), dict(wiedervorlage_am="2020-01-01"),
                                dict(status_datum="gestern"), dict(bezeichnung=""),
                                dict(bezeichnung="x" * 201), dict(eintrag_id="unbekannt")])
def test_ungueltig(kw):
    lead = _lead()
    a = dict(art="eigen", bereich="bav", bezeichnung="bAV Allianz")
    a.update(kw)
    assert "fehler" in vt.speichern(lead, **a)
    assert vt.eintraege(lead) == []


def test_altform_wird_normalisiert_und_kaputtes_ignoriert():
    lead = _lead({"vertraege": [{"sparte": "KFZ", "gesellschaft": "HUK", "ablauf": "2027-01-01"},
                                "kaputt", {"notiz": "nur notiz"}]})
    es = vt.eintraege(lead)
    assert es[0]["art"] == "fremd" and es[0]["bezeichnung"] == "KFZ" and es[0]["anbieter"] == "HUK"
    assert len(es) == 2
    assert vt.eintraege_aus({"vertraege": "kein array"}) == []
    assert vt.eintraege_aus(None) == []


def test_grenze_50_und_sperren(monkeypatch):
    lead = _lead()
    for i in range(50):
        assert "fehler" not in vt.speichern(lead, "eigen", "it", f"P{i}")
    assert "fehler" in vt.speichern(lead, "eigen", "it", "zuviel")
    privat = _lead({"_privat": {"privat": True}})
    assert "fehler" in vt.speichern(privat, "eigen", "it", "x")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", lead)
    assert "fehler" in vt.speichern(lead, "eigen", "it", "y")


def test_vertrag_speichern_schreibt_id_und_art_und_profil_zeigt_beides():
    lead = _lead()
    json.loads(server.vertrag_speichern(lead, "KFZ", gesellschaft="HUK"))
    json.loads(server.abschluss_speichern(lead, "vorsorge", "Rürup", "angeboten"))
    p = json.loads(server.profil_lesen(lead))
    arten = sorted(v["art"] for v in p["vertraege"])
    assert arten == ["eigen", "fremd"] and all(v["id"] for v in p["vertraege"])


def test_werkzeug_registriert_und_signatur():
    assert server.abschluss_speichern in server.WERKZEUGE
    assert list(inspect.signature(server.abschluss_speichern).parameters) == [
        "lead_id", "bereich", "bezeichnung", "status", "status_datum", "anbieter", "betrag",
        "wiedervorlage_am", "notiz", "eintrag_id"]
```

`tests/test_agents_regeln.py`:

```python
def test_vertraege_projekte_im_prompt():
    assert "abschluss_speichern(" in TEXT and "vertrag_speichern(" in TEXT
    assert "`abschluss_speichern`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_vertraege_eigen.py tests/test_agents_regeln.py`. Expected: FAIL (`ModuleNotFoundError: vertraege`)

- [ ] **Step 3: Implementieren** (`sales-mcp/vertraege.py`)

```python
"""Vertraege & Projekte (C2, Spec 2026-10-17): eigene Abschluesse/Projekte
('eigen') und vom Kunden genannte Vertraege ('fremd') in EINER Liste
leads.enrichment.vertraege — ohne DDL. Altform-Eintraege (sparte/
gesellschaft/ablauf aus vertrag_speichern) werden beim Lesen normalisiert."""
import json
import re
import uuid
from datetime import date, datetime, timezone

import server

STATUS = {"angeboten": "angeboten", "in_arbeit": "in Arbeit",
          "abgeschlossen": "abgeschlossen", "beendet": "beendet"}
ARTEN = ("eigen", "fremd")
TEXT_MAX = 200
EINTRAEGE_MAX = 50


def betrag_norm(text) -> str | None:
    """'1.200,50' / '1200,5' / '€ 99' -> '1200.50'; '' -> ''; Unsinn -> None."""
    t = str(text or "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not t:
        return ""
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    return f"{float(t):.2f}"


def _normal(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    if v.get("art") in ARTEN:
        aus = dict(v)
    else:
        aus = {"art": "fremd", "bezeichnung": v.get("sparte", ""),
               "anbieter": v.get("gesellschaft", ""), "ablauf": v.get("ablauf", ""),
               "notiz": v.get("notiz", ""), "erfasst": v.get("erfasst", ""), "id": v.get("id", "")}
    for k in ("id", "bereich", "bezeichnung", "status", "status_datum", "anbieter", "betrag",
              "wiedervorlage_am", "notiz", "erfasst", "wiedervorlage_id"):
        aus.setdefault(k, "")
    if not (aus["bezeichnung"] or aus["anbieter"] or aus["notiz"]):
        return None if not aus.get("ablauf") else aus
    return aus


def eintraege_aus(enrichment) -> list:
    roh = (enrichment or {}).get("vertraege") if isinstance(enrichment, dict) else None
    if not isinstance(roh, list):
        return []
    return [n for n in (_normal(v) for v in roh) if n is not None]
```

Weiter in `vertraege.py`:

```python
def eintraege(lead_id) -> list:
    z = server._q("select enrichment from leads where id = %s", (str(lead_id),))
    return eintraege_aus(z[0]["enrichment"]) if z else []


def _datum(text, feld):
    if not text:
        return "", None
    try:
        return date.fromisoformat(str(text)).isoformat(), None
    except ValueError:
        return None, f"{feld} '{text}' ist kein Datum (JJJJ-MM-TT)."


def speichern(lead_id, art, bereich, bezeichnung, status="", status_datum="", anbieter="",
              betrag="", wiedervorlage_am="", notiz="", eintrag_id="", quelle="agent") -> dict:
    try:
        lead_id = str(uuid.UUID(str(lead_id)))
    except ValueError:
        return {"fehler": f"'{lead_id}' ist keine gueltige lead_id."}
    if art not in ARTEN:
        return {"fehler": f"Art muss eigen oder fremd sein, nicht '{art}'."}
    if bereich and bereich not in server.BEREICHE:
        return {"fehler": f"Unbekannter Bereich '{bereich}'."}
    if status and status not in STATUS:
        return {"fehler": f"Unbekannter Status '{status}' — erlaubt: {', '.join(STATUS)}."}
    bezeichnung = " ".join(str(bezeichnung or "").split())
    if not 1 <= len(bezeichnung) <= TEXT_MAX:
        return {"fehler": f"Bezeichnung fehlt oder ist laenger als {TEXT_MAX} Zeichen."}
    for name, wert in (("Anbieter", anbieter), ("Notiz", notiz)):
        if len(str(wert or "")) > TEXT_MAX:
            return {"fehler": f"{name} ist laenger als {TEXT_MAX} Zeichen."}
    b = betrag_norm(betrag)
    if b is None:
        return {"fehler": f"Betrag '{betrag}' ist kein Euro-Betrag."}
    sd, f = _datum(status_datum, "Status-Datum")
    if f:
        return {"fehler": f}
    wv, f = _datum(wiedervorlage_am, "Wiedervorlage")
    if f:
        return {"fehler": f}
    heute = datetime.now(timezone.utc).date()
    if wv and date.fromisoformat(wv) < heute:
        return {"fehler": f"Wiedervorlage {wv} liegt in der Vergangenheit."}
    if server._sammelkontakt(lead_id):
        return {"fehler": "Sammelkontakte bekommen keine Vertraege."}
    z = server._q("select enrichment from leads where id = %s", (lead_id,))
    if not z:
        return {"fehler": f"Kein Kontakt mit lead_id {lead_id}."}
    enr = z[0]["enrichment"] or {}
    if server._privat(enr):
        return {"fehler": "Privat markierte Kontakte bekommen keine Vertraege."}
    liste = eintraege_aus(enr)
    alt = next((e for e in liste if e["id"] and e["id"] == eintrag_id), None) if eintrag_id else None
    if eintrag_id and alt is None:
        return {"fehler": f"Kein Eintrag mit id {eintrag_id}."}
    if alt is None and len(liste) >= EINTRAEGE_MAX:
        return {"fehler": f"Hoechstens {EINTRAEGE_MAX} Eintraege je Kontakt."}
    neu = {"id": alt["id"] if alt else str(uuid.uuid4()), "art": art, "bereich": bereich or "",
           "bezeichnung": bezeichnung, "status": status or "", "status_datum": sd,
           "anbieter": " ".join(str(anbieter or "").split()), "betrag": b,
           "wiedervorlage_am": wv, "notiz": str(notiz or "").strip(),
           "erfasst": alt["erfasst"] if alt and alt.get("erfasst") else heute.isoformat(),
           "wiedervorlage_id": alt.get("wiedervorlage_id", "") if alt else ""}
    if alt and alt.get("ablauf"):
        neu["ablauf"] = alt["ablauf"]
    # Wiedervorlage: alte quittieren, wenn Datum wechselt oder beendet; neue anlegen
    wiedervorlage = None
    alte_wv = neu["wiedervorlage_id"]
    if alte_wv and (status == "beendet" or wv != (alt or {}).get("wiedervorlage_am")):
        server.wiedervorlage_erledigt(lead_id, alte_wv)
        neu["wiedervorlage_id"] = ""
    if wv and status != "beendet" and not neu["wiedervorlage_id"]:
        wv_id = server._wiedervorlage_anlegen(lead_id, date.fromisoformat(wv),
                                              f"Vertrag/Projekt: {bezeichnung}")
        neu["wiedervorlage_id"] = wv_id
        wiedervorlage = {"aktivitaets_id": wv_id, "faellig_am": wv}
    rest = [e for e in liste if e is not alt]
    gesamt = ([neu] + rest) if alt is None else [neu if e is alt else e for e in liste]
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "'{vertraege}', %s::jsonb, true), updated_at = now() where id = %s returning id",
              (json.dumps(gesamt, ensure_ascii=False), lead_id))
    server._q("insert into activities (lead_id, type, payload, actor) values (%s, %s, %s, %s) "
              "returning id",
              (lead_id, "vertrag_geaendert" if alt else "vertrag_angelegt",
               json.dumps({"id": neu["id"], **({"vorher": alt} if alt else {}), "nachher": neu},
                          ensure_ascii=False), "human" if quelle == "ui" else "agent"))
    if status == "abgeschlossen" and bereich:
        server._einordnen(lead_id, None, [bereich], (), quelle="ui" if quelle == "ui" else "agent")
    return {"eintrag": neu, "angelegt": alt is None, "wiedervorlage": wiedervorlage}
```

Hinweis: Das Zurückschreiben normalisiert auch Altform-Einträge. Das ist gewollt, `vertrag_speichern`-Tests prüfen nur Inhalte. Die Reihenfolge ist neueste zuerst bei neuen Einträgen, an Ort und Stelle bei Änderungen.

`server.py`:
- In `vertrag_speichern` den Dict `vertrag` um `"id": str(uuid.uuid4())` und `"art": "fremd"` ergänzen, vor dem Dedup-Vergleich. `_kern` bleibt unverändert.
- In `profil_lesen` `"vertraege": vertraege.eintraege_aus(e)` setzen (lokal `import vertraege`).
- Das Werkzeug:

```python
@_gesichert
def abschluss_speichern(lead_id: str, bereich: str, bezeichnung: str, status: str,
                        status_datum: str = "", anbieter: str = "", betrag: str = "",
                        wiedervorlage_am: str = "", notiz: str = "",
                        eintrag_id: str = "") -> str:
    """EIGENEN Abschluss bzw. eigenes Projekt am Kontakt anlegen oder aendern
    (eintrag_id gesetzt = aendern). bereich: bav, mitarbeiter, vorsorge,
    immobilien, it, homelab. status: angeboten, in_arbeit, abgeschlossen,
    beendet (+ status_datum JJJJ-MM-TT). betrag in EUR. wiedervorlage_am
    legt eine Wiedervorlage genau zu dem Datum an. Vom Kunden nur GENANNTE
    fremde Vertraege weiter mit vertrag_speichern. Nur auf Zuruf oder bei
    eindeutigem Gespraechsinhalt; nie raten; jede Aenderung dem Betreiber
    nennen. Setzt KEINEN Bestandskunden-Status."""
    import vertraege
    return _json(vertraege.speichern(lead_id, "eigen", bereich, bezeichnung, status,
                                     status_datum, anbieter, betrag, wiedervorlage_am,
                                     notiz, eintrag_id, quelle="agent"))
```

`WERKZEUGE` direkt nach `vertrag_speichern`: `abschluss_speichern,` mit Kommentar `# Vertraege & Projekte (17.10.2026), Vertraege: tests/test_vertraege_eigen.py.`. Die Zähler in `test_werkzeuge.py` (Changelog „96 -> 97“) und `test_recherche.py` auf 97.

AGENTS.md: Abschnitt `## Verträge & Projekte` direkt nach `## Einordnung (Art und Bereiche)`:

```markdown
## Verträge & Projekte

Am Kontakt steht EINE Liste: **eigene** Abschluesse und Projekte (bAV,
Vorsorge, Immobilie, IT-Projekt, Homelab …) und **fremde** Vertraege, die
der Kunde nur nennt.
- Eigenes: `abschluss_speichern(lead_id, bereich, bezeichnung, status,
  status_datum, anbieter, betrag, wiedervorlage_am, notiz)` — Status
  angeboten · in_arbeit · abgeschlossen · beendet; zum Aendern die
  `eintrag_id` aus `profil_lesen` mitgeben.
- Fremdes: weiter `vertrag_speichern(lead_id, sparte, ablauf, gesellschaft,
  notiz)` (Wiedervorlage 90 Tage vor Ablauf).
- Nur auf Zuruf oder bei eindeutigem Gespraechsinhalt; nie raten; jede
  Aenderung in einer Zeile nennen. Ein Abschluss macht den Kontakt NICHT
  zum Bestandskunden im Sinne des UWG — das entscheidet der Betreiber.
```

In der Tabu-Liste `` `empfehlungslisten_zeigen` sowie jede Recherche `` ersetzen durch `` `empfehlungslisten_zeigen`, `abschluss_speichern` sowie jede Recherche ``.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_vertraege_eigen.py tests/test_vertraege.py tests/test_werkzeuge.py tests/test_recherche.py tests/test_agents_regeln.py tests/test_uebergabe.py tests/test_wochenbericht.py`. Expected: grün bis auf die bekannten Roten. `test_vertraege.py` muss unverändert grün sein.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/vertraege.py sales-mcp/server.py sales-mcp/tests/test_vertraege_eigen.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py sales-mcp/tests/test_agents_regeln.py config/workspace/AGENTS.md
git commit -m "feat(vertraege): eigene Abschluesse und Projekte neben fremden Vertraegen"
```

---

### Task 2: C2 Kontaktseite „Verträge & Projekte“

**Files:**
- Modify: `sales-mcp/ui.py`: Abschnitt Verträge in `kontakt_detail` (~5662-5671) ersetzen; neuer Handler `aktion_kontakt_vertrag`, Route `POST /kontakte/vertrag` vor `/kontakte/{lead_id}`
- Test: `sales-mcp/tests/test_ui.py` (anhängen)

**Interfaces:**
- Consumes: `vertraege.eintraege(lead_id)`, `vertraege.speichern(..., quelle="ui")`, `vertraege.STATUS`, `server.BEREICHE`.
- Produces: POST `/kontakte/vertrag` mit Form `csrf`, `lead_id`, `eintrag_id` (leer = neu), `art`, `bereich`, `bezeichnung`, `status`, `status_datum`, `anbieter`, `betrag`, `wiedervorlage_am`, `notiz`.

- [ ] **Step 1: Failing tests**

```python
def test_vertraege_kasten_zeigt_beide_arten_escaped():
    lead = _lead()
    ui.server._q("update leads set enrichment = jsonb_set(coalesce(enrichment,'{}'::jsonb), "
                 "'{vertraege}', %s::jsonb, true) where id=%s returning id",
                 (json.dumps([{"sparte": "KFZ <b>", "gesellschaft": "HUK"},
                              {"id": "e1", "art": "eigen", "bereich": "homelab",
                               "bezeichnung": "NAS", "status": "abgeschlossen",
                               "betrag": "1499.00"}]), lead))
    s = _get(f"/kontakte/{lead}").text
    assert "Verträge &amp; Projekte" in s or "Verträge & Projekte" in s
    assert "KFZ &lt;b&gt;" in s and "NAS" in s and "fremd" in s and "bei uns" in s
    assert "1.499,00" in s or "1499.00" in s
    assert 'action="/kontakte/vertrag"' in s


def test_vertrag_formular_speichert_und_validiert():
    lead = _lead()
    d = {"csrf": ui.CSRF_TOKEN, "lead_id": lead, "eintrag_id": "", "art": "eigen",
         "bereich": "it", "bezeichnung": "Webshop", "status": "in_arbeit", "status_datum": "",
         "anbieter": "", "betrag": "2.500", "wiedervorlage_am": "", "notiz": ""}
    assert _post("/kontakte/vertrag", {k: v for k, v in d.items() if k != "csrf"}).status_code == 403
    assert _post("/kontakte/vertrag", d).status_code == 303
    import vertraege
    e = vertraege.eintraege(lead)[0]
    assert e["bezeichnung"] == "Webshop" and e["betrag"] == "2500.00"
    assert _post("/kontakte/vertrag", {**d, "betrag": "viel"}).status_code == 422
```

(Kaputte `vertraege` (kein Array) dürfen die Seite nicht brechen, dafür einen Test mit `'"kaputt"'` als Wert ergänzen: Seite 200.)

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_ui.py -k vertrag`. Expected: FAIL

- [ ] **Step 3: Implementieren.**
  - Den alten Abschnitt durch `_vertraege_bereich(lead)` ersetzen:
    - Überschrift `<h2 id="vertraege">Verträge & Projekte (N)</h2>`.
    - Tabelle mit den Spalten Art („bei uns“/„fremd“), Bereich (Anzeige aus `server.BEREICHE`), Bezeichnung, Status (Anzeige plus Datum TT.MM.JJJJ), Anbieter, Betrag (deutsch formatiert `1.499,00 €`), Wiedervorlage bzw. Ablauf, Notiz, alles `_e`.
    - Pro Zeile ein „Bearbeiten“ als `<details>` mit vorbelegtem Formular, darunter `<details><summary>Neu</summary>` mit leerem Formular (Art-Auswahl eigen/fremd, Bereich-Auswahl inklusive leer, Status-Auswahl inklusive leer, Datumsfelder `type="date"`).
    - Rolle `lesen`/`kalender` (`_AKTIVE_ROLLE`): Tabelle ohne Formulare.
    - Privat und Sammelkontakt: kein Formular.
  - Handler: `_kontakt_vorspann`, dann `vertraege.speichern(lead_id, ..., quelle="ui")`. Bei `fehler` folgt `_fehlerseite(422, "Nicht gespeichert", _e(fehler))`, sonst `RedirectResponse(f"/kontakte/{lead_id}#vertraege", 303)`.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_ui.py tests/test_vertraege_eigen.py`. Expected: grün.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_ui.py
git commit -m "feat(ui): Kontaktseite mit Vertraegen und Projekten"
```

---

### Task 3: C3 Kern — `drafts.thema`, `historie.py`

**Files:**
- Modify: `db/provision.sql` (im Loop neben ~273: `execute format('alter table %I.drafts add column if not exists thema text', s);` mit Kommentar)
- Create: `sales-mcp/historie.py`
- Create: `sales-mcp/tests/test_historie.py` (Name prüfen)
- Lokal: `alter table sales_test.drafts add column if not exists thema text`

**Interfaces:**
- Produces:
  - `historie.thema_norm(text) -> str`
  - `historie.doppelt_pruefen(lead_id, thema, tage=90) -> list[dict]` mit `{draft_id, kanal, thema, status, datum}`
  - `historie.doppelt_hinweis(treffer: list) -> str`
  - `historie.kontakt_historie(lead_id, tage=365) -> list[dict]` mit `{datum, art, kanal, text}`, neueste zuerst
  - `historie.zuletzt(lead_id) -> dict | None`

- [ ] **Step 1: Failing tests** (`tests/test_historie.py`)

```python
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import historie as hi  # noqa: E402
import server  # noqa: E402

PROVISION = (Path(__file__).resolve().parents[2] / "db" / "provision.sql").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")


def _lead():
    return str(server._q("insert into leads (name, phone) values ('K', '+491701234567') "
                         "returning id")[0]["id"])


def _draft(lead, thema, status="sent", tage_alt=1, kanal="whatsapp", subject=None, newsletter=None):
    t = datetime.now(timezone.utc) - timedelta(days=tage_alt)
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, thema, subject, "
        "newsletter, created_at, sent_at) values (%s,%s,'x','Text',%s,%s,%s,%s,%s,%s) returning id",
        (lead, kanal, status, thema, subject, newsletter, t, t if status == "sent" else None))[0]["id"])


def test_provision_hat_thema_spalte():
    assert "add column if not exists thema text" in PROVISION


def test_thema_norm():
    assert hi.thema_norm("  BAV   Erstansprache ") == hi.thema_norm("bav erstansprache")
    assert len(hi.thema_norm("x" * 200)) == 80
    assert hi.thema_norm(None) == ""


def test_doppelt_frist_status_termin():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=10)
    _draft(lead, "bAV Erstansprache", status="rejected", tage_alt=5)
    _draft(lead, "Homelab", tage_alt=120)
    _draft(lead, "termin", tage_alt=1)
    assert len(hi.doppelt_pruefen(lead, "  BAV  erstansprache")) == 1
    assert hi.doppelt_pruefen(lead, "homelab") == []
    assert hi.doppelt_pruefen(lead, "termin") == []
    assert hi.doppelt_pruefen(lead, "") == []
    _draft(lead, "Homelab", status="pending", tage_alt=0)
    assert hi.doppelt_pruefen(lead, "Homelab")[0]["status"] == "pending"


def test_hinweis_wortlaut():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=3)
    h = hi.doppelt_hinweis(hi.doppelt_pruefen(lead, "bAV Erstansprache"))
    assert h.startswith("Schon am ") and "per WhatsApp zum Thema bAV Erstansprache angeschrieben" in h
    assert h.endswith("trotzdem anlegen? Dann trotzdem=True.")


def test_historie_quellen_und_handy_summe():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=3, kanal="email", subject="bAV für Ihr Team")
    _draft(lead, None, tage_alt=2, kanal="email", subject="Oktober-News",
           newsletter="00000000-0000-0000-0000-000000000001")
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin',%s) returning id",
              (lead, json.dumps({"datum": "2026-10-20", "uhrzeit": "10:00", "thema": "Erstgespräch"})))
    with server.pool.connection() as c:
        c.execute("insert into sales_test.activities (lead_id, type, payload, created_at) "
                  "select %s, 'nachricht_ausgehend', '{\"text\":\"hi\"}', now() - (g || ' hours')::interval "
                  "from generate_series(1, 5000) g", (lead,))
    h = hi.kontakt_historie(lead)
    arten = [e["art"] for e in h]
    assert "entwurf" in arten and "newsletter" in arten and "termin" in arten and "handy" in arten
    handy = [e for e in h if e["art"] == "handy"]
    assert all("Nachrichten" in e["text"] for e in handy) and len(handy) <= 13
    assert h == sorted(h, key=lambda e: e["datum"], reverse=True)
    assert hi.zuletzt(lead)["art"] != "handy"
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_historie.py`. Expected: FAIL (Modul fehlt, Spalte fehlt)

- [ ] **Step 3: Implementieren.**
  - `provision.sql`: die Spalte (siehe Files).
  - Lokal: `alter table sales_test.drafts add column if not exists thema text;`
  - `sales-mcp/historie.py`:

```python
"""Kontakt-Historie und Doppel-Pruefung (C3, Spec 2026-10-17)."""
from datetime import date, datetime

import server

FRIST_TAGE = 90
THEMA_MAX = 80
_KANAL = {"whatsapp": "WhatsApp", "email": "Mail", "linkedin": "LinkedIn", "telegram": "Telegram"}


def thema_norm(text) -> str:
    return " ".join(str(text or "").lower().split())[:THEMA_MAX]


def doppelt_pruefen(lead_id, thema, tage=FRIST_TAGE) -> list:
    n = thema_norm(thema)
    if not n or n == "termin":
        return []
    return [{"draft_id": str(z["id"]), "kanal": z["channel"], "thema": z["thema"],
             "status": z["status"], "datum": z["datum"]}
            for z in server._q(
                "select id, channel, thema, status, coalesce(sent_at, created_at) as datum "
                "from drafts where lead_id = %s and status in ('pending','approved','sent') "
                "and lower(regexp_replace(trim(coalesce(thema,'')), '\\s+', ' ', 'g')) = %s "
                "and coalesce(sent_at, created_at) > now() - make_interval(days => %s) "
                "order by datum desc", (str(lead_id), n, tage))]


def doppelt_hinweis(treffer: list) -> str:
    t = treffer[0]
    d = t["datum"]
    tag = d.strftime("%d.%m.") if isinstance(d, (date, datetime)) else str(d)[8:10] + "." + str(d)[5:7] + "."
    return (f"Schon am {tag} per {_KANAL.get(t['kanal'], t['kanal'])} zum Thema {t['thema']} "
            f"angeschrieben — trotzdem anlegen? Dann trotzdem=True.")


def kontakt_historie(lead_id, tage=365) -> list:
    lid = str(lead_id)
    aus = []
    for z in server._q(
            "select channel, subject, thema, newsletter, left(body, 60) as anfang, "
            "coalesce(sent_at, created_at) as datum from drafts where lead_id = %s "
            "and status = 'sent' and coalesce(sent_at, created_at) > now() - make_interval(days => %s)",
            (lid, tage)):
        art = "newsletter" if z["newsletter"] else "entwurf"
        text = z["thema"] or z["subject"] or z["anfang"] or ""
        aus.append({"datum": z["datum"], "art": art, "kanal": z["channel"], "text": text})
    for z in server._q(
            "select type, payload, created_at from activities where lead_id = %s and type in "
            "('termin','termin_abgesagt','einladung_entworfen') and created_at > now() - "
            "make_interval(days => %s)", (lid, tage)):
        p = z["payload"] or {}
        text = {"termin": f"Termin {p.get('datum','')} {p.get('uhrzeit','')} {p.get('thema','')}",
                "termin_abgesagt": f"Termin abgesagt {p.get('datum','')}",
                "einladung_entworfen": f"Einladung {p.get('datum','')} {p.get('uhrzeit','')}"}[z["type"]]
        aus.append({"datum": z["created_at"], "art": "termin", "kanal": "", "text": " ".join(text.split())})
    for z in server._q(
            "select date_trunc('month', created_at) as monat, count(*) as n, max(created_at) as zuletzt "
            "from activities where lead_id = %s and type = 'nachricht_ausgehend' and created_at > "
            "now() - make_interval(days => %s) group by 1", (lid, tage)):
        aus.append({"datum": z["zuletzt"], "art": "handy", "kanal": "whatsapp",
                    "text": f"{z['n']} Nachrichten (WhatsApp vom Handy) im {z['monat']:%m/%Y}"})
    aus.sort(key=lambda e: e["datum"], reverse=True)
    return aus


def zuletzt(lead_id) -> dict | None:
    return next((e for e in kontakt_historie(lead_id) if e["art"] != "handy"), None)
```

(Ist `created_at` von `drafts` nicht setzbar, weil Spalte oder Default anders heißen, die echte Spalte aus `information_schema` nehmen. Ebenso `sent_at`.)

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_historie.py`. Expected: alle grün.

- [ ] **Step 5: Commit**

```bash
git add db/provision.sql sales-mcp/historie.py sales-mcp/tests/test_historie.py
git commit -m "feat(historie): Thema an Entwuerfen, Doppel-Pruefung und Kontakt-Historie"
```

---

### Task 4: C3 Werkzeuge — Thema setzen, Doppel-Warnung, Historie lesen

**Files:**
- Modify: `sales-mcp/server.py`:
  - `_entwurf_erstellen` (~2458): Parameter `thema: str = ""`, in das INSERT als `thema` (`nullif(%s,'')`).
  - Die Werkzeuge `entwurf_erstellen` (~2413), `antwort_entwerfen` (~6704) und `mail_beantworten` (~3397) bekommen `thema: str = ""` und `trotzdem: bool = False`.
  - `post_entwurf_erstellen` (~2714) schreibt `thema` in die Spalte.
  - `_termin_einladen` und die Wege von `kunde_benachrichtigen` übergeben `thema="termin"`, `_newsletter_entwurf` (~2688) setzt `thema = "Newsletter: " + betreff`.
  - `profil_lesen` bekommt `zuletzt_angeschrieben` und `historie_kurz`.
  - Neues Werkzeug `kontakt_historie_lesen`, dazu `WERKZEUGE` und die Tabu-Liste.
- Modify:
  - `sales-mcp/tests/test_werkzeuge.py`: Signaturtest (~1314), Zähler 97 → 98;
  - `tests/test_recherche.py`: Zähler 98;
  - `tests/test_historie.py`: anhängen;
  - `config/workspace/AGENTS.md`;
  - `tests/test_agents_regeln.py`.

**Interfaces:**
- Consumes: `historie.doppelt_pruefen`, `historie.doppelt_hinweis`, `historie.kontakt_historie`, `historie.zuletzt` (Task 3).
- Produces:
  - `entwurf_erstellen(lead_id, kanal, text, betreff="", medien_datei="", auftrag_betreiber=False, thema="", trotzdem=False)`
  - `antwort_entwerfen(lead_id, text, medien_datei="", auftrag_betreiber=False, thema="", trotzdem=False)`
  - `mail_beantworten(uid, text, thema="", trotzdem=False)`
  - `kontakt_historie_lesen(lead_id: str) -> str`

- [ ] **Step 1: Failing tests** (an `tests/test_historie.py` anhängen. Die Kontakt-Vorbereitung muss die bestehenden Tore passieren: Einwilligung `opt_in` und WhatsApp-Freigabe wie in vorhandenen `entwurf_erstellen`-Tests setzen, das Muster aus `tests/test_werkzeuge.py` übernehmen.)

```python
import inspect


def _kunde_mit_freigabe():
    lead = _lead()
    server.einwilligung_erfassen(lead, "opt_in", "Test")
    server.kontakt_freigeben(lead) if hasattr(server, "kontakt_freigeben") else None
    return lead


def test_entwurf_mit_thema_warnt_bei_doppelt_und_trotzdem_legt_an():
    lead = _kunde_mit_freigabe()
    r1 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 1", thema="bAV Erstansprache"))
    assert "draft_id" in r1
    assert server._q("select thema from drafts where id=%s", (r1["draft_id"],))[0]["thema"] == "bAV Erstansprache"
    r2 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 2", thema="bav  erstansprache"))
    assert "draft_id" not in r2 and r2["doppelt"] and r2["hinweis"].endswith("Dann trotzdem=True.")
    r3 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 3", thema="bav erstansprache",
                                             trotzdem=True))
    assert "draft_id" in r3
    assert server._q("select count(*) n from activities where type='doppelt_bestaetigt'")[0]["n"] == 1


def test_ohne_thema_keine_pruefung():
    lead = _kunde_mit_freigabe()
    assert "draft_id" in json.loads(server.entwurf_erstellen(lead, "whatsapp", "A"))
    assert "draft_id" in json.loads(server.entwurf_erstellen(lead, "whatsapp", "B"))


def test_signaturen():
    assert list(inspect.signature(server.entwurf_erstellen).parameters) == [
        "lead_id", "kanal", "text", "betreff", "medien_datei", "auftrag_betreiber", "thema", "trotzdem"]
    assert list(inspect.signature(server.antwort_entwerfen).parameters)[-2:] == ["thema", "trotzdem"]
    assert list(inspect.signature(server.mail_beantworten).parameters) == ["uid", "text", "thema", "trotzdem"]
    assert server.kontakt_historie_lesen in server.WERKZEUGE


def test_profil_und_historie_werkzeug():
    lead = _lead()
    _draft(lead, "Homelab-Angebot", tage_alt=4)
    p = json.loads(server.profil_lesen(lead))
    assert p["zuletzt_angeschrieben"]["text"] == "Homelab-Angebot" and len(p["historie_kurz"]) == 1
    h = json.loads(server.kontakt_historie_lesen(lead))
    assert h["historie"][0]["text"] == "Homelab-Angebot"
```

(Heißt das Freigabe-Werkzeug anders, das aus den bestehenden WhatsApp-Entwurfs-Tests nehmen. `json.dumps` in `_json` muss `datetime` können: `_json` nutzt `default=str`, also ok.)

`tests/test_werkzeuge.py` (~1314): Die erwartete Liste für `entwurf_erstellen` um `"thema", "trotzdem"` erweitern, Zähler-Changelog „97 -> 98: kontakt_historie_lesen“.

`tests/test_agents_regeln.py`:

```python
def test_doppeltes_vermeiden_im_prompt():
    assert "## Doppeltes vermeiden" in TEXT
    abschnitt = TEXT.split("## Doppeltes vermeiden")[1].split("\n## ")[0]
    assert "thema=" in abschnitt and "trotzdem=True" in abschnitt
    assert "`kontakt_historie_lesen`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_historie.py tests/test_agents_regeln.py`. Expected: FAIL

- [ ] **Step 3: Implementieren.**
  - In den drei Werkzeugen ganz am Anfang (nach der Lead-Auflösung, bei `mail_beantworten` nach der Ermittlung von `lead_id`):

```python
    if thema and not trotzdem:
        import historie
        treffer = historie.doppelt_pruefen(lead_id, thema)
        if treffer:
            return _json({"doppelt": treffer, "hinweis": historie.doppelt_hinweis(treffer)})
```

  - Nach erfolgreichem Anlegen mit `trotzdem` und einem Thema, zu dem es Treffer gab: Aktivität `doppelt_bestaetigt` mit `{draft_id, thema}` buchen. `thema` an `_entwurf_erstellen` durchreichen.
  - `_entwurf_erstellen`: Das INSERT wird zu `insert into drafts (lead_id, channel, recipient, subject, body, media_ref, thema) values (%s, %s, %s, nullif(%s,''), %s, %s, nullif(%s,''))`. `thema` wird vorher auf 200 Zeichen begrenzt.
  - Termin- und Absage-Wege: `thema="termin"`.
  - `_newsletter_entwurf`: Spalte `thema` mit `f"Newsletter: {betreff}"[:200]`.
  - `post_entwurf_erstellen`: `thema` als Spalte.
  - `profil_lesen`: `"zuletzt_angeschrieben": historie.zuletzt(lead_id)` und `"historie_kurz": [e for e in historie.kontakt_historie(lead_id) if e["art"] != "handy"][:5]`.
  - Werkzeug:

```python
@_gesichert
def kontakt_historie_lesen(lead_id: str) -> str:
    """Womit wurde der Kontakt in den letzten 365 Tagen angeschrieben —
    versendete Entwuerfe (mit Thema), Newsletter, Termine/Einladungen,
    WhatsApp vom Handy als Monatssumme. Neueste zuerst. Liest nur."""
    import historie
    return _json({"historie": historie.kontakt_historie(lead_id)})
```

  - AGENTS.md: neuer Abschnitt `## Doppeltes vermeiden` nach `## Entwuerfe` (wörtlich):

```markdown
## Doppeltes vermeiden

Gib bei JEDER Erstansprache und jedem Angebot ein kurzes Thema mit:
`entwurf_erstellen(..., thema='bAV-Erstansprache')` (ebenso
`antwort_entwerfen`, `mail_beantworten`). Gab es an denselben Kontakt in
den letzten 90 Tagen schon etwas zum selben Thema, kommt statt eines
Entwurfs `doppelt` mit einem Hinweis zurueck: nenne dem Betreiber
Datum, Kanal und Thema und rufe nur auf sein ausdrueckliches „trotzdem"
erneut mit `trotzdem=True` auf. `kontakt_historie_lesen(lead_id)` zeigt,
womit der Kontakt schon angeschrieben wurde.
```

  - Tabu-Liste: `` `abschluss_speichern` sowie jede Recherche `` wird zu `` `abschluss_speichern`, `kontakt_historie_lesen` sowie jede Recherche ``.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_historie.py tests/test_werkzeuge.py tests/test_recherche.py tests/test_agents_regeln.py tests/test_mail_beantworten.py tests/test_termin_aendern.py tests/test_newsletter_abmelden.py tests/test_linkedin_posts.py tests/test_uwg.py`. Expected: grün bis auf die bekannten Roten.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_historie.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py sales-mcp/tests/test_agents_regeln.py config/workspace/AGENTS.md
git commit -m "feat(historie): Entwuerfe mit Thema, Doppel-Warnung und Historie fuer den Agenten"
```

---

### Task 5: C3 Oberfläche — Freigabe-Hinweis und Zeitleiste

**Files:**
- Modify: `sales-mcp/ui.py`:
  - Die Pending-Abfragen in `inbox()` (~2519-2524) und auf der Heute-Seite (~6743-6748) bekommen `d.lead_id, d.thema`.
  - `_entwurf_karte_offen` (~1843) bekommt den Hinweis.
  - `kontakt_detail` bekommt die Zeitleiste nach „Verträge & Projekte“.
- Test: `sales-mcp/tests/test_ui.py` (anhängen)

**Interfaces:**
- Consumes: `historie.doppelt_pruefen`, `historie.kontakt_historie` (Task 3).

- [ ] **Step 1: Failing tests**

```python
def test_freigabe_karte_zeigt_schon_angeschrieben():
    lead = _lead()
    ui.server._q("insert into drafts (lead_id, channel, recipient, body, status, thema, sent_at) "
                 "values (%s,'whatsapp','x','alt','sent','bAV Erstansprache', now() - interval '3 days') "
                 "returning id", (lead,))
    ui.server._q("insert into drafts (lead_id, channel, recipient, body, status, thema) "
                 "values (%s,'whatsapp','x','neu','pending','bav erstansprache') returning id", (lead,))
    s = _get("/freigaben").text
    assert "Schon angeschrieben" in s and "bAV Erstansprache" in s


def test_kontaktseite_zeitleiste():
    lead = _lead()
    ui.server._q("insert into drafts (lead_id, channel, recipient, body, status, thema, sent_at) "
                 "values (%s,'email','x','b','sent','Homelab <Angebot>', now()) returning id", (lead,))
    s = _get(f"/kontakte/{lead}").text
    assert "Kontakt-Historie" in s and "Homelab &lt;Angebot&gt;" in s
```

- [ ] **Step 2: Rot sehen.** Run: `python -m pytest -q tests/test_ui.py -k "angeschrieben or zeitleiste"`. Expected: FAIL

- [ ] **Step 3: Implementieren.**
  - In `_entwurf_karte_offen`: Ist `z.get("thema")` gesetzt und `z.get("lead_id")` vorhanden, werden die Treffer aus `historie.doppelt_pruefen(z["lead_id"], z["thema"])` geholt, **ohne den Entwurf selbst** (Treffer mit `draft_id == str(z["id"])` herausfiltern). Gibt es Treffer, kommt `<div class="hinweis">Schon angeschrieben: TT.MM. · Kanal · Thema</div>` dazu (escaped, höchstens 3).
  - Kontaktseite: `<h2 id="historie">Kontakt-Historie</h2>` mit den letzten 20 Einträgen als Liste `TT.MM.JJJJ · Kanal · Text` (escaped). Bei mehr als 20 folgt ein Link `?historie=alle#historie`, der alle zeigt.
  - DB-Fehler der Historie werden abgefangen: Der Abschnitt entfällt, die Seite bleibt 200.

- [ ] **Step 4: Grün sehen.** Run: `python -m pytest -q tests/test_ui.py`. Expected: grün.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_ui.py
git commit -m "feat(ui): Freigabe warnt vor Doppeltem, Kontaktseite zeigt Historie"
```

---

### Task 6: Deploy (Controller)

- [ ] Claims setzen.
- [ ] provision.sql als supabase_admin, dann `drafts.thema` in `sales`, `sales_ivan` und `sales_test` prüfen.
- [ ] Fremde, noch nicht deployte Commits prüfen, dann push und `update.sh`.
- [ ] Probe gegen `sales_test` im `sales-mcp`-Container: Abschluss anlegen, Doppel-Warnung auslösen, Historie lesen, danach aufräumen.
- [ ] HTTP-Probe: Kontaktseite eines echten Kontakts liefert 200 mit „Kontakt-Historie“ und „Verträge & Projekte“.
- [ ] Agent prüfen: `abschluss_speichern` und `Doppeltes vermeiden` in seiner AGENTS.md.
- [ ] Claims schließen, Gedächtnis aktualisieren, Arbeitsbereich löschen.
