"""Seite "Marke" in sales-ui (Spec 2026-10-07-marke-per-chat-design.md §4.1, Task 6).
Der Client zur Marketing-API wird gefaelscht (wie in test_marketing_pult.py)."""
import asyncio
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
VID = "22222222-2222-2222-2222-222222222222"
LOGO = "data:image/png;base64,iVBORw0KGgo="
SPIEGEL = {"gestalt": {"akzent": "#5eead4", "flaeche": "#1d3b39", "logo": LOGO,
                       "schriften": {"anzeige": "playfair", "text": "manrope"}},
           "stand": "2026-10-07 09:12 von mira", "gespiegelt_am": "2026-10-07T09:12:00", "fehler": None}
VORSCHLAG = {"id": VID, "erstellt_am": "2026-10-07T10:00:00",
             "vorschlag": {"akzent": "#ff6600", "zweitfarbe": "#fff1e6", "grund": "#ffffff", "text": "#111111",
                           "schrift_anzeige": "playfair", "schrift_text": "manrope", "logo": None,
                           "abschnitte": {"Wer wir sind": "Eine kleine Rösterei.", "Ton": "<b>warm</b> und klar"},
                           "mustertext": {"betreff": "Hallo", "ueberschrift": "Kaffee", "absatz": "Frisch."}}}


NAMEN = ("Kurz gesagt", "Wer wir sind", "Menschen", "Zielgruppe", "Ton", "Wörter", "Angebote", "Abgrenzung",
         "Do & Don'ts", "Fakten und Zahlen", "Bildstil", "Kanäle", "Kontakt und Impressum", "Stimme")
FAEHIG = {"kann": ["Webseiten lesen, die du nennst oder die ich finde", "im Web suchen (mit Quellen)"],
          "nicht": ["keine Beiträge veröffentlichen oder Mails senden"]}
ZIEL = "/marketing/layouts?reiter=chat#ende"
# Review-Fix 1: der Refresh zielt immer auf eine NEUE Adresse (stand=<Sekunden>) - ein Ziel, das sich nur im
# Anker von der Seite unterscheidet, ist in Firefox/Safari nur ein Sprung ohne Neuladen.
REFRESH_CHAT = re.compile(r'<meta http-equiv="refresh" content="5;url=/marketing/layouts\?reiter=chat&amp;stand=\d+#ende">')
PROFIL = "/marketing/layouts?reiter=profil"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.fehler_pfad = None
        self.im_loop = []
        self.zustand = {"mandant": "vibemind", "name": "VibeMind", "spiegel": dict(SPIEGEL),
                        "auftraege": [], "laeuft": False, "vorschlag": None, "uebernahme": None,
                        "uebernahme_seit": None, "aktuell": None, "abschnitt_namen": list(NAMEN),
                        "faehigkeiten": FAEHIG, "runden_gesamt": 0}
        self.stimmen = ["eigene-a", "eigene-b", "eigene-c"]
        self.einrichtungen = []          # GET /mandanten?einrichtung=1 (086)
        self.chat_antwort = {"auftrag": "a1"}

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        try:
            asyncio.get_running_loop()
            self.im_loop.append(pfad)
        except RuntimeError:
            pass
        if self.fehler and (self.fehler_pfad is None or pfad.endswith(self.fehler_pfad)
                            or self.fehler_pfad in pfad):
            raise self.fehler
        if roh:
            return (b"<p>Muster</p>", "text/html")
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True}]}
        if pfad == "/mandanten?einrichtung=1":
            return {"mandanten": list(self.einrichtungen)}
        if pfad.startswith("/marke?mandant="):
            return {**self.zustand, "mandant": urllib.parse.parse_qs(pfad.split("?", 1)[1])["mandant"][0]}
        if pfad == "/marke/chat":
            return self.chat_antwort
        if pfad.startswith("/marke/einrichtung/"):
            return {"ok": True}
        if pfad == "/medien/zuordnung":
            return {"dateiname": daten["dateiname"], "mandant": daten["mandant"]}
        if pfad.endswith("/uebernehmen"):
            return {"auftrag": "u1"}
        if pfad.endswith("/verwerfen"):
            return {"status": "verworfen"}
        if pfad.endswith("/rueckgaengig"):
            return {"auftrag": "r1"}
        if pfad == "/marke/bearbeiten":
            return {"auftrag": "b1"}
        if pfad == "/stimmen":
            return {"stimmen": list(self.stimmen)}
        return {}

    def nach(self, teil):
        return [a for a in self.aufrufe if teil in a[1]]


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    return f


@pytest.fixture
def angemeldet(pult):
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus - Seitentests brauchen die Anmeldung")
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", "freigeben", ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               headers=HOST, follow_redirects=False)
    assert r.status_code == 303
    yield c
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def medienordner(tmp_path, monkeypatch):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    return tmp_path


def seite(c, pfad="/marketing/layouts"):
    return c.get(pfad, headers=HOST)


def rumpf(r):
    """Nur der Seitenkoerper (das eingebettete CSS nennt Klassennamen)."""
    return r.text[r.text.index("<main"):]


# --- Profil -------------------------------------------------------------------

def test_profil_mit_kopfteil(angemeldet):
    r = seite(angemeldet, PROFIL)
    s = r.text
    assert r.status_code == 200 and "<h1>Marke</h1>" in s
    assert "#5eead4" in s and "#1d3b39" in s
    assert "Aa – VibeMind" in s
    assert f'<img class="marke-logo" src="{LOGO}"' in s
    assert "Stand: 2026-10-07 09:12 von mira" in s
    assert "Noch kein Branding" not in s
    csp = r.headers["content-security-policy"]
    assert csp == ("default-src 'none'; style-src 'unsafe-inline' 'self'; font-src 'self'; "
                   "img-src 'self' data:; media-src 'self'; form-action 'self'; base-uri 'none'; "
                   "frame-ancestors 'none'; frame-src 'self'")
    assert '<link rel="stylesheet" href="/marketing/schrift/schriften.css">' in s


def test_profil_ohne_kopfteil(angemeldet, pult):
    pult.zustand["spiegel"] = {"gestalt": {}, "stand": "", "gespiegelt_am": None, "fehler": None}
    s = rumpf(seite(angemeldet, PROFIL))
    assert "Noch kein Branding – erzähl mir von der Firma" in s
    assert "Stand:" not in s and "marke-logo" not in s


def test_logo_nur_als_bilddaten_url(angemeldet, pult):
    pult.zustand["spiegel"]["gestalt"]["logo"] = 'javascript:alert(1)"><script>'
    s = rumpf(seite(angemeldet, PROFIL))
    assert "javascript:" not in s and "<script" not in s and "marke-logo" not in s


def test_spiegel_veraltet_und_hinweise(angemeldet, pult):
    pult.zustand["spiegel"]["fehler"] = "akzent ungültig <i>"
    pult.zustand["auftraege"] = [{"id": "x", "nachricht": "Mach es wärmer", "antwort": "Fertig, <b>hier</b>",
                                  "status": "fertig", "hinweise": ["Marke.md: akzent ungültig"],
                                  "vorschlag": None, "erstellt_am": "2026-10-07T09:00:00"}]
    p = seite(angemeldet, PROFIL).text
    assert "Spiegel veraltet seit" in p and "akzent ungültig &lt;i&gt;" in p
    s = seite(angemeldet).text
    assert "Mach es wärmer" in s and "Fertig, &lt;b&gt;hier&lt;/b&gt;" in s
    assert "Marke.md: akzent ungültig" in s


def test_firma_aus_cookie(angemeldet, pult):
    cookies = "; ".join(f"{k}={v}" for k, v in angemeldet.cookies.items())
    angemeldet.get("/marketing/layouts", headers={**HOST, "cookie": f"{cookies}; mk_mandant=fin2gether"})
    assert ("GET", "/marke?mandant=fin2gether") in [a[:2] for a in pult.aufrufe]
    assert not any("mandant=vibemind" in a[1] for a in pult.aufrufe)


# --- Auffrischen und Status -----------------------------------------------------

def test_refresh_nur_bei_laufendem_auftrag(angemeldet, pult):
    assert 'http-equiv="refresh"' not in seite(angemeldet).text
    pult.zustand["laeuft"] = True
    assert REFRESH_CHAT.search(seite(angemeldet).text)
    pult.zustand["laeuft"] = False
    pult.zustand["uebernahme"] = "laeuft"
    s = seite(angemeldet).text
    assert REFRESH_CHAT.search(s) and "Wird übernommen …" in s


def test_kein_refresh_ohne_uebernahme_und_ohne_lauf_mit_vorschlag(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = seite(angemeldet).text
    assert 'http-equiv="refresh"' not in s and "Wird übernommen" not in s


# --- Chat senden ------------------------------------------------------------------

def test_senden_schickt_nachricht_mit_firma(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Wir sind warm und modern"})
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    m, p, d = pult.nach("/marke/chat")[-1]
    assert (m, p) == ("POST", "/marke/chat")
    assert d["mandant"] == "vibemind" and d["nachricht"] == "Wir sind warm und modern"
    assert d["kontext"] == {"anhaenge": []}


def test_senden_ohne_csrf(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, data={"nachricht": "x"})
    assert r.status_code == 403 and pult.nach("/marke/chat") == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_senden_leere_oder_lange_nachricht_ohne_aufruf(angemeldet, pult, text):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": text})
    assert r.status_code == 422 and pult.nach("/marke/chat") == []


def test_senden_api_lehnt_ab_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Es läuft schon ein Auftrag")
    pult.fehler_pfad = "/marke/chat"
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Hallo"})
    assert r.status_code == 422 and "Es läuft schon ein Auftrag" in r.text


# --- Uploads ------------------------------------------------------------------------

def test_upload_ordnet_der_firma_zu(angemeldet, pult, medienordner):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Hier mein Logo"},
                        files=[("datei", ("Logo Neu.PNG", b"P" * 10, "image/png")),
                               ("datei", ("preise.pdf", b"D" * 20, "application/pdf"))])
    assert r.status_code == 303
    assert (medienordner / "Logo_Neu.png").read_bytes() == b"P" * 10
    assert (medienordner / "preise.pdf").exists()
    zu = [a[2] for a in pult.nach("/medien/zuordnung")]
    assert zu == [{"dateiname": "Logo_Neu.png", "mandant": "vibemind"},
                  {"dateiname": "preise.pdf", "mandant": "vibemind"}]
    d = pult.nach("/marke/chat")[-1][2]
    assert d["kontext"]["anhaenge"] == [{"name": "Logo_Neu.png", "art": "bild"},
                                        {"name": "preise.pdf", "art": "dokument"}]
    # Zuordnung vor dem Chat-Auftrag
    pfade = [a[1] for a in pult.aufrufe]
    assert pfade.index("/medien/zuordnung") < pfade.index("/marke/chat")


def test_upload_zuordnung_scheitert_loescht_datei_und_sendet_nicht(angemeldet, pult, medienordner):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    pult.fehler_pfad = "/medien/zuordnung"
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Logo"},
                        files={"datei": ("logo.png", b"P" * 10, "image/png")})
    assert r.status_code == 503
    assert list(medienordner.iterdir()) == []
    assert pult.nach("/marke/chat") == []


