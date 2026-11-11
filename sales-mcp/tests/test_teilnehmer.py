"""Teilnehmer klassifizieren und mit dem CRM verknuepfen (Meeting-Mittelpunkt Task 4)."""
import logging
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mail_dispatch  # noqa: E402
import server  # noqa: E402
import sperrliste  # noqa: E402
import teilnehmer  # noqa: E402

UID = "uid-teilnehmer-1"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_teilnehmer, sales_test.termin_akten, "
                     "sales_test.leads, sales_test.post_konten, "
                     "sales_test.kalender_konten cascade")
        conn.execute("truncate compliance_test.sperrliste")
        conn.execute("insert into sales_test.termin_akten (uid, herkunft, beginn, ende) "
                     "values (%s, 'kalender', now(), now() + interval '1 hour')", (UID,))
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "")
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "")
    monkeypatch.setattr(teilnehmer.postfach, "IMAP_USER", "")


def _t(adresse, name="", rolle="gast", art="individual"):
    return {"adresse": adresse, "name": name, "rolle": rolle, "art": art}


def _lead(email, enrichment="{}"):
    return str(server._q("insert into leads (name, email, enrichment) values ('X', %s, %s::jsonb) "
                         "returning id", (email, enrichment))[0]["id"])


def _anzahl_leads():
    return server._q("select count(*) as n from leads")[0]["n"]


def test_bekannter_gast_verknuepft():
    lid = _lead("kunde@firma.de")
    z = teilnehmer.verknuepfen(UID, [_t("Kunde@Firma.de")], darf_anlegen=True)
    assert str(z[0]["lead_id"]) == lid
    assert z[0]["grund"] is None
    assert _anzahl_leads() == 1


def test_unbekannter_gast_angelegt():
    z = teilnehmer.verknuepfen(UID, [_t("x@firma.de", name="Xaver")], darf_anlegen=True)
    lead = server._q("select * from leads where id = %s", (z[0]["lead_id"],))[0]
    assert lead["source"] == "aus Kalender"
    assert lead["consent_status"] == "unknown"
    assert lead["company"] == "Firma"
    assert lead["name"] == "Xaver"
    assert lead["enrichment"] == {"art": "kontakt", "aus_termin": UID}
    # idempotent: zweiter Aufruf findet den Lead, legt keinen zweiten an
    z2 = teilnehmer.verknuepfen(UID, [_t("x@firma.de", name="Xaver")], darf_anlegen=True)
    assert z2[0]["lead_id"] == z[0]["lead_id"]
    assert _anzahl_leads() == 1
    assert server._q("select count(*) as n from termin_teilnehmer")[0]["n"] == 1


def test_name_faellt_auf_localpart():
    z = teilnehmer.verknuepfen(UID, [_t("max.muster@firma.de")], darf_anlegen=True)
    name = server._q("select name from leads where id=%s", (z[0]["lead_id"],))[0]["name"]
    assert name == "max.muster"


def test_freemail_ohne_firma():
    z = teilnehmer.verknuepfen(UID, [_t("x@gmail.com")], darf_anlegen=True)
    firma = server._q("select company from leads where id=%s", (z[0]["lead_id"],))[0]["company"]
    assert not firma
    assert teilnehmer.firma_aus_domain("k@mueller-bau.de") == "Mueller-bau"
    assert teilnehmer.firma_aus_domain("k@web.de") == ""


def test_nicht_angelegt_ohne_erlaubnis():
    z = teilnehmer.verknuepfen(UID, [_t("x@firma.de")], darf_anlegen=False)
    assert z[0]["lead_id"] is None and z[0]["grund"] == "private Quelle"
    assert _anzahl_leads() == 0


def test_eigene_adresse_nicht_angelegt(monkeypatch):
    server._q("insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
              "values ('felix', 'haupt', 'namecheap', 'Felix@Haus.de', 'ui') returning id")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "Absender@haus.de")
    z = teilnehmer.verknuepfen(UID, [_t("felix@haus.de"), _t("absender@haus.de")],
                               darf_anlegen=True)
    assert [r["grund"] for r in z] == ["eigene Adresse", "eigene Adresse"]
    assert all(r["lead_id"] is None for r in z)
    assert _anzahl_leads() == 0


