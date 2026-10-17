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


# --- Fix-Runde 1 (Review I1-I5) -------------------------------------------

def _kontakt(name="Anna Alt", telefon="+491701234567"):
    return server.json.loads(server.kontakt_anlegen(name, phone=telefon))["lead_id"]


def _einwilligungen(lid):
    return server._q("select payload from activities where lead_id=%s and "
                     "type='werbe_einwilligung' order by created_at", (lid,))


def test_fremde_einwilligung_wird_beim_abhaken_nicht_widerrufen():
    lid = _kontakt()
    server.einwilligung_erfassen(lid, "opt_in", "Messe-Formular")
    r = _anlegen()                                     # Liste ohne Einwilligung
    assert r["verknuepft"] == 1
    assert em.liste(r["liste_id"])["zeilen"][0]["einwilligung"] is False
    em.zeile_setzen(lid, einwilligung=True)            # schon opt_in: nichts buchen
    assert len(_einwilligungen(lid)) == 1
    aus = em.zeile_setzen(lid, einwilligung=False)
    assert _lead(lid)["consent_status"] == "opt_in"
    assert any("anderer Quelle" in h for h in aus["hinweise"])
    assert em.liste(r["liste_id"])["zeilen"][0]["einwilligung"] is False


def test_bestandskunde_bleibt_unberuehrt():
    lid = _kontakt()
    server.einwilligung_erfassen(lid, "existing_customer", "Vertrag 2024")
    r = _anlegen(einwilligung=True)
    assert _lead(lid)["consent_status"] == "existing_customer"
    assert len(_einwilligungen(lid)) == 1
    em.zeile_setzen(lid, einwilligung=False)
    assert _lead(lid)["consent_status"] == "existing_customer"
    assert r["verknuepft"] == 1


def test_frueherer_widerruf_bekommt_keine_empfehlungs_einwilligung():
    lid = _kontakt()
    server.einwilligung_erfassen(lid, "opt_in", "Formular")
    server.einwilligung_widerrufen(lid, "will nicht mehr")
    r = _anlegen(einwilligung=True)
    assert r["verknuepft"] == 1 and any("widerrufen" in h for h in r["hinweise"])
    assert _lead(lid)["consent_status"] == "unknown"
    assert em.liste(r["liste_id"])["zeilen"][0]["einwilligung"] is False
    aus = em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "unknown"
    assert any("widerrufen" in h for h in aus["hinweise"])


def test_eigener_haekchen_widerruf_sperrt_nicht():
    r = _anlegen(einwilligung=True)
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    q = _einwilligungen(lid)[0]["payload"]["quelle"]
    assert q.startswith("Empfehlung:") and r["liste_id"] in q
    em.zeile_setzen(lid, einwilligung=False)
    em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "opt_in"


def test_verbotsliste_und_loeschantrag_werden_nicht_verknuepft(monkeypatch):
    gesperrt = _kontakt()
    geloescht = _kontakt("Lea Loesch", "+491705555555")
    server._q("update leads set enrichment = enrichment || "
              "'{\"_loeschantrag\": {\"am\": \"2026-10-01\", \"quelle\": \"Telefonat\"}}'::jsonb "
              "where id=%s returning id", (geloescht,))
    monkeypatch.setattr(server, "_sperre", lambda email="", phone="":
                        "sales:widerruf: am Telefon" if phone == "+491701234567" else "")
    r = _anlegen(einwilligung=True,
                 zeilen=[Z(), Z(vorname="Lea", name="Loesch", telefon="+491705555555")])
    gruende = {a["zeile"]: a["grund"] for a in r["abgewiesen"]}
    assert "Verbotsliste" in gruende[1] and "Löschantrag" in gruende[2]
    assert r["verknuepft"] == 0 and r["neu"] == 0
    for lid in (gesperrt, geloescht):
        assert "empfehlung" not in (_lead(lid)["enrichment"] or {})
        assert _lead(lid)["consent_status"] == "unknown"


def test_fremde_zeile_nur_lesend_und_nicht_gezaehlt():
    r1 = _anlegen()
    lid = em.liste(r1["liste_id"])["zeilen"][0]["lead_id"]
    em.zeile_setzen(lid, ergebnis="abschluss", liste_id=r1["liste_id"])
    r2 = _anlegen(empfohlen_von_name="Zweiter", einwilligung=True)
    z2 = em.liste(r2["liste_id"])["zeilen"][0]
    assert z2["fremd"] is True and z2["fremd_liste_datum"] == date.today()
    assert em.liste(r1["liste_id"])["zeilen"][0]["fremd"] is False
    assert _lead(lid)["consent_status"] == "unknown"   # fremde Zeile bucht nichts
    zaehler = {l["id"]: l for l in em.listen()}
    assert zaehler[r1["liste_id"]]["abschluss"] == 1
    assert zaehler[r2["liste_id"]]["abschluss"] == 0
    assert zaehler[r2["liste_id"]]["anzahl"] == 1
    assert "fehler" in em.zeile_setzen(lid, ergebnis="offen", liste_id=r2["liste_id"])
    assert "fehler" not in em.zeile_setzen(lid, ergebnis="offen", liste_id=r1["liste_id"])


