"""sales-dispatch — die einzige Komponente des Systems, die wirklich versendet.

Sie liest ausschliesslich freigegebene WhatsApp-Entwuerfe
(`drafts.status='approved' and channel='whatsapp'`) und stellt sie ueber
OpenWA zu. Das Freigabe-Gate ist damit die Datenbank und nicht das Verhalten
eines Sprachmodells (Stufe-3-Plan, Grundsatzentscheidung 1). LinkedIn wird
NIE angefasst (Grundsatzentscheidung 3) — `channel='whatsapp'` steht in
jeder Query, auch im Claim.

Geteilt mit `server.py` (gleiches Image, gleicher Build-Kontext): der
Verbindungspool, der Query-Helfer `_q` und vor allem die Schema-Whitelist —
`import server` laesst denselben `SystemExit` fliegen, wenn jemand
`SALES_DB_SCHEMA` auf etwas anderes als `sales`/`sales_test` stellt. Der
Import baut nebenbei das MCPServer-Objekt auf; gestartet wird es nie
(`mcp.run()` steht dort unter `if __name__ == "__main__"`).

CLAIM OHNE DDL — der Kunstgriff dieses Moduls
---------------------------------------------
`drafts.status` traegt einen CHECK auf (pending|approved|rejected|sent|
failed). Ein sauberer Zwischenstatus 'sending' fehlt, und DDL ist der Rolle
`sales_app` verboten (db/provision.sql vergibt nur DML). Der Claim laeuft
deshalb ueber den erlaubten Uebergang approved -> failed mit einer Marke im
`error`-Feld:

    update drafts set status='failed', error='in Zustellung seit … (…)'
     where id=%s and status='approved' and channel='whatsapp'
     returning id, lead_id, recipient, subject, body

Zwei nebenlaeufige Dispatcher koennen denselben Entwurf nie beide gewinnen:
der zweite UPDATE blockiert auf der Zeilensperre, prueft nach dem Commit des
ersten seine WHERE-Klausel gegen die neue Zeilenversion (READ COMMITTED),
sieht `status='failed'` und liefert null Zeilen. Kein Doppelversand, ohne
Advisory Locks, ohne zusaetzliche Tabelle, ohne DDL.

Warum 'failed' als Zwischenzustand und nicht der huebschere Weg?
Der Claim ist VOR dem Senden committet. Stirbt der Prozess mitten im
Versand, bleibt der Entwurf liegen und wird nie erneut versendet —
Zustellung hoechstens einmal (at-most-once). Die naheliegende Alternative,
`select … for update skip locked` ueber den HTTP-Aufruf hinweg offen zu
halten, liest sich schoener, liefert aber at-least-once: ein Absturz nach
erfolgreichem Senden gaebe die Zeile wieder als 'approved' frei und die
naechste Runde schickt dieselbe Nachricht ein zweites Mal an einen echten
Menschen. Ein liegengebliebener Entwurf ist das kleinere Uebel.

Sichtbarkeit des Zwischenzustands: ein geclaimter Entwurf steht als
status='failed' mit error='in Zustellung seit <UTC-Zeitstempel>
(dispatcher <Marke>)' in der DB — fuer einen Menschen also lesbar als
„in Zustellung", mit Zeitpunkt. Steht er laenger so da, ist der Dispatcher
waehrend genau dieses Versands gestorben.

MEDIEN-ENTWUERFE (Stufe 4, F4)
------------------------------
Traegt ein Entwurf ein `media_ref`, geht er ueber den Media-Endpunkt von
OpenWA raus (Endung -> send-document/send-image/send-audio, Nutzlast base64,
Text als Bildunterschrift) — EIN Aufruf, wie beim Text. Die Datei wird
unmittelbar vor dem Senden erneut gegen `medien.pruefe` gehalten; faellt sie
durch (typisch: seit der Freigabe geloescht), wird der Entwurf mit klarem
Grund fehlgeschlagen gebucht. Ein Ersatzversand als reiner Text findet
ausdruecklich NICHT statt: freigegeben wurde eine Nachricht mit Unterlage.

KEIN RETRY. Ein fehlgeschlagener Entwurf bleibt 'failed' — weder in dieser
noch in einer spaeteren Runde wird er erneut probiert. Der Weg zurueck
fuehrt ueber einen Menschen, der neu freigibt. Das ist Absicht: bei einer
Vertriebsnachricht soll jemand hinschauen, bevor sie doch noch rausgeht.
"""
import base64
import json
import logging
import os
import signal
import socket
import sys
import threading
import urllib.error
import urllib.request
import uuid

