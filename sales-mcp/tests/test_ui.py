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
    seite = _get("/freigaben").text
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


def test_extra_host_gilt_auch_nackt_und_auf_443():
    """Hinter `tailscale serve` (F4, gemessen 31.08.2026) kommt der
    Original-Host OHNE :8791 an — mal nackt, mal mit :443. Beide Formen
    eines eingetragenen Extra-Hosts muessen bedient werden, sonst ist die
    HTTPS-Adresse ein 421. Fremde Namen bleiben fremd."""
    vorher = ui.ERLAUBTE_HOSTS
    ui.ERLAUBTE_HOSTS = ui._erlaubte_hosts(["vm.beispiel.ts.net"], ui.PORT)
    try:
        assert _get("/", host="vm.beispiel.ts.net:8791").status_code == 200
        assert _get("/", host="vm.beispiel.ts.net").status_code == 200
        assert _get("/", host="vm.beispiel.ts.net:443").status_code == 200
        assert _get("/", host="boese.example").status_code == 421
        assert _get("/", host="vm.beispiel.ts.net:8080").status_code == 421
    finally:
        ui.ERLAUBTE_HOSTS = vorher


# ---------------------------------------------------------------------------
# XSS: Fremddaten erscheinen escaped, nie roh — und die Seiten haben kein JS
# ---------------------------------------------------------------------------

def test_entwurfstext_mit_script_erscheint_escaped_nie_roh():
    lead = _lead()
    _entwurf(lead, text="<script>alert('xss')</script>")
    seite = _get("/freigaben").text
    assert "<script" not in seite
    assert "&lt;script&gt;" in seite


def test_fehlertext_und_kontaktname_erscheinen_escaped():
    lead = _lead(name='<img src=x onerror="alert(1)">')
    _entwurf(lead, status="failed", fehler='<svg onload="alert(2)">')
    seite = _get("/freigaben").text
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
    seite = _get("/freigaben").text
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

def _lese_stand(draft):
    """Der Fingerabdruck des Textes, wie ihn die geladene Seite truege."""
    return ui._text_stand(server._q(
        "select body from drafts where id = %s", (draft,))[0]["body"] or "")


def test_freigeben_pending_wird_approved_mit_betreiber_ui():
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN,
                                    "stand": _lese_stand(draft)})
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
    seite = _get("/freigaben").text
    assert seite.count('action="/aktion/verwerfen"') == 2


def test_verwerfen_knopf_steht_nicht_an_pending_und_gesendeten():
    lead = _lead()
    _entwurf(lead, status="pending")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent"),))
    seite = _get("/freigaben").text
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
    seite = _get("/freigaben").text
    assert "Pending-Text hier" in seite
    assert "Nummer nicht zustellbar" in seite
    assert "wartet auf Dispatcher" in seite
    assert "Schon gesendeter Text" in seite
    assert 'http-equiv="refresh" content="30"' in seite


def test_inbox_linkedin_sonderfall_nennt_den_handversand():
    lead = _lead()
    _entwurf(lead, status="approved", kanal="linkedin",
             approved_by="betreiber", text="LinkedIn-Post-Text")
    seite = _get("/freigaben").text
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

