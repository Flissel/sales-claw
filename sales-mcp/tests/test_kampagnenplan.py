"""Kampagnenkalender (17.10.2026, Marketing-Migration 071): Seite /marketing/plan
und der Block im Morgen-Digest. Der Client zur Marketing-API wird gefaelscht,
ebenso die Abfrage auf marketing.plan_anstehend (die Test-DB kennt kein
marketing-Schema)."""
import json
import os
from datetime import date, timedelta

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_plan  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
# Die Vergangenheitspruefung rechnet mit dem heutigen Tag, daher sind alle Schreib-Tests relativ zu heute.
ZUKUNFT = date.today() + timedelta(days=40)
Z_TEILE = {"tag": str(ZUKUNFT.day), "monat": str(ZUKUNFT.month), "jahr": str(ZUKUNFT.year)}
Z_MONAT = f"{ZUKUNFT:%Y-%m}"
PID = "22222222-2222-2222-2222-222222222222"
IID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.eintraege = [
            {"id": PID, "datum": "2026-10-22", "art": "newsletter", "titel": "Herbst-Newsletter",
             "notiz": "mit Podcast", "status": "vorschlag", "inhalt": None},
            {"id": "33333333-3333-3333-3333-333333333333", "datum": "2026-10-24", "art": "podcast",
             "titel": "Folge 2", "notiz": "", "status": "geplant", "inhalt": IID},
            {"id": "44444444-4444-4444-4444-444444444444", "datum": "2026-10-02", "art": "post",
             "titel": "<script>x</script>", "notiz": "", "status": "erledigt", "inhalt": None}]

    def anfrage(self, methode, pfad, daten=None, roh=False):
        self.aufrufe.append((methode, pfad, daten))
        if self.fehler:
            raise self.fehler
        if pfad == "/mandanten":
            return {"mandanten": [{"id": "vibemind", "name": "VibeMind", "aktiv": True},
                                  {"id": "fin2gether", "name": "fin2gether", "aktiv": True}]}
        if pfad.startswith("/plan?"):
            return {"eintraege": self.eintraege}
        if pfad == "/plan":
            return {"id": PID}
        if pfad.startswith("/plan/"):
            return {"status": (daten or {}).get("status") or "verschoben"}
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


# --- reine Hilfen ---------------------------------------------------------

@pytest.mark.parametrize("roh, erwartet", [
    ("2026-10", date(2026, 10, 1)), ("2026-02", date(2026, 2, 1)), ("", date(2026, 10, 1)),
    ("2026-13", date(2026, 10, 1)), ("abc", date(2026, 10, 1)), ("1800-01", date(2026, 10, 1)),
    ("2026-10-05", date(2026, 10, 1))])
def test_monat_lesen(roh, erwartet):
    assert ui_plan.monat_lesen(roh, heute=date(2026, 10, 17)) == erwartet


def test_monat_grenzen():
    assert ui_plan.monat_ende(date(2026, 2, 1)) == date(2026, 2, 28)
    assert ui_plan.monat_ende(date(2026, 12, 1)) == date(2026, 12, 31)
    assert ui_plan.nachbar(date(2026, 1, 1), -1) == "2025-12"
    assert ui_plan.nachbar(date(2026, 12, 1), 1) == "2027-01"


@pytest.mark.parametrize("roh, erwartet", [("podcast", "podcast"), ("fax", None), ("", None),
                                           (None, None), ("<script>", None)])
def test_art_lesen(roh, erwartet):
    assert ui_plan.art_lesen(roh) == erwartet


def test_zaehlen_ohne_abgesagte():
    e = [{"art": "post", "status": "geplant"}, {"art": "post", "status": "abgesagt"},
         {"art": "video", "status": "erledigt"}, {"art": "gibtsnicht", "status": "geplant"}]
    z = ui_plan.zaehlen(e, abgesagte=False)
    assert z["alle"] == 3 and z["post"] == 1 and z["video"] == 1 and z["sonstiges"] == 1
    assert ui_plan.zaehlen(e, abgesagte=True)["alle"] == 4


