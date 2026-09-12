"""Vertragstests fuer `termin_einladen` — Einladung statt stillem Eintrag."""
import json
import os
from datetime import timedelta, timezone
from datetime import datetime as dt

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
# Wiedervorlage zum Nachfassen (W1, Schlusspruefung 11.09.2026)
#
# `postfach.lesen()` ist die einzige Auswertungsstelle fuer Antworten und
# wird nur aktiv, wenn jemand die richtige Mail von Hand oeffnet — ohne
# eigene Wiedervorlage verschwindet eine unbeantwortete Einladung lautlos.
# `termin_bestaetigen` legt fuer die Terminerinnerung laengst eine an
# (test_termin.py::test_wiedervorlage_entsteht_am_vortag_und_ist_auffindbar);
# hier dasselbe Muster fuer die Einladung selbst.
# ---------------------------------------------------------------------------

def _heute():
    """UTC, nicht date.today() — gleiche Begruendung wie in test_termin.py."""
    return dt.now(timezone.utc).date()


def test_einladung_legt_wiedervorlage_zum_nachfassen_an():
    lead = _lead()
    datum = (_heute() + timedelta(days=10)).isoformat()
    antwort = json.loads(server.termin_einladen(
        lead, datum, "14:30", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort

    faellig = (_heute() + timedelta(days=2)).isoformat()  # EINLADUNG_NACHFASS_TAGE
    assert antwort["wiedervorlage"]["faellig_am"] == faellig
    assert antwort["wiedervorlage"]["aktivitaets_id"]

    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'wiedervorlage'", (lead,))
    assert len(zeilen) == 1, zeilen
    assert zeilen[0]["payload"]["faellig_am"] == faellig
    assert "Nachfassen" in zeilen[0]["payload"]["notiz"]
    assert "Erstgespräch" in zeilen[0]["payload"]["notiz"]
    assert datum in zeilen[0]["payload"]["notiz"]


def test_nachfass_wiedervorlage_wird_auf_den_termintag_gedeckelt():
    """Eine sehr kurzfristige Einladung (Termin morgen) darf keine
    Nachfass-Faelligkeit NACH dem Termin bekommen — min(), nicht der volle
    EINLADUNG_NACHFASS_TAGE-Abstand."""
    lead = _lead()
    datum = (_heute() + timedelta(days=1)).isoformat()
    antwort = json.loads(server.termin_einladen(
        lead, datum, "14:30", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort
    assert antwort["wiedervorlage"]["faellig_am"] == datum


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


def test_report_schreibfehler_wird_gemeldet_und_raeumt_auf(monkeypatch):
    """Fix-Runde 3: report_schreiben lief bislang OHNE try/except — anders
    als bei den vier anderen Aufrufern im Modul, und anders als in
    termin_bestaetigen ist ein fehlgeschlagener Schreibvorgang hier
    TOEDLICH (keine Reportkopie -> keine vollstaendige Einladung, die man
    anhaengen koennte), nicht nur Beiwerk. Gleiches Mock-Muster wie
    `test_schreibfehler_kostet_den_termin_nicht` in test_termin.py."""
    def _kaputt(*_a, **_kw):
        raise OSError("Read-only file system")

    monkeypatch.setattr(recherche, "report_schreiben", _kaputt)
    lead = _lead()

    # Eigenes Datum/Uhrzeit (nicht das sonst ueberall verwendete
    # 2026-10-01/14:30): der Dateiname traegt Datum+Uhrzeit, und der reale
    # Medienordner wird zwischen Tests NICHT geleert (nur die DB-Tabellen,
    # siehe Fixture `leer` oben) — mit dem verbreiteten Datum haette hier
    # bereits die Datei eines FRUEHEREN, erfolgreichen Tests gelegen, und
    # die Sicherung "nur entfernen, was dieser Aufruf neu angelegt hat"
    # haette zu Recht nicht geloescht, das aber als Fehlschlag dieses Tests
    # ausgesehen.
    antwort = json.loads(server.termin_einladen(lead, "2026-11-22", "09:15"))

    assert "fehler" in antwort
    assert "reports" in antwort["fehler"]

    entwuerfe = server._q("select id from drafts where lead_id = %s", (lead,))
    assert entwuerfe == []

    dateiname = f"einladung-{recherche.slug('Ivan')}-2026-11-22-0915.ics"
    assert not os.path.exists(
        os.path.join(medien.ERZEUGT_VERZEICHNIS, dateiname)), (
        "verwaiste .ics im Medienordner haengengeblieben")


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


# ---------------------------------------------------------------------------
# Fix-Runde 1 zu Aufgabe 5 (Koordinator-Feedback, 11.09.2026): `uid`/`folge`
# zum Fortschreiben einer bestehenden Einladung (z. B. nach einem
# angenommenen Gegenvorschlag) — statt einer zweiten, unabhaengigen
# Einladung, die im Kalenderprogramm des Empfaengers neben der alten
# stehen bleibt. Eigene Daten (2026-12-0x/nicht sonst im Modul verwendete
# Uhrzeiten): der Medienordner wird zwischen Tests NICHT geleert (siehe
# `test_report_schreibfehler_wird_gemeldet_und_raeumt_auf` oben), eine
# Kollision mit den ueberall sonst benutzten 2026-10-01/14:30 waere hier
# besonders leicht moeglich (derselbe Kontaktname "Ivan").
# ---------------------------------------------------------------------------

def test_uid_und_folge_schreiben_die_bestehende_einladung_fort():
    """Der Kernfall: zweiter Aufruf mit der Kennung des ersten und
    hoeherer Folge traegt DIESELBE UID mit gestiegener SEQUENCE — keine
    zweite, unabhaengige Buchung."""
    lead = _lead()
    erste = json.loads(server.termin_einladen(
        lead, "2026-12-03", "11:00", thema="Erstgespräch"))
    assert "fehler" not in erste, erste
    assert erste["folge"] == 0

    zweite = json.loads(server.termin_einladen(
        lead, "2026-12-04", "15:30", thema="Erstgespräch",
        uid=erste["uid"], folge=1))
    assert "fehler" not in zweite, zweite
    assert zweite["uid"] == erste["uid"]
    assert zweite["folge"] == 1

    with open(zweite["pfad"], encoding="utf-8", newline="") as f:
        text = _entfaltet(f.read())
    assert f"UID:{erste['uid']}" in text
    assert "SEQUENCE:1" in text

    # Zwei Aktivitaeten unter DERSELBEN uid, mit unterschiedlicher folge —
    # append-only, keine Aenderung der ersten Zeile.
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_entworfen' order by created_at", (lead,))
    assert len(zeilen) == 2, zeilen
    assert [z["payload"]["folge"] for z in zeilen] == [0, 1]
    assert {z["payload"]["uid"] for z in zeilen} == {erste["uid"]}


def test_gleiche_oder_niedrigere_folge_wird_abgelehnt():
    """Eine SEQUENCE, die nicht hoeher ist als die zuletzt verwendete, waere
    fuer ein Kalenderprogramm wirkungslos (RFC 5546) — das muss ein
    lesbarer Fehler sein, keine still erzeugte, nutzlose Einladung."""
    lead = _lead()
    erste = json.loads(server.termin_einladen(
        lead, "2026-12-03", "11:00", thema="Erstgespräch"))
    hoehere = json.loads(server.termin_einladen(
        lead, "2026-12-04", "15:30", thema="Erstgespräch",
        uid=erste["uid"], folge=2))
    assert "fehler" not in hoehere, hoehere

    gleiche = json.loads(server.termin_einladen(
        lead, "2026-12-05", "09:45", thema="Erstgespräch",
        uid=erste["uid"], folge=2))
    assert "fehler" in gleiche
    assert "SEQUENCE" in gleiche["fehler"]

    niedrigere = json.loads(server.termin_einladen(
        lead, "2026-12-05", "09:45", thema="Erstgespräch",
        uid=erste["uid"], folge=1))
    assert "fehler" in niedrigere
    assert "SEQUENCE" in niedrigere["fehler"]

    # Kein Entwurf und keine Datei aus den beiden abgelehnten Aufrufen.
    entwuerfe = server._q(
        "select id from drafts where lead_id = %s", (lead,))
    assert len(entwuerfe) == 2, entwuerfe  # nur die zwei erfolgreichen


def test_ohne_uid_bleibt_alles_wie_bisher():
    """Ohne `uid` (und ohne `folge`) verhaelt sich das Werkzeug exakt wie
    vor dieser Fix-Runde: neue Kennung, SEQUENCE 0."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-12-03", "11:00", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort
    assert antwort["folge"] == 0
    assert antwort["uid"].endswith("@sales-claw")


def test_uid_ohne_vorherige_einladung_wird_abgelehnt():
    """Eine `uid`, zu der es bei diesem Kontakt keine vorherige Einladung
    gibt, laesst sich nicht fortschreiben — sonst koennte eine falsch
    abgetippte Kennung unbemerkt eine neue, aber falsch benannte Buchung
    erzeugen."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-12-03", "11:00", thema="Erstgespräch",
        uid="frei-erfunden@sales-claw", folge=1))
    assert "fehler" in antwort
    assert "Keine vorherige Einladung" in antwort["fehler"]


def test_folge_ohne_uid_wird_abgelehnt():
    """`folge` ohne `uid` haette ohne diese Pruefung STILL keine Wirkung
    (eine neue Einladung beginnt ohnehin immer bei SEQUENCE 0) — das muss
    gemeldet werden, kein unbemerkter Bedeutungsverlust einer Angabe."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-12-03", "11:00", thema="Erstgespräch", folge=1))
    assert "fehler" in antwort
    assert "ohne uid" in antwort["fehler"]


# --- Wie die Mail beim Empfaenger ankommt (12.09.2026) ---------------------
# Gefunden im ersten echten Durchgang gegen ein Gmail-Postfach, nicht am
# Schreibtisch: der Text sprach von einem Anhang, den es bewusst nicht gibt,
# und ein Videoraum-Link war in der Mail selbst unsichtbar.

def test_einladungstext_verspricht_keinen_anhang():
    """`nachricht_mit_einladung` haengt die Kalenderdaten ABSICHTLICH nicht
    als Datei an, sondern als Alternative zum Text — nur so baut das
    Mailprogramm die Schaltflaechen. Ein Text, der einen Anhang ankuendigt,
    widerspricht dem sichtbar: der Empfaenger sucht eine Datei, findet keine
    und haelt die Mail fuer kaputt."""
    lead = _lead()
    json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    rumpf = server._q(
        "select body from drafts where lead_id = %s", (lead,))[0]["body"]
    assert "Anhang" not in rumpf, rumpf
    assert "zusagen" in rumpf and "absagen" in rumpf, rumpf


def test_videoraum_link_steht_sichtbar_in_der_mail():
    """Ein Meet-/Jitsi-Raum kommt als `ort` herein und landete bisher NUR im
    LOCATION-Feld des Kalendereintrags — in der Mail stand er nirgends. Wer
    eine Einladung zu einem Videotermin bekommt, erwartet den Link im Text."""
    lead = _lead()
    raum = "https://meet.google.com/abc-defg-hij"
    json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch", ort=raum))
    rumpf = server._q(
        "select body from drafts where lead_id = %s", (lead,))[0]["body"]
    assert raum in rumpf, rumpf
    # Und er ist als Videoraum benannt, nicht als "Ort: https://…".
    assert f"Videoraum: {raum}" in rumpf, rumpf


def test_gewoehnlicher_ort_heisst_weiterhin_ort():
    """Gegenprobe zum vorigen Test: die Unterscheidung darf nicht jeden Ort
    zum Videoraum erklaeren."""
    lead = _lead()
    json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch", ort="Büro Kirchheim"))
    rumpf = server._q(
        "select body from drafts where lead_id = %s", (lead,))[0]["body"]
    assert "Ort: Büro Kirchheim" in rumpf, rumpf
    assert "Videoraum" not in rumpf, rumpf


def test_kalenderbeschreibung_traegt_echte_umlaute():
    """Die DESCRIPTION steht in JEDER Einladung, die einen Kunden erreicht —
    sichtbarer als jede Bildschirmzeile. Der Waechter aus Stufe 1 bewacht nur
    `ui.py` und hat diese Stelle nie gesehen; hier stand "ueber"."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        text = _entfaltet(f.read())
    assert "über die" in text, text
    assert "ueber die" not in text, text


# --- Zeilenenden der versendeten Datei (12.09.2026) ------------------------
# Gefunden erst am echten Gmail-Postfach: dort stand "Unable to load event".
# Gmail hatte den Kalenderteil also erkannt und war am PARSEN gescheitert.
# Ursache war eine doppelte Uebersetzung beim Schreiben der Zweitschrift.

def _rohbytes(dateiname):
    with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, dateiname), "rb") as f:
        return f.read()