def test_upload_falsche_endung_abgewiesen(angemeldet, pult, medienordner):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "x"},
                        files={"datei": ("virus.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 422 and list(medienordner.iterdir()) == []
    assert pult.nach("/marke/chat") == [] and pult.nach("/medien/zuordnung") == []


def test_zu_viele_anhaenge(angemeldet, pult, medienordner):
    dateien = [("datei", (f"a{i}.png", b"P", "image/png")) for i in range(6)]
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "x"}, files=dateien)
    assert r.status_code == 422 and list(medienordner.iterdir()) == []


# --- Vorschlag ------------------------------------------------------------------------

def test_vorschlag_karte_und_rahmen(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = seite(angemeldet).text
    assert '<iframe class="vorschau" sandbox' in s
    assert f'src="/marketing/marke/vorschau?format=mail&amp;vorschlag={VID}"' in s
    assert 'href="/marketing/layouts?reiter=chat&amp;format=handy#vorschlag"' in s
    assert "#ff6600" in s and "Eine kleine Rösterei." in s and "&lt;b&gt;warm&lt;/b&gt;" in s
    assert "<b>warm</b>" not in s
    assert 'action="/marketing/marke/uebernehmen"' in s and 'action="/marketing/marke/verwerfen"' in s
    assert 'type="checkbox" name="bestaetigt"' in s and f'name="vorschlag" value="{VID}"' in s
    assert "Ja, dieses Profil übernehmen" in s
    assert "Die Marke hat sich geändert – übernehmen?" not in s               # das ist der Editor-Hinweis
    assert "<script" not in s


def test_handy_umschalter(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = seite(angemeldet, "/marketing/layouts?format=handy").text
    assert f'src="/marketing/marke/vorschau?format=handy&amp;vorschlag={VID}"' in s
    assert 'href="/marketing/layouts?reiter=chat&amp;format=mail#vorschlag"' in s


def test_kein_vorschlag_keine_knoepfe(angemeldet):
    s = seite(angemeldet).text
    assert "/marke/uebernehmen" not in s and "<iframe" not in s


def test_vorschau_proxy_mit_sandbox(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    r = angemeldet.get("/marketing/marke/vorschau?format=handy", headers=HOST)
    assert r.status_code == 200 and b"Muster" in r.content
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    m, p, _ = pult.aufrufe[-1]
    assert m == "GET" and p.startswith(f"/marke/vorschlaege/{VID}/vorschau?") and "format=handy" in p


def test_vorschau_ohne_vorschlag_404_im_rahmen(angemeldet):
    r = angemeldet.get("/marketing/marke/vorschau", headers=HOST)
    assert r.status_code == 404 and "sandbox" in r.headers["content-security-policy"]


def test_vorschau_api_weg_bleibt_im_rahmen(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Die Vorlage studio ist nicht verfügbar")
    pult.fehler_pfad = "/vorschau"
    r = angemeldet.get("/marketing/marke/vorschau", headers=HOST)
    assert r.status_code == 422 and "studio" in r.text
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


# --- Uebernehmen / Verwerfen -------------------------------------------------------------

def test_uebernehmen_ohne_haken_ruft_nichts_auf(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/uebernehmen", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID})
    assert r.status_code == 422 and pult.nach("/uebernehmen") == []


def test_uebernehmen_mit_haken(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/uebernehmen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID, "bestaetigt": "ja"})
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    assert pult.nach("/uebernehmen")[-1] == ("POST", f"/marke/vorschlaege/{VID}/uebernehmen",
                                             {"von": "mira", "mandant": "vibemind"})


def test_uebernehmen_ohne_csrf(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/uebernehmen", headers=HOST,
                        data={"vorschlag": VID, "bestaetigt": "ja"})
    assert r.status_code == 403 and pult.nach("/uebernehmen") == []


def test_uebernehmen_konflikt_zeigt_meldung(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Inzwischen gibt es ein neueres Profil – bitte neu laden")
    pult.fehler_pfad = "/uebernehmen"
    r = angemeldet.post("/marketing/marke/uebernehmen", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID, "bestaetigt": "ja"})
    assert r.status_code == 422
    assert "Inzwischen gibt es ein neueres Profil – bitte neu laden" in r.text
    assert 'href="/marketing/layouts?reiter=chat#ende"' in r.text


@pytest.mark.parametrize("pfad", ["uebernehmen", "verwerfen"])
def test_vorschlag_id_muss_uuid_sein(angemeldet, pult, pfad):
    r = angemeldet.post(f"/marketing/marke/{pfad}", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": "../../x", "bestaetigt": "ja"})
    assert r.status_code == 422 and pult.nach("/vorschlaege") == []


def test_verwerfen(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/verwerfen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID})
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    assert pult.nach("/verwerfen")[-1] == ("POST", f"/marke/vorschlaege/{VID}/verwerfen",
                                           {"von": "mira", "mandant": "vibemind"})


def test_verwerfen_ohne_csrf(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/verwerfen", headers=HOST, data={"vorschlag": VID})
    assert r.status_code == 403 and pult.nach("/verwerfen") == []


# --- Alte Pfade, Fehler, Threadpool ---------------------------------------------------------

@pytest.mark.parametrize("methode,pfad", [
    ("get", "/marketing/layout/dunkel"), ("post", "/marketing/layout/dunkel/speichern"),
    ("post", "/marketing/layout/dunkel/standard"), ("post", "/marketing/layout-vorschau"),
    ("get", "/marketing/layout-bild/dunkel")])
def test_alte_pfade_leiten_auf_die_marke(angemeldet, pult, methode, pfad):
    r = getattr(angemeldet, methode)(pfad, headers=HOST, follow_redirects=False,
                                     **({"data": {"csrf": ui.CSRF_TOKEN}} if methode == "post" else {}))
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    assert pult.aufrufe == []


def test_kein_javascript(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    pult.zustand["laeuft"] = True
    r = seite(angemeldet)
    assert "<script" not in r.text and "onclick" not in r.text
    assert "script-src" not in r.headers["content-security-policy"]


@pytest.mark.parametrize("art,status,text", [("nicht_erreichbar", 503, "Marketing gerade nicht erreichbar"),
                                             ("nicht_verbunden", 503, "Marketing nicht verbunden")])
def test_api_weg(angemeldet, pult, art, status, text):
    pult.fehler = marketing_pult.PultFehler(art, "x")
    r = seite(angemeldet)
    assert r.status_code == status and text in r.text


def test_alle_pult_aufrufe_im_threadpool(angemeldet, pult, medienordner):
    pult.zustand["vorschlag"] = VORSCHLAG
    seite(angemeldet)
    angemeldet.get("/marketing/marke/vorschau", headers=HOST)
    angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "nachricht": "x"},
                    files={"datei": ("logo.png", b"P", "image/png")})
    angemeldet.post("/marketing/marke/uebernehmen", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID, "bestaetigt": "ja"})
    angemeldet.post("/marketing/marke/verwerfen", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID})
    angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "akzent": "#000000"})
    pfade = [a[1] for a in pult.aufrufe]
    for teil in ("/marke?mandant=", "/vorschau?", "/medien/zuordnung", "/marke/chat", "/uebernehmen", "/verwerfen", "/marke/bearbeiten"):
        assert any(teil in p for p in pfade), teil
    assert pult.im_loop == []


# --- Fix-Runde 1 --------------------------------------------------------------------------

AKTUELL = {"abschnitte": {"Ton": "warm und klar\n\nimmer per Du\ndritte Zeile",
                          "Zielgruppe": "Radfahrer in der Stadt " + "x" * 300},
           "werte": {"grund": "#faf7f2", "text": "#2b2724", "akzent": "#b45309"}}


