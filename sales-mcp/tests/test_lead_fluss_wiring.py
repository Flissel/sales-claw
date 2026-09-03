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


# --- F3 -------------------------------------------------------------------

UEBERGABE = {"id": "u1", "from_email": "petra@kunde.de", "from_name": "Petra Probe",
             "subject": "Re: Early Access", "auszug": "Wie geht es weiter?",
             "kampagne": "Herbst", "klassifikation": "reply", "seit": "2026-09-03"}


def test_uebergaben_pruefen_listet_offene(monkeypatch):
    monkeypatch.setattr(server, "_q", verteiler([("uebergaben_offen", [UEBERGABE])]))
    out = json.loads(server.uebergaben_pruefen())
    assert out["offen"] == 1 and out["uebergaben"][0]["from_email"] == "petra@kunde.de"


def test_annehmen_legt_kontakt_mit_marketing_und_inbound_an(monkeypatch):
    q = verteiler([
        ("uebergaben_offen", [UEBERGABE]),
        ("lower(email) = lower(%s)", []),              # kein bestehender Kontakt
        ("insert into leads", [{"id": "l-neu"}]),
        ("uebergabe_erledigen", [{"ok": True}]),
    ])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "_sperre", lambda email="", phone="": "")
    out = json.loads(server.uebergabe_annehmen("u1"))
    assert out == {"lead_id": "l-neu", "angelegt": True, "consent_status": "inbound", "uebergabe_erledigt": True}
    insert = next(p for s, p in q.aufrufe if "insert into leads" in s)
    assert "marketing" in insert                       # source='marketing'
    assert any("consent_status = 'inbound'" in s for s, _ in q.aufrufe)
    erledigt = next(p for s, p in q.aufrufe if "uebergabe_erledigen" in s)
    assert erledigt[1] == "angenommen" and erledigt[2] == "l-neu"


def test_annehmen_nutzt_bestehenden_kontakt_per_email(monkeypatch):
    q = verteiler([
        ("uebergaben_offen", [UEBERGABE]),
        ("lower(email) = lower(%s)", [{"id": "l-alt"}]),
        ("uebergabe_erledigen", [{"ok": True}]),
    ])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "_sperre", lambda email="", phone="": "")
    out = json.loads(server.uebergabe_annehmen("u1"))
    assert out["lead_id"] == "l-alt" and out["angelegt"] is False
    assert not any("insert into leads" in s for s, _ in q.aufrufe)


def test_annehmen_lehnt_gesperrten_absender_ab(monkeypatch):
    q = verteiler([("uebergaben_offen", [UEBERGABE]), ("uebergabe_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "_sperre", lambda email="", phone="": "marketing:unsubscribe: abgemeldet")
    out = json.loads(server.uebergabe_annehmen("u1"))
    assert "Verbotsliste" in out["fehler"]
    erledigt = next(p for s, p in q.aufrufe if "uebergabe_erledigen" in s)
    assert erledigt[1] == "abgelehnt" and "Verbotsliste" in erledigt[3]
    assert not any("insert into leads" in s for s, _ in q.aufrufe)


def test_annehmen_unbekannte_uebergabe(monkeypatch):
    monkeypatch.setattr(server, "_q", verteiler([("uebergaben_offen", [])]))
    out = json.loads(server.uebergabe_annehmen("u9"))
    assert "Keine offene Uebergabe" in out["fehler"]


def test_ablehnen_braucht_grund(monkeypatch):
    monkeypatch.setattr(server, "_q", verteiler([]))
    out = json.loads(server.uebergabe_ablehnen("u1", "  "))
    assert "grund" in out["fehler"]


def test_ablehnen_mit_grund(monkeypatch):
    q = verteiler([("uebergabe_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.uebergabe_ablehnen("u1", "Spam"))
    assert out == {"abgelehnt": True}


def test_drei_uebergabe_werkzeuge_registriert():
    for fn in (server.uebergaben_pruefen, server.uebergabe_annehmen, server.uebergabe_ablehnen):
        assert fn in server.WERKZEUGE
