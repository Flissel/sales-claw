"""auftrag-bote (M8 Stufe A): fertige Marketing-Ergebnisse werden Kanal-Entwuerfe, Auftraege werden abgeschlossen.

Das Schema `auftrag` gibt es in keiner Test-DB: das Auftragsbuch ist hier ein Stub mit Auftraegen im Speicher.
`drafts`, `activities`, `kanal_status` und `einstellungen` sind echt in sales_test, die Entwuerfe entstehen ueber
dieselben Werkzeuge wie "Auf Kanaelen teilen" (server.kanal_post_entwurf / post_entwurf_erstellen).
"""
import json
import os
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# HART, nicht setdefault (T5a): siehe test_linkedin_posts.py.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auftrag_bote as ab  # noqa: E402
import freigabe_eingang as fe  # noqa: E402
import kanaele  # noqa: E402
import marketing_pult  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402
from pult_http import PultFehler  # noqa: E402

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
DATEI = "vid-0123abcd-drei-fehler.mp4"
FIRMA = "fin2gether"
LADEN = "testladen"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Buch:
    """Auftragsbuch im Speicher, mit denselben Regeln wie Migration 096 fuer die Sales-Huellen."""

    UEBERGAENGE = {("erzeugt", "wartet_freigabe"), ("erzeugt", "fehler"), ("wartet_freigabe", "fertig"),
                   ("wartet_freigabe", "abgebrochen"), ("wartet_freigabe", "fehler")}

    def __init__(self):
        self.auftraege: dict[str, dict] = {}
        self.jetzt = T0
        self.ablaufen_aufrufe = 0
        self.mischungen: list[tuple[str, dict]] = []
        # Marketing-API (GET /video): fertige Reels je Firma, aktuell und im Archiv
        self.reels = {FIRMA: [{"datei": DATEI, "status": "fertig", "archiviert": False},
                              {"datei": "vid-99999999-in-arbeit.mp4", "status": "in_arbeit", "archiviert": False}],
                      "andere-firma": [{"datei": "vid-77777777-fremd.mp4", "status": "fertig", "archiviert": True}]}
        self.pult_fehler = None

    def pult(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        if self.pult_fehler:
            raise self.pult_fehler
        assert methode == "GET" and pfad.startswith("/video?"), pfad
        abfrage = urllib.parse.parse_qs(pfad.split("?", 1)[1])
        archiv = abfrage["archiv"] == ["true"]
        return {"auftraege": [a for a in self.reels.get(abfrage["mandant"][0], []) if a["archiviert"] == archiv]}

    def neu(self, kanaele=("mastodon", "discord"), stand="erzeugt", **ergebnis) -> str:
        aid = str(uuid.uuid4())
        self.auftraege[aid] = {
            "id": aid, "von": "sales", "an": "marketing", "laden": LADEN, "mandant": FIRMA, "art": "reel",
            "stand": stand, "eingabe": {"thema": "Drei Fehler bei der bAV", "kanaele": list(kanaele)},
            "ergebnis": {"video": str(uuid.uuid4()), "datei": DATEI, "titel": "Drei Fehler bei der bAV",
                         "text_lang": "Drei Fehler, die fast jeder bei der bAV macht. #bAV",
                         "text_kurz": "Drei bAV-Fehler. #bAV", **ergebnis},
            "fehler": None, "erinnert_am": None,
            "verlauf": [{"stand": stand, "zeit": self.jetzt.isoformat()}]}
        return aid

    @staticmethod
    def _kopie(wert):
        return json.loads(json.dumps(wert))      # wie eine frisch gelesene jsonb-Zeile

    def ablaufen(self, q):
        self.ablaufen_aufrufe += 1
        return 0

    def eigene(self, q, laden, staende):
        return [self._kopie(a) for a in self.auftraege.values() if a["laden"] == laden and a["stand"] in staende]

    def ergebnis_mischen(self, q, aid, teil):
        a = self.auftraege[aid]
        if a["stand"] not in ("in_arbeit", "erzeugt", "wartet_freigabe"):
            return False
        self.mischungen.append((aid, self._kopie(teil)))
        a["ergebnis"] = {**a["ergebnis"], **self._kopie(teil)}
        return True

    def stand_setzen(self, q, aid, von, nach, fehler=None):
        a = self.auftraege[aid]
        if a["stand"] != von or (von, nach) not in self.UEBERGAENGE:
            return False
        a["stand"], a["fehler"] = nach, fehler or a["fehler"]
        a["verlauf"].append({"stand": nach, "zeit": self.jetzt.isoformat()})
        return True

    def erinnert(self, q, aid):
        self.auftraege[aid]["erinnert_am"] = self.jetzt.isoformat()
        return True


@pytest.fixture(autouse=True)
def buch(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, sales_test.personas, "
                     "sales_test.leads, sales_test.kanal_status, sales_test.medien_meta cascade")
        conn.execute("delete from sales_test.einstellungen where schluessel in (%s, %s)",
                     (ab.EINSTELLUNG_HERZSCHLAG, fe.EINSTELLUNG_HERZSCHLAG))
    sammel = str(server._q("insert into leads (name, source) values "
                           "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"])
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", sammel)
    monkeypatch.setenv("LINKEDIN_POST_LEAD_ID", sammel)
    monkeypatch.setenv("MARKETING_MANDANT", FIRMA)
    monkeypatch.setenv("LADEN_PRAEFIX", LADEN)
    for kanal in ("mastodon", "discord", "youtube"):
        kanaele.status_schreiben(server._q, kanal, True, None)
    with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, DATEI), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom" + b"0" * 20)
    b = Buch()
    monkeypatch.setattr(ab, "auftrag_buch", b)
    monkeypatch.setattr(marketing_pult, "anfrage", b.pult)
    return b


