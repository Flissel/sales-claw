"""Auswertung: Mitschrift -> JSON, Markdown, Vorschlaege, Kundenfassung (Task 10).

Ollama wird per Stub ersetzt, der feste JSON-Antworten liefert.
"""
import json
import logging
import pathlib
from datetime import date, datetime, timedelta, timezone

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
    "art": "kundentermin",
    "verlauf": [{"thema": "VERLAUF-GEHEIM Angebote", "inhalt": "Angebote dauern zu lange.",
                 "von": 0, "bis": 9},
                {"thema": "Budget", "inhalt": "Budget liegt bei 5000 Euro.", "von": 10, "bis": 20}],
    "entscheidungen": [{"text": "Vorfuehrung am 17.11.", "segment": 30}],
    "ideen": ["IDEE-GEHEIM Vorlage fuer Angebote"],
}


def test_fixture_ist_ein_gespraech():
    seg = _fixture()
    assert 35 <= len(seg) <= 45
    assert len({s["sprecher"] for s in seg}) == 2
    assert all(s["beginn"] and s["text"] and s["sprache"] == "de" for s in seg)


def test_abschnitte_reihenfolge():
    assert [k for k, _ in auswertung.ABSCHNITTE] == [
        "kurzfassung", "verlauf", "entscheidungen", "painpoints", "ziele", "ideen", "fakten",
        "einwaende", "zusagen_felix", "zusagen_kunde", "naechste_schritte", "beteiligte",
        "offene_fragen", "stimmung"]
    titel = dict(auswertung.ABSCHNITTE)
    assert titel["ziele"] == "Ziele und Wünsche"
    assert titel["verlauf"] == "Gesprächsverlauf"


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
                                "zeit": "01:15", "sprecher": seg[5]["sprecher"],
                                "bedeutung": ""}]
    assert s.aufrufe[0]["als_json"] is True
    assert "[5] " in s.aufrufe[0]["nutzer"]
    assert "Painpoints nur fuer echte Probleme, Kosten oder Frust" in s.aufrufe[0]["system"]


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


def test_stueckelung(stub, monkeypatch):
    monkeypatch.delenv("AUSWERTUNG_STUECK_ZEICHEN", raising=False)
    # 30 Segmente mit je ~1000 Zeichen = ~30 000 Zeichen -> drei Stuecke
    seg = [{"sprecher": "A", "beginn": f"2026-11-12T09:{i:02d}:00Z",
            "text": "wort " * 195, "sprache": "de"} for i in range(30)]
    s = stub(_stueck_antwort("Teil eins", 0), _stueck_antwort("Teil zwei", 12),
             _stueck_antwort("Teil drei", 24), {"kurzfassung": "Gesamt"})
    a = auswertung.auswerten(seg)
    assert len(s.aufrufe) == 4
    for aufruf in s.aufrufe[:3]:
        assert len(aufruf["nutzer"]) <= auswertung.AUSWERTUNG_STUECK_ZEICHEN == 12000
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
    assert a["zusagen_felix"] == [{"text": "Angebot senden", "datum": "2026-12-01",
                                   "segment": None}]


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
    assert a["art"] == "kundentermin"
    assert set(a) == {k for k, _ in auswertung.ABSCHNITTE} | {"ergebnis", "felder", "art"}


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
    ohne = {"segment": None}
    assert a["zusagen_felix"] == [{"text": "A", "datum": None, **ohne},
                                  {"text": "B", "datum": None, **ohne},
                                  {"text": "C", "datum": "2026-12-31", **ohne},
                                  {"text": "D", "datum": None, **ohne},
                                  {"text": "7", "datum": None, **ohne}]
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
                   "zehn Stunden", "Painpoint", "Einw", "Stimmung", "Entscheider",
                   "VERLAUF-GEHEIM", "IDEE-GEHEIM", "Verlauf", "Ideen", "Segment"):
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


# --- Tiefere Auswertung: Verlauf, Entscheidungen, Ideen, Gespraechsart ------

def test_prompt_kennt_neue_regeln():
    p = auswertung.SYSTEM_PROMPT
    for teil in ('"art"', '"kundentermin"', '"intern"', '"verlauf"', '"entscheidungen"',
                 '"ideen"', '"bedeutung"', "6 bis 12 Saetze", "Smalltalk",
                 "ausdruecklich", "Spracherkennung",
                 # Nachbesserung: Umlaute, technische Einrichtung, lueckenloser Verlauf
                 "echte Umlaute (ä, ö, ü) und ß", "Bildschirm teilen", "Einwahl",
                 "wer ist da", "jeder inhaltliche Abschnitt"):
        assert teil in p, teil
    assert "6 bis 12 Saetze" in auswertung.SYSTEM_ZUSAMMENFUEHREN


