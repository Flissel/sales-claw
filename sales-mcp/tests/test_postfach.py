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


def test_liste_markiert_mails_mit_kalenderteil(stub):
    """W1 (Schlusspruefung, 11.09.2026): `liste()` wertete den Kalenderteil
    bisher GAR NICHT aus — eine Antwort auf eine Einladung war nur
    auffindbar, wenn jemand GENAU diese Mail von Hand oeffnete, und nichts
    in der Liste wies darauf hin, dass es sie ueberhaupt gibt. `kalenderteil`
    markiert nur die ANWESENHEIT des `text/calendar`-Teils — keine
    Auswertung, die bleibt `lesen()` vorbehalten."""
    stub.mails[b"4"] = _antwort_mail(status="ACCEPTED", uid="abc-123")
    antwort = json.loads(server.postfach_lesen(anzahl=10))
    assert "fehler" not in antwort, antwort
    mails = {m["uid"]: m for m in antwort["mails"]}
    assert set(mails) == {"1", "2", "3", "4"}
    assert mails["4"]["kalenderteil"] is True
    assert mails["1"]["kalenderteil"] is False
    assert mails["2"]["kalenderteil"] is False
    assert mails["3"]["kalenderteil"] is False


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


def test_antwort_findet_kontakt_trotz_abweichender_schreibweise_in_db(stub):
    """W2 (Schlusspruefung, 11.09.2026): der Kontakt-Lookup in
    `_antwort_festhalten` verglich bisher exakt (`where email = %s`) — ohne
    Normalisierung, obwohl `_normalisierte_adresse` zwei Funktionen weiter
    oben genau dafuer gebaut wurde (`_passenden_teilnehmer_waehlen` nutzt
    sie laengst fuer den Vergleich ATTENDEE<->From). Hier: der Kontakt
    steht GROSSGESCHRIEBEN in der DB, die Kalenderdatei traegt ihn
    kleingeschrieben."""
    lead_id = _lead(email_adresse="IVAN@VIBEMIND.SPACE")
    stub.mails[b"9"] = _antwort_mail(status="ACCEPTED",
                                     teilnehmer="ivan@vibemind.space",
                                     uid="abc-321")
    antwort = json.loads(server.postfach_mail_lesen("9"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, (
        "Kontakt wurde trotz Normalisierungs-Helfer nicht gefunden — "
        "exakter Stringvergleich statt lower(trim(email)).")
    assert zeilen[0]["payload"]["status"] == "ACCEPTED"


def test_antwort_bei_mehreren_treffern_waehlt_deterministisch_denselben_kontakt(
        stub):
    """W2: `leads[0]` ohne ORDER BY haengt von der (unspezifizierten)
    Rueckgabereihenfolge der Datenbank ab — zwei unabhaengige Antworten an
    dieselbe (normalisierte) Adresse duerften nicht mal beim einen, mal
    beim anderen Kontakt landen. Es kommt hier nicht darauf an, WELCHER der
    beiden Kontakte gewaehlt wird, nur dass es IMMER derselbe ist.

    Ehrlicher Befund zu diesem Test: er ist GRUEN, auch gegen den ALTEN
    Code (dort liefert PostgreSQL fuer diese einfache, unveraenderte
    Abfrage in der Praxis stabil die Einfuegereihenfolge zurueck — das ist
    Zufall der Implementierung, kein garantiertes Verhalten der Norm). Er
    ist damit kein echter RED-Beleg fuer die Nichtdeterminismus-Behauptung,
    sondern eine REGRESSIONSSICHERUNG: das explizite `order by created_at
    desc, id desc` im Fix macht das Verhalten GARANTIERT statt zufaellig
    richtig — dieser Test haelt genau das fest, damit ein kuenftiges
    Entfernen der ORDER BY (z. B. bei einer Umformulierung der Abfrage)
    auffiele, auch wenn es lokal zufaellig weiter gruen bliebe."""
    erster = _lead(name="Ivan Alt", email_adresse="ivan@vibemind.space")
    zweiter = _lead(name="Ivan Neu", email_adresse="IVAN@VIBEMIND.SPACE")

    stub.mails[b"10"] = _antwort_mail(status="ACCEPTED", uid="abc-701")
    stub.mails[b"11"] = _antwort_mail(status="DECLINED", uid="abc-702")
    antwort1 = json.loads(server.postfach_mail_lesen("10"))
    antwort2 = json.loads(server.postfach_mail_lesen("11"))
    assert "fehler" not in antwort1, antwort1
    assert "fehler" not in antwort2, antwort2

    treffer1 = server._q(
        "select lead_id from activities where type = 'einladung_antwort' "
        "and payload->>'uid' = 'abc-701'")
    treffer2 = server._q(
        "select lead_id from activities where type = 'einladung_antwort' "
        "and payload->>'uid' = 'abc-702'")
    assert len(treffer1) == 1 and len(treffer2) == 1
    gefunden1 = str(treffer1[0]["lead_id"])
    gefunden2 = str(treffer2[0]["lead_id"])
    assert gefunden1 in (erster, zweiter)
    assert gefunden1 == gefunden2, (
        "zwei unabhaengige Antworten an dieselbe (normalisierte) Adresse "
        "landeten bei VERSCHIEDENEN Kontakten — nicht deterministisch.")


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


# ---------------------------------------------------------------------------
# Gegenvorschlaege (Aufgabe 5, 11.09.2026) — METHOD:COUNTER traegt einen
# konkreten neuen Zeitpunkt. Der Bot nimmt ihn nicht an: er legt eine
# Wiedervorlage an, dasselbe Muster wie die Terminerinnerung von
# `termin_bestaetigen`. Automatisch entsteht keine Zusage, keine neue
# Einladung, kein Kalendereintrag.
# ---------------------------------------------------------------------------

def _gegenvorschlag_mail(teilnehmer="ivan@vibemind.space",
                         von="Ivan Beispiel <ivan@vibemind.space>",
                         uid="abc-123", folge=0, grund="",
                         dtstart="20261002T160000"):
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:COUNTER\r\n"
           "BEGIN:VEVENT\r\n"
           f"UID:{uid}\r\nSEQUENCE:{folge}\r\n"
           f"DTSTART;TZID=Europe/Berlin:{dtstart}\r\n"
           f"ATTENDEE;PARTSTAT=DECLINED:mailto:{teilnehmer}\r\n"
           + (f"COMMENT:{grund}\r\n" if grund else "") +
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    nachricht = email.message.EmailMessage()
    nachricht["From"] = von
    nachricht["To"] = "buero@vibemind.space"
    nachricht["Subject"] = "Re: Terminvorschlag: Erstgespräch"
    nachricht["Date"] = "Mon, 31 Aug 2026 10:00:00 +0200"
    nachricht.set_content("Siehe Gegenvorschlag im Anhang.")
    nachricht.add_attachment(ics.encode("utf-8"), maintype="text",
                             subtype="calendar", filename="counter.ics")
    return nachricht.as_bytes()


def test_gegenvorschlag_legt_wiedervorlage_fuer_den_betreiber_an(stub):
    """Der eigentliche Zweck dieser Stufe: der Betreiber muss den
    Gegenvorschlag SEHEN und ihm zustimmen oder ihn ablehnen koennen — eine
    faellige Wiedervorlage ist das bestehende Muster dafuer im Projekt
    (`termin_bestaetigen`s Terminerinnerung)."""
    lead_id = _lead()
    stub.mails[b"20"] = _gegenvorschlag_mail(
        grund="Donnerstag passt besser")
    antwort = json.loads(server.postfach_mail_lesen("20"))
    assert "fehler" not in antwort, antwort
    wiedervorlagen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead_id,))
    assert len(wiedervorlagen) == 1, wiedervorlagen
    notiz = wiedervorlagen[0]["payload"]["notiz"]
    assert "ivan@vibemind.space" in notiz
    assert "02.10.2026" in notiz and "16:00" in notiz
    assert "Donnerstag passt besser" in notiz
    assert "abc-123" in notiz and "folge 1" in notiz
    # Faellig HEUTE — die Entscheidung soll sofort im Digest auftauchen,
    # nicht erst am Tag der vorgeschlagenen Zeit.
    import datetime as _dt
    heute = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    assert wiedervorlagen[0]["payload"]["faellig_am"] == heute


