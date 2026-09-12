"""Telegram als vierter Versandkanal (Betreiber-Entscheid 12.09.2026).

sales-claw ist seit diesem Tag der einzige Versandweg des Hauses. Marketings
eigener Telegram-Versender ist gesperrt — ohne diesen Kanal hier waere er
ersatzlos weggefallen.

Was diese Tests festhalten, ist genau das, was beim Bauen gefaehrlich war:

  * EINE CHAT-ID IST KEINE TELEFONNUMMER. Sie sieht einer zum Verwechseln
    aehnlich; durch die Telefon-Normalisierung geschickt wuerde aus
    `1092040975` die Rufnummer `tel:+1092040975` — jemand im
    nordamerikanischen Raum, den es vermutlich nicht gibt. Deshalb eine
    eigene Form und eine eigene Pruefung.
  * ERREICHBARKEIT IST KEINE EINWILLIGUNG. Dass jemand den Bot gestartet hat
    (anders kommt keine chat_id zustande), macht ihn erreichbar — das UWG-Tor
    bleibt davon unberuehrt.
  * HTTP 200 IST NICHT DIE ZUSAGE. Die Bot-API antwortet auf Ablehnungen
    („bot was blocked by the user") ebenfalls mit 200 und `ok: false`. Wer
    nur den Code prueft, bucht ungesendete Nachrichten als gesendet.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os
from unittest import mock

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import dispatch  # noqa: E402
import server  # noqa: E402
import telegram_chat  # noqa: E402
import telegram_dispatch  # noqa: E402

CHAT_ID = "1092040975"


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
        # Die Verbotsliste GEHOERT DAZU (gemessen beim ersten Lauf dieser
        # Datei): ein Sperr-Test weiter unten traegt max@example.com ein, und
        # danach scheiterte JEDES kontakt_anlegen der folgenden Tests mit
        # „steht auf der gemeinsamen Verbotsliste" — neun Ausfaelle, deren
        # Ursache neun Tests entfernt lag. compliance_test, nie compliance
        # (sperrliste.SCHEMA, siehe dort); dieselbe Vorsichtsmassnahme wie
        # in test_dsgvo.py.
        conn.execute("truncate compliance_test.sperrliste")
    yield


def _anlegen(mit_einwilligung=True, mit_chat=True):
    lead = json.loads(server.kontakt_anlegen(
        name="Max Testperson", phone="+491701234567",
        email="max@example.com"))["lead_id"]
    if mit_einwilligung:
        server._q("update leads set consent_status = 'existing_customer' "
                  "where id = %s returning id", (lead,))
    if mit_chat:
        server.telegram_freigeben(lead, CHAT_ID)
    return lead


# --- Die chat_id ist keine Telefonnummer -----------------------------------

def test_chat_id_wird_nicht_zur_telefonnummer():
    """Der teuerste denkbare Irrtum dieses Kanals, als Test festgehalten."""
    import sperrliste
    # Was die Telefon-Normalisierung daraus MACHEN WUERDE — eine Nummer im
    # nordamerikanischen Raum (+1 092…), zu der niemand gehoert. (Beim
    # Schreiben stand hier `tel:+491092040975`; die deutsche Vorwahl kommt
    # nur bei fuehrender Null dazu. Der Test hat die falsche Behauptung
    # gefangen — die Verwechslungsgefahr wird dadurch nicht kleiner.)
    assert sperrliste.kennung_tel(CHAT_ID) == "tel:+1092040975"
    # Was hier passiert:
    assert telegram_chat.kennung(CHAT_ID) == "tg:1092040975"


@pytest.mark.parametrize("roh", ["1092040975", " 1092040975 ", 1092040975])
def test_gueltige_ids(roh):
    wert, fehler = telegram_chat.pruefe(roh)
    assert fehler is None and wert == "1092040975"


@pytest.mark.parametrize("roh", [
    "", "   ", None, "abc", "10920 40975", "1.092.040.975", "+1092040975",
    "0", "00", "0x41",
    "-1001234567890",        # Supergruppe: gueltig bei Telegram, hier NICHT
    "9" * 20,                # jenseits von int53 — eher ein Zeitstempel
])
def test_ungueltige_ids(roh):
    wert, fehler = telegram_chat.pruefe(roh)
    assert wert is None and fehler == telegram_chat.FEHLER_UNZUSTELLBAR


def test_gruppen_id_wird_bewusst_abgelehnt():
    """Negative IDs sind bei Telegram Gruppen und Kanaele. Dieses Haus
    schreibt an PERSONEN — eine Nachricht an eine Gruppe statt an einen
    Menschen ist der teuerste Irrtum, den dieser Kanal hergibt."""
    assert telegram_chat.pruefe("-1001234567890")[0] is None


# --- Erreichbarkeit am Kontakt --------------------------------------------

def test_ohne_freigabe_ist_der_kontakt_nicht_erreichbar():
    lead = _anlegen(mit_chat=False)
    zeile = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._telegram_chat_id(zeile["enrichment"]) is None


def test_freigeben_hinterlegt_die_id_und_nennt_die_grenze():
    lead = _anlegen(mit_chat=False)
    out = json.loads(server.telegram_freigeben(lead, CHAT_ID))
    assert out["telegram_erreichbar"] is True
    # Der Hinweis muss die Verwechslung ausdruecklich ausraeumen.
    assert "Einwilligung" in out["hinweis"] or "Erlaubnis" in out["hinweis"]
    zeile = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._telegram_chat_id(zeile["enrichment"]) == CHAT_ID


def test_freigeben_lehnt_eine_kaputte_id_ab_ohne_etwas_zu_schreiben():
    lead = _anlegen(mit_chat=False)
    out = json.loads(server.telegram_freigeben(lead, "nicht-numerisch"))
    assert "fehler" in out
    zeile = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert (zeile["enrichment"] or {}).get("telegram") is None


def test_entzug_behaelt_die_id_aber_sperrt_die_zustellung():
    """Wer die ID loeschte, muesste zum Wiederaufnehmen den Menschen bitten,
    den Bot erneut zu starten. Ein Entzug soll umkehrbar sein, ohne jemanden
    zu behelligen."""
    lead = _anlegen()
    json.loads(server.telegram_freigabe_entziehen(lead))
    zeile = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._telegram_chat_id(zeile["enrichment"]) is None
    assert zeile["enrichment"]["telegram"]["chat_id"] == CHAT_ID


# --- Das Entwurfs-Tor -------------------------------------------------------

def test_ohne_chat_id_entsteht_kein_entwurf():
    lead = _anlegen(mit_chat=False)
    out = json.loads(server.entwurf_erstellen(lead, "telegram", "Hallo"))
    assert "fehler" in out
    assert "chat_id" in out["fehler"]
    assert server._q("select id from drafts") == []


def test_erreichbarkeit_ersetzt_die_einwilligung_nicht():
    """Der Kern: eine hinterlegte chat_id oeffnet das UWG-Tor NICHT."""
    lead = _anlegen(mit_einwilligung=False, mit_chat=True)
    out = json.loads(server.entwurf_erstellen(lead, "telegram", "Hallo"))
    assert "fehler" in out
    assert "ERSTANSPRACHE" in out["fehler"]
    assert server._q("select id from drafts") == []


def test_mit_beidem_entsteht_ein_pending_entwurf_an_die_chat_id():
    lead = _anlegen()
    out = json.loads(server.entwurf_erstellen(lead, "telegram", "Hallo",
                                              betreff="Betreff"))
    assert out["status"] == "pending"
    zeile = server._q("select channel, recipient, status from drafts "
                      "where id = %s", (out["draft_id"],))[0]
    assert zeile["channel"] == "telegram"
    assert zeile["recipient"] == CHAT_ID       # nicht die Telefonnummer!
    assert zeile["status"] == "pending"


def test_die_verbotsliste_greift_ueber_den_kontakt():
    """Telegram-Kennungen passen nicht in compliance.sperrliste (deren CHECK
    kennt nur email: und tel:). Die Sperre wirkt trotzdem — ueber die
    E-Mail und die Nummer desselben Kontakts."""
    import sperrliste
    lead = _anlegen()
    sperrliste.sperren(server._q, email="max@example.com",
                       quelle="test", grund="Widerruf")
    out = json.loads(server.entwurf_erstellen(lead, "telegram", "Hallo"))
    assert "fehler" in out and "Verbotsliste" in out["fehler"]


# --- Der Dispatcher ---------------------------------------------------------

def _entwurf_sql(lead_id, status="approved", recipient=CHAT_ID,
                 media_ref=None, body="Hallo", subject=None):
    return server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref, status) values (%s, 'telegram', %s, %s, %s, %s, %s) "
        "returning id", (lead_id, recipient, subject, body, media_ref, status)
    )[0]["id"]


def test_claim_fasst_nur_telegram_an():
    lead = _anlegen()
    fremd = server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'email', 'max@example.com', 'Hallo', 'approved') "
        "returning id", (lead,))[0]["id"]
    assert telegram_dispatch.claim(fremd) is None
    assert server._q("select status from drafts where id = %s",
                     (fremd,))[0]["status"] == "approved"


def test_claim_ist_einmalig():
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    assert telegram_dispatch.claim(draft) is not None
    assert telegram_dispatch.claim(draft) is None


def test_claim_traegt_die_gemeinsame_marke():
    """Sonst waere die Schutzkante gegen Doppelversand fuer diesen Kanal
    still ausser Kraft: entwurf_erneut_freigeben erkennt einen haengenden
    Versand an genau diesem Praefix."""
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    telegram_dispatch.claim(draft)
    fehler = server._q("select error from drafts where id = %s", (draft,))[0]["error"]
    assert fehler.startswith(dispatch.CLAIM_PRAEFIX)


def test_anhang_wird_abgelehnt_statt_ohne_ihn_zu_senden():
    lead = _anlegen()
    draft = _entwurf_sql(lead, media_ref="post.pdf")
    with mock.patch.object(telegram_dispatch, "senden") as gesendet:
        ausgang = telegram_dispatch.verarbeite_draft(draft)
    gesendet.assert_not_called()
    assert ausgang == "anhang_nicht_unterstuetzt"
    zeile = server._q("select status, error from drafts where id = %s", (draft,))[0]
    assert zeile["status"] == "failed"
    assert "NICHTS raus" in zeile["error"]


def test_zu_langer_text_faellt_vor_dem_netzgriff_durch():
    lead = _anlegen()
    draft = _entwurf_sql(lead, body="x" * (telegram_dispatch.TEXT_MAXLAENGE + 1))
    with mock.patch.object(telegram_dispatch, "senden") as gesendet:
        ausgang = telegram_dispatch.verarbeite_draft(draft)
    gesendet.assert_not_called()
    assert ausgang == "unzustellbar"
    assert "kuerzen" in server._q(
        "select error from drafts where id = %s", (draft,))[0]["error"]


def test_betreff_wird_zur_ersten_zeile():
    """Telegram kennt keinen Betreff — ohne diese Zeile ginge die
    Ueberschrift, die ein Mensch freigegeben hat, still verloren."""
    assert telegram_dispatch._text_bauen("Kopf", "Rumpf") == "Kopf\n\nRumpf"
    assert telegram_dispatch._text_bauen("", "Rumpf") == "Rumpf"
    assert telegram_dispatch._text_bauen(None, "Rumpf") == "Rumpf"


def test_erfolg_bucht_sent_und_protokolliert_die_chat_id():
    lead = _anlegen()
    draft = _entwurf_sql(lead, subject="Kopf")
    gesehen = {}

    def falsches_senden(chat_id, text):
        gesehen.update(chat_id=chat_id, text=text)

    with mock.patch.object(telegram_dispatch, "senden", falsches_senden):
        ausgang = telegram_dispatch.verarbeite_draft(draft)
    assert ausgang == "gesendet"
    assert gesehen == {"chat_id": CHAT_ID, "text": "Kopf\n\nHallo"}
    assert server._q("select status from drafts where id = %s",
                     (draft,))[0]["status"] == "sent"
    akt = server._q("select type, payload from activities where lead_id = %s "
                    "and type = 'versand'", (lead,))
    # psycopg gibt jsonb bereits als dict zurueck — kein json.loads noetig.
    assert akt and akt[0]["payload"]["empfaenger"] == CHAT_ID


def test_ablehnung_der_api_wird_zum_lesbaren_grund():
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    with mock.patch.object(
            telegram_dispatch, "senden",
            side_effect=telegram_dispatch.VersandFehler(
                "Telegram lehnt ab: bot was blocked by the user")):
        ausgang = telegram_dispatch.verarbeite_draft(draft)
    assert ausgang == "fehler"
    zeile = server._q("select status, error from drafts where id = %s", (draft,))[0]
    assert zeile["status"] == "failed"
    assert "blocked" in zeile["error"]


def test_runde_holt_nur_freigegebene_telegram_entwuerfe():
    lead = _anlegen()
    _entwurf_sql(lead, status="pending")
    _entwurf_sql(lead, status="approved")
    with mock.patch.object(telegram_dispatch, "senden"):
        bilanz = telegram_dispatch.eine_runde()
    assert bilanz == {"gesendet": 1}


# --- Der Token darf nirgends landen ----------------------------------------

def test_der_bot_token_wird_aus_fehlertexten_gefiltert():
    """Jede URL dieses Dienstes traegt den Token. Ein Fehlertext aus urllib
    traegt die URL — und er landet ueber _als_fehler_buchen in der Datenbank
    und in der Oberflaeche."""
    with mock.patch.object(telegram_dispatch, "BOT_TOKEN", "123:GEHEIM"):
        sauber = telegram_dispatch._ohne_token(
            "HTTP Error bei https://api.telegram.org/bot123:GEHEIM/sendMessage")
    assert "GEHEIM" not in sauber and "***" in sauber


def test_die_zwei_werkzeuge_sind_registriert():
    namen = {w.__name__ for w in server.WERKZEUGE}
    assert {"telegram_freigeben", "telegram_freigabe_entziehen"} <= namen
