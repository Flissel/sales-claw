"""Annahme POST /api/auftraege/video (Rowboat -> Video-Werkbank).

Das Schema `auftrag` existiert in keiner Test-DB: `server._q` wird durch einen Rekorder ersetzt (wie in
test_auftrag_geben.py). Der Rekorder beantwortet auch die Schluessel-Abfrage, damit der echte Aufloeser
(`freigabe_eingang.schluessel_herkunft`) mitlaeuft - die Tests brauchen keine Datenbank.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

from starlette.testclient import TestClient  # noqa: E402

import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import video_konzept  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
URL = "/api/auftraege/video"
SCHLUESSEL = "test-schluessel-rowboat-nur-fuer-die-suite"
FREMD = "test-schluessel-debugger-nur-fuer-die-suite"
AID = "0123abcd-0000-4000-8000-000000000001"
KERN = "Geheime Kernaussage fuer den Logtest."


class Buch:
    """Faengt server._q ab: Schluesseltabelle und auftrag.* (anlegen, eigene) mit einem kleinen Gedaechtnis."""

    def __init__(self):
        self.anlegen = []          # (laden, mandant, art, eingabe)
        self.zeilen = []           # was sales_eigene liefert
        self.fehler = None
        self.eigene_aufrufe = []
        self.schluessel = [{"herkunft": "rowboat", "hash": fe._hash(SCHLUESSEL)},
                           {"herkunft": "debugger-claw", "hash": fe._hash(FREMD)}]

    def __call__(self, sql, params=()):
        if "freigabe_schluessel" in sql:
            return list(self.schluessel)
        if "auftrag.sales_anlegen" in sql:
            if self.fehler:
                raise self.fehler
            laden, mandant, art, eingabe = params
            self.anlegen.append((laden, mandant, art, json.loads(eingabe)))
            self.zeilen.append({"id": AID, "art": art, "stand": "offen", "laden": laden,
                                "eingabe": json.loads(eingabe),
                                "angelegt": datetime.now(timezone.utc).isoformat()})
            return [{"id": AID}]
        if "auftrag.sales_eigene" in sql:
            laden, staende = params
            self.eigene_aufrufe.append((laden, list(staende)))
            return [{"a": z} for z in self.zeilen if z["laden"] == laden and z["stand"] in staende]
        raise AssertionError(f"unerwartete Abfrage: {sql}")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture
def buch(monkeypatch):
    b = Buch()
    monkeypatch.setattr(server, "_q", b)
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    monkeypatch.setattr(ui, "UI_BASIS_URL", "http://laden.example:8792")
    return b


@pytest.fixture
def client(buch):
    return TestClient(ui.app, headers=HOST)


KOPF = {"Authorization": "Bearer " + SCHLUESSEL}


def konzept(**ueber):
    k = {
        "thema": "KI im Vertrieb", "zielgruppe": "Entscheider 34+", "minuten": 4,
        "hook": "Was kostet ein verlorener Lead?", "kernaussage": KERN,
        "stufen": [
            {"name": "Problem", "szenen": [{"kurz": f"Szene {i}", "bildart": "slide"} for i in range(4)]},
            {"name": "Lösung", "szenen": [{"kurz": f"Szene {i}", "bildart": "clip", "notiz": "n"}
                                         for i in range(4, 8)]},
        ],
        "abschluss": "Jetzt anfragen.", "auftrag": None, "firma": "fin2gether",
        "pfad": "knowledge/Konzepte/ki.html", "name": "ki",
    }
    k.update(ueber)
    return k


def rumpf(k=None, **ueber):
    r = {"thema": "KI im Vertrieb", "minuten": 4, "zielgruppe": "Entscheider 34+",
         "beschreibung": "Ein Konzept aus Rowboat.", "konzept": konzept() if k is None else k}
    r.update(ueber)
    return r


def test_gueltig_legt_auftrag_an(client, buch):
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 200
    assert r.json() == {"auftrag": AID[:8], "id": AID,
                        "link": f"http://laden.example:8792/marketing/werkbank/{AID}"}
    assert r.json()["link"].endswith(AID)
    (laden, mandant, art, eingabe), = buch.anlegen
    assert (laden, mandant, art) == ("ivan", "fin2gether", "video")
    assert eingabe["von"] == "rowboat"
    assert eingabe["konzept"] == konzept()
    assert eingabe["konzept_sha"] == video_konzept.block_hash(konzept())
    assert (eingabe["thema"], eingabe["minuten"]) == ("KI im Vertrieb", 4)
    assert eingabe["beschreibung"] == "Ein Konzept aus Rowboat."


def test_zielgruppe_vorgabe_wenn_leer(client, buch):
    r = client.post(URL, json=rumpf(zielgruppe=""), headers=KOPF)
    assert r.status_code == 200
    assert buch.anlegen[0][3]["zielgruppe"] == server.VIDEO_ZIELGRUPPE_VORGABE


def test_ohne_schluessel_401(client, buch):
    r = client.post(URL, json=rumpf())
    assert r.status_code == 401 and r.json() == {"fehler": "Nicht berechtigt."}
    assert buch.anlegen == []


def test_falscher_schluessel_401(client, buch):
    for kopf in ({"Authorization": "Bearer falsch"}, {"Authorization": "Basic abc"}):
        assert client.post(URL, json=rumpf(), headers=kopf).status_code == 401
    assert buch.anlegen == []


def test_schluessel_anderer_herkunft_401(client, buch):
    r = client.post(URL, json=rumpf(), headers={"Authorization": "Bearer " + FREMD})
    assert r.status_code == 401 and buch.anlegen == []


def test_firma_passt_nicht_400(client, buch):
    r = client.post(URL, json=rumpf(konzept(firma="andere-firma")), headers=KOPF)
    assert r.status_code == 400 and "anderen Firma" in r.json()["fehler"]
    assert buch.anlegen == []


def test_konzept_ohne_firma_geht(client, buch):
    k = konzept()
    del k["firma"]
    assert client.post(URL, json=rumpf(k), headers=KOPF).status_code == 200


def test_laden_ohne_marketing_firma_400(client, buch, monkeypatch):
    monkeypatch.setenv("MARKETING_MANDANT", "")
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 400
    assert r.json() == {"fehler": "Für diesen Laden ist keine Marketing-Firma eingetragen."}
    assert buch.anlegen == []


def test_fremdes_schema_400(client, buch, monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "ivan_x")
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 400 and r.json() == {"fehler": "Aufträge gibt es in diesem Laden noch nicht."}


def _szenen(n):
    return konzept(stufen=[{"name": "A", "szenen": [{"kurz": "s", "bildart": "slide"} for _ in range(n)]}])


def _kurz():
    k = konzept()
    k["stufen"][0]["szenen"][0]["kurz"] = "k" * 301
    return k


def _bildart():
    k = konzept()
    k["stufen"][0]["szenen"][0]["bildart"] = "foto"
    return k


def _neun_stufen():
    return konzept(stufen=[{"name": f"S{i}", "szenen": [{"kurz": "s", "bildart": "slide"}] * 2}
                           for i in range(9)])


@pytest.mark.parametrize("body,teil", [
    (lambda: rumpf(_szenen(6)), "8 bis 15 Szenen"),
    (lambda: rumpf(minuten=6), "3 bis 5 Minuten"),
    (lambda: rumpf(konzept(minuten=6)), "3 und 5 Minuten"),
    (lambda: rumpf(_kurz()), "höchstens 300 Zeichen"),
    (lambda: rumpf(_bildart()), "Bildart"),
    (lambda: rumpf(_neun_stufen()), "höchstens 8 Stufen"),
    (lambda: rumpf(thema="ab"), "Thema"),
    (lambda: rumpf(beschreibung="b" * 4001), "4000 Zeichen"),
    (lambda: rumpf(zielgruppe="z" * 301), "Zielgruppe"),
    (lambda: rumpf(thema=5), "müssen Text sein"),
    (lambda: {"thema": "KI im Vertrieb", "minuten": 4}, "Videokonzept fehlt"),
])
def test_pruefung_400(client, buch, body, teil):
    r = client.post(URL, json=body(), headers=KOPF)
    assert r.status_code == 400 and teil in r.json()["fehler"]
    assert buch.anlegen == []


def test_kein_json_400(client, buch):
    r = client.post(URL, content=b"{kaputt", headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and "JSON" in r.json()["fehler"]


def _auf_block(ziel):
    k = konzept()
    k["stufen"][0]["szenen"][0]["notiz"] = ""
    k["stufen"][0]["szenen"][0]["notiz"] = "x" * (ziel - len(video_konzept._kanonisch(k)))
    assert len(video_konzept._kanonisch(k)) == ziel
    return k


def test_block_mit_20000_zeichen_wird_angenommen(client, buch):
    r = client.post(URL, json=rumpf(_auf_block(20_000)), headers=KOPF)
    assert r.status_code == 200
    assert client.post(URL, json=rumpf(_auf_block(20_001)), headers=KOPF).status_code == 400


def test_rumpf_64_kib_plus_eins_413(client, buch):
    grenze = 64 * 1024
    r = client.post(URL, content=b"x" * (grenze + 1), headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 413 and r.json() == {"fehler": "Der Rumpf ist größer als 64 KiB."}
    assert buch.anlegen == []


def test_rumpf_ohne_laengenangabe_413(client, buch):
    def stuecke():
        for _ in range(9):
            yield b"x" * 8192
    r = client.post(URL, content=stuecke(), headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 413 and buch.anlegen == []


def test_gleiches_konzept_binnen_zehn_minuten_409(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 409
    assert AID[:8] in r.json()["fehler"] and "10 Minuten" in r.json()["fehler"]
    assert len(buch.anlegen) == 1


def test_doppelte_uebergabe_ignoriert_auftrag_pfad_name(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    k = konzept(auftrag="abcd1234", pfad="knowledge/Konzepte/neu.html", name="neu")
    assert client.post(URL, json=rumpf(k), headers=KOPF).status_code == 409


def test_anderes_konzept_ist_keine_doppelte_uebergabe(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    assert client.post(URL, json=rumpf(konzept(hook="Ein anderer Hook")), headers=KOPF).status_code == 200
    assert len(buch.anlegen) == 2


def test_nach_zehn_minuten_wieder_moeglich(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    buch.zeilen[0]["angelegt"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    assert len(buch.anlegen) == 2


def test_abgebrochener_auftrag_blockiert_nicht(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    buch.zeilen[0]["stand"] = "abgebrochen"
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200


def test_unlesbare_zeit_lehnt_lieber_ab(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    buch.zeilen[0]["angelegt"] = "kein datum"
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 409


def test_andere_laden_zaehlen_nicht(client, buch, monkeypatch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    monkeypatch.setenv("LADEN_PRAEFIX", "sales")
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200


def test_fremde_zeilen_ohne_konzept_werden_uebersprungen(client, buch):
    buch.zeilen.append({"id": "x" * 36, "art": "reel", "stand": "offen", "laden": "ivan",
                        "eingabe": {"thema": "t"}, "angelegt": datetime.now(timezone.utc).isoformat()})
    buch.zeilen.append({"id": "y" * 36, "art": "video", "stand": "offen", "laden": "ivan",
                        "eingabe": {"von": "sales"}, "angelegt": datetime.now(timezone.utc).isoformat()})
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200


def test_tagesgrenze_429(client, buch):
    buch.fehler = RuntimeError("Tagesgrenze erreicht: hoechstens 2 Video-Auftraege je Laden pro Tag")
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 429
    assert r.json() == {"fehler": "Heute sind schon zwei Videos bestellt – morgen wieder."}


def test_anderer_buchfehler_400_ohne_details(client, buch):
    buch.fehler = RuntimeError("secret detail 123")
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 400 and "secret" not in r.text


def test_log_ohne_schluessel_und_rumpf(client, buch, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(URL, json=rumpf(), headers=KOPF)
        client.post(URL, json=rumpf(), headers=KOPF)                       # 409
        client.post(URL, json=rumpf(), headers={"Authorization": "Bearer " + FREMD})
    assert SCHLUESSEL not in caplog.text and FREMD not in caplog.text
    assert KERN not in caplog.text and "Entscheider" not in caplog.text


def test_ohne_sitzung_erreichbar_aber_nur_post(client, buch):
    # Die Anmelde-Wache (UI_SESSION_SECRET gesetzt) laesst genau diesen Pfad ohne Sitzung durch ...
    assert client.post(URL, json=rumpf(), headers=KOPF, follow_redirects=False).status_code == 200
    # ... andere Pfade bleiben hinter der Anmeldung.
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (303, 401)


def test_bestehender_auftrag_geben_video_unveraendert(buch):
    r = json.loads(server.auftrag_geben("video", "KI im Vertrieb", beschreibung="Text", minuten=4))
    assert r["auftrag"] == AID[:8]
    assert json.loads(server.auftrag_geben("video", "KI im Vertrieb", minuten=6)) == {
        "fehler": "Das Video dauert 3 bis 5 Minuten."}
    assert json.loads(server.auftrag_geben("video", "KI im Vertrieb", beschreibung="b" * 4001)) == {
        "fehler": "Die Beschreibung darf höchstens 4000 Zeichen haben."}
    assert json.loads(server.auftrag_geben("video", "KI im Vertrieb", zielgruppe="z" * 301)) == {
        "fehler": "Die Zielgruppe darf höchstens 300 Zeichen haben."}
    assert "von" not in buch.anlegen[0][3]              # der Salesman-Weg schreibt weder von noch konzept
