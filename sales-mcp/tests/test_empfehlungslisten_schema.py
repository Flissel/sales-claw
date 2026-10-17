"""Schema der Empfehlungslisten (Spec C4 §3.1) — Text von provision.sql und
die Tabelle in sales_test."""
import os
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
PROVISION = (WURZEL / "db" / "provision.sql").read_text(encoding="utf-8")
LADEN = (WURZEL / "db" / "laden-anlegen.sql").read_text(encoding="utf-8")


def test_provision_legt_tabelle_im_loop_an_und_gibt_rechte():
    assert "%I.empfehlungslisten" in PROVISION
    assert "check (art in ('pole_position', 'mitarbeitervorschlaege'))" in PROVISION
    assert ("grant select, insert, update on %I.empfehlungslisten to %I" in PROVISION)
    assert "grant select, insert, update on sales.empfehlungslisten to sales_app" in PROVISION
    assert "delete on sales.empfehlungslisten" not in PROVISION


def test_laden_anlegen_kennt_die_tabelle():
    assert 'create table if not exists :"schema".empfehlungslisten (like sales.empfehlungslisten including all);' in LADEN
    assert 'grant select, insert, update on :"schema".empfehlungslisten to :"rolle";' in LADEN


def test_tabelle_in_sales_test():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name='empfehlungslisten'")}
    assert spalten == {"id", "art", "empfohlen_von_lead", "empfohlen_von_name", "datum",
                       "berater_name", "struktur", "bereiche", "einwilligung",
                       "einwilligung_am", "erstellt_am"}
