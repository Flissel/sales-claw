"""Vertragstests Bewerbungs-Eingang (bewerbungs_eingang.py).

sales-claw liest die Mails NUR aus der Datenbank der Post-Sammelstelle
(`post_mails`/`post_konten`, geschrieben von sales-post) und meldet der
Zentrale des Bewerbungs-Bots genau die, die zu einer wartenden Bewerbung
passen. Was diese Suite verteidigt:

1. Nur passende Mails gehen hinaus. Eine private Mail verlaesst sales-claw nie
   - auch nicht mit dem Firmennamen im Text, auch nicht im Log.
2. Nur Konten des Laden-Inhabers (Besitzer des env-Kontos) werden gelesen,
   nur aktive; die Postfach-Namen im Vertrag sind gmail/gmx/vibemind.
3. Kein IMAP: das Modul oeffnet nie ein Postfach und schreibt nie in die
   Datenbank. Kein Cursor - jeder Lauf prueft das ganze Fenster, die Zentrale
   ist idempotent.
4. Die Meldung passt in die Grenzen der Zentrale (320/998/20 000/20).
5. Weder Schluessel noch Adressen/Kennungen stehen je im Log oder in der Ausgabe.

Die Datenbankschicht (`_konten`, `_mails`, `_text`) ist in den meisten Tests
eine Attrappe; EIN Test (`test_echte_abfragen_...`) laeuft gegen sales_test. Die
Zentrale ist eine Attrappe (Vertrag v1); kein Test oeffnet eine Verbindung nach
aussen. Nur die HTTP-Schicht selbst spricht einmal mit 127.0.0.1.
"""
import http.server
import imaplib
import itertools
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import bewerbungs_eingang as be  # noqa: E402
import postfach  # noqa: E402

UTC = timezone.utc
BASIS = "https://zentrale.test:8447"
SCHLUESSEL = "eingang-geheim-0123456789"
ADRESSE_GMX = "felix.geheim@gmx.test"
KENNUNG_GMX = "gmx-kennung-felix.geheim@gmx.test"

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
# Fruehestes gesendet_am (27.10. 09:12 UTC) minus ein Tag = 26.10. 09:12 UTC.
GRENZE = datetime(2026, 10, 26, 9, 12, tzinfo=UTC)
EINGANG = datetime(2026, 10, 29, 9, 0, 5, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Attrappen
# ---------------------------------------------------------------------------

class AttrappeSammelstelle:
    """Die drei Funktionen der Datenbankschicht. `_mails` bildet die SQL-
    Bedingung nach (datum >= grenze oder datum null und gesehen_am >= grenze;
    die echte Abfrage prueft der Test gegen sales_test) und liefert KEINEN
    Text - den gibt es nur ueber `_text`, und jede Abfrage wird gezaehlt."""

    def __init__(self):
        self.konten = []
        self.zeilen = {}           # konto_id -> [Zeile mit Text]
        self.fehler = {}           # "konten"/"mails"/"text" -> Ausnahme
        self.mails_abgefragt = []  # (konto_id, besitzer)
        self.text_abgefragt = []   # mail_id
        self._nr = itertools.count(1)
        self.haupt = self.konto("namecheap")

    def konto(self, anbieter, besitzer="felix", quelle="ui", aktiv=True):
        nr = next(self._nr)
        kid = f"k{nr}"
        self.konten.append({
            "id": kid, "besitzer": besitzer, "anbieter": anbieter,
            "quelle": quelle, "aktiv": aktiv,
            # Nie ins Log/Ergebnis: die echte `_konten` liefert beides gar nicht
            # erst, die Attrappe versucht das Modul hier zu verleiten.
            "kennung": f"{KENNUNG_GMX}-{nr}", "adresse": ADRESSE_GMX,
            "angelegt_am": datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=nr)})
        self.zeilen[kid] = []
        if self.konten[0] is self.konten[-1]:
            self.konten[0]["quelle"] = "env"
        return kid

    def mail(self, von, betreff="Ihre Bewerbung", text="Hallo Felix.",
             an="felix@vibemind.space", message_id=None, datum=EINGANG,
             gesehen_am=EINGANG, ersatz=False, konto=None, besitzer=None):
        nr = next(self._nr)
        konto = konto or self.haupt
        zeile = {
            "id": f"m{nr}", "von": von, "an": an, "betreff": betreff,
            "datum": datum, "gesehen_am": gesehen_am,
            "message_id": message_id if message_id is not None else f"m{nr}@test.invalid",
            "message_id_ersatz": ersatz, "text": text,
            "besitzer": besitzer or self._besitzer(konto)}
        self.zeilen[konto].append(zeile)
        return zeile["id"]

    def _besitzer(self, konto):
        return next(k["besitzer"] for k in self.konten if k["id"] == konto)

    # -- ersetzt die Funktionen des Moduls ---------------------------------
    def _konten(self):
        if "konten" in self.fehler:
            raise self.fehler["konten"]
        return [dict(k) for k in self.konten]

    def _mails(self, konto_id, besitzer, grenze):
        if "mails" in self.fehler:
            raise self.fehler["mails"]
        self.mails_abgefragt.append((konto_id, besitzer))
        treffer = []
        for z in self.zeilen[konto_id]:
            if z["besitzer"] != besitzer:
                continue
            if ((z["datum"] is not None and z["datum"] >= grenze)
                    or (z["datum"] is None and z["gesehen_am"] >= grenze)):
                treffer.append({k: v for k, v in z.items() if k != "text"})
        return treffer

    def _text(self, mail_id):
        if "text" in self.fehler:
            raise self.fehler["text"]
        self.text_abgefragt.append(mail_id)
        for zeilen in self.zeilen.values():
            for z in zeilen:
                if z["id"] == mail_id:
                    return z["text"]
        raise AssertionError(mail_id)


