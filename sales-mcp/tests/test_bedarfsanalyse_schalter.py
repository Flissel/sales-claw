"""Schalter SALES_BEDARFSANALYSE: Vorgabe aus, nur 'an' schaltet ein.

Aus heisst: Werkzeuge nicht registriert, Digest/Uebergabe/Kontaktseite ohne
Bedarfsanalyse. Code und Daten bleiben bestehen.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(tmp_path, monkeypatch):
    import recherche
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


def _lead_mit_bedarf():
    lead = server._q(
        "insert into leads (name, phone, source, enrichment) values "
        "('Anna Schalter', '+491701234567', 'whatsapp', %s) returning id",
        (json.dumps({"bedarf": {"alter": {"antwort": "34", "at": "2026-08-19"}}}),)
    )[0]["id"]
    return str(lead)


def test_aus_ist_vorgabe(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    assert server.bedarfsanalyse_an() is False


@pytest.mark.parametrize("wert", ["", "ja", "1", "true", "aus"])
def test_nur_an_schaltet_ein(monkeypatch, wert):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", wert)
    assert server.bedarfsanalyse_an() is False


def test_werkzeuge_ohne_bedarf(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    namen = {f.__name__ for f in server.aktive_werkzeuge()}
    assert "bedarf_speichern" not in namen and "bedarf_offen" not in namen
    assert "entwurf_erstellen" in namen


def test_an_bringt_sie_zurueck(monkeypatch):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")
    assert {"bedarf_speichern", "bedarf_offen"} <= {
        f.__name__ for f in server.aktive_werkzeuge()}
    assert len(server.aktive_werkzeuge()) == len(server.WERKZEUGE)


def test_digest_ohne_bedarf(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    _lead_mit_bedarf()
    assert "unvollstaendige_bedarfsanalysen" not in json.loads(server.digest())


def test_digest_ohne_bedarf_macht_keine_bedarf_abfrage(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    _lead_mit_bedarf()

    def boom(*a, **k):
        raise AssertionError("bedarf_offen darf nicht laufen")
    monkeypatch.setattr(server, "bedarf_offen", boom)
    json.loads(server.digest())


def test_digest_mit_bedarf(monkeypatch):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")
    _lead_mit_bedarf()
    assert "unvollstaendige_bedarfsanalysen" in json.loads(server.digest())


def test_uebergabe_ohne_abschnitt(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    lead = _lead_mit_bedarf()
    text = json.loads(server.uebergabe_erstellen(lead))["text"]
    assert "## Bedarfsanalyse" not in text
    assert "## Vertraege" in text


def test_uebergabe_mit_abschnitt(monkeypatch):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")
    lead = _lead_mit_bedarf()
    assert "## Bedarfsanalyse" in json.loads(
        server.uebergabe_erstellen(lead))["text"]


def test_kontaktseite_ohne_bedarfsstand(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    lead = _lead_mit_bedarf()
    seite = CLIENT.get(f"/kontakte/{lead}", headers={"host": HOST_OK}).text
    assert "Anna Schalter" in seite and "Bedarfsstand" not in seite


def test_kontaktseite_mit_bedarfsstand(monkeypatch):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")
    lead = _lead_mit_bedarf()
    seite = CLIENT.get(f"/kontakte/{lead}", headers={"host": HOST_OK}).text
    assert "Bedarfsstand" in seite
