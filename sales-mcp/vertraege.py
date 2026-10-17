"""Vertraege & Projekte (C2, Spec 2026-10-17): eigene Abschluesse/Projekte
('eigen') und vom Kunden genannte Vertraege ('fremd') in EINER Liste
leads.enrichment.vertraege — ohne DDL. Altform-Eintraege (sparte/
gesellschaft/ablauf aus vertrag_speichern) werden beim Lesen normalisiert."""
import json
import re
import uuid
from datetime import date, datetime, timezone

import server

STATUS = {"angeboten": "angeboten", "in_arbeit": "in Arbeit",
          "abgeschlossen": "abgeschlossen", "beendet": "beendet"}
ARTEN = ("eigen", "fremd")
TEXT_MAX = 200
EINTRAEGE_MAX = 50
# Fester Namensraum fuer die stabile id id-loser Eintraege (Altform vor dem
# 17.10.2026). NIE aendern — sonst wechseln die ids aller Altform-Eintraege.
ID_NAMENSRAUM = uuid.UUID("6f1c2a52-8e0b-4d55-9a57-2b0c1c7e0c17")


def _stabile_id(v: dict, n: int = 0) -> str:
    """Inhaltsbasierte id (Ruling I1): dieselbe Rohzeile ergibt bei jedem Lesen
    dieselbe id, damit speichern(eintrag_id=...) sie wiederfindet. `n` trennt
    inhaltsgleiche Zeilen in derselben Liste."""
    kern = "|".join(str(v.get(k) or "") for k in
                    ("sparte", "gesellschaft", "ablauf", "erfasst", "notiz"))
    return str(uuid.uuid5(ID_NAMENSRAUM, kern + (f"#{n}" if n else "")))


