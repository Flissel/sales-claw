"""sales-kanaele - Dauerdienst fuer eigene Beitraege auf Bluesky, Mastodon,
Telegram-Kanal, Discord und dev.to (Spec 2026-10-24-kanaele-posten).

Muster und ausfuehrliche Begruendung: linkedin_dispatch.py. Kurz:
* Claim approved -> failed+Marke je Kanalwert UND `recipient='eigenes-
  profil'` im UPDATE selbst; der Kanalwert kommt nur aus der Registry.
* Beleg in `activities` VOR der Buchung auf `sent`; `bereits_veroeffentlicht`
  fragt den Beleg, nicht drafts.status.
* Ein ungewisser Ausgang (keine Antwort beim Veroeffentlichen, oder eine
  unerwartete Ausnahme im Adapter) schreibt einen Ungewiss-Beleg und sperrt
  jede Wiederholung.
* Kadenz und Frischegrenze je Kanal; je Runde hoechstens ein Beitrag je
  Kanal. Ein Fehler in einem Kanal haelt die anderen nicht auf.
* Fehlende Zugaenge sind ein gueltiger Zustand ("nicht verbunden"), kein
  Ausfall: der Dienst laeuft weiter, Entwuerfe bleiben unangetastet.

Jede Runde schreibt je Kanal eine Zeile in kanal_status. Kein Fehlertext,
kein Log enthaelt einen Zugangswert (`kanal_api.ohne_geheimnisse`).
"""
import json
import logging
import os
import signal
import sys
import threading
from typing import Mapping

import psycopg

import dispatch
import kanal_adapter
import medien
import server
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)
from kanaele import (KANAELE, KanalInfo, pruefe_entwurf, status_schreiben,
                     zugang_lesen, zugang_pruefen)
from kanal_api import KanalFehler, Medium, ohne_geheimnisse

KANAL_INTERVAL_S = float(os.environ.get("KANAL_INTERVAL_S", "60"))
KANAL_FRISCHE_TAGE = int(os.environ.get("KANAL_FRISCHE_TAGE", "7"))
KANAL_ONCE = os.environ.get("KANAL_ONCE", "").strip().lower() in (
    "1", "true", "ja", "yes")

WEG = "kanal-dispatcher"
LOG = logging.getLogger("sales-kanaele")

# Normalzustand: kein Log je Runde.
_RUHIG = ("nichts", "kadenz", "nicht_verbunden")


class BeitragFehler(Exception):
    """Der Beitrag kann nicht entstehen, mit menschenlesbarem Grund."""


def _info(kanal: str) -> KanalInfo:
    info = KANAELE.get(kanal)
    if info is None:
        raise ValueError(f"unbekannter Kanal: {kanal!r}")
    return info


def _zugang(info: KanalInfo) -> dict[str, str]:
    return zugang_lesen(info, os.environ)


def _geheim(info: KanalInfo, zugang: Mapping[str, str] | None = None) -> list[str]:
    """Alle Zugangswerte des Kanals - auch Handle, Instanz und Kanal-ID sollen
    nie in UI oder Log stehen, nicht nur die geheim_namen."""
    zugang = zugang if zugang is not None else _zugang(info)
    return [zugang.get(n, "") for n in info.env_namen]


def _alle_geheim() -> list[str]:
    return [w for info in KANAELE.values() for w in _geheim(info)]


def _sauber(text: str, geheim: list[str], laenge: int = 500) -> str:
    return _einzeilig(ohne_geheimnisse(str(text), geheim))[:laenge]


# ---------------------------------------------------------------------------
# Claim / Belege
# ---------------------------------------------------------------------------

def claim(kanal: str, draft_id: str) -> dict | None:
    """Atomarer Claim approved -> failed+Marke, nur eigene Beitraege dieses
    Kanals (Praezisierung 4)."""
    kanalwert = _info(kanal).name   # nur die Registry liefert den Wert
    marke = _claim_marke()
    zeilen = server._q(
        "update drafts set status = 'failed', error = %s "
        "where id = %s and status = 'approved' and channel = %s "
        "and recipient = 'eigenes-profil' "
        "returning id, lead_id, subject, body, media_ref, thema",
        (marke, draft_id, kanalwert))
    if not zeilen:
        return None
    geclaimt = dict(zeilen[0])
    geclaimt["marke"] = marke
    return geclaimt


def _beleg_schreiben(kanal: str, geclaimt: dict, payload: dict) -> None:
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": kanal,
                     "weg": WEG, "empfaenger": "eigenes-profil", **payload},
                    ensure_ascii=False)))


