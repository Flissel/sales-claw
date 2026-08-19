"""Vertragstests fuer die Beraterin-Uebergabe gegen sales_test.

Die Uebergabe ist die Naht zwischen Assistent und lizenzierter Beraterin
(§34d): sie STELLT ZUSAMMEN, was der Kunde selbst gesagt hat — Profil,
Bedarfsantworten, genannte Vertraege, offene Punkte — und BEWERTET nichts.
Sie versendet nichts und ruehrt keinen Entwurf an; geschrieben wird
ausschliesslich der Markdown-Report nach /reports (ueber
`recherche.report_schreiben`, Pfad-Haertung inklusive) und ein
Protokoll-Ereignis. Genau diese drei Eigenschaften — Vollstaendigkeit,
Nicht-Bewertung, kein Egress — sind hier festgenagelt.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import pytest

# HART, nicht setdefault: eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die truncate-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import recherche  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein."""
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer(tmp_path, monkeypatch):
    # Reportordner-Muster aus test_recherche.py (saubere_umgebung): kein Test
    # schreibt je in das echte /reports des Betriebs.
    monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


def _heute():
    """UTC, nicht date.today() — und das ist hier keine Kosmetik.

    Der Container laeuft mit TZ=Europe/Berlin, die Werkzeugschicht rechnet
    durchgehend in UTC (`datetime.now(timezone.utc).date()`). Zwischen 00:00
    und 02:00 Berliner Zeit laufen beide Datumsbegriffe einen Tag auseinander —
    ein Test mit date.today() ist in genau diesem Fenster rot, sonst gruen.
    Gleiches Muster wie `_heute()` in test_vertraege.py und test_werkzeuge.py.
    """
    return datetime.now(timezone.utc).date()


def _lead(name="Max Bestand"):
    return server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491701234567', 'whatsapp') returning id", (name,))[0]["id"]


def test_uebergabe_sammelt_profil_bedarf_und_offene_punkte(tmp_path):
    lead = _lead()
    server.profil_aktualisieren(str(lead), "beruf", "Schreinermeister")
    # frage_id muss aus dem Leitfaden stammen (bedarf_speichern prueft gegen
    # ALLE_FRAGEN) — 'netto' ist die Einkommensfrage, 'einkommen' nur die
    # Gruppe.
    server.bedarf_speichern(str(lead), "netto", "3800 netto")
    server.aktivitaet_loggen(lead_id=str(lead), typ="offener_punkt",
                             inhalt="Frage nach BU-Nachversicherung")
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    assert antwort["offene_punkte_anzahl"] == 1
    text = antwort["text"]
    for erwartet in ("Max Bestand", "Schreinermeister", "3800 netto",
                     "BU-Nachversicherung", "Consent"):
        assert erwartet in text
    # Der Report liegt im (monkeypatchten) Reportordner und ist zeichengleich
    # mit dem zurueckgegebenen Text — was die Beraterin liest, ist genau das,
    # was der Chat angezeigt hat.
    assert os.path.dirname(antwort["pfad"]) == os.path.realpath(str(tmp_path))
    with open(antwort["pfad"], encoding="utf-8") as f:
        assert f.read() == text


def test_vertraege_stehen_mit_gesellschaft_und_ablauf_im_text():
    """Die Feldnamen sind die von vertrag_speichern geschriebenen
    (sparte/gesellschaft/ablauf) — laufen sie auseinander, steht in der
    Uebergabe '?' statt des Bestands."""
    lead = _lead()
    ablauf = (_heute() + timedelta(days=120)).isoformat()
    server.vertrag_speichern(lead_id=str(lead), sparte="BU",
                             gesellschaft="Beispiel AG", ablauf=ablauf)
    text = json.loads(server.uebergabe_erstellen(str(lead)))["text"]
    assert "BU" in text and "Beispiel AG" in text and ablauf in text
    assert "?" not in text.split("## Vertraege")[1].split("##")[0]


def test_leere_abschnitte_bleiben_lesbar_und_ohne_bewertung():
    """Der haeufigste Fall am Anfang: fast nichts steht drin. Die Uebergabe
    muss trotzdem eine vollstaendige, lesbare Struktur liefern — und den
    §34d-Schlusssatz tragen, der sie als Zusammenstellung ausweist."""
    lead = _lead()
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    text = antwort["text"]
    assert antwort["offene_punkte_anzahl"] == 0
    for abschnitt in ("## Profil", "## Bedarfsanalyse", "## Vertraege",
                      "## Fragen des Kunden", "## Letzte Aktivitaeten"):
        assert abschnitt in text
    assert "(leer)" in text and "(keine genannt)" in text and "(keine)" in text
    assert "KEINE Beratung" in text


