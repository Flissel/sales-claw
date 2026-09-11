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
import medien  # noqa: E402
import recherche  # noqa: E402


def _entfaltet(text: str) -> str:
    """ICS-Zeilen sind auf 75 Oktette gefaltet (CRLF + Leerzeichen) — vor
    einem Substring-Vergleich erst entfalten, sonst kann eine lange
    ORGANIZER/ATTENDEE-Zeile mitten in der gesuchten Adresse brechen.
    Dieselbe Technik wie in kalender.ics_einladung selbst."""
    return text.replace("\r\n ", "").replace("\r\n\t", "")


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


# ---------------------------------------------------------------------------
# Fix-Runde 2 (Koordinator-Feedback, 11.09.2026)
# ---------------------------------------------------------------------------

def test_organizer_ist_der_konfigurierte_absender_attendee_der_kontakt():
    """Mangel 3: die Kernzusage der Aufgabe — ORGANIZER muss derselbe
    Absender sein, von dem die Mail tatsaechlich kommt, sonst findet eine
    Zusage nie zu ihrer Einladung zurueck. Bisher nur durch Codelesen
    gestuetzt (mail_konfiguriert setzt 'buero@vibemind.space'), nicht durch
    einen Test."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        text = _entfaltet(f.read())
    assert "ORGANIZER:mailto:buero@vibemind.space" in text
    assert ("ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
            "PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:ivan@vibemind.space"
            ) in text


def test_ohne_einwilligung_bleibt_kein_muell_liegen():
    """Mangel 2: der haeufigste Fall — ein frischer Erstkontakt mit dem
    DB-Standardwert consent_status='unknown' (genau die Zielgruppe fuer
    einen Terminvorschlag) wird vom UWG-Tor in entwurf_erstellen abgelehnt.
    Weder ein Entwurf noch die zuvor geschriebene .ics duerfen zurueckbleiben
    — und der Fehlertext muss den echten Grund nennen, nicht nur
    'Fehler beim Anlegen'."""
    lead = str(server._q(
        "insert into leads (name, email, phone, source) values "
        "(%s, %s, '+491701234567', 'whatsapp') returning id",
        ("Kalt", "kalt@vibemind.space"))[0]["id"])

    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))

    assert "fehler" in antwort
    assert "einwilligung" in antwort["fehler"].lower()

    entwuerfe = server._q("select id from drafts where lead_id = %s", (lead,))
    assert entwuerfe == []

    dateiname = f"einladung-{recherche.slug('Kalt')}-2026-10-01-1430.ics"
    assert not os.path.exists(
        os.path.join(medien.ERZEUGT_VERZEICHNIS, dateiname)), (
        "verwaiste .ics im Medienordner haengengeblieben")
    assert not os.path.exists(
        os.path.join(recherche.REPORT_VERZEICHNIS, dateiname)), (
        "verwaiste .ics in reports/ haengengeblieben")


def test_mehrere_eingeladene_stehen_alle_als_attendee():
    """Kleinere Luecke (freigestellt, billig): `eingeladene` mit mehreren,
    kommagetrennten Adressen — ersetzt die Kontaktadresse, statt sie zu
    ergaenzen (server.py: `if not gaeste: ... gaeste = [kontakt_mail]`)."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30",
        eingeladene="erste@vibemind.space, zweite@vibemind.space"))
    assert "fehler" not in antwort, antwort
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        text = _entfaltet(f.read())
    assert "mailto:erste@vibemind.space" in text
    assert "mailto:zweite@vibemind.space" in text
    assert "mailto:ivan@vibemind.space" not in text


def test_kaputte_adresse_wird_nicht_gebaut():
    """Kleinere Luecke (freigestellt, billig): der ValueError-Pfad aus
    kalender._adresse (kein '@') — die Einladung wird gar nicht erst
    angelegt, kalender.ics_einladung wird VOR jedem Dateizugriff
    aufgerufen."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", eingeladene="keine-email-adresse"))
    assert "fehler" in antwort
    assert "nicht baubar" in antwort["fehler"]


def test_nicht_beschreibbarer_medienordner_wird_gemeldet(tmp_path, monkeypatch):
    """Kleinere Luecke (freigestellt, billig): der Medienordner existiert
    nicht und kann es auch nicht werden (ein Dateiname im Pfad, wo ein
    Ordner erwartet wird) — os.makedirs wirft OSError."""
    sperre = tmp_path / "ist-eine-datei"
    sperre.write_text("x")
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(sperre / "unterordner"))
    lead = _lead()
    antwort = json.loads(server.termin_einladen(lead, "2026-10-01", "14:30"))
    assert "fehler" in antwort
    assert "abgelegt" in antwort["fehler"]


def test_fehlender_absender_wird_gemeldet(monkeypatch):
    """Kleinere Luecke (freigestellt, billig): ohne EMAIL_ABSENDER kein
    Veranstalter — die autouse-Fixture `mail_konfiguriert` wird fuer diesen
    einen Test gezielt wieder aufgehoben."""
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "")
    lead = _lead()
    antwort = json.loads(server.termin_einladen(lead, "2026-10-01", "14:30"))
    assert "fehler" in antwort
    assert "EMAIL_ABSENDER" in antwort["fehler"]
