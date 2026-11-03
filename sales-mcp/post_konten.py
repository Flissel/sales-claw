"""Konten der Post-Sammelstelle: mehrere Postfaecher je Anbieter (Stufe 1).

Die Tabelle `post_konten` kennt zwei Herkuenfte:
- `env`: aus der Umgebung (Hauptpostfach, POSTFACH_GMX_*, POSTFACH_GMAIL_*); das
  Passwort bleibt in der Umgebung, die Tabelle haelt nur Adresse und Zustand.
- `ui`: in der Oberflaeche angelegt; das Passwort liegt NUR versiegelt
  (post_tresor) in `zugang_versiegelt`.

Rueckgaben und Fehlertexte nennen nie ein Passwort - auch dann nicht, wenn die
Probe-Ausnahme es selbst enthaelt: von ihr bleibt nur der Typname.
"""
from __future__ import annotations

import re

import post_tresor
import postfach
import server

KENNUNG_MUSTER = r"^[a-z][a-z0-9-]{1,30}$"
# Neue Konten aus der UI: nur GMX und Gmail. Namecheap (das Hauptpostfach)
# kommt ausschliesslich aus der Umgebung.
UI_ANBIETER = ("gmx", "gmail")
# Diese Kennungen gehoeren den Konten aus der Umgebung (env_konten_uebernehmen
# legt sie mit `on conflict do nothing` an). Ein UI-Konto mit demselben Namen
# wuerde das Env-Konto still verdraengen - und alte uids "gmx:12" zeigten
# dann auf ein fremdes Postfach.
RESERVIERT = (postfach.HAUPT, "gmx", "gmail")
PROBE_TIMEOUT_S = 30
_SPALTEN = ("id, besitzer, kennung, anbieter, adresse, zugang_versiegelt, quelle, "
            "uidvalidity, letzte_uid, altbestand_fertig, aktiv, angelegt_am")


def _probe_imap(konto: postfach.Konto) -> None:
    """Echte Anmeldung und Abmeldung; wirft bei Ablehnung.

    Mit eigener Zeitgrenze am Socket: die Probe laeuft in sales-ui, waehrend
    jemand auf die Seite wartet - ein haengender Anbieter darf die Anfrage
    nicht endlos halten. Kein prozessweiter Default (s. postfach._imap_oeffnen)."""
    kasten = postfach._imap_oeffnen(konto, timeout=PROBE_TIMEOUT_S)
    try:
        kasten.logout()
    except Exception:  # noqa: BLE001 - die Anmeldung hat geklappt, mehr wollen wir nicht
        pass


def env_konten_uebernehmen(besitzer: str) -> int:
    """Legt je eingerichtetem Env-Postfach (haupt, gmx, gmail) eine Zeile an.
    Idempotent ueber `kennung`; Rueckgabe = Anzahl neu angelegter Zeilen."""
    kandidaten = []
    if postfach.konfiguriert():
        kandidaten.append(("haupt", "namecheap", postfach.IMAP_USER))
    for k in ("gmx", "gmail"):
        z = postfach.konto(k)
        if z is not None:
            kandidaten.append((k, k, z.adresse))
    neu = 0
    with server.pool.connection() as conn:
        for kennung, anbieter, adresse in kandidaten:
            zeile = conn.execute(
                "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
                "values (%s, %s, %s, %s, 'env') on conflict (kennung) do nothing "
                "returning id", (besitzer, kennung, anbieter, adresse)).fetchone()
            neu += 1 if zeile else 0
    return neu


def konto_anlegen(besitzer: str, kennung: str, anbieter: str, adresse: str,
                  passwort: str, probe=None) -> dict:
    """Prueft, probiert die Anmeldung, versiegelt das Passwort, speichert.
    Rueckgabe {"konto_id", "kennung"} oder {"fehler"} - nie mit Passwort."""
    kennung = (kennung or "").strip()
    adresse = (adresse or "").strip()
    if not re.match(KENNUNG_MUSTER, kennung):
        return {"fehler": "Kennung ungueltig: kleine Buchstaben, Ziffern und Bindestrich, "
                          "2 bis 31 Zeichen, mit einem Buchstaben beginnen"}
    if kennung in RESERVIERT:
        return {"fehler": f"Kennung '{kennung}' ist fuer die Postfaecher aus der "
                          "Umgebung reserviert - bitte z. B. 'gmx-privat' waehlen"}
    if anbieter not in UI_ANBIETER:
        return {"fehler": "Anbieter nicht zulaessig (erlaubt: gmx, gmail)"}
    if not adresse or not passwort:
        return {"fehler": "Adresse und Passwort sind noetig"}
    with server.pool.connection() as conn:
        if conn.execute("select 1 from post_konten where kennung = %s",
                        (kennung,)).fetchone():
            return {"fehler": f"Kennung '{kennung}' ist schon vergeben"}
    try:
        (probe or _probe_imap)(postfach.Konto(kennung, adresse, passwort, anbieter_id=anbieter))
    except Exception as e:  # noqa: BLE001 - nur der Typ, der Text koennte das Passwort tragen
        return {"fehler": f"Anmeldung am Postfach fehlgeschlagen ({type(e).__name__})"}
    try:
        versiegelt = post_tresor.versiegeln(passwort)
    except post_tresor.TresorFehler as e:
        return {"fehler": f"Passwort konnte nicht versiegelt werden: {e}"}
    with server.pool.connection() as conn:
        zeile = conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, "
            "zugang_versiegelt, quelle) values (%s, %s, %s, %s, %s, 'ui') "
            "on conflict (kennung) do nothing returning id",
            (besitzer, kennung, anbieter, adresse, versiegelt)).fetchone()
    if not zeile:                      # zwischen Pruefung und Insert vergeben
        return {"fehler": f"Kennung '{kennung}' ist schon vergeben"}
    return {"konto_id": str(zeile["id"]), "kennung": kennung}


def aktive_konten() -> list[dict]:
    """Alle aktiven Zeilen; `zugang_versiegelt` bleibt fuer verbinden() drin
    (es ist versiegelt, kein Klartext)."""
    with server.pool.connection() as conn:
        return conn.execute(
            f"select {_SPALTEN} from post_konten where aktiv order by kennung").fetchall()


def verbinden(zeile: dict):
    """Angemeldete IMAP-Verbindung zu einer Konto-Zeile."""
    if zeile["quelle"] == "env":
        return postfach.oeffnen(zeile["kennung"])
    passwort = post_tresor.oeffnen(zeile["zugang_versiegelt"])
    return postfach._imap_oeffnen(postfach.Konto(
        zeile["kennung"], zeile["adresse"], passwort, anbieter_id=zeile["anbieter"]))
