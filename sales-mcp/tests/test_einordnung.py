"""Vertragstests der Einordnung (Stufe 11, T2–T5) gegen sales_test.

Der Betriebsmodus dieser Stufe: eine eingehende Nachricht wird EINGEORDNET,
nicht beantwortet. Geprueft wird deshalb genau das —

* T2  in welcher Reihenfolge der Absender aufgeloest wird
      (senderPhone -> gespeicherte Zuordnung -> Sammelkontakt),
* T3  dass LID-Seite und Rufnummer-Seite wieder ein Paar finden,
* T4  dass es je Absender GENAU EINE Rueckfrage gibt und „ignorieren"
      dauerhaft raeumt, ohne zu loeschen,
* T5  dass von ignorierten Absendern kein Nachrichtentext mehr gespeichert
      wird.

Wie test_inbox.py reden die Eingangstests HTTP mit dem echten Handler und
signieren ihre Rumpfbytes selbst. Es geht zu keinem Zeitpunkt eine
WhatsApp-Nachricht raus, und es wird kein Webhook registriert.
"""
import hashlib
import hmac
import json
import os
import threading
import urllib.error
import urllib.request

import psycopg
import pytest

# HART, nicht setdefault (wie test_dispatch/test_inbox): eine von aussen
# gesetzte SALES_DB_SCHEMA=sales wuerde die truncate-Fixture auf die echten
# Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("INBOX_WEBHOOK_SECRET", "test-geheimnis-0123456789")
import inbox  # noqa: E402
import server  # noqa: E402

GEHEIMNIS = "test-geheimnis-0123456789"
EIGENE = "4915100000000@c.us"
# Die gemessene LID von Sophie und ihre gemessene Rufnummer (Plan T1).
SOPHIE_LID = "183096603361451@lid"
SOPHIE_NUMMER = "491729186846@c.us"
# Ein ZWEITER Mensch mit einer eigenen LID. Zeigen beide auf dieselbe Nummer,
# hat `_kanon` sie bis zur Fix-Runde zu einer einzigen Identitaet kollabiert
# (Review-Befund H4) — Person B war im Posteingang nie sichtbar.
ZWEITE_LID = "222096603361451@lid"

