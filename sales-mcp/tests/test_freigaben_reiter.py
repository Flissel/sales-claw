"""Freigaben in Reitern (Betreiber 09.11.2026: „Genau, so finde ich super.").

Vorher eine lange Seite, auf der alles untereinander stand und sich mischte
(„Kanäle haben Eigenprofil, LinkedIn posten und das ist eigentlich falsch").
Jetzt oben fünf Reiter, darunter je Reiter seine Unter-Reiter, beide mit
offenen Zahlen; leere Reiter blass, aber sichtbar. Nur die Anordnung ändert
sich: Freigeben, Ablehnen, Bearbeiten bleiben, wie sie sind.

  Nachrichten  E-Mail · WhatsApp · LinkedIn · Mails aufräumen   (Vorgabe)
  Marketing    LinkedIn-Beiträge · Kanäle · Newsletter · Marketing-Pult · Videos
  Bewerbungen
  Kurse
  Technik      Debugger-PRs · Rückfragen
"""
import re
import urllib.parse

import pytest
from starlette.testclient import TestClient

import freigabe_eingang as fe
import server
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
PR = "Flissel/vibemind-os#154"
RUECK = "Flissel/vibemind-os#77"
KURS = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads, sales_test.kanal_status cascade")
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")
    yield


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(pfad, daten):
    return CLIENT.post(pfad, data={"csrf": ui.CSRF_TOKEN, **daten},
                       headers={"host": HOST_OK}, follow_redirects=False)


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _entwurf(lead, kanal="whatsapp", text="Hallo?", status="pending",
             empfaenger="+491701234567", fehler=None, newsletter=None):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, error, newsletter) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (lead, kanal, empfaenger, text, status, fehler, newsletter))[0]["id"])


def _reiter(seite: str) -> list[tuple[str, str, bool, bool]]:
    """Die obere Reiterleiste: (Name, Zahl, aktiv, blass) je Reiter."""
    leiste = seite[seite.index('<nav class="reiter" aria-label="Freigaben">'):]
    leiste = leiste[:leiste.index("</nav>")]
    return [(m["name"].strip(), m["zahl"], bool(m["aktiv"]), "leer" in (m["klasse"] or ""))
            for m in re.finditer(
                r'<a(?: class="(?P<klasse>[^"]*)")? href="[^"]*"(?P<aktiv> aria-current="page")?>'
                r'(?P<name>[^<]+)<span class="zaehler[^"]*">(?P<zahl>\d+)</span></a>', leiste)]


def _unterreiter(seite: str) -> list[tuple[str, str, bool, bool]]:
    if '<nav class="reiter unter"' not in seite:
        return []
    leiste = seite[seite.index('<nav class="reiter unter"'):]
    leiste = leiste[:leiste.index("</nav>")]
    return [(m["name"].strip(), m["zahl"], bool(m["aktiv"]), "leer" in (m["klasse"] or ""))
            for m in re.finditer(
                r'<a(?: class="(?P<klasse>[^"]*)")? href="[^"]*"(?P<aktiv> aria-current="page")?>'
                r'(?P<name>[^<]+)<span class="zaehler[^"]*">(?P<zahl>\d+)</span></a>', leiste)]


def _aktiv(reiter) -> str:
    return next(name for name, _, aktiv, _ in reiter if aktiv)


# --- Reiter oben ------------------------------------------------------------

def test_reiterleiste_in_fester_reihenfolge_nachrichten_vorgewaehlt():
    seite = _get("/freigaben")
    assert seite.status_code == 200
    namen = [r[0] for r in _reiter(seite.text)]
    # Bewerbungen nur, wo der Bewerbungs-Bot eingerichtet ist (hier nicht).
    assert namen == ["Nachrichten", "Marketing", "Kurse", "Technik"]
    assert _aktiv(_reiter(seite.text)) == "Nachrichten"


def test_bewerbungen_reiter_wo_eingerichtet(monkeypatch):
    import ui_freigabe_bewerbung
    monkeypatch.setattr(ui_freigabe_bewerbung, "sichtbar", lambda _ui: True)
    monkeypatch.setattr(ui_freigabe_bewerbung, "anzahl_offen", lambda _ui: 2)
    namen = [(r[0], r[1]) for r in _reiter(_get("/freigaben").text)]
    assert namen == [("Nachrichten", "0"), ("Marketing", "0"), ("Bewerbungen", "2"),
                     ("Kurse", "0"), ("Technik", "0")]


