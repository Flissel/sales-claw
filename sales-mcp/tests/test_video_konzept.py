"""Pruefung des Videokonzept-Blocks (reine Funktionen, keine Datenbank)."""
import copy

import pytest

import konzept_lesen as kl
import video_konzept as vk


def konzept(**ueber):
    k = {
        "thema": "KI im Vertrieb",
        "zielgruppe": "Entscheider 34+",
        "minuten": 4,
        "hook": "Was kostet ein verlorener Lead?",
        "kernaussage": "Wer früh antwortet, gewinnt.",
        "stufen": [
            {"name": "Problem", "szenen": [{"kurz": f"Szene {i}", "bildart": "slide"} for i in range(4)]},
            {"name": "Lösung", "szenen": [{"kurz": f"Szene {i}", "bildart": "clip", "notiz": "n"} for i in range(4, 8)]},
        ],
        "abschluss": "Jetzt anfragen.",
        "auftrag": None,
        "firma": "fin2gether",
        "pfad": "knowledge/Konzepte/ki.html",
        "name": "ki",
    }
    k.update(ueber)
    return k


def mit_szenen(n):
    return konzept(stufen=[{"name": "Alles", "szenen": [{"kurz": "s", "bildart": "slide"} for _ in range(n)]}])


def test_gueltig():
    assert vk.pruefen(konzept()) is None


@pytest.mark.parametrize("n", [8, 15])
def test_szenen_grenzen_gueltig(n):
    assert vk.pruefen(mit_szenen(n)) is None


@pytest.mark.parametrize("n", [0, 6, 7, 16])
def test_szenenzahl_ausserhalb(n):
    satz = vk.pruefen(mit_szenen(n))
    assert satz and "8 bis 15 Szenen" in satz and f"gefunden wurden {n}" in satz


def test_szenen_zaehlen_ueber_alle_stufen():
    k = konzept()
    k["stufen"][0]["szenen"] = k["stufen"][0]["szenen"][:2]      # 2 + 4 = 6
    assert "8 bis 15 Szenen" in vk.pruefen(k)


@pytest.mark.parametrize("minuten", [2, 6, True, "4", None, 4.5, 2.0])
def test_minuten_ausserhalb(minuten):
    assert vk.pruefen(konzept(minuten=minuten)) is not None


def test_minuten_satz_kommt_vom_gemeinsamen_pruefer():
    assert vk.pruefen(konzept(minuten=6)) == "Die Länge muss zwischen 3 und 5 Minuten liegen."
    assert vk.pruefen(konzept(minuten=3.5)) == "Die Länge muss eine ganze Zahl von Minuten sein."


@pytest.mark.parametrize("minuten", [4.0, 3.0, 5.0])
def test_ganzzahlige_minuten_als_float_gelten(minuten):
    assert vk.pruefen(konzept(minuten=minuten)) is None
    assert isinstance(vk.bereinigen(konzept(minuten=minuten))["minuten"], int)


def test_hash_von_4_und_4_0_ist_gleich():
    assert vk.block_hash(konzept(minuten=4)) == vk.block_hash(konzept(minuten=4.0))
    assert vk.block_hash(vk.bereinigen(konzept(minuten=4.0))) == vk.block_hash(konzept(minuten=4))


def test_minuten_grenzen_gueltig():
    assert vk.pruefen(konzept(minuten=3)) is None and vk.pruefen(konzept(minuten=5)) is None


def test_kurz_grenze_300():
    k = konzept()
    k["stufen"][0]["szenen"][0]["kurz"] = "k" * 300
    assert vk.pruefen(k) is None
    k["stufen"][0]["szenen"][0]["kurz"] = "k" * 301
    assert "höchstens 300 Zeichen" in vk.pruefen(k)


@pytest.mark.parametrize("bildart", ["foto", "", None, 3])
def test_unbekannte_bildart(bildart):
    k = konzept()
    k["stufen"][1]["szenen"][0]["bildart"] = bildart
    assert "slide, avatar_slide, avatar_gross oder clip" in vk.pruefen(k)


@pytest.mark.parametrize("bildart", list(vk.BILDARTEN))
def test_alle_bildarten_gueltig(bildart):
    k = konzept()
    k["stufen"][0]["szenen"][0]["bildart"] = bildart
    assert vk.pruefen(k) is None


def test_stufen_hoechstens_acht():
    k = konzept(stufen=[{"name": f"S{i}", "szenen": [{"kurz": "s", "bildart": "slide"}]} for i in range(9)])
    assert vk.pruefen(k) == "Es sind höchstens 8 Stufen erlaubt."
    k["stufen"] = k["stufen"][:8]            # 8 Stufen mit je einer Szene = 8 Szenen
    assert vk.pruefen(k) is None