URL = ""


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(scope="module", autouse=True)
def dienst():
    """Der echte Webhook-Handler auf einem freien Port — kein Mock."""
    httpd = inbox.baue_server(("127.0.0.1", 0))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    global URL
    URL = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield httpd
    httpd.shutdown()


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    inbox.SECRET = GEHEIMNIS
    inbox.UNBEKANNT_LEAD_ID = ""
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = ""
    yield
    server.UNBEKANNT_LEAD_ID = vorher


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead(name="Sophie Beispiel", phone="+49 172 9186846"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _sammel():
    lead = str(server._q(
        "insert into leads (name, source) values "
        "('Unbekannte Eingaenge', 'system') returning id")[0]["id"])
    inbox.UNBEKANNT_LEAD_ID = lead
    server.UNBEKANNT_LEAD_ID = lead
    return lead


def _post(umschlag):
    roh = json.dumps(umschlag, ensure_ascii=False).encode("utf-8")
    kopf = {"Content-Type": "application/json",
            "X-OpenWA-Signature": "sha256=" + hmac.new(
                GEHEIMNIS.encode("utf-8"), roh, hashlib.sha256).hexdigest()}
    anfrage = urllib.request.Request(f"{URL}/webhook", data=roh,
                                     method="POST", headers=kopf)
    try:
        with urllib.request.urlopen(anfrage, timeout=10) as antwort:
            return antwort.status, json.loads(antwort.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _eingang(absender=SOPHIE_LID, text="Hallo, passt Donnerstag?",
             message_id="wa-1", **felder):
    daten = {"id": message_id, "from": absender, "to": EIGENE,
             "chatId": absender, "body": text, "type": "text",
             "timestamp": 1770000000, "fromMe": False, "isGroup": False}
    daten.update(felder)
    return _post({"event": "message.received", "sessionId": "stub",
                  "idempotencyKey": message_id, "data": daten})


def _ausgang(gegenstelle=SOPHIE_LID, text="Donnerstag 15 Uhr passt.",
             message_id="wa-echo-1"):
    daten = {"id": message_id, "from": EIGENE, "to": gegenstelle,
             "chatId": gegenstelle, "body": text, "type": "text",
             "timestamp": 1770000100, "fromMe": True, "isGroup": False}
    return _post({"event": "message.sent", "sessionId": "stub",
                  "idempotencyKey": message_id, "data": daten})


def _zeilen(typ=None):
    if typ:
        return server._q("select lead_id, type, payload, created_at from "
                         "activities where type = %s order by created_at", (typ,))
    return server._q("select lead_id, type, payload, created_at from "
                     "activities order by created_at")


def _kundenantwort(lead, absender, text="Hallo?", vor_stunden=1,
                   message_id=None):
    return str(server._q(
        "insert into activities (lead_id, type, payload, actor, created_at) "
        "values (%s, 'kundenantwort', %s, 'human', "
        "        now() - (%s * interval '1 hour')) returning id",
        (lead, json.dumps({"text": text, "richtung": "eingehend",
                           "absender": absender,
                           "message_id": message_id or f"wa-{absender}-{text}"}),
         vor_stunden))[0]["id"])


def _antwort_raus(lead, empfaenger, vor_stunden=0, typ="nachricht_ausgehend"):
    schluessel = "chat_id" if typ == "versand" else "empfaenger"
    return str(server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "values (%s, %s, %s, now() - (%s * interval '1 hour')) returning id",
        (lead, typ, json.dumps({"richtung": "ausgehend",
                                schluessel: empfaenger}), vor_stunden))
        [0]["id"])


def _zuordnung(kennung=SOPHIE_LID, telefon=SOPHIE_NUMMER, quelle="openwa"):
    return server.lid_zuordnung_speichern(kennung, telefon, quelle, "rufnummer")


def _posteingang(**kw):
    return json.loads(server.posteingang(**kw))


def _einordnen(**kw):
    return json.loads(server.eingang_einordnen(**kw))


# ---------------------------------------------------------------------------
# T2 — die Reihenfolge der Aufloesung
# ---------------------------------------------------------------------------

def test_senderphone_schlaegt_die_gespeicherte_zuordnung():
    """Punkt 1 der Reihenfolge: was OpenWA selbst aufgeloest hat, gilt. Eine
    aeltere Spiegel-Zeile darf das nicht ueberstimmen."""
    lead = _lead()
    _sammel()
    _zuordnung(SOPHIE_LID, "4915199999999@c.us")   # veraltet/falsch
    status, _ = _eingang(senderPhone="491729186846")
    assert status == 200
    zeilen = _zeilen("kundenantwort")
    assert str(zeilen[0]["lead_id"]) == lead
    assert zeilen[0]["payload"]["absender"] == SOPHIE_NUMMER
    assert zeilen[0]["payload"]["kennung_quelle"] == "senderPhone"


def test_gespeicherte_zuordnung_holt_die_lid_zum_richtigen_kontakt():
    """Punkt 2: ohne `senderPhone` entscheidet die Spiegel-Zeile — der Grund,
    warum RESOLVE_LID_TO_PHONE nicht mehr allein tragen muss."""
    lead = _lead()
    _sammel()
    _zuordnung()
    status, _ = _eingang()
    assert status == 200
    zeilen = _zeilen("kundenantwort")
    assert str(zeilen[0]["lead_id"]) == lead
    assert zeilen[0]["payload"]["absender"] == SOPHIE_NUMMER
    assert zeilen[0]["payload"]["kennung_quelle"] == "zuordnung"


def test_unaufgeloeste_lid_wird_niemals_als_rufnummer_gebucht():
    """Punkt 3 und Review-Befund H1: `183…@c.us` sah aus wie eine Rufnummer und
    verleitete dazu, sie als Kontakt anzulegen. Jetzt steht `@lid` da."""
    sammel = _sammel()
    status, _ = _eingang()
    assert status == 200
    zeilen = _zeilen("kundenantwort")
    assert str(zeilen[0]["lead_id"]) == sammel
    assert zeilen[0]["payload"]["absender"] == SOPHIE_LID
    assert zeilen[0]["payload"]["kennung_quelle"] == "lid"


def test_eine_echte_rufnummer_laeuft_unveraendert_durch():
    lead = _lead("Max Testperson", "+491701234567")
    _sammel()
    status, _ = _eingang(absender="491701234567@c.us")
    assert status == 200
    assert str(_zeilen("kundenantwort")[0]["lead_id"]) == lead


def test_ausgehende_richtung_benutzt_dieselbe_zuordnung():
    """Ohne das bliebe die Gegenrichtung eine LID und die Beantwortet-Pruefung
    faende nie ein Paar (Review-Befund M1)."""
    lead = _lead()
    _sammel()
    _zuordnung()
    status, _ = _ausgang()
    assert status == 200
    zeilen = _zeilen("nachricht_ausgehend")
    assert str(zeilen[0]["lead_id"]) == lead
    assert zeilen[0]["payload"]["empfaenger"] == SOPHIE_NUMMER


# ---------------------------------------------------------------------------
# T3 — beide Seiten finden wieder ein Paar
# ---------------------------------------------------------------------------

def test_ohne_zuordnung_bleiben_lid_und_rufnummer_zwei_fremde():
    """Der Ausgangszustand, den T3 behebt — hier absichtlich festgehalten."""
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=1)
    assert _posteingang()["anzahl_unbeantwortet"] == 1


def test_zuordnung_laesst_die_antwort_auf_die_lid_frage_zaehlen():
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=1)
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_auch_umgekehrt_rufnummer_rein_lid_raus():
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_NUMMER, vor_stunden=5)
    _antwort_raus(sammel, SOPHIE_LID, vor_stunden=1)
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_die_alte_attrappe_183_at_c_us_loest_ebenfalls_auf():
    """Bis Stufe 11 wurden LIDs als `183…@c.us` gespeichert. Die Aufloesung
    greift ueber die ZIFFERN, nicht ueber die Domain — sonst blieben genau die
    bestehenden Zeilen aussen vor."""
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, "183096603361451@c.us", vor_stunden=5)
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=1)
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_zwei_schreibweisen_bleiben_zwei_zeilen_und_eine_antwort_raeumt_beide():
    """Bis zur Fix-Runde stand hier
    `test_zwei_schreibweisen_desselben_menschen_sind_ein_eintrag` und pinnte,
    dass `_kanon` beide Schreibweisen zu EINEM Eintrag verschmilzt. Bequem —
    aber dieselbe Verschmelzung kollabierte auch zwei FREMDE Identitaeten,
    sobald zwei LIDs auf dieselbe Nummer zeigten (Review-Befund H4). Die
    GRUPPIERUNG arbeitet deshalb auf den rohen Kennungsziffern: zwei
    Schreibweisen sind zwei Zeilen. Die BEANTWORTET-Pruefung verschmilzt
    weiterhin (T3) — eine Antwort raeumt beide Zeilen ab, der Betreiber muss
    also nicht zweimal antworten."""
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, text="Erste", vor_stunden=5)
    _kundenantwort(sammel, SOPHIE_NUMMER, text="Zweite", vor_stunden=2)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 2
    assert [e["absender"] for e in p["eintraege"]] == [SOPHIE_LID,
                                                       SOPHIE_NUMMER]
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=0)
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_eine_antwort_an_einen_unbekannten_raeumt_die_anderen_nicht_ab():
    """Die absenderscharfe Pruefung bleibt scharf, auch mit Aufloesung."""
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, text="Sophie", vor_stunden=9)
    _kundenantwort(sammel, "4915199999992@c.us", text="Jemand", vor_stunden=3)
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=1)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert p["eintraege"][0]["absender"] == "4915199999992@c.us"


