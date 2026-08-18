"""sales-mcp — Werkzeugdienst des sales-claw-Prototyps.

Dreizehn deutsche Werkzeuge über MCP (streamable-http). Kein Send-Werkzeug:
Entwürfe enden als drafts(status='pending') und werden über die
Freigabe-Werkzeuge nach 'approved'/'rejected' bewegt — den tatsächlichen
Versand macht ausschliesslich der Dispatcher (WhatsApp) bzw. quittiert der
Betreiber selbst (LinkedIn, entwurf_manuell_gesendet versendet nichts,
es protokolliert nur einen bereits erfolgten Handversand; Stufe-3-Plan
Grundsatzentscheidung 1+3).
"""
import functools
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import yaml
# Brief-Abweichung (gemessen mit `python -c "import mcp...; inspect.signature(...)"`
# im Container, installierte Version mcp==2.0.0 statt der vom Brief angenommenen
# 1.x-Reihe): `mcp.server.fastmcp.FastMCP` existiert nicht mehr — die Klasse
# heisst jetzt `MCPServer` und liegt unter `mcp.server.mcpserver`. Zusaetzlich
# nimmt ihr Konstruktor kein `host`/`port` mehr entgegen; beides wandert zu
# `.run(transport=..., host=..., port=...)`. `transport="streamable-http"`
# selbst ist unveraendert. Die Werkzeug-Funktionen unten sind davon nicht
# betroffen und bleiben wortgleich zum Brief.
from mcp.server.mcpserver import MCPServer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = os.environ.get("SALES_DB_SCHEMA", "sales")
if SCHEMA not in ("sales", "sales_test"):
    raise SystemExit(f"Unzulaessiges Schema '{SCHEMA}' — erlaubt: sales, sales_test")

LEITFADEN = yaml.safe_load(
    (Path(__file__).parent / "leitfaden.yaml").read_text(encoding="utf-8"))
ALLE_FRAGEN = {f["id"]: {"frage": f["frage"], "gruppe": g["titel"]}
               for g in LEITFADEN["gruppen"] for f in g["fragen"]}

pool = ConnectionPool(
    os.environ["SALES_DB_URL"], min_size=1, max_size=4, open=True,
    kwargs={"row_factory": dict_row, "options": f"-c search_path={SCHEMA}"})

DB_FEHLER = ("Datenbank nicht erreichbar — Protokoll und Profil werden gerade "
             "NICHT gespeichert. Sag das dem Gespraechspartner ausdruecklich "
             "und versuche es spaeter erneut.")

MCP_HOST = "0.0.0.0"
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))

mcp = MCPServer("sales-mcp")


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(sql: str, params=()):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _gesichert(fn):
    """DB-Ausfall wird zur definierten Meldung, nie zum Traceback (Spec §4).

    functools.wraps ist hier KEIN Stil, sondern Funktionsvoraussetzung: die
    MCP-Registrierung baut das Werkzeug-Schema aus inspect.signature(). Ein
    Wrapper, der nur __name__/__doc__ kopiert, liefert (*a, **kw) — das
    Schema ist dann leer und KEIN Agent kann irgendein Werkzeug aufrufen.
    Genau so in Task 4 passiert: Anbindung stand, jeder Aufruf scheiterte.
    """
    @functools.wraps(fn)
    def innen(*a, **kw):
        try:
            return fn(*a, **kw)
        except psycopg.OperationalError:
            return _json({"fehler": DB_FEHLER})
        except psycopg.Error as e:
            return _json({"fehler": f"Datenbankfehler ({e.sqlstate}): "
                                    f"{str(e).splitlines()[0][:200]}"})
    return innen


@_gesichert
def kontakt_suchen(text: str) -> str:
    """Kontakt per Name, E-Mail oder Telefonnummer finden. Immer zuerst
    aufrufen, bevor ein Kontakt neu angelegt wird."""
    zeilen = _q(
        "select id, name, status, consent_status from leads "
        "where name ilike %s or email ilike %s or phone ilike %s "
        "order by updated_at desc limit 10",
        (f"%{text}%", f"%{text}%", f"%{text}%"))
    return _json({"kontakte": [
        {"lead_id": z["id"], "name": z["name"], "status": z["status"],
         "consent": z["consent_status"]} for z in zeilen]})


