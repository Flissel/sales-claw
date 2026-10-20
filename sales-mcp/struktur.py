"""Struktur-Graph: wer welchen Laden eingeladen hat (Plan 2026-10-20-struktur-graph).

Reine Funktionen ohne Seiteneffekte: keine DB, kein ui. Eingabe ist eine
Zuordnung ``Laden -> gespeicherter Einlader`` (``None`` = Betreiber). Daraus
entstehen der wirksame Baum mit Tiefen (E5: unbekannte Einlader und Ringe in
den Daten werden deterministisch aufgebrochen), die Prüfungen für neue Läden
und fürs Umhängen (keine Ringe) und die Anordnung für das SVG (E6,
„Blatt-Spalten“).

Betreiber 20.10.2026: „die Ebenen sind die Level des einzelnen Mitarbeiters,
die Struktur ist das Einladungsverhältnis, es können unendlich viele Nodes
generiert werden – quasi ein Schneeball.“ Deshalb gibt es KEINE Tiefengrenze;
``Baum.tiefe`` ist die Tiefe im Einladungsbaum (Reihe im Graph). Das
Level (``LEVEL_MIN``..``LEVEL_MAX``) ist ein Merkmal des Mitglieds und steht in
der DB-Spalte ``admin_auftraege.level``.

Fehlertexte sind deutsche Sätze, unescaped und ohne „Nichts wurde …“; beides
ergänzt die Oberfläche.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

LEVEL_MIN, LEVEL_MAX = 1, 6
SPALTE, ZEILE, RADIUS, RAND = 120, 90, 18, 30


@dataclass(frozen=True)
class Baum:
    kinder: dict[str | None, tuple[str, ...]]  # None = Betreiber; Kinder nach Name sortiert; nur Eltern mit Kindern
    einlader: dict[str, str | None]            # WIRKSAMER Einlader je Laden (nach E5-Reparatur)
    tiefe: dict[str, int]                      # Tiefe im Baum: Kind des Betreibers = 1 (nicht das Level!)
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
    tiefe: dict[str, int] = {}
    verwaist: set[str] = set()

    def breitensuche(start: str | None, start_tiefe: int) -> None:
        schlange: deque[tuple[str | None, int]] = deque([(start, start_tiefe)])
        while schlange:
            knoten, e = schlange.popleft()
            for kind in roh_kinder.get(knoten, ()):
                if kind in tiefe:
                    continue
                einlader[kind] = knoten
                tiefe[kind] = e + 1
                schlange.append((kind, e + 1))

    breitensuche(None, 0)
    for name in sorted(laeden):
        if name in tiefe:
            continue
        einlader[name] = None
        tiefe[name] = 1
        verwaist.add(name)
        breitensuche(name, 1)

    kinder: dict[str | None, list[str]] = {}
    for name, e in einlader.items():
        kinder.setdefault(e, []).append(name)
    return Baum(
        kinder={k: tuple(sorted(v)) for k, v in kinder.items()},
        einlader=einlader,
        tiefe=tiefe,
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
    return max(baum.tiefe[n] for n in unten) - baum.tiefe[name]


def level_lesen(roh) -> int | None:
    """Formularwert -> Level ``LEVEL_MIN``..``LEVEL_MAX``, sonst None.
    Nur ASCII-Ziffern zählen (``int("³")`` o. Ä. wird nicht angenommen)."""
    text = str("" if roh is None else roh).strip()
    if not (text.isascii() and text.isdigit()):
        return None
    wert = int(text)
    return wert if LEVEL_MIN <= wert <= LEVEL_MAX else None


def fehler_neuer_laden(baum: Baum, einlader: str | None) -> str | None:
    """Fehlertext, falls ein neuer Laden nicht unter ``einlader`` darf, sonst None.
    Keine Tiefengrenze (Betreiber 20.10.2026) - nur der Einlader muss existieren."""
    if einlader is not None and einlader not in baum.tiefe:
        return f"„{einlader}“ gibt es nicht als angelegten Laden."
    return None


def fehler_umhaengen(baum: Baum, name: str, einlader: str | None) -> str | None:
    """Fehlertext, falls ``name`` samt Teilbaum nicht unter ``einlader`` darf, sonst None.
    Geprüft wird nur noch auf Ringe, nicht mehr auf Tiefe (Betreiber 20.10.2026)."""
    if name not in baum.tiefe:
        return f"Den Laden „{name}“ gibt es nicht als angelegten Laden."
    if einlader is not None and einlader not in baum.tiefe:
        return f"„{einlader}“ gibt es nicht als angelegten Laden."
    if einlader == name:
        return "Ein Laden kann sich nicht selbst einladen."
    if einlader is not None and einlader in nachfahren(baum, name):
        return (f"{name} kann nicht unter {einlader} hängen, weil {einlader} "
                f"selbst von {name} abstammt.")
    return None


def anordnen(baum: Baum) -> Anordnung:
    """Blatt-Spalten (E6): jedes Blatt eine Spalte, ein Elternteil steht über
    seinem ERSTEN Kind (linksbündig, Review 20.10.2026). So liegt „Ich“ immer
    links oben (x = RAND + SPALTE/2) und ist beim Öffnen eines breiten Baums
    sichtbar; mittig gesetzt läge die Wurzel außerhalb des Ausschnitts."""
    # Ohne Rekursion: der Baum darf beliebig tief werden (Betreiber
    # 20.10.2026), Pythons Rekursionsgrenze liegt bei ~1000.
    spalte: dict[str | None, float] = {}
    frei = 0
    stapel: list[tuple[str | None, bool]] = [(None, False)]
    while stapel:
        k, fertig = stapel.pop()
        ks = baum.kinder.get(k, ())
        if not ks:
            spalte[k] = frei
            frei += 1
        elif fertig:
            spalte[k] = spalte[ks[0]]
        else:
            stapel.append((k, True))
            stapel.extend((kind, False) for kind in reversed(ks))
    punkte: dict[str | None, tuple[float, float]] = {}
    for k, s in spalte.items():
        e = 0 if k is None else baum.tiefe[k]
        punkte[k] = (RAND + s * SPALTE + SPALTE / 2, RAND + RADIUS + e * ZEILE)
    max_tiefe = max(baum.tiefe.values(), default=0)
    return Anordnung(
        punkte=punkte,
        breite=max(1, frei) * SPALTE + 2 * RAND,
        hoehe=2 * RAND + 2 * RADIUS + max_tiefe * ZEILE + 20,
    )
