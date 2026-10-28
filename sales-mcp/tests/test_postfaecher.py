"""Mehrere Postfaecher (28.10.2026): neben dem Postfach des Ladens auch GMX
und Gmail des Betreibers.

Vertraege:
1. Mails aus einem Zusatzpostfach tragen die uid "<kennung>:<nummer>" —
   Index, Aufraeumen und Antworten wissen damit, wohin sie gehoeren. Das
   Hauptpostfach behaelt die nackte Nummer (alte Eintraege bleiben gueltig).
2. Ein kaputtes Postfach kostet nie die anderen.
3. Die Antwort auf eine GMX-Mail geht ueber GMX hinaus, mit der GMX-Adresse
   als Absender. Ist das Postfach nicht (mehr) eingerichtet, geht NICHTS raus.
4. Kein Passwort eines Zusatzpostfachs landet je in einem Fehlertext.
"""
import base64
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mail_dispatch  # noqa: E402
import postfach  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

HOST_OK = {"host": "127.0.0.1:8791"}
GMX_ADRESSE = "felix.test@gmx.de"
GMX_GEHEIM = "GMX-GEHEIM-123"


def _mail(von, betreff, text, datum, mid):
    return (f"From: {von}\r\nTo: ich@beispiel.org\r\nSubject: {betreff}\r\n"
            f"Date: {datum}\r\nMessage-ID: <{mid}>\r\n"
            f'Content-Type: text/plain; charset="utf-8"\r\n\r\n{text}').encode("utf-8")


class Kasten:
    """IMAP-Ersatz mit Ordnern — merkt sich jeden schreibenden Befehl."""

    def __init__(self, mails, ordner=()):
        self.mails = dict(mails)
        self.ordner = list(ordner) or [(r"\HasNoChildren", "INBOX")]
        self.selects, self.kopien, self.flags, self.angelegt = [], [], [], []
        self.expunged = False
        self.abgemeldet = False

    def select(self, ordner, readonly=False):
        self.selects.append((ordner, readonly))
        return "OK", [str(len(self.mails)).encode()]

    def uid(self, befehl, *args):
        if befehl == "search":
            return "OK", [b" ".join(sorted(self.mails))]
        if befehl == "fetch":
            if args[0] not in self.mails:
                return "NO", [None]
            return "OK", [(args[0] + b" (RFC822 ...)", self.mails[args[0]])]
        if befehl == "copy":
            self.kopien.append((args[0], args[1]))
            return "OK", [b""]
        if befehl == "store":
            self.flags.append((args[0], args[2]))
            return "OK", [b""]
        raise AssertionError(befehl)

    def list(self):
        return "OK", [f'({f}) "/" "{n}"'.encode() for f, n in self.ordner]

    def create(self, name):
        self.angelegt.append(name)
        return "OK", [b""]

    def expunge(self):
        self.expunged = True
        return "OK", [b""]

    def append(self, ordner, flags, zeit, inhalt):
        self.abgelegt = (ordner, inhalt)
        return "OK", [b""]

    def logout(self):
        self.abgemeldet = True
        return "BYE", []


@pytest.fixture
def haupt(monkeypatch):
    monkeypatch.setattr(postfach, "IMAP_HOST", "imap.test.invalid")
    monkeypatch.setattr(postfach, "IMAP_USER", "laden@test.invalid")
    kasten = Kasten({b"7": _mail("Kundin <k@beispiel.org>", "Anfrage Laden", "Hallo Laden.",
                                 "Tue, 27 Oct 2026 09:00:00 +0100", "laden-7@x")})
    monkeypatch.setattr(postfach, "_verbinden", lambda: kasten)
    return kasten


@pytest.fixture
def gmx(monkeypatch):
    monkeypatch.setenv("POSTFACH_GMX_ADRESSE", GMX_ADRESSE)
    monkeypatch.setenv("POSTFACH_GMX_PASSWORT", GMX_GEHEIM + "\r")  # CRLF aus der .env
    kasten = Kasten({b"2": _mail("Freund <f@beispiel.org>", "Privat über GMX", "Hallo Felix.",
                                 "Wed, 28 Oct 2026 08:00:00 +0100", "gmx-2@x")},
                    ordner=[(r"\HasNoChildren", "INBOX"), (r"\HasNoChildren \Junk", "Spamverdacht"),
                            (r"\HasNoChildren \Sent", "Gesendet")])
    geoeffnet = []

    def oeffnen(konto):
        geoeffnet.append(konto)
        return kasten
    monkeypatch.setattr(postfach, "_imap_oeffnen", oeffnen)
    kasten.geoeffnet = geoeffnet
    return kasten


@pytest.fixture
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, sales_test.leads, "
                     "sales_test.postfach_mails cascade")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.postfach_mails")


# --- Kennungen ---------------------------------------------------------------

