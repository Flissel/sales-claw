"""Vorbereitete Video-Uebergaben (video_uebergabe.py) gegen die echte Tabelle `sales_test.video_uebergabe`.

NUR IN DER CI lauffaehig (Postgres mit db/video-uebergabe.sql fuer sales_test). Das Schema `auftrag` gibt es in
keiner Test-DB: `auftrag_buch.anlegen` wird durch einen Ersatz ersetzt, der die Bestellung aufzeichnet oder wie
das Auftragsbuch ablehnt. Der Ersatz schreibt nichts in ein echtes Auftragsbuch.
"""
import json
import logging
import os
import threading
import time

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import auftrag_buch  # noqa: E402
import server  # noqa: E402
import video_konzept  # noqa: E402
import video_uebergabe as vu  # noqa: E402

AID = "0123abcd-0000-4000-8000-000000000001"
TAGESGRENZE = "Heute sind schon zwei Videos bestellt – morgen wieder."
SERIE = "KI im Vertrieb <b>fett</b>"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.video_uebergabe")
    yield


class Bestellungen:
    """Ersatz fuer auftrag_buch.anlegen: zeichnet auf, wartet optional, lehnt optional ab oder scheitert."""

    def __init__(self):
        self.aufrufe = []            # (laden, mandant, art, eingabe)
        self.ablehnung = None        # AuftragAbgelehnt-Satz
        self.ausfall = None          # Ausnahme, wie bei einem DB-Fehler
        self.dauer = 0.0
        self.drin = threading.Event()   # gesetzt, sobald ein Aufruf im Auftragsbuch steckt (haelt dann die Zeilensperre)

    def __call__(self, q, laden, mandant, art, eingabe):
        self.drin.set()
        time.sleep(self.dauer)
        if self.ablehnung:
            raise auftrag_buch.AuftragAbgelehnt(self.ablehnung)
        if self.ausfall:
            raise self.ausfall
        self.aufrufe.append((laden, mandant, art, eingabe))
        return AID


@pytest.fixture
def buch(monkeypatch):
    b = Bestellungen()
    monkeypatch.setattr(auftrag_buch, "anlegen", b)
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    return b


def konzept(**ueber):
    k = {
        "thema": "KI im Vertrieb", "zielgruppe": "Entscheider 34+", "minuten": 4,
        "hook": "Was kostet ein verlorener Lead?", "kernaussage": "Wer früh antwortet, gewinnt.",
        "stufen": [
            {"name": "Problem", "szenen": [{"kurz": f"Szene {i}", "bildart": "slide"} for i in range(4)]},
            {"name": "Lösung", "szenen": [{"kurz": f"Szene {i}", "bildart": "clip", "notiz": "n"}
                                         for i in range(4, 8)]},
        ],
        "abschluss": "Jetzt anfragen.", "auftrag": None, "firma": "fin2gether",
        "pfad": "knowledge/Konzepte/ki.html", "name": "ki",
    }
    k.update(ueber)
    return k


def vorbereiten(**ueber):
    k = konzept(**ueber)
    return vu.anlegen(k, video_konzept.block_hash(k))


def eine_id():
    return str(server._q("select id from video_uebergabe order by erstellt_am limit 1")[0]["id"])


def zeile(kennung=None):
    sql = "select * from video_uebergabe " + ("where id = %s" if kennung else "")
    return server._q(sql, (kennung,) if kennung else ())[0]


def altern(stunden, kennung=None):
    server._q("update video_uebergabe set erstellt_am = now() - make_interval(hours => %s) "
              + ("where id = %s " if kennung else "") + "returning id", (stunden, kennung) if kennung else (stunden,))


# --- Anlegen --------------------------------------------------------------------------------------------

def test_anlegen_legt_genau_eine_offene_uebergabe_an(buch):
    vorgang, satz = vorbereiten()
    assert satz is None and len(vorgang) == 8 and set(vorgang) <= set("0123456789abcdef")
    z = zeile()
    assert str(z["id"]).startswith(vorgang) and z["status"] == "offen"
    assert z["konzept"] == konzept() and z["konzept_sha"] == video_konzept.block_hash(konzept())
    assert z["auftrag_id"] is None and z["entschieden_am"] is None
    assert buch.aufrufe == []                                    # keine Bestellung


def test_gleicher_hash_solange_offen_409(buch):
    assert vorbereiten()[1] is None
    assert vorbereiten() == ("", vu.SATZ_DOPPELT)
    assert vorbereiten(name="anders", pfad="knowledge/Konzepte/anders.html", auftrag="abcd1234")[1] == vu.SATZ_DOPPELT
    assert server._q("select count(*) as n from video_uebergabe")[0]["n"] == 1


