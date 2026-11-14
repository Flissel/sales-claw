"""Mitschrift beim Ablegen bereinigen (Abnahme-Befunde 14.11.2026).

Vexa/Whisper liefert Halluzinationen ("Untertitel im Auftrag des ZDF"),
uneinheitliche Sprechernamen, Segmente ohne Sprecher und winzige Bruchstuecke.
Die Indizes der GESPEICHERTEN Mitschrift sind Bezug fuer Auswertung
(verlauf.von/bis) und Vorschaubilder - darum wird vor dem Insert bereinigt.

Segment-Schema unveraendert: sprecher, beginn, text, sprache. Die Eingabe wird
nie veraendert; es kommen neue dicts zurueck. Logs nur mit Zaehlern.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

LOG = logging.getLogger("sales-mcp.mitschrift_bereinigen")

MAX_LUECKE_FUELLEN_S = 3
MAX_LUECKE_VERBINDEN_S = 6
MAX_ZEICHEN_VERBUNDEN = 400
BETREIBER_STANDARD = "Felix Baumann"

_HALLUZINATIONEN = [re.compile(p) for p in (
    r"untertitel(ung)?( im auftrag)? (des|der|von) [\w .\-]+(, \d{4})?",
    r"untertitel der amara\.org-community",
    r"(vielen )?dank (fürs|für's|für das) zuschauen",
    r"copyright [\w .\-]+ \d{4}",
    r"(swr|wdr|ndr|br|zdf|ard)( \d{4})?",
)]
_RAND = re.compile(r"^[\W_]+|[\W_]+$")


def _ist_halluzination(text: str) -> bool:
    norm = _RAND.sub("", str(text).lower().strip())
    return bool(norm) and any(p.fullmatch(norm) for p in _HALLUZINATIONEN)


def _sekunden(beginn: object) -> float | None:
    """ISO-8601-Text (mit/ohne Z/Offset; ohne = UTC) oder Zahl -> Sekunden, sonst None."""
    if isinstance(beginn, bool):
        return None
    if isinstance(beginn, (int, float)):
        return float(beginn)
    if not isinstance(beginn, str) or not beginn.strip():
        return None
    try:
        t = datetime.fromisoformat(beginn.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()


def _betreiber_name(betreiber: str | None) -> str:
    if betreiber is None:
        return os.environ.get("BETREIBER_NAME", "").strip() or BETREIBER_STANDARD
    return betreiber.strip()


def _sprecher_abbilden(namen: list[str], betreiber: str) -> dict[str, str]:
    """Rohname -> vereinheitlichter Name (nur nicht-leere Namen)."""
    abbild = {n: n for n in set(namen) if n.strip()}
    if betreiber:
        erstes = betreiber.split()[0].lower()
        for n in abbild:
            if n.split()[0].lower() == erstes:
                abbild[n] = betreiber
    haeufig: dict[str, int] = {}
    for n in namen:
        if n in abbild:
            w = abbild[n]
            haeufig[w] = haeufig.get(w, 0) + 1
    mengen = {w: frozenset(w.lower().split()) for w in set(abbild.values())}

    def rang(w: str) -> tuple:
        return (len(mengen[w]), len(w), haeufig.get(w, 0), w)

    ziel: dict[str, str] = {}
    for w, m in mengen.items():
        kandidaten = [v for v, mv in mengen.items() if m <= mv]
        ziel[w] = max(kandidaten, key=rang)
    return {n: ziel[w] for n, w in abbild.items()}


def bereinigen(segmente: list[dict], betreiber: str | None = None) -> list[dict]:
    """Halluzinationen raus, Sprecher vereinheitlichen, Luecken fuellen, Bruchstuecke verbinden."""
    neu = [dict(s) for s in segmente]
    anfang = len(neu)

    # 1. Halluzinationen
    neu = [s for s in neu if not _ist_halluzination(s.get("text") or "")]
    entfernt = anfang - len(neu)

    # 2. Sprechernamen
    abbild = _sprecher_abbilden([str(s.get("sprecher") or "") for s in neu],
                                _betreiber_name(betreiber))
    for s in neu:
        roh = str(s.get("sprecher") or "")
        s["sprecher"] = abbild.get(roh, roh)

    zeit = [_sekunden(s.get("beginn")) for s in neu]

    # 3. Fehlenden Sprecher fuellen (Nachbarn aus dem Stand nach Schritt 2)
    sprecher = [s["sprecher"] for s in neu]
    for i in range(1, len(neu) - 1):
        if sprecher[i].strip():
            continue
        a, b = sprecher[i - 1], sprecher[i + 1]
        if not a.strip() or a != b:
            continue
        if None in (zeit[i - 1], zeit[i], zeit[i + 1]):
            continue
        if (abs(zeit[i] - zeit[i - 1]) <= MAX_LUECKE_FUELLEN_S
                and abs(zeit[i + 1] - zeit[i]) <= MAX_LUECKE_FUELLEN_S):
            neu[i]["sprecher"] = a

    # 4. Bruchstuecke verbinden (Abstand zum direkten Vorgaenger)
    aus: list[dict] = []
    letzte_zeit: float | None = None
    verbunden = 0
    for s, t in zip(neu, zeit):
        if (aus and s["sprecher"].strip() and aus[-1]["sprecher"] == s["sprecher"]
                and t is not None and letzte_zeit is not None
                and abs(t - letzte_zeit) <= MAX_LUECKE_VERBINDEN_S):
            text = " ".join(x for x in (str(aus[-1].get("text") or "").strip(),
                                        str(s.get("text") or "").strip()) if x)
            if len(text) <= MAX_ZEICHEN_VERBUNDEN:
                aus[-1]["text"] = text
                letzte_zeit = t
                verbunden += 1
                continue
        aus.append(s)
        letzte_zeit = t
    LOG.info("Mitschrift bereinigt: %d entfernt, %d verbunden", entfernt, verbunden)
    return aus
