"""Seite "Marke" in sales-ui (Spec 2026-10-07-marke-per-chat-design.md §4.1, Task 6).
Der Client zur Marketing-API wird gefaelscht (wie in test_marketing_pult.py)."""
import asyncio
import os

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
                       "schriften": {"anzeige": "fraunces", "text": "inter"}},
           "stand": "2026-10-07 09:12 von mira", "gespiegelt_am": "2026-10-07T09:12:00", "fehler": None}
VORSCHLAG = {"id": VID, "erstellt_am": "2026-10-07T10:00:00",
             "vorschlag": {"akzent": "#ff6600", "zweitfarbe": "#fff1e6", "grund": "#ffffff", "text": "#111111",
                           "schrift_anzeige": "fraunces", "schrift_text": "inter", "logo": None,
                           "abschnitte": {"Wer wir sind": "Eine kleine Rösterei.", "Ton": "<b>warm</b> und klar"},
                           "mustertext": {"betreff": "Hallo", "ueberschrift": "Kaffee", "absatz": "Frisch."}}}


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
                        "auftraege": [], "laeuft": False, "vorschlag": None, "uebernahme": None}

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
        if pfad.startswith("/marke?mandant="):
            return {**self.zustand, "mandant": pfad.split("=", 1)[1]}
        if pfad == "/marke/chat":
            return {"auftrag": "a1"}
        if pfad == "/medien/zuordnung":
            return {"dateiname": daten["dateiname"], "mandant": daten["mandant"]}
        if pfad.endswith("/uebernehmen"):
            return {"auftrag": "u1"}
        if pfad.endswith("/verwerfen"):
            return {"status": "verworfen"}
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
    r = seite(angemeldet)
    s = r.text
    assert r.status_code == 200 and "<h1>Marke</h1>" in s
    assert "#5eead4" in s and "#1d3b39" in s
    assert "fraunces" in s and "inter" in s
    assert f'<img class="marke-logo" src="{LOGO}"' in s
    assert "Stand: 2026-10-07 09:12 von mira" in s
    assert "Noch kein Branding" not in s
    csp = r.headers["content-security-policy"]
    assert "img-src 'self' data:" in csp and "frame-src 'self'" in csp
    assert "script-src" not in csp


def test_profil_ohne_kopfteil(angemeldet, pult):
    pult.zustand["spiegel"] = {"gestalt": {}, "stand": "", "gespiegelt_am": None, "fehler": None}
    s = rumpf(seite(angemeldet))
    assert "Noch kein Branding – erzähl mir von der Firma" in s
    assert "Stand:" not in s and "marke-logo" not in s


def test_logo_nur_als_bilddaten_url(angemeldet, pult):
    pult.zustand["spiegel"]["gestalt"]["logo"] = 'javascript:alert(1)"><script>'
    s = rumpf(seite(angemeldet))
    assert "javascript:" not in s and "<script" not in s and "marke-logo" not in s


def test_spiegel_veraltet_und_hinweise(angemeldet, pult):
    pult.zustand["spiegel"]["fehler"] = "akzent ungültig <i>"
    pult.zustand["auftraege"] = [{"id": "x", "nachricht": "Mach es wärmer", "antwort": "Fertig, <b>hier</b>",
                                  "status": "fertig", "hinweise": ["Marke.md: akzent ungültig"],
                                  "vorschlag": None, "erstellt_am": "2026-10-07T09:00:00"}]
    s = seite(angemeldet).text
    assert "Spiegel veraltet seit" in s and "akzent ungültig &lt;i&gt;" in s
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
    assert '<meta http-equiv="refresh" content="5">' in seite(angemeldet).text
    pult.zustand["laeuft"] = False
    pult.zustand["uebernahme"] = "laeuft"
    s = seite(angemeldet).text
    assert '<meta http-equiv="refresh" content="5">' in s and "Wird übernommen …" in s


def test_kein_refresh_ohne_uebernahme_und_ohne_lauf_mit_vorschlag(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = seite(angemeldet).text
    assert 'http-equiv="refresh"' not in s and "Wird übernommen" not in s


# --- Chat senden ------------------------------------------------------------------

def test_senden_schickt_nachricht_mit_firma(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/senden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "nachricht": "Wir sind warm und modern"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
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
    assert 'src="/marketing/marke/vorschau?format=mail"' in s
    assert 'href="/marketing/layouts?format=handy"' in s
    assert "#ff6600" in s and "Eine kleine Rösterei." in s and "&lt;b&gt;warm&lt;/b&gt;" in s
    assert "<b>warm</b>" not in s
    assert 'action="/marketing/marke/uebernehmen"' in s and 'action="/marketing/marke/verwerfen"' in s
    assert 'type="checkbox" name="bestaetigt"' in s and f'name="vorschlag" value="{VID}"' in s
    assert "Die Marke hat sich geändert – übernehmen?" in s
    assert "<script" not in s


def test_handy_umschalter(angemeldet, pult):
    pult.zustand["vorschlag"] = VORSCHLAG
    s = seite(angemeldet, "/marketing/layouts?format=handy").text
    assert 'src="/marketing/marke/vorschau?format=handy"' in s
    assert 'href="/marketing/layouts?format=mail"' in s


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
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    assert pult.nach("/uebernehmen")[-1] == ("POST", f"/marke/vorschlaege/{VID}/uebernehmen", {"von": "mira"})


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
    assert 'href="/marketing/layouts"' in r.text


@pytest.mark.parametrize("pfad", ["uebernehmen", "verwerfen"])
def test_vorschlag_id_muss_uuid_sein(angemeldet, pult, pfad):
    r = angemeldet.post(f"/marketing/marke/{pfad}", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": "../../x", "bestaetigt": "ja"})
    assert r.status_code == 422 and pult.nach("/vorschlaege") == []


def test_verwerfen(angemeldet, pult):
    r = angemeldet.post("/marketing/marke/verwerfen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorschlag": VID})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    assert pult.nach("/verwerfen")[-1] == ("POST", f"/marke/vorschlaege/{VID}/verwerfen", {"von": "mira"})


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
    pfade = [a[1] for a in pult.aufrufe]
    for teil in ("/marke?mandant=", "/vorschau?", "/medien/zuordnung", "/marke/chat", "/uebernehmen", "/verwerfen"):
        assert any(teil in p for p in pfade), teil
    assert pult.im_loop == []
