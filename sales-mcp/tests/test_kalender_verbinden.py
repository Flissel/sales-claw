"""Der Kollege verbindet selbst — Spec §2.7, Pruefung 1 (Torschritt)."""
import os
from datetime import datetime, timedelta, timezone

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
        # dieser Datei stehen blieben. `leads`/`activities` mit dabei (W5,
        # Schlusspruefung 13.09.2026): der neue Sichtbarkeits-Test legt
        # echte Termine/Wiedervorlagen an (Muster: test_team_sicht.py::
        # ohne_kollegenquellen).
        conn.execute("truncate sales_test.kalender_quellen, "
                     "sales_test.benutzer, sales_test.leads, "
                     "sales_test.activities cascade")
    yield


@pytest.fixture(autouse=True)
def laden_besitzer(monkeypatch):
    """Ohne Anmeldung handelt der Laden-Besitzer (POST_BESITZER)."""
    monkeypatch.setenv("POST_BESITZER", "felix")


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


def _post_entfernen(daten):
    return CLIENT.post("/team/kalender/entfernen", data=daten,
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


class _FakeAntwort:
    """Attrappe fuer kalenderquellen._antwort_lesen: laesst das ECHTE
    hole() parsen und fenstern, ohne Netz zu brauchen (Muster:
    test_kalenderquellen.py::test_die_adresse_steht_in_keinem_fehlertext)."""

    def __init__(self, daten: bytes):
        self._daten = daten

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return self._daten[:n]


def _ics_zwei_termine(alt_beginn, alt_ende, zuk_beginn, zuk_ende) -> bytes:
    fmt = "%Y%m%dT%H%M%SZ"
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:uralt@test\r\n"
        f"DTSTART:{alt_beginn.strftime(fmt)}\r\n"
        f"DTEND:{alt_ende.strftime(fmt)}\r\n"
        "SUMMARY:Uralter Termin\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:kuenftig@test\r\n"
        f"DTSTART:{zuk_beginn.strftime(fmt)}\r\n"
        f"DTEND:{zuk_ende.strftime(fmt)}\r\n"
        "SUMMARY:Kuenftiger Termin\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n").encode("utf-8")


def test_verbinden_meldet_die_zahl_der_termine(monkeypatch):
    """Der Kern von §2.7: sofortige Rueckmeldung im Klartext.

    K2 (Schlusspruefung 13.09.2026): der bisherige Test stubbte `hole()`
    komplett und lieferte GENAU EINEN kuenftigen Termin — der aelteste war
    darin zufaellig auch der naechste, und der eigentliche Fehler (hole()
    ohne Zeitfenster liefert den AELTESTEN Termin der GANZEN Historie als
    "naechsten") blieb unsichtbar. Hier laeuft das ECHTE hole() (nur das
    Netz ist ersetzt, ueber _antwort_lesen) mit einem ueber 5 Jahre alten
    Termin UND einem kuenftigen — vor dem Fix waere "Uralter Termin" der
    gemeldete "naechste" gewesen (aufsteigend sortiert, kein Fenster).
    """
    jetzt = datetime.now(timezone.utc)
    monkeypatch.setattr(kalenderquellen, "_ziel_erlaubt",
                        lambda url: (True, None))
    monkeypatch.setattr(kalenderquellen, "_antwort_lesen", lambda url: (
        _FakeAntwort(_ics_zwei_termine(
            jetzt - timedelta(days=2000),
            jetzt - timedelta(days=2000) + timedelta(hours=1),
            jetzt + timedelta(days=10),
            jetzt + timedelta(days=10, hours=1)))))
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    # Nur der kuenftige Termin liegt im Fenster — die Zahl bezieht sich auf
    # dasselbe Fenster, das /kalender spaeter benutzt (K2-Ruling).
    assert "1 Termin" in antwort.text
    assert "Uralter Termin" not in antwort.text
    assert "Kuenftiger Termin" in antwort.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"


