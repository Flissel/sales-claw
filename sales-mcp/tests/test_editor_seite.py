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
        self.betreff = "Oktober-Ausgabe"
        self.format = "bloecke"
        self.art = "newsletter"
        self.status = "entwurf"
        self.alter_weg = None
        self.alt_format = "felder"          # Format der aelteren Fassung 1
        self.speichern_antwort = {"fassung": 3}
        self.bilder = {"auftraege": []}

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
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
    assert offen == [("GET", "/marketing/bild/{token}/{name}", 404)]


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


def test_stand_json(angemeldet, pult):
    pult.bilder = {"auftraege": [{"platz": "kopf", "status": "in_arbeit"}]}
    j = angemeldet.get(f"/marketing/editor/{IID}/stand.json", headers=HOST).json()
    assert j["fassung"] == 2 and j["auftraege"][0]["status"] == "in_arbeit"
