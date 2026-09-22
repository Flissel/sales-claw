"""Volltextsuche ueber den Gespraechsverlauf (22.09.2026).

`kontakt_suchen` findet Stammdaten, `kontakt_aehnlich` Schreibweisen — den
FREITEXT der Aktivitaeten durchsuchte bis hierher niemand. Gemessen am
17.09.2026 lagen dort 6397 Texte, und die einzige Art heranzukommen war ein
geratenes `ILIKE`-Muster.

Was diese Tests festhalten, ist zur Haelfte, was die Suche NICHT kann. Das ist
kein Pessimismus, sondern der Grund, warum sie ueberhaupt dokumentiert gehoert:
wer die Grenzen nicht kennt, liest aus einem leeren Ergebnis „das Ereignis gab
es nicht" — und genau dieser Fehlschluss ist am 17.09. beinahe passiert.

  * Der deutsche Stemmer trennt Substantiv und Verb: „gewechselt" findet
    „Wechsel" nicht.
  * Verneinung wird ignoriert: „kein Interesse" liefert Interessenten.
  * Kennungen (`message_id`, `draft_id`) stehen NICHT im Index — sonst
    erzeugten sie Treffer, die nur zufaellig Zeichen teilen.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
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
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.leads cascade")
    yield


def _lead(name="Ivan"):
    return server._q(
        "insert into leads (name, source) values (%s, 'test') returning id",
        (name,))[0]["id"]


def _aktivitaet(lead, text, art="kundenantwort", schluessel="text"):
    return server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, %s, jsonb_build_object(%s::text, %s::text)) returning id",
        (lead, art, schluessel, text))[0]["id"]


def _suchen(frage, **kw):
    return json.loads(server.gespraeche_suchen(frage, **kw))


def test_findet_den_satz_im_gespraechsverlauf():
    lead = _lead()
    _aktivitaet(lead, "Kann ich dir morgen einen Beratungstermin einstellen?")
    treffer = _suchen("Beratungstermin")["treffer"]
    assert len(treffer) == 1
    assert treffer[0]["name"] == "Ivan"
    assert "<<" in treffer[0]["ausschnitt"], "Fundstelle soll markiert sein"


def test_mehrere_woerter_werden_und_verknuepft():
    lead = _lead()
    _aktivitaet(lead, "Wir sprechen ueber Vorsorge und Versicherung.")
    _aktivitaet(lead, "Heute nur ueber Vorsorge.")
    assert len(_suchen("Vorsorge Versicherung")["treffer"]) == 1
    assert len(_suchen("Vorsorge")["treffer"]) == 2


def test_beugung_wird_gefunden_dieselbe_wortfamilie():
    """Wofuer der Stemmer da ist: gebeugte Formen derselben Wortart."""
    lead = _lead()
    _aktivitaet(lead, "Die Versicherungen sind alle beim ADAC.")
    assert _suchen("Versicherung")["treffer"], "Plural soll den Singular finden"


def test_GRENZE_stemmer_trennt_substantiv_und_verb():
    """Gemessen 17.09.2026 am echten Bestand: null Treffer.

    Der Satz lautete „Falscher Ivan hat Nummer Wechsel gehabt", gesucht
    wurde „Nummer gewechselt" — der Stemmer fuehrt beide NICHT zusammen.
    Dieser Test haelt die Grenze fest, damit niemand spaeter aus einem
    leeren Ergebnis schliesst, es sei nichts passiert.
    """
    lead = _lead()
    _aktivitaet(lead, "Falscher Ivan hat Nummer Wechsel gehabt")
    assert _suchen("Nummer gewechselt")["treffer"] == []
    # Mit der richtigen Wortform dagegen sofort:
    assert len(_suchen("Nummer Wechsel")["treffer"]) == 1


def test_GRENZE_verneinung_wird_ignoriert():
    """„kein" verschwindet als Stoppwort — der Treffer ist das Gegenteil."""
    lead = _lead()
    _aktivitaet(lead, "Ich habe grosses Interesse an dem Angebot.")
    treffer = _suchen("kein Interesse")["treffer"]
    assert len(treffer) == 1, "die Verneinung filtert nichts weg"


def test_der_hinweis_nennt_beide_grenzen():
    """Sie stehen in der Antwort, nicht nur im Quelltext — der Agent liest
    die Antwort, nicht den Docstring."""
    hinweis = _suchen("egal")["hinweis"]
    assert "Wechsel" in hinweis and "Verneinung" in hinweis


def test_kennungen_stehen_nicht_im_index():
    """`message_id` trug 6155 Werte. Im Volltextindex erzeugten sie Treffer,
    die nur zufaellig Zeichen teilen."""
    lead = _lead()
    _aktivitaet(lead, "ABC123XYZ", schluessel="message_id")
    assert _suchen("ABC123XYZ")["treffer"] == []


def test_auch_inhalt_und_begruendung_werden_durchsucht():
    lead = _lead()
    _aktivitaet(lead, "Routinelauf mit Terminkarte", schluessel="inhalt")
    _aktivitaet(lead, "Abgelehnt wegen Sperrliste", schluessel="begruendung")
    assert len(_suchen("Terminkarte")["treffer"]) == 1
    assert len(_suchen("Sperrliste")["treffer"]) == 1


def test_leere_frage_wird_abgewiesen():
    assert "fehler" in _suchen("   ")


def test_unsinnige_grenze_wird_abgewiesen_statt_zu_stuerzen():
    assert "fehler" in _suchen("Termin", grenze="viele")


def test_grenze_wird_gedeckelt():
    lead = _lead()
    for i in range(4):
        _aktivitaet(lead, f"Termin Nummer {i} steht an")
    assert len(_suchen("Termin", grenze=2)["treffer"]) == 2
