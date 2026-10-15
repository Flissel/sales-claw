"""Abmelden per Antwort (Newsletter an Kontakte, Entscheidung E2, 15.10.2026). Deterministisch, ohne
Agent; laeuft im Mail-Dispatcher.

Sicherheits-Nachbesserung (Commit-Review 15.10.): der Absender einer Mail ist faelschbar. Deshalb
- stoppt jede "Abmelden"-Mail die Newsletter (opt_in -> unknown) - mehr kann eine Faelschung nicht,
- kommt die Adresse nur auf die gemeinsame Verbotsliste, wenn der Mailserver den Absender bestaetigt
  hat (DKIM/SPF/DMARC pass im obersten Authentication-Results),
- aendern unbekannte Absender nichts, und andere Einwilligungen bleiben unberuehrt."""
import uuid

import pytest

import postfach
import server


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _lead(email, consent="opt_in"):
    return str(server._q("insert into leads (name, email, consent_status) values ('Anna Weber', %s, %s) "
                         "returning id", (email, consent))[0]["id"])


def _mail(von, betreff="Abmelden", bestaetigt=True):
    return {"von": von, "betreff": betreff, "message_id": f"{uuid.uuid4()}@example.com",
            "absender_bestaetigt": bestaetigt}


def _adresse():
    return f"anna-{uuid.uuid4().hex[:8]}@example.com"


def _consent(lead):
    return server._q("select consent_status from leads where id = %s", (lead,))[0]["consent_status"]


def test_bestaetigter_absender_wird_gesperrt_und_verliert_einwilligung():
    adresse = _adresse()
    lead = _lead(adresse)
    m = _mail(f"Anna Weber <{adresse.upper()}>", "AW: Abmelden")
    assert server._newsletter_abmeldungen([m]) == 1
    assert server._sperre(adresse, "") and _consent(lead) == "unknown"
    akt = server._q("select payload from activities where lead_id = %s and type = 'newsletter_abmeldung'", (lead,))
    assert len(akt) == 1 and akt[0]["payload"]["message_id"] == m["message_id"]
    assert akt[0]["payload"]["bestaetigt"] is True
    assert server._newsletter_abmeldungen([m]) == 0          # dieselbe Mail: nichts Neues


def test_unbestaetigter_absender_stoppt_nur_den_newsletter():
    adresse = _adresse()
    lead = _lead(adresse)
    assert server._newsletter_abmeldungen([_mail(adresse, bestaetigt=False)]) == 1
    assert _consent(lead) == "unknown" and not server._sperre(adresse, "")


def test_andere_einwilligung_bleibt_bei_gefaelschtem_abmelden():
    adresse = _adresse()
    lead = _lead(adresse, consent="existing_customer")
    assert server._newsletter_abmeldungen([_mail(adresse, bestaetigt=False)]) == 0
    assert _consent(lead) == "existing_customer" and not server._sperre(adresse, "")


def test_unbekannte_adresse_aendert_nichts():
    adresse = _adresse()
    assert server._newsletter_abmeldungen([_mail(adresse)]) == 0
    assert not server._sperre(adresse, "")


@pytest.mark.parametrize("betreff", ["Re: Herbst im Laden", "Termin abmelden?", "", "Abmeldung vom Kurs am Freitag"])
def test_andere_mails_bleiben_unberuehrt(betreff):
    adresse = _adresse()
    lead = _lead(adresse)
    assert server._newsletter_abmeldungen([_mail(adresse, betreff)]) == 0
    assert _consent(lead) == "opt_in"


@pytest.mark.parametrize("koepfe, erwartet", [
    (["mx.example.net; dkim=pass header.d=laden.de; spf=pass"], True),
    (["mx.example.net; dmarc=pass"], True),
    (["mx.example.net; dkim=fail; spf=softfail", "faelscher; dkim=pass"], False),   # nur der oberste zaehlt
    ([], False),
])
def test_absender_bestaetigt(koepfe, erwartet):
    import email.message
    n = email.message.Message()
    for k in koepfe:
        n["Authentication-Results"] = k
    assert postfach.absender_bestaetigt(n) is erwartet
