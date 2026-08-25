"""sales-linkedin — der Zwilling des Dispatchers fuer LinkedIn-BEITRAEGE.

Er liest ausschliesslich freigegebene LinkedIn-Beitraege
(`drafts.status='approved' and channel='linkedin' and
recipient='eigenes-profil'`) und veroeffentlicht sie ueber die offizielle
LinkedIn-API auf dem Profil des Betreibers. Das Freigabe-Gate ist auch hier
die Datenbank und nicht das Verhalten eines Sprachmodells.

WARUM `recipient = 'eigenes-profil'` IN JEDER QUERY STEHT
---------------------------------------------------------
Das ist keine Feinheit, sondern die Sicherheitskante dieses Dienstes.
`channel='linkedin'` traegt ZWEI verschiedene Dinge:

* BEITRAEGE auf dem eigenen Profil (`recipient='eigenes-profil'`, angelegt
  von `post_entwurf_erstellen`) — die kann die API veroeffentlichen.
* DIREKTNACHRICHTEN an echte Menschen (`recipient='<Name>'`, angelegt von
  `entwurf_erstellen(kanal='linkedin')`) — die kann die API NICHT
  versenden; fuer Privatprofile gibt es keinen Nachrichtenversand. Sie
  bleiben Handarbeit und werden mit `entwurf_manuell_gesendet` quittiert.

Als dieser Dienst gebaut wurde, lag genau so eine freigegebene
Direktnachricht in der Datenbank. Ein Versender, der stumpf nach
`channel='linkedin'` greift, haette sie beim ersten Start angefasst — und
zwar als Beitrag, also den Text einer privaten Ansprache oeffentlich auf
das Profil gestellt. Deshalb steht `recipient='eigenes-profil'` im Claim
selbst und nicht in einer Pruefung davor: was der Claim nicht greift, kann
dieser Dienst nicht versehentlich veroeffentlichen.

CLAIM, at-most-once, kein Retry
-------------------------------
Wortgleich zu dispatch.py und mail_dispatch.py, inklusive Begruendung: der
Claim laeuft ueber den erlaubten Uebergang approved -> failed mit einer
Marke im `error`-Feld, und er ist VOR dem Veroeffentlichen committet.
Stirbt der Prozess mitten im Vorgang, bleibt der Entwurf liegen und wird
nie erneut veroeffentlicht. Ein liegengebliebener Beitrag ist das viel
kleinere Uebel gegenueber einem doppelten Beitrag auf dem Profil — den
sieht jeder Leser, und er laesst sich nur von Hand wieder wegraeumen.

Claim-Marke und Buchungen werden aus dispatch.py IMPORTIERT, nicht
abgeschrieben: `entwurf_erneut_freigeben` in server.py erkennt einen
haengenden Versand am Praefix, den `_claim_marke` schreibt. Eine zweite,
aehnliche Marke setzte diese Schutzkante fuer LinkedIn-Entwuerfe still
ausser Kraft.

MEDIEN
------
`drafts.media_ref` traegt entweder nichts (reiner Textbeitrag), einen
Dateinamen oder mehrere durch Komma getrennt. Woraus ein Beitrag wird,
entscheidet die Endung ueber `medien.endpunkt_und_typ` — dieselbe
Whitelist wie beim WhatsApp-Versand, damit es nicht zwei Wahrheiten
darueber gibt, was versendbar ist:

* nichts            -> Textbeitrag
* ein .mp4          -> Videobeitrag
* ein oder mehrere Bilder -> Bildbeitrag (mehrere = multiImage)
* alles andere      -> FEHLGESCHLAGEN, kein Ersatz

Ein Ersatzversand als reiner Text findet ausdruecklich NICHT statt:
freigegeben wurde ein Beitrag MIT Unterlage. Dieselbe Regel wie im
WhatsApp- und im Mailweg.
"""
import json
import logging
import os
import signal
import sys
import threading

import psycopg

import dispatch
import linkedin_api
import medien
import server
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)

