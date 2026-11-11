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
import auftrag_buch  # noqa: E402
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
        if a["stand"] not in ("in_arbeit", "erzeugt", "wartet_freigabe", "werkbank"):
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
                                          "youtube": "privat", "linkedin": "https://www.linkedin.com/feed/update/urn:li:share:7"}


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
    assert a["ergebnis"]["kanal_fehler"] == {"discord": ab.VERSAND_FEHLGESCHLAGEN}   # in Zustellung: noch kein Fehler
    assert [t for _, t in buch.mischungen if "kanal_fehler" in t] == [
        {"kanal_fehler": {"discord": ab.VERSAND_FEHLGESCHLAGEN}}]
    _status("youtube", "failed", "YouTube: Kontingent erschoepft")
    _durchgang(buch)
    assert buch.auftraege[aid]["ergebnis"]["kanal_fehler"] == {"discord": ab.VERSAND_FEHLGESCHLAGEN,
                                                               "youtube": ab.VERSAND_FEHLGESCHLAGEN}


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
    assert a["stand"] == "fehler"
    assert a["fehler"] == "Kein Kanal nahm den Entwurf an: Telegram-Kanal: Der Kanal ist nicht verbunden."
    b = buch.auftraege[ohne_datei]
    assert b["stand"] == "fehler"
    assert b["fehler"] == "Kein Kanal nahm den Entwurf an: Mastodon: Die Reel-Datei ließ sich nicht anhängen."


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


# --- Fix-Runde 1 ---------------------------------------------------------------------------------------------

def test_abgelehnter_kanal_wird_einmal_vermerkt(buch, caplog):
    """YouTube lehnt ab (schon ein Beitrag zum Thema), Telegram-Kanal ist nicht verbunden, Mastodon und
    Discord nehmen an: der Auftrag wartet, die zwei Kanaele stehen je einmal mit Satz in kanal_fehler."""
    anderes = "vid-11111111-altes-reel.mp4"
    with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, anderes), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom" + b"0" * 20)
    alt = json.loads(server.kanal_post_entwurf("youtube", "Drei Fehler bei der bAV", "Frueher", titel="Frueher",
                                               medien_dateien=anderes))
    assert "draft_id" in alt
    aid = buch.neu(kanaele=("mastodon", "discord", "youtube", "telegram_kanal"))
    caplog.set_level("WARNING", logger="auftrag-bote")
    _durchgang(buch)
    a = buch.auftraege[aid]
    assert a["stand"] == "wartet_freigabe"
    assert set(a["ergebnis"]["entwuerfe"]) == {"mastodon", "discord"}
    assert a["ergebnis"]["kanal_fehler"] == {"youtube": "Zu diesem Thema gibt es dort schon einen Beitrag.",
                                             "telegram_kanal": ab.NICHT_VERBUNDEN}
    log = caplog.text
    assert "youtube" in log and "telegram_kanal" in log and "trotzdem" not in log
    # Neustart vor dem Standwechsel: kein zweiter Vermerk
    a["stand"] = "erzeugt"
    _durchgang(buch)
    assert len([t for _, t in buch.mischungen if "kanal_fehler" in t]) == 1


@pytest.mark.parametrize("grund, satz", [
    ("Zum Thema 'X' gibt es auf YouTube schon einen Beitrag (Zustand 'pending', vom 10.11.2026). Zwei Beitraege "
     "zum selben Thema fallen auf. ... ruf erneut auf mit trotzdem=True.",
     "Zu diesem Thema gibt es dort schon einen Beitrag."),
    ("Kanal Mastodon ist noch nicht verbunden – es entsteht kein Entwurf. Zugang am PC speichern: kanal-zugang "
     "speichern mastodon", ab.NICHT_VERBUNDEN),
    ("Datei 'vid-1.mp4' liegt nicht im Medienordner. medien_liste() zeigt, was verfuegbar ist.",
     "Die Reel-Datei ließ sich nicht anhängen."),
    ("Die Datei 'vid-1.mp4' ist fuer den Bot gesperrt — der Schalter ...",
     "Die Reel-Datei ist in den Medien für den Bot gesperrt."),
    ("Mastodon: der Text hat 600 Zeichen, erlaubt sind mit Medien höchstens 500",
     "Text oder Titel passen nicht in die Grenzen des Kanals."),
    ("etwas ganz anderes", ab.UNBEKANNT_ABGELEHNT),
])
def test_ablehnungen_werden_kurze_saetze(grund, satz):
    assert ab.ablehnung_satz(grund) == satz
    assert len(satz) <= 120 and "trotzdem" not in satz


