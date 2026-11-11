"""Video-Werkbank im Marketing-Pult (11.11.2026, Plan docs/superpowers/plans/2026-11-11-video-werkbank-stufe-1.md
Task 10; die Marketing-Seite steht in vibemind-os spaces/marketing/api/werkbank.py, Pult-Router).

Der Betreiber nimmt ein langes Video Szene fuer Szene am Handy ab:

- /marketing/werkbank/v/{kennung}: Sprung aus der Rowboat-Nachricht auf die passende Seite.
- /marketing/werkbank/{aid}: Uebersicht mit Gliederung, Quellen, Szenenliste und Zaehlung.
- /marketing/werkbank/{aid}/szene/{nr}: Text, Bildidee, Belege, Clip-Abspieler, Wunschfeld und Knoepfe.
- /marketing/werkbank/{aid}/video: das fertige Video mit Abspieler, Download und Kopierfeldern.
- /marketing/werkbank/datei/{name}: Clips und Video aus dem Erzeugt-Ordner, gestreamt, mit Range.
- POST /aktion/werkbank-{wunsch,urteil,nochmal,oeffnen}: gehen an die Pult-Routen der Marketing-API.

Alle Seiten laufen ohne JavaScript, ausser dem Kopier-Knopf der Videoseite (eigene Skriptdatei, CSP script-src
'self' nur auf dieser Seite). Geprueft wird in der Marketing-API (eine Wahrheit): die Seiten senden nur durch,
was sie selbst anzeigen konnten. Die Firma ist die des Ladens (MARKETING_MANDANT)."""
from __future__ import annotations

import os
import re
import stat
import time
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

import auftrag_buch
import marketing_pult
import medien
import ui_reels

BASIS = "/marketing/werkbank"
STUECK = 1024 * 1024               # Lesegroesse beim Streamen: nie die ganze Datei im Speicher
WUNSCH_MAX = 2000                  # wie video_wunsch_setzen (099) und die Pult-Route
NR_MAX = 999
_AID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_KENNUNG = re.compile(r"^wb-[a-z2-7]{10}$")
_NR = re.compile(r"^[0-9]{1,3}$")
_RANGE = re.compile(r"^bytes=([0-9]{0,15})-([0-9]{0,15})$")     # Ziffern begrenzt: nie ein ValueError in int()
# Alle Staende des Auftragsbuchs (Migration 098): die Datei-Route und die Videoseite suchen den Auftrag darin.
_DATEI_STAENDE = ["in_arbeit", "werkbank", "erzeugt", "wartet_freigabe", "fertig"]    # hier kann ein Video Dateien haben
_AUFTRAG_ZEIT = 60.0               # so lange gilt "Praefix -> Auftrag" in der Datei-Route (Seeking = viele Anfragen)
_auftrag_cache: dict[str, tuple[float, str]] = {}
_STAENDE = ["offen", "in_arbeit", "erzeugt", "wartet_freigabe", "fertig", "abgebrochen", "fehler", "abgelaufen",
            "werkbank"]

STAND = {"geplant": "wird geplant", "text_wartet": "Text wartet auf dich", "text_ok": "Text ist ok",
         "wird_erzeugt": "Clip entsteht", "clip_wartet": "Clip wartet auf dich", "fertig": "fertig"}
STAND_CHIP = {"geplant": "offen", "text_wartet": "bereich", "text_ok": "offen", "wird_erzeugt": "offen",
              "clip_wartet": "bereich", "fertig": "gut"}
WARTET = ("text_wartet", "clip_wartet")
MIT_CLIP = ("clip_wartet", "fertig")
BILDART = {"slide": "Slide mit Stimme aus dem Off", "avatar_gross": "Avatar im ganzen Bild",
           "avatar_slide": "Avatar vor der Slide", "clip": "Filmischer Clip"}
VORLAGE = {"titel": "Titel", "stichpunkte": "Stichpunkte", "zahl": "Zahl", "zitat": "Zitat",
           "vergleich": "Vergleich", "agenda": "Agenda"}
UEBERGANG = {"schnitt": "Schnitt", "blende": "Blende"}
AUFTRAG_STAND = {"offen": "bestellt", "in_arbeit": "wird vorbereitet", "werkbank": "in der Werkbank",
                 "erzeugt": "Video ist fertig", "wartet_freigabe": "wartet auf deine Freigabe", "fertig": "fertig",
                 "abgebrochen": "abgebrochen", "fehler": "fehlgeschlagen", "abgelaufen": "abgelaufen"}
HINWEISE = {"ueberholt": ("hinweis", "Diese Fassung ist überholt."),
            "entschieden": ("hinweis", "Schon entschieden – Seite neu geladen."),
            "gespeichert": ("meta", "Dein Wunsch ist gespeichert."),
            "passt": ("meta", "Danke, das ist abgenommen."),
            "nochmal": ("meta", "Verstanden, das wird noch einmal gemacht."),
            "versucht": ("meta", "Die Szene wird noch einmal versucht."),
            "geoeffnet": ("meta", "Die Szene ist wieder offen.")}

