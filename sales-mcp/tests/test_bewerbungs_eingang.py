"""Vertragstests Bewerbungs-Eingang (29.10.2026, bewerbungs_eingang.py).

sales-claw liest drei Postfaecher NUR LESEND und meldet der Zentrale des
Bewerbungs-Bots genau die Mails, die zu einer wartenden Bewerbung passen.
Was diese Suite verteidigt:

1. Nur passende Mails gehen hinaus. Eine private Mail verlaesst sales-claw nie
   - auch nicht mit dem Firmennamen im Text, auch nicht im Log.
2. Der Cursor je Postfach rueckt nur nach einem vollstaendigen Lauf vor; ein
   Netzfehler zur Zentrale beendet den Lauf ohne Fortschritt.
3. IMAP wird nie schreibend geoeffnet: EXAMINE statt SELECT, BODY.PEEK statt
   RFC822, kein STORE/COPY/MOVE/EXPUNGE/APPEND.
4. Kalendereinladungen werden erkannt; ein fehlendes Postfach wird
   uebersprungen; HTML wird zu Text, gedeckelt auf 20 000 Zeichen.
5. Weder Schluessel noch Passwoerter stehen je im Log oder in der Ausgabe.

IMAP und Zentrale sind Attrappen (Vertrag v1 aus dem Auftrag vom 28.10.2026);
kein Test oeffnet eine Verbindung nach aussen. Nur die HTTP-Schicht selbst
spricht einmal mit einem Gegenueber auf 127.0.0.1.
"""
import email.utils
import http.server
import json
import logging
import re
import threading
from email.message import EmailMessage

import pytest

import bewerbungs_eingang as be
import postfach

BASIS = "https://zentrale.test:8447"
SCHLUESSEL = "eingang-geheim-0123456789"
PASSWORT_GMX = "gmx-app-passwort-geheim"

WARTELISTE = {
    "stand": "2026-10-29T18:40:00Z",
    "bewerbungen": [
        {"application_id": "bw-1", "firma": "Beispiel GmbH",
         "domains": ["beispiel.de"], "gesendet_am": "2026-10-27T09:12:00Z",
         "an": "jobs@beispiel.de"},
        {"application_id": "bw-2", "firma": "Nordlicht AG",
         "domains": ["nordlicht.example"], "gesendet_am": "2026-10-28T09:00:00Z",
         "an": "karriere@nordlicht.example"},
    ],
    "portal_absender": ["personio.de", "join.com", "smartrecruiters.com"],
}
# Fruehestes gesendet_am (27.10. 09:12 UTC) minus ein Tag.
GRENZE = "26-Oct-2026 09:12:00 +0000"


# ---------------------------------------------------------------------------
# Attrappen
# ---------------------------------------------------------------------------

def _mail(von, betreff="Ihre Bewerbung", text="Hallo Felix.", html=None,
          an="felix@vibemind.space", message_id=None, ics=None,
          ics_anhang=False):
    m = EmailMessage()
    m["From"] = von
    m["To"] = an
    m["Subject"] = betreff
    m["Date"] = "Thu, 29 Oct 2026 10:00:00 +0100"
    if message_id is not False:
        m["Message-ID"] = message_id or email.utils.make_msgid(domain="test.invalid")
    if html is not None:
        m.set_content(html, subtype="html")
    else:
        m.set_content(text)
    if ics is not None:
        if ics_anhang:
            m.add_attachment(ics.encode("utf-8"), maintype="application",
                             subtype="ics", filename="invite.ics")
        else:
            m.add_alternative(ics, subtype="calendar",
                              params={"method": "REQUEST"})
    return m.as_bytes()


_MONATE = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _tag(imap_datum: str) -> tuple:
    t, m, j = imap_datum.split()[0].split("-")
    return int(j), _MONATE[m], int(t)


