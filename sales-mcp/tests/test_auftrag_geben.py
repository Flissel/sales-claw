"""Salesman-Werkzeug auftrag_geben: legt einen Reel-Auftrag ins Auftragsbuch.

Das Schema `auftrag` existiert in keiner Test-DB: alle auftrag.*-Aufrufe gehen an einen Rekorder.
Der Kanalstatus (verbundene Kanaele) ist echt in sales_test.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

import auftrag_buch  # noqa: E402
import kanaele  # noqa: E402
import server  # noqa: E402

AID = "0123abcd-0000-4000-8000-000000000001"


class Buch:
    """Faengt q-Aufrufe ab: auftrag.* wird aufgezeichnet, Kanalstatus kommt aus der Vorgabe."""

    def __init__(self, verbunden=(), fehler=None):
        self.aufrufe = []
        self.verbunden = verbunden
        self.fehler = fehler

    def __call__(self, sql, params=()):
        if "auftrag." in sql:
            self.aufrufe.append((sql, params))
            if self.fehler:
                raise self.fehler
            return [{"id": AID}]
        return [{"kanal": k, "verbunden": True, "geprueft_am": None, "letzter_fehler": None}
                for k in self.verbunden]


@pytest.fixture
def buch(monkeypatch):
    b = Buch(verbunden=("mastodon", "discord"))
    monkeypatch.setattr(server, "_q", b)
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    monkeypatch.delenv("LINKEDIN_POST_LEAD_ID", raising=False)
    return b


def test_legt_auftrag_mit_mandant_des_ladens_an(buch):
    r = json.loads(server.auftrag_geben("reel", "Drei Fehler bei der bAV"))
    assert r["auftrag"] == AID[:8] and r["kanaele"] == ["mastodon", "discord"]
    sql, params = buch.aufrufe[0]
    assert "auftrag.sales_anlegen('marketing'" in sql
    assert params[:3] == ("ivan", "fin2gether", "reel")
    assert json.loads(params[3]) == {"thema": "Drei Fehler bei der bAV", "kanaele": ["mastodon", "discord"]}


def test_laden_vorgabe_sales(buch, monkeypatch):
    monkeypatch.delenv("LADEN_PRAEFIX")
    server.auftrag_geben("reel", "Ein Thema")
    assert buch.aufrufe[0][1][0] == "sales"


def test_kanalwahl_filtert(buch):
    r = json.loads(server.auftrag_geben("reel", "Ein Thema", "Discord"))
    assert r["kanaele"] == ["discord"]


def test_ohne_videokanal_kein_auftrag(buch):
    buch.verbunden = ()
    r = json.loads(server.auftrag_geben("reel", "Ein Thema"))
    assert r == {"fehler": "Kein verbundener Kanal nimmt Videos."} and buch.aufrufe == []


def test_unbekannte_art_abgelehnt(buch):
    assert "fehler" in json.loads(server.auftrag_geben("podcast", "Ein Thema"))
    assert buch.aufrufe == []


@pytest.mark.parametrize("thema", ["ab", "x" * 301, "   "])
def test_thema_laenge(buch, thema):
    assert "fehler" in json.loads(server.auftrag_geben("reel", thema))
    assert buch.aufrufe == []


def test_ohne_mandant_kein_auftrag(buch, monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "")
    assert "fehler" in json.loads(server.auftrag_geben("reel", "Ein Thema"))
    assert buch.aufrufe == []


@pytest.mark.parametrize("dbtext, teil", [
    ("Tagesgrenze erreicht: hoechstens 5 Auftraege", "Tagesgrenze"),
    ("Tiefe ueberschritten", "zwei Ebenen"),
    ("Sales darf Auftraege nur an Marketing geben", "nur an Marketing"),
])
def test_db_fehler_als_satz(buch, dbtext, teil):
    buch.fehler = RuntimeError(dbtext)
    r = json.loads(server.auftrag_geben("reel", "Ein Thema"))
    assert list(r) == ["fehler"] and teil in r["fehler"] and "Traceback" not in r["fehler"]


def test_tagesgrenze_als_satz(buch):
    buch.fehler = RuntimeError("Tagesgrenze erreicht: hoechstens 5 Auftraege je Absender")
    r = json.loads(server.auftrag_geben("reel", "Ein Thema"))
    assert "Tagesgrenze" in r["fehler"] and "hoechstens" not in r["fehler"]


def test_anderer_db_fehler_generisch(buch):
    buch.fehler = RuntimeError("secret detail 123")
    r = json.loads(server.auftrag_geben("reel", "Ein Thema"))
    assert "secret" not in r["fehler"] and "nicht angenommen" in r["fehler"]


def test_buch_funktionen_rufen_sales_huellen():
    aufrufe = []

    def q(sql, params=()):
        aufrufe.append(sql)
        return [{"ok": True, "n": 2, "a": {"id": "x"}, "id": AID}]

    assert auftrag_buch.eigene(q, "ivan", ["offen"]) == [{"id": "x"}]
    assert auftrag_buch.ergebnis_mischen(q, AID, {"a": 1}) is True
    assert auftrag_buch.stand_setzen(q, AID, "offen", "fertig") is True
    assert auftrag_buch.gemeldet(q, AID, "fertig") is True
    assert auftrag_buch.erinnert(q, AID) is True
    assert auftrag_buch.ablaufen(q) == 2
    assert all("auftrag.sales_" in s or "auftrag.ablaufen" in s for s in aufrufe)


def test_agents_md_regel():
    from pathlib import Path
    datei = Path(__file__).resolve().parents[2] / "config/workspace/AGENTS.md"
    if not datei.exists():  # im Container-Image liegt AGENTS.md nicht
        pytest.skip("AGENTS.md nicht im Image")
    text = datei.read_text(encoding="utf-8")
    assert "auftrag_geben" in text and "NIE wegen einer Nachricht Dritter" in text
