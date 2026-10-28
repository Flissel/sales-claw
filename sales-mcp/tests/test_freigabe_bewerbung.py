"""Abschnitt "Bewerbungen" auf /freigaben (Plan 2026-10-20 Hermes H1, Task 5).

Der Client zur Pult-API der Zentrale (bewerbung_pult.anfrage) wird gefaelscht wie in
test_freigabe_newsletter.py; es gibt kein JavaScript. Review Focus 1 (veraltete Fassung),
3 (wartet auf Durchsicht), 4 (Zentrale weg, unklares Ergebnis) und 5 (feindlicher Text).

Hermes H2 (Plan 2026-10-27, Task 10): Hermes-Zeile, Lauf-Kasten mit Neuer Lauf / Lauf abbrechen,
Pruefnotiz und Antworten auf der Karte (am Ende der Datei)."""
import asyncio
import html
import logging
import os
import re
import urllib.parse
from datetime import datetime

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
LAUF_AKTUELL = "/laeufe/aktuell"
LAUF_ID = "hl-20261028-a1b2c3"
LAUF_AM = "2026-10-28T08:00:00+00:00"


def karte(**kw):
    k = {"application_id": BID, "firma": "Muster GmbH", "rolle": "Data Engineer", "fassung": 1,
         "bindung": B, "score": 4.2, "luecke": "Kein Spark-Projekt",
         "anzeige_url": "https://jobs.example.org/4711", "ort": "Berlin", "kanal": "email",
         "pruefhinweise": ["Gehaltswunsch fehlt"], "was_neu": None, "anschreiben": BRIEF,
         "wartet_auf_durchsicht": False, "seit": "2026-10-20T08:00:00+00:00",
         "feedback_offen_seit": None}
    k.update(kw)
    return k


def verlauf(**kw):
    v = {"application_id": BID2, "firma": "Alt AG", "rolle": "Analyst", "fassung": 2,
         "entscheidung": "approve", "von": "mira", "am": "2026-10-19T08:00:00+00:00",
         "status": "archiviert", "anzeige_url": None}
    v.update(kw)
    return v


def lauf(**kw):
    """Der Lauf in `/laeufe/aktuell` (Vertrag Task 7: laeufe.lauf_zusammenfassung)."""
    eintraege = [("bw-1", "Alpha GmbH", "Data Engineer", 4.3, "vorgelegt"),
                 ("bw-2", "Beta AG", "Analyst", 4.0, "in_arbeit"),
                 ("bw-3", "Gamma SE", "ML Engineer", 3.6, "aufgegeben"),
                 ("bw-4", "Delta KG", "Architect", 3.5, "offen")]
    l = {"lauf_id": LAUF_ID, "status": "laeuft", "ziel": 5, "angefordert_am": LAUF_AM,
         "gestartet_am": "2026-10-28T08:00:05+00:00", "beendet_am": None, "ende_grund": None,
         "begruendung": "Zwei Stellen passen zum Profil",
         "bewerbungen": [{"application_id": a, "firma": f, "rolle": r, "score": sc, "stand": st}
                         for a, f, r, sc, st in eintraege],
         "bewertet": 9, "unter_schwelle": 5, "sperrfrist": 1, "lauf_voll": 1,
         "dauer_s": 720.0, "modellaufrufe": 31}
    l.update(kw)
    return l


def uebersicht(l=None, zustand="bereit", grund=None, moeglich=True):
    """Die ganze Antwort von `GET /laeufe/aktuell`."""
    return {"lauf": l, "neuer_lauf_moeglich": moeglich,
            "hermes": {"zustand": zustand, "grund": grund, "gesehen_am": "2026-10-28T08:05:00+00:00"}}


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
        self.fehler_lauf = None     # nur GET /laeufe/aktuell
        self.uebersicht = uebersicht()
        self.karten = [karte()]
        self.verlauf = []
        self.pdf = (b"%PDF-1.7 Anschreiben", "application/pdf")
        self.antwort = {"freigeben": {"status": "freigegeben", "kommando": "k-1"},
                        "nicht-bewerben": {"status": "abgelehnt", "kommando": "k-2"},
                        "feedback": {"status": "erfasst"},
                        "versandziel": {"status": "gesetzt", "versand": {
                            "kanal": "email", "an": "neu@muster.example", "warnung": None}},
                        "antworten": {"status": "erfasst", "anzahl": 1},
                        "laeufe": {"lauf": lauf(status="angefordert", bewerbungen=[])},
                        "abbrechen": {"lauf": lauf(status="abgebrochen")}}

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
        if pfad == LAUF_AKTUELL:
            if self.fehler_lauf:
                raise self.fehler_lauf
            return self.uebersicht
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
         ("feedback", {"fassung": "1", "kommentar": "Bitte kürzer"}),
         ("versandziel", {"fassung": "1", "an": "bewerbung@muster.example"}),
         ("antworten", {"fassung": "1", "antwort_f1": "Ab sofort"})]


def _post(c, pfad, **daten):
    return c.post(f"/freigaben/bewerbung/{BID}/{pfad}", data={"csrf": ui.CSRF_TOKEN, **daten},
                  follow_redirects=False)


# --- Anzeige -----------------------------------------------------------------


def test_abschnitt_zeigt_karte_maskiert(client, falsch):            # Review Focus 5
    falsch.karten = [karte(firma=BOESE, rolle=BOESE2, luecke=BOESE, ort=BOESE2, kanal=BOESE,
                           pruefhinweise=[BOESE], was_neu=[BOESE2], fassung=2,
                           anschreiben="</textarea>" + BOESE, anzeige_url="javascript:alert(1)",
                           application_id='x"><script>y</script>', seit=BOESE,
                           feedback_offen_seit=BOESE2)]
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
    assert s.count(f'name="csrf" value="{ui.CSRF_TOKEN}"') == 3 + 1       # dazu "Neuer Lauf" im Kopf (H2)
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


def test_offenes_feedback_steht_auf_der_karte(client, falsch):
    """Die Zentrale meldet `feedback_offen_seit`: Felix sieht, dass sein Feedback zu
    dieser Fassung angekommen ist und noch umgesetzt wird. Fehlt es, steht nichts da."""
    am = "2026-10-20T08:30:00+00:00"
    falsch.karten = [karte(fassung=2, feedback_offen_seit=am),
                     karte(application_id=BID2, bindung=B2, firma="Ohne GmbH"),
                     karte(application_id="bw-3", firma="Fehlt GmbH")]
    del falsch.karten[2]["feedback_offen_seit"]                         # aeltere Zentrale
    s = _abschnitt(client)
    zeit = ui._zeit(datetime.fromisoformat(am))
    mit, ohne, fehlt = s.split("<details class=\"karte\"")[1:]
    assert f"Feedback zu Fassung 2 erfasst am {ui._e(zeit)}" in mit
    assert "erfasst am" not in ohne and "erfasst am" not in fehlt


@pytest.mark.parametrize("wert", [BOESE, BOESE2, "morgen <b>früh</b>"])
def test_offenes_feedback_seit_wird_maskiert(client, falsch, wert):        # Review Focus 5
    falsch.karten = [karte(feedback_offen_seit=wert)]
    s = _abschnitt(client)
    assert f"Feedback zu Fassung 1 erfasst am {ui._e(wert)}" in s
    assert "<script" not in s and '"><img' not in s and "<b>früh</b>" not in s


@pytest.mark.parametrize("wert", ["", "   ", 7, ["2026-10-20"], {"x": 1}])
def test_offenes_feedback_seit_ohne_text_zeigt_nichts(client, falsch, wert):
    falsch.karten = [karte(feedback_offen_seit=wert)]
    assert "erfasst am" not in _abschnitt(client)


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
    ("versandziel_geaendert", "Bewerbungsadresse hat sich geändert – Seite neu laden"),
])
@pytest.mark.parametrize("pfad,daten", POSTS)
def test_veraltet_wird_als_hinweis_gezeigt(client, falsch, pfad, daten, grund, text):   # Review Focus 1
    falsch.fehler_post = PultFehler("abgelehnt", grund, {"detail": grund})
    r = _post(client, pfad, **daten)
    assert r.status_code == 303 and r.headers["location"] == f"/freigaben?bw_hinweis={grund}#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert text in s
    for erfolg in ("freigegeben", "nicht_beworben", "feedback", "adresse_gespeichert", "weg_portal"):
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
    for erfolg in ("freigegeben", "nicht_beworben", "feedback", "adresse_gespeichert", "weg_portal"):   # nie eine Erfolgsmeldung
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
    assert z[("POST", f"/bewerbungen/{BID}/versandziel")] == 8
    assert z[("POST", f"/bewerbungen/{BID}/antworten")] == 8
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
    ("freigeben", {"fassung": "1", "bindung": B, "bestaetigt": "ja", "versand_an": "geheim-an@example.org"}),
    ("nicht-bewerben", {"fassung": "1", "bindung": B, "bestaetigt": "ja", "grund": "GRUND-XYZ"}),
    ("feedback", {"fassung": "1", "kommentar": "KOMMENTAR-XYZ", "text": "BRIEFTEXT-XYZ"}),
    ("versandziel", {"fassung": "1", "an": "geheim-an@example.org"}),
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
    for geheim in (SCHLUESSEL, "GRUND-XYZ", "KOMMENTAR-XYZ", "BRIEFTEXT-XYZ", B, "geheim-an@example.org"):
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


