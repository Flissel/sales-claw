"""API des Freigabe-Eingangs fuer Dienste und CLI fuer Schluessel (Plan 2026-11-08, Task 5)."""
import io
import os
import uuid

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import freigabe_eingang as fe  # noqa: E402
import freigabe_schluessel  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
PR = "Flissel/vibemind-os#154"
EINTRAG = "/api/freigaben/eintrag"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        # Eine Anweisung, eintraege zuerst (Sperrreihenfolge, s. test_freigabe_eingang.py).
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")
    yield


@pytest.fixture
def anmeldung(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    yield


@pytest.fixture
def client(anmeldung):
    return TestClient(ui.app, headers=HOST)


def _kopf(herkunft):
    return {"Authorization": "Bearer " + fe.schluessel_anlegen(herkunft)}


def _rumpf(**kw):
    r = {"art": "debugger_pr", "quelle_ref": PR, "titel": "PR 154",
         "link": "https://x.example/1"}
    r.update(kw)
    return r


def test_ohne_schluessel_401(client):
    for r in (client.post(EINTRAG, json=_rumpf()), client.get("/api/freigaben/offen"),
              client.get("/api/freigaben/auftraege"),
              client.post("/api/freigaben/schliessen", json={}),
              client.post(f"/api/freigaben/auftraege/{uuid.uuid4()}", json={"ok": True})):
        assert r.status_code == 401
        assert r.json() == {"fehler": "nicht_berechtigt"}


def test_falscher_schluessel_401(client):
    _kopf("debugger-claw")
    r = client.post(EINTRAG, json=_rumpf(), headers={"Authorization": "Bearer falsch"})
    assert r.status_code == 401 and r.json() == {"fehler": "nicht_berechtigt"}
    r = client.post(EINTRAG, json=_rumpf(), headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_eintrag_anlegen_und_wiederholen(client):
    kopf = _kopf("debugger-claw")
    r1 = client.post(EINTRAG, json=_rumpf(), headers=kopf)
    r2 = client.post(EINTRAG, json=_rumpf(), headers=kopf)
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["neu"] is True and r2.json()["neu"] is False
    assert r1.json()["kennung"] == r2.json()["kennung"]


def test_herkunft_aus_schluessel(client):
    kopf = _kopf("debugger-claw")
    r = client.post(EINTRAG, json=_rumpf(herkunft="werkstatt"), headers=kopf)
    assert r.status_code == 201
    z = server._q("select herkunft from freigabe_eintraege where kennung = %s",
                  (r.json()["kennung"],))
    assert z[0]["herkunft"] == "debugger-claw"


def test_fremde_art_403(client):
    kopf = _kopf("debugger-claw")
    r = client.post(EINTRAG, json=_rumpf(art="kursfreigabe"), headers=kopf)
    assert r.status_code == 403 and r.json() == {"fehler": "art_nicht_erlaubt"}


def test_validierung_422_ohne_echo(client):
    kopf = _kopf("debugger-claw")
    r = client.post(EINTRAG, json=_rumpf(quelle_ref=""), headers=kopf)
    assert r.status_code == 422
    r = client.post(EINTRAG, json=_rumpf(details="GEHEIMTEXT"), headers=kopf)
    assert r.status_code == 422 and "GEHEIMTEXT" not in r.text
    r = client.post(EINTRAG, content=b"{kaputt", headers=kopf)
    assert r.status_code == 422
    r = client.post(EINTRAG, json=[1], headers=kopf)
    assert r.status_code == 422


def test_zu_gross_413(client):
    kopf = _kopf("debugger-claw")
    r = client.post(EINTRAG, json=_rumpf(titel="x" * 9000), headers=kopf)
    assert r.status_code == 413


def test_offen_nur_eigene(client):
    kd, ks = _kopf("debugger-claw"), _kopf("selbstbild")
    client.post(EINTRAG, json=_rumpf(details={"a": 1}), headers=kd)
    client.post(EINTRAG, json={"art": "selbstbild_rueckfrage", "quelle_ref": "r#1",
                               "titel": "t"}, headers=ks)
    e = client.get("/api/freigaben/offen", headers=kd).json()["eintraege"]
    assert len(e) == 1
    assert set(e[0]) == {"kennung", "art", "quelle_ref", "details", "rowboat_stand", "vermerk"}
    assert e[0]["art"] == "debugger_pr" and e[0]["details"] == {"a": 1}


def test_schliessen(client):
    kd = _kopf("debugger-claw")
    client.post(EINTRAG, json=_rumpf(), headers=kd)
    r = client.post("/api/freigaben/schliessen",
                    json={"quelle_ref": PR, "status": "erledigt"}, headers=kd)
    assert r.status_code == 200 and r.json() == {"geschlossen": 1}
    r = client.post("/api/freigaben/schliessen",
                    json={"quelle_ref": PR, "status": "unsinn"}, headers=kd)
    assert r.status_code == 422


def test_schliessen_ausgefuehrt_verboten(client):
    kd = _kopf("debugger-claw")
    client.post(EINTRAG, json=_rumpf(), headers=kd)
    r = client.post("/api/freigaben/schliessen",
                    json={"quelle_ref": PR, "status": "ausgefuehrt"}, headers=kd)
    assert r.status_code == 422 and r.json() == {"fehler": "ungueltig"}
    assert len(fe.offene("debugger-claw")) == 1


def test_fremden_eintrag_nicht_schliessen(client):
    kd, ks = _kopf("debugger-claw"), _kopf("selbstbild")
    client.post(EINTRAG, json=_rumpf(), headers=kd)
    r = client.post("/api/freigaben/schliessen",
                    json={"quelle_ref": PR, "status": "erledigt"}, headers=ks)
    assert r.json() == {"geschlossen": 0}
    assert len(fe.offene("debugger-claw")) == 1


def _auftrag_werkstatt():
    k, _ = fe.eintragen("werkstatt", "kursfreigabe", "kurs-1", "Kurs")
    return fe.auftrag_anlegen(k, "kurs_freigabe_zeigen", {"course_id": "c1"}, "mira")


def test_auftraege_nur_eigene(client):
    kw, ks = _kopf("werkstatt"), _kopf("selbstbild")
    aid = _auftrag_werkstatt()
    assert client.get("/api/freigaben/auftraege", headers=ks).json() == {"auftraege": []}
    a = client.get("/api/freigaben/auftraege", headers=kw).json()["auftraege"]
    assert a == [{"id": aid, "art": "kurs_freigabe_zeigen", "nutzlast": {"course_id": "c1"}}]


def test_auftrag_ergebnis(client):
    kw, ks = _kopf("werkstatt"), _kopf("selbstbild")
    aid = _auftrag_werkstatt()
    client.get("/api/freigaben/auftraege", headers=kw)
    url = f"/api/freigaben/auftraege/{aid}"
    assert client.post(url, json={"ok": True}, headers=ks).status_code == 404
    assert client.post(url, json={"ok": "ja"}, headers=kw).status_code == 422
    assert client.post(url, json={"ok": True}, headers=kw).json() == {"ok": True}
    assert client.post(url, json={"ok": True}, headers=kw).status_code == 404
    assert client.post("/api/freigaben/auftraege/kein-uuid", json={"ok": True},
                       headers=kw).status_code == 404


def test_anmeldung_bleibt_fuer_ui(client):
    r = client.get("/freigaben", follow_redirects=False)
    assert r.status_code in (303, 403)
    r = client.get("/api/freigabenX", follow_redirects=False)
    assert r.status_code in (303, 403)
    r = client.post("/api/freigabenX", json={}, follow_redirects=False)
    assert r.status_code == 403
    r = client.get("/api/freigaben/offen", follow_redirects=False)
    assert r.status_code == 401


class _Ausgabe(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def test_cli_nur_in_pipe(monkeypatch):
    out, err = _Ausgabe(True), _Ausgabe(False)
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    assert freigabe_schluessel.main(["anlegen", "werkstatt"]) == 2
    assert out.getvalue() == ""
    assert server._q("select 1 from freigabe_schluessel") == []

    out, err = _Ausgabe(False), _Ausgabe(False)
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    assert freigabe_schluessel.main(["anlegen", "werkstatt"]) == 0
    schluessel = out.getvalue()
    assert schluessel and "\n" not in schluessel
    assert fe.schluessel_herkunft(schluessel) == "werkstatt"
    assert schluessel not in err.getvalue() and "angelegt: werkstatt" in err.getvalue()

    # ersetzt den alten Schluessel
    out2 = _Ausgabe(False)
    monkeypatch.setattr("sys.stdout", out2)
    assert freigabe_schluessel.main(["anlegen", "werkstatt"]) == 0
    assert fe.schluessel_herkunft(schluessel) is None
    assert fe.schluessel_herkunft(out2.getvalue()) == "werkstatt"


def test_cli_unbekannte_herkunft(monkeypatch):
    monkeypatch.setattr("sys.stdout", _Ausgabe(False))
    monkeypatch.setattr("sys.stderr", _Ausgabe(False))
    assert freigabe_schluessel.main(["anlegen", "sales"]) == 2
