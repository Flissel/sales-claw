"""Terminkarten-Werkzeuge. Die Bruecke zu Marketing wird ersetzt; Ablage im
Medienordner und Aktivitaet am Kontakt laufen echt gegen sales_test."""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import medien  # noqa: E402
import server  # noqa: E402
import vorlagen_bruecke  # noqa: E402

GESTALT = {"seite": {"breite_mm": 148, "hoehe_mm": 105}, "felder": [
    {"name": "kunde", "beschriftung": "Kunde", "art": "text", "quelle": "kunde.name",
     "platz": {"x": 8, "y": 20, "breite": 60, "hoehe": 12}},
    {"name": "wann", "beschriftung": "Datum", "art": "datum", "quelle": "termin.datum",
     "platz": {"x": 80, "y": 20, "breite": 60, "hoehe": 12}},
    {"name": "vorinfo", "beschriftung": "Vorinfos", "art": "mehrzeilig", "quelle": "frei",
     "platz": {"x": 8, "y": 40, "breite": 132, "hoehe": 30}}]}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.leads cascade")
    erzeugt, mappe = tmp_path / "erzeugt", tmp_path / "media"
    erzeugt.mkdir(); mappe.mkdir()
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(mappe))
    monkeypatch.setattr(server, "UI_BASIS_URL", "https://laden.example:8445")
    monkeypatch.setattr(server, "MITGLIED_NAME", "Felix Baumann")
    yield erzeugt, mappe


def _lead(name="Jürgen Müßig"):
    lead = str(server._q("insert into leads (name, phone, source) values (%s, '+491701234567',"
                         " 'test') returning id", (name,))[0]["id"])
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s) "
              "returning id", (lead, json.dumps({"datum": "2026-10-02", "uhrzeit": "14:30",
                                                "uid": "u1"})))
    return lead


def _freigegeben(monkeypatch):
    monkeypatch.setattr(vorlagen_bruecke, "vorlage", lambda q, n: {
        "name": "terminkarte", "status": "freigegeben", "fassung": 1, "gestalt": GESTALT,
        "freigegebene_fassung": 1, "freigegebene_gestalt": GESTALT})


def test_ohne_freigegebene_vorlage_entsteht_keine_karte(monkeypatch):
    monkeypatch.setattr(vorlagen_bruecke, "vorlage", lambda q, n: None)
    # Lokale sales_test-DB kennt kein Schema `marketing` (Moduldocstring
    # oben) — auch auftraege() muss ersetzt werden, sonst scheitert
    # terminkarte_erstellen an der echten DB statt am erwarteten
    # fachlichen Fehler (dieselbe Stelle liest `stand` fuer die Antwort).
    monkeypatch.setattr(vorlagen_bruecke, "auftraege", lambda q: [])
    antwort = json.loads(server.terminkarte_erstellen(_lead()))
    assert "fehler" in antwort and "freigegeben" in antwort["fehler"]


def test_fehlende_felder_werden_erfragt_statt_erfunden(monkeypatch, umgebung):
    _freigegeben(monkeypatch)
    antwort = json.loads(server.terminkarte_erstellen(_lead()))
    assert antwort["fehlend"] == [{"feld": "vorinfo", "beschriftung": "Vorinfos"}]
    assert list(umgebung[0].iterdir()) == []


def test_leer_lassen_setzt_die_karte_und_legt_sie_beim_kunden_ab(monkeypatch, umgebung):
    _freigegeben(monkeypatch)
    lead = _lead()
    antwort = json.loads(server.terminkarte_erstellen(lead, leer_lassen=True))
    datei = umgebung[0] / antwort["datei"]
    assert datei.read_bytes().startswith(b"%PDF")
    assert antwort["link"] == f"https://laden.example:8445/medien/datei/{antwort['datei']}"
    akt = server._q("select payload from activities where lead_id = %s and type = "
                    "'terminkarte'", (lead,))
    assert akt[0]["payload"]["datei"] == antwort["datei"]
    assert akt[0]["payload"]["fassung"] == 1
    assert akt[0]["payload"]["leer"] == ["vorinfo"]


def test_zweite_karte_am_selben_tag_ueberschreibt_die_erste_nicht(monkeypatch, umgebung):
    _freigegeben(monkeypatch)
    lead = _lead()
    erste = json.loads(server.terminkarte_erstellen(lead, leer_lassen=True))["datei"]
    zweite = json.loads(server.terminkarte_erstellen(lead, leer_lassen=True))["datei"]
    assert erste != zweite and zweite.endswith("-2.pdf")