def test_datenbankfehler_je_zeile_wird_abgewiesen(monkeypatch):
    import psycopg

    def kaputt(*a, **kw):
        raise psycopg.OperationalError("weg")
    monkeypatch.setattr(server, "kontakt_anlegen", kaputt)
    r = _anlegen(zeilen=[Z(), Z(vorname="B", telefon="")])
    assert r["liste_id"] and r["neu"] == 0
    assert [a["zeile"] for a in r["abgewiesen"]] == [1, 2]
    assert all("Datenbankfehler" in a["grund"] for a in r["abgewiesen"])
    monkeypatch.setattr(server, "kontakt_anlegen",
                        lambda *a, **kw: server._json({"fehler": server.DB_FEHLER}))
    aus = em.zeile_hinzufuegen(r["liste_id"], Z(telefon=""))
    assert "Datenbankfehler" in aus["fehler"]


def test_fehler_beim_buchen_setzt_kein_haekchen(monkeypatch):
    r = _anlegen()
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    monkeypatch.setattr(server, "einwilligung_erfassen",
                        lambda *a, **kw: server._json({"fehler": "Datenbankfehler (X): weg"}))
    aus = em.zeile_setzen(lid, einwilligung=True)
    assert "fehler" in aus
    assert em.liste(r["liste_id"])["zeilen"][0]["einwilligung"] is False


# --- Fix-Runde 2 (N1: jede eigene Ablehnung blockiert) --------------------

def _blockiert_empfehlungs_einwilligung(lid):
    r = _anlegen(einwilligung=True)
    assert r["verknuepft"] == 1 and any("widerrufen" in h for h in r["hinweise"])
    assert _lead(lid)["consent_status"] == "unknown"
    assert em.liste(r["liste_id"])["zeilen"][0]["einwilligung"] is False
    aus = em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "unknown"
    assert any("widerrufen" in h for h in aus["hinweise"])


def test_newsletter_abmeldung_blockiert():
    lid = _kontakt()
    server._q("update leads set email='anna@example.com', consent_status='opt_in' "
              "where id=%s returning id", (lid,))
    assert server._newsletter_abmeldungen([{"betreff": "Abmelden", "von": "anna@example.com",
                                             "message_id": "m1@x"}]) == 1
    _blockiert_empfehlungs_einwilligung(lid)


def test_consent_kontakt_nein_blockiert():
    lid = _kontakt()
    server.bedarf_speichern(lid, "consent_kontakt", "nein, bitte nicht")
    _blockiert_empfehlungs_einwilligung(lid)


def test_consent_kontakt_ja_blockiert_nicht():
    lid = _kontakt()
    server.bedarf_speichern(lid, "consent_kontakt", "ja gern")
    server._q("update leads set consent_status='unknown' where id=%s returning id", (lid,))
    r = _anlegen(einwilligung=True)
    assert _lead(lid)["consent_status"] == "opt_in" and r["verknuepft"] == 1


def test_widerruf_mit_empfehlungs_praefix_aber_anderem_text_blockiert():
    lid = _kontakt()
    server.einwilligung_erfassen(lid, "opt_in", "Formular")
    server.einwilligung_widerrufen(lid, "Empfehlung: Kontakt will nicht")
    _blockiert_empfehlungs_einwilligung(lid)


def test_haken_grund_ist_exakt_und_listenbezogen():
    r = _anlegen(einwilligung=True)
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    em.zeile_setzen(lid, einwilligung=False)
    g = server._q("select payload->>'grund' g from activities where lead_id=%s and "
                  "type='werbe_einwilligung_widerrufen'", (lid,))[0]["g"]
    assert g == f"Empfehlung: Häkchen entfernt [Liste {r['liste_id']}]"
    em.zeile_setzen(lid, einwilligung=True)
    assert _lead(lid)["consent_status"] == "opt_in"


def test_gefaelschtes_tag_im_namen_zaehlt_nicht():
    lid = _kontakt()
    andere = _anlegen(empfohlen_von_name="Erste")["liste_id"]   # Heimatliste des Kontakts
    server.einwilligung_erfassen(
        lid, "opt_in", f"Empfehlung: vorab gefragt von X [Liste {andere}] (Liste 01.01.2026) "
                       f"[Liste 00000000-0000-0000-0000-000000000000]")
    aus = em.zeile_setzen(lid, einwilligung=True)
    aus = em.zeile_setzen(lid, einwilligung=False)
    assert _lead(lid)["consent_status"] == "opt_in"
    assert any("anderer Quelle" in h for h in aus["hinweise"])


