"""Vertragstests von sales-mail gegen sales_test + einen eigenen SMTP-Stub.

DREI RIEGEL GEGEN EINEN ECHTEN VERSAND — sie muessen alle drei stehen,
weil die Suite mit `--env-file .env` laeuft und damit die ECHTEN
SMTP-Zugangsdaten in der Umgebung hat:

1. `SALES_DB_SCHEMA=sales_test` hart gesetzt (wie ueberall).
2. Die autouse-Fixture biegt `mail_dispatch.SMTP_HOST` auf 127.0.0.1 und
   prueft anschliessend, dass dort auch wirklich Loopback steht.
3. `mail_dispatch._verbindung` wird auf eine blanke Verbindung zum Stub
   umgebogen. Ohne diesen Handgriff wuerde `smtplib` TLS sprechen wollen,
   und der Stub hat kein Zertifikat — der Test wuerde scheitern, nicht
   still zum echten Server ausweichen.

`aiosmtpd` ist im Image NICHT installiert (gemessen), der Stub ist deshalb
selbstgebaut: ein Thread auf socketserver-Basis, der genau so viel SMTP
spricht, wie `smtplib` fuer EHLO/AUTH/MAIL/RCPT/DATA/QUIT braucht.
"""
import base64
import email
import json
import logging
import os
import smtplib
import socketserver
import threading
import time
from email import policy

import pytest

# HART, nicht setdefault: eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die truncate-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import dispatch  # noqa: E402
import mail_dispatch  # noqa: E402
import mailadresse  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402

# Die ECHTE Verbindungsfunktion, bevor die autouse-Fixture sie umbiegt. Nur
# die drei Tests am Dateiende, die die Verschluesselung selbst pruefen,
# benutzen sie — und die sprechen ausschliesslich mit Attrappen.
_ECHTE_VERBINDUNG = mail_dispatch._verbindung


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


# ---------------------------------------------------------------------------
# SMTP-Stub
# ---------------------------------------------------------------------------

class _Stub:
    """Konfigurierbarer Mailserver-Ersatz."""

    def __init__(self):
        self.mail_status = b"250 2.1.0 Ok"
        self.rcpt_status = b"250 2.1.5 Ok"
        self.data_status = b"250 2.0.0 Ok: queued as STUB1"
        self.auth_status = b"235 2.7.0 Authentication successful"
        self.verzoegerung = 0.0
        self.mails = []
        self.anmeldungen = []
        self.sperre = threading.Lock()

    def zuruecksetzen(self):
        self.__init__()


STUB = _Stub()
STUB_PORT = 0


