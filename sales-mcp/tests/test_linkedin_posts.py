"""Vertragstests fuer LinkedIn-Post-Entwuerfe (Stufe 6) gegen sales_test.

Ein Post ist ein linkedin-Entwurf ohne Empfaenger-Person: recipient
'eigenes-profil', Betreff 'Post: <thema>', Lead = Sammelkontakt
"LINKEDIN (Eigenes Profil)". Er nimmt denselben Weg wie jede
LinkedIn-Nachricht — pending -> Freigabe -> Handversand -> quittiert —,
und der Dispatcher fasst ihn nie an (der zieht nur channel='whatsapp').
"""
import json
import os

import pytest

# HART, nicht setdefault (T5a): eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die autouse-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import medien  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    """Zweiter Riegel: was oben gesetzt wurde, muss auch angekommen sein."""
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def sammelkontakt(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    sammel = server._q(
        "insert into leads (name, source) values "
        "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(sammel))
    return str(sammel)


def _post(**kw):
    return json.loads(server.post_entwurf_erstellen(**kw))


def test_post_entsteht_pending_am_sammelkontakt(sammelkontakt):
    antwort = _post(thema="bAV im Handwerk", text="Drei Fragen an jeden "
                    "Betriebsinhaber zur betrieblichen Altersvorsorge …")
    assert antwort["status"] == "pending"
    zeile = server._q("select lead_id, channel, recipient, subject, status "
                      "from drafts where id = %s", (antwort["draft_id"],))[0]
    assert str(zeile["lead_id"]) == sammelkontakt
    assert zeile["channel"] == "linkedin"
    assert zeile["recipient"] == "eigenes-profil"
    assert zeile["subject"] == "Post: bAV im Handwerk"
    assert zeile["status"] == "pending"


def test_leeres_thema_oder_leerer_text_ergibt_keinen_entwurf():
    assert "fehler" in _post(thema="   ", text="Inhalt")
    assert "fehler" in _post(thema="Karriere", text="  ")
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0


def test_ueber_3000_zeichen_wird_beim_erstellen_abgelehnt():
    antwort = _post(thema="Karriere", text="x" * 3001)
    assert "3000" in antwort["fehler"]
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0


def test_ohne_sammelkontakt_klare_ansage_statt_verwaister_zeile(monkeypatch):
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    antwort = _post(thema="Karriere", text="Wir suchen Vertriebspartner.")
    assert "LINKEDIN_POST_LEAD_ID" in antwort["fehler"]
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0


def test_medien_merkposten_laeuft_durch_dieselbe_pruefung(tmp_path, monkeypatch):
    ordner = tmp_path / "media"
    ordner.mkdir()
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(ordner))
    (ordner / "grafik.png").write_bytes(b"\x89PNG-daten")

    assert "fehler" in _post(thema="Karriere", text="T", medien_datei="../raus.png")
    assert "fehler" in _post(thema="Karriere", text="T", medien_datei="fehlt.png")
    assert server._q("select count(*) as n from drafts")[0]["n"] == 0

    antwort = _post(thema="Karriere", text="Wir wachsen in Regensburg.",
                    medien_datei="grafik.png")
    assert antwort["medien_datei"] == "grafik.png"


def test_voller_weg_freigeben_von_hand_posten_quittieren():
    draft_id = _post(thema="Karriere",
                     text="Quereinstieg in den Vertrieb — so lief mein "
                          "erstes Jahr.")["draft_id"]
    # Vor der Freigabe sichtbar, als Post erkennbar.
    offen = json.loads(server.entwuerfe_offen())["entwuerfe"]
    assert [e for e in offen if e["draft_id"] == draft_id
            and e["empfaenger"] == "eigenes-profil"]
    assert json.loads(server.entwurf_freigeben(draft_id))["status"] == "approved"
    # Nach der Freigabe wartet er weiter auf den Handversand — und fuer den
    # Dispatcher existiert er nicht (der zieht nur channel='whatsapp').
    assert [e for e in json.loads(server.entwuerfe_offen())["entwuerfe"]
            if e["draft_id"] == draft_id and e["status"] == "approved"]
    assert server._q("select count(*) as n from drafts where "
                     "status='approved' and channel='whatsapp'")[0]["n"] == 0
    assert json.loads(server.entwurf_manuell_gesendet(draft_id))["status"] == "sent"
    versand = server._q("select payload from activities where type='versand'")
    assert len(versand) == 1 and versand[0]["payload"]["weg"] == "manuell"


def test_signatur_ueberlebt_den_dekorator():
    """Ohne functools.wraps waere das MCP-Schema leer (Task-4-Vorfall)."""
    import inspect
    parameter = inspect.signature(server.post_entwurf_erstellen).parameters
    assert list(parameter) == ["thema", "text", "medien_datei",
                               "trotzdem"]
    assert parameter["medien_datei"].default == ""
    assert server.post_entwurf_erstellen in server.WERKZEUGE


# ---------------------------------------------------------------------------
# Historie und Redundanz (Betreiber-Wunsch 25.08.2026)
#
# „post history von linkedin damit wir nicht redunate posts erzeugen und einen
#  eigenen stil entwicklen koennen pro post."
#
# GEMESSEN: LinkedIn gibt die Historie NICHT heraus — die App hat
# `w_member_social` (schreiben), aber keine Leseberechtigung; GET auf
# /rest/posts antwortet mit 403 ACCESS_DENIED. Gebraucht wird sie dort auch
# nicht: was ueber dieses System entstand, steht in `drafts`.
# ---------------------------------------------------------------------------

def test_historie_zeigt_die_eigenen_beitraege(sammelkontakt):
    _post(thema="Erstes Thema", text="Ein Beitrag ueber das erste Thema.")
    _post(thema="Zweites Thema", text="Ein Beitrag ueber das zweite Thema.")
    h = json.loads(server.linkedin_historie())
    assert h["anzahl"] == 2
    themen = {b["thema"] for b in h["beitraege"]}
    assert themen == {"Erstes Thema", "Zweites Thema"}
    assert all(b["status"] == "pending" for b in h["beitraege"])


def test_historie_nennt_die_erste_zeile(sammelkontakt):
    _post(thema="Haken", text="Die Frage vorweg?\nDann der Rumpf des Textes.")
    b = json.loads(server.linkedin_historie())["beitraege"][0]
    assert b["erste_zeile"] == "Die Frage vorweg?"


def test_historie_aendert_nichts(sammelkontakt):
    _post(thema="Thema", text="Text.")
    vorher = server._q("select count(*) n from drafts")[0]["n"]
    server.linkedin_historie()
    assert server._q("select count(*) n from drafts")[0]["n"] == vorher


# --- Der Schablonen-Melder --------------------------------------------------

SCHABLONE = ("In VibeMind, meinem quelloffenen KI-Betriebssystem, "
             "erkennt Brain die Absicht und leitet weiter. ")


def test_wiederholte_wendung_wird_gemeldet(sammelkontakt):
    _post(thema="Alpha", text=SCHABLONE + "Alpha macht das eine.")
    _post(thema="Beta", text=SCHABLONE + "Beta macht das andere.")
    bausteine = json.loads(server.linkedin_historie())["bausteine"]
    assert bausteine, "die gemeinsame Wendung wurde nicht gefunden"
    treffer = bausteine[0]
    assert treffer["anzahl"] == 2
    assert sorted(treffer["in_beitraegen"]) == ["Alpha", "Beta"]
    assert "erkennt brain die absicht" in treffer["wortfolge"]


def test_ueberlappende_funde_werden_zusammengezogen(sammelkontakt):
    """Sonst steht dieselbe Fundstelle ein Dutzend Mal, um ein Wort
    verschoben — ein Melder, der unlesbarer ist als das Problem."""
    lang = ("Eine sehr lange gemeinsame Wendung die in beiden Texten "
            "vollkommen wortgleich enthalten ist. ")
    _post(thema="Eins", text=lang + "Danach etwas Eigenes.")
    _post(thema="Zwei", text=lang + "Und hier etwas anderes.")
    bausteine = json.loads(server.linkedin_historie())["bausteine"]
    # EINE Fundstelle, nicht viele Verschiebungen davon.
    assert len(bausteine) == 1
    assert len(bausteine[0]["wortfolge"].split()) >= 12


def test_verschiedene_texte_melden_nichts(sammelkontakt):
    _post(thema="Eins", text="Ein vollkommen eigener Text ueber Aepfel.")
    _post(thema="Zwei", text="Etwas ganz anderes zum Thema Birnen heute.")
    assert json.loads(server.linkedin_historie())["bausteine"] == []


# --- Kein zweiter Beitrag zum selben Thema ----------------------------------

def test_gleiches_thema_wird_abgelehnt(sammelkontakt):
    _post(thema="VibeMind Laura", text="Der erste Beitrag dazu.")
    antwort = json.loads(server.post_entwurf_erstellen(
        "VibeMind Laura", "Noch ein Beitrag dazu."))
    assert "fehler" in antwort
    assert "schon einen Beitrag" in antwort["fehler"]
    assert server._q("select count(*) n from drafts")[0]["n"] == 1


def test_gross_klein_zaehlt_als_dasselbe_thema(sammelkontakt):
    _post(thema="VibeMind Laura", text="Der erste Beitrag dazu.")
    antwort = json.loads(server.post_entwurf_erstellen(
        "vibemind laura", "Noch einer."))
    assert "fehler" in antwort


def test_mit_trotzdem_geht_es_doch(sammelkontakt):
    """Eine Fortsetzung ist ein gueltiger Grund — sie soll nur bewusst sein."""
    _post(thema="VibeMind Laura", text="Der erste Beitrag dazu.")
    antwort = json.loads(server.post_entwurf_erstellen(
        "VibeMind Laura", "Teil zwei, anderer Blickwinkel.", trotzdem=True))
    assert "fehler" not in antwort
    assert server._q("select count(*) n from drafts")[0]["n"] == 2


def test_abgelehnter_beitrag_blockiert_nicht(sammelkontakt):
    """Verworfen heisst: der zweite Anlauf ist genau das Richtige."""
    erst = _post(thema="VibeMind Laura", text="Erster Versuch.")
    server._q("update drafts set status = 'rejected' where id = %s",
              (erst["draft_id"],))
    antwort = json.loads(server.post_entwurf_erstellen(
        "VibeMind Laura", "Zweiter Versuch, besser."))
    assert "fehler" not in antwort


def test_anderes_thema_geht_ohne_weiteres(sammelkontakt):
    _post(thema="VibeMind Laura", text="Der erste Beitrag.")
    antwort = json.loads(server.post_entwurf_erstellen(
        "VibeMind Rowboat", "Ein anderer Beitrag."))
    assert "fehler" not in antwort
