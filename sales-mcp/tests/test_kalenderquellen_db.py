"""Die Liste der abonnierten Fremdkalender — Spec 2026-09-11 §2.1 Weg 3."""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def test_quelle_anlegen_und_lesen():
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1, quellen
    assert quellen[0]["anzeigename"] == "Ivan"
    assert quellen[0]["url"] == "https://example.test/a.ics"
    assert quellen[0]["art"] == "ics"
    assert quellen[0]["aktiv"] is True


def test_gleicher_name_ersetzt_statt_zu_verdoppeln():
    """Verbindet ein Kollege seinen Kalender ein zweites Mal — weil er die
    Adresse zurueckgesetzt hat —, soll die alte, tote Adresse verschwinden
    und nicht daneben stehenbleiben und stuendlich Fehler produzieren."""
    server.kalenderquelle_speichern("Ivan", "https://example.test/alt.ics")
    server.kalenderquelle_speichern("Ivan", "https://example.test/neu.ics")
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1, quellen
    assert quellen[0]["url"] == "https://example.test/neu.ics"


def test_stand_wird_festgehalten():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] is None
    assert q["zuletzt_gelesen"] is not None


def test_fehler_loescht_den_alten_zaehler_nicht():
    """Ein einzelner Abrufausfall darf die letzte bekannte Zahl nicht
    wegwischen — sonst sieht die Seite aus, als sei nie etwas angekommen."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    server.kalenderquelle_stand_setzen(qid, None, "Zeitgrenze")
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] == "Zeitgrenze"


def test_entfernen():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    assert server.kalenderquelle_entfernen(qid) is True
    assert server.kalenderquellen_lesen() == []
    assert server.kalenderquelle_entfernen(qid) is False