class _Handler(socketserver.StreamRequestHandler):
    """Genau so viel SMTP, wie smtplib fuer einen Versand braucht."""

    def _sag(self, text: bytes):
        self.wfile.write(text + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self._sag(b"220 stub.invalid ESMTP")
        absender, empfaenger = None, []
        while True:
            zeile = self.rfile.readline()
            if not zeile:
                return
            befehl = zeile.decode("utf-8", "replace").strip()
            oben = befehl.upper()
            if oben.startswith(("EHLO", "HELO")):
                # Mehrzeilige Antwort: alle bis auf die letzte mit '-'.
                # Beworben wird NUR AUTH PLAIN — smtplib schickt dann eine
                # einzige Zeile mit der Anmeldung, statt die mehrstufigen
                # LOGIN-/CRAM-MD5-Dialoge zu beginnen.
                self._sag(b"250-stub.invalid\r\n250-AUTH PLAIN\r\n250 HELP")
            elif oben.startswith("AUTH"):
                with STUB.sperre:
                    STUB.anmeldungen.append(befehl)
                self._sag(STUB.auth_status)
            elif oben.startswith("MAIL FROM"):
                absender = befehl.split(":", 1)[1].strip()
                self._sag(STUB.mail_status)
            elif oben.startswith("RCPT TO"):
                empfaenger.append(befehl.split(":", 1)[1].strip())
                self._sag(STUB.rcpt_status)
            elif oben == "DATA":
                self._sag(b"354 End data with <CR><LF>.<CR><LF>")
                rumpf = []
                while True:
                    z = self.rfile.readline()
                    if not z or z in (b".\r\n", b".\n"):
                        break
                    rumpf.append(z)
                if STUB.verzoegerung:
                    time.sleep(STUB.verzoegerung)
                with STUB.sperre:
                    STUB.mails.append({
                        "absender": absender, "empfaenger": list(empfaenger),
                        "roh": b"".join(rumpf).decode("utf-8", "replace")})
                empfaenger = []
                self._sag(STUB.data_status)
            elif oben == "RSET":
                absender, empfaenger = None, []
                self._sag(b"250 2.0.0 Ok")
            elif oben == "NOOP":
                self._sag(b"250 2.0.0 Ok")
            elif oben == "QUIT":
                self._sag(b"221 2.0.0 Bye")
                return
            else:
                self._sag(b"502 5.5.2 Not implemented")


class _Dienst(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture(scope="module", autouse=True)
def stub_dienst():
    global STUB_PORT
    dienst = _Dienst(("127.0.0.1", 0), _Handler)
    threading.Thread(target=dienst.serve_forever, daemon=True).start()
    STUB_PORT = dienst.server_address[1]
    yield dienst
    dienst.shutdown()


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch):
    # Riegel 2: nie der echte Mailserver aus der .env.
    monkeypatch.setattr(mail_dispatch, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(mail_dispatch, "SMTP_PORT", STUB_PORT)
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "stub-user@example.org")
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "STUB-GEHEIMNIS")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "haus@example.org")
    monkeypatch.setattr(mail_dispatch, "SENDE_PAUSE_S", 0.0)
    monkeypatch.setattr(mail_dispatch, "SMTP_TIMEOUT_S", 5.0)
    assert mail_dispatch.SMTP_HOST == "127.0.0.1", (
        "sales-mail zeigt im Test nicht auf Loopback — Abbruch, bevor eine "
        "echte Mail rausgeht.")

    # Riegel 3: blanke Verbindung zum Stub statt TLS.
    def _blank():
        verbindung = smtplib.SMTP(mail_dispatch.SMTP_HOST,
                                  mail_dispatch.SMTP_PORT,
                                  timeout=mail_dispatch.SMTP_TIMEOUT_S)
        verbindung.ehlo()
        return verbindung

    monkeypatch.setattr(mail_dispatch, "_verbindung", _blank)
    STUB.zuruecksetzen()
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


class _Mitschnitt(logging.Handler):
    """Wie in test_dispatch.py: `mail_dispatch.LOG` propagiert nicht."""

    def __init__(self):
        super().__init__()
        self.saetze = []

    def emit(self, record):
        self.saetze.append(record)

    def texte(self, level=None):
        return [s.getMessage() for s in self.saetze
                if level is None or s.levelno == level]

    def __enter__(self):
        mail_dispatch.LOG.addHandler(self)
        return self

    def __exit__(self, *_):
        mail_dispatch.LOG.removeHandler(self)
        return False


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead(name="Max Testperson", email="max@example.com"):
    return server._q(
        "insert into leads (name, email, phone, source) values "
        "(%s, %s, '+491701234567', 'whatsapp') returning id",
        (name, email))[0]["id"]


def _draft(lead_id, recipient="max@example.com", kanal="email",
           status="approved", body="Guten Tag Herr Testperson,\n\nvielen Dank.",
           betreff="Ihr Termin", medien=None):
    return server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref, status, approved_by, approved_at) values "
        "(%s, %s, %s, nullif(%s,''), %s, %s, %s, 'betreiber', now()) "
        "returning id",
        (lead_id, kanal, recipient, betreff, body, medien, status))[0]["id"]


def _zeile(draft_id):
    return server._q(
        "select status, error, sent_at, channel from drafts where id = %s",
        (draft_id,))[0]


# ---------------------------------------------------------------------------
# Empfaengerpruefung (ohne DB, ohne Netz)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("roh", [
    "max@example.com",
    "max.mustermann@example.co.uk",
    "max+termin@example.com",
    "m@a.de",
    "  max@example.com  ",          # aussen gekuerzt
    "MAX@Example.COM",
])
def test_gueltige_adressen(roh):
    adresse, fehler = mailadresse.pruefe(roh)
    assert fehler is None
    assert adresse == roh.strip()


