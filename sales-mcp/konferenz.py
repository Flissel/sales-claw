"""Konferenz-Raeume: der Link fuer einen Termin, zwei Anbieter, eine Stelle.

Ein eigenes Modul aus demselben Grund wie `kalender.py` und `recherche.py`:
hier steht Namensbau und HTTP — keine Datenbank, kein Werkzeug, kein
Rueckimport auf `server.py`. Damit ist der Raumname ohne Netz testbar, und
der einzige neue ausgehende Pfad dieser Stufe (Google Meet) liegt an EINER
Stelle, an der man ihn ansehen kann.

DIE ARBEITSTEILUNG, die der Betreiber am 03.09.2026 vorgegeben hat
-------------------------------------------------------------------
Google liefert AUSSCHLIESSLICH den Raum. Einladung, Kalendereintrag und
Absenderadresse bleiben bei uns: die Mail geht ueber `mail_dispatch` von
der eigenen Domain, der Termin ueber `kalender.eintragen` in den eigenen
CalDAV-Kalender. Es entsteht KEIN Eintrag in einem Google-Kalender, und
Google sieht keine Teilnehmerliste. Deshalb `spaces.create` (ein nackter
Raum) und nicht der Kalender-Weg mit `conferenceData`, der ein Ereignis
samt Gaesten bei Google anlegen wuerde.

ZWEI ANBIETER
-------------
* `jitsi` (Vorgabe): der Link IST der Raumname. Kein Konto, kein Token,
  keine Anfrage — die Adresse entsteht hier im Prozess. Funktioniert
  sofort und ohne Konfiguration.
* `google`: POST an die Meet-API mit einem kurzlebigen Zugriffstoken, das
  aus dem Auffrischungstoken geholt wird. Nur aktiv, wenn alle drei Werte
  gesetzt sind — sonst faellt das Modul auf `jitsi` zurueck und sagt es im
  Hinweis. Kein Fehler, keine Ueberraschung; dieselbe Bauart wie der
  CalDAV-Weg in `kalender.py`.

WARUM DER JITSI-RAUMNAME SO LANG IST
------------------------------------
Beim oeffentlichen Jitsi darf jeder einen Raum betreten, dessen Namen er
kennt. Ein kurzer oder sprechender Name ist damit ein fremder Zuhoerer im
Kundengespraech. `secrets.token_urlsafe` liefert kryptografisch sichere
Zufallszeichen; 24 Byte sind rund 32 Zeichen und damit nicht zu raten.
Sprechende Namen wie "vibemind-erstgespraech" waeren genau der Fehler.

GEHEIMNISSE
-----------
`GOOGLE_MEET_CLIENT_SECRET` und `GOOGLE_MEET_REFRESH_TOKEN` sind
Geheimnisse und werden aus jedem Fehlertext gefiltert (`_ohne_geheimnis`),
bevor er in die Werkzeug-Antwort, in den Chat und ins Log geht — dieselbe
Klasse Vorfall wie beim CalDAV-Passwort.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

# Oeffentliche Jitsi-Instanz. Ein eigener Server (spaeter, etwa unter der
# eigenen Domain) aendert AUSSCHLIESSLICH diesen Wert — die Logik bleibt.
JITSI_BASIS = "https://meet.jit.si"
JITSI_ZUFALL_BYTES = 24

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_MEET_URL = "https://meet.googleapis.com/v2/spaces"
GOOGLE_ZEITLIMIT = 20.0

FEHLER_MAXLAENGE = 200


def konfiguration():
    """(anbieter, client_id, client_secret, refresh_token) zur AUFRUFZEIT.

    Gleicher Grund wie `kalender.konfiguration()`: sonst koennte die Suite
    den unkonfigurierten Fall nicht pruefen, und ein spaeter nachgetragener
    Wert wirkte erst nach einem Neustart.
    """
    return (
        (os.environ.get("KONFERENZ_ANBIETER", "") or "jitsi").strip().lower(),
        os.environ.get("GOOGLE_MEET_CLIENT_ID", "").strip(),
        os.environ.get("GOOGLE_MEET_CLIENT_SECRET", ""),
        os.environ.get("GOOGLE_MEET_REFRESH_TOKEN", ""),
    )


def _ohne_geheimnis(text: str) -> str:
    """Client-Secret und Auffrischungstoken duerfen in keinem Text landen."""
    _a, _id, secret, refresh = konfiguration()
    for wert in (secret, refresh):
        if wert:
            text = text.replace(wert, "***").replace(
                urllib.parse.quote(wert, safe=""), "***")
    return text


def _kurz(text: str) -> str:
    return " ".join((text or "").split())[:FEHLER_MAXLAENGE]


def jitsi_raum() -> str:
    """Ein nicht zu ratender Raum. Entsteht lokal, ohne jede Anfrage."""
    return f"{JITSI_BASIS}/{secrets.token_urlsafe(JITSI_ZUFALL_BYTES)}"


def _zugriffstoken(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Kurzlebiges Zugriffstoken aus dem Auffrischungstoken.

    Bewusst ohne Zwischenspeicher: ein Termin entsteht selten, und ein
    gespeichertes Token waere ein Geheimnis mehr, das irgendwo liegt.
    """
    daten = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    anfrage = urllib.request.Request(
        GOOGLE_TOKEN_URL, data=daten,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(anfrage, timeout=GOOGLE_ZEITLIMIT) as antwort:
        return json.load(antwort)["access_token"]


def google_raum(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Ein Meet-Raum ohne Kalendereintrag. Rueckgabe ist die Beitritts-URL."""
    token = _zugriffstoken(client_id, client_secret, refresh_token)
    anfrage = urllib.request.Request(
        GOOGLE_MEET_URL, data=b"{}", method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=GOOGLE_ZEITLIMIT) as antwort:
        raum = json.load(antwort)
    url = (raum.get("meetingUri") or "").strip()
    if not url:
        raise ValueError("Meet-API lieferte keine meetingUri")
    return url


def raum(anbieter: str = "") -> tuple:
    """(url, hinweis) — der Konferenzlink fuer einen Termin.

    Faellt in JEDEM Zweifelsfall auf Jitsi zurueck und sagt warum: ohne
    Konfiguration, bei unbekanntem Anbieter und wenn Google nicht
    antwortet. Ein Termin ohne Link waere schlechter als ein Termin mit
    einem Link, der nicht von Google kommt.
    """
    gewaehlt, client_id, client_secret, refresh_token = konfiguration()
    gewaehlt = (anbieter or gewaehlt or "jitsi").strip().lower()

    if gewaehlt != "google":
        if gewaehlt != "jitsi":
            return jitsi_raum(), (
                f"Unbekannter Anbieter {gewaehlt!r} — Jitsi verwendet.")
        return jitsi_raum(), ""

    if not (client_id and client_secret and refresh_token):
        return jitsi_raum(), (
            "Google Meet ist nicht konfiguriert (GOOGLE_MEET_CLIENT_ID, "
            "GOOGLE_MEET_CLIENT_SECRET, GOOGLE_MEET_REFRESH_TOKEN) — "
            "Jitsi verwendet.")
    try:
        return google_raum(client_id, client_secret, refresh_token), ""
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
            KeyError, json.JSONDecodeError, OSError) as fehler:
        return jitsi_raum(), (
            "Google Meet nicht erreichbar, Jitsi verwendet: "
            + _ohne_geheimnis(_kurz(f"{type(fehler).__name__}: {fehler}")))