def test_neue_abschnitte_falsche_typen_werden_leer(stub):
    stub({"verlauf": "ein Text", "entscheidungen": {"x": 1}, "ideen": 5, "art": 7})
    a = auswertung.auswerten(_fixture())
    assert a["verlauf"] == [] and a["entscheidungen"] == [] and a["ideen"] == []
    assert a["art"] == "kundentermin"


def test_neue_abschnitte_eintraege_normalisiert(stub):
    stub({"verlauf": [{"thema": "  Budget  ", "inhalt": "Fuenf   tausend", "von": 2, "bis": 4},
                      {"thema": "ohne Bereich", "inhalt": "x", "von": "3", "bis": True},
                      {"thema": "", "inhalt": ""}, "Text", None,
                      {"thema": "zu gross", "von": 5, "bis": 999},
                      {"inhalt": "nur Inhalt", "von": -1, "bis": 6}],
          "entscheidungen": [{"text": "Pilot startet", "segment": 7},
                             {"text": "ohne Beleg", "segment": "7"}, "als Text",
                             {"segment": 3}, 4],
          "ideen": ["  Vorlage  bauen ", None, {"a": 1}, 3]})
    a = auswertung.auswerten(_fixture())
    assert a["verlauf"] == [
        {"thema": "Budget", "inhalt": "Fuenf tausend", "von": 2, "bis": 4},
        {"thema": "ohne Bereich", "inhalt": "x", "von": None, "bis": None},
        {"thema": "zu gross", "inhalt": "", "von": 5, "bis": None},
        {"thema": "", "inhalt": "nur Inhalt", "von": None, "bis": 6},
    ]
    assert a["entscheidungen"] == [{"text": "Pilot startet", "segment": 7},
                                   {"text": "ohne Beleg", "segment": None},
                                   {"text": "als Text", "segment": None},
                                   {"text": "4", "segment": None}]
    assert a["ideen"] == ["Vorlage bauen", "3"]


def test_verlauf_chronologisch_ohne_ueberlappung(stub):
    stub({"verlauf": [{"thema": "C", "von": 20, "bis": 30},
                      {"thema": "A", "von": 0, "bis": 12},
                      {"thema": "B", "von": 10, "bis": 19},
                      {"thema": "D", "von": 22, "bis": 25},
                      {"thema": "E", "von": 33, "bis": 31}]})
    v = auswertung.auswerten(_fixture())["verlauf"]
    assert [(x["thema"], x["von"], x["bis"]) for x in v] == [
        ("A", 0, 12), ("B", 13, 19), ("C", 20, 30), ("D", None, None), ("E", 31, 33)]


def test_painpoint_bedeutung_und_markdown(stub):
    stub({"painpoints": [{"zitat": "Das dauert ewig", "segment": 5,
                          "bedeutung": "  kostet   Zeit "}]})
    a = auswertung.auswerten(_fixture())
    assert a["painpoints"][0]["bedeutung"] == "kostet Zeit"
    assert "- „Das dauert ewig“ (01:15, Kundin) — kostet Zeit" in auswertung.markdown(a)


def test_zusagen_mit_segment_beleg(stub):
    stub({"zusagen_felix": [{"text": "Angebot", "datum": None, "segment": 12}],
          "zusagen_kunde": [{"text": "Zahlen liefern", "segment": 14}, "Budget klaeren",
                            {"text": "falscher Beleg", "segment": 999}]})
    a = auswertung.auswerten(_fixture())
    assert a["zusagen_felix"] == [{"text": "Angebot", "datum": None, "segment": 12}]
    assert a["zusagen_kunde"] == [{"text": "Zahlen liefern", "segment": 14},
                                  {"text": "Budget klaeren", "segment": None},
                                  {"text": "falscher Beleg", "segment": None}]
    md = auswertung.markdown(a)
    assert "- Angebot [Segment 12]" in md and "- Zahlen liefern [Segment 14]" in md
    assert "- Budget klaeren\n" in md


def test_art_intern_leert_verkaufsrubriken(stub):
    stub({**VOLL, "art": "intern", "ideen": ["Neues Modul"]})
    a = auswertung.auswerten(_fixture())
    assert a["art"] == "intern"
    assert a["einwaende"] == [] and a["zusagen_kunde"] == []
    assert a["painpoints"] == []     # intern: nie Painpoints, auch wenn das Modell welche liefert
    assert a["ideen"] == ["Neues Modul"]
    # Inhalt, Entscheidungen und Felix' Zusagen bleiben
    assert a["verlauf"] and a["entscheidungen"] and a["zusagen_felix"]


