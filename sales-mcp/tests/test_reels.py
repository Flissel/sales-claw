"""Reels im Marketing-Pult (17.10.2026, Video-Claw; Reels Stufe 1 21.10.2026: Galerie, Detailseite,
gefuehrte Bestellung, Herunterladen). Der Client zur Marketing-API wird gefaelscht."""
import json
import os
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
        self.archiv_ok = True

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
        if pfad == "/video":
            return {"auftrag": NEU}
        if pfad.endswith("/nochmal"):
            return {"auftrag": NEU}
        if pfad.endswith("/archivieren"):
            return {"ok": self.archiv_ok}
        if pfad.endswith("/abbrechen"):
            return {"status": "abgebrochen"}
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

def test_bestellung_schritt1_drei_karten(angemeldet, pult):
    r = get(angemeldet, "/marketing/reels/neu")
    s = rumpf(r)
    assert r.status_code == 200
    for art, name in (("bilder", "Aus Bildern"), ("material", "Aus Videomaterial"),
                      ("kurzfassung", "Kurzfassung eines Videos")):
        assert f'<a class="reel-art" href="/marketing/reels/neu?art={art}"><b>{name}</b>' in s
    assert s.count('<a class="reel-art"') == 3
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