def _kundenantwort(lead, text="Passt Donnerstag?", absender="491701234567@c.us",
                   typ=None):
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'kundenantwort', %s, 'human') returning id",
              (lead, json.dumps({"text": text, "richtung": "eingehend",
                                 "absender": absender,
                                 "nachrichtentyp": typ or "text",
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

def test_kontakte_und_verlauf_lassen_sich_nirgends_loeschen():
    """Kein Loeschweg fuer DATENSAETZE — und das ist die Zusage.

    PRAEZISIERT am 25.08.2026. Vorher pruefte dieser Test, dass es
    UEBERHAUPT keine Route mit „loesch" gibt. Seit es die Medienseite gibt,
    ist das zu grob: eine Datei auf der Platte ist etwas anderes als ein
    Datensatz.

    Der Grund fuer die Zusage gilt naemlich fuer Datensaetze, nicht fuer
    Dateien: die Rolle hat auf `sales` kein DELETE-Recht, und `activities`
    haengt mit ON DELETE CASCADE am Kontakt — ein geloeschter Kontakt naehme
    die gesamte Historie mit. Eine Mediendatei hat keine Historie, sie ist
    eine Kopie einer Unterlage, und der Betreiber hat sie selbst
    hochgeladen. Sie loeschen zu koennen ist die Kehrseite davon, sie
    hochladen zu koennen.

    Geprueft wird deshalb jetzt genau das Versprechen, das gilt: keine
    Route und kein Werkzeug loescht KONTAKTE oder VERLAUF.
    """
    lead = _lead()
    # Die Kontaktseite sagt ausdruecklich, dass es kein Loeschen gibt, und
    # nennt den Grund — schweigen waere hier die schlechtere Antwort.
    seite = _get(f"/kontakte/{lead}").text
    assert "Loeschen gibt es hier nicht" in seite
    assert "ON DELETE CASCADE" in seite
    # Auf den Datensatz-Seiten taucht kein Loeschweg auf. /medien steht
    # bewusst NICHT in der Liste: dort geht es um Dateien.
    for pfad in ("/", "/kontakte", f"/kontakte/{lead}", "/posteingang",
                 "/einordnung", "/wiedervorlagen"):
        assert "/loeschen" not in _get(pfad).text
    # Routen mit „loesch" gibt es nur unter /medien — nirgends fuer
    # Kontakte, Entwuerfe oder Aktivitaeten.
    pfade = [getattr(r, "path", "") for r in ui.app.routes]
    verdaechtig = [p for p in pfade
                   if ("loesch" in p or "delete" in p)
                   and not p.startswith("/medien/")]
    assert not verdaechtig, verdaechtig
    # Auch kein Chat-Werkzeug — sonst koennte der Agent, was die Oberflaeche
    # bewusst nicht kann. Hier bleibt die Zusage vollstaendig: der Agent
    # loescht auch keine Dateien.
    #
    # Dokumentierte Verengung 29.08.2026 (dieselbe wie in test_werkzeuge):
    # `loeschantrag_vermerken` traegt das Wort, LOESCHT aber nichts — es
    # VERMERKT ein DSGVO-Begehren und stoppt die Verarbeitung
    # (tests/test_dsgvo.py). Kein anderes Werkzeug darf loeschen oder
    # danach klingen.
    namen = {fn.__name__ for fn in server.WERKZEUGE}
    assert not [n for n in namen
                if ("loesch" in n or "delete" in n)
                and n != "loeschantrag_vermerken"]


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
    # 29.08.2026: die Spalte heisst „Stufe" — sie zeigt die
    # Pipeline-Stufe, und „Status" stand im selben Blick neben der
    # Autonomie-„Stufe" daneben. „Status" bleibt in der Liste, weil
    # andere Ansichten es weiterhin verwenden duerfen.
    "Stufe",
    "Score", "Zuletzt",   # /kontakte seit Schritt 5 (02.09.2026)
    "Archiv",   # /kontakte, Archiv-Knopf je Zeile
    "Autonomie",   # /kontakte, Stufe je Zeile (25.08.2026)
    "Profil",   # /einordnung, Link zum Kontaktprofil
    "Quittieren",   # /wiedervorlagen, Erledigt-Knopf je Zeile
    "Kontakt", "Faellig am", "Notiz",                       # Wiedervorlagen
    "Frage", "Antwort",                                     # Bedarfsstand
    "Sparte", "Gesellschaft", "Ablauf",                     # Vertraege
    "Wann", "Was", "Inhalt",   # Verlauf (25.08.2026 lesbar gemacht)
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
    seite = _get("/freigaben").text
    assert "@media (max-width: 640px)" in seite
    # Der gewaehlte Weg: Tabellenzeilen werden zu Karten, die
    # Spaltenueberschrift wandert per ::before aus data-label vor die Zelle.
    assert "content: attr(data-label)" in seite
    assert ".tabelle thead { display: none; }" in seite


def test_dunkles_thema_wird_ausgeliefert():
    """Viele Leute haben das Telefon dauerhaft auf dunkel; eine gleissend
    weisse Seite am Abend ist der Grund, sie nicht aufzumachen."""
    seite = _get("/freigaben").text
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
    seite = _get("/freigaben").text
    assert "min-height: 44px" in seite
    assert "font-size: 16px" in seite


def test_die_seite_selbst_scrollt_nie_waagerecht():
    """Lange Zeichenketten ohne Leerzeichen (URLs, Base64, Kennungen) sind
    Fremddaten und kommen vor. Sie brechen um; was sich nicht brechen laesst,
    scrollt in seinem EIGENEN Kasten — nie die Seite."""
    seite = _get("/freigaben").text
    assert "overflow-wrap: anywhere" in seite
    assert "html, body { overflow-x: hidden; }" in seite
    assert ".tabelle { overflow-x: auto;" in seite


def test_navigation_umbricht_statt_ueberzulaufen():
    seite = _get("/freigaben").text
    assert ("nav.seite { display: flex; flex-direction: row; flex-wrap: wrap;"
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
    # „Stufe" statt „Status" seit 29.08.2026 — die Spalte zeigt die
    # Pipeline-Stufe und stand als „Status" verwirrend neben der
    # Autonomie-Stufe in derselben Zeile.
    for pfad, spalten in (("/kontakte", ["Name", "Stufe", "Score",
                                         "Zuletzt"]),
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
    _entwurf(lead, status="rejected", text="Abgelehnter Text")
    server._q("update drafts set sent_at = now() where id = %s returning id",
              (_entwurf(lead, status="sent"),))
    seite = _get("/freigaben").text
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
    seite = _get("/freigaben").text
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
    seite = _get("/freigaben").text
    assert "<details class=\"karte\">" in seite
    assert "<summary>" in seite
    # Der Text steht drin — aber die Karte ist zu, bis jemand klickt.
    assert "Ein Entwurf, der aufklappbar sein soll." in seite


def test_vorschau_ist_gekuerzt_und_escaped():
    lead = _lead()
    _entwurf(lead, text='X' * 300 + '<script>alert(1)</script>')
    seite = _get("/freigaben").text
    assert "<script" not in seite
    assert "…" in seite


def test_bearbeitungsfeld_nur_bei_offenen_entwuerfen():
    lead = _lead()
    _entwurf(lead, status="pending")
    assert 'action="/aktion/bearbeiten"' in _get("/freigaben").text
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.drafts cascade")
    _entwurf(lead, status="approved")
    assert 'action="/aktion/bearbeiten"' not in _get("/freigaben").text


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


# ---------------------------------------------------------------------------
# Medien ansehen und loeschen (Betreiber-Wunsch 25.08.2026)
#
# „ich möchte noch eine möglichkeit die documente zu previewn oder die videos
# abzuspielen und delete soll auch möglich sein."
#
# Zwei Kanten, die hier zaehlen: die Datei wird zum ANSEHEN ausgeliefert,
# nicht zum Ausfuehren — und geloescht wird nichts, woran ein freigegebener
# Entwurf haengt.
# ---------------------------------------------------------------------------

def test_bild_wird_eingebettet_video_abgespielt_pdf_verlinkt(medienordner):
    for name in ("bild.png", "clip.mp4", "unterlage.pdf"):
        (medienordner / name).write_bytes(b"x" * 64)
    seite = _get("/medien").text
    assert '<img src="/medien/datei/bild.png"' in seite
    assert '<video class="vorschau" controls preload="none"' in seite
    # PDF wird NICHT eingebettet — es kann JavaScript enthalten.
    assert "unterlage.pdf" in seite
    assert '<embed' not in seite and '<object' not in seite


def test_csp_erlaubt_bilder_und_medien_nur_von_self():
    kopf = _get("/medien").headers["content-security-policy"]
    assert "img-src 'self'" in kopf
    assert "media-src 'self'" in kopf
    assert "default-src 'none'" in kopf


def test_datei_wird_mit_dem_typ_der_whitelist_ausgeliefert(medienordner):
    (medienordner / "bild.png").write_bytes(b"PNGDATEN")
    antwort = _get("/medien/datei/bild.png")
    assert antwort.status_code == 200
    assert antwort.content == b"PNGDATEN"
    assert antwort.headers["content-type"].startswith("image/png")
    assert antwort.headers["x-content-type-options"] == "nosniff"


def test_ausgelieferte_datei_traegt_die_haertere_richtlinie(medienordner):
    (medienordner / "bild.png").write_bytes(b"x")
    kopf = _get("/medien/datei/bild.png").headers["content-security-policy"]
    assert "sandbox" in kopf
    assert "default-src 'none'" in kopf


def test_datei_mit_pfad_wird_nicht_ausgeliefert(medienordner):
    assert _get("/medien/datei/..%2F..%2Fetc%2Fpasswd").status_code in (404, 400)


def test_unbekannte_datei_ist_404(medienordner):
    assert _get("/medien/datei/gibtsnicht.png").status_code == 404


def test_loeschen_zeigt_erst_die_warnseite(medienordner):
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    antwort = _post("/medien/loeschen",
                    {"name": "bild.png", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 409
    assert "Loeschen bestaetigen" in antwort.text
    assert (medienordner / "bild.png").is_file()      # nichts passiert


def test_loeschen_nennt_die_haengenden_entwuerfe(medienordner):
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    lead = _lead()
    _entwurf(lead, status="pending")
    server._q("update drafts set media_ref = %s where lead_id = %s",
              ("bild.png", lead))
    antwort = _post("/medien/loeschen",
                    {"name": "bild.png", "csrf": ui.CSRF_TOKEN})
    assert "haengen 1" in antwort.text or "haengen" in antwort.text


def test_bestaetigtes_loeschen_entfernt_die_datei(medienordner):
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    antwort = _post("/medien/loeschen-bestaetigen",
                    {"name": "bild.png", "name_bestaetigt": "bild.png",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    assert not (medienordner / "bild.png").exists()


def test_ohne_gelesenen_namen_wird_nicht_geloescht(medienordner):
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    antwort = _post("/medien/loeschen-bestaetigen",
                    {"name": "bild.png", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert (medienordner / "bild.png").is_file()


def test_freigegebener_entwurf_blockiert_das_loeschen(medienordner):
    """Der Versender liest die Datei erst beim Zustellen — jeden Moment."""
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    lead = _lead()
    _entwurf(lead, status="approved")
    server._q("update drafts set media_ref = %s where lead_id = %s",
              ("bild.png", lead))
    antwort = _post("/medien/loeschen-bestaetigen",
                    {"name": "bild.png", "name_bestaetigt": "bild.png",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 409
    assert (medienordner / "bild.png").is_file()


def test_loeschen_ohne_csrf_ist_403(medienordner):
    (medienordner / "bild.png").write_bytes(b"x" * 64)
    assert _post("/medien/loeschen",
                 {"name": "bild.png"}).status_code == 403
    assert (medienordner / "bild.png").is_file()


# ---------------------------------------------------------------------------
# WhatsApp-Freigabe in der Oberflaeche (25.08.2026)
#
# Sie fehlte: der Betreiber konnte in der Kontaktliste `auto` einstellen, aber
# die Voraussetzung dafuer nirgends setzen. Der Waehler sagte „ohne Wirkung",
# ohne einen Weg anzubieten — dieselbe Sackgasse wie die Wiedervorlagen-Seite
# ohne Anlege-Formular.
# ---------------------------------------------------------------------------

def test_kontaktseite_zeigt_die_freigabe_und_den_weg():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert "WhatsApp-Freigabe" in seite
    assert "Nicht erteilt" in seite
    assert 'action="/kontakte/freigeben"' in seite


def test_freigeben_und_entziehen_ueber_die_oberflaeche():
    lead = _lead()
    antwort = _post("/kontakte/freigeben",
                    {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    z = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._whatsapp_freigegeben(z["enrichment"]) is True

    antwort = _post("/kontakte/freigabe-entziehen",
                    {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    z = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._whatsapp_freigegeben(z["enrichment"]) is False


def test_freigabe_ohne_csrf_ist_403():
    lead = _lead()
    assert _post("/kontakte/freigeben", {"lead_id": lead}).status_code == 403
    z = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert server._whatsapp_freigegeben(z["enrichment"]) is False


def test_auto_ohne_freigabe_verweist_auf_den_weg():
    """Eine Warnung, die nicht sagt wo man es behebt, ist eine Sackgasse."""
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    seite = _get("/kontakte").text
    assert "ohne Wirkung" in seite
    assert f'href="/kontakte/{lead}#freigabe"' in seite


def test_auto_mit_freigabe_warnt_nicht_mehr():
    lead = _lead()
    server.kontakt_freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "auto")
    assert "ohne Wirkung" not in _get("/kontakte").text


# ---------------------------------------------------------------------------
# Pipeline (27.08.2026): Spaltensicht plus Stufen-Formular auf der
# Kontaktseite — derselbe Werkzeugweg wie der Chat, jeder Wechsel eine
# Beweiszeile.
# ---------------------------------------------------------------------------

def test_die_pipeline_zeigt_die_aktiven_stufen_als_spalten():
    """Seit 01.09.2026 bewusst VERENGT: nur der Fluss (neu … termin) —
    acht Spalten ueberragten jeden Bildschirm. gewonnen/verloren stehen
    auf /ergebnisse (Vertraege am Dateiende)."""
    lead = _lead(name="Paula Pipelinefrau")
    server.kontakt_stufe_setzen(lead, "termin", "Termin steht")
    seite = _get("/pipeline").text
    for stufe in server.PIPELINE_STUFEN[:-2]:
        assert stufe in seite
    assert "Paula Pipelinefrau" in seite


def test_stufe_setzen_ueber_die_oberflaeche_schreibt_den_beweis():
    lead = _lead()
    antwort = _post("/kontakte/stufe", {
        "lead_id": lead, "stufe": "kontaktiert",
        "begruendung": "", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    zeile = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'stufenwechsel'", (lead,))[0]
    assert zeile["payload"]["nach"] == "kontaktiert"
    assert "Oberflaeche" in zeile["payload"]["begruendung"]


def test_stufe_ohne_csrf_schreibt_nichts():
    lead = _lead()
    antwort = _post("/kontakte/stufe", {
        "lead_id": lead, "stufe": "kontaktiert", "begruendung": "x"})
    assert antwort.status_code in (400, 403)
    assert server._q(
        "select count(*) n from activities where lead_id = %s and "
        "type = 'stufenwechsel'", (lead,))[0]["n"] == 0


# ---------------------------------------------------------------------------
# Privat-Markierung (P3, 29.08.2026): Warnseite vor dem Setzen (kuenftige
# Nachrichten sind unwiederbringlich still), Aufheben direkt, Schloss in
# der Liste.
# ---------------------------------------------------------------------------

def test_privat_setzen_braucht_die_warnseite():
    lead = _lead()
    erste = _post("/kontakte/privat", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert erste.status_code == 200
    assert "nichts mehr gespeichert" in erste.text
    assert server._privat(server._q(
        "select enrichment from leads where id = %s",
        (lead,))[0]["enrichment"]) is False
    zweite = _post("/kontakte/privat-bestaetigen", {
        "lead_id": lead, "name_bestaetigt": "Max Testperson",
        "csrf": ui.CSRF_TOKEN})
    assert zweite.status_code == 303
    assert server._privat(server._q(
        "select enrichment from leads where id = %s",
        (lead,))[0]["enrichment"]) is True


def test_privat_aufheben_geht_direkt():
    lead = _lead()
    server.kontakt_privat_setzen(lead)
    antwort = _post("/kontakte/privat-entziehen",
                    {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    assert server._privat(server._q(
        "select enrichment from leads where id = %s",
        (lead,))[0]["enrichment"]) is False


def test_das_schloss_steht_in_der_liste():
    lead = _lead()
    server.kontakt_privat_setzen(lead)
    assert "privat" in _get("/kontakte").text


# ---------------------------------------------------------------------------
# Freigegeben wird, was GELESEN wurde (29.08.2026): der Lese-Stand bindet
# die Freigabe an den angezeigten Wortlaut. Vorfall am selben Tag: Seite
# vor einer Ueberarbeitung geladen, Klick danach — freigegeben wurde ein
# anderer Text als der gelesene.
# ---------------------------------------------------------------------------

def test_veralteter_lese_stand_gibt_nichts_frei():
    lead = _lead()
    draft = _entwurf(lead)
    alter_stand = _lese_stand(draft)
    server.entwurf_bearbeiten(draft, "Voellig neuer Text nach dem Laden.")
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN,
                                    "stand": alter_stand})
    assert r.status_code == 409
    assert "geaendert" in r.text
    assert _zeile(draft)["status"] == "pending"


def test_ohne_lese_stand_gibt_es_keine_freigabe():
    lead = _lead()
    draft = _entwurf(lead)
    r = _post("/aktion/freigeben", {"draft_id": draft, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert _zeile(draft)["status"] == "pending"


def test_die_karte_traegt_den_lese_stand():
    lead = _lead()
    draft = _entwurf(lead)
    assert f'name="stand" value="{_lese_stand(draft)}"' in _get("/freigaben").text


# ---------------------------------------------------------------------------
# WhatsApp-Zustandsseite (29.08.2026): liest NUR — und bleibt stehen, wenn
# OpenWA nicht antwortet. Genau dann wird sie gebraucht.
# ---------------------------------------------------------------------------

def test_whatsapp_seite_ohne_zugang_erklaert_statt_zu_scheitern(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "")
    seite = _get("/whatsapp")
    assert seite.status_code == 200
    assert "OPENWA_VIEWER_KEY" in seite.text


def test_whatsapp_seite_uebersetzt_den_zustand(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(ui, "_openwa_lesen", lambda pfad: (
        [{"id": "s1", "status": "qr_ready", "phone": "4917000",
          "pushName": "Test", "connectedAt": "2026-08-29T07:00:00Z",
          "lastActive": None, "engineLoaded": True}], None))
    seite = _get("/whatsapp").text
    assert "wartet auf Kopplung" in seite      # Klartext, nicht nur qr_ready
    assert "nichts kommt an" in seite          # die Folge steht dabei
    assert "29.08.2026 09:00" in seite         # ISO -> Ortszeit (CEST)
    assert "UTC" not in seite                   # keine zwei Zeitzonen mehr


def test_whatsapp_seite_warnt_wenn_nie_etwas_ankam(monkeypatch):
    """Der Weg in den Posteingang wird aus der DATENBANK belegt, nicht aus
    dem Webhook-Register: eine eingetragene Zeile beweist nichts, eine
    angekommene Nachricht schon."""
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda pfad: ([{"id": "s1", "status": "ready"}], None))
    seite = _get("/whatsapp").text
    assert "NIE eine" in seite
    assert "unbewiesen" in seite


def test_whatsapp_seite_belegt_die_kette_mit_einer_echten_nachricht(monkeypatch):
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "Hallo"})))
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda pfad: ([{"id": "s1", "status": "ready"}], None))
    seite = _get("/whatsapp").text
    assert "Die Kette bis in die Datenbank funktioniert" in seite


def test_whatsapp_seite_haelt_einen_openwa_ausfall_aus(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "_openwa_lesen",
                        lambda p: (None, "OpenWA ist nicht erreichbar"))
    seite = _get("/whatsapp")
    assert seite.status_code == 200
    assert "nicht erreichbar" in seite.text


def test_der_nav_fuehrt_zur_whatsapp_seite():
    assert 'href="/whatsapp"' in _get("/freigaben").text


# ---------------------------------------------------------------------------
# Kleinigkeiten aus dem Browser-Durchgang (29.08.2026).
# ---------------------------------------------------------------------------

def test_die_consent_spalte_erklaert_sich():
    """Sie zeigte bei jedem Kontakt dasselbe 'unknown' — ohne Erklaerung
    ist das keine Information, sondern eine offene Frage in der Ansicht.

    Der Kontakt ist noetig: ohne Zeilen zeigt die Seite nur den
    Leer-Hinweis, und dort gehoert keine Spaltenerklaerung hin."""
    _lead()
    seite = _get("/kontakte").text
    assert "Werbe-Einwilligung" in seite
    assert "nie erfasst" in seite
    assert "NICHT die WhatsApp-Freigabe" in seite
    # Seit F5 (31.08.2026) blockiert Consent tatsaechlich — die Fussnote
    # darf nicht mehr behaupten, sie blockiere nichts (test_uwg.py).
    assert "blockiert derzeit nichts" not in seite
    assert "kein Erstansprache-" in seite


def test_sprachnachricht_ohne_text_wird_benannt():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "", "nachrichtentyp": "ptt",
                                   "message_id": "wa-ptt-1"})))
    seite = _get("/posteingang").text
    assert "Sprachnachricht" in seite
    assert "kein Text zum Mitlesen" in seite


# ---------------------------------------------------------------------------
# /einordnung/nachrichten/<kennung> — alle Nachrichten eines Absenders
# (Betreiber-Wunsch 31.08.2026: die Kurzfassung auf der Einordnungskarte
# reicht nicht immer, um zu entscheiden, wer da schreibt.)
# ---------------------------------------------------------------------------

SOPHIE_KENNUNG = "183096603361451"     # _roh_ziffern(SOPHIE_LID)


def test_einordnung_verlinkt_die_nachrichtenliste(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Wer bin ich?", absender=SOPHIE_LID)
    seite = _get("/einordnung").text
    assert f'href="/einordnung/nachrichten/{SOPHIE_KENNUNG}"' in seite


def test_nachrichtenliste_zeigt_alle_chronologisch_und_nur_eigene(
        sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="Erste Nachricht", absender=SOPHIE_LID)
    _kundenantwort(sammel, text="Zweite Nachricht", absender=SOPHIE_LID)
    _kundenantwort(sammel, text="Fremder Faden", absender="4915205134135@c.us")
    seite = _get(f"/einordnung/nachrichten/{SOPHIE_KENNUNG}").text
    assert "Erste Nachricht" in seite and "Zweite Nachricht" in seite
    assert seite.index("Erste Nachricht") < seite.index("Zweite Nachricht")
    assert "Fremder Faden" not in seite


def test_nachrichtenliste_escaped_fremddaten(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="<script>alert(1)</script>",
                   absender=SOPHIE_LID)
    seite = _get(f"/einordnung/nachrichten/{SOPHIE_KENNUNG}").text
    assert "<script>alert(1)</script>" not in seite
    assert "&lt;script&gt;" in seite


def test_nachrichtenliste_benennt_nachrichten_ohne_text(sammelkontakt_zurueck):
    sammel = _sammel()
    _kundenantwort(sammel, text="", absender=SOPHIE_LID, typ="ptt")
    seite = _get(f"/einordnung/nachrichten/{SOPHIE_KENNUNG}").text
    assert "Sprachnachricht" in seite
    assert "kein Text zum Mitlesen" in seite


def test_nachrichtenliste_unbekannte_kennung_ist_eine_meldung(
        sammelkontakt_zurueck):
    _sammel()
    antwort = _get("/einordnung/nachrichten/999999999999")
    assert antwort.status_code == 404
    assert "keine Nachrichten" in antwort.text


def test_nachrichtenliste_kaputte_kennung_wird_abgewiesen(
        sammelkontakt_zurueck):
    _sammel()
    assert _get("/einordnung/nachrichten/abc123").status_code == 400
    assert _get("/einordnung/nachrichten/1").status_code == 400


# ---------------------------------------------------------------------------
# Pipeline-Zuschnitt (01.09.2026, Betreiber-Feedback): die acht Spalten
# ueberragten jeden Bildschirm — die Seite wirkte abgeschnitten. Die
# Pipeline zeigt jetzt den FLUSS (neu … termin); die Endzustaende
# gewonnen/verloren haben ihren eigenen Tab „Ergebnisse".
# ---------------------------------------------------------------------------

def test_pipeline_zeigt_nur_die_aktiven_stufen():
    _lead()
    seite = _get("/pipeline").text
    for aktiv in ("neu", "recherchiert", "qualifiziert", "kontaktiert",
                  "geantwortet", "termin"):
        assert f"<h2>{aktiv} " in seite
    assert "<h2>gewonnen " not in seite
    assert "<h2>verloren " not in seite
    assert 'href="/ergebnisse"' in seite      # Verweis statt Spalte


def test_ergebnisse_zeigt_gewonnen_und_verloren():
    gewonnen = _lead(name="Kunde Gewonnen")
    server._q("update leads set status = 'won' where id = %s returning id",
              (gewonnen,))
    verloren = _lead(name="Kontakt Verloren", phone="+491702223344")
    server._q("update leads set status = 'lost' where id = %s returning id",
              (verloren,))
    _lead(name="Aktiver Kontakt", phone="+491703334455")
    seite = _get("/ergebnisse").text
    assert "Kunde Gewonnen" in seite
    assert "Kontakt Verloren" in seite
    assert "Aktiver Kontakt" not in seite


def test_ergebnisse_steht_in_der_navigation():
    seite = _get("/pipeline").text
    assert 'href=\"/ergebnisse\"' in seite


def test_kontaktseite_zeigt_die_recherche_arbeit():
    lead = _lead()
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true) where id = %s returning id",
        (json.dumps({"website": "https://beispiel-makler.de",
                     "seiten": [{"url": "https://beispiel-makler.de/ueber",
                                 "typ": "ueber", "titel": "Über uns",
                                 "text": "Wir <script>x</script> beraten."}],
                     "seiten_anzahl": 1}), lead))
    seite = _get(f"/kontakte/{lead}").text
    assert "Recherche" in seite
    assert "beispiel-makler.de" in seite
    assert "Über uns" in seite
    assert "<script>x</script>" not in seite   # Fremddaten bleiben escaped


def test_kontaktseite_ohne_recherche_zeigt_den_leerstand():
    lead = _lead()
    seite = _get(f"/kontakte/{lead}").text
    assert "Noch keine Firmendaten" in seite


def test_kontaktseite_zeigt_die_geschaeftsverweise():
    lead = _lead()
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true) where id = %s returning id",
        (json.dumps({"website": "https://x.de", "seiten": [],
                     "verweise": [
                         {"plattform": "LinkedIn",
                          "url": "https://linkedin.com/company/x"},
                         {"plattform": "Instagram",
                          "url": "https://instagram.com/x"}]}), lead))
    seite = _get(f"/kontakte/{lead}").text
    assert "LinkedIn" in seite and "Instagram" in seite
    assert 'href="https://linkedin.com/company/x"' in seite
    assert 'rel="noopener noreferrer nofollow"' in seite


@pytest.mark.parametrize("typ,erwartet", [
    ("voice", "Sprachnachricht"),      # OpenWA schickt 'voice' — gemessen
    ("ptt", "Sprachnachricht"),        # historische Schreibweise
    ("audio", "Tonaufnahme"),
    ("image", "Bild"),
])
def test_nachrichtentypen_werden_benannt(typ, erwartet):
    """Live-Messung 01.09.2026: OpenWA liefert 'voice' (16 Nachrichten in
    30 Tagen), die Benennung kannte nur 'ptt' — sie standen als 'ohne
    Text' da, als waere nichts angekommen."""
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "", "nachrichtentyp": typ,
                                   "message_id": f"wa-{typ}-1"})))
    seite = _get("/posteingang").text
    assert erwartet in seite


def test_verlauf_zeigt_sprachnachricht_und_transkription():
    """01.09.2026: eine Sprachnachricht stand als leere Zeile im Verlauf.
    Jetzt wird sie benannt, und die Transkription steht als eigene Zeile
    dahinter (append-only — die Nachricht selbst bleibt unveraendert)."""
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "", "nachrichtentyp": "voice",
                                   "audio_datei": "abc.ogg",
                                   "message_id": "wa-v-1"})))
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'transkription', %s) returning id",
              (lead, server._json({"text": "Ich haette eine Frage zur Police.",
                                   "message_id": "wa-v-1", "sprache": "de"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "Sprachnachricht" in seite
    assert "abgehoert" in seite
    assert "Ich haette eine Frage zur Police." in seite


# ---------------------------------------------------------------------------
# Kalender-Tab (01.09.2026, Betreiber-Wunsch): die Termine an EINER Stelle,
# statt sie aus dem Verlauf einzelner Kontakte zu suchen. Quelle sind die
# Termin-Aktivitaeten und die offenen Wiedervorlagen — beides steht schon
# in der Datenbank. Der CalDAV-Kalender selbst laesst sich nicht einbetten
# (kein Web-UI), seine Eintraege holt der Tab optional dazu.
# ---------------------------------------------------------------------------

def _termin(lead, datum, uhrzeit="10:00", thema="Beratung", ort="Buero"):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin', %s) returning id",
              (lead, server._json({"datum": datum, "uhrzeit": uhrzeit,
                                   "thema": thema, "ort": ort,
                                   "dauer_minuten": 60})))


def test_kalender_steht_in_der_navigation():
    assert 'href="/kalender"' in _get("/pipeline").text


def test_kalender_zeigt_kommende_termine_mit_kontakt():
    lead = _lead(name="Sabrina Schmidt")
    _termin(lead, "2099-09-04", thema="Erstgespraech bAV")
    seite = _get("/kalender").text
    assert "Sabrina Schmidt" in seite
    assert "Erstgespraech bAV" in seite
    assert "04.09.2099" in seite


def test_kalender_trennt_kommend_von_vergangen():
    lead = _lead()
    _termin(lead, "2020-01-15", thema="Lange her")
    _termin(lead, "2099-09-04", thema="Steht an")
    seite = _get("/kalender").text
    assert seite.index("Steht an") < seite.index("Lange her")


def test_kalender_zeigt_offene_wiedervorlagen():
    lead = _lead(name="Max Wiedervorlage")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'wiedervorlage', %s) returning id",
              (lead, server._json({"faellig_am": "2099-10-01",
                                   "notiz": "Angebot nachfassen"})))
    seite = _get("/kalender").text
    assert "Angebot nachfassen" in seite
    assert "Max Wiedervorlage" in seite


