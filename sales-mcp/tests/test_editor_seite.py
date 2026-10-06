"""Newsletter-Editor im Pult (Spec 2026-09-29-newsletter-editor-design.md
§3.1/§3.2, Plan E1 Task 6): Editor-Seite, Speichern, Medienliste, signierte
Bilder, Vorlagen. Der Client zur Marketing-API wird gefaelscht."""
import json
import os
import re

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_editor  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
IID = "11111111-1111-1111-1111-111111111111"
DOK = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["i"]}},
       "i": {"type": "Image", "data": {"props": {"url": "medien:logo.png"}}}}
FELDER = {"betreff": "Early Access", "vorschautext": "", "abschnitte": [{"titel": "", "text": "Hallo"}],
          "knopf_text": "", "knopf_link": ""}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.zeitlimits = []
        self.betreff = "Oktober-Ausgabe"
        self.format = "bloecke"
        self.art = "newsletter"
        self.status = "entwurf"
        self.alter_weg = None
        self.alt_format = "felder"          # Format der aelteren Fassung 1
        self.speichern_antwort = {"fassung": 3}
        self.bilder = {"auftraege": []}
        self.verweise = []
        self.gestaltung_antwort = {"url": "/medien/datei/gs-0123456789ab.jpg", "width": 1200,
                                   "height": 800, "hinweise": []}

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        self.zeitlimits.append(zeitlimit)
        if self.fehler:
            raise self.fehler
        if roh:
            return (b"<!doctype html><p>Vorschau</p>", "text/html")
        if pfad.startswith("/uebersicht"):
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True}],
                    "zaehler": {"entwurf": 1, "freigegeben": 0, "abgelehnt": 0}}
        if pfad.startswith("/inhalte?"):
            return {"inhalte": [{"id": IID, "art": "newsletter", "titel": "Oktober",
                                 "status": "entwurf", "erstellt_am": "2026-09-29", "fassungen": 2,
                                 "layout": None}]}
        if pfad == f"/inhalte/{IID}":
            bloecke = self.format == "bloecke"
            neu = {"fassung": 2, "felder": {"betreff": self.betreff, "vorschautext": "Kurz"} if bloecke else FELDER,
                   "layout": None if bloecke else "dunkel", "urheber": "betreiber", "erstellt_am": "x",
                   "format": self.format, "bloecke": DOK if bloecke else None}
            alt = {"fassung": 1, "felder": FELDER, "layout": "dunkel", "urheber": "agent",
                   "erstellt_am": "y", "format": self.alt_format, "bloecke": None}
            return {"inhalt": {"id": IID, "art": self.art, "titel": "Oktober", "status": self.status,
                               "mandant": "vibemind"},
                    "fassungen": [neu, alt], "alter_weg": self.alter_weg}
        if pfad == f"/inhalte/{IID}/bilder":
            return {"auftrag": "a1"} if methode == "POST" else self.bilder
        if pfad == f"/inhalte/{IID}/gestaltung":
            return self.gestaltung_antwort
        if pfad == f"/inhalte/{IID}/chat":
            return {"auftrag": "c1"} if methode == "POST" else {
                "laeuft": True, "verlauf": [{"id": "c1"}],
                "live": {"schritt": "Titel", "schritt_nr": 2, "zwischenstand": {"b1": {"t": "x"}}, "stopp": None},
                "vorgemerkt": {"id": "v1", "nachricht": "Danach den Fuss"}}
        if pfad == f"/inhalte/{IID}/chat/vormerkung":
            return {"id": "v1", "status": "wartet"} if methode == "PUT" else {"geloescht": True}
        if pfad == f"/inhalte/{IID}/chat/vormerkung/starten":
            return {"auftrag": "c2"}
        if pfad == f"/inhalte/{IID}/chat/stopp":
            return {"abgeschlossen": False}
        if pfad == f"/inhalte/{IID}/chat/rueckgaengig":
            return {"fassung": 4}
        if pfad == f"/inhalte/{IID}/export/vorschau":
            return {"flaechen": {"kopf": {"handy": "medien:gs-0123456789ab.jpg", "tablet": "x", "pc": "y"}}}
        if pfad == f"/inhalte/{IID}/export":
            return {"dateien": ["oktober-handy.jpg"], "auftrag": "e1"}
        if pfad == f"/inhalte/{IID}/bloecke":
            return self.speichern_antwort
        if pfad == f"/inhalte/{IID}/in_bloecke":
            return {"fassung": 3}
        if pfad == "/inhalte/aus_vorlage":
            return {"id": IID}
        if pfad.startswith("/vorlagen?"):
            return {"vorlagen": [{"name": "leer", "beschreibung": "Leere Vorlage", "status": "freigegeben",
                                  "fassung": 1}]}
        if pfad.startswith("/layouts"):
            return {"layouts": []}
        if pfad.startswith("/medien/verweise?name="):
            return {"verweise": self.verweise}
        return {}


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


def _start(text: str) -> dict:
    roh = re.search(r'<script type="application/json" id="editor-start">(.*?)</script>', text, re.S).group(1)
    return json.loads(roh)


# --- Editor-Seite ---------------------------------------------------------------

def test_editor_seite_einzige_mit_skript(angemeldet):
    r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert csp == ui_editor.CSP_EDITOR                  # genau diese, nicht die Seiten-CSP
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert '<script src="/static/editor/editor.js"' in r.text
    assert '<link rel="stylesheet" href="/static/editor/editor.css">' in r.text
    start = _start(r.text)
    assert start["basis_fassung"] == 2 and start["csrf"] == ui.CSRF_TOKEN
    assert start["dokument"]["i"]["data"]["props"]["url"] == "medien:logo.png"
    assert start["betreff"] == "Oktober-Ausgabe" and start["vorschautext"] == "Kurz"
    assert start["speichern_url"] == f"/marketing/editor/{IID}/speichern"
    assert start["vorschau_url"] == f"/marketing/entwurf/{IID}/vorschau"
    assert start["medien_url"] == "/marketing/editor/medien.json"
    assert start["zurueck_url"] == f"/marketing/entwurf/{IID}"
    assert "Der Editor braucht einen größeren Bildschirm" in r.text
    # Nur ein Skript: das Paket. Das Datenelement ist kein Skript.
    assert len(re.findall(r"<script(?![^>]*application/json)", r.text)) == 1


def test_schmal_hinweis_regel_vor_media_query(angemeldet):
    """Die Grundregel .schmal{display:none} muss VOR der Media-Query stehen,
    sonst ueberstimmt sie bei gleicher Spezifitaet das display:block (im
    Browser-Smoke gemessen: Hinweis bei 390 px unsichtbar)."""
    s = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text
    stil = re.search(r"<style>(.*?)</style>", s, re.S).group(1)
    assert stil.index(".schmal{display:none") < stil.index("@media (max-width:767px)")


def test_andere_pult_seiten_bleiben_skriptfrei(angemeldet):
    for pfad in ("/marketing", "/marketing/entwuerfe", f"/marketing/entwurf/{IID}", "/marketing/vorlagen",
                 "/marketing/layouts", "/"):
        r = angemeldet.get(pfad, headers=HOST)
        assert "script-src" not in r.headers.get("content-security-policy", ""), pfad
        assert "connect-src" not in r.headers.get("content-security-policy", ""), pfad
        assert "<script" not in r.text.replace('type="application/json"', ""), pfad


def test_startdaten_escapen_schliessendes_tag(angemeldet, pult):
    pult.betreff = "</script><script>alert(1)</script><!--"
    r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    assert "</script><script>alert(1)" not in r.text and "<!--" not in r.text
    assert _start(r.text)["betreff"] == "</script><script>alert(1)</script><!--"


def test_editor_nur_fuer_bloecke_newsletter_entwurf(angemeldet, pult):
    for feld, wert in (("format", "felder"), ("art", "post"), ("status", "freigegeben")):
        f = Falsch()
        setattr(f, feld, wert)
        pult.__dict__.update(f.__dict__)
        r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
        assert r.status_code == 422 and "lässt sich nicht im Editor öffnen" in r.text, feld
        assert "script-src" not in r.headers["content-security-policy"], feld


def test_editor_marketing_nicht_erreichbar(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "timeout")
    r = angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    assert r.status_code == 503 and "script-src" not in r.headers["content-security-policy"]


# --- Speichern ------------------------------------------------------------------

def _speichern(c, headers=None, **mehr):
    body = {"basis_fassung": 2, "betreff": "B", "vorschautext": "", "dokument": DOK, **mehr}
    return c.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, **(headers or {})}, json=body)


def test_speichern_braucht_csrf_header(angemeldet, pult):
    for kopf in ({}, {"X-CSRF": "falsch"}):
        r = _speichern(angemeldet, kopf)
        assert r.status_code == 403 and r.json() == {"grund": "Fehlende oder falsche CSRF-Marke"}
    assert not any(a[1].endswith("/bloecke") for a in pult.aufrufe)


