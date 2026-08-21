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


def test_zwei_schreibweisen_desselben_menschen_sind_ein_eintrag():
    sammel = _sammel()
    _zuordnung()
    _kundenantwort(sammel, SOPHIE_LID, text="Erste", vor_stunden=5)
    _kundenantwort(sammel, SOPHIE_NUMMER, text="Zweite", vor_stunden=2)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert p["eintraege"][0]["absender"] == SOPHIE_NUMMER
    assert p["eintraege"][0]["text_kurz"] == "Zweite"


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
# Registrierung
# ---------------------------------------------------------------------------

def test_signatur_ueberlebt_den_dekorator_und_werkzeug_ist_registriert():
    import inspect
    parameter = inspect.signature(server.eingang_einordnen).parameters
    assert list(parameter) == ["absender", "entscheidung", "lead_id", "telefon"]
    assert all(p.default == "" for p in parameter.values())
    assert server.eingang_einordnen in server.WERKZEUGE