# --- H4: Versandweg auf Karte und Verlauf (Plan 2026-10-27, Task 6) ------------------

ADRESSE = "bewerbung@muster.example"
UNKLAR_TEXT = "Versand unklar – in Gmail ‚Gesendet' prüfen"


def weg(kanal="email", an=ADRESSE, warnung=None):
    """Das `versand`-Objekt der Karte (Vertrag Task 4)."""
    return {"kanal": kanal, "an": an, "warnung": warnung}


def _karten(s: str) -> list[str]:
    """Der Abschnitt in seine Karten zerlegt, ohne den Verlauf."""
    return s.split("Zuletzt entschieden")[0].split('<details class="karte"')[1:]


def _formulare(k: str) -> list[tuple[str, str]]:
    return [(m.group(1).rsplit("/", 1)[1], m.group(0))
            for m in re.finditer(r'<form[^>]*action="([^"]*)".*?</form>', k, re.S)]


def _form(k: str, suffix: str, enthaelt: str = "") -> str:
    treffer = [f for s, f in _formulare(k) if s == suffix and enthaelt in f]
    assert len(treffer) == 1, (suffix, enthaelt, [s for s, _ in _formulare(k)])
    return treffer[0]


def _ohne_form(k: str, suffix: str, enthaelt: str = "") -> bool:
    return not [f for s, f in _formulare(k) if s == suffix and enthaelt in f]


def test_kartenzeile_je_weg(client, falsch):
    falsch.karten = [
        karte(firma="Mail", versand=weg(warnung="Freemail-Adresse – passt sie zur Firma?")),
        karte(application_id=BID2, firma="Ohne", versand=weg(an=None, warnung="Versandziel nicht lesbar")),
        karte(application_id="bw-3", firma="Portal", versand=weg("portal", None)),
    ]
    mail, ohne, portal = _karten(_abschnitt(client))
    assert "Versand: E-Mail an bewerbung@muster.example" in mail
    assert '<div class="warnung">Freemail-Adresse – passt sie zur Firma?</div>' in mail
    assert "Adresse fehlt" not in mail and "Handarbeit" not in mail
    assert "Versand: E-Mail – Adresse fehlt" in ohne and "E-Mail an" not in ohne
    assert '<div class="warnung">Versandziel nicht lesbar</div>' in ohne
    assert "Versand: Portal – nach Freigabe Handarbeit nötig" in portal
    assert "E-Mail an" not in portal and "Adresse fehlt" not in portal and "warnung" not in portal


def test_ohne_warnung_kein_warnkasten(client, falsch):
    falsch.karten = [karte(versand=weg())]
    assert 'class="warnung"' not in _abschnitt(client)


def test_der_weg_kommt_aus_versand_nicht_aus_dem_aufnahmekanal(client, falsch):    # Ruling 1
    falsch.karten = [
        karte(firma="A", kanal="portal", versand=weg()),                       # Aufnahme Portal, Weg E-Mail
        karte(application_id=BID2, firma="B", kanal="email", versand=weg("portal", None)),
        karte(application_id="bw-3", firma="C", kanal="email"),                  # Zentrale ohne `versand`
        karte(application_id="bw-4", firma="D", kanal="email", versand="kaputt"),
        karte(application_id="bw-5", firma="E", kanal="email", versand=weg("fax", None)),
    ]
    a, b, c, d, f = _karten(_abschnitt(client))
    assert "Versand: E-Mail an bewerbung@muster.example" in a and ">Freigeben und senden<" in a
    assert "Versand: Portal" in b and ">Freigeben<" in b and ">Freigeben und senden<" not in b
    for unbekannt in (c, d, f):                       # nichts raten: wie vor H4
        assert ">Freigeben<" in unbekannt and ">Freigeben und senden<" not in unbekannt
        assert 'name="versand_an"' not in unbekannt
        assert _ohne_form(unbekannt, "versandziel")
    assert "Versand:" not in c and "Versand:" not in d
    assert "Versand: fax" in f


def test_etikett_folgt_dem_versandweg(client, falsch):
    """Das Etikett oben auf der Karte widerspricht der Versandzeile nicht: mit `versand`
    kommt es aus `versand.kanal`, sonst (Zentrale vor H4, kaputt) wie bisher aus `kanal`."""
    falsch.karten = [
        karte(firma="A", kanal="portal", versand=weg()),                       # Aufnahme Portal, Weg E-Mail
        karte(application_id=BID2, firma="B", kanal="email", versand=weg("portal", None)),
        karte(application_id="bw-3", firma="C", kanal="email"),                  # ohne `versand`
        karte(application_id="bw-4", firma="D", kanal="portal", versand="kaputt"),
        karte(application_id="bw-5", firma="E", kanal="email", versand=weg(BOESE, None)),
        karte(application_id="bw-6", firma="F", kanal="portal", versand={"an": None}),
    ]
    s = _abschnitt(client)
    a, b, c, d, f, g = _karten(s)
    assert '<summary><span class="badge">E-Mail</span><b>A – Data Engineer</b>' in a
    assert '<summary><span class="badge">Portal</span><b>B – Data Engineer</b>' in b
    assert '<summary><span class="badge">E-Mail</span><b>C – Data Engineer</b>' in c
    assert '<summary><span class="badge">Portal</span><b>D – Data Engineer</b>' in d
    assert '<span class="badge">&lt;script&gt;x&lt;/script&gt;</span><b>E – ' in f
    assert '<summary><span class="badge">Portal</span><b>F – Data Engineer</b>' in g
    assert "<script" not in s


def test_versandangaben_werden_maskiert(client, falsch):                         # Review Focus 5
    falsch.karten = [karte(versand=weg(an=BOESE, warnung=BOESE2)),
                     karte(application_id=BID2, versand=weg(BOESE, BOESE2, BOESE)),
                     karte(application_id="bw-3", versand=weg(an=BOESE2, warnung=BOESE))]
    seite = client.get("/freigaben").text
    assert "<script" not in seite and '"><img' not in seite
    assert "Versand: E-Mail an &lt;script&gt;x&lt;/script&gt;" in seite
    assert "&quot;&gt;&lt;img onerror=1&gt;" in seite
    assert 'name="versand_an" value="&lt;script&gt;x&lt;/script&gt;"' in seite
    assert 'name="an" value="&lt;script&gt;x&lt;/script&gt;"' in seite          # Adressfeld vorbefuellt
    assert "Versand: &lt;script&gt;x&lt;/script&gt;" in seite                  # unbekannter Kanal


def test_freigeben_formular_traegt_den_angezeigten_weg(client, falsch):          # Ruling 2 und 4
    falsch.karten = [karte(firma="Mail", versand=weg()),
                     karte(application_id=BID2, bindung=B2, firma="Ohne", versand=weg(an=None)),
                     karte(application_id="bw-3", firma="Portal", versand=weg("portal", None))]
    mail, ohne, portal = _karten(_abschnitt(client))
    freigeben = _form(mail, "freigeben")
    assert ">Freigeben und senden</button>" in freigeben
    assert f'name="versand_an" value="{ADRESSE}"' in freigeben and mail.count('name="versand_an"') == 1
    freigeben = _form(ohne, "freigeben")
    assert ">Freigeben</button>" in freigeben and "Freigeben und senden" not in ohne
    assert 'name="versand_an"' not in ohne                    # weglassen: Zentrale fragt selbst per Mail
    freigeben = _form(portal, "freigeben")
    assert ">Freigeben</button>" in freigeben and "Freigeben und senden" not in portal
    assert 'name="versand_an" value=""' in freigeben and portal.count('name="versand_an"') == 1
    for k in (mail, ohne, portal):
        for suffix in ("nicht-bewerben", "feedback", "versandziel"):
            assert 'name="versand_an"' not in "".join(f for s, f in _formulare(k) if s == suffix)