def betrag_norm(text) -> str | None:
    """'1.200,50' / '1200,5' / '€ 99' -> '1200.50'; '' -> ''; Unsinn -> None."""
    t = str(text or "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not t:
        return ""
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")   # deutscher Tausenderpunkt: '2.500' = 2500
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    return f"{float(t):.2f}"


def _normal(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    # Alle Originalschluessel bleiben stehen: Uebergabe, UI-Kontaktseite und
    # vertraege_ablaufend lesen sparte/gesellschaft/ablauf, und speichern()
    # schreibt die normalisierte Liste zurueck. vertrag_speichern schreibt
    # art='fremd' MIT sparte — bezeichnung/anbieter werden deshalb auch dann
    # aus der Altform abgeleitet, wenn `art` schon gesetzt ist.
    aus = dict(v)
    if aus.get("art") not in ARTEN:
        aus["art"] = "fremd"
    if not aus.get("bezeichnung"):
        aus["bezeichnung"] = str(v.get("sparte") or "")
    if not aus.get("anbieter"):
        aus["anbieter"] = str(v.get("gesellschaft") or "")
    if not aus.get("id"):
        aus["id"] = _stabile_id(v)
    for k in ("bereich", "bezeichnung", "status", "status_datum", "anbieter", "betrag",
              "wiedervorlage_am", "notiz", "erfasst", "wiedervorlage_id"):
        aus.setdefault(k, "")
    if not (aus["bezeichnung"] or aus["anbieter"] or aus["notiz"]):
        return None if not aus.get("ablauf") else aus
    return aus


def eintraege_aus(enrichment) -> list:
    roh = (enrichment or {}).get("vertraege") if isinstance(enrichment, dict) else None
    if not isinstance(roh, list):
        return []
    aus, gesehen = [], set()
    for v in roh:
        n = _normal(v)
        if n is None:
            continue
        if n["id"] in gesehen and not v.get("id"):
            k = 1
            while _stabile_id(v, k) in gesehen:
                k += 1
            n["id"] = _stabile_id(v, k)
        gesehen.add(n["id"])
        aus.append(n)
    return aus


def eintraege(lead_id) -> list:
    z = server._q("select enrichment from leads where id = %s", (str(lead_id),))
    return eintraege_aus(z[0]["enrichment"]) if z else []


def _datum(text, feld):
    if not text:
        return "", None
    try:
        return date.fromisoformat(str(text)).isoformat(), None
    except ValueError:
        return None, f"{feld} '{text}' ist kein Datum (JJJJ-MM-TT)."


def speichern(lead_id, art, bereich, bezeichnung, status="", status_datum="", anbieter="",
              betrag="", wiedervorlage_am="", notiz="", eintrag_id="", quelle="agent") -> dict:
    try:
        lead_id = str(uuid.UUID(str(lead_id)))
    except ValueError:
        return {"fehler": f"'{lead_id}' ist keine gueltige lead_id."}
    if art not in ARTEN:
        return {"fehler": f"Art muss eigen oder fremd sein, nicht '{art}'."}
    if bereich and bereich not in server.BEREICHE:
        return {"fehler": f"Unbekannter Bereich '{bereich}'."}
    if status and status not in STATUS:
        return {"fehler": f"Unbekannter Status '{status}' — erlaubt: {', '.join(STATUS)}."}
    bezeichnung = " ".join(str(bezeichnung or "").split())
    if len(bezeichnung) > TEXT_MAX:
        return {"fehler": f"Bezeichnung fehlt oder ist laenger als {TEXT_MAX} Zeichen."}
    for name, wert in (("Anbieter", anbieter), ("Notiz", notiz)):
        if len(str(wert or "")) > TEXT_MAX:
            return {"fehler": f"{name} ist laenger als {TEXT_MAX} Zeichen."}
    b = betrag_norm(betrag)
    if b is None:
        return {"fehler": f"Betrag '{betrag}' ist kein Euro-Betrag."}
    sd, f = _datum(status_datum, "Status-Datum")
    if f:
        return {"fehler": f}
    wv, f = _datum(wiedervorlage_am, "Wiedervorlage")
    if f:
        return {"fehler": f}
    heute = datetime.now(timezone.utc).date()
    if server._sammelkontakt(lead_id):
        return {"fehler": "Sammelkontakte bekommen keine Vertraege."}
    z = server._q("select enrichment from leads where id = %s", (lead_id,))
    if not z:
        return {"fehler": f"Kein Kontakt mit lead_id {lead_id}."}
    enr = z[0]["enrichment"] or {}
    if server._privat(enr):
        return {"fehler": "Privat markierte Kontakte bekommen keine Vertraege."}
    liste = eintraege_aus(enr)
    alt = next((e for e in liste if e["id"] == eintrag_id), None) if eintrag_id else None
    if eintrag_id and alt is None:
        return {"fehler": f"Kein Eintrag mit id {eintrag_id}."}
    # Ruling I2: die Art eines Eintrags wechselt nie ueber speichern.
    if alt and alt["art"] != art:
        return {"fehler": ("Fremder Vertrag — als fremd pflegen (vertrag_speichern bzw. "
                           "Kontaktseite).") if alt["art"] == "fremd" else
                ("Eigener Abschluss — als eigen pflegen (abschluss_speichern bzw. "
                 "Kontaktseite).")}
    if alt is None and len(liste) >= EINTRAEGE_MAX:
        return {"fehler": f"Hoechstens {EINTRAEGE_MAX} Eintraege je Kontakt."}
    # Ruling I3: der Agent aendert per Merge — leere Felder bleiben, wie sie
    # sind (leeren geht nur ueber die Kontaktseite). Die UI schickt das ganze
    # Formular und ersetzt vollstaendig.
    if alt and quelle != "ui":
        bereich = bereich or alt["bereich"]
        bezeichnung = bezeichnung or alt["bezeichnung"]
        status = status or alt["status"]
        sd = sd or alt["status_datum"]
        anbieter = anbieter or alt["anbieter"]
        b = b or alt["betrag"]
        wv = wv or alt["wiedervorlage_am"]
        notiz = notiz or alt["notiz"]
    if not bezeichnung:
        return {"fehler": f"Bezeichnung fehlt oder ist laenger als {TEXT_MAX} Zeichen."}
    # Ein unveraendertes, inzwischen ueberfaelliges Datum ist kein Fehler.
    if wv and date.fromisoformat(wv) < heute and wv != (alt or {}).get("wiedervorlage_am"):
        return {"fehler": f"Wiedervorlage {wv} liegt in der Vergangenheit."}
    neu = {"id": alt["id"] if alt else str(uuid.uuid4()), "art": art, "bereich": bereich or "",
           "bezeichnung": bezeichnung, "status": status or "", "status_datum": sd,
           "anbieter": " ".join(str(anbieter or "").split()), "betrag": b,
           "wiedervorlage_am": wv, "notiz": str(notiz or "").strip(),
           "erfasst": alt["erfasst"] if alt and alt.get("erfasst") else heute.isoformat(),
           "wiedervorlage_id": alt.get("wiedervorlage_id", "") if alt else ""}
    if alt and alt.get("ablauf"):
        neu["ablauf"] = alt["ablauf"]
    if art == "fremd":
        # vertrag_speichern-Dedup (_kern), vertraege_ablaufend und die Kontakt-
        # seite lesen sparte/gesellschaft — sie spiegeln bezeichnung/anbieter.
        neu["sparte"], neu["gesellschaft"] = neu["bezeichnung"], neu["anbieter"]
    # Wiedervorlage: alte quittieren, wenn Datum wechselt oder beendet; neue anlegen
    wiedervorlage = None
    alte_wv = neu["wiedervorlage_id"]
    if alte_wv and (status == "beendet" or wv != (alt or {}).get("wiedervorlage_am")):
        server.wiedervorlage_erledigt(lead_id, alte_wv)
        neu["wiedervorlage_id"] = ""
    if wv and status != "beendet" and not neu["wiedervorlage_id"]:
        wv_id = server._wiedervorlage_anlegen(lead_id, date.fromisoformat(wv),
                                              f"Vertrag/Projekt: {bezeichnung}")
        neu["wiedervorlage_id"] = wv_id
        wiedervorlage = {"aktivitaets_id": wv_id, "faellig_am": wv}
    rest = [e for e in liste if e is not alt]
    gesamt = ([neu] + rest) if alt is None else [neu if e is alt else e for e in liste]
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "'{vertraege}', %s::jsonb, true), updated_at = now() where id = %s returning id",
              (json.dumps(gesamt, ensure_ascii=False), lead_id))
    server._q("insert into activities (lead_id, type, payload, actor) values (%s, %s, %s, %s) "
              "returning id",
              (lead_id, "vertrag_geaendert" if alt else "vertrag_angelegt",
               json.dumps({"id": neu["id"], **({"vorher": alt} if alt else {}), "nachher": neu},
                          ensure_ascii=False), "human" if quelle == "ui" else "agent"))
    if status == "abgeschlossen" and bereich:
        server._einordnen(lead_id, None, [bereich], (), quelle="ui" if quelle == "ui" else "agent")
    return {"eintrag": neu, "angelegt": alt is None, "wiedervorlage": wiedervorlage}
