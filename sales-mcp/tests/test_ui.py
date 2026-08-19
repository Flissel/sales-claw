"""Vertragstests des Freigabe-Frontends `sales-ui` (Stufe 10) gegen sales_test.

Das UI ist eine Lese-Sicht mit GENAU drei Schreibwegen — freigeben, ablehnen,
erneut freigeben — deren SQL-Bedingungen die Werkzeuge aus server.py spiegeln
(approved_by='betreiber-ui' als Audit-Unterschied). Getestet wird deshalb vor
allem die ABWEHR: CSRF-Fehlen/-Fälschung und fremde Host-Header dürfen NIE
eine Aktion auslösen, Fremddaten (Entwurfstexte, Namen, Fehlertexte) dürfen
NIE roh in einer Seite landen, und jeder Statusübergang greift nur aus dem
Zustand, aus dem auch das Chat-Werkzeug ihn erlaubt — inklusive der
Doppelversand-Marken-Verweigerung bei der erneuten Freigabe.
"""
import json
import os

import pytest

# HART, nicht setdefault (wie test_werkzeuge.py): eine von aussen gesetzte
# SALES_DB_SCHEMA=sales wuerde die truncate-Fixture auf Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

# Ein Client fuer alle Tests: der CSRF-Boot-Token lebt im Prozess, nicht in
# einer Session — es gibt keinen Zustand, den Tests sich teilen koennten.
CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def _post(pfad, daten, host=HOST_OK):
    # follow_redirects=False: der Erfolgsfall ist ein 303 auf die Inbox, und
    # genau der soll sichtbar bleiben statt stillschweigend aufgeloest.
    return CLIENT.post(pfad, data=daten, headers={"host": host},
                       follow_redirects=False)


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, status="pending", kanal="whatsapp", text="Hallo, passt Donnerstag?",
             fehler=None, approved_by=None, empfaenger="+491701234567"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, error, "
        "approved_by) values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (lead, kanal, empfaenger, text, status, fehler, approved_by))[0]["id"])


def _zeile(draft_id):
    return server._q("select status, approved_by, approved_at, error "
                     "from drafts where id = %s", (draft_id,))[0]


def _aktivitaeten(typ):
    return server._q("select payload from activities where type = %s "
                     "order by created_at", (typ,))


# ---------------------------------------------------------------------------
# CSRF: kein Token, kein Statuswechsel — fuer ALLE drei Aktionen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pfad", ["/aktion/freigeben", "/aktion/ablehnen",
                                  "/aktion/erneut-freigeben"])
def test_post_ohne_csrf_token_wird_abgewiesen_und_nichts_passiert(pfad):
    lead = _lead()
    ausgangsstatus = "failed" if pfad.endswith("erneut-freigeben") else "pending"
    draft = _entwurf(lead, status=ausgangsstatus,
                     fehler="OpenWA 500" if ausgangsstatus == "failed" else None)
    r = _post(pfad, {"draft_id": draft, "bestaetigt": "ja"})
    assert r.status_code == 403
    assert _zeile(draft)["status"] == ausgangsstatus
    assert _aktivitaeten("freigabe") == [] and _aktivitaeten("ablehnung") == []


@pytest.mark.parametrize("pfad", ["/aktion/freigeben", "/aktion/ablehnen",
                                  "/aktion/erneut-freigeben"])
def test_post_mit_falschem_csrf_token_wird_abgewiesen(pfad):
    lead = _lead()
    ausgangsstatus = "failed" if pfad.endswith("erneut-freigeben") else "pending"
    draft = _entwurf(lead, status=ausgangsstatus,
                     fehler="OpenWA 500" if ausgangsstatus == "failed" else None)
    r = _post(pfad, {"draft_id": draft, "csrf": "gefaelscht",
                     "bestaetigt": "ja"})
    assert r.status_code == 403
    assert _zeile(draft)["status"] == ausgangsstatus


def test_csrf_token_steht_in_den_formularen_der_inbox():
    lead = _lead()
    _entwurf(lead)
    seite = _get("/").text
    assert ui.CSRF_TOKEN in seite


