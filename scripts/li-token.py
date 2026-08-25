"""LinkedIn-Zugriffstoken holen oder erneuern.

WANN MAN DAS BRAUCHT
--------------------
Das Token laeuft nach rund 60 Tagen ab. Danach schreibt sales-linkedin in
`drafts.error` die Meldung „LinkedIn lehnt das Zugriffstoken ab (HTTP 401)"
und veroeffentlicht nichts mehr — freigegebene Beitraege bleiben liegen,
es geht nichts verloren.

    python scripts/li-token.py

Das Skript druckt eine Zustimmungs-Adresse, wartet auf die Rueckleitung und
schreibt Token und Person-Kennung nach sales-claw/.env. Danach:

    docker compose up -d sales-linkedin

WAS ES NICHT TUT
----------------
Es zeigt keine Geheimnisse an. Von Token und Client-Secret erscheinen
hoechstens Laenge und die letzten vier Zeichen — genug, um zu erkennen, DASS
etwas ankam, zu wenig, um es zu missbrauchen. Auch das Zugriffslog des
kurzlebigen Empfaengers bleibt aus: die Rueckleitungs-Adresse traegt den
Autorisierungscode im Klartext.

VORAUSSETZUNG
-------------
In der LinkedIn-Entwicklerkonsole muss bei der App unter „Auth" die
Rueckleitungs-Adresse `http://localhost:8712/callback` eingetragen sein und
das Produkt „Share on LinkedIn" (Scope `w_member_social`) freigeschaltet.
Ohne `w_member_social` kommt ein Token zurueck, das nichts posten darf.
"""
import http.server
import io
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
SALES_ENV = os.path.join(os.path.dirname(HIER), ".env")

PORT = 8712
REDIRECT = f"http://localhost:{PORT}/callback"
# w_member_social = im eigenen Namen posten. openid/profile liefern die
# Person-Kennung (urn:li:person:...), ohne die kein Beitrag adressierbar ist.
SCOPE = "openid profile w_member_social"
WARTEZEIT_S = 300


def env_lesen(pfad, schluessel):
    if not os.path.exists(pfad):
        return None
    for zeile in io.open(pfad, encoding="utf-8", errors="replace"):
        if zeile.startswith(schluessel + "="):
            return zeile.split("=", 1)[1].strip()
    return None


def anwendungsdaten():
    """Client-Kennung und -Geheimnis — aus .env oder aus der Umgebung.

    Bewusst KEINE Eingabeaufforderung: ein Geheimnis, das jemand in ein
    Terminal tippt, steht anschliessend im Verlauf der Sitzung.
    """
    kennung = (os.environ.get("LINKEDIN_CLIENT_ID")
               or env_lesen(SALES_ENV, "LINKEDIN_CLIENT_ID"))
    geheim = (os.environ.get("LINKEDIN_CLIENT_SECRET")
              or env_lesen(SALES_ENV, "LINKEDIN_CLIENT_SECRET"))
    if not kennung or not geheim:
        raise SystemExit(
            "LINKEDIN_CLIENT_ID/LINKEDIN_CLIENT_SECRET fehlen. Sie stehen in "
            "der LinkedIn-Entwicklerkonsole unter 'Auth' und gehoeren in "
            f"{SALES_ENV} — oder in die Umgebung dieses Aufrufs.")
    return kennung, geheim


