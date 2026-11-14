"""Beobachter sales-auge: Abgleich, Beitritt, Runde, Beschreib-Arbeit, HTTP (Task 6).

Browser und Modelle sind Attrappen: eine Seite mit `evaluate`/`close`, ein
Einbetter mit festen Vektoren. Playwright und fastembed muessen hier NICHT
installiert sein (auge.py importiert sie erst beim Start des Dienstes).
"""
import base64
import io
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auge  # noqa: E402
import bild_arbeit  # noqa: E402
import bildschirm  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402

T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
GEHEIM = "Geheimer Raum 4711"
LINK = "https://meet.ffmuc.net/GeheimerRaum4711"
FRAGMENT = ("#config.startWithAudioMuted=true&config.startWithVideoMuted=true"
            "&config.prejoinConfig.enabled=false&config.startSilent=true"
            "&userInfo.displayName=%22Laura%20(Bildschirm)%22")


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    monkeypatch.delenv("JITSI_HOSTS", raising=False)
    monkeypatch.delenv("JITSI_BASIS", raising=False)
    monkeypatch.setattr(auge, "_gesperrt_bis", {})
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield


def _jpeg(muster="links", groesse=(320, 200)):
    bild = Image.new("RGB", groesse, (255, 255, 255))
    d = ImageDraw.Draw(bild)
    b, h = groesse
    if muster == "links":
        d.rectangle([0, 0, b // 2, h], fill=(0, 0, 0))
    elif muster == "oben":
        d.rectangle([0, 0, b, h // 2], fill=(0, 0, 0))
    elif muster == "diagonal":
        for i in range(0, b, 20):
            d.rectangle([i, 0, i + 9, h], fill=(0, 0, 0))
    out = io.BytesIO()
    bild.save(out, "JPEG")
    return out.getvalue()


def _b64(muster):
    return base64.b64encode(_jpeg(muster)).decode()


def _akte(uid="a1", schalter=True, link=LINK):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, plattform, status, "
        "bildschirm_auswerten, vexa_meeting_id, link) "
        "values (%s, 'kalender', %s, %s, 'jitsi', 'laeuft', %s, 7, %s) returning uid",
        (uid, T0, T0 + timedelta(hours=1), schalter, link))


class Seite:
    """Attrappe einer Browserseite: liefert der Reihe nach die Antworten."""

    def __init__(self, antworten=()):
        self.antworten = list(antworten)
        self.geschlossen = False
        self.skripte = []

    def evaluate(self, skript):
        self.skripte.append(skript)
        a = self.antworten.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    def close(self):
        self.geschlossen = True


class Oeffner:
    def __init__(self):
        self.urls = []
        self.seiten = []

    def __call__(self, url):
        self.urls.append(url)
        s = Seite()
        self.seiten.append(s)
        return s


def _quelle(muster, von="Anna", quelle=None):
    """Ein Eintrag aus __lauraBild().quellen; Quelle vorgabemaessig je Teilendem."""
    return {"quelle": quelle or f"{von}-v1", "von": von,
            "jpeg": _b64(muster) if muster else None}


def _roh(jpeg, von="Anna"):
    """Freigabe mit einer Quelle und beliebigem (auch kaputtem) jpeg-Feld."""
    return {"teilt": True, "quellen": [{"quelle": f"{von}-v1", "von": von, "jpeg": jpeg}]}


def _teilt(muster, von="Anna"):
    return {"teilt": True, "quellen": [_quelle(muster, von)]}


def _mehrere(*quellen):
    return {"teilt": True, "quellen": list(quellen)}


AUS = {"teilt": False, "quellen": []}


# ---------- Abgleich ----------

def test_abgleich_startet_und_beendet():
    assert auge.abgleich({"a", "b"}, {"b", "c"}) == ({"a"}, {"c"})
    assert auge.abgleich(set(), set()) == (set(), set())
    assert auge.abgleich({"a"}, {"a"}) == (set(), set())


def test_abgleich_beendet_wenn_schalter_aus():
    """Review Focus 1: Schalter mitten im Termin aus -> binnen einer Runde raus."""
    _akte("a1")
    _akte("aus", schalter=False)
    sitzungen = {}
    oeffner = Oeffner()
    auge.abgleichen(sitzungen, oeffner, T0)
    assert set(sitzungen) == {"a1"}
    assert oeffner.urls == [LINK + FRAGMENT]

    # Es teilt jemand, ein Bild liegt offen (bis = null)
    sitzungen["a1"].seite.antworten.append(_teilt("links"))
    auge.runde(sitzungen, T0 + timedelta(seconds=1))
    assert len(bildschirm.bilder("a1")) == 1

    server._q("update termin_akten set bildschirm_auswerten = false where uid = 'a1' "
              "returning uid")
    auge.abgleichen(sitzungen, oeffner, T0 + timedelta(seconds=3))
    assert sitzungen == {}
    assert oeffner.seiten[0].geschlossen
    assert bildschirm.bilder("a1")[0]["bis"] == T0 + timedelta(seconds=3)
    # Nichts mehr abgelegt, auch wenn noch ein Bild "in Arbeit" ist
    assert bildschirm.bild_ablegen("a1", _jpeg("oben"), T0 + timedelta(seconds=9), "Anna") is None


def test_abgleich_oeffnet_nur_jitsi_links_mit_https():
    _akte("http", link="http://meet.ffmuc.net/Raum")
    _akte("fremd", link="https://boese.example/Raum")
    _akte("js", link="javascript:alert(1)")
    _akte("leer", link=None)
    _akte("ok", link="https://meet.ffmuc.net/Raum?x=1")
    oeffner = Oeffner()
    sitzungen = {}
    auge.abgleichen(sitzungen, oeffner, T0)
    assert set(sitzungen) == {"ok"}
    assert oeffner.urls == ["https://meet.ffmuc.net/Raum?x=1" + FRAGMENT]


def test_abgleich_oeffnen_scheitert_ohne_absturz_und_wartet(caplog):
    _akte("a1")
    caplog.set_level(logging.DEBUG)
    versuche = []

    def kaputt(url):
        versuche.append(url)
        raise RuntimeError(GEHEIM)

    sitzungen = {}
    auge.abgleichen(sitzungen, kaputt, T0)
    auge.abgleichen(sitzungen, kaputt, T0 + timedelta(seconds=2))
    assert sitzungen == {} and len(versuche) == 1           # Pause nach Fehlschlag
    auge.abgleichen(sitzungen, kaputt, T0 + auge.NEUSTART_PAUSE + timedelta(seconds=1))
    assert len(versuche) == 2
    assert GEHEIM not in caplog.text and "GeheimerRaum" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_beitritts_url():
    assert auge.beitritts_url("https://meet.ffmuc.net/Raum") == \
        "https://meet.ffmuc.net/Raum" + FRAGMENT
    assert auge.beitritts_url("https://meet.ffmuc.net/Raum?jwt=a&b=c#config.x=1") == \
        "https://meet.ffmuc.net/Raum?jwt=a&b=c" + FRAGMENT
    assert auge.beitritts_url("https://meet.ffmuc.net/Raum#") == \
        "https://meet.ffmuc.net/Raum" + FRAGMENT
    assert auge.ANZEIGENAME == "Laura (Bildschirm)"


# ---------- Runde ----------

def _sitzung(uid="a1", antworten=()):
    s = auge.Sitzung(uid=uid, seite=Seite(antworten))
    return {uid: s}


def test_runde_legt_bei_aenderung_ab():
    _akte("a1")
    sitzungen = _sitzung("a1", [
        _teilt("links"),                     # T0: erstes Bild -> ablegen
        _teilt("links"),                     # +10 s: gleich -> nein
        _teilt("diagonal"),                  # +12 s: anders -> ablegen
        _teilt("oben"),                      # +14 s: anders, aber < 5 s -> nein
        _roh("kein-base64!"),                                     # kaputt -> weiter
        _roh(base64.b64encode(b"kein jpeg").decode()),
        _roh(None),                                               # noch kein Bild
        _teilt("oben"),                      # +20 s: anders -> ablegen
    ])
    for sek in (0, 10, 12, 14, 15, 16, 17, 20):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    liste = bildschirm.bilder("a1")
    assert [x["aufgenommen_am"] for x in liste] == [
        T0, T0 + timedelta(seconds=12), T0 + timedelta(seconds=20)]
    assert {x["geteilt_von"] for x in liste} == {"Anna"}
    assert sitzungen["a1"].anzahl == 3
    # Sicherheit: ausgewertet wird nur, was __lauraBild liefert
    assert all("__lauraBild" in s for s in sitzungen["a1"].seite.skripte)


def test_runde_zaehlt_vorhandene_bilder_fuer_die_obergrenze():
    _akte("a1")
    for i in range(3):
        bildschirm.bild_ablegen("a1", _jpeg("links"), T0 - timedelta(minutes=10 - i), "X")
    sitzungen = {}
    oeffner = Oeffner()
    auge.abgleichen(sitzungen, oeffner, T0)
    assert sitzungen["a1"].anzahl == 3


def test_runde_freigabe_ende():
    _akte("a1")
    sitzungen = _sitzung("a1", [
        _teilt("links"),                     # T0 ablegen
        AUS,                                 # +30 s Freigabe endet -> bis
        AUS,                                 # +32 s nichts
        _teilt("links", von="Ben"),          # +33 s neue Freigabe, gleiches Bild -> ablegen
    ])
    for sek in (0, 30, 32, 33):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    liste = bildschirm.bilder("a1")
    assert len(liste) == 2
    assert liste[0]["bis"] == T0 + timedelta(seconds=30)
    assert liste[1]["aufgenommen_am"] == T0 + timedelta(seconds=33)
    assert liste[1]["geteilt_von"] == "Ben" and liste[1]["bis"] is None


def test_runde_wechsel_des_teilenden_nimmt_naechstes_erlaubtes_bild():
    """Wechsel des Teilenden: gleiches Bild zaehlt als neu, aber erst nach MIN_ABSTAND."""
    _akte("a1")
    sitzungen = _sitzung("a1", [_teilt("links", "Anna"), _teilt("links", "Ben"),
                                _teilt("links", "Ben")])
    for sek in (0, 1, 5):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    liste = bildschirm.bilder("a1")
    assert [x["geteilt_von"] for x in liste] == ["Anna", "Ben"]
    assert liste[1]["aufgenommen_am"] == T0 + timedelta(seconds=5)
    assert liste[0]["bis"] == T0 + timedelta(seconds=5)


def test_runde_drossel_gilt_auch_nach_freigabe_ende():
    """Ende und sofort neue Freigabe innerhalb von 5 s: kein Bild vor MIN_ABSTAND."""
    _akte("a1")
    sitzungen = _sitzung("a1", [_teilt("links"), AUS, _teilt("diagonal"),
                                _teilt("diagonal")])
    for sek in (0, 2, 3, 5):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    liste = bildschirm.bilder("a1")
    assert [x["aufgenommen_am"] for x in liste] == [T0, T0 + timedelta(seconds=5)]
    assert liste[0]["bis"] == T0 + timedelta(seconds=2)


def test_runde_ab_obergrenze_nur_starke_aenderung_auch_nach_wechsel():
    _akte("a1")
    sitzungen = _sitzung("a1", [_teilt("links", "Anna"), AUS, _teilt("links", "Ben"),
                                _teilt("links", "Ben")])
    s = sitzungen["a1"]
    s.anzahl = bildschirm.OBERGRENZE
    s.letzter_hash = bildschirm.dhash(_jpeg("links"))
    s.letzte_zeit = T0 - timedelta(minutes=1)
    for sek in (0, 10, 20, 30):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    assert bildschirm.bilder("a1") == []          # gleiches Bild, Wechsel hilft nicht
    assert s.letzter_hash == bildschirm.dhash(_jpeg("links"))


def test_sitzung_ab_obergrenze_startet_mit_letztem_hash_aus_der_db():
    _akte("a1")
    for i in range(bildschirm.OBERGRENZE):
        server._q("insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash) "
                  "values ('a1', %s, %s, 1, 1, %s) returning id",
                  (T0 - timedelta(minutes=200 - i), b"x", i))
    sitzungen = {}
    auge.abgleichen(sitzungen, Oeffner(), T0)
    s = sitzungen["a1"]
    assert s.anzahl == bildschirm.OBERGRENZE
    assert s.letzter_hash == bildschirm.OBERGRENZE - 1
    assert s.letzte_zeit == T0 - timedelta(minutes=200 - bildschirm.OBERGRENZE + 1)


def test_runde_seitenfehler_stoppt_andere_nicht_und_loggt_nichts(caplog):
    _akte("a1")
    _akte("a2")
    caplog.set_level(logging.DEBUG)
    sitzungen = {**_sitzung("a1", [RuntimeError(GEHEIM)]),
                 **_sitzung("a2", [_teilt("links", von=GEHEIM)])}
    auge.runde(sitzungen, T0)
    assert len(bildschirm.bilder("a2")) == 1
    assert sitzungen["a1"].fehler == 1
    text = caplog.text
    assert GEHEIM not in text and "a1" not in text.replace(auge._h("a1"), "")
    assert "RuntimeError" in text


def test_runde_beendet_seite_nach_wiederholten_fehlern():
    _akte("a1")
    sitzungen = _sitzung("a1", [RuntimeError("x")] * auge.MAX_SEITENFEHLER)
    seite = sitzungen["a1"].seite
    for i in range(auge.MAX_SEITENFEHLER):
        auge.runde(sitzungen, T0 + timedelta(seconds=i))
    assert sitzungen == {} and seite.geschlossen


def test_beenden_schliesst_alle_und_setzt_bis():
    _akte("a1")
    sitzungen = _sitzung("a1", [_teilt("links")])
    seite = sitzungen["a1"].seite
    auge.runde(sitzungen, T0)
    auge.alle_beenden(sitzungen, T0 + timedelta(seconds=7))
    assert sitzungen == {} and seite.geschlossen
    assert bildschirm.bilder("a1")[0]["bis"] == T0 + timedelta(seconds=7)


# ---------- Mehrere gleichzeitige Freigaben (Abnahme-Befunde Task 6) ----------

def test_zwei_quellen_beide_abgelegt():
    _akte("a1")
    sitzungen = _sitzung("a1", [_mehrere(_quelle("links", "Anna"), _quelle("oben", "Ben"))])
    auge.runde(sitzungen, T0)
    liste = bildschirm.bilder("a1")
    assert sorted(x["geteilt_von"] for x in liste) == ["Anna", "Ben"]
    assert {x["aufgenommen_am"] for x in liste} == {T0}
    s = sitzungen["a1"]
    assert s.anzahl == 2 and s.teilt
    assert set(s.quellen) == {"Anna-v1", "Ben-v1"}
    assert s.quellen["Anna-v1"].von == "Anna" and s.quellen["Ben-v1"].von == "Ben"
    assert s.quellen["Anna-v1"].letzter_hash == bildschirm.dhash(_jpeg("links"))
    assert s.quellen["Ben-v1"].letzter_hash == bildschirm.dhash(_jpeg("oben"))


def test_drossel_je_quelle():
    """Quelle A legt ab, B im selben Moment auch; danach drosselt jede Quelle fuer sich."""
    _akte("a1")
    sitzungen = _sitzung("a1", [
        _mehrere(_quelle("links", "Anna"), _quelle("oben", "Ben")),          # T0: beide
        _mehrere(_quelle("diagonal", "Anna"), _quelle("diagonal", "Ben")),   # +2: beide gedrosselt
        _mehrere(_quelle("diagonal", "Anna"), _quelle("diagonal", "Ben")),   # +5: beide
    ])
    for sek in (0, 2, 5):
        auge.runde(sitzungen, T0 + timedelta(seconds=sek))
    liste = bildschirm.bilder("a1")
    assert sorted((x["aufgenommen_am"], x["geteilt_von"]) for x in liste) == [
        (T0, "Anna"), (T0, "Ben"),
        (T0 + timedelta(seconds=5), "Anna"), (T0 + timedelta(seconds=5), "Ben")]
    s = sitzungen["a1"]
    assert s.quellen["Anna-v1"].letzte_zeit == s.quellen["Ben-v1"].letzte_zeit \
        == T0 + timedelta(seconds=5)
    assert s.anzahl == 4


def test_quelle_endet_andere_laeuft_weiter(monkeypatch):
    _akte("a1")
    enden = []
    echt = bildschirm.freigabe_ende

    def ende(uid, zeitpunkt):
        enden.append(zeitpunkt)
        echt(uid, zeitpunkt)

    monkeypatch.setattr(bildschirm, "freigabe_ende", ende)
    sitzungen = _sitzung("a1", [
        _mehrere(_quelle("links", "Anna"), _quelle("oben", "Ben")),   # T0: beide
        _mehrere(_quelle("oben", "Ben")),                              # +10: Anna weg
        AUS,                                                           # +20: auch Ben weg
    ])
    s = sitzungen["a1"]
    auge.runde(sitzungen, T0)
    ben = s.quellen["Ben-v1"]
    vorher = (ben.von, ben.letzter_hash, ben.letzte_zeit)
    auge.runde(sitzungen, T0 + timedelta(seconds=10))
    assert enden == []                               # Ben teilt noch: kein Freigabe-Ende
    assert s.teilt and set(s.quellen) == {"Ben-v1"}
    assert s.quellen["Ben-v1"] is ben and (ben.von, ben.letzter_hash, ben.letzte_zeit) == vorher
    assert len(bildschirm.bilder("a1")) == 2         # Bens Bild unveraendert -> nichts Neues
    auge.runde(sitzungen, T0 + timedelta(seconds=20))
    assert enden == [T0 + timedelta(seconds=20)]
    assert not s.teilt and s.quellen == {}
    assert all(x["bis"] is not None for x in bildschirm.bilder("a1"))


def test_obergrenze_gemeinsam():
    """anzahl und Obergrenze gelten je Akte; eine neue Quelle ab der Obergrenze beginnt
    mit dem Akte-weiten letzten Hash (gleiches Bild -> nichts Neues)."""
    _akte("a1")
    sitzungen = _sitzung("a1", [
        _mehrere(_quelle("links", "Anna"), _quelle("oben", "Ben")),             # T0
        _mehrere(_quelle("links", "Anna"), _quelle("oben", "Ben"),
                 _quelle("oben", "Cleo")),                                      # +10: Cleo neu
    ])
    s = sitzungen["a1"]
    s.anzahl = bildschirm.OBERGRENZE - 2
    auge.runde(sitzungen, T0)
    assert s.anzahl == bildschirm.OBERGRENZE          # beide Quellen zaehlen in einen Topf
    assert s.letzter_hash == bildschirm.dhash(_jpeg("oben"))   # zuletzt abgelegt: Ben
    auge.runde(sitzungen, T0 + timedelta(seconds=10))
    assert s.quellen["Cleo-v1"].letzter_hash == bildschirm.dhash(_jpeg("oben"))
    assert len(bildschirm.bilder("a1")) == 2 and s.anzahl == bildschirm.OBERGRENZE


def test_frame_nur_neue_form_hoechstens_drei_quellen(monkeypatch):
    """Alte Form ({teilt, von, jpeg}) gilt als 'teilt nicht'; mehr als MAX_QUELLEN
    Quellen werden (sortiert) gekappt."""
    _akte("a1")
    enden = []
    monkeypatch.setattr(bildschirm, "freigabe_ende", lambda uid, t: enden.append(t))
    alt = {"teilt": True, "von": "Anna", "jpeg": _b64("links")}
    sitzungen = _sitzung("a1", [_teilt("links"), alt])
    auge.runde(sitzungen, T0)
    auge.runde(sitzungen, T0 + timedelta(seconds=10))
    assert enden == [T0 + timedelta(seconds=10)] and not sitzungen["a1"].teilt
    assert len(bildschirm.bilder("a1")) == 1

    assert auge.MAX_QUELLEN == 3
    viele = _mehrere(*[_quelle("links", n) for n in ("Eva", "Dora", "Cleo", "Ben", "Anna")])
    teilt, quellen = auge._frame(viele)
    assert teilt and [q for q, _, _ in quellen] == ["Anna-v1", "Ben-v1", "Cleo-v1"]
    assert auge._frame(alt) == (False, [])
    assert auge._frame({"teilt": True, "quellen": []}) == (False, [])


# ---------- Beschreib-Arbeit (R6) ----------

class Attrappe:
    def bild(self, jpeg):
        v = [0.0] * 512
        v[0] = 1.0
        return v

    def text_clip(self, text):
        v = [0.0] * 512
        v[0 if "bild" in text else 7] = 1.0
        return v

    def text(self, text):
        v = [0.0] * 384
        v[3] = 1.0
        return v


def test_beschreib_schritt_pausen(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _akte("a1")
    assert auge.beschreib_schritt(Attrappe()) == auge.LEER_PAUSE_S
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "Anna")
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie")
    assert auge.beschreib_schritt(Attrappe()) == 0
    # KI aus -> Bild endet in 'fehler' -> 30 s Pause
    bildschirm.bild_ablegen("a1", _jpeg("oben"), T0 + timedelta(seconds=30), "Anna")

    def aus(*a, **kw):
        raise ollama.OllamaFehler(GEHEIM)

    monkeypatch.setattr(ollama, "chat", aus)
    assert auge.beschreib_schritt(Attrappe()) == auge.FEHLER_PAUSE_S == 30

    # Ausnahme aus naechste_beschreiben selbst (z. B. DB weg) -> gefangen, Pause
    def kaputt(_e):
        raise RuntimeError(GEHEIM)

    monkeypatch.setattr(bild_arbeit, "naechste_beschreiben_status", kaputt)
    assert auge.beschreib_schritt(Attrappe()) == auge.FEHLER_PAUSE_S
    assert GEHEIM not in caplog.text and "RuntimeError" in caplog.text


def test_naechste_beschreiben_status(monkeypatch):
    _akte("a1")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) is None
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "Anna")
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie")
    assert bild_arbeit.naechste_beschreiben_status(Attrappe()) == "fertig"


def test_beschreib_schleife_endet_mit_stopp(monkeypatch):
    stopp = threading.Event()
    aufrufe = []

    def schritt(_e):
        aufrufe.append(1)
        if len(aufrufe) == 3:
            stopp.set()
        return 0

    monkeypatch.setattr(auge, "beschreib_schritt", schritt)
    auge.beschreib_schleife(Attrappe(), stopp)
    assert len(aufrufe) == 3


# ---------- HTTP ----------

@pytest.fixture
def dienst():
    srv = auge.http_dienst(Attrappe(), "127.0.0.1", 0, lambda: {"sitzungen": 0})
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _post(url, daten):
    roh = daten if isinstance(daten, bytes) else json.dumps(daten).encode()
    anfrage = urllib.request.Request(url, data=roh, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=10) as r:
        return r.status, json.loads(r.read())


def test_suche_endpunkt(dienst, monkeypatch):
    _akte("a1")
    _akte("a2")
    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie mit Graph")
    b1 = bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "Anna")
    b2 = bildschirm.bild_ablegen("a2", _jpeg("links"), T0, "Anna")
    while bild_arbeit.naechste_beschreiben(Attrappe()):
        pass

    with urllib.request.urlopen(dienst + "/gesund", timeout=10) as r:
        assert r.status == 200 and json.loads(r.read())["ok"] is True

    status, liste = _post(dienst + "/suche", {"text": "bild"})
    assert status == 200 and {x["id"] for x in liste} == {b1, b2}
    assert liste[0]["beschreibung"] == "Folie mit Graph"
    assert datetime.fromisoformat(liste[0]["aufgenommen_am"]) == T0
    status, liste = _post(dienst + "/suche", {"text": "bild", "uid": "a2", "limit": 5})
    assert [x["id"] for x in liste] == [b2]

    for falsch in ({}, {"text": ""}, {"text": 5}, {"text": "x", "limit": "viel"},
                   {"text": "x", "uid": 3}, b"kein json", {"text": "x" * 5000}):
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(dienst + "/suche", falsch)
        assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(dienst + "/gibtsnicht", timeout=10)
    assert e.value.code == 404


