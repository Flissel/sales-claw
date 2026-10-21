"""Gemeinsamer Zwischenspeicher der Pult-Abschnitte auf /freigaben (Marketing und
Bewerbungen, Fix-Runde 1 zu Task 5 des Plans 2026-10-20 Hermes H1)."""
import threading

import pult_cache


def test_merken_frisch_fehler_und_leeren(monkeypatch):
    jetzt = [1000.0]
    monkeypatch.setattr(pult_cache.time, "monotonic", lambda: jetzt[0])
    c = pult_cache.PultCache("probe")
    assert c.frisch_fehler() is None                      # leer: kein Fehler gemerkt
    c.merken(3)
    assert c.frisch_fehler() is None                      # gelungen
    c.merken(0, "nicht_verbunden")
    assert c.frisch_fehler() == "nicht_verbunden"         # die Art bleibt erhalten
    jetzt[0] += pult_cache.ALTER_S - 1
    assert c.frisch_fehler() == "nicht_verbunden"
    jetzt[0] += 1
    assert c.frisch_fehler() is None                      # nach ALTER_S: neuer Versuch
    c.merken(0, "nicht_erreichbar")
    c.leeren()
    assert c.frisch_fehler() is None


def test_anzahl_liest_nur_den_speicher_und_startet_hoechstens_einen_thread():
    c = pult_cache.PultCache("probe-zaehler")
    los = threading.Event()
    aufrufe = []

    def laden():
        aufrufe.append(1)
        los.wait(5)
        c.merken(7)

    assert c.anzahl(laden) == 0                           # kalt: alter Wert, Abruf im Hintergrund
    t = c.laeuft["thread"]
    assert t.name == "probe-zaehler" and t.daemon
    assert c.anzahl(laden) == 0 and c.laeuft["thread"] is t   # laeuft noch: kein zweiter Thread
    los.set()
    t.join(5)
    assert aufrufe == [1]
    assert c.anzahl(laden) == 7 and c.laeuft["thread"] is t   # frisch: kein neuer Abruf
