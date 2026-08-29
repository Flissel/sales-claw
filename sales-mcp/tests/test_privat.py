"""Vertragstests fuer die Privat-Markierung (P3, 29.08.2026).

Betreiber: "p3 erst dann teil b" — die Stufe UEBER ignorieren fuer echte
Privat-Kontakte. Kern: Datensparsamkeit statt Filterung. Was nie
gespeichert wurde, kann in keiner Liste, keinem Profil und keinem Report
auftauchen. Bestandsinhalte BLEIBEN (Betreiber-Standard: behalten, ab
jetzt still); Loeschung einzelner Altinhalte laeuft ueber docs/06.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Ein privater Kontakt ist dem System still: keine neuen Inhalte
   (test_inbox.py), kein Verlauf fuer den Bot, keine Faelligkeiten,
   keine Entwuerfe.
2. Die Auskunft (Art. 15) funktioniert WEITER — sie ist das Recht der
   Person, nicht eine Analyse des Vertriebs.
3. Fail-closed in Schutzrichtung: ein kaputter Vermerk zaehlt als
   privat; nur ein ausdruecklich zurueckgenommener nicht.
"""
import json
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
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _lead(name="Pia Privat"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491706667788', 'whatsapp') returning id", (name,))[0]["id"])
    server.kontakt_freigeben(lead)
    return lead


def _nachrichten(lead, n=6):
    for i in range(n):
        server._q(
            "insert into activities (lead_id, type, payload) values "
            "(%s, 'kundenantwort', %s) returning id",
            (lead, server._json({"text": f"privates {i}"})))


def _enrichment(lead):
    return server._q("select enrichment from leads where id = %s",
                     (lead,))[0]["enrichment"]


# ---------------------------------------------------------------------------
# Der Vermerk selbst
# ---------------------------------------------------------------------------

def test_setzen_vermerkt_und_protokolliert():
    lead = _lead()
    antwort = json.loads(server.kontakt_privat_setzen(lead))
    assert "fehler" not in antwort
    assert server._privat(_enrichment(lead)) is True
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'kontakt_privat'", (lead,))
    assert len(zeilen) == 1 and zeilen[0]["payload"]["privat"] is True


def test_entziehen_macht_wieder_sichtbar():
    lead = _lead()
    server.kontakt_privat_setzen(lead)
    antwort = json.loads(server.kontakt_privat_entziehen(lead))
    assert "fehler" not in antwort
    assert server._privat(_enrichment(lead)) is False


def test_der_sammelkontakt_kann_nicht_privat_sein(monkeypatch):
    lead = _lead("Unbekannte Eingaenge")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", lead)
    antwort = json.loads(server.kontakt_privat_setzen(lead))
    assert "fehler" in antwort


@pytest.mark.parametrize("wert,erwartet", [
    (None, False), ({}, False), ({"_privat": None}, False),
    ({"_privat": "ja"}, False),
    ({"_privat": {"privat": True}}, True),
    ({"_privat": {"privat": False}}, False),
    ({"_privat": {"kaputt": 1}}, True),   # Schutzrichtung
])
def test_der_leser_ist_fail_closed_in_schutzrichtung(wert, erwartet):
    assert server._privat(wert) is erwartet


# ---------------------------------------------------------------------------
# Der Vollstopp
# ---------------------------------------------------------------------------

def test_kein_verlauf_fuer_den_bot():
    lead = _lead()
    _nachrichten(lead)
    server.kontakt_privat_setzen(lead)
    antwort = json.loads(server.chat_verlauf(lead))
    assert "fehler" in antwort
    assert "privat" in antwort["fehler"].lower()


def test_keine_entwuerfe_mehr():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "Telefonat", "Ja")
    server.kontakt_privat_setzen(lead)
    for versuch in (server.antwort_entwerfen(lead, "Hallo!"),
                    server.entwurf_erstellen(lead, "whatsapp", "Hallo!")):
        antwort = json.loads(versuch)
        assert "fehler" in antwort
        assert "privat" in antwort["fehler"].lower()
    assert server._q("select count(*) n from drafts where lead_id = %s",
                     (lead,))[0]["n"] == 0


def test_in_keiner_faelligkeitsliste():
    lead = _lead()
    _nachrichten(lead)
    server.kontakt_privat_setzen(lead)
    assert lead not in {str(z["lead_id"]) for z in server._profil_faellig()}
    assert lead not in {str(z["lead_id"])
                        for z in server._chat_faellig(schwelle=3)}
    faellig = json.loads(server.antworten_faellig())
    assert lead not in {str(e.get("lead_id")) for e in faellig["eintraege"]}


def test_die_auskunft_funktioniert_weiter():
    """Art. 15 ist das Recht der PERSON — privat markiert heisst still
    fuer den Vertrieb, nicht rechtlos."""
    lead = _lead()
    _nachrichten(lead, 2)
    server.kontakt_privat_setzen(lead)
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert "fehler" not in antwort
    assert "privates 0" in antwort["text"]
