"""Adapter je Kanal: senden_<kanal>(zugang, text, medien, titel, schluessel)
-> Beleg (Spec 2026-10-24-kanaele-posten).

Jeder Adapter uebersetzt nur zwischen unserem Vokabular und dem des
Anbieters. Freigabe, Grenzen, Kadenz und Buchung liegen im Dienst
(kanal_dispatch.py). Netz nur ueber kanal_api.json_ruf/ruf; Fehler sind immer
kanal_api.KanalFehler mit Schritt statt URL und ohne Geheimnisse.

Einziger veroeffentlichender Aufruf je Adapter ist der letzte
(`veroeffentlicht=True`). Vorbereitende Lesezugriffe (Discord-Webhook)
sind bei jedem Fehler dauerhaft: es ist sicher nichts entstanden.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Mapping

import kanal_api
from kanaele import KANAELE, instanz_normalisieren
from kanal_api import Anfrage, Beleg, KanalFehler, Medium, Sender


def _geheimnisse(kanal: str, zugang: Mapping[str, str]) -> list[str]:
    return [(zugang.get(n) or "").strip() for n in KANAELE[kanal].geheim_namen]


def _hoechstens_ein_medium(kanal: str, medien: list[Medium]) -> Medium | None:
    if len(medien) > 1:
        raise KanalFehler(f"{KANAELE[kanal].anzeige}: höchstens ein Medium erlaubt")
    return medien[0] if medien else None


def _json_anfrage(url: str, last: dict, kopf: Mapping[str, str] | None = None) -> Anfrage:
    return Anfrage("POST", url, {"Content-Type": "application/json", **(kopf or {})},
                   json.dumps(last).encode("utf-8"), kanal_api.FRIST_JSON)


def _multipart_anfrage(url: str, felder: Mapping[str, str],
                       datei: tuple[str, str, str, bytes],
                       kopf: Mapping[str, str] | None = None) -> Anfrage:
    rumpf, content_type = kanal_api.multipart(felder, [datei])
    return Anfrage("POST", url, {"Content-Type": content_type, **(kopf or {})}, rumpf,
                   kanal_api.FRIST_UPLOAD)


# Austauschbar fuer Tests (Warten auf die Mastodon-Medienverarbeitung).
warten = time.sleep


# --- Bluesky ----------------------------------------------------------------------

# Nicht geheim und optional, steht deshalb nicht in env_namen.
BLUESKY_PDS = os.environ.get("BLUESKY_PDS", "https://bsky.social")

_LINK = re.compile(r"https?://\S+")
_HASHTAG = re.compile(r"(?<!\w)#([^\s#.,;:!?()]+)")
_LINK_ENDE = ".,;:!?)"


def _byte(text: str, zeichen: int) -> int:
    return len(text[:zeichen].encode("utf-8"))


def _facette(text: str, start: int, ende: int, merkmal: dict) -> dict:
    return {"index": {"byteStart": _byte(text, start), "byteEnd": _byte(text, ende)},
            "features": [merkmal]}


def bluesky_facetten(text: str) -> list[dict]:
    """Links und Hashtags als app.bsky.richtext.facet. Bluesky zaehlt in
    UTF-8-Bytes, nicht in Zeichen. Satzzeichen am Linkende gehoeren nicht
    zum Link; ein `#` innerhalb eines Links (Anker) ist kein Hashtag."""
    facetten: list[tuple[int, dict]] = []
    links: list[tuple[int, int]] = []
    for m in _LINK.finditer(text):
        uri = m.group(0).rstrip(_LINK_ENDE)
        if uri.endswith("://"):
            continue
        start, ende = m.start(), m.start() + len(uri)
        links.append((start, ende))
        facetten.append((start, _facette(text, start, ende, {
            "$type": "app.bsky.richtext.facet#link", "uri": uri})))
    for m in _HASHTAG.finditer(text):
        start, ende = m.start(), m.end()
        if any(a <= start < b for a, b in links):
            continue
        facetten.append((start, _facette(text, start, ende, {
            "$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)})))
    return [f for _, f in sorted(facetten, key=lambda x: x[0])]


def _jetzt_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def senden_bluesky(zugang: Mapping[str, str], text: str,
                   medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """createSession -> je Bild uploadBlob -> createRecord. Nur createRecord
    veroeffentlicht; Login und Upload sind bei jedem Fehler dauerhaft."""
    kanal = "bluesky"
    handle = (zugang.get("BLUESKY_HANDLE") or "").strip()
    handle = handle[1:] if handle.startswith("@") else handle
    passwort = (zugang.get("BLUESKY_APP_PASSWORD") or "").strip()
    # Handle ist nicht geheim, soll aber nie in Fehlertexten (UI/Log) stehen.
    geheim = _geheimnisse(kanal, zugang) + [handle]
    xrpc = BLUESKY_PDS.strip().rstrip("/") + "/xrpc"
    if any(m.art != "bild" for m in medien):
        raise KanalFehler("Bluesky: nur Bilder möglich, kein Video")

    sitzung = kanal_api.json_ruf(
        _json_anfrage(f"{xrpc}/com.atproto.server.createSession",
                      {"identifier": handle, "password": passwort}),
        kanal=kanal, was="createSession", veroeffentlicht=False, geheimnisse=geheim)
    jwt, did = sitzung.get("accessJwt"), sitzung.get("did")
    # Ab hier sind die Sitzungsschluessel Geheimnisse wie das Passwort.
    geheim += [w for w in (jwt, sitzung.get("refreshJwt")) if isinstance(w, str)]
    if not isinstance(jwt, str) or not jwt or not isinstance(did, str) or not did:
        raise KanalFehler("Bluesky: Anmeldung ohne Sitzung bei createSession – "
                          "veröffentlicht wurde nichts")
    auth = {"Authorization": f"Bearer {jwt}"}

    bilder = []
    for medium in medien:
        hochgeladen = kanal_api.json_ruf(
            Anfrage("POST", f"{xrpc}/com.atproto.repo.uploadBlob",
                    {"Content-Type": medium.mimetyp, **auth}, medium.daten,
                    kanal_api.FRIST_UPLOAD),
            kanal=kanal, was="uploadBlob", veroeffentlicht=False, geheimnisse=geheim)
        blob = hochgeladen.get("blob")
        if not isinstance(blob, dict):
            raise KanalFehler("Bluesky: Upload ohne Blob bei uploadBlob – "
                              "veröffentlicht wurde nichts")
        bilder.append({"alt": "", "image": blob})

    record: dict = {"$type": "app.bsky.feed.post", "text": text,
                    "createdAt": _jetzt_utc(), "facets": bluesky_facetten(text),
                    "langs": ["de"]}
    if bilder:
        record["embed"] = {"$type": "app.bsky.embed.images", "images": bilder}
    antwort = kanal_api.json_ruf(
        _json_anfrage(f"{xrpc}/com.atproto.repo.createRecord",
                      {"repo": did, "collection": "app.bsky.feed.post",
                       "record": record}, auth),
        kanal=kanal, was="createRecord", veroeffentlicht=True, geheimnisse=geheim)
    uri = antwort.get("uri")
    if not isinstance(uri, str) or not uri.startswith("at://"):
        raise KanalFehler("Bluesky: Antwort ohne lesbare Kennung bei createRecord",
                          ungewiss=True)
    rkey = uri.rstrip("/").rsplit("/", 1)[-1]
    return Beleg(uri, f"https://bsky.app/profile/{handle}/post/{rkey}")


# --- Mastodon ---------------------------------------------------------------------

MASTODON_MEDIEN_FRIST_S = 240
MASTODON_MEDIEN_TAKT_S = 5


def _mastodon_medium(basis: str, auth: Mapping[str, str], medium: Medium,
                     geheim: list[str]) -> str:
    """POST /api/v2/media, bei 202 bzw. url=None warten bis verarbeitet.
    Nichts hiervon veroeffentlicht; Fristablauf ist dauerhaft."""
    kanal = "mastodon"
    antwort = kanal_api.ruf(
        _multipart_anfrage(f"{basis}/api/v2/media", {"description": ""},
                           ("file", medium.name, medium.mimetyp, medium.daten), auth),
        kanal=kanal, was="Medium hochladen", veroeffentlicht=False, geheimnisse=geheim)
    try:
        daten = json.loads(antwort.rumpf.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        daten = None
    kennung = daten.get("id") if isinstance(daten, dict) else None
    if not isinstance(kennung, str) or not kennung:
        raise KanalFehler("Mastodon: Antwort ohne lesbare Kennung bei Medium hochladen "
                          "– veröffentlicht wurde nichts")
    if antwort.status != 202 and daten.get("url") is not None:
        return kennung
    for _ in range(MASTODON_MEDIEN_FRIST_S // MASTODON_MEDIEN_TAKT_S):
        warten(MASTODON_MEDIEN_TAKT_S)
        stand = kanal_api.json_ruf(
            Anfrage("GET", f"{basis}/api/v1/media/{kennung}", dict(auth), None,
                    kanal_api.FRIST_JSON),
            kanal=kanal, was="Medium prüfen", veroeffentlicht=False, geheimnisse=geheim)
        if stand.get("url") is not None:
            return kennung
    raise KanalFehler(f"Mastodon: Medium nach {MASTODON_MEDIEN_FRIST_S} s noch nicht "
                      f"verarbeitet – veröffentlicht wurde nichts")


def senden_mastodon(zugang: Mapping[str, str], text: str,
                    medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """Je Medium Upload (+ Warten auf Verarbeitung), dann POST /api/v1/statuses
    mit Idempotency-Key = schluessel (Mastodon verwirft Doppel)."""
    kanal = "mastodon"
    basis = instanz_normalisieren(zugang.get("MASTODON_INSTANCE") or "")
    token = (zugang.get("MASTODON_TOKEN") or "").strip()
    # Instanz ist nicht geheim, soll aber nie in Fehlertexten (UI/Log) stehen.
    geheim = _geheimnisse(kanal, zugang) + [basis, basis.split("://", 1)[-1]]
    auth = {"Authorization": f"Bearer {token}"}
    media_ids = [_mastodon_medium(basis, auth, m, geheim) for m in medien]
    antwort = kanal_api.json_ruf(
        _json_anfrage(f"{basis}/api/v1/statuses",
                      {"status": text, "media_ids": media_ids, "visibility": "public"},
                      {**auth, "Idempotency-Key": schluessel}),
        kanal=kanal, was="Status veröffentlichen", veroeffentlicht=True,
        geheimnisse=geheim)
    kennung = antwort.get("id")
    if not isinstance(kennung, str) or not kennung:
        raise KanalFehler("Mastodon: Antwort ohne lesbare Kennung bei Status "
                          "veröffentlichen", ungewiss=True)
    url = antwort.get("url")
    return Beleg(kennung, url if isinstance(url, str) else "")


# --- Telegram-Kanal -------------------------------------------------------------

def _telegram_url(chat_id: str, chat: Mapping, beitrag: str) -> str:
    username = chat.get("username") if isinstance(chat, Mapping) else None
    if isinstance(username, str) and username:
        return f"https://t.me/{username}/{beitrag}"
    if chat_id.startswith("@"):
        return f"https://t.me/{chat_id[1:]}/{beitrag}"
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{beitrag}"
    return ""


def senden_telegram_kanal(zugang: Mapping[str, str], text: str,
                          medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """sendMessage (nur Text) oder sendPhoto/sendVideo mit dem Text als
    caption. Der Bot muss Admin im Kanal sein."""
    kanal = "telegram_kanal"
    token = (zugang.get("TELEGRAM_KANAL_BOT_TOKEN") or "").strip()
    chat_id = (zugang.get("TELEGRAM_KANAL_ID") or "").strip()
    geheim = _geheimnisse(kanal, zugang)
    basis = f"https://api.telegram.org/bot{token}"
    medium = _hoechstens_ein_medium(kanal, medien)
    if medium is None:
        was = "sendMessage"
        anfrage = _json_anfrage(f"{basis}/{was}", {"chat_id": chat_id, "text": text})
    else:
        was, feld = ("sendPhoto", "photo") if medium.art == "bild" else ("sendVideo", "video")
        anfrage = _multipart_anfrage(f"{basis}/{was}", {"chat_id": chat_id, "caption": text},
                                     (feld, medium.name, medium.mimetyp, medium.daten))
    antwort = kanal_api.json_ruf(anfrage, kanal=kanal, was=was,
                                 veroeffentlicht=True, geheimnisse=geheim)
    ergebnis = antwort.get("result")
    kennung = ergebnis.get("message_id") if isinstance(ergebnis, dict) else None
    if antwort.get("ok") is not True or not isinstance(kennung, int):
        raise KanalFehler(f"Telegram-Kanal: Antwort ohne lesbare Kennung bei {was}",
                          ungewiss=True)
    beitrag = str(kennung)
    return Beleg(beitrag, _telegram_url(chat_id, ergebnis.get("chat") or {}, beitrag))


# --- Discord (Webhook) ------------------------------------------------------------

def senden_discord(zugang: Mapping[str, str], text: str,
                   medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """Erst GET <webhook> (guild_id/channel_id fuer den Link, veroeffentlicht
    nichts), dann POST <webhook>?wait=true. allowed_mentions parse=[]: auch
    @everyone/@here im Text pingt niemanden."""
    kanal = "discord"
    webhook = (zugang.get("DISCORD_ANKUENDIGUNG_WEBHOOK") or "").strip()
    geheim = _geheimnisse(kanal, zugang) + [webhook.rstrip("/").rsplit("/", 1)[-1]]
    medium = _hoechstens_ein_medium(kanal, medien)

    info = kanal_api.json_ruf(
        Anfrage("GET", webhook, {}, None, kanal_api.FRIST_JSON),
        kanal=kanal, was="Webhook lesen", veroeffentlicht=False, geheimnisse=geheim)
    guild_id, channel_id = info.get("guild_id"), info.get("channel_id")
    if not guild_id or not channel_id:
        raise KanalFehler("Discord: Webhook ohne Server oder Kanal – veröffentlicht "
                          "wurde nichts")

    last = {"content": text, "allowed_mentions": {"parse": []}}
    ziel = f"{webhook}?wait=true"
    if medium is None:
        anfrage = _json_anfrage(ziel, last)
    else:
        anfrage = _multipart_anfrage(ziel, {"payload_json": json.dumps(last)},
                                     ("files[0]", medium.name, medium.mimetyp, medium.daten))
    nachricht = kanal_api.json_ruf(anfrage, kanal=kanal, was="Nachricht senden",
                                   veroeffentlicht=True, geheimnisse=geheim)
    kennung = nachricht.get("id")
    if not isinstance(kennung, str) or not kennung:
        raise KanalFehler("Discord: Antwort ohne lesbare Kennung bei Nachricht senden",
                          ungewiss=True)
    return Beleg(kennung, f"https://discord.com/channels/{guild_id}/{channel_id}/{kennung}")


# --- dev.to -----------------------------------------------------------------------

DEVTO_ARTIKEL = "https://dev.to/api/articles"


def senden_devto(zugang: Mapping[str, str], text: str,
                 medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """Legt den Artikel IMMER als Entwurf an (published: false); veroeffentlicht
    wird er erst von Hand bei dev.to."""
    kanal = "devto"
    if medien:
        raise KanalFehler("dev.to: Medien sind hier nicht möglich")
    schluessel_api = (zugang.get("DEVTO_API_KEY") or "").strip()
    anfrage = _json_anfrage(
        DEVTO_ARTIKEL,
        {"article": {"title": titel, "body_markdown": text, "published": False}},
        {"api-key": schluessel_api, "Accept": "application/vnd.forem.api-v1+json"})
    antwort = kanal_api.json_ruf(anfrage, kanal=kanal, was="Artikel anlegen",
                                 veroeffentlicht=True,
                                 geheimnisse=_geheimnisse(kanal, zugang))
    kennung = antwort.get("id")
    if isinstance(kennung, bool) or not isinstance(kennung, (int, str)) or kennung == "":
        raise KanalFehler("dev.to: Antwort ohne lesbare Kennung bei Artikel anlegen",
                          ungewiss=True)
    url = antwort.get("url")
    return Beleg(str(kennung), url if isinstance(url, str) else "")


SENDER: dict[str, Sender] = {
    "bluesky": senden_bluesky,
    "mastodon": senden_mastodon,
    "telegram_kanal": senden_telegram_kanal,
    "discord": senden_discord,
    "devto": senden_devto,
}
assert set(SENDER) == set(KANAELE)
