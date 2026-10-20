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
from collections.abc import Mapping

from starlette.responses import RedirectResponse
from starlette.routing import Route

import server
import struktur

# E7: ab dieser Länge kürzt das SVG den Namen (Spalte 120 px); voll im <title>.
_KURZ_AB, _KURZ_AUF = 15, 13
# Grundlinie des Namens unter dem Kreisrand (px).
_NAME_ABSTAND = 16


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


def _kurzname(name: str) -> str:
    return name[:_KURZ_AUF] + "…" if len(name) >= _KURZ_AB else name


def svg_zeichnen(baum: struktur.Baum) -> str:
    """Der Baum als Inline-SVG (E6). Keine Farben, keine style=-Attribute:
    gestaltet wird nur über Klassen im Stylesheet (`ui._STIL`)."""
    a = struktur.anordnen(baum)
    r = struktur.RADIUS
    teile = [f'<svg class="struktur-svg" xmlns="http://www.w3.org/2000/svg" '
             f'width="{a.breite}" height="{a.hoehe}" viewBox="0 0 {a.breite} {a.hoehe}" '
             f'role="img" aria-label="Struktur: wer wen eingeladen hat">']
    for name in sorted(baum.einlader):
        eltern = baum.einlader[name]
        x1, y1 = a.punkte[eltern]
        # Sichtprüfung 20.10.: unter einem Laden steht sein Name - die Kante
        # beginnt deshalb unter dem Namen, sonst kreuzt sie die Schrift.
        y1 += r if eltern is None else r + _NAME_ABSTAND + 6
        x2, y2 = a.punkte[name]
        teile.append(f'<line class="kante" x1="{x1:g}" y1="{y1:g}" '
                     f'x2="{x2:g}" y2="{y2 - r:g}"/>')
    x, y = a.punkte[None]
    teile.append(f'<g class="knoten wurzel"><title>Ich</title>'
                 f'<circle cx="{x:g}" cy="{y:g}" r="{r}"/>'
                 f'<text class="zahl" x="{x:g}" y="{y:g}">Ich</text></g>')
    for name in sorted(baum.ebene, key=lambda n: (baum.ebene[n], n)):
        n = baum.ebene[name]
        x, y = a.punkte[name]
        teile.append(f'<g class="knoten ebene-{n}"><title>{_e(name)} – Ebene {n}</title>'
                     f'<circle cx="{x:g}" cy="{y:g}" r="{r}"/>'
                     f'<text class="zahl" x="{x:g}" y="{y:g}">{n}</text>'
                     f'<text class="name" x="{x:g}" y="{y + r + _NAME_ABSTAND:g}">{_e(_kurzname(name))}</text></g>')
    teile.append("</svg>")
    return "".join(teile)


def liste_zeichnen(baum: struktur.Baum, csrf: str,
                   gespeichert: Mapping[str, str | None] | None = None) -> str:
    """Derselbe Baum als verschachtelte Liste (immer volle Namen).

    `gespeichert` ist die Zuordnung aus `laeden_lesen`; aus ihr kommt bei
    verwaisten Läden der Name des nicht gefundenen Einladers (E5)."""
    gespeichert = gespeichert or {}

    def zweig(eltern: str | None) -> str:
        kinder = baum.kinder.get(eltern, ())
        if not kinder:
            return ""
        teile = ["<ul>"]
        for name in kinder:
            teile.append(f'<li><span class="ebene-zahl">{baum.ebene[name]}</span> '
                         f'<b>{_e(name)}</b>')
            if name in baum.verwaist:
                alt = gespeichert.get(name)
                wer = f"Einlader „{_e(alt)}“" if alt else "Einlader"
                teile.append(f' <span class="meta">{wer} nicht gefunden – hängt '
                             f'vorläufig direkt unter dir.</span>')
            # Task 4: umhängen. Der Laden selbst und seine Nachfahren fehlen
            # in der Auswahl (E9); zu tiefe Ziele lehnt erst der Server ab.
            ohne = struktur.nachfahren(baum, name) | {name}
            teile.append(
                '<form method="post" action="/team/struktur/einlader" class="einlader-form">'
                f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
                f'<input type="hidden" name="name" value="{_e(name)}">'
                f'<label>Einlader ändern {einlader_wahl(baum, baum.einlader[name], ohne)}</label>'
                '<button type="submit">Ändern</button></form>')
            teile.append(zweig(name))
            teile.append("</li>")
        teile.append("</ul>")
        return "".join(teile)

    return f'<ul class="struktur-liste"><li class="wurzel">Ich{zweig(None)}</li></ul>'


def routen(ui) -> list:
    """Die Seite /team/struktur. `ui` wird hereingereicht, nie importiert."""

    @ui._gesichert_seite
    async def seite(request):
        with server.pool.connection() as conn:
            laeden = laeden_lesen(conn)
        baum = struktur.baum_bauen(laeden)
        if not laeden:
            rumpf = ('<p class="leer-hinweis">Noch keine Mitglieder. Sobald du einen '
                     'Laden anlegst, erscheint er hier. '
                     '<a href="/team/laden-anlegen">Laden anlegen</a></p>')
        else:
            rumpf = ('<p class="meta">Wer wen eingeladen hat. Ebene 1 = von dir '
                     f'eingeladen, höchstens {struktur.MAX_EBENE} Ebenen.</p>'
                     f'<div class="struktur"><div class="struktur-graph">{svg_zeichnen(baum)}</div>'
                     f'{liste_zeichnen(baum, ui.CSRF_TOKEN, laeden)}</div>')
        return ui._seite("Struktur", rumpf)

    @ui._gesichert_seite
    async def einlader(request):
        """Einen Laden samt Teilbaum umhängen. Prüfen und Schreiben in einer
        Transaktion mit gesperrten erfolg-Zeilen (E10); geschrieben wird nur
        `eingeladen_von`, auf ALLEN erfolg-Zeilen dieses Namens (E1/E3)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(
                400, "Ungültige Anfrage",
                "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
                "Seite neu laden und erneut versuchen.")
        name = str(form.get("name") or "").strip()
        neu = str(form.get("einlader") or "").strip() or None
        with server.pool.connection() as conn:
            baum = struktur.baum_bauen(laeden_lesen(conn, sperren=True))
            text = struktur.fehler_umhaengen(baum, name, neu)
            if text:
                return ui._fehlerseite(400, "Einlader nicht geändert",
                                       ui._e(text) + " Nichts wurde geändert.")
            conn.execute(
                "update admin_auftraege set eingeladen_von = %s "
                "where art = 'laden_anlegen' and status = 'erfolg' and name = %s",
                (neu, name))
        return RedirectResponse("/team/struktur", status_code=303)

    return [Route("/team/struktur", seite),
            Route("/team/struktur/einlader", einlader, methods=["POST"])]
