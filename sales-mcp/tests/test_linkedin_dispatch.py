"""Vertragstests von sales-linkedin gegen sales_test — ohne echte API.

DREI RIEGEL GEGEN EINE ECHTE VEROEFFENTLICHUNG — sie muessen alle drei
stehen, weil die Suite mit `--env-file .env` laufen kann und damit das
ECHTE LinkedIn-Token in der Umgebung haette:

1. `SALES_DB_SCHEMA=sales_test` hart gesetzt (wie ueberall).
2. Die autouse-Fixture biegt `linkedin_api.bild_hochladen`,
   `video_hochladen` und `beitrag_erstellen` auf Attrappen um — und prueft
   anschliessend, dass dort auch wirklich die Attrappe steht.
3. `linkedin_api.BASIS` wird auf eine unerreichbare Adresse gebogen. Wenn
   ein kuenftiger Umbau eine Funktion vergisst umzubiegen, scheitert der
   Test mit einem Verbindungsfehler — er weicht nicht still zur echten API
   aus und stellt etwas auf das Profil eines Menschen.

Der wichtigste Test dieser Datei ist `test_direktnachricht_wird_nicht_...`:
er haelt fest, dass eine freigegebene LinkedIn-DIREKTNACHRICHT von diesem
Dienst nicht angefasst wird. Genau so eine lag beim Bau in der Datenbank.
"""
import io
import json
import os

import pytest

# HART, nicht setdefault: eine von aussen gesetzte SALES_DB_SCHEMA=sales
# wuerde die truncate-Fixture unten auf die echten Kundendaten loslassen.
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import dispatch  # noqa: E402
import linkedin_api  # noqa: E402
import linkedin_dispatch as ld  # noqa: E402
import medien  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


class Attrappe:
    """Merkt sich, was veroeffentlicht worden WAERE."""

    def __init__(self):
        self.bilder = []
        self.videos = []
        self.beitraege = []
        self.fehler_bei_beitrag = None
        self.fehler_bei_bild = None

    def bild_hochladen(self, daten, mimetyp):
        if self.fehler_bei_bild:
            raise self.fehler_bei_bild
        self.bilder.append((len(daten), mimetyp))
        return f"urn:li:image:ATTRAPPE{len(self.bilder)}"

    def video_hochladen(self, daten, mimetyp="video/mp4"):
        self.videos.append((len(daten), mimetyp))
        return f"urn:li:video:ATTRAPPE{len(self.videos)}"

    def beitrag_erstellen(self, text, bilder=None, video=None,
                          sichtbarkeit="PUBLIC"):
        if self.fehler_bei_beitrag:
            raise self.fehler_bei_beitrag
        self.beitraege.append({"text": text, "bilder": list(bilder or []),
                               "video": video})
        return f"urn:li:share:ATTRAPPE{len(self.beitraege)}"


@pytest.fixture(autouse=True)
def umgebung(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")

    attrappe = Attrappe()
    # Die gebundenen Methoden EINMAL festhalten: jeder Attributzugriff auf
    # `attrappe.beitrag_erstellen` erzeugt ein neues Methodenobjekt, ein
    # `is`-Vergleich gegen einen zweiten Zugriff waere deshalb immer falsch —
    # und die Riegelpruefung unten damit wertlos.
    echte = {"bild_hochladen": attrappe.bild_hochladen,
             "video_hochladen": attrappe.video_hochladen,
             "beitrag_erstellen": attrappe.beitrag_erstellen}
    for name, funktion in echte.items():
        monkeypatch.setattr(linkedin_api, name, funktion)
    # Riegel 3: selbst wenn eine Funktion vergessen wuerde, ginge nichts raus.
    monkeypatch.setattr(linkedin_api, "BASIS", "http://127.0.0.1:1")
    for name, funktion in echte.items():
        assert getattr(linkedin_api, name) is funktion, (
            f"{name} ist nicht auf die Attrappe gebogen — der Test wuerde "
            f"gegen die ECHTE LinkedIn-API laufen.")

    # Eigener Medienordner je Test — der echte ist read-only gemountet.
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    return attrappe


@pytest.fixture()
def sammel():
    return str(server._q(
        "insert into leads (name, source) values "
        "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"])


def _entwurf(lead_id, body="Hallo Netzwerk", media_ref=None,
             recipient="eigenes-profil", status="approved",
             channel="linkedin", subject="Post: Test"):
    zeile = server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref) values (%s, %s, %s, %s, %s, %s) returning id",
        (lead_id, channel, recipient, subject, body, media_ref))[0]
    if status != "pending":
        server._q("update drafts set status = %s where id = %s",
                  (status, zeile["id"]))
    return zeile["id"]