def test_speichern_csrf_im_body_reicht_nicht(angemeldet, pult):
    r = _speichern(angemeldet, csrf=ui.CSRF_TOKEN)
    assert r.status_code == 403 and not any(a[1].endswith("/bloecke") for a in pult.aufrufe)


def test_speichern_reicht_durch(angemeldet, pult):
    r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 200 and r.json() == {"fassung": 3}
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", f"/inhalte/{IID}/bloecke")
    assert d == {"basis_fassung": 2, "betreff": "B", "vorschautext": "", "bloecke": DOK,
                 "als_kopie": False, "urheber": "betreiber"}


def test_speichern_als_kopie(angemeldet, pult):
    r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN}, als_kopie=True)
    assert r.status_code == 200 and pult.aufrufe[-1][2]["als_kopie"] is True


def test_speichern_prueft_den_koerper(angemeldet, pult):
    kopf = {"X-CSRF": ui.CSRF_TOKEN}
    for schlecht in ({"basis_fassung": True}, {"basis_fassung": -1}, {"basis_fassung": "2"},
                     {"dokument": "nein"}, {"dokument": []}, {"betreff": 5}, {"vorschautext": None},
                     {"als_kopie": "ja"}):
        r = _speichern(angemeldet, kopf, **schlecht)
        assert r.status_code == 422 and r.json()["grund"], schlecht
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, **kopf,
                        "content-type": "application/json"}, content=b"{kaputt")
    assert r.status_code == 422
    r = angemeldet.post(f"/marketing/editor/{IID}/speichern", headers={**HOST, **kopf}, json=[1, 2])
    assert r.status_code == 422
    assert not any(a[1].endswith("/bloecke") for a in pult.aufrufe)


def test_konflikt_wird_409(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Inzwischen gibt es Fassung 5 - neu laden oder als Kopie behalten")
    r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 409 and r.json() == {
        "konflikt": True, "grund": "Inzwischen gibt es Fassung 5 - neu laden oder als Kopie behalten"}


def test_andere_ablehnung_422(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Blocktyp Html ist nicht erlaubt")
    r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 422 and "Html" in r.json()["grund"]


def test_api_weg_wird_503(angemeldet, pult):
    for art in ("nicht_erreichbar", "nicht_verbunden", "unbekannt"):
        pult.fehler = marketing_pult.PultFehler(art, "intern")
        r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
        assert r.status_code == 503 and r.json() == {"grund": "Speichern gerade nicht möglich"}, art


# --- Medienliste ------------------------------------------------------------------

def test_medien_json_nur_bilder_ohne_interne(angemeldet, monkeypatch, tmp_path):
    for name in ("logo.png", "team.jpg", "preise.pdf", "terminkarte-x.png", "clip.mp4"):
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n0000")
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    monkeypatch.setattr(server.medien, "ERZEUGT_VERZEICHNIS", str(tmp_path / "fehlt"))
    r = angemeldet.get("/marketing/editor/medien.json", headers=HOST)
    assert r.status_code == 200 and r.json() == {"bilder": ["logo.png", "team.jpg"]}


def test_medien_json_ordner_fehlt(angemeldet, monkeypatch, tmp_path):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path / "gibtsnicht"))
    r = angemeldet.get("/marketing/editor/medien.json", headers=HOST)
    assert r.status_code == 200 and r.json() == {"bilder": []}


# --- Signierte Bilder ------------------------------------------------------------------

def test_bild_token(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    t = ui_editor.bild_token(jetzt=1000)
    assert ui_editor.bild_token_ok(t, jetzt=1500)
    assert not ui_editor.bild_token_ok(t, jetzt=1000 + 901)
    ablauf, sig = t.split(".")
    assert not ui_editor.bild_token_ok(f"{int(ablauf) + 60}.{sig}", jetzt=1500)
    assert not ui_editor.bild_token_ok("kaputt", jetzt=1500)
    assert not ui_editor.bild_token_ok(f"{ablauf}.", jetzt=1500)
    # Ein Token aus der Zukunft (weiter als 15 Minuten) gilt nicht
    fern = ui_editor.bild_token(jetzt=5000)
    assert not ui_editor.bild_token_ok(fern, jetzt=1000)
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "anderes")
    assert not ui_editor.bild_token_ok(t, jetzt=1500)
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")
    assert not ui_editor.bild_token_ok(t, jetzt=1500)


