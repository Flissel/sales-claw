"""Kursmitschrift erzeugen: KI (ollama.chat) und sales-auge sind ersetzt. Datenbank sales_test."""
import io
import json
import os
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_mitschrift as km  # noqa: E402
import kurs_pdf  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402

UID = "kurs-mitschrift-0001@sales-claw"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
JETZT = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
SEG = [{"sprecher": "Felix", "beginn": T0.isoformat(), "text": "Klick oben rechts auf Neu"},
       {"sprecher": "Diana", "beginn": (T0 + timedelta(minutes=5)).isoformat(),
        "text": "Und dann?"}]


class _Antwort:
    def __init__(self, status, daten):
        self.status = status
        self._daten = daten

    def read(self):
        return self._daten

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGE_URL", "http://auge.invalid:8790")
    ziel = tmp_path / "ablage"
    ziel.mkdir()
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(ziel))
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")


@pytest.fixture
def ablage(tmp_path):
    return tmp_path / "ablage"


@pytest.fixture
def auge_liefert_pdf(monkeypatch):
    def falsch(anfrage, timeout=None):
        return _Antwort(200, b"%PDF-1.7 test")

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", falsch)


@pytest.fixture
def auge_antwortet_503(monkeypatch):
    def falsch(anfrage, timeout=None):
        raise urllib.error.HTTPError(anfrage.full_url, 503, "weg", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", falsch)


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (1600, 900), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _bild(minute=1, status="fertig"):
    z = server._q(
        "insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash, "
        "beschreibung, beschreibung_status) values (%s, %s, %s, 1600, 900, %s, 'Folie', %s) "
        "returning id", (UID, T0 + timedelta(minutes=minute), _jpeg(), minute, status))
    return str(z[0]["id"])


def _zeile(uid=UID):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _gut(bid, titel="Termin anlegen"):
    return {"ueberblick": "Du lernst den Kalender kennen.",
            "abschnitte": [{"titel": titel,
                            "bilder": [{"bild_id": bid, "zu_sehen": "Der Kalender",
                                        "erklaert": "Felix zeigt Neu.",
                                        "schritte": ["Oben rechts auf Neu klicken"]}],
                            "merken": ["Neu steht oben rechts."]}],
            "offen": ["Diana fragte nach Serienterminen"]}


@pytest.fixture
def kurs_mitschrift():
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs Kalender', 'fertig') returning uid",
              (UID, BEGINN, BEGINN + timedelta(hours=1)))
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik) "
              "values (%s, %s::jsonb, 'fertig', '{}'::jsonb, now(), 'Kurse') returning id",
              (UID, json.dumps(SEG)))
    return _bild()


@pytest.fixture
def ki_liefert_gutes_json(monkeypatch, kurs_mitschrift):
    gesehen = {}

    def chat(system, nutzer, **kw):
        gesehen["system"], gesehen["nutzer"], gesehen["kw"] = system, nutzer, kw
        return json.dumps(_gut(kurs_mitschrift))

    monkeypatch.setattr(ollama, "chat", chat)
    return gesehen


@pytest.fixture
def ki_liefert_text(monkeypatch, kurs_mitschrift):
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: "Das ist kein JSON")


@pytest.fixture
def kurs_fertig(kurs_mitschrift, ki_liefert_gutes_json):
    km.erzeugen(UID, JETZT)
    return kurs_mitschrift


def test_erzeugen_speichert_json_und_stand(kurs_mitschrift, ki_liefert_gutes_json):
    j = km.erzeugen(UID, JETZT)
    z = _zeile()
    assert j["abschnitte"][0]["titel"] == "Termin anlegen"
    assert z["kurs_json"] == j
    assert z["kurs_stand"] == km.kurs_stand(UID)
    assert z["kurs_am"] == JETZT and z["kurs_versuche"] == 0 and z["kurs_status"] is None
    assert ki_liefert_gutes_json["kw"].get("als_json") is True
    ein = json.loads(ki_liefert_gutes_json["nutzer"])
    assert ein["bilder"][0]["bild_id"] == kurs_mitschrift
    assert ein["segmente"][0]["sprecher"] == "Felix"
    assert ein["datum"] == "14.11.2026" and ein["titel"] == "Kurs Kalender"


def test_ungepruefte_bilder_gehen_nicht_an_die_ki(kurs_mitschrift, ki_liefert_gutes_json):
    _bild(minute=2, status="offen")
    km.erzeugen(UID, JETZT)
    assert len(json.loads(ki_liefert_gutes_json["nutzer"])["bilder"]) == 1


