"""„Mit Google verbinden“ in der Oberflaeche (Task 9). Google ist gemockt."""
import base64
import logging
import os
import time
import urllib.parse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import google_kalender  # noqa: E402
import post_tresor  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

HOST_OK = "127.0.0.1:8791"
CODE = "CODE-GEHEIM-4711"
REFRESH = "1//" + "r" * 509                      # 512 Zeichen
ZUGRIFF = "ya29.ZUGRIFF-GEHEIM-0815"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_konten, "
                     "sales_test.benutzer cascade")
    monkeypatch.setenv("POST_BESITZER", "felix")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_konten, "
                     "sales_test.benutzer cascade")


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def paar():
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    privat = k.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    oeff = k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    return (base64.b64encode(privat).decode(), base64.b64encode(oeff).decode())


@pytest.fixture
def eingerichtet(monkeypatch, paar):
    monkeypatch.setenv("GOOGLE_KALENDER_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("GOOGLE_KALENDER_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv("UI_BASIS_URL", "https://ui.example.test")
    monkeypatch.setenv("KALENDER_SCHLUESSEL_OEFFENTLICH", paar[1])
    return paar


@pytest.fixture
def google(monkeypatch):
    """Ersetzt die Google-Aufrufe und zaehlt sie."""
    z = {"aufrufe": 0, "liste": [
        {"id": "ivan@example.test", "name": "Ivan", "primaer": True},
        {"id": "team@group.calendar.google.com", "name": "Team", "primaer": False},
    ], "refresh": REFRESH, "fehler": None}

    def tauschen(code):
        z["aufrufe"] += 1
        if z["fehler"]:
            raise z["fehler"]
        assert code == CODE
        return {"refresh_token": z["refresh"], "access_token": ZUGRIFF}

    def liste(access):
        z["aufrufe"] += 1
        assert access == ZUGRIFF
        return z["liste"]

    monkeypatch.setattr(google_kalender, "code_tauschen", tauschen)
    monkeypatch.setattr(google_kalender, "kalender_liste", liste)
    return z


def _angemeldet(name, rolle="kalender", passwort="pw-fuer-tests-9"):
    import benutzer_anlegen
    assert benutzer_anlegen.anlegen(name, rolle, passwort).startswith("OK")
    c = TestClient(ui.app)
    r = c.post("/login", data={"name": name, "passwort": passwort,
                               "csrf": ui.CSRF_TOKEN},
               headers={"host": HOST_OK}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _get(c, pfad):
    return c.get(pfad, headers={"host": HOST_OK}, follow_redirects=False)


def _post(c, pfad, daten, csrf=True):
    d = dict(daten, csrf=ui.CSRF_TOKEN) if csrf else dict(daten)
    return c.post(pfad, data=d, headers={"host": HOST_OK},
                  follow_redirects=False)


def _zurueck(c, name, **extra):
    q = {"code": CODE, "state": ui._google_state(name)}
    q.update(extra)
    return _get(c, "/team/kalender/google/zurueck?" + urllib.parse.urlencode(q))


def _applog(caplog) -> str:
    """Nur was die App loggt - die Zeilen des Test-Clients (httpx) nennen die
    Adresse, die der Test selbst aufruft (im Betrieb ist access_log aus)."""
    return chr(10).join(r.getMessage() for r in caplog.records
                     if not r.name.startswith(("httpx", "asyncio")))


def _konten():
    return server._q("select * from kalender_konten")


def _quellen():
    return server._q("select * from kalender_quellen")


def _konto_id(antwort):
    """Die Auswahlseite steht hinter einem 303 mit ?konto=<uuid>."""
    assert antwort.status_code == 303, antwort.text
    return urllib.parse.parse_qs(
        urllib.parse.urlparse(antwort.headers["location"]).query)["konto"][0]


# --- State -----------------------------------------------------------------

def test_state_eines_anderen_wird_abgewiesen(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    r = _get(c, "/team/kalender/google/zurueck?" + urllib.parse.urlencode(
        {"code": CODE, "state": ui._google_state("felix")}))
    assert r.status_code == 400
    assert google["aufrufe"] == 0
    assert _konten() == [] and _quellen() == []


def test_abgelaufener_state(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    alt = ui._google_state("ivan", jetzt=time.time() - 11 * 60)
    r = _get(c, "/team/kalender/google/zurueck?" + urllib.parse.urlencode(
        {"code": CODE, "state": alt}))
    assert r.status_code == 400
    assert google["aufrufe"] == 0 and _konten() == []


def test_manipulierter_oder_fehlender_state(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    s = ui._google_state("ivan")
    for schlecht in (s[:-2] + ("aa" if not s.endswith("aa") else "bb"),
                     "", "a.b.c.d", "Müll", s + "x"):
        r = _get(c, "/team/kalender/google/zurueck?" + urllib.parse.urlencode(
            {"code": CODE, "state": schlecht}))
        assert r.status_code == 400
    r = _get(c, "/team/kalender/google/zurueck?code=" + CODE)
    assert r.status_code == 400
    assert google["aufrufe"] == 0 and _konten() == []


def test_state_pruefen_rundlauf():
    ui_secret = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "abc"
    try:
        assert ui._google_state_pruefen(ui._google_state("ivan")) == "ivan"
        s = ui._google_state("ivan")
        ui.UI_SESSION_SECRET = "anderes"
        assert ui._google_state_pruefen(s) is None
    finally:
        ui.UI_SESSION_SECRET = ui_secret


def test_zugriff_verweigert_ist_freundlich(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    r = _get(c, "/team/kalender/google/zurueck?error=access_denied&state=x")
    assert r.status_code == 200
    assert "nicht verbunden" in r.text.lower()
    assert google["aufrufe"] == 0 and _konten() == [] and _quellen() == []


# --- Start -----------------------------------------------------------------

def test_start_leitet_zu_google(scharf, eingerichtet):
    c = _angemeldet("ivan")
    r = _get(c, "/team/kalender/google/start")
    assert r.status_code == 303
    ziel = urllib.parse.urlparse(r.headers["location"])
    assert ziel.netloc == "accounts.google.com"
    state = urllib.parse.parse_qs(ziel.query)["state"][0]
    assert ui._google_state_pruefen(state) == "ivan"


def test_start_ohne_einrichtung_leitet_nicht_weiter(scharf, monkeypatch):
    monkeypatch.delenv("GOOGLE_KALENDER_CLIENT_ID", raising=False)
    c = _angemeldet("ivan")
    r = _get(c, "/team/kalender/google/start")
    assert r.status_code != 303 and "accounts.google.com" not in r.text
    assert "noch nicht eingerichtet" in r.text


def test_ohne_einrichtung_kein_knopf(scharf, monkeypatch):
    monkeypatch.delenv("KALENDER_SCHLUESSEL_OEFFENTLICH", raising=False)
    c = _angemeldet("ivan")
    seite = _get(c, "/team/kalender").text
    assert "Google-Anbindung ist noch nicht eingerichtet" in seite
    assert "/team/kalender/google/start" not in seite


def test_mit_einrichtung_knopf(scharf, eingerichtet):
    c = _angemeldet("ivan")
    seite = _get(c, "/team/kalender").text
    assert "/team/kalender/google/start" in seite
    assert "Mit Google verbinden" in seite
    assert "noch nicht eingerichtet" not in seite


# --- Rueckkehr: Token wird versiegelt ---------------------------------------

def test_token_wird_versiegelt_gespeichert(scharf, eingerichtet, google, caplog):
    caplog.set_level(logging.DEBUG)
    c = _angemeldet("ivan")
    r = _zurueck(c, "ivan")
    konto_id = _konto_id(r)
    zeilen = _konten()
    assert len(zeilen) == 1 and str(zeilen[0]["id"]) == konto_id
    z = zeilen[0]
    assert z["besitzer"] == "ivan" and z["adresse"] == "ivan@example.test"
    assert REFRESH not in z["zugang_versiegelt"]
    assert "r" * 40 not in z["zugang_versiegelt"]
    assert post_tresor.oeffnen(
        z["zugang_versiegelt"], base64.b64decode(eingerichtet[0]).decode()
    ) == REFRESH
    assert [k["id"] for k in z["kalender_liste"]] == [
        "ivan@example.test", "team@group.calendar.google.com"]
    # Nichts Geheimes in Redirect, Seite, Log.
    seite = _get(c, r.headers["location"]).text
    alles = r.text + str(dict(r.headers)) + seite + _applog(caplog)
    for geheim in (CODE, REFRESH, ZUGRIFF, z["zugang_versiegelt"]):
        assert geheim not in alles
    # Der Code bleibt nicht in der Adresszeile der Auswahl.
    assert "code=" not in r.headers["location"]


def test_google_fehler_zeigt_festen_text(scharf, eingerichtet, google):
    google["fehler"] = google_kalender.GoogleFehler(google_kalender.ABGELEHNT)
    c = _angemeldet("ivan")
    r = _zurueck(c, "ivan")
    assert r.status_code in (400, 502)
    assert google_kalender.ABGELEHNT in r.text
    assert _konten() == []


def test_fremde_ausnahme_wird_nicht_gezeigt_noch_geloggt(
        scharf, eingerichtet, google, caplog):
    caplog.set_level(logging.DEBUG)
    google["fehler"] = RuntimeError("TOKEN-LEAK-" + REFRESH)
    c = _angemeldet("ivan")
    r = _zurueck(c, "ivan")
    assert r.status_code >= 400
    assert "TOKEN-LEAK" not in r.text and "TOKEN-LEAK" not in _applog(caplog)
    assert CODE not in r.text and CODE not in _applog(caplog)
    assert _konten() == []


def test_kalender_ohne_eintraege(scharf, eingerichtet, google):
    google["liste"] = []
    c = _angemeldet("ivan")
    r = _zurueck(c, "ivan")
    assert r.status_code == 400 and _konten() == []


# --- Auswahl / Uebernehmen --------------------------------------------------

def _auswahl(c, name="ivan"):
    return _konto_id(_zurueck(c, name))


def test_auswahlseite_zeigt_pflicht_radios_und_escaped(scharf, eingerichtet, google):
    google["liste"] = [{"id": "x@example.test", "name": "<script>boese()</script>",
                        "primaer": True}]
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    seite = _get(c, f"/team/kalender/google/auswahl?konto={konto_id}").text
    assert "<script>boese" not in seite
    assert "&lt;script&gt;boese" in seite
    assert seite.count('type="radio"') == 2 and "Pflicht" in seite
    assert 'action="/team/kalender/google/uebernehmen"' in seite


def test_auswahlseite_fremdes_konto_403(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    d = _angemeldet("dora")
    r = _get(d, f"/team/kalender/google/auswahl?konto={konto_id}")
    assert r.status_code == 403
    assert "ivan@example.test" not in r.text


def test_uebernehmen_legt_quellen_an(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id,
        "wahl": ["ivan@example.test", "team@group.calendar.google.com"],
        "bereich_ivan@example.test": "privat",
        "bereich_team@group.calendar.google.com": "business"})
    assert r.status_code == 200
    assert "innerhalb einer Minute" in r.text
    q = {x["google_id"]: x for x in _quellen()}
    assert set(q) == {"ivan@example.test", "team@group.calendar.google.com"}
    assert q["ivan@example.test"]["bereich"] == "privat"
    assert q["team@group.calendar.google.com"]["bereich"] == "business"
    for x in q.values():
        assert x["art"] == "google" and x["url"] is None
        assert x["besitzer"] == "ivan" and str(x["konto_id"]) == konto_id
        assert x["aktiv"] is True
    assert {x["anzeigename"] for x in q.values()} == {"Ivan", "Team"}


def test_auswahl_ohne_bereich_abgewiesen(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id,
        "wahl": ["ivan@example.test", "team@group.calendar.google.com"],
        "bereich_ivan@example.test": "privat"})
    assert r.status_code == 400
    assert _quellen() == []
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["ivan@example.test"],
        "bereich_ivan@example.test": "egal"})
    assert r.status_code == 400 and _quellen() == []


def test_nichts_gewaehlt_abgewiesen(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {"konto_id": konto_id})
    assert r.status_code == 400 and _quellen() == []


def test_fremdes_konto_wird_abgewiesen(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    d = _angemeldet("dora")
    r = _post(d, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["ivan@example.test"],
        "bereich_ivan@example.test": "business"})
    assert r.status_code == 403
    assert _quellen() == []
    # Auch die Rolle freigeben nimmt kein fremdes Konto.
    chef = _angemeldet("chefin", "freigeben")
    r = _post(chef, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["ivan@example.test"],
        "bereich_ivan@example.test": "business"})
    assert r.status_code == 403 and _quellen() == []


def test_unbekannte_google_id_wird_abgewiesen(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id,
        "wahl": ["ivan@example.test", "fremd@example.test"],
        "bereich_ivan@example.test": "business",
        "bereich_fremd@example.test": "business"})
    assert r.status_code == 400
    assert _quellen() == []


def test_unbekanntes_konto_und_kaputte_id(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    for kid in ("00000000-0000-0000-0000-000000000000", "kein-uuid", ""):
        r = _post(c, "/team/kalender/google/uebernehmen", {
            "konto_id": kid, "wahl": ["a"], "bereich_a": "business"})
        assert r.status_code in (400, 403)
    assert _quellen() == []


def test_uebernehmen_ohne_csrf(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["ivan@example.test"],
        "bereich_ivan@example.test": "business"}, csrf=False)
    assert r.status_code == 403 and _quellen() == []


def test_uebernehmen_ist_kein_get(scharf, eingerichtet):
    c = _angemeldet("ivan")
    assert _get(c, "/team/kalender/google/uebernehmen").status_code == 405


def test_gleiche_namen_werden_unterscheidbar(scharf, eingerichtet, google):
    google["liste"] = [{"id": "a", "name": "Arbeit", "primaer": True},
                       {"id": "b", "name": "Arbeit", "primaer": False}]
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["a", "b"],
        "bereich_a": "business", "bereich_b": "privat"})
    assert r.status_code == 200
    assert len({x["anzeigename"] for x in _quellen()}) == 2


