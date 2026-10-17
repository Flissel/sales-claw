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
