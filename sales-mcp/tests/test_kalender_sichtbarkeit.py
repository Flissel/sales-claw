"""Sichtbarkeitsregel Business/Privat fuer Kalendertermine (reines Modul)."""
from datetime import datetime, timedelta, timezone

from kalender_sichtbarkeit import PRIVATTERMIN, anwenden, details_speichern, maskiert

_BEGINN = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def _t(**kw):
    basis = dict(
        besitzer="felix", bereich="business", quelle="Q", quelle_id="q1",
        uid="", titel="T", ort="O", ganztaegig=False, frei=False,
        beginn=_BEGINN, ende=_BEGINN + timedelta(hours=1),
    )
    basis.update(kw)
    return basis


def test_eigene_privat_voll_fremde_privat_maskiert():
    t = _t(besitzer="felix", bereich="privat", titel="Zahnarzt")
    assert anwenden([t], "felix")[0]["titel"] == "Zahnarzt"
    aus = anwenden([t], "ivan")[0]
    assert aus["titel"] == "Privattermin" and aus["ort"] == "" and aus["maskiert"]


def test_ohne_betrachter_ist_jedes_privat_maskiert():
    assert anwenden([_t(bereich="privat")], "")[0]["maskiert"]


def test_business_fremd_voll():
    aus = anwenden([_t(besitzer="ivan", bereich="business", titel="Kunde X")], "felix")[0]
    assert aus["titel"] == "Kunde X" and aus["ort"] == "O" and not aus["maskiert"]


def test_doppelter_termin_einmal_und_strenger():
    a = _t(quelle="Arbeit", bereich="business", uid="u1", titel="Treffen")
    b = _t(quelle="Privat", bereich="privat", uid="u1", titel="Treffen")
    aus = anwenden([a, b], "ivan")
    assert len(aus) == 1 and aus[0]["titel"] == "Privattermin"
    assert aus[0]["kalender"] == [] and aus[0]["quelle"] == "Privat (felix)"


def test_verschiedene_besitzer_werden_nicht_zusammengefuehrt():
    assert len(anwenden([_t(besitzer="felix", uid="u1"), _t(besitzer="ivan", uid="u1")], "felix")) == 2


def test_details_speichern():
    assert details_speichern("felix", "privat", "felix")
    assert not details_speichern("ivan", "privat", "felix")
    assert not details_speichern("felix", "privat", "")
    assert details_speichern("ivan", "business", "felix")


def test_maskiert_regel():
    assert not maskiert("felix", "privat", "felix")
    assert maskiert("felix", "privat", "ivan")
    assert maskiert("felix", "privat", "")
    assert not maskiert("felix", "business", "")


def test_zusammenfuehrung_ueber_tripel_ohne_uid():
    a = _t(quelle="A", titel="Sync")
    b = _t(quelle="B", titel="Sync")
    aus = anwenden([a, b], "felix")
    assert len(aus) == 1 and sorted(aus[0]["kalender"]) == ["A", "B"]


def test_ohne_titel_kein_tripel_merge():
    assert len(anwenden([_t(titel="", quelle="A"), _t(titel="", quelle="B")], "felix")) == 2


def test_frei_nur_wenn_alle_kopien_frei():
    a = _t(quelle="A", uid="u", frei=True)
    b = _t(quelle="B", uid="u", frei=False)
    assert anwenden([a, b], "felix")[0]["frei"] is False
    b2 = _t(quelle="B", uid="u", frei=True)
    assert anwenden([a, b2], "felix")[0]["frei"] is True


def test_sortiert_nach_beginn_und_eingabe_unveraendert():
    spaet = _t(uid="s", titel="Spaet", beginn=_BEGINN + timedelta(hours=5))
    frueh = _t(uid="f", titel="Frueh")
    privat = _t(uid="p", bereich="privat", titel="Geheim")
    eingang = [spaet, frueh, privat]
    aus = anwenden(eingang, "ivan")
    assert [x["uid"] for x in aus][-1] == "s"
    assert "maskiert" not in privat and "kalender" not in privat
    assert privat["titel"] == "Geheim" and privat["ort"] == "O"
    assert eingang == [spaet, frueh, privat]


def test_maskiertes_ergebnis_traegt_keinen_kalendernamen():
    privat = _t(besitzer="felix", bereich="privat", quelle="Felix geheim", uid="u1")
    aus = anwenden([privat], "ivan")[0]
    assert aus["quelle"] == "Privat (felix)" and aus["kalender"] == []


def test_zusammengefuehrt_mit_business_kopie_bleibt_namenlos():
    privat = _t(besitzer="felix", bereich="privat", quelle="Felix geheim", uid="u1")
    business = _t(besitzer="felix", bereich="business", quelle="Felix Arbeit", uid="u1")
    for reihenfolge in ([privat, business], [business, privat]):
        (aus,) = anwenden(reihenfolge, "ivan")
        assert aus["maskiert"] and aus["quelle"] == "Privat (felix)" and aus["kalender"] == []
        assert "Felix geheim" not in str(aus) and "Felix Arbeit" not in str(aus)
    assert anwenden([privat], "felix")[0]["quelle"] == "Felix geheim"