def test_versand_des_dispatchers_zaehlt_ueber_chat_id_ebenso():
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _antwort_raus(sammel, SOPHIE_NUMMER, vor_stunden=1, typ="versand")
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_aufgeloeste_kennung_zeigt_auf_den_kontakt_dem_sie_gehoert():
    """Abnahme 1 in der Form, die ohne DELETE/UPDATE moeglich ist: die alten
    Zeilen bleiben am Sammelkontakt, aber der Betreiber sieht, WER wartet."""
    lead = _lead()
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    eintrag = _posteingang()["eintraege"][0]
    assert str(eintrag["zugeordnet_zu"]) == lead
    assert eintrag["zugeordnet_name"] == "Sophie Beispiel"


# ---------------------------------------------------------------------------
# T4 — genau eine Rueckfrage je Absender
# ---------------------------------------------------------------------------

def test_eine_rueckfrage_je_absender_nicht_je_nachricht():
    sammel = _sammel()
    for i in range(3):
        _kundenantwort(sammel, SOPHIE_LID, text=f"Nachricht {i}",
                       vor_stunden=5 - i)
    antwort = _einordnen()
    assert len(antwort["neu"]) == 1
    eintrag = antwort["neu"][0]
    assert eintrag["absender"] == SOPHIE_LID
    assert eintrag["anzahl_nachrichten"] == 3
    assert "wer ist das?" in eintrag["frage"]
    assert "Nachricht 2" in eintrag["frage"]     # die juengste wird zitiert
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.ABSENDER_RUECKFRAGE,))[0]["n"] == 1


def test_der_zweite_aufruf_fragt_nicht_noch_einmal():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)
    assert len(_einordnen()["neu"]) == 1
    zweite = _einordnen()
    assert zweite["neu"] == []
    assert [e["absender"] for e in zweite["bereits_gefragt"]] == [SOPHIE_LID]
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.ABSENDER_RUECKFRAGE,))[0]["n"] == 1


def test_jeder_absender_bekommt_seine_eigene_frage():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, text="Sophie", vor_stunden=5)
    _kundenantwort(sammel, "4915199999992@c.us", text="Jemand", vor_stunden=3)
    assert len(_einordnen()["neu"]) == 2


def test_wer_schon_einem_kontakt_gehoert_wird_nicht_gefragt():
    lead = _lead()
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID)
    antwort = _einordnen()
    assert antwort["neu"] == []
    assert str(antwort["aufgeloest"][0]["lead_id"]) == lead
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.ABSENDER_RUECKFRAGE,))[0]["n"] == 0


def test_zuordnen_zu_einem_bestehenden_kontakt_routet_die_naechste_nachricht():
    lead = _lead()
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
                         lead_id=lead)
    assert antwort["zugeordnet"]["telefon"] == SOPHIE_NUMMER
    assert antwort["zugeordnet"]["kontakt"] == "Sophie Beispiel"
    status, _ = _eingang(message_id="wa-danach")
    assert status == 200
    danach = [z for z in _zeilen("kundenantwort")
              if z["payload"]["message_id"] == "wa-danach"]
    assert str(danach[0]["lead_id"]) == lead


def test_zuordnen_ueber_eine_nummer_geht_auch_ohne_kontakt():
    _sammel()
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
                         telefon="+49 172 9186846")
    assert antwort["zugeordnet"]["telefon"] == SOPHIE_NUMMER
    assert server.lid_telefon(SOPHIE_LID) == SOPHIE_NUMMER


def test_eine_falsche_zuordnung_laesst_sich_korrigieren():
    """Geschluesselt wird auf die uebergebene Kennung, nicht auf ihre schon
    aufgeloeste Form — sonst entstuende eine Zuordnung Nummer->Nummer und die
    LID zeigte weiter auf die alte Nummer."""
    _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
               telefon="+4915199999999")
    assert server.lid_telefon(SOPHIE_LID) == "4915199999999@c.us"
    _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
               telefon="+49 172 9186846")
    assert server.lid_telefon(SOPHIE_LID) == SOPHIE_NUMMER


def test_zuordnen_ohne_ziel_ist_ein_fehler_und_kein_treffer_ins_blaue():
    _sammel()
    assert "fehler" in _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen")


def test_zuordnen_zu_einem_kontakt_ohne_nummer_sagt_was_zu_tun_ist():
    ohne = _lead("Ohne Nummer", None)
    _sammel()
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
                         lead_id=ohne)
    assert "kontakt_aktualisieren" in antwort["fehler"]
    assert server.lid_telefon(SOPHIE_LID) == ""


