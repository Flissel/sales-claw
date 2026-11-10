"""post_regeln gegen echte Datenbank (nur sales_test): Reihenfolge, Treffer, kaputte Zeilen."""
import os
import re
import sys
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_einordnung as pe  # noqa: E402
import server  # noqa: E402


@pytest.fixture(autouse=True)
def saubere_tabelle():
    assert server.SCHEMA == "sales_test"
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_regeln")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_regeln")


def _regel(muster, fach, zeit, bereich="privat"):
    # Feste Zeitpunkte statt now(): die Reihenfolge darf nicht an Mikrosekunden
    # zwischen zwei Transaktionen haengen.
    server._q("insert into post_regeln (muster, feld, bereich, fach, sensibel, "
              "angelegt_am) values (%s, 'von', %s, %s, false, %s)",
              (muster, bereich, fach, zeit))


def test_regeln_aus_tabelle_neueste_zuerst_kaputte_uebersprungen():
    # Ruling R11: die neueste gueltige Regel gewinnt; neuere kaputte Zeilen
    # (ungueltiges Muster, unbekanntes Fach) werden uebersprungen.
    _regel(r"@shop\.example", "Werbung", "2026-11-01 10:00+00")
    _regel(r"@shop\.example", "Käufe & Bestellungen", "2026-11-02 10:00+00")
    _regel(r"@shop\.example", "Nirgends", "2026-11-03 10:00+00")
    _regel("(", "Werbung", "2026-11-03 11:00+00")
    mail = {"id": "x", "von": "Info@SHOP.example", "betreff": "b", "datum": "", "text": ""}
    e = pe.nach_regel(mail)
    assert (e.bereich, e.fach, e.quelle) == ("privat", "Käufe & Bestellungen", "regel")
    assert pe.nach_regel({**mail, "von": "x@y.org"}) is None


def test_menschliche_korrektur_schlaegt_aeltere_regel():
    _regel(r"news@firma\.de", "Abos & Newsletter", "2026-10-01 10:00+00")
    _regel(r"news@firma\.de", "Rechnungen", "2026-11-03 09:00+00",
           bereich="business")
    e = pe.nach_regel({"id": "x", "von": "Firma <news@firma.de>", "betreff": "b",
                       "datum": "", "text": ""})
    assert (e.bereich, e.fach) == ("business", "Rechnungen")


def test_regel_ohne_zeitpunkt_kommt_zuletzt():
    # `desc` allein setzte NULL nach vorn - eine Zeile ohne angelegt_am haette
    # jede datierte (also jede echte menschliche) Regel verdeckt.
    server._q("insert into post_regeln (muster, feld, bereich, fach, sensibel, "
              "angelegt_am) values (%s, 'von', 'privat', 'Werbung', false, null)",
              (r"@laden\.example",))
    _regel(r"@laden\.example", "Käufe & Bestellungen", "2026-11-01 10:00+00")
    e = pe.nach_regel({"id": "x", "von": "a@laden.example", "betreff": "b",
                       "datum": "", "text": ""})
    assert e.fach == "Käufe & Bestellungen"


def test_regel_mit_besitzer_nur_fuer_dessen_post():
    server._q("insert into post_regeln (muster, feld, bereich, fach, sensibel, "
              "besitzer) values (%s, 'von', 'privat', 'Werbung', false, 'anna')",
              (r"@laden\.example",))
    mail = {"id": "x", "von": "a@laden.example", "betreff": "b", "datum": "", "text": ""}
    assert pe.nach_regel({**mail, "besitzer": "anna"}).fach == "Werbung"
    assert pe.nach_regel({**mail, "besitzer": "ben"}) is None
    assert pe.nach_regel(mail) is None           # ohne Besitzer: fail closed


SQL_DATEI = Path(__file__).resolve().parents[2] / "db" / "post-sammelstelle.sql"


def _umbenennung_einspielen():
    """Fuehrt die Daten-Statements zu 'Unklar'/'Zum Nachsehen' aus der Migrationsdatei
    aus (Umbenennung in post_mails, Loeschen sinnloser Regeln in post_regeln). Die
    DDL-Teile spielt das Testverfahren per psql als supabase_admin ein (sales_app darf
    kein DDL); die Daten-Aenderungen darf sie."""
    assert server.SCHEMA == "sales_test"
    text = SQL_DATEI.read_text(encoding="utf-8")
    anweisungen = (re.findall(r"update :\"schema\"\.post_\w+ set fach = 'Zum Nachsehen'"
                              r"[^;]*;", text)
                   + re.findall(r"delete from :\"schema\"\.post_regeln where fach in "
                                r"\('Unklar', 'Zum Nachsehen'\);", text))
    assert len(anweisungen) == 2, "Umbenennung in post_mails und Loeschen in post_regeln erwartet"
    with server.pool.connection() as conn:
        for a in anweisungen:
            conn.execute(a.replace(':"schema"', "sales_test"))


def test_migration_zweimal_einspielbar_und_unklar_umbenannt():
    with server.pool.connection() as conn:
        k = conn.execute("insert into sales_test.post_konten (besitzer, kennung, "
                         "anbieter, adresse, quelle) values ('t2', 't2-mig', 'gmx', "
                         "'a@b.de', 'ui') returning id").fetchone()["id"]
        conn.execute("insert into sales_test.post_mails (konto_id, imap_uid, message_id, "
                     "besitzer, bereich, fach) values (%s, 1, '<t2@x>', 't2', "
                     "'business', 'Unklar')", (k,))
        conn.execute("insert into sales_test.post_regeln (muster, feld, bereich, fach) "
                     "values ('t2', 'von', 'business', 'Unklar'), "
                     "('t2', 'von', 'business', 'Zum Nachsehen'), "
                     "('t2', 'von', 'privat', 'Rechnungen')")
    try:
        _umbenennung_einspielen()
        _umbenennung_einspielen()
        m = server._q("select bereich, fach from post_mails where konto_id = %s", (k,))[0]
        assert (m["bereich"], m["fach"]) == ("privat", "Zum Nachsehen")
        # I2a: Regeln nach Unklar/Zum Nachsehen sind weg, andere bleiben.
        r = server._q("select fach from post_regeln where muster = 't2'")
        assert [z["fach"] for z in r] == ["Rechnungen"]
        spalten = {z["column_name"] for z in server._q(
            "select column_name from information_schema.columns "
            "where table_schema = 'sales_test' and table_name in "
            "('post_konten','post_mails','post_regeln')")}
        assert {"standard_bereich", "unterfach", "vorschlaege", "modellaufrufe",
                "einordnung_version", "vorschau", "vorschau_am"} <= spalten
        # Neue Quellen sind erlaubt, alte bleiben es.
        for q in ("katalog", "pruefer", "regel"):
            server._q("update post_mails set einordnung_quelle = %s where konto_id = %s",
                      (q, k))
        fach = {z["fach"] for z in server._q(
            "select fach from post_abteilung_faecher where abteilung = 'Marketing'")}
        assert {"Veranstaltungen", "Soziale Netzwerke"} <= fach
    finally:
        server._q("delete from post_mails where konto_id = %s", (k,))
        server._q("delete from post_konten where id = %s", (k,))
        server._q("delete from post_regeln where muster = 't2'")
