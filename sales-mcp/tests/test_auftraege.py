"""Vertragstests fuer den Auftrags-Spool (Update per Bot-Anfrage).

Betreiber am 27.08.2026: "update ueber mich bzw bot anfragen" — der Bot darf
ein Update ANFORDERN, nie ausfuehren. Das Werkzeug schreibt eine
Auftragsdatei in einen Spool; ein Waechter auf dem WIRT (systemd-path-Unit,
deploy/auftrag-ausfuehren.sh) prueft und fuehrt aus. Der Bot fasst nie
selbst git oder docker an.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Ein Auftrag ist eine Datei, kein Befehl. Das Werkzeug hat keinerlei
   Ausfuehrungsmacht — was es schreiben kann, bestimmt allein der Waechter
   auf dem Wirt (und der kennt nur bekannte Typen).
2. Hoechstens ein Auftrag zur Zeit, hoechstens einer alle zehn Minuten.
   Ein Chat-Missverstaendnis darf keine Update-Schleife treten.
3. Ergebnisse werden ehrlich berichtet: kein Ergebnis heisst "keins da",
   kaputtes JSON heisst "kaputt" — niemals Traceback, niemals Erfindung.
"""
import json
import os
import time

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("AUFTRAG_SPOOL", str(tmp_path))
    return tmp_path


def _auftraege(spool):
    return sorted(spool.glob("auftrag-*.json"))


# ---------------------------------------------------------------------------
# Anfordern — eine Datei, ein Vertrag
# ---------------------------------------------------------------------------

def test_der_auftrag_wird_als_datei_mit_vertrag_geschrieben(spool):
    antwort = json.loads(server.update_anfordern())
    assert "fehler" not in antwort
    dateien = _auftraege(spool)
    assert len(dateien) == 1
    inhalt = json.loads(dateien[0].read_text(encoding="utf-8"))
    assert inhalt["typ"] == "update"
    assert inhalt["zeitpunkt"]
    assert antwort["auftrag"] == dateien[0].name


def test_ein_wartender_auftrag_blockiert_den_naechsten(spool):
    server.update_anfordern()
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "wartet bereits" in antwort["fehler"]
    assert len(_auftraege(spool)) == 1


def test_kurz_nach_einem_ergebnis_wird_nicht_erneut_bestellt(spool):
    (spool / "ergebnis-update-20260827-010000.json").write_text(
        json.dumps({"typ": "update", "ergebnis": "eingespielt"}),
        encoding="utf-8")
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "Minuten" in antwort["fehler"]
    assert _auftraege(spool) == []


def test_nach_ablauf_der_sperre_geht_es_wieder(spool):
    alt = spool / "ergebnis-update-20260827-010000.json"
    alt.write_text(json.dumps({"typ": "update", "ergebnis": "eingespielt"}),
                   encoding="utf-8")
    vor_elf_minuten = time.time() - 660
    os.utime(alt, (vor_elf_minuten, vor_elf_minuten))
    antwort = json.loads(server.update_anfordern())
    assert "fehler" not in antwort
    assert len(_auftraege(spool)) == 1


def test_fehlender_spool_ist_eine_meldung_kein_absturz(monkeypatch):
    monkeypatch.setenv("AUFTRAG_SPOOL", "/gibt/es/nicht")
    antwort = json.loads(server.update_anfordern())
    assert "fehler" in antwort
    assert "Spool" in antwort["fehler"]


# ---------------------------------------------------------------------------
# Ergebnis lesen — ehrlich oder gar nicht
# ---------------------------------------------------------------------------

def test_ohne_ergebnis_sagt_es_das(spool):
    antwort = json.loads(server.update_ergebnis())
    assert antwort["ergebnis"] is None
    assert antwort["auftrag_wartet"] is False


def test_das_juengste_ergebnis_gewinnt(spool):
    (spool / "ergebnis-update-20260827-010000.json").write_text(
        json.dumps({"ergebnis": "rollback"}), encoding="utf-8")
    (spool / "ergebnis-update-20260827-020000.json").write_text(
        json.dumps({"ergebnis": "eingespielt"}), encoding="utf-8")
    antwort = json.loads(server.update_ergebnis())
    assert antwort["ergebnis"]["ergebnis"] == "eingespielt"


def test_ein_wartender_auftrag_wird_mitgemeldet(spool):
    server.update_anfordern()
    antwort = json.loads(server.update_ergebnis())
    assert antwort["auftrag_wartet"] is True


def test_kaputtes_ergebnis_json_stuerzt_nicht_ab(spool):
    (spool / "ergebnis-update-20260827-030000.json").write_text(
        "{kein json", encoding="utf-8")
    antwort = json.loads(server.update_ergebnis())
    assert "fehler" in antwort
    assert "lesbar" in antwort["fehler"]


