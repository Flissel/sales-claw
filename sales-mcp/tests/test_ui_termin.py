"""Termin-Seite /termine/{uid} und JSON (Meeting-Mittelpunkt Task 12).

Vexa ist per Monkeypatch ersetzt; die Datenbank ist sales_test. Die Akten
stehen direkt in der Tabelle."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import sperrliste  # noqa: E402
import termin_akte  # noqa: E402
import ui  # noqa: E402
import ui_termin  # noqa: E402
import vexa  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
MEET = "https://meet.google.com/abc-defg-hij"
ADRESSE = "kunde@firma.de"
PASSCODE = "PASS4711"
SEGMENT_TEXT = "GEHEIMTEXT zum Budget"
SEGMENTE = [{"sprecher": "Karla", "beginn": "2099-01-09T12:01:00Z",
             "text": SEGMENT_TEXT, "sprache": "de"}]
SONDER_UID = "abc@google.com#2026-11-12T09:00:00+00:00"


class FakeVexa:
    def __init__(self):
        self.aufrufe: list[tuple] = []
        self.fehler: Exception | None = None

    def bot_stoppen(self, plattform, native_id):
        self.aufrufe.append(("stoppen", plattform, native_id))
        if self.fehler:
            raise self.fehler

    def meeting_loeschen(self, mid):
        self.aufrufe.append(("loeschen", mid))
        if self.fehler:
            raise self.fehler


@pytest.fixture
def fake(monkeypatch):
    f = FakeVexa()
    monkeypatch.setattr(vexa, "bot_stoppen", f.bot_stoppen)
    monkeypatch.setattr(vexa, "meeting_loeschen", f.meeting_loeschen)
    return f


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    yield


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


# --- Helfer -----------------------------------------------------------------

def _akte(uid="u1", **spalten):
    beginn = spalten.pop("beginn", JETZT + timedelta(hours=5))
    werte = {"uid": uid, "herkunft": "sales-claw", "beginn": beginn,
             "ende": beginn + timedelta(hours=1), "titel": "Beratung",
             "thema": "Beratung bAV", "link": MEET, "plattform": "google_meet",
             "passcode": PASSCODE, "status": "geplant", **spalten}
    namen = list(werte)
    server._q(f"insert into termin_akten ({', '.join(namen)}) values "
              f"({', '.join(['%s'] * len(namen))}) returning uid",
              [werte[n] for n in namen])
    return uid


def _zeile(uid="u1"):
    return server._q("select * from termin_akten where uid = %s", (uid,))[0]


def _lead(email=ADRESSE, name="Karla Kunde", firma="Firma GmbH"):
    return str(server._q(
        "insert into leads (name, email, company, source) values (%s, %s, %s, 'Messe') "
        "returning id", (name, email, firma))[0]["id"])


def _teilnehmer(uid, lead=None, adresse=ADRESSE, grund=None, name="Karla Kunde"):
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id, grund) "
              "values (%s, %s, %s, 'gast', %s, %s) returning uid",
              (uid, adresse, name, lead, grund))


def _mitschrift(uid="u1", **spalten):
    werte = {"uid": uid, "segmente": json.dumps(SEGMENTE),
             "auswertung_status": "fertig", **spalten}
    namen = list(werte)
    marken = ["%s::jsonb" if n == "segmente" else "%s" for n in namen]
    return str(server._q(
        f"insert into termin_mitschriften ({', '.join(namen)}) values ({', '.join(marken)}) "
        "returning id", [werte[n] for n in namen])[0]["id"])


def _mit(uid="u1"):
    z = server._q("select * from termin_mitschriften where uid = %s", (uid,))
    return z[0] if z else None


def _vorschlag(mid, art, lead, daten):
    return str(server._q(
        "insert into termin_vorschlaege (mitschrift_id, art, lead_id, daten) "
        "values (%s, %s, %s, %s::jsonb) returning id",
        (mid, art, lead, json.dumps(daten)))[0]["id"])


def _vstatus(vid):
    return server._q("select status from termin_vorschlaege where id = %s", (vid,))[0]["status"]


def _pfad(uid):
    return f"/termine/{quote(uid, safe='')}"


def _get(pfad, client=CLIENT):
    return client.get(pfad, headers={"host": HOST_OK}, follow_redirects=False)


def _post(uid, aktion, csrf=True, client=CLIENT, **felder):
    daten = {"aktion": aktion, **felder}
    if csrf:
        daten["csrf"] = ui.CSRF_TOKEN
    return client.post(_pfad(uid), data=daten, headers={"host": HOST_OK},
                       follow_redirects=False)


def _hinweis(antwort) -> str:
    from urllib.parse import parse_qs, urlsplit
    code = parse_qs(urlsplit(antwort.headers["location"]).query).get("m", [""])[0]
    assert code == "" or code in ui_termin.MELDUNGEN
    return ui_termin.MELDUNGEN.get(code, "")


def _anmelden(name, rolle, passwort="termin-passwort-9"):
    import benutzer_anlegen
    assert benutzer_anlegen.anlegen(name, rolle, passwort).startswith("OK")
    client = TestClient(ui.app)
    antwort = client.post("/login", data={"name": name, "passwort": passwort,
                                          "csrf": ui.CSRF_TOKEN},
                          headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    return client


# --- Seite und JSON ---------------------------------------------------------

def test_seite_mit_beitreten_knopf():
    lead = _lead()
    _akte("u1", titel="Beratung <b>bAV</b>")
    _teilnehmer("u1", lead)
    a = _get(_pfad("u1"))
    assert a.status_code == 200
    assert f'<a class="knopf gross" href="{MEET}"' in a.text
    assert ">Beitreten</a>" in a.text
    assert "Karla Kunde (Firma GmbH)" in a.text
    assert "Beratung <b>bAV</b>" not in a.text and "Beratung &lt;b&gt;bAV&lt;/b&gt;" in a.text
    assert "Mitschrift-Bot: <b>geplant</b>" in a.text
    assert 'aria-label="Bereiche"' in a.text
    assert "min-height: 56px" in ui._STIL


def test_unbekannte_akte_404():
    assert _get(_pfad("gibts-nicht")).status_code == 404
    assert _get(_pfad("gibts-nicht") + ".json").status_code == 404


def test_beitreten_nur_fuer_http_links():
    _akte("u1", link="javascript:alert(1)")
    a = _get(_pfad("u1"))
    assert a.status_code == 200
    assert "javascript:" not in a.text and 'class="knopf gross"' not in a.text
    assert "Kein Beitritts-Link" in a.text


def test_status_mit_umlaut():
    _akte("u1", status="laeuft")
    _akte("u2", status="wartet_auf_einlass")
    assert "<b>läuft</b>" in _get(_pfad("u1")).text
    assert "<b>wartet auf Einlass</b>" in _get(_pfad("u2")).text


def test_json_gleich_wie_lesen():
    lead = _lead()
    _akte("u1")
    _teilnehmer("u1", lead)
    a = _get(_pfad("u1") + ".json")
    assert a.status_code == 200
    assert a.json() == json.loads(server._json(termin_akte.lesen("u1")))
    assert a.headers["cache-control"] == "no-store"


def test_uid_mit_sonderzeichen():
    _akte(SONDER_UID)
    h = _get(_pfad(SONDER_UID))
    assert h.status_code == 200 and ">Beitreten</a>" in h.text
    j = _get(_pfad(SONDER_UID) + ".json")
    assert j.status_code == 200 and j.json()["uid"] == SONDER_UID


def test_reiter_und_verlauf_mit_frueherer_akte():
    lead = _lead()
    _akte("u1")
    _akte("alt", beginn=JETZT - timedelta(days=30), titel="Erstgespraech")
    _teilnehmer("u1", lead)
    _teilnehmer("alt", lead)
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s) "
              "returning id", (lead, server._json({"datum": "2098-12-01", "uhrzeit": "10:00",
                                                    "thema": "Kennenlernen"})))
    a = _get(_pfad("u1") + "?reiter=verlauf")
    assert a.status_code == 200
    assert "Kennenlernen" in a.text
    assert f'href="{_pfad("alt")}"' in a.text and "Erstgespraech" in a.text
    assert 'aria-current="page">Verlauf' in a.text
    assert "Mitschrift</a>" not in a.text          # noch keine Mitschrift


def test_briefing_reiter_escaped():
    _akte("u1", briefing_md="## Kurz\n- Punkt <script>x</script>\n**fett**",
          briefing_mit_ki=False)
    a = _get(_pfad("u1") + "?reiter=briefing")
    assert "<script>x</script>" not in a.text
    assert "<h3>Kurz</h3>" in a.text and "<strong>fett</strong>" in a.text
    assert "&lt;script&gt;" in a.text


def test_mitschrift_reiter_erst_mit_mitschrift():
    _akte("u1", status="fertig")
    _mitschrift("u1", auswertung_md="## Ergebnis\n- alles gut")
    a = _get(_pfad("u1"))
    assert 'aria-current="page">Mitschrift' in a.text
    assert SEGMENT_TEXT in a.text and "alles gut" in a.text
    assert "Mitschrift verwerfen" in a.text


def test_knoepfe_je_status():
    _akte("lauf", status="laeuft")
    _akte("plan", status="geplant")
    _akte("fert", status="fertig")
    lauf, plan, fert = (_get(_pfad(u)).text for u in ("lauf", "plan", "fert"))
    assert "Ohne Aufnahme" in lauf and "Will Zusammenfassung" in lauf and "Kein Bot" not in lauf
    assert "Kein Bot" in plan and "Ohne Aufnahme" not in plan
    assert "Ohne Aufnahme" not in fert and "Kein Bot" not in fert


# --- Aktionen ---------------------------------------------------------------

def test_ohne_aufnahme_setzt_status_und_ueberlaesst_vexa_dem_taktgeber(fake):
    # C1: Die Oberflaeche spricht nie mit Vexa (sie hat keinen VEXA_API_KEY);
    # die Ids bleiben stehen, der Taktgeber stoppt den Bot und loescht.
    _akte("u1", status="laeuft", vexa_meeting_id=11, vexa_plattform="google_meet",
          vexa_native_id="abc-defg-hij")
    _mitschrift("u1")
    a = _post("u1", "ohne_aufnahme")
    assert a.status_code == 303 and a.headers["location"].startswith(_pfad("u1"))
    assert fake.aufrufe == []
    z = _zeile()
    assert z["status"] == "ohne_aufnahme" and z["status_grund"] == "Kunde hat abgelehnt"
    assert (z["vexa_meeting_id"], z["vexa_plattform"], z["vexa_native_id"]) == (
        11, "google_meet", "abc-defg-hij")
    assert _mit() is None
    assert _hinweis(a) == "Aufnahme beendet – der Bot verlässt den Termin in Kürze."
    assert "Aufnahme beendet – der Bot verlässt den Termin in Kürze." in _get(
        a.headers["location"]).text


def test_ohne_aufnahme_vexa_weg_trotzdem_status(fake):
    fake.fehler = vexa.VexaFehler("weg")
    _akte("u1", status="laeuft", vexa_meeting_id=11, vexa_plattform="google_meet",
          vexa_native_id="abc-defg-hij")
    _mitschrift("u1")
    assert _post("u1", "ohne_aufnahme").status_code == 303
    z = _zeile()
    assert z["status"] == "ohne_aufnahme"
    assert z["vexa_meeting_id"] == 11            # der Taktgeber loescht nach
    assert _mit() is None and fake.aufrufe == []


def test_will_zusammenfassung_schaltet_um():
    _akte("u1", status="laeuft")
    assert _zeile()["will_zusammenfassung"] is False
    _post("u1", "will_zusammenfassung")
    assert _zeile()["will_zusammenfassung"] is True
    _post("u1", "will_zusammenfassung")
    assert _zeile()["will_zusammenfassung"] is False


def test_kein_bot_vor_dem_termin_aenderbar():
    _akte("u1", status="geplant")
    _post("u1", "kein_bot")
    assert _zeile()["kein_bot"] is True
    _post("u1", "kein_bot")
    assert _zeile()["kein_bot"] is False


def test_kein_bot_nach_start_nicht_aenderbar():
    for status in ("wartet_auf_einlass", "laeuft", "fertig"):
        _akte(f"u-{status}", status=status)
        a = _post(f"u-{status}", "kein_bot")
        assert a.status_code == 303 and "nicht mehr" in _hinweis(a)
        assert _zeile(f"u-{status}")["kein_bot"] is False


def test_termin_ergebnis_kalendertermin_legt_terminzeile_an():
    lead = _lead()
    _akte("u1", herkunft="kalender", status="fertig")
    _teilnehmer("u1", lead)
    mid = _mitschrift("u1")
    vid = _vorschlag(mid, "termin_ergebnis", lead,
                     {"stattgefunden": True, "erfolg": False, "was": ""})
    a = _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    assert a.status_code == 303 and _hinweis(a) == ""
    termine = server._q("select id, payload from activities where lead_id = %s "
                        "and type = 'termin'", (lead,))
    assert len(termine) == 1
    p = termine[0]["payload"]
    assert p["uid"] == "u1" and p["aus_kalender"] is True and p["ort"] == MEET
    assert p["dauer_minuten"] == 60 and p["thema"] == "Beratung bAV"
    assert p["datum"] and p["uhrzeit"]
    assert str(_zeile()["termin_activity_id"]) == str(termine[0]["id"])
    erg = server._q("select payload from activities where lead_id = %s "
                    "and type = 'termin_ergebnis'", (lead,))
    assert len(erg) == 1 and erg[0]["payload"]["weg"] == "termin-seite"
    assert erg[0]["payload"]["termin_id"] == str(termine[0]["id"])
    assert _vstatus(vid) == "bestaetigt"


def test_termin_ergebnis_zweimal_bleibt_offen():
    lead = _lead()
    _akte("u1", herkunft="kalender", status="fertig")
    _teilnehmer("u1", lead)
    mid = _mitschrift("u1")
    daten = {"stattgefunden": True, "erfolg": False, "was": ""}
    v1 = _vorschlag(mid, "termin_ergebnis", lead, daten)
    v2 = _vorschlag(mid, "termin_ergebnis", lead, daten)
    assert _hinweis(_post("u1", "vorschlag_uebernehmen", vorschlag_id=v1)) == ""
    a = _post("u1", "vorschlag_uebernehmen", vorschlag_id=v2)
    assert "schon gebucht" in _hinweis(a)
    assert _vstatus(v1) == "bestaetigt" and _vstatus(v2) == "offen"
    assert len(server._q("select 1 from activities where type = 'termin' "
                         "and lead_id = %s", (lead,))) == 1
    assert len(server._q("select 1 from activities where type = 'termin_ergebnis' "
                         "and lead_id = %s", (lead,))) == 1


def test_wiedervorlage_uebernehmen():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    vid = _vorschlag(_mitschrift("u1"), "wiedervorlage", lead,
                     {"faellig_am": "2099-02-01", "notiz": "Angebot schicken"})
    a = _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    assert a.status_code == 303 and _hinweis(a) == ""
    z = server._q("select payload from activities where lead_id = %s "
                  "and type = 'wiedervorlage'", (lead,))
    assert len(z) == 1 and z[0]["payload"] == {"faellig_am": "2099-02-01",
                                               "notiz": "Angebot schicken"}
    assert _vstatus(vid) == "bestaetigt"


def test_feld_nur_die_zwei_spalten():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    mid = _mitschrift("u1")
    v_titel = _vorschlag(mid, "feld", lead, {"feld": "title", "wert": "Geschaeftsfuehrer"})
    v_firma = _vorschlag(mid, "feld", lead, {"feld": "company", "wert": "Neu AG"})
    v_boese = _vorschlag(mid, "feld", lead, {"feld": "email", "wert": "x@y.de"})
    for vid in (v_titel, v_firma, v_boese):
        _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    z = server._q("select title, company, email from leads where id = %s", (lead,))[0]
    assert z["title"] == "Geschaeftsfuehrer" and z["company"] == "Neu AG"
    assert z["email"] == ADRESSE
    assert _vstatus(v_titel) == "bestaetigt" and _vstatus(v_firma) == "bestaetigt"
    assert _vstatus(v_boese) == "offen"


def test_vorschlag_verwerfen():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    vid = _vorschlag(_mitschrift("u1"), "wiedervorlage", lead,
                     {"faellig_am": "2099-02-01", "notiz": "x"})
    _post("u1", "vorschlag_verwerfen", vorschlag_id=vid)
    assert _vstatus(vid) == "verworfen"
    assert not server._q("select 1 from activities where type = 'wiedervorlage'")


def test_vorschlag_einer_anderen_akte_wird_nicht_angefasst():
    lead = _lead()
    _akte("u1", status="fertig")
    _akte("u2", status="fertig")
    vid = _vorschlag(_mitschrift("u2"), "wiedervorlage", lead,
                     {"faellig_am": "2099-02-01", "notiz": "x"})
    a = _post("u1", "vorschlag_verwerfen", vorschlag_id=vid)
    assert a.status_code == 303 and _hinweis(a)
    assert _vstatus(vid) == "offen"


def test_gesperrter_lead_wird_nicht_uebernommen():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead, adresse="anderer@firma.de")
    vid = _vorschlag(_mitschrift("u1"), "wiedervorlage", lead,
                     {"faellig_am": "2099-02-01", "notiz": "x"})
    server._q("update leads set enrichment = %s::jsonb where id = %s returning id",
              (json.dumps({server.PRIVAT_SCHLUESSEL: {"privat": True}}), lead))
    a = _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    assert "gesperrt" in _hinweis(a)
    assert _vstatus(vid) == "offen"
    assert not server._q("select 1 from activities where type = 'wiedervorlage'")


def test_mitschrift_verwerfen_raeumt_ab_und_lehnt_entwurf_ab():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    entwurf = str(server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, status) "
        "values (%s, 'email', %s, 'Danke', 'Text', 'pending') returning id",
        (lead, ADRESSE))[0]["id"])
    mid = _mitschrift("u1", entwurf_id=entwurf)
    v_bestaetigt = _vorschlag(mid, "wiedervorlage", lead,
                              {"faellig_am": "2099-02-01", "notiz": "bleibt"})
    _vorschlag(mid, "wiedervorlage", lead, {"faellig_am": "2099-03-01", "notiz": "geht"})
    _post("u1", "vorschlag_uebernehmen", vorschlag_id=v_bestaetigt)
    a = _post("u1", "mitschrift_verwerfen")
    assert a.status_code == 303
    assert _mit() is None
    assert not server._q("select 1 from termin_vorschlaege")
    assert server._q("select status from drafts where id = %s", (entwurf,))[0]["status"] == "rejected"
    z = _zeile()
    assert z["status"] == "ohne_aufnahme" and z["status_grund"] == "nachträglich verworfen"
    # Bestaetigte Wirkung bleibt (append-only).
    assert len(server._q("select 1 from activities where type = 'wiedervorlage'")) == 1


def test_unbekannte_aktion_und_unbekannte_akte():
    _akte("u1")
    assert "Unbekannte Aktion" in _hinweis(_post("u1", "unfug"))
    assert _post("gibts-nicht", "kein_bot").status_code == 404


# --- Schutz -----------------------------------------------------------------

def test_csrf_pflicht():
    _akte("u1", status="geplant")
    assert _post("u1", "kein_bot", csrf=False).status_code == 403
    assert _zeile()["kein_bot"] is False


def test_rolle_lesen_darf_nicht_posten(scharf):
    _akte("u1", status="geplant")
    client = _anmelden("lena", "lesen")
    assert _get(_pfad("u1"), client).status_code == 200
    a = _post("u1", "kein_bot", client=client)
    assert a.status_code == 403
    assert _zeile()["kein_bot"] is False
    # Die Seite zeigt der Rolle keine Schreib-Knoepfe.
    assert "Kein Bot" not in _get(_pfad("u1"), client).text


def test_gesperrter_teilnehmer_nicht_in_html_und_json():
    lead = _lead()
    _akte("u1")
    _teilnehmer("u1", lead)
    _teilnehmer("u1", None, "weg@firma.de", grund="gesperrt", name="Gesperrt Gustav")
    _teilnehmer("u1", None, "spaeter@firma.de", name="Spaeter Sperre")
    sperrliste.sperren(server._q, email="spaeter@firma.de", quelle="test", grund="Widerruf")
    for text in (_get(_pfad("u1")).text, _get(_pfad("u1") + ".json").text):
        assert "weg@firma.de" not in text and "Gesperrt Gustav" not in text
        assert "spaeter@firma.de" not in text and "Spaeter Sperre" not in text
        assert ADRESSE in text


def test_kein_passcode_und_keine_mitschrift_im_log(caplog, fake):
    caplog.set_level(logging.DEBUG)
    lead = _lead()
    _akte("u1", status="laeuft", vexa_meeting_id=11, vexa_plattform="google_meet",
          vexa_native_id="abc")
    _teilnehmer("u1", lead)
    _mitschrift("u1")
    fake.fehler = vexa.VexaFehler(f"kaputt {PASSCODE}")
    _get(_pfad("u1"))
    _get(_pfad("u1") + ".json")
    _post("u1", "ohne_aufnahme")
    log = caplog.text
    assert PASSCODE not in log and SEGMENT_TEXT not in log and ADRESSE not in log


# --- Fix-Runde 1 ------------------------------------------------------------

def test_lead_gesperrt_nicht_in_html_und_json():
    frei = _lead()
    weg = _lead(email="geaendert@firma.de", name="Privat Paula", firma="Geheim AG")
    _akte("u1")
    _teilnehmer("u1", frei)
    _teilnehmer("u1", weg, adresse="andere-adresse@firma.de", name="Privat Paula")
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s) "
              "returning id", (weg, server._json({"datum": "2098-12-01", "uhrzeit": "10:00",
                                                    "thema": "VERLAUFSGEHEIMNIS"})))
    server._q("update leads set enrichment = %s::jsonb where id = %s returning id",
              (json.dumps({server.PRIVAT_SCHLUESSEL: {"privat": True}}), weg))
    for pfad in (_pfad("u1"), _pfad("u1") + "?reiter=verlauf", _pfad("u1") + ".json"):
        text = _get(pfad).text
        for geheim in ("Privat Paula", "Geheim AG", "VERLAUFSGEHEIMNIS", weg,
                       "andere-adresse@firma.de"):
            assert geheim not in text, (pfad, geheim)
        assert "Karla Kunde" in text


def test_lead_mit_telefon_auf_sperrliste_nicht_sichtbar():
    weg = str(server._q(
        "insert into leads (name, email, phone, source) values "
        "('Tel Torsten', 'ttt@firma.de', '+4915112345678', 'Messe') returning id")[0]["id"])
    _akte("u1")
    _teilnehmer("u1", weg, adresse="neu@firma.de", name="Tel Torsten")
    sperrliste.sperren(server._q, phone="+4915112345678", quelle="test", grund="Widerruf")
    assert "Tel Torsten" not in _get(_pfad("u1")).text
    assert "Tel Torsten" not in _get(_pfad("u1") + ".json").text


def test_ohne_aufnahme_lehnt_offenen_entwurf_ab(fake):
    lead = _lead()
    _akte("u1", status="fertig")
    entwurf = str(server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, status) "
        "values (%s, 'email', %s, 'Danke', 'Text', 'pending') returning id",
        (lead, ADRESSE))[0]["id"])
    _mitschrift("u1", entwurf_id=entwurf)
    _post("u1", "ohne_aufnahme")
    assert server._q("select status from drafts where id = %s", (entwurf,))[0]["status"] == "rejected"
    assert _mit() is None and _zeile()["status"] == "ohne_aufnahme"


def test_mitschrift_verwerfen_ohne_mitschrift_aendert_nichts():
    _akte("u1", status="fertig")
    a = _post("u1", "mitschrift_verwerfen")
    assert a.status_code == 303 and "keine Mitschrift" in _hinweis(a)
    assert _zeile()["status"] == "fertig"


def test_vorschlag_zweimal_absenden_bucht_einmal():
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    vid = _vorschlag(_mitschrift("u1"), "wiedervorlage", lead,
                     {"faellig_am": "2099-02-01", "notiz": "einmal"})
    assert _hinweis(_post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)) == ""
    assert "nicht (mehr)" in _hinweis(_post("u1", "vorschlag_uebernehmen", vorschlag_id=vid))
    assert len(server._q("select 1 from activities where type = 'wiedervorlage'")) == 1


def test_fehlgeschlagene_wirkung_setzt_vorschlag_zurueck(monkeypatch):
    lead = _lead()
    _akte("u1", status="fertig")
    _teilnehmer("u1", lead)
    vid = _vorschlag(_mitschrift("u1"), "wiedervorlage", lead,
                     {"faellig_am": "kein-datum", "notiz": "x"})
    a = _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    assert "ungültig" in _hinweis(a) and _vstatus(vid) == "offen"
    def kaputt(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "_wiedervorlage_anlegen", kaputt)
    server._q("update termin_vorschlaege set daten = %s::jsonb where id = %s returning id",
              (json.dumps({"faellig_am": "2099-02-01", "notiz": "x"}), vid))
    with pytest.raises(RuntimeError):
        _post("u1", "vorschlag_uebernehmen", vorschlag_id=vid)
    assert _vstatus(vid) == "offen"


def test_nur_fruehere_akten_im_verlauf():
    lead = _lead()
    _akte("u1")
    _akte("alt", beginn=JETZT - timedelta(days=30), titel="FRUEHERTERMIN")
    _akte("spaeter", beginn=JETZT + timedelta(days=30), titel="SPAETERTERMIN")
    for u in ("u1", "alt", "spaeter"):
        _teilnehmer(u, lead)
    text = _get(_pfad("u1") + "?reiter=verlauf").text
    assert "FRUEHERTERMIN" in text and "SPAETERTERMIN" not in text


def test_hinweis_nur_als_festcode():
    _akte("u1")
    a = _get(_pfad("u1") + "?m=unbekannte_aktion")
    assert "Unbekannte Aktion." in a.text
    a = _get(_pfad("u1") + "?m=%3Cb%3Efrei%3C%2Fb%3E&hinweis=Freitext")
    assert "<b>frei</b>" not in a.text and "Freitext" not in a.text


@pytest.mark.parametrize("uid", ["a/b@x", "evt.json", "x/y.json"])
def test_uid_mit_schraegstrich_und_json_endung(uid):
    _akte(uid)
    h = _get(_pfad(uid))
    assert h.status_code == 200 and ">Beitreten</a>" in h.text
    j = _get(_pfad(uid) + ".json")
    assert j.status_code == 200 and j.json()["uid"] == uid


# --- Final-Review I2: erst Status, dann loeschen ------------------------------

def test_i2_aufnahme_beenden_setzt_status_vor_dem_loeschen(monkeypatch):
    _akte("u1", status="laeuft")
    _mitschrift("u1")
    gesehen = []
    echt = termin_akte.mitschrift_entfernen

    def spion(uid):
        gesehen.append(_zeile(uid)["status"])
        return echt(uid)

    monkeypatch.setattr(termin_akte, "mitschrift_entfernen", spion)
    _post("u1", "ohne_aufnahme")
    assert gesehen == ["ohne_aufnahme"]
    assert _mit() is None


# --- Bildschirm (Bildauswertung live, Task 7) --------------------------------

def _jpeg(farbe=(10, 20, 30)):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (64, 40), farbe).save(out, "JPEG")
    return out.getvalue()


def _jitsi(uid="j1", status="laeuft", **spalten):
    return _akte(uid, plattform="jitsi", status=status, vexa_meeting_id=7,
                 link="https://meet.ffmuc.net/x1", **spalten)


def _bild(uid="j1", minuten=0, name=None, beschr=None):
    import bildschirm
    bid = bildschirm.bild_ablegen(uid, _jpeg((minuten * 20 % 255, 0, 0)),
                                  datetime(2099, 1, 9, 12, 1, tzinfo=timezone.utc)
                                  + timedelta(minutes=minuten), name)
    assert bid
    if beschr is not None:
        server._q("update termin_bilder set beschreibung = %s, beschreibung_status = 'fertig' "
                  "where id = %s returning id", (beschr, bid))
    return bid


def _an(uid="j1"):
    return _zeile(uid)["bildschirm_auswerten"]


def _neue_uuid():
    import uuid
    return str(uuid.uuid4())


def test_schalter_nur_bei_jitsi():
    _akte("u1", plattform="google_meet", status="geplant")
    a = _post("u1", "bildschirm", wert="an")
    assert a.status_code == 303
    assert _hinweis(a) == "Bildschirm auswerten geht in Stufe 1 nur bei Jitsi-Terminen."
    assert _an("u1") is False
    # auch ohne erkannte Plattform
    _akte("u2", plattform=None, status="kein_link", link=None)
    assert "nur bei Jitsi" in _hinweis(_post("u2", "bildschirm", wert="an"))
    assert _an("u2") is False


def test_schalter_schaltet_um():
    _akte("j1", plattform="jitsi", status="geplant")
    assert "Bildschirm auswerten: aus" in _get(_pfad("j1")).text
    assert 'name="wert" value="an"' in _get(_pfad("j1")).text
    a = _post("j1", "bildschirm", wert="an")
    assert a.status_code == 303 and _hinweis(a) == ""
    assert _an("j1") is True
    t = _get(_pfad("j1")).text
    assert "Bildschirm auswerten: an" in t and 'name="wert" value="aus"' in t
    _post("j1", "bildschirm", wert="aus")
    assert _an("j1") is False


def test_schalter_setzt_zielwert_idempotent():
    _akte("j1", plattform="jitsi", status="laeuft", bildschirm_auswerten=True)
    for _ in range(2):          # doppelt abgeschickt / alter Tab: bleibt aus
        assert _hinweis(_post("j1", "bildschirm", wert="aus")) == ""
        assert _an("j1") is False
    for _ in range(2):
        assert _hinweis(_post("j1", "bildschirm", wert="an")) == ""
        assert _an("j1") is True


@pytest.mark.parametrize("wert", [None, "", "toggle", "AN"])
def test_schalter_ohne_gueltigen_wert_aendert_nichts(wert):
    _akte("j1", plattform="jitsi", status="laeuft", bildschirm_auswerten=True)
    felder = {} if wert is None else {"wert": wert}
    a = _post("j1", "bildschirm", **felder)
    assert a.status_code == 303 and "nichts geändert" in _hinweis(a)
    assert _an("j1") is True


@pytest.mark.parametrize("status", ["wartet_auf_einlass", "laeuft", "kein_link"])
def test_schalter_in_erlaubten_status(status):
    _akte("j1", plattform="jitsi", status=status)
    assert _hinweis(_post("j1", "bildschirm", wert="an")) == ""
    assert _an("j1") is True


@pytest.mark.parametrize("status", ["fertig", "ohne_aufnahme", "fehlgeschlagen"])
def test_schalter_gesperrt_nach_dem_termin(status):
    _akte("j1", plattform="jitsi", status=status)
    assert "nicht mehr" in _hinweis(_post("j1", "bildschirm", wert="an"))
    assert _an("j1") is False


def test_schalter_csrf_und_rolle_lesen(scharf):
    _akte("j1", plattform="jitsi", status="geplant")
    assert _post("j1", "bildschirm", csrf=False, wert="an").status_code == 403
    assert _an("j1") is False
    client = _anmelden("lena", "lesen")
    assert _post("j1", "bildschirm", client=client, wert="an").status_code == 403
    assert _an("j1") is False
    assert "Bildschirm auswerten:" not in _get(_pfad("j1"), client).text


def test_reiter_bildschirm_nur_mit_schalter_oder_bildern():
    _akte("j1", plattform="jitsi", status="geplant")
    assert "reiter=bildschirm" not in _get(_pfad("j1")).text
    _post("j1", "bildschirm", wert="an")
    assert "reiter=bildschirm" in _get(_pfad("j1")).text


def test_reiter_bildschirm_zeigt_bilder():
    _jitsi(bildschirm_auswerten=True)
    b1 = _bild(minuten=0, name="Karla <i>K</i>", beschr="Folie <script>x()</script> Budget")
    b2 = _bild(minuten=1)
    a = _get(_pfad("j1") + "?reiter=bildschirm")
    assert a.status_code == 200
    t = a.text
    assert f"/termine/j1/bild/{b1}.jpg" in t and f"/termine/j1/bild/{b2}.jpg" in t
    assert "Folie &lt;script&gt;x()&lt;/script&gt; Budget" in t and "<script>x()" not in t
    assert "Karla &lt;i&gt;K&lt;/i&gt;" in t and "<i>K</i>" not in t
    assert "wird beschrieben" in t                       # b2 noch ohne Beschreibung
    assert "13:01" in t                                  # 12:01 UTC = 13:01 Berlin (Januar)
    assert "/static/termin_bilder/bilder.js" in t and 'type="search"' in t
    assert "script-src 'self'" in a.headers["content-security-policy"]


def test_reiter_bildschirm_vermerkt_obergrenze(monkeypatch):
    import bildschirm
    monkeypatch.setattr(bildschirm, "OBERGRENZE", 2)
    _jitsi(bildschirm_auswerten=True)
    _bild(minuten=0)
    t = _get(_pfad("j1") + "?reiter=bildschirm").text
    assert "Obergrenze" not in t
    _bild(minuten=1)
    t = _get(_pfad("j1") + "?reiter=bildschirm").text
    assert ("Obergrenze von 2 Standbildern erreicht – weitere nur noch bei starker Änderung."
            in t)


def test_reiter_bildschirm_ohne_bilder_hinweis():
    _jitsi(bildschirm_auswerten=True)
    assert "Noch keine Bilder" in _get(_pfad("j1") + "?reiter=bildschirm").text


def test_bilder_json_live():
    _jitsi(bildschirm_auswerten=True)
    b = _bild(beschr="Preisliste")
    a = _get(_pfad("j1") + "/bilder.json")
    assert a.status_code == 200
    d = a.json()
    assert d["live"] is True
    assert [x["id"] for x in d["bilder"]] == [b]
    x = d["bilder"][0]
    assert x["beschreibung"] == "Preisliste" and x["url"] == f"/termine/j1/bild/{b}.jpg"
    assert "bild" not in x and "dhash" not in x
    server._q("update termin_akten set status = 'fertig' where uid = 'j1' returning uid")
    assert _get(_pfad("j1") + "/bilder.json").json()["live"] is False


def test_bilder_json_unbekannte_akte_404():
    assert _get(_pfad("gibts-nicht") + "/bilder.json").status_code == 404


def test_bild_jpg_und_fremde_uid_404():
    _jitsi(bildschirm_auswerten=True)
    _jitsi("j2", bildschirm_auswerten=True)
    b = _bild("j1")
    a = _get(f"/termine/j1/bild/{b}.jpg")
    assert a.status_code == 200 and a.headers["content-type"] == "image/jpeg"
    # geloeschte Bilder sollen nicht im Browser-Cache weiterleben (M6)
    assert a.headers["cache-control"] == "private, no-store"
    assert a.content.startswith(b"\xff\xd8")
    assert _get(f"/termine/j2/bild/{b}.jpg").status_code == 404
    assert _get(f"/termine/j1/bild/{_neue_uuid()}.jpg").status_code == 404
    assert _get("/termine/j1/bild/kein-uuid.jpg").status_code == 404


def test_bild_loeschen():
    _jitsi(bildschirm_auswerten=True)
    b1, b2 = _bild(minuten=0), _bild(minuten=1)
    a = _post("j1", "bild_loeschen", bild_id=b1)
    assert a.status_code == 303 and _hinweis(a) == ""
    assert "reiter=bildschirm" in a.headers["location"]
    import bildschirm
    assert [str(x["id"]) for x in bildschirm.bilder("j1")] == [b2]
    assert "nicht (mehr)" in _hinweis(_post("j1", "bild_loeschen", bild_id=b1))
    assert "nicht (mehr)" in _hinweis(_post("j1", "bild_loeschen", bild_id="murks"))


def test_bild_loeschen_csrf_und_rolle(scharf):
    _jitsi(bildschirm_auswerten=True)
    b = _bild()
    assert _post("j1", "bild_loeschen", csrf=False, bild_id=b).status_code == 403
    client = _anmelden("lena", "lesen")
    assert _post("j1", "bild_loeschen", client=client, bild_id=b).status_code == 403
    import bildschirm
    assert len(bildschirm.bilder("j1")) == 1
    t = _get(_pfad("j1") + "?reiter=bildschirm", client).text
    assert f"/termine/j1/bild/{b}.jpg" in t and "bild_loeschen" not in t


def test_rolle_lesen_darf_bilder_sehen(scharf):
    _jitsi(bildschirm_auswerten=True)
    b = _bild()
    client = _anmelden("lena", "lesen")
    assert _get(_pfad("j1") + "/bilder.json", client).status_code == 200
    assert _get(f"/termine/j1/bild/{b}.jpg", client).status_code == 200


class _Antwort:
    def __init__(self, daten):
        self._d = json.dumps(daten).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._d


def test_bilder_json_suche_ruft_auge(monkeypatch):
    import urllib.request
    _jitsi(bildschirm_auswerten=True)
    b1, b2 = _bild(minuten=0, beschr="Preisliste"), _bild(minuten=1, beschr="Vertrag")
    gesehen = {}

    def urlopen(req, timeout=None):
        gesehen["url"], gesehen["timeout"] = req.full_url, timeout
        gesehen["body"] = json.loads(req.data)
        return _Antwort([
            {"id": b2, "uid": "j1", "aufgenommen_am": "x", "beschreibung": "Vertrag",
             "score": 0.9},
            {"id": _neue_uuid(), "uid": "j1", "aufgenommen_am": "x",
             "beschreibung": "weg", "score": 0.5}])

    monkeypatch.setenv("AUGE_URL", "http://auge:8790")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    d = _get(_pfad("j1") + "/bilder.json?q=Vertrag").json()
    assert gesehen["url"] == "http://auge:8790/suche" and gesehen["timeout"] <= 15
    assert gesehen["body"]["text"] == "Vertrag" and gesehen["body"]["uid"] == "j1"
    assert [x["id"] for x in d["bilder"]] == [b2]       # unbekannte Id faellt weg
    assert d["bilder"][0]["score"] == 0.9 and "fehler" not in d


def test_bilder_json_suche_ohne_auge_ist_freundlich(monkeypatch):
    import urllib.request
    _jitsi(bildschirm_auswerten=True)
    _bild()
    monkeypatch.setenv("AUGE_URL", "")
    d = _get(_pfad("j1") + "/bilder.json?q=x")
    assert d.status_code == 200 and d.json()["bilder"] == [] and d.json()["fehler"]

    def kaputt(req, timeout=None):
        raise OSError("weg")
    monkeypatch.setenv("AUGE_URL", "http://auge:8790")
    monkeypatch.setattr(urllib.request, "urlopen", kaputt)
    d = _get(_pfad("j1") + "/bilder.json?q=x")
    assert d.status_code == 200 and d.json()["fehler"]


def test_route_reihenfolge_vor_kennung_path():
    pfade = [r.path for r in ui_termin.routen(ui)]
    kennung = [i for i, p in enumerate(pfade) if p == "/termine/{kennung:path}"]
    assert kennung
    bild = [i for i, p in enumerate(pfade) if "bild" in p]
    assert bild and max(bild) < min(kennung)
    assert any(p.endswith("/bilder.json") for p in pfade)
    assert any(p.endswith(".jpg") for p in pfade)


def test_static_bilder_js():
    a = _get("/static/termin_bilder/bilder.js")
    assert a.status_code == 200 and "javascript" in a.headers["content-type"]
    assert "innerHTML" not in a.text
    assert _get("/static/termin_bilder/nix.js").status_code == 404


def test_verlauf_zeigt_vorschaubilder():
    _jitsi(bildschirm_auswerten=True)
    segmente = [{"sprecher": "A", "beginn": "2099-01-09T12:00:00Z", "text": "SEGMENTAAA"},
                {"sprecher": "B", "beginn": "2099-01-09T12:02:00Z", "text": "SEGMENTBBB"},
                {"sprecher": "C", "beginn": "2099-01-09T12:10:00Z", "text": "SEGMENTCCC"}]
    verlauf = [{"thema": "Preise <b>neu</b>", "inhalt": "x", "von": 0, "bis": 0},
               {"thema": "Vertrag", "inhalt": "y", "von": 1, "bis": 1},
               {"thema": "Ohne Bilder", "inhalt": "z", "von": 2, "bis": 2},
               {"thema": "KaputtBereich", "inhalt": "z", "von": "a", "bis": None},
               {"thema": "AusserhalbBereich", "inhalt": "z", "von": 1, "bis": 99},
               "kein-dict"]
    _mitschrift("j1", segmente=json.dumps(segmente),
                auswertung_json=json.dumps({"verlauf": verlauf}))
    b0 = _bild(minuten=0)          # 12:01 -> Eintrag "Preise"
    b1 = _bild(minuten=2)          # 12:03 -> Eintrag "Vertrag"
    a = _get(_pfad("j1") + "?reiter=mitschrift")
    assert a.status_code == 200
    t = a.text
    assert "Preise &lt;b&gt;neu&lt;/b&gt;" in t and "Preise <b>neu</b>" not in t
    ip, iv = t.index("Preise &lt;b&gt;"), t.index(">Vertrag</h3>")
    i0, i1 = t.index(f"/bild/{b0}.jpg"), t.index(f"/bild/{b1}.jpg")
    assert ip < i0 < iv < i1
    assert t.count(f"/bild/{b0}.jpg") == 2 and t.count(f"/bild/{b1}.jpg") == 2   # Link + Bild
    for fremd in ("Ohne Bilder", "KaputtBereich", "AusserhalbBereich"):
        assert f">{fremd}</h3>" not in t
    # keine Vorschaubilder mehr je Rohsegment: nach dem Mitschrift-Text kommt keins
    assert f"/bild/{b1}.jpg" not in t[t.index("SEGMENTAAA"):]


def test_verlauf_ohne_auswertung_json_keine_bilder_je_thema():
    _jitsi(bildschirm_auswerten=True)
    _mitschrift("j1")
    _bild()
    assert "Bilder je Thema" not in _get(_pfad("j1") + "?reiter=mitschrift").text


def test_akte_json_hat_schalter_und_anzahl():
    _jitsi(bildschirm_auswerten=True)
    _bild()
    d = _get(_pfad("j1") + ".json").json()
    assert d["bildschirm_auswerten"] is True and d["bilder_anzahl"] == 1


def test_reiter_bildschirm_vermerkt_uebersprungene_heikle():
    _jitsi(bildschirm_auswerten=True)
    assert "heikle Bildschirme" not in _get(_pfad("j1") + "?reiter=bildschirm").text
    server._q("update termin_akten set bilder_uebersprungen = 3 where uid = 'j1' returning uid")
    t = _get(_pfad("j1") + "?reiter=bildschirm").text
    assert "3 heikle Bildschirme (Anmeldung, Bezahlung, Postfach) wurden nicht gespeichert." in t
    assert _get(_pfad("j1") + ".json").json()["bilder_uebersprungen"] == 3
