"""Heikel-Erkennung Schicht A (Bildauswertung live): Abstand zwischen heikel und neutral."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import heikel  # noqa: E402


def _achse(i: int, wert: float = 1.0) -> list[float]:
    v = [0.0] * 512
    v[i] = wert
    return v


class Attrappe:
    """Feste Vektoren: heikle Klassen auf Achse 0, neutrale auf Achse 1; das Bild
    (jpeg-Bytes sind die Steuerung) liegt zwischen beiden."""

    def __init__(self):
        self.text_aufrufe = []
        self.bild_aufrufe = 0

    def text_clip(self, text):
        self.text_aufrufe.append(text)
        return _achse(0 if text in heikel.KLASSEN_HEIKEL else 1)

    def bild(self, jpeg):
        self.bild_aufrufe += 1
        v = [0.0] * 512
        if jpeg == b"heikel":
            v[0], v[1] = 0.9, 0.1
        elif jpeg == b"neutral":
            v[0], v[1] = 0.1, 0.9
        else:                            # knapp: Abstand 0.02
            v[0], v[1] = 0.51, 0.49
        return v

    def text(self, text):
        return [0.0] * 384


def test_heikel_ueber_abstand():
    p = heikel.Pruefer(Attrappe(), abstand=0.05)
    ist, vektor = p.heikel(b"heikel")
    assert ist is True
    assert len(vektor) == 512


def test_neutral_unter_abstand():
    p = heikel.Pruefer(Attrappe(), abstand=0.05)
    assert p.heikel(b"neutral")[0] is False
    assert p.heikel(b"knapp")[0] is False        # 0.02 < 0.05
    assert heikel.Pruefer(Attrappe(), abstand=0.01).heikel(b"knapp")[0] is True


def test_textvektoren_nur_einmal():
    e = Attrappe()
    p = heikel.Pruefer(e, abstand=0.05)
    n = len(e.text_aufrufe)
    assert n == len(heikel.KLASSEN_HEIKEL) + len(heikel.KLASSEN_NEUTRAL)
    p.heikel(b"heikel")
    p.heikel(b"neutral")
    assert len(e.text_aufrufe) == n
    assert e.bild_aufrufe == 2


def test_klassentexte_und_vorgabe():
    assert "an email inbox with a list of messages" in heikel.KLASSEN_HEIKEL
    assert "a presentation slide" in heikel.KLASSEN_NEUTRAL
    assert 0 < heikel.ABSTAND < 0.2
