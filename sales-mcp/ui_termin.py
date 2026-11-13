"""Termin-Seite /termine/{uid} (Meeting-Mittelpunkt, Variante C) und ihre JSON-Ansicht.

Oben Titel, Kunde, Zeit und der grosse Beitreten-Knopf; darunter die Reiter
Details, Briefing, Verlauf und (sobald es eine gibt) Mitschrift. `GET
/termine/{uid}.json` liefert dieselbe Akte. Gesperrte Kontakte fehlen in
Seite und JSON (termin_akte.lesen). Alles Fremde (Titel, Namen, Briefing,
Auswertung, Mitschrift) geht ueber html.escape; der Beitreten-Link nur, wenn er
mit http(s) beginnt. Der Passcode steht auf der Seite (Felix' eigene Seite),
nie in einem Log.

Schreibwege (POST, Formfeld `aktion` + `csrf`) gehen immer mit 303 zurueck auf
die Seite; Meldungen reisen als kurzer Text im Query mit. In `activities`
landet nur, was Felix hier bestaetigt (Termin-Zeile fuer Kalendertermine,
Termin-Ergebnis, Wiedervorlage)."""
from __future__ import annotations

import html
import json
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

import bildschirm
import historie
import post_struktur
import server
import termin_akte
from ui_kalender import _gesichert_json, _grund, _ok


STATUS_TEXT = {"geplant": "geplant", "wartet_auf_einlass": "wartet auf Einlass",
               "laeuft": "läuft", "fertig": "fertig", "ohne_aufnahme": "ohne Aufnahme",
               "fehlgeschlagen": "fehlgeschlagen", "kein_link": "kein Link"}
VORSCHLAG_TEXT = {"offen": "offen", "bestaetigt": "übernommen", "verworfen": "verworfen"}
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
FELD_NAMEN = {"title": "Position", "company": "Firma"}   # Whitelist der Spalten
_REITER = ("details", "briefing", "verlauf", "mitschrift", "bildschirm")
STATIK = Path(__file__).resolve().parent / "static" / "termin_bilder"
STATIK_DATEIEN = {"bilder.js": "text/javascript"}
_BILDSTATUS_LIVE = ("wartet_auf_einlass", "laeuft")
_SCHALTER_STATUS = ("geplant", "kein_link", "wartet_auf_einlass", "laeuft")
MELDUNGEN = {
    "unbekannte_aktion": "Unbekannte Aktion.",
    "kein_bot_gesperrt": "„Kein Bot“ lässt sich nach dem Start nicht mehr ändern.",
    "kein_vorschlag": "Diesen offenen Vorschlag gibt es nicht (mehr).",
    "ohne_kontakt": "Der Vorschlag gehört zu keinem Kontakt.",
    "gesperrt": "Dieser Kontakt ist inzwischen gesperrt – nichts übernommen.",
    "keine_terminzeile": "Zu diesem Termin gibt es keine Termin-Zeile im CRM.",
    "schon_gebucht": "Zu diesem Termin ist das Ergebnis schon gebucht.",
    "nicht_gebucht": "Der Vorschlag konnte nicht übernommen werden.",
    "datum_ungueltig": "Das Datum der Wiedervorlage ist ungültig.",
    "feld_ungueltig": "Dieses Feld lässt sich nicht übernehmen.",
    "keine_mitschrift": "Es gibt keine Mitschrift (mehr).",
    # Final-Review C1: die Oberflaeche setzt nur den Status; den Bot holt der
    # Taktgeber in seiner naechsten Runde aus dem Termin.
    "aufnahme_beendet": "Aufnahme beendet – der Bot verlässt den Termin in Kürze.",
    "bildschirm_nur_jitsi": "Bildschirm auswerten geht in Stufe 1 nur bei Jitsi-Terminen.",
    "bildschirm_gesperrt": "Bildschirm auswerten lässt sich bei diesem Terminstatus nicht mehr ändern.",
    "bildschirm_wert": "Unklar, ob Bildschirm auswerten an oder aus sein soll – nichts geändert.",
    "bild_unbekannt": "Dieses Bild gibt es nicht (mehr).",
}
_VERLAUF_MAX = 20
_TEXT_MAX = 300


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert), quote=True)


def _pfad(uid: str) -> str:
    return f"/termine/{quote(uid, safe='')}"


def _link_ok(link) -> str:
    """Nur http(s) mit Host - sonst leer (kein javascript:, kein data:)."""
    t = urlsplit(str(link or "").strip())
    return str(link).strip() if t.scheme in ("http", "https") and t.netloc else ""


