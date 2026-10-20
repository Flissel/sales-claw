"""Abschnitt "Bewerbungen" auf /freigaben (Plan 2026-10-20 Hermes H1, Task 5).

Der Client zur Pult-API der Zentrale (bewerbung_pult.anfrage) wird gefaelscht wie in
test_freigabe_newsletter.py; es gibt kein JavaScript. Review Focus 1 (veraltete Fassung),
3 (wartet auf Durchsicht), 4 (Zentrale weg, unklares Ergebnis) und 5 (feindlicher Text)."""
import asyncio
import html
import logging
import os
import re

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import bewerbung_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_freigabe_bewerbung  # noqa: E402

PultFehler = bewerbung_pult.PultFehler
HOST = {"host": "127.0.0.1:8791"}
BID = "bw-4711"
BID2 = "bw-4712"
B = "sha256:" + "ab" * 32
B2 = "sha256:" + "cd" * 32
BRIEF = ("Sehr geehrte Frau Muster,\n\nhiermit bewerbe ich mich als Data Engineer.\n\n"
         "Mit freundlichen Grüßen\nFelix")
OFFEN = "/bewerbungen?status=offen"
ENTSCHIEDEN = "/bewerbungen?status=entschieden"
BOESE = "<script>x</script>"
BOESE2 = '"><img onerror=1>'


def karte(**kw):
    k = {"application_id": BID, "firma": "Muster GmbH", "rolle": "Data Engineer", "fassung": 1,
         "bindung": B, "score": 4.2, "luecke": "Kein Spark-Projekt",
         "anzeige_url": "https://jobs.example.org/4711", "ort": "Berlin", "kanal": "email",
         "pruefhinweise": ["Gehaltswunsch fehlt"], "was_neu": None, "anschreiben": BRIEF,
         "wartet_auf_durchsicht": False, "seit": "2026-10-20T08:00:00+00:00"}
    k.update(kw)
    return k


def verlauf(**kw):
    v = {"application_id": BID2, "firma": "Alt AG", "rolle": "Analyst", "fassung": 2,
         "entscheidung": "approve", "von": "mira", "am": "2026-10-19T08:00:00+00:00",
         "status": "archiviert"}
    v.update(kw)
    return v


class Falsch:
    """Attrappe fuer bewerbung_pult.anfrage: merkt Aufrufe, Zeitlimits und ob sie im
    Event-Loop liefen (der Render-Weg darf nie blockierend ins Netz)."""

    def __init__(self):
        self.aufrufe = []
        self.zeitlimits = []
        self.roh = []
        self.im_loop = []
        self.fehler = None          # jede Anfrage
        self.fehler_post = None     # nur POST
        self.fehler_pdf = None      # nur das PDF
        self.karten = [karte()]
        self.verlauf = []
        self.pdf = (b"%PDF-1.7 Anschreiben", "application/pdf")
        self.antwort = {"freigeben": {"status": "freigegeben", "kommando": "k-1"},
                        "nicht-bewerben": {"status": "abgelehnt", "kommando": "k-2"},
                        "feedback": {"status": "erfasst"}}

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        self.zeitlimits.append((methode, pfad, zeitlimit))
        self.roh.append(roh)
        try:
            asyncio.get_running_loop()
            self.im_loop.append(pfad)
        except RuntimeError:
            pass
        if self.fehler:
            raise self.fehler
        if methode == "POST":
            if self.fehler_post:
                raise self.fehler_post
            return self.antwort[pfad.rsplit("/", 1)[1]]
        if pfad == OFFEN:
            return {"bewerbungen": self.karten}
        if pfad == ENTSCHIEDEN:
            return {"bewerbungen": self.verlauf}
        if "/anschreiben.pdf?" in pfad and roh:
            if self.fehler_pdf:
                raise self.fehler_pdf
            return self.pdf
        raise AssertionError(f"unerwartet: {methode} {pfad}")

    def aktionen(self):
        return [a for a in self.aufrufe if a[0] == "POST"]


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _zaehler_still():
    """Ein Zaehler-Thread eines Tests darf den Zwischenspeicher des naechsten nicht fuellen."""
    t = ui_freigabe_bewerbung._laeuft["thread"]
    if t is not None:
        t.join(5)
    ui_freigabe_bewerbung._cache_leeren()


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    _zaehler_still()
    yield
    _zaehler_still()


def _anmelden(rolle: str) -> TestClient:
    """Angemeldeter Client; der Abschnitt folgt der Huerde der Admin-Pfade (Rolle
    freigeben im Basis-Laden, sales_test zaehlt als Basis-Laden)."""
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app, headers=HOST)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               follow_redirects=False)
    assert r.status_code == 303
    return c


