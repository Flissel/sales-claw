"""F1-Verdrahtung in server.py: die Verbotsliste greift VOR der Erstansprache
und wird bei Widerruf/Loeschantrag beschrieben.

Ohne Datenbank fuer den Ablehnungspfad: die Sperrpruefung liegt vor jedem
Insert, also beweist ein ersetztes `sperrliste.gesperrt` allein, dass
kontakt_anlegen nicht anlegt. Der Schreibpfad wird ueber ein ersetztes
`sperrliste.sperren` und ein ersetztes `_q` gemessen.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")
import server  # noqa: E402
import sperrliste  # noqa: E402


def test_kontakt_anlegen_lehnt_gesperrte_ab(monkeypatch):
    monkeypatch.setattr(sperrliste, "gesperrt", lambda q, email="", phone="": "marketing:unsubscribe: abgemeldet 2026-09-01")
    aufrufe = []
    monkeypatch.setattr(server, "_q", lambda sql, params=(): aufrufe.append(sql) or [])
    out = json.loads(server.kontakt_anlegen("Max", email="max@x.de"))
    assert "Verbotsliste" in out["fehler"]
    assert "marketing:unsubscribe" in out["fehler"]
    assert not any("insert into leads" in s for s in aufrufe)


def test_kontakt_anlegen_ohne_sperre_legt_an(monkeypatch):
    monkeypatch.setattr(sperrliste, "gesperrt", lambda q, email="", phone="": None)
    monkeypatch.setattr(server, "_q", lambda sql, params=(): [{"id": "lead-1"}])
    out = json.loads(server.kontakt_anlegen("Max", email="max@x.de"))
    assert out == {"lead_id": "lead-1", "angelegt": True}


def test_entwurf_erstellen_lehnt_gesperrte_ab(monkeypatch):
    monkeypatch.setattr(sperrliste, "gesperrt", lambda q, email="", phone="": "sales:loeschantrag: Loeschantrag via mail")
    monkeypatch.setattr(server, "_q", lambda sql, params=(): [
        {"name": "Max", "phone": "0171 1234567", "email": "max@x.de", "enrichment": {}}])
    out = json.loads(server.entwurf_erstellen("lead-1", "whatsapp", "Hallo"))
    assert "Verbotsliste" in out["fehler"]


def test_loeschantrag_sperrt_beide_seiten(monkeypatch):
    gesperrt = []
    monkeypatch.setattr(sperrliste, "sperren",
                        lambda q, email="", phone="", *, quelle, grund="": gesperrt.append((email, phone, quelle, grund)) or 1)
    monkeypatch.setattr(server, "_q", lambda sql, params=(): [
        {"enrichment": {}, "name": "Max", "email": "max@x.de", "phone": "", "id": "lead-1"}])
    out = json.loads(server.loeschantrag_vermerken("lead-1", "mail", "bitte loeschen"))
    assert "fehler" not in out
    assert gesperrt and gesperrt[0][2] == "sales:loeschantrag"
    assert gesperrt[0][0] == "max@x.de"
