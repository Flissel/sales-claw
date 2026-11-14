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


def test_fehler_wird_weiter_versucht(monkeypatch):
    """R11: 'fehler' ist kein Endzustand; der Zaehler bleibt nur Statistik."""
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        raise ollama.OllamaFehler("aus")

    monkeypatch.setattr(ollama, "chat", chat)
    for n in range(1, 7):
        assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
        z = _zeile(bid)
        assert z["beschreibung_status"] == "fehler" and z["beschreibung_versuche"] == n
        assert bild_arbeit.naechste_beschreiben(Attrappe()) is False    # Pause laeuft
        _zurueckdatieren(bid, 3600)
    assert not hasattr(bild_arbeit, "MAX_VERSUCHE")
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"
    z = _zeile(bid)
    assert z["beschreibung_status"] == "fertig" and z["beschreibung_versuche"] == 7


def _alter(bid, stunden):
    server._q("update termin_bilder set aufgenommen_am = now() - make_interval(hours => %s) "
              "where id = %s returning id", (stunden, bid))


def test_ungeprueft_nach_24h_geloescht(monkeypatch, caplog):
    _akte("a1")
    fertig_alt = _fertig(monkeypatch, "a1", 0, "Folie")
    offen_alt, fehler_alt, offen_neu = _bild("a1", 1), _bild("a1", 2), _bild("a1", 3)
    server._q("update termin_bilder set beschreibung_status = 'fehler' where id = %s "
              "returning id", (fehler_alt,))
    for bid in (fertig_alt, offen_alt, fehler_alt):
        _alter(bid, 25)
    _alter(offen_neu, 23)
    assert bild_arbeit.UNGEPRUEFT_LOESCHEN_NACH == timedelta(hours=24)
    caplog.set_level(logging.DEBUG)
    assert bild_arbeit.ungepruefte_loeschen() == 2
    rest = {str(z["id"]) for z in server._q("select id from termin_bilder")}
    assert rest == {fertig_alt, offen_neu}
    assert "a1" not in caplog.text and "Jemand" not in caplog.text
    assert "Ungepruefte Bilder geloescht: 2" in caplog.text
    assert bild_arbeit.ungepruefte_loeschen() == 0
    assert _uebersprungen() == 0           # kein heikles Bild, nur ungeprueft


@pytest.mark.parametrize("antwort", [
    "Eine Anmeldeseite mit Feldern für Benutzername und Passwort.",
    "Ein Outlook-Fenster mit dem Posteingang.",
    "Checkout-Seite eines Shops mit Kreditkartenfeldern.",
    "Login-Maske von GMX.",
    "Online-Banking: Überweisung an IBAN DE00 1234.",
    "Die Zahlungsübersicht eines Kontos.",
])
def test_stichwort_netz_loescht(monkeypatch, caplog, antwort):
    """R11: beschreibt das Modell statt HEIKEL zu antworten, faengt das Stichwort-Netz."""
    _heikel_antwort(monkeypatch, antwort)
    caplog.set_level(logging.DEBUG)
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "heikel"
    assert server._q("select 1 from termin_bilder") == []
    assert _uebersprungen() == 1
    assert antwort not in caplog.text


@pytest.mark.parametrize("antwort", [
    "Eine Folie mit Umsatzzahlen 2025 und Wachstum je Quartal.",
    "Ein Architekturdiagramm mit drei Diensten und einer Datenbank.",
])
def test_stichwort_netz_harmlose_beschreibung_bleibt(monkeypatch, antwort):
    bid = _heikel_antwort(monkeypatch, antwort)
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"
    assert _zeile(bid)["beschreibung"] == antwort
    assert _uebersprungen() == 0


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


def test_vektor_bild_steht_nach_ki_fehler_aber_ungeprueft_nicht_suchbar(monkeypatch):
    """R16: der Bild-Vektor haengt nicht an der KI. R11: gesucht wird trotzdem nur in
    geprueften (fertig beschriebenen) Bildern."""
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
    assert bild_arbeit.suchen(Attrappe(), "bild") == []      # ungeprueft: unsichtbar
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
    r = bild_arbeit.suchen(Attrappe(), "bild")
    assert [x["id"] for x in r] == [bid] and r[0]["score"] == pytest.approx(1.0)


