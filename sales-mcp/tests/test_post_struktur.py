"""Tests der Post-Sammelstelle, Stufe 1: feste Faecher und Tabellen.

Die DB-Tests laufen nur gegen `sales_test` (Schema vorher mit
db/post-sammelstelle.sql eingespielt).
"""
import os

import pytest

import post_struktur

SPEC_PRIVAT = (
    "Familie & Freunde", "Käufe & Bestellungen", "Rechnungen",
    "Behörden & Versicherung", "Gesundheit", "Abos & Newsletter",
    "Soziale Netzwerke", "Konten & Sicherheit", "Werbung", "Zum Nachsehen",
)
SPEC_BUSINESS = (
    "Kunden & Anfragen", "Partner & Netzwerk", "Veranstaltungen", "Rechnungen",
    "Tools & Dienste", "Soziale Netzwerke", "Konten & Sicherheit",
    "Bewerbungen & Jobs", "Newsletter & Branche", "Werbung", "Zum Nachsehen",
)
ps = post_struktur


def test_faecher_sind_genau_die_spec_liste():
    assert post_struktur.BEREICHE == ("privat", "business")
    assert post_struktur.FAECHER["privat"] == SPEC_PRIVAT
    assert post_struktur.FAECHER["business"] == SPEC_BUSINESS


def test_unklar_in_beiden_bereichen():
    assert post_struktur.UNKLAR == "Zum Nachsehen"
    for bereich in post_struktur.BEREICHE:
        assert post_struktur.fach_gueltig(bereich, post_struktur.UNKLAR)
        assert not post_struktur.fach_gueltig(bereich, "Unklar")


def test_soziale_netzwerke_in_beiden_bereichen_mit_unterfaechern():
    for br in ("privat", "business"):
        assert "Soziale Netzwerke" in ps.FAECHER[br]
        assert "Konten & Sicherheit" in ps.FAECHER[br]
        assert ps.FAECHER[br][-1] == "Zum Nachsehen"
    assert ps.UNKLAR == "Zum Nachsehen"
    assert "Veranstaltungen" in ps.FAECHER["business"] and "Gesundheit" in ps.FAECHER["privat"]
    assert "Unklar" not in ps.FAECHER["privat"] + ps.FAECHER["business"]


def test_unterfach_zwingen():
    assert ps.unterfach_zwingen("Soziale Netzwerke", "Instagram") == "Instagram"
    assert ps.unterfach_zwingen("Soziale Netzwerke", "Myspace") == "Sonstige"
    assert ps.unterfach_zwingen("Soziale Netzwerke", None) == "Sonstige"
    assert ps.unterfach_zwingen("Werbung", "Instagram") is None
    assert ps.unterfach_gueltig("Werbung", None) and not ps.unterfach_gueltig("Werbung", "X")
    assert ps.unterfach_gueltig("Werbung", "")
    assert ps.unterfach_gueltig("Tools & Dienste", "GitHub")
    assert not ps.unterfach_gueltig("Tools & Dienste", "Instagram")
    assert not ps.unterfach_gueltig("Soziale Netzwerke", None)
    # Konten & Sicherheit kennt Netzwerke und Anbieter, „Sonstige“ genau einmal.
    ks = ps.UNTERFAECHER["Konten & Sicherheit"]
    assert "Instagram" in ks and "GitHub" in ks and ks.count("Sonstige") == 1


def test_bereich_fuer():
    assert ps.bereich_fuer("Tools & Dienste", "privat") == "business"
    assert ps.bereich_fuer("Soziale Netzwerke", "privat") == "privat"
    assert ps.bereich_fuer("Gesundheit", "business") == "privat"
    assert ps.bereich_fuer("Rechnungen", "business") == "business"
    assert ps.bereich_fuer("Veranstaltungen", "privat") == "business"
    assert ps.bereich_fuer("Konten & Sicherheit", "privat") == "privat"
    assert ps.bereich_fuer("Gibtsnicht", "privat") == "privat"


def test_jedes_fach_hat_eine_beschreibung():
    for br, faecher in ps.FAECHER.items():
        for f in faecher:
            assert ps.BESCHREIBUNG[(br, f)].strip()
    assert set(ps.BESCHREIBUNG) == {(br, f) for br, fs in ps.FAECHER.items() for f in fs}


def test_nur_business_faecher_gibt_es_nur_unter_business():
    for f in ps.NUR_BUSINESS:
        assert f in ps.FAECHER["business"] and f not in ps.FAECHER["privat"]


def test_fach_gueltig_lehnt_fach_aus_anderem_bereich_ab():
    assert post_struktur.fach_gueltig("business", "Familie & Freunde") is False
    assert post_struktur.fach_gueltig("privat", "Kunden & Anfragen") is False
    assert post_struktur.fach_gueltig("gibtsnicht", "Rechnungen") is False


@pytest.fixture
def db():
    os.environ["SALES_DB_SCHEMA"] = "sales_test"
    import server
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")
    with server.pool.connection() as conn:
        yield conn


def test_tabellen_existieren_im_testschema(db):
    tabellen = {r["table_name"] for r in db.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'sales_test'").fetchall()}
    for t in ("post_konten", "post_mails", "post_regeln", "post_abteilungen",
              "post_abteilung_faecher", "benutzer_abteilungen"):
        assert t in tabellen, t
    spalte = db.execute(
        "select is_nullable, column_default from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = 'benutzer' "
        "and column_name = 'leitung'"
    ).fetchone()
    assert spalte is not None
    assert spalte["is_nullable"] == "NO"
    assert spalte["column_default"] == "false"


def test_suchtext_enthaelt_keinen_text_sensibler_mails(db):
    konto = db.execute(
        "insert into sales_test.post_konten (besitzer, kennung, anbieter, "
        "adresse, quelle) values ('t', 'test-suchtext', 'gmx', 'a@b.de', 'env') "
        "on conflict (kennung) do update set besitzer = 't' returning id"
    ).fetchone()["id"]
    try:
        db.execute(
            "insert into sales_test.post_mails (konto_id, imap_uid, message_id, "
            "besitzer, betreff, text, sensibel) values "
            "(%s, 1, '<s@x>', 't', 'Hallo', 'geheimcode 4711', true), "
            "(%s, 2, '<o@x>', 't', 'Hallo', 'geheimcode 4711', false)",
            (konto, konto))
        treffer = [r["sensibel"] for r in db.execute(
            "select sensibel from sales_test.post_mails where konto_id = %s "
            "and suchtext @@ plainto_tsquery('german', 'geheimcode')",
            (konto,)).fetchall()]
        assert treffer == [False]
    finally:
        db.execute("delete from sales_test.post_mails where konto_id = %s", (konto,))
        db.execute("delete from sales_test.post_konten where id = %s", (konto,))
