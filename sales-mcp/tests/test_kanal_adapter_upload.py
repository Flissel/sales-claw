"""Adapter Bluesky und Mastodon mit Medien-Upload (Spec 2026-10-24-kanaele-posten).
Nie echtes Netz: kanal_api.HTTP ist ein Rekorder mit Riegel; das Warten
auf die Mastodon-Verarbeitung ist ersetzt."""
import json

import pytest

import kanaele
import kanal_adapter
from kanal_api import Antwort, Beleg, KanalFehler, Medium

BS_PASS = "abcd-efgh-ijkl-mnop"
BS_JWT = "eyJhbGciOiJIUzI1NiJ9.sitzungsJWTgeheim.signatur"
BS = {"BLUESKY_HANDLE": "vibemind.bsky.social", "BLUESKY_APP_PASSWORD": BS_PASS}
BS_DID = "did:plc:abc123"
BS_URI = f"at://{BS_DID}/app.bsky.feed.post/3kabc"
MA_TOKEN = "mastodonTOKENgeheim4711"
MA = {"MASTODON_INSTANCE": "https://mastodon.social", "MASTODON_TOKEN": MA_TOKEN}
PNG1 = Medium("a.png", "image/png", b"\x89PNGeins", "bild")
PNG2 = Medium("b.png", "image/png", b"\x89PNGzwei", "bild")
VIDEO = Medium("v.mp4", "video/mp4", b"\x00\x00video", "video")


@pytest.fixture(autouse=True)
def rek(kanal_http):
    # Rekorder mit Riegel aus conftest.py: nie echtes Netz.
    return kanal_http


@pytest.fixture
def gewartet(monkeypatch):
    takte = []
    monkeypatch.setattr(kanal_adapter, "warten", takte.append)
    return takte


def _json(obj, status=200):
    return Antwort(status, {"Content-Type": "application/json"}, json.dumps(obj).encode())


def _session():
    return _json({"accessJwt": BS_JWT, "refreshJwt": "refreshJWTgeheim0815",
                  "did": BS_DID, "handle": "vibemind.bsky.social"})


def _blob(n):
    return _json({"blob": {"$type": "blob", "ref": {"$link": f"baf{n}"},
                           "mimeType": "image/png", "size": 8}})


def _record():
    return _json({"uri": BS_URI, "cid": "bafyrecord"})


# --- Bluesky: Facetten ----------------------------------------------------------

def test_bluesky_facetten_byteversatz():
    text = "Grüße #KünstlicheIntelligenz https://vibemind.de."
    facetten = kanal_adapter.bluesky_facetten(text)
    tags = [f for f in facetten if f["features"][0]["$type"] == "app.bsky.richtext.facet#tag"]
    links = [f for f in facetten if f["features"][0]["$type"] == "app.bsky.richtext.facet#link"]
    assert len(tags) == 1 and len(links) == 1
    assert tags[0]["index"]["byteStart"] == len("Grüße ".encode())
    assert tags[0]["index"]["byteEnd"] == len("Grüße #KünstlicheIntelligenz".encode())
    assert tags[0]["features"][0]["tag"] == "KünstlicheIntelligenz"
    assert links[0]["features"][0]["uri"] == "https://vibemind.de"
    assert links[0]["index"]["byteStart"] == len("Grüße #KünstlicheIntelligenz ".encode())
    assert links[0]["index"]["byteEnd"] == len(
        "Grüße #KünstlicheIntelligenz https://vibemind.de".encode())


def test_bluesky_facetten_anker_im_link_ist_kein_hashtag():
    facetten = kanal_adapter.bluesky_facetten("Siehe https://vibemind.de/#preise!")
    assert len(facetten) == 1
    assert facetten[0]["features"][0]["uri"] == "https://vibemind.de/#preise"


# --- Bluesky: Senden ------------------------------------------------------------

