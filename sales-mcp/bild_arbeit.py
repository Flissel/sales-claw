"""Standbilder beschreiben, einbetten und durchsuchen (Bildauswertung live).

Ablauf je Bild: kurz beanspruchen (Versuch zaehlen, Zeitpunkt merken, KEINE
Zeilensperre waehrend der KI), zuerst den Bild-Vektor lokal berechnen und
schreiben (die Bildsuche braucht keine Beschreibung, Ruling R16), dann die
Beschreibung ueber das KI-Tor holen, Text-Vektor berechnen, Ergebnis mit
`update ... returning` schreiben. Wurde das Bild inzwischen geloescht
(Mitschrift-Loeschung), trifft das Update keine Zeile: still erledigt.

Neuversuche mit wachsender Pause ab dem letzten Versuch (R16): nach Versuch 1
30 s, nach Versuch 2 5 min; Versuch 3 ist der letzte.

Logs: nur gekuerzte uid, Fehlerart. Nie Beschreibungen, Prompts oder Bilddaten.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Protocol

import bildschirm
import ollama
import server

log = logging.getLogger("bild_arbeit")

MAX_VERSUCHE = 3
KI_TIMEOUT_S = 60
# Pause vor dem naechsten Versuch je Zahl bisheriger Versuche (R16).
PAUSE_NACH_VERSUCH_1 = "30 seconds"
PAUSE_NACH_VERSUCH_2 = "5 minutes"

BILD_PROMPT = (
    "Du siehst ein Standbild eines geteilten Bildschirms aus einem Termin. "
    "Beschreibe in höchstens 3 Sätzen auf Deutsch, was zu sehen ist: das Programm "
    "oder die Seite, lesbare Überschriften, die Kernaussagen und genannte Zahlen. "
    "Nenne keine Personen anhand ihres Aussehens. Erfinde nichts: nur, was lesbar "
    "oder eindeutig erkennbar ist. "
    "Zeigt das Bild eine Anmeldung mit Passwort- oder Kontoauswahl, eine Bezahlseite "
    "mit Karten- oder Kontodaten oder ein E-Mail-Postfach bzw. eine geöffnete E-Mail, "
    "antworte nur mit dem Wort HEIKEL."
)

# Antwort beginnt mit dem Wort HEIKEL (Satzzeichen danach ok; "Heikle ..." nicht).
# Anfuehrung/Markdown, in die kleine Modelle Ein-Wort-Antworten gern huellen.
_UMHUELLUNG = " \t\r\n\"'„“”*_`"
_HEIKEL = re.compile(r"^heikel\b", re.IGNORECASE)


class Einbetter(Protocol):
    def bild(self, jpeg: bytes) -> list[float]: ...        # 512
    def text_clip(self, text: str) -> list[float]: ...     # 512
    def text(self, text: str) -> list[float]: ...          # 384


def _h(uid: str) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def _literal(vektor: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vektor) + "]"


def _beanspruchen() -> dict | None:
    """Aeltestes offene Bild, dessen Pause abgelaufen ist; zaehlt den Versuch und
    setzt versucht_am. Die Zeilensperre (skip locked) gilt nur fuer dieses
    Statement, nie waehrend der KI (R5)."""
    zeilen = server._q(
        "update termin_bilder set beschreibung_versuche = beschreibung_versuche + 1, "
        "versucht_am = now() "
        "where id = (select id from termin_bilder "
        "where beschreibung_status in ('offen', 'fehler') and beschreibung_versuche < %s "
        "and (versucht_am is null or versucht_am <= now() - case "
        "  when beschreibung_versuche >= 2 then %s::interval else %s::interval end) "
        "order by aufgenommen_am, id for update skip locked limit 1) "
        "returning id, uid, bild, vektor_bild is not null as hat_vektor_bild",
        (MAX_VERSUCHE, PAUSE_NACH_VERSUCH_2, PAUSE_NACH_VERSUCH_1))
    return zeilen[0] if zeilen else None


def _fehler(bild_id, uid, e: Exception) -> str:
    server._q("update termin_bilder set beschreibung_status = 'fehler' "
              "where id = %s returning id", (bild_id,))
    log.warning("Bild beschreiben fehlgeschlagen uid=%s (%s)", _h(uid), type(e).__name__)
    return "fehler"


def _heikel_entfernen(bild_id, uid) -> str:
    """Die KI hat das Bild als heikel gemeldet: Zeile loeschen (Bild, Beschreibung und
    beide Vektoren verschwinden mit ihr), nichts davor oder danach schreiben. Zaehlt
    nur, wenn die Zeile noch da war (sonst war sie schon geloescht)."""
    geloescht = server._q("delete from termin_bilder where id = %s returning id", (bild_id,))
    if geloescht:
        bildschirm.uebersprungen_zaehlen(uid)
        log.info("Heikles Bild nach Beschreibung entfernt uid=%s", _h(uid))
    return "heikel"


def naechste_beschreiben(einbetter: Einbetter) -> bool:
    """Bearbeitet das aelteste offene Bild; True, wenn eines bearbeitet wurde."""
    return naechste_beschreiben_status(einbetter) is not None


def naechste_beschreiben_status(einbetter: Einbetter) -> str | None:
    """Wie `naechste_beschreiben`, liefert aber das Ergebnis: None (nichts offen),
    'fehler' (KI oder Einbettung gescheitert), 'heikel' (Bild entfernt) oder 'fertig'. Der Beobachter
    pausiert nach 'fehler', damit ein kurzer KI-Ausfall nicht alle Versuche
    verbrennt (Ruling R6)."""
    z = _beanspruchen()
    if z is None:
        return None
    bild_id, uid, jpeg = z["id"], z["uid"], bytes(z["bild"])
    # Zuerst der Bild-Vektor, unabhaengig von der KI: so ist das Bild auch bei
    # KI-Ausfall per Bildsuche auffindbar (R16).
    if not z["hat_vektor_bild"]:
        try:
            v_bild = _literal(einbetter.bild(jpeg))
        except Exception as e:  # noqa: BLE001
            return _fehler(bild_id, uid, e)
        server._q("update termin_bilder set vektor_bild = %s::public.vector "
                  "where id = %s returning id", (v_bild, bild_id))
    try:
        text = ollama.chat(BILD_PROMPT, "Beschreibe dieses Bild.",
                           timeout_s=KI_TIMEOUT_S, bilder=[jpeg]).strip()
        if _HEIKEL.match(text.strip(_UMHUELLUNG)):
            return _heikel_entfernen(bild_id, uid)
        if not text:
            raise ValueError("leere Beschreibung")
        v_text = _literal(einbetter.text(text))
    except Exception as e:  # noqa: BLE001
        return _fehler(bild_id, uid, e)
    gespeichert = server._q(
        "update termin_bilder set beschreibung = %s, beschreibung_status = 'fertig', "
        "vektor_text = %s::public.vector "
        "where id = %s returning id", (text, v_text, bild_id))
    if gespeichert:
        log.info("Bild beschrieben uid=%s", _h(uid))
    return "fertig"


def suchen(einbetter: Einbetter, text: str, uid: str | None = None,
           limit: int = 10) -> list[dict]:
    """Bilder per Text finden: bester Wert aus Bild-Vektor (CLIP) und Text-Vektor.
    Auch Bilder ohne Beschreibung (KI noch offen oder gescheitert) zaehlen, sobald
    ihr Bild-Vektor steht (R16); `greatest` ueberspringt den fehlenden Text-Vektor."""
    q_clip = _literal(einbetter.text_clip(text))
    q_text = _literal(einbetter.text(text))
    zeilen = server._q(
        "select id, uid, aufgenommen_am, beschreibung, score from ("
        " select id, uid, aufgenommen_am, beschreibung, greatest("
        "  1 - (vektor_bild OPERATOR(public.<=>) %s::public.vector),"
        "  1 - (vektor_text OPERATOR(public.<=>) %s::public.vector)) as score "
        " from termin_bilder where (vektor_bild is not null or vektor_text is not null) "
        "  and (%s::text is null or uid = %s)) t "
        "where score is not null order by score desc, aufgenommen_am, id limit %s",
        (q_clip, q_text, uid, uid, max(0, int(limit))))
    log.info("Bildsuche: %d Treffer", len(zeilen))
    return [{**z, "id": str(z["id"]), "score": float(z["score"])} for z in zeilen]
