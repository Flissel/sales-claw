"""KI-Einordnung: eine Rubrik je Mitschrift (Mitschriften-Ablage).

Dieselbe KI wie die Auswertung. Fehlschlag -> Unsortiert; eine von Hand gesetzte
Rubrik (rubrik_manuell) wird nie ueberschrieben. Hoechstens MAX_RUBRIKEN Rubriken
bindet nur die KI. Logs: nur gekuerzte uid und Fehlerart; nie Titel oder Rubrik-Namen.
"""
import json
import logging
from datetime import timedelta

import ollama
import server
from mitschrift_bericht import UNSORTIERT, rubrik_angleichen, rubrik_normalisieren, uid8

log = logging.getLogger("mitschrift_einordnung")

MAX_RUBRIKEN = 12
MAX_VERSUCHE = 3
NEUVERSUCH_NACH = timedelta(hours=1)
KI_TIMEOUT_S = 120
KURZFASSUNG_MAX = 1500
BETEILIGTE_MAX = 10

SYSTEM = (
    "Du ordnest die Mitschrift eines Termins einer Rubrik (Ordner) zu. "
    'Antworte ausschliesslich mit JSON: {"rubrik": "...", "neu": true|false}. '
    "Bevorzuge eine der vorhandenen Rubriken, wenn sie passt (neu: false). "
    "Lege nur dann eine neue Rubrik an, wenn keine vorhandene passt (neu: true). "
    "Der Name besteht aus 1–3 Wörtern, steht in der Mehrzahl und ist deutsch. "
    'Beispiele: "Kurse", "Kundentermine", "Interne Besprechungen".'
)
HINWEIS_GRENZE = (
    "\n\nEs gibt bereits die Höchstzahl an Rubriken. Lege keine neue an: "
    "wähle eine vorhandene Rubrik aus der Liste."
)


def vorhandene_rubriken() -> list[tuple[str, int]]:
    z = server._q("select rubrik, count(*) as n from termin_mitschriften "
                  "where rubrik is not null and rubrik <> %s "
                  "group by rubrik order by n desc, rubrik", (UNSORTIERT,))
    return [(r["rubrik"], int(r["n"])) for r in z]


def _nutzertext(eingabe: dict, vorhandene: list[tuple[str, int]]) -> str:
    beteiligte = [str(b) for b in (eingabe.get("beteiligte") or [])][:BETEILIGTE_MAX]
    liste = ", ".join(f"{n} ({c})" for n, c in vorhandene) or "(noch keine)"
    return (f"Titel: {eingabe.get('titel') or ''}\n"
            f"Art: {eingabe.get('art') or ''}\n"
            f"Beteiligte: {', '.join(beteiligte)}\n"
            f"Kurzfassung: {str(eingabe.get('kurzfassung') or '')[:KURZFASSUNG_MAX]}\n"
            f"Vorhandene Rubriken (Anzahl): {liste}")


def _antwort(system: str, nutzer: str, namen: list[str]) -> str:
    roh = ollama.chat(system, nutzer, als_json=True, timeout_s=KI_TIMEOUT_S)
    d = json.loads(roh)
    if not isinstance(d, dict):
        raise ValueError("Antwort ist kein Objekt")
    name = rubrik_normalisieren(d.get("rubrik"))
    if name is None or name.casefold() == UNSORTIERT.casefold():
        raise ValueError("unbrauchbare Rubrik")
    return rubrik_angleichen(name, namen)


def rubrik_waehlen(eingabe: dict, vorhandene: list[tuple[str, int]]) -> str:
    namen = [n for n, _ in vorhandene]
    nutzer = _nutzertext(eingabe, vorhandene)
    wahl = _antwort(SYSTEM, nutzer, namen)
    if len(namen) >= MAX_RUBRIKEN and wahl not in namen:
        wahl = _antwort(SYSTEM + HINWEIS_GRENZE, nutzer, namen)
        if wahl not in namen:
            raise ValueError("keine vorhandene Rubrik gewaehlt")
    return wahl


def _eingabe(zeile: dict) -> dict:
    aj = zeile.get("auswertung_json")
    if isinstance(aj, str):
        try:
            aj = json.loads(aj)
        except ValueError:
            aj = {}
    if not isinstance(aj, dict):
        aj = {}
    return {"titel": zeile.get("titel") or zeile.get("thema") or "",
            "art": aj.get("art") or "",
            "kurzfassung": aj.get("kurzfassung") or "",
            "beteiligte": aj.get("beteiligte") if isinstance(aj.get("beteiligte"), list) else []}


def einordnen(uid: str) -> str:
    z = server._q("select m.rubrik, m.rubrik_manuell, m.auswertung_json, a.titel, a.thema "
                  "from termin_mitschriften m left join termin_akten a on a.uid = m.uid "
                  "where m.uid = %s", (uid,))
    if not z:
        return UNSORTIERT
    if z[0]["rubrik_manuell"]:
        return z[0]["rubrik"] or UNSORTIERT
    try:
        rubrik = rubrik_waehlen(_eingabe(z[0]), vorhandene_rubriken())
    except Exception as e:  # KI-Pfad: jede Stoerung -> Unsortiert; nie die Meldung loggen
        log.warning("einordnung %s fehlgeschlagen: %s", uid8(uid), type(e).__name__)
        rubrik = UNSORTIERT
    g = server._q("update termin_mitschriften set rubrik = %s, "
                  "einordnung_versuche = einordnung_versuche + 1, einordnung_am = now() "
                  "where uid = %s and rubrik_manuell = false returning rubrik",
                  (rubrik, uid))
    if g:
        log.info("einordnung %s fertig", uid8(uid))
        return g[0]["rubrik"]
    n = server._q("select rubrik from termin_mitschriften where uid = %s", (uid,))
    return (n[0]["rubrik"] if n else None) or UNSORTIERT
