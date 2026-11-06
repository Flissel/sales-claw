"""Werbung ohne Modell: Absender-Regeln, Schutzregel, Regel-Vorschlag (Spec §4).

Oberer Teil rein (Regel-Laden und Schutz-Abfragen ersetzt, Modell ein Fake); unterer Teil
gegen die echte Datenbank, nur Schema sales_test.
"""
import os
import re
import sys
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_einordnung as pe  # noqa: E402
import post_struktur  # noqa: E402
import post_werbung  # noqa: E402

PRIVAT = {"kennung": "privat@example.org", "standard_bereich": "privat"}
WERBE_REGEL = {"muster": post_struktur.absender_muster("news@shop.example"), "feld": "von",
               "bereich": "privat", "fach": "Werbung", "unterfach": None, "besitzer": "felix"}


def _mail(**kw):
    m = {"id": "11111111-1111-1111-1111-111111111111", "besitzer": "felix",
         "von": "Shop <news@shop.example>", "betreff": "20 % auf alles",
         "datum": "2026-11-03", "text": "Inhalt"}
    m.update(kw)
    return m


def _urteil(bereich="privat", fach="Käufe & Bestellungen", sicher=True):
    return {"bereich": bereich, "fach": fach, "unterfach": "", "sensibel": False,
            "sicher": sicher, "begruendung": "x", "aufmerksamkeit": False}


def _modell(antwort, protokoll):
    def aufruf(agent, *a, **k):
        protokoll.append(agent)
        return antwort
    return aufruf


@pytest.fixture
def ohne_db(monkeypatch):
    """Keine Datenbank: Regeln aus einer Liste, kein Schutz, kein Bleibt-immer-Verlauf."""
    regeln = [dict(WERBE_REGEL)]
    monkeypatch.setattr(pe, "_regeln_laden", lambda: regeln)
    monkeypatch.setattr(post_werbung, "geschuetzt", lambda besitzer, von: False)
    monkeypatch.setattr(post_werbung, "bleibt_immer_absender", lambda besitzer, von: False)
    monkeypatch.setattr(pe.post_katalog, "treffer", lambda von: None)
    return regeln


def test_werbe_regel_ohne_modellaufruf(ohne_db):
    g = []
    e = pe.einordnen(_mail(), PRIVAT, aufruf=_modell(_urteil(), g))
    assert g == []
    assert (e.fach, e.quelle, e.aufrufe, e.sensibel, e.werbung_sicher, e.aufmerksamkeit) == \
        ("Werbung", "regel", 0, False, True, False)


def test_werbe_regel_greift_nicht_bei_rechnungsbetreff(ohne_db):
    g = []
    e = pe.einordnen(_mail(betreff="Ihre Rechnung 4711"), PRIVAT,
                     aufruf=_modell(_urteil(fach="Rechnungen"), g))
    assert g == ["post", "post-pruefer"]
    assert e.fach == "Rechnungen" and e.werbung_sicher is False


def test_betreff_muster_trifft_die_vereinbarten_woerter():
    for wort in ("Rechnung", "invoice", "Beleg", "Quittung", "Bestellung", "order", "Versand",
                 "Lieferung", "Vertrag", "Kündigung", "Mahnung", "Zahlung", "payment", "Konto",
                 "Passwort", "Sicherheit"):
        assert re.search(post_werbung.BLEIBT_BETREFF, f"Re: {wort} bestätigt"), wort
    assert not re.search(post_werbung.BLEIBT_BETREFF, "20 % auf alles")


def test_werbe_regel_greift_nicht_bei_absender_mit_frueherer_rechnung(ohne_db, monkeypatch):
    # R3: eine fruehere Mail in einem Bleibt-immer-Fach hebt die Regel fuer diesen Besitzer auf.
    monkeypatch.setattr(post_werbung, "bleibt_immer_absender", lambda besitzer, von: True)
    g = []
    e = pe.einordnen(_mail(), PRIVAT, aufruf=_modell(_urteil(fach="Rechnungen"), g))
    assert g == ["post", "post-pruefer"]
    assert e.werbung_sicher is False


