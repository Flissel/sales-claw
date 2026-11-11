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


def _nachricht(lead, text="Angebot", tag="2098-12-20"):
    """Gesendete WhatsApp-Nachricht (kein Mailinhalt: der bleibt aus dem Briefing)."""
    server._q("insert into drafts (lead_id, channel, recipient, body, status, sent_at) "
              "values (%s, 'whatsapp', '+4915112345678', %s, 'sent', %s) returning id",
              (lead, text, tag + " 09:00+00"))


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
    _nachricht(lead, "Angebot bAV")
    server._wiedervorlage_anlegen(lead, datetime(2099, 1, 20).date(), "Unterlagen schicken")
    _alte_akte(lead, "alt-1")
    # Form aus Task 10: {"zitat", "zeit", "sprecher"}; tolerant auch str / {"text"}
    _auswertung("alt-1", [{"zitat": "Zu teuer", "zeit": "01:02", "sprecher": "Kunde"},
                          {"text": "Kein Zeit"}, "Nur Text", 5, {"x": 1}])
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
    assert {p["text"] for p in l["painpoints"]} == {"Zu teuer", "Kein Zeit", "Nur Text"}
    assert all(p["datum"] == "2098-12-01" for p in l["painpoints"])
    assert f["ziel"]["thema"] == "Beratung bAV"
    assert f["beginn"].startswith("2099-01-10T09:00")
    md = briefing.fakten_markdown(f)
    for kopf in ("## Wer", "## Letzte Kontakte", "## Offen",
                 "## Painpoints aus früheren Gesprächen", "## Ziel"):
        assert kopf in md
    assert "Karla Kunde" in md and "- „Zu teuer“ (01.12.2098)" in md


def test_leere_abschnitte_strich():
    uid = _akte(_lead())
    md = briefing.fakten_markdown(briefing.fakten(uid))
    assert "## Offen\n—" in md
    assert "## Painpoints aus früheren Gesprächen\n—" in md


def test_painpoints_max_8_und_nur_fertige():
    lead = _lead()
    uid = _akte(lead)
    _alte_akte(lead, "alt-1")
    _auswertung("alt-1", [{"zitat": f"p{i}", "zeit": "00:01", "sprecher": "K"}
                          for i in range(12)])
    _alte_akte(lead, "alt-2", beginn="2098-11-01 09:00+00")
    _auswertung("alt-2", [{"zitat": "nicht fertig", "zeit": "00:01", "sprecher": "K"}],
                status="offen")
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

    def chat(system, nutzer, *, als_json=False, timeout_s=None):
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
    _nachricht(lead, "Neue Nachricht")
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


# --- Fix-Runde 1 ---------------------------------------------------------

@pytest.mark.parametrize("titel", ["Call kunde@firma.de", "Rückruf +49 30 1234567",
                                   "Tel (030) 123 45 67 wegen bAV"])
def test_hinweis_titel_ohne_adresse_und_telefon(titel):
    akte = _akte_dict(lead=None)
    akte["titel"] = titel
    akte["thema"] = None
    text = briefing.hinweis_text(akte, "https://ui.example")
    assert len(text.split("\n")) == 4
    assert "@" not in text and "firma.de" not in text
    assert not re.search(r"\d[\d ()+-]{5,}\d", text.split("\n")[0] + text.split("\n")[1])
    assert "1234567" not in text.replace(" ", "")


def test_hinweis_nur_adresse_im_titel_wird_neutral():
    akte = _akte_dict(lead=None)
    akte["titel"], akte["thema"] = "kunde@firma.de", None
    zeilen = briefing.hinweis_text(akte, "https://ui.example").split("\n")
    assert zeilen[0] == "🗓 10:00 Kundentermin" and zeilen[1] == "Kundentermin"


def test_hinweis_firma_und_url_im_thema_bereinigt():
    lead = _lead(firma="Firma +49 30 1234567 GmbH")
    akte = _akte_dict(lead=lead)
    akte["thema"] = "Siehe https://zoom.us/j/123456789?pwd=abc bAV"
    text = briefing.hinweis_text(akte, "https://ui.example")
    zeilen = text.split("\n")
    assert len(zeilen) == 4
    assert "1234567" not in zeilen[0] and "zoom" not in zeilen[1] and "bAV" in zeilen[1]


