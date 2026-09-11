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
import email.message
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


# ---------------------------------------------------------------------------
# Antworten auf Einladungen (Aufgabe 4, 11.09.2026) — eigene Tests, der Brief
# gab fuer diesen Schritt keinen Testcode vor (anders als Schritt 1). Das
# Postfach bleibt beim IMAP rein lesend; diese Faelle pruefen nur, dass eine
# erkannte Kalenderantwort als Aktivitaet an der eigenen Datenbank landet —
# keine IMAP-Schreiboperation.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads cascade")
    yield


def _lead(name="Ivan", email_adresse="ivan@vibemind.space"):
    return str(server._q(
        "insert into leads (name, email, phone, source) values "
        "(%s, %s, '+491701234567', 'whatsapp') returning id",
        (name, email_adresse))[0]["id"])


def _antwort_mail(status="ACCEPTED", teilnehmer="ivan@vibemind.space",
                  grund="", uid="abc-123",
                  von="Ivan Beispiel <ivan@vibemind.space>"):
    """Eine Mail mit einem `text/calendar`-Teil (METHOD:REPLY) — die
    Antwort auf eine Einladung, so wie ein Mailprogramm sie tatsaechlich
    verschickt: der Kalenderteil ist ein eigener MIME-Teil, kein Anhang
    im Sinne von medien.py (analog mail_dispatch.nachricht_mit_einladung,
    die ihn beim Versand ebenso als Teil anhaengt, nicht als Attachment
    im UI-Sinn)."""
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
           f"UID:{uid}\r\nSEQUENCE:0\r\n"
           f"ATTENDEE;PARTSTAT={status}:mailto:{teilnehmer}\r\n"
           + (f"COMMENT:{grund}\r\n" if grund else "") +
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    nachricht = email.message.EmailMessage()
    nachricht["From"] = von
    nachricht["To"] = "buero@vibemind.space"
    nachricht["Subject"] = "Terminvorschlag: Erstgespräch"
    nachricht["Date"] = "Mon, 31 Aug 2026 10:00:00 +0200"
    nachricht.set_content("Siehe Kalenderantwort im Anhang.")
    nachricht.add_attachment(ics.encode("utf-8"), maintype="text",
                             subtype="calendar", filename="reply.ics")
    return nachricht.as_bytes()


def test_zusage_wird_als_aktivitaet_am_kontakt_festgehalten(stub):
    lead_id = _lead()
    stub.mails[b"5"] = _antwort_mail(status="ACCEPTED")
    antwort = json.loads(server.postfach_mail_lesen("5"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, zeilen
    payload = zeilen[0]["payload"]
    assert payload["status"] == "ACCEPTED"
    assert payload["teilnehmer"] == "ivan@vibemind.space"
    assert payload["uid"] == "abc-123"


def test_absage_traegt_den_grund_in_die_aktivitaet(stub):
    lead_id = _lead()
    stub.mails[b"6"] = _antwort_mail(
        status="DECLINED", grund="Bin an dem Tag beim Kunden in München")
    server.postfach_mail_lesen("6")
    zeile = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))[0]
    assert zeile["payload"]["status"] == "DECLINED"
    assert "beim Kunden in München" in zeile["payload"]["grund"]


