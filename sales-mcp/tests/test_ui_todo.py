"""Vertraege aus dem Seitenrundgang mit dem Betreiber (27./28.10.2026,
docs/superpowers/plans/2026-10-27-sales-ui-ueberarbeitung-todo.md)."""
import pytest
from starlette.testclient import TestClient

import server
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
        conn.execute("truncate sales_test.einstellungen, sales_test.postfach_mails")
    server._BEZIEHUNG_CACHE.update(wert=None, bis=0.0)
    yield
    # Nichts zuruecklassen, was andere Testdateien veraendert (Team-Ebenen,
    # hoeherer Knoten, Standardstufen, Postfach-Index).
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.einstellungen, sales_test.postfach_mails")
    server._BEZIEHUNG_CACHE.update(wert=None, bis=0.0)


def _get(pfad, **kw):
    return CLIENT.get(pfad, headers={"host": HOST_OK}, **kw)


def _lead(name="Max Testperson", phone="+491701234567", **spalten):
    namen = ["name", "phone", "source", *spalten]
    werte = [name, phone, "whatsapp", *spalten.values()]
    return str(server._q(
        f"insert into leads ({', '.join(namen)}) values "
        f"({', '.join(['%s'] * len(werte))}) returning id",
        tuple(werte))[0]["id"])


# --- Allgemein: Schrift groesser --------------------------------------------

def test_grundschrift_und_menue_sind_groesser():
    """Rundgang 27.10.: Aufgaben-Bereich soll leichter lesbar sein."""
    s = _get("/").text
    assert "font-size: 17px; line-height: 1.5" in s
    assert "font-size: 1.05rem; font-weight: 600" in s
    assert ".gruppenname { font-size: .78rem" in s


# --- Allgemein: keine Seitenleiste ohne Anmeldung ---------------------------

def test_login_seite_ohne_sitzung_zeigt_kein_menue_und_keine_zahlen(
        monkeypatch):
    """Rundgang 27.10.: die Anmeldemaske zeigte die Seitenleiste samt
    Zaehlern (Kontakte 569, Posteingang 5) - fuer jeden im Tailnet, ohne
    Anmeldung."""
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis")
    _lead()
    s = _get("/login").text
    assert 'name="passwort"' in s
    assert '<nav class="seite"' not in s
    assert '<nav class="tabs"' not in s
    assert 'href="/kontakte"' not in s
    assert 'class="zaehler' not in s


def test_passwort_vergessen_ohne_sitzung_ohne_menue(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis")
    s = _get("/passwort-vergessen").text
    assert '<nav class="seite"' not in s


def _post(pfad, daten):
    return CLIENT.post(pfad, data={"csrf": ui.CSRF_TOKEN, **daten},
                       headers={"host": HOST_OK}, follow_redirects=False)


# --- Heute / Termine ohne Datum ----------------------------------------------

def test_termin_ohne_datum_lehnt_das_werkzeug_ab():
    import json
    lead = _lead()
    r = json.loads(server.aktivitaet_loggen(lead, "termin", "Donnerstag?"))
    assert "fehler" in r and "termin_bestaetigen" in r["fehler"]
    assert not server._q("select 1 from activities where lead_id = %s "
                         "and type = 'termin'", (lead,))
    assert "geloggt" in json.loads(server.aktivitaet_loggen(lead, "notiz", "x"))


def test_heute_ohne_termine_ohne_datum_mit_termine_heute():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin', '{\"inhalt\": \"alte Notiz\"}') returning id", (lead,))
    s = _get("/").text.split("<main>")[1]
    assert "Termine ohne festes Datum" not in s
    assert "Terminanfrage" not in s
    assert "Termine heute" in s
    assert "alte Notiz" not in s


def test_freigaben_ohne_termine_und_ohne_verlauf():
    s = _get("/freigaben").text
    assert 'id="termine"' not in s
    assert "Verlauf WhatsApp" not in s and "Ganzer Verlauf" not in s


def test_monitoring_verlauf_zeigt_die_verlaeufe():
    s = _get("/monitoring/verlauf").text
    assert "Verlauf WhatsApp" in s and "Verlauf Termine" in s
    menue = _get("/").text
    assert 'href="/monitoring/verlauf"' in menue
    gruppen = dict(ui._GRUPPEN)
    assert ("/einstellungen/kanaele", "Kanäle") in gruppen["Monitoring"]
    assert all(p != "/einstellungen/kanaele" for p, _ in gruppen["Admin"])


# --- Einordnung ------------------------------------------------------------------

def _sammel(monkeypatch):
    sammel = str(server._q("insert into leads (name, source) values "
                           "('Unbekannte Eingaenge', 'system') returning id")[0]["id"])
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", sammel)
    return sammel


def _eingang(sammel, nummer, text="", typ="chat", **mehr):
    import json
    nutzlast = {"absender": f"{nummer}@c.us", "text": text,
                "nachrichtentyp": typ, "message_id": f"m-{nummer}-{text}-{typ}",
                **mehr}
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'kundenantwort', %s, 'human') returning id",
              (sammel, json.dumps(nutzlast)))


