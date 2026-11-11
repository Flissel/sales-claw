"""Meldungen an den Betreiber: auftrag_meldung + Werkzeug auftraege_melden.

Das Schema `auftrag` existiert in keiner Test-DB: auftrag_buch wird im Speicher nachgebaut.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

import auftrag_buch  # noqa: E402
import auftrag_meldung  # noqa: E402
import server  # noqa: E402

AID = "0123abcd-0000-4000-8000-000000000001"
THEMA = "Drei Fehler bei der bAV"


class Speicher:
    """Mini-Auftragsbuch: Zeilen wie sales_eigene sie liefert; ergebnis_mischen nur bis zum Endstand."""

    def __init__(self, monkeypatch, *zeilen):
        self.zeilen = list(zeilen)
        self.laden = None
        monkeypatch.setattr(auftrag_buch, "eigene", self.eigene)
        monkeypatch.setattr(auftrag_buch, "gemeldet", self.gemeldet)
        monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", self.mischen)

    def eigene(self, q, laden, staende):
        self.laden = laden
        return [json.loads(json.dumps(z)) for z in self.zeilen if z["stand"] in staende]

    def _zeile(self, aid):
        return next(z for z in self.zeilen if z["id"] == aid)

    def gemeldet(self, q, aid, stand):
        z = self._zeile(aid)
        if z["stand"] != stand:
            return False
        z["gemeldet_stand"] = stand
        return True

    def mischen(self, q, aid, teil):
        z = self._zeile(aid)
        if z["stand"] not in ("in_arbeit", "erzeugt", "wartet_freigabe"):
            return False
        z["ergebnis"] = {**z.get("ergebnis", {}), **teil}
        return True


def auftrag(stand, **rest):
    return {"id": AID, "stand": stand, "gemeldet_stand": None, "erinnert_am": None, "fehler": None,
            "eingabe": {"thema": THEMA, "kanaele": ["mastodon", "discord"]}, "ergebnis": {}, **rest}


def melden():
    return auftrag_meldung.melden(None, "sales", None)


def test_fertig_meldet_links_einmal(monkeypatch):
    Speicher(monkeypatch, auftrag("fertig", ergebnis={"beitraege": {"mastodon": "https://m.example/1",
                                                                     "linkedin": "privat"}}))
    erste = melden()
    assert len(erste) == 1
    assert erste[0].startswith(f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) ist online: ")
    assert "mastodon: https://m.example/1" in erste[0] and "linkedin: privat" in erste[0]
    assert melden() == []


def test_links_bleiben_unveraendert(monkeypatch):
    mastodon = "https://mastodon.social/@vibemind/113456789012345678"
    youtube = "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share&t=1234567890123"
    Speicher(monkeypatch, auftrag("fertig", ergebnis={"beitraege": {"mastodon": mastodon, "youtube": youtube}}))
    text = melden()[0]
    assert f"mastodon: {mastodon}; youtube: {youtube}" in text
    assert "[Adresse]" not in text and "[Nummer]" not in text


def test_viele_kanaele_lassen_ganze_eintraege_weg_nie_einen_link_kuerzen(monkeypatch):
    lang = "https://example.org/" + "a" * 500
    beitraege = {f"k{i}": f"{lang}{i}" for i in range(10)}
    Speicher(monkeypatch, auftrag("fertig", ergebnis={"beitraege": beitraege}))
    text = melden()[0]
    assert f"k7: {lang}7" in text and "k8:" not in text and text.endswith("… und 2 weitere")


def test_thema_mit_nummer_und_adresse_wird_gesaeubert(monkeypatch):
    z = auftrag("abgelaufen", eingabe={"thema": "Rueckruf +49 170 1234567 oder anna@example.com", "kanaele": []})
    Speicher(monkeypatch, z)
    text = melden()[0]
    assert "1234567" not in text and "anna@example.com" not in text and "Rueckruf" in text


def test_nichts_ging_raus_nur_wenn_nichts_gesendet_wurde(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))
    assert melden()[0].endswith("wurde verworfen, nichts ging raus.")
    Speicher(monkeypatch, auftrag("abgebrochen", ergebnis={"beitraege": {"mastodon": "https://m.example/1"}}))
    assert "nichts ging raus" not in melden()[0]
    Speicher(monkeypatch, auftrag("abgebrochen", ergebnis={"kanal_fehler": {"discord": "Der Versand ist fehlgeschlagen."}}))
    text = melden()[0]
    assert "nichts ging raus" not in text and "discord ging nicht raus" in text


def test_abgelaufen_wird_genau_einmal_gemeldet(monkeypatch):
    Speicher(monkeypatch, auftrag("abgelaufen"))
    assert melden() == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) ist nicht rechtzeitig fertig geworden (PC aus?)."]
    assert melden() == []


def test_verworfen_und_gescheitert(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))
    assert melden()[0].endswith("wurde verworfen, nichts ging raus.")
    Speicher(monkeypatch, auftrag("fehler", fehler="Das Reel-Werkzeug war nicht erreichbar."))
    assert melden()[0].endswith("ist gescheitert: Das Reel-Werkzeug war nicht erreichbar.")


def test_fehler_nennt_grund_ohne_personendaten(monkeypatch):
    z = auftrag("fehler", fehler="Absage an anna@example.com und +49 170 1234567 kam zurueck",
                eingabe={"thema": THEMA, "kanaele": [], "empfaenger": "+491701234567",
                         "mail": "anna@example.com"})
    Speicher(monkeypatch, z)
    text = melden()[0]
    assert "Absage" in text
    for roh in ("491701234567", "1234567", "anna@example.com", "@"):
        assert roh not in text


def test_offene_auftraege_melden_nichts(monkeypatch):
    Speicher(monkeypatch, auftrag("angenommen"), auftrag("in_arbeit"), auftrag("erzeugt"), auftrag("wartet_freigabe"))
    assert melden() == []


def test_erinnerung_einmal(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("wartet_freigabe", erinnert_am="2026-11-10T10:00:00+00:00"))
    assert melden() == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}) wartet seit 2 Tagen auf deine Freigabe."]
    assert melden() == []
    sp.zeilen[0]["stand"] = "fertig"          # der Endstand kommt trotzdem noch einmal
    sp.zeilen[0]["ergebnis"]["beitraege"] = {"mastodon": "https://m.example/1"}
    assert len(melden()) == 1 and melden() == []


def test_kanalfehler_einmal_solange_er_wartet(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("wartet_freigabe",
                                       ergebnis={"kanal_fehler": {"discord": "Der Versand ist fehlgeschlagen."}}))
    zeilen = melden()
    assert zeilen == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}): discord ging nicht raus: "
                      "Der Versand ist fehlgeschlagen. Bitte in /freigaben ansehen."]
    assert melden() == []
    assert sp.zeilen[0]["ergebnis"]["kanal_fehler_gemeldet"] == ["discord"]


def test_endmeldung_nennt_noch_nicht_gemeldete_kanalfehler(monkeypatch):
    Speicher(monkeypatch, auftrag("fertig", ergebnis={
        "beitraege": {"mastodon": "https://m.example/1", "bluesky": "https://b.example/2"},
        "kanal_fehler": {"discord": "Der Versand hängt seit über 30 Minuten.",
                         "bluesky": "Der Versand ist fehlgeschlagen.",   # spaeter doch gepostet
                         "x": "Der Kanal ist nicht verbunden."},
        "kanal_fehler_gemeldet": ["x"]}))
    text = melden()[0]
    assert "discord ging nicht raus: Der Versand hängt" in text
    assert "bluesky ging nicht raus" not in text and "x ging nicht raus" not in text
    assert melden() == []


def test_markieren_scheitert_keine_wiederholung(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("abgelaufen"))
    monkeypatch.setattr(auftrag_buch, "gemeldet", lambda q, aid, stand: False)
    assert melden() == []
    sp.zeilen[0]["stand"] = "wartet_freigabe"
    sp.zeilen[0]["erinnert_am"] = "x"
    monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", lambda q, aid, teil: False)
    assert melden() == []


def test_faellige_markiert_nichts(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))
    erste = auftrag_meldung.faellige(None, "sales", None)
    assert erste == auftrag_meldung.faellige(None, "sales", None)
    assert erste[0][:2] == (AID, "abgebrochen") and len(erste[0]) == 3


def test_werkzeug_liefert_meldungen_json_mit_laden(monkeypatch):
    sp = Speicher(monkeypatch, auftrag("abgebrochen"))
    monkeypatch.setenv("LADEN_PRAEFIX", "ivan")
    r = json.loads(server.auftraege_melden())
    assert len(r["meldungen"]) == 1 and sp.laden == "ivan"
    assert json.loads(server.auftraege_melden()) == {"meldungen": []}
    assert server.auftraege_melden in server.WERKZEUGE


def test_cron_postfach_check_ruft_auftraege_melden_auf_antworten_pruefen_nicht():
    from pathlib import Path
    cron = Path(__file__).resolve().parents[2] / "deploy" / "cron"
    if not (cron / "postfach-check.json").exists():  # im Container-Image liegt deploy/ nicht
        pytest.skip("deploy/cron nicht im Image")
    pf = json.loads((cron / "postfach-check.json").read_text(encoding="utf-8"))
    assert pf["enabled"] is True and pf["delivery"]["mode"] == "announce"
    assert pf["delivery"]["to"] == "${MELDE_AN}"
    assert "auftraege_melden()" in pf["payload"]["message"]
    alt = json.loads((cron / "antworten-pruefen.json").read_text(encoding="utf-8"))
    assert "auftraege_melden" not in alt["payload"]["message"]


def test_zweiter_aufruf_bei_gehaltener_sperre_liefert_nichts(monkeypatch):
    """Echte Advisory-Sperre in sales_test: solange eine andere Sitzung sie haelt, kommt nichts."""
    Speicher(monkeypatch, auftrag("abgebrochen"))
    schluessel = f"{server.SCHEMA}:{auftrag_meldung.SPERRE}"
    with server.pool.connection() as fremd:
        fremd.execute("select pg_advisory_lock(hashtext(%s))", (schluessel,))
        try:
            assert json.loads(server.auftraege_melden()) == {"meldungen": []}
        finally:
            fremd.execute("select pg_advisory_unlock(hashtext(%s))", (schluessel,))
    assert len(json.loads(server.auftraege_melden())["meldungen"]) == 1      # Sperre war frei und wurde nicht verbraucht
    assert json.loads(server.auftraege_melden()) == {"meldungen": []}


def test_sperre_wird_auch_bei_fehler_freigegeben(monkeypatch):
    Speicher(monkeypatch, auftrag("abgebrochen"))

    def kaputt(q, laden, jetzt=None):
        raise RuntimeError("x")
    monkeypatch.setattr(auftrag_meldung, "melden", kaputt)
    with pytest.raises(RuntimeError):
        auftrag_meldung.melden_gesperrt(server.pool, None, "sales", server.SCHEMA)
    monkeypatch.undo()
    schluessel = f"{server.SCHEMA}:{auftrag_meldung.SPERRE}"
    with server.pool.connection() as c:
        assert c.execute("select pg_try_advisory_lock(hashtext(%s)) as ok", (schluessel,)).fetchone()["ok"]
        c.execute("select pg_advisory_unlock(hashtext(%s))", (schluessel,))


def test_fremdes_schema_meldet_nichts_ohne_db(monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    monkeypatch.setattr(auftrag_buch, "eigene", lambda *a, **k: pytest.fail("kein DB-Zugriff"))
    assert json.loads(server.auftraege_melden()) == {"meldungen": []}


def test_ungewisser_versand_wird_nicht_als_nichts_raus_gemeldet(monkeypatch):
    sat = auftrag_buch.VERSAND_UNGEWISS
    Speicher(monkeypatch, auftrag("abgebrochen", ergebnis={"kanal_fehler": {"discord": sat}},
                                  ))
    text = melden()[0]
    assert "nichts ging raus" not in text and sat in text and "discord ging nicht raus" not in text
    Speicher(monkeypatch, auftrag("wartet_freigabe", ergebnis={"kanal_fehler": {"discord": sat}}))
    assert melden() == [f"Reel ‚{THEMA}‘ (Nr. {AID[:8]}): discord: {sat}"]
    # auch wenn der Fehler schon gemeldet wurde, sagt der Endtext nicht "nichts ging raus"
    Speicher(monkeypatch, auftrag("abgebrochen", ergebnis={"kanal_fehler": {"discord": sat},
                                                            "kanal_fehler_gemeldet": ["discord"]}))
    assert "nichts ging raus" not in melden()[0]


# --- Video (Video-Werkbank): Zwischenstaende, Erinnerung, Hinweise, Freigabe, Download ---------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

JETZT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
BASIS = "https://laden.example"
KOPF = f"Video ‚{THEMA}‘ (Nr. {AID[:8]})"
GEHEIM = "GEHEIMWORT-aus-der-Beschreibung des Betreibers"


class Buch(Speicher):
    """Wie Speicher, aber ergebnis_mischen gilt auch im Stand werkbank (Migration 098); `ausfall` laesst das
    Markieren bestimmter Zeilen scheitern, `schreibt` haelt jede geschriebene Markierung fest."""

    def __init__(self, monkeypatch, *zeilen):
        super().__init__(monkeypatch, *zeilen)
        self.schreibt = []
        self.ausfall = None            # Funktion(teil) -> True = dieses Markieren wirft

    def mischen(self, q, aid, teil):
        z = self._zeile(aid)
        if z["stand"] not in ("in_arbeit", "erzeugt", "wartet_freigabe", "werkbank"):
            return False
        if self.ausfall and self.ausfall(teil):
            raise RuntimeError("Datenbank weg")
        self.schreibt.append(json.loads(json.dumps(teil)))
        z["ergebnis"] = {**z.get("ergebnis", {}), **json.loads(json.dumps(teil))}
        return True

    def setze_werkbank(self, **felder):
        z = self.zeilen[0]
        z["ergebnis"]["werkbank"] = {**z["ergebnis"].get("werkbank", {}), **felder}

    def marke(self):
        return self.zeilen[0]["ergebnis"].get("werkbank_gemeldet")


@pytest.fixture(autouse=True)
def basis(monkeypatch):
    monkeypatch.setenv("UI_BASIS_URL", BASIS + "/")


def video(stand, **rest):
    rest.setdefault("eingabe", {"thema": THEMA, "beschreibung": GEHEIM, "minuten": 4,
                                "zielgruppe": "Entscheider 34+, die eine Schulung suchen"})
    return auftrag(stand, art="video", **rest)


def melden_um(jetzt=JETZT):
    return auftrag_meldung.melden(None, "sales", jetzt)


def test_zwischenstand_einmal_je_runde(monkeypatch):
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 8, "wartet_tor": "text", "runde": 2}}))
    assert melden_um() == [f"{KOPF}: 8 Szenentexte warten in Rowboat auf dich."]
    assert melden_um() == []
    assert b.marke() == {"runde": 2}
    b.setze_werkbank(runde=3, wartet=4)
    assert melden_um() == [f"{KOPF}: 4 Szenentexte warten in Rowboat auf dich."]
    assert melden_um() == []
    assert b.marke() == {"runde": 3}


@pytest.mark.parametrize("tor, n, satz", [
    ("gliederung", 1, "1 Gliederung wartet in Rowboat auf dich."),
    ("text", 1, "1 Szenentext wartet in Rowboat auf dich."),
    ("text", 8, "8 Szenentexte warten in Rowboat auf dich."),
    ("clip", 3, "3 Clips warten in Rowboat auf dich."),
    ("clip", 1, "1 Clip wartet in Rowboat auf dich."),
    (None, 2, "2 Einträge warten in Rowboat auf dich."),
    ("etwas-neues", 1, "1 Eintrag wartet in Rowboat auf dich.")])
def test_zwischenstand_nennt_das_tor(monkeypatch, tor, n, satz):
    Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": n, "wartet_tor": tor, "runde": 1}}))
    assert melden_um() == [f"{KOPF}: {satz}"]


def test_nichts_wartet_nichts_gemeldet(monkeypatch):
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 0, "wartet_tor": None, "runde": 4,
                                                                   "wartet_seit": None, "hinweise": []}}))
    assert melden_um() == [] and b.schreibt == []


def test_erinnerung_nach_48h_einmal_je_wartezeit(monkeypatch):
    seit = (JETZT - timedelta(hours=47)).isoformat()
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 2, "wartet_tor": "clip", "runde": 1,
                                                                   "wartet_seit": seit}}))
    assert melden_um() == [f"{KOPF}: 2 Clips warten in Rowboat auf dich."]       # noch keine 48 h
    spaeter = JETZT + timedelta(hours=2)
    assert melden_um(spaeter) == [f"{KOPF} wartet seit 2 Tagen auf deine Abnahme in Rowboat."]
    assert melden_um(spaeter) == [] and melden_um(spaeter + timedelta(hours=30)) == []
    assert b.marke() == {"runde": 1, "erinnert": seit}
    neu = (JETZT + timedelta(hours=5)).isoformat()                                 # neue Wartezeit, wieder alt genug
    b.setze_werkbank(wartet_seit=neu, runde=2)
    assert melden_um(JETZT + timedelta(hours=60)) == [f"{KOPF}: 2 Clips warten in Rowboat auf dich.",
                                                      f"{KOPF} wartet seit 2 Tagen auf deine Abnahme in Rowboat."]
    assert melden_um(JETZT + timedelta(hours=61)) == []


def test_erinnerung_mit_unlesbarer_zeit_gibt_nur_den_zwischenstand(monkeypatch):
    Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 1, "wartet_tor": "text", "runde": 1,
                                                               "wartet_seit": "kaputt"}}))
    assert len(melden_um()) == 1


def test_hinweis_budget_genau_einmal(monkeypatch):
    satz = "Das Tagesbudget ist heute aufgebraucht. Es geht morgen weiter."
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {
        "wartet": 0, "runde": 1, "hinweise": [{"key": "budget_2026_11_11", "satz": satz}]}}))
    assert melden_um() == [f"{KOPF}: {satz}"]
    assert melden_um() == [] and b.marke() == {"hinweise": ["budget_2026_11_11"]}
    b.setze_werkbank(hinweise=[{"key": "budget_2026_11_11", "satz": satz},
                               {"key": "budget_2026_11_12", "satz": "Das Budget ist wieder knapp."}])
    assert melden_um() == [f"{KOPF}: Das Budget ist wieder knapp."]
    assert b.marke() == {"hinweise": ["budget_2026_11_11", "budget_2026_11_12"]}


def test_hinweis_wird_gesaeubert_und_doppelter_key_nur_einmal(monkeypatch):
    Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 0, "runde": 1, "hinweise": [
        {"key": "a_1", "satz": "Rueckruf an anna@example.com"}, {"key": "a_1", "satz": "noch mal"},
        {"key": "", "satz": "ohne Schluessel"}, {"key": "b_2", "satz": ""}, "kaputt"]}}))
    assert melden_um() == [f"{KOPF}: Rueckruf an [Adresse]"]


def test_szenenfehler_blockiert_keine_andere_zeile(monkeypatch):
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {
        "wartet": 3, "wartet_tor": "text", "runde": 2, "hinweise": [
            {"key": "quelle_s3_f1", "satz": "Szene 3: die Quelle liess sich nicht lesen."},
            {"key": "budget_2026_11_11", "satz": "Das Tagesbudget ist aufgebraucht."}]}}))
    b.ausfall = lambda teil: "quelle_s3_f1" in teil["werkbank_gemeldet"].get("hinweise", [])
    erste = melden_um()
    assert erste == [f"{KOPF}: 3 Szenentexte warten in Rowboat auf dich.",
                     f"{KOPF}: Das Tagesbudget ist aufgebraucht."]
    # die gescheiterte Zeile ist NICHT mitmarkiert worden und kommt beim naechsten Aufruf
    assert b.marke() == {"runde": 2, "hinweise": ["budget_2026_11_11"]}
    b.ausfall = None
    assert melden_um() == [f"{KOPF}: Szene 3: die Quelle liess sich nicht lesen."]
    assert melden_um() == []


def test_zwischenstand_scheitert_hinweis_kommt_trotzdem_und_der_zwischenstand_spaeter(monkeypatch):
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {
        "wartet": 3, "wartet_tor": "clip", "runde": 2,
        "hinweise": [{"key": "budget_2026_11_11", "satz": "Das Tagesbudget ist aufgebraucht."}]}}))
    b.ausfall = lambda teil: "runde" in teil["werkbank_gemeldet"]
    assert melden_um() == [f"{KOPF}: Das Tagesbudget ist aufgebraucht."]
    assert b.marke() == {"hinweise": ["budget_2026_11_11"]}
    b.ausfall = None
    assert melden_um() == [f"{KOPF}: 3 Clips warten in Rowboat auf dich."]
    assert b.marke() == {"hinweise": ["budget_2026_11_11"], "runde": 2}


def test_markieren_liefert_false_dann_keine_zeile_und_kein_verlust(monkeypatch):
    b = Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 1, "wartet_tor": "gliederung",
                                                                   "runde": 1}}))
    monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", lambda q, aid, teil: False)
    assert melden_um() == []
    monkeypatch.setattr(auftrag_buch, "ergebnis_mischen", b.mischen)
    assert melden_um() == [f"{KOPF}: 1 Gliederung wartet in Rowboat auf dich."]


def test_bereit_zur_freigabe_mit_link(monkeypatch):
    b = Buch(monkeypatch, video("wartet_freigabe", ergebnis={"freigabe": "fg-abcdefghij", "fassung": 1,
                                                             "werkbank": {"wartet": 0, "runde": 5}}))
    assert melden_um() == [f"{KOPF} ist fertig und wartet in /freigaben: {BASIS}/freigaben#fg-abcdefghij"]
    assert melden_um() == [] and b.marke() == {"freigabe_fassung": 1}
    b.zeilen[0]["ergebnis"].update({"freigabe": "fg-klmnopqrst", "fassung": 2})      # neue Fassung gebaut
    assert melden_um() == [f"{KOPF} ist fertig und wartet in /freigaben: {BASIS}/freigaben#fg-klmnopqrst"]
    assert melden_um() == [] and b.marke() == {"freigabe_fassung": 2}


def test_bereit_ohne_basisadresse_ohne_link(monkeypatch):
    monkeypatch.delenv("UI_BASIS_URL")
    Buch(monkeypatch, video("wartet_freigabe", ergebnis={"freigabe": "fg-abcdefghij", "fassung": 1}))
    assert melden_um() == [f"{KOPF} ist fertig und wartet in /freigaben."]


def test_wartet_freigabe_ohne_kennung_schweigt(monkeypatch):
    Buch(monkeypatch, video("wartet_freigabe", ergebnis={"fassung": 1}))
    assert melden_um() == []


def test_video_wartet_seit_2_tagen_auf_freigabe_wie_beim_reel(monkeypatch):
    Buch(monkeypatch, video("wartet_freigabe", erinnert_am="2026-11-10T10:00:00+00:00",
                            ergebnis={"freigabe": "fg-abcdefghij", "fassung": 1}))
    texte = melden_um()
    assert f"{KOPF} wartet seit 2 Tagen auf deine Freigabe." in texte
    assert melden_um() == []


def test_endstaende_des_videos(monkeypatch):
    Buch(monkeypatch, video("fertig", ergebnis={"freigabe": "fg-abcdefghij", "fassung": 1}))
    assert melden_um() == [f"{KOPF} ist freigegeben. Download: {BASIS}/marketing/werkbank/{AID}/video"]
    assert melden_um() == []
    Buch(monkeypatch, video("abgebrochen"))
    assert melden_um() == [f"{KOPF} wurde verworfen."]
    Buch(monkeypatch, video("fehler", fehler="Die Gliederung liess sich nicht schreiben."))
    assert melden_um() == [f"{KOPF} ist gescheitert: Die Gliederung liess sich nicht schreiben."]
    Buch(monkeypatch, video("abgelaufen"))
    assert melden_um() == [f"{KOPF} ist nicht rechtzeitig fertig geworden (PC aus?)."]


def test_fertig_ohne_basisadresse_ohne_link(monkeypatch):
    monkeypatch.delenv("UI_BASIS_URL")
    Buch(monkeypatch, video("fertig"))
    assert melden_um() == [f"{KOPF} ist freigegeben."]


def test_kopf_sagt_video(monkeypatch):
    Buch(monkeypatch, video("abgebrochen"))
    assert melden_um()[0].startswith("Video ‚")
    Buch(monkeypatch, auftrag("abgebrochen"))                       # ohne art: wie bisher ein Reel
    assert melden_um()[0].startswith("Reel ‚")
    Buch(monkeypatch, auftrag("abgebrochen", art="reel"))
    assert melden_um()[0].startswith("Reel ‚")


def test_thema_im_kopf_wird_gesaeubert(monkeypatch):
    Buch(monkeypatch, video("abgebrochen", eingabe={"thema": "Rueckruf +49 170 1234567 oder anna@example.com",
                                                    "beschreibung": GEHEIM}))
    text = melden_um()[0]
    assert "1234567" not in text and "anna@example.com" not in text and "Rueckruf" in text


def test_beschreibung_erscheint_nie_in_der_meldung(monkeypatch):
    zeilen = [video("werkbank", ergebnis={"werkbank": {"wartet": 2, "wartet_tor": "text", "runde": 1, "hinweise": [
                  {"key": "budget_2026_11_11", "satz": "Das Tagesbudget ist aufgebraucht."}]}}),
              video("wartet_freigabe", ergebnis={"freigabe": "fg-abcdefghij", "fassung": 1}),
              video("fertig"), video("abgebrochen"), video("fehler", fehler="kaputt"), video("abgelaufen")]
    for z in zeilen:
        Buch(monkeypatch, z)
        texte = melden_um() + melden_um(JETZT + timedelta(days=5))
        assert texte, z["stand"]
        assert not any(GEHEIM in t or "Beschreibung" in t for t in texte), z["stand"]
    Buch(monkeypatch, *zeilen)
    assert GEHEIM not in " ".join(t for _, _, t in auftrag_meldung.faellige(None, "sales", JETZT))


def test_offene_video_staende_melden_nichts(monkeypatch):
    Buch(monkeypatch, video("offen"), video("in_arbeit"), video("erzeugt"))
    assert melden_um() == []


def test_hinweis_eines_videos_in_arbeit_kommt_einmal(monkeypatch):
    """M1: die Gliederung entsteht, solange der Auftrag in_arbeit steht; ihre Hinweise kommen trotzdem."""
    satz = "Die Gliederung ließ sich nicht schreiben – bitte Wunsch ergänzen."
    b = Buch(monkeypatch, video("in_arbeit", ergebnis={"werkbank": {
        "wartet": 0, "hinweise": [{"key": "gliederung_f1", "satz": satz}]}}))
    assert melden_um() == [f"{KOPF}: {satz}"]
    assert melden_um() == [] and b.marke() == {"hinweise": ["gliederung_f1"]}


def test_video_kann_nicht_in_die_freigabe_wird_einmal_gemeldet(monkeypatch):
    """I2: der Auftrag-Bote laesst das Video in `erzeugt` und setzt ergebnis.freigabe_problem; die Meldung kommt
    einmal je Problemart, mit Marke in werkbank_gemeldet."""
    b = Buch(monkeypatch, video("erzeugt", ergebnis={"freigabe_problem": "adresse"}))
    satz = f"{KOPF} ist fertig, kann aber nicht in die Freigabe gestellt werden – bitte Einstellung prüfen."
    assert melden_um() == [satz]
    assert melden_um() == [] and b.marke() == {"freigabe_problem": "adresse"}
    b.zeilen[0]["ergebnis"]["freigabe_problem"] = "datei"            # anderes Problem: eine neue Zeile
    assert melden_um() == [satz] and melden_um() == []
    b.zeilen[0]["ergebnis"]["freigabe_problem"] = None
    assert melden_um() == []


def test_reel_in_arbeit_oder_erzeugt_meldet_weiter_nichts(monkeypatch):
    Buch(monkeypatch, auftrag("in_arbeit", ergebnis={"kanal_fehler": {"mastodon": "kaputt"},
                                                     "werkbank": {"hinweise": [{"key": "a", "satz": "b"}]}}),
         auftrag("erzeugt", ergebnis={"kanal_fehler": {"discord": "kaputt"}, "freigabe_problem": "adresse"}))
    assert melden_um() == []


def test_reel_in_der_werkbank_bekommt_keine_videozeilen(monkeypatch):
    Buch(monkeypatch, auftrag("werkbank", ergebnis={"werkbank": {"wartet": 2, "wartet_tor": "text", "runde": 1}}))
    assert melden_um() == []


def test_video_werkzeug_geht_ueber_die_sperre_und_meldet_jede_zeile_einmal(monkeypatch):
    Buch(monkeypatch, video("werkbank", ergebnis={"werkbank": {"wartet": 8, "wartet_tor": "text", "runde": 2}}))
    r = json.loads(server.auftraege_melden())
    assert r == {"meldungen": [f"{KOPF}: 8 Szenentexte warten in Rowboat auf dich."]}
    assert json.loads(server.auftraege_melden()) == {"meldungen": []}


def test_cron_postfach_check_nennt_reels_und_videos():
    from pathlib import Path
    cron = Path(__file__).resolve().parents[2] / "deploy" / "cron" / "postfach-check.json"
    if not cron.exists():  # im Container-Image liegt deploy/ nicht
        pytest.skip("deploy/cron nicht im Image")
    text = json.loads(cron.read_text(encoding="utf-8"))["payload"]["message"]
    assert "REEL- UND VIDEO-AUFTRAEGE: Rufe auftraege_melden() auf." in text
