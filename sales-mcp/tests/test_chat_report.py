"""Vertragstests fuer den Chat-Report (Betreiber-Wunsch 22.08.2026).

Der Auftrag: lange Verlaeufe verdichten. Gemessen am 22.08.2026 im Schema
`sales`: 369 `nachricht_ausgehend` und 352 `kundenantwort`, ein einzelner
Kontakt weit ueber hundert davon — als Einzelzeilen unbrauchbar.

Die drei Saetze, die diese Suite festnagelt:

1. **Das Werkzeug fasst nichts zusammen.** Den Text schreibt der Agent; hier
   wird nur gespeichert. Kein Modellaufruf, kein Netz, kein Wort an den Kunden
   — nachgewiesen ueber die Tatsache, dass ausser der einen Report-Zeile
   nichts entsteht (kein Entwurf, keine ausgehende Nachricht).
2. **Append-only.** Der Report ist eine ZUSAETZLICHE Zeile. Die
   Einzelnachrichten bleiben vollzaehlig in der Datenbank; sie verschwinden
   nur aus der ANZEIGE.
3. **Die Grenze haelt.** Ein Report merkt sich, bis zu welcher Nachricht er
   reicht, damit der naechste dort ansetzt und nichts doppelt erzaehlt. Die
   Grenze ist ein PAAR (Zeitpunkt, Aktivitaets-id): `created_at` ist die
   Transaktionszeit, zwei Zeilen derselben Transaktion tragen denselben Wert
   (Befund M10) — ein Zeitstempel allein waere dort ein Muenzwurf.
"""
import json
import os

import pytest

# HART, nicht setdefault (wie test_werkzeuge.py).
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
    """`server.UNBEKANNT_LEAD_ID` ist ein Modulattribut aus der Umgebung —
    wer es umbiegt, muss es zuruecklegen (Muster aus test_einordnung.py)."""
    vorher = server.UNBEKANNT_LEAD_ID
    yield
    server.UNBEKANNT_LEAD_ID = vorher


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _nachrichten(lead, anzahl, typ="kundenantwort", ab_minute=1000):
    """`anzahl` Nachrichten mit AUSEINANDERLIEGENDEN Zeitstempeln.

    In EINER Anweisung, weil der Test sonst je Nachricht eine Verbindung
    aufmacht — bei 55 Nachrichten ist das der Unterschied zwischen einer und
    fuenfzig Sekunden. `created_at` wird ausdruecklich gesetzt: der
    Spalten-Default waere `now()`, also die Transaktionszeit, und alle Zeilen
    truegen denselben Wert.
    """
    return [str(z["id"]) for z in server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "select %s, %s, jsonb_build_object('text', 'Nachricht ' || g), "
        "       now() - make_interval(mins => %s - g) "
        "  from generate_series(1, %s) g "
        "returning id", (lead, typ, ab_minute, anzahl))]


def _reports(lead):
    return server._q(
        "select payload, actor, created_at from activities "
        "where lead_id = %s and type = %s order by created_at",
        (lead, server.CHAT_REPORT_TYP))


def _nachrichten_in_db(lead):
    return server._q(
        "select count(*) as n from activities where lead_id = %s "
        "and type = any(%s)",
        (lead, list(server.CHAT_NACHRICHT_TYPEN)))[0]["n"]


# ---------------------------------------------------------------------------
# Die Schwelle ist eine Konstante, keine Zahl im SQL
# ---------------------------------------------------------------------------

def test_schwelle_steht_als_konstante_und_ist_fuenfzig():
    assert server.CHAT_REPORT_SCHWELLE == 50


def test_unter_der_schwelle_ist_nichts_faellig():
    lead = _lead()
    _nachrichten(lead, server.CHAT_REPORT_SCHWELLE - 1)
    faellig = json.loads(server.chat_reports_faellig())
    assert faellig["anzahl"] == 0
    assert faellig["kontakte"] == []


def test_genau_auf_der_schwelle_ist_faellig():
    """„50 ODER MEHR" — die Grenze gehoert zum faelligen Bereich."""
    lead = _lead()
    _nachrichten(lead, server.CHAT_REPORT_SCHWELLE)
    faellig = json.loads(server.chat_reports_faellig())
    assert faellig["anzahl"] == 1
    assert faellig["kontakte"][0]["lead_id"] == lead
    assert faellig["kontakte"][0]["offene_nachrichten"] == 50
    assert faellig["schwelle"] == 50


