"""Welche Schemanamen die Wache durchlaesst — und welche nicht.

WELCHE KAPUTTE FASSUNG FAENGT DIESER TEST?
-------------------------------------------------------------------------
Der Schemaname wird in die Verbindungsoption `-c search_path=<name>`
eingesetzt. Ein Muster, das zu viel erlaubt, ist eine Einschleusungsluecke:
`sales -c log_statement=all` oder `public, sales` waeren zwei Beispiele, die
kein Fehler aufhalten wuerde. Ein Muster, das zu wenig erlaubt, macht jeden
neuen Laden unmoeglich. Beide Haelften stehen deshalb hier.

Die Wache laeuft auf MODULEBENE (server.py:81). Sie laesst sich nicht
aufrufen, also pruefen wir die Regel selbst — und halten mit dem letzten
Test fest, dass die Regel wirklich DIE ist, die server.py benutzt.

KORREKTUR GEGENUEBER DEM BRIEF (task-2-brief.md):
-------------------------------------------------------------------------
Der Brief listet `"sales_" + "x" * 31` unter VERBOTEN ("zu lang"). Das
Muster erlaubt nach dem Unterstrich `[a-z]` plus bis zu 30 weitere Zeichen,
also 31 Zeichen insgesamt — dieser Name IST erlaubt, der Test aus dem Brief
haette also zu Recht fehlgeschlagen. Stattdessen: `"sales_" + "x" * 32"`
(32 Zeichen nach dem Unterstrich, eins zu viel) unter VERBOTEN, und der
Grenzfall "genau 31, muss erlaubt sein" zusaetzlich unter ERLAUBT — damit
ist die Grenze von beiden Seiten festgehalten, nicht nur von der Seite, die
ohnehin schon getroffen wurde.
"""
import re
from pathlib import Path

import pytest

import server

ERLAUBT = ["sales", "sales_test", "sales_ivan", "sales_a", "sales_b2",
           "sales_lange_aber_zulaessige_kennung",
           # Grenzfall: genau 31 Zeichen nach dem Unterstrich (1 Buchstabe
           # + 30 weitere) — die laengste noch erlaubte Kennung.
           "sales_" + "a" + "x" * 30]

VERBOTEN = [
    "",                        # leer
    "public",                  # fremdes Schema
    "Sales",                   # Grossbuchstaben
    "sales_",                  # Unterstrich ohne Namen
    "sales_1",                 # Ziffer als erstes Zeichen des Namens
    "sales-ivan",              # Bindestrich
    "sales ivan",              # Leerzeichen
    "sales_ivan; drop schema sales cascade",
    "sales -c log_statement=all",
    "public, sales",
    # zu lang: 32 Zeichen nach dem Unterstrich, einer mehr als die 31
    # erlaubten (1 Buchstabe + 30 weitere). Siehe Korrektur-Hinweis oben —
    # mit 31 Zeichen (die urspruengliche Zahl aus dem Brief) waere dieser
    # Name faelschlich als verboten erwartet worden, obwohl das Muster ihn
    # zulaesst.
    "sales_" + "x" * 32,
]


@pytest.mark.parametrize("name", ERLAUBT)
def test_erlaubte_namen(name):
    assert server.SCHEMA_MUSTER.fullmatch(name), name


@pytest.mark.parametrize("name", VERBOTEN)
def test_verbotene_namen(name):
    assert not server.SCHEMA_MUSTER.fullmatch(name), name


def test_die_wache_benutzt_wirklich_dieses_muster():
    """Sonst prueften die Tests oben eine Regel, die niemand anwendet.

    Genau diese Falle ist in dieser Woche mehrfach aufgetreten: ein Test,
    der eine Hilfsfunktion prueft, waehrend der Aufrufer eine andere
    benutzt. Der Quelltext haelt die Kopplung fest.
    """
    quelle = (Path(server.__file__)).read_text(encoding="utf-8")
    assert "if not SCHEMA_MUSTER.fullmatch(SCHEMA):" in quelle
