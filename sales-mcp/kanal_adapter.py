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
import struct
import time
import urllib.parse
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


# --- YouTube (Shorts) ---------------------------------------------------------------

YOUTUBE_TOKEN = "https://oauth2.googleapis.com/token"
YOUTUBE_KANAL = "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true"
YOUTUBE_HOCHLADEN = ("https://www.googleapis.com/upload/youtube/v3/videos"
                     "?uploadType=resumable&part=snippet,status")
YOUTUBE_SHORT_MAX_S = 180
YOUTUBE_BESCHREIBUNG_MAX_BYTES = 5000
# Kategorie "Wissenschaft & Technik".
YOUTUBE_KATEGORIE = "28"
_YOUTUBE_SICHTBARKEIT = ("private", "unlisted", "public")


def youtube_sichtbarkeit() -> str:
    """privacyStatus aus YOUTUBE_SICHTBARKEIT (nicht geheim, je Aufruf frisch
    gelesen). Leer oder unbekannt = private: als Sicherung, bis der Betreiber
    ausdruecklich unlisted oder public eintraegt."""
    wert = (os.environ.get("YOUTUBE_SICHTBARKEIT") or "").strip().lower()
    return wert if wert in _YOUTUBE_SICHTBARKEIT else "private"


def _mp4_boxen(daten: bytes, start: int, ende: int):
    """(typ, inhalt_von, inhalt_bis) der Boxen in daten[start:ende]. Eine
    Box, deren Groesse nicht passt, beendet die Suche (kein Haenger)."""
    pos = start
    while pos + 8 <= ende:
        groesse, typ = struct.unpack_from(">I4s", daten, pos)
        kopf = 8
        if groesse == 1:
            if pos + 16 > ende:
                return
            groesse, kopf = struct.unpack_from(">Q", daten, pos + 8)[0], 16
        elif groesse == 0:
            groesse = ende - pos
        if groesse < kopf or pos + groesse > ende:
            return
        yield typ, pos + kopf, pos + groesse
        pos += groesse


def mp4_eckdaten(daten: bytes) -> tuple[float, int, int] | None:
    """(Sekunden, Breite, Hoehe) aus moov/mvhd und dem ersten tkhd mit
    Bildgroesse; None, wenn das kein lesbares MP4 ist. Eine Drehmatrix wird
    nicht ausgewertet - die Reels rendert Laura ohne."""
    try:
        moov = next(((a, b) for t, a, b in _mp4_boxen(daten, 0, len(daten))
                     if t == b"moov"), None)
        if moov is None:
            return None
        sekunden, breite, hoehe = None, 0, 0
        for typ, a, b in _mp4_boxen(daten, *moov):
            if typ == b"mvhd":
                if daten[a] == 1:
                    zeitbasis, dauer = struct.unpack_from(">IQ", daten, a + 20)
                else:
                    zeitbasis, dauer = struct.unpack_from(">II", daten, a + 12)
                if zeitbasis:
                    sekunden = dauer / zeitbasis
            elif typ == b"trak" and not breite:
                for typ2, a2, b2 in _mp4_boxen(daten, a, b):
                    versatz = 88 if typ2 == b"tkhd" and daten[a2] == 1 else 76
                    if typ2 == b"tkhd" and a2 + versatz + 8 <= b2:
                        w, h = struct.unpack_from(">II", daten, a2 + versatz)
                        if w >> 16 and h >> 16:
                            breite, hoehe = w >> 16, h >> 16
    except (struct.error, IndexError):
        return None
    if sekunden is None or not breite:
        return None
    return sekunden, breite, hoehe


def _ohne_spitze_klammern(text: str) -> str:
    # YouTube lehnt "<" und ">" in Titel und Beschreibung ab.
    return text.replace("<", "‹").replace(">", "›")


def _kopf(antwort: kanal_api.Antwort, name: str) -> str | None:
    for k, v in antwort.kopf.items():
        if k.lower() == name.lower():
            return v
    return None