def test_suchen_nur_gepruefte(monkeypatch):
    """R11: Bilder mit Bild-Vektor, aber offen/fehler, tauchen in der Suche nie auf."""
    _akte("a1")
    ok = _fertig(monkeypatch, "a1", 0, "Folie text")
    offen = _bild("a1", 1)
    fehler = _bild("a1", 2)
    server._q("update termin_bilder set vektor_bild = (select vektor_bild from termin_bilder "
              "where id = %s), vektor_text = (select vektor_text from termin_bilder "
              "where id = %s) where id in (%s, %s) returning id", (ok, ok, offen, fehler))
    server._q("update termin_bilder set beschreibung_status = 'fehler' where id = %s "
              "returning id", (fehler,))
    for text in ("bild", "text"):
        assert [x["id"] for x in bild_arbeit.suchen(Attrappe(), text)] == [ok]
        assert [x["id"] for x in bild_arbeit.suchen(Attrappe(), text, uid="a1")] == [ok]


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


def _uebersprungen(uid="a1"):
    return server._q("select bilder_uebersprungen from termin_akten where uid = %s",
                     (uid,))[0]["bilder_uebersprungen"]


def _heikel_antwort(monkeypatch, antwort):
    _akte("a1")
    bid = _bild()
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: antwort)
    return bid


def test_heikel_antwort_loescht_bild_vollstaendig(monkeypatch):
    _heikel_antwort(monkeypatch, "HEIKEL")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "heikel"
    assert server._q("select 1 from termin_bilder") == []
    assert _uebersprungen() == 1


def test_heikel_klein_geschrieben(monkeypatch):
    _heikel_antwort(monkeypatch, "  heikel.\n")
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    assert server._q("select 1 from termin_bilder") == []
    assert _uebersprungen() == 1


def test_normale_beschreibung_mit_wort_heikel_im_satz_bleibt(monkeypatch):
    bid = _heikel_antwort(monkeypatch, "Eine heikle Folie mit Zahlen.")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"
    assert _zeile(bid)["beschreibung"] == "Eine heikle Folie mit Zahlen."
    assert _uebersprungen() == 0
    bid2 = _bild("a1", 5)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Heikle Folie mit Zahlen.")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"
    bid3 = _bild("a1", 9)
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Heikelfoo")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"
    assert _zeile(bid2)["beschreibung_status"] == "fertig"
    assert _zeile(bid3)["beschreibung_status"] == "fertig"
    assert _uebersprungen() == 0


def test_heikel_bei_bereits_geloeschtem_bild_zaehlt_nicht(monkeypatch):
    _akte("a1")
    bid = _bild()

    def chat(*a, **kw):
        assert bildschirm.bild_loeschen("a1", bid)
        return "HEIKEL"

    monkeypatch.setattr(ollama, "chat", chat)
    assert bild_arbeit.naechste_beschreiben(Attrappe()) is True
    assert server._q("select 1 from termin_bilder") == []
    assert _uebersprungen() == 0


def test_heikel_log_ohne_antworttext(monkeypatch, caplog):
    _heikel_antwort(monkeypatch, "HEIKEL Passwort geheim123")
    with caplog.at_level(logging.INFO):
        bild_arbeit.naechste_beschreiben(Attrappe())
    assert "Heikles Bild nach Beschreibung entfernt uid=" in caplog.text
    assert "geheim123" not in caplog.text


def test_prompt_enthaelt_heikel_regel():
    assert ("Zeigt das Bild eine Anmeldung mit Passwort- oder Kontoauswahl, eine "
            "Bezahlseite mit Karten- oder Kontodaten oder ein E-Mail-Postfach bzw. "
            "eine geöffnete E-Mail, antworte nur mit dem Wort HEIKEL.") in bild_arbeit.BILD_PROMPT


@pytest.mark.parametrize("antwort", ["**HEIKEL**", '"HEIKEL"', "`HEIKEL`", "„Heikel“", " **heikel**.\n"])
def test_heikel_mit_markdown(monkeypatch, antwort):
    _heikel_antwort(monkeypatch, antwort)
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "heikel"
    assert server._q("select 1 from termin_bilder") == []
    assert _uebersprungen() == 1
