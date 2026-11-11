"""Duenne DB-Schicht fuer das Auftragsbuch (Schema `auftrag`, vibemind-os Migration 096).

sales_app darf NUR die `sales_*`-Huellen und `ablaufen()` aufrufen: Absender ist dort fest
'sales', und jede Huelle fasst nur Auftraege von Sales an. `q` wird uebergeben (wie in
lead_fluss), damit die Tests ohne Datenbank laufen.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# Satz fuer einen Versand, dessen Ausgang unklar ist (kanal_dispatch: error "UNGEWISS: ..."); der Beitrag KANN online sein.
VERSAND_UNGEWISS = "Ob der Beitrag online ist, ist unklar – bitte im Kanal nachsehen."


class AuftragAbgelehnt(Exception):
    """Das Auftragsbuch nimmt den Auftrag nicht an; `grund` ist ein kurzer deutscher Satz."""

    def __init__(self, grund: str):
        super().__init__(grund)
        self.grund = grund


def _satz(fehler: Exception) -> str:
    text = str(fehler)
    if "2 Video-Auftraege" in text:      # vor der allgemeinen Tagesgrenze: der Text nennt beide
        return "Heute sind schon zwei Videos bestellt – morgen wieder."
    if "Tagesgrenze" in text:
        return "Die Tagesgrenze für Aufträge ist erreicht – morgen wieder."
    if "Tiefe" in text:
        return "Folgeaufträge gehen höchstens zwei Ebenen tief."
    if "nur an Marketing" in text:
        return "Aufträge gehen nur an Marketing."
    # Nur der Typname ins Log, nie der Text (kann Eingaben enthalten).
    log.warning("auftrag.sales_anlegen abgelehnt: %s", type(fehler).__name__)
    return "Das Auftragsbuch hat den Auftrag nicht angenommen."


def anlegen(q, laden: str, mandant: str, art: str, eingabe: dict) -> str:
    try:
        zeilen = q("select auftrag.sales_anlegen('marketing', %s, %s, %s, %s::jsonb) as id",
                   (laden, mandant, art, json.dumps(eingabe, ensure_ascii=False)))
    except Exception as e:  # noqa: BLE001 - jeder DB-Fehler wird zu einem Satz
        raise AuftragAbgelehnt(_satz(e)) from None
    return str(zeilen[0]["id"])


def eigene(q, laden: str, staende: list[str]) -> list[dict]:
    zeilen = q("select auftrag.sales_eigene(%s, %s::text[]) as a", (laden, list(staende)))
    return [z["a"] for z in zeilen]


def ergebnis_mischen(q, aid: str, teil: dict) -> bool:
    z = q("select auftrag.sales_ergebnis_mischen(%s::uuid, %s::jsonb) as ok",
          (aid, json.dumps(teil, ensure_ascii=False)))
    return bool(z and z[0]["ok"])


def stand_setzen(q, aid: str, von: str, nach: str, fehler: str | None = None) -> bool:
    z = q("select auftrag.sales_stand_setzen(%s::uuid, %s, %s, %s) as ok", (aid, von, nach, fehler))
    return bool(z and z[0]["ok"])


def ablaufen(q) -> int:
    z = q("select auftrag.ablaufen() as n")
    return int(z[0]["n"]) if z else 0


def gemeldet(q, aid: str, stand: str) -> bool:
    z = q("select auftrag.sales_gemeldet(%s::uuid, %s) as ok", (aid, stand))
    return bool(z and z[0]["ok"])


def erinnert(q, aid: str) -> bool:
    z = q("select auftrag.sales_erinnert(%s::uuid) as ok", (aid,))
    return bool(z and z[0]["ok"])
