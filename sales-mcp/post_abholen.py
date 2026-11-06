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

AUFRAEUMEN (Spec 2026-11-06). Nach dem Einordnen pflegt die Runde das Ziel je
Mail (post_ziel.ziele_aktualisieren, immer) und gleicht mit POST_ORDNEN != aus
das Postfach daran an (post_ordnen). Das Abholen oben bleibt dabei lesend.

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
import socket
import sys
import threading

import post_einordnung
import post_konten
import post_ordnen
import post_struktur
import post_werbung
import post_ziel
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
# Ein Fehler ausserhalb des Gateways (kaputte Mail, Netz-Eigenheit) darf die
# aelteste offene Mail nicht ewig vorne halten: nach so vielen Versuchen wird
# sie `fehler` und die Runde geht weiter (Ruling R8).
VERSUCHE_MAX = 3
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
        sensibel_treffer = True
    else:
        sensibel_treffer = False
    return {
        "message_id": message_id or _ersatz_id(kennung, uid),
        # M3: Platzhalter merken - er beweist bei Antworten keine Identitaet und
        # ist nach einem UIDVALIDITY-Wechsel kein Wiedererkennungsmerkmal.
        "message_id_ersatz": not message_id,
        # I1: nur das Vorhandensein; ausgewertet wird die Antwort erst, wenn der
        # Bot die Mail oeffnet (postfach_mail_lesen) - wie frueher postfach.lesen.
        "kalenderteil": _kalender_sicher(nachricht),
        "von": von,
        # Sensibel: weder Empfaenger noch Anhaenge speichern (Spec §5).
        "an": None if sensibel_treffer else _rein(postfach._kopf(nachricht, "To"), KOPF_MAX),
        "betreff": betreff, "datum": _datum(postfach._kopf(nachricht, "Date")),
        "text": text, "auszug": auszug, "anhaenge": [] if sensibel_treffer else _anhaenge(nachricht),
    }


def _ersatz_id(kennung: str, uid: int) -> str:
    return f"{kennung}:{uid}@sales-post"


def _kalender_sicher(nachricht) -> bool:
    try:
        return bool(postfach._kalender_teil(nachricht))
    except (LookupError, UnicodeError):
        # Unbekannter Zeichensatz im Kalenderteil: vorhanden ist er trotzdem.
        return True


# Anfang der `fehler`-Meldung einer Mail, die schon beim Abholen kaputt war. Die
# Neu-Sortierung (post_neu_einordnen) erkennt solche Zeilen daran und laesst sie
# stehen - sonst verdeckte eine Einordnung den Abholfehler.
ABHOLFEHLER = "Mail nicht lesbar"


def _unlesbar(kennung: str, uid: int, fehlertyp: str) -> dict:
    """Platzhalter fuer eine Mail, die sich nicht zerlegen liess: sie geht
    nicht verloren (Spec: keine Mail verschwindet), steht aber als fehler da."""
    return {"message_id": _ersatz_id(kennung, uid), "message_id_ersatz": True,
            "kalenderteil": False, "von": None, "an": None,
            "betreff": None, "datum": None, "text": None, "auszug": None, "anhaenge": [],
            "fehler": f"{ABHOLFEHLER} ({fehlertyp})"}


def _holen(kasten, uid: int):
    """Wie postfach._holen, aber streng: ein abgelehnter Abruf (NO/BAD) wirft.
    postfach._holen liefert dann None - hier hiesse das „Mail entfernt“, und
    letzte_uid liefe still an einer Mail vorbei, die es noch gibt. So scheitert
    das Konto in dieser Runde und holt dieselbe UID in der naechsten erneut."""
    status, daten = kasten.uid("fetch", str(uid).encode("ascii"), "(RFC822)")
    if status != "OK":
        raise RuntimeError("IMAP-Abruf abgelehnt")
    for teil in daten or ():
        if isinstance(teil, tuple) and len(teil) >= 2 and teil[1]:
            return email.message_from_bytes(teil[1])
    return None              # OK ohne Daten: die Mail gibt es nicht mehr


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


