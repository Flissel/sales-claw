"""sales-telegram — der Zwilling des Dispatchers fuer den Kanal Telegram.

Er liest AUSSCHLIESSLICH freigegebene Telegram-Entwuerfe
(`drafts.status='approved' and channel='telegram'`) und stellt sie ueber die
Bot-API zu. Das Freigabe-Gate ist damit auch hier die Datenbank und nicht
das Verhalten eines Sprachmodells — `channel='telegram'` steht in jeder
Query, auch im Claim, genauso wie `channel='whatsapp'` in dispatch.py und
`channel='email'` in mail_dispatch.py steht.

WARUM ES DIESEN DIENST GIBT (Betreiber-Entscheid 12.09.2026)
-------------------------------------------------------------
sales-claw ist seit diesem Tag der einzige Versandweg des Hauses (Spec
`docs/superpowers/specs/2026-09-12-sales-claw-einziger-versandweg.md`).
Marketing hatte einen eigenen, sorgfaeltig gebauten Telegram-Versender
(`spaces/marketing/tools/_send_telegram.py`, 12 Gates) — der ist jetzt
gesperrt, und ohne diesen Dienst hier waere der Kanal ersatzlos
weggefallen. Deshalb wurde jener Versender gesperrt und NICHT geloescht:
die Opt-in-Ueberlegung unten stammt woertlich von dort.

DIE PLATTFORM ERZWINGT DEN ERSTKONTAKT — UND ERSETZT DIE EINWILLIGUNG NICHT
--------------------------------------------------------------------------
Ein Bot kann keinen Chat eroeffnen; die Gegenseite muss ihn zuerst mit
`/start` angeschrieben haben. Dass eine `chat_id` ueberhaupt existiert, ist
also ein von Telegram selbst erzwungener Erstkontakt. Das ist ERREICHBARKEIT
— keine Erlaubnis zur Werbung. Beides bleibt getrennt: `telegram_freigeben`
haelt die Erreichbarkeit am Kontakt fest, `einwilligung_erfassen` die
Erlaubnis, und `entwurf_erstellen` prueft beide. Hier unten wird deshalb
NICHTS davon noch einmal beurteilt: dieser Dienst stellt zu, was ein Mensch
freigegeben hat.

WAS AUS dispatch.py IMPORTIERT WIRD — und warum nicht kopiert
-------------------------------------------------------------
Claim-Marke, Erfolgs- und Fehlerbuchung sind kanalunabhaengig; sie arbeiten
auf `drafts.status` und `drafts.error`. Sie werden deshalb IMPORTIERT, nicht
abgeschrieben — dieselbe Begruendung wie in mail_dispatch.py:
`entwurf_erneut_freigeben` in server.py erkennt einen haengenden Versand
daran, dass `drafts.error` mit `dispatch.CLAIM_PRAEFIX` beginnt. Eine
zweite, aehnliche Marke setzte die Schutzkante gegen Doppelversand fuer
Telegram-Entwuerfe still ausser Kraft.

CLAIM, at-most-once, kein Retry
-------------------------------
Wortgleich zu dispatch.py und mail_dispatch.py, inklusive Begruendung: der
Claim laeuft ueber den erlaubten Uebergang approved -> failed mit einer
Marke im `error`-Feld (DDL ist der Rolle `sales_app` verboten, ein Status
'sending' existiert nicht). Er ist VOR dem Senden committet. Stirbt der
Prozess mitten im Versand, bleibt der Entwurf liegen und wird nie erneut
versendet. Fehlgeschlagene Entwuerfe werden NIE automatisch wiederholt —
der Weg zurueck fuehrt ueber einen Menschen, der neu freigibt.

KEINE ANHAENGE
--------------
Diese Fassung versendet reinen Text. Traegt ein Entwurf ein `media_ref`,
wird er ausdruecklich FEHLGESCHLAGEN gebucht, statt ohne die Unterlage
rauszugehen — dieselbe Regel und derselbe Grund wie bei mail_dispatch:
„freigegeben wurde eine Nachricht MIT Unterlage". Telegram KOENNTE Bilder
und Dokumente (`sendDocument`, `sendPhoto`); das waere eine eigene Stufe
mit eigener Pruefung des Medienordners, und sie still mitzunehmen hiesse,
ungeprueft Dateien zu verschicken.

4096 ZEICHEN — GEMESSENE GRENZE
-------------------------------
`sendMessage` lehnt laengere Texte mit HTTP 400 ab. Das faellt hier VOR dem
Netzgriff auf, nicht danach: ein Entwurf, der am Zeichenlimit scheitert,
soll das mit einem Satz sagen, den ein Mensch versteht, statt als
„Bad Request" im Log zu enden.
"""
import json
import logging
import os
import signal
import sys
import threading
import urllib.error
import urllib.request

