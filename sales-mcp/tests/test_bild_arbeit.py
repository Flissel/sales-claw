"""Bilder beschreiben, einbetten, durchsuchen (Bildauswertung live, Task 4)."""
import io
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import bild_arbeit  # noqa: E402
import bildschirm  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402

T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
GEHEIM = "Streng geheime Umsatzzahl 4711"


def _vek(dim, achse):
    v = [0.0] * dim
    v[achse % dim] = 1.0
    return v


class Attrappe:
    """Feste Vektoren: Bild -> Achse 0 (CLIP) / 0 (Text); Suchtexte waehlen die Achse."""

    def __init__(self, fehler=False):
        self.fehler = fehler

    def bild(self, jpeg):
        if self.fehler:
            raise RuntimeError("kaputt")
        return _vek(512, 0)

    def text_clip(self, text):
        return _vek(512, 0 if "bild" in text else 7)

    def text(self, text):
        if self.fehler:
            raise RuntimeError("kaputt")
        return _vek(384, 3 if "text" in text else 9)


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _akte(uid):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, plattform, status, "
        "bildschirm_auswerten, vexa_meeting_id, link) "
        "values (%s, 'kalender', %s, %s, 'jitsi', 'laeuft', true, 7, 'https://x.invalid/r') "
        "returning uid", (uid, T0, T0 + timedelta(hours=1)))


def _bild(uid="a1", minute=0):
    return bildschirm.bild_ablegen(uid, _jpeg(), T0 + timedelta(minutes=minute), "Jemand")


def _zeile(bid):
    return server._q("select beschreibung, beschreibung_status, beschreibung_versuche, "
                     "versucht_am, "
                     "vektor_bild is not null as vb, vektor_text is not null as vt "
                     "from termin_bilder where id = %s", (bid,))[0]


def _zurueckdatieren(bid, sekunden):
    """Den letzten Versuch in die Vergangenheit legen (statt zu warten)."""
    server._q("update termin_bilder set versucht_am = versucht_am - make_interval(secs => %s) "
              "where id = %s returning id", (sekunden, bid))


def test_beschreiben_schreibt_text_und_vektoren(monkeypatch):
    _akte("a1")
    bid = _bild()
    aufrufe = []

    def chat(system, nutzer, **kw):
        aufrufe.append((system, kw))
        return "  Eine Folie mit Umsatzzahlen.  "

    monkeypatch.setattr(ollama, "chat", chat)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    z = _zeile(bid)
    assert z["beschreibung"] == "Eine Folie mit Umsatzzahlen."
    assert z["beschreibung_status"] == "fertig" and z["vb"] and z["vt"]
    assert z["beschreibung_versuche"] == 1
    assert len(aufrufe[0][1]["bilder"]) == 1 and aufrufe[0][1]["timeout_s"] == 60
    assert aufrufe[0][0] == bild_arbeit.BILD_PROMPT
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False


def test_beschreiben_fehler_zaehlt_versuche_bis_drei(monkeypatch):
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        raise ollama.OllamaFehler("aus")

    monkeypatch.setattr(ollama, "chat", chat)
    for n in (1, 2, 3):
        assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
        z = _zeile(bid)
        assert z["beschreibung_status"] == "fehler" and z["beschreibung_versuche"] == n
        _zurueckdatieren(bid, 3600)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False
    assert _zeile(bid)["beschreibung_versuche"] == 3


def test_neuversuch_wartet_wachsende_pause(monkeypatch):
    """R16: nach Versuch 1 30 s, nach Versuch 2 5 min, gemessen ab dem letzten Versuch."""
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        raise ollama.OllamaFehler("aus")

    monkeypatch.setattr(ollama, "chat", chat)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    assert _zeile(bid)["versucht_am"] is not None
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False      # Pause laeuft
    _zurueckdatieren(bid, 20)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False      # 20 s < 30 s
    _zurueckdatieren(bid, 11)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True       # Versuch 2
    assert _zeile(bid)["beschreibung_versuche"] == 2
    _zurueckdatieren(bid, 31)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False      # jetzt 5 min
    _zurueckdatieren(bid, 240)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is False      # 271 s < 300 s
    _zurueckdatieren(bid, 30)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie")
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True       # Versuch 3
    z = _zeile(bid)
    assert z["beschreibung_versuche"] == 3 and z["beschreibung_status"] == "fertig"


def test_pause_haelt_andere_bilder_nicht_auf(monkeypatch):
    _akte("a1")
    b1 = _bild("a1", 0)
    b2 = _bild("a1", 1)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: (_ for _ in ()).throw(
        ollama.OllamaFehler("aus")))
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True       # b1 scheitert
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Text")
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True       # b2 trotz Pause von b1
    assert _zeile(b2)["beschreibung_status"] == "fertig"
    assert _zeile(b1)["beschreibung_status"] == "fehler"


