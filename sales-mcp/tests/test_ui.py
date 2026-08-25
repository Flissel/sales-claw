"""Vertragstests des Freigabe-Frontends `sales-ui` (Stufe 10) gegen sales_test.

Das UI ist eine Lese-Sicht mit GENAU vier Schreibwegen auf `drafts` —
freigeben, ablehnen, erneut freigeben, verwerfen — deren SQL-Bedingungen die
Werkzeuge aus server.py spiegeln (approved_by='betreiber-ui' als
Audit-Unterschied). Getestet wird deshalb vor allem die ABWEHR: CSRF-Fehlen/
-Fälschung und fremde Host-Header dürfen NIE eine Aktion auslösen, Fremddaten
(Entwurfstexte, Namen, Fehlertexte, Reporttexte) dürfen NIE roh in einer Seite
landen, und jeder Statusübergang greift nur aus dem Zustand, aus dem auch das
Chat-Werkzeug ihn erlaubt — inklusive der Marken-Verweigerung, die bei der
erneuten Freigabe den Doppelversand und beim Verwerfen die verdeckte
Zustellung verhindert.
"""
import json
import os
import re

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
# Verwerfen (Betreiber-Wunsch 22.08.2026): failed einschrittig, approved
# zweistufig, Marken-Fall ausnahmslos verweigert
#
# Die Zweistufigkeit ist hier dieselbe wie bei `ignorieren-bestaetigen` und
# `archivieren-bestaetigen`: erster POST schreibt NICHTS, zweiter POST auf
# eigener Route traegt den Wert, den der Betreiber gelesen hat.
# ---------------------------------------------------------------------------

_VERWERF_MARKE = ("in Zustellung seit 2026-08-22T09:00:00+00:00 "
                  "(dispatcher beef0001)")


def _verwerfungen():
    return server._q("select lead_id, payload, actor from activities "
                     "where type = 'verwerfung' order by created_at")


@pytest.mark.parametrize("pfad", ["/aktion/verwerfen",
                                  "/aktion/verwerfen-bestaetigen"])
def test_verwerfen_ohne_csrf_wird_abgewiesen_und_nichts_passiert(pfad):
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA 500")
    r = _post(pfad, {"draft_id": draft, "empfaenger_bestaetigt": "+491701234567"})
    assert r.status_code == 403
    assert _zeile(draft)["status"] == "failed"
    assert _verwerfungen() == []


@pytest.mark.parametrize("pfad", ["/aktion/verwerfen",
                                  "/aktion/verwerfen-bestaetigen"])
def test_verwerfen_mit_falschem_csrf_wird_abgewiesen(pfad):
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA 500")
    r = _post(pfad, {"draft_id": draft, "csrf": "gefaelscht",
                     "empfaenger_bestaetigt": "+491701234567"})
    assert r.status_code == 403
    assert _zeile(draft)["status"] == "failed"


def test_verwerfen_mit_fremdem_host_wird_trotz_gueltigem_token_abgewiesen():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA 500")
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN},
              host="boese.example:8791")
    assert r.status_code == 421
    assert _zeile(draft)["status"] == "failed"


def test_verwerfen_knopf_steht_an_failed_und_approved_entwuerfen():
    lead = _lead()
    _entwurf(lead, status="failed", fehler="OpenWA 500")
    _entwurf(lead, status="approved", approved_by="betreiber")
    seite = _get("/").text
    assert seite.count('action="/aktion/verwerfen"') == 2


def test_verwerfen_knopf_steht_nicht_an_pending_und_gesendeten():
    lead = _lead()
    _entwurf(lead, status="pending")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent"),))
    seite = _get("/").text
    assert 'action="/aktion/verwerfen"' not in seite


def test_failed_wird_einschrittig_verworfen():
    lead = _lead()
    draft = _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert _zeile(draft)["status"] == "rejected"
    akt = _verwerfungen()
    assert len(akt) == 1
    # actor='human' und weg='ui' — sonst waere die Entscheidung eines
    # Menschen im append-only-Log von einer Agenten-Entscheidung nicht zu
    # unterscheiden, und nachtragen laesst sie sich nie.
    assert akt[0]["actor"] == "human"
    assert akt[0]["payload"]["weg"] == "ui"
    assert akt[0]["payload"]["aus_status"] == "failed"
    assert akt[0]["payload"]["draft_id"] == draft


def test_approved_erster_post_zeigt_nur_die_warnseite_und_schreibt_nichts():
    lead = _lead()
    draft = _entwurf(lead, status="approved", approved_by="betreiber",
                     text="Guten Tag, hier der vereinbarte Termin")
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert "Guten Tag, hier der vereinbarte Termin" in r.text
    assert "+491701234567" in r.text
    assert 'action="/aktion/verwerfen-bestaetigen"' in r.text
    assert _zeile(draft)["status"] == "approved"
    assert _verwerfungen() == []


def test_approved_zweiter_post_verwirft():
    lead = _lead()
    draft = _entwurf(lead, status="approved", approved_by="betreiber")
    r = _post("/aktion/verwerfen-bestaetigen",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN,
               "empfaenger_bestaetigt": "+491701234567"})
    assert r.status_code == 303
    assert _zeile(draft)["status"] == "rejected"
    akt = _verwerfungen()
    assert akt[0]["actor"] == "human"
    assert akt[0]["payload"]["aus_status"] == "approved"


