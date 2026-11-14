"""Das Ja gegen ECHTES SQL: Anspruch, Auftrag, Sicherungspunkt und Statuswechsel laufen wirklich in einer Transaktion.

NUR IN DER CI lauffaehig (Postgres mit db/video-uebergabe.sql fuer sales_test). Im Unterschied zu test_video_uebergabe.py
ersetzt hier NICHTS `auftrag_buch.anlegen`: der echte Code ruft `auftrag.sales_anlegen`. Das Auftragsbuch gibt es in
keiner Test-DB, darum legt dieses Modul ein Test-Schema `auftrag` aus tests/auftrag_standin.sql an (gleiche Namen,
Signaturen und Fehlertexte wie 096/098 in vibemind-os) und wirft es am Ende weg.

Schutz: das Modul laeuft nur, wenn `server.SCHEMA == "sales_test"` und das Schema `auftrag` entweder nicht existiert
oder die Marke dieses Ersatzes traegt. Existiert ein anderes `auftrag` (ein echtes Auftragsbuch), wird ALLES
uebersprungen und nichts angefasst.
"""
import json
import os
from pathlib import Path

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import auftrag_buch  # noqa: E402
import server  # noqa: E402
import video_konzept  # noqa: E402
import video_uebergabe as vu  # noqa: E402

MARKE = "TEST-STANDIN fuer video_uebergabe (kein echtes Auftragsbuch)"
SQL = Path(__file__).with_name("auftrag_standin.sql")
TAGESGRENZE = "Heute sind schon zwei Videos bestellt – morgen wieder."


@pytest.fixture(scope="module", autouse=True)
def standin():
    assert server.SCHEMA == "sales_test"
    vorhanden = server._q("select obj_description(oid, 'pg_namespace') as c from pg_namespace "
                          "where nspname = 'auftrag'")
    if vorhanden and vorhanden[0]["c"] != MARKE:
        pytest.skip("Schema `auftrag` gehoert einem echten Auftragsbuch - nichts angefasst")
    with server.pool.connection() as conn:
        conn.execute("drop schema if exists auftrag cascade")        # nur der eigene Ersatz kann hier stehen
        conn.execute(SQL.read_text(encoding="utf-8"))
    yield
    with server.pool.connection() as conn:
        conn.execute("drop schema if exists auftrag cascade")


