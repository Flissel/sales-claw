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
from test_post_imap import FakeKasten, mail  # noqa: E402

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
            conn.execute("delete from sales_test.drafts "
                         "where recipient like '%@t-erledigt.example'")
            conn.execute("delete from sales_test.leads where source = 't_erledigt' "
                         "or email like '%@t-erledigt.example' "
                         "or email like '%.t-erledigt.example'")
    leeren()
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 11, 1))
    yield server
    leeren()


def _konto(server, besitzer="t_anna", kennung="t-anna", uidvalidity=1):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle, uidvalidity) "
            "values (%s, %s, 'gmx', %s, 'ui', %s) returning id",
            (besitzer, kennung, f"{kennung}@x.de", uidvalidity)).fetchone()["id"]


_n = [0]


def _mail(server, konto_id, *, besitzer="t_anna", datum="2026-11-02", ziel="posteingang",
          abgeglichen=True, fach="Kunden & Anfragen", von="Max <max@t-erledigt.example>",
          uid=None, mid=None, ersatz=False, ordner="INBOX", ordner_uid=None,
          abgleich_aus=False):
    _n[0] += 1
    uid = _n[0] if uid is None else uid
    mid = f"e{_n[0]}@x" if mid is None else mid
    with server.pool.connection() as conn:
        return str(conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, "
            "text, auszug, bereich, fach, status, ziel, datum, anhaenge, abgeglichen_am, "
            "message_id_ersatz, ordner, ordner_uid, abgleich_aus) "
            "values (%s, %s, %s, %s, %s, 'Betreff', 'Text', 'Auszug', 'business', %s, "
            "'eingeordnet', %s, %s::timestamptz, '{}', "
            + ("now()" if abgeglichen else "null") + ", %s, %s, %s, %s) returning id",
            (konto_id, uid, mid, besitzer, von, fach, ziel, datum,
             ersatz, ordner, ordner_uid, abgleich_aus)
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


# --- Antwort-Abgleich -------------------------------------------------------------

def _verbinden(kaesten: dict, aufrufe=None):
    def verbinden(zeile):
        if aufrufe is not None:
            aufrufe.append(zeile["kennung"])
        return kaesten[zeile["kennung"]]
    return verbinden


@pytest.fixture
def abg(db, monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "t_anna")
    return db


def _schreibend(k) -> list:
    return [p for p in k.protokoll
            if p[:2] in (("uid", "MOVE"), ("uid", "COPY"), ("uid", "STORE"), ("uid", "EXPUNGE"))
            or p[0] == "expunge"]


def _inbox(*uids, **kw) -> FakeKasten:
    return FakeKasten(ordner={"INBOX": {u: mail(f"m{u}@x") for u in uids}}, **kw)


def test_abgleich_answered_markiert_beantwortet(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    kasten = _inbox(7)
    kasten.flags[("INBOX", 7)] = {"\\Answered"}
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    z = _zeile(abg, m)
    assert z["erledigt_art"] == "beantwortet" and z["erledigt_am"] and z["abgeglichen_am"]
    assert bilanz == {"geprueft": 1, "beantwortet": 1, "fehlt": 0, "konten_fehler": 0,
                       "sent_fehler": 0}
    assert ("logout",) in kasten.protokoll


def test_abgleich_ohne_signal_bleibt_offen_aber_geprueft(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}))
    z = _zeile(abg, m)
    assert z["erledigt_am"] is None and z["abgeglichen_am"] is not None
    assert bilanz["geprueft"] == 1 and bilanz["beantwortet"] == 0
    assert m in _ids(ANNA)


def test_abgleich_gesendet_bei_gmail(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    roh = mail("a1@x").replace(b"Subject:", b"In-Reply-To: <m7@x>\nSubject:", 1)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "Gesendet": {3: roh}},
                        merkmale={"Gesendet": "\\Sent"})
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, m)["erledigt_art"] == "beantwortet"
    assert bilanz["beantwortet"] == 1


def _entwurf(abg, antwort_auf, status="sent"):
    abg._q("insert into drafts (channel, recipient, body, status, antwort_auf) "
           "values ('email', 'x@t-erledigt.example', 'Text', %s, %s) returning id",
           (status, antwort_auf))


def test_abgleich_entwurf_sent(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    _entwurf(abg, "m7@x")
    kasten = _inbox(7)
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, m)["erledigt_art"] == "beantwortet"
    assert bilanz["beantwortet"] == 1
    assert not kasten.protokoll          # kein IMAP noetig


def test_abgleich_entwurf_nicht_gesendet_zaehlt_nicht(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    _entwurf(abg, "m7@x", status="approved")
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}))
    assert _zeile(abg, m)["erledigt_am"] is None


def test_abgleich_fehlende_mail_bleibt_offen(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=99, mid="m99@x", abgeglichen=False)
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}))
    z = _zeile(abg, m)
    assert z["ordner_stand"] == "fehlt" and z["erledigt_am"] is None
    assert z["abgeglichen_am"] is not None
    assert bilanz["fehlt"] == 1 and bilanz["beantwortet"] == 0


