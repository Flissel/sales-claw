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


def faehigkeiten(kasten) -> set[str]:
    """Faehigkeiten des Kastens, gross geschrieben (nach faehigkeiten_auffrischen)."""
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


# --- Anhaenge per BODYSTRUCTURE -------------------------------------------------
# Fuer Mails, die abgeholt wurden, bevor ein Anhang ohne Dateinamen erkannt wurde: vor dem
# Loeschen fragt post_ordnen nur die Struktur ab (Typen, Disposition), nie den Inhalt.

_TOKEN = re.compile(rb'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)
_LITERAL_ENDE = re.compile(rb"\{\d+\}\s*$")
# Hauptteile, die ein Text-/HTML-Rumpf oder ein Bild sein koennen. Alles andere (application,
# audio, video, message, ...) ist ein Anhang - auch ohne Dateinamen und ohne Disposition.
_RUMPF_TYPEN = ("text", "multipart")


def _rohtext(daten) -> bytes:
    """FETCH-Antwort von imaplib zu einem Text: Literale ({n} + Tupel) werden zu Strings."""
    teile = []
    for teil in daten or ():
        if isinstance(teil, tuple) and len(teil) >= 2:
            kopf = _LITERAL_ENDE.sub(b"", teil[0] or b"")
            wert = (teil[1] or b"").replace(b"\\", b"\\\\").replace(b'"', b'\\"')
            teile.append(kopf + b'"' + wert + b'"')
        elif isinstance(teil, bytes):
            teile.append(teil)
    return b"".join(teile)


def _parsen(roh: bytes) -> list:
    """Klammerausdruecke (RFC 3501) als verschachtelte Listen; NIL = None. Wirft ValueError,
    wenn die Klammern nicht aufgehen."""
    wurzel: list = []
    stapel = [wurzel]
    pos = 0
    while pos < len(roh):
        treffer = _TOKEN.match(roh, pos)
        if treffer is None:
            if roh[pos:].strip():
                raise ValueError("BODYSTRUCTURE nicht lesbar")
            break
        pos = treffer.end()
        auf, zu, zitat, atom = treffer.groups()
        if auf:
            neu: list = []
            stapel[-1].append(neu)
            stapel.append(neu)
        elif zu:
            if len(stapel) == 1:
                raise ValueError("BODYSTRUCTURE nicht lesbar")
            stapel.pop()
        elif zitat is not None:
            stapel[-1].append(re.sub(rb"\\(.)", rb"\1", zitat).decode("utf-8", "replace"))
        else:
            wert = atom.decode("ascii", "replace")
            stapel[-1].append(None if wert.upper() == "NIL" else wert)
    if len(stapel) != 1:
        raise ValueError("BODYSTRUCTURE nicht lesbar")
    return wurzel


def _anhang_in(teil) -> bool:
    """Enthaelt dieser Teil der BODYSTRUCTURE einen Anhang, der kein Bild ist?"""
    if not isinstance(teil, list) or not teil:
        raise ValueError("BODYSTRUCTURE nicht lesbar")
    if isinstance(teil[0], list):
        # multipart: erst die Unterteile, dann der Untertyp und die Erweiterungsdaten.
        kinder = []
        for k in teil:
            if not isinstance(k, list):
                break
            kinder.append(k)
        return any(_anhang_in(k) for k in kinder)
    haupt = str(teil[0] or "").lower()
    if haupt == "image":
        return False                       # Bilder sind erlaubt, auch als attachment
    if haupt not in _RUMPF_TYPEN:
        return True
    # text/*: nur mit Disposition attachment oder mit Datei-/Teilnamen ein Anhang.
    for feld in teil[2:]:
        if (isinstance(feld, list) and feld and isinstance(feld[0], str)
                and feld[0].lower() == "attachment"):
            return True
    parameter = teil[2] if len(teil) > 2 and isinstance(teil[2], list) else []
    return any(isinstance(p, str) and p.lower() == "name" for p in parameter[0::2])


def anhang_ausser_bildern(kasten, uid: int) -> bool:
    """Hat die Mail `uid` im gewaehlten Ordner einen Anhang, der kein Bild ist? Fragt nur
    `UID FETCH <uid> (BODYSTRUCTURE)` ab, keinen Inhalt. Keine Mail unter der UID: `Fehlt`;
    unlesbare Antwort: `ImapFehler` (der Aufrufer loescht dann nicht)."""
    nummer = int(uid)
    if nummer <= 0:
        raise Fehlt("UID nicht im Ordner")
    daten = _ok(kasten.uid("FETCH", str(nummer), "(BODYSTRUCTURE)"), "UID FETCH")
    if not any(isinstance(t, (bytes, tuple)) for t in daten or ()):
        raise Fehlt("UID nicht im Ordner")
    try:
        antworten = _parsen(_rohtext(daten))
        # Je Antwort: Nummer, dann (UID n BODYSTRUCTURE (...)). Ungefragte Antworten anderer
        # Mails zaehlen nicht.
        for feld in antworten:
            if not isinstance(feld, list):
                continue
            werte = {str(feld[j]).upper(): feld[j + 1] for j in range(0, len(feld) - 1, 2)
                     if isinstance(feld[j], str)}
            if werte.get("UID") == str(nummer) and "BODYSTRUCTURE" in werte:
                return _anhang_in(werte["BODYSTRUCTURE"])
    except ValueError:
        raise ImapFehler("BODYSTRUCTURE nicht lesbar") from None
    raise Fehlt("UID nicht im Ordner")


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
    faehig = faehigkeiten(kasten)
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
    if "UIDPLUS" not in faehigkeiten(kasten):
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
