"""Marketings Versandauftraege — Logik und Verdrahtung, ohne Datenbank.

Betreiber-Entscheid 12.09.2026: sales-claw ist der EINZIGE Versandweg. Was
diese Tests festhalten, ist genau das Versprechen dieses Entscheids:

  * Ein Auftrag ist eine BITTE. Er wird hoechstens zu einem Entwurf, nie zu
    einer Sendung — und nur durch entwurf_erstellen, also durch alle Tore.
  * Faellt er an einem Tor durch, geht der Torfehler WOERTLICH an Marketing
    zurueck. Marketing soll nicht raten muessen und muss dafuer nichts in
    sales.* lesen duerfen.
  * Ohne passenden Kontakt entsteht KEIN Kontakt und KEIN Entwurf. Bestand
    anlegen ist eine Entscheidung des Betreibers.

`q` wird aufgezeichnet bzw. nach SQL-Teilstrings verteilt — die Tests
beweisen die Reihenfolge der Griffe und die Fehlerpfade, nicht die Datenbank.
"""
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
os.environ.setdefault("SALES_DB_URL", "postgresql://x:y@127.0.0.1:1/x")

import lead_fluss  # noqa: E402
import server  # noqa: E402


class Rekorder:
    def __init__(self, antworten=None):
        self.aufrufe = []
        self.antworten = list(antworten or [])

    def __call__(self, sql, params=()):
        self.aufrufe.append((sql, params))
        return self.antworten.pop(0) if self.antworten else []


def verteiler(antworten):
    """antworten: Liste von (sql_teil, rueckgabe). Erster Treffer gewinnt."""
    aufrufe = []

    def q(sql, params=()):
        aufrufe.append((sql, params))
        for teil, wert in antworten:
            if teil in sql:
                return wert
        return []
    q.aufrufe = aufrufe
    return q


AUFTRAG = {"id": "a-1", "kanal": "email", "empfaenger": "anna@firma.de",
           "betreff": "Neues aus dem Haus", "nachricht": "Hallo Anna",
           "medien_datei": "", "kampagne": "Herbst", "quelle": "broadcast_proposal:x",
           "seit": "2026-09-12"}


def _offene(auftrag):
    """Antwort-Paar fuer den Verteiler: die SECURITY-DEFINER-Funktion."""
    return ("versandauftraege_offen", [auftrag] if auftrag else [])


# --- Logik in lead_fluss ---------------------------------------------------

def test_offene_auftraege_gehen_ueber_die_db_funktion():
    q = Rekorder([[AUFTRAG]])
    lead_fluss.versandauftraege_offen(q, 5)
    sql, params = q.aufrufe[0]
    assert "marketing.versandauftraege_offen" in sql
    # sales_app liest marketing.versandauftraege NIE direkt.
    assert "from marketing.versandauftraege " not in sql
    assert params == (5,)


def test_erledigen_reicht_status_draft_und_grund_durch():
    q = Rekorder([[{"ok": True}]])
    assert lead_fluss.versandauftrag_erledigen(q, "a-1", "angenommen", "d-9", "") is True
    sql, params = q.aufrufe[0]
    assert "marketing.versandauftrag_erledigen" in sql
    assert params == ("a-1", "angenommen", "d-9", "")


def test_empfaenger_leads_sucht_die_mail_klein_und_getrimmt():
    q = Rekorder([[{"id": "l1", "name": "Anna", "email": "anna@firma.de", "phone": ""}]])
    treffer = lead_fluss.empfaenger_leads(q, "  Anna@Firma.DE ",
                                          archiviert="ARCHIV", privat="PRIVAT")
    sql, params = q.aufrufe[0]
    assert "lower(btrim(coalesce(email, ''))) = %s" in sql
    assert "not ARCHIV" in sql and "not PRIVAT" in sql
    assert params == ("anna@firma.de",)
    assert [z["id"] for z in treffer] == ["l1"]


