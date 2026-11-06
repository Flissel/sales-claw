"""Ziel je Mail (Spec 2026-11-06 §5/§6): welcher Ordner ist fuer die Mail vorgesehen.

Oberer Teil rein (ohne Datenbank); unterer Teil gegen die echte Datenbank, nur sales_test.
Hier hängt am Ende das Löschen: jeder Fall der Tabelle ist ein möglicher Verlust einer echten Mail.
"""
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_struktur  # noqa: E402
import post_ziel  # noqa: E402

MEZ = timezone(timedelta(hours=1))
JETZT = datetime(2026, 11, 6, 12, 0, tzinfo=MEZ)
LOGIN = "sensibel-muster:betreff:0"


def _m(**kw):
    m = {"fach": "Rechnungen", "aufmerksamkeit": False, "werbung_sicher": False,
         "datum": datetime(2025, 6, 1, 9, 0, tzinfo=MEZ), "anhaenge": [], "begruendung": "x",
         "ziel": None, "ziel_manuell": False}
    m.update(kw)
    return m


def _werbung(**kw):
    return _m(fach="Werbung", werbung_sicher=True, **kw)


@pytest.fixture(autouse=True)
def stichtag(monkeypatch):
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 11, 10))


def _ziel(m, freigegeben=frozenset(), kontakt=False, geschuetzt=False, jetzt=JETZT):
    return post_ziel.ziel_fuer(m, jetzt, set(freigegeben), kontakt, geschuetzt)


FAELLE = [
    ("unklar", _m(fach=post_struktur.UNKLAR, werbung_sicher=True), {}, "posteingang"),
    ("werbung 2025, Jahr nicht freigegeben", _werbung(), {}, "loeschen"),
    ("werbung 2025, freigegeben, ziel null", _werbung(), {"freigegeben": {2025}}, "to_review"),
    ("werbung 2025, freigegeben, ziel war loeschen", _werbung(ziel="loeschen"),
     {"freigegeben": {2025}}, "loeschen"),
    ("werbung, ziel war loeschen, geschuetzt", _werbung(ziel="loeschen"),
     {"freigegeben": {2025}, "geschuetzt": True}, "zur_info"),
    ("werbung nach ALTBESTAND_AB", _werbung(datum=datetime(2026, 11, 12, 8, 0, tzinfo=MEZ)),
     {}, "to_review"),
    ("werbung, Kontakt", _werbung(), {"kontakt": True}, "zur_info"),
    ("werbung, Anhang pdf", _werbung(anhaenge=["angebot.pdf"]), {}, "zur_info"),
    ("werbung, Anhang png", _werbung(anhaenge=["bild.png"]), {}, "loeschen"),
    ("werbung, Anhang Bild und pdf", _werbung(anhaenge=["bild.png", "a.pdf"]), {}, "zur_info"),
    ("werbung, Anhang ohne Endung", _werbung(anhaenge=["bild"]), {}, "zur_info"),
    ("werbung, Anhang JPG gross", _werbung(anhaenge=["BILD.JPG"]), {}, "loeschen"),
    ("werbung nicht sicher", _m(fach="Werbung", werbung_sicher=False), {}, "zur_info"),
    ("werbung sicher, geschuetzt", _werbung(), {"geschuetzt": True}, "zur_info"),
    ("rechnung mit aufmerksamkeit, 2026-10-20",
     _m(aufmerksamkeit=True, datum=datetime(2026, 10, 20, 9, 0, tzinfo=MEZ)), {}, "posteingang"),
    ("rechnung mit aufmerksamkeit, Altbestand > 90 Tage",
     _m(aufmerksamkeit=True, datum=datetime(2026, 5, 1, 9, 0, tzinfo=MEZ)), {}, "zur_info"),
    ("rechnung ohne aufmerksamkeit", _m(), {}, "zur_info"),
    ("login-code vor 2 Stunden",
     _m(fach="Konten & Sicherheit", aufmerksamkeit=True, begruendung=LOGIN,
        datum=JETZT - timedelta(hours=2)), {}, "posteingang"),
    ("login-code vor 2 Tagen",
     _m(fach="Konten & Sicherheit", aufmerksamkeit=True, begruendung=LOGIN,
        datum=JETZT - timedelta(days=2)), {}, "zur_info"),
    ("manuell posteingang, fach Werbung",
     _werbung(ziel="posteingang", ziel_manuell=True), {}, "posteingang"),
    ("manuell zur_info schlaegt Werbung loeschen",
     _werbung(ziel="zur_info", ziel_manuell=True), {}, "zur_info"),
]