def test_adressformular_je_weg(client, falsch):
    falsch.karten = [karte(firma="Mail", fassung=3, versand=weg()),
                     karte(application_id=BID2, bindung=B2, firma="Ohne", fassung=4, versand=weg(an=None)),
                     karte(application_id="bw-3", firma="Portal", fassung=5, versand=weg("portal", None))]
    mail, ohne, portal = _karten(_abschnitt(client))
    for k, nr, bid in ((mail, 3, BID), (ohne, 4, BID2), (portal, 5, "bw-3")):
        f = _form(k, "versandziel", 'name="an"')
        assert f'method="post" action="/freigaben/bewerbung/{bid}/versandziel"' in f
        assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in f and f'name="fassung" value="{nr}"' in f
        assert 'type="email" name="an"' in f and 'maxlength="254"' in f
        assert 'name="kanal"' not in f and 'name="bindung"' not in f
    assert 'name="an" value="bewerbung@muster.example"' in _form(mail, "versandziel", 'name="an"')
    assert 'name="an" value=""' in _form(ohne, "versandziel", 'name="an"')
    assert 'name="an" value=""' in _form(portal, "versandziel", 'name="an"')
    # Fehlt die Adresse, ist das Formular nicht eingeklappt; sonst unter einer Ueberschrift.
    assert _form(ohne, "versandziel", 'name="an"').startswith('<form class="aktion primaer adresse"')
    assert "<summary>Bewerbungsadresse" not in ohne
    assert "<summary>Bewerbungsadresse ändern</summary>" in mail
    assert "<summary>Bewerbungsadresse eintragen</summary>" in portal


def test_kein_email_weg_knopf_nur_auf_email_karten(client, falsch):                # Ruling 3 (optional)
    falsch.karten = [karte(firma="Mail", fassung=3, versand=weg()),
                     karte(application_id=BID2, bindung=B2, firma="Ohne", versand=weg(an=None)),
                     karte(application_id="bw-3", firma="Portal", versand=weg("portal", None))]
    mail, ohne, portal = _karten(_abschnitt(client))
    f = _form(mail, "versandziel", 'name="kanal" value="portal"')
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in f and 'name="fassung" value="3"' in f
    assert 'name="an"' not in f and ">Kein E-Mail-Weg (Portal)</button>" in f
    assert _form(ohne, "versandziel", 'name="kanal" value="portal"')
    assert "Kein E-Mail-Weg" not in portal


def test_wartet_auf_durchsicht_zeigt_weg_und_adresse_aber_kein_freigeben(client, falsch):
    falsch.karten = [karte(wartet_auf_durchsicht=True, versand=weg())]
    k, = _karten(_abschnitt(client))
    assert "Versand: E-Mail an bewerbung@muster.example" in k
    assert _form(k, "versandziel", 'name="an"')                       # die Adresse geht schon jetzt
    assert _ohne_form(k, "freigeben") and 'name="versand_an"' not in k


def test_ohne_gueltige_fassung_kein_adressformular(client, falsch):
    falsch.karten = [karte(fassung="x", versand=weg())]
    k, = _karten(_abschnitt(client))
    assert "Versand: E-Mail an" in k and _ohne_form(k, "versandziel")


def test_jedes_formular_hat_die_csrf_marke(client, falsch):
    falsch.karten = [karte(versand=weg()),
                     karte(application_id=BID2, versand=weg(an=None)),
                     karte(application_id="bw-3", versand=weg("portal", None)),
                     karte(application_id="bw-4", wartet_auf_durchsicht=True, versand=weg())]
    s = _abschnitt(client)
    # 4 Karten (17 Formulare) und im Kopf "Neuer Lauf" (H2): jedes traegt die CSRF-Marke.
    assert s.count("<form") == 18 == s.count(f'name="csrf" value="{ui.CSRF_TOKEN}"')


# --- Adresse setzen ------------------------------------------------------------------


def test_adressformular_reicht_fassung_kanal_an_von_weiter(client, falsch):
    r = _post(client, "versandziel", fassung="2", an="  Bewerbung@Muster.example \r\n")
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=adresse_gespeichert#bewerbungen"
    assert falsch.aktionen() == [("POST", f"/bewerbungen/{BID}/versandziel",
                                  {"fassung": 2, "kanal": "email", "an": "Bewerbung@Muster.example",
                                   "von": "mira"})]
    assert falsch.im_loop == []
    assert "Bewerbungsadresse gespeichert" in _abschnitt(client, r.headers["location"])


@pytest.mark.parametrize("an", ["a@b.de", "Vor.Name+bew@Sub.Firma-X.example", "a_b%c-d@x.io", "x" * 249 + "@b.de"])
def test_gueltige_adresse_geht_durch(client, falsch, an):
    assert _post(client, "versandziel", fassung="1", an=an).status_code == 303
    assert falsch.aktionen()[-1][2]["an"] == an


@pytest.mark.parametrize("an", [
    "", "   ", "kein-at", "a@b", "a@b.c", "Felix <a@b.de>", "a@b.de, c@d.de", "a@b.de;c@d.de",
    "a@b.de\nc@d.de", "a b@c.de", "ä@b.de", "a@bü.de", "a@@b.de", "@b.de", "a@.de",
    "x" * 250 + "@b.de", BOESE,
])
def test_adresse_wird_lokal_geprueft(client, falsch, an):
    r = _post(client, "versandziel", fassung="1", an=an)
    assert r.status_code == 422 and falsch.aktionen() == []


def test_adresse_fehlt_im_formular(client, falsch):
    r = client.post(f"/freigaben/bewerbung/{BID}/versandziel", data={"csrf": ui.CSRF_TOKEN, "fassung": "1"},
                    follow_redirects=False)
    assert r.status_code == 422 and falsch.aktionen() == []


@pytest.mark.parametrize("fassung", ["0", "x", "", "²", "1" * 12])
def test_versandziel_prueft_die_fassung(client, falsch, fassung):
    r = _post(client, "versandziel", fassung=fassung, an=ADRESSE)
    assert r.status_code == 422 and falsch.aktionen() == []


def test_kein_email_weg_setzt_portal_ohne_adresse(client, falsch):
    r = _post(client, "versandziel", fassung="1", kanal="portal", an="ignoriert@x.example")
    assert r.status_code == 303 and r.headers["location"] == "/freigaben?bw_hinweis=weg_portal#bewerbungen"
    assert falsch.aktionen() == [("POST", f"/bewerbungen/{BID}/versandziel",
                                  {"fassung": 1, "kanal": "portal", "von": "mira"})]
    assert "Portal" in _abschnitt(client, r.headers["location"])


@pytest.mark.parametrize("kanal", ["fax", "EMAIL", "Portal", " portal", "email,portal", ""])
def test_unbekannter_kanal_ist_422(client, falsch, kanal):
    r = _post(client, "versandziel", fassung="1", kanal=kanal, an=ADRESSE)
    assert r.status_code == 422 and falsch.aktionen() == []


@pytest.mark.parametrize("grund", ["nicht_offen", "eingabe_ungueltig", "unbekannt"])
def test_versandziel_andere_ablehnung_ist_ein_allgemeiner_hinweis(client, falsch, grund):
    falsch.fehler_post = PultFehler("abgelehnt", grund)
    r = _post(client, "versandziel", fassung="1", an=ADRESSE)
    assert r.status_code == 303
    assert r.headers["location"] == f"/freigaben?bw_hinweis=abgelehnt&bw_grund={grund}#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert "nicht angenommen" in s and ui_freigabe_bewerbung._HINWEISE["adresse_gespeichert"][1] not in s


def test_versandziel_antwort_ohne_gesetzt_ist_unklar(client, falsch):
    falsch.antwort["versandziel"] = {"status": "freigegeben"}
    r = _post(client, "versandziel", fassung="1", an=ADRESSE)
    assert r.status_code == 504 and ui_freigabe_bewerbung.UNKLAR_TITEL in r.text


# --- Freigeben mit der bestaetigten Adresse -------------------------------------------


def test_freigeben_schickt_das_angezeigte_versand_an(client, falsch):
    falsch.karten = [karte(versand=weg())]
    seite = client.get("/freigaben").text
    r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja", versand_an=_wert(seite, "versand_an"))
    assert r.status_code == 303 and r.headers["location"] == "/freigaben?bw_hinweis=freigegeben#bewerbungen"
    assert falsch.aktionen() == [("POST", f"/bewerbungen/{BID}/freigeben",
                                  {"fassung": 1, "bindung": B, "von": "mira", "versand_an": ADRESSE})]
    assert falsch.im_loop == []


def test_freigeben_beim_portal_schickt_leeres_versand_an(client, falsch):
    falsch.karten = [karte(versand=weg("portal", None))]
    seite = client.get("/freigaben").text
    assert _wert(seite, "versand_an") == ""
    r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja", versand_an="")
    assert r.status_code == 303
    assert falsch.aktionen()[-1][2] == {"fassung": 1, "bindung": B, "von": "mira", "versand_an": ""}


def test_freigeben_ohne_adresse_laesst_versand_an_weg(client, falsch):
    falsch.karten = [karte(versand=weg(an=None))]
    seite = client.get("/freigaben").text
    assert 'name="versand_an"' not in seite                           # also kein Feld im Formular
    assert _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja").status_code == 303
    assert "versand_an" not in falsch.aktionen()[-1][2]


@pytest.mark.parametrize("wert", [
    "a@b", " ", "a@b.de,c@d.de", "Felix <a@b.de>", "a@b.de ", " a@b.de", "a@b.de\n", "ä@b.de",
    "x" * 250 + "@b.de", BOESE,
])
def test_freigeben_prueft_versand_an_lokal(client, falsch, wert):
    r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja", versand_an=wert)
    assert r.status_code == 422 and falsch.aktionen() == []


