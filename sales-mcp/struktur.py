"""Struktur-Graph: wer welchen Laden eingeladen hat (Plan 2026-10-20-struktur-graph).

Reine Funktionen ohne Seiteneffekte: keine DB, kein ui. Eingabe ist eine
Zuordnung ``Laden -> gespeicherter Einlader`` (``None`` = Betreiber). Daraus
entstehen der wirksame Baum mit Ebenen (E5: unbekannte Einlader und Ringe in
den Daten werden deterministisch aufgebrochen), die Prüfungen für neue Läden
und fürs Umhängen (höchstens ``MAX_EBENE`` Ebenen, keine Ringe) und die
Anordnung für das SVG (E6, „Blatt-Spalten“).

Fehlertexte sind deutsche Sätze, unescaped und ohne „Nichts wurde …“; beides
ergänzt die Oberfläche.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

MAX_EBENE: int = 6
SPALTE, ZEILE, RADIUS, RAND = 120, 90, 18, 30


@dataclass(frozen=True)
class Baum:
    kinder: dict[str | None, tuple[str, ...]]  # None = Betreiber; Kinder nach Name sortiert; nur Eltern mit Kindern
    einlader: dict[str, str | None]            # WIRKSAMER Einlader je Laden (nach E5-Reparatur)
    ebene: dict[str, int]                      # Kind des Betreibers = 1
    verwaist: frozenset[str]                   # gespeicherter Einlader unbekannt oder Ring


@dataclass(frozen=True)
class Anordnung:
    punkte: dict[str | None, tuple[float, float]]  # Mittelpunkt je Knoten, None = Betreiber
    breite: int
    hoehe: int


def baum_bauen(laeden: Mapping[str, str | None]) -> Baum:
    """Baut den wirksamen Baum. Endet immer, auch bei kaputten Daten (E5)."""
    roh_kinder: dict[str | None, list[str]] = {}
    for name in sorted(laeden):
        e = laeden[name]
        if e is None or e in laeden:
            roh_kinder.setdefault(e, []).append(name)

    einlader: dict[str, str | None] = {}
    ebene: dict[str, int] = {}
    verwaist: set[str] = set()

    def breitensuche(start: str | None, start_ebene: int) -> None:
        schlange: deque[tuple[str | None, int]] = deque([(start, start_ebene)])
        while schlange:
            knoten, e = schlange.popleft()
            for kind in roh_kinder.get(knoten, ()):
                if kind in ebene:
                    continue
                einlader[kind] = knoten
                ebene[kind] = e + 1
                schlange.append((kind, e + 1))

    breitensuche(None, 0)
    for name in sorted(laeden):
        if name in ebene:
            continue
        einlader[name] = None
        ebene[name] = 1
        verwaist.add(name)
        breitensuche(name, 1)

    kinder: dict[str | None, list[str]] = {}
    for name, e in einlader.items():
        kinder.setdefault(e, []).append(name)
    return Baum(
        kinder={k: tuple(sorted(v)) for k, v in kinder.items()},
        einlader=einlader,
        ebene=ebene,
        verwaist=frozenset(verwaist),
    )


def nachfahren(baum: Baum, name: str) -> frozenset[str]:
    """Alle Läden unterhalb von ``name`` (ohne ``name`` selbst)."""
    gefunden: set[str] = set()
    offen = list(baum.kinder.get(name, ()))
    while offen:
        k = offen.pop()
        if k in gefunden:
            continue
        gefunden.add(k)
        offen.extend(baum.kinder.get(k, ()))
    return frozenset(gefunden)


def teilbaum_tiefe(baum: Baum, name: str) -> int:
    """0 = keine Kinder; sonst wie viele Ebenen unter ``name`` noch folgen."""
    unten = nachfahren(baum, name)
    if not unten:
        return 0
    return max(baum.ebene[n] for n in unten) - baum.ebene[name]


def _ebene_von(baum: Baum, einlader: str | None) -> int:
    return 0 if einlader is None else baum.ebene[einlader]


def fehler_neuer_laden(baum: Baum, einlader: str | None) -> str | None:
    """Fehlertext, falls ein neuer Laden nicht unter ``einlader`` darf, sonst None."""
    if einlader is not None and einlader not in baum.ebene:
        return f"„{einlader}“ gibt es nicht als angelegten Laden."
    e = _ebene_von(baum, einlader)
    if e + 1 > MAX_EBENE:
        return (f"{einlader} steht auf Ebene {e}. Ein neuer Laden darunter läge auf "
                f"Ebene {e + 1}; erlaubt sind höchstens {MAX_EBENE} Ebenen.")
    return None


def fehler_umhaengen(baum: Baum, name: str, einlader: str | None) -> str | None:
    """Fehlertext, falls ``name`` samt Teilbaum nicht unter ``einlader`` darf, sonst None."""
    if name not in baum.ebene:
        return f"Den Laden „{name}“ gibt es nicht als angelegten Laden."
    if einlader is not None and einlader not in baum.ebene:
        return f"„{einlader}“ gibt es nicht als angelegten Laden."
    if einlader == name:
        return "Ein Laden kann sich nicht selbst einladen."
    if einlader is not None and einlader in nachfahren(baum, name):
        return (f"{name} kann nicht unter {einlader} hängen, weil {einlader} "
                f"selbst von {name} abstammt.")
    n = _ebene_von(baum, einlader) + 1 + teilbaum_tiefe(baum, name)
    if n > MAX_EBENE:
        return (f"Unter {einlader} läge der Teilbaum von {name} bis Ebene {n}; "
                f"erlaubt sind höchstens {MAX_EBENE} Ebenen.")
    return None


def anordnen(baum: Baum) -> Anordnung:
    """Blatt-Spalten (E6): jedes Blatt eine Spalte, Eltern mittig über ihren Kindern."""
    spalte: dict[str | None, float] = {}
    frei = 0

    def setze(k: str | None) -> None:
        nonlocal frei
        ks = baum.kinder.get(k, ())
        if not ks:
            spalte[k] = frei
            frei += 1
            return
        for kind in ks:
            setze(kind)
        spalte[k] = (spalte[ks[0]] + spalte[ks[-1]]) / 2

    setze(None)
    punkte: dict[str | None, tuple[float, float]] = {}
    for k, s in spalte.items():
        e = 0 if k is None else baum.ebene[k]
        punkte[k] = (RAND + s * SPALTE + SPALTE / 2, RAND + RADIUS + e * ZEILE)
    max_ebene = max(baum.ebene.values(), default=0)
    return Anordnung(
        punkte=punkte,
        breite=max(1, frei) * SPALTE + 2 * RAND,
        hoehe=2 * RAND + 2 * RADIUS + max_ebene * ZEILE + 20,
    )
