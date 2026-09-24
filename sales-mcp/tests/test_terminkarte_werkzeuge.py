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
        # test_nach_loeschantrag_keine_karte traegt die Nummer aus _lead() in die
        # TEST-Verbotsliste ein; ohne Leeren blockiert sie in spaeteren Dateien
        # (test_mail_dispatch, test_medien_meta) jede Erstansprache — wie test_dsgvo.
        conn.execute("truncate compliance_test.sperrliste")
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


def test_auskunft_nennt_die_terminkarte(monkeypatch, umgebung):
    _freigegeben(monkeypatch)
    lead = _lead()
    datei = json.loads(server.terminkarte_erstellen(lead, leer_lassen=True))["datei"]
    assert datei in json.loads(server.kontakt_auskunft(lead))["text"]


# ---------------------------------------------------------------------------
# Final-Review-Fixwelle (final-fix-findings.md, 24.09.2026)
# ---------------------------------------------------------------------------

def _vorgelegt(monkeypatch, gestalt, runde=1):
    monkeypatch.setattr(vorlagen_bruecke, "auftraege", lambda q: [
        {"id": "a1", "art": "terminkarte", "status": "vorgelegt", "runde": runde,
         "vorlage": "terminkarte", "fehler": "", "rueckmeldungen": []}])
    monkeypatch.setattr(vorlagen_bruecke, "vorlage", lambda q, n: {
        "name": "terminkarte", "status": "vorschlag", "fassung": 1, "gestalt": gestalt,
        "freigegebene_fassung": None, "freigegebene_gestalt": None})


def _mit_platz(**platz):
    feld = dict(GESTALT["felder"][0], platz=dict(GESTALT["felder"][0]["platz"], **platz))
    return {"seite": GESTALT["seite"], "felder": [feld] + GESTALT["felder"][1:]}


@pytest.mark.parametrize("gestalt", [_mit_platz(hoehe=4), _mit_platz(x="8")],
                         ids=["feld-4mm", "string-koordinate"])
def test_i1_nicht_setzbares_musterblatt_haelt_die_pruefung_nicht_an(monkeypatch, umgebung,
                                                                     gestalt):
    """I-1: ein Musterblatt, das `setzen` nicht zeichnen kann, wird zum
    beantwortbaren Eintrag (auftrag_id + fehler + frage), nicht zur Ausnahme."""
    _vorgelegt(monkeypatch, gestalt)
    antwort = json.loads(server.vorlagenauftraege_pruefen())
    eintrag = antwort["vorgelegt"][0]
    assert eintrag["auftrag_id"] == "a1" and eintrag["runde"] == 1
    assert eintrag["fehler"].startswith("Musterblatt nicht setzbar: ")
    assert "nein" in eintrag["frage"] and "Marketing" in eintrag["frage"]
    assert "muster" not in eintrag and "link" not in eintrag
    assert list(umgebung[0].iterdir()) == []


def test_i3_alte_gescheiterte_auftraege_werden_nicht_ewig_gemeldet(monkeypatch, umgebung):
    """I-3: gemeldet wird ein gescheiterter Auftrag nur, wenn er der juengste
    seiner Art ist (Liste kommt juengster zuerst)."""
    def auftrag(i, status):
        return {"id": i, "art": "terminkarte", "status": status, "runde": 1,
                "vorlage": "terminkarte", "fehler": "kaputt", "rueckmeldungen": []}
    monkeypatch.setattr(vorlagen_bruecke, "auftraege", lambda q: [
        auftrag("neu1", "in_arbeit"), auftrag("alt1", "gescheitert"),
        auftrag("alt2", "gescheitert")])
    uebrige = json.loads(server.vorlagenauftraege_pruefen())["uebrige"]
    assert [u["id"] for u in uebrige] == ["neu1"]

    monkeypatch.setattr(vorlagen_bruecke, "auftraege", lambda q: [
        auftrag("jung", "gescheitert"), auftrag("alt", "gescheitert")])
    uebrige = json.loads(server.vorlagenauftraege_pruefen())["uebrige"]
    assert [u["id"] for u in uebrige] == ["jung"]


