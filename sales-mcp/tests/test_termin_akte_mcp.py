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
