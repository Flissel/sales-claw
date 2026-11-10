"""Postfach an das Ziel angleichen (Spec 2026-11-06 §6, §11, §12; Rulings R1, R5, R13).

Gegen die echte Datenbank, nur sales_test. IMAP ist die Attrappe aus test_post_imap
und wird `ordnen` als Verbindungsweg uebergeben; die Sperre in conftest bleibt.
Hier haengt das Loeschen echter Mails dran: jeder Test, der „nicht geloescht“
prueft, schaut auf DB-Zeile UND Attrappe.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_abholen  # noqa: E402
import post_konten  # noqa: E402
import post_ordnen  # noqa: E402
import post_werbung  # noqa: E402
import post_ziel  # noqa: E402
from test_post_imap import FakeKasten, mail, mail_mit_anhang  # noqa: E402

VON = "Shop <news@shop.example>"
BETREFF = "Nur heute 50 Prozent Rabatt"


@pytest.fixture
def db(monkeypatch):
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_regeln")
            conn.execute("truncate sales_test.post_loeschfreigaben")
            conn.execute("truncate sales_test.post_konten cascade")
    leeren()
    # 2025 ist Altbestand, was seit 2026 kam, ist neu (To-Review statt Loeschen).
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 1, 1))
    monkeypatch.setattr(post_ordnen, "MODUS", "verschieben")
    yield server
    leeren()


def _konto(server, kennung="gmx-test", anbieter="gmx", uidvalidity=1, besitzer="felix"):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle, uidvalidity) "
            "values (%s, %s, %s, %s, 'ui', %s) returning id",
            (besitzer, kennung, anbieter, f"{kennung}@x.de", uidvalidity)).fetchone()["id"]


def _mail(server, konto_id, uid, mid=None, *, fach="Werbung", sicher=True, ziel=None,
          ordner="INBOX", ordner_uid=None, ordner_am=None, datum=None,
          ersatz=False, von=VON, betreff=BETREFF, aufmerksamkeit=False, besitzer="felix"):
    mid = f"m{uid}@x" if mid is None else mid
    datum = datum or ALT
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, message_id_ersatz, besitzer, "
            "von, betreff, text, auszug, bereich, fach, werbung_sicher, aufmerksamkeit, status, "
            "ziel, ordner, ordner_uid, ordner_am, datum, anhaenge) values "
            "(%s, %s, %s, %s, %s, %s, %s, 'Volltext der Mail', 'Auszug', 'privat', %s, %s, %s, "
            "'eingeordnet', %s, %s, %s, " + (ordner_am or "null") + ", " + datum + ", '{}') "
            "returning id",
            (konto_id, uid, mid, ersatz, besitzer, von, betreff, fach, sicher, aufmerksamkeit,
             ziel, ordner, ordner_uid)).fetchone()["id"]


def _datum(wert: str) -> str:
    return "'" + wert + "'::timestamptz"


def _zeile(server, mail_id) -> dict:
    return server._q("select * from post_mails where id = %s", (mail_id,))[0]


def _konto_zeile(server, kennung) -> dict:
    return server._q("select * from post_konten where kennung = %s", (kennung,))[0]


def _freigabe(server, jahr=2025, ausgenommen=(), besitzer="felix"):
    server._q("insert into post_loeschfreigaben (besitzer, jahr, ausgenommen) "
              "values (%s, %s, %s::jsonb) returning id",
              (besitzer, jahr, json.dumps(list(ausgenommen))))


def _verbinden(kaesten: dict, aufrufe=None):
    def verbinden(zeile):
        if aufrufe is not None:
            aufrufe.append(zeile["kennung"])
        return kaesten[zeile["kennung"]]
    return verbinden


def _schreibend(k: FakeKasten) -> list:
    return [p for p in k.protokoll
            if p[:2] in (("uid", "MOVE"), ("uid", "COPY"), ("uid", "STORE"), ("uid", "EXPUNGE"))
            or p[0] == "expunge"]


ALT = _datum("2025-06-01T09:00:00Z")


# --- Verschieben ----------------------------------------------------------------

def test_ordnen_verschiebt_zur_info_und_merkt_ordner(db):
    k_id = _konto(db)
    m = _mail(db, k_id, 7, fach="Newsletter & Branche", sicher=False, datum=ALT)
    post_ziel.ziele_aktualisieren()
    assert _zeile(db, m)["ziel"] == "zur_info"
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz == {"verschoben": 1, "geloescht": 0, "fehlt": 0, "fehler": 0, "konten_aus": []}
    z = _zeile(db, m)
    assert (z["ordner"], z["ordner_stand"], z["ordner_uid"], z["ziel"]) == (
        "Zur Info", "ok", 1, "zur_info")
    assert z["ordner_am"] is not None and z["status"] == "eingeordnet"
    assert 7 not in kasten.ordner["INBOX"] and kasten.ordner["Zur Info"] == {1: mail("m7@x")}
    # Zweite Runde: nichts mehr zu tun, keine Verbindung noetig.
    aufrufe = []
    zweite = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}, aufrufe))
    assert zweite["verschoben"] == 0
    assert aufrufe == []


def test_ordnen_fehlende_uid_markiert_und_laeuft_weiter(db):
    k_id = _konto(db)
    # Die neuere Mail zuerst; ihre UID gibt es nicht mehr (Felix hat sie am Handy verschoben).
    weg = _mail(db, k_id, 7, fach="Rechnungen", sicher=False, ziel="zur_info",
                datum=_datum("2025-07-01T09:00:00Z"))
    da = _mail(db, k_id, 8, fach="Rechnungen", sicher=False, ziel="zur_info",
               datum=_datum("2025-06-01T09:00:00Z"))
    kasten = FakeKasten(ordner={"INBOX": {8: mail("m8@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert (bilanz["fehlt"], bilanz["verschoben"], bilanz["fehler"]) == (1, 1, 0)
    assert (_zeile(db, weg)["ordner_stand"], _zeile(db, weg)["ordner"]) == ("fehlt", "INBOX")
    assert (_zeile(db, da)["ordner_stand"], _zeile(db, da)["ordner"]) == ("ok", "Zur Info")
    # Eine fehlende Mail wird nicht jede Runde neu gesucht.
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))["fehlt"] == 0


def test_ordnen_ohne_faehigkeit_setzt_ordnen_aus_und_andere_konten_laufen(db):
    alt = _konto(db, "gmx-alt")
    gut = _konto(db, "gmx-gut")
    m_alt = _mail(db, alt, 7, fach="Rechnungen", sicher=False, ziel="zur_info", datum=ALT)
    m_gut = _mail(db, gut, 7, fach="Rechnungen", sicher=False, ziel="zur_info", datum=ALT)
    k_alt = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}}, capabilities=("IMAP4REV1",))
    k_gut = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    kaesten = {"gmx-alt": k_alt, "gmx-gut": k_gut}
    bilanz = post_ordnen.ordnen(verbinden=_verbinden(kaesten))
    assert bilanz["konten_aus"] == ["gmx-alt"] and bilanz["verschoben"] == 1
    assert "MOVE" in _konto_zeile(db, "gmx-alt")["ordnen_aus"]
    assert _konto_zeile(db, "gmx-gut")["ordnen_aus"] is None
    assert (_zeile(db, m_alt)["ordner"], _zeile(db, m_alt)["ordner_stand"]) == ("INBOX", None)
    assert _zeile(db, m_gut)["ordner"] == "Zur Info"
    assert _schreibend(k_alt) == [] and 7 in k_alt.ordner["INBOX"]
    # Das ruhende Konto wird danach gar nicht mehr geoeffnet.
    aufrufe = []
    post_ordnen.ordnen(verbinden=_verbinden(kaesten, aufrufe))
    assert "gmx-alt" not in aufrufe


def test_ordner_ohne_uid_sucht_per_message_id(db):
    k_id = _konto(db)
    m = _mail(db, k_id, 7, fach="Rechnungen", sicher=False, ziel="posteingang",
              ordner="Zur Info", ordner_am="now() - interval '1 day'", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {}, "Zur Info": {4: mail("anders@x"), 5: mail("m7@x")}})
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))["verschoben"] == 1
    z = _zeile(db, m)
    assert (z["ordner"], z["ordner_uid"], z["ordner_stand"]) == ("INBOX", 1, "ok")
    assert set(kasten.ordner["Zur Info"]) == {4}


def test_ersatz_id_ausserhalb_der_inbox_wird_nicht_geraten(db):
    k_id = _konto(db)
    m = _mail(db, k_id, 7, "gmx-test:7@sales-post", ersatz=True, fach="Rechnungen",
              sicher=False, ziel="posteingang", ordner="Zur Info", ordner_uid=4, datum=ALT)
    kasten = FakeKasten(ordner={"Zur Info": {4: mail(None)}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["fehler"] == 1 and _zeile(db, m)["ordner_stand"] == "fehler"
    assert _schreibend(kasten) == []


def test_uidvalidity_geaendert_konto_ruht(db):
    k_id = _konto(db, uidvalidity=1)
    m = _mail(db, k_id, 7, fach="Rechnungen", sicher=False, ziel="zur_info", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}}, uidvalidity=2)
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["konten_aus"] == ["gmx-test"] and bilanz["verschoben"] == 0
    assert "UIDVALIDITY" in _konto_zeile(db, "gmx-test")["ordnen_aus"]
    assert _zeile(db, m)["ordner"] == "INBOX" and _schreibend(kasten) == []


def test_platzhalter_nach_uidvalidity_wechsel_werden_uebersprungen(db):
    """Reihenfolge wie in eine_runde: abholen nummeriert die INBOX nach einem
    UIDVALIDITY-Wechsel um (alte UIDs negativ, neue UIDVALIDITY gespeichert) und
    findet je Runde nur einen Stapel wieder. ordnen darf die noch nicht
    wiedergefundenen Zeilen nicht als fehlt abschreiben."""
    k_id = _konto(db, uidvalidity=1)
    offen = _mail(db, k_id, 7, fach="Rechnungen", sicher=False, ziel="zur_info",
                  datum=_datum("2025-07-01T09:00:00Z"))
    wieder = _mail(db, k_id, 8, fach="Rechnungen", sicher=False, ziel="zur_info",
                   datum=_datum("2025-06-01T09:00:00Z"))
    # Das echte Umnummerieren aus post_abholen, dann wie _speichern: Zeile 8 wiedergefunden.
    assert post_abholen._uidvalidity_pruefen(_konto_zeile(db, "gmx-test"), 2) == 0
    assert _zeile(db, offen)["imap_uid"] < 0 and _zeile(db, wieder)["imap_uid"] < 0
    db._q("update post_mails set imap_uid = 1 where id = %s returning id", (wieder,))
    kasten = FakeKasten(ordner={"INBOX": {1: mail("m8@x"), 2: mail("m7@x")}}, uidvalidity=2)

    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz == {"verschoben": 1, "geloescht": 0, "fehlt": 0, "fehler": 0, "konten_aus": []}
    z = _zeile(db, offen)
    assert (z["ordner"], z["ordner_stand"], z["ordner_am"]) == ("INBOX", None, None)
    assert (_zeile(db, wieder)["ordner"], _zeile(db, wieder)["ordner_stand"]) == ("Zur Info", "ok")
    assert 2 in kasten.ordner["INBOX"]
    # Spaeter wiedergefunden: dann wird auch sie normal geordnet.
    db._q("update post_mails set imap_uid = 2 where id = %s returning id", (offen,))
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))["verschoben"] == 1
    assert _zeile(db, offen)["ordner"] == "Zur Info"


# --- Loeschen -------------------------------------------------------------------

def test_modus_verschieben_loescht_nie(db):
    k_id = _konto(db)
    _freigabe(db, 2025)
    werbung = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    review = _mail(db, k_id, 8, ziel="to_review", ordner="To-Review", ordner_uid=3,
                   ordner_am="now() - interval '40 days'", datum="now() - interval '41 days'")
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "To-Review": {3: mail("m8@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0 and _schreibend(kasten) == []
    # R5: freigegebene Werbung bleibt, wo sie ist - auch nicht nach To-Review oder Zur Info.
    z = _zeile(db, werbung)
    assert (z["status"], z["ordner"]) == ("eingeordnet", "INBOX")
    assert _zeile(db, review)["status"] == "eingeordnet"
    assert 7 in kasten.ordner["INBOX"] and 3 in kasten.ordner["To-Review"]


def test_loeschen_ohne_freigabe_bleibt_wo_es_ist(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2024)                                  # anderes Jahr
    _freigabe(db, 2025, besitzer="ivan")                 # anderer Besitzer
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0 and _schreibend(kasten) == []
    assert (_zeile(db, m)["status"], _zeile(db, m)["ordner"]) == ("eingeordnet", "INBOX")


def test_loeschen_leert_text_behaelt_kopf(db, monkeypatch, caplog):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")}})
    kasten.flags[("INBOX", 8)] = {"\\Deleted"}          # fremde Markierung bleibt unberuehrt
    caplog.set_level("INFO")
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 1
    z = _zeile(db, m)
    assert z["status"] == "geloescht" and z["geloescht_am"] is not None
    assert z["text"] is None and z["auszug"] is None
    assert (z["von"], z["betreff"], z["message_id"], z["imap_uid"], z["fach"]) == (
        VON, BETREFF, "m7@x", 7, "Werbung")
    assert z["ordner_stand"] == "ok"
    assert set(kasten.ordner["INBOX"]) == {8} and not kasten.nackt_expunged()
    assert kasten.befehle("EXPUNGE") == [("uid", "EXPUNGE", "7")]
    # Protokoll: Kennung und Aktion, nie Betreff oder Absender.
    assert "gmx-test" in caplog.text
    assert BETREFF not in caplog.text and "news@shop.example" not in caplog.text


def test_to_review_nach_30_tagen_geloescht_nur_voll(db, monkeypatch):
    k_id = _konto(db)
    neu = "now() - interval '41 days'"
    alt = _mail(db, k_id, 7, ziel="to_review", ordner="To-Review", ordner_uid=3,
                ordner_am="now() - interval '31 days'", datum=neu)
    jung = _mail(db, k_id, 8, ziel="to_review", ordner="To-Review", ordner_uid=4,
                 ordner_am="now() - interval '5 days'", datum=neu)
    kasten = FakeKasten(ordner={"To-Review": {3: mail("m7@x"), 4: mail("m8@x")}})
    verbinden = _verbinden({"gmx-test": kasten})

    assert post_ordnen.ordnen(verbinden=verbinden)["geloescht"] == 0
    assert _zeile(db, alt)["status"] == "eingeordnet" and _schreibend(kasten) == []

    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    assert post_ordnen.ordnen(verbinden=verbinden)["geloescht"] == 1
    assert _zeile(db, alt)["status"] == "geloescht"
    assert _zeile(db, jung)["status"] == "eingeordnet"
    assert set(kasten.ordner["To-Review"]) == {4}


def test_falsche_message_id_unter_der_uid_loescht_nicht(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("rechnung@bank.example")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0 and bilanz["fehlt"] == 1
    assert (_zeile(db, m)["status"], _zeile(db, m)["ordner_stand"]) == ("eingeordnet", "fehlt")
    assert 7 in kasten.ordner["INBOX"] and _schreibend(kasten) == []


def test_ersatz_id_wird_nie_geloescht(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, "gmx-test:7@sales-post", ersatz=True, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail(None)}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0 and bilanz["fehler"] == 1
    assert (_zeile(db, m)["status"], _zeile(db, m)["ordner_stand"]) == ("eingeordnet", "fehler")
    assert 7 in kasten.ordner["INBOX"] and _schreibend(kasten) == []


def test_ziel_inzwischen_zur_info_wird_nicht_geloescht(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    # Nach der Berechnung des gespeicherten Ziels: Absender wird geschuetzt.
    post_werbung.schutz_setzen("felix", VON)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0
    z = _zeile(db, m)
    assert z["status"] == "eingeordnet" and z["ziel"] == "zur_info"
    assert 7 in kasten.ordner["INBOX"]
    assert not kasten.befehle("STORE") and not kasten.befehle("EXPUNGE")


def test_absender_in_ausgenommen_wird_nicht_geloescht(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025, ausgenommen=["News@Shop.example"])
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0
    assert _zeile(db, m)["status"] == "eingeordnet"
    assert 7 in kasten.ordner["INBOX"] and _schreibend(kasten) == []


def test_leere_message_id_ist_zeilenfehler_und_konto_laeuft_weiter(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    leer = _mail(db, k_id, 7, "", ziel="loeschen", datum=_datum("2025-07-01T09:00:00Z"))
    gut = _mail(db, k_id, 8, ziel="loeschen", datum=_datum("2025-06-01T09:00:00Z"))
    kasten = FakeKasten(ordner={"INBOX": {7: mail(None), 8: mail("m8@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert (bilanz["fehler"], bilanz["geloescht"], bilanz["konten_aus"]) == (1, 1, [])
    z = _zeile(db, leer)
    assert (z["status"], z["ordner_stand"]) == ("eingeordnet", "fehler")
    assert _zeile(db, gut)["status"] == "geloescht"
    assert 7 in kasten.ordner["INBOX"] and 8 not in kasten.ordner["INBOX"]


def test_gmail_loeschen_ueber_ordnen(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db, "gmail-test", anbieter="gmail")
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "[Gmail]/Trash": {}},
                        merkmale={"[Gmail]/Trash": "\\Trash"})
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmail-test": kasten}))["geloescht"] == 1
    assert _zeile(db, m)["status"] == "geloescht"
    assert kasten.ordner["INBOX"] == {} and kasten.ordner["[Gmail]/Trash"] == {}
    assert kasten.befehle("EXPUNGE") == [("uid", "EXPUNGE", "1")]


def test_bleibt_immer_absender_regelwerbung_wird_nicht_geloescht(db, monkeypatch):
    """C1: das gespeicherte Ziel ist loeschen, inzwischen kam eine Rechnung desselben
    Absenders. ziel_frisch sieht das, also bleibt die Mail."""
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)            # Quelle unbekannt = Regel
    _mail(db, k_id, 8, fach="Rechnungen", sicher=False, ziel="zur_info", ordner="Zur Info",
          ordner_uid=3, ordner_am="now()")
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "Zur Info": {3: mail("m8@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0
    z = _zeile(db, m)
    assert (z["status"], z["ziel"]) == ("eingeordnet", "zur_info")
    assert 7 in kasten.ordner["INBOX"] and _schreibend(kasten) == []


def test_to_review_mit_geaendertem_ziel_wird_nach_30_tagen_nicht_geloescht(db, monkeypatch):
    """M5: herausgeholt (Absender jetzt geschuetzt) - ziel_frisch weicht ab, nichts geloescht."""
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    m = _mail(db, k_id, 7, ziel="to_review", ordner="To-Review", ordner_uid=3,
              ordner_am="now() - interval '31 days'", datum="now() - interval '41 days'")
    post_werbung.schutz_setzen("felix", VON)
    kasten = FakeKasten(ordner={"To-Review": {3: mail("m7@x")}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0
    z = _zeile(db, m)
    assert (z["status"], z["ziel"]) == ("eingeordnet", "zur_info")
    assert 3 in kasten.ordner["To-Review"]
    assert not kasten.befehle("STORE") and not kasten.befehle("EXPUNGE")


@pytest.mark.parametrize("teil", [
    ("application", "pdf", "angebot.pdf", "attachment"),
    ("application", "octet-stream", None, None),
    ("message", "rfc822", None, None),
], ids=["pdf", "ohne-namen", "rfc822"])
def test_altbestand_mit_anhang_laut_struktur_wird_nicht_geloescht(db, monkeypatch, teil):
    """I7: beim Abholen ohne Dateinamen nicht erkannt (anhaenge leer). Vor dem Loeschen zeigt
    BODYSTRUCTURE den Anhang: die Mail bleibt, bekommt den Platzhalter und Ziel zur_info."""
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail_mit_anhang("m7@x", teil)}})
    bilanz = post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))
    assert bilanz["geloescht"] == 0
    z = _zeile(db, m)
    assert (z["status"], z["ziel"], z["ordner"]) == ("eingeordnet", "zur_info", "INBOX")
    assert z["ordner_stand"] in (None, "ok") and "(Anhang)" in z["anhaenge"]
    assert 7 in kasten.ordner["INBOX"] and _schreibend(kasten) == []
    # Nur Struktur und Kopf abgefragt, nie der Inhalt.
    assert all("BODY[]" not in p[3] and "RFC822" not in p[3] for p in kasten.befehle("FETCH"))
    # Die naechste Berechnung bleibt dabei (kein Hin und Her mit ziele_aktualisieren).
    post_ziel.ziele_aktualisieren()
    assert _zeile(db, m)["ziel"] == "zur_info"


def test_altbestand_nur_mit_bild_wird_geloescht(db, monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db)
    _freigabe(db, 2025)
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT)
    kasten = FakeKasten(ordner={"INBOX": {7: mail_mit_anhang(
        "m7@x", ("image", "png", None, "attachment"))}})
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmx-test": kasten}))["geloescht"] == 1
    assert _zeile(db, m)["status"] == "geloescht" and 7 not in kasten.ordner["INBOX"]


def test_fremdes_konto_nicht_angefasst(db, monkeypatch):
    """Freigabe und Loeschen nur fuer Konten des eigenen Besitzers."""
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    k_id = _konto(db, "gmx-ivan", besitzer="ivan")
    _freigabe(db, 2025, besitzer="felix")
    m = _mail(db, k_id, 7, ziel="loeschen", datum=ALT, besitzer="ivan")
    kasten = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    assert post_ordnen.ordnen(verbinden=_verbinden({"gmx-ivan": kasten}))["geloescht"] == 0
    assert _zeile(db, m)["status"] == "eingeordnet" and _schreibend(kasten) == []


# --- Schalter und Runde ---------------------------------------------------------

def test_modus_aus_tut_nichts(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(post_ordnen, "MODUS", "aus")
    monkeypatch.setattr(post_abholen, "_STOPP", post_abholen.threading.Event())
    monkeypatch.setattr(post_konten, "aktive_konten", lambda: [])
    monkeypatch.setattr(post_abholen, "kunde_aktiv", lambda: False)
    monkeypatch.setattr(post_abholen, "modellaufrufe_heute", lambda: 0)
    monkeypatch.setattr(post_abholen, "einordnen_offene", lambda grenze: 0)
    monkeypatch.setattr(post_ziel, "ziele_aktualisieren", lambda: aufrufe.append("ziele") or 0)
    monkeypatch.setattr(post_ordnen, "ordnen", lambda *a, **k: aufrufe.append("ordnen") or {})
    post_abholen.eine_runde()
    assert aufrufe == ["ziele"]


def test_ordnen_selbst_tut_bei_modus_aus_nichts(monkeypatch):
    monkeypatch.setattr(post_ordnen, "MODUS", "aus")

    def nie(zeile):
        raise AssertionError("Verbindung bei MODUS aus")
    assert post_ordnen.ordnen(verbinden=nie) == {
        "verschoben": 0, "geloescht": 0, "fehlt": 0, "fehler": 0, "konten_aus": []}


def test_modus_aus_unbekanntem_wert_ist_aus():
    assert post_ordnen._modus("voll") == "voll"
    assert post_ordnen._modus(" Verschieben ") == "verschieben"
    assert post_ordnen._modus("ja") == "aus" and post_ordnen._modus("") == "aus"


def _runde_ohne_abholen(monkeypatch):
    monkeypatch.setattr(post_abholen, "_STOPP", post_abholen.threading.Event())
    monkeypatch.setattr(post_konten, "aktive_konten", lambda: [])
    monkeypatch.setattr(post_abholen, "kunde_aktiv", lambda: False)
    monkeypatch.setattr(post_abholen, "modellaufrufe_heute", lambda: 0)
    monkeypatch.setattr(post_abholen, "einordnen_offene", lambda grenze: 0)


def test_runde_ordnet_wenn_modus_an(monkeypatch):
    aufrufe = []
    _runde_ohne_abholen(monkeypatch)
    monkeypatch.setattr(post_ordnen, "MODUS", "verschieben")
    monkeypatch.setattr(post_ziel, "ziele_aktualisieren", lambda: aufrufe.append("ziele") or 2)
    monkeypatch.setattr(post_ordnen, "ordnen",
                        lambda *a, **k: aufrufe.append("ordnen") or {"verschoben": 1})
    bilanz = post_abholen.eine_runde()
    assert aufrufe == ["ziele", "ordnen"]
    assert bilanz["ziele"] == 2 and bilanz["ordnen"] == {"verschoben": 1}


def test_runde_ordnet_auch_in_der_kundenpause(monkeypatch):
    aufrufe = []
    _runde_ohne_abholen(monkeypatch)
    monkeypatch.setattr(post_abholen, "kunde_aktiv", lambda: True)
    monkeypatch.setattr(post_ordnen, "MODUS", "verschieben")
    monkeypatch.setattr(post_ziel, "ziele_aktualisieren", lambda: aufrufe.append("ziele") or 0)
    monkeypatch.setattr(post_ordnen, "ordnen", lambda *a, **k: aufrufe.append("ordnen") or {})
    assert post_abholen.eine_runde().get("pause") == "kundenantwort"
    assert aufrufe == ["ziele", "ordnen"]


def test_fehler_in_ziele_oder_ordnen_bricht_runde_nicht_ab(monkeypatch, caplog):
    _runde_ohne_abholen(monkeypatch)
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    gerufen = []

    def ziele_kaputt():
        raise RuntimeError("Failing row contains Geheimer Betreff")

    def ordnen_kaputt(*a, **k):
        gerufen.append("ordnen")
        raise OSError("Geheimer Betreff")
    monkeypatch.setattr(post_ziel, "ziele_aktualisieren", ziele_kaputt)
    monkeypatch.setattr(post_ordnen, "ordnen", ordnen_kaputt)
    bilanz = post_abholen.eine_runde()
    assert gerufen == ["ordnen"] and "eingeordnet" in bilanz
    assert "RuntimeError" in caplog.text and "OSError" in caplog.text
    assert "Geheimer Betreff" not in caplog.text