def test_nicht_bewerben_gibt_versand_an_nie_weiter(client, falsch):
    r = _post(client, "nicht-bewerben", fassung="1", bindung=B, bestaetigt="ja", versand_an=ADRESSE)
    assert r.status_code == 303
    assert falsch.aktionen()[-1][2] == {"fassung": 1, "bindung": B, "von": "mira"}


def test_adresse_geaendert_ist_ein_hinweis_nie_eine_erfolgsmeldung(client, falsch):      # Ruling 5
    falsch.fehler_post = PultFehler("abgelehnt", "versandziel_geaendert", {"detail": "versandziel_geaendert"})
    r = _post(client, "freigeben", fassung="1", bindung=B, bestaetigt="ja", versand_an=ADRESSE)
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=versandziel_geaendert#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert '<div class="warnung">Bewerbungsadresse hat sich geändert – Seite neu laden</div>' in s
    assert ui_freigabe_bewerbung._HINWEISE["freigegeben"][1] not in s


# --- Zuletzt entschieden ---------------------------------------------------------------


def test_verlauf_text_je_ausgang(client, falsch):                                   # Ruling 6
    falsch.verlauf = [
        verlauf(application_id="bw-1", firma="Eins", ausgang="versendet", versand_an=ADRESSE),
        verlauf(application_id="bw-2", firma="Zwei", ausgang="unklar", versand_an=ADRESSE),
        verlauf(application_id="bw-3", firma="Drei", ausgang="handarbeit", status="blockiert", fassung=3,
                anzeige_url="https://jobs.example.org/3"),
        verlauf(application_id="bw-4", firma="Vier", ausgang="wird_versendet"),
        verlauf(application_id="bw-5", firma="Fuenf", ausgang="abgelehnt", entscheidung="reject"),
        verlauf(application_id="bw-6", firma="Sechs", ausgang="offen", status="blockiert"),
    ]
    s = _abschnitt(client)
    v = s[s.index("Zuletzt entschieden"):]
    eins = _zeile(v, "Eins")
    assert "Versendet an bewerbung@muster.example" in eins and "von Hand" not in eins
    assert "von mira" in eins and "Fassung 2" in eins
    zwei = _zeile(v, "Zwei")
    assert UNKLAR_TEXT in zwei and "Versendet" not in zwei and "von Hand" not in zwei
    drei = _zeile(v, "Drei")
    assert "Freigegeben – bitte von Hand einreichen" in drei
    assert ('<a href="/freigaben/bewerbung/bw-3/anschreiben.pdf?fassung=3" target="_blank" '
            'rel="noopener noreferrer">') in drei
    assert '<a href="https://jobs.example.org/3" target="_blank" rel="noopener noreferrer">' in drei
    vier = _zeile(v, "Vier")
    assert "Wird versendet …" in vier and "von Hand" not in vier and "Versendet" not in vier
    fuenf = _zeile(v, "Fuenf")
    assert "Nicht bewerben" in fuenf and "Versend" not in fuenf and "von Hand" not in fuenf
    sechs = _zeile(v, "Sechs")                      # `offen` schlaegt den Status: noch nicht verarbeitet
    assert "Freigegeben" in sechs and "von Hand" not in sechs and "Wird versendet" not in sechs


WARTET_TEXT = "Versand wartet auf deine Freigabe – Link in der Mail"
HAENGT_TEXT = "Versand hängt – bitte von Hand einreichen oder archivieren"


def test_verlauf_wartet_auf_freigabe_per_mail_und_haengt(client, falsch):
    falsch.verlauf = [
        verlauf(application_id="bw-1", firma="Eins", ausgang="freigabe_per_mail",
                status="wartet_auf_absendefreigabe", versand_an=ADRESSE,
                anzeige_url="https://jobs.example.org/1"),
        verlauf(application_id="bw-2", firma="Zwei", ausgang="haengt", status="wartet_auf_absendefreigabe",
                fassung=4, versand_an=ADRESSE, anzeige_url="https://jobs.example.org/2"),
        verlauf(application_id="bw-3", firma="Drei", ausgang="haengt", status="wartet_auf_absendefreigabe",
                fassung="x", anzeige_url=None),
    ]
    v = _abschnitt(client)
    eins = _zeile(v, "Eins")
    assert WARTET_TEXT in eins and "von Hand" not in eins and "Wird versendet" not in eins
    assert "anschreiben.pdf" not in eins and "Anzeige" not in eins       # Felix klickt in der Mail
    zwei = _zeile(v, "Zwei")
    assert HAENGT_TEXT in zwei and "Freigegeben" not in zwei and "Wird versendet" not in zwei
    assert ('<a href="/freigaben/bewerbung/bw-2/anschreiben.pdf?fassung=4" target="_blank" '
            'rel="noopener noreferrer">') in zwei
    assert '<a href="https://jobs.example.org/2" target="_blank" rel="noopener noreferrer">' in zwei
    drei = _zeile(v, "Drei")                                     # ohne Fassung und Anzeige: keine Links
    assert HAENGT_TEXT in drei and "anschreiben.pdf" not in drei and "Anzeige" not in drei


def test_verlauf_haengt_maskiert_kennung_und_anzeige(client, falsch):            # Review Focus 5
    falsch.verlauf = [verlauf(application_id='bw"><script>k</script>', firma="Eins", ausgang="haengt",
                              fassung=2, anzeige_url='https://x.example/"><script>z</script>',
                              versand_an=BOESE)]
    s = _abschnitt(client)
    assert "<script" not in s and HAENGT_TEXT in _zeile(s, "Eins")
    assert "/freigaben/bewerbung/bw%22%3E%3Cscript%3Ek%3C%2Fscript%3E/anschreiben.pdf?fassung=2" in s
    assert 'href="https://x.example/&quot;&gt;&lt;script&gt;z&lt;/script&gt;"' in s


def test_handarbeit_beim_email_weg_nennt_die_adresse(client, falsch):
    falsch.verlauf = [
        verlauf(application_id="bw-1", firma="Mail", ausgang="handarbeit", status="blockiert", fassung=3,
                versand_an=ADRESSE, anzeige_url="https://jobs.example.org/1"),
        verlauf(application_id="bw-2", firma="Portal", ausgang="handarbeit", status="blockiert",
                versand_an=None),
        verlauf(application_id="bw-3", firma="Boese", ausgang="handarbeit", status="blockiert",
                versand_an=BOESE),
    ]
    s = _abschnitt(client)
    mail = _zeile(s, "Mail")
    assert f"Freigegeben – bitte von Hand einreichen (per E-Mail an {ADRESSE})" in mail
    assert "anschreiben.pdf?fassung=3" in mail and "Anzeige" in mail
    portal = _zeile(s, "Portal")
    assert "Freigegeben – bitte von Hand einreichen" in portal and "E-Mail an" not in portal
    boese = _zeile(s, "Boese")
    assert "<script" not in s and "per E-Mail an &lt;script&gt;x&lt;/script&gt;" in boese


def test_verlauf_ohne_ausgang_bleibt_wie_vor_h4(client, falsch):
    falsch.verlauf = [verlauf(application_id="bw-1", firma="Alt", status="blockiert"),
                      verlauf(application_id="bw-2", firma="Neu", status="archiviert")]
    v = _abschnitt(client)
    assert "Freigegeben – bitte von Hand einreichen" in _zeile(v, "Alt")
    assert "von Hand" not in _zeile(v, "Neu") and "Freigegeben" in _zeile(v, "Neu")


def test_verlauf_versendet_ohne_adresse(client, falsch):
    falsch.verlauf = [verlauf(firma="Ohne", ausgang="versendet", versand_an=None)]
    z = _zeile(_abschnitt(client), "Ohne")
    assert "Versendet" in z and "Versendet an" not in z


def test_verlauf_maskiert_adresse_und_unbekannten_ausgang(client, falsch):          # Review Focus 5
    falsch.verlauf = [
        verlauf(application_id="bw-1", firma="Eins", ausgang="versendet", versand_an=BOESE),
        verlauf(application_id="bw-2", firma="Zwei", ausgang=BOESE2),
        verlauf(application_id="bw-3", firma="Drei", ausgang="vielleicht <b>"),
        verlauf(application_id="bw-4", firma="Vier", ausgang=7),
        verlauf(application_id="bw-5", firma="Fuenf", ausgang="versendet", versand_an=BOESE2),
    ]
    s = _abschnitt(client)
    assert "<script" not in s and '"><img' not in s and "vielleicht <b>" not in s
    assert "Versendet an &lt;script&gt;x&lt;/script&gt;" in _zeile(s, "Eins")
    assert "&quot;&gt;&lt;img onerror=1&gt;" in _zeile(s, "Zwei")
    assert "vielleicht &lt;b&gt;" in _zeile(s, "Drei")
    assert "Freigegeben" not in _zeile(s, "Drei")                    # unbekannt: wie geliefert
    assert "7" in _zeile(s, "Vier")
    assert "Versendet an &quot;&gt;&lt;img onerror=1&gt;" in _zeile(s, "Fuenf")


