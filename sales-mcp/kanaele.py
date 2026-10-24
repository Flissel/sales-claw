"""Kanal-Registry fuer eigene Beitraege (Spec docs/superpowers/specs/
2026-10-24-kanaele-posten-design.md): Bluesky, Mastodon, Telegram-Kanal,
Discord, dev.to.

Dieses Modul haelt nur Metadaten (Grenzen, Medien, Kadenz, Env-NAMEN) und
liest/schreibt die Tabelle kanal_status. Es macht keinen Netzaufruf und
kennt keinen Zugangswert ausser dem, den man ihm zum Pruefen reicht.
server.py, ui.py und ui_reels.py importieren nur dieses Modul und erfahren
"verbunden" allein aus kanal_status (Praezisierung 1) - die Zugaenge kennt
nur der Dienst sales-kanaele.

Fehlertexte nennen nur NAMEN (z. B. "MASTODON_INSTANCE hat kein gueltiges
Format"), nie Werte: auch Handle, Instanz und Kanal-ID landen nie in UI
oder Log.
"""
import re
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import psycopg

MEDIUM_ART = Literal["bild", "video"]

MIB = 1024 * 1024
FEHLER_MAX = 300


@dataclass(frozen=True)
class KanalInfo:
    name: str
    anzeige: str
    env_namen: tuple[str, ...]
    geheim_namen: tuple[str, ...]
    max_zeichen: int
    max_zeichen_mit_medien: int
    bilder_max: int
    video_max: int
    medien_max: int
    bild_max_bytes: int
    video_max_bytes: int
    kadenz_pro_tag: int
    titel_pflicht: bool
    titel_max: int
    hashtags: bool


# Reihenfolge = Reihenfolge in UI, Freigabe und Dienst.
KANAELE: dict[str, KanalInfo] = {
    "bluesky": KanalInfo(
        name="bluesky", anzeige="Bluesky",
        env_namen=("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"),
        geheim_namen=("BLUESKY_APP_PASSWORD",),
        max_zeichen=300, max_zeichen_mit_medien=300,
        bilder_max=4, video_max=0, medien_max=4,
        bild_max_bytes=1_000_000, video_max_bytes=0,
        kadenz_pro_tag=3, titel_pflicht=False, titel_max=0, hashtags=True),
    "mastodon": KanalInfo(
        name="mastodon", anzeige="Mastodon",
        env_namen=("MASTODON_INSTANCE", "MASTODON_TOKEN"),
        geheim_namen=("MASTODON_TOKEN",),
        max_zeichen=500, max_zeichen_mit_medien=500,
        bilder_max=4, video_max=1, medien_max=4,
        bild_max_bytes=16 * MIB, video_max_bytes=40 * MIB,
        kadenz_pro_tag=3, titel_pflicht=False, titel_max=0, hashtags=True),
    "telegram_kanal": KanalInfo(
        name="telegram_kanal", anzeige="Telegram-Kanal",
        env_namen=("TELEGRAM_KANAL_ID", "TELEGRAM_KANAL_BOT_TOKEN"),
        geheim_namen=("TELEGRAM_KANAL_BOT_TOKEN",),
        max_zeichen=4096, max_zeichen_mit_medien=1024,
        bilder_max=1, video_max=1, medien_max=1,
        bild_max_bytes=10 * MIB, video_max_bytes=50 * MIB,
        kadenz_pro_tag=3, titel_pflicht=False, titel_max=0, hashtags=False),
    "discord": KanalInfo(
        name="discord", anzeige="Discord",
        env_namen=("DISCORD_ANKUENDIGUNG_WEBHOOK",),
        geheim_namen=("DISCORD_ANKUENDIGUNG_WEBHOOK",),
        max_zeichen=2000, max_zeichen_mit_medien=2000,
        bilder_max=1, video_max=1, medien_max=1,
        bild_max_bytes=10 * MIB, video_max_bytes=10 * MIB,
        kadenz_pro_tag=3, titel_pflicht=False, titel_max=0, hashtags=False),
    # dev.to: Beitrag wird dort nur als Entwurf angelegt (published: false),
    # zunaechst ohne Bilder (gehen nur als oeffentliche URL, Praezisierung 8).
    "devto": KanalInfo(
        name="devto", anzeige="dev.to",
        env_namen=("DEVTO_API_KEY",),
        geheim_namen=("DEVTO_API_KEY",),
        max_zeichen=100_000, max_zeichen_mit_medien=100_000,
        bilder_max=0, video_max=0, medien_max=0,
        bild_max_bytes=0, video_max_bytes=0,
        kadenz_pro_tag=1, titel_pflicht=True, titel_max=128, hashtags=False),
}


