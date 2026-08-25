"""Vertragstests fuer die Zustimmung zur automatischen Antwort.

Betreiber am 25.08.2026: „request freigabe an den auto consumenten" — der
Kontakt selbst soll gefragt werden, bevor ein Programm ihm selbstaendig
antwortet. Und auf Rueckfrage: kontaktweit, nicht je Kanal.

Die Spezifikation (docs/moegliche-erweiterungen/autoantwort-zustimmungs-
gate.md) beschreibt, wie eine Zustimmung DOKUMENTIERT wird. Wie man sie
EINHOLT, stand dort nicht.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Die Frage geht durch die Freigabe wie jede andere Nachricht. Eine
   Zustimmung zur automatischen Kommunikation automatisch zu erfragen waere
   genau der Vorgang, den sie erst erlauben soll.
2. Die Antwort erfasst ein MENSCH — mit Quelle und Wortlaut. Ohne Quelle
   entsteht kein Nachweis.
3. Ohne Zustimmung faellt `auto` auf `halbauto` zurueck. Still, nicht als
   Fehler: die Absicht des Betreibers bleibt, nur der letzte Schritt fehlt.
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


def _lead(name="Max Testperson", phone="+491701234567"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])
    server.kontakt_freigeben(lead)          # WhatsApp-Gate ist nicht Thema
    return lead


def _enrichment(lead):
    return server._q("select enrichment from leads where id = %s",
                     (lead,))[0]["enrichment"]


def _entwuerfe(lead):
    return server._q(
        "select id, status, approved_by, body, error from drafts "
        "where lead_id = %s order by created_at", (lead,))


# ---------------------------------------------------------------------------
# Fragen — als Entwurf, nie als Versand
# ---------------------------------------------------------------------------

def test_die_frage_wird_ein_entwurf_und_geht_nicht_raus():
    lead = _lead()
    antwort = json.loads(server.zustimmung_anfragen(lead))
    assert "fehler" not in antwort
    zeilen = _entwuerfe(lead)
    assert len(zeilen) == 1
    assert zeilen[0]["status"] == "pending"
    assert zeilen[0]["approved_by"] is None


def test_die_standardfrage_nennt_den_assistenten():
    """Wer nicht weiss, dass er mit einem Programm schreibt, hat nicht
    zugestimmt."""
    lead = _lead()
    server.zustimmung_anfragen(lead)
    text = _entwuerfe(lead)[0]["body"].lower()
    assert "assistent" in text
    assert "?" in text


def test_eigener_text_wird_uebernommen():
    lead = _lead()
    server.zustimmung_anfragen(lead, "Darf mein Assistent Ihnen antworten?")
    assert _entwuerfe(lead)[0]["body"] == "Darf mein Assistent Ihnen antworten?"


def test_zweimal_fragen_wird_abgelehnt():
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "WhatsApp-Antwort", "Ja gerne")
    antwort = json.loads(server.zustimmung_anfragen(lead))
    assert "fehler" in antwort
    assert "bereits zugestimmt" in antwort["fehler"]
    assert _entwuerfe(lead) == []


def test_nach_widerruf_darf_wieder_gefragt_werden():
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "Telefonat")
    server.zustimmung_widerrufen(lead, "Kunde moechte nicht mehr")
    assert "fehler" not in json.loads(server.zustimmung_anfragen(lead))


# ---------------------------------------------------------------------------
# Erfassen — durch einen Menschen, mit Nachweis
# ---------------------------------------------------------------------------

def test_ohne_quelle_wird_nichts_erfasst():
    """Ein Nachweis, der nicht sagt woher er kommt, ist keiner."""
    lead = _lead()
    antwort = json.loads(server.zustimmung_erfassen(lead, True, "  "))
    assert "fehler" in antwort
    assert server._zustimmung(_enrichment(lead)) is None


def test_erfasste_zustimmung_haelt_wortlaut_und_quelle():
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "WhatsApp-Antwort",
                               "Ja klar, gerne!")
    z = server._zustimmung(_enrichment(lead))
    assert z["erteilt"] is True
    assert z["quelle"] == "WhatsApp-Antwort"
    assert z["wortlaut"] == "Ja klar, gerne!"
    assert z["durch"] == "betreiber"
    assert z["am"]


def test_abgelehnte_zustimmung_ist_keine():
    lead = _lead()
    server.zustimmung_erfassen(lead, False, "WhatsApp-Antwort", "Lieber nicht")
    assert server._zustimmung(_enrichment(lead)) is None


def test_erfassen_wird_protokolliert():
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "Telefonat", "Passt")
    zeilen = server._q(
        "select payload from activities where lead_id = %s and type = "
        "'zustimmung'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["quelle"] == "Telefonat"


@pytest.mark.parametrize("kaputt", [
    None, {}, {"auto_zustimmung": None}, {"auto_zustimmung": "ja"},
    {"auto_zustimmung": {"erteilt": "ja"}},
    {"auto_zustimmung": {"erteilt": True, "widerrufen_am": "2026-08-25"}},
])
def test_alles_unklare_zaehlt_als_keine_zustimmung(kaputt):
    """Fail-closed: es geht darum, ob ein Programm unbeaufsichtigt
    schreibt."""
    assert server._zustimmung(kaputt) is None


# ---------------------------------------------------------------------------
# Der Kern: auto ohne Zustimmung faellt auf halbauto
# ---------------------------------------------------------------------------

def test_auto_ohne_zustimmung_bleibt_ein_entwurf():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    antwort = json.loads(server.antwort_entwerfen(lead, "Gerne, Donnerstag?"))
    assert "fehler" not in antwort
    assert antwort["wirksam_als"] == "halbauto"
    assert "NICHT zugestimmt" in antwort["hinweis"]
    zeilen = _entwuerfe(lead)
    assert len(zeilen) == 1
    assert zeilen[0]["status"] == "pending"
    assert zeilen[0]["approved_by"] is None


def test_auto_mit_zustimmung_geht_durch():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "WhatsApp-Antwort", "Ja")
    antwort = json.loads(server.antwort_entwerfen(lead, "Gerne, Donnerstag?"))
    assert antwort.get("wirksam_als") is None
    zeilen = _entwuerfe(lead)
    assert zeilen[0]["status"] == "approved"
    assert zeilen[0]["approved_by"] == "auto-betrieb"


def test_halbauto_braucht_keine_zustimmung():
    """Ein Entwurf zur Freigabe geht an niemanden — dafuer fragt man nicht."""
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "halbauto")
    antwort = json.loads(server.antwort_entwerfen(lead, "Gerne!"))
    assert "fehler" not in antwort
    assert _entwuerfe(lead)[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Widerruf — wirkt sofort, auch nach hinten
# ---------------------------------------------------------------------------

def test_widerruf_stoppt_freigegebene_auto_antworten():
    """Genau die waeren sonst die Nachrichten, die nach dem Widerruf noch
    ankommen."""
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "WhatsApp-Antwort", "Ja")
    server.antwort_entwerfen(lead, "Eine automatische Antwort.")
    assert _entwuerfe(lead)[0]["status"] == "approved"

    antwort = json.loads(server.zustimmung_widerrufen(lead, "Kundenwunsch"))
    assert antwort["gestoppte_entwuerfe"] == 1
    zeile = _entwuerfe(lead)[0]
    assert zeile["status"] == "rejected"
    assert "widerrufen" in zeile["error"].lower()


def test_widerruf_laesst_selbst_freigegebene_entwuerfe_stehen():
    """Was der Betreiber selbst freigegeben hat, hat er gelesen und
    gewollt — das anzuhalten waere seine Entscheidung, nicht unsere."""
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "Telefonat")
    d = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Von Hand."))
    server.entwurf_freigeben(d["draft_id"])
    server.zustimmung_widerrufen(lead)
    zeile = server._q("select status, approved_by from drafts where id = %s",
                      (d["draft_id"],))[0]
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] != "auto-betrieb"


def test_widerruf_ohne_zustimmung_sagt_es():
    lead = _lead()
    antwort = json.loads(server.zustimmung_widerrufen(lead))
    assert "fehler" in antwort
    assert "keine gueltige Zustimmung" in antwort["fehler"]


def test_nach_widerruf_entsteht_nur_noch_ein_entwurf():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "Telefonat")
    server.zustimmung_widerrufen(lead, "Kundenwunsch")
    antwort = json.loads(server.antwort_entwerfen(lead, "Noch eine Antwort."))
    assert antwort["wirksam_als"] == "halbauto"
    assert all(z["status"] == "pending" for z in _entwuerfe(lead)
               if z["body"] == "Noch eine Antwort.")


def test_widerruf_wird_protokolliert():
    lead = _lead()
    server.zustimmung_erfassen(lead, True, "Telefonat")
    server.zustimmung_widerrufen(lead, "Kunde moechte nicht mehr")
    zeilen = server._q(
        "select payload from activities where lead_id = %s and type = "
        "'zustimmung_widerrufen'", (lead,))
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["grund"] == "Kunde moechte nicht mehr"