def test_stufe_ohne_namen_oder_szenenliste():
    for kaputt in ({"szenen": []}, {"name": "x"}, {"name": 3, "szenen": []}, "text"):
        k = konzept()
        k["stufen"].append(kaputt)
        assert vk.pruefen(k) == "Jede Stufe braucht einen Namen und eine Liste von Szenen."


def test_notiz_muss_text_sein():
    k = konzept()
    k["stufen"][0]["szenen"][0]["notiz"] = 5
    assert "Notiz" in vk.pruefen(k)


@pytest.mark.parametrize("feld", ["thema", "zielgruppe", "hook", "kernaussage", "abschluss"])
def test_pflichttexte(feld):
    assert vk.pruefen(konzept(**{feld: "  "})) is not None
    k = konzept()
    del k[feld]
    assert vk.pruefen(k) is not None


def test_thema_laenge():
    assert vk.pruefen(konzept(thema="ab")) and vk.pruefen(konzept(thema="x" * 301))
    assert vk.pruefen(konzept(thema="x" * 300)) is None


@pytest.mark.parametrize("wert", [None, "text", 3, []])
def test_kein_objekt(wert):
    assert vk.pruefen(wert) == "Das Videokonzept fehlt oder ist kein Objekt."


def _auf_laenge(ziel: int) -> dict:
    k = konzept()
    k["stufen"][0]["szenen"][0]["notiz"] = ""
    rest = ziel - kl.utf16_laenge(vk._kanonisch(k))
    k["stufen"][0]["szenen"][0]["notiz"] = "x" * rest
    assert kl.utf16_laenge(vk._kanonisch(k)) == ziel
    return k


def test_block_grenze_20000_zeichen():
    assert vk.pruefen(_auf_laenge(vk.BLOCK_MAX)) is None
    assert "20000 Zeichen" in vk.pruefen(_auf_laenge(vk.BLOCK_MAX + 1))


def test_hash_stabil_und_unabhaengig_von_auftrag_pfad_name():
    a = konzept()
    b = copy.deepcopy(a)
    b["auftrag"], b["pfad"], b["name"] = "abcd1234", "knowledge/Konzepte/anders.html", "anders"
    assert vk.block_hash(a) == vk.block_hash(b)
    assert len(vk.block_hash(a)) == 64 and set(vk.block_hash(a)) <= set("0123456789abcdef")


def test_hash_unabhaengig_von_schluesselreihenfolge():
    a = konzept()
    b = dict(reversed(list(a.items())))
    assert vk.block_hash(a) == vk.block_hash(b)


def test_hash_aendert_sich_mit_dem_inhalt():
    assert vk.block_hash(konzept()) != vk.block_hash(konzept(hook="Anderer Hook"))
    k = konzept()
    k["stufen"][0]["szenen"][0]["kurz"] = "anders"
    assert vk.block_hash(konzept()) != vk.block_hash(k)


@pytest.mark.parametrize("auftrag", [None, "abcd1234", "00000000"])
def test_auftrag_leer_oder_acht_hex(auftrag):
    assert vk.pruefen(konzept(auftrag=auftrag)) is None


@pytest.mark.parametrize("auftrag", ["", "abcd123", "ABCD1234", "abcd12345", "nicht-hex", 12345678])
def test_auftrag_sonst_ungueltig(auftrag):
    assert vk.pruefen(konzept(auftrag=auftrag)).startswith("Der Auftrag muss leer (null)")


def test_auftrag_fehlt_gilt_wie_null():
    k = konzept()
    del k["auftrag"]
    assert vk.pruefen(k) is None and vk.bereinigen(k)["auftrag"] is None
    assert vk.block_hash(vk.bereinigen(k)) == vk.block_hash(konzept())


def test_bereinigen_laesst_nur_bekannte_felder_uebrig():
    k = konzept(extra={"a": 1})
    k["stufen"][0]["x"] = 1
    k["stufen"][0]["szenen"][0]["sprechtext"] = "s"
    assert vk.pruefen(k) is None
    assert vk.bereinigen(k) == konzept()
    assert vk.bereinigen(konzept(firma=None)).get("firma") is None and "firma" not in vk.bereinigen(konzept(firma=None))


def test_blockgroesse_zaehlt_nur_bekannte_felder():
    k = vk.bereinigen(_auf_laenge(vk.BLOCK_MAX))
    k["unbekannt"] = "u" * 5000
    assert vk.pruefen(k) is None


def test_beschreibung_aus_kernaussage_und_abschluss():
    assert vk.beschreibung_aus(konzept(kernaussage=" A ", abschluss=" B\n")) == "A\n\nB"


# --- JavaScript-Semantik (UTF-16, js_trim), Sales' eigene Felder -------------------------------------------

def test_laengen_zaehlen_in_utf16_einheiten():
    k = konzept()
    k["stufen"][0]["szenen"][0]["kurz"] = "\U0001F600" * 150          # 150 Zeichen, 300 UTF-16-Einheiten
    assert vk.pruefen(k) is None
    k["stufen"][0]["szenen"][0]["kurz"] = "\U0001F600" * 151          # 302 Einheiten
    assert "höchstens 300 Zeichen" in vk.pruefen(k)
    assert vk.pruefen(konzept(thema="\U0001F600" * 151)) == "Das Thema muss 3 bis 300 Zeichen lang sein."


