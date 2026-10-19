"""Podcast-Seite im Marketing-Pult (19.10.2026). Der Client zur Marketing-API wird gefaelscht."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402

import server  # noqa: E402
import ui  # noqa: E402
import ui_podcast  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
AID = "0123abcd-4444-4444-4444-444444444444"
AID2 = "11112222-4444-4444-4444-444444444444"
DATEI = "pod-0123abcd-herbst.mp3"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


# --- Stand: Freigabe-Stand zu Mediendateien ----------------------------------

def _db():
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus")


@pytest.fixture(autouse=True)
def aufraeumen():
    yield
    try:
        server._q("delete from drafts where lead_id in (select id from leads where phone = '+491701230000')")
        server._q("delete from leads where phone = '+491701230000'")
    except Exception:
        pass


def _entwurf_mit_medien(status, media_ref):
    lead = server._q("insert into leads (name, phone, source) values ('Pod', '+491701230000', 'whatsapp') "
                     "returning id")[0]["id"]
    server._q("insert into drafts (lead_id, channel, recipient, body, status, media_ref) "
              "values (%s, 'linkedin', 'eigenes-profil', 'x', %s, %s)", (lead, status, media_ref))


def test_stand_weitester_gewinnt():
    _db()
    name = "pod-aaaaaaaa-weitester.mp3"
    _entwurf_mit_medien("rejected", name)
    _entwurf_mit_medien("approved", name)
    assert server.entwurf_staende_zu_medien([name]) == {name: "approved"}


def test_stand_exakter_name():
    _db()
    name = "pod-aaaaaaaa-x.mp3"
    _entwurf_mit_medien("sent", "pod-aaaaaaaa-x.mp3.bak")
    _entwurf_mit_medien("sent", "xpod-aaaaaaaa-x.mp3")
    _entwurf_mit_medien("pending", f"andere.png, {name}")
    assert server.entwurf_staende_zu_medien([name]) == {name: "pending"}


def test_stand_leere_liste_ohne_abfrage(monkeypatch):
    def nie(*a, **k):
        raise AssertionError("keine Abfrage erwartet")
    monkeypatch.setattr(server, "_q", nie)
    assert server.entwurf_staende_zu_medien([]) == {}


# --- Seite -----------------------------------------------------------------------

class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.auftraege = [
            {"id": AID, "mandant": "vibemind", "titel": "Herbst-Folge", "sprache": "de",
             "skript": [{"sprecher": "Anna", "text": "Hallo"}, {"sprecher": "Ben", "text": "Hi"}],
             "status": "fertig", "datei": DATEI, "dauer_s": 125, "befund": None, "angelegt_von": "agent",
             "erstellt_am": "2026-10-19T10:00:00", "geaendert_am": "2026-10-19T10:05:00"},
            {"id": AID2, "mandant": "vibemind", "titel": "<script>x</script>", "sprache": "de",
             "skript": [{"sprecher": "Anna", "text": "<b>fett</b>"}], "status": "in_arbeit", "datei": None,
             "dauer_s": None, "befund": None, "angelegt_von": "betreiber",
             "erstellt_am": "2026-10-19T11:00:00", "geaendert_am": "2026-10-19T11:00:00"}]

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
        if self.fehler:
            raise self.fehler
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True}]}
        if pfad.startswith("/ton?"):
            return {"auftraege": self.auftraege}
        if pfad == "/ton":
            return {"auftrag": AID}
        if pfad.endswith("/abbrechen"):
            return {"status": "abgebrochen"}
        return {}


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    monkeypatch.setattr(server, "entwurf_staende_zu_medien", lambda namen: {DATEI: "pending"})
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


def test_menue_hat_podcast_nach_reels():
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        s = ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)
    assert 'href="/marketing/podcast"' in s
    assert s.index('href="/marketing/reels"') < s.index('href="/marketing/podcast"')


def test_skript_aus_text():
    f = ui_podcast.skript_aus_text
    assert f("Anna: Hallo\nBen: Hi", "Sprecher") == [{"sprecher": "Anna", "text": "Hallo"},
                                                     {"sprecher": "Ben", "text": "Hi"}]
    assert f("Nur Text ohne Namen", "Mira") == [{"sprecher": "Mira", "text": "Nur Text ohne Namen"}]
    assert f("\n\nAnna: Eins\n   \n\nZwei\n", "Mira") == [{"sprecher": "Anna", "text": "Eins"},
                                                           {"sprecher": "Mira", "text": "Zwei"}]
    assert f("Siehe https://x", "Mira") == [{"sprecher": "Mira", "text": "Siehe https://x"}]
    assert f("Dr. Ana-Lena Ö.: Grüße", "Mira") == [{"sprecher": "Dr. Ana-Lena Ö.", "text": "Grüße"}]
    lang = "A" * 31 + ": x"
    assert f(lang, "Mira") == [{"sprecher": "Mira", "text": lang}]
    assert f("Anna: Zeit 10:30", "Mira") == [{"sprecher": "Anna", "text": "Zeit 10:30"}]
    assert f("   \n", "Mira") == []


def test_seite_zeigt_folgen_status_player_skript(angemeldet, pult):
    r = angemeldet.get("/marketing/podcast", headers=HOST)
    s = r.text
    assert r.status_code == 200
    assert pult.aufrufe[-1][1] == "/ton?mandant=vibemind&limit=50"
    assert f'<audio controls preload="none" src="/medien/datei/{DATEI}">' in s
    assert "2:05" in s and "zur Freigabe" in s
    assert "<details><summary>Skript</summary>" in s and "Anna: Hallo" in s
    assert "wird gesprochen" in s and 'http-equiv="refresh"' in s
    assert f'action="/marketing/podcast/{AID2}/abbrechen"' in s
    assert f'action="/marketing/podcast/{AID}/abbrechen"' not in s      # fertig: nicht abbrechbar
    assert "Betreiber" in s and "Agent" in s
    assert 'action="/marketing/podcast/neu"' in s


def test_ohne_laufende_folge_kein_refresh(angemeldet, pult):
    pult.auftraege = pult.auftraege[:1]
    assert 'http-equiv="refresh"' not in angemeldet.get("/marketing/podcast", headers=HOST).text


def test_xss_und_manipulierte_datei(angemeldet, pult):
    s = angemeldet.get("/marketing/podcast", headers=HOST).text
    assert "&lt;script&gt;x&lt;/script&gt;" in s and "<script>x" not in s
    assert "&lt;b&gt;fett&lt;/b&gt;" in s and "<b>fett" not in s
    pult.auftraege[0]["datei"] = "../x.mp3"
    assert "<audio" not in angemeldet.get("/marketing/podcast", headers=HOST).text


def test_andere_firma_nutzt_cookie(angemeldet, pult):
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    angemeldet.get("/marketing/podcast", headers=HOST)
    assert pult.aufrufe[-1][1] == "/ton?mandant=fin2gether&limit=50"


def test_neu_bestellt_beim_pult(angemeldet, pult):
    r = angemeldet.post("/marketing/podcast/neu", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "titel": " Herbst ", "sprache": "de", "sprecher": "Mira",
        "skript": "Anna: Hallo\nBen: Hi\nOhne Namen"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/podcast"
    methode, pfad, daten = pult.aufrufe[-1]
    assert (methode, pfad) == ("POST", "/ton")
    assert daten == {"mandant": "vibemind", "titel": "Herbst", "sprache": "de",
                     "skript": [{"sprecher": "Anna", "text": "Hallo"}, {"sprecher": "Ben", "text": "Hi"},
                                {"sprecher": "Mira", "text": "Ohne Namen"}]}


@pytest.mark.parametrize("daten", [{"titel": "T", "skript": ""}, {"titel": "T", "skript": " \n \n"},
                                   {"titel": "", "skript": "Anna: x"}, {"titel": "T", "skript": "x", "sprecher": "9"}])
def test_neu_leeres_skript_422_ohne_pult_aufruf(angemeldet, pult, daten):
    r = angemeldet.post("/marketing/podcast/neu", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "sprache": "de", "sprecher": "Mira", **daten})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_neu_api_lehnt_ab_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "text: 1 bis 1000 Zeichen je Abschnitt")
    r = angemeldet.post("/marketing/podcast/neu", headers=HOST, follow_redirects=False, data={
        "csrf": ui.CSRF_TOKEN, "titel": "T", "sprache": "de", "sprecher": "Mira", "skript": "Anna: " + "x" * 1001})
    assert r.status_code == 422 and "1 bis 1000 Zeichen je Abschnitt" in r.text


def test_abbrechen(angemeldet, pult):
    r = angemeldet.post(f"/marketing/podcast/{AID2}/abbrechen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and pult.aufrufe[-1][:2] == ("POST", f"/ton/{AID2}/abbrechen")


def test_abbrechen_nicht_mehr_offen_zeigt_grund(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Folge ist nicht mehr offen")
    r = angemeldet.post(f"/marketing/podcast/{AID}/abbrechen", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 422 and "nicht mehr offen" in r.text


def test_abbrechen_und_csrf(angemeldet, pult):
    for pfad in ("/marketing/podcast/neu", f"/marketing/podcast/{AID}/abbrechen"):
        r = angemeldet.post(pfad, headers=HOST, follow_redirects=False, data={"titel": "x"})
        assert r.status_code == 403, pfad
    assert not pult.aufrufe


@pytest.mark.parametrize("art", ["nicht_verbunden", "nicht_erreichbar"])
def test_pult_ausfall_fehlerseite(angemeldet, pult, art):
    pult.fehler = marketing_pult.PultFehler(art)
    assert angemeldet.get("/marketing/podcast", headers=HOST).status_code == 503


def test_hinweis_versand_per_assistent(angemeldet, pult):
    s = angemeldet.get("/marketing/podcast", headers=HOST).text
    assert "Zum Versenden den Assistenten bitten" in s and "Stimme: KI" in s
    assert "Zur Freigabe vorbereiten" not in s


def test_freigabe_stand_ausfall_zeigt_seite(angemeldet, pult, monkeypatch):
    def kaputt(namen):
        raise RuntimeError("db weg")
    monkeypatch.setattr(server, "entwurf_staende_zu_medien", kaputt)
    r = angemeldet.get("/marketing/podcast", headers=HOST)
    assert r.status_code == 200 and "noch kein Entwurf" in r.text
