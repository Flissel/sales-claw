"""Double-Opt-in im Mail-Dispatcher (20.10.2026): die Bestaetigungsmail geht ohne Freigabe raus,
mit festem Text an genau den Absender der Anmeldung; vermerkt wird erst nach dem Versand."""
import email
import os
import uuid

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mail_dispatch  # noqa: E402
import newsletter_anmeldung as na  # noqa: E402
import postfach  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture
def versand(monkeypatch):
    gesendet = []
    monkeypatch.setattr(mail_dispatch, "SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "haus@example.org")
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "x")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "haus@example.org")
    monkeypatch.setattr(mail_dispatch, "senden", lambda n, ident=None: gesendet.append(n))
    monkeypatch.setattr(mail_dispatch, "_sent_ablegen", lambda n: None)
    return gesendet


def _adresse():
    return f"neu-{uuid.uuid4().hex[:8]}@example.com"


def _mail(von, betreff, **extra):
    return {"von": von, "betreff": betreff, "auszug": "", "message_id": f"{uuid.uuid4()}@example.com",
            **extra}


def test_anmeldung_bekommt_bestaetigungsmail_und_antwort_setzt_opt_in(versand):
    adresse = _adresse()
    anmeldung = _mail(adresse, "Anmelden")
    assert mail_dispatch.anmeldungen_pruefen([anmeldung])["gesendet"] == 1
    assert len(versand) == 1
    n = versand[0]
    assert n["To"] == adresse and n["From"] == "haus@example.org"
    assert n["In-Reply-To"] == f"<{anmeldung['message_id']}>"
    code = na.CODE_MUSTER.search(n["Subject"]).group(1)
    assert code in n.get_content()
    # zweiter Lauf mit derselben Mail: keine zweite Bestaetigungsmail
    assert mail_dispatch.anmeldungen_pruefen([anmeldung])["gesendet"] == 0
    # Antwort mit dem Code
    bilanz = mail_dispatch.anmeldungen_pruefen([anmeldung, _mail(adresse, f"AW: {n['Subject']}")])
    assert bilanz["bestaetigt"] == 1
    assert server._q("select consent_status from leads where lower(email) = %s",
                     (adresse,))[0]["consent_status"] == "opt_in"


def test_versandfehler_vermerkt_nichts_und_der_naechste_lauf_versucht_es_wieder(versand, monkeypatch):
    def scheitern(n, ident=None):
        raise mail_dispatch.VersandFehler("SMTP weg")
    monkeypatch.setattr(mail_dispatch, "senden", scheitern)
    m = _mail(_adresse(), "Anmelden")
    assert mail_dispatch.anmeldungen_pruefen([m])["fehler"] == 1
    monkeypatch.setattr(mail_dispatch, "senden", lambda n, ident=None: versand.append(n))
    assert mail_dispatch.anmeldungen_pruefen([m])["gesendet"] == 1


def test_ohne_postfach_des_ladens_geht_nichts_raus(versand, monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "")
    assert mail_dispatch.anmeldungen_pruefen([_mail(_adresse(), "Anmelden")])["gesendet"] == 0
    assert versand == []


def test_fehlende_message_id_wird_kein_kaputter_bezug(versand):
    m = _mail(_adresse(), "Anmelden")
    m["message_id"] = ""
    mail_dispatch.anmeldungen_pruefen([m])
    assert versand and versand[0]["In-Reply-To"] is None


def _roh(**koepfe):
    n = email.message.EmailMessage()
    n["From"] = "a@example.com"
    n["Subject"] = "AW: Code ABCD-EFGH"
    for k, v in koepfe.items():
        n[k.replace("_", "-")] = v
    n.set_content("x")
    return n


@pytest.mark.parametrize("koepfe", [{"Auto_Submitted": "auto-replied"}, {"X_Autoreply": "yes"},
                                    {"Precedence": "auto_reply"}, {"Return_Path": "<>"}])
def test_postfach_erkennt_automatische_mails(koepfe):
    assert postfach._automatisch(_roh(**koepfe))


def test_postfach_normale_antwort_ist_nicht_automatisch():
    assert not postfach._automatisch(_roh(Auto_Submitted="no"))
    assert not postfach._automatisch(_roh())
