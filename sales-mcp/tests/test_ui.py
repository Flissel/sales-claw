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
    return server._q("select lead_id, payload, actor from activities "
                     "where type = %s order by created_at", (typ,))


# --- Einordnung (Stufe 11 in der Oberflaeche) -------------------------------
# Gemessene Werte aus test_einordnung.py, damit beide Suiten ueber dieselbe
# Person reden: Sophies Privacy-Kennung und ihre echte Rufnummer.
SOPHIE_LID = "183096603361451@lid"
SOPHIE_NUMMER = "491729186846@c.us"
SOPHIE_PHONE = "+49 172 9186846"


@pytest.fixture
def sammelkontakt_zurueck():
    """`server.UNBEKANNT_LEAD_ID` ist ein Modulattribut aus der Umgebung —
    wer es fuer einen Test umbiegt, muss es zuruecklegen (Muster aus
    test_einordnung.py)."""
    vorher = server.UNBEKANNT_LEAD_ID
    yield
    server.UNBEKANNT_LEAD_ID = vorher


def _sammel():
    """Der Sammelkontakt „Unbekannte Eingaenge" — ohne ihn ist die Einordnung
    blind. Nur zusammen mit der Fixture `sammelkontakt_zurueck` benutzen."""
    lead = _lead(name="Unbekannte Eingaenge", phone=None)
    server.UNBEKANNT_LEAD_ID = lead
    return lead


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
                                  "/einordnung", "/wiedervorlagen"])
def test_seiten_kommen_ohne_javascript_aus(pfad):
    seite = _get(pfad)
    assert seite.status_code == 200
    assert "<script" not in seite.text


def test_fremddaten_brechen_nicht_aus_attribut_kontext_aus():
    """Ein Anfuehrungszeichen in einem Wert, der in ein value="…"/href="…"
    landet, darf das Attribut nicht schliessen. Sichert html.escape(quote=True)
    gegen eine Regression auf quote=False, die die reinen Element-Tests
    (oben) NICHT faengt."""
    lead = _lead(name='Anna"><script>alert(1)</script>')
    _entwurf(lead, empfaenger='+49"><img src=x onerror=alert(2)>')
    seite = _get("/").text
    assert '"><script' not in seite
    assert '"><img' not in seite
    assert "&quot;&gt;" in seite  # das Zeichen ist da, aber escaped
    liste = _get("/kontakte").text
    assert '"><script' not in liste


# ---------------------------------------------------------------------------
# Schutz-Koepfe: Framing (Clickjacking) und Sniffing sind gesperrt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pfad", ["/", "/kontakte", "/posteingang",
                                  "/einordnung", "/wiedervorlagen"])
def test_schutzkoepfe_auf_jeder_seite(pfad):
    """Ohne frame-ancestors/X-Frame-Options waere das CSRF-Token per
    Clickjacking umgehbar (fremde Seite rahmt die UI, Overlay ueber den
    Freigeben-Knopf)."""
    r = _get(pfad)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_schutzkoepfe_auch_auf_der_host_fehlerseite():
    # Die 421-Abweisung bei fremdem Host darf ebenfalls nicht rahmbar sein.
    r = _get("/", host="boese.example")
    assert r.status_code == 421
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


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
    # Herkunft: ein Mensch am UI, nicht der Agent — sonst waere die Freigabe im
    # append-only-Log falsch attribuiert.
    assert freigaben[0]["actor"] == "human"
    assert freigaben[0]["payload"]["weg"] == "ui"


def test_ablehnen_wird_als_human_geloggt():
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/ablehnen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    ablehnungen = _aktivitaeten("ablehnung")
    assert len(ablehnungen) == 1
    assert ablehnungen[0]["actor"] == "human"
    assert ablehnungen[0]["payload"]["weg"] == "ui"


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

