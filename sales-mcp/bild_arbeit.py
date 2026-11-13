"""Standbilder beschreiben, einbetten und durchsuchen (Bildauswertung live).

Ablauf je Bild: kurz beanspruchen (Versuch zaehlen, KEINE Zeilensperre waehrend
der KI), Beschreibung ueber das KI-Tor holen, Vektoren lokal berechnen, Ergebnis
mit `update ... returning` schreiben. Wurde das Bild inzwischen geloescht
(Mitschrift-Loeschung), trifft das Update keine Zeile: still erledigt.

Logs: nur gekuerzte uid, Fehlerart. Nie Beschreibungen, Prompts oder Bilddaten.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Protocol

import ollama
import server

log = logging.getLogger("bild_arbeit")

MAX_VERSUCHE = 3
KI_TIMEOUT_S = 60

BILD_PROMPT = (
    "Du siehst ein Standbild eines geteilten Bildschirms aus einem Termin. "
    "Beschreibe in höchstens 3 Sätzen auf Deutsch, was zu sehen ist: das Programm "
    "oder die Seite, lesbare Überschriften, die Kernaussagen und genannte Zahlen. "
    "Nenne keine Personen anhand ihres Aussehens. Erfinde nichts: nur, was lesbar "
    "oder eindeutig erkennbar ist."
)


class Einbetter(Protocol):
    def bild(self, jpeg: bytes) -> list[float]: ...        # 512
    def text_clip(self, text: str) -> list[float]: ...     # 512
    def text(self, text: str) -> list[float]: ...          # 384


def _h(uid: str) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def _literal(vektor: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vektor) + "]"


def _beanspruchen() -> dict | None:
    zeilen = server._q(
        "update termin_bilder set beschreibung_versuche = beschreibung_versuche + 1 "
        "where id = (select id from termin_bilder "
        "where beschreibung_status in ('offen', 'fehler') and beschreibung_versuche < %s "
        "order by aufgenommen_am, id for update skip locked limit 1) "
        "returning id, uid, bild", (MAX_VERSUCHE,))
    return zeilen[0] if zeilen else None


def naechste_beschreiben(einbetter: Einbetter) -> bool:
    """Bearbeitet das aelteste offene Bild; True, wenn eines bearbeitet wurde."""
    z = _beanspruchen()
    if z is None:
        return False
    bild_id, uid, jpeg = z["id"], z["uid"], bytes(z["bild"])
    try:
        text = ollama.chat(BILD_PROMPT, "Beschreibe dieses Bild.",
                           timeout_s=KI_TIMEOUT_S, bilder=[jpeg]).strip()
        if not text:
            raise ValueError("leere Beschreibung")
        v_bild = _literal(einbetter.bild(jpeg))
        v_text = _literal(einbetter.text(text))
    except Exception as e:  # noqa: BLE001
        server._q("update termin_bilder set beschreibung_status = 'fehler' "
                  "where id = %s returning id", (bild_id,))
        log.warning("Bild beschreiben fehlgeschlagen uid=%s (%s)", _h(uid), type(e).__name__)
        return True
    gespeichert = server._q(
        "update termin_bilder set beschreibung = %s, beschreibung_status = 'fertig', "
        "vektor_bild = %s::public.vector, vektor_text = %s::public.vector "
        "where id = %s returning id", (text, v_bild, v_text, bild_id))
    if gespeichert:
        log.info("Bild beschrieben uid=%s", _h(uid))
    return True


def suchen(einbetter: Einbetter, text: str, uid: str | None = None,
           limit: int = 10) -> list[dict]:
    """Bilder per Text finden: bester Wert aus Bild-Vektor (CLIP) und Text-Vektor."""
    q_clip = _literal(einbetter.text_clip(text))
    q_text = _literal(einbetter.text(text))
    zeilen = server._q(
        "select id, uid, aufgenommen_am, beschreibung, score from ("
        " select id, uid, aufgenommen_am, beschreibung, greatest("
        "  1 - (vektor_bild OPERATOR(public.<=>) %s::public.vector),"
        "  1 - (vektor_text OPERATOR(public.<=>) %s::public.vector)) as score "
        " from termin_bilder where beschreibung_status = 'fertig' "
        "  and (%s::text is null or uid = %s)) t "
        "where score is not null order by score desc, aufgenommen_am, id limit %s",
        (q_clip, q_text, uid, uid, max(0, int(limit))))
    log.info("Bildsuche: %d Treffer", len(zeilen))
    return [{**z, "id": str(z["id"]), "score": float(z["score"])} for z in zeilen]
