"""Bestaetigungsmails der Warteliste: Lesen, Wortlaut, Versandlauf - ohne
Datenbank und ohne Mailserver (beide kommen als Funktionen herein).

Dass die fertige Mail den Link auch in der HTML-Fassung traegt, steht in
test_warteliste_bestaetigung_mail.py (braucht mail_dispatch)."""
import io
import json

import pytest

import verlinken
import warteliste_bestaetigung as wb

TOKEN = "c3" * 32
TOKEN2 = "d4" * 32


def _zeile(email, token=TOKEN):
    return {"email": email, "token": token}


def _dok(*zeilen):
    return {"generated_at": "2026-11-13T18:00:00+00:00", "count": len(zeilen), "rows": list(zeilen)}


# --- Lesen ---------------------------------------------------------------------

def test_lesen_nimmt_nur_brauchbare_zeilen():
    eintraege, unbrauchbar = wb.eintraege_lesen(_dok(
        _zeile("anna@example.org"),
        _zeile("anna@example.org", TOKEN2),              # doppelt: eine Mail, erste Zeile
        _zeile("Anna@Example.org"),                      # die Website liefert klein - sonst unbrauchbar
        _zeile("kein-at-zeichen"),
        _zeile("b@example.org", "kurz"),
        _zeile("c@example.org", TOKEN.upper()),
        _zeile("d@example.org\nBcc: x@example.org"),
        {"email": "e@example.org"},
        "keine Zeile",
        _zeile("f@example.org", TOKEN2)))
    assert eintraege == [("anna@example.org", TOKEN), ("f@example.org", TOKEN2)]
    assert unbrauchbar == 7


@pytest.mark.parametrize("dokument", [
    None, [], {}, {"rows": "x"}, {"code": "42501", "message": "not allowed"},
    {"count": 3, "rows": [_zeile("a@example.org")]},      # abgeschnitten
    {"rows": [_zeile("a@example.org")]},                   # count fehlt
    _dok(*[_zeile(f"a{i}@example.org") for i in range(wb.HOECHSTENS + 1)]),
])
def test_lesen_weist_fremde_dokumente_ab(dokument):
    with pytest.raises(wb.EingabeFehler):
        wb.eintraege_lesen(dokument)


def test_lesen_leere_warteschlange():
    assert wb.eintraege_lesen(_dok()) == ([], 0)


# --- Wortlaut ------------------------------------------------------------------

def test_rumpf_traegt_den_link_mit_token_als_pfadstueck():
    text = wb.rumpf(TOKEN)
    assert f"https://vibemind.space/waitlist/confirm/{TOKEN}\n" in text
    assert "seven days" in text and "ignore this mail" in text


def test_link_enthaelt_kein_zeichen_das_ein_mailprogramm_umkodiert():
    """14.11.2026: GMX machte aus dem `#` vor dem Token ein `%23`, der
    Empfaenger sah eine 404-Seite. Im Link stehen nur Zeichen, an denen eine
    Link-Weiterleitung nichts zu aendern hat."""
    import re
    for seite in (wb.SEITE, "https://staging.example/w/confirm", "https://staging.example/w/confirm/"):
        zeile = next(z for z in wb.rumpf(TOKEN, seite).splitlines() if TOKEN in z)
        assert re.fullmatch(r"https://[a-z0-9.-]+(/[A-Za-z0-9_-]+)+", zeile), zeile
        assert zeile.endswith(f"/confirm/{TOKEN}")


def test_rumpf_eigene_seite_und_unbrauchbare_eingaben():
    assert f"https://staging.example/w/confirm/{TOKEN}" in wb.rumpf(TOKEN, "https://staging.example/w/confirm")
    for seite in ("http://vibemind.space/waitlist/confirm", "https://vibemind.space/x?y=1",
                  "https://vibemind.space/x#y", "javascript:alert(1)", ""):
        with pytest.raises(ValueError):
            wb.rumpf(TOKEN, seite)
    for token in ("", "kurz", TOKEN + "0", TOKEN.upper(), TOKEN[:-1] + "\n"):
        with pytest.raises(ValueError):
            wb.rumpf(token)


def test_link_bleibt_in_der_html_fassung_ganz():
    """Die HTML-Fassung baut mail_dispatch mit verlinken.text_html - der Token
    muss Teil des Links bleiben."""
    html = verlinken.text_html(wb.rumpf(TOKEN))
    assert f'<a href="https://vibemind.space/waitlist/confirm/{TOKEN}">' in html


def test_betreff_und_rumpf_ohne_platzhalter_reste():
    text = wb.rumpf(TOKEN)
    assert "{" not in text and "}" not in text
    assert "\n" not in wb.BETREFF and len(wb.BETREFF) < 80


# --- Versandlauf ---------------------------------------------------------------

class _Post:
    def __init__(self, scheitert=()):
        self.gesendet, self.scheitert = [], set(scheitert)

    def __call__(self, adresse, betreff, text):
        if adresse in self.scheitert:
            raise RuntimeError(f"Mailserver weist den Empfaenger zurueck: {adresse}")
        self.gesendet.append((adresse, betreff, text))


def test_verschicken_eine_mail_je_adresse():
    post = _Post()
    ergebnis = wb.verschicken([("a@example.org", TOKEN), ("b@example.org", TOKEN2)],
                              gesperrt=lambda a: False, senden=post)
    assert ergebnis == {"gesendet": 2, "gesperrt": 0, "fehler": 0, "erneut": []}
    assert [a for a, _, _ in post.gesendet] == ["a@example.org", "b@example.org"]
    assert post.gesendet[0][1] == wb.BETREFF
    assert f"/{TOKEN}" in post.gesendet[0][2] and TOKEN2 not in post.gesendet[0][2]
    assert f"/{TOKEN2}" in post.gesendet[1][2]