def test_art_kundentermin_behaelt_verkaufsrubriken(stub):
    stub(VOLL)
    a = auswertung.auswerten(_fixture())
    assert a["art"] == "kundentermin"
    assert a["einwaende"] == VOLL["einwaende"]
    assert [z["text"] for z in a["zusagen_kunde"]] == VOLL["zusagen_kunde"]


def test_stueck_zeichen_aus_umgebung(monkeypatch):
    monkeypatch.delenv("AUSWERTUNG_STUECK_ZEICHEN", raising=False)
    assert auswertung._stueck_zeichen() == 12000
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "80000")
    assert auswertung._stueck_zeichen() == 80000
    for falsch in ("", "abc", "0", "-5", "1.5"):
        monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", falsch)
        assert auswertung._stueck_zeichen() == 12000, falsch


def test_stueck_zeichen_wirkt_auf_stueckelung(stub, monkeypatch):
    seg = [{"sprecher": "A", "beginn": "", "text": "wort " * 195, "sprache": "de"}
           for _ in range(30)]
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "80000")
    s = stub({"kurzfassung": "Ganz"})
    assert auswertung.auswerten(seg)["kurzfassung"] == "Ganz"
    assert len(s.aufrufe) == 1
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "500")
    zeilen = auswertung._zeilen(seg)
    assert all(len(z) <= 499 for z in zeilen)
    assert len(auswertung._stuecke(zeilen)) == 30


def test_vereinen_haengt_verlauf_entscheidungen_ideen_an():
    a, b = auswertung._leer(), auswertung._leer()
    a["verlauf"] = [{"thema": "Eins", "inhalt": "", "von": 0, "bis": 10}]
    b["verlauf"] = [{"thema": "Zwei", "inhalt": "", "von": 8, "bis": 20}]
    a["entscheidungen"] = [{"text": "Pilot", "segment": 3}]
    b["entscheidungen"] = [{"text": "Pilot", "segment": 15}]
    a["ideen"], b["ideen"] = ["Vorlage"], ["Vorlage", "Bot"]
    v = auswertung._vereinen([a, b])
    assert [(x["thema"], x["von"], x["bis"]) for x in v["verlauf"]] == [
        ("Eins", 0, 10), ("Zwei", 11, 20)]
    assert v["entscheidungen"] == [{"text": "Pilot", "segment": 3},
                                   {"text": "Pilot", "segment": 15}]
    assert v["ideen"] == ["Vorlage", "Vorlage", "Bot"]


def test_vereinen_art_intern_nur_wenn_alle_stuecke_intern():
    a, b = auswertung._leer(), auswertung._leer()
    a["art"], b["art"] = "intern", "intern"
    b["painpoints"] = [{"zitat": "kaputt", "zeit": "", "sprecher": "A", "bedeutung": ""}]
    assert auswertung._vereinen([a, b])["art"] == "intern"
    assert auswertung._vereinen([a, b])["painpoints"] == []
    b["art"] = "kundentermin"
    b["einwaende"] = ["Preis"]
    v = auswertung._vereinen([a, b])
    assert v["art"] == "kundentermin" and v["einwaende"] == ["Preis"]


def test_markdown_mit_verlauf(stub):
    stub(VOLL)
    md = auswertung.markdown(auswertung.auswerten(_fixture()))
    ueberschriften = [z for z in md.splitlines() if z.startswith("## ")]
    assert ueberschriften[:3] == ["## Kurzfassung", "## Gesprächsverlauf", "## Entscheidungen"]
    assert "- **VERLAUF-GEHEIM Angebote** (Segment 0–9): Angebote dauern zu lange." in md
    assert "- **Budget** (Segment 10–20): Budget liegt bei 5000 Euro." in md
    assert "- Vorfuehrung am 17.11. [Segment 30]" in md
    assert "## Ideen und Feedback\n- IDEE-GEHEIM Vorlage fuer Angebote" in md


def test_markdown_verlauf_ohne_bereich_und_ohne_thema():
    a = auswertung._leer()
    a["verlauf"] = [{"thema": "Nur Thema", "inhalt": "", "von": None, "bis": None},
                    {"thema": "", "inhalt": "Nur Inhalt", "von": 3, "bis": None}]
    md = auswertung.markdown(a)
    assert "- **Nur Thema**\n" in md and "- Nur Inhalt (Segment 3)\n" in md


