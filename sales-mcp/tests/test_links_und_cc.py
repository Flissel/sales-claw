"""Verträge (03.09.2026): Hyperlinks sind klickbar, E-Mails koennen CC.

Betreiber: „Hyperlinks werden nicht korrekt als Hyperlinks angezeigt,
sondern als Text" und „Leute ins CC setzen hat noch nicht gefunkt."
Gemessen: jeder Text lief nur durch html.escape (richtig), aber ohne
Verlinkung; das Betreiber-Mail-Werkzeug kannte keinen CC-Parameter, drafts
hatte keine Spalte dafuer, der Versender setzte nur `To`.
"""
import json

import pytest
from starlette.testclient import TestClient

import mail_dispatch
import server
import ui

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


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(pfad, daten):
    return CLIENT.post(pfad, data=daten, headers={"host": HOST_OK},
                       follow_redirects=False)


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, text, kanal="whatsapp", betreff=None, cc=None,
             empfaenger="+491701234567"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, subject, cc, "
        "status) values (%s, %s, %s, %s, %s, %s, 'pending') returning id",
        (lead, kanal, empfaenger, text, betreff, cc))[0]["id"])


# --- Hyperlinks ------------------------------------------------------------

def test_links_werden_klickbar_und_alles_andere_bleibt_escaped():
    lead = _lead()
    _entwurf(lead, "Schau mal https://vibemind.space/angebot?x=1&y=2. "
                   "Und <script>alert(1)</script> bleibt Text.")
    seite = _get("/freigaben").text
    assert ('<a href="https://vibemind.space/angebot?x=1&amp;y=2" '
            'rel="noreferrer noopener" target="_blank">'
            'https://vibemind.space/angebot?x=1&amp;y=2</a>.') in seite
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in seite
    assert "<script>" not in seite


def test_nur_http_und_https_werden_verlinkt():
    lead = _lead()
    _entwurf(lead, "javascript:alert(1) und ftp://x.y und http://klar.de/ok")
    seite = _get("/freigaben").text
    assert '<a href="javascript' not in seite
    assert '<a href="ftp' not in seite
    assert '<a href="http://klar.de/ok"' in seite


def test_links_auch_im_posteingang():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s::jsonb) returning id",
              (lead, json.dumps({"text": "Hier: https://kunde.example/seite"})))
    seite = _get("/posteingang").text
    assert '<a href="https://kunde.example/seite"' in seite


# --- CC ------------------------------------------------------------------

@pytest.fixture
def betreiber_postausgang(monkeypatch):
    sammel = _lead(name="Betreiber-Postausgang", phone="+490000000000")
    monkeypatch.setattr(server, "BETREIBER_MAIL_LEAD_ID", sammel)
    return sammel


def test_betreiber_mail_nimmt_cc_und_prueft_es(betreiber_postausgang):
    antwort = json.loads(server.betreiber_mail_entwurf(
        "ziel@example.org", "Betreff", "Text",
        cc="a@example.org, b@example.org"))
    assert "fehler" not in antwort, antwort
    zeile = server._q("select cc from drafts where id = %s",
                      (antwort["draft_id"],))[0]
    assert zeile["cc"] == "a@example.org, b@example.org"
    kaputt = json.loads(server.betreiber_mail_entwurf(
        "ziel@example.org", "Betreff", "Text", cc="kein-adresse"))
    assert "fehler" in kaputt and "CC" in kaputt["fehler"]
    ohne = json.loads(server.betreiber_mail_entwurf(
        "ziel@example.org", "Betreff", "Text"))
    assert server._q("select cc from drafts where id = %s",
                     (ohne["draft_id"],))[0]["cc"] is None


def test_versender_setzt_die_cc_kopfzeile():
    mit = mail_dispatch.nachricht_bauen("ziel@example.org", "B", "T",
                                       cc="a@example.org, b@example.org")
    assert mit["To"] == "ziel@example.org"
    assert mit["Cc"] == "a@example.org, b@example.org"
    ohne = mail_dispatch.nachricht_bauen("ziel@example.org", "B", "T")
    assert ohne["Cc"] is None