KOPIER_JS = """document.addEventListener("click", function (ev) {
  var knopf = ev.target.closest("button[data-kopieren]");
  if (!knopf) { return; }
  var feld = document.getElementById(knopf.getAttribute("data-kopieren"));
  if (!feld) { return; }
  var fertig = function () { knopf.textContent = "Kopiert"; };
  var notfall = function () { feld.select(); try { document.execCommand("copy"); fertig(); } catch (x) {} };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(feld.value).then(fertig, notfall);
  } else { notfall(); }
});
"""

_STIL = """<style>
.wb h2 { margin-top: 1.2rem; }
.wb video { width: 100%; max-height: 70vh; background: #000; }
.wb textarea { width: 100%; min-height: 6rem; box-sizing: border-box; }
.wb .wb-text { white-space: pre-wrap; padding: .6rem .8rem; border-left: 4px solid var(--akzent, #1f7a4d); }
.wb .aktionen { display: flex; flex-wrap: wrap; gap: .6rem; margin: .8rem 0; }
.wb button, .wb a.knopf { min-height: 48px; padding: .5rem 1.1rem; }
.wb ul { padding-left: 1.2rem; }
.wb .wb-szenen a { display: block; padding: .6rem 0; }
</style>"""


def bereich(kopf: str | None, groesse: int) -> tuple[int, int] | None:
    """Start und Ende (beide eingeschlossen) fuer einen Range-Kopf `bytes=a-b`, `a-` oder `-n`; None bei
    Unsinn, mehreren Bereichen oder einem Start hinter dem Ende der Datei (dann antwortet die Route mit 416)."""
    m = _RANGE.fullmatch((kopf or "").strip())
    if not m or groesse <= 0:
        return None
    von, bis = m.groups()
    if von == "" and bis == "":
        return None
    if von == "":                                   # -n: die letzten n Bytes
        n = int(bis)
        return None if n <= 0 else (max(0, groesse - n), groesse - 1)
    start = int(von)
    if start >= groesse:
        return None
    ende = groesse - 1 if bis == "" else min(int(bis), groesse - 1)
    return None if ende < start else (start, ende)


def laden() -> str:
    return os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"


def minuten(sekunden) -> str:
    return ui_reels.laenge_text(sekunden)


def quelle_text(q) -> str:
    """Ein Beleg als eine Zeile: Text, oder bei einem Objekt der erste benennende Wert (plus Stelle)."""
    if isinstance(q, str):
        return q.strip()[:300]
    if not isinstance(q, dict):
        return ""
    for schluessel in ("name", "quelle", "datei", "titel", "pfad", "url"):
        wert = q.get(schluessel)
        if isinstance(wert, str) and wert.strip():
            stelle = q.get("stelle") or q.get("abschnitt")
            zusatz = f" ({str(stelle).strip()})" if isinstance(stelle, (str, int)) and str(stelle).strip() else ""
            return (wert.strip() + zusatz)[:300]
    return " – ".join(str(w) for w in q.values() if isinstance(w, (str, int, float))
                      and not isinstance(w, bool) and str(w).strip())[:300]


def liste(wert) -> list:
    return wert if isinstance(wert, list) else []