def test_leere_reiter_blass_aber_sichtbar():
    _entwurf(_lead(), text="WA offen")
    reiter = {name: (zahl, blass) for name, zahl, _, blass in _reiter(_get("/freigaben").text)}
    assert reiter["Nachrichten"] == ("1", False)
    assert reiter["Kurse"] == ("0", True)
    assert reiter["Technik"] == ("0", True)
    assert 'Nachrichten <span class="zaehler offen">1</span>' in _get("/freigaben").text


def test_unbekannter_reiter_faellt_auf_nachrichten():
    seite = _get("/freigaben?tab=fax&art=%3Cscript%3E")
    assert seite.status_code == 200
    assert _aktiv(_reiter(seite.text)) == "Nachrichten"
    assert "<script>" not in seite.text


# --- Nachrichten ------------------------------------------------------------

def test_nachrichten_unterreiter_und_vorwahl_der_ersten_mit_offenem():
    lead = _lead()
    _entwurf(lead, text="WA offen eins")
    _entwurf(lead, text="WA offen zwei")
    seite = _get("/freigaben").text
    unter = _unterreiter(seite)
    assert [(n, z) for n, z, _, _ in unter] == [("E-Mail", "0"), ("WhatsApp", "2"),
                                               ("LinkedIn", "0")]
    # E-Mail steht vorn, ist aber leer: gewaehlt ist die erste mit Offenem.
    assert _aktiv(unter) == "WhatsApp"
    assert "WA offen eins" in seite and "WA offen zwei" in seite


def test_ohne_offenes_ist_der_erste_unterreiter_gewaehlt():
    assert _aktiv(_unterreiter(_get("/freigaben").text)) == "E-Mail"


def test_unterreiter_zeigt_nur_seine_art():
    lead = _lead()
    _entwurf(lead, text="WA-Text hier")
    _entwurf(lead, kanal="email", text="Mailtext hier", empfaenger="x@y.de")
    wa = _get("/freigaben?tab=nachrichten&art=whatsapp").text
    assert "WA-Text hier" in wa and "Mailtext hier" not in wa
    mail = _get("/freigaben?tab=nachrichten&art=email").text
    assert "Mailtext hier" in mail and "WA-Text hier" not in mail
    assert _aktiv(_unterreiter(mail)) == "E-Mail"


def test_zaehler_zaehlen_offenes_und_gescheitertes():
    lead = _lead()
    _entwurf(lead, text="WA eins")
    _entwurf(lead, text="WA zwei")
    _entwurf(lead, kanal="email", text="Mail kaputt", status="failed",
             fehler="SMTP antwortet nicht", empfaenger="x@y.de")
    seite = _get("/freigaben").text
    reiter = {n: z for n, z, _, _ in _reiter(seite)}
    assert reiter["Nachrichten"] == "3"
    unter = {n: (z, blass) for n, z, _, blass in _unterreiter(seite)}
    assert unter["WhatsApp"] == ("2", False)
    assert unter["E-Mail"] == ("1", False)
    assert unter["LinkedIn"] == ("0", True)
    # Gescheitertes braucht eine Entscheidung: der E-Mail-Reiter ist vorne
    # und hat Offenes, also ist er gewaehlt.
    assert _aktiv(_unterreiter(seite)) == "E-Mail"
    assert "SMTP antwortet nicht" in seite


# --- LinkedIn: Nachricht gegen eigener Beitrag ---------------------------------

def test_linkedin_beitrag_steht_unter_marketing_die_nachricht_unter_nachrichten():
    lead = _lead()
    _entwurf(lead, kanal="linkedin", text="Direktnachricht an Max",
             empfaenger="https://www.linkedin.com/in/max")
    _entwurf(lead, kanal="linkedin", text="Beitrag fürs eigene Profil",
             empfaenger="eigenes-profil")
    nachrichten = _get("/freigaben?tab=nachrichten&art=linkedin").text
    assert "Direktnachricht an Max" in nachrichten
    assert "Beitrag fürs eigene Profil" not in nachrichten
    marketing = _get("/freigaben?tab=marketing&art=linkedin").text
    assert "Beitrag fürs eigene Profil" in marketing
    assert "Direktnachricht an Max" not in marketing
    assert _aktiv(_reiter(marketing)) == "Marketing"
    assert _aktiv(_unterreiter(marketing)) == "LinkedIn-Beiträge"
    reiter = {n: z for n, z, _, _ in _reiter(marketing)}
    assert reiter == {"Nachrichten": "1", "Marketing": "1", "Kurse": "0", "Technik": "0"}