# --- Zugaenge (nur Formpruefung, nie Werte im Text) -------------------------

_INSTANZ = re.compile(r"^https://[a-z0-9.-]+\.[a-z]{2,}/?$")
_TELEGRAM_ID = re.compile(r"^(@[A-Za-z0-9_]{5,32}|-100[0-9]{5,15})$")
_DISCORD_WEBHOOK = re.compile(
    r"^https://(discord|discordapp)\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$")


def zugang_lesen(info: KanalInfo, env: Mapping[str, str]) -> dict[str, str]:
    """Liest die Env-Werte des Kanals; strip() nimmt Leerzeichen und ein
    Windows-Zeilenende (\\r) aus einer .env-Datei mit."""
    return {n: (env.get(n, "") or "").strip() for n in info.env_namen}


def instanz_normalisieren(wert: str) -> str:
    """Mastodon-Instanz als `https://host` ohne Schraegstrich am Ende. Ein
    nackter Host bekommt `https://` vorangestellt; ein anderes Schema bleibt
    stehen und faellt dann in zugang_pruefen durch."""
    w = (wert or "").strip().lower()
    if w and "://" not in w:
        w = "https://" + w
    return w.rstrip("/")


def zugang_pruefen(info: KanalInfo, zugang: Mapping[str, str]) -> str | None:
    """None = vollstaendig und in gueltiger Form (verbunden). Sonst ein
    deutscher Satz, der nur Namen nennt."""
    for n in info.env_namen:
        if not (zugang.get(n) or "").strip():
            return f"{n} fehlt"
    for n in info.env_namen:
        wert = (zugang.get(n) or "").strip()
        if n == "MASTODON_INSTANCE":
            ok = bool(_INSTANZ.fullmatch(instanz_normalisieren(wert)))
        elif n == "TELEGRAM_KANAL_ID":
            ok = bool(_TELEGRAM_ID.fullmatch(wert))
        elif n == "DISCORD_ANKUENDIGUNG_WEBHOOK":
            ok = bool(_DISCORD_WEBHOOK.fullmatch(wert))
        elif n == "BLUESKY_HANDLE":
            handle = wert[1:] if wert.startswith("@") else wert
            ok = "." in handle and not handle.startswith("@")
        else:
            ok = True
        if not ok:
            return f"{n} hat kein gültiges Format"
    return None


# --- Entwurfspruefung ---------------------------------------------------------