def _status(draft_id):
    return server._q("select status, error from drafts where id = %s",
                     (draft_id,))[0]


def _datei(tmp_path, name, groesse=64):
    pfad = tmp_path / name
    pfad.write_bytes(b"x" * groesse)
    return name


# ---------------------------------------------------------------------------
# Die Sicherheitskante
# ---------------------------------------------------------------------------

def test_direktnachricht_wird_nicht_veroeffentlicht(umgebung, sammel):
    """Eine freigegebene LinkedIn-DM darf dieser Dienst NIE anfassen.

    Sie ist an einen Menschen gerichtet; als Beitrag stuende ihr Text
    oeffentlich auf dem Profil. Genau so ein Entwurf lag beim Bau dieses
    Dienstes freigegeben in der Datenbank.
    """
    dm = _entwurf(sammel, body="Hallo Frau Probekunde, haetten Sie Zeit?",
                  recipient="Lisa Probekunde", subject="LinkedIn-Erstkontakt")
    assert ld.claim(dm) is None
    assert ld.verarbeite_draft(dm) == "uebersprungen"
    assert umgebung.beitraege == []
    # Sie taucht auch nicht als wartender Beitrag auf.
    assert [z["id"] for z in ld.wartende_beitraege()] == []
    # Und der Entwurf steht unveraendert da — nicht geclaimt, nicht failed.
    zeile = _status(dm)
    assert zeile["status"] == "approved"
    assert zeile["error"] is None


def test_nur_der_genannte_entwurf_geht_raus(umgebung, sammel):
    """Exact-ID-One-Shot: die Freigabe gilt EINEM Beitrag.

    Frueher nahm dieser Dienst einen Stapel. Wer einen Beitrag freigab und
    den Dienst startete, veroeffentlichte damit auch alles andere, was
    irgendwann auf `approved` stehen geblieben war.
    """
    alt1 = _entwurf(sammel, body="Vor Wochen freigegeben und vergessen")
    alt2 = _entwurf(sammel, body="Ebenfalls vergessen")
    gewollt = _entwurf(sammel, body="Der Beitrag, den ich jetzt will")

    assert ld.verarbeite_draft(gewollt) == "veroeffentlicht"

    assert len(umgebung.beitraege) == 1
    assert umgebung.beitraege[0]["text"] == "Der Beitrag, den ich jetzt will"
    assert _status(gewollt)["status"] == "sent"
    # Die beiden anderen sind unberuehrt — nicht geclaimt, nicht gepostet.
    for d in (alt1, alt2):
        zeile = _status(d)
        assert zeile["status"] == "approved"
        assert zeile["error"] is None


def test_wartende_beitraege_listet_nur_eigene_profil_entwuerfe(umgebung, sammel):
    _entwurf(sammel, recipient="Lisa Probekunde")             # DM
    _entwurf(sammel, status="pending")                        # nicht frei
    _entwurf(sammel, status="rejected")                       # abgelehnt
    _entwurf(sammel, channel="whatsapp", recipient="+4915112345678")
    gut = _entwurf(sammel, body="Der einzige echte Beitrag")
    wartend = ld.wartende_beitraege()
    assert [str(z["id"]) for z in wartend] == [str(gut)]
    assert umgebung.beitraege == []      # Auflisten postet nichts


# ---------------------------------------------------------------------------
# Die drei Beitragsarten
# ---------------------------------------------------------------------------

def test_reiner_text(umgebung, sammel):
    d = _entwurf(sammel, body="Wir suchen Verstaerkung.")
    assert ld.verarbeite_draft(d) == "veroeffentlicht"
    assert umgebung.beitraege == [{"text": "Wir suchen Verstaerkung.",
                                   "bilder": [], "video": None}]
    assert umgebung.bilder == [] and umgebung.videos == []
    assert _status(d)["status"] == "sent"


def test_ein_bild(umgebung, sammel, tmp_path):
    name = _datei(tmp_path, "buero.png", 128)
    d = _entwurf(sammel, media_ref=name)
    assert ld.verarbeite_draft(d) == "veroeffentlicht"
    assert umgebung.bilder == [(128, "image/png")]
    assert umgebung.beitraege[0]["bilder"] == ["urn:li:image:ATTRAPPE1"]
    assert umgebung.beitraege[0]["video"] is None