def test_einordnung_seite_ohne_sammelkontakt_sagt_es(sammelkontakt_zurueck):
    """Ohne INBOX_UNBEKANNT_LEAD_ID kann `_einzuordnende` nichts finden — die
    Seite waere dann leer, ohne zu sagen warum. Der Fall ist real: die
    Compose-Definition von sales-ui hatte die Variable zunaechst nicht."""
    server.UNBEKANNT_LEAD_ID = ""
    seite = _get("/einordnung")
    assert seite.status_code == 200
    assert "INBOX_UNBEKANNT_LEAD_ID" in seite.text


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


# ---------------------------------------------------------------------------
# Einordnung (/einordnung): die Rueckfrage „wer ist das?" in der Oberflaeche
#
# Betreiber-Wunsch 21.08.2026: nicht mehr im WhatsApp-Chat beantworten, sondern
# hier — mit dem vollen Nachrichtentext vor Augen und einem Klick je Absender.
# Getestet wird wie beim Rest des UI vor allem die ABWEHR: ohne gueltiges
# CSRF-Token und unter fremdem Host darf KEINE der Aktionen eine Zeile
# schreiben, Nachrichtentexte sind Fremddaten (der wichtigste XSS-Vektor dieser
# Seite), und die H3-Schutzkante aus server.eingang_einordnen — ein echter
# Kontakt laesst sich nicht beilaeufig stummschalten — muss in der Oberflaeche
# ein ZWEITER, ausdruecklicher Schritt sein statt ein Haekchen neben dem Knopf.
# ---------------------------------------------------------------------------

EINORDNUNG_AKTIONEN = ["/einordnung/ignorieren", "/einordnung/zuordnen",
                       "/einordnung/anlegen",
                       "/einordnung/ignorieren-bestaetigen"]


def _einordnung_daten(ziel):
    """Ein Formularsatz, der fuer JEDE der vier Routen vollstaendig waere —
    damit ein 403/421 nachweislich am Token bzw. am Host haengt und nicht
    daran, dass ein Feld fehlte."""
    return {"absender": SOPHIE_LID, "lead_id": ziel, "name": "Neu Person",
            "lead_bestaetigt": ziel}


def _nichts_geschrieben():
    """Keine Einordnung, keine Zuordnung, kein neuer Kontakt."""
    return (_aktivitaeten(server.ABSENDER_IGNORIERT) == []
            and _aktivitaeten(server.ABSENDER_BEACHTET) == []
            and _aktivitaeten(server.LID_ZUORDNUNG) == []
            and server._q("select id from leads where name = %s",
                          ("Neu Person",)) == [])


@pytest.mark.parametrize("pfad", EINORDNUNG_AKTIONEN)
@pytest.mark.parametrize("token", [None, "gefaelscht"])
def test_einordnung_post_ohne_gueltiges_csrf_schreibt_nichts(
        pfad, token, sammelkontakt_zurueck):
    sammel = _sammel()
    ziel = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    daten = _einordnung_daten(ziel)
    if token:
        daten["csrf"] = token
    r = _post(pfad, daten)
    assert r.status_code == 403
    assert _nichts_geschrieben()


@pytest.mark.parametrize("pfad", EINORDNUNG_AKTIONEN)
def test_einordnung_post_mit_fremdem_host_schreibt_nichts(
        pfad, sammelkontakt_zurueck):
    """DNS-Rebinding: selbst MIT erbeutetem Token darf unter fremdem Namen
    nichts passieren — die Host-Wache laeuft vor jeder Route."""
    sammel = _sammel()
    ziel = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    daten = _einordnung_daten(ziel)
    daten["csrf"] = ui.CSRF_TOKEN
    r = _post(pfad, daten, host="boese.example:8791")
    assert r.status_code == 421
    assert _nichts_geschrieben()


def test_einordnung_seite_mit_fremdem_host_wird_abgewiesen():
    assert _get("/einordnung", host="boese.example:8791").status_code == 421


