"""Reels im Marketing-Pult (17.10.2026, Video-Claw). Der Client zur Marketing-API wird gefaelscht."""
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.datastructures import FormData  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_reels  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
AID = "0123abcd-3333-3333-3333-333333333333"
DATEI = "vid-0123abcd-herbst-reel.mp4"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.auftraege = [
            {"id": AID, "titel": "Herbst-Reel", "art": "bilder", "status": "fertig", "datei": DATEI,
             "dauer_s": 24.5, "bytes": 9_200_000, "angelegt_von": "agent", "erstellt_am": "2026-10-17T10:00",
             "briefing": {"thema": "bAV", "sprechertext": "Drei Fehler."},
             "protokoll": [{"text": "drei Bilder, zoom_rein"}]},
            {"id": "11112222-3333-3333-3333-333333333333", "titel": "Laeuft", "art": "material",
             "status": "in_arbeit", "briefing": {"thema": "<script>x</script>"}, "protokoll": []}]

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
        if self.fehler:
            raise self.fehler
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True}]}
        if pfad.startswith("/video?"):
            return {"auftraege": self.auftraege}
        if pfad == "/video":
            return {"auftrag": AID}
        if pfad.endswith("/abbrechen"):
            return {"status": "abgebrochen"}
        return {}


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    monkeypatch.setenv("MARKETING_MANDANT", "vibemind")
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


# --- reine Teile ---------------------------------------------------------------

def test_briefing_bilder():
    art, titel, b = ui_reels.briefing_aus_formular(FormData([
        ("art", "bilder"), ("titel", " Herbst "), ("thema", "bAV"), ("sprechertext", "Drei."), ("dauer_s", "25"),
        ("bilder", "team.png, buero.jpg\nlogo.png"), ("logo", "logo.png"), ("farbe_hintergrund", "#0f2422"),
        ("farbe_text", ""), ("videos", "a1b2")]))
    assert (art, titel) == ("bilder", "Herbst")
    assert b["bilder"] == ["team.png", "buero.jpg", "logo.png"] and b["farben"] == {"hintergrund": "#0f2422"}
    assert b["dauer_s"] == 25 and b["stimme"] == "standard" and "videos" not in b


def test_briefing_material_und_kurzfassung():
    _, _, b = ui_reels.briefing_aus_formular(FormData([("art", "material"), ("videos", "a1, b2"), ("dauer_s", "x")]))
    assert b["videos"] == ["a1", "b2"] and b["dauer_s"] == 30 and "bilder" not in b
    _, _, k = ui_reels.briefing_aus_formular(FormData([("art", "kurzfassung"), ("video", " v1 ")]))
    assert k["video"] == "v1"


# --- Seite ---------------------------------------------------------------------

def test_menue_hat_reels():
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert 'href="/marketing/reels"' in ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)


def test_seite_zeigt_video_post_knopf_und_abbrechen(angemeldet, pult):
    r = angemeldet.get("/marketing/reels", headers=HOST)
    s = r.text
    assert r.status_code == 200
    assert pult.aufrufe[-1][1] == "/video?mandant=vibemind"
    assert f'<video controls preload="metadata" width="270" src="/medien/datei/{DATEI}">' in s
    assert "drei Bilder, zoom_rein" in s and "9,2 MB" in s
    assert 'action="/marketing/reels/post"' in s and "Als LinkedIn-Post vorbereiten" in s
    assert 'action="/marketing/reels/11112222-3333-3333-3333-333333333333/abbrechen"' in s
    assert "&lt;script&gt;x&lt;/script&gt;" in s and "<script>x" not in s
    assert 'http-equiv="refresh"' in s          # laeuft noch -> Seite frischt sich auf
    assert 'action="/marketing/reels/neu"' in s


def test_andere_firma_kein_post_knopf(angemeldet, pult):
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    s = angemeldet.get("/marketing/reels", headers=HOST).text
    assert "Als LinkedIn-Post vorbereiten" not in s and "Posten kann nur der Laden dieser Firma" in s


def test_neu_bestellt_beim_pult(angemeldet, pult):
    r = angemeldet.post("/marketing/reels/neu", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "art": "bilder", "titel": "Herbst", "thema": "bAV", "sprechertext": "Drei.",
        "bilder": "team.png", "dauer_s": "20"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/reels"
    methode, pfad, daten = pult.aufrufe[-1]
    assert (methode, pfad) == ("POST", "/video") and daten["mandant"] == "vibemind" and daten["art"] == "bilder"
    assert daten["briefing"]["bilder"] == ["team.png"] and daten["briefing"]["dauer_s"] == 20


@pytest.mark.parametrize("daten", [{"art": "film", "titel": "T", "thema": "t"},
                                   {"art": "bilder", "titel": "", "thema": "t"},
                                   {"art": "bilder", "titel": "T", "thema": ""}])
def test_neu_prueft_vorher(angemeldet, pult, daten):
    r = angemeldet.post("/marketing/reels/neu", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, **daten})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_neu_api_lehnt_ab(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Bild gehoert einer anderen Firma: x.png")
    r = angemeldet.post("/marketing/reels/neu", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "art": "bilder", "titel": "T", "thema": "t", "bilder": "x.png"})
    assert r.status_code == 422 and "anderen Firma" in r.text