def test_mehrere_bilder(umgebung, sammel, tmp_path):
    namen = [_datei(tmp_path, f"bild{i}.jpg", 32) for i in range(3)]
    d = _entwurf(sammel, media_ref=", ".join(namen))
    assert ld.verarbeite_draft(d) == "veroeffentlicht"
    assert len(umgebung.bilder) == 3
    assert umgebung.beitraege[0]["bilder"] == [
        "urn:li:image:ATTRAPPE1", "urn:li:image:ATTRAPPE2",
        "urn:li:image:ATTRAPPE3"]


def test_video(umgebung, sammel, tmp_path):
    name = _datei(tmp_path, "produkt.mp4", 4096)
    d = _entwurf(sammel, media_ref=name)
    assert ld.verarbeite_draft(d) == "veroeffentlicht"
    assert umgebung.videos == [(4096, "video/mp4")]
    assert umgebung.beitraege[0]["video"] == "urn:li:video:ATTRAPPE1"
    assert umgebung.beitraege[0]["bilder"] == []


# ---------------------------------------------------------------------------
# Was NICHT rausgeht — und nie als Text ersatzweise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dateien,brocken", [
    (["a.png", "b.mp4"], "entweder Bilder oder ein Video"),
    (["a.mp4", "b.mp4"], "hoechstens ein Video"),
    (["unterlage.pdf"], "nicht verwendbar"),
    (["ton.mp3"], "nicht verwendbar"),
])
def test_unbrauchbare_medien_gehen_gar_nicht_raus(umgebung, sammel, tmp_path,
                                                  dateien, brocken):
    for n in dateien:
        _datei(tmp_path, n)
    d = _entwurf(sammel, media_ref=",".join(dateien))
    assert ld.verarbeite_draft(d) == "medien_unbrauchbar"
    # Der Kern: KEIN Ersatzbeitrag als reiner Text.
    assert umgebung.beitraege == []
    zeile = _status(d)
    assert zeile["status"] == "failed"
    assert brocken in zeile["error"]
    assert "NICHTS raus" in zeile["error"]


def test_fehlende_datei_geht_nicht_raus(umgebung, sammel):
    d = _entwurf(sammel, media_ref="gibtsnicht.png")
    assert ld.verarbeite_draft(d) == "medien_unbrauchbar"
    assert umgebung.beitraege == []
    assert _status(d)["status"] == "failed"


def test_pfad_im_medienfeld_wird_abgewiesen(umgebung, sammel):
    d = _entwurf(sammel, media_ref="..\\windows\\system.ini")
    assert ld.verarbeite_draft(d) == "medien_unbrauchbar"
    assert umgebung.beitraege == []


def test_zu_viele_bilder(umgebung, sammel, tmp_path):
    namen = [_datei(tmp_path, f"b{i}.png", 8) for i in range(ld.BILDER_MAX + 1)]
    d = _entwurf(sammel, media_ref=",".join(namen))
    assert ld.verarbeite_draft(d) == "medien_unbrauchbar"
    assert umgebung.beitraege == []
    assert "hoechstens" in _status(d)["error"]


def test_leerer_text(umgebung, sammel):
    d = _entwurf(sammel, body="   ")
    assert ld.verarbeite_draft(d) == "leer"
    assert umgebung.beitraege == []
    assert _status(d)["status"] == "failed"


# ---------------------------------------------------------------------------
# Claim: at-most-once
# ---------------------------------------------------------------------------

def test_claim_ist_einmalig(umgebung, sammel):
    d = _entwurf(sammel)
    erst = ld.claim(d)
    assert erst is not None
    assert ld.claim(d) is None            # zweiter Greifer geht leer aus
    assert _status(d)["error"].startswith(dispatch.CLAIM_PRAEFIX)


def test_kein_zweiter_beitrag_nach_veroeffentlichung(umgebung, sammel):
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "veroeffentlicht"
    # Ein zweiter Durchlauf darf NICHT noch einmal posten — und er scheitert
    # jetzt am Beleg, nicht erst am Status. Das ist der Unterschied: der
    # Status liesse sich zuruecksetzen, der Beleg nicht.
    assert ld.verarbeite_draft(d) == "schon_veroeffentlicht"
    assert len(umgebung.beitraege) == 1


def test_buchung_scheitert_kein_zweiter_beitrag(umgebung, sammel, monkeypatch):
    """Beitrag steht oeffentlich, Buchung schlaegt fehl — kein zweiter Lauf."""
    monkeypatch.setattr(ld, "_als_gesendet_buchen", lambda *a, **k: False)
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "veroeffentlicht_ohne_buchung"
    assert len(umgebung.beitraege) == 1
    assert _status(d)["status"] == "failed"
    # Und selbst ein direkter zweiter Aufruf postet nicht noch einmal.
    assert ld.verarbeite_draft(d) == "schon_veroeffentlicht"
    assert len(umgebung.beitraege) == 1


