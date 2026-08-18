"""Vertragstests des Webhook-Eingangs gegen sales_test + echte HTTP-Aufrufe.

Wie test_dispatch.py laeuft die Suite NIE gegen `sales`. Gepruefte Sicht ist
die eines fremden Absenders: die Tests reden HTTP mit dem echten Handler
(`http.server`-Thread auf einem vom Betriebssystem vergebenen Port) und
signieren ihre Rumpfbytes selbst — genau so, wie OpenWA es tut
(HMAC-SHA256 ueber den rohen Rumpf, Header `X-OpenWA-Signature`,
Wert `sha256=<hex>`; gemessen in
openwa/upstream/src/modules/webhook/webhook-delivery.service.ts).

Es geht in diesen Tests zu keinem Zeitpunkt eine WhatsApp-Nachricht raus und
es wird kein echter Webhook registriert.
"""
import hashlib
import hmac
import json
import logging
import os
import threading
import urllib.error
import urllib.request

import psycopg
import pytest

# HART, nicht setdefault (wie test_werkzeuge/test_dispatch): eine von aussen
# gesetzte SALES_DB_SCHEMA=sales wuerde die autouse-Fixture unten auf die
# echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
# Muss VOR dem Import stehen: inbox.py liest das Geheimnis beim Import.
os.environ.setdefault("INBOX_WEBHOOK_SECRET", "test-geheimnis-0123456789")
import inbox  # noqa: E402
import server  # noqa: E402

GEHEIMNIS = "test-geheimnis-0123456789"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(scope="module", autouse=True)
def dienst():
    """Der echte Handler auf einem freien Port — kein Mock des Verhaltens."""
    httpd = inbox.baue_server(("127.0.0.1", 0))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    global URL
    URL = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield httpd
    httpd.shutdown()


URL = ""


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    inbox.SECRET = GEHEIMNIS
    inbox.UNBEKANNT_LEAD_ID = ""
    inbox.fehlversuche_zuruecksetzen()
    yield