def _ersatz_wiederfinden(conn, zeile: dict, mail: dict):
    """M3: eine Mail OHNE Message-ID nach einem UIDVALIDITY-Wechsel
    wiedererkennen. Der Platzhalter enthaelt die alte UID und taugt dafuer
    nicht; stattdessen gleiches Konto + Absender + Betreff + Datum unter den
    alten Zeilen (negative UID). Nicht lesbare Mails (alles NULL) werden nie
    zusammengelegt - zwei kaputte Mails waeren sonst eine."""
    if mail.get("fehler") or not (mail.get("von") or mail.get("betreff") or mail.get("datum")):
        return None
    return conn.execute(
        "select id, konto_id, imap_uid from post_mails where konto_id = %s "
        "and message_id_ersatz and imap_uid < 0 "
        "and von is not distinct from %s and betreff is not distinct from %s "
        "and datum is not distinct from %s order by imap_uid desc limit 1",
        (zeile["id"], mail["von"], mail["betreff"], mail["datum"])).fetchone()


def _speichern(zeile: dict, uid: int, mail: dict | None) -> bool:
    """Eine Mail und der neue Stand `letzte_uid` in EINER Transaktion: bricht
    die Runde ab, ist weder eine Mail doppelt noch eine uebersprungen."""
    neu = False
    with server.pool.connection() as conn, conn.transaction():
        if mail is not None:
            ersatz = bool(mail.get("message_id_ersatz"))
            if ersatz:
                vorhanden = _ersatz_wiederfinden(conn, zeile, mail)
            else:
                vorhanden = conn.execute(
                    "select id, konto_id, imap_uid from post_mails where besitzer = %s "
                    "and message_id = %s and not message_id_ersatz "
                    "and von is not distinct from %s "
                    "and betreff is not distinct from %s "
                    "order by (konto_id = %s and imap_uid < 0) desc limit 1",
                    (zeile["besitzer"], mail["message_id"], mail["von"], mail["betreff"],
                     zeile["id"])).fetchone()
            if vorhanden is None:
                neu = conn.execute(
                    "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
                    "von, an, betreff, datum, text, auszug, anhaenge, status, fehler, "
                    "bereich, fach, message_id_ersatz, kalenderteil) values "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "on conflict (konto_id, imap_uid) do nothing returning id",
                    (zeile["id"], uid, mail["message_id"], zeile["besitzer"], mail["von"],
                     mail["an"], mail["betreff"], mail["datum"], mail["text"],
                     mail["auszug"], mail["anhaenge"],
                     "fehler" if mail.get("fehler") else "neu", mail.get("fehler"),
                     "privat" if mail.get("fehler") else None,
                     post_struktur.UNKLAR if mail.get("fehler") else None,
                     ersatz, bool(mail.get("kalenderteil")))
                ).fetchone() is not None
            elif str(vorhanden["konto_id"]) == str(zeile["id"]) and vorhanden["imap_uid"] < 0:
                # Nach UIDVALIDITY-Wechsel wiedergefunden: neuer Fundort, keine
                # Dublette. Ein Platzhalter traegt die UID im Namen - er zieht mit.
                conn.execute(
                    "update post_mails set imap_uid = %s, message_id = case when "
                    "message_id_ersatz then %s else message_id end where id = %s",
                    (uid, mail["message_id"], vorhanden["id"]))
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
            nachricht = _holen(kasten, uid)
            mail = None
            if nachricht is None:
                LOG.info("Konto %s: UID %s ohne Inhalt (entfernt) - uebersprungen",
                         zeile["kennung"], uid)
            else:
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

# Kosten eines Fehlversuchs (Sortierer/Pruefer haben gekostet, die Mail bleibt `neu`):
# am selben Tag aufaddieren, an einem neuen Tag neu beginnen - so zaehlt jeder Aufruf
# genau einmal, an dem Tag, an dem er anfiel (gleiches Muster wie post_neu_einordnen._KOSTEN_SQL).
_FEHL_KOSTEN_SQL = ("fehl_aufrufe = %s + case when fehl_am::date = current_date "
                    "then fehl_aufrufe else 0 end, fehl_am = now()")

