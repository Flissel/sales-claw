"""Vertragstests fuer das UWG-Einwilligungs-Tor (F5, 31.08.2026).

`leads.consent_status` existierte mit genau dem richtigen Wortschatz
(opt_in | existing_customer | inbound | unknown — die Bestandskunden-
Ausnahme des Par. 7 Abs. 3 UWG eingebaut) und wurde NIE benutzt: alle
Kontakte standen auf unknown, und nichts hinderte eine Erstansprache.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. ERSTANSPRACHE (der Kontakt hat noch nie selbst geschrieben) per
   WhatsApp oder E-Mail braucht dokumentierte Grundlage: opt_in oder
   existing_customer. Ohne sie entsteht KEIN Entwurf.
2. ANTWORTEN bleibt frei: wer selbst geschrieben hat, hat den Kanal
   geoeffnet — unabhaengig vom consent_status.
3. Die Grundlage erfasst ein Mensch mit Quelle; der Widerruf wirkt
   sofort und steht wie alles im Protokoll.
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


def _lead(name="Udo Umworben"):
    lead = str(server._q(
        "insert into leads (name, phone, email, source) values "
        "(%s, '+491705556677', 'udo@example.org', 'whatsapp') "
        "returning id", (name,))[0]["id"])
    server.kontakt_freigeben(lead)
    return lead


def _hat_geschrieben(lead):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'kundenantwort', %s) returning id",
              (lead, server._json({"text": "Hallo, ich haette Interesse."})))


def _status(lead):
    return server._q("select consent_status from leads where id = %s",
                     (lead,))[0]["consent_status"]


# ---------------------------------------------------------------------------
# Das Tor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kanal", ["whatsapp", "email"])
def test_erstansprache_ohne_grundlage_scheitert(kanal):
    lead = _lead()
    antwort = json.loads(server.entwurf_erstellen(
        lead, kanal, "Darf ich Ihnen etwas vorstellen?"))
    assert "fehler" in antwort
    assert "Einwilligung" in antwort["fehler"]
    assert server._q("select count(*) n from drafts where lead_id = %s",
                     (lead,))[0]["n"] == 0


def test_wer_selbst_schrieb_darf_beantwortet_werden():
    lead = _lead()
    _hat_geschrieben(lead)
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Gerne! Passt Donnerstag?"))
    assert "fehler" not in antwort


@pytest.mark.parametrize("art", ["opt_in", "existing_customer"])
def test_mit_grundlage_geht_die_erstansprache(art):
    lead = _lead()
    server.einwilligung_erfassen(lead, art, "Messegespraech 30.08.")
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Wie besprochen die Unterlagen."))
    assert "fehler" not in antwort


def test_linkedin_beitraege_sind_kein_direktkontakt():
    """Ein Beitrag aufs eigene Profil spricht niemanden direkt an —
    das Tor gilt fuer WhatsApp und E-Mail."""
    lead = _lead("LINKEDIN (Eigenes Profil)")
    antwort = json.loads(server.entwurf_erstellen(
        lead, "linkedin", "Ein Beitrag.", betreff="Post: Probe"))
    assert "fehler" not in antwort


# ---------------------------------------------------------------------------
# Erfassen und Widerruf
# ---------------------------------------------------------------------------

def test_erfassen_setzt_status_und_protokolliert():
    lead = _lead()
    antwort = json.loads(server.einwilligung_erfassen(
        lead, "opt_in", "WhatsApp-Nachricht", "Ja, gerne Infos!"))
    assert "fehler" not in antwort
    assert _status(lead) == "opt_in"
    zeilen = server._q(
        "select payload from activities where lead_id = %s and "
        "type = 'werbe_einwilligung'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["quelle"] == "WhatsApp-Nachricht"


def test_ohne_quelle_wird_nichts_erfasst():
    lead = _lead()
    antwort = json.loads(server.einwilligung_erfassen(lead, "opt_in", "  "))
    assert "fehler" in antwort
    assert _status(lead) == "unknown"


def test_unbekannte_art_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.einwilligung_erfassen(
        lead, "vielleicht", "Telefonat"))
    assert "fehler" in antwort
    assert "opt_in" in antwort["fehler"]
    assert _status(lead) == "unknown"


def test_widerruf_wirkt_sofort():
    lead = _lead()
    server.einwilligung_erfassen(lead, "opt_in", "Messegespraech")
    antwort = json.loads(server.einwilligung_widerrufen(
        lead, "Kunde will keine Werbung mehr"))
    assert "fehler" not in antwort
    assert _status(lead) == "unknown"
    gesperrt = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Noch ein Angebot?"))
    assert "fehler" in gesperrt
