"""Beobachter sales-auge: "Laura (Bildschirm)" (Bildauswertung live, Task 6).

Ein headless Chromium tritt internen Jitsi-Terminen als sichtbarer Teilnehmer
"Laura (Bildschirm)" bei, holt Standbilder NUR des geteilten Bildschirms (das
Seiten-Skript `auge_jitsi.js` liest ausschliesslich entfernte Tracks mit
videoType 'desktop', nie Kameras) und legt sie bei spuerbarer Aenderung in
`termin_bilder` ab. Ein eigener Thread beschreibt und bettet die Bilder ein,
eines nach dem anderen, und loescht ungepruefte nach 24 h (R11). Ein kleiner HTTP-Dienst (nur im Compose-Netz) bietet
`GET /gesund` und `POST /suche`.

Jede Runde (`AUGE_RUNDE_S`, Vorgabe 2 s):
  1. Soll-Abgleich aus der DB (`bildschirm.beobachtung_soll`): neue Termine
     betreten (eine Seite je Termin), nicht mehr gewollte sofort verlassen
     (Seite schliessen, offenes Bild bekommt `bis`).
  2. Je Sitzung `window.__lauraBild()`; je gleichzeitiger Freigabe (Quelle,
     hoechstens MAX_QUELLEN) bei spuerbarer Aenderung (dHash des ROHEN Frames
     gegen den rohen Hash des letzten abgelegten Frames DIESER Quelle, Ruling R4)
     ablegen; Drossel je Quelle, Obergrenze je Akte. Endet eine Quelle, waehrend
     andere teilen -> `quelle_ende` (R9b); teilt keine Quelle mehr -> `freigabe_ende`.

Ein Browser-Prozess, eine Seite (in eigenem Kontext) je Termin. Playwright und
fastembed werden erst in `main()` importiert, damit Tests ohne sie laufen.
Playwright (sync) wird nur aus dem Hauptthread benutzt.

LOGS: nur gekuerzte uid (sha256, 8 Zeichen), Zaehler, Fehlerart. Nie Links,
Raum- oder Anzeigenamen, Beschreibungen oder Bilddaten. Bei Ausnahmen steht nur
der Typname im Log.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import math
import os
import signal
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import bild_arbeit
import bildschirm
import server
import termin_link

LOG = logging.getLogger("sales-auge")

ANZEIGENAME = "Laura (Bildschirm)"
# startSilent: Laura empfaengt keinen Ton (Spec: nur der Bildschirm-Track).
FRAGMENT = ("config.startWithAudioMuted=true&config.startWithVideoMuted=true"
            "&config.prejoinConfig.enabled=false&config.startSilent=true"
            "&userInfo.displayName=%22Laura%20(Bildschirm)%22")
SKRIPT_PFAD = Path(__file__).resolve().parent / "auge_jitsi.js"
AUFRUF = "() => window.__lauraBild ? window.__lauraBild() : null"

PORT_STANDARD = 8790
RUNDE_STANDARD_S = 2.0
KI_BILD_TIMEOUT_STANDARD_S = 60.0
KI_PUFFER_S = 15.0           # Client wartet etwas laenger als die Bild-Spur des KI-Tors
FEHLER_PAUSE_S = 30          # nach einem Fehlversuch der Beschreibung (Ruling R6)
LEER_PAUSE_S = 3             # nichts offen
AUFRAEUMEN_ABSTAND_S = 600   # ungepruefte Bilder nach 24 h loeschen, hoechstens je 10 min (R11)
NEUSTART_PAUSE = timedelta(seconds=30)   # nach gescheitertem Beitritt
MAX_SEITENFEHLER = 5         # so viele Fehler am Stueck -> Seite schliessen, neu betreten
MAX_QUELLEN = 3              # gleichzeitige Freigaben je Termin (wie MAX_QUELLEN in auge_jitsi.js)
SUCHE_MAX_TEXT = 1000
SUCHE_MAX_LIMIT = 50
SUCHE_MAX_BYTES = 16 * 1024
# Beitritt (goto) blockiert die Runde aller Termine: kurz halten (T6a).
BEITRITT_TIMEOUT_MS = 15_000
# Lese-Timeout je HTTP-Verbindung: ein langsamer Client haelt keinen Thread (T6b).
HTTP_LESE_TIMEOUT_S = 10

CHROMIUM_ARGS = (
    "--mute-audio",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-dev-shm-usage",
)

_STOPP = threading.Event()


def _h(uid: str) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def _typ(e: BaseException) -> str:
    return type(e).__name__


# ---------- Soll-Abgleich ----------

@dataclass
class Quelle:
    """Eine laufende Bildschirmfreigabe (ein Desktop-Track) in einer Sitzung:
    Drossel und Aenderungserkennung (R4) gelten je Quelle."""
    von: str | None
    letzter_hash: int | None             # dHash des letzten abgelegten (oder heiklen) rohen Frames
    letzte_zeit: datetime | None


@dataclass
class Sitzung:
    """Eine Seite in einem Termin. `letzter_hash`/`letzte_zeit`/`anzahl` gelten fuer die
    ganze Akte (letztes abgelegtes Bild, Start aus der DB); je Freigabe eine `Quelle`."""
    uid: str
    seite: Any
    letzter_hash: int | None = None      # dHash des letzten ABGELEGTEN rohen Frames (Akte)
    letzte_zeit: datetime | None = None
    anzahl: int = 0                      # Bilder dieser Akte (Start aus der DB)
    teilt: bool = False
    quellen: dict[str, Quelle] = field(default_factory=dict)
    fehler: int = 0
    gestartet: datetime | None = field(default=None)
    uebersprungen: int = 0               # heikle, nicht gespeicherte Bilder dieser Sitzung


_gesperrt_bis: dict[str, datetime] = {}

# Heikel-Pruefer (Schicht A), von main() gesetzt; auf None wird nicht geprueft
# (nur Tests ohne Modelle).
pruefer: Any = None


def abgleich(soll: set[str], laufend: set[str]) -> tuple[set[str], set[str]]:
    """(zu starten, zu beenden)."""
    return set(soll) - set(laufend), set(laufend) - set(soll)


def beitritts_url(link: str) -> str:
    """Jitsi-Link mit eigenem Fragment: stumm, ohne Vorschaltseite, Anzeigename.
    Ein vorhandenes Fragment wird ersetzt, die Query bleibt."""
    return link.split("#", 1)[0] + "#" + FRAGMENT


def _link_ok(link: str | None) -> bool:
    """Nur https und nur bekannte Jitsi-Hosts (keine beliebige Navigation)."""
    if not link or not isinstance(link, str):
        return False
    try:
        teile = urllib.parse.urlsplit(link.strip())
    except ValueError:
        return False
    if teile.scheme != "https" or not teile.hostname:
        return False
    host = teile.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in termin_link.jitsi_hosts())


def _bestand(uid: str) -> tuple[int, int | None, datetime | None]:
    """(Anzahl Bilder, dHash und Zeit des letzten abgelegten Bildes) aus der DB:
    Obergrenze und Drossel gelten auch ueber einen Neustart des Dienstes hinweg."""
    z = server._q(
        "select (select count(*) from termin_bilder where uid = %s) as n, l.dhash, "
        "l.aufgenommen_am from (select 1) x left join lateral (select dhash, aufgenommen_am "
        "from termin_bilder where uid = %s order by aufgenommen_am desc, erstellt_am desc "
        "limit 1) l on true", (uid, uid))
    if not z:
        return 0, None, None
    return int(z[0]["n"]), z[0]["dhash"], z[0]["aufgenommen_am"]


def _schliessen(seite: Any, uid: str) -> None:
    try:
        seite.close()
    except Exception as e:  # noqa: BLE001
        LOG.warning("Seite schliessen uid=%s fehlgeschlagen (%s)", _h(uid), _typ(e))


def _beenden(sitzungen: dict[str, Sitzung], uid: str, jetzt: datetime) -> None:
    s = sitzungen.pop(uid, None)
    if s is None:
        return
    _schliessen(s.seite, uid)
    try:
        bildschirm.freigabe_ende(uid, jetzt)
    except Exception as e:  # noqa: BLE001
        LOG.warning("Freigabe-Ende uid=%s fehlgeschlagen (%s)", _h(uid), _typ(e))
    LOG.info("Termin verlassen uid=%s (Bilder %d)", _h(uid), s.anzahl)


def abgleichen(sitzungen: dict[str, Sitzung], oeffnen: Callable[[str], Any],
               jetzt: datetime) -> None:
    """Soll aus der DB lesen; nicht mehr gewollte Termine SOFORT verlassen,
    neue betreten. `oeffnen(url)` liefert eine Seite mit evaluate/close."""
    soll = {z["uid"]: z["link"] for z in bildschirm.beobachtung_soll()}
    starten, beenden = abgleich(set(soll), set(sitzungen))
    for uid in sorted(beenden):
        _beenden(sitzungen, uid, jetzt)
    for uid in sorted(starten):
        if _gesperrt_bis.get(uid) and jetzt < _gesperrt_bis[uid]:
            continue
        link = soll[uid]
        if not _link_ok(link):
            if uid not in _gesperrt_bis:
                LOG.warning("Kein gueltiger Jitsi-Link uid=%s - kein Beitritt", _h(uid))
            _gesperrt_bis[uid] = jetzt + NEUSTART_PAUSE
            continue
        try:
            seite = oeffnen(beitritts_url(link.strip()))
        except Exception as e:  # noqa: BLE001
            _gesperrt_bis[uid] = jetzt + NEUSTART_PAUSE
            LOG.warning("Beitritt uid=%s fehlgeschlagen (%s)", _h(uid), _typ(e))
            continue
        _gesperrt_bis.pop(uid, None)
        try:
            anzahl, letzter, zeit = _bestand(uid)
        except Exception as e:  # noqa: BLE001
            LOG.warning("Bilder zaehlen uid=%s fehlgeschlagen (%s)", _h(uid), _typ(e))
            anzahl, letzter, zeit = bildschirm.OBERGRENZE, None, jetzt
        # Ab der Obergrenze den letzten Hash mitnehmen (sonst waere das erste Bild
        # nach einem Neustart "neu"); darunter beginnt die Sitzung frisch.
        sitzungen[uid] = Sitzung(uid=uid, seite=seite, anzahl=anzahl, gestartet=jetzt,
                                 letzter_hash=letzter if anzahl >= bildschirm.OBERGRENZE else None,
                                 letzte_zeit=zeit)
        LOG.info("Termin betreten uid=%s (Bilder bisher %d)", _h(uid), anzahl)
    for uid in list(_gesperrt_bis):
        if uid not in soll:
            _gesperrt_bis.pop(uid, None)


def alle_beenden(sitzungen: dict[str, Sitzung], jetzt: datetime) -> None:
    for uid in sorted(sitzungen):
        _beenden(sitzungen, uid, jetzt)


# ---------- Runde ----------

def _frame(antwort: Any) -> tuple[bool, list[tuple[str, str | None, Any]]]:
    """(teilt, [(quelle, von, jpeg-Base64 oder None)]) aus der Antwort von
    __lauraBild, sortiert nach Quelle, hoechstens MAX_QUELLEN. Nur die Form
    {teilt, quellen: [{quelle, von, jpeg}]} gilt; alles andere (auch die alte Form
    {teilt, von, jpeg}) heisst "teilt nicht". Dekodiert wird erst je Quelle."""
    if not isinstance(antwort, dict) or not antwort.get("teilt"):
        return False, []
    roh = antwort.get("quellen")
    if not isinstance(roh, list):
        return False, []
    je: dict[str, tuple[str, str | None, Any]] = {}
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            continue
        quelle = eintrag.get("quelle")
        if not isinstance(quelle, str) or not quelle or quelle in je:
            continue
        von = eintrag.get("von")
        je[quelle] = (quelle, str(von) if von is not None else None, eintrag.get("jpeg"))
    quellen = [je[q] for q in sorted(je)][:MAX_QUELLEN]
    return bool(quellen), quellen


def _jpeg(roh: Any) -> bytes | None:
    """Base64 -> Bytes; None, wenn (noch) kein Bild. Wirft bei kaputten Daten."""
    if not roh:
        return None
    if not isinstance(roh, str):
        raise TypeError("jpeg ist kein Text")
    return base64.b64decode(roh, validate=True)


def _neu_beginnen(s: Sitzung, von: str | None, alt: Quelle | None = None) -> Quelle:
    """Neue Quelle (neue Freigabe) oder neuer Teilender auf einer Quelle: unter der
    Obergrenze zaehlt das naechste Bild als neu (kein Hash). Ab der Obergrenze gilt der
    Akte-weite letzte Hash, dann darf nur eine starke Aenderung ein Bild erzeugen.
    Drossel: die Zeit der bisherigen Quelle bzw. des letzten Bildes der Akte bleibt."""
    return Quelle(von=von,
                  letzter_hash=s.letzter_hash if s.anzahl >= bildschirm.OBERGRENZE else None,
                  letzte_zeit=alt.letzte_zeit if alt is not None else s.letzte_zeit)


def _heikel_pruefen(s: Sitzung, q: Quelle, jpeg: bytes,
                    jetzt: datetime) -> tuple[bool | None, list[float] | None]:
    """Schicht A: (heikel?, Bildvektor). None als Urteil, wenn die Pruefung scheitert
    (dann wird nichts abgelegt). Ohne Pruefer: (False, None)."""
    if pruefer is None:
        return False, None
    try:
        ist, vektor = pruefer.heikel(jpeg)
    except Exception as e:  # noqa: BLE001 - Modellfehler: Bild nicht ablegen
        LOG.warning("Heikel-Pruefung uid=%s fehlgeschlagen (%s)", _h(s.uid), _typ(e))
        q.letzte_zeit = jetzt        # Drossel: kaputtes Modell nicht jede Runde neu versuchen
        return None, None
    return bool(ist), vektor


def _quelle_aufnehmen(s: Sitzung, q: Quelle, roh: Any, jetzt: datetime) -> None:
    """Ein Frame einer Quelle: Drossel und Hash je Quelle, Obergrenze je Akte."""
    try:
        jpeg = _jpeg(roh)
    except (binascii.Error, ValueError, TypeError) as e:
        LOG.warning("Standbild uid=%s unbrauchbar (%s)", _h(s.uid), _typ(e))
        return
    if jpeg is None:
        return                       # Freigabe laeuft, noch kein Bild
    # Drossel gilt immer, auch nach Ende der Freigabe oder Wechsel des Teilenden.
    if q.letzte_zeit is not None and jetzt - q.letzte_zeit < bildschirm.MIN_ABSTAND:
        return
    try:
        neu = bildschirm.dhash(jpeg)
    except Exception as e:  # noqa: BLE001 - kaputte Bytes von der Seite
        LOG.warning("Standbild uid=%s unbrauchbar (%s)", _h(s.uid), _typ(e))
        return
    if not bildschirm.soll_aufnehmen(q.letzter_hash, neu, q.letzte_zeit, jetzt, s.anzahl):
        return
    heikel, vektor = _heikel_pruefen(s, q, jpeg, jetzt)
    if heikel is None:
        return                       # Pruefung gescheitert: im Zweifel nichts ablegen
    if heikel:
        # Nie speichern; Hash und Zeit trotzdem merken (gleiches Bild nicht neu pruefen).
        q.letzter_hash, q.letzte_zeit = neu, jetzt
        s.uebersprungen += 1
        bildschirm.uebersprungen_zaehlen(s.uid)
        LOG.info("Heikles Bild verworfen uid=%s (Nr. übersprungen %d)",
                 _h(s.uid), s.uebersprungen)
        return
    bild_id = bildschirm.bild_ablegen(s.uid, jpeg, jetzt, q.von, vektor_bild=vektor)
    if bild_id is None:
        LOG.info("Ablage verweigert uid=%s (nicht mehr beobachtet)", _h(s.uid))
        return
    q.letzter_hash, q.letzte_zeit = neu, jetzt
    s.letzter_hash, s.letzte_zeit, s.anzahl = neu, jetzt, s.anzahl + 1
    LOG.info("Standbild abgelegt uid=%s (Nr. %d, Quellen %d)", _h(s.uid), s.anzahl,
             len(s.quellen))


def _eine(s: Sitzung, jetzt: datetime) -> None:
    antwort = s.seite.evaluate(AUFRUF)
    s.fehler = 0
    teilt, frames = _frame(antwort)
    if not teilt:
        if s.teilt:
            bildschirm.freigabe_ende(s.uid, jetzt)
            LOG.info("Freigabe beendet uid=%s", _h(s.uid))
        s.teilt, s.quellen = False, {}
        return
    # Verschwundene Quellen vergessen: kein Freigabe-Ende, solange eine andere teilt.
    aktuell = {quelle for quelle, _, _ in frames}
    beendet = []                      # Teilende, deren Quelle (oder Name) endet
    for quelle in [x for x in s.quellen if x not in aktuell]:
        beendet.append(s.quellen.pop(quelle).von)
    # Neue Quellen (oder neuer Teilender) VOR der Ablage anlegen: gleichzeitig neue
    # Quellen drosseln sich nicht gegenseitig.
    for quelle, von, _ in frames:
        alt = s.quellen.get(quelle)
        if alt is None or alt.von != von:
            if alt is not None:
                beendet.append(alt.von)
            s.quellen[quelle] = _neu_beginnen(s, von, alt)
    # Offenes Bild einer beendeten Quelle schliessen (R9b) - nicht, wenn eine laufende
    # Quelle denselben Namen traegt (das offene Bild koennte ihres sein).
    laufend = {bildschirm.name_norm(q.von) for q in s.quellen.values()}
    for von in dict.fromkeys(beendet):
        if bildschirm.name_norm(von) not in laufend:
            bildschirm.quelle_ende(s.uid, von, jetzt)
    s.teilt = True
    for quelle, _, roh in frames:
        _quelle_aufnehmen(s, s.quellen[quelle], roh, jetzt)


def runde(sitzungen: dict[str, Sitzung], jetzt: datetime) -> None:
    """Je Sitzung ein Standbild holen; ein Fehler stoppt die anderen nicht."""
    for uid in sorted(sitzungen):
        s = sitzungen[uid]
        try:
            _eine(s, jetzt)
        except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
            s.fehler += 1
            LOG.warning("Runde uid=%s fehlgeschlagen (%s, %d. Mal)", _h(uid), _typ(e), s.fehler)
            if s.fehler >= MAX_SEITENFEHLER:
                _beenden(sitzungen, uid, jetzt)


# ---------- Beschreib-Arbeit (eigener Thread) ----------

def beschreib_schritt(einbetter: bild_arbeit.Einbetter) -> float:
    """Ein Bild beschreiben; liefert die Pause bis zum naechsten Versuch (R6)."""
    try:
        ergebnis = bild_arbeit.naechste_beschreiben_status(einbetter)
    except Exception as e:  # noqa: BLE001
        LOG.warning("Beschreiben fehlgeschlagen (%s)", _typ(e))
        return FEHLER_PAUSE_S
    if ergebnis is None:
        return LEER_PAUSE_S
    if ergebnis == "fehler":
        return FEHLER_PAUSE_S
    return 0


def aufraeum_schritt(zuletzt: float | None, jetzt: float) -> float | None:
    """Hoechstens einmal je AUFRAEUMEN_ABSTAND_S: ungepruefte Bilder nach 24 h loeschen
    (R11). Liefert den Zeitpunkt des letzten Laufs (auch nach einem Fehler)."""
    if zuletzt is not None and jetzt - zuletzt < AUFRAEUMEN_ABSTAND_S:
        return zuletzt
    try:
        bild_arbeit.ungepruefte_loeschen()
    except Exception as e:  # noqa: BLE001 - nur der Typname ins Log
        LOG.warning("Aufraeumen ungepruefter Bilder fehlgeschlagen (%s)", _typ(e))
    return jetzt


def beschreib_schleife(einbetter: bild_arbeit.Einbetter, stopp: threading.Event) -> None:
    aufgeraeumt: float | None = None
    while not stopp.is_set():
        aufgeraeumt = aufraeum_schritt(aufgeraeumt, time.monotonic())
        pause = beschreib_schritt(einbetter)
        if pause:
            stopp.wait(pause)


class GesperrterEinbetter:
    """Ein Modellaufruf zur Zeit (Beschreib-Thread und Suche teilen die Modelle)."""

    def __init__(self, inneres: bild_arbeit.Einbetter) -> None:
        self._inneres = inneres
        self._sperre = threading.Lock()

    def bild(self, jpeg: bytes) -> list[float]:
        with self._sperre:
            return self._inneres.bild(jpeg)

    def text_clip(self, text: str) -> list[float]:
        with self._sperre:
            return self._inneres.text_clip(text)

    def text(self, text: str) -> list[float]:
        with self._sperre:
            return self._inneres.text(text)


# ---------- HTTP ----------

def _json_wert(w: Any) -> Any:
    if isinstance(w, (datetime, date)):
        return w.isoformat()
    return str(w)


class _Fehler(Exception):
    pass


def _suchanfrage(roh: bytes) -> tuple[str, str | None, int]:
    try:
        d = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise _Fehler("kein JSON") from e
    if not isinstance(d, dict):
        raise _Fehler("kein Objekt")
    text, uid, limit = d.get("text"), d.get("uid"), d.get("limit", 10)
    if not isinstance(text, str) or not text.strip() or len(text) > SUCHE_MAX_TEXT:
        raise _Fehler("text")
    if uid is not None and (not isinstance(uid, str) or not uid.strip()):
        raise _Fehler("uid")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise _Fehler("limit")
    return text.strip(), uid, max(1, min(SUCHE_MAX_LIMIT, limit))


def http_dienst(einbetter: bild_arbeit.Einbetter, host: str, port: int,
                stand: Callable[[], dict]) -> ThreadingHTTPServer:
    """HTTP nur im Compose-Netz: GET /gesund, POST /suche."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "sales-auge"
        sys_version = ""
        timeout = HTTP_LESE_TIMEOUT_S      # Socket-Timeout fuer Kopf und Rumpf

        def log_message(self, *_a) -> None:   # keine Zugriffszeilen
            return

        def _antwort(self, status: int, daten: Any) -> None:
            roh = json.dumps(daten, default=_json_wert, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/gesund":
                self._antwort(404, {"fehler": "unbekannt"})
                return
            try:
                info = dict(stand())
            except Exception:  # noqa: BLE001
                info = {"ok": False}
            ok = info.pop("ok", True) is not False
            self._antwort(200 if ok else 503, {"ok": ok, **info})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/suche":
                self._antwort(404, {"fehler": "unbekannt"})
                return
            try:
                laenge = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                laenge = -1
            if laenge <= 0 or laenge > SUCHE_MAX_BYTES:
                self._antwort(400, {"fehler": "ungueltige Anfrage"})
                return
            try:
                text, uid, limit = _suchanfrage(self.rfile.read(laenge))
            except _Fehler:
                self._antwort(400, {"fehler": "ungueltige Anfrage"})
                return
            try:
                treffer = bild_arbeit.suchen(einbetter, text, uid=uid, limit=limit)
            except Exception as e:  # noqa: BLE001
                LOG.warning("Suche fehlgeschlagen (%s)", _typ(e))
                self._antwort(500, {"fehler": "Suche fehlgeschlagen"})
                return
            self._antwort(200, treffer)

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


# ---------- Browser ----------

class _Seite:
    """Playwright-Seite in eigenem Kontext; close() schliesst beides."""

    def __init__(self, kontext: Any, seite: Any) -> None:
        self._kontext = kontext
        self._seite = seite

    def evaluate(self, skript: str) -> Any:
        return self._seite.evaluate(skript)

    def close(self) -> None:
        try:
            self._seite.close()
        finally:
            self._kontext.close()


def _oeffner(browser: Any) -> Callable[[str], _Seite]:
    skript = SKRIPT_PFAD.read_text(encoding="utf-8")

    def oeffnen(url: str) -> _Seite:
        kontext = browser.new_context(viewport={"width": 1280, "height": 720},
                                      locale="de-DE")
        try:
            kontext.add_init_script(script=skript)
            seite = kontext.new_page()
            seite.goto(url, wait_until="domcontentloaded", timeout=BEITRITT_TIMEOUT_MS)
        except Exception:
            kontext.close()
            raise
        return _Seite(kontext, seite)

    return oeffnen


# ---------- Dienst ----------

def takt_schritt(sitzungen: dict[str, Sitzung], oeffnen: Callable[[str], Any],
                 browser: Any, zustand: dict, jetzt: datetime) -> bool:
    """Eine Runde: Abgleich und Standbilder. False, wenn der Browser nicht mehr
    verbunden ist: dann scheitert jeder Beitritt fuer immer, also soll der Prozess
    enden (Exit != 0, Docker startet neu); /gesund meldet es bis dahin."""
    try:
        lebt = bool(browser.is_connected())
    except Exception:  # noqa: BLE001
        lebt = False
    zustand["browser"] = lebt
    if not lebt:
        LOG.error("Browser getrennt - Dienst endet fuer einen Neustart")
        return False
    try:
        abgleichen(sitzungen, oeffnen, jetzt)
    except Exception as e:  # noqa: BLE001 - die Schleife darf nie sterben
        LOG.warning("Abgleich fehlgeschlagen (%s)", _typ(e))
    try:
        runde(sitzungen, datetime.now(timezone.utc))
    except Exception as e:  # noqa: BLE001
        LOG.warning("Runde fehlgeschlagen (%s)", _typ(e))
    return True


def _zahl(name: str, vorgabe: float) -> float:
    try:
        wert = float(os.environ.get(name, "") or vorgabe)
    except ValueError:
        return vorgabe
    return wert if 0 < wert < math.inf else vorgabe


def _port() -> int:
    try:
        p = int(os.environ.get("AUGE_PORT", "") or PORT_STANDARD)
    except ValueError:
        return PORT_STANDARD
    return p if 0 < p < 65536 else PORT_STANDARD


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen - Ende nach der laufenden Runde.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout (Muster termin_takt): `import server` zieht ueber
    das mcp-Paket eine Root-Konfiguration hoch."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for name in ("sales-auge", "bild_arbeit"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        lg.propagate = False


def main() -> int:
    _logging_einrichten()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:      # nicht im Hauptthread
            pass
    takt = _zahl("AUGE_RUNDE_S", RUNDE_STANDARD_S)
    bild_arbeit.KI_TIMEOUT_S = _zahl("KI_BILD_TIMEOUT_S", KI_BILD_TIMEOUT_STANDARD_S) + KI_PUFFER_S
    LOG.info("sales-auge startet (Runde %.1f s, Port %d)", takt, _port())

    from einbetter_fastembed import FastEmbedEinbetter  # lazy: nur im Auge-Abbild
    einbetter = GesperrterEinbetter(FastEmbedEinbetter())
    global pruefer
    import heikel                       # Pruefer teilt die gesperrte Modellinstanz
    # Scheitert der Konstruktor, bricht main() ab: nie ohne Heikel-Pruefung (kein Fail-open).
    pruefer = heikel.Pruefer(einbetter)
    LOG.info("Modelle geladen (Heikel-Abstand %.3f)", heikel.ABSTAND)

    sitzungen: dict[str, Sitzung] = {}
    zustand = {"browser": True}
    srv = http_dienst(einbetter, "0.0.0.0", _port(),
                      lambda: {"ok": zustand["browser"], "browser": zustand["browser"],
                               "sitzungen": len(sitzungen)})
    threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
    arbeit = threading.Thread(target=beschreib_schleife, args=(einbetter, _STOPP),
                              name="beschreiben", daemon=True)
    arbeit.start()

    from playwright.sync_api import sync_playwright  # lazy: nur im Auge-Abbild
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=list(CHROMIUM_ARGS))
    oeffnen = _oeffner(browser)
    rc = 0
    try:
        while not _STOPP.is_set():
            if not takt_schritt(sitzungen, oeffnen, browser, zustand,
                                datetime.now(timezone.utc)):
                rc = 1          # Browser weg: Prozess endet, Docker startet ihn neu
                break
            _STOPP.wait(takt)
    finally:
        alle_beenden(sitzungen, datetime.now(timezone.utc))
        for schritt in (browser.close, pw.stop, srv.shutdown, srv.server_close):
            try:
                schritt()
            except Exception as e:  # noqa: BLE001
                LOG.warning("Aufraeumen fehlgeschlagen (%s)", _typ(e))
        arbeit.join(timeout=5)
        LOG.info("sales-auge beendet (rc=%d)", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
