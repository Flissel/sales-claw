"""Vertragstests von sales-kanaele gegen sales_test - ohne echtes Netz.

Riegel gegen eine echte Veroeffentlichung:
1. `SALES_DB_SCHEMA=sales_test` hart gesetzt, Schema-Wache.
2. Jeder Eintrag in `kanal_adapter.SENDER` ist eine Attrappe.
3. `kanal_api.HTTP` laesst den Test scheitern, falls doch ein Adapter
   durchrutscht.
"""
import json
import os

import pytest

# HART, nicht setdefault (Begruendung in test_linkedin_dispatch.py).
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kanal_adapter  # noqa: E402
import kanal_api  # noqa: E402
import kanal_dispatch as kd  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402
from kanaele import KANAELE  # noqa: E402
from kanal_api import Beleg, KanalFehler  # noqa: E402

BS_PASSWORT = "abcd-efgh-ijkl-mnop"
MASTO_TOKEN = "mastoTOKENgeheim4711"
BS_URL = "https://bsky.app/profile/vibemind.bsky.social/post/1"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' - erlaubt ist nur "
        f"'sales_test'.")


class Attrappe:
    """Merkt sich je Kanal, was veroeffentlicht worden WAERE."""

    def __init__(self):
        self.aufrufe = {k: [] for k in KANAELE}
        self.fehler = {}

    def sender(self, kanal):
        def senden(zugang, text, medien_, titel, schluessel):
            self.aufrufe[kanal].append({"text": text, "medien": list(medien_),
                                        "titel": titel,
                                        "schluessel": schluessel})
            if kanal in self.fehler:
                raise self.fehler[kanal]
            if kanal == "bluesky":
                return Beleg("at://x/app.bsky.feed.post/1", BS_URL)
            return Beleg(f"{kanal}-1", "")
        return senden


def _kein_netz(anfrage):
    pytest.fail("kanal_api.HTTP wurde gerufen - echtes Netz im Test")


@pytest.fixture(autouse=True)
def umgebung(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.leads, sales_test.kanal_status cascade")
    attrappe = Attrappe()
    for kanal in KANAELE:
        monkeypatch.setitem(kanal_adapter.SENDER, kanal, attrappe.sender(kanal))
    monkeypatch.setattr(kanal_api, "HTTP", _kein_netz)
    for info in KANAELE.values():
        for name in info.env_namen:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BLUESKY_HANDLE", "vibemind.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", BS_PASSWORT)
    monkeypatch.setenv("MASTODON_INSTANCE", "https://mastodon.social")
    monkeypatch.setenv("MASTODON_TOKEN", MASTO_TOKEN)
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    return attrappe


def _lead():
    return server._q("insert into leads (name, source) values "
                     "('KANAELE (Eigenes Profil)', 'system') returning id")[0]["id"]


def _entwurf(kanal, status="approved", approved_vor_tagen=0, media_ref=None,
             body="Hallo", recipient="eigenes-profil", subject="Post: Test"):
    zeile = server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref, thema) values (%s, %s, %s, %s, %s, %s, 'Test') "
        "returning id",
        (_lead(), kanal, recipient, subject, body, media_ref))[0]
    if status != "pending":
        server._q("update drafts set status = %s, approved_at = now() - "
                  "make_interval(days => %s) where id = %s",
                  (status, approved_vor_tagen, zeile["id"]))
    return str(zeile["id"])


def _draft(draft_id):
    return server._q("select status, error from drafts where id = %s",
                     (draft_id,))[0]


def _belege(draft_id=None):
    zeilen = server._q("select payload from activities where type = 'versand' "
                       "order by created_at")
    werte = [z["payload"] if isinstance(z["payload"], dict)
             else json.loads(z["payload"]) for z in zeilen]
    if draft_id:
        werte = [w for w in werte if w.get("draft_id") == draft_id]
    return werte


def _status(kanal):
    zeilen = server._q("select verbunden, letzter_fehler from kanal_status "
                       "where kanal = %s", (kanal,))
    return zeilen[0] if zeilen else None


def _beleg_von_heute(kanal, ungewiss=False):
    payload = {"draft_id": "00000000-0000-0000-0000-000000000000",
               "kanal": kanal, "weg": "kanal-dispatcher",
               "empfaenger": "eigenes-profil", "beitrag": None if ungewiss else "x"}
    if ungewiss:
        payload["ungewiss"] = True
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'versand', %s) returning id", (_lead(), json.dumps(payload)))


