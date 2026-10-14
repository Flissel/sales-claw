"""Eigene Termine des Betreibers (Spec 2026-10-14 §1.1): ohne Kontakt, mit CalDAV-Abgleich.
CalDAV legt nur an (If-None-Match: *) -> Aendern = loeschen + neu eintragen mit derselben uid."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
import kalender
import server

DAUER_MIN, DAUER_MAX = 5, 1440
TEXT_MAX = 200
ORT_MAX, NOTIZ_MAX = 200, 2000
SPALTEN = "uid, titel, beginn, dauer_minuten, ort, notiz, kalender_stand, geaendert_am"


def _zeile(z: dict) -> dict:
    return {**z, "beginn": z["beginn"].astimezone(kalender.ortszone()),
            "geaendert_am": z["geaendert_am"].isoformat()}


def _pruefen(titel, beginn, dauer, ort=None, notiz=None, zukunft=True):
    if not isinstance(titel, str) or not titel.strip() or len(titel) > TEXT_MAX:
        return "Titel fehlt oder ist zu lang (höchstens 200 Zeichen)."
    if not isinstance(dauer, int) or isinstance(dauer, bool) or not DAUER_MIN <= dauer <= DAUER_MAX:
        return f"Dauer muss {DAUER_MIN}–{DAUER_MAX} Minuten sein."
    if ort is not None and (not isinstance(ort, str) or len(ort) > ORT_MAX):
        return "Ort ist ungültig oder zu lang (höchstens 200 Zeichen)."
    if notiz is not None and (not isinstance(notiz, str) or len(notiz) > NOTIZ_MAX):
        return "Notiz ist ungültig oder zu lang (höchstens 2000 Zeichen)."
    if not isinstance(beginn, datetime) or beginn.tzinfo is None:
        return "Beginn fehlt oder hat keine Zeitzone."
    if zukunft and beginn < datetime.now(beginn.tzinfo) - timedelta(minutes=1):
        return "Der Termin liegt in der Vergangenheit."
    return None


def _eintragen(uid, titel, beginn, dauer, ort) -> str:
    naiv = beginn.astimezone(kalender.ortszone()).replace(tzinfo=None)
    zustand, grund = kalender.eintragen(uid, kalender.ics(uid, naiv, dauer, titel, ort=ort or ""))
    return grund and f"fehlgeschlagen: {grund}" or zustand


def _stand_setzen(uid, stand) -> None:
    # Bewusst ohne geaendert_am: das ist der Versionsstempel der Nutzerinhalte.
    server._q("update eigene_termine set kalender_stand=%s where uid=%s", (stand, uid))


def anlegen(titel, beginn, dauer_minuten, ort="", notiz=""):
    f = _pruefen(titel, beginn, dauer_minuten, ort, notiz)
    if f:
        return {"fehler": f}
    uid = f"{uuid.uuid4()}@sales-claw"
    # Erst speichern, dann CalDAV: ein DB-Ausfall hinterlaesst kein Waisen-Event im Handy.
    server._q("insert into eigene_termine (uid, titel, beginn, dauer_minuten, ort, notiz) "
              "values (%s,%s,%s,%s,nullif(%s,''),nullif(%s,''))",
              (uid, titel.strip(), beginn, dauer_minuten, ort or "", notiz or ""))
    stand = _eintragen(uid, titel.strip(), beginn, dauer_minuten, ort)
    _stand_setzen(uid, stand)
    z = server._q(f"select {SPALTEN} from eigene_termine where uid = %s", (uid,))
    return {"termin": _zeile(z[0])}


def aendern(uid, geaendert_am, **felder):
    alt = server._q(f"select {SPALTEN} from eigene_termine where uid = %s", (uid,))
    if not alt:
        return {"fehler": "Diesen Termin gibt es nicht."}
    if alt[0]["geaendert_am"].isoformat() != geaendert_am:
        return {"veraltet": True}
    neu = {**alt[0], **{k: v for k, v in felder.items() if k in ("titel", "beginn", "dauer_minuten", "ort", "notiz")}}
    # Vergangenheitspruefung nur, wenn der Beginn wirklich geaendert wird.
    beginn_neu = "beginn" in felder and felder["beginn"] != alt[0]["beginn"]
    f = _pruefen(neu["titel"], neu["beginn"], neu["dauer_minuten"], neu.get("ort"), neu.get("notiz"),
                 zukunft=beginn_neu)
    if f:
        return {"fehler": f}
    titel = neu["titel"].strip()
    # Erst die geschuetzte DB-Aenderung, dann CalDAV (loeschen + neu, gleiche uid).
    z = server._q("update eigene_termine set titel=%s, beginn=%s, dauer_minuten=%s, ort=nullif(%s,''), "
                  "notiz=nullif(%s,''), kalender_stand=null, geaendert_am=now() "
                  "where uid=%s and geaendert_am=%s returning geaendert_am",
                  (titel, neu["beginn"], neu["dauer_minuten"], neu.get("ort") or "", neu.get("notiz") or "",
                   uid, alt[0]["geaendert_am"]))
    if not z:
        return {"veraltet": True}
    kalender.loeschen(uid)  # Rueckgabe egal: scheitert es, zeigt der PUT-Stand das Problem.
    _stand_setzen(uid, _eintragen(uid, titel, neu["beginn"], neu["dauer_minuten"], neu.get("ort")))
    return {"termin": _zeile(server._q(f"select {SPALTEN} from eigene_termine where uid = %s", (uid,))[0])}


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