def test_team_adresse_nicht_angelegt(monkeypatch):
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "ivan@haus.de, Anna@haus.de")
    server._q("insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
              "values ('ivan', 'ivan-1', 'gmx', 'ivan2@haus.de', 'ui') returning id")
    z = teilnehmer.verknuepfen(UID, [_t("anna@haus.de"), _t("ivan2@haus.de")],
                               darf_anlegen=True)
    assert [r["grund"] for r in z] == ["Team", "Team"]
    assert _anzahl_leads() == 0
    assert {"anna@haus.de", "ivan@haus.de", "ivan2@haus.de"} <= teilnehmer.nicht_extern()


def test_gesperrte_adresse_nicht_angelegt():
    sperrliste.sperren(server._q, email="nein@firma.de", quelle="test", grund="abgemeldet")
    z = teilnehmer.verknuepfen(UID, [_t("nein@firma.de")], darf_anlegen=True)
    assert z[0]["grund"] == "gesperrt" and z[0]["lead_id"] is None
    assert _anzahl_leads() == 0


def test_loeschantrag_lead_nicht_verknuepft():
    _lead("weg@firma.de", '{"_loeschantrag": {"am": "2026-11-01", "quelle": "mail"}}')
    z = teilnehmer.verknuepfen(UID, [_t("weg@firma.de")], darf_anlegen=True)
    assert z[0]["lead_id"] is None and z[0]["grund"] == "gesperrt"
    assert teilnehmer.sperrgrund("weg@firma.de")
    assert _anzahl_leads() == 1


def test_privater_lead_nicht_verknuepft():
    _lead("p@firma.de", '{"_privat": {"privat": true}}')
    z = teilnehmer.verknuepfen(UID, [_t("p@firma.de")], darf_anlegen=True)
    assert z[0]["lead_id"] is None and z[0]["grund"] == "gesperrt"


def test_ressource_und_noreply():
    z = teilnehmer.verknuepfen(UID, [
        _t("raum@firma.de", art="room"),
        _t("noreply@firma.de"),
        _t("x@resource.calendar.google.com"),
        _t("y@group.calendar.google.com"),
    ], darf_anlegen=True)
    assert [r["grund"] for r in z] == ["Ressource"] * 4
    assert _anzahl_leads() == 0
    assert not teilnehmer.ist_ressource("anna@firma.de", "individual")


KUNDE = [_t("kunde@firma.de")]


@pytest.mark.parametrize("herkunft,bereich,liste,anzahl,erwartet", [
    ("sales-claw", "privat", [], 99, (True, "")),
    ("kalender", "privat", KUNDE, 2, (False, "private Quelle")),
    ("kalender", "business", KUNDE, 11, (False, "mehr als 10 Teilnehmer")),
    ("kalender", "business", [_t("felix@haus.de")], 1, (False, "keine externen Teilnehmer")),
    ("kalender", "business", [_t("ivan@haus.de")], 2, (False, "keine externen Teilnehmer")),
    ("kalender", "business", [_t("a@b.de")] * 3 + [_t("raum@f.de", art="room")], 30,
     (False, "mehr als 10 Teilnehmer")),
    ("kalender", "business", KUNDE + [_t("felix@haus.de")], 2, (True, "")),
])
def test_kundentermin_regeln(monkeypatch, herkunft, bereich, liste, anzahl, erwartet):
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@haus.de")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "ivan@haus.de")
    assert teilnehmer.ist_kundentermin(herkunft, bereich, liste, anzahl) == erwartet


def test_kein_log_mit_adresse(caplog, monkeypatch):
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@haus.de")
    sperrliste.sperren(server._q, email="nein@firma.de", quelle="test", grund="x")
    with caplog.at_level(logging.DEBUG):
        teilnehmer.verknuepfen(UID, [_t("geheim@firma.de", name="Gerda Geheim"),
                                     _t("felix@haus.de"), _t("nein@firma.de"),
                                     _t("raum@firma.de", art="room")], darf_anlegen=True)
        teilnehmer.ist_kundentermin("kalender", "business", [_t("geheim@firma.de")], 2)
    text = caplog.text.lower()
    assert "geheim" not in text and "firma.de" not in text and "haus.de" not in text
