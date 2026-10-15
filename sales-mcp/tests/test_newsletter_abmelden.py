"""Abmelden per Antwort (Newsletter an Kontakte, Entscheidung E2, 15.10.2026). Deterministisch, ohne
Agent; laeuft im Mail-Dispatcher.

Nach drei Runden Commit-Sicherheitspruefung: eine "Abmelden"-Mail stoppt nur die Newsletter
(opt_in -> unknown). Die gemeinsame Verbotsliste setzt sie nicht - der Absender ist faelschbar,
und mehr als "kein Newsletter" darf eine Faelschung nicht bewirken."""
import uuid

import pytest

import server


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _lead(email, consent="opt_in"):
    return str(server._q("insert into leads (name, email, consent_status) values ('Anna Weber', %s, %s) "
                         "returning id", (email, consent))[0]["id"])


def _mail(von, betreff="Abmelden"):
    return {"von": von, "betreff": betreff, "message_id": f"{uuid.uuid4()}@example.com"}


def _adresse():
    return f"anna-{uuid.uuid4().hex[:8]}@example.com"


def _consent(lead):
    return server._q("select consent_status from leads where id = %s", (lead,))[0]["consent_status"]


def test_abmelden_stoppt_den_newsletter_ohne_globale_sperre():
    adresse = _adresse()
    lead = _lead(adresse)
    m = _mail(f"Anna Weber <{adresse.upper()}>", "AW: Abmelden")
    assert server._newsletter_abmeldungen([m]) == 1
    assert _consent(lead) == "unknown"
    assert not server._sperre(adresse, "")      # Verbotsliste nur ueber menschliche Wege
    akt = server._q("select payload from activities where lead_id = %s and type = 'newsletter_abmeldung'", (lead,))
    assert len(akt) == 1 and akt[0]["payload"]["message_id"] == m["message_id"]
    assert server._newsletter_abmeldungen([m]) == 0          # dieselbe Mail: nichts Neues


def test_abgemeldet_heisst_nicht_mehr_in_der_empfaengerliste():
    adresse = _adresse()
    lead = _lead(adresse)
    server._newsletter_abmeldungen([_mail(adresse)])
    assert lead not in [k["id"] for k in server._newsletter_empfaenger(str(uuid.uuid4()))]


def test_andere_einwilligung_bleibt_unberuehrt():
    adresse = _adresse()
    lead = _lead(adresse, consent="existing_customer")
    assert server._newsletter_abmeldungen([_mail(adresse)]) == 0
    assert _consent(lead) == "existing_customer"


def test_unbekannte_adresse_aendert_nichts():
    assert server._newsletter_abmeldungen([_mail(_adresse())]) == 0


@pytest.mark.parametrize("betreff", ["Re: Herbst im Laden", "Termin abmelden?", "", "Abmeldung vom Kurs am Freitag"])
def test_andere_mails_bleiben_unberuehrt(betreff):
    adresse = _adresse()
    lead = _lead(adresse)
    assert server._newsletter_abmeldungen([_mail(adresse, betreff)]) == 0
    assert _consent(lead) == "opt_in"