_FELDER = {"postfach", "message_id", "von", "an", "betreff", "datum", "text",
           "kalender", "kandidaten"}


def _text_ok(wert, hoechstens, mindestens=0):
    if not isinstance(wert, str) or not mindestens <= len(wert) <= hoechstens:
        return False
    try:
        wert.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _regeln_der_zentrale(daten) -> list:
    """Was die echte Zentrale (bewerbung, zentrale/eingang_api.py und
    antworten.mail_melden, Stand 13.11.2026) an einer Meldung prueft. Jeder
    Verstoss dort ist eine 422 - die Mail waere verloren. Ein Kalender, der
    nicht passt, lehnt die Mail nicht ab, wird aber verworfen: auch das zaehlt
    hier als Verstoss."""
    if not isinstance(daten, dict):
        return ["kein Objekt"]
    v = []
    if set(daten) - _FELDER:
        v.append(f"Zusatzfelder {sorted(set(daten) - _FELDER)}")
    if _FELDER - {"kalender"} - set(daten):
        v.append(f"fehlende Felder {sorted(_FELDER - {'kalender'} - set(daten))}")
    if daten.get("postfach") not in ("gmail", "gmx", "vibemind"):
        v.append("postfach")
    for feld, hoechstens, mindestens in (("message_id", 998, 1), ("von", 320, 0),
                                         ("an", 320, 0), ("betreff", 998, 0),
                                         ("text", 20000, 0), ("datum", 64, 1)):
        if not _text_ok(daten.get(feld), hoechstens, mindestens):
            v.append(feld)
    if "datum" not in v:
        try:
            zone = datetime.fromisoformat(daten["datum"]).utcoffset()
        except ValueError:
            zone = None
        if zone is None:
            v.append("datum ohne Zone")
    kandidaten = daten.get("kandidaten")
    if (not isinstance(kandidaten, list) or not 1 <= len(kandidaten) <= 20
            or not all(isinstance(k, str) for k in kandidaten)):
        v.append("kandidaten")
    kal = daten.get("kalender")
    if kal is not None and (
            not isinstance(kal, dict) or set(kal) != {"start", "ende", "organisator"}
            or not all(_text_ok(kal[f], 320) for f in kal)):
        v.append("kalender verworfen")
    return v


class AttrappeZentrale:
    """Vertrag v1 mit den Pruefungen der echten Zentrale. `reaktionen` (Liste)
    bestimmt die Antworten auf POST in Reihenfolge: (status, koerper) oder eine
    Ausnahme zum Werfen. Ein Rumpf, den die echte Zentrale abwiese, landet in
    `verstoesse`; das Fixture laesst den Test dann scheitern."""

    def __init__(self, warteliste=None):
        self.warteliste = json.loads(json.dumps(warteliste or WARTELISTE))
        self.reaktionen = []
        self.gemeldet = []
        self.anfragen = []
        self.verstoesse = []

    def __call__(self, methode, url, kopf, koerper, zeitlimit):
        self.anfragen.append((methode, url, dict(kopf)))
        assert kopf.get("X-Eingang-Key") == SCHLUESSEL
        if methode == "GET" and url == BASIS + "/api/eingang/warteliste":
            return 200, json.dumps(self.warteliste).encode()
        if methode == "POST" and url == BASIS + "/api/eingang/mails":
            daten = json.loads(koerper)
            self.gemeldet.append(daten)
            verstoss = _regeln_der_zentrale(daten)
            if verstoss:
                self.verstoesse.append((daten.get("message_id"), verstoss))
            reaktion = (self.reaktionen.pop(0) if self.reaktionen
                        else (200, {"status": "angenommen"}))
            if isinstance(reaktion, BaseException):
                raise reaktion
            return reaktion[0], json.dumps(reaktion[1]).encode()
        raise AssertionError(f"unerwartete Anfrage {methode} {url}")

    def ids(self):
        return [m["message_id"] for m in self.gemeldet]


@pytest.fixture
def zentrale(monkeypatch):
    z = AttrappeZentrale()
    monkeypatch.setattr(be, "URL", BASIS)
    monkeypatch.setattr(be, "KEY", SCHLUESSEL)
    monkeypatch.setattr(be, "HTTP", z)
    yield z
    assert z.verstoesse == [], "die echte Zentrale wiese diese Meldungen ab"


@pytest.fixture
def post(monkeypatch):
    """Die Sammelstelle als Attrappe: ein env-Konto (namecheap, Besitzer
    felix) ist schon da. Jedes Oeffnen eines Postfachs ist ein Testfehler."""
    s = AttrappeSammelstelle()
    monkeypatch.setattr(be, "_konten", s._konten)
    monkeypatch.setattr(be, "_mails", s._mails)
    monkeypatch.setattr(be, "_text", s._text)

    def nie(*a, **kw):
        raise AssertionError("IMAP im Bewerbungs-Eingang")
    monkeypatch.setattr(postfach, "oeffnen", nie)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", nie)
    monkeypatch.setattr(imaplib, "IMAP4", nie)
    return s


