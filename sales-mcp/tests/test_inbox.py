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


# Die eigene (gekoppelte) Nummer und die des Kunden. Bei `fromMe` traegt
# `from` die EIGENE und `chatId` (== `to`) die des Kunden — gemessen an
# openwa/upstream/src/engine/adapters/message-mapper.ts und an den echten
# Zeilen der openwa-Datenbank (Tabelle `messages`), siehe Moduldocstring von
# inbox.py. Genau diese Umkehr bilden die Stubs unten ab.
EIGENE = "4915100000000@c.us"
KUNDE = "491701234567@c.us"


def _ereignis(**felder):
    """Ein `message.received`-Umschlag in der gemessenen OpenWA-Form."""
    daten = {"id": "wa-nachricht-1", "from": KUNDE,
             "to": EIGENE, "chatId": KUNDE,
             "body": "Hallo, passt Donnerstag?", "type": "text",
             "timestamp": 1770000000, "fromMe": False, "isGroup": False,
             "kind": "individual"}
    daten.update(felder)
    return {"event": "message.received",
            "timestamp": "2026-08-18T20:00:00.000Z",
            "sessionId": "stub-session", "idempotencyKey": "idem-1",
            "deliveryId": "lieferung-1", "data": daten}


def _echo(**felder):
    """Ein `message.sent`-Umschlag: von diesem Konto ging etwas raus.

    OpenWA dispatcht eigene Sendungen NICHT als `message.received`, sondern
    als `message.sent` (message-projector.service.ts: der Eingangspfad
    dispatcht `message.received`, `handleOwnSendEcho` dispatcht
    `message.sent`); die Nutzlast ist dieselbe IncomingMessage.
    """
    daten = {"id": "wa-echo-1", "from": EIGENE, "to": KUNDE, "chatId": KUNDE,
             "body": "Donnerstag 15 Uhr passt, bis dann!", "type": "text",
             "timestamp": 1770000100, "fromMe": True, "isGroup": False,
             "kind": "individual"}
    daten.update(felder)
    return {"event": "message.sent",
            "timestamp": "2026-08-18T20:05:00.000Z",
            "sessionId": "stub-session", "idempotencyKey": "idem-echo-1",
            "deliveryId": "lieferung-2", "data": daten}


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
# Eigene Nachrichten (Stufe 8): Kundenchat wird protokolliert, Selbst-Chat
# nicht. Ohne diese Zeilen bliebe ein vom Handy beantworteter Kontakt im
# Postfach ewig „unbeantwortet"; mit dem Selbst-Chat drin flutete jede
# Digest-Zustellung dasselbe Postfach.
# ---------------------------------------------------------------------------

def test_eigene_antwort_an_kunden_wird_als_nachricht_ausgehend_gebucht():
    lead = _lead()
    status, antwort = _post(_echo())
    assert status == 200, antwort
    assert antwort["gespeichert"] is True
    assert _aktivitaeten("kundenantwort") == []
    zeilen = _aktivitaeten("nachricht_ausgehend")
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == lead
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["richtung"] == "ausgehend"
    assert nutzlast["empfaenger"] == KUNDE
    assert nutzlast["message_id"] == "wa-echo-1"
    assert nutzlast["text"] == "Donnerstag 15 Uhr passt, bis dann!"
    assert nutzlast["unbekannter_empfaenger"] is False
    # Herkunft ist an der Nutzlast nicht entscheidbar (Betreiber-Handy ODER
    # Echo eines Dispatcher-Versands) — und wird deshalb nicht erfunden.
    assert nutzlast["weg"] == "unbekannt"


def test_ausgehende_zeile_wird_nicht_als_mensch_gebucht():
    """`activities_actor_check` laesst nur ('agent','human','cron') zu — das im
    Plan genannte 'system' ist ohne DDL nicht speicherbar. 'human' waere
    falsch: bei einem Dispatcher-Echo hat kein Mensch getippt."""
    _lead()
    _post(_echo())
    assert _aktivitaeten("nachricht_ausgehend")[0]["actor"] == "agent"


