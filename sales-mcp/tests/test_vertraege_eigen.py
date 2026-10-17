"""C2 Vertraege & Projekte (Spec 2026-10-17)."""
import inspect
import json
import os
from datetime import date, timedelta

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402
import vertraege as vt  # noqa: E402

MORGEN = (date.today() + timedelta(days=1)).isoformat()
SPAETER = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")


def _lead(enrichment=None):
    return str(server._q("insert into leads (name, enrichment) values ('Kunde K', %s::jsonb) "
                         "returning id", (json.dumps(enrichment or {}),))[0]["id"])


def _offene_wv(lead):
    return server._q(
        "select w.id::text id, w.payload from activities w where w.lead_id=%s and "
        "w.type='wiedervorlage' and not exists (select 1 from activities e where "
        "e.type='wiedervorlage_erledigt' and e.payload->>'wiedervorlage_id'=w.id::text)", (lead,))


@pytest.mark.parametrize("ein,aus", [("1.200,50", "1200.50"), ("1200,5", "1200.50"),
                                     ("€ 99", "99.00"), ("0", "0.00"), ("", ""),
                                     ("viel", None), ("-5", None), ("1,234", "1.23"),
                                     ("2.500", "2500.00"), ("1.234.567", "1234567.00"),
                                     ("2.5", "2.50"), ("12.50", "12.50"),
                                     ("0.500", "0.50"), ("0.500.000", None)])
def test_betrag_norm(ein, aus):
    if aus == "1.23":       # mehr als 2 Nachkommastellen ist ein Fehler
        assert vt.betrag_norm(ein) is None
    else:
        assert vt.betrag_norm(ein) == aus


def test_eigen_anlegen_mit_wiedervorlage_und_bereich():
    lead = _lead()
    r = vt.speichern(lead, "eigen", "homelab", "NAS + Backup", status="abgeschlossen",
                     status_datum=date.today().isoformat(), anbieter="Synology",
                     betrag="1.499,00", wiedervorlage_am=SPAETER, notiz="Wartung jährlich")
    e = r["eintrag"]
    assert r["angelegt"] and e["art"] == "eigen" and e["betrag"] == "1499.00" and e["id"]
    wv = _offene_wv(lead)
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == SPAETER
    assert e["wiedervorlage_id"] == wv[0]["id"]
    enr = server._q("select enrichment from leads where id=%s", (lead,))[0]["enrichment"]
    assert "homelab" in enr["bereiche"]
    assert server._q("select count(*) n from activities where type='vertrag_angelegt'")[0]["n"] == 1


def test_aendern_quittiert_alte_wiedervorlage_und_beendet_quittiert():
    lead = _lead()
    e = vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", wiedervorlage_am=MORGEN)["eintrag"]
    vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", wiedervorlage_am=SPAETER,
                 eintrag_id=e["id"])
    wv = _offene_wv(lead)
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == SPAETER
    vt.speichern(lead, "eigen", "it", "Webshop", status="beendet", eintrag_id=e["id"])
    assert _offene_wv(lead) == []
    assert len(vt.eintraege(lead)) == 1
    assert server._q("select count(*) n from activities where type='vertrag_geaendert'")[0]["n"] == 2


@pytest.mark.parametrize("kw", [dict(art="kunde"), dict(bereich="rente"), dict(status="fertig"),
                                dict(betrag="viel"), dict(wiedervorlage_am="2020-01-01"),
                                dict(status_datum="gestern"), dict(bezeichnung=""),
                                dict(bezeichnung="x" * 201), dict(eintrag_id="unbekannt")])
def test_ungueltig(kw):
    lead = _lead()
    a = dict(art="eigen", bereich="bav", bezeichnung="bAV Allianz")
    a.update(kw)
    assert "fehler" in vt.speichern(lead, **a)
    assert vt.eintraege(lead) == []


def test_altform_wird_normalisiert_und_kaputtes_ignoriert():
    lead = _lead({"vertraege": [{"sparte": "KFZ", "gesellschaft": "HUK", "ablauf": "2027-01-01"},
                                "kaputt", {"notiz": "nur notiz"}]})
    es = vt.eintraege(lead)
    assert es[0]["art"] == "fremd" and es[0]["bezeichnung"] == "KFZ" and es[0]["anbieter"] == "HUK"
    assert len(es) == 2
    assert vt.eintraege_aus({"vertraege": "kein array"}) == []
    assert vt.eintraege_aus(None) == []


def test_grenze_50_und_sperren(monkeypatch):
    lead = _lead()
    for i in range(50):
        assert "fehler" not in vt.speichern(lead, "eigen", "it", f"P{i}")
    assert "fehler" in vt.speichern(lead, "eigen", "it", "zuviel")
    privat = _lead({"_privat": {"privat": True}})
    assert "fehler" in vt.speichern(privat, "eigen", "it", "x")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", lead)
    assert "fehler" in vt.speichern(lead, "eigen", "it", "y")


