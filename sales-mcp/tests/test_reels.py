"""Reels im Marketing-Pult (17.10.2026, Video-Claw; Reels Stufe 1 21.10.2026: Galerie, Detailseite,
gefuehrte Bestellung, Herunterladen). Der Client zur Marketing-API wird gefaelscht."""
import json
import os
import re
import urllib.parse

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
AID_LAEUFT = "11112222-3333-3333-3333-333333333333"
AID_FEHLER = "44445555-3333-3333-3333-333333333333"
AID_ARCHIV = "66667777-3333-3333-3333-333333333333"
AID_FREMD = "88889999-3333-3333-3333-333333333333"
NEU = "aaaabbbb-3333-3333-3333-333333333333"
DATEI = "vid-0123abcd-herbst-reel.mp4"
POSTER = "vid-0123abcd-herbst-reel.jpg"
ROHBEFUND = "Render: ffmpeg exit 1 (stderr: moov atom not found)"
BILD_NEU = "eeeeffff-3333-3333-3333-333333333333"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _auftraege():
    return [
        {"id": AID, "mandant": "vibemind", "titel": "Herbst-Reel", "art": "bilder", "status": "fertig",
         "datei": DATEI, "poster": POSTER, "dauer_s": 24.5, "bytes": 9_200_000, "angelegt_von": "agent",
         "erstellt_am": "2026-10-17T10:00:00", "archiviert": False, "befund": "", "befund_text": "",
         "vorgaenger": AID_FEHLER, "vorgaenger_titel": "Herbst-Reel (erster Versuch)",
         "aenderungswunsch": "kürzer, mehr Bilder vom Team",
         "briefing": {"thema": "bAV", "sprechertext": "Drei Fehler.", "hook": "Wusstest du?", "dauer_s": 25,
                      "stimme": "eigene-a", "bilder": ["team.png"]},
         "protokoll": [{"text": "drei Bilder, zoom_rein"}]},
        {"id": AID_LAEUFT, "mandant": "vibemind", "titel": "Laeuft", "art": "material", "status": "in_arbeit",
         "archiviert": False, "erstellt_am": "2026-10-18T09:00:00", "befund": "", "befund_text": "",
         "briefing": {"thema": "<script>x</script>"}, "protokoll": []},
        {"id": AID_FEHLER, "mandant": "vibemind", "titel": "Herbst-Reel (erster Versuch)", "art": "bilder",
         "status": "fehler", "archiviert": False, "erstellt_am": "2026-10-16T08:00:00", "befund": ROHBEFUND,
         "befund_text": "Laura konnte das Video nicht fertig rendern.",
         "briefing": {"thema": "bAV", "sprechertext": "Drei Fehler.", "stimme": "standard",
                      "stimme_hinweis": "Die Markenstimme 'alt' gibt es nicht mehr – Standard genommen."},
         "protokoll": [{"text": "Laura meldet Renderfehler"}]},
        {"id": AID_ARCHIV, "mandant": "vibemind", "titel": "Alter Sommer", "art": "bilder", "status": "fertig",
         "datei": "vid-66667777-alter-sommer.mp4", "dauer_s": 30, "archiviert": True,
         "erstellt_am": "2026-08-01T08:00:00", "befund": "", "befund_text": "", "briefing": {"thema": "Sommer"},
         "protokoll": []},
        {"id": AID_FREMD, "mandant": "fin2gether", "titel": "Fremd-Reel", "art": "bilder", "status": "fertig",
         "datei": "vid-88889999-fremd-reel.mp4", "dauer_s": 20, "archiviert": False,
         "erstellt_am": "2026-10-17T11:00:00", "befund": "", "befund_text": "", "briefing": {"thema": "Fonds"},
         "protokoll": []},
    ]


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.zeitlimits = {}
        self.fehler = None
        self.fehler_pfad = None
        self.auftraege = _auftraege()
        self.bilder = [{"name": "team.png"}, {"name": "buero.jpg"}, {"name": "logo.png"}, {"name": "../boese.png"}]
        self.material = {"videos": [
            {"kennung": "a1b2c3d4-0000", "name": "Messe 2026 <lang>", "projekt": "Messe", "dauer_s": 312.4},
            {"kennung": "b2c3d4e5-0000", "name": "Interview Ivan", "projekt": "Team", "dauer_s": 95}]}
        self.markenstimme = "eigene-a"
        self.stimmen = ["eigene-a", "eigene-b"]
        self.archiv_ok = True
        self.freigabe_ok = True

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        self.zeitlimits[pfad] = zeitlimit
        if self.fehler and (self.fehler_pfad is None or self.fehler_pfad in pfad):
            raise self.fehler
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True}]}
        if pfad.startswith("/video?"):
            q = urllib.parse.parse_qs(pfad.split("?", 1)[1])
            archiv = q.get("archiv", ["false"])[0] == "true"
            return {"auftraege": [a for a in self.auftraege if a["mandant"] == q["mandant"][0]
                                  and bool(a.get("archiviert")) == archiv]}
        if pfad.startswith("/video/bilder?"):
            return {"bilder": self.bilder}
        if pfad == "/video/material":
            return self.material
        if pfad.startswith("/marke?mandant="):
            return {"profil": {"werte": {"stimme": self.markenstimme} if self.markenstimme else {}}}
        if pfad == "/stimmen":
            return {"stimmen": self.stimmen} if self.stimmen is not None else {}
        if pfad == "/video":
            return {"auftrag": NEU}
        if pfad.endswith("/nochmal"):
            return {"auftrag": NEU}
        if pfad.endswith("/archivieren"):
            return {"ok": self.archiv_ok}
        if pfad.endswith("/abbrechen"):
            return {"status": "abgebrochen"}
        if pfad.endswith("/ki/neu"):
            return {"bild": BILD_NEU}
        if pfad.endswith("/ki/freigeben"):
            return {"ok": self.freigabe_ok}
        return {}

    def posts(self):
        return [a for a in self.aufrufe if a[0] == "POST"]


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


def rumpf(r):
    """Nur der Seitenkoerper (das eingebettete CSS nennt Klassennamen)."""
    return r.text[r.text.index("<main"):]


def get(c, pfad):
    return c.get(pfad, headers=HOST)


def post(c, pfad, daten):
    return c.post(pfad, headers=HOST, follow_redirects=False, data=daten)


# --- reine Teile ---------------------------------------------------------------

def test_briefing_bilder():
    art, titel, b = ui_reels.briefing_aus_formular(FormData([
        ("art", "bilder"), ("titel", " Herbst "), ("thema", "bAV"), ("sprechertext", "Drei."), ("dauer_s", "25"),
        ("bild", "team.png"), ("bild", " buero.jpg "), ("logo", "logo.png"), ("farbe_hintergrund", "#0f2422"),
        ("stimme", "eigene-b"), ("video", "a1b2c3d4")]))
    assert (art, titel) == ("bilder", "Herbst")
    assert b == {"thema": "bAV", "sprechertext": "Drei.", "hook": "", "dauer_s": 25,
                 "bilder": ["team.png", "buero.jpg"], "logo": "logo.png"}


def test_briefing_material_und_kurzfassung():
    _, _, b = ui_reels.briefing_aus_formular(FormData([("art", "material"), ("video", "a1"), ("video", "b2"),
                                                       ("dauer_s", "x")]))
    assert b["videos"] == ["a1", "b2"] and b["dauer_s"] == 30 and "bilder" not in b and "stimme" not in b
    _, _, k = ui_reels.briefing_aus_formular(FormData([("art", "kurzfassung"), ("video", " v1 ")]))
    assert k["video"] == "v1" and "videos" not in k


@pytest.mark.parametrize("art,bilder,videos,erwartet", [
    ("bilder", ["a.png"], [], ""),
    ("bilder", [], [], "mindestens ein Bild"),
    ("bilder", [f"b{i}.png" for i in range(9)], [], "höchstens 8"),
    ("bilder", ["../x.png"], [], "Ungültige Auswahl"),
    ("material", [], [], ""),
    ("material", [], [f"a1b2c3d{i}" for i in range(9)], "höchstens 8"),
    ("material", [], ["xyz"], "Ungültige Auswahl"),
    ("kurzfassung", [], [], "genau ein Video"),
    ("kurzfassung", [], ["a1b2c3d4", "b2c3d4e5"], "genau ein Video"),
    ("kurzfassung", [], ["a1b2c3d4"], ""),
])
def test_auswahl_regeln(art, bilder, videos, erwartet):
    meldung = ui_reels.auswahl_fehler(art, bilder, videos)
    assert (erwartet in meldung) if erwartet else meldung == ""