def test_approved_zweiter_post_ohne_bestaetigten_empfaenger_tut_nichts():
    lead = _lead()
    draft = _entwurf(lead, status="approved", approved_by="betreiber")
    r = _post("/aktion/verwerfen-bestaetigen",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert _zeile(draft)["status"] == "approved"


def test_approved_zweiter_post_mit_veraendertem_empfaenger_tut_nichts():
    """Zwischen Warnseite und Klick kann sich die Lage geaendert haben. Dann
    ist das Ja von eben kein Ja zu dem, was jetzt passieren wuerde."""
    lead = _lead()
    draft = _entwurf(lead, status="approved", approved_by="betreiber")
    server._q("update drafts set recipient = '+491700000099' where id = %s "
              "returning id", (draft,))
    r = _post("/aktion/verwerfen-bestaetigen",
              {"draft_id": draft, "csrf": ui.CSRF_TOKEN,
               "empfaenger_bestaetigt": "+491701234567"})
    assert r.status_code == 409
    assert _zeile(draft)["status"] == "approved"
    assert _verwerfungen() == []


@pytest.mark.parametrize("pfad", ["/aktion/verwerfen",
                                  "/aktion/verwerfen-bestaetigen"])
def test_marken_fall_wird_ausnahmslos_verweigert(pfad):
    """Dieselbe Marke wie beim erneuten Freigeben, andersherum gelesen: hier
    waere ein `rejected` die Luege, die eine erfolgte Zustellung verdeckt.
    Die Oberflaeche bietet die Uebernahme grundsaetzlich nicht an."""
    for status in ("failed", "approved"):
        lead = _lead()
        draft = _entwurf(lead, status=status, fehler=_VERWERF_MARKE)
        r = _post(pfad, {"draft_id": draft, "csrf": ui.CSRF_TOKEN,
                         "empfaenger_bestaetigt": "+491701234567"})
        assert r.status_code == 409, (pfad, status)
        assert "bereits" in r.text
        zeile = _zeile(draft)
        assert zeile["status"] == status
        assert zeile["error"] == _VERWERF_MARKE   # die Marke bleibt lesbar
    assert _verwerfungen() == []


def test_pending_verweist_auf_ablehnen_und_bleibt_unberuehrt():
    lead = _lead()
    draft = _entwurf(lead, status="pending")
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert "Ablehnen" in r.text
    assert _zeile(draft)["status"] == "pending"


def test_sent_bleibt_stehen():
    lead = _lead()
    draft = _entwurf(lead, status="sent")
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert _zeile(draft)["status"] == "sent"
    assert _verwerfungen() == []


def test_verwerfen_unbekannte_draft_id_gibt_404():
    r = _post("/aktion/verwerfen",
              {"draft_id": "00000000-0000-0000-0000-000000000000",
               "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 404


def test_verwerfen_warnseite_escaped_den_entwurfstext():
    lead = _lead()
    draft = _entwurf(lead, status="approved", approved_by="betreiber",
                     text='<script>alert("weg")</script>')
    r = _post("/aktion/verwerfen", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert "<script" not in r.text
    assert "&lt;script&gt;" in r.text


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


# --- Chat-Reports auf der Kontaktseite (Betreiber-Wunsch 22.08.2026) --------
#
# Die Oberflaeche ZEIGT sie nur. Geschrieben werden Reports im Chat
# (`chat_report_speichern`), weil dort das Sprachmodell sitzt, das den Text
# verfasst — eine Oberflaeche ohne Modell haette dafuer nichts in der Hand.

def _chat_nachrichten(lead, anzahl, ab_minute=1000, typ="kundenantwort",
                      praefix="Zeile"):
    """`praefix` unterscheidet die Stapel voneinander — ohne ihn hiesse die
    erste Nachricht jedes Stapels „… 1", und ein Test, der „taucht nicht mehr
    auf" prueft, fiele auf den gleichnamigen Text des naechsten Stapels
    herein (genau so beim ersten Lauf passiert)."""
    return [str(z["id"]) for z in server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "select %s, %s, jsonb_build_object('text', %s || ' ' || g), "
        "       now() - make_interval(mins => %s - g) "
        "  from generate_series(1, %s) g returning id",
        (lead, typ, praefix, ab_minute, anzahl))]


def test_kontaktseite_zeigt_reports_statt_der_abgedeckten_zeilen():
    lead = _lead(name="Anna Beispiel")
    _chat_nachrichten(lead, 6, ab_minute=1000, praefix="Frueher")
    server.chat_report_speichern(lead, "Kundin fragt nach bAV, Termin offen.")
    _chat_nachrichten(lead, 2, ab_minute=500, praefix="Danach")
    seite = _get(f"/kontakte/{lead}").text
    assert "Chat-Reports (1)" in seite
    assert "Kundin fragt nach bAV, Termin offen." in seite
    assert "Frueher 1" not in seite      # vom Report abgedeckt
    assert "Danach 1" in seite           # danach eingegangen, also offen
    assert "Geloescht ist nichts" in seite


def test_kontaktseite_ohne_report_zeigt_den_verlauf_unveraendert():
    lead = _lead(name="Anna Beispiel")
    _chat_nachrichten(lead, 3)
    seite = _get(f"/kontakte/{lead}").text
    assert "Chat-Reports" not in seite
    assert "Zeile 1" in seite


def test_kontaktseite_escaped_den_reporttext():
    """Der Reporttext ist Agententext ueber Kundennachrichten — also
    Fremddatum wie jedes andere auf dieser Seite."""
    lead = _lead(name="Anna Beispiel")
    _chat_nachrichten(lead, 3)
    server.chat_report_speichern(lead, '<script>alert("report")</script>')
    seite = _get(f"/kontakte/{lead}").text
    assert "<script" not in seite
    assert "&lt;script&gt;" in seite


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


# ---------------------------------------------------------------------------
# Kontaktpflege (/kontakte/{id}): bearbeiten und archivieren
#
# Betreiber-Wunsch 21.08.2026. LOESCHEN ist ausdruecklich NICHT Teil davon und
# wird auch nicht gebaut: `sales_app` hat auf `sales` kein DELETE-Recht, und
# `activities.lead_id` haengt mit ON DELETE CASCADE am Kontakt — ein Loeschen
# naehme die gesamte Historie mit und hebelte die append-only-Garantie ueber
# den Umweg aus. Statt zu loeschen wird archiviert (Merkmal in
# `leads.enrichment`, Muster `whatsapp_freigabe`), und das ist rueckgaengig zu
# machen.
#
# Getestet wird wie beim Rest des UI vor allem die ABWEHR: ohne gueltiges
# CSRF-Token und unter fremdem Host schreibt keine der vier Routen eine Zeile;
# Stammdaten sind Fremddaten und stehen im Formular im ATTRIBUTKONTEXT
# (value="…"); ein ungueltiger Wert laesst die Datenbank unberuehrt; und das
# Archivieren verlangt — wie das Ignorieren eines echten Kontakts — einen
# zweiten, ausdruecklichen Schritt.
# ---------------------------------------------------------------------------

KONTAKT_AKTIONEN = ["/kontakte/bearbeiten", "/kontakte/archivieren",
                    "/kontakte/archivieren-bestaetigen",
                    "/kontakte/wiederherstellen"]


def _kontakt_daten(lead):
    """Ein Formularsatz, der fuer JEDE der vier Routen vollstaendig waere —
    damit ein 403/421 nachweislich am Token bzw. am Host haengt und nicht
    daran, dass ein Feld fehlte."""
    return {"lead_id": lead, "name": "Umbenannt Person",
            "phone": "+491729999999", "email": "neu@example.de",
            "name_bestaetigt": "Max Testperson"}


def _stamm(lead):
    return server._q("select name, email, phone, status, consent_status, "
                     "enrichment from leads where id = %s", (lead,))[0]


def _ist_archiviert(lead):
    return server._archiviert(_stamm(lead)["enrichment"])


def _unveraendert(lead):
    """Stammdaten wie von _lead() angelegt, nicht archiviert, kein Protokoll."""
    zeile = _stamm(lead)
    return (zeile["name"] == "Max Testperson"
            and zeile["phone"] == "+491701234567"
            and zeile["email"] is None
            and not server._archiviert(zeile["enrichment"])
            and _aktivitaeten("korrektur") == []
            and _aktivitaeten("kontakt_archiviert") == [])


# --- Abwehr: CSRF und Host ---------------------------------------------------

@pytest.mark.parametrize("pfad", KONTAKT_AKTIONEN)
@pytest.mark.parametrize("token", [None, "gefaelscht"])
def test_kontaktpflege_post_ohne_gueltiges_csrf_schreibt_nichts(pfad, token):
    lead = _lead()
    daten = _kontakt_daten(lead)
    if token:
        daten["csrf"] = token
    r = _post(pfad, daten)
    assert r.status_code == 403
    assert _unveraendert(lead)


@pytest.mark.parametrize("pfad", KONTAKT_AKTIONEN)
def test_kontaktpflege_post_mit_fremdem_host_schreibt_nichts(pfad):
    """DNS-Rebinding: selbst MIT erbeutetem Token darf unter fremdem Namen
    nichts passieren — die Host-Wache laeuft vor jeder Route."""
    lead = _lead()
    daten = _kontakt_daten(lead)
    daten["csrf"] = ui.CSRF_TOKEN
    r = _post(pfad, daten, host="boese.example:8791")
    assert r.status_code == 421
    assert _unveraendert(lead)


def test_kontaktpflege_csrf_token_steht_in_den_formularen():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert ui.CSRF_TOKEN in seite
    for pfad in ("/kontakte/bearbeiten", "/kontakte/archivieren"):
        assert f'action="{pfad}"' in seite


# --- XSS: Stammdaten stehen im Formular im Attributkontext -------------------

def test_kontaktdaten_brechen_nicht_aus_dem_formularfeld_aus():
    """`value="…"` ist Attributkontext. Ein Anfuehrungszeichen im Namen darf
    das Attribut nicht schliessen — sonst waere der Rest der Zeile Markup."""
    lead = _lead(name='Anna"><script>alert(1)</script>',
                 phone='+49"><img src=x onerror=alert(2)>')
    seite = _get(f"/kontakte/{lead}").text
    assert "<script" not in seite and "<img" not in seite
    assert '"><script' not in seite and '"><img' not in seite
    assert "&lt;script&gt;" in seite and "&quot;&gt;" in seite
    # Auch in der Liste (dort steht der Name neben einem href).
    liste = _get("/kontakte").text
    assert '"><script' not in liste and "&lt;script&gt;" in liste


# --- Bearbeiten --------------------------------------------------------------

def test_bearbeiten_formular_bietet_genau_die_felder_des_werkzeugs():
    """Die Oberflaeche haelt KEINE eigene Whitelist — sie liest
    server.KONTAKT_FELDER. Status und Consent stehen bewusst nicht drin: die
    Einwilligung entsteht aus einer Antwort des Kontakts (bedarf_speichern),
    nicht aus einem Formularfeld."""
    assert set(server.KONTAKT_FELDER) == {"phone", "email", "name"}
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    for feld in server.KONTAKT_FELDER:
        assert f'name="{feld}"' in seite
    assert 'name="status"' not in seite
    assert 'name="consent_status"' not in seite
    assert 'name="enrichment"' not in seite


def test_bearbeiten_aendert_genau_die_erlaubten_felder_und_protokolliert():
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Maxi Testperson", "phone": "+491729186846",
               "email": "maxi@example.de",
               # Mitgeschickt, aber nicht erlaubt: darf spurlos verpuffen.
               "status": "won", "consent_status": "opt_in",
               "enrichment": '{"boese": true}'})
    assert r.status_code == 303
    zeile = _stamm(lead)
    assert zeile["name"] == "Maxi Testperson"
    assert zeile["phone"] == "+491729186846"
    assert zeile["email"] == "maxi@example.de"
    # Genau das, was das Werkzeug nicht erlaubt, ist unveraendert geblieben.
    assert zeile["status"] == "new"
    assert zeile["consent_status"] == "unknown"
    assert "boese" not in json.dumps(zeile["enrichment"])
    # Protokoll: je Feld eine Zeile des Werkzeugs (mit vorher/nachher) plus
    # GENAU EINE Herkunftszeile der Oberflaeche — actor='human', weg='ui'.
    zeilen = _aktivitaeten("korrektur")
    menschlich = [z for z in zeilen if z["actor"] == "human"]
    assert len(menschlich) == 1
    assert menschlich[0]["payload"]["weg"] == "ui"
    assert sorted(menschlich[0]["payload"]["felder"]) == ["email", "name",
                                                          "phone"]
    werkzeug = [z for z in zeilen if z["actor"] != "human"]
    assert len(werkzeug) == 3
    assert {z["payload"]["feld"] for z in werkzeug} == {"name", "phone",
                                                        "email"}
    alt = [z for z in werkzeug if z["payload"]["feld"] == "name"][0]
    assert alt["payload"]["vorher"] == "Max Testperson"


def test_bearbeiten_ohne_aenderung_schreibt_keine_zeile():
    """Ein Speichern ohne Aenderung ist kein Ereignis — sonst waere der
    Verlauf nach einem Tag Blaettern voller leerer Korrekturen."""
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Max Testperson", "phone": "+491701234567",
               "email": ""})
    assert r.status_code == 303
    assert _aktivitaeten("korrektur") == []


