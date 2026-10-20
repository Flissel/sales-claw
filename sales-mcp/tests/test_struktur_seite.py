"""Seite /team/struktur: wer welchen Laden eingeladen hat (Plan
docs/superpowers/plans/2026-10-20-struktur-graph.md, Tasks 3 und 4).

Entscheidungen des Betreibers (20.10.2026), sie gehen dem Plan vor:
* Läden mit ergebnis->>'ausgeblendet' = 'true' erscheinen weder im Graph
  noch in der Liste noch in einer Einlader-Auswahl; die Datenzeile bleibt.
* Der Menüpunkt steht in der Gruppe „Analyse“, die Rechte bleiben
  Admin-Basis (_ADMIN_BASIS_PFADE, gefiltert über _pfad_erlaubt).
"""
import os
import re

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import struktur  # noqa: E402
import ui_struktur  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.admin_auftraege, sales_test.benutzer cascade")


@pytest.fixture
def scharf():
    """Anmeldung scharf schalten - Muster aus test_laden_anlegen_seite.py."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _post(pfad, daten, host=HOST_OK, client=None):
    return (client or CLIENT).post(
        pfad, data=daten, headers={"host": host}, follow_redirects=False)


def _get(pfad, host=HOST_OK, client=None):
    return (client or CLIENT).get(pfad, headers={"host": host})


def _erfolg(name, einlader=None, ergebnis=None):
    server._q(
        "insert into admin_auftraege (art, name, angefordert_von, status, "
        "ergebnis, erledigt_am, eingeladen_von) values ('laden_anlegen', %s, "
        "'test', 'erfolg', %s::jsonb, now(), %s) returning id",
        (name, ergebnis, einlader))


def _angemeldet(name, rolle, passwort="struktur-passwort-9"):
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen(name, rolle, passwort)
    assert meldung.startswith("OK"), meldung
    client = TestClient(ui.app)
    r = client.post("/login", data={"name": name, "passwort": passwort,
                                    "csrf": ui.CSRF_TOKEN},
                    headers={"host": HOST_OK}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


# --- Task 3: Seite, Tor, Menü, SVG, Liste -----------------------------------

def test_tor_wie_laden_anlegen(monkeypatch):
    for p in ("/team/struktur", "/team/struktur/einlader"):
        assert ui._pfad_erlaubt("freigeben", p) is True
        assert ui._pfad_erlaubt("lesen", p) is False and ui._pfad_erlaubt("kalender", p) is False
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/struktur") is False


def test_menue_und_mehr_tragen_struktur():
    # Betreiber 20.10.: Gruppe „Analyse“ statt „Admin“ (E11 geändert).
    gruppen = dict(ui._menue_gruppen("freigeben"))
    assert ("/team/struktur", "Struktur") in gruppen["Analyse"]
    assert ("/team/struktur", "Struktur") not in gruppen.get("Admin", ())
    assert 'href="/team/struktur"' in ui._menue_links(ui._menue_gruppen("freigeben"), {}, None)
    assert "/team/struktur" not in ui._menue_links(ui._menue_gruppen("lesen"), {}, None)


def test_rolle_kalender_sieht_und_oeffnet_struktur_nicht(scharf):
    client = _angemeldet("kalli", "kalender")
    assert "/team/struktur" not in ui._menue_links(ui._menue_gruppen("kalender"), {}, None)
    seite = _get("/kalender", client=client)
    assert seite.status_code == 200 and 'href="/team/struktur"' not in seite.text
    mehr = _get("/mehr", client=client)
    assert mehr.status_code == 200 and 'href="/team/struktur"' not in mehr.text
    assert _get("/team/struktur", client=client).status_code == 403


def test_ivans_laden_sieht_und_oeffnet_struktur_nicht(scharf, monkeypatch):
    client = _angemeldet("ivan", "freigeben")
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert "/team/struktur" not in ui._menue_links(ui._menue_gruppen("freigeben"), {}, None)
    mehr = _get("/mehr", client=client)
    assert mehr.status_code == 200 and 'href="/team/struktur"' not in mehr.text
    assert _get("/team/struktur", client=client).status_code == 403
    r = _post("/team/struktur/einlader",
              {"name": "lena", "einlader": "", "csrf": ui.CSRF_TOKEN}, client=client)
    assert r.status_code == 403


def test_leerer_zustand():
    t = _get("/team/struktur").text
    assert "Noch keine Mitglieder" in t and 'href="/team/laden-anlegen"' in t and "<svg" not in t


def test_graph_und_liste():
    _erfolg("ivan"); _erfolg("lena", "ivan")
    r = _get("/team/struktur"); t = r.text
    assert r.status_code == 200 and "<script" not in t.lower()
    svg = t[t.index("<svg"):t.index("</svg>")]
    assert svg.count("<circle") == 3 and svg.count("<line") == 2
    assert '<text class="zahl"' in svg and ">Ich<" in svg and ">ivan<" in svg and ">lena<" in svg
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", svg) and "style=" not in svg
    assert t.index('class="struktur-liste"') > t.index("</svg>")
    assert r.headers["content-security-policy"] == ui._CSP


def test_nur_erfolg_erscheint():
    _erfolg("ivan")
    server._q("insert into admin_auftraege (art,name,angefordert_von,status) values ('laden_anlegen','kaputt','t','fehler')")
    assert "kaputt" not in _get("/team/struktur").text


def test_seite_mit_verwaistem_laden():
    server._q("insert into admin_auftraege (art,name,angefordert_von,status,eingeladen_von) "
              "values ('laden_anlegen','lena','t','erfolg','weg')")
    t = _get("/team/struktur").text
    assert "nicht gefunden" in t and ">lena<" in t


def test_svg_escaped_namen():
    svg = ui_struktur.svg_zeichnen(struktur.baum_bauen({'<script>"x': None}))
    assert "<script" not in svg and "&lt;script&gt;&quot;x" in svg


def test_langer_name_gekuerzt_mit_vollem_titel():
    n = "a" * 31
    svg = ui_struktur.svg_zeichnen(struktur.baum_bauen({n: None}))
    assert f">{'a' * 13}…<" in svg and f"<title>{n} – Ebene 1</title>" in svg


def test_css_nur_variablen():
    teil = ui._STIL[ui._STIL.index("/* Struktur-Graph"):]
    teil = teil[:teil.index("/* Ende Struktur-Graph */")]
    assert "var(--akzent" in teil and not re.search(r"#[0-9a-fA-F]{3,8}\b", teil)


def test_nachtrag_zeile_erscheint_im_graph():
    """E14: nachgetragene Bestandsläden sind normale erfolg-Zeilen."""
    server._q("insert into admin_auftraege (art,name,angefordert_von,status,ergebnis,erledigt_am) "
              "values ('laden_anlegen','ivan','nachtrag-struktur','erfolg','{\"nachtrag\": true}'::jsonb, now())")
    _erfolg("lena", "ivan")
    t = _get("/team/struktur").text
    svg = t[t.index("<svg"):t.index("</svg>")]
    assert ">ivan<" in svg and ">lena<" in svg and svg.count("<line") == 2


def test_ausgeblendeter_laden_fehlt_in_graph_und_liste():
    _erfolg("ivan")
    _erfolg("probelauf", ergebnis='{"ausgeblendet": true}')
    _erfolg("probemail", ergebnis='{"ausgeblendet": "true", "port_serve": 8450}')
    t = _get("/team/struktur").text
    assert ">ivan<" in t
    assert "probelauf" not in t and "probemail" not in t
    assert server._q("select count(*) as n from admin_auftraege "
                     "where name in ('probelauf','probemail')")[0]["n"] == 2


def test_nur_ausgeblendete_laeden_ergibt_leerzustand():
    _erfolg("probelauf", ergebnis='{"ausgeblendet": true}')
    t = _get("/team/struktur").text
    assert "Noch keine Mitglieder" in t and "<svg" not in t


def test_ausgeblendet_false_bleibt_sichtbar():
    _erfolg("ivan", ergebnis='{"ausgeblendet": false}')
    assert ">ivan<" in _get("/team/struktur").text


def test_laeden_lesen_filtert_ausgeblendete():
    _erfolg("ivan")
    _erfolg("probelauf", ergebnis='{"ausgeblendet": true}')
    with server.pool.connection() as conn:
        assert ui_struktur.laeden_lesen(conn) == {"ivan": None}
        assert ui_struktur.laeden_lesen(conn, sperren=True) == {"ivan": None}


# --- Task 4: Einlader ändern ------------------------------------------------

def _umhaengen(name, einlader, csrf=True):
    d = {"name": name, "einlader": einlader}
    if csrf: d["csrf"] = ui.CSRF_TOKEN
    return _post("/team/struktur/einlader", d)


def _einlader(name):
    return server._q("select eingeladen_von from admin_auftraege where name=%s and status='erfolg'", (name,))[0]["eingeladen_von"]


def test_liste_escaped_namen():
    html = ui_struktur.liste_zeichnen(struktur.baum_bauen({'a"><img': None, "b": None}), "tok")
    assert "<img" not in html and 'value="a&quot;&gt;&lt;img"' in html


def test_liste_hat_formular_je_laden_ohne_eigene_nachfahren():
    _erfolg("ivan"); _erfolg("lena", "ivan")
    t = _get("/team/struktur").text
    assert t.count('action="/team/struktur/einlader"') == 2
    form_ivan = t[t.index('name="name" value="ivan"'):]
    form_ivan = form_ivan[:form_ivan.index("</form>")]
    assert 'value="lena"' not in form_ivan and '<option value="">Ich</option>' in form_ivan.replace(" selected", "")


def test_formular_waehlt_den_aktuellen_einlader_vor():
    _erfolg("ivan"); _erfolg("lena", "ivan")
    t = _get("/team/struktur").text
    form_lena = t[t.index('name="name" value="lena"'):]
    form_lena = form_lena[:form_lena.index("</form>")]
    assert '<option value="ivan" selected>' in form_lena


def test_post_haengt_um_und_springt_zurueck():
    _erfolg("ivan"); _erfolg("lena")
    r = _umhaengen("lena", "ivan")
    assert r.status_code == 303 and r.headers["location"] == "/team/struktur"
    assert _einlader("lena") == "ivan"
    assert _umhaengen("lena", "").status_code == 303 and _einlader("lena") is None


def test_post_ohne_csrf():
    _erfolg("ivan"); _erfolg("lena")
    assert _umhaengen("lena", "ivan", csrf=False).status_code == 400 and _einlader("lena") is None


def test_post_unbekannt():
    _erfolg("ivan")
    server._q("insert into admin_auftraege (art,name,angefordert_von) values ('laden_anlegen','offen1','t')")
    assert _umhaengen("offen1", "ivan").status_code == 400
    r = _umhaengen("ivan", "nemo")
    assert r.status_code == 400 and "Nichts wurde geändert" in r.text and _einlader("ivan") is None


def test_post_ring_wird_abgewiesen():
    _erfolg("ivan"); _erfolg("lena", "ivan"); _erfolg("otto", "lena")
    r = _umhaengen("ivan", "otto")
    assert r.status_code == 400 and "abstammt" in r.text and _einlader("ivan") is None
    assert _umhaengen("lena", "lena").status_code == 400


def test_post_zu_tief_wird_abgewiesen():
    _erfolg("x"); _erfolg("x1", "x"); _erfolg("x2", "x1")
    vorher = None
    for n in ("a1", "a2", "a3", "a4"):
        _erfolg(n, vorher); vorher = n
    r = _umhaengen("x", "a4")
    assert r.status_code == 400 and "Ebene 7" in r.text and _einlader("x") is None
    assert _umhaengen("x", "a3").status_code == 303 and _einlader("x") == "a3"


def test_post_aendert_nur_erfolg_zeilen():
    _erfolg("ivan"); _erfolg("lena")
    server._q("insert into admin_auftraege (art,name,angefordert_von,status) values ('laden_anlegen','lena','t','fehler')")
    _umhaengen("lena", "ivan")
    assert server._q("select eingeladen_von from admin_auftraege where name='lena' and status='fehler'")[0]["eingeladen_von"] is None


def test_ausgeblendeter_laden_fehlt_in_den_umhaengen_auswahlen():
    _erfolg("ivan"); _erfolg("lena")
    _erfolg("probelauf", ergebnis='{"ausgeblendet": true}')
    t = _get("/team/struktur").text
    assert 'value="probelauf"' not in t and t.count('action="/team/struktur/einlader"') == 2


def test_ausgeblendeter_laden_laesst_sich_nicht_umhaengen():
    _erfolg("ivan")
    _erfolg("probelauf", ergebnis='{"ausgeblendet": true}')
    assert _umhaengen("probelauf", "ivan").status_code == 400
    assert _umhaengen("ivan", "probelauf").status_code == 400
    assert _einlader("probelauf") is None and _einlader("ivan") is None