import psycopg

import dispatch
import server
import telegram_chat
from dispatch import (_als_fehler_buchen, _als_gesendet_buchen, _claim_marke,
                      _einzeilig)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API_BASIS = os.environ.get("TELEGRAM_API_BASIS", "https://api.telegram.org").rstrip("/")
TIMEOUT_S = float(os.environ.get("TELEGRAM_TIMEOUT_S", "20"))
INTERVAL_S = float(os.environ.get("TELEGRAM_INTERVAL_S", "10"))
EINMAL = os.environ.get("TELEGRAM_ONCE", "").strip().lower() in (
    "1", "true", "yes", "ja")

STAPEL = 5                 # Entwuerfe je Runde, wie bei den Zwillingen
SENDE_PAUSE_S = float(os.environ.get("TELEGRAM_SENDE_PAUSE_S", "1.0"))

# Gemessene Grenze von sendMessage (Telegram-Doku, Stand 2026): 4096 Zeichen.
TEXT_MAXLAENGE = 4096

LOG = logging.getLogger("sales-telegram")
_STOPP = threading.Event()

# Ausgaenge, nach denen tatsaechlich eine Verbindung zur Bot-API stattfand —
# nur danach wird pausiert (gleiche Regel wie bei den Zwillingen: die Pause
# gilt dem Empfaengerdienst, nicht der Datenbank).
_NETZ_AUSGAENGE = frozenset(("gesendet", "fehler", "gesendet_ohne_buchung"))


class VersandFehler(Exception):
    """Fehlgeschlagener Zustellversuch mit menschenlesbarem Grund."""


def _ohne_token(text: str) -> str:
    """Der Bot-Token steht in JEDER URL dieses Dienstes.

    Ein Fehlertext aus urllib traegt die aufgerufene URL mit — und die
    landet ueber `_als_fehler_buchen` in `drafts.error`, also in der
    Datenbank und in der Oberflaeche. Ohne diese Filterung stuende der
    Token dort im Klartext. Gleiche Ueberlegung wie `_ohne_geheimnis` in
    mail_dispatch.py.
    """
    sauber = text or ""
    if BOT_TOKEN:
        sauber = sauber.replace(BOT_TOKEN, "***")
    return sauber


def _maskiert(chat_id: str) -> str:
    """Fuers Log: nur die letzten vier Ziffern.

    Die vollstaendige chat_id steht in der versand-Aktivitaet in der
    Datenbank, wo sie hingehoert — nicht in einem Containerlog, das jeder
    `docker logs` ausspuckt. Gleiche Regel wie `dispatch._maskiert`.
    """
    text = str(chat_id or "")
    return ("…" + text[-4:]) if len(text) > 4 else "…"


# ---------------------------------------------------------------------------
# Claim / Buchung
# ---------------------------------------------------------------------------

def claim(draft_id):
    """Atomarer Claim approved -> failed+Marke, NUR fuer channel='telegram'.

    Eigene Fassung statt `dispatch.claim`, weil dort `channel = 'whatsapp'`
    im WHERE steht — und genau diese Klausel ist die Kanaltrennung. Marke
    und Semantik sind dieselben (siehe Moduldocstring).
    """
    marke = _claim_marke()
    zeilen = server._q(
        "update drafts set status = 'failed', error = %s "
        "where id = %s and status = 'approved' and channel = 'telegram' "
        "returning id, lead_id, recipient, subject, body, media_ref",
        (marke, draft_id))
    if not zeilen:
        return None
    geclaimt = dict(zeilen[0])
    geclaimt["marke"] = marke
    return geclaimt


