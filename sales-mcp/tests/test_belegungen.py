"""Die gemeinsame Belegung ueber alle Quellen — Spec §2.2.

Der Betreiber hat das am 12.09.2026 ausdruecklich verlangt: "dass Ivans und
meiner dann beruecksichtigt wird". Geprueft wird gegen JEDE aktive Quelle.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402
import kalenderquellen  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


@pytest.fixture(autouse=True)
def kein_eigener_kalender(monkeypatch):
    """Ohne CALDAV_* liefert termine_lesen leer — der Ausgangszustand im
    CI-Container. Tests, die den eigenen Kalender brauchen, biegen um."""
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], None))
    yield


def _t(tag, stunde):
    return datetime(2026, 10, tag, stunde, tzinfo=timezone.utc)


def test_fremde_quelle_erscheint_mit_namen(monkeypatch):
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "Kundentermin",
         "ort": "", "uid": "x"}], None))
    eintraege, luecken = server.belegungen()
    assert luecken == []
    assert len(eintraege) == 1
    assert eintraege[0]["quelle"] == "Ivan"
    assert eintraege[0]["titel"] == "Kundentermin"


def test_eigener_und_fremder_kalender_zusammen(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([
        {"beginn": _t(1, 14), "ende": _t(1, 15), "titel": "Eigener",
         "ort": "", "uid": "e"}], None))
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "Ivans",
         "ort": "", "uid": "i"}], None))
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Ivans", "Eigener"]
    assert {e["quelle"] for e in eintraege} == {"Ivan", "Betreiber"}


def test_unerreichbare_quelle_wird_als_luecke_gemeldet(monkeypatch):
    """Sie darf NICHT stillschweigend als 'frei' gelten — sonst schlaegt der
    Bot ausgerechnet dann Termine vor, wenn er am wenigsten weiss."""
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda url, *a, **k: ([], "Nicht erreichbar (TimeoutError)."))
    eintraege, luecken = server.belegungen()
    assert eintraege == []
    assert len(luecken) == 1
    assert luecken[0]["quelle"] == "Ivan"
    assert "erreichbar" in luecken[0]["grund"]


def test_der_stand_wird_festgehalten(monkeypatch):
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "A", "ort": "",
         "uid": "x"}], None))
    server.belegungen()
    q = [z for z in server.kalenderquellen_lesen() if z["id"] == qid][0]
    assert q["termine_zuletzt"] == 1
    assert q["letzter_fehler"] is None


def test_fehlerfall_wird_in_der_datenbank_festgehalten(monkeypatch):
    """Ergaenzung Fix-Runde 1 (Pruefung 13.09.2026): der Fehlerfall wurde
    bisher nur ueber den Rueckgabewert von belegungen() geprueft, nie gegen
    die Tabelle selbst — dort liest die Verbindungsseite den Stand aber
    tatsaechlich ab ("zuletzt gelesen um ...", Fehlertext). Steht dort
    nichts oder das Falsche, sucht der Kollege an der falschen Stelle.

    Ablauf als Abfolge, erst erfolgreich, dann fehlschlagend: nur so zeigt
    sich im Zusammenspiel mit belegungen(), dass ein einzelner Ausfall die
    letzte bekannte Zahl nicht wegwischt (Aufgabe 1 hat das nur isoliert an
    kalenderquelle_stand_setzen geprueft, nie ueber belegungen())."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url, *a, **k: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "A", "ort": "",
         "uid": "x"}], None))
    server.belegungen()
    q = [z for z in server.kalenderquellen_lesen() if z["id"] == qid][0]
    assert q["termine_zuletzt"] == 1
    alter_zeitpunkt = q["zuletzt_gelesen"]
    assert alter_zeitpunkt is not None

    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda url, *a, **k: ([], "Nicht erreichbar (TimeoutError)."))
    server.belegungen()
    q = [z for z in server.kalenderquellen_lesen() if z["id"] == qid][0]
    assert q["letzter_fehler"] == "Nicht erreichbar (TimeoutError)."
    assert q["zuletzt_gelesen"] is not None
    assert q["zuletzt_gelesen"] > alter_zeitpunkt
    # Der wertvollste Teil: der alte Zaehler bleibt stehen, ein einzelner
    # Ausfall wischt die letzte bekannte Zahl nicht weg.
    assert q["termine_zuletzt"] == 1


def test_inaktive_quelle_wird_nicht_abgerufen(monkeypatch):
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    with server.pool.connection() as conn:
        conn.execute("update sales_test.kalender_quellen set aktiv = false")
    gerufen = []
    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda url, *a, **k: gerufen.append(url) or ([], None))
    eintraege, luecken = server.belegungen()
    assert gerufen == []
    assert eintraege == [] and luecken == []


def test_eigener_kalenderfehler_ist_auch_eine_luecke(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen",
                        lambda *a, **k: ([], "Kalender nicht erreichbar."))
    eintraege, luecken = server.belegungen()
    assert [l["quelle"] for l in luecken] == ["Betreiber"]


@pytest.fixture
def ohne_kalender_quellen():
    """Simuliert eine Installation, auf der db/provision.sql noch nicht
    gegen die Datenbank gefahren wurde (K3, Schlusspruefung 13.09.2026):
    `kalender_quellen` fehlt. Umbenennen statt DROP + CREATE — so bleibt
    die exakte Spalten-/Constraint-Definition unangetastet und die Zeile
    kommt beim Zurueckbenennen unveraendert wieder."""
    with server.pool.connection() as conn:
        conn.execute("alter table sales_test.kalender_quellen "
                     "rename to kalender_quellen_versteckt")
    try:
        yield
    finally:
        with server.pool.connection() as conn:
            conn.execute("alter table sales_test.kalender_quellen_versteckt "
                         "rename to kalender_quellen")


def test_fehlende_quellentabelle_kostet_nur_die_fremdtermine(
        monkeypatch, ohne_kalender_quellen):
    """K3: ohne `kalender_quellen` darf hoechstens die Fremdsicht ausfallen
    — der eigene Kalender bleibt da, gemeldet als EINE Luecke statt eines
    harten Fehlers."""
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([
        {"beginn": _t(1, 14), "ende": _t(1, 15), "titel": "Eigener",
         "ort": "", "uid": "e"}], None))
    eintraege, luecken = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Eigener"]
    assert len(luecken) == 1
    assert luecken[0]["quelle"] == server.FREMDE_QUELLEN_LUECKE


def test_fehlende_quellentabelle_reisst_termin_konflikte_nicht_ab(
        monkeypatch, ohne_kalender_quellen):
    """Der eigentliche Schaden aus dem Pruefbericht: `@_gesichert` faengt
    einen unbehandelten psycopg.Error der AUFRUFENDEN Funktion ab — ohne
    den Fang in belegungen() waere termin_konflikte() (und ebenso
    termin_bestaetigen/termin_einladen) insgesamt tot statt nur die
    Kollisionspruefung gegen Kollegen-Kalender."""
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], None))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00"))
    assert "fehler" not in antwort, antwort
    assert antwort["frei"] is False
    assert [l["quelle"] for l in antwort["quellen_luecken"]] == [
        server.FREMDE_QUELLEN_LUECKE]
