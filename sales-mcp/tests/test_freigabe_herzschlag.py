"""Herzschlag des Freigabe-Boten (M4): Bote schreibt, Wache und Seite lesen."""
import os
import urllib.error
from datetime import datetime, timedelta, timezone

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import freigabe_bote as fb  # noqa: E402
import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_freigabe_eingang as ufe  # noqa: E402

BASIS = "https://s"
T0 = datetime(2026, 11, 9, 11, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    def weg():
        with server.pool.connection() as conn:
            conn.execute("delete from sales_test.einstellungen where schluessel = %s",
                         (fe.EINSTELLUNG_HERZSCHLAG,))
    weg()
    yield
    weg()


# --- schreiben / lesen ----------------------------------------------------

def test_ohne_eintrag_unbekannt():
    h = fe.herzschlag_lesen(jetzt=T0)
    assert h["zustand"] == "unbekannt" and h["erfolg"] is None


def test_erfolg_ist_ok():
    fe.herzschlag_schreiben(True, jetzt=T0)
    h = fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=2))
    assert h["zustand"] == "ok"
    assert h["erfolg"] == T0 and h["fehler"] is None and h["fehler_seit"] is None
    assert h["minuten"] == 2


def test_fehler_behaelt_erfolg_und_ersten_fehlerzeitpunkt():
    fe.herzschlag_schreiben(True, jetzt=T0)
    fe.herzschlag_schreiben(False, "URLError", jetzt=T0 + timedelta(minutes=1))
    fe.herzschlag_schreiben(False, "HTTPError", jetzt=T0 + timedelta(minutes=2))
    h = fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=3))
    assert h["erfolg"] == T0
    assert h["fehler"] == "HTTPError"
    assert h["fehler_seit"] == T0 + timedelta(minutes=1)
    assert h["versuch"] == T0 + timedelta(minutes=2)
    assert h["zustand"] == "ok"  # noch keine 10 Minuten still


def test_erfolg_loescht_fehler():
    fe.herzschlag_schreiben(False, "URLError", jetzt=T0)
    fe.herzschlag_schreiben(True, jetzt=T0 + timedelta(minutes=1))
    h = fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=1))
    assert h["fehler"] is None and h["fehler_seit"] is None and h["zustand"] == "ok"


def test_still_nach_zehn_minuten():
    fe.herzschlag_schreiben(True, jetzt=T0)
    assert fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=10))["zustand"] == "ok"
    assert fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=11))["zustand"] == "still"


def test_nur_fehler_nie_erfolg_ist_still():
    fe.herzschlag_schreiben(False, "URLError", jetzt=T0)
    h = fe.herzschlag_lesen(jetzt=T0)
    assert h["zustand"] == "still" and h["erfolg"] is None


def test_fehler_nur_als_typname():
    fe.herzschlag_schreiben(False, "Bearer abc geheim\n<b>x</b>" + "y" * 200, jetzt=T0)
    fehler = fe.herzschlag_lesen(jetzt=T0)["fehler"]
    assert " " not in fehler and "<" not in fehler and "\n" not in fehler
    assert len(fehler) <= 60


def test_kaputter_wert_ist_unbekannt():
    server._q("insert into einstellungen (schluessel, wert, geaendert_von) values (%s, %s, 'x') "
              "returning schluessel", (fe.EINSTELLUNG_HERZSCHLAG, '"kaputt"'))
    assert fe.herzschlag_lesen(jetzt=T0)["zustand"] == "unbekannt"


@pytest.mark.parametrize("schreiben, minuten, anfang", [
    ([], 0, "unbekannt"),
    ([(True, None, 0)], 3, "ok"),
    ([(True, None, 0), (False, "URLError", 1)], 15, "still"),
])
def test_pruefzeile(schreiben, minuten, anfang):
    for erfolg, fehler, m in schreiben:
        fe.herzschlag_schreiben(erfolg, fehler, jetzt=T0 + timedelta(minutes=m))
    zeile = fe.herzschlag_pruefzeile(jetzt=T0 + timedelta(minutes=minuten))
    assert zeile.split(" ", 1)[0] == anfang
    assert "\n" not in zeile
    if anfang == "still":
        assert "URLError" in zeile


# --- der Bote schreibt ----------------------------------------------------

