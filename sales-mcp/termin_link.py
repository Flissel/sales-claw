"""Erkennt den Konferenz-Link eines Termins (Meeting-Mittelpunkt).

Reines Modul: keine Datenbank, kein Serverimport, keine Anfrage. Die
Termin-Akte reicht Konferenzfeld, Ort und Beschreibung in dieser
Reihenfolge herein; der erste Treffer gewinnt.

Hosts werden NACH dem Parsen verglichen (Host gleich Domain oder
Subdomain davon), nie als Teilstring — `evilzoom.us` und
`zoom.us.evil.com` sind keine Zoom-Links.

Link, Passcode und Einwahl duerfen in kein Log: dieses Modul loggt nichts.
"""
from __future__ import annotations

import os
import re
import urllib.parse

import konferenz

# (Plattform, Muster auf den Host in Kleinbuchstaben). Jitsi steht nicht
# hier, weil seine Hosts aus der Umgebung kommen (`jitsi_hosts`).
MUSTER: tuple[tuple[str, re.Pattern], ...] = (
    ("google_meet", re.compile(r"^meet\.google\.com$")),
    ("teams", re.compile(r"^(teams\.microsoft\.com|teams\.live\.com)$")),
    ("zoom", re.compile(r"^([a-z0-9-]+\.)*(zoom\.us|zoomgov\.com)$")),
    # Bekannte Videodienste ohne Bot-Unterstuetzung
    ("sonstige", re.compile(
        r"^([a-z0-9-]+\.)*(webex\.com|gotomeeting\.com)$|^meet\.goto\.com$")),
)

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_URL_ENDE = ">)].,;:!?\"'"
_PASSCODE = re.compile(
    r"(?:Kenncode|Passcode|Zugangscode|Meeting-Kennwort|Kennwort|Passwort"
    r"|Password)\s*:\s*([^\s,;]+)", re.IGNORECASE)
_EINWAHL = re.compile(
    r"(?:Telefon|Einwahl|Dial[- ]?in|Phone|Tel\.?)\s*:\s*(\+?\d[^\r\n]*)",
    re.IGNORECASE)


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def jitsi_hosts() -> set[str]:
    """Bekannte Jitsi-Hosts zur AUFRUFZEIT: `JITSI_HOSTS` (Komma-Liste),
    dazu immer meet.jit.si und der Host der eigenen Basis."""
    hosts = {"meet.jit.si"}
    basis = _host(konferenz.jitsi_basis())
    if basis:
        hosts.add(basis)
    for eintrag in os.environ.get("JITSI_HOSTS", "").split(","):
        eintrag = eintrag.strip().lower()
        if eintrag:
            hosts.add(eintrag)
    return hosts


def _plattform(host: str, jitsi: set[str]) -> str:
    if not host:
        return ""
    if any(host == h or host.endswith("." + h) for h in jitsi):
        return "jitsi"
    for name, muster in MUSTER:
        if muster.match(host):
            return name
    return ""


def _passcode(link: str, texte: tuple) -> str:
    try:
        pwd = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("pwd")
    except ValueError:
        pwd = None
    if pwd and pwd[0]:
        return pwd[0]
    for text in texte:
        treffer = _PASSCODE.search(text or "")
        if treffer:
            return treffer.group(1)
    return ""


def _einwahl(texte: tuple) -> str:
    for text in texte:
        treffer = _EINWAHL.search(text or "")
        if treffer:
            return treffer.group(1).strip()
    return ""


def erkennen(*texte: str | None) -> dict | None:
    """Erster bekannter Konferenz-Link in der Reihenfolge der Texte.

    Rueckgabe `{"link", "plattform", "passcode", "einwahl"}` oder `None`.
    Ein beliebiger Link ohne bekannte Plattform ergibt `None`.
    """
    jitsi = jitsi_hosts()
    for text in texte:
        for roh in _URL.findall(text or ""):
            link = roh.rstrip(_URL_ENDE)
            plattform = _plattform(_host(link), jitsi)
            if plattform:
                return {
                    "link": link,
                    "plattform": plattform,
                    "passcode": _passcode(link, texte),
                    "einwahl": _einwahl(texte),
                }
    return None
