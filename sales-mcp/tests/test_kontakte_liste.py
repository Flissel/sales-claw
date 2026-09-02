"""Verträge über die Kontaktliste — Schritt 5 des UI-Plans (02.09.2026):
eine Zeile pro Kontakt mit Stufe, Score, letzter Aktivität und Autonomie
als Segment; kein Auswahlfeld mit Setzen-Knopf mehr je Zeile.
"""
import pytest
from starlette.testclient import TestClient

import server
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _lead(name, phone, status=None, score=None):
    return str(server._q(
        "insert into leads (name, phone, source, status, score) "
        "values (%s, %s, 'whatsapp', coalesce(%s, 'new'), %s) returning id",
        (name, phone, status, score))[0]["id"])


def test_spalten_stufe_score_zuletzt_autonomie():
    _lead("Hoch Score", "+491700000001", status="meeting", score=72)
    _lead("Mittel Score", "+491700000002", status="replied", score=35)
    _lead("Ohne Score", "+491700000003")
    seite = _get("/kontakte").text
    for spalte in ("Name", "Stufe", "Score", "Zuletzt", "Autonomie"):
        assert f'data-label="{spalte}"' in seite, spalte
    assert 'data-label="Consent"' not in seite
    assert '<span class="score hoch">72</span>' in seite
    assert '<span class="score mittel">35</span>' in seite
    assert '<span class="stufe termin">termin</span>' in seite
    assert '<span class="stufe geantwortet">geantwortet</span>' in seite
    ohne = seite[seite.index("Ohne Score"):]
    assert '<span class="score leer">—</span>' in ohne[:1500]


def test_consent_steht_als_meta_unter_dem_namen():
    _lead("Anna Beispiel", "+491700000004")
    seite = _get("/kontakte").text
    zeile = seite[seite.index("Anna Beispiel"):]
    assert "Consent: unknown" in zeile[:600]


def test_autonomie_ist_ein_segment_ohne_auswahlfeld():
    lead = _lead("Segment Person", "+491700000005")
    seite = _get("/kontakte").text
    assert '<select name="stufe"' not in seite
    assert seite.count('<span class="an">') == 1
    for stufe in server.AUTONOMIE_STUFEN:
        assert (f'<input type="hidden" name="stufe" value="{stufe}">' in seite
                or f'<span class="an">{stufe}</span>' in seite), stufe
    assert f'<input type="hidden" name="lead_id" value="{lead}">' in seite
    assert 'action="/kontakte/autonomie"' in seite


def test_sammelkontakt_hat_weder_segment_noch_archivknopf(sammel=None):
    seite = _get("/kontakte").text
    # Ohne Kontakte gibt es keine Zeilen — die Seite sagt es.
    assert "Keine Kontakte." in seite