@pytest.fixture
def anmeldung(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield _anmelden
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def falsch(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(bewerbung_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(bewerbung_pult, "eingerichtet", lambda: True)
    return f


@pytest.fixture
def client(anmeldung, falsch):
    return anmeldung("freigeben")


@pytest.fixture
def client_lesen(anmeldung, falsch):
    return anmeldung("lesen")


@pytest.fixture
def rolle_freigeben():
    t = ui._AKTIVE_ROLLE.set("freigeben")
    yield
    ui._AKTIVE_ROLLE.reset(t)


def _abschnitt(c, pfad="/freigaben") -> str:
    r = c.get(pfad)
    assert r.status_code == 200
    s = r.text[r.text.index('<section class="block" id="bewerbungen">'):]
    return s[:s.index("</section>")]


def _zeile(s: str, firma: str) -> str:
    z = s[s.index(f"{firma} –"):]
    return z[:z.index("</div>")]


def _wert(seite: str, name: str) -> str:
    return html.unescape(re.search(rf'name="{name}" value="([^"]*)"', seite).group(1))


ENTSCHEIDUNG = {"csrf": ui.CSRF_TOKEN, "fassung": "1", "bindung": B, "bestaetigt": "ja"}
POSTS = [("freigeben", {"fassung": "1", "bindung": B, "bestaetigt": "ja"}),
         ("nicht-bewerben", {"fassung": "1", "bindung": B, "bestaetigt": "ja"}),
         ("feedback", {"fassung": "1", "kommentar": "Bitte kürzer"})]


def _post(c, pfad, **daten):
    return c.post(f"/freigaben/bewerbung/{BID}/{pfad}", data={"csrf": ui.CSRF_TOKEN, **daten},
                  follow_redirects=False)


# --- Anzeige -----------------------------------------------------------------


def test_abschnitt_zeigt_karte_maskiert(client, falsch):            # Review Focus 5
    falsch.karten = [karte(firma=BOESE, rolle=BOESE2, luecke=BOESE, ort=BOESE2, kanal=BOESE,
                           pruefhinweise=[BOESE], was_neu=[BOESE2], fassung=2,
                           anschreiben="</textarea>" + BOESE, anzeige_url="javascript:alert(1)",
                           application_id='x"><script>y</script>', seit=BOESE)]
    falsch.verlauf = [verlauf(firma=BOESE, rolle=BOESE2, von=BOESE2, entscheidung=BOESE,
                              status="blockiert", anzeige_url="javascript:alert(2)", am=BOESE),
                      verlauf(application_id="bw-9", firma="Neun", entscheidung="approve",
                              status="blockiert", anzeige_url='https://x.example/"><script>z</script>')]
    seite = client.get("/freigaben").text
    assert "<script>x</script>" not in seite and "&lt;script&gt;" in seite
    assert "<script" not in seite and '"><img' not in seite
    assert "&lt;/textarea&gt;&lt;script&gt;" in seite                  # Feld-Inhalt bleibt Text
    assert "javascript:" not in seite
    assert "x%22%3E%3Cscript%3Ey%3C%2Fscript%3E" in seite             # Kennung im Pfad maskiert


def test_karte_zeigt_angaben_links_und_formulare(client, falsch):
    falsch.karten = [karte(fassung=2, was_neu=["Absatz 2 neu geschrieben"])]
    s = _abschnitt(client)
    assert "Muster GmbH – Data Engineer" in s
    assert "Fassung 2" in s and "Score 4,2 / 5" in s and "Kein Spark-Projekt" in s
    assert "E-Mail" in s and "Berlin" in s
    assert "Gehaltswunsch fehlt" in s and "Was ist neu" in s and "Absatz 2 neu geschrieben" in s
    assert ('<a href="https://jobs.example.org/4711" target="_blank" '
            'rel="noopener noreferrer">Anzeige') in s
    assert f'href="/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=2"' in s
    assert "<iframe" not in s and "<embed" not in s and "<object" not in s   # PDF nur verlinkt
    for pfad in ("freigeben", "nicht-bewerben", "feedback"):
        assert f'method="post" action="/freigaben/bewerbung/{BID}/{pfad}"' in s
    assert s.count(f'name="csrf" value="{ui.CSRF_TOKEN}"') == 3
    assert s.count(f'name="bindung" value="{B}"') == 2 and s.count('name="fassung" value="2"') == 3
    assert s.count('name="bestaetigt" value="ja"') == 2
    assert 'name="grund" maxlength="500"' in s
    assert '<textarea name="kommentar" maxlength="2000"' in s
    assert "<summary>Anschreiben selbst ändern</summary>" in s
    assert f'maxlength="15000">{ui._e(BRIEF)}</textarea>' in s           # vorbefuellt


def test_codes_werden_beschriftet(client, falsch):
    falsch.karten = [karte(kanal="email"), karte(application_id=BID2, kanal="portal", firma="Zwei"),
                     karte(application_id="bw-3", kanal="fax", firma="Drei")]
    falsch.verlauf = [verlauf(firma="Ja AG", entscheidung="approve"),
                      verlauf(firma="Nein AG", entscheidung="reject"),
                      verlauf(firma="Wer AG", entscheidung="vielleicht")]
    s = _abschnitt(client)
    karten, entschieden = s.split("Zuletzt entschieden")
    assert ">E-Mail<" in karten and ">Portal<" in karten and ">fax<" in karten
    assert "Freigegeben" in _zeile(entschieden, "Ja AG") and "von Hand" not in _zeile(entschieden, "Ja AG")
    assert "Nicht bewerben" in _zeile(entschieden, "Nein AG")
    assert "vielleicht" in _zeile(entschieden, "Wer AG")


def test_wartet_auf_durchsicht_ohne_freigeben_formular(client, falsch):   # Review Focus 3
    falsch.karten = [karte(wartet_auf_durchsicht=True), karte(application_id=BID2, bindung=B2)]
    s = _abschnitt(client)
    assert "Wartet auf Durchsicht" in s
    assert f'action="/freigaben/bewerbung/{BID}/freigeben"' not in s
    assert f'action="/freigaben/bewerbung/{BID}/nicht-bewerben"' not in s
    assert f'action="/freigaben/bewerbung/{BID}/feedback"' in s           # Feedback bleibt
    assert f'action="/freigaben/bewerbung/{BID2}/freigeben"' in s


def test_anschreiben_nicht_lesbar(client, falsch):
    falsch.karten = [karte(anschreiben="")]
    s = _abschnitt(client)
    assert "Anschreiben nicht lesbar" in s
    assert 'name="text"' not in s and '<textarea name="kommentar"' in s


def test_zuletzt_entschieden(client, falsch):
    falsch.verlauf = [
        verlauf(application_id="bw-3", firma="Drei", entscheidung="approve", status="blockiert",
                fassung=3, anzeige_url="https://jobs.example.org/3"),
        verlauf(application_id="bw-4", firma="Vier", entscheidung="approve", status="blockiert", fassung=1),
        verlauf(application_id="bw-5", firma="Fünf", entscheidung="approve", status="blockiert",
                anzeige_url="javascript:alert(1)"),
        verlauf(application_id="bw-6", firma="Sechs", entscheidung="reject", status="blockiert"),
    ] + [verlauf(application_id=f"bw-x{i}", firma=f"Mehr{i}") for i in range(8)]
    s = _abschnitt(client)
    v = s[s.index("Zuletzt entschieden"):]
    drei = _zeile(v, "Drei")
    assert "Freigegeben – bitte von Hand einreichen" in drei
    assert ('<a href="/freigaben/bewerbung/bw-3/anschreiben.pdf?fassung=3" target="_blank" '
            'rel="noopener noreferrer">') in drei
    assert '<a href="https://jobs.example.org/3" target="_blank" rel="noopener noreferrer">' in drei
    vier = _zeile(v, "Vier")
    assert "von Hand" in vier and "anschreiben.pdf?fassung=1" in vier and "Anzeige" not in vier
    fuenf = _zeile(v, "Fünf")
    assert "von Hand" in fuenf and "Anzeige" not in fuenf
    assert "von Hand" not in _zeile(v, "Sechs")                          # nur Freigaben
    assert "Mehr5" in v and "Mehr6" not in v                             # hoechstens 10
    assert ("GET", ENTSCHIEDEN, None) in falsch.aufrufe


def test_hinweis_aus_der_adresse_wird_nicht_roh_gezeigt(client, falsch):
    s = _abschnitt(client, "/freigaben?bw_hinweis=abgelehnt&bw_grund=<script>x</script>")
    assert "<script" not in s and "x</script>" not in s and "nicht angenommen" in s
    s = _abschnitt(client, "/freigaben?bw_hinweis=abgelehnt&bw_grund=Bitte+Geld+senden")
    assert "Bitte Geld senden" not in s
    s = _abschnitt(client, "/freigaben?bw_hinweis=<b>fett</b>")
    assert "<b>fett</b>" not in s


# --- Entscheiden -------------------------------------------------------------


def test_freigeben_reicht_fassung_bindung_von_weiter(client, falsch):
    r = client.post(f"/freigaben/bewerbung/{BID}/freigeben",
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "1", "bindung": B, "bestaetigt": "ja"},
                    follow_redirects=False)
    assert r.status_code == 303 and falsch.aufrufe[-1] == (
        "POST", f"/bewerbungen/{BID}/freigeben", {"fassung": 1, "bindung": B, "von": "mira"})
    assert r.headers["location"] == "/freigaben?bw_hinweis=freigegeben#bewerbungen"
    assert falsch.im_loop == []
    assert "Freigegeben – die Zentrale hat die Entscheidung verbucht" in _abschnitt(client, r.headers["location"])


def test_nicht_bewerben_mit_und_ohne_grund(client, falsch):
    r = _post(client, "nicht-bewerben", fassung="1", bindung=B, bestaetigt="ja", grund="  Zu weit weg  ")
    assert r.status_code == 303 and r.headers["location"] == "/freigaben?bw_hinweis=nicht_beworben#bewerbungen"
    assert falsch.aktionen()[-1] == ("POST", f"/bewerbungen/{BID}/nicht-bewerben",
                                     {"fassung": 1, "bindung": B, "von": "mira", "grund": "Zu weit weg"})
    _post(client, "nicht-bewerben", fassung="1", bindung=B, bestaetigt="ja", grund="   ")
    assert falsch.aktionen()[-1][2] == {"fassung": 1, "bindung": B, "von": "mira"}
    r = _post(client, "nicht-bewerben", fassung="1", bindung=B, bestaetigt="ja", grund="g" * 501)
    assert r.status_code == 422 and len(falsch.aktionen()) == 2
    r = _post(client, "nicht-bewerben", fassung="1", bindung=B, bestaetigt="ja", grund="g" * 500)
    assert r.status_code == 303 and falsch.aktionen()[-1][2]["grund"] == "g" * 500
    assert falsch.im_loop == []


@pytest.mark.parametrize("pfad", ["freigeben", "nicht-bewerben"])
def test_ohne_haken_ruft_nichts(client, falsch, pfad):
    r = _post(client, pfad, fassung="1", bindung=B)
    assert r.status_code == 400 and falsch.aktionen() == []


@pytest.mark.parametrize("fassung,bindung", [
    ("0", B), ("-1", B), ("1.0", B), ("abc", B), ("", B), ("²", B), ("1" * 12, B),
    ("1", ""), ("1", "sha256:xyz"), ("1", "sha256:" + "a" * 63), ("1", "md5:" + "a" * 64),
    ("1", B + "0"), ("1", B + "\n"),
])
@pytest.mark.parametrize("pfad", ["freigeben", "nicht-bewerben"])
def test_fassung_und_bindung_werden_lokal_geprueft(client, falsch, pfad, fassung, bindung):
    r = _post(client, pfad, fassung=fassung, bindung=bindung, bestaetigt="ja")
    assert r.status_code == 422 and falsch.aktionen() == []


@pytest.mark.parametrize("fassung", ["0", "x", "", "²"])
def test_feedback_prueft_die_fassung(client, falsch, fassung):
    r = _post(client, "feedback", fassung=fassung, kommentar="Bitte kürzer")
    assert r.status_code == 422 and falsch.aktionen() == []


@pytest.mark.parametrize("akteur,von", [
    ("mira", "mira"), ("x@y.de-1_2", "x@y.de-1_2"), ("Felix Müller!", "Felix_M_ller_"),
    ("a" * 70, "a" * 60), ("", "sales-ui"), (None, "sales-ui"),
])
def test_von_passt_auf_das_muster(akteur, von):
    assert ui_freigabe_bewerbung._von(akteur) == von
    assert re.fullmatch(r"[A-Za-z0-9_.@-]{1,60}", ui_freigabe_bewerbung._von(akteur))


@pytest.mark.parametrize("pfad,daten", POSTS)
def test_ohne_csrf_403(client, falsch, pfad, daten):
    for token in (None, "falsch"):
        d = dict(daten) if token is None else {**daten, "csrf": token}
        r = client.post(f"/freigaben/bewerbung/{BID}/{pfad}", data=d, follow_redirects=False)
        assert r.status_code == 403
    assert falsch.aktionen() == []


@pytest.mark.parametrize("pfad,daten", POSTS)
def test_rolle_lesen_darf_nicht_posten(client_lesen, falsch, monkeypatch, pfad, daten):
    r = _post(client_lesen, pfad, **daten)
    assert r.status_code == 403 and "Nicht für diese Anmeldung" in r.text and falsch.aktionen() == []
    assert client_lesen.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=1").status_code == 403
    assert 'id="bewerbungen"' not in client_lesen.get("/freigaben").text
    assert falsch.aufrufe == []
    assert ui._pfad_erlaubt("freigeben", f"/freigaben/bewerbung/{BID}/{pfad}") is True
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")          # fremder Laden: gesperrt
    assert ui._pfad_erlaubt("freigeben", f"/freigaben/bewerbung/{BID}/{pfad}") is False
    assert ui._pfad_erlaubt("freigeben", "/freigaben") is True


@pytest.mark.parametrize("pfad,daten", POSTS)
def test_ohne_anmeldung_keine_entscheidung(falsch, monkeypatch, pfad, daten):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")             # Wache durchlaessig
    c = TestClient(ui.app, headers=HOST)
    assert _post(c, pfad, **daten).status_code == 403
    assert c.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=1").status_code == 403
    assert 'id="bewerbungen"' not in c.get("/freigaben").text
    assert falsch.aufrufe == []


def test_kennung_wird_im_pfad_maskiert(client, falsch):
    falsch.karten = [karte(application_id="a b/c")]
    assert 'action="/freigaben/bewerbung/a%20b%2Fc/freigeben"' in _abschnitt(client)
    r = client.post("/freigaben/bewerbung/bw-1%3Fx%3D1%23y/freigeben", data=ENTSCHEIDUNG,
                    follow_redirects=False)
    assert r.status_code == 303
    assert falsch.aktionen()[-1][1] == "/bewerbungen/bw-1%3Fx%3D1%23y/freigeben"


# --- Fehler nach dem Absenden --------------------------------------------------


@pytest.mark.parametrize("grund,text", [
    ("fassung_veraltet", "Diese Fassung ist veraltet – Seite neu laden"),
    ("schon_entschieden", "Schon entschieden"),
    ("wartet_auf_durchsicht", "Wartet auf Durchsicht"),
])
@pytest.mark.parametrize("pfad,daten", POSTS)
def test_veraltet_wird_als_hinweis_gezeigt(client, falsch, pfad, daten, grund, text):   # Review Focus 1
    falsch.fehler_post = PultFehler("abgelehnt", grund, {"detail": grund})
    r = _post(client, pfad, **daten)
    assert r.status_code == 303 and r.headers["location"] == f"/freigaben?bw_hinweis={grund}#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert text in s
    for erfolg in ("freigegeben", "nicht_beworben", "feedback"):
        assert ui_freigabe_bewerbung._HINWEISE[erfolg][1] not in s


@pytest.mark.parametrize("grund", ["nicht_offen", "unbekannt", "eingabe_ungueltig", "Eingabe ungueltig", "409"])
def test_andere_ablehnung_ist_ein_allgemeiner_hinweis(client, falsch, grund):
    falsch.fehler_post = PultFehler("abgelehnt", grund)
    r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja")
    assert r.status_code == 303 and r.headers["location"].startswith("/freigaben?bw_hinweis=abgelehnt")
    assert r.headers["location"].endswith("#bewerbungen")
    s = _abschnitt(client, r.headers["location"])
    assert "nicht angenommen" in s and ui_freigabe_bewerbung._HINWEISE["freigegeben"][1] not in s


def test_api_weg_seite_bleibt(client, falsch):                     # Review Focus 4
    lead = str(server._q("insert into leads (name, phone, source) values ('Max', '+491', 'whatsapp') "
                         "returning id")[0]["id"])
    server._q("insert into drafts (lead_id, channel, recipient, body, status) values "
              "(%s, 'whatsapp', '+491', 'Hallo Welt', 'pending') returning id", (lead,))
    falsch.fehler = PultFehler("nicht_erreichbar", "URLError")
    r = client.get("/freigaben")
    assert r.status_code == 200
    assert "Bewerbungs-Zentrale ist gerade nicht erreichbar" in r.text
    assert "Hallo Welt" in r.text and 'id="termine"' in r.text      # Sales-Abschnitte da
    assert len(falsch.aufrufe) == 1
    assert "gerade nicht erreichbar" in client.get("/freigaben").text
    assert len(falsch.aufrufe) == 1                                  # < 60 s: kein neuer Versuch


@pytest.mark.parametrize("fehler,text", [
    (PultFehler("nicht_verbunden", "401"), "Bewerbungs-Zentrale ist nicht verbunden"),
    (PultFehler("unbekannt", "500"), "gerade nicht erreichbar"),
    (RuntimeError("kaputt"), "gerade nicht erreichbar"),
])
def test_lesefehler_gibt_hinweis_statt_500(client, falsch, fehler, text):
    falsch.fehler = fehler
    r = client.get("/freigaben")
    assert r.status_code == 200 and text in r.text


def test_kaputte_antwort_ist_kein_nichts_offen(client, falsch):
    falsch.karten = "kaputt"
    s = _abschnitt(client)
    assert "gerade nicht erreichbar" in s


@pytest.mark.parametrize("art", ["nicht_erreichbar", "unbekannt"])
@pytest.mark.parametrize("pfad,daten", POSTS)
def test_zeitueberschreitung_nach_post_ist_unklar(client, falsch, pfad, daten, art):   # Review Focus 4
    falsch.fehler_post = PultFehler(art, "TimeoutError")
    r = _post(client, pfad, **daten)
    assert r.status_code == 504 and ui_freigabe_bewerbung.UNKLAR_TITEL in r.text
    assert "Ergebnis unklar – Seite neu laden" in r.text
    assert "location" not in r.headers and "Nichts wurde" not in r.text
    for erfolg in ("freigegeben", "nicht_beworben", "feedback"):              # nie eine Erfolgsmeldung
        assert ui_freigabe_bewerbung._HINWEISE[erfolg][1] not in r.text


@pytest.mark.parametrize("pfad,daten", POSTS)
def test_unklare_erfolgsantwort_ist_unklar(client, falsch, pfad, daten):
    falsch.antwort[pfad] = {}
    r = _post(client, pfad, **daten)
    assert r.status_code == 504 and ui_freigabe_bewerbung.UNKLAR_TITEL in r.text


@pytest.mark.parametrize("pfad,daten", POSTS)
def test_nicht_verbunden_nach_post_503(client, falsch, pfad, daten):
    falsch.fehler_post = PultFehler("nicht_verbunden", "401")
    r = _post(client, pfad, **daten)
    assert r.status_code == 503 and "nicht verbunden" in r.text


# --- Feedback ----------------------------------------------------------------


def test_feedback_grenzen_und_crlf(client, falsch):
    r = _post(client, "feedback", fassung="1", kommentar="x" * 2001)
    assert r.status_code == 422 and falsch.aktionen() == []
    r = _post(client, "feedback", fassung="1", kommentar="a\r\n" * 999 + "ab")   # 2000 Zeichen mit LF
    assert r.status_code == 303, r.text
    gesendet = falsch.aktionen()[-1][2]
    assert "\r" not in gesendet["kommentar"] and len(gesendet["kommentar"]) == 2000 and "text" not in gesendet
    r = _post(client, "feedback", fassung="1", text="y" * 15001)
    assert r.status_code == 422 and len(falsch.aktionen()) == 1
    r = _post(client, "feedback", fassung="1", text="b\r\n" * 7499 + "bc")      # 15000 Zeichen mit LF
    assert r.status_code == 303
    gesendet = falsch.aktionen()[-1][2]
    assert "\r" not in gesendet["text"] and len(gesendet["text"]) == 15000 and "kommentar" not in gesendet
    assert falsch.im_loop == []


def test_feedback_schickt_text_nur_wenn_geaendert(client, falsch):
    seite = client.get("/freigaben").text
    original = _wert(seite, "original")
    wie_browser = "\r\n" + BRIEF.replace("\n", "\r\n") + "\r\n  "         # unveraendert abgeschickt
    r = _post(client, "feedback", fassung="1", original=original, kommentar=" Bitte kürzer ",
              text=wie_browser)
    assert r.status_code == 303 and r.headers["location"] == "/freigaben?bw_hinweis=feedback#bewerbungen"
    assert falsch.aktionen()[-1] == ("POST", f"/bewerbungen/{BID}/feedback",
                                     {"fassung": 1, "von": "mira", "kommentar": "Bitte kürzer"})
    assert "Feedback erfasst" in _abschnitt(client, r.headers["location"])
    neu = BRIEF.replace("hiermit", "gern")
    _post(client, "feedback", fassung="1", original=original, kommentar="", text=neu.replace("\n", "\r\n"))
    assert falsch.aktionen()[-1][2] == {"fassung": 1, "von": "mira", "text": neu}
    n = len(falsch.aktionen())
    for kommentar, text in (("  ", wie_browser), ("", ""), ("\r\n", "  ")):
        r = _post(client, "feedback", fassung="1", original=original, kommentar=kommentar, text=text)
        assert r.status_code == 303
        assert r.headers["location"] == "/freigaben?bw_hinweis=kein_feedback#bewerbungen"
    assert len(falsch.aktionen()) == n
    assert "Kein Feedback eingegeben" in _abschnitt(client, r.headers["location"])


# --- PDF ---------------------------------------------------------------------


def test_pdf_mit_sandbox_csp(client, falsch):
    r = client.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=1")
    assert r.status_code == 200 and r.content == falsch.pdf[0]
    assert r.headers["content-type"].startswith("application/pdf")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["content-security-policy"] == ui._CSP_DATEI
    assert r.headers["content-disposition"].startswith("inline")
    i = falsch.aufrufe.index(("GET", f"/bewerbungen/{BID}/anschreiben.pdf?fassung=1", None))
    assert falsch.roh[i] is True and falsch.zeitlimits[i][2] == 8        # Fix-Runde 1: 8 s
    assert falsch.im_loop == []


@pytest.mark.parametrize("abfrage", ["", "?fassung=0", "?fassung=x", "?fassung=-1", "?fassung=²"])
def test_pdf_ohne_gueltige_fassung_ruft_nichts(client, falsch, abfrage):
    r = client.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf{abfrage}")
    assert r.status_code == 422
    assert not [a for a in falsch.aufrufe if "anschreiben.pdf" in a[1]]


@pytest.mark.parametrize("fehler,status,text", [
    (PultFehler("abgelehnt", "fassung_veraltet"), 409, "Diese Fassung ist veraltet – Seite neu laden"),
    (PultFehler("abgelehnt", "unbekannt"), 404, "Nicht gefunden"),
    (PultFehler("nicht_verbunden", "401"), 503, "nicht verbunden"),
    (PultFehler("nicht_erreichbar", "TimeoutError"), 503, "gerade nicht erreichbar"),
    (PultFehler("abgelehnt", BOESE), 422, "&lt;script&gt;x&lt;/script&gt;"),
])
def test_pdf_fehler(client, falsch, fehler, status, text):
    falsch.fehler_pdf = fehler
    r = client.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=1")
    assert r.status_code == status and text in r.text
    assert "<script" not in r.text


def test_pdf_nur_als_pdf(client, falsch):
    falsch.pdf = (b"<html><script>alert(1)</script></html>", "text/html")
    r = client.get(f"/freigaben/bewerbung/{BID}/anschreiben.pdf?fassung=1")
    assert r.status_code == 502 and "alert(1)" not in r.text


# --- Sichtbarkeit, Zaehler, Zeitlimits -----------------------------------------


def test_unsichtbar_ohne_pult_konfiguration(client, falsch, monkeypatch):
    monkeypatch.setattr(bewerbung_pult, "eingerichtet", lambda: False)
    monkeypatch.setitem(ui_freigabe_bewerbung._laeuft, "thread", None)
    r = client.get("/freigaben")
    assert r.status_code == 200 and 'id="bewerbungen"' not in r.text
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert ui_freigabe_bewerbung.anzahl_offen(ui) == 0
        assert asyncio.run(ui_freigabe_bewerbung.abschnitt(ui)) == ""
    finally:
        ui._AKTIVE_ROLLE.reset(t)
    assert ui_freigabe_bewerbung._laeuft["thread"] is None and falsch.aufrufe == []


def test_anzahl_offen_ist_nur_zwischenspeicher(falsch, rolle_freigeben):
    falsch.karten = [karte(), karte(application_id=BID2)]
    assert ui_freigabe_bewerbung.anzahl_offen(ui) == 0             # kalt: kein Abruf auf dem Render-Weg
    ui_freigabe_bewerbung._laeuft["thread"].join(5)
    assert falsch.im_loop == []
    assert ui_freigabe_bewerbung.anzahl_offen(ui) == 2             # Hintergrund hat aufgefrischt
    n = len(falsch.aufrufe)
    assert ui_freigabe_bewerbung.anzahl_offen(ui) == 2
    assert len(falsch.aufrufe) == n                                 # frisch: kein weiterer Abruf


def test_zaehler_addiert_nur_im_menue_nicht_in_heute(falsch, monkeypatch, rolle_freigeben):
    monkeypatch.setattr(server.medien, "liste", lambda *a, **k: [])
    falsch.karten = [karte(), karte(application_id=BID2)]
    assert ui_freigabe_bewerbung._laden() == 2
    z = ui._zaehler_abfragen()
    assert z["/freigaben"] == 2
    assert z["/"] == z["/freigaben"] - 2 + z["/wiedervorlagen"] + z["/einordnung"]


def test_laden_fehler_gibt_0(falsch):
    falsch.fehler = PultFehler("nicht_erreichbar", "x")
    assert ui_freigabe_bewerbung._laden() == 0
    falsch.fehler = RuntimeError("kaputt")
    assert ui_freigabe_bewerbung._laden() == 0


def test_zeitlimits(client, falsch):
    client.get("/freigaben")
    for pfad, daten in POSTS:
        assert _post(client, pfad, **daten).status_code == 303
    z = {(m, p): t for m, p, t in falsch.zeitlimits if m == "POST"}
    assert z[("POST", f"/bewerbungen/{BID}/freigeben")] == 30
    assert z[("POST", f"/bewerbungen/{BID}/nicht-bewerben")] == 30
    assert z[("POST", f"/bewerbungen/{BID}/feedback")] == 8
    lesen = [t for m, p, t in falsch.zeitlimits if m == "GET"]
    assert lesen and all(t is not None and t <= 3 for t in lesen)
    assert falsch.im_loop == []


# --- Fix-Runde 1 (Review Task 5) ---------------------------------------------------

SCHLUESSEL = "GEHEIM-PULT-SCHLUESSEL-4711"


def _meldungen(caplog) -> list[str]:
    return [x.getMessage() for x in caplog.records if x.name == "sales-ui"]


def test_ohne_kanal_kein_leeres_etikett(client, falsch):                          # F7
    falsch.karten = [karte(kanal=""), karte(application_id=BID2, kanal=None, firma="Zwei")]
    s = _abschnitt(client)
    assert 'class="badge"></span>' not in s
    assert "<summary><b>Muster GmbH – Data Engineer</b></summary>" in s
    assert "<summary><b>Zwei – Data Engineer</b></summary>" in s


def test_kaputte_karte_reisst_die_seite_nicht(client, falsch, caplog):             # F5, Review Focus 4
    lead = str(server._q("insert into leads (name, phone, source) values ('Max', '+491', 'whatsapp') "
                         "returning id")[0]["id"])
    server._q("insert into drafts (lead_id, channel, recipient, body, status) values "
              "(%s, 'whatsapp', '+491', 'Hallo Welt', 'pending') returning id", (lead,))
    falsch.karten = [karte(score=10 ** 400)]                    # OverflowError beim Formatieren
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        r = client.get("/freigaben")
    assert r.status_code == 200 and "Hallo Welt" in r.text and 'id="termine"' in r.text
    assert "Bewerbungs-Zentrale ist gerade nicht erreichbar" in _abschnitt(client)
    assert any(x.exc_info for x in caplog.records if x.name == "sales-ui")


def test_nicht_verbunden_bleibt_im_zwischenspeicher_nicht_verbunden(client, falsch):   # F3
    falsch.fehler = PultFehler("nicht_verbunden", "401")
    assert "Bewerbungs-Zentrale ist nicht verbunden" in _abschnitt(client)
    n = len(falsch.aufrufe)
    s = _abschnitt(client)                                       # < 60 s: aus dem Zwischenspeicher
    assert "Bewerbungs-Zentrale ist nicht verbunden" in s and "nicht erreichbar" not in s
    assert len(falsch.aufrufe) == n


def test_zaehlerfehler_zeigt_seine_art_im_abschnitt(client, falsch):                # F3
    falsch.fehler = PultFehler("nicht_verbunden", "401")
    assert ui_freigabe_bewerbung._laden() == 0
    n = len(falsch.aufrufe)
    s = _abschnitt(client)
    assert "Bewerbungs-Zentrale ist nicht verbunden" in s and len(falsch.aufrufe) == n


def test_zaehler_liest_mit_dem_zeitlimit_des_abschnitts(falsch):                     # F4
    assert ui_freigabe_bewerbung._laden() == 1
    assert falsch.zeitlimits[-1] == ("GET", OFFEN, ui_freigabe_bewerbung.LESE_ZEITLIMIT_S)
    assert ui_freigabe_bewerbung.LESE_ZEITLIMIT_S == 3


@pytest.mark.parametrize("art", ["nicht_erreichbar", "unbekannt"])
@pytest.mark.parametrize("pfad,daten", [
    ("freigeben", {"fassung": "1", "bindung": B, "bestaetigt": "ja"}),
    ("nicht-bewerben", {"fassung": "1", "bindung": B, "bestaetigt": "ja", "grund": "GRUND-XYZ"}),
    ("feedback", {"fassung": "1", "kommentar": "KOMMENTAR-XYZ", "text": "BRIEFTEXT-XYZ"}),
])
def test_unklarer_ausgang_wird_protokolliert_ohne_schluessel(client, falsch, monkeypatch, caplog,
                                                            pfad, daten, art):       # F2
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    falsch.fehler_post = PultFehler(art, "TimeoutError")
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        r = _post(client, pfad, **daten)
    assert r.status_code == 504
    zeilen = [m for m in _meldungen(caplog) if BID in m]
    assert len(zeilen) == 1, _meldungen(caplog)
    assert "Fassung 1" in zeilen[0] and pfad in zeilen[0] and art in zeilen[0] and "TimeoutError" in zeilen[0]
    for geheim in (SCHLUESSEL, "GRUND-XYZ", "KOMMENTAR-XYZ", "BRIEFTEXT-XYZ", B):
        assert geheim not in caplog.text


def test_unklare_erfolgsantwort_wird_ohne_rumpf_protokolliert(client, falsch, caplog):   # F2
    falsch.antwort["freigeben"] = {"status": "komisch", "rumpf": "RUMPF-XYZ"}
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja")
    assert r.status_code == 504
    zeilen = [m for m in _meldungen(caplog) if BID in m]
    assert len(zeilen) == 1 and "Fassung 1" in zeilen[0] and "freigeben" in zeilen[0]
    assert "RUMPF-XYZ" not in caplog.text and "komisch" not in caplog.text


def test_lesefehler_wird_protokolliert(client, falsch, monkeypatch, caplog):          # F2
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    falsch.fehler = PultFehler("nicht_erreichbar", "URLError", {"detail": "RUMPF-XYZ"})
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        client.get("/freigaben")
    assert any("nicht_erreichbar" in m and "URLError" in m for m in _meldungen(caplog))
    assert SCHLUESSEL not in caplog.text and "RUMPF-XYZ" not in caplog.text


def test_unerwarteter_lesefehler_mit_stapel(client, falsch, caplog):                 # F2
    falsch.fehler = RuntimeError("kaputt")
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        assert client.get("/freigaben").status_code == 200
    assert any(x.exc_info for x in caplog.records if x.name == "sales-ui")


def test_zaehlerfehler_wird_protokolliert(falsch, caplog):                           # F2
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        falsch.fehler = PultFehler("nicht_erreichbar", "TimeoutError")
        assert ui_freigabe_bewerbung._laden() == 0
        falsch.fehler = RuntimeError("kaputt")
        assert ui_freigabe_bewerbung._laden() == 0
    assert any("nicht_erreichbar" in m and "TimeoutError" in m for m in _meldungen(caplog))
    assert any(x.exc_info for x in caplog.records if x.name == "sales-ui")