def test_vertrag_speichern_schreibt_id_und_art_und_profil_zeigt_beides():
    lead = _lead()
    json.loads(server.vertrag_speichern(lead, "KFZ", gesellschaft="HUK"))
    json.loads(server.abschluss_speichern(lead, "vorsorge", "Rürup", "angeboten"))
    p = json.loads(server.profil_lesen(lead))
    arten = sorted(v["art"] for v in p["vertraege"])
    assert arten == ["eigen", "fremd"] and all(v["id"] for v in p["vertraege"])


def test_werkzeug_registriert_und_signatur():
    assert server.abschluss_speichern in server.WERKZEUGE
    assert list(inspect.signature(server.abschluss_speichern).parameters) == [
        "lead_id", "bereich", "bezeichnung", "status", "status_datum", "anbieter", "betrag",
        "wiedervorlage_am", "notiz", "eintrag_id"]


def test_altform_behaelt_sparte_und_gesellschaft_beim_zurueckschreiben():
    """Uebergabe, UI-Kontaktseite und vertraege_ablaufend lesen sparte/
    gesellschaft — ein Rueckschreiben durch speichern darf sie nicht tilgen."""
    lead = _lead({"vertraege": [{"sparte": "KFZ", "gesellschaft": "HUK", "ablauf": "2027-01-01"}]})
    vt.speichern(lead, "eigen", "it", "Webshop")
    roh = server._q("select enrichment->'vertraege' v from leads where id=%s", (lead,))[0]["v"]
    alt = next(v for v in roh if v["art"] == "fremd")
    assert alt["sparte"] == "KFZ" and alt["gesellschaft"] == "HUK" and alt["ablauf"] == "2027-01-01"


def test_uebergabe_und_ablaufend_vertragen_eigene_eintraege():
    lead = _lead()
    server.vertrag_speichern(lead, "KFZ", ablauf=SPAETER, gesellschaft="HUK")
    vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", anbieter="Ich")
    ab = json.loads(server.vertraege_ablaufend(tage=90))
    assert [z["sparte"] for z in ab["vertraege"]] == ["KFZ"]
    text = json.loads(server.uebergabe_erstellen(lead))["text"]
    abschnitt = text.split("## Vertraege")[1].split("\n## ")[0]
    assert "KFZ (HUK)" in abschnitt and "Webshop" in abschnitt and "?" not in abschnitt


# --- Fix-Runde 1 (Review task-1, Rulings I1-I3) ---

def test_i1_altform_id_stabil_und_aenderbar_ohne_dublette():
    lead = _lead({"vertraege": [{"sparte": "KFZ", "gesellschaft": "HUK", "ablauf": "2027-01-01",
                                 "erfasst": "2026-01-02"}]})
    a, b = vt.eintraege(lead), vt.eintraege(lead)
    assert a[0]["id"] and a[0]["id"] == b[0]["id"]
    r = vt.speichern(lead, "fremd", "", "KFZ", anbieter="HUK24", eintrag_id=a[0]["id"], quelle="ui")
    assert "fehler" not in r and r["angelegt"] is False
    es = vt.eintraege(lead)
    assert len(es) == 1 and es[0]["id"] == a[0]["id"] and es[0]["anbieter"] == "HUK24"
    roh = server._q("select enrichment->'vertraege' v from leads where id=%s", (lead,))[0]["v"]
    assert roh[0]["id"] == a[0]["id"] and roh[0]["ablauf"] == "2027-01-01"
    # fremd bleibt fuer vertraege_ablaufend/Uebergabe lesbar
    assert roh[0]["sparte"] == "KFZ" and roh[0]["gesellschaft"] == "HUK24"


def test_i1_gleiche_altform_eintraege_bekommen_verschiedene_ids():
    v = {"sparte": "KFZ", "gesellschaft": "HUK"}
    es = vt.eintraege_aus({"vertraege": [dict(v), dict(v)]})
    assert es[0]["id"] != es[1]["id"]


def test_i2_abschluss_speichern_lehnt_fremden_eintrag_ab():
    lead = _lead()
    server.vertrag_speichern(lead, "KFZ", gesellschaft="HUK")
    fid = vt.eintraege(lead)[0]["id"]
    r = json.loads(server.abschluss_speichern(lead, "it", "KFZ", "abgeschlossen", eintrag_id=fid))
    assert r["fehler"] == "Fremder Vertrag — als fremd pflegen (vertrag_speichern bzw. Kontaktseite)."
    assert vt.eintraege(lead)[0]["art"] == "fremd"
    eid = vt.speichern(lead, "eigen", "it", "Webshop")["eintrag"]["id"]
    r2 = vt.speichern(lead, "fremd", "", "Webshop", eintrag_id=eid, quelle="ui")
    assert "Eigener" in r2["fehler"]