class _Mitschnitt(logging.Handler):
    """Eigener Handler am Modul-Logger — `inbox.LOG` hat propagate=False."""

    def __init__(self):
        super().__init__()
        self.saetze = []

    def emit(self, record):
        self.saetze.append(record)

    def texte(self):
        return [s.getMessage() for s in self.saetze]

    def __enter__(self):
        inbox.LOG.addHandler(self)
        return self

    def __exit__(self, *_):
        inbox.LOG.removeHandler(self)
        return False


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead(name="Max Testperson", phone="+49 170 1234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _sammel_lead():
    lead = _lead("Unbekannte Eingaenge", None)
    inbox.UNBEKANNT_LEAD_ID = lead
    return lead


def _ereignis(**felder):
    """Ein `message.received`-Umschlag in der gemessenen OpenWA-Form."""
    daten = {"id": "wa-nachricht-1", "from": "491701234567@c.us",
             "to": "4915100000000@c.us", "chatId": "491701234567@c.us",
             "body": "Hallo, passt Donnerstag?", "type": "text",
             "timestamp": 1770000000, "fromMe": False, "isGroup": False,
             "kind": "individual"}
    daten.update(felder)
    return {"event": "message.received",
            "timestamp": "2026-08-18T20:00:00.000Z",
            "sessionId": "stub-session", "idempotencyKey": "idem-1",
            "deliveryId": "lieferung-1", "data": daten}


def _signiere(roh: bytes, geheimnis: str = GEHEIMNIS) -> str:
    return "sha256=" + hmac.new(geheimnis.encode("utf-8"), roh,
                                hashlib.sha256).hexdigest()


def _post(umschlag=None, *, roh=None, signatur=None, pfad="/webhook",
          methode="POST", kopfzeilen=None):
    """Schickt einen echten HTTP-Aufruf und gibt (status, antwort-dict) zurueck."""
    if roh is None:
        roh = json.dumps(umschlag, ensure_ascii=False).encode("utf-8")
    kopf = {"Content-Type": "application/json",
            "User-Agent": "OpenWA-Webhook/1.0.0",
            "X-OpenWA-Event": "message.received"}
    if signatur is not False:
        kopf["X-OpenWA-Signature"] = signatur or _signiere(roh)
    kopf.update(kopfzeilen or {})
    anfrage = urllib.request.Request(f"{URL}{pfad}", data=roh, method=methode,
                                     headers=kopf)
    try:
        with urllib.request.urlopen(anfrage, timeout=10) as antwort:
            return antwort.status, json.loads(antwort.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _aktivitaeten(typ="kundenantwort"):
    return server._q(
        "select lead_id, payload, actor from activities where type = %s "
        "order by created_at", (typ,))


# ---------------------------------------------------------------------------
# Signatur — die Kante, an der alles haengt
# ---------------------------------------------------------------------------

def test_gueltige_signatur_legt_kundenantwort_beim_richtigen_lead_an():
    lead = _lead()
    status, antwort = _post(_ereignis())
    assert status == 200, antwort
    assert antwort["gespeichert"] is True
    zeilen = _aktivitaeten()
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == lead
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["richtung"] == "eingehend"
    assert nutzlast["message_id"] == "wa-nachricht-1"
    assert nutzlast["text"] == "Hallo, passt Donnerstag?"
    assert nutzlast["absender"] == "491701234567@c.us"
    assert nutzlast["unbekannter_absender"] is False


def test_falsche_signatur_gibt_401_und_schreibt_nichts():
    _lead()
    status, antwort = _post(_ereignis(), signatur="sha256=" + "00" * 32)
    assert status == 401
    assert "fehler" in antwort
    assert _aktivitaeten() == []


def test_fehlender_signaturkopf_gibt_401():
    _lead()
    status, _ = _post(_ereignis(), signatur=False)
    assert status == 401
    assert _aktivitaeten() == []


def test_signatur_mit_falschem_geheimnis_gibt_401():
    _lead()
    roh = json.dumps(_ereignis()).encode("utf-8")
    status, _ = _post(roh=roh, signatur=_signiere(roh, "anderes-geheimnis-xy"))
    assert status == 401
    assert _aktivitaeten() == []


def test_veraenderter_rumpf_unter_alter_signatur_gibt_401():
    """Replay mit manipuliertem Text: die Signatur deckt den ROHEN Rumpf."""
    _lead()
    original = json.dumps(_ereignis()).encode("utf-8")
    signatur = _signiere(original)
    veraendert = json.dumps(_ereignis(body="Bitte 5000 EUR ueberweisen")).encode()
    status, _ = _post(roh=veraendert, signatur=signatur)
    assert status == 401
    assert _aktivitaeten() == []


def test_signaturpruefung_laeuft_vor_dem_parsen():
    """Kaputtes JSON + falsche Signatur -> 401, nicht 400.

    Beweist die Reihenfolge: waere zuerst geparst worden, kaeme der
    Parser-Fehler zuerst."""
    status, _ = _post(roh=b"{kein json", signatur="sha256=" + "11" * 32)
    assert status == 401


def test_kaputtes_json_mit_gueltiger_signatur_gibt_400():
    status, _ = _post(roh=b"{kein json")
    assert status == 400
    assert _aktivitaeten() == []


def test_fehlversuche_werden_gezaehlt_und_ohne_inhalt_geloggt():
    _lead()
    with _Mitschnitt() as m:
        _post(_ereignis(body="GEHEIMER KUNDENTEXT"), signatur="sha256=" + "22" * 32)
        _post(_ereignis(body="GEHEIMER KUNDENTEXT"), signatur="sha256=" + "33" * 32)
    texte = " ".join(m.texte())
    assert "GEHEIMER KUNDENTEXT" not in texte
    assert "2" in texte          # der Zaehler steht in der Zeile
    assert inbox.fehlversuche() == 2


# ---------------------------------------------------------------------------
# Verwerfen: fromMe, Gruppen, fremde Ereignisse
# ---------------------------------------------------------------------------

def test_frommme_wird_verworfen():
    _lead()
    status, antwort = _post(_ereignis(fromMe=True))
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten() == []


def test_gruppennachricht_wird_verworfen():
    _lead()
    status, antwort = _post(_ereignis(
        isGroup=True, chatId="120363000000000000@g.us",
        **{"from": "120363000000000000@g.us"}))
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten() == []


def test_gruppe_auch_ohne_isgroup_flag_am_jid_erkannt():
    _lead()
    status, antwort = _post(_ereignis(
        isGroup=False, chatId="120363000000000000@g.us",
        **{"from": "120363000000000000@g.us",
           "author": "491701234567@c.us"}))
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten() == []


def test_anderes_ereignis_wird_verworfen():
    _lead()
    umschlag = _ereignis()
    umschlag["event"] = "message.ack"
    status, antwort = _post(umschlag)
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten() == []


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_wiederholte_zustellung_wird_nur_einmal_gespeichert():
    _lead()
    erst = _post(_ereignis())
    zweit = _post(_ereignis())
    assert erst[0] == 200 and zweit[0] == 200
    assert zweit[1].get("doppelt") is True
    assert len(_aktivitaeten()) == 1


def test_zwei_verschiedene_nachrichten_werden_beide_gespeichert():
    _lead()
    _post(_ereignis(id="wa-1"))
    _post(_ereignis(id="wa-2"))
    assert len(_aktivitaeten()) == 2


def test_ohne_message_id_traegt_der_idempotenzschluessel():
    lead = _lead()
    umschlag = _ereignis()
    del umschlag["data"]["id"]
    status, _ = _post(umschlag)
    assert status == 200
    zeilen = _aktivitaeten()
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["message_id"] == "idem-1"
    assert str(zeilen[0]["lead_id"]) == lead


# ---------------------------------------------------------------------------
# Absender-Zuordnung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gespeichert, jid", [
    ("+49 170 1234567", "491701234567@c.us"),
    ("+491701234567", "491701234567@c.us"),
    ("0049 170 1234567", "491701234567@c.us"),
    ("491701234567", "491701234567@c.us"),
    ("+49 (0)170 1234567", "491701234567@c.us"),
    # Landesvorwahl ausserhalb 49 — der JID bringt sie ausgeschrieben mit.
    ("+43 664 1234567", "436641234567@c.us"),
    ("+1 202 555 0143", "12025550143@c.us"),
])
def test_absender_wird_ueber_nummern_py_zugeordnet(gespeichert, jid):
    lead = _lead(phone=gespeichert)
    status, _ = _post(_ereignis(**{"from": jid, "chatId": jid}))
    assert status == 200
    zeilen = _aktivitaeten()
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == lead