def test_empfaenger_leads_beim_telefon_grenzt_ein_und_entscheidet_genau():
    """Die Datenbank grenzt ueber die letzten acht Ziffern ein — das trifft
    auch eine oesterreichische Nummer mit derselben Endung. Die genaue
    Entscheidung faellt mit derselben Normalisierung wie die Verbotsliste."""
    q = Rekorder([[
        {"id": "l1", "name": "Anna", "email": "", "phone": "+49 170 111 2233"},
        {"id": "lx", "name": "Fast gleich", "email": "", "phone": "+43 170 111 2233"},
    ]])
    treffer = lead_fluss.empfaenger_leads(q, "01701112233",
                                          archiviert="A", privat="P")
    sql, params = q.aufrufe[0]
    assert "regexp_replace" in sql and "like %s" in sql
    assert params == ("%01112233",)
    assert [z["id"] for z in treffer] == ["l1"]


def test_empfaenger_leads_ohne_lesbare_adresse_fragt_gar_nicht():
    q = Rekorder()
    assert lead_fluss.empfaenger_leads(q, "weder-noch", archiviert="A", privat="P") == []
    assert q.aufrufe == []


def test_auftrag_notiz_nennt_kanal_kampagne_und_quelle():
    notiz = lead_fluss.auftrag_notiz(AUFTRAG)
    assert "email" in notiz and "Herbst" in notiz and "broadcast_proposal:x" in notiz


# --- Verdrahtung in server.py ----------------------------------------------

def test_pruefen_ist_nur_lesend(monkeypatch):
    q = verteiler([_offene(AUFTRAG)])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.versandauftraege_pruefen())
    assert out["offen"] == 1
    assert out["auftraege"][0]["nachricht"] == "Hallo Anna"
    assert all("insert" not in sql.lower() and "update" not in sql.lower()
               for sql, _ in q.aufrufe)


def test_unbekannter_auftrag_ist_ein_fehler_keine_absage(monkeypatch):
    q = verteiler([_offene(None)])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert "Kein offener Versandauftrag" in out["fehler"]
    # Nichts erledigen: ein Auftrag, den es nicht gibt, wird nicht abgelehnt.
    assert all("versandauftrag_erledigen" not in sql for sql, _ in q.aufrufe)