def bereits_veroeffentlicht(kanal: str, draft_id: str) -> str | None:
    """Beitrags-Kennung, falls fuer diesen Entwurf auf diesem Kanal schon ein
    Beleg steht (auch ein ungewisser). Fragt `activities` (append-only), nicht
    den zuruecksetzbaren drafts.status - siehe linkedin_dispatch.py."""
    zeilen = server._q(
        "select payload from activities where type = 'versand' "
        "and payload->>'kanal' = %s and payload->>'draft_id' = %s limit 1",
        (_info(kanal).name, str(draft_id)))
    if not zeilen:
        return None
    beleg = zeilen[0]["payload"] or {}
    if isinstance(beleg, str):
        beleg = json.loads(beleg)
    if beleg.get("ungewiss"):
        return ("ungewisser Ausgang eines frueheren Versuchs - auf dem Kanal "
                "nachsehen")
    return beleg.get("beitrag") or "unbekannte Beitrags-Kennung"


def heute_anzahl(kanal: str) -> int:
    """Belege dieses Kanals seit Tagesbeginn (DB-Zeit); ungewisse zaehlen mit."""
    zeilen = server._q(
        "select count(*) as n from activities where type = 'versand' "
        "and payload->>'kanal' = %s and created_at >= date_trunc('day', now())",
        (_info(kanal).name,))
    return int(zeilen[0]["n"])


def wartende(kanal: str) -> list[dict]:
    """Freigegebene eigene Beitraege dieses Kanals, aelteste Freigabe zuerst.
    `zu_alt` = juenger als die Frischegrenze ist die Freigabe nicht mehr."""
    return server._q(
        "select id, subject, media_ref, approved_at, "
        "coalesce(approved_at < now() - make_interval(days => %s), false) "
        "as zu_alt from drafts "
        "where status = 'approved' and channel = %s "
        "and recipient = 'eigenes-profil' "
        "order by approved_at nulls last, created_at",
        (KANAL_FRISCHE_TAGE, _info(kanal).name))


# ---------------------------------------------------------------------------
# Medien
# ---------------------------------------------------------------------------

_ART = {"send-image": "bild", "send-video": "video"}


def medien_laden(kanal: str, media_ref: str | None) -> list[Medium]:
    """`media_ref` (Komma-Liste) in Medien aufloesen. Grenzen aus der Registry
    werden VOR dem Lesen geprueft (Dateigroesse), damit kein zu grosses Video
    erst in den Speicher geladen wird. Wirft BeitragFehler (oder OSError,
    wenn eine Datei inzwischen fehlt)."""
    info = _info(kanal)
    namen = [t.strip() for t in (media_ref or "").split(",") if t.strip()]
    gefunden: list[tuple[str, str, str]] = []
    for name in namen:
        basis, fehler = medien.pruefe_anhang(name)
        if fehler:
            raise BeitragFehler(f"{fehler} Es ging NICHTS raus.")
        endpunkt, mimetyp = medien.endpunkt_und_typ(basis)
        art = _ART.get(endpunkt)
        if art is None:
            raise BeitragFehler(
                f"'{basis}' ist fuer einen Beitrag auf {info.anzeige} nicht "
                f"verwendbar - nur Bilder oder ein Video. Es ging NICHTS raus.")
        gefunden.append((basis, mimetyp, art))
    if not gefunden:
        return []
    groessen = [(b, a, os.path.getsize(medien.pfad(b))) for b, _m, a in gefunden]
    # Nur die Medienregeln pruefen: Platzhaltertext und -titel.
    grund = pruefe_entwurf(info, "x", "x" if info.titel_pflicht else "", groessen)
    if grund:
        raise BeitragFehler(f"{grund}. Es ging NICHTS raus.")
    return [Medium(b, m, medien.lies(b), a) for b, m, a in gefunden]


def _medienart(liste: list[Medium]) -> str:
    if any(m.art == "video" for m in liste):
        return "video"
    if len(liste) > 1:
        return f"bilder({len(liste)})"
    return "bild" if liste else "text"


# ---------------------------------------------------------------------------
# Verarbeitung
# ---------------------------------------------------------------------------