class AttrappeImap:
    """Ein Postfach, das mitschreibt, WIE es benutzt wird. Alles ausser
    select/uid/response/logout ist verboten und laesst den Test scheitern."""

    def __init__(self, mails, uidvalidity=7):
        # uid(int) -> (INTERNALDATE, rfc822 bytes)
        self.mails = dict(mails)
        self.uidvalidity = uidvalidity
        self.befehle = []

    def select(self, ordner, readonly=False):
        self.befehle.append(("select", ordner, readonly))
        return "OK", [str(len(self.mails)).encode()]

    def response(self, code):
        if code == "UIDVALIDITY":
            return code, [str(self.uidvalidity).encode()]
        if code == "UIDNEXT":
            return code, [str(max(self.mails, default=0) + 1).encode()]
        return code, [None]

    def uid(self, befehl, *args):
        befehl = befehl.lower()
        self.befehle.append(("uid", befehl) + args)
        if befehl == "search":
            teile = [a for a in args if a is not None]
            assert teile[0].upper() == "UID" and teile[2].upper() == "SINCE", teile
            start = int(teile[1].split(":")[0])
            seit = _tag(teile[3])
            alle = sorted(self.mails)
            treffer = [u for u in alle if u >= start
                       and _tag(self.mails[u][0]) >= seit]
            # Die bekannte IMAP-Falle: "n:*" mit n hinter der hoechsten UID
            # liefert die LETZTE Mail statt keiner (RFC 3501, '*' = groesste UID).
            if not treffer and alle and start > alle[-1]:
                treffer = [alle[-1]]
            return "OK", [" ".join(str(u) for u in treffer).encode()]
        if befehl == "fetch":
            uid, was = int(args[0]), args[1]
            assert "BODY.PEEK[]" in was and "RFC822" not in was.upper(), was
            datum, roh = self.mails[uid]
            kopf = (f'{uid} (UID {uid} INTERNALDATE "{datum}" '
                    f'BODY[] {{{len(roh)}}}').encode()
            return "OK", [(kopf, roh), b")"]
        raise AssertionError(f"unerwarteter UID-Befehl {befehl}")

    def logout(self):
        self.befehle.append(("logout",))
        return "BYE", []

    def __getattr__(self, name):
        raise AssertionError(f"verbotener IMAP-Befehl {name}")


class AttrappeZentrale:
    """Vertrag v1. `reaktionen` (Liste) bestimmt die Antworten auf POST in
    Reihenfolge: (status, koerper) oder eine Ausnahme zum Werfen."""

    def __init__(self, warteliste=None):
        self.warteliste = json.loads(json.dumps(warteliste or WARTELISTE))
        self.reaktionen = []
        self.gemeldet = []
        self.anfragen = []

    def __call__(self, methode, url, kopf, koerper, zeitlimit):
        self.anfragen.append((methode, url, dict(kopf)))
        assert kopf.get("X-Eingang-Key") == SCHLUESSEL
        if methode == "GET" and url == BASIS + "/api/eingang/warteliste":
            return 200, json.dumps(self.warteliste).encode()
        if methode == "POST" and url == BASIS + "/api/eingang/mails":
            daten = json.loads(koerper)
            self.gemeldet.append(daten)
            reaktion = (self.reaktionen.pop(0) if self.reaktionen
                        else (200, {"status": "angenommen"}))
            if isinstance(reaktion, BaseException):
                raise reaktion
            return reaktion[0], json.dumps(reaktion[1]).encode()
        raise AssertionError(f"unerwartete Anfrage {methode} {url}")

    def ids(self):
        return [m["message_id"] for m in self.gemeldet]


@pytest.fixture
def ablage(monkeypatch):
    """Cursor-Ablage im Speicher statt in der Tabelle einstellungen."""
    gespeichert = {}
    schreibvorgaenge = []

    def lesen():
        return json.loads(json.dumps(gespeichert))

    def schreiben(daten):
        schreibvorgaenge.append(json.loads(json.dumps(daten)))
        gespeichert.clear()
        gespeichert.update(json.loads(json.dumps(daten)))

    monkeypatch.setattr(be, "_cursor_lesen", lesen)
    monkeypatch.setattr(be, "_cursor_schreiben", schreiben)
    gespeichert_obj = type("Ablage", (), {})()
    gespeichert_obj.daten = gespeichert
    gespeichert_obj.schreibvorgaenge = schreibvorgaenge
    return gespeichert_obj


@pytest.fixture
def zentrale(monkeypatch):
    z = AttrappeZentrale()
    monkeypatch.setattr(be, "URL", BASIS)
    monkeypatch.setattr(be, "KEY", SCHLUESSEL)
    monkeypatch.setattr(be, "HTTP", z)
    return z