import psycopg

import medien
import server
from nummern import normalisiere_empfaenger
from server import _jetzt

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
OPENWA_URL = os.environ.get("OPENWA_URL", "http://openwa:2785")
OPENWA_SESSION_ID = os.environ.get("OPENWA_SESSION_ID", "")
OPENWA_API_KEY = os.environ.get("OPENWA_API_KEY", "")
HTTP_TIMEOUT_S = float(os.environ.get("OPENWA_TIMEOUT_S", "30"))
DISPATCH_INTERVAL_S = float(os.environ.get("DISPATCH_INTERVAL_S", "10"))
DISPATCH_ONCE = os.environ.get("DISPATCH_ONCE", "").strip().lower() in (
    "1", "true", "yes", "ja")
STAPEL = 5                 # Entwuerfe je Runde (Plan T3)
FEHLER_MAXLAENGE = 300     # drafts.error wird hart gekuerzt
CLAIM_PRAEFIX = "in Zustellung seit "

# Pause zwischen zwei tatsaechlichen Sendungen einer Runde (T5a). Fuenf
# Nachrichten im selben Sekundenbruchteil sind fuer WhatsApp das Muster eines
# Bots, nicht das eines Menschen — und der Stapel steht ohnehin nicht unter
# Zeitdruck. Gewartet wird nur gegenueber OpenWA: ein Entwurf, der die
# Empfaengerpruefung gar nicht besteht, hat das Netz nie beruehrt und haelt
# den Rest deshalb nicht auf. `_STOPP.wait` statt `time.sleep`, damit ein
# SIGTERM die Pause sofort beendet.
_SENDE_PAUSE_VORGABE = 1.0
SENDE_PAUSE_S = float(os.environ.get("DISPATCH_SENDE_PAUSE_S",
                                     _SENDE_PAUSE_VORGABE))
# Ausgaenge, nach denen tatsaechlich ein HTTP-Aufruf stattgefunden hat.
_NETZ_AUSGAENGE = frozenset(("gesendet", "fehler", "gesendet_ohne_buchung"))

LOG = logging.getLogger("sales-dispatch")
_STOPP = threading.Event()


class VersandFehler(Exception):
    """Fehlgeschlagener Zustellversuch mit menschenlesbarem Grund."""


# ---------------------------------------------------------------------------
# Empfaenger
# ---------------------------------------------------------------------------

# `normalisiere_empfaenger` lebt seit T5a in `nummern.py` und wird von dort
# importiert (oben). Der Grund ist keine Aufraeumlust: `entwuerfe_offen` in
# server.py zeigt dem Betreiber VOR der Freigabe an, an welche Nummer ein
# Entwurf ginge — diese Anzeige und dieser Versand duerfen nie zwei
# verschiedene Regeln benutzen, sonst gibt jemand etwas anderes frei als das,
# was passiert. Der Name bleibt im Modul-Namensraum sichtbar
# (`dispatch.normalisiere_empfaenger`), Aufrufer und Tests bleiben unveraendert.


def _maskiert(chat_id: str) -> str:
    """Fuer Logzeilen: Landesvorwahl + letzte drei Stellen, Rest verdeckt.

    Die vollstaendige Nummer steht im Aktivitaets-Log in der Datenbank, wo
    sie hingehoert — nicht in einem Containerlog, das jeder `docker logs`
    ausspuckt.
    """
    ziffern = chat_id.split("@", 1)[0]
    return f"{ziffern[:4]}…{ziffern[-3:]}" if len(ziffern) >= 9 else "…"


# ---------------------------------------------------------------------------
# Claim / Buchung
# ---------------------------------------------------------------------------

def _claim_marke() -> str:
    return f"{CLAIM_PRAEFIX}{_jetzt()} (dispatcher {uuid.uuid4().hex[:8]})"


def claim(draft_id):
    """Atomarer Claim approved -> failed+Marke. Siehe Moduldocstring.

    Rueckgabe: Zeile inkl. `marke`, oder None wenn ein anderer schneller war
    (bzw. der Entwurf nicht mehr approved/whatsapp ist).
    """
    marke = _claim_marke()
    zeilen = server._q(
        "update drafts set status = 'failed', error = %s "
        "where id = %s and status = 'approved' and channel = 'whatsapp' "
        "returning id, lead_id, recipient, subject, body, media_ref",
        (marke, draft_id))
    if not zeilen:
        return None
    geclaimt = dict(zeilen[0])
    geclaimt["marke"] = marke
    return geclaimt