def _ics_serie_und_normal(normal_beginn, normal_ende, serie_beginn,
                          serie_ende) -> bytes:
    fmt = "%Y%m%dT%H%M%SZ"
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:normal@test\r\n"
        f"DTSTART:{normal_beginn.strftime(fmt)}\r\n"
        f"DTEND:{normal_ende.strftime(fmt)}\r\n"
        "SUMMARY:Normaler Termin\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:teamrunde@test\r\n"
        f"DTSTART:{serie_beginn.strftime(fmt)}\r\n"
        f"DTEND:{serie_ende.strftime(fmt)}\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO\r\n"
        "SUMMARY:Teamrunde\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n").encode("utf-8")


def test_verbinden_loest_serientermin_auf_ohne_hinweis(
        monkeypatch):
    """BLOCKER (Koordinator-Fix-Runde, 13.09.2026): seit K4 meldet hole()
    `fehler` auch dann, wenn die Quelle VOLLSTAENDIG verstanden wurde und
    nur zusaetzlich eine Serie enthaelt — ui.py behandelte jeden `fehler`
    bisher als Totalausfall ("Nichts wurde gespeichert"). Ein gewoehnlicher
    Google-/Outlook-Kalender mit einer woechentlichen Teamrunde war damit
    GAR NICHT MEHR verbindbar — Spec-Pruefpunkt 1, der Torschritt.

    Echtes ICS mit RRULE UND einem gewoehnlichen Termin durch die
    tatsaechliche Route, nicht durch einen vollstaendig gestubbten
    hole() — der stubbt genau die Fensterung/Zaehlung weg, um die es hier
    geht."""
    jetzt = datetime.now(timezone.utc)
    monkeypatch.setattr(kalenderquellen, "_ziel_erlaubt",
                        lambda url: (True, None))
    monkeypatch.setattr(kalenderquellen, "_antwort_lesen", lambda url: (
        _FakeAntwort(_ics_serie_und_normal(
            jetzt + timedelta(days=3), jetzt + timedelta(days=3, hours=1),
            jetzt + timedelta(days=5), jetzt + timedelta(days=5, hours=1)))))
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    # Gespeichert — nicht abgewiesen.
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"
    assert "Nichts wurde gespeichert" not in antwort.text
    # Task 3: die Serie wird aufgeloest (woechentlich im 60-Tage-Fenster:
    # mehr als ein Vorkommen), der alte Vorbehalt entfaellt.
    assert "Normaler Termin" in antwort.text
    assert "Serientermin" not in antwort.text
    assert "RRULE" not in antwort.text


def test_falscher_link_wird_benannt_nicht_nur_abgewiesen(monkeypatch):
    """Der haeufigste Bedienfehler. 'Ungueltig' hilft niemandem weiter."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: (
        [], "Dort liegt kein Kalender, sondern eine Webseite."))
    antwort = _post({"name": "Ivan", "url": "https://example.test/",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200
    assert "Webseite" in antwort.text
    assert server.kalenderquellen_lesen(nur_aktive=False) == []


def test_die_adresse_erscheint_nach_dem_speichern_nirgends(monkeypatch):
    """Spec §4: sie ist ein Schluessel, kein Anzeigewert — auch nicht fuer
    den Betreiber."""
    geheim = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "Ivan", "url": geheim, "bereich": "business", "csrf": ui.CSRF_TOKEN})
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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "  ", "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen() == []


def test_reservierter_name_wird_abgewiesen(monkeypatch):
    """W4 (Schlusspruefung 13.09.2026): 'Betreiber' ist der Anzeigename der
    EIGENEN Quelle (server.EIGENE_QUELLE) — nennt sich ein Kollege so,
    landeten seine Fremdtermine in der Paarung des eigenen Kalenders (ui.py
    paart ausschliesslich ueber diesen Namen, nicht ueber den Besitzer)."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "Betreiber", "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400, antwort.text
    assert server.kalenderquellen_lesen() == []