def test_kaputtes_json_zaehlt_versuch(kurs_mitschrift, ki_liefert_text):
    with pytest.raises(ValueError):
        km.erzeugen(UID, JETZT)
    z = _zeile()
    assert z["kurs_versuche"] == 1 and z["kurs_am"] == JETZT
    assert z["kurs_status"] is None and z["kurs_json"] is None


def test_nach_drei_versuchen_fehler(kurs_mitschrift, ki_liefert_text):
    for n in range(km.MAX_VERSUCHE):
        assert _zeile()["kurs_status"] is None
        with pytest.raises(ValueError):
            km.erzeugen(UID, JETZT + timedelta(hours=n))
    z = _zeile()
    assert z["kurs_status"] == "fehler" and z["kurs_versuche"] == km.MAX_VERSUCHE


def test_ki_ausfall_zaehlt_versuch_und_wird_weitergereicht(kurs_mitschrift, monkeypatch):
    def chat(*a, **k):
        raise ollama.OllamaFehler("weg")

    monkeypatch.setattr(ollama, "chat", chat)
    with pytest.raises(ollama.OllamaFehler):
        km.erzeugen(UID, JETZT)
    assert _zeile()["kurs_versuche"] == 1


def test_erfolg_setzt_versuche_zurueck(kurs_mitschrift, monkeypatch):
    server._q("update termin_mitschriften set kurs_versuche = 2 where uid = %s returning id",
              (UID,))
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: json.dumps(_gut(kurs_mitschrift)))
    km.erzeugen(UID, JETZT)
    assert _zeile()["kurs_versuche"] == 0


def test_pruefen_ohne_abschnitte_oder_titel():
    for roh in (None, [], "x", {}, {"abschnitte": []}, {"abschnitte": "x"},
                {"abschnitte": [{"titel": "  "}]}, {"abschnitte": [{"bilder": []}, 5]}):
        with pytest.raises(ValueError):
            km.pruefen(roh, set())


def test_unbekannte_bild_id_wird_verworfen():
    j = km.pruefen({"ueberblick": "x", "abschnitte": [
        {"titel": "A", "bilder": [{"bild_id": "fremd"}, {"bild_id": "b1"}, {"bild_id": "b1"}],
         "merken": []}], "offen": []}, {"b1"})
    assert [b["bild_id"] for b in j["abschnitte"][0]["bilder"]] == ["b1"]
    j = km.pruefen({"ueberblick": "x", "abschnitte": [
        {"titel": "A", "bilder": [{"bild_id": "fremd"}], "merken": []}], "offen": []}, {"b1"})
    assert j["abschnitte"][0]["bilder"] == []


def test_hoechstens_sechs_bilder_je_abschnitt():
    ids = [f"b{i}" for i in range(20)]
    j = km.pruefen({"abschnitte": [{"titel": "A", "bilder": [{"bild_id": i} for i in ids]}]},
                   set(ids))
    gew = [b["bild_id"] for b in j["abschnitte"][0]["bilder"]]
    assert len(gew) == km.MAX_BILDER_ABSCHNITT == 6
    assert gew[0] == "b0" and gew == sorted(gew, key=ids.index)
    assert gew[-1] in ids[12:]          # gleichmaessig verteilt, nicht nur der Anfang


def test_pruefen_erzwingt_listen_und_strings():
    j = km.pruefen({"ueberblick": 5, "abschnitte": [
        {"titel": "A", "bilder": "nein", "merken": "ein Satz"},
        {"titel": 7, "bilder": []},
        {"titel": "B", "bilder": [{"bild_id": "b1", "zu_sehen": None, "erklaert": ["x"],
                                   "schritte": "oben klicken"}], "merken": [1, " ok ", ""]}],
        "offen": None}, {"b1"})
    assert j["ueberblick"] == "" and j["offen"] == []
    assert [a["titel"] for a in j["abschnitte"]] == ["A", "B"]
    assert j["abschnitte"][0] == {"titel": "A", "bilder": [], "merken": []}
    b = j["abschnitte"][1]
    assert b["merken"] == ["ok"]
    assert b["bilder"][0] == {"bild_id": "b1", "zu_sehen": "", "erklaert": "", "schritte": []}


def test_lernenden_fassung_ohne_offen_und_transkript(kurs_fertig):
    h = km.kurs_html(UID, "lernend")
    assert "Offen" not in h and "Transkript" not in h and "Intern" not in h
    assert "Serientermine" not in h and "Klick oben rechts auf Neu" not in h
    assert "Merken" in h and "Zu sehen" in h and "Erklärt" in h and "<ol><li>Oben rechts" in h
    assert 'href="#a1"' in h and 'id="a1"' in h and "Überblick" in h
    assert h.count("<img") == 1 and "data:image/jpeg;base64," in h


