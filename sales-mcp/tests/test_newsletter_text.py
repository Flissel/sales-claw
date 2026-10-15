"""Newsletter an Kontakte: Vorname und Platzhalter (reine Funktionen, ohne Datenbank).
Plan: docs/superpowers/plans/2026-10-15-newsletter-versand-an-kontakte.md"""
import pytest

import newsletter_text as nt


@pytest.mark.parametrize("name, firma, erwartet", [
    ("Anna Weber", "", "Anna"),
    ("Dr. Anna Weber", "", "Anna"),
    ("Frau Prof. Dr. Anna-Lena Weber", "", "Anna-Lena"),
    ("Herr Weber", "", ""),            # nur Anrede + Nachname: kein Vorname
    ("Weber GmbH", "Weber GmbH", ""),  # Firma
    ("info@laden.de", "", ""),
    ("", "", ""),
    ("  anna  ", "", ""),              # ein Wort: Vor- oder Nachname? Im Zweifel leer
    ("  anna   weber ", "", "Anna"),
])
def test_vorname_vorschlag(name, firma, erwartet):
    assert nt.vorname_vorschlag(name, firma) == erwartet


def test_vorname_feld_hat_vorrang():
    assert nt.vorname({"vorname": " Lena ", "name": "Anna Weber"}) == "Lena"
    assert nt.vorname({"vorname": None, "name": "Anna Weber", "company": ""}) == "Anna"


def test_einsetzen_mit_vorname_escaped():
    html, text = nt.einsetzen("<p>Hallo {vorname},</p><p>{abmeldelink}</p>", "Hallo {vorname},\n{abmeldelink}",
                              "Ann<a>", "laden@example.de")
    assert "Hallo Ann&lt;a&gt;," in html and "<a>" not in html.replace('<a href', '')
    assert 'href="mailto:laden@example.de?subject=Abmelden"' in html
    assert text.startswith("Hallo Ann<a>,") and "mailto:laden@example.de?subject=Abmelden" in text


def test_einsetzen_ohne_vorname_faellt_sauber_weg():
    html, text = nt.einsetzen("<p>Hallo {vorname},</p><p>Liebe/r {vorname}!</p>", "Hallo {vorname},", "", "a@b.de")
    assert "<p>Hallo,</p>" in html and "{vorname}" not in html
    assert text == "Hallo,"


def test_einsetzen_ohne_absender_bricht_ab():
    with pytest.raises(ValueError):
        nt.einsetzen("{abmeldelink}", "", "Anna", "")
