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
    assert list(parameter) == ["thema", "text", "medien_datei"]
    assert parameter["medien_datei"].default == ""
    assert server.post_entwurf_erstellen in server.WERKZEUGE