def test_nach_nein_ja_und_verfall_wieder_moeglich(buch):
    assert vorbereiten()[1] is None
    assert vu.verwerfen(eine_id(), "mira") is True
    assert vorbereiten()[1] is None                              # nach Nein
    kennung = [str(r["id"]) for r in server._q("select id from video_uebergabe where status = 'offen'")][0]
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"
    assert vorbereiten()[1] is None                              # nach Ja
    altern(25)
    assert vorbereiten()[1] is None                              # nach Verfall
    assert {r["status"] for r in server._q("select status from video_uebergabe")} == {
        "verworfen", "bestaetigt", "abgelaufen", "offen"}


def test_sechste_offene_uebergabe_429(buch):
    for i in range(5):
        assert vorbereiten(hook=f"Hook {i}")[1] is None
    assert vorbereiten(hook="Hook 6") == ("", vu.SATZ_VOLL)
    assert vu.verwerfen(eine_id(), "mira")
    assert vorbereiten(hook="Hook 7")[1] is None                 # Platz ist wieder frei
    assert vu.SATZ_VOLL == "Es sind schon 5 Übergaben offen. Bitte erst in Sales entscheiden."


def test_abgelaufene_zaehlen_nicht_zur_grenze(buch):
    for i in range(5):
        vorbereiten(hook=f"Hook {i}")
    altern(25)
    assert vorbereiten(hook="Hook neu")[1] is None


