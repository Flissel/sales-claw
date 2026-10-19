"""Kalender-Schnittstelle und Seite /kalender (Spec 2026-10-14, Task 4).

JSON-Routen fuer das Kalender-Paket: Ereignisse lesen, eigene und Kunden-
termine anlegen, aendern, loeschen/absagen, Videoraum, Kontaktsuche. Kern-
Zusage: jede Aenderung/Absage eines Kundentermins legt einen PENDING-Entwurf
an den Kunden an (oder einen Hinweis ohne Kanal) - versendet wird nichts.
Konflikte kommen zuerst (409), der Entwurf erst beim zweiten Aufruf."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import mail_dispatch  # noqa: E402  (nach `import server`, siehe test_termin_einladen)
import kalender  # noqa: E402
import kalender_sicht  # noqa: E402
import konferenz  # noqa: E402
import medien  # noqa: E402
import recherche  # noqa: E402
import ui  # noqa: E402
import ui_kalender  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
B = ZoneInfo("Europe/Berlin")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(tmp_path, monkeypatch):
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(tmp_path / "erzeugt"))
    for name in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server, "belegungen", lambda tage_voraus=60: ([], []))
    monkeypatch.setattr(server, "kalenderquellen_lesen", lambda nur_aktive=True: [])
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: ([], None))
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "buero@vibemind.space")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads, "
                     "sales_test.eigene_termine, sales_test.benutzer cascade")
    yield


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


# --- Helfer -----------------------------------------------------------------

def _get(pfad, client=CLIENT):
    return client.get(pfad, headers={"host": HOST_OK})


def _senden(methode, pfad, daten=None, csrf=True, client=CLIENT):
    koepfe = {"host": HOST_OK}
    if csrf:
        koepfe["x-csrf"] = ui.CSRF_TOKEN
    return client.request(methode, pfad, json=daten, headers=koepfe,
                          follow_redirects=False)


def _um(n, h, m=0):
    d = (datetime.now(B) + timedelta(days=n)).date()
    return datetime(d.year, d.month, d.day, h, m, tzinfo=B)


def _lead_mail(name="Ivan Kunde", email="ivan@vibemind.space"):
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values (%s, %s, '+491701234567', 'whatsapp', 'existing_customer') "
        "returning id", (name, email))[0]["id"])


def _lead_ohne_kanal(name="Kai Stumm"):
    return str(server._q(
        "insert into leads (name, source, consent_status) "
        "values (%s, 'whatsapp', 'existing_customer') returning id",
        (name,))[0]["id"])


def _kundentermin(lead, beginn, dauer=60, thema="Beratung", ort="Buero"):
    t = beginn.astimezone(B)
    return json.loads(server.termin_bestaetigen(
        lead, t.date().isoformat(), f"{t:%H:%M}", dauer_minuten=dauer,
        thema=thema, ort=ort))["termin"]


def _entwuerfe(lead=None):
    if lead:
        return server._q("select status, channel from drafts where lead_id = %s", (lead,))
    return server._q("select status, channel from drafts")


def _start(seite: str) -> dict:
    m = re.search(r'<script type="application/json" id="kalender-start">(.*?)</script>',
                  seite, flags=re.S)
    assert m, "Startdaten fehlen"
    return json.loads(m.group(1))


def _anmelden(name, rolle, passwort="kalender-passwort-9"):
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen(name, rolle, passwort)
    assert meldung.startswith("OK"), meldung
    client = TestClient(ui.app)
    antwort = client.post("/login", data={"name": name, "passwort": passwort,
                                          "csrf": ui.CSRF_TOKEN},
                          headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    return client


# --- Seite ------------------------------------------------------------------

def test_seite_traegt_script_src_und_kontakte_nicht():
    antwort = _get("/kalender")
    assert antwort.status_code == 200
    csp = antwort.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert csp.startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in csp
    assert antwort.headers["cache-control"] == "no-store"
    assert '<div id="kalender"></div>' in antwort.text
    assert '<script src="/static/kalender/kalender.js" defer></script>' in antwort.text
    assert 'href="/static/kalender/kalender.css"' in antwort.text
    assert "script-src" not in _get("/kontakte").headers["content-security-policy"]


def test_seite_behaelt_die_uebrigen_abschnitte_unter_dem_kalender():
    lead = _lead_mail(name="Sabrina Schmidt")
    _kundentermin(lead, _um(3, 10), thema="Erstgespraech bAV")
    seite = _get("/kalender").text
    assert seite.index('<div id="kalender">') < seite.index("Kommende Termine")
    assert "Erstgespraech bAV" in seite
    assert 'class="monat"' not in seite        # das alte Monatsgitter ist weg (R5)


def test_startdaten_mit_csrf_und_uebernommener_ansicht():
    start = _start(_get("/kalender?datum=2099-09-04&ansicht=monat").text)
    assert start["csrf"] == ui.CSRF_TOKEN
    assert start["datum"] == "2099-09-04"
    assert start["ansicht"] == "monat"
    assert start["darf_schreiben"] is True
    assert start["freigaben_url"] == "/freigaben"


def test_startdaten_fallen_bei_kaputten_werten_auf_woche_und_heute():
    start = _start(_get("/kalender?datum=quatsch&ansicht=jahr").text)
    assert start["ansicht"] == "woche"
    assert start["datum"] == datetime.now(B).date().isoformat()


def test_startdaten_rolle_kalender_darf_nicht_schreiben(scharf):
    client = _anmelden("ivan", "kalender")
    antwort = _get("/kalender", client=client)
    assert antwort.status_code == 200
    start = _start(antwort.text)
    assert start["rolle"] == "kalender"
    assert start["darf_schreiben"] is False
    assert start["csrf"] == ui.CSRF_TOKEN


def test_statik_liefert_nur_die_zwei_paketdateien(tmp_path, monkeypatch):
    (tmp_path / "kalender.js").write_text("// platzhalter", encoding="utf-8")
    (tmp_path / "kalender.css").write_text("/* platzhalter */", encoding="utf-8")
    (tmp_path / "x.js").write_text("// nicht ausliefern", encoding="utf-8")
    monkeypatch.setattr(ui_kalender, "STATIK", tmp_path)
    js = _get("/static/kalender/kalender.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    assert _get("/static/kalender/kalender.css").status_code == 200
    assert _get("/static/kalender/x.js").status_code == 404


def test_statik_ohne_gebautes_paket_ist_404(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_kalender, "STATIK", tmp_path)
    assert _get("/static/kalender/kalender.js").status_code == 404


def test_rolle_kalender_darf_die_paketdateien_laden():
    assert ui._pfad_erlaubt("kalender", "/static/kalender/kalender.js") is True
    assert ui._pfad_erlaubt("kalender", "/static/editor/editor.js") is False


# --- termine.json -------------------------------------------------------------

@pytest.mark.parametrize("abfrage", [
    "", "?von=2099-09-01T00:00:00%2B02:00",
    "?von=quatsch&bis=2099-09-08T00:00:00%2B02:00",
    # bis vor von
    "?von=2099-09-08T00:00:00%2B02:00&bis=2099-09-01T00:00:00%2B02:00",
    # mehr als 62 Tage
    "?von=2099-09-01T00:00:00%2B02:00&bis=2099-11-03T00:00:00%2B01:00",
])
def test_termine_json_mit_falschen_parametern_ist_422(abfrage):
    antwort = _get("/kalender/termine.json" + abfrage)
    assert antwort.status_code == 422
    assert antwort.json()["grund"]
    assert antwort.headers["cache-control"] == "no-store"


def test_termine_json_liefert_die_ereignisse(monkeypatch):
    gesehen = {}

    def _ereignisse(von, bis):
        gesehen["von"], gesehen["bis"] = von, bis
        return {"ereignisse": [{"id": "eigen:a", "art": "eigen", "titel": "Steuer",
                                "beginn": "2099-09-02T10:00:00+02:00",
                                "ende": "2099-09-02T10:30:00+02:00", "bearbeitbar": True}],
                "hinweise": ["Handy-Termine gerade nicht abrufbar"]}
    monkeypatch.setattr(kalender_sicht, "ereignisse", _ereignisse)
    antwort = _get("/kalender/termine.json?von=2099-09-01T00:00:00%2B02:00"
                   "&bis=2099-09-08T00:00:00%2B02:00")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["ereignisse"][0]["id"] == "eigen:a"
    assert antwort.json()["hinweise"] == ["Handy-Termine gerade nicht abrufbar"]
    assert gesehen["von"] == datetime(2099, 9, 1, tzinfo=timezone(timedelta(hours=2)))
    assert gesehen["bis"] - gesehen["von"] == timedelta(days=7)
    assert antwort.headers["cache-control"] == "no-store"


def test_termine_json_db_ausfall_ist_503(monkeypatch):
    def _wirft(von, bis):
        raise psycopg.OperationalError("weg")
    monkeypatch.setattr(kalender_sicht, "ereignisse", _wirft)
    antwort = _get("/kalender/termine.json?von=2099-09-01T00:00:00%2B02:00"
                   "&bis=2099-09-08T00:00:00%2B02:00")
    assert antwort.status_code == 503
    assert antwort.json()["grund"]


# --- POST /kalender/termine ---------------------------------------------------

def _eigen_body(beginn, dauer=30, titel="Steuerberater", **mehr):
    return {"art": "eigen", "titel": titel, "beginn": beginn.isoformat(),
            "dauer_minuten": dauer, **mehr}


def test_post_eigener_termin_201():
    beginn = _um(2, 9)
    antwort = _senden("POST", "/kalender/termine", _eigen_body(beginn, ort="Kanzlei"))
    assert antwort.status_code == 201, antwort.text
    e = antwort.json()["ereignis"]
    assert e["id"].startswith("eigen:") and e["art"] == "eigen"
    assert e["titel"] == "Steuerberater" and e["ort"] == "Kanzlei"
    assert datetime.fromisoformat(e["beginn"]) == beginn
    assert datetime.fromisoformat(e["ende"]) == beginn + timedelta(minutes=30)
    assert e["geaendert_am"] and e["bearbeitbar"] is True
    assert server._q("select titel from eigene_termine")[0]["titel"] == "Steuerberater"


def test_post_ohne_csrf_ist_403_und_legt_nichts_an():
    antwort = _senden("POST", "/kalender/termine", _eigen_body(_um(2, 9)), csrf=False)
    assert antwort.status_code == 403
    assert antwort.json()["grund"]
    assert server._q("select uid from eigene_termine") == []


def test_post_mit_falscher_csrf_ist_403():
    antwort = CLIENT.post("/kalender/termine", json=_eigen_body(_um(2, 9)),
                          headers={"host": HOST_OK, "x-csrf": "falsch"})
    assert antwort.status_code == 403


@pytest.mark.parametrize("body", [
    {"art": "eigen", "titel": "x", "beginn": "quatsch", "dauer_minuten": 30},
    {"art": "eigen", "titel": "x", "beginn": "2099-09-02T10:00:00", "dauer_minuten": 30},
    {"art": "eigen", "titel": "", "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 30},
    {"art": "eigen", "titel": "x", "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 2},
    {"art": "eigen", "titel": "x", "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": "30"},
    {"art": "eigen", "titel": "x", "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 30,
     "trotzdem": "ja"},
    {"art": "fremd", "titel": "x", "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 30},
    {"art": "kunde", "lead_id": "keine-uuid", "thema": "x",
     "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 60},
    {"art": "kunde", "lead_id": "00000000-0000-0000-0000-000000000000", "thema": "x",
     "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 10},
    {"art": "kunde", "lead_id": "00000000-0000-0000-0000-000000000000", "thema": "  ",
     "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 60},
    {"art": "kunde", "lead_id": "00000000-0000-0000-0000-000000000000",
     "beginn": "2099-09-02T10:00:00+02:00", "dauer_minuten": 60},
    [1, 2],
])
def test_post_mit_ungueltigem_koerper_ist_422(body):
    antwort = _senden("POST", "/kalender/termine", body)
    assert antwort.status_code == 422, antwort.text
    assert antwort.json()["grund"]


def test_post_kein_json_ist_422():
    antwort = CLIENT.post("/kalender/termine", content=b"{kaputt",
                          headers={"host": HOST_OK, "x-csrf": ui.CSRF_TOKEN,
                                   "content-type": "application/json"})
    assert antwort.status_code == 422


def test_post_konflikt_409_und_mit_trotzdem_201():
    _senden("POST", "/kalender/termine", _eigen_body(_um(2, 9), dauer=60, titel="Erster"))
    zweiter = _eigen_body(_um(2, 9, 30), titel="Zweiter")
    antwort = _senden("POST", "/kalender/termine", zweiter)
    assert antwort.status_code == 409, antwort.text
    d = antwort.json()
    assert d["grund"] == "Konflikt"
    assert d["konflikte"][0]["titel"] == "Erster"
    assert d["unvollstaendig"] is False
    assert len(server._q("select uid from eigene_termine")) == 1
    antwort = _senden("POST", "/kalender/termine", {**zweiter, "trotzdem": True})
    assert antwort.status_code == 201, antwort.text
    assert len(server._q("select uid from eigene_termine")) == 2


def test_post_eigen_caldav_fehler_meldet_nicht_im_handy_kalender(monkeypatch):
    monkeypatch.setattr(kalender, "eintragen",
                        lambda uid, text: (kalender.FEHLGESCHLAGEN, "Server antwortet nicht"))
    antwort = _senden("POST", "/kalender/termine", _eigen_body(_um(2, 9)))
    assert antwort.status_code == 201
    assert antwort.json()["hinweis"] == "nicht im Handy-Kalender"


def test_post_kundentermin_mit_einladung_legt_pending_entwurf_an():
    lead = _lead_mail()
    beginn = _um(3, 14, 30)
    antwort = _senden("POST", "/kalender/termine", {
        "art": "kunde", "lead_id": lead, "thema": "Beratung", "beginn": beginn.isoformat(),
        "dauer_minuten": 45, "ort": "Buero", "einladung": True})
    assert antwort.status_code == 201, antwort.text
    d = antwort.json()
    e = d["ereignis"]
    assert e["id"].startswith("kunde:") and e["art"] == "kunde"
    assert e["lead_id"] == lead and e["kontakt"] == "Ivan Kunde"
    assert datetime.fromisoformat(e["beginn"]) == beginn
    assert datetime.fromisoformat(e["ende"]) == beginn + timedelta(minutes=45)
    assert d["entwurf"]["draft_id"] and d["entwurf"]["kanal"] == "email"
    assert [z["status"] for z in _entwuerfe(lead)] == ["pending"]
    zeile = server._termin_zeile(lead, e["uid"])
    assert zeile["payload"]["uhrzeit"] == "14:30"
    assert zeile["payload"]["dauer_minuten"] == 45


def test_post_kundentermin_mit_einladung_bucht_keine_einwilligung():
    # Final-Review I1: die Einladung aus der Oberflaeche hat Terminbezug —
    # sie passiert das Erstansprache-Tor, bucht aber kein betreiber_auftrag.
    lead = str(server._q(
        "insert into leads (name, email, source) values "
        "('Uwe Unbekannt', 'uwe@example.org', 'whatsapp') returning id")[0]["id"])
    antwort = _senden("POST", "/kalender/termine", {
        "art": "kunde", "lead_id": lead, "thema": "Beratung",
        "beginn": _um(3, 11).isoformat(), "dauer_minuten": 45, "einladung": True})
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["entwurf"]["kanal"] == "email"
    assert [z["status"] for z in _entwuerfe(lead)] == ["pending"]
    assert server._q("select consent_status from leads where id = %s",
                     (lead,))[0]["consent_status"] == "unknown"
    assert not server._q("select 1 from activities where lead_id = %s "
                         "and type = 'werbe_einwilligung'", (lead,))


def test_post_kundentermin_ohne_einladung_legt_keinen_entwurf_an():
    lead = _lead_mail()
    antwort = _senden("POST", "/kalender/termine", {
        "art": "kunde", "lead_id": lead, "thema": "Beratung",
        "beginn": _um(3, 10).isoformat(), "dauer_minuten": 60})
    assert antwort.status_code == 201, antwort.text
    assert "entwurf" not in antwort.json()
    assert _entwuerfe(lead) == []


def test_post_kundentermin_zu_unbekanntem_kontakt_ist_422():
    antwort = _senden("POST", "/kalender/termine", {
        "art": "kunde", "lead_id": "00000000-0000-0000-0000-000000000000", "thema": "x",
        "beginn": _um(3, 10).isoformat(), "dauer_minuten": 60})
    assert antwort.status_code == 422
    assert "Kein Kontakt" in antwort.json()["grund"]


# --- PATCH ----------------------------------------------------------------------

def _eigen_anlegen(beginn, dauer=30, titel="Steuer"):
    return _senden("POST", "/kalender/termine",
                   _eigen_body(beginn, dauer=dauer, titel=titel)).json()["ereignis"]


def test_patch_eigen_aendert_den_termin():
    e = _eigen_anlegen(_um(2, 9))
    neu = _um(2, 11)
    antwort = _senden("PATCH", f"/kalender/termine/{e['id']}",
                      {"geaendert_am": e["geaendert_am"], "beginn": neu.isoformat(),
                       "titel": "Steuer neu"})
    assert antwort.status_code == 200, antwort.text
    n = antwort.json()["ereignis"]
    assert n["id"] == e["id"] and n["titel"] == "Steuer neu"
    assert datetime.fromisoformat(n["beginn"]) == neu
    assert n["geaendert_am"] != e["geaendert_am"]


def test_patch_eigen_veraltet_ist_409_mit_wortlaut():
    e = _eigen_anlegen(_um(2, 9))
    antwort = _senden("PATCH", f"/kalender/termine/{e['id']}",
                      {"geaendert_am": "2000-01-01T00:00:00+00:00", "titel": "egal"})
    assert antwort.status_code == 409
    assert antwort.json()["grund"] == "inzwischen geändert – neu laden"


def test_patch_eigen_ohne_stempel_ist_422():
    e = _eigen_anlegen(_um(2, 9))
    antwort = _senden("PATCH", f"/kalender/termine/{e['id']}", {"titel": "egal"})
    assert antwort.status_code == 422


def test_patch_eigen_konflikt_mit_sich_selbst_zaehlt_nicht():
    e = _eigen_anlegen(_um(2, 9), dauer=60)
    antwort = _senden("PATCH", f"/kalender/termine/{e['id']}",
                      {"geaendert_am": e["geaendert_am"], "beginn": _um(2, 9, 30).isoformat()})
    assert antwort.status_code == 200, antwort.text


def test_patch_eigen_konflikt_mit_anderem_ist_409():
    _eigen_anlegen(_um(2, 12), dauer=60, titel="Belegt")
    e = _eigen_anlegen(_um(2, 9))
    antwort = _senden("PATCH", f"/kalender/termine/{e['id']}",
                      {"geaendert_am": e["geaendert_am"], "beginn": _um(2, 12, 15).isoformat()})
    assert antwort.status_code == 409
    assert antwort.json()["konflikte"][0]["titel"] == "Belegt"


@pytest.mark.parametrize("kennung", ["handy:abc", "kollege:abc", "abc", "eigen:"])
def test_patch_nicht_bearbeitbarer_kennung_ist_422(kennung):
    antwort = _senden("PATCH", f"/kalender/termine/{kennung}", {"titel": "x"})
    assert antwort.status_code == 422


def test_patch_unbekannter_eigener_termin_ist_404():
    antwort = _senden("PATCH", "/kalender/termine/eigen:gibt-es-nicht@sales-claw",
                      {"geaendert_am": "2000-01-01T00:00:00+00:00", "titel": "x"})
    assert antwort.status_code == 404


def test_patch_kunde_legt_pending_entwurf_an_und_antwortet_mit_draft_id():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    antwort = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                      {"beginn": _um(3, 16).isoformat()})
    assert antwort.status_code == 200, antwort.text
    d = antwort.json()
    assert d["entwurf"]["draft_id"] and d["entwurf"]["kanal"] == "email"
    assert [z["status"] for z in _entwuerfe(lead)] == ["pending"]
    e = d["ereignis"]
    assert e["id"].startswith("kunde:") and e["id"] != f"kunde:{alt['uid']}"
    assert d["ersetzt"] == f"kunde:{alt['uid']}"
    assert datetime.fromisoformat(e["beginn"]) == _um(3, 16)
    assert server._termin_abgesagt(lead, alt["uid"])


def test_patch_kunde_ohne_kanal_gibt_hinweis():
    lead = _lead_ohne_kanal()
    alt = _kundentermin(lead, _um(3, 14, 30))
    antwort = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                      {"titel": "Neues Thema"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["hinweis"] == server.KEIN_KANAL_HINWEIS
    assert _entwuerfe(lead) == []


def test_patch_kunde_nichts_geaendert_ist_422():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    antwort = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                      {"beginn": _um(3, 14, 30).isoformat()})
    assert antwort.status_code == 422
    assert _entwuerfe(lead) == []


def test_patch_kunde_konflikt_mit_handy_termin_erst_409_dann_genau_ein_entwurf(monkeypatch):
    """Review Focus 2: der Konflikt kommt ZUERST, ohne Entwurf; erst der
    zweite Aufruf mit `trotzdem` aendert und legt genau einen Entwurf an."""
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: ([{
        "uid": "handy-1@iphone", "titel": "Zahnarzt", "ort": "",
        "beginn": _um(3, 16, 15), "ende": _um(3, 17)}], None))
    body = {"beginn": _um(3, 16).isoformat()}
    erste = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}", body)
    assert erste.status_code == 409, erste.text
    assert erste.json()["konflikte"][0]["art"] == "handy"
    assert _entwuerfe(lead) == []
    assert not server._termin_abgesagt(lead, alt["uid"])
    zweite = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}", {**body, "trotzdem": True})
    assert zweite.status_code == 200, zweite.text
    assert [z["status"] for z in _entwuerfe(lead)] == ["pending"]


def test_patch_kunde_db_fehler_beim_benachrichtigen_ist_503(monkeypatch):
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))

    def _wirft(*a, **k):
        raise psycopg.OperationalError("weg")
    monkeypatch.setattr(server, "kunde_benachrichtigen", _wirft)
    antwort = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                      {"beginn": _um(3, 16).isoformat()})
    assert antwort.status_code == 503
    assert "selbst Bescheid geben" in antwort.json()["grund"]
    assert antwort.json()["ereignis"]["id"].startswith("kunde:")


def test_patch_unbekannter_kundentermin_ist_404():
    antwort = _senden("PATCH", "/kalender/termine/kunde:gibt-es-nicht",
                      {"titel": "x"})
    assert antwort.status_code == 404


# --- DELETE ---------------------------------------------------------------------

def test_delete_eigen_loescht():
    e = _eigen_anlegen(_um(2, 9))
    antwort = _senden("DELETE", f"/kalender/termine/{e['id']}", {})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["geloescht"] is True
    assert server._q("select uid from eigene_termine") == []


def test_delete_eigen_ohne_csrf_ist_403():
    e = _eigen_anlegen(_um(2, 9))
    antwort = _senden("DELETE", f"/kalender/termine/{e['id']}", {}, csrf=False)
    assert antwort.status_code == 403
    assert len(server._q("select uid from eigene_termine")) == 1


def test_delete_kunde_ohne_grund_ist_422():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    for body in ({}, {"grund": "   "}, None):
        antwort = _senden("DELETE", f"/kalender/termine/kunde:{alt['uid']}", body)
        assert antwort.status_code == 422, antwort.text
    assert not server._termin_abgesagt(lead, alt["uid"])
    assert _entwuerfe(lead) == []


def test_delete_kunde_mit_grund_sagt_ab_und_legt_entwurf_an():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    antwort = _senden("DELETE", f"/kalender/termine/kunde:{alt['uid']}",
                      {"grund": "krank"})
    assert antwort.status_code == 200, antwort.text
    d = antwort.json()
    assert d["geloescht"] is True
    assert d["entwurf"]["draft_id"] and d["entwurf"]["kanal"] == "email"
    assert server._termin_abgesagt(lead, alt["uid"])
    assert [z["status"] for z in _entwuerfe(lead)] == ["pending"]


# --- Videoraum, Kontaktsuche ----------------------------------------------------------

def test_videoraum_liefert_link(monkeypatch):
    monkeypatch.setattr(konferenz, "raum", lambda anbieter="": ("https://meet.jit.si/abc", "ohne Google"))
    antwort = _senden("POST", "/kalender/videoraum", {})
    assert antwort.status_code == 200
    assert antwort.json() == {"link": "https://meet.jit.si/abc", "hinweis": "ohne Google"}


def test_videoraum_ohne_csrf_ist_403(monkeypatch):
    monkeypatch.setattr(konferenz, "raum", lambda anbieter="": ("https://meet.jit.si/abc", ""))
    assert _senden("POST", "/kalender/videoraum", {}, csrf=False).status_code == 403


def test_kontaktsuche_liefert_hoechstens_zehn_mit_id_und_name():
    for i in range(12):
        _lead_ohne_kanal(name=f"Ivan Nummer {i}")
    _lead_ohne_kanal(name="Anderer Mensch")
    antwort = _get("/kalender/kontakte.json?q=Ivan")
    assert antwort.status_code == 200
    kontakte = antwort.json()["kontakte"]
    assert len(kontakte) == 10
    assert set(kontakte[0]) == {"lead_id", "name"}
    assert all(k["name"].startswith("Ivan") for k in kontakte)
    assert _get("/kalender/kontakte.json?q=").json() == {"kontakte": []}


def test_kontaktsuche_ist_fuer_rolle_kalender_gesperrt(scharf):
    _lead_ohne_kanal(name="Geheimer Kunde")
    client = _anmelden("ivan", "kalender")
    antwort = _get("/kalender/kontakte.json?q=Geheim", client=client)
    assert antwort.status_code == 403
    assert "Geheimer Kunde" not in antwort.text


# --- Rollen -------------------------------------------------------------------------

def test_rolle_kalender_liest_aber_schreibt_nicht(scharf):
    client = _anmelden("ivan", "kalender")
    lesen = _get("/kalender/termine.json?von=2099-09-01T00:00:00%2B02:00"
                 "&bis=2099-09-08T00:00:00%2B02:00", client=client)
    assert lesen.status_code == 200, lesen.text
    schreiben = _senden("POST", "/kalender/termine", _eigen_body(_um(2, 9)), client=client)
    assert schreiben.status_code == 403
    assert server._q("select uid from eigene_termine") == []


def test_rolle_lesen_schreibt_nicht(scharf):
    client = _anmelden("leser", "lesen")
    antwort = _senden("POST", "/kalender/videoraum", {}, client=client)
    assert antwort.status_code == 403
    assert _start(_get("/kalender", client=client).text)["darf_schreiben"] is False


# --- Kontaktseite ---------------------------------------------------------------------

def test_kontaktseite_zeigt_termine_mit_link_in_den_kalender():
    lead = _lead_mail()
    t = _kundentermin(lead, _um(3, 14, 30), thema="Beratung Altersvorsorge")
    weg = _kundentermin(lead, _um(4, 9), thema="Abgesagtes Thema")
    json.loads(server.termin_absagen(lead, weg["uid"], "krank"))
    seite = _get(f"/kontakte/{lead}?reiter=termine").text
    assert "<h2>Termine" in seite
    assert "Offene Wiedervorlagen" not in seite
    assert f'href="/kalender?datum={t["datum"]}' in seite
    assert "ansicht=woche" in seite
    # Nur der Abschnitt zaehlt - die Terminerinnerung (Wiedervorlage) traegt
    # das Thema auch des abgesagten Termins weiter.
    abschnitt = seite[seite.index("<h2>Termine"):]
    assert "Beratung Altersvorsorge" in abschnitt
    assert "Abgesagtes Thema" not in abschnitt
    assert abschnitt.count("im Kalender öffnen") == 1


def test_kontaktseite_ohne_termine():
    lead = _lead_mail()
    seite = _get(f"/kontakte/{lead}?reiter=termine").text
    assert "<h2>Termine" in seite
    assert 'href="/kalender?datum=' not in seite


# --- Fix-Runde 1 -------------------------------------------------------------

def test_csp_kalender_folgt_ui_csp():
    def _direktiven(csp):
        return {t.split()[0]: t for t in (d.strip() for d in csp.split(";")) if t}
    basis, kal = _direktiven(ui._CSP), _direktiven(ui_kalender.csp_kalender(ui))
    for name, wert in basis.items():
        if name != "style-src":
            assert kal[name] == wert, name
    assert kal["style-src"] == "style-src 'self' 'unsafe-inline'"
    assert kal["script-src"] == "script-src 'self'"
    assert kal["connect-src"] == "connect-src 'self'"
    assert set(kal) == set(basis) | {"script-src", "connect-src"}
    assert _get("/kalender").headers["content-security-policy"] == ui_kalender.csp_kalender(ui)


def test_nicht_ascii_csrf_ist_403_json():
    antwort = CLIENT.post("/kalender/videoraum", json={},
                          headers={"host": HOST_OK, "x-csrf": "fälschung".encode("latin-1")})
    assert antwort.status_code == 403
    assert antwort.json()["grund"]


def test_patch_kunde_zweimal_ist_beim_zweiten_mal_veraltet():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    erste = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                    {"beginn": _um(3, 16).isoformat()})
    assert erste.status_code == 200, erste.text
    zweite = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                     {"beginn": _um(3, 17).isoformat()})
    assert zweite.status_code == 409, zweite.text
    assert zweite.json()["grund"] == "inzwischen geändert – neu laden"
    assert len(_entwuerfe(lead)) == 1


def test_delete_kunde_nach_patch_ist_veraltet():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    assert _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                   {"beginn": _um(3, 16).isoformat()}).status_code == 200
    antwort = _senden("DELETE", f"/kalender/termine/kunde:{alt['uid']}", {"grund": "krank"})
    assert antwort.status_code == 409
    assert antwort.json()["grund"] == "inzwischen geändert – neu laden"
    assert len(_entwuerfe(lead)) == 1


def test_patch_kunde_nur_dauer():
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30), dauer=60)
    antwort = _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}", {"dauer_minuten": 90})
    assert antwort.status_code == 200, antwort.text
    e = antwort.json()["ereignis"]
    assert datetime.fromisoformat(e["beginn"]) == _um(3, 14, 30)
    assert datetime.fromisoformat(e["ende"]) == _um(3, 16)
    neu = server._termin_zeile(lead, e["uid"])["payload"]
    assert neu["dauer_minuten"] == 90 and neu["uhrzeit"] == "14:30"
    assert neu["thema"] == "Beratung" and neu["ort"] == "Buero"


def test_rolle_kalender_patch_und_delete_sind_403(scharf):
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))
    client = _anmelden("ivan", "kalender")
    assert _senden("PATCH", f"/kalender/termine/kunde:{alt['uid']}",
                   {"dauer_minuten": 90}, client=client).status_code == 403
    assert _senden("DELETE", f"/kalender/termine/kunde:{alt['uid']}",
                   {"grund": "x"}, client=client).status_code == 403
    assert not server._termin_abgesagt(lead, alt["uid"])


def test_delete_kunde_db_fehler_beim_benachrichtigen_ist_503(monkeypatch):
    lead = _lead_mail()
    alt = _kundentermin(lead, _um(3, 14, 30))

    def _wirft(*a, **k):
        raise psycopg.OperationalError("weg")
    monkeypatch.setattr(server, "kunde_benachrichtigen", _wirft)
    antwort = _senden("DELETE", f"/kalender/termine/kunde:{alt['uid']}", {"grund": "krank"})
    assert antwort.status_code == 503
    assert antwort.json()["grund"].startswith("Termin abgesagt, aber")
    assert "selbst Bescheid geben" in antwort.json()["grund"]
    assert antwort.json()["geloescht"] is True
    assert server._termin_abgesagt(lead, alt["uid"])


@pytest.mark.parametrize("thema", [None, "", "   "])
def test_post_kundentermin_ohne_thema_ist_422(thema):
    lead = _lead_mail()
    body = {"art": "kunde", "lead_id": lead, "beginn": _um(3, 10).isoformat(),
            "dauer_minuten": 60}
    if thema is not None:
        body["thema"] = thema
    antwort = _senden("POST", "/kalender/termine", body)
    assert antwort.status_code == 422, antwort.text
    assert server._q("select 1 from activities where type = 'termin'") == []


def test_start_mit_neu_kunde_vorbelegung():
    lead = server._q("insert into leads (name) values ('Anna Vorbelegt') returning id")[0]["id"]
    s = _start(_get(f"/kalender?neu=kunde&lead_id={lead}").text)
    assert s["neu_kunde"] == {"lead_id": str(lead), "name": "Anna Vorbelegt"}
    assert "neu_kunde" not in _start(_get("/kalender?neu=kunde&lead_id=kaputt").text)
    assert "neu_kunde" not in _start(_get(
        "/kalender?neu=kunde&lead_id=00000000-0000-0000-0000-000000000000").text)


def test_start_neu_kunde_nie_fuer_privat_und_sammelkontakt(monkeypatch):
    privat = server._q(
        "insert into leads (name, enrichment) values ('Pia Privat', %s::jsonb) returning id",
        ('{"_privat": {"privat": true}}',))[0]["id"]
    assert "neu_kunde" not in _start(_get(f"/kalender?neu=kunde&lead_id={privat}").text)
    sammel = server._q("insert into leads (name) values ('Sammel') returning id")[0]["id"]
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", str(sammel))
    assert "neu_kunde" not in _start(_get(f"/kalender?neu=kunde&lead_id={sammel}").text)


def test_start_neu_kunde_nie_fuer_rolle_lesen(scharf):
    lead = server._q("insert into leads (name) values ('Rolf Lesen') returning id")[0]["id"]
    lesen = _anmelden("nur-lesen-neu", "lesen")
    assert "neu_kunde" not in _start(_get(f"/kalender?neu=kunde&lead_id={lead}", client=lesen).text)
