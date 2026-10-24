"""Adapter Telegram-Kanal, Discord, dev.to (Spec 2026-10-24-kanaele-posten).
Nie echtes Netz: kanal_api.HTTP ist ein Rekorder mit Riegel."""
import json

import pytest

import kanal_adapter
import kanal_api
from kanaele import KANAELE
from kanal_api import Antwort, Beleg, KanalFehler, Medium

TG_TOKEN = "987654:XYZsecretTOKEN"
TG = {"TELEGRAM_KANAL_ID": "@vibemind_kanal", "TELEGRAM_KANAL_BOT_TOKEN": TG_TOKEN}
WH_SEGMENT = "geheimesWebhookSegment_123-abc"
WEBHOOK = f"https://discord.com/api/webhooks/1122334455/{WH_SEGMENT}"
DC = {"DISCORD_ANKUENDIGUNG_WEBHOOK": WEBHOOK}
DEVTO_KEY = "devtoKEY4711geheim"
DV = {"DEVTO_API_KEY": DEVTO_KEY}
BILD = Medium("a.jpg", "image/jpeg", b"\xff\xd8bild", "bild")
VIDEO = Medium("v.mp4", "video/mp4", b"\x00\x00video", "video")


class Rekorder:
    def __init__(self):
        self.vorrat = []
        self.anfragen = []

    def __call__(self, anfrage):
        self.anfragen.append(anfrage)
        if not self.vorrat:
            pytest.fail(f"unerwarteter HTTP-Aufruf Nr. {len(self.anfragen)}")
        naechste = self.vorrat.pop(0)
        if isinstance(naechste, BaseException):
            raise naechste
        return naechste


@pytest.fixture(autouse=True)
def rek(monkeypatch):
    r = Rekorder()
    monkeypatch.setattr(kanal_api, "HTTP", r)
    return r


def _json(obj, status=200):
    return Antwort(status, {"Content-Type": "application/json"}, json.dumps(obj).encode())


def _kein_geheimnis(fehler, *werte):
    text = str(fehler)
    for w in werte:
        assert w not in text


def _payload_json(rumpf: bytes) -> dict:
    teil = rumpf.split(b'name="payload_json"', 1)[1]
    teil = teil.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0]
    return json.loads(teil)


def test_sender_registry():
    assert set(kanal_adapter.SENDER) <= set(KANAELE)
    assert {"telegram_kanal", "discord", "devto"} <= set(kanal_adapter.SENDER)


# --- Telegram-Kanal ------------------------------------------------------------

def test_telegram_text_erfolg(rek):
    rek.vorrat.append(_json({"ok": True, "result": {
        "message_id": 42, "chat": {"id": -100555, "username": "vibemind_kanal"}}}))
    beleg = kanal_adapter.senden_telegram_kanal(TG, "Hallo Kanal", [], "", "d1")
    assert beleg == Beleg("42", "https://t.me/vibemind_kanal/42")
    a = rek.anfragen[0]
    assert a.methode == "POST"
    assert a.url.endswith("/sendMessage")
    assert a.frist == kanal_api.FRIST_JSON
    assert json.loads(a.daten) == {"chat_id": "@vibemind_kanal", "text": "Hallo Kanal"}


def test_telegram_url_aus_at_id_ohne_username(rek):
    rek.vorrat.append(_json({"ok": True, "result": {"message_id": 7, "chat": {"id": -1}}}))
    beleg = kanal_adapter.senden_telegram_kanal(TG, "x", [], "", "d1")
    assert beleg == Beleg("7", "https://t.me/vibemind_kanal/7")