@pytest.fixture
def haupt(monkeypatch):
    """Das Hauptpostfach (felix@vibemind.space) als Attrappe."""
    kasten = AttrappeImap({})
    monkeypatch.setattr(postfach, "IMAP_HOST", "imap.test.invalid")
    monkeypatch.setattr(postfach, "IMAP_USER", "felix@vibemind.space")
    monkeypatch.setattr(postfach, "_verbinden", lambda: kasten)
    return kasten


@pytest.fixture
def gmx(monkeypatch):
    kasten = AttrappeImap({}, uidvalidity=99)
    monkeypatch.setenv("POSTFACH_GMX_ADRESSE", "felix@gmx.test")
    monkeypatch.setenv("POSTFACH_GMX_PASSWORT", PASSWORT_GMX)

    def oeffnen(konto):
        assert konto.kennung == "gmx"
        return kasten
    monkeypatch.setattr(postfach, "_imap_oeffnen", oeffnen)
    return kasten


EINGANG = "29-Oct-2026 10:00:05 +0100"


# ---------------------------------------------------------------------------
# 1. Nur passende Mails gehen hinaus
# ---------------------------------------------------------------------------

def test_nur_passende_mails_werden_gemeldet(zentrale, haupt, ablage):
    haupt.mails = {
        1: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<a@beispiel.de>")),
        2: (EINGANG, _mail("Team <hr@karriere.beispiel.de>",
                           message_id="<b@beispiel.de>")),
        3: (EINGANG, _mail("Oma <oma@web.de>", betreff="Gruesse",
                           text="Wie war es bei der Beispiel GmbH?",
                           message_id="<privat@web.de>")),
        4: (EINGANG, _mail("Personio <no-reply@personio.de>",
                           betreff="Deine Bewerbung bei Beispiel GmbH",
                           message_id="<c@personio.de>")),
        5: (EINGANG, _mail("Personio <no-reply@personio.de>",
                           betreff="Deine Bewerbung bei Andere AG",
                           message_id="<d@personio.de>")),
        6: (EINGANG, _mail("Falsch <x@boese-beispiel.de>",
                           message_id="<e@boese-beispiel.de>")),
        7: (EINGANG, _mail("JOIN <notifications@mail.join.com>",
                           betreff="Neuigkeiten",
                           text="Nordlicht AG hat deine Bewerbung gelesen.",
                           message_id="<f@join.com>")),
    }
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert sorted(zentrale.ids()) == sorted(
        ["<a@beispiel.de>", "<b@beispiel.de>", "<c@personio.de>", "<f@join.com>"])
    nach_id = {m["message_id"]: m for m in zentrale.gemeldet}
    assert nach_id["<a@beispiel.de>"]["kandidaten"] == ["bw-1"]
    assert nach_id["<f@join.com>"]["kandidaten"] == ["bw-2"]
    assert all(m["postfach"] == "vibemind" for m in zentrale.gemeldet)
    assert ergebnis["postfaecher"]["vibemind"]["geprueft"] == 7
    assert ergebnis["postfaecher"]["vibemind"]["passend"] == 4


def test_rumpf_folgt_dem_vertrag_v1(zentrale, haupt, ablage):
    haupt.mails = {1: (EINGANG, _mail(
        "=?utf-8?q?J=C3=BCrgen_Personal?= <jobs@beispiel.de>",
        betreff="=?utf-8?q?R=C3=BCckfrage_zu_Ihrer_Bewerbung?=",
        text="Koennen Sie am Montag?", message_id="<r1@beispiel.de>"))}
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert set(rumpf) == {"postfach", "message_id", "von", "an", "betreff",
                          "datum", "text", "kalender", "kandidaten"}
    assert rumpf["von"] == "Jürgen Personal <jobs@beispiel.de>"
    assert rumpf["an"] == "felix@vibemind.space"
    assert rumpf["betreff"] == "Rückfrage zu Ihrer Bewerbung"
    assert rumpf["text"] == "Koennen Sie am Montag?"
    # Eingang beim Server, in UTC.
    assert rumpf["datum"] == "2026-10-29T09:00:05Z"
    assert rumpf["kalender"] is None
    assert rumpf["kandidaten"] == ["bw-1"]