@pytest.mark.parametrize("m,kw,erwartet", [f[1:] for f in FAELLE], ids=[f[0] for f in FAELLE])
def test_ziel_fuer(m, kw, erwartet):
    assert _ziel(m, **kw) == erwartet


def test_aufmerksamkeit_alt_bleibt_im_posteingang_nach_stichtag_r2():
    # Spec §5: eine Mail, die im Posteingang alt wird, bleibt dort. Bezugspunkt ist der Stichtag,
    # nicht „jetzt“ - sonst wanderte jede Aufmerksamkeits-Mail nach 90 Tagen ab.
    m = _m(aufmerksamkeit=True, datum=datetime(2026, 10, 20, 9, 0, tzinfo=MEZ))
    assert _ziel(m, jetzt=datetime(2027, 3, 1, 12, 0, tzinfo=MEZ)) == "posteingang"


def test_aufmerksamkeit_neue_mail_nie_alterung():
    m = _m(aufmerksamkeit=True, datum=datetime(2026, 11, 12, 9, 0, tzinfo=MEZ))
    assert _ziel(m, jetzt=datetime(2030, 1, 1, tzinfo=MEZ)) == "posteingang"


def test_altbestand_genau_neunzig_tage_bleibt_neunzig_und_eins_geht():
    heute = JETZT.date()           # Bezugspunkt = min(heute, Stichtag) = heute
    grenze = datetime.combine(heute - timedelta(days=90), datetime.min.time(), tzinfo=MEZ)
    assert _ziel(_m(aufmerksamkeit=True, datum=grenze)) == "posteingang"
    assert _ziel(_m(aufmerksamkeit=True, datum=grenze - timedelta(days=1))) == "zur_info"


@pytest.mark.parametrize("m,kw,erwartet", [
    (_werbung(datum=None), {}, "zur_info"),
    (_werbung(datum=None, ziel="loeschen"), {"freigegeben": {2025}}, "zur_info"),
    (_m(aufmerksamkeit=True, datum=None), {}, "posteingang"),
    (_m(aufmerksamkeit=False, datum=None), {}, "zur_info"),
    (_m(fach="Konten & Sicherheit", aufmerksamkeit=True, begruendung=LOGIN, datum=None), {},
     "posteingang"),
], ids=["werbung", "werbung-war-loeschen", "aufmerksamkeit", "ohne", "login-code"])
def test_ohne_datum_nie_loeschen_nie_to_review(m, kw, erwartet):
    assert _ziel(m, **kw) == erwartet


def test_ohne_stichtag_ist_alles_altbestand(monkeypatch):
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date.max)
    # Auch eine Mail vom 12.11. gilt dann als Altbestand: sie wartet auf die Jahres-Freigabe,
    # statt direkt nach To-Review zu gehen.
    m = _werbung(datum=datetime(2026, 11, 12, 8, 0, tzinfo=MEZ))
    assert _ziel(m) == "loeschen"


def test_stichtag_aus_umgebung(monkeypatch):
    assert post_ziel._stichtag("2026-11-10") == date(2026, 11, 10)
    assert post_ziel._stichtag("") == date.max
    assert post_ziel._stichtag(None) == date.max
    assert post_ziel._stichtag("kaputt") == date.max   # fail closed: alles Altbestand


def test_datum_als_text_wird_gelesen():
    assert _ziel(_werbung(datum="2025-06-01T09:00:00+01:00")) == "loeschen"


# --- gegen die echte Datenbank (nur sales_test) -------------------------------------------

@pytest.fixture
def db():
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"
    marke = f"ziel-{uuid.uuid4().hex[:8]}"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_regeln")
            conn.execute("truncate sales_test.post_loeschfreigaben")
            conn.execute("truncate sales_test.post_konten cascade")
            conn.execute("delete from leads where source = %s", (marke,))
    leeren()
    with server.pool.connection() as conn:
        konto_id = conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) values "
            "('felix', 'ziel-test', 'gmx', 'x@gmx.de', 'ui') returning id").fetchone()["id"]
    yield server, konto_id, marke
    leeren()