def test_bild_basis(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    monkeypatch.setattr(ui, "UI_BASIS_URL", "https://laden.example.ts.net/")
    b = ui_editor.bild_basis()
    assert re.fullmatch(r"https://laden\.example\.ts\.net/marketing/bild/\d+\.[0-9a-f]{64}/", b)
    # Die API nimmt nur https-Adressen - ohne https keine Bilder statt 422
    monkeypatch.setattr(ui, "UI_BASIS_URL", "http://127.0.0.1:8791")
    assert ui_editor.bild_basis() == ""
    monkeypatch.setattr(ui, "UI_BASIS_URL", "https://laden.example.ts.net")
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")
    assert ui_editor.bild_basis() == ""


@pytest.fixture
def medien_ordner(monkeypatch, tmp_path):
    ordner = tmp_path / "media"
    ordner.mkdir()
    (ordner / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 10)
    (ordner / "preise.pdf").write_bytes(b"%PDF-1.4 x")
    (ordner / "terminkarte-kunde.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 10)
    (tmp_path / "geheim.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 10)
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(ordner))
    monkeypatch.setattr(server.medien, "ERZEUGT_VERZEICHNIS", str(tmp_path / "fehlt"))
    return ordner


def test_bild_route_ohne_anmeldung_nur_mit_token(monkeypatch, medien_ordner):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    gut = ui_editor.bild_token()
    r = c.get(f"/marketing/bild/{gut}/logo.png", headers=HOST)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=300"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    abgelaufen = ui_editor.bild_token(jetzt=1000)
    for pfad in ("/marketing/bild/0.abc/logo.png", f"/marketing/bild/{abgelaufen}/logo.png",
                 f"/marketing/bild/{gut}/..%2Fgeheim.png", f"/marketing/bild/{gut}/..%5Cgeheim.png",
                 f"/marketing/bild/{gut}/text.txt", f"/marketing/bild/{gut}/preise.pdf",
                 f"/marketing/bild/{gut}/terminkarte-kunde.png", f"/marketing/bild/{gut}/fehlt.png"):
        r = c.get(pfad, headers=HOST, follow_redirects=False)
        # 404 vom Handler; Pfade mit einem (entschluesselten) "/" zu viel
        # laesst schon die Wache nicht durch (-> /login)
        assert r.status_code == 404 or (r.status_code == 303 and r.headers["location"] == "/login"), pfad
        assert b"PNG" not in r.content, pfad


def test_bild_route_liefert_entwurfsbilder_aus(monkeypatch, medien_ordner):
    # Block-Bilder `medien:gs-...` werden ueber diese Route angezeigt.
    (medien_ordner / "gs-0123456789ab.jpg").write_bytes(bytes([0xFF, 0xD8, 0xFF]) + b"0" * 10)
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    r = c.get(f"/marketing/bild/{ui_editor.bild_token()}/gs-0123456789ab.jpg", headers=HOST)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert server.medien.pruefe_anhang("gs-0123456789ab.jpg")[0] is None   # Anhang: weiter gesperrt


def test_bild_route_nur_get(monkeypatch, medien_ordner):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    r = c.post(f"/marketing/bild/{ui_editor.bild_token()}/logo.png", headers=HOST)
    assert r.status_code == 403                             # Wache: kein POST ohne Anmeldung


def test_anmeldewache_ausnahme_ist_praefixgenau(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    for pfad in ("/marketing/bildX/a/b.png", "/marketing/bild", "/marketing/bild/", "/marketing/bild/a",
                 "/marketing/bild/a/b/c.png", "/marketing/bild/../entwuerfe", "/marketing/bild/%2e%2e/entwuerfe",
                 f"/marketing/bild/{'1.' + '0' * 64}/..", f"/marketing/bild/{'1.' + '0' * 64}/.x.png",
                 f"/marketing/bild/{'1.' + '0' * 64}/a/b.png"):
        r = c.get(pfad, headers=HOST, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", pfad


def _beispielpfad(route: Route) -> str:
    # Das Token wohlgeformt, aber falsch signiert - so kommt die Anfrage
    # durch die Wache bis zur Signaturpruefung der Route.
    pfad = route.path.replace("{token}", "1." + "0" * 64).replace("{name}", "x.png")
    return re.sub(r"\{[^}]+\}", "x", pfad)


def test_ohne_anmeldung_ist_kein_marketing_pfad_offen(monkeypatch):
    """Jede registrierte /marketing-Route ohne Sitzung -> /login (GET) bzw.
    403 (POST) - ausser dem signierten /marketing/bild/..."""
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    routen = [r for r in ui.app.routes if isinstance(r, Route) and r.path.startswith("/marketing")]
    assert len(routen) >= 18
    offen = []
    for route in routen:
        pfad = _beispielpfad(route)
        for methode in sorted(route.methods - {"HEAD"}):
            r = c.request(methode, pfad, headers=HOST, follow_redirects=False)
            geschuetzt = ((r.status_code == 303 and r.headers.get("location") == "/login") if methode == "GET"
                          else (r.status_code == 403 and "Nicht angemeldet" in r.text))
            if not geschuetzt:
                offen.append((methode, route.path, r.status_code))
    # offen sind genau die zwei Ausnahmen: signiertes Bild und eigene Schriften
    assert sorted(offen) == [("GET", "/marketing/bild/{token}/{name}", 404),
                             ("GET", "/marketing/schrift/{datei}", 404)]


def test_statik_ohne_anmeldung_nicht_erreichbar(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    r = TestClient(ui.app).get("/static/editor/editor.js", headers=HOST, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_pfad_erlaubt_bild_fuer_jede_rolle(monkeypatch):
    t = "1." + "a" * 64
    for rolle in ("freigeben", "lesen", "kalender", ""):
        assert ui._pfad_erlaubt(rolle, f"/marketing/bild/{t}/logo.png"), rolle
    assert not ui._pfad_erlaubt("lesen", f"/marketing/bildX/{t}/logo.png")
    assert not ui._pfad_erlaubt("lesen", "/marketing/bild/1.a/logo.png")      # kein Token-Format
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", f"/marketing/bild/{t}/logo.png")
    assert not ui._pfad_erlaubt("freigeben", "/marketing/editor/x")


# --- Vorschau-Proxy und Entwurfsseite ---------------------------------------------

def test_vorschau_proxy_gibt_bild_basis_mit(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(ui, "UI_BASIS_URL", "https://laden.example.ts.net")
    r = angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    csp = r.headers["content-security-policy"]
    assert "img-src 'self' data:" in csp and "sandbox" in csp and "script-src" not in csp
    pfad = [a[1] for a in pult.aufrufe if "/vorschau" in a[1]][-1]
    assert "bild_basis=" in pfad and "%2Fmarketing%2Fbild%2F" in pfad
    assert "bild_basis=https%3A%2F%2Fladen.example.ts.net%2Fmarketing%2Fbild%2F" in pfad


def test_vorschau_proxy_ohne_https_ohne_bild_basis(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(ui, "UI_BASIS_URL", "http://127.0.0.1:8791")
    angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    pfad = [a[1] for a in pult.aufrufe if "/vorschau" in a[1]][-1]
    assert "bild_basis" not in pfad


def test_entwurf_mit_bloecken_zeigt_editor_knopf(angemeldet):
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    s = r.text
    assert f'href="/marketing/editor/{IID}"' in s and "Im Editor öffnen" in s
    assert "Dieser Newsletter wird im Editor bearbeitet." in s
    assert 'name="abschnitt_text"' not in s and f'action="/marketing/entwurf/{IID}/speichern"' not in s
    assert 'value="freigeben"' in s and 'value="ablehnen"' in s          # Urteil bleibt
    assert "script-src" not in r.headers["content-security-policy"]


def test_entwurf_mit_feldern_bleibt_formular(angemeldet, pult):
    pult.format = "felder"
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert 'name="abschnitt_text"' in s and "/marketing/editor/" not in s


def test_entwurf_bloecke_kein_pdf_verweis(angemeldet):
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert "format=pdf" not in s


def test_uebersicht_verweist_auf_vorlagen(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    assert 'href="/marketing/vorlagen"' in s and "Neuer Newsletter aus Vorlage" in s


# --- Vorlagen ------------------------------------------------------------------

def test_vorlagen_seite(angemeldet, pult):
    r = angemeldet.get("/marketing/vorlagen", headers=HOST)
    s = r.text
    assert r.status_code == 200 and "Leere Vorlage" in s
    assert '<iframe class="layout-bild" sandbox' in s and 'src="/marketing/vorlage-bild/leer"' in s
    assert 'action="/marketing/aus-vorlage"' in s and 'name="vorlage" value="leer"' in s
    assert 'name="titel"' in s and f'value="{ui.CSRF_TOKEN}"' in s
    assert "frame-src 'self'" in r.headers["content-security-policy"]
    assert ("GET", "/vorlagen?mandant=vibemind&status=freigegeben", None) in pult.aufrufe


def test_vorlage_bild_proxy(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(ui, "UI_BASIS_URL", "https://laden.example.ts.net")
    r = angemeldet.get("/marketing/vorlage-bild/leer", headers=HOST)
    assert r.status_code == 200 and b"Vorschau" in r.content
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox") and "img-src 'self' data:" in csp and "frame-ancestors 'self'" in csp
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    pfad = pult.aufrufe[-1][1]
    assert pfad.startswith("/vorlagen/leer/vorschau?format=mail&") and "bild_basis=https%3A" in pfad


def test_vorlage_bild_unbekannter_name(angemeldet, pult):
    r = angemeldet.get("/marketing/vorlage-bild/..%2Fx", headers=HOST)
    assert r.status_code == 404 and not any("/vorlagen/" in a[1] for a in pult.aufrufe)


def test_aus_vorlage(angemeldet, pult):
    r = angemeldet.post("/marketing/aus-vorlage", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "vorlage": "leer", "titel": "  Oktober  "})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/editor/{IID}"
    assert pult.aufrufe[-1] == ("POST", "/inhalte/aus_vorlage",
                                {"vorlage": "leer", "titel": "Oktober", "mandant": "vibemind"})


def test_aus_vorlage_ohne_csrf_oder_mit_schlechten_werten(angemeldet, pult):
    r = angemeldet.post("/marketing/aus-vorlage", headers=HOST, data={"vorlage": "leer", "titel": "T"})
    assert r.status_code == 403
    for daten in ({"vorlage": "leer", "titel": ""}, {"vorlage": "leer", "titel": "x" * 201},
                  {"vorlage": "../x", "titel": "T"}):
        r = angemeldet.post("/marketing/aus-vorlage", headers=HOST, data={"csrf": ui.CSRF_TOKEN, **daten})
        assert r.status_code == 422, daten
    assert not any(a[1] == "/inhalte/aus_vorlage" for a in pult.aufrufe)


def test_aus_vorlage_ablehnung_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Unbekannte Vorlage")
    r = angemeldet.post("/marketing/aus-vorlage", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "vorlage": "leer", "titel": "T"})
    assert r.status_code == 422 and "Unbekannte Vorlage" in r.text


# --- Statik ------------------------------------------------------------------

def test_statische_dateien_nur_zwei(angemeldet):
    js = angemeldet.get("/static/editor/editor.js", headers=HOST)
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert js.headers["cache-control"] == "no-cache"
    css = angemeldet.get("/static/editor/editor.css", headers=HOST)
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    for pfad in ("/static/editor/MANIFEST.json", "/static/editor/../ui.py", "/static/editor/..%2F..%2Fui.py",
                 "/static/editor/.gitattributes"):
        assert angemeldet.get(pfad, headers=HOST).status_code == 404, pfad


def test_i1_kein_api_aufruf_im_event_loop(angemeldet, pult, monkeypatch):
    import asyncio
    im_loop = []
    original = pult.anfrage

    def spion(*a, **k):
        try:
            asyncio.get_running_loop()
            im_loop.append(a[1])
        except RuntimeError:
            pass
        return original(*a, **k)

    monkeypatch.setattr(marketing_pult, "anfrage", spion)
    angemeldet.get(f"/marketing/editor/{IID}", headers=HOST)
    _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
    angemeldet.get("/marketing/vorlagen", headers=HOST)
    angemeldet.get("/marketing/vorlage-bild/leer", headers=HOST)
    angemeldet.post("/marketing/aus-vorlage", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "vorlage": "leer", "titel": "T"})
    assert len(pult.aufrufe) >= 5 and im_loop == []


# --- Schlussrunde E1 (final-fix-findings.md) ------------------------------------

def test_i7_alter_weg_im_datenelement(angemeldet, pult):
    assert _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)["alter_weg"] is None
    pult.alter_weg = {"status": "pending_approval", "kanal": "email"}
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["alter_weg"] == {"status": "pending_approval", "kanal": "email"}


def test_speichern_koerper_hoechstens_300_kb(angemeldet, pult):
    gross = {"root": {"type": "EmailLayout", "data": {"childrenIds": []}},
             "t": {"type": "Text", "data": {"props": {"text": "x" * (300 * 1024)}}}}
    r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN}, dokument=gross)
    assert r.status_code == 413 and "300 KB" in r.json()["grund"]
    assert not any(a[1].endswith("/bloecke") for a in pult.aufrufe)
    # knapp darunter geht durch
    klein = {"root": {"type": "EmailLayout", "data": {"childrenIds": []}},
             "t": {"type": "Text", "data": {"props": {"text": "x" * (250 * 1024)}}}}
    assert _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN}, dokument=klein).status_code == 200


def test_speichern_kaputte_api_antwort_503(angemeldet, pult):
    for antwort in ({}, {"fassung": "drei"}, {"fassung": None}, {"fassung": [3]}):
        pult.speichern_antwort = antwort
        r = _speichern(angemeldet, {"X-CSRF": ui.CSRF_TOKEN})
        assert r.status_code == 503 and r.json() == {"grund": "Speichern gerade nicht möglich"}, antwort


def test_bild_route_entschluesselt_nur_einmal(monkeypatch, medien_ordner):
    """Starlette entschluesselt den Pfad schon; ein zweites unquote machte aus
    logo%2Epng wieder logo.png (Umgehung der Endungs- und Namenspruefung)."""
    import asyncio
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    gut = ui_editor.bild_token()

    async def holen(pfad: str, roh: str) -> tuple[int, bytes]:
        # Roher ASGI-Aufruf: der Test-Client entschluesselt %25 selbst schon
        # einmal und saehe den Fehler nie. So kommt der Pfad an, wie uvicorn
        # ihn aus "logo%252Epng" macht: path "logo%2Epng".
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": pfad, "raw_path": roh.encode(), "query_string": b"",
                 "root_path": "", "headers": [(b"host", HOST["host"].encode())],
                 "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8791)}
        eingang = [{"type": "http.request", "body": b"", "more_body": False}]
        aus = {"status": 0, "body": b""}

        async def receive():
            return eingang.pop(0) if eingang else {"type": "http.disconnect"}

        async def send(m):
            if m["type"] == "http.response.start":
                aus["status"] = m["status"]
            elif m["type"] == "http.response.body":
                aus["body"] += m.get("body", b"")
        await ui.app(scope, receive, send)
        return aus["status"], aus["body"]

    status, inhalt = asyncio.run(holen(f"/marketing/bild/{gut}/logo%2Epng", f"/marketing/bild/{gut}/logo%252Epng"))
    assert status == 404 and b"PNG" not in inhalt
    status, inhalt = asyncio.run(holen(f"/marketing/bild/{gut}/logo.png", f"/marketing/bild/{gut}/logo.png"))
    assert status == 200 and inhalt.startswith(b"\x89PNG")


def test_i8_knopf_ins_editor_format_nur_fuer_feld_newsletter(angemeldet, pult):
    pult.format = "felder"
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert f'action="/marketing/entwurf/{IID}/in-bloecke"' in s and "Ins Editor-Format übernehmen" in s
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in s
    for feld, wert in (("format", "bloecke"), ("art", "post"), ("status", "freigegeben")):
        f = Falsch()
        f.format = "felder"
        setattr(f, feld, wert)
        pult.__dict__.update(f.__dict__)
        s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
        assert "Ins Editor-Format übernehmen" not in s, feld


def test_i8_uebernehmen_leitet_in_den_editor(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/in-bloecke", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/editor/{IID}"
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", f"/inhalte/{IID}/in_bloecke") and d == {"von": "mira"}


def test_i8_uebernehmen_csrf_und_ablehnung(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/in-bloecke", headers=HOST, data={}, follow_redirects=False)
    assert r.status_code == 403 and not any(a[1].endswith("/in_bloecke") for a in pult.aufrufe)
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Dieser Newsletter ist schon im Editor-Format")
    r = angemeldet.post(f"/marketing/entwurf/{IID}/in-bloecke", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN}, follow_redirects=False)
    assert r.status_code == 422 and "schon im Editor-Format" in r.text


def test_formularwahl_nach_neuester_fassung(angemeldet, pult):
    """Aeltere Feld-Fassung eines Editor-Newsletters ansehen: kein Feldformular
    (die DB lehnte das Speichern ohnehin ab), sondern der Weg in den Editor."""
    s = angemeldet.get(f"/marketing/entwurf/{IID}?fassung=1", headers=HOST).text
    assert "Fassung 1" in s
    assert 'name="abschnitt_text"' not in s and f'href="/marketing/editor/{IID}"' in s
    # umgekehrt: neueste ist Feldformat, aeltere war Bloecke -> Formular, kein Editor-Knopf
    pult.format, pult.alt_format = "felder", "bloecke"
    s = angemeldet.get(f"/marketing/entwurf/{IID}?fassung=1", headers=HOST).text
    assert 'name="abschnitt_text"' in s and "/marketing/editor/" not in s

# --- Bilder: Auftrag und Stand (Newsletter-Bilder Task 8) -----------------------

def test_start_nennt_bild_und_stand_url(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["bild_url"] == f"/marketing/editor/{IID}/bild"
    assert start["stand_url"] == f"/marketing/editor/{IID}/stand.json"


def test_bild_beauftragen(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"platz": "kopf", "hinweis": "waermer"})
    assert r.status_code == 200 and r.json() == {"auftrag": "a1"}
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/bilder",
                                {"platz": "kopf", "hinweis": "waermer", "nur_leere": False,
                                 "staerke": 55, "modus": "ueberarbeiten"})


def test_bild_mit_staerke(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"platz": "kopf", "hinweis": "waermer", "staerke": 30})
    assert r.status_code == 200
    assert pult.aufrufe[-1][2] == {"platz": "kopf", "hinweis": "waermer", "nur_leere": False,
                                   "staerke": 30, "modus": "ueberarbeiten"}


def test_bild_ganz_neu(angemeldet, pult):
    angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                    json={"platz": "kopf", "neu": True, "staerke": 20})
    assert pult.aufrufe[-1][2]["staerke"] == 100 and pult.aufrufe[-1][2]["modus"] == "neu"