def _ergebnis_speichern(mail_id, e: post_einordnung.Einordnung) -> None:
    bereich, fach = e.bereich, e.fach
    unterfach = e.unterfach
    aufmerksamkeit = e.aufmerksamkeit
    if not post_struktur.fach_gueltig(bereich or "", fach or ""):
        # Die feste Liste gilt auch hier: nie ein Fach speichern, das es nicht gibt.
        fach, unterfach = post_struktur.UNKLAR, None
    if fach == post_struktur.UNKLAR:
        # Spec §6: Zum Nachsehen liegt IMMER privat - hier zentral, egal welcher
        # Weg (Modell, Regel, Fallback oben) die Einordnung geliefert hat.
        bereich, unterfach = "privat", None
        # Zum Nachsehen bleibt im Posteingang (Spec §5), egal was die Stufe davor meldete.
        aufmerksamkeit = True
    server._q(
        "update post_mails set bereich = %s, fach = %s, unterfach = %s, sensibel = %s, "
        "einordnung_quelle = %s, begruendung = %s, vorschlaege = %s::jsonb, "
        "aufmerksamkeit = %s, werbung_sicher = %s, "
        # `=`, nicht `+`: Fehlversuch-Kosten stehen auf fehl_aufrufe (Tag ihres Anfalls),
        # modellaufrufe traegt nur die endgueltige Einordnung - sonst zaehlte sie doppelt.
        "modellaufrufe = %s, einordnung_version = 3, eingeordnet_am = now(), "
        "status = 'eingeordnet', fehler = null, "
        "text = case when %s then null else text end, "
        "auszug = case when %s then null else auszug end, "
        "an = case when %s then null else an end, "
        "anhaenge = case when %s then '{}'::text[] else anhaenge end "
        "where id = %s and status = 'neu'",
        (bereich, fach, unterfach, e.sensibel, e.quelle, e.begruendung,
         None if e.vorschlaege is None else server._json(e.vorschlaege),
         aufmerksamkeit, e.werbung_sicher, e.aufrufe,
         e.sensibel, e.sensibel, e.sensibel, e.sensibel, mail_id))
    if e.werbung_sicher:
        _werbe_regel_vorschlagen(mail_id)


def _werbe_regel_vorschlagen(mail_id) -> None:
    """Hat der Absender jetzt genug sichere Werbemails, legt post_werbung eine Regel an
    (kuenftig ohne Modell). Ein Fehler hier darf die gespeicherte Einordnung nicht kippen."""
    try:
        zeile = server._q("select besitzer, von from post_mails where id = %s", (mail_id,))
        if zeile and post_werbung.regel_vorschlagen(zeile[0]["besitzer"], zeile[0]["von"] or ""):
            LOG.info("Werbe-Regel fuer einen Absender angelegt")
    except Exception as e:      # noqa: BLE001 - nur der Typ: Meldungen koennten Mailinhalt tragen
        LOG.warning("Werbe-Regel-Vorschlag fehlgeschlagen (%s)", type(e).__name__)


def _pruefer_vorschlag_speichern(mail_id, vorschlag: post_einordnung.Einordnung) -> None:
    """Pruefer dreimal ausgefallen: Die Mail geht nicht ungeprueft ins Fach des
    Sortierers, sondern privat zum Nachsehen - sein Vorschlag liegt daneben."""
    sortierer = {"bereich": vorschlag.bereich, "fach": vorschlag.fach,
                 "unterfach": vorschlag.unterfach}
    if not vorschlag.sensibel:      # Freitext sensibler Mails wird nie gespeichert (Spec §5)
        sortierer["begruendung"] = vorschlag.begruendung
    _ergebnis_speichern(mail_id, post_einordnung.Einordnung(
        "privat", post_struktur.UNKLAR, vorschlag.sensibel, "modell",
        "pruefer:ausgefallen", None, aufrufe=0,   # Kosten stehen schon auf der Zeile
         vorschlaege={"sortierer": sortierer}))


