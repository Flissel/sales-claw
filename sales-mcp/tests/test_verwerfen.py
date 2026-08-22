"""Vertragstests fuer `entwurf_verwerfen` (Betreiber-Wunsch 22.08.2026).

Der Auftrag: Entwuerfe endgueltig wegraeumen. Bis dahin gab es fuer einen
Entwurf keinen Ausgang ausser dem Versand — `failed` liess sich nur erneut
freigeben, `approved` gar nicht mehr stoppen (gemessen am 22.08.2026 im Schema
`sales`: drei `failed` und ein `approved` vom 18.08., seit vier Tagen in der
Liste).

Getestet wird vor allem die ABWEHR, denn das Wegraeumen ist eine Behauptung
ueber die Wirklichkeit: `rejected` heisst „ging nicht raus". Deshalb
* `sent` niemals — die Zeile ist ein Zustellnachweis;
* `pending` gar nicht hier — dafuer gibt es `entwurf_ablehnen`, denselben
  Vorgang, und die Fehlermeldung muss dorthin zeigen;
* `approved` nur ausdruecklich bestaetigt — eine geltende Freigabe;
* und ueberall dort, wo die Claim-Marke des Dispatchers steht, gar nicht bzw.
  nur ausdruecklich: sie heisst „moeglicherweise schon beim Empfaenger", und
  ein `rejected` verdeckte das dann.
"""
import json
import os

import pytest

# HART, nicht setdefault (wie test_werkzeuge.py): eine von aussen gesetzte
# SALES_DB_SCHEMA=sales wuerde die truncate-Fixture auf Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
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


# Die Claim-Marke wird direkt per SQL gesetzt statt ueber den Dispatcher —
# server.py kennt bewusst nur das Textmuster, nicht dispatch.py (Zirkelimport;
# dispatch.py hat seine eigene Suite in test_dispatch.py).
_CLAIM_MARKE = "in Zustellung seit 2026-08-22T09:00:00+00:00 (dispatcher beef0001)"


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, status="failed", kanal="whatsapp", fehler="OpenWA HTTP 500",
             text="Hallo, passt Donnerstag?"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, error) "
        "values (%s, %s, '+491701234567', %s, %s, %s) returning id",
        (lead, kanal, text, status, fehler))[0]["id"])


def _zeile(draft_id):
    return server._q("select status, error, body, approved_by "
                     "from drafts where id = %s", (draft_id,))[0]


def _verwerfungen(lead):
    return server._q(
        "select payload, actor from activities where lead_id = %s "
        "and type = 'verwerfung' order by created_at", (lead,))


# ---------------------------------------------------------------------------
# failed -> rejected: der einfache Fall, ohne Bestaetigung
# ---------------------------------------------------------------------------

def test_failed_wird_ohne_bestaetigung_rejected():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    ok = json.loads(server.entwurf_verwerfen(draft))
    assert ok["status"] == "rejected"
    assert ok["aus_status"] == "failed"
    assert _zeile(draft)["status"] == "rejected"


def test_failed_verwerfen_loggt_aktivitaet_mit_aus_status():
    """Nach dem Uebergang traegt die Zeile `rejected` und sagt nicht mehr, ob
    sie gescheitert oder freigegeben war. Das Protokoll ist der einzige Ort,
    an dem das spaeter noch steht."""
    lead = _lead()
    draft = _entwurf(lead, status="failed")
    server.entwurf_verwerfen(draft)
    akt = _verwerfungen(lead)
    assert len(akt) == 1
    assert akt[0]["payload"]["draft_id"] == draft
    assert akt[0]["payload"]["kanal"] == "whatsapp"
    assert akt[0]["payload"]["aus_status"] == "failed"


def test_verwerfen_loescht_nichts_der_text_bleibt_stehen():
    lead = _lead()
    draft = _entwurf(lead, status="failed", text="Guten Tag, Frau Mueller")
    server.entwurf_verwerfen(draft)
    assert _zeile(draft)["body"] == "Guten Tag, Frau Mueller"


