"""Freigabe-Bote (Plan 2026-11-08, Task 7): planen/vorschlagstext rein, durchgang gegen Fake-RPC."""
import io
import logging
import os
import urllib.error

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402

import freigabe_bote as fb  # noqa: E402
import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402

BASIS = "https://s"
K = "fg-aaaaaaaaaa"
K2 = "fg-bbbbbbbbbb"
SCHLUESSEL = "geheim-schluessel-12345"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")
        conn.execute("delete from sales_test.einstellungen where schluessel = 'freigabe_stufe2'")
    yield


def eintrag(kennung=K, stand="ungesichtet", **kw):
    e = {"kennung": kennung, "herkunft": "debugger-claw", "art": "debugger_pr",
         "quelle_ref": "Flissel/vibemind-os#154", "titel": "Titel",
         "link": "https://github.com/x/pull/154", "rowboat_stand": stand}
    e.update(kw)
    return e


def text_zu(kennung=K):
    return fb.vorschlagstext(eintrag(kennung), BASIS)


def sig(kind, kennung=K):
    return {"kind": kind, "key": f"[debugger-claw] titel · [sales]({BASIS}/freigaben#{kennung})",
            "at": "2026-11-08T10:00:00Z"}


# --- rein -----------------------------------------------------------------

def test_vorschlagstext_bereinigt():
    e = eintrag(titel="@rowboat fix [a](b)\nzwei" + "x" * 900)
    t = fb.vorschlagstext(e, BASIS)
    titel = t.split(" · ")[0].split("] ", 1)[1]
    assert "\n" not in t and "@" not in t
    assert not any(c in titel for c in "[]()@")
    assert len(titel) <= 160
    assert t.endswith(f" · [Sales](https://s/freigaben#{K})")


def test_vorschlagstext_form_und_label():
    assert fb.vorschlagstext(eintrag(), BASIS) == (
        f"[Debugger-Claw] Titel · [PR #154](https://github.com/x/pull/154) · "
        f"[Sales]({BASIS}/freigaben#{K})")
    s = eintrag(herkunft="selbstbild", art="selbstbild_rueckfrage", quelle_ref="a/b#7")
    assert "[Issue #7](" in fb.vorschlagstext(s, BASIS)
    w = eintrag(herkunft="werkstatt", art="kursfreigabe", quelle_ref="kurs-1")
    assert "[Ansehen](" in fb.vorschlagstext(w, BASIS)
    kein_link = fb.vorschlagstext(eintrag(link=None), BASIS)
    assert kein_link == f"[Debugger-Claw] Titel · [Sales]({BASIS}/freigaben#{K})"


def test_neuer_eintrag_wird_vorgeschlagen():
    p = fb.planen([eintrag()], [], fb.RowboatStand(), BASIS)
    assert p.hinzufuegen == [text_zu()] and not p.staende


def test_vorschlag_vorhanden_setzt_stand():
    p = fb.planen([eintrag()], [], fb.RowboatStand(vorschlaege=[text_zu()]), BASIS)
    assert p.staende == {K: "vorgeschlagen"} and p.hinzufuegen == []


def test_annahme_nur_mit_kept_signal():
    st = fb.RowboatStand(items=[("k", text_zu(), False)])
    p = fb.planen([eintrag(stand="vorgeschlagen")], [], st, BASIS)
    assert p.staende == {} and p.hinzufuegen == [text_zu()]
    st.signale = [sig("kept")]
    p = fb.planen([eintrag(stand="vorgeschlagen")], [], st, BASIS)
    assert p.staende == {K: "angenommen"} and p.hinzufuegen == []


def test_fremde_kennung_ignoriert():
    st = fb.RowboatStand(vorschlaege=[text_zu(K2)], items=[("k", text_zu(K2), False)],
                         signale=[sig("kept", K2)])
    p = fb.planen([], [], st, BASIS)
    assert p == fb.Plan()


def test_kennung_ausserhalb_sales_link_zaehlt_nicht():
    assert fb.kennung_in("fg-aaaaaaaaaa") is None
    assert fb.kennung_in("todo fg-aaaaaaaaaa [x](https://s/freigaben#fg-aaaaaaaaaa") is None
    assert fb.kennung_in(text_zu()) == K


def test_ablehnung():
    p = fb.planen([eintrag(stand="vorgeschlagen")], [], fb.RowboatStand(signale=[sig("dismissed")]),
                  BASIS)
    assert p.staende == {K: "abgelehnt"} and p.hinzufuegen == []


def test_abgehakt_nach_annahme():
    st = fb.RowboatStand(items=[("k", text_zu(), True)], signale=[sig("kept")])
    assert fb.planen([eintrag(stand="angenommen")], [], st, BASIS).staende == {K: "abgehakt"}
    # Item fehlt, Stand schon angenommen
    assert fb.planen([eintrag(stand="angenommen")], [], fb.RowboatStand(), BASIS).staende == {
        K: "abgehakt"}


