"""Passwort vergessen — der Einmal-Link (Betreiber-Auftrag 16.09.2026).

Es gab bisher genau einen Weg zu einem neuen Passwort:
`benutzer_anlegen.py` auf der Kommandozeile IM CONTAINER. Wer keine Shell
auf der VM hat - und der zweite Benutzer dieses Hauses hat keine -, war
ausgesperrt.

Was diese Tests festhalten, ist ueberwiegend, was NICHT gehen darf:

  * Ein leeres `reset_hash` darf kein Schluessel sein. `sha256("")` ist ein
    gueltiger Hash, und ohne die Leerpruefung waere JEDES Konto ohne
    offenen Reset mit einem leeren Token uebernehmbar.
  * Ein Token gilt EINMAL. Nach dem Setzen ist er weg, nicht bloss alt.
  * Ein abgelaufener Token traegt nicht, auch nicht knapp.
  * Die Maske verraet nicht, welche Konten es gibt - eine Antwort fuer
    jeden Ausgang, wie bei der Anmeldung.
  * Geht die Mail nicht raus, bleibt kein gueltiger Token stehen. Ein
    offenes Fenster, das niemand bemerkt, ist schlimmer als ein Fehler.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os
import time
from unittest import mock

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import passwort_reset  # noqa: E402
import server  # noqa: E402
import mail_dispatch  # noqa: E402
import ui  # noqa: E402


# Ohne expliziten Host-Header antwortet die HostWache mit 421 (Falscher
# Host) - TestClient() setzt sonst "testserver". Dieselbe Falle wie in
# test_kalender_verbinden.py und test_team_sicht.py, dort schon dokumentiert.
HOST_OK = {"host": "127.0.0.1:8791"}


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer")
        conn.execute("truncate sales_test.benutzer_mails")
    yield


def _benutzer(name="ivan", email="ivan@example.invalid", aktiv=True):
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv, email) "
        "values (%s, 'kalender', %s, %s, nullif(%s,'')) returning name",
        (name, ui._passwort_hashen("altes-passwort-x"), aktiv, email or ""))
    return name


# --- Die reine Rechnung ----------------------------------------------------

def test_token_ist_nicht_zu_erraten_und_wandert_gehasht_in_die_db():
    klartext, gehasht = passwort_reset.token_erzeugen()
    assert len(klartext) >= 40                 # 32 Bytes urlsafe
    assert klartext != gehasht
    assert gehasht == passwort_reset.token_hashen(klartext)
    # Zwei Aufrufe ergeben nie dasselbe.
    assert passwort_reset.token_erzeugen()[0] != klartext


def test_leerer_token_oeffnet_nichts():
    """Der gefaehrlichste Fall: sha256("") IST ein gueltiger Hash. Ohne die
    Leerpruefung waere jedes Konto ohne offenen Reset uebernehmbar."""
    assert passwort_reset.token_stimmt("", "") is False
    assert passwort_reset.token_stimmt("", passwort_reset.token_hashen("")) is False
    assert passwort_reset.token_stimmt("irgendwas", "") is False
    assert passwort_reset.token_stimmt(None, None) is False


def test_falscher_token_stimmt_nicht():
    _, gehasht = passwort_reset.token_erzeugen()
    assert passwort_reset.token_stimmt("daneben", gehasht) is False


def test_fehlender_ablauf_gilt_als_abgelaufen():
    """Fail-closed: ein Konto ohne `reset_bis` hat keinen offenen Reset."""
    assert passwort_reset.abgelaufen(None) is True


def test_ablauf_rechnet_in_beiden_formen():
    jetzt = 1_000_000.0
    assert passwort_reset.abgelaufen(jetzt + 10, jetzt) is False
    assert passwort_reset.abgelaufen(jetzt - 1, jetzt) is True
    from datetime import datetime, timezone
    frueher = datetime.fromtimestamp(jetzt - 1, tz=timezone.utc)
    assert passwort_reset.abgelaufen(frueher, jetzt) is True


def test_bremse_greift_nur_kurz_nach_dem_letzten_link():
    jetzt = 1_000_000.0
    assert passwort_reset.bremse_greift(None, jetzt) is False
    assert passwort_reset.bremse_greift(jetzt - 10, jetzt) is True
    assert passwort_reset.bremse_greift(
        jetzt - passwort_reset.BREMSE_S - 1, jetzt) is False


def test_passwort_mindestlaenge_deckt_sich_mit_benutzer_anlegen():
    """Zwei Orte, dieselbe Regel - laufen sie auseinander, faellt es hier
    auf und nicht erst beim Benutzer."""
    import benutzer_anlegen
    assert passwort_reset.passwort_taugt("neun-zeic")            # 9
    assert passwort_reset.passwort_taugt("zehn-zeich") == ""     # 10
    assert "10 Zeichen" in benutzer_anlegen.anlegen("x", "lesen", "kurz")


def test_link_nimmt_die_basis_aus_der_umgebung_nicht_aus_der_anfrage():
    link = passwort_reset.link_bauen("https://haus.example/", "a b", "t/k+n")
    assert link.startswith("https://haus.example/passwort-neu?")
    assert "a%20b" in link or "a+b" in link
    assert "t%2Fk%2Bn" in link                 # Sonderzeichen kodiert


def test_mailtext_traegt_den_link_und_beruhigt():
    text = passwort_reset.mailtext("ivan", "https://x/y")
    assert "https://x/y" in text
    assert "30 Minuten" in text
    assert "musst du nichts tun" in text       # wer es nicht war


# --- Die Verdrahtung -------------------------------------------------------

def _anfordern(name):
    """POST /passwort-vergessen, ohne echten Webserver.

    Die Seite VERSENDET NICHTS mehr - sie legt einen Zettel. Kein Umbau um
    des Umbaus willen: `sales-ui` hat keine SMTP-Umgebung und darf nach
    T5a keine bekommen (Sendemacht nur bei den Versendern, damit das
    Freigabe-Tor die Datenbank bleibt). Der erste Anlauf rief hier
    `mail_dispatch.senden` im UI-Container auf und konnte NIE senden.
    """
    from starlette.testclient import TestClient
    with TestClient(ui.app) as client:
        return client.post("/passwort-vergessen", headers=HOST_OK,
                           data={"csrf": ui.CSRF_TOKEN, "name": name})


def _zettel(name=None):
    """Konto-Zettel, wahlweise fuer einen Namen."""
    if name is None:
        return server._q("select id, benutzer, art, status, grund "
                         "from benutzer_mails order by erstellt_am")
    return server._q("select id, benutzer, art, status, grund "
                     "from benutzer_mails where benutzer = %s "
                     "order by erstellt_am", (name,))


def test_unbekannter_name_sieht_dasselbe_wie_ein_bekannter():
    """Die Maske verraet nicht, welche Konten es gibt."""
    _benutzer("ivan")
    mit = _anfordern("ivan")
    ohne = _anfordern("gibtsnicht")
    assert mit.status_code == ohne.status_code == 200
    assert ui._RESET_ANTWORT[:60] in mit.text
    assert ui._RESET_ANTWORT[:60] in ohne.text


def test_die_seite_legt_nur_einen_zettel_und_keinen_token():
    """Der Klartext soll die Datenbank NIE erreichen - auch nicht kurz."""
    _benutzer("ivan")
    _anfordern("ivan")
    zettel = _zettel("ivan")
    assert len(zettel) == 1
    assert zettel[0]["art"] == "passwort_reset"
    assert zettel[0]["status"] == "offen"
    z = server._q("select reset_hash, reset_bis, reset_zuletzt "
                  "from benutzer where name = %s", ("ivan",))[0]
    assert z["reset_hash"] is None and z["reset_bis"] is None
    assert z["reset_zuletzt"] is not None       # die Bremse laeuft ab jetzt


def test_konto_ohne_adresse_bekommt_keinen_zettel():
    _benutzer("ohnemail", email="")
    antwort = _anfordern("ohnemail")
    assert antwort.status_code == 200
    assert _zettel() == []


def test_inaktives_konto_bekommt_keinen_zettel():
    _benutzer("ruhend", aktiv=False)
    _anfordern("ruhend")
    assert _zettel() == []


def test_unbekannter_name_bekommt_keinen_zettel():
    _anfordern("gibtsnicht")
    assert _zettel() == []


def test_zweite_anforderung_greift_in_die_bremse():
    _benutzer("ivan")
    _anfordern("ivan")
    _anfordern("ivan")
    assert len(_zettel("ivan")) == 1            # kein zweiter Zettel


# --- Der Versender: hier entsteht der Token, hier liegt die Sendemacht ----

def _versenden(zettel_id, basis="https://haus.example", fehler=None):
    """verarbeite_kontomail mit abgefangenem SMTP-Ausgang."""
    def _ausgang(_nachricht):
        if fehler is not None:
            raise fehler

    with mock.patch.object(mail_dispatch, "UI_BASIS_URL", basis), \
         mock.patch.object(mail_dispatch, "EMAIL_ABSENDER",
                           "haus@example.invalid"), \
         mock.patch.object(mail_dispatch, "senden",
                           side_effect=_ausgang) as gesendet:
        ausgang = mail_dispatch.verarbeite_kontomail(zettel_id)
    return ausgang, gesendet


def test_versender_erzeugt_den_token_und_verschickt():
    _benutzer("ivan")
    _anfordern("ivan")
    ausgang, gesendet = _versenden(_zettel("ivan")[0]["id"])
    assert ausgang == "gesendet"
    gesendet.assert_called_once()
    z = server._q("select reset_hash, reset_bis from benutzer where name = %s",
                  ("ivan",))[0]
    assert z["reset_hash"] and z["reset_bis"]   # jetzt erst gibt es einen
    assert _zettel("ivan")[0]["status"] == "gesendet"


def test_der_klartext_steht_nirgends_in_der_datenbank():
    """Die eigentliche Zusage: gespeichert wird nur der Hash."""
    import urllib.parse
    _benutzer("ivan")
    _anfordern("ivan")
    _, gesendet = _versenden(_zettel("ivan")[0]["id"])
    rumpf = gesendet.call_args[0][0].get_content()
    roh = rumpf.split("token=")[1].split()[0]
    klartext = urllib.parse.unquote(roh)
    gespeichert = server._q("select reset_hash from benutzer where name = %s",
                            ("ivan",))[0]["reset_hash"]
    assert klartext and klartext not in gespeichert
    assert passwort_reset.token_stimmt(klartext, gespeichert)


def test_scheiternder_versand_raeumt_token_und_bremse_weg():
    """Ein Fehlschlag, den der Mensch nicht verursacht hat, darf ihn nicht
    aussperren - genau das ist am 17.09.2026 passiert."""
    _benutzer("ivan")
    _anfordern("ivan")
    ausgang, _ = _versenden(_zettel("ivan")[0]["id"],
                            fehler=mail_dispatch.VersandFehler("SMTP tot"))
    assert ausgang == "fehler"
    z = server._q("select reset_hash, reset_bis, reset_zuletzt "
                  "from benutzer where name = %s", ("ivan",))[0]
    assert z["reset_hash"] is None and z["reset_bis"] is None
    assert z["reset_zuletzt"] is None           # die Bremse ist offen
    _anfordern("ivan")                          # und der naechste geht sofort
    assert len(_zettel("ivan")) == 2


def test_ohne_basis_adresse_wird_nichts_versendet():
    """Lieber keine Mail als eine mit totem Link."""
    _benutzer("ivan")
    _anfordern("ivan")
    ausgang, gesendet = _versenden(_zettel("ivan")[0]["id"], basis="")
    assert ausgang == "fehler"
    gesendet.assert_not_called()
    assert server._q("select reset_zuletzt from benutzer where name = %s",
                     ("ivan",))[0]["reset_zuletzt"] is None


def test_zwischenzeitlich_deaktiviertes_konto_bekommt_nichts():
    """Zwischen Zettel und Versand kann sich etwas aendern - der Versender
    glaubt der Oberflaeche nicht, er prueft noch einmal."""
    _benutzer("ivan")
    _anfordern("ivan")
    server._q("update benutzer set aktiv = false where name = %s "
              "returning name", ("ivan",))
    ausgang, gesendet = _versenden(_zettel("ivan")[0]["id"])
    assert ausgang == "fehler"
    gesendet.assert_not_called()


def test_ein_zettel_wird_nur_einmal_versendet():
    _benutzer("ivan")
    _anfordern("ivan")
    zid = _zettel("ivan")[0]["id"]
    _versenden(zid)
    ausgang, gesendet = _versenden(zid)
    assert ausgang == "uebersprungen"
    gesendet.assert_not_called()


def _token_setzen(name, klartext, sekunden=600):
    server._q(
        "update benutzer set reset_hash = %s, "
        "reset_bis = now() + make_interval(secs => %s) where name = %s "
        "returning name",
        (passwort_reset.token_hashen(klartext), sekunden, name))


def _neu_setzen(name, token, passwort, passwort2=None):
    from starlette.testclient import TestClient
    with TestClient(ui.app) as client:
        return client.post("/passwort-neu", headers=HOST_OK, data={
            "csrf": ui.CSRF_TOKEN, "name": name, "token": token,
            "passwort": passwort,
            "passwort2": passwort if passwort2 is None else passwort2})


def test_gueltiger_token_setzt_das_passwort():
    _benutzer("ivan")
    _token_setzen("ivan", "geheim-token")
    antwort = _neu_setzen("ivan", "geheim-token", "ein-neues-passwort")
    assert antwort.status_code == 200
    z = server._q("select passwort_hash, reset_hash, reset_bis from benutzer "
                  "where name = %s", ("ivan",))[0]
    assert ui._passwort_pruefen("ein-neues-passwort", z["passwort_hash"])
    # Einmal heisst einmal: der Token ist weg, nicht bloss alt.
    assert z["reset_hash"] is None and z["reset_bis"] is None


def test_derselbe_link_traegt_kein_zweites_mal():
    _benutzer("ivan")
    _token_setzen("ivan", "geheim-token")
    _neu_setzen("ivan", "geheim-token", "ein-neues-passwort")
    zweite = _neu_setzen("ivan", "geheim-token", "noch-ein-passwort")
    assert zweite.status_code == 400
    # Und das erste Passwort gilt weiter.
    z = server._q("select passwort_hash from benutzer where name = %s",
                  ("ivan",))[0]
    assert ui._passwort_pruefen("ein-neues-passwort", z["passwort_hash"])


def test_abgelaufener_token_traegt_nicht():
    _benutzer("ivan")
    _token_setzen("ivan", "geheim-token", sekunden=-1)
    antwort = _neu_setzen("ivan", "geheim-token", "ein-neues-passwort")
    assert antwort.status_code == 400
    assert "gilt nicht mehr" in antwort.text


def test_ohne_offenen_reset_oeffnet_auch_ein_leerer_token_nichts():
    """Der Fall, den die Leerpruefung in token_stimmt abfaengt - hier an
    der echten Verdrahtung nachgewiesen."""
    _benutzer("ivan")
    for token in ("", "irgendwas"):
        antwort = _neu_setzen("ivan", token, "ein-neues-passwort")
        assert antwort.status_code == 400, token
    z = server._q("select passwort_hash from benutzer where name = %s",
                  ("ivan",))[0]
    assert ui._passwort_pruefen("altes-passwort-x", z["passwort_hash"])


def test_zu_kurzes_passwort_wird_abgewiesen_und_der_token_bleibt():
    """Ein Tippfehler darf den Link nicht verbrennen."""
    _benutzer("ivan")
    _token_setzen("ivan", "geheim-token")
    antwort = _neu_setzen("ivan", "geheim-token", "kurz")
    assert antwort.status_code == 200
    assert "10 Zeichen" in antwort.text
    assert server._q("select reset_hash from benutzer where name = %s",
                     ("ivan",))[0]["reset_hash"] is not None


def test_ungleiche_eingaben_werden_abgewiesen_und_der_token_bleibt():
    _benutzer("ivan")
    _token_setzen("ivan", "geheim-token")
    antwort = _neu_setzen("ivan", "geheim-token", "ein-neues-passwort",
                          passwort2="ein-anderes-passwort")
    assert "nicht gleich" in antwort.text
    assert server._q("select reset_hash from benutzer where name = %s",
                     ("ivan",))[0]["reset_hash"] is not None


def test_beide_seiten_sind_ohne_anmeldung_erreichbar():
    """Wer sein Passwort vergessen hat, kann sich nicht anmelden - eine
    Wache davor schuetzte die Seiten vor ihrem einzigen Benutzer."""
    from starlette.testclient import TestClient
    with mock.patch.object(ui, "UI_SESSION_SECRET", "scharf-geschaltet"):
        with TestClient(ui.app) as client:
            for pfad in ("/passwort-vergessen", "/passwort-neu"):
                antwort = client.get(pfad, headers=HOST_OK,
                                     follow_redirects=False)
                assert antwort.status_code != 303, f"{pfad} leitet zur Anmeldung"


def test_die_anmeldemaske_zeigt_den_weg():
    from starlette.testclient import TestClient
    with TestClient(ui.app) as client:
        assert "/passwort-vergessen" in client.get(
            "/login", headers=HOST_OK).text