def _verarbeite(kanal: str, draft_id: str) -> tuple[str, str | None]:
    """(Ausgang, bereinigter Fehlertext fuer kanal_status oder None)."""
    info = _info(kanal)
    zugang = _zugang(info)
    geheim = _geheim(info, zugang)

    schon = bereits_veroeffentlicht(kanal, draft_id)
    if schon:
        LOG.warning("%s draft=%s NICHT erneut gepostet - bereits "
                    "veroeffentlicht als %s", kanal, draft_id, schon)
        return "schon_veroeffentlicht", None

    # Zugang VOR dem Claim: ein nicht verbundener Kanal laesst den Entwurf
    # unangetastet auf `approved` liegen.
    grund = zugang_pruefen(info, zugang)
    if grund:
        return "nicht_verbunden", grund

    geclaimt = claim(kanal, draft_id)
    if geclaimt is None:
        LOG.info("%s draft=%s uebersprungen (nicht mehr approved oder fremd "
                 "geclaimt)", kanal, draft_id)
        return "uebersprungen", None
    marke = geclaimt["marke"]

    def fehler(ausgang: str, text: str) -> tuple[str, str]:
        text = _sauber(text, geheim)
        _als_fehler_buchen(draft_id, marke, text)
        LOG.info("%s draft=%s %s (%s)", kanal, draft_id, ausgang, text[:160])
        return ausgang, text

    text = geclaimt["body"] or ""
    titel = (geclaimt["subject"] or "") if info.titel_pflicht else ""
    if not text.strip():
        return fehler("leer", f"{info.anzeige}: Beitrag ohne Text - es ging "
                              f"NICHTS raus.")
    try:
        liste = medien_laden(kanal, geclaimt["media_ref"])
    except BeitragFehler as e:
        return fehler("medien_unbrauchbar", str(e))
    except OSError as e:
        return fehler("medien_unbrauchbar",
                      f"Medienordner nicht lesbar ({type(e).__name__}) - es "
                      f"ging NICHTS raus.")
    grund = pruefe_entwurf(info, text, titel,
                           [(m.name, m.art, len(m.daten)) for m in liste])
    if grund:
        return fehler("zu_lang", f"{grund} - es ging NICHTS raus.")

    art = _medienart(liste)
    try:
        beleg = kanal_adapter.SENDER[kanal](zugang, text, liste, titel,
                                            str(draft_id))
    except KanalFehler as e:
        if not e.ungewiss:
            return fehler("fehler", str(e))
        grund_u = _sauber(str(e), geheim, 300)
    except Exception as e:                  # noqa: BLE001 - bewusst breit
        # Unbekannt, ob der veroeffentlichende Aufruf schon draussen war.
        grund_u = _sauber(f"{type(e).__name__}: {e}", geheim, 300)
    else:
        grund_u = None

    if grund_u is not None:
        try:
            _beleg_schreiben(kanal, geclaimt, {
                "beitrag": None, "url": None, "ungewiss": True,
                "medienart": art, "grund": grund_u})
        except psycopg.Error as db:
            LOG.critical("%s draft=%s UNGEWISSER AUSGANG und der Nachweis "
                         "liess sich nicht schreiben (%s) - auf dem Kanal "
                         "nachsehen, BEVOR dieser Entwurf erneut angefasst "
                         "wird. Grund: %s", kanal, draft_id,
                         _einzeilig(str(db)), grund_u)
            return "ungewiss_ohne_nachweis", f"UNGEWISS ohne Nachweis: {grund_u}"
        meldung = _sauber(
            f"UNGEWISS: keine verwertbare Antwort von {info.anzeige} gesehen. "
            f"Der Beitrag KANN oeffentlich stehen. Erneutes Freigeben aendert "
            f"daran nichts - dieser Dienst wird ihn nicht noch einmal posten. "
            f"Auf dem Kanal nachsehen und dann entscheiden. {grund_u}", geheim)
        _als_fehler_buchen(draft_id, marke, meldung)
        LOG.critical("%s draft=%s UNGEWISSER AUSGANG - Kanal pruefen: %s",
                     kanal, draft_id, grund_u)
        return "ungewiss", meldung

    # DER BELEG ZUERST, DIE BUCHUNG DANACH (Praezisierung 10).
    try:
        _beleg_schreiben(kanal, geclaimt, {
            "beitrag": beleg.beitrag, "url": beleg.url or None,
            "medienart": art})
    except psycopg.Error as e:
        LOG.critical("%s draft=%s VEROEFFENTLICHT als %s, aber der Nachweis "
                     "liess sich nicht schreiben: %s - diese Kennung von Hand "
                     "sichern, bevor der Entwurf erneut angefasst wird",
                     kanal, draft_id, beleg.beitrag, _einzeilig(str(e)))
        return ("veroeffentlicht_ohne_nachweis",
                f"veroeffentlicht als {beleg.beitrag}, Nachweis fehlt")

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
    except psycopg.Error as e:
        gebucht = False
        LOG.critical("%s draft=%s VEROEFFENTLICHT (%s), Buchung scheiterte: "
                     "%s", kanal, draft_id, beleg.beitrag, _einzeilig(str(e)))
    if not gebucht:
        LOG.critical("%s draft=%s VEROEFFENTLICHT als %s, aber nicht auf "
                     "'sent' gebucht - Entwurf bleibt geclaimt liegen, kein "
                     "zweiter Beitrag", kanal, draft_id, beleg.beitrag)
        return ("veroeffentlicht_ohne_buchung",
                f"veroeffentlicht als {beleg.beitrag}, nicht auf 'sent' gebucht")

    LOG.info("%s draft=%s veroeffentlicht als %s (%s)", kanal, draft_id,
             beleg.beitrag, art)
    return "veroeffentlicht", None