def test_private_mail_verlaesst_sales_claw_nie_auch_nicht_im_log(
        zentrale, haupt, ablage, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    haupt.mails = {
        1: (EINGANG, _mail("Freundin <lisa@web.de>",
                           betreff="Geheimnis-Betreff-4711",
                           text="Ich habe gehoert, du warst bei Beispiel GmbH "
                                "und Nordlicht AG. Privates Detail XYZ.",
                           message_id="<privat-4711@web.de>")),
    }
    ergebnis = be.lauf()
    print(json.dumps(ergebnis))
    assert zentrale.gemeldet == []
    gesamt = caplog.text + capsys.readouterr().out
    for spur in ("Geheimnis-Betreff-4711", "lisa@web.de", "privat-4711",
                 "Privates Detail", "web.de"):
        assert spur not in gesamt, spur


def test_vor_der_grenze_eingegangene_mails_bleiben_draussen(zentrale, haupt, ablage):
    haupt.mails = {
        1: ("25-Oct-2026 08:00:00 +0000",
            _mail("Alt <jobs@beispiel.de>", message_id="<alt@beispiel.de>")),
        2: ("26-Oct-2026 08:00:00 +0000",
            _mail("Knapp davor <jobs@beispiel.de>", message_id="<knapp@beispiel.de>")),
        3: ("26-Oct-2026 21:00:00 +0000",
            _mail("Danach <jobs@beispiel.de>", message_id="<danach@beispiel.de>")),
    }
    be.lauf()
    assert zentrale.ids() == ["<danach@beispiel.de>"]


def test_freemail_domain_in_der_warteliste_oeffnet_keine_privaten_mails(
        zentrale, haupt, ablage):
    """Eine kleine Firma mit Gmail-Adresse darf nicht dazu fuehren, dass jede
    Mail von gmail.com hinausgeht. Gemeldet wird dann nur die eine Adresse."""
    zentrale.warteliste["bewerbungen"].append(
        {"application_id": "bw-3", "firma": "Baeckerei Korn",
         "domains": ["gmail.com"], "gesendet_am": "2026-10-28T09:00:00Z",
         "an": "baeckerei.korn@gmail.com"})
    zentrale.warteliste["portal_absender"].append("web.de")
    haupt.mails = {
        1: (EINGANG, _mail("Freund <freund@gmail.com>", message_id="<f@gmail>")),
        2: (EINGANG, _mail("Korn <Baeckerei.Korn@gmail.com>", message_id="<k@gmail>")),
        3: (EINGANG, _mail("Oma <oma@web.de>", text="Beispiel GmbH?",
                           message_id="<o@web>")),
    }
    be.lauf()
    assert zentrale.ids() == ["<k@gmail>"]
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-3"]


def test_firmenname_ohne_rechtsform_und_nur_als_ganzes_wort(zentrale, haupt, ablage):
    haupt.mails = {
        1: (EINGANG, _mail("Personio <no-reply@personio.de>",
                           betreff="Danke fuer deine Bewerbung bei BEISPIEL",
                           message_id="<kern@personio.de>")),
        2: (EINGANG, _mail("Personio <no-reply@personio.de>",
                           betreff="Beispielhafte Stellen fuer dich",
                           message_id="<wort@personio.de>")),
    }
    be.lauf()
    assert zentrale.ids() == ["<kern@personio.de>"]


def test_firmenname_im_absendernamen_genuegt(zentrale, haupt, ablage):
    haupt.mails = {1: (EINGANG, _mail(
        "Nordlicht AG via SmartRecruiters <no-reply@smartrecruiters.com>",
        betreff="Update", text="Status geaendert.",
        message_id="<sr@smartrecruiters.com>"))}
    be.lauf()
    assert zentrale.ids() == ["<sr@smartrecruiters.com>"]
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-2"]


# ---------------------------------------------------------------------------
# 2. Kalendereinladungen
# ---------------------------------------------------------------------------

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REQUEST\r\n"
    "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nBEGIN:DAYLIGHT\r\n"
    "DTSTART:19700329T020000\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\nUID:gespraech-1@beispiel.de\r\n"
    "DTSTART;TZID=Europe/Berlin:20261105T100000\r\n"
    "DTEND;TZID=Europe/Berlin:20261105T110000\r\n"
    "SUMMARY:Kennenlernen\r\n"
    "ORGANIZER;CN=Personal Beispiel:mailto:HR@Beispiel.de\r\n"
    "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:felix@vibemind.space\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n")


