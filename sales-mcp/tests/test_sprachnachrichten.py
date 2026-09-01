"""Vertragstests fuer Sprachnachrichten (01.09.2026).

Gemessen: OpenWA schickt 16 Sprachnachrichten in 30 Tagen — der
Assistent war fuer sie BLIND (`text: ""`, Anzeige „ohne Text"). Der
Webhook liefert das Audio inline mit (WEBHOOK_MEDIA_INLINE_MAX_BYTES,
Vorgabe 1 MB); bisher wurde es weggeworfen.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Der Webhook bleibt SCHNELL: das Audio wird gespeichert, nicht
   transkribiert. Eine Transkription im Webhook (Sekunden) liesse
   OpenWA in den Wiederholungslauf gehen.
2. Die Transkription ist eine EIGENE Aktivitaet (`transkription`) mit
   Bezug zur message_id — activities ist append-only, die urspruengliche
   Zeile wird nie veraendert.
3. Sie bleibt im Haus: der Text kommt von sales-stt auf derselben VM.
   Faellt der Dienst aus, bleibt die Sprachnachricht unverarbeitet
   liegen — sie geht nie an einen Fremddienst und nie verloren.
"""
import base64
import hashlib
import hmac
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import inbox  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


GEHEIMNIS = "test-geheimnis-0123456789"


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(inbox, "SECRET", GEHEIMNIS)
    monkeypatch.setattr(inbox, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(inbox, "SPRACH_VERZEICHNIS", str(tmp_path))
    monkeypatch.setattr(server, "SPRACH_VERZEICHNIS", str(tmp_path))
    inbox.fehlversuche_zuruecksetzen()
    yield


def _zustellen(daten: dict):
    """Ein signierter Zustellversuch — wie ihn OpenWA schickt."""
    umschlag = {"event": inbox.EREIGNIS, "data": daten}
    roh = json.dumps(umschlag, ensure_ascii=False).encode("utf-8")
    signatur = "sha256=" + hmac.new(GEHEIMNIS.encode("utf-8"), roh,
                                    hashlib.sha256).hexdigest()
    return inbox.verarbeite(roh, signatur)


def _lead(name="Vera Voice", phone="+491701112233"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, %s, 'whatsapp') returning id", (name, phone))[0]["id"])


def _webhook_daten(message_id="wa-voice-1", typ="voice", media=True):
    daten = {"from": "491701112233@c.us", "to": "4917499@c.us",
             "body": "", "type": typ, "fromMe": False,
             "timestamp": 1756700000, "id": message_id}
    if media:
        daten["media"] = {"mimetype": "audio/ogg; codecs=opus",
                          "data": base64.b64encode(b"OggS-Testaudio").decode()}
    return daten


def _aktivitaeten(typ):
    return server._q("select payload from activities where type = %s "
                     "order by created_at", (typ,))


# ---------------------------------------------------------------------------
# Der Webhook: speichern, nicht transkribieren
# ---------------------------------------------------------------------------

def test_audio_wird_gespeichert_und_der_pfad_vermerkt():
    _lead()
    code, _ = _zustellen(_webhook_daten())
    assert code == 200
    zeilen = _aktivitaeten("kundenantwort")
    assert len(zeilen) == 1
    nutzlast = zeilen[0]["payload"]
    assert nutzlast["nachrichtentyp"] == "voice"
    datei = nutzlast.get("audio_datei")
    assert datei
    assert os.path.exists(os.path.join(inbox.SPRACH_VERZEICHNIS, datei))


def test_ohne_audio_bleibt_alles_wie_bisher():
    _lead()
    _zustellen(_webhook_daten(typ="text", media=False))
    nutzlast = _aktivitaeten("kundenantwort")[0]["payload"]
    assert "audio_datei" not in nutzlast


def test_bilder_werden_nicht_als_audio_abgelegt():
    _lead()
    daten = _webhook_daten(typ="image")
    daten["media"]["mimetype"] = "image/jpeg"
    _zustellen(daten)
    nutzlast = _aktivitaeten("kundenantwort")[0]["payload"]
    assert "audio_datei" not in nutzlast


def test_privater_kontakt_bekommt_keine_audiodatei():
    lead = _lead(name="Lisa Privat")
    server._q("update leads set enrichment = '{\"_privat\": {}}'::jsonb "
              "where id = %s returning id", (lead,))
    code, antwort = _zustellen(_webhook_daten())
    assert code == 200 and antwort.get("privat") is True
    assert os.listdir(inbox.SPRACH_VERZEICHNIS) == []


# ---------------------------------------------------------------------------
# Die Transkription: eigenes Werkzeug, eigene Aktivitaet
# ---------------------------------------------------------------------------

class _SttStub:
    def __init__(self, text="Guten Tag, ich haette eine Frage zur Police."):
        self.text = text
        self.aufrufe = 0

    def __call__(self, audio: bytes) -> dict:
        self.aufrufe += 1
        return {"text": self.text, "sprache": "de", "dauer_s": 8.2}


def test_transkription_wird_eigene_aktivitaet(monkeypatch):
    _lead()
    _zustellen(_webhook_daten())
    stub = _SttStub()
    monkeypatch.setattr(server, "_stt_aufrufen", stub)

    ergebnis = json.loads(server.sprachnachrichten_transkribieren())

    assert ergebnis["transkribiert"] == 1
    zeilen = _aktivitaeten("transkription")
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["text"] == stub.text
    assert zeilen[0]["payload"]["message_id"] == "wa-voice-1"
    # Die urspruengliche Zeile bleibt unangetastet (append-only).
    assert _aktivitaeten("kundenantwort")[0]["payload"]["text"] == ""


def test_zweiter_lauf_transkribiert_nicht_erneut(monkeypatch):
    _lead()
    _zustellen(_webhook_daten())
    stub = _SttStub()
    monkeypatch.setattr(server, "_stt_aufrufen", stub)
    server.sprachnachrichten_transkribieren()
    ergebnis = json.loads(server.sprachnachrichten_transkribieren())
    assert ergebnis["transkribiert"] == 0
    assert stub.aufrufe == 1


def test_ausfall_des_dienstes_verliert_nichts(monkeypatch):
    _lead()
    _zustellen(_webhook_daten())

    def kaputt(audio):
        raise OSError("connection refused")
    monkeypatch.setattr(server, "_stt_aufrufen", kaputt)

    ergebnis = json.loads(server.sprachnachrichten_transkribieren())
    assert ergebnis["transkribiert"] == 0
    assert ergebnis["gescheitert"] == 1
    assert _aktivitaeten("transkription") == []
    # Beim naechsten Lauf ist sie wieder dran — nichts ist verloren.
    monkeypatch.setattr(server, "_stt_aufrufen", _SttStub())
    assert json.loads(
        server.sprachnachrichten_transkribieren())["transkribiert"] == 1


def test_leere_transkription_wird_vermerkt_statt_wiederholt(monkeypatch):
    """Eine Sprachnachricht ohne erkennbare Worte (Rauschen, Versehen)
    darf nicht bei jedem Lauf erneut durch die Maschine."""
    _lead()
    _zustellen(_webhook_daten())
    monkeypatch.setattr(server, "_stt_aufrufen", _SttStub(text="   "))
    ergebnis = json.loads(server.sprachnachrichten_transkribieren())
    assert ergebnis["transkribiert"] == 1
    zeilen = _aktivitaeten("transkription")
    assert zeilen[0]["payload"]["text"] == ""
    assert zeilen[0]["payload"].get("leer") is True


def test_private_kontakte_werden_nie_transkribiert(monkeypatch):
    lead = _lead()
    _zustellen(_webhook_daten())
    server._q("update leads set enrichment = '{\"_privat\": {}}'::jsonb "
              "where id = %s returning id", (lead,))
    stub = _SttStub()
    monkeypatch.setattr(server, "_stt_aufrufen", stub)
    ergebnis = json.loads(server.sprachnachrichten_transkribieren())
    assert ergebnis["transkribiert"] == 0
    assert stub.aufrufe == 0


def test_fehlende_datei_wird_gemeldet_nicht_verschluckt(monkeypatch):
    _lead()
    _zustellen(_webhook_daten())
    for name in os.listdir(inbox.SPRACH_VERZEICHNIS):
        os.unlink(os.path.join(inbox.SPRACH_VERZEICHNIS, name))
    monkeypatch.setattr(server, "_stt_aufrufen", _SttStub())
    ergebnis = json.loads(server.sprachnachrichten_transkribieren())
    assert ergebnis["gescheitert"] == 1