# ---------------------------------------------------------------------------
# 1. Nur passende Mails gehen hinaus
# ---------------------------------------------------------------------------

def test_nur_passende_mails_werden_gemeldet(zentrale, post):
    post.mail("HR <jobs@beispiel.de>", message_id="a@beispiel.de")
    post.mail("Team <hr@karriere.beispiel.de>", message_id="b@beispiel.de")
    post.mail("Oma <oma@web.de>", betreff="Gruesse",
              text="Wie war es bei der Beispiel GmbH?", message_id="privat@web.de")
    post.mail("Personio <no-reply@personio.de>",
              betreff="Deine Bewerbung bei Beispiel GmbH", message_id="c@personio.de")
    post.mail("Personio <no-reply@personio.de>",
              betreff="Deine Bewerbung bei Andere AG", message_id="d@personio.de")
    post.mail("Falsch <x@boese-beispiel.de>", message_id="e@boese-beispiel.de")
    post.mail("JOIN <notifications@mail.join.com>", betreff="Neuigkeiten",
              text="Nordlicht AG hat deine Bewerbung gelesen.", message_id="f@join.com")
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


def test_rumpf_folgt_dem_vertrag_v1(zentrale, post):
    post.mail("Jürgen Personal <jobs@beispiel.de>",
              betreff="Rückfrage zu Ihrer Bewerbung",
              text="Koennen Sie am Montag?", message_id="r1@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert set(rumpf) == _FELDER
    assert rumpf["postfach"] == "vibemind"
    assert rumpf["message_id"] == "<r1@beispiel.de>"
    assert rumpf["von"] == "Jürgen Personal <jobs@beispiel.de>"
    assert rumpf["an"] == "felix@vibemind.space"
    assert rumpf["betreff"] == "Rückfrage zu Ihrer Bewerbung"
    assert rumpf["text"] == "Koennen Sie am Montag?"
    assert rumpf["datum"] == "2026-10-29T09:00:05Z"      # UTC
    assert rumpf["kalender"] is None
    assert rumpf["kandidaten"] == ["bw-1"]


def test_private_mail_verlaesst_sales_claw_nie_auch_nicht_im_log(
        zentrale, post, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    post.mail("Freundin <lisa@web.de>", betreff="Geheimnis-Betreff-4711",
              text="Ich habe gehoert, du warst bei Beispiel GmbH "
                   "und Nordlicht AG. Privates Detail XYZ.",
              message_id="privat-4711@web.de")
    ergebnis = be.lauf()
    print(json.dumps(ergebnis))
    assert zentrale.gemeldet == []
    gesamt = caplog.text + capsys.readouterr().out
    for spur in ("Geheimnis-Betreff-4711", "lisa@web.de", "privat-4711",
                 "Privates Detail", "web.de"):
        assert spur not in gesamt, spur


def test_text_wird_nur_fuer_mails_geladen_die_ihn_brauchen(zentrale, post):
    """Nicht in der Massenabfrage: eine Abfrage je Zeile, und nur fuer das
    Portal-Matching und fuer die Meldung."""
    privat = post.mail("Oma <oma@web.de>", message_id="o@web")
    firma = post.mail("HR <jobs@beispiel.de>", message_id="h@beispiel.de")
    portal_ohne = post.mail("Personio <no-reply@personio.de>", betreff="Newsletter",
                            text="nichts", message_id="p1@personio.de")
    portal_mit = post.mail("Personio <no-reply@personio.de>", betreff="Update",
                           text="Nordlicht AG hat reagiert.", message_id="p2@personio.de")
    be.lauf()
    assert sorted(post.text_abgefragt) == sorted([firma, portal_ohne, portal_mit])
    assert privat not in post.text_abgefragt
    # Je Mail hoechstens eine Abfrage, auch wenn Abgleich UND Meldung den Text brauchen.
    assert len(post.text_abgefragt) == len(set(post.text_abgefragt))


def test_mail_vor_der_grenze_faellt_raus_datum_null_nimmt_gesehen_am(zentrale, post):
    post.mail("Alt <jobs@beispiel.de>", message_id="alt@beispiel.de",
              datum=datetime(2026, 10, 25, 8, tzinfo=UTC))
    post.mail("Knapp davor <jobs@beispiel.de>", message_id="knapp@beispiel.de",
              datum=datetime(2026, 10, 26, 9, 11, tzinfo=UTC))
    post.mail("Danach <jobs@beispiel.de>", message_id="danach@beispiel.de",
              datum=datetime(2026, 10, 26, 21, tzinfo=UTC))
    # Ohne Kopfdatum zaehlt gesehen_am - und taucht dann auch als `datum` auf.
    post.mail("Ohne Datum <jobs@beispiel.de>", message_id="ohne@beispiel.de",
              datum=None, gesehen_am=datetime(2026, 11, 2, 7, 30, tzinfo=UTC))
    post.mail("Ohne Datum alt <jobs@beispiel.de>", message_id="ohnealt@beispiel.de",
              datum=None, gesehen_am=datetime(2026, 10, 20, tzinfo=UTC))
    be.lauf()
    assert sorted(zentrale.ids()) == ["<danach@beispiel.de>", "<ohne@beispiel.de>"]
    nach_id = {m["message_id"]: m for m in zentrale.gemeldet}
    assert nach_id["<ohne@beispiel.de>"]["datum"] == "2026-11-02T07:30:00Z"


def test_freemail_domain_in_der_warteliste_oeffnet_keine_privaten_mails(
        zentrale, post):
    """Eine kleine Firma mit Gmail-Adresse darf nicht dazu fuehren, dass jede
    Mail von gmail.com hinausgeht. Gemeldet wird dann nur die eine Adresse."""
    zentrale.warteliste["bewerbungen"].append(
        {"application_id": "bw-3", "firma": "Baeckerei Korn",
         "domains": ["gmail.com"], "gesendet_am": "2026-10-28T09:00:00Z",
         "an": "baeckerei.korn@gmail.com"})
    zentrale.warteliste["portal_absender"].append("web.de")
    post.mail("Freund <freund@gmail.com>", message_id="f@gmail")
    post.mail("Korn <Baeckerei.Korn@gmail.com>", message_id="k@gmail")
    post.mail("Oma <oma@web.de>", text="Beispiel GmbH?", message_id="o@web")
    be.lauf()
    assert zentrale.ids() == ["<k@gmail>"]
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-3"]


def test_genaue_an_adresse_der_bewerbung_genuegt(zentrale, post):
    post.mail("Irgendwer <info@anderer-absender.example>",
              message_id="an@anderer-absender.example")
    post.mail("Karriere <KARRIERE@nordlicht.example>", message_id="an2@nordlicht.example")
    be.lauf()
    assert zentrale.ids() == ["<an2@nordlicht.example>"]


def test_firmenname_ohne_rechtsform_und_nur_als_ganzes_wort(zentrale, post):
    post.mail("Personio <no-reply@personio.de>",
              betreff="Danke fuer deine Bewerbung bei BEISPIEL",
              message_id="kern@personio.de")
    post.mail("Personio <no-reply@personio.de>",
              betreff="Beispielhafte Stellen fuer dich", message_id="wort@personio.de")
    be.lauf()
    assert zentrale.ids() == ["<kern@personio.de>"]


def test_firmenname_im_absendernamen_genuegt(zentrale, post):
    post.mail("Nordlicht AG via SmartRecruiters <no-reply@smartrecruiters.com>",
              betreff="Update", text="Status geaendert.",
              message_id="sr@smartrecruiters.com")
    be.lauf()
    assert zentrale.ids() == ["<sr@smartrecruiters.com>"]
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-2"]


def test_dreibuchstabige_firma_ohne_rechtsform(zentrale, post):
    zentrale.warteliste["bewerbungen"].append(
        {"application_id": "bw-4", "firma": "SAP SE", "domains": ["sap.example"],
         "gesendet_am": "2026-10-28T09:00:00Z", "an": "jobs@sap.example"})
    post.mail("JOIN <no-reply@join.com>", betreff="Deine Bewerbung bei SAP",
              message_id="sap@join.com")
    be.lauf()
    assert zentrale.gemeldet[0]["kandidaten"] == ["bw-4"]


def test_mail_ohne_absender_passt_nie_und_zaehlt_als_geprueft(zentrale, post):
    post.mail(None, message_id="leer@x", text="Beispiel GmbH Nordlicht AG")
    post.mail("", message_id="leer2@x")
    ergebnis = be.lauf()
    assert zentrale.gemeldet == []
    zaehler = ergebnis["postfaecher"]["vibemind"]
    assert zaehler["geprueft"] == 2 and zaehler["unlesbar"] == 0
    assert ergebnis["vollstaendig"] is True


# ---------------------------------------------------------------------------
# 2. Konten: Besitzer, aktiv, Namen
# ---------------------------------------------------------------------------

def test_fremde_und_inaktive_konten_werden_nie_gelesen_oder_gemeldet(zentrale, post):
    inaktiv = post.konto("gmail", aktiv=False)
    fremd = post.konto("gmx", besitzer="anna")
    fremd_gmail = post.konto("gmail", besitzer="anna", quelle="env")
    eigen = post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", message_id="haupt@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="inaktiv@beispiel.de", konto=inaktiv)
    post.mail("HR <jobs@beispiel.de>", message_id="fremd@beispiel.de", konto=fremd)
    post.mail("HR <jobs@beispiel.de>", message_id="fremd2@beispiel.de", konto=fremd_gmail)
    post.mail("HR <jobs@beispiel.de>", message_id="eigen@beispiel.de", konto=eigen)
    ergebnis = be.lauf()
    assert sorted(zentrale.ids()) == ["<eigen@beispiel.de>", "<haupt@beispiel.de>"]
    assert {k for k, _ in post.mails_abgefragt} == {post.haupt, eigen}
    assert {b for _, b in post.mails_abgefragt} == {"felix"}
    assert set(ergebnis["postfaecher"]) == {"vibemind", "gmx"}


def test_besitzer_des_env_kontos_zaehlt_auch_bei_anderem_namen(zentrale, post):
    """Nicht fest `felix`: der Besitzer des env-Kontos ist der Laden-Inhaber."""
    post.konten[0]["besitzer"] = "inhaber"
    for z in post.zeilen[post.haupt]:
        z["besitzer"] = "inhaber"
    felix = post.konto("gmx", besitzer="felix")
    post.mail("HR <jobs@beispiel.de>", message_id="x@beispiel.de", konto=felix)
    post.mail("HR <jobs@beispiel.de>", message_id="y@beispiel.de", besitzer="inhaber")
    be.lauf()
    assert zentrale.ids() == ["<y@beispiel.de>"]


def test_ohne_env_konto_laeuft_nichts(zentrale, post):
    post.konten[0]["quelle"] = "ui"
    post.mail("HR <jobs@beispiel.de>", message_id="a@beispiel.de")
    ergebnis = be.lauf()
    assert ergebnis["status"] == "keine postfaecher"
    assert ergebnis["vollstaendig"] is True and ergebnis["postfaecher"] == {}
    assert zentrale.gemeldet == [] and post.mails_abgefragt == []


def test_anbieter_werden_zu_den_postfach_namen_des_vertrags(zentrale, post):
    gmail = post.konto("gmail")
    gmx = post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", message_id="v@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="g@beispiel.de", konto=gmail)
    post.mail("HR <jobs@beispiel.de>", message_id="x@beispiel.de", konto=gmx)
    ergebnis = be.lauf()
    assert set(ergebnis["postfaecher"]) == {"vibemind", "gmail", "gmx"}
    nach_id = {m["message_id"]: m["postfach"] for m in zentrale.gemeldet}
    assert nach_id == {"<v@beispiel.de>": "vibemind", "<g@beispiel.de>": "gmail",
                       "<x@beispiel.de>": "gmx"}