def _als_gesendet_buchen(draft_id, marke) -> bool:
    """failed+eigene Marke -> sent. Die Marke im WHERE stellt sicher, dass
    wir nur unseren eigenen Claim aufloesen und keinen fremden."""
    return bool(server._q(
        "update drafts set status = 'sent', sent_at = now(), error = null "
        "where id = %s and status = 'failed' and error = %s returning id",
        (draft_id, marke)))


def _als_fehler_buchen(draft_id, marke, text) -> bool:
    """Marke durch den echten Fehlertext ersetzen; status bleibt 'failed'.

    Die Rueckgabe wird ausgewertet, weil ihr Ausbleiben teuer ist: greift das
    UPDATE nicht (die Marke steht nicht mehr da — jemand hat den Entwurf
    nebenher erneut freigegeben, oder ein zweiter Dispatcher war am Werk),
    dann behaelt der Entwurf die Marke „in Zustellung seit …". Fuer einen
    Menschen sieht er dann aus wie ein haengender Versand, und
    `entwurf_erneut_freigeben` verweigert die erneute Freigabe dauerhaft ohne
    `bestaetigt=True` — der echte Grund waere nirgends aufgeschrieben.
    Deshalb LOG.critical statt stillschweigend weiterlaufen.
    """
    gebucht = bool(server._q(
        "update drafts set error = %s "
        "where id = %s and status = 'failed' and error = %s returning id",
        (text[:FEHLER_MAXLAENGE], draft_id, marke)))
    if not gebucht:
        LOG.critical(
            "draft=%s Fehlergrund NICHT gebucht — der eigene Claim steht nicht "
            "mehr in der Zeile. Der Entwurf traegt weiter die Marke "
            "'in Zustellung' und braucht einen Menschen. Grund war: %s",
            draft_id, _einzeilig(text))
    return gebucht


def _versand_loggen(geclaimt, chat_id, basis=None) -> None:
    # `medien_datei` steht nur dann im Payload, wenn wirklich ein Anhang mitging
    # — die Historie soll zeigen, was beim Empfaenger ankam, nicht nur dass
    # etwas ankam. Ein zusaetzlicher Schluessel, kein geaenderter: bestehende
    # Auswertungen lesen weiter, was sie kennen.
    inhalt = {"draft_id": str(geclaimt["id"]), "kanal": "whatsapp",
              "weg": "dispatcher", "chat_id": chat_id}
    if basis:
        inhalt["medien_datei"] = basis
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"], json.dumps(inhalt, ensure_ascii=False)))


# ---------------------------------------------------------------------------
# OpenWA
# ---------------------------------------------------------------------------

def _einzeilig(text: str) -> str:
    return " ".join((text or "").split())[:FEHLER_MAXLAENGE]


def _senden(endpunkt: str, nutzlast: dict) -> None:
    """POST /api/sessions/{id}/messages/{endpunkt}. Wirft VersandFehler.

    Ein gemeinsamer Weg fuer Text und Medien: die Abbildung der Ausfaelle auf
    lesbare Fehlertexte (und damit auf `drafts.error`) darf nicht in zwei
    Fassungen existieren, sonst liest der Betreiber je nach Entwurfsart andere
    Gruende fuer denselben Ausfall.
    """
    try:
        # Der Request wird INNERHALB des try gebaut (T5a). `Request(...)`
        # wirft schon beim Konstruieren ValueError("unknown url type"), wenn
        # OPENWA_URL kein brauchbares Schema hat — eine vertippte Compose-Zeile
        # riss so die ganze Schleife ab, statt eine Fehlerbuchung zu erzeugen.
        # Der Dispatcher darf an einer Fehlkonfiguration nicht sterben: der
        # Entwurf ist zu diesem Zeitpunkt bereits geclaimt und bliebe sonst
        # ohne jeden Grund im Zustand „in Zustellung" liegen.
        ziel = (f"{OPENWA_URL.rstrip('/')}/api/sessions/{OPENWA_SESSION_ID}"
                f"/messages/{endpunkt}")
        anfrage = urllib.request.Request(
            ziel, method="POST",
            data=json.dumps(nutzlast).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "X-API-Key": OPENWA_API_KEY})
        with urllib.request.urlopen(anfrage, timeout=HTTP_TIMEOUT_S) as antwort:
            antwort.read()
    except urllib.error.HTTPError as e:   # muss vor URLError stehen
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:                 # noqa: BLE001 — Detail ist Beiwerk
            detail = ""
        raise VersandFehler(
            f"OpenWA HTTP {e.code}: {_einzeilig(detail)}") from None
    except socket.timeout:                # ab 3.10 identisch mit TimeoutError
        raise VersandFehler(
            f"OpenWA Zeitueberschreitung nach {HTTP_TIMEOUT_S:g} s") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise VersandFehler(
                f"OpenWA Zeitueberschreitung nach {HTTP_TIMEOUT_S:g} s") from None
        raise VersandFehler(
            f"OpenWA nicht erreichbar: {_einzeilig(str(e.reason))}") from None
    except Exception as e:                # noqa: BLE001 — nie als Traceback sterben
        raise VersandFehler(
            f"Versandfehler {type(e).__name__}: {_einzeilig(str(e))}") from None