# --- H2: Hermes-Zeile, Lauf-Kasten, Pruefnotiz und Antworten (Plan 2026-10-27, Task 10) --------------

HERMES_TEXTE = {"bereit": "Hermes: bereit", "arbeitet": "Hermes arbeitet …",
                "pausiert": "Hermes pausiert: Kontingent", "nicht_erreichbar": "Hermes nicht erreichbar",
                "unbekannt": "Hermes: Status unbekannt"}
WEG_TEXT = "Bewerbungs-Zentrale ist gerade nicht erreichbar"
NICHT_VERBUNDEN_TEXT = "Bewerbungs-Zentrale ist nicht verbunden"
FRAGEN_HINWEIS = "Gilt nur für diese Bewerbung. Soll es allgemein gelten, am PC in profil/ übernehmen."


def notiz(**kw):
    """Die `pruefnotiz` einer Karte (Vertrag Task 7: Pruefnotiz.als_dict() mit `fragen[].antwort`)."""
    n = {"zusammenfassung": "Der Brief passt zur Stelle, zwei Angaben sind nicht belegt.",
         "geprueft": ["Anschrift stimmt", "Datum heute"], "geaendert": ["Absatz 2 gekürzt"],
         "quellen": ["https://firma.example/karriere"],
         "fragen": [{"id": "f1", "frage": "Ab wann bist du verfügbar?", "antwort": None},
                    {"id": "f2", "frage": "Welches Gehalt erwartest du?", "antwort": None}]}
    n.update(kw)
    return n


def _kopf(s: str) -> str:
    """Was vor den Karten und dem Verlauf steht: Hinweis, Hermes-Zeile, Lauf-Kasten, Knoepfe."""
    return s.split('<details class="karte"')[0].split("Zuletzt entschieden")[0]


def _tag(html_text: str, name: str) -> str:
    return re.search(rf'<input[^>]*name="{name}"[^>]*>', html_text).group(0)


def _post_lauf(c, pfad, **daten):
    return c.post(f"/freigaben/bewerbung/{pfad}", data={"csrf": ui.CSRF_TOKEN, **daten},
                  follow_redirects=False)


# --- Hermes-Zeile -----------------------------------------------------------------------


@pytest.mark.parametrize("zustand,grund", [("bereit", None), ("arbeitet", None), ("pausiert", "kontingent"),
                                           ("nicht_erreichbar", None), ("unbekannt", None)])
def test_hermes_zeile_je_zustand(client, falsch, zustand, grund):
    falsch.uebersicht = uebersicht(zustand=zustand, grund=grund)
    kopf = _kopf(_abschnitt(client))
    assert HERMES_TEXTE[zustand] in kopf
    for anderer, text in HERMES_TEXTE.items():
        if anderer != zustand:
            assert text not in kopf


@pytest.mark.parametrize("zustand,grund,text", [
    ("pausiert", "Quota <b>leer</b>", "Hermes pausiert: Quota &lt;b&gt;leer&lt;/b&gt;"),
    ("pausiert", BOESE, "Hermes pausiert: &lt;script&gt;x&lt;/script&gt;"),
    ("pausiert", None, "Hermes pausiert<"),
    ("pausiert", "  ", "Hermes pausiert<"),
    (BOESE, None, "Hermes: Status unbekannt"),
    (BOESE2, BOESE, "Hermes: Status unbekannt"),
    (None, None, "Hermes: Status unbekannt"),
    (7, None, "Hermes: Status unbekannt"),
    ("schläft", None, "Hermes: Status unbekannt"),
])
def test_hermes_zeile_maskiert_und_raet_nicht(client, falsch, zustand, grund, text):    # Review Focus 5
    falsch.uebersicht = uebersicht(zustand=zustand, grund=grund)
    s = _abschnitt(client)
    assert text in s
    assert "<script" not in s and '"><img' not in s and "<b>leer</b>" not in s
    if "unbekannt" in text:                       # ein unbekannter Zustand wird nicht wiedergegeben
        assert "schläft" not in s and "&lt;script" not in s


def test_hermes_zeile_ohne_hermes_objekt(client, falsch):
    for hermes in ("kaputt", None, 3, {}):
        falsch.uebersicht = {**uebersicht(), "hermes": hermes}
        assert HERMES_TEXTE["unbekannt"] in _kopf(_abschnitt(client))


# --- Lauf-Kasten ------------------------------------------------------------------------


def test_lauf_kasten_zeigt_zaehler_staende_begruendung_und_dauer(client, falsch):
    falsch.uebersicht = uebersicht(lauf(), moeglich=False)
    kopf = _kopf(_abschnitt(client))
    am = ui._e(ui._zeit(datetime.fromisoformat(LAUF_AM)))
    assert f"Lauf vom {am}: läuft" in kopf
    assert "Alpha GmbH – Data Engineer (Score 4,3): vorgelegt" in kopf
    assert "Beta AG – Analyst (Score 4,0): in Arbeit" in kopf
    assert "Gamma SE – ML Engineer (Score 3,6): aufgegeben" in kopf
    assert "Delta KG – Architect (Score 3,5): offen" in kopf
    assert "bewertet 9 · unter 3,5: 5 · Sperrfrist: 1 · Lauf voll: 1" in kopf
    assert "Zwei Stellen passen zum Profil" in kopf
    assert "Dauer 12 min · 31 Modellaufrufe" in kopf
    assert kopf.index("Alpha GmbH") < kopf.index("Beta AG") < kopf.index("Gamma SE") < kopf.index("Delta KG")
    assert falsch.im_loop == []


@pytest.mark.parametrize("status,text", [("angefordert", "angefordert"), ("laeuft", "läuft"),
                                         ("fertig", "fertig"), ("abgebrochen", "abgebrochen")])
def test_lauf_kasten_status(client, falsch, status, text):
    falsch.uebersicht = uebersicht(lauf(status=status), moeglich=status in ("fertig", "abgebrochen"))
    am = ui._e(ui._zeit(datetime.fromisoformat(LAUF_AM)))
    assert f"Lauf vom {am}: {text}<" in _kopf(_abschnitt(client))


def test_lauf_kasten_ohne_lauf_und_ohne_bewerbungen(client, falsch):
    falsch.uebersicht = uebersicht(None)
    kopf = _kopf(_abschnitt(client))
    assert "Lauf vom" not in kopf and "Noch kein Lauf" in kopf and HERMES_TEXTE["bereit"] in kopf
    falsch.uebersicht = uebersicht(lauf(bewerbungen=[], bewertet=0, unter_schwelle=0, sperrfrist=0,
                                       lauf_voll=0, begruendung=None, dauer_s=0.0, modellaufrufe=None))
    kopf = _kopf(_abschnitt(client))
    assert "bewertet 0 · unter 3,5: 0 · Sperrfrist: 0 · Lauf voll: 0" in kopf
    assert "Dauer 0 min" in kopf and "Modellaufrufe" not in kopf and "Begründung" not in kopf


def test_lauf_kasten_unbekannte_werte_werden_nicht_geraten(client, falsch):
    falsch.uebersicht = uebersicht(lauf(
        angefordert_am=None, status="wartet", bewertet=None, unter_schwelle="viel", sperrfrist=True,
        lauf_voll=-1, dauer_s="lang", modellaufrufe="x",
        bewerbungen=["kaputt", {"firma": "Eins", "rolle": "R", "score": None, "stand": "neu"},
                     {"firma": "Zwei", "rolle": "R", "score": True, "stand": None}]))
    kopf = _kopf(_abschnitt(client))
    assert "Lauf vom ?: wartet" in kopf
    assert "bewertet ? · unter 3,5: ? · Sperrfrist: ? · Lauf voll: ?" in kopf
    assert "Eins – R (Score –): neu" in kopf and "Zwei – R (Score –): " in kopf
    assert "Dauer ? min" in kopf and "Modellaufrufe" not in kopf


def test_lauf_kasten_maskiert_alles(client, falsch):                                  # Review Focus 5
    falsch.uebersicht = uebersicht(lauf(
        lauf_id='x"><script>y</script>', angefordert_am=BOESE2, begruendung=BOESE,
        bewerbungen=[{"application_id": "bw-1", "firma": BOESE, "rolle": BOESE2, "score": 4.0, "stand": BOESE},
                     {"application_id": "bw-2", "firma": "Zwei", "rolle": "R", "score": "hoch",
                      "stand": "vielleicht <b>"}]),
        zustand="pausiert", grund=BOESE, moeglich=False)
    seite = client.get("/freigaben").text
    assert "<script" not in seite and '"><img' not in seite and "vielleicht <b>" not in seite
    assert "&lt;script&gt;x&lt;/script&gt; – &quot;&gt;&lt;img onerror=1&gt; (Score 4,0): &lt;script&gt;" in seite
    assert "Zwei – R (Score –): vielleicht &lt;b&gt;" in seite
    assert "Begründung: &lt;script&gt;x&lt;/script&gt;" in seite
    assert "Lauf vom &quot;&gt;&lt;img onerror=1&gt;: läuft" in seite
    assert 'action="/freigaben/bewerbung/lauf/x%22%3E%3Cscript%3Ey%3C%2Fscript%3E/abbrechen"' in seite