def test_ablehnung_wird_nicht_mitgeschrieben():
    """`ablehnung` heisst „vor der Freigabe abgelehnt", `verwerfung` heisst
    „danach weggeraeumt". Wer die beiden im Protokoll vermischt, kann sie nie
    wieder trennen (activities ist append-only)."""
    lead = _lead()
    draft = _entwurf(lead, status="failed")
    server.entwurf_verwerfen(draft)
    assert server._q("select id from activities where lead_id = %s "
                     "and type = 'ablehnung'", (lead,)) == []


# ---------------------------------------------------------------------------
# approved -> rejected: nur ausdruecklich
# ---------------------------------------------------------------------------

def test_approved_ohne_bestaetigung_bleibt_unberuehrt():
    lead = _lead()
    draft = _entwurf(lead, status="approved", fehler=None)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft))
    assert "fehler" in kaputt
    assert "bestaetigt=True" in kaputt["fehler"]
    assert _zeile(draft) == vor
    assert _verwerfungen(lead) == []


def test_approved_mit_bestaetigung_wird_rejected():
    lead = _lead()
    draft = _entwurf(lead, status="approved", fehler=None)
    ok = json.loads(server.entwurf_verwerfen(draft, bestaetigt=True))
    assert ok["status"] == "rejected"
    assert ok["aus_status"] == "approved"
    assert _zeile(draft)["status"] == "rejected"
    akt = _verwerfungen(lead)
    assert akt[0]["payload"]["aus_status"] == "approved"
    assert akt[0]["payload"]["bestaetigt"] is True


def test_approved_linkedin_laesst_sich_wegraeumen():
    """Der gemessene Produktionsfall: fuer LinkedIn gibt es bewusst keinen
    Dispatcher (Stufe 3, Nr. 3). Ohne `entwurf_manuell_gesendet` lag so ein
    freigegebener Entwurf bis dahin bis in alle Ewigkeit in der Liste."""
    lead = _lead()
    draft = _entwurf(lead, status="approved", kanal="linkedin", fehler=None)
    ok = json.loads(server.entwurf_verwerfen(draft, bestaetigt=True))
    assert ok["status"] == "rejected"


# ---------------------------------------------------------------------------
# sent und pending: die beiden Zustaende, die hier NICHTS zu suchen haben
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bestaetigt", [False, True])
def test_sent_wird_niemals_verworfen(bestaetigt):
    """Was raus ist, ist raus — die Zeile ist der Zustellnachweis. Auch mit
    Bestaetigung nicht: es gibt keinen Zustand, in dem das richtig waere."""
    lead = _lead()
    draft = _entwurf(lead, status="sent", fehler=None)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft, bestaetigt=bestaetigt))
    assert "fehler" in kaputt
    assert "sent" in kaputt["fehler"]
    assert _zeile(draft) == vor
    assert _verwerfungen(lead) == []


@pytest.mark.parametrize("bestaetigt", [False, True])
def test_pending_verweist_auf_entwurf_ablehnen(bestaetigt):
    """Fuer offene Entwuerfe gibt es `entwurf_ablehnen` — fachlich derselbe
    Vorgang (pending -> rejected mit Protokollzeile). Es soll je Zustand genau
    EINEN Weg geben, und die Fehlermeldung muss ihn nennen, sonst sucht der
    naechste einen zweiten."""
    lead = _lead()
    draft = _entwurf(lead, status="pending", fehler=None)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft, bestaetigt=bestaetigt))
    assert "fehler" in kaputt
    assert "entwurf_ablehnen" in kaputt["fehler"]
    assert _zeile(draft) == vor
    assert _verwerfungen(lead) == []


