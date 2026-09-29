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
                     "csrf": ui.CSRF_TOKEN})
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


def test_verbinden_speichert_trotz_serientermin_und_zeigt_den_hinweis(
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
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    # Gespeichert — nicht abgewiesen.
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"
    assert "Nichts wurde gespeichert" not in antwort.text
    # Der verstandene Termin zaehlt und wird genannt ...
    assert "1 Termin" in antwort.text
    assert "Normaler Termin" in antwort.text
    # ... der Vorbehalt steht DANEBEN, nicht als Totalabweisung.
    assert "Serientermin" in antwort.text
    assert "RRULE" in antwort.text


def test_falscher_link_wird_benannt_nicht_nur_abgewiesen(monkeypatch):
    """Der haeufigste Bedienfehler. 'Ungueltig' hilft niemandem weiter."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: (
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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "  ", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen() == []


def test_reservierter_name_wird_abgewiesen(monkeypatch):
    """W4 (Schlusspruefung 13.09.2026): 'Betreiber' ist der Anzeigename der
    EIGENEN Quelle (server.EIGENE_QUELLE) — nennt sich ein Kollege so,
    wuerde `kalenderquelle_speichern`s `on conflict (anzeigename)` seine
    Fremdtermine mit dem eigenen Kalender verschmelzen (ui.py paart
    ausschliesslich ueber diesen Namen)."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "Betreiber", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400, antwort.text
    assert server.kalenderquellen_lesen() == []


def test_reservierter_name_wird_case_insensitiv_abgewiesen(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    antwort = _post({"name": "  betreiber  ",
                     "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400, antwort.text
    assert server.kalenderquellen_lesen() == []


def test_entfernen_knopf_steht_je_aktiver_quelle_auf_der_seite(monkeypatch):
    """W3 (Schlusspruefung 13.09.2026): je Quelle ein Knopf auf der
    Verbindungsseite selbst — vorher gab es dafuer ueberhaupt keinen
    Aufrufer ausserhalb der Tests."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    _post({"name": "Ivan", "url": "https://example.test/a.ics",
          "csrf": ui.CSRF_TOKEN})
    seite = _get("/team/kalender").text
    assert 'action="/team/kalender/entfernen"' in seite
    quelle_id = server.kalenderquellen_lesen()[0]["id"]
    assert f'value="{quelle_id}"' in seite


def test_entfernen_deaktiviert_die_quelle(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    _post({"name": "Ivan", "url": "https://example.test/a.ics",
          "csrf": ui.CSRF_TOKEN})
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
          "csrf": ui.CSRF_TOKEN})
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
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([], None))
    verbunden = client.post(
        "/team/kalender/verbinden",
        data={"name": "Ivan", "url": "https://example.test/a.ics",
              "csrf": ui.CSRF_TOKEN},
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
