"""Seite "Marke" in sales-ui (Spec 2026-10-07-marke-per-chat-design.md §4.1, Task 6).
Der Client zur Marketing-API wird gefaelscht (wie in test_marketing_pult.py)."""
import asyncio
import os
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
                        "uebernahme_seit": None, "aktuell": None}

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
        if pfad == "/marke/bearbeiten":
            return {"auftrag": "b1"}
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
    assert f'src="/marketing/marke/vorschau?format=mail&amp;vorschlag={VID}"' in s
    assert 'href="/marketing/layouts?format=handy"' in s
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


def test_ton_und_zielgruppe_aus_aktuell_gekuerzt(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL
    s = rumpf(seite(angemeldet))
    assert "<b>Ton:</b> warm und klar<br>immer per Du" in s and "dritte Zeile" not in s
    ziel = s[s.index("<b>Zielgruppe:</b>"):]
    ziel = ziel[:ziel.index("</p>")]
    assert "Radfahrer in der Stadt" in ziel and ziel.endswith("…") and len(ziel) < 200
    assert "Grund #faf7f2" in s and "Text #2b2724" in s


def test_ohne_aktuell_keine_ton_zeilen(angemeldet):
    s = rumpf(seite(angemeldet))
    assert "<b>Ton:</b>" not in s and "<b>Zielgruppe:</b>" not in s and "Grund #" not in s


def test_aktuell_wird_escaped(angemeldet, pult):
    pult.zustand["aktuell"] = {"abschnitte": {"Ton": "<script>x</script>"}, "werte": {}}
    s = rumpf(seite(angemeldet))
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
    s = rumpf(seite(angemeldet))
    assert "</style><b>" not in s and "&lt;/style&gt;" in s
    assert "font-family:'x" not in s


def test_logo_grenze(angemeldet, pult):
    rand = "data:image/png;base64," + "A" * 210_000
    pult.zustand["spiegel"]["gestalt"]["logo"] = rand
    assert 'class="marke-logo"' in rumpf(seite(angemeldet))
    pult.zustand["spiegel"]["gestalt"]["logo"] = rand + "A"
    assert 'class="marke-logo"' not in rumpf(seite(angemeldet))


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
    s = rumpf(seite(angemeldet))
    profil = s[s.index('class="marke-profil"'):s.index("<h2>Chat</h2>")]
    assert "Marke.md: akzent ungültig" in profil and "Marke.md: &lt;b&gt;logo&lt;/b&gt; ungültig" in profil
    assert "<b>logo</b>" not in s


def test_i3_hinweise_auch_ohne_gespiegeltes_profil(angemeldet, pult):
    pult.zustand["spiegel"] = {"gestalt": {}, "stand": "", "gespiegelt_am": None, "fehler": None}
    pult.zustand["profil_hinweise"] = ["Marke.md: akzent ungültig"]
    s = rumpf(seite(angemeldet))
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
    s = rumpf(seite(angemeldet))
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
    assert '<details class="spur">' in s
    assert "Gedanken &amp; Schritte" in s
    assert "Claudes Gedanken (zusammengefasst, englisch)" in s
    assert "Let me &lt;think&gt;" in s and "Let me <think>" not in s
    assert "08:03:41" in s and "Webseite gelesen (3 Seiten)" in s


def test_ohne_spur_kein_details(angemeldet, pult):
    pult.zustand["auftraege"] = [{"nachricht": "Hallo", "antwort": "Fertig.", "status": "fertig", "hinweise": [],
                                  "denken": "", "schritte": []}]
    assert "spur" not in rumpf(seite(angemeldet))


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
    assert "<details" not in rumpf(seite(angemeldet))


def test_uebernahme_schritte_in_letzte(angemeldet, pult):
    pult.zustand["letzte_uebernahme"] = {"status": "fertig", "antwort": "Die Marke ist übernommen.",
                                         "hinweise": [], "geaendert_am": "2026-10-07T11:00:00",
                                         "schritte": [{"zeit": "08:02:13", "text": "Rowboat geschrieben"}]}
    s = rumpf(seite(angemeldet))
    assert "Rowboat geschrieben" in s and '<details class="spur">' in s


# --- Profil bearbeiten und Logo-Fassungen (Spec 2026-10-09-marke-exakt) -------------------------

AKTUELL_VOLL = {"abschnitte": {"Ton": "warm & klar", "Bildstil": "Tageslicht"},
                "werte": {"akzent": "#b45309", "zweitfarbe": "#3b2f2f", "grund": "#faf7f2", "text": "#2b2724",
                          "schrift_anzeige": "playfair", "schrift_text": "manrope",
                          "webseite": "https://radhaus.example/"}}


def test_profil_bearbeiten_link_und_vorbefuelltes_formular(angemeldet, pult):
    pult.zustand["aktuell"] = AKTUELL_VOLL
    assert 'href="/marketing/layouts?bearbeiten=1"' in seite(angemeldet).text
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'action="/marketing/marke/bearbeiten"' in s and "An den Agenten geben" in s
    assert 'name="akzent" value="#b45309"' in s
    assert 'name="webseite" type="url" value="https://radhaus.example/"' in s
    assert '<option value="playfair" selected>' in s and '<option value="manrope" selected>' in s
    assert ">warm &amp; klar</textarea>" in s and 'name="ab6"' in s
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
             "webseite": "https://radhaus.example/", "ab2": "Ruhig,\r\nper Du.", "ab6": "Tageslicht"}
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data=daten, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    (methode, _, body), = pult.nach("/marke/bearbeiten")
    assert methode == "POST" and body["mandant"] == "vibemind"
    f = body["formular"]
    assert f["akzent"] == "#b45309" and f["webseite"] == "https://radhaus.example/"
    assert f["abschnitte"]["Ton"] == "Ruhig,\nper Du." and f["abschnitte"]["Bildstil"] == "Tageslicht"
    assert f["abschnitte"]["Angebote"] == "" and len(f["abschnitte"]) == 7