def test_geraetesuffix_im_jid_stoert_die_zuordnung_nicht():
    lead = _lead()
    status, _ = _post(_ereignis(**{"from": "491701234567:12@s.whatsapp.net"}))
    assert status == 200
    assert str(_aktivitaeten()[0]["lead_id"]) == lead


def test_lid_absender_wird_ueber_senderphone_zugeordnet():
    lead = _lead()
    status, _ = _post(_ereignis(**{"from": "22334455667788@lid",
                                   "isLidSender": True,
                                   "senderPhone": "491701234567"}))
    assert status == 200
    assert str(_aktivitaeten()[0]["lead_id"]) == lead


def test_unbekannter_absender_landet_im_sammel_lead():
    bekannt = _lead()
    sammel = _sammel_lead()
    status, antwort = _post(_ereignis(**{"from": "4915199999999@c.us",
                                         "chatId": "4915199999999@c.us"}))
    assert status == 200
    assert antwort["gespeichert"] is True
    zeilen = _aktivitaeten()
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == sammel
    assert str(zeilen[0]["lead_id"]) != bekannt
    assert zeilen[0]["payload"]["unbekannter_absender"] is True
    assert zeilen[0]["payload"]["absender"] == "4915199999999@c.us"


def test_unbekannter_absender_legt_keinen_kontakt_an():
    _lead()
    _sammel_lead()
    vorher = server._q("select count(*) as n from leads")[0]["n"]
    _post(_ereignis(**{"from": "4915199999999@c.us",
                       "chatId": "4915199999999@c.us"}))
    assert server._q("select count(*) as n from leads")[0]["n"] == vorher


def test_absender_ohne_brauchbare_nummer_landet_im_sammel_lead():
    _lead()
    sammel = _sammel_lead()
    status, _ = _post(_ereignis(**{"from": "22334455667788@lid",
                                   "isLidSender": True, "senderPhone": None}))
    assert status == 200
    assert str(_aktivitaeten()[0]["lead_id"]) == sammel


def test_ohne_sammel_lead_wird_nichts_verschluckt():
    """Kein INBOX_UNBEKANNT_LEAD_ID -> 503, damit OpenWA es wiederholt."""
    _lead()
    inbox.UNBEKANNT_LEAD_ID = ""
    status, _ = _post(_ereignis(**{"from": "4915199999999@c.us",
                                   "chatId": "4915199999999@c.us"}))
    assert status == 503
    assert _aktivitaeten() == []


# ---------------------------------------------------------------------------
# Inhalt
# ---------------------------------------------------------------------------

def test_text_wird_auf_2000_zeichen_gekuerzt():
    _lead()
    _post(_ereignis(body="x" * 5000))
    nutzlast = _aktivitaeten()[0]["payload"]
    assert len(nutzlast["text"]) == 2000
    assert nutzlast["gekuerzt"] is True


def test_kurzer_text_wird_nicht_als_gekuerzt_markiert():
    _lead()
    _post(_ereignis())
    assert _aktivitaeten()[0]["payload"]["gekuerzt"] is False


def test_medien_nachricht_ohne_text_wird_mit_typ_gespeichert():
    _lead()
    _post(_ereignis(body="", type="image"))
    nutzlast = _aktivitaeten()[0]["payload"]
    assert nutzlast["text"] == ""
    assert nutzlast["nachrichtentyp"] == "image"


def test_aktivitaet_wird_als_menschliche_quelle_gebucht():
    _lead()
    _post(_ereignis())
    assert _aktivitaeten()[0]["actor"] == "human"


# ---------------------------------------------------------------------------
# HTTP-Kanten
# ---------------------------------------------------------------------------

def test_falscher_pfad_gibt_404():
    status, _ = _post(_ereignis(), pfad="/")
    assert status == 404


def test_get_gibt_405():
    anfrage = urllib.request.Request(f"{URL}/webhook", method="GET")
    try:
        with urllib.request.urlopen(anfrage, timeout=10) as antwort:
            status = antwort.status
    except urllib.error.HTTPError as e:
        status = e.code
        e.read()
    assert status == 405


def test_zu_grosser_rumpf_wird_ohne_verarbeitung_abgewiesen():
    _lead()
    riesig = json.dumps(_ereignis(body="x" * (inbox.RUMPF_MAX + 10))).encode()
    status, _ = _post(roh=riesig)
    assert status == 413
    assert _aktivitaeten() == []


def test_datenbankausfall_gibt_503(monkeypatch):
    def kaputt(*_a, **_kw):
        raise psycopg.OperationalError("Verbindung weg")

    monkeypatch.setattr(server, "_q", kaputt)
    status, _ = _post(_ereignis())
    assert status == 503
