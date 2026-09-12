#!/usr/bin/env python3
"""deploy/google-meet-zugang.py — holt EINMALIG das Auffrischungstoken fuer
Google Meet und schreibt es in eine .env. Laeuft auf DEINEM Rechner, nicht
auf der VM: der Schritt braucht einen Browser.

WARUM DIESES SKRIPT UEBERHAUPT. `konferenz.py` braucht drei Werte:
CLIENT_ID, CLIENT_SECRET und ein REFRESH_TOKEN. Die ersten beiden legst du
in der Google Cloud Console an (Anleitung unten). Das dritte entsteht nur
durch eine Anmeldung mit deinem Google-Konto — die kann und darf dir
niemand abnehmen. Dieses Skript nimmt dir alles ausser dem Klick ab: es
startet einen Empfangspunkt auf 127.0.0.1, oeffnet den Browser, faengt die
Rueckleitung ab und tauscht den Code gegen das Token.

WAS VORHER ZU TUN IST (einmalig, ca. 10 Minuten)
------------------------------------------------
 1. console.cloud.google.com oeffnen, ein Projekt anlegen (Name egal).
 2. "APIs & Dienste" -> "Bibliothek" -> "Google Meet API" -> aktivieren.
 3. "APIs & Dienste" -> "OAuth-Zustimmungsbildschirm": Nutzertyp "Extern",
    App-Name eintragen, deine Adresse als Kontakt. Unter "Testnutzer" DEIN
    Google-Konto eintragen — sonst verweigert Google spaeter die Anmeldung.
    Die App muss NICHT veroeffentlicht werden; ein Testnutzer genuegt, und
    das Auffrischungstoken bleibt gueltig, solange du es nicht widerrufst.
 4. "Anmeldedaten" -> "Anmeldedaten erstellen" -> "OAuth-Client-ID" ->
    Anwendungstyp "Desktop-App". Du bekommst Client-ID und Client-Secret.
 5. Dieses Skript aufrufen:
        python deploy/google-meet-zugang.py --client-id <ID> --env .env
    Das Secret fragt es interaktiv ab, damit es nicht in der
    Shell-Historie landet. Alternativ liegt es in
    GOOGLE_MEET_CLIENT_SECRET in der Umgebung.

WAS DAS SKRIPT NICHT TUT. Es legt kein Konto an, es klickt keine
Zustimmung, es speichert kein Passwort. Die Anmeldung passiert in deinem
Browser, unter deinen Augen. Das Skript sieht nur den Code, den Google
danach an 127.0.0.1 zurueckgibt.

WARUM NUR EIN BERECHTIGUNGSUMFANG. `meetings.space.created` erlaubt genau
eines: Raeume anzulegen, die diese Anwendung selbst erzeugt hat. Kein
Zugriff auf deinen Kalender, keine Mails, keine bestehenden Konferenzen.
Weniger geht nicht, mehr braucht es nicht.
"""
from __future__ import annotations

import argparse
import getpass
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/meetings.space.created"
SCHLUESSEL = ("GOOGLE_MEET_CLIENT_ID", "GOOGLE_MEET_CLIENT_SECRET",
              "GOOGLE_MEET_REFRESH_TOKEN")


class _Empfang(http.server.BaseHTTPRequestHandler):
    """Faengt die Rueckleitung von Google ab. Beantwortet genau eine Anfrage."""

    def do_GET(self):  # noqa: N802
        teile = urllib.parse.urlparse(self.path)
        werte = urllib.parse.parse_qs(teile.query)
        self.server.code = (werte.get("code") or [""])[0]
        self.server.fehler = (werte.get("error") or [""])[0]
        self.server.zustand = (werte.get("state") or [""])[0]
        gut = bool(self.server.code) and not self.server.fehler
        if gut:
            text = ("<h2>Fertig.</h2><p>Du kannst dieses Fenster schliessen "
                    "und zum Terminal zurueckgehen.</p>")
        else:
            grund = self.server.fehler or "kein Code"
            text = f"<h2>Fehlgeschlagen.</h2><p>{grund}</p>"
        roh = f"<html><meta charset='utf-8'><body>{text}</body></html>".encode()
        self.send_response(200 if gut else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *_):
        pass


