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
from functools import partial
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
LESE_ZEITLIMIT_S = 3
# Freigeben exportiert danach alle Flaechen x 3 Geraete auf der VM - wie die
# Gestaltung im Editor (ui_editor.GESTALTUNG_ZEITLIMIT_S) dauert das laenger als 8 s.
AKTION_ZEITLIMIT_S = 30
UNKLAR_TITEL = "Ergebnis unklar – Seite neu laden"

_EINGEREICHT = f"/freigaben?status=eingereicht&limit={OFFEN_MAX}"
_ENTSCHIEDEN = f"/freigaben?status=entschieden&limit={VERLAUF_MAX}"

_cache_lock = threading.Lock()
_cache: dict = {"stand": None, "wert": 0, "ok": True}
_laeuft = {"thread": None}


def _cache_leeren() -> None:
    with _cache_lock:
        _cache.update(stand=None, wert=0, ok=True)


def _merken(wert: int, ok: bool) -> None:
    with _cache_lock:
        _cache.update(stand=time.monotonic(), wert=wert, ok=ok)


def _frisch() -> bool:
    with _cache_lock:
        return _cache["stand"] is not None and time.monotonic() - _cache["stand"] < ZAEHLER_ALTER_S


def sichtbar(ui) -> bool:
    """Abschnitt und Zaehler gibt es nur, wenn die Marketing-API eingerichtet
    ist UND die angemeldete Rolle /marketing betreten darf - dieselbe Huerde
    wie das Pult (ui._pfad_erlaubt), Rolle aus derselben Quelle wie die
    Seitenleiste (ui._AKTIVE_ROLLE, gesetzt von _gesichert_seite)."""
    return marketing_pult.eingerichtet() and ui._pfad_erlaubt(ui._AKTIVE_ROLLE.get(), "/marketing")


def _laden() -> int:
    """Blockierend (nur im Thread/Threadpool aufrufen): holt die Zahl und
    merkt sie - auch den Fehlerfall, damit eine tote API nicht jede Seite
    warten laesst."""
    try:
        antwort = marketing_pult.anfrage("GET", _EINGEREICHT, zeitlimit=ZAEHLER_ZEITLIMIT_S)
        liste = antwort.get("freigaben") if isinstance(antwort, dict) else None
        wert = len(liste) if isinstance(liste, list) else 0
        _merken(wert, isinstance(liste, list))
    except Exception:  # noqa: BLE001 - ein Zaehler darf nie die Seite reissen
        wert = 0
        _merken(0, False)
    return wert