def test_profilkarten_zeigen_den_vollen_text_aus_aktuell(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL
    s = rumpf(seite(angemeldet, PROFIL))
    ton = s[s.index("<h3>Ton</h3>"):]
    ton = ton[:ton.index("</section>")]
    assert "warm und klar<br><br>immer per Du<br>dritte Zeile" in ton
    assert "Radfahrer in der Stadt " + "x" * 300 in s
    assert "Grund #faf7f2" in s and "Text #2b2724" in s


def test_ohne_aktuell_leere_karten(angemeldet):
    s = rumpf(seite(angemeldet, PROFIL))
    assert s.count("Noch leer – frag den Agenten") == 14 and "Grund #" not in s


def test_aktuell_wird_escaped(angemeldet, pult):
    pult.zustand["aktuell"] = {"abschnitte": {"Ton": "<script>x</script>"}, "werte": {}}
    s = rumpf(seite(angemeldet, PROFIL))
    assert "<script" not in s and "&lt;script&gt;" in s


def _vor(sekunden):
    return (datetime.now(timezone.utc) - timedelta(seconds=sekunden)).isoformat()


def test_uebernahme_unter_60s(angemeldet, pult):
    pult.zustand.update(uebernahme="laeuft", uebernahme_seit=_vor(20))
    s = rumpf(seite(angemeldet))
    assert "Wird übernommen …" in s and "sobald der PC läuft" not in s


def test_uebernahme_ueber_60s_sagt_pc(angemeldet, pult):
    pult.zustand.update(uebernahme="laeuft", uebernahme_seit=_vor(90))
    r = seite(angemeldet)
    assert "Wird übernommen, sobald der PC läuft" in r.text and "Wird übernommen …" not in rumpf(r)
    assert 'http-equiv="refresh"' in r.text


def test_uebernahme_seit_postgres_format_und_ohne_zone(angemeldet, pult):
    alt = datetime.now(timezone.utc) - timedelta(seconds=120)
    pult.zustand.update(uebernahme="laeuft", uebernahme_seit=alt.strftime("%Y-%m-%d %H:%M:%S") + "+00")
    assert "sobald der PC läuft" in seite(angemeldet).text
    pult.zustand["uebernahme_seit"] = alt.strftime("%Y-%m-%d %H:%M:%S")       # ohne Zone = UTC
    assert "sobald der PC läuft" in seite(angemeldet).text
    pult.zustand["uebernahme_seit"] = "kein Datum"
    assert "Wird übernommen …" in rumpf(seite(angemeldet))


def test_schriftmuster_in_der_schrift(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = rumpf(seite(angemeldet))
    assert "font-family:'Playfair Display', sans-serif\">Aa – VibeMind" in s
    assert "font-family:'Manrope', sans-serif\">Aa – VibeMind" in s


def test_unbekannte_schrift_id_wird_nicht_in_css_gesetzt(angemeldet, pult):
    pult.zustand["spiegel"]["gestalt"]["schriften"] = {"anzeige": "x';}</style><b>", "text": "manrope"}
    s = rumpf(seite(angemeldet, PROFIL))
    assert "</style><b>" not in s and "&lt;/style&gt;" in s
    assert "font-family:'x" not in s


def test_logo_grenze(angemeldet, pult):
    rand = "data:image/png;base64," + "A" * 210_000
    pult.zustand["spiegel"]["gestalt"]["logo"] = rand
    assert 'class="marke-logo"' in rumpf(seite(angemeldet, PROFIL))
    pult.zustand["spiegel"]["gestalt"]["logo"] = rand + "A"
    assert 'class="marke-logo"' not in rumpf(seite(angemeldet, PROFIL))


def test_formular_weg_solange_agent_laeuft(angemeldet, pult):
    pult.zustand["laeuft"] = True
    s = rumpf(seite(angemeldet))
    assert 'action="/marketing/marke/senden"' not in s and 'type="file"' not in s
    assert "Der Marken-Agent arbeitet gerade" in s
    pult.zustand["laeuft"] = False
    assert 'action="/marketing/marke/senden"' in rumpf(seite(angemeldet))


def test_chat_abgelehnt_loescht_eben_abgelegte_uploads(angemeldet, pult, medienordner):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Es läuft schon ein Auftrag")
    pult.fehler_pfad = "/marke/chat"
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Logo"},
                        files={"datei": ("logo.png", b"P" * 10, "image/png")})
    assert r.status_code == 422 and "Es läuft schon ein Auftrag" in r.text
    assert list(medienordner.iterdir()) == []


def test_vorschau_nimmt_die_id_aus_dem_rahmen(angemeldet, pult):
    neuer = "44444444-4444-4444-4444-444444444444"
    pult.zustand["vorschlag"] = {**VORSCHLAG, "id": neuer}
    r = angemeldet.get(f"/marketing/marke/vorschau?format=mail&vorschlag={VID}", headers=HOST)
    assert r.status_code == 200
    assert pult.aufrufe[-1][1].startswith(f"/marke/vorschlaege/{VID}/vorschau?")
    assert not any(a[1].startswith("/marke?mandant=") for a in pult.aufrufe)


@pytest.mark.parametrize("wert", ["../../x", "", "nix"])
def test_vorschau_ungueltige_id_404_im_rahmen(angemeldet, pult, wert):
    r = angemeldet.get(f"/marketing/marke/vorschau?vorschlag={wert}", headers=HOST)
    assert r.status_code == 404 and "sandbox" in r.headers["content-security-policy"]
    assert pult.nach("/vorschlaege") == []



# --- Schlussrunde (final-review.md) -------------------------------------------------------

def _mit_cookie(c, firma):
    cookies = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    return {**HOST, "cookie": f"{cookies}; mk_mandant={firma}"}


def test_i3_profil_zeigt_die_lesehinweise_der_marke_md(angemeldet, pult):
    pult.zustand["profil_hinweise"] = ["Marke.md: akzent ungültig", "Marke.md: <b>logo</b> ungültig"]
    s = rumpf(seite(angemeldet, PROFIL))
    profil = s[s.index('class="marke-profil"'):s.index('class="profil-karten"')]
    assert "Marke.md: akzent ungültig" in profil and "Marke.md: &lt;b&gt;logo&lt;/b&gt; ungültig" in profil
    assert "<b>logo</b>" not in s


def test_i3_hinweise_auch_ohne_gespiegeltes_profil(angemeldet, pult):
    pult.zustand["spiegel"] = {"gestalt": {}, "stand": "", "gespiegelt_am": None, "fehler": None}
    pult.zustand["profil_hinweise"] = ["Marke.md: akzent ungültig"]
    s = rumpf(seite(angemeldet, PROFIL))
    assert "Noch kein Branding" in s and "Marke.md: akzent ungültig" in s


def test_i6_fehlgeschlagene_uebernahme_ist_sichtbar(angemeldet, pult):
    pult.zustand["letzte_uebernahme"] = {"status": "fehler", "geaendert_am": "2026-10-07T11:00:00",
                                         "antwort": "Übernehmen nicht möglich: Logo <x>.png nicht gefunden",
                                         "hinweise": []}
    s = rumpf(seite(angemeldet))
    assert "Übernehmen fehlgeschlagen" in s and "Logo &lt;x&gt;.png nicht gefunden" in s


def test_i6_hinweise_einer_erfolgreichen_uebernahme(angemeldet, pult):
    pult.zustand["letzte_uebernahme"] = {"status": "fertig", "geaendert_am": "2026-10-07T11:00:00",
                                         "antwort": "Die Marke ist übernommen.",
                                         "hinweise": ["Spiegel nicht aktualisiert: x – der Abgleich holt es nach."]}
    s = rumpf(seite(angemeldet))
    assert "Die Marke ist übernommen." in s and "Spiegel nicht aktualisiert: x – der Abgleich holt es nach." in s


def test_i6_erfolg_ohne_hinweise_bleibt_still_und_laufende_uebernahme_verdeckt_das_alte(angemeldet, pult):
    pult.zustand["letzte_uebernahme"] = {"status": "fertig", "antwort": "Die Marke ist übernommen.",
                                         "hinweise": [], "geaendert_am": "2026-10-07T11:00:00"}
    assert "Die Marke ist übernommen." not in rumpf(seite(angemeldet))
    pult.zustand["letzte_uebernahme"] = {"status": "fehler", "antwort": "Alter Fehler", "hinweise": [],
                                         "geaendert_am": "2026-10-07T11:00:00"}
    pult.zustand["uebernahme"] = "laeuft"
    pult.zustand["uebernahme_seit"] = datetime.now(timezone.utc).isoformat()
    s = rumpf(seite(angemeldet))
    assert "Wird übernommen …" in s and "Alter Fehler" not in s


def test_minor3_spiegel_fehler_ohne_stand_wird_gezeigt(angemeldet, pult):
    pult.zustand["spiegel"] = {"gestalt": {}, "stand": "", "gespiegelt_am": None, "fehler": "Layout ungueltig: x"}
    s = rumpf(seite(angemeldet, PROFIL))
    assert "Layout ungueltig: x" in s and "None" not in s
    assert "Spiegel noch nie gesetzt: Layout ungueltig: x" in s


def test_minor4_aktionen_tragen_die_firma_der_oberflaeche(angemeldet, pult):
    """Ein Tab nach dem Firmenwechsel: die API vergleicht die gewaehlte Firma mit der des Vorschlags."""
    h = _mit_cookie(angemeldet, "fin2gether")
    angemeldet.post("/marketing/marke/uebernehmen", headers=h, data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID,
                                                                    "bestaetigt": "ja"})
    assert pult.nach("/uebernehmen")[-1][2] == {"von": "mira", "mandant": "fin2gether"}
    angemeldet.post("/marketing/marke/verwerfen", headers=h, data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID})
    assert pult.nach("/verwerfen")[-1][2] == {"von": "mira", "mandant": "fin2gether"}
    angemeldet.get(f"/marketing/marke/vorschau?vorschlag={VID}", headers=h)
    assert "mandant=fin2gether" in pult.nach("/vorschlaege/")[-1][1]


