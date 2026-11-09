"""Kern-Modul freigabe_eingang (Plan 2026-11-08, Task 4)."""
import json
import os
import re
import uuid

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402

import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402

PR = "Flissel/vibemind-os#154"
LINK = "https://github.com/x"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        # Eine Anweisung, eintraege zuerst: die Fixtures anderer Dateien sperren
        # drafts -> eintraege -> auftraege; eine andere Reihenfolge ergibt Deadlocks.
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")
        conn.execute("delete from sales_test.einstellungen where schluessel = 'freigabe_stufe2'")
    yield


def _zeile(kennung):
    return server._q("select * from freigabe_eintraege where kennung = %s", (kennung,))[0]


def _debugger(ref=PR):
    return fe.eintragen("debugger-claw", "debugger_pr", ref, "t", LINK)[0]


def test_eintragen_idempotent():
    k1, neu1 = fe.eintragen("debugger-claw", "debugger_pr", PR, "t", LINK)
    k2, neu2 = fe.eintragen("debugger-claw", "debugger_pr", PR, "t", LINK)
    assert k1 == k2 and neu1 is True and neu2 is False
    assert len(server._q("select 1 from freigabe_eintraege")) == 1


def test_falsche_art_fuer_herkunft():
    with pytest.raises(fe.EingabeFehler):
        fe.eintragen("selbstbild", "debugger_pr", PR, "t")


def test_details_zu_gross():
    with pytest.raises(fe.EingabeFehler):
        fe.eintragen("debugger-claw", "debugger_pr", PR, "t", details={"x": "y" * 3000})


def test_titel_einzeilig_gekappt():
    k, _ = fe.eintragen("debugger-claw", "debugger_pr", PR, "a\nb" + "x" * 500)
    t = _zeile(k)["titel"]
    assert "\n" not in t and len(t) == 200


def test_link_nur_http():
    k, _ = fe.eintragen("debugger-claw", "debugger_pr", PR, "t", link="javascript:x")
    assert _zeile(k)["link"] is None


def test_kennung_format():
    assert re.fullmatch(r"fg-[a-z2-7]{10}", fe.kennung_neu())


def test_schliessen_nur_eigene_herkunft():
    k = _debugger()
    assert fe.schliessen("selbstbild", PR, "erledigt", "t") == 0
    assert _zeile(k)["status"] == "offen"
    assert fe.schliessen("debugger-claw", PR, "erledigt", "t") == 1
    assert _zeile(k)["status"] == "erledigt"


def test_schliessen_kennung_und_neu_nach_schliessen():
    k = _debugger()
    assert fe.schliessen_kennung(k, "verworfen", "ui") is True
    assert fe.schliessen_kennung(k, "verworfen", "ui") is False
    _, neu = fe.eintragen("debugger-claw", "debugger_pr", PR, "t")
    assert neu is True


def test_offene_und_zum_aufraeumen():
    k = _debugger()
    assert [e["kennung"] for e in fe.offene("debugger-claw")] == [k]
    assert fe.offene("selbstbild") == []
    fe.rowboat_stand_setzen(k, "vorgeschlagen")
    assert fe.zum_aufraeumen() == []
    fe.schliessen_kennung(k, "erledigt", "ui")
    assert [e["kennung"] for e in fe.zum_aufraeumen()] == [k]
    fe.aufgeraeumt(k)
    assert fe.zum_aufraeumen() == []


def test_zum_aufraeumen_enthaelt_geschlossene_ungesichtete():
    k = _debugger()
    fe.schliessen_kennung(k, "verworfen", "ui")
    assert _zeile(k)["rowboat_stand"] == "ungesichtet"
    assert [e["kennung"] for e in fe.zum_aufraeumen()] == [k]


def test_stand_nur_vorwaerts():
    k = _debugger()
    fe.rowboat_stand_setzen(k, "angenommen")
    assert _zeile(k)["rowboat_seit"] is not None
    fe.rowboat_stand_setzen(k, "vorgeschlagen")
    assert _zeile(k)["rowboat_stand"] == "angenommen"
    fe.rowboat_stand_setzen(k, "abgelehnt")
    assert _zeile(k)["rowboat_stand"] == "angenommen"


def test_abgelehnt_endgueltig():
    k = _debugger()
    fe.rowboat_stand_setzen(k, "abgelehnt")
    assert _zeile(k)["rowboat_stand"] == "abgelehnt"
    fe.rowboat_stand_setzen(k, "angenommen")
    assert _zeile(k)["rowboat_stand"] == "abgelehnt"


def _label_auftrag():
    k, _ = fe.eintragen("selbstbild", "selbstbild_rueckfrage", "r#1", "t")
    a = fe.auftrag_anlegen(k, "selbstbild_label", {"repo": "r", "nummer": 1, "label": "antwort:weg"}, "ui")
    return k, a


def test_auftrag_unbekannte_art():
    k = _debugger()
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "gibt_es_nicht", {}, "ui")


def test_auftrag_nur_einmal_abgeholt():
    _label_auftrag()
    assert len(fe.auftraege_abholen("selbstbild")) == 1
    assert fe.auftraege_abholen("selbstbild") == []


