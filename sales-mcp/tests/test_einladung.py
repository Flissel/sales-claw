"""Vertragstests der Einladungs-Kalenderdaten (Termin-Einladungen).

Eine Einladung ist NICHT dieselbe Datei wie der Kalendereintrag: RFC 4791
verbietet `METHOD:` auf einem CalDAV-Server, RFC 5546 verlangt es fuer eine
Einladung. Beide Fassungen beschreiben dieselbe Buchung unter derselben UID.
"""
import os
from datetime import datetime

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402


def _zeilen(text):
    """Entfaltet die ICS-Faltung und liefert die Zeilen."""
    roh = text.replace("\r\n ", "").replace("\r\n\t", "")
    return roh.split("\r\n")


def test_einladung_traegt_method_request():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"])
    assert "METHOD:REQUEST" in _zeilen(text)


def test_einladung_nennt_veranstalter_und_eingeladene():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space", "kunde@beispiel.de"])
    zeilen = _zeilen(text)
    assert "ORGANIZER:mailto:felix@vibemind.space" in zeilen
    teilnehmer = [z for z in zeilen if z.startswith("ATTENDEE")]
    assert len(teilnehmer) == 2, teilnehmer
    assert all("RSVP=TRUE" in z for z in teilnehmer), teilnehmer
    assert all("PARTSTAT=NEEDS-ACTION" in z for z in teilnehmer), teilnehmer
    assert any(z.endswith(":mailto:ivan@vibemind.space") for z in teilnehmer)


def test_kalendereintrag_bleibt_ohne_method():
    """Die bestehende Fassung darf sich NICHT aendern — SabreDAV lehnt
    `METHOD:` mit HTTP 415 ab."""
    text = kalender.ics("abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch")
    assert "METHOD" not in text


def test_beide_fassungen_beschreiben_dieselbe_buchung():
    stempel = datetime(2026, 9, 11, 8, 0)
    gemeinsam = dict(uid="abc-123", beginn=datetime(2026, 10, 1, 14, 30),
                     dauer_minuten=30, summary="Erstgespräch", jetzt=stempel)
    eintrag = _zeilen(kalender.ics(**gemeinsam))
    einladung = _zeilen(kalender.ics_einladung(
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"], **gemeinsam))
    for feld in ("UID:abc-123", "DTSTART;TZID=Europe/Berlin:20261001T143000"):
        assert feld in eintrag, feld
        assert feld in einladung, feld


def test_folge_erscheint_als_sequence():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"], folge=2)
    assert "SEQUENCE:2" in _zeilen(text)


def test_adressen_werden_geprueft():
    """Eine Zeichenkette ohne @ ist keine Adresse und darf nicht durchrutschen."""
    with pytest.raises(ValueError):
        kalender.ics_einladung(
            "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
            veranstalter="kein-at-zeichen", eingeladene=["ivan@vibemind.space"])
    with pytest.raises(ValueError):
        kalender.ics_einladung(
            "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
            veranstalter="felix@vibemind.space", eingeladene=[])