def test_minor4_vorschau_ohne_id_traegt_die_firma(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    angemeldet.get("/marketing/marke/vorschau", headers=HOST)
    assert "mandant=vibemind" in pult.nach("/vorschlaege/")[-1][1]


# --- Denken und Schritte des Agenten ---------------------------------------------


def test_runde_mit_spur_hat_details(angemeldet, pult):
    pult.zustand["auftraege"] = [{"nachricht": "Hallo", "antwort": "Fertig.", "status": "fertig", "hinweise": [],
                                  "denken": "Let me <think>",
                                  "schritte": [{"zeit": "08:03:41", "text": "Webseite gelesen (3 Seiten)"}]}]
    s = rumpf(seite(angemeldet))
    assert '<details class="schritte">' in s
    assert "<summary>1 Schritt</summary>" in s
    assert "Claudes Gedanken (zusammengefasst, englisch)" in s
    assert "Let me &lt;think&gt;" in s and "Let me <think>" not in s
    assert "08:03:41" in s and "Webseite gelesen (3 Seiten)" in s


def test_ohne_spur_kein_details(angemeldet, pult):
    pult.zustand["auftraege"] = [{"nachricht": "Hallo", "antwort": "Fertig.", "status": "fertig", "hinweise": [],
                                  "denken": "", "schritte": []}]
    s = rumpf(seite(angemeldet))
    assert '<details class="schritte"' not in s and "spur" not in s


def test_laufend_zeigt_live_ausschnitt(angemeldet, pult):
    pult.zustand["laeuft"] = True
    pult.zustand["laufend"] = {"art": "chat", "denken": "A" * 1000 + "ENDE",
                               "schritte": [{"zeit": "08:00:01", "text": "Frage an Claude"}]}
    s = rumpf(seite(angemeldet))
    assert 'class="spur-live"' in s
    assert "Denkt nach …" in s
    assert "ENDE" in s and "A" * 700 not in s
    assert "Frage an Claude" in s


def test_laufende_runde_hat_kein_aufklapp_element(angemeldet, pult):
    pult.zustand["laeuft"] = True
    pult.zustand["auftraege"] = [{"nachricht": "Hallo", "antwort": "", "status": "in_arbeit", "hinweise": [],
                                  "denken": "halb", "schritte": [{"zeit": "08:00:01", "text": "Frage an Claude"}]}]
    s = rumpf(seite(angemeldet))
    assert '<details class="schritte"' not in s and '<details class="spur"' not in s


def test_uebernahme_schritte_in_letzte(angemeldet, pult):
    pult.zustand["letzte_uebernahme"] = {"status": "fertig", "antwort": "Die Marke ist übernommen.",
                                         "hinweise": [], "geaendert_am": "2026-10-07T11:00:00",
                                         "schritte": [{"zeit": "08:02:13", "text": "Rowboat geschrieben"}]}
    s = rumpf(seite(angemeldet))
    assert "Rowboat geschrieben" in s and '<details class="schritte"><summary>1 Schritt</summary>' in s


# --- Profil bearbeiten und Logo-Fassungen (Spec 2026-10-09-marke-exakt) -------------------------

AKTUELL_VOLL = {"abschnitte": {"Ton": "warm & klar", "Bildstil": "Tageslicht"},
                "werte": {"akzent": "#b45309", "zweitfarbe": "#3b2f2f", "grund": "#faf7f2", "text": "#2b2724",
                          "schrift_anzeige": "playfair", "schrift_text": "manrope",
                          "webseite": "https://radhaus.example/"}}


def test_profil_bearbeiten_link_und_vorbefuelltes_formular(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL_VOLL
    assert 'href="/marketing/layouts?bearbeiten=1"' in seite(angemeldet, PROFIL).text
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'action="/marketing/marke/bearbeiten"' in s and "An den Agenten geben" in s
    assert 'name="akzent" value="#b45309"' in s
    assert 'name="webseite" type="url" value="https://radhaus.example/"' in s
    assert '<option value="playfair" selected>' in s and '<option value="manrope" selected>' in s
    assert ">warm &amp; klar</textarea>" in s and 'name="abschnitt::Bildstil"' in s
    assert "<script" not in s


def test_profil_bearbeiten_ohne_aktuell_nimmt_den_spiegel(angemeldet, pult):
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'name="akzent" value="#5eead4"' in s and 'name="zweitfarbe" value="#1d3b39"' in s
    assert '<option value="manrope" selected>' in s


def test_bearbeiten_waehrend_der_agent_arbeitet(angemeldet, pult):
    pult.zustand["laeuft"] = True
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert "/marketing/marke/bearbeiten" not in s and "bearbeiten geht danach" in s


def test_formular_geht_an_den_agenten(angemeldet, pult):
    daten = {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "akzent": " #b45309 ", "zweitfarbe": "#3b2f2f", "grund": "#faf7f2",
             "text": "#2b2724", "schrift_anzeige": "playfair", "schrift_text": "manrope",
             "webseite": "https://radhaus.example/", "abschnitt::Ton": "Ruhig,\r\nper Du.",
             "abschnitt::Bildstil": "Tageslicht", "abschnitt::Angebote": ""}
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data=daten, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    (methode, _, body), = pult.nach("/marke/bearbeiten")
    assert methode == "POST" and body["mandant"] == "vibemind"
    f = body["formular"]
    assert f["akzent"] == "#b45309" and f["webseite"] == "https://radhaus.example/"
    assert f["abschnitte"]["Ton"] == "Ruhig,\nper Du." and f["abschnitte"]["Bildstil"] == "Tageslicht"
    assert f["abschnitte"] == {"Ton": "Ruhig,\nper Du.", "Bildstil": "Tageslicht", "Angebote": ""}


def test_formular_ohne_csrf_und_zu_lang(angemeldet, pult):
    assert angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data={"akzent": "#000000"}).status_code == 403
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind",
                                                                         "abschnitt::Kurz gesagt": "x" * 8001})
    assert r.status_code == 422 and pult.nach("/marke/bearbeiten") == []


def test_kein_direktes_speichern(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/speichern", headers=HOST, data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code not in (200, 303)
    angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "akzent": "#000000"})
    assert [a[1] for a in pult.aufrufe if a[0] == "POST"] == ["/marke/bearbeiten"]


def test_bearbeiten_abgelehnt_zeigt_meldung(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Assistent arbeitet gerade")
    pult.fehler_pfad = "/marke/bearbeiten"
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "akzent": "#000000"})
    assert r.status_code == 422 and "Der Assistent arbeitet gerade" in r.text


def test_vorschlag_zeigt_drei_logo_fassungen(angemeldet, pult):
    pult.zustand["vorschlag"] = {**VORSCHLAG, "vorschlag": {**VORSCHLAG["vorschlag"],
                                 "logo": "marke-vibemind-logo-a1.png", "logo_dunkel": "marke-vibemind-logo-b2.png",
                                 "logo_original": "karte.png"}}
    r = seite(angemeldet)
    s = rumpf(r)
    for name, titel, klasse in (("karte.png", "Original", "original"),
                                ("marke-vibemind-logo-a1.png", "Logo auf Weiß", "hell"),
                                ("marke-vibemind-logo-b2.png", "Logo auf dunkler Fläche", "dunkel")):
        assert f'<figure class="logo-fassung {klasse}"><img src="/medien/datei/{name}" alt="{titel}">' in s
    assert ".logo-fassung.dunkel { background: #1a1a1a;" in r.text


def test_logo_fassungen_nur_mit_schlichten_namen(angemeldet, pult):
    pult.zustand["vorschlag"] = {**VORSCHLAG, "vorschlag": {**VORSCHLAG["vorschlag"], "logo": "../geheim.png",
                                                             "logo_dunkel": "x.svg"}}
    s = rumpf(seite(angemeldet))
    assert "logo-fassung" not in s and "/medien/datei/.." not in s


def test_profil_zeigt_dunkles_logo_aus_dem_spiegel(angemeldet, pult):
    pult.zustand["spiegel"] = {**SPIEGEL, "gestalt": {**SPIEGEL["gestalt"], "logo_dunkel": LOGO}}
    assert f'<img class="marke-logo dunkel" src="{LOGO}"' in rumpf(seite(angemeldet, PROFIL))


def test_formular_traegt_die_firma_als_versteckte_angabe(angemeldet, pult):
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert '<input type="hidden" name="mandant" value="vibemind">' in s


def test_formular_anderer_firma_wird_abgewiesen(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "fin2gether", "akzent": "#000000"})
    assert r.status_code == 422 and "Die Firma wurde gewechselt" in r.text
    assert pult.nach("/marke/bearbeiten") == []


def test_formular_ohne_firma_wird_abgewiesen(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "akzent": "#000000"})
    assert r.status_code == 422 and pult.nach("/marke/bearbeiten") == []


WISSEN_FERTIG = {"status": "fertig",
                 "antwort": "Wissen aktualisiert: 2 Dateien\n- companys/VibeMind/Über uns.md\n- Projekte/Plan.md\n"
                            "- Markenhandbuch: companys/VibeMind/Markenhandbuch.md",
                 "hinweise": ["Projekte/X.md: Ausschnitt nicht genau einmal gefunden – verworfen"],
                 "denken": "Updating <docs>", "schritte": [{"zeit": "14:30:05", "text": "Kandidaten: 5 Dokumente"}],
                 "geaendert_am": "2026-10-09T14:31:00"}


def test_wissens_lauf_fertig_mit_liste_denken_und_schritten(angemeldet, pult):
    pult.zustand["wissen"] = WISSEN_FERTIG
    s = rumpf(seite(angemeldet))
    assert "<summary>Firmenwissen: aktuell</summary>" in s
    assert '<p class="meta">Wissen aktualisiert: 2 Dateien</p>' in s
    assert "<li>Projekte/Plan.md</li>" in s and "<li>Markenhandbuch: companys/VibeMind/Markenhandbuch.md</li>" in s
    assert "verworfen" in s and "Kandidaten: 5 Dokumente" in s and "Updating &lt;docs&gt;" in s


def test_wissens_lauf_wartet_und_laeuft(angemeldet, pult):
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "offen"}
    r = seite(angemeldet)
    assert "Wissen wird aktualisiert, sobald der PC läuft" in r.text and 'http-equiv="refresh"' not in r.text
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit"}
    pult.zustand["laufend"] = {"art": "wissen", "denken": "Reading",
                               "schritte": [{"zeit": "14:30:01", "text": "Frage an Claude"}]}
    r = seite(angemeldet)
    # R7: ein laufender Wissens-Lauf laedt die Seite nicht neu; Stand mit "Aktualisieren", Denken als Spur
    assert "Wissen wird aktualisiert …" in r.text and 'http-equiv="refresh"' not in r.text
    assert '<a href="/marketing/layouts?reiter=chat#ende">Aktualisieren</a>' in r.text
    assert "<summary>Firmenwissen: wird aufgefrischt</summary>" in r.text
    assert 'class="spur-live"' not in r.text and "Updating &lt;docs&gt;" in r.text


def test_wissens_denken_erscheint_nicht_im_chat_bereich(angemeldet, pult):
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit", "denken": "NurWissen"}
    pult.zustand["laufend"] = {"art": "wissen", "denken": "Reading", "schritte": []}
    s = rumpf(seite(angemeldet))
    assert s.count('class="spur-live"') == 0 and "Reading" not in s
    assert s.index('class="chat-eingabe"') < s.index("Wissen wird aktualisiert") < s.index("NurWissen") < s.index('id="ende"')


def test_wissens_lauf_teilweise_und_fehler(angemeldet, pult):
    teilweise = ("teilweise: abgebrochen bei Projekte/Plan.md (OSError: Platte voll); geschrieben: "
                 "companys/VibeMind/Über uns.md – jede Datei ist gesichert")
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "hinweise": [teilweise]}
    assert teilweise in rumpf(seite(angemeldet))
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "fehler",
                              "antwort": "Wissen-Lauf nicht möglich: companys/VibeMind fehlt"}
    s = rumpf(seite(angemeldet))
    assert ('<p class="warnung">Wissen nicht aktualisiert: Wissen-Lauf nicht möglich: companys/VibeMind fehlt</p>'
            in s) and "<summary>Firmenwissen: Fehler</summary>" in s


def test_ohne_wissens_lauf_kein_abschnitt(angemeldet):
    s = rumpf(seite(angemeldet))
    assert "marke-wissen" not in s and "Wissen wird" not in s and "Firmenwissen" not in s


# --- Schlussrunde (final-review.md I1/I2, Rulings R7/R8) ------------------------------------------


def test_r7_nur_wissen_laeuft_kein_refresh_chat_formular_offen(angemeldet, pult):
    """Ein wartender oder laufender Wissens-Lauf haelt weder Chat noch Formular auf und laedt nie neu."""
    for status in ("offen", "in_arbeit"):
        pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": status}
        r = seite(angemeldet)
        assert 'http-equiv="refresh"' not in r.text, status
        assert 'action="/marketing/marke/senden"' in r.text, status
        assert '<a href="/marketing/layouts?reiter=chat#ende">Aktualisieren</a>' in r.text, status
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'action="/marketing/marke/bearbeiten"' in s


def test_r7_refresh_bleibt_fuer_chat_bearbeitung_und_uebernahme(angemeldet, pult):
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit"}
    pult.zustand["laeuft"] = True
    assert REFRESH_CHAT.search(seite(angemeldet).text)
    pult.zustand["laeuft"] = False
    pult.zustand["uebernahme"] = "laeuft"
    assert REFRESH_CHAT.search(seite(angemeldet).text)


