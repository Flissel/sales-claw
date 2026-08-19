"""Vertragstests des Support-Posteingangs (Stufe 8) gegen sales_test.

`posteingang` ist eine reine Lese-Sicht: es versendet nichts, beantwortet
nichts und fasst keinen `drafts`-Satz an. Getestet wird deshalb vor allem die
ABGRENZUNG — was gilt als beantwortet (zwei Wege: `versand` vom Dispatcher und
`nachricht_ausgehend` aus dem Eingang), was faellt aus dem Fenster, und wie
werden die Unbekannten am Sammelkontakt auseinandergehalten, die sich EINEN
Lead teilen.
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
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    # Wie inbox.py: die UUID kommt aus der Umgebung, der Test biegt das
    # Modulattribut um (gleiches Muster wie LINKEDIN_POST_LEAD_ID).
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = ""
    yield
    server.UNBEKANNT_LEAD_ID = vorher


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _sammel():
    lead = str(server._q(
        "insert into leads (name, source) values "
        "('Unbekannte Eingaenge', 'system') returning id")[0]["id"])
    server.UNBEKANNT_LEAD_ID = lead
    return lead


def _kundenantwort(lead, vor_stunden=1, text="Passt Donnerstag?",
                   absender="491701234567@c.us"):
    return str(server._q(
        "insert into activities (lead_id, type, payload, actor, created_at) "
        "values (%s, 'kundenantwort', %s, 'human', "
        "        now() - (%s * interval '1 hour')) returning id",
        (lead, json.dumps({"text": text, "richtung": "eingehend",
                           "absender": absender, "message_id": f"wa-{text[:8]}"}),
         vor_stunden))[0]["id"])


def _antwort(lead, typ="nachricht_ausgehend", vor_stunden=0, **nutzlast):
    return str(server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "values (%s, %s, %s, now() - (%s * interval '1 hour')) returning id",
        (lead, typ, json.dumps(nutzlast), vor_stunden))[0]["id"])


def _posteingang(**kw):
    return json.loads(server.posteingang(**kw))


# ---------------------------------------------------------------------------
# Grundfall
# ---------------------------------------------------------------------------

def test_unbeantwortete_kundenantwort_steht_im_posteingang():
    lead = _lead()
    _kundenantwort(lead, vor_stunden=5)
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    eintrag = p["eintraege"][0]
    assert str(eintrag["lead_id"]) == lead
    assert eintrag["kontakt"] == "Max Testperson"
    assert eintrag["text_kurz"] == "Passt Donnerstag?"
    assert 4.9 < eintrag["wartet_stunden"] < 5.1
    # Bei einem echten Kontakt sagt der Name mehr als die Nummer.
    assert "absender" not in eintrag


def test_leerer_posteingang_ist_kein_fehler():
    p = _posteingang()
    assert p == {"fenster_stunden": 48, "anzahl_unbeantwortet": 0,
                 "angezeigt": 0, "eintraege": []}


def test_nur_die_juengste_nachricht_je_kontakt_steht_da():
    """Wer dreimal schreibt, wartet einmal — nicht dreimal."""
    lead = _lead()
    _kundenantwort(lead, vor_stunden=9, text="Hallo?")
    _kundenantwort(lead, vor_stunden=5, text="Immer noch da?")
    _kundenantwort(lead, vor_stunden=2, text="Melden Sie sich bitte")
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert p["eintraege"][0]["text_kurz"] == "Melden Sie sich bitte"


# ---------------------------------------------------------------------------
# Beantwortet — die beiden Wege
# ---------------------------------------------------------------------------

def test_versand_des_dispatchers_beendet_das_warten():
    lead = _lead()
    _kundenantwort(lead, vor_stunden=5)
    _antwort(lead, typ="versand", vor_stunden=1, draft_id="d-1",
             kanal="whatsapp", weg="dispatcher", chat_id="491701234567@c.us")
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_eigene_nachricht_vom_handy_beendet_das_warten():
    """Der zweite Weg, und der Grund fuer E1: ohne `nachricht_ausgehend`
    bliebe ein von Hand beantworteter Kontakt ewig unbeantwortet."""
    lead = _lead()
    _kundenantwort(lead, vor_stunden=5)
    _antwort(lead, vor_stunden=1, richtung="ausgehend",
             empfaenger="491701234567@c.us")
    assert _posteingang()["anzahl_unbeantwortet"] == 0


def test_antwort_vor_der_frage_zaehlt_nicht():
    """Die Reihenfolge ist der ganze Punkt: eine Antwort von gestern beantwortet
    die Nachricht von heute nicht."""
    lead = _lead()
    _antwort(lead, vor_stunden=9, richtung="ausgehend",
             empfaenger="491701234567@c.us")
    _kundenantwort(lead, vor_stunden=5)
    assert _posteingang()["anzahl_unbeantwortet"] == 1


def test_andere_aktivitaeten_beenden_das_warten_nicht():
    """Eine Notiz oder eine Freigabe ist keine Antwort an den Kunden."""
    lead = _lead()
    _kundenantwort(lead, vor_stunden=5)
    _antwort(lead, typ="nachricht", vor_stunden=1, inhalt="mit Kundin telefoniert")
    _antwort(lead, typ="freigabe", vor_stunden=1, draft_id="d-1")
    assert _posteingang()["anzahl_unbeantwortet"] == 1


# ---------------------------------------------------------------------------
# Sammelkontakt: mehrere Unbekannte teilen sich EINEN Lead
# ---------------------------------------------------------------------------

def test_am_sammelkontakt_zaehlt_jede_absendernummer_einzeln():
    sammel = _sammel()
    _kundenantwort(sammel, vor_stunden=9, text="Erste Unbekannte",
                   absender="4915199999991@c.us")
    _kundenantwort(sammel, vor_stunden=3, text="Zweiter Unbekannter",
                   absender="4915199999992@c.us")
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 2
    # Aelteste zuerst — wer am laengsten wartet, steht oben.
    assert [e["absender"] for e in p["eintraege"]] == ["4915199999991@c.us",
                                                       "4915199999992@c.us"]
    assert "kontakt_anlegen" in p["hinweis"]


def test_antwort_an_einen_unbekannten_laesst_den_anderen_stehen():
    """Ohne die Absenderpruefung wuerde EINE Antwort alle Unbekannten als
    beantwortet gelten lassen — und das Postfach loeschte sich selbst."""
    sammel = _sammel()
    _kundenantwort(sammel, vor_stunden=9, text="Erste Unbekannte",
                   absender="4915199999991@c.us")
    _kundenantwort(sammel, vor_stunden=3, text="Zweiter Unbekannter",
                   absender="4915199999992@c.us")
    _antwort(sammel, vor_stunden=1, richtung="ausgehend",
             empfaenger="4915199999991@c.us")
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert p["eintraege"][0]["absender"] == "4915199999992@c.us"


def test_ohne_gesetzten_sammelkontakt_bleibt_die_sicht_lesbar():
    """Ist INBOX_UNBEKANNT_LEAD_ID nicht gesetzt, kann nicht nach Nummer
    getrennt werden — die Zeilen fallen dann zu einem Eintrag zusammen, statt
    dass das Werkzeug ausfaellt."""
    sammel = _sammel()
    server.UNBEKANNT_LEAD_ID = ""
    _kundenantwort(sammel, vor_stunden=9, absender="4915199999991@c.us")
    _kundenantwort(sammel, vor_stunden=3, absender="4915199999992@c.us")
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 1
    assert "absender" not in p["eintraege"][0]


# ---------------------------------------------------------------------------
# Fenster, Reihenfolge, Deckelung
# ---------------------------------------------------------------------------

def test_was_aus_dem_fenster_faellt_steht_nicht_da():
    lead = _lead()
    _kundenantwort(lead, vor_stunden=60)
    assert _posteingang()["anzahl_unbeantwortet"] == 0
    assert _posteingang(stunden=72)["anzahl_unbeantwortet"] == 1


@pytest.mark.parametrize("gefragt, erwartet", [
    (0, 1), (-5, 1), (1, 1), (48, 48), (168, 168), (500, 168),
])
def test_fenster_wird_gekappt_statt_abgelehnt(gefragt, erwartet):
    assert _posteingang(stunden=gefragt)["fenster_stunden"] == erwartet


def test_unlesbare_stundenangabe_faellt_auf_die_vorgabe_zurueck():
    assert _posteingang(stunden="viele")["fenster_stunden"] == 48


def test_aelteste_zuerst():
    a = _lead("Alt Wartend", "+491701111111")
    b = _lead("Frisch Wartend", "+491702222222")
    _kundenantwort(b, vor_stunden=2, absender="491702222222@c.us")
    _kundenantwort(a, vor_stunden=20, absender="491701111111@c.us")
    p = _posteingang()
    assert [e["kontakt"] for e in p["eintraege"]] == ["Alt Wartend",
                                                      "Frisch Wartend"]


def test_gesamtzahl_steht_neben_der_gedeckelten_liste():
    sammel = _sammel()
    for i in range(30):
        _kundenantwort(sammel, vor_stunden=30 - i, text=f"Nachricht {i:02d}",
                       absender=f"49151999{i:05d}@c.us")
    p = _posteingang()
    assert p["anzahl_unbeantwortet"] == 30
    assert p["angezeigt"] == server.POSTEINGANG_LIMIT == 25
    assert len(p["eintraege"]) == 25


def test_langer_text_wird_gekuerzt():
    lead = _lead()
    _kundenantwort(lead, text="x" * 500)
    kurz = _posteingang()["eintraege"][0]["text_kurz"]
    assert len(kurz) == server.POSTEINGANG_TEXT_MAX + 1
    assert kurz.endswith("…")


# ---------------------------------------------------------------------------
# Digest-Block (E3)
# ---------------------------------------------------------------------------

def test_digest_nennt_die_unbeantworteten_eingaenge():
    lead = _lead()
    _kundenantwort(lead, vor_stunden=6)
    d = json.loads(server.digest())
    block = d["unbeantwortete_eingaenge"]
    assert block["anzahl"] == 1
    assert block["eintraege"][0]["kontakt"] == "Max Testperson"
    assert 5.9 < block["eintraege"][0]["wartet_stunden"] < 6.1
    # Die bestehenden Digest-Zusagen bleiben unberuehrt.
    assert "faellige_wiedervorlagen" in d and "letzte_aktivitaeten" in d


def test_digest_zeigt_hoechstens_fuenf_eintraege_nennt_aber_alle():
    """Der Digest ist eine Ansage, keine Liste — die ganze Sicht zeigt
    `posteingang`."""
    sammel = _sammel()
    for i in range(8):
        _kundenantwort(sammel, vor_stunden=8 - i, text=f"Nachricht {i}",
                       absender=f"49151999{i:05d}@c.us")
    block = json.loads(server.digest())["unbeantwortete_eingaenge"]
    assert block["anzahl"] == 8
    assert len(block["eintraege"]) == 5
    assert all("absender" in e for e in block["eintraege"])


# ---------------------------------------------------------------------------
# Registrierung
# ---------------------------------------------------------------------------

def test_signatur_ueberlebt_den_dekorator_und_werkzeug_ist_registriert():
    import inspect
    parameter = inspect.signature(server.posteingang).parameters
    assert list(parameter) == ["stunden"]
    assert parameter["stunden"].default == 48
    assert server.posteingang in server.WERKZEUGE
