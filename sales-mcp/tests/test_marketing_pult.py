"""Marketing-Pult in sales-ui (Spec 2026-09-29-marketing-pult-design.md §3.1,
Stufe 1). Der Client zur Marketing-API wird gefaelscht."""
import asyncio
import json
import os
import urllib.request

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_marketing  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
IID = "11111111-1111-1111-1111-111111111111"
FELDER = {"betreff": "Early Access", "vorschautext": "", "abschnitte": [{"titel": "", "text": "Hallo"}],
          "knopf_text": "", "knopf_link": ""}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


GESTALT = {"grund": "#0f2422", "text": "#cfe3df", "akzent": "#5eead4", "flaeche": "#1d3b39",
           "text_hell": "#e9fbf6", "text_leise": "#8aa3a0", "gold": "#fbbf24",
           "handlung_text": "#0f2422", "rundung": 8, "schrift": "system", "abstand": "mittel"}
LOGO_ALT = "data:image/png;base64,iVBORw0KGgo="
BLOECKE_MIT_PLATZ = {
    "root": {"type": "EmailLayout", "data": {"childrenIds": ["kopf"]}},
    "kopf": {"type": "Image", "data": {"props": {"url": "medien:platzhalter-2x1.png", "width": 600,
                                                   "height": 300, "alt": "Team"}}}}


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.fehler_pfad = None      # gesetzt: nur Aufrufe mit diesem Pfad-Ende scheitern
        self.im_loop = []            # Pfade, die IM Event-Loop-Thread liefen (blockieren sales-ui)
        self.alter_weg = None        # I3: Status im alten Freigabeweg
        self.layout = "dunkel"       # Layout der Fassungen
        self.bloecke = None          # gesetzt: neueste Fassung ist eine Editor-Fassung
        self.bilder = {"auftraege": []}
        self.inhalt_mandant = "vibemind"   # Firma des Inhalts (Entwurfsseite)
        self.status = "entwurf"            # Status des Inhalts (entwurf|eingereicht|freigegeben|abgelehnt)
        self.rueckmeldungen = []           # neueste zuerst: {text, von, am, fassung, erledigt}
        self.extra = {}                    # weitere Felder am Inhalt (freigegebene_fassung, ...)
        self.inhalte = None                # gesetzt: Zeilen der Entwurfsliste

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
        try:
            asyncio.get_running_loop()
            self.im_loop.append(pfad)
        except RuntimeError:
            pass                     # Threadpool: kein laufender Loop in diesem Thread
        if self.fehler and (self.fehler_pfad is None or pfad.endswith(self.fehler_pfad)):
            raise self.fehler
        if pfad == "/layouts/vorschau" and roh:
            return (b"<p>Beispiel</p>", "text/html")
        if roh:
            if "format=pdf" in pfad:
                return (b"%PDF-1.4 falsch", "application/pdf")
            return (b"<!doctype html><p>Vorschau</p>", "text/html")
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True},
                                  {"id": "alt", "name": "Alt", "aktiv": False}]}
        if pfad.startswith("/uebersicht"):
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": False}],
                    "zaehler": {"entwurf": 7, "zurueckgegeben": 1, "eingereicht": 2, "freigegeben": 0,
                                "abgelehnt": 0}}
        if pfad.startswith("/inhalte?"):
            if self.inhalte is not None:
                return {"inhalte": self.inhalte}
            return {"inhalte": [{"id": IID, "art": "newsletter", "titel": "Early Access",
                                 "status": "entwurf", "erstellt_am": "2026-09-04", "fassungen": 2,
                                 "layout": "dunkel"}]}
        if pfad == f"/inhalte/{IID}/bilder":
            return {"auftrag": "a1"} if methode == "POST" else self.bilder
        if pfad == f"/inhalte/{IID}":
            neu_extra = {"format": "bloecke", "bloecke": self.bloecke} if self.bloecke else {}
            return {"inhalt": {"id": IID, "art": "newsletter", "titel": "Early Access",
                               "status": self.status, "mandant": self.inhalt_mandant,
                               "freigegebene_fassung": None, "entschieden_von": None,
                               "entschieden_am": None, "grund": None, "eingereichte_fassung": None,
                               "eingereicht_am": None, "eingereicht_von": None, **self.extra},
                    "fassungen": [{"fassung": 2, "felder": FELDER, "layout": self.layout,
                                   "urheber": "betreiber", "erstellt_am": "x", **neu_extra},
                                  {"fassung": 1, "felder": FELDER, "layout": self.layout,
                                   "urheber": "agent", "erstellt_am": "y"}],
                    "alter_weg": self.alter_weg, "rueckmeldungen": self.rueckmeldungen}
        if pfad.startswith("/layouts?mandant="):
            return {"layouts": [
                {"name": "dunkel", "beschreibung": "Dunkel mit Tuerkis", "inhaltsart": "newsletter",
                 "fassung": 2, "standard": False, "status": "aktiv",
                 "gestalt": {**GESTALT, "logo": LOGO_ALT}},
                {"name": "hell", "beschreibung": "Hell", "inhaltsart": "newsletter",
                 "fassung": 1, "standard": True, "status": "aktiv",
                 "gestalt": {**GESTALT, "grund": "#ffffff", "text": "#111111"}},
                {"name": "karte", "beschreibung": "Post-Karte", "inhaltsart": "post",
                 "fassung": 1, "standard": True, "status": "aktiv", "gestalt": GESTALT}]}
        if pfad.endswith("/fassungen"):
            return {"fassung": 3}
        if pfad.endswith("/entscheiden"):
            return {"status": "freigegeben"}
        return {}


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    return f


def test_menue_nur_fuer_freigeben_im_basis_laden(monkeypatch):
    for rolle, sichtbar in (("freigeben", True), ("lesen", False), ("kalender", False), ("", False)):
        t = ui._AKTIVE_ROLLE.set(rolle)
        try:
            assert ('href="/marketing"' in ui._seitenleiste("")) is sichtbar, rolle
        finally:
            ui._AKTIVE_ROLLE.reset(t)
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/marketing/entwuerfe") is False


def test_schalter_ist_weg():
    assert not hasattr(ui, "_marketing_link")
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert 'class="schalter"' not in ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)


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