def test_abgleich_ersatz_id_ohne_gesendet_suche(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="7:1@sales-post", ersatz=True, abgeglichen=False)
    _entwurf(abg, "7:1@sales-post")
    kasten = FakeKasten(ordner={"INBOX": {7: mail(None)}, "Gesendet": {}},
                        merkmale={"Gesendet": "\\Sent"})
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert not kasten.befehle("SEARCH")
    assert _zeile(abg, m)["erledigt_am"] is None     # auch der Entwurf zaehlt bei Ersatz-ID nicht


def test_abgleich_ueberspringt_wieder_geoeffnete(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgleich_aus=True)
    aufrufe = []
    kasten = _inbox(7)
    kasten.flags[("INBOX", 7)] = {"\\Answered"}
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}, aufrufe))
    assert _zeile(abg, m)["erledigt_am"] is None
    assert aufrufe == [] and bilanz["geprueft"] == 0


def test_abgleich_ohne_stichtag_verbindet_nicht(abg, monkeypatch):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, abgeglichen=False)
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date.max)
    aufrufe = []
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}, aufrufe))
    assert aufrufe == [] and bilanz["geprueft"] == 0
    assert _zeile(abg, m)["abgeglichen_am"] is None


def test_abgleich_ohne_besitzer_verbindet_nicht(abg, monkeypatch):
    monkeypatch.delenv("POST_BESITZER")
    k_id = _konto(abg)
    _mail(abg, k_id, uid=7, abgeglichen=False)
    aufrufe = []
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}, aufrufe))
    assert aufrufe == [] and bilanz["geprueft"] == 0


def test_abgleich_nur_container_besitzer_und_stichtag(abg):
    k_id = _konto(abg)
    fremd = _konto(abg, besitzer="t_ben", kennung="t-ben")
    alt = _mail(abg, k_id, uid=7, datum="2026-10-31", abgeglichen=False)
    f = _mail(abg, fremd, uid=7, besitzer="t_ben", abgeglichen=False)
    aufrufe = []
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7), "t-ben": _inbox(7)},
                                                aufrufe))
    assert aufrufe == []                  # Anna: nur Altbestand; Ben: nicht der Besitzer
    assert _zeile(abg, alt)["abgeglichen_am"] is None
    assert _zeile(abg, f)["abgeglichen_am"] is None


def test_abgleich_kontofehler_zaehlt_und_geht_weiter(abg):
    a = _konto(abg, kennung="t-a1")
    b = _konto(abg, kennung="t-a2")
    _mail(abg, a, uid=7, abgeglichen=False)
    m2 = _mail(abg, b, uid=7, abgeglichen=False)

    def verbinden(zeile):
        if zeile["kennung"] == "t-a1":
            raise OSError("weg")
        return _inbox(7)
    bilanz = post_erledigt.abgleich(verbinden=verbinden)
    assert bilanz["konten_fehler"] == 1 and bilanz["geprueft"] == 1
    assert _zeile(abg, m2)["abgeglichen_am"] is not None


def test_abgleich_anderer_ordner_traut_answered_nicht(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", ordner="Rechnungen", ordner_uid=3,
              abgeglichen=False)
    kasten = FakeKasten(ordner={"INBOX": {}, "Rechnungen": {3: mail("m7@x")}})
    kasten.flags[("Rechnungen", 3)] = {"\\Answered"}
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    z = _zeile(abg, m)
    assert z["erledigt_am"] is None and z["abgeglichen_am"] is not None
    assert not kasten.befehle("FETCH")


def test_abgleich_uidvalidity_weicht_ab_kein_answered(abg):
    k_id = _konto(abg, uidvalidity=5)                     # live: 1
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    kasten = _inbox(7)
    kasten.flags[("INBOX", 7)] = {"\\Answered"}
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    z = _zeile(abg, m)
    assert z["erledigt_am"] is None and z["abgeglichen_am"] is not None
    assert bilanz["beantwortet"] == 0 and bilanz["geprueft"] == 1
    assert not kasten.befehle("FETCH")
    assert m in _ids(ANNA)


def test_abgleich_ohne_gespeicherte_uidvalidity_kein_answered(abg):
    k_id = _konto(abg, uidvalidity=None)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    kasten = _inbox(7)
    kasten.flags[("INBOX", 7)] = {"\\Answered"}
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, m)["erledigt_am"] is None


def test_abgleich_uidvalidity_abweichung_gesendet_gilt_noch(abg):
    k_id = _konto(abg, uidvalidity=5)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    roh = mail("a1@x").replace(b"Subject:", b"In-Reply-To: <m7@x>\nSubject:", 1)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "Gesendet": {3: roh}},
                        merkmale={"Gesendet": "\\Sent"})
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, m)["erledigt_art"] == "beantwortet"