def sende_text(chat_id: str, text: str) -> None:
    """Reiner Text — der Weg jedes Entwurfs ohne Anhang."""
    _senden("send-text", {"chatId": chat_id, "text": text})


def sende_medium(chat_id: str, text: str, basis: str) -> None:
    """Anhang + Text in EINER Nachricht. Wirft VersandFehler.

    Gemessen an der OpenWA-Quelle (Herleitung im Kopf von medien.py): der
    Endpunkt folgt der Endung (pdf -> send-document, jpg/jpeg/png ->
    send-image, mp3/ogg -> send-audio), die Datei reist als `base64` mit
    zwingendem `mimetype`, der Dateiname als `filename`, und der Entwurfstext
    als `caption`. Deshalb genau EIN Aufruf je Entwurf — kein zweiter Send mit
    dem Text, denn zwei Nachrichten waeren beim Empfaenger etwas anderes als
    die eine, die der Betreiber freigegeben hat.

    Die Datei wird hier gelesen, nicht frueher: zwischen Pruefung und Lesen
    liegt ein Wimpernschlag, aber ein Fehlschlag genau darin (Datei in der
    Sekunde geloescht) muss dieselbe saubere Fehlerbuchung ergeben wie jeder
    andere Ausfall.
    """
    endpunkt, mimetype = medien.endpunkt_und_typ(basis)
    try:
        rohdaten = medien.lies(basis)
    except OSError as e:
        raise VersandFehler(
            f"Anhang '{basis}' nicht lesbar ({type(e).__name__}) — "
            f"nichts gesendet.") from None
    _senden(endpunkt, {"chatId": chat_id,
                       "base64": base64.b64encode(rohdaten).decode("ascii"),
                       "mimetype": mimetype,
                       "filename": basis,
                       "caption": text})


# ---------------------------------------------------------------------------
# Schleife
# ---------------------------------------------------------------------------

