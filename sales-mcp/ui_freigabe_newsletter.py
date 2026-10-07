"""Marketing-Inhalte in den Sales-Freigaben (Plan 2026-10-07, Task 4, R7).

Auf /freigaben steht unter den Sales-Arten ein Abschnitt "Marketing": alle
zur Freigabe eingereichten Inhalte (Newsletter, Post, Team-Material) aller
Firmen, je mit Firmen- und Art-Etikett, Vorschau-Rahmen und den Knoepfen
Freigeben / Zurueckgeben. Die Daten und die Entscheidung gehoeren der
Marketing-API (Pult); diese Datei zeigt nur an und reicht weiter.

Wie der Rest von sales-ui: kein JavaScript (Seiten-CSP `default-src 'none'`).
Aufklappen per <details>, Mail/Handy per Verweis mit Abfrageparameter.
Faellt die API aus, zeigt der Abschnitt einen Hinweis - die Seite bleibt."""
from __future__ import annotations

import threading
import time
import urllib.parse
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import marketing_pult

ARTEN = {"newsletter": "Newsletter", "post": "Post", "material": "Team-Material"}
FORMATE = ("mail", "handy")
KOMMENTAR_MAX = 2000
ERLEDIGT_MAX = 3            # erledigte Rueckmeldungen je Karte
VERLAUF_MAX = 10
OFFEN_MAX = 100
ZAEHLER_ALTER_S = 60
ZAEHLER_ZEITLIMIT_S = 2

_EINGEREICHT = f"/freigaben?status=eingereicht&limit={OFFEN_MAX}"
_ENTSCHIEDEN = f"/freigaben?status=entschieden&limit={VERLAUF_MAX}"

_cache_lock = threading.Lock()
_cache: dict = {"stand": None, "wert": 0}


def _cache_leeren() -> None:
    with _cache_lock:
        _cache["stand"], _cache["wert"] = None, 0


def anzahl_offen() -> int:
    """Zahl der eingereichten Marketing-Inhalte fuer den Menue-Zaehler.
    60 s Zwischenspeicher (auch fuer den Fehlerfall - sonst wartete jede
    Seite bei toter API zwei Sekunden), Zeitlimit 2 s, jeder Fehler => 0."""
    jetzt = time.monotonic()
    with _cache_lock:
        if _cache["stand"] is not None and jetzt - _cache["stand"] < ZAEHLER_ALTER_S:
            return int(_cache["wert"])
    try:
        antwort = marketing_pult.anfrage("GET", _EINGEREICHT, zeitlimit=ZAEHLER_ZEITLIMIT_S)
        liste = antwort.get("freigaben") if isinstance(antwort, dict) else None
        wert = len(liste) if isinstance(liste, list) else 0
    except Exception:  # noqa: BLE001 - ein Zaehler darf nie die Seite reissen
        wert = 0
    with _cache_lock:
        _cache["stand"], _cache["wert"] = time.monotonic(), wert
    return wert


def _vor(iso) -> str:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    s = max(0, int((datetime.now(timezone.utc) - t).total_seconds()))
    if s < 3600:
        return f"{max(1, s // 60)} Min."
    if s < 86400:
        return f"{s // 3600} Std."
    return f"{s // 86400} Tg."


def _dicts(liste) -> list[dict]:
    return [x for x in (liste or []) if isinstance(x, dict)]


async def _lesen(pfad: str) -> list[dict]:
    antwort = await run_in_threadpool(marketing_pult.anfrage, "GET", pfad)
    return _dicts(antwort.get("freigaben") if isinstance(antwort, dict) else None)


def _etiketten(ui, f: dict) -> str:
    e = ui._e
    art = ARTEN.get(f.get("art"), f.get("art"))
    return (f'<span class="badge">{e(f.get("mandant_name") or f.get("mandant"))}</span>'
            f'<span class="badge">{e(art)}</span>')