# ---------------------------------------------------------------------------
# Die Sperre gegen den zweiten Beitrag
#
# Der Fall, den ein fremdes Review benannte: ein Beitrag ist draussen, die
# Buchung scheiterte, der Entwurf liegt auf `failed`. Genau dort greift
# `entwurf_erneut_freigeben` mit bestaetigt=True und holt ihn auf
# `approved` zurueck — bei WhatsApp eine vertretbare Betreiberentscheidung,
# hier ein zweiter oeffentlicher Beitrag.
# ---------------------------------------------------------------------------

def test_erneute_freigabe_postet_nicht_ein_zweites_mal(umgebung, sammel,
                                                       monkeypatch):
    """Der harte Fall: veroeffentlicht, Buchung kaputt, wieder freigegeben."""
    monkeypatch.setattr(ld, "_als_gesendet_buchen", lambda *a, **k: False)
    d = _entwurf(sammel, body="Geht genau einmal raus")
    assert ld.verarbeite_draft(d) == "veroeffentlicht_ohne_buchung"
    assert len(umgebung.beitraege) == 1

    # Ein Mensch setzt den Entwurf zurueck auf approved — genau das, was
    # entwurf_erneut_freigeben(bestaetigt=True) tut.
    server._q("update drafts set status = 'approved', error = null "
              "where id = %s", (d,))
    assert _status(d)["status"] == "approved"

    assert ld.verarbeite_draft(d) == "schon_veroeffentlicht"
    assert len(umgebung.beitraege) == 1        # KEIN zweiter Beitrag
    # Und der Entwurf wurde dabei nicht angefasst: kein Claim, keine Marke.
    zeile = _status(d)
    assert zeile["status"] == "approved"
    assert zeile["error"] is None


def test_beleg_steht_vor_der_buchung(umgebung, sammel, monkeypatch):
    """Scheitert die Buchung, existiert der Nachweis trotzdem.

    Das ist die Bedingung dafuer, dass die Sperre ueberhaupt greifen kann:
    stand der Beleg hinter der Buchung, gab es bei kaputter Buchung keinen
    Eintrag — und der naechste Lauf haette den Entwurf durchgewunken.
    """
    monkeypatch.setattr(ld, "_als_gesendet_buchen", lambda *a, **k: False)
    d = _entwurf(sammel)
    ld.verarbeite_draft(d)
    zeilen = server._q("select payload from activities where type = 'versand'")
    assert len(zeilen) == 1
    last = zeilen[0]["payload"]
    if isinstance(last, str):
        last = json.loads(last)
    assert last["beitrag"].startswith("urn:li:share:")
    assert ld.bereits_veroeffentlicht(d) == last["beitrag"]


def test_ohne_beleg_keine_sperre(umgebung, sammel):
    """Gegenprobe: ein unberuehrter Entwurf ist nicht gesperrt."""
    d = _entwurf(sammel)
    assert ld.bereits_veroeffentlicht(d) is None


def test_sperre_verwechselt_entwuerfe_nicht(umgebung, sammel):
    """Der Beleg des einen darf den anderen nicht blockieren."""
    a = _entwurf(sammel, body="A")
    b = _entwurf(sammel, body="B")
    assert ld.verarbeite_draft(a) == "veroeffentlicht"
    assert ld.bereits_veroeffentlicht(b) is None
    assert ld.verarbeite_draft(b) == "veroeffentlicht"
    assert [x["text"] for x in umgebung.beitraege] == ["A", "B"]


def test_beleg_eines_anderen_kanals_sperrt_nicht(umgebung, sammel):
    """Eine WhatsApp-Versandzeile darf keinen LinkedIn-Beitrag blockieren."""
    d = _entwurf(sammel)
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s) returning id",
        (sammel, json.dumps({"draft_id": str(d), "kanal": "whatsapp"})))
    assert ld.bereits_veroeffentlicht(d) is None
    assert ld.verarbeite_draft(d) == "veroeffentlicht"


# ---------------------------------------------------------------------------
# Der unbekannte externe Erfolgszustand
#
# Eine Zeitueberschreitung heisst NICHT „nicht angekommen". Der Beitrag kann
# oeffentlich stehen, waehrend wir einen Fehler buchen. Genau das nennt das
# Sperrgate des Proxmox-Runbooks „unbekannter externer Erfolgszustand".
# ---------------------------------------------------------------------------

