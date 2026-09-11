"""Selbsttest der gemeinsamen Datei-Verzeichnis-Fixture (W6, Schlusspruefung
11.09.2026 — die Fixture selbst steht in tests/conftest.py).

Reihenfolge ist hier bewusst TEIL des Tests: `test_a_...` laeuft vor
`test_b_...` (Pytest sammelt Tests standardmaessig in Quelltextreihenfolge
innerhalb einer Datei; `requirements.txt` zieht kein Random-Order-Plugin).
`test_a_...` hinterlaesst eine Datei in beiden Verzeichnissen, `test_b_...`
prueft, dass keine von ihnen mehr da ist — genau der Kollisionsmechanismus
(„zurueckgelassene Dateien"), der in diesem Vorhaben schon dreimal lokal
umgangen wurde (eigens ungewoehnliche Testdaten gewaehlt), statt an der
Wurzel behoben zu werden.
"""
import os

import medien
import recherche


def test_a_hinterlaesst_dateien_in_beiden_verzeichnissen():
    with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, "hinterlassen.ics"),
              "w", encoding="utf-8") as f:
        f.write("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    with open(os.path.join(recherche.REPORT_VERZEICHNIS, "hinterlassen.ics"),
              "w", encoding="utf-8") as f:
        f.write("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    assert os.listdir(medien.ERZEUGT_VERZEICHNIS) == ["hinterlassen.ics"]
    assert os.listdir(recherche.REPORT_VERZEICHNIS) == ["hinterlassen.ics"]


def test_b_sieht_beide_verzeichnisse_wieder_leer():
    """Ohne die gemeinsame Fixture (tests/conftest.py) staende hier noch
    'hinterlassen.ics' aus test_a — ein zweiter Test, der zufaellig
    denselben Dateinamen erzeugt (z. B. gleicher Kundenname+Datum+Uhrzeit
    bei termin_bestaetigen/termin_einladen), wuerde die Datei des ersten
    ueberschreiben oder lesen, je nach Ausfuehrungsreihenfolge."""
    assert os.listdir(medien.ERZEUGT_VERZEICHNIS) == []
    assert os.listdir(recherche.REPORT_VERZEICHNIS) == []


def test_verzeichnisse_zeigen_nicht_auf_die_produktiven_standardpfade():
    """W6, ausdrueckliche Randbedingung: die Fixture darf NIE das echte
    Verzeichnis des Betreibers treffen, falls jemand die Suite ausserhalb
    des Containers (mit denselben Umgebungsvariablen wie der Dienst)
    laufen laesst."""
    assert medien.ERZEUGT_VERZEICHNIS != "/media-erzeugt"
    assert recherche.REPORT_VERZEICHNIS != "/reports"
    assert os.path.isdir(medien.ERZEUGT_VERZEICHNIS)
    assert os.path.isdir(recherche.REPORT_VERZEICHNIS)