@_gesichert
def kontakt_anlegen(name: str, email: str = "", phone: str = "",
                    source: str = "whatsapp", notes: str = "") -> str:
    """Neuen Kontakt anlegen. Nur verwenden, wenn kontakt_suchen leer war."""
    zeilen = _q(
        "insert into leads (name, email, phone, source, notes) "
        "values (%s, nullif(%s,''), nullif(%s,''), %s, nullif(%s,'')) "
        "returning id", (name, email, phone, source, notes))
    return _json({"lead_id": zeilen[0]["id"], "angelegt": True})


@_gesichert
def aktivitaet_loggen(lead_id: str, typ: str, inhalt: str) -> str:
    """Interaktion unveraenderlich protokollieren (nachricht, notiz, termin,
    offener_punkt, bedarf). Nach JEDER Kundeninteraktion aufrufen."""
    _q("insert into activities (lead_id, type, payload) values (%s, %s, %s) "
       "returning id", (lead_id, typ, json.dumps({"inhalt": inhalt},
                                                 ensure_ascii=False)))
    return _json({"geloggt": True})


@_gesichert
def profil_lesen(lead_id: str) -> str:
    """Kundenprofil samt der letzten Aktivitaeten lesen. Zu Gespraechsbeginn
    aufrufen, damit nichts doppelt gefragt wird."""
    leads = _q("select id, name, status, consent_status, enrichment, notes "
               "from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    akt = _q("select type, payload, actor, created_at from activities "
             "where lead_id = %s order by created_at desc limit 10", (lead_id,))
    e = leads[0]["enrichment"] or {}
    return _json({"lead_id": leads[0]["id"], "name": leads[0]["name"],
                  "status": leads[0]["status"],
                  "consent": leads[0]["consent_status"],
                  "profil": e.get("profil", {}), "bedarf": e.get("bedarf", {}),
                  "notes": leads[0]["notes"], "aktivitaeten": akt})