def zustimmung_einholen(client_id):
    """Zustimmungs-Adresse zeigen und auf die Rueckleitung warten."""
    zustand = secrets.token_urlsafe(24)
    ergebnis = {}

    class Empfaenger(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            teile = urllib.parse.urlparse(self.path)
            if teile.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(teile.query)
            ergebnis["code"] = (q.get("code") or [None])[0]
            ergebnis["state"] = (q.get("state") or [None])[0]
            ergebnis["fehler"] = (q.get("error_description")
                                  or q.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            text = ("Zustimmung angekommen — dieses Fenster kann zu."
                    if ergebnis["code"] else
                    f"Fehlgeschlagen: {ergebnis['fehler']}")
            self.wfile.write(
                f"<html><body><p>{text}</p></body></html>".encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *_):
            pass    # kein Zugriffslog: die Adresse traegt den Code

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Empfaenger)
    adresse = "https://www.linkedin.com/oauth/v2/authorization?" + \
        urllib.parse.urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": REDIRECT, "state": zustand, "scope": SCOPE})
    print(f"Empfaenger laeuft auf 127.0.0.1:{PORT}. Diese Adresse im Browser "
          f"oeffnen:\n\n{adresse}\n")
    print(f"(wartet bis zu {WARTEZEIT_S // 60} Minuten auf die Zustimmung)")
    srv.timeout = WARTEZEIT_S
    srv.serve_forever()

    if ergebnis.get("fehler"):
        raise SystemExit("LinkedIn meldet: " + str(ergebnis["fehler"]))
    if not ergebnis.get("code"):
        raise SystemExit("Kein Code empfangen (Zeitueberschreitung?)")
    if ergebnis.get("state") != zustand:
        # Der Zustandswert ist der Schutz gegen eine untergeschobene
        # Rueckleitung. Stimmt er nicht, wurde der Code nicht von DIESEM
        # Aufruf angefordert — dann wird er nicht eingeloest.
        raise SystemExit("state stimmt nicht — Abbruch (moegliche Faelschung)")
    return ergebnis["code"]


def token_tauschen(code, client_id, client_secret):
    daten = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": REDIRECT, "client_id": client_id,
        "client_secret": client_secret}).encode()
    anfrage = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken", data=daten,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as a:
            return json.loads(a.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit("Token-Tausch fehlgeschlagen: HTTP %s — %s"
                         % (e.code, e.read().decode()[:300]))


def person_kennung(token):
    anfrage = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(anfrage, timeout=30) as a:
        return "urn:li:person:" + json.loads(a.read().decode())["sub"]


def env_schreiben(werte):
    """Die LINKEDIN_-Zeilen ersetzen, alles andere unangetastet lassen."""
    zeilen = (io.open(SALES_ENV, encoding="utf-8").read().splitlines()
              if os.path.exists(SALES_ENV) else [])
    ersetzt = tuple(n + "=" for n in werte)
    behalten = [z for z in zeilen if not z.startswith(ersetzt)]
    neu = behalten + ["",
                      "# LinkedIn (Beitraege auf dem eigenen Profil).",
                      "# Token laeuft nach rund 60 Tagen ab — Erneuerung:",
                      "#   python scripts/li-token.py"]
    neu += [f"{name}={wert}" for name, wert in werte.items()]
    io.open(SALES_ENV, "w", encoding="utf-8", newline="\n").write(
        "\n".join(neu) + "\n")


def main():
    client_id, client_secret = anwendungsdaten()
    code = zustimmung_einholen(client_id)
    antwort = token_tauschen(code, client_id, client_secret)

    token = antwort.get("access_token")
    if not token:
        raise SystemExit("Antwort ohne access_token: "
                         + json.dumps(antwort)[:200])
    scopes = antwort.get("scope", "")
    print(f"\nToken erhalten ({len(token)} Zeichen, endet auf {token[-4:]}).")
    print("gueltig (Sekunden):", antwort.get("expires_in"),
          f"≈ {int(antwort.get('expires_in', 0)) // 86400} Tage")
    print("Scopes:", scopes)
    if "w_member_social" not in scopes:
        # Ohne diesen Scope ist das Token zum Posten wertlos. Das JETZT zu
        # sagen ist besser, als es in 60 Tagen aus einem 403 zu schliessen.
        print("\nWARNUNG: 'w_member_social' fehlt — mit diesem Token laesst "
              "sich NICHTS posten. In der Entwicklerkonsole das Produkt "
              "'Share on LinkedIn' freischalten und erneut ausfuehren.")

    werte = {"LINKEDIN_CLIENT_ID": client_id,
             "LINKEDIN_CLIENT_SECRET": client_secret,
             "LINKEDIN_ACCESS_TOKEN": token}
    try:
        urn = person_kennung(token)
        werte["LINKEDIN_PERSON_URN"] = urn
        print("Person-Kennung:", urn)
    except Exception as e:                  # noqa: BLE001 — bewusst breit
        print("Person-Kennung NICHT abrufbar:", str(e)[:200])
        print("Ohne sie kann sales-linkedin keinen Beitrag adressieren.")

    env_schreiben(werte)
    print(f"\nNach {SALES_ENV} geschrieben.")
    print("Jetzt: docker compose up -d sales-linkedin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
