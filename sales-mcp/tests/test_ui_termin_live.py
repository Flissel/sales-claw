"""Steuerseite /termine/{uid}/live und live.json (Meeting-Mittelpunkt Task 7).

Die Datenbank ist sales_test; Akten, Segmente und Pausen stehen direkt in den
Tabellen (sales-termine ist hier nicht beteiligt)."""
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import termin_akte  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
MEET = "https://meet.jit.si/abc-defg-hij"
GEHEIM = "GEHEIMTEXT <b>fett</b> zum Budget"
SONDER_UID = "abc@google.com#2026-11-12T09:00:00+00:00"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    yield


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _akte(uid="u1", **spalten):
    beginn = spalten.pop("beginn", JETZT)
    werte = {"uid": uid, "herkunft": "sales-claw", "beginn": beginn,
             "ende": beginn + timedelta(hours=1), "titel": "Beratung",
             "thema": "Beratung bAV", "link": MEET, "plattform": "jitsi",
             "status": "laeuft", **spalten}
    namen = list(werte)
    server._q(f"insert into termin_akten ({', '.join(namen)}) values "
              f"({', '.join(['%s'] * len(namen))}) returning uid",
              [werte[n] for n in namen])
    return uid


def _zeile(uid="u1"):
    return server._q("select * from termin_akten where uid = %s", (uid,))[0]


def _segment(uid, sid, minute, text=GEHEIM, sprecher="Karla"):
    t = JETZT + timedelta(minutes=minute)
    server._q("insert into termin_live_segmente (uid, segment_id, beginn, ende, sprecher, text) "
              "values (%s, %s, %s, %s, %s, %s) returning segment_id",
              (uid, sid, t, t + timedelta(seconds=5), sprecher, text))


def _pfad(uid):
    return f"/termine/{quote(uid, safe='')}"


def _get(pfad, client=CLIENT):
    return client.get(pfad, headers={"host": HOST_OK}, follow_redirects=False)


def _post(uid, aktion, csrf=True, client=CLIENT):
    daten = {"aktion": aktion}
    if csrf:
        daten["csrf"] = ui.CSRF_TOKEN
    return client.post(_pfad(uid) + "/live", data=daten, headers={"host": HOST_OK},
                       follow_redirects=False)


