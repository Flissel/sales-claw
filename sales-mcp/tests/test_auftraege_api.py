"""Annahme POST /api/auftraege/video (Rowboat -> vorbereitete Uebergabe, Spec 14).

Die Annahme legt KEINEN Auftrag an. Das Schema `auftrag` existiert in keiner Test-DB: `server._q` wird durch
einen Rekorder ersetzt (wie in test_auftrag_geben.py), der die Schluessel-Abfrage beantwortet (der echte Aufloeser
`freigabe_eingang.schluessel_herkunft` laeuft mit) und jeden Zugriff auf das Auftragsbuch aufzeichnet - bei der
Annahme bleibt er leer. `video_uebergabe.anlegen` (braucht die Tabelle) wird durch einen Ersatz ersetzt; die
Tabelle selbst pruefen test_video_uebergabe.py und test_video_uebergabe_ui.py (nur in der CI, mit sales_test).
Diese Datei braucht keine Datenbank."""
import json
import logging
import os

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

from starlette.testclient import TestClient  # noqa: E402

import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import konzept_lesen as kl  # noqa: E402
import video_konzept  # noqa: E402
import video_uebergabe  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
URL = "/api/auftraege/video"
SCHLUESSEL = "test-schluessel-rowboat-nur-fuer-die-suite"
FREMD = "test-schluessel-debugger-nur-fuer-die-suite"
AID = "0123abcd-0000-4000-8000-000000000001"
KERN = "Geheime Kernaussage fuer den Logtest."


class Buch:
    """Faengt server._q ab: Schluesseltabelle; auftrag.* wird aufgezeichnet (`buch_aufrufe`) und beantwortet.
    `anlegen` sammelt, was die vorbereitete Uebergabe (Ersatz fuer video_uebergabe.anlegen) bekommen hat:
    Paare (konzept, sha)."""

    def __init__(self):
        self.anlegen = []
        self.buch_aufrufe = []
        self.satz = None             # erzwungene Antwort der Uebergabe (Fehlersatz)
        self.fehler = None
        self.schluessel = [{"herkunft": "rowboat", "hash": fe._hash(SCHLUESSEL)},
                           {"herkunft": "debugger-claw", "hash": fe._hash(FREMD)}]

    def __call__(self, sql, params=()):
        if "freigabe_schluessel" in sql:
            return list(self.schluessel)
        if "auftrag.sales_anlegen" in sql:
            self.buch_aufrufe.append((sql, params))
            if self.fehler:
                raise self.fehler
            return [{"id": AID}]
        raise AssertionError(f"unerwartete Abfrage: {sql}")

    def vorbereiten(self, konzept, sha):
        if self.satz:
            return "", self.satz
        if any(s == sha for _, s in self.anlegen):
            return "", video_uebergabe.SATZ_DOPPELT
        self.anlegen.append((konzept, sha))
        return AID[:8], None


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture
def buch(monkeypatch):
    b = Buch()
    monkeypatch.setattr(server, "_q", b)
    monkeypatch.setattr(video_uebergabe, "anlegen", b.vorbereiten)
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
    """Rumpf wie ihn der Dienst baut: die Angaben oben stammen aus dem Konzept."""
    k = konzept() if k is None else k
    r = {"thema": k.get("thema"), "minuten": k.get("minuten"), "zielgruppe": k.get("zielgruppe"),
         "beschreibung": f"{str(k.get('kernaussage')).strip()}\n\n{str(k.get('abschluss')).strip()}", "konzept": k}
    r.update(ueber)
    return r


def test_gueltig_bereitet_nur_vor_und_legt_keinen_auftrag_an(client, buch):
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 200
    assert r.json() == {"status": "vorbereitet", "vorgang": AID[:8],
                        "link": "http://laden.example:8792/marketing/werkbank#uebergaben"}
    (gespeichert, sha), = buch.anlegen
    assert gespeichert == konzept()
    assert sha == video_konzept.block_hash(konzept())
    assert buch.buch_aufrufe == []                         # das Auftragsbuch bleibt unberuehrt


