"""YouTube-Shorts als sechster Beitragskanal (Nachtrag 25.10.2026 zur Spec
2026-10-24-kanaele-posten): Registry, MP4-Eckdaten, Adapter.

Rein, ohne Datenbank. Nie echtes Netz: kanal_api.HTTP ist ein Rekorder mit
Riegel (conftest.py)."""
import json
import struct
import urllib.parse

import pytest

import kanal_adapter
import kanal_api
from kanaele import KANAELE, pruefe_entwurf, zugang_pruefen
from kanal_api import Antwort, Beleg, KanalFehler, Medium

MIB = 1024 * 1024
KANAL_ID = "UCb2EuqM9XueyXlLzQM0fTvQ"
CLIENT_ID = "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-geheimesClientSecret4711"
REFRESH = "1//0geheimerRefreshToken-abcdefghijklmnop"
ACCESS = "ya29.geheimerZugriffsToken0815"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable"
              "&part=snippet,status&upload_id=geheimeUploadKennung42")
YT = {"YOUTUBE_CLIENT_ID": CLIENT_ID, "YOUTUBE_CLIENT_SECRET": CLIENT_SECRET,
      "YOUTUBE_REFRESH_TOKEN": REFRESH, "YOUTUBE_CHANNEL_ID": KANAL_ID}


@pytest.fixture(autouse=True)
def rek(kanal_http, monkeypatch):
    monkeypatch.delenv("YOUTUBE_SICHTBARKEIT", raising=False)
    return kanal_http


# --- MP4-Bausteine ---------------------------------------------------------------

def _box(typ: bytes, inhalt: bytes) -> bytes:
    return struct.pack(">I", 8 + len(inhalt)) + typ + inhalt


def _mvhd(sekunden: float, version: int = 0, zeitbasis: int = 1000) -> bytes:
    dauer = int(sekunden * zeitbasis)
    if version == 1:
        kopf = struct.pack(">I", 1 << 24) + struct.pack(">QQIQ", 0, 0, zeitbasis, dauer)
    else:
        kopf = struct.pack(">I", 0) + struct.pack(">IIII", 0, 0, zeitbasis, dauer)
    return _box(b"mvhd", kopf + b"\x00" * 80)


def _tkhd(breite: int, hoehe: int, version: int = 0) -> bytes:
    if version == 1:
        kopf = struct.pack(">I", 1 << 24) + struct.pack(">QQIIQ", 0, 0, 1, 0, 0)
    else:
        kopf = struct.pack(">I", 0) + struct.pack(">IIIII", 0, 0, 1, 0, 0)
    rest = b"\x00" * 8 + b"\x00" * 8 + b"\x00" * 36
    return _box(b"tkhd", kopf + rest + struct.pack(">II", breite << 16, hoehe << 16))


def _mp4(sekunden=30.0, breite=1080, hoehe=1920, version=0, mdat_zuerst=False) -> bytes:
    ton = _box(b"trak", _tkhd(0, 0, version))          # Tonspur: 0x0
    bild = _box(b"trak", _tkhd(breite, hoehe, version))
    moov = _box(b"moov", _mvhd(sekunden, version) + ton + bild)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    mdat = _box(b"mdat", b"\x00" * 64)
    return ftyp + (mdat + moov if mdat_zuerst else moov + mdat)


def _video(**kw) -> Medium:
    return Medium("vid-1.mp4", "video/mp4", _mp4(**kw), "video")


def _json(obj, status=200, kopf=None):
    return Antwort(status, {"Content-Type": "application/json", **(kopf or {})},
                   json.dumps(obj).encode())


def _token():
    return _json({"access_token": ACCESS, "expires_in": 3599, "token_type": "Bearer"})


def _kanal(kennung=KANAL_ID):
    return _json({"items": [{"id": kennung}]})


def _start(kopfname="Location"):
    return Antwort(200, {kopfname: UPLOAD_URL}, b"")


