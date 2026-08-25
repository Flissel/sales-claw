"""Vertragstests fuer die Autonomiestufe je Kontakt.

Betreiber am 25.08.2026, woertlich:

  „in der Kontakt liste sollte die Autonomie bestimmt werden heisst auto fuer
   openclaw immer zurueckschreiben / fuer half auto entwuerfe basierend auf
   der gesprachshistory erstellen letzten 20 nachrichten sollte reichen von
   beiden … manuell und ignore fuer ignorieren."

DER SATZ, DEN DIESE SUITE VERTEIDIGT: der Agent kann die Stufe nicht selbst
setzen. Er kann nur in ihr handeln. Ob eine Nachricht ohne menschlichen
Blick an einen Menschen geht, entscheiden DREI Tore, und keines davon der
Agent:

  1. die Autonomiestufe            — der Betreiber, nach dem Gespraech
  2. die WhatsApp-Kontaktfreigabe  — der Betreiber, ob ueberhaupt
  3. die Zustimmung des Kontakts   — der KONTAKT selbst (seit 25.08.2026,
                                      tests/test_zustimmung.py)

Faellt eines aus, entsteht hoechstens ein Entwurf zur Freigabe.

Der Anlass fuer die Strenge steht im Verlauf dieses Projekts: die
Auto-Antwort war schon einmal an und wurde am 22.08.2026 ausdruecklich
abgeschaltet („nur die nachricht analysiert wird die reinkommt und
eingeordnet stattdem das openclaw antwortet"). Sie kommt jetzt zurueck —
aber je Kontakt, abgestuft und fail-closed.
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


@pytest.fixture
def sammelkontakt_zurueck():
    vorher = server.UNBEKANNT_LEAD_ID
    yield
    server.UNBEKANNT_LEAD_ID = vorher


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _freigeben(lead):
    return json.loads(server.kontakt_freigeben(lead))


def _stufe(lead):
    z = server._q("select enrichment from leads where id = %s", (lead,))[0]
    return server._autonomie(z["enrichment"])


def _entwuerfe(lead):
    return server._q(
        "select id, status, approved_by, body from drafts where lead_id = %s "
        "order by created_at", (lead,))


# ---------------------------------------------------------------------------
# Die Stufen selbst
# ---------------------------------------------------------------------------

def test_die_vier_stufen_stehen_an_einer_stelle():
    assert server.AUTONOMIE_STUFEN == ("ignorieren", "manuell", "halbauto",
                                       "auto")
    assert server.AUTONOMIE_VORGABE == "manuell"
    assert set(server.AUTONOMIE_TEXT) == set(server.AUTONOMIE_STUFEN)


def test_vorgabe_ist_manuell():
    """Bestandskontakte sind stumm, ohne dass jemand etwas tun muss."""
    assert _stufe(_lead()) == "manuell"


@pytest.mark.parametrize("kaputt", [
    None, {}, {"autonomie": None}, {"autonomie": "auto"},
    {"autonomie": {"stufe": "vollgas"}}, {"autonomie": {"stufe": None}},
    {"autonomie": []},
])
def test_alles_unklare_zaehlt_als_manuell(kaputt):
    """Fail-closed wie bei der WhatsApp-Freigabe — ein Tippfehler macht
    keinen Kontakt gespraechig."""
    assert server._autonomie(kaputt) == "manuell"


@pytest.mark.parametrize("stufe", ["ignorieren", "manuell", "halbauto", "auto"])
def test_setzen_und_lesen(stufe):
    lead = _lead()
    antwort = json.loads(server.kontakt_autonomie_setzen(lead, stufe))
    assert "fehler" not in antwort
    assert antwort["stufe"] == stufe
    assert _stufe(lead) == stufe


def test_unbekannte_stufe_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.kontakt_autonomie_setzen(lead, "vollgas"))
    assert "fehler" in antwort
    assert _stufe(lead) == "manuell"


def test_setzen_wird_protokolliert():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "halbauto")
    server.kontakt_autonomie_setzen(lead, "auto")
    zeilen = server._q(
        "select payload from activities where lead_id = %s and type = "
        "'autonomie' order by created_at", (lead,))
    assert [z["payload"]["stufe"] for z in zeilen] == ["halbauto", "auto"]
    assert zeilen[1]["payload"]["vorher"] == "halbauto"


def test_auto_ohne_whatsapp_freigabe_warnt():
    """Die Stufe allein reicht nicht — und das sagt die Antwort sofort."""
    lead = _lead()
    antwort = json.loads(server.kontakt_autonomie_setzen(lead, "auto"))
    assert "achtung" in antwort
    assert "KEINE WhatsApp-Freigabe" in antwort["achtung"]


def test_auto_mit_freigabe_warnt_nicht():
    lead = _lead()
    _freigeben(lead)
    antwort = json.loads(server.kontakt_autonomie_setzen(lead, "auto"))
    assert "achtung" not in antwort


def test_sammelkontakt_bekommt_keine_stufe(sammelkontakt_zurueck):
    """Sonst antwortete der Agent allen Fremden auf einmal."""
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    server.UNBEKANNT_LEAD_ID = sammel
    antwort = json.loads(server.kontakt_autonomie_setzen(sammel, "auto"))
    assert "fehler" in antwort
    assert _stufe(sammel) == "manuell"


# ---------------------------------------------------------------------------
# Was die Stufe erlaubt — und was nicht
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stufe", ["manuell", "ignorieren"])
def test_ohne_stufe_entsteht_kein_entwurf(stufe):
    lead = _lead()
    _freigeben(lead)
    server.kontakt_autonomie_setzen(lead, stufe)
    antwort = json.loads(server.antwort_entwerfen(lead, "Hallo, gerne!"))
    assert "fehler" in antwort
    assert stufe in antwort["fehler"]
    assert _entwuerfe(lead) == []


def test_halbauto_erzeugt_einen_pending_entwurf():
    lead = _lead()
    _freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "halbauto")
    antwort = json.loads(server.antwort_entwerfen(lead, "Hallo, gerne!"))
    assert "fehler" not in antwort
    zeilen = _entwuerfe(lead)
    assert len(zeilen) == 1
    assert zeilen[0]["status"] == "pending"
    assert zeilen[0]["approved_by"] is None


def test_auto_erzeugt_einen_freigegebenen_entwurf():
    """DREI Tore, nicht zwei — seit dem Zustimmungs-Gate vom 25.08.2026.

    Diese Zusicherung stammt aus der Fassung davor und erwartete
    `approved`, sobald Stufe und WhatsApp-Freigabe standen. Seit der
    Kontakt selbst gefragt wird, gehoert seine Zustimmung dazu; ohne sie
    faellt `auto` still auf `halbauto` zurueck. Der Rueckfall selbst ist
    in tests/test_zustimmung.py festgenagelt — hier steht der Vollfall.
    """
    lead = _lead()
    _freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "auto")
    server.zustimmung_erfassen(lead, True, "WhatsApp-Antwort", "Ja gerne")
    antwort = json.loads(server.antwort_entwerfen(lead, "Hallo, gerne!"))
    assert "fehler" not in antwort
    zeilen = _entwuerfe(lead)
    assert len(zeilen) == 1
    assert zeilen[0]["status"] == "approved"
    # In JEDER Zeile sichtbar, dass kein Mensch daraufgesehen hat.
    assert zeilen[0]["approved_by"] == "auto-betrieb"


def test_auto_ohne_zustimmung_des_kontakts_bleibt_entwurf():
    """Das dritte Tor: der Kontakt selbst. Ausfuehrlich in
    tests/test_zustimmung.py."""
    lead = _lead()
    _freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "auto")
    antwort = json.loads(server.antwort_entwerfen(lead, "Hallo, gerne!"))
    assert antwort["wirksam_als"] == "halbauto"
    assert _entwuerfe(lead)[0]["status"] == "pending"


def test_auto_ohne_whatsapp_freigabe_erzeugt_nichts():
    """Zwei Gates, nicht eines: Stufe UND Kontaktfreigabe."""
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    antwort = json.loads(server.antwort_entwerfen(lead, "Hallo!"))
    assert "fehler" in antwort
    assert _entwuerfe(lead) == []


def test_der_agent_kann_die_stufe_nicht_umgehen():
    """Der Kern der Suite: kein Weg von 'manuell' zu einer Antwort."""
    lead = _lead()
    _freigeben(lead)
    # Ohne gesetzte Stufe steht der Kontakt auf manuell.
    assert "fehler" in json.loads(server.antwort_entwerfen(lead, "Hallo"))
    # Auch nicht ueber den Umweg eines gewoehnlichen Entwurfs mit
    # anschliessender Selbstfreigabe: entwurf_erstellen legt 'pending' an,
    # und freigeben kann nur ein Mensch (approved_by='betreiber').
    json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo"))
    zeilen = _entwuerfe(lead)
    assert len(zeilen) == 1 and zeilen[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Die Faelligkeitsliste
# ---------------------------------------------------------------------------

def _kundennachricht(lead, text="Haben Sie kurz Zeit?"):
    return server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'kundenantwort', %s) returning id",
        (lead, json.dumps({"text": text, "richtung": "eingehend",
                           "absender": "491701234567@c.us"})))[0]["id"]


def test_nur_halbauto_und_auto_stehen_in_der_faelligkeit():
    warten = {}
    for stufe in server.AUTONOMIE_STUFEN:
        lead = _lead(name=f"Kontakt {stufe}",
                     phone="+4917000000" + str(len(warten)).zfill(2))
        server.kontakt_autonomie_setzen(lead, stufe)
        _kundennachricht(lead)
        warten[stufe] = lead
    faellig = json.loads(server.antworten_faellig())
    drin = {str(e["lead_id"]) for e in faellig["eintraege"]}
    assert warten["halbauto"] in drin
    assert warten["auto"] in drin
    assert warten["manuell"] not in drin
    assert warten["ignorieren"] not in drin
    assert faellig["uebersprungen_weil_manuell"] >= 2


def test_faelligkeit_nennt_die_stufe_und_das_verlauf_limit():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "halbauto")
    _kundennachricht(lead)
    faellig = json.loads(server.antworten_faellig())
    treffer = [e for e in faellig["eintraege"] if str(e["lead_id"]) == lead]
    assert treffer and treffer[0]["autonomie"] == "halbauto"
    # „letzten 20 nachrichten … von beiden" — beide Richtungen zusammen.
    assert faellig["verlauf_limit"] == server.ANTWORT_VERLAUF == 20


def test_faelligkeit_aendert_nichts():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    _kundennachricht(lead)
    vorher = server._q("select count(*) n from activities")[0]["n"]
    server.antworten_faellig()
    assert server._q("select count(*) n from activities")[0]["n"] == vorher
    assert _entwuerfe(lead) == []