def test_verschicken_gesperrte_bekommen_nichts_und_werden_nicht_wiederholt():
    post = _Post()
    ergebnis = wb.verschicken([("a@example.org", TOKEN), ("b@example.org", TOKEN2)],
                              gesperrt=lambda a: a == "a@example.org", senden=post)
    assert ergebnis == {"gesendet": 1, "gesperrt": 1, "fehler": 0, "erneut": []}
    assert [a for a, _, _ in post.gesendet] == ["b@example.org"]


def test_verschicken_fehler_gehen_zurueck_und_der_lauf_geht_weiter():
    post, warnungen = _Post(scheitert={"a@example.org"}), []
    ergebnis = wb.verschicken([("a@example.org", TOKEN), ("b@example.org", TOKEN2)],
                              gesperrt=lambda a: False, senden=post, warnen=warnungen.append)
    assert ergebnis == {"gesendet": 1, "gesperrt": 0, "fehler": 1, "erneut": ["a@example.org"]}
    assert len(warnungen) == 1
    assert "a@example.org" not in warnungen[0] and "a…@example.org" in warnungen[0]
    assert TOKEN not in warnungen[0]


def test_verschicken_ohne_lesbare_verbotsliste_geht_nichts_raus():
    def kaputt(_adresse):
        raise ConnectionError("Datenbank weg")
    post, warnungen = _Post(), []
    ergebnis = wb.verschicken([("a@example.org", TOKEN)], gesperrt=kaputt, senden=post,
                              warnen=warnungen.append)
    assert ergebnis == {"gesendet": 0, "gesperrt": 0, "fehler": 1, "erneut": ["a@example.org"]}
    assert post.gesendet == []
    assert "a@example.org" not in warnungen[0]


def test_verschicken_pausiert_zwischen_den_mails_nicht_davor():
    pausen = []
    wb.verschicken([("a@example.org", TOKEN), ("b@example.org", TOKEN2), ("c@example.org", TOKEN)],
                   gesperrt=lambda a: False, senden=_Post(), pause=1.5, schlafen=pausen.append)
    assert pausen == [1.5, 1.5]


# --- CLI -----------------------------------------------------------------------

def _lauf(argumente, eingabe, werkzeuge=None):
    aus, err = io.StringIO(), io.StringIO()
    code = wb.main(argumente, eingabe=io.StringIO(eingabe), ausgabe=aus, fehlerausgabe=err,
                   werkzeuge=werkzeuge)
    return code, aus.getvalue(), err.getvalue()


def _verboten():
    raise AssertionError("bei dieser Eingabe darf der Laden nicht angefasst werden")


@pytest.mark.parametrize("eingabe", ["", "   ", "kein json", "[]", '{"code":"42501"}',
                                     '{"count": 2, "rows": []}'])
def test_cli_unbrauchbare_eingabe_versendet_nichts(eingabe):
    code, aus, err = _lauf(["senden"], eingabe, _verboten)
    assert code == 2 and aus == "" and "nichts versendet" in err


def test_cli_unbekannte_argumente():
    assert _lauf([], json.dumps(_dok()), _verboten)[0] == 2
    assert _lauf(["senden", "--trocken"], json.dumps(_dok()), _verboten)[0] == 2
    assert _lauf(["senden", "--seite", "http://x.example"], json.dumps(_dok()), _verboten)[0] == 2


def test_cli_leere_warteschlange_fasst_den_laden_nicht_an():
    code, aus, err = _lauf(["senden"], json.dumps(_dok()), _verboten)
    assert code == 0 and aus == "[]\n"
    assert json.loads(err) == {"gesendet": 0, "gesperrt": 0, "fehler": 0, "unbrauchbar": 0}


def test_cli_versendet_und_meldet_nur_zahlen():
    post = _Post()
    code, aus, err = _lauf(["senden", "--seite", "https://staging.example/confirm"],
                           json.dumps(_dok(_zeile("a@example.org"), _zeile("kaputt"))),
                           lambda: (lambda a: False, post, 0.0))
    assert code == 0 and aus == "[]\n"
    assert json.loads(err) == {"gesendet": 1, "gesperrt": 0, "fehler": 0, "unbrauchbar": 1}
    assert f"https://staging.example/confirm/{TOKEN}" in post.gesendet[0][2]
    assert "a@example.org" not in err and TOKEN not in err and TOKEN not in aus


def test_cli_fehlgeschlagene_adressen_stehen_als_kompakte_liste_auf_stdout():
    post = _Post(scheitert={"a@example.org", "c@example.org"})
    code, aus, err = _lauf(["senden"], json.dumps(_dok(
        _zeile("a@example.org"), _zeile("b@example.org", TOKEN2), _zeile("c@example.org"))),
        lambda: (lambda a: False, post, 0.0))
    assert code == 3
    assert aus == '["a@example.org","c@example.org"]\n'      # die Form, die das Skript prueft
    zeilen = err.strip().splitlines()
    assert json.loads(zeilen[-1]) == {"gesendet": 1, "gesperrt": 0, "fehler": 2, "unbrauchbar": 0}
    assert "a@example.org" not in err and TOKEN not in err


def test_cli_ohne_brauchbares_postfach_gehen_alle_zurueck():
    code, aus, err = _lauf(["senden"], json.dumps(_dok(_zeile("a@example.org"), _zeile("b@example.org", TOKEN2))),
                           lambda: (None, None, 0.0))
    assert code == 3
    assert json.loads(aus) == ["a@example.org", "b@example.org"]
    assert "nichts versendet" in err and "a@example.org" not in err
