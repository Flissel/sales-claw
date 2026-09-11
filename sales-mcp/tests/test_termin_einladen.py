"""Vertragstests fuer `termin_einladen` — Einladung statt stillem Eintrag."""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
# `import server` oben laedt das Modul vollstaendig (inklusive Pool, MCP-
# Registrierung); erst DANACH ist `import mail_dispatch` hier gefahrlos —
# mail_dispatch.py importiert seinerseits `dispatch`, das mit
# `from server import _jetzt` auf DIESES Modul zurueckgreift. Kaeme dieser
# Import vor `import server`, waere es ein Ringschluss waehrend server.py
# noch selbst laedt (siehe Kommentar an der gleichnamigen Stelle in
# `server.termin_einladen`).
import mail_dispatch  # noqa: E402


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads cascade")
    yield


@pytest.fixture(autouse=True)
def mail_konfiguriert(monkeypatch):
    """`termin_einladen` braucht einen Veranstalter — ohne EMAIL_ABSENDER
    kann keine gueltige Einladung entstehen (RFC 5546 verlangt ORGANIZER).
    Der CI-Container laeuft ohne SMTP-Konfiguration (siehe docker-Aufruf in
    global-constraints.md: nur SALES_DB_SCHEMA/SALES_DB_URL sind gesetzt),
    deshalb hier explizit gesetzt — gleiches Muster wie `kalender_konfiguriert`
    in test_termin.py fuer CALDAV_URL/_USER/_PASSWORT."""
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "buero@vibemind.space")


def _lead(name="Ivan", email="ivan@vibemind.space"):
    # consent_status='existing_customer': `termin_einladen` legt den Entwurf
    # ueber `entwurf_erstellen` an, und der durchlaeuft dasselbe UWG-Tor
    # (F5) wie jeder andere E-Mail-Entwurf — ein Erstkontakt ganz ohne
    # dokumentierte Grundlage wird dort abgelehnt, unabhaengig vom Zweck.
    # Gleiches Muster wie `_lead()` in test_mail_dispatch.py: das Tor ist
    # hier nicht das Thema, ein bereits bekannter Kontakt schon.
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values (%s, %s, '+491701234567', 'whatsapp', 'existing_customer') "
        "returning id",
        (name, email))[0]["id"])


def test_einladung_wird_entwurf_und_geht_nicht_raus():
    """Der Kern: es entsteht ein Entwurf zur Freigabe, kein Versand."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort
    entwuerfe = server._q(
        "select status, channel from drafts where lead_id = %s", (lead,))
    assert len(entwuerfe) == 1, entwuerfe
    assert entwuerfe[0]["status"] == "pending"
    assert entwuerfe[0]["channel"] == "email"


def test_einladung_traegt_die_kalenderdatei():
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    assert antwort["datei"].endswith(".ics"), antwort
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        text = f.read()
    assert "METHOD:REQUEST" in text
    assert "ATTENDEE" in text and "ivan@vibemind.space" in text


def test_ohne_adresse_keine_einladung():
    """Ein Kontakt ohne Mailadresse kann nicht eingeladen werden — und das
    muss gesagt werden, nicht still scheitern."""
    lead = _lead(name="Ohne Mail", email=None)
    antwort = json.loads(server.termin_einladen(lead, "2026-10-01", "14:30"))
    assert "fehler" in antwort
    assert "adresse" in antwort["fehler"].lower()


def test_vergangenes_datum_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.termin_einladen(lead, "2020-01-01", "14:30"))
    assert "fehler" in antwort