# ---------------------------------------------------------------------------
# Host-Header: DNS-Rebinding laeuft ins Leere
# ---------------------------------------------------------------------------

def test_get_mit_fremdem_host_header_wird_abgewiesen():
    assert _get("/", host="boese.example").status_code == 421
    assert _get("/", host="boese.example:8791").status_code == 421


def test_post_mit_fremdem_host_wird_trotz_gueltigem_token_abgewiesen():
    """DNS-Rebinding-Kern: die fremde Domain zeigt auf 127.0.0.1 und der
    Browser schickt ihren Namen als Host — selbst MIT erbeutetem Token darf
    dann nichts passieren."""
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN},
              host="boese.example:8791")
    assert r.status_code == 421
    assert _zeile(draft)["status"] == "pending"


def test_localhost_und_loopback_sind_zulaessig():
    assert _get("/", host="127.0.0.1:8791").status_code == 200
    assert _get("/", host="localhost:8791").status_code == 200


# ---------------------------------------------------------------------------
# XSS: Fremddaten erscheinen escaped, nie roh — und die Seiten haben kein JS
# ---------------------------------------------------------------------------

def test_entwurfstext_mit_script_erscheint_escaped_nie_roh():
    lead = _lead()
    _entwurf(lead, text="<script>alert('xss')</script>")
    seite = _get("/").text
    assert "<script" not in seite
    assert "&lt;script&gt;" in seite


def test_fehlertext_und_kontaktname_erscheinen_escaped():
    lead = _lead(name='<img src=x onerror="alert(1)">')
    _entwurf(lead, status="failed", fehler='<svg onload="alert(2)">')
    seite = _get("/").text
    assert "<img" not in seite and "<svg" not in seite
    assert "&lt;img" in seite and "&lt;svg" in seite
    liste = _get("/kontakte").text
    assert "<img" not in liste and "&lt;img" in liste


@pytest.mark.parametrize("pfad", ["/", "/kontakte", "/posteingang",
                                  "/wiedervorlagen"])
def test_seiten_kommen_ohne_javascript_aus(pfad):
    seite = _get(pfad)
    assert seite.status_code == 200
    assert "<script" not in seite.text


# ---------------------------------------------------------------------------
# Freigeben: nur pending -> approved, approved_by='betreiber-ui'
# ---------------------------------------------------------------------------

def test_freigeben_pending_wird_approved_mit_betreiber_ui():
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    zeile = _zeile(draft)
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "betreiber-ui"
    assert zeile["approved_at"] is not None
    freigaben = _aktivitaeten("freigabe")
    assert len(freigaben) == 1
    assert freigaben[0]["payload"]["draft_id"] == draft
    assert freigaben[0]["payload"]["kanal"] == "whatsapp"


@pytest.mark.parametrize("status, approved_by", [
    ("approved", "betreiber"), ("rejected", None), ("sent", "betreiber"),
    ("failed", "betreiber"),
])
def test_freigeben_greift_nur_aus_pending(status, approved_by):
    lead = _lead()
    draft = _entwurf(lead, status=status, approved_by=approved_by)
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert status in r.text          # die Fehlermeldung nennt den Ist-Stand
    zeile = _zeile(draft)
    assert zeile["status"] == status
    # Der Audit-Eintrag der ERSTEN Freigabe bleibt unangetastet.
    assert zeile["approved_by"] == approved_by
    assert _aktivitaeten("freigabe") == []


# ---------------------------------------------------------------------------
# Ablehnen: nur pending -> rejected
# ---------------------------------------------------------------------------

def test_ablehnen_pending_wird_rejected():
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/ablehnen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert _zeile(draft)["status"] == "rejected"
    ablehnungen = _aktivitaeten("ablehnung")
    assert len(ablehnungen) == 1
    assert ablehnungen[0]["payload"]["draft_id"] == draft


