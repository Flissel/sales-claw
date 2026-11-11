"""Briefing vor einem Kundentermin (Meeting-Mittelpunkt).

Zwei Teile: ein deterministischer Faktenteil aus dem CRM und, wenn der lokale
Ollama erreichbar ist, ein KI-Kurztext (3-5 Saetze). Ohne Ollama oder bei einem
Ollama-Fehler gibt es nur die Fakten - `erstellen` wirft nie wegen Ollama.

KUNDENTEXT: Nichts davon wird geloggt (nur Zaehler und uids). Kundentext geht
ausschliesslich ueber `ollama` an OLLAMA_URL; dieses Modul importiert weder
`gateway` noch einen anderen KI-Client.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import ollama
import server
import teilnehmer
import termin_akte
from historie import kontakt_historie

LOG = logging.getLogger("briefing")

MAX_KONTAKTE = 5
MAX_PAINPOINTS = 8
MAX_BESCHREIBUNG = 400
MAX_KI_ZEICHEN = 1200
NEUTRAL = "Kundentermin"
LEER = "—"

SYSTEM_PROMPT = ("Du bereitest Felix auf ein Kundengespräch vor. Antworte auf Deutsch "
                 "in 3–5 Sätzen, nur aus den gegebenen Fakten, nichts erfinden.")


def _tag(wert) -> str:
    if isinstance(wert, datetime):
        return wert.date().isoformat()
    if isinstance(wert, date):
        return wert.isoformat()
    return str(wert or "")[:10]


def _kurz(text, grenze: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= grenze else t[:grenze - 1].rstrip() + "…"


_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_MAIL = re.compile(r"\S+@\S+")
_NUMMER = re.compile(r"\+?\(?\d[\d\s().\-/]*\d")
_GEHEIMZEILE = re.compile(
    r"passcode|kenncode|kennwort|meeting[\s-]?id|besprechungs[\s-]?id|dial[\s-]?in|"
    r"einwahl|telefon", re.I)
_LANGE_ZIFFERN = re.compile(r"\d[\d\s-]{6,}\d")


def _ziffern_weg(m) -> str:
    return " " if sum(c.isdigit() for c in m.group(0)) >= 7 else m.group(0)


def _scrub(text, neutral: str = NEUTRAL) -> str:
    """Fuer den Telegram-Hinweis: ohne URLs, E-Mail-Adressen und Telefon-/Zifferfolgen
    (7+ Ziffern); leer -> neutrale Bezeichnung."""
    t = _URL.sub(" ", str(text or ""))
    t = _MAIL.sub(" ", t)
    t = _NUMMER.sub(_ziffern_weg, t)
    t = " ".join(t.split())
    return t or neutral


def _beschreibung(text, grenze: int) -> str:
    """Zugangsdaten raus, bevor gekuerzt wird: Zeilen mit URL oder Passcode-/
    Einwahl-Stichwort entfallen, lange Zifferfolgen ebenfalls."""
    zeilen = []
    for z in str(text or "").splitlines():
        if _URL.search(z) or _GEHEIMZEILE.search(z):
            continue
        zeilen.append(_LANGE_ZIFFERN.sub(" ", z))
    return _kurz(" ".join(zeilen), grenze)


def gesperrt(lead: dict) -> bool:
    """Live pruefen (nicht nur den gespeicherten Grund): Sperrliste ueber E-Mail
    und Telefon, Loeschantrag und Privat-Vermerk am Lead."""
    if server._sperre(lead.get("email") or "", lead.get("phone") or ""):
        return True
    if lead.get("email") and teilnehmer.sperrgrund(lead["email"]):
        return True
    enr = lead.get("enrichment")
    return bool(server._loeschantrag(enr) or server._privat(enr))


_gesperrt = gesperrt   # alter Name


def _painpoint_texte(auswertung) -> list[str]:
    """Form (Task 10): auswertung_json hat auf oberster Ebene den Schluessel
    "painpoints" mit einer Liste von {"zitat", "zeit", "sprecher"}; tolerant
    auch Strings oder Dicts mit "text". Alles andere wird still uebergangen."""
    if not isinstance(auswertung, dict):
        return []
    roh = auswertung.get("painpoints")
    if not isinstance(roh, list):
        return []
    aus = []
    for p in roh:
        t = (p.get("zitat") or p.get("text")) if isinstance(p, dict) else p
        if isinstance(t, str) and t.strip():
            aus.append(" ".join(t.split()))
    return aus


def _painpoints(lead_id: str, uid: str) -> list[dict]:
    aus = []
    for andere in termin_akte.akten_eines_leads(lead_id):
        if andere == uid:
            continue
        for z in server._q(
                "select m.auswertung_json, coalesce(m.auswertung_am, a.beginn) as am "
                "from termin_mitschriften m join termin_akten a on a.uid = m.uid "
                "where m.uid = %s and m.auswertung_status = 'fertig'", (andere,)):
            for t in _painpoint_texte(z["auswertung_json"]):
                aus.append({"datum": _tag(z["am"]), "text": t})
    aus.sort(key=lambda p: (p["datum"], p["text"]), reverse=True)
    return aus[:MAX_PAINPOINTS]


def _wiedervorlagen(lead_id: str) -> list[dict]:
    aus = []
    for w in server._offene_wiedervorlagen(lead_id):
        p = w.get("payload") if isinstance(w.get("payload"), dict) else {}
        aus.append({"faellig_am": str(p.get("faellig_am") or ""),
                    "notiz": _kurz(p.get("notiz"), 200)})
    aus.sort(key=lambda w: (w["faellig_am"], w["notiz"]))
    return aus


def _lead_fakten(lead: dict, uid: str) -> dict:
    lid = str(lead["id"])
    # kontakt_historie sortiert nur nach datum; Gleichstaende voll ordnen,
    # damit Schnitt und stand stabil bleiben
    roh = sorted(kontakt_historie(lid, tage=365),
                 key=lambda e: (str(e["datum"]), e["art"] or "", e["kanal"] or "",
                                str(e["text"] or "")), reverse=True)
    kontakte = [{"datum": _tag(e["datum"]), "art": e["art"], "kanal": e["kanal"],
                 "text": _kurz(e["text"], 120)} for e in roh[:MAX_KONTAKTE]]
    return {"name": lead.get("name") or "", "rolle": lead.get("title") or "",
            "firma": lead.get("company") or "", "quelle": lead.get("source") or "",
            "erster_kontakt": _tag(lead.get("created_at")),
            "letzte_kontakte": kontakte,
            "offene_wiedervorlagen": _wiedervorlagen(lid),
            "painpoints": _painpoints(lid, uid)}


def fakten(uid: str) -> dict:
    akte = termin_akte.lesen(uid)
    if akte is None:
        raise ValueError("Termin-Akte unbekannt")
    leads, gesehen = [], set()
    for t in akte["teilnehmer"]:
        lid = t.get("lead_id")
        if not lid or lid in gesehen:
            continue
        gesehen.add(lid)
        z = server._q("select id, name, email, phone, company, title, source, "
                      "created_at, enrichment from leads where id = %s::uuid", (lid,))
        if z and not gesperrt(z[0]):
            leads.append(_lead_fakten(z[0], uid))
    LOG.debug("Briefing-Fakten: uid=%s leads=%d",
              hashlib.sha256(uid.encode()).hexdigest()[:8], len(leads))
    return {"beginn": akte["beginn"].isoformat(),
            "ziel": {"thema": akte.get("thema") or akte.get("titel") or "",
                     "beschreibung": _beschreibung(akte.get("beschreibung"), MAX_BESCHREIBUNG)},
            "leads": leads}


def _dd(tag: str) -> str:
    return f"{tag[8:10]}.{tag[5:7]}.{tag[:4]}" if len(tag) >= 10 else (tag or "?")


def fakten_markdown(f: dict) -> str:
    leads = f.get("leads") or []
    viele = len(leads) > 1
    wer, kontakte, offen, pain = [], [], [], []
    for lead in leads:
        marke = f" [{lead['name']}]" if viele else ""
        zeile = lead["name"] or "?"
        if lead["rolle"]:
            zeile += f", {lead['rolle']}"
        if lead["firma"]:
            zeile += f" ({lead['firma']})"
        extra = []
        if lead["quelle"]:
            extra.append(f"Quelle: {lead['quelle']}")
        if lead["erster_kontakt"]:
            extra.append(f"erster Kontakt: {_dd(lead['erster_kontakt'])}")
        wer.append("- " + zeile + (" — " + ", ".join(extra) if extra else ""))
        for k in lead["letzte_kontakte"]:
            kontakte.append(f"- {_dd(k['datum'])} {k['art']}"
                            + (f" ({k['kanal']})" if k["kanal"] else "")
                            + (f": {k['text']}" if k["text"] else "") + marke)
        for w in lead["offene_wiedervorlagen"]:
            offen.append(f"- fällig {_dd(w['faellig_am'])}: {w['notiz'] or LEER}" + marke)
        for p in lead["painpoints"]:
            pain.append(f"- „{p['text']}“ ({_dd(p['datum'])})" + marke)
    ziel = f.get("ziel") or {}
    z = " — ".join(x for x in (ziel.get("thema"), ziel.get("beschreibung")) if x)

    def abschnitt(titel, zeilen):
        return f"## {titel}\n" + ("\n".join(zeilen) if zeilen else LEER)

    return "\n\n".join([
        abschnitt("Wer", wer), abschnitt("Letzte Kontakte", kontakte),
        abschnitt("Offen", offen),
        abschnitt("Painpoints aus früheren Gesprächen", pain),
        abschnitt("Ziel", [z] if z else [])]) + "\n"


def _ki_text(roh) -> str:
    """Begrenzen und fuehrende '#' je Zeile weg: der KI-Text soll keine
    Faktenueberschriften nachahmen."""
    zeilen = [z.lstrip().lstrip("#").strip() for z in str(roh or "").strip().splitlines()]
    return "\n".join(zeilen).strip()[:MAX_KI_ZEICHEN].strip()


def stand_von(f: dict) -> str:
    """Fingerabdruck der Fakten (ohne KI-Text). Der Taktgeber vergleicht ihn
    mit dem gespeicherten, ohne dafuer Ollama zu befragen."""
    return hashlib.sha256(json.dumps(f, sort_keys=True, default=str).encode()).hexdigest()


def erstellen(uid: str) -> dict:
    f = fakten(uid)
    md = fakten_markdown(f)
    # stand nur ueber die Fakten: aendert sich mit neuer Mail, nicht mit KI-Text
    stand = stand_von(f)
    kurz = ""
    try:
        if ollama.erreichbar():
            kurz = _ki_text(ollama.chat(SYSTEM_PROMPT, md))
    except ollama.OllamaFehler:
        LOG.warning("Briefing ohne KI-Text: Ollama-Fehler (uid=%s)", uid)
    except Exception:  # noqa: BLE001 - Vertrag: Ollama bricht das Briefing nie
        LOG.warning("Briefing ohne KI-Text: unerwarteter Fehler (uid=%s)", uid)
    if kurz:
        return {"markdown": f"## Kurz\n{kurz}\n\n{md}", "mit_ki": True, "stand": stand}
    return {"markdown": f"_ohne KI-Text_\n\n{md}", "mit_ki": False, "stand": stand}


def hinweis_text(akte: dict, ui_basis: str) -> str:
    """Genau vier Zeilen (drei ohne Link); keine Adresse, kein Telefon, keine
    URL ausser dem Beitrittslink, kein Passcode. Uhrzeit in der Zeitzone der
    Akte. Kunde und Thema laufen durch `_scrub`."""
    try:
        zone = ZoneInfo(akte.get("zeitzone") or "Europe/Berlin")
    except Exception:  # noqa: BLE001 - unbekannte Zone: Vorgabe
        zone = ZoneInfo("Europe/Berlin")
    uhr = akte["beginn"].astimezone(zone).strftime("%H:%M")
    kunde = _scrub(akte.get("titel"))
    for t in akte.get("teilnehmer") or []:
        if not t.get("lead_id"):
            continue
        z = server._q("select name, company, email, phone, enrichment from leads "
                      "where id = %s::uuid", (str(t["lead_id"]),))
        if z and gesperrt(z[0]):
            kunde = NEUTRAL  # gesperrter erster Lead: nichts von ihm, auch nicht der Titel
        elif z:
            name = _scrub(z[0]["name"], "")
            if name:
                kunde = name
                firma = _scrub(z[0]["company"], "")
                if firma:
                    kunde += f" ({firma})"
        break
    thema = _scrub(akte.get("thema") or akte.get("titel"))
    zeilen = [f"🗓 {uhr} {kunde}", thema,
              f"Briefing öffnen: {ui_basis}/termine/{quote(akte['uid'], safe='')}"]
    link = (akte.get("beitreten") or {}).get("link")
    if link:
        zeilen.append(f"Beitreten: {link}")
    return "\n".join(zeilen)