def test_uebersicht(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    assert "VibeMind" in s and "fin2gether" in s
    assert "in Arbeit" in s and ">7<" in s and "zur Freigabe" in s and ">2<" in s


def test_entwuerfe_liste(angemeldet):
    s = angemeldet.get("/marketing/entwuerfe", headers=HOST).text
    assert "Early Access" in s and f'href="/marketing/entwurf/{IID}"' in s and "Newsletter" in s


def test_entwurf_zeigt_felder_und_vorschau(angemeldet):
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    s = r.text
    assert 'name="betreff"' in s and "Early Access" in s
    assert f'src="/marketing/entwurf/{IID}/vorschau?fassung=2&amp;format=mail"' in s
    assert "Fassung 2" in s and "Fassung 1" in s
    assert 'value="dunkel"' in s and 'value="hell"' in s
    # Die Seiten-CSP laesst genau den eigenen Rahmen zu, sonst bliebe die
    # Vorschau im Browser leer; Skripte gibt es in sales-ui nicht.
    assert "frame-src 'self'" in r.headers["content-security-policy"]
    assert "<script" not in s
    # Verwerfen nennt die gesehene Fassung.
    assert '<input type="hidden" name="fassung" value="2">' in s
    assert "nicht die neueste Fassung" not in s


def test_aeltere_fassung_nur_ansehen(angemeldet):
    s = angemeldet.get(f"/marketing/entwurf/{IID}?fassung=1", headers=HOST).text
    assert "Das ist nicht die neueste Fassung" in s
    assert f'src="/marketing/entwurf/{IID}/vorschau?fassung=1&amp;format=mail"' in s
    assert 'value="freigeben"' not in s and "/entscheiden" not in s
    assert "/einreichen" not in s                              # einreichen nimmt die neueste Fassung
    assert "/speichern" in s                                   # speichern bleibt erlaubt


def test_vorschau_wird_durchgereicht_mit_sandbox(angemeldet):
    r = angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    assert r.status_code == 200 and b"Vorschau" in r.content
    csp = r.headers.get("content-security-policy", "")
    assert "sandbox" in csp and "frame-ancestors 'self'" in csp
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_vorschau_pdf_mit_datei_richtlinie(angemeldet):
    r = angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=pdf", headers=HOST)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-security-policy"] == ui._CSP_DATEI


def test_speichern_legt_fassung_an(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "betreff": "Neu", "vorschautext": "",
                              "abschnitt_titel": ["", "Zwei"], "abschnitt_text": ["Eins", "Text zwei"],
                              "knopf_text": "", "knopf_link": "", "layout": "hell"})
    assert r.status_code == 303
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", f"/inhalte/{IID}/fassungen")
    assert d["felder"]["betreff"] == "Neu" and d["layout"] == "hell"
    assert d["felder"]["abschnitte"] == [{"titel": "", "text": "Eins"}, {"titel": "Zwei", "text": "Text zwei"}]
    assert d["von"] == "mira"


def test_speichern_ohne_csrf_abgewiesen(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST,
                        data={"betreff": "x"})
    assert r.status_code == 403 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_freigeben_geht_hier_nicht_mehr(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/entscheiden", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "fassung": "2", "urteil": "freigeben", "grund": ""})
    assert r.status_code == 422 and "Freigeben geht über die Freigaben" in r.text
    assert 'href="/freigaben#marketing"' in r.text
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_entscheiden_ohne_fassung_abgewiesen(angemeldet, pult):
    for fassung in (None, "", "abc", "0"):
        daten = {"csrf": ui.CSRF_TOKEN, "urteil": "ablehnen", "grund": "weg"}
        if fassung is not None:
            daten["fassung"] = fassung
        r = angemeldet.post(f"/marketing/entwurf/{IID}/entscheiden", headers=HOST,
                            follow_redirects=False, data=daten)
        assert r.status_code == 400, fassung
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_marketing_nicht_erreichbar(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "timeout")
    r = angemeldet.get("/marketing/entwuerfe", headers=HOST)
    assert r.status_code == 503 and "Marketing gerade nicht erreichbar" in r.text
    assert 'href="/kontakte"' in r.text                       # Rest von Sales bleibt bedienbar


def test_schluessel_falsch(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_verbunden", "401")
    assert "Marketing nicht verbunden" in angemeldet.get("/marketing", headers=HOST).text


def test_db_ablehnung_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Nur Entwuerfe lassen sich bearbeiten")
    r = angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "betreff": "x", "abschnitt_titel": [""],
                              "abschnitt_text": ["y"], "layout": "dunkel"})
    assert r.status_code == 422 and "Nur Entwuerfe lassen sich bearbeiten" in r.text
    assert "Nicht möglich" in r.text                          # M5: echte Umlaute


# --- Task 5: Layout-Galerie und Layout-Editor --------------------------------

def _regler(**mehr):
    return {"csrf": ui.CSRF_TOKEN, **{k: str(v) for k, v in GESTALT.items()}, **mehr}


def test_galerie_zeigt_alle_layouts_mit_vorschau(angemeldet):
    r = angemeldet.get("/marketing/layouts", headers=HOST)
    s = r.text
    assert r.status_code == 200
    assert "dunkel" in s and "hell" in s and "karte" in s and "Standard" in s
    assert s.count('<iframe class="layout-bild"') == 3
    assert 'src="/marketing/layout-bild/dunkel"' in s
    assert 'href="/marketing/layout/dunkel"' in s
    # nach Inhaltsart gruppiert, Standard zuerst
    assert s.index("<h2>Newsletter</h2>") < s.index("/layout-bild/hell") < s.index("/layout-bild/dunkel")
    assert s.index("/layout-bild/dunkel") < s.index("<h2>Post</h2>") < s.index("/layout-bild/karte")
    assert "frame-src 'self'" in r.headers["content-security-policy"]
    assert "<script" not in s


def test_layout_bild_mit_sandbox(angemeldet, pult):
    r = angemeldet.get("/marketing/layout-bild/dunkel", headers=HOST)
    assert r.status_code == 200 and b"Beispiel" in r.content
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox") and "frame-ancestors 'self'" in csp
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", "/layouts/vorschau") and d["gestalt"]["grund"] == "#0f2422"
    assert d["format"] == "mail"


def test_layout_bild_unbekannt(angemeldet):
    r = angemeldet.get("/marketing/layout-bild/gibtsnicht", headers=HOST)
    assert r.status_code == 404
    assert "sandbox" in r.headers["content-security-policy"]


def test_editor_hat_alle_regler(angemeldet):
    r = angemeldet.get("/marketing/layout/dunkel", headers=HOST)
    s = r.text
    for feld in ("grund", "text", "akzent", "flaeche", "text_hell", "text_leise", "gold",
                 "handlung_text", "schrift", "abstand", "rundung", "kopf_text", "fuss_text", "logo",
                 "logo_entfernen", "format"):
        assert f'name="{feld}"' in s, feld
    assert 'value="#0f2422"' in s and 'type="range"' in s and 'type="color"' in s
    assert 'id="regler"' in s and 'enctype="multipart/form-data"' in s
    assert 'action="/marketing/layout/dunkel/speichern"' in s
    assert 'action="/marketing/layout/dunkel/standard"' in s
    assert "Das Logo erscheint in der Vorschau nach dem Speichern" in s
    assert "frame-src 'self'" in r.headers["content-security-policy"]


