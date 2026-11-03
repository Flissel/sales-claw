"""Sichtbarkeit der Post-Sammelstelle (Spec §6/§7/§14.3).

Diese Suite verteidigt: private Post sieht nur ihr Besitzer (auch die
Leitung und der Bot nicht), sensible Mails verlieren Text und Auszug in jeder
Abfrage, Business-Post folgt den Abteilungen.
"""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import post_struktur as ps  # noqa: E402

NAMEN = ("t7_anna", "t7_ben", "t7_lea", "t7_inaktiv")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_mails, sales_test.post_konten "
                     "cascade")
        conn.execute("delete from sales_test.benutzer_abteilungen where "
                     "benutzer = any(%s)", (list(NAMEN),))
        conn.execute("delete from sales_test.benutzer where name = any(%s)",
                     (list(NAMEN),))


@pytest.fixture(autouse=True)
def welt():
    _aufraeumen()
    with server.pool.connection() as conn:
        for n, leit, akt in (("t7_anna", False, True), ("t7_ben", False, True),
                             ("t7_lea", True, True),
                             ("t7_inaktiv", False, False)):
            conn.execute(
                "insert into sales_test.benutzer (name, rolle, "
                "passwort_hash, aktiv, leitung) values "
                "(%s, 'lesen', 'x', %s, %s)", (n, akt, leit))
        conn.execute("insert into sales_test.benutzer_abteilungen values "
                     "('t7_ben', 'Vertrieb')")
    yield
    _aufraeumen()


_zaehler = [0]


def _mail(besitzer="t7_anna", bereich="business", fach="Kunden & Anfragen",
          sensibel=False, betreff="Angebot", text="Hallo Welt", datum=None):
    _zaehler[0] += 1
    konto = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, "
        "quelle) values (%s, %s, 'gmx', 'a@b.de', 'ui') "
        "on conflict (kennung) do update set besitzer = excluded.besitzer "
        "returning id", (besitzer, f"k-{besitzer}"))[0]["id"]
    return str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
        "von, betreff, text, auszug, bereich, fach, sensibel, datum) values "
        "(%s, %s, %s, %s, 'x@y.de', %s, %s, %s, %s, %s, %s, %s) "
        "returning id",
        (konto, _zaehler[0], f"m{_zaehler[0]}", besitzer, betreff, text,
         text[:20], bereich, fach, sensibel, datum))[0]["id"])


def _ids(b, **kw):
    return {str(r["id"]) for r in ps.mails_suchen(b, **kw)}


def _b(name):
    b = ps.betrachter_laden(name)
    assert b is not None
    return b


def test_privat_nur_fuer_besitzer():
    m = _mail("t7_anna", "privat", "Familie & Freunde")
    assert m in _ids(_b("t7_anna"))
    assert m not in _ids(_b("t7_ben"))
    assert m not in _ids(_b("t7_lea"))          # auch die Leitung nicht
    assert ps.mail_lesen(_b("t7_lea"), m) is None
    assert ps.mail_lesen(_b("t7_ben"), m) is None
    assert ps.mail_lesen(_b("t7_anna"), m) is not None


def test_business_nach_abteilung():
    kunden = _mail("t7_anna", "business", "Kunden & Anfragen")
    rechn = _mail("t7_anna", "business", "Rechnungen")
    ben = _ids(_b("t7_ben"))                    # Mitglied Vertrieb
    assert kunden in ben
    assert rechn not in ben


def test_unklar_nur_leitung_und_besitzer():
    unklar = _mail("t7_anna", "business", ps.UNKLAR)
    assert unklar not in _ids(_b("t7_ben"))
    assert unklar in _ids(_b("t7_anna"))
    assert unklar in _ids(_b("t7_lea"))


def test_privates_fach_gleichen_namens_oeffnet_nichts():
    # „Rechnungen“ privat von Anna darf Bens Abteilung nicht aufmachen.
    m = _mail("t7_anna", "privat", "Kunden & Anfragen")
    assert m not in _ids(_b("t7_ben"))


def test_nicht_eingeordnet_nur_besitzer():
    m = _mail("t7_anna", None, None)
    assert m in _ids(_b("t7_anna"))
    assert m not in _ids(_b("t7_lea"))
    assert m not in _ids(_b("t7_ben"))
    assert m not in _ids(ps.BETREIBER_AGENT)


