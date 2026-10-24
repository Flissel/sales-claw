"""Vertragstests fuer kanal_post_entwurf (Beitraege auf weitere Kanaele,
24.10.2026) gegen sales_test.

Ein Kanal-Beitrag ist ein Entwurf ohne Empfaenger: channel = Kanalwert aus
der Registry (bluesky, mastodon, telegram_kanal, discord, devto),
recipient 'eigenes-profil', Lead = Sammelkontakt. Ohne verbundenen Kanal
(Zeile in kanal_status) entsteht kein Entwurf.
"""
import json
import os

import pytest

# HART, nicht setdefault (T5a): siehe test_linkedin_posts.py.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kanaele  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def sammelkontakt(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads, sales_test.kanal_status, "
            "sales_test.medien_meta cascade")
    sammel = server._q(
        "insert into leads (name, source) values "
        "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(sammel))
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    kanaele.status_schreiben(server._q, "bluesky", True, None)
    kanaele.status_schreiben(server._q, "devto", True, None)
    return str(sammel)


def _kp(*args, **kw):
    return json.loads(server.kanal_post_entwurf(*args, **kw))


def _anzahl():
    return server._q("select count(*) as n from drafts")[0]["n"]


def test_entwurf_pending_am_sammelkontakt(sammelkontakt):
    antwort = _kp("bluesky", "Herbst", "Hallo #KI")
    assert antwort["status"] == "pending"
    assert antwort["kanal"] == "bluesky"
    assert "sales-kanaele" in antwort["hinweis"]
    zeile = server._q(
        "select lead_id, channel, recipient, subject, thema, status "
        "from drafts where id = %s", (antwort["draft_id"],))[0]
    assert zeile["channel"] == "bluesky"
    assert zeile["recipient"] == "eigenes-profil"
    assert zeile["subject"] == "Post: Herbst"
    assert zeile["thema"] == "Herbst"
    assert zeile["status"] == "pending"
    assert str(zeile["lead_id"]) == sammelkontakt


def test_nicht_verbunden_klare_ablehnung():
    antwort = _kp("mastodon", "Herbst", "Hallo")
    assert "noch nicht verbunden" in antwort["fehler"]
    assert "kanal-zugang speichern mastodon" in antwort["fehler"]
    assert _anzahl() == 0


def test_unbekannter_kanal_nennt_liste():
    assert "post_entwurf_erstellen" in _kp("linkedin", "Herbst", "Hallo")["fehler"]
    assert "bluesky" in _kp("instagram", "Herbst", "Hallo")["fehler"]
    assert _anzahl() == 0


def test_leeres_thema_oder_text():
    assert "fehler" in _kp("bluesky", "  ", "Hallo")
    assert "fehler" in _kp("bluesky", "Herbst", "  ")
    assert _anzahl() == 0


def test_grenze_beim_anlegen():
    antwort = _kp("bluesky", "Herbst", "x" * 301)
    assert "300" in antwort["fehler"]
    assert _anzahl() == 0


def test_doppel_thema_je_kanal():
    erst = _kp("bluesky", "Herbst", "Eins")
    assert "draft_id" in erst
    zweit = _kp("bluesky", " herbst ", "Zwei")
    assert "trotzdem=True" in zweit["fehler"]
    assert "draft_id" in _kp("bluesky", "Herbst", "Drei", trotzdem=True)
    # Anderer Kanal: frei.
    assert "draft_id" in _kp("devto", "Herbst", "# Text", titel="Unser Herbst")
    # Abgelehnte zaehlen nicht.
    server._q("update drafts set status = 'rejected' where channel = 'bluesky' "
              "returning id")
    assert "draft_id" in _kp("bluesky", "Herbst", "Vier")


def test_devto_titel_ist_betreff():
    antwort = _kp("devto", "Herbst", "# Text", titel="Unser Herbst")
    assert "Entwurf bei dev.to" in antwort["hinweis"]
    zeile = server._q("select subject, thema from drafts where id = %s",
                      (antwort["draft_id"],))[0]
    assert zeile["subject"] == "Unser Herbst"
    assert zeile["thema"] == "Herbst"
    ohne = _kp("devto", "Winter", "# Text")
    assert "Titel" in ohne["fehler"]
    assert _anzahl() == 1


def test_youtube_titel_ist_betreff_und_video_pflicht(tmp_path):
    """YouTube (Nachtrag 25.10.2026): Titel Pflicht wie dev.to, dazu genau
    ein Video; ohne Video entsteht kein Entwurf."""
    kanaele.status_schreiben(server._q, "youtube", True, None)
    (tmp_path / "vid-1.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"0" * 20)
    (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"0" * 10)
    antwort = _kp("youtube", "Herbst", "Beschreibung #KI", titel="Unser Short",
                  medien_dateien="vid-1.mp4")
    assert "YouTube" in antwort["hinweis"]
    zeile = server._q("select subject, media_ref, thema from drafts where id = %s",
                      (antwort["draft_id"],))[0]
    assert zeile["subject"] == "Unser Short"
    assert zeile["media_ref"] == "vid-1.mp4"
    assert "Video ist Pflicht" in _kp("youtube", "Winter", "B", titel="T")["fehler"]
    assert "Titel" in _kp("youtube", "Winter", "B", medien_dateien="vid-1.mp4")["fehler"]
    assert "fehler" in _kp("youtube", "Winter", "B", titel="T", medien_dateien="a.png")
    assert _anzahl() == 1


def test_medien_werden_geprueft(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"0" * 10)
    (tmp_path / "b.jpg").write_bytes(b"\xff\xd8" + b"0" * 10)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")
    antwort = _kp("bluesky", "Herbst", "Hallo", medien_dateien="a.png, b.jpg")
    assert antwort["medien_dateien"] == "a.png,b.jpg"
    zeile = server._q("select media_ref from drafts where id = %s",
                      (antwort["draft_id"],))[0]
    assert zeile["media_ref"] == "a.png,b.jpg"
    assert "fehler" in _kp("bluesky", "PDF", "Hallo", medien_dateien="doc.pdf")
    assert "fehler" in _kp("bluesky", "Weg", "Hallo", medien_dateien="../x.png")
    # dev.to: keine Medien.
    assert "fehler" in _kp("devto", "Bild", "# T", titel="T", medien_dateien="a.png")


def test_gesperrte_datei_abgelehnt(tmp_path):
    (tmp_path / "geheim.png").write_bytes(b"\x89PNG" + b"0" * 10)
    server.medien_meta_setzen("geheim.png", bot_darf_senden=False)
    antwort = _kp("bluesky", "Herbst", "Hallo", medien_dateien="geheim.png")
    assert "fuer den Bot gesperrt" in antwort["fehler"]
    assert _anzahl() == 0


def test_ohne_kanal_status_tabelle_nicht_verbunden(monkeypatch):
    monkeypatch.setattr(kanaele, "status_lesen", lambda q: {})
    antwort = _kp("bluesky", "Herbst", "Hallo")
    assert "noch nicht verbunden" in antwort["fehler"]
    assert _anzahl() == 0


def test_ohne_sammelkontakt_klare_ansage(monkeypatch):
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    antwort = _kp("bluesky", "Herbst", "Hallo")
    assert "LINKEDIN_POST_LEAD_ID" in antwort["fehler"]
    assert _anzahl() == 0


def test_entwurf_erstellen_verweist_auf_kanal_post(sammelkontakt):
    antwort = json.loads(server.entwurf_erstellen(sammelkontakt, "bluesky", "x"))
    assert "kanal_post_entwurf" in antwort["fehler"]
    # Unbekannte Werte behalten den alten Text.
    antwort = json.loads(server.entwurf_erstellen(sammelkontakt, "fax", "x"))
    assert "Erlaubt: whatsapp, linkedin, email, telegram" in antwort["fehler"]


def test_bearbeiten_haelt_kanalgrenze(tmp_path):
    draft_id = _kp("bluesky", "Herbst", "x" * 280)["draft_id"]
    antwort = json.loads(server.entwurf_bearbeiten(draft_id, "x" * 340))
    assert "300" in antwort["fehler"]
    assert server._q("select body from drafts where id = %s",
                     (draft_id,))[0]["body"] == "x" * 280
    # Innerhalb der Grenze geht es.
    assert "fehler" not in json.loads(server.entwurf_bearbeiten(draft_id, "y" * 300))

    kanaele.status_schreiben(server._q, "telegram_kanal", True, None)
    (tmp_path / "bild.png").write_bytes(b"\x89PNG" + b"0" * 10)
    tg = _kp("telegram_kanal", "Herbst", "kurz", medien_dateien="bild.png")["draft_id"]
    antwort = json.loads(server.entwurf_bearbeiten(tg, "z" * 1500))
    assert "1024" in antwort["fehler"]
    assert server._q("select body from drafts where id = %s",
                     (tg,))[0]["body"] == "kurz"
    # Bild weg -> 4096 gilt, 1500 passt.
    assert "fehler" not in json.loads(
        server.entwurf_bearbeiten(tg, "z" * 1500, medien_datei="-"))


def test_bearbeiten_devto_titel_aus_betreff():
    draft_id = _kp("devto", "Herbst", "# Text", titel="Unser Herbst")["draft_id"]
    antwort = json.loads(server.entwurf_bearbeiten(draft_id, "# Neu",
                                                   betreff="t" * 129))
    assert "128" in antwort["fehler"]
    assert "fehler" not in json.loads(server.entwurf_bearbeiten(draft_id, "# Neu"))


def test_signatur_und_registrierung():
    import inspect
    parameter = inspect.signature(server.kanal_post_entwurf).parameters
    assert list(parameter) == ["kanal", "thema", "text", "titel",
                               "medien_dateien", "trotzdem"]
    namen = [fn.__name__ for fn in server.WERKZEUGE]
    assert namen.index("kanal_post_entwurf") == namen.index("post_entwurf_erstellen") + 1
