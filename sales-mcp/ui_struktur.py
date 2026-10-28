"""Struktur-Graph in sales-ui (Plan docs/superpowers/plans/2026-10-20-struktur-graph.md,
20.10.2026): welcher Laden von wem eingeladen wurde, und welches Level jedes
Mitglied hat.

Betreiber 20.10.2026: „die Ebenen sind die Level des einzelnen Mitarbeiters,
die Struktur ist das Einladungsverhältnis, es können unendlich viele Nodes
generiert werden – quasi ein Schneeball.“ Der Einladungsbaum hat deshalb
keine Tiefengrenze (nur Ringe sind verboten); das Level 1–6 ist ein Merkmal
des Mitglieds (Spalte `admin_auftraege.level`) und steht im Kreis.

Liest die angelegten Läden aus `admin_auftraege` (nur `status = 'erfolg'`, je
Name die jüngste Zeile, E1). Die Baum-Logik steht in `struktur.py`. Wie der
Rest von sales-ui ohne JavaScript; jeder Fremdwert geht durch
`html.escape(quote=True)`. `ui` wird nie importiert, sondern bei `routen(ui)`
hereingereicht.

Betreiber 20.10.: Läden mit `ergebnis->>'ausgeblendet' = 'true'` (Probe-Läden)
erscheinen nirgends; ihre Datenzeilen bleiben unverändert stehen.
"""
from __future__ import annotations

import html
import json
from collections.abc import Mapping
from pathlib import Path

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import server
import struktur
import ui_kalender

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


def mitglieder_lesen(conn, sperren: bool = False) -> dict[str, tuple[str | None, int]]:
    """Angelegte Läden -> (gespeicherter Einlader, Level).

    Je Name zählt die jüngste `erfolg`-Zeile (E1). Ist sie ausgeblendet,
    fehlt der Laden ganz. Mit `sperren=True` werden alle `erfolg`-Zeilen bis
    zum Ende der Transaktion gesperrt (E10); FOR UPDATE verträgt kein
    DISTINCT, deshalb wählt hier Python je Name die jüngste Zeile."""
    sql = ("select name, eingeladen_von, level, ergebnis from admin_auftraege "
           "where art = 'laden_anlegen' and status = 'erfolg' "
           "order by name, erstellt_am desc")
    if sperren:
        sql += " for update"
    mitglieder: dict[str, tuple[str | None, int]] = {}
    gesehen: set[str] = set()
    for z in conn.execute(sql).fetchall():
        if z["name"] in gesehen:
            continue
        gesehen.add(z["name"])
        if not _ausgeblendet(z["ergebnis"]):
            mitglieder[z["name"]] = (z["eingeladen_von"], int(z["level"]))
    return mitglieder


def laeden_lesen(conn, sperren: bool = False) -> dict[str, str | None]:
    """Angelegte Läden -> gespeicherter Einlader (None = Betreiber)."""
    return {n: e for n, (e, _) in mitglieder_lesen(conn, sperren).items()}


def einlader_wahl(baum: struktur.Baum, gewaehlt: str | None,
                  ohne: frozenset[str] = frozenset(),
                  level: Mapping[str, int] | None = None) -> str:
    """Auswahlfeld `einlader`: „Ich“ (Wert "") und jeder Laden nach Name,
    mit seinem Level. Läden in `ohne` fehlen (E9: beim Umhängen der Laden
    selbst und seine Nachfahren)."""
    level = level or {}
    teile = ['<select name="einlader" class="einlader-wahl">',
             '<option value="">Ich</option>']
    for name in sorted(baum.tiefe):
        if name in ohne:
            continue
        sel = " selected" if gewaehlt is not None and name == gewaehlt else ""
        teile.append(f'<option value="{_e(name)}"{sel}>{_e(name)} '
                     f'(Level {level.get(name, struktur.LEVEL_MIN)})</option>')
    teile.append("</select>")
    return "".join(teile)


def level_wahl(gewaehlt: int = struktur.LEVEL_MIN) -> str:
    """Auswahlfeld `level` mit Level 1..6, `gewaehlt` vorausgewählt."""
    teile = ['<select name="level" class="level-wahl">']
    for n in range(struktur.LEVEL_MIN, struktur.LEVEL_MAX + 1):
        sel = " selected" if n == gewaehlt else ""
        teile.append(f'<option value="{n}"{sel}>Level {n}</option>')
    teile.append("</select>")
    return "".join(teile)


def _kurzname(name: str) -> str:
    return name[:_KURZ_AUF] + "…" if len(name) >= _KURZ_AB else name