def test_bild_staerke_100_ist_neu(angemeldet, pult):
    angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                    json={"platz": "kopf", "staerke": 100})
    assert pult.aufrufe[-1][2]["staerke"] == 100 and pult.aufrufe[-1][2]["modus"] == "neu"


@pytest.mark.parametrize("body", [{"staerke": 101}, {"staerke": -1}, {"staerke": True},
                                  {"staerke": "5"}, {"neu": "ja"}])
def test_bild_formen_staerke_neu(angemeldet, pult, body):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"platz": "kopf", **body})
    assert r.status_code == 422
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_bild_beauftragen_formen_und_csrf(angemeldet, pult):
    assert angemeldet.post(f"/marketing/editor/{IID}/bild", headers=HOST, json={"platz": "kopf"}).status_code == 403
    for body in ({"platz": "a b"}, {"platz": 5}, {"hinweis": "x" * 501}, [1]):
        r = angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN}, json=body)
        assert r.status_code == 422, body
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_bild_beauftragen_db_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler(
        "abgelehnt", "Bildplatz kopf gibt es in der gespeicherten Fassung nicht - erst speichern")
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", headers={**HOST, "X-CSRF": ui.CSRF_TOKEN},
                        json={"platz": "kopf"})
    assert r.status_code == 422 and "erst speichern" in r.json()["grund"]


# --- Gestaltungsflaeche durchreichen ---------------------------------------------

GESTALTUNG = {"format": "quer", "alt": "Herbst", "ebenen": []}


def _gestalten(c, body, csrf=True):
    h = {**HOST, "X-CSRF": ui.CSRF_TOKEN} if csrf else HOST
    return c.post(f"/marketing/editor/{IID}/gestaltung", headers=h, json=body)


