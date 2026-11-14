"""Heikle Bildschirme lokal erkennen (Bildauswertung live, Schicht A).

Anmeldeseiten, Bezahlseiten und Postfaecher duerfen NIE in `termin_bilder`
landen. Der Pruefer vergleicht den CLIP-Bildvektor mit kurzen Klassentexten
(Zero-Shot, dasselbe Modell, das die Bildsuche ohnehin nutzt): heikel ist ein
Bild, wenn es einer heiklen Klasse um mehr als `abstand` aehnlicher ist als
jeder neutralen Klasse. Kein Bild und keine Beschreibung verlaesst den Prozess.
"""
from __future__ import annotations

import math
import os
from typing import Protocol

KLASSEN_HEIKEL = (
    "a login page with a password field",
    "a sign in with Google account chooser",
    "a payment checkout page with credit card fields",
    "an email inbox with a list of messages",
    "an opened email message",
)
KLASSEN_NEUTRAL = (
    "a presentation slide",
    "a website",
    "a document in a text editor",
    "a chat with an AI assistant",
    "a video call",
)


def _abstand_aus_umgebung(vorgabe: float) -> float:
    try:
        wert = float(os.environ.get("AUGE_HEIKEL_ABSTAND", "") or vorgabe)
    except ValueError:
        return vorgabe
    return wert if math.isfinite(wert) else vorgabe


# Kalibriert am 14.11.2026 (scripts/heikel_kalibrieren.py, Einmal-Container aus dem
# Produktionsdienst, lesend) an 356 Bildern der beiden Abnahme-Akten (61 heikel,
# 295 neutral; Wahrheit per Stichwort aus der Beschreibung): bei 0,045 trafen
# 9/61 = 14,8 % der heiklen Bilder bei 4/295 = 1,4 % Fehlalarmen (hoechste
# Trefferquote unter 2 %). Die Trefferquote ist NIEDRIG: Schicht A allein
# genuegt nicht, Schicht B (Beschreibung) muss mittragen. Zum Vergleich: bei 0,030
# 29,5 % Treffer, aber 6,1 % Fehlalarme; bei 0,000 75,4 % Treffer, 43,7 % Fehlalarme.
ABSTAND = _abstand_aus_umgebung(0.045)


class Einbetter(Protocol):
    def bild(self, jpeg: bytes) -> list[float]: ...        # 512
    def text_clip(self, text: str) -> list[float]: ...     # 512


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class Pruefer:
    """Textvektoren der Klassen werden einmal im Konstruktor berechnet."""

    def __init__(self, einbetter: Einbetter, abstand: float = ABSTAND) -> None:
        self._einbetter = einbetter
        self._abstand = abstand
        self._heikel = [einbetter.text_clip(t) for t in KLASSEN_HEIKEL]
        self._neutral = [einbetter.text_clip(t) for t in KLASSEN_NEUTRAL]

    def heikel(self, jpeg: bytes) -> tuple[bool, list[float]]:
        """(heikel?, Bildvektor); der Vektor wird beim Ablegen wiederverwendet."""
        v = self._einbetter.bild(jpeg)
        d = (max(_cos(v, t) for t in self._heikel)
             - max(_cos(v, t) for t in self._neutral))
        return d > self._abstand, v
