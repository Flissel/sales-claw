"""Schneller Pausenweg und Live-Transkript in sales-termine (Meeting-Steuerseite).

Die Steuerseite schreibt nur einen WUNSCH (`termin_akte.aufnahme_wuenschen`):
`aufnahme_wunsch` an/pause/notbremse plus die Pausenzeilen in `termin_pausen`.
Dieser Weg laeuft als eigener Thread in sales-termine (nur dieser Prozess hat
VEXA_API_KEY) und fuehrt den Wunsch gegen Vexa aus:

  * `wache_runde` jede Sekunde: Pause/Weiter senden, die Bot-Bestaetigung aus
    `GET /meetings/{id}` (`data.aufnahme_pause`) in die Akte tragen, nach 10 s
    ohne Bestaetigung `aufnahme_pause_fehler = 'nicht_bestaetigt'` plus EIN
    Betreiber-Hinweis je Pause; Notbremse stoppt den Bot sofort.
  * `live_runde` alle 5 s: Segmente laufender Akten in `termin_live_segmente`
    spiegeln - nie ein Segment, das ein Pausenfenster beruehrt.

PAUSENBEGINN (R10): `ab`/`at_ms` ist `von` der OFFENEN Pausenzeile (erster
Klick), nicht `aufnahme_wunsch_am` (ein Doppelklick setzt das neu). Die 10-s-Frist
zaehlt ab `von`. Nach "Weiter" ist die Zeile geschlossen; eine neue Pause ist eine
neue Zeile mit neuem `von` - so geht nach einem resume nie eine pause mit aelterem
at_ms an Vexa (Bindung aus Task 2). Alle Acts sendet NUR dieser eine Thread,
nacheinander: eine pause aus Runde n kommt immer vor dem resume aus Runde n+1.

BERUEHREN (R4/R11): ein Segment beruehrt ein Fenster [von, bis), wenn sein Beginn
darin liegt oder es vor `von` beginnt und nach `von` endet. Ohne einordenbaren
Beginn gilt es bei vorhandenen Pausen als beruehrend ("im Zweifel weg").

LOGS: nur uid-Hash, Zaehler und Typnamen - nie Text, Namen, Raum-Ids, Schluessel.
"""
from __future__ import annotations

import hashlib
import logging
import os
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
LIVE_ALLE = timedelta(seconds=5)
WACHE_TAKT_S = 1.0
# seit_ms des Bots darf so weit NACH `von` liegen und gilt noch als diese Pause
# (Uhren von sales-termine und Bot). Der Bot klemmt eine Klickzeit in der Zukunft
# auf seine Uhr - seit_ms liegt dann VOR `von` und die Pause deckt den Klick ab.
TOLERANZ = timedelta(seconds=2)

# Speicher dieses Prozesses (nach einem Neustart leer - siehe die Funktionen).
_gesendet: dict[tuple[str, str], datetime] = {}   # (uid, "pause:<ms>"|"resume") -> letzter Versuch
_letzter_act: dict[str, str] = {}                  # uid -> "pause" | "resume"
_nachschuss: set[tuple[str, int]] = set()          # (uid, von_ms): R11c-Aufruf steht aus
_gemeldet: set[tuple[str, int]] = set()            # (uid, von_ms): Betreiber-Hinweis raus
_hinweis_offen: dict[tuple[str, int], datetime | None] = {}
_gestoppt: set[str] = set()                        # Notbremse: Bot gestoppt
_enden: dict[str, dict[str, datetime]] = {}        # uid -> segment_id -> Ende (letzte live_runde)


