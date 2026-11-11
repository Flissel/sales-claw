"""Die Liste der abonnierten Fremdkalender — Spec 2026-09-11 §2.1 Weg 3."""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def test_quelle_anlegen_und_lesen():
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
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
    server.kalenderquelle_speichern("Ivan", "https://example.test/alt.ics", "ivan", "privat")
    server.kalenderquelle_speichern("Ivan", "https://example.test/neu.ics", "ivan", "privat")
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1, quellen
    assert quellen[0]["url"] == "https://example.test/neu.ics"


def test_stand_wird_festgehalten():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] is None
    assert q["zuletzt_gelesen"] is not None


def test_fehler_loescht_den_alten_zaehler_nicht():
    """Ein einzelner Abrufausfall darf die letzte bekannte Zahl nicht
    wegwischen — sonst sieht die Seite aus, als sei nie etwas angekommen."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    server.kalenderquelle_stand_setzen(qid, None, "Zeitgrenze")
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] == "Zeitgrenze"


def test_zweiter_erfolgreicher_aufruf_aktualisiert_zaehler():
    """Ein zweiter erfolgreicher Abruf mit einer anderen Zahl muss den
    Zaehler wirklich weiterschreiben — sonst friert er beim ersten Wert
    ein (z.B. bei vertauschten coalesce-Argumenten)."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    server.kalenderquelle_stand_setzen(qid, 20, None)
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 20


def test_erfolg_nach_fehler_loescht_den_fehler():
    """Klappt der naechste Abruf wieder, muss der alte Fehler verschwinden
    und der neue Zaehlerstand stehen — sonst zeigt die Seite dauerhaft
    einen Fehler, der laengst behoben ist."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    server.kalenderquelle_stand_setzen(qid, None, "Zeitgrenze")
    server.kalenderquelle_stand_setzen(qid, 20, None)
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 20
    assert q["letzter_fehler"] is None


def test_entfernen():
    """Fix-Runde 1 (Task 9): Entfernen loescht die Zeile (und ihre Termine)
    wirklich - aktiv oder pausiert. Neu verbinden legt eine neue Zeile an."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "privat")
    assert server.kalenderquelle_entfernen(qid, "ivan") is True
    assert server.kalenderquellen_lesen() == []
    assert server.kalenderquelle_entfernen(qid, "ivan") is False

    assert server.kalenderquellen_lesen(nur_aktive=False) == []

    # Verbindet der Kollege seinen Kalender unter demselben Namen neu,
    # entsteht eine neue Zeile.
    neue_id = server.kalenderquelle_speichern("Ivan", "https://example.test/neu.ics", "ivan", "privat")
    assert neue_id != qid
    wieder = server.kalenderquellen_lesen()
    assert len(wieder) == 1, wieder
    assert wieder[0]["aktiv"] is True
    assert wieder[0]["url"] == "https://example.test/neu.ics"


# --- Besitzer und Bereich (Spec 2026-11-08) ----------------------------------

def _termin(titel="Zahnarzt", ort="Praxis"):
    beginn = datetime.now(timezone.utc) + timedelta(days=1)
    return {"uid": "u1", "beginn": beginn, "ende": beginn + timedelta(hours=1),
            "titel": titel, "ort": ort}


def _gespeichert(qid):
    return server._q("select titel, ort from kalender_termine where quelle_id = %s",
                     (qid,))


def test_quelle_traegt_besitzer_und_bereich():
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    q = server.kalenderquellen_lesen()[0]
    assert (q["besitzer"], q["bereich"]) == ("ivan", "business")


def test_gleicher_name_verschiedener_besitzer_sind_zwei_quellen():
    a = server.kalenderquelle_speichern("Privat", "https://example.test/a.ics", "ivan", "privat")
    b = server.kalenderquelle_speichern("Privat", "https://example.test/b.ics", "felix", "privat")
    assert a != b
    assert len(server.kalenderquellen_lesen()) == 2


def test_bereich_ist_pflicht_und_geprueft():
    with pytest.raises(ValueError):
        server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "")
    assert server.kalenderquellen_lesen(nur_aktive=False) == []


def test_wechsel_auf_privat_loescht_fremde_titel_sofort():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    server.kalendertermine_ersetzen(qid, [_termin()], True)
    assert _gespeichert(qid) == [{"titel": "Zahnarzt", "ort": "Praxis"}]
    assert server.kalenderquelle_bereich_setzen(qid, "privat", "ivan") is True
    assert _gespeichert(qid) == [{"titel": None, "ort": None}]
    assert server.kalenderquellen_lesen()[0]["bereich"] == "privat"


def test_wechsel_auf_privat_behaelt_titel_des_laden_besitzers():
    qid = server.kalenderquelle_speichern("Felix", "https://example.test/a.ics", "felix", "business")
    server.kalendertermine_ersetzen(qid, [_termin()], True)
    assert server.kalenderquelle_bereich_setzen(qid, "privat", "felix") is True
    assert _gespeichert(qid) == [{"titel": "Zahnarzt", "ort": "Praxis"}]


def test_neu_verbinden_als_privat_loescht_fremde_titel():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    server.kalendertermine_ersetzen(qid, [_termin()], True)
    assert server.kalenderquelle_speichern(
        "Ivan", "https://example.test/neu.ics", "ivan", "privat") == qid
    assert _gespeichert(qid) == [{"titel": None, "ort": None}]


