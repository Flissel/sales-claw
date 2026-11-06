"""Datenmodell fuer das Aufraeumen der Post-Sammelstelle (Spec 2026-11-06).
Nur gegen sales_test."""
import os
import re
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

SQL = Path(__file__).resolve().parents[2] / "db" / "post-sammelstelle.sql"

ERWARTET = {
    "post_mails": {"aufmerksamkeit", "werbung_sicher", "ziel", "ziel_manuell", "ordner",
                   "ordner_uid", "ordner_stand", "ordner_am", "urspruengliche_adresse",
                   "geloescht_am"},
    "post_konten": {"ordnen_aus"},
    "post_regeln": {"art"},
    "post_loeschfreigaben": {"id", "besitzer", "jahr", "freigegeben_am", "ausgenommen"},
}


@pytest.fixture(autouse=True)
def wache():
    assert server.SCHEMA == "sales_test"


def _spalten(tabelle):
    return {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name=%s", (tabelle,))}


def _mail(konto_id, **felder):
    spalten = {"konto_id": konto_id, "imap_uid": 1, "message_id": f"<{uuid.uuid4()}>",
               "besitzer": "test-aufraeumen", **felder}
    namen = ", ".join(spalten)
    platz = ", ".join(["%s"] * len(spalten))
    server._q(f"insert into sales_test.post_mails ({namen}) values ({platz})",
              tuple(spalten.values()))


@pytest.fixture
def konto():
    k = server._q("insert into sales_test.post_konten (anbieter, adresse, quelle) "
                  "values ('gmx','aufraeumen@example.test','ui') returning id")[0]["id"]
    yield k
    server._q("delete from sales_test.post_mails where konto_id=%s", (k,))
    server._q("delete from sales_test.post_konten where id=%s", (k,))


def test_spalten_und_tabellen_da(konto):
    for tabelle, spalten in ERWARTET.items():
        assert spalten <= _spalten(tabelle), (tabelle, spalten - _spalten(tabelle))

    _mail(konto, status="geloescht")
    with pytest.raises(psycopg.errors.CheckViolation):
        _mail(konto, imap_uid=2, ziel="weg")

    server._q("insert into sales_test.post_loeschfreigaben (besitzer, jahr) "
              "values ('test-aufraeumen', 2099)")
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            server._q("insert into sales_test.post_loeschfreigaben (besitzer, jahr) "
                      "values ('test-aufraeumen', 2099)")
    finally:
        server._q("delete from sales_test.post_loeschfreigaben where besitzer='test-aufraeumen'")


def test_sql_ist_idempotent():
    # Die App-Rolle besitzt die Tabellen nicht (ALTER scheitert mit "must be
    # owner"), darum laesst sich der Abschnitt nicht ueber server._q zweimal
    # ausfuehren. Der echte Doppellauf ist die psql-Probe auf der VM (siehe
    # Bericht); hier wird nur gesichert, dass jede Anweisung des Abschnitts
    # einen Wiederholungsschutz traegt.
    text = SQL.read_text(encoding="utf-8")
    ab = text[text.index("-- Aufräumen (Spec 2026-11-06)"):]
    for anw in re.findall(r"(?:alter table|create table|create index)[^;]*;", ab, re.S):
        if anw.lstrip().startswith("alter table"):
            for teil in re.findall(r"add column[^,;]*", anw):
                assert teil.startswith("add column if not exists"), teil
        else:
            assert "if not exists" in anw.split("(")[0], anw
    # Der Status-Check wird nur ersetzt, wenn er 'geloescht' noch nicht kennt.
    assert "like '%geloescht%'" in ab
