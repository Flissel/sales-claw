"""Welche Werte eine Terminkarte bekommt — und welche sie NICHT erfindet.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import terminkarte  # noqa: E402

GESTALT = {"seite": {"breite_mm": 148, "hoehe_mm": 105}, "felder": [
    {"name": "kunde", "beschriftung": "Kunde", "art": "text", "quelle": "kunde.name",
     "platz": {"x": 8, "y": 20, "breite": 60, "hoehe": 12}},
    {"name": "tel", "beschriftung": "Telefon", "art": "telefon", "quelle": "kunde.telefon",
     "platz": {"x": 8, "y": 34, "breite": 60, "hoehe": 12}},
    {"name": "wann", "beschriftung": "Datum", "art": "datum", "quelle": "termin.datum",
     "platz": {"x": 80, "y": 20, "breite": 60, "hoehe": 12}},
    {"name": "um", "beschriftung": "Uhrzeit", "art": "uhrzeit", "quelle": "termin.uhrzeit",
     "platz": {"x": 80, "y": 34, "breite": 60, "hoehe": 12}},
    {"name": "berater", "beschriftung": "Berater", "art": "text", "quelle": "mitglied.name",
     "platz": {"x": 8, "y": 48, "breite": 60, "hoehe": 12}},
    {"name": "vorinfo", "beschriftung": "Vorinfos", "art": "mehrzeilig", "quelle": "frei",
     "platz": {"x": 8, "y": 62, "breite": 132, "hoehe": 30}}]}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.leads cascade")
    yield


def _lead(name="Jürgen Müßig", phone="+491701234567"):
    return str(server._q("insert into leads (name, phone, source) values (%s, %s, 'test') "
                         "returning id", (name, phone))[0]["id"])


def _termin(lead, datum, uhrzeit, uid, abgesagt=False):
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s) "
              "returning id", (lead, json.dumps({"datum": datum, "uhrzeit": uhrzeit,
                                                "dauer_minuten": 60, "thema": "Erstgespraech",
                                                "ort": "Buero", "uid": uid})))
    if abgesagt:
        server._q("insert into activities (lead_id, type, payload) values "
                  "(%s, 'termin_abgesagt', %s) returning id", (lead, json.dumps({"uid": uid})))


def test_katalog_ist_der_aus_der_spezifikation():
    assert set(terminkarte.KATALOG) == {
        "kunde.name", "kunde.telefon", "kunde.email", "kunde.firma", "termin.datum",
        "termin.uhrzeit", "termin.dauer", "termin.thema", "termin.ort", "mitglied.name", "frei"}


def test_werte_kommen_aus_kontakt_termin_und_mitglied():
    lead = _lead()
    _termin(lead, "2026-10-02", "14:30", "u1")
    r = terminkarte.werte_sammeln(server._q, lead, GESTALT, "Felix Baumann", {})
    assert r["werte"]["kunde"] == "Jürgen Müßig"
    assert r["werte"]["wann"] == "02.10.2026"
    assert r["werte"]["um"] == "14:30"
    assert r["werte"]["berater"] == "Felix Baumann"
    assert r["termin_uid"] == "u1"
    assert r["fehlend"] == ["vorinfo"]


def test_ein_abgesagter_termin_wird_nicht_genommen():
    lead = _lead()
    _termin(lead, "2026-10-01", "09:00", "alt")
    _termin(lead, "2026-10-09", "11:00", "neu", abgesagt=True)
    r = terminkarte.werte_sammeln(server._q, lead, GESTALT, "Felix", {})
    assert r["termin_uid"] == "alt" and r["werte"]["wann"] == "01.10.2026"


def test_ohne_termin_bleiben_die_terminfelder_offen():
    r = terminkarte.werte_sammeln(server._q, _lead(), GESTALT, "Felix", {})
    assert r["termin_uid"] == "" and {"wann", "um"} <= set(r["fehlend"])


def test_zusatz_fuellt_freie_felder_und_ueberstimmt_nichts_stilles():
    lead = _lead()
    r = terminkarte.werte_sammeln(server._q, lead, GESTALT, "Felix",
                                  {"vorinfo": "Hat 2 Kinder", "kunde": "Anderer Name"})
    assert r["werte"]["vorinfo"] == "Hat 2 Kinder"
    assert r["werte"]["kunde"] == "Anderer Name"   # ausdrueckliche Angabe gewinnt


def test_dateiname_bekommt_bei_kollision_ein_suffix():
    belegt = {"terminkarte-juergen-muessig-2026-10-02.pdf"}
    assert terminkarte.dateiname("Jürgen Müßig", "2026-10-02", belegt.__contains__) == \
        "terminkarte-juergen-muessig-2026-10-02-2.pdf"