# --- Entfernen / Hinweis ----------------------------------------------------

def _konto_mit_quellen(n=2):
    kid = server.kalenderkonto_speichern(
        "ivan", "ivan@example.test", "VERSIEGELT-X",
        [{"id": f"k{i}", "name": f"K{i}", "primaer": i == 0} for i in range(n)])
    qs = [server.google_quelle_speichern(kid, f"k{i}", f"K{i}", "ivan", "business")
          for i in range(n)]
    return kid, qs


def test_letzte_quelle_entfernt_vernichtet_zugang():
    kid, (q1, q2) = _konto_mit_quellen()
    assert server.kalenderquelle_entfernen(q1, "ivan") is True
    assert server.kalender_konto_zugang(kid) == "VERSIEGELT-X"
    assert server.kalenderquelle_entfernen(q2, "ivan") is True
    assert _konten()[0]["zugang_versiegelt"] is None
    assert server.kalender_konto_zugang(kid) is None


def test_konto_lesen_und_speichern_ist_upsert():
    kid = server.kalenderkonto_speichern("ivan", "a@example.test", "V1", [])
    kid2 = server.kalenderkonto_speichern(
        "ivan", "a@example.test", "V2",
        [{"id": "z", "name": "Z", "primaer": True}])
    assert kid == kid2
    k = server.kalenderkonto_lesen(kid)
    assert k["besitzer"] == "ivan" and k["kalender_liste"][0]["id"] == "z"
    assert server.kalenderkonto_lesen("kein-uuid") is None
    assert server.kalenderkonto_lesen("00000000-0000-0000-0000-000000000000") is None