def test_start_nennt_gestaltung_url(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["gestaltung_url"] == f"/marketing/editor/{IID}/gestaltung"


def test_gestaltung_durchreichen(angemeldet, pult):
    r = _gestalten(angemeldet, {"gestaltung": GESTALTUNG})
    assert r.status_code == 200 and r.json() == pult.gestaltung_antwort
    assert r.headers["cache-control"] == "no-store"
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/gestaltung", {"gestaltung": GESTALTUNG})
    assert pult.zeitlimits[-1] == ui_editor.GESTALTUNG_ZEITLIMIT_S == 30      # Flaechen mit vielen Ebenen rechnen laenger als 8 s


def test_gestaltung_ohne_csrf(angemeldet, pult):
    assert _gestalten(angemeldet, {"gestaltung": GESTALTUNG}, csrf=False).status_code == 403
    assert not any(a[0] == "POST" for a in pult.aufrufe)


@pytest.mark.parametrize("body", [{}, {"gestaltung": "x"}, {"gestaltung": [1]}, {"gestaltung": None}, [1]])
def test_gestaltung_kein_objekt(angemeldet, pult, body):
    r = _gestalten(angemeldet, body)
    assert r.status_code == 422 and r.json()["grund"] == "Gestaltung fehlt"
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_gestaltung_pult_lehnt_ab(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Bild x fehlt in den Medien")
    r = _gestalten(angemeldet, {"gestaltung": GESTALTUNG})
    assert r.status_code == 422 and r.json() == {"grund": "Bild x fehlt in den Medien"}


@pytest.mark.parametrize("art", ["nicht_erreichbar", "nicht_verbunden", "unbekannt"])
def test_gestaltung_pult_weg(angemeldet, pult, art):
    pult.fehler = marketing_pult.PultFehler(art, "intern")
    r = _gestalten(angemeldet, {"gestaltung": GESTALTUNG})
    assert r.status_code == 503 and r.json() == {"grund": "Gestaltung gerade nicht möglich"}


def test_medien_json_ohne_entwurfsbilder(angemeldet, monkeypatch, tmp_path):
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    (tmp_path / "leer").mkdir()
    for name in ("gs-0123456789ab.jpg", "nl-12345678-x.jpg"):
        (erzeugt / name).write_bytes(bytes([0xFF, 0xD8]) + b"x" * 64)
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path / "leer"))
    monkeypatch.setattr(server.medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    r = angemeldet.get("/marketing/editor/medien.json", headers=HOST)
    assert r.json() == {"bilder": ["nl-12345678-x.jpg"]}


def test_stand_json(angemeldet, pult):
    pult.bilder = {"auftraege": [{"platz": "kopf", "status": "in_arbeit"}]}
    j = angemeldet.get(f"/marketing/editor/{IID}/stand.json", headers=HOST).json()
    assert j["fassung"] == 2 and j["auftraege"][0]["status"] == "in_arbeit"


# --- Bilder aus der Bibliothek loeschen (Betreiber 01.10.2026) -------------------

LOESCHEN = "/marketing/editor/medien/loeschen"


@pytest.fixture
def bibliothek(monkeypatch, tmp_path):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    (tmp_path / "nl-1234abcd-kopf.jpg").write_bytes(bytes([0xFF, 0xD8]) + b"x" * 64)
    return tmp_path


def _loeschen(c, name, bestaetigt=False, csrf=True):
    kopf = {**HOST, **({"X-CSRF": ui.CSRF_TOKEN} if csrf else {})}
    return c.post(LOESCHEN, json={"name": name, "bestaetigt": bestaetigt}, headers=kopf)


def test_start_kennt_die_loesch_adresse(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["medien_loeschen_url"] == LOESCHEN


def test_pruefen_loescht_nichts_und_berichtet(angemeldet, pult, bibliothek):
    r = _loeschen(angemeldet, "nl-1234abcd-kopf.jpg")
    assert r.status_code == 200
    assert r.json() == {"name": "nl-1234abcd-kopf.jpg", "entwuerfe": 0, "sperre": None, "newsletter": []}
    assert (bibliothek / "nl-1234abcd-kopf.jpg").is_file()
    assert ("GET", "/medien/verweise?name=nl-1234abcd-kopf.jpg", None) in pult.aufrufe


def test_bestaetigt_loescht_die_datei(angemeldet, pult, bibliothek):
    r = _loeschen(angemeldet, "nl-1234abcd-kopf.jpg", bestaetigt=True)
    assert r.status_code == 200 and r.json() == {"geloescht": "nl-1234abcd-kopf.jpg"}
    assert not (bibliothek / "nl-1234abcd-kopf.jpg").exists()


def test_bild_im_newsletter_sperrt(angemeldet, pult, bibliothek):
    pult.verweise = [{"id": IID, "titel": "Herbst-Update", "status": "entwurf", "art": "newsletter", "wo": "aktuell"}]
    info = _loeschen(angemeldet, "nl-1234abcd-kopf.jpg").json()
    assert "Herbst-Update" in info["sperre"] and info["newsletter"] == [{"titel": "Herbst-Update", "status": "entwurf"}]
    r = _loeschen(angemeldet, "nl-1234abcd-kopf.jpg", bestaetigt=True)
    assert r.status_code == 409 and "Herbst-Update" in r.json()["grund"]
    assert (bibliothek / "nl-1234abcd-kopf.jpg").is_file()


def test_marketing_weg_sperrt_statt_zu_raten(angemeldet, pult, bibliothek):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "URLError")
    r = _loeschen(angemeldet, "nl-1234abcd-kopf.jpg", bestaetigt=True)
    assert r.status_code == 409 and "Marketing antwortet gerade nicht" in r.json()["grund"]
    assert (bibliothek / "nl-1234abcd-kopf.jpg").is_file()


def test_ohne_csrf_403(angemeldet, pult, bibliothek):
    assert _loeschen(angemeldet, "nl-1234abcd-kopf.jpg", bestaetigt=True, csrf=False).status_code == 403
    assert (bibliothek / "nl-1234abcd-kopf.jpg").is_file()


def test_platzhalter_bleiben(angemeldet, pult, bibliothek):
    (bibliothek / "platzhalter-2x1.png").write_bytes(bytes([0x89]) + b"PNG" + b"x" * 64)
    assert _loeschen(angemeldet, "platzhalter-2x1.png", bestaetigt=True).status_code == 422
    assert (bibliothek / "platzhalter-2x1.png").is_file()


@pytest.mark.parametrize("name", ["gibt-es-nicht.jpg", "../server.py", 7])
def test_unbekannt_oder_unsinn(angemeldet, pult, bibliothek, name):
    assert _loeschen(angemeldet, name, bestaetigt=True).status_code in (404, 422)


# --- Eigene Schriften, Schwarz-Weiss-Bilder, Vorschau-CSP (Newsletter-Vorlagen Task 8) ---

def test_schrift_css_ohne_anmeldung_mit_cors(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")     # Wache aktiv, keine Sitzung
    c = TestClient(ui.app)
    r = c.get("/marketing/schrift/schriften.css", headers=HOST, follow_redirects=False)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "font-family: 'Oxanium'" in r.text and "url(oxanium-600-normal.woff2)" in r.text
    assert "googleapis" not in r.text


def test_schriftdatei_und_nichts_anderes(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    r = c.get("/marketing/schrift/poppins-400-normal.woff2", headers=HOST, follow_redirects=False)
    assert r.status_code == 200 and r.content[:4] == b"wOF2" and r.headers["content-type"] == "font/woff2"
    assert r.headers["access-control-allow-origin"] == "*"
    for boese in ("../ui.py", "poppins.ttf", "x-400-normal.woff2", "%2e%2e%2fui.py",
                  "OFL-poppins.txt", "poppins-500-normal.woff2"):
        r = c.get(f"/marketing/schrift/{boese}", headers=HOST, follow_redirects=False)
        assert r.status_code in (303, 404), boese
        assert b"wOF2" not in r.content, boese
    # nur GET/HEAD ohne Anmeldung
    assert c.post("/marketing/schrift/schriften.css", headers=HOST, follow_redirects=False).status_code in (403, 405)


def test_schriften_register_und_dateien_stimmen():
    import schriften
    assert len(schriften.REGISTER) == 11
    assert sum(len(s["dateien"]) for s in schriften.REGISTER.values()) == 22
    for sid, s in schriften.REGISTER.items():
        assert (schriften.ORDNER / f"OFL-{sid}.txt").is_file(), sid
        for gewicht, stil in s["dateien"]:
            assert (schriften.ORDNER / f"{sid}-{gewicht}-{stil}.woff2").read_bytes()[:4] == b"wOF2"


def test_vorschau_csp_erlaubt_eigene_schriften():
    import ui_marketing
    assert "font-src 'self'" in ui_marketing._CSP_VORSCHAU
    assert "style-src 'self' 'unsafe-inline'" in ui_marketing._CSP_VORSCHAU


def test_bild_sw(monkeypatch, medien_ordner):
    import io
    from PIL import Image
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    Image.new("RGB", (8, 8), (200, 30, 30)).save(medien_ordner / "rot.png")
    Image.new("RGB", (8, 8), (200, 30, 30)).save(medien_ordner / "rot.jpg")
    c = TestClient(ui.app)
    t = ui_editor.bild_token()
    for name, fmt in (("rot.png", "PNG"), ("rot.jpg", "JPEG")):
        farbig = c.get(f"/marketing/bild/{t}/{name}", headers=HOST)
        grau = c.get(f"/marketing/bild/{t}/{name}?sw=1", headers=HOST)
        assert farbig.status_code == grau.status_code == 200
        assert Image.open(io.BytesIO(farbig.content)).convert("RGB").getpixel((4, 4))[0] > 150
        bild = Image.open(io.BytesIO(grau.content))
        assert bild.format == fmt
        px = bild.convert("RGB").getpixel((4, 4))
        assert px[0] == px[1] == px[2]


def test_bild_sw_kaputte_datei_liefert_original(monkeypatch, medien_ordner):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    c = TestClient(ui.app)
    r = c.get(f"/marketing/bild/{ui_editor.bild_token()}/logo.png?sw=1", headers=HOST)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")


def test_freistellen_nutzlast(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", json={"platz": "i", "freistellen": True, "staerke": 30, "neu": True},
                        headers={**HOST, "X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 200
    methode, pfad, daten = pult.aufrufe[-1]
    assert pfad == f"/inhalte/{IID}/bilder"
    assert daten == {"platz": "i", "hinweis": "", "nur_leere": False, "staerke": 0, "modus": "freistellen"}


@pytest.mark.parametrize("body", [{"freistellen": True}, {"platz": "i", "freistellen": "ja"}])
def test_freistellen_ungueltig(angemeldet, pult, body):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", json=body, headers={**HOST, "X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 422
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_freistellen_api_grund_durchgereicht(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Dieser Platz hat noch kein echtes Bild")
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", json={"platz": "i", "freistellen": True},
                        headers={**HOST, "X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 422 and "kein echtes Bild" in r.json()["grund"]


def test_bild_sw_behaelt_alpha(monkeypatch, medien_ordner):
    import io
    from PIL import Image
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    bild = Image.new("RGBA", (8, 8), (200, 30, 30, 255))
    bild.putpixel((0, 0), (200, 30, 30, 0))
    bild.save(medien_ordner / "frei.png")
    c = TestClient(ui.app)
    r = c.get(f"/marketing/bild/{ui_editor.bild_token()}/frei.png?sw=1", headers=HOST)
    assert r.status_code == 200
    grau = Image.open(io.BytesIO(r.content))
    assert grau.format == "PNG" and grau.mode == "LA"
    assert grau.getpixel((0, 0))[1] == 0 and grau.getpixel((4, 4))[1] == 255


# --- Chat, Rueckgaengig, Export durchreichen ---------------------------------------

def _post(c, ende, body, csrf=True):
    h = {**HOST, "X-CSRF": ui.CSRF_TOKEN} if csrf else HOST
    return c.post(f"/marketing/editor/{IID}/{ende}", headers=h, json=body)


def _posts(pult):
    return [a for a in pult.aufrufe if a[0] == "POST"]


def test_start_nennt_chat_und_export_urls(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["chat_url"] == f"/marketing/editor/{IID}/chat"
    assert start["chat_stand_url"] == f"/marketing/editor/{IID}/chat.json"
    assert start["chat_rueckgaengig_url"] == f"/marketing/editor/{IID}/chat/rueckgaengig"
    assert start["export_vorschau_url"] == f"/marketing/editor/{IID}/export/vorschau"
    assert start["export_url"] == f"/marketing/editor/{IID}/export"


def test_chat_durchreichen(angemeldet, pult):
    r = _post(angemeldet, "chat", {"nachricht": "Mach den Titel gross", "kontext": {"auswahl": "t1"}})
    assert r.status_code == 200 and r.json() == {"auftrag": "c1"}
    assert r.headers["cache-control"] == "no-store"
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/chat",
                                {"nachricht": "Mach den Titel gross", "kontext": {"auswahl": "t1"}})
    assert pult.zeitlimits[-1] is None


def test_chat_kontext_ist_optional(angemeldet, pult):
    assert _post(angemeldet, "chat", {"nachricht": "Hallo"}).status_code == 200
    assert pult.aufrufe[-1][2] == {"nachricht": "Hallo", "kontext": {}}


def test_chat_stand_json(angemeldet, pult):
    r = angemeldet.get(f"/marketing/editor/{IID}/chat.json", headers=HOST)
    assert r.status_code == 200
    # live und vorgemerkt kommen unveraendert durch.
    assert r.json() == {
        "laeuft": True, "verlauf": [{"id": "c1"}],
        "live": {"schritt": "Titel", "schritt_nr": 2, "zwischenstand": {"b1": {"t": "x"}}, "stopp": None},
        "vorgemerkt": {"id": "v1", "nachricht": "Danach den Fuss"}}
    assert r.headers["cache-control"] == "no-store"
    assert pult.aufrufe[-1] == ("GET", f"/inhalte/{IID}/chat", None)


def test_chat_stand_json_pult_weg(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "intern")
    r = angemeldet.get(f"/marketing/editor/{IID}/chat.json", headers=HOST)
    assert r.status_code == 503 and r.json() == {"grund": "Assistent gerade nicht erreichbar"}


def test_chat_stand_json_ohne_anmeldung_gesperrt(pult, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    r = TestClient(ui.app).get(f"/marketing/editor/{IID}/chat.json", headers=HOST, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login" and not pult.aufrufe


def test_rueckgaengig_durchreichen(angemeldet, pult):
    r = _post(angemeldet, "chat/rueckgaengig", {"auftrag": "c1"})
    assert r.status_code == 200 and r.json() == {"fassung": 4}
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/chat/rueckgaengig", {"auftrag": "c1"})


def test_export_vorschau_durchreichen(angemeldet, pult):
    r = _post(angemeldet, "export/vorschau", {"flaechen": ["kopf"]})
    assert r.status_code == 200
    # Entwurfsbild-Adressen bleiben unveraendert (der Editor macht zurAnzeige).
    assert r.json()["flaechen"]["kopf"]["handy"] == "medien:gs-0123456789ab.jpg"
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/export/vorschau", {"flaechen": ["kopf"]})
    assert pult.zeitlimits[-1] == ui_editor.GESTALTUNG_ZEITLIMIT_S


def test_export_durchreichen(angemeldet, pult):
    r = _post(angemeldet, "export", {"newsletter": True, "flaechen": ["kopf"], "bestaetigt": True})
    assert r.status_code == 200 and r.json() == {"dateien": ["oktober-handy.jpg"], "auftrag": "e1"}
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/export",
                                {"newsletter": True, "flaechen": ["kopf"], "bestaetigt": True})
    assert pult.zeitlimits[-1] == ui_editor.GESTALTUNG_ZEITLIMIT_S


@pytest.mark.parametrize("ende,body", [
    ("chat", {"nachricht": "x"}),
    ("chat/rueckgaengig", {"auftrag": "c1"}),
    ("export/vorschau", {"flaechen": []}),
    ("export", {"newsletter": True, "flaechen": [], "bestaetigt": True}),
])
def test_chat_und_export_ohne_csrf(angemeldet, pult, ende, body):
    assert _post(angemeldet, ende, body, csrf=False).status_code == 403
    assert not _posts(pult)


@pytest.mark.parametrize("nachricht", ["", "   ", None, 5, "x" * 2001])
def test_chat_nachricht_ungueltig(angemeldet, pult, nachricht):
    r = _post(angemeldet, "chat", {"nachricht": nachricht})
    assert r.status_code == 422 and r.json()["grund"]
    assert not _posts(pult)


def test_chat_nachricht_2000_geht(angemeldet, pult):
    assert _post(angemeldet, "chat", {"nachricht": "x" * 2000}).status_code == 200


@pytest.mark.parametrize("kontext", ["x", [1], 5, True])
def test_chat_kontext_kein_objekt(angemeldet, pult, kontext):
    r = _post(angemeldet, "chat", {"nachricht": "Hi", "kontext": kontext})
    assert r.status_code == 422 and not _posts(pult)


def test_chat_kontext_zu_gross(angemeldet, pult):
    r = _post(angemeldet, "chat", {"nachricht": "Hi", "kontext": {"k": "x" * 5000}})
    assert r.status_code == 422 and not _posts(pult)


@pytest.mark.parametrize("ende,body", [
    ("chat", [1]),
    ("chat/rueckgaengig", {}),
    ("chat/rueckgaengig", {"auftrag": 5}),
    ("export/vorschau", {}),
    ("export/vorschau", {"flaechen": "kopf"}),
    ("export/vorschau", {"flaechen": [1]}),
    ("export", {"newsletter": "ja", "flaechen": [], "bestaetigt": True}),
    ("export", {"newsletter": True, "flaechen": "kopf", "bestaetigt": True}),
])
def test_chat_und_export_formfehler(angemeldet, pult, ende, body):
    r = _post(angemeldet, ende, body)
    assert r.status_code == 422 and not _posts(pult)


@pytest.mark.parametrize("bestaetigt", [False, None, "true", 1])
def test_export_nur_mit_bestaetigung(angemeldet, pult, bestaetigt):
    r = _post(angemeldet, "export", {"newsletter": True, "flaechen": [], "bestaetigt": bestaetigt})
    assert r.status_code == 422 and r.json()["grund"] == "Export nur mit Bestätigung"
    assert not _posts(pult)
    r = _post(angemeldet, "export", {"newsletter": True, "flaechen": []})
    assert r.status_code == 422 and not _posts(pult)


@pytest.mark.parametrize("ende,body", [
    ("chat", {"nachricht": "Hi"}),
    ("chat/rueckgaengig", {"auftrag": "c1"}),
    ("export/vorschau", {"flaechen": ["kopf"]}),
    ("export", {"newsletter": False, "flaechen": ["kopf"], "bestaetigt": True}),
])
def test_chat_und_export_fehlerabbildung(angemeldet, pult, ende, body):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Assistent arbeitet gerade")
    r = _post(angemeldet, ende, body)
    assert r.status_code == 422 and r.json() == {"grund": "Der Assistent arbeitet gerade"}
    for art in ("nicht_erreichbar", "nicht_verbunden", "unbekannt"):
        pult.fehler = marketing_pult.PultFehler(art, "intern")
        r = _post(angemeldet, ende, body)
        assert r.status_code == 503 and r.json() == {"grund": "Assistent gerade nicht erreichbar"}


# --- Vormerken und Stopp durchreichen -------------------------------------------------

UUID_A = "123e4567-e89b-42d3-a456-426614174000"


def _senden(c, methode, ende, body=None, csrf=True):
    h = {**HOST, "X-CSRF": ui.CSRF_TOKEN} if csrf else HOST
    kw = {"json": body} if body is not None else {}
    return c.request(methode, f"/marketing/editor/{IID}/{ende}", headers=h, **kw)


def test_start_nennt_vormerk_und_stopp_urls(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["chat_vormerkung_url"] == f"/marketing/editor/{IID}/chat/vormerkung"
    assert start["chat_vormerkung_starten_url"] == f"/marketing/editor/{IID}/chat/vormerkung/starten"
    assert start["chat_stopp_url"] == f"/marketing/editor/{IID}/chat/stopp"


def test_vormerken_put_durchreichen(angemeldet, pult):
    r = _senden(angemeldet, "PUT", "chat/vormerkung", {"nachricht": "Danach den Fuss", "kontext": {"a": 1}})
    assert r.status_code == 200 and r.json() == {"id": "v1", "status": "wartet"}
    assert r.headers["cache-control"] == "no-store"
    assert pult.aufrufe[-1] == ("PUT", f"/inhalte/{IID}/chat/vormerkung",
                                {"nachricht": "Danach den Fuss", "kontext": {"a": 1}})


def test_vormerkung_loeschen_durchreichen(angemeldet, pult):
    r = _senden(angemeldet, "DELETE", "chat/vormerkung")
    assert r.status_code == 200 and r.json() == {"geloescht": True}
    assert pult.aufrufe[-1] == ("DELETE", f"/inhalte/{IID}/chat/vormerkung", None)


def test_vormerkung_starten_durchreichen(angemeldet, pult):
    r = _senden(angemeldet, "POST", "chat/vormerkung/starten")
    assert r.status_code == 200 and r.json() == {"auftrag": "c2"}
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/chat/vormerkung/starten", None)


@pytest.mark.parametrize("body,erwartet", [
    ({"art": "behalten"}, {"art": "behalten"}),
    ({"art": "verwerfen", "auftrag": UUID_A}, {"art": "verwerfen", "auftrag": UUID_A}),
])
def test_stopp_durchreichen(angemeldet, pult, body, erwartet):
    r = _senden(angemeldet, "POST", "chat/stopp", body)
    assert r.status_code == 200 and r.json() == {"abgeschlossen": False}
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/chat/stopp", erwartet)


@pytest.mark.parametrize("methode,ende,body", [
    ("PUT", "chat/vormerkung", {"nachricht": "x"}),
    ("DELETE", "chat/vormerkung", None),
    ("POST", "chat/vormerkung/starten", None),
    ("POST", "chat/stopp", {"art": "behalten"}),
])
def test_vormerk_und_stopp_ohne_csrf(angemeldet, pult, methode, ende, body):
    assert _senden(angemeldet, methode, ende, body, csrf=False).status_code == 403
    assert not pult.aufrufe or pult.aufrufe[-1][0] == "GET"


@pytest.mark.parametrize("nachricht", ["", "   ", None, 5, "x" * 2001])
def test_vormerken_nachricht_ungueltig(angemeldet, pult, nachricht):
    r = _senden(angemeldet, "PUT", "chat/vormerkung", {"nachricht": nachricht})
    assert r.status_code == 422 and r.json()["grund"]
    assert not [a for a in pult.aufrufe if a[0] == "PUT"]


def test_vormerken_kontext_zu_gross_oder_kein_objekt(angemeldet, pult):
    assert _senden(angemeldet, "PUT", "chat/vormerkung",
                   {"nachricht": "Hi", "kontext": {"k": "x" * 5000}}).status_code == 422
    assert _senden(angemeldet, "PUT", "chat/vormerkung", {"nachricht": "Hi", "kontext": [1]}).status_code == 422
    assert not [a for a in pult.aufrufe if a[0] == "PUT"]


@pytest.mark.parametrize("body", [
    {}, {"art": "abbrechen"}, {"art": 5}, {"art": "behalten", "auftrag": "kein-uuid"},
    {"art": "behalten", "auftrag": 5}, {"art": "behalten", "auftrag": ""},
])
def test_stopp_formfehler(angemeldet, pult, body):
    r = _senden(angemeldet, "POST", "chat/stopp", body)
    assert r.status_code == 422 and r.json()["grund"]
    assert not [a for a in pult.aufrufe if a[2] is not None and "art" in a[2]]


@pytest.mark.parametrize("methode,ende,body", [
    ("PUT", "chat/vormerkung", {"nachricht": "x"}),
    ("DELETE", "chat/vormerkung", None),
    ("POST", "chat/vormerkung/starten", None),
    ("POST", "chat/stopp", {"art": "verwerfen"}),
])
def test_vormerk_und_stopp_fehlerabbildung(angemeldet, pult, methode, ende, body):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Kein Lauf aktiv")
    r = _senden(angemeldet, methode, ende, body)
    assert r.status_code == 422 and r.json() == {"grund": "Kein Lauf aktiv"}
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "intern")
    r = _senden(angemeldet, methode, ende, body)
    assert r.status_code == 503 and r.json() == {"grund": "Assistent gerade nicht erreichbar"}


# --- Anhang hochladen (Gestaltungs-Chat) ---------------------------------

MARKETING_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(png|jpe?g|gif|webp|pdf|docx|txt|md)")


@pytest.fixture
def medienordner(tmp_path, monkeypatch):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    return tmp_path


def _anhang(c, name, inhalt=b"x" * 64, csrf=True):
    daten = {"csrf": ui.CSRF_TOKEN} if csrf else {}
    return c.post(f"/marketing/editor/{IID}/anhang", data=daten, headers=HOST,
                  files={"datei": (name, inhalt, "application/octet-stream")})


def test_start_nennt_anhang_url(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert start["anhang_url"] == f"/marketing/editor/{IID}/anhang"


def test_anhang_bild_und_pdf_landen_im_medienordner(angemeldet, medienordner):
    r = _anhang(angemeldet, "logo.png", b"P" * 10)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"name": "logo.png", "art": "bild", "groesse": 10}
    assert (medienordner / "logo.png").read_bytes() == b"P" * 10
    r = _anhang(angemeldet, "preise.pdf", b"D" * 20)
    assert r.json() == {"name": "preise.pdf", "art": "dokument", "groesse": 20}
    assert sorted(p.name for p in medienordner.iterdir()) == ["logo.png", "preise.pdf"]


def test_anhang_name_wird_auf_das_marketing_muster_normalisiert(angemeldet, medienordner):
    r = _anhang(angemeldet, "Preise 2026.PDF")
    assert r.status_code == 200
    name = r.json()["name"]
    assert name == "Preise_2026.pdf" and MARKETING_NAME.fullmatch(name)
    assert (medienordner / name).is_file()
    name = _anhang(angemeldet, "Angebot_Müller.docx").json()["name"]
    assert name == "Angebot_Mueller.docx" and MARKETING_NAME.fullmatch(name)
    assert (medienordner / name).is_file()


@pytest.mark.parametrize("roh,erwartet", [
    ("Straße Öl Ärger.JPG", "Strasse_Oel_Aerger.jpg"),
    ("..hidden file.png", "hidden_file.png"),
    ("__a  b__c.md", "a_b_c.md"),
    ("日本語.txt", "anhang.txt"),
    ("a....b---c.webp", "a.b-c.webp"),
    (r"C:\Users\x\bild.jpeg", "bild.jpeg"),
])
def test_anhang_normalisierung(angemeldet, medienordner, roh, erwartet):
    r = _anhang(angemeldet, roh)
    assert r.status_code == 200 and r.json()["name"] == erwartet
    assert MARKETING_NAME.fullmatch(erwartet) and (medienordner / erwartet).is_file()


def test_anhang_langer_name_wird_gekappt_und_passt_noch_mit_suffix(angemeldet, medienordner):
    lang = "a" * 300 + ".png"
    n1 = _anhang(angemeldet, lang).json()["name"]
    n2 = _anhang(angemeldet, lang).json()["name"]
    assert MARKETING_NAME.fullmatch(n1) and MARKETING_NAME.fullmatch(n2) and n1 != n2


def test_anhang_interner_name_wird_nicht_unsichtbar(angemeldet, medienordner):
    name = _anhang(angemeldet, "Terminkarte-x.pdf").json()["name"]
    assert MARKETING_NAME.fullmatch(name) and not server.medien.intern(name)
    assert server.medien.pruefe_anhang(name)[1] is None


def test_anhang_kollision_bekommt_suffix_alte_datei_bleibt(angemeldet, medienordner):
    (medienordner / "logo.png").write_bytes(b"ALT")
    r = _anhang(angemeldet, "logo.png", b"NEU")
    assert r.status_code == 200
    name = r.json()["name"]
    assert name == "logo-2.png" and MARKETING_NAME.fullmatch(name)
    assert (medienordner / "logo.png").read_bytes() == b"ALT"
    assert (medienordner / "logo-2.png").read_bytes() == b"NEU"
    assert _anhang(angemeldet, "logo.png", b"DRITT").json()["name"] == "logo-3.png"
    assert not list(medienordner.glob("*.teil"))


@pytest.mark.parametrize("name", ["virus.exe", "ton.mp3", "clip.mp4", "kalender.ics", "ohne", "bild.gif"])
def test_anhang_falscher_typ_ist_422(angemeldet, medienordner, name):
    r = _anhang(angemeldet, name)
    assert r.status_code == 422 and r.json()["grund"]
    assert list(medienordner.iterdir()) == []


def test_anhang_zu_gross_und_leer_ist_422(angemeldet, medienordner, monkeypatch):
    monkeypatch.setattr(server.medien, "MAX_BYTES", 1024)
    assert _anhang(angemeldet, "gross.pdf", b"z" * 4096).status_code == 422
    assert _anhang(angemeldet, "leer.pdf", b"").status_code == 422
    assert list(medienordner.iterdir()) == []


def test_anhang_ohne_datei_ist_422(angemeldet, medienordner):
    r = angemeldet.post(f"/marketing/editor/{IID}/anhang", data={"csrf": ui.CSRF_TOKEN}, headers=HOST)
    assert r.status_code == 422


def test_anhang_ohne_csrf_ist_403(angemeldet, medienordner):
    r = _anhang(angemeldet, "logo.png", csrf=False)
    assert r.status_code == 403 and r.json() == {"grund": "Fehlende oder falsche CSRF-Marke"}
    assert list(medienordner.iterdir()) == []


def test_anhang_nicht_beschreibbarer_ordner_ist_500(angemeldet, tmp_path, monkeypatch):
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path / "gibtsnicht"))
    r = _anhang(angemeldet, "logo.png")
    assert r.status_code == 500 and "nicht beschreibbar" in r.json()["grund"]


def test_neue_endungen_sind_zugelassen_und_haben_mime():
    assert server.medien.ERLAUBT[".webp"] == ("send-image", "image/webp")
    assert server.medien.ERLAUBT[".docx"] == (
        "send-document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert server.medien.ERLAUBT[".txt"] == ("send-document", "text/plain")
    assert server.medien.ERLAUBT[".md"] == ("send-document", "text/markdown")


# --- Anhang: Nebenlaeufigkeit, Bot-Sperre, Randfaelle (Fix-Runde 1) --------

class _Strom:
    """Minimaler UploadFile-Ersatz: liefert den Inhalt in Stuecken und gibt dem
    Event-Loop dazwischen die Kontrolle (so verzahnen sich zwei Uploads)."""
    def __init__(self, inhalt, stueck=4):
        self.inhalt, self.pos, self.stueck = inhalt, 0, stueck

    async def read(self, _n):
        import asyncio
        await asyncio.sleep(0)
        teil = self.inhalt[self.pos:self.pos + self.stueck]
        self.pos += self.stueck
        return teil

    async def seek(self, p):
        self.pos = p


def test_gleichzeitiges_ablegen_gleichen_namens_laesst_eine_intakte_datei(medienordner):
    import asyncio

    async def lauf():
        return await asyncio.gather(
            ui.medien_ablegen(_Strom(b"A" * 40), "bild.png", ersetzen=False),
            ui.medien_ablegen(_Strom(b"B" * 40), "bild.png", ersetzen=False))
    erg = asyncio.run(lauf())
    assert sorted(r[1][0] if r[1] else 0 for r in erg) == [0, 409]
    assert (medienordner / "bild.png").read_bytes() in (b"A" * 40, b"B" * 40)
    assert [p.name for p in medienordner.iterdir()] == ["bild.png"]


def test_gleichzeitige_anhang_uploads_gleichen_namens_zwei_intakte_dateien(angemeldet, medienordner):
    from concurrent.futures import ThreadPoolExecutor
    inhalte = [bytes([65 + i]) * 200_000 for i in range(4)]
    with ThreadPoolExecutor(4) as pool:
        antworten = list(pool.map(lambda b: _anhang(angemeldet, "image.png", b), inhalte))
    assert [a.status_code for a in antworten] == [200] * 4
    namen = [a.json()["name"] for a in antworten]
    assert len(set(namen)) == 4 and all(MARKETING_NAME.fullmatch(n) for n in namen)
    assert sorted((medienordner / n).read_bytes() for n in namen) == sorted(inhalte)
    assert sorted(p.name for p in medienordner.iterdir()) == sorted(namen)


@pytest.fixture
def meta_leer(angemeldet):
    server._q("delete from medien_meta")
    yield
    server._q("delete from medien_meta")


def test_anhang_ist_nicht_automatisch_fuer_den_bot_sendbar(angemeldet, medienordner, meta_leer):
    name = _anhang(angemeldet, "privat.txt", b"geheim").json()["name"]
    assert server.medien_meta_lesen()[name]["bot_darf_senden"] is False


def test_medien_hochladen_bleibt_fuer_den_bot_freigegeben(angemeldet, medienordner, meta_leer):
    r = angemeldet.post("/medien/hochladen", data={"csrf": ui.CSRF_TOKEN}, headers=HOST,
                        files={"datei": ("angebot.pdf", b"y" * 10, "application/pdf")},
                        follow_redirects=False)
    assert r.status_code == 303 and "angebot.pdf" not in server.medien_meta_lesen()


def test_anhang_meta_fehler_laesst_keine_sendbare_datei_zurueck(angemeldet, medienordner, monkeypatch):
    def kaputt(*a, **k):
        raise RuntimeError("db weg")
    monkeypatch.setattr(server, "medien_meta_setzen", kaputt)
    r = _anhang(angemeldet, "privat.txt", b"geheim")
    assert r.status_code == 503 and list(medienordner.iterdir()) == []


def test_ablegen_faellt_ohne_hardlink_auf_exklusives_anlegen_zurueck(medienordner, monkeypatch):
    import asyncio

    def kein_link(*a, **k):
        raise PermissionError("kein Hardlink")
    monkeypatch.setattr(os, "link", kein_link)
    assert asyncio.run(ui.medien_ablegen(_Strom(b"NEU1"), "x.png", ersetzen=False))[1] is None
    assert (medienordner / "x.png").read_bytes() == b"NEU1"
    erg = asyncio.run(ui.medien_ablegen(_Strom(b"NEU2"), "x.png", ersetzen=False))
    assert erg[1][0] == 409 and (medienordner / "x.png").read_bytes() == b"NEU1"
    assert [p.name for p in medienordner.iterdir()] == ["x.png"]


def test_anhang_kollisionssuffix_ergibt_keinen_internen_namen(angemeldet, medienordner):
    (medienordner / "terminkarte.pdf").write_bytes(b"ALT")
    name = _anhang(angemeldet, "terminkarte.pdf").json()["name"]
    assert name == "anhang-terminkarte-2.pdf"
    assert not server.medien.intern(name) and MARKETING_NAME.fullmatch(name)


def test_anhang_nur_endung_und_doppelendung(angemeldet, medienordner):
    assert _anhang(angemeldet, ".pdf").json()["name"] == "anhang.pdf"
    assert _anhang(angemeldet, "x.pdf.exe").status_code == 422
    assert [p.name for p in medienordner.iterdir()] == ["anhang.pdf"]


def test_anhang_praefix_und_suffix_zusammen(angemeldet, medienordner):
    a = _anhang(angemeldet, "Terminkarte-x.pdf").json()["name"]
    b = _anhang(angemeldet, "Terminkarte-x.pdf").json()["name"]
    assert (a, b) == ("anhang-Terminkarte-x.pdf", "anhang-Terminkarte-x-2.pdf")
    assert not server.medien.intern(a) and not server.medien.intern(b)