def test_bereich_setzen_nur_als_besitzer():
    qid = server.kalenderquelle_speichern("Felix", "https://example.test/a.ics", "felix", "privat")
    assert server.kalenderquelle_bereich_setzen(qid, "business", "ivan") is False
    assert server.kalenderquellen_lesen()[0]["bereich"] == "privat"
    # besitzer=None: Rolle `freigeben` darf alle.
    assert server.kalenderquelle_bereich_setzen(qid, "business", None) is True
    assert server.kalenderquellen_lesen()[0]["bereich"] == "business"


def test_nur_besitzer_entfernt():
    qid = server.kalenderquelle_speichern("Felix", "https://example.test/a.ics", "felix", "privat")
    assert server.kalenderquelle_entfernen(qid, "ivan") is False
    q = server.kalenderquellen_lesen()[0]
    assert q["aktiv"] is True and q["url"] == "https://example.test/a.ics"
    assert server.kalenderquelle_entfernen(qid, None) is True


def test_entfernen_loescht_die_abgeglichenen_termine():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    server.kalendertermine_ersetzen(qid, [_termin()], True)
    assert server.kalenderquelle_entfernen(qid, "ivan") is True
    assert _gespeichert(qid) == []


def test_pausieren_und_fortsetzen_nur_als_besitzer():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    assert server.kalenderquelle_pausieren(qid, False, "felix") is False
    assert server.kalenderquelle_pausieren(qid, False, "ivan") is True
    assert server.kalenderquellen_lesen() == []
    assert server.kalenderquelle_pausieren(qid, True, "ivan") is True
    assert server.kalenderquellen_lesen()[0]["id"] == qid


def test_entfernte_quelle_laesst_sich_nicht_fortsetzen():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    server.kalenderquelle_entfernen(qid, "ivan")
    assert server.kalenderquelle_pausieren(qid, True, "ivan") is False
    assert server.kalenderquellen_lesen() == []


# --- Abgleich gegen Wechsel/Entfernen (Fix-Runde 1, Task 5) ------------------

def test_ersetzen_nach_wechsel_auf_privat_speichert_keine_fremden_titel():
    """Der Abgleich hat details=True aus seinem Stand zu Rundenbeginn; in
    der Zwischenzeit wurde die Quelle privat. Massgeblich ist die Zeile."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    assert server.kalenderquelle_bereich_setzen(qid, "privat", "ivan") is True
    assert server.kalendertermine_ersetzen(qid, [_termin()], True) == 1
    assert _gespeichert(qid) == [{"titel": None, "ort": None}]


def test_ersetzen_nach_entfernen_schreibt_nichts():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    assert server.kalenderquelle_entfernen(qid, "ivan") is True
    assert server.kalendertermine_ersetzen(qid, [_termin()], True) == 0
    assert _gespeichert(qid) == []


def test_ersetzen_unbekannte_quelle_schreibt_nichts():
    assert server.kalendertermine_ersetzen(
        "00000000-0000-0000-0000-000000000000", [_termin()], True) == 0


def test_details_false_des_aufrufers_schraenkt_zusaetzlich_ein():
    qid = server.kalenderquelle_speichern("Felix", "https://example.test/a.ics", "felix", "business")
    server.kalendertermine_ersetzen(qid, [_termin()], False)
    assert _gespeichert(qid) == [{"titel": None, "ort": None}]


def test_eigener_privatkalender_eines_teammitglieds_zeigt_privattermin():
    """Fallback in kalendertermine_lesen: ivans Privattitel wurden nie
    gespeichert (Spec §6.3) - auch ivan selbst sieht den Block, nie None."""
    qid = server.kalenderquelle_speichern("Ivan privat", "https://example.test/a.ics",
                                          "ivan", "privat")
    server.kalendertermine_ersetzen(qid, [_termin()], True)
    server.kalenderquelle_stand_setzen(qid, 1, None)
    assert _gespeichert(qid) == [{"titel": None, "ort": None}]
    jetzt = datetime.now(timezone.utc)
    termine, luecken = server.kalendertermine_lesen(jetzt, jetzt + timedelta(days=2), "ivan")
    assert luecken == []
    assert [(t["titel"], t["ort"], t["maskiert"]) for t in termine] == [
        ("Privattermin", "", False)]


def test_wechsel_auf_privat_loescht_alle_detailspalten():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    server.kalendertermine_ersetzen(qid, [dict(
        _termin(), beschreibung="Agenda", konferenz="https://meet.example/x",
        teilnehmer=[{"adresse": "g@x.example", "name": "G", "rolle": "gast",
                     "art": "individual"}], teilnehmer_anzahl=1)], True)
    voll = server._q("select titel, ort, beschreibung, teilnehmer, konferenz "
                     "from kalender_termine where quelle_id = %s", (qid,))[0]
    assert all(v is not None for v in voll.values()), voll
    assert server.kalenderquelle_bereich_setzen(qid, "privat", "ivan") is True
    leer = server._q("select titel, ort, beschreibung, teilnehmer, konferenz "
                     "from kalender_termine where quelle_id = %s", (qid,))[0]
    assert all(v is None for v in leer.values()), leer
