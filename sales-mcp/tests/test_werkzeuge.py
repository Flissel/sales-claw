"""Vertragstests gegen sales_test. Die Suite darf NIE gegen `sales` laufen —
`sales.activities` ist append-only und ließe sich nicht zurücksetzen."""
import json
import os

import pytest

os.environ.setdefault("SALES_DB_SCHEMA", "sales_test")
import server  # noqa: E402  — liest SALES_DB_SCHEMA beim Import


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _anlegen(name="Max Testperson"):
    return json.loads(server.kontakt_anlegen(name=name, phone="+490000000001"))


def test_kontakt_anlegen_und_suchen():
    neu = _anlegen()
    assert neu["lead_id"]
    treffer = json.loads(server.kontakt_suchen("testperson"))
    assert treffer["kontakte"][0]["lead_id"] == neu["lead_id"]


def test_suche_ohne_treffer_ist_leer_und_kein_fehler():
    treffer = json.loads(server.kontakt_suchen("gibtsnicht"))
    assert treffer["kontakte"] == []


def test_aktivitaet_landet_im_protokoll():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.aktivitaet_loggen(lead, "nachricht", "Kunde fragt nach Termin"))
    assert ok["geloggt"] is True
    profil = json.loads(server.profil_lesen(lead))
    assert profil["aktivitaeten"][0]["type"] == "nachricht"


def test_profil_aktualisieren_ist_kumulativ():
    lead = _anlegen()["lead_id"]
    server.profil_aktualisieren(lead, "beruf", "Lehrerin")
    server.profil_aktualisieren(lead, "wohnort", "Regensburg")
    profil = json.loads(server.profil_lesen(lead))
    assert profil["profil"]["beruf"] == "Lehrerin"
    assert profil["profil"]["wohnort"] == "Regensburg"


def test_unbekannte_lead_id_gibt_fehlertext():
    kaputt = json.loads(server.profil_lesen("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


def test_bedarf_speichern_und_offene_schrumpfen():
    lead = _anlegen()["lead_id"]
    vorher = json.loads(server.bedarf_offen(lead))
    server.bedarf_speichern(lead, "alter", "34")
    nachher = json.loads(server.bedarf_offen(lead))
    assert vorher["anzahl_offen"] - nachher["anzahl_offen"] == 1
    profil = json.loads(server.profil_lesen(lead))
    assert profil["bedarf"]["alter"]["antwort"] == "34"


def test_bedarf_unbekannte_frage_wird_abgelehnt():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.bedarf_speichern(lead, "schuhgroesse", "44"))
    assert "fehler" in kaputt


def test_consent_frage_setzt_consent_status():
    lead = _anlegen()["lead_id"]
    server.bedarf_speichern(lead, "consent_kontakt", "ja, gerne")
    profil = json.loads(server.profil_lesen(lead))
    assert profil["consent"] == "opt_in"


def test_entwurf_bleibt_pending():
    lead = _anlegen()["lead_id"]
    e = json.loads(server.entwurf_erstellen(lead, "linkedin",
                                            "Hallo Herr Testperson, ..."))
    assert e["status"] == "pending"
    zeilen = server._q("select status, channel from drafts")
    assert zeilen == [{"status": "pending", "channel": "linkedin"}]


def test_entwurf_unzulaessiger_kanal():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.entwurf_erstellen(lead, "brieftaube", "x"))
    assert "fehler" in kaputt


def test_digest_nennt_offene_entwuerfe():
    lead = _anlegen()["lead_id"]
    server.entwurf_erstellen(lead, "whatsapp", "Follow-up-Text")
    d = json.loads(server.digest())
    assert d["offene_entwuerfe"][0]["kanal"] == "whatsapp"
    assert d["anzahl_entwuerfe"] == 1


def test_werkzeug_signaturen_ueberleben_den_dekorator():
    import inspect
    assert "name" in inspect.signature(server.kontakt_anlegen).parameters
    assert "frage_id" in inspect.signature(server.bedarf_speichern).parameters


# ---------------------------------------------------------------------------
# T2 — Freigabe-Werkzeuge (entwuerfe_offen, entwurf_freigeben,
# entwurf_ablehnen, entwurf_manuell_gesendet)
# ---------------------------------------------------------------------------

def _entwurf(lead_id, kanal="whatsapp", text="Text"):
    return json.loads(server.entwurf_erstellen(lead_id, kanal, text))["draft_id"]


def _zeile(draft_id):
    zeilen = server._q(
        "select status, channel, approved_by, approved_at, sent_at "
        "from drafts where id = %s", (draft_id,))
    return zeilen[0]


# --- entwurf_freigeben ---