def test_nach_loeschantrag_keine_karte(monkeypatch):
    _freigegeben(monkeypatch)
    lead = _lead()
    server.loeschantrag_vermerken(lead, "WhatsApp-Nachricht", "bitte loeschen")
    assert "fehler" in json.loads(server.terminkarte_erstellen(lead, leer_lassen=True))


def test_bestellen_nimmt_nur_jpeg_und_png(monkeypatch, umgebung):
    (umgebung[1] / "karte.pdf").write_bytes(b"%PDF-1.4")
    antwort = json.loads(server.vorlage_beauftragen(bild="karte.pdf"))
    assert "fehler" in antwort and "JPEG" in antwort["fehler"]


def test_bestellen_weist_ein_zu_grosses_foto_vor_der_datenbank_ab(monkeypatch, umgebung):
    (umgebung[1] / "gross.jpg").write_bytes(b"\xff\xd8" + b"0" * (8 * 1024 * 1024 + 1))
    aufgerufen = []
    monkeypatch.setattr(vorlagen_bruecke, "anlegen", lambda *a: aufgerufen.append(a))
    antwort = json.loads(server.vorlage_beauftragen(bild="gross.jpg"))
    assert "fehler" in antwort and aufgerufen == []


def test_pruefen_setzt_fuer_vorgelegte_auftraege_ein_musterblatt(monkeypatch, umgebung):
    monkeypatch.setattr(vorlagen_bruecke, "auftraege", lambda q: [
        {"id": "a1", "art": "terminkarte", "status": "vorgelegt", "runde": 2,
         "vorlage": "terminkarte", "fehler": "", "rueckmeldungen": []}])
    monkeypatch.setattr(vorlagen_bruecke, "vorlage", lambda q, n: {
        "name": "terminkarte", "status": "vorschlag", "fassung": 1, "gestalt": GESTALT,
        "freigegebene_fassung": None, "freigegebene_gestalt": None})
    antwort = json.loads(server.vorlagenauftraege_pruefen())
    eintrag = antwort["vorgelegt"][0]
    assert (umgebung[0] / eintrag["muster"]).read_bytes().startswith(b"%PDF")
    assert eintrag["muster"] == "muster-terminkarte-f1-r2.pdf"
    assert "Passt" in eintrag["frage"]


def test_karte_mit_zu_kleinem_feld_meldet_fehler_statt_datei(monkeypatch, umgebung):
    """Ruling 11/13: `setzen` wirft `formular.PasstNicht`, wenn ein Wert
    selbst bei kleinster Schrift nicht passt — terminkarte_erstellen faengt
    das ab: fehler + feld, KEINE Datei, KEINE Aktivitaet."""
    winzig = {"seite": {"breite_mm": 148, "hoehe_mm": 105}, "felder": [
        {"name": "kunde", "beschriftung": "Kunde", "art": "text", "quelle": "kunde.name",
         "platz": {"x": 8, "y": 20, "breite": 60, "hoehe": 12}},
        {"name": "wann", "beschriftung": "Datum", "art": "datum", "quelle": "termin.datum",
         "platz": {"x": 80, "y": 20, "breite": 60, "hoehe": 12}},
        {"name": "vorinfo", "beschriftung": "Vorinfos", "art": "mehrzeilig", "quelle": "frei",
         "platz": {"x": 8, "y": 60, "breite": 5, "hoehe": 3}}]}
    monkeypatch.setattr(vorlagen_bruecke, "vorlage", lambda q, n: {
        "name": "terminkarte", "status": "freigegeben", "fassung": 1, "gestalt": winzig,
        "freigegebene_fassung": 1, "freigegebene_gestalt": winzig})
    lead = _lead()
    lang = "Das ist ein sehr langer Zusatztext, der niemals in dieses winzige Feld passt."
    antwort = json.loads(server.terminkarte_erstellen(lead, zusatz={"vorinfo": lang}))
    assert "fehler" in antwort and antwort["feld"] == "vorinfo"
    assert list(umgebung[0].iterdir()) == []
    akt = server._q("select payload from activities where lead_id = %s and type = "
                    "'terminkarte'", (lead,))
    assert akt == []
