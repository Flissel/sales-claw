"""Vertragstests fuer das strukturierte Kontaktprofil.

Betreiber-Wunsch vom 22.08.2026, woertlich:

  „wir wollen noch die Nachrichten pro kontakt mit einen automatisch
   generierten Profil ueber die Nachrichten / links pdfs dateien / es soll
   wer ist der Mensch / in welcher beziehung stehe ich zu ihn / was ist
   wichtig fuer den Mensch / was ist aktuell grad los … das soll alle 50
   Nachrichten aktuellisiert werden."

Die Saetze, die diese Suite festnagelt:

1. **Vier Leitfragen, alle vier oder keine.** Ein Profil mit drei
   beantworteten Fragen und einer leeren Stelle saehe in der Anzeige aus wie
   ein vollstaendiges — und niemand wuesste, ob die vierte unbeantwortbar
   war oder vergessen wurde.
2. **Kein zweites System.** Das Profil ist Teil des Chat-Reports: derselbe
   Ausloeser (50 Nachrichten), dieselbe Grenze, dieselbe Faelligkeitsliste.
   Ein eigener Zaehler waere eine zweite Wahrheit darueber, was schon
   verarbeitet ist.
3. **Append-only, also versioniert.** Jede Fassung ist eine neue Zeile in
   `activities`. Die vorige bleibt lesbar — das ist die Historie, die ein
   „alle 50 Nachrichten aktualisiert" ueberhaupt erst sinnvoll macht.
4. **Getrennt von dem, was ein Mensch bestaetigt hat.** `enrichment->profil`
   (profil_aktualisieren) bleibt unberuehrt. Was ein Modell aus dem Verlauf
   schliesst, ueberschreibt nicht, was ein Mensch gesetzt hat.
"""
import json
import os

import pytest

# HART, nicht setdefault (wie ueberall in dieser Suite).
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


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _nachrichten(lead, anzahl, typ="kundenantwort", ab_minute=1000):
    return [str(z["id"]) for z in server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "select %s, %s, jsonb_build_object('text', 'Nachricht ' || g), "
        "       now() - make_interval(mins => %s - g) "
        "  from generate_series(1, %s) g "
        "returning id", (lead, typ, ab_minute, anzahl))]


VOLLES_PROFIL = {
    "wer": "Selbstaendiger Handwerker, Mitte vierzig, zwei Kinder.",
    "beziehung": "Seit dem Erstgespraech im Juli in loser Verbindung.",
    "wichtig": "Verlaesslichkeit und kurze Wege; will keine Vertreterbesuche.",
    "aktuell": "Sucht eine Absicherung fuer den Betrieb, wartet auf Zahlen.",
}


def _speichern(lead, **zusatz):
    argumente = {"zusammenfassung": "Kurzer Verlauf, nichts Offenes."}
    argumente.update(zusatz)
    return json.loads(server.chat_report_speichern(lead, **argumente))


def _reports(lead):
    return server._q(
        "select payload, created_at from activities where lead_id = %s "
        "and type = %s order by created_at", (lead, server.CHAT_REPORT_TYP))


# ---------------------------------------------------------------------------
# Die vier Leitfragen
# ---------------------------------------------------------------------------

def test_die_vier_leitfragen_stehen_an_einer_stelle():
    """Sie sind eine Konstante, keine im Code verstreute Aufzaehlung."""
    assert server.PROFIL_FELDER == ("wer", "beziehung", "wichtig", "aktuell")
    assert set(server.PROFIL_FRAGEN) == set(server.PROFIL_FELDER)
    for frage in server.PROFIL_FRAGEN.values():
        assert frage.endswith("?")


def test_volles_profil_wird_gespeichert():
    lead = _lead()
    _nachrichten(lead, 3)
    antwort = _speichern(lead, **VOLLES_PROFIL)
    assert "fehler" not in antwort

    zeilen = _reports(lead)
    assert len(zeilen) == 1
    profil = zeilen[0]["payload"]["profil"]
    for feld, wert in VOLLES_PROFIL.items():
        assert profil[feld] == wert
    assert profil["links"] == []
    assert profil["dateien"] == []


@pytest.mark.parametrize("weggelassen", ["wer", "beziehung", "wichtig",
                                         "aktuell"])
def test_drei_von_vier_werden_abgelehnt(weggelassen):
    """Und zwar VOLLSTAENDIG: dann entsteht auch kein Report."""
    lead = _lead()
    _nachrichten(lead, 3)
    teil = {k: v for k, v in VOLLES_PROFIL.items() if k != weggelassen}
    antwort = _speichern(lead, **teil)
    assert "fehler" in antwort
    assert weggelassen in antwort["fehler"]
    assert _reports(lead) == []          # kein halber Report


def test_ohne_profil_bleibt_der_report_ein_report():
    """Rueckwaertsvertraeglich: die Felder sind optional."""
    lead = _lead()
    _nachrichten(lead, 3)
    antwort = _speichern(lead)
    assert "fehler" not in antwort
    zeilen = _reports(lead)
    assert len(zeilen) == 1
    assert "profil" not in zeilen[0]["payload"]


def test_zu_langer_abschnitt_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 3)
    zu_lang = dict(VOLLES_PROFIL)
    zu_lang["wer"] = "x" * (server.PROFIL_FELD_MAXLAENGE + 1)
    antwort = _speichern(lead, **zu_lang)
    assert "fehler" in antwort
    assert "wer" in antwort["fehler"]
    assert _reports(lead) == []


# ---------------------------------------------------------------------------
# Links und Dateien
# ---------------------------------------------------------------------------

