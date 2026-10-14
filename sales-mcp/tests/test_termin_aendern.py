"""Vertragstests fuer `termin_aendern` und `kunde_benachrichtigen`
(Spec 2026-10-14 §1.2): Kundentermin aendern/absagen und den Kunden per
pending-Entwurf benachrichtigen. Versendet wird nie etwas."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import mail_dispatch  # noqa: E402  (nach `import server`, siehe test_termin_einladen)
import medien  # noqa: E402
import recherche  # noqa: E402


@pytest.fixture(autouse=True)
def leer(tmp_path, monkeypatch):
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(tmp_path / "erzeugt"))
    for name in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server, "belegungen", lambda tage_voraus=60: ([], []))
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "buero@vibemind.space")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    yield


def _tag(n=1):
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


def _lead_mail(name="Ivan Kunde", email="ivan@vibemind.space"):
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values (%s, %s, '+491701234567', 'whatsapp', 'existing_customer') "
        "returning id", (name, email))[0]["id"])


def _lead_whatsapp(name="Wanda Handy"):
    return str(server._q(
        "insert into leads (name, phone, source, consent_status, enrichment) "
        "values (%s, '+491701234568', 'whatsapp', 'existing_customer', "
        "%s::jsonb) returning id",
        (name, json.dumps({"whatsapp_freigabe": {"freigegeben": True}})))[0]["id"])


def _lead_ohne_kanal(name="Kai Stumm"):
    return str(server._q(
        "insert into leads (name, source, consent_status) "
        "values (%s, 'whatsapp', 'existing_customer') returning id",
        (name,))[0]["id"])


def _termin(lead, datum=None, uhrzeit="14:30", **kw):
    return json.loads(server.termin_bestaetigen(
        lead, datum or _tag(), uhrzeit, **kw))["termin"]


def _status(lead):
    return [z["status"] for z in server._q(
        "select status from drafts where lead_id = %s", (lead,))]


# --- termin_aendern ---------------------------------------------------------

def test_aendern_neue_uhrzeit_sagt_alt_ab_und_bestaetigt_neu():
    lead = _lead_mail()
    alt = _termin(lead, uhrzeit="14:30", ort="Buero")
    r = json.loads(server.termin_aendern(lead, alt["uid"], uhrzeit="16:00"))
    assert "fehler" not in r, r
    assert r["uid_neu"] and r["uid_neu"] != alt["uid"]
    assert r["termin"]["uhrzeit"] == "16:00"
    assert r["termin"]["ort"] == "Buero"
    assert r["verschoben_von"]["uid"] == alt["uid"]
    assert server._termin_abgesagt(lead, alt["uid"])
    assert server._termin_zeile(lead, r["uid_neu"]) is not None
    assert not server._termin_abgesagt(lead, r["uid_neu"])


def test_aendern_nur_ort_behaelt_uhrzeit():
    lead = _lead_mail()
    alt = _termin(lead, uhrzeit="14:30", ort="Buero")
    r = json.loads(server.termin_aendern(lead, alt["uid"], ort="Cafe Mitte"))
    assert "fehler" not in r, r
    assert r["termin"]["uhrzeit"] == "14:30"
    assert r["termin"]["datum"] == alt["datum"]
    assert r["termin"]["ort"] == "Cafe Mitte"


def test_aendern_ohne_aenderung():
    lead = _lead_mail()
    alt = _termin(lead, ort="Buero")
    r = json.loads(server.termin_aendern(lead, alt["uid"]))
    assert r == {"fehler": "Nichts geändert."}
    assert not server._termin_abgesagt(lead, alt["uid"])


def test_aendern_gleiche_werte_zaehlen_nicht_als_aenderung():
    lead = _lead_mail()
    alt = _termin(lead, uhrzeit="14:30")
    r = json.loads(server.termin_aendern(lead, alt["uid"], uhrzeit="14:30"))
    assert r == {"fehler": "Nichts geändert."}


def test_aendern_unbekannte_und_abgesagte_uid():
    lead = _lead_mail()
    assert "fehler" in json.loads(server.termin_aendern(lead, "x@y", ort="a"))
    alt = _termin(lead)
    server.termin_absagen(lead, alt["uid"], "test")
    assert "abgesagt" in json.loads(
        server.termin_aendern(lead, alt["uid"], ort="a"))["fehler"]


def test_aendern_ist_kein_agent_werkzeug():
    assert server.termin_aendern not in server.WERKZEUGE


# --- kunde_benachrichtigen --------------------------------------------------

def _payload(tag, uhrzeit="14:30", **kw):
    return {"datum": tag, "uhrzeit": uhrzeit, "dauer_minuten": 60,
            "thema": "Beratung", "ort": "", "uid": "x", **kw}


def test_mail_mit_bestehender_einladung_wird_fortgeschrieben():
    lead = _lead_mail()
    tag = _tag()
    e = json.loads(server.termin_einladen(lead, tag, "14:30", thema="Beratung"))
    assert "fehler" not in e, e
    r = server.kunde_benachrichtigen(
        lead, _payload(tag), _payload(tag, "16:00", uid="neu"))
    assert r.get("kanal") == "email" and r.get("draft_id"), r
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'einladung_entworfen' order by (payload->>'folge')::int", (lead,))
    assert len(zeilen) == 2
    assert zeilen[1]["payload"]["uid"] == zeilen[0]["payload"]["uid"] == e["uid"]
    assert zeilen[1]["payload"]["folge"] == 1
    assert zeilen[1]["payload"]["uhrzeit"] == "16:00"
    d = server._q("select * from drafts where id = %s", (r["draft_id"],))[0]
    assert d["status"] == "pending"
    assert str(d.get("media_ref") or "").endswith(".ics"), d


def test_mail_ohne_einladung_neue_einladung_folge_0():
    lead = _lead_mail()
    tag = _tag()
    r = server.kunde_benachrichtigen(
        lead, _payload(tag), _payload(tag, "16:00", uid="b"))
    assert r.get("kanal") == "email", r
    z = server._q("select payload from activities where lead_id = %s and "
                  "type = 'einladung_entworfen'", (lead,))
    assert len(z) == 1 and z[0]["payload"]["folge"] == 0
    assert _status(lead) == ["pending"]


def test_whatsapp_text_nennt_neuen_tag_und_uhrzeit():
    lead = _lead_whatsapp()
    tag = _tag(3)
    r = server.kunde_benachrichtigen(
        lead, _payload(_tag()), _payload(tag, "16:15", ort="Cafe Mitte"))
    assert r.get("kanal") == "whatsapp" and r.get("draft_id"), r
    d = server._q("select * from drafts where id = %s", (r["draft_id"],))[0]
    t = datetime.fromisoformat(tag)
    text = str(d.get("body") or d.get("text") or d)
    assert server.WOCHENTAGE[t.weekday()] in text and f"{t:%d.%m.}" in text
    assert "16:15" in text and "Cafe Mitte" in text
    assert d["status"] == "pending"


def test_absage_per_mail_ist_text_entwurf_mit_grund():
    lead = _lead_mail()
    r = server.kunde_benachrichtigen(
        lead, _payload(_tag()), None, grund="Krankheit")
    assert r.get("kanal") == "email", r
    d = server._q("select * from drafts where id = %s", (r["draft_id"],))[0]
    assert "Termin abgesagt: Beratung" in str(d.get("subject") or d)
    text = str(d.get("body") or d.get("text") or d)
    assert "Krankheit" in text and "14:30" in text
    assert not d.get("media_ref")
    assert d["status"] == "pending"


def test_kein_kanal_gibt_hinweis_ohne_entwurf():
    lead = _lead_ohne_kanal()
    r = server.kunde_benachrichtigen(lead, _payload(_tag()), None, grund="x")
    assert r == {"hinweis": "kein Kanal zum Kunden – bitte selbst Bescheid geben"}
    assert _status(lead) == []


# --- Terminbezug statt Betreiber-Auftrag (Final-Review I1, Ruling 14.10.) -----
# Eine Terminnachricht aus der Oberflaeche passiert das UWG-Erstansprache-Tor,
# bucht aber KEINE Werbe-Einwilligung: consent_status bleibt, wie er war.

def _lead_ohne_grundlage_mail(name="Uwe Unbekannt"):
    return str(server._q(
        "insert into leads (name, email, source) "
        "values (%s, 'uwe@example.org', 'whatsapp') returning id",
        (name,))[0]["id"])


def _lead_ohne_grundlage_whatsapp(name="Wilma Unbekannt"):
    return str(server._q(
        "insert into leads (name, phone, source, enrichment) "
        "values (%s, '+491701239999', 'whatsapp', %s::jsonb) returning id",
        (name, json.dumps({"whatsapp_freigabe": {"freigegeben": True}})))[0]["id"])


def _grundlage(lead):
    status = server._q("select consent_status from leads where id = %s",
                       (lead,))[0]["consent_status"]
    gebucht = server._q("select 1 from activities where lead_id = %s "
                        "and type = 'werbe_einwilligung'", (lead,))
    return status, bool(gebucht)


def test_terminbezug_mail_aenderung_ohne_einwilligung_bucht_nichts():
    lead = _lead_ohne_grundlage_mail()
    tag = _tag()
    r = server.kunde_benachrichtigen(
        lead, _payload(tag), _payload(tag, "16:00", uid="n"))
    assert r.get("kanal") == "email" and r.get("draft_id"), r
    assert _status(lead) == ["pending"]
    assert _grundlage(lead) == ("unknown", False)


def test_terminbezug_mail_absage_ohne_einwilligung_bucht_nichts():
    lead = _lead_ohne_grundlage_mail()
    r = server.kunde_benachrichtigen(lead, _payload(_tag()), None, grund="x")
    assert r.get("kanal") == "email" and r.get("draft_id"), r
    assert _status(lead) == ["pending"]
    assert _grundlage(lead) == ("unknown", False)


def test_terminbezug_whatsapp_ohne_einwilligung_bucht_nichts():
    lead = _lead_ohne_grundlage_whatsapp()
    r = server.kunde_benachrichtigen(
        lead, _payload(_tag()), _payload(_tag(2), "16:00"))
    assert r.get("kanal") == "whatsapp" and r.get("draft_id"), r
    assert _status(lead) == ["pending"]
    assert _grundlage(lead) == ("unknown", False)


def test_terminbezug_verbotsliste_sperrt_weiter(monkeypatch):
    monkeypatch.setattr(server, "_sperre", lambda email="", phone="": "Abmeldung")
    for lead, neu in ((_lead_ohne_grundlage_mail(), _payload(_tag(), "16:00")),
                      (_lead_ohne_grundlage_mail("Ulla"), None),
                      (_lead_ohne_grundlage_whatsapp(), _payload(_tag(), "16:00"))):
        r = server.kunde_benachrichtigen(lead, _payload(_tag()), neu, grund="x")
        assert "Verbotsliste" in r.get("fehler", ""), r
        assert _status(lead) == []
        assert _grundlage(lead) == ("unknown", False)


def test_terminbezug_ersetzt_keine_kontakt_freigabe():
    # WhatsApp nicht freigegeben, keine Mail: kein Entwurf, nur Hinweis.
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "('Nora Nichtfrei', '+491701238888', 'whatsapp') returning id")[0]["id"])
    r = server.kunde_benachrichtigen(lead, _payload(_tag()), None, grund="x")
    assert r == {"hinweis": "kein Kanal zum Kunden – bitte selbst Bescheid geben"}
    assert _grundlage(lead) == ("unknown", False)


def test_ohne_terminbezug_bleibt_das_tor_zu():
    lead = _lead_ohne_grundlage_mail()
    assert "fehler" in json.loads(server.entwurf_erstellen(lead, "email", "Hallo"))
    assert _grundlage(lead) == ("unknown", False)


def test_terminbezug_ist_kein_parameter_der_agent_werkzeuge():
    import inspect
    for fn in server.WERKZEUGE:
        assert "termin_bezug" not in inspect.signature(fn).parameters, fn.__name__
    assert "termin_bezug" in inspect.signature(server._termin_einladen).parameters