class _Leer:
    def __call__(self, kanal, body):
        if kanal == "todo:get":
            return {"list": {"blocks": []}, "suggestions": []}
        if kanal == "todo:plannerSignals":
            return {"signals": []}
        raise AssertionError(kanal)


def _truncate():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")


def test_durchgang_erfolg_schreibt_herzschlag(monkeypatch):
    _truncate()
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    monkeypatch.setattr(fb, "_rpc", _Leer())
    assert fb.durchgang() == 0
    h = fe.herzschlag_lesen()
    assert h["zustand"] == "ok" and h["fehler"] is None


def test_durchgang_rowboat_weg_schreibt_fehler(monkeypatch):
    _truncate()
    monkeypatch.setenv("UI_BASIS_URL", BASIS)

    def weg(kanal, body):
        raise urllib.error.URLError("weg")
    monkeypatch.setattr(fb, "_rpc", weg)
    assert fb.durchgang() == 1
    h = fe.herzschlag_lesen()
    assert h["fehler"] == "URLError" and h["erfolg"] is None


def test_durchgang_ohne_basis_url_schreibt_fehler(monkeypatch):
    monkeypatch.delenv("UI_BASIS_URL", raising=False)
    assert fb.durchgang() == 1
    assert fe.herzschlag_lesen()["fehler"] == "UI_BASIS_URL_fehlt"


def test_entwuerfe_kaputt_ist_kein_erfolg(monkeypatch):
    _truncate()
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    monkeypatch.setattr(fb, "_rpc", _Leer())

    def kaputt(basis):
        raise KeyError("x")
    monkeypatch.setattr(fe, "entwuerfe_spiegeln", kaputt)
    fb.durchgang()
    h = fe.herzschlag_lesen()
    assert h["erfolg"] is None and h["fehler"] == "Entwurfsspiegel.KeyError"


def test_herzschlag_kaputt_stoppt_den_boten_nicht(monkeypatch):
    _truncate()
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    monkeypatch.setattr(fb, "_rpc", _Leer())

    def kaputt(*a, **kw):
        raise RuntimeError("db weg")
    monkeypatch.setattr(fe, "herzschlag_schreiben", kaputt)
    assert fb.durchgang() == 0


# --- die Seite zeigt ------------------------------------------------------

def test_zeile_unbekannt_leer():
    assert ufe.abgleich_zeile(jetzt=T0) == ""


def test_zeile_ok_unauffaellig():
    fe.herzschlag_schreiben(True, jetzt=T0)
    z = ufe.abgleich_zeile(jetzt=T0 + timedelta(minutes=1))
    assert "Rowboat-Abgleich" in z and "vor 1 min" in z
    assert 'class="meta"' in z and "warnung" not in z


def test_zeile_still_rot_mit_uhrzeit_und_fehler():
    fe.herzschlag_schreiben(True, jetzt=T0)
    fe.herzschlag_schreiben(False, "URLError", jetzt=T0 + timedelta(minutes=1))
    z = ufe.abgleich_zeile(jetzt=T0 + timedelta(minutes=30))
    assert 'class="warnung"' in z
    assert "12:00" in z  # letzter Erfolg in Ortszeit (Europe/Berlin, UTC+1 im November)
    assert "URLError" in z


@pytest.mark.parametrize("fehler", ["Entwurfsspiegel.KeyError", "UI_BASIS_URL_fehlt", "URLError"])
def test_roter_hinweis_ohne_ascii_umschreibung(fehler):
    """Die Fehlernamen des Boten stehen auf /freigaben, also gilt die Umlaut-Regel."""
    from tests.test_darstellung import WOERTER_ASCII
    fe.herzschlag_schreiben(False, fehler, jetzt=T0)
    z = ufe.abgleich_zeile(jetzt=T0 + timedelta(minutes=30))
    assert fehler in z
    assert [w for w in WOERTER_ASCII if w in z] == []


def test_freigaben_seite_zeigt_zeile(monkeypatch):
    fe.herzschlag_schreiben(False, "URLError", jetzt=datetime.now(timezone.utc) - timedelta(hours=1))
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", "lesen", ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app, headers={"host": "127.0.0.1:8791"})
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9",
                               "csrf": ui.CSRF_TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    for pfad in ("/freigaben", "/freigaben?tab=technik"):
        seite = c.get(pfad)
        assert seite.status_code == 200
        assert "Rowboat-Abgleich" in seite.text and 'class="warnung"' in seite.text
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