ECHT = {"werte": {"akzent": "#123456", "zweitfarbe": "#3b2f2f", "grund": "#faf7f2", "text": "#2b2724",
                  "schrift_anzeige": "oxanium", "schrift_text": "manrope", "webseite": "https://echt.example/"},
        "abschnitte": {"Ton": "Aus der Marke.md", "Angebote": "Nur in Rowboat ergänzt"}}


def test_r8_formular_aus_dem_echten_profil_nicht_aus_dem_vorschlag(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL_VOLL
    pult.zustand["profil"] = ECHT
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'name="akzent" value="#123456"' in s and 'name="akzent" value="#b45309"' not in s
    assert 'name="webseite" type="url" value="https://echt.example/"' in s
    assert '<option value="oxanium" selected>' in s
    assert ">Aus der Marke.md</textarea>" in s and ">Nur in Rowboat ergänzt</textarea>" in s
    assert "warm &amp; klar" not in s and "Tageslicht" not in s
    p = rumpf(seite(angemeldet, PROFIL))             # die Profilkarten lesen dieselbe Quelle
    assert "Aus der Marke.md" in p and "warm &amp; klar" not in p


def test_r8_ohne_profil_rueckfall_auf_den_letzten_vorschlag(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL_VOLL
    pult.zustand["profil"] = None
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'name="akzent" value="#b45309"' in s and ">warm &amp; klar</textarea>" in s


def test_r8_profil_wird_escaped(angemeldet, pult):
    pult.zustand["profil"] = {"werte": {"webseite": '"><script>x</script>'},
                              "abschnitte": {"Ton": "</textarea><script>y</script>"}}
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert "<script" not in s


def test_profil_bearbeiten_warnt_vor_offenem_vorschlag(angemeldet, pult, medienordner):
    pult.zustand["aktuell"] = AKTUELL_VOLL
    ohne = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert "offenen Vorschlag" not in ohne
    pult.zustand["vorschlag"] = {**VORSCHLAG, "erstellt_am": "2026-10-07T10:00:00<b>"}
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert "Es gibt einen offenen Vorschlag vom " in s
    assert ("– wenn du das Formular abschickst, ersetzt es ihn. Übernimm oder verwirf ihn vorher, "
            "wenn du ihn behalten willst.") in s
    assert "<b>" not in s.split("offenen Vorschlag vom ")[1].split("</p>")[0]
    assert s.index("offenen Vorschlag") < s.index("marke-bearbeiten")


# --- Marken-Chat neu (Plan 2026-10-20, Task 5: Reiter, Chat wie Claude Code, Profil vollständig) ----------

VID_A = "55555555-5555-5555-5555-555555555555"


def _runde(n, **kw):
    a = {"id": f"a{n}", "nachricht": f"Frage Nummer {n}", "antwort": f"Antwort Nummer {n}", "status": "fertig",
         "hinweise": [], "vorschlag": None, "denken": "", "schritte": [], "art": "chat", "quellen": [],
         "aenderung": None, "erstellt_am": f"2026-10-20T09:{n:02d}:00"}
    a.update(kw)
    return a


def _aenderung(vid=VID_A, **kw):
    z = {"vid": vid, "status": "angenommen", "direkt": True, "rueckgaengig_moeglich": True,
         "aenderungen": [{"feld": "Ton", "vorher": "kühl <i>", "nachher": "warm und klar"}]}
    z.update(kw)
    return z


def test_reiter_chat_ist_vorgabe(angemeldet, pult):
    s = rumpf(seite(angemeldet))
    assert '<nav class="reiter"' in s
    assert 'href="/marketing/layouts?reiter=chat#ende" aria-current="page">Chat</a>' in s
    assert 'href="/marketing/layouts?reiter=profil">Profil</a>' in s
    assert 'class="profil-karten"' not in s and 'id="ende"' in s
    p = rumpf(seite(angemeldet, PROFIL))
    assert 'href="/marketing/layouts?reiter=profil" aria-current="page">Profil</a>' in p
    assert 'class="profil-karten"' in p and 'id="ende"' not in p


def test_profil_reiter_zeigt_leere_neue_abschnitte(angemeldet, pult):
    pult.zustand["profil"] = {"werte": {}, "abschnitte": {"Ton": "warm", "Bildstil": "hell"}}
    s = rumpf(seite(angemeldet, PROFIL))
    assert s.count('<section class="profil-karte">') == 14
    assert s.count("Noch leer – frag den Agenten") == 12
    positionen = [s.index(f"<h3>{ui._e(n)}</h3>") for n in NAMEN]
    assert positionen == sorted(positionen)
    assert "<h3>Kanäle</h3>" in s and "<h3>Do &amp; Don&#x27;ts</h3>" in s


def test_profil_ohne_namensliste_zeigt_die_vorhandenen_abschnitte(angemeldet, pult):
    pult.zustand.pop("abschnitt_namen")
    pult.zustand["profil"] = {"werte": {}, "abschnitte": {"Ton": "warm", "Notizen": "eigene"}}
    s = rumpf(seite(angemeldet, PROFIL))
    assert s.count('<section class="profil-karte">') == 2
    assert s.index("<h3>Ton</h3>") < s.index("<h3>Notizen</h3>")


def test_dunkles_logo_auf_dunkler_flaeche(angemeldet, pult):
    pult.zustand["spiegel"] = {**SPIEGEL, "gestalt": {**SPIEGEL["gestalt"], "logo": LOGO, "logo_dunkel": LOGO}}
    s = rumpf(seite(angemeldet, PROFIL))
    dunkel = s[s.index('class="logo-dunkel-flaeche"'):]
    assert dunkel.index(f'<img class="marke-logo dunkel" src="{LOGO}"') < dunkel.index("</div>")
    hell = s[s.index('class="logo-hell-flaeche"'):]
    assert hell.index(f'<img class="marke-logo" src="{LOGO}"') < hell.index("</div>")


def test_verlauf_aelteste_oben_eingabe_unten(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(1), _runde(2)]
    s = rumpf(seite(angemeldet))
    verlauf = s.index('class="chat-verlauf"')
    assert verlauf < s.index("Frage Nummer 1") < s.index("Frage Nummer 2") < s.index('id="ende"')
    assert '<form method="post" action="/marketing/marke/senden"' in s
    eingabe = s.index('action="/marketing/marke/senden"')
    assert s.index("Antwort Nummer 2") < eingabe < s.index('class="chat-eingabe"') < s.index('id="ende"')
    assert 'class="blase-du"' in s and 'class="blase-agent"' in s
    assert "20.10.2026 09:01" in s or "20.10.2026 11:01" in s          # Uhrzeit an der Du-Blase


def test_aeltere_anzeigen_link(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(i) for i in range(5, 15)]
    pult.zustand["runden_gesamt"] = 14
    s = rumpf(seite(angemeldet))
    assert 'href="/marketing/layouts?reiter=chat&amp;alle=1#ende">Ältere anzeigen' in s
    assert s.index("Ältere anzeigen") < s.index("Frage Nummer 5")
    assert pult.nach("/marke?mandant=")[-1][1] == "/marke?mandant=vibemind"
    s = rumpf(seite(angemeldet, "/marketing/layouts?reiter=chat&alle=1"))
    assert pult.nach("/marke?mandant=")[-1][1] == "/marke?mandant=vibemind&alle=1"
    pult.zustand["runden_gesamt"] = 10
    assert "Ältere anzeigen" not in rumpf(seite(angemeldet))


def test_schritte_eine_zeile(angemeldet, pult):
    schritte = [{"zeit": "09:00:0" + str(i), "text": t} for i, t in
                enumerate(["Frage an Claude", "Websuche genutzt", "Antwort geprüft: ok", "Vorschlag abgelegt"])]
    quellen = [{"titel": "Rösterei Startseite", "url": "https://roesterei.example/", "art": "gelesen"},
               {"titel": "Branchenbericht", "url": "http://bericht.example/a", "art": "websuche"}]
    pult.zustand["auftraege"] = [_runde(1, schritte=schritte, quellen=quellen, denken="Thinking")]
    s = rumpf(seite(angemeldet))
    assert '<details class="schritte"><summary>4 Schritte · Websuche · 2 Quellen</summary>' in s
    assert ('<a href="https://roesterei.example/" rel="noopener noreferrer" target="_blank">'
            'Rösterei Startseite</a>') in s
    assert "Branchenbericht</a> <span class=\"meta\">Websuche</span>" in s
    assert "Claudes Gedanken (zusammengefasst, englisch)" in s and "Thinking" in s
    pult.zustand["auftraege"] = [_runde(1, schritte=schritte[:1])]
    assert "<summary>1 Schritt</summary>" in rumpf(seite(angemeldet))


def test_quelle_javascript_wird_kein_link(angemeldet, pult):
    quellen = [{"titel": "<script>alert(2)</script>", "url": "javascript:alert(1)", "art": "websuche"},
               {"titel": "Daten", "url": "data:text/html,x", "art": "websuche"},
               {"titel": "Gut", "url": 'https://a.example/"><b>', "art": "gelesen"}]
    pult.zustand["auftraege"] = [_runde(1, quellen=quellen, schritte=[{"zeit": "09:00:00", "text": "x"}])]
    s = rumpf(seite(angemeldet))
    assert 'href="javascript' not in s and 'href="data:' not in s
    assert "<script" not in s and "&lt;script&gt;alert(2)&lt;/script&gt;" in s
    assert "javascript:alert(1)" in s                                   # als Text sichtbar
    assert 'href="https://a.example/&quot;&gt;&lt;b&gt;"' in s and "<b>" not in s


def test_aenderung_mit_rueckgaengig(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung(
        aenderungen=[{"feld": "Ton", "vorher": "kühl <i>", "nachher": "warm und klar"},
                     {"feld": "Wörter", "vorher": "", "nachher": "Bohne, Röstung"}]))]
    s = rumpf(seite(angemeldet))
    assert "Geändert: Ton, Wörter" in s
    assert "kühl &lt;i&gt;" in s and "warm und klar" in s and "Bohne, Röstung" in s
    assert "<summary>Ton</summary>" in s and "vorher" in s and "nachher" in s
    assert 'action="/marketing/marke/rueckgaengig"' in s
    assert f'name="vorschlag" value="{VID_A}"' in s and "Rückgängig</button>" in s
    karte = s[s.index("Geändert: Ton"):]
    assert 'name="csrf"' in karte[:karte.index("Rückgängig</button>")]
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung(rueckgaengig_moeglich=False))]
    s = rumpf(seite(angemeldet))
    assert "Geändert: Ton" in s and "/marketing/marke/rueckgaengig" not in s


