"""Newsletter-Anmeldung per Mail mit Bestaetigung (Double-Opt-in, Betreiber 20.10.2026, A2 b).

Was diese Suite verteidigt:
1. "Anmelden" allein setzt NIE opt_in - erst die Antwort mit dem Einmal-Code.
2. Der Code zaehlt nur von der angemeldeten Adresse, nie aus einer automatischen Antwort.
3. Hoechstens eine Bestaetigungsmail je Adresse und Sperrfrist; der Code steht nur als Hash in der DB.
4. Verbotsliste, Loeschantrag und privat gehen jedem opt_in vor."""
import uuid

import pytest

import newsletter_anmeldung as na
import server
import sperrliste


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _adresse():
    return f"neu-{uuid.uuid4().hex[:8]}@example.com"


def _mail(von, betreff, auszug="", **extra):
    return {"von": von, "betreff": betreff, "auszug": auszug,
            "message_id": f"{uuid.uuid4()}@example.com", **extra}


def _consent(lead):
    return server._q("select consent_status from leads where id = %s", (lead,))[0]["consent_status"]


def _anmelden(adresse, betreff="Anmelden"):
    """Anmeldung durchspielen wie sales-mail: anfragen -> (Versand) -> vermerken. Gibt (anfrage, code)."""
    anfragen = na.anfragen([_mail(adresse, betreff)])
    assert len(anfragen) == 1
    code, h = na.code_neu()
    na.vermerken(anfragen[0], h)
    return anfragen[0], code


@pytest.mark.parametrize("betreff", ["Anmelden", "anmelden!", "AW: Anmelden", "Newsletter anmelden",
                                     "Newsletter: Anmelden"])
def test_betreff_wird_erkannt(betreff):
    assert na.ANMELDE_BETREFF.match(betreff)


@pytest.mark.parametrize("betreff", ["Abmelden", "Wie kann ich mich anmelden?", "Anmeldung zum Termin"])
def test_anderes_ist_keine_anmeldung(betreff):
    assert not na.ANMELDE_BETREFF.match(betreff)


def test_unbekannte_adresse_wird_kontakt_und_bleibt_ohne_einwilligung():
    adresse = _adresse()
    anfrage, _ = _anmelden(adresse)
    zeile = server._q("select email, source, consent_status from leads where id = %s",
                      (anfrage["lead_id"],))[0]
    assert zeile["email"] == adresse and zeile["source"] == "newsletter_anmeldung"
    assert zeile["consent_status"] == "unknown"           # Anmelden allein ist KEIN Ja


def test_bestaetigung_mit_code_setzt_opt_in_mit_nachweis():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    betreff, rumpf = na.mailtext(code)
    assert code in betreff and code in rumpf
    antwort = _mail(f"Neu <{adresse.upper()}>", f"AW: {betreff}")
    assert na.bestaetigungen([antwort]) == 1
    assert _consent(anfrage["lead_id"]) == "opt_in"
    nachweis = server._q("select payload from activities where lead_id = %s and type = 'werbe_einwilligung'",
                         (anfrage["lead_id"],))
    assert len(nachweis) == 1
    p = nachweis[0]["payload"]
    assert p["weg"] == "double_opt_in" and p["durch"] == "kontakt" and p["art"] == "opt_in"
    assert p["anmelde_message_id"] == anfrage["message_id"]
    assert p["bestaetigungs_message_id"] == antwort["message_id"]
    assert p["angemeldet_am"] and p["bestaetigt_am"]
    assert na.bestaetigungen([antwort]) == 0              # dieselbe Antwort: nichts Neues


def test_code_im_text_reicht_auch_wenn_der_betreff_geaendert_wurde():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    assert na.bestaetigungen([_mail(adresse, "Ja bitte", auszug=f"gerne. > Code {code.lower()}")]) == 1
    assert _consent(anfrage["lead_id"]) == "opt_in"


def test_code_im_klartext_steht_nirgends_in_der_datenbank():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    roh = server._q("select payload::text as t from activities where lead_id = %s", (anfrage["lead_id"],))
    assert all(code not in z["t"] for z in roh)


def test_gefaelschter_absender_ohne_code_bestaetigt_nichts():
    adresse = _adresse()
    anfrage, _ = _anmelden(adresse)
    falsch, _ = na.code_neu()
    assert na.bestaetigungen([_mail(adresse, f"AW: Newsletter bestätigen – Code {falsch}")]) == 0
    assert _consent(anfrage["lead_id"]) == "unknown"