def svg_zeichnen(baum: struktur.Baum, level: Mapping[str, int] | None = None) -> str:
    """Der Baum als Inline-SVG (E6). Im Kreis steht das Level des Mitglieds;
    die Tiefe im Einladungsbaum ist die Reihe. Keine Farben, keine
    style=-Attribute: gestaltet wird nur über Klassen im Stylesheet
    (`ui._STIL`, Kreisfarbe je `level-N`). Breite und Höhe wachsen mit."""
    level = level or {}
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
        oben = y2 - r
        # Review 20.10.: Winkellinie (senkrecht - waagerecht - senkrecht).
        # Der Baum ist linksbündig, schräge Kanten liefen dort quer über
        # die Reihe; der waagerechte Teil liegt mitten zwischen den Reihen.
        ym = (y1 + oben) / 2
        teile.append(f'<path class="kante" d="M {x1:g} {y1:g} V {ym:g} '
                     f'H {x2:g} V {oben:g}"/>')
    x, y = a.punkte[None]
    teile.append(f'<g class="knoten wurzel"><title>Ich</title>'
                 f'<circle cx="{x:g}" cy="{y:g}" r="{r}"/>'
                 f'<text class="zahl" x="{x:g}" y="{y:g}">Ich</text></g>')
    for name in sorted(baum.tiefe, key=lambda n: (baum.tiefe[n], n)):
        tiefe = baum.tiefe[name]
        stufe = level.get(name, struktur.LEVEL_MIN)
        x, y = a.punkte[name]
        teile.append(f'<g class="knoten level-{stufe} tiefe-{tiefe}">'
                     f'<title>{_e(name)} – Level {stufe}</title>'
                     f'<circle cx="{x:g}" cy="{y:g}" r="{r}"/>'
                     f'<text class="zahl" x="{x:g}" y="{y:g}">{stufe}</text>'
                     f'<text class="name" x="{x:g}" y="{y + r + _NAME_ABSTAND:g}">{_e(_kurzname(name))}</text></g>')
    teile.append("</svg>")
    return "".join(teile)


def liste_zeichnen(baum: struktur.Baum, csrf: str,
                   gespeichert: Mapping[str, str | None] | None = None,
                   level: Mapping[str, int] | None = None) -> str:
    """Derselbe Baum als verschachtelte Liste (immer volle Namen), je Eintrag
    „Level N“ und zwei Formulare: Einlader ändern und Level setzen.

    Zwei getrennte Formulare statt einem (Entscheidung 20.10.): jedes POST
    ändert genau eine Sache, hat eine eigene Fehlerklasse (Ring = 400,
    Level außerhalb 1–6 = 422), und ein Level-Wechsel muss den Baum weder
    prüfen noch sperren.

    `gespeichert` ist die Zuordnung aus `laeden_lesen`; aus ihr kommt bei
    verwaisten Läden der Name des nicht gefundenen Einladers (E5). Ohne
    Rekursion gebaut, weil der Baum beliebig tief werden darf."""
    gespeichert = gespeichert or {}
    level = level or {}

    def eintrag(name: str) -> str:
        stufe = level.get(name, struktur.LEVEL_MIN)
        # Drag and Drop (Betreiber 28.10.2026): jeder Eintrag ist ziehbar und
        # Ziel; die Formulare darunter bleiben der Weg ohne Maus.
        teile = [f'<li draggable="true" data-name="{_e(name)}">'
                 f'<span class="level-chip level-{stufe}">Level {stufe}</span> '
                 f'<b>{_e(name)}</b>']
        if name in baum.verwaist:
            alt = gespeichert.get(name)
            wer = f"Einlader „{_e(alt)}“" if alt else "Einlader"
            teile.append(f' <span class="meta">{wer} nicht gefunden – hängt '
                         f'vorläufig direkt unter dir.</span>')
        # Umhängen: der Laden selbst und seine Nachfahren fehlen (E9).
        ohne = struktur.nachfahren(baum, name) | {name}
        teile.append(
            '<div class="laden-formulare">'
            '<form method="post" action="/team/struktur/einlader" class="einlader-form">'
            f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
            f'<input type="hidden" name="name" value="{_e(name)}">'
            f'<label>Einlader ändern {einlader_wahl(baum, baum.einlader[name], ohne, level)}</label>'
            '<button type="submit">Ändern</button></form>'
            '<form method="post" action="/team/struktur/level" class="level-form">'
            f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
            f'<input type="hidden" name="name" value="{_e(name)}">'
            f'<label>Level {level_wahl(stufe)}</label>'
            '<button type="submit">Setzen</button></form></div>')
        return "".join(teile)

    teile = ['<ul class="struktur-liste"><li class="wurzel" data-name="">Ich']
    stapel: list[tuple[str, str | None]] = [("kinder", None)]
    while stapel:
        art, k = stapel.pop()
        if art == "kinder":
            kinder = baum.kinder.get(k, ())
            if kinder:
                teile.append("<ul>")
                stapel.append(("ul_zu", None))
                stapel.extend(("li", kind) for kind in reversed(kinder))
        elif art == "li":
            teile.append(eintrag(k))
            stapel.append(("li_zu", None))
            stapel.append(("kinder", k))
        elif art == "ul_zu":
            teile.append("</ul>")
        else:
            teile.append("</li>")
    teile.append("</li></ul>")
    return "".join(teile)


