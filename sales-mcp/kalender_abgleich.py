"""sales-kalender - gleicht die verbundenen Kalender in die Datenbank ab.

Spec 2026-11-08 (Kalender verbinden) §5 und §6. Alle INTERVAL_S Sekunden wird
jede aktive Quelle neu gelesen und ihre Termine in `kalender_termine`
ersetzt; neu verbundene Quellen (noch nie gelesen) holt der Dienst alle 30 s
sofort nach.

DATENSPARSAMKEIT (Spec §6.3). Gehoert eine Quelle einer anderen Person als dem
Laden-Besitzer und ist sie privat, werden titel und ort gar nicht erst
gespeichert (`kalender_sichtbarkeit.details_speichern`). Das Protokoll nennt
nur Quell-Kennung, Zahlen und Fehler-TYPEN - nie Titel, Ort oder Adresse.

FEHLER. Schlaegt ein Abruf fehl, bleiben die alten Termine stehen und
`letzter_fehler` wird gesetzt; die Quelle zaehlt dann als Luecke, nie als frei.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading

import kalender_sichtbarkeit
import kalenderquellen
import post_struktur
import server

FENSTER_ZURUECK_TAGE = 30
FENSTER_VORAUS_TAGE = 180
INTERVAL_S = float(os.environ.get("KALENDER_INTERVAL_S", "300"))
NEU_PRUEFEN_S = 30.0
KALENDER_ONCE = os.environ.get("KALENDER_ONCE", "").strip().lower() in ("1", "true", "yes", "ja")
GOOGLE_NOCH_NICHT = "Google noch nicht unterstützt"

LOG = logging.getLogger("sales-kalender")
_STOPP = threading.Event()


def quelle_abgleichen(quelle: dict) -> tuple[int | None, str | None]:
    """Eine Quelle lesen und speichern -> (Anzahl, Fehlertext).

    Erfolg: Termine ersetzt, Stand gesetzt. Fehler ohne Termine: alte Termine
    bleiben, nur der Fehler wird festgehalten. Teilerfolg (Termine UND Fehler):
    die Termine werden gespeichert und der Fehler bleibt stehen."""
    qid = quelle["id"]
    if quelle.get("art") != "ics":
        server.kalenderquelle_stand_setzen(qid, None, GOOGLE_NOCH_NICHT)
        return None, GOOGLE_NOCH_NICHT
    termine, fehler = kalenderquellen.hole(
        quelle["url"], FENSTER_ZURUECK_TAGE, FENSTER_VORAUS_TAGE)
    if fehler and not termine:
        server.kalenderquelle_stand_setzen(qid, None, fehler)
        return None, fehler
    details = kalender_sichtbarkeit.details_speichern(
        quelle["besitzer"], quelle["bereich"], post_struktur.container_besitzer())
    anzahl = server.kalendertermine_ersetzen(qid, termine, details)
    server.kalenderquelle_stand_setzen(qid, anzahl, fehler)
    return anzahl, fehler


def _abgleichen_geschuetzt(quelle: dict) -> bool:
    """Wahr bei Fehler. Eine Quelle darf die anderen nie aufhalten."""
    try:
        _, fehler = quelle_abgleichen(quelle)
    except Exception as e:  # noqa: BLE001 - Meldung koennte Inhalt zitieren
        LOG.error("Quelle %s: Abgleich fehlgeschlagen (%s)", quelle["id"], type(e).__name__)
        return True
    if fehler:
        LOG.warning("Quelle %s: Fehler gemeldet", quelle["id"])
    return bool(fehler)


def runde() -> dict:
    bilanz = {"quellen": 0, "fehler": 0}
    for quelle in server.kalenderquellen_lesen():
        if _STOPP.is_set():
            break
        bilanz["quellen"] += 1
        if _abgleichen_geschuetzt(quelle):
            bilanz["fehler"] += 1
    return bilanz


def neue_quellen() -> list[dict]:
    """Aktive Quellen, die noch nie gelesen wurden (frisch verbunden)."""
    return [q for q in server.kalenderquellen_lesen() if q["zuletzt_gelesen"] is None]


def _stoppen(signum, _rahmen) -> None:
    LOG.info("Signal %s empfangen - Ende.", signal.Signals(signum).name)
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


def _neue_nachholen() -> None:
    for quelle in neue_quellen():
        if _STOPP.is_set():
            return
        _abgleichen_geschuetzt(quelle)


def main() -> int:
    _logging_einrichten()
    _STOPP.clear()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stoppen)
        except ValueError:
            pass    # nicht im Hauptthread (Tests)
    LOG.info("Start: schema=%s intervall=%gs once=%s",
             server.SCHEMA, INTERVAL_S, KALENDER_ONCE)
    while not _STOPP.is_set():
        try:
            LOG.info("Runde: %s", runde())
        except Exception as e:  # noqa: BLE001
            LOG.error("Runde uebersprungen (%s)", type(e).__name__)
        if KALENDER_ONCE:
            break
        # Bis zur naechsten vollen Runde alle 30 s frisch verbundene Quellen holen.
        gewartet = 0.0
        while gewartet < INTERVAL_S and not _STOPP.is_set():
            schritt = min(NEU_PRUEFEN_S, INTERVAL_S - gewartet)
            if _STOPP.wait(schritt):
                break
            gewartet += schritt
            try:
                _neue_nachholen()
            except Exception as e:  # noqa: BLE001
                LOG.error("Nachholen uebersprungen (%s)", type(e).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
