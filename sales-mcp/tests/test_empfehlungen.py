"""Empfehlungslisten-Kern (Spec C4 §3/§4.1)."""
import json
import os
from datetime import date, timedelta

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import empfehlungen as em  # noqa: E402
import server  # noqa: E402

HEUTE = date.today().isoformat()


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.empfehlungslisten, sales_test.activities, "
                     "sales_test.drafts, sales_test.personas, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    monkeypatch.delenv("RECHERCHE_LEAD_ID", raising=False)


def Z(vorname="Anna", name="Beispiel", telefon="+491701234567", **kw):
    return {"vorname": vorname, "name": name, "telefon": telefon, **kw}


def _lead(lid):
    return server._q("select name, phone, consent_status, enrichment from leads where id=%s",
                     (lid,))[0]


def _anlegen(**kw):
    a = dict(art="mitarbeitervorschlaege", empfohlen_von_name="Klaus Kunde",
             datum=HEUTE, zeilen=[Z()], berater_name="Felix Baumann", struktur="Team Nord")
    a.update(kw)
    return em.liste_anlegen(**a)


def test_mitarbeitervorschlag_legt_kontakt_an_und_ordnet_ein():
    r = _anlegen(zeilen=[Z(beruf="Koch", alter=30, zeichnet_aus="zuverlässig",
                          interessiert="Selbstständigkeit")])
    assert r["neu"] == 1 and r["verknuepft"] == 0 and r["abgewiesen"] == []
    l = em.liste(r["liste_id"])
    z = l["zeilen"][0]
    assert z["name"] == "Anna Beispiel" and z["beruf"] == "Koch" and z["alter"] == 30
    assert z["ergebnis"] == "offen" and z["einwilligung"] is False
    e = _lead(z["lead_id"])["enrichment"]
    assert e["art"] == "person" and e["bereiche"] == ["mitarbeiter"]
    assert e["empfehlung"]["liste_id"] == r["liste_id"]
    assert l["kopf"]["berater_name"] == "Felix Baumann" and l["kopf"]["struktur"] == "Team Nord"


def test_pole_position_bereiche_und_firmenzeile():
    r = _anlegen(art="pole_position", bereiche=["vorsorge", "immobilien"],
                 zeilen=[Z(), Z(vorname="", name="Bäckerei Huber", telefon="+4989123456",
                              firma=True)])
    zs = {z["name"]: z for z in em.liste(r["liste_id"])["zeilen"]}
    p = _lead(zs["Anna Beispiel"]["lead_id"])["enrichment"]
    f = _lead(zs["Bäckerei Huber"]["lead_id"])["enrichment"]
    assert p["art"] == "person" and p["bereiche"] == ["vorsorge", "immobilien"]
    assert f["art"] == "firma" and f["bereiche"] == ["bav"]


def test_grenzen_und_pruefung_vor_dem_schreiben():
    assert "fehler" in _anlegen(art="pole_position", zeilen=[Z(telefon="")] * 16)
    r = _anlegen(zeilen=[Z(), Z(vorname="", name=""), Z()])
    assert "fehler" in r and "Zeile 2" in r["fehler"]
    r = _anlegen(zeilen=[Z(alter="ca. 30")])
    assert "fehler" in r and "Zeile 1" in r["fehler"]
    assert "fehler" in _anlegen(zeilen=[Z(beruf="x" * 201)])
    assert "fehler" in _anlegen(art="quatsch")
    assert "fehler" in _anlegen(empfohlen_von_name="")
    assert server._q("select count(*) n from leads")[0]["n"] == 0
    assert server._q("select count(*) n from empfehlungslisten")[0]["n"] == 0


def test_alter_unter_22_nur_hinweis():
    r = _anlegen(zeilen=[Z(alter=19)])
    assert r["neu"] == 1 and any("22" in h for h in r["hinweise"])


def test_kaputte_telefonnummer_zeile_ohne_telefon():
    r = _anlegen(zeilen=[Z(telefon="0171/ 23 45 x")])
    assert r["neu"] == 1 and any("Telefon" in h for h in r["hinweise"])
    assert _lead(em.liste(r["liste_id"])["zeilen"][0]["lead_id"])["phone"] is None