def verarbeite_draft(draft_id) -> str:
    """Ein Entwurf: claimen, pruefen, senden, buchen. Gibt den Ausgang zurueck."""
    geclaimt = claim(draft_id)
    if geclaimt is None:
        LOG.info("draft=%s uebersprungen (nicht mehr approved oder fremd geclaimt)",
                 draft_id)
        return "uebersprungen"
    marke = geclaimt["marke"]

    chat_id, fehler = normalisiere_empfaenger(geclaimt["recipient"])
    if fehler:
        _als_fehler_buchen(draft_id, marke, fehler)
        LOG.info("draft=%s nicht zugestellt (%s)", draft_id, fehler)
        return "unzustellbar"

    # Der Anhang wird HIER erneut geprueft, obwohl entwurf_erstellen ihn schon
    # geprueft hat: zwischen Erstellung, Freigabe und Zustellung koennen
    # Minuten liegen, und /media ist ein Host-Bind, in dem der Betreiber
    # jederzeit aufraeumt. Faellt die Pruefung jetzt durch, wird der Entwurf
    # fehlgeschlagen gebucht — es geht ausdruecklich KEIN Ersatzversand als
    # reiner Text raus: freigegeben wurde eine Nachricht MIT Unterlage, und
    # was der Empfaenger bekommt, muss das sein, was ein Mensch freigegeben
    # hat. Dieselbe Funktion wie in server.py (medien.py), damit Anzeige,
    # Freigabe und Versand nie auseinanderlaufen.
    basis = None
    if geclaimt["media_ref"]:
        basis, medienfehler = medien.pruefe(geclaimt["media_ref"])
        if medienfehler:
            _als_fehler_buchen(draft_id, marke,
                               f"Anhang nicht versandfaehig: {medienfehler}")
            LOG.info("draft=%s nicht zugestellt (%s)", draft_id, medienfehler)
            return "anhang_fehlt"

    try:
        # Betreff wird bewusst nicht mitgesendet: WhatsApp kennt keinen.
        if basis:
            sende_medium(chat_id, geclaimt["body"], basis)
        else:
            sende_text(chat_id, geclaimt["body"])
    except VersandFehler as e:
        _als_fehler_buchen(draft_id, marke, str(e))
        LOG.info("draft=%s fehlgeschlagen an %s (%s)", draft_id,
                 _maskiert(chat_id), _einzeilig(str(e)))
        return "fehler"

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
        if gebucht:
            _versand_loggen(geclaimt, chat_id, basis)
    except psycopg.Error as e:
        gebucht = False
        LOG.critical("draft=%s GESENDET, Buchung scheiterte: %s", draft_id,
                     _einzeilig(str(e)))
    if not gebucht:
        # Nachricht ist raus, der Statuswechsel nicht durchgekommen. Der
        # Entwurf bleibt als geclaimt liegen und wird nie erneut versendet —
        # genau dafuer ist der Claim vor dem Senden da.
        LOG.critical("draft=%s GESENDET, aber Status nicht auf 'sent' gebucht "
                     "— Entwurf bleibt geclaimt liegen, kein zweiter Versand",
                     draft_id)
        return "gesendet_ohne_buchung"

    LOG.info("draft=%s gesendet an %s%s", draft_id, _maskiert(chat_id),
             f" (Anhang {basis})" if basis else "")
    return "gesendet"


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene WhatsApp-Entwuerfe, aelteste zuerst.

    Zwischen zwei tatsaechlichen Sendungen liegt SENDE_PAUSE_S (siehe dort).
    Nach einem Entwurf, der OpenWA gar nicht erreicht hat — uebersprungen oder
    unzustellbar —, wird nicht gewartet: die Pause gilt dem Empfaengerdienst,
    nicht der Datenbank.
    """
    zeilen = server._q(
        "select id from drafts where status = 'approved' and channel = 'whatsapp' "
        "order by created_at limit %s", (STAPEL,))
    bilanz = {}
    letzter_ausgang = None
    for z in zeilen:
        if letzter_ausgang in _NETZ_AUSGAENGE and SENDE_PAUSE_S > 0:
            _STOPP.wait(SENDE_PAUSE_S)      # unterbrechbar durch SIGTERM
        letzter_ausgang = verarbeite_draft(z["id"])
        bilanz[letzter_ausgang] = bilanz.get(letzter_ausgang, 0) + 1
    return bilanz


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen — Ende nach der laufenden Runde.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout statt logging.basicConfig().

    Gemessen: `import server` zieht ueber das mcp-Paket eine
    Root-Konfiguration hoch (StreamHandler auf **stderr**, Format
    "%(message)s"). `basicConfig()` ist dann ein stiller No-op — die
    Dispatcher-Zeilen landeten ohne Zeitstempel und ohne Level auf stderr
    statt, wie vorgesehen, auf stdout. Deshalb haengt der Handler direkt am
    Modul-Logger, mit propagate=False, damit nichts doppelt erscheint.
    """
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

    fehlend = [name for name, wert in (("OPENWA_SESSION_ID", OPENWA_SESSION_ID),
                                       ("OPENWA_API_KEY", OPENWA_API_KEY))
               if not wert]
    if fehlend:
        LOG.error("Konfiguration unvollstaendig — %s fehlt in der Umgebung. "
                  "Es wird nichts versendet.", ", ".join(fehlend))
        return 2

    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) — dann eben ohne Handler
    LOG.info("Start: schema=%s openwa=%s session=%s intervall=%gs pause=%gs "
             "once=%s", server.SCHEMA, OPENWA_URL, OPENWA_SESSION_ID,
             DISPATCH_INTERVAL_S, SENDE_PAUSE_S, DISPATCH_ONCE)

    while not _STOPP.is_set():
        try:
            bilanz = eine_runde()
            if bilanz:
                LOG.info("Runde: %s", bilanz)
        except psycopg.Error as e:
            LOG.error("Datenbankfehler — Runde uebersprungen: %s",
                      _einzeilig(str(e)))
        if DISPATCH_ONCE:
            LOG.info("DISPATCH_ONCE — eine Runde gelaufen, Ende.")
            break
        _STOPP.wait(DISPATCH_INTERVAL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