def test_fremd_abgehaktes_item_ohne_kept_zaehlt_nicht():
    st = fb.RowboatStand(items=[("k", text_zu(), True)])
    p = fb.planen([eintrag()], [], st, BASIS)
    assert p.staende == {} and p.hinzufuegen == [text_zu()]


def test_aufraeumen_regeln():
    e = eintrag(stand="vorgeschlagen")
    p = fb.planen([], [e], fb.RowboatStand(vorschlaege=[text_zu()]), BASIS)
    assert p.zurueckziehen == [text_zu()] and p.aufgeraeumt == []
    p = fb.planen([], [e], fb.RowboatStand(items=[("k1", text_zu(), False)]), BASIS)
    assert p.abhaken == ["k1"] and p.aufgeraeumt == []
    p = fb.planen([], [e], fb.RowboatStand(items=[("k1", text_zu(), True)]), BASIS)
    assert p.aufgeraeumt == [K] and p.abhaken == []
    assert fb.planen([], [e], fb.RowboatStand(), BASIS).aufgeraeumt == [K]


# --- durchgang gegen Fake -------------------------------------------------

class FakeRowboat:
    def __init__(self, haken_verwerfen=False):
        self.suggestions: list[str] = []
        self.items: list[dict] = []
        self.signals: list[dict] = []
        self.haken_verwerfen = haken_verwerfen
        self.aufrufe: list[tuple[str, object]] = []

    def annehmen(self, text):
        self.suggestions.remove(text)
        self.items.append({"key": text.lower(), "text": text, "checked": False, "children": []})
        self.signals.append({"kind": "kept", "key": text.lower(), "at": "x"})

    def __call__(self, kanal, body):
        self.aufrufe.append((kanal, body))
        if kanal == "todo:get":
            return {"list": {"blocks": [{"kind": "raw", "text": "# Todo"}] +
                             [{"kind": "item", "item": i} for i in self.items]},
                    "running": [], "sessions": {}, "suggestions": list(self.suggestions)}
        if kanal == "todo:plannerSignals":
            return {"signals": list(self.signals)}
        if kanal == "todo:addSuggestions":
            added = [t for t in body["texts"] if t not in self.suggestions
                     and t not in [i["text"] for i in self.items]]
            self.suggestions += added
            return {"added": added}
        if kanal == "todo:withdrawSuggestion":
            gone = body["text"] in self.suggestions
            if gone:
                self.suggestions.remove(body["text"])
            return {"success": True, "removed": gone}
        if kanal == "todo:setChecked":
            if not self.haken_verwerfen:
                for i in self.items:
                    if i["key"] == body["key"]:
                        i["checked"] = body["checked"]
            return {"success": True}
        raise AssertionError(kanal)

    def gesendet(self, kanal):
        return [b for k, b in self.aufrufe if k == kanal]


@pytest.fixture
def rowboat(monkeypatch):
    fake = FakeRowboat()
    monkeypatch.setattr(fb, "_rpc", fake)
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    return fake


def _db(kennung):
    return server._q("select * from freigabe_eintraege where kennung = %s", (kennung,))[0]


def _neuer_eintrag():
    k, _ = fe.eintragen("debugger-claw", "debugger_pr", "Flissel/vibemind-os#154", "Titel",
                        "https://github.com/x/pull/154")
    return k


def test_zwei_laeufe_eine_zeile(rowboat):
    k = _neuer_eintrag()
    assert fb.durchgang() == 0
    assert len(rowboat.suggestions) == 1 and kennung_ok(rowboat.suggestions[0], k)
    assert _db(k)["rowboat_stand"] == "vorgeschlagen"
    assert fb.durchgang() == 0
    assert len(rowboat.suggestions) == 1
    assert len(rowboat.gesendet("todo:addSuggestions")) == 1


def kennung_ok(text, k):
    return fb.kennung_in(text) == k


def test_annahme_und_abhaken_ueber_lauf(rowboat):
    k = _neuer_eintrag()
    fb.durchgang()
    rowboat.annehmen(rowboat.suggestions[0])
    fb.durchgang()
    assert _db(k)["rowboat_stand"] == "angenommen"
    rowboat.items[0]["checked"] = True
    fb.durchgang()
    assert _db(k)["rowboat_stand"] == "abgehakt"


