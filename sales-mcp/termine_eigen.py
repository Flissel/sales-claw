"""Eigene Termine des Betreibers (Spec 2026-10-14 §1.1): ohne Kontakt, mit CalDAV-Abgleich.
CalDAV legt nur an (If-None-Match: *) -> Aendern = loeschen + neu eintragen mit derselben uid."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
import kalender
import server

DAUER_MIN, DAUER_MAX = 5, 1440
TEXT_MAX = 200
SPALTEN = "uid, titel, beginn, dauer_minuten, ort, notiz, kalender_stand, geaendert_am"


def _zeile(z: dict) -> dict:
    return {**z, "beginn": z["beginn"].astimezone(kalender.ortszone()),
            "geaendert_am": z["geaendert_am"].isoformat()}


def _pruefen(titel, beginn, dauer):
    if not isinstance(titel, str) or not titel.strip() or len(titel) > TEXT_MAX:
        return "Titel fehlt oder ist zu lang (höchstens 200 Zeichen)."
    if not isinstance(dauer, int) or not DAUER_MIN <= dauer <= DAUER_MAX:
        return f"Dauer muss {DAUER_MIN}–{DAUER_MAX} Minuten sein."
    if beginn.tzinfo is None or beginn < datetime.now(beginn.tzinfo) - timedelta(minutes=1):
        return "Der Termin liegt in der Vergangenheit."
    return None


def _eintragen(uid, titel, beginn, dauer, ort) -> str:
    naiv = beginn.astimezone(kalender.ortszone()).replace(tzinfo=None)
    zustand, grund = kalender.eintragen(uid, kalender.ics(uid, naiv, dauer, titel, ort=ort or ""))
    return grund and f"fehlgeschlagen: {grund}" or zustand


def anlegen(titel, beginn, dauer_minuten, ort="", notiz=""):
    f = _pruefen(titel, beginn, dauer_minuten)
    if f:
        return {"fehler": f}
    uid = f"{uuid.uuid4()}@sales-claw"
    stand = _eintragen(uid, titel.strip(), beginn, dauer_minuten, ort)
    z = server._q(f"insert into eigene_termine (uid, titel, beginn, dauer_minuten, ort, notiz, kalender_stand) "
                  f"values (%s,%s,%s,%s,nullif(%s,''),nullif(%s,''),%s) returning {SPALTEN}",
                  (uid, titel.strip(), beginn, dauer_minuten, ort or "", notiz or "", stand))
    return {"termin": _zeile(z[0])}


def aendern(uid, geaendert_am, **felder):
    alt = server._q(f"select {SPALTEN} from eigene_termine where uid = %s", (uid,))
    if not alt:
        return {"fehler": "Diesen Termin gibt es nicht."}
    if alt[0]["geaendert_am"].isoformat() != geaendert_am:
        return {"veraltet": True}
    neu = {**alt[0], **{k: v for k, v in felder.items() if k in ("titel", "beginn", "dauer_minuten", "ort", "notiz")}}
    f = _pruefen(neu["titel"], neu["beginn"], neu["dauer_minuten"])
    if f:
        return {"fehler": f}
    kalender.loeschen(uid)
    stand = _eintragen(uid, neu["titel"], neu["beginn"], neu["dauer_minuten"], neu.get("ort"))
    z = server._q(f"update eigene_termine set titel=%s, beginn=%s, dauer_minuten=%s, ort=nullif(%s,''), "
                  f"notiz=nullif(%s,''), kalender_stand=%s, geaendert_am=now() where uid=%s and geaendert_am=%s "
                  f"returning {SPALTEN}",
                  (neu["titel"], neu["beginn"], neu["dauer_minuten"], neu.get("ort") or "", neu.get("notiz") or "",
                   stand, uid, alt[0]["geaendert_am"]))
    return {"termin": _zeile(z[0])} if z else {"veraltet": True}


def loeschen(uid):
    z = server._q("delete from eigene_termine where uid = %s returning uid", (uid,))
    if not z:
        return {"fehler": "Diesen Termin gibt es nicht."}
    zustand, grund = kalender.loeschen(uid)
    return {"geloescht": True, "kalender": grund and f"fehlgeschlagen: {grund}" or zustand}


def im_zeitraum(von, bis):
    return [_zeile(z) for z in server._q(
        f"select {SPALTEN} from eigene_termine where beginn < %s and beginn + make_interval(mins => dauer_minuten) > %s "
        "order by beginn", (bis, von))]