def test_ungewisser_ausgang_sperrt_jede_wiederholung(umgebung, sammel):
    umgebung.fehler_bei_beitrag = linkedin_api.LinkedInFehler(
        "Zeitueberschreitung bei /rest/posts nach 30s", dauerhaft=False,
        ungewiss=True)
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "ungewiss"

    zeile = _status(d)
    assert zeile["status"] == "failed"
    assert zeile["error"].startswith("UNGEWISS:")
    assert "KANN oeffentlich stehen" in zeile["error"]

    # Der Beleg ist da, sagt aber ausdruecklich nicht "veroeffentlicht".
    zeilen = server._q("select payload from activities where type = 'versand'")
    assert len(zeilen) == 1
    last = zeilen[0]["payload"]
    if isinstance(last, str):
        last = json.loads(last)
    assert last["ungewiss"] is True
    assert last["beitrag"] is None

    # Und er sperrt — auch nach einer erneuten Freigabe von Hand.
    umgebung.fehler_bei_beitrag = None
    server._q("update drafts set status = 'approved', error = null "
              "where id = %s", (d,))
    assert ld.verarbeite_draft(d) == "schon_veroeffentlicht"
    assert umgebung.beitraege == []


def test_eindeutiger_fehler_sperrt_nicht(umgebung, sammel):
    """Ein 4xx IST die Aussage: es ist nichts entstanden, Retry erlaubt."""
    umgebung.fehler_bei_beitrag = linkedin_api.LinkedInFehler(
        "HTTP 422 bei /rest/posts", dauerhaft=True, status=422, ungewiss=False)
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "fehler"
    assert ld.bereits_veroeffentlicht(d) is None
    assert server._q(
        "select id from activities where type = 'versand'") == []

    # Nach dem Beheben laeuft er durch.
    umgebung.fehler_bei_beitrag = None
    server._q("update drafts set status = 'approved', error = null "
              "where id = %s", (d,))
    assert ld.verarbeite_draft(d) == "veroeffentlicht"


def test_upload_fehler_erzeugt_keine_sperre(umgebung, sammel, tmp_path):
    """Ein Upload veroeffentlicht nichts — er darf nichts blockieren."""
    umgebung.fehler_bei_bild = linkedin_api.LinkedInFehler(
        "Upload abgelehnt (HTTP 400)")
    _datei(tmp_path, "bild.png")
    d = _entwurf(sammel, media_ref="bild.png")
    assert ld.verarbeite_draft(d) == "fehler"
    assert ld.bereits_veroeffentlicht(d) is None
    assert server._q("select id from activities where type = 'versand'") == []


@pytest.mark.parametrize("status,ungewiss", [
    (400, False), (403, False), (404, False), (422, False),
    (408, True), (500, True), (502, True), (503, True),
])
def test_ungewissheit_wird_am_status_erkannt(monkeypatch, status, ungewiss):
    """4xx ist eine Antwort, 5xx und 408 sind keine verwertbare Aussage."""
    import urllib.error

    def falsches_urlopen(anfrage, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.linkedin.com/rest/posts", status, "x", {},
            io.BytesIO(b'{"message":"x"}'))

    monkeypatch.setattr(linkedin_api.urllib.request, "urlopen",
                        falsches_urlopen)
    with pytest.raises(linkedin_api.LinkedInFehler) as e:
        linkedin_api._json_ruf("/rest/posts", {"a": 1})
    assert e.value.ungewiss is ungewiss


