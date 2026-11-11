"""Vertragstests fuer das DSGVO-Handwerk (P2, 27.08.2026).

Bisher stand nur im Docstring von kontakt_archivieren: ein echtes
Loeschbegehren ist ein Admin-Eingriff ausserhalb dieser Werkzeuge. P2
macht daraus zwei definierte Ablaeufe: Auskunft (Art. 15) als Export,
Loeschantrag (Art. 17) als Vermerk, der SOFORT jede weitere Verarbeitung
stoppt — die physische Loeschung bleibt bewusst ein dokumentierter
Menschen-Schritt (docs/06_DSGVO.md).

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Die Auskunft ist vollstaendig oder sie ist keine: Stammdaten,
   Anreicherung, jede Protokollzeile, jeder Entwurf.
2. Ein vermerkter Loeschantrag stoppt ALLES: keine neuen Entwuerfe, kein
   Auto-Betrieb, kein stilles Zurueckholen aus dem Archiv.
3. Es gibt weiterhin KEIN Loesch-Werkzeug — der Vermerk ist Schutz, die
   Loeschung ist ein Menschen-Schritt mit Vier-Augen.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
        # F1 (03.09.2026): loeschantrag_vermerken schreibt in die TEST-Verbotsliste
        # (compliance_test, nie compliance) — je Test leeren, sonst blockiert
        # Doras Loeschantrag die naechste Erstansprache mit derselben Nummer.
        conn.execute("truncate compliance_test.sperrliste")
    yield


def _lead(name="Dora Datenschutz"):
    # existing_customer: UWG-Erstansprache-Tor (test_uwg.py) ist nicht Thema.
    lead = str(server._q(
        "insert into leads (name, phone, email, source, consent_status) "
        "values (%s, '+491709998877', 'dora@example.org', 'whatsapp', "
        "'existing_customer') returning id", (name,))[0]["id"])
    server.kontakt_freigeben(lead)
    return lead


def _enrichment(lead):
    return server._q("select enrichment from leads where id = %s",
                     (lead,))[0]["enrichment"]


# ---------------------------------------------------------------------------
# Auskunft — vollstaendig oder keine
# ---------------------------------------------------------------------------

def test_die_auskunft_traegt_alle_vier_abschnitte():
    lead = _lead()
    server.aktivitaet_loggen(lead, "notiz", "Rueckruf gewuenscht")
    server.entwurf_erstellen(lead, "whatsapp", "Hallo Dora!")
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert "fehler" not in antwort
    text = antwort["text"]
    for abschnitt in ("# Datenauskunft", "## Stammdaten", "## Anreicherung",
                      "## Protokoll", "## Entwuerfe"):
        assert abschnitt in text
    assert "Dora Datenschutz" in text
    assert "Rueckruf gewuenscht" in text
    assert "Hallo Dora!" in text
    assert antwort["protokollzeilen"] >= 2  # freigabe + notiz mindestens
    assert antwort["entwuerfe"] == 1


def test_auskunft_unbekannter_kontakt_ist_eine_meldung():
    antwort = json.loads(server.kontakt_auskunft(
        "00000000-0000-0000-0000-000000000000"))
    assert "fehler" in antwort


# ---------------------------------------------------------------------------
# Loeschantrag — Vermerk, Archiv, Vollstopp
# ---------------------------------------------------------------------------

def test_der_antrag_vermerkt_archiviert_und_protokolliert():
    lead = _lead()
    antwort = json.loads(server.loeschantrag_vermerken(
        lead, "WhatsApp-Nachricht", "bitte loeschen Sie meine Daten"))
    assert "fehler" not in antwort
    anr = _enrichment(lead)
    assert anr["_loeschantrag"]["quelle"] == "WhatsApp-Nachricht"
    assert anr["_loeschantrag"]["am"]
    assert server._archiviert(anr) is True
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'loeschantrag'", (lead,))
    assert len(zeilen) == 1


def test_ohne_quelle_kein_vermerk():
    lead = _lead()
    antwort = json.loads(server.loeschantrag_vermerken(lead, "  "))
    assert "fehler" in antwort
    assert server._loeschantrag(_enrichment(lead)) is None


def test_zweiter_antrag_ist_eine_meldung():
    lead = _lead()
    server.loeschantrag_vermerken(lead, "Telefonat")
    antwort = json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert "fehler" in antwort
    assert "liegt bereits vor" in antwort["fehler"]


def test_nach_dem_antrag_entsteht_kein_entwurf_mehr():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "Telefonat", "Ja gerne")
    server.loeschantrag_vermerken(lead, "WhatsApp-Nachricht")
    for versuch in (
            server.antwort_entwerfen(lead, "Noch eine Antwort."),
            server.entwurf_erstellen(lead, "whatsapp", "Hallo?")):
        antwort = json.loads(versuch)
        assert "fehler" in antwort
        assert "Loeschantrag" in antwort["fehler"]
    assert server._q("select count(*) n from drafts where lead_id = %s",
                     (lead,))[0]["n"] == 0


def test_kein_stilles_zurueckholen_aus_dem_archiv():
    lead = _lead()
    server.loeschantrag_vermerken(lead, "Telefonat")
    antwort = json.loads(server.kontakt_wiederherstellen(lead))
    assert "fehler" in antwort
    assert "Loeschantrag" in antwort["fehler"]
    assert server._archiviert(_enrichment(lead)) is True


def test_der_antrag_taucht_in_der_auskunft_auf():
    """Auch der Antrag selbst ist ein Datum ueber die Person — die
    Auskunft nennt ihn."""
    lead = _lead()
    server.loeschantrag_vermerken(lead, "E-Mail", "loeschen bitte")
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert "Loeschantrag" in antwort["text"]


@pytest.mark.parametrize("kaputt", [
    None, {}, {"_loeschantrag": None}, {"_loeschantrag": "ja"},
])
def test_kein_antrag_ist_kein_antrag(kaputt):
    assert server._loeschantrag(kaputt) is None


def test_ein_kaputter_vermerk_schuetzt_trotzdem():
    """Fail-closed in Schutzrichtung: ein dict-Vermerk ohne Datum zaehlt
    ALS Antrag — lieber zu viel gestoppt als weiterverarbeitet."""
    assert server._loeschantrag({"_loeschantrag": {"quelle": "?"}}) is not None


# ---------------------------------------------------------------------------
# Meeting-Mittelpunkt Task 14: Mitschriften im Loeschantrag und in der Auskunft
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

import termin_akte  # noqa: E402
import vexa  # noqa: E402

BEGINN = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def akten_leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield


def _akte(uid, lead=None, status="fertig", vexa_id=None, briefing=None):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, titel, status, "
        "vexa_meeting_id, vexa_plattform, vexa_native_id, briefing_md, "
        "briefing_stand, briefing_mit_ki, briefing_am) "
        "values (%s, 'sales-claw', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "returning uid",
        (uid, BEGINN, BEGINN + timedelta(hours=1), f"Termin {uid}", status,
         vexa_id, "google_meet" if vexa_id else None,
         "abc-defg-hij" if vexa_id else None, briefing,
         "stand" if briefing else None, True if briefing else None,
         BEGINN if briefing else None))
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
              "values (%s, 'chef@firma.de', 'Chef', 'organisator', null) "
              "returning uid", (uid,))
    if lead:
        server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
                  "values (%s, 'dora@example.org', 'Dora', 'gast', %s) returning uid",
                  (uid, lead))


def _mitschrift(uid, text="Geheimer Satz", entwurf_id=None):
    server._q(
        "insert into termin_mitschriften (uid, segmente, auswertung_status, "
        "auswertung_json, auswertung_md, entwurf_id) values (%s, %s::jsonb, "
        "'fertig', %s::jsonb, %s, %s) returning id",
        (uid, json.dumps([{"sprecher": "Dora", "text": text}]),
         json.dumps({"zusammenfassung": f"Zusammenfassung {uid}"}),
         f"Auswertung {uid}", entwurf_id))


def test_loeschantrag_loescht_mitschriften_aller_termine(akten_leer):
    lead = _lead()
    andere = _lead("Andi Anders")
    _akte("a1", lead, briefing="Briefing Dora Datenschutz")
    _akte("a2", lead, briefing="Briefing Dora Datenschutz")
    _akte("a3", andere, briefing="Briefing Andi")
    for uid in ("a1", "a2", "a3"):
        _mitschrift(uid)
    antwort = json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert "fehler" not in antwort
    uids = [z["uid"] for z in server._q("select uid from termin_mitschriften")]
    assert uids == ["a3"]
    # Briefing enthaelt Namen und Kontakte: weg bei a1/a2, bleibt bei a3.
    b = {z["uid"]: z for z in server._q(
        "select uid, briefing_md, briefing_stand, briefing_mit_ki, briefing_am "
        "from termin_akten")}
    for uid in ("a1", "a2"):
        assert (b[uid]["briefing_md"], b[uid]["briefing_stand"],
                b[uid]["briefing_mit_ki"], b[uid]["briefing_am"]) == (None,) * 4
    assert b["a3"]["briefing_md"] == "Briefing Andi"
    # Teilnehmerzeile: ausgeloest und gesperrt; die anderen bleiben.
    z = server._q("select lead_id, grund from termin_teilnehmer "
                  "where uid = 'a1' and adresse = 'dora@example.org'")[0]
    assert z["lead_id"] is None and z["grund"] == "gesperrt"
    assert str(server._q("select lead_id from termin_teilnehmer where uid = 'a3' "
                         "and adresse = 'dora@example.org'")[0]["lead_id"]) == andere


def test_loeschantrag_lehnt_offenen_zusammenfassungs_entwurf_ab(akten_leer):
    lead = _lead()
    entwurf = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Zusammenfassung"))
    entwurf_id = entwurf["draft_id"] if "draft_id" in entwurf else entwurf["id"]
    _akte("a1", lead)
    _mitschrift("a1", entwurf_id=entwurf_id)
    server.loeschantrag_vermerken(lead, "E-Mail")
    assert server._q("select status from drafts where id = %s",
                     (entwurf_id,))[0]["status"] != "pending"


def test_loeschantrag_beendet_laufenden_bot(akten_leer, monkeypatch):
    lead = _lead()
    _akte("l1", lead, status="laeuft", vexa_id=7)
    _akte("w1", lead, status="wartet_auf_einlass", vexa_id=8)
    _akte("f1", lead, status="fertig")
    gerufen = []
    monkeypatch.setattr(vexa, "bot_stoppen",
                        lambda p, n: gerufen.append(("stop", p, n)))
    monkeypatch.setattr(vexa, "meeting_loeschen",
                        lambda i: gerufen.append(("del", i)))
    server.loeschantrag_vermerken(lead, "E-Mail")
    # C1: Nur der Taktgeber spricht mit Vexa; hier nur Status und Absicht.
    assert gerufen == []
    st = {z["uid"]: z for z in server._q(
        "select uid, status, status_grund, vexa_meeting_id from termin_akten")}
    for uid, mid in (("l1", 7), ("w1", 8)):
        assert st[uid]["status"] == "ohne_aufnahme"
        assert st[uid]["status_grund"] == "Löschantrag eines Teilnehmers"
        assert st[uid]["vexa_meeting_id"] == mid       # der Taktgeber stoppt und loescht
    assert st["f1"]["status"] == "fertig"      # fertige Akte: Status bleibt


def test_auskunft_enthaelt_mitschrift(akten_leer):
    lead = _lead()
    andere = _lead("Andi Anders")
    _akte("a1", lead)
    _akte("a2", andere)
    _mitschrift("a1", text="Ich brauche ein Angebot")
    _mitschrift("a2", text="Fremder Satz")
    antwort = json.loads(server.kontakt_auskunft(lead))
    text = antwort["text"]
    assert "## Termine" in text and "Termin a1" in text
    assert "Ich brauche ein Angebot" in text and "Auswertung a1" in text
    assert "Zusammenfassung a1" in text
    # Nur eigene Akten, keine fremden Adressen.
    assert "Fremder Satz" not in text and "Termin a2" not in text
    assert "chef@firma.de" not in text
    assert antwort["termine"] == 1


def test_zwei_leads_in_einer_akte_antrag_von_a(akten_leer, monkeypatch):
    a = _lead()
    b = _lead("Bernd Beispiel")
    _akte("z1", a, status="laeuft", vexa_id=9, briefing="Briefing beide")
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
              "values ('z1', 'bernd@example.org', 'Bernd', 'gast', %s) returning uid",
              (b,))
    _mitschrift("z1")
    monkeypatch.setattr(vexa, "bot_stoppen", lambda p, n: None)
    geloescht = []
    monkeypatch.setattr(vexa, "meeting_loeschen",
                        lambda i: geloescht.append(i))
    server.loeschantrag_vermerken(a, "E-Mail")
    assert geloescht == []                     # C1: das macht der Taktgeber
    assert server._q("select 1 from termin_mitschriften") == []
    z = server._q("select status, briefing_md from termin_akten")[0]
    assert z["status"] == "ohne_aufnahme" and z["briefing_md"] is None
    zb = server._q("select lead_id, grund from termin_teilnehmer "
                   "where adresse = 'bernd@example.org'")[0]
    assert str(zb["lead_id"]) == b and zb["grund"] is None
    za = server._q("select lead_id, grund from termin_teilnehmer "
                   "where adresse = 'dora@example.org'")[0]
    assert za["lead_id"] is None and za["grund"] == "gesperrt"


def test_abraeumen_vor_dem_vermerk_zweiter_aufruf_klappt(akten_leer, monkeypatch):
    lead = _lead()
    _akte("r1", lead, briefing="Briefing")
    _mitschrift("r1")
    echt = termin_akte.mitschrift_entfernen
    zaehler = {"n": 0}

    def einmal_kaputt(uid):
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            raise RuntimeError("DB weg")
        return echt(uid)
    monkeypatch.setattr(termin_akte, "mitschrift_entfernen", einmal_kaputt)
    erst = json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert "Mitschriften nicht abgeraeumt" in erst["fehler"]
    assert _enrichment(lead).get(server.LOESCH_SCHLUESSEL) is None
    assert server._q("select 1 from activities where lead_id = %s "
                     "and type = 'loeschantrag'", (lead,)) == []
    assert len(server._q("select 1 from termin_mitschriften")) == 1
    zweit = json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert "fehler" not in zweit
    assert server._q("select 1 from termin_mitschriften") == []
    assert server._q("select briefing_md from termin_akten")[0]["briefing_md"] is None
    assert _enrichment(lead).get(server.LOESCH_SCHLUESSEL)


def test_nichts_davon_im_log(akten_leer, caplog):
    import logging
    lead = _lead()
    _akte("g1", lead, briefing="Briefing GEHEIMBRIEFING")
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle) values "
              "('g1', 'sentinel@geheim.example', 'Sentinel Sprecher', 'gast') "
              "returning uid")
    _mitschrift("g1", text="SENTINELSATZ vertraulich")
    with caplog.at_level(logging.DEBUG):
        server.kontakt_auskunft(lead)
        server.loeschantrag_vermerken(lead, "E-Mail")
    for geheim in ("SENTINELSATZ", "sentinel@geheim.example",
                   "Sentinel Sprecher", "GEHEIMBRIEFING", "dora@example.org"):
        assert geheim not in caplog.text, geheim


# --- Final-Review I5: Akten auch ueber die Adresse finden --------------------

def _akte_ueber_adresse(uid):
    """Teilnehmerzeile mit der Adresse des Kontakts, aber ohne lead_id (er war
    schon vorher gesperrt und wurde beim Abgleich ausgeloest)."""
    _akte(uid)
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id, grund) "
              "values (%s, 'Dora@Example.org', null, 'gast', null, 'gesperrt') "
              "returning uid", (uid,))


def test_i5_auskunft_und_loeschantrag_finden_ausgeloeste_akte(akten_leer):
    lead = _lead()
    _akte_ueber_adresse("s1")
    _mitschrift("s1", text="Satz aus der Sperrzeit")
    server._q("update termin_akten set briefing_md = 'Briefing s1' where uid = 's1' "
              "returning uid")
    antwort = json.loads(server.kontakt_auskunft(lead))
    assert antwort["termine"] == 1
    assert "Termin s1" in antwort["text"] and "Satz aus der Sperrzeit" in antwort["text"]
    assert "fehler" not in json.loads(server.loeschantrag_vermerken(lead, "E-Mail"))
    assert server._q("select 1 from termin_mitschriften where uid = 's1'") == []
    assert server._q("select briefing_md from termin_akten where uid = 's1'"
                     )[0]["briefing_md"] is None


def test_i6_ausgeloeste_zeile_behaelt_nur_die_adresse(akten_leer):
    lead = _lead()
    _akte("n1", lead)
    server.loeschantrag_vermerken(lead, "E-Mail")
    z = server._q("select lead_id, grund, name from termin_teilnehmer "
                  "where uid = 'n1' and adresse = 'dora@example.org'")[0]
    assert (z["lead_id"], z["grund"], z["name"]) == (None, "gesperrt", None)
    # die anderen Teilnehmer behalten ihren Namen
    assert server._q("select name from termin_teilnehmer where uid = 'n1' "
                     "and adresse = 'chef@firma.de'")[0]["name"] == "Chef"