def test_gleichzeitige_anlagen_an_der_grenze_ergeben_hoechstens_fuenf(buch):
    for i in range(3):
        assert vorbereiten(hook=f"Hook {i}")[1] is None
    ergebnisse = []

    def los(i):
        ergebnisse.append(vorbereiten(hook=f"Parallel {i}"))

    faeden = [threading.Thread(target=los, args=(i,)) for i in range(3)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()
    assert sorted(s for _, s in ergebnisse if s) == [vu.SATZ_VOLL]
    assert server._q("select count(*) as n from video_uebergabe where status = 'offen'")[0]["n"] == 5


def test_gleichzeitig_derselbe_hash_ergibt_eine_uebergabe(buch):
    ergebnisse = []
    faeden = [threading.Thread(target=lambda: ergebnisse.append(vorbereiten())) for _ in range(3)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()
    assert sorted(s or "" for _, s in ergebnisse) == ["", vu.SATZ_DOPPELT, vu.SATZ_DOPPELT]
    assert server._q("select count(*) as n from video_uebergabe")[0]["n"] == 1


# --- Lesen ----------------------------------------------------------------------------------------------

def test_offene_zeigt_nur_nicht_abgelaufene_mit_alter(buch):
    vorbereiten(hook="neu")
    vorbereiten(hook="alt")
    server._q("update video_uebergabe set erstellt_am = now() - interval '25 hours' "
              "where konzept ->> 'hook' = 'alt' returning id")
    offene = vu.offene()
    assert len(offene) == 1 and offene[0]["konzept"]["hook"] == "neu"
    assert 0 <= offene[0]["alter_s"] < 60


def test_offene_nennt_fruehere_bestaetigung_desselben_konzepts(buch):
    vorbereiten()
    assert vu.offene()[0]["frueher_auftrag"] is None
    assert vu.bestaetigen(eine_id(), "mira")[0] == "ok"
    vorbereiten()                                                  # gleicher Inhalt noch einmal
    (z,) = vu.offene()
    assert str(z["frueher_auftrag"]) == AID


def test_zustand_liefert_nur_status_auftrag_und_fehler(buch):
    vorbereiten()
    kennung = eine_id()
    assert vu.zustand(kennung) == {"status": "offen", "auftrag_id": None, "fehler": None}
    assert vu.zustand("kaputt") is None and vu.zustand("0123abcd-0000-4000-8000-00000000ffff") is None
    vu.bestaetigen(kennung, "mira")
    z = vu.zustand(kennung)
    assert z["status"] == "bestaetigt" and str(z["auftrag_id"]) == AID and "konzept" not in z


# --- Ja --------------------------------------------------------------------------------------------------

def test_ja_legt_auftrag_an_und_setzt_bestaetigt(buch):
    vorbereiten()
    kennung = eine_id()
    art, wert = vu.bestaetigen(kennung, "mira")
    assert (art, wert) == ("ok", {"auftrag": AID[:8], "id": AID})
    (laden, mandant, bart, eingabe), = buch.aufrufe
    assert (laden, mandant, bart) == ("ivan", "fin2gether", "video")
    assert eingabe["von"] == "rowboat" and eingabe["konzept"] == konzept()
    assert eingabe["konzept_sha"] == video_konzept.block_hash(konzept()) and eingabe["uebergabe"] == kennung
    assert eingabe["beschreibung"] == "Wer früh antwortet, gewinnt.\n\nJetzt anfragen."
    z = zeile(kennung)
    assert z["status"] == "bestaetigt" and str(z["auftrag_id"]) == AID
    assert z["entschieden_von"] == "mira" and z["entschieden_am"] is not None and z["fehler"] is None


def test_tagesgrenze_beim_ja_haelt_die_uebergabe_offen(buch):
    vorbereiten()
    kennung = eine_id()
    buch.ablehnung = TAGESGRENZE
    assert vu.bestaetigen(kennung, "mira") == ("abgelehnt", TAGESGRENZE)
    z = zeile(kennung)
    assert z["status"] == "offen" and z["fehler"] == TAGESGRENZE
    assert z["entschieden_von"] is None and z["auftrag_id"] is None
    buch.ablehnung = None                                         # am naechsten Tag klappt es
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"
    assert zeile(kennung)["fehler"] is None


def test_pruefung_beim_ja_auch_fuer_ein_schon_gespeichertes_konzept(buch):
    k = konzept(firma="andere-firma")                             # am Annahme-Weg vorbei in die Tabelle
    server._q("insert into video_uebergabe (konzept, konzept_sha) values (%s::jsonb, %s) returning id",
              (json.dumps(k), "a" * 64))
    assert vu.bestaetigen(eine_id(), "mira") == ("abgelehnt", vu.SATZ_FIRMA)
    assert buch.aufrufe == [] and zeile()["status"] == "offen"


def test_ja_ohne_marketing_firma(buch, monkeypatch):
    vorbereiten()
    monkeypatch.setenv("MARKETING_MANDANT", "")
    assert vu.bestaetigen(eine_id(), "mira") == ("abgelehnt", vu.SATZ_KEINE_FIRMA)


def test_abgelaufene_uebergabe_laesst_sich_nicht_bestaetigen(buch):
    vorbereiten()
    kennung = eine_id()
    altern(25, kennung)
    assert vu.bestaetigen(kennung, "mira") == ("abgelaufen", "Diese Übergabe ist abgelaufen.")
    assert zeile(kennung)["status"] == "abgelaufen" and buch.aufrufe == []
    assert vu.verwerfen(kennung, "mira") is False


def test_zweites_ja_ist_schon_entschieden(buch):
    vorbereiten()
    kennung = eine_id()
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"
    assert vu.bestaetigen(kennung, "mira") == ("entschieden", "Diese Übergabe ist schon entschieden.")
    assert len(buch.aufrufe) == 1


def test_doppelklick_zwei_gleichzeitige_ja_ergeben_genau_einen_auftrag(buch):
    vorbereiten()
    kennung = eine_id()
    buch.dauer = 1.0                                              # das erste Ja haelt die Zeilensperre
    ergebnisse = []
    faeden = [threading.Thread(target=lambda: ergebnisse.append(vu.bestaetigen(kennung, "mira")))
              for _ in range(2)]
    faeden[0].start()
    assert buch.drin.wait(10)               # erst wenn das erste Ja im Buch steckt, kommt das zweite: Ueberlappung erzwungen
    faeden[1].start()
    for f in faeden:
        f.join()
    assert sorted(a for a, _ in ergebnisse) == ["entschieden", "ok"]
    assert len(buch.aufrufe) == 1 and zeile(kennung)["status"] == "bestaetigt"


def test_ausfall_beim_ja_nimmt_alles_zurueck(buch):
    vorbereiten()
    kennung = eine_id()
    buch.ausfall = RuntimeError("Datenbank weg")
    with pytest.raises(RuntimeError):
        vu.bestaetigen(kennung, "mira")
    z = zeile(kennung)
    assert z["status"] == "offen" and z["entschieden_von"] is None and z["auftrag_id"] is None
    buch.ausfall = None
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"             # ein Wiederholen legt genau einen Auftrag an
    assert len(buch.aufrufe) == 1


@pytest.mark.parametrize("kennung", ["", "kaputt", "0123abcd-0000-4000-8000-00000000ffff", None, 5])
def test_unbekannte_kennung(buch, kennung):
    assert vu.bestaetigen(kennung, "mira") == ("fehlt", "Diese Übergabe gibt es nicht.")
    assert vu.verwerfen(kennung, "mira") is False


# --- Nein ------------------------------------------------------------------------------------------------

def test_nein_verwirft_ohne_bestellung(buch):
    vorbereiten()
    kennung = eine_id()
    assert vu.verwerfen(kennung, "mira") is True
    z = zeile(kennung)
    assert z["status"] == "verworfen" and z["entschieden_von"] == "mira" and buch.aufrufe == []
    assert vu.verwerfen(kennung, "mira") is False
    assert vu.bestaetigen(kennung, "mira")[0] == "entschieden"


# --- Log -------------------------------------------------------------------------------------------------

def test_log_nennt_nur_kennung_status_und_hash_anfang(buch, caplog):
    with caplog.at_level(logging.DEBUG):
        vorbereiten(kernaussage="Streng geheime Kernaussage", thema=SERIE)
        kennung = eine_id()
        vu.bestaetigen(kennung, "mira")
    text = caplog.text
    assert "video-uebergabe status=vorbereitet" in text and "video-uebergabe status=bestaetigt" in text
    assert kennung[:8] in text
    assert "geheime" not in text and "fett" not in text and "Entscheider" not in text