def test_bearbeiten_lehnt_kaputte_nummer_ab_ohne_etwas_zu_aendern():
    """Nationale Schreibweise (0170…) ist laut nummern.py nicht zustellbar.
    Der Name im selben Formular darf davon NICHT halb angewandt werden."""
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Maxi Testperson", "phone": "0170 1234567",
               "email": ""})
    assert r.status_code == 400
    assert "Landesvorwahl" in r.text
    assert _unveraendert(lead)


def test_bearbeiten_lehnt_kaputte_mailadresse_ab():
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Max Testperson", "phone": "+491701234567",
               "email": "max@localhost"})
    assert r.status_code == 400
    assert _unveraendert(lead)


def test_bearbeiten_lehnt_leeren_namen_ab():
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN, "name": "   ",
               "phone": "+491701234567", "email": ""})
    assert r.status_code == 400
    assert _unveraendert(lead)


def test_bearbeiten_leert_ein_feld_aber_nie_den_namen():
    lead = _lead()
    server.kontakt_aktualisieren(lead_id=lead, feld="email",
                                 wert="alt@example.de")
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Max Testperson", "phone": "+491701234567",
               "email": ""})
    assert r.status_code == 303
    assert _stamm(lead)["email"] is None


def test_bearbeiten_nennt_die_folgen_einer_neuen_telefonnummer():
    """Die Nummer ist der Schluessel, ueber den eingehende Nachrichten
    zugeordnet werden — das Werkzeug erlaubt die Aenderung, also sagt die
    Oberflaeche beim Speichern, was sie bewirkt."""
    lead = _lead()
    r = _post("/kontakte/bearbeiten",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name": "Max Testperson", "phone": "+491729186846",
               "email": ""})
    assert r.status_code == 303
    assert r.headers["location"] == f"/kontakte/{lead}?gespeichert=telefon"
    seite = _get(r.headers["location"]).text
    assert "Telefonnummer geaendert" in seite
    assert "Sammelkontakt" in seite
    # Ohne den Abfrageteil steht der Hinweis NICHT auf der Seite.
    assert "Telefonnummer geaendert" not in _get(f"/kontakte/{lead}").text


def test_bearbeiten_unbekannter_kontakt_gibt_404():
    r = _post("/kontakte/bearbeiten",
              {"lead_id": "00000000-0000-0000-0000-000000000000",
               "csrf": ui.CSRF_TOKEN, "name": "Wer auch immer"})
    assert r.status_code == 404


def test_bearbeiten_unlesbare_lead_id_gibt_400():
    r = _post("/kontakte/bearbeiten",
              {"lead_id": "keine-uuid", "csrf": ui.CSRF_TOKEN, "name": "X"})
    assert r.status_code == 400


# --- Archivieren: zwei Schritte, und kein DELETE ----------------------------