def test_unbekannte_entscheidung_wird_abgewiesen():
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="loeschen")
    assert "fehler" in antwort and "zuordnen" in antwort["fehler"]


def test_ignorieren_raeumt_den_posteingang_ohne_delete():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    vorher = server._q("select count(*) as n from activities")[0]["n"]
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    assert antwort["geloescht"] is False
    assert _posteingang()["anzahl_unbeantwortet"] == 0
    # Nichts weg, eine Zeile dazu: das Gegen-Ereignis.
    nachher = server._q("select count(*) as n from activities")[0]["n"]
    assert nachher == vorher + 1
    assert server._q("select count(*) as n from activities "
                     "where type = 'kundenantwort'")[0]["n"] == 1


def test_ignorierte_absender_stehen_in_keiner_rueckfrage():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    antwort = _einordnen()
    assert antwort["neu"] == [] and antwort["bereits_gefragt"] == []


def test_beachten_nimmt_das_ignorieren_zurueck():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    assert _posteingang()["anzahl_unbeantwortet"] == 0
    _einordnen(absender=SOPHIE_LID, entscheidung="beachten")
    assert _posteingang()["anzahl_unbeantwortet"] == 1


def test_zuordnen_hebt_ein_ignorieren_auf():
    """Sonst bliebe der eben zugeordnete Kontakt unsichtbar."""
    lead = _lead()
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="zuordnen",
                         lead_id=lead)
    assert antwort["ignorieren_zurueckgenommen"] is True
    assert server.absender_ist_ignoriert(SOPHIE_LID) is False


def test_ignorieren_greift_auch_nach_der_aufloesung_noch():
    """Der Betreiber hat `183…@lid` ignoriert; OpenWA liefert spaeter die
    Nummer. Ohne die Bruecke ueber die Zuordnung kaeme derselbe Mensch als
    neuer Absender zurueck."""
    sammel = _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    _zuordnung()
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is True
    _kundenantwort(sammel, SOPHIE_NUMMER, vor_stunden=5)
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_digest_zaehlt_die_unbekannten_ohne_zu_fragen():
    """Der Digest ist eine Ansage. Wuerde er beanspruchen, entstuenden
    Rueckfragen, die niemand gestellt hat."""
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)
    block = json.loads(server.digest())["unbekannte_absender"]
    assert block["anzahl_neu"] == 1 and block["anzahl_gefragt"] == 0
    assert "eingang_einordnen" in block["hinweis"]
    assert server._q("select count(*) as n from activities where type = %s",
                     (server.ABSENDER_RUECKFRAGE,))[0]["n"] == 0


def test_ohne_sammelkontakt_bleibt_die_einordnung_lesbar():
    server.UNBEKANNT_LEAD_ID = ""
    antwort = _einordnen()
    assert antwort["neu"] == [] and "fehler" not in antwort


# ---------------------------------------------------------------------------
# T5 — von ignorierten Absendern wird kein Text mehr gespeichert
# ---------------------------------------------------------------------------

def test_vom_ignorierten_absender_bleibt_nur_die_tatsache():
    sammel = _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    status, antwort = _eingang(text="Privates aus dem Freundeskreis")
    assert status == 200 and antwort["typ"] == server.EINGANG_IGNORIERT
    zeilen = _zeilen(server.EINGANG_IGNORIERT)
    assert len(zeilen) == 1
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["text"] == "" and nutzlast["ohne_text"] is True
    assert nutzlast["absender"] == SOPHIE_LID
    assert nutzlast["message_id"] == "wa-1"
    assert _zeilen("kundenantwort") == []
    # Der Text steht auch sonst nirgends.
    assert "Privates" not in json.dumps(
        [z["payload"] for z in _zeilen()], ensure_ascii=False)
    assert str(zeilen[0]["lead_id"]) == sammel


def test_wiederholte_zustellung_erzeugt_auch_ignoriert_keine_zweite_zeile():
    """OpenWA wiederholt bei 5xx/Timeout — deshalb wird die Tatsache gebucht
    und nicht einfach verworfen."""
    _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    _eingang()
    status, antwort = _eingang()
    assert status == 200 and antwort.get("doppelt") is True
    assert len(_zeilen(server.EINGANG_IGNORIERT)) == 1


def test_ein_nicht_ignorierter_absender_behaelt_seinen_text():
    _sammel()
    _eingang(text="Bitte melden Sie sich")
    assert _zeilen("kundenantwort")[0]["payload"]["text"] == \
        "Bitte melden Sie sich"


def test_ignorierte_eingaenge_tauchen_im_posteingang_nicht_auf():
    _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    _eingang()
    assert _posteingang()["anzahl_unbeantwortet"] == 0


# ---------------------------------------------------------------------------
# H2 — die EIGENE Haelfte eines ignorierten Chats ist genauso sensibel
#
# `_ausgehend` hatte keine Ignoriert-Pruefung; nur `_eingehend`. Gemessen:
# Absender ignoriert -> eigene Nachricht in denselben Chat -> volle
# `nachricht_ausgehend` mit Text in `activities`. Damit war die Zusage aus T5
# („von einem ignorierten Absender wird kein Text mehr gespeichert") nur zur
# Haelfte eingeloest — bei einem privaten Chat schreibt der Betreiber selbst
# das Private.
# ---------------------------------------------------------------------------

