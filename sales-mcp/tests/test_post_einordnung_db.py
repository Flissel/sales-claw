"""post_regeln gegen echte Datenbank (nur sales_test): Reihenfolge, Treffer, kaputte Zeilen."""
import os
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


def test_regeln_aus_tabelle_aelteste_zuerst_kaputte_uebersprungen():
    for muster, fach in (("(", "Werbung"), (r"@shop\.example", "Nirgends"),
                         (r"@shop\.example", "Käufe & Bestellungen"),
                         (r"@shop\.example", "Werbung")):
        server._q("insert into post_regeln (muster, feld, bereich, fach, sensibel) "
                  "values (%s, 'von', 'privat', %s, false)", (muster, fach))
    mail = {"id": "x", "von": "Info@SHOP.example", "betreff": "b", "datum": "", "text": ""}
    e = pe.nach_regel(mail)
    assert (e.bereich, e.fach, e.quelle) == ("privat", "Käufe & Bestellungen", "regel")
    assert pe.nach_regel({**mail, "von": "x@y.org"}) is None