def test_ohne_kontakt_wird_abgelehnt_und_kein_kontakt_angelegt(monkeypatch):
    q = verteiler([_offene(AUFTRAG),
                   ("from leads", []),
                   ("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)

    def darf_nicht(*a, **k):
        raise AssertionError("es wurde ein Kontakt angelegt")
    monkeypatch.setattr(server, "kontakt_anlegen", darf_nicht)

    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert out["abgelehnt"] is True
    assert "Kein Kontakt in sales-claw" in out["grund"]
    erledigt = [p for sql, p in q.aufrufe if "versandauftrag_erledigen" in sql]
    assert erledigt and erledigt[0][1] == "abgelehnt"
    assert "anna@firma.de" in erledigt[0][3]


def test_mehrere_kontakte_werden_abgelehnt_mit_beiden_namen(monkeypatch):
    q = verteiler([_offene(AUFTRAG),
                   ("from leads", [{"id": "l1", "name": "Anna A", "email": "anna@firma.de", "phone": ""},
                                   {"id": "l2", "name": "Anna B", "email": "anna@firma.de", "phone": ""}]),
                   ("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert "Anna A" in out["grund"] and "Anna B" in out["grund"]


def test_ein_tor_das_ablehnt_gibt_seinen_grund_woertlich_an_marketing(monkeypatch):
    """Der Kern des Entscheids: die Tore bleiben in entwurf_erstellen, und ihr
    Wortlaut ist das, was Marketing zu sehen bekommt."""
    torfehler = ("Kontakt ist nicht fuer WhatsApp freigegeben — es entsteht "
                 "kein Entwurf.")
    q = verteiler([_offene({**AUFTRAG, "kanal": "whatsapp", "empfaenger": "+491701112233"}),
                   ("from leads", [{"id": "l1", "name": "Anna", "email": "",
                                    "phone": "+491701112233"}]),
                   ("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "entwurf_erstellen",
                        lambda *a, **k: json.dumps({"fehler": torfehler}))
    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert out["grund"] == torfehler
    erledigt = [p for sql, p in q.aufrufe if "versandauftrag_erledigen" in sql][0]
    assert erledigt[3] == torfehler


def test_erfolg_erzeugt_einen_pending_entwurf_und_bucht_den_auftrag(monkeypatch):
    gesehen = {}

    def falscher_entwurf(lead_id, kanal, text, betreff="", medien_datei=""):
        gesehen.update(lead_id=lead_id, kanal=kanal, text=text,
                       betreff=betreff, medien_datei=medien_datei)
        return json.dumps({"draft_id": "d-9", "status": "pending",
                           "medien_datei": None, "hinweis": "Nicht versendet."})

    q = verteiler([_offene(AUFTRAG),
                   ("from leads", [{"id": "l1", "name": "Anna",
                                    "email": "anna@firma.de", "phone": ""}]),
                   ("insert into activities", [{"id": "akt-1"}]),
                   ("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "entwurf_erstellen", falscher_entwurf)

    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert out["draft_id"] == "d-9"
    assert out["status"] == "pending"        # nichts ist rausgegangen
    assert out["lead_id"] == "l1"
    assert out["auftrag_erledigt"] is True
    # Der Auftrag wurde unveraendert weitergereicht.
    assert gesehen == {"lead_id": "l1", "kanal": "email", "text": "Hallo Anna",
                       "betreff": "Neues aus dem Haus", "medien_datei": ""}
    # Am Kontakt steht, woher die Nachricht kam.
    akt = [p for sql, p in q.aufrufe if "insert into activities" in sql][0]
    assert akt[1] == "versandauftrag_uebernommen"
    assert "broadcast_proposal:x" in akt[2]
    erledigt = [p for sql, p in q.aufrufe if "versandauftrag_erledigen" in sql][0]
    assert erledigt[1] == "angenommen" and erledigt[2] == "d-9"


def test_linkedin_post_geht_ohne_kontakt_und_nimmt_den_betreff_als_thema(monkeypatch):
    gesehen = {}

    def falscher_post(thema, text, medien_datei="", trotzdem=False):
        gesehen.update(thema=thema, text=text, medien_datei=medien_datei)
        return json.dumps({"draft_id": "d-post", "status": "pending"})

    auftrag = {**AUFTRAG, "kanal": "linkedin_post", "empfaenger": "",
               "betreff": "Warum bAV", "nachricht": "Ein langer Beitrag",
               "medien_datei": "bild.png"}
    q = verteiler([_offene(auftrag),
                   ("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    monkeypatch.setattr(server, "post_entwurf_erstellen", falscher_post)

    out = json.loads(server.versandauftrag_uebernehmen("a-1"))
    assert out["draft_id"] == "d-post"
    assert out["status"] == "pending"
    assert gesehen == {"thema": "Warum bAV", "text": "Ein langer Beitrag",
                       "medien_datei": "bild.png"}
    # Kein Kontakt gesucht, keine Aktivitaet am Kontakt — ein Beitrag gehoert
    # zu keinem Kunden.
    assert all("from leads" not in sql for sql, _ in q.aufrufe)
    assert all("insert into activities" not in sql for sql, _ in q.aufrufe)


def test_ablehnen_braucht_einen_grund(monkeypatch):
    q = verteiler([])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.versandauftrag_ablehnen("a-1", "   "))
    assert "grund fehlt" in out["fehler"]
    assert q.aufrufe == []


def test_ablehnen_bucht_den_grund(monkeypatch):
    q = verteiler([("versandauftrag_erledigen", [{"ok": True}])])
    monkeypatch.setattr(server, "_q", q)
    out = json.loads(server.versandauftrag_ablehnen("a-1", " passt nicht "))
    assert out["abgelehnt"] is True
    assert q.aufrufe[0][1] == ("a-1", "abgelehnt", "", "passt nicht")


def test_die_drei_werkzeuge_sind_registriert():
    namen = {w.__name__ for w in server.WERKZEUGE}
    assert {"versandauftraege_pruefen", "versandauftrag_uebernehmen",
            "versandauftrag_ablehnen"} <= namen
