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
    # Kontaktliste nach der Papiervorlage (28.10.2026): Score und Zuletzt sind
    # keine eigenen Spalten mehr, die Stufe steht als Chip beim Namen.
    for spalte in ("Name / Anschrift", "Telefon", "Termine", "Autonomie"):
        assert f'data-label="{spalte}"' in seite, spalte
    assert 'data-label="Consent"' not in seite
    assert '<span class="stufe termin">termin</span>' in seite
    assert '<span class="stufe geantwortet">geantwortet</span>' in seite


def test_consent_steht_als_meta_unter_dem_namen():
    _lead("Anna Beispiel", "+491700000004")
    seite = _get("/kontakte").text
    zeile = seite[seite.index("Anna Beispiel"):]
    assert "Newsletter: nein" in zeile[:600]      # Ja/Nein seit 28.10.2026
    assert "Consent: unknown" not in seite


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


# --- C1 Aufgabe 3 (16.10.2026): Reiter, Bereich-Filter, Suche, Blaettern ---
import json as _json_t  # noqa: E402


def _lead_e(name, company=None, enrichment=None, phone=None):
    return str(server._q(
        "insert into leads (name, company, phone, enrichment) values (%s, %s, %s, %s::jsonb) "
        "returning id", (name, company, phone, _json_t.dumps(enrichment or {})))[0]["id"])


def test_reiter_und_anzahlen():
    _lead_e("Pia Person", enrichment={"art": "person", "bereiche": ["mitarbeiter"]})
    _lead_e("Firma Alpha", company="Alpha GmbH", enrichment={"bereiche": ["bav"]})
    _lead_e("Offen Otto")
    seite = _get("/kontakte?ansicht=mitarbeiter").text
    assert "Pia Person" in seite and "Firma Alpha" not in seite and "Offen Otto" not in seite
    assert "Firma Alpha" in _get("/kontakte?ansicht=firmen").text
    offen = _get("/kontakte?ansicht=offen").text
    assert "Offen Otto" in offen and "Pia Person" not in offen
    alle = _get("/kontakte").text
    assert "Mitarbeiter-Kandidaten (1)" in alle and "Nicht eingeordnet (1)" in alle


def test_bereich_filter():
    _lead_e("Ina IT", enrichment={"bereiche": ["it"]})
    _lead_e("Hans Homelab", enrichment={"bereiche": ["homelab"]})
    seite = _get("/kontakte?bereich=it").text
    assert "Ina IT" in seite and "Hans Homelab" not in seite


def test_unbekannte_ansicht_und_bereich_gelten_als_alle():
    _lead_e("Zora Ziel")
    assert _get("/kontakte?ansicht=quatsch&bereich=quatsch").status_code == 200


def test_suche_name_firma_telefon_und_sonderzeichen():
    _lead_e("Klara Klee", company="Blumen 100% GmbH", phone="+49 171 2345678")
    _lead_e("Bert Andere")
    assert "Klara Klee" in _get("/kontakte?q=klee").text
    assert "Klara Klee" in _get("/kontakte?q=blumen").text
    assert "Klara Klee" in _get("/kontakte?q=2345678").text
    r = _get("/kontakte?q=100%25")
    assert r.status_code == 200 and "Klara Klee" in r.text and "Bert Andere" not in r.text
    for q in ("%25", "_", "%27", "%5C"):
        assert _get(f"/kontakte?q={q}").status_code == 200
    assert "Bert Andere" not in _get("/kontakte?q=%25").text


def test_kaputte_bereiche_gelten_als_offen():
    _lead_e("Kaputt Karl", enrichment={"bereiche": "bav"})
    assert "Kaputt Karl" in _get("/kontakte?ansicht=offen").text


def test_blaettern_ueber_500():
    with server.pool.connection() as conn:
        conn.execute("insert into sales_test.leads (name) select 'Massen ' || "
                     "lpad(g::text, 4, '0') from generate_series(1, 567) g")
    namen = set()
    for s in range(1, 7):
        t = _get(f"/kontakte?seite={s}").text
        namen |= {n for n in (f"Massen {i:04d}" for i in range(1, 568)) if n in t}
    assert len(namen) == 567
    for s in ("0", "-3", "abc", "999"):
        assert _get(f"/kontakte?seite={s}").status_code == 200


def test_einordnung_spalte_zeigt_chips():
    _lead_e("Chip Chen", enrichment={"art": "person", "bereiche": ["vorsorge"]})
    seite = _get("/kontakte").text
    assert "Private Vorsorge/Versicherung" in seite


