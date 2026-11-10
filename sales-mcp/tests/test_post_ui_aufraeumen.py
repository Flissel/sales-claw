"""Mail-Reiter Aufmerksamkeit, Zur Info, To-Review und Aufräumen (Spec 2026-11-06 §6.1,
§6.3, §7) gegen sales_test. Anmeldung, Personen und Hilfen kommen aus test_ui_post.py.
"""
import math
import os
import re

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402
import server  # noqa: E402
import post_struktur as ps  # noqa: E402
from test_ui_post import (HOST, _client, _get, _mail, _post, _zeile,  # noqa: E402,F401
                          schema_wache, welt)  # noqa: F401


@pytest.fixture(autouse=True)
def freigaben_leer():
    # `welt` leert Mails, Konten und Regeln, nicht die Freigaben.
    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_loeschfreigaben")
    leeren()
    yield
    leeren()


def _ziel(mail_id, ziel, **spalten):
    sets = ["ziel = %s"] + [f"{k} = %s" for k in spalten]
    with server.pool.connection() as conn:
        conn.execute(f"update post_mails set {', '.join(sets)} where id = %s",
                     (ziel, *spalten.values(), mail_id))
    return mail_id


def _werbung(von, jahr=2025, betreff="Angebot", besitzer="t8_anna"):
    m = _mail(besitzer, "privat", "Werbung", von=von, betreff=betreff)
    return _ziel(m, "loeschen", datum=f"{jahr}-06-15 12:00+00")


def _post_liste(name, pfad, daten, csrf=True):
    """Formular mit mehrfach vorkommenden Feldern (absender, loeschen)."""
    if csrf:
        daten = {**daten, "csrf": ui_token()}
    return _client(name).post(pfad, data=daten, headers=HOST, follow_redirects=False)


def ui_token():
    import ui
    return ui.CSRF_TOKEN


def _regeln(art="nie_werbung", besitzer="t8_anna"):
    return server._q("select muster from post_regeln where art = %s and besitzer = %s",
                     (art, besitzer))


# --- Reiter ---------------------------------------------------------------

def test_standardansicht_ist_aufmerksamkeit():
    _ziel(_mail(betreff="Im Posteingang"), "posteingang")
    _mail(betreff="Noch ohne Ziel")
    _ziel(_mail(betreff="Nur zur Info"), "zur_info")
    _ziel(_mail(betreff="Wird geprueft"), "to_review")
    _ziel(_mail(betreff="Schon weg"), "posteingang", status="geloescht")
    seite = _get("t8_anna", "/post").text
    assert "Im Posteingang" in seite and "Noch ohne Ziel" in seite
    assert "Nur zur Info" not in seite and "Wird geprueft" not in seite
    assert "Schon weg" not in seite
    assert 'class="reiter"' in seite
    for reiter in ("Aufmerksamkeit", "Zur Info", "To-Review", "Aufräumen"):
        assert reiter in seite
    # Unbekannte Ansicht fällt auf die Vorgabe zurück, kein 500.
    assert "Im Posteingang" in _get("t8_anna", "/post?ansicht=quatsch").text
    # Geloeschtes erscheint in keinem Reiter.
    for ansicht in ("zur_info", "to_review"):
        assert "Schon weg" not in _get("t8_anna", f"/post?ansicht={ansicht}").text


def test_zur_info_reiter_zeigt_faecher():
    _ziel(_mail("t8_anna", "privat", "Rechnungen", betreff="Rechnung A"), "zur_info")
    _ziel(_mail("t8_anna", "privat", "Familie & Freunde", betreff="Ausflug"), "posteingang")
    seite = _get("t8_anna", "/post?ansicht=zur_info").text
    assert 'class="faecher"' in seite
    assert "Rechnung A" in seite and "Ausflug" not in seite
    # Die Fächer-Links bleiben im Reiter und zählen nur dessen Mails.
    assert "ansicht=zur_info" in seite and "fach=Rechnungen" in seite
    assert "fach=Familie" not in seite
    gefiltert = _get("t8_anna", "/post?ansicht=zur_info&bereich=privat&fach=Rechnungen").text
    assert "Rechnung A" in gefiltert


