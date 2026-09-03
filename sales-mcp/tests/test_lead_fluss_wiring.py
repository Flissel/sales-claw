"""F2/F3-Verdrahtung in server.py, ohne Datenbank: `_q` wird durch einen
Verteiler ersetzt, der nach SQL-Teilstrings antwortet. So beweisen die Tests
die Reihenfolge der Griffe (Auswahl -> genau ein Funktionsaufruf -> Vermerk)
und die Fehlerpfade, nicht die Datenbank."""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")
import server  # noqa: E402


def verteiler(antworten):
    """antworten: Liste von (sql_teil, rueckgabe). Erster Treffer gewinnt."""
    aufrufe = []

    def q(sql, params=()):
        aufrufe.append((sql, params))
        for teil, wert in antworten:
            if teil in sql:
                return wert
        return []
    q.aufrufe = aufrufe
    return q


ZEILE = {"id": "l1", "name": "Anna Apify", "email": "anna@firma.de", "phone": "",
         "notes": "b2b_leads", "enrichment": {}}


def test_recherche_an_marketing_braucht_begruendung(monkeypatch):
    monkeypatch.setattr(server, "_q", verteiler([]))
    out = json.loads(server.recherche_an_marketing("   "))
    assert "begruendung" in out["fehler"]


def test_recherche_an_marketing_ohne_kandidaten_ist_eine_meldung(monkeypatch):
    monkeypatch.setattr(server, "_q", verteiler([("from leads", [])]))
    out = json.loads(server.recherche_an_marketing("passen zur Zielgruppe"))
    assert "Keine passenden Recherche-Leads" in out["fehler"]


def test_recherche_an_marketing_schlaegt_vor_und_vermerkt(monkeypatch):
    q = verteiler([
        ("from leads", [ZEILE]),
        ("vorschlag_aus_sales", [{"ergebnis": {"proposal_id": "p-1", "angenommen": 1,
                                                "uebersprungen_gesperrt": 0,
                                                "uebersprungen_ungueltig": 0}}]),
    ])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.recherche_an_marketing("KMU-Zielgruppe passt"))
    assert out["proposal_id"] == "p-1" and out["leads"] == 1
    funktionsaufrufe = [s for s, _ in q.aufrufe if "vorschlag_aus_sales" in s]
    assert len(funktionsaufrufe) == 1
    assert any("jsonb_set" in s for s, _ in q.aufrufe)          # E6: vermerkt
    assert any(p and p[1] == "an_marketing" for _, p in q.aufrufe if len(p) == 3)


def test_recherche_an_marketing_vermerkt_nichts_ohne_proposal(monkeypatch):
    q = verteiler([
        ("from leads", [ZEILE]),
        ("vorschlag_aus_sales", [{"ergebnis": {"proposal_id": None, "angenommen": 0,
                                                "uebersprungen_gesperrt": 1,
                                                "uebersprungen_ungueltig": 0}}]),
    ])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.recherche_an_marketing("Grund"))
    assert out["uebersprungen_gesperrt"] == 1 and out["proposal_id"] is None
    assert not any("jsonb_set" in s for s, _ in q.aufrufe)


def test_recherche_an_marketing_ist_registriert():
    assert server.recherche_an_marketing in server.WERKZEUGE
