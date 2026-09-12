"""Vertragstests fuer `konferenz.raum` — der Link, der in einen Termin geht.

Drei Dinge sind hier festgenagelt:

1. **Ohne Konfiguration entsteht trotzdem ein Link.** Jitsi ist die
   Vorgabe, und der Raumname entsteht lokal — es geht in diesen Tests zu
   keinem Zeitpunkt eine Anfrage an einen echten Konferenzdienst.
2. **Der Jitsi-Raum ist nicht zu raten.** Ein kurzer oder sprechender Name
   waere ein fremder Zuhoerer im Kundengespraech.
3. **Es faellt IMMER auf Jitsi zurueck, nie auf gar nichts.** Fehlende
   Konfiguration, unbekannter Anbieter, Google antwortet nicht: in jedem
   Fall ein brauchbarer Link plus ein Hinweis, der sagt warum — und in dem
   kein Geheimnis steht.

Der Google-Weg wird gegen einen `http.server`-Thread auf einem vom
Betriebssystem vergebenen Port geprueft (Muster aus test_dispatch.py und
test_termin.py), nie gegen die echte API.
"""
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import konferenz  # noqa: E402


@pytest.fixture(autouse=True)
def _saubere_umgebung(monkeypatch):
    """Jeder Test startet unkonfiguriert — sonst faerbt die .env des
    Entwicklers auf das Ergebnis ab."""
    for name in ("KONFERENZ_ANBIETER", "GOOGLE_MEET_CLIENT_ID",
                 "GOOGLE_MEET_CLIENT_SECRET", "GOOGLE_MEET_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_ohne_konfiguration_entsteht_ein_jitsi_link():
    url, hinweis = konferenz.raum()
    assert url.startswith("https://meet.jit.si/")
    assert hinweis == ""


def test_jitsi_raumname_ist_lang_und_zufaellig():
    namen = {konferenz.raum()[0].rsplit("/", 1)[1] for _ in range(20)}
    assert len(namen) == 20, "Raumnamen wiederholen sich"
    for name in namen:
        assert len(name) >= 24, f"Raumname zu kurz: {name!r}"
        assert re.fullmatch(r"[A-Za-z0-9_-]+", name), name


def test_unbekannter_anbieter_faellt_auf_jitsi_zurueck_und_sagt_es():
    url, hinweis = konferenz.raum(anbieter="webex")
    assert url.startswith("https://meet.jit.si/")
    assert "webex" in hinweis and "Jitsi" in hinweis


def test_google_ohne_zugangsdaten_faellt_zurueck_und_nennt_die_variablen(monkeypatch):
    monkeypatch.setenv("KONFERENZ_ANBIETER", "google")
    url, hinweis = konferenz.raum()
    assert url.startswith("https://meet.jit.si/")
    assert "GOOGLE_MEET_CLIENT_ID" in hinweis


class _MeetStub(BaseHTTPRequestHandler):
    """Token-Endpunkt und Meet-API in einem, damit kein Netz noetig ist."""

    def do_POST(self):  # noqa: N802
        laenge = int(self.headers.get("Content-Length", "0"))
        rumpf = self.rfile.read(laenge).decode()
        if self.path.endswith("/token"):
            self.server.token_anfragen.append(rumpf)
            antwort = {"access_token": "zugriff-123", "expires_in": 3599}
        else:
            self.server.meet_kopfzeilen.append(self.headers.get("Authorization", ""))
            antwort = {"name": "spaces/abc",
                       "meetingUri": "https://meet.google.com/abc-mnop-xyz"}
        roh = json.dumps(antwort).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *_):
        pass


@pytest.fixture
def meet_stub(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _MeetStub)
    server.token_anfragen, server.meet_kopfzeilen = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(konferenz, "GOOGLE_TOKEN_URL", basis + "/token")
    monkeypatch.setattr(konferenz, "GOOGLE_MEET_URL", basis + "/v2/spaces")
    monkeypatch.setenv("KONFERENZ_ANBIETER", "google")
    monkeypatch.setenv("GOOGLE_MEET_CLIENT_ID", "kennung")
    monkeypatch.setenv("GOOGLE_MEET_CLIENT_SECRET", "geheim-secret")
    monkeypatch.setenv("GOOGLE_MEET_REFRESH_TOKEN", "geheim-refresh")
    yield server
    server.shutdown()


def test_google_liefert_den_raum_und_nutzt_das_zugriffstoken(meet_stub):
    url, hinweis = konferenz.raum()
    assert url == "https://meet.google.com/abc-mnop-xyz"
    assert hinweis == ""
    assert meet_stub.meet_kopfzeilen == ["Bearer zugriff-123"]
    assert "grant_type=refresh_token" in meet_stub.token_anfragen[0]


def test_google_ohne_meetinguri_faellt_zurueck(monkeypatch, meet_stub):
    monkeypatch.setattr(konferenz, "GOOGLE_MEET_URL",
                        konferenz.GOOGLE_TOKEN_URL)  # liefert kein meetingUri
    url, hinweis = konferenz.raum()
    assert url.startswith("https://meet.jit.si/")
    assert "Google Meet nicht erreichbar" in hinweis


def test_kein_geheimnis_im_hinweis(monkeypatch):
    """Der Hinweis geht in die Werkzeug-Antwort, in den Chat und ins Log."""
    monkeypatch.setenv("KONFERENZ_ANBIETER", "google")
    monkeypatch.setenv("GOOGLE_MEET_CLIENT_ID", "kennung")
    monkeypatch.setenv("GOOGLE_MEET_CLIENT_SECRET", "streng-geheim-secret")
    monkeypatch.setenv("GOOGLE_MEET_REFRESH_TOKEN", "streng-geheim-refresh")
    # Ein Ziel, das garantiert nicht antwortet: Port 0 ist nie erreichbar.
    monkeypatch.setattr(konferenz, "GOOGLE_TOKEN_URL", "http://127.0.0.1:1/token")
    url, hinweis = konferenz.raum()
    assert url.startswith("https://meet.jit.si/")
    assert "streng-geheim" not in hinweis