def test_to_review_nennt_loeschdatum():
    _ziel(_mail(betreff="Fest verschoben"), "to_review", ordner_am="2026-10-01 12:00+00",
          ordner="To-Review")
    _ziel(_mail(betreff="Noch nicht verschoben"), "to_review")
    # M1: ordner_am stammt vom Verschieben nach Zur Info - die Frist laeuft erst in To-Review.
    _ziel(_mail(betreff="Liegt in Zur Info"), "to_review", ordner_am="2026-10-01 12:00+00",
          ordner="Zur Info")
    seite = _get("t8_anna", "/post?ansicht=to_review").text
    assert "wird gelöscht am 31.10.2026" in seite
    # Ohne ordner_am oder ausserhalb von To-Review gibt es kein erfundenes Datum.
    assert seite.count("wird gelöscht am") == 1
    assert seite.count("noch nicht im Ordner") == 2


# --- Aufräumen ------------------------------------------------------------

def test_aufraeumen_zeigt_jahre_und_resttage():
    _werbung("Shop <news@shop.example>", jahr=2025)
    _werbung("Shop <news@shop.example>", jahr=2024)
    for _ in range(3):
        _mail("t8_anna", None, None, status="neu")
    konto = server._q("select id from post_konten where besitzer = 't8_anna'")[0]["id"]
    server._q("update post_konten set ordnen_aus = 'UIDVALIDITY geaendert' where id = %s "
              "returning id", (konto,))
    seite = _get("t8_anna", "/post/aufraeumen").text
    assert "/post/aufraeumen/2025" in seite and "/post/aufraeumen/2024" in seite
    assert "Modellaufrufe heute" in seite and "/ 500" in seite
    assert f"<b>{math.ceil(3 * 2 / 500)}</b> Tage Rest" in seite
    assert "ruht: UIDVALIDITY geaendert" in seite
    assert "Ordnungsmodus" in seite


def test_vorschau_formular_ein_knopf_und_haken_je_absender():
    for i in range(2):
        _werbung("Shop <news@shop.example>", betreff=f"Sale {i}")
    _werbung("Andere <info@andere.example>", betreff="Aktion")
    seite = _get("t8_anna", "/post/aufraeumen/2025").text
    # Ein Formular, ein Knopf für die Freigabe (der Seitenrahmen hat eigene Formulare).
    assert seite.count('action="/post/aufraeumen/2025"') == 1
    assert seite.count('class="primaer"') == 1
    assert "Jahr 2025 löschen freigeben" in seite
    haken = re.findall(r'<input type="checkbox" name="loeschen"[^>]*>', seite)
    assert len(haken) == 2 and all(" checked" in h for h in haken)
    assert len(re.findall(r'type="hidden" name="absender"', seite)) == 2
    assert "news@shop.example" in seite and "Sale" in seite


def test_abgewaehlter_absender_wird_ausgenommen():
    a = _werbung("Shop <news@shop.example>")
    b = _werbung("Andere <info@andere.example>")
    r = _post_liste("t8_anna", "/post/aufraeumen/2025", {
        "absender": ["news@shop.example", "info@andere.example"],
        "loeschen": ["news@shop.example"]})
    assert r.status_code == 303 and r.headers["location"].startswith("/post/aufraeumen")
    zeile = server._q("select ausgenommen from post_loeschfreigaben "
                      "where besitzer = 't8_anna' and jahr = 2025")[0]
    assert zeile["ausgenommen"] == ["info@andere.example"]
    assert len(_regeln()) == 1 and "andere" in _regeln()[0]["muster"]
    assert _zeile(a)["ziel"] == "loeschen" and _zeile(b)["ziel"] == "zur_info"
    # Zweiter Klick auf dasselbe Jahr: Hinweis statt Absturz.
    zweit = _post_liste("t8_anna", "/post/aufraeumen/2025", {
        "absender": ["news@shop.example"], "loeschen": ["news@shop.example"]})
    assert zweit.status_code == 303
    assert zweit.headers["location"] == "/post/aufraeumen?hinweis=schon"
    assert "schon freigegeben" in _get("t8_anna", zweit.headers["location"]).text


