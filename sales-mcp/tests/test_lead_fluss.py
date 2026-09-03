"""F2-Logik ohne Datenbank: `q` wird aufgezeichnet. Die Tests halten fest,
WELCHE Leads in Frage kommen, WIE ein Kandidat aussieht, dass die
DB-Funktion genau einmal gerufen wird und dass ein Vorschlag am Lead
vermerkt wird (E6: nie zweimal vorschlagen)."""
import json

import lead_fluss


class Rekorder:
    def __init__(self, antworten=None):
        self.aufrufe = []
        self.antworten = list(antworten or [])

    def __call__(self, sql, params=()):
        self.aufrufe.append((sql, params))
        return self.antworten.pop(0) if self.antworten else []


ZEILEN = [
    {"id": "l1", "name": "Anna Apify", "email": "Anna@Firma.DE", "phone": "",
     "notes": "gefunden via b2b_leads", "enrichment": {"firma": {"name": "Firma GmbH"}}},
    {"id": "l2", "name": "Ohne Mail", "email": "", "phone": "+491701112233", "notes": "", "enrichment": {}},
    {"id": "l3", "name": "Kaputt", "email": "kein-mail", "phone": "", "notes": "", "enrichment": None},
]


def test_auswahl_filtert_recherche_ohne_einwilligung_mit_mail():
    q = Rekorder([[ZEILEN[0]]])
    lead_fluss.recherche_kandidaten(q, archiviert="ARCHIV(enrichment)", privat="PRIVAT(enrichment)")
    sql, params = q.aufrufe[0]
    assert "source = 'recherche'" in sql
    assert "consent_status = 'unknown'" in sql
    assert "coalesce(email, '') <> ''" in sql
    assert "not ARCHIV(enrichment)" in sql and "not PRIVAT(enrichment)" in sql
    assert "'an_marketing'" in sql           # E6: schon Vorgeschlagenes bleibt draussen
    assert params == ()


def test_erneut_hebt_den_vorschlagsfilter_auf():
    q = Rekorder([[]])
    lead_fluss.recherche_kandidaten(q, archiviert="A", privat="P", erneut=True)
    assert "'an_marketing'" not in q.aufrufe[0][0]


def test_lead_ids_grenzen_ein():
    q = Rekorder([[]])
    lead_fluss.recherche_kandidaten(q, archiviert="A", privat="P", lead_ids=["l1", "l2"])
    sql, params = q.aufrufe[0]
    assert "id::text = any(%s)" in sql
    assert params == (["l1", "l2"],)


def test_kandidatenform_klein_und_ohne_kaputte():
    k = lead_fluss.kandidaten_form(ZEILEN)
    assert k == [{"email": "anna@firma.de", "display_name": "Anna Apify",
                  "company": "Firma GmbH", "notiz": "gefunden via b2b_leads"}]


def test_vorschlagen_ruft_die_funktion_genau_einmal_mit_json():
    q = Rekorder([[{"ergebnis": {"proposal_id": "p-1", "angenommen": 1,
                                  "uebersprungen_gesperrt": 0, "uebersprungen_ungueltig": 0}}]])
    erg = lead_fluss.vorschlagen(q, "Name", "Grund", [{"email": "a@x.de"}])
    assert erg["proposal_id"] == "p-1"
    assert len(q.aufrufe) == 1
    sql, params = q.aufrufe[0]
    assert "marketing.vorschlag_aus_sales(%s, %s, %s::jsonb)" in sql
    assert params[0] == "Name" and params[1] == "Grund"
    assert json.loads(params[2]) == [{"email": "a@x.de"}]


def test_vorschlagen_liest_auch_string_ergebnis():
    q = Rekorder([[{"ergebnis": json.dumps({"proposal_id": None, "angenommen": 0,
                                            "uebersprungen_gesperrt": 1, "uebersprungen_ungueltig": 0})}]])
    erg = lead_fluss.vorschlagen(q, "N", "G", [{"email": "a@x.de"}])
    assert erg["proposal_id"] is None and erg["uebersprungen_gesperrt"] == 1


def test_vermerken_schreibt_enrichment_und_aktivitaet_je_lead():
    q = Rekorder()
    n = lead_fluss.vermerken(q, ["l1", "l2"], "p-1", "2026-09-03T10:00:00+00:00")
    assert n == 2
    updates = [s for s, _ in q.aufrufe if "jsonb_set" in s]
    aktivitaeten = [p for s, p in q.aufrufe if "insert into activities" in s]
    assert len(updates) == 2 and len(aktivitaeten) == 2
    assert aktivitaeten[0][1] == "an_marketing"
    assert json.loads(aktivitaeten[0][2])["proposal_id"] == "p-1"