def test_haengende_zustellung_nach_30_min_einmal(buch):
    aid = buch.neu()
    _durchgang(buch)
    marke = f"in Zustellung seit {(T0 + timedelta(minutes=1)).isoformat()} (dispatcher 1a2b3c4d)"
    _status("discord", "failed", marke)
    _durchgang(buch, T0 + timedelta(minutes=20))
    assert "kanal_fehler" not in buch.auftraege[aid]["ergebnis"]
    _durchgang(buch, T0 + timedelta(minutes=40))
    _durchgang(buch, T0 + timedelta(minutes=50))
    a = buch.auftraege[aid]
    assert a["stand"] == "wartet_freigabe"
    assert a["ergebnis"]["kanal_fehler"] == {"discord": ab.VERSAND_HAENGT}
    assert len([t for _, t in buch.mischungen if "kanal_fehler" in t]) == 1


def test_failed_dann_rejected_ohne_gesendet_macht_abgebrochen(buch):
    aid = buch.neu()
    _durchgang(buch)
    _status("mastodon", "rejected")
    _status("discord", "failed", "Discord: HTTP 500")
    _durchgang(buch)
    assert buch.auftraege[aid]["stand"] == "wartet_freigabe"
    _status("discord", "rejected", "Discord: HTTP 500")
    _durchgang(buch)
    assert buch.auftraege[aid]["stand"] == "abgebrochen"


def test_verwaister_gesendeter_entwurf_schliesst_den_kanal_ab(buch):
    """Ein von Hand auf der Reels-Seite angelegter, schon gesendeter Entwurf derselben Datei wird uebernommen:
    dieselbe Datei ein zweites Mal zu posten waere ein Doppel."""
    hand = json.loads(server.kanal_post_entwurf("discord", "Von Hand", "Schon draussen", medien_dateien=DATEI))
    _status("discord", "sent")
    aid = buch.neu()
    _durchgang(buch)
    discord = [e for e in _entwuerfe() if e["channel"] == "discord"]
    assert len(discord) == 1 and str(discord[0]["id"]) == str(hand["draft_id"])
    assert str(discord[0]["auftrag"]) == aid


def test_doppel_beim_zuordnen_wird_zurueckgenommen(buch, monkeypatch):
    """Ein zweiter Bote (oder ein Rennen) hat dem Auftrag fuer Discord schon einen Entwurf zugeordnet, waehrend
    dieser Durchgang seinen anlegt: der eigene verliert am eindeutigen Index und wird sofort zurueckgenommen."""
    aid = buch.neu()
    echt = ab._anlegen

    def mit_rennen(info, thema, ergebnis, datei):
        if info.name == "discord":
            server._q("insert into drafts (lead_id, channel, recipient, subject, body, thema, auftrag) "
                      "values (%s, 'discord', 'eigenes-profil', 'Post: anders', 'x', 'anders', %s) returning id",
                      (server.LINKEDIN_POST_LEAD_ID, aid))
        return echt(info, thema, ergebnis, datei)
    monkeypatch.setattr(ab, "_anlegen", mit_rennen)
    zaehler = _durchgang(buch)
    discord = server._q("select id, status, auftrag from drafts where channel = 'discord' order by created_at")
    assert [(d["status"], d["auftrag"] is not None) for d in discord] == [("pending", True), ("rejected", False)]
    assert buch.auftraege[aid]["ergebnis"]["entwuerfe"]["discord"] == str(discord[0]["id"])
    assert zaehler["entwuerfe"] == 1 and buch.auftraege[aid]["stand"] == "wartet_freigabe"