def routen(ui) -> list:
    e = ui._e

    def csrf() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(404, "Nicht gefunden", "Das gibt es bei dieser Firma nicht.")
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def keine_firma():
        return ui._fehlerseite(422, "Nicht möglich", "Dieser Laden ist keiner Marketing-Firma zugeordnet.")

    def nicht_gefunden(text: str = "Das gibt es nicht."):
        return ui._fehlerseite(404, "Nicht gefunden", e(text))

    def darf_schreiben() -> bool:
        return ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")

    def api(methode: str, pfad: str, daten: dict | None = None):
        return run_in_threadpool(marketing_pult.anfrage, methode, pfad, daten)

    def seite_url(aid: str, nr: str | None = None, hinweis: str | None = None, kennung: str | None = None) -> str:
        url = f"{BASIS}/{aid}" + (f"/szene/{nr}" if nr else "")
        q = [(k, v) for k, v in (("hinweis", hinweis), ("k", kennung)) if v]
        return url + (f"?{urllib.parse.urlencode(q)}" if q else "")

    def datei_url(name: str, laden_: bool = False) -> str:
        return f"{BASIS}/datei/{e(urllib.parse.quote(name, safe=''))}" + ("?laden=1" if laden_ else "")

    def hinweis_html(request) -> str:
        art, text = HINWEISE.get(request.query_params.get("hinweis", ""), ("", ""))
        return f'<p class="{art}">{e(text)}</p>' if text else ""

    def stand_chip(stand: str, fehler_: bool = False) -> str:
        chip = f'<span class="chip {STAND_CHIP.get(stand, "offen")}">{e(STAND.get(stand, stand))}</span>'
        return chip + (' <span class="chip fehler">Fehler beim Erzeugen</span>' if fehler_ else "")

    async def werk_lesen(m: str, aid: str) -> dict:
        d = await api("GET", f"/werkbank/{aid}?{urllib.parse.urlencode({'mandant': m})}")
        if not isinstance(d, dict) or not isinstance(d.get("werk"), dict):
            raise marketing_pult.PultFehler("unbekannt", "Antwort ohne Werk")
        return d

    async def buch_zeilen(staende: list[str] | None = None) -> list[dict]:
        # sales_eigene filtert nur nach Staenden (nicht nach art): die Videos sucht der Code selbst heraus
        zeilen = await run_in_threadpool(auftrag_buch.eigene, ui.server._q, laden(), staende or _STAENDE)
        return [z for z in zeilen if isinstance(z, dict) and z.get("art") == "video"]

    # --- Sprung aus der Nachricht ----------------------------------------------------------

    @ui._gesichert_seite
    async def sprung(request):
        kennung = request.path_params["kennung"]
        firma = ui_reels.eigene_firma()
        if not firma:
            return keine_firma()
        ueberholt = nicht_gefunden("Diese Fassung ist überholt.")
        if not _KENNUNG.fullmatch(kennung):
            return ueberholt
        try:
            d = await api("GET", f"/werkbank/v/{kennung}")
        except marketing_pult.PultFehler as f:
            return ueberholt if f.art == "abgelehnt" else fehler(f)
        aid = str(d.get("auftrag") or "") if isinstance(d, dict) else ""
        if not _AID.fullmatch(aid) or d.get("mandant") != firma:
            return ueberholt
        if d.get("aktuell") is not True:
            return RedirectResponse(seite_url(aid, hinweis="ueberholt"), status_code=303)
        nr = d.get("nr")
        if d.get("tor") != "gliederung" and isinstance(nr, int) and not isinstance(nr, bool) and 0 < nr <= NR_MAX:
            return RedirectResponse(seite_url(aid, str(nr)), status_code=303)
        return RedirectResponse(seite_url(aid, kennung=kennung), status_code=303)

    # --- Liste der Video-Auftraege ---------------------------------------------------------

    @ui._gesichert_seite
    async def liste_seite(request):
        firma = ui_reels.eigene_firma()
        if not firma:
            return keine_firma()
        try:
            zeilen = await buch_zeilen()
        except Exception:                                   # noqa: BLE001 - nur der Satz, nie der Text
            return ui._fehlerseite(503, "Auftragsbuch nicht erreichbar", "Bitte gleich noch einmal versuchen.")
        eigene = [z for z in zeilen if z.get("mandant") == firma and _AID.fullmatch(str(z.get("id") or ""))]
        eigene.sort(key=lambda z: str(z.get("angelegt") or ""), reverse=True)     # neueste zuerst
        karten = []
        for z in eigene:
            eingabe = z.get("eingabe") if isinstance(z.get("eingabe"), dict) else {}
            thema = str(eingabe.get("thema") or eingabe.get("titel") or "").strip() or "Video ohne Titel"
            erg = z.get("ergebnis") if isinstance(z.get("ergebnis"), dict) else {}
            wb = erg.get("werkbank") if isinstance(erg.get("werkbank"), dict) else {}
            wartet = wb.get("wartet")
            warten = (f' <span class="chip bereich">{wartet} warten auf dich</span>'
                      if isinstance(wartet, int) and not isinstance(wartet, bool) and wartet > 0 else "")
            stand = str(z.get("stand") or "")
            karten.append(f'<a href="{e(seite_url(str(z["id"])))}"><b>{e(thema)}</b> '
                          f'<span class="meta">{e(AUFTRAG_STAND.get(stand, stand))}</span>{warten}</a>')
        inhalt = (f'<div class="wb-szenen">{"".join(karten)}</div>' if karten else
                  '<p class="meta">Noch kein langes Video bestellt. Schreib dem Salesman: „Video zu …“ und '
                  'nenn das Thema.</p>')
        return ui._seite("Lange Videos", _STIL + f'<div class="wb"><p><a href="/marketing/reels">Alle Reels</a></p>'
                         f'{inhalt}</div>')

    # --- Uebersicht -------------------------------------------------------------------------

    def gliederung_html(werk: dict) -> str:
        gl = werk.get("gliederung") if isinstance(werk.get("gliederung"), dict) else {}
        teile = []
        titel = str(gl.get("titel") or "").strip()
        if titel:
            teile.append(f"<h2>{e(titel)}</h2>")
        hook = str(gl.get("hook") or "").strip()
        if hook:
            teile.append(f'<p class="wb-text">{e(hook)}</p>')
        for stufe in liste(gl.get("stufen")):
            if not isinstance(stufe, dict):
                continue
            zeilen = []
            for sz in liste(stufe.get("szenen")):
                kurz = sz if isinstance(sz, str) else (sz.get("kurz") or sz.get("titel") if isinstance(sz, dict) else "")
                quellen = [quelle_text(q) for q in liste(sz.get("quellen"))] if isinstance(sz, dict) else []
                beleg = (f' <span class="meta">Quellen: {e(", ".join(q for q in quellen if q))}</span>'
                         if any(quellen) else "")
                zeilen.append(f"<li>{e(str(kurz or '').strip())}{beleg}</li>")
            teile.append(f"<h3>{e(str(stufe.get('name') or stufe.get('titel') or ''))}</h3><ul>{''.join(zeilen)}</ul>")
        fehlt = gl.get("fehlt")
        fehlt = [fehlt] if isinstance(fehlt, str) else liste(fehlt)
        saetze = [str(f).strip() for f in fehlt if isinstance(f, (str, int, float)) and str(f).strip()]
        if saetze:
            teile.append('<p class="hinweis"><b>Dazu fehlt mir noch etwas:</b></p><ul>'
                         + "".join(f"<li>{e(s)}</li>" for s in saetze) + "</ul>")
        quellen = [quelle_text(q) for q in liste(werk.get("quellen"))]
        quellen = [q for q in quellen if q]
        if quellen:
            teile.append("<h3>Quellen</h3><ul>" + "".join(f"<li>{e(q)}</li>" for q in quellen) + "</ul>")
        return "".join(teile)

    def wunschfeld_gliederung(aid: str, kennung: str, werk: dict) -> str:
        if not (darf_schreiben() and _KENNUNG.fullmatch(kennung) and werk.get("gliederung_stand") == "text_wartet"):
            return ""
        vorbelegt = str(werk.get("gliederung_wunsch") or "")
        return ('<h3>Passt die Gliederung?</h3>'
                f'<form method="post" action="/aktion/werkbank-urteil">{csrf()}'
                f'<input type="hidden" name="aid" value="{e(aid)}"><input type="hidden" name="kennung" value="{e(kennung)}">'
                f'<label>Was soll anders werden? <textarea name="wunsch" maxlength="{WUNSCH_MAX}" '
                f'placeholder="z. B. mehr zu den Kosten, eine Szene weniger">{e(vorbelegt)}</textarea></label>'
                '<div class="aktionen">'
                '<button class="primaer" type="submit" name="urteil" value="passt">Passt</button>'
                '<button type="submit" name="urteil" value="nochmal">Nochmal</button>'
                '<button type="submit" formaction="/aktion/werkbank-wunsch">Wunsch speichern</button>'
                '</div></form>')

    @ui._gesichert_seite
    async def uebersicht(request):
        aid = request.path_params["aid"]
        if not _AID.fullmatch(aid):
            return nicht_gefunden()
        firma = ui_reels.eigene_firma()
        if not firma:
            return keine_firma()
        try:
            d = await werk_lesen(firma, aid)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        werk = d["werk"]
        # Die API nennt die lebende Gliederungs-Kennung (null = keine); fehlt der Schluessel (aeltere API), gilt ?k=
        kennung = d.get("gliederung_kennung") if "gliederung_kennung" in d else request.query_params.get("k", "")
        kennung = kennung if isinstance(kennung, str) else ""
        szenen = [s for s in liste(werk.get("szenen")) if isinstance(s, dict)]
        fertig = sum(1 for s in szenen if s.get("stand") == "fertig")
        warten = sum(1 for s in szenen if s.get("stand") in WARTET)
        teile = [hinweis_html(request),
                 f'<p>{len(szenen)} Szenen, {fertig} fertig, {warten} warten auf dich.</p>',
                 gliederung_html(werk),
                 wunschfeld_gliederung(aid, kennung, werk)]
        if szenen:
            zeilen = []
            for s in szenen:
                nr = s.get("nr")
                if not isinstance(nr, int) or isinstance(nr, bool):
                    continue
                zeilen.append(f'<a href="{e(seite_url(aid, str(nr)))}"><b>Szene {nr}</b> {e(str(s.get("kurz") or ""))} '
                              f'{stand_chip(str(s.get("stand") or ""), bool(s.get("fehler")))}</a>')
            teile.append(f'<h2>Szenen</h2><div class="wb-szenen">{"".join(zeilen)}</div>')
        if werk.get("alle_fertig") is True:
            teile.append(f'<p><a class="knopf primaer" href="{e(BASIS)}/{e(aid)}/video">Zum fertigen Video</a></p>')
        return ui._seite("Video-Werkbank", _STIL + f'<div class="wb">{"".join(teile)}</div>')

    # --- Szenenseite ------------------------------------------------------------------------

    def schritte_html(s: dict) -> str:
        bild = s.get("bild") if isinstance(s.get("bild"), dict) else {}
        teile = []
        art = BILDART.get(str(s.get("bildart") or ""))
        if art:
            teile.append(f"<p>{e(art)}</p>")
        zeilen = []
        for i, sch in enumerate(liste(bild.get("schritte")), 1):
            if not isinstance(sch, dict):
                continue
            namen = VORLAGE.get(str(sch.get("vorlage") or ""), str(sch.get("vorlage") or "Bild"))
            inhalt = []
            for k, w in sch.items():
                if k == "vorlage":
                    continue
                if isinstance(w, (str, int, float)) and not isinstance(w, bool) and str(w).strip():
                    inhalt.append(str(w).strip())
                elif isinstance(w, list):
                    inhalt += [str(x).strip() for x in w if isinstance(x, (str, int, float)) and str(x).strip()]
            zeilen.append(f"<li>Bild {i}: <b>{e(namen)}</b>"
                          + (f" – {e(' · '.join(inhalt))}" if inhalt else "") + "</li>")
        if zeilen:
            teile.append(f'<ol class="wb-schritte">{"".join(zeilen)}</ol>')
        uebergang = UEBERGANG.get(str(s.get("uebergang") or ""))
        if uebergang:
            teile.append(f'<p class="meta">Übergang zur nächsten Szene: {e(uebergang)}</p>')
        return "".join(teile)

    def wuensche_html(s: dict) -> str:
        texte = []
        for w in liste(s.get("wuensche")):
            t = w.get("text") if isinstance(w, dict) else w
            if isinstance(t, str) and t.strip():
                texte.append(t.strip())
        return ("<h3>Bisherige Wünsche</h3><ul>" + "".join(f"<li>{e(t)}</li>" for t in texte) + "</ul>") if texte else ""

    def knoepfe_html(aid: str, nr: str, s: dict, kennung: str) -> str:
        if not darf_schreiben():
            return ""
        stand = str(s.get("stand") or "")
        ziel = (f'<input type="hidden" name="aid" value="{e(aid)}"><input type="hidden" name="nr" value="{e(nr)}">')
        teile = []
        if stand in WARTET and _KENNUNG.fullmatch(kennung):
            frage = "Ist der Text so gut?" if stand == "text_wartet" else "Passt der Clip?"
            teile.append(
                f'<h3>{frage}</h3><form method="post" action="/aktion/werkbank-urteil">{csrf()}{ziel}'
                f'<input type="hidden" name="kennung" value="{e(kennung)}">'
                f'<label>Dein Wunsch (freiwillig, bis {WUNSCH_MAX} Zeichen) <textarea name="wunsch" '
                f'maxlength="{WUNSCH_MAX}">{e(str(s.get("wunsch") or ""))}</textarea></label>'
                '<div class="aktionen">'
                '<button class="primaer" type="submit" name="urteil" value="passt">Passt</button>'
                '<button type="submit" name="urteil" value="nochmal">Nochmal</button>'
                '<button type="submit" formaction="/aktion/werkbank-wunsch">Wunsch speichern</button>'
                '</div></form>')
        if s.get("fehler"):
            teile.append(f'<form method="post" action="/aktion/werkbank-nochmal">{csrf()}{ziel}'
                         '<div class="aktionen"><button class="primaer" type="submit">Nochmal versuchen</button></div></form>')
        if stand == "fertig":
            teile.append(
                f'<form method="post" action="/aktion/werkbank-oeffnen">{csrf()}{ziel}'
                f'<label>Was soll anders werden? <textarea name="wunsch" maxlength="{WUNSCH_MAX}" required></textarea></label>'
                '<div class="aktionen"><button type="submit">Szene wieder öffnen</button></div></form>')
        return "".join(teile)

    @ui._gesichert_seite
    async def szene(request):
        aid, nr = request.path_params["aid"], request.path_params["nr"]
        if not _AID.fullmatch(aid) or not _NR.fullmatch(nr):
            return nicht_gefunden()
        firma = ui_reels.eigene_firma()
        if not firma:
            return keine_firma()
        try:
            d = await api("GET", f"/werkbank/{aid}/szene/{int(nr)}?{urllib.parse.urlencode({'mandant': firma})}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        s = d.get("szene") if isinstance(d, dict) and isinstance(d.get("szene"), dict) else None
        if s is None:
            return nicht_gefunden()
        kennung = str(d.get("kennung") or "")
        stand = str(s.get("stand") or "")
        teile = [hinweis_html(request),
                 f'<p><a href="{e(seite_url(aid))}">Alle Szenen</a></p>',
                 f'<h2>Szene {int(nr)}: {e(str(s.get("kurz") or ""))}</h2>',
                 f'<p>{stand_chip(stand, bool(s.get("fehler")))}'
                 + (f' <span class="meta">{e(str(s.get("stufe")))}</span>' if s.get("stufe") else "") + "</p>"]
        if s.get("fehler"):
            teile.append(f'<p class="warnung">Beim Erzeugen ist etwas schiefgegangen: {e(str(s["fehler"])[:300])}</p>')
        datei = str(s.get("clip_datei") or "")
        if stand in MIT_CLIP and medien.WERKBANK_MUSTER.fullmatch(datei):
            dauer = ui_reels.dauer_text(s.get("dauer_s"))
            teile.append(f'<video controls preload="metadata" src="{datei_url(datei)}"></video>'
                         + (f'<p class="meta">Länge {e(dauer)}</p>' if dauer else ""))
        sprech = str(s.get("sprechtext") or "").strip()
        teile.append('<h3>Sprechtext</h3>' + (f'<p class="wb-text">{e(sprech)}</p>' if sprech
                                              else '<p class="meta">Der Text ist noch nicht geschrieben.</p>'))
        teile.append("<h3>Bildidee</h3>" + (schritte_html(s) or '<p class="meta">Noch keine Bildidee.</p>'))
        belege = [quelle_text(q) for q in liste(s.get("quellen"))]
        belege = [b for b in belege if b]
        teile.append("<h3>Belege</h3>" + ("<ul>" + "".join(f"<li>{e(b)}</li>" for b in belege) + "</ul>" if belege
                                          else '<p class="meta">Keine Belege angegeben.</p>'))
        teile.append(wuensche_html(s))
        teile.append(knoepfe_html(aid, nr, s, kennung))
        return ui._seite(f"Szene {int(nr)}", _STIL + f'<div class="wb">{"".join(teile)}</div>')

    # --- Fertiges Video ---------------------------------------------------------------------

    def kopierfeld(feld: str, titel: str, text: str) -> str:
        return (f'<h3>{e(titel)}</h3><textarea id="kf-{feld}" readonly rows="{min(12, max(3, text.count(chr(10)) + 2))}">'
                f'{e(text)}</textarea>'
                f'<div class="aktionen"><button type="button" data-kopieren="kf-{feld}">Kopieren</button></div>')

    def zeitmarken_text(marken) -> str:
        zeilen = []
        for z in liste(marken):
            if isinstance(z, dict):
                zeilen.append(f'{str(z.get("zeit") or "0:00").strip()} {str(z.get("name") or "").strip()}'.strip())
        return "\n".join(zeilen)

    @ui._gesichert_seite
    async def video(request):
        aid = request.path_params["aid"]
        if not _AID.fullmatch(aid):
            return nicht_gefunden()
        firma = ui_reels.eigene_firma()
        if not firma:
            return keine_firma()
        try:
            werk = (await werk_lesen(firma, aid))["werk"]   # die Firma kennt den Auftrag, sonst 404
            zeilen = await buch_zeilen(_DATEI_STAENDE)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        except Exception:                                   # noqa: BLE001 - nur der Satz, nie der Text
            return ui._fehlerseite(503, "Auftragsbuch nicht erreichbar", "Bitte gleich noch einmal versuchen.")
        zeile = next((z for z in zeilen if str(z.get("id")) == aid and z.get("mandant") == firma), None)
        erg = zeile.get("ergebnis") if zeile and isinstance(zeile.get("ergebnis"), dict) else {}
        datei = str(erg.get("datei") or "")
        zurueck = f'<p><a href="{e(seite_url(aid))}">Alle Szenen</a></p>'
        if not medien.WERKBANK_MUSTER.fullmatch(datei):
            return ui._seite("Fertiges Video", _STIL + '<div class="wb">' + zurueck
                             + '<p class="hinweis">Das Video ist noch nicht fertig zusammengesetzt.</p></div>')
        groesse = (f'{erg["bytes"] / 1_000_000:.0f} MB' if isinstance(erg.get("bytes"), (int, float))
                   and not isinstance(erg.get("bytes"), bool) and erg["bytes"] > 0 else "")
        angaben = " · ".join(t for t in (minuten(erg.get("dauer_s")) if erg.get("dauer_s") else "", groesse) if t)
        veraltet = werk.get("video_veraltet") is True
        laden_knopf = ("" if veraltet else f'<a class="knopf primaer" href="{datei_url(datei, True)}">Herunterladen</a>')
        teile = [zurueck,
                 '<p class="hinweis">Eine Szene wurde wieder geöffnet – dieses Video wird neu gebaut.</p>'
                 if veraltet else "",
                 f'<video controls preload="metadata" src="{datei_url(datei)}"></video>',
                 f'<p class="meta">{e(angaben)}</p>' if angaben else "",
                 f'<div class="aktionen">{laden_knopf}<a class="knopf" href="/freigaben">Zu den Freigaben</a></div>',
                 '<p class="hinweis">Dieses Video ist mit KI erstellt (Bilder, Stimme und Schnitt). '
                 'Gib es erst frei, wenn du es dir angesehen hast.</p>',
                 kopierfeld("titel", "Titel", str(erg.get("titel") or "")),
                 kopierfeld("beschreibung", "Beschreibung", str(erg.get("beschreibung") or "")),
                 kopierfeld("zeitmarken", "Zeitmarken für YouTube", zeitmarken_text(erg.get("zeitmarken")))]
        notiz = str(erg.get("messnotiz") or "").strip()
        if notiz:
            teile.append(f'<h3>Messnotiz</h3><p class="wb-text">{e(notiz)}</p>')
        warn = [str(w).strip() for w in liste(erg.get("warnungen")) if isinstance(w, str) and w.strip()]
        if warn:
            teile.append('<h3>Warnungen</h3><ul class="warnung">' + "".join(f"<li>{e(w)}</li>" for w in warn) + "</ul>")
        teile.append(f'<script src="{BASIS}/kopieren.js" defer></script>')
        antwort = ui._seite("Fertiges Video", _STIL + f'<div class="wb">{"".join(t for t in teile if t)}</div>')
        antwort.headers["Content-Security-Policy"] = ui._CSP + "; script-src 'self'"
        return antwort

    @ui._gesichert_seite
    async def kopier_skript(request):
        return Response(KOPIER_JS, media_type="text/javascript",
                        headers={"cache-control": "no-cache", "X-Content-Type-Options": "nosniff"})

    # --- Aktionen ----------------------------------------------------------------------------

    async def aktion(request, ziel_nr: bool):
        """Gemeinsamer Kopf der vier POST-Routen: -> (form, aid, nr, firma, None) oder (None, ..., Fehlerseite)."""
        form = await request.form()
        if not ui._csrf_ok(form):
            return None, None, None, None, ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        rolle = ui._AKTIVE_ROLLE.get()
        if not darf_schreiben() or (rolle and not ui._pfad_erlaubt(rolle, BASIS)):
            return None, None, None, None, ui._fehlerseite(403, "Nicht erlaubt", "Diese Anmeldung darf hier nichts ändern.")
        aid, nr = str(form.get("aid") or ""), str(form.get("nr") or "")
        if not _AID.fullmatch(aid) or (nr and not _NR.fullmatch(nr)) or (ziel_nr and not nr):
            return None, None, None, None, nicht_gefunden()
        firma = ui_reels.eigene_firma()
        if not firma:
            return None, None, None, None, keine_firma()
        return form, aid, nr, firma, None

    def wunsch_aus(form) -> str | None:
        wunsch = str(form.get("wunsch") or "").strip()
        return None if len(wunsch) > WUNSCH_MAX else wunsch

    def zu_lang():
        return ui._fehlerseite(422, "Nicht möglich", f"Der Wunsch darf höchstens {WUNSCH_MAX} Zeichen haben.")

    def schon_entschieden(aid: str, nr: str, wunsch: str, kennung: str):
        """Die API hat abgelehnt (409, oder 200 mit ok:false). Ohne Wunsch: zurueck zur Seite mit dem Hinweis.
        Mit Wunsch: kein Redirect, damit der getippte Text nicht verloren geht - er steht zum Kopieren da."""
        ziel = seite_url(aid, nr or None, "entschieden", None if nr else kennung or None)
        if not wunsch:
            return RedirectResponse(ziel, status_code=303)
        rumpf = (_STIL + '<div class="wb"><p class="hinweis">Schon entschieden – Seite neu geladen. Dein Wunsch ist '
                 'nicht gespeichert; hier steht er zum Kopieren.</p>'
                 f'<textarea readonly rows="6">{e(wunsch)}</textarea>'
                 f'<p><a class="knopf primaer" href="{e(ziel)}">Seite neu laden</a></p></div>')
        return ui._seite("Schon entschieden", rumpf, status=409)

    async def senden(request, aid: str, nr: str, pfad: str, daten: dict, erfolg: str, kennung: str = ""):
        """Pult-Route aufrufen. Eine Ablehnung heisst: schon entschieden. Sie kommt als 404/409/422 (PultFehler)
        oder, bei /wunsch, als 200 mit {"ok": false} - beides wird gleich behandelt."""
        daten = {**daten, "mandant": ui_reels.eigene_firma(), "von": (ui._ui_akteur(request) or "betreiber-ui")[:60]}
        wunsch = str(daten.get("wunsch") or "")
        try:
            antwort = await api("POST", pfad, daten)
        except marketing_pult.PultFehler as f:
            if f.art != "abgelehnt":
                return fehler(f)
            return schon_entschieden(aid, nr, wunsch, kennung)
        if isinstance(antwort, dict) and antwort.get("ok") is False:
            return schon_entschieden(aid, nr, wunsch, kennung)
        return RedirectResponse(seite_url(aid, nr or None, erfolg, None if nr else kennung or None), status_code=303)

    @ui._gesichert_seite
    async def wunsch_speichern(request):
        form, aid, nr, _, abgelehnt = await aktion(request, False)
        if abgelehnt is not None:
            return abgelehnt
        kennung, wunsch = str(form.get("kennung") or ""), wunsch_aus(form)
        if not _KENNUNG.fullmatch(kennung):
            return nicht_gefunden()
        if wunsch is None:
            return zu_lang()
        if not wunsch:
            return ui._fehlerseite(422, "Nicht möglich", "Schreib bitte erst einen Wunsch auf.")
        return await senden(request, aid, nr, f"/werkbank/v/{kennung}/wunsch", {"wunsch": wunsch}, "gespeichert", kennung)

    @ui._gesichert_seite
    async def urteil(request):
        form, aid, nr, _, abgelehnt = await aktion(request, False)
        if abgelehnt is not None:
            return abgelehnt
        kennung, wunsch = str(form.get("kennung") or ""), wunsch_aus(form)
        art = str(form.get("urteil") or "")
        if not _KENNUNG.fullmatch(kennung) or art not in ("passt", "nochmal"):
            return nicht_gefunden()
        if wunsch is None:
            return zu_lang()
        return await senden(request, aid, nr, f"/werkbank/v/{kennung}/urteil", {"urteil": art, "wunsch": wunsch}, art, kennung)

    @ui._gesichert_seite
    async def nochmal(request):
        form, aid, nr, _, abgelehnt = await aktion(request, True)
        if abgelehnt is not None:
            return abgelehnt
        return await senden(request, aid, nr, f"/werkbank/{aid}/szene/{int(nr)}/nochmal-versuchen", {}, "versucht")

    @ui._gesichert_seite
    async def oeffnen(request):
        form, aid, nr, _, abgelehnt = await aktion(request, True)
        if abgelehnt is not None:
            return abgelehnt
        wunsch = wunsch_aus(form)
        if wunsch is None:
            return zu_lang()
        if not wunsch:
            return ui._fehlerseite(422, "Nicht möglich", "Schreib bitte auf, was anders werden soll.")
        return await senden(request, aid, nr, f"/werkbank/{aid}/szene/{int(nr)}/oeffnen", {"wunsch": wunsch}, "geoeffnet")

    # --- Dateien (Clips und Video) -----------------------------------------------------------

    def datei_pruefen(name: str) -> int | None:
        """Groesse der Datei im Erzeugt-Ordner, wenn sie eine echte Datei ist (kein Symlink, nichts anderes)."""
        try:
            st = os.lstat(os.path.join(medien.erzeugt_wurzel(), name))
        except OSError:
            return None
        return st.st_size if stat.S_ISREG(st.st_mode) and st.st_size > 0 else None

    async def stuecke(name: str, start: int, ende: int):
        """Die Bytes start..ende in Stuecken von 1 MB. Geoeffnet wird erst hier (nicht schon in der Route):
        ein Abbruch vor dem ersten Stueck laesst so nie ein offenes Handle zurueck."""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = await run_in_threadpool(os.open, os.path.join(medien.erzeugt_wurzel(), name), flags)
        try:
            if not stat.S_ISREG((await run_in_threadpool(os.fstat, fd)).st_mode):
                return
            await run_in_threadpool(os.lseek, fd, start, os.SEEK_SET)
            rest = ende - start + 1
            while rest > 0:
                teil = await run_in_threadpool(os.read, fd, min(STUECK, rest))
                if not teil:
                    break
                rest -= len(teil)
                yield teil
        finally:
            os.close(fd)

    @ui._gesichert_seite
    async def datei(request):
        name = request.path_params["name"]
        if not medien.WERKBANK_MUSTER.fullmatch(name):
            return nicht_gefunden()
        firma = ui_reels.eigene_firma()
        if not firma:
            return nicht_gefunden()
        try:
            schluessel = f"{firma}/{name[3:11]}"
            jetzt = time.monotonic()
            treffer = _auftrag_cache.get(schluessel)
            if treffer and jetzt - treffer[0] < _AUFTRAG_ZEIT:
                aid = treffer[1]
            else:
                zeilen = await buch_zeilen(_DATEI_STAENDE)
                aid = next((str(z["id"]) for z in zeilen
                            if str(z.get("id") or "").startswith(name[3:11]) and z.get("mandant") == firma), "")
                if not _AID.fullmatch(aid):
                    return nicht_gefunden()
                _auftrag_cache[schluessel] = (jetzt, aid)
            await werk_lesen(firma, aid)                    # die Marketing-API kennt den Auftrag dieser Firma
        except marketing_pult.PultFehler as f:
            return nicht_gefunden() if f.art == "abgelehnt" else fehler(f)
        except Exception:                                   # noqa: BLE001
            return ui._fehlerseite(503, "Auftragsbuch nicht erreichbar", "Bitte gleich noch einmal versuchen.")
        groesse = await run_in_threadpool(datei_pruefen, name)
        if groesse is None:
            return nicht_gefunden("Die Datei liegt nicht bereit.")
        art = "attachment" if request.query_params.get("laden") == "1" else "inline"
        koepfe = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=60",
                  "Content-Disposition": f'{art}; filename="{name}"',
                  "Content-Security-Policy": ui._CSP_DATEI}
        kopf = request.headers.get("range")
        if kopf is None:
            start, ende, status = 0, groesse - 1, 200
        else:
            r = bereich(kopf, groesse)
            if r is None:
                return Response(status_code=416, headers={**koepfe, "Content-Range": f"bytes */{groesse}"})
            (start, ende), status = r, 206
            koepfe["Content-Range"] = f"bytes {start}-{ende}/{groesse}"
        koepfe["Content-Length"] = str(ende - start + 1)
        if request.method == "HEAD":
            return Response(status_code=status, headers=koepfe, media_type="video/mp4")
        return StreamingResponse(stuecke(name, start, ende), status_code=status, headers=koepfe,
                                 media_type="video/mp4")

    return [
        Route(BASIS, liste_seite),
        Route(f"{BASIS}/kopieren.js", kopier_skript),
        Route(f"{BASIS}/v/{{kennung}}", sprung),
        Route(f"{BASIS}/datei/{{name}}", datei),
        Route(f"{BASIS}/{{aid}}", uebersicht),
        Route(f"{BASIS}/{{aid}}/video", video),
        Route(f"{BASIS}/{{aid}}/szene/{{nr}}", szene),
        Route("/aktion/werkbank-wunsch", wunsch_speichern, methods=["POST"]),
        Route("/aktion/werkbank-urteil", urteil, methods=["POST"]),
        Route("/aktion/werkbank-nochmal", nochmal, methods=["POST"]),
        Route("/aktion/werkbank-oeffnen", oeffnen, methods=["POST"]),
    ]
