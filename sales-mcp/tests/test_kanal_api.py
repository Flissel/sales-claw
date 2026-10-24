"""HTTP-Kern fuer eigene Kanal-Beitraege (Spec 2026-10-24-kanaele-posten):
Fehlereinordnung dauerhaft/ungewiss, Geheimnisse aus jedem Text, multipart.
Nie echtes Netz: kanal_api.HTTP ist ein Rekorder mit Riegel."""
import json

import pytest

import kanal_api
from kanal_api import Anfrage, Antwort, KanalFehler

TOKEN = "123456:ABCdef"
URL = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"


@pytest.fixture(autouse=True)
def rek(kanal_http):
    # Rekorder mit Riegel aus conftest.py: nie echtes Netz.
    return kanal_http


def _anfrage():
    return Anfrage("POST", URL, {"Content-Type": "application/json"}, b"{}", kanal_api.FRIST_JSON)


def _ruf(veroeffentlicht=True):
    return kanal_api.ruf(_anfrage(), kanal="telegram_kanal", was="sendPhoto",
                         veroeffentlicht=veroeffentlicht, geheimnisse=[TOKEN])


def test_ohne_geheimnisse_ersetzt_werte_und_adressen():
    text = f"Token {TOKEN} an {URL} fehlgeschlagen"
    ergebnis = kanal_api.ohne_geheimnisse(text, [TOKEN, "kurz"])
    assert TOKEN not in ergebnis
    assert "/bot" not in ergebnis
    assert "<geheim>" in ergebnis
    assert "<adresse>" in ergebnis
    webhook = "https://discord.com/api/webhooks/1/abcXYZ"
    assert "abcXYZ" not in kanal_api.ohne_geheimnisse(f"x {webhook}", [])


def test_ruf_2xx_gibt_antwort(rek):
    rek.vorrat.append(Antwort(201, {}, b'{"ok": true}'))
    assert _ruf().status == 201
    assert rek.anfragen[0].url == URL


def test_ruf_4xx_dauerhaft(rek):
    rek.vorrat.append(Antwort(400, {}, b"bad"))
    with pytest.raises(KanalFehler) as e:
        _ruf()
    assert e.value.art == "dauerhaft"
    assert e.value.ungewiss is False
    assert e.value.status == 400
    assert str(e.value).startswith("Telegram-Kanal: HTTP 400 bei sendPhoto: bad")


def test_ruf_5xx_ungewiss_nur_beim_veroeffentlichen(rek):
    rek.vorrat += [Antwort(503, {}, b"weg"), Antwort(503, {}, b"weg")]
    with pytest.raises(KanalFehler) as e:
        _ruf(veroeffentlicht=True)
    assert e.value.art == "ungewiss"
    assert e.value.status == 503
    with pytest.raises(KanalFehler) as e:
        _ruf(veroeffentlicht=False)
    assert e.value.art == "dauerhaft"


def test_ruf_408_ungewiss(rek):
    rek.vorrat.append(Antwort(408, {}, b""))
    with pytest.raises(KanalFehler) as e:
        _ruf()
    assert e.value.art == "ungewiss"


def test_ruf_timeout_ungewiss(rek):
    rek.vorrat.append(TimeoutError("timed out"))
    with pytest.raises(KanalFehler) as e:
        _ruf()
    assert e.value.art == "ungewiss"
    assert "UNBEKANNT" in str(e.value)
    assert "sendPhoto" in str(e.value)


def test_ruf_netzfehler_ohne_veroeffentlichen_dauerhaft(rek):
    rek.vorrat.append(OSError("reset"))
    with pytest.raises(KanalFehler) as e:
        _ruf(veroeffentlicht=False)
    assert e.value.art == "dauerhaft"