def test_links_und_dateien_zeilenweise():
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL,
               links="https://example.org/a" + chr(10) + "https://example.org/b",
               dateien="Angebot.pdf" + chr(10) + "Grundriss.jpg")
    profil = _reports(lead)[0]["payload"]["profil"]
    assert profil["links"] == ["https://example.org/a", "https://example.org/b"]
    assert profil["dateien"] == ["Angebot.pdf", "Grundriss.jpg"]


def test_kommagetrennt_geht_auch():
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL, dateien="a.pdf, b.pdf ,c.pdf")
    assert _reports(lead)[0]["payload"]["profil"]["dateien"] == [
        "a.pdf", "b.pdf", "c.pdf"]


def test_umbruch_gewinnt_gegen_komma():
    """Sonst zerrisse ein Komma innerhalb einer URL den Eintrag."""
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL,
               links="https://x.de/s?q=a,b" + chr(10) + "https://y.de/")
    assert _reports(lead)[0]["payload"]["profil"]["links"] == [
        "https://x.de/s?q=a,b", "https://y.de/"]


def test_doppelte_eintraege_fallen_weg():
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL, dateien="a.pdf,a.pdf,b.pdf,a.pdf")
    assert _reports(lead)[0]["payload"]["profil"]["dateien"] == [
        "a.pdf", "b.pdf"]


def test_liste_ist_gedeckelt():
    lead = _lead()
    _nachrichten(lead, 3)
    viele = ",".join(f"datei{i}.pdf" for i in range(server.PROFIL_LISTE_MAX + 20))
    _speichern(lead, **VOLLES_PROFIL, dateien=viele)
    assert len(_reports(lead)[0]["payload"]["profil"]["dateien"]) == \
        server.PROFIL_LISTE_MAX


# ---------------------------------------------------------------------------
# Versionierung — der Kern des „alle 50 Nachrichten"
# ---------------------------------------------------------------------------

def test_jede_fassung_ist_eine_neue_zeile():
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL)
    _nachrichten(lead, 3, ab_minute=500)
    neu = dict(VOLLES_PROFIL, aktuell="Zahlen sind da, Termin steht.")
    _speichern(lead, **neu)

    zeilen = _reports(lead)
    assert len(zeilen) == 2
    # Die ALTE Fassung ist noch da und unveraendert.
    assert zeilen[0]["payload"]["profil"]["aktuell"] == VOLLES_PROFIL["aktuell"]
    assert zeilen[1]["payload"]["profil"]["aktuell"] == neu["aktuell"]


def test_profil_lesen_zeigt_die_juengste_fassung():
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL)
    _nachrichten(lead, 3, ab_minute=500)
    _speichern(lead, **dict(VOLLES_PROFIL, aktuell="Neuer Stand."))

    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"]["aktuell"] == "Neuer Stand."
    assert gelesen["kontaktprofil"]["wer"] == VOLLES_PROFIL["wer"]
    assert "stand_vom" in gelesen["kontaktprofil"]


def test_ein_report_ohne_profil_loescht_das_profil_nicht():
    """Sonst verschwaende ein blosser Zwischenreport den Stand."""
    lead = _lead()
    _nachrichten(lead, 3)
    _speichern(lead, **VOLLES_PROFIL)
    _nachrichten(lead, 3, ab_minute=500)
    _speichern(lead, zusammenfassung="Nur ein Zwischenstand.")

    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"] is not None
    assert gelesen["kontaktprofil"]["wer"] == VOLLES_PROFIL["wer"]


def test_ohne_report_ist_das_profil_leer():
    lead = _lead()
    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"] is None


# ---------------------------------------------------------------------------
# Trennung von dem, was ein Mensch bestaetigt hat
# ---------------------------------------------------------------------------

def test_bestaetigte_profilfelder_bleiben_unberuehrt():
    lead = _lead()
    _nachrichten(lead, 3)
    server.profil_aktualisieren(lead, "beruf", "Dachdeckermeister")
    _speichern(lead, **VOLLES_PROFIL)

    gelesen = json.loads(server.profil_lesen(lead))
    # Das vom Menschen gesetzte Feld steht unveraendert im Profil-Knoten …
    assert gelesen["profil"]["beruf"] == "Dachdeckermeister"
    # … und das generierte liegt daneben, nicht darin.
    assert "wer" not in gelesen["profil"]
    assert gelesen["kontaktprofil"]["wer"] == VOLLES_PROFIL["wer"]


# ---------------------------------------------------------------------------
# Kein zweites System: derselbe Ausloeser, dieselbe Grenze
# ---------------------------------------------------------------------------

def test_profil_nutzt_die_grenze_des_reports():
    lead = _lead()
    ids = _nachrichten(lead, 10)
    _speichern(lead, **VOLLES_PROFIL, bis_aktivitaet_id=ids[4])
    nutzlast = _reports(lead)[0]["payload"]
    assert nutzlast["bis_aktivitaet_id"] == ids[4]
    assert nutzlast["anzahl"] == 5
    # Und das Profil haengt an derselben Zeile — nicht an einer zweiten.
    assert "profil" in nutzlast


def test_faelligkeit_bleibt_die_des_reports():
    """Ein Profil erzeugt keinen eigenen Zaehler."""
    lead = _lead()
    _nachrichten(lead, server.CHAT_REPORT_SCHWELLE)
    faellig = json.loads(server.chat_reports_faellig())
    assert any(str(k["lead_id"]) == lead for k in faellig["kontakte"])

    _speichern(lead, **VOLLES_PROFIL)
    danach = json.loads(server.chat_reports_faellig())
    assert not any(str(k["lead_id"]) == lead for k in danach["kontakte"])