def test_gegenvorschlag_notiz_nennt_auch_die_alte_zeit(stub):
    """Fix-Runde 2 (Koordinator, 11.09.2026): ohne die ALTE Zeit muesste der
    Betreiber erst in der Vorgangshistorie nachsehen, wovon ueberhaupt
    verschoben wird — die Wiedervorlage soll fuer sich stehen. Die alte
    Zeit steht in der `einladung_entworfen`-Aktivitaet, die `termin_einladen`
    beim urspruenglichen Versand angelegt haette; hier direkt eingefuegt,
    ohne den ganzen Einladungsweg nachzubauen."""
    lead_id = _lead()
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_entworfen', %s::jsonb)",
        (lead_id, json.dumps({"uid": "abc-123", "datum": "2026-09-20",
                              "uhrzeit": "10:00", "folge": 0,
                              "eingeladene": ["ivan@vibemind.space"],
                              "thema": "Erstgespräch"})))
    stub.mails[b"26"] = _gegenvorschlag_mail(grund="Donnerstag passt besser")
    antwort = json.loads(server.postfach_mail_lesen("26"))
    assert "fehler" not in antwort, antwort
    notiz = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead_id,))[0]["payload"]["notiz"]
    assert "statt 20.09.2026 10:00" in notiz
    assert "jetzt 02.10.2026 16:00" in notiz