def test_nach_tagen_gruppiert_und_sortiert():
    e = [{"datum": "2026-10-24", "titel": "b"}, {"datum": "2026-10-22", "titel": "a"},
         {"datum": "2026-10-24", "titel": "c"}, {"datum": "kaputt", "titel": "d"}]
    g = ui_plan.nach_tagen(e)
    assert [t for t, _ in g] == [date(2026, 10, 22), date(2026, 10, 24), None]
    assert [p["titel"] for p in g[1][1]] == ["b", "c"]


@pytest.mark.parametrize("t, m, j, erwartet", [
    ("22", "10", "2026", "2026-10-22"), ("31", "2", "2026", None), ("31", "4", "2026", None),
    ("29", "2", "2027", None), ("29", "2", "2028", "2028-02-29"), ("x", "10", "2026", None),
    ("", "", "", None)])
def test_datum_aus_teilen(t, m, j, erwartet):
    assert ui_plan.datum_aus_teilen(t, m, j) == erwartet


def test_plan_pfad():
    assert ui_plan.plan_pfad(date(2026, 10, 1), None, False) == "/marketing/plan?monat=2026-10"
    assert ui_plan.plan_pfad(date(2026, 10, 1), "post", True) == "/marketing/plan?monat=2026-10&art=post&abgesagt=1"


# --- Seite ----------------------------------------------------------------

def test_menue_hat_plan():
    t = ui._AKTIVE_ROLLE.set("freigeben")
    try:
        assert 'href="/marketing/plan"' in ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(t)


def test_seite_zeigt_monat_und_knoepfe(angemeldet, pult):
    r = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST)
    s = r.text
    assert r.status_code == 200 and "<script" not in s.lower().replace("&lt;script&gt;", "")
    methode, pfad, _ = pult.aufrufe[-1]
    assert methode == "GET" and pfad.startswith("/plan?") and "mandant=vibemind" in pfad
    assert "von=2026-10-01" in pfad and "bis=2026-10-31" in pfad
    assert "Oktober 2026" in s and "monat=2026-09" in s and "monat=2026-11" in s
    assert "Herbst-Newsletter" in s and "mit Podcast" in s and "1 Vorschlag vom Agenten" in s
    # Vorschlag: uebernehmen/verwerfen; geplant: erledigt/absagen; erledigt: keine Knoepfe.
    assert 'value="uebernehmen"' in s and 'value="erledigt"' in s and 'value="verschieben"' in s
    assert s.count(f'action="/marketing/plan/{PID}"') == 3
    assert "/marketing/plan/44444444-4444-4444-4444-444444444444" not in s
    assert f'href="/marketing/entwurf/{IID}"' in s
    assert "&lt;script&gt;x&lt;/script&gt;" in s
    assert 'action="/marketing/plan/neu"' in s