def senden_youtube(zugang: Mapping[str, str], text: str,
                   medien: list[Medium], titel: str, schluessel: str) -> Beleg:
    """Ein Reel als Short: MP4 pruefen (hochkant/quadratisch, <= 3 min),
    Zugriffsschluessel per Refresh-Token, Kanal pruefen (gehoert der Zugang
    zu YOUTUBE_CHANNEL_ID?), resumable Upload starten, Video in EINEM PUT
    hochladen. Nur der PUT veroeffentlicht; alles davor ist dauerhaft.
    YouTube kennt keinen Idempotenzschluessel - die Sperre gegen Doppel
    liegt allein im Dienst. Sichtbarkeit: youtube_sichtbarkeit()."""
    kanal = "youtube"
    if len(medien) != 1 or medien[0].art != "video":
        raise KanalFehler("YouTube: genau ein Video nötig – hochgeladen wurde nichts")
    medium = medien[0]
    eckdaten = mp4_eckdaten(medium.daten)
    if eckdaten is None:
        raise KanalFehler(f"YouTube: {medium.name} ist als MP4 nicht lesbar (Dauer "
                          f"oder Bildgröße fehlen) – hochgeladen wurde nichts")
    sekunden, breite, hoehe = eckdaten
    if sekunden > YOUTUBE_SHORT_MAX_S:
        raise KanalFehler(f"YouTube: das Video dauert {sekunden:.0f} s, ein Short "
                          f"höchstens 3 Minuten – hochgeladen wurde nichts")
    if breite > hoehe:
        raise KanalFehler(f"YouTube: das Video ist quer ({breite}x{hoehe}), ein Short "
                          f"ist hochkant oder quadratisch – hochgeladen wurde nichts")
    beschreibung = _ohne_spitze_klammern(text)
    if len(beschreibung.encode("utf-8")) > YOUTUBE_BESCHREIBUNG_MAX_BYTES:
        raise KanalFehler(f"YouTube: die Beschreibung hat mehr als "
                          f"{YOUTUBE_BESCHREIBUNG_MAX_BYTES} Bytes – hochgeladen "
                          f"wurde nichts")

    client_id = (zugang.get("YOUTUBE_CLIENT_ID") or "").strip()
    kanal_id = (zugang.get("YOUTUBE_CHANNEL_ID") or "").strip()
    # Client-ID und Kanal-ID sind nicht geheim, sollen aber nie in UI/Log.
    geheim = _geheimnisse(kanal, zugang) + [client_id, kanal_id]
    token = kanal_api.json_ruf(
        Anfrage("POST", YOUTUBE_TOKEN,
                {"Content-Type": "application/x-www-form-urlencoded"},
                urllib.parse.urlencode({
                    "grant_type": "refresh_token", "client_id": client_id,
                    "client_secret": (zugang.get("YOUTUBE_CLIENT_SECRET") or "").strip(),
                    "refresh_token": (zugang.get("YOUTUBE_REFRESH_TOKEN") or "").strip(),
                }).encode("ascii"), kanal_api.FRIST_JSON),
        kanal=kanal, was="Anmeldung", veroeffentlicht=False, geheimnisse=geheim)
    zugriff = token.get("access_token")
    if not isinstance(zugriff, str) or not zugriff:
        raise KanalFehler("YouTube: Anmeldung ohne Zugriffsschlüssel – hochgeladen "
                          "wurde nichts")
    geheim.append(zugriff)
    auth = {"Authorization": f"Bearer {zugriff}"}

    # Ein Token des persoenlichen Kanals statt der Marke wuerde sonst
    # klaglos dort hochladen.
    eigene = kanal_api.json_ruf(
        Anfrage("GET", YOUTUBE_KANAL, dict(auth), None, kanal_api.FRIST_JSON),
        kanal=kanal, was="Kanal prüfen", veroeffentlicht=False, geheimnisse=geheim)
    eintraege = eigene.get("items")
    kennungen = ([e.get("id") for e in eintraege if isinstance(e, dict)]
                 if isinstance(eintraege, list) else [])
    if kanal_id not in kennungen:
        raise KanalFehler("YouTube: der Zugang gehört zu einem anderen Kanal als "
                          "YOUTUBE_CHANNEL_ID – hochgeladen wurde nichts")

    meta = {"snippet": {"title": _ohne_spitze_klammern(titel.strip()),
                        "description": beschreibung,
                        "categoryId": YOUTUBE_KATEGORIE,
                        "defaultLanguage": "de", "defaultAudioLanguage": "de"},
            # Reels sprechen mit KI-Stimme: Offenlegung als KI-Inhalt.
            "status": {"privacyStatus": youtube_sichtbarkeit(),
                       "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True}}
    start = kanal_api.ruf(
        Anfrage("POST", YOUTUBE_HOCHLADEN,
                {**auth, "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": medium.mimetyp,
                 "X-Upload-Content-Length": str(len(medium.daten))},
                json.dumps(meta, ensure_ascii=False).encode("utf-8"),
                kanal_api.FRIST_JSON),
        kanal=kanal, was="Hochladen vorbereiten", veroeffentlicht=False,
        geheimnisse=geheim)
    ziel = (_kopf(start, "Location") or "").strip()
    if not ziel.startswith("https://"):
        raise KanalFehler("YouTube: Hochladen vorbereiten ohne Upload-Adresse – "
                          "hochgeladen wurde nichts")
    # Die Upload-Adresse traegt die Sitzung: wie ein Schluessel behandeln.
    geheim += [ziel] + urllib.parse.parse_qs(
        urllib.parse.urlsplit(ziel).query).get("upload_id", [])

    video = kanal_api.json_ruf(
        Anfrage("PUT", ziel, {**auth, "Content-Type": medium.mimetyp}, medium.daten,
                kanal_api.FRIST_UPLOAD),
        kanal=kanal, was="Video hochladen", veroeffentlicht=True, geheimnisse=geheim)
    kennung = video.get("id")
    if not isinstance(kennung, str) or not kennung:
        raise KanalFehler("YouTube: Antwort ohne lesbare Kennung bei Video hochladen",
                          ungewiss=True)
    return Beleg(kennung, f"https://youtube.com/shorts/{kennung}")


SENDER: dict[str, Sender] = {
    "bluesky": senden_bluesky,
    "mastodon": senden_mastodon,
    "telegram_kanal": senden_telegram_kanal,
    "discord": senden_discord,
    "devto": senden_devto,
    "youtube": senden_youtube,
}
assert set(SENDER) == set(KANAELE)
