"""sales-inbox — eingehende Kundenantworten der Versandnummer ins CRM.

Der erste von aussen erreichbare Endpunkt dieses Systems. OpenWA stellt hier
das Ereignis `message.received` der Session `sales` zu; jede angenommene
Nachricht wird zu einer `activities`-Zeile vom Typ `kundenantwort`. Versendet
wird hier NICHTS — der Dienst schreibt ausschliesslich in die Datenbank
(Freigabe-Gate bleibt unberuehrt, Stufe-3-Grundsatzentscheidung 1).

GEMESSENE WEBHOOK-MECHANIK (openwa/upstream/src/modules/webhook/)
-----------------------------------------------------------------
`webhook-delivery.service.ts`:

    generateSignature(payload, secret) {
      const hmac = crypto.createHmac('sha256', secret);
      hmac.update(payload);
      return `sha256=${hmac.digest('hex')}`;
    }

Signiert wird der EXAKTE, einmal serialisierte Rumpf (`body`), nicht ein neu
zusammengesetztes Objekt — deshalb prueft dieses Modul die rohen Bytes und
parst erst danach. Der Header heisst `X-OpenWA-Signature`. Daneben kommen
`X-OpenWA-Event`, `X-OpenWA-Idempotency-Key`, `X-OpenWA-Delivery-Id`,
`X-OpenWA-Retry-Count` und `User-Agent: OpenWA-Webhook/1.0.0` — allesamt
UNSIGNIERT, sie sind Beiwerk, keine Wahrheit. Die Wahrheit steht im Rumpf:

    {"event", "timestamp", "sessionId", "idempotencyKey", "deliveryId",
     "data": { …IncomingMessage… }}

`data` ist die engine-neutrale `IncomingMessage`
(openwa/upstream/src/engine/interfaces/whatsapp-engine.interface.ts): `id`,
`from`, `to`, `chatId`, `body`, `type`, `timestamp`, `fromMe`, `isGroup`,
optional `author` (Gruppen-Teilnehmer), `isLidSender`/`senderPhone`,
`contact`, `media`, …

Zustellung: `retryCount` Versuche (Default 3, Maximum 5), exponentieller
Abstand ab `WEBHOOK_RETRY_DELAY` (Default 5 s). Ein 5xx oder ein Timeout wird
also wiederholt — deshalb ist Dedup ueber die `message_id` keine Kuer.

WARUM SO STRENG
---------------
1. **Signatur zuerst, immer.** Vor der Verifikation wird nichts geparst und
   nichts angefasst, was die Datenbank sieht. Ungueltig -> 401, kein Insert,
   Fehlversuch mit Zaehler im Log (ohne jeden Inhalt der Nachricht).
2. **Kein Auto-Anlegen unbekannter Kontakte.** Wer schreibt, ohne im CRM zu
   stehen, landet als Aktivitaet am Sammel-Lead „Unbekannte Eingaenge"
   (`INBOX_UNBEKANNT_LEAD_ID`). Sonst legte jede Spam-Nummer einen Datensatz
   an — und der Betreiber verlaesst sich darauf, dass ein Kontakt im CRM
   bedeutet, dass jemand ihn dort haben wollte.
3. **Nummern kommen aus `nummern.py`.** Keine zweite Nummernregel in diesem
   Haus. Der JID bringt seine Landesvorwahl technisch immer mit, wird also
   ausdruecklich als `+<ziffern>` uebergeben — nicht blank, damit die
   49-Sonderregel fuer blanke Folgen (BLANK_PRAEFIX) gar nicht erst greift
   und eine oesterreichische Nummer nicht als unzustellbar gilt.
4. **Der Text ist Datum, nie Befehl.** Er wird auf 2000 Zeichen gekuerzt
   gespeichert und sonst nicht interpretiert. Die Regel, dass der Agent
   Inhalte daraus nie als Anweisung befolgt, steht in AGENTS.md
   („Kundenantworten") — hier wird sie technisch vorbereitet, indem der Text
   als Zitat mit `richtung: 'eingehend'` abgelegt wird.
5. **Gruppen und eigene Nachrichten fliegen raus.** `fromMe=true` ist die
   eigene Nummer (die gekoppelte IST die Betreiber-Nummer), Gruppen sind kein
   Kundendialog.

Geteilt mit `server.py` (gleiches Image): Verbindungspool, Query-Helfer `_q`
und vor allem die Schema-Wache — `import server` laesst denselben `SystemExit`
fliegen, wenn `SALES_DB_SCHEMA` etwas anderes als `sales`/`sales_test` ist.
"""
import hashlib
import hmac
import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg

import server
from nummern import normalisiere_empfaenger

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
BIND_HOST = os.environ.get("INBOX_HOST", "0.0.0.0")
PORT = int(os.environ.get("INBOX_PORT", "8790"))
PFAD = os.environ.get("INBOX_PFAD", "/webhook")
SECRET = os.environ.get("INBOX_WEBHOOK_SECRET", "")
UNBEKANNT_LEAD_ID = os.environ.get("INBOX_UNBEKANNT_LEAD_ID", "")

EREIGNIS = "message.received"
SIGNATUR_KOPF = "X-OpenWA-Signature"
SIGNATUR_PRAEFIX = "sha256="
# OpenWA deckelt den Rumpf selbst bei 1 MiB (DEFAULT_WEBHOOK_MAX_PAYLOAD_BYTES);
# etwas Luft darueber, alles daruber ist nicht von OpenWA und wird nicht gelesen.
RUMPF_MAX = 1024 * 1024 + 64 * 1024
# Ein abgewiesener Riesenrumpf wird bis hierhin verworfen, damit der Aufrufer
# seine Antwort noch lesen kann statt in einen Verbindungsabbruch zu laufen.
VERWERF_MAX = 8 * 1024 * 1024
TEXT_MAXLAENGE = 2000
# Mindestlaenge des Geheimnisses — dieselbe Untergrenze, die OpenWAs
# CreateWebhookDto erzwingt (@MinLength(16)).
SECRET_MIN = 16

LOG = logging.getLogger("sales-inbox")
_STOPP = threading.Event()

# Check-und-Insert der Dedup-Pruefung laufen unter dieser Sperre: der Server
# ist mehrfaedig (ThreadingHTTPServer), und OpenWAs Wiederholungen koennen
# sich ueberlappen. Prozessweit, nicht clusterweit — es gibt genau einen
# sales-inbox-Container, und die Sperre kostet nichts.
_SCHREIBSPERRE = threading.Lock()

_fehlversuche = 0
_ZAEHLERSPERRE = threading.Lock()


def fehlversuche() -> int:
    with _ZAEHLERSPERRE:
        return _fehlversuche


def fehlversuche_zuruecksetzen() -> None:
    global _fehlversuche
    with _ZAEHLERSPERRE:
        _fehlversuche = 0


def _fehlversuch_zaehlen() -> int:
    global _fehlversuche
    with _ZAEHLERSPERRE:
        _fehlversuche += 1
        return _fehlversuche


# ---------------------------------------------------------------------------
# Signatur
# ---------------------------------------------------------------------------