def test_einordnung_csrf_token_steht_in_den_formularen(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    seite = _get("/einordnung").text
    assert ui.CSRF_TOKEN in seite
    for pfad in ("/einordnung/zuordnen", "/einordnung/anlegen",
                 "/einordnung/ignorieren"):
        assert f'action="{pfad}"' in seite


# --- XSS: der Nachrichtentext ist das gefaehrlichste Feld dieser Seite ------

def test_einordnung_nachrichtentext_erscheint_escaped_nie_roh(
        sammelkontakt_zurueck):
    """Elementkontext und der Ausbruchsversuch aus einem Attribut in einem
    Zug: der Text kommt von einem FREMDEN, der sich gerade vorstellen soll."""
    sammel = _sammel()
    _kundenantwort(
        sammel, absender=SOPHIE_LID,
        text='<script>alert(1)</script> und Anna"><img src=x onerror=alert(2)>')
    seite = _get("/einordnung").text
    assert "<script" not in seite
    assert "&lt;script&gt;" in seite
    assert '"><img' not in seite
    assert "&lt;img" in seite
    assert "&quot;&gt;" in seite      # das Zeichen ist da, aber escaped


def test_einordnung_kennung_bricht_nicht_aus_dem_hidden_feld_aus(
        sammelkontakt_zurueck):
    """Die Kennung landet in `value="…"` mehrerer Hidden-Felder. Sichert
    html.escape(quote=True) gegen eine Regression auf quote=False, die der
    reine Elementtest oben NICHT faengt."""
    sammel = _sammel()
    boese = '4917012345">@c.us'
    _kundenantwort(sammel, text="Harmloser Text", absender=boese)
    seite = _get("/einordnung").text
    assert '">@c.us' not in seite
    assert "&quot;&gt;@c.us" in seite


def test_einordnung_zeigt_mehr_text_als_der_chat(sammelkontakt_zurueck):
    """Der Grund fuer die Seite: im Chat steht ein 120-Zeichen-Zitat, hier soll
    der Betreiber lesen koennen, worum es geht — gedeckelt bleibt es
    trotzdem."""
    sammel = _sammel()
    _kundenantwort(sammel, text="A" * 600, absender=SOPHIE_LID)
    seite = _get("/einordnung").text
    assert "A" * (server.EINORDNUNG_TEXT_MAX + 1) in seite
    assert "A" * (ui.EINORDNUNG_TEXT_MAX + 1) not in seite


# --- Die Seite selbst -------------------------------------------------------

def test_einordnung_zeigt_neue_und_bereits_gefragte_in_einem_topf(
        sammelkontakt_zurueck):
    """Im Chat sind das zwei Toepfe, weil die Frage dort GESTELLT wird und nur
    einmal gestellt werden darf. Hier wird sie gezeigt, nicht gestellt — also
    ist beides schlicht „wartet auf Entscheidung"."""
    sammel = _sammel()
    _kundenantwort(sammel, text="Erste Person", absender=SOPHIE_LID)
    _kundenantwort(sammel, text="Zweite Person",
                   absender="222096603361451@lid")
    # Fuer die eine steht die Rueckfrage schon (wie nach einem Chat-Aufruf).
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, %s, %s, 'agent') returning id",
              (sammel, server.ABSENDER_RUECKFRAGE,
               json.dumps({"absender": SOPHIE_LID,
                           "kennung": "183096603361451"})))
    seite = _get("/einordnung").text
    assert "Wartet auf Entscheidung (2)" in seite
    assert "Erste Person" in seite and "Zweite Person" in seite
    assert "im Chat gefragt am" in seite and "noch nicht gefragt" in seite


def test_einordnung_seitenaufruf_beansprucht_keine_rueckfrage(
        sammelkontakt_zurueck):
    """Die Seite liest, sie fragt nicht. Wuerde sie server.eingang_einordnen()
    ohne Argumente rufen, entstuende bei JEDEM Seitenaufruf ein
    Rueckfrage-Anspruch — ein GET, das schreibt, und der Chat kaeme nie mehr
    dazu, den Betreiber zu fragen."""
    sammel = _sammel()
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    assert _get("/einordnung").status_code == 200
    assert _get("/einordnung").status_code == 200
    assert _aktivitaeten(server.ABSENDER_RUECKFRAGE) == []