@pytest.fixture(autouse=True)
def sauber(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.video_uebergabe")
        conn.execute("truncate auftrag.auftraege")
        conn.execute("update auftrag.test_modus set modus = 'ok'")
    monkeypatch.setenv("MARKETING_MANDANT", "fin2gether")
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    yield


def modus(wert):
    server._q("update auftrag.test_modus set modus = %s returning modus", (wert,))


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


def vorbereiten():
    k = konzept()
    assert vu.anlegen(k, video_konzept.block_hash(k))[1] is None
    return str(server._q("select id from video_uebergabe")[0]["id"])


def uebergabe(kennung):
    return server._q("select * from video_uebergabe where id = %s", (kennung,))[0]


def auftraege():
    return server._q("select * from auftrag.auftraege order by angelegt")


def zwei_videos_heute():
    for _ in range(2):
        server._q("insert into auftrag.auftraege (von, an, laden, mandant, art) "
                  "values ('sales', 'marketing', 'ivan', 'fin2gether', 'video') returning id")


def test_standin_hat_die_echte_signatur():
    # Der Ersatz wird so aufgerufen wie das echte Auftragsbuch: auftrag_buch.anlegen -> auftrag.sales_anlegen(...)
    aid = auftrag_buch.anlegen(server._q, "ivan", "fin2gether", "video", {"x": 1})
    assert len(aid) == 36 and len(auftraege()) == 1


def test_erfolg_bestaetigt_und_der_auftrag_existiert(monkeypatch):
    kennung = vorbereiten()
    art, wert = vu.bestaetigen(kennung, "mira")
    assert art == "ok"
    (a,) = auftraege()
    assert str(a["id"]) == wert["id"] and wert["auftrag"] == wert["id"][:8]
    assert (a["von"], a["an"], a["laden"], a["mandant"], a["art"]) == ("sales", "marketing", "ivan", "fin2gether", "video")
    assert a["eingabe"]["von"] == "rowboat" and a["eingabe"]["uebergabe"] == kennung
    assert a["eingabe"]["konzept"] == konzept()
    z = uebergabe(kennung)
    assert z["status"] == "bestaetigt" and str(z["auftrag_id"]) == str(a["id"]) and z["entschieden_von"] == "mira"


def test_tagesgrenze_rollt_den_auftrag_zurueck_und_die_uebergabe_bleibt_offen():
    kennung = vorbereiten()
    zwei_videos_heute()
    assert vu.bestaetigen(kennung, "mira") == ("abgelehnt", TAGESGRENZE)
    assert len(auftraege()) == 2                                  # nichts dazugekommen
    z = uebergabe(kennung)
    assert z["status"] == "offen" and z["fehler"] == TAGESGRENZE            # Update nach dem abgebrochenen Statement ging
    assert z["entschieden_von"] is None and z["auftrag_id"] is None
    server._q("delete from auftrag.auftraege where id = (select id from auftrag.auftraege limit 1) returning id")
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"             # am naechsten Tag (hier: Platz frei) klappt es
    assert uebergabe(kennung)["fehler"] is None


def test_allgemeine_ablehnung_des_buchs_ist_eine_ablehnung():
    kennung = vorbereiten()
    modus("ablehnung")
    assert vu.bestaetigen(kennung, "mira") == ("abgelehnt", "Das Auftragsbuch hat den Auftrag nicht angenommen.")
    assert auftraege() == [] and uebergabe(kennung)["status"] == "offen"


def test_fehlende_rechte_sind_ein_ausfall_keine_ablehnung():
    kennung = vorbereiten()
    modus("rechte")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        vu.bestaetigen(kennung, "mira")
    z = uebergabe(kennung)
    assert z["status"] == "offen" and z["fehler"] is None and auftraege() == []


def test_ausfall_nach_dem_insert_im_auftragsbuch_nimmt_beides_zurueck():
    kennung = vorbereiten()
    modus("ausfall_nach_insert")
    with pytest.raises(psycopg.errors.DivisionByZero):
        vu.bestaetigen(kennung, "mira")
    z = uebergabe(kennung)
    assert auftraege() == [] and z["status"] == "offen" and z["entschieden_von"] is None and z["fehler"] is None


def test_ausfall_nach_dem_auftrag_beim_statuswechsel_nimmt_beides_zurueck():
    """Der Auftrag ist angelegt, der Sicherungspunkt freigegeben - erst der letzte Update scheitert."""
    kennung = vorbereiten()
    with server.pool.connection() as conn:
        conn.execute("alter table sales_test.video_uebergabe "
                     "add constraint test_nie_bestaetigt check (status <> 'bestaetigt')")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            vu.bestaetigen(kennung, "mira")
    finally:
        with server.pool.connection() as conn:
            conn.execute("alter table sales_test.video_uebergabe drop constraint if exists test_nie_bestaetigt")
    z = uebergabe(kennung)
    assert auftraege() == []
    assert z["status"] == "offen" and z["auftrag_id"] is None and z["entschieden_von"] is None


def test_ausfall_im_python_nach_der_anlage_nimmt_beides_zurueck(monkeypatch):
    kennung = vorbereiten()
    echt = auftrag_buch.anlegen

    def danach(*args, **kw):
        echt(*args, **kw)
        raise RuntimeError("nach dem Auftrag")

    monkeypatch.setattr(auftrag_buch, "anlegen", danach)
    with pytest.raises(RuntimeError):
        vu.bestaetigen(kennung, "mira")
    assert auftraege() == [] and uebergabe(kennung)["status"] == "offen"
    monkeypatch.setattr(auftrag_buch, "anlegen", echt)
    assert vu.bestaetigen(kennung, "mira")[0] == "ok" and len(auftraege()) == 1      # Wiederholen: genau ein Auftrag


def test_doppeltes_ja_legt_genau_einen_auftrag_an():
    kennung = vorbereiten()
    assert vu.bestaetigen(kennung, "mira")[0] == "ok"
    assert vu.bestaetigen(kennung, "mira")[0] == "entschieden"
    assert len(auftraege()) == 1


def test_gespeichertes_konzept_geht_unveraendert_in_den_auftrag():
    kennung = vorbereiten()
    vu.bestaetigen(kennung, "mira")
    (a,) = auftraege()
    assert json.dumps(a["eingabe"]["konzept"], sort_keys=True) == json.dumps(konzept(), sort_keys=True)