def test_kanal_beitrag_bekommt_seinen_unterreiter_unter_marketing():
    lead = _lead()
    _entwurf(lead, kanal="bluesky", text="Grüße vom Bluesky-Test",
             empfaenger="eigenes-profil")
    seite = _get("/freigaben?tab=marketing").text
    unter = [(n, z) for n, z, _, _ in _unterreiter(seite)]
    # Unverbundene Kanaele ohne Inhalt bleiben weg (wie bisher die Bloecke).
    # „Videos" (Herkunft Marketing-Video, Werkbank) steht immer da, hier leer.
    assert unter == [("LinkedIn-Beiträge", "0"), ("Bluesky", "1"), ("Newsletter", "0"),
                     ("Videos", "0")]
    assert _aktiv(_unterreiter(seite)) == "Bluesky"
    assert "Grüße vom Bluesky-Test" in seite
    assert "Grüße vom Bluesky-Test" not in _get("/freigaben").text
    assert "Grüße vom Bluesky-Test" not in _get("/freigaben?tab=marketing&art=video").text


def test_marketing_video_steht_nur_unter_videos():
    fe.eintragen("marketing-video", "marketing_video", "0123abcd-0000-4000-8000-000000000001",
                 "Video: Reiter-Probe", "https://laden.example/marketing/werkbank/"
                 "0123abcd-0000-4000-8000-000000000001/video",
                 {"auftrag": "0123abcd-0000-4000-8000-000000000001", "fassung": 1})
    videos = _get("/freigaben?tab=marketing&art=video").text
    assert "Video: Reiter-Probe" in videos
    assert _aktiv(_reiter(videos)) == "Marketing"
    assert _aktiv(_unterreiter(videos)) == "Videos"
    assert [(n, z) for n, z, _, _ in _unterreiter(videos)] == [
        ("LinkedIn-Beiträge", "0"), ("Newsletter", "0"), ("Videos", "1")]
    assert {n: z for n, z, _, _ in _reiter(videos)} == {
        "Nachrichten": "0", "Marketing": "1", "Kurse": "0", "Technik": "0"}
    for pfad in ("/freigaben", "/freigaben?tab=marketing&art=linkedin",
                 "/freigaben?tab=marketing&art=newsletter", "/freigaben?tab=kurse",
                 "/freigaben?tab=technik&art=debugger",
                 "/freigaben?tab=technik&art=rueckfragen"):
        assert "Video: Reiter-Probe" not in _get(pfad).text, pfad


def test_ohne_offenes_ist_der_unterreiter_mit_inhalt_gewaehlt():
    # Freigegeben, wartet auf den Dienst: nichts zu entscheiden, aber zu sehen.
    _entwurf(_lead(), kanal="mastodon", text="Wartet auf Mastodon", status="approved",
             empfaenger="eigenes-profil")
    seite = _get("/freigaben?tab=marketing").text
    unter = {n: (z, blass) for n, z, _, blass in _unterreiter(seite)}
    assert unter["Mastodon"] == ("0", False)
    assert _aktiv(_unterreiter(seite)) == "Mastodon"
    assert "Wartet auf Mastodon" in seite


def test_newsletter_entwuerfe_stehen_unter_marketing_newsletter():
    lead = _lead()
    nl = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    _entwurf(lead, kanal="email", text="Newsletter November", empfaenger="x@y.de",
             newsletter=nl)
    _entwurf(lead, kanal="email", text="Antwort an Max", empfaenger="x@y.de")
    nachrichten = _get("/freigaben?tab=nachrichten&art=email").text
    assert "Antwort an Max" in nachrichten and "Newsletter November" not in nachrichten
    marketing = _get("/freigaben?tab=marketing&art=newsletter").text
    assert "Newsletter November" in marketing and "Antwort an Max" not in marketing


# --- Kurse und Technik: der Eingang geteilt ------------------------------------

def _eingang():
    pr = fe.eintragen("debugger-claw", "debugger_pr", PR, "Fix für Mail-Schleife",
                      "https://github.com/Flissel/vibemind-os/pull/154", {"tests": "12 grün"})[0]
    rueck = fe.eintragen("selbstbild", "selbstbild_rueckfrage", RUECK, "Ist das Absicht?",
                         "https://github.com/x/issues/77")[0]
    kurs = fe.eintragen("werkstatt", "kursfreigabe", "kurs-1", "Mathe 1", None,
                        {"course_id": KURS})[0]
    return pr, rueck, kurs


