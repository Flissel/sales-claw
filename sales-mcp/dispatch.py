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

KEIN RETRY. Ein fehlgeschlagener Entwurf bleibt 'failed' — weder in dieser
noch in einer spaeteren Runde wird er erneut probiert. Der Weg zurueck
fuehrt ueber einen Menschen, der neu freigibt. Das ist Absicht: bei einer
Vertriebsnachricht soll jemand hinschauen, bevor sie doch noch rausgeht.
"""
import json
import logging
import os
import re
import signal
import socket
import sys
import threading
import urllib.error
import urllib.request
import uuid

import psycopg

import server
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

LOG = logging.getLogger("sales-dispatch")
_STOPP = threading.Event()


class VersandFehler(Exception):
    """Fehlgeschlagener Zustellversuch mit menschenlesbarem Grund."""


# ---------------------------------------------------------------------------
# Empfaenger
# ---------------------------------------------------------------------------

# Trenner, die in notierten Telefonnummern ueblich sind. Alles andere macht
# den Empfaenger unzustellbar — wir raten nicht.
_TRENNER = re.compile(r"[\s\-./() ‑]")
_NUMMER = re.compile(r"(\+|00)?\d{8,15}\Z")


def normalisiere_empfaenger(recipient):
    """`recipient` -> ("49…@c.us", None) oder (None, Fehlertext).

    Der bekannte Befund aus Stufe 2 (entwurf_erstellen faellt auf den
    Kontaktnamen zurueck, wenn keine Telefonnummer hinterlegt ist) wird hier
    zur harten Pruefung: nur etwas, das als Ganzes eine Telefonnummer ist,
    wird zugestellt. Mischformen wie "Herr Mueller 0170 1234567" werden
    bewusst NICHT auseinandergenommen — bei einer Nachricht an einen echten
    Menschen ist Raten die teurere Option als eine Rueckfrage.

    Autonome Festlegung (Betrieb ist durchgehend deutsch): eine fuehrende
    Amtsnull ohne Landesvorwahl wird als deutsche Nummer gelesen
    (0170… -> 49170…), ebenso der Einschub "(0)" und eine Amtsnull direkt
    hinter der 49. Andere Landesvorwahlen bleiben unangetastet.
    """
    roh = (recipient or "").strip()
    if not roh:
        return None, "kein zustellbarer Empfaenger"
    kern = _TRENNER.sub("", roh.replace("(0)", ""))
    if not _NUMMER.fullmatch(kern):
        return None, "kein zustellbarer Empfaenger"

    if kern.startswith("+"):
        ziffern = kern[1:]
    elif kern.startswith("00"):
        ziffern = kern[2:]
    elif kern.startswith("0"):
        ziffern = "49" + kern[1:]          # deutsche Amtsnull
    else:
        ziffern = kern
    if ziffern.startswith("490"):          # Amtsnull hinter der Landesvorwahl
        ziffern = "49" + ziffern[3:]

    if not 8 <= len(ziffern) <= 15:
        return None, "kein zustellbarer Empfaenger"
    return f"{ziffern}@c.us", None


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
        "returning id, lead_id, recipient, subject, body", (marke, draft_id))
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


def _als_fehler_buchen(draft_id, marke, text) -> None:
    """Marke durch den echten Fehlertext ersetzen; status bleibt 'failed'."""
    server._q(
        "update drafts set error = %s "
        "where id = %s and status = 'failed' and error = %s returning id",
        (text[:FEHLER_MAXLAENGE], draft_id, marke))


def _versand_loggen(geclaimt, chat_id) -> None:
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": "whatsapp",
                     "weg": "dispatcher", "chat_id": chat_id},
                    ensure_ascii=False)))


# ---------------------------------------------------------------------------
# OpenWA
# ---------------------------------------------------------------------------

def _einzeilig(text: str) -> str:
    return " ".join((text or "").split())[:FEHLER_MAXLAENGE]


def sende_text(chat_id: str, text: str) -> None:
    """POST /api/sessions/{id}/messages/send-text. Wirft VersandFehler."""
    ziel = (f"{OPENWA_URL.rstrip('/')}/api/sessions/{OPENWA_SESSION_ID}"
            f"/messages/send-text")
    anfrage = urllib.request.Request(
        ziel, method="POST",
        data=json.dumps({"chatId": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "X-API-Key": OPENWA_API_KEY})
    try:
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

    try:
        # Betreff wird bewusst nicht mitgesendet: WhatsApp kennt keinen.
        sende_text(chat_id, geclaimt["body"])
    except VersandFehler as e:
        _als_fehler_buchen(draft_id, marke, str(e))
        LOG.info("draft=%s fehlgeschlagen an %s (%s)", draft_id,
                 _maskiert(chat_id), _einzeilig(str(e)))
        return "fehler"

    try:
        gebucht = _als_gesendet_buchen(draft_id, marke)
        if gebucht:
            _versand_loggen(geclaimt, chat_id)
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

    LOG.info("draft=%s gesendet an %s", draft_id, _maskiert(chat_id))
    return "gesendet"


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene WhatsApp-Entwuerfe, aelteste zuerst."""
    zeilen = server._q(
        "select id from drafts where status = 'approved' and channel = 'whatsapp' "
        "order by created_at limit %s", (STAPEL,))
    bilanz = {}
    for z in zeilen:
        ausgang = verarbeite_draft(z["id"])
        bilanz[ausgang] = bilanz.get(ausgang, 0) + 1
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
    LOG.info("Start: schema=%s openwa=%s session=%s intervall=%gs once=%s",
             server.SCHEMA, OPENWA_URL, OPENWA_SESSION_ID,
             DISPATCH_INTERVAL_S, DISPATCH_ONCE)

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