def test_suche_endpunkt_fehler_ohne_inhalt(dienst, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def kaputt(*a, **kw):
        raise RuntimeError(GEHEIM)

    monkeypatch.setattr(bild_arbeit, "suchen", kaputt)
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(dienst + "/suche", {"text": GEHEIM})
    assert e.value.code == 500
    assert GEHEIM not in e.value.read().decode()
    assert GEHEIM not in caplog.text and "RuntimeError" in caplog.text


def test_http_lese_timeout_schliesst_haengende_verbindung(monkeypatch):
    """T6b: ein Client, der den Rumpf nicht schickt, haelt keinen Thread fest."""
    import socket
    import time
    assert auge.HTTP_LESE_TIMEOUT_S == 10
    monkeypatch.setattr(auge, "HTTP_LESE_TIMEOUT_S", 1)
    srv = auge.http_dienst(Attrappe(), "127.0.0.1", 0, lambda: {})
    assert srv.RequestHandlerClass.timeout == 1
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with socket.create_connection(srv.server_address, timeout=10) as s:
            s.sendall(b"POST /suche HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{\"te")
            beginn = time.monotonic()
            assert s.recv(1024) == b""            # Server schliesst ohne Antwort
            assert time.monotonic() - beginn < 5
    finally:
        srv.shutdown()
        srv.server_close()


def test_beitritt_goto_timeout_kurz():
    """T6a: ein haengender Beitritt blockiert die Runde hoechstens ~15 s."""
    gesehen = {}

    class Seite:
        def goto(self, url, **kw):
            gesehen.update(kw, url=url)

    class Kontext:
        def add_init_script(self, script):
            pass

        def new_page(self):
            return Seite()

        def close(self):
            pass

    class Browser:
        def new_context(self, **kw):
            return Kontext()

    auge._oeffner(Browser())("https://meet.invalid/r")
    assert gesehen["timeout"] == auge.BEITRITT_TIMEOUT_MS == 15_000


# ---------- Seiten-Skript (statisch) ----------

def test_seitenskript_liest_nur_desktop_tracks():
    js = (auge.SKRIPT_PFAD).read_text(encoding="utf-8")
    assert "window.__lauraBild" in js
    assert "features/base/tracks" in js and "'desktop'" in js
    # R11: nur Multistream-Bildschirmtracks, kein alter 'video'+'desktop'-Weg
    assert "t.mediaType !== 'screenshare'" in js
    assert "t.mediaType !== 'video'" not in js and "t.mediaType === 'video'" not in js
    assert "image/jpeg" in js and "0.8" in js and "1600" in js
    assert "setReceiverConstraints" in js
    # keine Netz-Zugriffe, kein Ablegen im Browser
    for verboten in ("fetch(", "XMLHttpRequest", "localStorage", "WebSocket(", "MediaRecorder"):
        assert verboten not in js, verboten


def test_max_drei_quellen_js():
    js = (auge.SKRIPT_PFAD).read_text(encoding="utf-8")
    assert "const MAX_QUELLEN = 3;" in js
    assert ".slice(0, MAX_QUELLEN)" in js
    assert "const HOECHSTENS_MS = 8000;" in js
    # je Quelle ein eigenes <video> in einer Map nach getSourceName(), Rueckfall participantId
    assert "new Map()" in js and "getSourceName" in js and "participantId" in js
    assert "quellen:" in js
    # nur noch EIN Video-Slot gibt es nicht mehr
    assert "let video = null" not in js


def test_kamera_bleibt_ausgeschlossen_js():
    js = (auge.SKRIPT_PFAD).read_text(encoding="utf-8")
    # istDesktop unveraendert (R11): nur entfernte Multistream-Bildschirmtracks
    for zeile in ("if (!t || t.local || !t.jitsiTrack) return false;",
                  "if (t.mediaType !== 'screenshare') return false;",
                  "if (t.videoType !== DESKTOP) return false;",
                  "if (typeof jt.isLocal === 'function' && jt.isLocal()) return false;",
                  "jt.getVideoType() !== DESKTOP) return false;",
                  "const desktopTracks = (s) => ((s && s['features/base/tracks']) || [])"
                  ".filter(istDesktop);"):
        assert zeile in js, zeile
    # holen nimmt seine Tracks nur aus desktopTracks
    assert "desktopTracks(s).filter((t) => !t.muted)" in js
    assert "'camera'" not in js.split("window.__lauraInfo")[0]


# ---------- Browser weg ----------

class Browser:
    def __init__(self, lebt=True):
        self.lebt = lebt

    def is_connected(self):
        if isinstance(self.lebt, Exception):
            raise self.lebt
        return self.lebt


def test_takt_schritt_meldet_toten_browser():
    _akte("a1")
    oeffner = Oeffner()
    sitzungen, zustand = {}, {}
    assert auge.takt_schritt(sitzungen, oeffner, Browser(True), zustand, T0) is True
    assert zustand["browser"] is True and set(sitzungen) == {"a1"}
    for tot in (Browser(False), Browser(RuntimeError("weg"))):
        assert auge.takt_schritt(sitzungen, oeffner, tot, zustand, T0) is False
        assert zustand["browser"] is False
    assert len(oeffner.urls) == 1                  # kein Beitrittsversuch mehr


def test_gesund_meldet_toten_browser_mit_503():
    zustand = {"browser": True}
    srv = auge.http_dienst(Attrappe(), "127.0.0.1", 0,
                           lambda: {"ok": zustand["browser"], "browser": zustand["browser"]})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/gesund"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200 and json.loads(r.read())["browser"] is True
        zustand["browser"] = False
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=10)
        assert e.value.code == 503
        assert json.loads(e.value.read()) == {"ok": False, "browser": False}
    finally:
        srv.shutdown()
        srv.server_close()