def test_einordnung_zeigt_auch_aeltere_offene_absender(monkeypatch):
    sammel = _sammel(monkeypatch)
    for i in range(30):
        _eingang(sammel, f"49170000{i:04d}", f"hallo {i}")
    s = _get("/einordnung").text
    assert "Wartet auf Entscheidung (30)" in s
    menue = s.split('href="/einordnung">')[1][:80]
    assert ">30<" in menue


def test_einordnung_sprachnachricht_mit_spieler_und_abschrift(monkeypatch):
    import json
    sammel = _sammel(monkeypatch)
    _eingang(sammel, "4917011112222", "", "ptt",
             audio_datei="0123456789abcdef0123456789abcdef.ogg")
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'transkription', %s, 'agent') returning id",
              (sammel, json.dumps({"message_id": "m-4917011112222--ptt",
                                   "text": "Hier ist Karl vom Sportverein"})))
    s = _get("/einordnung").text
    assert 'src="/einordnung/datei/0123456789abcdef0123456789abcdef.ogg"' in s
    assert "Hier ist Karl vom Sportverein" in s
    assert "+49 170 11112222" in s


def test_einordnung_datei_nur_hashnamen(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SPRACH_VERZEICHNIS", str(tmp_path))
    (tmp_path / ("a" * 32 + ".ogg")).write_bytes(b"OggS")
    r = _get("/einordnung/datei/" + "a" * 32 + ".ogg")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/ogg"
    assert _get("/einordnung/datei/..%2Fetc%2Fpasswd").status_code == 404
    assert _get("/einordnung/datei/" + "b" * 32 + ".ogg").status_code == 404


def test_bereits_entschieden_mit_beziehung_ohne_profil(monkeypatch):
    sammel = _sammel(monkeypatch)
    lead = _lead(name="Julia", phone="+4917099998888")
    _eingang(sammel, "4917099998888", "hi")
    s = _get("/einordnung").text
    teil = s.split("Bereits entschieden")[1]
    assert "<th>Beziehung</th>" in teil
    assert "<th>Profil</th>" not in teil and "<th>Nachrichten</th>" not in teil
    r = _post("/kontakte/beziehung", {"lead_id": lead, "beziehung": "partner",
                                     "danach": "/einordnung"})
    assert r.status_code == 303 and r.headers["location"] == "/einordnung"
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]
    assert e["enrichment"]["beziehung"] == "partner"
    assert 'value="partner" selected' in _get("/einordnung").text


def test_beziehung_ziel_nie_fremd():
    lead = _lead()
    r = _post("/kontakte/beziehung", {"lead_id": lead, "beziehung": "kunde",
                                     "danach": "//boese.example"})
    assert r.headers["location"] == f"/kontakte/{lead}"


# --- Autonomie je Beziehung --------------------------------------------------------