def _fertig(kennung="dQw4w9WgXcQ"):
    return _json({"id": kennung, "snippet": {"channelId": KANAL_ID},
                  "status": {"privacyStatus": "private"}})


def _kein_geheimnis(fehler, *werte):
    text = str(fehler)
    for w in werte:
        assert w not in text, w


# --- Registry --------------------------------------------------------------------

def test_registry_youtube():
    info = KANAELE["youtube"]
    assert list(KANAELE)[-1] == "youtube"
    assert info.anzeige == "YouTube"
    assert info.env_namen == ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                              "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID")
    assert info.geheim_namen == ("YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    assert info.titel_pflicht is True and info.titel_max == 100
    assert info.video_pflicht is True
    assert (info.bilder_max, info.video_max, info.medien_max) == (0, 1, 1)
    assert info.max_zeichen == 5000
    assert info.kadenz_pro_tag == 2
    # Alle anderen Kanaele kommen ohne Medium aus.
    assert [k for k, i in KANAELE.items() if i.video_pflicht] == ["youtube"]


def test_zugang_youtube_form():
    info = KANAELE["youtube"]
    assert zugang_pruefen(info, YT) is None
    grund = zugang_pruefen(info, {**YT, "YOUTUBE_CHANNEL_ID": "@vibemindos"})
    assert grund and "YOUTUBE_CHANNEL_ID" in grund and "vibemindos" not in grund
    grund = zugang_pruefen(info, {**YT, "YOUTUBE_CLIENT_ID": "kein-client"})
    assert grund and "YOUTUBE_CLIENT_ID" in grund and "kein-client" not in grund
    grund = zugang_pruefen(info, {**YT, "YOUTUBE_REFRESH_TOKEN": ""})
    assert grund == "YOUTUBE_REFRESH_TOKEN fehlt"


def test_pruefe_entwurf_youtube():
    yt = KANAELE["youtube"]
    video = ("vid-1.mp4", "video", 10 * MIB)
    assert pruefe_entwurf(yt, "Beschreibung", "Titel", [video]) is None
    grund = pruefe_entwurf(yt, "Beschreibung", "Titel", [])
    assert grund and "Video ist Pflicht" in grund
    grund = pruefe_entwurf(yt, "Beschreibung", "", [video])
    assert grund and "Titel ist Pflicht" in grund
    assert pruefe_entwurf(yt, "B", "x" * 101, [video])
    assert pruefe_entwurf(yt, "B", "x" * 100, [video]) is None
    assert pruefe_entwurf(yt, "x" * 5001, "T", [video])
    grund = pruefe_entwurf(yt, "B", "T", [("a.png", "bild", 100)])
    assert grund and "Bilder sind hier nicht möglich" in grund
    assert pruefe_entwurf(yt, "B", "T", [video, video])
    assert pruefe_entwurf(yt, "B", "T", [("v.mp4", "video", 256 * MIB + 1)])
    # Der Satz fuer Kanaele ohne Titel nennt jetzt beide Titel-Kanaele.
    grund = pruefe_entwurf(KANAELE["bluesky"], "hallo", "Titel", [])
    assert grund and "titel gibt es nur bei dev.to und YouTube" in grund


# --- MP4-Eckdaten ------------------------------------------------------------------

def test_mp4_eckdaten_hochkant():
    assert kanal_adapter.mp4_eckdaten(_mp4(42.5, 1080, 1920)) == (42.5, 1080, 1920)


def test_mp4_eckdaten_version1_und_mdat_vorn():
    assert kanal_adapter.mp4_eckdaten(
        _mp4(179.0, 1080, 1080, version=1, mdat_zuerst=True)) == (179.0, 1080, 1080)


@pytest.mark.parametrize("daten", [b"", b"kein mp4", b"\x00\x00\x00\x08ftyp",
                                   _box(b"moov", _mvhd(10)),  # ohne Bildspur
                                   _box(b"ftyp", b"isom")])
def test_mp4_eckdaten_unlesbar(daten):
    assert kanal_adapter.mp4_eckdaten(daten) is None


def test_mp4_kaputte_groesse_laeuft_nicht_endlos():
    # Box-Groesse 0 mitten im moov oder kleiner als der Kopf: kein Haenger.
    kaputt = _box(b"moov", struct.pack(">I", 3) + b"mvhd" + b"\x00" * 20)
    assert kanal_adapter.mp4_eckdaten(kaputt) is None


# --- Adapter -------------------------------------------------------------------------

def test_youtube_erfolg_ablauf(rek):
    rek.vorrat += [_token(), _kanal(), _start(), _fertig()]
    beleg = kanal_adapter.senden_youtube(YT, "Beschreibung #KI", [_video()],
                                         "Unser Short", "d1")
    assert beleg == Beleg("dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ")
    token, kanal, start, hoch = rek.anfragen

    assert token.methode == "POST" and token.url == "https://oauth2.googleapis.com/token"
    assert token.kopf["Content-Type"] == "application/x-www-form-urlencoded"
    form = dict(urllib.parse.parse_qsl(token.daten.decode()))
    assert form == {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET, "refresh_token": REFRESH}

    assert kanal.methode == "GET"
    assert kanal.url == "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true"
    assert kanal.kopf["Authorization"] == f"Bearer {ACCESS}"

    assert start.methode == "POST"
    assert start.url == ("https://www.googleapis.com/upload/youtube/v3/videos"
                         "?uploadType=resumable&part=snippet,status")
    assert start.kopf["Authorization"] == f"Bearer {ACCESS}"
    assert start.kopf["X-Upload-Content-Type"] == "video/mp4"
    assert start.kopf["X-Upload-Content-Length"] == str(len(_video().daten))
    meta = json.loads(start.daten)
    assert meta["snippet"]["title"] == "Unser Short"
    assert meta["snippet"]["description"] == "Beschreibung #KI"
    assert meta["snippet"]["categoryId"] == "28"
    assert meta["status"]["privacyStatus"] == "private"
    assert meta["status"]["selfDeclaredMadeForKids"] is False
    assert meta["status"]["containsSyntheticMedia"] is True

    assert hoch.methode == "PUT" and hoch.url == UPLOAD_URL
    assert hoch.kopf["Content-Type"] == "video/mp4"
    assert hoch.daten == _video().daten
    assert hoch.frist == kanal_api.FRIST_UPLOAD


def test_youtube_location_kopf_klein_geschrieben(rek):
    rek.vorrat += [_token(), _kanal(), _start("location"), _fertig("abc")]
    beleg = kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert beleg.beitrag == "abc"
    assert rek.anfragen[3].url == UPLOAD_URL


@pytest.mark.parametrize("wert,erwartet", [
    ("unlisted", "unlisted"), ("PUBLIC", "public"), (" private ", "private"),
    ("oeffentlich", "private"), ("", "private")])
def test_youtube_sichtbarkeit_aus_env(rek, monkeypatch, wert, erwartet):
    monkeypatch.setenv("YOUTUBE_SICHTBARKEIT", wert)
    rek.vorrat += [_token(), _kanal(), _start(), _fertig()]
    kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert json.loads(rek.anfragen[2].daten)["status"]["privacyStatus"] == erwartet


def test_youtube_spitze_klammern_ersetzt(rek):
    rek.vorrat += [_token(), _kanal(), _start(), _fertig()]
    kanal_adapter.senden_youtube(YT, "a -> b <c>", [_video()], "<Titel>", "d1")
    snippet = json.loads(rek.anfragen[2].daten)["snippet"]
    assert "<" not in snippet["title"] + snippet["description"]
    assert ">" not in snippet["title"] + snippet["description"]
    assert snippet["title"] == "‹Titel›"


@pytest.mark.parametrize("medien,satz", [
    ([], "genau ein Video"),
    ([Medium("a.png", "image/png", b"\x89PNG", "bild")], "genau ein Video"),
    ([Medium("a.mp4", "video/mp4", b"kaputt", "video")], "nicht lesbar"),
])
def test_youtube_ohne_brauchbares_video_kein_netz(rek, medien, satz):
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", medien, "T", "d1")
    assert e.value.art == "dauerhaft" and satz in str(e.value)
    assert rek.anfragen == []


def test_youtube_zu_lang_kein_short(rek):
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video(sekunden=181)], "T", "d1")
    assert e.value.art == "dauerhaft" and "3 Minuten" in str(e.value)
    assert rek.anfragen == []


