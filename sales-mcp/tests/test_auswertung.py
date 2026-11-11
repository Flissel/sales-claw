"""Auswertung: Mitschrift -> JSON, Markdown, Vorschlaege, Kundenfassung (Task 10).

Ollama wird per Stub ersetzt, der feste JSON-Antworten liefert.
"""
import json
import logging
import pathlib
from datetime import date, timedelta

import pytest

import auswertung
import ollama

DATEN = pathlib.Path(__file__).parent / "daten" / "mitschrift_beispiel.json"


def _fixture() -> list[dict]:
    return json.loads(DATEN.read_text(encoding="utf-8"))


class Stub:
    """Liefert die Antworten der Reihe nach; Strings gehen roh durch, Dicts als JSON."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def __call__(self, system, nutzer, *, als_json=False):
        self.aufrufe.append({"system": system, "nutzer": nutzer, "als_json": als_json})
        a = self.antworten.pop(0)
        return a if isinstance(a, str) else json.dumps(a)


@pytest.fixture
def stub(monkeypatch):
    def setzen(*antworten):
        s = Stub(*antworten)
        monkeypatch.setattr(ollama, "chat", s)
        return s
    return setzen


VOLL = {
    "kurzfassung": "Kurz gesagt: Angebote kosten zu viel Zeit.",
    "painpoints": [{"zitat": "Das kostet uns jede Woche gut zehn Stunden.", "segment": 5}],
    "ziele": ["Nichts doppelt eintippen"],
    "fakten": ["12 Mitarbeitende", "Budget 5000 Euro"],
    "einwaende": ["EINWAND-GEHEIM Cloud"],
    "zusagen_felix": [{"text": "Angebot schicken", "datum": "2026-11-20"},
                      {"text": "Uebersicht Datenschutz", "datum": None}],
    "zusagen_kunde": ["Budget klaeren"],
    "naechste_schritte": [{"text": "Vorfuehrung", "datum": "2026-11-17"}],
    "beteiligte": ["BETEILIGTER-GEHEIM Herr Beispiel"],
    "offene_fragen": ["Zwei Arbeitsplaetze mehr?"],
    "stimmung": "STIMMUNG-GEHEIM offen und interessiert",
    "ergebnis": {"stattgefunden": True, "erfolg": True, "was": "Vorfuehrung vereinbart"},
}


def test_fixture_ist_ein_gespraech():
    seg = _fixture()
    assert 35 <= len(seg) <= 45
    assert len({s["sprecher"] for s in seg}) == 2
    assert all(s["beginn"] and s["text"] and s["sprache"] == "de" for s in seg)


def test_abschnitte_reihenfolge():
    assert [k for k, _ in auswertung.ABSCHNITTE] == [
        "kurzfassung", "painpoints", "ziele", "fakten", "einwaende", "zusagen_felix",
        "zusagen_kunde", "naechste_schritte", "beteiligte", "offene_fragen", "stimmung"]
    assert [t for _, t in auswertung.ABSCHNITTE][2] == "Ziele und Wünsche"


def test_markdown_alle_abschnitte_in_reihenfolge(stub):
    stub(VOLL)
    a = auswertung.auswerten(_fixture())
    md = auswertung.markdown(a)
    ueberschriften = [z for z in md.splitlines() if z.startswith("## ")]
    assert ueberschriften == ["## " + t for _, t in auswertung.ABSCHNITTE]
    assert "- „Das kostet uns jede Woche gut zehn Stunden.“ (01:15, Kundin)" in md
    assert "- Angebot schicken (bis 2026-11-20)" in md
    assert "|" not in md


def test_markdown_leere_abschnitte(stub):
    md = auswertung.markdown(auswertung._leer())
    assert md.count("- —") == len(auswertung.ABSCHNITTE)


def test_painpoint_zeit_aus_segment(stub):
    s = stub(VOLL)
    seg = _fixture()
    a = auswertung.auswerten(seg)
    assert a["painpoints"] == [{"zitat": "Das kostet uns jede Woche gut zehn Stunden.",
                                "zeit": "01:15", "sprecher": seg[5]["sprecher"]}]
    assert s.aufrufe[0]["als_json"] is True
    assert "[5] " in s.aufrufe[0]["nutzer"]
    assert "Probleme, Ärger, Kosten, Zeitverlust des Kunden, wörtlich zitiert" \
        in s.aufrufe[0]["system"]


def test_painpoint_modellzeit_wird_ignoriert(stub):
    stub({"painpoints": [{"zitat": "x", "segment": 5, "zeit": "99:99", "sprecher": "Fremd"}]})
    p = auswertung.auswerten(_fixture())["painpoints"][0]
    assert p["zeit"] == "01:15" and p["sprecher"] != "Fremd"


@pytest.mark.parametrize("index", [-1, 40, 999, "5", 5.0, None, True])
def test_painpoint_ungueltiger_index_faellt_weg(stub, index):
    stub({"painpoints": [{"zitat": "x", "segment": index},
                         {"zitat": "bleibt", "segment": 0}]})
    a = auswertung.auswerten(_fixture())
    assert [p["zitat"] for p in a["painpoints"]] == ["bleibt"]
    assert a["painpoints"][0]["zeit"] == "00:00"


def test_painpoint_segment_ohne_beginn_hat_leere_zeit(stub):
    seg = _fixture()
    seg.append({"sprecher": "Kundin", "beginn": "", "text": "Ohne Zeit", "sprache": "de"})
    stub({"painpoints": [{"zitat": "Ohne Zeit", "segment": 40}]})
    p = auswertung.auswerten(seg)["painpoints"][0]
    assert p["zeit"] == "" and p["sprecher"] == "Kundin"
    assert "(Kundin)" in auswertung.markdown({"painpoints": [p]})


def test_zeit_relativ_zum_ersten_segment_mit_beginn(stub):
    seg = [{"sprecher": "A", "beginn": "", "text": "ohne", "sprache": "de"},
           {"sprecher": "B", "beginn": "2026-11-12T09:00:00Z", "text": "eins", "sprache": "de"},
           {"sprecher": "B", "beginn": "2026-11-12T10:02:03Z", "text": "zwei", "sprache": "de"}]
    stub({"painpoints": [{"zitat": "zwei", "segment": 2}]})
    assert auswertung.auswerten(seg)["painpoints"][0]["zeit"] == "62:03"


def _stueck_antwort(kurz, painpoint_segment, punkt="Doppelt tippen"):
    return {"kurzfassung": kurz,
            "painpoints": [{"zitat": punkt, "segment": painpoint_segment}],
            "ziele": ["Zeit sparen"], "einwaende": ["Cloud?"]}


def test_stueckelung(stub):
    # 30 Segmente mit je ~1000 Zeichen = ~30 000 Zeichen -> drei Stuecke
    seg = [{"sprecher": "A", "beginn": f"2026-11-12T09:{i:02d}:00Z",
            "text": "wort " * 195, "sprache": "de"} for i in range(30)]
    s = stub(_stueck_antwort("Teil eins", 0), _stueck_antwort("Teil zwei", 12),
             _stueck_antwort("Teil drei", 24), {"kurzfassung": "Gesamt"})
    a = auswertung.auswerten(seg)
    assert len(s.aufrufe) == 4
    for aufruf in s.aufrufe[:3]:
        assert len(aufruf["nutzer"]) <= auswertung.AUSWERTUNG_STUECK_ZEICHEN
        # nie mitten im Segment geteilt: jede Zeile beginnt mit [n] und ist vollstaendig
        assert all(z.startswith("[") and z.endswith("wort") for z in aufruf["nutzer"].splitlines())
    assert "Teil eins" in s.aufrufe[3]["nutzer"] and "Teil drei" in s.aufrufe[3]["nutzer"]
    assert a["kurzfassung"] == "Gesamt"
    # Duplikate (Gross-/Kleinschreibung, Satzzeichen) nur einmal; Index global
    assert len(a["painpoints"]) == 1
    assert a["ziele"] == ["Zeit sparen"] and a["einwaende"] == ["Cloud?"]
    # globale Nummerierung: das zweite Stueck beginnt nicht bei 0
    assert not s.aufrufe[1]["nutzer"].startswith("[0]")


def test_stueckelung_dedupe_normalisiert_und_behaelt_datum(stub):
    seg = [{"sprecher": "A", "beginn": "", "text": "x" * 7000, "sprache": "de"}] * 2
    stub({"painpoints": [{"zitat": "Doppelt  tippen!", "segment": 0}],
          "zusagen_felix": [{"text": "Angebot senden", "datum": None}]},
         {"painpoints": [{"zitat": "doppelt tippen", "segment": 1}],
          "zusagen_felix": [{"text": "angebot senden.", "datum": "2026-12-01"}]})
    a = auswertung.auswerten(seg)
    assert len(a["painpoints"]) == 1
    assert a["zusagen_felix"] == [{"text": "Angebot senden", "datum": "2026-12-01"}]


def test_stueck_ohne_kurzfassung_braucht_keinen_zusammenfuehr_aufruf(stub):
    seg = [{"sprecher": "A", "beginn": "", "text": "x" * 7000, "sprache": "de"}] * 2
    s = stub({"kurzfassung": "Nur eine"}, {})
    assert auswertung.auswerten(seg)["kurzfassung"] == "Nur eine"
    assert len(s.aufrufe) == 2


def test_ein_stueck_ohne_zusammenfuehren(stub):
    s = stub(VOLL)
    auswertung.auswerten(_fixture())
    assert len(s.aufrufe) == 1


def test_leere_mitschrift_ruft_ollama_nicht(stub):
    s = stub()
    a = auswertung.auswerten([{"sprecher": "A", "beginn": "", "text": " ", "sprache": "de"}])
    assert s.aufrufe == [] and a == auswertung._leer()


def test_kaputtes_json_einmal_wiederholt(stub):
    s = stub("das ist kein json", VOLL)
    a = auswertung.auswerten(_fixture())
    assert len(s.aufrufe) == 2 and a["kurzfassung"] == VOLL["kurzfassung"]


def test_kaputtes_json_zweimal_wirft(stub):
    s = stub("nein", "[1, 2]")
    with pytest.raises(ollama.OllamaFehler):
        auswertung.auswerten(_fixture())
    assert len(s.aufrufe) == 2


def test_json_im_codezaun_wird_gelesen(stub):
    stub("```json\n" + json.dumps(VOLL) + "\n```")
    assert auswertung.auswerten(_fixture())["fakten"] == VOLL["fakten"]


def test_ollama_fehler_wird_nicht_wiederholt(monkeypatch):
    aufrufe = []

    def chat(*a, **k):
        aufrufe.append(1)
        raise ollama.OllamaFehler("aus")
    monkeypatch.setattr(ollama, "chat", chat)
    with pytest.raises(ollama.OllamaFehler):
        auswertung.auswerten(_fixture())
    assert len(aufrufe) == 1


def test_fehlende_schluessel_und_ergebnis_standard(stub):
    stub({})
    a = auswertung.auswerten(_fixture())
    assert a == auswertung._leer()
    assert a["ergebnis"] == {"stattgefunden": True, "erfolg": None, "was": ""}
    assert set(a) == {k for k, _ in auswertung.ABSCHNITTE} | {"ergebnis", "felder"}


def test_falsche_typen_werden_gerade_gezogen(stub):
    stub({"kurzfassung": ["liste"], "stimmung": 5,
          "ziele": "ein Ziel", "fakten": [1, None, {"a": 1}, "  Wort   Wort "],
          "einwaende": {"x": 1}, "painpoints": "text",
          "zusagen_felix": [{"text": "A", "datum": "31.12.2026"},
                            {"text": "B", "datum": "2026-02-30"},
                            {"text": "C", "datum": "2026-12-31"},
                            "D", {"datum": "2026-12-31"}, 7],
          "naechste_schritte": "nicht liste",
          "ergebnis": {"stattgefunden": "ja", "erfolg": "nein", "was": 3}})
    a = auswertung.auswerten(_fixture())
    assert a["kurzfassung"] == "" and a["stimmung"] == "5"
    assert a["ziele"] == ["ein Ziel"] and a["fakten"] == ["1", "Wort Wort"]
    assert a["einwaende"] == [] and a["painpoints"] == []
    assert a["zusagen_felix"] == [{"text": "A", "datum": None}, {"text": "B", "datum": None},
                                  {"text": "C", "datum": "2026-12-31"},
                                  {"text": "D", "datum": None}, {"text": "7", "datum": None}]
    assert a["naechste_schritte"] == [{"text": "nicht liste", "datum": None}]
    assert a["ergebnis"] == {"stattgefunden": True, "erfolg": None, "was": "3"}


def test_ergebnis_erfolg_false_bleibt(stub):
    stub({"ergebnis": {"stattgefunden": False, "erfolg": False, "was": "abgesagt"}})
    assert auswertung.auswerten(_fixture())["ergebnis"] == \
        {"stattgefunden": False, "erfolg": False, "was": "abgesagt"}


def test_vorschlaege(stub):
    stub(VOLL)
    a = auswertung.auswerten(_fixture())
    heute = date(2026, 11, 12)
    v = auswertung.vorschlaege(a, ["L1", "L2"], heute=heute)
    assert v == [
        {"art": "termin_ergebnis", "lead_id": "L1", "daten": a["ergebnis"]},
        {"art": "wiedervorlage", "lead_id": "L1",
         "daten": {"faellig_am": "2026-11-20", "notiz": "Angebot schicken"}},
        {"art": "wiedervorlage", "lead_id": "L1",
         "daten": {"faellig_am": "2026-11-15", "notiz": "Uebersicht Datenschutz"}},
    ]


def test_vorschlaege_felder_nur_wenn_vorhanden():
    a = auswertung._leer()
    assert [x["art"] for x in auswertung.vorschlaege(a, ["L1"])] == ["termin_ergebnis"]
    a["felder"] = {"title": "Leiterin Einkauf", "company": " ", "x": "y"}
    v = auswertung.vorschlaege(a, ["L1"])
    assert v[1] == {"art": "feld", "lead_id": "L1",
                    "daten": {"feld": "title", "wert": "Leiterin Einkauf"}}
    assert len(v) == 2


def test_vorschlaege_ohne_lead_und_heute_ueber_berliner_datum():
    assert auswertung.vorschlaege(auswertung._leer(), []) == []
    a = auswertung._leer()
    a["zusagen_felix"] = [{"text": "t", "datum": None}]
    f = auswertung.vorschlaege(a, ["L1"])[1]["daten"]["faellig_am"]
    assert date.fromisoformat(f) > date.today() - timedelta(days=1)


def test_kundenfassung_ohne_interna(stub):
    stub(VOLL)
    a = auswertung.auswerten(_fixture())
    text = auswertung.kundenfassung(a, "Guten Tag Frau Kunde")
    assert text.startswith("Guten Tag Frau Kunde,")
    for geheim in ("EINWAND-GEHEIM", "STIMMUNG-GEHEIM", "BETEILIGTER-GEHEIM",
                   "zehn Stunden", "Painpoint", "Einw", "Stimmung", "Entscheider"):
        assert geheim not in text
    for erwartet in (VOLL["kurzfassung"], "Nichts doppelt eintippen", "Angebot schicken",
                     "Budget klaeren", "Vorfuehrung", "Zwei Arbeitsplaetze mehr?",
                     "Viele Grüße"):
        assert erwartet in text


def test_kundenfassung_laesst_leere_abschnitte_weg():
    text = auswertung.kundenfassung(auswertung._leer(), "Hallo")
    assert "Zusagen" not in text and "Offene Fragen" not in text


def test_kein_log_mit_mitschrift(stub, caplog):
    geheim = "GEHEIMSATZ-Kundenname-Mueller"
    seg = _fixture()
    seg[3]["text"] = geheim
    stub("kein json " + geheim, {"painpoints": [{"zitat": geheim, "segment": 3}],
                                "kurzfassung": geheim})
    with caplog.at_level(logging.DEBUG):
        auswertung.auswerten(seg)
    assert geheim not in caplog.text

    stub("nein " + geheim, "nein " + geheim)
    with caplog.at_level(logging.DEBUG), pytest.raises(ollama.OllamaFehler) as fehler:
        auswertung.auswerten(seg)
    assert geheim not in caplog.text and geheim not in str(fehler.value)


# --- Final-Review I10: Feldvorschlaege aus der Modellantwort ---------------

def test_i10_prompt_kennt_felder():
    assert '"felder"' in auswertung.SYSTEM_PROMPT
    assert '"title"' in auswertung.SYSTEM_PROMPT and '"company"' in auswertung.SYSTEM_PROMPT


def test_i10_felder_aus_antwort_werden_feldvorschlaege(stub):
    stub({**VOLL, "felder": {"title": "  Leiterin   Einkauf ", "company": "Neue AG",
                             "phone": "0301234", "name": "x"}})
    a = auswertung.auswerten(_fixture())
    assert a["felder"] == {"title": "Leiterin Einkauf", "company": "Neue AG"}
    felder = [x["daten"] for x in auswertung.vorschlaege(a, ["L1"]) if x["art"] == "feld"]
    assert felder == [{"feld": "title", "wert": "Leiterin Einkauf"},
                      {"feld": "company", "wert": "Neue AG"}]


def test_i10_felder_nur_strings_und_gekappt(stub):
    stub({**VOLL, "felder": {"title": 5, "company": "C" * 500}})
    a = auswertung.auswerten(_fixture())
    assert a["felder"] == {"company": "C" * 200}
    stub({**VOLL, "felder": "Chefin"})
    assert auswertung.auswerten(_fixture())["felder"] == {}


def test_i10_ohne_felder_keine_feldvorschlaege(stub):
    stub(VOLL)
    a = auswertung.auswerten(_fixture())
    assert a["felder"] == {}
    assert not [x for x in auswertung.vorschlaege(a, ["L1"]) if x["art"] == "feld"]


def test_i10_felder_ueber_stuecke_vereint():
    a, b = auswertung._leer(), auswertung._leer()
    a["felder"] = {"title": "Alt", "company": "Firma A"}
    b["felder"] = {"title": "Neu"}
    assert auswertung._vereinen([a, b])["felder"] == {"title": "Neu", "company": "Firma A"}