def einordnen_offene(grenze: int) -> int:
    """Ordnet bis zu `grenze` offene Mails ein (zuerst gesehen zuerst).
    Rueckgabe = Zahl der Mails, die `neu` verlassen haben (eingeordnet oder fehler)."""
    if grenze <= 0:
        return 0
    # Das Konto bestimmt den Standardbereich (Spec v2 §5.1); ohne Konto-Zeile
    # (sollte es nicht geben) gilt der Standard von post_einordnung.
    offene = server._q(
        "select m.id, m.besitzer, m.von, m.betreff, m.datum, m.text, "
        "k.kennung, k.standard_bereich from post_mails m "
        "left join post_konten k on k.id = m.konto_id where m.status = 'neu' "
        "order by m.gesehen_am, m.imap_uid limit %s", (int(grenze),))
    erledigt = 0
    for zeile in offene:
        if _STOPP.is_set():
            break
        # besitzer nur fuer die Regelauswahl (R13); an das Modell geht er nicht
        # (post_einordnung._auftrag nimmt nur Absender, Betreff, Datum, Text).
        mail = {"id": str(zeile["id"]), "besitzer": zeile["besitzer"],
                "von": zeile["von"] or "",
                "betreff": zeile["betreff"] or "",
                "datum": zeile["datum"].isoformat() if zeile["datum"] else "",
                "text": zeile["text"] or ""}
        konto = {"kennung": zeile["kennung"], "standard_bereich": zeile["standard_bereich"]}
        try:
            ergebnis = post_einordnung.einordnen(mail, konto)
        except post_einordnung.PrueferVoruebergehend as e:
            # Muss vor GatewayTransient stehen (Unterklasse). Der Sortierer hat schon
            # gekostet: auf den Tag des Anfalls buchen (fehl_am macht es fuer die
            # Tagesgrenze sichtbar), aber keinen Versuch zaehlen - der Pruefer, nicht
            # die Mail ist schuld.
            server._q(
                f"update post_mails set {_FEHL_KOSTEN_SQL} "
                "where id = %s and status = 'neu'", (int(e.aufrufe), mail["id"]))
            LOG.info("Einordnen pausiert: Pruefer voruebergehend nicht bereit")
            break
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
                # Der Aufruf hat das Modell erreicht: zaehlt zur Tagesgrenze.
                "einordnung_quelle = 'modell', modellaufrufe = 1, einordnung_version = 2, "
                "aufmerksamkeit = true, eingeordnet_am = now() where id = %s and status = 'neu'",
                (post_struktur.UNKLAR, mail["id"]))
            erledigt += 1
            continue
        except post_einordnung.PrueferFehlgeschlagen as e:
            # Sortierer-Aufrufe (e.vorschlag.aufrufe) plus der gescheiterte Pruefer
            # haben gekostet. fehl_aufrufe/fehl_am machen sie am Tag ihres Anfalls fuer
            # die Tagesgrenze sichtbar, auch solange die Mail `neu` ist.
            zeilen = server._q(
                f"update post_mails set versuche = versuche + 1, {_FEHL_KOSTEN_SQL} "
                "where id = %s returning versuche", (e.vorschlag.aufrufe + 1, mail["id"]))
            if zeilen and zeilen[0]["versuche"] >= VERSUCHE_MAX:
                LOG.warning("Mail %s: Pruefer nach %d Versuchen ausgefallen - Zum Nachsehen",
                            mail["id"], VERSUCHE_MAX)
                _pruefer_vorschlag_speichern(mail["id"], e.vorschlag)
                erledigt += 1
            else:
                LOG.warning("Mail %s: Pruefer ausgefallen - bleibt neu", mail["id"])
            continue          # die naechste Mail ist vom Pruefer-Ausfall nicht betroffen
        except Exception as e:  # noqa: BLE001 - Netz-/JSON-Eigenheiten (Task-4-Luecke)
            versuche = server._q(
                "update post_mails set versuche = versuche + 1 where id = %s "
                "returning versuche", (mail["id"],))
            if versuche and versuche[0]["versuche"] >= VERSUCHE_MAX:
                LOG.warning("Mail %s: Einordnung nach %d Versuchen aufgegeben (%s)",
                            mail["id"], VERSUCHE_MAX, type(e).__name__)
                server._q(
                    "update post_mails set status = 'fehler', bereich = 'privat', fach = %s, "
                    "fehler = 'Einordnung wiederholt fehlgeschlagen', aufmerksamkeit = true, "
                    "eingeordnet_am = now() "
                    "where id = %s and status = 'neu'", (post_struktur.UNKLAR, mail["id"]))
                erledigt += 1
                continue
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
    # Jeder Modellaufruf zaehlt genau einmal, an dem Tag, an dem er anfiel:
    # - modellaufrufe: Kosten der endgueltigen Einordnung (feste Regeln und menschliche
    #   Korrekturen: 0) am Tag eingeordnet_am,
    # - fehl_aufrufe: Kosten der Fehlversuche (Pruefer ausgefallen) am Tag fehl_am - so
    #   entgeht auch eine noch `neue` Mail mit toten Versuchen der Grenze nicht und
    #   zaehlt nicht an Folgetagen erneut,
    # - vorschau_aufrufe am Tag vorschau_am (ueberlebt anwenden).
    zeile = server._q(
        "select (select coalesce(sum(modellaufrufe), 0) from post_mails "
        "         where eingeordnet_am::date = current_date) "
        "     + (select coalesce(sum(fehl_aufrufe), 0) from post_mails "
        "         where fehl_am::date = current_date) "
        "     + (select coalesce(sum(vorschau_aufrufe), 0) from post_mails "
        "         where vorschau_am::date = current_date) as n")[0]
    return int(zeile["n"])


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
    _einordnen(bilanz)
    if not _STOPP.is_set():
        _aufraeumen(bilanz)
    return bilanz