def test_standard_autonomie_je_beziehung():
    server._q("delete from einstellungen")
    server._BEZIEHUNG_CACHE.update(wert=None, bis=0.0)
    lead = _lead()
    server._beziehung_setzen(lead, "privat")
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert server._autonomie(e) == "manuell"
    r = _post("/kontakte/beziehung-autonomie", {"beziehung": "privat",
                                                "standard": "halbauto"})
    assert r.status_code == 303
    assert server._autonomie(e) == "halbauto"
    # Eigene Stufe am Kontakt geht vor.
    e["autonomie"] = {"stufe": "manuell"}
    assert server._autonomie(e) == "manuell"
    assert "fehler" in server.beziehung_autonomie_setzen("kunde", "ignorieren", "t")


# --- Kontaktliste -----------------------------------------------------------------

def test_kontaktliste_spalten_wie_papiervorlage():
    _lead()
    s = _get("/kontakte").text
    for spalte in ("Name / Anschrift", "Telefon", "Alter / Fam. / Kinder",
                   "Beruf &amp; Hobbys", "Termine", "Abschluss", "Empf.-Zahl",
                   "Bemerkung FK", "Autonomie"):
        assert f"<th>{spalte}</th>" in s, spalte
    assert "Kontaktliste (" in s


def test_kontaktliste_felder_speichern_und_zeigen():
    lead = _lead(name="Hannah Löffelmann")
    r = _post("/kontakte/liste", {"lead_id": lead, "alter": "34",
                                  "beruf": "Sales Veranst.", "hobbys": "singt",
                                  "bemerkung_fk": "gut", "analysiert": "1"})
    assert r.status_code == 303
    s = _get("/kontakte").text
    assert "34" in s and "Sales Veranst. · singt" in s and "analysiert ✓" in s


def test_kontaktsuche_erlaubt_tippfehler():
    _lead(name="Hannah Löffelmann")
    _lead(name="Max Mustermann", phone="+491709999999")
    s = _get("/kontakte?q=Löfelman").text
    assert "Hannah Löffelmann" in s and "Max Mustermann" not in s


def test_kontaktliste_zeigt_bis_fuenf_termine():
    import json
    lead = _lead()
    for tag in range(1, 8):
        server._q("insert into activities (lead_id, type, payload) values "
                  "(%s, 'termin', %s) returning id",
                  (lead, json.dumps({"datum": f"2026-11-0{tag}", "uhrzeit": "10:00"})))
    s = _get("/kontakte").text
    assert "<div>5) " in s and "<div>6) " not in s


def test_kalender_verbinden_bietet_gmx():
    assert any(a[0] == "GMX" for a in ui._ANBIETER_WEGE)


# --- Pipeline / Ergebnisse / Wiedervorlagen -------------------------------------

def test_pipeline_drei_arten_und_phasen():
    k = _lead(name="Kunde Karl")
    f = _lead(name="Firma GmbH", phone="+491701112233")
    p = _lead(name="Freund Fritz", phone="+491701112244")
    m = _lead(name="Mitarbeiter Mia", phone="+491701112255")
    server._beziehung_setzen(k, "kunde")
    server._beziehung_setzen(f, "partner")
    server._beziehung_setzen(p, "privat")
    server._beziehung_setzen(m, "mitarbeiter")
    s = _get("/pipeline").text
    assert "Kunde Karl" in s and "Firma GmbH" not in s and "Mitarbeiter Mia" not in s
    assert "Firma GmbH" in _get("/pipeline?art=firmen").text
    assert "Freund Fritz" in _get("/pipeline?art=privat").text
    for name in ("Termin 1 · Aufnahme", "Bedarfsanalyse",
                 "Termin 2 · Verkaufsgespräch", "Abschluss", "Empfehlung"):
        assert name in s
    r = _post("/pipeline/phase", {"lead_id": k, "phase": "bedarfsanalyse"})
    assert r.status_code == 303
    e = server._q("select status, enrichment from leads where id = %s", (k,))[0]
    assert server._phase(e["status"], e["enrichment"]) == "bedarfsanalyse"