def test_reservierter_name_wird_case_insensitiv_abgewiesen(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "  betreiber  ",
                     "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400, antwort.text
    assert server.kalenderquellen_lesen() == []


def test_entfernen_knopf_steht_je_aktiver_quelle_auf_der_seite(monkeypatch):
    """W3 (Schlusspruefung 13.09.2026): je Quelle ein Knopf auf der
    Verbindungsseite selbst — vorher gab es dafuer ueberhaupt keinen
    Aufrufer ausserhalb der Tests."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    _post({"name": "Ivan", "url": "https://example.test/a.ics",
          "bereich": "business", "csrf": ui.CSRF_TOKEN})
    seite = _get("/team/kalender").text
    assert 'action="/team/kalender/entfernen"' in seite
    quelle_id = server.kalenderquellen_lesen()[0]["id"]
    assert f'value="{quelle_id}"' in seite


def test_entfernen_deaktiviert_die_quelle(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    _post({"name": "Ivan", "url": "https://example.test/a.ics",
          "bereich": "business", "csrf": ui.CSRF_TOKEN})
    quelle_id = server.kalenderquellen_lesen()[0]["id"]
    antwort = _post_entfernen({"quelle_id": quelle_id, "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 303, antwort.text
    assert server.kalenderquellen_lesen() == []
    # Nicht geloescht, nur deaktiviert (Gegen-Ereignis) — die Zeile bleibt,
    # zaehlt aber nicht mehr als aktive Quelle.
    alle = server.kalenderquellen_lesen(nur_aktive=False)
    assert len(alle) == 1 and alle[0]["aktiv"] is False


def test_entfernen_ohne_csrf_passiert_nichts(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    _post({"name": "Ivan", "url": "https://example.test/a.ics",
          "bereich": "business", "csrf": ui.CSRF_TOKEN})
    quelle_id = server.kalenderquellen_lesen()[0]["id"]
    antwort = _post_entfernen({"quelle_id": quelle_id})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen()[0]["aktiv"] is True


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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))

    def _wirft(*a):
        raise psycopg.errors.UniqueViolation(
            f"duplicate key value violates unique constraint "
            f'"kalender_quellen_url_key" DETAIL: Key (url)=({geheim}) '
            f"already exists.")
    monkeypatch.setattr(server, "kalenderquelle_speichern", _wirft)
    antwort = _post({"name": "Ivan", "url": geheim, "bereich": "business", "csrf": ui.CSRF_TOKEN})
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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    verbunden = client.post(
        "/team/kalender/verbinden",
        data={"name": "Ivan", "url": "https://example.test/a.ics",
              "bereich": "business", "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert verbunden.status_code == 200, verbunden.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"

    # Entfernen (W3) ist dieselbe Ausnahme wie Verbinden — sonst kann
    # ausgerechnet diese Rolle die eigene tote Quelle nicht loswerden.
    quelle_id = server.kalenderquellen_lesen()[0]["id"]
    entfernt = client.post(
        "/team/kalender/entfernen",
        data={"quelle_id": quelle_id, "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert entfernt.status_code == 303, entfernt.text
    assert server.kalenderquellen_lesen() == []


def test_rolle_kalender_sieht_termine_aber_keine_wiedervorlagen_oder_anfragen(
        scharf):
    """W5 (Schlusspruefung 13.09.2026): der eine Pfad, den die schmale
    Rolle betreten darf (/kalender), lieferte Kontaktnamen, Themen samt
    Ort UND (scheibchenweise) den restlichen Kundenstamm mit: rohe
    Anfragetexte ("Ohne festes Datum") und offene Wiedervorlagen samt
    Notiz. Termine mit Kunde/Thema/Ort sind gewollt (Spec §4, Betreiber-
    Wahl "Alles"); Wiedervorlagen und rohe Anfragen sind keine Termindaten
    und genau das, wovor diese Rolle ferngehalten werden sollte."""
    heute = datetime.now(timezone.utc).date()
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('W5-Testkontakt', '+491701119999', 'whatsapp') returning id"
    )[0]["id"]
    # Ein gewoehnlicher, DATIERTER Termin — Spec §4 will genau das sehen.
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s)",
        (lead, server._json({
            "datum": (heute + timedelta(days=3)).isoformat(),
            "uhrzeit": "10:00", "thema": "W5-SICHTBARES-THEMA",
            "ort": "W5-SICHTBARER-ORT", "uid": "w5-termin"})))
    # Eine Terminanfrage OHNE Datum — traegt den rohen eingegangenen Text.
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s)",
        (lead, server._json({
            "inhalt": "W5-GEHEIMER-ANFRAGETEXT"})))
    server.wiedervorlage_setzen(
        lead, heute.isoformat(), "W5-GEHEIME-WIEDERVORLAGE-NOTIZ")

    _benutzer_kalender()
    client = _client()
    _login(client, "ivan", "nur-kalender-9")
    seite = client.get("/kalender", headers={"host": HOST_OK}).text

    assert "W5-SICHTBARES-THEMA" in seite
    assert "W5-SICHTBARER-ORT" in seite
    assert "W5-GEHEIMER-ANFRAGETEXT" not in seite
    assert "W5-GEHEIME-WIEDERVORLAGE-NOTIZ" not in seite
    assert "Offene Wiedervorlagen" not in seite
    assert "Ohne festes Datum" not in seite

    # Gegenprobe: fuer die volle Rolle ('lesen') stehen beide Abschnitte
    # weiterhin da (kein Kollateralschaden fuer den Betreiber selbst).
    # Eigener Client + eigenes Konto, damit die scharf geschaltete Wache
    # (UI_SESSION_SECRET) auch diese Anfrage authentifiziert verlangt.
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen("betreiberin", "lesen", "voller-zugriff-9")
    assert meldung.startswith("OK"), meldung
    voller_client = _client()
    _login(voller_client, "betreiberin", "voller-zugriff-9")
    voll = voller_client.get("/kalender", headers={"host": HOST_OK}).text
    assert "W5-GEHEIMER-ANFRAGETEXT" in voll
    assert "W5-GEHEIME-WIEDERVORLAGE-NOTIZ" in voll


# --- Leichter machen (29.09.2026) -------------------------------------------

def test_seite_hat_genau_eine_ueberschrift():
    seite = _get("/team/kalender").text
    assert seite.count("<h1>") == 1


def test_seite_fuehrt_in_nummerierten_schritten():
    seite = _get("/team/kalender").text
    assert "<ol" in seite
    # Erst Anbieter, dann Adresse einfuegen, dann pruefen — in dieser Reihenfolge.
    assert (seite.index("Anbieter") < seite.index('name="url"')
            < seite.index("Verbinden und prüfen"))


def test_jeder_anbieter_hat_einen_direkten_link_zu_den_einstellungen():
    seite = _get("/team/kalender").text
    for link in ("https://calendar.google.com/calendar/r/settings",
                 "https://www.icloud.com/calendar",
                 "https://outlook.live.com/calendar/0/options/calendar/SharedCalendars"):
        assert link in seite, link
    # Neuer Tab: die eingefuegte Adresse soll hier nicht verloren gehen.
    assert 'target="_blank" rel="noopener noreferrer"' in seite


def test_name_ist_mit_dem_angemeldeten_benutzer_vorbelegt(scharf):
    name = _benutzer_kalender("ivan", "nur-kalender-9")
    client = _client()
    assert _login(client, name, "nur-kalender-9").status_code == 303
    seite = client.get("/team/kalender", headers={"host": HOST_OK}).text
    assert 'name="name"' in seite and 'value="ivan"' in seite


def test_ohne_anmeldung_bleibt_der_name_leer():
    seite = _get("/team/kalender").text
    assert 'value="betreiber-ui"' not in seite


# --- Task 6: Besitzer und Bereich ------------------------------------------

def _leer_hole(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))


def _angemeldet(name, rolle, passwort="pw-fuer-tests-9"):
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen(name, rolle, passwort)
    assert meldung.startswith("OK"), meldung
    client = _client()
    assert _login(client, name, passwort).status_code == 303
    return client


def _client_post(client, pfad, daten):
    return client.post(pfad, data=dict(daten, csrf=ui.CSRF_TOKEN),
                       headers={"host": HOST_OK}, follow_redirects=False)


def _quelle_von(besitzer, name, bereich="privat", url="https://example.test/x.ics"):
    return server.kalenderquelle_speichern(name, url, besitzer, bereich)


def test_bereich_ist_pflicht(monkeypatch):
    _leer_hole(monkeypatch)
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert "Business oder Privat wählen" in antwort.text
    assert server.kalenderquellen_lesen(nur_aktive=False) == []


def test_besitzer_ist_angemeldete_person(scharf, monkeypatch):
    _leer_hole(monkeypatch)
    client = _angemeldet("ivan", "kalender")
    antwort = _client_post(client, "/team/kalender/verbinden", {
        "name": "felix", "url": "https://example.test/a.ics",
        "bereich": "privat"})
    assert antwort.status_code == 200, antwort.text
    zeilen = server.kalenderquellen_lesen()
    assert len(zeilen) == 1
    assert zeilen[0]["besitzer"] == "ivan"
    assert zeilen[0]["anzeigename"] == "felix"
    assert zeilen[0]["bereich"] == "privat"


def test_ohne_anmeldung_und_ohne_laden_besitzer_wird_nichts_gespeichert(
        monkeypatch):
    _leer_hole(monkeypatch)
    monkeypatch.setenv("POST_BESITZER", "")
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "bereich": "privat", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen(nur_aktive=False) == []


def test_kalender_rolle_entfernt_fremde_quelle_nicht(scharf):
    qid = _quelle_von("felix", "Felix")
    client = _angemeldet("ivan", "kalender")
    antwort = _client_post(client, "/team/kalender/entfernen",
                           {"quelle_id": qid})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen()[0]["aktiv"] is True


def test_freigeben_entfernt_jede(scharf):
    qid = _quelle_von("felix", "Felix")
    client = _angemeldet("chefin", "freigeben")
    antwort = _client_post(client, "/team/kalender/entfernen",
                           {"quelle_id": qid})
    assert antwort.status_code == 303
    assert server.kalenderquellen_lesen() == []


def test_meine_kalender_zeigt_keine_adresse(scharf):
    geheim = "https://calendar.example/ical/GEHEIM777/basic.ics"
    _quelle_von("ivan", "Ivans Kalender", "business", geheim)
    _quelle_von("felix", "Felix Privat", "privat", geheim + "2")
    client = _angemeldet("ivan", "kalender")
    seite = client.get("/team/kalender", headers={"host": HOST_OK}).text
    assert "GEHEIM777" not in seite
    assert "Ivans Kalender" in seite
    assert "Business" in seite
    assert "noch nicht gelesen" in seite
    # Fremde Quellen stehen in der persoenlichen Liste nicht.
    assert "Felix Privat" not in seite


def test_team_liste_nur_fuer_freigeben(scharf):
    _quelle_von("felix", "Felix Privat", "privat")
    chefin = _angemeldet("chefin", "freigeben")
    seite = chefin.get("/team/kalender", headers={"host": HOST_OK}).text
    assert "Kalender im Team" in seite and "Felix Privat" in seite
    assert "felix" in seite
    ivan = _angemeldet("ivan", "kalender")
    assert "Kalender im Team" not in ivan.get(
        "/team/kalender", headers={"host": HOST_OK}).text


def test_bereich_wechseln_als_besitzer(scharf):
    qid = _quelle_von("ivan", "Ivan", "privat")
    client = _angemeldet("ivan", "kalender")
    antwort = _client_post(client, "/team/kalender/bereich",
                           {"quelle_id": qid, "bereich": "business"})
    assert antwort.status_code == 303
    assert server.kalenderquellen_lesen()[0]["bereich"] == "business"


def test_bereich_wechseln_fremde_quelle_403(scharf):
    qid = _quelle_von("felix", "Felix", "privat")
    client = _angemeldet("ivan", "kalender")
    antwort = _client_post(client, "/team/kalender/bereich",
                           {"quelle_id": qid, "bereich": "business"})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen()[0]["bereich"] == "privat"


def test_bereich_ungueltig_ist_400(scharf):
    qid = _quelle_von("ivan", "Ivan", "privat")
    client = _angemeldet("ivan", "kalender")
    antwort = _client_post(client, "/team/kalender/bereich",
                           {"quelle_id": qid, "bereich": "geheim"})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen()[0]["bereich"] == "privat"


def test_pausieren_und_fortsetzen(scharf):
    qid = _quelle_von("ivan", "Ivan")
    client = _angemeldet("ivan", "kalender")
    assert _client_post(client, "/team/kalender/pausieren",
                        {"quelle_id": qid, "aktiv": "0"}).status_code == 303
    assert server.kalenderquellen_lesen() == []
    seite = client.get("/team/kalender", headers={"host": HOST_OK}).text
    assert "Fortsetzen" in seite and "pausiert" in seite
    assert _client_post(client, "/team/kalender/pausieren",
                        {"quelle_id": qid, "aktiv": "1"}).status_code == 303
    assert len(server.kalenderquellen_lesen()) == 1


def test_pausieren_fremde_quelle_403(scharf):
    qid = _quelle_von("felix", "Felix")
    client = _angemeldet("ivan", "kalender")
    assert _client_post(client, "/team/kalender/pausieren",
                        {"quelle_id": qid, "aktiv": "0"}).status_code == 403
    assert server.kalenderquellen_lesen()[0]["aktiv"] is True


def test_neue_aktionen_ohne_csrf_passiert_nichts():
    qid = _quelle_von("felix", "Felix", "privat")
    for pfad, daten in (("/team/kalender/bereich", {"bereich": "business"}),
                        ("/team/kalender/pausieren", {"aktiv": "0"})):
        antwort = CLIENT.post(pfad, data=dict(daten, quelle_id=qid),
                              headers={"host": HOST_OK}, follow_redirects=False)
        assert antwort.status_code == 403
    zeile = server.kalenderquellen_lesen()[0]
    assert zeile["bereich"] == "privat" and zeile["aktiv"] is True


def test_ical_quelle_sofort_abgeglichen(monkeypatch):
    jetzt = datetime.now(timezone.utc)
    monkeypatch.setattr(kalenderquellen, "_ziel_erlaubt",
                        lambda url: (True, None))
    monkeypatch.setattr(kalenderquellen, "_antwort_lesen", lambda url: (
        _FakeAntwort(_ics_zwei_termine(
            jetzt - timedelta(days=2000),
            jetzt - timedelta(days=2000) + timedelta(hours=1),
            jetzt + timedelta(days=10),
            jetzt + timedelta(days=10, hours=1)))))
    antwort = _post({"name": "Felix", "url": "https://example.test/a.ics",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    quelle = server.kalenderquellen_lesen()[0]
    assert quelle["zuletzt_gelesen"] is not None
    zeilen = server._q("select titel from kalender_termine "
                       "where quelle_id = %s", (quelle["id"],))
    assert [z["titel"] for z in zeilen] == ["Kuenftiger Termin"]


def test_tippfehler_beim_neu_verbinden_zerstoert_funktionierende_quelle_nicht(
        monkeypatch):
    url_a = "https://example.test/a-gut.ics"
    qid = server.kalenderquelle_speichern("Felix", url_a, "felix", "business")
    jetzt = datetime.now(timezone.utc)
    server.kalendertermine_ersetzen(qid, [{
        "uid": "u1", "beginn": jetzt + timedelta(days=1),
        "ende": jetzt + timedelta(days=1, hours=1), "titel": "Bleibt"}], True)
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: (
        [], "Dort liegt kein Kalender, sondern eine Webseite."))
    antwort = _post({"name": "Felix", "url": "https://example.test/b-kaputt",
                     "bereich": "business", "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200
    assert "Nichts wurde gespeichert" in antwort.text
    zeile = server.kalenderquellen_lesen(nur_aktive=False)
    assert len(zeile) == 1
    assert zeile[0]["aktiv"] is True
    assert zeile[0]["url"] == url_a
    titel = [z["titel"] for z in server._q(
        "select titel from kalender_termine where quelle_id = %s", (qid,))]
    assert titel == ["Bleibt"]
