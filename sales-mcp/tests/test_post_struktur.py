"""Tests der Post-Sammelstelle, Stufe 1: feste Faecher und Tabellen.

Die DB-Tests laufen nur gegen `sales_test` (Schema vorher mit
db/post-sammelstelle.sql eingespielt).
"""
import os

import pytest

import post_struktur

SPEC_PRIVAT = {
    "Familie & Freunde", "Rechnungen", "Käufe & Bestellungen",
    "Abos & Newsletter", "Soziale Netzwerke", "Konten & Sicherheit",
    "Behörden & Versicherung", "Werbung", "Unklar",
}
SPEC_BUSINESS = {
    "Kunden & Anfragen", "Partner & Netzwerk", "Rechnungen",
    "Tools & Dienste", "Bewerbungen & Jobs", "Newsletter & Branche",
    "Werbung", "Unklar",
}


def test_faecher_sind_genau_die_spec_liste():
    assert post_struktur.BEREICHE == ("privat", "business")
    assert set(post_struktur.FAECHER) == {"privat", "business"}
    assert set(post_struktur.FAECHER["privat"]) == SPEC_PRIVAT
    assert set(post_struktur.FAECHER["business"]) == SPEC_BUSINESS
    assert len(post_struktur.FAECHER["privat"]) == len(SPEC_PRIVAT)
    assert len(post_struktur.FAECHER["business"]) == len(SPEC_BUSINESS)


def test_unklar_in_beiden_bereichen():
    assert post_struktur.UNKLAR == "Unklar"
    for bereich in post_struktur.BEREICHE:
        assert post_struktur.fach_gueltig(bereich, post_struktur.UNKLAR)


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
        "select 1 from information_schema.columns where table_schema = "
        "'sales_test' and table_name = 'benutzer' and column_name = 'leitung'"
    ).fetchone()
    assert spalte is not None


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
