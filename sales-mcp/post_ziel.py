"""Ziel je Mail (Spec 2026-11-06 §5/§6): wohin gehoert die Mail im Postfach?

  posteingang | zur_info | to_review | loeschen

`ziel_fuer` ist rein und entscheidet nach fester Reihenfolge. `ziele_aktualisieren`
schreibt das Ergebnis in post_mails.ziel. Geloescht wird spaeter nur, was hier
`loeschen` bekam UND dessen Jahr fuer den Besitzer freigegeben ist (Task 5); jede
Unsicherheit faellt darum auf die sichere Seite (zur_info/posteingang), nie auf loeschen.
Kein IMAP in diesem Modul.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import post_struktur

LOG = logging.getLogger("post_ziel")

POSTEINGANG, ZUR_INFO, TO_REVIEW, LOESCHEN = "posteingang", "zur_info", "to_review", "loeschen"
WERBUNG = "Werbung"
# Beginn der Begruendung, die post_einordnung.nach_muster bei Treffer 0 der festen
# Sensibel-Muster schreibt (Feld `betreff`, Index 0 = Login-/Sicherheitscode).
LOGIN_CODE = "sensibel-muster:betreff:0"
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp")
LOGIN_FRIST = timedelta(days=1)
ALTER_TAGE = 90
_BLOCK = 1000     # Mails je UPDATE


def _stichtag(wert: str | None) -> date:
    """Stichtag aus POST_AUFRAEUMEN_AB. Fehlt er oder ist er kaputt: date.max, also ist
    alles Altbestand und nichts geht direkt nach To-Review (sicherer Default)."""
    if not (wert or "").strip():
        return date.max
    try:
        return date.fromisoformat(wert.strip())
    except ValueError:
        LOG.warning("POST_AUFRAEUMEN_AB ist kein ISO-Datum; alles gilt als Altbestand")
        return date.max


ALTBESTAND_AB: date = _stichtag(os.environ.get("POST_AUFRAEUMEN_AB"))


def _als_datetime(wert) -> datetime | None:
    if wert is None or wert == "":
        return None
    if isinstance(wert, datetime):
        return wert
    if isinstance(wert, date):
        return datetime(wert.year, wert.month, wert.day)
    try:
        return datetime.fromisoformat(str(wert))
    except ValueError:
        return None      # unlesbares Datum zaehlt wie kein Datum: nie loeschen


def _nur_bilder(anhaenge) -> bool:
    return all(str(name).strip().lower().endswith(BILD_ENDUNGEN) for name in (anhaenge or []))


def ziel_fuer(m: dict, jetzt: datetime, freigegebene_jahre: set[int],
              ist_kontakt: bool, geschuetzt: bool) -> str:
    """Ziel der Mail; der erste Treffer gewinnt (Reihenfolge der Brief, Task 4)."""
    # 1. Handentscheidung gilt immer.
    if m.get("ziel_manuell"):
        return m.get("ziel") or ZUR_INFO
    # 2. Unklares bleibt zum Nachsehen im Posteingang.
    if m.get("fach") == post_struktur.UNKLAR:
        return POSTEINGANG

    datum = _als_datetime(m.get("datum"))
    if datum is not None and datum.tzinfo is None and jetzt.tzinfo is not None:
        datum = datum.replace(tzinfo=jetzt.tzinfo)

    # 3. Werbung: nur sichere, nicht geschuetzte, nicht von Kontakten, nur mit Bild-Anhaengen.
    if m.get("fach") == WERBUNG:
        if (not m.get("werbung_sicher") or ist_kontakt or geschuetzt
                or not _nur_bilder(m.get("anhaenge"))):
            return ZUR_INFO
        if datum is None:
            return ZUR_INFO           # ohne Datum weder Jahr noch Alter: nie loeschen
        if datum.date() >= ALTBESTAND_AB:
            return TO_REVIEW          # neue Mail: ein Mensch schaut drauf
        if m.get("ziel") == LOESCHEN:
            return LOESCHEN           # war schon vor der Freigabe als loeschbar vorgesehen
        if datum.year not in freigegebene_jahre:
            return LOESCHEN           # wartet auf die Freigabe ihres Jahres
        return TO_REVIEW              # erst nach der Freigabe als Werbung erkannt (Spec §6.1)

    # 4. Login-Code: einen Tag im Posteingang, danach nur noch zur Info.
    if (m.get("begruendung") or "").startswith(LOGIN_CODE):
        if datum is None or jetzt - datum < LOGIN_FRIST:
            return POSTEINGANG
        return ZUR_INFO

    # 5. Aufmerksamkeit: im Posteingang, ausser Altbestand aelter als 90 Tage. Der Bezugspunkt
    #    ist hoechstens der Stichtag, nicht „jetzt“ (R2): was im Posteingang alt wird, bleibt
    #    dort (Spec §5), sonst wanderte jede Mail nach 90 Tagen ab.
    if m.get("aufmerksamkeit"):
        if datum is not None and datum.date() < ALTBESTAND_AB:
            bezug = min(jetzt.date(), ALTBESTAND_AB)
            if (bezug - datum.date()).days > ALTER_TAGE:
                return ZUR_INFO
        return POSTEINGANG

    # 6. Alles andere ist nur zur Info.
    return ZUR_INFO


def _db():
    # server erst hier: das Modul bleibt ohne Datenbank importier- und testbar.
    import server
    return server


# Spalten, die ziel_fuer braucht.
_SPALTEN = ("id, besitzer, von, fach, aufmerksamkeit, werbung_sicher, datum, anhaenge, "
            "begruendung, ziel, ziel_manuell")


def _freigegeben(server, besitzer: str | None = None) -> dict[str, set[int]]:
    """Freigegebene Jahre je Besitzer; mit `besitzer` nur dessen."""
    sql, werte = "select besitzer, jahr from post_loeschfreigaben", ()
    if besitzer is not None:
        sql, werte = sql + " where besitzer = %s", (besitzer,)
    freigegeben: dict[str, set[int]] = {}
    for z in server._q(sql, werte):
        freigegeben.setdefault(z["besitzer"], set()).add(z["jahr"])
    return freigegeben


def _kontakte(server, adresse: str | None = None) -> set[str]:
    """Adressen bekannter Kontakte; jede Zeile in leads zaehlt, auch archivierte.
    Mit `adresse` nur diese (leer, wenn sie kein Kontakt ist)."""
    sql = ("select distinct lower(trim(email)) as adresse from leads "
           "where email is not null and trim(email) <> ''")
    werte = ()
    if adresse is not None:
        sql, werte = sql + " and lower(trim(email)) = %s", (adresse,)
    return {z["adresse"] for z in server._q(sql, werte)}


def _schutz(server, besitzer: str | None = None) -> set[tuple[str, str]]:
    """(Besitzer, Muster) der Regeln „nie Werbung“. Dieselbe Musterlogik wie
    post_werbung.geschuetzt: gleich ohne Gross/Klein."""
    sql = ("select besitzer, lower(muster) as muster from post_regeln "
           "where art = 'nie_werbung' and feld = 'von' and besitzer is not null")
    werte = ()
    if besitzer is not None:
        sql, werte = sql + " and besitzer = %s", (besitzer,)
    return {(z["besitzer"], z["muster"]) for z in server._q(sql, werte)}


def _berechnen(z: dict, jetzt: datetime, freigegeben: dict[str, set[int]],
               kontakte: set[str], schutz: set[tuple[str, str]]) -> str:
    adresse = post_struktur.absender_adresse(z["von"])
    # Ohne lesbare Absenderadresse laesst sich weder Kontakt noch Schutz pruefen: dann
    # gilt die Mail als geschuetzt (nie loeschen).
    geschuetzt = (not adresse or (z["besitzer"], post_struktur.absender_muster(adresse).lower())
                  in schutz)
    return ziel_fuer(z, jetzt, freigegeben.get(z["besitzer"], set()),
                     bool(adresse) and adresse in kontakte, geschuetzt)


def ziel_frisch(mail_id) -> str | None:
    """Ziel genau dieser Mail, frisch aus der Datenbank berechnet; None, wenn sie nicht
    (mehr) eingeordnet ist. Fuer post_ordnen direkt vor dem Loeschen (R13): das
    gespeicherte `ziel` kann seit dem letzten ziele_aktualisieren veraltet sein."""
    server = _db()
    zeilen = server._q(f"select {_SPALTEN} from post_mails "
                       "where id = %s and status = 'eingeordnet'", (mail_id,))
    if not zeilen:
        return None
    z = zeilen[0]
    adresse = post_struktur.absender_adresse(z["von"])
    return _berechnen(z, datetime.now(timezone.utc), _freigegeben(server, z["besitzer"]),
                      _kontakte(server, adresse) if adresse else set(),
                      _schutz(server, z["besitzer"]))


def ziele_aktualisieren() -> int:
    """Berechnet das Ziel aller eingeordneten Mails ohne Handentscheidung neu und schreibt
    nur Abweichungen. Rueckgabe: Zahl geaenderter Zeilen. Geloeschte Mails bleiben unberuehrt.

    Die Eingaben werden gebuendelt geladen (je Lauf einmal), nicht je Mail abgefragt."""
    server = _db()
    jetzt = datetime.now(timezone.utc)
    freigegeben = _freigegeben(server)
    kontakte = _kontakte(server)
    schutz = _schutz(server)

    zeilen = server._q(
        f"select {_SPALTEN} from post_mails "
        "where status = 'eingeordnet' and not ziel_manuell")

    neu: dict[str, list] = {}
    for z in zeilen:
        ziel = _berechnen(z, jetzt, freigegeben, kontakte, schutz)
        if ziel != z["ziel"]:
            neu.setdefault(ziel, []).append(z["id"])

    geaendert = 0
    with server.pool.connection() as conn:
        for ziel, ids in neu.items():
            for i in range(0, len(ids), _BLOCK):
                # Die Bedingungen wiederholt: eine Handentscheidung oder ein Loeschen, das
                # zwischen Lesen und Schreiben passiert, wird nicht ueberschrieben.
                geaendert += conn.execute(
                    "update post_mails set ziel = %s where id = any(%s) "
                    "and status = 'eingeordnet' and not ziel_manuell and ziel is distinct from %s",
                    (ziel, ids[i:i + _BLOCK], ziel)).rowcount
    LOG.info("Ziele: %d von %d Mails geaendert", geaendert, len(zeilen))
    return geaendert