def test_archivieren_erster_post_zeigt_nur_die_warnseite():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'nachricht', %s) returning id",
              (lead, json.dumps({"inhalt": "telefoniert"})))
    _entwurf(lead, status="pending")
    r = _post("/kontakte/archivieren", {"lead_id": lead,
                                        "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert "Max Testperson" in r.text
    assert "1</b> Aktivitaet(en)" in r.text
    assert "1</b> offene Entwuerfe" in r.text
    # Das eigene Formular des zweiten Schritts, mit eigenem Hidden-Feld.
    assert 'action="/kontakte/archivieren-bestaetigen"' in r.text
    assert 'name="name_bestaetigt" value="Max Testperson"' in r.text
    # KEINE Zeile in der Datenbank.
    assert _unveraendert(lead)


def test_archivieren_zweiter_post_wirkt_und_wird_protokolliert():
    lead = _lead()
    r = _post("/kontakte/archivieren-bestaetigen",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name_bestaetigt": "Max Testperson"})
    assert r.status_code == 303
    assert _ist_archiviert(lead) is True
    zeilen = _aktivitaeten("kontakt_archiviert")
    # Eine Zeile des Werkzeugs und eine Herkunftszeile der Oberflaeche.
    assert len(zeilen) == 2
    menschlich = [z for z in zeilen if z["actor"] == "human"]
    assert len(menschlich) == 1
    assert menschlich[0]["payload"] == {"archiviert": True, "weg": "ui"}


def test_archivieren_bestaetigen_ohne_hidden_feld_wirkt_nicht():
    lead = _lead()
    r = _post("/kontakte/archivieren-bestaetigen",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert _unveraendert(lead)


def test_archivieren_bestaetigen_fuer_einen_anderen_namen_wirkt_nicht():
    """Die Bestaetigung gilt dem Kontakt, dessen Namen der Betreiber GELESEN
    hat — wurde er zwischendurch umbenannt, wird nichts getan."""
    lead = _lead()
    r = _post("/kontakte/archivieren-bestaetigen",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name_bestaetigt": "Jemand Anderes"})
    assert r.status_code == 409
    assert _unveraendert(lead)


def test_archivieren_veraendert_keine_einzige_aktivitaet():
    """Der Kern des „archivieren statt loeschen": die Historie bleibt
    vollzaehlig. Ein DELETE naehme sie mit — activities haengt mit ON DELETE
    CASCADE am Kontakt."""
    lead = _lead()
    for text in ("erstes Gespraech", "zweites Gespraech"):
        server._q("insert into activities (lead_id, type, payload) "
                  "values (%s, 'nachricht', %s) returning id",
                  (lead, json.dumps({"inhalt": text})))
    vorher = server._q("select id, type, payload, actor, created_at from "
                       "activities where lead_id = %s order by created_at",
                       (lead,))
    assert len(vorher) == 2
    r = _post("/kontakte/archivieren-bestaetigen",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
               "name_bestaetigt": "Max Testperson"})
    assert r.status_code == 303
    nachher = server._q("select id, type, payload, actor, created_at from "
                        "activities where lead_id = %s and type = 'nachricht' "
                        "order by created_at", (lead,))
    assert nachher == vorher
    # Der Verlauf auf der Kontaktseite zeigt sie weiterhin, alle beide.
    seite = _get(f"/kontakte/{lead}").text
    assert "erstes Gespraech" in seite and "zweites Gespraech" in seite
    assert "archiviert" in seite


def test_archivierter_kontakt_fehlt_in_der_liste_und_kommt_mit_schalter():
    lead = _lead(name="Weggeraeumt Person")
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Weggeraeumt Person"})
    liste = _get("/kontakte").text
    assert "Weggeraeumt Person" not in liste
    assert "auch archivierte zeigen" in liste
    mit_archiv = _get("/kontakte?archiv=1").text
    assert "Weggeraeumt Person" in mit_archiv
    assert "archiviert" in mit_archiv
    # Ueber die Adresse bleibt er erreichbar — nichts ist verschwunden.
    assert _get(f"/kontakte/{lead}").status_code == 200


def test_archivierter_kontakt_laesst_sich_wiederherstellen():
    lead = _lead(name="Zurueck Person")
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Zurueck Person"})
    assert _ist_archiviert(lead) is True
    r = _post("/kontakte/wiederherstellen",
              {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert _ist_archiviert(lead) is False
    assert "Zurueck Person" in _get("/kontakte").text
    # Gegen-Ereignis statt Zuruecknehmen: alle vier Zeilen stehen im Protokoll
    # (je Schritt eine des Werkzeugs und eine der Oberflaeche).
    zeilen = _aktivitaeten("kontakt_archiviert")
    assert [z["payload"]["archiviert"] for z in zeilen] == [True, True,
                                                            False, False]


def test_archivierter_kontakt_fehlt_im_posteingang():
    lead = _lead(name="Still Person")
    _kundenantwort(lead, text="Meldet sich noch jemand?")
    assert "Still Person" in _get("/posteingang").text
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Still Person"})
    seite = _get("/posteingang").text
    assert "Still Person" not in seite
    assert "Meldet sich noch jemand?" not in seite
    # Auch die Zahl stimmt — sonst zaehlte der Kopf Eintraege, die fehlen.
    assert json.loads(server.posteingang())["anzahl_unbeantwortet"] == 0


def test_archivierter_kontakt_fehlt_in_der_zuordnungsauswahl(
        sammelkontakt_zurueck):
    sammel = _sammel()
    ziel = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    assert f'<option value="{ziel}">' in _get("/einordnung").text
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": ziel, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Sophie Beispiel"})
    assert f'<option value="{ziel}">' not in _get("/einordnung").text


def test_schon_archivierter_kontakt_wird_nicht_zweimal_archiviert():
    lead = _lead()
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Max Testperson"})
    r = _post("/kontakte/archivieren", {"lead_id": lead,
                                        "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409
    assert len(_aktivitaeten("kontakt_archiviert")) == 2


def test_sammelkontakt_laesst_sich_nicht_archivieren(sammelkontakt_zurueck):
    """An ihm haengt jede Nachricht einer noch unbekannten Nummer — archiviert
    waere der Posteingang fuer Unbekannte blind."""
    sammel = _sammel()
    r = _post("/kontakte/archivieren-bestaetigen",
              {"lead_id": sammel, "csrf": ui.CSRF_TOKEN,
               "name_bestaetigt": "Unbekannte Eingaenge"})
    assert r.status_code == 400
    assert _ist_archiviert(sammel) is False


# --- Es gibt keinen Loeschweg, und das ist die Zusage ------------------------

def test_die_oberflaeche_bietet_nirgends_ein_loeschen_an():
    lead = _lead()
    # Die Kontaktseite sagt ausdruecklich, dass es kein Loeschen gibt, und
    # nennt den Grund — schweigen waere hier die schlechtere Antwort.
    seite = _get(f"/kontakte/{lead}").text
    assert "Loeschen gibt es hier nicht" in seite
    assert "ON DELETE CASCADE" in seite
    # Keine Route, die es doch taete — auf keiner Seite.
    for pfad in ("/", "/kontakte", f"/kontakte/{lead}", "/posteingang",
                 "/einordnung", "/wiedervorlagen"):
        assert "/loeschen" not in _get(pfad).text
    pfade = [getattr(r, "path", "") for r in ui.app.routes]
    assert not [p for p in pfade if "loesch" in p or "delete" in p]
    # Auch kein Chat-Werkzeug — sonst koennte der Agent, was die Oberflaeche
    # bewusst nicht kann.
    namen = {fn.__name__ for fn in server.WERKZEUGE}
    assert not [n for n in namen if "loesch" in n or "delete" in n]


def test_kontakt_aktualisieren_weist_status_und_consent_ab():
    """Die Kante sitzt im Werkzeug (KONTAKT_FELDER) — das UI erbt sie, weil es
    das Werkzeug ruft statt selbst zu schreiben."""
    lead = _lead()
    for feld, wert in (("status", "won"), ("consent_status", "opt_in"),
                       ("enrichment", "{}"), ("id", "x")):
        antwort = json.loads(server.kontakt_aktualisieren(
            lead_id=lead, feld=feld, wert=wert))
        assert "fehler" in antwort
    zeile = _stamm(lead)
    assert zeile["status"] == "new" and zeile["consent_status"] == "unknown"


def test_archiv_werkzeug_meldet_einen_unbekannten_kontakt():
    for werkzeug in (server.kontakt_archivieren, server.kontakt_wiederherstellen):
        antwort = json.loads(werkzeug(
            lead_id="00000000-0000-0000-0000-000000000000"))
        assert "fehler" in antwort


def test_archivmerkmal_faellt_bei_kaputten_werten_nach_sichtbar():
    """fail-open, und zwar in Python UND in SQL mit derselben Antwort.

    Ohne die `jsonb_typeof`-Pruefung in server._archiv_sql zaehlte die
    ZEICHENKETTE "true" in SQL als archiviert, waehrend Python (`is True`) sie
    nicht zaehlt — der Kontakt waere aus der Liste verschwunden, ohne dass die
    Kontaktseite ihn als archiviert kennzeichnet. Ein kaputter Wert darf
    niemanden unsichtbar machen.
    """
    kaputte = ('"true"', "true", '{"archiviert": "true"}',
               '{"archiviert": 1}', "null", '{"anderes": true}')
    for nummer, wert in enumerate(kaputte):
        lead = _lead(name=f"Kaputt Person {nummer}")
        server._q("update leads set enrichment = jsonb_set(enrichment, "
                  "'{archiviert}', %s::jsonb, true) where id = %s returning id",
                  (wert, lead))
        assert server._archiviert(_stamm(lead)["enrichment"]) is False, wert
        sichtbar = server._q(
            "select id from leads l where l.id = %s and not "
            + server._archiv_sql("l.enrichment"), (lead,))
        assert len(sichtbar) == 1, wert
        assert f"Kaputt Person {nummer}" in _get("/kontakte").text


def test_archivmerkmal_greift_nur_beim_echten_wahrheitswert():
    """Die Gegenprobe zum Test darueber: der ECHTE Wert wirkt in beiden Welten."""
    lead = _lead(name="Echt Archiviert")
    server._q("update leads set enrichment = jsonb_set(enrichment, "
              "'{archiviert}', %s::jsonb, true) where id = %s returning id",
              ('{"archiviert": true}', lead))
    assert server._archiviert(_stamm(lead)["enrichment"]) is True
    assert server._q("select id from leads l where l.id = %s and not "
                     + server._archiv_sql("l.enrichment"), (lead,)) == []
    assert "Echt Archiviert" not in _get("/kontakte").text


# ---------------------------------------------------------------------------
# Handytauglich (Betreiber-Wunsch 22.08.2026)
#
# Der Betreiber erreicht die Oberflaeche seit dem Tailscale-Zugang vom iPhone.
# Gebaut war sie fuer einen Desktop-Browser. Nachgezogen ist das in REINEM CSS
# — und genau das ist der Grund, warum es hier Tests gibt: eine Media-Query
# faellt lautlos aus, wenn jemand am Geruest arbeitet. Kein Test ersetzt den
# Blick auf ein echtes Telefon; diese hier halten fest, was sich ueberhaupt
# maschinell festhalten laesst.
#
# Die harten Randbedingungen stehen mit im Netz: KEIN JavaScript (die CSP sagt
# `default-src 'none'`), keine externen Ressourcen, und die `data-label`, aus
# denen die Handy-Ansicht ihre Spaltenbeschriftung baut, tragen ausschliesslich
# eigenen Text — ein Kundenname im Attribut waere derselbe Ausbruch, gegen den
# `html.escape(quote=True)` sonst ueberall steht.
# ---------------------------------------------------------------------------

# Jede Spaltenueberschrift, die `ui._tabelle` je in ein `data-label` schreibt.
# Die Liste ist der eigentliche Test: steht dort eines Tages etwas anderes,
# kommt es aus der Datenbank.
ERLAUBTE_LABEL = {
    "Name", "Status", "Consent", "Letzte Aktivitaet",       # /kontakte
    "Archiv",   # /kontakte, Archiv-Knopf je Zeile
    "Profil",   # /einordnung, Link zum Kontaktprofil
    "Quittieren",   # /wiedervorlagen, Erledigt-Knopf je Zeile
    "Kontakt", "Faellig am", "Notiz",                       # Wiedervorlagen
    "Frage", "Antwort",                                     # Bedarfsstand
    "Sparte", "Gesellschaft", "Ablauf",                     # Vertraege
    "Wann", "Typ", "Wer", "Inhalt",                         # Verlauf
    "Kennung", "Nachrichten", "Zuletzt",                    # Einordnung
    "Zusammenfassung",                                      # Chat-Reports
}


def _seitenarten():
    """Eine Antwort je SEITENART — Listen, Detail, Warn- und Fehlerseiten.

    Alles laeuft durch dasselbe `ui._seite`. Die Liste ist trotzdem lang,
    weil genau die Seiten, an die niemand denkt (die 421-Abweisung bei
    fremdem Host, die Archiv-Warnung), diejenigen sind, auf denen eine
    Regression am Geruest zuerst auffiele — und zuletzt gesucht wuerde.

    Nur zusammen mit der Fixture `sammelkontakt_zurueck` benutzen: die
    Ignorieren-Warnseite gibt es nur mit Sammelkontakt.
    """
    sammel = _sammel()
    lead = _lead(name="Handy Testperson")
    _entwurf(lead, text="Pending-Text")
    _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    freigegeben = _entwurf(lead, status="approved", approved_by="betreiber")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent"),))
    _kundenantwort(lead)
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'wiedervorlage', %s) returning id",
              (lead, json.dumps({"faellig_am": "2026-09-01",
                                 "notiz": "Vertragsablauf pruefen"})))
    # Fuer die Einordnung: ein Absender, der einem echten Kontakt gehoert —
    # daraus entsteht unten die zweistufige Ignorieren-Warnseite.
    _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, text="Ich habe unterschrieben",
                   absender=SOPHIE_NUMMER)

    arten = [(pfad, _get(pfad)) for pfad in (
        "/", "/kontakte", "/kontakte?archiv=1", f"/kontakte/{lead}",
        "/posteingang", "/einordnung", "/wiedervorlagen")]
    arten += [
        # Warnseiten (409) — beide schreiben nichts, siehe die Tests oben.
        ("archiv-warnung", _post("/kontakte/archivieren",
                                 {"lead_id": lead, "csrf": ui.CSRF_TOKEN})),
        ("ignorieren-warnung", _post("/einordnung/ignorieren",
                                     {"absender": SOPHIE_NUMMER,
                                      "csrf": ui.CSRF_TOKEN})),
        ("verwerfen-warnung", _post("/aktion/verwerfen",
                                    {"draft_id": freigegeben,
                                     "csrf": ui.CSRF_TOKEN})),
        # Fehlerseiten: fehlendes Token, unbekannter Kontakt, fremder Host.
        ("403-csrf", _post("/aktion/freigeben", {"draft_id": lead})),
        ("404-kontakt",
         _get("/kontakte/00000000-0000-0000-0000-000000000000")),
        ("421-host", _get("/", host="boese.example")),
    ]
    return arten


def _eingabe_tag(seite: str, name: str) -> str:
    """Das `<input …>` mit genau diesem name-Attribut.

    Ueber die Reihenfolge der Attribute sagt der Test damit nichts — nur
    darueber, WELCHE dranstehen.
    """
    treffer = [t for t in re.findall(r"<input[^>]*>", seite)
               if f'name="{name}"' in t]
    assert len(treffer) == 1, (name, treffer)
    return treffer[0]


# --- Der Bauplan der Seite: Viewport, kein JavaScript ------------------------

def test_viewport_meta_steht_auf_jeder_seitenart(sammelkontakt_zurueck):
    """Ohne diese Zeile legt Safari eine 980px breite Desktop-Leinwand an und
    zoomt sie auf die Geraetebreite herunter: die Seite ist vollstaendig da
    und vollstaendig unlesbar — und KEINE Media-Query greift, weil der
    Browser sich fuer breit haelt. Sie ist die Voraussetzung fuer alles
    andere in diesem Abschnitt, also wird sie auf jeder Seitenart geprueft."""
    for name, antwort in _seitenarten():
        assert ('<meta name="viewport" content="width=device-width, '
                'initial-scale=1">') in antwort.text, name
        # Sagt dem Browser, dass beide Themen bedient werden — sonst malt er
        # Formularfelder und Bildlaufleisten hell in die dunkle Seite.
        assert '<meta name="color-scheme" content="light dark">' in antwort.text


def test_keine_seitenart_enthaelt_javascript(sammelkontakt_zurueck):
    """Die Zusage aus dem Moduldocstring gilt weiter — auch nachdem die
    Oberflaeche handytauglich wurde. Handytauglichkeit war ausdruecklich kein
    Grund, Skripte einzufuehren: die CSP sagt `default-src 'none'`, und ein
    Freigabe-Frontend ohne JavaScript ist eine Zusage, keine Bequemlichkeit."""
    for name, antwort in _seitenarten():
        assert "<script" not in antwort.text, name
        assert "javascript:" not in antwort.text, name
        assert "onclick" not in antwort.text, name


def test_keine_seitenart_laedt_etwas_von_aussen(sammelkontakt_zurueck):
    """Keine Fonts, keine CDNs, keine Bilder von fremden Rechnern: die CSP
    verbietet sie (`default-src 'none'`), und der Rechner ist im Zweifel
    offline. Eine Seite, die auf eine externe Schrift wartet, waere auf dem
    Telefon des Betreibers eine Seite, die nicht kommt."""
    for name, antwort in _seitenarten():
        assert "https://" not in antwort.text, name
        assert "http://" not in antwort.text, name
        assert "@import" not in antwort.text, name
        assert "<link" not in antwort.text, name


# --- Das ausgelieferte CSS: schmale Schirme und dunkles Thema ---------------

def test_media_query_fuer_schmale_schirme_wird_ausgeliefert():
    """Nicht `ui._STIL` wird geprueft, sondern was im Browser ankommt — die
    Konstante koennte gepflegt und trotzdem nicht eingebunden sein."""
    seite = _get("/").text
    assert "@media (max-width: 640px)" in seite
    # Der gewaehlte Weg: Tabellenzeilen werden zu Karten, die
    # Spaltenueberschrift wandert per ::before aus data-label vor die Zelle.
    assert "content: attr(data-label)" in seite
    assert ".tabelle thead { display: none; }" in seite


def test_dunkles_thema_wird_ausgeliefert():
    """Viele Leute haben das Telefon dauerhaft auf dunkel; eine gleissend
    weisse Seite am Abend ist der Grund, sie nicht aufzumachen."""
    seite = _get("/").text
    assert "@media (prefers-color-scheme: dark)" in seite
    # Farben stehen als Variablen — sonst kann der dunkle Satz sie gar nicht
    # ueberschreiben, und die beiden Themen driften beim naechsten #fff
    # auseinander.
    assert "--flaeche:" in seite and "--schrift:" in seite
    assert "background: var(--flaeche)" in seite
    assert "color: var(--schrift)" in seite
    # Auch die Warn- und Fehlerfarben — die sind sonst die ersten, die im
    # dunklen Satz absaufen: einmal im hellen Satz, einmal im dunklen.
    for name in ("--fehler:", "--fehler_flaeche:", "--hinweis_flaeche:",
                 "--achtung:"):
        assert seite.count(name) >= 2, name


def test_touchziele_und_schriftgroesse_der_eingabefelder():
    """44px ist die Untergrenze, unter der ein Daumen daneben trifft; 16px die
    Schwelle, unter der iOS beim Fokussieren von selbst ins Feld zoomt und die
    Seite verschoben zuruecklaesst. Beides ist hier kein Geschmack: ein
    Fehlgriff neben „Freigeben" verschickt eine Nachricht."""
    seite = _get("/").text
    assert "min-height: 44px" in seite
    assert "font-size: 16px" in seite


def test_die_seite_selbst_scrollt_nie_waagerecht():
    """Lange Zeichenketten ohne Leerzeichen (URLs, Base64, Kennungen) sind
    Fremddaten und kommen vor. Sie brechen um; was sich nicht brechen laesst,
    scrollt in seinem EIGENEN Kasten — nie die Seite."""
    seite = _get("/").text
    assert "overflow-wrap: anywhere" in seite
    assert "html, body { overflow-x: hidden; }" in seite
    assert ".tabelle { overflow-x: auto;" in seite


def test_navigation_umbricht_statt_ueberzulaufen():
    seite = _get("/").text
    assert ("nav { background: var(--balken); display: flex; flex-wrap: wrap;"
            in seite)


# --- Tabellen: Spaltenueberschrift je Zelle, und NIE Fremddaten darin -------

def test_jede_tabellenzelle_traegt_ihre_spaltenueberschrift():
    """Der gewaehlte Ansatz steht und faellt damit: auf dem Handy ist die
    Kopfzeile ausgeblendet, und ohne `data-label` an der Zelle stuenden dort
    vier nackte Werte ohne Bedeutung."""
    lead = _lead(name="Anna Beispiel")
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'wiedervorlage', %s) returning id",
              (lead, json.dumps({"faellig_am": "2026-09-01",
                                 "notiz": "Vertragsablauf pruefen"})))
    for pfad, spalten in (("/kontakte", ["Name", "Status", "Consent",
                                         "Letzte Aktivitaet"]),
                          ("/wiedervorlagen", ["Kontakt", "Faellig am",
                                               "Notiz"])):
        seite = _get(pfad).text
        for spalte in spalten:
            assert f'data-label="{spalte}"' in seite, (pfad, spalte)


def test_data_label_traegt_nie_fremddaten(sammelkontakt_zurueck):
    """Die Beschriftung der Handy-Ansicht steht im ATTRIBUTKONTEXT. Dort darf
    ausschliesslich eigener Text stehen: ein Kontaktname im `data-label` waere
    genau der Ausbruch, den `html.escape(quote=True)` an jeder anderen Stelle
    dieser Oberflaeche verhindert. Geprueft wird deshalb nicht, dass die
    Fremddaten escaped sind, sondern dass sie dort GAR NICHT vorkommen — jedes
    Label muss eine der Ueberschriften aus dem Code sein."""
    boese = 'Anna"><script>alert(1)</script>'
    lead = _lead(name=boese)
    server._q("update leads set enrichment = %s where id = %s returning id",
              (json.dumps({"vertraege": [{"sparte": boese,
                                          "gesellschaft": boese,
                                          "ablauf": boese}]}), lead))
    server._q("insert into activities (lead_id, type, payload) "
              "values (%s, 'wiedervorlage', %s) returning id",
              (lead, json.dumps({"faellig_am": boese, "notiz": boese})))
    _entwurf(lead, text=boese)
    sammel = _sammel()
    _kundenantwort(sammel, text=boese, absender=SOPHIE_NUMMER)
    _lead(name=boese + " zwei", phone=SOPHIE_PHONE)

    for pfad in ("/", "/kontakte", f"/kontakte/{lead}", "/posteingang",
                 "/einordnung", "/wiedervorlagen"):
        seite = _get(pfad).text
        assert "<script" not in seite, pfad
        assert '"><script' not in seite, pfad
        gefunden = set(re.findall(r'data-label="([^"]*)"', seite))
        assert gefunden <= ERLAUBTE_LABEL, (pfad, gefunden - ERLAUBTE_LABEL)


# --- Formulare: die richtige Tastatur unter dem Finger ----------------------

@pytest.mark.parametrize("feld, erwartet", [
    # Eine Rufnummer auf der Buchstabentastatur einzugeben ist der Weg zum
    # Zahlendreher — und ein Zahlendreher schickt die naechste Nachricht an
    # einen Fremden.
    ("phone", ('type="tel"', 'inputmode="tel"', 'autocomplete="tel"')),
    ("email", ('type="email"', 'inputmode="email"', 'autocapitalize="none"')),
    ("name", ('type="text"', 'autocapitalize="words"')),
])
def test_stammdatenfelder_schalten_die_passende_handytastatur(feld, erwartet):
    lead = _lead()
    tag = _eingabe_tag(_get(f"/kontakte/{lead}").text, feld)
    for stueck in erwartet:
        assert stueck in tag, (feld, tag)
    # Die Laengenbegrenzung des Werkzeugs bleibt daneben stehen.
    assert f'maxlength="{ui.KONTAKT_FELD_MAX}"' in tag


def test_jedes_stammdatenfeld_hat_eine_tastatur_auch_ein_neues():
    """Die Feldliste kommt aus `server.KONTAKT_FELDER`. Ein dort ergaenztes
    Feld taucht in der Oberflaeche von selbst auf — es soll dann ein
    gewoehnliches Textfeld sein und nicht ein `<input>` ohne `type`."""
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    for feld in server.KONTAKT_FELDER:
        assert "type=" in _eingabe_tag(seite, feld), feld
    assert "type=" in ui.KONTAKT_FELD_EINGABE_STANDARD


def test_namensfeld_der_einordnung_ist_ein_textfeld(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    tag = _eingabe_tag(_get("/einordnung").text, "name")
    assert 'type="text"' in tag
    assert 'autocapitalize="words"' in tag
    assert f'maxlength="{ui.EINORDNUNG_NAME_MAX}"' in tag


# --- Abzeichen: das Wort traegt die Aussage, nicht die Farbe ----------------

def test_jede_entwurfskarte_nennt_ihren_zustand_als_wort():
    """Auf dem Telefon scrollt die Ueberschrift des Blocks („Fehlgeschlagen")
    aus dem Bild, waehrend die Karten weiterlaufen — dann bliebe nur die Farbe
    des Knopfes. Farbe allein traegt eine Unterscheidung nicht: Sehschwaeche,
    Sonnenlicht, ein Abzeichen von 12px."""
    lead = _lead()
    _entwurf(lead, text="Pending-Text hier")
    _entwurf(lead, status="failed", fehler="OpenWA HTTP 500")
    _entwurf(lead, status="approved", approved_by="betreiber")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent"),))
    seite = _get("/").text
    for zustand, wort in ui.ZUSTAND_TITEL.items():
        assert f'<span class="badge zustand {zustand}">{wort}</span>' in seite


def test_archiviert_und_lid_stehen_als_text_nicht_nur_als_farbe(
        sammelkontakt_zurueck):
    lead = _lead(name="Weggeraeumt Person")
    _post("/kontakte/archivieren-bestaetigen",
          {"lead_id": lead, "csrf": ui.CSRF_TOKEN,
           "name_bestaetigt": "Weggeraeumt Person"})
    liste = _get("/kontakte?archiv=1").text
    assert '<span class="badge archiv">archiviert</span>' in liste
    sammel = _sammel()
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    for pfad in ("/posteingang", "/einordnung"):
        assert "LID-Pseudo-Kennung, keine Rufnummer" in _get(pfad).text, pfad


# --- Aktionen: getrennte Formulare, und Abstand fuer den Daumen -------------

def test_freigeben_und_ablehnen_sind_getrennte_ziele():
    """Sie stehen in EINEM Kasten, aber in ZWEI Formularen, und das
    gefaehrliche traegt seine Klasse auch am Formular — daran haengt die
    Media-Query, die es auf dem Handy abrueckt. Ein Fehlgriff verschickt hier
    eine Nachricht oder verwirft einen Entwurf; beides ist endgueltig."""
    lead = _lead()
    _entwurf(lead)
    seite = _get("/").text
    assert '<div class="aktionen">' in seite
    assert 'action="/aktion/freigeben"' in seite
    assert 'action="/aktion/ablehnen"' in seite
    assert '<form class="aktion gefahr"' in seite
    assert ".aktionen form.aktion.gefahr { margin-top: .8rem; }" in seite
    # Auf schmalen Schirmen stehen sie untereinander ueber die volle Breite.
    assert (".aktionen { flex-direction: column; align-items: stretch; }"
            in seite)


def test_die_gefaehrlichen_knoepfe_tragen_ihre_klasse_am_formular(
        sammelkontakt_zurueck):
    """Ueberall dasselbe Muster: `ignorieren`, `archivieren` und die beiden
    zweiten, ausdruecklichen Schritte."""
    sammel = _sammel()
    lead = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    # Zwei Absender: die @lid wartet noch auf eine Entscheidung (sie traegt
    # die drei Knoepfe der Seite), die Rufnummer gehoert Sophie bereits — an
    # ihr haengt unten die zweistufige Warnseite.
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    _kundenantwort(sammel, text="Hallo", absender=SOPHIE_NUMMER)
    assert '<form class="aktion gefahr"' in _get("/einordnung").text
    assert '<form class="aktion gefahr"' in _get(f"/kontakte/{lead}").text
    warnung = _post("/einordnung/ignorieren",
                    {"absender": SOPHIE_NUMMER, "csrf": ui.CSRF_TOKEN})
    assert warnung.status_code == 409
    assert '<form class="aktion gefahr"' in warnung.text
    archiv = _post("/kontakte/archivieren",
                   {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert archiv.status_code == 409
    assert '<form class="aktion gefahr"' in archiv.text


# ---------------------------------------------------------------------------
# Kontaktprofil in der Oberflaeche (Betreiber-Wunsch 22.08.2026)
#
# Die Oberflaeche SCHREIBT hier nichts — Profile entstehen im Chat, weil dort
# das Sprachmodell sitzt. Geprueft wird das Anzeigen, der Link von der
# Einordnungsuebersicht und der Archiv-Knopf in der Kontaktliste.
# ---------------------------------------------------------------------------

VOLLES_PROFIL = {
    "wer": "Selbstaendige Tischlerin, Mitte dreissig.",
    "beziehung": "Seit dem Erstgespraech im Juli lose in Kontakt.",
    "wichtig": "Kurze Wege, keine Vertreterbesuche.",
    "aktuell": "Wartet auf Zahlen zur Betriebsabsicherung.",
}


def _profil_anlegen(lead, **abweichend):
    felder = dict(VOLLES_PROFIL, **abweichend)
    return json.loads(server.chat_report_speichern(
        lead, zusammenfassung="Kurzer Verlauf, nichts Offenes.", **felder))


def test_kontaktseite_zeigt_das_profil():
    lead = _lead()
    _kundenantwort(lead)
    assert "fehler" not in _profil_anlegen(lead)
    seite = _get(f"/kontakte/{lead}").text
    assert "Kontaktprofil" in seite
    for frage in server.PROFIL_FRAGEN.values():
        assert frage in seite
    for wert in VOLLES_PROFIL.values():
        assert wert in seite


def test_kontaktseite_ohne_profil_sagt_es():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert "Kontaktprofil" in seite
    assert "Noch keins" in seite


def test_profiltext_wird_escaped():
    """Profiltext ist Modelltext ueber Kundennachrichten — also Fremddatum."""
    lead = _lead()
    _kundenantwort(lead)
    _profil_anlegen(lead, wer='Anna"><script>alert(1)</script>')
    seite = _get(f"/kontakte/{lead}").text
    assert "<script" not in seite
    assert "&lt;script" in seite


def test_links_und_dateien_stehen_im_profil():
    lead = _lead()
    _kundenantwort(lead)
    server.chat_report_speichern(
        lead, zusammenfassung="Verlauf.", **VOLLES_PROFIL,
        links="https://example.org/angebot", dateien="Angebot.pdf")
    seite = _get(f"/kontakte/{lead}").text
    assert "https://example.org/angebot" in seite
    assert "Angebot.pdf" in seite


def test_einordnung_verlinkt_das_profil(sammelkontakt_zurueck):
    sammel = _sammel()
    lead = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, absender=SOPHIE_NUMMER)
    _kundenantwort(lead)
    _profil_anlegen(lead)
    seite = _get("/einordnung").text
    assert "Profil" in seite
    assert f'href="/kontakte/{lead}#profil"' in seite


def test_einordnung_zeigt_fehlendes_profil_ehrlich(sammelkontakt_zurueck):
    sammel = _sammel()
    lead = _lead(name="Sophie Beispiel", phone=SOPHIE_PHONE)
    _kundenantwort(sammel, absender=SOPHIE_NUMMER)
    seite = _get("/einordnung").text
    assert "noch keins" in seite
    assert f'href="/kontakte/{lead}#profil"' not in seite


def test_kontaktliste_hat_den_archiv_knopf():
    lead = _lead()
    seite = _get("/kontakte").text
    assert "Archivieren" in seite
    assert 'action="/kontakte/archivieren"' in seite
    assert f'value="{lead}"' in seite


def test_archivieren_aus_der_liste_schreibt_erst_nichts():
    """Der erste POST zeigt die Warnseite — auch aus der Liste heraus.

    409, nicht 200: dieser Schritt allein WIRKT nicht, er verlangt einen
    zweiten. Der Statuscode sagt dasselbe wie die Seite.
    """
    lead = _lead()
    antwort = _post("/kontakte/archivieren",
                    {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 409
    assert "Archivieren bestaetigen" in antwort.text
    zeile = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert not server._archiviert(zeile["enrichment"])


def test_archivieren_aus_der_liste_ohne_csrf_ist_403():
    lead = _lead()
    antwort = _post("/kontakte/archivieren", {"lead_id": lead})
    assert antwort.status_code == 403


# ---------------------------------------------------------------------------
# Der Sammelkontakt ist kein Mensch
#
# Am 25.08.2026 wurde er in der Oberflaeche in "Jody" umbenannt und sah danach
# aus wie eine Person mit 675 Nachrichten — in Wahrheit die Nachrichten von
# sechzehn verschiedenen Fremden nebeneinander. `kontakt_archivieren` hatte
# die Kante schon, `kontakt_aktualisieren` nicht.
# ---------------------------------------------------------------------------

def test_sammelkontakt_laesst_sich_nicht_umbenennen(sammelkontakt_zurueck):
    sammel = _sammel()
    antwort = json.loads(server.kontakt_aktualisieren(sammel, "name", "Jody"))
    assert "fehler" in antwort
    assert "kein Mensch" in antwort["fehler"]
    name = server._q("select name from leads where id = %s", (sammel,))[0]
    assert name["name"] != "Jody"


def test_echter_kontakt_laesst_sich_weiter_umbenennen(sammelkontakt_zurueck):
    _sammel()
    lead = _lead(name="Alt")
    antwort = json.loads(server.kontakt_aktualisieren(lead, "name", "Neu"))
    assert "fehler" not in antwort
    assert server._q("select name from leads where id = %s",
                     (lead,))[0]["name"] == "Neu"


def test_sammelkontakt_zeigt_kein_stammdatenformular(sammelkontakt_zurueck):
    sammel = _sammel()
    seite = _get(f"/kontakte/{sammel}").text
    assert "Sammelkontakt fuer unbekannte Eingaenge" in seite
    assert 'action="/kontakte/bearbeiten"' not in seite
    assert "Das ist kein Mensch" in seite


def test_kontaktliste_markiert_den_sammelkontakt(sammelkontakt_zurueck):
    _sammel()
    seite = _get("/kontakte").text
    assert "Sammelkontakt" in seite


def test_kein_archiv_knopf_am_sammelkontakt(sammelkontakt_zurueck):
    """Ein Knopf, den das Werkzeug ohnehin ablehnt, waere eine Luege."""
    sammel = _sammel()
    lead = _lead()
    seite = _get("/kontakte").text
    # Fuer den echten Kontakt gibt es ihn …
    assert f'value="{lead}"' in seite
    # … fuer den Sammelkontakt nicht.
    import re
    formulare = re.findall(r'action="/kontakte/archivieren".*?</form>', seite,
                           re.S)
    assert all(str(sammel) not in f for f in formulare)


# ---------------------------------------------------------------------------
# Entwuerfe bearbeiten und aufklappen (Betreiber-Wunsch 25.08.2026)
#
# „die freigaben müssen noch editierbar sein" und „Freigaben could be more
# likely an extendable chart, which is open by click on. So we only have that
# view with our back and forward."
# ---------------------------------------------------------------------------

def test_freigaben_sind_aufklappbar():
    lead = _lead()
    _entwurf(lead, text="Ein Entwurf, der aufklappbar sein soll.")
    seite = _get("/").text
    assert "<details class=\"karte\">" in seite
    assert "<summary>" in seite
    # Der Text steht drin — aber die Karte ist zu, bis jemand klickt.
    assert "Ein Entwurf, der aufklappbar sein soll." in seite


def test_vorschau_ist_gekuerzt_und_escaped():
    lead = _lead()
    _entwurf(lead, text='X' * 300 + '<script>alert(1)</script>')
    seite = _get("/").text
    assert "<script" not in seite
    assert "…" in seite


def test_bearbeitungsfeld_nur_bei_offenen_entwuerfen():
    lead = _lead()
    _entwurf(lead, status="pending")
    assert 'action="/aktion/bearbeiten"' in _get("/").text
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.drafts cascade")
    _entwurf(lead, status="approved")
    assert 'action="/aktion/bearbeiten"' not in _get("/").text


def test_bearbeiten_aendert_den_text_und_sendet_nichts():
    lead = _lead()
    d = _entwurf(lead, text="Alter Text")
    antwort = _post("/aktion/bearbeiten",
                    {"draft_id": d, "text": "Neuer Text", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code in (200, 303)
    zeile = server._q("select body, status from drafts where id = %s",
                      (d,))[0]
    assert zeile["body"] == "Neuer Text"
    assert zeile["status"] == "pending"      # Freigabe bleibt ein eigener Schritt


def test_bearbeiten_protokolliert_alt_und_neu():
    lead = _lead()
    d = _entwurf(lead, text="Alter Text")
    _post("/aktion/bearbeiten",
          {"draft_id": d, "text": "Neuer Text", "csrf": ui.CSRF_TOKEN})
    zeilen = server._q(
        "select payload from activities where type = 'entwurf_bearbeitet'")
    assert len(zeilen) == 1
    p = zeilen[0]["payload"]
    assert p["vorher"] == "Alter Text"
    assert p["nachher"] == "Neuer Text"


def test_freigegebener_entwurf_laesst_sich_nicht_aendern():
    """Sonst haenge die Freigabe an einem Text, den niemand gelesen hat."""
    lead = _lead()
    d = _entwurf(lead, text="Freigegeben", status="approved")
    antwort = _post("/aktion/bearbeiten",
                    {"draft_id": d, "text": "Heimlich anders",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 409
    assert server._q("select body from drafts where id = %s",
                     (d,))[0]["body"] == "Freigegeben"


def test_bearbeiten_ohne_csrf_ist_403():
    lead = _lead()
    d = _entwurf(lead, text="Alter Text")
    assert _post("/aktion/bearbeiten",
                 {"draft_id": d, "text": "Neu"}).status_code == 403
    assert server._q("select body from drafts where id = %s",
                     (d,))[0]["body"] == "Alter Text"


# ---------------------------------------------------------------------------
# Medien hochladen (Betreiber-Wunsch 25.08.2026)
#
# „there is no site where we have, like, the chance to upload media as
# videos, PDFs, and something like that."
#
# Das ist die EINZIGE Stelle, an der Daten von aussen in den Versandvorrat
# kommen. Entsprechend eng: derselbe Namensfilter, dieselbe Whitelist und
# dieselbe Groessengrenze wie beim Versand — und kein stilles Ueberschreiben.
# ---------------------------------------------------------------------------

@pytest.fixture()
def medienordner(tmp_path, monkeypatch):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    return tmp_path


def _upload(name, inhalt=b"x" * 64, csrf=True, ueberschreiben=False):
    daten = {"csrf": ui.CSRF_TOKEN} if csrf else {}
    if ueberschreiben:
        daten["ueberschreiben"] = "ja"
    return CLIENT.post("/medien/hochladen", data=daten,
                       files={"datei": (name, inhalt, "application/pdf")},
                       headers={"host": HOST_OK}, follow_redirects=False)


def test_medienseite_zeigt_liste_und_formular(medienordner):
    (medienordner / "vorhanden.pdf").write_bytes(b"x" * 100)
    seite = _get("/medien").text
    assert "vorhanden.pdf" in seite
    assert 'enctype="multipart/form-data"' in seite
    assert "Hochladen" in seite


def test_hochladen_legt_die_datei_ab(medienordner):
    antwort = _upload("angebot.pdf", b"y" * 200)
    assert antwort.status_code == 303
    ziel = medienordner / "angebot.pdf"
    assert ziel.is_file() and ziel.read_bytes() == b"y" * 200
    # Kein Zwischenname bleibt liegen.
    assert not (medienordner / "angebot.pdf.teil").exists()


def test_unzulaessige_endung_wird_abgewiesen(medienordner):
    antwort = _upload("schadcode.exe")
    assert antwort.status_code == 400
    assert not (medienordner / "schadcode.exe").exists()


def test_pfad_im_dateinamen_wird_abgewiesen(medienordner):
    antwort = _upload("..\\windows\\system.ini")
    assert antwort.status_code == 400
    assert list(medienordner.iterdir()) == []


def test_zu_grosse_datei_wird_abgewiesen(medienordner, monkeypatch):
    monkeypatch.setattr(server.medien, "MAX_BYTES", 1024)
    antwort = _upload("gross.pdf", b"z" * 4096)
    assert antwort.status_code == 413
    assert not (medienordner / "gross.pdf").exists()
    # Auch das Bruchstueck ist weg — sonst haelte der Dispatcher es spaeter
    # fuer eine gueltige Unterlage.
    assert list(medienordner.iterdir()) == []


def test_leere_datei_wird_abgewiesen(medienordner):
    assert _upload("leer.pdf", b"").status_code == 400
    assert list(medienordner.iterdir()) == []


def test_vorhandene_datei_wird_nicht_still_ersetzt(medienordner):
    (medienordner / "angebot.pdf").write_bytes(b"ALT")
    antwort = _upload("angebot.pdf", b"NEU")
    assert antwort.status_code == 409
    assert (medienordner / "angebot.pdf").read_bytes() == b"ALT"


def test_ersetzen_geht_mit_ausdruecklichem_haken(medienordner):
    (medienordner / "angebot.pdf").write_bytes(b"ALT")
    antwort = _upload("angebot.pdf", b"NEU", ueberschreiben=True)
    assert antwort.status_code == 303
    assert (medienordner / "angebot.pdf").read_bytes() == b"NEU"


def test_hochladen_ohne_csrf_ist_403(medienordner):
    assert _upload("angebot.pdf", csrf=False).status_code == 403
    assert list(medienordner.iterdir()) == []


def test_hochgeladene_datei_besteht_die_versand_pruefung(medienordner):
    """Was hier durchkommt, muss `medien.pruefe` anschliessend durchlassen —
    sonst gaebe es zwei Wahrheiten darueber, was versendbar ist."""
    _upload("angebot.pdf", b"y" * 200)
    basis, fehler = server.medien.pruefe("angebot.pdf")
    assert fehler is None and basis == "angebot.pdf"


# ---------------------------------------------------------------------------
# Wiedervorlagen anlegen und quittieren (Betreiber-Wunsch 25.08.2026)
#
# „und was sollte auf wiedervorlagen sein?" — die Seite war leer, weil es in
# der Oberflaeche keinen Weg gab, eine anzulegen. Das konnte nur der Agent.
# ---------------------------------------------------------------------------

def _morgen():
    from datetime import date, timedelta
    return (date.today() + timedelta(days=1)).isoformat()


def test_kontaktseite_hat_das_wiedervorlage_formular():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert 'action="/wiedervorlagen/setzen"' in seite
    assert 'type="date"' in seite


def test_wiedervorlage_anlegen_und_anzeigen():
    lead = _lead(name="Sabrina Beispiel")
    antwort = _post("/wiedervorlagen/setzen",
                    {"lead_id": lead, "faellig_am": _morgen(),
                     "notiz": "Rueckruf wegen des Angebots",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    seite = _get("/wiedervorlagen").text
    assert "Sabrina Beispiel" in seite
    assert "Rueckruf wegen des Angebots" in seite


def test_wiedervorlage_in_der_vergangenheit_wird_abgewiesen():
    lead = _lead()
    antwort = _post("/wiedervorlagen/setzen",
                    {"lead_id": lead, "faellig_am": "2020-01-01",
                     "notiz": "zu spaet", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server._q(
        "select id from activities where type = 'wiedervorlage'") == []


def test_wiedervorlage_quittieren_loescht_nichts():
    """Append-only: erledigt heisst Gegen-Ereignis, nicht Loeschen."""
    lead = _lead()
    _post("/wiedervorlagen/setzen",
          {"lead_id": lead, "faellig_am": _morgen(), "notiz": "Rueckruf",
           "csrf": ui.CSRF_TOKEN})
    offen = server._q(
        "select id from activities where type = 'wiedervorlage'")
    assert len(offen) == 1
    antwort = _post("/wiedervorlagen/erledigt",
                    {"lead_id": lead, "aktivitaets_id": str(offen[0]["id"]),
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    # Die Ursprungszeile steht noch — dazu kam eine zweite.
    assert len(server._q(
        "select id from activities where type = 'wiedervorlage'")) == 1
    assert len(server._q(
        "select id from activities where type = 'wiedervorlage_erledigt'")) == 1
    assert "Keine offenen Wiedervorlagen" in _get("/wiedervorlagen").text


def test_wiedervorlage_ohne_csrf_ist_403():
    lead = _lead()
    assert _post("/wiedervorlagen/setzen",
                 {"lead_id": lead, "faellig_am": _morgen(),
                  "notiz": "x"}).status_code == 403
    assert server._q(
        "select id from activities where type = 'wiedervorlage'") == []