def test_auftrag_nur_fuer_abholer():
    _label_auftrag()
    assert fe.auftraege_abholen("werkstatt") == []


def test_haengender_auftrag_wird_fehler():
    _, a = _label_auftrag()
    fe.auftraege_abholen("selbstbild")
    server._q("update freigabe_auftraege set abgeholt_am = now() - interval '11 minutes' "
              "where id = %s returning id", (a,))
    assert fe.auftraege_abholen("selbstbild") == []
    z = server._q("select status from freigabe_auftraege where id = %s", (a,))
    assert z[0]["status"] == "fehler"


def test_label_erfolg_fuehrt_eintrag_aus():
    k, a = _label_auftrag()
    fe.auftraege_abholen("selbstbild")
    assert fe.auftrag_ergebnis(a, "selbstbild", True, None) is True
    assert _zeile(k)["status"] == "ausgefuehrt"
    assert fe.auftrag_ergebnis(a, "selbstbild", True, None) is False


def test_label_fehler_laesst_offen():
    k, a = _label_auftrag()
    fe.auftraege_abholen("selbstbild")
    assert fe.auftrag_ergebnis(a, "selbstbild", False, "kaputt") is True
    assert _zeile(k)["status"] == "offen"


def test_kurs_erfolg_laesst_offen():
    k, _ = fe.eintragen("werkstatt", "kursfreigabe", "kurs-1", "t")
    a = fe.auftrag_anlegen(k, "kurs_freigabe_zeigen", {"course_id": "c1"}, "ui")
    assert fe.auftraege_abholen("werkstatt")[0]["abholer"] == "werkstatt"
    assert fe.auftrag_ergebnis(a, "werkstatt", True, None) is True
    z = _zeile(k)
    assert z["status"] == "offen" and z["vermerk"] == "Freigabe-Link gesendet"


def test_ergebnis_falscher_abholer():
    _, a = _label_auftrag()
    fe.auftraege_abholen("selbstbild")
    assert fe.auftrag_ergebnis(a, "werkstatt", True, None) is False


def test_schluessel_hash_nicht_klartext():
    klar = fe.schluessel_anlegen("werkstatt")
    inhalt = str(server._q("select * from freigabe_schluessel"))
    assert klar not in inhalt
    assert fe.schluessel_herkunft(klar) == "werkstatt"
    assert fe.schluessel_herkunft("falsch") is None
    with pytest.raises(fe.EingabeFehler):
        fe.schluessel_anlegen("sales")


def test_schluessel_neu_ersetzt_alten():
    alt = fe.schluessel_anlegen("selbstbild")
    neu = fe.schluessel_anlegen("selbstbild")
    assert fe.schluessel_herkunft(alt) is None
    assert fe.schluessel_herkunft(neu) == "selbstbild"


def test_stufe2_aus_und_gesperrt():
    assert fe.stufe2_lesen() == {"debugger_pr": False, "selbstbild_rueckfrage": False,
                                 "kursfreigabe": False, "entwurf": False}
    with pytest.raises(fe.Stufe2Gesperrt):
        fe.stufe2_setzen("entwurf", True, "t")
    assert fe.stufe2_lesen()["entwurf"] is False
    fe.stufe2_setzen("entwurf", False, "t")
    assert fe.stufe2_lesen()["entwurf"] is False


def test_stufe2_lesen_ignoriert_gespeichertes_true():
    server._q("insert into einstellungen (schluessel, wert, geaendert_von) values "
              "('freigabe_stufe2', %s, 'sql') returning schluessel",
              (json.dumps({"entwurf": True, "debugger_pr": True,
                           "selbstbild_rueckfrage": False, "kursfreigabe": False}),))
    assert not any(fe.stufe2_lesen().values())
    fe.stufe2_setzen("debugger_pr", False, "t")
    roh = server._q("select wert from einstellungen where schluessel = 'freigabe_stufe2'")
    assert True not in roh[0]["wert"].values()


LABEL = {"repo": "r", "nummer": 1, "label": "antwort:weg"}


def test_auftrag_unbekannter_oder_geschlossener_eintrag():
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen("fg-aaaaaaaaaa", "selbstbild_label", LABEL, "ui")
    k, _ = fe.eintragen("selbstbild", "selbstbild_rueckfrage", "r#2", "t")
    fe.schliessen_kennung(k, "verworfen", "ui")
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")


def test_auftrag_art_passt_nicht_zum_eintrag():
    k = _debugger()
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "kurs_freigabe_zeigen", {"course_id": "c"}, "ui")


@pytest.mark.parametrize("nutzlast", [
    {"repo": "r", "nummer": 1, "label": "antwort:anders"},
    {"repo": "r", "nummer": "1", "label": "antwort:weg"},
    {"repo": 5, "nummer": 1, "label": "antwort:weg"},
    {"repo": "r", "nummer": 1},
    {"repo": "r", "nummer": 1, "label": "antwort:weg", "extra": 1},
    "text",
])
def test_auftrag_label_nutzlast_falsch(nutzlast):
    k, _ = fe.eintragen("selbstbild", "selbstbild_rueckfrage", "r#3", "t")
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "selbstbild_label", nutzlast, "ui")


