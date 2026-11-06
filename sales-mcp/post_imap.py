"""IMAP-Befehle zum Aufraeumen der Postfaecher (Spec 2026-11-06 §11, §14).

Jeder Befehl trifft genau eine UID. Darum nie ein nacktes EXPUNGE: das entfernt
jede als geloescht markierte Mail des Ordners, auch die, die Felix am Handy
markiert hat. Erlaubt sind nur `UID MOVE` und `UID EXPUNGE <uid>` (UIDPLUS).
Kann der Server beides nicht, gilt `NichtUnterstuetzt`, und der Aufrufer laesst
das Postfach ruhen, statt einen Rundumschlag zu riskieren.

Vor jedem Anfassen wird geprueft, dass unter der UID noch eine Mail liegt, und
wenn eine Message-ID bekannt ist, dass es dieselbe ist (Ruling R13). Sonst
`Fehlt`. Fehlertexte nennen nie Betreff, Absender oder Message-ID.

Kein Verbindungsaufbau hier: der Aufrufer gibt den angemeldeten Kasten hinein.
"""
from __future__ import annotations

import email
import re

import postfach


class NichtUnterstuetzt(Exception):
    """Der Server kann den Schritt nicht sicher ausfuehren (fehlt MOVE/UIDPLUS o. ae.)."""


class Fehlt(Exception):
    """Die UID ist im Quellordner nicht (mehr) vorhanden oder zeigt auf eine andere Mail."""


class ImapFehler(Exception):
    """Der Server hat einen einzelnen Befehl abgelehnt (NO/BAD)."""


# Wie post_abholen.KOPF_MAX: so lang wurde die Message-ID gespeichert.
_KOPF_MAX = 1000
# Druckbares ASCII ohne Leerzeichen, Anfuehrungszeichen und Backslash: nur so
# laesst sich die Message-ID ohne Quoting-Fallen in UID SEARCH einsetzen.
_SUCHBAR = re.compile(r'[!#-\[\]-~]+')
_SUCHE_MAX = 10       # mehr Kandidaten bei einer Message-ID ist kein Zufall mehr


def _ok(antwort, was: str):
    status, daten = antwort
    if status != "OK":
        raise ImapFehler(f"{was} abgelehnt")
    return daten


def faehigkeiten_auffrischen(kasten) -> None:
    """CAPABILITY nach der Anmeldung neu lesen. imaplib fragt nur davor, und Gmail
    nennt MOVE und UIDPLUS erst angemeldet. Scheitert die Frage, bleibt der alte Stand."""
    frage = getattr(kasten, "capability", None)
    if frage is None:
        return
    try:
        status, daten = frage()
    except Exception:  # noqa: BLE001 - dann gilt der Stand vor der Anmeldung
        return
    if status == "OK" and daten and daten[-1]:
        roh = daten[-1]
        roh = roh.decode("ascii", "replace") if isinstance(roh, bytes) else str(roh)
        kasten.capabilities = tuple(roh.upper().split())


def _faehig(kasten) -> set[str]:
    return {str(f).upper() for f in (getattr(kasten, "capabilities", None) or ())}


def waehlen(kasten, ordner: str) -> int | None:
    """Ordner schreibend oeffnen; Rueckgabe UIDVALIDITY (None, wenn der Server keine nennt).
    Gibt es den Ordner nicht, kann die Mail dort nicht liegen: `Fehlt`."""
    status, _ = kasten.select(postfach._imap_name(ordner))
    if status != "OK":
        raise Fehlt("Ordner nicht vorhanden")
    _typ, daten = kasten.response("UIDVALIDITY")
    try:
        return int(daten[0]) if daten and daten[0] is not None else None
    except (TypeError, ValueError):
        return None


