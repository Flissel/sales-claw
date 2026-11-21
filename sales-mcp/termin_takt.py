"""Taktgeber sales-termine (Meeting-Mittelpunkt, Spec §5).

Alle `TERMIN_TAKT_S` Sekunden (Vorgabe 30) eine Runde, jeder Schritt mit eigenem
`try`, damit ein Fehler den Rest nicht stoppt:

  1. Termin-Akten abgleichen
  2. Briefing 30 Minuten vorher (und einmal Telegram-Hinweis)
  3. Vexa-Bot 1 Minute vorher schicken
  4. Bot verfolgen; fertig -> Mitschrift holen, ablegen, bei Vexa loeschen;
     nach Terminende und `VEXA_STILLE_NACH_ENDE_MIN` Minuten Stille den Bot
     stoppen (Jitsi meldet das Gehen aller nicht)
  5. Bei Vexa nachraeumen: Bot stoppen (nach "Nein", Loeschantrag, Verschiebung)
     und Meeting loeschen, was beim Abholen liegen blieb
  6. Eine offene Mitschrift mit dem lokalen Ollama auswerten (nicht kurz vor
     oder waehrend eines Termins mit Bot - der Takt soll dann nicht stehen)
  7. Mitschriften-Ablage: eine fertige Mitschrift per KI einer Rubrik zuordnen
     (gleiche Pause wie 6), einen Bericht (neu) ablegen, hoechstens stuendlich
     Dateien und Buchungen abgleichen (`mitschrift_bericht.abgleichen`)

Daneben laufen die Threads des schnellen Pausenwegs der Meeting-Steuerseite
(`termin_pause.starten`: Pause/Weiter/Notbremse jede Sekunde, Live-Transkript
alle 5 s und Betreiber-Hinweise - je ein eigener Thread).

NUR DER TAKTGEBER SPRICHT MIT VEXA (Final-Review C1): Oberflaeche und MCP haben
keinen VEXA_API_KEY; sie setzen nur Status und lassen die Vexa-Ids stehen.
Schritt 5 stoppt den Bot und loescht das Meeting.

STATUS (Final-Review I2): jeder Statuswechsel ist bedingt
(`termin_akte.status_wechseln`) - ein "Nein" aus der Oberflaeche gewinnt immer,
auch wenn es zwischen Vexa-Aufruf und Speichern faellt; die Vexa-Ids gehen
dabei nie verloren.

REIHENFOLGE (Schritt 4): Mitschrift-Insert und Status `fertig` in EINER Transaktion
(Akte mit `for update` gesperrt, nur aus wartet_auf_einlass/laeuft),
`meeting_loeschen` erst NACH dem Commit; scheitert es, bleibt `vexa_meeting_id`
stehen und Schritt 5 loescht nach.

LOGS: nur uid-Hash (sha256, 8 Zeichen), Status und Zaehler - nie Adressen,
Namen, Links, Passcodes, Segment- oder Auswertungstext, Schluessel. Bei
Ausnahmen steht nur der Typname im Log (der Text koennte Kundendaten tragen).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import auswertung
import bildschirm
import betreiber_hinweis
import briefing
import kurs_handbuch
import kurs_mitschrift
import mitschrift_bereinigen
import mitschrift_bericht
import mitschrift_einordnung
import ollama
import server
import termin_akte
import termin_pause
import vexa

LOG = logging.getLogger("sales-termine")

TAKT_STANDARD_S = 30
BRIEFING_VOR = timedelta(minutes=30)
BOT_VOR = timedelta(seconds=60)
NEUVERSUCH_NACH = timedelta(hours=1)
MAX_AUSWERTUNGEN = 3
# I7a: keine Auswertung, wenn ein Termin mit Bot so bald beginnt oder laeuft
AUSWERTUNG_PAUSE_VOR = timedelta(minutes=15)
# I7b: Briefing ohne KI-Text hoechstens so oft neu versuchen (Fakten gleich)
BRIEFING_KI_PAUSE = timedelta(minutes=5)
# Status, aus denen ein Bot laeuft oder anstehen kann
BOT_STATUS = ("wartet_auf_einlass", "laeuft")
# Abnahme 12.11.2026: Bot nach Terminende stoppen, wenn so lange niemand spricht
STILLE_NACH_ENDE_STANDARD_MIN = 10.0

_STOPP = threading.Event()
# Letzter bekannter Zustand je Gegenstelle, damit nur der WECHSEL geloggt wird.
_zustand: dict[str, bool] = {}


def _h(uid: str) -> str:
    return hashlib.sha256(uid.encode()).hexdigest()[:8]


def _wechsel(name: str, ok: bool, text_ok: str, text_aus: str) -> None:
    if _zustand.get(name) is not ok:
        _zustand[name] = ok
        LOG.info(text_ok if ok else text_aus)


def _felder(uid: str, **felder) -> None:
    """Spalten der Akte setzen, ohne Status und geaendert_am anzufassen."""
    unbekannt = set(felder) - termin_akte.FELDER
    if unbekannt:
        raise ValueError(f"Unbekannte Felder: {sorted(unbekannt)}")
    namen = sorted(felder)
    server._q(f"update termin_akten set {', '.join(f'{n} = %s' for n in namen)} "
              "where uid = %s returning uid", (*[felder[n] for n in namen], uid))


def _je_akte(schritt: str, uid: str, fn) -> bool:
    """Ein Fehler bei einer Akte stoppt die naechste nicht."""
    try:
        fn()
        return True
    except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
        LOG.warning("%s uid=%s fehlgeschlagen (%s)", schritt, _h(uid), type(e).__name__)
        return False


# ---------- 1. Abgleich ----------

def _abgleichen(jetzt: datetime):
    return termin_akte.abgleichen(jetzt)


# ---------- 2. Briefing ----------

def _briefing(jetzt: datetime) -> int:
    ui_basis = os.environ.get("UI_BASIS_URL", "").strip().rstrip("/")
    zeilen = server._q(
        "select uid, briefing_stand, briefing_mit_ki, briefing_am, hinweis_gesendet_am "
        "from termin_akten "
        "where abgesagt_am is null and beginn > %s and beginn <= %s order by beginn",
        (jetzt, jetzt + BRIEFING_VOR))
    getan = 0
    ki: list[bool] = []          # Ollama hoechstens einmal je Runde fragen

    def ki_da() -> bool:
        if not ki:
            ki.append(ollama.erreichbar())
        return ki[0]

    def neu_erstellen(z):
        stand = z["briefing_stand"]
        # Nur neu, wenn die Fakten sich geaendert haben - oder das Briefing ohne
        # KI-Text entstand, die Pause (I7b) um ist und Ollama jetzt da ist.
        if stand and stand == briefing.stand_von(briefing.fakten(z["uid"])):
            if z["briefing_mit_ki"] is not False:
                return False
            if z["briefing_am"] is not None and z["briefing_am"] > jetzt - BRIEFING_KI_PAUSE:
                return False
            if not ki_da():
                return False
        b = briefing.erstellen(z["uid"])
        _felder(z["uid"], briefing_md=b["markdown"], briefing_stand=b["stand"],
                briefing_mit_ki=b["mit_ki"], briefing_am=jetzt)
        return True

    def hinweis(z):
        akte = termin_akte.lesen(z["uid"])
        if akte is None or akte["abgesagt"]:
            return
        if betreiber_hinweis.senden(briefing.hinweis_text(akte, ui_basis)) is True:
            _felder(z["uid"], hinweis_gesendet_am=jetzt)

    for z in zeilen:
        uid = z["uid"]
        ergebnis: list[bool] = []
        if _je_akte("Briefing", uid, lambda: ergebnis.append(neu_erstellen(z))):
            getan += bool(ergebnis and ergebnis[0])
        if z["hinweis_gesendet_am"] is None:
            _je_akte("Hinweis", uid, lambda: hinweis(z))
    return getan


# ---------- 3. Bot ----------

def _bot_starten(uid: str, link: str, jetzt: datetime) -> None:
    if termin_akte.hat_gesperrte(uid):
        termin_akte.status_wechseln(uid, ("geplant",), "ohne_aufnahme",
                                    "gesperrter Teilnehmer")
        return
    # Akte ZUERST beanspruchen: nur wer sie von 'geplant' weiterschaltet, schickt
    # den Bot. Ein zweiter Aufruf (Rennen, Neustart) findet keine Zeile. Stehen
    # noch Ids eines alten Bots, raeumt erst Schritt 5 auf.
    # Final-Review I1: eine neue Bot-Sitzung beginnt immer mit "Aufnahme an" - ein
    # Wunsch, eine Bestaetigung oder ein Fehler aus einer frueheren Sitzung (Akte
    # nach Verschiebung wieder 'geplant') gilt nicht weiter.
    if not server._q(
            "update termin_akten set status = 'wartet_auf_einlass', status_grund = null, "
            "bot_geschickt_am = now(), geaendert_am = now(), "
            "aufnahme_wunsch = 'an', aufnahme_wunsch_am = null, "
            "aufnahme_pausiert_seit = null, aufnahme_pause_fehler = null, "
            "aufnahme_notbremse_am = null "
            "where uid = %s and status = 'geplant' and vexa_meeting_id is null "
            "and vexa_native_id is null returning uid", (uid,)):
        return
    # Eine noch offene Pause der alten Sitzung (sonst schliesst sie termin_pause._aufraeumen)
    # endet jetzt - sie wuerde sonst die ganze neue Sitzung wegfiltern.
    # Rennen: ein Klick zwischen Claim und hier oeffnet eine Zeile mit von > bot_geschickt_am;
    # die gehoert zur neuen Sitzung und bleibt offen.
    server._q("update termin_pausen set bis = greatest(now(), von) "
              "where uid = %s and bis is null "
              "and von < (select bot_geschickt_am from termin_akten where uid = %s) "
              "returning id", (uid, uid))
    try:
        m = vexa.bot_schicken(link)
    except vexa.VexaFehler:
        termin_akte.status_wechseln(uid, ("wartet_auf_einlass",), "fehlgeschlagen",
                                    "Bot konnte nicht starten")
        return
    ids = {"vexa_meeting_id": m["meeting_id"], "vexa_plattform": m["plattform"],
           "vexa_native_id": m["native_id"]}
    try:
        if not termin_akte.status_wechseln(uid, ("wartet_auf_einlass",), "wartet_auf_einlass",
                                           bot_geschickt_am=jetzt, **ids):
            # Inzwischen "Nein" (I2): Status bleibt, aber die Ids muessen in die
            # Akte, damit Schritt 5 den Bot wieder herausholt.
            termin_akte.felder_setzen(uid, **ids)
            LOG.info("Bot gestartet nach Statuswechsel uid=%s - wird gestoppt", _h(uid))
    except Exception as e:  # noqa: BLE001
        # Der Bot laeuft schon, die Akte weiss es nicht: wegnehmen, nie still.
        LOG.warning("Bot gestartet, Speichern gescheitert uid=%s (%s) - raeume auf",
                    _h(uid), type(e).__name__)
        for aufraeumen in (lambda: vexa.bot_stoppen(m["plattform"], m["native_id"]),
                           lambda: vexa.meeting_loeschen(m["meeting_id"])):
            try:
                aufraeumen()
            except Exception as e2:  # noqa: BLE001
                LOG.warning("Aufraeumen nach Bot-Start gescheitert uid=%s (%s)",
                            _h(uid), type(e2).__name__)


def _bot(jetzt: datetime) -> int:
    konf = vexa.konfiguriert()
    zeilen = server._q(
        "select uid, link from termin_akten "
        "where status = 'geplant' and coalesce(link, '') <> '' and not kein_bot "
        "and vexa_meeting_id is null and vexa_native_id is null "
        "and abgesagt_am is null and beginn <= %s and ende > %s order by beginn",
        (jetzt + BOT_VOR, jetzt))
    if zeilen:
        _wechsel("vexa", konf, "Vexa konfiguriert",
                 "Vexa nicht konfiguriert (VEXA_API_KEY fehlt) - kein Bot")
    getan = 0
    if konf:
        getan = sum(_je_akte("Bot", z["uid"],
                             lambda z=z: _bot_starten(z["uid"], z["link"], jetzt))
                    for z in zeilen)
    # Vorbei und nie aufgenommen: nicht ewig 'geplant' lassen - auch mit Vexa
    # (z. B. Taktgeber war aus, Bot-Fenster verpasst).
    for z in server._q(
            "select uid, kein_bot from termin_akten "
            "where status = 'geplant' and coalesce(link, '') <> '' and abgesagt_am is null "
            "and ende <= %s", (jetzt,)):
        grund = ("kein Bot gewuenscht" if z["kein_bot"]
                 else "Termin vorbei ohne Bot" if konf else "Vexa nicht konfiguriert")
        getan += _je_akte("Ende", z["uid"],
                          lambda z=z, g=grund: termin_akte.status_wechseln(
                              z["uid"], ("geplant",), "ohne_aufnahme", g))
    return getan


# ---------- 4./5. Verfolgen, Abholen, Loeschen ----------

def _vexa_loeschen(uid: str, meeting_id: int) -> bool:
    """Bei Vexa loeschen, dann die Id vergessen. Scheitert das Loeschen, bleibt
    die Id stehen (Schritt 5 versucht es wieder)."""
    try:
        vexa.meeting_loeschen(meeting_id)
    except vexa.VexaNichtErreichbar:
        return False            # vexa meldet den Ausfall selbst, einmal (I9)
    except vexa.VexaFehler:
        LOG.warning("Loeschen bei Vexa gescheitert uid=%s (Neuversuch folgt)", _h(uid))
        return False
    _felder(uid, vexa_meeting_id=None)
    return True


def _mitschrift_ablegen(uid: str, segmente: list[dict],
                        ende_am: datetime | None = None) -> bool:
    """Mitschrift und Status `fertig` gemeinsam oder gar nicht -> abgelegt?

    Die Akte ist in der Transaktion gesperrt (`for update`): steht sie nicht
    mehr auf wartet_auf_einlass/laeuft (z. B. "Nein" in der Oberflaeche), wird
    die Mitschrift verworfen (I2) und die Vexa-Ids bleiben fuer Schritt 5. Mit
    `fertig` faellt die Bot-Kennung (Plattform/native Id) weg - der Bot ist
    gegangen; nur die Meeting-Id bleibt zum Loeschen.

    Die Segmente werden VOR dem Insert bereinigt: ihre Indizes in der
    gespeicherten Mitschrift sind Bezug fuer Auswertung und Vorschaubilder.

    Pausen (Meeting-Steuerseite, R4/R11): unter der Sperre fallen erst alle
    Segmente weg, die ein Pausenfenster beruehren (`termin_pause.pausen_filtern`,
    VOR dem Bereinigen - das verbindet Bruchstuecke). Eine noch offene Pause
    (Ende waehrend der Pause, auch nach Notbremse) schliesst mit bis =
    TATSAECHLICHES Ende `ende_am` (R12: Erkennung des Endes, Vorgabe jetzt; nie
    vor `von`); die Live-Ablage der Akte wird mit `fertig` geleert."""
    ende_am = ende_am or _uhr()
    roh = len(segmente)
    with server.pool.connection() as conn:
        with conn.transaction():
            z = conn.execute("select status, ende from termin_akten where uid = %s for update",
                             (uid,)).fetchone()
            if not z or z["status"] not in BOT_STATUS:
                return False
            pausen = conn.execute("select von, bis from termin_pausen where uid = %s "
                                  "order by von", (uid,)).fetchall()
            segmente = termin_pause.pausen_filtern(segmente, pausen)
            if len(segmente) != roh:
                LOG.info("Mitschrift uid=%s: %d Segmente aus Pausen verworfen",
                         _h(uid), roh - len(segmente))
            segmente = mitschrift_bereinigen.bereinigen(segmente)
            conn.execute(
                "insert into termin_mitschriften (uid, segmente, auswertung_status) "
                "values (%s, %s::jsonb, %s) on conflict (uid) do nothing",
                (uid, json.dumps(segmente), "offen" if segmente else "leer"))
            if conn.execute(
                    "update termin_akten set status = 'fertig', status_grund = null, "
                    "vexa_plattform = null, vexa_native_id = null, "
                    "geaendert_am = now() where uid = %s "
                    "and status in ('wartet_auf_einlass', 'laeuft')", (uid,)).rowcount != 1:
                raise RuntimeError("Status inzwischen geaendert")   # rollt den Insert zurueck
            conn.execute("update termin_pausen set bis = greatest(%s::timestamptz, von) "
                         "where uid = %s and bis is null", (ende_am, uid))
            conn.execute("delete from termin_live_segmente where uid = %s", (uid,))
    return True


def _stille_nach_ende() -> timedelta:
    try:
        minuten = float(os.environ.get("VEXA_STILLE_NACH_ENDE_MIN", "")
                        or STILLE_NACH_ENDE_STANDARD_MIN)
    except ValueError:
        minuten = STILLE_NACH_ENDE_STANDARD_MIN
    return timedelta(minutes=max(minuten, 1.0))


# Vexa-Zeit -> aware datetime; dieselbe Umrechnung nutzt der Pausenfilter.
_zeitpunkt = termin_pause.zeitpunkt


def _nach_ende_stoppen(z: dict, jetzt: datetime) -> None:
    """Sicherung (Abnahme 12.11.2026): Auf Jitsi merkte Vexa nicht, dass alle
    gegangen waren - der Bot blieb allein im Raum, das Meeting `active`, und
    Mitschrift und Auswertung kamen nie. Darum: ist das Terminende vorbei und
    seit `VEXA_STILLE_NACH_ENDE_MIN` (Vorgabe 10) Minuten nichts mehr gesagt,
    stoppt der Taktgeber den Bot. Vexa schliesst das Meeting dann ab, und die
    naechste Runde holt die Mitschrift wie gewohnt. Wer ueberzieht, verliert
    nichts, solange gesprochen wird. Einmal je Akte; scheitert der Aufruf,
    versucht es die naechste Runde."""
    uid = z["uid"]
    if _zustand.get(f"nach_ende_gestoppt:{uid}"):
        return
    if not (z.get("vexa_plattform") and z.get("vexa_native_id") and z.get("ende")):
        return
    stille = _stille_nach_ende()
    if jetzt < z["ende"] + stille:
        return                                    # vor Ende + Stille: nichts holen
    try:
        segmente = vexa.segmente_holen(z["vexa_meeting_id"])
    except vexa.VexaFehler:
        return
    zeiten = [t for t in (_zeitpunkt(s.get("beginn") or "") for s in segmente) if t]
    if zeiten and max(zeiten) + stille > jetzt:
        return                                    # es wird noch gesprochen
    try:
        vexa.bot_stoppen(z["vexa_plattform"], z["vexa_native_id"])
    except vexa.VexaFehler as e:
        LOG.warning("Bot nach Terminende stoppen uid=%s fehlgeschlagen (%s)",
                    _h(uid), type(e).__name__)
        return
    _zustand[f"nach_ende_gestoppt:{uid}"] = True
    LOG.info("Bot nach Terminende und Stille gestoppt uid=%s", _h(uid))


def _verfolgen_eine(z: dict, jetzt: datetime | None = None) -> int:
    uid, mid = z["uid"], z["vexa_meeting_id"]
    if mid is None:
        return int(termin_akte.status_wechseln(uid, BOT_STATUS, "fehlgeschlagen",
                                               "Keine Vexa-Meeting-Id"))
    try:
        m = vexa.meeting_lesen(mid)
    except vexa.VexaNichtGefunden:
        return int(termin_akte.status_wechseln(uid, BOT_STATUS, "fehlgeschlagen",
                                               "Meeting bei Vexa nicht mehr vorhanden"))
    except vexa.VexaFehler:
        return 0                                  # naechste Runde
    if m["status"] == "failed":
        return int(termin_akte.status_wechseln(
            uid, BOT_STATUS, "fehlgeschlagen",
            m["grund"] or m["ende_grund"] or "Bot ist gescheitert"))
    if m["status"] == "completed":
        try:
            segmente = vexa.segmente_holen(mid)
        except vexa.VexaFehler:
            return 0                              # nichts geaendert, Wiederholung
        # R12: Ende = jetzt erkannt; die Runde kann Minuten alt sein -> frische Uhr
        ende_am = max(jetzt, _uhr()) if jetzt is not None else _uhr()
        if not _mitschrift_ablegen(uid, segmente, ende_am=ende_am):
            LOG.info("Mitschrift verworfen uid=%s (Status inzwischen geaendert)", _h(uid))
            return 1                              # Schritt 5 raeumt bei Vexa auf
        LOG.info("Mitschrift abgelegt uid=%s segmente=%d", _h(uid), len(segmente))
        _vexa_loeschen(uid, mid)                  # strikt nach dem Commit
        return 1
    neu = vexa.abbilden(m["status"])
    if neu == "laeuft" and jetzt is not None:
        _nach_ende_stoppen(z, jetzt)
    if neu != z["status"]:
        return int(termin_akte.status_wechseln(uid, (z["status"],), neu))
    return 0


def _verfolgen(jetzt: datetime) -> int:
    zeilen = server._q(
        "select uid, status, ende, vexa_meeting_id, vexa_plattform, vexa_native_id "
        "from termin_akten where status in ('wartet_auf_einlass', 'laeuft') order by beginn")
    erg: list[int] = []
    for z in zeilen:
        _je_akte("Verfolgen", z["uid"], lambda z=z: erg.append(_verfolgen_eine(z, jetzt)))
    return sum(erg)


def _nachloeschen_eine(z: dict) -> bool:
    """Erst den Bot stoppen (404 = schon weg), dann das Meeting loeschen, dann
    die Ids vergessen - nur wenn sie noch dieselben sind (ein neuer Bot der
    Akte behaelt seine). Scheitert Vexa, bleiben die Ids: naechste Runde."""
    uid = z["uid"]
    try:
        if z["vexa_plattform"] and z["vexa_native_id"]:
            vexa.bot_stoppen(z["vexa_plattform"], z["vexa_native_id"])
            # Bot ist weg: Kennung sofort vergessen, damit ein haengendes
            # Meeting-Loeschen nicht alle 30 s erneut DELETE /bots schickt.
            server._q(
                "update termin_akten set vexa_plattform = null, vexa_native_id = null "
                "where uid = %s and vexa_meeting_id is not distinct from %s "
                "and vexa_native_id is not distinct from %s returning uid",
                (uid, z["vexa_meeting_id"], z["vexa_native_id"]))
            z = {**z, "vexa_native_id": None}
        if z["vexa_meeting_id"] is not None:
            vexa.meeting_loeschen(int(z["vexa_meeting_id"]))
    except vexa.VexaNichtErreichbar:
        return False            # vexa meldet den Ausfall selbst, einmal (I9)
    except vexa.VexaFehler as e:
        LOG.warning("Nachraeumen bei Vexa gescheitert uid=%s (%s) - Neuversuch folgt",
                    _h(uid), type(e).__name__)
        return False
    server._q(
        "update termin_akten set vexa_meeting_id = null, vexa_plattform = null, "
        "vexa_native_id = null where uid = %s "
        "and vexa_meeting_id is not distinct from %s "
        "and vexa_native_id is not distinct from %s returning uid",
        (uid, z["vexa_meeting_id"], z["vexa_native_id"]))
    return True


def _nachloeschen(jetzt: datetime) -> int:
    """C1: Jede Akte ohne laufende Aufnahme, an der noch Vexa-Ids haengen -
    nach "Nein", Loeschantrag, Fehlschlag, Abholen oder Verschiebung."""
    zeilen = server._q(
        "select uid, vexa_meeting_id, vexa_plattform, vexa_native_id from termin_akten "
        "where status in ('fertig', 'ohne_aufnahme', 'fehlgeschlagen', 'geplant', 'kein_link') "
        "and (vexa_meeting_id is not null or vexa_native_id is not null) "
        "order by beginn")
    erg: list[bool] = []
    for z in zeilen:
        _je_akte("Nachloeschen", z["uid"], lambda z=z: erg.append(_nachloeschen_eine(z)))
    return sum(erg)


# ---------- 6. Auswerten ----------

def _leads(akte: dict) -> list[tuple[str, str]]:
    """(lead_id, name) der verknuepften Kontakte, in Akten-Reihenfolge; ein JETZT
    gesperrter Kontakt faellt weg (Spec §4)."""
    aus, gesehen = [], set()
    for t in akte["teilnehmer"]:
        lid = t.get("lead_id")
        if not lid or lid in gesehen:
            continue
        gesehen.add(lid)
        z = server._q("select name, email, phone, enrichment from leads "
                      "where id = %s::uuid", (lid,))
        if z and not briefing.gesperrt(z[0]):
            aus.append((lid, z[0]["name"] or ""))
    return aus


def _zusammenfassung(uid: str, akte: dict, a: dict, lead: tuple[str, str]) -> str | None:
    """Entwurf der Kunden-Zusammenfassung (Freigabe bleibt bei Felix). None, wenn
    keiner entsteht; das stoppt die Auswertung nicht."""
    try:
        zone = ZoneInfo(akte.get("zeitzone") or "Europe/Berlin")
    except Exception:  # noqa: BLE001 - unbekannte Zone: Vorgabe
        zone = ZoneInfo("Europe/Berlin")
    datum = akte["beginn"].astimezone(zone).strftime("%d.%m.%Y")
    anrede = f"Guten Tag {lead[1].strip()}".strip()
    try:
        antwort = json.loads(server._entwurf_erstellen(
            lead[0], "email", auswertung.kundenfassung(a, anrede),
            betreff=f"Zusammenfassung unseres Gesprächs vom {datum}",
            termin_bezug=True, thema="termin_zusammenfassung"))
    except Exception as e:  # noqa: BLE001
        LOG.warning("Zusammenfassung uid=%s: kein Entwurf (%s)", _h(uid), type(e).__name__)
        return None
    if not antwort.get("draft_id"):
        LOG.info("Zusammenfassung uid=%s: kein Entwurf (abgelehnt)", _h(uid))
        return None
    return str(antwort["draft_id"])


def _auswerten_eine(m: dict, jetzt: datetime) -> None:
    uid = m["uid"]
    try:
        a = auswertung.auswerten(m["segmente"], bilder=bildschirm.bilder_zeilen(uid))
        md = auswertung.markdown(a)
        akte = termin_akte.lesen(uid)
        leads = _leads(akte) if akte else []
        vorschlaege = auswertung.vorschlaege(a, [lid for lid, _ in leads])
        modell = os.environ.get("OLLAMA_MODELL", "").strip() or ollama.MODELL_STANDARD
        # ERST Ergebnis und Vorschlaege gemeinsam festschreiben, dann der Entwurf:
        # scheitert der, gibt es keine zweite Auswertung und keinen zweiten Entwurf.
        # Die Mitschrift ist gesperrt; wurde sie waehrend der Auswertung
        # verworfen ("Nein", Loeschantrag), entsteht nichts daraus. Haben sich
        # ihre Segmente inzwischen geaendert (Neu-Auswertung), passt das Ergebnis
        # nicht mehr zu den Indizes: verwerfen, die neue Fassung kommt danach dran.
        verworfen = veraltet = False
        with server.pool.connection() as conn:
            with conn.transaction():
                zeile = conn.execute(
                    "select segmente = %s::jsonb as gleich from termin_mitschriften "
                    "where id = %s for update",
                    (json.dumps(m["segmente"]), m["id"])).fetchone()
                if zeile is None or not zeile["gleich"]:
                    verworfen, veraltet = zeile is None, zeile is not None
                    vorschlaege = []
                else:
                    conn.execute(
                        "update termin_mitschriften set auswertung_status = 'fertig', "
                        "auswertung_json = %s::jsonb, auswertung_md = %s, auswertung_am = %s, "
                        "modell = %s where id = %s",
                        (json.dumps(a), md, jetzt, modell, m["id"]))
                for v in vorschlaege:
                    conn.execute(
                        "insert into termin_vorschlaege (mitschrift_id, art, lead_id, daten) "
                        "values (%s, %s, %s, %s::jsonb)",
                        (m["id"], v["art"], v["lead_id"], json.dumps(v["daten"])))
    except Exception as e:  # noqa: BLE001 - OllamaFehler und alles andere
        server._q("update termin_mitschriften set auswertung_status = 'fehler', "
                  "auswertung_versuche = auswertung_versuche + 1, auswertung_am = %s "
                  "where id = %s returning id", (jetzt, m["id"]))
        LOG.warning("Auswertung uid=%s fehlgeschlagen (%s)", _h(uid), type(e).__name__)
        return
    if verworfen:
        LOG.info("Auswertung uid=%s: Mitschrift verworfen waehrend Auswertung", _h(uid))
        return
    if veraltet:
        LOG.info("Auswertung uid=%s: Segmente geaendert waehrend Auswertung - verworfen",
                 _h(uid))
        return
    entwurf = None
    # Internes Gespraech (art "intern"): keine Zusammenfassung an einen Kunden,
    # Ergebnis und Wiedervorlagen oben entstehen trotzdem.
    if (akte and akte["will_zusammenfassung"] and a.get("art") != "intern"
            and leads and m["entwurf_id"] is None):
        try:
            entwurf = _zusammenfassung(uid, akte, a, leads[0])
            if entwurf:
                server._q("update termin_mitschriften set entwurf_id = %s where id = %s "
                          "returning id", (entwurf, m["id"]))
        except Exception as e:  # noqa: BLE001 - nie zurueck in die Auswertung
            LOG.warning("Entwurf-Verknuepfung uid=%s gescheitert (%s)", _h(uid),
                        type(e).__name__)
    LOG.info("Auswertung fertig uid=%s vorschlaege=%d entwurf=%s",
             _h(uid), len(vorschlaege), entwurf is not None)


def _termin_steht_an(jetzt: datetime) -> bool:
    """I7a: beginnt bald ein Termin mit Bot oder laeuft einer? Dann wartet die
    Auswertung (ein Ollama-Aufruf kann Minuten dauern, der Bot nicht)."""
    return bool(server._q(
        "select 1 from termin_akten where abgesagt_am is null "
        "and coalesce(link, '') <> '' and not kein_bot "
        "and status in ('geplant', 'wartet_auf_einlass', 'laeuft') "
        "and beginn <= %s and ende > %s limit 1",
        (jetzt + AUSWERTUNG_PAUSE_VOR, jetzt)))


def _uhr() -> datetime:
    """Aktuelle Zeit (in Tests ersetzbar). Spaete Schritte einer Runde laufen u. U. Minuten
    nach deren Beginn (`jetzt`), weil Briefing und Auswertung davor KI-Auftraege hatten."""
    return datetime.now(timezone.utc)


def _termin_naht(jetzt: datetime) -> bool:
    """Wie `_termin_steht_an`, zusaetzlich mit frischer Uhrzeit (Final-Fix I2)."""
    return _termin_steht_an(jetzt) or _termin_steht_an(_uhr())


def _auswerten(jetzt: datetime) -> int:
    if _termin_steht_an(jetzt):
        return 0
    kandidaten = server._q(
        "select id, uid, segmente, entwurf_id from termin_mitschriften "
        "where auswertung_status = 'offen' or (auswertung_status = 'fehler' "
        "and auswertung_versuche < %s and auswertung_am <= %s) "
        "order by (auswertung_status = 'fehler'), geholt_am, id limit 1",
        (MAX_AUSWERTUNGEN, jetzt - NEUVERSUCH_NACH))
    if not kandidaten or not _ollama_da():
        return 0
    return int(_je_akte("Auswertung", kandidaten[0]["uid"],
                        lambda: _auswerten_eine(kandidaten[0], jetzt)))


def _ollama_da() -> bool:
    ok = ollama.erreichbar()
    _wechsel("ollama", ok, "Ollama erreichbar", "Ollama nicht erreichbar - Auswertung wartet")
    return ok


# ---------- 7. Mitschriften-Ablage ----------

ABGLEICH_ALLE = timedelta(hours=1)
# Letzter Datei-Abgleich dieses Prozesses (None: die erste Runde gleicht ab).
_LETZTER_ABGLEICH: datetime | None = None
# uid -> letzter gescheiterter Bericht-Versuch: eine kaputte Mitschrift haelt die
# anderen nicht auf, sie kommt nach NEUVERSUCH_NACH wieder dran.
_bericht_pause: dict[str, datetime] = {}


def _ablage_veraltet(jetzt: datetime) -> int:
    """Hoechstens ein veralteter Bericht je Runde: die Auswertung ist nach einer
    Neu-Auswertung leer oder endgueltig gescheitert (Versuche aufgebraucht) -
    der alte Bericht zeigte die alte Auswertung. Buchung leeren, Datei weg.
    'offen' bleibt unberuehrt (die Neu-Auswertung laeuft noch)."""
    weg = server._q(
        "with alt as (select id, uid, bericht_pfad from termin_mitschriften "
        "where bericht_pfad is not null and (auswertung_status = 'leer' "
        "or (auswertung_status = 'fehler' and auswertung_versuche >= %s)) "
        "order by geholt_am, id limit 1 for update skip locked) "
        "update termin_mitschriften m set bericht_pfad = null, bericht_stand = null, "
        "bericht_am = null from alt where m.id = alt.id "
        "returning alt.uid, alt.bericht_pfad", (MAX_AUSWERTUNGEN,))
    if not weg:
        return 0
    uid, pfad = weg[0]["uid"], weg[0]["bericht_pfad"]
    return int(_je_akte("Bericht veraltet", uid,
                        lambda: mitschrift_bericht.datei_entfernen(pfad)))


def _ablage_einordnen(jetzt: datetime) -> int:
    """Hoechstens eine KI-Einordnung je Runde: ohne Rubrik, oder 'Unsortiert'
    (nicht von Hand) mit faelligem Neuversuch. Nicht vor/waehrend eines Termins
    mit Bot und nicht ohne Ollama - dann bleibt die Rubrik leer."""
    kandidaten = server._q(
        "select uid from termin_mitschriften where auswertung_status = 'fertig' "
        "and (rubrik is null or (rubrik = %s and not rubrik_manuell "
        "and einordnung_versuche < %s and einordnung_am <= %s)) "
        "order by (rubrik is not null), geholt_am, id limit 1",
        (mitschrift_bericht.UNSORTIERT, mitschrift_einordnung.MAX_VERSUCHE,
         jetzt - mitschrift_einordnung.NEUVERSUCH_NACH))
    if not kandidaten or _termin_steht_an(jetzt) or not _ollama_da():
        return 0
    uid = kandidaten[0]["uid"]
    return int(_je_akte("Einordnung", uid, lambda: mitschrift_einordnung.einordnen(uid)))


def _ablage_bericht(jetzt: datetime) -> int:
    """Hoechstens ein Bericht je Runde: noch keiner, Stand (Auswertung oder
    Bildbestand) geaendert oder Datei liegt nicht im Ordner der Rubrik."""
    for uid, wann in list(_bericht_pause.items()):
        if not timedelta(0) <= jetzt - wann < NEUVERSUCH_NACH:
            del _bericht_pause[uid]
    kandidaten = server._q(
        "select m.uid, m.rubrik from termin_mitschriften m "
        "where m.rubrik is not null and m.auswertung_status = 'fertig' "
        "and not (m.uid = any(%s::text[])) "
        "and (m.bericht_pfad is null "
        f"or m.bericht_stand is distinct from ({mitschrift_bericht.STAND_SQL}) "
        "or split_part(m.bericht_pfad, '/', 1) <> m.rubrik) "
        "order by m.geholt_am, m.id limit 1", (list(_bericht_pause),))
    if not kandidaten:
        return 0
    uid, rubrik = kandidaten[0]["uid"], kandidaten[0]["rubrik"]
    pfad: list = []
    ok = _je_akte("Bericht", uid, lambda: pfad.append(mitschrift_bericht.ablegen(uid)))
    if not ok or not pfad or not pfad[0] or pfad[0].split("/", 1)[0] != rubrik:
        _bericht_pause[uid] = jetzt
        return 0
    return 1


def _ablage_abgleich(jetzt: datetime) -> int:
    global _LETZTER_ABGLEICH
    if (_LETZTER_ABGLEICH is not None
            and timedelta(0) <= jetzt - _LETZTER_ABGLEICH < ABGLEICH_ALLE):
        return 0
    _LETZTER_ABGLEICH = jetzt
    try:
        r = mitschrift_bericht.abgleichen()
    except Exception as e:  # noqa: BLE001 - nur der Typname ins Log (Pfade!)
        LOG.warning("Abgleich der Mitschriften-Ablage fehlgeschlagen (%s)", type(e).__name__)
        return 0
    return int(r.get("geloescht", 0)) + int(r.get("zurueckgesetzt", 0))


def _ablage(jetzt: datetime) -> int:
    ok = mitschrift_bericht._beschreibbar(mitschrift_bericht.ordner())
    _wechsel("mitschriften", ok, "Mitschriften-Ablage bereit",
             "Mitschriften-Ablage fehlt oder ist nicht beschreibbar - Berichte warten")
    if not ok:
        return 0
    return (_ablage_veraltet(jetzt) + _ablage_einordnen(jetzt) + _ablage_bericht(jetzt)
            + _ablage_abgleich(jetzt))


# ---------- 8. Kursmitschrift und Kurs-Handbuch ----------

# (lead_id, uid) | ("ablage", uid) | ("ausgabe", lead_id) -> Zeit des letzten gescheiterten
# Versuchs (In-Memory, wie _bericht_pause): ein kaputter Auftrag haelt die anderen nicht auf.
_kurs_pause: dict[tuple[str, str], datetime] = {}

_KURS_RUBRIK_SQL = "lower(coalesce(m.rubrik, '')) = lower(%s)"
_KURS_DATEN_SQL = ("(m.kurs_json is not null or m.kurs_pfad is not null "
                   "or m.kurs_pfad_lernend is not null or m.kurs_pdf is not null)")


def _kurs_pause_pruefen(jetzt: datetime) -> None:
    for schluessel, wann in list(_kurs_pause.items()):
        if not timedelta(0) <= jetzt - wann < kurs_mitschrift.NEUVERSUCH_NACH:
            del _kurs_pause[schluessel]


def _kurs_veraltet() -> int:
    """Ohne KI: Kursdaten, deren Stand nicht mehr passt oder deren Rubrik nicht mehr "Kurse"
    ist, entfernen (die Sitzung laeuft dann wie neu, mit frischen Versuchen). Unberuehrt
    bleibt, was nie verarbeitet wurde."""
    kandidaten = server._q(
        f"select m.uid from termin_mitschriften m where ({_KURS_DATEN_SQL} "
        f"or (m.kurs_status = 'fehler' and m.kurs_stand is not null)) "
        f"and (not ({_KURS_RUBRIK_SQL}) or m.kurs_stand is distinct from "
        f"({kurs_mitschrift.KURS_STAND_SQL})) order by m.geholt_am, m.id",
        (kurs_mitschrift.RUBRIK_KURSE,))
    getan = 0
    for z in kandidaten:
        uid = z["uid"]

        def entfernen(uid=uid):
            kurs_mitschrift.entfernen(uid)
            server._q("update termin_mitschriften set kurs_versuche = 0, kurs_am = null "
                      "where uid = %s returning id", (uid,))

        getan += int(_je_akte("Kurs veraltet", uid, entfernen))
    return getan


def _kurs_fehlversuch(lead_id: str, uid: str, jetzt: datetime, was: str, err: Exception) -> None:
    """Zuordnung/Fortschreiben gescheitert: Pause fuer (lead, uid), Versuch zaehlen, nach
    MAX_VERSUCHE gilt die Sitzung als 'fehler' und wird uebersprungen."""
    _kurs_pause[(lead_id, uid)] = jetzt
    z = server._q(
        "update termin_mitschriften set kurs_versuche = kurs_versuche + 1, kurs_am = %s, "
        "kurs_status = case when kurs_versuche + 1 >= %s then 'fehler' else kurs_status end "
        "where uid = %s returning kurs_status", (jetzt, kurs_mitschrift.MAX_VERSUCHE, uid))
    fehler = bool(z) and z[0]["kurs_status"] == "fehler"
    LOG.warning("Kurs-Handbuch %s uid=%s lead=%s fehlgeschlagen (%s)%s", was, _h(uid),
                kurs_handbuch._lead8(lead_id), type(err).__name__,
                " - Sitzung auf fehler" if fehler else "")
    if fehler:
        # Teilinhalt zurueckrollen: das Handbuch geht ohne diese Sitzung weiter
        try:
            kurs_handbuch.quelle_entfernen(lead_id, uid)
        except kurs_handbuch.Veraltet:
            pass
        except Exception as e2:  # noqa: BLE001 - nur der Typname ins Log
            LOG.warning("Kurs-Handbuch Rueckbau uid=%s lead=%s fehlgeschlagen (%s)", _h(uid),
                        kurs_handbuch._lead8(lead_id), type(e2).__name__)


def _kurs_erfolg(uid: str) -> None:
    """Ein Handbuch-Auftrag gelang: die naechsten bekommen wieder volle Versuche."""
    server._q("update termin_mitschriften set kurs_versuche = 0, kurs_am = null "
              "where uid = %s returning id", (uid,))


def _kurs_wartet(lead_id: str, uid: str, jetzt: datetime) -> bool:
    """Pause im Speicher oder (nach Neustart) gespeicherter Fehlversuch noch nicht lange her."""
    if (lead_id, uid) in _kurs_pause:
        return True
    return bool(server._q(
        "select 1 from termin_mitschriften where uid = %s and kurs_versuche > 0 "
        "and kurs_am > %s", (uid, jetzt - kurs_mitschrift.NEUVERSUCH_NACH)))


def _gesperrt_pruefer():
    """Fuer einen Schritt `kurs`: hat der Lernende einen Loeschantrag oder eine Sperre
    (`kurs_mitschrift.lernender_gesperrt`)? Dann weder zuordnen noch fortschreiben noch
    ausgeben (Final-Fix I3, Verteidigung in der Tiefe: die Wahl selbst lehnt die Oberflaeche
    schon ab). Ergebnis je Lernendem gemerkt; scheitert die Pruefung, gilt er als gesperrt
    (lieber warten als einen Kontakt weiterverarbeiten, der um Loeschung bat)."""
    gemerkt: dict[str, bool] = {}

    def gesperrt(lead_id: str) -> bool:
        if lead_id not in gemerkt:
            try:
                gemerkt[lead_id] = kurs_mitschrift.lernender_gesperrt(lead_id)
            except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
                LOG.warning("Kurs-Handbuch Sperrpruefung lead=%s fehlgeschlagen (%s)",
                            kurs_handbuch._lead8(lead_id), type(e).__name__)
                gemerkt[lead_id] = True
            if gemerkt[lead_id] and lead_id not in _kurs_gesperrt_gemeldet:
                _kurs_gesperrt_gemeldet.add(lead_id)
                LOG.info("Kurs-Handbuch lead=%s ruht (Loeschantrag oder Sperre)",
                         kurs_handbuch._lead8(lead_id))
        return gemerkt[lead_id]

    return gesperrt


# Lernende, deren Ruhen (Loeschantrag/Sperre) schon geloggt wurde: einmal je Prozess.
_kurs_gesperrt_gemeldet: set[str] = set()


def _kurs_ablegen(uid: str, jetzt: datetime) -> bool:
    ok = _je_akte("Kursmitschrift ablegen", uid, lambda: kurs_mitschrift.ablegen(uid))
    if not ok:
        _kurs_pause[("ablage", uid)] = jetzt
    return ok


def _kurs_mitschrift(jetzt: datetime, ki_frei) -> tuple[int, bool]:
    """(Anzahl, KI benutzt). Erst ein Ablegen ohne KI (kurs_json da, noch nicht abgelegt),
    dann - mit KI-Budget - die aelteste faellige Kursmitschrift. Ablegen druckt ein PDF in
    sales-auge (Chromium im Prozess, der live den Bildschirm aufnimmt): nicht, wenn ein
    Termin mit Bot ansteht oder laeuft (frische Uhrzeit, Final-Fix Minor 8); es bleibt
    faellig."""
    getan = 0
    gesperrt = [u for (a, u) in _kurs_pause if a == "ablage"]
    rest = server._q(
        f"select m.uid from termin_mitschriften m where {_KURS_RUBRIK_SQL} "
        "and m.auswertung_status = 'fertig' and m.bericht_pfad is not null "
        "and m.kurs_json is not null and m.kurs_status is null "
        "and not (m.uid = any(%s::text[])) order by m.geholt_am, m.id limit 1",
        (kurs_mitschrift.RUBRIK_KURSE, gesperrt))
    if rest and not _termin_naht(jetzt):
        getan += int(_kurs_ablegen(rest[0]["uid"], jetzt))
    faellig = server._q(
        f"select m.uid from termin_mitschriften m where {_KURS_RUBRIK_SQL} "
        "and m.auswertung_status = 'fertig' and m.bericht_pfad is not null "
        "and m.kurs_json is null and coalesce(m.kurs_status, '') <> 'fehler' "
        "and (m.kurs_am is null or m.kurs_am <= %s) "
        "order by m.geholt_am, m.id limit 1",
        (kurs_mitschrift.RUBRIK_KURSE, jetzt - kurs_mitschrift.NEUVERSUCH_NACH))
    if not faellig or not ki_frei():
        return getan, False
    uid = faellig[0]["uid"]
    if not _je_akte("Kursmitschrift", uid, lambda: kurs_mitschrift.erzeugen(uid, jetzt)):
        return getan, True               # erzeugen zaehlt den Versuch selbst
    getan += 1
    if not _termin_naht(jetzt):              # der KI-Auftrag kann Minuten gedauert haben
        _kurs_ablegen(uid, jetzt)
    return getan, True


def _kurs_zuordnen(jetzt: datetime, ki_frei, gesperrt=None) -> int:
    """Hoechstens eine Zuordnung: aelteste Sitzung (nach Termin-Beginn) mit Lernendem und
    ohne Quelle im Handbuch. Veraltet = Stand hat sich geaendert: liegen lassen.

    Final-Fix I1: Hat der Lernende noch eine zugeordnete, nicht eingearbeitete Quelle, wartet
    seine naechste Zuordnung, bis `_kurs_fortschreiben` sie eingearbeitet hat (das laeuft in
    jeder Runde ohne Zuordnung). Sonst saehe die KI die Kapitel der vorigen Sitzung noch nicht
    (nur "neu:<n>"-Eintraege) und legte bei gleichem Thema parallele Kapitel an. Andere
    Lernende werden weiter zugeordnet. Quellen von Sitzungen auf 'fehler' halten nicht auf."""
    gesperrt = gesperrt or _gesperrt_pruefer()
    kandidaten = server._q(
        f"select m.uid, m.kurs_lead_id, a.beginn from termin_mitschriften m "
        "join termin_akten a on a.uid = m.uid "
        f"where {_KURS_RUBRIK_SQL} and m.kurs_status = 'fertig' and m.kurs_lead_id is not null "
        "and not exists (select 1 from kurs_handbuch_quelle q where q.lead_id = m.kurs_lead_id "
        "and q.uid = m.uid) order by a.beginn, m.id", (kurs_mitschrift.RUBRIK_KURSE,))
    if not kandidaten:
        return 0
    # Lernende mit wartender aelterer Sitzung oder offener Quelle
    wartend: set[str] = {str(z["lead_id"]) for z in server._q(
        "select distinct q.lead_id from kurs_handbuch_quelle q "
        "join termin_mitschriften m on m.uid = q.uid "
        "where q.eingearbeitet_am is null and coalesce(m.kurs_status, '') <> 'fehler'")}
    for z in kandidaten:
        uid, lead_id = z["uid"], str(z["kurs_lead_id"])
        if lead_id in wartend:
            continue
        if gesperrt(lead_id):
            wartend.add(lead_id)
            continue
        if _kurs_wartet(lead_id, uid, jetzt):
            wartend.add(lead_id)            # keine juengere vorziehen (Rueckrollen)
            continue
        if not ki_frei():
            return 0
        try:
            kurs_handbuch.einfuegen_vorbereiten(lead_id, uid, z["beginn"])
            kurs_handbuch.zuordnen(lead_id, uid)
            _kurs_erfolg(uid)
        except kurs_handbuch.Veraltet:
            LOG.info("Kurs-Handbuch Zuordnung uid=%s lead=%s uebersprungen (Stand geaendert)",
                     _h(uid), kurs_handbuch._lead8(lead_id))
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            _kurs_fehlversuch(lead_id, uid, jetzt, "Zuordnung", e)
        return 1
    return 0


def _kurs_fortschreiben(jetzt: datetime, ki_frei, gesperrt=None) -> int:
    """Hoechstens ein Fortschreiben: je Lernendem der aelteste offene Auftrag, der aelteste
    Quelle zuerst ueber alle Lernenden. Nicht fuer Lernende mit Loeschantrag/Sperre."""
    gesperrt = gesperrt or _gesperrt_pruefer()
    quellen = server._q(
        "select q.lead_id, q.uid from kurs_handbuch_quelle q "
        "where q.eingearbeitet_am is null order by q.beginn, q.uid")
    gesehen: set[str] = set()
    for q in quellen:
        lead_id = str(q["lead_id"])
        if lead_id in gesehen:
            continue
        gesehen.add(lead_id)
        if gesperrt(lead_id):
            continue
        try:
            auftraege = kurs_handbuch.offene_auftraege(lead_id)
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            LOG.warning("Kurs-Handbuch Auftraege lead=%s fehlgeschlagen (%s)",
                        kurs_handbuch._lead8(lead_id), type(e).__name__)
            continue
        for uid, ziel in auftraege:
            if _kurs_wartet(lead_id, uid, jetzt):
                break                       # Reihenfolge der Sitzungen wahren
            if server._q("select 1 from termin_mitschriften where uid = %s "
                         "and kurs_status = 'fehler'", (uid,)):
                continue
            if not ki_frei():
                return 0
            try:
                kurs_handbuch.fortschreiben(lead_id, uid, ziel)
                _kurs_erfolg(uid)
            except kurs_handbuch.Veraltet:
                LOG.info("Kurs-Handbuch Fortschreiben uid=%s lead=%s uebersprungen "
                         "(Stand geaendert)", _h(uid), kurs_handbuch._lead8(lead_id))
            except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
                _kurs_fehlversuch(lead_id, uid, jetzt, "Fortschreiben", e)
            return 1
    return 0


def _kurs_ausgabe(jetzt: datetime, gesperrt=None) -> int:
    """Ohne KI: hoechstens eine Ausgabe je Runde (HTML und PDF des Handbuchs). Nicht fuer
    Lernende mit Loeschantrag/Sperre; nicht, wenn ein Termin mit Bot ansteht oder laeuft
    (PDF in sales-auge, frische Uhrzeit) - die Ausgabe bleibt dann faellig."""
    gesperrt = gesperrt or _gesperrt_pruefer()
    lernende = server._q(
        "select lead_id from kurs_handbuch union select lead_id from kurs_handbuch_kapitel "
        "union select lead_id from kurs_handbuch_quelle order by lead_id")
    for z in lernende:
        lead_id = str(z["lead_id"])
        if ("ausgabe", lead_id) in _kurs_pause or gesperrt(lead_id):
            continue
        try:
            if not kurs_handbuch.ausgabe_faellig(lead_id):
                continue
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            _kurs_pause[("ausgabe", lead_id)] = jetzt
            LOG.warning("Kurs-Handbuch Ausgabe lead=%s fehlgeschlagen (%s)",
                        kurs_handbuch._lead8(lead_id), type(e).__name__)
            continue
        if _termin_naht(jetzt):
            return 0
        try:
            kurs_handbuch.ausgeben(lead_id)
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            _kurs_pause[("ausgabe", lead_id)] = jetzt
            LOG.warning("Kurs-Handbuch Ausgabe lead=%s fehlgeschlagen (%s)",
                        kurs_handbuch._lead8(lead_id), type(e).__name__)
            continue
        return 1
    return 0


def _kurs(jetzt: datetime) -> int:
    ok = mitschrift_bericht._beschreibbar(mitschrift_bericht.ordner())
    _wechsel("kurs_ablage", ok, "Kurs-Ablage bereit",
             "Mitschriften-Ablage fehlt oder ist nicht beschreibbar - Kurse warten")
    if not ok:
        return 0
    _kurs_pause_pruefen(jetzt)
    getan = _kurs_veraltet()
    erlaubt: list[bool] = []
    gesperrt = _gesperrt_pruefer()

    def ki_frei() -> bool:                  # erst gefragt, wenn es einen Auftrag gibt
        # Final-Fix I2: nicht, wenn ein frueherer Schritt dieser Runde die KI schon benutzt
        # hat, und die Termin-Sperre mit frischer Uhrzeit (die Runde kann Minuten alt sein)
        if not erlaubt:
            erlaubt.append(not _ki_in_runde_benutzt() and not _termin_naht(jetzt)
                           and _ollama_da())
        return erlaubt[0]

    n, ki_benutzt = _kurs_mitschrift(jetzt, ki_frei)
    getan += n
    if not ki_benutzt:                      # hoechstens ein KI-Auftrag je Runde
        getan += (_kurs_zuordnen(jetzt, ki_frei, gesperrt)
                  or _kurs_fortschreiben(jetzt, ki_frei, gesperrt))
    return getan + _kurs_ausgabe(jetzt, gesperrt)


# ---------- Runde und Schleife ----------

SCHRITTE = (("abgleich", _abgleichen), ("briefing", _briefing), ("bot", _bot),
            ("verfolgen", _verfolgen), ("nachloeschen", _nachloeschen),
            ("auswerten", _auswerten), ("ablage", _ablage), ("kurs", _kurs))


# Stand von `ollama.auftraege()` zu Beginn der laufenden Runde (None ausserhalb einer Runde):
# der Schritt `kurs` startet keinen eigenen KI-Auftrag, wenn ein frueherer Schritt die KI in
# dieser Runde schon benutzt hat (Final-Fix I2).
_KI_ZU_RUNDENBEGINN: int | None = None


def _ki_in_runde_benutzt() -> bool:
    return _KI_ZU_RUNDENBEGINN is not None and ollama.auftraege() != _KI_ZU_RUNDENBEGINN


def runde(jetzt: datetime) -> dict:
    global _KI_ZU_RUNDENBEGINN
    ergebnis: dict = {}
    _KI_ZU_RUNDENBEGINN = ollama.auftraege()
    try:
        for name, schritt in SCHRITTE:
            try:
                ergebnis[name] = schritt(jetzt)
            except Exception as e:  # noqa: BLE001 - Rest der Runde laeuft weiter
                LOG.warning("Schritt %s fehlgeschlagen (%s)", name, type(e).__name__)
                ergebnis[name] = "fehler"
    finally:
        _KI_ZU_RUNDENBEGINN = None
    zaehler = {k: v for k, v in ergebnis.items()
               if k != "abgleich" and isinstance(v, int) and v}
    if zaehler:
        LOG.info("Runde: %s", " ".join(f"{k}={v}" for k, v in zaehler.items()))
    return ergebnis


def _takt() -> float:
    try:
        wert = float(os.environ.get("TERMIN_TAKT_S", "") or TAKT_STANDARD_S)
    except ValueError:
        return TAKT_STANDARD_S
    return wert if 0 < wert < math.inf else TAKT_STANDARD_S


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen - Ende nach der laufenden Runde.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout: `import server` zieht ueber das mcp-Paket eine
    Root-Konfiguration hoch, `basicConfig()` waere danach ein stiller No-op."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main() -> int:
    _logging_einrichten()
    einmal = os.environ.get("TERMIN_EINMAL", "").strip() == "1"
    try:
        signal.signal(signal.SIGTERM, _stoppen)
    except ValueError:      # nicht im Hauptthread
        pass
    LOG.info("sales-termine startet (Takt %.0f s%s)", _takt(), ", einmalig" if einmal else "")
    if not einmal:
        # Meeting-Steuerseite: Pause/Weiter/Notbremse binnen 2 s und das
        # Live-Transkript und Betreiber-Hinweise laufen in eigenen Threads neben
        # dem 30-s-Takt (termin_pause.starten).
        termin_pause.starten(_STOPP)
    while not _STOPP.is_set():
        try:
            runde(datetime.now(timezone.utc))
        except Exception as e:  # noqa: BLE001 - die Schleife darf nie sterben
            LOG.warning("Runde fehlgeschlagen (%s)", type(e).__name__)
        if einmal:
            break
        _STOPP.wait(_takt())
    return 0


if __name__ == "__main__":
    sys.exit(main())
