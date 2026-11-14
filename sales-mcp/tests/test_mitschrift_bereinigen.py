"""Mitschrift bereinigen: reine Funktion, keine DB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mitschrift_bereinigen as mb  # noqa: E402


def _s(sprecher, beginn, text="x", sprache="de"):
    return {"sprecher": sprecher, "beginn": beginn, "text": text, "sprache": sprache}


def _iso(sek):
    return f"2099-01-09T12:{sek // 60:02d}:{sek % 60:02d}Z"


def test_zdf_halluzination_faellt_weg():
    ein = [_s("A", _iso(0), "Untertitel im Auftrag des ZDF, 2017"),
           _s("A", _iso(30), "Das ZDF hat angerufen")]
    aus = mb.bereinigen(ein)
    assert [s["text"] for s in aus] == ["Das ZDF hat angerufen"]


def test_danke_fuers_zuschauen_nur_ganz():
    ein = [_s("A", _iso(0), "Vielen Dank fürs Zuschauen!"),
           _s("B", _iso(30), "Danke, das schau ich mir an")]
    assert [s["text"] for s in mb.bereinigen(ein)] == ["Danke, das schau ich mir an"]


def test_betreiber_name_vereinheitlicht(monkeypatch):
    monkeypatch.delenv("BETREIBER_NAME", raising=False)
    aus = mb.bereinigen([_s("felix", _iso(0), "Hallo")])
    assert aus[0]["sprecher"] == "Felix Baumann"
    assert mb.bereinigen([_s("felix", _iso(0))], betreiber="")[0]["sprecher"] == "felix"


def test_kurzname_auf_langen():
    ein = [_s("Diana", _iso(0), "a"), _s("Diana Marx", _iso(60), "b"),
           _s("Diana", _iso(120), "c")]
    assert {s["sprecher"] for s in mb.bereinigen(ein, betreiber="")} == {"Diana Marx"}


def test_luecke_gefuellt():
    ein = [_s("A", _iso(0), "eins"), _s("", _iso(2), "zwei"), _s("A", _iso(4), "drei")]
    aus = mb.bereinigen(ein, betreiber="")
    assert {s["sprecher"] for s in aus} == {"A"}
    ein = [_s("A", _iso(0), "eins"), _s("", _iso(2), "zwei"), _s("B", _iso(4), "drei")]
    aus = mb.bereinigen(ein, betreiber="")
    assert [s["sprecher"] for s in aus] == ["A", "", "B"]


def test_bruchstuecke_verbunden():
    ein = [_s("A", _iso(0), "Ja"), _s("A", _iso(2), "genau"),
           _s("A", _iso(4), "so machen wir das")]
    aus = mb.bereinigen(ein, betreiber="")
    assert len(aus) == 1 and aus[0]["text"] == "Ja genau so machen wir das"
    assert aus[0]["beginn"] == _iso(0)
    getrennt = mb.bereinigen([_s("A", _iso(0), "Ja"), _s("A", _iso(10), "genau")], betreiber="")
    assert len(getrennt) == 2
    lang = "a" * 200
    assert len(mb.bereinigen([_s("A", _iso(0), lang), _s("A", _iso(2), "b" * 199)],
                             betreiber="")) == 1      # 200 + 1 + 199 = 400
    assert len(mb.bereinigen([_s("A", _iso(0), lang), _s("A", _iso(2), "b" * 200)],
                             betreiber="")) == 2      # 401


def test_ohne_beginn_nicht_verbunden():
    ein = [_s("A", "", "Ja"), _s("A", "", "genau"), _s("A", "murks", "so"),
           _s("A", _iso(0), "ok")]
    assert len(mb.bereinigen(ein, betreiber="")) == 4


def test_zahlen_als_beginn_und_eingabe_unveraendert():
    ein = [_s("A", 0, "Ja"), _s("A", 5, "genau")]
    kopie = [dict(s) for s in ein]
    aus = mb.bereinigen(ein, betreiber="")
    assert len(aus) == 1 and ein == kopie


def test_anderer_felix_bleibt(monkeypatch):
    monkeypatch.delenv("BETREIBER_NAME", raising=False)
    ein = [_s("felix", _iso(0), "a"), _s("Felix Meier", _iso(60), "b"),
           _s("felix baumann", _iso(120), "c")]
    assert [s["sprecher"] for s in mb.bereinigen(ein)] == \
        ["Felix Baumann", "Felix Meier", "Felix Baumann"]


def test_kurzname_mehrdeutig_bleibt():
    ein = [_s("Diana", _iso(0), "a"), _s("Diana Marx", _iso(60), "b"),
           _s("Diana Klein", _iso(120), "c")]
    assert [s["sprecher"] for s in mb.bereinigen(ein, betreiber="")] == \
        ["Diana", "Diana Marx", "Diana Klein"]


def test_verbinden_kettet_ueber_vorgaenger():
    ein = [_s("A", _iso(0), "eins"), _s("A", _iso(5), "zwei"), _s("A", _iso(10), "drei")]
    aus = mb.bereinigen(ein, betreiber="")
    assert len(aus) == 1 and aus[0]["text"] == "eins zwei drei"


def test_sender_im_satz_bleibt():
    ein = [_s("A", _iso(0), "ARD und ZDF zeigen das heute")]
    assert [s["text"] for s in mb.bereinigen(ein, betreiber="")] == ["ARD und ZDF zeigen das heute"]


def test_untertitel_nur_mit_sender_am_ende():
    ein = [_s("A", _iso(0), "Untertitel der Videos sind fertig"),
           _s("A", _iso(30), "Untertitel von Max"),
           _s("A", _iso(60), "Untertitelung des ZDF für funk, 2017"),
           _s("A", _iso(90), "Untertitel der Amara.org-Community"),
           _s("A", _iso(120), "Untertitel im Auftrag des ZDF, 2018"),
           _s("A", _iso(150), "Untertitel von SWR")]
    assert [s["text"] for s in mb.bereinigen(ein)] == [
        "Untertitel der Videos sind fertig", "Untertitel von Max"]
