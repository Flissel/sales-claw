"""Vertragstests der UI-Anmeldung (E1/F4, 31.08.2026) gegen sales_test.

Die Anmeldung ist SCHARF, sobald `UI_SESSION_SECRET` gesetzt ist — ohne
Secret verhaelt sich die Oberflaeche wie vorher (Uebergangszustand, den
der Betreiber mit deploy/benutzer-anlegen.sh beendet). Scharf heisst:

1. Ohne gueltige Sitzung: jede Seite leitet auf /login, jeder POST wird
   abgelehnt. /login selbst bleibt offen.
2. Die Sitzung ist ein signierter Cookie (HMAC ueber name|ablauf) —
   faelschen, ablaufen lassen oder den Benutzer deaktivieren beendet
   sie. Rolle und aktiv kommen bei JEDER Anfrage frisch aus der
   Datenbank, nie aus dem Cookie.
3. Rolle `lesen` sieht alles und schreibt nichts; Rolle `freigeben`
   arbeitet wie vorher — und hinterlaesst ihren NAMEN in approved_by.
4. Fehlversuche werden gebremst (Sperre nach 5), auch fuer das dann
   richtige Passwort.
"""
import json
import os
import time

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads, sales_test.benutzer "
            "cascade")
    yield


@pytest.fixture
def scharf():
    """Anmeldung fuer die Dauer eines Tests scharf schalten; die Bremse
    startet leer und wird zurueckgelassen, wie sie vorgefunden wurde."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _client():
    # Eigener Client je Test: die Sitzung lebt im Cookie-Glas des Clients,
    # und Tests duerfen sich keine Sitzungen teilen.
    return TestClient(ui.app)


def _benutzer(name="erika", rolle="freigeben", passwort="korrekt-pferd-9",
              aktiv=True):
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv) values "
        "(%s, %s, %s, %s) returning name",
        (name, rolle, ui._passwort_hashen(passwort), aktiv))
    return name


def _login(client, name, passwort, csrf=None):
    return client.post(
        "/login",
        data={"name": name, "passwort": passwort,
              "csrf": ui.CSRF_TOKEN if csrf is None else csrf},
        headers={"host": HOST_OK}, follow_redirects=False)


def _lead_mit_entwurf():
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "('Max Testperson', '+491701234567', 'whatsapp') returning id",
    )[0]["id"])
    draft = str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'whatsapp', '+491701234567', 'Hallo!', 'pending') "
        "returning id", (lead,))[0]["id"])
    return draft


# ---------------------------------------------------------------------------
# Uebergangszustand: ohne Secret bleibt alles wie vorher
# ---------------------------------------------------------------------------

def test_ohne_secret_bleibt_die_oberflaeche_offen():
    client = _client()
    assert client.get("/", headers={"host": HOST_OK}).status_code == 200
    seite = client.get("/login", headers={"host": HOST_OK})
    assert seite.status_code == 200
    assert "nicht scharf" in seite.text


# ---------------------------------------------------------------------------
# Scharf: zu ohne Sitzung
# ---------------------------------------------------------------------------

def test_scharf_leitet_unangemeldete_auf_login(scharf):
    client = _client()
    for pfad in ("/", "/kontakte", "/pipeline", "/whatsapp"):
        antwort = client.get(pfad, headers={"host": HOST_OK},
                             follow_redirects=False)
        assert antwort.status_code == 303, pfad
        assert antwort.headers["location"] == "/login"


def test_scharf_lehnt_unangemeldete_posts_ab(scharf):
    draft = _lead_mit_entwurf()
    antwort = _client().post(
        "/aktion/freigeben", data={"draft_id": draft, "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 403
    zeile = server._q("select status from drafts where id = %s", (draft,))[0]
    assert zeile["status"] == "pending"


def test_die_login_seite_selbst_bleibt_offen(scharf):
    antwort = _client().get("/login", headers={"host": HOST_OK})
    assert antwort.status_code == 200
    assert 'name="passwort"' in antwort.text


# ---------------------------------------------------------------------------
# Anmelden: richtig, falsch, gebremst
# ---------------------------------------------------------------------------

def test_richtiges_passwort_oeffnet_eine_sitzung(scharf):
    _benutzer()
    client = _client()
    antwort = _login(client, "erika", "korrekt-pferd-9")
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/"
    assert ui.SITZUNG_COOKIE in client.cookies
    assert client.get("/", headers={"host": HOST_OK}).status_code == 200


def test_falsches_passwort_oeffnet_nichts(scharf):
    _benutzer()
    client = _client()
    antwort = _login(client, "erika", "falsch")
    assert antwort.status_code == 200
    assert "fehlgeschlagen" in antwort.text
    assert ui.SITZUNG_COOKIE not in client.cookies


def test_unbekannter_name_klingt_wie_falsches_passwort(scharf):
    client = _client()
    antwort = _login(client, "niemand", "egal")
    assert antwort.status_code == 200
    assert "fehlgeschlagen" in antwort.text


def test_login_ohne_csrf_marke_wird_abgelehnt(scharf):
    _benutzer()
    client = _client()
    antwort = _login(client, "erika", "korrekt-pferd-9", csrf="gefaelscht")
    assert antwort.status_code == 400
    assert ui.SITZUNG_COOKIE not in client.cookies


def test_fuenf_fehlversuche_bremsen_auch_das_richtige_passwort(scharf):
    _benutzer()
    client = _client()
    for _ in range(5):
        assert _login(client, "erika", "falsch").status_code == 200
    gebremst = _login(client, "erika", "korrekt-pferd-9")
    assert gebremst.status_code == 429
    assert ui.SITZUNG_COOKIE not in client.cookies


def test_erfolg_setzt_die_bremse_zurueck(scharf):
    _benutzer()
    client = _client()
    for _ in range(3):
        _login(client, "erika", "falsch")
    assert _login(client, "erika", "korrekt-pferd-9").status_code == 303
    assert ui.ANMELDE_BREMSE["fehler"] == 0


def test_inaktiver_benutzer_kommt_nicht_rein(scharf):
    _benutzer(aktiv=False)
    antwort = _login(_client(), "erika", "korrekt-pferd-9")
    assert antwort.status_code == 200
    assert "fehlgeschlagen" in antwort.text


# ---------------------------------------------------------------------------
# Die Sitzung: signiert, endlich, widerruflich
# ---------------------------------------------------------------------------

def test_gefaelschte_signatur_zaehlt_nicht(scharf):
    _benutzer()
    client = _client()
    _login(client, "erika", "korrekt-pferd-9")
    wert = client.cookies[ui.SITZUNG_COOKIE]
    letztes = "0" if wert[-1] != "0" else "1"
    # Frisches Cookie-Glas: httpx behielte sonst den ECHTEN Cookie neben
    # der Faelschung, und der Server saehe weiter die gueltige Sitzung.
    faelscher = _client()
    faelscher.cookies.set(ui.SITZUNG_COOKIE, wert[:-1] + letztes)
    antwort = faelscher.get("/", headers={"host": HOST_OK},
                            follow_redirects=False)
    assert antwort.status_code == 303


def test_abgelaufene_sitzung_zaehlt_nicht(scharf):
    _benutzer()
    client = _client()
    client.cookies.set(ui.SITZUNG_COOKIE,
                       ui._sitzung_bauen("erika", time.time() - 60))
    antwort = client.get("/", headers={"host": HOST_OK},
                         follow_redirects=False)
    assert antwort.status_code == 303


def test_deaktivierung_beendet_laufende_sitzungen(scharf):
    """Rolle und aktiv kommen pro Anfrage aus der Datenbank — wer
    deaktiviert wird, ist SOFORT draussen, nicht erst beim Cookie-Ablauf."""
    _benutzer()
    client = _client()
    _login(client, "erika", "korrekt-pferd-9")
    server._q("update benutzer set aktiv = false where name = 'erika' "
              "returning name")
    antwort = client.get("/", headers={"host": HOST_OK},
                         follow_redirects=False)
    assert antwort.status_code == 303


def test_logout_beendet_die_sitzung(scharf):
    _benutzer()
    client = _client()
    _login(client, "erika", "korrekt-pferd-9")
    antwort = client.post("/logout", data={"csrf": ui.CSRF_TOKEN},
                          headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    antwort = client.get("/", headers={"host": HOST_OK},
                         follow_redirects=False)
    assert antwort.status_code == 303


# ---------------------------------------------------------------------------
# Rollen: lesen sieht, freigeben schreibt — mit Namen im Beweis
# ---------------------------------------------------------------------------

def test_rolle_lesen_sieht_alles_und_schreibt_nichts(scharf):
    _benutzer(name="ludwig", rolle="lesen", passwort="nur-gucken-7")
    draft = _lead_mit_entwurf()
    client = _client()
    _login(client, "ludwig", "nur-gucken-7")
    assert client.get("/kontakte",
                      headers={"host": HOST_OK}).status_code == 200
    antwort = client.post(
        "/aktion/freigeben", data={"draft_id": draft, "csrf": ui.CSRF_TOKEN},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 403
    zeile = server._q("select status from drafts where id = %s", (draft,))[0]
    assert zeile["status"] == "pending"


def test_rolle_freigeben_hinterlaesst_ihren_namen(scharf):
    _benutzer(name="erika", rolle="freigeben")
    draft = _lead_mit_entwurf()
    client = _client()
    _login(client, "erika", "korrekt-pferd-9")
    antwort = client.post(
        "/aktion/freigeben",
        data={"draft_id": draft, "csrf": ui.CSRF_TOKEN,
              "stand": ui._text_stand("Hallo!")},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    zeile = server._q("select status, approved_by from drafts where id = %s",
                      (draft,))[0]
    assert zeile["status"] == "approved"
    assert zeile["approved_by"] == "erika"


def test_ohne_anmeldung_bleibt_der_alte_stempel():
    """Uebergangszustand: solange die Anmeldung nicht scharf ist, traegt
    die UI-Freigabe weiter 'betreiber-ui' — der Audit-Unterschied zur
    Chat-Freigabe bleibt erhalten."""
    draft = _lead_mit_entwurf()
    antwort = _client().post(
        "/aktion/freigeben",
        data={"draft_id": draft, "csrf": ui.CSRF_TOKEN,
              "stand": ui._text_stand("Hallo!")},
        headers={"host": HOST_OK}, follow_redirects=False)
    assert antwort.status_code == 303
    zeile = server._q("select approved_by from drafts where id = %s",
                      (draft,))[0]
    assert zeile["approved_by"] == "betreiber-ui"


# ---------------------------------------------------------------------------
# Passwort-Handwerk
# ---------------------------------------------------------------------------

def test_hash_ist_gesalzen_und_pruefbar():
    a = ui._passwort_hashen("geheim")
    b = ui._passwort_hashen("geheim")
    assert a != b                      # Salz — gleiche Passwoerter, andere Hashes
    assert a.startswith("scrypt$")
    assert ui._passwort_pruefen("geheim", a)
    assert ui._passwort_pruefen("geheim", b)
    assert not ui._passwort_pruefen("falsch", a)


def test_kaputter_hash_prueft_still_auf_falsch():
    assert not ui._passwort_pruefen("egal", "kein-echter-hash")
    assert not ui._passwort_pruefen("egal", "")


# ---------------------------------------------------------------------------
# Der Menschen-Schritt: benutzer_anlegen (deploy/benutzer-anlegen.sh)
# ---------------------------------------------------------------------------

def test_benutzer_anlegen_legt_an():
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen("erika", "freigeben", "korrekt-pferd-9")
    assert meldung.startswith("OK")
    zeile = server._q("select rolle, aktiv from benutzer "
                      "where name = 'erika'")[0]
    assert zeile["rolle"] == "freigeben" and zeile["aktiv"] is True


def test_benutzer_anlegen_ist_auch_der_reset():
    """Gleicher Name = Passwort-Reset, Rollenwechsel und Reaktivierung in
    einem — es gibt keinen zweiten Weg, den man falsch gehen koennte."""
    import benutzer_anlegen
    benutzer_anlegen.anlegen("erika", "freigeben", "altes-passwort-1")
    server._q("update benutzer set aktiv = false where name = 'erika' "
              "returning name")
    meldung = benutzer_anlegen.anlegen("erika", "lesen", "neues-passwort-2")
    assert meldung.startswith("OK")
    zeile = server._q("select rolle, aktiv, passwort_hash from benutzer "
                      "where name = 'erika'")[0]
    assert zeile["rolle"] == "lesen" and zeile["aktiv"] is True
    assert ui._passwort_pruefen("neues-passwort-2", zeile["passwort_hash"])
    assert not ui._passwort_pruefen("altes-passwort-1", zeile["passwort_hash"])


@pytest.mark.parametrize("name,rolle,passwort", [
    ("", "lesen", "lang-genug-123"),
    ("mit|strich", "lesen", "lang-genug-123"),
    ("mit:punkt", "lesen", "lang-genug-123"),
    ("erika", "chef", "lang-genug-123"),
    ("erika", "lesen", "kurz"),
])
def test_benutzer_anlegen_lehnt_kaputtes_ab(name, rolle, passwort):
    import benutzer_anlegen
    meldung = benutzer_anlegen.anlegen(name, rolle, passwort)
    assert meldung.startswith("FEHLER")
    assert server._q("select count(*) n from benutzer")[0]["n"] == 0