def test_reiter_zeigen_anzahl_und_filtern(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=podcast", headers=HOST).text
    # Fixture: Newsletter-Vorschlag, Podcast, erledigter Post = 3 sichtbare, kein abgesagter.
    assert 'aria-current="page"' in s and "Podcast (1)" in s and "Alle (3)" in s
    assert "Folge 2" in s and "Herbst-Newsletter" not in s
    assert "monat=2026-09&amp;art=podcast" in s


def test_podcast_eintrag_verweist_auf_die_podcast_seite(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    # Fixture: genau ein Podcast-Eintrag, daneben Newsletter und Post - nur der Podcast bekommt den Link.
    assert s.count("Folgen ansehen") == 1
    assert '<a href="/marketing/podcast">Folgen ansehen</a>' in s
    nur_post = angemeldet.get("/marketing/plan?monat=2026-10&art=post", headers=HOST).text
    assert "Folgen ansehen" not in nur_post


def test_gruppen_nach_tag_mit_wochentag(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert s.index("Fr 2. Oktober") < s.index("Do 22. Oktober") < s.index("Sa 24. Oktober")


def test_leerer_monat_hat_leerzustand_mit_knopf(angemeldet, pult):
    pult.eintraege = []
    s = angemeldet.get("/marketing/plan?monat=2026-12", headers=HOST).text
    assert "plan-leer" in s and 'href="#neu"' in s and "nichts geplant" in s.lower()


def test_reiter_ohne_treffer_sagt_welche_art(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=video", headers=HOST).text
    assert "Video" in s and "plan-leer" in s


def test_abgesagte_nur_auf_wunsch(angemeldet, pult):
    pult.eintraege.append({"id": "55555555-5555-5555-5555-555555555555", "datum": "2026-10-25",
                           "art": "post", "titel": "Alt", "notiz": "", "status": "abgesagt", "inhalt": None})
    assert "Alt" not in angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert "Alt" in angemeldet.get("/marketing/plan?monat=2026-10&abgesagt=1", headers=HOST).text


def test_nur_abgesagte_hat_eigenen_leerzustand(angemeldet, pult):
    pult.eintraege = [{"id": "55555555-5555-5555-5555-555555555555", "datum": "2026-10-25",
                       "art": "post", "titel": "Alt", "notiz": "", "status": "abgesagt", "inhalt": None}]
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert "plan-leer" in s and "Abgesagte zeigen" in s and "Alt" not in s


@pytest.mark.parametrize("q", ["art=fax", "art=%3Cscript%3E", "monat=abc", "abgesagt=2"])
def test_manipulierte_parameter_fallen_zurueck(angemeldet, pult, q):
    r = angemeldet.get(f"/marketing/plan?{q}", headers=HOST)
    assert r.status_code == 200 and "<script>" not in r.text


def test_unbekannte_art_und_fehlendes_datum_ohne_absturz(angemeldet, pult):
    pult.eintraege = [{"id": "66666666-6666-6666-6666-666666666666", "datum": None, "art": "fax",
                       "titel": "Wirr", "notiz": "", "status": "geplant", "inhalt": None}]
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert "Wirr" in s and "Sonstiges (1)" in s and "Alle (1)" in s


def test_zurueck_traegt_reiter_in_den_knoepfen(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=newsletter", headers=HOST).text
    assert 'name="zurueck" value="/marketing/plan?monat=2026-10&amp;art=newsletter"' in s


def test_formular_hat_drei_datumsfelder_keinen_datepicker(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=video", headers=HOST).text
    assert 'name="datum_tag"' in s and 'name="datum_monat"' in s and 'name="datum_jahr"' in s
    assert 'type="date"' not in s
    assert '<option value="video" selected>' in s          # E5: Reiter = Vorgabe-Art
    assert 'name="reiter" value="video"' in s


def test_neu_aus_dreierauswahl(angemeldet, pult):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": Z_TEILE["tag"], "datum_monat": Z_TEILE["monat"], "datum_jahr": Z_TEILE["jahr"],
              "art": "podcast", "titel": "Folge 3", "notiz": "", "reiter": "podcast"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/plan?monat={Z_MONAT}&art=podcast"
    assert pult.aufrufe[-1][2]["datum"] == ZUKUNFT.isoformat()


def test_neu_andere_art_als_reiter_geht_auf_alle(angemeldet, pult):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": Z_TEILE["tag"], "datum_monat": Z_TEILE["monat"], "datum_jahr": Z_TEILE["jahr"],
              "art": "post", "titel": "T", "reiter": "podcast"})
    assert r.headers["location"] == f"/marketing/plan?monat={Z_MONAT}"


@pytest.mark.parametrize("t, m, j", [("31", "2", "2027"), ("31", "4", "2027"), ("29", "2", "2027"), ("1", "1", "2020")])
def test_neu_unmoegliches_oder_vergangenes_datum_422(angemeldet, pult, t, m, j):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": t, "datum_monat": m, "datum_jahr": j, "art": "post", "titel": "T"})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_verschieben_aus_dreierauswahl(angemeldet, pult):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "aktion": "verschieben", "neu_tag": Z_TEILE["tag"], "neu_monat": Z_TEILE["monat"], "neu_jahr": Z_TEILE["jahr"]})
    assert r.status_code == 303 and pult.aufrufe[-1] == ("POST", f"/plan/{PID}", {"datum": ZUKUNFT.isoformat()})


def test_verschieben_in_die_vergangenheit_422(angemeldet, pult):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "aktion": "verschieben", "neu_tag": "1", "neu_monat": "1", "neu_jahr": "2020"})
    assert r.status_code == 422 and not pult.aufrufe


def test_datum_felder_vorgabe_und_jahre():
    h = ui_plan.datum_felder("datum", date(2026, 10, 22), heute=date(2026, 10, 19))
    assert 'name="datum_tag"' in h and 'name="datum_monat"' in h and 'name="datum_jahr"' in h
    assert '<option value="22" selected>' in h and '<option value="10" selected>Oktober</option>' in h
    assert '<option value="2026" selected>' in h and '<option value="2028"' in h and '"2029"' not in h
    assert 'aria-label="Tag"' in h and 'aria-label="Monat"' in h and 'aria-label="Jahr"' in h


def test_seite_api_weg_503(angemeldet, pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    assert angemeldet.get("/marketing/plan", headers=HOST).status_code == 503


def test_neu_legt_fuer_gewaehlte_firma_an(angemeldet, pult):
    angemeldet.cookies.set("mk_mandant", "fin2gether", path="/marketing")
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "datum_tag": Z_TEILE["tag"], "datum_monat": Z_TEILE["monat"], "datum_jahr": Z_TEILE["jahr"],
                              "art": "podcast", "titel": " Folge 3 ", "notiz": "Gast"})
    assert r.status_code == 303 and r.headers["location"] == f"/marketing/plan?monat={Z_MONAT}"
    assert pult.aufrufe[-1] == ("POST", "/plan", {"mandant": "fin2gether", "datum": ZUKUNFT.isoformat(),
                                                 "art": "podcast", "titel": "Folge 3", "notiz": "Gast"})


@pytest.mark.parametrize("daten", [
    {"art": "fax", "titel": "T"},
    {"art": "post", "titel": "  "}])
def test_neu_prueft_vorher(angemeldet, pult, daten):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "datum_tag": "3", "datum_monat": "11",
                              "datum_jahr": "2026", **daten})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)


