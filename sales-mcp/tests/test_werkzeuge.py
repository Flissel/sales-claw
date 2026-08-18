"""Vertragstests gegen sales_test. Die Suite darf NIE gegen `sales` laufen —
`sales.activities` ist append-only und ließe sich nicht zurücksetzen."""
import json
import os

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen. Der
# Schutz muss konstruktiv sein, nicht von der Disziplin des Aufrufers abhaengen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
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


def test_fuenfzehn_werkzeuge_registriert():
    namen = {fn.__name__ for fn in server.WERKZEUGE}
    assert len(namen) == 15
    assert "kontakt_aktualisieren" in namen