def test_pipeline_newsletter_als_ja_nein():
    k = _lead(name="Nora Newsletter")
    server._q("update leads set consent_status = 'opt_in' where id = %s", (k,))
    s = _get("/pipeline").text
    assert "Newsletter ✓" in s
    assert "Nora Newsletter" not in _get("/pipeline?newsletter=nein").text


def _termin_gestern(lead, uhrzeit="10:00"):
    import json
    from datetime import date, timedelta
    tag = (date.today() - timedelta(days=1)).isoformat()
    return str(server._q("insert into activities (lead_id, type, payload) values "
                         "(%s, 'termin', %s) returning id",
                         (lead, json.dumps({"datum": tag, "uhrzeit": uhrzeit,
                                            "dauer_minuten": 60})))[0]["id"])


def test_rueckfrage_nach_dem_termin_zwei_termine():
    import json
    lead = _lead()
    t1 = _termin_gestern(lead, "09:00")
    offen = json.loads(server.termin_rueckfragen())["rueckfragen"]
    assert [o["termin_id"] for o in offen] == [t1] and offen[0]["art"] == "aufnahme"
    assert "Wie lief der Termin? (1)" in _get("/ergebnisse").text
    r = _post("/ergebnisse/termin", {"termin_id": t1, "stattgefunden": "1"})
    assert r.status_code == 303
    t2 = _termin_gestern(lead, "15:00")
    offen = json.loads(server.termin_rueckfragen())["rueckfragen"]
    assert offen[0]["art"] == "verkaufsgespraech"
    fehlt = json.loads(server.termin_ergebnis_speichern(t2, True, True, "", ""))
    assert "fehler" in fehlt
    ok = json.loads(server.termin_ergebnis_speichern(t2, True, True, "bAV-Vertrag", ""))
    assert ok["gebucht"]
    s = _get("/ergebnisse").text
    assert "Verkaufsgespräche (1)" in s and "bAV-Vertrag" in s
    e = server._q("select status, enrichment from leads where id = %s", (lead,))[0]
    assert server._phase(e["status"], e["enrichment"]) == "abschluss"


def test_wiedervorlagen_zeigen_heutige_termine_mit_unterlagen():
    import json
    lead = _lead(name="Heute Hans")
    heute = ui.datetime.now(ui.ZEITZONE).date().isoformat()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'termin', %s) returning id",
              (lead, json.dumps({"datum": heute,
                                 "uhrzeit": "14:00", "thema": "Erstgespräch"})))
    s = _get("/wiedervorlagen").text
    assert "Heute anstehende Termine (1)" in s and "Heute Hans" in s
    assert "Bedarfsanalyse-Bogen" in s


# --- Posteingang -----------------------------------------------------------------

def test_posteingang_mails_suche_und_aufraeumen():
    server._q("delete from postfach_mails")
    server._q("insert into postfach_mails (message_id, uid, von, betreff, auszug) "
              "values ('a1', '7', 'shop@werbung.de', 'Rabattaktion Herbst', "
              "'Jetzt sparen'), ('a2', '8', 'bank@betrug.ru', 'Konto gesperrt', "
              "'Bitte einloggen')")
    server._q("update postfach_mails set art = 'spam', status = 'verschoben', "
              "grund = 'Phishing' where message_id = 'a2'")
    server._q("update postfach_mails set art = 'unwichtig', status = 'vorgeschlagen', "
              "grund = 'Werbung' where message_id = 'a1'")
    s = _get("/posteingang").text
    assert "Rabattaktion Herbst" in s and "Spam-Ordner (1)" in s
    assert "Rabattaktionen" in _get("/posteingang?q=Rabattaktionen").text or \
        "Rabattaktion Herbst" in _get("/posteingang?q=Rabattaktionen").text
    assert "Rabattaktion Herbst" in _get("/posteingang?q=Rabbataktion").text
    f = _get("/freigaben").text
    assert "Mails aufräumen" in f and "Rabattaktion Herbst" in f
    r = _post("/posteingang/aufraeumen", {"message_id": "a1",
                                          "entscheidung": "verschieben"})
    assert r.status_code == 303
    assert server._q("select status from postfach_mails where message_id = 'a1'"
                     )[0]["status"] == "bestaetigt"


