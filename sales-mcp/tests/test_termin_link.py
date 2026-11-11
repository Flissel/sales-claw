"""Link-Erkennung je Plattform (Meeting-Mittelpunkt, Task 2)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from termin_link import erkennen  # noqa: E402


@pytest.fixture(autouse=True)
def _saubere_umgebung(monkeypatch):
    for name in ("JITSI_BASIS", "JITSI_HOSTS"):
        monkeypatch.delenv(name, raising=False)


def test_meet():
    assert erkennen("Ort: https://meet.google.com/abc-defg-hij")["plattform"] == "google_meet"


def test_teams():
    r = erkennen("https://teams.microsoft.com/l/meetup-join/19%3ameeting_X%40thread.v2/0")
    assert r["plattform"] == "teams"
    assert r["link"].endswith("%40thread.v2/0")


def test_teams_live():
    assert erkennen("https://teams.live.com/meet/9312345")["plattform"] == "teams"


def test_zoom_subdomain():
    r = erkennen("https://us02web.zoom.us/j/81234567890?pwd=abc")
    assert (r["plattform"], r["passcode"]) == ("zoom", "abc")


def test_jitsi_ffmuc():
    assert erkennen("https://meet.ffmuc.net/Raum1")["plattform"] == "jitsi"


def test_jitsi_aus_liste(monkeypatch):
    monkeypatch.setenv("JITSI_HOSTS", "video.firma.de")
    assert erkennen("https://video.firma.de/x")["plattform"] == "jitsi"


def test_jitsi_basis_zaehlt_als_jitsi(monkeypatch):
    monkeypatch.setenv("JITSI_BASIS", "https://jitsi.example.org")
    assert erkennen("https://jitsi.example.org/x")["plattform"] == "jitsi"


def test_sonstiger_link_nur_wenn_kein_bekannter():
    assert erkennen("https://example.com/x") is None


def test_webex_sonstige():
    assert erkennen("https://firma.webex.com/meet/abc")["plattform"] == "sonstige"


def test_kein_teilstring_host():
    assert erkennen("https://evilzoom.us/j/1") is None
    assert erkennen("https://zoom.us.evil.com/j/1") is None


def test_satzzeichen_am_ende():
    assert erkennen("Link <https://meet.google.com/abc-defg-hij>.")["link"] == "https://meet.google.com/abc-defg-hij"
    assert erkennen("(https://zoom.us/j/1234567890),")["link"] == "https://zoom.us/j/1234567890"


def test_passcode_aus_text():
    r = erkennen("https://teams.microsoft.com/l/meetup-join/x", "Kenncode: 7Hx9")
    assert r["passcode"] == "7Hx9"


def test_einwahl():
    r = erkennen("https://meet.google.com/abc-defg-hij", "Telefon: +49 30 1234567 PIN: 123 456#")
    assert r["einwahl"].startswith("+49 30 1234567")


def test_einwahl_leer():
    assert erkennen("https://meet.google.com/abc-defg-hij")["einwahl"] == ""


def test_vorrang_reihenfolge():
    assert "zoom" == erkennen("https://zoom.us/j/1234567890", "https://meet.google.com/abc-defg-hij")["plattform"]


def test_kein_link():
    assert erkennen("", None, "Büro 3. Stock") is None


def test_kein_log_von_passcode(caplog):
    with caplog.at_level("DEBUG"):
        erkennen("https://us02web.zoom.us/j/81234567890?pwd=geheim123")
    assert "geheim123" not in caplog.text