def test_editor_ohne_skript_mit_vorschau_knopf(angemeldet):
    s = angemeldet.get("/marketing/layout/dunkel", headers=HOST).text
    assert "<script" not in s
    knopf = s[s.index("Vorschau aktualisieren") - 400:s.index("Vorschau aktualisieren")]
    assert 'formaction="/marketing/layout-vorschau"' in knopf
    assert 'formtarget="vorschau"' in knopf and 'formmethod="post"' in knopf
    assert 'formenctype="multipart/form-data"' in knopf
    assert '<iframe class="vorschau" name="vorschau" sandbox' in s
    assert 'src="/marketing/layout-bild/dunkel"' in s
    assert 'name="format" value="mail" checked' in s


def test_editor_unbekannt(angemeldet):
    assert angemeldet.get("/marketing/layout/gibtsnicht", headers=HOST).status_code == 404


def test_speichern_schickt_gestalt(angemeldet, pult):
    daten = {"csrf": ui.CSRF_TOKEN, **{k: v for k, v in GESTALT.items() if k != "rundung"},
             "rundung": "4", "kopf_text": "Hallo", "fuss_text": "", "format": "handy"}
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=daten,
                        follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layout/dunkel"
    m, p, d = pult.aufrufe[-1]
    assert (m, p) == ("POST", "/layouts/dunkel/fassungen")
    assert d["gestalt"]["rundung"] == 4 and d["gestalt"]["kopf_text"] == "Hallo"
    assert "fuss_text" not in d["gestalt"]          # leer = nicht gesetzt
    assert "format" not in d["gestalt"]
    assert d["gestalt"]["logo"] == LOGO_ALT         # ohne neue Datei bleibt das alte Logo
    assert d["von"] == "mira"


def test_speichern_logo_entfernen(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data=_regler(logo_entfernen="1"), follow_redirects=False)
    assert r.status_code == 303 and "logo" not in pult.aufrufe[-1][2]["gestalt"]


def test_speichern_neues_logo(angemeldet, pult):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=_regler(),
                        files={"logo": ("logo.png", png, "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    assert pult.aufrufe[-1][2]["gestalt"]["logo"].startswith("data:image/png;base64,iVBORw0KGgo")


def test_speichern_ohne_csrf_kein_api_aufruf(angemeldet, pult):
    daten = _regler()
    del daten["csrf"]
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=daten)
    assert r.status_code == 403 and pult.aufrufe == []


def test_live_vorschau(angemeldet, pult):
    r = angemeldet.post("/marketing/layout-vorschau", headers=HOST,
                        data=_regler(format="handy", layout="dunkel"))
    assert r.status_code == 200 and b"Beispiel" in r.content
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox") and "frame-ancestors 'self'" in csp
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    m, p, d = pult.aufrufe[-1]
    assert p == "/layouts/vorschau" and d["format"] == "handy"
    assert d["gestalt"]["logo"] == LOGO_ALT          # gespeichertes Logo, nicht hochgeladen
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)   # nichts gespeichert


def test_live_vorschau_ignoriert_hochgeladenes_logo(angemeldet, pult):
    r = angemeldet.post("/marketing/layout-vorschau", headers=HOST, data=_regler(layout="dunkel"),
                        files={"logo": ("x.gif", b"GIF89a....", "image/gif")})
    assert r.status_code == 200 and pult.aufrufe[-1][2]["gestalt"]["logo"] == LOGO_ALT
    assert pult.aufrufe[-1][2]["format"] == "mail"


def test_live_vorschau_fehler_bleibt_im_rahmen(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "rundung muss eine Zahl von 0 bis 24 sein")
    pult.fehler_pfad = "/layouts/vorschau"
    r = angemeldet.post("/marketing/layout-vorschau", headers=HOST,
                        data=_regler(rundung="999", layout="dunkel"))
    assert r.status_code == 422 and "rundung muss eine Zahl" in r.text
    # Die Fehlermeldung landet im Rahmen - ohne SAMEORIGIN bliebe er leer.
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_live_vorschau_ohne_csrf(angemeldet, pult):
    daten = _regler()
    del daten["csrf"]
    r = angemeldet.post("/marketing/layout-vorschau", headers=HOST, data=daten)
    assert r.status_code == 403 and pult.aufrufe == []


def test_ungueltiger_regler_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "rundung muss eine Zahl von 0 bis 24 sein")
    pult.fehler_pfad = "/fassungen"
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data=_regler(rundung="999"))
    assert r.status_code == 422 and "rundung muss eine Zahl" in r.text


def test_rundung_keine_zahl_ohne_api(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST,
                        data=_regler(rundung="viel"))
    assert r.status_code == 422 and "Rundung muss eine Zahl" in r.text
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)


def test_zu_grosses_logo_abgewiesen_ohne_api(angemeldet, pult):
    gross = b"\x89PNG\r\n\x1a\n" + b"0" * 160_000
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=_regler(),
                        files={"logo": ("logo.png", gross, "image/png")})
    assert r.status_code == 422 and "150 KB" in r.text
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)


def test_riesiges_logo_wird_nicht_ganz_gelesen(angemeldet, pult, monkeypatch):
    """Ein 2-MB-Upload wird stueckweise gelesen und frueh abgebrochen - kein
    read() ohne Groesse, und kaum mehr als die Grenze landet im Speicher."""
    from starlette.datastructures import UploadFile
    gelesen, groessen = [], []
    original = UploadFile.read

    async def spion(self, size=-1):
        groessen.append(size)
        daten = await original(self, size)
        gelesen.append(len(daten))
        return daten

    monkeypatch.setattr(UploadFile, "read", spion)
    riesig = b"\x89PNG\r\n\x1a\n" + b"0" * 2_000_000
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=_regler(),
                        files={"logo": ("logo.png", riesig, "image/png")})
    assert r.status_code == 422 and "Das Logo ist größer als 150 KB." in r.text
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)
    assert groessen and all(g is not None and g > 0 for g in groessen), groessen
    assert sum(gelesen) <= ui_marketing.LOGO_MAX + ui_marketing.LOGO_STUECK


def test_logo_falscher_typ_abgewiesen(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/dunkel/speichern", headers=HOST, data=_regler(),
                        files={"logo": ("logo.png", b"GIF89a....", "image/png")})
    assert r.status_code == 422 and "PNG oder JPEG" in r.text
    assert not any(a[1].endswith("/fassungen") for a in pult.aufrufe)