def _versand_loggen(geclaimt, chat_id) -> None:
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (geclaimt["lead_id"],
         json.dumps({"draft_id": str(geclaimt["id"]), "kanal": "telegram",
                     "weg": "telegram-dispatcher", "empfaenger": str(chat_id)},
                    ensure_ascii=False)))


# ---------------------------------------------------------------------------
# Bot-API
# ---------------------------------------------------------------------------

def _text_bauen(betreff: str, rumpf: str) -> str:
    """Betreff und Rumpf zu EINER Nachricht.

    Telegram kennt keinen Betreff. `drafts.subject` ist bei diesem Kanal
    optional; ist er da, steht er als erste Zeile — sonst ginge die
    Ueberschrift, die ein Mensch freigegeben hat, still verloren. Bewusst
    OHNE Markdown/HTML-Auszeichnung: `parse_mode` wuerde jeden Unterstrich
    und Stern im Text zur Formatanweisung machen, und ein unpaariges
    Zeichen laesst die ganze Nachricht mit HTTP 400 scheitern.
    """
    kopf = (betreff or "").strip()
    text = (rumpf or "").strip()
    return f"{kopf}\n\n{text}" if kopf else text


def senden(chat_id: str, text: str) -> None:
    """Eine Nachricht ueber sendMessage. Wirft VersandFehler mit Grund."""
    if not BOT_TOKEN:
        raise VersandFehler("Telegram-Kanal nicht eingerichtet "
                            "(TELEGRAM_BOT_TOKEN fehlt).")
    nutzlast = json.dumps({"chat_id": int(chat_id), "text": text,
                           "disable_web_page_preview": True}).encode("utf-8")
    anfrage = urllib.request.Request(
        f"{API_BASIS}/bot{BOT_TOKEN}/sendMessage", data=nutzlast,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            roh = antwort.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        rumpf = ""
        try:
            rumpf = e.read().decode("utf-8", "replace")[:300]
        except Exception:                   # noqa: BLE001 — best effort
            pass
        # Telegram begruendet Ablehnungen im Rumpf („bot was blocked by the
        # user", „chat not found"). Genau das soll der Betreiber lesen —
        # der HTTP-Code allein saehe nach einem Ausfall aus, obwohl es eine
        # Entscheidung der Gegenseite ist.
        raise VersandFehler(_ohne_token(
            f"Telegram lehnt ab (HTTP {e.code}): {_einzeilig(rumpf)}")) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise VersandFehler(_ohne_token(
            f"Telegram nicht erreichbar ({type(e).__name__}: "
            f"{_einzeilig(str(e))[:160]})")) from e

    try:
        daten = json.loads(roh)
    except ValueError as e:
        raise VersandFehler("Telegram antwortete nicht mit JSON.") from e
    # HTTP 200 ist NICHT die Zusage: die API antwortet auch auf Ablehnungen
    # mit 200 und `ok: false`. Wer nur den Code prueft, bucht ungesendete
    # Nachrichten als gesendet.
    if not daten.get("ok"):
        raise VersandFehler(_ohne_token(
            f"Telegram lehnt ab: {_einzeilig(str(daten.get('description', daten)))[:200]}"))


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------

def verarbeite_draft(draft_id) -> str:
    """Ein Entwurf: claimen, pruefen, senden, buchen. Gibt den Ausgang zurueck."""
    geclaimt = claim(draft_id)
    if geclaimt is None:
        LOG.info("draft=%s uebersprungen (nicht mehr approved oder fremd "
                 "geclaimt)", draft_id)
        return "uebersprungen"
    marke = geclaimt["marke"]

    chat_id, fehler = telegram_chat.pruefe(geclaimt["recipient"])
    if fehler:
        _als_fehler_buchen(draft_id, marke, fehler)
        LOG.info("draft=%s nicht zugestellt (%s)", draft_id, fehler)
        return "unzustellbar"

    # Siehe Moduldocstring: lieber ein Entwurf, der auf einen Menschen
    # wartet, als eine Nachricht ohne die freigegebene Unterlage.
    if geclaimt["media_ref"]:
        grund = (f"Anhang '{geclaimt['media_ref']}' — der Telegram-Versand "
                 f"schickt in dieser Fassung nur Text. Es ging NICHTS raus "
                 f"(auch kein Text ohne Anhang). Ohne Anhang neu erstellen "
                 f"und freigeben — oder die Unterlage von Hand schicken.")
        _als_fehler_buchen(draft_id, marke, grund)
        LOG.info("draft=%s nicht zugestellt (Anhang, kein Ersatzversand)",
                 draft_id)
        return "anhang_nicht_unterstuetzt"

    text = _text_bauen(geclaimt["subject"], geclaimt["body"])
    if not text:
        _als_fehler_buchen(draft_id, marke, "Der Entwurf hat keinen Text.")
        return "unzustellbar"
    if len(text) > TEXT_MAXLAENGE:
        grund = (f"Der Text ist {len(text)} Zeichen lang; Telegram nimmt "
                 f"hoechstens {TEXT_MAXLAENGE}. Es ging nichts raus — "
                 f"kuerzen und neu freigeben.")
        _als_fehler_buchen(draft_id, marke, grund)
        LOG.info("draft=%s nicht zugestellt (zu lang)", draft_id)
        return "unzustellbar"

    try:
        senden(chat_id, text)
    except VersandFehler as e:
        _als_fehler_buchen(draft_id, marke, str(e))
        LOG.info("draft=%s nicht zugestellt (%s)", draft_id, _einzeilig(str(e))[:160])
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
        LOG.critical("draft=%s GESENDET, aber Status nicht auf 'sent' gebucht "
                     "— Entwurf bleibt geclaimt liegen, kein zweiter Versand",
                     draft_id)
        return "gesendet_ohne_buchung"

    LOG.info("draft=%s gesendet an %s", draft_id, _maskiert(chat_id))
    return "gesendet"


def eine_runde() -> dict:
    """Bis zu STAPEL freigegebene Telegram-Entwuerfe, aelteste zuerst."""
    zeilen = server._q(
        "select id from drafts where status = 'approved' "
        "and channel = 'telegram' order by created_at limit %s", (STAPEL,))
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
    """Eigener Handler auf stdout (gleiche Lehre wie in den Zwillingen).

    `import server` zieht ueber das mcp-Paket eine Root-Konfiguration hoch;
    `logging.basicConfig()` waere danach ein stiller No-op. Der Handler
    haengt deshalb direkt am Modul-Logger — und ausdruecklich AUCH an
    `dispatch.LOG`, weil die importierten Buchungshelfer ihre
    `critical`-Saetze dorthin loggen. Das sind genau die Saetze, die einen
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

    if not BOT_TOKEN:
        # Exit 0, nicht 2 — wortgleiche Begruendung wie in mail_dispatch:
        # ein nicht eingerichteter Kanal ist ein gueltiger Zustand, kein
        # Ausfall, und ein Container als „Exited (2)" sieht aus wie ein
        # Fehler und wird gesucht.
        LOG.warning("Telegram-Kanal nicht eingerichtet — TELEGRAM_BOT_TOKEN "
                    "fehlt in der Umgebung (.env). Es wird nichts versendet; "
                    "freigegebene Telegram-Entwuerfe bleiben liegen.")
        return 0

    signal.signal(signal.SIGTERM, _stoppen)
    signal.signal(signal.SIGINT, _stoppen)

    LOG.info("sales-telegram startet (Takt %.0fs, Stapel %d)",
             INTERVAL_S, STAPEL)
    while not _STOPP.is_set():
        try:
            bilanz = eine_runde()
            if bilanz:
                LOG.info("Runde: %s", bilanz)
        except psycopg.Error as e:
            LOG.error("Datenbankfehler in der Runde: %s", _einzeilig(str(e))[:200])
        except Exception as e:              # noqa: BLE001 — der Dienst laeuft weiter
            LOG.exception("Unerwarteter Fehler in der Runde: %s", type(e).__name__)
        if EINMAL:
            break
        _STOPP.wait(INTERVAL_S)
    LOG.info("sales-telegram beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
