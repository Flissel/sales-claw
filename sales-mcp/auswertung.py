"""Auswertung einer Vexa-Mitschrift durch das lokale Ollama (Meeting-Mittelpunkt).

Aus den Segmenten (`vexa.segmente_holen`) entsteht ein JSON-Dict mit festen
Abschnitten, daraus Markdown, CRM-Vorschlaege und eine Kundenfassung.

KUNDENTEXT: Die Mitschrift geht nur an `ollama.chat` (= `OLLAMA_URL`). Dieses
Modul importiert weder `gateway` noch einen anderen KI- oder HTTP-Client.
Mitschrift-Text, Zitate und Namen stehen in keinem Log und in keiner
Fehlermeldung, nur Zaehler.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import ollama

LOG = logging.getLogger("auswertung")

AUSWERTUNG_STUECK_ZEICHEN = 12000
WIEDERVORLAGE_TAGE = 3

ABSCHNITTE: tuple[tuple[str, str], ...] = (
    ("kurzfassung", "Kurzfassung"),
    ("painpoints", "Painpoints"),
    ("ziele", "Ziele und Wünsche"),
    ("fakten", "Zahlen und Fakten"),
    ("einwaende", "Einwände und Bedenken"),
    ("zusagen_felix", "Zusagen von Felix"),
    ("zusagen_kunde", "Zusagen des Kunden"),
    ("naechste_schritte", "Nächste Schritte"),
    ("beteiligte", "Entscheider und Beteiligte"),
    ("offene_fragen", "Offene Fragen"),
    ("stimmung", "Stimmung"),
)
_TEXTE = ("kurzfassung", "stimmung")
_MIT_DATUM = ("zusagen_felix", "naechste_schritte")
_ZEITZONE = ZoneInfo("Europe/Berlin")
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = """Du wertest die Mitschrift eines Verkaufsgespraechs aus.
Die Mitschrift besteht aus nummerierten Segmenten im Format "[Nummer] Sprecher: Text".
Antworte NUR als JSON nach diesem Schema, ohne Erklaerung, auf Deutsch:
{
  "kurzfassung": "2 bis 4 Saetze",
  "painpoints": [{"zitat": "woertlich aus dem Segment", "segment": 0}],
  "ziele": ["Ziele und Wuensche des Kunden"],
  "fakten": ["Zahlen und Fakten: Mitarbeiter, Tools, Budget, Fristen"],
  "einwaende": ["Einwaende und Bedenken"],
  "zusagen_felix": [{"text": "Was Felix zusagt", "datum": "YYYY-MM-DD oder null"}],
  "zusagen_kunde": ["Was der Kunde zusagt"],
  "naechste_schritte": [{"text": "Naechster Schritt", "datum": "YYYY-MM-DD oder null"}],
  "beteiligte": ["Entscheider und Beteiligte mit Rolle"],
  "offene_fragen": ["Offene Fragen"],
  "stimmung": "ein kurzer Satz",
  "ergebnis": {"stattgefunden": true, "erfolg": null, "was": "kurz, was herauskam"},
  "felder": {"title": "neue Position des Kunden", "company": "neue Firma des Kunden"}
}
Painpoints = Probleme, Ärger, Kosten, Zeitverlust des Kunden, wörtlich zitiert.
"segment" ist die Nummer des Segments, aus dem das Zitat stammt. Nenne keine Uhrzeiten.
Nimm nur auf, was im Text steht. Leere Abschnitte sind leere Listen oder leere Texte.
Datum nur, wenn ein konkretes Datum genannt wurde, sonst null.
"felder" nur fuellen, wenn der Kunde ausdruecklich eine neue Position (title) oder
eine neue Firma (company) nennt; sonst {} bzw. den Schluessel weglassen."""

SYSTEM_ZUSAMMENFUEHREN = """Du bekommst Kurzfassungen von Teilen eines Verkaufsgespraechs.
Fasse sie zu einer einzigen Kurzfassung in 2 bis 4 Saetzen zusammen.
Antworte NUR als JSON auf Deutsch: {"kurzfassung": "..."}"""


# ---------- Normalisierung ----------

def _leer() -> dict:
    a: dict = {}
    for schluessel, _ in ABSCHNITTE:
        a[schluessel] = "" if schluessel in _TEXTE else []
    a["ergebnis"] = {"stattgefunden": True, "erfolg": None, "was": ""}
    a["felder"] = {}
    return a


FELD_MAX_ZEICHEN = 200


def _felder(wert) -> dict:
    """Feldvorschlaege (I10): nur title/company, nur Strings, getrimmt, gekappt."""
    if not isinstance(wert, dict):
        return {}
    aus = {}
    for name in ("title", "company"):
        x = wert.get(name)
        if isinstance(x, str):
            text = " ".join(x.split())[:FELD_MAX_ZEICHEN].strip()
            if text:
                aus[name] = text
    return aus


def _norm(text: str) -> str:
    """Schluessel fuer Duplikate: casefold, ohne Satzzeichen, Leerraum gekappt."""
    return " ".join(re.sub(r"[\W_]+", " ", str(text).casefold()).split())


def _str(wert) -> str:
    if isinstance(wert, str):
        return " ".join(wert.split())
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return str(wert)
    return ""


def _datum(wert) -> str | None:
    if not isinstance(wert, str) or not _DATUM.match(wert.strip()):
        return None
    try:
        date.fromisoformat(wert.strip())
    except ValueError:
        return None
    return wert.strip()


def _strings(wert) -> list[str]:
    if isinstance(wert, str):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    return [t for t in (_str(x) for x in wert) if t]


def _paare(wert) -> list[dict]:
    if isinstance(wert, (str, dict)):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    aus = []
    for x in wert:
        if isinstance(x, dict):
            text, datum = _str(x.get("text")), _datum(x.get("datum"))
        else:
            text, datum = _str(x), None
        if text:
            aus.append({"text": text, "datum": datum})
    return aus


def _beginne(segmente: list[dict]) -> list[datetime | None]:
    aus = []
    for s in segmente:
        try:
            roh = str(s.get("beginn") or "").strip().replace("Z", "+00:00")
            zeit = datetime.fromisoformat(roh) if roh else None
        except ValueError:
            zeit = None
        aus.append(zeit)
    return aus


def _painpoints(wert, segmente: list[dict], beginne: list[datetime | None]) -> list[dict]:
    """Zeit und Sprecher kommen vom Code aus dem verwiesenen Segment."""
    if isinstance(wert, dict):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    start = next((b for b in beginne if b is not None), None)
    aus = []
    for x in wert:
        if not isinstance(x, dict):
            continue
        zitat, index = _str(x.get("zitat")), x.get("segment")
        if not zitat or isinstance(index, bool) or not isinstance(index, int):
            continue
        if not 0 <= index < len(segmente):
            continue
        zeit, b = "", beginne[index]
        if start is not None and b is not None:
            try:
                sek = max(0, int((b - start).total_seconds()))
                zeit = f"{sek // 60:02d}:{sek % 60:02d}"
            except TypeError:  # naive gegen aware gemischt
                zeit = ""
        aus.append({"zitat": zitat, "zeit": zeit,
                    "sprecher": _str(segmente[index].get("sprecher"))})
    return aus


def _ergebnis(wert) -> dict:
    standard = {"stattgefunden": True, "erfolg": None, "was": ""}
    if not isinstance(wert, dict):
        return standard
    if isinstance(wert.get("stattgefunden"), bool):
        standard["stattgefunden"] = wert["stattgefunden"]
    if isinstance(wert.get("erfolg"), bool):
        standard["erfolg"] = wert["erfolg"]
    standard["was"] = _str(wert.get("was"))
    return standard


def _normalisieren(roh: dict, segmente: list[dict], beginne: list[datetime | None]) -> dict:
    a = _leer()
    for schluessel, _ in ABSCHNITTE:
        wert = roh.get(schluessel)
        if schluessel in _TEXTE:
            a[schluessel] = _str(wert)
        elif schluessel == "painpoints":
            a[schluessel] = _painpoints(wert, segmente, beginne)
        elif schluessel in _MIT_DATUM:
            a[schluessel] = _paare(wert)
        else:
            a[schluessel] = _strings(wert)
    a["ergebnis"] = _ergebnis(roh.get("ergebnis"))
    a["felder"] = _felder(roh.get("felder"))
    return a


# ---------- Modellaufruf ----------

def _json_aufruf(system: str, nutzer: str) -> dict:
    """Ein Versuch plus eine Wiederholung bei ungueltigem JSON, dann OllamaFehler."""
    for versuch in (1, 2):
        text = ollama.chat(system, nutzer, als_json=True).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            roh = json.loads(text)
        except ValueError:
            roh = None
        if isinstance(roh, dict):
            return roh
        LOG.warning("Auswertung: Antwort kein gueltiges JSON (Versuch %d)", versuch)
    raise ollama.OllamaFehler("Auswertung: Modellantwort ist kein gueltiges JSON")


# ---------- Stueckelung und Zusammenfuehren ----------

def _zeilen(segmente: list[dict]) -> list[str]:
    """Nummerierte Zeilen; die Nummer ist der globale Index ueber alle Stuecke."""
    zeilen = []
    for i, s in enumerate(segmente):
        text = " ".join(str(s.get("text") or "").split())
        if not text:
            continue
        zeile = f"[{i}] {str(s.get('sprecher') or '').strip() or '?'}: {text}"
        # Ein einzelnes Segment wird nie geteilt, aber hart gekappt, damit
        # kein Stueck die Grenze sprengt.
        zeilen.append(zeile[:AUSWERTUNG_STUECK_ZEICHEN - 1])
    return zeilen


def _stuecke(zeilen: list[str]) -> list[str]:
    stuecke, aktuell, laenge = [], [], 0
    for z in zeilen:
        if aktuell and laenge + len(z) + 1 > AUSWERTUNG_STUECK_ZEICHEN:
            stuecke.append("\n".join(aktuell))
            aktuell, laenge = [], 0
        aktuell.append(z)
        laenge += len(z) + 1
    if aktuell:
        stuecke.append("\n".join(aktuell))
    return stuecke


def _vereinen(teile: list[dict]) -> dict:
    a = _leer()
    for schluessel, _ in ABSCHNITTE:
        if schluessel in _TEXTE:
            continue
        gesehen: dict[str, dict | str] = {}
        for t in teile:
            for eintrag in t[schluessel]:
                text = eintrag if isinstance(eintrag, str) else (
                    eintrag["zitat"] if schluessel == "painpoints" else eintrag["text"])
                k = _norm(text)
                if not k:
                    continue
                if k not in gesehen:
                    gesehen[k] = eintrag
                elif schluessel in _MIT_DATUM and not gesehen[k]["datum"]:
                    gesehen[k]["datum"] = eintrag["datum"]
        a[schluessel] = list(gesehen.values())
    stimmungen = [t["stimmung"] for t in teile if t["stimmung"]]
    a["stimmung"] = stimmungen[-1] if stimmungen else ""
    e = a["ergebnis"]
    e["stattgefunden"] = False  # wahr, sobald ein Stueck es meldet
    for t in teile:
        er = t["ergebnis"]
        e["stattgefunden"] = e["stattgefunden"] or er["stattgefunden"]
        if er["erfolg"] is not None:
            e["erfolg"] = er["erfolg"]
        if er["was"]:
            e["was"] = er["was"]
        a["felder"].update(t.get("felder") or {})  # spaetere Nennung gewinnt
    return a


def auswerten(segmente: list[dict]) -> dict:
    """Mitschrift -> Auswertung (alle Schluessel aus ABSCHNITTE plus `ergebnis`).

    Wirft `ollama.OllamaFehler`, wenn Ollama fehlt oder zweimal kein JSON liefert.
    """
    beginne = _beginne(segmente)
    stuecke = _stuecke(_zeilen(segmente))
    LOG.info("Auswertung: %d Segmente in %d Stuecken", len(segmente), len(stuecke))
    if not stuecke:
        return _leer()
    teile = []
    for stueck in stuecke:
        roh = _json_aufruf(SYSTEM_PROMPT, stueck)
        teile.append(_normalisieren(roh, segmente, beginne))
    if len(teile) == 1:
        return teile[0]
    a = _vereinen(teile)
    kurz = [t["kurzfassung"] for t in teile if t["kurzfassung"]]
    if len(kurz) > 1:
        roh = _json_aufruf(SYSTEM_ZUSAMMENFUEHREN,
                           "\n".join(f"{i}. {k}" for i, k in enumerate(kurz, 1)))
        a["kurzfassung"] = _str(roh.get("kurzfassung")) or kurz[0]
    else:
        a["kurzfassung"] = kurz[0] if kurz else ""
    return a


# ---------- Ausgaben ----------

def _zeile(schluessel: str, eintrag) -> str:
    if schluessel == "painpoints":
        rest = ", ".join(x for x in (eintrag.get("zeit"), eintrag.get("sprecher")) if x)
        return f"- „{eintrag['zitat']}“" + (f" ({rest})" if rest else "")
    if isinstance(eintrag, dict):
        mit = f" (bis {eintrag['datum']})" if eintrag.get("datum") else ""
        return f"- {eintrag['text']}{mit}"
    return f"- {eintrag}"


def markdown(a: dict) -> str:
    teile = []
    for schluessel, titel in ABSCHNITTE:
        wert = a.get(schluessel)
        if schluessel in _TEXTE:
            zeilen = [f"- {wert}"] if wert else []
        else:
            zeilen = [_zeile(schluessel, e) for e in (wert or [])]
        teile.append(f"## {titel}\n" + "\n".join(zeilen or ["- —"]))
    return "\n\n".join(teile) + "\n"


def vorschlaege(a: dict, lead_ids: list[str], heute: date | None = None) -> list[dict]:
    """CRM-Vorschlaege; Felix bestaetigt sie. `heute` ist fuer Tests einspeisbar."""
    if not lead_ids:
        return []
    lead = lead_ids[0]
    heute = heute or datetime.now(_ZEITZONE).date()
    standard = (heute + timedelta(days=WIEDERVORLAGE_TAGE)).isoformat()
    aus = [{"art": "termin_ergebnis", "lead_id": lead, "daten": a["ergebnis"]}]
    for z in a.get("zusagen_felix") or []:
        aus.append({"art": "wiedervorlage", "lead_id": lead,
                    "daten": {"faellig_am": z.get("datum") or standard,
                              "notiz": z["text"]}})
    felder = a.get("felder")
    if isinstance(felder, dict):
        for name in ("title", "company"):
            wert = _str(felder.get(name))
            if wert:
                aus.append({"art": "feld", "lead_id": lead,
                            "daten": {"feld": name, "wert": wert}})
    return aus


def _liste(eintraege) -> list[str]:
    return [_zeile("", e) for e in eintraege or []]


def kundenfassung(a: dict, anrede: str) -> str:
    """Klartext fuer die E-Mail. Nie Painpoints, Einwaende, Stimmung, Beteiligte."""
    teile = [f"{anrede.strip()},", "vielen Dank für das Gespräch. "
             "Hier die wichtigsten Punkte in Kürze."]
    if a.get("kurzfassung"):
        teile.append("Kurzfassung\n" + a["kurzfassung"])
    if a.get("ziele"):
        teile.append("Ihre Ziele und Wünsche\n" + "\n".join(_liste(a["ziele"])))
    zusagen = []
    if a.get("zusagen_felix"):
        zusagen += ["Von uns:"] + _liste(a["zusagen_felix"])
    if a.get("zusagen_kunde"):
        zusagen += ["Von Ihnen:"] + _liste(a["zusagen_kunde"])
    if zusagen:
        teile.append("Zusagen\n" + "\n".join(zusagen))
    if a.get("naechste_schritte"):
        teile.append("Nächste Schritte\n" + "\n".join(_liste(a["naechste_schritte"])))
    if a.get("offene_fragen"):
        teile.append("Offene Fragen\n" + "\n".join(_liste(a["offene_fragen"])))
    teile.append("Viele Grüße")
    return "\n\n".join(teile) + "\n"