def test_mc_umbenanntes_heic_wird_vor_der_datenbank_abgewiesen(monkeypatch, umgebung):
    """M-c: die Endung allein beweist nichts — HEIC-Bytes in einer .jpg."""
    (umgebung[1] / "karte.jpg").write_bytes(b"\x00\x00\x00\x18ftypheic" + b"0" * 64)
    aufgerufen = []
    monkeypatch.setattr(vorlagen_bruecke, "anlegen", lambda *a: aufgerufen.append(a))
    antwort = json.loads(server.vorlage_beauftragen(bild="karte.jpg"))
    assert "fehler" in antwort and "JPEG" in antwort["fehler"] and "PNG" in antwort["fehler"]
    assert aufgerufen == []


def test_mc_echtes_jpeg_und_png_gehen_durch(monkeypatch, umgebung):
    (umgebung[1] / "karte.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)
    (umgebung[1] / "karte.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    aufgerufen = []
    monkeypatch.setattr(vorlagen_bruecke, "anlegen",
                        lambda *a: aufgerufen.append(a) or {"ok": True, "id": "x"})
    assert json.loads(server.vorlage_beauftragen(bild="karte.jpg"))["auftrag_id"] == "x"
    assert json.loads(server.vorlage_beauftragen(bild="karte.png"))["auftrag_id"] == "x"
    assert [a[2] for a in aufgerufen] == ["image/jpeg", "image/png"]


def test_md_kontakt_ohne_termin_bekommt_keine_karte(monkeypatch, umgebung):
    """M-d: ohne Termin wird nachgefragt — auch leer_lassen macht keine Karte."""
    _freigegeben(monkeypatch)
    lead = str(server._q("insert into leads (name, phone, source) values ('Ohne Termin',"
                         " '+491709999999', 'test') returning id")[0]["id"])
    for leer in (False, True):
        antwort = json.loads(server.terminkarte_erstellen(lead, leer_lassen=leer))
        assert antwort["kein_termin"] is True
        assert "termin_bestaetigen" in antwort["hinweis"]
        assert "datei" not in antwort
    assert list(umgebung[0].iterdir()) == []
    assert server._q("select id from activities where lead_id = %s and type = "
                     "'terminkarte'", (lead,)) == []


def test_ohne_ui_basis_url_nennt_die_antwort_den_dateinamen(monkeypatch, umgebung):
    monkeypatch.setattr(server, "UI_BASIS_URL", "")
    _freigegeben(monkeypatch)
    antwort = json.loads(server.terminkarte_erstellen(_lead(), leer_lassen=True))
    assert antwort["link"] == ""
    assert antwort["hinweis"] == ("Kein Link moeglich (UI_BASIS_URL fehlt) - die Datei "
                                  f"liegt in den Medien unter {antwort['datei']}.")
    _vorgelegt(monkeypatch, GESTALT)
    eintrag = json.loads(server.vorlagenauftraege_pruefen())["vorgelegt"][0]
    assert eintrag["link"] == "" and eintrag["muster"] in eintrag["hinweis"]


def test_ma_karte_und_muster_sind_kein_kundenanhang(monkeypatch, umgebung):
    """M-a: Terminkarte und Musterblatt gehen nie an den Kunden (Spec §1)."""
    for name in ("terminkarte-x-2026-10-02.pdf", "muster-terminkarte-f1-r1.pdf"):
        (umgebung[0] / name).write_bytes(b"%PDF-1.4 karte")
    (umgebung[1] / "flyer.pdf").write_bytes(b"%PDF-1.4 flyer")
    namen = [d["name"] for d in json.loads(server.medien_liste())["dateien"]]
    assert namen == ["flyer.pdf"]
    lead = _lead()
    for name in ("terminkarte-x-2026-10-02.pdf", "muster-terminkarte-f1-r1.pdf"):
        antwort = json.loads(server.entwurf_erstellen(lead, "linkedin", "Hallo",
                                                      medien_datei=name))
        assert "fehler" in antwort and "nicht an Kunden" in antwort["fehler"]
    assert server._q("select id from drafts where lead_id = %s", (lead,)) == []
    basis, fehler = medien.pruefe_anhang("terminkarte-x-2026-10-02.pdf")
    assert basis is None and "nicht an Kunden" in fehler
    # Nur das erzeugte Musterblatt ist intern, nicht jede Datei mit muster-.
    assert not medien.intern("muster-vorlage-warm-sand.pdf")
    assert medien.intern("muster-terminkarte-f2-r3.pdf")
    # Die Oberflaeche liefert die Datei weiter aus: dieselbe Grundpruefung.
    assert medien.pruefe("terminkarte-x-2026-10-02.pdf") == ("terminkarte-x-2026-10-02.pdf",
                                                             None)