def test_direkt_aber_offen_zeigt_die_vorschlagskarte(angemeldet, pult):
    """Ruling: scheitert das direkte Annehmen, bleibt der Vorschlag offen - dann die normale Karte."""
    pult.zustand["vorschlag"] = {**VORSCHLAG, "id": VID_A}
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung(status="offen",
                                                                                 rueckgaengig_moeglich=False))]
    s = rumpf(seite(angemeldet))
    assert "Geändert:" not in s and "/marketing/marke/rueckgaengig" not in s
    assert 'action="/marketing/marke/uebernehmen"' in s and 'name="bestaetigt"' in s


def test_rueckgaengig_post(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/rueckgaengig", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID_A})
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    assert pult.nach("/rueckgaengig")[-1] == ("POST", f"/marke/vorschlaege/{VID_A}/rueckgaengig",
                                              {"von": "mira", "mandant": "vibemind"})
    r = angemeldet.post("/marketing/marke/rueckgaengig", headers=HOST, data={"vorschlag": VID_A})
    assert r.status_code == 403 and len(pult.nach("/rueckgaengig")) == 1
    r = angemeldet.post("/marketing/marke/rueckgaengig", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": "../x"})
    assert r.status_code == 422 and len(pult.nach("/rueckgaengig")) == 1
    meldung = "Inzwischen gibt es eine neuere Änderung – Rückgängig geht nur für die letzte."
    pult.fehler = marketing_pult.PultFehler("abgelehnt", meldung)
    pult.fehler_pfad = "/rueckgaengig"
    r = angemeldet.post("/marketing/marke/rueckgaengig", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID_A})
    assert r.status_code == 422 and meldung in r.text


def test_offener_vorschlag_in_seiner_runde(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID), _runde(2)]
    s = rumpf(seite(angemeldet))
    karte = s.index('action="/marketing/marke/uebernehmen"')
    assert s.index("Antwort Nummer 1") < karte < s.index("Frage Nummer 2") < s.index('id="ende"')
    assert s.count('action="/marketing/marke/uebernehmen"') == 1


def test_offener_vorschlag_ohne_runde_steht_vor_der_eingabe(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    pult.zustand["auftraege"] = [_runde(1), _runde(2)]
    s = rumpf(seite(angemeldet))
    assert s.index("Antwort Nummer 2") < s.index('action="/marketing/marke/uebernehmen"') < s.index('id="ende"')


def test_bearbeitung_als_systemzeile(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(1, art="bearbeitung", nachricht="Formular", antwort="Übernommen.")]
    s = rumpf(seite(angemeldet))
    assert '<p class="systemzeile">Profil von Hand bearbeitet' in s
    assert 'class="blase-du"' not in s and "Übernommen." in s


def test_refresh_mit_anker(angemeldet, pult):
    pult.zustand["laeuft"] = True
    assert REFRESH_CHAT.search(seite(angemeldet).text)
    s = seite(angemeldet, "/marketing/layouts?reiter=chat&alle=1").text
    assert re.search(r'content="5;url=/marketing/layouts\?reiter=chat&amp;alle=1&amp;stand=\d+#ende"', s)
    p = seite(angemeldet, PROFIL).text
    assert re.search(r'content="5;url=/marketing/layouts\?reiter=profil&amp;stand=\d+"', p)
    pult.zustand["laeuft"] = False
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit"}
    assert 'http-equiv="refresh"' not in seite(angemeldet).text


def test_seite_refresh_bleibt_rueckwaertsvertraeglich():
    assert '<meta http-equiv="refresh" content="7">' in ui._seite("X", "<p>x</p>", refresh=7).body.decode()
    alt = ui._seite("X", "<p>x</p>", refresh=(5, "/a?b=1&c=2#ende")).body.decode()
    assert '<meta http-equiv="refresh" content="5;url=/a?b=1&amp;c=2#ende">' in alt
    assert 'http-equiv="refresh"' not in ui._seite("X", "<p>x</p>").body.decode()


def test_bearbeiten_felder_nach_namen(angemeldet, pult):
    pult.zustand["profil"] = {"werte": {}, "abschnitte": {"Kurz gesagt": "Röstet <gut>"}}
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    for n in NAMEN:
        assert f'name="abschnitt::{ui._e(n)}"' in s, n
    assert ">Röstet &lt;gut&gt;</textarea>" in s and 'name="ab0"' not in s
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "abschnitt::Kurz gesagt": "Kurz",
                              "abschnitt::Wörter": "Bohne", "abschnitt::Kanäle": "Instagram"})
    assert r.status_code == 303 and r.headers["location"] == ZIEL
    f = pult.nach("/marke/bearbeiten")[-1][2]["formular"]
    assert f["abschnitte"] == {"Kurz gesagt": "Kurz", "Wörter": "Bohne", "Kanäle": "Instagram"}


def test_bearbeiten_altes_formular_wird_abgewiesen(angemeldet, pult):
    """Ein Tab mit dem alten Formular (ab0..ab6) leerte sonst alle Abschnitte."""
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "ab0": "Wer"})
    assert r.status_code == 422 and pult.nach("/marke/bearbeiten") == []


def test_faehigkeiten_eingeklappt_oben(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(1)]
    s = rumpf(seite(angemeldet))
    f = s.index('<details class="faehigkeiten">')
    assert f < s.index('class="chat-verlauf"')
    assert "im Web suchen (mit Quellen)" in s and "keine Beiträge veröffentlichen oder Mails senden" in s
    pult.zustand.pop("faehigkeiten")
    assert "faehigkeiten" not in rumpf(seite(angemeldet))


def test_laufende_runde_zeigt_denkt_nach_in_der_runde(angemeldet, pult):
    pult.zustand["laeuft"] = True
    pult.zustand["laufend"] = {"art": "chat", "denken": "", "schritte": [{"zeit": "09:00:01", "text": "Frage an Claude"}]}
    pult.zustand["auftraege"] = [_runde(1), _runde(2, antwort="", status="in_arbeit")]
    s = rumpf(seite(angemeldet))
    assert s.count("Denkt nach …") == 1
    assert s.index("Frage Nummer 2") < s.index("Denkt nach …") < s.index('id="ende"')


# --- Review-Fixes Task 5 -----------------------------------------------------------------------------


def test_rueckgaengig_gemacht_zeigt_das_und_keinen_knopf(angemeldet, pult):
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung(
        rueckgaengig_moeglich=False, rueckgaengig_gemacht=True))]
    s = rumpf(seite(angemeldet))
    assert "Geändert: Ton" in s and "Rückgängig gemacht" in s
    assert "/marketing/marke/rueckgaengig" not in s and "Rückgängig</button>" not in s
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung())]
    assert "Rückgängig gemacht" not in rumpf(seite(angemeldet))


@pytest.mark.parametrize("direkt", [True, False])
@pytest.mark.parametrize("status,wort", [("verworfen", "Vorschlag verworfen"),
                                          ("ersetzt", "Vorschlag durch einen neueren ersetzt")])
def test_verworfen_oder_ersetzt_zeigt_die_statuszeile(angemeldet, pult, direkt, status, wort):
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung(
        status=status, direkt=direkt, rueckgaengig_moeglich=False))]
    s = rumpf(seite(angemeldet))
    assert f'<p class="systemzeile">{wort}</p>' in s and "Geändert:" not in s


def test_fehlerseite_fuehrt_zurueck_in_den_chat(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Assistent arbeitet gerade")
    pult.fehler_pfad = "/marke/chat"
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, data={"csrf": ui.CSRF_TOKEN, "nachricht": "x"})
    assert r.status_code == 422 and '<a href="/marketing/layouts?reiter=chat#ende">Zur Marke</a>' in r.text
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, data={"csrf": ui.CSRF_TOKEN, "nachricht": " "})
    assert r.status_code == 422 and '<a href="/marketing/layouts?reiter=chat#ende">Zur Marke</a>' in r.text


# --- Abschluss-Review --------------------------------------------------------------------------------


@pytest.mark.parametrize("schalter", [{"uebernahme": "laeuft"}, {"laeuft": True}])
def test_rueckgaengig_knopf_versteckt_solange_der_agent_arbeitet(angemeldet, pult, schalter):
    """Minor 1: waehrend einer Uebernahme oder Chat-Runde kein Rueckgaengig-Knopf, nur ein Hinweis."""
    pult.zustand["auftraege"] = [_runde(1, vorschlag=VID_A, aenderung=_aenderung())]
    pult.zustand.update(schalter)
    s = rumpf(seite(angemeldet))
    assert "Geändert: Ton" in s
    assert "Rückgängig</button>" not in s and 'action="/marketing/marke/rueckgaengig"' not in s
    assert '<p class="meta">Rückgängig geht, sobald der Agent fertig ist.</p>' in s
    pult.zustand.update({"uebernahme": None, "laeuft": False})
    s = rumpf(seite(angemeldet))
    assert "Rückgängig</button>" in s and "sobald der Agent fertig ist" not in s


def test_offener_gegenvorschlag_heisst_rueckgaengig_wird_uebernommen(angemeldet, pult):
    pult.zustand["vorschlag"] = {**VORSCHLAG, "id": VID_A, "ist_rueckgaengig": True}
    s = rumpf(seite(angemeldet))
    assert "<h3>Rückgängig wird übernommen</h3>" in s and "<h3>Vorschlag</h3>" not in s
    assert 'action="/marketing/marke/uebernehmen"' in s and 'action="/marketing/marke/verwerfen"' in s
    for wert in (False, None, "ja"):
        pult.zustand["vorschlag"] = {**VORSCHLAG, "id": VID_A, "ist_rueckgaengig": wert}
        s = rumpf(seite(angemeldet))
        assert "<h3>Vorschlag</h3>" in s and "Rückgängig wird übernommen" not in s, wert


# --- Reels Stufe 1, E11: Stimme fuer Reels und Podcast ------------------------------------

def test_profil_zeigt_stimme_karte(angemeldet, pult):
    pult.zustand["profil"] = {"werte": {"stimme": "eigene-b"}, "abschnitte": {}}
    s = rumpf(seite(angemeldet, PROFIL))
    assert '<section class="profil-karte stimme-karte"><h3>Stimme für Reels und Podcast</h3><p>eigene-b</p>' in s
    pult.zustand["profil"] = {"werte": {"stimme": "<b>x</b>"}, "abschnitte": {}}
    assert "&lt;b&gt;x&lt;/b&gt;" in rumpf(seite(angemeldet, PROFIL))
    pult.zustand["profil"] = {"werte": {}, "abschnitte": {}}
    s = rumpf(seite(angemeldet, PROFIL))
    assert '<h3>Stimme für Reels und Podcast</h3><p class="leer">Noch keine festgelegt</p>' in s