def test_uebergabe_wird_protokolliert_und_unbekannter_lead_faellt_sauber():
    lead = _lead()
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    protokoll = server._q("select payload from activities "
                          "where type='uebergabe'")
    assert len(protokoll) == 1
    assert protokoll[0]["payload"]["pfad"] == antwort["pfad"]
    assert "fehler" in json.loads(server.uebergabe_erstellen(
        "00000000-0000-0000-0000-000000000000"))


def test_dateiname_wird_geslugt_und_verlaesst_den_reportordner_nicht(tmp_path):
    """Der Kundenname geht in einen Dateinamen — also durch `recherche.slug`.
    Ein Name mit Umlauten, Sonderzeichen und Traversal-Versuch darf weder
    ausbrechen noch etwas anderes als [a-z0-9-] hinterlassen."""
    lead = _lead(name="Müller & Söhne ../../etc/passwd")
    pfad = json.loads(server.uebergabe_erstellen(str(lead)))["pfad"]
    assert os.path.dirname(pfad) == os.path.realpath(str(tmp_path))
    assert re.fullmatch(r"uebergabe-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.md",
                        os.path.basename(pfad))
    assert "mueller" in os.path.basename(pfad)


def test_schreibfehler_kostet_die_uebergabe_nicht(monkeypatch):
    """Fehlt der Bind ./reports:/reports, ist der Ordner nicht beschreibbar —
    die Zusammenstellung ist damit trotzdem fertig und gehoert in den Chat.
    Gleiche Kante wie bei marktanalyse (server.py, Report-Schreibfehler)."""
    lead = _lead()

    def _kaputt(*_a, **_kw):
        raise OSError("Read-only file system")

    monkeypatch.setattr(recherche, "report_schreiben", _kaputt)
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    assert "Max Bestand" in antwort["text"]
    assert antwort.get("pfad") is None
    assert "reports" in antwort["fehler"]
    # Protokolliert wird trotzdem — die Uebergabe hat stattgefunden.
    assert server._q("select count(*) as n from activities "
                     "where type='uebergabe'")[0]["n"] == 1


def test_uebergabe_versendet_nichts():
    """Gate-Invariante: die Uebergabe erzeugt keinen Entwurf und aendert
    keinen — weitergegeben wird sie vom Betreiber, nicht vom Werkzeug."""
    lead = _lead()
    server._q("insert into drafts (lead_id, channel, recipient, body, status) "
              "values (%s,'whatsapp','+491701234567','x','pending')", (lead,))
    server.uebergabe_erstellen(str(lead))
    zeilen = server._q("select status, count(*) as n from drafts group by status")
    assert [(z["status"], z["n"]) for z in zeilen] == [("pending", 1)]


def test_signatur_ueberlebt_den_dekorator_und_werkzeug_ist_registriert():
    import inspect
    assert list(inspect.signature(server.uebergabe_erstellen).parameters) == [
        "lead_id"]
    assert server.uebergabe_erstellen in server.WERKZEUGE


# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Abschluss-Review (Befunde B5, B6, B10)
# ---------------------------------------------------------------------------

def test_fehlgeformtes_enrichment_bricht_die_uebergabe_nicht():
    """B5: derselbe Fremddatenknoten, den vertraege_ablaufend absichert,
    darf auch hier keinen Traceback ausloesen — String statt Objekt,
    Array mit Nicht-Objekten, alles nur leere Abschnitte."""
    lead = _lead()
    server._q("update leads set enrichment = %s::jsonb where id = %s "
              "returning id",
              ('{"profil": "kaputt", "bedarf": 42, '
               '"vertraege": ["nur-string", 7]}', lead))
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    assert "text" in antwort
    assert "- (leer)" in antwort["text"]
    assert "- (keine genannt)" in antwort["text"]


def test_zweite_uebergabe_meldet_das_ueberschreiben():
    """B6: die Uebergabe ist nicht identisch rekonstruierbar (Aktivitaeten
    gedeckelt, Profil ueberschreibt in-place) — ein Overwrite am selben Tag
    muss gemeldet werden, wie report_schreiben es zusagt."""
    lead = _lead()
    erste = json.loads(server.uebergabe_erstellen(str(lead)))
    assert erste["ueberschrieben"] is False
    zweite = json.loads(server.uebergabe_erstellen(str(lead)))
    assert zweite["ueberschrieben"] is True


def test_bedarf_zeile_traegt_den_fragetext_nicht_die_id():
    """B10: die Beraterin liest den Fragetext aus dem Leitfaden — eine
    interne frage_id sagt einem Menschen nichts. Unbekannte ids fallen auf
    die id zurueck."""
    fragetext = server.ALLE_FRAGEN["netto"]["frage"]
    zeile = server._bedarf_zeile("netto", {"antwort": "3800"})
    assert fragetext in zeile and "3800" in zeile
    assert server._bedarf_zeile("erfundene_id", "x") == "- erfundene_id: x"
