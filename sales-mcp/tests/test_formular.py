"""Setzprogramm fuer Formular-Vorlagen (Terminkarten, spaeter Fiko-Heft).

Der Kern-Vertrag: Musterblatt und ausgefuellte Karte kommen aus DEMSELBEN
Aufruf `formular.setzen(gestalt, werte)`. Eine Freigabe gilt sonst fuer ein
anderes Blatt als das, das gedruckt wird.
"""
import io

from pypdf import PdfReader

import formular

GESTALT = {
    "seite": {"breite_mm": 148, "hoehe_mm": 105},
    "texte": [{"text": "TERMINKARTE", "platz": {"x": 8, "y": 6, "breite": 80, "hoehe": 8},
               "groesse": 14}],
    "felder": [
        {"name": "kunde", "beschriftung": "Kunde", "art": "text", "quelle": "kunde.name",
         "platz": {"x": 8, "y": 20, "breite": 60, "hoehe": 12}},
        {"name": "datum", "beschriftung": "Datum", "art": "datum", "quelle": "termin.datum",
         "platz": {"x": 80, "y": 20, "breite": 60, "hoehe": 12}},
        {"name": "notiz", "beschriftung": "Notiz", "art": "mehrzeilig", "quelle": "frei",
         "platz": {"x": 8, "y": 40, "breite": 132, "hoehe": 30}},
    ],
}


def _text(pdf: bytes) -> str:
    return "".join(s.extract_text() for s in PdfReader(io.BytesIO(pdf)).pages)


def test_eine_seite_im_format_der_gestalt():
    seiten = PdfReader(io.BytesIO(formular.setzen(GESTALT, {}))).pages
    assert len(seiten) == 1
    breite, hoehe = float(seiten[0].mediabox.width), float(seiten[0].mediabox.height)
    assert round(breite / 72 * 25.4) == 148 and round(hoehe / 72 * 25.4) == 105


def test_beschriftungen_feste_texte_und_werte_stehen_auf_dem_blatt():
    text = _text(formular.setzen(GESTALT, {"kunde": "Jürgen Müßig", "datum": "24.09.2026"}))
    for erwartet in ("TERMINKARTE", "Kunde", "Datum", "Notiz", "Jürgen Müßig", "24.09.2026"):
        assert erwartet in text, erwartet


def test_ein_langer_wert_wird_umbrochen_nicht_abgeschnitten():
    lang = "Anneliese Kowalczyk-Schwarzenberger von der Heydt-Oberlausitz"
    text = " ".join(_text(formular.setzen(GESTALT, {"kunde": lang})).split())
    for wort in lang.split():
        assert wort in text, wort


def test_leere_felder_sind_kein_fehler():
    assert _text(formular.setzen(GESTALT, {})).count("Kunde") == 1


def test_zeichen_ausserhalb_latin1_stuerzen_nicht():
    text = _text(formular.setzen(GESTALT, {"kunde": "Łukasz Żółć 🙂"}))
    assert "Lukasz" in text


def test_musterblatt_und_karte_sind_derselbe_aufruf():
    muster = formular.beispielwerte(GESTALT)
    assert set(muster) == {"kunde", "datum", "notiz"}
    assert "Muster" in _text(formular.setzen(GESTALT, muster))


def test_wert_der_nur_nach_schrumpfen_passt_ist_vollstaendig():
    """Ein langer Wert, der nach Größenverkleinerung passt, wird vollständig angezeigt."""
    lang = "Anneliese Kowalczyk-Schwarzenberger"
    text = " ".join(_text(formular.setzen(GESTALT, {"kunde": lang})).split())
    for wort in lang.split():
        assert wort in text, wort


def test_zu_langer_wert_hebt_passt_nicht_exception():
    """Ein Wert, der nicht mal bei minimaler Schrift passt, wirft PasstNicht."""
    # Kleines Feld mit großem Text
    gestalt_klein = {
        "seite": {"breite_mm": 148, "hoehe_mm": 105},
        "texte": [],
        "felder": [
            {"name": "kunde", "beschriftung": "Kunde", "art": "text", "quelle": "kunde.name",
             "platz": {"x": 8, "y": 20, "breite": 30, "hoehe": 5}},
        ],
    }
    zu_lang = "Antidisestablishmentarianism Floccinaucinilicilification Pneumonoultramicroscopicsilicovolcanoconiosis extra extra extra"
    try:
        formular.setzen(gestalt_klein, {"kunde": zu_lang})
        assert False, "Expected PasstNicht exception"
    except formular.PasstNicht as e:
        assert "Kunde" in str(e)
        assert "zu lang" in str(e)


def test_feld_am_seitenende_passt_wenn_es_klein_genug_ist():
    """Ein Feld nahe am Seitenende mit ausreichend kleinem Wert passt ohne Exception."""
    # Feld fast ganz unten mit wenig Platz
    gestalt_oben = {
        "seite": {"breite_mm": 148, "hoehe_mm": 105},
        "texte": [],
        "felder": [
            {"name": "test", "beschriftung": "Test", "art": "text", "quelle": "test",
             "platz": {"x": 8, "y": 95, "breite": 60, "hoehe": 8}},
        ],
    }
    # Kurzer Wert sollte passen
    pdf = formular.setzen(gestalt_oben, {"test": "OK"})
    text = _text(pdf)
    assert "OK" in text
    assert "Test" in text