def test_als_standard(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/hell/standard", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and pult.aufrufe[-1][:2] == ("POST", "/layouts/hell/standard")
    assert r.headers["location"] == "/marketing/layouts"


def test_als_standard_ohne_csrf(angemeldet, pult):
    r = angemeldet.post("/marketing/layout/hell/standard", headers=HOST, data={})
    assert r.status_code == 403 and pult.aufrufe == []


# --- Final-Review Fix-Welle (final-fix-findings.md) -------------------------

def test_i1_kein_api_aufruf_im_event_loop(angemeldet, pult):
    """sales-ui ist EIN uvicorn-Prozess: ein blockierender API-Aufruf im
    Event-Loop friert jede andere Seite ein. Alle Pult-Aufrufe muessen im
    Threadpool laufen (wie die Layout-Seiten)."""
    angemeldet.get("/marketing", headers=HOST)
    angemeldet.get("/marketing/entwuerfe", headers=HOST)
    angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    angemeldet.get(f"/marketing/entwurf/{IID}/vorschau?fassung=2&format=mail", headers=HOST)
    angemeldet.post(f"/marketing/entwurf/{IID}/speichern", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "betreff": "x", "abschnitt_titel": [""],
                          "abschnitt_text": ["y"], "layout": "dunkel"})
    angemeldet.post(f"/marketing/entwurf/{IID}/entscheiden", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "2", "urteil": "ablehnen", "grund": "weg"})
    pfade = [a[1] for a in pult.aufrufe]
    for teil in ("/uebersicht", "/inhalte?", f"/inhalte/{IID}", "/layouts?", "/vorschau?",
                 "/fassungen", "/entscheiden"):
        assert any(teil in p for p in pfade), teil
    assert pult.im_loop == []


ALTER_WEG_TEXT = "Dieser Entwurf liegt noch im alten Freigabeweg"


def test_i3_warnung_alter_weg_offen(angemeldet, pult):
    for status in ("pending_approval", "draft"):
        pult.alter_weg = {"status": status, "kanal": "linkedin"}
        s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
        assert (f"{ALTER_WEG_TEXT} (linkedin). Ablehnen hier stoppt ihn dort nicht, und Änderungen "
                "hier werden dort nicht verschickt. Im alten Weg ablehnen, falls er nicht rausgehen soll.") in s
        assert s.index(ALTER_WEG_TEXT) < s.index('value="ablehnen"')     # ueber den Aktionen


def test_i3_keine_warnung_ohne_oder_mit_erledigtem_alten_weg(angemeldet, pult):
    for alter_weg in (None, {"status": "rejected", "kanal": "linkedin"}):
        pult.alter_weg = alter_weg
        s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
        assert ALTER_WEG_TEXT not in s, alter_weg


def test_i3_kanal_wird_escaped(angemeldet, pult):
    pult.alter_weg = {"status": "pending_approval", "kanal": "<b>x</b>"}
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert "(&lt;b&gt;x&lt;/b&gt;)" in s and "<b>x</b>" not in s


class _Antwort:
    def __init__(self, inhalt):
        self.inhalt = inhalt
        self.headers = {"Content-Type": "text/html"}

    def read(self):
        return self.inhalt

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def client_echt(monkeypatch):
    """Der echte marketing_pult.anfrage, nur urlopen gefaelscht."""
    gesehen = []
    inhalt = [b"{}"]

    def urlopen(req, timeout=None):
        gesehen.append(req)
        return _Antwort(inhalt[0])

    monkeypatch.setattr(marketing_pult, "URL", "http://pult.test")
    monkeypatch.setattr(marketing_pult, "KEY", "geheim-123")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return gesehen, inhalt


def test_m1_200_ohne_json_ist_pultfehler(client_echt):
    _, inhalt = client_echt
    inhalt[0] = b"<html>Proxy-Seite</html>"
    with pytest.raises(marketing_pult.PultFehler) as f:
        marketing_pult.anfrage("GET", "/uebersicht")
    assert f.value.art == "unbekannt"


def test_m2_schluessel_folgt_keiner_umleitung(client_echt):
    gesehen, inhalt = client_echt
    inhalt[0] = json.dumps({"ok": True}).encode()
    assert marketing_pult.anfrage("POST", "/x", {"a": 1}) == {"ok": True}
    req = gesehen[0]
    assert req.unredirected_hdrs.get("X-pult-key") == "geheim-123"
    assert "X-pult-key" not in req.headers                    # urllib gibt headers bei 30x weiter
    assert req.headers.get("Content-type") == "application/json"


def test_m3_standard_filter_zur_freigabe(angemeldet, pult):
    s = angemeldet.get("/marketing/entwuerfe", headers=HOST).text
    assert "status=entwurf" in pult.aufrufe[-1][1]
    assert 'class="aktiv" href="/marketing/entwuerfe?status=entwurf"' in s


def test_m3_alle_zeigt_alles(angemeldet, pult):
    angemeldet.get("/marketing/entwuerfe?status=alle", headers=HOST)
    assert "status=" not in pult.aufrufe[-1][1]


def test_m3_filter_behalten_die_andere_achse(angemeldet, pult):
    s = angemeldet.get("/marketing/entwuerfe?art=post&status=abgelehnt", headers=HOST).text
    p = pult.aufrufe[-1][1]
    assert "art=post" in p and "status=abgelehnt" in p
    # Art-Verweise behalten den Status ...
    assert 'href="/marketing/entwuerfe?art=newsletter&amp;status=abgelehnt"' in s
    assert 'href="/marketing/entwuerfe?status=abgelehnt"' in s              # Art "Alle"
    # ... Status-Verweise behalten die Art.
    assert 'href="/marketing/entwuerfe?art=post&amp;status=freigegeben"' in s
    assert 'href="/marketing/entwuerfe?art=post&amp;status=alle"' in s


def test_m4_aktuelles_layout_vorgewaehlt(angemeldet, pult):
    pult.layout = "hell"
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert '<option value="hell" selected>' in s and s.count(" selected>") == 1


def test_m4_layout_nicht_mehr_in_der_liste(angemeldet, pult):
    pult.layout = "altmodisch"
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert '<option value="altmodisch" selected>altmodisch (nicht mehr in der Liste)</option>' in s
    assert s.count(" selected>") == 1


def test_m5_umlaute(angemeldet, pult, monkeypatch):
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert 'placeholder="Überschrift"' in s
    monkeypatch.setattr(marketing_pult, "anfrage", lambda methode, pfad, *a, **k: (
        {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True}]} if pfad == "/mandanten"
        else {"inhalte": []}))
    assert "Keine Entwürfe." in angemeldet.get("/marketing/entwuerfe", headers=HOST).text


# --- Browser-Durchlauf 29.09.2026 (Aufgabe 0b): Vorschau nur 140 px hoch ------
# Gemessen: .pult-rechts iframe.vorschau {height:80vh} galt, aber die spaetere
# Medienlisten-Regel `.vorschau { max-height: 140px }` traf denselben Rahmen.

import re as _re  # noqa: E402

