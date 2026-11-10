"""Sichtbarkeit der Post-Sammelstelle (Spec §6/§7/§14.3).

Diese Suite verteidigt: private Post sieht nur ihr Besitzer (auch die
Leitung und der Bot nicht), sensible Mails verlieren Text und Auszug in jeder
Abfrage, jede Mail sieht nur ihr Besitzer (auch Leitung und Abteilungen nicht),
der Bot nur Business des Container-Besitzers.
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
          sensibel=False, betreff="Angebot", text="Hallo Welt", datum=None,
          anhaenge=(), an=None):
    _zaehler[0] += 1
    konto = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, "
        "quelle) values (%s, %s, 'gmx', 'a@b.de', 'ui') "
        "on conflict (kennung) do update set besitzer = excluded.besitzer "
        "returning id", (besitzer, f"k-{besitzer}"))[0]["id"]
    return str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
        "von, betreff, text, auszug, bereich, fach, sensibel, datum, "
        "anhaenge, an) values "
        "(%s, %s, %s, %s, 'x@y.de', %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "returning id",
        (konto, _zaehler[0], f"m{_zaehler[0]}", besitzer, betreff, text,
         text[:20], bereich, fach, sensibel, datum, list(anhaenge), an))[0]["id"])


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


def test_abteilung_sieht_fremde_business_nicht():
    # DSGVO: ein Container = ein Nutzer. Auch Abteilungsmitglieder sehen
    # fremde Mails nicht, selbst wenn das Fach zu ihrer Abteilung passt.
    kunden = _mail("t7_anna", "business", "Kunden & Anfragen")
    rechn = _mail("t7_anna", "business", "Rechnungen")
    ben = _ids(_b("t7_ben"))                    # Mitglied Vertrieb
    assert kunden not in ben
    assert rechn not in ben
    assert ps.mail_lesen(_b("t7_ben"), kunden) is None


def test_unklar_nur_besitzer():
    unklar = _mail("t7_anna", "business", ps.UNKLAR)
    assert unklar not in _ids(_b("t7_ben"))
    assert unklar in _ids(_b("t7_anna"))
    assert unklar not in _ids(_b("t7_lea"))     # Leitung: fremde Mail, nein


def test_sensible_business_mail_nur_besitzer():
    server._q("insert into post_abteilungen (name) values ('Marketing') "
              "on conflict do nothing")
    # Die Migration legt die Zeile an; nur loeschen, was dieser Test selbst
    # eingefuegt hat.
    selbst_eingefuegt = bool(server._q(
        "insert into post_abteilung_faecher (abteilung, fach) values "
        "('Marketing', 'Soziale Netzwerke') on conflict do nothing returning fach"))
    server._q("insert into benutzer_abteilungen values ('t7_ben', "
              "'Marketing') on conflict do nothing")
    try:
        sens = _mail("t7_anna", "business", "Soziale Netzwerke", sensibel=True)
        offen = _mail("t7_anna", "business", "Soziale Netzwerke")
        assert sens in _ids(_b("t7_anna"))
        assert sens not in _ids(_b("t7_lea"))        # Leitung: fremde Mail
        assert sens not in _ids(_b("t7_ben"))        # Abteilung nie
        assert offen not in _ids(_b("t7_ben"))       # Abteilung: auch nicht
        assert sens not in _ids(ps.BETREIBER_AGENT)
        assert ps.mail_lesen(_b("t7_ben"), sens) is None
        privat = _mail("t7_anna", "privat", "Konten & Sicherheit",
                       sensibel=True)
        assert privat in _ids(_b("t7_anna"))
        assert privat not in _ids(_b("t7_lea"))
    finally:
        if selbst_eingefuegt:
            server._q("delete from post_abteilung_faecher where abteilung = "
                      "'Marketing' and fach = 'Soziale Netzwerke'")
        server._q("delete from benutzer_abteilungen where benutzer = 't7_ben' "
                  "and abteilung = 'Marketing'")


def test_privates_fach_gleichen_namens_oeffnet_nichts():
    # Privates Fach mit dem Namen eines Vertriebs-Fachs oeffnet nichts.
    m = _mail("t7_anna", "privat", "Kunden & Anfragen")
    assert m not in _ids(_b("t7_ben"))


def test_nicht_eingeordnet_nur_besitzer():
    m = _mail("t7_anna", None, None)
    assert m in _ids(_b("t7_anna"))
    assert m not in _ids(_b("t7_lea"))
    assert m not in _ids(_b("t7_ben"))
    assert m not in _ids(ps.BETREIBER_AGENT)


def test_leitung_sieht_fremde_mails_nicht():
    a = _mail("t7_anna", "business", "Rechnungen")
    b = _mail("t7_ben", "business", ps.UNKLAR)
    assert not ({a, b} & _ids(_b("t7_lea")))
    eigene = _mail("t7_lea", "business", "Rechnungen")
    assert eigene in _ids(_b("t7_lea"))


def test_agent_sieht_weder_privat_noch_sensibel(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "t7_anna")
    ok = _mail("t7_anna", "business", "Kunden & Anfragen")
    priv = _mail("t7_anna", "privat", "Familie & Freunde")
    sens = _mail("t7_anna", "business", "Tools & Dienste", sensibel=True)
    ids = _ids(ps.BETREIBER_AGENT)
    assert ok in ids
    assert priv not in ids
    assert sens not in ids
    assert ps.mail_lesen(ps.BETREIBER_AGENT, priv) is None
    assert ps.mail_lesen(ps.BETREIBER_AGENT, sens) is None


def test_agent_sieht_nur_business_des_container_besitzers(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "t7_anna")
    anna = _mail("t7_anna", "business", "Kunden & Anfragen")
    ben = _mail("t7_ben", "business", "Kunden & Anfragen")
    ids = _ids(ps.BETREIBER_AGENT)
    assert anna in ids
    assert ben not in ids
    assert ps.mail_lesen(ps.BETREIBER_AGENT, ben) is None


@pytest.mark.parametrize("leer", ["", "   "])
def test_agent_ohne_container_besitzer_sieht_nichts(monkeypatch, leer):
    monkeypatch.setenv("POST_BESITZER", leer)
    _mail("t7_anna", "business", "Kunden & Anfragen")
    assert _ids(ps.BETREIBER_AGENT) == set()
    monkeypatch.delenv("POST_BESITZER")
    assert _ids(ps.BETREIBER_AGENT) == set()


def test_container_besitzer_liest_bei_jedem_aufruf(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "  t7_anna ")
    assert ps.container_besitzer() == "t7_anna"
    monkeypatch.setenv("POST_BESITZER", "t7_ben")
    assert ps.container_besitzer() == "t7_ben"
    monkeypatch.delenv("POST_BESITZER")
    assert ps.container_besitzer() == ""


def test_mail_verlauf_erlaubt(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "t7_anna")
    assert ps.mail_verlauf_erlaubt("t7_anna") is True
    assert ps.mail_verlauf_erlaubt("t7_ben") is False
    assert ps.mail_verlauf_erlaubt(None) is False
    assert ps.mail_verlauf_erlaubt("") is False
    monkeypatch.setenv("POST_BESITZER", "")
    assert ps.mail_verlauf_erlaubt("t7_anna") is False
    assert ps.mail_verlauf_erlaubt("") is False


def test_sensible_mail_ohne_text_auch_fuer_besitzer_in_der_suche():
    m = _mail("t7_anna", "privat", "Konten & Sicherheit", sensibel=True,
              betreff="Code", text="Ihr Code ist 123456")
    zeilen = ps.mails_suchen(_b("t7_anna"))
    z = next(r for r in zeilen if str(r["id"]) == m)
    assert z["text"] is None and z["auszug"] is None
    assert z["anhaenge"] == [] and z["an"] is None
    assert z["betreff"] == "Code"
    # Auch ueber die Suche nach dem Text nicht auffindbar
    assert m not in _ids(_b("t7_anna"), suche="123456")
    lesen = ps.mail_lesen(_b("t7_anna"), m)
    assert lesen["text"] is None and lesen["auszug"] is None
    assert lesen["anhaenge"] == [] and lesen["an"] is None
    # Auch bei einer sensiblen Business-Mail bleiben dem Besitzer nur
    # Metadaten; die Leitung sieht die fremde Mail gar nicht.
    b = _mail("t7_anna", "business", "Tools & Dienste", sensibel=True,
              text="geheim", anhaenge=["pass.pdf"], an="chef@x.de")
    k = ps.mail_lesen(_b("t7_anna"), b)
    assert k["text"] is None and k["auszug"] is None
    assert k["anhaenge"] == [] and k["an"] is None
    assert ps.mail_lesen(_b("t7_lea"), b) is None


def test_sensibel_spalte_ist_not_null():
    zeile = server._q(
        "select is_nullable from information_schema.columns where "
        "table_schema = 'sales_test' and table_name = 'post_mails' and "
        "column_name = 'sensibel'")[0]
    assert zeile["is_nullable"] == "NO"


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
