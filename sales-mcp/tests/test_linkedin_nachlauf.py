"""Meldung nach dem Posten (Spec 2026-10-15 §4.4)."""
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402
import linkedin_nachlauf as nl  # noqa: E402

HIER = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sammel(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    s = server._q("insert into leads (name, source) values "
                  "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(s))
    return str(s)


def _versand(sammel, beitrag="urn:li:share:1", alter_h=0, **extra):
    d = server._q("insert into drafts (lead_id, channel, recipient, body, status) "
                  "values (%s, 'linkedin', 'eigenes-profil', 'x', 'sent') returning id",
                  (sammel,))[0]["id"]
    payload = {"draft_id": str(d), "kanal": "linkedin", "weg": "linkedin-dispatcher",
               "empfaenger": "eigenes-profil", "beitrag": beitrag, "medienart": "bild",
               **extra}
    server._q("insert into activities (lead_id, type, payload, created_at) values "
              "(%s, 'versand', %s, now() - make_interval(hours => %s)) returning id",
              (sammel, json.dumps(payload), alter_h))
    return str(d)


def test_offen_und_nach_buchung_nicht_mehr(sammel):
    d = _versand(sammel)
    assert [m["draft_id"] for m in nl.offene_meldungen()] == [d]
    nl.als_gemeldet_buchen(d)
    assert nl.offene_meldungen() == []


def test_aelter_als_24h_nie(sammel):
    _versand(sammel, alter_h=25)
    assert nl.offene_meldungen() == []


def test_ungewiss_und_manuell_nie(sammel):
    _versand(sammel, beitrag=None, ungewiss=True)
    _versand(sammel, beitrag=None, weg="manuell")
    assert nl.offene_meldungen() == []


def test_whatsapp_versand_nie(sammel):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'versand', %s) returning id",
              (sammel, json.dumps({"kanal": "whatsapp", "draft_id": "x"})))
    assert nl.offene_meldungen() == []


def test_text_ohne_liste(sammel):
    d = _versand(sammel, beitrag="urn:li:share:7516268598298845185")
    t = nl.meldetext(d, "urn:li:share:7516268598298845185")
    assert t.startswith("LinkedIn-Post ist online: "
                        "https://www.linkedin.com/feed/update/urn:li:share:7516268598298845185/")
    assert "markieren" not in t


def test_text_mit_liste(sammel):
    d = _versand(sammel)
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'linkedin_markierungen', %s) returning id",
              (sammel, json.dumps({"draft_id": d, "eintraege": [
                  {"name": "Peter Steinacker", "art": "person",
                   "profil": "https://www.linkedin.com/in/p"},
                  {"name": "BMW Group", "art": "firma", "profil": ""}]})))
    t = nl.meldetext(d, "urn:li:share:1")
    assert "Jetzt in der App markieren (Bearbeiten → @Name):" in t
    assert "- @Peter Steinacker · Person · https://www.linkedin.com/in/p" in t
    assert "- @BMW Group · Firma" in t


def _cli(*args):
    return subprocess.run([sys.executable, "linkedin_nachlauf.py", *args], cwd=HIER,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "SALES_DB_SCHEMA": "sales_test"})


def test_cli_liste_text_gemeldet(sammel):
    d = _versand(sammel)
    r = _cli("liste")
    assert r.returncode == 0 and r.stdout.split() == [d]
    r = _cli("text", d)
    assert r.returncode == 0 and "feed/update/urn:li:share:1/" in r.stdout
    assert _cli("gemeldet", d).returncode == 0
    assert _cli("liste").stdout.strip() == ""
    assert _cli("text", d).returncode == 3
