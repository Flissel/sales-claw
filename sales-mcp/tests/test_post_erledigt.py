"""Erledigt-Zustand und Liste offener Mails (Spec 2026-11-07, Z3). Nur sales_test."""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_erledigt  # noqa: E402
import post_ziel  # noqa: E402
from post_struktur import Betrachter  # noqa: E402

ANNA = Betrachter(name="t_anna", leitung=False, abteilungen=())
BEN = Betrachter(name="t_ben", leitung=False, abteilungen=())


@pytest.fixture
def db(monkeypatch):
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_regeln")
            conn.execute("truncate sales_test.post_loeschfreigaben")
            conn.execute("truncate sales_test.post_konten cascade")
            conn.execute("delete from sales_test.leads where source = 't_erledigt' "
                         "or email like '%@t-erledigt.example' "
                         "or email like '%.t-erledigt.example'")
    leeren()
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 11, 1))
    yield server
    leeren()


def _konto(server, besitzer="t_anna", kennung="t-anna"):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values (%s, %s, 'gmx', %s, 'ui') returning id",
            (besitzer, kennung, f"{kennung}@x.de")).fetchone()["id"]


_n = [0]


def _mail(server, konto_id, *, besitzer="t_anna", datum="2026-11-02", ziel="posteingang",
          abgeglichen=True, fach="Kunden & Anfragen", von="Max <max@t-erledigt.example>"):
    _n[0] += 1
    with server.pool.connection() as conn:
        return str(conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, "
            "text, auszug, bereich, fach, status, ziel, datum, anhaenge, abgeglichen_am) "
            "values (%s, %s, %s, %s, %s, 'Betreff', 'Text', 'Auszug', 'business', %s, "
            "'eingeordnet', %s, %s::timestamptz, '{}', "
            + ("now()" if abgeglichen else "null") + ") returning id",
            (konto_id, _n[0], f"e{_n[0]}@x", besitzer, von, fach, ziel, datum)
        ).fetchone()["id"])


def _zeile(server, mid):
    return server._q("select * from post_mails where id = %s", (mid,))[0]


def _ids(b):
    return {str(z["id"]) for z in post_erledigt.mails_offen(b)[0]}


def test_offen_nur_ab_stichtag_und_abgeglichen(db):
    k = _konto(db)
    alt = _mail(db, k, datum="2026-10-31")
    ungeprueft = _mail(db, k, abgeglichen=False)
    info = _mail(db, k, ziel="zur_info")
    drin = _mail(db, k)
    zeilen, gesamt = post_erledigt.mails_offen(ANNA)
    assert {str(z["id"]) for z in zeilen} == {drin}
    assert gesamt == 1
    assert not ({alt, ungeprueft, info} & _ids(ANNA))
    assert zeilen[0]["kennung"] == "t-anna"


def test_ohne_stichtag_keine_mails(db, monkeypatch):
    _mail(db, _konto(db))
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date.max)
    assert post_erledigt.mails_offen(ANNA) == ([], 0)
    assert post_erledigt.stichtag_gesetzt() is False


def test_nur_eigene_mails(db):
    kb = _konto(db, "t_ben", "t-ben")
    mid = _mail(db, kb, besitzer="t_ben")
    assert mid not in _ids(ANNA)
    assert mid in _ids(BEN)


def test_erledigen_und_wieder_oeffnen(db):
    mid = _mail(db, _konto(db))
    assert post_erledigt.erledigen(ANNA, mid, "erledigt") is True
    assert mid not in _ids(ANNA)
    assert _zeile(db, mid)["erledigt_art"] == "erledigt"
    assert post_erledigt.wieder_oeffnen(ANNA, mid) is True
    assert mid in _ids(ANNA)
    z = _zeile(db, mid)
    assert z["abgleich_aus"] is True and z["erledigt_am"] is None
    assert post_erledigt.erledigen(ANNA, mid, "unsinn") is False


def test_bezahlt_nur_bei_rechnungen(db):
    k = _konto(db)
    kunde = _mail(db, k)
    assert post_erledigt.erledigen(ANNA, kunde, "bezahlt") is False
    z = _zeile(db, kunde)
    assert z["erledigt_am"] is None and z["bezahlt_am"] is None
    rech = _mail(db, k, fach="Rechnungen")
    assert post_erledigt.erledigen(ANNA, rech, "bezahlt") is True
    z = _zeile(db, rech)
    assert z["bezahlt_am"] is not None and z["erledigt_art"] == "bezahlt"
    rech2 = _mail(db, k, fach="Rechnungen")
    assert post_erledigt.erledigen(ANNA, rech2, "erledigt") is True
    assert _zeile(db, rech2)["bezahlt_am"] is None


def test_fremde_mail_nicht_erledigbar(db):
    mid = _mail(db, _konto(db))
    assert post_erledigt.erledigen(BEN, mid, "erledigt") is False
    assert post_erledigt.wieder_oeffnen(BEN, mid) is False
    assert _zeile(db, mid)["erledigt_am"] is None


def test_kontakt_zuordnung_ohne_gross_klein(db):
    mid = _mail(db, _konto(db), von="Max <Max@Firma.t-erledigt.example>")
    with db.pool.connection() as conn:
        lid = conn.execute(
            "insert into leads (name, email, source) values ('Max', "
            "'max@firma.t-erledigt.example', 't_erledigt') returning id").fetchone()["id"]
    zeilen, _ = post_erledigt.mails_offen(ANNA)
    z = [x for x in zeilen if str(x["id"]) == mid][0]
    assert str(z["lead_id"]) == str(lid)


def test_kontakt_anlegen(db):
    k = _konto(db)
    mid = _mail(db, k, von="Neu Mensch <neu@t-erledigt.example>")
    lid = post_erledigt.kontakt_anlegen(ANNA, mid)
    assert lid
    assert post_erledigt.kontakt_anlegen(ANNA, mid) == lid
    assert post_erledigt.kontakt_anlegen(BEN, mid) is None
    zeile = db._q("select name, source from leads where id = %s", (lid,))[0]
    assert zeile["name"] == "Neu Mensch" and zeile["source"] == "email"
