"""wissensbasis_fragen — die Wissensbasis in natuerlicher Sprache fragen.

Ohne echte Datenbank und ohne echtes Rowboat: SALES_DB_URL zeigt ins Leere
(der Pool oeffnet faul, Import bleibt moeglich), rowboat.frage wird ersetzt.
Drei Zusagen: (1) die Antwort kommt als JSON mit `antwort`, (2) fehlende
Konfiguration ist eine hoerbare Meldung, kein Absturz, (3) der Schluessel
steht in keiner Rueckgabe.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")
import rowboat  # noqa: E402
import server  # noqa: E402


def test_antwort_kommt_als_json(monkeypatch):
    monkeypatch.setattr(rowboat, "frage",
                        lambda text, **kw: {"ok": True, "antwort": "VibeMind ist ein Agenten-OS.", "dauer_ms": 12})
    out = json.loads(server.wissensbasis_fragen("Was ist VibeMind?"))
    assert out["antwort"].startswith("VibeMind")
    assert "fehler" not in out


def test_fehlende_konfiguration_ist_hoerbar(monkeypatch):
    monkeypatch.setattr(rowboat, "frage",
                        lambda text, **kw: {"ok": False, "dauer_ms": 0,
                                            "fehler": "Rowboat ist nicht eingerichtet, es fehlt: ROWBOAT_API_KEY"})
    out = json.loads(server.wissensbasis_fragen("Was ist VibeMind?"))
    assert "ROWBOAT_API_KEY" in out["fehler"]


def test_leere_frage_wird_abgelehnt():
    out = json.loads(server.wissensbasis_fragen("   "))
    assert "fehler" in out


def test_kein_schluessel_in_der_rueckgabe(monkeypatch):
    monkeypatch.setattr(rowboat, "SCHLUESSEL", "geheim-42")
    monkeypatch.setattr(rowboat, "frage",
                        lambda text, **kw: {"ok": False, "dauer_ms": 0,
                                            "fehler": rowboat._ohne_schluessel("HTTP 401: Bearer geheim-42 abgelehnt")})
    out = server.wissensbasis_fragen("Test")
    assert "geheim-42" not in out


def test_werkzeug_ist_registriert():
    assert server.wissensbasis_fragen in server.WERKZEUGE
