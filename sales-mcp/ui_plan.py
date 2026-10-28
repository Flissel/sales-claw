"""Kampagnenkalender im Marketing-Pult (17.10.2026, Marketing-Migration 071).

Betreiber-Entscheid: eigene Seite /marketing/plan, der Agent darf nur
vorschlagen, bestaetigt wird hier. Ein Planeintrag versendet nichts - was
hinausgeht, laeuft weiter ueber Entwurf und Freigabe. Alle Daten kommen ueber
marketing_pult (/api/pult/plan); diese Datei kennt keine Marketing-Tabelle.
Wie der Rest von sales-ui ohne JavaScript: jede Aktion ist ein eigenes Formular.
"""
from __future__ import annotations

import urllib.parse
from datetime import date, timedelta

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import marketing_mandant
import marketing_pult

ARTEN = {"newsletter": "Newsletter", "post": "Post", "podcast": "Podcast", "video": "Video",
         "aktion": "Aktion", "sonstiges": "Sonstiges"}
STATUS = {"vorschlag": "Vorschlag vom Agenten", "geplant": "geplant", "verschoben": "verschoben",
          "erledigt": "erledigt", "abgesagt": "abgesagt"}
# Knopf -> Status an die API. "verschieben" schickt stattdessen das neue Datum.
AKTIONEN = {"uebernehmen": "geplant", "erledigt": "erledigt", "absagen": "abgesagt"}
MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember")
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def monat_lesen(roh: str | None, heute: date | None = None) -> date:
    """'JJJJ-MM' -> erster Tag des Monats; alles andere -> aktueller Monat."""
    heute = heute or date.today()
    try:
        j, m = (int(x) for x in str(roh or "").split("-"))
        if 2000 <= j <= 2100 and 1 <= m <= 12:
            return date(j, m, 1)
    except ValueError:
        pass
    return heute.replace(day=1)


