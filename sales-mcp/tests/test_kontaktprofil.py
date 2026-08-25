"""Vertragstests fuer das strukturierte Kontaktprofil.

Betreiber-Wunsch vom 22.08.2026, woertlich:

  „wir wollen noch die Nachrichten pro kontakt mit einen automatisch
   generierten Profil ueber die Nachrichten / links pdfs dateien / es soll
   wer ist der Mensch / in welcher beziehung stehe ich zu ihn / was ist
   wichtig fuer den Mensch / was ist aktuell grad los"

und nachgereicht am 25.08.2026:

  „i think every 5 would be better or on request of the owner of the bot."

DIE ZWEITE FASSUNG KORRIGIERT DIE ERSTE. Zuerst lag das Profil IM
Chat-Report — ein Zaehler, eine Grenze, keine Doppelung. Fuer 50
Nachrichten war das richtig. Bei 5 zerbricht es, weil die beiden Dinge
Verschiedenes TUN:

  Report:  verdichtet und VERSTECKT die abgedeckten Nachrichten in der
           Anzeige. Selten richtig, bei 50.
  Profil:  Momentaufnahme, versteckt NICHTS. Oft richtig, bei 5.

Bei gemeinsamer Grenze haette „alle 5" den Verlauf binnen eines Tages in
lauter Stummel verwandelt. Diese Suite nagelt die Trennung fest.
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


@pytest.fixture
def sammelkontakt_zurueck():
    vorher = server.UNBEKANNT_LEAD_ID
    yield
    server.UNBEKANNT_LEAD_ID = vorher


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


VOLL = {
    "wer": "Selbstaendiger Handwerker, Mitte vierzig, zwei Kinder.",
    "beziehung": "Seit dem Erstgespraech im Juli in loser Verbindung.",
    "wichtig": "Verlaesslichkeit und kurze Wege; will keine Vertreterbesuche.",
    "aktuell": "Sucht eine Absicherung fuer den Betrieb, wartet auf Zahlen.",
}


def _schreiben(lead, **abweichend):
    felder = dict(VOLL, **abweichend)
    return json.loads(server.kontaktprofil_schreiben(lead, **felder))


def _profile(lead):
    return server._q(
        "select payload, created_at from activities where lead_id = %s "
        "and type = %s order by created_at, id", (lead, server.PROFIL_TYP))


def _reports(lead):
    return server._q(
        "select payload from activities where lead_id = %s and type = %s "
        "order by created_at", (lead, server.CHAT_REPORT_TYP))


# ---------------------------------------------------------------------------
# Die vier Leitfragen
# ---------------------------------------------------------------------------

def test_die_vier_leitfragen_stehen_an_einer_stelle():
    assert server.PROFIL_FELDER == ("wer", "beziehung", "wichtig", "aktuell")
    assert set(server.PROFIL_FRAGEN) == set(server.PROFIL_FELDER)
    for frage in server.PROFIL_FRAGEN.values():
        assert frage.endswith("?")


def test_volles_profil_wird_gespeichert():
    lead = _lead()
    _nachrichten(lead, 3)
    assert "fehler" not in _schreiben(lead)
    zeilen = _profile(lead)
    assert len(zeilen) == 1
    for feld, wert in VOLL.items():
        assert zeilen[0]["payload"][feld] == wert


@pytest.mark.parametrize("leer", ["wer", "beziehung", "wichtig", "aktuell"])
def test_drei_von_vier_werden_abgelehnt(leer):
    lead = _lead()
    _nachrichten(lead, 3)
    antwort = _schreiben(lead, **{leer: ""})
    assert "fehler" in antwort
    assert leer in antwort["fehler"]
    assert _profile(lead) == []


def test_zu_langer_abschnitt_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 3)
    antwort = _schreiben(lead, wer="x" * (server.PROFIL_FELD_MAXLAENGE + 1))
    assert "fehler" in antwort
    assert _profile(lead) == []


def test_ohne_nachrichten_kein_profil():
    lead = _lead()
    antwort = _schreiben(lead)
    assert "fehler" in antwort
    assert "keine Nachricht" in antwort["fehler"]


# ---------------------------------------------------------------------------
# DER KERN: ein Profil versteckt nichts
# ---------------------------------------------------------------------------

def test_profil_versteckt_keine_nachrichten():
    """Der Grund, warum Profil und Report getrennt sind.

    Der Chat-Report schiebt seine Grenze und laesst die abgedeckten
    Nachrichten aus der Anzeige verschwinden. Bei „alle 5" waere der
    Verlauf binnen eines Tages weg. Ein Profil darf das nicht.
    """
    lead = _lead()
    _nachrichten(lead, 12)
    vorher = json.loads(server.chat_verlauf(lead))
    _schreiben(lead)
    nachher = json.loads(server.chat_verlauf(lead))
    assert nachher["gesamt"] == vorher["gesamt"]
    assert len(nachher["nachrichten"]) == len(vorher["nachrichten"])
    assert _reports(lead) == []          # und es entstand kein Report


def test_profil_bewegt_die_report_grenze_nicht():
    lead = _lead()
    _nachrichten(lead, 12)
    vor = server._chat_grenze(lead)
    _schreiben(lead)
    assert server._chat_grenze(lead) == vor


def test_report_und_profil_haben_getrennte_grenzen():
    lead = _lead()
    ids = _nachrichten(lead, 20)
    _schreiben(lead, **{})                       # Profil bis zur juengsten
    server.chat_report_speichern(lead, "Zusammenfassung.",
                                 bis_aktivitaet_id=ids[4])
    profil_zeit, profil_id = server._profil_grenze(lead)
    report_zeit, report_id = server._chat_grenze(lead)
    assert str(profil_id) != str(report_id)
    assert str(report_id) == ids[4]


# ---------------------------------------------------------------------------
# Versionierung
# ---------------------------------------------------------------------------

def test_jede_fassung_ist_eine_neue_zeile():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead)
    _nachrichten(lead, 3, ab_minute=500)
    _schreiben(lead, aktuell="Zahlen sind da, Termin steht.")
    zeilen = _profile(lead)
    assert len(zeilen) == 2
    assert zeilen[0]["payload"]["aktuell"] == VOLL["aktuell"]
    assert zeilen[1]["payload"]["aktuell"] == "Zahlen sind da, Termin steht."


def test_profil_lesen_zeigt_die_juengste_fassung():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead)
    _nachrichten(lead, 3, ab_minute=500)
    _schreiben(lead, aktuell="Neuer Stand.")
    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"]["aktuell"] == "Neuer Stand."
    assert "stand_vom" in gelesen["kontaktprofil"]
    # Buchhaltungsfelder gehoeren nicht in die Anzeige.
    for schluessel in ("anzahl", "bis_zeitpunkt", "bis_aktivitaet_id"):
        assert schluessel not in gelesen["kontaktprofil"]


def test_ohne_profil_ist_es_leer():
    assert json.loads(server.profil_lesen(_lead()))["kontaktprofil"] is None


def test_altes_eingebettetes_profil_wird_noch_gelesen():
    """Rueckwaertsvertraeglich: die erste Fassung legte es IM Report ab.

    Es gibt davon echte Daten (Sophie, 25.08.2026). Eine Wanderung waere
    mehr Risiko als der eine union-Zweig in _juengstes_profil.
    """
    lead = _lead()
    _nachrichten(lead, 3)
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, %s, %s) returning id",
        (lead, server.CHAT_REPORT_TYP,
         json.dumps({"zusammenfassung": "alt", "profil": dict(VOLL)})))
    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"]["wer"] == VOLL["wer"]


def test_neues_profil_gewinnt_gegen_altes_eingebettetes():
    lead = _lead()
    _nachrichten(lead, 3)
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, %s, %s) returning id",
        (lead, server.CHAT_REPORT_TYP,
         json.dumps({"zusammenfassung": "alt",
                     "profil": dict(VOLL, wer="Alte Fassung")})))
    _schreiben(lead, wer="Neue Fassung")
    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["kontaktprofil"]["wer"] == "Neue Fassung"


def test_bestaetigte_profilfelder_bleiben_unberuehrt():
    lead = _lead()
    _nachrichten(lead, 3)
    server.profil_aktualisieren(lead, "beruf", "Dachdeckermeister")
    _schreiben(lead)
    gelesen = json.loads(server.profil_lesen(lead))
    assert gelesen["profil"]["beruf"] == "Dachdeckermeister"
    assert "wer" not in gelesen["profil"]
    assert gelesen["kontaktprofil"]["wer"] == VOLL["wer"]


# ---------------------------------------------------------------------------
# Links und Dateien
# ---------------------------------------------------------------------------

def test_links_zeilenweise():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead, links="https://example.org/a" + chr(10)
               + "https://example.org/b")
    assert _profile(lead)[0]["payload"]["links"] == [
        "https://example.org/a", "https://example.org/b"]


def test_kommagetrennt_geht_auch():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead, dateien="a.pdf, b.pdf ,c.pdf")
    assert _profile(lead)[0]["payload"]["dateien"] == ["a.pdf", "b.pdf",
                                                       "c.pdf"]


def test_umbruch_gewinnt_gegen_komma():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead, links="https://x.de/s?q=a,b" + chr(10) + "https://y.de/")
    assert _profile(lead)[0]["payload"]["links"] == ["https://x.de/s?q=a,b",
                                                     "https://y.de/"]


def test_doppelte_fallen_weg_und_die_liste_ist_gedeckelt():
    lead = _lead()
    _nachrichten(lead, 3)
    _schreiben(lead, dateien="a.pdf,a.pdf,b.pdf")
    assert _profile(lead)[0]["payload"]["dateien"] == ["a.pdf", "b.pdf"]
    _nachrichten(lead, 1, ab_minute=500)
    viele = ",".join(f"d{i}.pdf" for i in range(server.PROFIL_LISTE_MAX + 20))
    _schreiben(lead, dateien=viele)
    assert len(_profile(lead)[1]["payload"]["dateien"]) == \
        server.PROFIL_LISTE_MAX


# ---------------------------------------------------------------------------
# Der Takt: alle fuenf — oder auf Zuruf
# ---------------------------------------------------------------------------

def test_schwelle_ist_fuenf_und_steht_an_einer_stelle():
    assert server.PROFIL_SCHWELLE == 5
    assert server.CHAT_REPORT_SCHWELLE == 50      # der Report bleibt selten


def test_unter_der_schwelle_nicht_faellig():
    lead = _lead()
    _nachrichten(lead, server.PROFIL_SCHWELLE - 1)
    faellig = json.loads(server.profile_faellig())
    assert not any(str(k["lead_id"]) == lead for k in faellig["kontakte"])


def test_ab_der_schwelle_faellig():
    lead = _lead()
    _nachrichten(lead, server.PROFIL_SCHWELLE)
    faellig = json.loads(server.profile_faellig())
    treffer = [k for k in faellig["kontakte"] if str(k["lead_id"]) == lead]
    assert treffer and treffer[0]["neue_nachrichten"] == server.PROFIL_SCHWELLE
    assert treffer[0]["angefordert"] is False


def test_nach_dem_schreiben_nicht_mehr_faellig():
    lead = _lead()
    _nachrichten(lead, server.PROFIL_SCHWELLE)
    _schreiben(lead)
    faellig = json.loads(server.profile_faellig())
    assert not any(str(k["lead_id"]) == lead for k in faellig["kontakte"])


def test_neue_nachrichten_machen_wieder_faellig():
    lead = _lead()
    _nachrichten(lead, server.PROFIL_SCHWELLE)
    _schreiben(lead)
    _nachrichten(lead, server.PROFIL_SCHWELLE, ab_minute=500)
    faellig = json.loads(server.profile_faellig())
    assert any(str(k["lead_id"]) == lead for k in faellig["kontakte"])


def test_anforderung_gilt_unabhaengig_von_der_anzahl():
    """Genau dann fragt man am ehesten: wenn erst wenig da ist."""
    lead = _lead()
    _nachrichten(lead, 2)                     # weit unter der Schwelle
    assert "fehler" not in json.loads(server.profil_anfordern(lead))
    faellig = json.loads(server.profile_faellig())
    treffer = [k for k in faellig["kontakte"] if str(k["lead_id"]) == lead]
    assert treffer and treffer[0]["angefordert"] is True


def test_anforderung_ist_nach_dem_schreiben_erledigt():
    lead = _lead()
    _nachrichten(lead, 2)
    server.profil_anfordern(lead)
    _schreiben(lead)
    faellig = json.loads(server.profile_faellig())
    assert not any(str(k["lead_id"]) == lead for k in faellig["kontakte"])


def test_angeforderte_stehen_oben():
    knapp = _lead(name="Viele Nachrichten", phone="+491700000001")
    _nachrichten(knapp, server.PROFIL_SCHWELLE + 10)
    gefragt = _lead(name="Angefordert", phone="+491700000002")
    _nachrichten(gefragt, 1)
    server.profil_anfordern(gefragt)
    kontakte = json.loads(server.profile_faellig())["kontakte"]
    assert str(kontakte[0]["lead_id"]) == gefragt


# ---------------------------------------------------------------------------
# Der Sammelkontakt bleibt draussen
# ---------------------------------------------------------------------------

def test_sammelkontakt_bekommt_kein_profil(sammelkontakt_zurueck):
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    server.UNBEKANNT_LEAD_ID = sammel
    _nachrichten(sammel, 20)
    antwort = _schreiben(sammel)
    assert "fehler" in antwort
    assert _profile(sammel) == []
    assert "fehler" in json.loads(server.profil_anfordern(sammel))
    faellig = json.loads(server.profile_faellig())
    assert not any(str(k["lead_id"]) == sammel for k in faellig["kontakte"])


def test_archivierte_stehen_nicht_in_der_faelligkeit():
    lead = _lead()
    _nachrichten(lead, server.PROFIL_SCHWELLE + 5)
    server.kontakt_archivieren(lead)
    faellig = json.loads(server.profile_faellig())
    assert not any(str(k["lead_id"]) == lead for k in faellig["kontakte"])


# ---------------------------------------------------------------------------
# Der bequeme Weg: Report und Profil in einem Aufruf
# ---------------------------------------------------------------------------

def test_report_kann_das_profil_mitschreiben():
    lead = _lead()
    _nachrichten(lead, 8)
    antwort = json.loads(server.chat_report_speichern(
        lead, "Zusammenfassung des Verlaufs.", **VOLL))
    assert "fehler" not in antwort
    # Zwei Zeilen, nicht eine mit eingebettetem Profil.
    assert len(_reports(lead)) == 1
    assert len(_profile(lead)) == 1
    assert "profil" not in _reports(lead)[0]["payload"]


def test_halbes_profil_verhindert_auch_den_report():
    lead = _lead()
    _nachrichten(lead, 8)
    antwort = json.loads(server.chat_report_speichern(
        lead, "Zusammenfassung.", wer=VOLL["wer"]))
    assert "fehler" in antwort
    assert _reports(lead) == []
    assert _profile(lead) == []


def test_report_ohne_profil_bleibt_ein_report():
    lead = _lead()
    _nachrichten(lead, 8)
    assert "fehler" not in json.loads(
        server.chat_report_speichern(lead, "Nur eine Zusammenfassung."))
    assert len(_reports(lead)) == 1
    assert _profile(lead) == []