def test_leitung_sieht_alle_business():
    a = _mail("t7_anna", "business", "Rechnungen")
    b = _mail("t7_ben", "business", ps.UNKLAR)
    assert {a, b} <= _ids(_b("t7_lea"))


def test_agent_sieht_weder_privat_noch_sensibel():
    ok = _mail("t7_anna", "business", "Kunden & Anfragen")
    priv = _mail("t7_anna", "privat", "Familie & Freunde")
    sens = _mail("t7_anna", "business", "Tools & Dienste", sensibel=True)
    ids = _ids(ps.BETREIBER_AGENT)
    assert ok in ids
    assert priv not in ids
    assert sens not in ids
    assert ps.mail_lesen(ps.BETREIBER_AGENT, priv) is None
    assert ps.mail_lesen(ps.BETREIBER_AGENT, sens) is None


def test_sensible_mail_ohne_text_auch_fuer_besitzer_in_der_suche():
    m = _mail("t7_anna", "privat", "Konten & Sicherheit", sensibel=True,
              betreff="Code", text="Ihr Code ist 123456")
    zeilen = ps.mails_suchen(_b("t7_anna"))
    z = next(r for r in zeilen if str(r["id"]) == m)
    assert z["text"] is None and z["auszug"] is None
    assert z["betreff"] == "Code"
    # Auch ueber die Suche nach dem Text nicht auffindbar
    assert m not in _ids(_b("t7_anna"), suche="123456")
    lesen = ps.mail_lesen(_b("t7_anna"), m)
    assert lesen["text"] is None and lesen["auszug"] is None


@pytest.mark.parametrize("s", ['"', "&", ":*", "   ", "'", "a & | !b", "\\"])
def test_suche_mit_sonderzeichen(s):
    _mail()
    ps.mails_suchen(_b("t7_anna"), suche=s)     # kein Fehler


def test_suche_findet_und_leer_filtert_nicht():
    m = _mail(text="Rechnung Nummer 4711")
    assert m in _ids(_b("t7_anna"), suche="4711")
    assert m not in _ids(_b("t7_anna"), suche="gibtsnicht")
    assert m in _ids(_b("t7_anna"), suche="   ")


def test_mail_lesen_fremde_id_none():
    b = _b("t7_anna")
    assert ps.mail_lesen(b, "00000000-0000-0000-0000-000000000000") is None
    assert ps.mail_lesen(b, "kein-uuid") is None
    assert ps.mail_lesen(b, "") is None


def test_filter_ungueltig_leer():
    _mail()
    b = _b("t7_anna")
    assert ps.mails_suchen(b, bereich="geheim") == []
    assert ps.mails_suchen(b, bereich="business",
                           fach="Familie & Freunde") == []
    assert ps.mails_suchen(b, fach="Gibtsnicht") == []
    assert ps.mails_suchen(b, konto_id="kein-uuid") == []


def test_filter_bereich_fach_konto():
    m = _mail("t7_anna", "business", "Kunden & Anfragen")
    _mail("t7_anna", "business", "Rechnungen")
    b = _b("t7_anna")
    assert _ids(b, bereich="business", fach="Kunden & Anfragen") == {m}
    konto = str(server._q("select id from post_konten limit 1")[0]["id"])
    assert m in _ids(b, konto_id=konto)


def test_reihenfolge_und_grenzen():
    alt = _mail(datum="2020-01-01")
    neu = _mail(datum="2024-01-01")
    ohne = _mail(datum=None)
    b = _b("t7_anna")
    assert [str(r["id"]) for r in ps.mails_suchen(b)] == [neu, alt, ohne]
    assert len(ps.mails_suchen(b, grenze=2)) == 2
    assert len(ps.mails_suchen(b, grenze=2, versatz=2)) == 1
    assert len(ps.mails_suchen(b, grenze=10_000, versatz=-5)) == 3


def test_betrachter_laden():
    assert ps.betrachter_laden("t7_gibtsnicht") is None
    assert ps.betrachter_laden("t7_inaktiv") is None
    ben = _b("t7_ben")
    assert ben.abteilungen == ("Vertrieb",) and not ben.leitung
    assert _b("t7_lea").leitung


def test_sichtbar_sql_ist_parametrisiert():
    boese = "x'; drop table y;--"
    frag, params = ps.sichtbar_sql(ps.Betrachter(boese, False, ("A'B",)))
    assert "drop" not in frag and "A'B" not in frag
    assert boese in params
