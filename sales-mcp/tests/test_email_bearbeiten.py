"""Verträge: E-Mail-Entwürfe lassen sich bearbeiten (03.09.2026).

Betreiber: „es ist grad ein E-Mail-Entwurf drin, ich frag mich, warum ich
die nicht editieren kann." Gemessen: der Entwurf hatte 5.537 Zeichen, das
Textfeld war hart auf 4.096 begrenzt — die WhatsApp-Grenze, für jeden Kanal.
Der Browser nimmt dann weder Eingaben noch das Absenden an. Seitdem gilt
die Grenze je Kanal, und E-Mails bekommen ihren Betreff zum Bearbeiten.
"""
import pytest
from starlette.testclient import TestClient

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


def _lead(name="Martin Muster", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, kanal, text, betreff=None, empfaenger="x@y.de"):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, subject, status) "
        "values (%s, %s, %s, %s, %s, 'pending') returning id",
        (lead, kanal, empfaenger, text, betreff))[0]["id"])


def _textfeld(seite: str, draft_id: str) -> str:
    """Das Bearbeitungsformular DIESES Entwurfs (ab seiner draft_id)."""
    anfang = seite.index(f'<input type="hidden" name="draft_id" value="{draft_id}">'
                         f'<input type="hidden" name="csrf"')
    return seite[anfang:anfang + 3000]


def test_lange_email_ist_bearbeitbar_und_hat_einen_betreff():
    lead = _lead()
    lang = "Sehr geehrter Herr Muster, " + ("x" * 5500)
    draft = _entwurf(lead, "email", lang, betreff="Ihr Angebot")
    seite = _get("/freigaben").text
    assert "Betreff: <b>Ihr Angebot</b>" in seite
    feld = _textfeld(seite, draft)
    assert f'maxlength="{ui.TEXTFELD_MAX["email"]}"' in feld
    assert ui.TEXTFELD_MAX["email"] >= 20000
    assert 'name="betreff" value="Ihr Angebot"' in feld
    assert 'rows="8"' not in feld                     # waechst mit dem Text
    # Aendern von Text und Betreff geht durch — inklusive 5.600 Zeichen.
    neu = "Sehr geehrter Herr Muster, " + ("y" * 5600)
    r = _post("/aktion/bearbeiten", {"draft_id": draft, "text": neu,
                                     "betreff": "Ihr Angebot, aktualisiert",
                                     "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303, r.text[:300]
    zeile = server._q("select body, subject from drafts where id = %s",
                      (draft,))[0]
    assert zeile["body"] == neu
    assert zeile["subject"] == "Ihr Angebot, aktualisiert"


def test_whatsapp_und_linkedin_behalten_ihre_grenzen():
    lead = _lead()
    wa = _entwurf(lead, "whatsapp", "Kurz per WhatsApp", empfaenger="+491701234567")
    li = _entwurf(lead, "linkedin", "Beitrag", empfaenger="eigenes-profil")
    seite = _get("/freigaben").text
    assert 'maxlength="4096"' in _textfeld(seite, wa)
    assert f'maxlength="{server.POST_MAXLAENGE}"' in _textfeld(seite, li)
    assert 'name="betreff"' not in _textfeld(seite, wa)


def test_betreff_ohne_textaenderung_wird_gespeichert():
    lead = _lead()
    draft = _entwurf(lead, "email", "Unveraenderter Text", betreff="Alt")
    r = _post("/aktion/bearbeiten", {"draft_id": draft,
                                     "text": "Unveraenderter Text",
                                     "betreff": "Neu", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert server._q("select subject from drafts where id = %s",
                     (draft,))[0]["subject"] == "Neu"