def _zeit(a: dict) -> str:
    from kalender_sicht import _zone
    b, e = a["beginn"].astimezone(_zone()), a["ende"].astimezone(_zone())
    ende = f"{e:%H:%M}" if e.date() == b.date() else f"{e:%d.%m. %H:%M}"
    return f"{WOCHENTAGE[b.weekday()]} {b:%d.%m.%Y}, {b:%H:%M}–{ende} Uhr"


def _md(text) -> str:
    """Kleines, sicheres Markdown: erst escapen, dann nur Ueberschriften,
    Listen, **fett** und Absaetze erkennen."""
    aus, liste = [], False
    for roh in str(text or "").splitlines():
        z = _e(roh.strip())
        z = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", z)
        punkt = re.match(r"^[-*] (.+)$", z)
        if liste and not punkt:
            aus.append("</ul>")
            liste = False
        if punkt:
            if not liste:
                aus.append("<ul>")
                liste = True
            aus.append(f"<li>{punkt.group(1)}</li>")
        elif z.startswith("#"):
            aus.append(f"<h3>{z.lstrip('#').strip()}</h3>")
        elif z:
            aus.append(f"<p>{z}</p>")
    if liste:
        aus.append("</ul>")
    return "".join(aus)


def _daten(v: dict) -> dict:
    d = v.get("daten")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            d = {}
    return d if isinstance(d, dict) else {}


def _json_sicher(akte: dict) -> dict:
    return json.loads(server._json(akte))


def _kunden(akte: dict) -> list[dict]:
    ids = sorted({t["lead_id"] for t in akte["teilnehmer"] if t["lead_id"]})
    if not ids:
        return []
    return server._q("select id, name, company from leads where id = any(%s::uuid[]) "
                     "order by name", (ids,))


# ---------------------------------------------------------------- Seite ----

def _kopf(akte: dict, kunden: list[dict], schreiben: bool) -> str:
    titel = akte["titel"] or akte["thema"] or "Kundentermin"
    wer = "; ".join(f"{_e(k['name'])}" + (f" ({_e(k['company'])})" if k["company"] else "")
                    for k in kunden) or "Kunde noch nicht verknüpft"
    link = _link_ok(akte["beitreten"]["link"])
    if link:
        beitreten = (f'<a class="knopf gross" href="{_e(link)}" rel="noopener noreferrer">'
                     'Beitreten</a>')
    else:
        beitreten = '<p class="meta">Kein Beitritts-Link im Termin.</p>'
    status = STATUS_TEXT.get(akte["status"], akte["status"])
    grund = f" – {_e(akte['status_grund'])}" if akte["status_grund"] else ""
    abgesagt = '<p class="fehler">Dieser Termin wurde abgesagt.</p>' if akte["abgesagt"] else ""
    return (f'<h1>{_e(titel)}</h1>{abgesagt}<p class="termin-wer">{wer}</p>'
            f'<p class="meta">{_e(_zeit(akte))}</p>{beitreten}'
            f'<p class="termin-status">Mitschrift-Bot: <b>{_e(status)}</b>{grund}</p>'
            + (_schalter(akte) if schreiben else ""))


def _knopf(uid: str, aktion: str, text: str, klasse: str = "", extra: str = "") -> str:
    import ui
    attr = f' class="{klasse}"' if klasse else ""
    return (f'<form method="post" action="{_e(_pfad(uid))}" class="aktion">'
            f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
            f'<input type="hidden" name="aktion" value="{_e(aktion)}">{extra}'
            f'<button type="submit"{attr}>{_e(text)}</button></form>')


def _schalter(akte: dict) -> str:
    uid, teile = akte["uid"], []
    if akte["status"] in ("wartet_auf_einlass", "laeuft"):
        teile.append(_knopf(uid, "ohne_aufnahme", "Ohne Aufnahme", "gefahr"))
        teile.append(_knopf(uid, "will_zusammenfassung",
                            "Will Zusammenfassung: " + ("ja" if akte["will_zusammenfassung"]
                                                         else "nein")))
    if akte["status"] in ("geplant", "kein_link"):
        teile.append(_knopf(uid, "kein_bot", "Kein Bot: " + ("an" if akte["kein_bot"]
                                                             else "aus")))
    if akte["status"] in _SCHALTER_STATUS:
        # Das Formular traegt den Zielzustand (idempotent: doppelt absenden
        # oder ein alter Tab schaltet nicht zurueck).
        an = bool(akte["bildschirm_auswerten"])
        teile.append(_knopf(uid, "bildschirm", "Bildschirm auswerten: " + ("an" if an else "aus"),
                            extra=f'<input type="hidden" name="wert" '
                                  f'value="{"aus" if an else "an"}">'))
    return f'<div class="termin-aktionen">{"".join(teile)}</div>' if teile else ""


