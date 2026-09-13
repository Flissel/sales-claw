"""Kollisionspruefung ueber alle Quellen — Spec §2.2, Pruefung 3a/3b."""
import json
import os
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import kalender  # noqa: E402

# ECHTE Ortszeit (Europe/Berlin), nicht UTC — dieselbe Zone, mit der
# `kalender._ics_zeit` fremde Kalendereintraege ueberhaupt erst nach UTC
# umrechnet. Fix-Runde 1 zu Aufgabe 4 (13.09.2026, Befund des
# Koordinators): die ursprüngliche Fassung dieser Datei baute Eintraege
# direkt in UTC und liess `_termin_zeitpunkt`s naive "09:00" ebenfalls als
# UTC durchgehen — das ging nur zufaellig auf, weil beide Seiten denselben
# (falschen) Fehler machten.
#
# Oktober bleibt der Monat (nicht Juli): `_termin_zeitpunkt` lehnt ein
# Datum in der Vergangenheit ab, und ein Juli-Termin 2026 liegt hinter dem
# heutigen 13.09.2026 (gemessen: "liegt in der Vergangenheit"-Fehler beim
# ersten Versuch mit Juli). Der 1. Oktober bleibt trotzdem ein
# SOMMERZEIT-Datum: die DST-Umstellung 2026 faellt auf den letzten
# Sonntag im Oktober (25.10.), Europe/Berlin steht am 1.10. also noch auf
# CEST = UTC+2 — der volle Zwei-Stunden-Versatz, den der Koordinator
# gemessen hat, nicht nur eine Stunde.
ORTSZONE = kalender.ortszone() or timezone.utc
MONAT = 10


def _belegt(*eintraege, luecken=()):
    return lambda tage_voraus=60: (list(eintraege), list(luecken))


def _e(tag, von, bis, quelle, titel="Belegt"):
    """Ein Fremdtermin in Berliner ORTSZEIT — so, wie ein Mensch ihn
    meint ("Ivan ist von 9 bis 10 Uhr belegt"), nicht als UTC-Zahl, die
    nur zufaellig mit einer Ortszeit-Eingabe zusammenpasst."""
    return {"beginn": datetime(2026, MONAT, tag, von, tzinfo=ORTSZONE),
            "ende": datetime(2026, MONAT, tag, bis, tzinfo=ORTSZONE),
            "titel": titel, "ort": "", "quelle": quelle}


def _beginn(tag, stunde):
    """Fuer den DIREKTEN Aufruf von `_kollisionen`: bereits aware, in
    Ortszeit — `_kollisionen` fasst eine aware Zeit unveraendert an, nur
    eine NAIVE Zeit wird lokalisiert (siehe `_beginn_naiv`)."""
    return datetime(2026, MONAT, tag, stunde, tzinfo=ORTSZONE)


def _beginn_naiv(tag, stunde):
    """So, wie `_termin_zeitpunkt` einen Zeitpunkt tatsaechlich liefert:
    NAIV, in Ortszeit gemeint, ohne tzinfo. Nur damit laesst sich die
    Lokalisierung in `_kollisionen` selbst pruefen, nicht nur ihr
    Ergebnis ueber ein Werkzeug."""
    return datetime(2026, MONAT, tag, stunde)


def test_ueberlappung_beim_kollegen_wird_gefunden(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Ivans Kundentermin")))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert len(treffer) == 1
    assert treffer[0]["quelle"] == "Ivan"
    assert treffer[0]["titel"] == "Ivans Kundentermin"


def test_ueberlappung_beim_betreiber_wird_gefunden(monkeypatch):
    """Gegenprobe zur vorigen: beide Richtungen, wie Pruefung 3a verlangt."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Betreiber", "Eigener")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert [t["quelle"] for t in treffer] == ["Betreiber"]


def test_anschliessender_termin_ist_keine_kollision(monkeypatch):
    """Ende gleich Beginn heisst nacheinander, nicht gleichzeitig — sonst
    waere jeder Tag mit Terminkette blockiert."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 10), 30)
    assert treffer == []


def test_termin_davor_ist_keine_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 14, 15, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 60)
    assert treffer == []