def test_zeitueberschreitung_ist_ungewiss(monkeypatch):
    def falsches_urlopen(anfrage, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(linkedin_api.urllib.request, "urlopen",
                        falsches_urlopen)
    with pytest.raises(linkedin_api.LinkedInFehler) as e:
        linkedin_api._json_ruf("/rest/posts", {"a": 1})
    assert e.value.ungewiss is True
    assert e.value.dauerhaft is False
    assert "UNBEKANNT" in str(e.value)


# ---------------------------------------------------------------------------
# Fehler der Gegenseite
# ---------------------------------------------------------------------------

def test_api_fehler_wird_gebucht(umgebung, sammel):
    umgebung.fehler_bei_beitrag = linkedin_api.LinkedInFehler(
        "HTTP 422 bei /rest/posts: irgendwas", dauerhaft=True, status=422)
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "fehler"
    zeile = _status(d)
    assert zeile["status"] == "failed"
    assert "422" in zeile["error"]


def test_upload_fehler_hinterlaesst_keinen_beitrag(umgebung, sammel, tmp_path):
    umgebung.fehler_bei_bild = linkedin_api.LinkedInFehler(
        "Upload abgelehnt (HTTP 400)")
    _datei(tmp_path, "bild.png")
    d = _entwurf(sammel, media_ref="bild.png")
    assert ld.verarbeite_draft(d) == "fehler"
    assert umgebung.beitraege == []
    assert _status(d)["status"] == "failed"


def test_unerwarteter_fehler_reisst_dienst_nicht_ab(umgebung, sammel):
    umgebung.fehler_bei_beitrag = RuntimeError("etwas voellig anderes")
    d = _entwurf(sammel)
    assert ld.verarbeite_draft(d) == "fehler"
    zeile = _status(d)
    assert zeile["status"] == "failed"
    assert "RuntimeError" in zeile["error"]


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------

def test_versand_wird_protokolliert(umgebung, sammel, tmp_path):
    _datei(tmp_path, "clip.mp4", 512)
    d = _entwurf(sammel, media_ref="clip.mp4")
    ld.verarbeite_draft(d)
    zeilen = server._q(
        "select payload from activities where type = 'versand'")
    assert len(zeilen) == 1
    last = zeilen[0]["payload"]
    if isinstance(last, str):
        last = json.loads(last)
    assert last["kanal"] == "linkedin"
    assert last["weg"] == "linkedin-dispatcher"
    assert last["medienart"] == "video"
    assert last["beitrag"].startswith("urn:li:share:")


def test_kein_protokoll_ohne_veroeffentlichung(umgebung, sammel):
    umgebung.fehler_bei_beitrag = linkedin_api.LinkedInFehler("nein")
    d = _entwurf(sammel)
    ld.verarbeite_draft(d)
    assert server._q(
        "select id from activities where type = 'versand'") == []


# ---------------------------------------------------------------------------
# Inert ohne Konfiguration
# ---------------------------------------------------------------------------

def test_ohne_token_wird_nichts_veroeffentlicht(umgebung, sammel, monkeypatch):
    monkeypatch.setattr(linkedin_api, "TOKEN", "")
    monkeypatch.setattr(linkedin_api, "PERSON_URN", "")
    _entwurf(sammel)
    assert linkedin_api.fehlende_konfiguration() == [
        "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN"]
    assert ld.main() == 0        # Exit 0, kein Ausfall
    assert umgebung.beitraege == []


# ---------------------------------------------------------------------------
# Der Einstieg: ohne genannte Kennung passiert nichts
# ---------------------------------------------------------------------------

@pytest.fixture()
def eingerichtet(monkeypatch):
    """Konfiguration vortaeuschen, damit main() ueberhaupt bis zur Arbeit kommt.

    Die Suite laeuft mit ausgeblanktem LINKEDIN_ACCESS_TOKEN (Riegel 4), und
    `main()` steigt bei fehlender Konfiguration korrekt sofort aus. Fuer die
    Tests des Einstiegs muss dieser Riegel also gezielt gelockert werden —
    die Attrappen aus `umgebung` stehen weiterhin davor, es geht nichts raus.
    """
    monkeypatch.setattr(linkedin_api, "TOKEN", "attrappe-token")
    monkeypatch.setattr(linkedin_api, "PERSON_URN", "urn:li:person:ATTRAPPE")


def test_main_ohne_kennung_nimmt_freigegebene_selbst(umgebung, eingerichtet,
                                                     sammel, monkeypatch):
    """UMGEDREHT am 30.08.2026 auf Betreiber-Entscheid „freigabe soll
    gleich versand machen".

    Vorher galt hier: ohne genannte Kennung geht NICHTS raus — die Lehre
    aus dem Doppelpost vom 26.08., als ein Stapellauf einen vergessenen
    freigegebenen Beitrag veroeffentlichte. Diese Sorge ist nicht
    verschwunden, sie wird nur anders abgefangen: Tageskadenz (hoechstens
    einer) und Frischegrenze (nichts laenger als LINKEDIN_FRISCHE_TAGE
    Freigegebenes) — beides eigens getestet.

    LINKEDIN_ONCE beendet die Schleife nach einer Runde; ohne das liefe
    main() hier endlos, und genau daran haengt dieser Test frueher
    haengengeblieben.
    """
    monkeypatch.setattr(ld, "DRAFT_ID", "")
    monkeypatch.setattr(ld, "LINKEDIN_ONCE", True)
    _entwurf(sammel, body="Erster.")
    _entwurf(sammel, body="Zweiter.")
    assert ld.main() == 0
    assert len(umgebung.beitraege) == 1          # Kadenz: genau einer
    assert umgebung.beitraege[0]["text"] == "Erster."


def test_main_mit_unsinniger_kennung_bricht_ab(umgebung, eingerichtet,
                                               sammel, monkeypatch):
    monkeypatch.setattr(ld, "DRAFT_ID", "der-erste-halt")
    _entwurf(sammel)
    assert ld.main() == 2
    assert umgebung.beitraege == []


def test_main_nimmt_genau_die_genannte_kennung(umgebung, eingerichtet,
                                               sammel, monkeypatch):
    anderer = _entwurf(sammel, body="Nicht dieser")
    gewollt = _entwurf(sammel, body="Dieser")
    monkeypatch.setattr(ld, "DRAFT_ID", str(gewollt))
    assert ld.main() == 0
    assert [x["text"] for x in umgebung.beitraege] == ["Dieser"]
    assert _status(anderer)["status"] == "approved"


# ---------------------------------------------------------------------------
# Textschutz (reine Funktion, keine API)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("roh,erwartet", [
    ("(netto)", "\\(netto\\)"),
    ("#bAV", "\\#bAV"),
    ("a_b", "a\\_b"),
    ("kein Sonderzeichen", "kein Sonderzeichen"),
])
def test_textschutz(roh, erwartet):
    assert linkedin_api.text_schuetzen(roh) == erwartet