def _durchgang(buch, jetzt=T0):
    buch.jetzt = jetzt
    return ab.durchgang(server._q, jetzt)


def _entwuerfe():
    return server._q("select id, channel, auftrag, media_ref, status, subject from drafts order by channel")


def _status(kanal, status, error=None):
    server._q("update drafts set status = %s, error = %s where channel = %s returning id", (status, error, kanal))


def _beleg(kanal, **payload):
    z = server._q("select id, lead_id from drafts where channel = %s", (kanal,))[0]
    server._q("insert into activities (lead_id, type, payload) values (%s, 'versand', %s) returning id",
              (z["lead_id"], json.dumps({"draft_id": str(z["id"]), "kanal": kanal, **payload})))


def test_erzeugt_legt_je_kanal_einen_entwurf_mit_auftrag_an(buch):
    aid = buch.neu(kanaele=("mastodon", "discord", "youtube", "linkedin"))
    zaehler = _durchgang(buch)
    entwuerfe = _entwuerfe()
    assert [e["channel"] for e in entwuerfe] == ["discord", "linkedin", "mastodon", "youtube"]
    assert all(str(e["auftrag"]) == aid and e["media_ref"] == DATEI and e["status"] == "pending"
               for e in entwuerfe)
    youtube = [e for e in entwuerfe if e["channel"] == "youtube"][0]
    assert youtube["subject"] == "Drei Fehler bei der bAV"          # Titel ist Pflicht: das Thema
    a = buch.auftraege[aid]
    assert a["stand"] == "wartet_freigabe"
    assert a["ergebnis"]["entwuerfe"] == {e["channel"]: str(e["id"]) for e in entwuerfe}
    assert zaehler == {"abgelaufen": 0, "entwuerfe": 4, "abgeschlossen": 0, "erinnert": 0}
    assert buch.ablaufen_aufrufe == 1


def test_zweiter_durchgang_legt_keine_doppelten_entwuerfe_an(buch):
    aid = buch.neu()
    _durchgang(buch)
    _durchgang(buch)
    assert len(_entwuerfe()) == 2
    # Neustart nach dem Anlegen, vor dem Standwechsel: der Auftrag steht noch auf erzeugt.
    buch.auftraege[aid]["stand"] = "erzeugt"
    assert _durchgang(buch)["entwuerfe"] == 0
    assert len(_entwuerfe()) == 2 and buch.auftraege[aid]["stand"] == "wartet_freigabe"
    # Neustart zwischen Anlegen und Zuordnen: der Entwurf traegt noch keinen Auftrag.
    server._q("update drafts set auftrag = null where channel = 'discord' returning id")
    buch.auftraege[aid]["stand"] = "erzeugt"
    assert _durchgang(buch)["entwuerfe"] == 0
    entwuerfe = _entwuerfe()
    assert len(entwuerfe) == 2 and all(str(e["auftrag"]) == aid for e in entwuerfe)
    assert buch.auftraege[aid]["ergebnis"]["entwuerfe"] == {e["channel"]: str(e["id"]) for e in entwuerfe}


