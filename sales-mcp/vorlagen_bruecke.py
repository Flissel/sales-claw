"""Die Bruecke zu marketing.* fuer Terminkarten — nur Funktionsaufrufe.

Wie lead_fluss.py: sales_app liest die Tabellen im Schema marketing NIE
direkt, sondern ruft die SECURITY-DEFINER-Funktionen aus Migration 045.
Welcher Laden ruft, bestimmt die Datenbank aus der Anmeldung; hier steht
deshalb nirgends ein Ladenname.
"""


def anlegen(q, bild: bytes | None, bild_typ: str | None, beschreibung: str,
            anmerkung: str) -> dict:
    zeilen = q("select marketing.vorlagenauftrag_anlegen(%s, %s, %s, %s, %s) as ergebnis",
               ("terminkarte", bild, bild_typ, beschreibung or "", anmerkung or ""))
    return zeilen[0]["ergebnis"]


def auftraege(q) -> list:
    return q("select id::text as id, art, status, runde, vorlage, fehler, rueckmeldungen, "
             "aktualisiert from marketing.vorlagenauftraege_des_ladens()") or []


def urteil(q, auftrag_id: str, urteil_: str, anmerkung: str) -> dict:
    zeilen = q("select marketing.vorlagenauftrag_urteil(%s::uuid, %s, %s) as ergebnis",
               (auftrag_id, urteil_, anmerkung or ""))
    return zeilen[0]["ergebnis"]


def vorlage(q, name: str) -> dict | None:
    zeilen = q("select * from marketing.formular_vorlage(%s)", (name,))
    return zeilen[0] if zeilen else None
