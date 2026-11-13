"""MCP-Werkzeug termin_akte_lesen (Meeting-Mittelpunkt Task 12)."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
PASSCODE = "PASS4711"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    yield


def _akte(uid="u1"):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, titel, link, plattform, "
        "passcode, einwahl, status) values (%s, 'sales-claw', %s, %s, 'Beratung', "
        "'https://meet.google.com/abc-defg-hij', 'google_meet', %s, '+49 30 123', 'geplant') "
        "returning uid", (uid, JETZT, JETZT + timedelta(hours=1), PASSCODE))


def test_mcp_ohne_passcode():
    _akte()
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle) "
              "values ('u1', 'weg@firma.de', 'Gesperrt', 'gast') returning uid")
    server._q("update termin_teilnehmer set grund = 'gesperrt' where uid = 'u1' returning uid")
    roh = server.termin_akte_lesen("u1")
    assert PASSCODE not in roh and "passcode" not in roh
    daten = json.loads(roh)
    assert daten["uid"] == "u1" and daten["titel"] == "Beratung"
    assert daten["beitreten"]["link"] == "https://meet.google.com/abc-defg-hij"
    assert daten["teilnehmer"] == []          # gesperrt: fehlt ganz
    assert "weg@firma.de" not in roh


def test_mcp_unbekannte_uid():
    assert json.loads(server.termin_akte_lesen("gibts-nicht")) == {
        "fehler": "Keine Akte zu dieser uid."}


def test_mcp_ist_registriert():
    assert server.termin_akte_lesen in server.WERKZEUGE


def test_mcp_passcode_auch_in_link_und_texten_weg():
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, titel, link, plattform, "
        "passcode, einwahl, beschreibung, status) values ('z1', 'sales-claw', %s, %s, "
        "'Zoom', 'https://zoom.us/j/1?pwd=PASS4711&x=1', 'zoom', %s, "
        "'Einwahl +49 30 1, Kenncode: PASS4711', 'Kenncode: PASS4711 bitte nutzen', "
        "'geplant') returning uid", (JETZT, JETZT + timedelta(hours=1), PASSCODE))
    roh = server.termin_akte_lesen("z1")
    assert PASSCODE not in roh
    daten = json.loads(roh)
    assert daten["beitreten"]["link"] == "https://zoom.us/j/1?x=1"
    assert "•••" in daten["beschreibung"] and "bitte nutzen" in daten["beschreibung"]


def test_mcp_ohne_gesprochenes_und_kundentext():
    lead = str(server._q("insert into leads (name, email, source) values "
                         "('Karla Kunde', 'k@firma.de', 'Messe') returning id")[0]["id"])
    _akte("g1")
    server._q("update termin_akten set briefing_md = %s, briefing_mit_ki = false, "
              "briefing_am = now() where uid = 'g1' returning uid",
              ("## Kurz\nBRIEFINGSATZ Budget knapp",))
    mid = str(server._q(
        "insert into termin_mitschriften (uid, segmente, auswertung_status, auswertung_md) "
        "values ('g1', %s::jsonb, 'fertig', %s) returning id",
        (json.dumps([{"sprecher": "K", "text": "GESPROCHENERSATZ zur Kuendigung"}]),
         "- Painpoint: \"AUSWERTUNGSZITAT\""))[0]["id"])
    server._q("insert into termin_vorschlaege (mitschrift_id, art, lead_id, daten) "
              "values (%s, 'wiedervorlage', %s, %s::jsonb) returning id",
              (mid, lead, json.dumps({"faellig_am": "2099-02-01", "notiz": "NOTIZTEXT"})))
    roh = server.termin_akte_lesen("g1")
    for geheim in ("GESPROCHENERSATZ", "AUSWERTUNGSZITAT", "BRIEFINGSATZ", "NOTIZTEXT"):
        assert geheim not in roh
    d = json.loads(roh)
    assert d["mitschrift"] == {"vorhanden": True, "auswertung_status": "fertig"}
    assert set(d["briefing"]) == {"am", "mit_ki"} and d["briefing"]["mit_ki"] is False
    assert len(d["vorschlaege"]) == 1
    assert set(d["vorschlaege"][0]) == {"id", "art", "status", "lead_id"}
    assert d["vorschlaege"][0]["art"] == "wiedervorlage"


def test_mcp_ohne_mitschrift_und_briefing_sind_none():
    _akte("g2")
    d = json.loads(server.termin_akte_lesen("g2"))
    assert d["mitschrift"] is None and d["briefing"] is None and d["vorschlaege"] == []


def test_mcp_pwd_hash_in_jeder_url_weg():
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, titel, link, plattform, "
        "passcode, beschreibung, einwahl, status) values ('z2', 'sales-claw', %s, %s, 'Zoom', "
        "'https://zoom.us/j/9?pwd=HASHlink999', 'zoom', '123456', %s, %s, 'geplant') "
        "returning uid",
        (JETZT, JETZT + timedelta(hours=1),
         "Beitreten: https://zoom.us/j/9?pwd=HASHabc123&uname=x. Bis dann",
         "Alternativ (https://zoom.us/j/9?passcode=HASHein77)"))
    roh = server.termin_akte_lesen("z2")
    for hash_ in ("HASHabc123", "HASHlink999", "HASHein77"):
        assert hash_ not in roh
    d = json.loads(roh)
    assert "https://zoom.us/j/9?uname=x" in d["beschreibung"] and "Bis dann" in d["beschreibung"]
    assert d["beitreten"]["link"] == "https://zoom.us/j/9"


class _Antwort:
    def __init__(self, daten):
        self._d = json.dumps(daten).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._d


def test_mcp_termin_bilder_suchen(monkeypatch):
    import urllib.request

    gesehen = {}

    def urlopen(req, timeout=None):
        gesehen["url"], gesehen["body"] = req.full_url, json.loads(req.data)
        gesehen["timeout"] = timeout
        return _Antwort([{"id": "i1", "uid": "u1", "aufgenommen_am": "2099-01-09T12:00:00Z",
                          "beschreibung": "Folie", "score": 0.8, "bild": "ROHBYTES"}])

    monkeypatch.setenv("AUGE_URL", "http://auge:8790")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert server.termin_bilder_suchen in server.WERKZEUGE
    roh = server.termin_bilder_suchen("Preisliste", uid="u1", limit=3)
    assert gesehen["url"] == "http://auge:8790/suche" and gesehen["timeout"] <= 15
    assert gesehen["body"] == {"text": "Preisliste", "uid": "u1", "limit": 3}
    d = json.loads(roh)
    assert d[0]["id"] == "i1" and d[0]["beschreibung"] == "Folie" and "ROHBYTES" not in roh
    # ohne uid: kein uid-Feld
    server.termin_bilder_suchen("x")
    assert "uid" not in gesehen["body"] and gesehen["body"]["limit"] == 10


def test_mcp_termin_bilder_suchen_fehlerfaelle(monkeypatch):
    import urllib.request
    monkeypatch.setenv("AUGE_URL", "")
    assert "fehler" in json.loads(server.termin_bilder_suchen("x"))
    monkeypatch.setenv("AUGE_URL", "http://auge:8790")

    def kaputt(req, timeout=None):
        raise OSError("geheim-Anfragetext")
    monkeypatch.setattr(urllib.request, "urlopen", kaputt)
    roh = server.termin_bilder_suchen("x")
    assert "fehler" in json.loads(roh) and "geheim" not in roh
    assert "fehler" in json.loads(server.termin_bilder_suchen("   "))