LINKEDIN_INTERVAL_S = float(os.environ.get("LINKEDIN_INTERVAL_S", "20"))
LINKEDIN_ONCE = os.environ.get("LINKEDIN_ONCE", "").strip().lower() in (
    "1", "true", "yes", "ja")

STAPEL = 5                  # Entwuerfe je Runde, wie bei den Zwillingen
SENDE_PAUSE_S = float(os.environ.get("LINKEDIN_SENDE_PAUSE_S", "2.0"))

# LinkedIn-Grenze fuer Beitraege mit mehreren Bildern. Ein Beitrag mit mehr
# Bildern wuerde erst beim Veroeffentlichen abprallen — also nach der
# Freigabe, am schlechtesten Zeitpunkt.
BILDER_MAX = 20

LOG = logging.getLogger("sales-linkedin")
_STOPP = threading.Event()

# Ausgaenge, nach denen tatsaechlich mit LinkedIn gesprochen wurde — nur
# danach wird pausiert. Die Pause gilt dem fremden Dienst, nicht der
# eigenen Datenbank.
_NETZ_AUSGAENGE = frozenset(("veroeffentlicht", "fehler",
                             "veroeffentlicht_ohne_buchung"))


class BeitragFehler(Exception):
    """Der Beitrag kann nicht entstehen, mit menschenlesbarem Grund."""


# ---------------------------------------------------------------------------
# Claim / Buchung
# ---------------------------------------------------------------------------

def claim(draft_id):
    """Atomarer Claim approved -> failed+Marke, NUR fuer eigene Beitraege.

    `channel='linkedin' and recipient='eigenes-profil'` gehoert in den
    Claim, nicht in eine Pruefung danach — siehe Moduldocstring.
    """
    marke = _claim_marke()
    zeilen = server._q(
        "update drafts set status = 'failed', error = %s "
        "where id = %s and status = 'approved' and channel = 'linkedin' "
        "and recipient = 'eigenes-profil' "
        "returning id, lead_id, recipient, subject, body, media_ref",
        (marke, draft_id))
    if not zeilen:
        return None
    geclaimt = dict(zeilen[0])
    geclaimt["marke"] = marke
    return geclaimt


def _versand_loggen(geclaimt, beitrag_urn, medienart) -> None:
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": "linkedin",
                     "weg": "linkedin-dispatcher", "empfaenger":
                     "eigenes-profil", "beitrag": beitrag_urn,
                     "medienart": medienart},
                    ensure_ascii=False)))


# ---------------------------------------------------------------------------
# Medien
# ---------------------------------------------------------------------------

def medien_aufteilen(media_ref):
    """`media_ref` in (Bilder, Video) aufloesen. Wirft BeitragFehler.

    Gibt zwei Listen/Werte zurueck: eine Liste geprueft vorhandener
    Bilddateien und hoechstens einen Videonamen. Geprueft wird mit
    `medien.pruefe` — derselben Kante, die auch der WhatsApp-Versand nutzt
    (kein Pfad, keine Traversierung, Endung in der Whitelist).
    """
    namen = [t.strip() for t in (media_ref or "").split(",") if t.strip()]
    bilder, video = [], None
    for name in namen:
        basis, fehler = medien.pruefe(name)
        if fehler:
            raise BeitragFehler(fehler)
        endpunkt, _typ = medien.endpunkt_und_typ(basis)
        if endpunkt == "send-image":
            bilder.append(basis)
        elif endpunkt == "send-video":
            if video is not None:
                raise BeitragFehler(
                    "Ein Beitrag traegt hoechstens ein Video; hier sind es "
                    "mehrere. Es ging NICHTS raus.")
            video = basis
        else:
            raise BeitragFehler(
                f"'{basis}' ist fuer einen LinkedIn-Beitrag nicht "
                f"verwendbar — ein Beitrag traegt Bilder oder ein Video. Es "
                f"ging NICHTS raus (auch kein Text ohne Unterlage).")
    if bilder and video:
        raise BeitragFehler(
            "Ein Beitrag traegt entweder Bilder oder ein Video, nicht "
            "beides. Es ging NICHTS raus.")
    if len(bilder) > BILDER_MAX:
        raise BeitragFehler(
            f"{len(bilder)} Bilder — LinkedIn nimmt hoechstens {BILDER_MAX}. "
            f"Es ging NICHTS raus.")
    return bilder, video