def test_felix_fassung_mit_offen_und_intern(kurs_fertig):
    h = km.kurs_html(UID, "felix")
    assert "Offen / nachfragen" in h and "Serienterminen" in h
    assert km.INTERN_HINWEIS in h and "Merken" in h
    assert "Transkript" not in h


def test_html_escaped_und_unbekannte_fassung(kurs_fertig):
    j = _zeile()["kurs_json"]
    j["abschnitte"][0]["titel"] = "<script>alert(1)</script>"
    server._q("update termin_mitschriften set kurs_json = %s::jsonb where uid = %s returning id",
              (json.dumps(j), UID))
    h = km.kurs_html(UID, "felix")
    assert "<script>" not in h and "&lt;script&gt;" in h
    with pytest.raises(ValueError):
        km.kurs_html(UID, "intern")


def test_bild_wird_verkleinert(kurs_fertig):
    import base64
    h = km.kurs_html(UID, "lernend")
    roh = h.split('src="data:image/jpeg;base64,')[1].split('"')[0]
    assert max(Image.open(io.BytesIO(base64.b64decode(roh))).size) <= km.BILD_KANTE


def test_ablegen_legt_drei_dateien(kurs_fertig, ablage, auge_liefert_pdf):
    assert km.ablegen(UID) == "fertig"
    z = _zeile()
    assert z["kurs_status"] == "fertig"
    assert z["kurs_pfad"].startswith("Kurse/") and z["kurs_pfad"].endswith("_kurs-intern.html")
    assert z["kurs_pfad_lernend"].endswith("_kurs.html") and z["kurs_pdf"].endswith("_kurs.pdf")
    assert all((ablage / z[k]).exists() for k in ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf"))
    assert (ablage / z["kurs_pdf"]).read_bytes().startswith(b"%PDF")
    assert "Offen / nachfragen" in (ablage / z["kurs_pfad"]).read_text(encoding="utf-8")
    assert "Offen" not in (ablage / z["kurs_pfad_lernend"]).read_text(encoding="utf-8")


def test_ablegen_pdf_fehler_laesst_keine_halben_dateien(kurs_fertig, ablage, auge_antwortet_503):
    with pytest.raises(kurs_pdf.PdfFehler):
        km.ablegen(UID)
    assert [p for p in ablage.rglob("*") if p.is_file()] == []
    z = _zeile()
    assert z["kurs_json"] is not None and z["kurs_status"] is None and z["kurs_versuche"] == 0
    assert z["kurs_pfad"] is None and z["kurs_pdf"] is None


def test_ablegen_nach_pdf_fehler_erneut_moeglich(kurs_fertig, ablage, monkeypatch):
    def aus(anfrage, timeout=None):
        raise OSError("weg")

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", aus)
    with pytest.raises(kurs_pdf.PdfFehler):
        km.ablegen(UID)
    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen",
                        lambda a, timeout=None: _Antwort(200, b"%PDF-1.7"))
    assert km.ablegen(UID) == "fertig"


def test_ablegen_entfernt_dateien_des_fruehen_ordners(kurs_fertig, ablage, auge_liefert_pdf):
    km.ablegen(UID)
    alt = _zeile()
    server._q("update termin_mitschriften set rubrik = 'Schulung' where uid = %s returning id",
              (UID,))
    km.ablegen(UID)
    neu = _zeile()
    assert neu["kurs_pfad"].startswith("Schulung/")
    for k in ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf"):
        assert not (ablage / alt[k]).exists() and (ablage / neu[k]).exists()


def test_ablegen_zweimal_gleicher_pfad_behaelt_dateien(kurs_fertig, ablage, auge_liefert_pdf):
    km.ablegen(UID)
    km.ablegen(UID)
    z = _zeile()
    assert all((ablage / z[k]).exists() for k in ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf"))
    assert len([p for p in ablage.rglob("*") if p.is_file()]) == 3


def test_entfernen_dateien(kurs_fertig, ablage, auge_liefert_pdf):
    km.ablegen(UID)
    z = _zeile()
    km.entfernen_dateien(UID)
    assert [p for p in ablage.rglob("*") if p.is_file()] == []
    n = _zeile()
    for k in ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf", "kurs_json", "kurs_stand",
              "kurs_status"):
        assert n[k] is None
    assert z["kurs_pfad"]


def test_keine_drafts(kurs_mitschrift, ki_liefert_gutes_json, auge_liefert_pdf):
    vorher = server._q("select count(*) as n from drafts")[0]["n"]
    km.erzeugen(UID, JETZT)
    km.ablegen(UID)
    assert server._q("select count(*) as n from drafts")[0]["n"] == vorher
