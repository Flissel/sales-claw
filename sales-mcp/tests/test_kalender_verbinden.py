"""Der Kollege verbindet selbst — Spec §2.7, Pruefung 1 (Torschritt)."""
import os

import psycopg
import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalenderquellen  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
# RED-Befund (Umsetzer, Task 5): ohne expliziten Host-Header antwortet die
# HostWache mit 421 (Falscher Host) — TestClient() setzt sonst "testserver"
# als Host. Jede andere Testdatei hier (test_freigaben.py, test_heute.py,
# test_darstellung.py, ...) setzt deshalb denselben Header von Hand; der
# Plantext hatte ihn hier vergessen.
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        # `benutzer` mit dabei (Fix-Runde 1, KRITISCH 3): der neue
        # Anmelde-Test legt echte Konten an, die sonst zwischen den Tests
        # dieser Datei stehen blieben.
        conn.execute("truncate sales_test.kalender_quellen, "
                     "sales_test.benutzer cascade")
    yield


@pytest.fixture
def scharf():
    """Anmeldung fuer die Dauer eines Tests scharf schalten (Muster aus
    test_login.py::scharf) — der Weg ueber /login existiert nur, wenn
    UI_SESSION_SECRET gesetzt ist; ohne das laeuft die Wache im
    durchlaessigen Uebergangszustand und niemand meldet sich wirklich an."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(daten):
    return CLIENT.post("/team/kalender/verbinden", data=daten,
                       headers={"host": HOST_OK}, follow_redirects=False)


def _client():
    # Eigener Client je Anmelde-Test (Muster aus test_login.py::_client) —
    # die Sitzung lebt im Cookie-Glas des Clients, geteilte Sitzungen
    # zwischen Tests waeren ein stiller Fehler.
    return TestClient(ui.app)


def _benutzer_kalender(name="ivan", passwort="nur-kalender-9"):
    # Ueber benutzer_anlegen.anlegen() statt per Roh-SQL (Fix-Runde 1,
    # KRITISCH 3): das ist der Weg, den ein Mensch tatsaechlich geht
    # (deploy/benutzer-anlegen.sh ruft exakt das auf) — und belegt
    # nebenbei, dass KRITISCH 1 (ROLLEN kannte 'kalender' nicht) behoben
    # ist, statt es nur per isoliertem Test auf ROLLEN zu behaupten.
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen(name, "kalender", passwort)
    assert meldung.startswith("OK"), meldung
    return name


def _login(client, name, passwort, csrf=None):
    return client.post(
        "/login",
        data={"name": name, "passwort": passwort,
              "csrf": ui.CSRF_TOKEN if csrf is None else csrf},
        headers={"host": HOST_OK}, follow_redirects=False)


def test_seite_erklaert_den_weg_je_anbieter():
    seite = _get("/team/kalender").text
    assert "Google" in seite and "Apple" in seite and "Outlook" in seite
    # Der genaue Klickweg, nicht nur der Name des Anbieters.
    assert "Geheime Adresse im iCal-Format" in seite


def test_verbinden_meldet_die_zahl_der_termine(monkeypatch):
    """Der Kern von §2.7: sofortige Rueckmeldung im Klartext."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": __import__("datetime").datetime(2026, 10, 1, 9,
         tzinfo=__import__("datetime").timezone.utc),
         "ende": __import__("datetime").datetime(2026, 10, 1, 10,
         tzinfo=__import__("datetime").timezone.utc),
         "titel": "A", "ort": "", "uid": "x"}], None))
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    assert "1 Termin" in antwort.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"


