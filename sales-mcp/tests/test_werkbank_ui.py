"""Video-Werkbank im Pult (Task 10): Szenenseite, Uebersicht, Videoseite, Aktionen und die Datei-Route mit
Range. Die Marketing-API (`marketing_pult.anfrage`) und das Auftragsbuch (`auftrag_buch.eigene`) sind
gefaelscht; die Dateien liegen in `tmp_path` als Erzeugt-Ordner."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import auftrag_buch  # noqa: E402
import marketing_pult  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_werkbank  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
AID = "0123abcd-4444-4444-4444-444444444444"
AID_FREMD = "99998888-4444-4444-4444-444444444444"
K = "wb-abcdefghij"
K_ALT = "wb-zzzzzzzzzz"
NAME = "wb-0123abcd-s03-f1.mp4"
NAME_VIDEO = "wb-0123abcd-video-f1.mp4"
NAME_FREMD = "wb-99998888-s01-f0.mp4"
MB = 1024 * 1024


def _szene(nr=3, stand="clip_wartet", **mehr):
    s = {"nr": nr, "stufe": "Problem", "kurz": "Drei Fehler", "sprechtext": "Viele machen drei Fehler.",
         "bildart": "slide", "uebergang": "blende", "stand": stand, "wunsch": None, "wuensche": [
             {"text": "etwas kürzer", "zeit": "2026-11-11T10:00:00", "tor": "text"}],
         "bild": {"schritte": [{"vorlage": "titel", "text": "Drei Fehler"}, {"vorlage": "stichpunkte",
                                                                        "punkte": ["Kosten", "Frist"]}]},
         "quellen": ["Marke.md", {"name": "Preise.pdf", "stelle": "S. 2"}], "clip_datei": NAME,
         "dauer_s": 24.5, "fehler": None}
    s.update(mehr)
    return s


def _werk():
    return {"auftrag": AID, "mandant": "vibemind", "gliederung_stand": "text_wartet", "gliederung_wunsch": None,
            "gliederung": {"titel": "Betriebliche Altersvorsorge", "hook": "Wusstest du?",
                           "stufen": [{"name": "Problem", "szenen": [
                               {"kurz": "Drei Fehler", "quellen": ["Marke.md"]}, "Die Kosten"]}],
                           "fehlt": ["Zahlen zur Förderung"]},
            "quellen": ["Marke.md", "Preise.pdf"],
            "szenen": [_szene(1, "fertig"), _szene(2, "text_wartet"), _szene(3), _szene(4, "geplant", fehler="kaputt")],
            "alle_fertig": False, "video_fassung": 0}


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None            # PultFehler fuer alle POSTs
        self.szene = _szene()
        self.kennung = K
        self.vorschlag = {"auftrag": AID, "tor": "clip", "nr": 3, "mandant": "vibemind", "aktuell": True}
        self.werk = _werk()
        self.gliederung_kennung = "fehlt"      # "fehlt" = Schluessel fehlt in der Antwort (aeltere API)
        self.ok_false = False                  # POST antwortet 200 mit {"ok": false}

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        if methode == "POST":
            if self.fehler:
                raise self.fehler
            return {"ok": not self.ok_false}
        if pfad.startswith(f"/werkbank/{AID_FREMD}"):
            raise marketing_pult.PultFehler("abgelehnt", "Unbekannter Auftrag")
        if pfad.startswith(f"/werkbank/v/{K}"):
            return self.vorschlag
        if pfad.startswith("/werkbank/v/"):
            raise marketing_pult.PultFehler("abgelehnt", "Unbekannter Vorschlag")
        if pfad.startswith(f"/werkbank/{AID}/szene/"):
            return {"szene": self.szene, "kennung": self.kennung}
        if pfad.startswith(f"/werkbank/{AID}?"):
            antwort = {"werk": self.werk, "stand": "werkbank", "werkbank": {}}
            if self.gliederung_kennung != "fehlt":
                antwort["gliederung_kennung"] = self.gliederung_kennung
            return antwort
        raise AssertionError(pfad)

    def posts(self):
        return [a for a in self.aufrufe if a[0] == "POST"]


@pytest.fixture
def pult(monkeypatch, tmp_path):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    monkeypatch.setenv("MARKETING_MANDANT", "vibemind")
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(tmp_path))
    ui_werkbank._auftrag_cache.clear()
    f.buch = [
        {"id": AID, "art": "video", "mandant": "vibemind", "stand": "werkbank", "angelegt": "2026-11-11T09:00:00",
         "eingabe": {"thema": "Altersvorsorge <kurz>"}, "ergebnis": {"werkbank": {"wartet": 2},
            "datei": NAME_VIDEO, "bytes": 90_000_000, "dauer_s": 245, "titel": "Altersvorsorge <einfach>",
            "beschreibung": "Drei Fehler und wie du sie vermeidest.",
            "zeitmarken": [{"zeit": "0:00", "name": "Einstieg"}, {"zeit": "0:42", "name": "Problem"}],
            "messnotiz": "Messung: Lautheit -14 LUFS", "warnungen": ["Szene 4 ist kurz <b>"], "ki_hinweis": True}},
        {"id": AID_FREMD, "art": "video", "mandant": "fin2gether", "stand": "werkbank", "ergebnis": {}},
        {"id": "55556666-4444-4444-4444-444444444444", "art": "reel", "mandant": "vibemind", "stand": "fertig",
         "ergebnis": {}}]
    def eigene(q, laden, staende):
        f.buch_staende.append(list(staende))
        return list(f.buch)
    f.buch_staende = []
    monkeypatch.setattr(auftrag_buch, "eigene", eigene)
    return f


@pytest.fixture
def datei_1mb(tmp_path):
    inhalt = bytes(range(256)) * (MB // 256)
    (tmp_path / NAME).write_bytes(inhalt)
    return inhalt


def _anmelden(rolle):
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               headers=HOST, follow_redirects=False)
    assert r.status_code == 303
    return c, vorher


def _db():
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus - Seitentests brauchen die Anmeldung")


@pytest.fixture
def klient(pult):
    _db()
    c, vorher = _anmelden("freigeben")
    yield c
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def leser(pult):
    _db()
    c, vorher = _anmelden("lesen")
    yield c
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def anonym(pult):
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    _db()
    yield TestClient(ui.app)
    ui.UI_SESSION_SECRET = vorher


def get(c, pfad, **kw):
    return c.get(pfad, headers={**HOST, **kw.pop("headers", {})}, follow_redirects=False, **kw)


def post(c, pfad, daten, csrf=True):
    if csrf:
        daten = {"csrf": ui.CSRF_TOKEN, **daten}
    return c.post(pfad, headers=HOST, follow_redirects=False, data=daten)


def rumpf(r):
    return r.text[r.text.index("<main"):]


# --- reine Teile ---------------------------------------------------------------

def test_bereich():
    assert ui_werkbank.bereich("bytes=0-99", 1000) == (0, 99) and ui_werkbank.bereich("bytes=900-", 1000) == (900, 999)
    assert ui_werkbank.bereich("bytes=-100", 1000) == (900, 999) and ui_werkbank.bereich("bytes=5000-", 1000) is None


@pytest.mark.parametrize("kopf", [None, "", "bytes=", "bytes=-", "bytes=9-3", "bytes=0-1,5-6", "items=0-5", "bytes=a-b",
                                  "bytes=-0", "bytes=1000-1001"])
def test_bereich_unsinn(kopf):
    assert ui_werkbank.bereich(kopf, 1000) is None


def test_bereich_ende_wird_gekappt_und_suffix_groesser_als_datei():
    assert ui_werkbank.bereich("bytes=990-5000", 1000) == (990, 999)
    assert ui_werkbank.bereich("bytes=-5000", 1000) == (0, 999)
    assert ui_werkbank.bereich("bytes=0-0", 0) is None


def test_werkbankdatei_ist_kein_medium():
    assert medien.verborgen("wb-0123abcd-s03-f1.mp4") and medien.verborgen(NAME_VIDEO)
    assert medien.verborgen("wb-0123abcd-s100-f12.mp4")
    for name in ("wb-0123abcd-s3-f1.mp4", "wb-0123abcd-s03-f1.mov", "wb-0123ABCD-s03-f1.mp4", "wb-0123abcd-x-f1.mp4"):
        assert not medien.werkbankdatei(name)
    assert medien.pruefe_anhang(NAME)[0] is None


# --- Datei-Route ----------------------------------------------------------------

def test_datei_ganz_mit_accept_ranges(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}")
    assert r.status_code == 200 and r.content == datei_1mb
    assert r.headers["Accept-Ranges"] == "bytes" and r.headers["Content-Length"] == str(MB)
    assert r.headers["Cache-Control"] == "private, max-age=60" and r.headers["Content-Type"] == "video/mp4"


def test_datei_range_liefert_206_und_nur_den_ausschnitt(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and len(r.content) == 10 and r.content == datei_1mb[10:20]
    assert r.headers["Content-Range"] == f"bytes 10-19/{MB}"


def test_datei_range_ueber_stueckgrenze(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": f"bytes={MB - 300}-"})
    assert r.status_code == 206 and r.content == datei_1mb[-300:]
    r = get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": "bytes=-5"})
    assert r.content == datei_1mb[-5:] and r.headers["Content-Range"] == f"bytes {MB - 5}-{MB - 1}/{MB}"


def test_datei_range_unsinn_416(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": f"bytes={MB}-"})
    assert r.status_code == 416 and r.headers["Content-Range"] == f"bytes */{MB}"


def test_datei_laden_ist_anhang(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}?laden=1")
    assert r.headers["Content-Disposition"] == f'attachment; filename="{NAME}"'


def test_datei_streamt_in_stuecken_nie_ganz(klient, datei_1mb, monkeypatch):
    gelesen = []
    echt = os.read

    def lesen(fd, n):
        gelesen.append(n)
        return echt(fd, n)
    monkeypatch.setattr(ui_werkbank.os, "read", lesen)
    monkeypatch.setattr(ui_werkbank, "STUECK", 100_000)
    r = get(klient, f"/marketing/werkbank/datei/{NAME}")
    assert r.content == datei_1mb and max(gelesen) <= 100_000 and len(gelesen) >= 10


def test_datei_fremder_firma_404(klient, tmp_path):
    (tmp_path / NAME_FREMD).write_bytes(b"x" * 100)
    assert get(klient, f"/marketing/werkbank/datei/{NAME_FREMD}").status_code == 404


def test_datei_unbekannter_auftrag_404(klient, tmp_path):
    name = "wb-deadbeef-s01-f0.mp4"
    (tmp_path / name).write_bytes(b"x" * 100)
    assert get(klient, f"/marketing/werkbank/datei/{name}").status_code == 404


def test_datei_api_kennt_auftrag_nicht_404(klient, pult, datei_1mb, monkeypatch):
    def nein(methode, pfad, daten=None, roh=False, zeitlimit=None):
        raise marketing_pult.PultFehler("abgelehnt", "Unbekannter Auftrag")
    monkeypatch.setattr(marketing_pult, "anfrage", nein)
    assert get(klient, f"/marketing/werkbank/datei/{NAME}").status_code == 404


@pytest.mark.parametrize("name", ["vid-0123abcd-herbst.mp4", "wb-0123abcd.mp4", "wb-0123abcd-s03-f1.mp4.teil",
                                  "wb-0123abcd-s03-f1.MP4", "..%2Fwb-0123abcd-s03-f1.mp4", "wb-0123abcd-s3-f1.mp4"])
def test_datei_falscher_name_404(klient, datei_1mb, name):
    assert get(klient, f"/marketing/werkbank/datei/{name}").status_code == 404


def test_datei_fehlt_im_ordner_404(klient):
    assert get(klient, f"/marketing/werkbank/datei/{NAME}").status_code == 404


def test_datei_symlink_wird_nicht_gefolgt(klient, tmp_path):
    ziel = tmp_path / "geheim.bin"
    ziel.write_bytes(b"geheim" * 100)
    os.symlink(ziel, tmp_path / NAME)
    assert get(klient, f"/marketing/werkbank/datei/{NAME}").status_code == 404


def test_datei_ohne_anmeldung_umleitung(anonym, datei_1mb):
    r = get(anonym, f"/marketing/werkbank/datei/{NAME}")
    assert r.status_code == 303 and r.headers["location"] == "/login"


# --- Szenenseite ------------------------------------------------------------------

def test_szenenseite_zeigt_text_quellen_und_spieler(klient, pult):
    r = get(klient, f"/marketing/werkbank/{AID}/szene/3")
    html = rumpf(r)
    assert r.status_code == 200
    assert ("GET", f"/werkbank/{AID}/szene/3?mandant=vibemind", None) in pult.aufrufe
    assert "Viele machen drei Fehler." in html and "Marke.md" in html and "Preise.pdf (S. 2)" in html
    assert f'<video controls preload="metadata" src="/marketing/werkbank/datei/{NAME}">' in html
    assert 'name="wunsch"' in html and "Passt" in html and "Nochmal" in html and "Wunsch speichern" in html
    assert "etwas kürzer" in html and "Bild 2: <b>Stichpunkte</b> – Kosten · Frist" in html
    assert "Passt der Clip?" in html and "Nochmal versuchen" not in html and "wieder öffnen" not in html
    assert "<script" not in html


def test_szenenseite_ohne_clip_hat_keinen_spieler(klient, pult):
    pult.szene = _szene(2, "text_wartet", clip_datei=None)
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/szene/2"))
    assert "<video" not in html and "Ist der Text so gut?" in html and "Passt" in html


def test_szenenseite_ohne_kennung_keine_urteilsknoepfe(klient, pult):
    pult.kennung = None
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/szene/3"))
    assert "<video" in html and 'value="passt"' not in html


def test_szenenseite_fehler_zeigt_nochmal_versuchen(klient, pult):
    pult.szene = _szene(4, "geplant", fehler="Der Sprecher antwortet nicht", clip_datei=None)
    pult.kennung = None
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/szene/4"))
    assert "Nochmal versuchen" in html and "Der Sprecher antwortet nicht" in html


def test_szenenseite_fertig_kann_wieder_geoeffnet_werden(klient, pult):
    pult.szene = _szene(1, "fertig")
    pult.kennung = None
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/szene/1"))
    assert "Szene wieder öffnen" in html and "<video" in html and 'value="passt"' not in html


def test_text_wird_maskiert(klient, pult):
    pult.szene = _szene(3, kurz="<i>kurz</i>", sprechtext="<script>alert(1)</script>", fehler="<b>x</b>",
                        quellen=["<img src=x>"], wuensche=["<u>w</u>"], wunsch="</textarea><b>w2</b>",
                        bild={"schritte": [{"vorlage": "titel", "text": "<svg onload=1>"}]})
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/szene/3"))
    for roh in ("<script>alert", "<i>kurz", "<img src=x>", "<u>w</u>", "</textarea><b>", "<svg onload", "<b>x</b>"):
        assert roh not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_szene_unbekannt_oder_fremd_404(klient):
    assert get(klient, f"/marketing/werkbank/{AID_FREMD}/szene/1").status_code == 404
    assert get(klient, f"/marketing/werkbank/{AID}/szene/abc").status_code == 404
    assert get(klient, "/marketing/werkbank/kein-auftrag/szene/1").status_code == 404


def test_leserolle_sieht_keine_knoepfe(leser, pult):
    r = get(leser, f"/marketing/werkbank/{AID}/szene/3")
    assert r.status_code == 403 and "Passt" not in r.text and "<form" not in r.text
    assert not pult.aufrufe


def test_leserolle_kann_nicht_urteilen(leser, pult):
    r = post(leser, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"})
    assert r.status_code == 403 and not pult.posts()


# --- Aktionen ---------------------------------------------------------------------

def test_urteil_schickt_wunsch_mit(klient, pult):
    r = post(klient, "/aktion/werkbank-urteil",
             {"aid": AID, "nr": "3", "kennung": K, "urteil": "nochmal", "wunsch": " kürzer "})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/werkbank/{AID}/szene/3?hinweis=nochmal"
    methode, pfad, daten = pult.posts()[0]
    assert (methode, pfad) == ("POST", f"/werkbank/v/{K}/urteil")
    assert daten == {"urteil": "nochmal", "wunsch": "kürzer", "mandant": "vibemind", "von": "mira"}


def test_urteil_passt(klient, pult):
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"})
    assert r.status_code == 303 and pult.posts()[0][2]["urteil"] == "passt" and pult.posts()[0][2]["wunsch"] == ""


def test_urteil_der_gliederung_geht_zur_uebersicht(klient, pult):
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "kennung": K, "urteil": "passt"})
    assert r.headers["location"] == f"/marketing/werkbank/{AID}?hinweis=passt&k={K}"


def test_urteil_ohne_csrf_403(klient, pult):
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"}, csrf=False)
    assert r.status_code == 403 and not pult.posts()


@pytest.mark.parametrize("daten", [
    {"aid": "x", "nr": "3", "kennung": K, "urteil": "passt"},
    {"aid": AID, "nr": "3", "kennung": "../../x", "urteil": "passt"},
    {"aid": AID, "nr": "3", "kennung": K, "urteil": "löschen"},
    {"aid": AID, "nr": "3x", "kennung": K, "urteil": "passt"}])
def test_urteil_ungueltig_wird_nicht_gesendet(klient, pult, daten):
    assert post(klient, "/aktion/werkbank-urteil", daten).status_code == 404 and not pult.posts()


def test_wunsch_zu_lang_wird_nicht_gesendet(klient, pult):
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt",
                                                   "wunsch": "x" * 2001})
    assert r.status_code == 422 and not pult.posts()


def test_wunsch_speichern(klient, pult):
    r = post(klient, "/aktion/werkbank-wunsch", {"aid": AID, "nr": "3", "kennung": K, "wunsch": "mehr Zahlen"})
    assert r.status_code == 303 and r.headers["location"].endswith("?hinweis=gespeichert")
    assert pult.posts()[0][:2] == ("POST", f"/werkbank/v/{K}/wunsch") and pult.posts()[0][2]["wunsch"] == "mehr Zahlen"
    assert post(klient, "/aktion/werkbank-wunsch", {"aid": AID, "nr": "3", "kennung": K, "wunsch": "  "}).status_code == 422


def test_nochmal_versuchen(klient, pult):
    r = post(klient, "/aktion/werkbank-nochmal", {"aid": AID, "nr": "4"})
    assert r.status_code == 303
    assert pult.posts()[0][:2] == ("POST", f"/werkbank/{AID}/szene/4/nochmal-versuchen")
    assert pult.posts()[0][2] == {"mandant": "vibemind", "von": "mira"}
    assert post(klient, "/aktion/werkbank-nochmal", {"aid": AID}).status_code == 404     # Szene fehlt


def test_oeffnen_braucht_wunsch(klient, pult):
    assert post(klient, "/aktion/werkbank-oeffnen", {"aid": AID, "nr": "1", "wunsch": ""}).status_code == 422
    r = post(klient, "/aktion/werkbank-oeffnen", {"aid": AID, "nr": "1", "wunsch": "anderer Einstieg"})
    assert r.status_code == 303 and pult.posts()[0][:2] == ("POST", f"/werkbank/{AID}/szene/1/oeffnen")
    assert pult.posts()[0][2]["wunsch"] == "anderer Einstieg"


def test_ablehnung_wird_zum_hinweis_schon_entschieden(klient, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Vorschlag ist nicht mehr aktuell")
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/werkbank/{AID}/szene/3?hinweis=entschieden"
    seite = get(klient, r.headers["location"])
    assert "Schon entschieden – Seite neu geladen" in rumpf(seite)


def test_api_weg_beim_urteil_ist_503(klient, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "URLError")
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"})
    assert r.status_code == 503


# --- Sprung aus der Nachricht -----------------------------------------------------

def test_kennung_leitet_auf_die_szene(klient, pult):
    r = get(klient, f"/marketing/werkbank/v/{K}")
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/werkbank/{AID}/szene/3"


def test_kennung_der_gliederung_leitet_auf_die_uebersicht(klient, pult):
    pult.vorschlag = {"auftrag": AID, "tor": "gliederung", "nr": None, "mandant": "vibemind", "aktuell": True}
    r = get(klient, f"/marketing/werkbank/v/{K}")
    assert r.headers["location"] == f"/marketing/werkbank/{AID}?k={K}"


def test_veraltete_kennung_leitet_auf_uebersicht(klient, pult):
    pult.vorschlag = {**pult.vorschlag, "aktuell": False}
    r = get(klient, f"/marketing/werkbank/v/{K}")
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/werkbank/{AID}?hinweis=ueberholt"
    assert "Diese Fassung ist überholt" in rumpf(get(klient, r.headers["location"]))


def test_unbekannte_kennung_ist_ueberholt_404(klient):
    r = get(klient, f"/marketing/werkbank/v/{K_ALT}")
    assert r.status_code == 404 and "Diese Fassung ist überholt" in r.text
    assert get(klient, "/marketing/werkbank/v/kaputt").status_code == 404


def test_kennung_einer_anderen_firma_ist_ueberholt(klient, pult):
    pult.vorschlag = {**pult.vorschlag, "mandant": "fin2gether"}
    assert get(klient, f"/marketing/werkbank/v/{K}").status_code == 404


# --- Uebersicht -------------------------------------------------------------------

def test_uebersicht(klient, pult):
    r = get(klient, f"/marketing/werkbank/{AID}")
    html = rumpf(r)
    assert r.status_code == 200
    assert "4 Szenen, 1 fertig, 2 warten auf dich." in html
    assert "Betriebliche Altersvorsorge" in html and "Zahlen zur Förderung" in html and "Die Kosten" in html
    assert "Preise.pdf" in html and f'href="/marketing/werkbank/{AID}/szene/3"' in html
    assert "Clip wartet auf dich" in html and "Fehler beim Erzeugen" in html
    assert 'name="wunsch"' not in html                  # ohne ?k=<Kennung> keine Gliederungs-Knoepfe
    assert "/video" not in html                         # noch nicht alle fertig


def test_uebersicht_mit_kennung_hat_wunschfeld(klient, pult):
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}?k={K}"))
    assert 'name="wunsch"' in html and f'name="kennung" value="{K}"' in html and "Passt" in html
    assert "Wunsch speichern" in html
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}?k=zzz"))
    assert 'name="wunsch"' not in html


def test_uebersicht_alle_fertig_verlinkt_video(klient, pult):
    pult.werk = {**_werk(), "alle_fertig": True}
    assert f'href="/marketing/werkbank/{AID}/video"' in rumpf(get(klient, f"/marketing/werkbank/{AID}"))


def test_uebersicht_maskiert(klient, pult):
    pult.werk = {**_werk(), "gliederung": {"titel": "<script>t</script>", "hook": "<b>h</b>", "fehlt": "<i>f</i>",
                                           "stufen": [{"name": "<u>s</u>", "szenen": ["<img src=x>"]}]}}
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}"))
    for roh in ("<script>t", "<b>h</b>", "<i>f</i>", "<u>s</u>", "<img src=x>"):
        assert roh not in html


def test_uebersicht_fremder_auftrag_404(klient):
    assert get(klient, f"/marketing/werkbank/{AID_FREMD}").status_code == 404


def test_ohne_firma_im_laden_kein_zugriff(klient, monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "")
    assert get(klient, f"/marketing/werkbank/{AID}").status_code == 422


def test_ohne_anmeldung_umleitung_seiten(anonym):
    for pfad in (f"/marketing/werkbank/{AID}", f"/marketing/werkbank/{AID}/szene/1", f"/marketing/werkbank/{AID}/video",
                 f"/marketing/werkbank/v/{K}"):
        assert get(anonym, pfad).headers["location"] == "/login"


# --- Videoseite -------------------------------------------------------------------

def test_videoseite_hat_ki_hinweis_und_kopierfelder(klient, pult):
    r = get(klient, f"/marketing/werkbank/{AID}/video")
    html = rumpf(r)
    assert r.status_code == 200 and "mit KI erstellt" in html and "0:00 Einstieg" in html and "0:42 Problem" in html
    assert f'<video controls preload="metadata" src="/marketing/werkbank/datei/{NAME_VIDEO}">' in html
    assert f'href="/marketing/werkbank/datei/{NAME_VIDEO}?laden=1"' in html and 'href="/freigaben"' in html
    assert html.count("data-kopieren=") == 3 and "Altersvorsorge &lt;einfach&gt;" in html
    assert "Messung: Lautheit -14 LUFS" in html and "Szene 4 ist kurz &lt;b&gt;" in html
    assert "<b>" not in html.split("Warnungen")[1].split("</ul>")[0]
    assert 'src="/marketing/werkbank/kopieren.js"' in html and "90 MB" in html and "4:05" in html
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_andere_seiten_haben_kein_script_src(klient):
    r = get(klient, f"/marketing/werkbank/{AID}")
    assert "script-src" not in r.headers["Content-Security-Policy"]


def test_kopier_skript(klient):
    r = get(klient, "/marketing/werkbank/kopieren.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "data-kopieren" in r.text


def test_videoseite_noch_nicht_fertig(klient, pult):
    pult.buch[0]["ergebnis"] = {"werkbank": {}}
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/video"))
    assert "noch nicht fertig" in html and "<video" not in html


def test_videoseite_fremder_auftrag_404(klient):
    assert get(klient, f"/marketing/werkbank/{AID_FREMD}/video").status_code == 404


def test_videoseite_boese_dateiname_wird_nicht_eingebettet(klient, pult):
    pult.buch[0]["ergebnis"]["datei"] = '"><script>x</script>.mp4'
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/video"))
    assert "<script>x" not in html and "<video" not in html



# --- Review-Runde: ok:false, Gliederungs-Kennung, Liste, Kleinkram ----------------------

def test_wunsch_ok_false_zeigt_hinweis_und_behaelt_den_text(klient, pult):
    pult.ok_false = True
    r = post(klient, "/aktion/werkbank-wunsch", {"aid": AID, "nr": "3", "kennung": K, "wunsch": "mehr <Zahlen>"})
    assert r.status_code == 409
    html = rumpf(r)
    assert "Schon entschieden – Seite neu geladen" in html and "Dein Wunsch ist gespeichert" not in html
    assert "mehr &lt;Zahlen&gt;" in html and "<Zahlen>" not in html
    assert f'href="/marketing/werkbank/{AID}/szene/3?hinweis=entschieden"' in html


def test_wunsch_abgelehnt_per_fehler_behaelt_den_text_auch(klient, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Der Vorschlag ist nicht mehr aktuell")
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "nochmal",
                                                  "wunsch": "kürzer"})
    assert r.status_code == 409 and "kürzer" in r.text


def test_urteil_ok_false_ohne_wunsch_leitet_mit_hinweis_um(klient, pult):
    pult.ok_false = True
    r = post(klient, "/aktion/werkbank-urteil", {"aid": AID, "nr": "3", "kennung": K, "urteil": "passt"})
    assert r.status_code == 303 and r.headers["location"].endswith("?hinweis=entschieden")


@pytest.mark.parametrize("pfad,daten", [
    ("/aktion/werkbank-nochmal", {"aid": AID, "nr": "4"}),
    ("/aktion/werkbank-oeffnen", {"aid": AID, "nr": "1", "wunsch": "anders"})])
def test_andere_posts_mit_ok_false(klient, pult, pfad, daten):
    pult.ok_false = True
    r = post(klient, pfad, daten)
    assert "Schon entschieden – Seite neu geladen" in r.text or r.headers["location"].endswith("hinweis=entschieden")


def test_gliederung_kennung_aus_der_api_zeigt_wunschfeld_ohne_k(klient, pult):
    pult.gliederung_kennung = K
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}"))
    assert 'name="wunsch"' in html and f'name="kennung" value="{K}"' in html and "Passt" in html


def test_gliederung_kennung_null_zeigt_keine_knoepfe_auch_mit_k(klient, pult):
    pult.gliederung_kennung = None
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}?k={K}"))
    assert 'name="wunsch"' not in html


def test_gliederung_kennung_der_api_gewinnt_gegen_k(klient, pult):
    pult.gliederung_kennung = K
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}?k={K_ALT}"))
    assert f'name="kennung" value="{K}"' in html and K_ALT not in html


def test_gliederung_wunsch_speichern_und_neu_laden_behaelt_die_knoepfe(klient, pult):
    pult.gliederung_kennung = K
    r = post(klient, "/aktion/werkbank-wunsch", {"aid": AID, "kennung": K, "wunsch": "mehr Kosten"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/werkbank/{AID}?hinweis=gespeichert&k={K}"
    html = rumpf(get(klient, r.headers["location"]))
    assert "Dein Wunsch ist gespeichert" in html and "Wunsch speichern" in html and 'value="nochmal"' in html
    # ohne ?k= (neue API) bleiben sie auch
    assert 'value="nochmal"' in rumpf(get(klient, f"/marketing/werkbank/{AID}?hinweis=gespeichert"))


def test_gliederung_wunsch_fallback_ohne_api_schluessel_behaelt_k(klient, pult):
    r = post(klient, "/aktion/werkbank-wunsch", {"aid": AID, "kennung": K, "wunsch": "mehr Kosten"})
    html = rumpf(get(klient, r.headers["location"]))                 # aeltere API: nur ?k= traegt die Kennung
    assert 'value="nochmal"' in html


def test_liste_zeigt_eigene_videoauftraege(klient, pult):
    pult.buch.append({"id": "77778888-4444-4444-4444-444444444444", "art": "video", "mandant": "vibemind",
                      "stand": "wartet_freigabe", "angelegt": "2026-11-12T09:00:00", "eingabe": {"thema": "Neu"},
                      "ergebnis": {}})
    r = get(klient, "/marketing/werkbank")
    html = rumpf(r)
    assert r.status_code == 200 and f'href="/marketing/werkbank/{AID}"' in html
    assert "Altersvorsorge &lt;kurz&gt;" in html and "in der Werkbank" in html and "2 warten auf dich" in html
    assert "wartet auf deine Freigabe" in html
    assert html.index("Neu</b>") < html.index("Altersvorsorge")            # neueste zuerst
    assert AID_FREMD not in html and "55556666" not in html                # fremde Firma, Reel


def test_liste_leer_erklaert_die_bestellung(klient, pult):
    pult.buch.clear()
    html = rumpf(get(klient, "/marketing/werkbank"))
    assert "Schreib dem Salesman" in html and "Video zu" in html


def test_liste_ohne_anmeldung_umleitung(anonym):
    assert get(anonym, "/marketing/werkbank").headers["location"] == "/login"


def test_reels_seite_verlinkt_die_liste(klient, pult, monkeypatch):
    echt = pult.anfrage

    def reels(methode, pfad, daten=None, roh=False, zeitlimit=None):
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True}]}
        if pfad.startswith("/video?"):
            return {"auftraege": []}
        return echt(methode, pfad, daten, roh, zeitlimit)
    monkeypatch.setattr(marketing_pult, "anfrage", reels)
    assert 'href="/marketing/werkbank"' in rumpf(get(klient, "/marketing/reels"))


def test_range_absurde_ziffern_sind_416_nicht_500(klient, datei_1mb):
    r = get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": "bytes=" + "9" * 5000 + "-"})
    assert r.status_code == 416
    assert ui_werkbank.bereich("bytes=0-" + "9" * 5000, 1000) is None


def test_datei_route_sucht_nur_in_staenden_mit_videos_und_merkt_sich_den_auftrag(klient, pult, datei_1mb):
    assert get(klient, f"/marketing/werkbank/datei/{NAME}").status_code == 200
    assert get(klient, f"/marketing/werkbank/datei/{NAME}", headers={"Range": "bytes=0-9"}).status_code == 206
    assert len(pult.buch_staende) == 1 and "abgebrochen" not in pult.buch_staende[0]


def test_videoseite_veraltet_ohne_download(klient, pult):
    pult.werk = {**_werk(), "video_veraltet": True}
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/video"))
    assert "Eine Szene wurde wieder geöffnet – dieses Video wird neu gebaut." in html
    assert "laden=1" not in html and "<video" in html


def test_videoseite_aktuell_hat_download_ohne_hinweis(klient, pult):
    html = rumpf(get(klient, f"/marketing/werkbank/{AID}/video"))
    assert "laden=1" in html and "neu gebaut" not in html


def test_alte_medienroute_sperrt_werkbankdateien_aber_nicht_reels(klient, tmp_path, monkeypatch):
    medien_ordner = tmp_path / "media"
    medien_ordner.mkdir()
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(medien_ordner))
    (medien_ordner / "vid-0123abcd-herbst.mp4").write_bytes(b"x" * 64)
    (medien_ordner / NAME).write_bytes(b"x" * 64)
    (tmp_path / NAME).write_bytes(b"x" * 64)               # auch im Erzeugt-Ordner
    assert get(klient, "/medien/datei/vid-0123abcd-herbst.mp4").status_code == 200
    assert get(klient, f"/medien/datei/{NAME}").status_code == 404