def test_einordnung_zeigt_den_kontaktnamen_als_warnung_am_eintrag(
        sammelkontakt_zurueck):
    """Gehoert die Kennung einem echten Kontakt, muss das AM EINTRAG stehen —
    bevor jemand auf „Ignorieren" drueckt, nicht erst danach.

    Die Kennung steht hier als WhatsApp-JID (`…@s.whatsapp.net`). Genau dafuer
    fragt die Oberflaeche zusaetzlich Python-seitig mit `lid_kanonisch` +
    `_lead_mit_gleicher_nummer` nach: die SQL-Aufloesung in `_einzuordnende`
    greift nur bei `@c.us`/`@lid`, und ohne die zweite Frage stuende dieser
    Absender ohne Warnung da — waehrend `eingang_einordnen` das Ignorieren sehr
    wohl verweigerte. Anzeige und Verweigerung sollen nie Verschiedenes
    behaupten."""
    sammel = _sammel()
    _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Ich habe unterschrieben",
                   absender="491729186846@s.whatsapp.net")
    seite = _get("/einordnung").text
    assert "Wartet auf Entscheidung (1)" in seite
    assert "Sophie Beispiel" in seite
    assert "zweiten, ausdruecklichen Schritt" in seite


def test_einordnung_zeigt_entschiedene_als_verlauf(sammelkontakt_zurueck):
    sammel = _sammel()
    _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Ich habe unterschrieben",
                   absender=SOPHIE_NUMMER)
    seite = _get("/einordnung").text
    assert "Bereits entschieden (1)" in seite
    assert "Sophie Beispiel" in seite
    assert "Wartet auf Entscheidung (0)" in seite


# --- ignorieren: ohne Lead wirkt es, mit Lead braucht es zwei Schritte ------

def test_ignorieren_eines_absenders_ohne_lead_wirkt(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Werbung, Werbung", absender=SOPHIE_LID)
    r = _post("/einordnung/ignorieren",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert server.absender_ist_ignoriert(SOPHIE_LID) is True
    zeilen = _aktivitaeten(server.ABSENDER_IGNORIERT)
    assert len(zeilen) == 1
    assert zeilen[0]["actor"] == "human"
    assert zeilen[0]["payload"]["absender"] == SOPHIE_LID
    # Er verschwindet aus der Seite, ohne dass etwas geloescht wurde.
    assert SOPHIE_LID not in _get("/einordnung").text
    assert len(_aktivitaeten("kundenantwort")) == 1


def test_ignorieren_eines_absenders_mit_lead_gibt_warnseite_ohne_wirkung(
        sammelkontakt_zurueck):
    """Die H3-Kante in der Oberflaeche. Erreichbar, sobald der Kontakt zwischen
    Seitenaufbau und Klick entsteht (im Chat, im zweiten Tab) — genau der Fall,
    den ein vorangekreuztes Haekchen neben dem Knopf durchgehen liesse."""
    sammel = _sammel()
    lead = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Ich habe den Vertrag unterschrieben",
                   absender=SOPHIE_NUMMER)
    r = _post("/einordnung/ignorieren",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert "Sophie Beispiel" in r.text
    # Das eigene Formular des zweiten Schritts, mit eigenem Hidden-Feld.
    assert 'action="/einordnung/ignorieren-bestaetigen"' in r.text
    assert f'name="lead_bestaetigt" value="{lead}"' in r.text
    # KEINE Zeile in der Datenbank.
    assert _aktivitaeten(server.ABSENDER_IGNORIERT) == []
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is False


def test_erst_der_zweite_ausdrueckliche_post_ignoriert_einen_echten_kontakt(
        sammelkontakt_zurueck):
    sammel = _sammel()
    lead = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Ich habe den Vertrag unterschrieben",
                   absender=SOPHIE_NUMMER)
    assert _post("/einordnung/ignorieren",
                 {"absender": SOPHIE_NUMMER,
                  "csrf": ui.CSRF_TOKEN}).status_code == 409
    r = _post("/einordnung/ignorieren-bestaetigen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN,
               "lead_bestaetigt": lead})
    assert r.status_code == 303
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is True
    zeilen = _aktivitaeten(server.ABSENDER_IGNORIERT)
    # Eine Zeile am Sammelkontakt UND eine am betroffenen Lead: sonst waere im
    # Verlauf des Kontakts nicht erklaerbar, warum er verstummt ist (H3).
    assert len(zeilen) == 2
    assert len([z for z in zeilen if str(z["lead_id"]) == lead]) == 1
    assert all(z["actor"] == "human" for z in zeilen)


