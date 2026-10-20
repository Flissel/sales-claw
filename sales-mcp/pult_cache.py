"""Gemeinsamer Zwischenspeicher der Pult-Abschnitte auf /freigaben (Marketing:
ui_freigabe_newsletter, Bewerbungen: ui_freigabe_bewerbung).

Beide Abschnitte lesen eine entfernte Pult-API. Gemerkt werden die Zahl fuer den
Menue-Zaehler und der Ausgang der letzten Lesung, beides ALTER_S gueltig:
  - Der Menue-Zaehler geht nie selbst ins Netz (der Render-Weg laeuft im
    Event-Loop). Er liest nur diesen Speicher; ist der veraltet, frischt ihn ein
    Hintergrund-Thread auf (hoechstens einer je Speicher).
  - Ist die letzte Lesung gescheitert, versucht der Abschnitt es bis ALTER_S
    nicht erneut - eine tote API laesst nicht jede Seite warten. Gemerkt wird
    die Art des Fehlschlags (z.B. PultFehler.art), damit der Hinweis stimmt."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

ALTER_S = 60


class PultCache:
    def __init__(self, thread_name: str):
        self._lock = threading.Lock()
        self._stand: float | None = None
        self._wert = 0
        self._fehler: str | None = None
        self._thread_name = thread_name
        # Ein dict statt eines Attributs: die Tests setzen den Eintrag per
        # monkeypatch.setitem (tests/test_freigabe_newsletter.py).
        self.laeuft: dict = {"thread": None}

    def _frisch(self) -> bool:
        return self._stand is not None and time.monotonic() - self._stand < ALTER_S

    def leeren(self) -> None:
        with self._lock:
            self._stand, self._wert, self._fehler = None, 0, None

    def merken(self, wert: int, fehler: str | None = None) -> None:
        """Ausgang einer Lesung: `fehler` None heisst gelungen, sonst die Art des Fehlschlags."""
        with self._lock:
            self._stand, self._wert, self._fehler = time.monotonic(), wert, fehler

    def frisch_fehler(self) -> str | None:
        """Die Art des Fehlschlags, wenn die letzte Lesung juenger als ALTER_S ist und
        scheiterte - sonst None (gelungen, veraltet oder nie gelesen)."""
        with self._lock:
            return self._fehler if self._frisch() else None

    def anzahl(self, laden: Callable[[], object]) -> int:
        """Die gemerkte Zahl, ohne Netz. Ist sie veraltet (oder fehlt), startet `laden`
        (blockierend, soll selbst `merken` rufen) in einem Hintergrund-Thread."""
        with self._lock:
            wert, frisch = int(self._wert), self._frisch()
        if not frisch:
            t = self.laeuft["thread"]
            if t is None or not t.is_alive():
                t = threading.Thread(target=laden, daemon=True, name=self._thread_name)
                self.laeuft["thread"] = t
                t.start()
        return wert
