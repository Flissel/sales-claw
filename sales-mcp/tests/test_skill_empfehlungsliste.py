"""Drift-Test: der Skill empfehlungsliste (C4)."""
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2] / "config" / "workspace" / "skills"
         / "empfehlungsliste" / "SKILL.md")


def test_skill_pflichtschritte():
    t = SKILL.read_text(encoding="utf-8")
    kopf = t.split("---")[1]
    assert "Pole Position" in kopf and "Mitarbeitervorschl" in kopf
    for s in ("(?)", "alle gefragt", "empfehlungsliste_anlegen(", "Nichts raten",
              "nie von sich aus"):
        assert s in t, s
    assert t.index("alle gefragt") < t.index("empfehlungsliste_anlegen(")


def test_skill_einwilligung_nur_aus_antrag_und_keine_recherche():
    t = SKILL.read_text(encoding="utf-8")
    for s in ("NUR aus der ausdruecklichen Antwort", "nie aus dem Foto", "Haken/Vermerk",
              "Diktat", "unklar oder keine Antwort", "einwilligung=false", "keine Recherche",
              "web_search", "firma_anreichern", "b2b_leads", "marktanalyse",
              "ausdruecklichen Zuruf", "Bei Mitarbeitervorschlaegen gibt es keine Firmenzeilen",
              "nie blind erneut anlegen"):
        assert s in t, s
    assert t.index("NUR aus der ausdruecklichen Antwort") < t.index("empfehlungsliste_anlegen(")