def test_freigabe_post_ohne_csrf_403_und_ohne_wirkung():
    _werbung("Shop <news@shop.example>")
    r = _post_liste("t8_anna", "/post/aufraeumen/2025",
                    {"absender": ["news@shop.example"]}, csrf=False)
    assert r.status_code == 403
    assert server._q("select count(*) n from post_loeschfreigaben")[0]["n"] == 0


def test_freigabe_rolle_lesen_403():
    _werbung("Shop <news@shop.example>", besitzer="t8_leser")
    r = _post_liste("t8_leser", "/post/aufraeumen/2025",
                    {"absender": ["news@shop.example"]})
    assert r.status_code == 403
    assert server._q("select count(*) n from post_loeschfreigaben")[0]["n"] == 0
    # Die Vorschau zeigt dem Leser keinen Freigabe-Knopf.
    assert "löschen freigeben" not in _get("t8_leser", "/post/aufraeumen/2025").text


def test_jahr_muss_plausibel_sein():
    for jahr in ("abc", "1", "99999"):
        assert _get("t8_anna", f"/post/aufraeumen/{jahr}").status_code == 404
        assert _post_liste("t8_anna", f"/post/aufraeumen/{jahr}", {}).status_code == 404


def test_freigabe_unbekanntes_jahr_404_ohne_zeile():
    _werbung("Mehr <x@mehr.example>", jahr=2023, besitzer="t8_ben")
    r = _post_liste("t8_ben", "/post/aufraeumen/2025", {"absender": ["x@mehr.example"]})
    assert r.status_code == 404
    assert server._q("select count(*) n from post_loeschfreigaben")[0]["n"] == 0


def test_resttage_zaehlen_altbestand_mit(monkeypatch):
    import post_abholen
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 10)
    for _ in range(3):
        _mail("t8_anna", None, None, status="neu")
    alt = [_mail("t8_anna", "privat", "Rechnungen") for _ in range(4)]
    v3 = _mail("t8_anna", "privat", "Rechnungen")
    mensch = _mail("t8_anna", "privat", "Rechnungen")
    fremd = _mail("t8_ben", "privat", "Rechnungen")
    with server.pool.connection() as conn:
        conn.execute("update post_mails set einordnung_version = 2 where id = any(%s)",
                     (alt + [mensch, fremd],))
        conn.execute("update post_mails set einordnung_version = 3 where id = %s", (v3,))
        conn.execute("update post_mails set einordnung_quelle = 'mensch' where id = %s",
                     (mensch,))
    seite = _get("t8_anna", "/post/aufraeumen").text
    # 3 neu + 4 Altbestand = 7 (v3, Mensch und fremde Konten zählen nicht):
    # ceil(7 * 2 / 10) = 2; ohne Altbestand wäre es ceil(3 * 2 / 10) = 1.
    assert "<b>7</b> Mails" in seite and "<b>2</b> Tage Rest" in seite
    assert "/ 10" in seite


def test_ohne_anmeldung_403():
    for pfad in ("/post/aufraeumen", "/post/aufraeumen/2025"):
        assert _get(None, pfad).status_code in (302, 303, 401, 403)


# --- Ziel ändern ----------------------------------------------------------