def test_ablehnen_bleibt_der_weg_fuer_pending_und_wirkt_unveraendert():
    """Gegenprobe zur Abgrenzung: derselbe Entwurf, der oben abgewiesen wurde,
    geht ueber `entwurf_ablehnen` klaglos durch — und landet auf demselben
    Status, aber mit der Protokollzeile `ablehnung`."""
    lead = _lead()
    draft = _entwurf(lead, status="pending", fehler=None)
    ok = json.loads(server.entwurf_ablehnen(draft))
    assert ok["status"] == "rejected"
    assert len(server._q("select id from activities where lead_id = %s "
                         "and type = 'ablehnung'", (lead,))) == 1
    assert _verwerfungen(lead) == []


def test_bereits_rejected_sagt_es_und_schreibt_keine_zweite_zeile():
    lead = _lead()
    draft = _entwurf(lead, status="failed")
    server.entwurf_verwerfen(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft))
    assert "fehler" in kaputt
    assert "rejected" in kaputt["fehler"]
    assert len(_verwerfungen(lead)) == 1


def test_unbekannte_draft_id_gibt_fehlertext():
    kaputt = json.loads(
        server.entwurf_verwerfen("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# ---------------------------------------------------------------------------
# Die Claim-Marke — dieselbe Kante wie bei entwurf_erneut_freigeben,
# andersherum gelesen
# ---------------------------------------------------------------------------

def test_failed_mit_claim_marke_ohne_bestaetigung_wird_verweigert():
    """Die Marke steht VOR dem Sendeversuch. Ein Absturz zwischen Claim und
    Buchung heisst: moeglicherweise BEREITS BEIM EMPFAENGER — ein `rejected`
    saehe dann aus wie „nie rausgegangen"."""
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler=_CLAIM_MARKE)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft))
    assert "fehler" in kaputt
    assert _CLAIM_MARKE in kaputt["fehler"]
    assert _zeile(draft) == vor       # die Marke bleibt lesbar stehen
    assert _verwerfungen(lead) == []


def test_failed_mit_claim_marke_mit_bestaetigung_wird_rejected():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler=_CLAIM_MARKE)
    ok = json.loads(server.entwurf_verwerfen(draft, bestaetigt=True))
    assert ok["status"] == "rejected"
    assert ok["aus_status"] == "failed"


def test_approved_mit_claim_marke_wird_auch_mit_bestaetigung_verweigert():
    """Aus `approved` heraus gibt es keine Lage, in der die Marke stimmen
    koennte — die Zeile widerspraeche sich selbst. So etwas raeumt niemand
    beilaeufig weg, auch nicht mit Haekchen."""
    lead = _lead()
    draft = _entwurf(lead, status="approved", fehler=_CLAIM_MARKE)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_verwerfen(draft, bestaetigt=True))
    assert "fehler" in kaputt
    assert "ausnahmslos" in kaputt["fehler"]
    assert _zeile(draft) == vor
    assert _verwerfungen(lead) == []


def test_fremder_fehlertext_ist_keine_marke():
    """Nur der Praefix zaehlt. Ein Fehlertext, in dem „in Zustellung"
    IRGENDWO vorkommt, ist keine Claim-Marke — sonst haengte ein Entwurf
    fest, weil OpenWA das Wort in einer Meldung benutzt hat."""
    lead = _lead()
    draft = _entwurf(lead, status="failed",
                     fehler="OpenWA 500: Nachricht war nicht in Zustellung")
    ok = json.loads(server.entwurf_verwerfen(draft))
    assert ok["status"] == "rejected"


# ---------------------------------------------------------------------------
# Werkzeugschicht
# ---------------------------------------------------------------------------

def test_werkzeug_ist_registriert_und_traegt_seine_parameter():
    import inspect
    assert server.entwurf_verwerfen in server.WERKZEUGE
    parameter = inspect.signature(server.entwurf_verwerfen).parameters
    assert "draft_id" in parameter and "bestaetigt" in parameter
    assert parameter["bestaetigt"].default is False


def test_werkzeugbeschreibung_nennt_entwurf_ablehnen_als_weg_fuer_pending():
    """Ohne diesen Satz sucht der naechste Agent einen zweiten Weg fuer
    `pending` — und findet keinen."""
    assert "entwurf_ablehnen" in server.entwurf_verwerfen.__doc__