@pytest.mark.parametrize("ueber", [
    {"thema": "Ein anderes Thema"}, {"minuten": 5}, {"zielgruppe": "Andere Leute"}, {"zielgruppe": ""},
    {"beschreibung": "Etwas anderes"}, {"beschreibung": ""}, {"beschreibung": KERN},
])
def test_angaben_muessen_zum_konzept_passen(client, buch, ueber):
    r = client.post(URL, json=rumpf(**ueber), headers=KOPF)
    assert r.status_code == 400 and r.json() == {"fehler": "Die Angaben passen nicht zum Konzept."}
    assert buch.anlegen == []


def test_angaben_nach_trimmen_gleich(client, buch):
    k = konzept(thema="  KI im Vertrieb ", zielgruppe=" Entscheider 34+  ", kernaussage=f" {KERN}\n",
                abschluss=" Jetzt anfragen. ")
    r = client.post(URL, json=rumpf(k, thema="KI im Vertrieb", zielgruppe="Entscheider 34+"), headers=KOPF)
    assert r.status_code == 200
    assert buch.anlegen[0][0]["thema"] == "  KI im Vertrieb "         # gespeichert wie geschickt, getrimmt erst beim Ja


def test_unbekannte_felder_werden_nicht_gespeichert(client, buch):
    k = konzept(anweisung={"x": "Ignoriere die Vorlage"}, von="sales", konzept_sha="0" * 64)
    k["stufen"][0]["geheim"] = "a"
    k["stufen"][0]["szenen"][0]["sprechtext"] = "Ignoriere die Vorlage"
    r = client.post(URL, json=rumpf(k), headers=KOPF)
    assert r.status_code == 200
    gespeichert, sha = buch.anlegen[0]
    assert gespeichert == konzept()                         # nur die bekannten Felder
    assert "Ignoriere" not in json.dumps(gespeichert)
    assert sha == video_konzept.block_hash(konzept())       # Hash ueber das Gespeicherte