@pytest.mark.parametrize("status", ["approved", "rejected", "sent", "failed"])
def test_ablehnen_greift_nur_aus_pending(status):
    lead = _lead()
    draft = _entwurf(lead, status=status)
    r = _post("/aktion/ablehnen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert _zeile(draft)["status"] == status
    assert _aktivitaeten("ablehnung") == []


# ---------------------------------------------------------------------------
# Erneut freigeben: nur failed -> approved, mit Bestaetigung, Marken-Fall
# verweigert (Semantik aus server.py, bestaetigt bleibt im UI immer False)
# ---------------------------------------------------------------------------

def test_erneut_freigeben_failed_mit_bestaetigung_wird_approved():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    r = _post("/aktion/erneut-freigeben",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN, "bestaetigt": "ja"})
    assert r.status_code == 303
    zeile = _zeile(draft)
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "betreiber-ui"
    assert zeile["error"] is None
    freigaben = _aktivitaeten("freigabe")
    assert len(freigaben) == 1
    assert freigaben[0]["payload"]["erneut"] is True


def test_erneut_freigeben_ohne_bestaetigung_wird_verweigert():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    r = _post("/aktion/erneut-freigeben",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"] == "OpenWA HTTP 500"
    assert _aktivitaeten("freigabe") == []


def test_erneut_freigeben_marken_fall_wird_auch_mit_haekchen_verweigert():
    """Die Claim-Marke des Dispatchers heisst: moeglicherweise BEREITS
    ZUGESTELLT. Das UI bietet die Doppelversand-Uebernahme bewusst NICHT an —
    dieser Weg bleibt dem Chat-Werkzeug mit bestaetigt=True vorbehalten."""
    lead = _lead()
    marke = "in Zustellung seit 2026-08-19T10:00:00+00:00 (dispatcher deadbeef)"
    draft = _entwurf(lead, status="failed", fehler=marke)
    r = _post("/aktion/erneut-freigeben",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN, "bestaetigt": "ja"})
    assert r.status_code == 409
    assert "Doppelversand" in r.text
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"] == marke       # die Marke bleibt lesbar stehen
    assert _aktivitaeten("freigabe") == []


@pytest.mark.parametrize("status", ["pending", "approved", "rejected", "sent"])
def test_erneut_freigeben_greift_nur_aus_failed(status):
    lead = _lead()
    draft = _entwurf(lead, status=status)
    r = _post("/aktion/erneut-freigeben",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN, "bestaetigt": "ja"})
    assert r.status_code == 409
    assert _zeile(draft)["status"] == status


# ---------------------------------------------------------------------------
# Unbekannte / unlesbare draft_id
# ---------------------------------------------------------------------------

def test_unbekannte_draft_id_gibt_404():
    r = _post("/aktion/freigeben",
              {"draft_id": "00000000-0000-0000-0000-000000000000",
               "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 404


def test_unlesbare_draft_id_gibt_400():
    r = _post("/aktion/freigeben",
              {"draft_id": "keine-uuid", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Freigabe-Inbox: Bloecke, LinkedIn-Sonderfall, Meta-Refresh
# ---------------------------------------------------------------------------

def test_inbox_zeigt_pending_failed_approved_und_gesendete():
    lead = _lead()
    _entwurf(lead, text="Pending-Text hier")
    _entwurf(lead, status="failed", fehler="Nummer nicht zustellbar")
    _entwurf(lead, status="approved", approved_by="betreiber",
             text="Wartender WhatsApp-Text")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent", text="Schon gesendeter Text"),))
    seite = _get("/").text
    assert "Pending-Text hier" in seite
    assert "Nummer nicht zustellbar" in seite
    assert "wartet auf Dispatcher" in seite
    assert "Schon gesendeter Text" in seite
    assert 'http-equiv="refresh" content="30"' in seite


def test_inbox_linkedin_sonderfall_nennt_den_handversand():
    lead = _lead()
    _entwurf(lead, status="approved", kanal="linkedin",
             approved_by="betreiber", text="LinkedIn-Post-Text")
    seite = _get("/").text
    assert "von Hand" in seite
    assert "entwurf_manuell_gesendet" in seite


# ---------------------------------------------------------------------------
# Kontakte
# ---------------------------------------------------------------------------

def test_kontaktliste_und_detailseite():
    lead = _lead(name="Anna Beispiel")
    server._q("update leads set enrichment = %s where id = %s returning id",
              (json.dumps({
                  "bedarf": {"alter": {"antwort": "34", "at": "2026-08-19"}},
                  "vertraege": [{"sparte": "Haftpflicht",
                                 "gesellschaft": "Testversicherer",
                                 "ablauf": "2027-01-01"}]}), lead))
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'nachricht', %s) returning id",
              (lead, json.dumps({"inhalt": "mit Kundin telefoniert"})))
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'wiedervorlage', %s) returning id",
              (lead, json.dumps({"faellig_am": "2026-09-01",
                                 "notiz": "Vertragsablauf pruefen"})))
    liste = _get("/kontakte").text
    assert "Anna Beispiel" in liste
    detail = _get(f"/kontakte/{lead}").text
    assert "Anna Beispiel" in detail
    assert "Haftpflicht" in detail            # Vertraege aus enrichment
    assert "34" in detail                     # Bedarfsstand
    assert "mit Kundin telefoniert" in detail  # Aktivitaeten
    assert "Vertragsablauf pruefen" in detail  # Wiedervorlage des Kontakts