def test_punktueller_termin_ohne_dauer_kollidiert_nicht(monkeypatch):
    """Fehlt DTEND, ist ende == beginn. Ein solcher Eintrag darf nicht den
    ganzen Tag blockieren."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 9, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []


def test_luecken_werden_durchgereicht(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []
    assert luecken[0]["quelle"] == "Ivan"


def test_lokalisierung_verhindert_den_zwei_stunden_sommerzeit_versatz(
        monkeypatch):
    """Faengt genau den vom Koordinator gemessenen Fehler fest: Ivan ist
    von 9 bis 10 Uhr BERLINER Zeit belegt (1. Oktober, vor der DST-
    Umstellung am 25.10. also noch CEST = UTC+2, damit 7-8 Uhr UTC). Die
    Anfrage kommt — wie bei einem echten Aufruf ueber
    termin_konflikte — als NAIVE 09:00 herein (`_beginn_naiv`), gemeint als
    dieselbe Ortszeit.

    Mit korrekter Lokalisierung (`kalender.ortszone()`) liegt die Anfrage
    ebenfalls bei 7:00-7:30 UTC und ueberschneidet sich mit Ivans Termin:
    ERKANNT.

    Mit der vorherigen Notloesung (`beginn.replace(tzinfo=timezone.utc)`,
    keine echte Umrechnung) haette dieselbe naive "09:00" bei 09:00-09:30
    UTC gelegen — zwei Stunden zu spaet, keine Ueberschneidung mit Ivans
    7-8-Uhr-UTC-Termin: die Kollision waere VERPASST worden. Genau das
    waere schlimmer als gar keine Pruefung: falsche Sicherheit statt
    keiner Aussage. Wegnahme-Beleg dazu im Bericht zu Aufgabe 4,
    Fix-Runde 1."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    treffer, _ = server._kollisionen(_beginn_naiv(1, 9), 30)
    assert len(treffer) == 1
    assert treffer[0]["quelle"] == "Ivan"


def test_werkzeug_meldet_frei(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt())
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is True
    assert antwort["kollisionen"] == []


def test_werkzeug_meldet_belegt_mit_namen(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:30", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_werkzeug_ist_bei_luecken_nicht_einfach_frei(monkeypatch):
    """Der wichtigste Fall: nichts gefunden, aber auch nichts gewusst."""
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_ungueltiges_datum_wird_abgewiesen():
    antwort = json.loads(server.termin_konflikte("morgen", "09:00"))
    assert "fehler" in antwort


def _lead():
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values ('Ivan K', 'k@example.test', '+491701234567', 'whatsapp', "
        "'existing_customer') returning id")[0]["id"])


def test_einladung_nennt_die_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    antwort = json.loads(server.termin_einladen(
        _lead(), "2026-10-01", "09:30", thema="Test"))
    assert "fehler" not in antwort, antwort
    assert antwort["kollisionen"], antwort
    assert "Ivan" in antwort["hinweis"]


def test_kollision_blockiert_die_einladung_NICHT(monkeypatch):
    """KEIN RED-Beleg: dieser Test war schon VOR jeder Aufgabe-4-Aenderung
    gruen, weil termin_einladen den Entwurf schon vorher unabhaengig von
    jeder Kollisionspruefung anlegte (gemeldet im Bericht zu Aufgabe 4).
    Er bleibt trotzdem sinnvoll als REGRESSIONSSCHUTZ fuer die bewusste
    Plan-Entscheidung, dass eine Kollision meldet, aber nicht blockiert:
    faellt er kuenftig um, hat jemand ein hartes Nein eingebaut, das dem
    Betreiber genau die Entscheidung abnaehme, die ihm gehoert."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 10, "Ivan")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    lead = _lead()
    json.loads(server.termin_einladen(lead, "2026-10-01", "09:30", thema="T"))
    assert len(server._q(
        "select id from drafts where lead_id = %s", (lead,))) == 1