def test_kundenfassung_ohne_verlauf_und_ideen():
    a = auswertung._leer()
    a["kurzfassung"] = "Kurz."
    a["verlauf"] = [{"thema": "VERLAUF-GEHEIM", "inhalt": "x", "von": 0, "bis": 1}]
    a["ideen"] = ["IDEE-GEHEIM"]
    a["entscheidungen"] = [{"text": "Pilot startet im Januar", "segment": 4}]
    a["zusagen_kunde"] = [{"text": "Zahlen liefern", "segment": 9}]
    text = auswertung.kundenfassung(a, "Hallo")
    assert "VERLAUF-GEHEIM" not in text and "IDEE-GEHEIM" not in text
    assert "Segment" not in text and "[" not in text
    assert "Pilot startet im Januar" in text and "- Zahlen liefern" in text


# ---------- Bildzeilen (Bildauswertung live, Task 5) ----------

def _seg(i, beginn, text="Hallo", sprecher="A"):
    return {"sprecher": sprecher, "beginn": beginn, "text": text, "sprache": "de"}


def test_zeilen_ohne_bilder_unveraendert():
    seg = _fixture()
    assert auswertung._zeilen(seg) == auswertung._zeilen(seg, None) == auswertung._zeilen(seg, [])
    assert all(z.startswith("[") and not z.startswith("[Bild") for z in auswertung._zeilen(seg))


def test_bildzeile_vor_passendem_segment():
    from datetime import datetime, timezone
    seg = [_seg(0, "2099-01-10T10:00:00Z", "eins"), _seg(1, "2099-01-10T10:02:00Z", "zwei"),
           _seg(2, "2099-01-10T10:05:00Z", "drei")]
    bilder = [(datetime(2099, 1, 10, 10, 1, tzinfo=timezone.utc), "Folie mit Preisen"),
              (datetime(2099, 1, 10, 10, 9, tzinfo=timezone.utc), "Spaetes Bild")]
    z = auswertung._zeilen(seg, bilder)
    # 10:01 UTC = 11:01 Berlin (Winter), vor Segment 1
    assert z == ["[0] A: eins", "[Bild 11:01] Folie mit Preisen", "[1] A: zwei",
                 "[2] A: drei", "[Bild 11:09] Spaetes Bild"]


def test_bildzeilen_ohne_nummer():
    from datetime import datetime, timezone
    seg = [_seg(0, "2099-01-10T10:00:00Z", "eins"), _seg(1, "", "ohne Zeit"),
           _seg(2, "2099-01-10T10:05:00Z", "drei")]
    bilder = [(datetime(2099, 1, 10, 9, 0, tzinfo=timezone.utc), "Ganz frueh")]
    z = auswertung._zeilen(seg, bilder)
    assert z[0] == "[Bild 10:00] Ganz frueh"
    # Segmentnummern unveraendert, Segment ohne Beginn behaelt Platz
    assert [x for x in z if not x.startswith("[Bild")] == ["[0] A: eins", "[1] A: ohne Zeit",
                                                           "[2] A: drei"]


def test_auswerten_reicht_bilder_in_den_prompt(stub):
    from datetime import datetime, timezone
    s = stub(VOLL)
    assert "[Bild HH:MM]" in auswertung.SYSTEM_PROMPT
    auswertung.auswerten(_fixture(), bilder=[
        (datetime(2026, 11, 12, 9, 0, 8, tzinfo=timezone.utc), "Tabelle mit Zahlen")])
    assert "[Bild 10:00] Tabelle mit Zahlen" in s.aufrufe[0]["nutzer"]


# ---------- reine Bild-Stuecke falten ----------

def _hat_segmentzeile(stueck: str) -> bool:
    return any(auswertung._SEGMENTZEILE.match(z) for z in stueck.splitlines())


def test_stuecke_haengen_reines_bildstueck_ans_vorige(monkeypatch):
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "100")
    z = ["[0] A: " + "x" * 40, "[1] A: " + "y" * 40, "[Bild 10:58] " + "b" * 30]
    # ohne Falten: Grenze bricht nach der letzten Segmentzeile -> 2 Stuecke, das letzte nur Bild
    assert len(z[0]) + len(z[1]) + 2 <= 100 < len(z[0]) + len(z[1]) + len(z[2]) + 3
    stuecke = auswertung._stuecke(z)
    assert len(stuecke) == 2 - 1
    assert stuecke[-1].splitlines()[-1] == z[2]
    assert all(_hat_segmentzeile(s) for s in stuecke)


