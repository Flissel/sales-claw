"""Vertragstests gegen sales_test. Die Suite darf NIE gegen `sales` laufen —
`sales.activities` ist append-only und ließe sich nicht zurücksetzen."""
import json
import os

import pytest

os.environ.setdefault("SALES_DB_SCHEMA", "sales_test")
import server  # noqa: E402  — liest SALES_DB_SCHEMA beim Import


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _anlegen(name="Max Testperson"):
    return json.loads(server.kontakt_anlegen(name=name, phone="+490000000001"))


def test_kontakt_anlegen_und_suchen():
    neu = _anlegen()
    assert neu["lead_id"]
    treffer = json.loads(server.kontakt_suchen("testperson"))
    assert treffer["kontakte"][0]["lead_id"] == neu["lead_id"]


def test_suche_ohne_treffer_ist_leer_und_kein_fehler():
    treffer = json.loads(server.kontakt_suchen("gibtsnicht"))
    assert treffer["kontakte"] == []


def test_aktivitaet_landet_im_protokoll():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.aktivitaet_loggen(lead, "nachricht", "Kunde fragt nach Termin"))
    assert ok["geloggt"] is True
    profil = json.loads(server.profil_lesen(lead))
    assert profil["aktivitaeten"][0]["type"] == "nachricht"


def test_profil_aktualisieren_ist_kumulativ():
    lead = _anlegen()["lead_id"]
    server.profil_aktualisieren(lead, "beruf", "Lehrerin")
    server.profil_aktualisieren(lead, "wohnort", "Regensburg")
    profil = json.loads(server.profil_lesen(lead))
    assert profil["profil"]["beruf"] == "Lehrerin"
    assert profil["profil"]["wohnort"] == "Regensburg"


def test_unbekannte_lead_id_gibt_fehlertext():
    kaputt = json.loads(server.profil_lesen("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt
