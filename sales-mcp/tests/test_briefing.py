"""Briefing: Faktenteil, KI-Kurztext, Hinweistext (Meeting-Mittelpunkt Task 9)."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import briefing  # noqa: E402
import mail_dispatch  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402
import teilnehmer  # noqa: E402
import termin_akte  # noqa: E402

JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
MEET = "https://meet.google.com/abc-defg-hij"
UID = "sc-1"
# Adresse, die in keinem Hinweis/Log erscheinen darf
ADRESSE = "kunde@firma.de"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "")
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "")
    monkeypatch.setattr(teilnehmer.postfach, "IMAP_USER", "")
    monkeypatch.setattr(ollama, "erreichbar", lambda: False)
    yield


def _lead(email=ADRESSE, name="Karla Kunde", firma="Firma GmbH", titel="Leiterin Einkauf"):
    return str(server._q(
        "insert into leads (name, email, company, title, source) "
        "values (%s, %s, %s, %s, 'Messe') returning id",
        (name, email, firma, titel))[0]["id"])


def _akte(lead, uid=UID, datum="2099-01-10", uhrzeit="10:00"):
    payload = {"datum": datum, "uhrzeit": uhrzeit, "thema": "Beratung bAV", "ort": MEET,
               "uid": uid}
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s::jsonb) "
              "returning id", (lead, json.dumps(payload)))
    termin_akte.abgleichen(JETZT)
    return uid


def _mail(lead, betreff="Angebot", tag="2098-12-20"):
    server._q("insert into drafts (lead_id, channel, recipient, subject, body, status, sent_at) "
              "values (%s, 'email', %s, %s, 'Text', 'sent', %s) returning id",
              (lead, ADRESSE, betreff, tag + " 09:00+00"))


def _auswertung(uid, painpoints, am="2098-12-01 10:00+00", status="fertig"):
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am) values (%s, '[]'::jsonb, %s, %s::jsonb, %s) "
              "returning id", (uid, status, json.dumps({"painpoints": painpoints}), am))


def _alte_akte(lead, uid, beginn="2098-12-01 09:00+00"):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel) "
              "values (%s, 'kalender', %s, %s::timestamptz + interval '1 hour', 'Alt') "
              "returning uid", (uid, beginn, beginn))
    server._q("insert into termin_teilnehmer (uid, adresse, rolle, lead_id) "
              "values (%s, %s, 'gast', %s) returning uid", (uid, ADRESSE, lead))


def test_fakten_inhalt():
    lead = _lead()
    uid = _akte(lead)
    _mail(lead, "Angebot bAV")
    server._wiedervorlage_anlegen(lead, datetime(2099, 1, 20).date(), "Unterlagen schicken")
    _alte_akte(lead, "alt-1")
    _auswertung("alt-1", ["Zu teuer", {"text": "Kein Zeit"}, 5, {"x": 1}])
    f = briefing.fakten(uid)
    assert len(f["leads"]) == 1
    l = f["leads"][0]
    assert (l["name"], l["rolle"], l["firma"], l["quelle"]) == (
        "Karla Kunde", "Leiterin Einkauf", "Firma GmbH", "Messe")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", l["erster_kontakt"])
    assert any("Angebot bAV" in k["text"] for k in l["letzte_kontakte"])
    assert len(l["letzte_kontakte"]) <= 5
    assert l["offene_wiedervorlagen"] == [{"faellig_am": "2099-01-20",
                                          "notiz": "Unterlagen schicken"}]
    assert {p["text"] for p in l["painpoints"]} == {"Zu teuer", "Kein Zeit"}
    assert all(p["datum"] == "2098-12-01" for p in l["painpoints"])
    assert f["ziel"]["thema"] == "Beratung bAV"
    assert f["beginn"].startswith("2099-01-10T09:00")
    md = briefing.fakten_markdown(f)
    for kopf in ("## Wer", "## Letzte Kontakte", "## Offen",
                 "## Painpoints aus früheren Gesprächen", "## Ziel"):
        assert kopf in md
    assert "Karla Kunde" in md and "Zu teuer" in md


def test_leere_abschnitte_strich():
    uid = _akte(_lead())
    md = briefing.fakten_markdown(briefing.fakten(uid))
    assert "## Offen\n—" in md
    assert "## Painpoints aus früheren Gesprächen\n—" in md


def test_painpoints_max_8_und_nur_fertige():
    lead = _lead()
    uid = _akte(lead)
    _alte_akte(lead, "alt-1")
    _auswertung("alt-1", [f"p{i}" for i in range(12)])
    _alte_akte(lead, "alt-2", beginn="2098-11-01 09:00+00")
    _auswertung("alt-2", ["nicht fertig"], status="offen")
    pp = briefing.fakten(uid)["leads"][0]["painpoints"]
    assert len(pp) == 8
    assert "nicht fertig" not in {p["text"] for p in pp}


def test_ohne_ollama_nur_fakten(monkeypatch):
    uid = _akte(_lead())
    monkeypatch.setattr(ollama, "erreichbar", lambda: False)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: pytest.fail("chat bei nicht erreichbar"))
    r = briefing.erstellen(uid)
    assert r["mit_ki"] is False
    assert "_ohne KI-Text_" in r["markdown"]
    assert "## Kurz" not in r["markdown"]


def test_mit_ollama_kurztext(monkeypatch):
    uid = _akte(_lead())
    aufrufe = []

    def chat(system, nutzer, *, als_json=False):
        aufrufe.append((system, nutzer))
        return "  Erster Satz. Zweiter Satz.  "
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", chat)
    r = briefing.erstellen(uid)
    assert r["mit_ki"] is True
    assert r["markdown"].startswith("## Kurz\nErster Satz. Zweiter Satz.\n")
    assert "_ohne KI-Text_" not in r["markdown"]
    assert aufrufe[0][0] == ("Du bereitest Felix auf ein Kundengespräch vor. Antworte auf "
                             "Deutsch in 3–5 Sätzen, nur aus den gegebenen Fakten, nichts erfinden.")
    assert aufrufe[0][1] == briefing.fakten_markdown(briefing.fakten(uid))


@pytest.mark.parametrize("antwort", ["", "  \n "])
def test_ollama_leere_antwort_faellt_zurueck(monkeypatch, antwort):
    uid = _akte(_lead())
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: antwort)
    r = briefing.erstellen(uid)
    assert r["mit_ki"] is False and "_ohne KI-Text_" in r["markdown"]


def test_ollama_fehler_faellt_zurueck(monkeypatch):
    uid = _akte(_lead())

    def kaputt(*a, **k):
        raise ollama.OllamaFehler("weg")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", kaputt)
    r = briefing.erstellen(uid)
    assert r["mit_ki"] is False and "_ohne KI-Text_" in r["markdown"]


def test_stand_aendert_sich_mit_neuer_mail(monkeypatch):
    lead = _lead()
    uid = _akte(lead)
    a = briefing.erstellen(uid)["stand"]
    assert briefing.erstellen(uid)["stand"] == a  # deterministisch
    _mail(lead, "Neue Mail")
    b = briefing.erstellen(uid)["stand"]
    assert b != a
    # KI-Text aendert den Stand nicht
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: "Text")
    assert briefing.erstellen(uid)["stand"] == b


@pytest.mark.parametrize("wie", ["sperrliste", "loeschantrag", "privat"])
def test_gesperrter_lead_fehlt(wie):
    frei = _lead("frei@firma.de", "Frei Mensch", "Freie AG")
    gesperrt = _lead("gesperrt@firma.de", "Gesperrt Person", "Sperr GmbH")
    uid = _akte(frei)
    server._q("insert into termin_teilnehmer (uid, adresse, rolle, lead_id) "
              "values (%s, 'gesperrt@firma.de', 'gast', %s) returning uid", (uid, gesperrt))
    assert len(briefing.fakten(uid)["leads"]) == 2
    if wie == "sperrliste":
        server._lead_sperren(gesperrt, "test", "test")
    elif wie == "loeschantrag":
        server._q("update leads set enrichment = %s::jsonb where id = %s returning id",
                  (json.dumps({"_loeschantrag": {"am": "2099-01-01", "quelle": "t"}}), gesperrt))
    else:
        server._q("update leads set enrichment = %s::jsonb where id = %s returning id",
                  (json.dumps({"_privat": {"privat": True}}), gesperrt))
    f = briefing.fakten(uid)
    assert [l["name"] for l in f["leads"]] == ["Frei Mensch"]
    md = briefing.erstellen(uid)["markdown"]
    assert "Gesperrt Person" not in md and "Sperr GmbH" not in md
    assert "gesperrt@firma.de" not in md


def _akte_dict(uid=UID, lead=None, link=MEET):
    return {"uid": uid, "titel": "Termin Kunde", "thema": "Beratung bAV",
            "beginn": datetime(2099, 1, 10, 9, 0, tzinfo=timezone.utc),
            "zeitzone": "Europe/Berlin",
            "beitreten": {"link": link, "plattform": "google_meet",
                          "passcode": "GEHEIM123", "einwahl": "+49 30 1234567"},
            "teilnehmer": [{"name": "Karla Kunde", "adresse": ADRESSE, "rolle": "gast",
                            "lead_id": lead, "grund": None}]}


def test_hinweis_nur_vier_zeilen_ohne_adressen():
    lead = _lead()
    akte = _akte_dict("a#b@c/d", lead)
    text = briefing.hinweis_text(akte, "https://ui.example")
    zeilen = text.split("\n")
    assert zeilen == ["🗓 10:00 Karla Kunde (Firma GmbH)", "Beratung bAV",
                      "Briefing öffnen: https://ui.example/termine/a%23b%40c%2Fd",
                      f"Beitreten: {MEET}"]
    assert "@" not in text.replace("%40", "") and "GEHEIM123" not in text
    assert "1234567" not in text and ADRESSE not in text
    assert not re.search(r"\+?\d[\d ]{6,}", text)


def test_hinweis_ohne_link_und_ohne_lead():
    akte = _akte_dict(lead=None, link=None)
    zeilen = briefing.hinweis_text(akte, "https://ui.example").split("\n")
    assert len(zeilen) == 3
    assert zeilen[0] == "🗓 10:00 Termin Kunde"


def test_hinweis_zeit_in_zeitzone_sommer():
    akte = _akte_dict()
    akte["beginn"] = datetime(2099, 7, 10, 8, 0, tzinfo=timezone.utc)
    assert briefing.hinweis_text(akte, "x").startswith("🗓 10:00 ")


def test_log_ohne_kundendaten(caplog):
    lead = _lead()
    uid = _akte(lead)
    _mail(lead, "Geheimer Betreff")
    with caplog.at_level(logging.DEBUG):
        briefing.erstellen(uid)
        briefing.hinweis_text(termin_akte.lesen(uid), "https://ui.example")
    log = caplog.text
    for geheim in (ADRESSE, "Karla", "Firma GmbH", "Geheimer Betreff", "Beratung"):
        assert geheim not in log
