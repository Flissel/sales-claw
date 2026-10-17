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