def test_neu_ohne_csrf_403(angemeldet, pult):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
                        data={"datum_tag": Z_TEILE["tag"], "datum_monat": Z_TEILE["monat"], "datum_jahr": Z_TEILE["jahr"], "art": "post", "titel": "T"})
    assert r.status_code == 403 and not pult.aufrufe


@pytest.mark.parametrize("aktion, erwartet", [
    ("uebernehmen", {"status": "geplant"}), ("erledigt", {"status": "erledigt"}),
    ("absagen", {"status": "abgesagt"})])
def test_aktionen(angemeldet, pult, aktion, erwartet):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "aktion": aktion, "zurueck": "/marketing/plan?monat=2026-10"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/plan?monat=2026-10"
    assert pult.aufrufe[-1] == ("POST", f"/plan/{PID}", erwartet)


def test_verschieben_schickt_nur_datum(angemeldet, pult):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "aktion": "verschieben", "neu_tag": Z_TEILE["tag"], "neu_monat": Z_TEILE["monat"], "neu_jahr": Z_TEILE["jahr"]})
    assert r.status_code == 303 and pult.aufrufe[-1] == ("POST", f"/plan/{PID}", {"datum": ZUKUNFT.isoformat()})


@pytest.mark.parametrize("daten", [
    {"aktion": "vorschlag"}, {"aktion": ""}, {"aktion": "verschieben", "neu_tag": "31", "neu_monat": "2", "neu_jahr": "2027"}])
def test_aktion_unbekannt_oder_ohne_datum_422(angemeldet, pult, daten):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, **daten})
    assert r.status_code == 422 and not pult.aufrufe


@pytest.mark.parametrize("ziel", ["//boese.de", "https://boese.de", "/marketing/entwuerfe", ""])
def test_aktion_boeses_ziel_geht_auf_plan(angemeldet, pult, ziel):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
                        data={"csrf": ui.CSRF_TOKEN, "aktion": "erledigt", "zurueck": ziel})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/plan"


def test_aktion_ohne_csrf_403(angemeldet, pult):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
                        data={"aktion": "erledigt"})
    assert r.status_code == 403 and not pult.aufrufe


# --- Morgen-Digest --------------------------------------------------------

def _plan_abfrage(monkeypatch, antwort):
    """Leitet nur die plan_anstehend-Abfrage um; alles andere geht an die Test-DB."""
    echt = server._q
    gesehen = []

    def q(sql, params=()):
        if "plan_anstehend" in sql:
            gesehen.append((sql, params))
            if isinstance(antwort, Exception):
                raise antwort
            return antwort
        return echt(sql, params)
    monkeypatch.setattr(server, "_q", q)
    return gesehen