_REGEL = _re.compile(r"([^{}]+)\{([^{}]*)\}")


def test_entwurf_rahmen_traegt_klasse_vorschau(angemeldet):
    s = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert '<iframe class="vorschau mail" sandbox' in s


def test_keine_spaetere_regel_begrenzt_die_vorschau_hoehe():
    css = ui._STIL
    start = css.index(".pult-rechts iframe.vorschau {")
    basis = css[start:css.index("}", start)]
    assert "height: min(80vh, 1100px)" in basis and "max-height: none" in basis
    for sel, koerper in _REGEL.findall(css[css.index("}", start) + 1:]):
        if not _re.search(r"(^|[;\s])(max-|min-)?height\s*:", koerper):
            continue
        for s in (t.strip() for t in sel.split(",")):
            s = s.split("{")[-1].strip()
            if s.startswith(".pult-rechts iframe.vorschau"):
                continue            # die eigenen (Handy-)Regeln
            letzter = s.split()[-1] if s else ""
            trifft = letzter in (".vorschau", "iframe", "iframe.vorschau", "*") or \
                (letzter.startswith((".vorschau", "iframe.vorschau", "iframe")) and
                 not letzter.startswith(("iframe.layout-bild", "iframe.dashboard")))
            assert not trifft, f"spaetere Regel '{s}' setzt eine Hoehe auf den Vorschau-Rahmen"


def test_handy_vorschau_mindestens_70vh():
    css = ui._STIL
    treffer = [m for m in _re.finditer(r"@media \(max-width: 767px\) \{\s*"
                                       r"\.pult-rechts iframe\.vorschau \{([^}]*)\}", css)]
    assert treffer and "min-height: 70vh" in treffer[0].group(1)

