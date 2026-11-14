"""Abschnitt "Übergaben aus Rowboat" auf der Werkbank-Liste und die Aktionen Ja/Nein (Spec 14).

NUR IN DER CI lauffaehig (Postgres mit db/video-uebergabe.sql, Benutzertabelle in sales_test). Gearbeitet wird
wie in test_freigabe_eingang_ui.py: echtes `sales_test`, angemeldeter Client, CSRF-Marke. Das Schema `auftrag`
gibt es dort nicht: `auftrag_buch.anlegen` (Ersatz) und `auftrag_buch.eigene` (leer) sind ersetzt.
"""
import os
import re
import urllib.parse

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"

from starlette.testclient import TestClient  # noqa: E402

import auftrag_buch  # noqa: E402
import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_werkbank  # noqa: E402
import video_konzept  # noqa: E402
import video_uebergabe as vu  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
LISTE = "/marketing/werkbank"
AID = "0123abcd-4444-4444-4444-444444444444"
TAGESGRENZE = "Heute sind schon zwei Videos bestellt – morgen wieder."
HINWEIS = "Was im Konzept steht, geht an das Videomodell und kann im Video landen."


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.video_uebergabe")
    yield


class Bestellungen:
    def __init__(self):
        self.aufrufe = []
        self.ablehnung = None

    def __call__(self, q, laden, mandant, art, eingabe):
        if self.ablehnung:
            raise auftrag_buch.AuftragAbgelehnt(self.ablehnung)
        self.aufrufe.append((laden, mandant, art, eingabe))
        return AID


@pytest.fixture
def buch(monkeypatch):
    b = Bestellungen()
    monkeypatch.setattr(auftrag_buch, "anlegen", b)
    monkeypatch.setattr(auftrag_buch, "eigene", lambda q, laden, staende: [])
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    return b


def _anmelden(rolle):
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
    return c


@pytest.fixture
def secret():
    vorher = ui.UI_SESSION_SECRET
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def klient(buch, secret):
    return _anmelden("freigeben")


@pytest.fixture
def leser(buch, secret):
    return _anmelden("lesen")


@pytest.fixture
def anonym(buch, secret):
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    return TestClient(ui.app)


def konzept(**ueber):
    k = {
        "thema": "KI im Vertrieb", "zielgruppe": "Entscheider 34+", "minuten": 4,
        "hook": "Was kostet ein verlorener Lead?", "kernaussage": "Wer früh antwortet, gewinnt.",
        "stufen": [
            {"name": "Problem", "szenen": [{"kurz": f"Szene {i}", "bildart": "slide"} for i in range(4)]},
            {"name": "Lösung", "szenen": [{"kurz": f"Szene {i}", "bildart": "clip", "notiz": f"Notiz {i}"}
                                         for i in range(4, 8)]},
        ],
        "abschluss": "Jetzt anfragen.", "auftrag": None, "firma": "fin2gether",
        "pfad": "knowledge/Konzepte/ki.html", "name": "ki.html",
    }
    k.update(ueber)
    return k


def vorbereiten(**ueber):
    k = konzept(**ueber)
    vorgang, satz = vu.anlegen(k, video_konzept.block_hash(k))
    assert satz is None
    return vorgang


def kennung():
    return str(server._q("select id from video_uebergabe order by erstellt_am limit 1")[0]["id"])


def zeile():
    return server._q("select * from video_uebergabe order by erstellt_am limit 1")[0]


def seite(c, pfad=LISTE):
    r = c.get(pfad, headers=HOST, follow_redirects=False)
    assert r.status_code == 200, r.status_code
    return r.text


def abschnitt(c, pfad=LISTE) -> str:
    text = seite(c, pfad)
    s = text[text.index('<section class="block" id="uebergaben">'):]
    return s[:s.index("</section>")]


def post(c, aktion, daten, csrf=True, headers=None):
    if csrf:
        daten = {**daten, "csrf": ui.CSRF_TOKEN}
    return c.post(f"/aktion/{aktion}", data=daten, headers={**HOST, **(headers or {})}, follow_redirects=False)


def ja(c, k=None):
    return post(c, "werkbank-uebergabe-ja", {"id": k or kennung()})


def nein(c, k=None):
    return post(c, "werkbank-uebergabe-nein", {"id": k or kennung()})


def ziel(r) -> str:
    assert r.status_code == 303, r.status_code
    return r.headers["location"].split("#")[0]


# --- Anzeige -------------------------------------------------------------------------------------------