def test_werbe_regel_greift_nicht_bei_geschuetztem_absender(ohne_db, monkeypatch):
    monkeypatch.setattr(post_werbung, "geschuetzt", lambda besitzer, von: True)
    g = []
    pe.einordnen(_mail(), PRIVAT, aufruf=_modell(_urteil(), g))
    assert g == ["post", "post-pruefer"]


def test_werbe_regel_ohne_besitzer_gilt_nicht(ohne_db):
    # Ohne Besitzer laesst sich Schutz und Verlauf nicht pruefen: fail closed.
    ohne_db[0]["besitzer"] = None
    g = []
    e = pe.einordnen(_mail(besitzer=None), PRIVAT, aufruf=_modell(_urteil(), g))
    assert g == ["post", "post-pruefer"] and e.werbung_sicher is False


def test_katalog_werbung_mit_frueherer_rechnung_geht_zum_modell(ohne_db, monkeypatch):
    ohne_db.clear()
    monkeypatch.setattr(pe.post_katalog, "treffer", lambda von: ("Werbung", None))
    monkeypatch.setattr(post_werbung, "bleibt_immer_absender", lambda besitzer, von: True)
    g = []
    e = pe.einordnen(_mail(), PRIVAT, aufruf=_modell(_urteil(fach="Rechnungen"), g))
    assert g == ["post", "post-pruefer"]
    assert e.quelle == "pruefer" and e.fach == "Rechnungen" and e.werbung_sicher is False


def test_katalog_werbung_ohne_ausschluss_bleibt_sicher(ohne_db, monkeypatch):
    ohne_db.clear()
    monkeypatch.setattr(pe.post_katalog, "treffer", lambda von: ("Werbung", None))
    g = []
    e = pe.einordnen(_mail(), PRIVAT, aufruf=_modell(_urteil(fach="Werbung"), g))
    assert g == ["post"] and e.quelle == "katalog" and e.werbung_sicher is True


def test_nach_nutzerregel_sucht_nach_ausgeschlossener_werbung_weiter(ohne_db):
    # Die naechste (aeltere) Regel gilt, wenn die Werbe-Regel nicht greifen darf.
    ohne_db.append({"muster": WERBE_REGEL["muster"], "feld": "von", "bereich": "privat",
                    "fach": "Käufe & Bestellungen", "unterfach": None, "besitzer": "felix"})
    e = pe.nach_nutzerregel(_mail(betreff="Bestellung 17"))
    assert e is not None and e.fach == "Käufe & Bestellungen"


def test_nie_werbung_regel_wird_nicht_als_einordnung_gelesen(monkeypatch):
    # Die Abfrage selbst filtert auf art = 'einordnen' (DB-Test unten); hier: eine Zeile
    # ohne Fach (so legt schutz_setzen sie an) setzt nie ein Fach.
    monkeypatch.setattr(pe, "_regeln_laden", lambda: [
        {"muster": WERBE_REGEL["muster"], "feld": "von", "bereich": None, "fach": None,
         "unterfach": None, "besitzer": "felix"}])
    assert pe.nach_nutzerregel(_mail()) is None


def test_modell_werbung_bei_geschuetztem_absender_ist_nicht_sicher(ohne_db, monkeypatch):
    ohne_db.clear()
    antwort = _urteil(fach="Werbung")
    g = []
    assert pe.einordnen(_mail(), PRIVAT, aufruf=_modell(antwort, g)).werbung_sicher is True
    monkeypatch.setattr(post_werbung, "geschuetzt", lambda besitzer, von: True)
    e = pe.einordnen(_mail(), PRIVAT, aufruf=_modell(antwort, g))
    assert e.fach == "Werbung" and e.quelle == "pruefer" and e.werbung_sicher is False