def test_selbst_chat_wird_verworfen():
    """Der Notizzettel-/Bot-Kanal: eigene Nummer an eigene Nummer. Gemessen
    ist er genau daran erkennbar, dass `chatId` und `from` dieselbe Nummer
    tragen (in der echten openwa-Datenbank die einzige Zeile mit
    from == to == chatId)."""
    _lead()
    status, antwort = _post(_echo(**{"to": EIGENE, "chatId": EIGENE}))
    assert status == 200
    assert "Selbst-Chat" in antwort["verworfen"]
    assert _aktivitaeten("nachricht_ausgehend") == []
    assert _aktivitaeten("kundenantwort") == []


def test_eigene_nachricht_ohne_lesbare_kennung_wird_verworfen():
    """Im Zweifel verwerfen: ein faelschlich gebuchter Selbst-Chat verstopft
    das Postfach, eine verpasste Antwort laesst nur einen Kontakt laenger
    unbeantwortet aussehen."""
    _lead()
    status, antwort = _post(_echo(**{"from": ""}))
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten("nachricht_ausgehend") == []


def test_wiederholtes_echo_wird_nur_einmal_gespeichert():
    _lead()
    erst = _post(_echo())
    zweit = _post(_echo())
    assert erst[0] == 200 and zweit[0] == 200
    assert zweit[1].get("doppelt") is True
    assert len(_aktivitaeten("nachricht_ausgehend")) == 1


def test_echo_an_unbekannten_empfaenger_landet_im_sammel_lead():
    bekannt = _lead()
    sammel = _sammel_lead()
    status, _ = _post(_echo(**{"to": "4915199999999@c.us",
                               "chatId": "4915199999999@c.us"}))
    assert status == 200
    zeilen = _aktivitaeten("nachricht_ausgehend")
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == sammel != bekannt
    assert zeilen[0]["payload"]["unbekannter_empfaenger"] is True
    assert zeilen[0]["payload"]["empfaenger"] == "4915199999999@c.us"


def test_eigene_nachricht_wird_am_frommme_erkannt_nicht_am_ereignisnamen():
    """Die Nutzlast ist die Wahrheit, der Ereignisname ist Beiwerk: ein
    `*`-Abo oder ein anderer Engine-Adapter kann dieselbe Nachricht unter
    anderem Namen zustellen."""
    lead = _lead()
    umschlag = _echo()
    umschlag["event"] = "message.received"
    status, _ = _post(umschlag)
    assert status == 200
    zeilen = _aktivitaeten("nachricht_ausgehend")
    assert len(zeilen) == 1 and str(zeilen[0]["lead_id"]) == lead


def test_eigene_nachricht_wird_dem_kunden_zugeordnet_nicht_der_eigenen_nummer():
    """Der Kern der gemessenen Umkehr: `absender_nummer` (die auf `from`
    schaut) haette diese Zeile auf die EIGENE Nummer gebucht."""
    kunde = _lead(name="Kundin", phone="+49 170 1234567")
    _lead(name="Eigene Versandnummer", phone="+49 151 00000000")
    _post(_echo())
    assert str(_aktivitaeten("nachricht_ausgehend")[0]["lead_id"]) == kunde


def test_gruppenecho_wird_verworfen():
    _lead()
    status, antwort = _post(_echo(
        isGroup=True, chatId="120363000000000000@g.us",
        **{"to": "120363000000000000@g.us"}))
    assert status == 200
    assert antwort["verworfen"]
    assert _aktivitaeten("nachricht_ausgehend") == []


def test_eingang_fasst_auch_bei_eigenen_nachrichten_keine_entwuerfe_an():
    """Gate-Invariante: dieser Dienst schreibt nur Protokollzeilen. Er
    versendet nichts und bewegt keinen `drafts`-Satz — auch nicht, seit er
    ausgehende Nachrichten kennt."""
    lead = _lead()
    server._q("insert into drafts (lead_id, channel, recipient, body, status) "
              "values (%s,'whatsapp','+491701234567','x','pending')", (lead,))
    _post(_echo())
    _post(_ereignis())
    zeilen = server._q("select status from drafts")
    assert [z["status"] for z in zeilen] == ["pending"]


# ---------------------------------------------------------------------------
# Verwerfen: Gruppen, fremde Ereignisse
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Zweitnummern: was der Betreiber einmal eingeordnet hat, bleibt eingeordnet
# ---------------------------------------------------------------------------

