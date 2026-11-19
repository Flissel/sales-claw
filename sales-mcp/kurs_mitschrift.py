"""Kursmitschrift: Konstanten, Wahl des Lernenden, Stand (Grundlage fuer das Kurs-Handbuch).

Logs: nie Namen oder Text.
"""
import uuid
from datetime import timedelta

import mitschrift_bericht
import server

RUBRIK_KURSE = "Kurse"
MAX_VERSUCHE = 3
NEUVERSUCH_NACH = timedelta(hours=1)
MAX_BILDER_ABSCHNITT = 6
BILD_KANTE = 800
BILD_QUALITAET = 60
MAX_ZULETZT = 5

# Wie mitschrift_bericht.STAND_SQL (Alias m), zusaetzlich mit der Rubrik: ein Wechsel
# der Rubrik aendert den Stand.
KURS_STAND_SQL = ("md5(lower(coalesce(m.rubrik,'')) || '|' || "
                  + mitschrift_bericht.STAND_SQL + ")")


def ist_kurs(rubrik: str | None) -> bool:
    return (rubrik or "").casefold() == RUBRIK_KURSE.casefold()


def _uuid(wert: object) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except ValueError:
        return None


def vorschlaege(uid: str) -> list[dict]:
    """Moegliche Lernende: Teilnehmer (ohne Organisator), danach zuletzt gewaehlte."""
    teilnehmer = server._q(
        "select l.id, l.name from termin_teilnehmer t "
        "join leads l on l.id = coalesce(t.lead_id, "
        "  (select (array_agg(x.id))[1] from leads x where lower(x.email) = lower(t.adresse) "
        "   having count(*) = 1)) "
        "where t.uid = %s and coalesce(t.rolle, '') <> 'organisator' "
        "order by t.ctid", (uid,))
    zuletzt = server._q(
        "select l.id, l.name from termin_mitschriften m join leads l on l.id = m.kurs_lead_id "
        "where m.uid <> %s group by l.id, l.name order by max(m.geholt_am) desc limit %s",
        (uid, MAX_ZULETZT))
    aus: list[dict] = []
    gesehen: set[str] = set()
    for z in list(teilnehmer) + list(zuletzt):
        lid = str(z["id"])
        if lid not in gesehen:
            gesehen.add(lid)
            aus.append({"lead_id": lid, "name": z["name"]})
    return aus


def lernender_setzen(uid: str, lead_id: str | None) -> bool:
    """Lernenden einer Kurs-Mitschrift setzen (None = entfernen). Sonst False."""
    z = server._q("select rubrik from termin_mitschriften where uid = %s", (uid,))
    if not z or not ist_kurs(z[0]["rubrik"]):
        return False
    if lead_id is None:
        neu = None
    else:
        neu = _uuid(lead_id)
        if neu is None or not server._q("select 1 from leads where id = %s", (neu,)):
            return False
    server._q("update termin_mitschriften set kurs_lead_id = %s where uid = %s returning uid",
              (neu, uid))
    return True


def kurs_stand(uid: str) -> str | None:
    z = server._q(f"select {KURS_STAND_SQL} as s from termin_mitschriften m where m.uid = %s",
                  (uid,))
    return z[0]["s"] if z else None