import io as _io  # noqa: E402
from pypdf import PdfReader  # noqa: E402


def _pdf_text(b):
    return "".join(s.extract_text() for s in PdfReader(_io.BytesIO(b)).pages)


def test_pdf_pole_position_quer_mit_kopf_und_spalten():
    r = _anlegen(art="pole_position", bereiche=["vorsorge"],
                 zeilen=[Z(vorname="Jörg", name="Müßig <script>", ort="München")])
    b = em.pdf(r["liste_id"])
    seiten = PdfReader(_io.BytesIO(b)).pages
    assert len(seiten) == 1 and seiten[0].mediabox.width > seiten[0].mediabox.height
    t = _pdf_text(b)
    for s in ("Pole Position", "Konzept für den Aufbau von Empfehlungen", "Name", "Vorname",
              "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis", "Felix", "Team Nord",
              "Klaus Kunde", "Jörg", "München", "offen"):
        assert s in t, s


def test_pdf_mitarbeitervorschlaege_spalten_und_folgeseite():
    r = _anlegen(zeilen=[Z(vorname=f"P{i}", telefon="") for i in range(25)])
    em.zeile_hinzufuegen(r["liste_id"], Z(vorname="Nummer26", telefon=""))
    b = em.pdf(r["liste_id"])
    assert len(PdfReader(_io.BytesIO(b)).pages) == 2
    t = _pdf_text(b)
    for s in ("Mitarbeitervorschläge", "Alter (ab 22)", "Was zeichnet aus", "Was interessiert",
              "Nummer26"):
        assert s in t, s


def test_pdf_unbekannt():
    assert em.pdf("00000000-0000-0000-0000-000000000000") is None


def test_pdf_fremde_zeile_zeigt_schon_bekannt():
    r1 = _anlegen(art="pole_position", bereiche=["vorsorge"])
    lid = em.liste(r1["liste_id"])["zeilen"][0]["lead_id"]
    em.zeile_setzen(lid, ergebnis="abschluss", liste_id=r1["liste_id"])
    r2 = _anlegen(art="pole_position", bereiche=["vorsorge"], empfohlen_von_name="Zweiter")
    assert em.liste(r2["liste_id"])["zeilen"][0]["fremd"] is True
    t = _pdf_text(em.pdf(r2["liste_id"]))
    assert "schon bekannt" in t and "Anna" in t
    assert "schon bekannt" not in _pdf_text(em.pdf(r1["liste_id"]))


def test_pdf_langer_text_wird_nie_still_abgeschnitten():
    lang = " ".join(f"Wort{i}" for i in range(25))[:150]
    r = _anlegen(zeilen=[Z(vorname=f"P{i}", telefon="", zeichnet_aus=lang) for i in range(25)])
    t = _pdf_text(em.pdf(r["liste_id"]))
    assert lang in t.replace("\n", " ") or "..." in t


def test_pdf_folgeseite_nummeriert_weiter():
    r = _anlegen(zeilen=[Z(vorname=f"P{i}", telefon="") for i in range(25)])
    em.zeile_hinzufuegen(r["liste_id"], Z(vorname="Nummer26", telefon=""))
    seiten = PdfReader(_io.BytesIO(em.pdf(r["liste_id"]))).pages
    assert "26." in seiten[1].extract_text()


import inspect  # noqa: E402


def test_werkzeuge_registriert():
    for f, p in ((server.empfehlungsliste_anlegen,
                  ["art", "empfohlen_von", "datum", "zeilen", "einwilligung", "bereiche",
                   "berater_name", "struktur"]),
                 (server.empfehlungslisten_zeigen, ["liste_id"])):
        assert f in server.WERKZEUGE
        assert list(inspect.signature(f).parameters) == p


def test_werkzeug_empfohlen_von_lead_oder_name():
    geber = json.loads(server.kontakt_anlegen("Klaus Kunde", phone="+491705555555"))["lead_id"]
    r = json.loads(server.empfehlungsliste_anlegen("mitarbeitervorschlaege", geber, HEUTE,
                                                   [Z()], False))
    k = em.liste(r["liste_id"])["kopf"]
    assert k["empfohlen_von_lead"] == geber and k["empfohlen_von_name"] == "Klaus Kunde"
    r2 = json.loads(server.empfehlungsliste_anlegen("pole_position", "Frau Nachbarin", HEUTE,
                                                    [Z(telefon="")], True, ["immobilien"],
                                                    "Felix", "Nord"))
    assert em.liste(r2["liste_id"])["kopf"]["empfohlen_von_lead"] is None
    z = json.loads(server.empfehlungslisten_zeigen())
    assert len(z["listen"]) == 2
    d = json.loads(server.empfehlungslisten_zeigen(r2["liste_id"]))
    assert d["kopf"]["empfohlen_von_name"] == "Frau Nachbarin" and len(d["zeilen"]) == 1
