"""Pausen-Wunsch, Pausenzeilen, Live-Ablage (Meeting-Steuerseite, Task 4)."""
import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import termin_akte  # noqa: E402

T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def leer():
    server._q("truncate sales_test.termin_akten cascade")
    yield
    server._q("truncate sales_test.termin_akten cascade")


def _akte(uid="p1", status="laeuft"):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, status) "
        "values (%s, 'kalender', %s, %s, %s) returning uid",
        (uid, T0, T0 + timedelta(hours=1), status))


def _akte_zeile(uid="p1"):
    return server._q("select aufnahme_wunsch, aufnahme_wunsch_am from termin_akten "
                     "where uid = %s", (uid,))[0]


def test_pause_legt_eine_offene_zeile_an():
    _akte()
    assert termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0) is True
    z = termin_akte.pausen("p1")
    assert len(z) == 1
    assert z[0]["von"] == T0 and z[0]["bis"] is None
    assert z[0]["angefordert_von"] == "felix" and z[0]["bestaetigt_am"] is None
    a = _akte_zeile()
    assert a["aufnahme_wunsch"] == "pause" and a["aufnahme_wunsch_am"] == T0


def test_pause_doppelt_bleibt_eine_zeile():
    _akte()
    assert termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0)
    spaeter = T0 + timedelta(minutes=3)
    assert termin_akte.aufnahme_wuenschen("p1", "pause", "felix", spaeter) is True
    z = termin_akte.pausen("p1")
    assert len(z) == 1
    assert z[0]["von"] == T0 and z[0]["bis"] is None


def test_unique_index_haelt_zwei_offene_nicht_zu():
    _akte()
    server._q("insert into termin_pausen (uid, von, angefordert_von) "
              "values ('p1', %s, 'x') returning id", (T0,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        server._q("insert into termin_pausen (uid, von, angefordert_von) "
                  "values ('p1', %s, 'y') returning id", (T0 + timedelta(minutes=1),))


def test_weiter_schliesst_die_pause():
    _akte()
    termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0)
    ende = T0 + timedelta(minutes=5)
    assert termin_akte.aufnahme_wuenschen("p1", "an", "felix", ende) is True
    z = termin_akte.pausen("p1")
    assert len(z) == 1 and z[0]["von"] == T0 and z[0]["bis"] == ende
    assert _akte_zeile()["aufnahme_wunsch"] == "an"
    # neue Pause nach einer geschlossenen ist wieder moeglich
    termin_akte.aufnahme_wuenschen("p1", "pause", "felix", ende + timedelta(minutes=1))
    z = termin_akte.pausen("p1")
    assert [p["bis"] is None for p in z] == [False, True]


def test_an_ohne_offene_pause_setzt_nur_den_wunsch():
    _akte()
    assert termin_akte.aufnahme_wuenschen("p1", "an", "felix", T0) is True
    assert termin_akte.pausen("p1") == []
    assert _akte_zeile()["aufnahme_wunsch_am"] == T0


def test_notbremse_laesst_offene_pause_offen():
    _akte()
    termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0)
    assert termin_akte.aufnahme_wuenschen(
        "p1", "notbremse", "felix", T0 + timedelta(minutes=2)) is True
    z = termin_akte.pausen("p1")
    assert len(z) == 1 and z[0]["bis"] is None
    assert _akte_zeile()["aufnahme_wunsch"] == "notbremse"


def test_notbremse_ohne_pause_legt_keine_an():
    _akte()
    assert termin_akte.aufnahme_wuenschen("p1", "notbremse", "felix", T0) is True
    assert termin_akte.pausen("p1") == []


@pytest.mark.parametrize("status", ["wartet_auf_einlass", "laeuft"])
def test_wunsch_bei_laufender_akte(status):
    _akte(status=status)
    assert termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0) is True


@pytest.mark.parametrize("status", ["geplant", "kein_link", "fertig",
                                    "fehlgeschlagen", "ohne_aufnahme"])
def test_wunsch_nur_bei_laufender_akte(status):
    _akte(status=status)
    assert termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0) is False
    assert termin_akte.pausen("p1") == []
    a = _akte_zeile()
    assert a["aufnahme_wunsch"] == "an" and a["aufnahme_wunsch_am"] is None


def test_wunsch_unbekannte_akte():
    assert termin_akte.aufnahme_wuenschen("gibts-nicht", "pause", "felix", T0) is False


def test_unbekannter_wunsch_ist_valueerror():
    _akte()
    with pytest.raises(ValueError):
        termin_akte.aufnahme_wuenschen("p1", "stopp", "felix", T0)
    assert _akte_zeile()["aufnahme_wunsch_am"] is None


def test_in_pause_grenzen():
    p = [{"von": T0, "bis": T0 + timedelta(minutes=5)}]
    assert termin_akte.in_pause(T0, p) is True                           # von inklusive
    assert termin_akte.in_pause(T0 - timedelta(seconds=1), p) is False
    assert termin_akte.in_pause(T0 + timedelta(minutes=5), p) is False  # bis exklusiv
    assert termin_akte.in_pause(T0 + timedelta(minutes=4, seconds=59), p) is True
    offen = [{"von": T0, "bis": None}]
    assert termin_akte.in_pause(T0 + timedelta(days=365), offen) is True
    assert termin_akte.in_pause(T0 - timedelta(seconds=1), offen) is False
    assert termin_akte.in_pause(T0, []) is False


def test_pausen_sortiert():
    _akte()
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) "
              "values ('p1', %s, %s, 'a') returning id",
              (T0 + timedelta(minutes=10), T0 + timedelta(minutes=12)))
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) "
              "values ('p1', %s, %s, 'b') returning id",
              (T0, T0 + timedelta(minutes=2)))
    assert [p["angefordert_von"] for p in termin_akte.pausen("p1")] == ["b", "a"]


def test_live_segmente_kaskade_und_schluessel():
    _akte()
    server._q("insert into termin_live_segmente (uid, segment_id, beginn, sprecher, text) "
              "values ('p1', 's1', %s, null, 'hallo') returning uid", (T0,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        server._q("insert into termin_live_segmente (uid, segment_id, beginn, text) "
                  "values ('p1', 's1', %s, 'nochmal') returning uid", (T0,))
    server._q("truncate sales_test.termin_akten cascade")
    assert server._q("select count(*) as n from termin_live_segmente")[0]["n"] == 0


def test_pausen_kaskade_mit_der_akte():
    _akte()
    termin_akte.aufnahme_wuenschen("p1", "pause", "felix", T0)
    server._q("delete from termin_akten where uid = 'p1' returning uid")
    assert server._q("select count(*) as n from termin_pausen")[0]["n"] == 0