def monat_ende(erster: date) -> date:
    return (erster.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def nachbar(erster: date, schritt: int) -> str:
    if schritt < 0:
        return (erster - timedelta(days=1)).strftime("%Y-%m")
    return (monat_ende(erster) + timedelta(days=1)).strftime("%Y-%m")


def art_lesen(roh: str | None) -> str | None:
    """Rohwert aus der Adresse -> Art aus ARTEN, sonst None (= Reiter "Alle")."""
    return roh if isinstance(roh, str) and roh in ARTEN else None


def zaehlen(eintraege: list[dict], abgesagte: bool) -> dict[str, int]:
    """Anzahl je Reiter. Unbekannte Arten zaehlen als "sonstiges"; Abgesagte nur auf Wunsch."""
    z = {"alle": 0, **{k: 0 for k in ARTEN}}
    for p in eintraege:
        if p.get("status") == "abgesagt" and not abgesagte:
            continue
        art = p.get("art")
        z["alle"] += 1
        z[art if art in ARTEN else "sonstiges"] += 1
    return z


def _tag(roh) -> date | None:
    try:
        return date.fromisoformat(str(roh or "")[:10])
    except ValueError:
        return None


def nach_tagen(eintraege: list[dict]) -> list[tuple[date | None, list[dict]]]:
    """Gruppen je Tag aufsteigend; Eintraege ohne lesbares Datum am Ende als (None, [...])."""
    gruppen: dict[date | None, list[dict]] = {}
    for p in eintraege:
        gruppen.setdefault(_tag(p.get("datum")), []).append(p)
    fertig = [(t, gruppen[t]) for t in sorted(k for k in gruppen if k is not None)]
    if None in gruppen:
        fertig.append((None, gruppen[None]))
    return fertig


def datum_aus_teilen(tag, monat, jahr) -> str | None:
    """Tag/Monat/Jahr aus dem Formular -> ISO-Datum, sonst None (31. Februar usw.)."""
    try:
        return date(int(jahr), int(monat), int(tag)).isoformat()
    except (ValueError, TypeError):
        return None


def plan_pfad(erster: date, art: str | None, abgesagte: bool) -> str:
    """Adresse der Seite mit Monat, Reiter und Abgesagte-Schalter in fester Reihenfolge."""
    q = [("monat", f"{erster:%Y-%m}")]
    if art in ARTEN:
        q.append(("art", art))
    if abgesagte:
        q.append(("abgesagt", "1"))
    return "/marketing/plan?" + urllib.parse.urlencode(q)


def datum_felder(praefix: str, vorgabe: date, heute: date | None = None) -> str:
    """Drei Auswahlfelder Tag / Monat (ausgeschrieben) / Jahr statt <input type=date>.

    Der Browser zeigt type=date in der Sprache des Betriebssystems, nicht der Seite;
    die Auswahl bleibt deutsch. Namen: {praefix}_tag, _monat, _jahr."""
    heute = heute or date.today()

    def wahl(name: str, label: str, werte: list[tuple[int, str]], aktuell: int) -> str:
        opt = "".join(f'<option value="{v}"{" selected" if v == aktuell else ""}>{t}</option>' for v, t in werte)
        return f'<select name="{praefix}_{name}" aria-label="{label}">{opt}</select>'
    return ('<span class="plan-datum">'
            + wahl("tag", "Tag", [(i, str(i)) for i in range(1, 32)], vorgabe.day)
            + wahl("monat", "Monat", [(i + 1, n) for i, n in enumerate(MONATE)], vorgabe.month)
            + wahl("jahr", "Jahr", [(j, str(j)) for j in sorted({*range(heute.year, heute.year + 3), vorgabe.year})], vorgabe.year)
            + '</span>')


def vergangen(iso: str) -> bool:
    """Gestern ist noch erlaubt (gleiche Grenze wie plan_anlegen in der Marketing-API)."""
    return date.fromisoformat(iso) < date.today() - timedelta(days=1)


# Echte Kampagnen (Betreiber 28.10.2026, Marketing-Migration 095): Ziel, Zielgruppe per Auswahl,
# Zeitraum; der Agent plant die Beitraege komplett. Stand, Reaktionen, Reichweite je Kampagne.
ZIELGRUPPEN = {"sales": "Kontakte aus Sales", "oeffentlich": "Öffentlich (Kanäle)",
               "verteiler": "Newsletter-Verteiler"}
KAMPAGNEN_STATUS = {"in_planung": "Agent plant", "geplant": "geplant", "laeuft": "läuft",
                    "abgeschlossen": "abgeschlossen", "abgesagt": "abgesagt"}
KAMPAGNEN_AKTIONEN = {"neu_planen": "in_planung", "starten": "laeuft", "abschliessen": "abgeschlossen",
                      "absagen": "abgesagt"}


def kampagnen_wirkung(beitraege: list[dict]) -> dict:
    """Reichweite und Reaktionen aus der Sales-Datenbank: Newsletter-Beitraege mit Entwurf -> gesendete
    Mails an Kontakte (Reichweite) und Kontakte, die danach geantwortet haben (Reaktionen). Posts zaehlen
    als veroeffentlicht, sobald der Plan-Eintrag erledigt ist; Klicks/Aufrufe liefern die Kanaele noch nicht."""
    import server
    inhalte = [str(b["inhalt"]) for b in beitraege if b.get("inhalt")]
    gesendet = reaktionen = 0
    if inhalte:
        z = server._q(
            "select count(*) filter (where d.status = 'sent') as gesendet, "
            "       count(distinct d.lead_id) filter (where exists (select 1 from activities a "
            "         where a.lead_id = d.lead_id and a.type = 'kundenantwort' "
            "           and a.created_at > coalesce(d.sent_at, d.created_at))) as reaktionen "
            "  from drafts d where d.newsletter::text = any(%s)", (inhalte,))[0]
        gesendet, reaktionen = int(z["gesendet"] or 0), int(z["reaktionen"] or 0)
    veroeffentlicht = sum(1 for b in beitraege if b.get("status") == "erledigt"
                          and b.get("art") in ("post", "video", "podcast"))
    return {"gesendet": gesendet, "reaktionen": reaktionen, "veroeffentlicht": veroeffentlicht}


def routen(ui) -> list:
    e = ui._e

    def fehler(f: marketing_pult.PultFehler):
        if f.art == "nicht_verbunden":
            return ui._fehlerseite(503, "Marketing nicht verbunden",
                                   "Die Verbindung zur Marketing-API ist nicht eingerichtet oder der Schlüssel stimmt nicht.")
        if f.art == "abgelehnt":
            return ui._fehlerseite(422, "Nicht möglich", e(f.grund))
        return ui._fehlerseite(503, "Marketing gerade nicht erreichbar",
                               "Die Marketing-API antwortet nicht. Sales läuft normal weiter.")

    def csrf() -> str:
        return f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'

    def zurueck_ziel(form) -> str:
        z = str(form.get("zurueck") or "")
        return z if marketing_mandant.ziel_ok(z) and z.startswith("/marketing/plan") else "/marketing/plan"

    def knoepfe(p: dict, zurueck: str) -> str:
        pid = e(urllib.parse.quote(str(p.get("id") or ""), safe=""))
        status = p.get("status")
        if status in ("erledigt", "abgesagt"):
            return ""

        def knopf(aktion: str, text: str, primaer: bool = False) -> str:
            klasse = ' class="primaer"' if primaer else ""
            return (f'<form method="post" action="/marketing/plan/{pid}" class="aktion">{csrf()}'
                    f'<input type="hidden" name="zurueck" value="{e(zurueck)}">'
                    f'<button type="submit" name="aktion" value="{aktion}"{klasse}>{text}</button></form>')
        teile = ([knopf("uebernehmen", "Übernehmen", True), knopf("absagen", "Verwerfen")] if status == "vorschlag"
                 else [knopf("erledigt", "Erledigt"), knopf("absagen", "Absagen")])
        teile.append(f'<details class="verschieben"><summary>Verschieben</summary>'
                     f'<form method="post" action="/marketing/plan/{pid}" class="aktion">{csrf()}'
                     f'<input type="hidden" name="zurueck" value="{e(zurueck)}">'
                     f'{datum_felder("neu", max(_tag(p.get("datum")) or date.today(), date.today()))}'
                     f'<button type="submit" name="aktion" value="verschieben">Verschieben</button></form>'
                     '</details>')
        return "".join(teile)

    def karte(p: dict, zurueck: str) -> str:
        status = str(p.get("status") or "")
        art = p.get("art")
        notiz = str(p.get("notiz") or "")
        chips = [f'<span class="plan-chip art">{e(ARTEN.get(art, ARTEN["sonstiges"]))}</span>',
                 f'<span class="plan-chip status {e(status)}">{e(STATUS.get(status, status))}</span>']
        if p.get("angelegt_von") == "agent" and status != "vorschlag":
            chips.append('<span class="plan-chip">vom Agenten</span>')
        return (f'<article class="plan-karte plan-{e(status)}"><div class="plan-chips">{"".join(chips)}</div>'
                f'<p class="plan-titel"><b>{e(str(p.get("titel") or ""))}</b></p>'
                + (f'<p class="plan-notiz">{e(notiz)}</p>' if notiz else "")
                + (f'<p><a href="/marketing/entwurf/{e(urllib.parse.quote(str(p["inhalt"]), safe=""))}">'
                   'Zum Entwurf</a></p>' if p.get("inhalt") else "")
                + ('<p><a href="/marketing/podcast">Folgen ansehen</a></p>' if art == "podcast" else "")
                + f'<div class="plan-knoepfe">{knoepfe(p, zurueck)}</div></article>')

    def kampagnen_html(kampagnen: list[dict], zurueck: str) -> str:
        teile = ['<section class="kampagnen" id="kampagnen"><h2>Kampagnen</h2>']
        if not kampagnen:
            teile.append('<p class="meta">Noch keine Kampagne. Leg eine an: Ziel, Zielgruppe, Zeitraum - '
                         'den Rest plant der Agent.</p>')
        for k in kampagnen:
            kid = e(urllib.parse.quote(str(k.get("id") or ""), safe=""))
            beitraege = [b for b in k.get("beitraege") or [] if isinstance(b, dict)]
            try:
                w = kampagnen_wirkung(beitraege)
            except Exception:  # noqa: BLE001 - die Zahlen sind Beiwerk, die Seite faellt nicht mit
                w = None
            stand = {}
            for b in beitraege:
                stand[b.get("status")] = stand.get(b.get("status"), 0) + 1
            stand_text = ", ".join(f"{n} {STATUS.get(s, s)}" for s, n in stand.items()) or "noch keine Beiträge"
            zeilen = "".join(
                f'<li>{e(str(b.get("datum") or ""))} · {e(ARTEN.get(b.get("art"), "Sonstiges"))} · '
                f'<b>{e(str(b.get("titel") or ""))}</b> · {e(STATUS.get(b.get("status"), b.get("status") or ""))}'
                + (f' · Entwurf: {e(str(b.get("inhalt_status")))}' if b.get("inhalt_status") else "")
                + '</li>' for b in beitraege)
            wirkung = ('<p class="meta">Wirkung: nicht lesbar.</p>' if w is None else
                       f'<p class="meta">Reichweite: {w["gesendet"]} Mails gesendet, {w["veroeffentlicht"]} '
                       f'Beiträge veröffentlicht (Klicks/Aufrufe liefern die Kanäle noch nicht) · '
                       f'Reaktionen: {w["reaktionen"]} Kontakte haben geantwortet</p>')

            def knopf(aktion: str, text: str) -> str:
                return (f'<form method="post" action="/marketing/plan/kampagne/{kid}/status" class="aktion">'
                        f'{csrf()}<input type="hidden" name="zurueck" value="{e(zurueck)}">'
                        f'<button type="submit" name="aktion" value="{aktion}">{text}</button></form>')
            status = str(k.get("status") or "")
            knoepfe = "" if status in ("abgeschlossen", "abgesagt") else (
                knopf("neu_planen", "Neu planen lassen") + knopf("starten", "Läuft")
                + knopf("abschliessen", "Abschließen") + knopf("absagen", "Absagen"))
            teile.append(
                f'<article class="plan-karte kampagne"><div class="plan-chips">'
                f'<span class="plan-chip status">{e(KAMPAGNEN_STATUS.get(status, status))}</span>'
                f'<span class="plan-chip art">{e(ZIELGRUPPEN.get(k.get("zielgruppe"), k.get("zielgruppe") or ""))}</span>'
                f'</div><p class="plan-titel"><b>{e(str(k.get("name") or ""))}</b> · '
                f'{e(str(k.get("von") or ""))} bis {e(str(k.get("bis") or ""))}</p>'
                + (f'<p class="plan-notiz">{e(str(k.get("ziel")))}</p>' if k.get("ziel") else "")
                + f'<p class="meta">Stand: {e(stand_text)}</p>{wirkung}'
                + (f'<details><summary>Beiträge ({len(beitraege)})</summary><ul>{zeilen}</ul></details>'
                   if beitraege else "")
                + f'<div class="plan-knoepfe">{knoepfe}</div></article>')
        heute = date.today()
        gruppen = "".join(f'<option value="{k}">{e(t)}</option>' for k, t in ZIELGRUPPEN.items())
        teile.append(
            '<details class="plan-form"><summary>+ Neue Kampagne</summary>'
            f'<form method="post" action="/marketing/plan/kampagne" class="aktion">{csrf()}'
            f'<input type="hidden" name="zurueck" value="{e(zurueck)}">'
            '<label>Name <input type="text" name="name" required maxlength="120"></label>'
            '<label>Ziel <textarea name="ziel" maxlength="2000" rows="2" '
            'placeholder="Was soll die Kampagne erreichen?"></textarea></label>'
            f'<label>Zielgruppe <select name="zielgruppe">{gruppen}</select></label>'
            f'<fieldset><legend>Von</legend>{datum_felder("von", heute, heute)}</fieldset>'
            f'<fieldset><legend>Bis</legend>{datum_felder("bis", heute + timedelta(days=28), heute)}</fieldset>'
            '<button type="submit" class="primaer">Anlegen - Agent plant</button></form>'
            '<p><small>Der Marketing-Agent schlägt die Beiträge vor (meist innerhalb von 10 Minuten) und '
            'meldet sich im Telegram-Chat. Versendet wird nichts ohne Freigabe.</small></p></details>')
        teile.append('</section>')
        return "".join(teile)

    @ui._gesichert_seite
    async def kampagne_neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        name = str(form.get("name") or "").strip()
        gruppe = str(form.get("zielgruppe") or "")
        von = datum_aus_teilen(form.get("von_tag"), form.get("von_monat"), form.get("von_jahr"))
        bis = datum_aus_teilen(form.get("bis_tag"), form.get("bis_monat"), form.get("bis_jahr"))
        if not name or gruppe not in ZIELGRUPPEN or not von or not bis:
            return ui._fehlerseite(422, "Nicht möglich", "Name, Zielgruppe und ein gültiger Zeitraum sind nötig.")
        if bis < von:
            return ui._fehlerseite(422, "Nicht möglich", "Das Ende liegt vor dem Beginn.")
        try:
            m, _ = await marketing_mandant.firma(request)
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/kampagnen",
                                    {"mandant": m, "name": name, "ziel": str(form.get("ziel") or ""),
                                     "zielgruppe": gruppe, "von": von, "bis": bis,
                                     "von_wer": ui._ui_akteur(request)})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(zurueck_ziel(form) + "#kampagnen", status_code=303)

    @ui._gesichert_seite
    async def kampagne_status(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        status = KAMPAGNEN_AKTIONEN.get(str(form.get("aktion") or ""))
        if not status:
            return ui._fehlerseite(422, "Nicht möglich", "Unbekannte Aktion.")
        kid = urllib.parse.quote(request.path_params["kid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/kampagnen/{kid}/status",
                                    {"status": status})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(zurueck_ziel(form) + "#kampagnen", status_code=303)

    @ui._gesichert_seite
    async def plan(request):
        erster = monat_lesen(request.query_params.get("monat"))
        art = art_lesen(request.query_params.get("art"))
        abgesagte = request.query_params.get("abgesagt") == "1"
        letzter = monat_ende(erster)
        try:
            m, liste = await marketing_mandant.firma(request)
            q = urllib.parse.urlencode({"mandant": m, "von": erster.isoformat(), "bis": letzter.isoformat()})
            d = await run_in_threadpool(marketing_pult.anfrage, "GET", f"/plan?{q}")
        except marketing_pult.PultFehler as f:
            return fehler(f)
        try:
            kd = await run_in_threadpool(marketing_pult.anfrage, "GET",
                                         f"/kampagnen?{urllib.parse.urlencode({'mandant': m})}")
            kampagnen = [k for k in (kd.get("kampagnen") if isinstance(kd, dict) else None) or []
                         if isinstance(k, dict)]
        except marketing_pult.PultFehler:
            kampagnen = []      # Kampagnen sind ein Zusatz: der Kalender bleibt sichtbar
        eintraege = [p for p in (d.get("eintraege") if isinstance(d, dict) else None) or [] if isinstance(p, dict)]
        hier = plan_pfad(erster, art, abgesagte)
        monat_name = f"{MONATE[erster.month - 1]} {erster.year}"
        z = zaehlen(eintraege, abgesagte)
        sichtbar = [p for p in eintraege if abgesagte or p.get("status") != "abgesagt"]
        gewaehlt = [p for p in sichtbar
                    if art is None or (p.get("art") if p.get("art") in ARTEN else "sonstiges") == art]
        vorschlaege = sum(1 for p in eintraege if p.get("status") == "vorschlag")

        untersatz = (f'<b>{vorschlaege} {"Vorschlag" if vorschlaege == 1 else "Vorschläge"} vom Agenten</b> '
                     f'{"wartet" if vorschlaege == 1 else "warten"} in {e(monat_name)} auf dich: '
                     'übernehmen oder verwerfen.' if vorschlaege else "Alles im Griff: nichts wartet auf dich.")
        kopf = ('<header class="plan-kopf">'
                f'<p class="plan-unter">{untersatz}</p>'
                '<a class="knopf" href="#neu">+ Neuer Eintrag</a></header>')
        # Die Zahl steht in Klammern direkt am Namen ("Podcast (1)"), damit sie ohne Gestaltung lesbar bleibt.
        reiter = ('<nav class="plan-reiter" aria-label="Art">'
                  + "".join(
                      f'<a href="{e(plan_pfad(erster, k, abgesagte))}"'
                      + (' class="aktiv" aria-current="page"' if k == art else "")
                      + f'>{e(t)} ({z[k or "alle"]})</a>'
                      for k, t in [(None, "Alle"), *ARTEN.items()])
                  + '</nav>')
        vor = monat_lesen(nachbar(erster, -1))
        nach = monat_lesen(nachbar(erster, 1))
        heute = date.today()
        monatsleiste = ('<div class="plan-monat">'
                        f'<a href="{e(plan_pfad(vor, art, abgesagte))}">&lsaquo; Vormonat</a>'
                        f'<span class="plan-monatsname">{e(monat_name)}</span>'
                        f'<a href="{e(plan_pfad(nach, art, abgesagte))}">Nächster Monat &rsaquo;</a>'
                        + (f'<a href="{e(plan_pfad(heute.replace(day=1), art, abgesagte))}">Heute</a>'
                           if erster != heute.replace(day=1) else "")
                        + (f'<a href="{e(plan_pfad(erster, art, False))}">Abgesagte ausblenden</a>' if abgesagte
                           else f'<a href="{e(plan_pfad(erster, art, True))}">Abgesagte zeigen</a>')
                        + '</div>')

        if gewaehlt:
            agenda = ""
            for tag, gruppe in nach_tagen(gewaehlt):
                if tag is None:
                    kopfzeile = "Ohne Datum"
                else:
                    kopfzeile = f"{WOCHENTAGE[tag.weekday()]} {tag.day}. {MONATE[tag.month - 1]}"
                    if tag == heute:
                        kopfzeile += ' <span class="plan-chip heute">Heute</span>'
                agenda += (f'<section class="plan-tag"><h2>{kopfzeile}</h2>'
                           + "".join(karte(p, hier) for p in gruppe) + '</section>')
        elif not eintraege:
            agenda = (f'<div class="plan-leer"><p>In {e(monat_name)} ist noch nichts geplant.</p>'
                      '<a class="knopf" href="#neu">Ersten Eintrag anlegen</a></div>')
        elif not sichtbar:
            agenda = (f'<div class="plan-leer"><p>In {e(monat_name)} gibt es nur abgesagte Einträge.</p>'
                      f'<a class="knopf" href="{e(plan_pfad(erster, art, True))}">Abgesagte zeigen</a></div>')
        else:
            agenda = (f'<div class="plan-leer"><p>Kein {e(ARTEN[art or "sonstiges"])}-Eintrag in {e(monat_name)}.</p>'
                      f'<a class="knopf" href="{e(plan_pfad(erster, None, abgesagte))}">Alle Arten zeigen</a></div>')

        vorgabe_art = art or "newsletter"
        arten = "".join(f'<option value="{k}"{" selected" if k == vorgabe_art else ""}>{e(t)}</option>'
                        for k, t in ARTEN.items())
        vorgabe = max(erster, heute)  # nie ein vergangener Tag: das wäre ein 422
        formular = (f'<section id="neu" class="plan-form"><h2>Neuer Eintrag</h2>'
                    f'<form method="post" action="/marketing/plan/neu" class="aktion">{csrf()}'
                    f'<input type="hidden" name="zurueck" value="{e(hier)}">'
                    f'<input type="hidden" name="reiter" value="{e(art or "")}">'
                    f'<fieldset><legend>Wann</legend>{datum_felder("datum", vorgabe, heute)}</fieldset>'
                    '<fieldset><legend>Was</legend>'
                    f'<label>Art <select name="art">{arten}</select></label>'
                    '<label>Titel <input type="text" name="titel" required maxlength="120"></label>'
                    '<label>Notiz <textarea name="notiz" maxlength="1000" rows="2"></textarea></label>'
                    '</fieldset><button type="submit">Eintragen</button></form>'
                    '<p><small>Ein Eintrag ist nur ein Plan, er verschickt nichts. Hinaus geht weiterhin nur, '
                    'was über Entwurf und Freigabe läuft.</small></p></section>')
        return ui._seite("Kampagnenplan", marketing_mandant.umschalter(e, ui.CSRF_TOKEN, m, liste, hier)
                         + kampagnen_html(kampagnen, hier)
                         + '<h2>Kalender</h2>' + kopf + reiter + monatsleiste
                         + f'<div class="plan-spalten"><div class="plan-agenda">{agenda}</div>{formular}</div>')

    @ui._gesichert_seite
    async def neu(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        datum = datum_aus_teilen(form.get("datum_tag"), form.get("datum_monat"), form.get("datum_jahr"))
        art = str(form.get("art") or "")
        titel = str(form.get("titel") or "").strip()
        if not datum:
            return ui._fehlerseite(422, "Nicht möglich", "Dieses Datum gibt es nicht. Bitte Tag, Monat und Jahr prüfen.")
        if art not in ARTEN or not titel:
            return ui._fehlerseite(422, "Nicht möglich", "Datum, Art und Titel sind nötig.")
        if vergangen(datum):
            return ui._fehlerseite(422, "Nicht möglich", "Das Datum liegt in der Vergangenheit.")
        try:
            m, _ = await marketing_mandant.firma(request)
            await run_in_threadpool(marketing_pult.anfrage, "POST", "/plan",
                                    {"mandant": m, "datum": datum, "art": art, "titel": titel,
                                     "notiz": str(form.get("notiz") or "")})
        except marketing_pult.PultFehler as f:
            return fehler(f)
        reiter = art_lesen(str(form.get("reiter") or ""))
        return RedirectResponse(plan_pfad(date.fromisoformat(datum).replace(day=1),
                                          art if reiter == art else None, False), status_code=303)

    @ui._gesichert_seite
    async def aendern(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "Abgewiesen", "Fehlende oder falsche CSRF-Marke.")
        aktion = str(form.get("aktion") or "")
        if aktion == "verschieben":
            datum = datum_aus_teilen(form.get("neu_tag"), form.get("neu_monat"), form.get("neu_jahr"))
            if not datum:
                return ui._fehlerseite(422, "Nicht möglich", "Bitte ein gültiges neues Datum wählen.")
            if vergangen(datum):
                return ui._fehlerseite(422, "Nicht möglich", "Das Datum liegt in der Vergangenheit.")
            daten = {"datum": datum}
        elif aktion in AKTIONEN:
            daten = {"status": AKTIONEN[aktion]}
        else:
            return ui._fehlerseite(422, "Nicht möglich", "Unbekannte Aktion.")
        pid = urllib.parse.quote(request.path_params["pid"], safe="")
        try:
            await run_in_threadpool(marketing_pult.anfrage, "POST", f"/plan/{pid}", daten)
        except marketing_pult.PultFehler as f:
            return fehler(f)
        return RedirectResponse(zurueck_ziel(form), status_code=303)

    return [
        Route("/marketing/plan", plan),
        Route("/marketing/plan/neu", neu, methods=["POST"]),
        # Vor /marketing/plan/{pid}: sonst faengt die Platzhalter-Route „kampagne" als pid ab.
        Route("/marketing/plan/kampagne", kampagne_neu, methods=["POST"]),
        Route("/marketing/plan/kampagne/{kid}/status", kampagne_status, methods=["POST"]),
        Route("/marketing/plan/{pid}", aendern, methods=["POST"]),
    ]