def test_sql_ansichten_folgen_genau_server_einordnung():
    # Randfaelle, an denen eine SQL-Nachbildung typischerweise abweicht:
    # Gross-/Kleinschreibung, Nicht-Text-Art, nur unbekannte Bereiche,
    # Bereiche als null/Objekt, Firmenfeld nur aus Leerraum.
    faelle = [
        ({"art": "Person", "bereiche": ["mitarbeiter"]}, "X GmbH"),
        ({"art": 5, "bereiche": ["quatsch"]}, None),
        ({"art": "firma", "bereiche": ["mitarbeiter", "bav"]}, None),
        ({"bereiche": None}, "   "),
        ({"bereiche": {"it": True}}, "\t\n"),
        ({"bereiche": ["mitarbeiter", 7]}, ""),
        ({"art": "person", "bereiche": []}, "Firma"),
        ({}, " Firma "),
    ]
    for i, (enr, firma) in enumerate(faelle):
        _lead_e(f"Fall {i:02d}", company=firma, enrichment=enr)
    erwartet = {"personen": set(), "firmen": set(), "mitarbeiter": set(),
                "offen": set()}
    for i, (enr, firma) in enumerate(faelle):
        art, bereiche = server._einordnung(enr, firma)
        name = f"Fall {i:02d}"
        erwartet["personen" if art == "person" else "firmen"].add(name)
        if art == "person" and "mitarbeiter" in bereiche:
            erwartet["mitarbeiter"].add(name)
        if not bereiche:
            erwartet["offen"].add(name)
    for ansicht, namen in erwartet.items():
        seite = _get(f"/kontakte?ansicht={ansicht}").text
        gesehen = {f"Fall {i:02d}" for i in range(len(faelle))
                   if f">Fall {i:02d}<" in seite}
        assert gesehen == namen, ansicht


def test_einordnung_zaehlt_nicht_als_letzte_aktivitaet():
    """Final-Review I3: der Bestandslauf bucht je Kontakt eine Aktivitaet
    `einordnung`. Die darf weder „Zuletzt" noch die Reihenfolge der Liste
    verschieben — sonst stuende danach ueberall der Deploy-Zeitpunkt."""
    alt = _lead("Alt Kontakt", "+491700000201")
    neu = _lead("Neu Kontakt", "+491700000202")
    for lead, tage in ((alt, 3), (neu, 1)):
        server._q("insert into activities (lead_id, type, payload, created_at) "
                  "values (%s, 'kundenantwort', '{}'::jsonb, "
                  "now() - make_interval(days => %s)) returning id", (lead, tage))
    assert "art" in server._einordnen(alt, "person", ["bav"], quelle="bestand")
    nur = _lead("Nur Einordnung", "+491700000203")
    assert "art" in server._einordnen(nur, "firma", quelle="ui")
    seite = _get("/kontakte").text
    # Sortiert nach letztem Kontaktgeschehen; die Einordnung zaehlt nicht -
    # „Nur Einordnung" steht deshalb hinter beiden.
    assert seite.index("Neu Kontakt") < seite.index("Alt Kontakt") \
        < seite.index("Nur Einordnung")



# --- Filter im Tabellenkopf (19.10.2026, Betreiber: "die Ordnung sollte mit in der Tabelle sein") ---

def test_filter_stehen_im_tabellenkopf():
    _lead_e("Ina IT", enrichment={"bereiche": ["it"]})
    seite = _get("/kontakte?ansicht=personen&bereich=it&q=Ina").text
    kopf = seite[seite.index("<thead"):seite.index("</thead>")]
    assert '<tr class="filterzeile">' in kopf
    assert '<select name="ansicht" form="kfilter"' in kopf
    assert '<option value="personen" selected>Personen (1)</option>' in kopf
    assert '<select name="bereich" form="kfilter"' in kopf
    assert '<option value="it" selected>IT-Lösung</option>' in kopf
    assert 'name="q" form="kfilter" value="Ina"' in kopf
    assert '<form id="kfilter" method="get" action="/kontakte">' in seite
    assert '<nav class="filterleiste" aria-label="Ansicht">' not in seite
    assert '<nav class="filterleiste" aria-label="Bereich">' not in seite
    assert "Filter zurücksetzen" in seite


def test_filterzeile_bleibt_auch_ohne_treffer():
    seite = _get("/kontakte?q=gibtesnicht").text
    assert '<tr class="filterzeile">' in seite and "Keine Kontakte." in seite


def test_einordnung_zeigt_bereiche_oder_hinweis():
    _lead_e("Ina IT", enrichment={"bereiche": ["it", "bav"]})
    _lead_e("Offen Otto")
    seite = _get("/kontakte").text
    ina = seite[seite.index(">Ina IT<"):][:1500]
    assert ">IT-Lösung<" in ina and ">bAV<" in ina
    otto = seite[seite.index(">Offen Otto<"):][:1500]
    assert "kein Bereich" in otto
