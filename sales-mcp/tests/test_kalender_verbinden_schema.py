"""Datenmodell fuer 'Kalender verbinden' (Besitzer, Bereich, Konten, Termine).
Struktur-Tests lesen nur die SQL-Datei; der DB-Teil laeuft nur gegen sales_test
(db/kalender-verbinden.sql muss dort eingespielt sein)."""
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

SQL = Path(__file__).resolve().parents[2] / "db" / "kalender-verbinden.sql"


def test_bestehende_quellen_werden_privat_und_gehoeren_dem_laden():
    sql = SQL.read_text(encoding="utf-8")
    assert "set besitzer = :'besitzer'" in sql and "bereich = 'privat'" in sql
    assert "where besitzer is null" in sql          # idempotent: zweiter Lauf aendert nichts


def test_termine_tabelle_hat_loeschrecht_und_konten_nicht():
    sql = SQL.read_text(encoding="utf-8")
    assert re.search(r"select, insert, update, delete[^;]*kalender_termine", sql)
    assert not re.search(r"delete[^;]*kalender_konten", sql)


def test_name_ist_nur_je_besitzer_eindeutig():
    sql = SQL.read_text(encoding="utf-8")
    assert "drop index if exists" in sql and "(besitzer, anzeigename)" in sql


def test_fehlender_besitzer_bricht_nur_bei_altzeilen_ab():
    sql = SQL.read_text(encoding="utf-8")
    assert ":{?besitzer}" in sql and "raise exception" in sql


def _spalten(tabelle):
    return {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name=%s", (tabelle,))}


def test_db_spalten_und_tabellen_da():
    assert server.SCHEMA == "sales_test"
    assert {"besitzer", "bereich", "konto_id", "google_id"} <= _spalten("kalender_quellen")
    assert {"id", "besitzer", "anbieter", "adresse", "zugang_versiegelt",
            "kalender_liste", "aktiv", "created_at"} <= _spalten("kalender_konten")
    assert {"quelle_id", "uid", "beginn", "ende", "ganztaegig", "frei", "titel",
            "ort", "abgeglichen_am"} <= _spalten("kalender_termine")


def test_db_bereich_geheim_scheitert_am_check():
    assert server.SCHEMA == "sales_test"
    name = f"kv-test-{uuid.uuid4()}"
    with pytest.raises(psycopg.errors.CheckViolation):
        server._q("insert into sales_test.kalender_quellen "
                  "(anzeigename, art, besitzer, bereich) values (%s,'ics','kv-test','geheim')",
                  (name,))
    assert server._q("select 1 from sales_test.kalender_quellen where anzeigename=%s", (name,)) == []
