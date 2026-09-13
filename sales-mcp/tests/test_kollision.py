"""Kollisionspruefung ueber alle Quellen — Spec §2.2, Pruefung 3a/3b."""
import json
import os
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads, sales_test.kalender_quellen cascade")
    yield


def _belegt(*eintraege, luecken=()):
    return lambda tage_voraus=60: (list(eintraege), list(luecken))


def _e(tag, von, bis, quelle, titel="Belegt"):
    return {"beginn": datetime(2026, 10, tag, von, tzinfo=timezone.utc),
            "ende": datetime(2026, 10, tag, bis, tzinfo=timezone.utc),
            "titel": titel, "ort": "", "quelle": quelle}


def _beginn(tag, stunde):
    return datetime(2026, 10, tag, stunde, tzinfo=timezone.utc)


def test_ueberlappung_beim_kollegen_wird_gefunden(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Ivans Kundentermin")))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert len(treffer) == 1
    assert treffer[0]["quelle"] == "Ivan"
    assert treffer[0]["titel"] == "Ivans Kundentermin"


def test_ueberlappung_beim_betreiber_wird_gefunden(monkeypatch):
    """Gegenprobe zur vorigen: beide Richtungen, wie Pruefung 3a verlangt."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Betreiber", "Eigener")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert [t["quelle"] for t in treffer] == ["Betreiber"]


def test_anschliessender_termin_ist_keine_kollision(monkeypatch):
    """Ende gleich Beginn heisst nacheinander, nicht gleichzeitig — sonst
    waere jeder Tag mit Terminkette blockiert."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 10), 30)
    assert treffer == []


def test_termin_davor_ist_keine_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 14, 15, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 60)
    assert treffer == []


def test_punktueller_termin_ohne_dauer_kollidiert_nicht(monkeypatch):
    """Fehlt DTEND, ist ende == beginn. Ein solcher Eintrag darf nicht den
    ganzen Tag blockieren."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 9, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []


def test_luecken_werden_durchgereicht(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []
    assert luecken[0]["quelle"] == "Ivan"


def test_werkzeug_meldet_frei(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt())
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is True
    assert antwort["kollisionen"] == []


def test_werkzeug_meldet_belegt_mit_namen(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:30", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_werkzeug_ist_bei_luecken_nicht_einfach_frei(monkeypatch):
    """Der wichtigste Fall: nichts gefunden, aber auch nichts gewusst."""
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_ungueltiges_datum_wird_abgewiesen():
    antwort = json.loads(server.termin_konflikte("morgen", "09:00"))
    assert "fehler" in antwort


def _lead():
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values ('Ivan K', 'k@example.test', '+491701234567', 'whatsapp', "
        "'existing_customer') returning id")[0]["id"])


def test_einladung_nennt_die_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    antwort = json.loads(server.termin_einladen(
        _lead(), "2026-10-01", "09:30", thema="Test"))
    assert "fehler" not in antwort, antwort
    assert antwort["kollisionen"], antwort
    assert "Ivan" in antwort["hinweis"]


def test_kollision_blockiert_die_einladung_NICHT(monkeypatch):
    """Bewusste Entscheidung: der Betreiber ruft das Werkzeug absichtlich
    auf. Eine Doppelbuchung kann gewollt sein; gemeldet wird sie, verhindert
    nicht."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 10, "Ivan")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    lead = _lead()
    json.loads(server.termin_einladen(lead, "2026-10-01", "09:30", thema="T"))
    assert len(server._q(
        "select id from drafts where lead_id = %s", (lead,))) == 1