def test_kalender_escaped_fremddaten():
    lead = _lead(name="<script>boese()</script>")
    _termin(lead, "2099-09-04", thema="<b>fett</b>")
    seite = _get("/kalender").text
    assert "<script>boese()</script>" not in seite
    assert "&lt;b&gt;fett&lt;/b&gt;" in seite


def test_kalender_ohne_termine_ist_kein_fehler():
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    assert "Kein Termin" in antwort.text


# ---------------------------------------------------------------------------
# Medien nach Art gruppiert (01.09.2026, Betreiber-Wunsch): 11 Dateien in
# einer flachen Liste — Videos, PDFs und Kalenderdateien durcheinander.
# ---------------------------------------------------------------------------

def test_medien_gruppiert_nach_art(medienordner):
    (medienordner / "film.mp4").write_bytes(b"\x00" * 40)
    (medienordner / "unterlage.pdf").write_bytes(b"%PDF-1.4 x")
    (medienordner / "bild.png").write_bytes(b"\x89PNG\r\n\x1a\n x")
    seite = _get("/medien").text
    for ueberschrift in ("Videos", "Dokumente", "Bilder"):
        assert ueberschrift in seite
    assert "film.mp4" in seite and "unterlage.pdf" in seite


def test_medien_zeigt_erzeugte_getrennt(medienordner, tmp_path, monkeypatch):
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    (erzeugt / "termin-x-2099-09-04.ics").write_text("BEGIN:VCALENDAR")
    monkeypatch.setattr(server.medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    seite = _get("/medien").text
    assert "termin-x-2099-09-04.ics" in seite
    assert "Termine" in seite


def test_zeiten_stehen_in_ortszeit_nicht_utc():
    """01.09.2026 im Kalender gefunden: ein 12:00-Termin stand als
    '10:00 UTC' da. In einem Kalender ist das nicht nur unschoen — wer
    danach plant, verpasst den Termin."""
    from datetime import datetime, timezone
    dt = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    assert ui._zeit(dt) == "02.09.2026 12:00"      # Europe/Berlin, Sommer
    winter = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert ui._zeit(winter) == "15.01.2026 11:00"  # Winterzeit
    assert ui._zeit(None) == "—"


def test_kalender_zeigt_terminanfragen_ohne_datum_getrennt():
    """Eine `termin`-Aktivitaet ohne Datum ist eine offene Anfrage
    ('Donnerstag 16 Uhr — welcher?'), kein vergangener Termin. Sie stand
    als leere Zeile unter 'Vergangen'."""
    lead = _lead(name="Lisa Probekunde")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin', %s) returning id",
              (lead, server._json({"inhalt": "Donnerstag 16 Uhr, unklar"})))
    seite = _get("/kalender").text
    assert "Ohne festes Datum" in seite
    assert "Donnerstag 16 Uhr, unklar" in seite
    assert "Vergangen" not in seite      # nichts Vergangenes vorhanden