# ---------- Heikle Bildschirme (Schicht A) ----------

class PrueferAttrappe:
    """Meldet jedes Bild als heikel (oder nicht) und zaehlt die Aufrufe."""

    def __init__(self, heikel=True):
        self._heikel = heikel
        self.aufrufe = 0

    def heikel(self, jpeg):
        self.aufrufe += 1
        v = [0.0] * 512
        v[2] = 1.0
        return self._heikel, v


def test_heikles_bild_wird_nicht_abgelegt_und_gezaehlt(monkeypatch, caplog):
    _akte("a1")
    monkeypatch.setattr(auge, "pruefer", PrueferAttrappe(True))
    sitzungen = _sitzung("a1", [_teilt("links")])
    with caplog.at_level("INFO", logger="sales-auge"):
        auge.runde(sitzungen, T0)
    assert bildschirm.bilder("a1") == []
    assert server._q("select count(*) as n from termin_bilder")[0]["n"] == 0
    assert server._q("select bilder_uebersprungen from termin_akten "
                     "where uid = 'a1'")[0]["bilder_uebersprungen"] == 1
    s = sitzungen["a1"]
    q = s.quellen["Anna-v1"]                     # Hash und Zeit je Quelle (Task 6)
    assert s.anzahl == 0 and q.letzte_zeit == T0 and q.letzter_hash is not None
    assert s.letzter_hash is None                # Akte-weit: nichts abgelegt
    assert "Heikles Bild verworfen" in caplog.text
    assert "Geheimer" not in caplog.text