def pruefe_entwurf(info: KanalInfo, text: str, titel: str,
                   medien: Sequence[tuple[str, MEDIUM_ART, int]]) -> str | None:
    """Ablehnungsgrund (deutsch) oder None. Medien als (name, art, bytes).
    Textlaenge = len(str); mit Medien gilt max_zeichen_mit_medien."""
    text = text or ""
    titel = (titel or "").strip()
    if not text.strip():
        return f"{info.anzeige}: der Text ist leer"
    if info.titel_pflicht:
        if not titel:
            return f"{info.anzeige}: ein Titel ist Pflicht"
        if len(titel) > info.titel_max:
            return (f"{info.anzeige}: der Titel hat {len(titel)} Zeichen, "
                    f"erlaubt sind höchstens {info.titel_max}")
    elif titel:
        return f"{info.anzeige}: titel gibt es nur bei dev.to"

    grenze = info.max_zeichen_mit_medien if medien else info.max_zeichen
    if len(text) > grenze:
        zusatz = " mit Medien" if medien and grenze != info.max_zeichen else ""
        return (f"{info.anzeige}: der Text hat {len(text)} Zeichen, erlaubt "
                f"sind{zusatz} höchstens {grenze}")

    if not medien:
        return None
    if info.medien_max == 0:
        return f"{info.anzeige}: Medien sind hier nicht möglich"
    if len(medien) > info.medien_max:
        return (f"{info.anzeige}: höchstens {info.medien_max} "
                f"{'Medium' if info.medien_max == 1 else 'Medien'} erlaubt")
    arten = {art for _, art, _ in medien}
    if not arten <= {"bild", "video"}:
        return f"{info.anzeige}: nur Bilder oder Videos sind möglich"
    if len(arten) > 1:
        return f"{info.anzeige}: Bilder und Video lassen sich nicht mischen"
    art = next(iter(arten))
    hoechst = info.bilder_max if art == "bild" else info.video_max
    if hoechst == 0:
        return f"{info.anzeige}: {'Bilder' if art == 'bild' else 'Videos'} sind hier nicht möglich"
    if len(medien) > hoechst:
        return (f"{info.anzeige}: höchstens {hoechst} "
                f"{('Bild' if hoechst == 1 else 'Bilder') if art == 'bild' else ('Video' if hoechst == 1 else 'Videos')} erlaubt")
    max_bytes = info.bild_max_bytes if art == "bild" else info.video_max_bytes
    for name, _, groesse in medien:
        if groesse > max_bytes:
            return (f"{info.anzeige}: {name} ist zu groß "
                    f"(höchstens {max_bytes} Bytes je {'Bild' if art == 'bild' else 'Video'})")
    return None


# --- Tabelle kanal_status -----------------------------------------------------

def status_lesen(q) -> dict[str, dict]:
    """kanal -> {verbunden, geprueft_am, letzter_fehler}. Fehlt die Tabelle
    (Code ausgeliefert, provision.sql noch nicht eingespielt), gilt alles als
    nicht verbunden: {}. Andere DB-Fehler gehen weiter."""
    try:
        zeilen = q("select kanal, verbunden, geprueft_am, letzter_fehler from kanal_status")
    except psycopg.errors.UndefinedTable:
        return {}
    return {z["kanal"]: {"verbunden": bool(z["verbunden"]),
                         "geprueft_am": z["geprueft_am"],
                         "letzter_fehler": z["letzter_fehler"]} for z in zeilen}


def verbunden(q, kanal: str) -> bool:
    """Fehlende Zeile (oder Tabelle) = nicht verbunden."""
    eintrag = status_lesen(q).get(kanal)
    return bool(eintrag and eintrag["verbunden"])


def status_schreiben(q, kanal: str, verbunden: bool, fehler: str | None, *,
                     fehler_loeschen: bool = False) -> None:
    """Upsert je Kanal, geprueft_am = now(). Ein gegebener Fehler wird auf
    300 Zeichen gekappt; fehler=None laesst den bisherigen stehen, ausser
    fehler_loeschen=True."""
    if fehler is not None:
        q("insert into kanal_status (kanal, verbunden, geprueft_am, letzter_fehler) "
          "values (%s, %s, now(), %s) on conflict (kanal) do update set "
          "verbunden = excluded.verbunden, geprueft_am = now(), "
          "letzter_fehler = excluded.letzter_fehler",
          (kanal, verbunden, fehler[:FEHLER_MAX]))
    elif fehler_loeschen:
        q("insert into kanal_status (kanal, verbunden, geprueft_am, letzter_fehler) "
          "values (%s, %s, now(), null) on conflict (kanal) do update set "
          "verbunden = excluded.verbunden, geprueft_am = now(), letzter_fehler = null",
          (kanal, verbunden))
    else:
        q("insert into kanal_status (kanal, verbunden, geprueft_am) "
          "values (%s, %s, now()) on conflict (kanal) do update set "
          "verbunden = excluded.verbunden, geprueft_am = now()",
          (kanal, verbunden))