def test_kalender_warnt_bei_terminkollision():
    lead = _lead(name="Sabrina Schmidt")
    _termin(lead, "2099-09-04", uhrzeit="13:00", thema="Erstgespraech")
    _termin(lead, "2099-09-04", uhrzeit="13:00", thema="Team-Meeting")
    seite = _get("/kalender").text
    assert "Doppelt belegt" in seite


# ---------------------------------------------------------------------------
# Monatsansicht (01.09.2026, Betreiber: „warum nicht wie eine normale
# Kalenderansicht?"). Ein Kalender ist ein Gitter — Wochentage als
# Spalten, ein Kasten je Tag, Termine darin. Die Listen darunter bleiben:
# sie tragen, was ein Gitter nicht zeigen kann (Wiedervorlagen, Anfragen
# ohne Datum, doppelt belegte Zeiten).
# ---------------------------------------------------------------------------

def test_kalender_hat_ein_monatsgitter():
    seite = _get("/kalender").text
    assert 'class="monat"' in seite
    for tag in ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"):
        assert f'>{tag}<' in seite


def test_monatsgitter_zeigt_den_termin_im_richtigen_kasten():
    lead = _lead(name="Sabrina Schmidt")
    _termin(lead, "2099-09-04", uhrzeit="13:00", thema="Erstgespraech")
    seite = _get("/kalender?monat=2099-09").text
    assert "September 2099" in seite
    assert "13:00" in seite and "Erstgespraech" in seite
    # Der 4.9.2099 ist ein Freitag — der Kasten traegt sein Datum.
    assert 'data-tag="2099-09-04"' in seite