def test_bestaetigen_ohne_das_eigene_hidden_feld_wirkt_nicht(
        sammelkontakt_zurueck):
    """Der zweite Schritt ist nicht bloss eine zweite URL: ohne die lead_id,
    die auf der Warnseite stand, passiert nichts."""
    sammel = _sammel()
    _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_NUMMER)
    r = _post("/einordnung/ignorieren-bestaetigen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert _aktivitaeten(server.ABSENDER_IGNORIERT) == []
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is False


def test_bestaetigen_fuer_einen_anderen_kontakt_wirkt_nicht(
        sammelkontakt_zurueck):
    """Die Bestaetigung gilt dem Kontakt, dessen Namen der Betreiber GELESEN
    hat. Passt sie nicht mehr zum aktuellen Stand, wird nichts getan."""
    sammel = _sammel()
    _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    fremd = _lead(name="Anna Andere", phone="+491701234567")
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_NUMMER)
    r = _post("/einordnung/ignorieren-bestaetigen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN,
               "lead_bestaetigt": fremd})
    assert r.status_code == 409
    assert _aktivitaeten(server.ABSENDER_IGNORIERT) == []
    assert server.absender_ist_ignoriert(SOPHIE_NUMMER) is False


def test_einordnung_unlesbare_kennung_wirkt_nicht(sammelkontakt_zurueck):
    _sammel()
    r = _post("/einordnung/ignorieren",
              {"absender": "keine-kennung", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert _aktivitaeten(server.ABSENDER_IGNORIERT) == []


# --- zuordnen ---------------------------------------------------------------

def test_zuordnen_zu_bestehendem_kontakt_wirkt(sammelkontakt_zurueck):
    sammel = _sammel()
    ziel = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Hallo, ich bin es", absender=SOPHIE_LID)
    r = _post("/einordnung/zuordnen",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN, "lead_id": ziel})
    assert r.status_code == 303
    zuordnungen = _aktivitaeten(server.LID_ZUORDNUNG)
    assert len(zuordnungen) == 1
    assert zuordnungen[0]["payload"]["lid"] == "183096603361451"
    assert zuordnungen[0]["payload"]["telefon"] == SOPHIE_NUMMER
    assert zuordnungen[0]["payload"]["quelle"] == "betreiber"
    # Danach gehoert die Kennung dem Kontakt: sie steht im Verlauf, nicht mehr
    # unter „wartet auf Entscheidung".
    seite = _get("/einordnung").text
    assert "Wartet auf Entscheidung (0)" in seite
    assert "Bereits entschieden (1)" in seite
    assert "Sophie Beispiel" in seite


def test_zuordnen_ohne_gewaehlten_kontakt_wirkt_nicht(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_LID)
    r = _post("/einordnung/zuordnen",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN, "lead_id": ""})
    assert r.status_code == 400
    assert _aktivitaeten(server.LID_ZUORDNUNG) == []


def test_zuordnen_zu_einem_kontakt_ohne_nummer_nennt_den_grund(
        sammelkontakt_zurueck):
    """Die Fehlermeldung des Werkzeugs steht unveraendert auf der Seite — sie
    ist fuer einen Menschen geschrieben und nennt den naechsten Schritt."""
    sammel = _sammel()
    ohne = _lead(name="Ohne Nummer", phone=None)
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_LID)
    r = _post("/einordnung/zuordnen",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN, "lead_id": ohne})
    assert r.status_code == 400
    assert "kontakt_aktualisieren" in r.text
    assert _aktivitaeten(server.LID_ZUORDNUNG) == []