def test_fremdes_schema_wartet_ohne_durchgang(monkeypatch):
    """Stufe A: nur VibeMind-Laden. In einem anderen Schema kein Exit (sonst Neustartschleife), sondern warten."""
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    monkeypatch.setattr(ab.signal, "signal", lambda *a: None)
    monkeypatch.setattr(ab, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(ab, "durchgang", lambda *a, **k: pytest.fail("kein Durchgang"))
    ab._STOPP.set()                       # wie SIGTERM: das Warten endet sofort
    try:
        assert ab.main() == 0
    finally:
        ab._STOPP.clear()


def test_ungewisser_versand_steht_als_unklar_nicht_als_fehlgeschlagen(buch):
    aid = buch.neu(kanaele=("discord",))
    _durchgang(buch)
    _status("discord", "failed", "UNGEWISS: Antwort verloren, der Beitrag KANN oeffentlich stehen")
    _durchgang(buch, T0 + timedelta(minutes=5))
    assert buch.auftraege[aid]["ergebnis"]["kanal_fehler"] == {"discord": auftrag_buch.VERSAND_UNGEWISS}


def test_linkedin_urn_wird_zum_link(buch):
    aid = buch.neu(kanaele=("linkedin", "mastodon"))
    _durchgang(buch)
    for kanal in ("linkedin", "mastodon"):
        _status(kanal, "sent")
    _beleg("linkedin", beitrag="urn:li:ugcPost:9")
    _beleg("mastodon", beitrag="urn:li:share:keinlinkedin", url="https://social.example/@haus/1")
    _durchgang(buch, T0 + timedelta(minutes=5))
    assert buch.auftraege[aid]["ergebnis"]["beitraege"] == {
        "linkedin": "https://www.linkedin.com/feed/update/urn:li:ugcPost:9",
        "mastodon": "https://social.example/@haus/1"}


# --- Video (Video-Werkbank): Freigabe-Eintrag statt Kanal-Entwuerfe ------------------------------------------

WB_DATEI = "wb-0123abcd-video-f1.mp4"
BASIS = "https://laden.example"


@pytest.fixture(autouse=True)
def eingang_leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.freigabe_eintraege cascade")
    monkeypatch.setenv("UI_BASIS_URL", BASIS + "/")


def _video(buch, stand="erzeugt", **ergebnis) -> str:
    aid = str(uuid.uuid4())
    buch.auftraege[aid] = {
        "id": aid, "von": "sales", "an": "marketing", "laden": LADEN, "mandant": FIRMA, "art": "video",
        "stand": stand, "eingabe": {"thema": "KI im Vertrieb", "beschreibung": "Geheimer Wunsch des Betreibers",
                                    "minuten": 4, "zielgruppe": "Entscheider 34+, die eine Schulung suchen"},
        "ergebnis": {"datei": WB_DATEI, "titel": "KI im Vertrieb", "dauer_s": 241, "fassung": 1,
                     "ki_hinweis": True, "werkbank": {"wartet": 0, "runde": 3}, **ergebnis},
        "fehler": None, "erinnert_am": None, "verlauf": [{"stand": stand, "zeit": buch.jetzt.isoformat()}]}
    return aid


def _eintraege(herkunft="marketing-video"):
    return fe.offene(herkunft)


def test_video_erzeugt_wird_freigabe_eintrag(buch):
    aid = _video(buch)
    zaehler = _durchgang(buch)
    e = _eintraege()
    assert len(e) == 1 and e[0]["art"] == "marketing_video" and e[0]["quelle_ref"] == aid
    assert e[0]["link"] == f"{BASIS}/marketing/werkbank/{aid}/video"
    assert e[0]["titel"] == "Video: KI im Vertrieb"
    assert e[0]["details"] == {"auftrag": aid, "datei": WB_DATEI, "dauer_s": 241, "fassung": 1}
    assert buch.auftraege[aid]["stand"] == "wartet_freigabe"
    assert buch.auftraege[aid]["ergebnis"]["freigabe"] == e[0]["kennung"]
    assert zaehler == {"abgelaufen": 0, "entwuerfe": 0, "abgeschlossen": 0, "erinnert": 0}


def test_video_zweiter_durchgang_kein_zweiter_eintrag(buch):
    aid = _video(buch)
    _durchgang(buch)
    kennung = buch.auftraege[aid]["ergebnis"]["freigabe"]
    _durchgang(buch)
    # Neustart zwischen Eintrag und Standwechsel: der Auftrag steht noch auf erzeugt.
    buch.auftraege[aid]["stand"] = "erzeugt"
    _durchgang(buch)
    e = _eintraege()
    assert len(e) == 1 and e[0]["kennung"] == kennung and buch.auftraege[aid]["stand"] == "wartet_freigabe"
    assert server._q("select count(*) n from freigabe_eintraege")[0]["n"] == 1


def test_video_freigegeben_macht_fertig(buch):
    aid = _video(buch)
    _durchgang(buch)
    assert _durchgang(buch)["abgeschlossen"] == 0 and buch.auftraege[aid]["stand"] == "wartet_freigabe"
    assert fe.schliessen_kennung(_eintraege()[0]["kennung"], "erledigt", "mira")
    assert _durchgang(buch)["abgeschlossen"] == 1
    assert buch.auftraege[aid]["stand"] == "fertig"


def test_video_verworfen_macht_abgebrochen(buch):
    aid = _video(buch)
    _durchgang(buch)
    assert fe.schliessen_kennung(_eintraege()[0]["kennung"], "verworfen", "mira")
    assert _durchgang(buch)["abgeschlossen"] == 1
    assert buch.auftraege[aid]["stand"] == "abgebrochen"


def test_video_wieder_in_werkbank_schliesst_alten_eintrag(buch):
    aid = _video(buch)
    _durchgang(buch)
    alt = buch.auftraege[aid]["ergebnis"]["freigabe"]
    buch.auftraege[aid]["stand"] = "werkbank"           # Marketing baut das Video neu
    _durchgang(buch)
    z = server._q("select status, geschlossen_von from freigabe_eintraege where kennung = %s", (alt,))[0]
    assert z["status"] == "verworfen" and z["geschlossen_von"] == "auftrag-bote" and _eintraege() == []
    assert buch.auftraege[aid]["stand"] == "werkbank"
    # die neue Fassung: neuer Eintrag mit neuer Kennung
    a = buch.auftraege[aid]
    a["stand"], a["ergebnis"]["datei"], a["ergebnis"]["fassung"] = "erzeugt", "wb-0123abcd-video-f2.mp4", 2
    _durchgang(buch)
    neu = _eintraege()
    assert len(neu) == 1 and neu[0]["kennung"] != alt and neu[0]["details"]["fassung"] == 2
    assert a["ergebnis"]["freigabe"] == neu[0]["kennung"] and a["stand"] == "wartet_freigabe"


def test_video_werkbank_ohne_eintrag_tut_nichts(buch):
    aid = _video(buch, stand="werkbank")
    assert _durchgang(buch) == {"abgelaufen": 0, "entwuerfe": 0, "abgeschlossen": 0, "erinnert": 0}
    assert buch.auftraege[aid]["stand"] == "werkbank"


def test_video_legt_keine_kanal_entwuerfe_an(buch):
    aid = _video(buch)
    _durchgang(buch)
    assert server._q("select count(*) n from drafts where auftrag = %s", (aid,))[0]["n"] == 0
    assert _entwuerfe() == []


def test_video_erinnerung_nach_48h_einmal(buch):
    aid = _video(buch)
    _durchgang(buch)
    assert _durchgang(buch, T0 + timedelta(hours=47))["erinnert"] == 0
    assert _durchgang(buch, T0 + timedelta(hours=49))["erinnert"] == 1
    assert buch.auftraege[aid]["erinnert_am"] is not None
    assert _durchgang(buch, T0 + timedelta(hours=72))["erinnert"] == 0


def test_video_ohne_basisadresse_wird_fehler(buch, monkeypatch):
    monkeypatch.delenv("UI_BASIS_URL")
    aid = _video(buch)
    _durchgang(buch)
    assert buch.auftraege[aid]["stand"] == "fehler" and buch.auftraege[aid]["fehler"] == ab.VIDEO_OHNE_BASIS
    assert _eintraege() == []


@pytest.mark.parametrize("datei", ["", "../media/geheim.mp4", "vid-0123abcd-drei-fehler.mp4",
                                   "wb-0123abcd-video-f1.mov", "wb-0123abcd-video-f1.mp4/../x"])
def test_video_ohne_gueltige_datei_wird_fehler(buch, datei):
    aid = _video(buch, datei=datei)
    _durchgang(buch)
    assert buch.auftraege[aid]["stand"] == "fehler" and buch.auftraege[aid]["fehler"] == ab.VIDEO_OHNE_DATEI
    assert _eintraege() == []


def test_ein_kaputtes_video_haelt_ein_reel_nicht_auf(buch):
    _video(buch, datei="")
    reel = buch.neu()
    _durchgang(buch)
    assert buch.auftraege[reel]["stand"] == "wartet_freigabe"


def test_reel_zweige_unveraendert_neben_einem_video(buch):
    reel, video = buch.neu(), _video(buch)
    zaehler = _durchgang(buch)
    assert zaehler["entwuerfe"] == 2 and len(_entwuerfe()) == 2
    assert all(str(e["auftrag"]) == reel for e in _entwuerfe())
    assert buch.auftraege[video]["stand"] == "wartet_freigabe" and len(_eintraege()) == 1
    assert _eintraege("sales") == [] and _eintraege("marketing") == []
