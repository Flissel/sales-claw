"""sales-post - holt die Mails aller aktiven Postfaecher und ordnet sie ein (Stufe 1).

Spec: docs/superpowers/specs/2026-10-30-post-sammelstelle-design.md, §8 Schritte 1-2.

ABHOLEN, NUR LESEND. Jedes Postfach wird mit `select("INBOX", readonly=True)`
(IMAP EXAMINE) geoeffnet: kein Flag wird gesetzt, nichts verschoben, nichts
geloescht. Stufe 1 archiviert nicht - Felix soll den ersten Lauf ueber den
Altbestand sehen, bevor irgendetwas im echten Postfach passiert (Spec §8.5).

Inkrementell ueber UID/UIDVALIDITY: je Runde und Konto hoechstens ein Stapel
UIDs oberhalb von `letzte_uid`, aelteste zuerst. So bleibt eine Runde kurz,
auch wenn der Altbestand zehntausend Mails hat; er darf Tage brauchen.
Aendert der Anbieter die UIDVALIDITY (GMX/Gmail nummerieren ein Postfach neu),
beginnt das Konto von vorn. Die alten Zeilen bleiben, bekommen aber negative
Platzhalter-UIDs, damit die neuen UIDs nicht an `unique (konto_id, imap_uid)`
scheitern; findet sich dieselbe Mail wieder (Message-ID, Absender, Betreff),
bekommt die alte Zeile ihre neue UID statt einer Dublette.

Dieselbe Mail in zwei Konten wird nur beim SELBEN Besitzer und nur bei
gleichem Absender und Betreff zusammengelegt (Spec §14.4) - eine gefaelschte
Message-ID kann so keine fremde Mail umdeuten.

EINORDNEN, NIEDRIGE PRIORITAET. Nach dem Abholen ordnet die Runde offene
Mails ein (Regeln, dann der Agent `post`), aber nur, wenn in den letzten
120 s keine Kundenantwort einging (Kunden haben Vorrang, Spec §14.5), und nur
bis zur Tagesgrenze an Modellaufrufen.

Sensibel: Treffen die festen Muster (Sicherheitscode, Passwort-Link) schon
beim Abholen, landet der Text gar nicht erst in der Datenbank. Sonst wird er
beim Einordnen als sensibel geloescht (text/auszug NULL, Spec §5).

Protokoll: nur Konto-Kennung, Zeilen-ID, Zahlen und Fehler-TYPEN. Nie
Absender, Betreff, Text oder die Ausnahme-Meldung selbst - Datenbank-Meldungen
zitieren die Zeile ("Failing row contains ..."), Netz-Meldungen manchmal das
Passwort.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import logging
import os
import re
import signal
import sys
import threading

import post_einordnung
import post_konten
import post_struktur
import postfach
import server
from gateway import GatewayFehler, GatewayTransient

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
POST_BESITZER = os.environ.get("POST_BESITZER", "").strip()
TAGESGRENZE = int(os.environ.get("POST_TAGESGRENZE", "500"))
INTERVAL_S = float(os.environ.get("POST_INTERVAL_S", "120"))
POST_ONCE = os.environ.get("POST_ONCE", "").strip().lower() in ("1", "true", "yes", "ja")
# Hoechstens so viele Einordnungen je Runde: danach wird erst wieder abgeholt
# und der Kunden-Vorrang neu geprueft, statt eine Stunde am Stueck zu rechnen.
EINORDNEN_JE_RUNDE = 25
KUNDE_PAUSE_S = 120
IMAP_TIMEOUT_S = 120          # ein haengender Anbieter darf die Runde nicht ewig halten
KOPF_MAX = 1000               # Absender/Empfaenger/Betreff: Fremddaten, gedeckelt
ANHANG_NAME_MAX = 200
ANHAENGE_MAX = 50

LOG = logging.getLogger("sales-post")
_STOPP = threading.Event()


# ---------------------------------------------------------------------------
# Abholen
# ---------------------------------------------------------------------------

def _rein(wert: str | None, laenge: int | None = None) -> str | None:
    """Postgres-text kann kein NUL-Zeichen speichern - eine einzige kaputte Mail
    wuerde sonst jede Runde an derselben Stelle scheitern."""
    if wert is None:
        return None
    wert = wert.replace("\x00", "")
    return wert[:laenge] if laenge else wert


def _text_sicher(nachricht) -> str:
    """postfach._text, aber robust gegen unbekannte Zeichensaetze (LookupError
    bei decode) - die Mail wird trotzdem gespeichert, notfalls als utf-8."""
    try:
        return postfach._text(nachricht)
    except (LookupError, UnicodeError):
        pass
    teile = nachricht.walk() if nachricht.is_multipart() else [nachricht]
    for teil in teile:
        if teil.get_content_type() in ("text/plain", "text/html"):
            roh = teil.get_payload(decode=True)
            if roh:
                text = roh.decode("utf-8", errors="replace")
                if teil.get_content_type() == "text/html":
                    text = postfach._html_zu_text(text)
                return text.strip()
    return ""


def _anhaenge(nachricht) -> list[str]:
    namen = []
    for teil in nachricht.walk():
        try:
            name = teil.get_filename()
            if name:
                name = str(email.header.make_header(email.header.decode_header(name)))
        except Exception:  # noqa: BLE001 - ein kaputter Dateiname kostet nur den Namen
            name = "(Anhang)"
        if name:
            namen.append(_rein(name, ANHANG_NAME_MAX))
        if len(namen) >= ANHAENGE_MAX:
            break
    return namen


def _datum(kopf: str):
    try:
        return email.utils.parsedate_to_datetime(kopf) if kopf else None
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _sensibel_nach_muster(von: str, betreff: str) -> bool:
    """Die festen Muster aus post_einordnung schon beim Speichern: ein
    Sicherheitscode soll gar nicht erst in der Datenbank stehen."""
    felder = {"von": von or "", "betreff": betreff or ""}
    return any(re.search(muster, felder.get(feld, ""))
               for feld, muster in post_einordnung.SENSIBEL_MUSTER)


def _mail_zerlegen(nachricht, kennung: str, uid: int) -> dict:
    von = _rein(postfach._kopf(nachricht, "From"), KOPF_MAX)
    betreff = _rein(postfach._kopf(nachricht, "Subject"), KOPF_MAX)
    message_id = _rein(postfach._kopf(nachricht, "Message-ID").strip().strip("<>"), KOPF_MAX)
    text = _rein(_text_sicher(nachricht), postfach.TEXT_MAX)
    auszug = " ".join(text.split())[:postfach.AUSZUG_MAX]
    if _sensibel_nach_muster(von, betreff):
        text = auszug = None
    return {
        "message_id": message_id or f"{kennung}:{uid}@sales-post",
        "von": von, "an": _rein(postfach._kopf(nachricht, "To"), KOPF_MAX),
        "betreff": betreff, "datum": _datum(postfach._kopf(nachricht, "Date")),
        "text": text, "auszug": auszug, "anhaenge": _anhaenge(nachricht),
    }


def _unlesbar(kennung: str, uid: int, fehlertyp: str) -> dict:
    """Platzhalter fuer eine Mail, die sich nicht zerlegen liess: sie geht
    nicht verloren (Spec: keine Mail verschwindet), steht aber als fehler da."""
    return {"message_id": f"{kennung}:{uid}@sales-post", "von": None, "an": None,
            "betreff": None, "datum": None, "text": None, "auszug": None, "anhaenge": [],
            "fehler": f"Mail nicht lesbar ({fehlertyp})"}


def _uidvalidity(kasten) -> int | None:
    try:
        _typ, daten = kasten.response("UIDVALIDITY")
        return int(daten[0]) if daten and daten[0] is not None else None
    except (ValueError, TypeError, IndexError):
        return None


def _uidvalidity_pruefen(zeile: dict, aktuell: int | None) -> int:
    """Liefert die `letzte_uid`, ab der zu holen ist (0 = von vorn)."""
    letzte = int(zeile.get("letzte_uid") or 0)
    gespeichert = zeile.get("uidvalidity")
    if aktuell is None or gespeichert == aktuell:
        return letzte
    with server.pool.connection() as conn, conn.transaction():
        if gespeichert is not None:
            LOG.info("Konto %s: UIDVALIDITY geaendert - hole neu", zeile["kennung"])
            # Alte UIDs gelten nicht mehr: unter alle vorhandenen Platzhalter
            # schieben (eindeutig, auch nach mehreren Wechseln), damit die neuen
            # UIDs frei sind. Die Zeilen selbst bleiben (nie loeschen).
            conn.execute(
                "with basis as (select least(coalesce(min(imap_uid), 0), 0) as b "
                "               from post_mails where konto_id = %s), "
                "alt as (select id, row_number() over (order by imap_uid) as n "
                "        from post_mails where konto_id = %s and imap_uid > 0) "
                "update post_mails p set imap_uid = basis.b - alt.n "
                "from alt, basis where p.id = alt.id", (zeile["id"], zeile["id"]))
        conn.execute(
            "update post_konten set uidvalidity = %s, letzte_uid = null, "
            "altbestand_fertig = false where id = %s", (aktuell, zeile["id"]))
    return 0


def _speichern(zeile: dict, uid: int, mail: dict | None) -> bool:
    """Eine Mail und der neue Stand `letzte_uid` in EINER Transaktion: bricht
    die Runde ab, ist weder eine Mail doppelt noch eine uebersprungen."""
    neu = False
    with server.pool.connection() as conn, conn.transaction():
        if mail is not None:
            vorhanden = conn.execute(
                "select id, konto_id, imap_uid from post_mails where besitzer = %s "
                "and message_id = %s and von is not distinct from %s "
                "and betreff is not distinct from %s "
                "order by (konto_id = %s and imap_uid < 0) desc limit 1",
                (zeile["besitzer"], mail["message_id"], mail["von"], mail["betreff"],
                 zeile["id"])).fetchone()
            if vorhanden is None:
                neu = conn.execute(
                    "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
                    "von, an, betreff, datum, text, auszug, anhaenge, status, fehler, "
                    "bereich, fach) values "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "on conflict (konto_id, imap_uid) do nothing returning id",
                    (zeile["id"], uid, mail["message_id"], zeile["besitzer"], mail["von"],
                     mail["an"], mail["betreff"], mail["datum"], mail["text"],
                     mail["auszug"], mail["anhaenge"],
                     "fehler" if mail.get("fehler") else "neu", mail.get("fehler"),
                     "privat" if mail.get("fehler") else None,
                     post_struktur.UNKLAR if mail.get("fehler") else None)
                ).fetchone() is not None
            elif str(vorhanden["konto_id"]) == str(zeile["id"]) and vorhanden["imap_uid"] < 0:
                # Nach UIDVALIDITY-Wechsel wiedergefunden: neuer Fundort, keine Dublette.
                conn.execute("update post_mails set imap_uid = %s where id = %s",
                             (uid, vorhanden["id"]))
        conn.execute(
            "update post_konten set letzte_uid = greatest(coalesce(letzte_uid, 0), %s) "
            "where id = %s", (uid, zeile["id"]))
    return neu


def konto_abholen(zeile: dict, kasten=None, stapel: int = 50) -> int:
    """Holt hoechstens `stapel` neue Mails eines Kontos; Rueckgabe = neu gespeichert."""
    eigener = kasten is None
    if eigener:
        kasten = post_konten.verbinden(zeile)
        try:
            kasten.sock.settimeout(IMAP_TIMEOUT_S)
        except AttributeError:
            pass
    try:
        kasten.select("INBOX", readonly=True)
        letzte = _uidvalidity_pruefen(zeile, _uidvalidity(kasten))
        status, daten = kasten.uid("search", None, f"UID {letzte + 1}:*")
        if status != "OK":
            raise RuntimeError("IMAP-Suche abgelehnt")
        # "n:*" liefert auf echtem IMAP immer mindestens die hoechste UID, auch
        # wenn sie kleiner als n ist - darum hier nachfiltern.
        offen = sorted(u for u in (int(x) for x in (daten[0] or b"").split()) if u > letzte)
        dieser_stapel = offen[:max(1, int(stapel))]
        neu = 0
        for uid in dieser_stapel:
            if _STOPP.is_set():
                return neu
            nachricht = postfach._holen(kasten, str(uid).encode("ascii"))
            mail = None
            if nachricht is not None:      # None: inzwischen entfernt - weiter
                try:
                    mail = _mail_zerlegen(nachricht, zeile["kennung"], uid)
                except Exception as e:  # noqa: BLE001 - sonst haengt das Konto ewig an dieser UID
                    LOG.warning("Konto %s: Mail %s nicht lesbar (%s)", zeile["kennung"], uid,
                                type(e).__name__)
                    mail = _unlesbar(zeile["kennung"], uid, type(e).__name__)
            neu += 1 if _speichern(zeile, uid, mail) else 0
        if len(dieser_stapel) == len(offen):
            with server.pool.connection() as conn:
                conn.execute("update post_konten set altbestand_fertig = true "
                             "where id = %s and not altbestand_fertig", (zeile["id"],))
        return neu
    finally:
        if eigener:
            try:
                kasten.logout()
            except Exception:  # noqa: BLE001 - Abmelden ist Hoeflichkeit
                pass


# ---------------------------------------------------------------------------
# Einordnen
# ---------------------------------------------------------------------------

def _ergebnis_speichern(mail_id, e: post_einordnung.Einordnung) -> None:
    bereich, fach = e.bereich, e.fach
    if not post_struktur.fach_gueltig(bereich or "", fach or ""):
        # Die feste Liste gilt auch hier: nie ein Fach speichern, das es nicht gibt.
        bereich, fach = (bereich if bereich in post_struktur.BEREICHE else "privat",
                         post_struktur.UNKLAR)
    server._q(
        "update post_mails set bereich = %s, fach = %s, sensibel = %s, "
        "einordnung_quelle = %s, begruendung = %s, eingeordnet_am = now(), "
        "status = 'eingeordnet', fehler = null, "
        "text = case when %s then null else text end, "
        "auszug = case when %s then null else auszug end "
        "where id = %s and status = 'neu'",
        (bereich, fach, e.sensibel, e.quelle, e.begruendung, e.sensibel, e.sensibel,
         mail_id))


def einordnen_offene(grenze: int) -> int:
    """Ordnet bis zu `grenze` offene Mails ein (zuerst gesehen zuerst).
    Rueckgabe = Zahl der Mails, die `neu` verlassen haben (eingeordnet oder fehler)."""
    if grenze <= 0:
        return 0
    offene = server._q(
        "select id, von, betreff, datum, text from post_mails where status = 'neu' "
        "order by gesehen_am, imap_uid limit %s", (int(grenze),))
    erledigt = 0
    for zeile in offene:
        if _STOPP.is_set():
            break
        mail = {"id": str(zeile["id"]), "von": zeile["von"] or "",
                "betreff": zeile["betreff"] or "",
                "datum": zeile["datum"].isoformat() if zeile["datum"] else "",
                "text": zeile["text"] or ""}
        try:
            ergebnis = post_einordnung.einordnen(mail)
        except GatewayTransient:
            LOG.info("Einordnen pausiert: Gateway voruebergehend nicht bereit")
            break
        except GatewayFehler:
            # Endgueltig fuer DIESE Mail. Fester Text: die Gateway-Meldung
            # koennte Teile der Anfrage (also der Mail) spiegeln.
            LOG.warning("Mail %s: Einordnung endgueltig fehlgeschlagen", mail["id"])
            server._q(
                "update post_mails set status = 'fehler', bereich = 'privat', fach = %s, "
                "fehler = 'Einordnung durch das Modell endgueltig fehlgeschlagen', "
                "eingeordnet_am = now() where id = %s and status = 'neu'",
                (post_struktur.UNKLAR, mail["id"]))
            erledigt += 1
            continue
        except Exception as e:  # noqa: BLE001 - Netz-/JSON-Eigenheiten (Task-4-Luecke)
            LOG.warning("Einordnen abgebrochen (%s) - naechste Runde erneut",
                        type(e).__name__)
            break
        _ergebnis_speichern(mail["id"], ergebnis)
        erledigt += 1
    return erledigt


def kunde_aktiv() -> bool:
    """Kundenantwort in den letzten 120 s? Dann hat der Kunde Vorrang am Gateway."""
    return bool(server._q(
        "select exists(select 1 from activities where type = 'kundenantwort' "
        "and created_at > now() - make_interval(secs => %s)) as aktiv",
        (KUNDE_PAUSE_S,))[0]["aktiv"])


def modellaufrufe_heute() -> int:
    return int(server._q(
        "select count(*) as n from post_mails where eingeordnet_am::date = current_date "
        "and einordnung_quelle = 'modell'")[0]["n"])


def eine_runde() -> dict:
    bilanz = {"abgeholt": 0, "konten_fehler": 0, "eingeordnet": 0}
    for zeile in post_konten.aktive_konten():
        if _STOPP.is_set():
            return bilanz
        try:
            bilanz["abgeholt"] += konto_abholen(zeile)
        except Exception as e:  # noqa: BLE001 - ein Konto haelt die anderen nicht auf
            bilanz["konten_fehler"] += 1
            LOG.warning("Konto %s: Abholen fehlgeschlagen (%s)", zeile["kennung"],
                        type(e).__name__)
    if _STOPP.is_set():
        return bilanz
    if kunde_aktiv():
        bilanz["pause"] = "kundenantwort"
        return bilanz
    rest = TAGESGRENZE - modellaufrufe_heute()
    if rest <= 0:
        bilanz["tagesgrenze"] = True
        return bilanz
    bilanz["eingeordnet"] = einordnen_offene(min(rest, EINORDNEN_JE_RUNDE))
    return bilanz


# ---------------------------------------------------------------------------
# Schleife - gleiches Geruest wie sales-auto
# ---------------------------------------------------------------------------

def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen - Ende nach der laufenden Mail.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout, propagate=False - Begruendung in
    dispatch.py (import server konfiguriert den Root-Logger um)."""
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
    if not POST_BESITZER:
        # Ohne Besitzer waere jede Mail niemandem zugeordnet - und privat
        # heisst „nur der Besitzer“ (Spec §6). Lieber gar nicht starten.
        LOG.error("POST_BESITZER fehlt in der Umgebung - es wird nichts abgeholt.")
        return 2
    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests) - dann eben ohne Handler
    try:
        neu = post_konten.env_konten_uebernehmen(POST_BESITZER)
    except Exception as e:  # noqa: BLE001 - nur der Typ; restart bringt uns wieder
        LOG.error("Konten aus der Umgebung nicht uebernommen (%s)", type(e).__name__)
        return 1
    LOG.info("Start: schema=%s intervall=%gs tagesgrenze=%d once=%s env-konten-neu=%d",
             server.SCHEMA, INTERVAL_S, TAGESGRENZE, POST_ONCE, neu)
    while not _STOPP.is_set():
        try:
            bilanz = eine_runde()
            if bilanz.get("abgeholt") or bilanz.get("eingeordnet") or bilanz.get("konten_fehler"):
                LOG.info("Runde: %s", bilanz)
        except Exception as e:  # noqa: BLE001 - Meldung koennte Mailinhalt zitieren
            LOG.error("Runde uebersprungen (%s)", type(e).__name__)
        if POST_ONCE:
            LOG.info("POST_ONCE - eine Runde gelaufen, Ende.")
            break
        _STOPP.wait(INTERVAL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
