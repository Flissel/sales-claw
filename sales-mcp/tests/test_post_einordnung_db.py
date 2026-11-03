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