def test_monatsgitter_blaettert_vor_und_zurueck():
    seite = _get("/kalender?monat=2099-09").text
    assert 'href="/kalender?monat=2099-08"' in seite
    assert 'href="/kalender?monat=2099-10"' in seite


def test_monatsgitter_zeigt_auch_die_kalendertermine(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(ui.kalender, "termine_lesen", lambda **k: ([{
        "beginn": datetime(2099, 9, 11, 8, 30, tzinfo=timezone.utc),
        "titel": "Fremder Termin", "ort": "Zoom", "uid": "x"}], None))
    seite = _get("/kalender?monat=2099-09").text
    assert "Fremder Termin" in seite


def test_kaputter_monat_faellt_auf_heute_zurueck():
    for kaputt in ("2099-13", "quatsch", "2099", ""):
        antwort = _get(f"/kalender?monat={kaputt}")
        assert antwort.status_code == 200


# ---------------------------------------------------------------------------
# Termine aendern in der Oberflaeche (01.09.2026, Betreiber: „geht das
# auch mit Daten-Editierung?"). Dieselben Werkzeuge wie im Chat — die
# Oberflaeche baut keinen zweiten Schreibweg (Muster der Freigaben).
# ---------------------------------------------------------------------------

def _termin_mit_uid(lead, uid="test-uid-1", datum="2099-09-04"):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin', %s) returning id",
              (lead, server._json({"datum": datum, "uhrzeit": "13:00",
                                   "thema": "Erstgespraech", "uid": uid,
                                   "dauer_minuten": 60})))
    return uid