# „Ich" unter einem hoeheren Knoten (Betreiber 28.10.2026: „Ivan ist mein
# hoeherer Knoten"). Der Einladungsbaum sagt nur, wer wen ins SYSTEM geholt
# hat; in der Geschaeftsstruktur kann ein solcher Laden UEBER dem Betreiber
# stehen. Gespeichert in der Tabelle einstellungen.
EINSTELLUNG_UEBER_MIR = "struktur_ueber_mir"
STATIK_JS = Path(__file__).resolve().parent / "static" / "struktur" / "struktur.js"


def ueber_mir_lesen(conn, mitglieder) -> str | None:
    z = conn.execute("select wert from einstellungen where schluessel = %s",
                     (EINSTELLUNG_UEBER_MIR,)).fetchone()
    name = (z["wert"] or {}).get("name") if z and isinstance(z["wert"], dict) else None
    return name if name in mitglieder else None


def ohne_ueber_mir(laeden: dict, ueber: str | None) -> dict:
    """Der Baum unter „Ich": der hoehere Knoten faellt heraus, wer an ihm
    hing, haengt jetzt direkt unter dem Betreiber."""
    if not ueber:
        return laeden
    return {n: (None if e == ueber else e) for n, e in laeden.items() if n != ueber}


def ueber_mir_zeichnen(ueber: str | None, level: Mapping[str, int], csrf: str,
                       namen) -> str:
    optionen = ['<option value="">— keiner —</option>'] + [
        f'<option value="{_e(n)}"{" selected" if n == ueber else ""}>{_e(n)}</option>'
        for n in sorted(namen)]
    knoten = (f'<div class="upline-knoten" data-name="{_e(ueber)}">'
              f'<span class="level-chip level-{level.get(ueber, struktur.LEVEL_MIN)}">'
              f'Level {level.get(ueber, struktur.LEVEL_MIN)}</span> <b>{_e(ueber)}</b>'
              f'<div class="meta">über mir</div></div><div class="upline-linie"></div>'
              if ueber else "")
    return ('<div class="upline" data-ziel="ueber">'
            f'{knoten}'
            '<form method="post" action="/team/struktur/ueber" class="upline-form">'
            f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
            f'<label>Mein höherer Knoten <select name="ueber">{"".join(optionen)}'
            '</select></label><button type="submit">Setzen</button></form>'
            '<p class="meta">Mitglieder per Ziehen umhängen: einen Eintrag auf einen '
            'anderen ziehen. Auf dieses Feld gezogen, wird er dein höherer Knoten.</p>'
            '</div>')