def verarbeite_draft(kanal: str, draft_id: str) -> str:
    """Ein Beitrag: pruefen, claimen, Medien laden, senden, belegen, buchen."""
    return _verarbeite(kanal, draft_id)[0]


def eine_runde_kanal(kanal: str) -> str:
    """Ein Durchgang fuer einen Kanal, hoechstens ein Beitrag."""
    info = _info(kanal)
    grund = zugang_pruefen(info, _zugang(info))
    if grund:
        status_schreiben(server._q, kanal, False, grund)
        return "nicht_verbunden"

    if heute_anzahl(kanal) >= info.kadenz_pro_tag:
        status_schreiben(server._q, kanal, True, None)
        return "kadenz"

    ausgang, fehlertext, zu_alt = "nichts", None, 0
    for eintrag in wartende(kanal):
        if eintrag["zu_alt"]:
            zu_alt += 1
            continue
        ausgang, fehlertext = _verarbeite(kanal, str(eintrag["id"]))
        break
    else:
        if zu_alt:
            LOG.warning("%s: %d freigegebene(r) Beitrag/Beitraege sind aelter "
                        "als %d Tage und bleiben liegen - wer sie will, gibt "
                        "sie erneut frei. Es wurde NICHTS veroeffentlicht.",
                        kanal, zu_alt, KANAL_FRISCHE_TAGE)

    if ausgang == "nicht_verbunden":    # Zugang mitten in der Runde weg
        status_schreiben(server._q, kanal, False, fehlertext)
        return ausgang
    status_schreiben(server._q, kanal, True, fehlertext,
                     fehler_loeschen=(ausgang == "veroeffentlicht"))
    return ausgang


def eine_runde() -> dict[str, str]:
    """Alle Kanaele der Registry. Eine Ausnahme (ausser DB-Fehler) in einem
    Kanal wird dort gebucht; die anderen laufen weiter."""
    ausgaenge: dict[str, str] = {}
    for kanal, info in KANAELE.items():
        try:
            ausgaenge[kanal] = eine_runde_kanal(kanal)
        except psycopg.Error:
            raise
        except Exception as e:              # noqa: BLE001 - bewusst breit
            text = _sauber(f"{type(e).__name__}: {e}", _alle_geheim(), 300)
            LOG.error("%s: Ausnahme in der Runde - %s", kanal, text)
            status_schreiben(server._q, kanal,
                             zugang_pruefen(info, _zugang(info)) is None, text)
            ausgaenge[kanal] = "ausnahme"
    return ausgaenge


# ---------------------------------------------------------------------------
# Betrieb
# ---------------------------------------------------------------------------

_STOPP = threading.Event()


def _stopp_anfordern(signum, _rahmen) -> None:
    """SIGTERM/SIGINT beenden die Schleife NACH der laufenden Runde."""
    LOG.info("%s empfangen - nach dieser Runde ist Schluss.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout, auch fuer dispatch.LOG (die importierten
    Buchungshelfer loggen ihre critical-Saetze dorthin)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for logger in (LOG, dispatch.LOG):
        if logger.handlers:
            continue
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def main() -> int:
    _logging_einrichten()
    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    # Nie Werte ins Log, nur die Zahl verbundener Kanaele (Praezisierung 9:
    # fehlende Zugaenge beenden den Dienst nicht).
    verbunden = sum(1 for info in KANAELE.values()
                    if zugang_pruefen(info, _zugang(info)) is None)
    LOG.info("Start: schema=%s intervall=%gs frische=%dd verbunden=%d/%d",
             server.SCHEMA, KANAL_INTERVAL_S, KANAL_FRISCHE_TAGE, verbunden,
             len(KANAELE))
    while not _STOPP.is_set():
        try:
            ausgaenge = eine_runde()
        except psycopg.Error as e:
            LOG.error("Datenbank nicht erreichbar: %s",
                      _sauber(str(e), _alle_geheim()))
            ausgaenge = {"*": "db-ausfall"}
        for kanal, ausgang in ausgaenge.items():
            if ausgang not in _RUHIG:
                LOG.info("%s: Ausgang %s", kanal, ausgang)
        if KANAL_ONCE:
            return 0
        _STOPP.wait(KANAL_INTERVAL_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
