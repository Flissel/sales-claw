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
from datetime import datetime, timedelta, timezone

import google_kalender
import kalender_sichtbarkeit
import kalenderquellen
import post_struktur
import post_tresor
import server

FENSTER_ZURUECK_TAGE = 30
FENSTER_VORAUS_TAGE = 180
INTERVAL_S = float(os.environ.get("KALENDER_INTERVAL_S", "300"))
NEU_PRUEFEN_S = 30.0
KALENDER_ONCE = os.environ.get("KALENDER_ONCE", "").strip().lower() in ("1", "true", "yes", "ja")
ENV_SCHLUESSEL_PRIVAT = "KALENDER_SCHLUESSEL_PRIVAT"
KONTO_FEHLT = "Google-Konto fehlt – bitte neu verbinden"
ZUGANG_UNLESBAR = "Zugang nicht lesbar – bitte neu verbinden"
SCHLUESSEL_FEHLT = "Kalender-Schlüssel fehlt – Betreiber muss einrichten"

LOG = logging.getLogger("sales-kalender")
_STOPP = threading.Event()


def _zugang(konto_id: str, zugaenge: dict) -> str:
    """Access-Token des Kontos - HOECHSTENS EINMAL je Konto und Runde.

    Auch ein Fehlschlag wird gemerkt (als Ausnahme), damit weitere Quellen
    desselben Kontos Google nicht noch einmal fragen."""
    if konto_id not in zugaenge:
        try:
            versiegelt = server.kalender_konto_zugang(konto_id)
            if not versiegelt:
                raise google_kalender.GoogleFehler(KONTO_FEHLT)
            try:
                refresh = post_tresor.oeffnen(
                    versiegelt, env_name=ENV_SCHLUESSEL_PRIVAT)
            except post_tresor.SchluesselFehlt:
                raise google_kalender.GoogleFehler(SCHLUESSEL_FEHLT) from None
            except post_tresor.TresorFehler:
                raise google_kalender.GoogleFehler(ZUGANG_UNLESBAR) from None
            zugaenge[konto_id] = google_kalender.zugang_erneuern(refresh)
        except google_kalender.GoogleFehler as e:
            zugaenge[konto_id] = e
    erg = zugaenge[konto_id]
    if isinstance(erg, Exception):
        raise erg
    return erg


def _google_holen(quelle: dict, zugaenge: dict) -> tuple[list, str | None]:
    """Termine einer Google-Quelle -> (termine, fehler). Der Fehlertext ist
    immer der feste Text des GoogleFehler, nie eine Google-Antwort."""
    if not quelle.get("konto_id") or not quelle.get("google_id"):
        return [], KONTO_FEHLT
    try:
        token = _zugang(str(quelle["konto_id"]), zugaenge)
        jetzt = datetime.now(timezone.utc)
        return google_kalender.termine_mit_hinweis(
            token, quelle["google_id"],
            jetzt - timedelta(days=FENSTER_ZURUECK_TAGE),
            jetzt + timedelta(days=FENSTER_VORAUS_TAGE))
    except google_kalender.GoogleFehler as e:
        return [], str(e)


def quelle_abgleichen(quelle: dict, zugaenge: dict | None = None
                      ) -> tuple[int | None, str | None]:
    """Eine Quelle lesen und speichern -> (Anzahl, Fehlertext).

    Erfolg: Termine ersetzt, Stand gesetzt. Fehler ohne Termine: alte Termine
    bleiben, nur der Fehler wird festgehalten. Teilerfolg (Termine UND Fehler):
    die Termine werden gespeichert und der Fehler bleibt stehen.

    `zugaenge` = Access-Tokens je Konto fuer die laufende Runde (siehe
    `_zugang`); ohne Angabe gilt eine eigene, einmalige Runde."""
    qid = quelle["id"]
    if quelle.get("art") == "google":
        termine, fehler = _google_holen(quelle, {} if zugaenge is None else zugaenge)
    else:
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


def _abgleichen_geschuetzt(quelle: dict, zugaenge: dict | None = None) -> bool:
    """Wahr bei Fehler. Eine Quelle darf die anderen nie aufhalten."""
    try:
        _, fehler = quelle_abgleichen(quelle, zugaenge)
    except Exception as e:  # noqa: BLE001 - Meldung koennte Inhalt zitieren
        LOG.error("Quelle %s: Abgleich fehlgeschlagen (%s)", quelle["id"], type(e).__name__)
        # Der Betreiber soll einen Fehlertext sehen; nur der Typ, nie str(e).
        try:
            server.kalenderquelle_stand_setzen(
                quelle["id"], None, f"Abgleich fehlgeschlagen ({type(e).__name__})")
        except Exception as e2:  # noqa: BLE001 - die Runde laeuft weiter
            LOG.error("Quelle %s: Stand nicht gesetzt (%s)", quelle["id"], type(e2).__name__)
        return True
    if fehler:
        LOG.warning("Quelle %s: Fehler gemeldet", quelle["id"])
    return bool(fehler)


def runde() -> dict:
    bilanz = {"quellen": 0, "fehler": 0}
    zugaenge: dict = {}     # ein Access-Token je Konto und Runde
    for quelle in server.kalenderquellen_lesen():
        if _STOPP.is_set():
            break
        bilanz["quellen"] += 1
        if _abgleichen_geschuetzt(quelle, zugaenge):
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
    zugaenge: dict = {}
    for quelle in neue_quellen():
        if _STOPP.is_set():
            return
        _abgleichen_geschuetzt(quelle, zugaenge)


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