def test_haken_verloren_wird_neu_gesetzt(rowboat):
    k = _neuer_eintrag()
    fb.durchgang()
    rowboat.annehmen(rowboat.suggestions[0])
    fb.durchgang()
    fe.schliessen("debugger-claw", "Flissel/vibemind-os#154", "erledigt", "test")
    rowboat.haken_verwerfen = True
    fb.durchgang()
    fb.durchgang()
    assert len(rowboat.gesendet("todo:setChecked")) == 2
    assert _db(k)["rowboat_aufgeraeumt"] is False
    rowboat.haken_verwerfen = False
    fb.durchgang()
    assert _db(k)["rowboat_aufgeraeumt"] is False  # Haken eben erst gesetzt, noch nicht gesehen
    fb.durchgang()
    assert _db(k)["rowboat_aufgeraeumt"] is True
    assert len(rowboat.gesendet("todo:setChecked")) == 3


def test_geschlossen_zieht_vorschlag_zurueck(rowboat):
    k = _neuer_eintrag()
    fb.durchgang()
    fe.schliessen("debugger-claw", "Flissel/vibemind-os#154", "verworfen", "test")
    fb.durchgang()
    assert rowboat.suggestions == [] and _db(k)["rowboat_aufgeraeumt"] is False
    fb.durchgang()
    assert _db(k)["rowboat_aufgeraeumt"] is True


def test_spaeterer_rpc_fehler_behaelt_vorgeschlagen(rowboat, monkeypatch):
    _neuer_eintrag()
    fb.durchgang()
    fe.schliessen("debugger-claw", "Flissel/vibemind-os#154", "verworfen", "test")
    k3, _ = fe.eintragen("debugger-claw", "debugger_pr", "Flissel/vibemind-os#156", "Drei")

    def kaputt(kanal, body):
        if kanal == "todo:withdrawSuggestion":
            raise urllib.error.URLError("weg")
        return rowboat(kanal, body)
    monkeypatch.setattr(fb, "_rpc", kaputt)
    assert fb.durchgang() == 1
    assert _db(k3)["rowboat_stand"] == "vorgeschlagen"


def test_geschlossen_ungesichtet_wird_zurueckgezogen(rowboat):
    k = _neuer_eintrag()
    rowboat.suggestions.append(fb.vorschlagstext(_db(k), BASIS))
    fe.schliessen("debugger-claw", "Flissel/vibemind-os#154", "verworfen", "test")
    assert _db(k)["rowboat_stand"] == "ungesichtet"
    fb.durchgang()
    assert rowboat.suggestions == [] and _db(k)["rowboat_aufgeraeumt"] is False
    fb.durchgang()
    assert _db(k)["rowboat_aufgeraeumt"] is True


def test_link_mit_at_und_klammern_bleibt_unschaedlich():
    t = fb.vorschlagstext(eintrag(link="https://x/@agent/[a](b)"), "https://s/@x")
    assert "@" not in t
    assert "[a]" not in t and t.count("[") == 3 and t.count("]") == 3
    assert fb.kennung_in(t) == K


def test_rowboat_weg_kein_zurueckschreiben(monkeypatch):
    k = _neuer_eintrag()
    monkeypatch.setenv("UI_BASIS_URL", BASIS)

    def weg(kanal, body):
        raise urllib.error.URLError("weg")
    monkeypatch.setattr(fb, "_rpc", weg)
    assert fb.durchgang() == 1
    assert _db(k)["rowboat_stand"] == "ungesichtet"


def test_ohne_basis_url_nichts(monkeypatch):
    _neuer_eintrag()
    monkeypatch.delenv("UI_BASIS_URL", raising=False)
    fake = FakeRowboat()
    monkeypatch.setattr(fb, "_rpc", fake)
    assert fb.durchgang() == 1
    assert fake.aufrufe == []


def test_schluessel_nie_im_log(monkeypatch, tmp_path, caplog):
    datei = tmp_path / "key"
    datei.write_text(SCHLUESSEL + "\n")
    monkeypatch.setattr(fb, "SCHLUESSEL_DATEI", str(datei))
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    _neuer_eintrag()
    gesehen = {}

    def urlopen(anfrage, timeout=None):
        gesehen["auth"] = anfrage.get_header("Authorization")
        gesehen["host"] = anfrage.get_header("Host")
        gesehen["timeout"] = timeout
        raise urllib.error.URLError(f"Verbindung mit {anfrage.get_header('Authorization')}")
    monkeypatch.setattr(fb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fb.LOG, "propagate", True)  # wird nach dem Test zurueckgesetzt
    with caplog.at_level(logging.DEBUG, logger="freigabe-bote"):
        assert fb.durchgang() == 1
    assert gesehen == {"auth": f"Bearer {SCHLUESSEL}", "host": "127.0.0.1:3220", "timeout": 10}
    assert SCHLUESSEL not in caplog.text and "URLError" in caplog.text


