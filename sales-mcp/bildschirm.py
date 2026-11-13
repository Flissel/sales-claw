"""Bildschirm-Standbilder: erfassen, ablegen, lesen (Bildauswertung live).

Der Beobachter (eigener Dienst) holt Standbilder des geteilten Bildschirms und
legt sie hier ab. Diese Datei kennt nur die Regeln (wann ist ein Bild neu
genug?) und die Tabelle `termin_bilder`. Logs: nie Inhalte, nie Namen.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from PIL import Image

import server

MIN_ABSTAND = timedelta(seconds=5)
SCHWELLE = 10          # Hamming-Abstand, ab dem ein Bild als neu gilt
SCHWELLE_STARK = 24    # ab Obergrenze nur noch bei starker Aenderung
OBERGRENZE = 150       # Bilder je Akte, danach nur noch starke Wechsel
MAX_BREITE = 1600
_JPEG_QUALITAET = 80
_NAME_MAX = 200

# Bedingung, unter der ein Termin beobachtet wird (eine Quelle fuer Liste und Pruefung).
_SOLL = ("bildschirm_auswerten and plattform = 'jitsi' "
         "and status in ('wartet_auf_einlass', 'laeuft') "
         "and abgesagt_am is null and not kein_bot and vexa_meeting_id is not null")


def dhash(jpeg: bytes) -> int:
    """64-Bit-Differenzhash (9x8 Graustufen), als signiertes int64."""
    with Image.open(io.BytesIO(jpeg)) as bild:
        klein = bild.convert("L").resize((9, 8), Image.LANCZOS)
        px = klein.tobytes()
    wert = 0
    for zeile in range(8):
        for spalte in range(8):
            wert = (wert << 1) | (1 if px[zeile * 9 + spalte] > px[zeile * 9 + spalte + 1] else 0)
    return wert - (1 << 64) if wert >= (1 << 63) else wert


def abstand(a: int, b: int) -> int:
    """Hamming-Abstand zweier (auch signierter) 64-Bit-Hashes."""
    return ((a ^ b) & 0xFFFFFFFFFFFFFFFF).bit_count()


def soll_aufnehmen(letzter: int | None, neu: int, letzte_zeit: datetime | None,
                   jetzt: datetime, anzahl: int) -> bool:
    if letzter is None:
        return True
    if letzte_zeit is not None and jetzt - letzte_zeit < MIN_ABSTAND:
        return False
    schwelle = SCHWELLE_STARK if anzahl >= OBERGRENZE else SCHWELLE
    return abstand(letzter, neu) > schwelle


def beobachtung_soll() -> list[dict]:
    return server._q(f"select uid, link from termin_akten where {_SOLL} order by beginn")


def ist_soll(uid: str) -> bool:
    return bool(server._q(f"select 1 from termin_akten where uid = %s and {_SOLL}", (uid,)))


def _verkleinern(jpeg: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(jpeg)) as bild:
        bild = bild.convert("RGB")
        if bild.width > MAX_BREITE:
            hoehe = max(1, round(bild.height * MAX_BREITE / bild.width))
            bild = bild.resize((MAX_BREITE, hoehe), Image.LANCZOS)
        out = io.BytesIO()
        bild.save(out, "JPEG", quality=_JPEG_QUALITAET)
        return out.getvalue(), bild.width, bild.height


def bild_ablegen(uid: str, jpeg: bytes, zeitpunkt: datetime,
                 geteilt_von: str | None) -> str | None:
    """Legt ein Bild ab und schliesst das vorige offene; None, wenn nicht (mehr) soll."""
    daten, breite, hoehe = _verkleinern(jpeg)
    hash_ = dhash(daten)
    name = (geteilt_von or "").strip()[:_NAME_MAX] or None
    with server.pool.connection() as conn:
        if not conn.execute("select 1 from termin_akten where uid = %s for update",
                            (uid,)).fetchall():
            return None
        if not conn.execute(f"select 1 from termin_akten where uid = %s and {_SOLL}",
                            (uid,)).fetchall():
            return None
        conn.execute("update termin_bilder set bis = %s where uid = %s and bis is null",
                     (zeitpunkt, uid))
        zeilen = conn.execute(
            "insert into termin_bilder (uid, aufgenommen_am, geteilt_von, bild, breite, "
            "hoehe, dhash) values (%s, %s, %s, %s, %s, %s, %s) returning id",
            (uid, zeitpunkt, name, daten, breite, hoehe, hash_)).fetchall()
    return str(_erste(zeilen[0]))


def _erste(zeile):
    return zeile["id"] if isinstance(zeile, dict) else zeile[0]


def freigabe_ende(uid: str, zeitpunkt: datetime) -> None:
    server._q("update termin_bilder set bis = %s where uid = %s and bis is null "
              "returning id", (zeitpunkt, uid))


def bilder(uid: str) -> list[dict]:
    return server._q(
        "select id, uid, aufgenommen_am, bis, geteilt_von, breite, hoehe, dhash, "
        "beschreibung, beschreibung_status, beschreibung_versuche, erstellt_am "
        "from termin_bilder where uid = %s order by aufgenommen_am, erstellt_am", (uid,))


def bild_daten(uid: str, bild_id: str) -> bytes | None:
    z = server._q("select bild from termin_bilder where uid = %s and id = %s",
                  (uid, bild_id))
    return bytes(z[0]["bild"]) if z else None


def bild_loeschen(uid: str, bild_id: str) -> bool:
    return bool(server._q("delete from termin_bilder where uid = %s and id = %s "
                          "returning id", (uid, bild_id)))


def bilder_zeilen(uid: str) -> list[tuple[datetime, str]]:
    """(Aufnahmezeit, Beschreibung) der fertig beschriebenen Bilder, fuer die Auswertung."""
    z = server._q("select aufgenommen_am, beschreibung from termin_bilder "
                  "where uid = %s and beschreibung_status = 'fertig' "
                  "and coalesce(beschreibung, '') <> '' "
                  "order by aufgenommen_am, erstellt_am", (uid,))
    return [(r["aufgenommen_am"], r["beschreibung"]) for r in z]


def _beginn(segment: dict) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(segment.get("beginn") or "").strip()
                                   .replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def bilder_zu_abschnitt(segmente: list[dict], von: int, bis: int,
                        bilder: list[dict]) -> list[str]:
    """Ids der Bilder, die ab Beginn von Segment `von` bis Ende von Segment `bis` entstanden.

    Das Ende ist der Beginn des naechsten Segments mit lesbarer Zeit (offen beim letzten).
    Ohne lesbaren Beginn ab `von` ist kein Zeitraum bestimmbar: leere Liste."""
    if not segmente or von > bis:
        return []
    von = max(von, 0)
    anfang = next((b for b in map(_beginn, segmente[von:bis + 1]) if b), None)
    if anfang is None:
        return []
    ende = next((b for b in map(_beginn, segmente[bis + 1:]) if b), None)
    return [str(b["id"]) for b in bilder
            if b["aufgenommen_am"] >= anfang and (ende is None or b["aufgenommen_am"] < ende)]