def test_vektor_bild_steht_nach_ki_fehler_und_ist_suchbar(monkeypatch):
    """R16: der Bild-Vektor haengt nicht an der KI; das Bild ist ohne Beschreibung findbar."""
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        z = _zeile(bid)
        assert z["vb"] and not z["vt"]           # schon vor dem KI-Aufruf geschrieben
        raise ollama.OllamaFehler("aus")

    monkeypatch.setattr(ollama, "chat", chat)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    z = _zeile(bid)
    assert z["beschreibung_status"] == "fehler" and z["vb"] and not z["vt"]
    assert z["beschreibung"] is None
    r = bild_arbeit.suchen(Attrappe(), "bild")
    assert [x["id"] for x in r] == [bid] and r[0]["score"] == pytest.approx(1.0)
    assert r[0]["beschreibung"] is None
    # Neuversuch berechnet den Bild-Vektor nicht noch einmal
    _zurueckdatieren(bid, 3600)

    class Zaehler(Attrappe):
        n = 0

        def bild(self, jpeg):
            Zaehler.n += 1
            return super().bild(jpeg)

    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie text")
    assert bild_arbeit.naechste_beschreiben(Zaehler()) is True
    assert Zaehler.n == 0
    z = _zeile(bid)
    assert z["beschreibung_status"] == "fertig" and z["vb"] and z["vt"]


def test_einbettungsfehler_ist_fehler_nie_fertig(monkeypatch):
    _akte("a1")
    bid = _bild()
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Text")
    assert bild_arbeit.naechste_beschreiben(Attrappe(fehler=True)) is True
    z = _zeile(bid)
    assert z["beschreibung_status"] == "fehler" and not z["vb"] and not z["vt"]
    assert z["beschreibung"] is None


def test_beschreibung_fuer_geloeschtes_bild_verpufft(monkeypatch):
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        assert bildschirm.bild_loeschen("a1", bid)
        return "Text"

    monkeypatch.setattr(ollama, "chat", chat)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    assert server._q("select 1 from termin_bilder") == []

    # auch der Fehlerpfad ist tolerant
    bid = _bild("a1", 5)

    def chat2(*a, **kw):
        bildschirm.bild_loeschen("a1", bid)
        raise ollama.OllamaFehler("aus")

    monkeypatch.setattr(ollama, "chat", chat2)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    assert server._q("select 1 from termin_bilder") == []


def _fertig(monkeypatch, uid, minute, text="x"):
    bid = _bild(uid, minute)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: text)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    return bid


def test_suchen_findet_per_text_und_bild_vektor(monkeypatch):
    _akte("a1")
    bid = _fertig(monkeypatch, "a1", 0, "Folie text")
    _bild("a1", 3)  # offen, noch ohne Vektor: darf nie auftauchen
    # Bild-Vektor (Achse 0) passt zu "bild"; Text-Vektor (Achse 3) zu "text"
    r = bild_arbeit.suchen(Attrappe(), "bild")
    assert [x["id"] for x in r] == [bid] and r[0]["score"] == pytest.approx(1.0)
    assert set(r[0]) == {"id", "uid", "aufgenommen_am", "beschreibung", "score"}
    r = bild_arbeit.suchen(Attrappe(), "text")
    assert r[0]["id"] == bid and r[0]["score"] == pytest.approx(1.0)
    r = bild_arbeit.suchen(Attrappe(), "nichts")
    assert r[0]["score"] == pytest.approx(0.0)
    assert bild_arbeit.suchen(Attrappe(), "bild", limit=0) == []


def test_suchen_auf_uid_begrenzt(monkeypatch):
    _akte("a1")
    _akte("a2")
    b1 = _fertig(monkeypatch, "a1", 0)
    b2 = _fertig(monkeypatch, "a2", 0)
    assert {x["id"] for x in bild_arbeit.suchen(Attrappe(), "bild")} == {b1, b2}
    r = bild_arbeit.suchen(Attrappe(), "bild", uid="a2")
    assert [x["id"] for x in r] == [b2]


def test_kein_inhalt_im_log(monkeypatch, caplog):
    _akte("geheim-uid")
    _bild("geheim-uid")
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: GEHEIM)
    bild_arbeit.naechste_beschreiben(Attrappe())
    _bild("geheim-uid", 5)

    def chat(*a, **kw):
        raise ollama.OllamaFehler(GEHEIM)

    monkeypatch.setattr(ollama, "chat", chat)
    bild_arbeit.naechste_beschreiben(Attrappe())
    bild_arbeit.suchen(Attrappe(), GEHEIM)
    log = caplog.text
    assert GEHEIM not in log and "geheim-uid" not in log and "Jemand" not in log
    assert "OllamaFehler" in log


def test_fastembed_einbetter_masse():
    pytest.importorskip("fastembed")
    import einbetter_fastembed
    e = einbetter_fastembed.FastEmbedEinbetter()
    assert len(e.bild(_jpeg())) == 512
    assert len(e.text_clip("ein Diagramm")) == 512
    assert len(e.text("ein Diagramm")) == 384