# --- anlegen: der Weg, den eingang_einordnen dafuer vorsieht ----------------
#
# `ENTSCHEIDUNGEN` kennt nur zuordnen/ignorieren/beachten — fuer einen NEUEN
# Kontakt nennt der Docstring von eingang_einordnen ausdruecklich den Umweg:
# „erst kontakt_anlegen(name, phone=…), dann hier zuordnen". Traegt der neue
# Kontakt die Rufnummer der Kennung, ist der zweite Schritt schon erledigt:
# `_einzuordnende` findet ihn ueber `_lead_mit_gleicher_nummer` von selbst.

def test_anlegen_erzeugt_den_kontakt_mit_der_rufnummer_der_kennung(
        sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Hallo, ich bin neu hier",
                   absender=SOPHIE_NUMMER)
    r = _post("/einordnung/anlegen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN,
               "name": "Sophie Neu"})
    assert r.status_code == 303
    neu = server._q("select id, phone, source from leads where name = %s",
                    ("Sophie Neu",))
    assert len(neu) == 1
    assert neu[0]["phone"] == "+491729186846"
    assert neu[0]["source"] == "whatsapp"
    assert r.headers["location"] == f"/kontakte/{neu[0]['id']}"
    # Der Absender ist damit eingeordnet, ohne dass ein zweites Werkzeug lief.
    koerbe = server._einzuordnende()
    assert koerbe["neu"] == [] and koerbe["bereits_gefragt"] == []
    assert [e["kontakt"] for e in koerbe["aufgeloest"]] == ["Sophie Neu"]


def test_anlegen_einer_bereits_aufgeloesten_lid_nimmt_die_gespeicherte_nummer(
        sammelkontakt_zurueck):
    """Steht zur `@lid` schon eine Zuordnung, ist die Rufnummer bekannt — dann
    darf angelegt werden, ohne dass die Oberflaeche irgendwen fragen muss."""
    sammel = _sammel()
    server.lid_zuordnung_speichern(SOPHIE_LID, SOPHIE_NUMMER, "betreiber",
                                   server.lid.TYP_RUFNUMMER)
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_LID)
    r = _post("/einordnung/anlegen",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN,
               "name": "Sophie Neu"})
    assert r.status_code == 303
    neu = server._q("select phone from leads where name = %s", ("Sophie Neu",))
    assert neu[0]["phone"] == "+491729186846"


def test_anlegen_einer_unaufgeloesten_lid_wird_verweigert(
        sammelkontakt_zurueck):
    """Eine `@lid` ist WhatsApps Pseudo-Kennung und keine Rufnummer; sie als
    `phone` einzutragen war Review-Befund H1. Die Aufloesung kostet
    Rate-Limit-Budget bei OpenWA und bleibt darum Chat-Sache — die Seite sagt
    das, statt zu raten."""
    sammel = _sammel()
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_LID)
    r = _post("/einordnung/anlegen",
              {"absender": SOPHIE_LID, "csrf": ui.CSRF_TOKEN,
               "name": "Wer Auch Immer"})
    assert r.status_code == 400
    assert "absender_aufloesen" in r.text
    assert server._q("select id from leads where name = %s",
                     ("Wer Auch Immer",)) == []


def test_anlegen_ohne_namen_wirkt_nicht(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_NUMMER)
    r = _post("/einordnung/anlegen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN,
               "name": "   "})
    assert r.status_code == 400
    assert server._q("select id from leads where phone = %s",
                     ("+491729186846",)) == []


def test_anlegen_legt_keinen_zweiten_kontakt_zur_selben_nummer_an(
        sammelkontakt_zurueck):
    """Die Dedup-Kante aus kontakt_anlegen (Demo-Befund B1) gilt auch hier —
    das UI erbt sie, weil es das Werkzeug ruft statt selbst einzufuegen."""
    sammel = _sammel()
    vorhanden = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_NUMMER)
    r = _post("/einordnung/anlegen",
              {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN,
               "name": "Sophie Doppelt"})
    assert r.status_code == 303
    assert r.headers["location"] == f"/kontakte/{vorhanden}"
    assert server._q("select id from leads where name = %s",
                     ("Sophie Doppelt",)) == []
