"""Abgleich-Dienst: Quellen lesen, Termine ersetzen, Sichtbarkeit (Spec §6)."""
import itertools
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender_abgleich  # noqa: E402
import kalenderquellen  # noqa: E402
import server  # noqa: E402

_NR = itertools.count(1)


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def _quelle(besitzer="felix", bereich="privat", art="ics", zuletzt_gelesen=False):
    n = next(_NR)
    z = server._q(
        "insert into kalender_quellen (anzeigename, url, besitzer, bereich, art) "
        "values (%s, %s, %s, %s, %s) returning id",
        (f"Q{n}", f"https://example.test/{n}.ics", besitzer, bereich, art))
    if zuletzt_gelesen:
        server._q("update kalender_quellen set zuletzt_gelesen = now() "
                  "where id = %s returning id", (z[0]["id"],))
    return next(q for q in server.kalenderquellen_lesen(False) if q["id"] == str(z[0]["id"]))


def _termin(titel="Zahnarzt", ort="Praxis", uid="u1", stunde=9):
    beginn = datetime(2030, 1, 1, stunde, tzinfo=timezone.utc)
    return {"beginn": beginn, "ende": beginn + timedelta(hours=1), "titel": titel,
            "ort": ort, "uid": uid, "ganztaegig": False, "frei": False}


def _hole_liefert(monkeypatch, termine, fehler=None):
    monkeypatch.setattr(kalenderquellen, "hole", lambda *a, **k: (termine, fehler))


def _termine(qid):
    return server._q("select * from kalender_termine where quelle_id = %s "
                     "order by beginn", (qid,))


def _stand(qid):
    return server._q("select * from kalender_quellen where id = %s", (qid,))[0]


def test_fremde_privatquelle_speichert_keinen_titel(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle(besitzer="ivan", bereich="privat")
    _hole_liefert(monkeypatch, [_termin(titel="Zahnarzt", ort="Praxis")])
    kalender_abgleich.quelle_abgleichen(q)
    zeile = _termine(q["id"])[0]
    assert zeile["titel"] is None and zeile["ort"] is None


def test_leerer_laden_besitzer_speichert_nie_privattitel(monkeypatch):
    monkeypatch.delenv("POST_BESITZER", raising=False)
    q = _quelle(besitzer="felix", bereich="privat")
    _hole_liefert(monkeypatch, [_termin()])
    kalender_abgleich.quelle_abgleichen(q)
    assert _termine(q["id"])[0]["titel"] is None


def test_eigene_privatquelle_speichert_titel(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle(besitzer="felix", bereich="privat")
    _hole_liefert(monkeypatch, [_termin()])
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert (anzahl, fehler) == (1, None)
    zeile = _termine(q["id"])[0]
    assert zeile["titel"] == "Zahnarzt" and zeile["ort"] == "Praxis"
    assert _stand(q["id"])["termine_zuletzt"] == 1


def test_fremde_businessquelle_speichert_titel(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle(besitzer="ivan", bereich="business")
    _hole_liefert(monkeypatch, [_termin()])
    kalender_abgleich.quelle_abgleichen(q)
    assert _termine(q["id"])[0]["titel"] == "Zahnarzt"


def test_fehler_laesst_alte_termine_stehen(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle()
    _hole_liefert(monkeypatch, [_termin()])
    kalender_abgleich.quelle_abgleichen(q)
    _hole_liefert(monkeypatch, [], "nicht erreichbar")
    assert kalender_abgleich.quelle_abgleichen(q) == (None, "nicht erreichbar")
    assert len(_termine(q["id"])) == 1 and _stand(q["id"])["letzter_fehler"]


def test_teilerfolg_speichert_und_meldet_fehler(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle()
    _hole_liefert(monkeypatch, [_termin()], "ein Serientermin unlesbar")
    assert kalender_abgleich.quelle_abgleichen(q) == (1, "ein Serientermin unlesbar")
    assert len(_termine(q["id"])) == 1
    assert _stand(q["id"])["letzter_fehler"] == "ein Serientermin unlesbar"


def test_ersetzen_entfernt_abgesagte(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle()
    _hole_liefert(monkeypatch, [_termin(uid="a"), _termin(uid="b", stunde=11)])
    kalender_abgleich.quelle_abgleichen(q)
    assert len(_termine(q["id"])) == 2
    _hole_liefert(monkeypatch, [_termin(uid="b", stunde=11)])
    kalender_abgleich.quelle_abgleichen(q)
    zeilen = _termine(q["id"])
    assert len(zeilen) == 1 and zeilen[0]["uid"] == "b"


def test_ersetzen_ist_atomar():
    """Scheitert das Einfuegen, bleiben die alten Termine."""
    q = _quelle()
    server.kalendertermine_ersetzen(q["id"], [_termin()], True)
    kaputt = dict(_termin(uid="x"), beginn=None)
    with pytest.raises(Exception):
        server.kalendertermine_ersetzen(q["id"], [kaputt], True)
    zeilen = _termine(q["id"])
    assert len(zeilen) == 1 and zeilen[0]["uid"] == "u1"


def test_google_quelle_wird_uebersprungen(monkeypatch):
    def nie(*a, **k):
        raise AssertionError("hole darf fuer Google nicht laufen")
    monkeypatch.setattr(kalenderquellen, "hole", nie)
    q = _quelle(art="google")
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert anzahl is None and fehler
    assert _stand(q["id"])["letzter_fehler"] == fehler


def test_kein_titel_im_log(caplog, monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle(besitzer="ivan", bereich="privat")
    _hole_liefert(monkeypatch, [_termin(titel="Zahnarzt", ort="Praxis")])
    with caplog.at_level(logging.DEBUG):
        kalender_abgleich.quelle_abgleichen(q)
        kalender_abgleich.runde()
    assert "Zahnarzt" not in caplog.text and "Praxis" not in caplog.text
    assert "example.test" not in caplog.text


def test_runde_zaehlt_und_haelt_bei_ausnahme_nicht_an(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    _quelle()
    _quelle()
    aufrufe = []

    def hole(url, *a, **k):
        aufrufe.append(url)
        if len(aufrufe) == 1:
            raise RuntimeError("Zahnarzt")
        return [_termin()], None
    monkeypatch.setattr(kalenderquellen, "hole", hole)
    assert kalender_abgleich.runde() == {"quellen": 2, "fehler": 1}
    faelle = server.kalenderquellen_lesen()
    texte = sorted(str(_stand(q["id"])["letzter_fehler"]) for q in faelle)
    assert "Abgleich fehlgeschlagen (RuntimeError)" in texte
    assert all("Zahnarzt" not in t for t in texte)


def test_stand_schreiben_scheitert_haelt_runde_nicht_an(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    _quelle()
    _quelle()

    def hole(url, *a, **k):
        raise RuntimeError("x")

    def stand(*a, **k):
        raise ValueError("db weg")
    monkeypatch.setattr(kalenderquellen, "hole", hole)
    monkeypatch.setattr(server, "kalenderquelle_stand_setzen", stand)
    assert kalender_abgleich.runde() == {"quellen": 2, "fehler": 2}


def test_neue_quellen_sind_die_nie_gelesenen():
    neu = _quelle()
    _quelle(zuletzt_gelesen=True)
    assert [q["id"] for q in kalender_abgleich.neue_quellen()] == [neu["id"]]