def test_entwurf_zeigt_bildstand_und_formular(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.bilder = {"auftraege": [
        {"platz": None, "nur_leere": True, "status": "offen", "befund": "", "hinweis": "", "geaendert_am": "2026-09-29 10:00"},
        {"platz": "kopf", "nur_leere": False, "status": "fehler", "befund": "Schrift im Bild", "hinweis": "", "geaendert_am": "2026-09-29 09:00"}]}
    seite = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert "Bilder" in seite and "wartet (PC muss laufen)" in seite and "Schrift im Bild" in seite
    assert f'action="/marketing/entwurf/{IID}/bilder"' in seite and '<option value="kopf">' in seite
    assert '<option value="">alle Bildplätze (auch belegte)</option>' in seite
    assert '<option value="__leere__">nur leere Bildplätze</option>' in seite
    assert "<script" not in seite


def test_entwurf_bildstand_fehler_laesst_seite_stehen(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    pult.fehler_pfad = "/bilder"
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    assert r.status_code == 200 and "Bildstand gerade nicht abrufbar" in r.text


def test_entwurf_bilder_formular(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/bilder", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "platz": "", "hinweis": "mehr Menschen"},
                        follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/entwurf/{IID}"
    assert pult.aufrufe[-1][2] == {"platz": None, "hinweis": "mehr Menschen", "nur_leere": False,
                                   "staerke": 55, "modus": "ueberarbeiten"}


def test_entwurf_bilder_formular_nur_leere(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/bilder", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "platz": "__leere__", "hinweis": ""},
                        follow_redirects=False)
    assert r.status_code == 303
    assert pult.aufrufe[-1][2] == {"platz": None, "hinweis": "", "nur_leere": True,
                                   "staerke": 55, "modus": "ueberarbeiten"}


def test_entwurf_laedt_neu_solange_auftraege_offen(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.bilder = {"auftraege": [
        {"platz": "kopf", "status": "in_arbeit", "modus": "ueberarbeiten", "staerke": 40, "messung": {}}]}
    seite = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert '<meta http-equiv="refresh" content="20">' in seite and "wird überarbeitet" in seite


def test_entwurf_ohne_offene_auftraege_kein_neuladen_mit_messung(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.bilder = {"auftraege": [
        {"platz": "kopf", "status": "fertig", "modus": "ueberarbeiten", "staerke": 55,
         "messung": {"kopf": {"aehnlich_original": 0.823, "naeher_am_hinweis": 0.04}}}]}
    seite = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text
    assert 'http-equiv="refresh"' not in seite and "kopf: 82 % Themen-Ähnlichkeit" in seite
    assert '<select name="staerke">' in seite and 'name="neu"' not in seite
    assert '<option value="35" selected>nah am Original</option>' in seite
    assert '<option value="75">freier</option>' in seite and '<option value="100">ganz neu</option>' in seite


def test_entwurf_messung_nan_inf_stuerzt_nicht_ab(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.bilder = {"auftraege": [
        {"platz": "kopf", "status": "fertig", "modus": "ueberarbeiten", "staerke": 55,
         "messung": {"kopf": {"aehnlich_original": float("nan")}, "b": {"aehnlich_original": float("inf")},
                     "c": {"aehnlich_original": 0.5}}}]}
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    assert r.status_code == 200 and "c: 50 % Themen-Ähnlichkeit" in r.text and "kopf:" not in r.text.split("Bilder")[1]


def test_entwurf_bildstand_fehler_kein_neuladen(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    pult.fehler_pfad = "/bilder"
    assert 'http-equiv="refresh"' not in angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text


def test_pult_formular_staerke_auswahl(angemeldet, pult):
    def sende(**extra):
        return angemeldet.post(f"/marketing/entwurf/{IID}/bilder", headers=HOST, follow_redirects=False,
                               data={"csrf": ui.CSRF_TOKEN, "platz": "kopf", "hinweis": "", **extra})
    assert sende(staerke="35").status_code == 303
    assert pult.aufrufe[-1][2]["staerke"] == 35 and pult.aufrufe[-1][2]["modus"] == "ueberarbeiten"
    sende(staerke="75")
    assert pult.aufrufe[-1][2]["staerke"] == 75 and pult.aufrufe[-1][2]["modus"] == "ueberarbeiten"
    sende(staerke="100")
    assert pult.aufrufe[-1][2]["staerke"] == 100 and pult.aufrufe[-1][2]["modus"] == "neu"
    sende(staerke="")
    assert pult.aufrufe[-1][2]["staerke"] == 55
    n = len(pult.aufrufe)
    for schlecht in ("abc", "101", "-1", "3.5"):
        assert sende(staerke=schlecht).status_code == 422, schlecht
    assert len(pult.aufrufe) == n


def test_entwurf_bilder_formular_ohne_csrf(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/bilder", headers=HOST, data={"platz": ""},
                        follow_redirects=False)
    assert r.status_code == 403 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_menue_vorlagen_und_editor():
    pfade = ("/marketing", "/marketing/entwuerfe", "/marketing/layouts", "/marketing/vorlagen")
    assert ui._aktiver_eintrag("/marketing/vorlagen", pfade) == "/marketing/vorlagen"
    assert ui._aktiver_eintrag("/marketing/vorlage-bild/x", pfade) == "/marketing/vorlagen"
    assert ui._aktiver_eintrag(f"/marketing/editor/{IID}", pfade) == "/marketing/entwuerfe"
    assert ("/marketing/vorlagen", "Vorlagen") in ui._NAV


# --- Firmen-Umschalter (Task 8) ----------------------------------------------

def _mit_firma(c, wert):
    """Anfrage-Kopfzeilen mit Sitzung UND dem Cookie mk_mandant (roher Wert)."""
    cookies = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    return {**HOST, "cookie": f"{cookies}; mk_mandant={wert}"}


def _mandant_fragen(pult):
    return [a[1] for a in pult.aufrufe if "mandant=" in a[1]]


def test_umschalter_zeigt_aktive_firmen_nicht_alt(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    assert 'action="/marketing/mandant"' in s and 'class="mandanten"' in s
    assert 'name="mandant" value="vibemind"' in s and 'name="mandant" value="fin2gether"' in s
    assert 'aria-pressed="true" class="mandant aktiv">VibeMind' in s
    assert 'aria-pressed="false" class="mandant">fin2gether' in s
    assert "Alt" not in s and 'value="alt"' not in s
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in s and 'name="zurueck" value="/marketing"' in s


def test_mandant_wechseln_setzt_cookie_und_leitet_zurueck(angemeldet):
    r = angemeldet.post("/marketing/mandant", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "fin2gether", "zurueck": "/marketing/layouts"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    kopf = r.headers["set-cookie"]
    assert kopf.startswith("mk_mandant=fin2gether") and "Path=/marketing" in kopf
    assert "HttpOnly" in kopf and "SameSite=lax" in kopf and "Max-Age=31536000" in kopf


@pytest.mark.parametrize("ziel", ["//boese.de", "https://boese.de", "/anderswo", "/marketing\\x",
                                  "/marketing//x", "/marketing/a\r\nb", ""])
def test_mandant_wechseln_boeses_ziel_geht_auf_marketing(angemeldet, ziel):
    r = angemeldet.post("/marketing/mandant", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "zurueck": ziel})
    assert r.status_code == 303 and r.headers["location"] == "/marketing"


def test_mandant_wechseln_ohne_csrf_403(angemeldet):
    r = angemeldet.post("/marketing/mandant", headers=HOST, follow_redirects=False,
                        data={"mandant": "fin2gether", "zurueck": "/marketing"})
    assert r.status_code == 403 and "set-cookie" not in r.headers


@pytest.mark.parametrize("wahl", ["alt", "gibtsnicht", "", 'x"><script>'])
def test_mandant_wechseln_inaktiv_oder_unbekannt_422(angemeldet, wahl):
    r = angemeldet.post("/marketing/mandant", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": wahl, "zurueck": "/marketing"})
    assert r.status_code == 422 and "set-cookie" not in r.headers
    assert "<script>" not in r.text


def test_mandant_wechseln_api_weg_503(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    r = angemeldet.post("/marketing/mandant", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "mandant": "fin2gether", "zurueck": "/marketing"})
    assert r.status_code == 503 and "set-cookie" not in r.headers


def test_cookie_fin2gether_fragt_liste_und_layouts_an(angemeldet, pult):
    h = _mit_firma(angemeldet, "fin2gether")
    assert 'aria-pressed="true" class="mandant aktiv">fin2gether' in angemeldet.get("/marketing", headers=h).text
    angemeldet.get("/marketing/entwuerfe", headers=h)
    angemeldet.get("/marketing/layouts", headers=h)
    angemeldet.get("/marketing/layout-bild/dunkel", headers=h)
    angemeldet.get("/marketing/layout/dunkel", headers=h)
    angemeldet.post("/marketing/layout-vorschau", headers=h, data={"csrf": ui.CSRF_TOKEN, "layout": "dunkel"})
    angemeldet.post("/marketing/layout/dunkel/speichern", headers=h,
                    data={"csrf": ui.CSRF_TOKEN, "layout": "dunkel"}, follow_redirects=False)
    fragen = _mandant_fragen(pult)
    assert "/uebersicht?mandant=fin2gether" in fragen
    assert any(p.startswith("/inhalte?") and "mandant=fin2gether" in p for p in fragen)
    assert "/layouts?mandant=fin2gether" in fragen
    assert not any("mandant=vibemind" in p for p in fragen)
    vorschauen = [a[2] for a in pult.aufrufe if a[1] == "/layouts/vorschau"]
    assert len(vorschauen) >= 2 and all(v["mandant"] == "fin2gether" for v in vorschauen)


@pytest.mark.parametrize("wert", ["alt", 'x"><script>', "", "gibtsnicht", "FIN2GETHER"])
def test_boeses_cookie_faellt_auf_vibemind(angemeldet, pult, wert):
    r = angemeldet.get("/marketing", headers=_mit_firma(angemeldet, wert))
    assert r.status_code == 200 and "<script" not in r.text
    angemeldet.get("/marketing/layouts", headers=_mit_firma(angemeldet, wert))
    fragen = _mandant_fragen(pult)
    assert "/uebersicht?mandant=vibemind" in fragen and "/layouts?mandant=vibemind" in fragen
    assert all(p.endswith("mandant=vibemind") or "mandant=vibemind&" in p for p in fragen)


def test_entwurf_folgt_der_firma_des_inhalts_nicht_dem_cookie(angemeldet, pult):
    pult.inhalt_mandant = "fin2gether"
    angemeldet.get(f"/marketing/entwurf/{IID}", headers=_mit_firma(angemeldet, "vibemind"))
    assert "/layouts?mandant=fin2gether" in _mandant_fragen(pult)
    assert "/layouts?mandant=vibemind" not in _mandant_fragen(pult)


def test_mandantenliste_nicht_erreichbar_seite_zeigt_fehler(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    assert angemeldet.get("/marketing", headers=HOST).status_code == 503


def test_quelltext_ohne_fest_verdrahtetes_vibemind():
    from pathlib import Path
    for name in ("ui_marketing.py", "ui_editor.py"):
        t = (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8")
        assert '"vibemind"' not in t and "mandant=vibemind" not in t, name


@pytest.mark.parametrize("wert", ["", None], ids=["leer", "null"])
def test_entwurf_inhalt_ohne_firma_fehlerseite_statt_500(angemeldet, pult, wert):
    pult.inhalt_mandant = wert
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    assert r.status_code == 422 and "Nicht möglich" in r.text
    assert not any(p.startswith("/layouts") for p in _mandant_fragen(pult))


# --- Task 5 (Newsletter-Freigabe): Entwurfsseite neu ---------------------------

def _seite(angemeldet, pult, status="entwurf", rueckmeldungen=None, **extra):
    pult.status, pult.rueckmeldungen, pult.extra = status, rueckmeldungen or [], extra
    return angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST).text


def _rumpf(s):
    """Nur der Seitenkoerper (ohne das eingebettete CSS, das Klassennamen enthaelt)."""
    return s[s.index("<main"):]


OFFEN = {"text": "Überschrift kürzer", "von": "mira", "am": "2026-10-07 09:00", "fassung": 2, "erledigt": False}


@pytest.mark.parametrize("status,rueck,wort", [
    ("entwurf", [OFFEN], "zurückgegeben"),
    ("entwurf", [], "in Arbeit"),
    ("entwurf", [{**OFFEN, "erledigt": True}], "in Arbeit"),
    ("eingereicht", [], "zur Freigabe"),
    ("freigegeben", [], "freigegeben"),
    ("abgelehnt", [], "verworfen"),
])
def test_status_pill_je_zustand(angemeldet, pult, status, rueck, wort):
    s = _rumpf(_seite(angemeldet, pult, status, rueck))
    assert '<span class="status-pill' in s and f'>{wort}</span>' in s
    assert ui_marketing.status_wort({"status": status}, rueck) == wort


def test_status_wort_ohne_rueckmeldungen_und_unbekannt():
    assert ui_marketing.status_wort({"status": "entwurf"}) == "in Arbeit"
    assert ui_marketing.status_wort({"status": "komisch"}) == "komisch"


def test_kopf_zeigt_firma_und_fassung(angemeldet, pult):
    s = _rumpf(_seite(angemeldet, pult))
    assert 'class="firma"' in s and ">VibeMind<" in s and "Fassung 2" in s


def test_band_mit_neuestem_kommentar_und_aelteren_in_details(angemeldet, pult):
    aelter = {"text": "Logo größer", "von": "ivan", "am": "2026-10-06 08:00", "fassung": 1, "erledigt": False}
    s = _rumpf(_seite(angemeldet, pult, "entwurf", [OFFEN, aelter]))
    band = s[s.index('class="feedback-band"'):]
    assert "Überschrift kürzer" in band.split("<details")[0] and "mira" in band
    assert "<details" in band and "Logo größer" in band.split("<details")[1]


def test_band_zeigt_lesbare_ortszeit_statt_iso(angemeldet, pult):
    """M8: "am 07.10.2026 14:32" (Ortszeit wie ui._zeit), nicht der rohe ISO-Text der API."""
    from datetime import datetime, timezone
    roh = "2026-10-07T12:32:10.123456+00:00"
    s = _rumpf(_seite(angemeldet, pult, "entwurf", [{**OFFEN, "am": roh}]))
    band = s[s.index('class="feedback-band"'):]
    erwartet = ui._zeit(datetime(2026, 10, 7, 12, 32, tzinfo=timezone.utc))
    assert f"am {erwartet}:" in band and erwartet.startswith("07.10.2026 ")
    assert "2026-10-07T12" not in band
    assert ui_marketing._wann(ui, "kaputt") == "kaputt" and ui_marketing._wann(ui, None) == ""


def test_entwurf_firmenname_nicht_lesbar_seite_bleibt(angemeldet, pult):
    """M5: scheitert nur die Firmenliste, steht die Seite mit der Firmen-Kennung (wie im Editor)."""
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("nicht_erreichbar", "x"), "/mandanten"
    r = angemeldet.get(f"/marketing/entwurf/{IID}", headers=HOST)
    assert r.status_code == 200, r.text
    s = _rumpf(r.text)
    assert 'class="firma"' in s and ">vibemind<" in s and "Early Access" in s


def test_kein_band_ohne_offene_rueckmeldung(angemeldet, pult):
    s = _rumpf(_seite(angemeldet, pult, "entwurf", [{**OFFEN, "erledigt": True}]))
    assert "feedback-band" not in s


def test_kein_freigeben_ablegen_mehr(angemeldet, pult):
    for st in ("entwurf", "eingereicht", "freigegeben", "abgelehnt"):
        s = _seite(angemeldet, pult, st)
        assert "Freigeben (ablegen)" not in s and 'value="freigeben"' not in s, st


def test_entwurf_hat_einreichen_verwerfen_und_editor(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    s = _seite(angemeldet, pult)
    assert f'action="/marketing/entwurf/{IID}/einreichen"' in s and "Zur Freigabe einreichen" in s
    assert "Zurückziehen" not in s
    assert f'/marketing/editor/{IID}' in s and "Im Editor öffnen" in s
    assert '<details class="gefahr">' in s and 'name="grund"' in s and 'value="ablehnen"' in s
    assert "Bild überarbeiten" in s


def test_eingereicht_zeigt_zurueckziehen_ohne_bildkarte(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    s = _seite(angemeldet, pult, "eingereicht")
    assert f'action="/marketing/entwurf/{IID}/zurueckziehen"' in s and "Zurückziehen" in s
    assert "/einreichen" not in s and "Zur Freigabe einreichen" not in s
    assert "Bild überarbeiten" not in s and '/bilder"' not in s
    assert not any(a[1].endswith("/bilder") for a in pult.aufrufe)
    assert '<details class="gefahr">' in s                      # verwerfen geht auch aus eingereicht


def test_freigegeben_und_verworfen_ohne_aktionen(angemeldet, pult):
    for st in ("freigegeben", "abgelehnt"):
        s = _rumpf(_seite(angemeldet, pult, st))
        assert "/einreichen" not in s and "/zurueckziehen" not in s and "gefahr" not in s


def test_fassungen_zeitleiste_markiert_freigegebene(angemeldet, pult):
    s = _rumpf(_seite(angemeldet, pult, "freigegeben", freigegebene_fassung=1))
    zeilen = [z.split("</li>")[0] for z in s.split("<li") if "Fassung" in z.split("</li>")[0]]
    eins = [z for z in zeilen if ">Fassung 1<" in z][0]
    zwei = [z for z in zeilen if ">Fassung 2<" in z][0]
    assert "freigegeben" in eins and "Agent" in eins
    assert "freigegeben" not in zwei


def test_felder_entwurf_behaelt_formular_in_arbeit(angemeldet, pult):
    s = _seite(angemeldet, pult)
    assert 'name="betreff"' in s and f'action="/marketing/entwurf/{IID}/speichern"' in s
    s = _seite(angemeldet, pult, "eingereicht")
    assert 'name="betreff"' not in s


def test_einreichen_sendet_pult_aufruf(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/einreichen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/entwurf/{IID}"
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/einreichen", {"von": "mira"})


def test_zurueckziehen_sendet_pult_aufruf(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/zurueckziehen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/zurueckziehen", {"von": "mira"})


@pytest.mark.parametrize("aktion", ["einreichen", "zurueckziehen", "verwerfen"])
def test_aktionen_ohne_csrf_kein_aufruf(angemeldet, pult, aktion):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/{aktion}", headers=HOST, follow_redirects=False,
                        data={"fassung": "2", "grund": "x"})
    assert r.status_code == 403 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_einreichen_ablehnung_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Assistent arbeitet gerade")
    r = angemeldet.post(f"/marketing/entwurf/{IID}/einreichen", headers=HOST, data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 422 and "Der Assistent arbeitet gerade" in r.text


def test_verwerfen_sendet_ablehnen_mit_grund(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/verwerfen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "fassung": "2", "grund": "  Thema passt nicht "})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/entwurf/{IID}"
    assert pult.aufrufe[-1] == ("POST", f"/inhalte/{IID}/entscheiden",
                                {"fassung": 2, "urteil": "ablehnen", "von": "mira", "grund": "Thema passt nicht"})


@pytest.mark.parametrize("grund", ["", "   "])
def test_verwerfen_ohne_grund_422_ohne_aufruf(angemeldet, pult, grund):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/verwerfen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "fassung": "2", "grund": grund})
    assert r.status_code == 422 and "Bitte gib einen Grund an" in r.text
    assert not any(a[0] == "POST" for a in pult.aufrufe)


def test_entscheiden_ablehnen_ohne_grund_422_ohne_aufruf(angemeldet, pult):
    r = angemeldet.post(f"/marketing/entwurf/{IID}/entscheiden", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "fassung": "2", "urteil": "ablehnen", "grund": ""})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_entwuerfe_liste_nutzt_status_woerter_und_eingereicht_filter(angemeldet, pult):
    s = angemeldet.get("/marketing/entwuerfe?status=eingereicht", headers=HOST).text
    assert "status=eingereicht" in pult.aufrufe[-1][1]
    assert 'class="aktiv" href="/marketing/entwuerfe?status=eingereicht"' in s
    assert "<td>in Arbeit</td>" in s


def test_uebersicht_kacheln_in_worten(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    for wort in ("in Arbeit", "zurückgegeben", "zur Freigabe", "freigegeben", "verworfen"):
        assert f"<span>{wort}</span>" in s
    assert "status=zurueckgegeben" in s and ">1<" in s
    assert "status=eingereicht" in s and "Zur Freigabe</span>" not in s


# Rand-Fehler: die Pult-Seite darf nie breiter als der Rahmen werden und nie
# waagerecht verschiebbar sein (Screenshot 07.10.: linke Spalte am Rand abgeschnitten).
def test_css_pult_spalten_schrumpfen_und_main_clippt():
    css = ui._STIL
    assert "main { overflow-x: clip; }" in css
    assert ".status-pill" in css and ".feedback-band" in css


# --- Fix-Runde 1: zurückgegeben in Übersicht und Liste -------------------------

def test_status_wort_zaehler_je_zeile():
    assert ui_marketing.status_wort({"status": "entwurf", "offene_rueckmeldungen": 2}) == "zurückgegeben"
    assert ui_marketing.status_wort({"status": "entwurf", "offene_rueckmeldungen": 0}) == "in Arbeit"
    assert ui_marketing.status_wort({"status": "eingereicht", "offene_rueckmeldungen": 2}) == "zur Freigabe"


def _liste(pult, *zeilen):
    pult.inhalte = list(zeilen)


def _zeile(titel, n, status="entwurf"):
    return {"id": IID, "art": "newsletter", "titel": titel, "status": status,
            "erstellt_am": "2026-10-07", "fassungen": 1, "layout": "dunkel", "offene_rueckmeldungen": n}


def test_liste_zeigt_zurueckgegeben_und_trennt_die_filter(angemeldet, pult):
    _liste(pult, _zeile("Offen-A", 1), _zeile("Ruhig-B", 0))
    z = angemeldet.get("/marketing/entwuerfe?status=zurueckgegeben", headers=HOST).text
    assert "status=entwurf" in pult.aufrufe[-1][1]                  # API kennt nur DB-Status
    assert "Offen-A" in z and "Ruhig-B" not in z and "<td>zurückgegeben</td>" in z
    assert 'class="aktiv" href="/marketing/entwuerfe?status=zurueckgegeben"' in z
    a = angemeldet.get("/marketing/entwuerfe?status=entwurf", headers=HOST).text
    assert "Ruhig-B" in a and "Offen-A" not in a and "<td>in Arbeit</td>" in a
    alle = angemeldet.get("/marketing/entwuerfe?status=alle", headers=HOST).text
    assert "Offen-A" in alle and "Ruhig-B" in alle


def test_einreichen_ist_zweitrangig_editor_ist_haupt(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    s = _rumpf(_seite(angemeldet, pult))
    assert 'class="knopf" href="/marketing/editor/' in s
    assert 'class="primaer"' not in s


def test_bilder_statuspunkte_je_status(angemeldet, pult):
    pult.bloecke = BLOECKE_MIT_PLATZ
    pult.bilder = {"auftraege": [{"platz": "kopf", "status": st} for st in
                                 ("offen", "in_arbeit", "fertig", "fehler", "verworfen")]}
    s = _rumpf(_seite(angemeldet, pult))
    for st in ("offen", "in_arbeit", "fertig", "fehler", "verworfen"):
        assert f'<span class="punkt bs-{st}"' in s, st
        assert f".punkt.bs-{st} " in ui._STIL


# --- Task 6: "Marke" statt "Layouts", Vorschauen lazy ---------------------------

SATZ_MARKE = "Diese Einstellungen (Farben, Schrift, Logo, Kopf- und Fußzeile) füllen neue Newsletter aus Vorlagen."


def test_galerie_heisst_marke_mit_satz_und_lazy_vorschauen(angemeldet):
    r = angemeldet.get("/marketing/layouts", headers=HOST)
    s = r.text
    assert r.status_code == 200
    assert "<title>Marke" in s and "<h1>Marke</h1>" in s
    assert SATZ_MARKE in s
    assert s.count('<iframe class="layout-bild" sandbox tabindex="-1" loading="lazy"') == 3
    for n in ("dunkel", "hell", "karte"):
        assert f'<span class="layout-platzhalter">{n}</span>' in s


def test_editor_heisst_marke_mit_satz(angemeldet):
    s = angemeldet.get("/marketing/layout/dunkel", headers=HOST).text
    assert "<h1>Marke dunkel</h1>" in s and SATZ_MARKE in s
    assert "Zurück zu allen Marken" in s and 'href="/marketing/layouts"' in s


def test_navigation_zeigt_marke_nicht_layouts(angemeldet):
    s = angemeldet.get("/marketing", headers=HOST).text
    assert 'href="/marketing/layouts"' in s and ">Marke<" in s and ">Layouts<" not in s