def _karte(ui, f: dict, fmt: str) -> str:
    e = ui._e
    iid = urllib.parse.quote(str(f.get("id") or ""), safe="")
    fassung = f.get("eingereichte_fassung")
    nr = fassung if isinstance(fassung, int) and not isinstance(fassung, bool) else 1
    erledigt = [r for r in _dicts(f.get("rueckmeldungen")) if r.get("erledigt")][-ERLEDIGT_MAX:]
    rueck = ""
    if erledigt:
        zeilen = "".join(f'<li>{e(r.get("text"))} <span class="meta">- {e(r.get("von"))}</span></li>'
                         for r in erledigt)
        rueck = (f'<details class="bearbeiten"><summary>Erledigte Rückmeldungen ({len(erledigt)})'
                 f'</summary><ul>{zeilen}</ul></details>')
    wahl = "".join(
        f'<a class="{"aktiv" if k == fmt else ""}" href="/freigaben?nl_format={k}#marketing">'
        f'{"Mail" if k == "mail" else "Handy"}</a>' for k in FORMATE)
    betreff = f'<div>Betreff: <b>{e(f.get("betreff"))}</b></div>' if f.get("betreff") else ""
    basis = f"/freigaben/newsletter/{iid}"
    freigeben = (
        f'<form class="aktion primaer" method="post" action="{basis}/freigeben">'
        f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
        f'<input type="hidden" name="fassung" value="{nr}">'
        f'<label class="haken"><input type="checkbox" name="bestaetigt" value="ja"> '
        f'Fassung {nr} freigeben bestätigen</label>'
        f'<button class="primaer">Freigeben</button></form>')
    zurueck = (
        f'<form class="aktion" method="post" action="{basis}/zurueckgeben">'
        f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
        f'<input type="hidden" name="fassung" value="{nr}">'
        f'<textarea name="kommentar" required maxlength="{KOMMENTAR_MAX}" rows="3" '
        f'placeholder="Was fehlt?"></textarea>'
        f'<button>Zurückgeben</button></form>')
    return (
        f'<details class="karte"><summary>{_etiketten(ui, f)}<b>{e(f.get("titel"))}</b></summary>'
        f'{betreff}'
        f'<div class="meta">Fassung {nr} · eingereicht von {e(f.get("eingereicht_von"))} '
        f'vor {e(_vor(f.get("eingereicht_am")))}</div>'
        f'<div class="nl-vorschau"><div class="vorschau-wahl">{wahl}'
        f'<a href="/marketing/entwurf/{iid}">Im Editor ansehen</a></div>'
        f'<iframe class="vorschau {fmt}" sandbox title="Vorschau" '
        f'src="/marketing/entwurf/{iid}/vorschau?fassung={nr}&amp;format={fmt}"></iframe></div>'
        f'{rueck}<div class="aktionen">{freigeben}{zurueck}</div></details>')


def _verlauf_zeile(ui, f: dict) -> str:
    e = ui._e
    iid = urllib.parse.quote(str(f.get("id") or ""), safe="")
    kopf = f'{_etiketten(ui, f)}<b>{e(f.get("titel"))}</b>'
    wer = f' <span class="meta">{e(f.get("entschieden_von"))}</span>' if f.get("entschieden_von") else ""
    status = f.get("status")
    if status == "freigegeben":
        auftrag = (f.get("export") or {}).get("auftrag_status") if isinstance(f.get("export"), dict) else None
        if auftrag in ("offen", "in_arbeit"):
            zusatz = "Export läuft"
        elif auftrag == "fertig":
            zusatz = "Newsletter-Bilder fertig"
        elif f.get("art") == "newsletter":
            zusatz = (
                f'Export offen – erneut anstoßen <form class="aktion" method="post" '
                f'action="/freigaben/newsletter/{iid}/export-nachholen">'
                f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
                f'<button>Export anstoßen</button></form>')
        else:
            zusatz = ""
        text = f'freigegeben{wer} · {zusatz}' if zusatz else f'freigegeben{wer}'
    elif status == "abgelehnt":
        text = f'verworfen{wer} · {e(f.get("grund"))}'
    else:
        letzte = _dicts(f.get("rueckmeldungen"))
        kommentar = e(letzte[-1].get("text")) if letzte else ""
        text = f'zurückgegeben{wer} · {kommentar}'
    return f'<div class="karte">{kopf} <span class="meta">{text}</span></div>'


def _hinweis(ui, request) -> str:
    if request is None:
        return ""
    art = request.query_params.get("nl_hinweis")
    if art == "export_offen":
        return ('<div class="fehler">Freigegeben - aber der Export hat nicht geklappt. '
                'Export offen – erneut anstoßen (Knopf im Verlauf).</div>')
    if art == "ok":
        n = request.query_params.get("nl_flaechen", "")
        n = int(n) if n.isdigit() and len(n) < 6 else 0
        return f'<div class="hinweis">Freigegeben. Medien: {n} Flächen.</div>'
    return ""