def test_vom_ignorierten_chat_bleibt_auch_die_eigene_haelfte_ohne_text():
    sammel = _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    status, antwort = _ausgang(text="Bis Samstag beim Grillen, Gruss an Anna!")
    assert status == 200 and antwort["typ"] == server.AUSGANG_IGNORIERT
    zeilen = _zeilen(server.AUSGANG_IGNORIERT)
    assert len(zeilen) == 1
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["text"] == "" and nutzlast["ohne_text"] is True
    assert nutzlast["richtung"] == "ausgehend"
    assert nutzlast["empfaenger"] == SOPHIE_LID
    assert nutzlast["message_id"] == "wa-echo-1"
    assert str(zeilen[0]["lead_id"]) == sammel
    assert _zeilen("nachricht_ausgehend") == []
    # Der Text steht auch sonst nirgends.
    assert "Grillen" not in json.dumps(
        [z["payload"] for z in _zeilen()], ensure_ascii=False)


def test_der_textlose_ausgang_bleibt_dedupbar():
    """Gegenstueck zu `eingang_ignoriert`: OpenWA wiederholt Zustellungen,
    deshalb wird die Tatsache gebucht statt die Nachricht zu verwerfen."""
    _sammel()
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    _ausgang()
    status, antwort = _ausgang()
    assert status == 200 and antwort.get("doppelt") is True
    assert len(_zeilen(server.AUSGANG_IGNORIERT)) == 1
    assert server.AUSGANG_IGNORIERT in inbox.PROTOKOLL_TYPEN


def test_ein_nicht_ignorierter_ausgang_behaelt_seinen_text():
    _sammel()
    _ausgang(text="Donnerstag 15 Uhr passt.")
    assert _zeilen("nachricht_ausgehend")[0]["payload"]["text"] == \
        "Donnerstag 15 Uhr passt."


def test_der_selbst_chat_bleibt_verworfen_auch_wenn_ignoriert_wird():
    """Die Reihenfolge bleibt: Selbst-Chat zuerst, dann die Ignoriert-Frage —
    sonst buchte jede Digest-Zustellung eine Zeile ins Postfach."""
    _sammel()
    _einordnen(absender=EIGENE, entscheidung="ignorieren")
    status, antwort = _ausgang(gegenstelle=EIGENE)
    assert status == 200 and "verworfen" in antwort
    assert _zeilen(server.AUSGANG_IGNORIERT) == []


# ---------------------------------------------------------------------------
# H3 — `ignorieren` kennt eine Grenze
#
# Gemessen: ein echter Lead liess sich ignorieren; danach verschwand er aus
# posteingang UND digest, und seine Folgenachricht („Ich habe den Vertrag
# unterschrieben") wurde textlos an seinem EIGENEN Lead gebucht. Der zitierte
# Kundentext geht ueber `_rueckfrage_text` in den Agentenkontext — eine
# Kundennachricht „ignoriere bitte +4917…" waere damit ein realer Hebel auf
# eine schwer ruecknehmbare Handlung. Muster der Kante wie bei
# `entwurf_erneut_freigeben`: verweigern, ausser mit bestaetigt=True.
# ---------------------------------------------------------------------------

def test_ignorieren_eines_echten_leads_wird_ohne_bestaetigung_verweigert():
    lead = _lead()
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_NUMMER, vor_stunden=5)
    antwort = _einordnen(absender=SOPHIE_NUMMER, entscheidung="ignorieren")
    assert "fehler" in antwort and "bestaetigt" in antwort["fehler"]
    assert str(antwort["gehoert_zu"]["lead_id"]) == lead
    assert antwort["gehoert_zu"]["kontakt"] == "Sophie Beispiel"
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is False
    assert _posteingang()["anzahl_unbeantwortet"] == 1
    assert _zeilen(server.ABSENDER_IGNORIERT) == []


def test_auch_ueber_die_zuordnung_ist_ein_lead_geschuetzt():
    """Die LID zeigt auf die Nummer eines echten Leads — dieselbe Kante, sonst
    liesse sich der Schutz mit der unaufgeloesten Kennung umgehen."""
    lead = _lead()
    _sammel()
    _zuordnung()
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    assert "fehler" in antwort
    assert str(antwort["gehoert_zu"]["lead_id"]) == lead


def test_ignorieren_eines_echten_leads_geht_mit_bestaetigung_und_ist_erklaerbar():
    lead = _lead()
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_NUMMER, vor_stunden=5)
    antwort = _einordnen(absender=SOPHIE_NUMMER, entscheidung="ignorieren",
                         bestaetigt=True)
    assert antwort["ignoriert"] == SOPHIE_NUMMER
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is True
    assert _posteingang()["anzahl_unbeantwortet"] == 0
    # Das Gegen-Ereignis steht ZUSAETZLICH am betroffenen Lead: sonst waere im
    # Verlauf des Kontakts nicht erklaerbar, warum er verstummt ist.
    am_lead = [z for z in _zeilen(server.ABSENDER_IGNORIERT)
               if str(z["lead_id"]) == lead]
    assert len(am_lead) == 1
    assert am_lead[0]["payload"]["absender"] == SOPHIE_NUMMER


def test_beachten_holt_einen_lead_ohne_bestaetigung_zurueck():
    """Die Kante steht nur vor der schwer ruecknehmbaren Richtung."""
    lead = _lead()
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_NUMMER, vor_stunden=5)
    _einordnen(absender=SOPHIE_NUMMER, entscheidung="ignorieren",
               bestaetigt=True)
    antwort = _einordnen(absender=SOPHIE_NUMMER, entscheidung="beachten")
    assert antwort["beachtet"] == SOPHIE_NUMMER
    assert _posteingang()["anzahl_unbeantwortet"] == 1
    assert [str(z["lead_id"]) for z in _zeilen(server.ABSENDER_BEACHTET)
            if str(z["lead_id"]) == lead]