def _zuordnung(kennung, telefon):
    """Wie `eingang_einordnen(entscheidung='zuordnen')` sie ablegt.

    `lid_zuordnung_speichern` haengt die Zeile an den Sammelkontakt, und den
    kennt SERVER unter eigenem Namen — `_sammel_lead()` setzt nur den des
    Eingangs. Ohne diese Klammer schluege der Fremdschluessel an.
    """
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = inbox.UNBEKANNT_LEAD_ID or ""
    try:
        return server.lid_zuordnung_speichern(kennung, telefon, "betreiber",
                                              "rufnummer")
    finally:
        server.UNBEKANNT_LEAD_ID = vorher


def test_eine_zugeordnete_ZWEITNUMMER_landet_beim_richtigen_kontakt():
    """Der gemessene Fall — 217 Nachrichten am falschen Platz.

    Am 01.09.2026 hat der Betreiber `491791714185` dem Kontakt hinter
    `4917688014635@c.us` zugeordnet; das Werkzeug versprach ihm dabei woertlich
    „Kuenftige Nachrichten von dieser Kennung laufen zum Kontakt mit dieser
    Nummer". Eingehalten wurde das nie: `_kennung` befragt die gespeicherte
    Zuordnung NUR im `@lid`-Zweig, eine Rufnummer laeuft daran vorbei. Bis zum
    22.09.2026 landeten so 217 Nachrichten desselben Menschen am
    Sammelkontakt — drei Wochen, nachdem die Frage „wer ist das?" beantwortet
    war. Deshalb kam er immer wieder zum Einordnen.
    """
    lead = _lead("Ivan", "+4917688014635")
    sammel = _sammel_lead()
    _zuordnung("491791714185", "4917688014635@c.us")
    status, _ = _post(_ereignis(**{"from": "491791714185@c.us",
                                   "chatId": "491791714185@c.us"}))
    assert status == 200
    zeilen = _aktivitaeten()
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == lead != sammel


def test_auch_die_AUSGEHENDE_richtung_folgt_der_zuordnung():
    """Sonst stuende die Antwort des Betreibers weiter am Sammelkontakt — und
    die Beantwortet-Pruefung saehe eine Frage ohne Antwort."""
    lead = _lead("Ivan", "+4917688014635")
    sammel = _sammel_lead()
    _zuordnung("491791714185", "4917688014635@c.us")
    status, _ = _post(_echo(**{"to": "491791714185@c.us",
                               "chatId": "491791714185@c.us"}))
    assert status == 200
    zeilen = _aktivitaeten("nachricht_ausgehend")
    assert len(zeilen) == 1
    assert str(zeilen[0]["lead_id"]) == lead != sammel


def test_der_DIREKTE_treffer_schlaegt_eine_veraltete_zuordnung():
    """Die Reihenfolge ist der Kern, nicht ein Detail.

    Genau dieser Zustand steht heute in der Produktion: die Zuordnung zeigt
    von der neuen Nummer auf die ALTE (`491791714185` -> `4917688014635@c.us`),
    inzwischen traegt der Kontakt aber die NEUE. Wer die Zuordnung vor der
    direkten Suche anwendet, loest auf eine Nummer auf, die kein Kontakt mehr
    hat — und schickt den Menschen zurueck an den Sammelkontakt, den er
    gerade verlassen hat. Die Zuordnung ist ein RUECKFALL, kein Vorlauf.
    """
    lead = _lead("Ivan", "+491791714185")          # neue Nummer, wie heute
    sammel = _sammel_lead()
    _zuordnung("491791714185", "4917688014635@c.us")   # zeigt ins Leere
    status, _ = _post(_ereignis(**{"from": "491791714185@c.us",
                                   "chatId": "491791714185@c.us"}))
    assert status == 200
    assert str(_aktivitaeten()[0]["lead_id"]) == lead != sammel


def test_eine_zuordnung_ohne_passenden_kontakt_bleibt_am_sammelkontakt():
    """Kein Auto-Anlegen, auch nicht ueber die Bruecke: zeigt die Zuordnung
    auf eine Nummer, die niemandem gehoert, ist der Absender weiterhin
    unbekannt — und wird gefragt, statt geraten."""
    _lead("Jemand anders", "+49 170 1234567")
    sammel = _sammel_lead()
    _zuordnung("4915199999999", "4915288888888@c.us")
    status, _ = _post(_ereignis(**{"from": "4915199999999@c.us",
                                   "chatId": "4915199999999@c.us"}))
    assert status == 200
    zeilen = _aktivitaeten()
    assert str(zeilen[0]["lead_id"]) == sammel
    assert zeilen[0]["payload"]["unbekannter_absender"] is True


