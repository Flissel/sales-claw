"""Struktur von sales_test.freigabe_eintraege / freigabe_auftraege / freigabe_schluessel.

WELCHE KAPUTTE FASSUNG FAENGT DAS?
-------------------------------------------------------------------------
Eine Tabelle mit falschem Spaltennamen (spaetere Module bauen darauf), eine
Kennung ohne Formpruefung, ein zweiter offener Eintrag fuer dieselbe Quelle
oder ein DELETE-Recht fuer sales_app.
"""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _spalten(tabelle):
    zeilen = server._q(
        "select column_name from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = %s "
        "order by ordinal_position", (tabelle,))
    return [z["column_name"] for z in zeilen]


def test_tabellen_und_spalten():
    assert _spalten("freigabe_eintraege") == [
        "id", "kennung", "herkunft", "art", "quelle_ref", "titel", "link",
        "details", "draft_id", "status", "rowboat_stand", "rowboat_seit",
        "rowboat_aufgeraeumt", "vermerk", "erstellt_am", "geschlossen_am",
        "geschlossen_von"]
    assert _spalten("freigabe_auftraege") == [
        "id", "eintrag_id", "art", "abholer", "nutzlast", "status",
        "angefordert_von", "fehler", "erstellt_am", "abgeholt_am", "erledigt_am"]
    assert _spalten("freigabe_schluessel") == [
        "herkunft", "hash", "aktiv", "angelegt_am"]


def _einfuegen(conn, kennung, quelle_ref="q1", herkunft="sales"):
    return conn.execute(
        "insert into freigabe_eintraege (kennung, herkunft, art, quelle_ref, titel) "
        "values (%s, %s, 'entwurf', %s, 'Probe') returning id",
        (kennung, herkunft, quelle_ref)).fetchone()


def _sqlstate(e):
    return str(getattr(e, "sqlstate", "") or e)


def test_kennung_form():
    with server.pool.connection() as conn:
        for schlecht in ("fg-ABC", "fg-abcdefgh01", "fg-ABCDEFGHIJ", "xx-abcdefghij",
                        "fg-abcdefghi", "fg-abcdefghijk"):
            ok = False
            try:
                _einfuegen(conn, schlecht)
            except Exception as e:
                ok = "23514" in _sqlstate(e)
            assert ok, schlecht
            conn.rollback()
        _einfuegen(conn, "fg-abcdefg234")
        _einfuegen(conn, "fg-abcdefghij", "q2")
        conn.rollback()


def test_ein_offener_je_quelle():
    with server.pool.connection() as conn:
        _einfuegen(conn, "fg-aaaaaaaaaa", "dup")
        ok = False
        try:
            _einfuegen(conn, "fg-bbbbbbbbbb", "dup")
        except Exception as e:
            ok = "23505" in _sqlstate(e)
        assert ok, "zweiter offener Eintrag haette am Unique-Index scheitern muessen"
        conn.rollback()
        # Nach dem Schliessen geht ein neuer; eine andere Herkunft ist ohnehin frei.
        erste = _einfuegen(conn, "fg-aaaaaaaaaa", "dup")
        conn.execute("update freigabe_eintraege set status = 'erledigt' where id = %s",
                     (erste["id"],))
        _einfuegen(conn, "fg-bbbbbbbbbb", "dup")
        _einfuegen(conn, "fg-cccccccccc", "dup", herkunft="marketing")
        conn.rollback()


def test_sales_app_darf_nicht_loeschen():
    for tabelle in ("freigabe_eintraege", "freigabe_auftraege", "freigabe_schluessel"):
        rechte = {z["privilege_type"].lower() for z in server._q(
            "select privilege_type from information_schema.role_table_grants "
            "where table_schema = 'sales_test' and table_name = %s "
            "and grantee = 'sales_app'", (tabelle,))}
        # sales_test: wie die anderen Tabellen mit truncate fuer die Fixtures,
        # aber ohne delete.
        assert rechte == {"select", "insert", "update", "truncate"}, (tabelle, rechte)


def test_indexe_draft_id_und_ein_auftrag_je_eintrag():
    """Final-Review I3/Zeile 14: draft_id-Index (Bote, jede Minute) und hoechstens ein
    offener/laufender Auftrag je Eintrag, auch ohne die Wache im Code."""
    idx = {z["indexname"]: z["indexdef"] for z in server._q(
        "select indexname, indexdef from pg_indexes where schemaname = 'sales_test' "
        "and tablename in ('freigabe_eintraege', 'freigabe_auftraege')")}
    assert "(draft_id)" in idx["freigabe_eintraege_draft_id"]
    auftrag = idx["freigabe_auftraege_offen_je_eintrag"]
    assert auftrag.startswith("CREATE UNIQUE INDEX") and "(eintrag_id)" in auftrag
    assert "'offen'" in auftrag and "'laeuft'" in auftrag
    with server.pool.connection() as conn:
        e = _einfuegen(conn, "fg-dddddddddd", "auftrag-dup")
        neu = ("insert into freigabe_auftraege (eintrag_id, art, abholer, nutzlast, "
               "angefordert_von, status) values (%s, 'selbstbild_label', 'selbstbild', "
               "'{}', 't', %s)")
        conn.execute(neu, (e["id"], "fehler"))
        conn.execute(neu, (e["id"], "erfolg"))  # abgeschlossene zaehlen nicht
        conn.execute(neu, (e["id"], "laeuft"))
        ok = False
        try:
            conn.execute(neu, (e["id"], "offen"))
        except Exception as fehler:
            ok = "23505" in _sqlstate(fehler)
        assert ok, "zweiter offener Auftrag haette am Unique-Index scheitern muessen"
        conn.rollback()


def test_tabelle_nimmt_herkunft_marketing_video():
    """db/freigabe-eingang.sql erweitert die beiden CHECKs (Video-Werkbank); die Standardnamen stimmen."""
    namen = {z["conname"]: z["def"] for z in server._q(
        "select conname, pg_get_constraintdef(oid) as def from pg_constraint "
        "where conrelid = 'sales_test.freigabe_eintraege'::regclass and contype = 'c'")}
    assert "marketing-video" in namen["freigabe_eintraege_herkunft_check"]
    assert "marketing_video" in namen["freigabe_eintraege_art_check"]
    with server.pool.connection() as conn:
        conn.execute(
            "insert into freigabe_eintraege (kennung, herkunft, art, quelle_ref, titel) "
            "values ('fg-vvvvvvvvvv', 'marketing-video', 'marketing_video', 'a1', 'Video: Probe') returning id")
        for herkunft, art in (("marketing-videos", "marketing_video"), ("marketing-video", "video")):
            ok = False
            try:
                conn.execute(
                    "insert into freigabe_eintraege (kennung, herkunft, art, quelle_ref, titel) "
                    "values ('fg-wwwwwwwwww', %s, %s, 'a2', 'x')", (herkunft, art))
            except Exception as e:
                ok = "23514" in _sqlstate(e)
            assert ok, (herkunft, art)
            conn.rollback()
        conn.rollback()