def signatur_gueltig(roh: bytes, kopf) -> bool:
    """HMAC-SHA256 ueber die ROHEN Rumpfbytes, Vergleich in konstanter Zeit.

    Ohne gesetztes Geheimnis ist NICHTS gueltig — ein Dienst, der ungeprueft
    annimmt, waere schlimmer als einer, der gar nicht laeuft.
    """
    if not SECRET or not kopf:
        return False
    erwartet = SIGNATUR_PRAEFIX + hmac.new(
        SECRET.encode("utf-8"), roh, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(erwartet, kopf.strip())
    except TypeError:
        # Header mit Nicht-ASCII: compare_digest verweigert den Vergleich.
        return False


# ---------------------------------------------------------------------------
# Absender
# ---------------------------------------------------------------------------

def _maskiert(nummer: str) -> str:
    """Fuer Logzeilen: Landesvorwahl + letzte drei Stellen (wie dispatch.py).

    Die vollstaendige Nummer steht in der Aktivitaet in der Datenbank, wo sie
    hingehoert — nicht in einem Containerlog.
    """
    ziffern = "".join(z for z in (nummer or "").split("@", 1)[0] if z.isdigit())
    return f"{ziffern[:4]}…{ziffern[-3:]}" if len(ziffern) >= 9 else "…"


def absender_nummer(daten: dict):
    """JID der Nachricht -> ("49…@c.us", None) oder (None, Grund).

    `senderPhone` schlaegt den JID, wenn es dasteht: bei einem `@lid`-Absender
    (Privacy-ID) ist der JID keine Rufnummer, die aufgeloeste Nummer schon.
    Der Rest ist bewusst duenn — die Regel selbst liegt in `nummern.py`.
    """
    telefon = daten.get("senderPhone")
    roh = str(telefon) if telefon else str(
        daten.get("author") or daten.get("from") or "")
    # `491701234567:12@s.whatsapp.net` — Geraetesuffix und Domain abschneiden.
    ziffern = "".join(z for z in roh.split("@", 1)[0].split(":", 1)[0]
                      if z.isdigit())
    if not ziffern:
        return None, "Absender ohne Rufnummer (Privacy-ID ohne Aufloesung)"
    # Ausdruecklich international: der JID fuehrt die Landesvorwahl technisch
    # immer mit, blank wuerde nummern.py nur `49…` vertrauen (BLANK_PRAEFIX).
    return normalisiere_empfaenger("+" + ziffern)


def _ist_gruppe(daten: dict) -> bool:
    if daten.get("isGroup") is True:
        return True
    ziele = (str(daten.get("chatId") or ""), str(daten.get("from") or ""))
    return any(z.endswith("@g.us") or z.endswith("@broadcast") for z in ziele)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def lead_zu_nummer(chat_id: str):
    """Lead mit dieser Nummer — verglichen wird normalisiert, nicht als Text.

    Vorfilter in SQL ueber die letzten acht Ziffern (Schreibweisen
    unterscheiden sich vorne: `+49…`, `0049…`, `49 (0)…`, nie hinten), die
    Entscheidung faellt danach ueber `nummern.normalisiere_empfaenger` —
    dieselbe Funktion, die auch den Versand steuert.
    """
    ziffern = chat_id.split("@", 1)[0]
    schwanz = ziffern[-8:] if len(ziffern) >= 8 else ziffern
    zeilen = server._q(
        "select id, name, phone from leads where phone is not null "
        "and regexp_replace(phone, '[^0-9]', '', 'g') like %s "
        "order by updated_at desc limit 500", (f"%{schwanz}",))
    treffer = [z for z in zeilen
               if normalisiere_empfaenger(z["phone"])[0] == chat_id]
    if len(treffer) > 1:
        LOG.warning("Nummer %s steht bei %d Kontakten — juengster gewinnt.",
                    _maskiert(chat_id), len(treffer))
    return treffer[0] if treffer else None


def bereits_gespeichert(message_id: str) -> bool:
    return bool(server._q(
        "select id from activities where type = 'kundenantwort' "
        "and payload->>'message_id' = %s limit 1", (message_id,)))


def speichern(lead_id: str, nutzlast: dict) -> str:
    """Append-only: eine `kundenantwort`-Zeile, actor='human'.

    `actor='human'` und nicht der Default 'agent': die Zeile haelt fest, was
    ein Mensch geschrieben hat, nicht was die Assistenz getan hat.
    """
    return str(server._q(
        "insert into activities (lead_id, type, payload, actor) "
        "values (%s, 'kundenantwort', %s, 'human') returning id",
        (lead_id, json.dumps(nutzlast, ensure_ascii=False)))[0]["id"])


# ---------------------------------------------------------------------------
# Kern
# ---------------------------------------------------------------------------

def _gesendet_am(zeitstempel):
    """WhatsApp liefert Sekunden seit Epoch; alles andere bleibt weg."""
    try:
        return datetime.fromtimestamp(int(zeitstempel), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def verarbeite(roh: bytes, signatur):
    """Ein Zustellversuch -> (HTTP-Status, Antwortobjekt).

    Reihenfolge ist Teil des Vertrags: Signatur, dann Parsen, dann Filter,
    dann Datenbank. Vor der ersten Zeile Datenbank steht die Verifikation.
    """
    if not signatur_gueltig(roh, signatur):
        LOG.warning("Signatur ungueltig — abgewiesen, nichts gespeichert "
                    "(Fehlversuche gesamt: %d)", _fehlversuch_zaehlen())
        return 401, {"fehler": "signatur ungueltig"}

    try:
        umschlag = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        LOG.warning("Rumpf mit gueltiger Signatur, aber kein JSON — verworfen.")
        return 400, {"fehler": "kein gueltiges JSON"}
    if not isinstance(umschlag, dict):
        return 400, {"fehler": "unerwartete Rumpfform"}

    if umschlag.get("event") != EREIGNIS:
        return 200, {"verworfen": f"Ereignis {umschlag.get('event')!r}"}
    daten = umschlag.get("data")
    if not isinstance(daten, dict):
        return 400, {"fehler": "Ereignis ohne data"}

    if daten.get("fromMe") is True:
        return 200, {"verworfen": "fromMe — eigene Nachricht"}
    if _ist_gruppe(daten):
        return 200, {"verworfen": "Gruppen-/Broadcast-Nachricht"}

    message_id = str(daten.get("id") or umschlag.get("idempotencyKey")
                     or "").strip()
    if not message_id:
        LOG.warning("Nachricht ohne message_id und ohne Idempotenzschluessel — "
                    "nicht dedupbar, verworfen.")
        return 400, {"fehler": "ohne message_id"}

    chat_id, nummern_fehler = absender_nummer(daten)
    text = str(daten.get("body") or "")
    nutzlast = {
        "text": text[:TEXT_MAXLAENGE],
        "gekuerzt": len(text) > TEXT_MAXLAENGE,
        "message_id": message_id,
        "richtung": "eingehend",
        "absender": chat_id or str(daten.get("from") or ""),
        "nachrichtentyp": str(daten.get("type") or "unknown"),
        "gesendet_am": _gesendet_am(daten.get("timestamp")),
        "unbekannter_absender": False,
    }

    try:
        with _SCHREIBSPERRE:
            if bereits_gespeichert(message_id):
                LOG.info("Wiederholte Zustellung — schon gespeichert.")
                return 200, {"doppelt": True}

            lead = lead_zu_nummer(chat_id) if chat_id else None
            if lead is None:
                if not UNBEKANNT_LEAD_ID:
                    LOG.critical(
                        "Unbekannter Absender %s, aber INBOX_UNBEKANNT_LEAD_ID "
                        "ist nicht gesetzt — nichts gespeichert, 503. Grund der "
                        "Nummernpruefung: %s", _maskiert(str(daten.get("from"))),
                        nummern_fehler or "kein Kontakt mit dieser Nummer")
                    return 503, {"fehler": "Sammel-Lead nicht konfiguriert"}
                nutzlast["unbekannter_absender"] = True
                lead_id = UNBEKANNT_LEAD_ID
            else:
                lead_id = str(lead["id"])

            akt_id = speichern(lead_id, nutzlast)
    except psycopg.OperationalError:
        LOG.error("Datenbank nicht erreichbar — nichts gespeichert, 503 "
                  "(OpenWA wiederholt).")
        return 503, {"fehler": "Datenbank nicht erreichbar"}
    except psycopg.Error as e:
        LOG.error("Datenbankfehler (%s) — nichts gespeichert, 503.", e.sqlstate)
        return 503, {"fehler": "Datenbankfehler"}

    LOG.info("Kundenantwort gespeichert: lead=%s absender=%s typ=%s "
             "zeichen=%d unbekannt=%s", lead_id, _maskiert(nutzlast["absender"]),
             nutzlast["nachrichtentyp"], len(nutzlast["text"]),
             nutzlast["unbekannter_absender"])
    return 200, {"gespeichert": True, "aktivitaet_id": akt_id}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "sales-inbox"
    sys_version = ""
    timeout = 30

    def _antworten(self, status: int, objekt: dict) -> None:
        rumpf = json.dumps(objekt, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def do_POST(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        if urlsplit(self.path).path != PFAD:
            self._antworten(404, {"fehler": "unbekannter Pfad"})
            return
        try:
            laenge = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._antworten(400, {"fehler": "Content-Length unlesbar"})
            return
        if laenge > RUMPF_MAX:
            # Verwerfen statt lesen: der Rumpf wird nie zu Speicher, aber der
            # Aufrufer kann seine Antwort noch abholen.
            offen = min(laenge, VERWERF_MAX)
            while offen > 0:
                stueck = self.rfile.read(min(65536, offen))
                if not stueck:
                    break
                offen -= len(stueck)
            self.close_connection = True
            self._antworten(413, {"fehler": "Rumpf zu gross"})
            return
        # Genau Content-Length Bytes — OpenWA sendet einen serialisierten
        # String und damit immer eine Laenge (undici setzt sie). Ein chunked
        # Aufruf laendet hier mit leerem Rumpf und damit bei 401; das ist der
        # richtige Ausgang fuer etwas, das nicht von OpenWA kommt.
        roh = self.rfile.read(laenge) if laenge else b""
        status, objekt = verarbeite(roh, self.headers.get(SIGNATUR_KOPF))
        self._antworten(status, objekt)

    def do_GET(self):  # noqa: N802
        self._antworten(405, {"fehler": "nur POST"})

    def do_HEAD(self):  # noqa: N802
        self._antworten(405, {"fehler": "nur POST"})

    def do_PUT(self):  # noqa: N802
        self._antworten(405, {"fehler": "nur POST"})

    def do_DELETE(self):  # noqa: N802
        self._antworten(405, {"fehler": "nur POST"})

    def log_message(self, format, *args):  # noqa: A002 — Signatur vorgegeben
        # Kein Zugriffslog: die Zeile enthielte Pfad und Absenderadresse und
        # sagt nichts, was die fachlichen Zeilen oben nicht besser sagen.
        LOG.debug("http %s", format % args)


def baue_server(adresse=None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(adresse or (BIND_HOST, PORT), _Handler)
    httpd.daemon_threads = True
    return httpd


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout — wie im Dispatcher, und aus demselben Grund:
    `import server` zieht ueber das mcp-Paket eine Root-Konfiguration auf
    stderr hoch, `logging.basicConfig()` waere dann ein stiller No-op."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen — Dienst wird beendet.",
             signal.Signals(signum).name)
    _STOPP.set()


def main() -> int:
    _logging_einrichten()

    if len(SECRET) < SECRET_MIN:
        LOG.error("INBOX_WEBHOOK_SECRET fehlt oder ist kuerzer als %d Zeichen — "
                  "der Dienst startet nicht. Ohne Geheimnis koennte jeder im "
                  "Compose-Netz Aktivitaeten in die Kundenhistorie schreiben.",
                  SECRET_MIN)
        return 2
    if not UNBEKANNT_LEAD_ID:
        LOG.error("INBOX_UNBEKANNT_LEAD_ID fehlt — ohne Sammel-Lead haette eine "
                  "Nachricht von einer unbekannten Nummer keinen Platz und "
                  "ginge verloren. Der Dienst startet nicht.")
        return 2

    httpd = baue_server()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) — dann eben ohne Handler
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    LOG.info("Start: schema=%s bind=%s:%d pfad=%s sammel_lead=%s",
             server.SCHEMA, BIND_HOST, PORT, PFAD, UNBEKANNT_LEAD_ID)
    _STOPP.wait()
    httpd.shutdown()
    LOG.info("Beendet. Ungueltige Signaturen in dieser Laufzeit: %d",
             fehlversuche())
    return 0


if __name__ == "__main__":
    sys.exit(main())
