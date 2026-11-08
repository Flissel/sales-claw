"""Der Freigabe-Bote: spiegelt offene Freigabe-Eintraege als Vorschlaege nach Rowboat.

Stufe 1: "Annehmen" in Rowboat fuehrt nichts aus, der Bote liest die Entscheidung
nur zurueck (Stand je Eintrag) und raeumt auf, wenn der Eintrag geschlossen ist.
Kein Sprachmodell, keine Schreibzugriffe auf Rowboats Dateien: nur
POST /rpc/<kanal> des headless Servers. Der Server-Schluessel steht in einer
Datei und erscheint nie in Log, Eintrag oder Fehlertext (geloggt wird nur der Typ).
"""
import json
import logging
import os
import re
import signal
import sys
import threading
import urllib.request
from dataclasses import dataclass, field

import freigabe_eingang as fe

LOG = logging.getLogger("freigabe-bote")

ROWBOAT_RPC_URL = os.environ.get("ROWBOAT_RPC_URL", "http://127.0.0.1:3220").rstrip("/")
SCHLUESSEL_DATEI = os.environ.get("ROWBOAT_SCHLUESSEL_DATEI", "/run/rowboat-server-key")
ROWBOAT_HOST = "127.0.0.1:3220"
RPC_ZEITLIMIT_S = 10
TAKT_S = 60
TITEL_MAX = 160

_KENNUNG_IM_LINK = re.compile(r"/freigaben#(fg-[a-z2-7]{10})\)")
_STOPP = threading.Event()


def _titel_bereinigen(titel) -> str:
    ohne = re.sub(r"[@\[\]()]", "", str(titel or ""))
    einzeilig = re.sub(r"\s+", " ", ohne).strip()[:TITEL_MAX].strip()
    return einzeilig or "Ohne Titel"


def _link_label(art: str, quelle_ref: str) -> str:
    ref = str(quelle_ref or "")
    nummer = ref.rpartition("#")[2] if "#" in ref else ""
    if re.fullmatch(r"\d+", nummer):
        if art == "debugger_pr":
            return f"PR #{nummer}"
        if art == "selbstbild_rueckfrage":
            return f"Issue #{nummer}"
    return "Ansehen"


def vorschlagstext(eintrag: dict, basis: str) -> str:
    herkunft = fe.HERKUNFT_ANZEIGE.get(eintrag["herkunft"], eintrag["herkunft"])
    teile = [f"[{herkunft}] {_titel_bereinigen(eintrag.get('titel'))}"]
    link = eintrag.get("link")
    if link:
        sicher = str(link).replace("(", "%28").replace(")", "%29")
        label = _link_label(eintrag.get("art", ""), eintrag.get("quelle_ref", ""))
        teile.append(f"[{label}]({sicher})")
    teile.append(f"[Sales]({basis.rstrip('/')}/freigaben#{eintrag['kennung']})")
    return " · ".join(teile)


def kennung_in(text: str) -> str | None:
    """Nur eine Kennung aus einem Sales-Link zaehlt; die letzte im Text gewinnt."""
    treffer = _KENNUNG_IM_LINK.findall(text or "")
    return treffer[-1] if treffer else None


@dataclass
class RowboatStand:
    vorschlaege: list[str] = field(default_factory=list)
    items: list[tuple[str, str, bool]] = field(default_factory=list)  # (key, text, checked)
    signale: list[dict] = field(default_factory=list)


@dataclass
class Plan:
    hinzufuegen: list[str] = field(default_factory=list)
    zurueckziehen: list[str] = field(default_factory=list)   # exakte Vorschlagstexte
    abhaken: list[str] = field(default_factory=list)         # Item-Keys
    staende: dict[str, str] = field(default_factory=dict)    # kennung -> rowboat_stand
    aufgeraeumt: list[str] = field(default_factory=list)


def _signal_zu(signale: list[dict], art: str, kennung: str) -> bool:
    return any(s.get("kind") == art and kennung in str(s.get("key", "")) for s in signale)


