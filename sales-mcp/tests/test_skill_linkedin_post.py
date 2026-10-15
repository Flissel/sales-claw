"""Der LinkedIn-Skill traegt die Pflichtschritte der Spec 2026-10-15 §4.1."""
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2]
         / "config" / "workspace" / "skills" / "linkedin-post" / "SKILL.md")


def _text():
    return SKILL.read_text(encoding="utf-8")


def test_beschreibung_triggert_bei_jedem_linkedin_post():
    kopf = _text().split("---")[1]
    assert "description:" in kopf and "Fragebogen" in kopf
    assert "LinkedIn" in kopf


def test_fragebogen_mit_vier_punkten_und_sprach_pflicht():
    t = _text()
    for punkt in ("1. Anlass & Kernbotschaft", "2. Sprache & Ton",
                  "3. Personen & Firmen", "4. Bild/Video, Links, Hashtags"):
        assert punkt in t
    assert "Ohne bestaetigte Sprache wird nicht geschrieben" in t


def test_vorschau_wortgleich_vor_dem_entwurf():
    t = _text()
    assert "wortgleich" in t
    assert t.index("Vorschau") < t.index("post_entwurf_erstellen(")


def test_markier_liste_und_selbst_regel():
    t = _text()
    assert "post_markierungen_setzen(" in t
    assert "web_search" in t
    assert "Der Betreiber selbst steht nie auf der Liste" in t


def test_bild_aus_dem_chat():
    assert "medien_aus_chat_uebernehmen(" in _text()


def test_handwerk_bleibt():
    t = _text()
    assert "linkedin_historie()" in t and "bausteine" in t