def test_youtube_quer_kein_short(rek):
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video(breite=1920, hoehe=1080)], "T", "d1")
    assert e.value.art == "dauerhaft" and "quer" in str(e.value)
    assert rek.anfragen == []


def test_youtube_quadratisch_und_genau_3_minuten_erlaubt(rek):
    rek.vorrat += [_token(), _kanal(), _start(), _fertig()]
    kanal_adapter.senden_youtube(YT, "B", [_video(sekunden=180, breite=1080, hoehe=1080)],
                                 "T", "d1")
    assert len(rek.anfragen) == 4


def test_youtube_beschreibung_zu_viele_bytes(rek):
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "ü" * 2501, [_video()], "T", "d1")
    assert e.value.art == "dauerhaft" and "5000 Bytes" in str(e.value)
    assert rek.anfragen == []


def test_youtube_token_abgelehnt_dauerhaft_ohne_geheimnis(rek):
    rek.vorrat.append(_json({"error": "invalid_grant",
                             "error_description": f"Bad token {REFRESH} {CLIENT_SECRET}"}, 400))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft"
    assert "invalid_grant" in str(e.value)
    _kein_geheimnis(e.value, REFRESH, CLIENT_SECRET)
    assert len(rek.anfragen) == 1


def test_youtube_token_ohne_access_token(rek):
    rek.vorrat.append(_json({"token_type": "Bearer"}))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 1


