"""Adapter je Kanal: senden_<kanal>(zugang, text, medien, titel, schluessel)
-> Beleg (Spec 2026-10-24-kanaele-posten).

Jeder Adapter uebersetzt nur zwischen unserem Vokabular und dem des
Anbieters. Freigabe, Grenzen, Kadenz und Buchung liegen im Dienst
(kanal_dispatch.py). Netz nur ueber kanal_api.json_ruf; Fehler sind immer
kanal_api.KanalFehler mit Schritt statt URL und ohne Geheimnisse.

Einziger veroeffentlichender Aufruf je Adapter ist der letzte
(`veroeffentlicht=True`). Vorbereitende Lesezugriffe (Discord-Webhook)
sind bei jedem Fehler dauerhaft: es ist sicher nichts entstanden.
"""
import json
from typing import Mapping

import kanal_api
from kanaele import KANAELE
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
                       datei: tuple[str, str, str, bytes]) -> Anfrage:
    rumpf, content_type = kanal_api.multipart(felder, [datei])
    return Anfrage("POST", url, {"Content-Type": content_type}, rumpf,
                   kanal_api.FRIST_UPLOAD)


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
    "telegram_kanal": senden_telegram_kanal,
    "discord": senden_discord,
    "devto": senden_devto,
}
assert set(SENDER) <= set(KANAELE)