def _anmelden(name, rolle, passwort="termin-passwort-9"):
    import benutzer_anlegen
    assert benutzer_anlegen.anlegen(name, rolle, passwort).startswith("OK")
    client = TestClient(ui.app)
    antwort = client.post("/login", data={"name": name, "passwort": passwort,
                                          "csrf": ui.CSRF_TOKEN},
                          headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    return client


def _json(uid="u1", client=CLIENT):
    a = _get(_pfad(uid) + "/live.json", client)
    assert a.status_code == 200
    return a.json()


# --- Routen -----------------------------------------------------------------

def test_live_route_nicht_vom_catchall_geschluckt():
    _akte("u1")
    a = _get(_pfad("u1") + "/live")
    assert a.status_code == 200 and "Live-Mitschrift" in a.text
    j = _get(_pfad("u1") + "/live.json")
    assert j.status_code == 200 and "zustand" in j.json()
    s = _get("/termine/live.js")
    assert s.status_code == 200 and s.headers["content-type"].startswith("text/javascript")
    assert s.headers["cache-control"] == "no-cache"
    assert s.headers["x-content-type-options"] == "nosniff"
    # Die Akte selbst ist weiter erreichbar, auch mit Sonderzeichen in der uid.
    assert _get(_pfad("u1")).status_code == 200
    _akte(SONDER_UID)
    assert _get(_pfad(SONDER_UID) + "/live").status_code == 200
    assert _get(_pfad("gibts-nicht") + "/live").status_code == 404
    assert _get(_pfad("gibts-nicht") + "/live.json").status_code == 404


def test_live_json_no_store_und_form():
    _akte("u1")
    _segment("u1", "s1", 1)
    a = _get(_pfad("u1") + "/live.json")
    assert a.headers["cache-control"] == "no-store"
    d = a.json()
    assert d["zustand"] == "an" and d["pausiert_seit"] is None
    assert d["pausen"] == [] and d["bilder_anzahl"] == 0
    assert d["segmente"][0]["text"] == GEHEIM and d["segmente"][0]["sprecher"] == "Karla"
    assert set(d["segmente"][0]) >= {"beginn", "sprecher", "text"}


def test_link_zur_akte_nur_wenn_live():
    _akte("u1", status="laeuft")
    _akte("u2", status="fertig")
    assert "/live\">Live-Ansicht" in _get(_pfad("u1")).text
    assert "Live-Ansicht" not in _get(_pfad("u2")).text


# --- Rechte -----------------------------------------------------------------

def test_lesen_ohne_knoepfe(scharf):
    _akte("u1")
    client = _anmelden("lena", "lesen")
    a = _get(_pfad("u1") + "/live", client)
    assert a.status_code == 200
    assert "Notbremse" not in a.text and 'name="aktion"' not in a.text
    assert _get(_pfad("u1") + "/live.json", client).status_code == 200
    assert _post("u1", "pause", client=client).status_code == 403
    assert _zeile()["aufnahme_wunsch_am"] is None
    schreiber = _anmelden("sven", "freigeben")
    t = _get(_pfad("u1") + "/live", schreiber).text
    assert 'value="pause"' in t and 'value="weiter"' in t and 'value="notbremse"' in t


def test_post_ohne_csrf_abgewiesen():
    _akte("u1")
    assert _post("u1", "pause", csrf=False).status_code == 403
    assert _zeile()["aufnahme_wunsch_am"] is None
    assert server._q("select 1 from termin_pausen where uid = 'u1'") == []
    # Gegenprobe (sonst bestuende der Test auch ohne die Route): mit Token geht es.
    assert _post("u1", "pause").status_code == 303
    assert _zeile()["aufnahme_wunsch"] == "pause"


def test_post_pause_setzt_wunsch():
    _akte("u1")
    a = _post("u1", "pause")
    assert a.status_code == 303 and a.headers["location"] == _pfad("u1") + "/live"
    z = _zeile()
    assert z["aufnahme_wunsch"] == "pause" and z["aufnahme_wunsch_am"] is not None
    # Nur der Wunsch: bestaetigt ist nichts.
    assert z["aufnahme_pausiert_seit"] is None
    p = termin_akte.pausen("u1")
    assert len(p) == 1 and p[0]["bis"] is None and p[0]["bestaetigt_am"] is None
    assert _post("u1", "weiter").status_code == 303
    assert _zeile()["aufnahme_wunsch"] == "an"
    assert termin_akte.pausen("u1")[0]["bis"] is not None
    assert _post("u1", "notbremse").status_code == 303
    assert _zeile()["aufnahme_wunsch"] == "notbremse"


def test_post_wer_ist_der_betreiber(scharf):
    _akte("u1")
    client = _anmelden("sven", "freigeben")
    assert _post("u1", "pause", client=client).status_code == 303
    assert termin_akte.pausen("u1")[0]["angefordert_von"] == "sven"


def test_post_unbekannte_aktion_400():
    _akte("u1")
    assert _post("u1", "loeschen").status_code == 400
    assert _post("u1", "an").status_code == 400
    assert _zeile()["aufnahme_wunsch_am"] is None


def test_post_akte_nicht_aktiv_meldet_sichtbar():
    _akte("u1", status="fertig")
    a = _post("u1", "pause")
    assert a.status_code == 303
    assert a.headers["location"] == _pfad("u1") + "/live?m=nicht_aktiv"
    assert _zeile()["aufnahme_wunsch_am"] is None
    seite = _get(a.headers["location"])
    assert seite.status_code == 200 and "nichts geändert" in seite.text
    assert _post("gibts-nicht", "pause").status_code == 404


# --- Zustand (R3 + R18) -----------------------------------------------------

SEIT = JETZT + timedelta(minutes=3)


@pytest.mark.parametrize("spalten, erwartet, text", [
    ({"aufnahme_wunsch": "notbremse", "aufnahme_pause_fehler": "nicht_bestaetigt",
      "aufnahme_pausiert_seit": SEIT}, "notbremse", "■ Notbremse – Bot hat den Raum verlassen"),
    ({"aufnahme_wunsch": "pause", "aufnahme_pause_fehler": "nicht_bestaetigt"},
     "nicht_bestaetigt", "⚠ Pause nicht bestätigt – Notbremse?"),
    ({"aufnahme_wunsch": "an", "aufnahme_pause_fehler": "weiter_nicht_bestaetigt",
      "aufnahme_pausiert_seit": SEIT}, "weiter_nicht_bestaetigt",
     "⚠ Weiter nicht bestätigt – Aufnahme evtl. noch pausiert"),
    ({"aufnahme_wunsch": "pause", "aufnahme_pausiert_seit": SEIT}, "pausiert",
     "⏸ Pausiert seit 13:03"),
    ({"aufnahme_wunsch": "pause"}, "wird_pausiert", "⏳ Wird pausiert …"),
    ({"aufnahme_wunsch": "an", "aufnahme_pausiert_seit": SEIT}, "wird_fortgesetzt",
     "⏳ Wird fortgesetzt …"),
    ({"aufnahme_wunsch": "an"}, "an", "● Aufnahme läuft"),
    ({}, "an", "● Aufnahme läuft"),
])
def test_zustand_zuordnung(spalten, erwartet, text):
    _akte("u1", zeitzone="Europe/Berlin", **spalten)
    d = _json()
    assert d["zustand"] == erwartet and d["zustand_text"] == text
    assert d["pausiert_seit"] == (SEIT.isoformat() if "aufnahme_pausiert_seit" in spalten else None)
    assert text in _get(_pfad("u1") + "/live").text


def test_json_zeigt_wird_pausiert_bis_bestaetigt():
    _akte("u1")
    assert _post("u1", "pause").status_code == 303
    d = _json()
    assert d["zustand"] == "wird_pausiert" and "pausiert seit" not in d["zustand_text"].lower()
    # sales-termine bestaetigt: Zeitstempel gesetzt.
    server._q("update termin_akten set aufnahme_pausiert_seit = %s where uid = 'u1' "
              "returning uid", (SEIT,))
    assert _json()["zustand"] == "pausiert"
    assert _post("u1", "weiter").status_code == 303
    assert _json()["zustand"] == "wird_fortgesetzt"
    server._q("update termin_akten set aufnahme_pausiert_seit = null where uid = 'u1' "
              "returning uid")
    assert _json()["zustand"] == "an"


def test_json_nicht_bestaetigt():
    _akte("u1", aufnahme_wunsch="pause", aufnahme_pause_fehler="nicht_bestaetigt")
    d = _json()
    assert d["zustand"] == "nicht_bestaetigt"
    assert d["zustand_text"] == "⚠ Pause nicht bestätigt – Notbremse?"


def test_json_pausen_und_segmente():
    _akte("u1", zeitzone="Europe/Berlin")
    _segment("u1", "s1", 1)
    _segment("u1", "s2", 9)
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) values "
              "('u1', %s, %s, 'felix') returning id",
              (JETZT + timedelta(minutes=3), JETZT + timedelta(minutes=7)))
    d = _json()
    assert [s["text"] for s in d["segmente"]] == [GEHEIM, GEHEIM]
    assert [p["text"] for p in d["pausen"]] == ["Pause 13:03–13:07"]
    assert d["pausen"][0]["von"] and d["pausen"][0]["bis"]