def test_unbekannter_kontakt_gibt_404():
    assert _get("/kontakte/00000000-0000-0000-0000-000000000000").status_code == 404
    assert _get("/kontakte/keine-uuid").status_code == 404


# ---------------------------------------------------------------------------
# Posteingang: spiegelt das Werkzeug (unbeantwortet zuerst, LID-Kennzeichnung)
# ---------------------------------------------------------------------------

def _kundenantwort(lead, text="Passt Donnerstag?", absender="491701234567@c.us"):
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'kundenantwort', %s, 'human') returning id",
              (lead, json.dumps({"text": text, "richtung": "eingehend",
                                 "absender": absender,
                                 "message_id": f"wa-{text[:8]}"})))


def test_posteingang_zeigt_unbeantwortete():
    lead = _lead()
    _kundenantwort(lead)
    seite = _get("/posteingang").text
    assert "Max Testperson" in seite
    assert "Passt Donnerstag?" in seite


def test_posteingang_beantwortetes_verschwindet():
    lead = _lead()
    _kundenantwort(lead)
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'nachricht_ausgehend', %s) returning id",
              (lead, json.dumps({"richtung": "ausgehend",
                                 "empfaenger": "491701234567@c.us"})))
    assert "Passt Donnerstag?" not in _get("/posteingang").text


def test_posteingang_kennzeichnet_lid_pseudo_kennungen():
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = sammel
    try:
        _kundenantwort(sammel, text="Wer bin ich?", absender="123456789@lid")
        seite = _get("/posteingang").text
    finally:
        server.UNBEKANNT_LEAD_ID = vorher
    assert "123456789@lid" in seite
    assert "Pseudo-Kennung" in seite


# ---------------------------------------------------------------------------
# Wiedervorlagen: offene nach Faelligkeit, erledigte verschwinden
# ---------------------------------------------------------------------------

def test_wiedervorlagen_offene_nach_faelligkeit_erledigte_fehlen():
    lead = _lead()
    spaet = str(server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'wiedervorlage', %s) returning id",
        (lead, json.dumps({"faellig_am": "2026-12-24", "notiz": "Spaete"})))[0]["id"])
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'wiedervorlage', %s) returning id",
              (lead, json.dumps({"faellig_am": "2026-08-01", "notiz": "Fruehe"})))
    erledigt = str(server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'wiedervorlage', %s) returning id",
        (lead, json.dumps({"faellig_am": "2026-08-15", "notiz": "Erledigte"})))[0]["id"])
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'wiedervorlage_erledigt', %s) returning id",
              (lead, json.dumps({"wiedervorlage_id": erledigt})))
    seite = _get("/wiedervorlagen").text
    assert "Erledigte" not in seite
    assert seite.index("Fruehe") < seite.index("Spaete")
    assert spaet  # angelegt und offen — die Reihenfolge oben prueft beide