def _details(akte: dict) -> str:
    b = akte["beitreten"]
    zeilen = []
    for t in akte["teilnehmer"]:
        name = _e(t["name"] or t["adresse"])
        if t["lead_id"]:
            name = f'<a href="/kontakte/{_e(t["lead_id"])}">{name}</a>'
        rolle = " (Organisator)" if t["rolle"] == "organisator" else ""
        zeilen.append(f"<li>{name}{rolle} <span class=\"meta\">{_e(t['adresse'])}</span></li>")
    teil = f"<ul>{''.join(zeilen)}</ul>" if zeilen else '<p class="meta">Keine Teilnehmer.</p>'
    ein = []
    if b["plattform"]:
        ein.append(f"<p>Plattform: {_e(b['plattform'])}</p>")
    if b["passcode"]:
        ein.append(f"<p>Passcode: <code>{_e(b['passcode'])}</code></p>")
    if b["einwahl"]:
        ein.append(f"<p>Einwahl: {_e(b['einwahl'])}</p>")
    beschr = (f'<div class="text">{_e(akte["beschreibung"])}</div>'
              if akte["beschreibung"] else '<p class="meta">Keine Beschreibung.</p>')
    return (f'<h2>Teilnehmer</h2>{teil}<h2>Beschreibung</h2>{beschr}'
            f'<h2>Einwahl</h2>{"".join(ein) or "<p class=meta>Keine Einwahldaten.</p>"}')


def _briefing(akte: dict) -> str:
    b = akte["briefing"]
    if not b:
        return ('<p class="meta">Das Briefing entsteht etwa 30 Minuten vor dem '
                'Termin.</p>')
    hinweis = "" if b["mit_ki"] else '<p class="meta">Ohne KI-Text erstellt.</p>'
    return hinweis + f'<div class="termin-md">{_md(b["markdown"])}</div>'


def _verlauf(akte: dict, betrachter: str | None) -> str:
    teile = []
    ids = sorted({t["lead_id"] for t in akte["teilnehmer"] if t["lead_id"]})
    mit_mail = post_struktur.mail_verlauf_erlaubt(betrachter)
    namen = {str(k["id"]): k["name"] for k in _kunden(akte)}
    frueher: dict[str, None] = {}
    for lid in ids:
        # DB-Fehler steigen auf (-> 503 ueber _gesichert_seite).
        eintraege = historie.kontakt_historie(lid, mit_mail=mit_mail)[:_VERLAUF_MAX]
        if eintraege:
            punkte = []
            for x in eintraege:
                tag = x["datum"].strftime("%d.%m.%Y")
                kanal = historie._KANAL.get(x["kanal"], x["kanal"])
                punkte.append(f"<li>{_e(tag)} · " + (f"{_e(kanal)} · " if x["kanal"] else "")
                              + f"{_e(x['text'])}</li>")
            zeilen = "<ul>" + "".join(punkte) + "</ul>"
        else:
            zeilen = '<p class="meta">Noch keine Einträge.</p>'
        teile.append(f'<h2><a href="/kontakte/{_e(lid)}">{_e(namen.get(lid, "Kontakt"))}</a></h2>'
                     + zeilen)
        for u in termin_akte.akten_eines_leads(lid):
            if u != akte["uid"]:
                frueher[u] = None
    if frueher:
        zeilen = server._q("select uid, beginn, titel from termin_akten where uid = any(%s) "
                           "and beginn < %s order by beginn desc",
                           (list(frueher), akte["beginn"]))
        from kalender_sicht import _zone
        punkte = []
        for z in zeilen:
            wann = z["beginn"].astimezone(_zone()).strftime("%d.%m.%Y %H:%M")
            punkte.append(f'<li><a href="{_e(_pfad(z["uid"]))}">{_e(wann)} · '
                          f'{_e(z["titel"] or "Termin")}</a></li>')
        teile.append("<h2>Frühere Termine mit diesen Kontakten</h2><ul>" + "".join(punkte)
                     + "</ul>")
    return "".join(teile) or '<p class="meta">Kein verknüpfter Kontakt.</p>'