# ---------------------------------------------------------------------------
# LinkedIn-Versand per Anfrage (27.08.2026, "mach das ."): das zweite Tor
# des Einmal-Versenders — der bewusste Start — oeffnet der Betreiber per
# Chat. Bestellt wird nur, was in der Oberflaeche FREIGEGEBEN wurde.
# ---------------------------------------------------------------------------

@pytest.fixture
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _li_entwurf(status="approved", betreff="Post: Probe"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "('LinkedIn Selbst', null, 'linkedin') returning id")[0]["id"])
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "status) values (%s, 'linkedin', 'eigenes-profil', %s, 'Text.', %s) "
        "returning id", (lead, betreff, status))[0]["id"])


def test_ohne_freigegebenen_entwurf_wird_nichts_bestellt(spool, saubere_tabellen):
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert "fehler" in antwort
    assert "Kein freigegebener" in antwort["fehler"]
    assert _auftraege(spool) == []


def test_der_einzige_freigegebene_wird_bestellt(spool, saubere_tabellen):
    kennung = _li_entwurf()
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert antwort["draft_id"] == kennung
    dateien = sorted(spool.glob("auftrag-linkedin-*.json"))
    assert len(dateien) == 1
    inhalt = json.loads(dateien[0].read_text(encoding="utf-8"))
    assert inhalt["typ"] == "linkedin"
    assert inhalt["draft_id"] == kennung


def test_bei_mehreren_muss_die_kennung_genannt_werden(spool, saubere_tabellen):
    a = _li_entwurf(betreff="Post: A")
    _li_entwurf(betreff="Post: B")
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert "fehler" in antwort
    assert len(antwort["freigegeben"]) == 2
    assert _auftraege(spool) == []
    gezielt = json.loads(server.linkedin_versand_anfordern(a))
    assert gezielt["draft_id"] == a


def test_nur_approved_wird_bestellt(spool, saubere_tabellen):
    kennung = _li_entwurf(status="pending")
    antwort = json.loads(server.linkedin_versand_anfordern(kennung))
    assert "fehler" in antwort
    assert "approved" in antwort["fehler"]
    assert _auftraege(spool) == []


def test_ein_update_auftrag_blockiert_den_versand_nicht(spool, saubere_tabellen):
    """Getrennte Spuren: die Auftragsarten duerfen einander nie sperren
    oder ueberdecken."""
    _li_entwurf()
    server.update_anfordern()
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert "fehler" not in antwort
    zweiter = json.loads(server.linkedin_versand_anfordern())
    assert "wartet bereits" in zweiter["fehler"]


def test_ein_beitrag_pro_tag_haelt_die_kadenz(spool, saubere_tabellen):
    """Betreiber 27.08.2026: die Serie ist pro Tag angesiedelt, um das
    Marketing ins Rollen zu bekommen — der zweite am selben Tag braucht
    ein ausdrueckliches trotzdem."""
    kennung = _li_entwurf()
    lead = server._q("select lead_id from drafts where id = %s",
                     (kennung,))[0]["lead_id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'versand', %s) returning id",
        (lead, server._json({"kanal": "linkedin", "beitrag": "urn:li:x"})))
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert "fehler" in antwort
    assert "pro Tag" in antwort["fehler"]
    assert sorted(spool.glob("auftrag-linkedin-*.json")) == []
    erzwungen = json.loads(server.linkedin_versand_anfordern(trotzdem=True))
    assert "fehler" not in erzwungen


def test_gestriger_versand_blockiert_heute_nicht(spool, saubere_tabellen):
    kennung = _li_entwurf()
    lead = server._q("select lead_id from drafts where id = %s",
                     (kennung,))[0]["lead_id"]
    server._q(
        "insert into activities (lead_id, type, payload, created_at) values "
        "(%s, 'versand', %s, now() - interval '1 day') returning id",
        (lead, server._json({"kanal": "linkedin", "beitrag": "urn:li:y"})))
    antwort = json.loads(server.linkedin_versand_anfordern())
    assert "fehler" not in antwort


def test_die_ergebnisleser_sehen_nur_ihre_spur(spool):
    (spool / "ergebnis-update-20260827-040000.json").write_text(
        json.dumps({"ergebnis": "eingespielt"}), encoding="utf-8")
    (spool / "ergebnis-linkedin-20260827-050000.json").write_text(
        json.dumps({"ergebnis": "veroeffentlicht"}), encoding="utf-8")
    update = json.loads(server.update_ergebnis())
    linkedin = json.loads(server.linkedin_versand_ergebnis())
    assert update["ergebnis"]["ergebnis"] == "eingespielt"
    assert linkedin["ergebnis"]["ergebnis"] == "veroeffentlicht"
