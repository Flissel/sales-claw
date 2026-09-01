"""Betreiber-Postfach LESEN (IMAP) — nie veraendern (31.08.2026).

Jede Verbindung oeffnet den Ordner READONLY: kein \\Seen-Flag, kein
Loeschen, kein Verschieben. Das ist die Bedingung, unter der der
Assistent ueberhaupt ins Postfach schauen darf — ein Lesefehler kann
nie eine Mail kosten.

Konfiguration: IMAP_HOST/IMAP_PORT/IMAP_USER/IMAP_PASSWORT, mit
Rueckfall auf die SMTP-Werte — bei Namecheap Private Email (dem Konto
des Betreibers) sind Host und Zugangsdaten fuer beide Wege identisch,
nur der Port unterscheidet sich (993 statt 465).

Alles, was aus einer Mail kommt, ist FREMDDATUM: Header werden
dekodiert und gedeckelt, HTML wird zu Text gestrippt, und nichts davon
ist je eine Anweisung (AGENTS.md, Abschnitt Betreiber-Postfach).
Vertragstests: tests/test_postfach.py (Stub); die Live-Verbindung misst
der Rollout.
"""
import email
import email.header
import imaplib
import os
import re
import ssl

IMAP_HOST = os.environ.get(
    "IMAP_HOST", os.environ.get("SMTP_HOST", "")).strip()
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ.get(
    "IMAP_USER", os.environ.get("SMTP_USER", "")).strip()
IMAP_PASSWORT = os.environ.get(
    "IMAP_PASSWORT", os.environ.get("SMTP_PASSWORT", ""))

AUSZUG_MAX = 300      # Zeichen je Mail in der Liste
TEXT_MAX = 20000      # Zeichen Volltext — Fremddatum bleibt gedeckelt
ANZAHL_MAX = 25       # Mails je Liste


def konfiguriert() -> bool:
    return bool(IMAP_HOST and IMAP_USER)


def _verbinden():
    kasten = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT,
                               ssl_context=ssl.create_default_context())
    kasten.login(IMAP_USER, IMAP_PASSWORT)
    return kasten


def _kopf(nachricht, name: str) -> str:
    roh = nachricht.get(name, "")
    teile = []
    for wert, zeichensatz in email.header.decode_header(roh):
        if isinstance(wert, bytes):
            teile.append(wert.decode(zeichensatz or "utf-8",
                                     errors="replace"))
        else:
            teile.append(wert)
    return "".join(teile).strip()


def _html_zu_text(html: str) -> str:
    # Script/Style samt Inhalt weg, dann alle Tags — grob, aber ehrlich:
    # das ist eine Lesehilfe, kein Browser.
    ohne = re.sub(r"<(script|style)\b.*?</\1>", " ", html,
                  flags=re.S | re.I)
    ohne = re.sub(r"<[^>]+>", " ", ohne)
    return " ".join(ohne.split())


def _text(nachricht) -> str:
    """text/plain bevorzugt; sonst text/html gestrippt; sonst leer."""
    kandidaten = (nachricht.walk()
                  if nachricht.is_multipart() else [nachricht])
    html = None
    for teil in kandidaten:
        typ = teil.get_content_type()
        if typ not in ("text/plain", "text/html"):
            continue
        roh = teil.get_payload(decode=True)
        if roh is None:
            continue
        zeichensatz = teil.get_content_charset() or "utf-8"
        wert = roh.decode(zeichensatz, errors="replace")
        if typ == "text/plain":
            return wert.strip()
        if html is None:
            html = wert
    return _html_zu_text(html) if html else ""


def _holen(kasten, uid: bytes):
    status, daten = kasten.uid("fetch", uid, "(RFC822)")
    if status != "OK":
        return None
    for teil in daten:
        if isinstance(teil, tuple) and len(teil) >= 2 and teil[1]:
            return email.message_from_bytes(teil[1])
    return None


def liste(anzahl: int = 10) -> list:
    """Die neuesten Mails der INBOX, neueste zuerst — uid, von, betreff,
    datum, auszug. Wirft bei Verbindungsproblemen (der Aufrufer in
    server.py macht daraus die lesbare Meldung)."""
    anzahl = max(1, min(int(anzahl), ANZAHL_MAX))
    kasten = _verbinden()
    try:
        kasten.select("INBOX", readonly=True)
        status, daten = kasten.uid("search", None, "ALL")
        if status != "OK":
            return []
        uids = (daten[0] or b"").split()
        ergebnis = []
        for uid in reversed(uids[-anzahl:]):
            nachricht = _holen(kasten, uid)
            if nachricht is None:
                continue
            text = " ".join(_text(nachricht).split())
            ergebnis.append({
                "uid": uid.decode("ascii", errors="replace"),
                "von": _kopf(nachricht, "From"),
                "betreff": _kopf(nachricht, "Subject"),
                "datum": _kopf(nachricht, "Date"),
                "auszug": (text[:AUSZUG_MAX] + "…"
                           if len(text) > AUSZUG_MAX else text),
            })
        return ergebnis
    finally:
        kasten.logout()


def lesen(uid: str):
    """Eine Mail im Volltext (gedeckelt) — oder None, wenn es sie nicht
    gibt."""
    kasten = _verbinden()
    try:
        kasten.select("INBOX", readonly=True)
        nachricht = _holen(kasten, str(uid).encode("ascii",
                                                   errors="replace"))
        if nachricht is None:
            return None
        text = _text(nachricht)
        if len(text) > TEXT_MAX:
            text = text[:TEXT_MAX] + "…"
        return {"uid": str(uid), "von": _kopf(nachricht, "From"),
                "an": _kopf(nachricht, "To"),
                "betreff": _kopf(nachricht, "Subject"),
                "datum": _kopf(nachricht, "Date"), "text": text}
    finally:
        kasten.logout()
