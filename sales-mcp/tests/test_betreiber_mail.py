"""Vertragstests fuer den Betreiber-Postausgang (31.08.2026).

Der Betreiber will eigene Korrespondenz (Bewerbungen, Anfragen an
Programme, Behoerden — der Anlassfall war die AI-NATION-Bewerbung) vom
Assistenten vorbereiten lassen. Der einzige Mail-Weg war bis jetzt
`entwurf_erstellen(lead_id, 'email', …)` — der braucht einen CRM-Kontakt
und dessen E-Mail-Adresse.

DAS MODELL BLEIBT: `betreiber_mail_entwurf` legt einen ENTWURF an einem
Systemkontakt an (Muster LINKEDIN_POST_LEAD_ID), mit frei gewaehltem
Empfaenger. Versendet wird ausschliesslich nach Freigabe, ueber den
bestehenden sales-mail-Weg (der an drafts.recipient zustellt, gemessen).

DIE GRENZE BLEIBT AUCH: gehoert die Adresse einem CRM-Kontakt, lehnt das
Werkzeug ab — sonst waere es die Hintertuer am UWG-Tor (F5) und am
Loeschantrag-Vollstopp vorbei.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def postausgang(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    sammel = server._q(
        "insert into leads (name, source) values "
        "('Betreiber-Postausgang', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "BETREIBER_MAIL_LEAD_ID", str(sammel))
    yield str(sammel)


def _entwurf(empfaenger="programm@beispiel.org", betreff="Bewerbung",
             text="Sehr geehrte Damen und Herren, ..."):
    return json.loads(server.betreiber_mail_entwurf(empfaenger, betreff, text))


# ---------------------------------------------------------------------------
# Der gute Weg
# ---------------------------------------------------------------------------

def test_entwurf_landet_pending_am_postausgang(postausgang):
    antwort = _entwurf()
    assert "fehler" not in antwort
    assert antwort["status"] == "pending"
    zeile = server._q(
        "select lead_id::text as lead_id, channel, recipient, subject, "
        "status from drafts where id = %s", (antwort["draft_id"],))[0]
    assert zeile["lead_id"] == postausgang
    assert zeile["channel"] == "email"
    assert zeile["recipient"] == "programm@beispiel.org"
    assert zeile["subject"] == "Bewerbung"
    assert zeile["status"] == "pending"


def test_freigabe_funktioniert_auf_dem_entwurf(postausgang):
    """Die Kette bis zur Versand-Queue: Freigabe wie bei jedem Entwurf —
    sales-mail stellt approved-E-Mails an drafts.recipient zu."""
    draft = _entwurf()["draft_id"]
    frei = json.loads(server.entwurf_freigeben(draft))
    assert "fehler" not in frei
    zeile = server._q("select status from drafts where id = %s", (draft,))[0]
    assert zeile["status"] == "approved"


# ---------------------------------------------------------------------------
# Abweisungen — es entsteht jeweils KEIN Entwurf
# ---------------------------------------------------------------------------

def _kein_draft():
    assert server._q("select count(*) n from drafts")[0]["n"] == 0


@pytest.mark.parametrize("kaputt", ["", "ohne-klammeraffe.de",
                                    "zwei@klammer@affen.de", "  "])
def test_kaputte_adresse_wird_abgelehnt(postausgang, kaputt):
    antwort = _entwurf(empfaenger=kaputt)
    assert "fehler" in antwort
    _kein_draft()


def test_ohne_betreff_keine_mail(postausgang):
    antwort = _entwurf(betreff="   ")
    assert "fehler" in antwort
    _kein_draft()


def test_ohne_text_keine_mail(postausgang):
    antwort = _entwurf(text=" ")
    assert "fehler" in antwort
    _kein_draft()


def test_zu_langer_text_wird_abgelehnt(postausgang):
    antwort = _entwurf(text="x" * (server.BETREIBER_MAIL_TEXT_MAX + 1))
    assert "fehler" in antwort
    _kein_draft()


def test_ohne_konfigurierten_postausgang_lesbarer_fehler(monkeypatch):
    monkeypatch.setattr(server, "BETREIBER_MAIL_LEAD_ID", "")
    antwort = _entwurf()
    assert "fehler" in antwort
    assert "BETREIBER_MAIL_LEAD_ID" in antwort["fehler"]


def test_verwaister_postausgang_lesbarer_fehler(monkeypatch):
    monkeypatch.setattr(server, "BETREIBER_MAIL_LEAD_ID",
                        "00000000-0000-0000-0000-000000000000")
    antwort = _entwurf()
    assert "fehler" in antwort


def test_adresse_eines_crm_kontakts_wird_abgewiesen(postausgang):
    """Die Hintertuer bleibt zu: Vertriebskontakte laufen ueber
    entwurf_erstellen — mit UWG-Tor, Loeschantrag-Vollstopp und
    Privat-Schutz. Wer dort geschuetzt ist, ist HIER nicht erreichbar."""
    server._q("insert into leads (name, email, source) values "
              "('Echter Kunde', 'kunde@beispiel.org', 'whatsapp') "
              "returning id")
    antwort = _entwurf(empfaenger="kunde@beispiel.org")
    assert "fehler" in antwort
    assert "entwurf_erstellen" in antwort["fehler"]
    _kein_draft()


def test_crm_pruefung_ist_gross_klein_blind(postausgang):
    server._q("insert into leads (name, email, source) values "
              "('Echter Kunde', 'Kunde@Beispiel.org', 'whatsapp') "
              "returning id")
    antwort = _entwurf(empfaenger="kunde@beispiel.org")
    assert "fehler" in antwort
    _kein_draft()
