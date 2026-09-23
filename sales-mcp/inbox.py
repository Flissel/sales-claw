"""sales-inbox — Nachrichtenverkehr der Versandnummer ins CRM.

Der erste von aussen erreichbare Endpunkt dieses Systems. OpenWA stellt hier
`message.received` (der Kunde schreibt) und `message.sent` (von diesem Konto
ging etwas raus) der Session `sales` zu; daraus werden `activities`-Zeilen vom
Typ `kundenantwort` bzw. `nachricht_ausgehend`. Versendet wird hier NICHTS —
der Dienst schreibt ausschliesslich in die Datenbank (Freigabe-Gate bleibt
unberuehrt, Stufe-3-Grundsatzentscheidung 1).

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

GEMESSENE fromMe-SEMANTIK (Stufe 8) — WER IST DER KUNDE?
--------------------------------------------------------
Eine eigene Nachricht (`fromMe: true`) dreht die Felder um. Quelle,
`openwa/upstream/src/engine/adapters/message-mapper.ts` (whatsapp-web.js ist
die konfigurierte Engine, `ENGINE_TYPE` in docker-compose.openwa.yml):

    // For an outgoing (fromMe) message `from` is the account's own JID and
    // `to` is the conversation; for an incoming message it's the reverse.
    // So the chat is `to` when fromMe, else `from`.
    const chatId = msg.fromMe ? msg.to : msg.from;

Der Baileys-Mapper sagt dasselbe ausdruecklich (`baileys-message-mapper.ts`:
`from: fields.fromMe ? self : chatId`). Also:

    fromMe=false ->  chatId == from  (der Kunde schreibt)
    fromMe=true  ->  chatId == to    (wir schreiben dem Kunden),
                     `from` traegt die EIGENE Nummer

Gegenprobe an echten Daten statt an der Doku (openwa.sqlite, Tabelle
`messages`, 180 Zeilen zum Zeitpunkt der Messung):

    direction | chatId=from | chatId=to | from=to |   n
    ----------+-------------+-----------+---------+-----
    incoming  |      1      |     0     |    0    |  72
    outgoing  |      0      |     1     |    0    | 107
    outgoing  |      1      |     1     |    1    |   1

Die letzte Zeile ist der SELBST-CHAT: eigene Nummer an eigene Nummer, der
Notizzettel-/Bot-Kanal. Er ist daran erkennbar — und nur daran —, dass
`chatId` und `from` dieselbe Nummer tragen. Er wird verworfen (siehe Punkt 6),
sonst schriebe jede Digest-Zustellung und jeder Systemtest eine
„Antwort an den Kunden" ins Postfach.

Und ein zweiter gemessener Punkt, ohne den E1 tot waere: eine eigene
Nachricht kommt NICHT als `message.received`. `message-projector.service.ts`
dispatcht den Eingang als `message.received` und das Echo eines eigenen
Sendens (wwebjs-Ereignis `message_create`, dort `if (!msg.fromMe) return;`)
als `message.sent` — gleiche Nutzlast, anderer Ereignisname. Deshalb nimmt
dieses Modul beide Ereignisse an und entscheidet dann am `fromMe`-Feld, nicht
am Ereignisnamen: die Nutzlast ist die Wahrheit, der Name ist Beiwerk (und
Baileys/`*`-Abos schneiden anders). Der REGISTRIERTE Webhook ist davon
unberuehrt: er abonniert heute nur `message.received` und muss vom Betreiber
um `message.sent` erweitert werden (docs/03_RUNBOOK.md).

WER HAT GESCHRIEBEN — DIE REIHENFOLGE (Stufe 11, T2)
----------------------------------------------------
WhatsApp adressiert die Chats dieser Session seit dem 18.08.2026 fast
durchgehend als `@lid` (Privacy-ID) statt `@c.us` (Rufnummer). Eine `@lid` ist
KEINE Rufnummer. Aufgeloest wird deshalb in genau dieser Reihenfolge
(`_kennung`), jede Stufe nur, wenn die vorige nichts hergab:

    senderPhone (OpenWA)  ->  gespeicherte Zuordnung  ->  Sammelkontakt

`senderPhone` entsteht nur, wenn OpenWAs `RESOLVE_LID_TO_PHONE` an ist, und
nur in der EINGANGSRICHTUNG (message-projector.service.ts, `!fromMe`-Zweig).
Die zweite Stufe — `server.lid_telefon`, gespeist aus `absender_aufloesen`
und den Entscheidungen des Betreibers — traegt deshalb die AUSGANGSRICHTUNG
mit. Ohne sie waere das Flag ein Schuss ins Knie: eingehende `absender`
wuerden Rufnummern, ausgehende `empfaenger` blieben LIDs, und die
absenderscharfe Beantwortet-Pruefung faende nie mehr ein Paar (Review-Befund
M1, docs/03_RUNBOOK.md).

Bleibt alles erfolglos, wird die Kennung ausdruecklich als `183…@lid`
gebucht — NICHT als `183…@c.us`. Die alte Schreibweise sah aus wie eine
Rufnummer und hat dazu verleitet, sie als Kontakt anzulegen (Befund H1).

WAS VON EINEM IGNORIERTEN CHAT GESPEICHERT WIRD (Stufe 11, T5)
--------------------------------------------------------------
Hat der Betreiber einen Absender ueber `eingang_einordnen` als „ignorieren"
eingeordnet, wird aus diesem Chat KEIN Nachrichtentext mehr gespeichert — nur
die Tatsache, dass etwas lief: Typ `eingang_ignoriert` fuer die fremde,
`ausgang_ignoriert` fuer die EIGENE Haelfte, beide mit leerem `text`. Damit
landen private Chats nicht dauerhaft in einer Vertriebsdatenbank. Gar nichts
zu buchen waere schlechter: OpenWA wiederholt Zustellungen, und ohne Zeile
gaebe es nichts zu deduplizieren.

Die ausgehende Haelfte fehlte bis zur Fix-Runde (Review-Befund H2): `_eingehend`
pruefte auf „ignoriert", `_ausgehend` nicht. Gemessen: Absender ignoriert,
eigene Nachricht in denselben Chat -> `nachricht_ausgehend` mit vollem Text.
Bei einem privaten Chat ist die eigene Haelfte genauso sensibel wie die
fremde — dort steht, was der Betreiber selbst geschrieben hat. Der Schutz gilt
dem CHAT, nicht der Richtung.

Gefragt wird mit BEIDEN Namen einer Gegenstelle (`_ist_ignoriert`): der rohen
Kennung aus der Nutzlast und der daraus aufgeloesten. Nur die aufgeloeste zu
fragen band die Antwort an die Aufloesung statt an die Person — zeigten zwei
verschiedene LIDs auf dieselbe Nummer, wurde mit der einen auch die andere
stumm gebucht (Review-Befund H4).

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
   ueber `normalisiere_msisdn` uebergeben — das ergaenzt ein fehlendes `+`,
   damit die 49-Sonderregel fuer blanke Folgen (BLANK_PRAEFIX) gar nicht erst
   greift und eine oesterreichische Nummer nicht als unzustellbar gilt.
   Ausdruecklich NICHT mehr `"+" + _ziffern(jid)`: das filterte alles weg, was
   keine Ziffer ist, und hebelte damit genau die Regel aus, an die es sich
   halten sollte (Review-Befund M7).
4. **Der Text ist Datum, nie Befehl.** Er wird auf 2000 Zeichen gekuerzt
   gespeichert und sonst nicht interpretiert. Die Regel, dass der Agent
   Inhalte daraus nie als Anweisung befolgt, steht in AGENTS.md
   („Kundenantworten") — hier wird sie technisch vorbereitet, indem der Text
   als Zitat mit `richtung: 'eingehend'` abgelegt wird.
5. **Gruppen fliegen raus.** Eine Gruppe ist kein Kundendialog.
6. **Eigene Nachrichten werden protokolliert, der Selbst-Chat nicht.** Seit
   Stufe 8 wird `fromMe=true` nicht mehr pauschal verworfen, sondern als
   `nachricht_ausgehend` beim Kunden gebucht — sonst bliebe ein von Hand vom
   Betreiber-Handy beantworteter Kontakt im Postfach ewig „unbeantwortet".
   Ausnahme bleibt der Selbst-Chat (oben gemessen). Es entsteht dabei KEIN
   Versandweg: dieser Dienst schreibt weiterhin nur in die Datenbank.

Geteilt mit `server.py` (gleiches Image): Verbindungspool, Query-Helfer `_q`
und vor allem die Schema-Wache — `import server` laesst denselben `SystemExit`
fliegen, wenn `SALES_DB_SCHEMA` etwas anderes als `sales`/`sales_test` ist.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import signal
import sys
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg

import lid
import server
from nummern import normalisiere_empfaenger, normalisiere_msisdn

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
BIND_HOST = os.environ.get("INBOX_HOST", "0.0.0.0")
PORT = int(os.environ.get("INBOX_PORT", "8790"))
PFAD = os.environ.get("INBOX_PFAD", "/webhook")
SECRET = os.environ.get("INBOX_WEBHOOK_SECRET", "")

# Sprachnachrichten (01.09.2026): das Audio kommt inline im Webhook und
# wird hier NUR abgelegt — transkribiert wird spaeter im Routinelauf.
# 'voice' ist die Schreibweise, die OpenWA tatsaechlich schickt (gemessen:
# 16 in 30 Tagen); 'ptt' und 'audio' kommen daneben vor.
SPRACH_VERZEICHNIS = os.environ.get("SPRACH_DIR", "/sprachnachrichten")
SPRACH_TYPEN = ("voice", "ptt", "audio")
# UI-Plan Schritt 4b (02.09.2026): Anhaenge, die der Betreiber AN SICH SELBST
# schickt, sind ein Upload in die Medien (Herkunft "chat"). Nur diese Typen,
# nur in den erzeugten Ordner (der einzige, den dieser Dienst schreibt).
ANHANG_TYPEN = ("image", "video", "document")
ERZEUGT_VERZEICHNIS = os.environ.get("MEDIA_ERZEUGT_DIR", "/media-erzeugt")
_ANHANG_ENDUNG = {"application/pdf": ".pdf", "image/jpeg": ".jpg",
                  "image/png": ".png", "video/mp4": ".mp4",
                  "audio/mpeg": ".mp3", "audio/ogg": ".ogg"}
SPRACH_MAX_BYTES = int(os.environ.get("SPRACH_MAX_BYTES",
                                      str(25 * 1024 * 1024)))
UNBEKANNT_LEAD_ID = os.environ.get("INBOX_UNBEKANNT_LEAD_ID", "")

EREIGNIS = "message.received"
# Das Echo eines eigenen Sendens (Stufe 8, gemessen im Moduldocstring). Beide
# Ereignisse tragen dieselbe IncomingMessage-Nutzlast; unterschieden wird
# danach am `fromMe`-Feld, nicht am Namen.
EREIGNIS_AUSGEHEND = "message.sent"
EREIGNISSE = (EREIGNIS, EREIGNIS_AUSGEHEND)
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


def _ziffern(jid) -> str:
    """Blanke Ziffern eines JID — Domain und `:geraet`-Suffix fallen weg.

    Nur zum VERGLEICHEN zweier JIDs (Selbst-Chat-Erkennung), nie zum
    Speichern: was gespeichert wird, geht durch `nummern.py`. Diese Funktion
    FILTERT — `49a17b29186846` wird hier klaglos zu `491729186846`. Genau
    deshalb darf ihr Ergebnis nie zur gespeicherten Nummer werden
    (Review-Befund M7); dafuer gibt es `_rohteil` und `normalisiere_msisdn`.
    """
    return "".join(z for z in str(jid or "").split("@", 1)[0].split(":", 1)[0]
                   if z.isdigit())


def _rohteil(jid) -> str:
    """Der Kennungsteil VOR Domain und `:geraet`-Suffix — ungefiltert.

    Gegenstueck zu `_ziffern`: das hier schneidet nur die technische Huelle ab
    und wirft nichts weg. Was danach keine Nummer ist, soll auch keine werden.
    """
    return str(jid or "").split("@", 1)[0].split(":", 1)[0].strip()


def _kennung(roh, senderphone=None):
    """Rohe Gegenstelle -> (Kennung, Quelle, Grund). DIE Reihenfolge (T2).

    Drei Stufen, in genau dieser Reihenfolge — jede spaetere greift nur, wenn
    die vorige nichts hergab:

    1. **`senderPhone`** (OpenWA hat selbst aufgeloest). Steht nur bei
       eingehenden Nachrichten und nur, wenn `RESOLVE_LID_TO_PHONE` an ist
       (gemessen: message-projector.service.ts setzt es im `!fromMe`-Zweig).
    2. **Die gespeicherte Zuordnung** (`server.lid_telefon`) — was ein
       frueherer `absender_aufloesen`-Lauf oder der Betreiber selbst
       eingetragen hat. Das ist die Gegenrichtung, ohne die Punkt 1 die
       Beantwortet-Pruefung zerlegen wuerde (Review-Befund M1).
    3. **Die Kennung selbst**, unaufgeloest — und dann ausdruecklich als
       `183…@lid`, NICHT als `183…@c.us`. Eine LID ist keine Rufnummer; sie
       als solche auszugeben hat schon einmal dazu verleitet, sie als Kontakt
       anzulegen (Review-Befund H1). Der Sammelkontakt faengt sie auf.

    Eine Gegenstelle OHNE `@lid`-Domain (`…@c.us`, `…@s.whatsapp.net`, mit
    oder ohne `:geraet`-Suffix) ist eine echte Rufnummer und laeuft direkt
    durch `nummern.py` — ausdruecklich als `+<ziffern>`, damit die
    49-Sonderregel fuer blanke Folgen (BLANK_PRAEFIX) nicht greift und eine
    oesterreichische Nummer nicht als unzustellbar gilt.
    """
    # Ein `senderPhone`, das sich nicht normalisieren laesst, faellt
    # stillschweigend auf die naechste Stufe durch: es ist ein Hinweis von
    # OpenWA, keine Wahrheit — und die Kennung selbst kennen wir immer noch.
    #
    # Der ROHWERT geht durch nummern.py, nicht `"+" + _ziffern(...)`
    # (Review-Befund M7): `_ziffern` filtert jedes Nicht-Ziffernzeichen weg und
    # das vorangestellte `+` erklaerte den Rest zur internationalen
    # Schreibweise. Aus `49a17b29186846` wurde so `491729186846@c.us` — die
    # Nummer eines echten Kunden, in dessen Historie die fremde Nachricht dann
    # gebucht wurde. `normalisiere_msisdn` ergaenzt das `+` nur, wenn der Wert
    # weder `+` noch `00` noch eine fuehrende `0` mitbringt.
    if senderphone:
        chat_id, _fehler = normalisiere_msisdn(_rohteil(senderphone))
        if chat_id:
            return chat_id, "senderPhone", None

    ziffern = _ziffern(roh)
    if not ziffern:
        return None, None, "Gegenstelle ohne lesbare Kennung"

    if lid.ist_lid(roh):
        telefon = server.lid_telefon(ziffern)
        if telefon:
            return telefon, "zuordnung", None
        # Unaufgeloest: als LID kenntlich weitergeben, nicht als Rufnummer.
        return lid.als_lid(ziffern), "lid", None

    chat_id, fehler = normalisiere_msisdn(_rohteil(roh))
    return chat_id, ("jid" if chat_id else None), fehler


def absender_kennung(daten: dict):
    """Wer hat geschrieben -> (Kennung, Quelle, Grund).

    Die Kennung ist entweder eine Rufnummer (`49…@c.us`) oder eine
    unaufgeloeste Privacy-ID (`183…@lid`). Bei Gruppen-Nachrichten steht der
    Teilnehmer in `author`, sonst in `from`.
    """
    return _kennung(daten.get("author") or daten.get("from"),
                    daten.get("senderPhone"))


def empfaenger_kennung(daten: dict):
    """Bei einer EIGENEN Nachricht: der Chat, in dem sie steht -> Gegenstelle.

    Gegenstueck zu `absender_kennung`, und bewusst eine eigene Funktion: bei
    `fromMe` traegt `from` die eigene Nummer, der Kunde steht in `chatId`
    (== `to`; gemessen, siehe Moduldocstring). Wer hier `absender_kennung`
    benutzte, buchte jede eigene Antwort auf die eigene Nummer.

    `senderPhone` wird hier NICHT gelesen: es entsteht nur im
    `!fromMe`-Zweig — die ausgehende Richtung kommt ueber die gespeicherte
    Zuordnung zum selben Ergebnis (T3).
    """
    return _kennung(daten.get("chatId") or daten.get("to"))


def selbst_chat_grund(daten: dict):
    """Verwerfungsgrund, wenn diese eigene Nachricht im Selbst-Chat steht.

    Der Selbst-Chat ist der Notizzettel-/Bot-Kanal des Betreibers: dort landen
    Digest-Zustellungen und Systemtests. Er ist kein Kundenverkehr, und wuerde
    er als `nachricht_ausgehend` gebucht, flutete jede Digest-Zustellung das
    Postfach. Erkennungsregel GEMESSEN (Quelle + echte Daten im
    Moduldocstring): bei `fromMe` traegt `from` die eigene Nummer und `chatId`
    den Chat — sind beide dieselbe Nummer, schreibt das Konto an sich selbst.

    Ist eine der beiden Seiten nicht lesbar, wird ebenfalls verworfen. Das ist
    die bewusste Richtung des Zweifels: eine verpasste Antwort laesst einen
    Kontakt laenger als noetig „unbeantwortet" aussehen (sichtbar, harmlos),
    ein faelschlich gebuchter Selbst-Chat verstopft das Postfach mit dem
    eigenen Bot-Verkehr (unsichtbar, schaedlich).
    """
    roh_chat = daten.get("chatId") or daten.get("to")
    roh_eigen = daten.get("from")
    chat = _ziffern(roh_chat)
    eigen = _ziffern(roh_eigen)
    if not chat or not eigen:
        return "eigene Nachricht ohne lesbare Chat-/Absenderkennung"
    if chat == eigen:
        return SELBST_CHAT
    # LID-FORM (23.09.2026). Seit WhatsApp Chats als `@lid` adressiert, traegt
    # im Selbst-Chat `from` die eigene RUFNUMMER und `chatId` die eigene LID.
    # Der Ziffernvergleich oben sah darin zwei Kennungen — gemessen wurden so
    # vom 21.08. bis 23.09.2026 1211 Bot-Antworten, Digest-Zustellungen und
    # weitergereichte Nachrichten als Kundenverkehr am Sammelkontakt gebucht,
    # und der Datei-Upload an sich selbst (Schritt 4b) lief ins Leere.
    # Verglichen werden deshalb zusaetzlich die AUFGELOESTEN Formen — ueber
    # die gespeicherte Zuordnung, nie ueber eine Live-Abfrage bei OpenWA
    # (heisser Pfad, Rate-Limit nach zehn Abfragen).
    if _aufgeloeste_ziffern(roh_chat) == _aufgeloeste_ziffern(roh_eigen):
        return SELBST_CHAT
    return None


SELBST_CHAT = "Selbst-Chat (Notizzettel-/Bot-Kanal), kein Kundenverkehr"


def _aufgeloeste_ziffern(jid) -> str:
    """Ziffern der Person hinter einem JID — eine `@lid` ueber die Zuordnung.

    Ohne Zuordnung bleibt die LID, was sie ist, und zaehlt als eigene
    Kennung: lieber einen Selbst-Chat verpassen (sichtbar im Sammelkontakt)
    als einen Kunden-Chat verwerfen (unsichtbar, sein Text waere weg). Ein
    Datenbankfehler endet ebenso — er kommt beim Buchen ohnehin wieder hoch,
    dort mit dem richtigen Status fuer OpenWA.
    """
    ziffern = _ziffern(jid)
    if not lid.ist_lid(jid):
        return ziffern
    try:
        telefon = server.lid_telefon(ziffern)
    except psycopg.Error:
        return ziffern
    return _ziffern(telefon) if telefon else ziffern


def _ist_gruppe(daten: dict) -> bool:
    if daten.get("isGroup") is True:
        return True
    ziele = (str(daten.get("chatId") or ""), str(daten.get("from") or ""))
    return any(z.endswith("@g.us") or z.endswith("@broadcast") for z in ziele)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def _lead_mit_phone(chat_id: str):
    """Lead, dessen `phone` GENAU diese Nummer ist — oder None.

    Vorfilter in SQL ueber die letzten acht Ziffern (Schreibweisen
    unterscheiden sich vorne: `+49…`, `0049…`, `49 (0)…`, nie hinten), die
    Entscheidung faellt danach ueber `nummern.normalisiere_empfaenger` —
    dieselbe Funktion, die auch den Versand steuert.
    """
    ziffern = chat_id.split("@", 1)[0]
    schwanz = ziffern[-8:] if len(ziffern) >= 8 else ziffern
    zeilen = server._q(
        "select id, name, phone, enrichment from leads where phone is not null "
        "and regexp_replace(phone, '[^0-9]', '', 'g') like %s "
        "order by updated_at desc limit 500", (f"%{schwanz}",))
    treffer = [z for z in zeilen
               if normalisiere_empfaenger(z["phone"])[0] == chat_id]
    if len(treffer) > 1:
        LOG.warning("Nummer %s steht bei %d Kontakten — juengster gewinnt.",
                    _maskiert(chat_id), len(treffer))
    return treffer[0] if treffer else None


def lead_zu_nummer(chat_id: str):
    """Wem gehoert diese Kennung? Erst die Nummer selbst, dann die Zuordnung.

    ZWEI STUFEN, UND DIE REIHENFOLGE IST DER KERN (23.09.2026).

    1. `leads.phone` — die Nummer, die am Kontakt steht.
    2. Die gespeicherte Zuordnung: was der Betreiber ueber
       `eingang_einordnen(entscheidung='zuordnen')` gesagt hat, oder was ein
       `absender_aufloesen`-Lauf von OpenWA erfahren hat. GENAU EIN Schritt.

    Stufe 2 gab es hier bisher nicht. `_kennung` befragt die Zuordnung zwar,
    aber NUR im `@lid`-Zweig — eine Rufnummer lief daran vorbei. Damit war die
    Zusage, die `eingang_einordnen` dem Betreiber woertlich gibt („Kuenftige
    Nachrichten von dieser Kennung laufen zum Kontakt mit dieser Nummer"), fuer
    jede Kennung unwahr, die selbst schon eine Nummer war. GEMESSEN am echten
    Bestand: am 01.09.2026 ordnete der Betreiber `491791714185` dem Kontakt
    hinter `4917688014635@c.us` zu; bis zum 22.09.2026 landeten trotzdem 217
    Nachrichten desselben Menschen am Sammelkontakt, und er kam immer wieder
    zum Einordnen. Ein Mensch mit zwei Nummern hatte in diesem System keinen
    Platz — `leads.phone` ist EINE Spalte.

    WARUM RUECKFALL UND NICHT VORLAUF. Die Zuordnung darf erst greifen, wenn
    die Nummer selbst niemanden findet. Sonst zerlegt eine veraltete Zeile,
    was laengst stimmt: dieselbe Zuordnung zeigt heute von Ivans NEUER Nummer
    auf seine ALTE, waehrend sein Kontakt inzwischen die neue traegt. Vorn
    angewendet schickte sie ihn auf eine Nummer, die kein Kontakt mehr hat —
    zurueck an den Sammelkontakt, den er gerade verlassen hat. Festgehalten in
    `test_der_DIREKTE_treffer_schlaegt_eine_veraltete_zuordnung`.

    WARUM GENAU EIN SCHRITT. `A->B` und `B->C` sind zwei Aussagen des
    Betreibers; „A ist C" ist seine dritte, die er nie getroffen hat. Eine
    Kette koennte ausserdem im Kreis laufen. Ein Schritt ist beweisbar das,
    was dasteht.

    Es entsteht dabei NIE ein Kontakt: zeigt die Zuordnung auf eine Nummer,
    die niemandem gehoert, bleibt der Absender unbekannt und wird gefragt.
    """
    lead = _lead_mit_phone(chat_id)
    if lead is not None:
        return lead
    ueber = server.lid_telefon(chat_id)
    if not ueber or ueber == chat_id:
        return None
    lead = _lead_mit_phone(ueber)
    if lead is not None:
        LOG.info("Kennung %s ueber die gespeicherte Zuordnung aufgeloest.",
                 _maskiert(chat_id))
    return lead


# Beide Richtungen teilen sich den Dedup-Raum: eine WhatsApp-message_id ist
# eindeutig, und eine Wiederholung soll auch dann greifen, wenn OpenWA
# dasselbe Ereignis einmal als `message.received` und einmal als
# `message.sent` zustellte (ein `*`-Abo oder ein Engine-Wechsel machen das
# moeglich). Zwei getrennte Pruefungen liessen genau diese Zeile doppelt.
# `eingang_ignoriert` gehoert dazu, obwohl es keinen Text traegt (Stufe 11):
# eine wiederholte Zustellung darf auch dort keine zweite Zeile erzeugen.
EINGANG_IGNORIERT = server.EINGANG_IGNORIERT
AUSGANG_IGNORIERT = server.AUSGANG_IGNORIERT
PROTOKOLL_TYPEN = ("kundenantwort", "nachricht_ausgehend", EINGANG_IGNORIERT,
                   AUSGANG_IGNORIERT)


def bereits_gespeichert(message_id: str) -> bool:
    return bool(server._q(
        "select id from activities where type = any(%s) "
        "and payload->>'message_id' = %s limit 1",
        (list(PROTOKOLL_TYPEN), message_id)))


def speichern(lead_id: str, nutzlast: dict, typ: str = "kundenantwort",
              actor: str = "human") -> str:
    """Append-only: eine Protokollzeile in `activities`.

    Eingehend ist `actor='human'` und nicht der Default 'agent': die Zeile
    haelt fest, was ein Mensch geschrieben hat, nicht was die Assistenz getan
    hat. Ausgehend steht 'agent' (siehe `_ausgehend`) — abweichend vom Plan,
    der 'system' vorsah: `activities_actor_check` erlaubt nur
    ('agent','human','cron'), und DDL ist in dieser Stufe verboten.
    """
    return str(server._q(
        "insert into activities (lead_id, type, payload, actor) "
        "values (%s, %s, %s, %s) returning id",
        (lead_id, typ, json.dumps(nutzlast, ensure_ascii=False), actor))[0]["id"])


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

    if umschlag.get("event") not in EREIGNISSE:
        return 200, {"verworfen": f"Ereignis {umschlag.get('event')!r}"}
    daten = umschlag.get("data")
    if not isinstance(daten, dict):
        return 400, {"fehler": "Ereignis ohne data"}

    if _ist_gruppe(daten):
        return 200, {"verworfen": "Gruppen-/Broadcast-Nachricht"}

    message_id = str(daten.get("id") or umschlag.get("idempotencyKey")
                     or "").strip()
    if not message_id:
        LOG.warning("Nachricht ohne message_id und ohne Idempotenzschluessel — "
                    "nicht dedupbar, verworfen.")
        return 400, {"fehler": "ohne message_id"}

    # Entschieden wird am `fromMe`-Feld, NICHT am Ereignisnamen: die Nutzlast
    # ist die Wahrheit (Moduldocstring), und ein `*`-Abo oder ein anderer
    # Engine-Adapter kann dieselbe Nachricht unter anderem Namen zustellen.
    if daten.get("fromMe") is True:
        return _ausgehend(daten, message_id)
    if umschlag.get("event") == "message.sent":
        # Widerspruch: ein Sende-Echo OHNE fromMe=true. Als Eingang gelesen
        # wuerde daraus eine "kundenantwort" von der EIGENEN Nummer — das
        # Postfach fuellte sich mit den eigenen Sendungen als unbeantworteten
        # Kundeneingaengen (Review-Befund M2). Heute setzt der Mapper fromMe
        # immer; die Wache faengt den Tag, an dem das nicht mehr stimmt.
        return 200, {"verworfen": "message.sent ohne fromMe=true — "
                                  "Widerspruch, nicht gebucht"}
    return _eingehend(daten, message_id)


def _db_ausfall(e):
    """Datenbankfehler -> (503, Grund). EINE Stelle fuer alle DB-Beruehrungen.

    503 und nicht 500: OpenWA wiederholt bei 5xx (Moduldocstring), die
    Nachricht geht also nicht verloren. Ein Traceback dagegen beendet die
    Verbindung und der Aufrufer bekommt gar keine Antwort — genau das ist
    passiert, als die Aufloesung des Absenders (Stufe 11) eine zweite
    Datenbank-Beruehrung VOR den Insert legte, ohne sie mitzusichern.
    """
    if isinstance(e, psycopg.OperationalError):
        LOG.error("Datenbank nicht erreichbar — nichts gespeichert, 503 "
                  "(OpenWA wiederholt).")
        return 503, {"fehler": "Datenbank nicht erreichbar"}
    LOG.error("Datenbankfehler (%s) — nichts gespeichert, 503.", e.sqlstate)
    return 503, {"fehler": "Datenbankfehler"}


def _ist_ignoriert(roh, kennung) -> bool:
    """Hat der Betreiber DIESE Gegenstelle als „ignorieren" eingeordnet?

    Gefragt wird mit BEIDEN Namen, die eine Nachricht hat: der rohen
    Gegenstelle aus der Nutzlast (`183…@lid`) und der daraus aufgeloesten
    Kennung (`4917…@c.us`). Bis zur Fix-Runde stand hier nur die aufgeloeste
    — und damit hing die Antwort an der Aufloesung statt an der Person:
    zeigten zwei verschiedene LIDs auf dieselbe Nummer, wurde mit der einen
    auch die andere stumm gebucht, obwohl der Betreiber sie nie genannt hatte
    (Review-Befund H4). Die rohe Kennung ist das, was der Betreiber in der
    Rueckfrage gesehen und beantwortet hat; die aufgeloeste faengt den Fall,
    dass er die Rufnummer genannt hat und OpenWA jetzt die LID liefert.
    """
    namen = [n for n in (roh, kennung) if n]
    return bool(namen) and server.absender_ist_ignoriert(*namen)


def _identitaetsfelder(daten: dict) -> dict:
    """Woran sich ein Absender wiedererkennen laesst — ohne Inhalt.

    WOZU. WhatsApp stellt auf LIDs um: dieselbe Person erscheint mal unter
    ihrer Rufnummer (`4915772882471@c.us`), mal unter einer LID
    (`143151310344360`), die keinerlei Bezug zur Nummer hat. Welche Felder
    dabei STABIL bleiben, laesst sich nicht herleiten — man muss es
    beobachten. Bisher haben wir je Nachricht nur `absender` und
    `kennung_quelle` behalten; damit ist die Frage „was aendert sich, was
    nicht" nicht beantwortbar.

    WAS NICHT. Kein Nachrichtentext, keine Anhaenge, nichts ueber den
    INHALT. Nur, unter welchen Merkmalen dieselbe Nachricht hereinkam.

    UND NICHT BEI IGNORIERTEN ABSENDERN. Von denen wird ausdruecklich nur
    die Tatsache gebucht, dass etwas lief (Stufe 11, T5) — ein `push_name`
    waere dort genau der Personenbezug, den diese Regel fernhaelt.
    """
    felder = {}
    push = str(daten.get("pushName") or daten.get("notifyName") or "").strip()
    if push:
        felder["push_name"] = push[:120]
    if daten.get("isLidSender") is not None:
        felder["ist_lid_absender"] = bool(daten.get("isLidSender"))
    # Der WERT, nicht nur ob er da war: genau er ist der Schluessel zum
    # exakten Matching. Hat er gegriffen, steht er ohnehin in `absender`;
    # hat er NICHT gegriffen, ist er hier das Einzige, woran sich die LID
    # spaeter ohne Rueckfrage bei OpenWA aufloesen laesst.
    sender_phone = str(daten.get("senderPhone") or "").strip()
    felder["senderphone"] = sender_phone or None
    for feld, name in (("chatId", "chat_kennung"), ("author", "autor"),
                       ("from", "roh_from")):
        wert = str(daten.get(feld) or "").strip()
        if wert:
            felder[name] = wert[:80]
    return felder


def _eingehend(daten: dict, message_id: str):
    """Der Kunde hat geschrieben -> `kundenantwort`, actor='human'.

    AUSNAHME (Stufe 11, T5): hat der Betreiber diesen Absender als
    „ignorieren" eingeordnet, wird nur noch die TATSACHE gebucht — Typ
    `eingang_ignoriert`, ohne ein Zeichen Nachrichtentext. Damit landen
    private Freundschaftschats nicht dauerhaft in der Vertriebsdatenbank, und
    die Zeile bleibt trotzdem dedupbar (OpenWA wiederholt Zustellungen).
    Gar nichts zu buchen waere die schlechtere Wahl: dieselbe Nachricht kaeme
    dann bei jedem Wiederholungsversuch erneut an.
    """
    try:
        kennung, quelle, kennung_fehler = absender_kennung(daten)
        ignoriert = _ist_ignoriert(daten.get("author") or daten.get("from"),
                                   kennung)
    except psycopg.Error as e:
        return _db_ausfall(e)

    if ignoriert:
        nutzlast = {
            **_textteil(daten, message_id),
            "text": "", "gekuerzt": False, "ohne_text": True,
            "richtung": "eingehend",
            "absender": kennung or str(daten.get("author")
                                       or daten.get("from") or ""),
            "unbekannter_absender": False,
        }
        LOG.info("Eingang von %s ignoriert — nur die Tatsache gebucht, "
                 "kein Text.", _maskiert(kennung))
        return _buchen(EINGANG_IGNORIERT, "human", kennung, kennung_fehler,
                       nutzlast, "unbekannter_absender",
                       str(daten.get("from")))

    nutzlast = {
        **_textteil(daten, message_id),
        **_identitaetsfelder(daten),
        "richtung": "eingehend",
        "absender": kennung or str(daten.get("from") or ""),
        "unbekannter_absender": False,
    }
    if quelle:
        nutzlast["kennung_quelle"] = quelle
    return _buchen("kundenantwort", "human", kennung, kennung_fehler, nutzlast,
                   "unbekannter_absender", str(daten.get("from")),
                   audio_daten=daten)


def _ausgehend(daten: dict, message_id: str):
    """Von diesem Konto ging etwas raus -> `nachricht_ausgehend`, actor='agent'.

    Zweck (Stufe 8): das Postfach soll nur zeigen, was WIRKLICH offen ist. Ohne
    diese Zeile bliebe ein Kontakt, den der Betreiber von seinem Handy aus
    beantwortet hat, fuer immer „unbeantwortet".

    ZWEI ABSICHTLICHE DOPPELUNGEN, beide gewollt:

    1. Es wird nicht unterschieden, WER gesendet hat — der Betreiber vom Handy
       oder das Webhook-Echo eines Dispatcher-Versands. Das ist an der Nutzlast
       auch nicht entscheidbar, und fuer den Zweck egal: beides heisst „im Chat
       des Kontakts steht eine Antwort". Deshalb `weg: "unbekannt"` statt einer
       erfundenen Herkunft.
    2. Zu einem Dispatcher-Versand steht damit zweierlei in der Historie:
       `versand` (vom Dispatcher: „das System hat zugestellt", Teil des
       Gate-Protokolls, traegt die draft_id) und `nachricht_ausgehend` (von
       hier: „im Chat steht eine Antwort", Postfach-Wahrheit). Zwei Fragen,
       zwei Ereignisse — die Zeilen werden ausdruecklich NICHT zusammengelegt,
       weil ihre Abwesenheit jeweils etwas anderes bedeutet: fehlt `versand`,
       hat das System nichts zugestellt; fehlt `nachricht_ausgehend`, ist im
       Chat nichts angekommen.

    `actor='agent'` statt des im Plan genannten 'system': die Wache
    `activities_actor_check` laesst nur ('agent','human','cron') zu und DDL ist
    verboten. 'agent' ist der Spaltendefault und heisst hier, was 'system'
    heissen sollte — kein Mensch hat diese Zeile ins CRM getippt.
    """
    grund = selbst_chat_grund(daten)
    if grund:
        # Schritt 4b: eine Datei an sich selbst ist ein Upload in die
        # Medien. Alles andere im Selbst-Chat bleibt verworfen wie bisher —
        # und auch der Anhang wird NIE als Nachricht gebucht.
        if grund.startswith("Selbst-Chat"):
            name, warum = _anhang_sichern(daten, message_id)
            if name:
                return 200, {"verworfen": grund, "medien": name}
            if warum:
                LOG.info("Selbst-Chat-Anhang nicht uebernommen: %s", warum)
                return 200, {"verworfen": grund, "anhang_abgelehnt": warum}
        LOG.info("Eigene Nachricht verworfen: %s", grund)
        return 200, {"verworfen": grund}

    roh_gegenstelle = daten.get("chatId") or daten.get("to")
    try:
        kennung, quelle, kennung_fehler = empfaenger_kennung(daten)
        ignoriert = _ist_ignoriert(roh_gegenstelle, kennung)
    except psycopg.Error as e:
        return _db_ausfall(e)

    if ignoriert:
        # Spiegelbild von `_eingehend` (Stufe 11, T5 / Review-Befund H2). Die
        # eigene Haelfte eines privaten Chats ist genauso sensibel wie die
        # fremde — dort steht, was der BETREIBER geschrieben hat. Bis zur
        # Fix-Runde fehlte diese Pruefung hier, und T5 war damit nur zur
        # Haelfte eingeloest: der Kunde wurde geschuetzt, der Betreiber nicht.
        # Wie beim Eingang wird die Tatsache gebucht statt verworfen, sonst
        # brächte jeder Wiederholungsversuch von OpenWA dieselbe Zeile erneut.
        nutzlast = {
            **_textteil(daten, message_id),
            "text": "", "gekuerzt": False, "ohne_text": True,
            "richtung": "ausgehend",
            "empfaenger": kennung or str(roh_gegenstelle or ""),
            "weg": "unbekannt", "unbekannter_empfaenger": False,
        }
        LOG.info("Ausgang an %s ignoriert — nur die Tatsache gebucht, "
                 "kein Text.", _maskiert(kennung))
        return _buchen(AUSGANG_IGNORIERT, "agent", kennung, kennung_fehler,
                       nutzlast, "unbekannter_empfaenger",
                       str(roh_gegenstelle))

    nutzlast = {
        **_textteil(daten, message_id),
        "richtung": "ausgehend",
        "empfaenger": kennung or str(roh_gegenstelle or ""),
        "weg": "unbekannt",
        "unbekannter_empfaenger": False,
    }
    if quelle:
        nutzlast["kennung_quelle"] = quelle
    return _buchen("nachricht_ausgehend", "agent", kennung, kennung_fehler,
                   nutzlast, "unbekannter_empfaenger", str(roh_gegenstelle))


def _textteil(daten: dict, message_id: str) -> dict:
    """Die Felder, die beide Richtungen gleich fuehren."""
    text = str(daten.get("body") or "")
    return {
        "text": text[:TEXT_MAXLAENGE],
        "gekuerzt": len(text) > TEXT_MAXLAENGE,
        "message_id": message_id,
        "nachrichtentyp": str(daten.get("type") or "unknown"),
        "gesendet_am": _gesendet_am(daten.get("timestamp")),
    }


def _audio_sichern(daten: dict, message_id: str):
    """Sprachnachricht -> Dateiname im Sprachordner, oder None.

    Der Webhook liefert das Audio inline als base64
    (WEBHOOK_MEDIA_INLINE_MAX_BYTES, Vorgabe 1 MB) — bisher wurde es
    weggeworfen, und der Assistent war fuer 16 Nachrichten im Monat
    blind. Hier wird NUR gespeichert: transkribiert wird spaeter im
    Routinelauf (`sprachnachrichten_transkribieren`), damit der Webhook
    schnell bleibt und OpenWA nicht in den Wiederholungslauf geht.

    Vertraege: tests/test_sprachnachrichten.py.
    """
    if str(daten.get("type") or "").lower() not in SPRACH_TYPEN:
        return None
    medien = daten.get("media")
    if not isinstance(medien, dict):
        return None
    roh = medien.get("data")
    if not roh:
        return None
    try:
        audio = base64.b64decode(roh, validate=True)
    except (ValueError, TypeError):
        LOG.warning("Sprachnachricht mit unlesbarem Audio-Blob — nur die "
                    "Nachricht gebucht.")
        return None
    if not audio or len(audio) > SPRACH_MAX_BYTES:
        LOG.warning("Sprachnachricht uebersprungen (%d Bytes, Grenze %d).",
                    len(audio), SPRACH_MAX_BYTES)
        return None
    # Der Dateiname traegt die message_id (gehasht, damit kein Zeichen aus
    # fremder Hand in einen Pfad geraet) — so ist die Datei eindeutig der
    # Nachricht zugeordnet und eine Wiederholung ueberschreibt sich selbst.
    name = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32] + ".ogg"
    try:
        os.makedirs(SPRACH_VERZEICHNIS, exist_ok=True)
        with open(os.path.join(SPRACH_VERZEICHNIS, name), "wb") as datei:
            datei.write(audio)
    except OSError as e:
        LOG.warning("Sprachnachricht nicht gespeichert (%s) — die Nachricht "
                    "selbst ist gebucht.", type(e).__name__)
        return None
    LOG.info("Sprachnachricht gesichert (%d Bytes).", len(audio))
    return name


def _medien_nachladen(chat_id: str, message_id: str) -> bytes:
    """Ueber-Cap-Anhaenge kommen im Webhook nur als Marker (omitted: true);
    die Bytes liefert GET /messages/:chatId/:messageId/media (OPERATOR-
    Schluessel, den dieser Dienst ohnehin traegt)."""
    basis = os.environ.get("OPENWA_URL", "").rstrip("/")
    sitzung = os.environ.get("OPENWA_SESSION_ID", "")
    schluessel = os.environ.get("OPENWA_API_KEY", "")
    if not (basis and sitzung and schluessel):
        raise RuntimeError("OpenWA-Zugang fuer das Nachladen fehlt")
    url = (f"{basis}/api/sessions/{urllib.parse.quote(sitzung, safe='')}"
           f"/messages/{urllib.parse.quote(chat_id, safe='')}"
           f"/{urllib.parse.quote(message_id, safe='')}/media")
    anfrage = urllib.request.Request(url, headers={"X-Api-Key": schluessel})
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        return antwort.read(server.medien.MAX_BYTES + 1)


def _anhang_bytes(daten: dict, message_id: str):
    """-> (bytes | None, media-dict | None)."""
    medien = daten.get("media")
    if not isinstance(medien, dict):
        return None, None
    if medien.get("omitted") is True:
        chat = str(daten.get("chatId") or daten.get("to") or "")
        try:
            return _medien_nachladen(chat, message_id), medien
        except Exception as e:  # Netz, HTTP, fehlende Konfiguration
            LOG.warning("Anhang nicht nachladbar (%s).", type(e).__name__)
            return None, medien
    roh = medien.get("data")
    if not roh:
        return None, medien
    try:
        return base64.b64decode(roh, validate=True), medien
    except (ValueError, TypeError):
        return None, medien


def _anhang_sichern(daten: dict, message_id: str):
    """Selbst-Chat-Anhang -> (dateiname, None) | (None, grund) |
    (None, None), wenn die Nachricht gar keinen Anhang traegt.

    Geschrieben wird atomar (.teil -> os.replace) in ERZEUGT_VERZEICHNIS;
    ein vorhandener Name wird nie ueberschrieben (-2, -3, …). Erlaubt ist
    nur, was medien.pruefe_neuen_namen nimmt — der Bot kann spaeter nur
    senden, was WhatsApp auf allen Geraeten abspielt.
    """
    if str(daten.get("type") or "").lower() not in ANHANG_TYPEN:
        return None, None
    inhalt, medien = _anhang_bytes(daten, message_id)
    if medien is None:
        return None, None
    if not inhalt:
        return None, "Anhang ohne lesbare Daten"
    if len(inhalt) > server.medien.MAX_BYTES:
        return None, (f"Anhang groesser als "
                      f"{server.medien.MAX_BYTES // 1048576} MB")
    mimetype = str(medien.get("mimetype") or "").split(";")[0].strip().lower()
    name = str(medien.get("filename") or "").strip()
    if name:
        basis, fehler = server.medien.pruefe_neuen_namen(name)
        if fehler:
            return None, fehler
    elif mimetype in _ANHANG_ENDUNG:
        basis = ("chat-" + hashlib.sha256(message_id.encode("utf-8"))
                 .hexdigest()[:12] + _ANHANG_ENDUNG[mimetype])
    else:
        return None, f"Dateityp {mimetype or 'unbekannt'} ist nicht erlaubt"
    stamm, endung = os.path.splitext(basis)
    ziel = os.path.join(ERZEUGT_VERZEICHNIS, basis)
    laufnummer = 2
    while os.path.exists(ziel):
        basis = f"{stamm}-{laufnummer}{endung}"
        ziel = os.path.join(ERZEUGT_VERZEICHNIS, basis)
        laufnummer += 1
    zwischen = ziel + ".teil"
    try:
        os.makedirs(ERZEUGT_VERZEICHNIS, exist_ok=True)
        with open(zwischen, "wb") as datei:
            datei.write(inhalt)
        os.replace(zwischen, ziel)
    except OSError as e:
        try:
            os.unlink(zwischen)
        except OSError:
            pass
        return None, f"Medienordner nicht beschreibbar ({type(e).__name__})"
    try:
        server.medien_meta_setzen(basis, herkunft="chat")
    except psycopg.Error as e:
        LOG.warning("Herkunft fuer %s nicht gebucht (%s).", basis,
                    type(e).__name__)
    LOG.info("Anhang aus dem Selbst-Chat uebernommen: %s (%d Bytes)",
             basis, len(inhalt))
    return basis, None


def _buchen(typ: str, actor: str, chat_id, nummern_fehler, nutzlast: dict,
            unbekannt_schluessel: str, roh_gegenstelle: str,
            audio_daten: dict | None = None):
    """Dedup, Lead-Zuordnung und Insert unter der Schreibsperre.

    Eine Stelle fuer beide Richtungen: die Dedup-Pruefung und der
    Sammelkontakt-Rueckfall sollen nicht zweimal dastehen und auseinanderlaufen.
    """
    try:
        with _SCHREIBSPERRE:
            if bereits_gespeichert(nutzlast["message_id"]):
                LOG.info("Wiederholte Zustellung — schon gespeichert.")
                return 200, {"doppelt": True}

            lead = lead_zu_nummer(chat_id) if chat_id else None
            # Privat-Markierung (P3, 29.08.2026): fuer private Kontakte wird
            # KEIN Inhalt gespeichert — Datensparsamkeit statt Filterung.
            # 200 zurueck (OpenWA soll nicht endlos wiederholen), und das
            # Log nennt bewusst weder Nummer noch Text noch Lead-Kennung.
            if lead is not None and server._privat(lead.get("enrichment")):
                LOG.info("privater kontakt — inhalt nicht gespeichert")
                return 200, {"privat": True}
            if lead is None:
                if not UNBEKANNT_LEAD_ID:
                    LOG.critical(
                        "Unbekannte Gegenstelle %s, aber INBOX_UNBEKANNT_LEAD_ID "
                        "ist nicht gesetzt — nichts gespeichert, 503. Grund der "
                        "Nummernpruefung: %s", _maskiert(roh_gegenstelle),
                        nummern_fehler or "kein Kontakt mit dieser Nummer")
                    return 503, {"fehler": "Sammel-Lead nicht konfiguriert"}
                nutzlast[unbekannt_schluessel] = True
                lead_id = UNBEKANNT_LEAD_ID
            else:
                lead_id = str(lead["id"])

            # Audio ERST hier — nach dem Privat-Gate: fuer private
            # Kontakte darf keine Datei entstehen (Datensparsamkeit,
            # dieselbe Regel wie fuer den Text).
            if audio_daten is not None:
                name = _audio_sichern(audio_daten, nutzlast["message_id"])
                if name:
                    nutzlast["audio_datei"] = name

            akt_id = speichern(lead_id, nutzlast, typ, actor)
    except psycopg.Error as e:
        return _db_ausfall(e)

    LOG.info("%s gespeichert: lead=%s gegenstelle=%s typ=%s zeichen=%d "
             "unbekannt=%s", typ, lead_id,
             _maskiert(nutzlast.get("absender") or nutzlast.get("empfaenger")),
             nutzlast["nachrichtentyp"], len(nutzlast["text"]),
             nutzlast[unbekannt_schluessel])
    return 200, {"gespeichert": True, "aktivitaet_id": akt_id, "typ": typ}


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