def test_mehrfaches_lesen_derselben_mail_erzeugt_keine_dublette(stub):
    """`lesen()` ist ein reiner Lesevorgang und darf beliebig oft aufgerufen
    werden (z. B. wenn der Betreiber dieselbe Mail zweimal oeffnet) — jeder
    Aufruf darf trotzdem hoechstens EINE Aktivitaet pro Antwort erzeugen."""
    lead_id = _lead()
    stub.mails[b"7"] = _antwort_mail(status="ACCEPTED")
    server.postfach_mail_lesen("7")
    server.postfach_mail_lesen("7")
    zeilen = server._q(
        "select id from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, zeilen


def test_unterschiedliche_begruendung_bei_gleichem_status_bleibt_erhalten(stub):
    """Fix-Runde 1 (Koordinator): sagt jemand zuerst kurz ab ('kann nicht')
    und schickt kurz darauf eine ausfuehrlichere Begruendung nach (gleicher
    Status, gleiche SEQUENCE) — beide Zeilen bleiben erhalten. Der Grund ist
    der Teil, wegen dem der Betreiber ueberhaupt hinsieht; ein Dedup allein
    ueber Status/Folge wuerde die zweite, brauchbarere Begruendung
    verschlucken."""
    lead_id = _lead()
    stub.mails[b"10"] = _antwort_mail(
        status="DECLINED", grund="kann nicht", uid="uid-1")
    stub.mails[b"11"] = _antwort_mail(
        status="DECLINED",
        grund="bin die Woche beim Kunden in München, ab der 15. wieder da",
        uid="uid-1")
    server.postfach_mail_lesen("10")
    server.postfach_mail_lesen("11")
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 2, zeilen
    gruende = {z["payload"]["grund"] for z in zeilen}
    assert gruende == {
        "kann nicht",
        "bin die Woche beim Kunden in München, ab der 15. wieder da"}


def _antwort_mail_mehrere(teilnehmer, von, uid="abc-123", grund=""):
    """Wie `_antwort_mail`, aber mit MEHREREN ATTENDEE-Zeilen — simuliert
    ein Mailprogramm, das bei einer Antwort auf eine Einladung an mehrere
    die komplette urspruengliche Liste zurueckspiegelt und nur EINEN
    Status aendert. `teilnehmer` ist eine Liste von (adresse, status)."""
    attendee_zeilen = "".join(
        f"ATTENDEE;PARTSTAT={status}:mailto:{adresse}\r\n"
        for adresse, status in teilnehmer)
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
           f"UID:{uid}\r\nSEQUENCE:0\r\n" + attendee_zeilen
           + (f"COMMENT:{grund}\r\n" if grund else "") +
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    nachricht = email.message.EmailMessage()
    nachricht["From"] = von
    nachricht["To"] = "buero@vibemind.space"
    nachricht["Subject"] = "Terminvorschlag: Erstgespräch"
    nachricht["Date"] = "Mon, 31 Aug 2026 10:00:00 +0200"
    nachricht.set_content("Siehe Kalenderantwort im Anhang.")
    nachricht.add_attachment(ics.encode("utf-8"), maintype="text",
                             subtype="calendar", filename="reply.ics")
    return nachricht.as_bytes()


def test_antwort_mit_mehreren_teilnehmern_waehlt_ueber_absender(stub):
    """Fix-Runde 2 (Koordinator, Mangel 1): die erste ATTENDEE-Zeile ist
    NICHT zwingend die des Antwortenden — hier steht sie an dritter
    Stelle, mit den ersten beiden auf NEEDS-ACTION (unveraendert). Der
    Absender der Mail IST der Antwortende; darueber, nicht ueber die
    Zeilenreihenfolge, muss die Aktivitaet zugeordnet werden."""
    lead_id = _lead()
    stub.mails[b"12"] = _antwort_mail_mehrere(
        von="Ivan Beispiel <ivan@vibemind.space>",
        teilnehmer=[
            ("felix@vibemind.space", "NEEDS-ACTION"),
            ("kunde@beispiel.de", "NEEDS-ACTION"),
            ("ivan@vibemind.space", "DECLINED"),
        ])
    antwort = json.loads(server.postfach_mail_lesen("12"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, zeilen
    payload = zeilen[0]["payload"]
    assert payload["teilnehmer"] == "ivan@vibemind.space"
    assert payload["status"] == "DECLINED"
    # Auch das zurueckgegebene Volltext-Ergebnis traegt die richtige Wahl,
    # nicht bloss die erste Zeile der ICS-Datei:
    assert antwort["kalender_antwort"]["teilnehmer"] == "ivan@vibemind.space"
    assert antwort["kalender_antwort"]["status"] == "DECLINED"


def test_antwort_waehlt_ueber_absender_trotz_gross_kleinschreibung(stub):
    """Fix-Runde 3 (Koordinator): viele Mailanbieter normalisieren nur die
    Domaene, nicht den lokalen Teil — eine abweichende Schreibweise
    zwischen dem `From`-Header und der `mailto:`-Zeile in der ICS-Datei
    ist deshalb Alltag, kein Sonderfall. Der Adressvergleich darf daran
    nicht scheitern, sonst greift wieder der (jetzt abgeschaffte)
    Rueckfall auf die erste Zeile."""
    lead_id = _lead()
    stub.mails[b"16"] = _antwort_mail_mehrere(
        von="Ivan Beispiel <Ivan@Vibemind.Space>",
        teilnehmer=[
            ("felix@vibemind.space", "NEEDS-ACTION"),
            ("ivan@vibemind.space", "DECLINED"),
        ])
    server.postfach_mail_lesen("16")
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, zeilen
    assert zeilen[0]["payload"]["teilnehmer"] == "ivan@vibemind.space"
    assert zeilen[0]["payload"]["status"] == "DECLINED"


def test_antwort_ohne_passenden_teilnehmer_erzeugt_keine_aktivitaet(stub):
    """Fix-Runde 3 (Koordinator): kein Rueckfall mehr auf die erste Zeile.
    Felix ist absichtlich ein ECHTER Kontakt — mit dem alten Rueckfall
    (erste Zeile mit nichtleerem Status) waere hier eine Aktivitaet unter
    SEINEM Namen entstanden, obwohl die Mail von einer ganz anderen
    Adresse kam. Lieber gar keine Aktivitaet als eine falsche."""
    _lead(name="Felix", email_adresse="felix@vibemind.space")
    stub.mails[b"17"] = _antwort_mail_mehrere(
        von="Fremde Adresse <fremd@nirgendwo.de>",
        teilnehmer=[
            ("felix@vibemind.space", "NEEDS-ACTION"),
            ("ivan@vibemind.space", "DECLINED"),
        ])
    antwort = json.loads(server.postfach_mail_lesen("17"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select id from activities where type = 'einladung_antwort'")
    assert zeilen == [], zeilen


def test_antwort_ohne_partstat_erzeugt_keine_aktivitaet(stub):
    """Fix-Runde 2 (Koordinator, Mangel 2): fehlt PARTSTAT in der
    ATTENDEE-Zeile, bleibt `status` leer — ein leerer Status ist in
    Aufgabe 6 nicht uebersetzbar (keine Zuordnung Status->Text) und darf
    nicht als Aktivitaet landen."""
    lead_id = _lead()
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
           "UID:abc-123\r\nSEQUENCE:0\r\n"
           "ATTENDEE:mailto:ivan@vibemind.space\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    nachricht = email.message.EmailMessage()
    nachricht["From"] = "Ivan Beispiel <ivan@vibemind.space>"
    nachricht["To"] = "buero@vibemind.space"
    nachricht["Subject"] = "Terminvorschlag: Erstgespräch"
    nachricht["Date"] = "Mon, 31 Aug 2026 10:00:00 +0200"
    nachricht.set_content("Siehe Kalenderantwort im Anhang.")
    nachricht.add_attachment(ics.encode("utf-8"), maintype="text",
                             subtype="calendar", filename="reply.ics")
    stub.mails[b"13"] = nachricht.as_bytes()
    antwort = json.loads(server.postfach_mail_lesen("13"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select id from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert zeilen == [], zeilen


def test_unbekannter_teilnehmer_erzeugt_keine_aktivitaet(stub):
    """Eine Antwort von einer Adresse ohne zugehoerigen Kontakt laesst sich
    niemandem zuordnen — es entsteht keine Aktivitaet, aber auch kein
    Fehler."""
    stub.mails[b"8"] = _antwort_mail(teilnehmer="unbekannt@nirgendwo.de")
    antwort = json.loads(server.postfach_mail_lesen("8"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select id from activities where type = 'einladung_antwort'")
    assert zeilen == []


def test_mail_ohne_kalenderteil_bleibt_unberuehrt(stub):
    """Die bestehenden Stub-Mails ohne `text/calendar`-Teil (z. B. uid '1')
    duerfen unter keinen Umstaenden eine Aktivitaet erzeugen."""
    server.postfach_mail_lesen("1")
    zeilen = server._q(
        "select id from activities where type = 'einladung_antwort'")
    assert zeilen == []


def test_einladung_ist_keine_antwort_im_postfach(stub):
    """Eine REQUEST-Datei (die eigene ausgehende Einladung, faelschlich im
    Posteingang) darf ebenfalls keine Aktivitaet erzeugen — derselbe
    Vertrag wie `kalender.ics_antwort_lesen` selbst."""
    import kalender
    from datetime import datetime
    einladung = kalender.ics_einladung(
        "xyz-999", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"])
    nachricht = email.message.EmailMessage()
    nachricht["From"] = "Felix <felix@vibemind.space>"
    nachricht["To"] = "buero@vibemind.space"
    nachricht["Subject"] = "Terminvorschlag: Erstgespräch"
    nachricht["Date"] = "Mon, 31 Aug 2026 10:00:00 +0200"
    nachricht.set_content("Einladung im Anhang.")
    nachricht.add_attachment(einladung.encode("utf-8"), maintype="text",
                             subtype="calendar", filename="invite.ics")
    stub.mails[b"9"] = nachricht.as_bytes()
    server.postfach_mail_lesen("9")
    zeilen = server._q(
        "select id from activities where type = 'einladung_antwort'")
    assert zeilen == []