def test_i3_agent_nur_status_behaelt_rest():
    lead = _lead()
    e = vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", anbieter="Ich",
                     betrag="500", wiedervorlage_am=SPAETER, notiz="wichtig")["eintrag"]
    json.loads(server.abschluss_speichern(lead, "", "", "abgeschlossen", eintrag_id=e["id"]))
    n = vt.eintraege(lead)[0]
    assert (n["status"], n["betrag"], n["notiz"], n["anbieter"], n["bereich"], n["bezeichnung"]) == \
        ("abgeschlossen", "500.00", "wichtig", "Ich", "it", "Webshop")
    wv = _offene_wv(lead)
    assert len(wv) == 1 and wv[0]["id"] == e["wiedervorlage_id"] == n["wiedervorlage_id"]


def test_i3_unveraenderte_vergangene_wiedervorlage_ist_kein_fehler():
    lead = _lead()
    e = vt.speichern(lead, "eigen", "it", "Webshop", wiedervorlage_am=MORGEN)["eintrag"]
    gestern = (date.today() - timedelta(days=1)).isoformat()
    with server.pool.connection() as conn:
        conn.execute("update sales_test.leads set enrichment = jsonb_set(enrichment, "
                     "'{vertraege,0,wiedervorlage_am}', to_jsonb(%s::text)) where id=%s",
                     (gestern, lead))
    r = vt.speichern(lead, "eigen", "", "", status="in_arbeit", wiedervorlage_am=gestern,
                     eintrag_id=e["id"])
    assert "fehler" not in r
    assert len(_offene_wv(lead)) == 1
    assert "fehler" in vt.speichern(lead, "eigen", "it", "Neu", wiedervorlage_am=gestern)


def test_i3_ui_ersetzt_vollstaendig_und_quittiert_bei_datum_weg():
    lead = _lead()
    e = vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", betrag="500",
                     wiedervorlage_am=SPAETER, quelle="ui")["eintrag"]
    vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", betrag="",
                 wiedervorlage_am=SPAETER, eintrag_id=e["id"], quelle="ui")
    n = vt.eintraege(lead)[0]
    assert n["betrag"] == "" and len(_offene_wv(lead)) == 1 and n["wiedervorlage_id"] == e["wiedervorlage_id"]
    vt.speichern(lead, "eigen", "it", "Webshop", status="in_arbeit", eintrag_id=e["id"], quelle="ui")
    assert _offene_wv(lead) == [] and vt.eintraege(lead)[0]["wiedervorlage_am"] == ""


def test_abschluss_speichern_versteht_tausenderpunkt():
    lead = _lead()
    r = json.loads(server.abschluss_speichern(lead, "it", "Webshop", "angeboten", betrag="2.500"))
    assert "fehler" not in r
    assert vt.eintraege(lead)[0]["betrag"] == "2500.00"


# --- Schluss-Fix: fremde Eintraege tragen keinen Status (Spec §2.1) --------

def test_fremd_erzwingt_leeren_status_und_ordnet_nie_ein(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(server, "_einordnen", lambda *a, **kw: aufrufe.append((a, kw)))
    lead = _lead()
    r = vt.speichern(lead, "fremd", "homelab", "KFZ", status="abgeschlossen",
                     status_datum=date.today().isoformat(), anbieter="HUK")
    e = r["eintrag"]
    assert (e["status"], e["status_datum"]) == ("", "")
    assert aufrufe == []
    gespeichert = vt.eintraege(lead)[0]
    assert (gespeichert["status"], gespeichert["status_datum"]) == ("", "")
    # Auch ueber die Kontaktseite (quelle='ui') und beim Aendern
    r2 = vt.speichern(lead, "fremd", "homelab", "KFZ", status="abgeschlossen",
                      status_datum=date.today().isoformat(), eintrag_id=e["id"], quelle="ui")
    assert (r2["eintrag"]["status"], r2["eintrag"]["status_datum"]) == ("", "")
    assert aufrufe == []


def test_fremd_altstatus_wird_beim_agenten_merge_geleert(monkeypatch):
    monkeypatch.setattr(server, "_einordnen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError))
    lead = _lead({"vertraege": [{"id": "f1", "art": "fremd", "bezeichnung": "KFZ",
                                 "status": "abgeschlossen", "status_datum": "2026-01-01",
                                 "bereich": "homelab"}]})
    r = vt.speichern(lead, "fremd", "", "", notiz="neu", eintrag_id="f1")
    assert (r["eintrag"]["status"], r["eintrag"]["status_datum"]) == ("", "")
