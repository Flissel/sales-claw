"""Verträge über die Monitoring-Seite (WhatsApp) — Schritt 6 des UI-Plans
(02.09.2026): drei Zustandskarten und die Kette vom Handy bis in die
Datenbank, jede Station mit ihrem letzten Beweis. Wird eine Station gelb,
steht der Grund dabei, nicht nur ein Punkt.
"""
import pytest
from starlette.testclient import TestClient

import server
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


@pytest.fixture(autouse=True)
def openwa_bereit(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(ui, "_openwa_lesen", lambda pfad: (
        [{"id": "s1", "status": "ready", "phone": "4917000",
          "pushName": "Test", "connectedAt": "2026-09-02T06:27:00Z",
          "lastActive": None, "engineLoaded": True}], None))


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _kundenantwort(lead, alter="0 hours"):
    server._q("insert into activities (lead_id, type, payload, actor, "
              "created_at) values (%s, 'kundenantwort', %s::jsonb, 'agent', "
              "now() - %s::interval) returning id",
              (lead, '{"text": "Hallo"}', alter))


def test_drei_karten_und_fuenf_stationen():
    _kundenantwort(_lead())
    seite = _get("/whatsapp").text
    for karte in ("Sitzung", "Automatik", "Kundennachrichten"):
        assert f'<div class="railtitel">{karte}</div>' in seite, karte
    assert 'class="kette"' in seite
    for station in ("Handy", "OpenWA", "Webhook", "Posteingang", "Datenbank"):
        assert f"<b>{station}</b>" in seite, station
    assert seite.count('class="punkt gut"') == 5
    assert "noch kein Lauf" in seite                # kein Cron-Lauf gebucht
    # Die bestehenden Saetze bleiben — sie sind die Beweise.
    assert "Die Kette bis in die Datenbank funktioniert" in seite


def test_automatik_karte_nennt_den_letzten_cron_lauf():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'transkription', %s::jsonb, 'cron') returning id",
              (lead, '{"leer": true}'))
    seite = _get("/whatsapp").text
    assert "letzter Lauf" in seite
    assert "noch kein Lauf" not in seite


def test_stationen_werden_gelb_wenn_lange_nichts_kam():
    _kundenantwort(_lead(), alter="3 days")
    seite = _get("/whatsapp").text
    assert 'class="punkt warnung"' in seite
    kette = seite[seite.index('class="kette"'):]
    assert "seit" in kette and "h" in kette
    assert "Das ist lange" in seite               # bestehende Warnung bleibt


def test_ohne_jede_nachricht_ist_die_kette_unbewiesen():
    seite = _get("/whatsapp").text
    assert "NIE eine" in seite
    kette = seite[seite.index('class="kette"'):]
    assert 'class="punkt warnung"' in kette
    assert "unbewiesen" in kette


def test_openwa_ausfall_faerbt_die_station_rot(monkeypatch):
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda p: (None, "OpenWA ist nicht erreichbar"))
    seite = _get("/whatsapp").text
    kette = seite[seite.index('class="kette"'):]
    assert 'class="punkt gefahr"' in kette
    assert "nicht erreichbar" in seite