def medien_hochladen(bilder, video):
    """Dateien zu LinkedIn hochladen. Gibt (Bild-Kennungen, Video-Kennung).

    Hochladen veroeffentlicht nichts — erst der Beitrag tut das. Schlaegt
    ein Upload fehl, entsteht deshalb auch kein halber Beitrag: es ist
    schlicht nichts zu sehen.
    """
    bild_urns = []
    for basis in bilder:
        _endpunkt, mimetyp = medien.endpunkt_und_typ(basis)
        bild_urns.append(linkedin_api.bild_hochladen(medien.lies(basis),
                                                     mimetyp))
    video_urn = None
    if video:
        _endpunkt, mimetyp = medien.endpunkt_und_typ(video)
        video_urn = linkedin_api.video_hochladen(medien.lies(video), mimetyp)
    return bild_urns, video_urn


def _medienart(bilder, video) -> str:
    if video:
        return "video"
    if len(bilder) > 1:
        return f"bilder({len(bilder)})"
    if bilder:
        return "bild"
    return "text"


# ---------------------------------------------------------------------------
# Verarbeitung
# ---------------------------------------------------------------------------

def verarbeite_draft(draft_id) -> str:
    """Ein Beitrag: claimen, Medien laden, veroeffentlichen, buchen."""
    geclaimt = claim(draft_id)
    if geclaimt is None:
        LOG.info("draft=%s uebersprungen (nicht mehr approved, keine "
                 "Profil-Veroeffentlichung oder fremd geclaimt)", draft_id)
        return "uebersprungen"
    marke = geclaimt["marke"]

    text = (geclaimt["body"] or "").strip()
    if not text:
        _als_fehler_buchen(draft_id, marke,
                           "Beitrag ohne Text — es ging NICHTS raus.")
        return "leer"

    try:
        bilder, video = medien_aufteilen(geclaimt["media_ref"])
    except BeitragFehler as e:
        _als_fehler_buchen(draft_id, marke, str(e))
        LOG.info("draft=%s nicht veroeffentlicht (%s)", draft_id,
                 _einzeilig(str(e)))
        return "medien_unbrauchbar"
    except OSError as e:
        _als_fehler_buchen(draft_id, marke,
                           f"Medienordner nicht lesbar ({type(e).__name__}) "
                           f"— es ging NICHTS raus.")
        return "medien_unbrauchbar"

    art = _medienart(bilder, video)
    try:
        bild_urns, video_urn = medien_hochladen(bilder, video)
        beitrag = linkedin_api.beitrag_erstellen(text, bilder=bild_urns,
                                                 video=video_urn)
    except linkedin_api.LinkedInFehler as e:
        _als_fehler_buchen(draft_id, marke, _einzeilig(str(e))[:500])
        LOG.info("draft=%s fehlgeschlagen (%s, dauerhaft=%s)", draft_id,
                 _einzeilig(str(e))[:160], e.dauerhaft)
        return "fehler"
    except OSError as e:
        _als_fehler_buchen(draft_id, marke,
                           f"Datei nicht lesbar ({type(e).__name__}) — es "
                           f"ging NICHTS raus.")
        return "fehler"
    except Exception as e:                  # noqa: BLE001 — bewusst breit
        # Gleiche Lehre wie im Mailweg (Review-Befund H1 dort): ein
        # unerwarteter Fehler beim Bauen der Nutzlast risse sonst den
        # Dienst ab (restart "no") und liesse den Entwurf mit Claim-Marke
        # liegen. Hier wird er zur regulaeren Fehlerbuchung.
        _als_fehler_buchen(draft_id, marke,
                           f"Beitrag nicht konstruierbar ({type(e).__name__}: "
                           f"{_einzeilig(str(e))[:200]})")
        LOG.info("draft=%s nicht konstruierbar (%s)", draft_id,
                 type(e).__name__)
        return "fehler"

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
        if gebucht:
            _versand_loggen(geclaimt, beitrag, art)
    except psycopg.Error as e:
        gebucht = False
        LOG.critical("draft=%s VEROEFFENTLICHT (%s), Buchung scheiterte: %s",
                     draft_id, beitrag, _einzeilig(str(e)))
    if not gebucht:
        # Der Beitrag steht bereits oeffentlich. Er darf auf keinen Fall ein
        # zweites Mal entstehen — der Entwurf bleibt geclaimt liegen, und
        # die Kennung steht im Log, damit ein Mensch ihn wiederfindet.
        LOG.critical("draft=%s VEROEFFENTLICHT als %s, aber nicht auf 'sent' "
                     "gebucht — Entwurf bleibt geclaimt liegen, kein zweiter "
                     "Beitrag", draft_id, beitrag)
        return "veroeffentlicht_ohne_buchung"

    LOG.info("draft=%s veroeffentlicht als %s (%s)", draft_id, beitrag, art)
    return "veroeffentlicht"


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene Beitraege, aelteste zuerst."""
    zeilen = server._q(
        "select id from drafts where status = 'approved' "
        "and channel = 'linkedin' and recipient = 'eigenes-profil' "
        "order by created_at limit %s", (STAPEL,))
    bilanz = {}
    letzter_ausgang = None
    for z in zeilen:
        if letzter_ausgang in _NETZ_AUSGAENGE and SENDE_PAUSE_S > 0:
            _STOPP.wait(SENDE_PAUSE_S)      # unterbrechbar durch SIGTERM
        letzter_ausgang = verarbeite_draft(z["id"])
        bilanz[letzter_ausgang] = bilanz.get(letzter_ausgang, 0) + 1
    return bilanz


# ---------------------------------------------------------------------------
# Betrieb
# ---------------------------------------------------------------------------

def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen — Ende nach der laufenden Runde.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout — gleiche Lehre wie in den Zwillingen.

    Auch an `dispatch.LOG`: die importierten Buchungshelfer loggen ihre
    `critical`-Saetze dorthin, und das sind genau die Saetze, die einen
    Menschen rufen.
    """
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

    fehlend = linkedin_api.fehlende_konfiguration()
    if fehlend:
        # Exit 0, nicht 2 — gleiche Ueberlegung wie im Mailweg: ein nicht
        # eingerichteter LinkedIn-Kanal ist ein gueltiger Zustand dieses
        # Prototyps, kein Ausfall.
        LOG.warning("LinkedIn-Kanal nicht eingerichtet — %s fehlt in der "
                    "Umgebung (.env). Es wird nichts veroeffentlicht; "
                    "freigegebene Beitraege bleiben unangetastet liegen.",
                    ", ".join(fehlend))
        return 0

    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) — dann eben ohne Handler

    # Weder Token noch Person-Kennung ins Log: das eine ist ein Geheimnis,
    # das andere ein Personenbezug.
    LOG.info("Start: schema=%s api-version=%s intervall=%gs pause=%gs "
             "once=%s — warte auf freigegebene LinkedIn-Beitraege.",
             server.SCHEMA, linkedin_api.VERSION, LINKEDIN_INTERVAL_S,
             SENDE_PAUSE_S, LINKEDIN_ONCE)

    while not _STOPP.is_set():
        try:
            bilanz = eine_runde()
            if bilanz:
                LOG.info("Runde: %s", bilanz)
        except psycopg.Error as e:
            LOG.error("Datenbankfehler — Runde uebersprungen: %s",
                      _einzeilig(str(e)))
        if LINKEDIN_ONCE:
            break
        _STOPP.wait(LINKEDIN_INTERVAL_S)
    LOG.info("Beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