def test_falscher_link_wird_benannt_nicht_nur_abgewiesen(monkeypatch):
    """Der haeufigste Bedienfehler. 'Ungueltig' hilft niemandem weiter."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: (
        [], "Dort liegt kein Kalender, sondern eine Webseite."))
    antwort = _post({"name": "Ivan", "url": "https://example.test/",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200
    assert "Webseite" in antwort.text
    assert server.kalenderquellen_lesen() == []


def test_die_adresse_erscheint_nach_dem_speichern_nirgends(monkeypatch):
    """Spec §4: sie ist ein Schluessel, kein Anzeigewert — auch nicht fuer
    den Betreiber."""
    geheim = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    antwort = _post({"name": "Ivan", "url": geheim, "csrf": ui.CSRF_TOKEN})
    # Gegenprobe (Pruefer, Fix-Runde 1): "die Adresse steht nirgends" haelt
    # auch dann, wenn das Speichern klanglos scheitert — dann steht ja
    # gar nichts da. Erst der Beleg, dass der POST ERFOLGREICH war UND die
    # Quelle wirklich in der Datenbank liegt, macht die Aussage ueber das
    # VERSTECKEN der Adresse wertvoll.
    assert antwort.status_code == 200, antwort.text
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1 and quellen[0]["anzeigename"] == "Ivan"
    assert quellen[0]["url"] == geheim
    assert "GEHEIM123" not in _get("/team/kalender").text


def test_ohne_csrf_passiert_nichts():
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics"})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen() == []


def test_leerer_name_wird_abgewiesen(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    antwort = _post({"name": "  ", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen() == []


def test_rolle_kalender_darf_die_seite_und_sonst_nichts():
    """Die vorhandene Rolle `lesen` 'sieht alles' — also auch saemtliche
    Kontakte und den Posteingang. Fuer einen Kollegen ist das zu viel."""
    assert ui._pfad_erlaubt("kalender", "/team/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kontakte") is False
    assert ui._pfad_erlaubt("kalender", "/posteingang") is False
    assert ui._pfad_erlaubt("kalender", "/freigaben") is False
    assert ui._pfad_erlaubt("lesen", "/kontakte") is True


def test_db_fehler_beim_speichern_traegt_die_adresse_nicht_nach_aussen(
        monkeypatch):
    """Aufgabe 1, offener Punkt: ein unbehandelter Datenbankfehler aus den
    Kalenderquellen-Helfern darf die geheime Adresse nicht in die
    Fehlerseite tragen — auch nicht ueber die DB-Fehlermeldung (DETAIL
    einer Unique-Verletzung nennt z.B. den Wert der Spalte)."""
    geheim = "https://calendar.google.com/ical/GEHEIM999/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))

    def _wirft(name, url):
        raise psycopg.errors.UniqueViolation(
            f"duplicate key value violates unique constraint "
            f'"kalender_quellen_url_key" DETAIL: Key (url)=({geheim}) '
            f"already exists.")
    monkeypatch.setattr(server, "kalenderquelle_speichern", _wirft)
    antwort = _post({"name": "Ivan", "url": geheim, "csrf": ui.CSRF_TOKEN})
    assert geheim not in antwort.text
    assert "GEHEIM999" not in antwort.text


def test_end_zu_end_anmeldung_rolle_kalender(scharf, monkeypatch):
    """KRITISCH 3 (Pruefer, Fix-Runde 1): keiner der obigen Tests meldet
    sich wirklich an — `_pfad_erlaubt` wurde bisher nur isoliert geprueft,
    waehrend `AnmeldeWache` mangels `UI_SESSION_SECRET` im durchlaessigen
    Uebergangszustand lief. Das hat KRITISCH 2 verdeckt (Redirect nach
    "/" waere fuer diese Rolle ein sofortiges 403). Dieser Test geht den
    ganzen Weg, den ein Mensch geht: Konto mit Rolle `kalender` anlegen,
    scharf schalten, ueber /login anmelden, dann pruefen, was diese Rolle
    wirklich sieht und tun darf."""
    _benutzer_kalender()
    client = _client()
    antwort = _login(client, "ivan", "nur-kalender-9")
    assert antwort.status_code == 303
    assert ui.SITZUNG_COOKIE in client.cookies

    # KRITISCH 2: die Zielseite der Anmeldung muss diese Rolle auch
    # wirklich sehen duerfen — kein 403 als Erstes nach dem Passwort.
    ziel = antwort.headers["location"]
    landung = client.get(ziel, headers={"host": HOST_OK})
    assert landung.status_code == 200, landung.text

    # /team/kalender ist erreichbar.
    assert client.get("/team/kalender",
                      headers={"host": HOST_OK}).status_code == 200

    # /kontakte und /posteingang sind es nicht — die Rolle ist schmal.
    assert client.get("/kontakte",
                      headers={"host": HOST_OK}).status_code == 403
    assert client.get("/posteingang",
                      headers={"host": HOST_OK}).status_code == 403

    # Verbinden per POST funktioniert trotz der allgemeinen Schreibsperre
    # fuer diese Rolle — die eine Ausnahme, die ihr gehoert.
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    verbunden = client.post(
        "/team/kalender/verbinden",
        data={"name": "Ivan", "url": "https://example.test/a.ics",
              "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert verbunden.status_code == 200, verbunden.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"