# --- Knoepfe: Neuer Lauf / Lauf abbrechen --------------------------------------------------


def test_neuer_lauf_nur_wenn_moeglich(client, falsch):
    falsch.uebersicht = uebersicht(None, moeglich=True)
    s = _abschnitt(client)
    f = _form(_kopf(s), "lauf")
    assert 'method="post" action="/freigaben/bewerbung/lauf"' in f
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in f and ">Neuer Lauf</button>" in f
    assert "Lauf läuft" not in s and _ohne_form(s, "abbrechen")
    falsch.uebersicht = uebersicht(lauf(), moeglich=False)
    s = _abschnitt(client)
    assert _ohne_form(s, "lauf") and "Neuer Lauf" not in s and "Lauf läuft" in _kopf(s)


@pytest.mark.parametrize("status,da", [("angefordert", True), ("laeuft", True), ("fertig", False),
                                       ("abgebrochen", False), ("komisch", False)])
def test_lauf_abbrechen_nur_fuer_offene_laeufe(client, falsch, status, da):
    falsch.uebersicht = uebersicht(lauf(status=status), moeglich=not da)
    s = _abschnitt(client)
    if da:
        f = _form(_kopf(s), "abbrechen")
        assert f'method="post" action="/freigaben/bewerbung/lauf/{LAUF_ID}/abbrechen"' in f
        assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in f and ">Lauf abbrechen</button>" in f
    else:
        assert _ohne_form(s, "abbrechen") and "Lauf abbrechen" not in s


def test_ohne_lauf_id_kein_abbrechen_knopf(client, falsch):
    for kaputt in (None, "", 7, [LAUF_ID]):
        falsch.uebersicht = uebersicht(lauf(lauf_id=kaputt), moeglich=False)
        assert _ohne_form(_abschnitt(client), "abbrechen")


def test_lauf_knoepfe_sind_nur_fuer_freigeben_sichtbar(client_lesen, falsch):
    s = client_lesen.get("/freigaben").text
    assert "Neuer Lauf" not in s and "Hermes" not in s and falsch.aufrufe == []


# --- Lauf starten und abbrechen -----------------------------------------------------------


def test_neuer_lauf_reicht_von_weiter(client, falsch):
    r = _post_lauf(client, "lauf")
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=lauf_gestartet#bewerbungen"
    assert falsch.aktionen() == [("POST", "/laeufe", {"von": "mira"})]
    assert falsch.im_loop == []
    assert "Neuer Lauf angefordert" in _abschnitt(client, r.headers["location"])


def test_lauf_abbrechen_reicht_von_weiter(client, falsch):
    r = _post_lauf(client, f"lauf/{LAUF_ID}/abbrechen")
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=lauf_abgebrochen#bewerbungen"
    assert falsch.aktionen() == [("POST", f"/laeufe/{LAUF_ID}/abbrechen", {"von": "mira"})]
    assert falsch.im_loop == []
    assert "Lauf abgebrochen" in _abschnitt(client, r.headers["location"])


def test_lauf_kennung_wird_im_pfad_maskiert(client, falsch):
    r = _post_lauf(client, "lauf/hl-1%3Fx%3D1%23y/abbrechen")
    assert r.status_code == 303
    assert falsch.aktionen()[-1][1] == "/laeufe/hl-1%3Fx%3D1%23y/abbrechen"


def test_lauf_zeitlimits(client, falsch):
    assert _post_lauf(client, "lauf").status_code == 303
    assert _post_lauf(client, f"lauf/{LAUF_ID}/abbrechen").status_code == 303
    client.get("/freigaben")
    z = {(m, p): t for m, p, t in falsch.zeitlimits}
    assert z[("POST", "/laeufe")] == 8
    assert z[("POST", f"/laeufe/{LAUF_ID}/abbrechen")] == 30
    assert z[("GET", LAUF_AKTUELL)] <= 3
    assert falsch.im_loop == []


LAUF_POSTS = [("lauf", "laeufe"), (f"lauf/{LAUF_ID}/abbrechen", "abbrechen")]


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_ohne_csrf_403(client, falsch, pfad, _):
    for daten in ({}, {"csrf": "falsch"}):
        r = client.post(f"/freigaben/bewerbung/{pfad}", data=daten, follow_redirects=False)
        assert r.status_code == 403
    assert falsch.aktionen() == []


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_rolle_lesen_darf_nicht_posten(client_lesen, falsch, pfad, _):
    r = _post_lauf(client_lesen, pfad)
    assert r.status_code == 403 and "Nicht für diese Anmeldung" in r.text and falsch.aufrufe == []
    assert ui._pfad_erlaubt("freigeben", f"/freigaben/bewerbung/{pfad}") is True
    assert ui._pfad_erlaubt("lesen", f"/freigaben/bewerbung/{pfad}") is False


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_ohne_anmeldung_nichts(falsch, monkeypatch, pfad, _):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")
    c = TestClient(ui.app, headers=HOST)
    assert _post_lauf(c, pfad).status_code == 403
    assert falsch.aufrufe == []


@pytest.mark.parametrize("pfad,grund,text", [
    ("lauf", "lauf_laeuft", "Es läuft schon ein Lauf."),
    (f"lauf/{LAUF_ID}/abbrechen", "lauf_unbekannt", "Diesen Lauf gibt es nicht – Seite neu laden."),
    (f"lauf/{LAUF_ID}/abbrechen", "lauf_nicht_offen", "Dieser Lauf ist schon beendet – Seite neu laden."),
])
def test_lauf_ablehnung_wird_als_hinweis_gezeigt(client, falsch, pfad, grund, text):
    falsch.fehler_post = PultFehler("abgelehnt", grund, {"detail": grund})
    r = _post_lauf(client, pfad)
    assert r.status_code == 303 and r.headers["location"] == f"/freigaben?bw_hinweis={grund}#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert f'<div class="warnung">{text}</div>' in s
    for erfolg in ("lauf_gestartet", "lauf_abgebrochen"):
        assert ui_freigabe_bewerbung._HINWEISE[erfolg][1] not in s


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_andere_ablehnung_ist_ein_allgemeiner_hinweis(client, falsch, pfad, _):
    falsch.fehler_post = PultFehler("abgelehnt", "eingabe_ungueltig")
    r = _post_lauf(client, pfad)
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=abgelehnt&bw_grund=eingabe_ungueltig#bewerbungen"
    assert "nicht angenommen" in _abschnitt(client, r.headers["location"])


@pytest.mark.parametrize("art", ["nicht_erreichbar", "unbekannt"])
@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_zeitueberschreitung_ist_unklar(client, falsch, pfad, _, art):             # Review Focus 4
    falsch.fehler_post = PultFehler(art, "TimeoutError")
    r = _post_lauf(client, pfad)
    assert r.status_code == 504 and ui_freigabe_bewerbung.UNKLAR_TITEL in r.text
    assert "location" not in r.headers and "Nichts wurde" not in r.text
    for erfolg in ("lauf_gestartet", "lauf_abgebrochen"):
        assert ui_freigabe_bewerbung._HINWEISE[erfolg][1] not in r.text


@pytest.mark.parametrize("antwort", [{}, {"lauf": None}, {"lauf": "x"}, [], "ok"])
@pytest.mark.parametrize("pfad,schluessel", LAUF_POSTS)
def test_lauf_unklare_erfolgsantwort_ist_unklar(client, falsch, pfad, schluessel, antwort):
    falsch.antwort[schluessel] = antwort
    r = _post_lauf(client, pfad)
    assert r.status_code == 504 and ui_freigabe_bewerbung.UNKLAR_TITEL in r.text


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_nicht_verbunden_nach_post_503(client, falsch, pfad, _):
    falsch.fehler_post = PultFehler("nicht_verbunden", "401")
    r = _post_lauf(client, pfad)
    assert r.status_code == 503 and "nicht verbunden" in r.text


@pytest.mark.parametrize("pfad,_", LAUF_POSTS)
def test_lauf_unklarer_ausgang_wird_protokolliert_ohne_schluessel(client, falsch, monkeypatch, caplog, pfad, _):
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    falsch.fehler_post = PultFehler("nicht_erreichbar", "TimeoutError", {"detail": "RUMPF-XYZ"})
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        assert _post_lauf(client, pfad).status_code == 504
    zeilen = [m for m in _meldungen(caplog) if "Lauf" in m]
    assert len(zeilen) == 1 and "nicht_erreichbar" in zeilen[0] and "TimeoutError" in zeilen[0]
    assert SCHLUESSEL not in caplog.text and "RUMPF-XYZ" not in caplog.text