def _vorschlag_text(v: dict, namen: dict) -> str:
    d = _daten(v)
    wer = _e(namen.get(v["lead_id"], "Kontakt"))
    if v["art"] == "termin_ergebnis":
        erfolg = {True: "ja", False: "nein"}.get(d.get("erfolg"), "–")
        return (f"<b>Termin-Ergebnis</b> ({wer}): stattgefunden "
                f"{'ja' if d.get('stattgefunden') else 'nein'}, Erfolg {erfolg}"
                + (f" – {_e(d.get('was'))}" if d.get("was") else ""))
    if v["art"] == "wiedervorlage":
        return (f"<b>Wiedervorlage</b> ({wer}) am {_e(d.get('faellig_am'))}: "
                f"{_e(d.get('notiz'))}")
    return (f"<b>{_e(FELD_NAMEN.get(d.get('feld'), 'Feld'))} setzen</b> ({wer}): "
            f"{_e(d.get('wert'))}")


def _mitschrift(akte: dict, schreiben: bool) -> str:
    m = akte["mitschrift"]
    uid = akte["uid"]
    namen = {str(k["id"]): k["name"] for k in _kunden(akte)}
    teile = []
    if m["auswertung_md"]:
        teile.append(f'<h2>Auswertung</h2><div class="termin-md">{_md(m["auswertung_md"])}</div>')
    else:
        status = {"offen": "noch nicht fertig", "fehler": "fehlgeschlagen",
                  "leer": "leer"}.get(m["auswertung_status"], m["auswertung_status"])
        teile.append(f'<p class="meta">Auswertung: {_e(status)}.</p>')
    if akte["vorschlaege"]:
        zeilen = []
        for v in akte["vorschlaege"]:
            knoepfe = ""
            if schreiben and v["status"] == "offen":
                extra = f'<input type="hidden" name="vorschlag_id" value="{_e(v["id"])}">'
                knoepfe = (_knopf(uid, "vorschlag_uebernehmen", "Übernehmen", "primaer", extra)
                           + _knopf(uid, "vorschlag_verwerfen", "Verwerfen", "", extra))
            zeilen.append(f'<li class="karte">{_vorschlag_text(v, namen)} '
                          f'<span class="meta">({_e(VORSCHLAG_TEXT.get(v["status"], v["status"]))})</span>'
                          f'<div class="termin-aktionen">{knoepfe}</div></li>')
        teile.append(f'<h2>Vorschläge fürs CRM</h2><ul class="termin-liste">{"".join(zeilen)}</ul>')
    teile.append(_bilder_je_thema(akte))
    segmente = m["segmente"] if isinstance(m["segmente"], list) else []
    if segmente:
        zeilen = "".join(f'<p><b>{_e(s.get("sprecher") or "?")}:</b> {_e(s.get("text"))}</p>'
                         for s in segmente if isinstance(s, dict))
        teile.append(f'<h2>Mitschrift</h2><div class="termin-md">{zeilen}</div>')
    if schreiben:
        teile.append(_knopf(uid, "mitschrift_verwerfen", "Mitschrift verwerfen", "gefahr"))
    return "".join(teile)


def _bildschirm_sichtbar(akte: dict) -> bool:
    return bool(akte["bildschirm_auswerten"] or akte["bilder_anzahl"])


def _zone_der(akte: dict):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(akte.get("zeitzone") or "Europe/Berlin")
    except Exception:
        from kalender_sicht import _zone
        return _zone()


def _bild_json(uid: str, b: dict, zone, score=None) -> dict:
    """Ein Bild fuer JSON und Seite - ohne Bytes und Hash."""
    t = b["aufgenommen_am"].astimezone(zone)
    d = {"id": str(b["id"]), "zeit": b["aufgenommen_am"].isoformat(),
         "uhr": f"{t:%H:%M:%S}", "geteilt_von": b["geteilt_von"],
         "beschreibung": b["beschreibung"] if b["beschreibung_status"] == "fertig" else None,
         "status": b["beschreibung_status"], "breite": b["breite"], "hoehe": b["hoehe"],
         "url": f"{_pfad(uid)}/bild/{b['id']}.jpg"}
    if score is not None:
        d["score"] = score
    return d


def _beschreibung_text(b: dict) -> str:
    if b["beschreibung"]:
        return _e(b["beschreibung"])
    return "keine Beschreibung möglich" if b["status"] == "fehler" else "wird beschrieben …"