# --- Seite ------------------------------------------------------------------

def test_meeting_knopf_neuer_tab_rel_noopener():
    _akte("u1")
    t = _get(_pfad("u1") + "/live").text
    assert (f'<a class="knopf sek" href="{MEET}" target="_blank" rel="noopener">'
            'Meeting öffnen ↗</a>') in t
    _akte("u2", link="javascript:alert(1)")
    t2 = _get(_pfad("u2") + "/live").text
    assert "javascript:" not in t2 and "Meeting öffnen" not in t2


def test_genau_ein_script_csp_self():
    _akte("u1")
    a = _get(_pfad("u1") + "/live")
    t = a.text.lower()
    assert t.count("<script") == 1 and '<script src="/termine/live.js" defer></script>' in a.text
    assert "<iframe" not in t
    csp = a.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert a.headers["cache-control"] == "no-store"
    # Kein Transkript in der Seite selbst (Fremdtext kommt nur per JSON + textContent).
    _segment("u1", "s1", 1)
    assert "GEHEIMTEXT" not in _get(_pfad("u1") + "/live").text


def test_nicht_live_akte_ohne_skript_und_knoepfe():
    _akte("u1", status="fertig")
    t = _get(_pfad("u1") + "/live").text
    assert "<script" not in t.lower() and 'name="aktion"' not in t
    assert "nichts zu steuern" in t


def test_live_js_ohne_innerhtml_und_log():
    js = _get("/termine/live.js").text
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    assert "console." not in js and "document.write" not in js and "eval(" not in js
    assert "textContent" in js and "Date.parse" in js


