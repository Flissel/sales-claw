"""Vertragstests des Rowboat-Lesezugriffs — ohne echte Wissensbasis.

ZWEI RIEGEL GEGEN EINEN ECHTEN AUFRUF. Die Suite kann mit `--env-file .env`
laufen und haette dann eine gueltige ROWBOAT_URL in der Umgebung:

1. Die autouse-Fixture setzt `rowboat.BASIS` auf eine unerreichbare Adresse
   und prueft anschliessend, dass dort auch wirklich die Attrappe steht.
2. Jeder Test, der eine Antwort erwartet, biegt `urllib.request.urlopen`
   ausdruecklich um. Vergisst ein kuenftiger Umbau das, scheitert der Test
   an einem Verbindungsfehler — er weicht nicht still zur echten Instanz aus.

DER WICHTIGSTE TEST DIESER DATEI ist `test_keine_eingebauten_zugangsdaten`.
Die Vorlage aus dem Marketing-Space (`spaces/marketing/tools/rowboat_client.py`)
traegt Vorgabewerte fuer Adresse, Projekt UND Bearer-Token im Code — und ihre
Projekt-Vorgabe weicht von der ab, die in der VibeMind-`.env` steht. Wer sie
ungeprueft uebernaehme, redete bei fehlender Umgebung still mit einem anderen
Projekt, statt sich zu verweigern. Dieses Modul hat deshalb KEINE Vorgaben:
fehlt die Konfiguration, sagt es das.
"""
import json
import os
import urllib.error

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import rowboat  # noqa: E402


UNERREICHBAR = "http://127.0.0.1:1"


@pytest.fixture(autouse=True)
def riegel(monkeypatch):
    """Riegel 1: die Adresse zeigt ins Leere, bevor irgendein Test laeuft."""
    monkeypatch.setattr(rowboat, "BASIS", UNERREICHBAR)
    monkeypatch.setattr(rowboat, "PROJEKT", "test-projekt")
    monkeypatch.setattr(rowboat, "SCHLUESSEL", "test-schluessel")
    assert rowboat.BASIS == UNERREICHBAR, "Riegel steht nicht"


class _Antwort:
    """Minimale urlopen-Attrappe als Kontextmanager."""

    def __init__(self, nutzlast: bytes):
        self._nutzlast = nutzlast

    def read(self):
        return self._nutzlast

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# ─── Konfiguration ────────────────────────────────────────────────────


def test_keine_eingebauten_zugangsdaten():
    """Ohne Umgebung gibt es KEINE Vorgabewerte — auch keine Adresse.

    Begruendung im Modulkopf: eine eingebaute Projekt-Vorgabe laesst den
    Dienst bei fehlender Umgebung mit dem falschen Projekt reden.
    """
    quelle = open(rowboat.__file__, encoding="utf-8").read()
    for verboten in ("vibemind-local-key", "127.0.0.1:3100", "c157ade4"):
        assert verboten not in quelle, (
            f"{verboten!r} steht als Vorgabe im Code — "
            "Zugangsdaten und Projektkennung gehoeren ausschliesslich in die Umgebung")


def test_fehlende_konfiguration_wird_benannt(monkeypatch):
    monkeypatch.setattr(rowboat, "BASIS", "")
    monkeypatch.setattr(rowboat, "SCHLUESSEL", "")
    fehlt = rowboat.fehlende_konfiguration()
    assert "ROWBOAT_URL" in fehlt
    assert "ROWBOAT_API_KEY" in fehlt
    assert "ROWBOAT_PROJECT_ID" not in fehlt      # steht in der Fixture


def test_ohne_konfiguration_kein_aufruf(monkeypatch):
    """Fail-soft: keine Ausnahme, keine Verbindung, klare Meldung."""
    monkeypatch.setattr(rowboat, "BASIS", "")

    def keine_verbindung(*_a, **_k):            # pragma: no cover
        raise AssertionError("es wurde trotz fehlender Konfiguration gerufen")

    monkeypatch.setattr(rowboat.urllib.request, "urlopen", keine_verbindung)
    e = rowboat.frage("Was wissen wir ueber Firma X?")
    assert e["ok"] is False
    assert "ROWBOAT_URL" in e["fehler"]