def test_kalendereinladung_wird_erkannt_und_gemeldet(zentrale, haupt, ablage):
    """Absender ist der Kalenderdienst, nicht die Firma - die Einladung zaehlt
    ueber die Domain des Organisators."""
    haupt.mails = {1: (EINGANG, _mail(
        "Google Kalender <calendar-notification@google.com>",
        betreff="Einladung: Kennenlernen", text="Einladung im Anhang.",
        message_id="<ics@google.com>", ics=ICS))}
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["kalender"] == {"start": "2026-11-05T09:00:00Z",
                                 "ende": "2026-11-05T10:00:00Z",
                                 "organisator": "hr@beispiel.de"}
    assert rumpf["kandidaten"] == ["bw-1"]


def test_einladung_als_ics_anhang_wird_erkannt(zentrale, haupt, ablage):
    haupt.mails = {1: (EINGANG, _mail(
        "Outlook <noreply@outlook.example>", betreff="Termin",
        message_id="<anhang@outlook>", ics=ICS, ics_anhang=True))}
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["kalender"]["organisator"] == "hr@beispiel.de"


def test_einladung_einer_fremden_firma_bleibt_draussen(zentrale, haupt, ablage):
    fremd = ICS.replace("mailto:HR@Beispiel.de", "mailto:chef@sportverein.example")
    haupt.mails = {1: (EINGANG, _mail(
        "Google Kalender <calendar-notification@google.com>",
        betreff="Training", message_id="<verein@google.com>", ics=fremd))}
    be.lauf()
    assert zentrale.gemeldet == []


def test_antwort_auf_eine_einladung_ist_keine_einladung(zentrale, haupt, ablage):
    absage = ICS.replace("METHOD:REQUEST", "METHOD:CANCEL")
    haupt.mails = {1: (EINGANG, _mail(
        "HR <hr@beispiel.de>", betreff="Abgesagt: Kennenlernen",
        message_id="<cancel@beispiel.de>", ics=absage))}
    be.lauf()
    (rumpf,) = zentrale.gemeldet          # passt ueber die Firmen-Domain
    assert rumpf["kalender"] is None


# ---------------------------------------------------------------------------
# 3. Cursor
# ---------------------------------------------------------------------------

def test_cursor_rueckt_nach_vollstaendigem_lauf_vor(zentrale, haupt, ablage):
    haupt.mails = {
        1: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<1@beispiel.de>")),
        2: (EINGANG, _mail("Oma <oma@web.de>", message_id="<2@web.de>")),
    }
    be.lauf()
    assert ablage.daten["vibemind"]["uid"] == 2
    assert ablage.daten["vibemind"]["uidvalidity"] == 7
    assert len(ablage.schreibvorgaenge) == 1          # einmal, am Ende

    haupt.mails[3] = (EINGANG, _mail("HR <jobs@beispiel.de>",
                                     message_id="<3@beispiel.de>"))
    be.lauf()
    assert zentrale.ids() == ["<1@beispiel.de>", "<3@beispiel.de>"]
    assert ablage.daten["vibemind"]["uid"] == 3


def test_uid_stern_falle_meldet_die_letzte_mail_nicht_doppelt(zentrale, haupt, ablage):
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>",
                                      message_id="<1@beispiel.de>"))}
    be.lauf()
    be.lauf()     # Server liefert fuer "2:*" die Mail 1 zurueck
    assert zentrale.ids() == ["<1@beispiel.de>"]