def test_hinweis_zugriff_entziehen_bei_google_quellen(scharf, eingerichtet):
    c = _angemeldet("ivan")
    assert "myaccount.google.com/permissions" not in _get(c, "/team/kalender").text
    _konto_mit_quellen(1)
    seite = _get(c, "/team/kalender").text
    assert "Zugriff bei Google entziehen: myaccount.google.com/permissions" in seite


def test_rollen_wache_laesst_schmale_rolle_uebernehmen(scharf, eingerichtet, google):
    # Dieselbe Regel wie beim Verbinden einer iCal-Adresse: die Rolle
    # `kalender` darf (sonst 403 "Nur Lesen").
    c = _angemeldet("ivan", "kalender")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["ivan@example.test"],
        "bereich_ivan@example.test": "privat"})
    assert r.status_code == 200 and len(_quellen()) == 1


# --- Fix-Runde 1: Entfernen loescht wirklich ---------------------------------

def _quelle_ids():
    return {str(x["id"]) for x in _quellen()}


def test_pausiert_a_entfernt_b_token_bleibt():
    kid, (a, b) = _konto_mit_quellen()
    assert server.kalenderquelle_pausieren(a, False, "ivan") is True
    assert server.kalenderquelle_entfernen(b, "ivan") is True
    assert _quelle_ids() == {a}                       # B ist wirklich weg
    assert server.kalender_konto_zugang(kid) == "VERSIEGELT-X"
    assert server.kalenderquelle_pausieren(a, True, "ivan") is True