def test_oberflaeche_zeigt_cc_und_bearbeitet_es():
    lead = _lead()
    draft = _entwurf(lead, "Mailtext", kanal="email", betreff="Hallo",
                     cc="a@example.org", empfaenger="ziel@example.org")
    seite = _get("/freigaben").text
    assert "CC: <b>a@example.org</b>" in seite
    assert 'name="cc" value="a@example.org"' in seite
    r = _post("/aktion/bearbeiten", {"draft_id": draft, "text": "Mailtext",
                                     "betreff": "Hallo",
                                     "cc": "b@example.org, c@example.org",
                                     "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303, r.text[:300]
    assert server._q("select cc from drafts where id = %s",
                     (draft,))[0]["cc"] == "b@example.org, c@example.org"
    r = _post("/aktion/bearbeiten", {"draft_id": draft, "text": "Mailtext",
                                     "betreff": "Hallo", "cc": "murks",
                                     "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 409



# ---------------------------------------------------------------------------
# Die ausgehende Mail (23.09.2026) — die zweite Haelfte derselben Forderung
# ---------------------------------------------------------------------------
#
# Die Forderung vom 03.09.2026 wurde nur in der OBERFLAECHE erfuellt. Die
# Mail selbst ging weiter als reiner Text raus. Gemessen am 23.09.2026: die
# Terminbestaetigung an einen Kunden trug ihren Konferenzlink als nackte
# Zeichenkette. Ob er klickbar war, entschied allein das Mailprogramm des
# Empfaengers. Jetzt reist neben dem Text eine HTML-Fassung mit echten
# Links, nach DENSELBEN Regeln wie `ui._text_html`.

JITSI = "https://meet.jit.si/PQcfdRqk6XMSiikezhOYe3mvzXNzdJxs"
MIT_LINK = ("Bonjour Stephane,\n\nLien de la réunion : " + JITSI +
            "\n\nCordialement")


def _teile(nachricht):
    return {t.get_content_type(): t for t in nachricht.walk()
            if not t.is_multipart()}


def test_eine_mail_mit_link_traegt_eine_HTML_fassung_mit_echtem_link():
    nachricht = mail_dispatch.nachricht_bauen("k@example.org", "Termin",
                                              MIT_LINK)
    teile = _teile(nachricht)
    assert nachricht.get_content_type() == "multipart/alternative"
    html = teile["text/html"].get_content()
    assert f'<a href="{JITSI}">{JITSI}</a>' in html
    assert "réunion" in html and "<br>" in html


def test_die_TEXTFASSUNG_bleibt_woertlich_was_freigegeben_wurde():
    """Freigegeben wurde der Text. Die HTML-Fassung ist eine Darstellung
    davon, kein zweiter Inhalt — der Text selbst aendert sich um kein Zeichen."""
    nachricht = mail_dispatch.nachricht_bauen("k@example.org", "Termin",
                                              MIT_LINK)
    assert _teile(nachricht)["text/plain"].get_content().rstrip("\n") == \
        MIT_LINK


def test_eine_mail_OHNE_link_bleibt_reiner_text():
    """Kein Anlass, kein Umbau: ohne Link gibt es nichts zu verlinken."""
    nachricht = mail_dispatch.nachricht_bauen("k@example.org", "Hallo",
                                              "Hallo Katrin,\ndanke!")
    assert nachricht.get_content_type() == "text/plain"


def test_im_HTML_wird_erst_escaped_dann_verlinkt():
    """Der Rumpf stammt aus einem Entwurf, und ein Entwurf kann Kundentext
    zitieren. Was darin nach Markup aussieht, bleibt Text; `javascript:`
    wird nie zum Link; Satzzeichen hinter der Adresse gehoeren nicht dazu."""
    rumpf = ("Siehe https://example.org/a?x=1&y=2. Und <script>boese()"
             "</script> javascript:alert(1)")
    html = _teile(mail_dispatch.nachricht_bauen("k@example.org", "x", rumpf)
                  )["text/html"].get_content()
    assert '<a href="https://example.org/a?x=1&amp;y=2">' in html
    assert "</a>." in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript' not in html


def test_die_EINLADUNG_traegt_text_html_und_kalender():
    """Der Weg der Terminbestaetigung: der Kalenderteil muss bleiben, sonst
    fehlen beim Kunden die Schaltflaechen zum Annehmen."""
    ics = ("BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
           "UID:x@y\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    nachricht = mail_dispatch.nachricht_mit_einladung(
        "k@example.org", "Termin", MIT_LINK, ics)
    teile = _teile(nachricht)
    assert set(teile) == {"text/plain", "text/html", "text/calendar"}
    assert f'<a href="{JITSI}">' in teile["text/html"].get_content()
    assert teile["text/calendar"].get_param("method") == "REQUEST"