def test_http_fehler_loggt_status_nie_rumpf(monkeypatch, tmp_path, caplog):
    datei = tmp_path / "key"
    datei.write_text(SCHLUESSEL + "\n")
    monkeypatch.setattr(fb, "SCHLUESSEL_DATEI", str(datei))
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    _neuer_eintrag()
    rumpf = io.BytesIO(f"RUMPF-GEHEIM {SCHLUESSEL}".encode())

    def urlopen(anfrage, timeout=None):
        raise urllib.error.HTTPError(anfrage.full_url, 401, "Unauthorized", None, rumpf)
    monkeypatch.setattr(fb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fb.LOG, "propagate", True)
    with caplog.at_level(logging.DEBUG, logger="freigabe-bote"):
        assert fb.durchgang() == 1
    assert "RPC todo:get: HTTPError 401" in caplog.text
    assert "RUMPF-GEHEIM" not in caplog.text and SCHLUESSEL not in caplog.text
    assert rumpf.closed


@pytest.mark.parametrize("schema", ["public", "sales_prod", ""])
def test_main_startet_nur_mit_sales_oder_sales_test(monkeypatch, caplog, schema):
    monkeypatch.setattr(fe.server, "SCHEMA", schema)
    monkeypatch.setattr(fb, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(fb.LOG, "propagate", True)
    monkeypatch.setattr(fb, "durchgang", lambda: pytest.fail("darf nicht laufen"))
    monkeypatch.setattr(fb.signal, "signal", lambda *a: pytest.fail("kein Signal-Handler"))
    with caplog.at_level(logging.DEBUG, logger="freigabe-bote"):
        assert fb.main() == 2
    assert "nicht erlaubt" in caplog.text and f"Schema {schema} " in caplog.text


def test_erlaubte_schemas():
    assert fb.ERLAUBTE_SCHEMAS == ("sales", "sales_test")


# --- F5: geaenderter Titel wird in Rowboat nachgezogen ---------------------

def test_geaenderter_text_wird_ersetzt():
    alt = text_zu()
    neu = fb.vorschlagstext(eintrag(titel="Neuer Titel"), BASIS)
    p = fb.planen([eintrag(titel="Neuer Titel", stand="vorgeschlagen")], [],
                  fb.RowboatStand(vorschlaege=[alt]), BASIS)
    assert p.ersetzen == [(alt, neu)]
    assert p.hinzufuegen == [] and p.zurueckziehen == [] and p.staende == {}


def test_gleicher_text_bis_auf_leerraum_wird_nicht_ersetzt():
    gespeichert = "  " + text_zu().replace(" · ", "  ·   ") + " "
    p = fb.planen([eintrag(stand="vorgeschlagen")], [],
                  fb.RowboatStand(vorschlaege=[gespeichert]), BASIS)
    assert p.ersetzen == [] and p.hinzufuegen == []


def test_angenommene_zeile_wird_nie_ersetzt():
    st = fb.RowboatStand(items=[("k", text_zu(), False)], signale=[sig("kept")])
    p = fb.planen([eintrag(titel="Neuer Titel", stand="angenommen")], [], st, BASIS)
    assert p.ersetzen == [] and p.hinzufuegen == []


def test_durchgang_zieht_titel_nach(rowboat):
    k = _neuer_eintrag()
    fb.durchgang()
    alt = rowboat.suggestions[0]
    fe.eintragen("debugger-claw", "debugger_pr", "Flissel/vibemind-os#154", "Neuer Titel",
                 "https://github.com/x/pull/154")
    assert _db(k)["titel"] == "Neuer Titel"
    assert fb.durchgang() == 0
    assert len(rowboat.suggestions) == 1
    assert "Neuer Titel" in rowboat.suggestions[0] and kennung_ok(rowboat.suggestions[0], k)
    assert rowboat.gesendet("todo:withdrawSuggestion") == [{"text": alt}]
    assert _db(k)["rowboat_stand"] == "vorgeschlagen"
    # danach Ruhe: kein weiteres Ersetzen
    fb.durchgang()
    assert len(rowboat.gesendet("todo:withdrawSuggestion")) == 1
    assert len(rowboat.gesendet("todo:addSuggestions")) == 2


def test_inzwischen_angenommen_kein_doppel(rowboat, monkeypatch):
    k = _neuer_eintrag()
    fb.durchgang()
    alt = rowboat.suggestions[0]
    fe.eintragen("debugger-claw", "debugger_pr", "Flissel/vibemind-os#154", "Neuer Titel",
                 "https://github.com/x/pull/154")
    echt = fb._rpc

    def zwischendurch_angenommen(kanal, body):
        if kanal == "todo:withdrawSuggestion" and alt in rowboat.suggestions:
            rowboat.annehmen(alt)  # der Mensch war schneller
        return echt(kanal, body)
    monkeypatch.setattr(fb, "_rpc", zwischendurch_angenommen)
    assert fb.durchgang() == 0
    assert rowboat.suggestions == []
    assert [i["text"] for i in rowboat.items] == [alt]
    fb.durchgang()
    assert _db(k)["rowboat_stand"] == "angenommen"
    assert rowboat.suggestions == []
