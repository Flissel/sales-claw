"""Verträge über den Upload per WhatsApp an den Bot — Schritt 4b des
UI-Plans (02.09.2026). Betreiber: „kann ich auch über den Bot uploaden?
also Video und alles andere an Formaten?“

Regel: Eine Datei, die der Betreiber AN SICH SELBST schickt (Selbst-Chat,
fromMe und Chat = eigene Nummer), landet im erzeugten Medienordner mit
Herkunft „chat“. Kundenanhänge werden nie übernommen. Der Selbst-Chat
ohne Anhang bleibt verworfen wie bisher.
"""
import base64
import hashlib
import hmac
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import inbox  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


GEHEIMNIS = "test-geheimnis-0123456789"
EIGENE = "491749708452@c.us"
PDF = b"%PDF-1.4 test-inhalt"


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads, sales_test.medien_meta "
            "cascade")
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(inbox, "SECRET", GEHEIMNIS)
    monkeypatch.setattr(inbox, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(inbox, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(media))
    inbox.fehlversuche_zuruecksetzen()
    yield


def _zustellen(daten: dict):
    umschlag = {"event": inbox.EREIGNIS_AUSGEHEND, "data": daten}
    roh = json.dumps(umschlag, ensure_ascii=False).encode("utf-8")
    signatur = "sha256=" + hmac.new(GEHEIMNIS.encode("utf-8"), roh,
                                    hashlib.sha256).hexdigest()
    return inbox.verarbeite(roh, signatur)


def _selbst(media, typ="document", mid="m-1"):
    return {"id": mid, "fromMe": True, "from": EIGENE, "to": EIGENE,
            "chatId": EIGENE, "type": typ, "body": "",
            "timestamp": 1756800000, "media": media}


def _inline(daten: bytes, mimetype="application/pdf", filename="angebot.pdf"):
    return {"data": base64.b64encode(daten).decode("ascii"),
            "mimetype": mimetype, "filename": filename}


def test_datei_an_sich_selbst_landet_in_den_medien(tmp_path):
    status, antwort = _zustellen(_selbst(_inline(PDF)))
    assert status == 200
    assert antwort["medien"] == "angebot.pdf"
    assert (tmp_path / "erzeugt" / "angebot.pdf").read_bytes() == PDF
    zeile = server._q("select herkunft, bot_darf_senden from medien_meta "
                      "where dateiname = 'angebot.pdf'")[0]
    assert zeile["herkunft"] == "chat"
    assert zeile["bot_darf_senden"] is True
    daten = json.loads(server.medien_liste())
    assert any(d["name"] == "angebot.pdf" and d["herkunft"] == "chat"
               for d in daten["dateien"])
    # Nichts davon steht als Nachricht in der Datenbank.
    assert server._q("select count(*) n from activities")[0]["n"] == 0


def test_gleicher_name_wird_nicht_ueberschrieben(tmp_path):
    _zustellen(_selbst(_inline(PDF), mid="m-1"))
    status, antwort = _zustellen(_selbst(_inline(b"%PDF-1.4 zweite"),
                                         mid="m-2"))
    assert status == 200
    assert antwort["medien"] == "angebot-2.pdf"
    assert (tmp_path / "erzeugt" / "angebot.pdf").read_bytes() == PDF


def test_video_geht_nur_als_mp4_und_ohne_namen_nach_typ(tmp_path):
    media = {"data": base64.b64encode(b"\x00\x00\x00 ftypmp42").decode("ascii"),
             "mimetype": "video/mp4"}
    status, antwort = _zustellen(_selbst(media, typ="video", mid="v-1"))
    assert status == 200
    assert antwort["medien"].startswith("chat-") and antwort["medien"].endswith(".mp4")
    assert (tmp_path / "erzeugt" / antwort["medien"]).exists()


def test_grosser_anhang_wird_ueber_die_api_nachgeladen(monkeypatch, tmp_path):
    gesehen = {}

    def nachladen(chat_id, message_id):
        gesehen["chat"], gesehen["msg"] = chat_id, message_id
        return PDF
    monkeypatch.setattr(inbox, "_medien_nachladen", nachladen)
    media = {"mimetype": "application/pdf", "filename": "gross.pdf",
             "omitted": True, "sizeBytes": 5_000_000}
    status, antwort = _zustellen(_selbst(media, mid="g-1"))
    assert status == 200
    assert antwort["medien"] == "gross.pdf"
    assert gesehen == {"chat": EIGENE, "msg": "g-1"}
    assert (tmp_path / "erzeugt" / "gross.pdf").read_bytes() == PDF


def test_nicht_erlaubter_typ_wird_benannt_und_nicht_abgelegt(tmp_path):
    media = _inline(b"PK\x03\x04", mimetype="application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet", filename="tabelle.xlsx")
    status, antwort = _zustellen(_selbst(media, mid="x-1"))
    assert status == 200
    assert "anhang_abgelehnt" in antwort
    assert "medien" not in antwort
    assert list((tmp_path / "erzeugt").iterdir()) == []


def test_kundenanhang_wird_nie_uebernommen(tmp_path):
    server._q("insert into leads (name, phone, source) values "
              "('Kunde K', '+491701112233', 'whatsapp') returning id")
    daten = {"id": "k-1", "fromMe": False, "from": "491701112233@c.us",
             "to": EIGENE, "chatId": "491701112233@c.us", "type": "document",
             "body": "", "timestamp": 1756800000, "media": _inline(PDF)}
    umschlag = {"event": inbox.EREIGNIS, "data": daten}
    roh = json.dumps(umschlag).encode("utf-8")
    signatur = "sha256=" + hmac.new(GEHEIMNIS.encode("utf-8"), roh,
                                    hashlib.sha256).hexdigest()
    status, antwort = inbox.verarbeite(roh, signatur)
    assert status == 200
    assert "medien" not in antwort
    assert list((tmp_path / "erzeugt").iterdir()) == []


def test_selbst_chat_ohne_anhang_bleibt_verworfen(tmp_path):
    daten = _selbst(None, typ="chat", mid="t-1")
    daten["body"] = "nur eine Notiz"
    status, antwort = _zustellen(daten)
    assert status == 200
    assert "verworfen" in antwort and "medien" not in antwort
    assert list((tmp_path / "erzeugt").iterdir()) == []