def _mail(server, konto_id, nr, von="Shop <news@shop.example>", fach="Werbung", sicher=True,
          status="eingeordnet", ziel=None, manuell=False, besitzer="felix",
          datum="2025-06-01T09:00:00+01:00", anhaenge=()):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, bereich, fach, "
            "werbung_sicher, status, ziel, ziel_manuell, datum, anhaenge) values "
            "(%s, %s, %s, %s, %s, 'privat', %s, %s, %s, %s, %s, %s, %s) returning id",
            (konto_id, nr, f"z{nr}@x", besitzer, von, fach, sicher, status, ziel, manuell,
             datum, list(anhaenge))).fetchone()["id"]


def _ziel_db(server, mail_id):
    return server._q("select ziel from post_mails where id = %s", (mail_id,))[0]["ziel"]


def test_aktualisieren_setzt_fehlendes_ziel(db):
    server, k, _ = db
    wer = _mail(server, k, 1)
    wb = _mail(server, k, 2, von="a@b.de", fach="Rechnungen", sicher=False)
    assert post_ziel.ziele_aktualisieren() == 2
    assert _ziel_db(server, wer) == "loeschen"      # Jahr 2025 nicht freigegeben
    assert _ziel_db(server, wb) == "zur_info"


def test_aktualisieren_laesst_manuelles_ziel_in_ruhe(db):
    server, k, _ = db
    mid = _mail(server, k, 1, ziel="posteingang", manuell=True)
    assert post_ziel.ziele_aktualisieren() == 0
    assert _ziel_db(server, mid) == "posteingang"


def test_aktualisieren_fasst_geloeschte_nicht_an(db):
    server, k, _ = db
    mid = _mail(server, k, 1, status="geloescht", ziel="loeschen")
    neu = _mail(server, k, 2, status="neu")
    assert post_ziel.ziele_aktualisieren() == 0
    assert _ziel_db(server, mid) == "loeschen"
    assert _ziel_db(server, neu) is None


def test_aktualisieren_kontakt_aus_leads_schuetzt_auch_archivierte(db):
    server, k, marke = db
    mid = _mail(server, k, 1, von="Frau Meier <Meier@Kunde.example>")
    with server.pool.connection() as conn:
        conn.execute("insert into leads (name, email, source, status) values "
                     "('Meier', ' MEIER@kunde.example ', %s, 'lost')", (marke,))
    assert post_ziel.ziele_aktualisieren() == 1
    assert _ziel_db(server, mid) == "zur_info"


def test_aktualisieren_nie_werbung_regel_schuetzt_nur_den_eigenen_besitzer(db):
    server, k, _ = db
    eigene = _mail(server, k, 1)
    fremde = _mail(server, k, 2, besitzer="laura")
    with server.pool.connection() as conn:
        conn.execute("insert into post_regeln (muster, feld, sensibel, besitzer, art) values "
                     "(%s, 'von', false, 'felix', 'nie_werbung')",
                     (post_struktur.absender_muster("news@shop.example").upper(),))
    assert post_ziel.ziele_aktualisieren() == 2
    assert _ziel_db(server, eigene) == "zur_info"
    assert _ziel_db(server, fremde) == "loeschen"


def test_aktualisieren_freigegebenes_jahr_je_besitzer(db):
    server, k, _ = db
    eigene = _mail(server, k, 1)
    fremde = _mail(server, k, 2, besitzer="laura")
    with server.pool.connection() as conn:
        conn.execute("insert into post_loeschfreigaben (besitzer, jahr) values ('felix', 2025)")
    post_ziel.ziele_aktualisieren()
    # Jahr freigegeben, ziel war null: erst nach der Freigabe als Werbung erkannt -> to_review.
    assert _ziel_db(server, eigene) == "to_review"
    assert _ziel_db(server, fremde) == "loeschen"


def test_aktualisieren_zaehlt_nur_geaenderte_zeilen(db):
    server, k, _ = db
    _mail(server, k, 1)
    _mail(server, k, 2, fach="Rechnungen", sicher=False)
    assert post_ziel.ziele_aktualisieren() == 2
    assert post_ziel.ziele_aktualisieren() == 0