# --- Akte: Pausen in Mitschrift, Bildschirm, Kopf ---------------------------

def _mitschrift_mit(uid, segmente):
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status) "
              "values (%s, %s::jsonb, 'fertig') returning id", (uid, json.dumps(segmente)))


def test_mitschrift_zeigt_pausenzeile_ohne_inhalt():
    _akte("u1", status="fertig", zeitzone="Europe/Berlin")
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) values "
              "('u1', %s, %s, 'felix') returning id",
              (JETZT + timedelta(minutes=3), JETZT + timedelta(minutes=7)))
    _mitschrift_mit("u1", [
        {"sprecher": "Karla", "beginn": "2099-01-09T12:01:00Z", "text": "VORHER"},
        {"sprecher": "Karla", "beginn": "2099-01-09T12:05:00Z", "text": "GEHEIMIN PAUSE"},
        {"sprecher": "Karla", "beginn": "2099-01-09T12:08:00Z", "text": "NACHHER"}])
    t = _get(_pfad("u1") + "?reiter=mitschrift").text
    assert "GEHEIMIN PAUSE" not in t
    z = t[t.index("<h2>Mitschrift</h2>"):]
    assert z.index("VORHER") < z.index("Pause 13:03–13:07") < z.index("NACHHER")
    # Kopf der Akte: Liste der Pausen mit von/bis und wer.
    kopf = _get(_pfad("u1") + "?reiter=details").text
    assert "<h2>Pausen</h2>" in kopf and "Pause 13:03–13:07" in kopf and "felix" in kopf


def test_bildschirm_zeigt_pausenzeile():
    _akte("u1", status="laeuft", zeitzone="Europe/Berlin", bildschirm_auswerten=True)
    server._q("insert into termin_pausen (uid, von, angefordert_von) values "
              "('u1', %s, 'felix') returning id", (JETZT + timedelta(minutes=3),))
    t = _get(_pfad("u1") + "?reiter=bildschirm").text
    assert "Pause seit 13:03" in t


# --- Gesperrte Teilnehmer ---------------------------------------------------
# Die bestehende Mitschrift-Ansicht filtert nicht je Sprecher, sondern nur auf
# Akte-/Kontakt-Ebene (Teilnehmerliste; der Bot startet bei gesperrtem
# Teilnehmer gar nicht: termin_akte.hat_gesperrte). Dieselbe Regel gilt hier:
# ist jemand gesperrt, liefert die Live-Ansicht keinen Inhalt.

def _teilnehmer(uid, adresse, grund=None):
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, grund) "
              "values (%s, %s, 'Gesperrt Gustav', 'gast', %s) returning uid",
              (uid, adresse, grund))


def _inhalt_vorbereiten():
    _akte("u1", zeitzone="Europe/Berlin")
    _segment("u1", "s1", 1)
    server._q("insert into termin_pausen (uid, von, bis, angefordert_von) values "
              "('u1', %s, %s, 'felix') returning id",
              (JETZT + timedelta(minutes=3), JETZT + timedelta(minutes=7)))


def _ohne_inhalt(d):
    assert d["segmente"] == [] and d["pausen"] == [] and d["bilder_anzahl"] == 0
    assert d["gesperrt"] is True
    assert GEHEIM not in json.dumps(d) and "Pause" not in json.dumps(d)


def test_live_gesperrter_teilnehmer_markiert_ohne_inhalt():
    _inhalt_vorbereiten()
    _teilnehmer("u1", "weg@firma.de", grund="gesperrt")
    _ohne_inhalt(_json())
    t = _get(_pfad("u1") + "/live").text
    assert "GEHEIMTEXT" not in t and "gesperrt" in t.lower()


def test_live_spaeter_gesperrter_teilnehmer_ohne_inhalt():
    import sperrliste
    _inhalt_vorbereiten()
    _teilnehmer("u1", "spaeter@firma.de")
    assert _json()["gesperrt"] is False and _json()["segmente"]
    sperrliste.sperren(server._q, email="spaeter@firma.de", quelle="test", grund="Widerruf")
    _ohne_inhalt(_json())
    # Der Zustand bleibt sichtbar (Notbremse muss weiter erreichbar sein).
    assert _json()["zustand"] == "an"
    assert "Notbremse" in _get(_pfad("u1") + "/live").text
