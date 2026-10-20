"""Reine Baum-Logik des Struktur-Graphs (Plan 2026-10-20-struktur-graph, Task 1).

Keine DB, kein ui: nur `import struktur`.
"""
from struktur import (MAX_EBENE, anordnen, baum_bauen, fehler_neuer_laden,
                      fehler_umhaengen, nachfahren, teilbaum_tiefe)

KETTE = {"ivan": None, "lena": "ivan", "otto": "lena"}


def test_leer_ergibt_nur_betreiber():
    b = baum_bauen({})
    assert b.ebene == {} and b.kinder == {} and b.verwaist == frozenset()


def test_ebenen_relativ_zum_betreiber():
    assert baum_bauen(KETTE).ebene == {"ivan": 1, "lena": 2, "otto": 3}


def test_kinder_nach_name_sortiert():
    assert baum_bauen({"zora": None, "anna": None}).kinder[None] == ("anna", "zora")


def test_unbekannter_einlader_wird_verwaist():
    b = baum_bauen({"lena": "gibtsnicht"})
    assert b.ebene == {"lena": 1} and b.einlader == {"lena": None}
    assert b.verwaist == frozenset({"lena"})


def test_ring_in_daten_wird_aufgebrochen():
    b = baum_bauen({"b": "a", "a": "b"})
    assert b.ebene == {"a": 1, "b": 2} and b.verwaist == frozenset({"a"})


def test_nachfahren_und_teilbaum_tiefe():
    b = baum_bauen(KETTE)
    assert nachfahren(b, "ivan") == frozenset({"lena", "otto"})
    assert teilbaum_tiefe(b, "ivan") == 2 and teilbaum_tiefe(b, "otto") == 0


def test_neuer_laden_unter_ebene_fuenf_ok_unter_sechs_nicht():
    kette = {"e1": None, "e2": "e1", "e3": "e2", "e4": "e3", "e5": "e4", "e6": "e5"}
    b = baum_bauen(kette)
    assert fehler_neuer_laden(b, None) is None
    assert fehler_neuer_laden(b, "e5") is None
    assert "Ebene 7" in fehler_neuer_laden(b, "e6")
    assert MAX_EBENE == 6


def test_neuer_laden_unbekannter_einlader():
    assert "gibt es nicht" in fehler_neuer_laden(baum_bauen(KETTE), "nemo")


def test_umhaengen_unter_sich_selbst():
    assert "sich nicht selbst" in fehler_umhaengen(baum_bauen(KETTE), "lena", "lena")


def test_umhaengen_unter_enkel_ist_ring():
    assert "abstammt" in fehler_umhaengen(baum_bauen(KETTE), "ivan", "otto")


def test_umhaengen_unbekannt():
    b = baum_bauen(KETTE)
    assert "gibt es nicht" in fehler_umhaengen(b, "nemo", None)
    assert "gibt es nicht" in fehler_umhaengen(b, "lena", "nemo")


def test_umhaengen_tiefe_grenze_genau_sechs():
    # x hat zwei Ebenen Nachfahren; a1..a4 ist eine Kette (Ebenen 1..4)
    d = {"x": None, "x1": "x", "x2": "x1",
         "a1": None, "a2": "a1", "a3": "a2", "a4": "a3"}
    b = baum_bauen(d)
    assert fehler_umhaengen(b, "x", "a3") is None          # 3+1+2 = 6
    assert "Ebene 7" in fehler_umhaengen(b, "x", "a4")      # 4+1+2 = 7


def test_umhaengen_zum_betreiber_ok():
    assert fehler_umhaengen(baum_bauen(KETTE), "otto", None) is None


def test_anordnen_kinder_unter_elternteil_und_reihen_je_ebene():
    a = anordnen(baum_bauen({"ivan": None, "lena": "ivan", "mia": "ivan", "zora": None}))
    (xi, yi), (xl, yl), (xm, ym) = a.punkte["ivan"], a.punkte["lena"], a.punkte["mia"]
    assert xi == (xl + xm) / 2 and yl == ym > yi
    assert a.punkte["zora"][1] == yi
    assert a.punkte[None][1] < yi
    assert xl < xm < a.punkte["zora"][0]          # Sortierung nach Name, Gruppierung
    assert a.breite == 3 * 120 + 2 * 30            # drei Blätter


def test_anordnen_deterministisch():
    d1 = {"ivan": None, "lena": "ivan", "zora": None}
    d2 = {"zora": None, "lena": "ivan", "ivan": None}
    assert anordnen(baum_bauen(d1)) == anordnen(baum_bauen(d2))
