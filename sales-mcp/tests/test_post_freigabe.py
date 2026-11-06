"""Loeschfreigabe je Jahr (Spec 2026-11-06 6.1; Review Focus 2 und 4).

Gegen die echte Datenbank, nur sales_test.
"""
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_freigabe  # noqa: E402
import post_werbung  # noqa: E402
import post_ziel  # noqa: E402

SHOP = "Shop <News@Shop.example>"
ANDERER = "Anderer <info@anderer.example>"


@pytest.fixture
def db(monkeypatch):
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_regeln")
            conn.execute("truncate sales_test.post_loeschfreigaben")
            conn.execute("truncate sales_test.post_konten cascade")
    leeren()
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 1, 1))
    yield server
    leeren()


def _konto(server, besitzer="felix", kennung="gmx-test"):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values (%s, %s, 'gmx', %s, 'ui') returning id",
            (besitzer, kennung, f"{kennung}@x.de")).fetchone()["id"]


_zaehler = iter(range(1, 10_000))


def _mail(server, konto, besitzer="felix", von=SHOP, betreff="Rabatt", jahr=2025,
          ziel="loeschen", fach="Werbung"):
    n = next(_zaehler)
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, "
            "text, bereich, fach, werbung_sicher, aufmerksamkeit, status, ziel, datum, anhaenge) "
            "values (%s, %s, %s, %s, %s, %s, 'T', 'privat', %s, true, false, 'eingeordnet', "
            "%s, %s, '{}') returning id",
            (konto, n, f"m{n}@x", besitzer, von, betreff, fach, ziel,
             datetime(jahr, 6, 1, 12, tzinfo=timezone.utc))).fetchone()["id"]


def _ziel(server, mail_id):
    return server._q("select ziel, ziel_manuell from post_mails where id = %s", (mail_id,))[0]


def test_vorschau_gruppiert_absender_mit_hoechstens_drei_beispielen(db):
    k = _konto(db)
    for i in range(5):
        _mail(db, k, betreff=("Lang " * 30) if i == 0 else f"Aktion {i}")
    _mail(db, k, von=ANDERER)
    _mail(db, k, jahr=2024)                       # anderes Jahr
    _mail(db, k, ziel="zur_info")                 # nicht loeschbar
    v = post_freigabe.vorschau("felix", 2025)
    assert [(g["absender"], g["anzahl"]) for g in v] == [
        ("news@shop.example", 5), ("info@anderer.example", 1)]
    assert len(v[0]["beispiele"]) == 3
    assert all(len(b) <= 80 for b in v[0]["beispiele"])


def test_vorschau_und_freigabe_nur_eigene_konten(db):
    ivan = _konto(db, "ivan", "gmx-ivan")
    # Auch eine Mail, deren post_mails.besitzer falsch auf felix steht, gehoert zum Konto von ivan.
    m1 = _mail(db, ivan, besitzer="ivan")
    m2 = _mail(db, ivan, besitzer="felix")
    assert post_freigabe.vorschau("felix", 2025) == []
    assert post_freigabe.freigeben("felix", 2025, [], []) == 0
    assert _ziel(db, m1)["ziel"] == "loeschen"
    assert _ziel(db, m2)["ziel"] == "loeschen"
    assert post_freigabe.jahre("felix") == []


def test_ausgenommener_absender_wird_geschuetzt_und_bleibt(db):
    k = _konto(db)
    a = _mail(db, k)
    b = _mail(db, k, von=ANDERER)
    n = post_freigabe.freigeben("felix", 2025, [SHOP, ANDERER], ["NEWS@shop.example"])
    assert n == 1
    assert _ziel(db, a) == {"ziel": "zur_info", "ziel_manuell": False}
    assert _ziel(db, b)["ziel"] == "loeschen"
    assert post_werbung.geschuetzt("felix", SHOP)
    f = db._q("select ausgenommen from post_loeschfreigaben")[0]
    assert f["ausgenommen"] == ["news@shop.example"]
    # Der naechste Ziel-Lauf dreht nichts zurueck.
    post_ziel.ziele_aktualisieren()
    assert _ziel(db, a)["ziel"] == "zur_info"
    assert _ziel(db, b)["ziel"] == "loeschen"