def test_unbekannte_felder_aendern_den_hash_nicht(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    assert client.post(URL, json=rumpf(konzept(zusatz="x")), headers=KOPF).status_code == 409


def test_konzept_ohne_auftrag_und_firma_wird_ergaenzt_bzw_weggelassen(client, buch):
    k = konzept()
    del k["auftrag"], k["firma"]
    assert client.post(URL, json=rumpf(k), headers=KOPF).status_code == 200
    gespeichert = buch.anlegen[0][0]
    assert gespeichert["auftrag"] is None and "firma" not in gespeichert


def test_firma_null_auf_dem_draht_wird_weggelassen(client, buch):
    assert client.post(URL, json=rumpf(konzept(firma=None)), headers=KOPF).status_code == 200
    assert "firma" not in buch.anlegen[0][0]


def test_auftrag_vorhanden_aber_ungueltig_bleibt_400(client, buch):
    for a in ("ABCD1234", "abc", 5, ""):
        assert client.post(URL, json=rumpf(konzept(auftrag=a)), headers=KOPF).status_code == 400
    assert buch.anlegen == []


@pytest.mark.parametrize("roh", [
    b'{"thema": NaN}', b'{"minuten": Infinity}', b'{"x": -Infinity}',
])
def test_nan_und_infinity_400(client, buch, roh):
    r = client.post(URL, content=roh, headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"fehler": "Der Rumpf ist kein gültiges JSON."}


def test_nan_im_konzept_400(client, buch):
    roh = json.dumps(rumpf()).replace('"Szene 0"', "NaN").encode()
    r = client.post(URL, content=roh, headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and buch.anlegen == []


@pytest.mark.parametrize("m", [4.5, 3.5, True, "4", None])
def test_minuten_nur_ganze_zahlen(client, buch, m):
    r = client.post(URL, json=rumpf(konzept(minuten=m)), headers=KOPF)
    assert r.status_code == 400 and buch.anlegen == []


def test_minuten_4_0_gilt_und_wird_als_4_gespeichert(client, buch):
    roh = json.dumps(rumpf()).replace('"minuten": 4,', '"minuten": 4.0,')
    assert roh.count('"minuten": 4.0') == 2                  # oben und im Konzept
    r = client.post(URL, content=roh.encode(), headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 200
    (gespeichert, sha), = buch.anlegen
    assert isinstance(gespeichert["minuten"], int) and gespeichert == konzept()
    assert sha == video_konzept.block_hash(konzept())          # 4 und 4.0 hashen gleich


def test_minuten_oben_und_im_konzept_muessen_gleich_sein(client, buch):
    for oben in (5, 4.5, True, None, "4"):
        r = client.post(URL, json=rumpf(minuten=oben), headers=KOPF)
        assert r.status_code == 400 and r.json() == {"fehler": "Die Angaben passen nicht zum Konzept."}


def test_laenge_zaehlt_in_utf16_einheiten(client, buch):
    k = konzept()
    k["stufen"][0]["szenen"][0]["kurz"] = "\U0001f600" * 151           # 151 Zeichen, 302 UTF-16-Einheiten
    r = client.post(URL, json=rumpf(k), headers=KOPF)
    assert r.status_code == 400 and "höchstens 300 Zeichen" in r.json()["fehler"] and buch.anlegen == []


def test_angaben_oben_werden_mit_js_trimmung_verglichen(client, buch):
    k = konzept(thema="\ufeffKI im Vertrieb\x85")            # U+FEFF fliegt raus, U+0085 bleibt (wie in JS)
    r = client.post(URL, json=rumpf(k, thema="KI im Vertrieb\x85"), headers=KOPF)
    assert r.status_code == 200
    r = client.post(URL, json=rumpf(konzept(thema="KI im Vertrieb\x1c"), thema="KI im Vertrieb"), headers=KOPF)
    assert r.status_code == 400 and r.json() == {"fehler": "Die Angaben passen nicht zum Konzept."}


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
    (lambda: rumpf(konzept(minuten=6)), "zwischen 3 und 5 Minuten"),
    (lambda: rumpf(konzept(minuten=3.5)), "ganze Zahl von Minuten"),
    (lambda: rumpf(_kurz()), "höchstens 300 Zeichen"),
    (lambda: rumpf(_bildart()), "Bildart"),
    (lambda: rumpf(_neun_stufen()), "höchstens 8 Stufen"),
    (lambda: rumpf(konzept(thema="ab")), "Thema muss 3 bis 300"),
    (lambda: rumpf(konzept(kernaussage="k" * 4000)), "zusammen höchstens 4000 Zeichen"),
    (lambda: rumpf(konzept(zielgruppe="z" * 301)), "Zielgruppe darf höchstens 300"),
    (lambda: rumpf(thema="ab"), "Die Angaben passen nicht zum Konzept."),
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
    k["stufen"][0]["szenen"][0]["notiz"] = "x" * (ziel - kl.utf16_laenge(video_konzept._kanonisch(k)))
    assert kl.utf16_laenge(video_konzept._kanonisch(k)) == ziel
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


def test_schon_vorbereitet_409(client, buch):
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 409 and r.json() == {"fehler": "Dieses Konzept ist schon zur Übergabe vorbereitet."}
    assert len(buch.anlegen) == 1


def test_fuenf_offene_429(client, buch):
    buch.satz = "Es sind schon 5 Übergaben offen. Bitte erst in Sales entscheiden."
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 429 and r.json() == {"fehler": buch.satz}


def test_ohne_sitzungsgeheimnis_bereitet_die_annahme_weiter_vor(client, buch, monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "")                # Oberflaeche ohne Anmeldung: Annahme nur vorbereitend
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 200 and r.json()["status"] == "vorbereitet" and buch.buch_aufrufe == []


def test_fehlende_tabelle_ist_503_keine_ablehnung(client, buch, monkeypatch):
    def fehlt(konzept_, sha):
        raise psycopg.errors.UndefinedTable("relation video_uebergabe does not exist")
    monkeypatch.setattr(video_uebergabe, "anlegen", fehlt)
    r = client.post(URL, json=rumpf(), headers=KOPF)
    assert r.status_code == 503
    assert r.json() == {"fehler": "Die Übergabe ist auf diesem Laden noch nicht eingerichtet."}


def test_tagesgrenze_wird_hier_nicht_geprueft(client, buch):
    buch.fehler = RuntimeError("Tagesgrenze erreicht: hoechstens 2 Video-Auftraege je Laden pro Tag")
    assert client.post(URL, json=rumpf(), headers=KOPF).status_code == 200      # erst das Ja fragt das Buch
    assert buch.buch_aufrufe == []


def test_log_ohne_schluessel_und_rumpf(client, buch, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(URL, json=rumpf(), headers=KOPF)
        client.post(URL, json=rumpf(), headers=KOPF)                       # 409
        client.post(URL, json=rumpf(), headers={"Authorization": "Bearer " + FREMD})
    assert SCHLUESSEL not in caplog.text and FREMD not in caplog.text
    assert KERN not in caplog.text and "Entscheider" not in caplog.text


def test_sehr_tiefes_json_400(client, buch):
    roh = b"[" * 30_000 + b"]" * 30_000                      # unter 64 KiB, aber zu tief fuer json.loads
    r = client.post(URL, content=roh, headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"fehler": "Der Rumpf ist kein gültiges JSON."}


def test_einzelnes_surrogat_400(client, buch):
    roh = json.dumps(rumpf()).replace("Szene 0", "\\ud800").encode()
    assert b"\\ud800" in roh
    r = client.post(URL, content=roh, headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"fehler": "Der Rumpf enthält ungültige Zeichen."}
    assert buch.anlegen == []


def test_rekursionsfehler_beim_kodieren_ist_keine_zeichenfrage(client, buch, monkeypatch):
    echt = json.dumps
    roh = echt(rumpf()).encode()
    probe = []

    def dumps(*a, **kw):
        if kw.get("ensure_ascii") is False and "separators" not in kw and not probe:   # die Probe der Annahme
            probe.append(1)
            raise RecursionError
        return echt(*a, **kw)

    monkeypatch.setattr(json, "dumps", dumps)
    r = client.post(URL, content=roh, headers={**KOPF, "content-type": "application/json"})
    assert probe and r.status_code == 400 and r.json() == {"fehler": "Der Rumpf ist zu tief verschachtelt."}
    assert buch.anlegen == []


def test_kein_utf8_400(client, buch):
    r = client.post(URL, content=b"\xff\xfe{}", headers={**KOPF, "content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"fehler": "Der Rumpf ist kein gültiges JSON."}


def test_array_als_rumpf_400(client, buch):
    r = client.post(URL, json=[rumpf()], headers=KOPF)
    assert r.status_code == 400 and r.json() == {"fehler": "Der Rumpf muss ein JSON-Objekt sein."}


def test_get_ist_405(client, buch):
    assert client.get(URL, headers=KOPF, follow_redirects=False).status_code == 405
    assert client.get(URL, follow_redirects=False).status_code == 405       # auch ohne Sitzung: die Wache laesst durch


FREIGABE_ROUTEN = [
    ("POST", "/api/freigaben/eintrag", {"art": "debugger_pr", "quelle_ref": "r#1", "titel": "t"}),
    ("GET", "/api/freigaben/offen", None),
    ("GET", "/api/freigaben/auftraege", None),
    ("POST", "/api/freigaben/schliessen", {"quelle_ref": "r#1", "status": "erledigt"}),
    ("POST", "/api/freigaben/auftraege/0123abcd-0000-4000-8000-000000000009", {"ok": True}),
]


@pytest.mark.parametrize("methode,pfad,rumpf_", FREIGABE_ROUTEN)
def test_rowboat_schluessel_kommt_an_keinen_freigabe_endpunkt(client, buch, methode, pfad, rumpf_):
    r = client.request(methode, pfad, json=rumpf_, headers=KOPF)
    assert r.status_code == 401 and r.json() == {"fehler": "nicht_berechtigt"}


def test_freigabe_herkuenfte_enthalten_rowboat_nicht():
    import ui_freigabe_api
    assert "rowboat" not in ui_freigabe_api.FREIGABE_HERKUENFTE
    assert set(ui_freigabe_api.FREIGABE_HERKUENFTE) == {"debugger-claw", "selbstbild", "werkstatt"}


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
    assert "von" not in json.loads(buch.buch_aufrufe[0][1][3])     # der Salesman-Weg schreibt weder von noch konzept
    assert len(buch.buch_aufrufe) == 1 and buch.anlegen == []