def test_aus_to_review_holen_schuetzt_absender():
    m = _ziel(_mail(von="Shop <news@shop.example>"), "to_review")
    r = _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": "posteingang"})
    assert r.status_code == 303
    z = _zeile(m)
    assert z["ziel"] == "posteingang" and z["ziel_manuell"] is True
    assert len(_regeln()) == 1
    # Von Zur Info in den Posteingang: nur diese Mail, keine Regel.
    n = _ziel(_mail(von="Bank <info@bank.example>"), "zur_info")
    assert _post("t8_anna", f"/post/mail/{n}/ziel", {"ziel": "posteingang"}).status_code == 303
    assert _zeile(n)["ziel"] == "posteingang" and _zeile(n)["ziel_manuell"] is True
    assert len(_regeln()) == 1


def test_leitung_darf_fremde_mail_nicht_umlegen():
    m = _ziel(_mail("t8_anna", "business", "Kunden & Anfragen",
                    von="Shop <news@shop.example>"), "to_review")
    r = _post("t8_lea", f"/post/mail/{m}/ziel", {"ziel": "posteingang"})
    assert r.status_code == 403
    z = _zeile(m)
    assert z["ziel"] == "to_review" and z["ziel_manuell"] is False
    assert not _regeln(besitzer="t8_anna") and not _regeln(besitzer="t8_lea")


def test_ziel_nur_posteingang_oder_zur_info_und_mit_csrf():
    m = _ziel(_mail(), "to_review")
    for ziel in ("loeschen", "to_review", "quatsch", ""):
        assert _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": ziel}).status_code == 400
    assert _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": "posteingang"},
                 csrf=False).status_code == 403
    z = _zeile(m)
    assert z["ziel"] == "to_review" and z["ziel_manuell"] is False and not _regeln()
    # Die Mail-Seite bietet die zwei Knöpfe an.
    assert f"/post/mail/{m}/ziel" in _get("t8_anna", f"/post/mail/{m}").text


def test_ziel_fremde_mail_und_leser():
    privat = _ziel(_mail("t8_anna", "privat", "Familie & Freunde"), "zur_info")
    assert _post("t8_ben", f"/post/mail/{privat}/ziel",
                 {"ziel": "posteingang"}).status_code in (403, 404)
    assert _zeile(privat)["ziel"] == "zur_info"
    eigene = _ziel(_mail("t8_leser", "privat", "Familie & Freunde"), "zur_info")
    assert _post("t8_leser", f"/post/mail/{eigene}/ziel",
                 {"ziel": "posteingang"}).status_code == 403
    assert _zeile(eigene)["ziel"] == "zur_info"


# --- Isolation ------------------------------------------------------------

def test_fremde_freigabe_nicht_moeglich():
    _werbung("Shop <news@shop.example>", besitzer="t8_anna", betreff="Annas Werbung")
    _werbung("Mehr <x@mehr.example>", jahr=2023, besitzer="t8_ben")
    for name in ("t8_ben", "t8_lea"):
        seite = _get(name, "/post/aufraeumen").text
        assert "k-t8-anna" not in seite and "/post/aufraeumen/2025" not in seite
    assert "/post/aufraeumen/2023" in _get("t8_ben", "/post/aufraeumen").text
    # Annas Jahr gibt es für Ben nicht; ein Freigabe-Post trifft nur Bens eigene Daten.
    assert _get("t8_ben", "/post/aufraeumen/2025").status_code == 404
    assert "Annas Werbung" not in _get("t8_lea", "/post/aufraeumen/2025").text
    r = _post_liste("t8_lea", "/post/aufraeumen/2025", {"absender": ["news@shop.example"]})
    assert r.status_code == 404      # Leas Konten haben dieses Jahr nicht
    assert server._q("select count(*) n from post_loeschfreigaben "
                     "where besitzer = 't8_anna'")[0]["n"] == 0
    # Einen Besitzer-Parameter gibt es nicht: er wird ignoriert.
    assert "/post/aufraeumen/2025" not in _get(
        "t8_ben", "/post/aufraeumen?besitzer=t8_anna").text