def test_zweite_freigabe_desselben_jahres_wirft(db):
    k = _konto(db)
    a = _mail(db, k)
    post_freigabe.freigeben("felix", 2025, [SHOP], [])
    with pytest.raises(ValueError, match="schon freigegeben"):
        post_freigabe.freigeben("felix", 2025, [], [SHOP])
    # nichts geaendert: keine Schutzregel, Mail bleibt loeschbar
    assert not post_werbung.geschuetzt("felix", SHOP)
    assert _ziel(db, a)["ziel"] == "loeschen"
    assert db._q("select count(*) as n from post_loeschfreigaben")[0]["n"] == 1


def test_nicht_gezeigter_absender_geht_nach_to_review_statt_loeschen(db):
    k = _konto(db)
    gesehen = _mail(db, k)
    neu = _mail(db, k, von=ANDERER)
    n = post_freigabe.freigeben("felix", 2025, ["Shop <news@shop.example>"], [])
    assert n == 1
    assert _ziel(db, gesehen)["ziel"] == "loeschen"
    assert _ziel(db, neu)["ziel"] == "to_review"
    post_ziel.ziele_aktualisieren()
    assert _ziel(db, gesehen)["ziel"] == "loeschen"
    assert _ziel(db, neu)["ziel"] == "to_review"


def test_ausgenommen_gezeigt_und_nicht_gezeigt_bleiben_nach_ziel_lauf_stabil(db):
    k = _konto(db)
    aus = _mail(db, k, von="Aus <aus@x.example>")
    ok = _mail(db, k, von="Ok <ok@x.example>")
    fremd = _mail(db, k, von="Neu <neu@x.example>")
    post_freigabe.freigeben("felix", 2025, ["ok@x.example", "aus@x.example"], ["aus@x.example"])
    post_ziel.ziele_aktualisieren()
    assert [_ziel(db, i)["ziel"] for i in (aus, ok, fremd)] == ["zur_info", "loeschen", "to_review"]


def test_fehler_mitten_in_freigabe_laesst_nichts_zurueck(db, monkeypatch):
    k = _konto(db)
    a = _mail(db, k)

    def kaputt(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(post_werbung, "schutz_setzen", kaputt)
    with pytest.raises(RuntimeError):
        post_freigabe.freigeben("felix", 2025, [SHOP], [SHOP])
    assert db._q("select count(*) as n from post_loeschfreigaben")[0]["n"] == 0
    assert _ziel(db, a)["ziel"] == "loeschen"


def test_nach_freigabe_erkannte_werbung_geht_nach_to_review(db):
    k = _konto(db)
    _mail(db, k)
    post_freigabe.freigeben("felix", 2025, [SHOP], [])
    spaet = _mail(db, k, von=ANDERER, ziel=None)       # erst jetzt als Werbung eingeordnet
    assert post_ziel.ziel_fuer(
        {"fach": "Werbung", "werbung_sicher": True, "anhaenge": [], "ziel": None,
         "datum": datetime(2025, 6, 1, tzinfo=timezone.utc)},
        datetime.now(timezone.utc), {2025}, False, False) == "to_review"
    post_ziel.ziele_aktualisieren()
    assert _ziel(db, spaet)["ziel"] == "to_review"


def test_jahre_zaehlt_offen_und_zu_loeschen(db):
    k = _konto(db)
    _mail(db, k)
    _mail(db, k, ziel="zur_info")
    _mail(db, k, jahr=2024)
    post_freigabe.freigeben("felix", 2024, [SHOP], [])
    j = post_freigabe.jahre("felix")
    assert [(x["jahr"], x["eingeordnet"], x["offen"], x["zu_loeschen"]) for x in j] == [
        (2025, 2, 1, 0), (2024, 1, 0, 1)]
    assert j[0]["freigegeben_am"] is None and j[1]["freigegeben_am"] is not None