def test_abbrechen(angemeldet, pult):
    r = angemeldet.post(f"/marketing/reels/{AID}/abbrechen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and pult.aufrufe[-1][:2] == ("POST", f"/video/{AID}/abbrechen")


def test_ohne_csrf_403(angemeldet, pult):
    for pfad in ("/marketing/reels/neu", f"/marketing/reels/{AID}/abbrechen", "/marketing/reels/post"):
        r = angemeldet.post(pfad, headers=HOST, follow_redirects=False, data={"titel": "x"})
        assert r.status_code == 403, pfad
    assert not pult.aufrufe


def test_post_vorbereiten_legt_entwurf_an(angemeldet, pult, monkeypatch):
    gesehen = []
    monkeypatch.setattr(server, "post_entwurf_erstellen",
                        lambda thema, text, medien_datei="": gesehen.append((thema, text, medien_datei))
                        or json.dumps({"draft_id": 7}))
    r = angemeldet.post("/marketing/reels/post", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "Herbst-Reel", "text": "Drei Fehler, kurz erklaert."})
    assert r.status_code == 303 and r.headers["location"] == "/freigaben"
    assert gesehen == [("Herbst-Reel", "Drei Fehler, kurz erklaert.", DATEI)]


@pytest.mark.parametrize("daten", [
    {"datei": "../x.mp4", "thema": "T", "text": "x"},
    {"datei": "vid-ffffffff-fremd.mp4", "thema": "T", "text": "x"},     # nicht unter den eigenen fertigen
    {"datei": DATEI, "thema": "", "text": "x"},
    {"datei": DATEI, "thema": "T", "text": "x" * 3001},
])
def test_post_vorbereiten_prueft(angemeldet, pult, monkeypatch, daten):
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    r = angemeldet.post("/marketing/reels/post", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, **daten})
    assert r.status_code == 422


def test_post_vorbereiten_nur_eigene_firma(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    r = angemeldet.post("/marketing/reels/post", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422


def test_post_vorbereiten_ohne_firma_im_laden(angemeldet, pult, monkeypatch):
    monkeypatch.delenv("MARKETING_MANDANT")
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    r = angemeldet.post("/marketing/reels/post", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422


def test_entwurf_fehler_wird_angezeigt(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(server, "post_entwurf_erstellen",
                        lambda *a, **k: json.dumps({"fehler": "Zum selben Thema gibt es schon einen Beitrag."}))
    r = angemeldet.post("/marketing/reels/post", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422 and "schon einen Beitrag" in r.text


# --- Freigabe-Karte zeigt Video/Ton zum Ansehen --------------------------------

def _z(media_ref):
    return {"channel": "linkedin", "name": None, "recipient": "eigenes-profil", "id": 7, "media_ref": media_ref,
            "consent_status": "n/a"}


def test_freigabekarte_spielt_reel_ab(monkeypatch):
    monkeypatch.setattr(server.medien, "pruefe", lambda n: (n, None))
    s = ui._entwurf_kopf(_z(DATEI), "pending")
    assert f'<video class="vorschau" controls preload="none" src="/medien/datei/{DATEI}"></video>' in s
    assert f"Anhang: <b>{DATEI}</b>" in s


def test_freigabekarte_bilder_nur_beim_namen(monkeypatch):
    monkeypatch.setattr(server.medien, "pruefe", lambda n: (n, None))
    s = ui._entwurf_kopf(_z("a.png,b.jpg"), "pending")
    assert "<img" not in s and "<video" not in s


def test_freigabekarte_fehlende_datei_ohne_vorschau(monkeypatch):
    monkeypatch.setattr(server.medien, "pruefe", lambda n: (None, "fehlt"))
    s = ui._entwurf_kopf(_z(DATEI), "pending")
    assert "<video" not in s and DATEI in s


def test_freigabekarte_podcast_anhoeren(monkeypatch):
    monkeypatch.setattr(server.medien, "pruefe", lambda n: (n, None))
    assert '<audio controls preload="none" src="/medien/datei/pod-1.mp3">' in ui._entwurf_kopf(_z("pod-1.mp3"), "pending")