def test_bluesky_text_erfolg(rek):
    rek.vorrat += [_session(), _record()]
    text = "Hallo #Bluesky https://vibemind.de"
    beleg = kanal_adapter.senden_bluesky(BS, text, [], "", "d1")
    assert beleg == Beleg(BS_URI, "https://bsky.app/profile/vibemind.bsky.social/post/3kabc")
    assert len(rek.anfragen) == 2
    login, post = rek.anfragen
    assert login.url == "https://bsky.social/xrpc/com.atproto.server.createSession"
    assert json.loads(login.daten) == {"identifier": "vibemind.bsky.social",
                                       "password": BS_PASS}
    assert post.url == "https://bsky.social/xrpc/com.atproto.repo.createRecord"
    assert post.kopf["Authorization"] == f"Bearer {BS_JWT}"
    last = json.loads(post.daten)
    assert last["repo"] == BS_DID and last["collection"] == "app.bsky.feed.post"
    record = last["record"]
    assert record["$type"] == "app.bsky.feed.post"
    assert record["text"] == text
    assert record["langs"] == ["de"]
    assert record["createdAt"].endswith("Z")
    assert len(record["facets"]) == 2
    assert "embed" not in record


def test_bluesky_handle_mit_at_zeichen(rek):
    rek.vorrat += [_session(), _record()]
    zugang = {**BS, "BLUESKY_HANDLE": "@vibemind.bsky.social\r"}
    beleg = kanal_adapter.senden_bluesky(zugang, "x", [], "", "d1")
    assert beleg.url == "https://bsky.app/profile/vibemind.bsky.social/post/3kabc"
    assert json.loads(rek.anfragen[0].daten)["identifier"] == "vibemind.bsky.social"


def test_bluesky_bilder_alt_leer(rek):
    rek.vorrat += [_session(), _blob(1), _blob(2), _record()]
    kanal_adapter.senden_bluesky(BS, "Zwei Bilder", [PNG1, PNG2], "", "d1")
    uploads = [a for a in rek.anfragen if a.url.endswith("com.atproto.repo.uploadBlob")]
    assert len(uploads) == 2
    for a, medium in zip(uploads, [PNG1, PNG2]):
        assert a.kopf["Content-Type"] == "image/png"
        assert a.kopf["Authorization"] == f"Bearer {BS_JWT}"
        assert a.daten == medium.daten
    record = json.loads(rek.anfragen[-1].daten)["record"]
    assert record["embed"]["$type"] == "app.bsky.embed.images"
    bilder = record["embed"]["images"]
    assert [b["alt"] for b in bilder] == ["", ""]
    assert [b["image"]["ref"]["$link"] for b in bilder] == ["baf1", "baf2"]


