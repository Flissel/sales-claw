"""Sichtbarkeit von Kalendertermin: Business/Privat (reines Modul, ohne DB).

Eigene Kalender sind voll sichtbar, fremde Business auch; fremde Privat
nur als Block mit dem Titel `Privattermin` und ohne Ort.
"""
from __future__ import annotations

PRIVATTERMIN = "Privattermin"


def details_speichern(besitzer: str, bereich: str, laden_besitzer: str) -> bool:
    """Darf der Titel/Ort dieser Quelle gespeichert werden?"""
    if bereich != "privat":
        return True
    return laden_besitzer != "" and besitzer == laden_besitzer


def maskiert(besitzer: str, bereich: str, betrachter: str) -> bool:
    """Sieht der Betrachter nur den Privattermin-Block?"""
    return bereich == "privat" and (betrachter == "" or besitzer != betrachter)


def privat_name(besitzer: str) -> str:
    """Anzeigename fuer einen Kalender, dessen echten Namen der Betrachter nicht sehen darf."""
    return f"Privat ({besitzer})"


def anwenden(termine: list[dict], betrachter: str) -> list[dict]:
    """Maskiert und fuehrt Doppelte je Besitzer zusammen; Eingang bleibt unveraendert."""
    gruppen: list[dict] = []
    index: dict[tuple, int] = {}
    for t in termine:
        schluessel = []
        if t.get("uid"):
            schluessel.append((t["besitzer"], "uid", t["uid"]))
        if t.get("titel"):
            schluessel.append((t["besitzer"], "tripel", t["titel"], t["beginn"], t["ende"]))
        pos = next((index[k] for k in schluessel if k in index), None)
        if pos is None:
            pos = len(gruppen)
            gruppen.append({"basis": t, "kopien": []})
        for k in schluessel:
            index.setdefault(k, pos)
        gruppen[pos]["kopien"].append(t)

    ergebnis = []
    for g in gruppen:
        kopien = g["kopien"]
        maske = any(maskiert(k["besitzer"], k["bereich"], betrachter) for k in kopien)
        neu = dict(g["basis"])
        neu["maskiert"] = maske
        neu["frei"] = all(k["frei"] for k in kopien)
        neu["kalender"] = list(dict.fromkeys(k["quelle"] for k in kopien))
        if maske:
            neu["titel"] = PRIVATTERMIN
            neu["ort"] = ""
            # Auch der Kalendername ist privat: kein Anzeigename einer fremden
            # Privat-Quelle (und keiner zusammengefuehrten Kopie) im Ergebnis.
            neu["quelle"] = privat_name(neu["besitzer"])
            neu["kalender"] = []
        ergebnis.append(neu)
    ergebnis.sort(key=lambda x: x["beginn"])
    return ergebnis