def _loeschen_formular(uid: str, bild_id: str) -> str:
    return _knopf(uid, "bild_loeschen", "Löschen", "gefahr",
                  f'<input type="hidden" name="bild_id" value="{_e(bild_id)}">')


def _karte(uid: str, b: dict, schreiben: bool) -> str:
    wer = f" · geteilt von {_e(b['geteilt_von'])}" if b["geteilt_von"] else ""
    loeschen = _loeschen_formular(uid, b["id"]) if schreiben else ""
    return (f'<li class="bild-karte karte" data-id="{_e(b["id"])}">'
            f'<a href="{_e(b["url"])}" target="_blank" rel="noopener">'
            f'<img class="bild-gross" src="{_e(b["url"])}" loading="lazy" '
            f'alt="Bildschirm um {_e(b["uhr"])}"></a>'
            f'<p class="meta bild-zeit">{_e(b["uhr"])}{wer}</p>'
            f'<p class="bild-text">{_beschreibung_text(b)}</p>{loeschen}</li>')


_BILD_STIL = ("<style>.bild-raster{list-style:none;margin:0;padding:0;display:grid;gap:12px;"
              "grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}"
              ".bild-gross{width:100%;height:auto;display:block;border-radius:6px}"
              ".bild-vorschau{width:120px;height:auto;border-radius:4px;margin:2px 6px 2px 0}"
              ".bild-suche{width:100%;max-width:28rem;min-height:44px;margin:8px 0}"
              ".bild-karte p{margin:4px 0}</style>")


def _bildschirm(akte: dict, schreiben: bool) -> str:
    uid = akte["uid"]
    zone = _zone_der(akte)
    bilder = [_bild_json(uid, b, zone) for b in bildschirm.bilder(uid)]
    live = akte["status"] in _BILDSTATUS_LIVE
    if akte["bildschirm_auswerten"]:
        kopf = ('<p class="meta">Laura (Bildschirm) wertet geteilte Bildschirme dieses '
                'Termins aus.</p>')
    else:
        kopf = ('<p class="meta">Bildschirm auswerten ist aus; schon erfasste Bilder '
                'bleiben sichtbar.</p>')
    karten = "".join(_karte(uid, b, schreiben) for b in reversed(bilder))
    leer = "" if bilder else '<p class="meta bild-leer">Noch keine Bilder.</p>'
    vorlage = ""
    if schreiben:
        vorlage = f'<template id="bild-loeschen-vorlage">{_loeschen_formular(uid, "")}</template>'
    return (_BILD_STIL + kopf
            + '<input type="search" class="bild-suche" id="bild-suche" '
              'placeholder="Bilder durchsuchen …" aria-label="Bilder durchsuchen" '
              'autocomplete="off">'
            + '<p class="meta" id="bild-meldung" role="status"></p>'
            + f'<div id="bilder" data-json="{_e(_pfad(uid))}/bilder.json" '
              f'data-live="{1 if live else 0}">{leer}'
              f'<ul class="bild-raster" id="bild-raster">{karten}</ul></div>'
            + vorlage
            + '<script src="/static/termin_bilder/bilder.js" defer></script>')


def _bilder_je_thema(akte: dict) -> str:
    """Je Verlaufseintrag der Auswertung (auswertung_json["verlauf"]) die Bilder,
    die in dessen Segmentbereich von..bis entstanden. Eintraege ohne gueltigen
    Bereich oder ohne Bilder fehlen."""
    m = akte["mitschrift"]
    aj = m.get("auswertung_json")
    if isinstance(aj, str):
        try:
            aj = json.loads(aj)
        except ValueError:
            aj = None
    verlauf = aj.get("verlauf") if isinstance(aj, dict) else None
    segmente = m["segmente"] if isinstance(m["segmente"], list) else []
    if not akte["bilder_anzahl"] or not isinstance(verlauf, list) or not segmente:
        return ""
    bilder = bildschirm.bilder(akte["uid"])
    basis = _e(_pfad(akte["uid"]))
    teile = []
    for e in verlauf:
        if not isinstance(e, dict):
            continue
        von, bis = e.get("von"), e.get("bis")
        if (not isinstance(von, int) or not isinstance(bis, int) or isinstance(von, bool)
                or isinstance(bis, bool) or von < 0 or bis < von or bis >= len(segmente)):
            continue
        ids = bildschirm.bilder_zu_abschnitt(segmente, von, bis, bilder)
        if not ids:
            continue
        vorschau = "".join(f'<a href="{basis}/bild/{_e(b)}.jpg" target="_blank" rel="noopener">'
                   f'<img class="bild-vorschau" loading="lazy" alt="Bildschirm" '
                   f'src="{basis}/bild/{_e(b)}.jpg"></a>' for b in ids)
        teile.append(f'<h3>{_e(e.get("thema") or "Thema")}</h3><p>{vorschau}</p>')
    if not teile:
        return ""
    return _BILD_STIL + '<h2>Bilder je Thema</h2>' + "".join(teile)


