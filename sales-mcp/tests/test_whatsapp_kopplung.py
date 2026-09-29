"""WhatsApp verbinden als Selbstbedienung (29.09.2026).

Die Oberflaeche darf keinen OpenWA-Schluessel haben, der senden kann — der
QR-Code verlangt aber genau so einen. Deshalb legt die Seite nur eine
Anfrage in `whatsapp_kopplung`; der Wirt auf dem Host (deploy/whatsapp-
koppeln.sh) holt den QR-Code und schreibt ihn in dieselbe Zeile, die Seite
zeigt ihn an.
"""
import os

import psycopg
import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
# 1x1-PNG, gueltiges Base64.
QR = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
      "DUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.whatsapp_kopplung")
    # Ohne Nur-Lese-Schluessel: wie bei Ivan vor der Kopplung.
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda pfad: (None, "OPENWA_VIEWER_KEY fehlt"))
    yield


def _get():
    return CLIENT.get("/whatsapp", headers={"host": HOST_OK})


def _post(daten):
    return CLIENT.post("/whatsapp/verbinden", data=daten,
                       headers={"host": HOST_OK}, follow_redirects=False)


def _zeile(status, qr=None, fehler=None):
    server._q("insert into whatsapp_kopplung (status, qr, fehler) "
              "values (%s, %s, %s) returning id", (status, qr, fehler))


# --- Tabelle ----------------------------------------------------------------

def test_tabelle_hat_die_erwarteten_spalten():
    spalten = [z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = 'whatsapp_kopplung' "
        "order by ordinal_position")]
    assert spalten == ["id", "status", "qr", "fehler", "erstellt_am",
                       "aktualisiert_am"]


def test_status_kennt_nur_die_fuenf_werte():
    with pytest.raises(psycopg.errors.CheckViolation):
        _zeile("irgendwas")


def test_hoechstens_eine_offene_anfrage():
    _zeile("angefordert")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _zeile("qr", QR)
    # Abgeschlossene zaehlen nicht mit.
    server._q("update whatsapp_kopplung set status = 'abgelaufen' returning id")
    _zeile("angefordert")


def test_jeder_laden_mit_rolle_darf_lesen_und_anfragen():
    """provision.sql vergibt die Rechte auch an bestehende Laeden (Ivan),
    nicht nur laden-anlegen.sql an neue."""
    rechte = {z["privilege_type"] for z in server._q(
        "select privilege_type from information_schema.role_table_grants "
        "where table_schema = 'sales' and table_name = 'whatsapp_kopplung' "
        "and grantee = 'sales_app'")}
    assert {"SELECT", "INSERT"} <= rechte
    assert "DELETE" not in rechte


# --- Seite ------------------------------------------------------------------

def test_ohne_kopplung_steht_der_knopf_da():
    seite = _get().text
    assert 'action="/whatsapp/verbinden"' in seite
    assert "WhatsApp verbinden" in seite


def test_knopf_legt_genau_eine_anfrage_an():
    assert _post({"csrf": ui.CSRF_TOKEN}).status_code == 303
    assert _post({"csrf": ui.CSRF_TOKEN}).status_code == 303
    zeilen = server._q("select status from whatsapp_kopplung")
    assert [z["status"] for z in zeilen] == ["angefordert"]


def test_ohne_csrf_passiert_nichts():
    assert _post({}).status_code in (400, 403)
    assert server._q("select count(*) n from whatsapp_kopplung")[0]["n"] == 0


def test_angefordert_wartet_und_laedt_neu():
    _zeile("angefordert")
    seite = _get().text
    assert 'http-equiv="refresh"' in seite
    assert 'action="/whatsapp/verbinden"' not in seite


def test_qr_wird_angezeigt():
    _zeile("qr", QR)
    seite = _get().text
    assert f'src="{QR}"' in seite
    assert "Verknüpfte Geräte" in seite
    assert 'http-equiv="refresh"' in seite


def test_ein_kaputter_qr_wird_nicht_eingebettet():
    _zeile("qr", 'data:image/png;base64,AAAA" onerror="alert(1)')
    seite = _get().text
    assert "onerror" not in seite
    assert 'class="qr"' not in seite


def test_abgelaufen_bietet_den_knopf_wieder_an():
    _zeile("abgelaufen", fehler="Kein Scan innerhalb von 3 Minuten.")
    seite = _get().text
    assert "Kein Scan innerhalb von 3 Minuten." in seite
    assert 'action="/whatsapp/verbinden"' in seite


def test_verbunden_zeigt_keinen_knopf(monkeypatch):
    monkeypatch.setattr(ui, "_openwa_lesen", lambda pfad: (
        [{"id": ui.OPENWA_SESSION_ID or "x", "status": "ready"}], None))
    seite = _get().text
    assert 'action="/whatsapp/verbinden"' not in seite


def test_ohne_tabelle_bleibt_die_seite_heil(monkeypatch):
    """Code ausgeliefert, provision.sql noch nicht: kein Absturz der Seite."""
    echt = server._q

    def ohne_tabelle(sql, params=()):
        if "whatsapp_kopplung" in sql:
            raise psycopg.errors.UndefinedTable("fehlt")
        return echt(sql, params)
    monkeypatch.setattr(server, "_q", ohne_tabelle)
    antwort = _get()
    assert antwort.status_code == 200
    assert 'action="/whatsapp/verbinden"' not in antwort.text
