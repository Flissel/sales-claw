"""Struktur-Graph in sales-ui (Plan docs/superpowers/plans/2026-10-20-struktur-graph.md,
20.10.2026): welcher Laden von wem eingeladen wurde, höchstens sechs Ebenen.

Liest die angelegten Läden aus `admin_auftraege` (nur `status = 'erfolg'`, je
Name die jüngste Zeile, E1) und baut daraus Auswahlfelder. Die Baum-Logik
selbst steht in `struktur.py`. Wie der Rest von sales-ui ohne JavaScript;
jeder Fremdwert geht durch `html.escape(quote=True)`. `ui` wird nie
importiert, sondern bei `routen(ui)` hereingereicht.

Betreiber 20.10.: Läden mit `ergebnis->>'ausgeblendet' = 'true'` (Probe-Läden)
erscheinen nirgends; ihre Datenzeilen bleiben unverändert stehen.
"""
from __future__ import annotations

import html

import struktur


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert), quote=True)


def _ausgeblendet(ergebnis) -> bool:
    """Dieselbe Bedeutung wie `ergebnis->>'ausgeblendet' = 'true'` in SQL:
    JSON-`true` oder die Zeichenkette "true"."""
    if not isinstance(ergebnis, dict):
        return False
    wert = ergebnis.get("ausgeblendet")
    return wert is True or wert == "true"


def laeden_lesen(conn, sperren: bool = False) -> dict[str, str | None]:
    """Angelegte Läden -> gespeicherter Einlader (None = Betreiber).

    Je Name zählt die jüngste `erfolg`-Zeile (E1). Ist sie ausgeblendet,
    fehlt der Laden ganz. Mit `sperren=True` werden alle `erfolg`-Zeilen bis
    zum Ende der Transaktion gesperrt (E10); FOR UPDATE verträgt kein
    DISTINCT, deshalb wählt hier Python je Name die jüngste Zeile."""
    sql = ("select name, eingeladen_von, ergebnis from admin_auftraege "
           "where art = 'laden_anlegen' and status = 'erfolg' "
           "order by name, erstellt_am desc")
    if sperren:
        sql += " for update"
    laeden: dict[str, str | None] = {}
    gesehen: set[str] = set()
    for z in conn.execute(sql).fetchall():
        if z["name"] in gesehen:
            continue
        gesehen.add(z["name"])
        if not _ausgeblendet(z["ergebnis"]):
            laeden[z["name"]] = z["eingeladen_von"]
    return laeden


def einlader_wahl(baum: struktur.Baum, gewaehlt: str | None,
                  ohne: frozenset[str] = frozenset()) -> str:
    """Auswahlfeld `einlader`: „Ich“ (Wert "") und jeder Laden, nach Ebene
    und Name sortiert. Läden in `ohne` fehlen (E9: beim Umhängen der Laden
    selbst und seine Nachfahren)."""
    teile = ['<select name="einlader" class="einlader-wahl">',
             '<option value="">Ich</option>']
    for name in sorted(baum.ebene, key=lambda n: (baum.ebene[n], n)):
        if name in ohne:
            continue
        sel = " selected" if gewaehlt is not None and name == gewaehlt else ""
        teile.append(f'<option value="{_e(name)}"{sel}>{_e(name)} '
                     f'(Ebene {baum.ebene[name]})</option>')
    teile.append("</select>")
    return "".join(teile)
