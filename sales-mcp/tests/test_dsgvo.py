"""Vertragstests fuer das DSGVO-Handwerk (P2, 27.08.2026).

Bisher stand nur im Docstring von kontakt_archivieren: ein echtes
Loeschbegehren ist ein Admin-Eingriff ausserhalb dieser Werkzeuge. P2
macht daraus zwei definierte Ablaeufe: Auskunft (Art. 15) als Export,
Loeschantrag (Art. 17) als Vermerk, der SOFORT jede weitere Verarbeitung
stoppt — die physische Loeschung bleibt bewusst ein dokumentierter
Menschen-Schritt (docs/06_DSGVO.md).

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Die Auskunft ist vollstaendig oder sie ist keine: Stammdaten,
   Anreicherung, jede Protokollzeile, jeder Entwurf.
2. Ein vermerkter Loeschantrag stoppt ALLES: keine neuen Entwuerfe, kein
   Auto-Betrieb, kein stilles Zurueckholen aus dem Archiv.
3. Es gibt weiterhin KEIN Loesch-Werkzeug — der Vermerk ist Schutz, die
   Loeschung ist ein Menschen-Schritt mit Vier-Augen.
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


def _lead(name="Dora Datenschutz"):
    # existing_customer: UWG-Erstansprache-Tor (test_uwg.py) ist nicht Thema.
    lead = str(server._q(
        "insert into leads (name, phone, email, source, consent_status) "
        "values (%s, '+491709998877', 'dora@example.org', 'whatsapp', "
        "'existing_customer') returning id", (name,))[0]["id"])
    server.kontakt_freigeben(lead)
    return lead


def _enrichment(lead):
    return server._q("select enrichment from leads where id = %s",
                     (lead,))[0]["enrichment"]


# ---------------------------------------------------------------------------
# Auskunft — vollstaendig oder keine
# ---------------------------------------------------------------------------

def test_die_auskunft_traegt_alle_vier_abschnitte():
    lead = _lead()
    server.aktivitaet_loggen(lead, "notiz", "Rueckruf gewuenscht")
    server.entwurf_erstellen(lead, "whatsapp", "Hallo Dora!")
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert "fehler" not in antwort
    text = antwort["text"]
    for abschnitt in ("# Datenauskunft", "## Stammdaten", "## Anreicherung",
                      "## Protokoll", "## Entwuerfe"):
        assert abschnitt in text
    assert "Dora Datenschutz" in text
    assert "Rueckruf gewuenscht" in text
    assert "Hallo Dora!" in text
    assert antwort["protokollzeilen"] >= 2  # freigabe + notiz mindestens
    assert antwort["entwuerfe"] == 1


def test_auskunft_unbekannter_kontakt_ist_eine_meldung():
    antwort = json.loads(server.kontakt_auskunft(
        "00000000-0000-0000-0000-000000000000"))
    assert "fehler" in antwort


# ---------------------------------------------------------------------------
# Loeschantrag — Vermerk, Archiv, Vollstopp
# ---------------------------------------------------------------------------

def test_der_antrag_vermerkt_archiviert_und_protokolliert():
    lead = _lead()
    antwort = json.loads(server.loeschantrag_vermerken(
        lead, "WhatsApp-Nachricht", "bitte loeschen Sie meine Daten"))
    assert "fehler" not in antwort
    anr = _enrichment(lead)
    assert anr["_loeschantrag"]["quelle"] == "WhatsApp-Nachricht"
    assert anr["_loeschantrag"]["am"]
    assert server._archiviert(anr) is True
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'loeschantrag'", (lead,))
    assert len(zeilen) == 1


def test_ohne_quelle_kein_vermerk():
    lead = _lead()
    antwort = json.loads(server.loeschantrag_vermerken(lead, "  "))
    assert "fehler" in antwort
    assert server._loeschantrag(_enrichment(lead)) is None


def test_zweiter_antrag_ist_eine_meldung():
    lead = _lead()
    server.loeschantrag_vermerken(lead, "Telefonat")
    antwort = json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert "fehler" in antwort
    assert "liegt bereits vor" in antwort["fehler"]


def test_nach_dem_antrag_entsteht_kein_entwurf_mehr():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "Telefonat", "Ja gerne")
    server.loeschantrag_vermerken(lead, "WhatsApp-Nachricht")
    for versuch in (
            server.antwort_entwerfen(lead, "Noch eine Antwort."),
            server.entwurf_erstellen(lead, "whatsapp", "Hallo?")):
        antwort = json.loads(versuch)
        assert "fehler" in antwort
        assert "Loeschantrag" in antwort["fehler"]
    assert server._q("select count(*) n from drafts where lead_id = %s",
                     (lead,))[0]["n"] == 0


def test_kein_stilles_zurueckholen_aus_dem_archiv():
    lead = _lead()
    server.loeschantrag_vermerken(lead, "Telefonat")
    antwort = json.loads(server.kontakt_wiederherstellen(lead))
    assert "fehler" in antwort
    assert "Loeschantrag" in antwort["fehler"]
    assert server._archiviert(_enrichment(lead)) is True


def test_der_antrag_taucht_in_der_auskunft_auf():
    """Auch der Antrag selbst ist ein Datum ueber die Person — die
    Auskunft nennt ihn."""
    lead = _lead()
    server.loeschantrag_vermerken(lead, "E-Mail", "loeschen bitte")
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert "Loeschantrag" in antwort["text"]


@pytest.mark.parametrize("kaputt", [
    None, {}, {"_loeschantrag": None}, {"_loeschantrag": "ja"},
])
def test_kein_antrag_ist_kein_antrag(kaputt):
    assert server._loeschantrag(kaputt) is None


def test_ein_kaputter_vermerk_schuetzt_trotzdem():
    """Fail-closed in Schutzrichtung: ein dict-Vermerk ohne Datum zaehlt
    ALS Antrag — lieber zu viel gestoppt als weiterverarbeitet."""
    assert server._loeschantrag({"_loeschantrag": {"quelle": "?"}}) is not None
