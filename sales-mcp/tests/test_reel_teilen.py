"""Ziele und Fassungen fuer Reels auf Beitragskanaelen (reel_teilen), ohne Datenbank."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

import kanaele  # noqa: E402
import reel_teilen  # noqa: E402


def _q_alle_verbunden(sql, params=()):
    return [{"kanal": k, "verbunden": True, "geprueft_am": None, "letzter_fehler": None}
            for k in kanaele.KANAELE]


def test_bluesky_und_devto_nie_ziel(monkeypatch):
    monkeypatch.delenv("LINKEDIN_POST_LEAD_ID", raising=False)
    namen = [i.name for i in reel_teilen.ziele(_q_alle_verbunden)]
    assert "bluesky" not in namen and "devto" not in namen  # bluesky: video_max=0
    assert {"mastodon", "discord", "youtube"} <= set(namen)


def test_linkedin_nur_mit_sammelkontakt(monkeypatch):
    monkeypatch.delenv("LINKEDIN_POST_LEAD_ID", raising=False)
    assert "linkedin" not in [i.name for i in reel_teilen.ziele(_q_alle_verbunden)]
    monkeypatch.setenv("LINKEDIN_POST_LEAD_ID", "lead-1")
    assert "linkedin" in [i.name for i in reel_teilen.ziele(_q_alle_verbunden)]
    assert "linkedin" not in [i.name for i in reel_teilen.ziele(_q_alle_verbunden, mit_linkedin=False)]


def test_nur_filtert(monkeypatch):
    monkeypatch.delenv("LINKEDIN_POST_LEAD_ID", raising=False)
    assert [i.name for i in reel_teilen.ziele(_q_alle_verbunden, ["discord"])] == ["discord"]


def test_langer_text_faellt_auf_kurz_zurueck():
    info = kanaele.KANAELE["mastodon"]  # 500 Zeichen
    lang, kurz = "wort " * 200, "Kurzer Text."
    titel, text = reel_teilen.fassung(info, "Thema", {"text_lang": lang, "text_kurz": kurz})
    assert text == kurz and titel == ""
    # passt der lange Text, gewinnt er
    assert reel_teilen.fassung(info, "T", {"text_lang": "kurz genug", "text_kurz": "k"})[1] == "kurz genug"
    # ohne passenden kurzen: gekuerzt
    text = reel_teilen.fassung(info, "T", {"text_lang": lang})[1]
    assert len(text) <= 500 and text.endswith("…")


def test_link_und_youtube_titel():
    info = kanaele.KANAELE["youtube"]
    titel, text = reel_teilen.fassung(info, "T" * 300, {"text_lang": "Beschreibung"}, "https://x.de")
    assert len(titel) <= 100 and text == "Beschreibung\n\nhttps://x.de"


def test_ui_reels_nutzt_dieselben_ziele():
    import ui_reels
    assert ui_reels.kuerzen is reel_teilen.kuerzen