# --- Faellt /laeufe/aktuell aus, bleiben die Karten ----------------------------------------


@pytest.mark.parametrize("fehler,text", [
    (PultFehler("nicht_erreichbar", "TimeoutError"), WEG_TEXT),
    (PultFehler("unbekannt", "500"), WEG_TEXT),
    (PultFehler("abgelehnt", "Not Found"), WEG_TEXT),       # eine Zentrale ohne die neue Route
    (PultFehler("nicht_verbunden", "401"), NICHT_VERBUNDEN_TEXT),
    (RuntimeError("kaputt"), WEG_TEXT),
])
def test_ausfall_von_laeufe_aktuell_laesst_die_karten_stehen(client, falsch, fehler, text):   # Review Focus 4
    falsch.fehler_lauf = fehler
    falsch.verlauf = [verlauf()]
    s = _abschnitt(client)
    assert text in _kopf(s)
    assert "Muster GmbH – Data Engineer" in s and "Alt AG" in s
    assert f'action="/freigaben/bewerbung/{BID}/freigeben"' in s                 # die Karte ist bedienbar
    assert not any(t in s for t in HERMES_TEXTE.values())
    assert _ohne_form(s, "lauf") and _ohne_form(s, "abbrechen") and "Neuer Lauf" not in s


@pytest.mark.parametrize("antwort", [
    "kaputt", [], {}, None,
    {"lauf": None, "hermes": {"zustand": "bereit"}},                          # neuer_lauf_moeglich fehlt
    {"lauf": None, "hermes": {"zustand": "bereit"}, "neuer_lauf_moeglich": "ja"},
    {"lauf": "x", "hermes": {"zustand": "bereit"}, "neuer_lauf_moeglich": True},
])
def test_kaputte_antwort_von_laeufe_aktuell_zeigt_keinen_lauf_status(client, falsch, antwort):
    falsch.uebersicht = antwort
    s = _abschnitt(client)
    assert WEG_TEXT in _kopf(s) and "Muster GmbH – Data Engineer" in s
    assert not any(t in s for t in HERMES_TEXTE.values()) and "Neuer Lauf" not in s


def test_kaputter_lauf_reisst_nur_den_kopf_nicht_den_abschnitt(client, falsch):
    falsch.uebersicht = uebersicht(lauf(bewerbungen=[{"firma": "A", "rolle": "B", "score": 10 ** 400}]))
    s = _abschnitt(client)                                                  # OverflowError beim Formatieren
    assert WEG_TEXT in _kopf(s) and "Muster GmbH – Data Engineer" in s


def test_ausfall_von_laeufe_aktuell_wird_protokolliert(client, falsch, monkeypatch, caplog):
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    falsch.fehler_lauf = PultFehler("nicht_erreichbar", "TimeoutError", {"detail": "RUMPF-XYZ"})
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        client.get("/freigaben")
    assert any("nicht_erreichbar" in m and "TimeoutError" in m and "Lauf" in m for m in _meldungen(caplog))
    assert SCHLUESSEL not in caplog.text and "RUMPF-XYZ" not in caplog.text
    falsch.fehler_lauf = RuntimeError("kaputt")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        assert client.get("/freigaben").status_code == 200
    assert any(x.exc_info for x in caplog.records if x.name == "sales-ui")


def test_ausfall_von_laeufe_aktuell_sperrt_den_abschnitt_nicht(client, falsch):
    """Anders als die Liste (60 s Sperre im Zwischenspeicher) wird der Lauf-Status jedes Mal neu gelesen."""
    falsch.fehler_lauf = PultFehler("nicht_erreichbar", "TimeoutError")
    assert WEG_TEXT in _kopf(_abschnitt(client))
    falsch.fehler_lauf = None
    assert HERMES_TEXTE["bereit"] in _kopf(_abschnitt(client))
    assert ui_freigabe_bewerbung._speicher.frisch_fehler() is None


def test_lauf_wird_nach_der_liste_gelesen(client, falsch):
    client.get("/freigaben")
    gets = [p for m, p, _ in falsch.aufrufe if m == "GET"]
    assert gets == [OFFEN, ENTSCHIEDEN, LAUF_AKTUELL]
    assert ("GET", LAUF_AKTUELL, ui_freigabe_bewerbung.LESE_ZEITLIMIT_S) in falsch.zeitlimits


# --- Pruefnotiz und offene Fragen auf der Karte ------------------------------------------------


def test_karte_zeigt_pruefnotiz_und_offene_fragen(client, falsch):
    falsch.karten = [karte(fassung=2, pruefnotiz=notiz(fragen=[
        {"id": "f1", "frage": "Ab wann bist du verfügbar?", "antwort": None},
        {"id": "f2", "frage": "Welches Gehalt erwartest du?", "antwort": "65.000 EUR"}]))]
    k, = _karten(_abschnitt(client))
    assert "<b>Prüfnotiz</b>" in k and "Der Brief passt zur Stelle, zwei Angaben sind nicht belegt." in k
    for titel in ("Geprüft", "Geändert", "Quellen"):
        assert f"<b>{titel}</b>" in k
    for eintrag in ("Anschrift stimmt", "Datum heute", "Absatz 2 gekürzt", "https://firma.example/karriere"):
        assert f"<li>{eintrag}</li>" in k
    assert "<b>Offene Fragen</b>" in k
    f = _form(k, "antworten")
    assert f'method="post" action="/freigaben/bewerbung/{BID}/antworten"' in f
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in f and 'name="fassung" value="2"' in f
    eingabe = _tag(f, "antwort_f1")
    assert 'type="text"' in eingabe and 'maxlength="500"' in eingabe and "required" not in eingabe
    assert "Ab wann bist du verfügbar?" in f
    assert 'name="antwort_f2"' not in k and "Welches Gehalt erwartest du?" in k    # beantwortet: Text, kein Feld
    assert "Deine Antwort: 65.000 EUR" in k
    assert FRAGEN_HINWEIS in k
    assert (k.index("<b>Prüfnotiz</b>") < k.index("<b>Offene Fragen</b>")
            < k.index(f'action="/freigaben/bewerbung/{BID}/freigeben"'))


def test_alle_fragen_beantwortet_kein_formular(client, falsch):
    falsch.karten = [karte(pruefnotiz=notiz(fragen=[
        {"id": "f1", "frage": "Ab wann?", "antwort": "Sofort"},
        {"id": "f2", "frage": "Gehalt?", "antwort": "65.000 EUR"}]))]
    k, = _karten(_abschnitt(client))
    assert "Deine Antwort: Sofort" in k and "Deine Antwort: 65.000 EUR" in k
    assert _ohne_form(k, "antworten") and 'name="antwort_' not in k
    assert FRAGEN_HINWEIS in k


def test_pruefnotiz_ohne_fragen_und_leere_listen(client, falsch):
    falsch.karten = [karte(pruefnotiz=notiz(geprueft=[], geaendert=[], quellen=[], fragen=[]))]
    k, = _karten(_abschnitt(client))
    assert "<b>Prüfnotiz</b>" in k and "Der Brief passt zur Stelle" in k
    for titel in ("Geprüft", "Geändert", "Quellen", "Offene Fragen"):
        assert f"<b>{titel}</b>" not in k
    assert _ohne_form(k, "antworten") and FRAGEN_HINWEIS not in k


@pytest.mark.parametrize("wert", ["MISSING", None, "kaputt", [], {}, 7])
def test_ohne_brauchbare_pruefnotiz_nichts_neues_auf_der_karte(client, falsch, wert):
    falsch.karten = [karte() if wert == "MISSING" else karte(pruefnotiz=wert)]
    k, = _karten(_abschnitt(client))
    assert "Prüfnotiz" not in k and "Offene Fragen" not in k and _ohne_form(k, "antworten")
    assert _form(k, "feedback") and _form(k, "freigeben")                         # der Rest der Karte bleibt


def test_pruefnotiz_ueberspringt_kaputte_eintraege(client, falsch):
    falsch.karten = [karte(pruefnotiz=notiz(
        zusammenfassung=7, geprueft=["ok", 3, None, ""], geaendert="kaputt", quellen=None,
        fragen=["kaputt", {"id": "f1"}, {"id": 5, "frage": "x"}, {"frage": "ohne Kennung"},
                {"id": "f2", "frage": "Echte Frage?", "antwort": 7},
                {"id": "f3", "frage": "Leer?", "antwort": ""}]))]
    k, = _karten(_abschnitt(client))
    assert "<li>ok</li>" in k
    assert "Echte Frage?" in k and "Leer?" in k and "ohne Kennung" not in k
    assert 'name="antwort_f2"' in k and 'name="antwort_f3"' in k                  # 7 und "" zaehlen als unbeantwortet
    assert 'name="antwort_f1"' not in k


