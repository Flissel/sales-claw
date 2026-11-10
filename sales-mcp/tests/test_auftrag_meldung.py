"""Meldungen an den Betreiber: auftrag_meldung + Werkzeug auftraege_melden.

Das Schema `auftrag` existiert in keiner Test-DB: auftrag_buch wird im Speicher nachgebaut.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

import auftrag_buch  # noqa: E402
import auftrag_meldung  # noqa: E402
import server  # noqa: E402

AID = "0123abcd-0000-4000-8000-000000000001"
THEMA = "Drei Fehler bei der bAV"


class Speicher:
    """Mini-Auftragsbuch: Zeilen wie sales_eigene sie liefert; ergebnis_mischen nur bis zum Endstand."""

    def __init__(self, monkeypatch, *zeilen):
        self.zeilen = list(zeilen)
        self.laden = None
        monkeypatch.setattr(auftrag_buch, "eigene", self.eigene)
        monkeypatch.setattr(auftrag_buch, "gemeldet", self.gemeldet)
        monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", self.mischen)

    def eigene(self, q, laden, staende):
        self.laden = laden
        return [json.loads(json.dumps(z)) for z in self.zeilen if z["stand"] in staende]

    def _zeile(self, aid):
        return next(z for z in self.zeilen if z["id"] == aid)

    def gemeldet(self, q, aid, stand):
        z = self._zeile(aid)
        if z["stand"] != stand:
            return False
        z["gemeldet_stand"] = stand
        return True

    def mischen(self, q, aid, teil):
        z = self._zeile(aid)
        if z["stand"] not in ("in_arbeit", "erzeugt", "wartet_freigabe"):
            return False
        z["ergebnis"] = {**z.get("ergebnis", {}), **teil}
        return True


def auftrag(stand, **rest):
    return {"id": AID, "stand": stand, "gemeldet_stand": None, "erinnert_am": None, "fehler": None,
            "eingabe": {"thema": THEMA, "kanaele": ["mastodon", "discord"]}, "ergebnis": {}, **rest}


def melden():
    return auftrag_meldung.melden(None, "sales", None)


def test_fertig_meldet_links_einmal(monkeypatch):
    Speicher(monkeypatch, auftrag("fertig", ergebnis={"beitraege": {"mastodon": "https://m.example/1",
                                                                     "linkedin": "privat"}}))
    erste = melden()
    assert len(erste) == 1
    assert erste[0].startswith(f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) ist online: ")
    assert "mastodon: https://m.example/1" in erste[0] and "linkedin: privat" in erste[0]
    assert melden() == []


def test_abgelaufen_wird_genau_einmal_gemeldet(monkeypatch):
    Speicher(monkeypatch, auftrag("abgelaufen"))
    assert melden() == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) ist nicht rechtzeitig fertig geworden (PC aus?)."]
    assert melden() == []


def test_verworfen_und_gescheitert(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))
    assert melden()[0].endswith("wurde verworfen, nichts ging raus.")
    Speicher(monkeypatch, auftrag("fehler", fehler="Das Reel-Werkzeug war nicht erreichbar."))
    assert melden()[0].endswith("ist gescheitert: Das Reel-Werkzeug war nicht erreichbar.")


def test_fehler_nennt_grund_ohne_personendaten(monkeypatch):
    z = auftrag("fehler", fehler="Absage an anna@example.com und +49 170 1234567 kam zurueck",
                eingabe={"thema": THEMA, "kanaele": [], "empfaenger": "+491701234567",
                         "mail": "anna@example.com"})
    Speicher(monkeypatch, z)
    text = melden()[0]
    assert "Absage" in text
    for roh in ("491701234567", "1234567", "anna@example.com", "@"):
        assert roh not in text


def test_offene_auftraege_melden_nichts(monkeypatch):
    Speicher(monkeypatch, auftrag("angenommen"), auftrag("in_arbeit"), auftrag("erzeugt"), auftrag("wartet_freigabe"))
    assert melden() == []


def test_erinnerung_einmal(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("wartet_freigabe", erinnert_am="2026-11-10T10:00:00+00:00"))
    assert melden() == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) wartet seit 2 Tagen auf deine Freigabe."]
    assert melden() == []
    sp.zeilen[0]["stand"] = "fertig"          # der Endstand kommt trotzdem noch einmal
    sp.zeilen[0]["ergebnis"]["beitraege"] = {"mastodon": "https://m.example/1"}
    assert len(melden()) == 1 and melden() == []


def test_kanalfehler_einmal_solange_er_wartet(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("wartet_freigabe",
                                       ergebnis={"kanal_fehler": {"discord": "Der Versand ist fehlgeschlagen."}}))
    zeilen = melden()
    assert zeilen == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}): discord ging nicht raus: "
                      "Der Versand ist fehlgeschlagen. Bitte in /freigaben ansehen."]
    assert melden() == []
    assert sp.zeilen[0]["ergebnis"]["kanal_fehler_gemeldet"] == ["discord"]


def test_endmeldung_nennt_noch_nicht_gemeldete_kanalfehler(monkeypatch):
    Speicher(monkeypatch, auftrag("fertig", ergebnis={
        "beitraege": {"mastodon": "https://m.example/1", "bluesky": "https://b.example/2"},
        "kanal_fehler": {"discord": "Der Versand hängt seit über 30 Minuten.",
                         "bluesky": "Der Versand ist fehlgeschlagen.",   # spaeter doch gepostet
                         "x": "Der Kanal ist nicht verbunden."},
        "kanal_fehler_gemeldet": ["x"]}))
    text = melden()[0]
    assert "discord ging nicht raus: Der Versand hängt" in text
    assert "bluesky ging nicht raus" not in text and "x ging nicht raus" not in text
    assert melden() == []


def test_markieren_scheitert_keine_wiederholung(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("abgelaufen"))
    monkeypatch.setattr(auftrag_buch, "gemeldet", lambda q, aid, stand: False)
    assert melden() == []
    sp.zeilen[0]["stand"] = "wartet_freigabe"
    sp.zeilen[0]["erinnert_am"] = "x"
    monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", lambda q, aid, teil: False)
    assert melden() == []


def test_faellige_markiert_nichts(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))
    erste = auftrag_meldung.faellige(None, "sales", None)
    assert erste == auftrag_meldung.faellige(None, "sales", None)
    assert erste[0][:2] == (AID, "abgebrochen") and len(erste[0]) == 3


def test_werkzeug_liefert_meldungen_json_mit_laden(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("abgebrochen"))
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    r = json.loads(server.auftraege_melden())
    assert len(r["meldungen"]) == 1 and sp.laden == "ivan"
    assert json.loads(server.auftraege_melden()) == {"meldungen": []}
    assert server.auftraege_melden in server.WERKZEUGE


def test_cron_postfach_check_ruft_auftraege_melden_auf_antworten_pruefen_nicht():
    from pathlib import Path
    cron = Path(__file__).resolve().parents[2] / "deploy" / "cron"
    pf = json.loads((cron / "postfach-check.json").read_text(encoding="utf-8"))
    assert pf["enabled"] is True and pf["delivery"]["mode"] == "announce"
    assert pf["delivery"]["to"] == "${MELDE_AN}"
    assert "auftraege_melden()" in pf["payload"]["message"]
    alt = json.loads((cron / "antworten-pruefen.json").read_text(encoding="utf-8"))
    assert "auftraege_melden" not in alt["payload"]["message"]