def test_bearbeiten_hat_stimmen_auswahl_aus_api(angemeldet, pult):
    pult.zustand["profil"] = {"werte": {"stimme": "eigene-b"}, "abschnitte": {}}
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert ("GET", "/stimmen", None) in pult.aufrufe
    assert ('<select name="stimme"><option value="">keine</option><option value="eigene-a">eigene-a</option>'
            '<option value="eigene-b" selected>eigene-b</option><option value="eigene-c">eigene-c</option>'
            '</select>') in s
    # eine Stimme, die es nicht mehr gibt, bleibt gewaehlt (sonst loescht ein Abschicken sie still)
    pult.zustand["profil"] = {"werte": {"stimme": "alt"}, "abschnitte": {}}
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert '<option value="alt" selected>alt (nicht mehr verfügbar)</option>' in s
    # Liste nicht erreichbar: kein Feld, also bleibt die Stimme unveraendert
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("nicht_erreichbar", "x"), "/stimmen"
    r = seite(angemeldet, "/marketing/layouts?bearbeiten=1")
    assert r.status_code == 200 and 'name="stimme"' not in rumpf(r) and "An den Agenten geben" in r.text


def test_bearbeiten_schickt_stimme(angemeldet, pult):
    basis = {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "akzent": "#000000"}
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False,
                        data={**basis, "stimme": " eigene-c "})
    assert r.status_code == 303 and pult.nach("/marke/bearbeiten")[-1][2]["formular"]["stimme"] == "eigene-c"
    angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False, data={**basis, "stimme": ""})
    assert pult.nach("/marke/bearbeiten")[-1][2]["formular"]["stimme"] == ""          # "" = entfernen
    angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False, data=basis)
    assert "stimme" not in pult.nach("/marke/bearbeiten")[-1][2]["formular"]          # fehlt = unveraendert
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, follow_redirects=False,
                        data={**basis, "stimme": "x" * 41})
    assert r.status_code == 422 and len(pult.nach("/marke/bearbeiten")) == 3


# --- /marke_neu: Einrichtung einer neuen Marke (Plan 2026-10-21-marke-neu-skill, Task 8) -----------------

BEFEHLE = [{"befehl": "/marke_neu", "beschreibung": "neue Marke einrichten"}]
PROBE = {"id": "probe_gmbh", "name": "Probe GmbH", "aktiv": False, "einrichtung": "laeuft"}
TITEL = ("Name und Webseite", "Pflichtangaben für Newsletter", "Wer und was", "Aussehen", "Stimme", "Belege",
         "Zusammenfassung und Bestätigung")
EINRICHTUNG = "/marketing/layouts?einrichtung=probe_gmbh"


def _stand(abschliessbar=False):
    return {"schritte": [{"nr": i, "titel": t, "erledigt": i <= 2, "offen": [] if i <= 2 else ["etwas"]}
                         for i, t in enumerate(TITEL, 1)],
            "naechster": 3, "abschliessbar": abschliessbar}


def _in_einrichtung(pult, abschliessbar=False):
    pult.einrichtungen = [dict(PROBE)]
    pult.zustand.update({"name": "Probe GmbH", "einrichtung": "laeuft", "einrichtung_stand": _stand(abschliessbar),
                         "befehle": BEFEHLE})


def test_befehlszeile_unter_eingabe(angemeldet, pult):
    pult.zustand["befehle"] = BEFEHLE
    s = rumpf(seite(angemeldet))
    assert "Befehle: /marke_neu – neue Marke einrichten" in s
    assert s.index('name="nachricht"') < s.index("Befehle: /marke_neu")


def test_senden_marke_neu_leitet_zur_einrichtung(angemeldet, pult):
    pult.chat_antwort = {"auftrag": "a9", "einrichtung": {"id": "probe_gmbh", "name": "Probe GmbH",
                                                          "fortgesetzt": False}}
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "/marke_neu Probe GmbH https://probe.de"})
    assert r.status_code == 303
    assert r.headers["location"] == "/marketing/layouts?einrichtung=probe_gmbh&reiter=chat#ende"
    d = pult.nach("/marke/chat")[-1][2]
    assert d["von"] == "mira" and d["nachricht"] == "/marke_neu Probe GmbH https://probe.de"


def test_senden_traegt_immer_von(angemeldet, pult):
    angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "nachricht": "Hallo"})
    assert pult.nach("/marke/chat")[-1][2]["von"] == "mira"


def test_befehl_mit_anhang_abgewiesen_ohne_ablage(angemeldet, pult, medienordner):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "  /marke_neu Probe GmbH"},
                        files=[("datei", ("logo.png", b"P" * 10, "image/png"))])
    assert r.status_code == 422 and "Befehle bitte ohne Dateien senden" in r.text
    assert list(medienordner.iterdir()) == []
    assert pult.aufrufe == []


def test_unbekannter_befehl_zeigt_grund(angemeldet, pult):
    grund = "Unbekannter Befehl. Verfügbar: /marke_neu – neue Marke einrichten"
    pult.fehler = marketing_pult.PultFehler("unbekannt", "400", {"detail": grund})
    pult.fehler_pfad = "/marke/chat"
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "/gibtsnicht"})
    assert r.status_code == 422 and grund in r.text


def test_einrichtung_kopf_fortschritt_knoepfe(angemeldet, pult):
    _in_einrichtung(pult)
    r = seite(angemeldet, EINRICHTUNG)
    s = rumpf(r)
    assert r.status_code == 200
    assert ("GET", "/marke?mandant=probe_gmbh") in [a[:2] for a in pult.aufrufe]
    assert "Probe GmbH – in Einrichtung" in s
    assert '<a href="/marketing/layouts">Zurück zu VibeMind</a>' in s
    assert "Schritt 3 von 7" in s and "Name und Webseite" in s and "Zusammenfassung und Bestätigung" in s
    assert "Einrichtung abbrechen" in s and "Marke anlegen" not in s
    assert 'action="/marketing/mandant"' not in s      # der Umschalter setzt das Cookie - hier nicht
    _in_einrichtung(pult, abschliessbar=True)
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    assert "Marke anlegen" in s and "Einrichtung abbrechen" in s
    assert 'action="/marketing/marke/einrichtung/abschliessen"' in s


def test_einrichtung_kopf_zeigt_rechtsangaben_woertlich(angemeldet, pult):
    """Vor "Marke anlegen" stehen die gespeicherten Rechtsangaben woertlich (escaped, Umbrueche erhalten)."""
    _in_einrichtung(pult, abschliessbar=True)
    pult.zustand.update({"pflichtteil": {"impressum": "Probe <GmbH>\nWeg 1", "abmelde_hinweis":
                                         "Abmelden: {abmeldelink}", "vermittlerangaben": "Reg. D-1"},
                         "einrichtung_vermittler": True})
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    block = s[s.index('<dl class="einrichtung-angaben">'):]
    assert s.index('<dl class="einrichtung-angaben">') < s.index("Marke anlegen")
    assert '<dt>Impressum</dt><dd class="woertlich">Probe &lt;GmbH&gt;\nWeg 1</dd>' in block
    assert '<dt>Abmeldehinweis</dt><dd class="woertlich">Abmelden: {abmeldelink}</dd>' in block
    assert "<dt>Vermittler</dt><dd>ja</dd>" in block
    assert '<dt>Vermittlerangaben</dt><dd class="woertlich">Reg. D-1</dd>' in block
    pult.zustand.update({"pflichtteil": {"impressum": " ", "abmelde_hinweis": ""}, "einrichtung_vermittler": None})
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    assert '<dt>Impressum</dt><dd class="fehlt">fehlt</dd>' in s
    assert '<dt>Abmeldehinweis</dt><dd class="fehlt">fehlt</dd>' in s
    assert "<dt>Vermittler</dt><dd>noch offen</dd>" in s and "Vermittlerangaben" not in s
    pult.zustand.update({"einrichtung_vermittler": False})
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    assert "<dt>Vermittler</dt><dd>nein</dd>" in s and "Vermittlerangaben" not in s
    pult.zustand.update({"einrichtung_vermittler": True})
    assert '<dt>Vermittlerangaben</dt><dd class="fehlt">fehlt</dd>' in rumpf(seite(angemeldet, EINRICHTUNG))


@pytest.mark.parametrize("schalter", [{"laeuft": True}, {"uebernahme": "laeuft"}])
def test_marke_anlegen_versteckt_solange_der_assistent_arbeitet(angemeldet, pult, schalter):
    _in_einrichtung(pult, abschliessbar=True)
    pult.zustand.update(schalter)
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    assert "Marke anlegen" not in s and 'action="/marketing/marke/einrichtung/abschliessen"' not in s
    assert '<p class="meta">Der Assistent arbeitet gerade' in s and "Einrichtung abbrechen" in s


def test_abgewiesen_in_einrichtung_fuehrt_zurueck(angemeldet, pult):
    _in_einrichtung(pult)
    zurueck = '<a href="/marketing/layouts?einrichtung=probe_gmbh&amp;reiter=chat#ende">Zur Marke</a>'
    r = angemeldet.post("/marketing/marke/senden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": " ", "einrichtung": "probe_gmbh"})
    assert r.status_code == 422 and zurueck in r.text
    r = angemeldet.post("/marketing/marke/uebernehmen", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID, "einrichtung": "probe_gmbh"})
    assert r.status_code == 422 and zurueck in r.text
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "einrichtung": "probe_gmbh"})
    assert r.status_code == 422 and zurueck in r.text


def test_einrichtung_css_vorhanden():
    for klasse in (".einrichtung-kopf", ".einrichtung-schritte li.erledigt", ".einrichtung-schritte li.offen",
                   ".einrichtung-angaben", ".in-einrichtung", ".befehle"):
        assert klasse in ui._STIL, klasse


def test_formulare_tragen_einrichtung(angemeldet, pult):
    _in_einrichtung(pult)
    pult.zustand["vorschlag"] = VORSCHLAG
    pult.zustand["auftraege"] = [{"id": "x", "nachricht": "n", "antwort": "a", "status": "fertig",
                                  "vorschlag": VID, "erstellt_am": "2026-10-07T09:00:00"}]
    feld = 'name="einrichtung" value="probe_gmbh"'
    for pfad in (EINRICHTUNG, EINRICHTUNG + "&reiter=profil", EINRICHTUNG + "&bearbeiten=1"):
        s = rumpf(seite(angemeldet, pfad))
        formulare = s.split("<form")[1:]
        assert formulare, pfad
        for f in formulare:
            assert feld in f[:f.index("</form>")], (pfad, f[:200])
    s = rumpf(seite(angemeldet, EINRICHTUNG))
    assert "einrichtung=probe_gmbh" in s[s.index("<iframe"):]     # die Vorschau zeigt dieselbe Firma
    assert 'href="/marketing/layouts?einrichtung=probe_gmbh&amp;reiter=profil"' in s
    p = rumpf(seite(angemeldet, EINRICHTUNG + "&reiter=profil"))
    assert "einrichtung=probe_gmbh&amp;bearbeiten=1" in p