def test_absender_muster_und_adresse_leben_in_post_struktur():
    assert post_struktur.absender_adresse('"Shop" <News@Shop.Example>') == "news@shop.example"
    assert post_struktur.absender_adresse("kein absender") == ""
    muster = post_struktur.absender_muster("a@x.de")
    assert re.search(muster, "Name <a@x.de>") and not re.search(muster, "ba@x.de")


# --- gegen die echte Datenbank (nur sales_test) -------------------------------------------

@pytest.fixture
def db():
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_regeln")
            conn.execute("truncate sales_test.post_konten cascade")
    leeren()
    with server.pool.connection() as conn:
        konto_id = conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) values "
            "('felix', 'werbe-test', 'gmx', 'x@gmx.de', 'ui') returning id").fetchone()["id"]
    yield server, konto_id
    leeren()


def _mail_db(server, konto_id, nr, von="Shop <news@shop.example>", fach="Werbung", sicher=True,
             besitzer="felix"):
    with server.pool.connection() as conn:
        conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, bereich, fach, "
            "werbung_sicher, status) values (%s, %s, %s, %s, %s, 'privat', %s, %s, 'eingeordnet')",
            (konto_id, nr, f"m{nr}@x", besitzer, von, fach, sicher))


def _regeln(server, art=None):
    sql, p = "select * from post_regeln", ()
    if art:
        sql, p = sql + " where art = %s", (art,)
    return server._q(sql, p)


def test_regel_vorschlag_erst_ab_drei_sicheren_und_ohne_bleibt_immer(db):
    server, k = db
    von = "Shop <news@shop.example>"
    for nr in (1, 2):
        _mail_db(server, k, nr)
    assert post_werbung.regel_vorschlagen("felix", von) is False
    assert _regeln(server) == []
    _mail_db(server, k, 3)
    assert post_werbung.regel_vorschlagen("felix", von) is True
    (regel,) = _regeln(server)
    assert (regel["art"], regel["feld"], regel["fach"], regel["besitzer"], regel["sensibel"]) == \
        ("einordnen", "von", "Werbung", "felix", False)
    assert regel["muster"] == post_struktur.absender_muster("news@shop.example")
    # Zweites Mal: Regel steht schon, nichts Doppeltes.
    assert post_werbung.regel_vorschlagen("felix", von) is False
    assert len(_regeln(server)) == 1


def test_regel_vorschlag_nicht_bei_rechnung_oder_zum_nachsehen_vom_absender(db):
    server, k = db
    for nr in (1, 2, 3):
        _mail_db(server, k, nr)
    _mail_db(server, k, 4, fach="Rechnungen", sicher=False)
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is False
    server._q("update post_mails set fach = %s where imap_uid = 4", (post_struktur.UNKLAR,))
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is False
    assert _regeln(server) == []


def test_regel_vorschlag_zaehlt_nur_diesen_absender_und_besitzer(db):
    server, k = db
    for nr in (1, 2):
        _mail_db(server, k, nr)
    _mail_db(server, k, 3, von="news@shop.example.evil.com")      # anderer Absender
    _mail_db(server, k, 4, besitzer="ben")                         # anderer Besitzer
    _mail_db(server, k, 5, fach="Rechnungen", sicher=False, besitzer="ben")   # fremde Rechnung
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is False
    _mail_db(server, k, 6, von="NEWS@Shop.example")                # Schreibweise egal
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is True


def test_regel_vorschlag_nicht_bei_geschuetztem_absender(db):
    server, k = db
    for nr in (1, 2, 3):
        _mail_db(server, k, nr)
    post_werbung.schutz_setzen("felix", "news@shop.example")
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is False
    assert _regeln(server, "einordnen") == []