def test_wartezeit_lesbar():
    assert ui._wartezeit(14.3) == "14 Std."
    assert ui._wartezeit(0.4) == "24 Min."


# --- Struktur ---------------------------------------------------------------------

def test_struktur_ich_unter_hoeherem_knoten(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("delete from admin_auftraege")
        conn.execute("delete from einstellungen where schluessel = 'struktur_ueber_mir'")
        conn.execute("insert into admin_auftraege (art, name, status, level, email, "
                     "angefordert_von) values ('laden_anlegen', 'ivan', 'erfolg', 3, "
                     "'i@x.de', 'test')")
    monkeypatch.setattr(ui, "_pfad_erlaubt", lambda rolle, pfad: True)
    r = _post("/team/struktur/ueber", {"ueber": "ivan"})
    assert r.status_code == 303
    s = _get("/team/struktur").text
    assert 'class="upline-knoten" data-name="ivan"' in s
    assert "über mir" in s
    assert '<script src="/team/struktur/struktur.js" defer></script>' in s
    js = _get("/team/struktur/struktur.js")
    assert js.status_code == 200 and "dragstart" in js.text


# --- Team-Kalender -----------------------------------------------------------------

def test_team_ebene_aus_gilt_fuer_planung(monkeypatch):
    import kalenderquellen
    server._q("delete from einstellungen where schluessel = 'kalender_team_aus'")
    monkeypatch.setattr(server, "kalenderquellen_lesen",
                        lambda nur_aktive=True: [{"id": "q1", "anzeigename": "Ivan",
                                                  "url": "x"}])
    monkeypatch.setattr(server, "kalenderquelle_stand_setzen", lambda *a: None)
    from datetime import datetime, timedelta
    t = {"beginn": datetime.now() + timedelta(days=1),
         "ende": datetime.now() + timedelta(days=1, hours=1),
         "titel": "Geheimes Thema", "ort": "Büro"}
    monkeypatch.setattr(kalenderquellen, "hole", lambda *a, **k: ([t], None))
    monkeypatch.setattr(server.kalender, "termine_lesen", lambda *a: ([], None))
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["belegt"]
    server.team_kalender_aus_setzen(["Ivan"], "test")
    eintraege, _ = server.belegungen()
    assert eintraege == []


# --- Marketing: Marke loeschen -----------------------------------------------------

def test_marke_loeschen_nur_mit_bestaetigung(monkeypatch):
    import marketing_pult
    aufrufe = []
    monkeypatch.setattr(ui, "_pfad_erlaubt", lambda rolle, pfad: True)
    monkeypatch.setattr(marketing_pult, "anfrage",
                        lambda methode, pfad, daten=None, **k: aufrufe.append((methode, pfad, daten))
                        or {"ok": True})
    r = _post("/marketing/marke/loeschen", {"mandant": "probe_gmbh", "bestaetigung": "falsch"})
    assert r.status_code == 422 and aufrufe == []
    r = _post("/marketing/marke/loeschen", {"mandant": "probe_gmbh", "bestaetigung": "probe_gmbh"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/layouts"
    assert aufrufe == [("POST", "/marke/loeschen", {"mandant": "probe_gmbh",
                                                    "bestaetigung": "probe_gmbh",
                                                    "von": "betreiber-ui"})]


def test_mit_sitzung_bleibt_das_menue(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis")
    server._q("insert into benutzer (name, passwort_hash, rolle, aktiv) "
              "values ('probe', 'x', 'freigeben', true) "
              "on conflict (name) do update set aktiv = true, "
              "rolle = 'freigeben'")
    import time
    keks = ui._sitzung_bauen("probe", time.time() + 600)
    s = CLIENT.get("/kontakte", headers={"host": HOST_OK},
                   cookies={ui.SITZUNG_COOKIE: keks}).text
    assert '<nav class="seite"' in s
