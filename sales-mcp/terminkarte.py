"""Terminkarte: woher die Werte kommen — und was NICHT erfunden wird.

Der Datenkatalog ist die EINE Liste der Quellen, aus denen ein Feld befuellt
werden darf (Spezifikation §4.3). Marketing waehlt beim Entwurf je Feld eine
davon; was hier nicht steht oder `frei` ist, wird im Chat erfragt oder leer
gelassen. Eine leere Linie ist auf Papier ein gueltiges Ergebnis, eine
erfundene Angabe nicht.
"""
from datetime import date

import recherche

KATALOG = {
    "kunde.name": "Name des Kontakts",
    "kunde.telefon": "Telefonnummer des Kontakts",
    "kunde.email": "E-Mail des Kontakts",
    "kunde.firma": "Firma des Kontakts",
    "termin.datum": "Datum des juengsten nicht abgesagten Termins",
    "termin.uhrzeit": "Uhrzeit dieses Termins",
    "termin.dauer": "Dauer dieses Termins",
    "termin.thema": "Thema dieses Termins",
    "termin.ort": "Ort dieses Termins",
    "mitglied.name": "Name des Mitglieds, dem der Laden gehoert (MITGLIED_NAME)",
    "frei": "wird im Chat erfragt oder leer gelassen",
}


def _termin(q, lead_id: str) -> dict:
    zeilen = q(
        "select payload from activities t where t.lead_id = %s and t.type = 'termin' "
        "and not exists (select 1 from activities a where a.lead_id = t.lead_id "
        "  and a.type = 'termin_abgesagt' and a.payload->>'uid' = t.payload->>'uid') "
        "order by t.created_at desc limit 1", (lead_id,))
    return (zeilen[0]["payload"] or {}) if zeilen else {}


def _datum(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return ""


def werte_sammeln(q, lead_id: str, gestalt: dict, mitglied_name: str, zusatz: dict) -> dict:
    kontakt = q("select name, phone, email, company from leads where id = %s", (lead_id,))
    k = kontakt[0] if kontakt else {}
    t = _termin(q, lead_id)
    quelle_wert = {
        "kunde.name": k.get("name") or "",
        "kunde.telefon": k.get("phone") or "",
        "kunde.email": k.get("email") or "",
        "kunde.firma": k.get("company") or "",
        "termin.datum": _datum(t.get("datum")),
        "termin.uhrzeit": t.get("uhrzeit") or "",
        "termin.dauer": f"{t['dauer_minuten']} Min." if t.get("dauer_minuten") else "",
        "termin.thema": t.get("thema") or "",
        "termin.ort": t.get("ort") or "",
        "mitglied.name": (mitglied_name or "").strip(),
    }
    werte, fehlend = {}, []
    for feld in gestalt["felder"]:
        name = feld["name"]
        wert = str((zusatz or {}).get(name) or quelle_wert.get(feld.get("quelle"), "")).strip()
        if wert:
            werte[name] = wert
        else:
            fehlend.append(name)
    return {"werte": werte, "fehlend": fehlend, "termin_uid": t.get("uid") or "",
            "kunde": k.get("name") or "", "termin_datum": t.get("datum") or ""}


def dateiname(kunde: str, datum_iso: str, vorhanden) -> str:
    kern = f"terminkarte-{recherche.slug(kunde) or 'kontakt'}-{datum_iso or date.today().isoformat()}"
    name, n = f"{kern}.pdf", 1
    while vorhanden(name):
        n += 1
        name = f"{kern}-{n}.pdf"
    return name