async def abschnitt(ui, request=None) -> str:
    """HTML des Abschnitts "Marketing" (offene Karten + Verlauf)."""
    kopf = '<section class="block" id="marketing"><h2>Marketing '
    fmt = "mail"
    if request is not None and request.query_params.get("nl_format") in FORMATE:
        fmt = request.query_params["nl_format"]
    try:
        offen = await _lesen(_EINGEREICHT)
        verlauf = await _lesen(_ENTSCHIEDEN)
    except marketing_pult.PultFehler as f:
        text = ("Marketing nicht verbunden." if f.art == "nicht_verbunden"
                else "Marketing gerade nicht erreichbar.")
        return f'{kopf}</h2><p class="meta">{text} Sales läuft normal weiter.</p></section>'
    n = len(offen)
    teile = [f'{kopf}<span class="zaehler{" offen" if n else ""}">{n}</span></h2>',
             _hinweis(ui, request)]
    if not offen:
        teile.append('<p class="meta">Nichts zur Freigabe eingereicht.</p>')
    teile.extend(_karte(ui, f, fmt) for f in offen)
    teile.append('<h3 class="verlauftitel">Verlauf Marketing</h3>')
    teile.append("".join(_verlauf_zeile(ui, f) for f in verlauf[:VERLAUF_MAX])
                 or '<p class="meta">Noch nichts im Verlauf.</p>')
    teile.append("</section>")
    return "".join(teile)


def _fassung(roh) -> int | None:
    s = str(roh or "").strip()
    return int(s) if s.isdigit() and len(s) < 6 and int(s) >= 1 else None


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet "
                                   "oder der Schlüssel stimmt nicht. Nichts wurde getan.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Nichts wurde getan; "
                               "Sales läuft normal weiter.")

    def ziel(anker_abfrage: str = "") -> RedirectResponse:
        return RedirectResponse(f"/freigaben{anker_abfrage}#marketing", status_code=303)

    @ui._gesichert_seite
    async def freigeben(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        fassung = _fassung(form.get("fassung"))
        if fassung is None:
            return ui._fehlerseite(400, "Abgewiesen", "Welche Fassung gemeint ist, fehlt. "
                                   "Nichts wurde freigegeben - Seite neu laden.")
        if form.get("bestaetigt") != "ja":
            return ui._fehlerseite(400, "Nicht bestätigt", "Der Bestätigungshaken fehlt. "
                                   "Nichts wurde freigegeben.")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/freigeben",
                                        {"fassung": fassung, "von": ui._ui_akteur(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        _cache_leeren()
        r = r if isinstance(r, dict) else {}
        if r.get("export_fehler"):
            return ziel("?nl_hinweis=export_offen")
        flaechen = r.get("flaechen")
        n = len(flaechen) if isinstance(flaechen, list) else 0
        return ziel(f"?nl_hinweis=ok&nl_flaechen={n}")

    @ui._gesichert_seite
    async def zurueckgeben(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        fassung = _fassung(form.get("fassung"))
        if fassung is None:
            return ui._fehlerseite(400, "Abgewiesen", "Welche Fassung gemeint ist, fehlt. "
                                   "Nichts wurde zurückgegeben - Seite neu laden.")
        text = str(form.get("kommentar") or "").strip()
        if not text:
            return ui._fehlerseite(422, "Bitte sag kurz, was fehlt",
                                   "Bitte sag kurz, was fehlt. Nichts wurde zurückgegeben.")
        if len(text) > KOMMENTAR_MAX:
            return ui._fehlerseite(422, "Zu lang", f"Höchstens {KOMMENTAR_MAX} Zeichen. "
                                   "Nichts wurde zurückgegeben.")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/inhalte/{iid}/zurueckgeben",
                                    {"fassung": fassung, "von": ui._ui_akteur(request), "text": text})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        _cache_leeren()
        return ziel()

    @ui._gesichert_seite
    async def export_nachholen(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        iid = urllib.parse.quote(request.path_params["iid"], safe="")
        try:
            r = await run_in_threadpool(marketing_pult.anfrage, "POST",
                                        f"/inhalte/{iid}/export_nachholen", {})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        if isinstance(r, dict) and r.get("export_fehler"):
            return ziel("?nl_hinweis=export_offen")
        return ziel()

    return [
        Route("/freigaben/newsletter/{iid}/freigeben", freigeben, methods=["POST"]),
        Route("/freigaben/newsletter/{iid}/zurueckgeben", zurueckgeben, methods=["POST"]),
        Route("/freigaben/newsletter/{iid}/export-nachholen", export_nachholen, methods=["POST"]),
    ]