def test_eine_kennung_ohne_lead_bleibt_ohne_bestaetigung_ignorierbar():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    assert "ignoriert" in _einordnen(absender=SOPHIE_LID,
                                     entscheidung="ignorieren")


# ---------------------------------------------------------------------------
# H4 — `_kanon` kollabierte fremde Identitaeten
#
# Gemessen: zwei verschiedene LIDs, beide auf dieselbe Nummer gemappt -> EIN
# Posteingangseintrag, EINE Rueckfrage; `ignorieren` der einen liess auch die
# andere verschwinden, deren naechste Nachricht wurde textlos gebucht. Person B
# war nie sichtbar. `_kanon` gilt seitdem nur noch dort, wo Verschmelzen
# gewollt ist: in der T3-Beantwortet-Pruefung.
# ---------------------------------------------------------------------------

def _zwei_lids_eine_nummer(sammel):
    _zuordnung(SOPHIE_LID, SOPHIE_NUMMER)
    _zuordnung(ZWEITE_LID, SOPHIE_NUMMER)
    _kundenantwort(sammel, SOPHIE_LID, text="A schreibt", vor_stunden=5)
    _kundenantwort(sammel, ZWEITE_LID, text="B schreibt", vor_stunden=4)


def test_zwei_lids_auf_dieselbe_nummer_bleiben_zwei_eintraege():
    sammel = _sammel()
    _zwei_lids_eine_nummer(sammel)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 2
    assert [e["absender"] for e in p["eintraege"]] == [SOPHIE_LID, ZWEITE_LID]


def test_dieselben_ziffern_in_zwei_domains_bleiben_eine_zeile():
    """Gruppiert wird auf den ZIFFERN, nicht auf der ganzen Zeichenkette:
    die Altlast `183…@c.us` (die Attrappe aus Befund H1) und `183…@lid` sind
    dieselbe Kennung, die Domain ist Anzeige. Sonst haette der H4-Fix die
    Migrationsphase mit Doppelzeilen zugestellt."""
    sammel = _sammel()
    _kundenantwort(sammel, "183096603361451@c.us", text="Alt", vor_stunden=5)
    _kundenantwort(sammel, SOPHIE_LID, text="Neu", vor_stunden=2)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert p["eintraege"][0]["absender"] == SOPHIE_LID   # juengste Schreibweise
    assert p["eintraege"][0]["text_kurz"] == "Neu"
    assert len(_einordnen()["neu"]) == 1


def test_zwei_lids_auf_dieselbe_nummer_bekommen_zwei_rueckfragen():
    sammel = _sammel()
    _zwei_lids_eine_nummer(sammel)
    antwort = _einordnen()
    assert sorted(e["absender"] for e in antwort["neu"]) == sorted(
        [SOPHIE_LID, ZWEITE_LID])


def test_ignorieren_der_einen_lid_laesst_die_andere_stehen():
    sammel = _sammel()
    _zwei_lids_eine_nummer(sammel)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    p = _posteingang()
    assert [e["absender"] for e in p["eintraege"]] == [ZWEITE_LID]
    assert [e["absender"] for e in _einordnen()["neu"]] == [ZWEITE_LID]


def test_die_nachricht_der_zweiten_lid_behaelt_ihren_text():
    """Der Buchungspfad fragt die ROHE Kennung. Sonst wurde B textlos gebucht,
    weil A ignoriert war und beide auf dieselbe Nummer zeigten."""
    _sammel()
    _zuordnung(SOPHIE_LID, SOPHIE_NUMMER)
    _zuordnung(ZWEITE_LID, SOPHIE_NUMMER)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    status, _ = _eingang(absender=ZWEITE_LID, text="Ich bin jemand anderes")
    assert status == 200
    assert _zeilen("kundenantwort")[0]["payload"]["text"] == \
        "Ich bin jemand anderes"
    assert _zeilen(server.EINGANG_IGNORIERT) == []


def test_absender_ist_ignoriert_und_der_buchungspfad_sagen_dasselbe():
    """Zweiter Teil des Befunds: `absender_ist_ignoriert('222…@lid')` lieferte
    False, waehrend der Buchungspfad B als ignoriert behandelte. Und die
    Bruecke Nummer->LID traegt nur, wenn GENAU EINE LID Anspruch erhebt."""
    _sammel()
    _zuordnung(SOPHIE_LID, SOPHIE_NUMMER)
    _zuordnung(ZWEITE_LID, SOPHIE_NUMMER)
    _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    assert server.absender_ist_ignoriert(SOPHIE_LID) is True
    assert server.absender_ist_ignoriert(ZWEITE_LID) is False
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is False


def test_ignorieren_speichert_die_genannte_kennung_nicht_die_nummer_dahinter():
    """Sonst hiesse „ignoriere 183…@lid" in der Datenbank „ignoriere jeden,
    der auf 4917… zeigt" — und traefe damit auch Person B."""
    _sammel()
    _zuordnung()
    antwort = _einordnen(absender=SOPHIE_LID, entscheidung="ignorieren")
    assert antwort["ignoriert"] == SOPHIE_LID
    assert _zeilen(server.ABSENDER_IGNORIERT)[0]["payload"]["absender"] == \
        SOPHIE_LID