@pytest.mark.parametrize("nutzlast", [{}, {"course_id": 7}, {"course_id": "c", "x": 1}])
def test_auftrag_kurs_nutzlast_falsch(nutzlast):
    k, _ = fe.eintragen("werkstatt", "kursfreigabe", "kurs-9", "t")
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "kurs_freigabe_zeigen", nutzlast, "ui")


def test_auftrag_kein_duplikat_bei_doppelklick():
    k, _ = fe.eintragen("selbstbild", "selbstbild_rueckfrage", "r#4", "t")
    fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")
    fe.auftraege_abholen("selbstbild")  # laeuft noch: weiterhin gesperrt
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")


def test_auftrag_nach_fehler_wieder_moeglich():
    k, a = _label_auftrag()
    fe.auftraege_abholen("selbstbild")
    fe.auftrag_ergebnis(a, "selbstbild", False, "kaputt")
    assert fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")


def test_kein_uuid_und_kaputte_kennung():
    assert fe.auftrag_ergebnis("kein-uuid", "selbstbild", True, None) is False
    assert fe.auftrag_ergebnis(None, "selbstbild", True, None) is False
    assert fe.auftrag_ergebnis(str(uuid.uuid4()), "selbstbild", True, None) is False
    assert fe.schliessen_kennung("x' or 1=1", "erledigt", "ui") is False
    assert fe.schliessen_kennung(None, "erledigt", "ui") is False
    with pytest.raises(fe.EingabeFehler):
        fe.auftrag_anlegen("kaputt", "selbstbild_label", LABEL, "ui")


def test_letzte_auftraege_je_eintrag():
    k = fe.eintragen("werkstatt", "kursfreigabe", "k-1", "Kurs", None, {"course_id": "c"})[0]
    assert fe.letzte_auftraege() == {}
    fe.auftrag_anlegen(k, "kurs_freigabe_zeigen", {"course_id": "c"}, "mira")
    z = fe.letzte_auftraege()
    assert list(z.values()) == [{"status": "offen", "fehler": None}]
    fe.schliessen_kennung(k, "verworfen", "mira")
    assert fe.letzte_auftraege() == {}


def test_auftrag_wettlauf_index_entscheidet(monkeypatch):
    """Final-Review I3/Zeile 14: zwei Klicks sehen beide keinen offenen Auftrag; der
    partielle Unique-Index weist den zweiten ab, mit derselben EingabeFehler-Meldung."""
    k, _ = fe.eintragen("selbstbild", "selbstbild_rueckfrage", "r#5", "t")
    fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")
    echt = server._q

    def ohne_wache(sql, params=()):
        if sql.startswith("insert into freigabe_auftraege"):  # Wache sieht den ersten nicht
            sql, params = sql.split(" where not exists")[0] + " returning id", params[:5]
        return echt(sql, params)
    monkeypatch.setattr(server, "_q", ohne_wache)
    with pytest.raises(fe.EingabeFehler, match="schon ein Auftrag"):
        fe.auftrag_anlegen(k, "selbstbild_label", LABEL, "ui")
    monkeypatch.undo()
    assert len(server._q("select 1 from freigabe_auftraege")) == 1


def test_erneute_meldung_frischt_offenen_eintrag_auf():
    """Final-Review M5: Titel, Details und Link der neuen Meldung; Kennung und Stand bleiben."""
    k, _ = fe.eintragen("debugger-claw", "debugger_pr", PR, "alt", LINK, {"tests": "1 failed"})
    fe.rowboat_stand_setzen(k, "angenommen")
    k2, neu = fe.eintragen("debugger-claw", "debugger_pr", PR, "neu\ntitel", LINK + "/2",
                           {"tests": "4 passed"})
    z = _zeile(k)
    assert (k2, neu) == (k, False)
    assert (z["titel"], z["details"], z["link"]) == ("neu titel", {"tests": "4 passed"}, LINK + "/2")
    assert z["rowboat_stand"] == "angenommen" and z["status"] == "offen"
    fe.eintragen("debugger-claw", "debugger_pr", PR, "ohne link")  # kein Link: alter bleibt
    fe.eintragen("debugger-claw", "debugger_pr", PR, "kaputter link", "javascript:x")
    z = _zeile(k)
    assert (z["titel"], z["details"], z["link"]) == ("kaputter link", {}, LINK + "/2")
    assert len(server._q("select 1 from freigabe_eintraege")) == 1


def test_erneute_meldung_laesst_geschlossenen_eintrag():
    k, _ = fe.eintragen("debugger-claw", "debugger_pr", PR, "alt", LINK)
    fe.schliessen_kennung(k, "verworfen", "ui")
    k2, neu = fe.eintragen("debugger-claw", "debugger_pr", PR, "neu", LINK)
    assert neu is True and k2 != k and _zeile(k)["titel"] == "alt"