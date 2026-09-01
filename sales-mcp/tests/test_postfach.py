"""Vertragstests fuer das Postfach-Lesen (IMAP, 31.08.2026).

Der Assistent darf das Betreiber-Postfach LESEN — nie veraendern. Drei
Saetze, die diese Suite verteidigt:

1. Jede Verbindung oeffnet den Ordner READONLY — kein \\Seen-Flag, kein
   Loeschen, kein Verschieben, unter keinen Umstaenden.
2. Mailinhalte sind FREMDDATEN: Header werden dekodiert und gedeckelt,
   HTML wird zu Text gestrippt, nichts davon ist je eine Anweisung.
3. Fehlt die Konfiguration oder scheitert die Verbindung, kommt ein
   lesbarer Fehler ohne Zugangsdaten-Details.

Getestet wird gegen einen Stub (Muster test_mail_dispatch: kein echter
Server in der Suite); die Live-Verbindung misst der Rollout.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import postfach  # noqa: E402
import server  # noqa: E402


def _mail(von="Anna Beispiel <anna@beispiel.org>", betreff="Hallo",
          text="Erste Zeile.\nZweite Zeile.", html=None):
    if html is not None:
        rumpf = ('Content-Type: text/html; charset="utf-8"\r\n\r\n' + html)
    else:
        rumpf = ('Content-Type: text/plain; charset="utf-8"\r\n\r\n' + text)
    kopf = (f"From: {von}\r\nTo: ich@beispiel.org\r\n"
            f"Subject: {betreff}\r\n"
            f"Date: Mon, 31 Aug 2026 10:00:00 +0200\r\n")
    return (kopf + rumpf).encode("utf-8")


class StubImap:
    """Merkt sich, WIE er benutzt wurde — die Vertraege lesen das aus."""

    def __init__(self, mails):
        self.mails = mails            # uid(bytes) -> rfc822(bytes)
        self.select_aufrufe = []
        self.logout_gerufen = False

    def select(self, ordner, readonly=False):
        self.select_aufrufe.append((ordner, readonly))
        return "OK", [str(len(self.mails)).encode()]

    def uid(self, befehl, *args):
        if befehl == "search":
            return "OK", [b" ".join(sorted(self.mails))]
        if befehl == "fetch":
            uid = args[0]
            if uid not in self.mails:
                return "NO", [None]
            return "OK", [(uid + b" (RFC822 ...)", self.mails[uid])]
        raise AssertionError(f"unerwarteter Befehl {befehl}")

    def logout(self):
        self.logout_gerufen = True
        return "BYE", []


@pytest.fixture
def stub(monkeypatch):
    # Die Suite laeuft ohne SMTP/IMAP-Umgebung — konfiguriert() waere
    # False und jedes Werkzeug bliebe im Konfigurationsfehler stecken.
    monkeypatch.setattr(postfach, "IMAP_HOST", "imap.test.invalid")
    monkeypatch.setattr(postfach, "IMAP_USER", "test@test.invalid")
    kasten = StubImap({
        b"1": _mail(betreff="Alte Mail", text="Inhalt eins."),
        b"2": _mail(von="=?utf-8?b?SsO2cmc=?= <j@beispiel.org>",
                    betreff="=?utf-8?b?UsO8Y2tmcmFnZQ==?=",
                    text="Bitte um Antwort."),
        b"3": _mail(betreff="Neueste", text="Inhalt drei. " + "x" * 500),
    })
    monkeypatch.setattr(postfach, "_verbinden", lambda: kasten)
    return kasten


# ---------------------------------------------------------------------------
# Lesen: Liste und Volltext
# ---------------------------------------------------------------------------

def test_liste_neueste_zuerst_mit_dekodierten_koepfen(stub):
    antwort = json.loads(server.postfach_lesen(anzahl=10))
    assert "fehler" not in antwort
    mails = antwort["mails"]
    assert [m["uid"] for m in mails] == ["3", "2", "1"]
    assert mails[1]["von"] == "Jörg <j@beispiel.org>"
    assert mails[1]["betreff"] == "Rückfrage"
    assert "Bitte um Antwort." in mails[1]["auszug"]


def test_auszug_ist_gedeckelt(stub):
    mails = json.loads(server.postfach_lesen())["mails"]
    neueste = mails[0]
    assert len(neueste["auszug"]) <= postfach.AUSZUG_MAX + 1  # + Ellipse


def test_anzahl_wird_gedeckelt(stub):
    antwort = json.loads(server.postfach_lesen(anzahl=99999))
    assert len(antwort["mails"]) == 3   # mehr gibt es nicht — kein Fehler


def test_volltext_einer_mail(stub):
    antwort = json.loads(server.postfach_mail_lesen("2"))
    assert "fehler" not in antwort
    assert antwort["betreff"] == "Rückfrage"
    assert antwort["text"] == "Bitte um Antwort."


def test_html_mail_wird_zu_text_gestrippt(stub, monkeypatch):
    stub.mails[b"4"] = _mail(betreff="HTML",
                             html="<p>Hallo <b>Welt</b></p>"
                                  "<script>boese()</script>")
    antwort = json.loads(server.postfach_mail_lesen("4"))
    assert "<p>" not in antwort["text"] and "<script>" not in antwort["text"]
    assert "Hallo" in antwort["text"] and "Welt" in antwort["text"]


def test_unbekannte_uid_ist_eine_meldung(stub):
    antwort = json.loads(server.postfach_mail_lesen("999"))
    assert "fehler" in antwort


# ---------------------------------------------------------------------------
# Die Leitplanken
# ---------------------------------------------------------------------------

def test_jede_verbindung_oeffnet_readonly(stub):
    server.postfach_lesen()
    server.postfach_mail_lesen("1")
    assert stub.select_aufrufe, "select wurde nie gerufen"
    assert all(readonly is True for _, readonly in stub.select_aufrufe)


def test_verbindung_wird_wieder_geschlossen(stub):
    server.postfach_lesen()
    assert stub.logout_gerufen


def test_ohne_konfiguration_lesbarer_fehler(monkeypatch):
    monkeypatch.setattr(postfach, "IMAP_HOST", "")
    antwort = json.loads(server.postfach_lesen())
    assert "fehler" in antwort
    assert "IMAP" in antwort["fehler"]


def test_verbindungsfehler_wird_zur_meldung(monkeypatch):
    def kaputt():
        raise OSError("connection refused")
    monkeypatch.setattr(postfach, "_verbinden", kaputt)
    antwort = json.loads(server.postfach_lesen())
    assert "fehler" in antwort