def test_kalender_bietet_absagen_und_verschieben():
    lead = _lead()
    _termin_mit_uid(lead)
    seite = _get("/kalender").text
    assert 'action="/kalender/absagen"' in seite
    assert 'action="/kalender/verschieben"' in seite


def test_absagen_ohne_csrf_aendert_nichts():
    lead = _lead()
    uid = _termin_mit_uid(lead)
    antwort = _post("/kalender/absagen",
                    {"lead_id": lead, "uid": uid, "grund": "weg"})
    assert antwort.status_code == 403
    assert server._q("select count(*) n from activities where "
                     "type = 'termin_abgesagt'")[0]["n"] == 0


def test_absagen_ueber_die_oberflaeche_schreibt_den_beweis():
    lead = _lead()
    uid = _termin_mit_uid(lead)
    antwort = _post("/kalender/absagen",
                    {"lead_id": lead, "uid": uid,
                     "grund": "Kunde hat abgesagt", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    zeilen = server._q("select payload from activities where "
                       "type = 'termin_abgesagt'")
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["uid"] == uid


def test_verschieben_ueber_die_oberflaeche():
    lead = _lead()
    uid = _termin_mit_uid(lead)
    antwort = _post("/kalender/verschieben",
                    {"lead_id": lead, "uid": uid, "datum": "2099-09-11",
                     "uhrzeit": "15:30", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303
    neue = server._q("select payload from activities where type = 'termin' "
                     "order by created_at desc limit 1")[0]["payload"]
    assert neue["datum"] == "2099-09-11" and neue["uhrzeit"] == "15:30"


def test_abgesagte_termine_verschwinden_aus_dem_kalender():
    lead = _lead()
    uid = _termin_mit_uid(lead)
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin_abgesagt', %s) returning id",
              (lead, server._json({"uid": uid, "grund": "abgesagt"})))
    seite = _get("/kalender").text
    assert "Erstgespraech" not in seite
    assert "Abgesagt (1)" in seite


# ---------------------------------------------------------------------------
# OpenWA direkt im WhatsApp-Tab (02.09.2026, Betreiber-Wunsch). Das
# Dashboard laeuft unter seiner eigenen HTTPS-Adresse; eingebettet wird es
# nur dann, und die Seite oeffnet ihr CSP GENAU fuer diese eine Origin.
# Alle anderen Seiten behalten `default-src 'none'` ohne frame-src.
# ---------------------------------------------------------------------------

def _wa_stub(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_VIEWER_KEY", "egal")
    monkeypatch.setattr(ui, "OPENWA_SESSION_ID", "")
    monkeypatch.setattr(ui, "_openwa_lesen", lambda pfad: ([], None))


def test_whatsapp_tab_bettet_das_dashboard_ein(monkeypatch):
    _wa_stub(monkeypatch)
    monkeypatch.setattr(ui, "OPENWA_DASHBOARD_URL",
                        "https://vm.beispiel.ts.net:8443/")
    antwort = _get("/whatsapp")
    assert antwort.status_code == 200
    assert '<iframe class="dashboard" src="https://vm.beispiel.ts.net:8443/"' \
        in antwort.text
    csp = antwort.headers["content-security-policy"]
    assert "frame-src https://vm.beispiel.ts.net:8443" in csp
    assert csp.startswith("default-src 'none'")       # Rest bleibt hart
    assert 'http-equiv="refresh"' not in antwort.text  # kein Minuten-Reload


def test_loopback_dashboard_wird_nicht_eingebettet(monkeypatch):
    """Die Vorgabe http://127.0.0.1:12785 zeigt auf die VM selbst — im
    Browser des Betreibers ein leerer Rahmen. Sie bleibt ein Verweis."""
    _wa_stub(monkeypatch)
    monkeypatch.setattr(ui, "OPENWA_DASHBOARD_URL", "http://127.0.0.1:12785")
    antwort = _get("/whatsapp")
    assert "<iframe" not in antwort.text
    assert 'href="http://127.0.0.1:12785"' in antwort.text
    assert "frame-src" not in antwort.headers["content-security-policy"]


def test_andere_seiten_oeffnen_kein_frame_src(monkeypatch):
    monkeypatch.setattr(ui, "OPENWA_DASHBOARD_URL",
                        "https://vm.beispiel.ts.net:8443/")
    for pfad in ("/", "/kontakte", "/kalender", "/medien"):
        csp = _get(pfad).headers["content-security-policy"]
        assert "frame-src" not in csp, pfad


def test_dashboard_url_ist_fremddatum_und_wird_escaped(monkeypatch):
    _wa_stub(monkeypatch)
    monkeypatch.setattr(ui, "OPENWA_DASHBOARD_URL",
                        'https://vm.beispiel.ts.net:8443/"><script>x</script>')
    text = _get("/whatsapp").text
    assert "<script>x</script>" not in text