# ---------------------------------------------------------------------------
# M7 — der Rohwert geht durch nummern.py, statt an ihm vorbei
# ---------------------------------------------------------------------------

def test_eine_jid_mit_buchstaben_landet_nicht_im_verlauf_eines_fremden():
    """`"+" + _ziffern("49a17b29186846@c.us")` ergab genau Sophies Nummer —
    eine unsaubere Kennung buchte in die Historie eines echten Kunden."""
    lead = _lead()
    sammel = _sammel()
    status, _ = _eingang(absender="49a17b29186846@c.us")
    assert status == 200
    zeile = _zeilen("kundenantwort")[0]
    assert str(zeile["lead_id"]) == sammel != lead
    assert zeile["payload"]["unbekannter_absender"] is True


def test_eine_jid_in_nationaler_schreibweise_wird_nicht_zurechtgebogen():
    """`"+0170123456"` lief als internationale Schreibweise durch und ergab die
    Chat-ID `0170123456@c.us` — eine Nummer, die es nicht gibt. Sichtbar wird
    das an `kennung_quelle`: es steht nur, wenn nummern.py zugestimmt hat."""
    _sammel()
    status, _ = _eingang(absender="0170123456@c.us")
    assert status == 200
    nutzlast = _zeilen("kundenantwort")[0]["payload"]
    assert nutzlast["unbekannter_absender"] is True
    assert "kennung_quelle" not in nutzlast


def test_ein_unsauberes_senderphone_faellt_auf_die_naechste_stufe_durch():
    """Es ist ein Hinweis von OpenWA, keine Wahrheit — und die Kennung selbst
    kennen wir immer noch."""
    sammel = _sammel()
    status, _ = _eingang(senderPhone="49a17b29186846")
    assert status == 200
    zeile = _zeilen("kundenantwort")[0]
    assert str(zeile["lead_id"]) == sammel
    assert zeile["payload"]["absender"] == SOPHIE_LID
    assert zeile["payload"]["kennung_quelle"] == "lid"


# ---------------------------------------------------------------------------
# M8 / M10 / N14
# ---------------------------------------------------------------------------

def test_ein_fehler_beim_einordnen_macht_nicht_den_ganzen_digest_kaputt(
        monkeypatch):
    """`_einzuordnende()` war die einzige ungesicherte Teilquelle des Digests
    (Review-Befund M8) — ein Fehler dort machte den GANZEN Digest zur
    Fehlermeldung. Gleiche Haertung wie beim Posteingang darueber."""
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)

    def kaputt(*_a, **_kw):
        raise psycopg.errors.UndefinedColumn("payload->>'absender' fehlt")

    monkeypatch.setattr(server, "_einzuordnende", kaputt)
    antwort = json.loads(server.digest())
    assert "fehler" not in antwort
    assert antwort["unbekannte_absender"]["anzahl_neu"] is None
    assert "nicht lesbar" in antwort["unbekannte_absender"]["hinweis"].lower()
    assert antwort["unbeantwortete_eingaenge"]["anzahl"] == 1


def _in_einer_transaktion(zeilen):
    """Mehrere activities-Zeilen in EINER Transaktion — sie tragen damit
    denselben `created_at` (`now()` ist Transaktionszeit)."""
    with server.pool.connection() as conn:
        with conn.cursor() as cur:
            for typ, nutzlast in zeilen:
                cur.execute(
                    "insert into activities (lead_id, type, payload, actor) "
                    "values (%s, %s, %s, 'agent')",
                    (server.UNBEKANNT_LEAD_ID or None, typ,
                     json.dumps(nutzlast)))


def test_zwei_zuordnungen_einer_transaktion_sind_entscheidbar():
    """Review-Befund M10: `order by created_at desc` ohne zweites Kriterium —
    zwei Zeilen einer Transaktion sind ununterscheidbar und „juengste gewinnt"
    ist ein Muenzwurf. Entschieden wird ueber den GESCHRIEBENEN Zeitstempel."""
    _sammel()
    _in_einer_transaktion([
        (server.LID_ZUORDNUNG,
         {"lid": "183096603361451", "telefon": "4915199999991@c.us",
          "quelle": "test", "typ": "rufnummer",
          "gesehen_am": "2026-08-20T10:00:00+00:00"}),
        (server.LID_ZUORDNUNG,
         {"lid": "183096603361451", "telefon": SOPHIE_NUMMER,
          "quelle": "test", "typ": "rufnummer",
          "gesehen_am": "2026-08-20T11:00:00+00:00"}),
    ])
    assert server.lid_telefon(SOPHIE_LID) == SOPHIE_NUMMER


def test_zwei_absender_ereignisse_einer_transaktion_sind_entscheidbar():
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID, vor_stunden=5)
    _in_einer_transaktion([
        (server.ABSENDER_BEACHTET,
         {"absender": SOPHIE_LID, "gesetzt_am": "2026-08-20T10:00:00+00:00"}),
        (server.ABSENDER_IGNORIERT,
         {"absender": SOPHIE_LID, "gesetzt_am": "2026-08-20T11:00:00+00:00"}),
    ])
    assert server.absender_ist_ignoriert(SOPHIE_LID) is True
    assert _posteingang()["anzahl_unbeantwortet"] == 0


