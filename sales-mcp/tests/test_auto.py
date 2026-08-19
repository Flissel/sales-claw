"""Vertragstests der Auto-Antwort-Bruecke (sales-auto) gegen sales_test.

Der Modellaufruf ist gestubbt (auto._api_aufruf) — es geht in diesen Tests
zu keinem Zeitpunkt eine Anfrage an die Anthropic-API raus, und versendet
wird ohnehin nie (auto.py schreibt nur drafts/activities; die Zustellung
gehoert sales-dispatch und dessen Tests).

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auto  # noqa: E402
import dispatch  # noqa: E402
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


@pytest.fixture(autouse=True)
def kurzes_sammelfenster(monkeypatch):
    """Vorgabe fuer die Tests: kein Warten. Das Fenster selbst prueft
    test_sammelfenster_verzoegert explizit."""
    monkeypatch.setattr(auto, "SAMMELFENSTER_S", 0)


def _lead(name="Max Testperson", phone="+491701234567", freigegeben=True):
    enrichment = ({"whatsapp_freigabe": {"freigegeben": True}}
                  if freigegeben else {})
    return server._q(
        "insert into leads (name, phone, source, enrichment) values "
        "(%s, %s, 'whatsapp', %s) returning id",
        (name, phone, json.dumps(enrichment)))[0]["id"]


def _kundenantwort(lead_id, text="Was kostet bei Ihnen eine Absicherung?",
                   vor_sekunden=0, message_id="wamid-1"):
    return server._q(
        "insert into activities (lead_id, type, payload, actor, created_at) "
        "values (%s, 'kundenantwort', %s, 'human', now() - make_interval("
        "secs => %s)) returning id",
        (lead_id, json.dumps({"text": text, "message_id": message_id,
                              "richtung": "eingehend"}),
         vor_sekunden))[0]["id"]


def _modell_ok(monkeypatch, antwort="Gern! Passt Ihnen Donnerstag 14 Uhr?",
               beraterin=False, stopp=False, begruendung=""):
    """Stub: eine wohlgeformte Messages-API-Antwort mit dem JSON-Ergebnis."""
    aufrufe = []

    def _stub(nutzlast):
        aufrufe.append(nutzlast)
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps({
                "antwort": antwort, "beraterin_noetig": beraterin,
                "stopp_wunsch": stopp, "begruendung": begruendung})}]}
    monkeypatch.setattr(auto, "_api_aufruf", _stub)
    return aufrufe


def _drafts():
    return server._q("select id, lead_id, channel, recipient, body, status, "
                     "approved_by from drafts order by created_at")


def _aktivitaeten(lead_id, typ):
    return server._q("select payload from activities where lead_id = %s "
                     "and type = %s order by created_at", (lead_id, typ))


# ---------------------------------------------------------------------------
# Der bestellte Weg
# ---------------------------------------------------------------------------

def test_freigegebener_kontakt_bekommt_approved_entwurf(monkeypatch):
    """Kundennachricht -> Entwurf mit status='approved' — die Zustellung
    uebernimmt der bestehende Dispatcher, kein neuer Versandweg."""
    _modell_ok(monkeypatch)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"beantwortet": 1}
    zeilen = _drafts()
    assert len(zeilen) == 1
    z = zeilen[0]
    assert (z["status"], z["approved_by"], z["channel"]) == (
        "approved", "auto-betrieb", "whatsapp")
    assert z["recipient"] == "+491701234567"
    assert "Donnerstag" in z["body"]
    anspruch = _aktivitaeten(lead, "auto_antwort")
    assert len(anspruch) == 1
    assert anspruch[0]["payload"]["draft_id"] == str(z["id"])
    assert anspruch[0]["payload"]["message_id"] == "wamid-1"


def test_ohne_freigabe_passiert_nichts(monkeypatch):
    aufrufe = _modell_ok(monkeypatch)
    lead = _lead(freigegeben=False)
    _kundenantwort(lead)
    assert auto.eine_runde() == {}
    assert _drafts() == [] and aufrufe == []


def test_entzug_nach_der_kundennachricht_stoppt_die_antwort(monkeypatch):
    _modell_ok(monkeypatch)
    lead = _lead()
    _kundenantwort(lead)
    server.kontakt_freigabe_entziehen(lead)
    assert auto.eine_runde() == {}
    assert _drafts() == []


def test_bereits_beantwortete_nachricht_wird_uebersprungen(monkeypatch):
    aufrufe = _modell_ok(monkeypatch)
    lead = _lead()
    _kundenantwort(lead, vor_sekunden=120)
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'nachricht_ausgehend', %s) returning id",
              (lead, json.dumps({"text": "Schon von Hand beantwortet."})))
    assert auto.eine_runde() == {}
    assert aufrufe == []


def test_hoechstens_ein_versuch_je_kundennachricht(monkeypatch):
    """At-most-once: die zweite Runde findet den Anspruch und schweigt."""
    _modell_ok(monkeypatch)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"beantwortet": 1}
    assert auto.eine_runde() == {}
    assert len(_drafts()) == 1


def test_sammelfenster_verzoegert(monkeypatch):
    """Innerhalb des Fensters wird gewartet — wer noch tippt, bekommt EINE
    Antwort auf alles, nicht eine je Nachricht."""
    aufrufe = _modell_ok(monkeypatch)
    monkeypatch.setattr(auto, "SAMMELFENSTER_S", 3600)
    lead = _lead()
    _kundenantwort(lead)          # gerade eben — juenger als das Fenster
    assert auto.eine_runde() == {}
    assert aufrufe == []
    monkeypatch.setattr(auto, "SAMMELFENSTER_S", 0)
    assert auto.eine_runde() == {"beantwortet": 1}


def test_sammelkontakte_werden_nie_beantwortet(monkeypatch):
    """Am Sammelkontakt haengen viele Menschen — Auto-Antworten waeren dort
    automatisch falsch, selbst wenn jemand ihm das Flag setzt."""
    aufrufe = _modell_ok(monkeypatch)
    sammel = _lead(name="Unbekannte Eingaenge", phone="")
    monkeypatch.setattr(auto, "SAMMEL_LEAD_IDS", (str(sammel),))
    _kundenantwort(sammel)
    assert auto.eine_runde() == {}
    assert aufrufe == []


def test_verlauf_und_profil_landen_im_modellauftrag(monkeypatch):
    aufrufe = _modell_ok(monkeypatch)
    lead = _lead(name="Anna Beispiel")
    server.profil_aktualisieren(lead, "beruf", "Baeckermeisterin")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'nachricht_ausgehend', %s) returning id",
              (lead, json.dumps({"text": "Guten Tag, Frau Beispiel!"})))
    _kundenantwort(lead, text="Wie sichere ich meinen Betrieb ab?",
                   vor_sekunden=0)
    auto.eine_runde()
    auftrag = aufrufe[0]["messages"][0]["content"]
    assert "Baeckermeisterin" in auftrag
    assert "Kunde: Wie sichere ich meinen Betrieb ab?" in auftrag
    assert "Wir: Guten Tag, Frau Beispiel!" in auftrag
    assert aufrufe[0]["model"] == auto.AUTO_MODELL
    assert aufrufe[0]["output_config"]["format"]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# Signale — was der Betreiber sehen muss
# ---------------------------------------------------------------------------

def test_stopp_wunsch_erzeugt_offenen_punkt_und_nur_bestaetigung(monkeypatch):
    _modell_ok(monkeypatch, antwort="Alles klar, Sie hoeren nichts mehr von uns.",
               stopp=True, begruendung="Kunde bat um Stopp.")
    lead = _lead()
    _kundenantwort(lead, text="Bitte keine Nachrichten mehr.")
    assert auto.eine_runde() == {"beantwortet": 1}
    punkte = _aktivitaeten(lead, "offener_punkt")
    assert len(punkte) == 1
    assert "kontakt_freigabe_entziehen" in punkte[0]["payload"]["inhalt"]
    assert _drafts()[0]["body"].startswith("Alles klar")


def test_beraterin_noetig_erzeugt_offenen_punkt(monkeypatch):
    _modell_ok(monkeypatch, beraterin=True,
               begruendung="Frage nach Beitragshoehe (§34d).")
    lead = _lead()
    _kundenantwort(lead, text="Was kostet die BU im Monat?")
    auto.eine_runde()
    punkte = _aktivitaeten(lead, "offener_punkt")
    assert len(punkte) == 1
    assert "Beraterin" in punkte[0]["payload"]["inhalt"]


# ---------------------------------------------------------------------------
# Fehlerordnung — endgueltig vs. voruebergehend
# ---------------------------------------------------------------------------

def test_endgueltiger_fehler_wird_verbucht_und_nie_wiederholt(monkeypatch):
    aufrufe = []

    def _kaputt(nutzlast):
        aufrufe.append(nutzlast)
        raise auto.AutoFehler("Anthropic HTTP 400: kaputtes Schema")
    monkeypatch.setattr(auto, "_api_aufruf", _kaputt)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert _drafts() == []
    anspruch = _aktivitaeten(lead, "auto_antwort")
    assert "HTTP 400" in anspruch[0]["payload"]["fehler"]
    assert auto.eine_runde() == {}          # nie wiederholt
    assert len(aufrufe) == 1


def test_transienter_fehler_laesst_keinen_anspruch_zurueck(monkeypatch):
    """429/5xx/Netz: nichts gesendet, nichts verbucht — die naechste Runde
    darf es erneut versuchen, und dann klappt es."""
    versuche = []

    def _erst_kaputt_dann_ok(nutzlast):
        versuche.append(1)
        if len(versuche) == 1:
            raise auto.AutoTransient("Anthropic HTTP 529: ueberlastet")
        return {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps({
                "antwort": "Gern!", "beraterin_noetig": False,
                "stopp_wunsch": False, "begruendung": ""})}]}
    monkeypatch.setattr(auto, "_api_aufruf", _erst_kaputt_dann_ok)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"aufgeschoben": 1}
    assert _aktivitaeten(lead, "auto_antwort") == [] and _drafts() == []
    assert auto.eine_runde() == {"beantwortet": 1}


def test_refusal_und_kaputtes_json_sind_endgueltig(monkeypatch):
    lead = _lead()
    _kundenantwort(lead)
    monkeypatch.setattr(auto, "_api_aufruf",
                        lambda n: {"stop_reason": "refusal", "content": []})
    assert auto.eine_runde() == {"fehler_verbucht": 1}

    lead2 = _lead(name="Zweite Person", phone="+491702222222")
    _kundenantwort(lead2, message_id="wamid-2")
    monkeypatch.setattr(auto, "_api_aufruf", lambda n: {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "kein json"}]})
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert _drafts() == []


def test_unzustellbare_nummer_wird_ohne_modellkosten_verbucht(monkeypatch):
    aufrufe = _modell_ok(monkeypatch)
    lead = _lead(phone="0170123456")     # national — gilt als nicht zustellbar
    _kundenantwort(lead)
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert aufrufe == [] and _drafts() == []
    anspruch = _aktivitaeten(lead, "auto_antwort")
    assert "zustellbare Nummer" in anspruch[0]["payload"]["fehler"]


def test_zu_lange_antwort_wird_nicht_gesendet(monkeypatch):
    _modell_ok(monkeypatch, antwort="x" * (auto.ANTWORT_MAXLAENGE + 1))
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert _drafts() == []


# ---------------------------------------------------------------------------
# Ende-zu-Ende mit dem Dispatcher — die ganze Bruecke
# ---------------------------------------------------------------------------

def test_der_entwurf_geht_durch_den_normalen_dispatcher(monkeypatch):
    _modell_ok(monkeypatch, antwort="Gern — passt Ihnen Donnerstag?")
    gesendet = []
    monkeypatch.setattr(dispatch, "sende_text",
                        lambda chat_id, text: gesendet.append((chat_id, text)))
    lead = _lead()
    _kundenantwort(lead)
    auto.eine_runde()
    draft_id = server._q("select id from drafts")[0]["id"]
    assert dispatch.verarbeite_draft(draft_id) == "gesendet"
    assert gesendet == [("491701234567@c.us", "Gern — passt Ihnen Donnerstag?")]
    zeile = server._q("select status from drafts where id = %s", (draft_id,))[0]
    assert zeile["status"] == "sent"