# --- Was gelöscht wird, einsehen (I9) ------------------------------------------

def test_vorschau_verlinkt_liste_je_absender():
    _werbung("Shop <news@shop.example>", betreff="Sale 1")
    seite = _get("t8_anna", "/post/aufraeumen/2025").text
    assert "/post/aufraeumen/2025/absender?adresse=news%40shop.example" in seite


def test_liste_je_absender_nur_eigene_loeschbare_mails():
    _werbung("Shop <news@shop.example>", betreff="Sale 1")
    _werbung("Shop <NEWS@shop.example>", betreff="Sale <b>2</b>")
    _werbung("Shop <news@shop.example>", jahr=2024, betreff="Altes Jahr")
    _werbung("Andere <info@andere.example>", betreff="Anderer Absender")
    _ziel(_mail("t8_anna", "privat", "Werbung", von="Shop <news@shop.example>",
                betreff="Bleibt in Zur Info"), "zur_info", datum="2025-05-01 12:00+00")
    _werbung("Shop <news@shop.example>", betreff="Bens Werbung", besitzer="t8_ben")
    r = _get("t8_anna", "/post/aufraeumen/2025/absender?adresse=news%40shop.example")
    assert r.status_code == 200
    seite = r.text
    assert "Sale 1" in seite and "Sale &lt;b&gt;2&lt;/b&gt;" in seite
    assert "k-t8-anna" in seite and "15.06.2025" in seite
    for fremd in ("Altes Jahr", "Anderer Absender", "Bleibt in Zur Info", "Bens Werbung"):
        assert fremd not in seite
    # Ohne JavaScript, ohne Formular: nur lesen.
    assert "<script" not in seite.lower()


def test_liste_je_absender_fremder_besitzer_sieht_nichts():
    _werbung("Shop <news@shop.example>", betreff="Annas Werbung")
    _werbung("Shop <news@shop.example>", jahr=2023, betreff="Annas altes Jahr")
    _werbung("Shop <news@shop.example>", jahr=2023, betreff="Bens Werbung", besitzer="t8_ben")
    # Ben: Annas Jahr gibt es nicht, im gemeinsamen Jahr nur seine eigene Mail.
    assert _get("t8_ben", "/post/aufraeumen/2025/absender?adresse=news%40shop.example"
                ).status_code == 404
    seite = _get("t8_ben", "/post/aufraeumen/2023/absender?adresse=news%40shop.example").text
    assert "Bens Werbung" in seite and "Annas" not in seite
    # Leitung ohne eigene Konten: nichts, auch nicht Annas Werbung.
    for jahr in (2025, 2023):
        r = _get("t8_lea", f"/post/aufraeumen/{jahr}/absender?adresse=news%40shop.example")
        assert r.status_code == 404 and "Annas" not in r.text
    # Ohne Anmeldung zu; eine kaputte Adresse liefert eine leere Liste statt 500.
    assert _get(None, "/post/aufraeumen/2025/absender?adresse=news%40shop.example"
                ).status_code in (302, 303, 401, 403)
    leer = _get("t8_anna", "/post/aufraeumen/2025/absender?adresse=%25")
    assert leer.status_code == 200 and "Annas Werbung" not in leer.text


# --- Handkorrektur (I2, I3, M2) -------------------------------------------------

def _setzen(mail_id, **spalten):
    sets = ", ".join(f"{k} = %s" for k in spalten)
    with server.pool.connection() as conn:
        conn.execute(f"update post_mails set {sets} where id = %s", (*spalten.values(), mail_id))
    return mail_id


