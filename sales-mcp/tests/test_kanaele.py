"""Kanal-Registry (Spec 2026-10-24-kanaele-posten): Grenzen, Zugaenge,
Entwurfspruefung. Rein, ohne Datenbank."""
from kanaele import KANAELE, pruefe_entwurf, zugang_lesen, zugang_pruefen

MIB = 1024 * 1024


def test_registry_reihenfolge_und_werte():
    assert list(KANAELE) == ["bluesky", "mastodon", "telegram_kanal", "discord", "devto"]
    erwartet = {
        "bluesky": (300, 3, ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")),
        "mastodon": (500, 3, ("MASTODON_INSTANCE", "MASTODON_TOKEN")),
        "telegram_kanal": (4096, 3, ("TELEGRAM_KANAL_ID", "TELEGRAM_KANAL_BOT_TOKEN")),
        "discord": (2000, 3, ("DISCORD_ANKUENDIGUNG_WEBHOOK",)),
        "devto": (100_000, 1, ("DEVTO_API_KEY",)),
    }
    for name, (max_zeichen, kadenz, env) in erwartet.items():
        info = KANAELE[name]
        assert info.name == name
        assert info.max_zeichen == max_zeichen
        assert info.kadenz_pro_tag == kadenz
        assert info.env_namen == env
    assert [i.anzeige for i in KANAELE.values()] == [
        "Bluesky", "Mastodon", "Telegram-Kanal", "Discord", "dev.to"]
    assert KANAELE["devto"].titel_pflicht is True
    assert KANAELE["devto"].titel_max == 128
    assert KANAELE["telegram_kanal"].max_zeichen_mit_medien == 1024
    assert [i.medien_max for i in KANAELE.values()] == [4, 4, 1, 1, 0]
    assert [i.hashtags for i in KANAELE.values()] == [True, True, False, False, False]


def test_geheim_namen_sind_teilmenge():
    for info in KANAELE.values():
        assert set(info.geheim_namen) <= set(info.env_namen)
    assert KANAELE["discord"].geheim_namen == ("DISCORD_ANKUENDIGUNG_WEBHOOK",)
    assert KANAELE["bluesky"].geheim_namen == ("BLUESKY_APP_PASSWORD",)


def test_zugang_crlf_wird_entfernt():
    zugang = zugang_lesen(KANAELE["mastodon"], {"MASTODON_INSTANCE": "mastodon.social\r",
                                                "MASTODON_TOKEN": " abc123\r\n"})
    assert zugang == {"MASTODON_INSTANCE": "mastodon.social", "MASTODON_TOKEN": "abc123"}
    assert zugang_pruefen(KANAELE["mastodon"], zugang) is None


def test_zugang_fehlt():
    info = KANAELE["bluesky"]
    grund = zugang_pruefen(info, zugang_lesen(info, {}))
    assert grund is not None and "BLUESKY_HANDLE fehlt" in grund


def test_zugang_gueltig_je_kanal():
    assert zugang_pruefen(KANAELE["bluesky"], {"BLUESKY_HANDLE": "@vibemind.bsky.social",
                                               "BLUESKY_APP_PASSWORD": "x"}) is None
    assert zugang_pruefen(KANAELE["telegram_kanal"], {"TELEGRAM_KANAL_ID": "-1001234567890",
                                                      "TELEGRAM_KANAL_BOT_TOKEN": "x"}) is None
    assert zugang_pruefen(KANAELE["telegram_kanal"], {"TELEGRAM_KANAL_ID": "@vibemind_news",
                                                      "TELEGRAM_KANAL_BOT_TOKEN": "x"}) is None
    assert zugang_pruefen(KANAELE["discord"], {
        "DISCORD_ANKUENDIGUNG_WEBHOOK": "https://discord.com/api/webhooks/123/ab_C-d"}) is None
    assert zugang_pruefen(KANAELE["mastodon"], {"MASTODON_INSTANCE": "https://Mastodon.Social/",
                                                "MASTODON_TOKEN": "x"}) is None
    assert zugang_pruefen(KANAELE["devto"], {"DEVTO_API_KEY": "x"}) is None


def test_zugang_falsche_form_nennt_nur_namen():
    grund = zugang_pruefen(KANAELE["mastodon"], {"MASTODON_INSTANCE": "http://geheim-instanz.example",
                                                 "MASTODON_TOKEN": "t"})
    assert grund and "MASTODON_INSTANCE" in grund and "geheim-instanz" not in grund
    grund = zugang_pruefen(KANAELE["telegram_kanal"], {"TELEGRAM_KANAL_ID": "12345",
                                                       "TELEGRAM_KANAL_BOT_TOKEN": "t"})
    assert grund and "TELEGRAM_KANAL_ID" in grund and "12345" not in grund
    grund = zugang_pruefen(KANAELE["discord"], {
        "DISCORD_ANKUENDIGUNG_WEBHOOK": "https://boese.example/api/webhooks/1/geheimpfad"})
    assert grund and "DISCORD_ANKUENDIGUNG_WEBHOOK" in grund
    assert "boese" not in grund and "geheimpfad" not in grund
    grund = zugang_pruefen(KANAELE["bluesky"], {"BLUESKY_HANDLE": "ohnepunkt",
                                                "BLUESKY_APP_PASSWORD": "p"})
    assert grund and "BLUESKY_HANDLE" in grund and "ohnepunkt" not in grund


def test_instanz_normalisieren():
    from kanaele import instanz_normalisieren
    assert instanz_normalisieren("mastodon.social") == "https://mastodon.social"
    assert instanz_normalisieren(" https://Mastodon.Social/ ") == "https://mastodon.social"


def test_pruefe_entwurf_grenzen():
    bs, ma, tg, dc, dv = (KANAELE[k] for k in KANAELE)
    bild = ("a.png", "bild", 1000)
    video = ("v.mp4", "video", 1000)
    grund = pruefe_entwurf(bs, "x" * 301, "", [])
    assert grund and "300" in grund
    assert pruefe_entwurf(bs, "x" * 300, "", []) is None
    grund = pruefe_entwurf(tg, "x" * 1025, "", [bild])
    assert grund and "1024" in grund
    assert pruefe_entwurf(tg, "x" * 1025, "", []) is None
    assert pruefe_entwurf(bs, "hallo", "", [video])
    assert pruefe_entwurf(ma, "hallo", "", [bild] * 5)
    assert pruefe_entwurf(ma, "hallo", "", [bild] * 4) is None
    assert pruefe_entwurf(ma, "hallo", "", [bild, video])
    assert pruefe_entwurf(ma, "hallo", "", [video]) is None
    assert pruefe_entwurf(dc, "hallo", "", [bild, bild])
    assert pruefe_entwurf(dc, "hallo", "", [bild]) is None
    assert pruefe_entwurf(bs, "hallo", "", [("a.png", "bild", 1_000_001)])
    assert pruefe_entwurf(bs, "hallo", "", [("a.png", "bild", 1_000_000)]) is None
    assert pruefe_entwurf(dc, "hallo", "", [("v.mp4", "video", 10 * MIB + 1)])
    assert pruefe_entwurf(dv, "artikel", "", [])
    assert pruefe_entwurf(dv, "artikel", "x" * 129, [])
    assert pruefe_entwurf(dv, "artikel", "x" * 128, []) is None
    assert pruefe_entwurf(dv, "artikel", "Titel", [bild])
    grund = pruefe_entwurf(bs, "hallo", "Titel", [])
    assert grund and "titel gibt es nur bei dev.to" in grund
    assert pruefe_entwurf(bs, "", "", []) is not None
