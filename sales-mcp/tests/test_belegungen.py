"""Die gemeinsame Belegung ueber alle Quellen — Spec §2.2.

Der Betreiber hat das am 12.09.2026 ausdruecklich verlangt: "dass Ivans und
meiner dann beruecksichtigt wird". Geprueft wird gegen JEDE aktive Quelle.

Seit Spec 2026-11-08 liest belegungen() den Abgleich (kalender_termine) statt
die Adressen live, und der Agent sieht, was der Laden-Besitzer sieht: fremdes
Business voll, fremdes Privat als „Privattermin".
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402
import kalender_sichtbarkeit  # noqa: E402
import kalenderquellen  # noqa: E402
import post_struktur  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


@pytest.fixture(autouse=True)
def kein_eigener_kalender(monkeypatch):
    """Ohne CALDAV_* liefert termine_lesen leer — der Ausgangszustand im
    CI-Container. Tests, die den eigenen Kalender brauchen, biegen um."""
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], None))
    yield


@pytest.fixture(autouse=True)
def kein_live_abruf(monkeypatch):
    """belegungen() liest nur noch den Abgleich - jede Adresse bleibt unberuehrt."""
    def _verboten(*a, **k):
        raise AssertionError("belegungen() darf keine Adresse live abrufen")
    monkeypatch.setattr(kalenderquellen, "hole", _verboten)
    yield


def _t(tag, stunde):
    """Kuenftig, im 60-Tage-Fenster von belegungen()."""
    morgen = datetime.now(timezone.utc).date() + timedelta(days=tag)
    return datetime(morgen.year, morgen.month, morgen.day, stunde, tzinfo=timezone.utc)


def _termin(tag, stunde, titel, uid, **extra):
    return {"beginn": _t(tag, stunde), "ende": _t(tag, stunde + 1), "titel": titel,
            "ort": "", "uid": uid, **extra}


def _quelle(name, besitzer, bereich, termine, fehler=None):
    """Eine verbundene Quelle so, wie sie der Abgleich hinterlaesst."""
    qid = server.kalenderquelle_speichern(name, "https://example.test/a.ics",
                                          besitzer, bereich)
    server.kalendertermine_ersetzen(qid, termine, kalender_sichtbarkeit.details_speichern(
        besitzer, bereich, post_struktur.container_besitzer()))
    server.kalenderquelle_stand_setzen(qid, len(termine), fehler)
    return qid


def test_fremde_quelle_erscheint_mit_namen():
    _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Kundentermin", "x")])
    eintraege, luecken = server.belegungen()
    assert luecken == []
    assert len(eintraege) == 1
    assert eintraege[0]["quelle"] == "Ivan"
    # Fremdes Business ist voll sichtbar (Spec 2026-11-08 §2.2) - ersetzt
    # die Regel vom 28.10.2026 („nur belegt").
    assert eintraege[0]["titel"] == "Kundentermin"
    assert eintraege[0]["maskiert"] is False


def test_agent_sieht_privattermin_als_belegt():
    _quelle("Ivan privat", "ivan", "privat",
            [_termin(1, 9, "Zahnarzt", "p", ort="Praxis")])
    eintraege, luecken = server.belegungen()
    assert luecken == []
    assert [e["titel"] for e in eintraege] == ["Privattermin"]
    assert eintraege[0]["ort"] == ""
    assert eintraege[0]["maskiert"] is True


def test_agent_sieht_eigene_privattermine_des_laden_besitzers_voll():
    _quelle("Felix privat", "felix", "privat", [_termin(1, 9, "Zahnarzt", "p")])
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Zahnarzt"]


def test_ohne_laden_besitzer_ist_jeder_privattermin_maskiert(monkeypatch):
    _quelle("Felix privat", "felix", "privat", [_termin(1, 9, "Zahnarzt", "p")])
    monkeypatch.setenv("POST_BESITZER", "")
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Privattermin"]


def test_freier_termin_kollidiert_nicht():
    _quelle("Ivan", "ivan", "business", [
        _termin(1, 9, "Geburtstag Oma", "g", frei=True),
        _termin(1, 11, "Kunde", "k")])
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Kunde"]
    treffer, luecken = server._kollisionen(_t(1, 9), 30)
    assert treffer == [] and luecken == []
    treffer, _ = server._kollisionen(_t(1, 11), 30)
    assert [t["titel"] for t in treffer] == ["Kunde"]


def test_ganztaegig_wird_mitgegeben():
    _quelle("Ivan", "ivan", "business", [_termin(1, 0, "Messe", "m", ganztaegig=True)])
    eintraege, _ = server.belegungen()
    assert eintraege[0]["ganztaegig"] is True


def test_team_schalter_wirkt_nicht_mehr_auf_den_agenten():
    """Spec 2026-11-08 §2.5: der ladenweite Schalter „Team-Ebenen" entfaellt;
    abgeschaltet wird je Quelle (aktiv)."""
    _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Kunde", "k")])
    server.team_kalender_aus_setzen(["Ivan"], "test")
    try:
        eintraege, _ = server.belegungen()
        assert [e["quelle"] for e in eintraege] == ["Ivan"]
    finally:
        server.team_kalender_aus_setzen([], "test")


def test_eigener_und_fremder_kalender_zusammen(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([
        {"beginn": _t(1, 14), "ende": _t(1, 15), "titel": "Eigener",
         "ort": "", "uid": "e"}], None))
    _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Ivans", "i")])
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Ivans", "Eigener"]
    assert {e["quelle"] for e in eintraege} == {"Ivan", "Betreiber"}


def test_unerreichbare_quelle_wird_als_luecke_gemeldet():
    """Sie darf NICHT stillschweigend als 'frei' gelten — sonst schlaegt der
    Bot ausgerechnet dann Termine vor, wenn er am wenigsten weiss."""
    _quelle("Ivan", "ivan", "business", [], fehler="Nicht erreichbar (TimeoutError).")
    eintraege, luecken = server.belegungen()
    assert eintraege == []
    assert len(luecken) == 1
    assert luecken[0]["quelle"] == "Ivan"
    assert "erreichbar" in luecken[0]["grund"]


def test_veraltete_quelle_ist_luecke():
    qid = _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Alt", "a")])
    server._q("update kalender_quellen set zuletzt_gelesen = now() - interval '16 minutes' "
              "where id = %s", (qid,))
    eintraege, luecken = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Alt"]
    assert luecken == [{"quelle": "Ivan",
                        "grund": "seit über 15 Minuten nicht abgeglichen"}]


def test_nie_abgeglichene_quelle_ist_luecke():
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics", "ivan", "business")
    _, luecken = server.belegungen()
    assert luecken == [{"quelle": "Ivan", "grund": "noch nicht abgeglichen"}]


def test_inaktive_quelle_wird_nicht_abgerufen():
    _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Kunde", "k")])
    with server.pool.connection() as conn:
        conn.execute("update sales_test.kalender_quellen set aktiv = false")
    eintraege, luecken = server.belegungen()
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


def test_teilweise_verstandene_quelle_behaelt_ihre_gueltigen_termine():
    """K4 (Schlusspruefung 13.09.2026): eine Quelle, die NUR TEILWEISE
    verstanden wurde, meldet `letzter_fehler` - ihre gueltigen Termine
    bleiben trotzdem echte Kollisionsdaten, die Luecke steht daneben."""
    _quelle("Ivan", "ivan", "business", [_termin(1, 9, "Normaler Termin", "n")],
            fehler="1 Termin nicht lesbar — dort kann etwas liegen, das hier fehlt.")
    eintraege, luecken = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Normaler Termin"]
    assert len(luecken) == 1
    assert luecken[0]["quelle"] == "Ivan"
    assert "nicht lesbar" in luecken[0]["grund"]


def test_luecke_laesst_termin_konflikte_nie_frei_melden():
    """Das K4-Ruling direkt am Werkzeug: eine Quelle mit Luecke darf
    `termin_konflikte` nie `frei: true` liefern lassen, auch ohne dass
    irgendetwas kollidiert."""
    _quelle("Ivan", "ivan", "business", [],
            fehler="1 Termin nicht lesbar — dort kann etwas liegen, das hier fehlt.")
    antwort = json.loads(server.termin_konflikte(_t(2, 9).date().isoformat(), "09:00"))
    assert antwort["frei"] is False
    assert [l["quelle"] for l in antwort["quellen_luecken"]] == ["Ivan"]
