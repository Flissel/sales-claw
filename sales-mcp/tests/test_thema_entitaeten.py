"""HTML-Entitaeten im Terminthema und im Ort — aufgeloest, aber eng begrenzt.

WARUM ES DAS GIBT (gemessen 12.09.2026, erster echter Durchgang)
-----------------------------------------------------------------
Der Betreiber bekam eine Einladung im Gmail-Postfach zu sehen, deren
Betreffzeile woertlich lautete:

    Terminvorschlag: Angebot &amp; Foerderung fuer Groesseres

Der escapte Wert kommt NICHT aus dem Code — im ganzen sales-mcp-Baum
escapet ausserhalb von `ui._e()` keine Stelle beim Speichern (bei Stufe 1
nachgeprueft). Er kommt als Werkzeug-Argument herein, also vom aufrufenden
Sprachmodell, das sein "&" von sich aus escapet. Das trifft jeden Termin
mit einem "&" im Thema und landet in SUMMARY, Betreff und Kalender des
Kunden.

WARUM NICHT `html.unescape`
----------------------------
Weil es deutschen Text zerstoert. HTML5 loest `&not` AUCH OHNE Semikolon
auf — gemessen im Container dieses Dienstes:

    html.unescape("Beratung &notwendig fuer Sie")
    -> 'Beratung ¬wendig fuer Sie'

Ein Terminthema "Beratung &notwendig" wuerde damit stillschweigend
verstuemmelt. Deshalb eine feste Liste von fuenf Entitaeten, jede nur MIT
Semikolon. Der Test unten nagelt genau das fest.

WARUM NUR THEMA UND ORT
------------------------
Das Freigabe-Gate und der Nachrichtentext bleiben unangetastet: dort steht
im Zweifel woertlicher Kundentext, und ihn stillschweigend umzuschreiben
waere schlimmer als eine haessliche Entitaet. Thema und Ort dagegen setzt
der Betreiber oder der Bot, nie der Kunde — dort nennt niemand einen
Termin absichtlich "&amp;".
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
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads cascade")
    yield


@pytest.fixture(autouse=True)
def mail_konfiguriert(monkeypatch):
    """`termin_einladen` braucht einen Veranstalter (RFC 5546: ORGANIZER);
    der CI-Container laeuft ohne SMTP-Konfiguration."""
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER",
                        "felix@vibemind.space")
    yield


def _lead(name="Ivan", email="ivan@vibemind.space"):
    # existing_customer: `termin_einladen` laeuft ueber `entwurf_erstellen`
    # und damit durch das UWG-Tor. Das Tor ist hier nicht das Thema.
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values (%s, %s, '+491701234567', 'whatsapp', 'existing_customer') "
        "returning id",
        (name, email))[0]["id"])


def _ics(antwort):
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        # Entfalten: ICS bricht auf 75 Oktette, ein langer SUMMARY kann
        # mitten im gesuchten Wort umbrechen.
        return f.read().replace("\r\n ", "").replace("\r\n\t", "")


# --- Der Kern ---------------------------------------------------------------

def test_escaptes_und_im_thema_wird_aufgeloest():
    """Das gemeldete Symptom: "&amp;" statt "&" in SUMMARY und Betreff."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Angebot &amp; Förderung"))
    text = _ics(antwort)
    assert "Angebot & Förderung" in text, text
    assert "&amp;" not in text, text


def test_betreff_der_mail_traegt_kein_amp():
    """Die Betreffzeile ist die Stelle, an der der Betreiber es gesehen hat."""
    lead = _lead()
    server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Angebot &amp; Förderung")
    betreff = server._q(
        "select subject from drafts where lead_id = %s", (lead,))[0]["subject"]
    assert betreff == "Terminvorschlag: Angebot & Förderung", betreff


def test_doppelt_escaptes_und_wird_ganz_aufgeloest():
    """Bestandsdaten tragen "&amp;amp;" — eine Runde Aufloesen genuegt dort
    nicht. Die Schleife laeuft, bis sich nichts mehr aendert."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Doppelt &amp;amp; kaputt"))
    text = _ics(antwort)
    assert "Doppelt & kaputt" in text, text


def test_auch_die_uebrigen_vier_entitaeten():
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30",
        thema="&lt;Beratung&gt; &quot;kurz&quot; &#x27;A&#x27;"))
    text = _ics(antwort)
    assert "<Beratung> \"kurz\" 'A'" in text, text


def test_link_im_ort_bleibt_heil():
    """Ein Videoraum-Link mit Abfrageteil traegt "&" — escapt waere er
    kaputt, und ein kaputter Link ist schlimmer als ein haesslicher Titel."""
    lead = _lead()
    raum = "https://teams.microsoft.com/l/meetup?a=1&amp;b=2"
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch", ort=raum))
    text = _ics(antwort)
    assert "https://teams.microsoft.com/l/meetup?a=1&b=2" in text, text
    rumpf = server._q(
        "select body from drafts where lead_id = %s", (lead,))[0]["body"]
    assert "a=1&b=2" in rumpf, rumpf


# --- Die Gegenprobe, auf die es ankommt -------------------------------------

def test_kaufmaennisches_und_vor_einem_wort_bleibt_stehen():
    """DIE Falle: `html.unescape` macht aus "&notwendig" ein "¬wendig",
    weil HTML5 `&not` auch ohne Semikolon aufloest. Nur Entitaeten MIT
    Semikolon duerfen angefasst werden — dieser Test faellt um, sobald
    jemand auf `html.unescape` umstellt."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Beratung &notwendig für Sie"))
    text = _ics(antwort)
    assert "Beratung &notwendig für Sie" in text, text
    assert "¬" not in text, text


def test_echtes_und_bleibt_unveraendert():
    """Ein gewoehnliches "&" wird nicht angefasst — weder verdoppelt noch
    entfernt."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Meier & Söhne"))
    text = _ics(antwort)
    assert "Meier & Söhne" in text, text


# --- Dieselbe Regel im zweiten Weg ------------------------------------------

def test_termin_bestaetigen_loest_ebenfalls_auf():
    """`termin_bestaetigen` baut dieselbe Kalenderdatei und landet ueber die
    Bestaetigung ebenso beim Kunden. Zwei Wege, eine Regel — sonst driften
    sie auseinander."""
    lead = _lead()
    antwort = json.loads(server.termin_bestaetigen(
        lead, "2026-10-01", "14:30", thema="Angebot &amp; Förderung"))
    text = _ics(antwort)
    assert "Angebot & Förderung" in text, text
    assert "&amp;" not in text, text
