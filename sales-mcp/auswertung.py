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
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ollama

LOG = logging.getLogger("auswertung")

# Vorgabe fuer kleine lokale Modelle; mit grossem Kontextfenster (sales-ki/Claude)
# per Umgebung AUSWERTUNG_STUECK_ZEICHEN hochsetzen, damit das Gespraech am Stueck
# ausgewertet wird (Runbook, KI-Tor).
AUSWERTUNG_STUECK_ZEICHEN = 12000
WIEDERVORLAGE_TAGE = 3

ABSCHNITTE: tuple[tuple[str, str], ...] = (
    ("kurzfassung", "Kurzfassung"),
    ("verlauf", "Gesprächsverlauf"),
    ("entscheidungen", "Entscheidungen"),
    ("painpoints", "Painpoints"),
    ("ziele", "Ziele und Wünsche"),
    ("ideen", "Ideen und Feedback"),
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
# Eintraege mit Segmentnummer als Beleg ({"text", "segment"[, "datum"]}).
_MIT_BELEG = ("entscheidungen", "zusagen_felix", "zusagen_kunde")
# Beim Zusammenfuehren mehrerer Stuecke nur angehaengt, nicht entdoppelt.
_ANHAENGEN = ("verlauf", "entscheidungen", "ideen")
ARTEN = ("kundentermin", "intern")
# Bei internen Gespraechen leer: es gibt keinen Kunden, der einwendet, zusagt oder
# Probleme hat; Pannen beim eigenen Ausprobieren sind keine Painpoints.
_NUR_KUNDENTERMIN = ("painpoints", "einwaende", "zusagen_kunde")
_ZEITZONE = ZoneInfo("Europe/Berlin")
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEGMENTZEILE = re.compile(r"^\[\d+\] ")
_SEGMENTZEILE_IM_STUECK = re.compile(r"^\[\d+\] ", re.MULTILINE)

SYSTEM_PROMPT = """Du bist ein sorgfaeltiger Protokollant und wertest die Mitschrift eines Gespraechs aus,
das Felix (Betreiber, Berater) gefuehrt hat. Ziel: Wer nicht dabei war, weiss danach alles
Wesentliche, was besprochen wurde. Gehe die GESAMTE Mitschrift von Anfang bis Ende durch und
lasse kein inhaltliches Thema aus, auch wenn es nicht nach Verkauf klingt. Die Mitschrift kann
ein Teil eines laengeren Gespraechs sein; werte dann nur diesen Teil aus.

Die Mitschrift stammt aus automatischer Spracherkennung: Saetze sind in kurze Segmente
zerhackt, einzelne Woerter koennen falsch erkannt sein, Sprecher "?" ist unbekannt. Lies
zusammenhaengend, erschliesse den Sinn aus dem Zusammenhang, korrigiere offensichtliche
Erkennungsfehler stillschweigend, aber erfinde nichts, was nicht gesagt wurde.

Format der Mitschrift: "[Nummer] Sprecher: Text". Zeilen der Form [Bild HH:MM] beschreiben, was zu diesem Zeitpunkt auf einem geteilten Bildschirm zu sehen war. Beziehe sie in Verlauf und Kurzfassung ein, wenn auf Gezeigtes Bezug genommen wird. Antworte NUR als JSON nach diesem Schema,
ohne Erklaerung, auf Deutsch. Schreibe in deiner Antwort echte Umlaute (ä, ö, ü) und ß
nach heutiger Rechtschreibung, nie ae, oe oder ue als Ersatz (auch wenn diese Anleitung
sie verwendet):
{
  "art": "kundentermin oder intern",
  "kurzfassung": "6 bis 12 Saetze: Anlass, Teilnehmer, Hauptthemen, wichtigste Aussagen, Ergebnis",
  "verlauf": [{"thema": "kurze Ueberschrift", "inhalt": "3 bis 8 Saetze: was dazu gesagt wurde, wer welche Position oder Idee hatte, Beispiele, Zahlen", "von": 0, "bis": 0}],
  "entscheidungen": [{"text": "was ausdruecklich festgelegt wurde", "segment": 0}],
  "painpoints": [{"zitat": "moeglichst woertlich", "segment": 0, "bedeutung": "warum das ein Problem ist"}],
  "ziele": ["Ziele und Wuensche der Gespraechspartner"],
  "ideen": ["Ideen, Vorschlaege und Feedback"],
  "fakten": ["Zahlen, Namen, Tools, Termine, Fristen, Budgets"],
  "einwaende": ["Einwaende und Bedenken"],
  "zusagen_felix": [{"text": "Was Felix ausdruecklich zusagt", "datum": "YYYY-MM-DD oder null", "segment": 0}],
  "zusagen_kunde": [{"text": "Was die Gespraechspartner ausdruecklich zusagen", "segment": 0}],
  "naechste_schritte": [{"text": "Naechster Schritt mit Verantwortlichem", "datum": "YYYY-MM-DD oder null"}],
  "beteiligte": ["Name - Rolle/Position im Gespraech"],
  "offene_fragen": ["Was offen blieb"],
  "stimmung": "1 bis 2 Saetze",
  "ergebnis": {"stattgefunden": true, "erfolg": null, "was": "1 bis 2 Saetze, was herauskam"},
  "felder": {"title": "neue Position des Kunden", "company": "neue Firma des Kunden"}
}
Regeln:
- "art": Zuerst bestimmen. "kundentermin", wenn Felix mit einem (moeglichen) Kunden spricht;
  "intern", wenn es ein Arbeits-, Team- oder Ideengespraech ohne Kunden ist. Bei "intern"
  bleiben "painpoints", "einwaende" und "zusagen_kunde" leer; fuelle stattdessen "ideen"
  mit den Ideen und dem Feedback.
- "verlauf": chronologisch, ein Eintrag je inhaltlichem Thema; "von"/"bis" sind die
  Segmentnummern, in denen das Thema besprochen wurde; Bereiche ueberlappen nicht.
  Lueckenlos: jeder inhaltliche Abschnitt des Gespraechs gehoert zu einem Thema, auch
  Nebenthemen und spaete Teile. Luecken zwischen den Bereichen nur fuer Smalltalk und
  technische Einrichtung.
- Kein Smalltalk und nichts Organisatorisches (Begruessung, Verabschiedung, Privates,
  eigene Folgetermine) in "verlauf" oder "naechste_schritte".
- Technische Einrichtung des Gespraechs gehoert weder in "verlauf" noch in "painpoints":
  Bildschirm teilen, Ton und Mikrofon, Kamera, Einwahl, Verbindung, wer ist da, wer hoert
  mich. Beispiel: "Siehst du meinen Bildschirm? - Nein, warte, jetzt." ist kein Thema und
  kein Painpoint. Ein Thema ist es nur, wenn ueber ein Produkt oder Werkzeug inhaltlich
  gesprochen wird (z. B. "Unser Videotool bricht bei Kunden staendig ab, das kostet uns
  Auftraege").
- Zusagen und Entscheidungen nur, wenn sie ausdruecklich ausgesprochen wurden, nicht
  vermutet; "segment" ist die Nummer des Segments, das sie belegt.
- Painpoints nur fuer echte Probleme, Kosten oder Frust der Gespraechspartner, moeglichst
  woertlich zitiert; "segment" ist die Nummer des Segments, aus dem das Zitat stammt;
  "bedeutung" sagt in einem Satz, warum es ein Problem ist.
- Nenne keine Uhrzeiten. Nimm nur auf, was im Text steht. Leere Abschnitte sind leere Listen
  oder leere Texte. Datum nur, wenn ein konkretes Datum genannt wurde, sonst null.
- "felder" nur fuellen, wenn der Kunde ausdruecklich eine neue Position (title) oder eine
  neue Firma (company) nennt; sonst {} bzw. den Schluessel weglassen.
- "beteiligte": nur Menschen, die am Gespraech teilnehmen. Aufnahme- und Beobachter-Bots (z. B. "Laura (Bildschirm)", "VibeMind Mitschrift") sind keine Beteiligten. Jede Person nur einmal, mit vollem Namen, wenn er vorkommt."""

SYSTEM_ZUSAMMENFUEHREN = """Du bekommst Kurzfassungen aufeinanderfolgender Teile eines Gespraechs.
Fasse sie zu einer einzigen Kurzfassung in 6 bis 12 Saetzen zusammen: Anlass, Teilnehmer,
Hauptthemen, wichtigste Aussagen, Ergebnis. Erfinde nichts dazu. Schreibe echte Umlaute
(ä, ö, ü) und ß.
Antworte NUR als JSON auf Deutsch: {"kurzfassung": "..."}"""


def _stueck_zeichen() -> int:
    """Stueckgroesse aus AUSWERTUNG_STUECK_ZEICHEN; ungueltig oder <= 0 -> Vorgabe."""
    roh = os.environ.get("AUSWERTUNG_STUECK_ZEICHEN", "").strip()
    try:
        wert = int(roh)
    except ValueError:
        return AUSWERTUNG_STUECK_ZEICHEN
    return wert if wert > 0 else AUSWERTUNG_STUECK_ZEICHEN


# ---------- Normalisierung ----------

def _leer() -> dict:
    a: dict = {}
    for schluessel, _ in ABSCHNITTE:
        a[schluessel] = "" if schluessel in _TEXTE else []
    a["ergebnis"] = {"stattgefunden": True, "erfolg": None, "was": ""}
    a["felder"] = {}
    a["art"] = "kundentermin"
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


def _index(wert, anzahl: int) -> int | None:
    """Segmentnummer nur als echte Ganzzahl im gueltigen Bereich, sonst None."""
    if isinstance(wert, bool) or not isinstance(wert, int):
        return None
    return wert if 0 <= wert < anzahl else None


def _strings(wert) -> list[str]:
    if isinstance(wert, str):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    return [t for t in (_str(x) for x in wert) if t]


def _eintraege(wert, anzahl: int, mit_datum: bool, mit_beleg: bool) -> list[dict]:
    """Listen von {"text"[, "datum"][, "segment"]}; Strings werden zu Eintraegen."""
    if isinstance(wert, (str, dict)):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    aus = []
    for x in wert:
        roh = x if isinstance(x, dict) else {"text": x}
        text = _str(roh.get("text"))
        if not text:
            continue
        e: dict = {"text": text}
        if mit_datum:
            e["datum"] = _datum(roh.get("datum"))
        if mit_beleg:
            e["segment"] = _index(roh.get("segment"), anzahl)
        aus.append(e)
    return aus


def _verlauf_ordnen(eintraege: list[dict]) -> list[dict]:
    """Chronologisch nach "von"; Bereiche werden so gekappt, dass sie nicht ueberlappen.

    Eintraege ohne "von" bleiben hinter ihrem Vorgaenger. Ein Bereich, der ganz
    in einem frueheren liegt, verliert seine Segmentangabe, der Inhalt bleibt.
    """
    schluessel, letzter = [], -1
    for e in eintraege:
        if e["von"] is not None:
            letzter = e["von"]
        schluessel.append(letzter)
    geordnet = [e for _, e in sorted(zip(schluessel, eintraege), key=lambda p: p[0])]
    aus, ende = [], -1
    for e in geordnet:
        e = dict(e)
        if e["von"] is not None and e["von"] <= ende:
            e["von"] = ende + 1
            if e["bis"] is not None and e["von"] > e["bis"]:
                e["von"] = e["bis"] = None
        elif e["von"] is None and e["bis"] is not None and e["bis"] <= ende:
            e["bis"] = None
        for grenze in (e["von"], e["bis"]):
            if grenze is not None:
                ende = max(ende, grenze)
        aus.append(e)
    return aus


def _verlauf(wert, anzahl: int) -> list[dict]:
    if isinstance(wert, dict):
        wert = [wert]
    if not isinstance(wert, list):
        return []
    aus = []
    for x in wert:
        if not isinstance(x, dict):
            continue
        thema, inhalt = _str(x.get("thema")), _str(x.get("inhalt"))
        if not thema and not inhalt:
            continue
        von, bis = _index(x.get("von"), anzahl), _index(x.get("bis"), anzahl)
        if von is not None and bis is not None and bis < von:
            von, bis = bis, von
        aus.append({"thema": thema, "inhalt": inhalt, "von": von, "bis": bis})
    return _verlauf_ordnen(aus)


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
        zitat, index = _str(x.get("zitat")), _index(x.get("segment"), len(segmente))
        if not zitat or index is None:
            continue
        zeit, b = "", beginne[index]
        if start is not None and b is not None:
            try:
                sek = max(0, int((b - start).total_seconds()))
                zeit = f"{sek // 60:02d}:{sek % 60:02d}"
            except TypeError:  # naive gegen aware gemischt
                zeit = ""
        aus.append({"zitat": zitat, "zeit": zeit,
                    "sprecher": _str(segmente[index].get("sprecher")),
                    "bedeutung": _str(x.get("bedeutung"))})
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


def _art(wert) -> str:
    text = _str(wert).casefold()
    return text if text in ARTEN else "kundentermin"


def _nach_art(a: dict) -> dict:
    if a["art"] == "intern":
        for schluessel in _NUR_KUNDENTERMIN:
            a[schluessel] = []
    return a


def _normalisieren(roh: dict, segmente: list[dict], beginne: list[datetime | None]) -> dict:
    a = _leer()
    anzahl = len(segmente)
    for schluessel, _ in ABSCHNITTE:
        wert = roh.get(schluessel)
        if schluessel in _TEXTE:
            a[schluessel] = _str(wert)
        elif schluessel == "painpoints":
            a[schluessel] = _painpoints(wert, segmente, beginne)
        elif schluessel == "verlauf":
            a[schluessel] = _verlauf(wert, anzahl)
        elif schluessel in _MIT_DATUM or schluessel in _MIT_BELEG:
            a[schluessel] = _eintraege(wert, anzahl, schluessel in _MIT_DATUM,
                                       schluessel in _MIT_BELEG)
        else:
            a[schluessel] = _strings(wert)
    a["ergebnis"] = _ergebnis(roh.get("ergebnis"))
    a["felder"] = _felder(roh.get("felder"))
    a["art"] = _art(roh.get("art"))
    return _nach_art(a)


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

def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _zeilen(segmente: list[dict],
            bilder: list[tuple[datetime, str]] | None = None) -> list[str]:
    """Nummerierte Zeilen; die Nummer ist der globale Index ueber alle Stuecke.

    Bildzeilen `[Bild HH:MM] Beschreibung` (Europe/Berlin) haben keine Nummer und stehen
    vor dem ersten Segment mit beginn >= Aufnahmezeit; Segmente ohne lesbaren Beginn
    behalten ihren Platz, spaetere Bilder landen am Ende."""
    grenze = _stueck_zeichen()
    offen = sorted(((_utc(t), b) for t, b in (bilder or []) if b and str(b).strip()),
                   key=lambda x: x[0])
    beginne = _beginne(segmente)
    zeilen = []

    def bildzeile(t: datetime, beschr: str) -> str:
        text = " ".join(str(beschr).split())
        return f"[Bild {t.astimezone(_ZEITZONE):%H:%M}] {text}"[:grenze - 1]

    for i, s in enumerate(segmente):
        if beginne[i] is not None:
            b = _utc(beginne[i])
            while offen and offen[0][0] <= b:
                zeilen.append(bildzeile(*offen.pop(0)))
        text = " ".join(str(s.get("text") or "").split())
        if not text:
            continue
        zeile = f"[{i}] {str(s.get('sprecher') or '').strip() or '?'}: {text}"
        # Ein einzelnes Segment wird nie geteilt, aber hart gekappt, damit
        # kein Stueck die Grenze sprengt.
        zeilen.append(zeile[:grenze - 1])
    zeilen.extend(bildzeile(*b) for b in offen)
    return zeilen


def _stuecke(zeilen: list[str]) -> list[str]:
    grenze = _stueck_zeichen()
    stuecke, aktuell, laenge = [], [], 0
    for z in zeilen:
        if aktuell and laenge + len(z) + 1 > grenze:
            stuecke.append("\n".join(aktuell))
            aktuell, laenge = [], 0
        aktuell.append(z)
        laenge += len(z) + 1
    if aktuell:
        stuecke.append("\n".join(aktuell))
    return _bildstuecke_falten(stuecke)


def _bildstuecke_falten(stuecke: list[str]) -> list[str]:
    """Kein Stueck ohne Segmentzeile: ein reines Bild-Stueck haengt am vorigen (das erste
    am folgenden), auch ueber die Zeichengrenze hinaus. Sonst ueberschriebe die Antwort
    zu einem Stueck ohne Gespraech Stimmung und Ergebnis. Ohne Segmentzeile: []."""
    ergebnis: list[str] = []
    vorab: list[str] = []
    for s in stuecke:
        if _SEGMENTZEILE_IM_STUECK.search(s):
            ergebnis.append("\n".join(vorab + [s]))
            vorab = []
        elif ergebnis:
            ergebnis[-1] += "\n" + s
        else:
            vorab.append(s)
    return ergebnis


def _vereinen(teile: list[dict]) -> dict:
    a = _leer()
    for schluessel, _ in ABSCHNITTE:
        if schluessel in _TEXTE:
            continue
        if schluessel in _ANHAENGEN:
            a[schluessel] = [e for t in teile for e in t.get(schluessel) or []]
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
    a["verlauf"] = _verlauf_ordnen(a["verlauf"])
    stimmungen = [t["stimmung"] for t in teile if t["stimmung"]]
    a["stimmung"] = stimmungen[-1] if stimmungen else ""
    # intern nur, wenn jedes Stueck intern ist; im Zweifel bleiben die Verkaufsrubriken
    a["art"] = "intern" if all(t.get("art") == "intern" for t in teile) else "kundentermin"
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
    return _nach_art(a)


BOT_NAMEN = ("laura (bildschirm)", "laura", "vibemind mitschrift", "vibemind", "vexa")


def _name_norm(text) -> str:
    return " ".join(str(text).casefold().split())


def beteiligte_bereinigen(liste: list[str], sprecher: set[str]) -> list[str]:
    """Entfernt Aufnahme-Bots (ausser sie sprechen) und fasst Namensdoppel zusammen.

    Eintrag = "Name - Rolle". Ist die Wortmenge eines Namens Teilmenge eines anderen,
    bleibt ein Eintrag am Platz des ersten Vorkommens: laengerer Name, Rolle des ersten.
    """
    sprechende = {_name_norm(x) for x in sprecher if x}
    ergebnis: list[list] = []  # [Name, Rolle, Wortmenge]
    for eintrag in liste:
        if not isinstance(eintrag, str):
            continue
        teile = re.split(r" [-–] ", eintrag.strip(), maxsplit=1)
        name = " ".join(teile[0].split())
        if not name:
            continue
        rolle = teile[1].strip() if len(teile) > 1 else ""
        schluessel = _name_norm(name)
        if schluessel in BOT_NAMEN and schluessel not in sprechende:
            continue
        worte = set(schluessel.split())
        for vorhanden in ergebnis:
            if worte <= vorhanden[2] or vorhanden[2] <= worte:
                if len(worte) > len(vorhanden[2]):
                    vorhanden[0], vorhanden[2] = name, worte
                break
        else:
            ergebnis.append([name, rolle, worte])
    return [f"{n} - {r}" if r else n for n, r, _ in ergebnis]


def auswerten(segmente: list[dict],
              bilder: list[tuple[datetime, str]] | None = None) -> dict:
    """Mitschrift -> Auswertung (Schluessel aus ABSCHNITTE plus `ergebnis`, `felder`, `art`).

    Wirft `ollama.OllamaFehler`, wenn Ollama fehlt oder zweimal kein JSON liefert.
    """
    beginne = _beginne(segmente)
    stuecke = _stuecke(_zeilen(segmente, bilder))
    LOG.info("Auswertung: %d Segmente in %d Stuecken", len(segmente), len(stuecke))
    if not stuecke:
        return _leer()
    teile = []
    for stueck in stuecke:
        roh = _json_aufruf(SYSTEM_PROMPT, stueck)
        teile.append(_normalisieren(roh, segmente, beginne))
    sprechende = {x["sprecher"] for x in segmente if x.get("sprecher")}
    if len(teile) == 1:
        teile[0]["beteiligte"] = beteiligte_bereinigen(teile[0]["beteiligte"], sprechende)
        return teile[0]
    a = _vereinen(teile)
    a["beteiligte"] = beteiligte_bereinigen(a["beteiligte"], sprechende)
    kurz = [t["kurzfassung"] for t in teile if t["kurzfassung"]]
    if len(kurz) > 1:
        roh = _json_aufruf(SYSTEM_ZUSAMMENFUEHREN,
                           "\n".join(f"{i}. {k}" for i, k in enumerate(kurz, 1)))
        a["kurzfassung"] = _str(roh.get("kurzfassung")) or kurz[0]
    else:
        a["kurzfassung"] = kurz[0] if kurz else ""
    return a


# ---------- Ausgaben ----------

def _bereich(von, bis) -> str:
    if von is not None and bis is not None:
        return f"Segment {von}–{bis}" if bis != von else f"Segment {von}"
    if von is not None or bis is not None:
        return f"Segment {von if von is not None else bis}"
    return ""


def _verlauf_zeile(e: dict) -> str:
    bereich = _bereich(e.get("von"), e.get("bis"))
    kopf = f"**{e['thema']}**" if e.get("thema") else ""
    if bereich:
        kopf = f"{kopf} ({bereich})" if kopf else f"({bereich})"
    inhalt = e.get("inhalt") or ""
    if kopf and inhalt:
        return f"- {kopf}: {inhalt}" if e.get("thema") else f"- {inhalt} ({bereich})"
    return f"- {kopf or inhalt}"


def _zeile(schluessel: str, eintrag, belege: bool = True) -> str:
    if schluessel == "painpoints":
        rest = ", ".join(x for x in (eintrag.get("zeit"), eintrag.get("sprecher")) if x)
        zeile = f"- „{eintrag['zitat']}“" + (f" ({rest})" if rest else "")
        return zeile + (f" — {eintrag['bedeutung']}" if eintrag.get("bedeutung") else "")
    if schluessel == "verlauf":
        return _verlauf_zeile(eintrag)
    if isinstance(eintrag, dict):
        mit = f" (bis {eintrag['datum']})" if eintrag.get("datum") else ""
        beleg = (f" [Segment {eintrag['segment']}]"
                 if belege and eintrag.get("segment") is not None else "")
        return f"- {eintrag['text']}{mit}{beleg}"
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
    """Fuer den Kunden: ohne Segmentbelege."""
    return [_zeile("", e, belege=False) for e in eintraege or []]


def kundenfassung(a: dict, anrede: str) -> str:
    """Klartext fuer die E-Mail. Nie Verlauf, Painpoints, Ideen, Einwaende, Stimmung,
    Beteiligte und nie Segmentnummern."""
    teile = [f"{anrede.strip()},", "vielen Dank für das Gespräch. "
             "Hier die wichtigsten Punkte in Kürze."]
    if a.get("kurzfassung"):
        teile.append("Kurzfassung\n" + a["kurzfassung"])
    if a.get("ziele"):
        teile.append("Ihre Ziele und Wünsche\n" + "\n".join(_liste(a["ziele"])))
    if a.get("entscheidungen"):
        teile.append("Vereinbart\n" + "\n".join(_liste(a["entscheidungen"])))
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
