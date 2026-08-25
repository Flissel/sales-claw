"""Vertragstests fuer den Kennungs-Bericht und den Identitaets-Mitschrieb.

Betreiber am 25.08.2026: „kannst du dir einen trigger setzen um zu
ueberpruefen welche daten gleich bleiben und welche sich aendern? damit wir
ein exaktes matching machen koennen?"

Der Anlass ist echt: WhatsApp stellt auf LIDs um. Dieselbe Person erscheint
mal unter ihrer Rufnummer (`4915772882471@c.us`), mal unter einer LID
(`143151310344360`), die keinen Bezug zur Nummer hat. In den Produktivdaten
war am 25.08.2026 nachweisbar:

* eine LID, die zu ZWEI verschiedenen Rufnummern aufgeloest wurde
  (`245745328336963`), und
* `senderPhone` — die erste und beste Stufe der Zuordnungskette — kein
  einziges Mal, obwohl RESOLVE_LID_TO_PHONE gesetzt war.

Beides war vorher unsichtbar, weil je Nachricht nur `absender` und
`kennung_quelle` behalten wurden. Diese Suite nagelt fest, dass es jetzt
sichtbar ist — und dass der Mitschrieb die Privatsphaere-Regel fuer
ignorierte Absender nicht unterlaeuft.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import inbox  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _nachricht(lead, absender, **zusatz):
    nutzlast = {"absender": absender, "text": "Hallo", "richtung": "eingehend"}
    nutzlast.update(zusatz)
    return server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'kundenantwort', %s) returning id",
        (lead, json.dumps(nutzlast)))[0]["id"]


def _zuordnung(lid, telefon, quelle):
    return server._q(
        "insert into activities (lead_id, type, payload) "
        "values (null, 'lid_zuordnung', %s) returning id",
        (json.dumps({"lid": lid, "telefon": telefon, "typ": "rufnummer",
                     "quelle": quelle}),))[0]["id"]


# ---------------------------------------------------------------------------
# Der Mitschrieb: was von einer Nachricht an Identitaet uebrig bleibt
# ---------------------------------------------------------------------------

def test_identitaetsfelder_werden_gesammelt():
    felder = inbox._identitaetsfelder({
        "pushName": "Sophie M.", "isLidSender": True,
        "senderPhone": "491729186846@c.us",
        "chatId": "183096603361451@lid", "from": "183096603361451@lid"})
    assert felder["push_name"] == "Sophie M."
    assert felder["ist_lid_absender"] is True
    assert felder["senderphone"] == "491729186846@c.us"
    assert felder["chat_kennung"] == "183096603361451@lid"


def test_fehlende_felder_erzeugen_keine_luege():
    """Was nicht kam, steht nicht drin — ausser senderphone.

    `senderphone: None` ist die AUSSAGE „OpenWA hat sie nicht mitgeliefert",
    und genau die ist der Befund, den dieser Mitschrieb sichtbar machen soll.
    Fehlt der Schluessel dagegen ganz, laesst sich „nicht geliefert" nicht
    von „diese Fassung schrieb es noch nicht mit" unterscheiden.
    """
    felder = inbox._identitaetsfelder({"from": "491701234567@c.us"})
    assert "push_name" not in felder
    assert "ist_lid_absender" not in felder
    assert felder["senderphone"] is None
    assert felder["roh_from"] == "491701234567@c.us"


def test_kein_inhalt_im_mitschrieb():
    """Identitaet ja, Inhalt nein."""
    felder = inbox._identitaetsfelder({
        "from": "x@c.us", "body": "Geheimer Text", "caption": "auch geheim",
        "pushName": "Wer"})
    zusammen = json.dumps(felder, ensure_ascii=False)
    assert "Geheimer Text" not in zusammen
    assert "auch geheim" not in zusammen


def test_langer_anzeigename_wird_gedeckelt():
    felder = inbox._identitaetsfelder({"pushName": "N" * 400, "from": "x"})
    assert len(felder["push_name"]) <= 120


# ---------------------------------------------------------------------------
# Der Bericht
# ---------------------------------------------------------------------------

def test_bericht_zeigt_kennungen_mit_quelle_und_kontakt():
    lead = _lead(name="Sophie", phone="+491729186846")
    _nachricht(lead, "491729186846@c.us", kennung_quelle="zuordnung",
               push_name="Sophie M.")
    b = json.loads(server.kennungen_bericht())
    treffer = [k for k in b["kennungen"]
               if k["kennung"] == "491729186846@c.us"]
    assert treffer, b["kennungen"]
    assert treffer[0]["kontakt"] == "Sophie"
    assert treffer[0]["quellen"] == ["zuordnung"]
    assert treffer[0]["anzeigenamen"] == ["Sophie M."]


def test_bericht_findet_den_widerspruch():
    """Der gefaehrliche Fall: eine LID, zwei verschiedene Rufnummern."""
    _zuordnung("245745328336963", "4915228908100@c.us", "openwa")
    _zuordnung("245745328336963", "491729186846@c.us", "betreiber")
    b = json.loads(server.kennungen_bericht())
    assert len(b["widersprueche"]) == 1
    w = b["widersprueche"][0]
    assert w["lid"] == "245745328336963"
    assert w["ziele"] == ["4915228908100@c.us", "491729186846@c.us"]
    assert w["quellen"] == ["openwa", "betreiber"]
    # Die spaetere gewinnt — genau das macht den Fall gefaehrlich.
    assert w["gewonnen_hat"] == "491729186846@c.us"


def test_eindeutige_aufloesung_ist_kein_widerspruch():
    _zuordnung("143151310344360", "4915772882471@c.us", "openwa")
    _zuordnung("143151310344360", "4915772882471@c.us", "betreiber")
    assert json.loads(server.kennungen_bericht())["widersprueche"] == []


def test_bericht_zaehlt_ob_openwa_die_nummer_mitliefert():
    """Der Befund, der die ganze Frage aufwarf: sie kam nie mit."""
    lead = _lead()
    _nachricht(lead, "1234567890123@lid", senderphone=None)
    _nachricht(lead, "491701234567@c.us",
               senderphone="491701234567@c.us")
    zahlen = json.loads(server.kennungen_bericht())["senderphone"]
    assert zahlen["mit_nummer"] == 1
    assert zahlen["ohne_nummer"] == 1


def test_bericht_markiert_was_im_sammelkontakt_haengt():
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = sammel
    try:
        _nachricht(sammel, "999888777666555@lid", kennung_quelle="lid")
        b = json.loads(server.kennungen_bericht())
        treffer = [k for k in b["kennungen"]
                   if k["kennung"] == "999888777666555@lid"]
        assert treffer and treffer[0]["im_sammelkontakt"] is True
    finally:
        server.UNBEKANNT_LEAD_ID = vorher


def test_bericht_aendert_nichts():
    lead = _lead()
    _nachricht(lead, "491701234567@c.us")
    vorher = server._q("select count(*) n from activities")[0]["n"]
    server.kennungen_bericht()
    assert server._q("select count(*) n from activities")[0]["n"] == vorher


def test_bericht_ohne_daten_faellt_nicht_um():
    b = json.loads(server.kennungen_bericht())
    assert b["kennungen"] == []
    assert b["widersprueche"] == []