def routen(ui) -> list:
    """Die Seite /team/struktur. `ui` wird hereingereicht, nie importiert."""

    def ungueltig():
        return ui._fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")

    @ui._gesichert_seite
    async def seite(request):
        with server.pool.connection() as conn:
            mitglieder = mitglieder_lesen(conn)
            ueber = ueber_mir_lesen(conn, mitglieder)
        laeden = {n: e for n, (e, _) in mitglieder.items()}
        level = {n: s for n, (_, s) in mitglieder.items()}
        unter = ohne_ueber_mir(laeden, ueber)
        baum = struktur.baum_bauen(unter)
        if not laeden:
            rumpf = ('<p class="leer-hinweis">Noch keine Mitglieder. Sobald du einen '
                     'Laden anlegst, erscheint er hier. '
                     '<a href="/team/laden-anlegen">Laden anlegen</a></p>')
        else:
            rumpf = ('<p class="meta">Deine Struktur: über dir dein höherer Knoten, '
                     'unter dir jede Reihe eine Ebene weiter, beliebig tief. Im Kreis '
                     f'steht das Level des Mitglieds ({struktur.LEVEL_MIN}–'
                     f'{struktur.LEVEL_MAX}).</p>'
                     + ueber_mir_zeichnen(ueber, level, ui.CSRF_TOKEN, laeden)
                     + '<div class="struktur">'
                     f'<div class="struktur-graph">{svg_zeichnen(baum, level)}</div>'
                     f'{liste_zeichnen(baum, ui.CSRF_TOKEN, unter, level)}</div>'
                     # Versteckte Formulare fuer das Ziehen (struktur.js fuellt sie).
                     '<form method="post" action="/team/struktur/einlader?dnd=1" id="dnd-einlader" hidden>'
                     f'<input type="hidden" name="csrf" value="{_e(ui.CSRF_TOKEN)}">'
                     '<input type="hidden" name="name"><input type="hidden" name="einlader"></form>'
                     '<form method="post" action="/team/struktur/ueber" id="dnd-ueber" hidden>'
                     f'<input type="hidden" name="csrf" value="{_e(ui.CSRF_TOKEN)}">'
                     '<input type="hidden" name="ueber"></form>'
                     '<script src="/team/struktur/struktur.js" defer></script>')
        antwort = ui._seite("Struktur", rumpf)
        antwort.headers["Content-Security-Policy"] = ui_kalender.csp_kalender(ui)
        return antwort

    @ui._gesichert_seite
    async def skript(request):
        return Response(STATIK_JS.read_bytes(), media_type="text/javascript",
                        headers={"cache-control": "no-cache",
                                 "X-Content-Type-Options": "nosniff"})

    @ui._gesichert_seite
    async def ueber_setzen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ungueltig()
        name = str(form.get("ueber") or "").strip() or None
        with server.pool.connection() as conn:
            mitglieder = mitglieder_lesen(conn)
            if name is not None and name not in mitglieder:
                return ui._fehlerseite(400, "Nicht geändert",
                                       f"Den Laden „{ui._e(name)}“ gibt es nicht. "
                                       "Nichts wurde geändert.")
            conn.execute(
                "insert into einstellungen (schluessel, wert, geaendert_von) "
                "values (%s, %s, %s) on conflict (schluessel) do update set "
                "wert = excluded.wert, geaendert_am = now(), "
                "geaendert_von = excluded.geaendert_von",
                (EINSTELLUNG_UEBER_MIR, json.dumps({"name": name}),
                 ui._ui_akteur(request)))
        return RedirectResponse("/team/struktur", status_code=303)

    @ui._gesichert_seite
    async def einlader(request):
        """Einen Laden samt Teilbaum umhängen. Prüfen und Schreiben in einer
        Transaktion mit gesperrten erfolg-Zeilen (E10); geschrieben wird nur
        `eingeladen_von`, auf ALLEN erfolg-Zeilen dieses Namens (E1/E3)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ungueltig()
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

    @ui._gesichert_seite
    async def level_setzen(request):
        """Das Level eines Mitglieds setzen (Betreiber 20.10.2026). Nur 1–6,
        sonst 422; geschrieben wird nur `level`, auf ALLEN erfolg-Zeilen
        dieses Namens (wie beim Umhängen, E1)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return ungueltig()
        name = str(form.get("name") or "").strip()
        stufe = struktur.level_lesen(form.get("level"))
        if stufe is None:
            return ui._fehlerseite(
                422, "Level nicht geändert",
                f"Das Level ist eine Zahl von {struktur.LEVEL_MIN} bis "
                f"{struktur.LEVEL_MAX}. Nichts wurde geändert.")
        with server.pool.connection() as conn:
            # Ohne Sperre (Review 20.10.): ein Level-Wechsel kann keinen
            # Ring erzeugen und haengt von keinem anderen Laden ab.
            if name not in mitglieder_lesen(conn):
                return ui._fehlerseite(
                    400, "Level nicht geändert",
                    f"Den Laden „{ui._e(name)}“ gibt es nicht als angelegten "
                    "Laden. Nichts wurde geändert.")
            conn.execute(
                "update admin_auftraege set level = %s "
                "where art = 'laden_anlegen' and status = 'erfolg' and name = %s",
                (stufe, name))
        return RedirectResponse("/team/struktur", status_code=303)

    return [Route("/team/struktur", seite),
            Route("/team/struktur/struktur.js", skript),
            Route("/team/struktur/ueber", ueber_setzen, methods=["POST"]),
            Route("/team/struktur/einlader", einlader, methods=["POST"]),
            Route("/team/struktur/level", level_setzen, methods=["POST"])]
