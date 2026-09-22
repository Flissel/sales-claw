"""Struktur von sales.admin_auftraege / sales_test.admin_auftraege.

WELCHE KAPUTTE FASSUNG FAENGT DAS?
-------------------------------------------------------------------------
Eine kuenftige Aenderung, die admin_auftraege versehentlich in die
Per-Laden-Schleife von db/provision.sql zieht (der K3-Fehler in die
GEGENTEILIGE Richtung): dann existierte sie auch in sales_ivan, und Ivans
sales_app_ivan koennte sie lesen/beschreiben. Dieser Test prueft deshalb
NICHT nur "existiert sie", sondern auch die Rechte von sales_app selbst.
"""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


def test_tabelle_existiert_mit_den_erwarteten_spalten():
    zeilen = server._q(
        "select column_name from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = 'admin_auftraege' "
        "order by ordinal_position")
    spalten = [z["column_name"] for z in zeilen]
    assert spalten == ["id", "art", "name", "angefordert_von", "status",
                        "ergebnis", "fehler", "erstellt_am", "erledigt_am",
                        "email"]


def test_art_erlaubt_nur_die_beiden_bekannten_werte():
    with server.pool.connection() as conn:
        try:
            conn.execute(
                "insert into admin_auftraege (art, name, angefordert_von) "
                "values ('etwas_anderes', 'probe', 'test')")
            assert False, "haette am CHECK scheitern muessen"
        except Exception as e:
            assert "23514" in str(getattr(e, "sqlstate", "") or e)
        conn.rollback()
        # Positivprobe: die zweite Auftragsart ist jetzt erlaubt.
        conn.execute(
            "insert into admin_auftraege (art, email, angefordert_von) "
            "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
        conn.rollback()


def test_name_erzwingt_das_schema_muster():
    with server.pool.connection() as conn:
        for schlechter_name in ("Ivan", "ivan-mit-bindestrich", "1ivan", ""):
            hat_sqlstate = False
            try:
                conn.execute(
                    "insert into admin_auftraege (art, name, angefordert_von) "
                    "values ('laden_anlegen', %s, 'test')", (schlechter_name,))
            except Exception as e:
                hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
            assert hat_sqlstate, f"'{schlechter_name}' haette am CHECK scheitern muessen"
            conn.rollback()


def test_sales_app_hat_kein_update_und_kein_delete_recht():
    zeilen = server._q(
        "select privilege_type from information_schema.role_table_grants "
        "where table_schema = 'sales_test' and table_name = 'admin_auftraege' "
        "and grantee = 'sales_app' order by privilege_type")
    rechte = {z["privilege_type"].lower() for z in zeilen}
    # sales_test traegt den Blankett-Grant (delete/insert/select/truncate/
    # update) — DAS ist hier gewollt (die Testsuite muss aufraeumen
    # koennen). Auf `sales` (Produktion) gilt das NICHT, siehe Step 1: dort
    # bekommt sales_app nur select+insert. Dieser Test haelt fest, WARUM
    # sales_test bewusst weiter reicht, statt es stillschweigend
    # hinzunehmen.
    assert rechte == {"delete", "insert", "select", "truncate", "update"}


def test_admin_auftraege_existiert_in_keinem_anderen_schema():
    """Der eigentliche Regressionsschutz: admin_auftraege darf NIRGENDS
    ausser sales/sales_test stehen — sonst koennte ein weiterer Laden
    (sales_ivan, ein kuenftiger sales_<name>) sie lesen oder beschreiben."""
    zeilen = server._q(
        "select table_schema from information_schema.tables "
        "where table_name = 'admin_auftraege' order by table_schema")
    schemata = {z["table_schema"] for z in zeilen}
    assert schemata == {"sales", "sales_test"}, schemata


def test_name_darf_bei_tailscale_einladen_leer_sein():
    """Die alte Fassung erzwang 'name not null' fuer JEDE Zeile — eine
    Einladung ohne Ladennamen waere daran gescheitert, obwohl sie gar
    keinen braucht."""
    with server.pool.connection() as conn:
        conn.execute(
            "insert into admin_auftraege (art, email, angefordert_von) "
            "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
        conn.rollback()


def test_name_darf_bei_laden_anlegen_nicht_leer_sein():
    """Deckt die NULL-Luecke ab: 'art <> x or name ~ muster' liesse ein
    NULL durch, weil 'NULL ~ muster' weder wahr noch falsch ist. Ohne das
    ausdrueckliche 'is not null' im CHECK waere dieser Test gruen, obwohl
    admin-auftrag-ausfuehren.sh dann mit einem leeren Ladennamen weiterliefe."""
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, angefordert_von) "
                "values ('laden_anlegen', 'test')")
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, "name=NULL haette am CHECK scheitern muessen"
        conn.rollback()


@pytest.mark.parametrize("schlechte_email", [
    "keineadresse", "kein-at-zeichen.de", "ohne-punkt@domain",
    "mit leerzeichen@domain.de", ""])
def test_email_erzwingt_ein_vernuenftiges_muster(schlechte_email):
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, email, angefordert_von) "
                "values ('tailscale_einladen', %s, 'test')", (schlechte_email,))
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, f"'{schlechte_email}' haette am CHECK scheitern muessen"
        conn.rollback()


def test_email_darf_bei_tailscale_einladen_nicht_leer_sein():
    """Dieselbe NULL-Luecke wie bei name oben, gespiegelt fuer email."""
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, angefordert_von) "
                "values ('tailscale_einladen', 'test')")
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, "email=NULL haette am CHECK scheitern muessen"
        conn.rollback()