def test_youtube_falscher_kanal_laedt_nichts_hoch(rek):
    rek.vorrat += [_token(), _kanal("UCaaaaaaaaaaaaaaaaaaaaaa")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft"
    assert "anderen Kanal" in str(e.value)
    _kein_geheimnis(e.value, KANAL_ID, "UCaaaaaaaaaaaaaaaaaaaaaa")
    assert len(rek.anfragen) == 2


def test_youtube_kanal_timeout_dauerhaft(rek):
    rek.vorrat += [_token(), TimeoutError("x")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft"


def test_youtube_start_ohne_location_dauerhaft(rek):
    rek.vorrat += [_token(), _kanal(), Antwort(200, {}, b"")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 3


def test_youtube_start_quota_dauerhaft(rek):
    rek.vorrat += [_token(), _kanal(),
                   _json({"error": {"code": 403, "message": "quotaExceeded"}}, 403)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "dauerhaft" and e.value.status == 403


def test_youtube_hochladen_timeout_ungewiss_ohne_geheimnis(rek):
    rek.vorrat += [_token(), _kanal(), _start(), TimeoutError("x")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "ungewiss"
    assert "UNBEKANNT" in str(e.value)
    _kein_geheimnis(e.value, ACCESS, "geheimeUploadKennung42", REFRESH)


def test_youtube_hochladen_500_ungewiss(rek):
    rek.vorrat += [_token(), _kanal(), _start(),
                   _json({"error": {"message": f"backend {UPLOAD_URL}"}}, 503)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "ungewiss"
    _kein_geheimnis(e.value, "geheimeUploadKennung42")


def test_youtube_antwort_ohne_kennung_ungewiss(rek):
    rek.vorrat += [_token(), _kanal(), _start(), _json({"kind": "youtube#video"})]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_youtube(YT, "B", [_video()], "T", "d1")
    assert e.value.art == "ungewiss"


def test_youtube_steht_in_sender():
    assert kanal_adapter.SENDER["youtube"] is kanal_adapter.senden_youtube