def test_zerlegen():
    assert postfach.zerlegen("12") == ("haupt", "12")
    assert postfach.zerlegen("gmx:12") == ("gmx", "12")
    assert postfach.zerlegen("gmail:3") == ("gmail", "3")
    with pytest.raises(ValueError):
        postfach.zerlegen("fremd:1")


def test_konto_nur_mit_adresse_und_passwort(monkeypatch):
    assert postfach.konto("gmx") is None
    monkeypatch.setenv("POSTFACH_GMX_ADRESSE", GMX_ADRESSE)
    assert postfach.konto("gmx") is None
    monkeypatch.setenv("POSTFACH_GMX_PASSWORT", GMX_GEHEIM + "\r\n")
    k = postfach.konto("gmx")
    assert (k.adresse, k.passwort) == (GMX_ADRESSE, GMX_GEHEIM)


def test_eingerichtet_je_uid(haupt, gmx):
    assert postfach.eingerichtet() and postfach.eingerichtet("7") and postfach.eingerichtet("gmx:2")
    assert not postfach.eingerichtet("gmail:1")
    assert not postfach.eingerichtet("fremd:1")


# --- Lesen -------------------------------------------------------------------

def test_postfach_lesen_mischt_alle_postfaecher_neueste_zuerst(haupt, gmx, leer):
    antwort = json.loads(server.postfach_lesen(10))
    assert [m["uid"] for m in antwort["mails"]] == ["gmx:2", "7"]
    assert [m["postfach"] for m in antwort["mails"]] == ["gmx", "haupt"]
    assert gmx.geoeffnet[0].adresse == GMX_ADRESSE
    assert all(readonly for _, readonly in gmx.selects)
    # Der Index kennt die Herkunft ueber die uid.
    zeilen = server._q("select uid from postfach_mails order by uid")
    assert [z["uid"] for z in zeilen] == ["7", "gmx:2"]


def test_ein_kaputtes_postfach_kostet_die_anderen_nicht(haupt, gmx, leer, monkeypatch):
    def kaputt(konto):
        raise OSError(f"login failed {GMX_GEHEIM}")
    monkeypatch.setattr(postfach, "_imap_oeffnen", kaputt)
    antwort = json.loads(server.postfach_lesen(10))
    assert [m["uid"] for m in antwort["mails"]] == ["7"]
    assert antwort["nicht_erreichbar"] == {"gmx": "OSError"}
    assert GMX_GEHEIM not in json.dumps(antwort)


def test_nur_ein_postfach_lesen(haupt, gmx, leer):
    antwort = json.loads(server.postfach_lesen(10, postfach="gmx"))
    assert [m["uid"] for m in antwort["mails"]] == ["gmx:2"]


def test_volltext_aus_gmx(haupt, gmx):
    mail = json.loads(server.postfach_mail_lesen("gmx:2"))
    assert mail["betreff"] == "Privat über GMX" and mail["uid"] == "gmx:2"
    assert mail["postfach"] == "gmx"
    assert gmx.selects == [("INBOX", True)]


def test_nicht_eingerichtetes_postfach_ist_eine_meldung(haupt):
    antwort = json.loads(server.postfach_mail_lesen("gmail:4"))
    assert "nicht eingerichtet" in antwort["fehler"]


# --- Aufraeumen --------------------------------------------------------------

def test_spam_aus_gmx_wandert_in_den_gmx_spamordner(haupt, gmx, leer):
    antwort = json.loads(server.mail_einstufen("gmx:2", "spam", "Phishing"))
    assert antwort["ordner"] == "Spamverdacht"
    assert gmx.kopien == [(b"2", '"Spamverdacht"')]
    assert gmx.flags == [(b"2", "(\\Deleted)")] and gmx.expunged
    assert haupt.kopien == []


def test_ordnernamen_mit_leerzeichen_und_klammern():
    kasten = Kasten({}, ordner=[(r"\HasNoChildren \Junk", "[Gmail]/Spam"),
                                (r"\HasNoChildren", "Alle Nachrichten")])
    assert postfach._spam_ordner(kasten) == "[Gmail]/Spam"
    assert ("", "Alle Nachrichten") in [("", n) for _, n in postfach._ordner_liste(kasten)]


# --- Antworten ---------------------------------------------------------------

def test_antwort_auf_gmx_mail_merkt_sich_das_postfach(haupt, gmx, leer):
    a = json.loads(server.mail_beantworten("gmx:2", "Danke, melde mich."))
    assert "fehler" not in a, a
    d = server._q("select postfach, antwort_auf, recipient from drafts where id = %s", (a["draft_id"],))[0]
    assert (d["postfach"], d["antwort_auf"], d["recipient"]) == ("gmx", "gmx-2@x", "f@beispiel.org")
    assert a["von"] == GMX_ADRESSE


