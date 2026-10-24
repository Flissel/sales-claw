"""Tabelle kanal_status und neue Kanalwerte im drafts-CHECK (Spec
2026-10-24-kanaele-posten, Praezisierung 1) - Text von provision.sql und
die Tabelle in sales_test."""
import os
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import psycopg  # noqa: E402
import pytest  # noqa: E402

import kanaele  # noqa: E402
import server  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
PROVISION = (WURZEL / "db" / "provision.sql").read_text(encoding="utf-8")
LADEN = (WURZEL / "db" / "laden-anlegen.sql").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def leer():
    server._q("truncate sales_test.kanal_status, sales_test.drafts, "
              "sales_test.activities, sales_test.leads cascade")
    yield


def test_provision_text():
    assert "%I.kanal_status" in PROVISION
    assert "'telegram_kanal'" in PROVISION
    assert "grant select, insert, update on sales.kanal_status to sales_app" in PROVISION
    assert "grant select, insert, update on %I.kanal_status to %I" in PROVISION
    assert "delete on sales.kanal_status" not in PROVISION
    assert ('create table if not exists :"schema".kanal_status '
            '(like sales.kanal_status including all);') in LADEN
    assert 'grant select, insert, update on :"schema".kanal_status to :"rolle";' in LADEN


def test_tabelle_in_sales_test():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name='kanal_status'")}
    assert spalten == {"kanal", "verbunden", "geprueft_am", "letzter_fehler"}


def test_channel_check_nimmt_neue_kanaele():
    for kanal in kanaele.KANAELE:
        server._q("insert into drafts (channel, recipient, body) "
                  "values (%s, 'eigenes-profil', 'x')", (kanal,))
    with pytest.raises(psycopg.errors.CheckViolation):
        server._q("insert into drafts (channel, recipient, body) "
                  "values ('instagram', 'eigenes-profil', 'x')")


def test_status_schreiben_und_lesen():
    kanaele.status_schreiben(server._q, "bluesky", True, None)
    kanaele.status_schreiben(server._q, "bluesky", True, None)
    assert server._q("select count(*) as n from kanal_status")[0]["n"] == 1
    assert kanaele.verbunden(server._q, "bluesky") is True
    kanaele.status_schreiben(server._q, "bluesky", False, "BLUESKY_HANDLE fehlt")
    status = kanaele.status_lesen(server._q)
    assert status["bluesky"]["verbunden"] is False
    assert status["bluesky"]["letzter_fehler"] == "BLUESKY_HANDLE fehlt"
    assert status["bluesky"]["geprueft_am"] is not None
    assert kanaele.verbunden(server._q, "mastodon") is False


def test_fehler_bleibt_ausser_loeschen_und_wird_gekappt():
    kanaele.status_schreiben(server._q, "devto", False, "x" * 500)
    assert len(kanaele.status_lesen(server._q)["devto"]["letzter_fehler"]) == 300
    kanaele.status_schreiben(server._q, "devto", True, None)
    assert kanaele.status_lesen(server._q)["devto"]["letzter_fehler"] == "x" * 300
    kanaele.status_schreiben(server._q, "devto", True, None, fehler_loeschen=True)
    assert kanaele.status_lesen(server._q)["devto"]["letzter_fehler"] is None


def test_status_lesen_ohne_tabelle():
    def q(sql, params=()):
        raise psycopg.errors.UndefinedTable("relation kanal_status does not exist")
    assert kanaele.status_lesen(q) == {}
    assert kanaele.verbunden(q, "bluesky") is False


def test_andere_db_fehler_gehen_weiter():
    def q(sql, params=()):
        raise psycopg.OperationalError("weg")
    with pytest.raises(psycopg.OperationalError):
        kanaele.status_lesen(q)