def test_telegram_bild_als_caption(rek):
    rek.vorrat.append(_json({"ok": True, "result": {"message_id": 43, "chat": {}}}))
    beleg = kanal_adapter.senden_telegram_kanal(TG, "Mit Bild", [BILD], "", "d1")
    assert beleg.beitrag == "43"
    a = rek.anfragen[0]
    assert a.url.endswith("/sendPhoto")
    assert a.frist == kanal_api.FRIST_UPLOAD
    assert a.kopf["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="caption"' in a.daten and b"Mit Bild" in a.daten
    assert b'name="photo"; filename="a.jpg"' in a.daten
    assert b'name="chat_id"' in a.daten


def test_telegram_video(rek):
    rek.vorrat.append(_json({"ok": True, "result": {"message_id": 44, "chat": {}}}))
    kanal_adapter.senden_telegram_kanal(TG, "Clip", [VIDEO], "", "d1")
    a = rek.anfragen[0]
    assert a.url.endswith("/sendVideo")
    assert b'name="video"; filename="v.mp4"' in a.daten


def test_telegram_privater_kanal_url(rek):
    rek.vorrat.append(_json({"ok": True, "result": {"message_id": 42, "chat": {"id": -1001234567890}}}))
    zugang = dict(TG, TELEGRAM_KANAL_ID="-1001234567890")
    beleg = kanal_adapter.senden_telegram_kanal(zugang, "x", [], "", "d1")
    assert beleg == Beleg("42", "https://t.me/c/1234567890/42")


def test_telegram_ok_false_ungewiss(rek):
    rek.vorrat.append(_json({"ok": False}))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_telegram_kanal(TG, "x", [], "", "d1")
    assert e.value.art == "ungewiss"


def test_telegram_403_dauerhaft_ohne_token(rek):
    rek.vorrat.append(_json({"ok": False, "description": f"Forbidden: bot {TG_TOKEN} is not a member"}, 403))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_telegram_kanal(TG, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert e.value.status == 403
    assert "sendMessage" in str(e.value)
    _kein_geheimnis(e.value, TG_TOKEN, "api.telegram.org")


def test_telegram_timeout_ungewiss(rek):
    rek.vorrat.append(TimeoutError("timed out"))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_telegram_kanal(TG, "x", [BILD], "", "d1")
    assert e.value.art == "ungewiss"
    _kein_geheimnis(e.value, TG_TOKEN)


# --- Discord ---------------------------------------------------------------------

def _dc_get():
    return _json({"id": "1122334455", "guild_id": "G", "channel_id": "C", "token": WH_SEGMENT})


def test_discord_erfolg_mit_link(rek):
    rek.vorrat += [_dc_get(), _json({"id": "M", "channel_id": "C"})]
    beleg = kanal_adapter.senden_discord(DC, "Neu bei uns", [], "", "d1")
    assert beleg == Beleg("M", "https://discord.com/channels/G/C/M")
    get, post = rek.anfragen
    assert get.methode == "GET" and get.url == WEBHOOK and get.daten is None
    assert post.methode == "POST" and post.url == WEBHOOK + "?wait=true"
    assert json.loads(post.daten)["content"] == "Neu bei uns"


def test_discord_pingt_niemanden(rek):
    rek.vorrat += [_dc_get(), _json({"id": "M"})]
    kanal_adapter.senden_discord(DC, "@everyone neu!", [], "", "d1")
    last = json.loads(rek.anfragen[1].daten)
    assert last["allowed_mentions"] == {"parse": []}
    assert last["content"] == "@everyone neu!"


def test_discord_mit_bild_multipart(rek):
    rek.vorrat += [_dc_get(), _json({"id": "M"})]
    kanal_adapter.senden_discord(DC, "@here Bild", [BILD], "", "d1")
    post = rek.anfragen[1]
    assert post.frist == kanal_api.FRIST_UPLOAD
    assert post.kopf["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="files[0]"; filename="a.jpg"' in post.daten
    assert _payload_json(post.daten) == {"content": "@here Bild", "allowed_mentions": {"parse": []}}


def test_discord_get_scheitert_nichts_gepostet(rek):
    rek.vorrat.append(_json({"message": "Unknown Webhook"}, 404))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_discord(DC, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 1


def test_discord_get_timeout_dauerhaft(rek):
    # Das Lesen des Webhooks veroeffentlicht nichts: kein ungewiss.
    rek.vorrat.append(TimeoutError("x"))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_discord(DC, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 1


def test_discord_fehlertext_ohne_webhook(rek):
    rek.vorrat += [_dc_get(), _json({"message": f"bad {WEBHOOK} token {WH_SEGMENT}"}, 400)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_discord(DC, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    _kein_geheimnis(e.value, WEBHOOK, WH_SEGMENT, "/webhooks/")


def test_discord_post_timeout_ungewiss(rek):
    rek.vorrat += [_dc_get(), TimeoutError("x")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_discord(DC, "x", [], "", "d1")
    assert e.value.art == "ungewiss"
    _kein_geheimnis(e.value, WEBHOOK, WH_SEGMENT)


# --- dev.to ------------------------------------------------------------------------

def test_devto_immer_unveroeffentlicht(rek):
    rek.vorrat.append(_json({"id": 999, "url": "https://dev.to/vibemind/titel-temp-slug-1"}, 201))
    beleg = kanal_adapter.senden_devto(DV, "# Text\n\nInhalt", [], "Mein Titel", "d1")
    assert beleg == Beleg("999", "https://dev.to/vibemind/titel-temp-slug-1")
    a = rek.anfragen[0]
    assert a.methode == "POST" and a.url == "https://dev.to/api/articles"
    assert a.kopf["api-key"] == DEVTO_KEY
    artikel = json.loads(a.daten)["article"]
    assert artikel["published"] is False
    assert artikel["title"] == "Mein Titel"
    assert artikel["body_markdown"] == "# Text\n\nInhalt"


def test_devto_422_dauerhaft_ohne_schluessel(rek):
    rek.vorrat.append(_json({"error": f"invalid api-key {DEVTO_KEY}"}, 422))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_devto(DV, "x", [], "T", "d1")
    assert e.value.art == "dauerhaft"
    assert e.value.status == 422
    _kein_geheimnis(e.value, DEVTO_KEY)


def test_devto_timeout_ungewiss(rek):
    rek.vorrat.append(TimeoutError("x"))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_devto(DV, "x", [], "T", "d1")
    assert e.value.art == "ungewiss"
    assert "UNBEKANNT" in str(e.value)