def _gesendet_kasten(*antwort_auf):
    roh = {i + 3: mail(f"a{i}@x").replace(
        b"Subject:", f"In-Reply-To: <{mid}>\nSubject:".encode(), 1)
        for i, mid in enumerate(antwort_auf)}
    return FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")}, "Gesendet": roh},
                      merkmale={"Gesendet": "\\Sent"})


def test_abgleich_gesendet_ordner_nur_einmal_gewaehlt(abg):
    k_id = _konto(abg)
    _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    _mail(abg, k_id, uid=8, mid="m8@x", abgeglichen=False)
    kasten = _gesendet_kasten("m8@x")
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert [p for p in kasten.protokoll if p[:2] == ("select", "Gesendet")] == [
        ("select", "Gesendet", True)]
    assert bilanz["beantwortet"] == 1 and bilanz["sent_fehler"] == 0


def test_abgleich_platzhalter_uid_nutzt_gesendet_suche(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=0, mid="m7@x", abgeglichen=False)
    kasten = _gesendet_kasten("m7@x")
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, m)["erledigt_art"] == "beantwortet"
    assert not kasten.befehle("FETCH")


def test_abgleich_ordner_ohne_uid_nutzt_gesendet_suche(abg):
    k_id = _konto(abg)
    a = _mail(abg, k_id, uid=7, mid="m7@x", ordner="Rechnungen", ordner_uid=None,
              abgeglichen=False)
    b = _mail(abg, k_id, uid=8, mid="m8@x", ordner="Rechnungen", ordner_uid=None,
              abgeglichen=False, ersatz=True)
    kasten = _gesendet_kasten("m7@x", "m8@x")
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _zeile(abg, a)["erledigt_art"] == "beantwortet"
    z = _zeile(abg, b)
    assert z["erledigt_am"] is None and z["abgeglichen_am"] is not None


def test_abgleich_gesendet_fehler_wird_gezaehlt(abg):
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    kasten = _gesendet_kasten("m7@x")
    echt = kasten.select

    def select(ordner="INBOX", readonly=False):
        if "Gesendet" in str(ordner):
            return "NO", [b"kaputt"]
        return echt(ordner, readonly)
    kasten.select = select
    bilanz = post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert bilanz["sent_fehler"] == 1 and bilanz["konten_fehler"] == 0
    z = _zeile(abg, m)
    assert z["erledigt_am"] is None and z["abgeglichen_am"] is not None


def test_abgleich_schreibt_nie(abg):
    k_id = _konto(abg)
    _mail(abg, k_id, uid=7, mid="m7@x", abgeglichen=False)
    _mail(abg, k_id, uid=8, mid="m8@x", abgeglichen=False)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")}, "Gesendet": {}},
                        merkmale={"Gesendet": "\\Sent"})
    kasten.flags[("INBOX", 7)] = {"\\Answered", "\\Deleted"}
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": kasten}))
    assert _schreibend(kasten) == []
    selects = [p for p in kasten.protokoll if p[0] == "select"]
    assert selects and all(p[2] is True for p in selects)
    assert kasten.flags[("INBOX", 7)] == {"\\Answered", "\\Deleted"}


def test_stichtag_sql_geteilt_mit_offen_sql(db, monkeypatch):
    assert post_erledigt.stichtag_sql() in post_erledigt.offen_sql()
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date.max)
    assert post_erledigt.stichtag_sql() == "false"
    assert post_erledigt.offen_sql() == "(m.ziel = 'posteingang' and m.status = 'eingeordnet' " \
        "and m.erledigt_am is null and m.abgeglichen_am is not null " \
        "and m.geloescht_am is null and false)"


def test_vor_erstem_abgleich_erledigt_dann_wieder_geoeffnet_erscheint(db):
    """I2: wieder_oeffnen setzt abgeglichen_am, sonst bleibt die Mail unsichtbar."""
    mid = _mail(db, _konto(db), abgeglichen=False)
    assert post_erledigt.erledigen(ANNA, mid, "erledigt") is True
    assert _zeile(db, mid)["abgeglichen_am"] is None
    assert post_erledigt.wieder_oeffnen(ANNA, mid) is True
    assert _zeile(db, mid)["abgeglichen_am"] is not None
    assert mid in _ids(ANNA)


def test_wieder_oeffnen_offener_mail_aendert_nichts(db):
    """I2: Guard erledigt_am is not null - offene Mail bleibt unveraendert."""
    mid = _mail(db, _konto(db))
    assert post_erledigt.wieder_oeffnen(ANNA, mid) is False
    assert _zeile(db, mid)["abgleich_aus"] is False


def test_abgleich_gefunden_setzt_fehlt_zurueck(abg):
    """Minor: wird eine als fehlt markierte Mail wiedergefunden, ist sie wieder 'ok'."""
    k_id = _konto(abg)
    m = _mail(abg, k_id, uid=7, mid="m7@x")
    abg._q("update post_mails set ordner_stand = 'fehlt' where id = %s returning id", (m,))
    post_erledigt.abgleich(verbinden=_verbinden({"t-anna": _inbox(7)}))
    assert _zeile(abg, m)["ordner_stand"] == "ok"