def test_formular_ohne_csrf_und_zu_lang(angemeldet, pult):
    assert angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data={"akzent": "#000000"}).status_code == 403
    r = angemeldet.post("/marketing/marke/bearbeiten", headers=HOST, data={"csrf": ui.CSRF_TOKEN, "ab0": "x" * 8001})
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
    assert f'<img class="marke-logo dunkel" src="{LOGO}"' in rumpf(seite(angemeldet))


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
    assert '<a href="/marketing/layouts">Aktualisieren</a>' in r.text
    assert 'class="spur-live"' not in r.text and "Updating &lt;docs&gt;" in r.text


def test_wissens_denken_erscheint_nicht_im_chat_bereich(angemeldet, pult):
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit", "denken": "NurWissen"}
    pult.zustand["laufend"] = {"art": "wissen", "denken": "Reading", "schritte": []}
    s = rumpf(seite(angemeldet))
    assert s.count('class="spur-live"') == 0 and "Reading" not in s
    assert s.index("marke-chat") > s.index("NurWissen") > s.index("Wissen wird aktualisiert")


def test_wissens_lauf_teilweise_und_fehler(angemeldet, pult):
    teilweise = ("teilweise: abgebrochen bei Projekte/Plan.md (OSError: Platte voll); geschrieben: "
                 "companys/VibeMind/Über uns.md – jede Datei ist gesichert")
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "hinweise": [teilweise]}
    assert teilweise in rumpf(seite(angemeldet))
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "fehler",
                              "antwort": "Wissen-Lauf nicht möglich: companys/VibeMind fehlt"}
    assert ('<p class="warnung">Wissen nicht aktualisiert: Wissen-Lauf nicht möglich: companys/VibeMind fehlt</p>'
            in rumpf(seite(angemeldet)))


def test_ohne_wissens_lauf_kein_abschnitt(angemeldet):
    s = rumpf(seite(angemeldet))
    assert "marke-wissen" not in s and "Wissen wird" not in s


# --- Schlussrunde (final-review.md I1/I2, Rulings R7/R8) ------------------------------------------


def test_r7_nur_wissen_laeuft_kein_refresh_chat_formular_offen(angemeldet, pult):
    """Ein wartender oder laufender Wissens-Lauf haelt weder Chat noch Formular auf und laedt nie neu."""
    for status in ("offen", "in_arbeit"):
        pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": status}
        r = seite(angemeldet)
        assert 'http-equiv="refresh"' not in r.text, status
        assert 'action="/marketing/marke/senden"' in r.text, status
        assert '<a href="/marketing/layouts">Aktualisieren</a>' in r.text, status
    s = rumpf(seite(angemeldet, "/marketing/layouts?bearbeiten=1"))
    assert 'action="/marketing/marke/bearbeiten"' in s


def test_r7_refresh_bleibt_fuer_chat_bearbeitung_und_uebernahme(angemeldet, pult):
    pult.zustand["wissen"] = {**WISSEN_FERTIG, "status": "in_arbeit"}
    pult.zustand["laeuft"] = True
    assert '<meta http-equiv="refresh" content="5">' in seite(angemeldet).text
    pult.zustand["laeuft"] = False
    pult.zustand["uebernahme"] = "laeuft"
    assert '<meta http-equiv="refresh" content="5">' in seite(angemeldet).text


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
    p = rumpf(seite(angemeldet))                     # die Profilkarte liest dieselbe Quelle
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