def test_handkorrektur_mit_regel_laesst_schutzregel_stehen():
    import post_werbung
    von = "Shop <News@Shop.example>"
    post_werbung.schutz_setzen("t8_anna", von)
    # Eine alte Einordnungs-Regel in anderer Schreibweise wird ersetzt, nicht verdoppelt.
    with server.pool.connection() as conn:
        conn.execute("insert into post_regeln (muster, feld, bereich, fach, sensibel, besitzer, "
                     "art) values (%s, 'von', 'privat', 'Werbung', false, 't8_anna', 'einordnen')",
                     (ps.absender_muster("News@Shop.example"),))
    m = _mail("t8_anna", "privat", ps.UNKLAR, von=von)
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": "Abos & Newsletter", "regel": "ja"}
                 ).status_code == 303
    assert len(_regeln("nie_werbung")) == 1
    einordnen = server._q("select muster, fach from post_regeln where art = 'einordnen' "
                          "and besitzer = 't8_anna'")
    assert [(r["muster"], r["fach"]) for r in einordnen] == [
        (ps.absender_muster("news@shop.example"), "Abos & Newsletter")]


def test_handkorrektur_aufmerksamkeit_aus_dem_neuen_fach():
    m = _setzen(_mail("t8_anna", "privat", ps.UNKLAR), aufmerksamkeit=True)
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": "Abos & Newsletter"}).status_code == 303
    assert _zeile(m)["aufmerksamkeit"] is False
    # Zurueck nach Zum Nachsehen: dann wieder Posteingang.
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": ps.UNKLAR}).status_code == 303
    assert _zeile(m)["aufmerksamkeit"] is True


def test_vorschlag_uebernimmt_aufmerksamkeit_des_vorschlags():
    import json
    mit = {"sortierer": {"bereich": "privat", "fach": "Rechnungen", "unterfach": None,
                         "aufmerksamkeit": True},
           "pruefer": {"bereich": "privat", "fach": "Abos & Newsletter", "unterfach": None}}
    for wahl, erwartet in (("sortierer", True), ("pruefer", False)):
        m = _mail("t8_anna", "privat", ps.UNKLAR)
        with server.pool.connection() as conn:
            conn.execute("update post_mails set aufmerksamkeit = true, "
                         "vorschlaege = %s::jsonb where id = %s", (json.dumps(mit), m))
        assert _post("t8_anna", f"/post/mail/{m}/vorschlag", {"wahl": wahl}).status_code == 303
        assert _zeile(m)["aufmerksamkeit"] is erwartet, wahl


def test_handkorrektur_nimmt_werbung_sicher_und_herkunft_bei_sensibel():
    m = _setzen(_mail("t8_anna", "privat", "Werbung"), werbung_sicher=True,
                urspruengliche_adresse="info@bluebatch.example")
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": "Werbung", "sensibel": "ja"}).status_code == 303
    z = _zeile(m)
    assert z["werbung_sicher"] is False and z["sensibel"] is True
    assert z["urspruengliche_adresse"] is None
    # Ohne sensibel bleibt die Herkunft; werbung_sicher faellt trotzdem (Mensch, nicht Regel).
    n = _setzen(_mail("t8_anna", "privat", "Werbung"), werbung_sicher=True,
                urspruengliche_adresse="info@bluebatch.example")
    assert _post("t8_anna", f"/post/mail/{n}/korrigieren",
                 {"bereich": "privat", "fach": "Werbung"}).status_code == 303
    z = _zeile(n)
    assert z["werbung_sicher"] is False and z["urspruengliche_adresse"] == "info@bluebatch.example"


def test_ziel_setzen_trifft_keine_inzwischen_geloeschte_mail(monkeypatch):
    """M2: zwischen Lesen und Schreiben geloescht (post_ordnen) - das UPDATE greift nicht."""
    m = _ziel(_mail(), "to_review")
    echt = ps.mail_lesen

    def veraltet(b, mail_id):
        gelesen = echt(b, mail_id)
        _setzen(m, status="geloescht")
        return gelesen
    monkeypatch.setattr(ps, "mail_lesen", veraltet)
    assert _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": "posteingang"}).status_code == 303
    z = _zeile(m)
    assert (z["status"], z["ziel"], z["ziel_manuell"]) == ("geloescht", "to_review", False)
