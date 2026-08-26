"""Vertragstests fuer den Auftrags-Spool (Update per Bot-Anfrage).

Betreiber am 27.08.2026: "update ueber mich bzw bot anfragen" — der Bot darf
ein Update ANFORDERN, nie ausfuehren. Das Werkzeug schreibt eine
Auftragsdatei in einen Spool; ein Waechter auf dem WIRT (systemd-path-Unit,
deploy/auftrag-ausfuehren.sh) prueft und fuehrt aus. Der Bot fasst nie
selbst git oder docker an.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Ein Auftrag ist eine Datei, kein Befehl. Das Werkzeug hat keinerlei
   Ausfuehrungsmacht — was es schreiben kann, bestimmt allein der Waechter
   auf dem Wirt (und der kennt nur bekannte Typen).
2. Hoechstens ein Auftrag zur Zeit, hoechstens einer alle zehn Minuten.
   Ein Chat-Missverstaendnis darf keine Update-Schleife treten.
3. Ergebnisse werden ehrlich berichtet: kein Ergebnis heisst "keins da",
   kaputtes JSON heisst "kaputt" — niemals Traceback, niemals Erfindung.
"""
import json
import os
import time

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("AUFTRAG_SPOOL", str(tmp_path))
    return tmp_path


def _auftraege(spool):
    return sorted(spool.glob("auftrag-*.json"))


# ---------------------------------------------------------------------------
# Anfordern — eine Datei, ein Vertrag
# ---------------------------------------------------------------------------

def test_der_auftrag_wird_als_datei_mit_vertrag_geschrieben(spool):
    antwort = json.loads(server.update_anfordern())
    assert "fehler" not in antwort
    dateien = _auftraege(spool)
    assert len(dateien) == 1
    inhalt = json.loads(dateien[0].read_text(encoding="utf-8"))
    assert inhalt["typ"] == "update"
    assert inhalt["zeitpunkt"]
    assert antwort["auftrag"] == dateien[0].name


def test_ein_wartender_auftrag_blockiert_den_naechsten(spool):
    server.update_anfordern()
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "wartet bereits" in antwort["fehler"]
    assert len(_auftraege(spool)) == 1


def test_kurz_nach_einem_ergebnis_wird_nicht_erneut_bestellt(spool):
    (spool / "ergebnis-20260827-010000.json").write_text(
        json.dumps({"typ": "update", "ergebnis": "eingespielt"}),
        encoding="utf-8")
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "Minuten" in antwort["fehler"]
    assert _auftraege(spool) == []


def test_nach_ablauf_der_sperre_geht_es_wieder(spool):
    alt = spool / "ergebnis-20260827-010000.json"
    alt.write_text(json.dumps({"typ": "update", "ergebnis": "eingespielt"}),
                   encoding="utf-8")
    vor_elf_minuten = time.time() - 660
    os.utime(alt, (vor_elf_minuten, vor_elf_minuten))
    antwort = json.loads(server.update_anfordern())
    assert "fehler" not in antwort
    assert len(_auftraege(spool)) == 1


def test_fehlender_spool_ist_eine_meldung_kein_absturz(monkeypatch):
    monkeypatch.setenv("AUFTRAG_SPOOL", "/gibt/es/nicht")
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "Spool" in antwort["fehler"]


# ---------------------------------------------------------------------------
# Ergebnis lesen — ehrlich oder gar nicht
# ---------------------------------------------------------------------------

def test_ohne_ergebnis_sagt_es_das(spool):
    antwort = json.loads(server.update_ergebnis())
    assert antwort["ergebnis"] is None
    assert antwort["auftrag_wartet"] is False


def test_das_juengste_ergebnis_gewinnt(spool):
    (spool / "ergebnis-20260827-010000.json").write_text(
        json.dumps({"ergebnis": "rollback"}), encoding="utf-8")
    (spool / "ergebnis-20260827-020000.json").write_text(
        json.dumps({"ergebnis": "eingespielt"}), encoding="utf-8")
    antwort = json.loads(server.update_ergebnis())
    assert antwort["ergebnis"]["ergebnis"] == "eingespielt"


def test_ein_wartender_auftrag_wird_mitgemeldet(spool):
    server.update_anfordern()
    antwort = json.loads(server.update_ergebnis())
    assert antwort["auftrag_wartet"] is True


def test_kaputtes_ergebnis_json_stuerzt_nicht_ab(spool):
    (spool / "ergebnis-20260827-030000.json").write_text(
        "{kein json", encoding="utf-8")
    antwort = json.loads(server.update_ergebnis())
    assert "fehler" in antwort
    assert "lesbar" in antwort["fehler"]