def test_versendete_datei_hat_einfaches_crlf():
    """RFC 5545 §3.1 verlangt CRLF. Die Zweitschrift in `media-erzeugt` wurde
    mit `newline="\\r\\n"` geschrieben, obwohl der Text schon CRLF trug —
    Python uebersetzte jedes "\\n" ein ZWEITES Mal, jede Zeile endete auf
    "\\r\\r\\n". Strenge Parser lehnen das ab; Gmail zeigte "Unable to load
    event".

    Geprueft wird die Datei in `media-erzeugt`, NICHT die in `reports`:
    versendet wird nur der Medienordner (`_anhang_erlaubt`), und genau die
    Fassung dort war kaputt, waehrend die Kopie in `reports` korrekt war.
    Deshalb ist es nie jemandem aufgefallen."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    roh = _rohbytes(antwort["datei"])
    assert b"\r\r" not in roh, roh[:120]
    assert b"\r\n" in roh, roh[:120]
    # Kein nacktes LF ohne CR — sonst waere die Uebersetzung nur halb heil.
    assert roh.replace(b"\r\n", b"").count(b"\n") == 0, roh[:200]


def test_versendete_datei_gleicht_der_in_reports():
    """Zwei Fassungen derselben Buchung duerfen sich nicht unterscheiden —
    die eine wird versendet, die andere archiviert. Weicht die versendete ab,
    beweist das Archiv nichts ueber das, was beim Kunden ankam."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    with open(antwort["pfad"], "rb") as f:
        archiv = f.read()
    assert _rohbytes(antwort["datei"]) == archiv