# ---------------------------------------------------------------------------

def test_veroeffentlicht_bucht_beleg_vor_sent(umgebung):
    d = _entwurf("bluesky")
    assert kd.verarbeite_draft("bluesky", d) == "veroeffentlicht"
    assert _draft(d)["status"] == "sent"
    assert _belege(d) == [{
        "draft_id": d, "kanal": "bluesky", "weg": "kanal-dispatcher",
        "empfaenger": "eigenes-profil", "beitrag": "at://x/app.bsky.feed.post/1",
        "url": BS_URL, "medienart": "text"}]
    assert umgebung.aufrufe["bluesky"][0]["schluessel"] == d


def test_doppelversand_ausgeschlossen(umgebung):
    d = _entwurf("bluesky")
    assert kd.verarbeite_draft("bluesky", d) == "veroeffentlicht"
    server._q("update drafts set status = 'approved' where id = %s returning id", (d,))
    assert kd.verarbeite_draft("bluesky", d) == "schon_veroeffentlicht"
    assert len(umgebung.aufrufe["bluesky"]) == 1


def test_claim_greift_nur_eigenes_profil_und_kanal(umgebung):
    dm = _entwurf("telegram", recipient="Max Muster")
    li = _entwurf("linkedin")
    kd.eine_runde()
    assert _draft(dm)["status"] == "approved"
    assert _draft(li)["status"] == "approved"
    assert kd.claim("bluesky", li) is None
    with pytest.raises(ValueError):
        kd.claim("linkedin", li)


def test_ungewiss_sperrt_wiederholung(umgebung):
    umgebung.fehler["bluesky"] = KanalFehler("Bluesky: keine Antwort",
                                             ungewiss=True)
    d = _entwurf("bluesky")
    assert kd.verarbeite_draft("bluesky", d) == "ungewiss"
    assert _draft(d)["error"].startswith("UNGEWISS")
    (beleg,) = _belege(d)
    assert beleg["ungewiss"] is True and beleg["beitrag"] is None
    assert beleg["url"] is None and beleg["grund"]
    server._q("update drafts set status = 'approved' where id = %s returning id", (d,))
    assert kd.verarbeite_draft("bluesky", d) == "schon_veroeffentlicht"
    assert len(umgebung.aufrufe["bluesky"]) == 1


def test_unerwartete_ausnahme_beim_senden_ist_ungewiss(umgebung):
    umgebung.fehler["bluesky"] = KeyError("cid")
    d = _entwurf("bluesky")
    assert kd.verarbeite_draft("bluesky", d) == "ungewiss"
    assert _belege(d)[0]["ungewiss"] is True


def test_dauerhaft_wird_fehler_und_ist_wiederholbar(umgebung):
    umgebung.fehler["bluesky"] = KanalFehler("x")
    d = _entwurf("bluesky")
    assert kd.verarbeite_draft("bluesky", d) == "fehler"
    assert _belege(d) == []
    assert _draft(d) == {"status": "failed", "error": "x"}
    assert kd.bereits_veroeffentlicht("bluesky", d) is None


def test_kadenz_je_kanal(umgebung):
    _beleg_von_heute("bluesky")
    _beleg_von_heute("bluesky")
    _beleg_von_heute("bluesky", ungewiss=True)
    _beleg_von_heute("linkedin")
    assert kd.heute_anzahl("bluesky") == 3
    b = _entwurf("bluesky")
    m = _entwurf("mastodon")
    ausgaenge = kd.eine_runde()
    assert ausgaenge["bluesky"] == "kadenz"
    assert ausgaenge["mastodon"] == "veroeffentlicht"
    assert _draft(b)["status"] == "approved"
    assert _draft(m)["status"] == "sent"


def test_frischegrenze(umgebung):
    d = _entwurf("bluesky", approved_vor_tagen=8)
    assert kd.wartende("bluesky")[0]["zu_alt"] is True
    assert kd.eine_runde_kanal("bluesky") == "nichts"
    assert _draft(d)["status"] == "approved"


def test_nicht_verbundener_kanal_bleibt_liegen(umgebung):
    d = _entwurf("discord")
    assert kd.eine_runde_kanal("discord") == "nicht_verbunden"
    assert _draft(d)["status"] == "approved"
    zeile = _status("discord")
    assert zeile["verbunden"] is False
    assert "DISCORD_ANKUENDIGUNG_WEBHOOK" in zeile["letzter_fehler"]


def test_ausfall_eines_kanals_haelt_andere_nicht_auf(umgebung, monkeypatch):
    echt = kd.heute_anzahl

    def kaputt(kanal):
        if kanal == "bluesky":
            raise RuntimeError("kaputt")
        return echt(kanal)

    monkeypatch.setattr(kd, "heute_anzahl", kaputt)
    _entwurf("bluesky")
    _entwurf("mastodon")
    ausgaenge = kd.eine_runde()
    assert ausgaenge["bluesky"] == "ausnahme"
    assert ausgaenge["mastodon"] == "veroeffentlicht"
    assert "RuntimeError" in _status("bluesky")["letzter_fehler"]


def test_zu_langer_text_geht_nicht_raus(umgebung):
    d = _entwurf("bluesky", body="x" * 301)
    assert kd.verarbeite_draft("bluesky", d) == "zu_lang"
    assert umgebung.aufrufe["bluesky"] == []
    assert "300" in _draft(d)["error"]
    assert "NICHTS" in _draft(d)["error"]


def test_medien_bild_wird_geladen(umgebung, tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"x" * 60)
    (tmp_path / "b.pdf").write_bytes(b"%PDF" + b"x" * 60)
    d = _entwurf("bluesky", media_ref="a.png")
    assert kd.verarbeite_draft("bluesky", d) == "veroeffentlicht"
    (medium,) = umgebung.aufrufe["bluesky"][0]["medien"]
    assert medium.art == "bild" and medium.mimetyp == "image/png"
    assert medium.daten.startswith(b"\x89PNG")
    assert _belege(d)[0]["medienart"] == "bild"

    p = _entwurf("mastodon", media_ref="b.pdf")
    assert kd.verarbeite_draft("mastodon", p) == "medien_unbrauchbar"
    assert umgebung.aufrufe["mastodon"] == []
    assert _draft(p)["status"] == "failed"


def test_medien_grenze_aus_registry(umgebung, tmp_path):
    (tmp_path / "gross.png").write_bytes(b"x" * 1_000_001)
    with pytest.raises(kd.BeitragFehler):
        kd.medien_laden("bluesky", "gross.png")
    with pytest.raises(kd.BeitragFehler):
        kd.medien_laden("bluesky", "../geheim.png")
    assert kd.medien_laden("bluesky", None) == []


def test_status_ohne_zugaenge_alle_nicht_verbunden(umgebung, monkeypatch):
    for info in KANAELE.values():
        for name in info.env_namen:
            monkeypatch.delenv(name, raising=False)
    ausgaenge = kd.eine_runde()
    assert ausgaenge == {k: "nicht_verbunden" for k in KANAELE}
    zeilen = server._q("select kanal, verbunden from kanal_status")
    assert {z["kanal"]: z["verbunden"] for z in zeilen} == {k: False for k in KANAELE}


def test_verbundener_kanal_status_und_fehler_geloescht(umgebung):
    umgebung.fehler["bluesky"] = KanalFehler("Bluesky: HTTP 400 bei createRecord")
    _entwurf("bluesky")
    assert kd.eine_runde_kanal("bluesky") == "fehler"
    assert "createRecord" in _status("bluesky")["letzter_fehler"]
    del umgebung.fehler["bluesky"]
    _entwurf("bluesky")
    assert kd.eine_runde_kanal("bluesky") == "veroeffentlicht"
    assert _status("bluesky") == {"verbunden": True, "letzter_fehler": None}


def test_kein_geheimnis_in_status_und_fehler(umgebung):
    umgebung.fehler["bluesky"] = KanalFehler(
        f"Bluesky: HTTP 401 bei createSession: password {BS_PASSWORT} falsch")
    d = _entwurf("bluesky")
    assert kd.eine_runde_kanal("bluesky") == "fehler"
    assert BS_PASSWORT not in _draft(d)["error"]
    assert BS_PASSWORT not in _status("bluesky")["letzter_fehler"]
    assert "createSession" in _status("bluesky")["letzter_fehler"]


def test_kein_geheimnis_bei_ausnahme_in_runde(umgebung, monkeypatch):
    def kaputt(kanal):
        raise RuntimeError(f"token {MASTO_TOKEN} kaputt")

    monkeypatch.setattr(kd, "heute_anzahl", kaputt)
    assert kd.eine_runde()["mastodon"] == "ausnahme"
    assert MASTO_TOKEN not in _status("mastodon")["letzter_fehler"]
