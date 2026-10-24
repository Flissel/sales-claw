"""Der Skill kanal-post traegt Ablauf und Grenzen fuer die fuenf weiteren Kanaele."""
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2]
         / "config" / "workspace" / "skills" / "kanal-post" / "SKILL.md")


def _text():
    return SKILL.read_text(encoding="utf-8")


def test_frontmatter():
    kopf = _text().split("---")[1]
    assert "name: kanal-post" in kopf and "description:" in kopf
    for kanal in ("Bluesky", "Mastodon", "Telegram", "Discord", "dev.to"):
        assert kanal in kopf
    assert '"openclaw": { "emoji":' in kopf


def test_nennt_linkedin_skill_fuer_linkedin():
    assert "linkedin-post" in _text()


def test_je_kanal_grenze_und_hashtag_regel():
    t = _text()
    for zahl in ("300", "500", "4096", "1024", "2000"):
        assert zahl in t
    zeilen = t.splitlines()
    for kanal in ("Bluesky", "Mastodon"):
        assert any(z.startswith(f"* {kanal}") and "mit Hashtags" in z for z in zeilen)
    for kanal in ("Telegram-Kanal", "Discord"):
        assert any(z.startswith(f"* {kanal}") and "ohne Hashtags" in z for z in zeilen)


def test_nur_verbundene_kanaele():
    t = _text()
    assert "noch nicht verbunden" in t and "/einstellungen/kanaele" in t


def test_vorschau_wortgleich_vor_anlegen():
    t = _text()
    assert "wortgleich" in t
    assert t.index("Vorschau") < t.index("kanal_post_entwurf(")
    assert "Ok" in t


def test_youtube_short_privat_mit_video_und_titel():
    t = _text()
    assert "YouTube" in t.split("---")[1]
    zeile = next(z for z in t.splitlines() if z.startswith("* YouTube"))
    assert "GENAU EIN" in zeile and "3 Minuten" in zeile and "100" in zeile
    assert "privat" in zeile
    assert "`youtube`" in t


def test_devto_als_entwurf():
    t = _text()
    assert "Entwurf bei dev.to" in t and "Titel" in t
