"""Reine Baum-Logik des Struktur-Graphs (Plan 2026-10-20-struktur-graph, Task 1).

Keine DB, kein ui: nur `import struktur`.
"""
from struktur import (LEVEL_MAX, LEVEL_MIN, anordnen, baum_bauen, fehler_neuer_laden,
                      fehler_umhaengen, level_lesen, nachfahren, teilbaum_tiefe)

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


# Betreiber 20.10.2026: "es können unendlich viele Nodes generiert werden -
# quasi ein Schneeball". Keine Tiefengrenze mehr; die Ringprüfung bleibt.
KETTE_15 = {f"k{i}": (f"k{i - 1}" if i > 1 else None) for i in range(1, 16)}


def test_neuer_laden_unter_tiefe_fuenfzehn_ist_erlaubt():
    b = baum_bauen(KETTE_15)
    assert b.ebene["k15"] == 15
    assert fehler_neuer_laden(b, None) is None
    assert fehler_neuer_laden(b, "k15") is None


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


def test_umhaengen_beliebig_tief_ist_erlaubt():
    # x hat zwei Ebenen Nachfahren; unter k15 landet x2 auf Tiefe 18.
    d = {**KETTE_15, "x": None, "x1": "x", "x2": "x1"}
    b = baum_bauen(d)
    assert fehler_umhaengen(b, "x", "k15") is None


def test_ring_bleibt_auch_in_tiefer_kette_verboten():
    b = baum_bauen(KETTE_15)
    assert "abstammt" in fehler_umhaengen(b, "k3", "k15")


def test_anordnen_tiefe_kette_waechst_nach_unten():
    a = anordnen(baum_bauen(KETTE_15))
    assert a.punkte["k15"][1] > a.punkte["k14"][1] > a.punkte[None][1]
    assert a.hoehe >= a.punkte["k15"][1] + 18
    assert a.breite == 120 + 2 * 30


def test_sehr_tiefe_kette_ohne_rekursionsgrenze():
    kette = {f"t{i}": (f"t{i - 1}" if i > 1 else None) for i in range(1, 3001)}
    b = baum_bauen(kette)
    a = anordnen(b)
    assert b.ebene["t3000"] == 3000 and teilbaum_tiefe(b, "t1") == 2999
    assert a.punkte["t3000"][0] == a.punkte[None][0]


def test_anordnen_breiter_baum_waechst_zur_seite():
    d = {f"m{i:02d}": None for i in range(40)}
    a = anordnen(baum_bauen(d))
    assert a.breite == 40 * 120 + 2 * 30
    assert len({p for p in a.punkte.values()}) == 41     # keine zwei Knoten übereinander


def test_level_lesen():
    assert (LEVEL_MIN, LEVEL_MAX) == (1, 6)
    for gut in ("1", "6", " 3 ", 4):
        assert level_lesen(gut) == int(str(gut).strip())
    for schlecht in ("0", "7", "-1", "", None, "abc", "2.5", "1e1", "³"):
        assert level_lesen(schlecht) is None


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
