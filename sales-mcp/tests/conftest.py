"""Gemeinsame Fixtures fuer die ganze Testsuite.

Datei-Verzeichnisse leeren (W6, Schlusspruefung 11.09.2026)
-------------------------------------------------------------------------
Dreimal in diesem Vorhaben sind Tests ueber zurueckgelassene Dateien
kollidiert (zwei Tests erzeugen denselben Dateinamen — z. B. ueber
Kundenname+Datum+Uhrzeit, siehe `termin_bestaetigen`/`termin_einladen` —
und der zweite ueberschreibt oder liest die Datei des ersten) und wurden
jedes Mal LOKAL umgangen (eigens ungewoehnliche Testdaten gewaehlt statt
das Problem an der Wurzel zu beheben, siehe task-3-report,
Aufgabe-3-fix-round-3-Minor). Das macht die Aussage "N Tests gruen" von der
Ausfuehrungsreihenfolge und dem Ordnerzustand abhaengig — und ein
Suitelauf IM CONTAINER schreibt Testeinladungen standardmaessig in die
PRODUKTIVEN Pfade (`medien.ERZEUGT_VERZEICHNIS` = `/media-erzeugt`,
`recherche.REPORT_VERZEICHNIS` = `/reports`, beide unveraendert per
Default), wo sie ueber `medien_liste` als echte, anhaengbare Dateien
auftauchen wuerden.

Nach dem Muster der bestehenden DB-Fixtures (`truncate ... cascade` vor
jedem Test, siehe z. B. tests/test_termin_einladen.py::leer): diese
Fixture bringt zusaetzlich die BEIDEN Dateiverzeichnisse vor jedem Test in
einen sauberen, LEEREN Zustand.

Bewusst NICHT das produktive Verzeichnis leeren
-------------------------------------------------------------------------
Ein `shutil.rmtree(medien.ERZEUGT_VERZEICHNIS)` waere hier lebensgefaehrlich:
laeuft die Suite aus irgendeinem Grund OHNE Container-Isolation (Betreiber
startet `pytest` direkt auf dem Host, mit denselben Umgebungsvariablen wie
der Dienst), zeigen die Defaultpfade auf das ECHTE `media-erzeugt/` bzw.
`reports/` des Betreibers — Gruende, die dort liegen, waeren weg. Diese
Fixture biegt beide Pfade deshalb GRUNDSAETZLICH auf ein eigenes
Testverzeichnis unter dem System-Temp-Verzeichnis um (nie auf die
Standardpfade selbst) und leert NUR dieses Testverzeichnis.

Einzelne Tests koennen die Umbiegung weiterhin selbst ueberschreiben (z. B.
fuer "Ordner nicht beschreibbar"-Faelle, siehe
test_termin_einladen.py::test_nicht_beschreibbarer_medienordner_wird_gemeldet)
— `monkeypatch` ist pro Testfunktion dieselbe Instanz fuer diese und jede
lokale Fixture, sie raeumt beim Teardown in umgekehrter Reihenfolge aller
`setattr`-Aufrufe auf; ein Konflikt entsteht nicht.
"""
import os
import shutil
import tempfile

import pytest

import medien
import recherche

# Fester Name (nicht `tempfile.mkdtemp()` je Testlauf): das Verzeichnis
# soll ZWISCHEN Tests desselben Laufs STABIL bleiben (die Fixture leert
# es, sie legt es nicht jedes Mal neu an anderer Stelle an) — genau das
# deckt den Kollisionsfall ab, um den es hier geht.
_TESTORDNER = os.path.join(tempfile.gettempdir(), "sales-mcp-test-dateien")
_MEDIEN_ERZEUGT_TEST = os.path.join(_TESTORDNER, "media-erzeugt")
_REPORTS_TEST = os.path.join(_TESTORDNER, "reports")


def _geleert(pfad: str) -> str:
    """`pfad` frisch und leer anlegen — vorhandener Inhalt (von einem
    frueheren Testlauf oder dem vorigen Test) faellt weg."""
    if os.path.exists(pfad):
        shutil.rmtree(pfad)
    os.makedirs(pfad, exist_ok=True)
    return pfad


@pytest.fixture(autouse=True)
def _dateiverzeichnisse_geleert(monkeypatch):
    """Autouse fuer JEDEN Test der Suite: `medien.ERZEUGT_VERZEICHNIS` und
    `recherche.REPORT_VERZEICHNIS` zeigen waehrend der Suite immer auf das
    (frisch geleerte) Testverzeichnis oben, nie auf die Standardpfade.

    `medien.MEDIA_VERZEICHNIS` (der UPLOAD-Ordner, von Menschen befuellt)
    bleibt bewusst UNANGETASTET — dort legt kein Test in dieser Suite
    etwas ab, ihn zu leeren waere eine Aenderung ohne Bezug zu diesem
    Mangel."""
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS",
                        _geleert(_MEDIEN_ERZEUGT_TEST))
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS",
                        _geleert(_REPORTS_TEST))
    yield