def test_pruefnotiz_und_fragen_werden_maskiert(client, falsch):                    # Review Focus 5
    falsch.karten = [karte(pruefnotiz=notiz(
        zusammenfassung=BOESE, geprueft=[BOESE2], geaendert=[BOESE], quellen=["javascript:alert(1)", BOESE2],
        fragen=[{"id": "f1", "frage": BOESE, "antwort": BOESE2},
                {"id": 'f2"><script>k</script>', "frage": BOESE2, "antwort": None},
                {"id": "f3", "frage": BOESE2, "antwort": None}]))]
    seite = client.get("/freigaben").text
    assert "<script" not in seite and '"><img' not in seite
    assert "&lt;script&gt;x&lt;/script&gt;" in seite and "Deine Antwort: &quot;&gt;&lt;img onerror=1&gt;" in seite
    assert '<a href="javascript:' not in seite                                    # Quellen sind Text, nie Links
    assert 'name="antwort_f3"' in seite and "antwort_f2" not in seite             # Kennung nicht erlaubt: kein Feld


def test_ohne_gueltige_fassung_keine_antwortfelder(client, falsch):
    falsch.karten = [karte(fassung="x", pruefnotiz=notiz())]
    k, = _karten(_abschnitt(client))
    assert "Ab wann bist du verfügbar?" in k and _ohne_form(k, "antworten") and 'name="antwort_' not in k


def test_antwortfelder_auch_waehrend_wartet_auf_durchsicht(client, falsch):
    falsch.karten = [karte(wartet_auf_durchsicht=True, pruefnotiz=notiz())]
    k, = _karten(_abschnitt(client))
    assert _form(k, "antworten") and _ohne_form(k, "freigeben")


# --- Antworten abschicken ----------------------------------------------------------------------


def test_antworten_senden_nur_nicht_leere_felder(client, falsch):
    r = _post(client, "antworten", fassung="2", antwort_f1="  ab sofort  ", antwort_f2="",
              antwort_f3="   ", antwort_f4="40 h")
    assert r.status_code == 303
    assert r.headers["location"] == "/freigaben?bw_hinweis=antworten_erfasst#bewerbungen"
    assert falsch.aktionen() == [("POST", f"/bewerbungen/{BID}/antworten", {
        "fassung": 2, "von": "mira",
        "antworten": [{"frage_id": "f1", "antwort": "ab sofort"}, {"frage_id": "f4", "antwort": "40 h"}]})]
    assert falsch.im_loop == []
    assert "Antworten erfasst" in _abschnitt(client, r.headers["location"])


def test_antworten_aus_dem_gerenderten_formular(client, falsch):
    """Ende zu Ende: die Felder der Seite abschicken, eines leer lassen."""
    falsch.karten = [karte(fassung=3, pruefnotiz=notiz(fragen=[
        {"id": "f1", "frage": "A?", "antwort": None}, {"id": "f2", "frage": "B?", "antwort": "schon da"},
        {"id": "f3", "frage": "C?", "antwort": None}]))]
    k, = _karten(_abschnitt(client))
    f = _form(k, "antworten")
    namen = re.findall(r'name="(antwort_[^"]*)"', f)
    assert namen == ["antwort_f1", "antwort_f3"]
    daten = {"fassung": _wert(f, "fassung"), namen[0]: "", namen[1]: "Dritte Antwort"}
    r = _post(client, "antworten", **daten)
    assert r.status_code == 303
    assert falsch.aktionen()[-1][2] == {"fassung": 3, "von": "mira",
                                        "antworten": [{"frage_id": "f3", "antwort": "Dritte Antwort"}]}


def test_antworten_alle_leer_ist_ein_hinweis_ohne_aufruf(client, falsch):
    for daten in ({}, {"antwort_f1": ""}, {"antwort_f1": "  ", "antwort_f2": "\r\n"}, {"quatsch": "x"}):
        r = _post(client, "antworten", fassung="1", **daten)
        assert r.status_code == 303 and r.headers["location"] == "/freigaben?bw_hinweis=keine_antwort#bewerbungen"
    assert falsch.aktionen() == []
    assert "Keine Antwort eingegeben" in _abschnitt(client, "/freigaben?bw_hinweis=keine_antwort")


def test_antworten_grenzen_und_einzeilig(client, falsch):
    r = _post(client, "antworten", fassung="1", antwort_f1="x" * 500)
    assert r.status_code == 303 and r.headers["location"].endswith("antworten_erfasst#bewerbungen")
    assert falsch.aktionen()[-1][2]["antworten"] == [{"frage_id": "f1", "antwort": "x" * 500}]
    r = _post(client, "antworten", fassung="1", antwort_f1="  ok \r\n")        # Rand-Leerraum faellt weg
    assert falsch.aktionen()[-1][2]["antworten"] == [{"frage_id": "f1", "antwort": "ok"}]
    n = len(falsch.aktionen())
    for zu_lang_oder_mehrzeilig in ("x" * 501, "zwei\nZeilen", "zwei\r\nZeilen", "zwei\rZeilen"):
        r = _post(client, "antworten", fassung="1", antwort_f1="gut", antwort_f2=zu_lang_oder_mehrzeilig)
        assert r.status_code == 303
        assert r.headers["location"] == "/freigaben?bw_hinweis=antwort_ungueltig#bewerbungen"
    assert len(falsch.aktionen()) == n                       # nichts davon geht an die Zentrale (alle oder keine)
    assert "Antwort ungültig – höchstens 500 Zeichen." in _abschnitt(client, "/freigaben?bw_hinweis=antwort_ungueltig")


@pytest.mark.parametrize("fassung", ["0", "x", "", "²", "1" * 12])
def test_antworten_prueft_die_fassung(client, falsch, fassung):
    r = _post(client, "antworten", fassung=fassung, antwort_f1="Ja")
    assert r.status_code == 422 and falsch.aktionen() == []


@pytest.mark.parametrize("feld", ['antwort_f1"x', "antwort_f 1", "antwort_" + "f" * 41, "antwort_ä", "antwort_f1/../x"])
def test_antworten_prueft_die_fragekennung(client, falsch, feld):
    r = _post(client, "antworten", fassung="1", **{feld: "Ja"})
    assert r.status_code == 422 and falsch.aktionen() == []


def test_antworten_hoechstens_fuenf_und_keine_doppelten(client, falsch):
    sechs = {f"antwort_f{i}": "Ja" for i in range(1, 7)}
    r = _post(client, "antworten", fassung="1", **sechs)
    assert r.status_code == 422 and falsch.aktionen() == []
    fuenf = {f"antwort_f{i}": "Ja" for i in range(1, 6)}
    assert _post(client, "antworten", fassung="1", **fuenf).status_code == 303
    assert len(falsch.aktionen()[-1][2]["antworten"]) == 5
    n = len(falsch.aktionen())
    doppelt = urllib.parse.urlencode([("csrf", ui.CSRF_TOKEN), ("fassung", "1"),
                                      ("antwort_f1", "a"), ("antwort_f1", "b")])
    r = client.post(f"/freigaben/bewerbung/{BID}/antworten", follow_redirects=False, content=doppelt,
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 422 and len(falsch.aktionen()) == n


@pytest.mark.parametrize("grund,text", [
    ("fassung_veraltet", "Diese Fassung ist veraltet – Seite neu laden"),
    ("antwort_ungueltig", "Antwort ungültig – höchstens 500 Zeichen."),
    ("frage_unbekannt", "Diese Frage gibt es nicht mehr – Seite neu laden."),
])
def test_antworten_ablehnung_wird_als_hinweis_gezeigt(client, falsch, grund, text):
    falsch.fehler_post = PultFehler("abgelehnt", grund, {"detail": grund})
    r = _post(client, "antworten", fassung="1", antwort_f1="Ja")
    assert r.status_code == 303 and r.headers["location"] == f"/freigaben?bw_hinweis={grund}#bewerbungen"
    s = _abschnitt(client, r.headers["location"])
    assert f'<div class="warnung">{text}</div>' in s
    assert ui_freigabe_bewerbung._HINWEISE["antworten_erfasst"][1] not in s


@pytest.mark.parametrize("grund", ["bewerbung_unbekannt", "eingabe_ungueltig", "Eingabe ungueltig", "409"])
def test_antworten_andere_ablehnung_ist_ein_allgemeiner_hinweis(client, falsch, grund):
    falsch.fehler_post = PultFehler("abgelehnt", grund)
    r = _post(client, "antworten", fassung="1", antwort_f1="Ja")
    assert r.status_code == 303 and r.headers["location"].startswith("/freigaben?bw_hinweis=abgelehnt")
    assert "nicht angenommen" in _abschnitt(client, r.headers["location"])


def test_antworttext_steht_in_keinem_protokoll(client, falsch, caplog):
    falsch.fehler_post = PultFehler("nicht_erreichbar", "TimeoutError")
    with caplog.at_level(logging.WARNING, logger="sales-ui"):
        assert _post(client, "antworten", fassung="1", antwort_f1="ANTWORT-XYZ").status_code == 504
    assert "ANTWORT-XYZ" not in caplog.text
    assert any(BID in m and "Fassung 1" in m and "antworten" in m for m in _meldungen(caplog))