def test_kein_schluessel_im_fehlertext(rek):
    rumpf = json.dumps({"description": f"Unauthorized {TOKEN} at {URL}"}).encode()
    rek.vorrat.append(Antwort(401, {}, rumpf))
    with pytest.raises(KanalFehler) as e:
        _ruf()
    assert TOKEN not in str(e.value)
    assert URL not in str(e.value)
    assert "api.telegram.org/bot" not in str(e.value)


def test_json_ruf_liefert_objekt(rek):
    rek.vorrat.append(Antwort(200, {}, b'{"ok": true}'))
    assert kanal_api.json_ruf(_anfrage(), kanal="discord", was="x",
                              veroeffentlicht=True, geheimnisse=[]) == {"ok": True}


def test_json_ruf_unlesbar_beim_veroeffentlichen_ungewiss(rek):
    rek.vorrat.append(Antwort(200, {}, b"<html>"))
    with pytest.raises(KanalFehler) as e:
        kanal_api.json_ruf(_anfrage(), kanal="discord", was="execute",
                           veroeffentlicht=True, geheimnisse=[])
    assert e.value.art == "ungewiss"
    assert "Antwort ohne lesbare Kennung" in str(e.value)


def test_json_ruf_unlesbar_ohne_veroeffentlichen_dauerhaft(rek):
    rek.vorrat.append(Antwort(200, {}, b"[1, 2]"))
    with pytest.raises(KanalFehler) as e:
        kanal_api.json_ruf(_anfrage(), kanal="discord", was="webhook lesen",
                           veroeffentlicht=False, geheimnisse=[])
    assert e.value.art == "dauerhaft"


def test_multipart_traegt_felder_und_datei():
    rumpf, content_type = kanal_api.multipart(
        {"chat_id": "@vibemind_kanal", "caption": "Grüße"},
        [("photo", "a.jpg", "image/jpeg", b"\xff\xd8JPEG")])
    assert content_type.startswith("multipart/form-data; boundary=")
    grenze = content_type.split("boundary=", 1)[1]
    assert b'name="chat_id"' in rumpf
    assert b'filename="a.jpg"' in rumpf
    assert b"Content-Type: image/jpeg" in rumpf
    assert b"\xff\xd8JPEG" in rumpf
    assert "Grüße".encode() in rumpf
    assert rumpf.endswith(f"--{grenze}--\r\n".encode())


def test_urllib_http_gibt_http_fehler_als_antwort(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    gesehen = {}

    def falsch_urlopen(req, timeout):
        gesehen["ua"] = req.get_header("User-agent")
        gesehen["frist"] = timeout
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {"X": "1"}, io.BytesIO(b"weg"))

    monkeypatch.setattr(urllib.request, "urlopen", falsch_urlopen)
    antwort = kanal_api._urllib_http(_anfrage())
    assert antwort == Antwort(404, {"X": "1"}, b"weg")
    assert gesehen["ua"].startswith("sales-claw/")
    assert gesehen["frist"] == kanal_api.FRIST_JSON


def test_urllib_http_wirft_netzfehler_weiter(monkeypatch):
    import urllib.error
    import urllib.request

    def falsch_urlopen(req, timeout):
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(urllib.request, "urlopen", falsch_urlopen)
    with pytest.raises(urllib.error.URLError):
        kanal_api._urllib_http(_anfrage())


def test_ruf_valueerror_dauerhaft_ohne_url(rek):
    webhook = "https://discord.com/api/webhooks/1/geheimSegment99"
    rek.vorrat.append(ValueError(f"unknown url type: {webhook}"))
    with pytest.raises(KanalFehler) as e:
        _ruf(veroeffentlicht=True)
    assert e.value.art == "dauerhaft"
    assert webhook not in str(e.value)
    assert "geheimSegment99" not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_ruf_http_exception_ungewiss(rek):
    import http.client
    rek.vorrat.append(http.client.IncompleteRead(b""))
    with pytest.raises(KanalFehler) as e:
        _ruf(veroeffentlicht=True)
    assert e.value.art == "ungewiss"
    assert "UNBEKANNT" in str(e.value)