@pytest.mark.parametrize("eingabe, erwartet", [
    ("+491701234567", "491701234567@c.us"),
    ("+49 170 1234567", "491701234567@c.us"),
    ("0049 170 1234567", "491701234567@c.us"),
    ("491701234567@c.us", "491701234567@c.us"),
    ("491701234567:12@s.whatsapp.net", "491701234567@c.us"),
    ("183096603361451@lid", "183096603361451@lid"),
    # Blanke Ziffern ohne Domain: nummern.py entscheidet, und dort gilt
    # `49…` als deutsche Nummer, alles andere bringt seine Vorwahl nicht mit.
    ("183096603361451", "183096603361451@lid"),
    ("", ""),
])
def test_lid_kanonisch_etikettiert_nur_echte_lids_als_lid(eingabe, erwartet):
    """Review-Befund N14: `lid_kanonisch('+491701234567')` lieferte
    `491701234567@lid` — an eine echte Rufnummer klebte die UI damit
    „LID-Pseudo-Kennung, keine Rufnummer"."""
    assert server.lid_kanonisch(eingabe) == erwartet


def test_lid_kanonisch_loest_weiterhin_auf_wenn_eine_zuordnung_dasteht():
    _sammel()
    _zuordnung()
    assert server.lid_kanonisch(SOPHIE_LID) == SOPHIE_NUMMER


# ---------------------------------------------------------------------------
# Registrierung
# ---------------------------------------------------------------------------

def test_signatur_ueberlebt_den_dekorator_und_werkzeug_ist_registriert():
    import inspect
    parameter = inspect.signature(server.eingang_einordnen).parameters
    assert list(parameter) == ["absender", "entscheidung", "lead_id",
                               "telefon", "bestaetigt"]
    assert all(p.default == "" for name, p in parameter.items()
               if name != "bestaetigt")
    assert parameter["bestaetigt"].default is False
    assert server.eingang_einordnen in server.WERKZEUGE


# ---------------------------------------------------------------------------
# Eine Zuordnung ergaenzt eine Nummer — sie ueberstimmt sie nicht (23.09.2026)
# ---------------------------------------------------------------------------

IVAN_NEU = "491791714185@c.us"
IVAN_ALT = "4917688014635@c.us"


def test_eine_veraltete_zuordnung_macht_aus_einem_kontakt_keinen_fremden():
    """Der vom Betreiber gemeldete Fall, gemessen im laufenden Betrieb.

    Am 01.09.2026 hat er gesagt: „491791714185 gehoert zu dem Kontakt mit
    4917688014635" — damals stand die alte Nummer am Lead. Am 22.09.2026
    wurde die NEUE Nummer an den Lead geschrieben; seither zeigt dieselbe
    Zuordnung auf eine Nummer, die niemand mehr hat.

    Weil jeder Aufrufer ueber `lid_kanonisch` fragte — die Zuordnung ERSETZT
    die Kennung, statt fuer sie einzuspringen — stand der Kontakt danach unter
    seiner EIGENEN, am Lead stehenden Nummer wieder in der Einordnungsliste.
    Gemessen am 23.09.2026 gegen den laufenden Dienst:

        direkt              -> Ivan, +491791714185
        ueber lid_kanonisch -> 4917688014635@c.us -> None
    """
    lead = _lead("Ivan", "+491791714185")
    sammel = _sammel()
    _zuordnung(IVAN_NEU, IVAN_ALT)
    _kundenantwort(sammel, IVAN_NEU, text="Bin dabei")

    koerbe = _einordnen()
    offen = [e["kennung"] for e in koerbe["neu"] + koerbe["bereits_gefragt"]]
    assert offen == [], f"nichts einzuordnen — der Kontakt steht fest: {offen}"
    assert [e.get("kontakt") for e in koerbe["aufgeloest"]] == ["Ivan"]
    assert str(koerbe["aufgeloest"][0]["lead_id"]) == lead


def test_ignorieren_bleibt_verweigert_wenn_die_zuordnung_ins_leere_zeigt():
    """Die Schutzkante aus Review-Befund H3 haengt an derselben Frage.

    Sie verweigert `ignorieren`, wenn die Kennung einem echten Kontakt gehoert
    — und stellte diese Frage bis zum 23.09.2026 ebenfalls nur ueber die
    aufgeloeste Form. Eine veraltete Zuordnung machte damit nicht bloss die
    Liste falsch, sondern oeffnete die Kante: der Kontakt haette ohne
    `bestaetigt=True` stillgelegt werden koennen, und von seinen Nachrichten
    waere danach kein Wort mehr gespeichert worden.
    """
    _lead("Ivan", "+491791714185")
    sammel = _sammel()
    _zuordnung(IVAN_NEU, IVAN_ALT)
    _kundenantwort(sammel, IVAN_NEU)

    antwort = _einordnen(absender=IVAN_NEU, entscheidung="ignorieren")
    assert antwort.get("ignoriert") is None
    assert "fehler" in antwort and "Ivan" in antwort["fehler"]
    assert antwort["gehoert_zu"]["kontakt"] == "Ivan"


def test_eine_LID_ohne_zuordnung_bleibt_unveraendert_eine_rueckfrage():
    """Die Gegenprobe: an dem, was die Aufloesung wirklich braucht, aendert
    sich nichts. Eine `@lid` ist keine Rufnummer — ohne Zuordnung findet sie
    keinen Kontakt und wird gefragt, nicht geraten."""
    _lead("Sophie Beispiel", "+49 172 9186846")
    sammel = _sammel()
    _kundenantwort(sammel, SOPHIE_LID)
    koerbe = _einordnen()
    assert [e["kennung"] for e in koerbe["neu"]] == [server.lid.ziffern(SOPHIE_LID)]
    assert koerbe["aufgeloest"] == []