def code_holen(client_id: str) -> tuple:
    """(code, redirect_uri) — oeffnet den Browser und wartet auf die Antwort."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Empfang)
    server.code = server.fehler = server.zustand = ""
    redirect = f"http://127.0.0.1:{server.server_address[1]}/"
    zustand = secrets.token_urlsafe(16)
    ziel = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": zustand,
    })
    print("\n  Browser wird geoeffnet. Falls nicht, oeffne von Hand:")
    print(f"  {ziel}\n")
    threading.Thread(target=lambda: webbrowser.open(ziel), daemon=True).start()
    server.handle_request()
    server.server_close()
    if server.fehler:
        raise SystemExit(f"  Google meldet: {server.fehler}")
    if server.zustand != zustand:
        raise SystemExit("  Zustandswert passt nicht — Abbruch (moeglicher Angriff).")
    if not server.code:
        raise SystemExit("  Kein Code empfangen.")
    return server.code, redirect


def token_tauschen(client_id: str, client_secret: str, code: str,
                   redirect: str) -> str:
    daten = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }).encode()
    anfrage = urllib.request.Request(
        TOKEN_URL, data=daten,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        nutzlast = json.load(antwort)
    token = nutzlast.get("refresh_token", "")
    if not token:
        raise SystemExit(
            "  Google lieferte KEIN Auffrischungstoken. Das passiert, wenn du\n"
            "  diese Anwendung schon einmal zugelassen hast. Widerrufe sie unter\n"
            "  myaccount.google.com/permissions und starte das Skript neu.")
    return token


def env_schreiben(pfad: str, werte: dict) -> None:
    """Setzt die drei Schluessel, laesst alles andere unangetastet."""
    zeilen = []
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as datei:
            zeilen = [z.rstrip("\n") for z in datei]
    for name, wert in werte.items():
        neu = f"{name}={wert}"
        for i, zeile in enumerate(zeilen):
            if zeile.startswith(f"{name}="):
                zeilen[i] = neu
                break
        else:
            zeilen.append(neu)
    with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
        datei.write("\n".join(zeilen) + "\n")


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Einmaliger Google-Meet-Zugang fuer konferenz.py")
    zerleger.add_argument("--client-id", required=True)
    zerleger.add_argument("--env", default=".env",
                          help="Zieldatei (Vorgabe: .env)")
    zerleger.add_argument("--nur-anzeigen", action="store_true",
                          help="nichts schreiben, Werte nur ausgeben")
    argumente = zerleger.parse_args()

    secret = os.environ.get("GOOGLE_MEET_CLIENT_SECRET", "")
    if not secret:
        secret = getpass.getpass(
            "  Client-Secret (Eingabe bleibt unsichtbar): ").strip()
    if not secret:
        raise SystemExit("  Ohne Client-Secret geht es nicht.")

    code, redirect = code_holen(argumente.client_id)
    token = token_tauschen(argumente.client_id, secret, code, redirect)

    werte = dict(zip(SCHLUESSEL, (argumente.client_id, secret, token)))
    if argumente.nur_anzeigen:
        print("\n  Diese drei Zeilen gehoeren in die .env:\n")
        for name in SCHLUESSEL:
            print(f"    {name}={werte[name]}")
    else:
        env_schreiben(argumente.env, werte)
        print(f"\n  Geschrieben nach {argumente.env}: {', '.join(SCHLUESSEL)}")
    print("\n  Danach in derselben .env setzen:  KONFERENZ_ANBIETER=google")
    print("  Das Auffrischungstoken ist ein Geheimnis wie ein Passwort.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