def test_trimmung_wie_javascript():
    assert vk.pruefen(konzept(thema="\x1c\x1cab")) is None             # U+001C ist in JS kein Leerraum
    assert vk.pruefen(konzept(thema="\ufeff\ufeffab")) is not None     # U+FEFF schon
    assert vk.pruefen(konzept(hook="\x85")) is None
    assert vk.pruefen(konzept(hook="\ufeff \xa0")) is not None
    assert vk.beschreibung_aus(konzept(kernaussage="\ufeffA\x85", abschluss="\xa0B\x1c ")) == "A\x85\n\nB\x1c"


def test_block_grenze_zaehlt_utf16():
    k = _auf_laenge(vk.BLOCK_MAX - 2)
    k["stufen"][0]["szenen"][0]["notiz"] += "\U0001F600"                # +1 Zeichen, +2 Einheiten = 20 000
    assert vk.pruefen(k) is None
    k["stufen"][0]["szenen"][0]["notiz"] += "\U0001F600"
    assert "20000 Zeichen" in vk.pruefen(k)


@pytest.mark.parametrize("feld", ["firma", "pfad", "name"])
def test_eigene_felder_hoechstens_500(feld):
    assert vk.pruefen(konzept(**{feld: "x" * 500})) is None
    assert vk.pruefen(konzept(**{feld: "x" * 501})) == f"Das Feld {feld} des Konzepts muss ein kurzer Text sein."
    assert vk.pruefen(konzept(**{feld: "\U0001F600" * 251})) is not None


@pytest.mark.parametrize("feld", ["pfad", "name"])
def test_pfad_und_name_nur_text_oder_leer(feld):
    assert vk.pruefen(konzept(**{feld: None})) is None
    assert vk.pruefen(konzept(**{feld: 5})) is not None


def test_firma_null_oder_fehlend_gilt_wie_keine_firma():
    assert vk.pruefen(konzept(firma=None)) is None
    k = konzept()
    del k["firma"]
    assert vk.pruefen(k) is None and "firma" not in vk.bereinigen(k) and "firma" not in vk.bereinigen(konzept(firma=None))
    assert vk.pruefen(konzept(firma=5)) == "Die Firma muss ein Text sein."


# --- Sales-eigene Regel: die Werkbank braucht Namen und Kurzbeschreibungen fuer die 1:1-Gliederung ---------------

LEER = ["", "   ", "\ufeff", " \ufeff\u00a0\t", "\u0001", "\u2028"]    # U+FEFF/U+00A0/U+2028: nur in JavaScript Leerraum


@pytest.mark.parametrize("wert", LEER)
def test_leerer_stufenname_wird_abgelehnt(wert):
    k = konzept()
    k["stufen"][1]["name"] = wert
    assert vk.pruefen(k) == "Jede Stufe braucht einen Namen."


@pytest.mark.parametrize("wert", LEER)
def test_leere_kurzbeschreibung_wird_abgelehnt(wert):
    k = konzept()
    k["stufen"][0]["szenen"][2]["kurz"] = wert
    assert vk.pruefen(k) == "Jede Szene braucht eine Kurzbeschreibung."


def test_js_trim_kennt_feff_python_strip_nicht():
    assert kl.js_trim("\ufeff") == "" and "\ufeff".strip() != ""      # sonst prueft der Test nichts


def test_stufe_ohne_szenen_wird_abgelehnt():
    k = konzept()
    k["stufen"].append({"name": "Leer", "szenen": []})                 # 8 Szenen bleiben 8: der gemeinsame Pruefer schweigt
    assert kl.video_pruefen_objekt(vk.angleichen(k)) is None
    assert vk.pruefen(k) == "Jede Stufe braucht mindestens eine Szene."


def test_gueltige_namen_mit_raendern_gelten():
    k = konzept()
    k["stufen"][0]["name"] = " \ufeffProblem\u00a0"
    k["stufen"][0]["szenen"][0]["kurz"] = "\tSzene\u200b"
    assert vk.pruefen(k) is None


def test_neun_stufen_meldet_weiter_der_gemeinsame_pruefer():
    k = konzept(stufen=[{"name": f"S{i}", "szenen": [{"kurz": "s", "bildart": "slide"}]} for i in range(9)])
    assert vk.pruefen(k) == "Es sind höchstens 8 Stufen erlaubt."


def test_leerer_name_hat_vorrang_nicht_vor_dem_gemeinsamen_pruefer():
    k = konzept(thema="ab")
    k["stufen"][0]["name"] = ""
    assert vk.pruefen(k) == "Das Thema muss 3 bis 300 Zeichen lang sein."
