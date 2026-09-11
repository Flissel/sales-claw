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


def _vevent_zeilen(text, ausschluss=()):
    """Die (entfalteten) Zeilen des VEVENT-Blocks, ohne die per `ausschluss`
    benannten Feldnamen. Fuer den Aequivalenzvergleich zwischen `ics()` und
    `ics_einladung()` unten."""
    zeilen = _zeilen(text)
    start = zeilen.index("BEGIN:VEVENT")
    ende = zeilen.index("END:VEVENT")
    block = zeilen[start:ende + 1]
    return [z for z in block if not any(z.startswith(p) for p in ausschluss)]


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
    """Echte Aequivalenz, nicht nur zwei herausgegriffene Teilstrings: alle
    Felder im VEVENT-Block muessen zwischen `ics()` und `ics_einladung()`
    identisch sein (UID, DTSTAMP, DTSTART, DTEND, SUMMARY, DESCRIPTION,
    STATUS, TRANSP, ...). Ausgenommen sind genau die Felder, die eine
    Einladung zusaetzlich traegt: ORGANIZER, ATTENDEE, SEQUENCE. `METHOD`
    faellt hier gar nicht erst an — es liegt ausserhalb des VEVENT-Blocks.

    Ein Fehler, der z. B. SUMMARY oder DTEND nur in der Einladungsfassung
    verfaelscht, faellt damit auf; die alte Fassung mit zwei fest
    verdrahteten `in`-Pruefungen haette das nicht bemerkt.
    """
    stempel = datetime(2026, 9, 11, 8, 0)
    gemeinsam = dict(uid="abc-123", beginn=datetime(2026, 10, 1, 14, 30),
                     dauer_minuten=30, summary="Erstgespräch", jetzt=stempel)
    eintrag = kalender.ics(**gemeinsam)
    einladung = kalender.ics_einladung(
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"], **gemeinsam)
    eintrag_vevent = _vevent_zeilen(eintrag)
    einladung_vevent = _vevent_zeilen(
        einladung, ausschluss=("ORGANIZER", "ATTENDEE", "SEQUENCE"))
    assert eintrag_vevent == einladung_vevent


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


def test_lange_attendee_zeile_wird_gefaltet():
    """Die Faltung greift bei jeder realen Einladung — schon das reine
    ATTENDEE-Praefix (`ATTENDEE;CUTYPE=...;RSVP=TRUE:mailto:`) ist 87 Oktette
    lang, also VOR jeder Adresse bereits ueber der 75-Oktette-Grenze aus
    RFC 5545 §3.1. `_zeilen()` in den Tests oben entfaltet aber vor dem
    Vergleich — genau die Faltung wuerde also unbemerkt verschwinden koennen
    (die Suite bliebe gruen, Empfaenger wuerden die Einladung stumm
    verwerfen). Deshalb hier auf der ROHEN, ungefalteten Ausgabe pruefen.
    """
    lange_adresse = "sehr-lange-adresse-fuer-die-faltung-xyz@beispiel-domain.de"
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space", eingeladene=[lange_adresse])
    # Letztes Element ist "" wegen des abschliessenden CRLF.
    physische_zeilen = [z for z in text.split("\r\n") if z != ""]
    for zeile in physische_zeilen:
        assert len(zeile.encode("utf-8")) <= 75, zeile
    attendee_index = next(
        i for i, z in enumerate(physische_zeilen) if z.startswith("ATTENDEE"))
    fortsetzung = physische_zeilen[attendee_index + 1]
    assert fortsetzung.startswith(" "), (
        "ATTENDEE-Zeile mit langer Adresse wurde nicht gefaltet: "
        f"{fortsetzung!r}")


def test_mailto_praefix_wird_entfernt_und_nicht_verdoppelt():
    """`veranstalter` mit einem bereits vorhandenen `mailto:`-Praefix darf
    kein `mailto:mailto:` erzeugen."""
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="mailto:felix@vibemind.space",
        eingeladene=["mailto:ivan@vibemind.space"])
    zeilen = _zeilen(text)
    assert "ORGANIZER:mailto:felix@vibemind.space" in zeilen
    assert "ORGANIZER:mailto:mailto:felix@vibemind.space" not in zeilen
    teilnehmer = [z for z in zeilen if z.startswith("ATTENDEE")]
    assert any(z.endswith(":mailto:ivan@vibemind.space") for z in teilnehmer)
    assert not any("mailto:mailto:" in z for z in teilnehmer)


def test_mehr_als_zwei_eingeladene():
    """Mehr als zwei Eingeladene erzeugen entsprechend viele ATTENDEE-Zeilen
    — die Vertragstests oben pruefen nur zwei, das darf keine verdeckte
    Obergrenze sein."""
    eingeladene = ["a@beispiel.de", "b@beispiel.de", "c@beispiel.de",
                   "d@beispiel.de"]
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space", eingeladene=eingeladene)
    teilnehmer = [z for z in _zeilen(text) if z.startswith("ATTENDEE")]
    assert len(teilnehmer) == len(eingeladene), teilnehmer
    for adresse in eingeladene:
        assert any(z.endswith(f":mailto:{adresse}") for z in teilnehmer), adresse


def test_negative_folge_wird_abgelehnt():
    """`folge` ist eine SEQUENCE (RFC 5545 §3.8.7.4) und damit ein
    nicht-negativer Zaehler — ein negativer Wert wuerde klaglos
    `SEQUENCE:-1` erzeugen und ist keine gueltige Aenderungsstufe."""
    with pytest.raises(ValueError):
        kalender.ics_einladung(
            "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
            veranstalter="felix@vibemind.space",
            eingeladene=["ivan@vibemind.space"], folge=-1)
