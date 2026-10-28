"""Kanal-Statusseite /einstellungen/kanaele (Beitraege auf weitere Kanaele,
Task 8, 24.10.2026) gegen sales_test.

Je Kanal der Registry eine Zeile: verbunden ja/nein, letzter Beitrag, Kadenz,
Grenze und bei "Nein" die Env-NAMEN samt Eintrage-Skript. Die Seite liest nie
die Umgebung - kein Zugangswert erscheint.
"""
import json
import os
import re

import pytest
from starlette.testclient import TestClient

# HART, nicht setdefault (wie test_ui.py).
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kanaele  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_kanaele  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.kanal_status cascade")


def _seite():
    r = CLIENT.get(ui_kanaele.PFAD, headers={"host": HOST_OK})
    return r.status_code, r.text[r.text.index("<main"):]


def _zeile(seite, kanal):
    """Die Tabellenzeile eines Kanals (data-kanal-Attribut)."""
    m = re.search(rf'<tr data-kanal="{kanal}">(.*?)</tr>', seite, re.S)
    assert m, kanal
    return m.group(1)


def _beleg(kanal, **payload):
    lead = server._q("insert into leads (name, source) values ('Sammel', 'system') "
                     "returning id")[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values (%s, 'versand', %s::jsonb) "
        "returning id",
        (lead, json.dumps({"draft_id": "1", "kanal": kanal, "weg": "kanal-dispatcher",
                           "empfaenger": "eigenes-profil", **payload})))


def test_alle_fuenf_nicht_verbunden_ohne_status():
    status, seite = _seite()
    assert status == 200
    for kanal, info in kanaele.KANAELE.items():
        z = _zeile(seite, kanal)
        assert info.anzeige in z and "Nein" in z
        assert f"kanal-zugang speichern {kanal}" in z
    assert "<code>BLUESKY_APP_PASSWORD</code>" in seite
    assert "kanal-zugang speichern bluesky" in seite


def test_kein_env_wert_auf_der_seite(monkeypatch):
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "geheim-xyz-123")
    monkeypatch.setenv("BLUESKY_HANDLE", "vibemind.bsky.social")
    _, seite = _seite()
    assert "geheim-xyz-123" not in seite
    assert "vibemind.bsky.social" not in seite


def test_verbunden_mit_letztem_beitrag():
    kanaele.status_schreiben(server._q, "bluesky", True, None, fehler_loeschen=True)
    _beleg("bluesky", beitrag="at://x", url="https://bsky.app/profile/x/post/abc",
           medienart=None)
    _, seite = _seite()
    z = _zeile(seite, "bluesky")
    assert "Ja" in z and "geprüft am" in z
    assert 'href="https://bsky.app/profile/x/post/abc"' in z and "ansehen" in z
    assert "kanal-zugang speichern" not in z


def test_ungewisser_beleg_ohne_link():
    kanaele.status_schreiben(server._q, "mastodon", True, None)
    _beleg("mastodon", beitrag=None, url=None, ungewiss=True, grund="503")
    _, seite = _seite()
    z = _zeile(seite, "mastodon")
    assert "ungewiss" in z and "href" not in z


def test_link_nur_bei_https():
    _beleg("discord", beitrag="1", url="javascript:alert(1)", medienart=None)
    _, seite = _seite()
    z = _zeile(seite, "discord")
    assert "href" not in z and "javascript" not in z


def test_letzter_fehler_escaped():
    kanaele.status_schreiben(server._q, "telegram_kanal", False, "<script>x</script>")
    _, seite = _seite()
    z = _zeile(seite, "telegram_kanal")
    assert "<script>x</script>" not in z and "&lt;script&gt;x&lt;/script&gt;" in z


def test_nur_freigeben_im_basis_laden(monkeypatch):
    assert ui._pfad_erlaubt("kalender", "/einstellungen/kanaele") is False
    assert ui._pfad_erlaubt("lesen", "/einstellungen/kanaele") is False
    assert server.SCHEMA == "sales_test"
    assert ui._pfad_erlaubt("freigeben", "/einstellungen/kanaele") is True
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/einstellungen/kanaele") is False


def test_im_menue_unter_monitoring():
    """Betreiber 27.10.2026: Kanaele gehoeren zum Monitoring, nicht zu Admin."""
    assert ("/einstellungen/kanaele", "Kanäle") in dict(ui._GRUPPEN)["Monitoring"]


def test_ohne_tabelle_kein_absturz(monkeypatch):
    monkeypatch.setattr(kanaele, "status_lesen", lambda q: {})
    status, seite = _seite()
    assert status == 200
    assert "Nein" in _zeile(seite, "devto")


def test_letzte_beitraege_je_kanal_der_juengste():
    _beleg("bluesky", url="https://bsky.app/alt")
    _beleg("bluesky", url="https://bsky.app/neu")
    _beleg("discord", url=None)
    belege = ui_kanaele.letzte_beitraege(server._q)
    assert set(belege) == {"bluesky", "discord"}
    assert belege["bluesky"]["payload"]["url"] == "https://bsky.app/neu"