def test_alle_gesendet_macht_fertig_mit_urls(buch):
    aid = buch.neu(kanaele=("mastodon", "youtube", "linkedin"))
    _durchgang(buch)
    for kanal in ("mastodon", "youtube", "linkedin"):
        _status(kanal, "sent")
    _beleg("mastodon", beitrag="1101", url="https://social.example/@haus/1101")
    _beleg("youtube", beitrag="abc", url="https://youtube.com/shorts/abc")
    _beleg("linkedin", beitrag="urn:li:share:7")
    zaehler = _durchgang(buch, T0 + timedelta(minutes=5))
    a = buch.auftraege[aid]
    assert a["stand"] == "fertig" and zaehler["abgeschlossen"] == 1
    assert a["ergebnis"]["beitraege"] == {"mastodon": "https://social.example/@haus/1101",
                                          "youtube": "privat", "linkedin": "urn:li:share:7"}


def test_alle_verworfen_macht_abgebrochen(buch):
    aid = buch.neu()
    _durchgang(buch)
    _status("mastodon", "rejected")
    assert _durchgang(buch)["abgeschlossen"] == 0          # discord wartet noch
    _status("discord", "rejected")
    assert _durchgang(buch)["abgeschlossen"] == 1
    a = buch.auftraege[aid]
    assert a["stand"] == "abgebrochen" and "beitraege" not in a["ergebnis"]


def test_failed_dann_rejected_schliesst_ab(buch):
    aid = buch.neu()
    _durchgang(buch)
    _status("mastodon", "sent")
    _beleg("mastodon", beitrag="1", url="https://social.example/@haus/1")
    _status("discord", "failed", "Discord: HTTP 500")
    _durchgang(buch)
    assert buch.auftraege[aid]["stand"] == "wartet_freigabe"
    _status("discord", "rejected", "Discord: HTTP 500")
    _durchgang(buch)
    a = buch.auftraege[aid]
    assert a["stand"] == "fertig"
    assert a["ergebnis"]["beitraege"] == {"mastodon": "https://social.example/@haus/1"}


def test_failed_haelt_offen_und_vermerkt_kanalfehler_einmal(buch):
    aid = buch.neu(kanaele=("mastodon", "discord", "youtube"))
    _durchgang(buch)
    _status("discord", "failed", "Discord: HTTP 500")
    _status("youtube", "failed", "in Zustellung seit 2026-11-10T12:01:00+00:00 (dispatcher 1a2b3c4d)")
    _durchgang(buch)
    _durchgang(buch)
    a = buch.auftraege[aid]
    assert a["stand"] == "wartet_freigabe"
    assert a["ergebnis"]["kanal_fehler"] == {"discord": "fehlgeschlagen"}   # in Zustellung ist kein Fehler
    assert [t for _, t in buch.mischungen if "kanal_fehler" in t] == [{"kanal_fehler": {"discord": "fehlgeschlagen"}}]
    _status("youtube", "failed", "YouTube: Kontingent erschoepft")
    _durchgang(buch)
    assert buch.auftraege[aid]["ergebnis"]["kanal_fehler"] == {"discord": "fehlgeschlagen",
                                                               "youtube": "fehlgeschlagen"}


def test_erinnerung_nach_48h_einmal(buch):
    aid = buch.neu()
    _durchgang(buch)
    assert _durchgang(buch, T0 + timedelta(hours=47))["erinnert"] == 0
    assert buch.auftraege[aid]["erinnert_am"] is None
    assert _durchgang(buch, T0 + timedelta(hours=49))["erinnert"] == 1
    assert buch.auftraege[aid]["erinnert_am"] is not None
    assert _durchgang(buch, T0 + timedelta(hours=72))["erinnert"] == 0