@pytest.mark.parametrize("roh", [
    "Max Testperson",               # ein Name, keine Adresse
    "max@example.com, chef@example.com",
    "max@example.com;chef@example.com",
    "max@@example.com",
    "max@example",                  # Domain ohne Punkt
    "@example.com",
    "max@",
    "max example@test.de",          # Leerzeichen
    "max@example.com\nBcc: chef@example.com",   # Kopfzeilen-Injektion
    "max@example.com\r\nBcc: chef@example.com",
    "<max@example.com>",
    "max" + "x" * 300 + "@example.com",
    "", "   ", None,
])
def test_unzustellbare_adressen(roh):
    adresse, fehler = mailadresse.pruefe(roh)
    assert adresse is None
    assert fehler == mailadresse.FEHLER_UNZUSTELLBAR


def test_anzeige_und_versand_benutzen_dieselbe_pruefung():
    """Wie bei den Nummern: `entwuerfe_offen` zeigt genau das Ziel an, das
    sales-mail dann anspricht — sonst gibt jemand etwas anderes frei."""
    assert server.mailadresse.pruefe is mailadresse.pruefe
    assert mail_dispatch.mailadresse.pruefe is mailadresse.pruefe


def test_entwuerfe_offen_zeigt_die_zieladresse():
    lead = _lead(email="max@example.com")
    draft = _draft(lead, status="pending")
    eintrag = next(e for e in json.loads(server.entwuerfe_offen())["entwuerfe"]
                   if str(e["draft_id"]) == str(draft))
    assert eintrag["kanal"] == "email"
    assert eintrag["zieladresse"] == "max@example.com"
    assert eintrag["zielnummer"] is None
    assert "hinweis" not in eintrag


def test_entwuerfe_offen_meldet_eine_unzustellbare_adresse():
    lead = _lead(email=None)
    draft = _draft(lead, recipient="Max Testperson", status="pending")
    eintrag = next(e for e in json.loads(server.entwuerfe_offen())["entwuerfe"]
                   if str(e["draft_id"]) == str(draft))
    assert eintrag["zieladresse"] is None
    assert eintrag["hinweis"] == "nicht zustellbar"


def test_linkedin_bleibt_ohne_zieladresse_und_ohne_warnung():
    lead = _lead()
    draft = _draft(lead, recipient="Max Testperson", kanal="linkedin",
                   status="pending")
    eintrag = next(e for e in json.loads(server.entwuerfe_offen())["entwuerfe"]
                   if str(e["draft_id"]) == str(draft))
    assert eintrag["zielnummer"] is None
    assert "zieladresse" not in eintrag
    assert "hinweis" not in eintrag


# ---------------------------------------------------------------------------
# Claim — die Kanaltrennung
# ---------------------------------------------------------------------------

def test_claim_setzt_die_marke_und_ist_nur_einmal_moeglich():
    draft = _draft(_lead())
    geclaimt = mail_dispatch.claim(draft)
    assert geclaimt is not None
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)
    assert mail_dispatch.claim(draft) is None
    assert STUB.mails == []


def test_claim_benutzt_dieselbe_marke_wie_der_whatsapp_dispatcher():
    """Die Marke ist die Schutzkante gegen Doppelversand:
    `entwurf_erneut_freigeben` erkennt einen haengenden Versand an ihrem
    Praefix. Zwei verschiedene Marken haetten sie fuer E-Mail still
    ausgehebelt."""
    assert mail_dispatch._claim_marke is dispatch._claim_marke
    draft = _draft(_lead())
    mail_dispatch.claim(draft)
    verweigert = json.loads(server.entwurf_erneut_freigeben(str(draft)))
    assert "fehler" in verweigert
    assert "Zustellung" in verweigert["fehler"]


def test_claim_fasst_whatsapp_und_linkedin_nicht_an():
    lead = _lead()
    for kanal, empfaenger in (("whatsapp", "+491701234567"),
                              ("linkedin", "Max Testperson")):
        draft = _draft(lead, recipient=empfaenger, kanal=kanal)
        assert mail_dispatch.claim(draft) is None
        assert _zeile(draft)["status"] == "approved"


def test_whatsapp_dispatcher_fasst_email_nicht_an():
    """Gegenprobe: die beiden Dienste duerfen sich nicht ins Gehege kommen."""
    draft = _draft(_lead())
    assert dispatch.claim(draft) is None
    assert _zeile(draft)["status"] == "approved"