def test_ohne_offene_uebergabe_kein_abschnitt(klient):
    assert 'id="uebergaben"' not in seite(klient)


def test_abschnitt_zeigt_zusammenfassung_hinweis_und_szenen(klient):
    vorbereiten()
    s = abschnitt(klient)
    assert "Übergaben aus Rowboat" in s and 'class="zaehler offen">1<' in s
    assert "KI im Vertrieb" in s and "4 Minuten" in s and "2 Stufen" in s and "8 Szenen" in s
    assert "Laden: ivan" in s and "ki.html" in s and "vor 1 Minute" in s
    assert HINWEIS in s
    assert "<details>" in s and "Problem" in s and "Lösung" in s
    assert "Szene 0" in s and "(slide)" in s and "(clip)" in s and "Notiz 4" in s
    assert "Ja, übergeben" in s and ">Nein<" in s
    assert s.count('name="csrf"') == 2 and f'value="{kennung()}"' in s


def test_alter_in_stunden_und_minuten(klient):
    vorbereiten()
    server._q("update video_uebergabe set erstellt_am = now() - interval '3 hours 10 minutes' returning id")
    assert "vor 3 Stunden" in abschnitt(klient)
    server._q("update video_uebergabe set erstellt_am = now() - interval '7 minutes' returning id")
    assert "vor 7 Minuten" in abschnitt(klient)


def test_alter_text():
    assert ui_werkbank.alter_text(0) == "vor 1 Minute" and ui_werkbank.alter_text(59) == "vor 1 Minute"
    assert ui_werkbank.alter_text(120) == "vor 2 Minuten" and ui_werkbank.alter_text(3600) == "vor 1 Stunde"
    assert ui_werkbank.alter_text(7300) == "vor 2 Stunden" and ui_werkbank.alter_text(None) == "vor 1 Minute"


def test_alle_werte_sind_maskiert(klient):
    boese = konzept(
        thema='<script>alert("t")</script> "x" \'y\'', name='<img src=x onerror=alert(1)>.html',
        stufen=[{"name": '<i>Stufe</i> "q"', "szenen": [
            {"kurz": '"><script>alert("k")</script>', "bildart": "slide",
             "notiz": "' onmouseover='alert(1)' <b>n</b>"}] * 8}])
    vu.anlegen(boese, video_konzept.block_hash(boese))
    s = abschnitt(klient)
    for roh in ("<script>", "<img src=x", "<i>Stufe</i>", "<b>n</b>", '"><script'):
        assert roh not in s
    assert "&lt;script&gt;alert(&quot;t&quot;)&lt;/script&gt;" in s
    assert "&lt;img src=x onerror=alert(1)&gt;.html" in s
    assert "&lt;b&gt;n&lt;/b&gt;" in s and "&#x27; onmouseover=&#x27;alert(1)&#x27;" in s


def test_abgelaufene_wird_nicht_gezeigt(klient):
    vorbereiten()
    server._q("update video_uebergabe set erstellt_am = now() - interval '25 hours' returning id")
    assert 'id="uebergaben"' not in seite(klient)


def test_lesende_anmeldung_sieht_keine_knoepfe(leser):
    vorbereiten()
    r = leser.get(LISTE, headers=HOST, follow_redirects=False)
    assert "Ja, übergeben" not in r.text and "werkbank-uebergabe" not in r.text
    assert ja(leser).status_code == 403 and nein(leser).status_code == 403
    assert zeile()["status"] == "offen"


# --- Ja ------------------------------------------------------------------------------------------------

def test_ja_legt_auftrag_an_und_zeigt_nummer_und_link(klient, buch):
    vorbereiten()
    r = ja(klient)
    assert ziel(r).startswith(f"{LISTE}?")
    text = seite(klient, r.headers["location"].split("#")[0])
    assert f"Übergeben: Auftrag {AID[:8]} ist angelegt." in text
    assert f'href="{LISTE}/{AID}"' in text
    assert 'id="uebergaben"' not in text                       # nicht mehr offen
    z = zeile()
    assert z["status"] == "bestaetigt" and str(z["auftrag_id"]) == AID and z["entschieden_von"] == "mira"
    (laden, mandant, art, eingabe), = buch.aufrufe
    assert (laden, mandant, art) == ("ivan", "fin2gether", "video")
    assert eingabe["von"] == "rowboat" and eingabe["konzept"] == konzept()


