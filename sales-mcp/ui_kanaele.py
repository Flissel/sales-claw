"""Kanal-Statusseite /einstellungen/kanaele (Beitraege auf weitere Kanaele,
Spec docs/superpowers/specs/2026-10-24-kanaele-posten-design.md, Task 8,
24.10.2026).

Je Kanal der Registry eine Zeile: verbunden ja/nein (aus kanal_status, die
der Dienst sales-kanaele schreibt), letzter Beitrag mit Link, Kadenz und
Grenze. Bei "Nein" stehen die Env-NAMEN da und der Befehl, mit dem der
Betreiber den Zugang eintraegt.

Diese Seite liest KEINE Umgebung: "verbunden" kommt allein aus kanal_status
(Praezisierung 1), ein Zugangswert kann hier also gar nicht erscheinen. Jeder
Fremdwert (letzter_fehler, URL, Zeit) geht durch html.escape(quote=True).
Ein Link entsteht nur fuer eine URL mit https://. `ui` wird nie importiert,
sondern bei `routen(ui)` hereingereicht (Muster ui_struktur).
"""
from __future__ import annotations

import html

from starlette.routing import Route

import kanaele
import server

PFAD = "/einstellungen/kanaele"


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert), quote=True)


def _zeit(wert) -> str:
    return wert.strftime("%d.%m.%Y %H:%M") if hasattr(wert, "strftime") else ""


def letzte_beitraege(q) -> dict[str, dict]:
    """kanal -> {payload, created_at} des juengsten Belegs des Dienstes."""
    zeilen = q("select distinct on (payload->>'kanal') payload, created_at "
               "from activities where type = 'versand' "
               "and payload->>'weg' = 'kanal-dispatcher' "
               "order by payload->>'kanal', created_at desc")
    ergebnis: dict[str, dict] = {}
    for z in zeilen:
        payload = z["payload"] if isinstance(z["payload"], dict) else {}
        kanal = payload.get("kanal")
        if isinstance(kanal, str):
            ergebnis[kanal] = {"payload": payload, "created_at": z["created_at"]}
    return ergebnis


def _letzter_beitrag(beleg: dict | None) -> str:
    if not beleg:
        return "–"
    payload = beleg["payload"]
    zeit = _e(_zeit(beleg["created_at"]))
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("https://"):
        return f'{zeit} <a href="{_e(url)}" rel="noopener noreferrer">ansehen</a>'
    if payload.get("ungewiss"):
        return f"{zeit} ungewiss – auf dem Kanal nachsehen"
    return zeit or "–"


def _zeile(info: kanaele.KanalInfo, status: dict | None, beleg: dict | None) -> str:
    ist_verbunden = bool(status and status.get("verbunden"))
    verbunden = "Ja" if ist_verbunden else "Nein"
    if status and status.get("geprueft_am") is not None:
        verbunden += f'<br><span class="meta">geprüft am {_e(_zeit(status["geprueft_am"]))}</span>'
    grenze = f"{info.max_zeichen} Zeichen"
    if info.medien_max:
        grenze += f", mit Medien {info.max_zeichen_mit_medien}"
    hinweis = []
    if not ist_verbunden:
        namen = ", ".join(f"<code>{_e(n)}</code>" for n in info.env_namen)
        hinweis.append(f"Zugang fehlt: {namen}. Am PC speichern mit "
                       f"<code>kanal-zugang speichern {_e(info.name)}</code>")
    fehler = status.get("letzter_fehler") if status else None
    if fehler:
        hinweis.append(f'<span class="fehler">{_e(fehler)}</span>')
    return (f'<tr data-kanal="{_e(info.name)}"><td>{_e(info.anzeige)}</td>'
            f"<td>{verbunden}</td><td>{_letzter_beitrag(beleg)}</td>"
            f"<td>{info.kadenz_pro_tag}</td><td>{_e(grenze)}</td>"
            f'<td>{"<br>".join(hinweis) or "–"}</td></tr>')


def tabelle(status: dict[str, dict], belege: dict[str, dict]) -> str:
    zeilen = "".join(_zeile(info, status.get(k), belege.get(k))
                     for k, info in kanaele.KANAELE.items())
    return ('<div class="tabelle"><table><thead><tr><th>Kanal</th><th>Verbunden</th>'
            '<th>Letzter Beitrag</th><th>Kadenz/Tag</th><th>Grenze</th><th>Hinweis</th>'
            f'</tr></thead><tbody>{zeilen}</tbody></table></div>')


def routen(ui) -> list:
    """Die Seite /einstellungen/kanaele. `ui` wird hereingereicht, nie importiert."""

    @ui._gesichert_seite
    async def seite(request):
        status = kanaele.status_lesen(server._q)
        belege = letzte_beitraege(server._q)
        rumpf = ('<p class="meta">Eigene Beiträge auf weiteren Kanälen. Verbunden heißt: der '
                 'Dienst sales-kanaele hat einen gültigen Zugang. Ohne Zugang entsteht kein '
                 'Entwurf. dev.to-Beiträge werden dort nur als Entwurf angelegt.</p>'
                 + tabelle(status, belege))
        return ui._seite("Kanäle", rumpf)

    return [Route(PFAD, seite)]