def test_backslash_wird_zuerst_geschuetzt():
    """Sonst schuetzte der Backslash die spaeter eingefuegten Schutzzeichen."""
    assert linkedin_api.text_schuetzen("a\\b") == "a\\\\b"
    assert linkedin_api.text_schuetzen("\\(") == "\\\\\\("


# ---------------------------------------------------------------------------
# Warten auf die Videoverarbeitung
#
# GEMESSEN: `finalizeUpload` heisst NICHT „fertig". Ein frisch hochgeladenes
# Video stand unmittelbar danach auf `WAITING_UPLOAD` und erst 11 Sekunden
# spaeter auf `AVAILABLE`. Ohne die Warteschleife waere der erste Videopost
# abgeprallt — diese Tests halten fest, dass sie da ist und richtig
# unterscheidet.
# ---------------------------------------------------------------------------

def test_warten_kehrt_bei_available_zurueck(monkeypatch):
    monkeypatch.setattr(linkedin_api, "video_status", lambda _u: "AVAILABLE")
    linkedin_api.auf_video_warten("urn:li:video:X", frist_s=0, takt_s=0)


def test_warten_haelt_zwischenzustaende_aus(monkeypatch):
    """WAITING_UPLOAD und PROCESSING sind kein Fehler, sondern Geduld."""
    staende = iter(["WAITING_UPLOAD", "PROCESSING", "PROCESSING", "AVAILABLE"])
    monkeypatch.setattr(linkedin_api, "video_status", lambda _u: next(staende))
    monkeypatch.setattr(linkedin_api.time, "sleep", lambda _s: None)
    linkedin_api.auf_video_warten("urn:li:video:X", frist_s=60, takt_s=1)


def test_warten_bricht_bei_verarbeitungsfehler_ab(monkeypatch):
    """Gescheiterte Verarbeitung ist dauerhaft — erneut freigeben hilft nicht."""
    monkeypatch.setattr(linkedin_api, "video_status",
                        lambda _u: "PROCESSING_FAILED")
    monkeypatch.setattr(linkedin_api.time, "sleep", lambda _s: None)
    with pytest.raises(linkedin_api.LinkedInFehler) as e:
        linkedin_api.auf_video_warten("urn:li:video:X", frist_s=60, takt_s=1)
    assert e.value.dauerhaft is True


def test_warten_laeuft_ab_und_ist_voruebergehend(monkeypatch):
    """Zeitueberschreitung ist NICHT dauerhaft: das Video ist ja schon oben."""
    monkeypatch.setattr(linkedin_api, "video_status", lambda _u: "PROCESSING")
    monkeypatch.setattr(linkedin_api.time, "sleep", lambda _s: None)
    with pytest.raises(linkedin_api.LinkedInFehler) as e:
        linkedin_api.auf_video_warten("urn:li:video:X", frist_s=2, takt_s=1)
    assert e.value.dauerhaft is False
    assert "NICHTS veroeffentlicht" in str(e.value)


def test_get_ruf_schickt_keinen_rumpf(monkeypatch):
    """`last=None` muss eine Anfrage OHNE Nutzlast werden.

    Mit `json.dumps(None)` reiste sonst der Text "null" als Rumpf mit — und
    ein GET mit Rumpf ist genau die Art Anfrage, die fremde Dienste
    unterschiedlich und meist schlecht behandeln.
    """
    gesehen = {}

    class Antwort:
        headers = {}

        def read(self):
            return b'{"status": "AVAILABLE"}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def falsches_urlopen(anfrage, timeout=None):
        gesehen["daten"] = anfrage.data
        gesehen["methode"] = anfrage.get_method()
        gesehen["url"] = anfrage.full_url
        return Antwort()

    monkeypatch.setattr(linkedin_api.urllib.request, "urlopen",
                        falsches_urlopen)
    assert linkedin_api.video_status("urn:li:video:A B") == "AVAILABLE"
    assert gesehen["daten"] is None
    assert gesehen["methode"] == "GET"
    # Die Kennung MUSS kodiert sein — unkodiert antwortet LinkedIn mit 400.
    assert "urn%3Ali%3Avideo%3AA%20B" in gesehen["url"]


