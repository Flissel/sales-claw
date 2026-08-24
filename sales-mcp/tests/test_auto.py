"""Vertragstests der Auto-Antwort-Bruecke (sales-auto) gegen sales_test.

Der Modellaufruf ist gestubbt (auto.create_structured_response) — es geht in
diesen Tests zu keinem Zeitpunkt eine Anfrage an die OpenAI-API raus, und
versendet wird ohnehin nie (auto.py schreibt nur drafts/activities; die
Zustellung gehoert sales-dispatch und dessen Tests).

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os
import sys

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    aufrufe = []

    def _stub(**kwargs):
        aufrufe.append(kwargs)
        return auto.OpenAIResult(
            payload={"antwort": antwort,
                     "beraterin_noetig": beraterin,
                     "stopp_wunsch": stopp,
                     "begruendung": begruendung},
            response_id="resp_test",
            input_tokens=20,
            output_tokens=8,
            total_tokens=28,
        )

    monkeypatch.setattr(auto, "create_structured_response", _stub)
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
    monkeypatch.setattr(auto, "OPENAI_MAX_OUTPUT_TOKENS", "2345")
    aufrufe = _modell_ok(monkeypatch)
    lead = _lead(name="Anna Beispiel")
    server.profil_aktualisieren(lead, "beruf", "Baeckermeisterin")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'nachricht_ausgehend', %s) returning id",
              (lead, json.dumps({"text": "Guten Tag, Frau Beispiel!"})))
    _kundenantwort(lead, text="Wie sichere ich meinen Betrieb ab?",
                   vor_sekunden=0)
    auto.eine_runde()
    aufruf = aufrufe[0]
    assert aufruf["api_key"] == auto.OPENAI_API_KEY
    assert aufruf["model"] == auto.OPENAI_MODEL
    assert aufruf["instructions"] == auto.SYSTEM_PROMPT
    assert "Baeckermeisterin" in aufruf["input_text"]
    assert "Kunde: Wie sichere ich meinen Betrieb ab?" in aufruf["input_text"]
    assert "Wir: Guten Tag, Frau Beispiel!" in aufruf["input_text"]
    assert aufruf["schema_name"] == "auto_antwort"
    assert aufruf["schema"] == auto.ANTWORT_SCHEMA
    assert aufruf["max_output_tokens"] == 2345
    assert aufruf["timeout_s"] == auto.HTTP_TIMEOUT_S


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

    def _kaputt(**kwargs):
        aufrufe.append(kwargs)
        raise auto.OpenAIPermanentError("OpenAI HTTP 400")

    monkeypatch.setattr(auto, "create_structured_response", _kaputt)
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

    def _erst_kaputt_dann_ok(**kwargs):
        versuche.append(1)
        if len(versuche) == 1:
            raise auto.OpenAITransientError("OpenAI HTTP 429")
        return auto.OpenAIResult(
            payload={"antwort": "Gern!", "beraterin_noetig": False,
                     "stopp_wunsch": False, "begruendung": ""},
            response_id="resp_test",
            input_tokens=20,
            output_tokens=8,
            total_tokens=28,
        )

    monkeypatch.setattr(auto, "create_structured_response",
                        _erst_kaputt_dann_ok)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"aufgeschoben": 1}
    assert _aktivitaeten(lead, "auto_antwort") == [] and _drafts() == []
    assert auto.eine_runde() == {"beantwortet": 1}


def test_providerseitig_unbrauchbare_antwort_ist_endgueltig(monkeypatch):
    def _unbrauchbar(**kwargs):
        raise auto.OpenAIPermanentError("OpenAI response output is invalid")

    monkeypatch.setattr(auto, "create_structured_response", _unbrauchbar)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert _drafts() == []


@pytest.mark.parametrize("payload", [
    {"beraterin_noetig": False, "stopp_wunsch": False, "begruendung": ""},
    {"antwort": "Gern!", "stopp_wunsch": False, "begruendung": ""},
    {"antwort": "Gern!", "beraterin_noetig": False, "begruendung": ""},
    {"antwort": "Gern!", "beraterin_noetig": False,
     "stopp_wunsch": False},
    {"antwort": "Gern!", "beraterin_noetig": "false",
     "stopp_wunsch": False, "begruendung": ""},
    {"antwort": "Gern!", "beraterin_noetig": False,
     "stopp_wunsch": 0, "begruendung": ""},
    {"antwort": "Gern!", "beraterin_noetig": False,
     "stopp_wunsch": False, "begruendung": None},
    {"antwort": "Gern!", "beraterin_noetig": False,
     "stopp_wunsch": False, "begruendung": "", "extra": True},
], ids=["antwort-fehlt", "beraterin-fehlt", "stopp-fehlt",
        "begruendung-fehlt", "beraterin-kein-bool", "stopp-kein-bool",
        "begruendung-kein-string", "unbekannter-schluessel"])
def test_unbrauchbare_payloads_erzeugen_keinen_entwurf(monkeypatch, payload):
    monkeypatch.setattr(auto, "create_structured_response", lambda **kwargs: (
        auto.OpenAIResult(payload=payload, response_id="resp_invalid",
                          input_tokens=None, output_tokens=None,
                          total_tokens=None)))
    lead = _lead()
    _kundenantwort(lead)
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


@pytest.mark.parametrize("antwort", ["", "   "])
def test_leere_antwort_wird_nicht_gesendet(monkeypatch, antwort):
    _modell_ok(monkeypatch, antwort=antwort)
    lead = _lead()
    _kundenantwort(lead)
    assert auto.eine_runde() == {"fehler_verbucht": 1}
    assert _drafts() == []


def test_main_meldet_fehlende_openai_variablen_in_reihenfolge(monkeypatch):
    fehler = []
    monkeypatch.setattr(auto, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(auto.LOG, "error",
                        lambda meldung, *werte: fehler.append(meldung % werte))
    monkeypatch.setattr(auto, "OPENAI_API_KEY", "")
    monkeypatch.setattr(auto, "OPENAI_MODEL", "")
    assert auto.main() == 2
    assert "OPENAI_API_KEY" in fehler[-1]
    assert "OPENAI_MODEL" not in fehler[-1]

    monkeypatch.setattr(auto, "OPENAI_API_KEY", "test-key")
    assert auto.main() == 2
    assert "OPENAI_MODEL" in fehler[-1]
    assert "OPENAI_API_KEY" not in fehler[-1]


@pytest.mark.parametrize(
    "raw_value",
    ["", "kein-int", "0", "-1", "10001"],
    ids=["empty", "malformed", "zero", "negative", "over-safe-maximum"],
)
def test_main_rejects_invalid_openai_output_budget_before_processing(
    monkeypatch, raw_value
):
    fehler = []
    runden = []
    monkeypatch.setattr(auto, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(
        auto.LOG,
        "error",
        lambda meldung, *werte: fehler.append(meldung % werte),
    )
    monkeypatch.setattr(auto.LOG, "info", lambda *args: None)
    monkeypatch.setattr(auto, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto, "OPENAI_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(auto, "OPENAI_MAX_OUTPUT_TOKENS", raw_value, raising=False)
    monkeypatch.setattr(auto, "AUTO_ONCE", True)
    monkeypatch.setattr(auto, "eine_runde", lambda: runden.append(True) or {})

    assert auto.main() == 2
    assert runden == []
    assert "OPENAI_MAX_OUTPUT_TOKENS" in fehler[-1]


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