def test_die_bruecke_geht_genau_EINEN_schritt():
    """A -> B -> C wird nicht durchgereicht.

    Eine Kette waere eine Aussage, die der Betreiber nie getroffen hat: er hat
    gesagt „A ist B" und „B ist C", nicht „A ist C". Zwei Schritte koennten
    ausserdem im Kreis laufen. Ein Schritt ist beweisbar das, was er gesagt
    hat — mehr nicht.
    """
    lead = _lead("Am Ende der Kette", "+4915277777777")
    sammel = _sammel_lead()
    _zuordnung("4915199999999", "4915288888888@c.us")
    _zuordnung("4915288888888", "4915277777777@c.us")
    status, _ = _post(_ereignis(**{"from": "4915199999999@c.us",
                                   "chatId": "4915199999999@c.us"}))
    assert status == 200
    assert str(_aktivitaeten()[0]["lead_id"]) == sammel != lead


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


# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Stufe-8-Review (Befunde M2, N1)
# ---------------------------------------------------------------------------

def test_message_sent_ohne_fromme_wird_als_widerspruch_verworfen():
    """M2: ein Sende-Echo ohne fromMe=true darf NICHT als Kundenantwort der
    eigenen Nummer gebucht werden — sonst fuellte ein abweichender Adapter
    das Postfach mit den eigenen Sendungen."""
    _lead()
    status, antwort = _post(_echo(fromMe=False))
    assert status == 200
    assert "Widerspruch" in antwort["verworfen"]
    assert _aktivitaeten() == []
    assert _aktivitaeten("nachricht_ausgehend") == []


def test_gleiche_message_id_ueber_beide_richtungen_bucht_nur_einmal():
    """N1: das Dedup ist typuebergreifend begruendet (inbox.py) — hier der
    Beweis: dieselbe message_id einmal eingehend, einmal als Echo ergibt
    genau EINE Zeile, die zweite Zustellung wird als Duplikat quittiert."""
    _lead()
    status, erste = _post(_ereignis(id="wa-doppelt-1"))
    assert status == 200 and erste["gespeichert"] is True
    status, zweite = _post(_echo(id="wa-doppelt-1"))
    assert status == 200
    assert zweite.get("gespeichert") is not True
    alle = server._q(
        "select type from activities where payload->>'message_id' = %s",
        ("wa-doppelt-1",))
    assert len(alle) == 1
    assert alle[0]["type"] == "kundenantwort"


# ---------------------------------------------------------------------------
# Privat-Markierung (P3, 29.08.2026): fuer private Kontakte wird KEIN
# Inhalt gespeichert — Datensparsamkeit statt Filterung. Der Webhook wird
# trotzdem mit 200 quittiert (OpenWA soll nicht endlos wiederholen), und
# das Log nennt weder Nummer noch Text.
# ---------------------------------------------------------------------------

def test_privater_kontakt_wird_nicht_gespeichert():
    lead = _lead("Pia Privat")
    server.kontakt_privat_setzen(lead)
    status, antwort = _post(_ereignis(id="wa-privat-1"))
    assert status == 200
    assert antwort.get("privat") is True
    assert "aktivitaet_id" not in antwort
    zeilen = server._q(
        "select count(*) n from activities where lead_id = %s and "
        "type in ('kundenantwort', 'nachricht_ausgehend')", (lead,))
    assert zeilen[0]["n"] == 0


def test_auch_die_eigene_richtung_bleibt_ungespeichert():
    lead = _lead("Pia Privat")
    server.kontakt_privat_setzen(lead)
    status, antwort = _post(_echo(id="wa-privat-2"),
                            kopfzeilen={"X-OpenWA-Event": "message.sent"})
    assert status == 200
    assert antwort.get("privat") is True
    assert server._q(
        "select count(*) n from activities where lead_id = %s",
        (lead,))[0]["n"] == 1  # nur die kontakt_privat-Beweiszeile


def test_das_log_verraet_weder_nummer_noch_text():
    lead = _lead("Pia Privat")
    server.kontakt_privat_setzen(lead)
    with _Mitschnitt() as m:
        _post(_ereignis(id="wa-privat-3"))
    verdaechtig = [t for t in m.texte()
                   if "1234567" in t or "Donnerstag" in t]
    assert verdaechtig == []