def test_letzte_pausierte_quelle_entfernen_loescht_zeile_und_zugang():
    kid, (a, b) = _konto_mit_quellen()
    for q in (a, b):
        assert server.kalenderquelle_pausieren(q, False, "ivan") is True
    assert server.kalenderquelle_entfernen(a, "ivan") is True
    assert server.kalender_konto_zugang(kid) == "VERSIEGELT-X"
    assert server.kalenderquelle_entfernen(b, "ivan") is True
    assert _quellen() == []
    assert _konten()[0]["zugang_versiegelt"] is None


def test_entfernte_google_quelle_nicht_fortsetzbar_auch_nicht_fuer_freigeben():
    kid, (a,) = _konto_mit_quellen(1)
    assert server.kalenderquelle_entfernen(a, "ivan") is True
    assert server.kalenderquelle_pausieren(a, True, "ivan") is False
    assert server.kalenderquelle_pausieren(a, True, None) is False
    assert _quellen() == []


def test_freigeben_entfernt_fremde_google_quelle_samt_zugang():
    kid, (a,) = _konto_mit_quellen(1)
    server._q("insert into kalender_termine (quelle_id, beginn, ende) "
              "values (%s, now(), now()) returning quelle_id", (a,))
    assert server.kalenderquelle_entfernen(a, None) is True
    assert _quellen() == []
    assert server._q("select 1 from kalender_termine") == []
    assert _konten()[0]["zugang_versiegelt"] is None