def test_richtiger_code_von_anderer_adresse_zaehlt_nicht():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    assert na.bestaetigungen([_mail(_adresse(), f"AW: Code {code}")]) == 0
    assert _consent(anfrage["lead_id"]) == "unknown"


@pytest.mark.parametrize("mail", [
    {"betreff": "Automatische Antwort: Newsletter bestätigen – Code {c}"},
    {"betreff": "Abwesenheitsnotiz: Code {c}"},
    {"betreff": "Out of Office: Code {c}"},
    {"betreff": "AW: Newsletter bestätigen – Code {c}", "automatisch": True},
])
def test_automatische_antwort_ist_nie_ein_ja(mail):
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    m = _mail(adresse, mail["betreff"].format(c=code), automatisch=mail.get("automatisch", False))
    assert na.bestaetigungen([m]) == 0
    assert _consent(anfrage["lead_id"]) == "unknown"


def test_unzustellbar_vom_mailer_daemon_ist_kein_ja():
    m = {"von": "MAILER-DAEMON@example.com", "betreff": "x"}
    assert na.automatisch(m)


def test_abgelaufener_code_zaehlt_nicht():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    server._q("update activities set created_at = now() - interval '8 days' where lead_id = %s "
              "and type = 'newsletter_anmeldung' returning id", (anfrage["lead_id"],))
    assert na.bestaetigungen([_mail(adresse, f"AW: Code {code}")]) == 0
    assert _consent(anfrage["lead_id"]) == "unknown"


def test_sperrfrist_hoechstens_eine_bestaetigungsmail_je_tag():
    adresse = _adresse()
    _anmelden(adresse)
    assert na.anfragen([_mail(adresse, "Anmelden")]) == []


def test_dieselbe_mail_loest_nur_einmal_aus():
    adresse = _adresse()
    m = _mail(adresse, "Anmelden")
    anfrage = na.anfragen([m])[0]
    na.vermerken(anfrage, na.code_neu()[1])
    server._q("update activities set created_at = now() - interval '2 days' where lead_id = %s "
              "returning id", (anfrage["lead_id"],))       # Sperrfrist vorbei - trotzdem nicht dieselbe Mail
    assert na.anfragen([m]) == []


def test_doppelt_im_selben_lauf_nur_eine_anfrage():
    adresse = _adresse()
    assert len(na.anfragen([_mail(adresse, "Anmelden"), _mail(adresse, "anmelden")])) == 1


def test_ohne_vermerk_wird_erneut_versucht():
    """Scheitert der Versand, vermerkt sales-mail nichts - der naechste Lauf versucht es wieder."""
    adresse = _adresse()
    m = _mail(adresse, "Anmelden")
    assert len(na.anfragen([m])) == 1
    assert len(na.anfragen([m])) == 1
    assert server._q("select count(*) as n from leads where lower(email) = %s", (adresse,))[0]["n"] == 1


def test_bestehender_opt_in_bekommt_keine_mail():
    adresse = _adresse()
    server._q("insert into leads (name, email, consent_status) values ('A', %s, 'opt_in') returning id",
              (adresse,))
    assert na.anfragen([_mail(adresse, "Anmelden")]) == []


def test_bestehender_kontakt_wird_wiederverwendet():
    adresse = _adresse()
    lead = str(server._q("insert into leads (name, email) values ('Anna Weber', %s) returning id",
                         (adresse.upper(),))[0]["id"])
    assert na.anfragen([_mail(adresse, "Anmelden")])[0]["lead_id"] == lead


def test_verbotsliste_geht_vor():
    adresse = _adresse()
    sperrliste.sperren(server._q, email=adresse, quelle="test", grund="abgemeldet")
    assert na.anfragen([_mail(adresse, "Anmelden")]) == []


def test_verbotsliste_nach_anmeldung_verhindert_opt_in():
    adresse = _adresse()
    anfrage, code = _anmelden(adresse)
    sperrliste.sperren(server._q, email=adresse, quelle="test", grund="Loeschung")
    assert na.bestaetigungen([_mail(adresse, f"AW: Code {code}")]) == 0
    assert _consent(anfrage["lead_id"]) == "unknown"


def test_loeschantrag_geht_vor():
    adresse = _adresse()
    server._q("insert into leads (name, email, enrichment) values ('A', %s, %s::jsonb) returning id",
              (adresse, server._json({server.LOESCH_SCHLUESSEL: {"am": "2026-10-01"}})))
    assert na.anfragen([_mail(adresse, "Anmelden")]) == []


def test_ungueltige_adresse_wird_ignoriert():
    assert na.anfragen([_mail("kein-at-zeichen", "Anmelden")]) == []
