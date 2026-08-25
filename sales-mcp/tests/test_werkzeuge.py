"""Vertragstests gegen sales_test. Die Suite darf NIE gegen `sales` laufen —
`sales.activities` ist append-only und ließe sich nicht zurücksetzen."""
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen. Der
# Schutz muss konstruktiv sein, nicht von der Disziplin des Aufrufers abhaengen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import medien  # noqa: E402
import nummern  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein.

    `server.SCHEMA` wird beim Import ausgewertet und steuert den search_path
    des Verbindungspools. Stimmt er nicht, bricht die Suite ab, BEVOR die
    erste Fixture etwas truncatet."""
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


def _wa_freigeben(lead_id):
    """Kontakt-Freigabe direkt in enrichment setzen — ohne den Werkzeugweg.

    Die Werkzeuge selbst (kontakt_freigeben, kontakt_freigabe_entziehen) und
    das Gate prueft tests/test_kontakt_freigabe.py; hier geht es nur darum,
    das Gate zu oeffnen, damit die uebrigen Vertragstests ihr eigentliches
    Thema testen — ohne zusaetzliche kontakt_freigabe-Aktivitaeten im
    Protokoll."""
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, "
        "'{whatsapp_freigabe}', '{\"freigegeben\": true}'::jsonb, true) "
        "where id = %s returning id", (lead_id,))


def _anlegen(name="Max Testperson", phone="+490000000001"):
    neu = json.loads(server.kontakt_anlegen(name=name, phone=phone))
    _wa_freigeben(neu["lead_id"])
    return neu


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


def test_leitfaden_reihenfolge_anlass_zuerst_termin_vor_consent():
    """Verkäufer-Ausrichtung (Stufe 4): 'anlass' steht ganz vorn, 'termin'
    kommt vor 'consent'. Bestehende Gruppen/frage_ids bleiben unangetastet —
    diese Prüfung geht ausschließlich über die Reihenfolge der Gruppen-ids."""
    ids = [g["id"] for g in server.LEITFADEN["gruppen"]]
    assert ids[0] == "anlass"
    assert ids.index("termin") < ids.index("consent")


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
    _wa_freigeben(lead_id)      # idempotent — auch fuer per SQL angelegte Leads
    return json.loads(server.entwurf_erstellen(lead_id, kanal, text))["draft_id"]


def _zeile(draft_id):
    zeilen = server._q(
        "select status, channel, approved_by, approved_at, sent_at, error "
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
    assert kaputt["fehler"] == ("nur fuer LinkedIn — WhatsApp und E-Mail "
                                "versenden die Dispatcher-Dienste")
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


# ---------------------------------------------------------------------------
# T4 — entwurf_erneut_freigeben (failed -> approved, Doppelversand-Schutz)
#
# Ein "failed"-Entwurf mit der Dispatcher-Claim-Marke im error-Feld
# ("in Zustellung seit ...") wird hier direkt per SQL erzeugt statt ueber den
# Dispatcher selbst (dispatch.py hat eine eigene, unabhaengige Testsuite in
# test_dispatch.py) -- server.py kennt nur das Textmuster, nicht dispatch.py
# (Zirkelimport waere sonst die Folge: dispatch.py importiert server).
# ---------------------------------------------------------------------------

_CLAIM_MARKE = "in Zustellung seit 2026-08-18T12:00:00+00:00 (dispatcher aaaa1111)"


def _als_failed_markieren(draft_id, error):
    server._q("update drafts set status = 'failed', error = %s where id = %s",
              (error, draft_id))


def test_erneut_freigeben_failed_wird_approved():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, "OpenWA HTTP 409: Session is not connected.")
    ok = json.loads(server.entwurf_erneut_freigeben(draft))
    assert ok["status"] == "approved"
    zeile = _zeile(draft)
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "betreiber"
    assert zeile["approved_at"] is not None
    assert zeile["error"] is None


def test_erneut_freigeben_loggt_aktivitaet_mit_erneut_true():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, "OpenWA HTTP 409: Session is not connected.")
    server.entwurf_erneut_freigeben(draft)
    akt = server._q(
        "select payload from activities where lead_id = %s and type = 'freigabe' "
        "order by created_at desc limit 1", (lead,))
    assert akt[0]["payload"]["erneut"] is True
    assert akt[0]["payload"]["draft_id"] == str(draft)
    assert akt[0]["payload"]["kanal"] == "whatsapp"


def test_erneut_freigeben_pending_bleibt_unberuehrt():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")  # bleibt pending
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_erneut_freigeben(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_erneut_freigeben_approved_bleibt_unberuehrt():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_erneut_freigeben(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_erneut_freigeben_sent_bleibt_unberuehrt():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "linkedin")
    server.entwurf_freigeben(draft)
    server.entwurf_manuell_gesendet(draft)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_erneut_freigeben(draft))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_erneut_freigeben_claim_marke_ohne_bestaetigt_wird_verweigert():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, _CLAIM_MARKE)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_erneut_freigeben(draft))
    assert "fehler" in kaputt
    assert _CLAIM_MARKE in kaputt["fehler"]
    assert _zeile(draft) == vor


def test_erneut_freigeben_claim_marke_ohne_bestaetigt_explizit_false_wird_verweigert():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, _CLAIM_MARKE)
    vor = _zeile(draft)
    kaputt = json.loads(server.entwurf_erneut_freigeben(draft, bestaetigt=False))
    assert "fehler" in kaputt
    assert _zeile(draft) == vor


def test_erneut_freigeben_claim_marke_mit_bestaetigt_wird_approved():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, _CLAIM_MARKE)
    ok = json.loads(server.entwurf_erneut_freigeben(draft, bestaetigt=True))
    assert ok["status"] == "approved"
    zeile = _zeile(draft)
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "betreiber"
    assert zeile["error"] is None


def test_erneut_freigeben_unbekannte_draft_id_gibt_fehlertext():
    kaputt = json.loads(
        server.entwurf_erneut_freigeben("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


def test_erneut_freigeben_werkzeug_signatur_ueberlebt_den_dekorator():
    import inspect
    parameter = inspect.signature(server.entwurf_erneut_freigeben).parameters
    assert "draft_id" in parameter
    assert "bestaetigt" in parameter
    assert parameter["bestaetigt"].default is False


# ---------------------------------------------------------------------------
# T5a — entwuerfe_offen zeigt die Freigabe-Grundlage
#
# T4 fand live: fehlgeschlagene Entwuerfe tauchen nirgends auf, die angezeigte
# draft_id war gekuerzt und damit werkzeuguntauglich, und niemand sah, an
# WELCHE Nummer ein Entwurf tatsaechlich ginge. Wer freigibt, muss beides
# sehen: die Zielnummer und den Einwilligungsstand.
# ---------------------------------------------------------------------------

def _lead_mit(name="Max Testperson", phone="+491701234567"):
    return server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"]


def _eintrag(ergebnis, block, draft_id):
    return next(e for e in ergebnis[block] if e["draft_id"] == draft_id)


def test_entwuerfe_offen_zeigt_zielnummer_und_consent_im_pending_block():
    lead = _lead_mit(phone="+49 170 1234567")
    draft = _entwurf(lead, "whatsapp", "Text")

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()), "entwuerfe", draft)

    assert eintrag["empfaenger"] == "+49 170 1234567"      # roh, wie erfasst
    assert eintrag["zielnummer"] == "491701234567@c.us"    # normalisiert
    assert eintrag["consent"] == "unknown"
    assert "hinweis" not in eintrag


def test_entwuerfe_offen_meldet_nicht_zustellbare_nummer_im_pending_block():
    lead = _lead_mit(phone="0664 1234567")                 # AT, national
    draft = _entwurf(lead, "whatsapp", "Text")

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()), "entwuerfe", draft)

    assert eintrag["zielnummer"] is None
    assert eintrag["hinweis"] == "nicht zustellbar"


def test_entwuerfe_offen_zeigt_vollstaendige_uuid():
    lead = _anlegen()["lead_id"]
    draft = _entwurf(lead, "whatsapp", "Text")

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()), "entwuerfe", draft)

    assert str(eintrag["draft_id"]) == str(draft)
    assert len(str(eintrag["draft_id"])) == 36


def test_entwuerfe_offen_listet_fehlgeschlagene_in_eigenem_block():
    lead = _lead_mit(phone="+491701234567")
    draft = _entwurf(lead, "whatsapp", "Text")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, "OpenWA HTTP 409: Session is not connected.")

    ergebnis = json.loads(server.entwuerfe_offen())

    assert draft not in {e["draft_id"] for e in ergebnis["entwuerfe"]}
    eintrag = _eintrag(ergebnis, "fehlgeschlagen", draft)
    assert str(eintrag["draft_id"]) == str(draft)
    assert eintrag["kanal"] == "whatsapp"
    assert eintrag["empfaenger"] == "+491701234567"
    assert eintrag["zielnummer"] == "491701234567@c.us"
    assert eintrag["consent"] == "unknown"
    assert eintrag["fehler"] == "OpenWA HTTP 409: Session is not connected."


def test_fehlgeschlagen_block_kuerzt_den_fehlertext_auf_120_zeichen():
    lead = _lead_mit()
    draft = _entwurf(lead, "whatsapp", "Text")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, "y" * 250)

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()),
                       "fehlgeschlagen", draft)

    assert len(eintrag["fehler"]) == 120


def test_fehlgeschlagen_block_zeigt_die_claim_marke_ungeschoent():
    """Ein Entwurf, der die Zustellungs-Marke traegt, muss auffindbar sein —
    sonst weiss niemand, dass er da ist."""
    lead = _lead_mit()
    draft = _entwurf(lead, "whatsapp", "Text")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, _CLAIM_MARKE)

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()),
                       "fehlgeschlagen", draft)

    assert eintrag["fehler"].startswith("in Zustellung")


def test_fehlgeschlagen_block_zeigt_unzustellbare_nummer_als_null():
    lead = _lead_mit(phone="0664 1234567")
    draft = _entwurf(lead, "whatsapp", "Text")
    server.entwurf_freigeben(draft)
    _als_failed_markieren(draft, "Empfaenger ohne Landesvorwahl")

    eintrag = _eintrag(json.loads(server.entwuerfe_offen()),
                       "fehlgeschlagen", draft)

    assert eintrag["zielnummer"] is None
    assert eintrag["hinweis"] == "nicht zustellbar"


def test_entwuerfe_offen_bleibt_leer_wenn_nichts_anliegt():
    ergebnis = json.loads(server.entwuerfe_offen())
    assert ergebnis["entwuerfe"] == []
    assert ergebnis["fehlgeschlagen"] == []


def test_entwuerfe_offen_nutzt_dieselbe_normalisierung_wie_der_dispatcher():
    assert server.normalisiere_empfaenger is nummern.normalisiere_empfaenger


# ---------------------------------------------------------------------------
# T5a — kontakt_aktualisieren
#
# T4-Befund: „Anna Beispiel" hatte keine Telefonnummer, und es gab kein
# Werkzeug, sie nachzutragen — `profil_aktualisieren` schreibt nur nach
# `enrichment`, nicht in die Spalte `phone`, die der Dispatcher liest.
# ---------------------------------------------------------------------------

def _lead_spalten(lead_id):
    return server._q("select name, phone, email from leads where id = %s",
                     (lead_id,))[0]


def test_kontakt_aktualisieren_traegt_telefonnummer_nach():
    lead = server._q("insert into leads (name, source) values "
                     "('Anna Beispiel', 'whatsapp') returning id")[0]["id"]
    assert _lead_spalten(lead)["phone"] is None

    ok = json.loads(server.kontakt_aktualisieren(lead, "phone", "+491701234567"))

    assert ok["gesetzt"] == {"phone": "+491701234567"}
    assert _lead_spalten(lead)["phone"] == "+491701234567"


@pytest.mark.parametrize("feld, wert", [
    ("phone", "+436641234567"),
    ("email", "anna@example.com"),
    ("name", "Anna Beispiel-Neu"),
])
def test_kontakt_aktualisieren_erlaubt_genau_drei_felder(feld, wert):
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.kontakt_aktualisieren(lead, feld, wert))
    assert "fehler" not in ok
    assert _lead_spalten(lead)[feld] == wert


@pytest.mark.parametrize("feld", [
    "enrichment",          # der im Brief genannte Fall
    "consent_status",      # Einwilligung wird nie per Freitext gesetzt
    "status",
    "score",
    "id",
    "notes",
    "phone; drop table leads",
    "PHONE",               # Whitelist ist buchstabengenau
    "",
])
def test_kontakt_aktualisieren_lehnt_jedes_andere_feld_ab(feld):
    lead = _anlegen()["lead_id"]
    vorher = _lead_spalten(lead)

    kaputt = json.loads(server.kontakt_aktualisieren(lead, feld, "boese"))

    assert "fehler" in kaputt
    assert "phone" in kaputt["fehler"]      # nennt die erlaubten Felder
    assert _lead_spalten(lead) == vorher    # nichts angefasst


def test_kontakt_aktualisieren_loggt_korrektur_mit_vorher_und_nachher():
    lead = _anlegen()["lead_id"]            # legt mit phone='+490000000001' an
    server.kontakt_aktualisieren(lead, "phone", "+491701234567")

    akt = server._q(
        "select payload from activities where lead_id = %s and type = 'korrektur'",
        (lead,))
    assert len(akt) == 1
    assert akt[0]["payload"]["feld"] == "phone"
    assert akt[0]["payload"]["wert"] == "+491701234567"
    assert akt[0]["payload"]["vorher"] == "+490000000001"


def test_kontakt_aktualisieren_lehnt_leeren_namen_ab():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.kontakt_aktualisieren(lead, "name", "   "))
    assert "fehler" in kaputt
    assert _lead_spalten(lead)["name"] == "Max Testperson"


def test_kontakt_aktualisieren_leert_telefonnummer_bei_leerem_wert():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.kontakt_aktualisieren(lead, "phone", ""))
    assert "fehler" not in ok
    assert _lead_spalten(lead)["phone"] is None


def test_kontakt_aktualisieren_unbekannte_lead_id_gibt_fehlertext():
    kaputt = json.loads(server.kontakt_aktualisieren(
        "00000000-0000-0000-0000-000000000000", "phone", "+491701234567"))
    assert "fehler" in kaputt


def test_kontakt_aktualisieren_schliesst_den_t4_befund():
    """Der ganze Grund fuer dieses Werkzeug: eine nachgetragene Nummer muss
    den Entwurf zustellbar machen."""
    lead = server._q("insert into leads (name, source) values "
                     "('Anna Beispiel', 'whatsapp') returning id")[0]["id"]
    draft = _entwurf(lead, "whatsapp", "Text")      # faellt auf den Namen zurueck
    vorher = _eintrag(json.loads(server.entwuerfe_offen()), "entwuerfe", draft)
    assert vorher["zielnummer"] is None

    server.kontakt_aktualisieren(lead, "phone", "+491701234567")
    neu = _entwurf(lead, "whatsapp", "Text")        # neuer Entwurf, neue Nummer

    nachher = _eintrag(json.loads(server.entwuerfe_offen()), "entwuerfe", neu)
    assert nachher["zielnummer"] == "491701234567@c.us"


def test_kontakt_aktualisieren_signatur_ueberlebt_den_dekorator():
    import inspect
    parameter = inspect.signature(server.kontakt_aktualisieren).parameters
    assert list(parameter) == ["lead_id", "feld", "wert"]


def test_dreiundvierzig_werkzeuge_registriert():
    namen = {fn.__name__ for fn in server.WERKZEUGE}
    assert len(namen) == 43
    # Beobachtet, welche Absender-Merkmale stabil bleiben (25.08.2026).
    assert "kennungen_bericht" in namen
    assert "kontakt_aktualisieren" in namen
    # Das Kontaktprofil (25.08.2026) mit EIGENEM Takt: Schwelle 5 statt der
    # 50 des Chat-Reports, und ohne Nachrichten zu verstecken. Dazu der Weg
    # fuer „jetzt bitte" aus der Oberflaeche. Vertragstests in
    # tests/test_kontaktprofil.py.
    assert "profile_faellig" in namen
    assert "kontaktprofil_schreiben" in namen
    assert "profil_anfordern" in namen
    # Kontakt-Freigabe fuer WhatsApp und Auto-Betrieb. Vertragstests dazu in
    # tests/test_kontakt_freigabe.py.
    assert "kontakt_freigeben" in namen
    assert "kontakt_freigabe_entziehen" in namen
    assert "kontakte_freigegeben" in namen
    # Archivieren statt Loeschen (21.08.2026). Es gibt bewusst KEIN
    # Loesch-Werkzeug: kein DELETE-Recht auf `sales`, und `activities` haengt
    # mit ON DELETE CASCADE am Kontakt. Vertragstests in tests/test_ui.py.
    assert "kontakt_archivieren" in namen
    assert "kontakt_wiederherstellen" in namen
    assert not [n for n in namen if "loesch" in n or "delete" in n]
    assert "wiedervorlage_setzen" in namen
    assert "wiedervorlage_erledigt" in namen
    assert "medien_liste" in namen
    # Stufe 5 — Recherche. Vertragstests dazu in tests/test_recherche.py.
    assert "marktanalyse" in namen
    assert "b2b_leads" in namen
    # Stufe 6 — LinkedIn-Posts. Vertragstests in tests/test_linkedin_posts.py.
    assert "post_entwurf_erstellen" in namen
    # Stufe 6 — Firmen-Anreicherung. Tests in tests/test_firma_anreichern.py.
    assert "firma_anreichern" in namen
    # Stufe 7 — Bestandspflege. Vertragstests in tests/test_vertraege.py.
    assert "vertrag_speichern" in namen
    assert "vertraege_ablaufend" in namen
    # Stufe 7 — Wochenbericht. Vertragstests in tests/test_wochenbericht.py.
    assert "wochenbericht" in namen
    # Stufe 7 — Beraterin-Uebergabe. Vertragstests in tests/test_uebergabe.py.
    assert "uebergabe_erstellen" in namen
    # Stufe 8 — Support-Posteingang. Vertragstests in tests/test_posteingang.py.
    assert "posteingang" in namen
    # Stufe 9 — Termine/ICS. Vertragstests in tests/test_termin.py.
    # sales-mail ist KEIN Werkzeug: der E-Mail-Versand ist ein Dienst hinter
    # dem Freigabe-Gate, kein Werkzeug in der Hand des Modells.
    assert "termin_bestaetigen" in namen
    # Stufe 11 — Einordnung eingehender Absender. Vertragstests in
    # tests/test_einordnung.py und tests/test_lid.py. Beide versenden nichts:
    # `absender_aufloesen` stellt eine Frage an den eigenen OpenWA-Container,
    # `eingang_einordnen` fasst nur die Datenbank an.
    assert "eingang_einordnen" in namen
    assert "absender_aufloesen" in namen
    # Betreiber-Wunsch 22.08.2026 — Entwuerfe endgueltig wegraeumen.
    # Vertragstests in tests/test_verwerfen.py. Fuer `pending` gibt es
    # bewusst KEIN zweites Werkzeug: das ist `entwurf_ablehnen`.
    assert "entwurf_verwerfen" in namen
    # Betreiber-Wunsch 22.08.2026 — lange Verlaeufe verdichten. Vertragstests
    # in tests/test_chat_report.py. Keins der drei ruft ein Modell auf oder
    # geht ins Netz: der Agent schreibt den Text, die Werkzeuge lesen und
    # legen ab.
    assert "chat_reports_faellig" in namen
    assert "chat_verlauf" in namen
    assert "chat_report_speichern" in namen


# ---------------------------------------------------------------------------
# F3 — Wiedervorlagen (ohne DDL, append-only: offen = wiedervorlage OHNE
# zugehoeriges Gegen-Ereignis wiedervorlage_erledigt)
# ---------------------------------------------------------------------------

def _heute() -> date:
    return datetime.now(timezone.utc).date()


def _wiedervorlage(lead_id, tage_versetzt=1, notiz="Rueckruf vereinbaren"):
    faellig = (_heute() + timedelta(days=tage_versetzt)).isoformat()
    return json.loads(server.wiedervorlage_setzen(lead_id, faellig, notiz))


def _faellig_am_setzen(aktivitaets_id, datum: date):
    """Faelligkeit direkt herbeifuehren — ein Zustand, den das Werkzeug selbst
    (das Vergangenheitsdaten ablehnt) nie herstellen wuerde. Gleiches Muster
    wie _als_failed_markieren oben: per SQL simulieren, was in der Zukunft zu
    Gegenwart wird."""
    server._q(
        "update activities set payload = jsonb_set(payload, '{faellig_am}', "
        "%s::jsonb) where id = %s", (json.dumps(datum.isoformat()), aktivitaets_id))


def test_wiedervorlage_setzen_liefert_aktivitaets_id_und_speichert_payload():
    lead = _anlegen()["lead_id"]
    ok = _wiedervorlage(lead, tage_versetzt=3, notiz="Rueckruf zum Angebot")
    assert "fehler" not in ok
    assert ok["aktivitaets_id"]
    akt = server._q("select type, payload from activities where id = %s",
                    (ok["aktivitaets_id"],))[0]
    assert akt["type"] == "wiedervorlage"
    assert akt["payload"]["notiz"] == "Rueckruf zum Angebot"
    assert akt["payload"]["faellig_am"] == (_heute() + timedelta(days=3)).isoformat()


def test_wiedervorlage_setzen_lehnt_vergangenheitsdatum_ab_und_schreibt_nichts():
    lead = _anlegen()["lead_id"]
    gestern = (_heute() - timedelta(days=1)).isoformat()
    kaputt = json.loads(server.wiedervorlage_setzen(lead, gestern, "x"))
    assert "fehler" in kaputt
    anzahl = server._q(
        "select count(*) as n from activities where type = 'wiedervorlage'")[0]["n"]
    assert anzahl == 0


def test_wiedervorlage_setzen_erlaubt_heute():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.wiedervorlage_setzen(lead, _heute().isoformat(), "x"))
    assert "fehler" not in ok


def test_wiedervorlage_setzen_lehnt_unlesbares_datum_ab():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.wiedervorlage_setzen(lead, "31.12.2026", "x"))
    assert "fehler" in kaputt


def test_wiedervorlage_erscheint_im_digest_erst_ab_faelligkeit_nicht_davor():
    lead = _anlegen(name="Faellig Testperson")["lead_id"]
    ok = _wiedervorlage(lead, tage_versetzt=1, notiz="Notiz A")

    vor_faelligkeit = json.loads(server.digest())
    assert ok["aktivitaets_id"] not in {
        e["aktivitaets_id"] for e in vor_faelligkeit["faellige_wiedervorlagen"]}

    _faellig_am_setzen(ok["aktivitaets_id"], _heute())

    nach_faelligkeit = json.loads(server.digest())
    eintrag = next(e for e in nach_faelligkeit["faellige_wiedervorlagen"]
                   if e["aktivitaets_id"] == ok["aktivitaets_id"])
    assert eintrag["kontakt"] == "Faellig Testperson"
    assert eintrag["notiz"] == "Notiz A"


def test_wiedervorlage_erledigt_entfernt_sie_aus_dem_digest():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.wiedervorlage_setzen(lead, _heute().isoformat(), "Notiz B"))
    vor = json.loads(server.digest())
    assert any(e["aktivitaets_id"] == ok["aktivitaets_id"]
               for e in vor["faellige_wiedervorlagen"])

    erledigt = json.loads(server.wiedervorlage_erledigt(lead, ok["aktivitaets_id"]))
    assert "fehler" not in erledigt

    nach = json.loads(server.digest())
    assert all(e["aktivitaets_id"] != ok["aktivitaets_id"]
               for e in nach["faellige_wiedervorlagen"])


def test_wiedervorlage_erledigt_schreibt_gegenereignis_append_only():
    lead = _anlegen()["lead_id"]
    ok = json.loads(server.wiedervorlage_setzen(lead, _heute().isoformat(), "Notiz C"))
    vorher = server._q("select type, payload from activities where id = %s",
                       (ok["aktivitaets_id"],))[0]

    server.wiedervorlage_erledigt(lead, ok["aktivitaets_id"])

    nachher = server._q("select type, payload from activities where id = %s",
                        (ok["aktivitaets_id"],))[0]
    assert nachher == vorher                       # Originalzeile unveraendert

    gegenereignis = server._q(
        "select payload from activities where lead_id = %s "
        "and type = 'wiedervorlage_erledigt'", (lead,))
    assert len(gegenereignis) == 1
    assert gegenereignis[0]["payload"]["wiedervorlage_id"] == str(ok["aktivitaets_id"])


def test_wiedervorlage_erledigt_auf_fremde_aktivitaets_id_schlaegt_fehl_und_schreibt_nichts():
    lead_a = _anlegen(name="Person Eins", phone="+491701111111")["lead_id"]
    lead_b = _anlegen(name="Person Zwei", phone="+491702222222")["lead_id"]
    ok = json.loads(server.wiedervorlage_setzen(lead_a, _heute().isoformat(), "Notiz D"))
    vor = server._q("select count(*) as n from activities")[0]["n"]

    kaputt = json.loads(server.wiedervorlage_erledigt(lead_b, ok["aktivitaets_id"]))

    assert "fehler" in kaputt
    nach = server._q("select count(*) as n from activities")[0]["n"]
    assert nach == vor


def test_wiedervorlage_erledigt_auf_unbekannte_aktivitaets_id_schlaegt_fehl():
    lead = _anlegen()["lead_id"]
    kaputt = json.loads(server.wiedervorlage_erledigt(
        lead, "00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


def test_wiedervorlage_erledigt_auf_falschen_aktivitaetstyp_schlaegt_fehl_und_schreibt_nichts():
    lead = _anlegen()["lead_id"]
    server.aktivitaet_loggen(lead, "notiz", "kein Wiedervorlage-Ereignis")
    fremde_akt = server._q(
        "select id from activities where lead_id = %s and type = 'notiz'", (lead,))[0]["id"]
    vor = server._q("select count(*) as n from activities")[0]["n"]

    kaputt = json.loads(server.wiedervorlage_erledigt(lead, fremde_akt))

    assert "fehler" in kaputt
    nach = server._q("select count(*) as n from activities")[0]["n"]
    assert nach == vor


def test_digest_faellige_wiedervorlagen_leer_wenn_nichts_ansteht():
    d = json.loads(server.digest())
    assert d["faellige_wiedervorlagen"] == []


def test_wiedervorlage_werkzeuge_signaturen_ueberleben_den_dekorator():
    import inspect
    setzen = inspect.signature(server.wiedervorlage_setzen).parameters
    assert list(setzen) == ["lead_id", "faellig_am", "notiz"]
    erledigt = inspect.signature(server.wiedervorlage_erledigt).parameters
    assert list(erledigt) == ["lead_id", "aktivitaets_id"]


# ---------------------------------------------------------------------------
# F3 (Demo-Befund B1) — Dedup-Kante in kontakt_anlegen: dieselbe normalisierte
# Telefonnummer (unabhaengig von der Schreibweise) -> bestehenden Lead
# zurueckgeben statt neu anlegen. Ohne (normalisierbare) Telefonnummer bleibt
# das bisherige Verhalten unveraendert: Namens-Dubletten sind legitim.
# ---------------------------------------------------------------------------

def test_kontakt_anlegen_erkennt_gleiche_nummer_in_anderer_schreibweise():
    erster = _anlegen(name="Lisa Probekunde", phone="+491701234567")
    assert erster["angelegt"] is True

    zweiter = json.loads(server.kontakt_anlegen(
        name="Lisa Probekunde", phone="00491701234567"))

    assert zweiter["angelegt"] is False
    assert zweiter["lead_id"] == erster["lead_id"]
    assert zweiter["hinweis"] == "Kontakt mit dieser Nummer existiert bereits"
    anzahl = server._q("select count(*) as n from leads")[0]["n"]
    assert anzahl == 1


def test_kontakt_anlegen_ohne_nummer_erlaubt_weiterhin_namensdubletten():
    erster = json.loads(server.kontakt_anlegen(name="Max Mueller"))
    zweiter = json.loads(server.kontakt_anlegen(name="Max Mueller"))

    assert erster["angelegt"] is True
    assert zweiter["angelegt"] is True
    assert erster["lead_id"] != zweiter["lead_id"]
    anzahl = server._q("select count(*) as n from leads")[0]["n"]
    assert anzahl == 2


def test_kontakt_anlegen_verschiedene_nummern_bleiben_getrennt():
    a = _anlegen(name="Person A", phone="+491701111111")
    b = _anlegen(name="Person B", phone="+491702222222")
    assert a["angelegt"] is True
    assert b["angelegt"] is True
    assert a["lead_id"] != b["lead_id"]


def test_kontakt_anlegen_unzustellbare_nummer_bleibt_weiterhin_neu_anlegbar():
    # Nationale Schreibweise ("0170…") kann normalisiere_empfaenger nicht
    # deuten -> kein Vergleich moeglich -> Verhalten wie ohne Telefonnummer.
    a = json.loads(server.kontakt_anlegen(name="Person C", phone="0170 1234567"))
    b = json.loads(server.kontakt_anlegen(name="Person D", phone="0170 1234567"))
    assert a["angelegt"] is True
    assert b["angelegt"] is True


# ---------------------------------------------------------------------------
# F4 — Medien-Entwuerfe: Haertung in entwurf_erstellen, Anzeige in
# entwuerfe_offen, medien_liste. Der Medienordner ist im Test ein tmp-Pfad
# (`medien.MEDIA_VERZEICHNIS` wird umgebogen) — nie der echte Bind.
# ---------------------------------------------------------------------------

@pytest.fixture
def medienordner(tmp_path, monkeypatch):
    """Frischer Medienordner mit einer gueltigen PDF-Datei."""
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    (tmp_path / "checkliste.pdf").write_bytes(b"%PDF-1.4 Testinhalt")
    return tmp_path


def _anzahl_drafts():
    return server._q("select count(*) as n from drafts")[0]["n"]


def test_entwurf_ohne_medien_datei_bleibt_unveraendert(medienordner):
    """Regression: der bestehende Weg darf sich nicht bewegen."""
    lead = _anlegen()["lead_id"]
    neu = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert neu["status"] == "pending"
    zeile = server._q("select media_ref from drafts where id = %s",
                      (neu["draft_id"],))[0]
    assert zeile["media_ref"] is None


def test_entwurf_mit_gueltiger_pdf_setzt_media_ref(medienordner):
    lead = _anlegen()["lead_id"]
    neu = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Die Checkliste vorab.",
        medien_datei="checkliste.pdf"))
    assert "fehler" not in neu
    assert neu["medien_datei"] == "checkliste.pdf"
    zeile = server._q("select media_ref from drafts where id = %s",
                      (neu["draft_id"],))[0]
    assert zeile["media_ref"] == "checkliste.pdf"


@pytest.mark.parametrize("boesartig", [
    "../../etc/passwd",
    "../checkliste.pdf",
    "..\\windows\\system.ini",
    "..\\..\\checkliste.pdf",
    "/etc/passwd",
    "/media/checkliste.pdf",
    "C:\\media\\checkliste.pdf",
    "unterordner/checkliste.pdf",
    # Ohne fuehrende Punkte: fuer diesen Fall traegt AUSSCHLIESSLICH die
    # Backslash-Regel — `basename` laesst ihn im Linux-Container unveraendert
    # durch, und er beginnt nicht mit '.'.
    "unterordner\\checkliste.pdf",
    "..",
    ".",
])
def test_pfadangaben_werden_abgelehnt_und_erzeugen_keinen_entwurf(
        medienordner, boesartig):
    """Pfad-Traversal: kein Draft, sprechender Fehlertext, nichts angefasst."""
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei=boesartig))
    assert "fehler" in antwort
    assert "draft_id" not in antwort
    assert _anzahl_drafts() == 0


@pytest.mark.parametrize("boesartig", [
    "../checkliste.pdf",
    "..\\checkliste.pdf",
    "..\\windows\\system.ini",
    "/etc/passwd",
    "C:\\media\\checkliste.pdf",
    "unterordner/checkliste.pdf",
    # Ohne fuehrende Punkte: fuer diesen Fall traegt AUSSCHLIESSLICH die
    # Backslash-Regel — `basename` laesst ihn im Linux-Container unveraendert
    # durch, und er beginnt nicht mit '.'.
    "unterordner\\checkliste.pdf",
])
def test_grund_der_ablehnung_ist_die_pfadangabe_nicht_die_fehlende_datei(
        medienordner, boesartig):
    """Schaerft die Abwehr: eine Pfadangabe muss AN DER PFADANGABE scheitern,
    nicht zufaellig daran, dass unter diesem Namen nichts im Ordner liegt.

    Der Unterschied ist nicht kosmetisch. Eine Abwehr, die den Namen still auf
    `os.path.basename` kuerzt, wuerde `../checkliste.pdf` klaglos als
    `checkliste.pdf` annehmen — der Betreiber haette eine Datei ausserhalb
    gemeint und bekaeme wortlos eine andere angehaengt. Und im
    Linux-Container ist '\\' kein Trennzeichen: `..\\windows\\system.ini`
    ueberlebt `basename` unveraendert und flaeche sonst erst durch die
    Endungspruefung."""
    basis, fehler = medien.pruefe(boesartig)
    assert basis is None
    assert "kein reiner Dateiname" in fehler


def test_traversal_auf_eine_existierende_datei_ausserhalb_wird_abgelehnt(
        tmp_path, monkeypatch):
    """Die scharfe Probe: die Zieldatei EXISTIERT wirklich, liegt aber eine
    Ebene ueber dem Medienordner. Eine Abwehr, die nur ueber die
    Existenzpruefung liefe, wuerde hier durchlassen."""
    ordner = tmp_path / "media"
    ordner.mkdir()
    (tmp_path / "geheim.pdf").write_bytes(b"%PDF-1.4 nicht fuer den Versand")
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(ordner))
    lead = _anlegen()["lead_id"]

    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="../geheim.pdf"))

    assert "fehler" in antwort
    assert _anzahl_drafts() == 0


@pytest.mark.parametrize("name", [
    "notizen.txt", "skript.sh", "archiv.zip", "tabelle.xlsx", "ohneendung",
    "doppel.pdf.exe",
])
def test_unerlaubte_endung_wird_abgelehnt(medienordner, name):
    (medienordner / name).write_bytes(b"egal")
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei=name))
    assert "fehler" in antwort
    assert _anzahl_drafts() == 0


def test_fehlende_datei_wird_abgelehnt(medienordner):
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="gibtsnicht.pdf"))
    assert "fehler" in antwort
    assert "gibtsnicht.pdf" in antwort["fehler"]
    assert _anzahl_drafts() == 0


def test_leere_datei_wird_abgelehnt(medienordner):
    (medienordner / "leer.pdf").write_bytes(b"")
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="leer.pdf"))
    assert "fehler" in antwort
    assert _anzahl_drafts() == 0


def test_zu_grosse_datei_wird_abgelehnt(medienordner, monkeypatch):
    monkeypatch.setattr(medien, "MAX_BYTES", 1024)
    (medienordner / "gross.pdf").write_bytes(b"x" * 2048)
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="gross.pdf"))
    assert "fehler" in antwort
    assert _anzahl_drafts() == 0


def test_echte_groessengrenze_ist_15_mb():
    """Die Zahl selbst ist eine Zusage an den Betreiber, kein Detail."""
    assert medien.MAX_BYTES == 15 * 1024 * 1024


def test_zu_langer_text_mit_anhang_wird_abgelehnt(medienordner):
    """Gemessen: der Media-Endpunkt deckelt die Bildunterschrift bei 1024
    Zeichen (Text allein duerfte 4096). Ein Entwurf, der daran scheitern
    wuerde, entsteht gar nicht erst."""
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "x" * 1025, medien_datei="checkliste.pdf"))
    assert "fehler" in antwort
    assert "1024" in antwort["fehler"]
    assert _anzahl_drafts() == 0


def test_langer_text_ohne_anhang_bleibt_erlaubt(medienordner):
    """Die Caption-Grenze gilt nur mit Anhang — reiner Text darf laenger."""
    lead = _anlegen()["lead_id"]
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "x" * 1025))
    assert "fehler" not in antwort


def test_entwuerfe_offen_zeigt_medien_datei(medienordner):
    lead = _anlegen()["lead_id"]
    mit = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="checkliste.pdf"))
    ohne = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Nur Text."))

    offen = json.loads(server.entwuerfe_offen())
    je_id = {e["draft_id"]: e for e in offen["entwuerfe"]}
    assert je_id[mit["draft_id"]]["medien_datei"] == "checkliste.pdf"
    assert je_id[ohne["draft_id"]]["medien_datei"] is None


def test_entwuerfe_offen_zeigt_medien_datei_auch_im_fehlgeschlagen_block(
        medienordner):
    lead = _anlegen()["lead_id"]
    neu = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei.", medien_datei="checkliste.pdf"))
    server._q("update drafts set status = 'failed', error = 'Datei weg' "
              "where id = %s returning id", (neu["draft_id"],))

    offen = json.loads(server.entwuerfe_offen())
    assert offen["fehlgeschlagen"][0]["medien_datei"] == "checkliste.pdf"


def test_medien_liste_nennt_namen_und_groesse(medienordner):
    (medienordner / "bild.jpg").write_bytes(b"x" * 100)
    (medienordner / "notiz.txt").write_bytes(b"x" * 50)

    liste = json.loads(server.medien_liste())

    namen = [d["name"] for d in liste["dateien"]]
    assert namen == ["bild.jpg", "checkliste.pdf"]     # .txt faellt raus
    assert liste["anzahl"] == 2
    je_name = {d["name"]: d for d in liste["dateien"]}
    assert je_name["bild.jpg"]["groesse_bytes"] == 100


def test_medien_liste_ohne_ordner_gibt_fehlertext_statt_traceback(monkeypatch):
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", "/gibt/es/nicht")
    antwort = json.loads(server.medien_liste())
    assert "fehler" in antwort


def test_medien_werkzeuge_signaturen_ueberleben_den_dekorator():
    import inspect
    erstellen = inspect.signature(server.entwurf_erstellen).parameters
    assert list(erstellen) == ["lead_id", "kanal", "text", "betreff",
                               "medien_datei"]
    assert erstellen["medien_datei"].default == ""
    assert list(inspect.signature(server.medien_liste).parameters) == []
    assert server.medien_liste in server.WERKZEUGE