def test_zwei_gmx_konten_bekommen_gmx_und_gmx_2_melden_aber_gmx(zentrale, post):
    eins = post.konto("gmx")
    zwei = post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", message_id="eins@beispiel.de", konto=eins)
    post.mail("HR <jobs@beispiel.de>", message_id="zwei@beispiel.de", konto=zwei)
    ergebnis = be.lauf()
    assert set(ergebnis["postfaecher"]) == {"vibemind", "gmx", "gmx-2"}
    assert ergebnis["postfaecher"]["gmx"]["passend"] == 1
    assert ergebnis["postfaecher"]["gmx-2"]["passend"] == 1
    assert [m["postfach"] for m in zentrale.gemeldet] == ["gmx", "gmx"]


# ---------------------------------------------------------------------------
# 3. Meldung: message_id, sensible Zeilen, Kalender
# ---------------------------------------------------------------------------

def test_normale_message_id_bekommt_klammern_geklammerte_bleibt(zentrale, post):
    post.mail("HR <jobs@beispiel.de>", message_id="ohne@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="<mit@beispiel.de>")
    be.lauf()
    assert zentrale.ids() == ["<ohne@beispiel.de>", "<mit@beispiel.de>"]


def test_ersatz_message_id_ist_stabil_ueber_die_zeilen_id(zentrale, post):
    m = post.mail("HR <jobs@beispiel.de>", message_id="haupt:7@sales-post", ersatz=True)
    be.lauf()
    be.lauf()
    a, b = zentrale.ids()
    assert a == b == f"<post-{m}@bewerbungs-eingang.sales-claw.invalid>"


def test_sensible_zeile_ohne_text_und_empfaenger_wird_trotzdem_gemeldet(zentrale, post):
    """Sensible Zeilen haben text NULL (und hier auch an NULL)."""
    post.mail("HR <jobs@beispiel.de>", message_id="s@beispiel.de", text=None, an=None)
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["text"] == "" and rumpf["an"] == ""
    assert rumpf["kandidaten"] == ["bw-1"]


def test_sensible_zeile_ohne_text_matcht_nie_ueber_den_text(zentrale, post):
    post.mail("Personio <no-reply@personio.de>", betreff="Update", text=None,
              message_id="pnull@personio.de")
    be.lauf()
    assert zentrale.gemeldet == []


def test_kalender_ist_in_jeder_meldung_null(zentrale, post):
    post.mail("HR <jobs@beispiel.de>", message_id="a@beispiel.de")
    post.mail("Personio <no-reply@personio.de>", betreff="Bewerbung bei Beispiel",
              message_id="b@personio.de")
    post.mail("Personal <hr@beispiel.de>", betreff="Einladung: Kennenlernen",
              message_id="ics@beispiel.de")
    be.lauf()
    assert len(zentrale.gemeldet) == 3
    assert all(m["kalender"] is None for m in zentrale.gemeldet)


def test_einladung_nur_ueber_den_organisator_passt_nicht_mehr(zentrale, post):
    """Regel (c) entfaellt: die Sammelstelle speichert nur das Flag, nicht den
    Organisator. Absender Kalenderdienst, nichts von der Firma -> draussen."""
    post.mail("Google Kalender <calendar-notification@google.com>",
              betreff="Einladung: Kennenlernen", text="Organisator: hr@beispiel.de",
              message_id="ics@google.com")
    be.lauf()
    assert zentrale.gemeldet == []


# ---------------------------------------------------------------------------
# 3a. Grenzen der echten Zentrale (13.11.2026): was dort eine 422 waere, ist
#     eine verlorene Antwort. Das Fixture `zentrale` prueft jede Meldung.
# ---------------------------------------------------------------------------

def test_lange_empfaengerliste_passt_in_die_grenze_der_zentrale(zentrale, post):
    """Eine Einladung an viele Teilnehmer: der ganze To-Kopf laege ueber 320
    Zeichen. Gemeldet werden die blanken Adressen, so viele wie passen."""
    teilnehmer = [f"Teilnehmerin Nummer {i} <teilnehmerin.{i}@beispiel.de>"
                  for i in range(12)]
    post.mail("HR <hr@beispiel.de>", an=", ".join(teilnehmer + ["felix@vibemind.space"]),
              message_id="viele@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    adressen = rumpf["an"].split(", ")
    assert adressen[0] == "teilnehmerin.0@beispiel.de"
    assert all(re.fullmatch(r"teilnehmerin\.\d+@beispiel\.de", a) for a in adressen)
    assert len(adressen) >= 5


def test_kurze_empfaengerliste_bleibt_wie_sie_ist(zentrale, post):
    post.mail("HR <hr@beispiel.de>",
              an="Felix Baumann <felix@vibemind.space>, Team <team@beispiel.de>",
              message_id="zwei@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["an"] == "Felix Baumann <felix@vibemind.space>, Team <team@beispiel.de>"


def test_ueberlanger_absendername_kostet_die_mail_nicht(zentrale, post):
    von = "Personalabteilung " + "mit sehr langem Namen " * 20 + "<jobs@beispiel.de>"
    post.mail(von, message_id="lang@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["von"] == "jobs@beispiel.de"
    assert rumpf["kandidaten"] == ["bw-1"]


def test_ueberlanger_betreff_wird_gekuerzt(zentrale, post):
    post.mail("HR <hr@beispiel.de>", betreff="Ihre Bewerbung " + "bei uns " * 200,
              message_id="betreff@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert len(rumpf["betreff"]) == 998
    assert rumpf["betreff"].startswith("Ihre Bewerbung bei uns bei uns")
    assert "\n" not in rumpf["betreff"]


def test_text_wird_auf_20000_zeichen_gekuerzt(zentrale, post):
    post.mail("HR <jobs@beispiel.de>", text="Sehr geehrter Herr Baumann,\n" + "x" * 30000)
    be.lauf()
    text = zentrale.gemeldet[0]["text"]
    assert len(text) == 20000 and text.startswith("Sehr geehrter Herr Baumann,")


def test_hoechstens_zwanzig_kandidaten_je_meldung(zentrale, post):
    """25 wartende Bewerbungen bei derselben Firma; gesendet_am so, wie die
    Zentrale es speichert (+00:00 statt Z). Die am laengsten Wartenden zuerst."""
    zentrale.warteliste = {
        "stand": "2026-10-29T18:40:00+00:00",
        "bewerbungen": [
            {"application_id": f"bw-{i}", "firma": "Beispiel GmbH",
             "domains": ["beispiel.de"], "gesendet_am": "2026-10-27T09:12:00+00:00",
             "an": None}
            for i in range(25)],
        "portal_absender": ["personio.de"],
    }
    post.mail("HR <hr@beispiel.de>", message_id="zwanzig@beispiel.de")
    be.lauf()
    (rumpf,) = zentrale.gemeldet
    assert rumpf["kandidaten"] == [f"bw-{i}" for i in range(20)]


# ---------------------------------------------------------------------------
# 4. Zentrale nicht bereit, Fehler, kein Cursor
# ---------------------------------------------------------------------------

def test_netzfehler_beendet_den_lauf_der_naechste_lauf_meldet_alles_erneut(
        zentrale, post):
    gmx = post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", message_id="g@beispiel.de", konto=gmx)
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="2@beispiel.de")
    zentrale.reaktionen = [(200, {"status": "angenommen"}), be.NetzFehler("URLError")]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ergebnis["status"] == "zentrale nicht erreichbar"
    assert "<g@beispiel.de>" not in zentrale.ids()     # GMX kam nicht mehr dran

    # Kein Cursor: der naechste Lauf prueft dasselbe Fenster noch einmal; die
    # Zentrale ist idempotent und sagt "bekannt".
    zentrale.gemeldet.clear()
    zentrale.reaktionen = [(200, {"status": "bekannt"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert sorted(zentrale.ids()) == ["<1@beispiel.de>", "<2@beispiel.de>",
                                      "<g@beispiel.de>"]
    assert ergebnis["postfaecher"]["vibemind"]["bekannt"] == 1


@pytest.mark.parametrize("code", [401, 403, 404, 408, 429, 500, 503])
def test_zentrale_nicht_bereit_bricht_ab_statt_mails_zu_verlieren(zentrale, post, code):
    """Ein falscher Schluessel, ein fehlender Endpunkt oder eine ueberlastete
    Zentrale lehnt nicht DIESE Mail ab, sondern jede: der Lauf endet."""
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="2@beispiel.de")
    zentrale.reaktionen = [(code, {"detail": "nein"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is False
    assert ergebnis["status"] == "zentrale nicht bereit"
    assert len(zentrale.gemeldet) == 1


@pytest.mark.parametrize("code", [400, 409, 413, 415, 422])
def test_abgelehnte_mail_wird_protokolliert_und_der_lauf_geht_weiter(
        zentrale, post, caplog, code):
    caplog.set_level(logging.INFO)
    post.mail("HR <jobs@beispiel.de>", betreff="Betreff-Eins", message_id="1@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="2@beispiel.de")
    zentrale.reaktionen = [(code, {"detail": "kaputt"}), (200, {"status": "angenommen"})]
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert zentrale.ids() == ["<1@beispiel.de>", "<2@beispiel.de>"]
    assert ergebnis["postfaecher"]["vibemind"]["abgelehnt"] == 1
    assert ergebnis["postfaecher"]["vibemind"]["angenommen"] == 1
    assert str(code) in caplog.text and "<1@beispiel.de>" in caplog.text
    assert "Betreff-Eins" not in caplog.text


def test_trockenlauf_meldet_nichts(zentrale, post):
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    ergebnis = be.lauf(trocken=True)
    assert ergebnis["postfaecher"]["vibemind"]["passend"] == 1
    assert zentrale.gemeldet == []
    assert [a for a in zentrale.anfragen if a[0] == "POST"] == []


def test_abfrage_der_sammelstelle_scheitert_nichts_wird_gemeldet(
        zentrale, post, caplog):
    caplog.set_level(logging.DEBUG)
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    for stelle in ("konten", "mails"):
        post.fehler = {stelle: RuntimeError(f"password={KENNUNG_GMX}")}
        ergebnis = be.lauf()
        assert ergebnis["status"] == "sammelstelle nicht lesbar", stelle
        assert ergebnis["vollstaendig"] is False
        assert zentrale.gemeldet == []
        assert KENNUNG_GMX not in caplog.text and "RuntimeError" in caplog.text


def test_scheitert_nur_der_textabruf_ist_der_lauf_unvollstaendig(zentrale, post):
    """Kein stilles `unlesbar`: eine Sammelstelle, die den Text nicht liefert,
    ist ein Sammelstellen-Fehler."""
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    post.fehler = {"text": OSError("weg")}
    ergebnis = be.lauf()
    assert ergebnis["status"] == "sammelstelle nicht lesbar"
    assert ergebnis["vollstaendig"] is False and zentrale.gemeldet == []


def test_eine_unlesbare_mail_haelt_den_lauf_nicht_auf(zentrale, post, monkeypatch,
                                                      caplog):
    caplog.set_level(logging.DEBUG)
    echt = be._auswerten
    kaputt = post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    post.mail("HR <jobs@beispiel.de>", message_id="2@beispiel.de")

    def zickig(zeile, liste, name):
        if zeile["id"] == kaputt:
            raise UnicodeError("Inhalt-der-kaputten-Mail")
        return echt(zeile, liste, name)
    monkeypatch.setattr(be, "_auswerten", zickig)
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True
    assert ergebnis["postfaecher"]["vibemind"]["unlesbar"] == 1
    assert zentrale.ids() == ["<2@beispiel.de>"]
    assert "Inhalt-der-kaputten-Mail" not in caplog.text


# ---------------------------------------------------------------------------
# 5. Kein IMAP, nichts schreiben
# ---------------------------------------------------------------------------

def test_das_modul_benutzt_kein_imap(zentrale, post):
    """`post` laesst postfach.oeffnen und imaplib.IMAP4_SSL werfen - ein ganzer
    Lauf geht trotzdem durch."""
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de")
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True and zentrale.ids() == ["<1@beispiel.de>"]
    quelle = Path(be.__file__).read_text(encoding="utf-8")
    assert "imaplib" not in quelle
    assert not hasattr(be, "postfach") and not hasattr(be, "imaplib")


def test_das_modul_schreibt_nie_in_die_datenbank():
    quelle = Path(be.__file__).read_text(encoding="utf-8")
    sql = " ".join(re.findall(r"_q\(\s*(?:f?\"[^\"]*\"\s*)+", quelle)).lower()
    assert "select" in sql
    for verboten in ("insert", "update", "delete", "truncate", "alter", "drop"):
        assert not re.search(rf"\b{verboten}\b", sql), verboten


def test_leere_warteliste_fragt_die_sammelstelle_nicht(zentrale, post):
    zentrale.warteliste["bewerbungen"] = []
    post.mail("HR <jobs@beispiel.de>")
    ergebnis = be.lauf()
    assert ergebnis["vollstaendig"] is True and ergebnis["status"] == "warteliste leer"
    assert post.mails_abgefragt == [] and post.text_abgefragt == []


def test_ohne_schluessel_kein_aufruf(monkeypatch, post):
    monkeypatch.setattr(be, "URL", BASIS)
    monkeypatch.setattr(be, "KEY", "")

    def nie(*a, **kw):
        raise AssertionError("Anfrage ohne Schluessel")
    monkeypatch.setattr(be, "HTTP", nie)
    ergebnis = be.lauf()
    assert ergebnis["status"] == "nicht eingerichtet"
    assert post.mails_abgefragt == []


# ---------------------------------------------------------------------------
# 6. Geheimnisse
# ---------------------------------------------------------------------------

def test_schluessel_und_kennungen_erscheinen_nicht_im_log(zentrale, post, monkeypatch,
                                                          caplog, capsys):
    caplog.set_level(logging.DEBUG)
    gmx = post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", message_id="1@beispiel.de", konto=gmx)
    post.mail("HR <jobs@beispiel.de>", message_id="2@beispiel.de")
    zentrale.reaktionen = [(200, {"status": "angenommen"}),
                           ValueError(f"header {SCHLUESSEL} kaputt")]
    # main() haengt einen eigenen stdout-Handler an (propagate aus) - fuer
    # diesen Test, danach zurueck, damit caplog in anderen Tests sieht.
    monkeypatch.setattr(be.LOG, "handlers", [])
    monkeypatch.setattr(be.LOG, "propagate", True)
    monkeypatch.setattr(be.LOG, "level", logging.NOTSET)
    rc = be.main(["lauf"])
    assert rc == 1
    gesamt = caplog.text + "".join(capsys.readouterr())
    for geheim in (SCHLUESSEL, ADRESSE_GMX, KENNUNG_GMX):
        assert geheim not in gesamt, geheim


def test_ergebnis_und_log_enthalten_nur_zahlen_und_feste_woerter(zentrale, post, caplog):
    caplog.set_level(logging.DEBUG)
    post.konto("gmx")
    post.mail("HR <jobs@beispiel.de>", betreff="Betreff-geheim", text="Text-geheim",
              message_id="1@beispiel.de")
    ergebnis = be.lauf()
    ausgabe = json.dumps(ergebnis) + caplog.text
    for spur in ("jobs@beispiel.de", "Betreff-geheim", "Text-geheim", "felix", "k1", "k2"):
        assert spur not in ausgabe, spur
    for zaehler in ergebnis["postfaecher"].values():
        assert set(zaehler) == {"status", "geprueft", "passend", "angenommen",
                                "bekannt", "abgelehnt", "unlesbar"}


# ---------------------------------------------------------------------------
# 7. Die echten Abfragen gegen sales_test
# ---------------------------------------------------------------------------

def test_echte_abfragen_besitzer_aktiv_grenze_gegen_sales_test(zentrale, monkeypatch):
    if not os.environ.get("SALES_DB_URL"):
        pytest.skip("keine Datenbank (SALES_DB_URL)")
    import server
    assert server.SCHEMA == "sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_mails, sales_test.post_konten cascade")
    leeren()
    try:
        def konto(kennung, anbieter, besitzer, quelle, aktiv, minute):
            return str(server._q(
                "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle, "
                "aktiv, angelegt_am) values (%s, %s, %s, %s, %s, %s, "
                "'2026-10-01 10:00+00'::timestamptz + make_interval(mins => %s)) "
                "returning id",
                (besitzer, kennung, anbieter, f"{kennung}@adresse.test", quelle, aktiv,
                 minute))[0]["id"])
        nr = itertools.count(1)

        def mail(konto_id, besitzer, message_id, datum, gesehen="2026-11-01 10:00+00",
                 text="Mailtext", von="HR <jobs@beispiel.de>", an="felix@vibemind.space",
                 ersatz=False):
            return str(server._q(
                "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, an, "
                "betreff, datum, text, gesehen_am, message_id_ersatz) values "
                "(%s, %s, %s, %s, %s, %s, 'Betreff', %s, %s, %s, %s) returning id",
                (konto_id, next(nr), message_id, besitzer, von, an, datum, text, gesehen,
                 ersatz))[0]["id"])
        env = konto("env-haupt", "namecheap", "felix", "env", True, 1)
        gmx = konto("ui-gmx", "gmx", "felix", "ui", True, 2)
        gmx2 = konto("ui-gmx-2", "gmx", "felix", "ui", True, 3)
        inaktiv = konto("ui-gmail", "gmail", "felix", "ui", False, 4)
        fremd = konto("ui-anna", "gmx", "anna", "ui", True, 5)
        mail(env, "felix", "im-fenster@beispiel.de", "2026-10-29 09:00:05+00")
        mail(env, "felix", "vor-grenze@beispiel.de", "2026-10-26 09:11:59+00")
        mail(env, "felix", "ohne-datum-neu@beispiel.de", None, gesehen="2026-11-02 07:30+00")
        mail(env, "felix", "ohne-datum-alt@beispiel.de", None, gesehen="2026-10-20 07:30+00")
        mail(env, "anna", "falscher-besitzer@beispiel.de", "2026-10-29 09:00:05+00")
        mail(gmx, "felix", "gmx@beispiel.de", "2026-10-29 09:00:05+00")
        sensibel = mail(gmx2, "felix", "sensibel@beispiel.de", "2026-10-29 09:00:05+00",
                        text=None, an=None)
        mail(inaktiv, "felix", "inaktiv@beispiel.de", "2026-10-29 09:00:05+00")
        mail(fremd, "anna", "fremd@beispiel.de", "2026-10-29 09:00:05+00")
        mail(gmx, "felix", "ohne-von@beispiel.de", "2026-10-29 09:00:05+00", von=None)

        konten = be._konten()
        assert all(not (set(k) & {"kennung", "adresse", "zugang_versiegelt"})
                   for k in konten)
        mails = be._mails(env, "felix", GRENZE)
        assert sorted(m["message_id"] for m in mails) == [
            "im-fenster@beispiel.de", "ohne-datum-neu@beispiel.de"]
        assert all("text" not in m for m in mails)
        assert be._text([m["id"] for m in mails if m["message_id"].startswith("im-")][0]) \
            == "Mailtext"
        assert be._text(sensibel) is None

        ergebnis = be.lauf()
        assert ergebnis["vollstaendig"] is True
        assert set(ergebnis["postfaecher"]) == {"vibemind", "gmx", "gmx-2"}
        assert sorted(zentrale.ids()) == sorted([
            "<im-fenster@beispiel.de>", "<ohne-datum-neu@beispiel.de>",
            "<gmx@beispiel.de>", "<sensibel@beispiel.de>"])
        nach_id = {m["message_id"]: m for m in zentrale.gemeldet}
        assert nach_id["<sensibel@beispiel.de>"]["text"] == ""
        assert nach_id["<sensibel@beispiel.de>"]["an"] == ""
        assert nach_id["<sensibel@beispiel.de>"]["postfach"] == "gmx"
        assert nach_id["<ohne-datum-neu@beispiel.de>"]["datum"] == "2026-11-02T07:30:00Z"
        assert ergebnis["postfaecher"]["gmx"]["geprueft"] == 2   # auch die Mail ohne von
    finally:
        leeren()


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