def test_dauer_und_datum():
    assert ui_reels.dauer_text(24.5) == "24,5 s" and ui_reels.dauer_text(30) == "30 s"
    assert ui_reels.dauer_text(None) == "" and ui_reels.datum_text("2026-10-17T10:00:00") == "17.10.2026"
    assert ui_reels.datum_text("kaputt") == ""


# --- Galerie ---------------------------------------------------------------------

def test_menue_hat_reels():
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert 'href="/marketing/reels"' in ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)


def test_galerie_reiter_und_vorgabe(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels")
    s = rumpf(r)
    assert r.status_code == 200
    assert ("GET", "/video?mandant=vibemind&archiv=false&limit=200", None) in pult.aufrufe
    assert '<nav class="reiter"' in s
    assert '<a href="/marketing/reels?reiter=fertig" aria-current="page">Fertig <span class="zahl">1</span></a>' in s
    assert '<a href="/marketing/reels?reiter=arbeit">In Arbeit <span class="zahl">1</span></a>' in s
    assert '<a href="/marketing/reels?reiter=fehler">Fehlgeschlagen <span class="zahl">1</span></a>' in s
    assert '<a href="/marketing/reels?reiter=archiv">Archiv <span class="zahl">1</span></a>' in s
    assert f'href="/marketing/reels/{AID}"' in s and f'href="/marketing/reels/{AID_LAEUFT}"' not in s
    assert '<a class="knopf" href="/marketing/reels/neu">Neues Reel</a>' in s
    assert 'http-equiv="refresh" content="30"' in r.text      # es laeuft noch eins
    # ohne fertige Reels ist "In Arbeit" die Vorgabe
    pult.auftraege = [a for a in pult.auftraege if a["status"] != "fertig"]
    s = rumpf(get(angemeldet, "/marketing/reels"))
    assert '<a href="/marketing/reels?reiter=arbeit" aria-current="page">' in s
    assert f'href="/marketing/reels/{AID_LAEUFT}"' in s and "<script>x" not in s
    s = rumpf(get(angemeldet, "/marketing/reels?reiter=fehler"))
    assert f'href="/marketing/reels/{AID_FEHLER}"' in s and f'href="/marketing/reels/{AID_LAEUFT}"' not in s


def test_galerie_ohne_laufende_kein_refresh(angemeldet, pult):
    pult.auftraege = [a for a in pult.auftraege if a["status"] not in ("offen", "in_arbeit")]
    assert 'http-equiv="refresh"' not in get(angemeldet, "/marketing/reels").text


def test_galerie_leer(angemeldet, pult):
    pult.auftraege = []
    s = rumpf(get(angemeldet, "/marketing/reels"))
    assert "Noch keine Reels" in s and 'href="/marketing/reels/neu"' in s


def test_karte_mit_poster(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels"))
    karte = s[s.index(f'href="/marketing/reels/{AID}"'):]
    karte = karte[:karte.index("</a>")]
    assert f'poster="/medien/datei/{POSTER}"' in karte and 'preload="none"' in karte
    assert "Herbst-Reel" in karte and "fertig" in karte and "24,5 s" in karte and "17.10.2026" in karte
    assert "controls" not in karte


@pytest.mark.parametrize("poster", [None, "", "../x.jpg", "vid-0123abcd-herbst.png"])
def test_karte_ohne_poster(angemeldet, pult, poster):
    pult.auftraege[0]["poster"] = poster
    s = rumpf(get(angemeldet, "/marketing/reels"))
    karte = s[s.index(f'href="/marketing/reels/{AID}"'):]
    karte = karte[:karte.index("</a>")]
    assert "<video" not in karte and "poster=" not in karte
    assert '<div class="reel-flaeche">' in karte and "Herbst-Reel" in karte


def test_archiv_reiter_fragt_archiv_true(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels?reiter=archiv"))
    assert ("GET", "/video?mandant=vibemind&archiv=true&limit=200", None) in pult.aufrufe
    assert f'href="/marketing/reels/{AID_ARCHIV}"' in s and f'href="/marketing/reels/{AID}"' not in s
    assert '<a href="/marketing/reels?reiter=archiv" aria-current="page">' in s


def test_galerie_fremder_reiter_faellt_auf_vorgabe(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels?reiter=%3Cx%3E"))
    assert '<a href="/marketing/reels?reiter=fertig" aria-current="page">' in s and "<x>" not in s


# --- Detailseite ------------------------------------------------------------------

def test_detail_zeigt_alles_und_befund_satz(angemeldet, pult):
    r = get(angemeldet, f"/marketing/reels/{AID_FEHLER}")
    s = rumpf(r)
    assert r.status_code == 200
    details = s.index("<details")
    assert "Laura konnte das Video nicht fertig rendern." in s[:details]
    assert ROHBEFUND not in s[:details] and ui._e(ROHBEFUND) in s[details:]
    assert "Was der Claw gemacht hat" in s[details:] and "Laura meldet Renderfehler" in s[details:]
    assert "Die Markenstimme &#x27;alt&#x27; gibt es nicht mehr" in s
    # fertiges Reel: grosses Video, alle Angaben, Vorgaenger und Wunsch
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert (f'<video class="reel-gross" controls preload="metadata" poster="/medien/datei/{POSTER}" '
            f'src="/medien/datei/{DATEI}"></video>') in s
    for teil in ("Herbst-Reel", "bAV", "Drei Fehler.", "Wusstest du?", "eigene-a", "24,5 s", "9,2 MB",
                 "drei Bilder, zoom_rein", "kürzer, mehr Bilder vom Team"):
        assert teil in s, teil
    assert f'<a href="/marketing/reels/{AID_FEHLER}">Herbst-Reel (erster Versuch)</a>' in s
    # laufendes Reel: escaped, frischt sich auf
    r = get(angemeldet, f"/marketing/reels/{AID_LAEUFT}")
    assert "&lt;script&gt;x&lt;/script&gt;" in r.text and "<script>x" not in r.text
    assert 'http-equiv="refresh"' in r.text


def test_detail_im_archiv(angemeldet, pult):
    r = get(angemeldet, f"/marketing/reels/{AID_ARCHIV}")
    assert r.status_code == 200 and "Alter Sommer" in r.text
    assert ("GET", "/video?mandant=vibemind&archiv=true&limit=200", None) in pult.aufrufe


def test_detail_fremde_firma_404(angemeldet, pult):
    r = get(angemeldet, f"/marketing/reels/{AID_FREMD}")
    assert r.status_code == 404 and "Fremd-Reel" not in r.text
    assert [a[1] for a in pult.aufrufe if a[1].startswith("/video?")] == [
        "/video?mandant=vibemind&archiv=false&limit=200", "/video?mandant=vibemind&archiv=true&limit=200"]
    # Unsinnige Kennung: 404 ohne API-Aufruf
    pult.aufrufe.clear()
    assert get(angemeldet, "/marketing/reels/..%2Fx").status_code == 404
    assert not [a for a in pult.aufrufe if a[1].startswith("/video")]


def test_aktionen_fremder_firma_gehen_mit_der_eigenen_firma_an_die_api(angemeldet, pult):
    """Die API prueft den Mandanten (404 -> abgelehnt); die Seite schickt immer die gewaehlte Firma mit."""
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Unbekannter Auftrag")
    pult.fehler_pfad = AID_FREMD
    for pfad, daten in ((f"/marketing/reels/{AID_FREMD}/nochmal", {"wunsch": "kürzer"}),
                        (f"/marketing/reels/{AID_FREMD}/archiv", {"an": "1"}),
                        (f"/marketing/reels/{AID_FREMD}/abbrechen", {})):
        r = post(angemeldet, pfad, {"csrf": ui.CSRF_TOKEN, **daten})
        assert r.status_code == 422 and "Unbekannter Auftrag" in r.text, pfad
    assert [a[2]["mandant"] for a in pult.posts()] == ["vibemind"] * 3


def test_download_link(angemeldet, pult):
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert f'<a class="knopf" href="/medien/datei/{DATEI}?laden=1">Herunterladen</a>' in s
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_FEHLER}"))
    assert "Herunterladen" not in s and "<video" not in s


def test_nochmal_post_leitet_auf_neuen_auftrag(angemeldet, pult):
    r = post(angemeldet, f"/marketing/reels/{AID}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": " kürzer "})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{NEU}"
    assert pult.posts() == [("POST", f"/video/{AID}/nochmal", {"wunsch": "kürzer", "mandant": "vibemind"})]


def test_nochmal_zu_langer_wunsch(angemeldet, pult):
    r = post(angemeldet, f"/marketing/reels/{AID}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": "x" * 501})
    assert r.status_code == 422 and not pult.posts()


def test_nochmal_unbrauchbare_antwort_geht_zur_galerie(angemeldet, pult, monkeypatch):
    alt = pult.anfrage
    monkeypatch.setattr(marketing_pult, "anfrage", lambda m, p, d=None, **k: {"auftrag": "//boese.example"}
                        if p.endswith("/nochmal") else alt(m, p, d, **k))
    r = post(angemeldet, f"/marketing/reels/{AID}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": "x"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/reels"


def test_nochmal_ohne_csrf_403(angemeldet, pult):
    for pfad in (f"/marketing/reels/{AID}/nochmal", f"/marketing/reels/{AID}/archiv",
                 f"/marketing/reels/{AID}/abbrechen", "/marketing/reels/neu", "/marketing/reels/post"):
        r = post(angemeldet, pfad, {"wunsch": "x", "titel": "x"})
        assert r.status_code == 403, pfad
    assert not pult.aufrufe


def test_neu_versuchen_nur_bei_fehler(angemeldet, pult):
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_FEHLER}"))
    assert f'action="/marketing/reels/{AID_FEHLER}/nochmal"' in s and "Neu versuchen" in s
    assert 'name="wunsch" rows' not in s and "Nochmal mit Änderung" not in s
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert "Neu versuchen" not in s and "Nochmal mit Änderung" in s
    assert ('<textarea name="wunsch" rows="3" maxlength="500" required '
            'placeholder="z. B. kürzer, anderer Einstieg, mehr Bilder vom Team"></textarea>') in s
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_LAEUFT}"))
    assert "/nochmal" not in s and f'action="/marketing/reels/{AID_LAEUFT}/abbrechen"' in s
    assert "/archiv" not in s
    r = post(angemeldet, f"/marketing/reels/{AID_FEHLER}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": ""})
    assert r.status_code == 303 and pult.posts()[-1][2] == {"wunsch": "", "mandant": "vibemind"}