# ─── Erfolgsfall ──────────────────────────────────────────────────────


def test_antwort_wird_gelesen(monkeypatch):
    gesehen = {}

    def fake(anfrage, timeout=None):
        gesehen["url"] = anfrage.full_url
        gesehen["kopf"] = dict(anfrage.headers)
        gesehen["rumpf"] = json.loads(anfrage.data)
        return _Antwort(json.dumps({"response": "Firma X ist Bestandskunde."}).encode())

    monkeypatch.setattr(rowboat.urllib.request, "urlopen", fake)
    e = rowboat.frage("Was wissen wir ueber Firma X?")

    assert e["ok"] is True
    assert e["antwort"] == "Firma X ist Bestandskunde."
    assert e["dauer_ms"] >= 0
    assert gesehen["url"] == f"{UNERREICHBAR}/api/v1/test-projekt/chat"
    # urllib normalisiert Kopfzeilennamen auf Erstbuchstabe-gross.
    assert gesehen["kopf"]["Authorization"] == "Bearer test-schluessel"
    assert gesehen["rumpf"]["messages"][0]["content"] == "Was wissen wir ueber Firma X?"


@pytest.mark.parametrize("feld", ["response", "message", "text"])
def test_bekannte_antwortfelder(monkeypatch, feld):
    """Rowboat hat drei Namen fuer dasselbe — alle drei werden gelesen."""
    monkeypatch.setattr(rowboat.urllib.request, "urlopen",
                        lambda *_a, **_k: _Antwort(json.dumps({feld: "Antwort"}).encode()))
    assert rowboat.frage("f")["antwort"] == "Antwort"


def test_leere_antwort_ist_kein_fehler(monkeypatch):
    """Rowboat weiss nichts — das ist eine Antwort, kein Fehler."""
    monkeypatch.setattr(rowboat.urllib.request, "urlopen",
                        lambda *_a, **_k: _Antwort(b"{}"))
    e = rowboat.frage("f")
    assert e["ok"] is True
    assert e["antwort"] == ""


# ─── Fehlerfaelle: nie eine Ausnahme nach aussen ──────────────────────


def test_http_fehler_wird_gemeldet(monkeypatch):
    def fake(*_a, **_k):
        raise urllib.error.HTTPError(UNERREICHBAR, 401, "Unauthorized", {},
                                     io_stub(b'{"error":"bad token"}'))

    monkeypatch.setattr(rowboat.urllib.request, "urlopen", fake)
    e = rowboat.frage("f")
    assert e["ok"] is False
    assert "401" in e["fehler"]


def test_netzfehler_wird_gemeldet(monkeypatch):
    def fake(*_a, **_k):
        raise urllib.error.URLError("keine Route")

    monkeypatch.setattr(rowboat.urllib.request, "urlopen", fake)
    e = rowboat.frage("f")
    assert e["ok"] is False
    assert "URLError" in e["fehler"]


def test_kein_json_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(rowboat.urllib.request, "urlopen",
                        lambda *_a, **_k: _Antwort(b"<html>Fehlerseite</html>"))
    e = rowboat.frage("f")
    assert e["ok"] is False
    assert "JSON" in e["fehler"]


def test_schluessel_steht_nie_in_der_meldung(monkeypatch):
    """Eine Fehlermeldung landet im Protokoll — der Schluessel darf nicht mit."""
    def fake(*_a, **_k):
        raise urllib.error.HTTPError(UNERREICHBAR, 500,
                                     "Bearer test-schluessel abgelehnt", {},
                                     io_stub(b"test-schluessel"))

    monkeypatch.setattr(rowboat.urllib.request, "urlopen", fake)
    e = rowboat.frage("f")
    assert e["ok"] is False
    assert "test-schluessel" not in e["fehler"]


def io_stub(nutzlast: bytes):
    import io
    return io.BytesIO(nutzlast)
