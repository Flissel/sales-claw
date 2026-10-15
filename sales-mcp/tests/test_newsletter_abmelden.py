"""Abmelden per Antwort (Newsletter an Kontakte, Entscheidung E2, 15.10.2026): eine Mail mit Betreff
"Abmelden" setzt den Absender auf die gemeinsame Verbotsliste und nimmt die Einwilligung zurueck.
Deterministisch, ohne Agent; laeuft im Mail-Dispatcher."""
import uuid

import pytest

import server


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _lead(email):
    return str(server._q("insert into leads (name, email, consent_status) values ('Anna Weber', %s, 'opt_in') "
                         "returning id", (email,))[0]["id"])


def _mail(von, betreff="Abmelden"):
    return {"von": von, "betreff": betreff, "message_id": f"{uuid.uuid4()}@example.com"}


def test_abmelden_sperrt_und_nimmt_einwilligung_zurueck():
    adresse = f"anna-{uuid.uuid4().hex[:8]}@example.com"
    lead = _lead(adresse)
    m = _mail(f"Anna Weber <{adresse.upper()}>", "AW: Abmelden")
    assert server._newsletter_abmeldungen([m]) == 1
    assert server._sperre(adresse, "")
    assert server._q("select consent_status from leads where id = %s", (lead,))[0]["consent_status"] == "unknown"
    akt = server._q("select payload from activities where lead_id = %s and type = 'newsletter_abmeldung'", (lead,))
    assert len(akt) == 1 and akt[0]["payload"]["message_id"] == m["message_id"]
    # dieselbe Mail ein zweites Mal: nichts Neues
    assert server._newsletter_abmeldungen([m]) == 0


def test_unbekannte_adresse_wird_trotzdem_gesperrt():
    adresse = f"fremd-{uuid.uuid4().hex[:8]}@example.com"
    assert server._newsletter_abmeldungen([_mail(adresse)]) == 1
    assert server._sperre(adresse, "")


@pytest.mark.parametrize("betreff", ["Re: Herbst im Laden", "Termin abmelden?", "", "Abmeldung vom Kurs am Freitag"])
def test_andere_mails_bleiben_unberuehrt(betreff):
    adresse = f"x-{uuid.uuid4().hex[:8]}@example.com"
    _lead(adresse)
    assert server._newsletter_abmeldungen([_mail(adresse, betreff)]) == 0
    assert not server._sperre(adresse, "")