def message_id(kasten, uid: int) -> str | None:
    """Message-ID der Mail unter `uid` im gewaehlten Ordner, wie post_abholen sie
    speichert (ohne <>). "" = Mail ohne Message-ID, None = keine Mail unter der UID."""
    nummer = int(uid)
    if nummer <= 0:
        return None
    daten = _ok(kasten.uid("FETCH", str(nummer), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"),
                "UID FETCH")
    teile = [t for t in daten or () if isinstance(t, tuple) and len(t) >= 2 and t[1] is not None]
    if len(teile) > 1:
        # Ungefragte FETCH-Antworten anderer Mails aussortieren.
        muster = re.compile(rb"\bUID %d\b" % nummer)
        teile = [t for t in teile if muster.search(t[0] or b"")]
    if len(teile) != 1:
        return None
    kopf = email.message_from_bytes(teile[0][1])
    return postfach._kopf(kopf, "Message-ID").strip().strip("<>").replace("\x00", "")[:_KOPF_MAX]


def pruefen(kasten, uid: int, erwartet: str | None) -> None:
    """Liegt unter `uid` eine Mail und, wenn `erwartet` gesetzt ist, genau diese? Sonst `Fehlt`."""
    gefunden = message_id(kasten, uid)
    if gefunden is None:
        raise Fehlt("UID nicht im Ordner")
    if erwartet is not None and gefunden != erwartet:
        raise Fehlt("unter der UID liegt eine andere Mail")


def suchen(kasten, mid: str) -> int:
    """UID der Mail mit genau dieser Message-ID im gewaehlten Ordner, sonst `Fehlt`.
    HEADER-Suche trifft Teilstuecke, darum wird jeder Kandidat genau verglichen."""
    if not mid or not _SUCHBAR.fullmatch(mid):
        raise Fehlt("Message-ID nicht suchbar")
    daten = _ok(kasten.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"'), "UID SEARCH")
    roh = daten[0] if daten and daten[0] else b""
    kandidaten = [int(x) for x in (roh.split() if isinstance(roh, bytes) else str(roh).split())]
    if len(kandidaten) > _SUCHE_MAX:
        raise Fehlt("Message-ID nicht eindeutig")
    passend = [u for u in kandidaten if message_id(kasten, u) == mid]
    if len(passend) != 1:
        raise Fehlt("Mail nicht (eindeutig) gefunden")
    return passend[0]


def ordner_sicherstellen(kasten, name: str) -> str:
    """Ordner anlegen, falls er fehlt; Rueckgabe der IMAP-Name (zitiert).
    Laesst er sich nicht anlegen, ruht das Postfach (sonst scheiterte jede Mail)."""
    imap = postfach._imap_name(name)
    if name in {n for _, n in postfach._ordner_liste(kasten)}:
        return imap
    status, daten = kasten.create(imap)
    text = b" ".join(d for d in (daten or ()) if isinstance(d, bytes)).upper()
    if status != "OK" and b"ALREADYEXISTS" not in text:
        raise NichtUnterstuetzt(f"Ordner '{name}' laesst sich nicht anlegen")
    return imap


def _neue_uid(kasten, uid: int) -> int | None:
    """Neue UID aus der COPYUID-Antwort (UIDPLUS): "<uidvalidity> <alt> <neu>"."""
    _typ, daten = kasten.response("COPYUID")
    for eintrag in reversed(daten or []):
        if not eintrag:
            continue
        teile = (eintrag.decode("ascii", "replace") if isinstance(eintrag, bytes)
                 else str(eintrag)).split()
        if len(teile) == 3 and teile[1] == str(uid) and teile[2].isdigit():
            return int(teile[2])
    return None


def verschieben(kasten, quelle: str, uid: int, ziel: str,
                message_id: str | None = None) -> int | None:
    """Genau die Mail `uid` aus `quelle` nach `ziel`; Rueckgabe die neue UID (COPYUID)
    oder None. `UID MOVE`, sonst `UID COPY` + `UID STORE` + `UID EXPUNGE <uid>`,
    sonst `NichtUnterstuetzt`. Mit `message_id` muss die UID noch diese Mail sein."""
    faehig = _faehig(kasten)
    if "MOVE" not in faehig and "UIDPLUS" not in faehig:
        raise NichtUnterstuetzt("Server kann weder MOVE noch UIDPLUS")
    waehlen(kasten, quelle)
    pruefen(kasten, uid, message_id)
    nummer, zielname = str(int(uid)), postfach._imap_name(ziel)
    kasten.response("COPYUID")          # Rest eines frueheren Befehls verwerfen
    if "MOVE" in faehig:
        _ok(kasten.uid("MOVE", nummer, zielname), "UID MOVE")
        return _neue_uid(kasten, int(uid))
    _ok(kasten.uid("COPY", nummer, zielname), "UID COPY")
    neu = _neue_uid(kasten, int(uid))
    _ok(kasten.uid("STORE", nummer, "+FLAGS", "(\\Deleted)"), "UID STORE")
    _ok(kasten.uid("EXPUNGE", nummer), "UID EXPUNGE")
    return neu


def _papierkorb(kasten) -> str | None:
    for merkmale, name in postfach._ordner_liste(kasten):
        if "\\TRASH" in merkmale.upper():
            return name
    return None


def _entfernen(kasten, uid: int) -> None:
    nummer = str(int(uid))
    _ok(kasten.uid("STORE", nummer, "+FLAGS", "(\\Deleted)"), "UID STORE")
    _ok(kasten.uid("EXPUNGE", nummer), "UID EXPUNGE")


def loeschen(kasten, quelle: str, uid: int, anbieter: str, message_id: str = "") -> None:
    """Genau die Mail `uid` aus `quelle` endgueltig loeschen. Nur mit Message-ID: vorher
    wird geprueft, dass die UID noch diese Mail ist (R13).

    gmx/namecheap: `UID STORE +FLAGS (\\Deleted)` + `UID EXPUNGE <uid>`.
    gmail: EXPUNGE in einem Label entfernt nur das Label. Darum in den Papierkorb
    (`\\Trash`) verschieben und dort die neue UID markieren und per UID EXPUNGE
    entfernen; ohne neue UID `NichtUnterstuetzt` (Spec §11)."""
    if not message_id:
        raise ValueError("Loeschen nur mit pruefbarer Message-ID")
    if "UIDPLUS" not in _faehig(kasten):
        raise NichtUnterstuetzt("Server kann kein UID EXPUNGE (UIDPLUS fehlt)")
    if anbieter == "gmail":
        papierkorb = _papierkorb(kasten)
        if not papierkorb:
            raise NichtUnterstuetzt("kein Papierkorb (\\Trash) im Postfach")
        neu = verschieben(kasten, quelle, uid, papierkorb, message_id=message_id)
        if neu is None:
            raise NichtUnterstuetzt("Papierkorb nennt keine neue UID")
        waehlen(kasten, papierkorb)
        pruefen(kasten, neu, message_id)
        _entfernen(kasten, neu)
        return
    waehlen(kasten, quelle)
    pruefen(kasten, uid, message_id)
    _entfernen(kasten, uid)