def test_kurse_und_technik_teilen_den_eingang():
    _eingang()
    reiter = {n: z for n, z, _, _ in _reiter(_get("/freigaben").text)}
    assert reiter["Kurse"] == "1" and reiter["Technik"] == "2"
    kurse = _get("/freigaben?tab=kurse").text
    assert "Mathe 1" in kurse and "Fix für Mail-Schleife" not in kurse
    assert "Ist das Absicht?" not in kurse
    assert _unterreiter(kurse) == []
    technik = _get("/freigaben?tab=technik").text
    assert [(n, z) for n, z, _, _ in _unterreiter(technik)] == [("Debugger-PRs", "1"),
                                                               ("Rückfragen", "1")]
    assert _aktiv(_unterreiter(technik)) == "Debugger-PRs"
    assert "Fix für Mail-Schleife" in technik and "Ist das Absicht?" not in technik
    assert "Mathe 1" not in technik
    rueck = _get("/freigaben?tab=technik&art=rueckfragen").text
    assert "Ist das Absicht?" in rueck and "Fix für Mail-Schleife" not in rueck


def test_nachrichten_zeigen_keinen_eingang():
    _eingang()
    seite = _get("/freigaben").text
    assert "Fix für Mail-Schleife" not in seite and "Mathe 1" not in seite


# --- Ruecksprung nach einer Aktion: in den Reiter, aus dem sie kam ---------------

def _ort(antwort) -> tuple[str, dict]:
    teile = urllib.parse.urlsplit(antwort.headers["location"])
    return teile.path, dict(urllib.parse.parse_qsl(teile.query))


def test_freigeben_eines_beitrags_springt_zurueck_nach_marketing():
    lead = _lead()
    draft = _entwurf(lead, kanal="linkedin", text="Beitrag fürs eigene Profil",
                     empfaenger="eigenes-profil")
    r = _post("/aktion/freigeben", {"draft_id": draft,
                                   "stand": ui._entwurf_stand({"body": "Beitrag fürs eigene Profil"})})
    assert r.status_code == 303
    assert _ort(r) == ("/freigaben", {"tab": "marketing", "art": "linkedin"})


def test_ablehnen_einer_nachricht_springt_zurueck_in_ihren_unterreiter():
    lead = _lead()
    draft = _entwurf(lead, text="WA-Text hier")
    r = _post("/aktion/ablehnen", {"draft_id": draft})
    assert r.status_code == 303
    assert _ort(r) == ("/freigaben", {"tab": "nachrichten", "art": "whatsapp"})


def test_aktion_von_heute_springt_weiter_nach_heute():
    lead = _lead()
    draft = _entwurf(lead, text="WA-Text hier")
    r = _post("/aktion/ablehnen", {"draft_id": draft, "danach": "/"})
    assert r.headers["location"] == "/"


def test_eingang_aktion_springt_in_kurse_bzw_technik():
    pr, rueck, kurs = _eingang()
    r = _post("/aktion/eingang-kurs", {"kennung": kurs})
    assert r.status_code == 303
    assert _ort(r)[1]["tab"] == "kurse" and r.headers["location"].endswith("#eingang")
    r = _post("/aktion/eingang-label", {"kennung": rueck, "label": "antwort:weg"})
    assert _ort(r)[1] == {"tab": "technik", "art": "rueckfragen", "eg_hinweis": "auftrag"}
    r = _post("/aktion/eingang-verwerfen", {"kennung": pr})
    assert _ort(r)[1] == {"tab": "technik", "art": "debugger", "eg_hinweis": "verworfen"}


def test_hinweis_der_abschnitte_waehlt_ihren_reiter():
    # Alte Ruecksprung-Adressen ohne tab (Marketing, Bewerbungen) landen richtig.
    assert _aktiv(_reiter(_get("/freigaben?nl_hinweis=ok").text)) == "Marketing"
    assert _aktiv(_reiter(_get("/freigaben?eg_hinweis=auftrag").text)) == "Technik"


def test_neu_laden_bleibt_im_reiter():
    seite = _get("/freigaben?tab=technik&art=rueckfragen").text
    assert 'href="/freigaben?tab=technik&amp;art=rueckfragen">neu laden</a>' in seite