def test_kein_kanal_macht_fehler(buch):
    nicht_verbunden = buch.neu(kanaele=("telegram_kanal",))
    os.remove(os.path.join(medien.ERZEUGT_VERZEICHNIS, DATEI))
    ohne_datei = buch.neu(kanaele=("mastodon",))
    _durchgang(buch)
    assert _entwuerfe() == []
    a = buch.auftraege[nicht_verbunden]
    assert a["stand"] == "fehler" and a["fehler"].startswith("Kein Kanal nahm den Entwurf an: ")
    b = buch.auftraege[ohne_datei]
    assert b["stand"] == "fehler" and b["fehler"].startswith("Kein Kanal nahm den Entwurf an: Mastodon: ")


def test_fremdes_reel_wird_nicht_geteilt(buch, monkeypatch):
    """Wie nicht_eigenes_reel auf der Reels-Seite: nur ein Reel der Firma dieses Ladens."""
    fremd = buch.neu()
    buch.auftraege[fremd]["mandant"] = "andere-firma"
    kaputt = buch.neu(datei="../media/geheim.mp4")
    _durchgang(buch)
    assert _entwuerfe() == []
    assert buch.auftraege[fremd]["stand"] == "fehler"
    assert buch.auftraege[kaputt]["stand"] == "fehler"


@pytest.mark.parametrize("datei", ["vid-77777777-fremd.mp4",        # fertiges Reel einer anderen Firma
                                   "vid-99999999-in-arbeit.mp4",    # eigenes, aber nicht fertig
                                   "vid-55555555-unbekannt.mp4"])   # Marketing kennt die Datei nicht
def test_datei_ist_kein_fertiges_reel_der_firma(buch, datei):
    """Dieselbe Eigentumspruefung wie die Reels-Seite (reel_teilen.fertige_reels): die Datei liegt im
    Medienordner und hat die Reel-Form, gehoert laut Marketing-API aber nicht zu den fertigen Reels der Firma."""
    with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, datei), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom" + b"0" * 20)
    aid = buch.neu(datei=datei)
    _durchgang(buch)
    assert _entwuerfe() == []
    a = buch.auftraege[aid]
    assert a["stand"] == "fehler" and a["fehler"] == "Das Reel gehört nicht zur Firma dieses Ladens."


def test_marketing_api_weg_laesst_auftrag_stehen(buch):
    """Ohne Antwort der Marketing-API ist nichts geprueft: kein Entwurf, der Auftrag bleibt `erzeugt`, der
    Herzschlag meldet den Fehler; der naechste Durchgang holt es nach."""
    aid = buch.neu()
    buch.pult_fehler = PultFehler("nicht_erreichbar", "weg")
    _durchgang(buch)
    assert _entwuerfe() == [] and buch.auftraege[aid]["stand"] == "erzeugt"
    h = fe.herzschlag_lesen(jetzt=T0, schluessel=ab.EINSTELLUNG_HERZSCHLAG)
    assert h["fehler"] == "Auftrag.PultFehler"
    buch.pult_fehler = None
    _durchgang(buch)
    assert len(_entwuerfe()) == 2 and buch.auftraege[aid]["stand"] == "wartet_freigabe"


def test_herzschlag_eigener_schluessel(buch, monkeypatch):
    buch.neu()
    _durchgang(buch)
    h = fe.herzschlag_lesen(jetzt=T0, schluessel=ab.EINSTELLUNG_HERZSCHLAG)
    assert ab.EINSTELLUNG_HERZSCHLAG == "auftrag_bote_herzschlag"
    assert h["zustand"] == "ok" and h["fehler"] is None
    assert fe.herzschlag_lesen(jetzt=T0)["zustand"] == "unbekannt"   # der Freigabe-Bote bleibt unberuehrt
    von = server._q("select geaendert_von from einstellungen where schluessel = %s",
                    (ab.EINSTELLUNG_HERZSCHLAG,))[0]["geaendert_von"]
    assert von == "auftrag-bote"
    assert fe.herzschlag_pruefzeile(jetzt=T0, schluessel=ab.EINSTELLUNG_HERZSCHLAG).startswith("ok ")

    def weg(*a, **kw):
        raise RuntimeError("Auftragsbuch weg")
    monkeypatch.setattr(buch, "eigene", weg)
    _durchgang(buch, T0 + timedelta(minutes=1))
    h = fe.herzschlag_lesen(jetzt=T0 + timedelta(minutes=1), schluessel=ab.EINSTELLUNG_HERZSCHLAG)
    assert h["fehler"] == "RuntimeError"
