"""lead_fluss — F2/F3: Leads zwischen sales-claw und Marketing (Spec 03.09.2026).

BEIDE RICHTUNGEN LAUFEN UEBER DB-FUNKTIONEN in derselben Postgres (Marketing-
Migrationen 041/042). sales_app darf diese Funktionen rufen, sonst nichts in
marketing.* — die Funktionen pruefen Eingaben und Sperrliste selbst.

REINE LOGIK MIT INJIZIERTEM `q`: dieses Modul importiert server.py nicht,
damit es lokal ohne Datenbank und ohne das mcp-Paket testbar bleibt. Die
Verdrahtung (Werkzeuge, _gesichert, _q) liegt in server.py.
"""
import json

VORSCHLAG_SCHLUESSEL = "an_marketing"      # enrichment-Schluessel: {proposal_id, am}
MAX_KANDIDATEN = 500                        # Kappung der DB-Funktion


# --- F2: Recherche-Leads -> Marketing-Staging ------------------------------

def recherche_kandidaten(q, *, archiviert: str, privat: str,
                         lead_ids=None, erneut: bool = False) -> list:
    """Leads, die Marketing angeboten werden duerfen: Quelle recherche, ohne
    Einwilligung, mit E-Mail, nicht archiviert, nicht privat, noch nicht
    vorgeschlagen (ausser `erneut`). `archiviert`/`privat` sind die
    SQL-Fragmente aus server._archiv_sql / _privat_sql — dieselbe Regel wie
    ueberall, nie eine eigene."""
    sql = ("select id, name, email, phone, notes, enrichment from leads "
           "where source = 'recherche' and consent_status = 'unknown' "
           "and coalesce(email, '') <> '' "
           f"and not {archiviert} and not {privat}")
    params = []
    if not erneut:
        sql += f" and (enrichment -> '{VORSCHLAG_SCHLUESSEL}') is null"
    if lead_ids:
        sql += " and id::text = any(%s)"
        params.append([str(i) for i in lead_ids])
    sql += f" order by created_at desc limit {MAX_KANDIDATEN}"
    return q(sql, tuple(params)) or []


def kandidaten_form(zeilen: list) -> list:
    """Kandidaten so, wie die DB-Funktion sie erwartet — E-Mail klein, ohne
    kaputte Adressen (die Funktion zaehlt sie sonst als ungueltig)."""
    out = []
    for z in zeilen:
        email = (z.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        anreicherung = z.get("enrichment") if isinstance(z.get("enrichment"), dict) else {}
        firma = anreicherung.get("firma") if isinstance(anreicherung.get("firma"), dict) else {}
        out.append({"email": email,
                    "display_name": (z.get("name") or "").strip(),
                    "company": (firma.get("name") or "").strip(),
                    "notiz": (z.get("notes") or "").strip()[:200]})
    return out


def vorschlagen(q, name: str, begruendung: str, kandidaten: list) -> dict:
    """Ein Aufruf der DB-Funktion fuer alle Kandidaten. Rueckgabe wie die
    Funktion: {proposal_id, angenommen, uebersprungen_gesperrt, uebersprungen_ungueltig}."""
    zeilen = q("select marketing.vorschlag_aus_sales(%s, %s, %s::jsonb) as ergebnis",
               (name, begruendung, json.dumps(kandidaten, ensure_ascii=False)))
    ergebnis = (zeilen or [{}])[0].get("ergebnis") or {}
    if isinstance(ergebnis, str):
        ergebnis = json.loads(ergebnis)
    return ergebnis


def vermerken(q, lead_ids: list, proposal_id: str, jetzt: str) -> int:
    """Je Lead: enrichment.an_marketing = {proposal_id, am} + Aktivitaet —
    damit derselbe Lead nicht beim naechsten Aufruf wieder vorgeschlagen wird."""
    for lid in lead_ids:
        q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
          "%s, %s::jsonb, true), updated_at = now() where id = %s returning id",
          ([VORSCHLAG_SCHLUESSEL], json.dumps({"proposal_id": proposal_id, "am": jetzt}), lid))
        q("insert into activities (lead_id, type, payload) values (%s, %s, %s) returning id",
          (lid, "an_marketing", json.dumps({"proposal_id": proposal_id})))
    return len(lead_ids)
