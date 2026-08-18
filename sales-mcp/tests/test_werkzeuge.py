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


def test_bedarf_speichern_und_offene_schrumpfen():
    lead = _anlegen()["lead_id"]
    vorher = json.loads(server.bedarf_offen(lead))
    server.bedarf_speichern(lead, "alter", "34")
    nachher = json.loads(server.bedarf_offen(lead))
    assert vorher["anzahl_offen"] - nachher["anzahl_offen"] == 1
    profil = json.loads(server.profil_lesen(lead))
    assert profil["bedarf"]["alter"]["antwort"] == "34"


def test_bedarf_unbekannte_frage_wird_abgelehnt():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.bedarf_speichern(lead, "schuhgroesse", "44"))
    assert "fehler" in kaputt


def test_consent_frage_setzt_consent_status():
    lead = _anlegen()["lead_id"]
    server.bedarf_speichern(lead, "consent_kontakt", "ja, gerne")
    profil = json.loads(server.profil_lesen(lead))
    assert profil["consent"] == "opt_in"


def test_entwurf_bleibt_pending():
    lead = _anlegen()["lead_id"]
    e = json.loads(server.entwurf_erstellen(lead, "linkedin",
                                            "Hallo Herr Testperson, ..."))
    assert e["status"] == "pending"
    zeilen = server._q("select status, channel from drafts")
    assert zeilen == [{"status": "pending", "channel": "linkedin"}]


def test_entwurf_unzulaessiger_kanal():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.entwurf_erstellen(lead, "brieftaube", "x"))
    assert "fehler" in kaputt


def test_digest_nennt_offene_entwuerfe():
    lead = _anlegen()["lead_id"]
    server.entwurf_erstellen(lead, "whatsapp", "Follow-up-Text")
    d = json.loads(server.digest())
    assert d["offene_entwuerfe"][0]["kanal"] == "whatsapp"
    assert d["anzahl_entwuerfe"] == 1


def test_werkzeug_signaturen_ueberleben_den_dekorator():
    import inspect
    assert "name" in inspect.signature(server.kontakt_anlegen).parameters
    assert "frage_id" in inspect.signature(server.bedarf_speichern).parameters