def _einordnen(bilanz: dict) -> None:
    if kunde_aktiv():
        bilanz["pause"] = "kundenantwort"
        return
    rest = TAGESGRENZE - modellaufrufe_heute()
    # Eine Mail kostet bis zu 2 Aufrufe (Sortierer + Pruefer), `rest` zaehlt Aufrufe.
    mails = min(rest // 2, EINORDNEN_JE_RUNDE)
    if mails <= 0:
        bilanz["tagesgrenze"] = True
        return
    bilanz["eingeordnet"] = einordnen_offene(mails)


def _aufraeumen(bilanz: dict) -> None:
    """Nach dem Einordnen: Ziel je Mail pflegen (immer, R1), dann das Postfach angleichen
    (nur mit POST_ORDNEN != aus). Beides ruft kein Modell, laeuft also auch in der
    Kundenpause und nach der Tagesgrenze. Ein Fehler in einem Schritt kostet die Runde
    nicht; im Protokoll nur der Typ (Datenbank-Meldungen zitieren Zeilen)."""
    try:
        bilanz["ziele"] = post_ziel.ziele_aktualisieren()
    except Exception as e:  # noqa: BLE001
        LOG.warning("Ziele nicht aktualisiert (%s)", type(e).__name__)
    if post_ordnen.MODUS == "aus":
        return
    try:
        bilanz["ordnen"] = post_ordnen.ordnen()
    except Exception as e:  # noqa: BLE001
        LOG.warning("Ordnen fehlgeschlagen (%s)", type(e).__name__)


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
    # imaplib.IMAP4_SSL (postfach._imap_oeffnen) verbindet und meldet sich ohne
    # Zeitgrenze an: ein haengender Anbieter hielte den Dienst fuer immer fest.
    # Die Vorgabe gilt fuer jeden danach geoeffneten Python-Socket; psycopg
    # (libpq) bleibt unberuehrt, das Gateway setzt seine Zeitgrenze selbst.
    socket.setdefaulttimeout(IMAP_TIMEOUT_S)
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
            if (bilanz.get("abgeholt") or bilanz.get("eingeordnet") or bilanz.get("konten_fehler")
                    or bilanz.get("ziele")):
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