def test_heikles_bild_nicht_alle_runden_neu_geprueft(monkeypatch):
    _akte("a1")
    p = PrueferAttrappe(True)
    monkeypatch.setattr(auge, "pruefer", p)
    sitzungen = _sitzung("a1", [_teilt("links"), _teilt("links")])
    auge.runde(sitzungen, T0)
    auge.runde(sitzungen, T0 + timedelta(seconds=10))
    assert p.aufrufe == 1                       # zweiter, gleicher Frame: kein Pruefen
    assert server._q("select bilder_uebersprungen from termin_akten "
                     "where uid = 'a1'")[0]["bilder_uebersprungen"] == 1


def test_unheikles_bild_wird_abgelegt_mit_vorberechnetem_vektor(monkeypatch):
    _akte("a1")
    monkeypatch.setattr(auge, "pruefer", PrueferAttrappe(False))
    sitzungen = _sitzung("a1", [_teilt("links")])
    auge.runde(sitzungen, T0)
    z = server._q("select vektor_bild is not null as hat from termin_bilder")
    assert len(z) == 1 and z[0]["hat"] is True
    assert sitzungen["a1"].anzahl == 1


def test_pruefer_fehler_legt_nichts_ab(monkeypatch):
    _akte("a1")

    class Kaputt:
        def heikel(self, jpeg):
            raise RuntimeError("Modell weg")

    k = Kaputt()
    k.aufrufe = 0
    orig = k.heikel

    def zaehlend(jpeg):
        k.aufrufe += 1
        return orig(jpeg)

    k.heikel = zaehlend
    monkeypatch.setattr(auge, "pruefer", k)
    sitzungen = _sitzung("a1", [_teilt("links"), _teilt("diagonal")])
    auge.runde(sitzungen, T0)
    auge.runde(sitzungen, T0 + timedelta(seconds=2))   # < MIN_ABSTAND: gedrosselt
    assert bildschirm.bilder("a1") == []
    assert k.aufrufe == 1


def test_beschreiben_rechnet_vektor_bild_nur_wenn_null(monkeypatch):
    _akte("a1")
    v = [0.0] * 512
    v[5] = 1.0
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "Anna", vektor_bild=v)
    gerechnet = []

    class Zaehler(Attrappe):
        def bild(self, jpeg):
            gerechnet.append(1)
            return super().bild(jpeg)

    monkeypatch.setattr(ollama, "chat", lambda *a, **kw: "Folie")
    assert bild_arbeit.naechste_beschreiben(Zaehler()) is True
    assert gerechnet == []
    assert server._q("select vektor_bild is not null as h from termin_bilder")[0]["h"]
