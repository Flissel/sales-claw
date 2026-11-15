"""Video-Werkbank im Marketing-Pult (11.11.2026, Plan docs/superpowers/plans/2026-11-11-video-werkbank-stufe-1.md
Task 10; die Marketing-Seite steht in vibemind-os spaces/marketing/api/werkbank.py, Pult-Router).

Der Betreiber nimmt ein langes Video Szene fuer Szene am Handy ab:

- /marketing/werkbank/v/{kennung}: Sprung aus der Rowboat-Nachricht auf die passende Seite.
- /marketing/werkbank/{aid}: Uebersicht mit Gliederung, Quellen, Szenenliste und Zaehlung.
- /marketing/werkbank/{aid}/szene/{nr}: Text, Bildidee, Belege, Clip-Abspieler, Wunschfeld und Knoepfe.
- /marketing/werkbank/{aid}/video: das fertige Video mit Abspieler, Download und Kopierfeldern.
- /marketing/werkbank/datei/{name}: Clips und Video aus dem Erzeugt-Ordner, gestreamt, mit Range.
- Abschnitt "Übergaben aus Rowboat" (#uebergaben) auf der Liste; POST /aktion/werkbank-uebergabe-{ja,nein}
  (video_uebergabe.py): erst das Ja legt den Auftrag an.
- POST /aktion/werkbank-{wunsch,urteil,nochmal,oeffnen,neu-schreiben,neu-bauen}: gehen an die Pult-Routen der
  Marketing-API. "Nochmal schreiben" gibt einer aufgegebenen Szene oder Gliederung einen neuen Wunsch, "Video neu
  zusammenfügen" startet nach einem gescheiterten Zusammenfuegen genau einen neuen Versuch.

Alle Seiten laufen ohne JavaScript, ausser dem Kopier-Knopf der Videoseite (eigene Skriptdatei, CSP script-src
'self' nur auf dieser Seite). Geprueft wird in der Marketing-API (eine Wahrheit): die Seiten senden nur durch,
was sie selbst anzeigen konnten. Die Firma ist die des Ladens (MARKETING_MANDANT)."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
import stat
import time
import unicodedata
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

import auftrag_buch
import marketing_pult
import medien
import ui_reels
import video_uebergabe

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
            "geoeffnet": ("meta", "Die Szene ist wieder offen."),
            "neu": ("meta", "Danke – das wird mit deinem Wunsch neu geschrieben."),
            "neu_bauen": ("meta", "Das Video wird neu zusammengefügt.")}

UEBERGABE_HINWEIS = "Was im Konzept steht, geht an das Videomodell und kann im Video landen."
UEBERGABE_NUR_MIT_ANMELDUNG = "Bestätigen geht nur mit Anmeldung."
UEBERGABE_DOPPELT = "Es gibt eine weitere offene Übergabe für diese Datei – bitte vergleichen."
KUERZEN_BEI = 300                  # Hook, Kernaussage, Abschluss: sichtbar bis hierher, der Rest unter "Alles lesen"
UEBERGABE_GEKUERZT = "… (gekürzt, alles unter „Alles lesen“)"
_SICHTBAR_LASSEN = "\n\r\t"           # Zeilenumbruch und Tab sind lesbar, alles andere Unsichtbare nicht


def sichtbar_machen(text) -> str:
    """Steuer-, Format- und Trennzeichen (Cc, Cf, Zl, Zp, Cs, Co, Cn: z. B. U+200B, U+202E, U+FEFF) werden als
    sichtbarer Platzhalter `⟨U+200B⟩` geschrieben. Damit kann ein Text, den der Betreiber liest, nicht aus Unsichtbarem
    bestehen oder seine Leserichtung drehen. Maskiert (HTML) wird erst danach."""
    return "".join(z if z in _SICHTBAR_LASSEN or unicodedata.category(z) not in _UNSICHTBAR else f"⟨U+{ord(z):04X}⟩"
                   for z in str(text or ""))


_UNSICHTBAR = frozenset(("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"))


def kuerzen_sichtbar(text, grenze: int = KUERZEN_BEI) -> tuple[str, bool]:
    """Der Anfang des Textes mit sichtbar gemachten Zeichen, hoechstens `grenze` angezeigte Zeichen (ein Platzhalter
    zaehlt mit seiner Laenge und wird nie zerschnitten) -> (Text, wurde_gekuerzt)."""
    ausgabe, n = [], 0
    for z in str(text or ""):
        stueck = sichtbar_machen(z)
        if n + len(stueck) > grenze:
            return "".join(ausgabe), True
        ausgabe.append(stueck)
        n += len(stueck)
    return "".join(ausgabe), False


def alter_text(sekunden) -> str:
    """"vor n Minuten" / "vor n Stunden" aus dem Alter in Sekunden (nach der Uhr der Datenbank)."""
    s = sekunden if isinstance(sekunden, int) and not isinstance(sekunden, bool) and sekunden > 0 else 0
    if s < 3600:
        n = max(1, s // 60)
        return f"vor {n} Minute" if n == 1 else f"vor {n} Minuten"
    n = s // 3600
    return f"vor {n} Stunde" if n == 1 else f"vor {n} Stunden"

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
        text = q.strip()[:300]
        return "Konzept" if text == "konzept" else text   # Quelle konzept: das Konzept aus Rowboat
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


def kurztext(wert, grenze: int = 300) -> str:
    return wert.strip()[:grenze] if isinstance(wert, str) else ""


def aussagen(belege) -> list[tuple[str, str]]:
    """Die geprueften Belege der Szene als (Aussage, Quelle); unbrauchbare Eintraege fallen weg."""
    paare = []
    for b in liste(belege):
        if not isinstance(b, dict):
            continue
        aussage, quelle = kurztext(b.get("aussage"), 500), kurztext(b.get("quelle"), 200)
        if aussage and quelle:
            paare.append((aussage, "Auftrag" if quelle == "auftrag" else quelle))
    return paare


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

    # --- Uebergaben aus Rowboat (Spec 14): das verbindliche Ja steht hier -----------------

    def darf_entscheiden() -> bool:
        rolle = ui._AKTIVE_ROLLE.get()
        return darf_schreiben() and not (rolle and not ui._pfad_erlaubt(rolle, BASIS))

    def anmeldung_aktiv(request) -> bool:
        """Bestaetigen verlangt eine ECHTE Anmeldung: ein gesetztes Sitzungsgeheimnis UND eine angemeldete Sitzung.
        Ohne Geheimnis laeuft die Oberflaeche ohne Login; dann waere jeder, der sie erreicht, "der Betreiber"."""
        return bool(ui.UI_SESSION_SECRET) and bool(request.scope.get("benutzer_name"))

    def gleiche_herkunft(request) -> bool:
        """Die Anfrage stammt von dieser Seite: `Sec-Fetch-Site` (wenn gesendet) muss same-origin sein, `Origin`
        (wenn gesendet) muss GENAU eine Herkunft dieser Oberflaeche sein: Schema + Host + Port, siehe
        `eigene_herkuenfte` (mit gesetzter UI_BASIS_URL zaehlt nur sie, auch hinter `tailscale serve` mit https). Ein
        anderes Schema oder ein anderer Port ist fremd. Fehlen beide Koepfe, gilt die Anfrage wie bei den uebrigen Aktionen der
        Seite (die pruefen keinen Herkunftskopf); Browser senden bei einem POST immer Origin."""
        kopf = request.headers
        site = kopf.get("sec-fetch-site")
        if site is not None and site != "same-origin":
            return False
        origin = kopf.get("origin")
        if origin is not None:
            if _herkunft(origin) not in eigene_herkuenfte(request):
                return False
        return True

    def _herkunft(url: str):
        """(Schema, Host, Port) einer Origin oder URL, Schema und Host kleingeschrieben; None, wenn unbrauchbar."""
        try:
            teile = urllib.parse.urlsplit(url)
            host, port = teile.hostname, teile.port
        except ValueError:
            return None
        if teile.scheme not in ("http", "https") or not host or teile.path not in ("", "/") or teile.query \
                or teile.fragment or teile.username is not None:
            return None
        return teile.scheme, host.lower(), port or (443 if teile.scheme == "https" else 80)

    def eigene_herkuenfte(request) -> set:
        """Die Herkuenfte (Schema, Host, Port), die ein Ja/Nein von dieser Seite haben darf.
        UI_BASIS_URL gesetzt (weicht vom Vorgabewert http://127.0.0.1:<Port> ab): NUR deren Herkunft, dazu die Hosts aus
        ERLAUBTE_HOSTS mit dem Schema der Basisadresse. Nicht gesetzt: die Herkunft der Anfrage selbst (Schema, mit dem
        sie ankommt, + Host-Kopf), dazu die Hosts aus ERLAUBTE_HOSTS mit https. Loopback-Namen zaehlen nur ueber die
        Herkunft der Anfrage bzw. der Basisadresse, nie als https-Herkunft (die Oberflaeche dient sie nur per http)."""
        basis = getattr(ui, "UI_BASIS_URL", "") or ""
        gesetzt = bool(basis) and basis.rstrip("/") != f"http://127.0.0.1:{getattr(ui, 'PORT', 8791)}"
        eigene = set()
        if gesetzt:
            h = _herkunft(basis)
            schema = h[0] if h else "https"
            if h:
                eigene.add(h)
        else:
            schema = "https"
            h = _herkunft(f"{request.url.scheme}://{request.headers.get('host', '')}")
            if h:
                eigene.add(h)
        for eintrag in getattr(ui, "ERLAUBTE_HOSTS", ()):
            h = _herkunft(f"{schema}://{eintrag}")
            if h and h[1] not in ("127.0.0.1", "localhost"):
                eigene.add(h)
        return eigene

    def zeit_text(zeit) -> str:
        if not isinstance(zeit, datetime):
            return ""
        zone = getattr(ui, "ZEITZONE", None) or timezone.utc
        return zeit.astimezone(zone).strftime("%d.%m.%Y %H:%M") + " Uhr"

    async def uebergabe_meldung(request) -> str:
        """Ergebniszeile nach Ja/Nein, aus der DB-Zeile der Uebergabe (`u` im Link) abgeleitet: ein gebastelter Link
        kann nur zeigen, was in der Zeile steht."""
        if request.query_params.get("hinweis") != "uebergabe":
            return hinweis_html(request)
        kennung = request.query_params.get("u", "")
        if not _AID.fullmatch(kennung):
            return ""
        try:
            z = await run_in_threadpool(video_uebergabe.zustand, kennung)
        except Exception:                                   # noqa: BLE001 - die Zeile ist nur Beiwerk
            return ""
        if z is None:
            return f'<p class="hinweis">{e(video_uebergabe.SATZ_FEHLT)}</p>'
        status = z.get("status")
        schon = (f"{video_uebergabe.SATZ_ENTSCHIEDEN} "
                 if request.query_params.get("e") == "1" and status != "offen" else "")
        if status == "bestaetigt" and z.get("auftrag_id"):
            aid = str(z["auftrag_id"])
            return (f'<p class="hinweis">{e(schon)}Übergeben: Auftrag {e(aid[:8])} ist angelegt. '
                    f'<a href="{e(BASIS)}/{e(aid)}">Zum Auftrag</a></p>')
        if status == "verworfen":
            return f'<p class="meta">{e(schon)}Die Übergabe ist verworfen. Es wurde kein Auftrag angelegt.</p>'
        if status == "abgelaufen":
            return f'<p class="hinweis">{e(video_uebergabe.SATZ_ABGELAUFEN)}</p>'
        if status == "offen" and z.get("fehler"):
            return ('<p class="warnung">Der Auftrag wurde nicht angelegt. '
                    'Der Grund steht an der Übergabe.</p>')
        return ""

    def t(text) -> str:
        """Text aus dem Konzept fuer die Karte: Unsichtbares als Platzhalter, dann HTML-maskiert."""
        return e(sichtbar_machen(text))

    def uebergabe_karte(z: dict, darf: bool, doppelt: bool) -> str:
        k = z["konzept"] if isinstance(z.get("konzept"), dict) else {}
        stufen = [s for s in liste(k.get("stufen")) if isinstance(s, dict)]
        szenen = sum(len([sz for sz in liste(s.get("szenen")) if isinstance(sz, dict)]) for s in stufen)
        kennung = str(z["id"])
        vorgang = kennung[:8]
        datei = " · ".join(f"{titel}: {t(wert)}" for titel, wert in
                           (("Konzept", k.get("name")), ("Datei", k.get("pfad"))) if wert) or "Konzept: ohne Namen"
        firma = f' · Firma: {t(k["firma"])}' if k.get("firma") else ""
        teile = [f'<div class="karte" id="u-{e(vorgang)}">',
                 f'<div><b>Vorgang {e(vorgang)}</b> · eingegangen {e(zeit_text(z.get("erstellt_am")))} '
                 f'({e(alter_text(z.get("alter_s")))})</div>',
                 f'<div><b>{t(k.get("thema", ""))}</b> · {e(k.get("minuten", ""))} Minuten · '
                 f'{len(stufen)} Stufen · {szenen} Szenen</div>',
                 f'<div class="meta">Laden: {e(laden())}{firma} · {datei}</div>']
        if k.get("auftrag"):
            teile.append(f'<p class="meta">Im Konzept eingetragener Auftrag: {t(str(k["auftrag"])[:8])}</p>')
        if doppelt:
            teile.append(f'<p class="warnung">{e(UEBERGABE_DOPPELT)}</p>')
        if z.get("frueher_auftrag"):
            teile.append('<p class="hinweis">Dieses Konzept wurde schon einmal übergeben (Auftrag '
                         f'{e(str(z["frueher_auftrag"])[:8])}).</p>')
        teile.append(f'<p class="hinweis">{e(UEBERGABE_HINWEIS)}</p>')
        # Alles, was an das Videomodell geht, steht auf der Karte: Zielgruppe, Hook, Kernaussage, Abschluss
        # (ab 300 Zeichen gekuerzt, die Kuerzung steht im Text; unsichtbare Zeichen als Platzhalter - der volle Text steht
        # unter "Alles lesen"), Stufen und Szenen darunter.
        voll = []
        teile.append(f'<p class="wb-text"><b>Zielgruppe:</b> {t(k.get("zielgruppe", ""))}</p>')
        for titel, feld in (("Hook", "hook"), ("Kernaussage", "kernaussage"), ("Abschluss", "abschluss")):
            sichtbar, abgeschnitten = kuerzen_sichtbar(k.get(feld))
            rest = f' <b class="warnung">{e(UEBERGABE_GEKUERZT)}</b>' if abgeschnitten else ""
            teile.append(f'<p class="wb-text"><b>{titel}:</b> {e(sichtbar)}{rest}</p>')
            if abgeschnitten:
                voll.append(f'<p class="wb-text"><b>{titel} (vollständig):</b> {t(k.get(feld))}</p>')
        for s in stufen:
            punkte = []
            for sz in liste(s.get("szenen")):
                if not isinstance(sz, dict):
                    continue
                notiz = f' <span class="meta">Notiz: {t(sz["notiz"])}</span>' if sz.get("notiz") else ""
                punkte.append(f'<li>{t(sz.get("kurz", ""))} <span class="meta">({e(sz.get("bildart", ""))})</span>'
                              f'{notiz}</li>')
            voll.append(f'<h4>{t(s.get("name", ""))}</h4><ul>{"".join(punkte)}</ul>')
        teile.append(f'<details><summary>Alles lesen: Stufen und Szenen</summary>{"".join(voll)}</details>')
        if z.get("fehler"):
            teile.append(f'<p class="warnung">{e(z["fehler"])}</p>')
        if darf:
            def knopf(aktion: str, text: str, klasse: str) -> str:
                return (f'<form class="aktion" method="post" action="/aktion/werkbank-uebergabe-{aktion}">{csrf()}'
                        f'<input type="hidden" name="id" value="{e(kennung)}">'
                        f'<button class="{klasse}">{text}</button></form>')
            teile.append(f'<div class="aktionen">{knopf("ja", "Ja, übergeben", "primaer")}'
                         f'{knopf("nein", "Nein", "gefahr")}</div>')
        teile.append("</div>")
        return "".join(teile)

    def fehlerabschnitt(satz: str) -> str:
        return (f'<section class="block" id="uebergaben"><h2>Übergaben aus Rowboat</h2>'
                f'<p class="warnung">{e(satz)}</p></section>')

    async def uebergaben_html(request) -> str:
        """Abschnitt "Übergaben aus Rowboat"; "" nur, wenn nichts offen ist. Eine fehlende Tabelle oder ein Lesefehler
        steht als sichtbare Zeile im Abschnitt, nie als stilles Fehlen."""
        try:
            offene = await run_in_threadpool(video_uebergabe.offene)
        except Exception as f:                              # noqa: BLE001 - nur der Typname, nie der Text
            logging.getLogger("sales-ui").error("Uebergaben nicht lesbar: %s", type(f).__name__)
            return fehlerabschnitt(video_uebergabe.SATZ_NICHT_EINGERICHTET
                                   if isinstance(f, video_uebergabe.NICHT_EINGERICHTET)
                                   else video_uebergabe.SATZ_NICHT_LESBAR)
        if not offene:
            return ""
        anmeldung = anmeldung_aktiv(request)
        darf = darf_entscheiden() and anmeldung
        pfade = [str((z["konzept"] or {}).get("pfad") or "") for z in offene if isinstance(z.get("konzept"), dict)]
        note = ("" if ui.UI_SESSION_SECRET else
                f'<p class="hinweis">{e(UEBERGABE_NUR_MIT_ANMELDUNG)}</p>')
        karten = "".join(
            uebergabe_karte(z, darf, bool(p) and pfade.count(p) > 1)
            for z in offene
            for p in [str((z["konzept"] or {}).get("pfad") or "") if isinstance(z.get("konzept"), dict) else ""])
        return (f'<section class="block" id="uebergaben"><h2>Übergaben aus Rowboat '
                f'<span class="zaehler offen">{len(offene)}</span></h2>{note}{karten}</section>')

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
        meldung = await uebergabe_meldung(request)
        uebergaben = await uebergaben_html(request)
        return ui._seite("Lange Videos", _STIL + f'<div class="wb"><p><a href="/marketing/reels">Alle Reels</a></p>'
                         f'{meldung}{uebergaben}{inhalt}</div>')

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

    def neu_schreiben_html(aid: str, nr: str | None, grund: str) -> str:
        """C1: aufgegeben (Szene oder Gliederung in geplant) -> Grund, Wunschfeld und "Nochmal schreiben"."""
        teile = [f'<p class="warnung">{e(grund)}</p>']
        if darf_schreiben():
            ziel = f'<input type="hidden" name="aid" value="{e(aid)}">' + (
                f'<input type="hidden" name="nr" value="{e(nr)}">' if nr else "")
            teile.append(
                f'<form method="post" action="/aktion/werkbank-neu-schreiben">{csrf()}{ziel}'
                f'<label>Was soll anders werden? <textarea name="wunsch" maxlength="{WUNSCH_MAX}" required '
                'placeholder="z. B. welche Zahl aus welchem Dokument, oder was weg kann"></textarea></label>'
                '<div class="aktionen"><button class="primaer" type="submit">Nochmal schreiben</button></div></form>')
        return "".join(teile)

    def neu_bauen_html(aid: str, werk: dict) -> str:
        """I1: das Zusammenfuegen ist gescheitert (video_fehler) und alle Szenen sind fertig."""
        grund = kurztext(werk.get("video_fehler"))
        if not grund or werk.get("alle_fertig") is not True:
            return ""
        teile = [f'<p class="warnung">{e(grund)}</p>']
        if darf_schreiben():
            teile.append(f'<form method="post" action="/aktion/werkbank-neu-bauen">{csrf()}'
                         f'<input type="hidden" name="aid" value="{e(aid)}">'
                         '<div class="aktionen"><button class="primaer" type="submit">Video neu zusammenfügen</button>'
                         '</div></form>')
        return "".join(teile)

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
        gl_grund = kurztext(werk.get("gliederung_aufgegeben"))
        teile = [hinweis_html(request),
                 f'<p>{len(szenen)} Szenen, {fertig} fertig, {warten} warten auf dich.</p>',
                 gliederung_html(werk),
                 wunschfeld_gliederung(aid, kennung, werk),
                 neu_schreiben_html(aid, None, gl_grund)
                 if gl_grund and werk.get("gliederung_stand") == "geplant" else ""]
        if szenen:
            zeilen = []
            for s in szenen:
                nr = s.get("nr")
                if not isinstance(nr, int) or isinstance(nr, bool):
                    continue
                aufgegeben = (' <span class="chip fehler">braucht deinen Wunsch</span>'
                              if s.get("stand") == "geplant" and kurztext(s.get("aufgegeben")) else "")
                zeilen.append(f'<a href="{e(seite_url(aid, str(nr)))}"><b>Szene {nr}</b> {e(str(s.get("kurz") or ""))} '
                              f'{stand_chip(str(s.get("stand") or ""), bool(s.get("fehler")))}{aufgegeben}</a>')
            teile.append(f'<h2>Szenen</h2><div class="wb-szenen">{"".join(zeilen)}</div>')
        teile.append(neu_bauen_html(aid, werk))
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
        grund = kurztext(s.get("aufgegeben"))
        if grund and stand == "geplant":
            teile.append(neu_schreiben_html(aid, nr, grund))
        teile.append('<h3>Sprechtext</h3>' + (f'<p class="wb-text">{e(sprech)}</p>' if sprech
                                              else '<p class="meta">Der Text ist noch nicht geschrieben.</p>'))
        paare = aussagen(s.get("belege"))
        if paare:                                    # I3: jede Aussage mit ihrer Quelle, direkt unter dem Text
            teile.append("<h3>Aussagen und Quellen</h3><ul>" + "".join(
                f'<li>{e(a)} <span class="meta">Quelle: {e(q)}</span></li>' for a, q in paare) + "</ul>")
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

    async def uebergabe_kopf(request):
        """Gemeinsamer Kopf von Ja und Nein: -> (id, None) oder (None, Fehlerseite). Verlangt (in dieser Reihenfolge)
        eine echte Anmeldung (Sitzungsgeheimnis + Sitzung), eine Anfrage von dieser Seite, die CSRF-Marke und das
        Schreibrecht wie bei den anderen Aktionen der Seite."""
        if not anmeldung_aktiv(request):
            return None, ui._fehlerseite(403, "Nicht angemeldet", UEBERGABE_NUR_MIT_ANMELDUNG + " Nichts wurde getan.")
        if not gleiche_herkunft(request):
            return None, ui._fehlerseite(403, "Abgewiesen", "Die Anfrage kommt nicht von dieser Seite.")
        form = await request.form()
        if not ui._csrf_ok(form):
            return None, ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        if not darf_entscheiden():
            return None, ui._fehlerseite(403, "Nicht erlaubt", "Diese Anmeldung darf hier nichts ändern.")
        kennung = str(form.get("id") or "")
        if not _AID.fullmatch(kennung):
            return None, nicht_gefunden()
        if not ui_reels.eigene_firma():
            return None, keine_firma()
        return kennung, None

    def zurueck(kennung: str, entschieden: bool = False) -> RedirectResponse:
        abfrage = {"hinweis": "uebergabe", "u": kennung, **({"e": "1"} if entschieden else {})}
        return RedirectResponse(f"{BASIS}?{urllib.parse.urlencode(abfrage)}#uebergaben", status_code=303)

    def ausfall(f: Exception):
        logging.getLogger("sales-ui").error("Uebergabe-Aktion fehlgeschlagen: %s", type(f).__name__)
        if isinstance(f, video_uebergabe.NICHT_EINGERICHTET):
            return ui._fehlerseite(503, "Nicht möglich", video_uebergabe.SATZ_NICHT_EINGERICHTET)
        return ui._fehlerseite(503, "Nicht möglich", video_uebergabe.SATZ_UNKLAR)

    @ui._gesichert_seite
    async def uebergabe_ja(request):
        kennung, abgelehnt = await uebergabe_kopf(request)
        if abgelehnt is not None:
            return abgelehnt
        try:
            art, _wert = await run_in_threadpool(video_uebergabe.bestaetigen, kennung, ui._ui_akteur(request))
        except Exception as f:                              # noqa: BLE001 - kein Satz "nichts angelegt": Ausgang unklar
            return ausfall(f)
        return zurueck(kennung, art == "entschieden")

    @ui._gesichert_seite
    async def uebergabe_nein(request):
        kennung, abgelehnt = await uebergabe_kopf(request)
        if abgelehnt is not None:
            return abgelehnt
        try:
            if await run_in_threadpool(video_uebergabe.verwerfen, kennung, ui._ui_akteur(request)):
                return zurueck(kennung)
            art, _ = await run_in_threadpool(video_uebergabe.warum_nicht, kennung)
        except Exception as f:                              # noqa: BLE001
            return ausfall(f)
        return zurueck(kennung, art == "entschieden")

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

    @ui._gesichert_seite
    async def neu_schreiben(request):
        """C1: neuer Wunsch an eine aufgegebene Szene (mit nr) oder Gliederung (ohne nr)."""
        form, aid, nr, _, abgelehnt = await aktion(request, False)
        if abgelehnt is not None:
            return abgelehnt
        wunsch = wunsch_aus(form)
        if wunsch is None:
            return zu_lang()
        if not wunsch:
            return ui._fehlerseite(422, "Nicht möglich", "Schreib bitte auf, was anders werden soll.")
        pfad = f"/werkbank/{aid}/szene/{int(nr)}/wunsch" if nr else f"/werkbank/{aid}/gliederung/wunsch"
        return await senden(request, aid, nr, pfad, {"wunsch": wunsch}, "neu")

    @ui._gesichert_seite
    async def neu_bauen(request):
        """I1: "Video neu zusammenfügen" nach einem gescheiterten Zusammenfuegen."""
        form, aid, _, _, abgelehnt = await aktion(request, False)
        if abgelehnt is not None:
            return abgelehnt
        return await senden(request, aid, "", f"/werkbank/{aid}/video/neu-bauen", {}, "neu_bauen")

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
        Route("/aktion/werkbank-neu-schreiben", neu_schreiben, methods=["POST"]),
        Route("/aktion/werkbank-neu-bauen", neu_bauen, methods=["POST"]),
        Route("/aktion/werkbank-uebergabe-ja", uebergabe_ja, methods=["POST"]),
        Route("/aktion/werkbank-uebergabe-nein", uebergabe_nein, methods=["POST"]),
    ]