def test_hinweis_gesperrter_erster_lead_neutral():
    lead = _lead("gesperrt@firma.de", "Gesperrt Person", "Sperr GmbH")
    server._lead_sperren(lead, "test", "test")
    akte = _akte_dict(lead=lead)
    akte["titel"] = "Gesperrt Person Besprechung"
    akte["thema"] = None
    text = briefing.hinweis_text(akte, "https://ui.example")
    assert len(text.split("\n")) == 4
    assert text.split("\n")[0] == "🗓 10:00 Kundentermin"
    assert "Gesperrt" not in text.split("\n")[0] and "Sperr GmbH" not in text


def test_stand_stabil_bei_gleichem_datum(monkeypatch):
    lead = _lead()
    uid = _akte(lead)
    gleich = datetime(2098, 12, 20, 9, 0, tzinfo=timezone.utc)
    eintraege = [{"datum": gleich, "art": "entwurf", "kanal": "email", "text": f"Betreff {i}"}
                 for i in range(8)]
    monkeypatch.setattr(briefing, "kontakt_historie", lambda *a, **k: list(eintraege))
    a = briefing.erstellen(uid)
    monkeypatch.setattr(briefing, "kontakt_historie", lambda *a, **k: list(reversed(eintraege)))
    b = briefing.erstellen(uid)
    assert a["stand"] == b["stand"] and a["markdown"] == b["markdown"]
    assert len(briefing.fakten(uid)["leads"][0]["letzte_kontakte"]) == 5


def test_beschreibung_ohne_link_und_passcode():
    uid = _akte(_lead())
    server._q("update termin_akten set beschreibung = %s where uid = %s returning uid",
              ("Agenda: Angebot bAV besprechen\n"
               "Zoom beitreten: https://zoom.us/j/12345678901?pwd=GEHEIMPWD\n"
               "Meeting-ID: 123 4567 8901\nKenncode: 987654\n"
               "Einwahl: +49 69 1234 5678\nBesprechungs-ID: 555 666 777\n"
               "Dial-in Telefon 069 12345678\nBitte Unterlagen mitbringen\n"
               "Nummer 12345678901 im Text", uid))
    f = briefing.fakten(uid)
    md = briefing.fakten_markdown(f)
    b = f["ziel"]["beschreibung"]
    assert "Angebot bAV" in b and "Unterlagen" in b
    for geheim in ("zoom", "GEHEIMPWD", "987654", "8901", "1234 5678", "555 666", "12345678"):
        assert geheim.lower() not in md.lower(), geheim


def test_ki_text_gekappt_und_ohne_ueberschriften(monkeypatch):
    uid = _akte(_lead())
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: "## Wer\n### Offen\nSatz. " + "x" * 3000)
    md = briefing.erstellen(uid)["markdown"]
    kurz = md.split("\n\n")[0]
    assert kurz.startswith("## Kurz\n")
    assert len(kurz) <= len("## Kurz\n") + 1200
    assert "\n## Wer\n" not in kurz and "### " not in kurz
    # die echten Faktenabschnitte bleiben genau einmal
    assert md.count("\n## Wer\n") == 1


def test_log_ohne_kundentext_bei_ollama_fehler(caplog, monkeypatch):
    lead = _lead()
    uid = _akte(lead)

    def kaputt(*a, **k):
        raise ollama.OllamaFehler("Karla Kunde kunde@firma.de Firma GmbH")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", kaputt)
    with caplog.at_level(logging.DEBUG):
        r = briefing.erstellen(uid)
    assert r["mit_ki"] is False
    assert any("ohne KI-Text" in x.message for x in caplog.records)
    for geheim in (ADRESSE, "Karla", "Firma GmbH", "Beratung"):
        assert geheim not in caplog.text


# --- Final-Review --------------------------------------------------------

def test_i11_mailbetreff_nicht_im_briefing():
    lead = _lead()
    uid = _akte(lead)
    _mail(lead, "GEHEIMBETREFF Gehaltsliste")
    _nachricht(lead, "Whatsapp sichtbar")
    md = briefing.erstellen(uid)["markdown"]
    assert "GEHEIMBETREFF" not in md and "Gehaltsliste" not in md
    assert "Whatsapp sichtbar" in md