def _reiter_leiste(akte: dict, aktiv: str) -> str:
    import ui_muster
    eintraege = [("details", "Details", None), ("briefing", "Briefing", None),
                 ("verlauf", "Verlauf", None)]
    if akte["mitschrift"]:
        eintraege.append(("mitschrift", "Mitschrift", None))
    if _bildschirm_sichtbar(akte):
        eintraege.append(("bildschirm", "Bildschirm", akte["bilder_anzahl"] or None))
    return ui_muster.reiter(eintraege, aktiv,
                            lambda k: f"{_pfad(akte['uid'])}?reiter={k}")


def _hinweis(request) -> str:
    h = MELDUNGEN.get(str(request.query_params.get("m") or ""))
    return f'<div class="hinweis">{_e(h)}</div>' if h else ""


# ------------------------------------------------------------- Aktionen ----

def _uuid(w):
    try:
        return str(uuid.UUID(str(w)))
    except (ValueError, TypeError, AttributeError):
        return None


def _vorschlag_anwenden(akte_zeile: dict, v: dict) -> str:
    """Wirkung eines offenen Vorschlags. '' = gebucht, sonst die Meldung."""
    uid, d = akte_zeile["uid"], _daten(v)
    lid = str(v["lead_id"]) if v["lead_id"] else None
    if not lid:
        return "ohne_kontakt"
    if termin_akte.lead_gesperrt(lid):
        return "gesperrt"
    if v["art"] == "termin_ergebnis":
        tid = akte_zeile["termin_activity_id"]
        if tid is None and akte_zeile["herkunft"] == "kalender":
            from kalender_sicht import _zone
            b = akte_zeile["beginn"].astimezone(_zone())
            dauer = max(1, int((akte_zeile["ende"] - akte_zeile["beginn"]).total_seconds() // 60))
            tid = str(server._q(
                "insert into activities (lead_id, type, payload) values (%s, 'termin', %s) "
                "returning id",
                (lid, server._json({
                    "datum": b.date().isoformat(), "uhrzeit": f"{b:%H:%M}",
                    "dauer_minuten": dauer, "thema": akte_zeile["thema"] or "",
                    "ort": akte_zeile["link"] or "", "uid": uid,
                    "aus_kalender": True})))[0]["id"])
            server._q("update termin_akten set termin_activity_id = %s where uid = %s "
                      "returning uid", (tid, uid))
        if tid is None:
            return "keine_terminzeile"
        erg = server._termin_ergebnis(
            str(tid), bool(d.get("stattgefunden")), d.get("erfolg"),
            str(d.get("was") or ""), quelle="termin-seite")
        if "fehler" not in erg:
            return ""
        return "schon_gebucht" if "schon gebucht" in erg["fehler"] else "nicht_gebucht"
    if v["art"] == "wiedervorlage":
        try:
            faellig = date.fromisoformat(str(d.get("faellig_am")))
        except ValueError:
            return "datum_ungueltig"
        server._wiedervorlage_anlegen(lid, faellig, str(d.get("notiz") or "")[:_TEXT_MAX])
        return ""
    feld, wert = d.get("feld"), " ".join(str(d.get("wert") or "").split())[:200]
    if feld not in FELD_NAMEN or not wert:
        return "feld_ungueltig"
    # Nur die zwei Spalten der Whitelist; der Name kommt nie aus den Daten.
    sql = ("update leads set title = %s, updated_at = now() where id = %s returning id"
           if feld == "title" else
           "update leads set company = %s, updated_at = now() where id = %s returning id")
    server._q(sql, (wert, lid))
    return ""


def _zurueck(vid) -> None:
    """Der Vorschlag wurde nicht angewendet: wieder offen."""
    server._q("update termin_vorschlaege set status = 'offen', erledigt_am = null "
              "where id = %s returning id", (vid,))


def _aktion(uid: str, form) -> str:
    """Fuehrt die Aktion aus -> Meldung ('' = alles gut)."""
    aktion = str(form.get("aktion") or "")
    if aktion == "ohne_aufnahme":
        termin_akte.aufnahme_beenden(uid, "Kunde hat abgelehnt")
        return "aufnahme_beendet"
    elif aktion == "will_zusammenfassung":
        server._q("update termin_akten set will_zusammenfassung = not will_zusammenfassung, "
                  "geaendert_am = now() where uid = %s returning uid", (uid,))
    elif aktion == "kein_bot":
        if not server._q("update termin_akten set kein_bot = not kein_bot, "
                         "geaendert_am = now() where uid = %s "
                         "and status in ('geplant', 'kein_link') returning uid", (uid,)):
            return "kein_bot_gesperrt"
    elif aktion in ("vorschlag_uebernehmen", "vorschlag_verwerfen"):
        uebernehmen = aktion == "vorschlag_uebernehmen"
        vid = _uuid(form.get("vorschlag_id"))
        # Zuerst beanspruchen: ein zweiter Absender findet nichts mehr.
        z = server._q(
            "update termin_vorschlaege v set status = %s, erledigt_am = now() "
            "from termin_mitschriften m where m.id = v.mitschrift_id and v.id = %s "
            "and m.uid = %s and v.status = 'offen' "
            "returning v.id, v.art, v.lead_id, v.daten",
            ("bestaetigt" if uebernehmen else "verworfen", vid, uid)) if vid else []
        if not z:
            return "kein_vorschlag"
        if uebernehmen:
            try:
                fehler = _vorschlag_anwenden(
                    server._q("select * from termin_akten where uid = %s", (uid,))[0], z[0])
            except Exception:
                _zurueck(vid)
                raise
            if fehler:
                _zurueck(vid)
                return fehler
    elif aktion == "bildschirm":
        ziel = {"an": True, "aus": False}.get(str(form.get("wert") or ""))
        if ziel is None:
            return "bildschirm_wert"
        z = server._q("select plattform from termin_akten where uid = %s", (uid,))
        if not z or z[0]["plattform"] != "jitsi":
            return "bildschirm_nur_jitsi"
        if not server._q(
                "update termin_akten set bildschirm_auswerten = %s, "
                "geaendert_am = now() where uid = %s and plattform = 'jitsi' "
                "and status in ('geplant', 'kein_link', 'wartet_auf_einlass', 'laeuft') "
                "returning uid", (ziel, uid)):
            return "bildschirm_gesperrt"
    elif aktion == "bild_loeschen":
        bid = _uuid(form.get("bild_id"))
        if not bid or not bildschirm.bild_loeschen(uid, bid):
            return "bild_unbekannt"
    elif aktion == "mitschrift_verwerfen":
        if not server._q("select 1 from termin_mitschriften where uid = %s", (uid,)):
            return "keine_mitschrift"
        termin_akte.aufnahme_beenden(uid, "nachträglich verworfen")
    else:
        return "unbekannte_aktion"
    return ""


# --------------------------------------------------------------- Routen ----

def routen(ui) -> list:

    async def json_ansicht(request):
        uid = request.path_params["kennung"][:-len(".json")]
        akte = termin_akte.lesen(uid)
        if akte is None:
            return _grund(404, "Keine Akte zu dieser uid.")
        return _ok(_json_sicher(akte))

    json_ansicht = _gesichert_json(json_ansicht)

    @ui._gesichert_seite
    async def seite(request):
        uid = request.path_params["kennung"]
        akte = termin_akte.lesen(uid)
        if akte is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Zu diesem Termin gibt es keine Akte.")
        schreiben = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
        aktiv = str(request.query_params.get("reiter") or "")
        if (aktiv not in _REITER or (aktiv == "mitschrift" and not akte["mitschrift"])
                or (aktiv == "bildschirm" and not _bildschirm_sichtbar(akte))):
            aktiv = "mitschrift" if akte["mitschrift"] else "details"
        inhalt = {"details": lambda: _details(akte), "briefing": lambda: _briefing(akte),
                  "verlauf": lambda: _verlauf(akte, ui._AKTIVER_BENUTZER.get() or None),
                  "mitschrift": lambda: _mitschrift(akte, schreiben),
                  "bildschirm": lambda: _bildschirm(akte, schreiben)}[aktiv]()
        rumpf = (_hinweis(request) + _kopf(akte, _kunden(akte), schreiben)
                 + _reiter_leiste(akte, aktiv) + f'<div class="termin-inhalt">{inhalt}</div>')
        antwort = ui._seite(akte["titel"] or "Kundentermin", rumpf, titel_zeigen=False)
        antwort.headers["Cache-Control"] = "no-store"
        if aktiv == "bildschirm":
            # Eigenes Skript und Abrufe an dieselbe Herkunft, sonst nichts.
            antwort.headers["Content-Security-Policy"] = (
                ui._CSP + "; script-src 'self'; connect-src 'self'")
        return antwort

    def _gibt(uid: str) -> bool:
        return bool(server._q("select 1 from termin_akten where uid = %s", (uid,)))

    async def lesen(request):
        k = str(request.path_params["kennung"])
        json_weg = k.endswith(".json")
        if json_weg:
            # Eine uid darf selbst auf ".json" enden: gibt es sie ohne den
            # Zusatz nicht, wohl aber mit, ist es ihre HTML-Seite.
            try:
                json_weg = _gibt(k[:-len(".json")]) or not _gibt(k)
            except psycopg.Error:
                pass
        if json_weg:
            return await json_ansicht(request)
        return await seite(request)

    @ui._gesichert_seite
    async def aktion(request):
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Keine Aktion ausgeführt. Die Seite neu laden und erneut "
                                   "versuchen.")
        if ui._AKTIVE_ROLLE.get() in ("lesen", "kalender"):
            return ui._fehlerseite(403, "Nur Lesen", "Diese Anmeldung darf nichts ändern.")
        uid = request.path_params["kennung"]
        if not server._q("select 1 from termin_akten where uid = %s", (uid,)):
            return ui._fehlerseite(404, "Nicht gefunden", "Zu diesem Termin gibt es keine Akte.")
        meldung = _aktion(uid, form)
        parameter = []
        if str(form.get("aktion") or "") in ("bildschirm", "bild_loeschen"):
            parameter.append("reiter=bildschirm")
        if meldung:
            parameter.append(f"m={meldung}")
        ziel = _pfad(uid) + ("?" + "&".join(parameter) if parameter else "")
        return RedirectResponse(ziel, status_code=303)

    @_gesichert_json
    async def bilder_json(request):
        uid = request.path_params["kennung"]
        akte_z = server._q("select status, zeitzone from termin_akten where uid = %s", (uid,))
        if not akte_z:
            return _grund(404, "Keine Akte zu dieser uid.")
        zone = _zone_der(akte_z[0])
        live = akte_z[0]["status"] in _BILDSTATUS_LIVE
        q = " ".join(str(request.query_params.get("q") or "").split())[:200]
        alle = {str(b["id"]): b for b in bildschirm.bilder(uid)}
        if not q:
            return _ok({"bilder": [_bild_json(uid, b, zone) for b in alle.values()],
                        "live": live})
        try:
            treffer = await run_in_threadpool(bildschirm.suchen, q, uid, 20)
        except bildschirm.SucheFehler as e:
            return _ok({"bilder": [], "live": live, "fehler": str(e)})
        aus = []
        for t in treffer:
            b = alle.get(str(t.get("id")))
            if b is not None and t.get("uid", uid) == uid:   # nur dieser Termin, nur Vorhandenes
                aus.append(_bild_json(uid, b, zone, t.get("score")))
        return _ok({"bilder": aus, "live": live})

    @ui._gesichert_seite
    async def bild_jpg(request):
        uid, bild_id = request.path_params["kennung"], _uuid(request.path_params["bild_id"])
        daten = bildschirm.bild_daten(uid, bild_id) if bild_id else None
        if daten is None:
            return ui._fehlerseite(404, "Nicht gefunden", "Dieses Bild gibt es nicht.")
        return Response(daten, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})

    async def statik(request):
        datei = request.path_params["datei"]
        typ = STATIK_DATEIEN.get(datei)
        pfad = STATIK / datei
        if not typ or not pfad.is_file():
            return Response("Nicht gefunden", status_code=404, media_type="text/plain")
        return FileResponse(pfad, media_type=typ, headers={"Cache-Control": "no-cache"})

    return [Route("/static/termin_bilder/{datei}", statik, methods=["GET"]),
            Route("/termine/{kennung:path}/bilder.json", bilder_json, methods=["GET"]),
            Route("/termine/{kennung:path}/bild/{bild_id}.jpg", bild_jpg, methods=["GET"]),
            Route("/termine/{kennung:path}", lesen, methods=["GET"]),
            Route("/termine/{kennung:path}", aktion, methods=["POST"])]