def test_beide_richtungen_zaehlen_als_nachricht():
    """Ein Chat besteht aus Hin und Her. Zaehlte nur eine Richtung, waere die
    Schwelle in der Praxis doppelt so hoch wie beschrieben."""
    lead = _lead()
    _nachrichten(lead, 20, typ="kundenantwort", ab_minute=1000)
    _nachrichten(lead, 20, typ="nachricht_ausgehend", ab_minute=900)
    _nachrichten(lead, 10, typ="versand", ab_minute=800)
    faellig = json.loads(server.chat_reports_faellig())
    assert faellig["kontakte"][0]["offene_nachrichten"] == 50


def test_andere_aktivitaeten_zaehlen_nicht_mit():
    lead = _lead()
    _nachrichten(lead, 40)
    _nachrichten(lead, 20, typ="bedarf", ab_minute=500)
    assert json.loads(server.chat_reports_faellig())["anzahl"] == 0


# ---------------------------------------------------------------------------
# Speichern: eine zusaetzliche Zeile, sonst nichts
# ---------------------------------------------------------------------------

def test_report_wird_als_aktivitaet_gespeichert():
    lead = _lead()
    _nachrichten(lead, 55)
    ok = json.loads(server.chat_report_speichern(
        lead, "Kunde fragt nach bAV, Unterlagen zugesagt."))
    assert ok["zusammengefasst"] == 55
    assert ok["offen_danach"] == 0
    zeilen = _reports(lead)
    assert len(zeilen) == 1
    assert zeilen[0]["payload"]["zusammenfassung"] == (
        "Kunde fragt nach bAV, Unterlagen zugesagt.")
    assert zeilen[0]["payload"]["anzahl"] == 55


def test_speichern_merkt_sich_die_grenze_als_paar():
    lead = _lead()
    ids = _nachrichten(lead, 55)
    ok = json.loads(server.chat_report_speichern(lead, "Zusammenfassung."))
    nutzlast = _reports(lead)[0]["payload"]
    assert nutzlast["bis_aktivitaet_id"] == ids[-1]
    assert nutzlast["bis_zeitpunkt"]
    assert ok["bis_aktivitaet_id"] == ids[-1]


def test_einzelnachrichten_bleiben_vollzaehlig_in_der_datenbank():
    """Append-only: verdichtet wird die ANZEIGE, nicht der Bestand."""
    lead = _lead()
    _nachrichten(lead, 55)
    server.chat_report_speichern(lead, "Zusammenfassung.")
    assert _nachrichten_in_db(lead) == 55


def test_speichern_schickt_nichts_und_erzeugt_keinen_entwurf():
    """Kein Modellaufruf, kein Netz, kein Wort an den Kunden: ausser der
    einen Report-Zeile darf gar nichts entstehen."""
    lead = _lead()
    _nachrichten(lead, 55)
    vorher = server._q("select type, count(*) as n from activities "
                       "where lead_id = %s group by type", (lead,))
    server.chat_report_speichern(lead, "Zusammenfassung.")
    nachher = server._q("select type, count(*) as n from activities "
                        "where lead_id = %s group by type", (lead,))
    neu = {z["type"]: z["n"] for z in nachher}
    alt = {z["type"]: z["n"] for z in vorher}
    assert set(neu) - set(alt) == {server.CHAT_REPORT_TYP}
    assert neu[server.CHAT_REPORT_TYP] == 1
    assert server._q("select id from drafts where lead_id = %s", (lead,)) == []


def test_leere_zusammenfassung_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 55)
    kaputt = json.loads(server.chat_report_speichern(lead, "   "))
    assert "fehler" in kaputt
    assert _reports(lead) == []


def test_zu_lange_zusammenfassung_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 55)
    kaputt = json.loads(server.chat_report_speichern(
        lead, "x" * (server.CHAT_REPORT_MAXLAENGE + 1)))
    assert "fehler" in kaputt
    assert _reports(lead) == []