def _db_da():
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus - der Digest braucht sie")


def test_digest_ohne_firma_ohne_block(monkeypatch):
    _db_da()
    monkeypatch.delenv("MARKETING_MANDANT", raising=False)
    gesehen = _plan_abfrage(monkeypatch, [])
    assert "kampagnenplan" not in json.loads(server.digest()) and not gesehen


def test_digest_nennt_anstehendes_der_eigenen_firma(monkeypatch):
    _db_da()
    monkeypatch.setenv("MARKETING_MANDANT", "vibemind")
    gesehen = _plan_abfrage(monkeypatch, [
        {"id": PID, "datum": "2026-10-22", "art": "newsletter", "titel": "Herbst", "status": "vorschlag",
         "entwurf_status": None},
        {"id": IID, "datum": "2026-10-24", "art": "podcast", "titel": "Folge 2", "status": "geplant",
         "entwurf_status": "freigegeben"}])
    plan = json.loads(server.digest())["kampagnenplan"]
    assert plan["anzahl"] == 2 and plan["vorschlaege"] == 1
    assert plan["eintraege"][1] == {"datum": "2026-10-24", "art": "podcast", "titel": "Folge 2",
                                    "status": "geplant", "entwurf": "freigegeben"}
    assert "/marketing/plan" in plan["hinweis"]
    assert gesehen and gesehen[0][1] == ("vibemind",)


def test_digest_ohne_recht_bleibt_ganz(monkeypatch):
    _db_da()
    monkeypatch.setenv("MARKETING_MANDANT", "vibemind")
    _plan_abfrage(monkeypatch, psycopg.errors.InsufficientPrivilege("permission denied"))
    d = json.loads(server.digest())
    assert d["kampagnenplan"]["anzahl"] is None and "42501" in d["kampagnenplan"]["hinweis"]
    assert "pipeline" in d and "offene_entwuerfe" in d


def test_hinweis_mit_umlaut_im_plural(angemeldet, pult):
    pult.eintraege.append({"id": "77777777-7777-7777-7777-777777777777", "datum": "2026-10-23", "art": "post",
                           "titel": "Zweiter", "notiz": "", "status": "vorschlag", "inhalt": None})
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert "2 Vorschläge vom Agenten" in s and "Vorschlage" not in s


def test_heute_chip_am_heutigen_tag(angemeldet, pult):
    h = date.today()
    pult.eintraege = [{"id": PID, "datum": h.isoformat(), "art": "post", "titel": "Jetzt", "notiz": "",
                       "status": "geplant", "inhalt": None}]
    s = angemeldet.get(f"/marketing/plan?monat={h:%Y-%m}", headers=HOST).text
    assert 'plan-chip heute">Heute</span>' in s
    pult.eintraege[0]["datum"] = (h + timedelta(days=1 if h.day < 28 else -1)).isoformat()
    assert 'plan-chip heute' not in angemeldet.get(f"/marketing/plan?monat={h:%Y-%m}", headers=HOST).text


def test_vorgaben_sind_nie_vergangen(angemeldet, pult):
    h = date.today()
    s = angemeldet.get("/marketing/plan?monat=2026-01", headers=HOST).text
    assert f'<option value="{h.day}" selected>' in s and f'<option value="{h.year}" selected>' in s


def test_verschieben_vorgabe_bei_vergangenem_eintrag_ist_heute(angemeldet, pult):
    h = date.today()
    pult.eintraege = [{"id": PID, "datum": "2026-01-05", "art": "post", "titel": "Alt", "notiz": "",
                       "status": "geplant", "inhalt": None}]
    s = angemeldet.get("/marketing/plan?monat=2026-01", headers=HOST).text
    teil = s.split('name="neu_tag"')[1].split("</select>")[0]
    assert f'<option value="{h.day}" selected>' in teil


def test_datum_felder_jahr_enthaelt_vorgabejahr():
    h = ui_plan.datum_felder("x", date(2031, 1, 2), heute=date(2026, 10, 19))
    assert '<option value="2031" selected>' in h
