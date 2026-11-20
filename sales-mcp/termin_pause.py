"""Schneller Pausenweg und Live-Transkript in sales-termine (Meeting-Steuerseite).

Die Steuerseite schreibt nur einen WUNSCH (`termin_akte.aufnahme_wuenschen`):
`aufnahme_wunsch` an/pause/notbremse plus die Pausenzeilen in `termin_pausen`.
Dieser Weg laeuft in sales-termine (nur dieser Prozess hat VEXA_API_KEY) in drei
eigenen, nie sterbenden Threads (`starten`) und fuehrt den Wunsch gegen Vexa aus:

  * Wach-Thread, `wache_runde` jede Sekunde: Pause/Weiter senden, die Bot-
    Bestaetigung aus `GET /meetings/{id}` (`data.aufnahme_pause`) in die Akte
    tragen, nach 10 s ohne Bestaetigung `aufnahme_pause_fehler =
    'nicht_bestaetigt'` (Pause) bzw. `'weiter_nicht_bestaetigt'` (Weiter, R14)
    plus EIN Betreiber-Hinweis je Klick (nur eingereiht); Notbremse stoppt den
    Bot sofort. Hier laeuft nur, was das kurze Pausen-Zeitlimit hat.
  * Live-Thread, `live_runde` alle 5 s: Segmente laufender Akten in
    `termin_live_segmente` spiegeln - nie ein Segment, das ein Pausenfenster
    beruehrt.
  * Hinweis-Thread, `hinweise_senden`: Telegram an den Betreiber.

LESEFEHLER != NICHT PAUSIERT: scheitert das Lesen des Zustands, bleibt ein
bestaetigter Zustand stehen (kein Leeren, kein Fehler, kein Hinweis). Meldet Vexa
dagegen gelesen das Gegenteil, wird sofort erneut gesendet (gleiche Klickzeit)
und die 10-s-Frist beginnt ab diesem Moment neu.

PAUSENBEGINN (R10): `ab`/`at_ms` ist `von` der OFFENEN Pausenzeile (erster
Klick), nicht `aufnahme_wunsch_am` (ein Doppelklick setzt das neu). Die 10-s-Frist
zaehlt ab `von`. Nach "Weiter" ist die Zeile geschlossen; eine neue Pause ist eine
neue Zeile mit neuem `von` - so geht nach einem resume nie eine pause mit aelterem
at_ms an Vexa (Bindung aus Task 2). Alle Acts sendet NUR dieser eine Thread,
nacheinander: eine pause aus Runde n kommt immer vor dem resume aus Runde n+1.

BERUEHREN (R4/R11): ein Segment beruehrt ein Fenster [von, bis), wenn sein Beginn
darin liegt oder es vor `von` beginnt und nach `von` endet. Ohne einordenbaren
Beginn gilt es bei vorhandenen Pausen als beruehrend ("im Zweifel weg"), ohne
Ende, sobald irgendeine Pause nach seinem Beginn anfaengt (R16).

LOGS: nur uid-Hash, Zaehler und Typnamen - nie Text, Namen, Raum-Ids, Schluessel.
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import betreiber_hinweis
import server
import termin_akte
import vexa

LOG = logging.getLogger("sales-termine.pause")

BOT_STATUS = ("wartet_auf_einlass", "laeuft")
FRIST = timedelta(seconds=10)            # Bestaetigung spaetestens 10 s nach `von`
NEU_SENDEN_NACH = timedelta(seconds=3)   # unbestaetigte Acts hoechstens alle 3 s erneut
HINWEIS_NEU_NACH = timedelta(seconds=60)  # gescheiterter Betreiber-Hinweis: Neuversuch
# Drei Threads (Review Important 1): nur der Wach-Thread steht im 2-s-Weg; das
# Live-Transkript (Vexa-Abruf bis 20 s) und Telegram (bis 10 s) laufen getrennt.
WACHE_TAKT_S = 1.0
LIVE_TAKT_S = 5.0
HINWEIS_TAKT_S = 1.0
# R15: eine Bestaetigung gehoert zu DIESER Pause nur mit von - 1 s <= seit_ms <=
# von + 2 s (Uhren von sales-termine und Bot; der Bot klemmt eine Klickzeit in der
# Zukunft auf seine Uhr). Aelter = eine fruehere Pause, ohne seit_ms = unklar:
# beides zaehlt nicht, es wird weiter gesendet.
SEIT_VOR = timedelta(seconds=1)
SEIT_NACH = timedelta(seconds=2)
FEHLER = {"pause": "nicht_bestaetigt", "weiter": "weiter_nicht_bestaetigt"}

# Speicher dieses Prozesses (nach einem Neustart leer - siehe die Funktionen).
_gesendet: dict[tuple[str, str], datetime] = {}   # (uid, "pause:<ms>"|"resume") -> letzter Versuch
_letzter_act: dict[str, str] = {}                  # uid -> "pause" | "resume"
_nachschuss: set[tuple[str, int]] = set()          # (uid, von_ms): R11c-Aufruf steht aus
# (uid, "pause"|"weiter", Klick-ms): Betreiber-Hinweis eingereiht (einmal je Klick)
_gemeldet: set[tuple[str, str, int]] = set()
# (uid, "pause"|"weiter", Klick-ms) -> Beginn der laufenden 10-s-Frist, wenn sie
# NICHT beim Klick beginnt: eine schon bestaetigte Pause bzw. ein bestaetigtes
# Weiter, das Vexa danach verliert, bekommt ab dem Verlust frische 10 s.
_frist_ab: dict[tuple[str, str, int], datetime] = {}
_gestoppt: set[str] = set()                        # Notbremse: Bot gestoppt
# Betreiber-Hinweise: der Wach-Thread reiht ein, der Hinweis-Thread sendet.
_hinweis_schlange: queue.Queue[str] = queue.Queue()
_hinweis_ausstehend: list[list] = []               # [letzter Fehlversuch | None, Text]
_UNBEKANNT = object()                              # Vexa-Zustand nicht lesbar


def _zuruecksetzen() -> None:
    """Speicher leeren (Tests, "Neustart")."""
    for ablage in (_gesendet, _letzter_act, _nachschuss, _gemeldet, _frist_ab,
                   _gestoppt, _hinweis_ausstehend):
        ablage.clear()
    while True:
        try:
            _hinweis_schlange.get_nowait()
        except queue.Empty:
            break


def _h(uid) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def _ms(t: datetime) -> int:
    return int((t - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1))


def _aus_ms(wert: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(wert))


def zeitpunkt(text) -> datetime | None:
    """Vexa-Zeit (ISO-8601, `absolute_start_time`/`absolute_end_time`, mit Z oder
    Offset; ohne Zone = UTC) -> aware datetime, sonst None."""
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def beruehrt_pause(beginn: datetime | None, ende: datetime | None,
                   pausen: list[dict]) -> bool:
    """R4/R11a: Beginn in einem Fenster (termin_akte.in_pause: von inklusive, bis
    exklusiv, offen = unendlich) ODER Beginn vor `von` und Ende nach `von`.
    Fail closed (R16): ohne Beginn immer beruehrend; ohne (lesbares) Ende
    beruehrend, sobald IRGENDEINE Pause nach dem Beginn anfaengt - es bleibt nur,
    wenn es nach allen Pausenanfaengen beginnt und in keiner Pause liegt.
    Nur aware datetimes hineingeben."""
    if not pausen:
        return False
    if beginn is None:
        return True
    if ende is None:
        return (termin_akte.in_pause(beginn, pausen)
                or any(p["von"] > beginn for p in pausen))
    unten, oben = (beginn, ende) if ende >= beginn else (ende, beginn)
    if termin_akte.in_pause(unten, pausen):
        return True
    return any(unten < p["von"] < oben for p in pausen)


def pausen_filtern(segmente: list[dict], pausen: list[dict]) -> list[dict]:
    """Segmente fuer die gespeicherte Mitschrift: alles, was ein Pausenfenster
    beruehrt, faellt weg; `ende`/`segment_id` (nur fuer den Filter) fallen ab.
    Ohne Pausen bleibt jedes Segment (auch ohne Zeitstempel)."""
    aus = []
    for seg in segmente:
        if pausen and beruehrt_pause(zeitpunkt(seg.get("beginn") or ""),
                                     zeitpunkt(seg.get("ende") or ""), pausen):
            continue
        aus.append({k: v for k, v in seg.items() if k not in ("ende", "segment_id")})
    return aus


# ---------- Wache: Wunsch -> Vexa -> Bestaetigung ----------

def _faellig(schluessel: tuple[str, str], jetzt: datetime) -> bool:
    letzter = _gesendet.get(schluessel)
    return letzter is None or not timedelta(0) <= jetzt - letzter < NEU_SENDEN_NACH


def _senden(z: dict, ab: datetime | None, jetzt: datetime) -> bool:
    """Ein Act an Vexa. Der Versuch zaehlt fuer die Drossel auch, wenn er
    scheitert (ein totes Vexa wird nicht jede Sekunde angefragt)."""
    uid = z["uid"]
    art = "resume" if ab is None else f"pause:{_ms(ab)}"
    erstmals = (uid, art) not in _gesendet
    _gesendet[(uid, art)] = jetzt
    try:
        vexa.pause_setzen(z["vexa_plattform"], z["vexa_native_id"], ab)
    except vexa.VexaFehler as e:
        LOG.warning("%s an Vexa gescheitert uid=%s (%s)",
                    "Weiter" if ab is None else "Pause", _h(uid), type(e).__name__)
        return False
    _letzter_act[uid] = "resume" if ab is None else "pause"
    (LOG.info if erstmals else LOG.debug)(
        "%s an Vexa gesendet uid=%s", "Weiter" if ab is None else "Pause", _h(uid))
    return True


def _zustand(z: dict):
    """Vom Bot bestaetigter Zustand (dict) oder None, wenn Vexa KEINE gueltige
    Bestaetigung meldet - oder `_UNBEKANNT`, wenn das Lesen scheiterte (Zeitlimit,
    Netz, 5xx). Das ist NICHT dasselbe (Review Important 2): ein Lesefehler aendert
    an einem bestaetigten Zustand nichts."""
    try:
        return vexa.pause_zustand(int(z["vexa_meeting_id"]))
    except vexa.VexaFehler:
        return _UNBEKANNT


def _hinweis_text(z: dict, art: str, klick: datetime) -> str:
    try:
        zone = ZoneInfo(z.get("zeitzone") or "Europe/Berlin")
    except Exception:  # noqa: BLE001 - unbekannte Zone: Vorgabe
        zone = ZoneInfo("Europe/Berlin")
    uhr = f"{klick.astimezone(zone):%H:%M:%S}"
    if art == "weiter":
        zeilen = [f"⚠️ Weiter (Aufnahme fortsetzen) nicht bestätigt (Klick {uhr}).",
                  "Die Aufnahme ist womöglich noch angehalten – bitte die Steuerseite prüfen."]
    else:
        zeilen = [f"⚠️ Aufnahme-Pause nicht bestätigt (Klick {uhr}).",
                  "Die Aufnahme läuft womöglich weiter – bitte die Steuerseite prüfen."]
    ui = os.environ.get("UI_BASIS_URL", "").strip().rstrip("/")
    if ui:
        zeilen.append(f"Steuerung: {ui}/termine/{quote(z['uid'], safe='')}/live")
    return "\n".join(zeilen)


def _nicht_bestaetigt(z: dict, art: str, klick: datetime) -> None:
    """Fehler setzen (nur beim Wechsel) und EIN Betreiber-Hinweis je Ereignis
    (`art` 'pause' je Pausenklick, 'weiter' je Weiter-Klick). Der Hinweis wird nur
    EINGEREIHT - senden tut der Hinweis-Thread (Telegram darf den 2-s-Weg nicht
    aufhalten). Nach einem Neustart steht der Fehler schon - dann kein zweiter
    Hinweis. Ein Fehler der anderen Art wird ueberschrieben: es zaehlt, was gerade
    gewuenscht ist."""
    uid, schluessel = z["uid"], (z["uid"], art, _ms(klick))
    bedingung = ("aufnahme_wunsch = 'pause' and aufnahme_pausiert_seit is null"
                 if art == "pause" else "aufnahme_wunsch = 'an'")
    gesetzt = server._q(
        "update termin_akten set aufnahme_pause_fehler = %s "
        f"where uid = %s and {bedingung} "
        "and aufnahme_pause_fehler is distinct from %s returning uid",
        (FEHLER[art], uid, FEHLER[art]))
    if gesetzt:
        LOG.warning("%s nicht bestaetigt uid=%s (Frist %d s)",
                    "Pause" if art == "pause" else "Weiter", _h(uid),
                    int(FRIST.total_seconds()))
        if schluessel not in _gemeldet:
            _gemeldet.add(schluessel)
            _hinweis_schlange.put(_hinweis_text(z, art, klick))


def _live_im_fenster_loeschen(uid: str, von: datetime) -> int:
    """R11b/R13: schon geholte Live-Segmente, die die offene Pause beruehren -
    reine DB-Abfrage: Beginn ab `von`, oder Beginn davor und Ende nach `von`,
    oder Ende unbekannt (R16, fail closed)."""
    weg = server._q(
        "delete from termin_live_segmente where uid = %s "
        "and (beginn >= %s or ende is null or greatest(beginn, ende) > %s) "
        "returning segment_id", (uid, von, von))
    return len(weg)


def _pause(z: dict, jetzt: datetime) -> int:
    uid, von = z["uid"], z["von"]
    von_ms = _ms(von)
    frist_schluessel = (uid, "pause", von_ms)
    acts = 0
    erstmals = (uid, f"pause:{von_ms}") not in _gesendet
    if erstmals:                         # erster Act ohne vorheriges Lesen: jede ms zaehlt
        acts += _senden(z, von, jetzt)
    zustand = _zustand(z)
    if zustand is _UNBEKANNT:
        if z["aufnahme_pausiert_seit"] is not None:
            # Bestaetigt und nur gerade nicht lesbar: nichts aendern - kein Leeren,
            # kein Fehler, kein Hinweis. Ein ausstehender Nachschuss (R11c) darf raus.
            if (uid, von_ms) in _nachschuss and _senden(z, von, jetzt):
                _nachschuss.discard((uid, von_ms))
                acts += 1
            return acts
        zustand = None                   # nie bestaetigt: bleibt unbestaetigt
    seit_ms = zustand.get("seit_ms") if zustand else None
    seit = _aus_ms(seit_ms) if seit_ms is not None else None
    if (zustand and zustand["pausiert"] is True and seit is not None
            and von - SEIT_VOR <= seit <= von + SEIT_NACH):     # R15
        erste = server._q(
            "update termin_pausen set bestaetigt_am = %s where id = %s "
            "and bestaetigt_am is null returning id", (jetzt, z["pause_id"]))
        server._q(
            "update termin_akten set aufnahme_pausiert_seit = %s, aufnahme_pause_fehler = null "
            "where uid = %s and (aufnahme_pausiert_seit is distinct from %s "
            "or aufnahme_pause_fehler is not null) returning uid", (seit, uid, seit))
        if erste:
            geloescht = _live_im_fenster_loeschen(uid, von)
            LOG.info("Pause bestaetigt uid=%s live_geloescht=%d", _h(uid), geloescht)
            # R11c: genau EIN zweiter Aufruf mit derselben Klickzeit - Vexas
            # Sicherheitsloeschung erfasst dann auch, was beim ersten unterwegs war.
            _nachschuss.add((uid, von_ms))
        if (uid, von_ms) in _nachschuss and _senden(z, von, jetzt):
            _nachschuss.discard((uid, von_ms))
            acts += 1
        _frist_ab.pop(frist_schluessel, None)
        return acts
    # Vexa meldet die Pause (gelesen!) nicht: Lobby-Rennen, Bot-Neustart, Act verloren.
    verloren = z["aufnahme_pausiert_seit"] is not None
    if verloren:
        server._q("update termin_akten set aufnahme_pausiert_seit = null "
                  "where uid = %s returning uid", (uid,))
        LOG.warning("Pause bei Vexa nicht mehr bestaetigt uid=%s - sende erneut", _h(uid))
        _frist_ab[frist_schluessel] = jetzt          # frische 10 s ab dem Verlust
    if not erstmals and (verloren or _faellig((uid, f"pause:{von_ms}"), jetzt)):
        acts += _senden(z, von, jetzt)
    if z["bestaetigt_am"] is not None:
        # war schon bestaetigt: Frist ab dem Verlust (nach einem Neustart dieses
        # Prozesses ab dem ersten Blick), nie ab `von`
        beginn = _frist_ab.setdefault(frist_schluessel, jetzt)
    else:
        beginn = _frist_ab.get(frist_schluessel, von)
    if jetzt - beginn > FRIST:
        _nicht_bestaetigt(z, "pause", von)
    return acts


def _weiter(z: dict, jetzt: datetime) -> int:
    uid = z["uid"]
    # Ein noch ausstehender Nachschuss gehoert zu einer geschlossenen Pause: nie
    # mehr senden (sonst kaeme eine alte pause nach dem resume).
    for schluessel in [k for k in _nachschuss if k[0] == uid]:
        _nachschuss.discard(schluessel)
    zustand = _zustand(z)
    if zustand is _UNBEKANNT:
        zustand = None       # Lesefehler: nur die gespeicherten Spalten entscheiden
    elif zustand and zustand["pausiert"] is False:
        server._q("update termin_akten set aufnahme_pausiert_seit = null, "
                  "aufnahme_pause_fehler = null where uid = %s and "
                  "(aufnahme_pausiert_seit is not null or aufnahme_pause_fehler is not null) "
                  "returning uid", (uid,))
        if _letzter_act.pop(uid, None) == "resume":
            LOG.info("Weiter bestaetigt uid=%s", _h(uid))
        for k in [k for k in _frist_ab if k[0] == uid and k[1] == "weiter"]:
            del _frist_ab[k]
        return 0
    vexa_pausiert = zustand is not None and zustand["pausiert"] is True
    vielleicht_pausiert = (
        vexa_pausiert
        or z["aufnahme_pausiert_seit"] is not None
        or z["aufnahme_pause_fehler"] is not None
        or _letzter_act.get(uid) == "pause")
    if not vielleicht_pausiert:
        return 0
    # R14: Klickzeit des Weiter = `bis` der zuletzt geschlossenen Pausenzeile (der
    # ERSTE Weiter-Klick; aufnahme_wunsch_am setzt ein Doppelklick neu). Ohne
    # geschlossene Zeile: aufnahme_wunsch_am.
    klick = z["weiter_am"] or z["aufnahme_wunsch_am"]
    frist_schluessel = (uid, "weiter", _ms(klick)) if klick is not None else None
    neu_verloren = (vexa_pausiert and z["aufnahme_pausiert_seit"] is None
                    and z["aufnahme_pause_fehler"] is None
                    and frist_schluessel is not None and frist_schluessel not in _frist_ab)
    if neu_verloren:
        # Weiter war bestaetigt (Spalten leer), Vexa meldet wieder pausiert (Bot-
        # Neustart, spaete alte Bestaetigung R8): sofort resume, frische 10 s.
        _frist_ab[frist_schluessel] = jetzt
        LOG.warning("Weiter bei Vexa nicht mehr bestaetigt uid=%s - sende erneut", _h(uid))
    acts = 0
    if neu_verloren or _faellig((uid, "resume"), jetzt):
        acts = int(_senden(z, None, jetzt))
    if klick is not None:
        beginn = _frist_ab.get(frist_schluessel, klick)
        if jetzt - beginn > FRIST:
            _nicht_bestaetigt(z, "weiter", klick)
    return acts


def _notbremse(z: dict) -> int:
    """R2: Bot sofort stoppen (einmal; scheitert es, die naechste Sekunde). Keine
    Pause-Acts mehr; offene Pause bleibt offen, Mitschrift und Live-Ablage
    bleiben - das Meeting-Ende schliesst ab."""
    uid = z["uid"]
    if uid in _gestoppt:
        return 0
    try:
        vexa.bot_stoppen(z["vexa_plattform"], z["vexa_native_id"])
    except vexa.VexaFehler as e:
        LOG.warning("Notbremse: Bot stoppen gescheitert uid=%s (%s)", _h(uid), type(e).__name__)
        return 0
    _gestoppt.add(uid)
    LOG.info("Notbremse: Bot gestoppt uid=%s", _h(uid))
    return 1


def _wache_eine(z: dict, jetzt: datetime) -> int:
    wunsch = z["aufnahme_wunsch"]
    if wunsch == "notbremse":
        return _notbremse(z)
    if wunsch == "pause":
        # Ohne offene Zeile gibt es kein `von` (nach Task 4 nicht moeglich): nichts raten.
        return _pause(z, jetzt) if z["von"] is not None else 0
    # 'an': nur Akten, die je eine Pause hatten (sonst kein Vexa-Aufruf je Sekunde)
    if not (z["hatte_pause"] or z["aufnahme_pausiert_seit"] is not None
            or z["aufnahme_pause_fehler"] is not None or z["uid"] in _letzter_act):
        return 0
    return _weiter(z, jetzt)


def _vergessen(aktiv: set[str]) -> None:
    """Speicher fuer Akten, die nicht mehr laufen, freigeben."""
    for k in [k for k in _gesendet if k[0] not in aktiv]:
        del _gesendet[k]
    for k in [k for k in _frist_ab if k[0] not in aktiv]:
        del _frist_ab[k]
    for ablage in (_nachschuss, _gemeldet):
        for k in [k for k in ablage if k[0] not in aktiv]:
            ablage.discard(k)
    for uid in [u for u in _letzter_act if u not in aktiv]:
        del _letzter_act[uid]
    _gestoppt.intersection_update(aktiv)


def wache_runde(jetzt: datetime) -> int:
    """Akten mit Vexa-Ids in wartet_auf_einlass/laeuft: Wunsch gegen den vom Bot
    bestaetigten Zustand abgleichen. -> Anzahl erfolgreich gesendeter Acts
    (pause, resume, Bot-Stopp). Ohne Vexa-Ids (Lobby vor dem Bot) passiert nichts."""
    if jetzt.tzinfo is None:
        jetzt = jetzt.replace(tzinfo=timezone.utc)
    if not vexa.konfiguriert():
        return 0
    zeilen = server._q(
        "select a.uid, a.zeitzone, a.vexa_meeting_id, a.vexa_plattform, a.vexa_native_id, "
        "a.aufnahme_wunsch, a.aufnahme_wunsch_am, a.aufnahme_pausiert_seit, "
        "a.aufnahme_pause_fehler, p.id as pause_id, p.von, p.bestaetigt_am, "
        "exists (select 1 from termin_pausen q where q.uid = a.uid) as hatte_pause, "
        "(select max(q.bis) from termin_pausen q where q.uid = a.uid) as weiter_am "
        "from termin_akten a "
        "left join termin_pausen p on p.uid = a.uid and p.bis is null "
        "where a.status = any(%s) and a.vexa_meeting_id is not null "
        "and coalesce(a.vexa_plattform, '') <> '' and coalesce(a.vexa_native_id, '') <> '' "
        "order by a.beginn, a.uid", (list(BOT_STATUS),))
    acts = 0
    for z in zeilen:
        try:
            acts += _wache_eine(z, jetzt)
        except Exception as e:  # noqa: BLE001 - eine Akte stoppt die naechste nicht
            LOG.warning("Pausen-Wache uid=%s fehlgeschlagen (%s)", _h(z["uid"]),
                        type(e).__name__)
    _vergessen({z["uid"] for z in zeilen})
    return acts


# ---------- Live-Transkript ----------

def _segment_id(seg: dict, beginn: datetime) -> str:
    sid = str(seg.get("segment_id") or "")
    if sid:
        return sid
    # Vexa liefert die Id sonst immer; ohne sie: stabil aus Beginn und Sprecher
    # (ein nachgeschaerfter Text bleibt dieselbe Zeile).
    roh = f"{beginn.isoformat()}|{seg.get('sprecher') or ''}"
    return "t-" + hashlib.sha256(roh.encode()).hexdigest()[:16]


def _live_eine(uid: str, mid: int) -> int:
    roh = vexa.segmente_holen(int(mid))
    kandidaten = []
    for seg in roh:
        beginn = zeitpunkt(seg.get("beginn") or "")
        if beginn is None:
            continue                      # nicht einzuordnen: nie live zeigen
        ende = zeitpunkt(seg.get("ende") or "")
        kandidaten.append((_segment_id(seg, beginn), beginn, ende, seg))
    with server.pool.connection() as conn:
        with conn.transaction():
            # Sperre gegen einen gleichzeitigen Klick: was vor uns committet ist,
            # filtern wir hier mit; ein spaeterer Klick liegt zeitlich nach jedem
            # schon geholten Segment-Beginn (Ueberlappungen raeumt R11b ab). Ist die
            # Akte inzwischen fertig (Mitschrift abgelegt, Live-Ablage geleert),
            # wird nichts mehr eingetragen.
            akte = conn.execute("select status from termin_akten where uid = %s for share",
                                (uid,)).fetchone()
            if not akte or akte["status"] != "laeuft":
                return 0
            pausen = conn.execute("select von, bis from termin_pausen where uid = %s "
                                  "order by von", (uid,)).fetchall()
            behalten = [(sid, beginn, ende, seg) for sid, beginn, ende, seg in kandidaten
                        if not beruehrt_pause(beginn, ende, pausen)]
            # Spiegel: was Vexa zurueckzog oder was ein Fenster beruehrt, geht.
            conn.execute("delete from termin_live_segmente where uid = %s "
                         "and not (segment_id = any(%s::text[]))",
                         (uid, [b[0] for b in behalten]))
            for sid, beginn, ende, seg in behalten:
                conn.execute(
                    "insert into termin_live_segmente "
                    "(uid, segment_id, beginn, ende, sprecher, text) "
                    "values (%s, %s, %s, %s, %s, %s) on conflict (uid, segment_id) do update set "
                    "beginn = excluded.beginn, ende = excluded.ende, "
                    "sprecher = excluded.sprecher, text = excluded.text "
                    "where (termin_live_segmente.beginn, termin_live_segmente.ende, "
                    "termin_live_segmente.sprecher, termin_live_segmente.text) "
                    "is distinct from "
                    "(excluded.beginn, excluded.ende, excluded.sprecher, excluded.text)",
                    (uid, sid, beginn, ende, seg.get("sprecher") or None,
                     seg.get("text") or ""))
    return len(behalten)


def _aufraeumen(jetzt: datetime) -> None:
    """Akten ausserhalb von wartet_auf_einlass/laeuft (Ende jeder Art): offene
    Pause schliessen mit bis = Zeitpunkt, an dem das Ende hier erkannt wird
    (R12: das TATSAECHLICHE Ende, nicht das geplante; nie vor `von`), Live-Ablage
    leeren. Den Normalfall (fertig) erledigt termin_takt._mitschrift_ablegen in
    seiner Transaktion; dies faengt fehlgeschlagen, ohne_aufnahme usw."""
    server._q(
        "update termin_pausen p set bis = greatest(%s::timestamptz, p.von) "
        "from termin_akten a where a.uid = p.uid and p.bis is null "
        "and not (a.status = any(%s)) returning p.id", (jetzt, list(BOT_STATUS)))
    server._q(
        "delete from termin_live_segmente l using termin_akten a "
        "where a.uid = l.uid and not (a.status = any(%s)) returning l.uid",
        (list(BOT_STATUS),))


def live_runde(jetzt: datetime) -> int:
    """Laufende Akten: Segmente holen und in termin_live_segmente spiegeln, nie
    ein Segment, das eine Pause beruehrt. -> Anzahl gespeicherter Segmente."""
    if jetzt.tzinfo is None:
        jetzt = jetzt.replace(tzinfo=timezone.utc)
    _aufraeumen(jetzt)
    if not vexa.konfiguriert():
        return 0
    zeilen = server._q(
        "select uid, vexa_meeting_id from termin_akten where status = 'laeuft' "
        "and vexa_meeting_id is not null order by beginn, uid")
    n = 0
    for z in zeilen:
        try:
            n += _live_eine(z["uid"], z["vexa_meeting_id"])
        except vexa.VexaNichtErreichbar:
            pass                          # vexa meldet den Ausfall selbst, einmal (I9)
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            LOG.warning("Live-Transkript uid=%s fehlgeschlagen (%s)", _h(z["uid"]),
                        type(e).__name__)
    return n


# ---------- Betreiber-Hinweise ----------

def hinweise_senden(jetzt: datetime) -> int:
    """Eingereihte Hinweise senden (Hinweis-Thread). Ein gescheiterter Hinweis
    bleibt stehen und wird fruehestens nach `HINWEIS_NEU_NACH` erneut versucht.
    -> Anzahl gesendeter Hinweise."""
    while True:
        try:
            _hinweis_ausstehend.append([None, _hinweis_schlange.get_nowait()])
        except queue.Empty:
            break
    gesendet = 0
    for eintrag in list(_hinweis_ausstehend):
        zuletzt, text = eintrag
        if zuletzt is not None and timedelta(0) <= jetzt - zuletzt < HINWEIS_NEU_NACH:
            continue
        if betreiber_hinweis.senden(text) is True:
            _hinweis_ausstehend.remove(eintrag)
            gesendet += 1
        else:
            eintrag[0] = jetzt
    return gesendet


# ---------- Threads ----------

def _takt(stopp: threading.Event, name: str, runde, takt_name: str) -> None:
    """Gemeinsame Schleife: `runde(jetzt)` je Takt. Fehler stehen mit Typname im
    Log; der Thread stirbt nie, er endet nur mit `stopp`. Den Takt liest jede
    Runde neu aus dem Modul (Tests verkuerzen ihn)."""
    while not stopp.is_set():
        try:
            try:
                runde(datetime.now(timezone.utc))
            except Exception as e:  # noqa: BLE001
                LOG.warning("%s fehlgeschlagen (%s)", name, type(e).__name__)
        except Exception:  # noqa: BLE001 - auch ein Log-Fehler beendet den Thread nicht
            pass
        stopp.wait(globals()[takt_name])


def schleife(stopp: threading.Event) -> None:
    """Wach-Thread (2-s-Weg): jede Sekunde nur `wache_runde` - Acts, Bot-Stopp und
    Zustand lesen, alles mit dem kurzen Pausen-Zeitlimit von vexa."""
    _takt(stopp, "Pausen-Wache", lambda j: wache_runde(j), "WACHE_TAKT_S")


def live_schleife(stopp: threading.Event) -> None:
    """Live-Thread: alle 5 s `live_runde` (Vexa-Abruf darf hier haengen)."""
    _takt(stopp, "Live-Transkript", lambda j: live_runde(j), "LIVE_TAKT_S")


def hinweis_schleife(stopp: threading.Event) -> None:
    """Hinweis-Thread: Telegram (bis 10 s) haelt nie einen Act auf."""
    _takt(stopp, "Betreiber-Hinweis", lambda j: hinweise_senden(j), "HINWEIS_TAKT_S")


def starten(stopp: threading.Event) -> list[threading.Thread]:
    """Die drei Daemon-Threads starten; sie enden mit `stopp`."""
    LOG.info("Schneller Pausenweg startet (Wache %.0f s, Live %.0f s, Hinweise getrennt)",
             WACHE_TAKT_S, LIVE_TAKT_S)
    threads = [
        threading.Thread(target=schleife, args=(stopp,), name="pausen-wache", daemon=True),
        threading.Thread(target=live_schleife, args=(stopp,), name="live-transkript",
                         daemon=True),
        threading.Thread(target=hinweis_schleife, args=(stopp,), name="betreiber-hinweise",
                         daemon=True),
    ]
    for th in threads:
        th.start()
    return threads