# ---------------------------------------------------------------------------
# Dauerbetrieb (30.08.2026): Freigabe IST der Versand — Betreiber-Entscheid
# „freigabe soll gleich versand machen". Der Einmal-Modus mit genannter
# Kennung bleibt daneben bestehen (Handbetrieb, Notfall).
#
# Die alte Sorge aus dem Kopfkommentar — „vor Wochen freigegeben, laengst
# vergessen, jetzt oeffentlich" — faengt die Frischegrenze ab, nicht mehr
# das Fehlen einer Schleife.
# ---------------------------------------------------------------------------

def _tagesversand(lead_id, wann="now()"):
    """Ein bereits veroeffentlichter Beitrag von heute (bzw. `wann`)."""
    server._q(
        f"insert into activities (lead_id, type, payload, created_at) values "
        f"(%s, 'versand', %s, {wann}) returning id",
        (lead_id, server._json({"kanal": "linkedin",
                                "beitrag": "urn:li:ugcPost:ALT"})))


def test_eine_runde_veroeffentlicht_den_aeltesten_freigegebenen(umgebung, sammel):
    alt = _entwurf(sammel, body="Der aeltere Beitrag.")
    _entwurf(sammel, body="Der juengere Beitrag.")
    assert ld.eine_runde() == "veroeffentlicht"
    assert len(umgebung.beitraege) == 1
    assert umgebung.beitraege[0]["text"] == "Der aeltere Beitrag."
    assert server._q("select status from drafts where id = %s",
                     (alt,))[0]["status"] == "sent"


def test_hoechstens_einer_pro_tag(umgebung, sammel):
    """Die Tageskadenz des Betreibers steckt jetzt IM Dienst — vorher nur
    im MCP-Werkzeug, das ein Dauerlaeufer nie aufruft."""
    _entwurf(sammel, body="Erster.")
    _entwurf(sammel, body="Zweiter.")
    assert ld.eine_runde() == "veroeffentlicht"
    assert ld.eine_runde() == "kadenz"
    assert len(umgebung.beitraege) == 1


def test_gestern_veroeffentlicht_blockiert_heute_nicht(umgebung, sammel):
    _tagesversand(sammel, "now() - interval '1 day'")
    _entwurf(sammel, body="Heute dran.")
    assert ld.eine_runde() == "veroeffentlicht"


def test_ohne_freigabe_passiert_nichts(umgebung, sammel):
    _entwurf(sammel, status="pending")
    assert ld.eine_runde() == "nichts"
    assert umgebung.beitraege == []


def test_zu_lange_freigegebene_bleiben_liegen(umgebung, sammel):
    """„Vor Wochen freigegeben, laengst vergessen" darf nicht ploetzlich
    oeffentlich werden — es bleibt approved und wartet auf einen Menschen."""
    kennung = _entwurf(sammel, body="Uralt.")
    server._q("update drafts set approved_at = now() - interval '30 days' "
              "where id = %s returning id", (kennung,))
    assert ld.eine_runde() == "nichts"
    assert umgebung.beitraege == []
    assert server._q("select status from drafts where id = %s",
                     (kennung,))[0]["status"] == "approved"


def test_ein_zu_alter_blockiert_den_frischen_nicht(umgebung, sammel):
    alt = _entwurf(sammel, body="Uralt.")
    server._q("update drafts set approved_at = now() - interval '30 days' "
              "where id = %s returning id", (alt,))
    _entwurf(sammel, body="Frisch freigegeben.")
    assert ld.eine_runde() == "veroeffentlicht"
    assert umgebung.beitraege[0]["text"] == "Frisch freigegeben."


def test_der_einmal_modus_bleibt_erhalten(umgebung, sammel, monkeypatch):
    """Handbetrieb mit genannter Kennung — unveraendert, und er ignoriert
    die Tageskadenz bewusst: der Mensch hat genau diesen gemeint."""
    _tagesversand(sammel)
    kennung = _entwurf(sammel, body="Von Hand.")
    monkeypatch.setattr(ld, "DRAFT_ID", kennung)
    assert ld.eine_runde() == "veroeffentlicht"
    assert umgebung.beitraege[0]["text"] == "Von Hand."