def planen(eintraege: list[dict], aufraeumen: list[dict], stand: RowboatStand,
           basis: str) -> Plan:
    plan = Plan()
    vorschlag_text: dict[str, str] = {}
    for text in stand.vorschlaege:
        k = kennung_in(text)
        if k:
            vorschlag_text.setdefault(k, text)
    items_je_kennung: dict[str, list[tuple[str, str, bool]]] = {}
    for item in stand.items:
        k = kennung_in(item[1])
        if k:
            items_je_kennung.setdefault(k, []).append(item)

    for e in eintraege:
        k = e["kennung"]
        aktuell = e.get("rowboat_stand", "ungesichtet")
        items = items_je_kennung.get(k, [])
        if k in vorschlag_text:                                            # Regel 1
            if aktuell != "vorgeschlagen":
                plan.staende[k] = "vorgeschlagen"
            continue
        if items and (_signal_zu(stand.signale, "kept", k)                 # Regel 2
                      or aktuell in ("angenommen", "abgehakt")):
            neu = "abgehakt" if any(i[2] for i in items) else "angenommen"
            if aktuell != neu:
                plan.staende[k] = neu
            continue
        if not items and aktuell == "angenommen":                          # Regel 2, Item fehlt
            plan.staende[k] = "abgehakt"
            continue
        if not items and _signal_zu(stand.signale, "dismissed", k):        # Regel 3
            if aktuell != "abgelehnt":
                plan.staende[k] = "abgelehnt"
            continue
        if aktuell in ("ungesichtet", "vorgeschlagen"):                    # Regel 4
            plan.hinzufuegen.append(vorschlagstext(e, basis))

    for e in aufraeumen:                                                   # Regel 5
        k = e["kennung"]
        offen = [i for i in items_je_kennung.get(k, []) if not i[2]]
        if k in vorschlag_text:
            plan.zurueckziehen.append(vorschlag_text[k])
        plan.abhaken.extend(i[0] for i in offen)
        if k not in vorschlag_text and not offen:
            plan.aufgeraeumt.append(k)
    return plan


def _schluessel() -> str:
    with open(SCHLUESSEL_DATEI, encoding="utf-8") as f:
        return f.read().strip()


def _rpc(kanal: str, body):
    anfrage = urllib.request.Request(
        f"{ROWBOAT_RPC_URL}/rpc/{kanal}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {_schluessel()}",
                 "Host": ROWBOAT_HOST,
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(anfrage, timeout=RPC_ZEITLIMIT_S) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


def _items_sammeln(items, ziel: list) -> None:
    for item in items:
        ziel.append((str(item["key"]), str(item["text"]), bool(item["checked"])))
        _items_sammeln(item.get("children") or [], ziel)


def _stand_lesen() -> RowboatStand:
    todo = _rpc("todo:get", None)
    items: list[tuple[str, str, bool]] = []
    _items_sammeln([b["item"] for b in todo["list"]["blocks"] if b.get("kind") == "item"],
                   items)
    signale = _rpc("todo:plannerSignals", None).get("signals") or []
    return RowboatStand(vorschlaege=[str(s) for s in todo.get("suggestions") or []],
                        items=items, signale=list(signale))


def durchgang() -> int:
    basis = os.environ.get("UI_BASIS_URL", "").strip().rstrip("/")
    if not basis:
        LOG.error("UI_BASIS_URL fehlt - Rowboat wird nicht angefasst.")
        return 1
    try:
        eintraege = fe.offene()
        aufraeumen = fe.zum_aufraeumen()
        stand = _stand_lesen()
        plan = planen(eintraege, aufraeumen, stand, basis)
        staende = dict(plan.staende)
        if plan.hinzufuegen:
            antwort = _rpc("todo:addSuggestions", {"texts": plan.hinzufuegen})
            for text in antwort.get("added") or []:
                k = kennung_in(text)
                if k:
                    staende[k] = "vorgeschlagen"
        for text in plan.zurueckziehen:
            _rpc("todo:withdrawSuggestion", {"text": text})
        for key in plan.abhaken:
            antwort = _rpc("todo:setChecked", {"key": key, "checked": True})
            if isinstance(antwort, dict) and antwort.get("success") is False:
                LOG.warning("setChecked abgelehnt - der naechste Durchgang versucht es erneut.")
        for kennung, neu in staende.items():
            fe.rowboat_stand_setzen(kennung, neu)
        for kennung in plan.aufgeraeumt:
            fe.aufgeraeumt(kennung)
    except Exception as e:  # noqa: BLE001 - nur der Typ ins Log, nie der Text (Schluessel)
        LOG.error("Durchgang abgebrochen: %s", type(e).__name__)
        return 1
    LOG.info("Durchgang: +%d Vorschlaege, -%d zurueckgezogen, %d abgehakt, %d Staende, "
             "%d aufgeraeumt", len(plan.hinzufuegen), len(plan.zurueckziehen),
             len(plan.abhaken), len(staende), len(plan.aufgeraeumt))
    return 0


def _stopp_anfordern(signum, _rahmen) -> None:
    LOG.info("%s empfangen - nach diesem Durchgang ist Schluss.",
             signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main() -> int:
    _logging_einrichten()
    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    LOG.info("Start: schema=%s takt=%ds", fe.server.SCHEMA, TAKT_S)
    while not _STOPP.is_set():
        try:
            an = [a for a, v in fe.stufe2_lesen().items() if v]
            if an:  # wird nie ausgefuehrt, nur gemeldet
                LOG.warning("Stufe 2 ist fuer %s an - der Bote fuehrt nichts aus.",
                            ", ".join(an))
        except Exception as e:  # noqa: BLE001
            LOG.error("Stufe-2-Stand nicht lesbar: %s", type(e).__name__)
        durchgang()
        _STOPP.wait(TAKT_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
