"""Aehnlichkeitssuche ueber Kontaktnamen (17.09.2026).

`kontakt_suchen` sucht mit `ilike` und findet nur, was den Suchtext woertlich
enthaelt. Gemessen am echten Bestand blieben damit unsichtbar: „Webdesigner
Muenchen" neben „Webdesign Muenchen", „DataGuard - Datenschutz &
Informationssicherheit" neben „DATENSCHUTZ UND INFORMATIONSSICHERHEIT".

Was diese Tests festhalten, ist ueberwiegend, was das Werkzeug NICHT tut:

  * Es entscheidet NICHT, ob zwei Treffer dieselbe Person sind. Die Naehe
    steht dabei, und ein Hinweis sagt es ausdruecklich - „Ark Software GmbH"
    und „SMC Software GmbH" liegen bei 0.67 und sind verschiedene Firmen.
  * Es ersetzt NICHT die Nummern-Dedup in `kontakt_anlegen`. Die prueft
    Identitaet (normalisierte Nummer), dieses hier Aehnlichkeit (Schreibweise).
  * Eine Schwelle von 0 gibt es nicht - sie wuerde den ganzen Bestand nach
    Zufallsnaehe sortiert zurueckgeben, und der echte Treffer ginge darin unter.

Und eine Zusage MIT ihrer Grenze, beide gemessen: Zusaetze zum Namen findet
es („Ivan G." = 0.714), einen vertauschten Buchstaben in einem kurzen Namen
NICHT („Iwan" = 0.250, unter jeder brauchbaren Schwelle). Ein leeres Ergebnis
heisst deshalb „keine aehnliche Schreibweise", nicht „keine Variante" - fuer
kurze Namen gehoert ein Muster dazu (`name ~* '(iwan|ivan)'`). Die Aussage
„es gibt keinen zweiten Ivan" stuetzt sich auf BEIDES.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.leads cascade")
    yield


def _lead(name, phone=None):
    return server._q(
        "insert into leads (name, phone, source) "
        "values (%s, nullif(%s,''), 'test') returning id",
        (name, phone or ""))[0]["id"]


def _suche(text, **kw):
    return json.loads(server.kontakt_aehnlich(text, **kw))


def test_findet_die_schreibvariante_die_ilike_verfehlt():
    """Der gemessene Fall: zwei Schreibweisen derselben Firma."""
    _lead("Webdesigner Muenchen", "+498921536269")
    _lead("Webdesign Muenchen", "+4989244126731")
    namen = [k["name"] for k in _suche("Webdesign Muenchen")["kontakte"]]
    assert "Webdesigner Muenchen" in namen and "Webdesign Muenchen" in namen


def test_findet_auch_bei_anderer_gross_und_kleinschreibung():
    _lead("DATENSCHUTZ UND INFORMATIONSSICHERHEIT")
    treffer = _suche("Datenschutz und Informationssicherheit")["kontakte"]
    assert treffer and treffer[0]["naehe"] > 0.9


def test_gibt_die_naehe_mit_aus_und_entscheidet_nicht_selbst():
    """Ein Trigramm-Fund ist ein Hinweis, kein Befund."""
    _lead("Ark Software GmbH")
    antwort = _suche("SMC Software GmbH", schwelle=0.4)
    assert antwort["kontakte"], "der Fall soll gefunden, nicht verschwiegen werden"
    assert all("naehe" in k for k in antwort["kontakte"])
    assert "KEIN Beweis" in antwort["hinweis"]


def test_kein_treffer_ist_eine_belastbare_aussage():
    """Darauf stuetzt sich „es gibt keinen zweiten Ivan"."""
    _lead("Ivan", "+4917688014635")
    assert len(_suche("Ivan")["kontakte"]) == 1
    assert _suche("Gustav von Zitzewitz")["kontakte"] == []


def test_zusaetze_zum_namen_werden_gefunden():
    """Gemessen 17.09.2026: similarity('Ivan','Ivan G.') = 0.714."""
    _lead("Ivan", "+4917688014635")
    _lead("Ivan G.", "+4915112345678")
    assert len(_suche("Ivan", schwelle=0.3)["kontakte"]) == 2


def test_ein_vertauschter_buchstabe_wird_NICHT_gefunden():
    """Die Grenze des Werkzeugs, gemessen und festgehalten statt behauptet.

    `similarity('Ivan','Iwan')` = 0.250, `'Iwan G.'` = 0.200 — beide liegen
    UNTER der Schwelle. Bei kurzen Namen teilen sich zwei Schreibweisen zu
    wenige Trigramme. Wer aus einem leeren Ergebnis schliesst „es gibt keine
    Variante", schliesst deshalb zu weit: fuer kurze Namen braucht es
    zusaetzlich ein Muster (`name ~* '(iwan|ivan)'`).

    Dieser Test steht hier, weil genau dieser Fehlschluss am 17.09.2026 in
    einem Entwurfsdokument stand, bevor er nachgemessen wurde.
    """
    _lead("Ivan", "+4917688014635")
    _lead("Iwan", "+4915112345678")
    treffer = _suche("Ivan", schwelle=0.3)["kontakte"]
    assert [k["name"] for k in treffer] == ["Ivan"]


def test_schwelle_null_wird_angehoben_statt_den_bestand_auszukippen():
    for n in ("Klara Weindorf", "Raik", "Steffen Wehringen", "Tom"):
        _lead(n)
    antwort = _suche("Ivan", schwelle=0)
    assert antwort["schwelle"] == 0.2
    assert antwort["kontakte"] == []


def test_leerer_suchtext_wird_abgewiesen():
    assert "fehler" in _suche("   ")


def test_unsinnige_schwelle_wird_abgewiesen_statt_zu_stuerzen():
    assert "fehler" in _suche("Ivan", schwelle="viel")


def test_archivierte_werden_gefunden_und_gekennzeichnet():
    """Dieselbe Ueberlegung wie bei kontakt_suchen: archiviert heisst
    unsichtbar in den Listen, nicht unauffindbar — sonst legte der naechste
    Griff einen zweiten Kontakt zur selben Person an (Demo-Befund B1)."""
    lid = _lead("Lisa Probekunde")
    # Gestalt wie `_archiviert` sie liest: unter dem Schluessel liegt ein
    # OBJEKT, nicht ein Wahrheitswert.
    server._q("update leads set enrichment = "
              "'{\"archiviert\": {\"archiviert\": true}}'::jsonb "
              "where id = %s returning id", (lid,))
    treffer = _suche("Lisa Probekunde")["kontakte"]
    assert len(treffer) == 1 and treffer[0]["archiviert"] is True