def anzahl_offen(ui) -> int:
    """Zahl der eingereichten Marketing-Inhalte fuer den Menue-Zaehler.
    NUR Zwischenspeicher: kein Netzwerk auf dem Render-Weg (der laeuft im
    Event-Loop). Ist der Speicher aelter als 60 s, stoesst ein Hintergrund-
    Thread die Auffrischung an; bis dahin gilt der alte Wert (leer => 0).
    Nicht sichtbar (s. sichtbar): 0, und es startet kein Thread."""
    if not sichtbar(ui):
        return 0
    with _cache_lock:
        wert = int(_cache["wert"])
    if not _frisch():
        t = _laeuft["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_laden, daemon=True, name="freigabe-zaehler")
            _laeuft["thread"] = t
            t.start()
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
    antwort = await run_in_threadpool(partial(marketing_pult.anfrage, "GET", pfad,
                                              zeitlimit=LESE_ZEITLIMIT_S))
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
        f'<details class="karte" open><summary>{_etiketten(ui, f)}<b>{e(f.get("titel"))}</b></summary>'
        f'{betreff}'
        f'<div class="meta">Fassung {nr} · eingereicht von {e(f.get("eingereicht_von"))} '
        f'vor {e(_vor(f.get("eingereicht_am")))}</div>'
        f'<div class="nl-vorschau"><div class="vorschau-wahl">{wahl}'
        f'<a href="/marketing/editor/{iid}">Im Editor ansehen</a></div>'
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
        elif f.get("art") == "newsletter" and f.get("format") != "felder":
            # Feld-Format: es gibt keinen Newsletter-Export und keine Flaechen - kein Knopf
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
        # Die API liefert die Rueckmeldungen neueste zuerst: die juengste nennt
        # Kommentar und wer zurueckgegeben hat (entschieden_von gilt hier nicht).
        letzte = _dicts(f.get("rueckmeldungen"))
        neueste = letzte[0] if letzte else {}
        kommentar = e(neueste.get("text")) if neueste else ""
        von = neueste.get("von")
        wer = f' <span class="meta">{e(von)}</span>' if von else ""
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
    """HTML des Abschnitts "Marketing" (offene Karten + Verlauf); "" wenn nicht sichtbar."""
    if not sichtbar(ui):
        return ""
    kopf ='<section class="block" id="marketing"><h2>Marketing '
    fmt = "mail"
    if request is not None and request.query_params.get("nl_format") in FORMATE:
        fmt = request.query_params["nl_format"]
    hinweis_weg = ('{k}</h2><p class="meta">Marketing gerade nicht erreichbar. '
                   'Sales läuft normal weiter.</p></section>')
    if _frisch() and not _cache["ok"]:
        return hinweis_weg.format(k=kopf)          # kuerzlich gescheitert: sofort
    try:
        offen = await _lesen(_EINGEREICHT)
        _merken(len(offen), True)
        verlauf = await _lesen(_ENTSCHIEDEN)
    except marketing_pult.PultFehler as f:
        _merken(0, False)
        if f.art == "nicht_verbunden":
            return (f'{kopf}</h2><p class="meta">Marketing nicht verbunden. '
                    f'Sales läuft normal weiter.</p></section>')
        return hinweis_weg.format(k=kopf)
    except Exception:  # noqa: BLE001 - die Seite darf daran nie scheitern
        _merken(0, False)
        return hinweis_weg.format(k=kopf)
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

    def fehler_nach_post(f: marketing_pult.PultFehler, was: str):
        """Freigeben/Export nachholen: lief die Anfrage ab (Zeitlimit, Verbindung weg, unklare
        Antwort), kann die Marketing-API sie trotzdem ausgefuehrt haben - nie "Nichts wurde getan"."""
        if f.art in ("nicht_erreichbar", "unbekannt"):
            return ui._fehlerseite(504, UNKLAR_TITEL,
                                   f"Die Marketing-API hat nicht rechtzeitig geantwortet. Ob {was}, "
                                   "ist offen - bitte die Freigaben-Seite neu laden und nachsehen.")
        return fehler(f)

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
            r = await run_in_threadpool(partial(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/freigeben",
                {"fassung": fassung, "von": ui._ui_akteur(request)}, zeitlimit=AKTION_ZEITLIMIT_S))
        except marketing_pult.PultFehler as f:
            return fehler_nach_post(f, "freigegeben wurde")
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
        # Browser schicken Zeilenumbrueche als CRLF - gezaehlt wird wie in der
        # textarea (maxlength) und in der DB: LF
        text = str(form.get("kommentar") or "").replace("\r\n", "\n").strip()
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
            r = await run_in_threadpool(partial(
                marketing_pult.anfrage, "POST", f"/inhalte/{iid}/export_nachholen", {},
                zeitlimit=AKTION_ZEITLIMIT_S))
        except marketing_pult.PultFehler as f:
            return fehler_nach_post(f, "der Export angestoßen wurde")
        if isinstance(r, dict) and r.get("export_fehler"):
            return ziel("?nl_hinweis=export_offen")
        return ziel()

    return [
        Route("/freigaben/newsletter/{iid}/freigeben", freigeben, methods=["POST"]),
        Route("/freigaben/newsletter/{iid}/zurueckgeben", zurueckgeben, methods=["POST"]),
        Route("/freigaben/newsletter/{iid}/export-nachholen", export_nachholen, methods=["POST"]),
    ]