def _zuruecksetzen() -> None:
    """Speicher leeren (Tests)."""
    for ablage in (_gesendet, _letzter_act, _nachschuss, _gemeldet, _hinweis_offen,
                   _gestoppt, _enden):
        ablage.clear()


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
    Nur aware datetimes hineingeben."""
    if not pausen:
        return False
    if beginn is None:
        return True
    unten, oben = (beginn, ende) if ende is None or ende >= beginn else (ende, beginn)
    oben = oben or unten
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


def _zustand(z: dict) -> dict | None:
    try:
        return vexa.pause_zustand(int(z["vexa_meeting_id"]))
    except vexa.VexaFehler:
        return None            # unbekannt: wie "keine Bestaetigung"


def _hinweis_text(z: dict, von: datetime) -> str:
    try:
        zone = ZoneInfo(z.get("zeitzone") or "Europe/Berlin")
    except Exception:  # noqa: BLE001 - unbekannte Zone: Vorgabe
        zone = ZoneInfo("Europe/Berlin")
    zeilen = [f"⚠️ Aufnahme-Pause nicht bestätigt (Klick {von.astimezone(zone):%H:%M:%S}).",
              "Die Aufnahme läuft womöglich weiter – bitte die Steuerseite prüfen."]
    ui = os.environ.get("UI_BASIS_URL", "").strip().rstrip("/")
    if ui:
        zeilen.append(f"Steuerung: {ui}/termine/{quote(z['uid'], safe='')}/live")
    return "\n".join(zeilen)


def _nicht_bestaetigt(z: dict, von: datetime, jetzt: datetime) -> None:
    """Fehler setzen (nur beim Wechsel) und EIN Betreiber-Hinweis je Pause.
    Nach einem Neustart steht der Fehler schon - dann kein zweiter Hinweis."""
    uid, schluessel = z["uid"], (z["uid"], _ms(von))
    gesetzt = server._q(
        "update termin_akten set aufnahme_pause_fehler = 'nicht_bestaetigt' "
        "where uid = %s and aufnahme_wunsch = 'pause' and aufnahme_pausiert_seit is null "
        "and aufnahme_pause_fehler is null returning uid", (uid,))
    if gesetzt:
        LOG.warning("Pause nicht bestaetigt uid=%s (Frist %d s)", _h(uid),
                    int(FRIST.total_seconds()))
        if schluessel not in _gemeldet:
            _hinweis_offen.setdefault(schluessel, None)
    if schluessel in _hinweis_offen:
        letzter = _hinweis_offen[schluessel]
        if letzter is not None and timedelta(0) <= jetzt - letzter < HINWEIS_NEU_NACH:
            return
        if betreiber_hinweis.senden(_hinweis_text(z, von)) is True:
            _gemeldet.add(schluessel)
            del _hinweis_offen[schluessel]
        else:
            _hinweis_offen[schluessel] = jetzt


def _live_im_fenster_loeschen(uid: str, von: datetime) -> int:
    """R11b: schon geholte Live-Segmente, die die (offene) Pause beruehren:
    Beginn ab `von` oder - laut letzter live_runde - Ende nach `von`."""
    ueber = [sid for sid, ende in _enden.get(uid, {}).items() if ende > von]
    weg = server._q(
        "delete from termin_live_segmente where uid = %s "
        "and (beginn >= %s or segment_id = any(%s::text[])) returning segment_id",
        (uid, von, ueber))
    return len(weg)


def _pause(z: dict, jetzt: datetime) -> int:
    uid, von = z["uid"], z["von"]
    von_ms = _ms(von)
    acts = 0
    erstmals = (uid, f"pause:{von_ms}") not in _gesendet
    if erstmals:                         # erster Act ohne vorheriges Lesen: jede ms zaehlt
        acts += _senden(z, von, jetzt)
    zustand = _zustand(z)
    seit_ms = zustand.get("seit_ms") if zustand else None
    if (zustand and zustand["pausiert"] is True
            and (seit_ms is None or _aus_ms(seit_ms) <= von + TOLERANZ)):
        seit = _aus_ms(seit_ms) if seit_ms is not None else von
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
        _hinweis_offen.pop((uid, von_ms), None)
        return acts
    # Nicht (mehr) bestaetigt: Lobby-Rennen, Vexa-Neustart, Act verloren.
    if z["aufnahme_pausiert_seit"] is not None:
        server._q("update termin_akten set aufnahme_pausiert_seit = null "
                  "where uid = %s returning uid", (uid,))
        LOG.warning("Pause bei Vexa nicht mehr bestaetigt uid=%s - sende erneut", _h(uid))
    if not erstmals and _faellig((uid, f"pause:{von_ms}"), jetzt):
        acts += _senden(z, von, jetzt)
    if jetzt - von > FRIST:
        _nicht_bestaetigt(z, von, jetzt)
    return acts


def _weiter(z: dict, jetzt: datetime) -> int:
    uid = z["uid"]
    # Ein noch ausstehender Nachschuss gehoert zu einer geschlossenen Pause: nie
    # mehr senden (sonst kaeme eine alte pause nach dem resume).
    for schluessel in [k for k in _nachschuss if k[0] == uid]:
        _nachschuss.discard(schluessel)
    zustand = _zustand(z)
    if zustand and zustand["pausiert"] is False:
        server._q("update termin_akten set aufnahme_pausiert_seit = null, "
                  "aufnahme_pause_fehler = null where uid = %s and "
                  "(aufnahme_pausiert_seit is not null or aufnahme_pause_fehler is not null) "
                  "returning uid", (uid,))
        if _letzter_act.pop(uid, None) == "resume":
            LOG.info("Weiter bestaetigt uid=%s", _h(uid))
        return 0
    vielleicht_pausiert = (
        (zustand is not None and zustand["pausiert"] is True)
        or z["aufnahme_pausiert_seit"] is not None
        or z["aufnahme_pause_fehler"] is not None
        or _letzter_act.get(uid) == "pause")
    if vielleicht_pausiert and _faellig((uid, "resume"), jetzt):
        return int(_senden(z, None, jetzt))
    return 0


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
    for k in [k for k in _hinweis_offen if k[0] not in aktiv]:
        del _hinweis_offen[k]
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
        "a.aufnahme_wunsch, a.aufnahme_pausiert_seit, a.aufnahme_pause_fehler, "
        "p.id as pause_id, p.von, "
        "exists (select 1 from termin_pausen q where q.uid = a.uid) as hatte_pause "
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
    kandidaten, enden = [], {}
    for seg in roh:
        beginn = zeitpunkt(seg.get("beginn") or "")
        if beginn is None:
            continue                      # nicht einzuordnen: nie live zeigen
        ende = zeitpunkt(seg.get("ende") or "")
        sid = _segment_id(seg, beginn)
        enden[sid] = max(beginn, ende) if ende else beginn
        kandidaten.append((sid, beginn, ende, seg))
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
            behalten = [(sid, beginn, seg) for sid, beginn, ende, seg in kandidaten
                        if not beruehrt_pause(beginn, ende, pausen)]
            # Spiegel: was Vexa zurueckzog oder was ein Fenster beruehrt, geht.
            conn.execute("delete from termin_live_segmente where uid = %s "
                         "and not (segment_id = any(%s::text[]))",
                         (uid, [sid for sid, _, _ in behalten]))
            for sid, beginn, seg in behalten:
                conn.execute(
                    "insert into termin_live_segmente (uid, segment_id, beginn, sprecher, text) "
                    "values (%s, %s, %s, %s, %s) on conflict (uid, segment_id) do update set "
                    "beginn = excluded.beginn, sprecher = excluded.sprecher, text = excluded.text "
                    "where (termin_live_segmente.beginn, termin_live_segmente.sprecher, "
                    "termin_live_segmente.text) is distinct from "
                    "(excluded.beginn, excluded.sprecher, excluded.text)",
                    (uid, sid, beginn, seg.get("sprecher") or None, seg.get("text") or ""))
    _enden[uid] = enden
    return len(behalten)


def _aufraeumen() -> None:
    """Akten ausserhalb von wartet_auf_einlass/laeuft (Ende jeder Art): offene
    Pause mit bis = Terminende schliessen (R2; nie vor `von`), Live-Ablage leeren.
    Den Normalfall (fertig) erledigt termin_takt._mitschrift_ablegen in seiner
    Transaktion; dies faengt fehlgeschlagen, ohne_aufnahme usw."""
    server._q(
        "update termin_pausen p set bis = greatest(a.ende, p.von) from termin_akten a "
        "where a.uid = p.uid and p.bis is null and not (a.status = any(%s)) returning p.id",
        (list(BOT_STATUS),))
    weg = server._q(
        "delete from termin_live_segmente l using termin_akten a "
        "where a.uid = l.uid and not (a.status = any(%s)) returning l.uid",
        (list(BOT_STATUS),))
    for uid in {z["uid"] for z in weg}:
        _enden.pop(uid, None)


def live_runde(jetzt: datetime) -> int:
    """Laufende Akten: Segmente holen und in termin_live_segmente spiegeln, nie
    ein Segment, das eine Pause beruehrt. -> Anzahl gespeicherter Segmente."""
    _aufraeumen()
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
    for uid in [u for u in _enden if u not in {z["uid"] for z in zeilen}]:
        del _enden[uid]
    return n


# ---------- Thread ----------

def schleife(stopp: threading.Event) -> None:
    """Schneller Weg: jede Sekunde `wache_runde`, alle 5 s `live_runde`. Fehler
    einer Runde stehen mit Typname im Log; der Thread stirbt nie, er endet nur
    mit `stopp`."""
    letzte_live: datetime | None = None
    LOG.info("Schneller Pausenweg startet (Wache %.0f s, Live %d s)",
             WACHE_TAKT_S, int(LIVE_ALLE.total_seconds()))
    while not stopp.is_set():
        try:
            jetzt = datetime.now(timezone.utc)
            try:
                wache_runde(jetzt)
            except Exception as e:  # noqa: BLE001
                LOG.warning("Pausen-Wache fehlgeschlagen (%s)", type(e).__name__)
            if letzte_live is None or not timedelta(0) <= jetzt - letzte_live < LIVE_ALLE:
                letzte_live = jetzt
                try:
                    live_runde(jetzt)
                except Exception as e:  # noqa: BLE001
                    LOG.warning("Live-Transkript fehlgeschlagen (%s)", type(e).__name__)
        except Exception:  # noqa: BLE001 - auch ein Log-Fehler beendet den Thread nicht
            pass
        stopp.wait(WACHE_TAKT_S)