def test_dublette_verknuepft_privat_abgewiesen_doppelt_in_liste():
    alt = server.json.loads(server.kontakt_anlegen("Anna Alt", phone="+491701234567"))["lead_id"]
    privat = server._q("insert into leads (name, phone, enrichment) values ('Pia Privat', "
                       "'+491709999999', '{\"_privat\": {\"privat\": true}}') returning id")[0]["id"]
    r = _anlegen(zeilen=[Z(), Z(vorname="Pia", name="Privat", telefon="+491709999999"),
                         Z(vorname="Anna", name="Doppelt", telefon="+491701234567")])
    assert r["verknuepft"] == 1 and r["neu"] == 0
    gruende = {a["zeile"]: a["grund"] for a in r["abgewiesen"]}
    assert 2 in gruende and "privat" in gruende[2].lower()
    assert 3 in gruende and "doppelt" in gruende[3].lower()
    assert _lead(alt)["enrichment"]["empfehlung"]["liste_id"] == r["liste_id"]
    assert "empfehlung" not in (_lead(str(privat))["enrichment"] or {})


def test_fremde_empfehlung_bleibt():
    r1 = _anlegen()
    r2 = _anlegen(empfohlen_von_name="Zweiter")
    lid = em.liste(r1["liste_id"])["zeilen"][0]["lead_id"]
    assert _lead(lid)["enrichment"]["empfehlung"]["liste_id"] == r1["liste_id"]
    assert r2["verknuepft"] == 1
    assert [z["lead_id"] for z in em.liste(r2["liste_id"])["zeilen"]] == [lid]


def test_einwilligung_pro_liste_und_umstellen():
    r = _anlegen(einwilligung=True)
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    assert _lead(lid)["consent_status"] == "opt_in"
    q = server._q("select payload from activities where lead_id=%s and type='werbe_einwilligung'",
                  (lid,))
    assert "vorab gefragt von Klaus Kunde" in q[0]["payload"]["quelle"]
    em.zeile_setzen(lid, einwilligung=False)
    assert _lead(lid)["consent_status"] == "unknown"
    em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "opt_in"
    em.zeile_setzen(lid, einwilligung=True)            # nichts doppelt
    assert len(server._q("select 1 from activities where lead_id=%s and "
                         "type='werbe_einwilligung'", (lid,))) == 2


def test_kopf_vorbelegung_aus_letzter_liste():
    _anlegen()
    r = _anlegen(berater_name=None, struktur=None)
    k = em.liste(r["liste_id"])["kopf"]
    assert k["berater_name"] == "Felix Baumann" and k["struktur"] == "Team Nord"


def test_ergebnis_setzen_und_termin_wirkt():
    r = _anlegen()
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    assert "fehler" in em.zeile_setzen(lid, ergebnis="quatsch")
    em.zeile_setzen(lid, ergebnis="nicht_erreicht", notiz="AB besprochen")
    tag = (date.today() + timedelta(days=3)).isoformat()
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin',%s) "
              "returning id", (lid, json.dumps({"uid": "u1@x", "datum": tag, "uhrzeit": "10:00"})))
    z = em.liste(r["liste_id"])["zeilen"][0]
    assert z["ergebnis"] == "termin" and z["termin_datum"] == tag and z["notiz"] == "AB besprochen"
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin_abgesagt',%s) "
              "returning id", (lid, json.dumps({"uid": "u1@x"})))
    assert em.liste(r["liste_id"])["zeilen"][0]["ergebnis"] == "nicht_erreicht"
    em.zeile_setzen(lid, ergebnis="abschluss")
    assert em.listen()[0]["abschluss"] == 1


def test_zeile_hinzufuegen_bis_50():
    r = _anlegen()
    for i in range(49):
        assert "fehler" not in em.zeile_hinzufuegen(r["liste_id"], Z(vorname=f"N{i}",
                                                                    telefon=""))
    assert "fehler" in em.zeile_hinzufuegen(r["liste_id"], Z(vorname="zuviel", telefon=""))
    assert len(em.liste(r["liste_id"])["zeilen"]) == 50


def test_unbekannte_liste():
    assert em.liste("00000000-0000-0000-0000-000000000000") is None
    assert "fehler" in em.zeile_hinzufuegen("kaputt", Z())