def test_entfernen_fremder_quelle_bleibt_abgewiesen():
    kid, (a,) = _konto_mit_quellen(1)
    assert server.kalenderquelle_entfernen(a, "dora") is False
    assert _quelle_ids() == {a} and server.kalender_konto_zugang(kid)


# --- Fix-Runde 1: iCal unter Google-Namen -----------------------------------

def test_ical_unter_google_namen_wird_abgewiesen(scharf, eingerichtet, monkeypatch):
    import kalenderquellen
    kid, (a,) = _konto_mit_quellen(1)
    aufrufe = []
    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda *x, **k: aufrufe.append(1) or ([], None))
    c = _angemeldet("ivan")
    r = _post(c, "/team/kalender/verbinden", {
        "name": "K0", "url": "https://example.test/a.ics", "bereich": "privat"})
    assert r.status_code == 400
    assert "Diesen Namen trägt schon ein Google-Kalender" in r.text
    assert aufrufe == []
    q = _quellen()
    assert len(q) == 1 and q[0]["art"] == "google" and q[0]["url"] is None
    assert q[0]["bereich"] == "business"


def test_speichern_backstop_gegen_google_namen():
    _konto_mit_quellen(1)
    with pytest.raises(ValueError):
        server.kalenderquelle_speichern("K0", "https://example.test/a.ics",
                                        "ivan", "privat")
    q = _quellen()
    assert len(q) == 1 and q[0]["art"] == "google" and q[0]["url"] is None