def test_tagesgrenze_beim_ja_bleibt_offen_mit_satz_an_der_uebergabe(klient, buch):
    vorbereiten()
    buch.ablehnung = TAGESGRENZE
    text = seite(klient, ziel(ja(klient)))
    s = text[text.index('id="uebergaben"'):]
    assert TAGESGRENZE in s and "Ja, übergeben" in s
    assert "Der Auftrag wurde nicht angelegt. Der Grund steht an der Übergabe." in text
    assert zeile()["status"] == "offen" and buch.aufrufe == []


def test_zweiter_klick_bekommt_schon_entschieden(klient, buch):
    vorbereiten()
    k = kennung()
    assert ja(klient, k).status_code == 303
    text = seite(klient, ziel(ja(klient, k)))
    assert "Diese Übergabe ist schon entschieden." in text
    assert len(buch.aufrufe) == 1


def test_ja_auf_abgelaufene_uebergabe(klient, buch):
    vorbereiten()
    server._q("update video_uebergabe set erstellt_am = now() - interval '25 hours' returning id")
    text = seite(klient, ziel(ja(klient)))
    assert "Diese Übergabe ist abgelaufen." in text and buch.aufrufe == []


def test_unbekannte_kennung_404(klient, buch):
    assert ja(klient, "kaputt").status_code == 404
    assert ja(klient, "0123abcd-4444-4444-4444-4444444444ff").status_code == 303     # gueltig, aber unbekannt
    assert buch.aufrufe == []


# --- Nein ----------------------------------------------------------------------------------------------

def test_nein_verwirft_ohne_auftrag(klient, buch):
    vorbereiten()
    text = seite(klient, ziel(nein(klient)))
    assert "Die Übergabe ist verworfen. Es wurde kein Auftrag angelegt." in text
    assert zeile()["status"] == "verworfen" and zeile()["entschieden_von"] == "mira" and buch.aufrufe == []
    assert 'id="uebergaben"' not in text


# --- Schutz --------------------------------------------------------------------------------------------

def test_ohne_csrf_abgewiesen(klient, buch):
    vorbereiten()
    assert post(klient, "werkbank-uebergabe-ja", {"id": kennung()}, csrf=False).status_code == 403
    assert post(klient, "werkbank-uebergabe-nein", {"id": kennung()}, csrf=False).status_code == 403
    assert zeile()["status"] == "offen" and buch.aufrufe == []


def test_ohne_login_abgewiesen(anonym, buch):
    vorbereiten()
    for aktion in ("werkbank-uebergabe-ja", "werkbank-uebergabe-nein"):
        r = anonym.post(f"/aktion/{aktion}", data={"id": kennung(), "csrf": ui.CSRF_TOKEN}, headers=HOST,
                        follow_redirects=False)
        assert r.status_code in (303, 401, 403)
        assert "/login" in r.headers.get("location", "/login")
    assert zeile()["status"] == "offen" and buch.aufrufe == []


def test_rowboat_schluessel_loest_die_aktionen_nicht_aus(anonym, buch):
    vorbereiten()
    kopf = {"Authorization": "Bearer " + fe.schluessel_anlegen("rowboat")}
    for aktion in ("werkbank-uebergabe-ja", "werkbank-uebergabe-nein"):
        r = anonym.post(f"/aktion/{aktion}", data={"id": kennung(), "csrf": ui.CSRF_TOKEN},
                        headers={**HOST, **kopf}, follow_redirects=False)
        assert r.status_code in (303, 401, 403)
    assert zeile()["status"] == "offen" and buch.aufrufe == []


def test_ohne_marketing_firma_kein_ja(klient, buch, monkeypatch):
    vorbereiten()
    monkeypatch.setenv("MARKETING_MANDANT", "")
    assert ja(klient).status_code == 422 and zeile()["status"] == "offen"


def test_ergebniszeile_nimmt_keine_fremden_werte(klient):
    muster = {"hinweis": "uebergeben", "nr": '"><script>', "a": AID}
    text = seite(klient, f"{LISTE}?{urllib.parse.urlencode(muster)}")
    assert "<script>" not in text and "Übergeben: Auftrag" not in text
    passt_nicht = {"hinweis": "uebergeben", "nr": "deadbeef", "a": AID}
    assert "Übergeben: Auftrag" not in seite(klient, f"{LISTE}?{urllib.parse.urlencode(passt_nicht)}")
    assert re.search(r"Übergeben: Auftrag 0123abcd", seite(klient, f"{LISTE}?hinweis=uebergeben&nr=0123abcd&a={AID}"))