# ---------------------------------------------------------------------------
# Versand: Erfolg
# ---------------------------------------------------------------------------

def test_erfolg_setzt_sent_loggt_und_schickt_genau_eine_mail():
    lead = _lead()
    draft = _draft(lead, betreff="Ihr Termin am Mittwoch")

    mail_dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "sent"
    assert zeile["sent_at"] is not None
    assert zeile["error"] is None

    assert len(STUB.mails) == 1
    mail = STUB.mails[0]
    assert mail["empfaenger"] == ["<max@example.com>"]
    assert mail["absender"] == "<haus@example.org>"
    assert "Subject: Ihr Termin am Mittwoch" in mail["roh"]
    assert "To: max@example.com" in mail["roh"]
    assert "From: haus@example.org" in mail["roh"]
    assert "vielen Dank." in mail["roh"]

    akt = server._q("select payload from activities where lead_id = %s "
                    "and type = 'versand'", (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["draft_id"] == str(draft)
    assert akt[0]["payload"]["kanal"] == "email"
    assert akt[0]["payload"]["weg"] == "mail-dispatcher"
    assert akt[0]["payload"]["empfaenger"] == "max@example.com"


def test_nur_approved_email_wird_verarbeitet():
    lead = _lead()
    pending = _draft(lead, status="pending")
    rejected = _draft(lead, status="rejected")
    gesendet = _draft(lead, status="sent")
    whatsapp = _draft(lead, recipient="+491701234567", kanal="whatsapp")

    mail_dispatch.eine_runde()

    assert STUB.mails == []
    assert _zeile(pending)["status"] == "pending"
    assert _zeile(rejected)["status"] == "rejected"
    assert _zeile(gesendet)["status"] == "sent"
    assert _zeile(whatsapp)["status"] == "approved"


def test_umlaute_ueberleben_den_versand():
    _draft(_lead(), body="Grüße aus Regensburg — schöne Woche!",
           betreff="Rückmeldung zur Vorsorge")
    mail_dispatch.eine_runde()
    # Kodiert wird nach den Regeln (quoted-printable/base64), nicht roh —
    # entscheidend ist, dass es sich beim Empfaenger wieder auspacken laesst.
    nachricht = email.message_from_string(STUB.mails[0]["roh"],
                                          policy=policy.default)
    assert "Grüße aus Regensburg — schöne Woche!" in nachricht.get_content()
    assert nachricht["Subject"] == "Rückmeldung zur Vorsorge"
    assert nachricht.get_content_type() == "text/plain"
    assert nachricht.get_content_charset() == "utf-8"


def test_fehlender_betreff_faellt_auf_die_vorgabe_zurueck():
    _draft(_lead(), betreff="")
    mail_dispatch.eine_runde()
    assert f"Subject: {mail_dispatch.BETREFF_VORGABE}" in STUB.mails[0]["roh"]


def test_stapel_ist_auf_fuenf_begrenzt():
    lead = _lead()
    for _ in range(7):
        _draft(lead)

    mail_dispatch.eine_runde()

    assert len(STUB.mails) == 5
    offen = server._q("select count(*) as n from drafts "
                      "where status = 'approved'")
    assert offen[0]["n"] == 2


def test_anmeldung_findet_statt_und_das_passwort_reist_nicht_im_klartext():
    _draft(_lead())
    mail_dispatch.eine_runde()
    assert len(STUB.anmeldungen) == 1
    befehl = STUB.anmeldungen[0]
    assert befehl.upper().startswith("AUTH PLAIN")
    # Base64 ist keine Verschluesselung — der Punkt ist, dass smtplib die
    # Zugangsdaten nicht als Klartext-Argument in die Zeile schreibt und
    # dass sie im Betrieb ueber TLS reisen (siehe test_verbindung_*).
    entpackt = base64.b64decode(befehl.split(" ", 2)[2]).decode("utf-8")
    assert entpackt.split("\x00")[2] == "STUB-GEHEIMNIS"


# ---------------------------------------------------------------------------
# Versand: Fehlerpfade
# ---------------------------------------------------------------------------

def test_name_als_empfaenger_wird_nie_gesendet():
    draft = _draft(_lead(), recipient="Max Testperson")

    mail_dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"] == mailadresse.FEHLER_UNZUSTELLBAR
    assert STUB.mails == []
    assert server._q("select count(*) as n from activities "
                     "where type = 'versand'")[0]["n"] == 0


def test_kopfzeilen_injektion_im_empfaenger_wird_abgewiesen():
    """Der schlimmste Fall dieses Kanals: ein zweiter, ungenannter
    Empfaenger, den niemand freigegeben hat."""
    draft = _draft(_lead(), recipient="max@example.com\nBcc: chef@example.com")

    mail_dispatch.eine_runde()

    assert _zeile(draft)["status"] == "failed"
    assert STUB.mails == []


def test_zurueckgewiesener_empfaenger_wird_failed():
    draft = _draft(_lead())
    STUB.rcpt_status = b"550 5.1.1 User unknown"

    mail_dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "550" in zeile["error"]
    assert zeile["sent_at"] is None
    assert not zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)


def test_abgelehnte_anmeldung_wird_failed_mit_hinweis_auf_die_env():
    draft = _draft(_lead())
    STUB.auth_status = b"535 5.7.8 Authentication credentials invalid"

    mail_dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "535" in zeile["error"]
    assert "App-Passwort" in zeile["error"]


def test_passwort_landet_nie_im_fehlertext():
    """SMTP-Antworten spiegeln die Anfrage manchmal zurueck."""
    draft = _draft(_lead())
    STUB.auth_status = b"535 5.7.8 bad password STUB-GEHEIMNIS"

    mail_dispatch.eine_runde()

    assert "STUB-GEHEIMNIS" not in _zeile(draft)["error"]
    assert "***" in _zeile(draft)["error"]


def test_mailserver_nicht_erreichbar_wird_failed(monkeypatch):
    draft = _draft(_lead())

    def _tot():
        return smtplib.SMTP("127.0.0.1", 1, timeout=2.0)   # niemand hoert zu

    monkeypatch.setattr(mail_dispatch, "_verbindung", _tot)
    mail_dispatch.eine_runde()          # darf nicht werfen

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert zeile["error"]
    assert not zeile["error"].startswith(dispatch.CLAIM_PRAEFIX)


def test_kaputte_verbindung_toetet_die_schleife_nicht(monkeypatch):
    def _tot():
        raise ValueError("kaputte Konfiguration")

    monkeypatch.setattr(mail_dispatch, "_verbindung", _tot)
    lead = _lead()
    for _ in range(2):
        _draft(lead)

    assert mail_dispatch.eine_runde() == {"fehler": 2}


def test_fehlertext_wird_auf_300_zeichen_gekuerzt():
    draft = _draft(_lead())
    STUB.rcpt_status = b"550 5.1.1 " + b"x" * 2000

    mail_dispatch.eine_runde()

    assert 0 < len(_zeile(draft)["error"]) <= 300


def test_kein_retry_in_der_naechsten_runde():
    draft = _draft(_lead())
    STUB.rcpt_status = b"550 5.1.1 User unknown"

    mail_dispatch.eine_runde()
    assert _zeile(draft)["status"] == "failed"

    STUB.rcpt_status = b"250 2.1.5 Ok"
    mail_dispatch.eine_runde()
    assert STUB.mails == []      # ein Mensch muss neu freigeben, nicht wir


# ---------------------------------------------------------------------------
# Anhaenge — der Punkt, an dem diese Fassung ausdruecklich NICHT sendet
# ---------------------------------------------------------------------------

def test_entwurf_mit_anhang_geht_nicht_ohne_den_anhang_raus():
    """Freigegeben wurde eine Nachricht MIT Unterlage. Sie ohne zu senden
    waere etwas anderes als das Freigegebene — dieselbe Regel wie beim
    WhatsApp-Weg, dort fuer eine geloeschte Datei."""
    draft = _draft(_lead(), medien="checkliste.pdf")

    mail_dispatch.eine_runde()

    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "checkliste.pdf" in zeile["error"]
    assert "NICHTS raus" in zeile["error"]
    assert STUB.mails == []
    assert zeile["sent_at"] is None


def test_entwurf_erstellen_warnt_frueh_beim_anhang_an_einer_email(
        tmp_path, monkeypatch):
    """Frueh sagen statt spaet scheitern: der Betreiber soll es beim
    Erstellen erfahren, nicht erst nach seiner Freigabe."""
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    (tmp_path / "checkliste.pdf").write_bytes(b"%PDF-1.4 Testinhalt")
    lead = str(_lead())

    mit = json.loads(server.entwurf_erstellen(
        lead, "email", "Text", medien_datei="checkliste.pdf"))
    assert "ACHTUNG" in mit["hinweis"] and "checkliste.pdf" in mit["hinweis"]

    ohne = json.loads(server.entwurf_erstellen(lead, "email", "Text"))
    assert "ACHTUNG" not in ohne["hinweis"]

    # Bei WhatsApp bleibt alles, wie es war — dort geht der Anhang mit.
    whatsapp = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Text", medien_datei="checkliste.pdf"))
    assert "ACHTUNG" not in whatsapp["hinweis"]


# ---------------------------------------------------------------------------
# Verbindungsart, Konfiguration, Start
# ---------------------------------------------------------------------------

class _FakeSMTP:
    letzte = None

    def __init__(self, host, port, timeout=None, context=None):
        self.args = {"host": host, "port": port, "timeout": timeout,
                     "context": context}
        self.schritte = []
        type(self).letzte = self

    def ehlo(self):
        self.schritte.append("ehlo")

    def starttls(self, context=None):
        self.schritte.append("starttls")
        self.args["tls_kontext"] = context


class _FakeSMTPSSL(_FakeSMTP):
    letzte = None


def test_verbindung_bei_465_ist_implizites_tls(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PORT", 465)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    verbindung = _ECHTE_VERBINDUNG()

    assert isinstance(verbindung, _FakeSMTPSSL)
    assert verbindung.args["port"] == 465
    assert verbindung.args["context"] is not None       # Zertifikatspruefung
    assert verbindung.schritte == []                    # kein STARTTLS noetig


def test_verbindung_bei_587_geht_ueber_starttls(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PORT", 587)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    verbindung = _ECHTE_VERBINDUNG()

    assert isinstance(verbindung, _FakeSMTP)
    assert not isinstance(verbindung, _FakeSMTPSSL)
    assert verbindung.schritte == ["ehlo", "starttls", "ehlo"]
    assert verbindung.args["tls_kontext"] is not None


@pytest.mark.parametrize("port", [25, 587, 2525, 1025])
def test_jeder_andere_port_geht_ebenfalls_verschluesselt(monkeypatch, port):
    """Regressionsprobe: es gibt keinen blanken Ausgang. Wer SMTP_PORT auf
    irgendetwas anderes stellt, bekommt STARTTLS — nicht Klartext."""
    monkeypatch.setattr(mail_dispatch, "SMTP_PORT", port)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    verbindung = _ECHTE_VERBINDUNG()

    assert "starttls" in verbindung.schritte
    assert verbindung.args["tls_kontext"] is not None


@pytest.mark.parametrize("fehlt", ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORT",
                                   "EMAIL_ABSENDER"])
def test_ohne_konfiguration_endet_der_dienst_sauber(monkeypatch, fehlt):
    monkeypatch.setattr(mail_dispatch, fehlt, "")
    monkeypatch.setattr(mail_dispatch, "MAIL_ONCE", True)
    draft = _draft(_lead())

    with _Mitschnitt() as mitschnitt:
        # Exit 0: ein nicht eingerichteter Kanal ist ein gueltiger Zustand
        # dieses Prototyps, kein Ausfall.
        assert mail_dispatch.main() == 0

    assert _zeile(draft)["status"] == "approved"     # nichts angefasst
    assert STUB.mails == []
    gemeldet = " ".join(mitschnitt.texte())
    assert fehlt in gemeldet
    assert "nicht eingerichtet" in gemeldet


def test_unbrauchbarer_absender_versendet_nichts(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "kein-absender")
    monkeypatch.setattr(mail_dispatch, "MAIL_ONCE", True)
    draft = _draft(_lead())

    assert mail_dispatch.main() == 0
    assert _zeile(draft)["status"] == "approved"
    assert STUB.mails == []


def test_mail_once_laeuft_eine_runde_und_endet(monkeypatch):
    draft = _draft(_lead())
    monkeypatch.setattr(mail_dispatch, "MAIL_ONCE", True)

    assert mail_dispatch.main() == 0
    assert _zeile(draft)["status"] == "sent"


def test_logging_geht_auf_stdout_und_auch_der_geliehene_logger():
    """Die importierten Buchungshelfer loggen nach `dispatch.LOG` — ihre
    `critical`-Saetze duerfen im Log dieses Dienstes nicht fehlen."""
    import sys as _sys
    mail_dispatch.LOG.handlers.clear()
    dispatch.LOG.handlers.clear()
    mail_dispatch._logging_einrichten()
    for logger in (mail_dispatch.LOG, dispatch.LOG):
        assert logger.handlers
        assert logger.handlers[0].stream is _sys.stdout
        assert logger.propagate is False


def test_betreff_mit_zeilenumbruch_wird_entschaerft():
    """Der Betreff kommt aus einem Sprachmodell. Ein Umbruch darin waere
    eine eigene Kopfzeile in der fertigen Mail."""
    boese = "Angebot\r\nBcc: chef@example.com"
    assert mail_dispatch._betreff(boese) == "Angebot Bcc: chef@example.com"
    _draft(_lead(), betreff=boese)

    mail_dispatch.eine_runde()

    roh = STUB.mails[0]["roh"]
    assert "\nBcc:" not in roh
    assert STUB.mails[0]["empfaenger"] == ["<max@example.com>"]


def test_leerer_betreff_nach_der_saeuberung_faellt_auf_die_vorgabe():
    assert mail_dispatch._betreff("\r\n\t ") == mail_dispatch.BETREFF_VORGABE
    assert mail_dispatch._betreff(None) == mail_dispatch.BETREFF_VORGABE


def test_zwischen_zwei_mails_liegt_eine_pause(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SENDE_PAUSE_S", 0.25)
    lead = _lead()
    for _ in range(3):
        _draft(lead)

    start = time.monotonic()
    mail_dispatch.eine_runde()
    gedauert = time.monotonic() - start

    assert len(STUB.mails) == 3
    assert gedauert >= 0.5      # zwei Pausen zwischen drei Sendungen


def test_keine_pause_hinter_einem_unzustellbaren_entwurf(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SENDE_PAUSE_S", 5.0)
    lead = _lead()
    for _ in range(3):
        _draft(lead, recipient="Max Testperson")

    start = time.monotonic()
    mail_dispatch.eine_runde()
    gedauert = time.monotonic() - start

    assert STUB.mails == []
    assert gedauert < 2.0


# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Stufe-9-Review (Befunde H1, H2)
# ---------------------------------------------------------------------------

def test_kaputte_nachrichtenkonstruktion_toetet_den_dienst_nicht(monkeypatch):
    """H1: nachricht_bauen liegt ausserhalb von sendens eigenem Fangnetz —
    ein unerwarteter Konstruktionsfehler muss zur regulaeren Fehlerbuchung
    werden, nicht zum Prozesstod (restart 'no' liesse den Dienst sonst
    unten, den Entwurf mit Claim-Marke liegen)."""
    draft = _draft(_lead())

    def _kaputt(*_a, **_kw):
        raise ValueError("Header values may not contain linefeed characters")

    monkeypatch.setattr(mail_dispatch, "nachricht_bauen", _kaputt)
    ergebnis = mail_dispatch.eine_runde()
    assert ergebnis.get("fehler", 0) == 1
    zeile = _zeile(draft)
    assert zeile["status"] == "failed"
    assert "nicht konstruierbar" in zeile["error"]
    assert "ValueError" in zeile["error"]
    assert STUB.mails == []          # nichts ging raus


def test_auch_die_base64_form_des_passworts_wird_gefiltert():
    """H2: auf der Leitung reist das Passwort base64-kodiert (AUTH LOGIN:
    allein; AUTH PLAIN: als NUL-User-NUL-Passwort-Block) — ein spiegelnder
    Gateway gaebe genau diese Darstellung zurueck, nicht den Klartext."""
    import base64 as b64
    allein = b64.b64encode(b"STUB-GEHEIMNIS").decode()
    block = b64.b64encode(
        b"\x00stub-user@example.org\x00STUB-GEHEIMNIS").decode()
    text = f"535 mirror {allein} und {block} ende"
    gefiltert = mail_dispatch._ohne_geheimnis(text)
    assert allein not in gefiltert
    assert block not in gefiltert
    assert gefiltert.count("***") >= 2
