"""Wiederkehrende Seitenbausteine von sales-ui (Design-Review S3, Plan
2026-10-19-design-s3-s4.md E2): Reiter und Seitenblättern.

Nur reine Funktionen: kein `import ui`, kein DB-Zugriff. Wer sie aufruft,
liefert die fertigen Adressen (aus geprüften Werten gebaut); hier wird alles
Fremde mit `html.escape(quote=True)` behandelt, wie `ui._e`. Das CSS steht im
einen Stylesheet `ui._STIL`.
"""
from __future__ import annotations

import html
from typing import Callable


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert), quote=True)


def reiter(eintraege: list[tuple[str, str, int | None]], aktiv: str,
           url: Callable[[str], str]) -> str:
    """Reiterleiste als Links: `(schluessel, name, zahl)` je Eintrag. Der
    aktive trägt `aria-current="page"` (zweites Merkmal neben der Farbe);
    eine Zahl `None` wird weggelassen."""
    teile = []
    for schluessel, name, zahl in eintraege:
        aktuell = ' aria-current="page"' if schluessel == aktiv else ""
        zusatz = "" if zahl is None else f' <span class="zahl">{int(zahl)}</span>'
        teile.append(f'<a href="{_e(url(schluessel))}"{aktuell}>{_e(name)}{zusatz}</a>')
    return f'<nav class="reiter" aria-label="Bereiche">{"".join(teile)}</nav>'


def blaettern(seite: int, letzte: int, url: Callable[[int], str]) -> str:
    """Seitenblättern wie in der Kontaktliste: nichts bei nur einer Seite,
    sonst Zurück/Weiter um „Seite S von L“. `seite` ist schon geklemmt."""
    if letzte <= 1:
        return ""
    zurueck = f'<a href="{_e(url(seite - 1))}">← Zurück</a>' if seite > 1 else ""
    weiter = f'<a href="{_e(url(seite + 1))}">Weiter →</a>' if seite < letzte else ""
    return (f'<nav class="filterleiste" aria-label="Seiten">{zurueck}'
            f'<span class="meta">Seite {int(seite)} von {int(letzte)}</span>{weiter}</nav>')