def _mit_gesperrtem(uid):
    gesperrt = _lead("gesperrt@firma.de", "Gesperrt Person", "Sperr GmbH")
    server._q("update termin_akten set titel = 'Gespräch mit Gesperrt Person', "
              "thema = 'Gesperrt Person Vertrag', beschreibung = 'Gesperrt Person bringt Vertrag' "
              "where uid = %s returning uid", (uid,))
    server._q("insert into termin_teilnehmer (uid, adresse, rolle, lead_id, grund) "
              "values (%s, 'gesperrt@firma.de', 'gast', null, 'gesperrt') returning uid", (uid,))
    server._lead_sperren(gesperrt, "test", "test")


def test_i4_hinweis_mit_gesperrtem_teilnehmer_neutral():
    uid = _akte(_lead())
    _mit_gesperrtem(uid)
    text = briefing.hinweis_text(termin_akte.lesen(uid), "https://ui.example")
    zeilen = text.split("\n")
    assert zeilen[0] == "🗓 10:00 Kundentermin" and zeilen[1] == "Kundentermin"
    for geheim in ("Gesperrt", "Sperr GmbH", "Vertrag", "Karla", "Firma GmbH"):
        assert geheim not in text, geheim


def test_i4_briefing_fakten_neutral_bei_gesperrtem_teilnehmer():
    uid = _akte(_lead())
    _mit_gesperrtem(uid)
    f = briefing.fakten(uid)
    assert f["ziel"] == {"thema": "Kundentermin", "beschreibung": ""}
    md = briefing.erstellen(uid)["markdown"]
    assert "Gesperrt" not in md and "Vertrag" not in md
    assert "Karla Kunde" in md          # der freie Kontakt bleibt im Briefing


MEET_EINLADUNG = (
    "Agenda: bAV-Angebot durchgehen. Mit Google Meet teilnehmen: "
    "https://meet.google.com/abc-defg-hij Oder telefonisch teilnehmen: (DE) +49 30 300195061 "
    "PIN: 123 456 789# Weitere Telefonnummern: https://tel.meet/abc-defg-hij?pin=123 "
    "Bitte Unterlagen mitbringen.")
TEAMS_EINLADUNG = (
    "Bitte vorab das Angebot lesen.\n" + "_" * 80 + "\nMicrosoft Teams-Besprechung\n"
    "Nehmen Sie auf Ihrem Computer, in der mobilen App oder auf einem Raumgerät teil\n"
    "Klicken Sie hier, um an der Besprechung teilzunehmen "
    "<https://teams.microsoft.com/l/meetup-join/19%3ameeting_x/0>\n"
    "Besprechungs-ID: 312 456 789 012\nKenncode: aB3cD4\n"
    "Weitere Informationen<https://aka.ms/JoinTeamsMeeting> | "
    "Besprechungsoptionen<https://teams.microsoft.com/meetingOptions/>\n" + "_" * 80)


def test_beschreibung_meet_einladung_einzeilig_bleibt():
    b = briefing._beschreibung(MEET_EINLADUNG, 400)
    assert "Agenda: bAV-Angebot durchgehen." in b and "Bitte Unterlagen mitbringen." in b
    for weg in ("meet.google", "tel.meet", "https", "300195061", "123 456", "PIN",
                "teilnehmen", "Telefonnummern"):
        assert weg not in b, weg


def test_beschreibung_teams_einladung_nur_eigener_text():
    assert briefing._beschreibung(TEAMS_EINLADUNG, 400) == "Bitte vorab das Angebot lesen."


def test_beschreibung_bleibt_gekappt():
    b = briefing._beschreibung("Wort " * 300 + "https://meet.google.com/abc-defg-hij", 50)
    assert len(b) <= 50 and b.startswith("Wort")


def test_log_uid_nur_als_hash(caplog, monkeypatch):
    import hashlib
    uid = _akte(_lead(), uid="uid-sehr-geheim")

    def kaputt(*a, **k):
        raise ollama.OllamaFehler("weg")
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", kaputt)
    with caplog.at_level(logging.DEBUG):
        briefing.erstellen(uid)
    assert "uid-sehr-geheim" not in caplog.text
    assert hashlib.sha256(uid.encode()).hexdigest()[:8] in caplog.text


def test_i7c_briefing_mit_eigenem_zeitlimit(monkeypatch):
    uid = _akte(_lead())
    gesehen = []
    monkeypatch.delenv("OLLAMA_BRIEFING_TIMEOUT_S", raising=False)
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(ollama, "chat", lambda s, n, **k: gesehen.append(k) or "Text.")
    assert briefing.erstellen(uid)["mit_ki"] is True
    assert gesehen == [{"timeout_s": 60}]