# --- Fix-Runde 1: verwaiste Token -------------------------------------------

def test_konto_ohne_quellen_wird_nach_einer_stunde_aufgeraeumt():
    alt = server.kalenderkonto_speichern("ivan", "alt@example.test", "V-ALT", [])
    jung = server.kalenderkonto_speichern("ivan", "jung@example.test", "V-JUNG", [])
    mit = server.kalenderkonto_speichern("ivan", "mit@example.test", "V-MIT", [])
    server.google_quelle_speichern(mit, "x", "X", "ivan", "business")
    server._q("update kalender_konten set created_at = now() - interval '2 hours' "
              "where id in (%s, %s) returning id", (alt, mit))
    assert server.kalenderkonten_aufraeumen() == 1
    assert server.kalender_konto_zugang(alt) is None
    assert server.kalender_konto_zugang(jung) == "V-JUNG"
    assert server.kalender_konto_zugang(mit) == "V-MIT"
    assert server.kalenderkonten_aufraeumen() == 0


def test_neu_verbinden_erneuert_den_zeitstempel():
    kid = server.kalenderkonto_speichern("ivan", "a@example.test", "V1", [])
    server._q("update kalender_konten set created_at = now() - interval '5 hours' "
              "returning id")
    server.kalenderkonto_speichern("ivan", "a@example.test", "V2", [])
    assert server.kalenderkonten_aufraeumen() == 0
    assert server.kalender_konto_zugang(kid) == "V2"


def test_runde_raeumt_konten_auf(monkeypatch):
    import kalender_abgleich
    n = []
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda *a, **k: [])
    monkeypatch.setattr(server, "kalenderkonten_aufraeumen",
                        lambda: n.append(1) or 0)
    kalender_abgleich.runde()
    assert n == [1]


def test_runde_laeuft_weiter_wenn_aufraeumen_scheitert(monkeypatch):
    import kalender_abgleich

    def kaputt():
        raise RuntimeError("GEHEIM")
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda *a, **k: [])
    monkeypatch.setattr(server, "kalenderkonten_aufraeumen", kaputt)
    assert kalender_abgleich.runde() == {"quellen": 0, "fehler": 0}


def test_auswahl_hat_abbrechen_und_loescht_token(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    seite = _get(c, f"/team/kalender/google/auswahl?konto={konto_id}").text
    assert 'action="/team/kalender/google/abbrechen"' in seite
    r = _post(c, "/team/kalender/google/abbrechen", {"konto_id": konto_id})
    assert r.status_code == 303
    assert server.kalender_konto_zugang(konto_id) is None


def test_abbrechen_laesst_konto_mit_quellen_in_ruhe(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    server.google_quelle_speichern(konto_id, "ivan@example.test", "Ivan", "ivan", "privat")
    _post(c, "/team/kalender/google/abbrechen", {"konto_id": konto_id})
    assert server.kalender_konto_zugang(konto_id)


def test_abbrechen_fremdes_konto_und_ohne_csrf(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    d = _angemeldet("dora")
    assert _post(d, "/team/kalender/google/abbrechen",
                 {"konto_id": konto_id}).status_code == 403
    assert _post(c, "/team/kalender/google/abbrechen", {"konto_id": konto_id},
                 csrf=False).status_code == 403
    assert server.kalender_konto_zugang(konto_id)


# --- Fix-Runde 1: eigene Meldung fuer fremde google_id ----------------------

def test_fremde_google_id_hat_eigene_meldung(scharf, eingerichtet, google):
    c = _angemeldet("ivan")
    konto_id = _auswahl(c)
    r = _post(c, "/team/kalender/google/uebernehmen", {
        "konto_id": konto_id, "wahl": ["fremd@example.test"],
        "bereich_fremd@example.test": "business"})
    assert r.status_code == 400
    assert "Kalender gehört nicht zu diesem Konto" in r.text
    assert "Bereich fehlt" not in r.text and _quellen() == []