def test_antwort_aus_dem_hauptpostfach_bleibt_ohne_postfach(haupt, leer):
    a = json.loads(server.mail_beantworten("7", "Gern."))
    d = server._q("select postfach from drafts where id = %s", (a["draft_id"],))[0]
    assert d["postfach"] is None


# --- Versand -----------------------------------------------------------------

class Gesendet:
    def __init__(self):
        self.mails = []

    def __call__(self, nachricht, identitaet=None):
        self.mails.append((nachricht, identitaet))


def _gmx_entwurf():
    lead = server._q("insert into leads (name, email, source, consent_status) values "
                     "('Freund', 'f@beispiel.org', 'email', 'existing_customer') returning id")[0]["id"]
    return server._q("insert into drafts (lead_id, channel, recipient, subject, body, status, "
                     "approved_by, approved_at, postfach, antwort_auf) values (%s, 'email', "
                     "'f@beispiel.org', 'Re: Privat', 'Danke.', 'approved', 'betreiber', now(), "
                     "%s, 'gmx-2@x') returning id", (lead, "gmx"))[0]["id"]


def test_versand_ueber_gmx(gmx, leer, monkeypatch):
    senden = Gesendet()
    monkeypatch.setattr(mail_dispatch, "senden", senden)
    monkeypatch.setattr(mail_dispatch, "_sent_moeglich", lambda: False)
    draft = _gmx_entwurf()
    assert mail_dispatch.verarbeite_draft(draft) == "gesendet"
    nachricht, ident = senden.mails[0]
    assert nachricht["From"] == GMX_ADRESSE
    assert nachricht["In-Reply-To"] == "<gmx-2@x>"
    assert (ident.host, ident.port, ident.user, ident.passwort) == (
        "mail.gmx.net", 465, GMX_ADRESSE, GMX_GEHEIM)
    # Kopie in den Gesendet-Ordner von GMX, nicht in den des Ladens.
    assert gmx.abgelegt[0] == '"Gesendet"' and b"Danke." in gmx.abgelegt[1]
    assert server._q("select status from drafts where id = %s", (draft,))[0]["status"] == "sent"


def test_gmail_legt_selbst_ab_keine_doppelte_kopie(leer, monkeypatch):
    monkeypatch.setenv("POSTFACH_GMAIL_ADRESSE", "felix.test@gmail.com")
    monkeypatch.setenv("POSTFACH_GMAIL_PASSWORT", "app-passwort")
    senden = Gesendet()
    monkeypatch.setattr(mail_dispatch, "senden", senden)
    draft = _gmx_entwurf()
    server._q("update drafts set postfach = 'gmail' where id = %s returning id", (draft,))
    # _imap_oeffnen wirft im Test (conftest) - eine Sent-Kopie wuerde scheitern und
    # stuende nur im Log; der Vertrag ist, dass gar keine versucht wird.
    monkeypatch.setattr(mail_dispatch, "_sent_ablegen",
                        lambda *a, **k: pytest.fail("Gmail-Kopie versucht"))
    assert mail_dispatch.verarbeite_draft(draft) == "gesendet"
    assert senden.mails[0][1].host == "smtp.gmail.com"


def test_ohne_eingerichtetes_postfach_geht_nichts_raus(leer, monkeypatch):
    senden = Gesendet()
    monkeypatch.setattr(mail_dispatch, "senden", senden)
    draft = _gmx_entwurf()
    assert mail_dispatch.verarbeite_draft(draft) == "fehler"
    z = server._q("select status, error from drafts where id = %s", (draft,))[0]
    assert z["status"] == "failed" and "GMX" in z["error"]
    assert senden.mails == []


def test_passwort_des_zusatzpostfachs_nie_im_fehlertext(gmx):
    roh = base64.b64encode(GMX_GEHEIM.encode()).decode()
    text = mail_dispatch._ohne_geheimnis(f"535 auth {GMX_GEHEIM} {roh}")
    assert GMX_GEHEIM not in text and roh not in text


# --- Oberflaeche -------------------------------------------------------------

def test_posteingang_zeigt_herkunft(leer):
    server._postfach_merken([
        {"uid": "gmx:2", "message_id": "gmx-2@x", "von": "f@beispiel.org", "betreff": "Privat",
         "datum": "", "auszug": "Hallo"},
        {"uid": "7", "message_id": "laden-7@x", "von": "k@beispiel.org", "betreff": "Laden",
         "datum": "", "auszug": "Hallo"}])
    seite = TestClient(ui.app).get("/posteingang", headers=HOST_OK).text
    assert '<span class="badge">GMX</span> <b>Privat</b>' in seite
    assert '<span class="badge">Hauptpostfach</span>' not in seite


def test_freigabe_zeigt_absender_postfach(leer):
    _gmx_entwurf()
    server._q("update drafts set status = 'pending'")
    seite = TestClient(ui.app).get("/freigaben", headers=HOST_OK).text
    assert "Absender: <b>GMX</b>" in seite
