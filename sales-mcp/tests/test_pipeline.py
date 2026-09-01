"""Vertragstests fuer die Pipeline-Stufen.

Befund vom 27.08.2026: `leads.status` existierte von Anfang an (samt
score-Spalten), aber ALLE 34 Leads standen auf `new` — kein Werkzeug hat
je ein Stadium bewegt. Der Betreiber will eine gelebte Pipeline.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Es gibt GENAU die acht Stufen des Schema-Constraints, und nur die.
   Ein Tippfehler wird zur
   Meldung, nie zu einem stillen Phantasie-Stadium in der Datenbank.
2. Jeder Wechsel ist ein Beweis: leads.status UND eine activities-Zeile
   mit von/nach/Begruendung. Ein Feld, das sich aendert, ohne dass das
   Protokoll sagt warum, gibt es nicht.
3. Der Altbestand (`new`) wird beim Lesen als `neu` gedeutet — keine
   Migration noetig, kein Kontakt faellt aus der Ansicht.
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
    yield


def _lead(status="new"):
    return str(server._q(
        "insert into leads (name, phone, source, status) values "
        "('Pia Pipeline', '+491701112233', 'whatsapp', %s) returning id",
        (status,))[0]["id"])


def _status(lead):
    return server._q("select status from leads where id = %s",
                     (lead,))[0]["status"]


# ---------------------------------------------------------------------------
# Der Vertrag: acht Stufen, Begruendung Pflicht, Beweiszeile
# ---------------------------------------------------------------------------

def test_die_stufen_folgen_dem_schema_wortschatz():
    """Das Schema kannte die Pipeline laengst: leads_status_check erlaubt
    acht Werte (gemessen 27.08.2026). Der deutsche Satz bildet GENAU sie
    ab — keine Parallelwelt neben dem Constraint."""
    assert server.PIPELINE_STUFEN == (
        "neu", "recherchiert", "qualifiziert", "kontaktiert",
        "geantwortet", "termin", "gewonnen", "verloren")
    assert set(server.STUFEN_DB.values()) == {
        "new", "researched", "qualified", "contacted", "replied",
        "meeting", "won", "lost"}


def test_die_datenbank_traegt_den_constraint_wert():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin am Freitag 10 Uhr")
    assert _status(lead) == "meeting"


def test_wechsel_schreibt_feld_und_beweis():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Erstnachricht am 27.08. beantwortet"))
    assert antwort["von"] == "neu"
    assert antwort["nach"] == "kontaktiert"
    assert _status(lead) == "contacted"
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'stufenwechsel'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["von"] == "neu"
    assert zeilen[0]["payload"]["nach"] == "kontaktiert"
    assert "Erstnachricht" in zeilen[0]["payload"]["begruendung"]


def test_unbekannte_stufe_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "vielleicht", "egal"))
    assert "fehler" in antwort
    assert "neu" in antwort["fehler"]  # die Meldung nennt die gueltigen
    assert _status(lead) == "new"      # nichts geschrieben


def test_ohne_begruendung_kein_wechsel():
    lead = _lead()
    antwort = json.loads(server.kontakt_stufe_setzen(lead, "termin", "  "))
    assert "fehler" in antwort
    assert "Begruendung" in antwort["fehler"]
    assert _status(lead) == "new"


def test_gleiche_stufe_ist_eine_meldung():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin steht")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "termin", "nochmal"))
    assert "fehler" in antwort
    assert "steht schon" in antwort["fehler"]


def test_rueckwaertsgang_ist_erlaubt_und_belegt():
    lead = _lead()
    server.kontakt_stufe_setzen(lead, "termin", "Termin vereinbart")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Angebot zurueckgezogen, Kunde ueberlegt neu"))
    assert "fehler" not in antwort
    assert _status(lead) == "contacted"


def test_unbekannter_kontakt_ist_eine_meldung():
    antwort = json.loads(server.kontakt_stufe_setzen(
        "00000000-0000-0000-0000-000000000000", "termin", "egal"))
    assert "fehler" in antwort


def test_altbestand_new_wird_als_neu_gedeutet():
    lead = _lead(status="new")
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead, "kontaktiert", "Altbestand angefasst"))
    assert antwort["von"] == "neu"


# ---------------------------------------------------------------------------
# Digest zaehlt je Stufe
# ---------------------------------------------------------------------------

def test_digest_zaehlt_die_pipeline():
    a = _lead()
    _lead()
    server.kontakt_stufe_setzen(a, "termin", "Termin am Freitag")
    d = json.loads(server.digest())
    assert d["pipeline"]["neu"] == 1
    assert d["pipeline"]["termin"] == 1


# ---------------------------------------------------------------------------
# Automatischer Abgleich (01.09.2026): Stufen, die als Beweis im Protokoll
# stehen, zieht stufen_abgleichen() nach — nur VORWAERTS, nur bis 'termin'
# (gewonnen/verloren/qualifiziert bleiben Urteile), jede Bewegung mit
# Begruendung. Betreiber-Wunsch: 39 Kontakte standen auf 'neu', obwohl
# hunderte Nachrichten laengst bewiesen, wie weit sie wirklich sind.
# ---------------------------------------------------------------------------

def _aktivitaet(lead, typ, payload=None):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, %s, %s) returning id",
              (lead, typ, server._json(payload or {"text": "x"})))


def _abgleich():
    return json.loads(server.stufen_abgleichen())


def _wechsel(lead):
    return server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'stufenwechsel' order by created_at", (lead,))


def test_kundenantwort_beweist_geantwortet():
    lead = _lead()
    _aktivitaet(lead, "kundenantwort")
    ergebnis = _abgleich()
    assert ergebnis["nachgezogen"] == 1
    assert _status(lead) == "replied"
    beweis = _wechsel(lead)
    assert len(beweis) == 1
    assert beweis[0]["payload"]["nach"] == "geantwortet"
    assert "automatisch" in beweis[0]["payload"]["begruendung"]


def test_nur_ausgang_beweist_kontaktiert():
    lead = _lead()
    _aktivitaet(lead, "nachricht_ausgehend")
    _abgleich()
    assert _status(lead) == "contacted"


def test_versand_zaehlt_wie_ausgang():
    lead = _lead()
    _aktivitaet(lead, "versand")
    _abgleich()
    assert _status(lead) == "contacted"


def test_termin_beweist_termin():
    lead = _lead()
    _aktivitaet(lead, "kundenantwort")
    _aktivitaet(lead, "termin", {"datum": "2026-09-03"})
    _abgleich()
    assert _status(lead) == "meeting"


def test_niemals_rueckwaerts():
    """Ein gewonnener Kontakt, der nochmal schreibt, faellt nicht auf
    'geantwortet' zurueck — und ein Termin-Kontakt auch nicht."""
    gewonnen = _lead(status="won")
    _aktivitaet(gewonnen, "kundenantwort")
    termin = _lead(status="meeting")
    _aktivitaet(termin, "kundenantwort")
    ergebnis = _abgleich()
    assert ergebnis["nachgezogen"] == 0
    assert _status(gewonnen) == "won"
    assert _status(termin) == "meeting"


def test_qualifiziert_geht_vorwaerts_auf_geantwortet():
    lead = _lead(status="qualified")
    _aktivitaet(lead, "kundenantwort")
    _abgleich()
    assert _status(lead) == "replied"


def test_zweiter_lauf_aendert_nichts():
    lead = _lead()
    _aktivitaet(lead, "kundenantwort")
    _abgleich()
    ergebnis = _abgleich()
    assert ergebnis["nachgezogen"] == 0
    assert len(_wechsel(lead)) == 1


def test_ohne_beweis_keine_bewegung():
    lead = _lead()
    _aktivitaet(lead, "notiz")
    ergebnis = _abgleich()
    assert ergebnis["nachgezogen"] == 0
    assert _status(lead) == "new"


def test_archivierte_private_und_systemkontakte_bleiben_stehen(monkeypatch):
    archiv = str(server._q(
        "insert into leads (name, source, enrichment) values "
        "('Alt Archiv', 'whatsapp', "
        "'{\"archiviert\": {\"archiviert\": true, \"am\": \"2026-08-01\"}}'"
        "::jsonb) returning id")[0]["id"])
    privat = str(server._q(
        "insert into leads (name, source, enrichment) values "
        "('Lisa Privat', 'whatsapp', '{\"_privat\": {}}'::jsonb) "
        "returning id")[0]["id"])
    system = _lead()
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", system)
    for lead in (archiv, privat, system):
        _aktivitaet(lead, "kundenantwort")
    ergebnis = _abgleich()
    assert ergebnis["nachgezogen"] == 0
    for lead in (archiv, privat, system):
        assert _status(lead) == "new"


def test_abgleich_meldet_die_bilanz():
    a = _lead()
    _aktivitaet(a, "kundenantwort")
    _lead()                                 # ohne Beweis
    ergebnis = _abgleich()
    assert ergebnis["geprueft"] == 2
    assert ergebnis["nachgezogen"] == 1
    assert ergebnis["wechsel"][0]["nach"] == "geantwortet"


def test_firmendaten_beweisen_recherchiert():
    lead = _lead()
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true) where id = %s returning id",
        (server._json({"website": "https://x.de", "seiten": []}), lead))
    _abgleich()
    assert _status(lead) == "researched"


def test_kundenantwort_schlaegt_firmendaten():
    lead = _lead()
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true) where id = %s returning id",
        (server._json({"website": "https://x.de"}), lead))
    _aktivitaet(lead, "kundenantwort")
    _abgleich()
    assert _status(lead) == "replied"