def test_senden_in_einrichtung(angemeldet, pult):
    _in_einrichtung(pult)
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Unsere Webseite ist probe.de",
                              "einrichtung": "probe_gmbh"})
    assert r.status_code == 303
    assert r.headers["location"] == "/marketing/layouts?einrichtung=probe_gmbh&reiter=chat#ende"
    assert pult.nach("/marke/chat")[-1][2]["mandant"] == "probe_gmbh"


def test_cookie_auf_einrichtung_faellt_auf_vorgabe(angemeldet, pult):
    _in_einrichtung(pult)
    angemeldet.get("/marketing/layouts", headers=_mit_cookie(angemeldet, "probe_gmbh"))
    assert ("GET", "/marke?mandant=vibemind") in [a[:2] for a in pult.aufrufe]
    assert not any("mandant=probe_gmbh" in a[1] for a in pult.aufrufe)


def test_get_mit_unbekannter_einrichtung_wie_ohne(angemeldet, pult):
    r = seite(angemeldet, "/marketing/layouts?einrichtung=alt_weg")
    assert r.status_code == 200
    assert ("GET", "/marke?mandant=vibemind") in [a[:2] for a in pult.aufrufe]
    assert "in Einrichtung" not in rumpf(r)


def test_post_mit_veralteter_einrichtung_422(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Hallo", "einrichtung": "alt_weg"})
    assert r.status_code == 422
    assert "Die Einrichtung ist abgeschlossen oder abgebrochen – bitte Seite neu laden. Nichts wurde geändert." in r.text
    assert pult.nach("/marke/chat") == []


def test_abschliessen_setzt_cookie_und_leitet(angemeldet, pult):
    _in_einrichtung(pult, abschliessbar=True)
    r = angemeldet.post("/marketing/marke/einrichtung/abschliessen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "einrichtung": "probe_gmbh"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts?reiter=profil"
    assert pult.nach("/marke/einrichtung/")[-1] == ("POST", "/marke/einrichtung/abschliessen",
                                                    {"mandant": "probe_gmbh", "von": "mira"})
    kopf = r.headers["set-cookie"]
    assert kopf.startswith("mk_mandant=probe_gmbh") and "Path=/marketing" in kopf
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Impressum fehlt")
    pult.fehler_pfad = "/abschliessen"
    r = angemeldet.post("/marketing/marke/einrichtung/abschliessen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "einrichtung": "probe_gmbh"})
    assert r.status_code == 422 and "Impressum fehlt" in r.text and "set-cookie" not in r.headers


@pytest.mark.parametrize("aktion", ["abschliessen", "abbrechen"])
def test_einrichtung_aktion_braucht_csrf_und_feld(angemeldet, pult, aktion):
    _in_einrichtung(pult)
    r = angemeldet.post(f"/marketing/marke/einrichtung/{aktion}", headers=HOST, data={"einrichtung": "probe_gmbh"})
    assert r.status_code == 403
    r = angemeldet.post(f"/marketing/marke/einrichtung/{aktion}", headers=HOST, data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 422
    r = angemeldet.post(f"/marketing/marke/einrichtung/{aktion}", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "einrichtung": "alt_weg"})
    assert r.status_code == 422
    assert pult.nach("/marke/einrichtung/") == []


def test_abbrechen_nennt_ordner(angemeldet, pult):
    _in_einrichtung(pult)
    r = angemeldet.post("/marketing/marke/einrichtung/abbrechen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "einrichtung": "probe_gmbh"})
    assert pult.nach("/marke/einrichtung/")[-1] == ("POST", "/marke/einrichtung/abbrechen",
                                                    {"mandant": "probe_gmbh", "von": "mira"})
    assert r.status_code == 200 and "set-cookie" not in r.headers
    assert "companys/Probe GmbH/" in r.text and 'href="/marketing/layouts"' in r.text


def test_liste_in_einrichtung_auf_normaler_seite(angemeldet, pult):
    assert "In Einrichtung" not in rumpf(seite(angemeldet))
    pult.einrichtungen = [dict(PROBE)]
    s = rumpf(seite(angemeldet))
    assert "In Einrichtung" in s and f'<a href="{EINRICHTUNG}">Probe GmbH</a>' in s
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    pult.fehler_pfad = "einrichtung=1"
    r = seite(angemeldet)
    assert r.status_code == 200 and "In Einrichtung" not in rumpf(r)


# --- Knopf "+ Neue Marke" -------------------------------------------------------------

def _neu(angemeldet, **felder):
    return angemeldet.post("/marketing/marke/neu", headers=HOST, follow_redirects=False,
                           data={"csrf": ui.CSRF_TOKEN, **felder})


def test_knopf_neue_marke_auf_normaler_seite(angemeldet, pult):
    s = rumpf(seite(angemeldet))
    assert "<summary>+ Neue Marke</summary>" in s
    form = s[s.index('action="/marketing/marke/neu"'):]
    form = form[:form.index("</form>")]
    assert 'name="name"' in form and 'maxlength="80"' in form and "required" in form
    assert 'name="webseite"' in form and 'type="url"' in form and "Einrichtung starten" in form
    assert 'name="csrf"' in form
    _in_einrichtung(pult)
    e = rumpf(seite(angemeldet, EINRICHTUNG))
    assert "Neue Marke" not in e and "/marketing/marke/neu" not in e


def test_neue_marke_formular_startet_einrichtung(angemeldet, pult):
    pult.chat_antwort = {"auftrag": "a9", "einrichtung": {"id": "baeckerei_sonnig", "name": "Bäckerei Sonnig",
                                                          "fortgesetzt": False}}
    r = _neu(angemeldet, name="Bäckerei Sonnig", webseite="https://b.de")
    assert r.status_code == 303
    assert r.headers["location"] == "/marketing/layouts?einrichtung=baeckerei_sonnig&reiter=chat#ende"
    m, p, d = pult.nach("/marke/chat")[-1]
    assert (m, p) == ("POST", "/marke/chat")
    assert d["nachricht"] == "/marke_neu Bäckerei Sonnig https://b.de" and d["von"] == "mira"


def test_neue_marke_ohne_webseite(angemeldet, pult):
    pult.chat_antwort = {"auftrag": "a9", "einrichtung": {"id": "x_gmbh", "name": "X GmbH", "fortgesetzt": False}}
    r = _neu(angemeldet, name="  X GmbH  ", webseite="  ")
    assert r.status_code == 303 and "einrichtung=x_gmbh" in r.headers["location"]
    assert pult.nach("/marke/chat")[-1][2]["nachricht"] == "/marke_neu X GmbH"


def test_neue_marke_leerer_name_422_ohne_api(angemeldet, pult):
    r = _neu(angemeldet, name="   ", webseite="")
    assert r.status_code == 422 and pult.nach("/marke/chat") == []


@pytest.mark.parametrize("web", ["b.de", "ftp://b.de", "https://b .de", "javascript:alert(1)"])
def test_neue_marke_ungueltige_webseite_422_ohne_api(angemeldet, pult, web):
    r = _neu(angemeldet, name="X GmbH", webseite=web)
    assert r.status_code == 422 and "Bitte eine Webseite mit https:// angeben oder leer lassen" in r.text
    assert pult.nach("/marke/chat") == []


def test_neue_marke_braucht_csrf(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/neu", headers=HOST, data={"name": "X GmbH"})
    assert r.status_code == 403 and pult.nach("/marke/chat") == []


# --- Pflichtangaben (Impressum, Vermittlerangaben, Abmeldehinweis) ------------------------------

def test_profil_zeigt_pflichtangaben_woertlich(angemeldet, pult):
    pult.zustand["pflichtteil"] = {"impressum": "Muster <b>GmbH</b>\nMusterweg 1",
                                   "abmelde_hinweis": "Abmelden: antworte mit STOP"}
    s = rumpf(seite(angemeldet, PROFIL))
    assert "Pflichtangaben" in s
    assert "Muster &lt;b&gt;GmbH&lt;/b&gt;\nMusterweg 1" in s and "<b>GmbH</b>" not in s   # escaped, Umbruch bleibt
    assert 'class="woertlich"' in s and "Abmelden: antworte mit STOP" in s
    assert "Vermittlerangaben" in s and "fehlt – im Chat ergänzen" in s                  # leeres Feld


def test_profil_ohne_pflichtteil_alles_fehlt(angemeldet, pult):
    s = rumpf(seite(angemeldet, PROFIL))
    assert s.count("fehlt – im Chat ergänzen") == 3


def test_vorschlag_mit_pflichtteil_zeigt_texte_vor_uebernehmen(angemeldet, pult):
    pult.zustand["vorschlag"] = {**VORSCHLAG, "vorschlag": {**VORSCHLAG["vorschlag"], "pflichtteil": {
        "impressum": "Neu <i>Impressum</i>\nZeile 2", "abmelde_hinweis": "Bitte STOP senden"}}}
    s = rumpf(seite(angemeldet))
    assert "Neue Pflichtangaben (wörtlich)" in s
    assert "Neu &lt;i&gt;Impressum&lt;/i&gt;\nZeile 2" in s and "<i>Impressum</i>" not in s
    assert "Bitte STOP senden" in s
    assert s.index("Neue Pflichtangaben (wörtlich)") < s.index("Bitte STOP senden") < s.index('name="bestaetigt"')
    assert s.index("Neu &lt;i&gt;Impressum") < s.index(">Übernehmen</button>")


def test_vorschlag_nur_pflichtteil_ohne_vorschau_iframe(angemeldet, pult):
    pult.zustand["vorschlag"] = {"id": VID, "erstellt_am": "2026-10-07T10:00:00", "direkt": False,
                                 "vorschlag": {"pflichtteil": {"impressum": "Nur Impressum"}}}
    s = rumpf(seite(angemeldet))
    assert "Nur Impressum" in s and 'name="bestaetigt"' in s
    assert "<iframe" not in s and 'class="farben-zeile"' not in s


def test_vorschlag_ohne_pflichtteil_hat_keinen_block(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    assert "Neue Pflichtangaben" not in rumpf(seite(angemeldet))