def test_regel_vorschlag_ueberschreibt_menschliche_regel_nicht(db):
    server, k = db
    for nr in (1, 2, 3):
        _mail_db(server, k, nr)
    server._q("insert into post_regeln (muster, feld, bereich, fach, sensibel, besitzer) values "
              "(%s, 'von', 'privat', 'Abos & Newsletter', false, 'felix')",
              (post_struktur.absender_muster("news@shop.example"),))
    assert post_werbung.regel_vorschlagen("felix", "news@shop.example") is False
    assert [r["fach"] for r in _regeln(server)] == ["Abos & Newsletter"]


def test_schutz_loescht_werbe_regel(db):
    server, k = db
    muster = post_struktur.absender_muster("news@shop.example")
    ins = ("insert into post_regeln (muster, feld, bereich, fach, sensibel, besitzer) "
           "values (%s, 'von', 'privat', %s, false, %s)")
    server._q(ins, (muster, "Werbung", "felix"))
    server._q(ins, (muster, "Werbung", "ben"))                    # anderer Besitzer bleibt
    server._q(ins, (muster, "Abos & Newsletter", "felix"))        # anderes Fach bleibt
    assert post_werbung.geschuetzt("felix", "news@shop.example") is False
    post_werbung.schutz_setzen("felix", "Shop <News@shop.example>")
    post_werbung.schutz_setzen("felix", "news@shop.example")      # doppelt: keine zweite Zeile
    assert post_werbung.geschuetzt("felix", "news@shop.example") is True
    assert post_werbung.geschuetzt("ben", "news@shop.example") is False
    assert len(_regeln(server, "nie_werbung")) == 1
    rest = sorted((r["besitzer"], r["fach"]) for r in _regeln(server, "einordnen"))
    assert rest == [("ben", "Werbung"), ("felix", "Abos & Newsletter")]


def test_nie_werbung_zeile_wird_aus_der_tabelle_nicht_als_einordnung_geladen(db):
    post_werbung.schutz_setzen("felix", "news@shop.example")
    assert pe._regeln_laden() == []


def test_bleibt_immer_absender_nur_fuer_den_eigenen_besitzer(db):
    server, k = db
    _mail_db(server, k, 1, fach="Rechnungen", sicher=False)
    assert post_werbung.bleibt_immer_absender("felix", "Shop <news@shop.example>") is True
    assert post_werbung.bleibt_immer_absender("ben", "news@shop.example") is False
    assert post_werbung.bleibt_immer_absender("felix", "andere@shop.example") is False
    _mail_db(server, k, 2, von="b@x.example", fach="Abos & Newsletter", sicher=False)
    assert post_werbung.bleibt_immer_absender("felix", "b@x.example") is False


def test_ergebnis_speichern_schlaegt_nach_dritter_sicherer_werbemail_die_regel_vor(db):
    import post_abholen
    server, k = db
    for nr in (1, 2):
        _mail_db(server, k, nr)
    with server.pool.connection() as conn:
        mail_id = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, status) "
            "values (%s, 3, 'm3@x', 'felix', 'Shop <news@shop.example>', 'neu') returning id",
            (k,)).fetchone()["id"]
    sicher = pe.Einordnung("privat", "Werbung", False, "pruefer", "x", None, aufrufe=2,
                           werbung_sicher=True)
    post_abholen._ergebnis_speichern(mail_id, sicher)
    assert [r["fach"] for r in _regeln(server)] == ["Werbung"]


def test_ergebnis_speichern_ohne_sichere_werbung_legt_keine_regel_an(db):
    import post_abholen
    server, k = db
    for nr in (1, 2, 3):
        _mail_db(server, k, nr)
    with server.pool.connection() as conn:
        mail_id = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, status) "
            "values (%s, 4, 'm4@x', 'felix', 'Shop <news@shop.example>', 'neu') returning id",
            (k,)).fetchone()["id"]
    post_abholen._ergebnis_speichern(mail_id, pe.Einordnung(
        "privat", "Rechnungen", False, "pruefer", "x", None, aufrufe=2))
    assert _regeln(server) == []