def test_ohne_offene_nachrichten_gibt_es_nichts_zusammenzufassen():
    lead = _lead()
    kaputt = json.loads(server.chat_report_speichern(lead, "Zusammenfassung."))
    assert "fehler" in kaputt
    assert _reports(lead) == []


def test_unbekannter_kontakt_gibt_fehlertext():
    kaputt = json.loads(server.chat_report_speichern(
        "00000000-0000-0000-0000-000000000000", "Zusammenfassung."))
    assert "fehler" in kaputt


# ---------------------------------------------------------------------------
# Die Grenze: der naechste Report setzt an, wo der vorige aufhoerte
# ---------------------------------------------------------------------------

def test_zweiter_report_faengt_hinter_dem_ersten_an():
    lead = _lead()
    _nachrichten(lead, 55, ab_minute=1000)
    server.chat_report_speichern(lead, "Erster Abschnitt.")
    _nachrichten(lead, 60, ab_minute=500)
    zweiter = json.loads(server.chat_report_speichern(lead, "Zweiter Abschnitt."))
    assert zweiter["zusammengefasst"] == 60      # NICHT 115
    assert zweiter["offen_danach"] == 0
    assert len(_reports(lead)) == 2


def test_nach_dem_report_ist_nichts_mehr_faellig():
    lead = _lead()
    _nachrichten(lead, 55)
    assert json.loads(server.chat_reports_faellig())["anzahl"] == 1
    server.chat_report_speichern(lead, "Zusammenfassung.")
    assert json.loads(server.chat_reports_faellig())["anzahl"] == 0


def test_grenze_aus_derselben_transaktion_bleibt_eindeutig():
    """Zwei Zeilen mit IDENTISCHEM `created_at` (dieselbe Transaktion, Befund
    M10). Eine Grenze aus dem Zeitstempel allein liesse hier eine der beiden
    Nachrichten entweder doppelt oder gar nicht durch; das Paar
    (Zeitpunkt, id) entscheidet."""
    lead = _lead()
    ids = [str(z["id"]) for z in server._q(
        "insert into activities (lead_id, type, payload, created_at) "
        "values (%s, 'kundenantwort', '{\"text\": \"a\"}', now()), "
        "       (%s, 'kundenantwort', '{\"text\": \"b\"}', now()) "
        "returning id", (lead, lead))]
    kleinere = min(ids)
    ok = json.loads(server.chat_report_speichern(
        lead, "Nur die erste.", bis_aktivitaet_id=kleinere))
    assert ok["zusammengefasst"] == 1
    assert ok["offen_danach"] == 1
    verlauf = json.loads(server.chat_verlauf(lead))
    assert [n["aktivitaets_id"] for n in verlauf["nachrichten"]] == [max(ids)]


def test_grenze_muss_hinter_dem_letzten_report_liegen():
    lead = _lead()
    ids = _nachrichten(lead, 10)
    server.chat_report_speichern(lead, "Alles bisher.")
    kaputt = json.loads(server.chat_report_speichern(
        lead, "Nochmal dasselbe.", bis_aktivitaet_id=ids[3]))
    assert "fehler" in kaputt
    assert len(_reports(lead)) == 1


def test_grenze_eines_fremden_kontakts_wird_abgelehnt():
    lead = _lead()
    fremd = _lead(name="Andere Person", phone="+491700000002")
    _nachrichten(lead, 5)
    fremde_ids = _nachrichten(fremd, 5, ab_minute=500)
    kaputt = json.loads(server.chat_report_speichern(
        lead, "Zusammenfassung.", bis_aktivitaet_id=fremde_ids[-1]))
    assert "fehler" in kaputt
    assert _reports(lead) == []


def test_grenze_auf_einer_nicht_nachricht_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 5)
    andere = str(server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'bedarf', '{}') returning id", (lead,))[0]["id"])
    kaputt = json.loads(server.chat_report_speichern(
        lead, "Zusammenfassung.", bis_aktivitaet_id=andere))
    assert "fehler" in kaputt
    assert _reports(lead) == []


