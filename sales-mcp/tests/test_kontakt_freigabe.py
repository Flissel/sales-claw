"""Vertragstests der Kontakt-Freigabe fuer WhatsApp (OpenClaw).

Das Gate VOR dem Nachrichten-Gate: ohne ausdrueckliche Freigabe des
Betreibers (kontakt_freigeben) entsteht kein WhatsApp-Entwurf, und der
Dispatcher stellt nichts zu — auch nicht, wenn die Nachricht selbst laengst
freigegeben war (Entzug zwischen Freigabe und Zustellung). E-Mail und
LinkedIn kennen dieses Gate nicht.

Wie test_werkzeuge.py: die Suite darf NIE gegen `sales` laufen.
"""
import json
import os

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen. Der
# Schutz muss konstruktiv sein, nicht von der Disziplin des Aufrufers abhaengen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import dispatch  # noqa: E402  — liest SALES_DB_SCHEMA ueber server beim Import
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein."""
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


def _anlegen(name="Max Testperson", phone="+491701234567", email=""):
    """Roher Kontakt ueber das Werkzeug — OHNE Kontakt-Freigabe. Genau so
    entsteht jeder Kontakt im Betrieb; das Gate ist von Anfang an zu."""
    return json.loads(server.kontakt_anlegen(
        name=name, phone=phone, email=email))["lead_id"]


def _entwurf_sql(lead_id, status="approved", recipient="+491701234567"):
    """Freigegebener WhatsApp-Entwurf direkt per SQL — vorbei am fruehen
    Gate in entwurf_erstellen, damit die Dispatcher-Pruefung isoliert
    testbar ist (Entzug NACH der Nachrichten-Freigabe)."""
    return server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, "
        "approved_by, approved_at) values (%s, 'whatsapp', %s, 'Hallo!', %s, "
        "'betreiber', now()) returning id",
        (lead_id, recipient, status))[0]["id"]


def _draft_zeile(draft_id):
    return server._q("select status, error from drafts where id = %s",
                     (draft_id,))[0]


def _aktivitaeten(lead_id, typ):
    return server._q(
        "select payload from activities where lead_id = %s and type = %s "
        "order by created_at", (lead_id, typ))


# ---------------------------------------------------------------------------
# Gate in entwurf_erstellen
# ---------------------------------------------------------------------------

def test_whatsapp_entwurf_ohne_freigabe_wird_abgelehnt():
    """Der Kern der Stufe: ein frisch angelegter Kontakt bekommt KEINEN
    WhatsApp-Entwurf, solange der Betreiber ihn nicht freigegeben hat."""
    lead = _anlegen()
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert "fehler" in antwort
    assert "kontakt_freigeben" in antwort["fehler"]
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0


def test_email_und_linkedin_bleiben_ohne_freigabe_offen():
    """Das Gate gilt NUR fuer WhatsApp — die anderen Kanaele sind nicht
    betroffen (E-Mail hat sein eigenes Nachrichten-Gate, LinkedIn den
    Handversand)."""
    lead = _anlegen(email="max@example.com")
    mail = json.loads(server.entwurf_erstellen(lead, "email", "Text"))
    li = json.loads(server.entwurf_erstellen(lead, "linkedin", "Text"))
    assert "fehler" not in mail and "fehler" not in li


def test_kontakt_freigeben_oeffnet_das_gate():
    lead = _anlegen()
    ok = json.loads(server.kontakt_freigeben(lead))
    assert ok["whatsapp_freigabe"] is True and ok["lead_id"] == lead
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert "fehler" not in antwort
    assert antwort["status"] == "pending"


def test_freigabe_entziehen_schliesst_das_gate_wieder():
    lead = _anlegen()
    server.kontakt_freigeben(lead)
    ok = json.loads(server.kontakt_freigabe_entziehen(lead))
    assert ok["whatsapp_freigabe"] is False
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert "fehler" in antwort


def test_unbekannte_lead_id_gibt_fehlertext():
    kaputt = "00000000-0000-0000-0000-000000000000"
    assert "fehler" in json.loads(server.kontakt_freigeben(kaputt))
    assert "fehler" in json.loads(server.kontakt_freigabe_entziehen(kaputt))


def test_freigabe_und_entzug_werden_protokolliert():
    lead = _anlegen()
    server.kontakt_freigeben(lead)
    server.kontakt_freigabe_entziehen(lead)
    payloads = [a["payload"] for a in _aktivitaeten(lead, "kontakt_freigabe")]
    assert payloads == [{"kanal": "whatsapp", "freigegeben": True},
                       {"kanal": "whatsapp", "freigegeben": False}]


def test_freigeben_ist_idempotent():
    lead = _anlegen()
    server.kontakt_freigeben(lead)
    ok = json.loads(server.kontakt_freigeben(lead))
    assert ok["whatsapp_freigabe"] is True


def test_freigabe_und_entzug_nennen_den_allowlist_sync():
    """Auto-Betrieb haengt an der Allowlist im OpenClaw-Volume — beide
    Werkzeuge muessen den Betreiber auf den Sync hinweisen (der Agent gibt
    den hinweis woertlich weiter). Beim Entzug ist der Hinweis
    sicherheitsrelevant: bis zum Sync hoert der Agent weiter mit."""
    lead = _anlegen()
    frei = json.loads(server.kontakt_freigeben(lead))
    assert frei["hinweis"] == server.FREIGABE_HINWEIS
    assert "sync-allowlist.ps1" in frei["hinweis"]
    entzug = json.loads(server.kontakt_freigabe_entziehen(lead))
    assert entzug["hinweis"] == server.ENTZUG_HINWEIS
    assert "WEITER" in entzug["hinweis"]


# ---------------------------------------------------------------------------
# kontakte_freigegeben — der Sollzustand, den sync-allowlist.ps1 uebertraegt
# ---------------------------------------------------------------------------

def test_kontakte_freigegeben_listet_nur_freigegebene_mit_zielnummer():
    """Die Liste ist der Sollzustand der Allowlist: nur freigegebene
    Kontakte, je mit der Nummer in E.164 — derselben Normalisierung, mit
    der auch zugestellt wird (0049 -> +49)."""
    frei = _anlegen(name="Frei Gegeben", phone="00491701234567")
    server.kontakt_freigeben(frei)
    _anlegen(name="Nicht Frei", phone="+491702222222")
    entzogen = _anlegen(name="Wieder Entzogen", phone="+491703333333")
    server.kontakt_freigeben(entzogen)
    server.kontakt_freigabe_entziehen(entzogen)

    liste = json.loads(server.kontakte_freigegeben())
    assert liste["anzahl"] == 1
    eintrag = liste["kontakte"][0]
    assert eintrag["lead_id"] == frei
    assert eintrag["nummer"] == "+491701234567"
    assert "hinweis" not in eintrag
    assert "sync-allowlist.ps1" in liste["hinweis"]


def test_kontakte_freigegeben_nennt_unzustellbare_nummern():
    """Ein freigegebener Kontakt ohne zustellbare Nummer kann nicht in die
    Allowlist — die Liste sagt es, statt ihn stumm wegzulassen."""
    ohne = _anlegen(name="Ohne Nummer", phone="")
    server.kontakt_freigeben(ohne)
    national = _anlegen(name="Nationale Nummer", phone="01704444444")
    server.kontakt_freigeben(national)

    liste = json.loads(server.kontakte_freigegeben())
    assert liste["anzahl"] == 2
    for eintrag in liste["kontakte"]:
        assert eintrag["nummer"] is None
        assert "Allowlist" in eintrag["hinweis"]


def test_kontakte_freigegeben_leer_ohne_freigaben():
    _anlegen()
    liste = json.loads(server.kontakte_freigegeben())
    assert liste["anzahl"] == 0 and liste["kontakte"] == []


def test_freigabe_ueberschreibt_kein_anderes_enrichment():
    """jsonb_set darf nur den eigenen Schluessel anfassen — Profil, Bedarf
    und Bestand bleiben stehen."""
    lead = _anlegen()
    server.profil_aktualisieren(lead, "beruf", "Lehrerin")
    server.kontakt_freigeben(lead)
    profil = json.loads(server.profil_lesen(lead))
    assert profil["profil"]["beruf"] == "Lehrerin"
    assert profil["whatsapp_freigabe"] is True


# ---------------------------------------------------------------------------
# Nur der Betreiber-Weg setzt die Freigabe
# ---------------------------------------------------------------------------

def test_profil_aktualisieren_kann_die_freigabe_nicht_setzen():
    """profil_aktualisieren schreibt unter enrichment->profil — ein dort
    abgelegtes 'whatsapp_freigabe' oeffnet das Gate NICHT. Eine Freigabe,
    die das Modell per Freitext setzen koennte, waere keine."""
    lead = _anlegen()
    server.profil_aktualisieren(lead, "whatsapp_freigabe", "ja")
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert "fehler" in antwort


@pytest.mark.parametrize("kaputt", [
    "true",                                  # String statt Objekt
    "{\"freigegeben\": \"ja\"}",             # String statt Boolean
    "{\"at\": \"2026-08-19\"}",              # Objekt ohne freigegeben
    "[]",                                    # falscher Typ
])
def test_kaputter_wert_zaehlt_als_nicht_freigegeben(kaputt):
    """Fail-closed: nur ein echtes {"freigegeben": true} oeffnet das Gate."""
    lead = _anlegen()
    server._q("update leads set enrichment = jsonb_set(enrichment, "
              "'{whatsapp_freigabe}', %s::jsonb, true) where id = %s "
              "returning id", (kaputt, lead))
    antwort = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo!"))
    assert "fehler" in antwort


# ---------------------------------------------------------------------------
# Anzeige — der Betreiber muss den Stand sehen, wo er entscheidet
# ---------------------------------------------------------------------------

def test_profil_und_suche_zeigen_die_freigabe():
    lead = _anlegen()
    assert json.loads(server.profil_lesen(lead))["whatsapp_freigabe"] is False
    treffer = json.loads(server.kontakt_suchen("Testperson"))["kontakte"][0]
    assert treffer["whatsapp_freigabe"] is False
    server.kontakt_freigeben(lead)
    assert json.loads(server.profil_lesen(lead))["whatsapp_freigabe"] is True
    treffer = json.loads(server.kontakt_suchen("Testperson"))["kontakte"][0]
    assert treffer["whatsapp_freigabe"] is True


def test_entwuerfe_offen_zeigt_die_freigabe_nur_bei_whatsapp():
    """WhatsApp-Eintraege tragen true/false; E-Mail und LinkedIn null — ein
    false dort waere eine falsche Warnung."""
    lead = _anlegen(email="max@example.com")
    server.kontakt_freigeben(lead)
    server.entwurf_erstellen(lead, "whatsapp", "Text WA")
    server.entwurf_erstellen(lead, "email", "Text Mail")
    eintraege = {e["kanal"]: e
                 for e in json.loads(server.entwuerfe_offen())["entwuerfe"]}
    assert eintraege["whatsapp"]["whatsapp_freigabe"] is True
    assert eintraege["email"]["whatsapp_freigabe"] is None

    server.kontakt_freigabe_entziehen(lead)
    eintraege = {e["kanal"]: e
                 for e in json.loads(server.entwuerfe_offen())["entwuerfe"]}
    assert eintraege["whatsapp"]["whatsapp_freigabe"] is False


def test_entwuerfe_offen_zeigt_die_freigabe_im_fehlgeschlagen_block():
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    dispatch.verarbeite_draft(draft)        # faellt am Gate, wird failed
    block = json.loads(server.entwuerfe_offen())["fehlgeschlagen"]
    assert block[0]["whatsapp_freigabe"] is False


# ---------------------------------------------------------------------------
# Dispatcher — das harte Gate vor jedem Netzkontakt
# ---------------------------------------------------------------------------

def _sende_verbieten(monkeypatch):
    def _nie(*_a, **_k):
        pytest.fail("OpenWA wurde angesprochen, obwohl die Kontakt-Freigabe "
                    "fehlt — das Gate haette VOR dem Netz greifen muessen.")
    monkeypatch.setattr(dispatch, "sende_text", _nie)
    monkeypatch.setattr(dispatch, "sende_medium", _nie)


def test_dispatcher_stoppt_kontakt_ohne_freigabe(monkeypatch):
    """Bestandskontakt ohne Freigabe-Schluessel: die Nachricht war
    freigegeben, der Kontakt nie — nichts geht raus."""
    _sende_verbieten(monkeypatch)
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    assert dispatch.verarbeite_draft(draft) == "kontakt_nicht_freigegeben"
    zeile = _draft_zeile(draft)
    assert zeile["status"] == "failed"
    assert "kontakt_freigeben" in zeile["error"]


def test_dispatcher_stoppt_entzug_nach_der_nachrichten_freigabe(monkeypatch):
    """Der Grund fuer die zweite Pruefung: zwischen Nachrichten-Freigabe und
    Zustellung liegen Minuten — ein Entzug dazwischen muss noch greifen."""
    _sende_verbieten(monkeypatch)
    lead = _anlegen()
    server.kontakt_freigeben(lead)
    draft = _entwurf_sql(lead)
    server.kontakt_freigabe_entziehen(lead)
    assert dispatch.verarbeite_draft(draft) == "kontakt_nicht_freigegeben"
    assert _draft_zeile(draft)["status"] == "failed"


def test_dispatcher_stoppt_entwurf_ohne_kontakt(monkeypatch):
    """Fail-closed: lead_id null (Kontakt geloescht) — niemand koennte die
    Freigabe erteilt haben, also wird nicht zugestellt."""
    _sende_verbieten(monkeypatch)
    draft = _entwurf_sql(None)
    assert dispatch.verarbeite_draft(draft) == "kontakt_nicht_freigegeben"
    zeile = _draft_zeile(draft)
    assert zeile["status"] == "failed"
    assert "ohne Kontakt" in zeile["error"]


def test_dispatcher_stellt_freigegebenen_kontakt_zu(monkeypatch):
    """Der bestellte Weg: Kontakt freigegeben, Nachricht freigegeben —
    zugestellt und als sent gebucht."""
    gesendet = []
    monkeypatch.setattr(dispatch, "sende_text",
                        lambda chat_id, text: gesendet.append((chat_id, text)))
    lead = _anlegen()
    server.kontakt_freigeben(lead)
    draft = _entwurf_sql(lead)
    assert dispatch.verarbeite_draft(draft) == "gesendet"
    assert gesendet == [("491701234567@c.us", "Hallo!")]
    assert _draft_zeile(draft)["status"] == "sent"


def test_der_ganze_weg_nach_nachtraeglicher_freigabe(monkeypatch):
    """Ende-zu-Ende: am Gate gescheitert -> Betreiber gibt den KONTAKT frei
    -> Betreiber gibt den Entwurf ERNEUT frei -> naechste Runde stellt zu."""
    gesendet = []
    monkeypatch.setattr(dispatch, "sende_text",
                        lambda chat_id, text: gesendet.append(chat_id))
    lead = _anlegen()
    draft = _entwurf_sql(lead)
    assert dispatch.verarbeite_draft(draft) == "kontakt_nicht_freigegeben"

    server.kontakt_freigeben(lead)
    erneut = json.loads(server.entwurf_erneut_freigeben(str(draft)))
    assert erneut["status"] == "approved"
    assert dispatch.verarbeite_draft(draft) == "gesendet"
    assert gesendet == ["491701234567@c.us"]