@_gesichert
def profil_aktualisieren(lead_id: str, feld: str, wert: str) -> str:
    """Ein Profilfeld setzen (kumulativ; bestehende Felder bleiben erhalten)."""
    # Brief-Abweichung: `jsonb_set(enrichment, '{profil,feld}', ..., true)` legt
    # den fehlenden Zwischenknoten `profil` NICHT an — `create_missing` erzeugt
    # laut Postgres-Doku nur das letzte Pfadelement, wenn dessen Elternobjekt
    # bereits existiert. `leads.enrichment` startet aber bei frischen Kontakten
    # als '{}'::jsonb (db/provision.sql), ohne `profil`-Schluessel — der Aufruf
    # aus dem Brief war damit auf frischen Kontakten ein stiller No-op (empirisch
    # gegen die DB geprueft: leeres Elternobjekt -> Ergebnis bleibt '{}'). Fix:
    # `profil` zuerst mit einem verschachtelten jsonb_set garantieren.
    zeilen = _q(
        "update leads set enrichment = jsonb_set("
        "jsonb_set(enrichment, '{profil}', coalesce(enrichment->'profil', '{}'::jsonb), true), "
        "%s, to_jsonb(%s::text), true) "
        "where id = %s returning id", (["profil", feld], wert, lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    return _json({"gesetzt": {feld: wert}})


@_gesichert
def bedarf_speichern(lead_id: str, frage_id: str, antwort: str) -> str:
    """Antwort auf eine Leitfaden-Frage strukturiert ablegen. frage_id muss
    aus bedarf_offen stammen."""
    if frage_id not in ALLE_FRAGEN:
        return _json({"fehler": f"Unbekannte frage_id '{frage_id}'. "
                                f"Gueltig: {sorted(ALLE_FRAGEN)}"})
    eintrag = {"antwort": antwort, "at": _jetzt()}
    # Verschachteltes jsonb_set — zwingend. Ein einfaches
    # jsonb_set(enrichment, '{bedarf,frage_id}', ..., true) legt den fehlenden
    # Zwischenknoten 'bedarf' NICHT an (create_missing erzeugt nur das letzte
    # Pfadelement) und ist auf frischen Kontakten ein stiller No-op. Exakt
    # dieser Fehler steckte in profil_aktualisieren und wurde in Task 2
    # empirisch belegt und behoben — dieses Muster spiegelt den Fix.
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, '{bedarf}', "
        "jsonb_set(coalesce(enrichment->'bedarf', '{}'::jsonb), %s, %s::jsonb, true), "
        "true) where id = %s returning id",
        ([frage_id], json.dumps(eintrag, ensure_ascii=False), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    if frage_id == "consent_kontakt":
        ja = antwort.strip().lower().startswith(("ja", "gern", "ok", "einverstanden"))
        _q("update leads set consent_status = %s where id = %s returning id",
           ("opt_in" if ja else "unknown", lead_id))
    _q("insert into activities (lead_id, type, payload) values (%s,'bedarf',%s) "
       "returning id",
       (lead_id, json.dumps({"frage_id": frage_id, "antwort": antwort},
                            ensure_ascii=False)))
    return _json({"gespeichert": frage_id})


@_gesichert
def bedarf_offen(lead_id: str) -> str:
    """Welche Leitfaden-Fragen sind noch offen? Vor jeder Frage aufrufen und
    nur Fehlendes fragen — nie etwas doppelt."""
    leads = _q("select enrichment from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    beantwortet = set((leads[0]["enrichment"] or {}).get("bedarf", {}))
    offen = [{"gruppe": g["titel"],
              "fragen": [f for f in g["fragen"] if f["id"] not in beantwortet]}
             for g in LEITFADEN["gruppen"]]
    offen = [g for g in offen if g["fragen"]]
    return _json({"anzahl_offen": sum(len(g["fragen"]) for g in offen),
                  "offen": offen})


@_gesichert
def entwurf_erstellen(lead_id: str, kanal: str, text: str,
                      betreff: str = "") -> str:
    """Beispiel-Nachricht in die Entwurfs-Queue legen. Kanaele: whatsapp,
    linkedin, email. Es wird NICHTS versendet — der Entwurf bleibt 'pending';
    den Versand uebernimmt spaeter eine andere App."""
    if kanal not in ("whatsapp", "linkedin", "email"):
        return _json({"fehler": f"Unzulaessiger Kanal '{kanal}'. "
                                f"Erlaubt: whatsapp, linkedin, email"})
    leads = _q("select name, phone, email from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    empfaenger = (leads[0]["phone"] if kanal == "whatsapp" else
                  leads[0]["email"] if kanal == "email" else leads[0]["name"])
    zeilen = _q(
        "insert into drafts (lead_id, channel, recipient, subject, body) "
        "values (%s, %s, %s, nullif(%s,''), %s) returning id, status",
        (lead_id, kanal, empfaenger or leads[0]["name"], betreff, text))
    return _json({"draft_id": zeilen[0]["id"], "status": zeilen[0]["status"],
                  "hinweis": "Nicht versendet — wartet in der Queue."})


@_gesichert
def digest() -> str:
    """Zusammenfassung: offene Entwuerfe, unvollstaendige Bedarfsanalysen,
    letzte Aktivitaeten (48 h)."""
    entwuerfe = _q("select d.id, d.channel, l.name, d.created_at from drafts d "
                   "left join leads l on l.id = d.lead_id "
                   "where d.status = 'pending' order by d.created_at desc")
    unvollstaendig = _q(
        "select id, name from leads where status not in ('won','lost') "
        "order by updated_at desc limit 20")
    offen_je_lead = []
    for lead in unvollstaendig:
        o = json.loads(bedarf_offen(str(lead["id"])))
        if "anzahl_offen" in o and o["anzahl_offen"] > 0:
            offen_je_lead.append({"lead_id": lead["id"], "name": lead["name"],
                                  "offene_fragen": o["anzahl_offen"]})
    letzte = _q("select a.type, a.payload, a.created_at, l.name "
                "from activities a left join leads l on l.id = a.lead_id "
                "where a.created_at > now() - interval '48 hours' "
                "order by a.created_at desc limit 20")
    return _json({"anzahl_entwuerfe": len(entwuerfe),
                  "offene_entwuerfe": [
                      {"draft_id": e["id"], "kanal": e["channel"],
                       "kontakt": e["name"]} for e in entwuerfe],
                  "unvollstaendige_bedarfsanalysen": offen_je_lead,
                  "letzte_aktivitaeten": letzte})


@_gesichert
def entwuerfe_offen() -> str:
    """Alle Entwuerfe, die auf eine Betreiber-Entscheidung warten: offene
    Freigaben (status='pending') sowie freigegebene LinkedIn-Entwuerfe, die
    noch auf den Handversand warten (status='approved', kanal='linkedin').
    Vor jeder Freigabe-Entscheidung aufrufen."""
    zeilen = _q(
        "select d.id, d.channel, d.recipient, d.status, d.body, l.name "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'pending' "
        "   or (d.status = 'approved' and d.channel = 'linkedin') "
        "order by d.created_at desc")
    return _json({"entwuerfe": [
        {"draft_id": z["id"], "kanal": z["channel"], "empfaenger": z["recipient"],
         "status": z["status"], "text": (z["body"] or "")[:200],
         "kontakt": z["name"]} for z in zeilen]})


def _entwurf_status_fehler(draft_id, erwarteter_status: str) -> str:
    """Baut die Fehlermeldung, wenn ein Statuswechsel am Ausgangsstatus
    scheitert: unbekannte draft_id vs. falscher tatsaechlicher Status."""
    zeilen = _q("select status from drafts where id = %s", (draft_id,))
    if not zeilen:
        return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
    return _json({"fehler": f"Entwurf {draft_id} hat Status "
                            f"'{zeilen[0]['status']}', erwartet '{erwarteter_status}'."})


@_gesichert
def entwurf_freigeben(draft_id: str) -> str:
    """Entwurf freigeben (pending -> approved). Nur fuer den Betreiber. Setzt
    approved_by/approved_at und protokolliert die Freigabe. Freigibt NICHT
    fuer bereits freigegebene/abgelehnte/versendete Entwuerfe."""
    zeilen = _q(
        "update drafts set status = 'approved', approved_by = 'betreiber', "
        "approved_at = now() where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _entwurf_status_fehler(draft_id, "pending")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'freigabe', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"]})))
    return _json({"draft_id": z["id"], "status": "approved"})