def test_unbekannte_grenze_wird_abgelehnt():
    lead = _lead()
    _nachrichten(lead, 5)
    kaputt = json.loads(server.chat_report_speichern(
        lead, "Zusammenfassung.",
        bis_aktivitaet_id="00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# ---------------------------------------------------------------------------
# chat_verlauf — die Lesevorlage
# ---------------------------------------------------------------------------

def test_verlauf_liefert_offene_nachrichten_aelteste_zuerst():
    lead = _lead()
    ids = _nachrichten(lead, 5)
    verlauf = json.loads(server.chat_verlauf(lead))
    assert [n["aktivitaets_id"] for n in verlauf["nachrichten"]] == ids
    assert verlauf["nachrichten"][0]["text"] == "Nachricht 1"
    assert verlauf["bis_aktivitaet_id"] == ids[-1]
    assert verlauf["vollstaendig"] is True


def test_verlauf_zeigt_zusammengefasste_nachrichten_nicht_mehr():
    lead = _lead()
    _nachrichten(lead, 10, ab_minute=1000)
    server.chat_report_speichern(lead, "Alles bisher.")
    neue = _nachrichten(lead, 3, ab_minute=500)
    verlauf = json.loads(server.chat_verlauf(lead))
    assert [n["aktivitaets_id"] for n in verlauf["nachrichten"]] == neue
    assert len(verlauf["reports"]) == 1
    assert verlauf["reports"][0]["zusammenfassung"] == "Alles bisher."


def test_verlauf_deckelt_und_sagt_es():
    lead = _lead()
    _nachrichten(lead, 30)
    verlauf = json.loads(server.chat_verlauf(lead, limit=10))
    assert verlauf["geliefert"] == 10
    assert verlauf["gesamt"] == 30
    assert verlauf["vollstaendig"] is False


def test_verlauf_mit_alle_holt_die_zusammengefassten_zurueck():
    """„Geloescht ist nichts" muss auch heissen: man kommt wieder ran. Ohne
    diesen Weg waere der Wortlaut hinter einem Report nur noch per psql
    erreichbar — und die Zusage in AGENTS.md und Runbook waere hohl."""
    lead = _lead()
    _nachrichten(lead, 10, ab_minute=1000)
    server.chat_report_speichern(lead, "Alles bisher.")
    _nachrichten(lead, 3, ab_minute=500)
    normal = json.loads(server.chat_verlauf(lead))
    alle = json.loads(server.chat_verlauf(lead, alle=True))
    assert normal["gesamt"] == 3
    assert alle["gesamt"] == 13
    assert alle["nachrichten"][0]["text"] == "Nachricht 1"


def test_verlauf_mit_alle_liefert_keine_grenze():
    """Die Nachlese deckelt VORN (aelteste zuerst) — ihre letzte Zeile als
    Grenze zu nehmen setzte den Report rueckwaerts."""
    lead = _lead()
    _nachrichten(lead, 5)
    alle = json.loads(server.chat_verlauf(lead, alle=True))
    assert alle["bis_aktivitaet_id"] is None
    assert alle["alle"] is True


def test_verlauf_kennt_die_richtung():
    lead = _lead()
    _nachrichten(lead, 1, typ="kundenantwort", ab_minute=1000)
    _nachrichten(lead, 1, typ="nachricht_ausgehend", ab_minute=900)
    verlauf = json.loads(server.chat_verlauf(lead))
    assert [n["richtung"] for n in verlauf["nachrichten"]] == [
        "eingehend", "ausgehend"]


def test_verlauf_unbekannter_kontakt_gibt_fehlertext():
    kaputt = json.loads(
        server.chat_verlauf("00000000-0000-0000-0000-000000000000"))
    assert "fehler" in kaputt


# ---------------------------------------------------------------------------
# profil_lesen — Reports zuerst, dann die offenen Einzelzeilen
# ---------------------------------------------------------------------------

def test_profil_zeigt_reports_und_verbirgt_die_abgedeckten_zeilen():
    lead = _lead()
    _nachrichten(lead, 12, ab_minute=1000)
    server.chat_report_speichern(lead, "Kunde fragt nach bAV.")
    _nachrichten(lead, 2, ab_minute=500)
    profil = json.loads(server.profil_lesen(lead))
    assert len(profil["chat_reports"]) == 1
    assert profil["chat_reports"][0]["zusammenfassung"] == "Kunde fragt nach bAV."
    assert profil["chat_reports"][0]["nachrichten"] == 12
    assert len(profil["aktivitaeten"]) == 2
    assert all(a["type"] == "kundenantwort" for a in profil["aktivitaeten"])


def test_profil_zeigt_den_report_nicht_zusaetzlich_im_verlauf():
    lead = _lead()
    _nachrichten(lead, 5)
    server.chat_report_speichern(lead, "Zusammenfassung.")
    profil = json.loads(server.profil_lesen(lead))
    assert all(a["type"] != server.CHAT_REPORT_TYP
               for a in profil["aktivitaeten"])


def test_profil_ohne_report_zeigt_den_verlauf_wie_bisher():
    lead = _lead()
    _nachrichten(lead, 3)
    profil = json.loads(server.profil_lesen(lead))
    assert profil["chat_reports"] == []
    assert len(profil["aktivitaeten"]) == 3


def test_profil_behaelt_nicht_nachrichtliche_zeilen_trotz_report():
    """Ein Report verdichtet Nachrichten — nicht den Bedarfsstand, nicht
    Freigaben, nicht Notizen. Die bleiben im Verlauf stehen."""
    lead = _lead()
    _nachrichten(lead, 5, ab_minute=1000)
    server._q("insert into activities (lead_id, type, payload, created_at) "
              "values (%s, 'notiz', '{\"inhalt\": \"wichtig\"}', "
              "now() - interval '600 minutes') returning id", (lead,))
    server.chat_report_speichern(lead, "Zusammenfassung.")
    profil = json.loads(server.profil_lesen(lead))
    assert [a["type"] for a in profil["aktivitaeten"]] == ["notiz"]


# ---------------------------------------------------------------------------
# Der Sammelkontakt: viele Fremde, kein gemeinsamer Chat
# ---------------------------------------------------------------------------

def test_sammelkontakt_steht_nie_in_der_faelligkeitsliste(sammelkontakt_zurueck):
    """An „Unbekannte Eingaenge" haengt JEDE Nachricht einer noch unbekannten
    Nummer — am 22.08.2026 waren das 675 Zeilen von 16 Absendern. Das ist kein
    Chat, sondern ein Stapel fremder Chats."""
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    server.UNBEKANNT_LEAD_ID = sammel
    _nachrichten(sammel, 80)
    assert json.loads(server.chat_reports_faellig())["anzahl"] == 0


def test_sammelkontakt_laesst_sich_nicht_zusammenfassen(sammelkontakt_zurueck):
    sammel = _lead(name="Unbekannte Eingaenge", phone=None)
    server.UNBEKANNT_LEAD_ID = sammel
    _nachrichten(sammel, 80)
    kaputt = json.loads(server.chat_report_speichern(sammel, "Alles Fremde."))
    assert "fehler" in kaputt
    assert "eingang_einordnen" in kaputt["fehler"]
    assert _reports(sammel) == []


def test_archivierter_kontakt_steht_nicht_in_der_faelligkeitsliste():
    lead = _lead()
    _nachrichten(lead, 60)
    server.kontakt_archivieren(lead)
    assert json.loads(server.chat_reports_faellig())["anzahl"] == 0


# ---------------------------------------------------------------------------
# Digest und Werkzeugschicht
# ---------------------------------------------------------------------------

def test_digest_nennt_faellige_chat_reports():
    lead = _lead()
    _nachrichten(lead, 60)
    block = json.loads(server.digest())["faellige_chat_reports"]
    assert block["anzahl"] == 1
    assert block["schwelle"] == 50
    assert block["kontakte"][0]["lead_id"] == lead


def test_werkzeuge_sind_registriert():
    for werkzeug in (server.chat_report_speichern, server.chat_reports_faellig,
                     server.chat_verlauf):
        assert werkzeug in server.WERKZEUGE


def test_speichern_traegt_seine_parameter():
    import inspect
    parameter = inspect.signature(server.chat_report_speichern).parameters
    assert "lead_id" in parameter and "zusammenfassung" in parameter
    assert parameter["bis_aktivitaet_id"].default == ""