def test_archivieren_und_wieder_anzeigen(angemeldet, pult):
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert (f'<form method="post" action="/marketing/reels/{AID}/archiv" class="aktion">'
            in s) and '<input type="hidden" name="an" value="1">' in s and ">Archivieren</button>" in s
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_ARCHIV}"))
    assert '<input type="hidden" name="an" value="0">' in s and ">Wieder anzeigen</button>" in s
    r = post(angemeldet, f"/marketing/reels/{AID}/archiv", {"csrf": ui.CSRF_TOKEN, "an": "1"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID}"
    r = post(angemeldet, f"/marketing/reels/{AID_ARCHIV}/archiv", {"csrf": ui.CSRF_TOKEN, "an": "0"})
    assert r.status_code == 303
    assert [a[2] for a in pult.posts()] == [{"an": True, "mandant": "vibemind"},
                                            {"an": False, "mandant": "vibemind"}]
    pult.archiv_ok = False
    r = post(angemeldet, f"/marketing/reels/{AID}/archiv", {"csrf": ui.CSRF_TOKEN, "an": "1"})
    assert r.status_code == 422 and "erledigte" in r.text


def test_abbrechen(angemeldet, pult):
    r = post(angemeldet, f"/marketing/reels/{AID_LAEUFT}/abbrechen", {"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_LAEUFT}"
    assert pult.posts() == [("POST", f"/video/{AID_LAEUFT}/abbrechen", {"mandant": "vibemind"})]


def test_post_linkedin_nur_eigene_firma(angemeldet, pult):
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert 'action="/marketing/reels/post"' in s and "Als LinkedIn-Post vorbereiten" in s
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_FREMD}"))
    assert "Fremd-Reel" in s
    assert "Als LinkedIn-Post vorbereiten" not in s and "Posten kann nur der Laden dieser Firma" in s


def test_post_vorbereiten_legt_entwurf_an(angemeldet, pult, monkeypatch):
    gesehen = []
    monkeypatch.setattr(server, "post_entwurf_erstellen",
                        lambda thema, text, medien_datei="": gesehen.append((thema, text, medien_datei))
                        or json.dumps({"draft_id": 7}))
    r = post(angemeldet, "/marketing/reels/post",
             {"csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "Herbst-Reel", "text": "Drei Fehler, kurz erklaert."})
    assert r.status_code == 303 and r.headers["location"] == "/freigaben"
    assert gesehen == [("Herbst-Reel", "Drei Fehler, kurz erklaert.", DATEI)]


def test_post_vorbereiten_auch_fuer_archivierte(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: json.dumps({"draft_id": 8}))
    r = post(angemeldet, "/marketing/reels/post",
             {"csrf": ui.CSRF_TOKEN, "datei": "vid-66667777-alter-sommer.mp4", "thema": "T", "text": "x"})
    assert r.status_code == 303


@pytest.mark.parametrize("daten", [
    {"datei": "../x.mp4", "thema": "T", "text": "x"},
    {"datei": "vid-ffffffff-fremd.mp4", "thema": "T", "text": "x"},     # nicht unter den eigenen fertigen
    {"datei": "vid-88889999-fremd-reel.mp4", "thema": "T", "text": "x"},  # fertig, aber andere Firma
    {"datei": DATEI, "thema": "", "text": "x"},
    {"datei": DATEI, "thema": "T", "text": "x" * 3001},
])
def test_post_vorbereiten_prueft(angemeldet, pult, monkeypatch, daten):
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    r = post(angemeldet, "/marketing/reels/post", {"csrf": ui.CSRF_TOKEN, **daten})
    assert r.status_code == 422


def test_post_vorbereiten_nur_eigene_firma(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    r = post(angemeldet, "/marketing/reels/post", {"csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422


def test_post_vorbereiten_ohne_firma_im_laden(angemeldet, pult, monkeypatch):
    monkeypatch.delenv("MARKETING_MANDANT")
    monkeypatch.setattr(server, "post_entwurf_erstellen", lambda *a, **k: pytest.fail("kein Entwurf"))
    r = post(angemeldet, "/marketing/reels/post", {"csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422


def test_entwurf_fehler_wird_angezeigt(angemeldet, pult, monkeypatch):
    monkeypatch.setattr(server, "post_entwurf_erstellen",
                        lambda *a, **k: json.dumps({"fehler": "Zum selben Thema gibt es schon einen Beitrag."}))
    r = post(angemeldet, "/marketing/reels/post", {"csrf": ui.CSRF_TOKEN, "datei": DATEI, "thema": "T", "text": "x"})
    assert r.status_code == 422 and "schon einen Beitrag" in r.text


# --- Gefuehrte Bestellung ------------------------------------------------------------

def test_bestellung_schritt1_vier_karten(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu")
    s = rumpf(r)
    assert r.status_code == 200
    for art, name in (("bilder", "Aus Bildern"), ("material", "Aus Videomaterial"),
                      ("kurzfassung", "Kurzfassung eines Videos"), ("ki", "Aus KI-Bildern")):
        assert f'<a class="reel-art" href="/marketing/reels/neu?art={art}"><b>{name}</b>' in s
    assert s.count('<a class="reel-art"') == 4
    assert not [a for a in pult.aufrufe if a[1].startswith("/video")]


def test_bestellung_bilder_raster_max8(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu?art=bilder")
    s = rumpf(r)
    assert r.status_code == 200 and ("GET", "/video/bilder?mandant=vibemind", None) in pult.aufrufe
    assert '<form method="get" action="/marketing/reels/neu"' in s
    assert '<input type="hidden" name="schritt" value="3">' in s
    assert '<input type="checkbox" name="bild" value="team.png">' in s
    assert '<img src="/medien/datei/team.png" loading="lazy" alt="">' in s
    assert "boese" not in s and "höchstens 8" in s
    assert '<select name="logo"><option value="">kein Logo</option>' in s and '<option value="logo.png">' in s
    neun = "&".join(f"bild=b{i}.png" for i in range(9))
    r = get(angemeldet, f"/marketing/reels/neu?art=bilder&schritt=3&{neun}")
    assert r.status_code == 422 and "höchstens 8" in r.text
    assert '<input type="checkbox" name="bild" value="team.png">' in rumpf(r)   # wieder Schritt 2
    # Auswahl bleibt beim Zurueckspringen angehakt
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&bild=buero.jpg&logo=logo.png"))
    assert '<input type="checkbox" name="bild" value="buero.jpg" checked>' in s
    assert '<option value="logo.png" selected>' in s


def test_bestellung_bilder_ohne_bilder(angemeldet, pult):
    pult.bilder = []
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder"))
    assert "Noch keine Bilder" in s and 'href="/medien"' in s and "Weiter" not in s


def test_bestellung_material_tabelle(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu?art=material")
    s = rumpf(r)
    assert r.status_code == 200 and pult.zeitlimits["/video/material"] >= 10
    assert '<input type="checkbox" name="video" value="a1b2c3d4-0000">' in s
    assert "Messe 2026 &lt;lang&gt;" in s and "<lang>" not in s and "Interview Ivan" in s
    assert "5:12" in s and "1:35" in s and "Team" in s
    assert "sucht der Claw selbst" in s and ">Weiter</button>" in s


@pytest.mark.parametrize("material,fehler", [
    ({"videos": [], "hinweis": "Laura ist gerade nicht erreichbar."}, None),
    (None, marketing_pult.PultFehler("nicht_erreichbar", "TimeoutError")),
])
def test_bestellung_material_ohne_laura(angemeldet, pult, material, fehler):
    if material is not None:
        pult.material = material
    if fehler is not None:
        pult.fehler, pult.fehler_pfad = fehler, "/video/material"
    r = get(angemeldet, "/marketing/reels/neu?art=material")
    s = rumpf(r)
    assert r.status_code == 200 and '<p class="hinweis">' in s and "nicht erreichbar" in s
    assert ">Weiter</button>" in s and "sucht der Claw selbst" in s
    r = get(angemeldet, "/marketing/reels/neu?art=material&schritt=3")
    assert r.status_code == 200 and ">Bestellen</button>" in r.text
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "material", "titel": "T",
                                                  "thema": "t", "sprechertext": "s"})
    assert r.status_code == 303
    assert pult.posts()[-1][2]["briefing"]["videos"] == []


def test_kurzfassung_braucht_auswahl(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=kurzfassung"))
    assert '<input type="radio" name="video" value="a1b2c3d4-0000">' in s and 'type="checkbox"' not in s
    r = get(angemeldet, "/marketing/reels/neu?art=kurzfassung&schritt=3")
    assert r.status_code == 422 and "genau ein Video" in r.text
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "kurzfassung", "titel": "T",
                                                  "thema": "t"})
    assert r.status_code == 422 and "genau ein Video" in r.text and not pult.posts()
    pult.material = {"videos": [], "hinweis": "Laura ist gerade nicht erreichbar."}
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=kurzfassung"))
    assert "nicht erreichbar" in s and "Weiter" not in s


def test_schritt3_traegt_auswahl_versteckt_und_zeigt_stimme(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png&bild=buero.jpg&logo=logo.png")
    s = rumpf(r)
    assert r.status_code == 200
    assert '<form method="post" action="/marketing/reels/neu"' in s
    assert f'<input type="hidden" name="csrf" value="{ui._e(ui.CSRF_TOKEN)}">' in s
    for feld in ('name="art" value="bilder"', 'name="bild" value="team.png"', 'name="bild" value="buero.jpg"',
                 'name="logo" value="logo.png"'):
        assert f'<input type="hidden" {feld}>' in s, feld
    assert ('<a href="/marketing/reels/neu?art=bilder&amp;bild=team.png&amp;bild=buero.jpg&amp;logo=logo.png">'
            'Ändern</a>') in s
    assert "Stimme: <b>eigene-a</b> (aus der Marke)" in s
    assert 'name="sprechertext" rows="4" maxlength="900" required' in s
    assert 'name="stimme"' not in s and "farbe" not in s
    # ohne Markenstimme: Standard und der Weg zur Marke
    pult.markenstimme = None
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert ('Stimme: Standard – <a href="/marketing/layouts?reiter=profil">in der Marke festlegen</a>') in s
    # Kurzfassung: Sprechertext freiwillig, Video mit Namen aus Laura
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=kurzfassung&schritt=3&video=a1b2c3d4-0000"))
    assert '<input type="hidden" name="video" value="a1b2c3d4-0000">' in s and "Messe 2026 &lt;lang&gt;" in s
    assert 'name="sprechertext" rows="4" maxlength="900">' in s


def test_schritt3_markenstimme_gibt_es_nicht_mehr(angemeldet, pult):
    pult.markenstimme = "weg-<x>"
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert "Stimme: Standard (die Markenstimme „weg-&lt;x&gt;“ gibt es nicht mehr)" in s
    assert "(aus der Marke)" not in s
    # 'standard' steht nie in der Liste und gilt immer
    pult.markenstimme = "standard"
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert "gibt es nicht mehr" not in s
    # Liste nicht lesbar: wie bisher die Markenstimme zeigen, nichts behaupten
    pult.markenstimme, pult.stimmen = "weg", None
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert "Stimme: <b>weg</b> (aus der Marke)" in s
    pult.stimmen = ["eigene-a"]
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("nicht_erreichbar", "x"), "/stimmen"
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert "Stimme: <b>weg</b> (aus der Marke)" in s and ">Bestellen</button>" in s


def test_schritt3_api_marke_weg_bleibt_bestellbar(angemeldet, pult):
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("nicht_erreichbar", "x"), "/marke?"
    r = get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png")
    assert r.status_code == 200 and ">Bestellen</button>" in r.text and "Stimme:" in r.text


def test_bestellen_post_an_api_ohne_farben_und_stimme(angemeldet, pult):
    r = post(angemeldet, "/marketing/reels/neu", {
        "csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "bilder", "titel": "Herbst", "thema": "bAV", "sprechertext": "Drei.",
        "bild": ["team.png", "buero.jpg"], "logo": "logo.png", "dauer_s": "20", "stimme": "eigene-c",
        "farbe_hintergrund": "#000000"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{NEU}"
    (methode, pfad, daten), = pult.posts()
    assert (methode, pfad) == ("POST", "/video") and daten["mandant"] == "vibemind" and daten["art"] == "bilder"
    assert daten["titel"] == "Herbst"
    assert daten["briefing"] == {"thema": "bAV", "sprechertext": "Drei.", "hook": "", "dauer_s": 20,
                                 "bilder": ["team.png", "buero.jpg"], "logo": "logo.png"}


@pytest.mark.parametrize("daten", [{"art": "film", "titel": "T", "thema": "t"},
                                   {"art": "bilder", "titel": "", "thema": "t", "bild": "a.png"},
                                   {"art": "bilder", "titel": "T", "thema": "", "bild": "a.png"},
                                   {"art": "bilder", "titel": "T", "thema": "t"}])
def test_neu_prueft_vorher(angemeldet, pult, daten):
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", **daten})
    assert r.status_code == 422 and not pult.posts()


def test_api_ablehnung_zeigt_meldung(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Bild gehoert einer anderen Firma: x.png")
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "bilder", "titel": "T",
                                                  "thema": "t", "sprechertext": "s", "bild": "x.png"})
    assert r.status_code == 422 and "anderen Firma" in r.text
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Nur fertige oder fehlgeschlagene Reels lassen sich neu bauen")
    r = post(angemeldet, f"/marketing/reels/{AID_LAEUFT}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": "x"})
    assert r.status_code == 422 and "lassen sich neu bauen" in r.text


def test_kein_javascript(angemeldet, pult):
    for pfad in ("/marketing/reels", "/marketing/reels?reiter=archiv", f"/marketing/reels/{AID}",
                 f"/marketing/reels/{AID_FEHLER}", "/marketing/reels/neu", "/marketing/reels/neu?art=bilder",
                 "/marketing/reels/neu?art=material", "/marketing/reels/neu?art=kurzfassung",
                 "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"):
        r = get(angemeldet, pfad)
        assert r.status_code == 200, pfad
        assert "<script" not in r.text and "onclick" not in r.text, pfad
        assert "script-src" not in r.headers["content-security-policy"], pfad


def test_keine_verbotenen_staemme_in_den_reels_seiten(angemeldet, pult):
    """Wie test_darstellung: keine ASCII-Umschreibung in Texten, Klassen, Feldern und Pfaden (ohne den
    Firmen-Umschalter, dessen Feld `zurueck` allen Marketing-Seiten gemeinsam ist)."""
    from test_darstellung import WOERTER_ASCII
    for pfad in ("/marketing/reels", f"/marketing/reels/{AID}", f"/marketing/reels/{AID_FEHLER}",
                 f"/marketing/reels/{AID_ARCHIV}", f"/marketing/reels/{AID_LAEUFT}", "/marketing/reels/neu",
                 "/marketing/reels/neu?art=bilder", "/marketing/reels/neu?art=material",
                 "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"):
        s = rumpf(get(angemeldet, pfad)).replace('name="zurueck"', "")
        gefunden = [w for w in WOERTER_ASCII if w in s]
        assert not gefunden, (pfad, gefunden)


def test_alle_pult_aufrufe_im_threadpool(angemeldet, pult, monkeypatch):
    import asyncio
    im_loop = []
    alt = pult.anfrage

    def wache(*a, **k):
        try:
            asyncio.get_running_loop()
            im_loop.append(a[1])
        except RuntimeError:
            pass
        return alt(*a, **k)
    monkeypatch.setattr(marketing_pult, "anfrage", wache)
    for pfad in ("/marketing/reels", f"/marketing/reels/{AID}", "/marketing/reels/neu?art=bilder",
                 "/marketing/reels/neu?art=material", "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"):
        get(angemeldet, pfad)
    post(angemeldet, f"/marketing/reels/{AID}/nochmal", {"csrf": ui.CSRF_TOKEN, "wunsch": "x"})
    post(angemeldet, f"/marketing/reels/{AID}/archiv", {"csrf": ui.CSRF_TOKEN, "an": "1"})
    assert im_loop == []


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


# --- Review Task 5: Firma sichtbar und festgehalten, Auswahl bleibt, Kurzfassung roh geprueft ---------

@pytest.mark.parametrize("pfad", ["/marketing/reels/neu", "/marketing/reels/neu?art=bilder",
                                  "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"])
def test_bestellung_zeigt_die_firma(angemeldet, pult, pfad):
    s = rumpf(get(angemeldet, pfad))
    assert 'value="vibemind" aria-pressed="true"' in s and "Bestellung für <b>VibeMind</b>" in s


def test_bestellung_haelt_die_firma_fest(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    assert '<input type="hidden" name="mandant" value="vibemind">' in s
    basis = {"csrf": ui.CSRF_TOKEN, "art": "bilder", "titel": "T", "thema": "t", "sprechertext": "s",
             "bild": "team.png"}
    for daten in ({**basis, "mandant": "fin2gether"}, basis):
        r = post(angemeldet, "/marketing/reels/neu", daten)
        assert r.status_code == 422 and "Die Firma wurde inzwischen gewechselt – bitte neu bestellen." in r.text
    assert not pult.posts()
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    r = post(angemeldet, "/marketing/reels/neu", {**basis, "mandant": "fin2gether"})
    assert r.status_code == 303 and pult.posts()[-1][2]["mandant"] == "fin2gether"


def test_falscher_schritt3_behaelt_die_gueltige_auswahl(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png&bild=..%2Fx.png&logo=logo.png")
    s = rumpf(r)
    assert r.status_code == 422 and "Ungültige Auswahl" in s
    assert '<input type="checkbox" name="bild" value="team.png" checked>' in s and "../x" not in s
    assert '<option value="logo.png" selected>' in s
    r = get(angemeldet, "/marketing/reels/neu?art=kurzfassung&schritt=3&video=a1b2c3d4-0000&video=b2c3d4e5-0000")
    s = rumpf(r)
    assert r.status_code == 422 and s.count(" checked>") == 1
    assert '<input type="radio" name="video" value="a1b2c3d4-0000" checked>' in s


def test_kurzfassung_post_prueft_die_rohe_auswahl(angemeldet, pult):
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "kurzfassung",
                                                  "titel": "T", "thema": "t",
                                                  "video": ["a1b2c3d4-0000", "b2c3d4e5-0000"]})
    assert r.status_code == 422 and "genau ein Video" in r.text and not pult.posts()


# --- Formate (Stufe 2, E7) -------------------------------------------------------

def _format_reel(aid: str, fmt, titel: str) -> dict:
    briefing = {"thema": "t"}
    if fmt is not None:
        briefing["format"] = fmt
    return {"id": aid, "mandant": "vibemind", "titel": titel, "art": "bilder", "status": "fertig",
            "datei": f"vid-{aid[:8]}-x.mp4", "poster": f"vid-{aid[:8]}-x.jpg", "dauer_s": 20,
            "archiviert": False, "erstellt_am": "2026-10-20T08:00:00", "befund": "", "befund_text": "",
            "briefing": briefing, "protokoll": []}


AID_Q = "0a0a0a0a-4444-4444-4444-444444444444"
AID_W = "0b0b0b0b-4444-4444-4444-444444444444"
AID_X = "0c0c0c0c-4444-4444-4444-444444444444"


def _karte_von(s: str, aid: str) -> str:
    ort = s.index(f'href="/marketing/reels/{aid}"')
    teil = s[s.rindex("<a ", 0, ort):]
    return teil[:teil.index("</a>")]


def test_schritt3_drei_formate_hochformat_vorgabe(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder&schritt=3&bild=team.png"))
    reihe = re.findall(r'<input type="radio" name="format" value="(\w+)"( checked)?', s)
    assert reihe == [("reel", " checked"), ("quadrat", ""), ("quer", "")]
    for text in ("Hochformat 9:16 – Instagram, TikTok, Shorts", "Quadrat 1:1 – LinkedIn",
                 "Querformat 16:9 – Website, Präsentation"):
        assert text in s, text
    # Bestellschritt 3 bleibt: versteckte Auswahl und Stimmzeile
    assert '<input type="hidden" name="bild" value="team.png">' in s and "Stimme: <b>eigene-a</b>" in s
    assert s.index('name="dauer_s"') < s.index('name="format"') < s.index("Stimme:")


def test_bestellen_schickt_format_nur_wenn_nicht_hochformat(angemeldet, pult):
    basis = {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "bilder", "titel": "T", "thema": "t",
             "sprechertext": "x", "bild": ["team.png"]}
    for form, erwartet in (({}, None), ({"format": "reel"}, None), ({"format": "quadrat"}, "quadrat"),
                           ({"format": "quer"}, "quer")):
        pult.aufrufe.clear()
        r = post(angemeldet, "/marketing/reels/neu", {**basis, **form})
        assert r.status_code == 303, form
        (_, pfad, daten), = pult.posts()
        assert pfad == "/video"
        assert daten["briefing"].get("format") == erwartet and ("format" in daten["briefing"]) == (erwartet is not None)


def test_karte_und_detail_klasse_je_format(angemeldet, pult):
    pult.auftraege += [_format_reel(AID_Q, "quadrat", "Quadrat-Reel"), _format_reel(AID_W, "quer", "Quer-Reel")]
    s = rumpf(get(angemeldet, "/marketing/reels"))
    assert 'class="reel-karte f-quadrat"' in _karte_von(s, AID_Q)
    assert 'class="reel-karte f-quer"' in _karte_von(s, AID_W)
    assert 'class="reel-karte"' in _karte_von(s, AID)
    d = rumpf(get(angemeldet, f"/marketing/reels/{AID_W}"))
    assert 'class="reel-gross f-quer"' in d and "f-quadrat" not in d
    d = rumpf(get(angemeldet, f"/marketing/reels/{AID_Q}"))
    assert 'class="reel-gross f-quadrat"' in d and "f-quer" not in d
    d = rumpf(get(angemeldet, f"/marketing/reels/{AID}"))
    assert 'class="reel-gross"' in d and "f-quer" not in d and "f-quadrat" not in d
    # laufender Auftrag ohne Datei: die Fläche trägt die Klasse mit
    pult.auftraege.append({**_format_reel(AID_X, "quer", "Laeuft quer"), "status": "in_arbeit", "datei": ""})
    d = rumpf(get(angemeldet, f"/marketing/reels/{AID_X}"))
    assert 'class="reel-flaeche reel-gross f-quer"' in d
    # die Darstellung gibt es wirklich
    assert re.search(r"\.f-quadrat[^{]*\{[^}]*aspect-ratio: 1 / 1", ui._STIL)
    assert re.search(r"\.f-quer[^{]*\{[^}]*aspect-ratio: 16 / 9", ui._STIL)


@pytest.mark.parametrize("fmt", ["9:16", "<x>", "", None, 7, "QUER", ["quer"], {"a": 1}])
def test_karte_unbekanntes_format_faellt_auf_hochformat(angemeldet, pult, fmt):
    pult.auftraege.append(_format_reel(AID_X, fmt, "Komisch"))
    s = rumpf(get(angemeldet, "/marketing/reels"))
    karte = _karte_von(s, AID_X)
    assert 'class="reel-karte"' in karte and "f-quer" not in karte and "f-quadrat" not in karte
    d = rumpf(get(angemeldet, f"/marketing/reels/{AID_X}"))
    assert 'class="reel-gross"' in d and "f-quer" not in d and "f-quadrat" not in d
    assert "<x>" not in d and "<x>" not in s


def test_detail_zeigt_format(angemeldet, pult):
    pult.auftraege += [_format_reel(AID_Q, "quadrat", "Q"), _format_reel(AID_W, "quer", "W"),
                       _format_reel(AID_X, "<x>", "X")]
    assert "<dt>Format</dt><dd>Quadrat 1:1 – LinkedIn</dd>" in rumpf(get(angemeldet, f"/marketing/reels/{AID_Q}"))
    assert "<dt>Format</dt><dd>Querformat 16:9 – Website, Präsentation</dd>" in rumpf(
        get(angemeldet, f"/marketing/reels/{AID_W}"))
    assert "<dt>Format</dt><dd>Hochformat 9:16 – Instagram, TikTok, Shorts</dd>" in rumpf(
        get(angemeldet, f"/marketing/reels/{AID}"))
    assert "<dt>Format</dt><dd>Hochformat 9:16" in rumpf(get(angemeldet, f"/marketing/reels/{AID_X}"))


def test_klassen_laesst_leere_teile_weg():
    assert ui_reels.klassen("a", "", "b c") == "a b c" and ui_reels.klassen("", "") == ""


@pytest.mark.parametrize("fmt", ["<x>", "9:16"])
def test_fremdes_format_beim_bestellen_zeigt_api_422_escaped(angemeldet, pult, fmt):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "format: reel, quadrat oder quer <b>" + fmt)
    pult.fehler_pfad = "/video"
    r = post(angemeldet, "/marketing/reels/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "bilder",
                                                  "titel": "T", "thema": "t", "sprechertext": "s", "bild": "x.png",
                                                  "format": fmt})
    assert r.status_code == 422 and "format: reel, quadrat oder quer" in r.text and "<b>" not in r.text
    (_, _, daten), = pult.posts()
    assert daten["briefing"]["format"] == fmt           # die Seite erfindet nichts, die API entscheidet


def test_quer_detail_stil_hat_schmalen_pfad():
    """Zwischen Handy und breitem Schirm darf die Textspalte nicht auf null schrumpfen."""
    assert re.search(r"\.reel-detail\.f-quer \{ grid-template-columns: minmax\(0, 3fr\) minmax\(16rem, 2fr\)", ui._STIL)
    assert re.search(r"max-width: 1099px\) \{\s*\.reel-detail\.f-quer \{ grid-template-columns: minmax\(0, 1fr\)", ui._STIL)


# --- KI-Bilder (Stufe 3, E7) ------------------------------------------------------

AID_KI = "0d0d0d0d-5555-5555-5555-555555555555"
KI_B = ["b1b1b1b1-5555-5555-5555-555555555555", "b2b2b2b2-5555-5555-5555-555555555555",
        "b3b3b3b3-5555-5555-5555-555555555555", "b4b4b4b4-5555-5555-5555-555555555555"]
FREMDES_BILD = "f0f0f0f0-5555-5555-5555-555555555555"


def _ki_bild(i: int, status: str, versuch: int = 1) -> dict:
    nr = i + 1
    return {"id": KI_B[i], "nr": nr, "idee": f"Idee {nr}: Team am Tisch <b>", "status": status,
            "datei": f"ki-0d0d0d0d-{nr}-{versuch}.jpg" if status == "fertig" else None,
            "befund": "FLUX.2: Zeitlimit" if status == "fehler" else ""}


def _ki_auftrag(status: str, bilder: list[dict], fmt: str | None = None, aid: str = AID_KI) -> dict:
    briefing = {"thema": "bAV", "sprechertext": "Drei.", "ki": {"anzahl": 4}}
    if fmt:
        briefing["format"] = fmt
    return {"id": aid, "mandant": "vibemind", "titel": "KI-Reel", "art": "bilder", "status": status,
            "archiviert": False, "erstellt_am": "2026-10-23T08:00:00", "befund": "", "befund_text": "",
            "briefing": briefing, "protokoll": [], "ki_bilder": bilder}


def _pruefen(fmt: str | None = "quer") -> dict:
    return _ki_auftrag("bilder_pruefen", [_ki_bild(0, "fertig"), _ki_bild(1, "fehler"),
                                          _ki_bild(2, "fertig", 2), _ki_bild(3, "fertig")], fmt)


def test_schritt1_hat_ki_karte(angemeldet, pult):
    s = rumpf(get(angemeldet, "/marketing/reels/neu"))
    karte = s[s.index('href="/marketing/reels/neu?art=ki"'):]
    karte = karte[:karte.index("</a>")]
    assert "<b>Aus KI-Bildern</b>" in karte and "Ich entwerfe 3 bis 5 Bilder im Bildstil deiner Marke." in karte


def test_schritt2_ki_anzahl_vorgabe_vier(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu?art=ki")
    s = rumpf(r)
    assert r.status_code == 200
    reihe = re.findall(r'<input type="radio" name="anzahl" value="(\d)"( checked)?', s)
    assert reihe == [("3", ""), ("4", " checked"), ("5", "")]
    assert "dauert etwa 2 Minuten je Bild" in s
    assert '<input type="hidden" name="art" value="ki">' in s and '<input type="hidden" name="schritt" value="3">' in s
    assert not [a for a in pult.aufrufe if a[1].startswith("/video")]       # keine Medien, kein Laura
    # zurueck aus Schritt 3: die gewaehlte Zahl bleibt
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=ki&anzahl=5"))
    assert '<input type="radio" name="anzahl" value="5" checked>' in s
    # Schritt 3: Zahl versteckt, Auswahl als Satz, Format und Stimme wie bisher
    r = get(angemeldet, "/marketing/reels/neu?art=ki&schritt=3&anzahl=3")
    s = rumpf(r)
    assert r.status_code == 200 and '<input type="hidden" name="anzahl" value="3">' in s
    assert "3 KI-Bilder im Bildstil deiner Marke" in s and 'name="format"' in s and "Stimme:" in s
    assert '<a href="/marketing/reels/neu?art=ki&amp;anzahl=3">' in s
    assert 'name="sprechertext" rows="4" maxlength="900" required' in s
    # unsinnige Zahl: zurueck zu Schritt 2 mit Vorgabe
    for roh in ("7", "x", ""):
        r = get(angemeldet, f"/marketing/reels/neu?art=ki&schritt=3&anzahl={roh}")
        assert r.status_code == 422 and "Wähle 3, 4 oder 5 Bilder." in r.text, roh
        assert '<input type="radio" name="anzahl" value="4" checked>' in rumpf(r)


def test_bestellen_ki_sendet_anzahl_ohne_bilder(angemeldet, pult):
    basis = {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "art": "ki", "titel": "KI", "thema": "bAV",
             "sprechertext": "Drei.", "dauer_s": "20"}
    r = post(angemeldet, "/marketing/reels/neu", {**basis, "anzahl": "5", "format": "quer",
                                                   "bild": "team.png", "logo": "logo.png"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{NEU}"
    (methode, pfad, daten), = pult.posts()
    assert (methode, pfad) == ("POST", "/video")
    assert daten == {"mandant": "vibemind", "art": "bilder", "titel": "KI",
                     "briefing": {"thema": "bAV", "sprechertext": "Drei.", "hook": "", "dauer_s": 20,
                                  "format": "quer", "ki": {"anzahl": 5}}}
    pult.aufrufe.clear()
    for roh in ("2", "6", "x", ""):
        r = post(angemeldet, "/marketing/reels/neu", {**basis, "anzahl": roh})
        assert r.status_code == 422 and "Wähle 3, 4 oder 5 Bilder." in r.text, roh
    r = post(angemeldet, "/marketing/reels/neu", {**basis, "anzahl": "4", "mandant": "fin2gether"})
    assert r.status_code == 422 and "Die Firma wurde inzwischen gewechselt" in r.text
    assert not pult.posts()


def test_detail_status_texte_ki(angemeldet, pult):
    pult.auftraege.append(_ki_auftrag("ideen", []))
    r = get(angemeldet, f"/marketing/reels/{AID_KI}")
    s = rumpf(r)
    assert "Bildideen werden geschrieben" in s and 'http-equiv="refresh"' in r.text
    assert "<dt>Art</dt><dd>Aus KI-Bildern</dd>" in s
    assert f'action="/marketing/reels/{AID_KI}/abbrechen"' in s
    pult.auftraege[-1] = _ki_auftrag("bilder_laufen", [_ki_bild(0, "fertig"), _ki_bild(1, "fehler"),
                                                       _ki_bild(2, "in_arbeit"), _ki_bild(3, "offen")])
    r = get(angemeldet, f"/marketing/reels/{AID_KI}")
    s = rumpf(r)
    assert "Bilder entstehen (2 von 4)" in s and 'http-equiv="refresh"' in r.text
    assert "/ki/neu" not in s and "/ki/bauen" not in s          # waehrend der Erzeugung nur ansehen
    assert '<img src="/medien/datei/ki-0d0d0d0d-1-1.jpg"' in s
    pult.auftraege[-1] = _pruefen()
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert '<span class="chip bereich">Bilder prüfen</span>' in s
    assert f'action="/marketing/reels/{AID_KI}/abbrechen"' in s


def test_pruefen_raster_im_format_mit_neu_und_bauen(angemeldet, pult):
    pult.auftraege.append(_pruefen("quer"))
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert '<div class="ki-raster f-quer">' in s
    for nr, versuch in ((1, 1), (3, 2), (4, 1)):
        assert f'<img src="/medien/datei/ki-0d0d0d0d-{nr}-{versuch}.jpg" alt="Bild {nr}" loading="lazy">' in s
    assert s.count("<img ") == 3
    # die Idee ausklappbar und escaped, der Fehlschlag mit Befund
    assert "<details><summary>Idee</summary><p>Idee 1: Team am Tisch &lt;b&gt;</p></details>" in s
    assert "Fehlgeschlagen: FLUX.2: Zeitlimit" in s
    # Neu erzeugen je Bild (auch beim fehlgeschlagenen), mit CSRF, Firma und optionaler Idee
    for bid in KI_B:
        form = s[s.rindex("<form ", 0, s.index(f'<input type="hidden" name="bild" value="{bid}">')):]
        form = form[:form.index("</form>")]
        assert f'<form method="post" action="/marketing/reels/{AID_KI}/ki/neu"' in form
        assert f'<input type="hidden" name="csrf" value="{ui._e(ui.CSRF_TOKEN)}">' in form
        assert '<input type="hidden" name="mandant" value="vibemind">' in form
        assert '<input type="text" name="idee" maxlength="600"' in form and "required" not in form
        assert ">Neu erzeugen</button>" in form
    assert "andere Idee" in s
    # ein Knopf Reel bauen mit CSRF und Firma; nur die drei fertigen gehen hinein
    bauen = s[s.index(f'action="/marketing/reels/{AID_KI}/ki/bauen"'):]
    bauen = bauen[:bauen.index("</form>")]
    assert f'name="csrf" value="{ui._e(ui.CSRF_TOKEN)}"' in bauen and 'name="mandant" value="vibemind"' in bauen
    assert '<button class="primaer" type="submit">Reel bauen</button>' in bauen
    assert "3 fertigen Bildern" in s
    # Hochformat: Raster ohne Formatklasse
    pult.auftraege[-1] = _pruefen(None)
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert '<div class="ki-raster">' in s


def test_kein_refresh_bei_bilder_pruefen(angemeldet, pult):
    pult.auftraege = [_pruefen()]
    assert 'http-equiv="refresh"' not in get(angemeldet, f"/marketing/reels/{AID_KI}").text
    assert 'http-equiv="refresh"' not in get(angemeldet, "/marketing/reels").text
    pult.auftraege = [_ki_auftrag("bilder_laufen", [_ki_bild(0, "in_arbeit")])]
    assert 'http-equiv="refresh"' in get(angemeldet, "/marketing/reels").text


def test_neu_erzeugen_post(angemeldet, pult):
    pult.auftraege.append(_pruefen())
    pfad = f"/marketing/reels/{AID_KI}/ki/neu"
    basis = {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "bild": KI_B[1]}
    r = post(angemeldet, pfad, {**basis, "idee": "  Team draußen  "})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}"
    assert pult.posts() == [("POST", f"/video/{AID_KI}/ki/neu",
                             {"bild": KI_B[1], "mandant": "vibemind", "idee": "Team draußen"})]
    r = post(angemeldet, pfad, basis)                       # ohne andere Idee: dieselbe
    assert r.status_code == 303 and pult.posts()[-1][2] == {"bild": KI_B[1], "mandant": "vibemind", "idee": ""}
    pult.aufrufe.clear()
    assert post(angemeldet, pfad, {"mandant": "vibemind", "bild": KI_B[1]}).status_code == 403
    assert not pult.aufrufe
    r = post(angemeldet, pfad, {**basis, "idee": "x" * 601})
    assert r.status_code == 422 and "höchstens 600 Zeichen" in r.text
    r = post(angemeldet, pfad, {**basis, "mandant": "fin2gether"})
    assert r.status_code == 422 and "Die Firma wurde inzwischen gewechselt" in r.text
    assert not pult.posts()
    # nur waehrend der Pruefung; sonst (Doppelklick, alter Tab) zurueck zur Detailseite statt Fehlerseite
    for status in ("bilder_laufen", "offen", "fertig", "abgebrochen"):
        pult.auftraege[-1] = _ki_auftrag(status, [_ki_bild(i, "fertig") for i in range(4)])
        r = post(angemeldet, pfad, basis)
        assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}", status
    # der Status zaehlt vor der Bild-Zugehoerigkeit: nach dem Bau ist das Bild ggf. weg
    pult.auftraege[-1] = _ki_auftrag("offen", [])
    r = post(angemeldet, pfad, basis)
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}"
    assert not pult.posts()
    # die Ablehnung der API kommt als Meldung an
    pult.auftraege[-1] = _pruefen()
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("abgelehnt", "Bild ist nicht fertig <x>"), "/ki/neu"
    r = post(angemeldet, pfad, basis)
    assert r.status_code == 422 and "Bild ist nicht fertig &lt;x&gt;" in r.text


def test_reel_bauen_post(angemeldet, pult):
    pult.auftraege.append(_pruefen())
    pfad = f"/marketing/reels/{AID_KI}/ki/bauen"
    r = post(angemeldet, pfad, {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}"
    assert pult.posts() == [("POST", f"/video/{AID_KI}/ki/freigeben", {"mandant": "vibemind"})]
    pult.aufrufe.clear()
    assert post(angemeldet, pfad, {"mandant": "vibemind"}).status_code == 403 and not pult.aufrufe
    r = post(angemeldet, pfad, {"csrf": ui.CSRF_TOKEN, "mandant": "fin2gether"})
    assert r.status_code == 422 and "Die Firma wurde inzwischen gewechselt" in r.text and not pult.posts()


@pytest.mark.parametrize("status", ["offen", "in_arbeit", "fertig", "abgebrochen", "bilder_laufen", "ideen"])
def test_reel_bauen_doppelt_fuehrt_zur_detailseite(angemeldet, pult, status):
    """Zweiter Klick / alter Tab: der Auftrag ist nicht mehr bei der Pruefung -> 303 statt Fehlerseite."""
    pult.auftraege.append({**_pruefen(), "status": status})
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/bauen", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}"
    assert not pult.posts()


def test_neu_erzeugen_verworfenes_bild_fuehrt_zur_detailseite(angemeldet, pult):
    """Das Bild wurde schon neu erzeugt (alte Kennung verworfen, alter Tab): 303 ohne API-Aufruf."""
    pult.auftraege.append(_pruefen())
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/neu",
             {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "bild": FREMDES_BILD})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/reels/{AID_KI}"
    assert not pult.posts()


def test_fertige_ki_bilder_eine_regel():
    a = _ki_auftrag("bilder_pruefen", [_ki_bild(0, "fertig"), _ki_bild(1, "fehler"),
                                       {**_ki_bild(2, "fertig"), "datei": "../x.jpg"}, _ki_bild(3, "in_arbeit")])
    assert [b["id"] for b in ui_reels.fertige_ki_bilder(a)] == [KI_B[0]]


def test_reel_bauen_ohne_gueltige_datei_422(angemeldet, pult):
    """fertig, aber ohne gueltigen Dateinamen zaehlt nicht - wie auf der Seite (kein Knopf)."""
    pult.auftraege.append(_ki_auftrag("bilder_pruefen", [{**_ki_bild(0, "fertig"), "datei": None}]))
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert "/ki/bauen" not in s
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/bauen", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert r.status_code == 422 and not pult.posts()


@pytest.mark.parametrize("status, klein", [("ideen", True), ("bilder_laufen", True), ("bilder_pruefen", True),
                                           ("offen", False), ("fertig", False)])
def test_ki_vorstufe_markiert_detail_fuer_handy(angemeldet, pult, status, klein):
    pult.auftraege.append({**_pruefen(), "status": status})
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert ('class="reel-detail f-quer ki-vorstufe"' in s) is klein
    css = get(angemeldet, f"/marketing/reels/{AID_KI}").text
    assert ".reel-detail.ki-vorstufe > .reel-bild { display: none; }" in css


def test_aus_bildern_zeigt_keine_ki_bilder(angemeldet, pult):
    pult.bilder = [{"name": "team.png"}, {"name": "ki-0d0d0d0d-1-1.jpg"}, {"name": "ki-0d0d0d0d-2-3.jpg"}]
    s = rumpf(get(angemeldet, "/marketing/reels/neu?art=bilder"))
    assert "team.png" in s and "ki-0d0d0d0d" not in s


def test_bauen_nur_mit_fertigem_bild(angemeldet, pult):
    pult.auftraege.append(_ki_auftrag("bilder_pruefen", [_ki_bild(i, "fehler") for i in range(4)]))
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert "/ki/bauen" not in s and "Reel bauen" not in s
    assert "Noch kein Bild ist fertig" in s and s.count(">Neu erzeugen</button>") == 4
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/bauen", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert r.status_code == 422 and "mindestens ein Bild fertig" in r.text and not pult.posts()
    # Die API hat das letzte Wort: lehnt sie ab (ok false), kommt keine Erfolgsmeldung
    pult.auftraege[-1] = _pruefen()
    pult.freigabe_ok = False
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/bauen", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert r.status_code == 422 and "mindestens ein Bild fertig" in r.text


def test_galerie_chip_bilder_pruefen(angemeldet, pult):
    pult.auftraege = [_ki_auftrag("ideen", [], aid=AID_Q), _ki_auftrag("bilder_laufen", [], aid=AID_W),
                      _pruefen()]
    s = rumpf(get(angemeldet, "/marketing/reels?reiter=arbeit"))
    assert '<a href="/marketing/reels?reiter=arbeit" aria-current="page">In Arbeit <span class="zahl">3</span></a>' in s
    assert '<span class="chip bereich">Bilder prüfen</span>' in _karte_von(s, AID_KI)
    assert 'class="reel-karte f-quer"' in _karte_von(s, AID_KI)
    assert "Bildideen werden geschrieben" in _karte_von(s, AID_Q)
    assert "Bilder entstehen" in _karte_von(s, AID_W)


def test_fremdes_bild_404(angemeldet, pult):
    pult.auftraege.append(_pruefen())
    # eine kaputte Kennung: 404 ohne Auftrag an die API (ein fremdes, gueltiges Bild -> 303, s. verworfen)
    for bild in ("../x", ""):
        r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/neu",
                 {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "bild": bild})
        assert r.status_code == 404, bild
    # ein Auftrag einer anderen Firma: 404 auf beiden Wegen
    for pfad, daten in ((f"/marketing/reels/{AID_FREMD}/ki/neu", {"bild": KI_B[0]}),
                        (f"/marketing/reels/{AID_FREMD}/ki/bauen", {})):
        r = post(angemeldet, pfad, {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", **daten})
        assert r.status_code == 404 and "Fremd-Reel" not in r.text, pfad
    assert not pult.posts()
    # die API sieht es anders (404 = abgelehnt): Meldung statt Erfolg
    pult.fehler, pult.fehler_pfad = marketing_pult.PultFehler("abgelehnt", "Unbekanntes Bild"), "/ki/"
    r = post(angemeldet, f"/marketing/reels/{AID_KI}/ki/neu",
             {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "bild": KI_B[0]})
    assert r.status_code == 422 and "Unbekanntes Bild" in r.text


def test_ki_seiten_ohne_javascript_und_ohne_verbotene_staemme(angemeldet, pult):
    from test_darstellung import WOERTER_ASCII
    pult.auftraege += [_pruefen(), _ki_auftrag("ideen", [], aid=AID_Q)]
    for pfad in ("/marketing/reels?reiter=arbeit", f"/marketing/reels/{AID_KI}", f"/marketing/reels/{AID_Q}",
                 "/marketing/reels/neu", "/marketing/reels/neu?art=ki",
                 "/marketing/reels/neu?art=ki&schritt=3&anzahl=4"):
        r = get(angemeldet, pfad)
        assert r.status_code == 200, pfad
        assert "<script" not in r.text and "onclick" not in r.text, pfad
        s = rumpf(r).replace('name="zurueck"', "")
        gefunden = [w for w in WOERTER_ASCII if w in s]
        assert not gefunden, (pfad, gefunden)


def test_ki_aufrufe_im_threadpool(angemeldet, pult, monkeypatch):
    import asyncio
    pult.auftraege.append(_pruefen())
    im_loop = []
    alt = pult.anfrage

    def wache(*a, **k):
        try:
            asyncio.get_running_loop()
            im_loop.append(a[1])
        except RuntimeError:
            pass
        return alt(*a, **k)
    monkeypatch.setattr(marketing_pult, "anfrage", wache)
    get(angemeldet, f"/marketing/reels/{AID_KI}")
    post(angemeldet, f"/marketing/reels/{AID_KI}/ki/neu", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind", "bild": KI_B[0]})
    post(angemeldet, f"/marketing/reels/{AID_KI}/ki/bauen", {"csrf": ui.CSRF_TOKEN, "mandant": "vibemind"})
    assert im_loop == []


def test_nochmal_bei_ki_reel_nennt_dieselben_bilder(angemeldet, pult):
    fertig = {**_pruefen(), "status": "fertig", "datei": "vid-0d0d0d0d-ki.mp4"}
    pult.auftraege.append(fertig)
    s = rumpf(get(angemeldet, f"/marketing/reels/{AID_KI}"))
    assert "Nochmal mit Änderung" in s and "Für neue KI-Bilder bestelle ein neues Reel." in s
    assert "/ki/neu" not in s and "/ki/bauen" not in s


def test_medien_karte_markiert_ki_bilder():
    karte = ui._medien_karte("ki-0d0d0d0d-2-3.jpg", 2048, {"herkunft": "system", "bot_darf_senden": True}, {}, "")
    assert "KI-Bild eines Reels" in karte and "nicht im Anhang" in karte
    andere = ui._medien_karte("team.png", 2048, {"herkunft": "hochgeladen", "bot_darf_senden": True}, {}, "")
    assert "KI-Bild" not in andere