def test_gegenvorschlag_erzeugt_auch_die_einladung_antwort_aktivitaet(stub):
    """Die Wiedervorlage kommt ZUSAETZLICH zur bestehenden
    `einladung_antwort`-Aktivitaet aus Aufgabe 4 — nicht an ihrer Stelle."""
    lead_id = _lead()
    stub.mails[b"21"] = _gegenvorschlag_mail()
    server.postfach_mail_lesen("21")
    zeile = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))[0]
    assert zeile["payload"]["methode"] == "COUNTER"
    assert zeile["payload"]["neuer_beginn"] is not None


def test_mehrfaches_lesen_des_gegenvorschlags_erzeugt_keine_doppelte_wiedervorlage(stub):
    lead_id = _lead()
    stub.mails[b"22"] = _gegenvorschlag_mail()
    server.postfach_mail_lesen("22")
    server.postfach_mail_lesen("22")
    wiedervorlagen = server._q(
        "select id from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead_id,))
    assert len(wiedervorlagen) == 1, wiedervorlagen


def test_absage_ohne_gegenzeit_legt_keine_wiedervorlage_an(stub):
    """Eine normale Absage (METHOD:REPLY) ist kein Gegenvorschlag — sie
    bekommt keine Wiedervorlage, nur die Aktivitaet."""
    lead_id = _lead()
    stub.mails[b"23"] = _antwort_mail(
        status="DECLINED", grund="Bin an dem Tag beim Kunden in München")
    server.postfach_mail_lesen("23")
    wiedervorlagen = server._q(
        "select id from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead_id,))
    assert wiedervorlagen == []


def test_gegenvorschlag_ohne_passenden_teilnehmer_legt_keine_wiedervorlage_an(stub):
    """Wie bei jeder anderen Antwort: ohne zuordenbaren Kontakt entsteht
    GAR NICHTS — auch keine Wiedervorlage."""
    stub.mails[b"24"] = _gegenvorschlag_mail(
        teilnehmer="unbekannt@nirgendwo.de",
        von="Unbekannt <unbekannt@nirgendwo.de>")
    antwort = json.loads(server.postfach_mail_lesen("24"))
    assert "fehler" not in antwort, antwort
    wiedervorlagen = server._q(
        "select id from activities where type = 'wiedervorlage'")
    assert wiedervorlagen == []


# ---------------------------------------------------------------------------
# W5 (Schlusspruefung, 11.09.2026): ein Fehler BEIM Protokollieren
# (_antwort_festhalten / _gegenvorschlag_vorlegen — eigene Datenbank, kein
# IMAP) darf nicht die ganze Mailanzeige kosten und sich nicht als
# "Postfach nicht erreichbar" ausgeben — eine falsche Ursache, das Postfach
# war erreichbar.
# ---------------------------------------------------------------------------

def test_protokollierfehler_reisst_die_mailanzeige_nicht_mit(stub, monkeypatch):
    """_antwort_festhalten lief bisher OHNE eigenes Fangnetz innerhalb von
    lesen() — ein DB-Fehler dort riss die GANZE Mailanzeige mit, und
    postfach_mail_lesens breites except uebersetzte ihn zu 'Postfach nicht
    erreichbar'."""
    _lead()
    stub.mails[b"25"] = _antwort_mail(status="ACCEPTED", uid="abc-990")

    def _kaputt(antwort):
        raise RuntimeError("DB explodiert waehrend des Protokollierens")

    monkeypatch.setattr(postfach, "_antwort_festhalten", _kaputt)
    antwort = json.loads(server.postfach_mail_lesen("25"))
    assert "fehler" not in antwort, (
        f"die Mailanzeige wurde vom Protokollierfehler mitgerissen: {antwort}")
    assert antwort["betreff"] == "Terminvorschlag: Erstgespräch"
    assert antwort["kalender_antwort"]["status"] == "ACCEPTED"
    assert "protokollierfehler" in antwort, (
        "der Fehler beim Protokollieren wird nicht gemeldet — er "
        "verschwindet lautlos")
    assert "DB explodiert" not in antwort["protokollierfehler"], (
        "keine rohen Ausnahmedetails im Werkzeug-Ergebnis, nur die "
        "Fehlerklasse (Details gehoeren ins Container-Log)")


def test_gegenvorschlag_protokollierfehler_reisst_die_mailanzeige_nicht_mit(
        stub, monkeypatch):
    """Derselbe Schutz gilt fuer den ZWEITEN Protokollierschritt
    (_gegenvorschlag_vorlegen), der synchron INNERHALB von
    _antwort_festhalten laeuft — ein Fehler dort darf ebenfalls nicht die
    Mailanzeige kosten. Die erste Aktivitaet (einladung_antwort) ist zu
    diesem Zeitpunkt bereits geschrieben; nur die Wiedervorlage schlaegt
    fehl."""
    lead_id = _lead()
    stub.mails[b"26"] = _gegenvorschlag_mail(grund="Donnerstag passt besser")

    def _kaputt(*args, **kwargs):
        raise RuntimeError("Wiedervorlage explodiert")

    monkeypatch.setattr(postfach, "_gegenvorschlag_vorlegen", _kaputt)
    antwort = json.loads(server.postfach_mail_lesen("26"))
    assert "fehler" not in antwort, (
        f"die Mailanzeige wurde vom Protokollierfehler mitgerissen: {antwort}")
    assert antwort["betreff"] == "Re: Terminvorschlag: Erstgespräch"
    assert "protokollierfehler" in antwort
    # Der ERSTE Schritt (einladung_antwort) ist trotzdem durchgelaufen —
    # der Fehler traf nur den zweiten.
    zeilen = server._q(
        "select id from activities where lead_id = %s and "
        "type = 'einladung_antwort'", (lead_id,))
    assert len(zeilen) == 1, zeilen


def test_gegenvorschlag_notiz_kappt_einen_sehr_langen_grund(stub):
    """Kleinigkeit aus der Schlusspruefung (11.09.2026): der Grund ist
    Fremdtext aus der Antwortmail und ging bisher UNGEKUERZT in die
    Wiedervorlage-Notiz — ein sehr langer Grund blaeht die Tabelle."""
    lead_id = _lead()
    lang = "Kann leider nicht, " + ("weil es einen anderen Termin gibt. " * 10)
    assert len(lang) > postfach.GEGENVORSCHLAG_GRUND_MAXLAENGE, (
        "Testannahme verletzt: der Grund muesste ueber "
        "GEGENVORSCHLAG_GRUND_MAXLAENGE hinausgehen, sonst kappt der Fix "
        "gar nichts")
    stub.mails[b"27"] = _gegenvorschlag_mail(grund=lang)
    antwort = json.loads(server.postfach_mail_lesen("27"))
    assert "fehler" not in antwort, antwort
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead_id,))
    assert len(zeilen) == 1, zeilen
    notiz = zeilen[0]["payload"]["notiz"]
    assert lang not in notiz, (
        "der volle, sehr lange Grund steht ungekuerzt in der Notiz")
    gekuerzt = lang[:postfach.GEGENVORSCHLAG_GRUND_MAXLAENGE] + "…"
    assert gekuerzt in notiz