def test_freigeben_pending_wird_approved():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    ok = json.loads(server.entwurf_freigeben(draft))
    assert ok["status"] == "approved"
    zeile = _zeile(draft)
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "betreiber"
    assert zeile["approved_at"] is not None


def test_freigeben_loggt_aktivitaet():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    akt = server._q(
        "select payload from activities where lead_id = %s and type = 'freigabe'",
        (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["kanal"] == "whatsapp"
    assert akt[0]["payload"]["draft_id"] == str(draft)


def test_freigeben_eines_bereits_freigegebenen_schlaegt_fehl_und_aendert_nichts():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_freigeben(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_freigeben_unbekannte_draft_id_gibt_fehlertext():
    kaputt = json.loads(
        server.entwurf_freigeben("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# --- entwurf_ablehnen ---

def test_ablehnen_pending_wird_rejected():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "email")
    ok = json.loads(server.entwurf_ablehnen(draft))
    assert ok["status"] == "rejected"
    assert _zeile(draft)["status"] == "rejected"


def test_ablehnen_loggt_aktivitaet():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "email")
    server.entwurf_ablehnen(draft)
    akt = server._q(
        "select payload from activities where lead_id = %s and type = 'ablehnung'",
        (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["draft_id"] == str(draft)


def test_ablehnen_eines_bereits_abgelehnten_schlaegt_fehl_und_aendert_nichts():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "email")
    server.entwurf_ablehnen(draft)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_ablehnen(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_ablehnen_unbekannte_draft_id_gibt_fehlertext():
    kaputt = json.loads(
        server.entwurf_ablehnen("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# --- entwurf_manuell_gesendet ---

def test_manuell_gesendet_approved_linkedin_wird_sent():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "linkedin")
    server.entwurf_freigeben(draft)
    ok = json.loads(server.entwurf_manuell_gesendet(draft))
    assert ok["status"] == "sent"
    zeile = _zeile(draft)
    assert zeile["status"] == "sent"
    assert zeile["sent_at"] is not None


def test_manuell_gesendet_loggt_aktivitaet_mit_weg_manuell():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "linkedin")
    server.entwurf_freigeben(draft)
    server.entwurf_manuell_gesendet(draft)
    akt = server._q(
        "select payload from activities where lead_id = %s and type = 'versand'",
        (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["weg"] == "manuell"
    assert akt[0]["payload"]["kanal"] == "linkedin"


def test_manuell_gesendet_auf_whatsapp_draft_schlaegt_fehl_und_aendert_nichts():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_manuell_gesendet(draft))
    assert kaputt["fehler"] == "nur für LinkedIn — WhatsApp versendet der Dispatcher"
    assert _zeile(draft) == vor


def test_manuell_gesendet_auf_pending_linkedin_schlaegt_fehl_und_aendert_nichts():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "linkedin")  # bleibt pending, nicht freigegeben
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_manuell_gesendet(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_manuell_gesendet_unbekannte_draft_id_gibt_fehlertext():
    kaputt = json.loads(
        server.entwurf_manuell_gesendet("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# --- entwuerfe_offen ---

def test_entwuerfe_offen_zeigt_pending_und_approved_linkedin_nicht_approved_whatsapp_nicht_sent():
    lead = _anlegen()["lead_id"]
    d_pending_wa = _entwurf(lead, "whatsapp", "Text A")
    d_approved_li = _entwurf(lead, "linkedin", "Text B")
    server.entwurf_freigeben(d_approved_li)
    d_approved_wa = _entwurf(lead, "whatsapp", "Text C")
    server.entwurf_freigeben(d_approved_wa)
    d_sent_li = _entwurf(lead, "linkedin", "Text D")
    server.entwurf_freigeben(d_sent_li)
    server.entwurf_manuell_gesendet(d_sent_li)

    ergebnis = json.loads(server.entwuerfe_offen())
    ids = {e["draft_id"] for e in ergebnis["entwuerfe"]}
    assert ids == {d_pending_wa, d_approved_li}
    assert d_approved_wa not in ids
    assert d_sent_li not in ids


def test_entwuerfe_offen_kuerzt_text_und_zeigt_kontaktnamen():
    lead = _anlegen(name="Lange Testperson")["lead_id"]
    langer_text = "x" * 300
    draft = _entwurf(lead, "whatsapp", langer_text)
    ergebnis = json.loads(server.entwuerfe_offen())
    eintrag = next(e for e in ergebnis["entwuerfe"] if e["draft_id"] == draft)
    assert len(eintrag["text"]) == 200
    assert eintrag["kontakt"] == "Lange Testperson"
    assert eintrag["kanal"] == "whatsapp"
    assert eintrag["status"] == "pending"
    assert eintrag["empfaenger"]
