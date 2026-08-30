"""sales-linkedin — der Zwilling des Dispatchers fuer LinkedIn-BEITRAEGE.

Er veroeffentlicht GENAU EINEN freigegebenen Beitrag — den, dessen Kennung
ihm ueber `LINKEDIN_DRAFT_ID` genannt wird — ueber die offizielle
LinkedIn-API auf dem Profil des Betreibers und beendet sich danach. Das
Freigabe-Gate ist auch hier die Datenbank und nicht das Verhalten eines
Sprachmodells.

ZWEI KANTEN, DIE DIESER DIENST ANDERS ZIEHT ALS SEINE ZWILLINGE
----------------------------------------------------------------
dispatch.py (WhatsApp) und mail_dispatch.py (E-Mail) laufen als Schleife
und nehmen je Runde einen Stapel. Beides waere hier falsch, und beides
wurde in einem fremden Review benannt, bevor dieser Dienst je lief:

1. STAPEL. Wer EINEN Beitrag freigibt und den Dienst startet, haette mit
   einem Stapellauf auch alles veroeffentlicht, was sonst noch auf
   `approved` steht — vor Wochen freigegeben, laengst vergessen, jetzt
   oeffentlich. Die Freigabe gilt EINEM Beitrag, also muss die Ausfuehrung
   demselben Beitrag gelten. Deshalb Exact-ID-One-Shot.

2. WIEDERHOLBARKEIT. Ging ein Beitrag raus und scheiterte danach die
   Buchung, blieb der Entwurf auf `failed` liegen — und
   `entwurf_erneut_freigeben` holt ihn mit `bestaetigt=True` zurueck auf
   `approved`. Bei WhatsApp bekommt der Empfaenger dann eine Nachricht
   doppelt; hier stuende ein zweiter Beitrag oeffentlich auf dem Profil,
   und niemand koennte vorher nachschlagen, ob der erste durchkam.
   Deshalb `bereits_veroeffentlicht` (siehe dort) und die Reihenfolge
   Beleg-vor-Buchung in `verarbeite_draft`.

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
import re
import signal
import sys
import threading
from datetime import datetime, timezone

import psycopg

import dispatch
import linkedin_api
import medien
import server
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)

# GENAU EIN ENTWURF, DESSEN KENNUNG GENANNT WIRD — kein Stapel, keine
# Schleife, kein Dauerbetrieb.
#
# Die Zwillinge (dispatch.py, mail_dispatch.py) nehmen je Runde bis zu fuenf
# freigegebene Entwuerfe. Fuer WhatsApp und E-Mail ist das richtig: dort ist
# `approved` eine Anweisung des Betreibers an genau einen Empfaenger, und
# mehrere davon abzuarbeiten ist blosse Reihenfolge.
#
# Hier waere es falsch. Wer EINEN Beitrag freigibt und den Dienst startet,
# haette mit einem Stapellauf auch alles andere veroeffentlicht, was
# irgendwann einmal auf `approved` stehen geblieben ist — vor Wochen
# freigegeben, laengst vergessen, jetzt oeffentlich. Die Freigabe gilt einem
# Beitrag; die Ausfuehrung muss demselben Beitrag gelten.
#
# Deshalb: der Betreiber nennt die Kennung, der Dienst macht genau das und
# beendet sich.
# NACHGEZOGEN 30.08.2026 (Betreiber: „freigabe soll gleich versand machen"):
# Der Dienst laeuft jetzt DAUERHAFT und nimmt freigegebene Beitraege von
# selbst — wie sales-dispatch bei WhatsApp. Die Sorge oben bleibt gueltig,
# wird aber anders abgefangen als durch das Fehlen einer Schleife:
#
#   * HOECHSTENS EINER PRO TAG (Kadenz des Betreibers vom 27.08.). Ein
#     Stapel freigegebener Beitraege geht damit nie gemeinsam raus,
#     sondern tropft — und wer zu viel freigegeben hat, merkt es am
#     ersten Tag, nicht an fuenf Beitraegen gleichzeitig.
#   * FRISCHEGRENZE: was laenger als LINKEDIN_FRISCHE_TAGE freigegeben
#     ist, bleibt liegen. Genau der Fall „vor Wochen freigegeben, laengst
#     vergessen" wird nicht ploetzlich oeffentlich, sondern wartet auf
#     einen Menschen.
#   * Der Einmal-Modus mit genannter Kennung bleibt daneben bestehen: er
#     ignoriert die Kadenz, denn dort hat ein Mensch genau diesen Beitrag
#     gemeint.
DRAFT_ID = os.environ.get("LINKEDIN_DRAFT_ID", "").strip()

# Wie oft nach freigegebenen Beitraegen gesehen wird. Zehn Sekunden wie bei
# den Zwillingen waeren Verschwendung: hier kommt hoechstens einmal am Tag
# etwas dazu.
LINKEDIN_INTERVAL_S = float(os.environ.get("LINKEDIN_INTERVAL_S", "60"))
LINKEDIN_FRISCHE_TAGE = int(os.environ.get("LINKEDIN_FRISCHE_TAGE", "7"))
LINKEDIN_ONCE = os.environ.get("LINKEDIN_ONCE", "").strip().lower() in (
    "1", "true", "ja", "yes")

_KENNUNG = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# LinkedIn-Grenze fuer Beitraege mit mehreren Bildern. Ein Beitrag mit mehr
# Bildern wuerde erst beim Veroeffentlichen abprallen — also nach der
# Freigabe, am schlechtesten Zeitpunkt.
BILDER_MAX = 20

LOG = logging.getLogger("sales-linkedin")


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


def _ungewiss_loggen(geclaimt, medienart, grund) -> None:
    """Beleg fuer einen Versuch mit unbekanntem Ausgang.

    Bewusst DIESELBE Zeilenart wie ein Erfolg (`type='versand'`), denn sie
    hat dieselbe Wirkung: dieser Entwurf wird nicht noch einmal gepostet.
    Unterschieden wird im Payload — `ungewiss: true` und `beitrag: null`.
    Wer die Zeile liest, sieht sofort, dass hier ein Mensch nachsehen muss,
    und niemand haelt sie faelschlich fuer eine belegte Veroeffentlichung.
    """
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": "linkedin",
                     "weg": "linkedin-dispatcher",
                     "empfaenger": "eigenes-profil", "beitrag": None,
                     "ungewiss": True, "medienart": medienart,
                     "grund": grund}, ensure_ascii=False)))


def bereits_veroeffentlicht(draft_id):
    """Beitrags-Kennung, falls fuer diesen Entwurf schon gepostet wurde.

    DIE Schutzkante gegen einen zweiten Beitrag — und sie fragt bewusst
    `activities` und nicht `drafts.status`.

    `activities` ist append-only: in der Produktion hat die Rolle dort nur
    INSERT und SELECT. Eine einmal geschriebene Zeile verschwindet also nie
    wieder und laesst sich auch nicht nachtraeglich schoenen.
    `drafts.status` dagegen ist zuruecksetzbar: `entwurf_erneut_freigeben`
    holt einen `failed`-Entwurf mit `bestaetigt=True` zurueck auf
    `approved` — ausdruecklich unter Inkaufnahme eines Doppelversands. Bei
    WhatsApp ist das eine vertretbare Betreiberentscheidung, weil der
    Empfaenger eine Nachricht doppelt bekommt. Auf einem oeffentlichen
    Profil ist es ein zweiter Beitrag, den jeder Leser sieht — und der
    Betreiber kann VORHER nirgends nachschlagen, ob der erste durchkam.

    Genau dafuer gibt es diese Abfrage. Sie macht das Doppelposten
    konstruktiv unmoeglich statt es durch Disziplin zu verhindern.
    """
    zeilen = server._q(
        "select payload from activities where type = 'versand' "
        "and payload->>'kanal' = 'linkedin' "
        "and payload->>'draft_id' = %s limit 1", (str(draft_id),))
    if not zeilen:
        return None
    last = zeilen[0]["payload"] or {}
    if isinstance(last, str):        # je nach Treiber Text statt dict
        last = json.loads(last)
    if last.get("ungewiss"):
        return ("ungewisser Ausgang eines frueheren Versuchs — auf dem "
                "Profil nachsehen")
    # Auch ohne lesbare Kennung ist die ZEILE die Aussage: es ging raus.
    return last.get("beitrag") or "unbekannte Beitrags-Kennung"


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
    """Ein Beitrag: pruefen, claimen, Medien laden, veroeffentlichen, buchen."""
    # VOR dem Claim, nicht danach: ein Entwurf, der schon draussen ist, soll
    # gar nicht erst angefasst werden — kein Statuswechsel, keine Marke, kein
    # Rauschen in der Freigabe-Anzeige. Das Rennen zweier Laeufer faengt
    # trotzdem der Claim ab: er ist atomar, nur einer gewinnt.
    schon = bereits_veroeffentlicht(draft_id)
    if schon:
        LOG.warning("draft=%s NICHT erneut gepostet — bereits veroeffentlicht "
                    "als %s", draft_id, schon)
        return "schon_veroeffentlicht"

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

    # Hochladen zuerst und GETRENNT: ein Upload veroeffentlicht nichts, ein
    # Fehler dabei ist also eindeutig — es steht garantiert nichts auf dem
    # Profil. Deshalb braucht er keine Ungewissheits-Behandlung.
    try:
        bild_urns, video_urn = medien_hochladen(bilder, video)
    except linkedin_api.LinkedInFehler as e:
        _als_fehler_buchen(draft_id, marke, _einzeilig(str(e))[:500])
        LOG.info("draft=%s Medien fehlgeschlagen, nichts veroeffentlicht (%s)",
                 draft_id, _einzeilig(str(e))[:160])
        return "fehler"

    # Und jetzt der eine Aufruf, der etwas oeffentlich macht.
    try:
        beitrag = linkedin_api.beitrag_erstellen(text, bilder=bild_urns,
                                                 video=video_urn)
    except linkedin_api.LinkedInFehler as e:
        if e.ungewiss:
            # DER FALL, DEN DAS SPERRGATE DES PROXMOX-RUNBOOKS „unbekannter
            # externer Erfolgszustand" nennt. Wir haben keine Antwort
            # gesehen — der Beitrag KANN oeffentlich stehen. Ihn als blossen
            # Fehler zu buchen waere die gefaehrlichste Luege dieses
            # Dienstes: der Entwurf sieht dann wiederholbar aus, und der
            # naechste Lauf postete ein zweites Mal.
            #
            # Deshalb entsteht hier derselbe Beleg wie bei einem Erfolg, nur
            # ohne Kennung und mit `ungewiss`. Er sperrt jede Wiederholung.
            # Aufloesen kann das nur ein Mensch, der auf dem Profil nachsieht.
            grund = _einzeilig(str(e))[:300]
            try:
                _ungewiss_loggen(geclaimt, art, grund)
            except psycopg.Error as db:
                LOG.critical("draft=%s UNGEWISSER AUSGANG und der Nachweis "
                             "liess sich nicht schreiben (%s) — auf dem "
                             "Profil nachsehen, BEVOR dieser Entwurf erneut "
                             "angefasst wird. Grund: %s",
                             draft_id, _einzeilig(str(db)), grund)
                return "ungewiss_ohne_nachweis"
            _als_fehler_buchen(draft_id, marke, (
                f"UNGEWISS: keine Antwort von LinkedIn gesehen. Der Beitrag "
                f"KANN oeffentlich stehen. Erneutes Freigeben aendert daran "
                f"nichts — dieser Dienst wird ihn nicht noch einmal posten. "
                f"Auf dem Profil nachsehen und dann entscheiden. {grund}"))
            LOG.critical("draft=%s UNGEWISSER AUSGANG — Profil pruefen: %s",
                         draft_id, grund)
            return "ungewiss"
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

    # DER BELEG ZUERST, DIE BUCHUNG DANACH. Die Reihenfolge ist der Punkt:
    # `activities` ist append-only und damit der haltbare Nachweis, dass
    # dieser Beitrag draussen ist. Stand er frueher hinter der Buchung, gab
    # es bei gescheiterter Buchung UEBERHAUPT KEINEN Nachweis in der
    # Datenbank — die Beitrags-Kennung existierte nur in einer Logzeile, und
    # `bereits_veroeffentlicht` haette den Entwurf spaeter durchgewinkt.
    try:
        _versand_loggen(geclaimt, beitrag, art)
    except psycopg.Error as e:
        # Der schlimmste Fall, den es hier noch gibt: draussen, aber ohne
        # Nachweis. Die Kennung steht wenigstens im Log — laut und in einer
        # Zeile, die einen Menschen ruft.
        LOG.critical("draft=%s VEROEFFENTLICHT als %s, aber der Nachweis "
                     "liess sich nicht schreiben: %s — diese Kennung von "
                     "Hand sichern, bevor der Entwurf erneut angefasst wird",
                     draft_id, beitrag, _einzeilig(str(e)))
        return "veroeffentlicht_ohne_nachweis"

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
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


def wartende_beitraege():
    """Welche Beitraege waeren freigegeben? Nur Lesen, veroeffentlicht nichts.

    Fuer den Betreiber, damit er die Kennung findet, die er dem Dienst
    nennen will — und damit er sieht, was sonst noch auf `approved` steht.
    """
    return server._q(
        "select id, subject, media_ref, approved_at from drafts "
        "where status = 'approved' and channel = 'linkedin' "
        "and recipient = 'eigenes-profil' order by created_at")


def heute_schon_veroeffentlicht() -> bool:
    """Tageskadenz (Betreiber, 27.08.2026: ein Beitrag pro Tag).

    Gezaehlt werden die NACHWEISE in `activities`, nicht drafts.status —
    derselbe Grund wie bei `bereits_veroeffentlicht`: der Status ist
    zuruecksetzbar, der Nachweis nicht.
    """
    return bool(server._q(
        "select 1 from activities where type = 'versand' "
        "and payload->>'kanal' = 'linkedin' "
        "and created_at >= date_trunc('day', now()) limit 1"))


def eine_runde() -> str:
    """Ein Durchgang: hoechstens EIN Beitrag. Gibt den Ausgang zurueck.

    `veroeffentlicht` | `kadenz` (heute war schon einer) | `nichts` (keiner
    freigegeben oder alle zu alt) | die Ausgaenge von `verarbeite_draft`.
    """
    if DRAFT_ID:
        # Handbetrieb: der Mensch hat GENAU diesen Beitrag gemeint — die
        # Kadenz ist eine Regel fuer den Automatismus, nicht fuer ihn.
        return verarbeite_draft(DRAFT_ID)

    if heute_schon_veroeffentlicht():
        return "kadenz"

    zu_alt = 0
    for beitrag in wartende_beitraege():
        freigabe = beitrag.get("approved_at")
        if freigabe is not None:
            alter_tage = (datetime.now(timezone.utc) - freigabe).days
            if alter_tage > LINKEDIN_FRISCHE_TAGE:
                zu_alt += 1
                continue
        return verarbeite_draft(str(beitrag["id"]))

    if zu_alt:
        LOG.warning(
            "%d freigegebene(r) Beitrag/Beitraege sind aelter als %d Tage "
            "und bleiben liegen — wer sie will, gibt sie erneut frei "
            "(Freigabe-Inbox). Es wurde NICHTS veroeffentlicht.",
            zu_alt, LINKEDIN_FRISCHE_TAGE)
    return "nichts"


# ---------------------------------------------------------------------------
# Betrieb
# ---------------------------------------------------------------------------

_STOPP = threading.Event()


def _stopp_anfordern(signum, _rahmen) -> None:
    """SIGTERM/SIGINT beenden die Schleife NACH der laufenden Runde.

    Ein Abbruch mitten in einem Upload waere genau der ungewisse Ausgang,
    gegen den der Nachweis-vor-Buchung-Weg gebaut ist.
    """
    LOG.info("%s empfangen — nach dieser Runde ist Schluss.",
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

    if DRAFT_ID and not _KENNUNG.match(DRAFT_ID):
        LOG.error("LINKEDIN_DRAFT_ID ist keine Entwurfs-Kennung (UUID "
                  "erwartet). Es wurde nichts veroeffentlicht.")
        return 2

    if DRAFT_ID:
        # Handbetrieb: genau ein genannter Beitrag, dann Schluss.
        # Weder Token noch Person-Kennung ins Log: das eine ist ein
        # Geheimnis, das andere ein Personenbezug.
        LOG.info("Start: schema=%s api-version=%s draft=%s — genau ein "
                 "Beitrag.", server.SCHEMA, linkedin_api.VERSION, DRAFT_ID)
        try:
            ausgang = eine_runde()
        except psycopg.Error as e:
            LOG.error("Datenbankfehler — es wurde nichts veroeffentlicht: %s",
                      _einzeilig(str(e)))
            return 1
        LOG.info("Ausgang: %s", ausgang)
        return 0

    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    LOG.info("Start: schema=%s api-version=%s intervall=%gs frische=%dd "
             "once=%s — Freigabe ist der Versand, hoechstens einer pro Tag.",
             server.SCHEMA, linkedin_api.VERSION, LINKEDIN_INTERVAL_S,
             LINKEDIN_FRISCHE_TAGE, LINKEDIN_ONCE)
    while not _STOPP.is_set():
        try:
            ausgang = eine_runde()
        except psycopg.Error as e:
            # Ein DB-Ausfall beendet den Dienst nicht: er kommt wieder, und
            # bis dahin bleibt jeder freigegebene Beitrag unangetastet.
            LOG.error("Datenbank nicht erreichbar: %s", _einzeilig(str(e)))
            ausgang = "db-ausfall"
        # `nichts` und `kadenz` sind der Normalzustand und wuerden das Log
        # sonst jede Minute fluten.
        if ausgang not in ("nichts", "kadenz"):
            LOG.info("Ausgang: %s", ausgang)
        if LINKEDIN_ONCE:
            return 0
        _STOPP.wait(LINKEDIN_INTERVAL_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