def test_netzfehler_beendet_den_lauf_ohne_den_cursor_zu_schieben(
        zentrale, haupt, gmx, ablage):
    gmx.mails = {5: (EINGANG, _mail("HR <jobs@beispiel.de>",
                                    message_id="<g@beispiel.de>"))}
    haupt.mails = {
        1: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<1@beispiel.de>")),
        2: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<2@beispiel.de>")),
    }
    zentrale.reaktionen = [(200, {"status": "angenommen"}),
                           be.NetzFehler("URLError")]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ablage.schreibvorgaenge == []
    assert "<g@beispiel.de>" not in zentrale.ids()   # GMX kam nicht mehr dran

    # Der naechste Lauf holt dieselben Mails noch einmal; die Zentrale ist
    # idempotent und sagt "bekannt".
    zentrale.gemeldet.clear()
    zentrale.reaktionen = [(200, {"status": "bekannt"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert sorted(zentrale.ids()) == ["<1@beispiel.de>", "<2@beispiel.de>",
                                      "<g@beispiel.de>"]
    assert ergebnis["postfaecher"]["vibemind"]["bekannt"] == 1
    assert ablage.daten["vibemind"]["uid"] == 2 and ablage.daten["gmx"]["uid"] == 5


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500, 503])
def test_zentrale_nicht_bereit_bricht_ab_statt_mails_zu_verlieren(
        zentrale, haupt, ablage, code):
    """Auslegung (Board): Ein falscher Schluessel, ein fehlender Endpunkt oder
    eine ueberlastete Zentrale lehnt nicht DIESE Mail ab, sondern jede. Liefe
    der Lauf weiter, rueckte der Cursor vor und die Mails waeren verloren."""
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>",
                                      message_id="<1@beispiel.de>"))}
    zentrale.reaktionen = [(code, {"detail": "nein"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ablage.schreibvorgaenge == []


def test_abgelehnte_mail_wird_protokolliert_und_der_lauf_geht_weiter(
        zentrale, haupt, ablage, caplog):
    caplog.set_level(logging.INFO)
    haupt.mails = {
        1: (EINGANG, _mail("HR <jobs@beispiel.de>", betreff="Betreff-Eins",
                           message_id="<1@beispiel.de>")),
        2: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<2@beispiel.de>")),
    }
    zentrale.reaktionen = [(422, {"detail": "kaputt"}),
                           (200, {"status": "angenommen"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert zentrale.ids() == ["<1@beispiel.de>", "<2@beispiel.de>"]
    assert ergebnis["postfaecher"]["vibemind"]["abgelehnt"] == 1
    assert ergebnis["postfaecher"]["vibemind"]["angenommen"] == 1
    assert "422" in caplog.text and "<1@beispiel.de>" in caplog.text
    assert "Betreff-Eins" not in caplog.text
    assert ablage.daten["vibemind"]["uid"] == 2


def test_neue_uidvalidity_liest_das_postfach_neu(zentrale, haupt, ablage):
    ablage.daten.update({"vibemind": {"uidvalidity": 1, "uid": 500}})
    haupt.mails = {3: (EINGANG, _mail("HR <jobs@beispiel.de>",
                                      message_id="<3@beispiel.de>"))}
    be.lauf()
    assert zentrale.ids() == ["<3@beispiel.de>"]
    assert ablage.daten["vibemind"] == {**ablage.daten["vibemind"],
                                        "uidvalidity": 7, "uid": 3}


def test_trockenlauf_meldet_nichts_und_schiebt_keinen_cursor(zentrale, haupt, ablage):
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>",
                                      message_id="<1@beispiel.de>"))}
    ergebnis = be.lauf(trocken=True)
    assert ergebnis["postfaecher"]["vibemind"]["passend"] == 1
    assert zentrale.gemeldet == [] and ablage.schreibvorgaenge == []


# ---------------------------------------------------------------------------
# 4. Nur lesend, Postfaecher, Text
# ---------------------------------------------------------------------------

def test_imap_wird_nie_schreibend_geoeffnet(zentrale, haupt, gmx, ablage):
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>"))}
    gmx.mails = {9: (EINGANG, _mail("Oma <oma@web.de>"))}
    be.lauf()
    for kasten in (haupt, gmx):
        selects = [b for b in kasten.befehle if b[0] == "select"]
        assert selects and all(b[2] is True for b in selects), selects
        uids = {b[1] for b in kasten.befehle if b[0] == "uid"}
        assert uids <= {"search", "fetch"}, uids
        assert kasten.befehle[-1] == ("logout",)


def test_fehlendes_postfach_wird_uebersprungen(zentrale, haupt, ablage, caplog):
    caplog.set_level(logging.INFO)
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>"))}
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert ergebnis["postfaecher"]["gmail"] == {"status": "nicht eingerichtet"}
    assert ergebnis["postfaecher"]["gmx"] == {"status": "nicht eingerichtet"}
    assert "gmx: nicht eingerichtet" in caplog.text
    assert set(ablage.daten) == {"vibemind"}


def test_kaputtes_postfach_kostet_die_anderen_nicht(zentrale, haupt, ablage,
                                                     monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("POSTFACH_GMX_ADRESSE", "felix@gmx.test")
    monkeypatch.setenv("POSTFACH_GMX_PASSWORT", PASSWORT_GMX)
    ablage.daten.update({"gmx": {"uidvalidity": 99, "uid": 40}})

    def kaputt(konto):
        raise OSError(f"login failed for {konto.adresse} with {konto.passwort}")
    monkeypatch.setattr(postfach, "_imap_oeffnen", kaputt)
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>"))}
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ergebnis["postfaecher"]["gmx"]["status"] == "fehler"
    assert ablage.daten["gmx"] == {"uidvalidity": 99, "uid": 40}
    assert ablage.daten["vibemind"]["uid"] == 1
    assert PASSWORT_GMX not in caplog.text and "felix@gmx.test" not in caplog.text


def test_eine_unlesbare_mail_haelt_das_postfach_nicht_auf(zentrale, haupt, ablage,
                                                          monkeypatch, caplog):
    """Sonst bliebe der Cursor fuer immer vor dieser einen Mail stehen."""
    caplog.set_level(logging.DEBUG)
    echt = be._auswerten

    def zickig(roh, kopf, liste, name, uidvalidity, uid):
        if uid == 1:
            raise UnicodeError("Inhalt-der-kaputten-Mail")
        return echt(roh, kopf, liste, name, uidvalidity, uid)
    monkeypatch.setattr(be, "_auswerten", zickig)
    haupt.mails = {
        1: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<1@beispiel.de>")),
        2: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id="<2@beispiel.de>")),
    }
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert ergebnis["postfaecher"]["vibemind"]["unlesbar"] == 1
    assert zentrale.ids() == ["<2@beispiel.de>"]
    assert ablage.daten["vibemind"]["uid"] == 2
    assert "Inhalt-der-kaputten-Mail" not in caplog.text


def test_dreibuchstabige_firma_ohne_rechtsform(zentrale, haupt, ablage):
    zentrale.warteliste["bewerbungen"].append(
        {"application_id": "bw-4", "firma": "SAP SE", "domains": ["sap.example"],
         "gesendet_am": "2026-10-28T09:00:00Z", "an": "jobs@sap.example"})
    haupt.mails = {1: (EINGANG, _mail("JOIN <no-reply@join.com>",
                                      betreff="Deine Bewerbung bei SAP",
                                      message_id="<sap@join.com>"))}
    be.lauf()
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-4"]


def test_leere_warteliste_oeffnet_kein_postfach(zentrale, ablage, monkeypatch):
    zentrale.warteliste["bewerbungen"] = []

    def nie(*a, **kw):
        raise AssertionError("Postfach geoeffnet trotz leerer Warteliste")
    monkeypatch.setattr(postfach, "oeffnen", nie)
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert ergebnis["status"] == "warteliste leer"
    assert ablage.schreibvorgaenge == []


def test_ohne_schluessel_kein_aufruf(monkeypatch, ablage):
    monkeypatch.setattr(be, "URL", BASIS)
    monkeypatch.setattr(be, "KEY", "")

    def nie(*a, **kw):
        raise AssertionError("Anfrage ohne Schluessel")
    monkeypatch.setattr(be, "HTTP", nie)
    ergebnis = be.lauf()
    assert ergebnis["status"] == "nicht eingerichtet"


def test_html_wird_zu_text_und_auf_20000_zeichen_gekuerzt(zentrale, haupt, ablage):
    html = ("<html><head><style>p{color:red}</style><title>T</title></head><body>"
            "<p>Sehr geehrter Herr Baumann,</p><script>alert(1)</script>"
            "<p>wir laden Sie ein &amp; freuen uns&nbsp;darauf.</p>"
            + "<div>" + "x" * 30000 + "</div></body></html>")
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>", html=html))}
    be.lauf()
    text = zentrale.gemeldet[0]["text"]
    assert len(text) == 20000
    assert "<" not in text and "color:red" not in text and "alert" not in text
    assert "Sehr geehrter Herr Baumann," in text
    assert "wir laden Sie ein & freuen uns darauf." in text


def test_fehlende_message_id_bekommt_eine_stabile_ersatzkennung(zentrale, haupt, ablage):
    haupt.mails = {12: (EINGANG, _mail("HR <jobs@beispiel.de>", message_id=False))}
    be.lauf()
    ablage.daten.clear()
    be.lauf()
    a, b = zentrale.ids()
    assert a == b and re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", a), a


# ---------------------------------------------------------------------------
# 5. Geheimnisse
# ---------------------------------------------------------------------------

def test_geheimnisse_erscheinen_nicht_im_log(zentrale, haupt, ablage, monkeypatch,
                                             caplog, capsys):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(postfach, "IMAP_PASSWORT", "haupt-passwort-geheim")
    monkeypatch.setenv("POSTFACH_GMAIL_ADRESSE", "felix@gmail.test")
    monkeypatch.setenv("POSTFACH_GMAIL_PASSWORT", "gmail-passwort-geheim")

    def kaputt(konto):
        raise OSError(f"AUTHENTICATIONFAILED {konto.passwort}")
    monkeypatch.setattr(postfach, "_imap_oeffnen", kaputt)
    haupt.mails = {1: (EINGANG, _mail("HR <jobs@beispiel.de>"))}
    zentrale.reaktionen = [ValueError(f"header {SCHLUESSEL} kaputt")]
    # main() haengt einen eigenen stdout-Handler an (propagate aus) - fuer
    # diesen Test, danach zurueck, damit caplog in anderen Tests sieht.
    monkeypatch.setattr(be.LOG, "handlers", [])
    monkeypatch.setattr(be.LOG, "propagate", True)
    monkeypatch.setattr(be.LOG, "level", logging.NOTSET)
    rc = be.main(["lauf"])
    assert rc == 1
    gesamt = caplog.text + "".join(capsys.readouterr())
    for geheim in (SCHLUESSEL, "haupt-passwort-geheim", "gmail-passwort-geheim"):
        assert geheim not in gesamt, geheim


# ---------------------------------------------------------------------------
# HTTP-Schicht gegen ein Gegenueber auf 127.0.0.1
# ---------------------------------------------------------------------------

class _Gegenueber(http.server.BaseHTTPRequestHandler):
    gesehen = []

    def do_GET(self):
        _Gegenueber.gesehen.append(("GET", self.path, dict(self.headers)))
        koerper = json.dumps({"stand": "x", "bewerbungen": [],
                              "portal_absender": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(koerper)))
        self.end_headers()
        self.wfile.write(koerper)

    def log_message(self, *a):
        pass


def test_http_schicht_sendet_den_schluessel_nur_im_kopf(monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Gegenueber)
    faden = threading.Thread(target=server.serve_forever, daemon=True)
    faden.start()
    try:
        monkeypatch.setattr(be, "URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setattr(be, "KEY", SCHLUESSEL)
        ergebnis = be.lauf()
    finally:
        server.shutdown()
    assert ergebnis["status"] == "warteliste leer"
    ((methode, pfad, kopf),) = _Gegenueber.gesehen
    assert methode == "GET" and pfad == "/api/eingang/warteliste"
    assert kopf.get("X-Eingang-Key") == SCHLUESSEL
    assert SCHLUESSEL not in pfad


def test_unerreichbare_zentrale_ist_ein_netzfehler(monkeypatch):
    monkeypatch.setattr(be, "URL", "http://127.0.0.1:9")
    monkeypatch.setattr(be, "KEY", SCHLUESSEL)
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ergebnis["status"] == "zentrale nicht erreichbar"


@pytest.mark.parametrize("key,erwartet", [
    ("k-123", True), ("", False), ("mit leer", False), ("umläut", False),
    ("steuer\x07", False)])
def test_eingerichtet_nur_mit_sendbarem_schluessel(monkeypatch, key, erwartet):
    monkeypatch.setattr(be, "URL", BASIS)
    monkeypatch.setattr(be, "KEY", key)
    assert be.eingerichtet() is erwartet