def test_stuecke_erstes_bildstueck_geht_ans_folgende(monkeypatch):
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "100")
    z = ["[Bild 10:00] " + "b" * 60, "[0] A: " + "x" * 60, "[1] A: " + "y" * 20]
    stuecke = auswertung._stuecke(z)
    assert all(_hat_segmentzeile(s) for s in stuecke)
    assert stuecke[0].splitlines()[0] == z[0]
    assert "\n".join(stuecke).splitlines() == z


def test_stuecke_ohne_segmentzeile_ist_leer():
    assert auswertung._stuecke(["[Bild 10:00] Folie"]) == []


def test_auswerten_ohne_segmente_fragt_nicht(stub):
    s = stub()
    t = datetime(2026, 11, 12, 10, 58, tzinfo=timezone.utc)
    assert auswertung.auswerten([], bilder=[(t, "Folie")]) == auswertung._leer()
    assert s.aufrufe == []


def test_auswerten_bildstueck_ueberschreibt_stimmung_nicht(stub, monkeypatch):
    monkeypatch.setenv("AUSWERTUNG_STUECK_ZEICHEN", "200")
    seg = [{"sprecher": "A", "beginn": f"2026-11-12T09:0{i}:00Z",
            "text": "wort " * 18, "sprache": "de"} for i in range(2)]
    t = datetime(2026, 11, 12, 10, 58, tzinfo=timezone.utc)
    # wuerde das Bild-Stueck gefragt, kaeme dessen "Keine Aussage moeglich" zuletzt und gewaenne
    s = stub({"stimmung": "offen und interessiert"},
             {"stimmung": "Keine Aussage möglich"})
    a = auswertung.auswerten(seg, bilder=[(t, "Folie")])
    assert a["stimmung"] == "offen und interessiert"
    assert len(s.aufrufe) == 1
    assert "[Bild 11:58] Folie" in s.aufrufe[0]["nutzer"]


# --- Beteiligte ohne Bots und Doppelte ---------------------------------------

def test_beteiligte_ohne_bots():
    liste = ["Felix - Berater", "Laura - teilt den Bildschirm", "VibeMind - Teilnehmer"]
    assert auswertung.beteiligte_bereinigen(liste, {"felix"}) == ["Felix - Berater"]


def test_beteiligte_sprechende_laura_bleibt():
    liste = ["Felix - Berater", "Laura - teilt den Bildschirm"]
    assert auswertung.beteiligte_bereinigen(liste, {"Laura"}) == [
        "Felix - Berater", "Laura - teilt den Bildschirm"]


def test_beteiligte_doppelte_zusammen():
    liste = ["Felix - Berater", "Diana - Kundin", "Felix Baumann - Betreiber",
             "Diana Marx - Kundin, Horizon Hues"]
    assert auswertung.beteiligte_bereinigen(liste, set()) == [
        "Felix Baumann - Berater", "Diana Marx - Kundin"]


def test_beteiligte_ohne_trenner_und_muell():
    assert auswertung.beteiligte_bereinigen(
        ["Anna", "Anna Schmidt – Chefin", "", None, 3, "Anna"], set()) == ["Anna Schmidt"]


def test_prompt_nennt_bot_regel():
    assert "keine Beteiligten" in auswertung.SYSTEM_PROMPT


def test_auswerten_bereinigt_beteiligte_ueber_stuecke(stub, monkeypatch):
    stub({"beteiligte": ["Felix - Berater", "VibeMind Mitschrift - Bot", "Felix Baumann - X"]})
    a = auswertung.auswerten(_fixture())
    assert a["beteiligte"] == ["Felix Baumann - Berater"]


def test_beteiligte_kette_dreifach():
    assert auswertung.beteiligte_bereinigen(["Felix", "Baumann", "Felix Baumann"], set()) == [
        "Felix Baumann"]


def test_beteiligte_mehrere_stuecke_bereinigt(stub, monkeypatch):
    monkeypatch.delenv("AUSWERTUNG_STUECK_ZEICHEN", raising=False)
    seg = [{"sprecher": "Felix", "beginn": f"2026-11-12T09:{i:02d}:00Z",
            "text": "wort " * 195, "sprache": "de"} for i in range(30)]
    s = stub(
        {"beteiligte": ["Felix - Berater", "Laura (Bildschirm) - Bot", "Diana - Kundin"]},
        {"beteiligte": ["VibeMind Mitschrift - Bot", "Felix Baumann - Betreiber"]},
        {"beteiligte": ["Diana Marx - Kundin, Horizon Hues", "vexa"]},
        {"kurzfassung": "Gesamt"})
    a = auswertung.auswerten(seg)
    assert len(s.aufrufe) > 1
    assert a["beteiligte"] == ["Felix Baumann - Berater", "Diana Marx - Kundin"]