@_gesichert
def entwurf_ablehnen(draft_id: str) -> str:
    """Entwurf ablehnen (pending -> rejected). Nur fuer den Betreiber.
    Protokolliert die Ablehnung. Lehnt NICHT bereits freigegebene/abgelehnte/
    versendete Entwuerfe ab."""
    zeilen = _q(
        "update drafts set status = 'rejected' where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _entwurf_status_fehler(draft_id, "pending")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'ablehnung', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"]})))
    return _json({"draft_id": z["id"], "status": "rejected"})


@_gesichert
def entwurf_manuell_gesendet(draft_id: str) -> str:
    """Quittiert einen bereits von Hand versendeten LinkedIn-Entwurf
    (approved -> sent). Versendet NICHTS selbst — nur fuer LinkedIn, WhatsApp
    versendet automatisch der Dispatcher. Nur nach tatsaechlichem
    Handversand aufrufen."""
    zeilen = _q(
        "update drafts set status = 'sent', sent_at = now() "
        "where id = %s and status = 'approved' and channel = 'linkedin' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        vorhanden = _q("select status, channel from drafts where id = %s", (draft_id,))
        if not vorhanden:
            return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
        if vorhanden[0]["channel"] != "linkedin":
            return _json({"fehler": "nur für LinkedIn — WhatsApp versendet der Dispatcher"})
        return _entwurf_status_fehler(draft_id, "approved")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'versand', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"],
                             "weg": "manuell"})))
    return _json({"draft_id": z["id"], "status": "sent"})


for _fn in (kontakt_suchen, kontakt_anlegen, aktivitaet_loggen,
            profil_lesen, profil_aktualisieren, bedarf_speichern,
            bedarf_offen, entwurf_erstellen, digest, entwuerfe_offen,
            entwurf_freigeben, entwurf_ablehnen, entwurf_manuell_gesendet):
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