def test_bluesky_login_401_dauerhaft_nichts_gepostet(rek):
    rek.vorrat.append(_json({"error": "AuthenticationRequired",
                             "message": f"Invalid password {BS_PASS} for vibemind.bsky.social"},
                            401))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_bluesky(BS, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 1
    assert BS_PASS not in str(e.value)
    assert "vibemind.bsky.social" not in str(e.value)
    assert "createSession" in str(e.value)


def test_bluesky_upload_fehler_dauerhaft(rek):
    rek.vorrat += [_session(), _json({"error": "x"}, 500)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_bluesky(BS, "x", [PNG1], "", "d1")
    assert e.value.art == "dauerhaft"
    assert len(rek.anfragen) == 2


def test_bluesky_createrecord_timeout_ungewiss(rek):
    rek.vorrat += [_session(), TimeoutError("timed out")]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_bluesky(BS, "x", [], "", "d1")
    assert e.value.art == "ungewiss"
    assert "createRecord" in str(e.value)


def test_bluesky_jwt_nie_im_fehlertext(rek):
    rek.vorrat += [_session(),
                   _json({"error": "InvalidRequest",
                          "message": f"bad token {BS_JWT} for {BS_DID}"}, 400)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_bluesky(BS, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert BS_JWT not in str(e.value)
    assert BS_PASS not in str(e.value)


def test_bluesky_antwort_ohne_uri_ungewiss(rek):
    rek.vorrat += [_session(), _json({"cid": "x"})]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_bluesky(BS, "x", [], "", "d1")
    assert e.value.art == "ungewiss"


# --- Mastodon -------------------------------------------------------------------

def _status(kennung="111", url="https://mastodon.social/@vibemind/111"):
    return _json({"id": kennung, "url": url})


def test_mastodon_text_erfolg_mit_idempotenz(rek):
    rek.vorrat.append(_status())
    beleg = kanal_adapter.senden_mastodon(MA, "Hallo #Fediverse", [], "", "schluessel-d1")
    assert beleg == Beleg("111", "https://mastodon.social/@vibemind/111")
    assert len(rek.anfragen) == 1
    a = rek.anfragen[0]
    assert a.methode == "POST"
    assert a.url == "https://mastodon.social/api/v1/statuses"
    assert a.kopf["Idempotency-Key"] == "schluessel-d1"
    assert a.kopf["Authorization"] == f"Bearer {MA_TOKEN}"
    assert json.loads(a.daten) == {"status": "Hallo #Fediverse", "media_ids": [],
                                   "visibility": "public"}


def test_mastodon_instanz_ohne_schema(rek):
    rek.vorrat.append(_status())
    kanal_adapter.senden_mastodon({**MA, "MASTODON_INSTANCE": "mastodon.social"},
                                  "x", [], "", "d1")
    assert rek.anfragen[0].url.startswith("https://mastodon.social/")


def test_mastodon_bild_sofort_fertig(rek, gewartet):
    rek.vorrat += [_json({"id": "m7", "url": "https://files/m7.png"}), _status()]
    kanal_adapter.senden_mastodon(MA, "Bild", [PNG1], "", "d1")
    upload, post = rek.anfragen
    assert upload.url == "https://mastodon.social/api/v2/media"
    assert upload.kopf["Authorization"] == f"Bearer {MA_TOKEN}"
    assert upload.kopf["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="a.png"' in upload.daten
    assert b'name="description"\r\n\r\n\r\n' in upload.daten
    assert json.loads(post.daten)["media_ids"] == ["m7"]
    assert gewartet == []


def test_mastodon_video_wartet_auf_verarbeitung(rek, gewartet):
    rek.vorrat += [_json({"id": "m1", "url": None}, 202),
                   _json({"id": "m1", "url": None}, 206),
                   _json({"id": "m1", "url": "https://files/m1.mp4"}),
                   _status()]
    beleg = kanal_adapter.senden_mastodon(MA, "Video", [VIDEO], "", "d1")
    assert beleg.beitrag == "111"
    urls = [a.url for a in rek.anfragen]
    assert urls == ["https://mastodon.social/api/v2/media",
                    "https://mastodon.social/api/v1/media/m1",
                    "https://mastodon.social/api/v1/media/m1",
                    "https://mastodon.social/api/v1/statuses"]
    assert [a.methode for a in rek.anfragen[1:3]] == ["GET", "GET"]
    assert json.loads(rek.anfragen[-1].daten)["media_ids"] == ["m1"]
    assert gewartet == [kanal_adapter.MASTODON_MEDIEN_TAKT_S] * 2


def test_mastodon_verarbeitung_frist_dauerhaft(rek, gewartet):
    runden = kanal_adapter.MASTODON_MEDIEN_FRIST_S // kanal_adapter.MASTODON_MEDIEN_TAKT_S
    rek.vorrat.append(_json({"id": "m1", "url": None}, 202))
    rek.vorrat += [_json({"id": "m1", "url": None}, 206) for _ in range(runden)]
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_mastodon(MA, "Video", [VIDEO], "", "d1")
    assert e.value.art == "dauerhaft"
    assert not any(a.url.endswith("/statuses") for a in rek.anfragen)
    assert sum(gewartet) <= kanal_adapter.MASTODON_MEDIEN_FRIST_S
    assert rek.vorrat == []


def test_mastodon_422_dauerhaft_ohne_token(rek):
    rek.vorrat.append(_json({"error": f"Validation failed, token {MA_TOKEN} "
                                      f"on https://mastodon.social"}, 422))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_mastodon(MA, "x", [], "", "d1")
    assert e.value.art == "dauerhaft"
    assert MA_TOKEN not in str(e.value)
    assert "mastodon.social" not in str(e.value)


def test_mastodon_statuses_503_ungewiss(rek):
    rek.vorrat.append(_json({"error": "down"}, 503))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_mastodon(MA, "x", [], "", "d1")
    assert e.value.art == "ungewiss"


def test_mastodon_antwort_ohne_id_ungewiss(rek):
    rek.vorrat.append(_json({"url": "x"}))
    with pytest.raises(KanalFehler) as e:
        kanal_adapter.senden_mastodon(MA, "x", [], "", "d1")
    assert e.value.art == "ungewiss"


# --- Registry -------------------------------------------------------------------

def test_sender_fuer_jeden_kanal():
    assert set(kanal_adapter.SENDER) == set(kanaele.KANAELE)
