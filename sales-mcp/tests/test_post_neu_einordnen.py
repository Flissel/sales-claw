"""Neu-Sortierung des Altbestands: Vorschau, Bericht, Anwenden.

DB-Tests nur gegen sales_test. `einordnen` ist durch eine Attrappe ersetzt - das
Modell wird nie gerufen.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import post_neu_einordnen as neu  # noqa: E402
import post_struktur  # noqa: E402
import server  # noqa: E402
from gateway import GatewayFehler  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' - erlaubt ist nur 'sales_test'.")


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_konten cascade")
        conn.execute("delete from sales_test.activities where type = 'kundenantwort'")
        conn.execute("truncate sales_test.post_mails")


@pytest.fixture(autouse=True)
def sauber():
    _aufraeumen()
    yield
    _aufraeumen()


@pytest.fixture
def konto_id():
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values ('felix', 'gmx-test', 'gmx', 'gmx-test@gmx.de', 'ui') returning id"
        ).fetchone()["id"]


def _mail(konto, uid, *, von="Shop <info@shop-test.example>", betreff="Hallo", quelle="modell",
          version=1, sensibel=False, bereich="business", fach="Sonstiges", aufrufe=1,
          status="eingeordnet", text="Mailtext"):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, text, "
            "auszug, an, anhaenge, status, bereich, fach, sensibel, einordnung_quelle, "
            "einordnung_version, modellaufrufe, eingeordnet_am) "
            "values (%s, %s, %s, 'felix', %s, %s, %s, 'Auszug', 'felix@x', '{a.pdf}', %s, %s, %s, "
            "%s, %s, %s, %s, now() - interval '3 days') returning id",
            (konto, uid, f"m{uid}@x", von, betreff, text, status, bereich, fach, sensibel,
             quelle, version, aufrufe)).fetchone()["id"]


def _zeile(mail_id):
    with server.pool.connection() as conn:
        return conn.execute("select * from post_mails where id = %s", (mail_id,)).fetchone()


def _fake(ergebnis=None, aufrufe=1, gesehen=None):
    ergebnis = ergebnis or {}

    def einordnen(mail, konto):
        if gesehen is not None:
            gesehen.append(mail)
        return post_einordnung.Einordnung(
            ergebnis.get("bereich", "privat"), ergebnis.get("fach", "Rechnungen"),
            ergebnis.get("sensibel", False), ergebnis.get("quelle", "pruefer"),
            ergebnis.get("begruendung", "neu"), ergebnis.get("unterfach"),
            aufrufe=aufrufe, vorschlaege=ergebnis.get("vorschlaege"))
    return einordnen


@pytest.fixture(autouse=True)
def grenze_hoch(monkeypatch):
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 500)


def test_vorschau_aendert_echte_spalten_nicht(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, betreff="Rechnung", fach="Sonstiges")
    vorher = _zeile(mid)
    gesehen = []
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(gesehen=gesehen))
    assert neu.vorschau(10) == 1
    nachher = _zeile(mid)
    assert nachher["vorschau"]["fach"] == "Rechnungen" and nachher["vorschau_am"] is not None
    assert nachher["vorschau"]["aufrufe"] == 1
    for spalte in ("bereich", "fach", "unterfach", "sensibel", "einordnung_quelle", "begruendung",
                   "einordnung_version", "status", "text", "auszug", "an", "anhaenge",
                   "modellaufrufe", "eingeordnet_am", "vorschlaege"):
        assert nachher[spalte] == vorher[spalte], spalte
    # Die Mail wird so gebaut wie im Betrieb.
    assert gesehen[0]["betreff"] == "Rechnung" and gesehen[0]["besitzer"] == "felix"


def test_vorschau_ueberspringt_mensch_und_version_2(monkeypatch, konto_id):
    mensch = _mail(konto_id, 1, quelle="mensch")
    v2 = _mail(konto_id, 2, version=2)
    offen = _mail(konto_id, 3, status="fehler", fach="Zum Nachsehen", bereich="privat")
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    assert neu.vorschau(10) == 1
    assert _zeile(mensch)["vorschau"] is None and _zeile(v2)["vorschau"] is None
    assert _zeile(offen)["vorschau"] is not None
    # Ohne --alle keine zweite Vorschau; mit --alle wieder.
    assert neu.vorschau(10) == 0
    assert neu.vorschau(10, alle=True) == 1


def test_vorschau_haelt_tagesgrenze(monkeypatch, konto_id):
    for uid in range(1, 6):
        _mail(konto_id, uid)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 3)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    bearbeitet = neu.vorschau(10)
    assert bearbeitet <= 2 and bearbeitet >= 1
    # Die Vorschau-Aufrufe zaehlen in der Tagesbilanz.
    assert post_abholen.modellaufrufe_heute() == 2 * bearbeitet
    assert post_abholen.modellaufrufe_heute() <= 3


def test_anwenden_uebernimmt_vorschau_ohne_modell(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, aufrufe=1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"bereich": "privat", "fach": "Rechnungen", "unterfach": None, "quelle": "pruefer",
         "begruendung": "grund"}, aufrufe=2))
    neu.vorschau(10)

    def verboten(*a, **k):
        pytest.fail("anwenden darf das Modell nicht rufen")
    monkeypatch.setattr(post_einordnung, "einordnen", verboten)
    assert neu.anwenden() == 1
    z = _zeile(mid)
    assert (z["bereich"], z["fach"], z["einordnung_quelle"], z["begruendung"]) == (
        "privat", "Rechnungen", "pruefer", "grund")
    assert z["einordnung_version"] == 2 and z["vorschau"] is None and z["status"] == "eingeordnet"
    assert z["modellaufrufe"] == 1            # nicht doppelt gezaehlt
    assert z["text"] == "Mailtext"            # nicht sensibel: Inhalt bleibt
    assert neu.anwenden() == 0                # wiederholbar


def test_anwenden_laesst_zwischenzeitliche_korrektur_unberuehrt(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, fach="Sonstiges")
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    neu.vorschau(10)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set einordnung_quelle = 'mensch' where id = %s", (mid,))
    vorher = _zeile(mid)
    assert neu.anwenden() == 0
    nachher = _zeile(mid)
    assert nachher["fach"] == "Sonstiges" and nachher["einordnung_quelle"] == "mensch"
    assert nachher["einordnung_version"] == 1 and nachher["vorschau"] == vorher["vorschau"]


def test_anwenden_macht_sensible_nie_unsensibel(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=True, text=None)
    # Alte Zeile war sensibel, hatte aber noch Reste in an/auszug/anhaenge (Fail-closed-Probe).
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"sensibel": False, "begruendung": "geheimer freitext",
         "vorschlaege": {"sortierer": {"fach": "x", "begruendung": "frei"},
                         "pruefer": {"fach": "y", "begruendung": "frei"}}}))
    neu.vorschau(10)
    v = _zeile(mid)["vorschau"]
    assert "frei" not in str(v["vorschlaege"]) and "geheimer" not in str(v)
    assert neu.anwenden() == 1
    z = _zeile(mid)
    assert z["sensibel"] is True
    assert z["text"] is None and z["auszug"] is None and z["an"] is None and z["anhaenge"] == []
    assert "geheimer" not in (z["begruendung"] or "") and "frei" not in str(z["vorschlaege"])


def test_anwenden_leert_neu_sensible(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=False)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"sensibel": True, "fach": "Konten & Sicherheit", "begruendung": "modell:sensibel",
         "vorschlaege": {"sortierer": {"fach": "x", "begruendung": "frei"}}}))
    neu.vorschau(10)
    neu.anwenden()
    z = _zeile(mid)
    assert z["sensibel"] is True and z["text"] is None and z["auszug"] is None
    assert z["an"] is None and z["anhaenge"] == []
    assert "frei" not in str(z["vorschlaege"])


def test_pruefer_ausfall_wird_zum_nachsehen(monkeypatch, konto_id):
    mid = _mail(konto_id, 1)

    def ausfall(mail, konto):
        raise post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
            "business", "Sonstiges", False, "modell", "sortierer-grund", None, aufrufe=1))
    monkeypatch.setattr(post_einordnung, "einordnen", ausfall)
    assert neu.vorschau(10) == 1
    v = _zeile(mid)["vorschau"]
    assert (v["bereich"], v["fach"], v["aufrufe"]) == ("privat", post_struktur.UNKLAR, 2)
    assert v["vorschlaege"]["sortierer"]["begruendung"] == "sortierer-grund"


def test_bericht_enthaelt_keine_betreffs(monkeypatch, konto_id):
    _mail(konto_id, 1, betreff="GEHEIM-123", von="Max Muster <max@mystery-test.example>")
    _mail(konto_id, 2, betreff="GEHEIM-456", von="x@instagram.com")
    _mail(konto_id, 3, betreff="GEHEIM-789")                  # bleibt offen
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"quelle": "katalog", "fach": "Soziale Netzwerke", "unterfach": "Instagram"}))
    neu.vorschau(2)
    b = neu.bericht()
    text = str(b)
    assert "GEHEIM" not in text and "max@" not in text
    assert b["offen"] == 1
    assert sum(b["alt"].values()) == 2 and sum(b["neu"].values()) == 2
    assert ("instagram.com", "Soziale Netzwerke", "Instagram", 1) in b["katalog"]
    assert ("mystery-test.example", 1) in b["ohne_katalog"]


def test_fehler_wird_gezaehlt_und_nicht_wiederholt(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=True, text=None)
    ruf = []

    def kaputt(mail, konto):
        ruf.append(1)
        raise GatewayFehler("x")
    monkeypatch.setattr(post_einordnung, "einordnen", kaputt)
    vorher = post_abholen.modellaufrufe_heute()
    assert neu.vorschau(10) == 1
    assert post_abholen.modellaufrufe_heute() > vorher
    v = _zeile(mid)["vorschau"]
    assert (v["fach"], v["begruendung"], v["sensibel"]) == (post_struktur.UNKLAR, "vorschau:fehler", True)
    assert neu.vorschau(10) == 0 and len(ruf) == 1


def test_fehler_senkt_rest_der_tagesgrenze(monkeypatch, konto_id):
    for uid in range(1, 6):
        _mail(konto_id, uid)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 4)

    def kaputt(mail, konto):
        raise RuntimeError("x")
    monkeypatch.setattr(post_einordnung, "einordnen", kaputt)
    assert neu.vorschau(10) == 2          # 4 // 2 Mails, nicht alle fuenf
    assert post_abholen.modellaufrufe_heute() == 2


def test_vorschau_kosten_ueberleben_anwenden(monkeypatch, konto_id):
    _mail(konto_id, 1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    neu.vorschau(10)
    nach_vorschau = post_abholen.modellaufrufe_heute()
    assert nach_vorschau == 2
    neu.anwenden()
    assert post_abholen.modellaufrufe_heute() == nach_vorschau


def test_vorschau_alle_zaehlt_aufsummiert(monkeypatch, konto_id):
    _mail(konto_id, 1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    neu.vorschau(10)
    erste = post_abholen.modellaufrufe_heute()
    neu.vorschau(10, alle=True)
    assert post_abholen.modellaufrufe_heute() == erste + 2
