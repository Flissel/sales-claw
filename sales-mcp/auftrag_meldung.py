"""Meldungen an den Betreiber zu seinen Auftraegen (M8 Stufe A, Task 7).

`faellige` liest die eigenen Auftraege des Ladens und baut je Anlass genau einen deutschen Satz:
online (mit Links), verworfen, gescheitert, nicht rechtzeitig fertig, Kanal ging nicht raus, wartet seit
2 Tagen auf Freigabe. `melden` markiert jede Zeile in derselben Runde - so kommt jede Zeile genau einmal.

Markierung:
- Endstand (fertig/abgebrochen/fehler/abgelaufen): auftrag_buch.gemeldet (Feld gemeldet_stand).
- Kanalfehler und Erinnerung: Flag in `ergebnis` (kanal_fehler_gemeldet, erinnerung_gemeldet). ergebnis_mischen
  wirkt nur bis zum Endstand; darum gibt es Kanalfehler- und Erinnerungszeilen nur, solange der Auftrag in
  `wartet_freigabe` steht. Im Endstand nennt die eine Schlussmeldung noch nicht gemeldete, gescheiterte Kanaele.
Kein Personenbezug im Text: nur Thema, Kurznummer, Kanalnamen, Links und die gespeicherten kurzen Saetze.
Freitext (Thema, fehler, gespeicherte Saetze) wird von Mailadressen und Telefonnummern gesaeubert; Links und
Kanalnamen NIE (Mastodon-Links tragen ein `@`, Status-Ids sind lange Zahlen).

Gleichzeitige Aufrufe: `melden_gesperrt` haelt eine Advisory-Sperre auf Sitzungsebene; wer sie nicht bekommt,
liefert nichts. Das schuetzt die Flags in `ergebnis` (ergebnis_mischen ist kein Compare-and-set); die Endstand-Zeilen
sichert zusaetzlich auftrag.sales_gemeldet (liefert nur True, wenn der Stand wirklich neu gesetzt wurde).
`jetzt` steht nur wegen der Plan-Signatur in `faellige`/`melden` und wird nicht gebraucht.
"""
from __future__ import annotations

import logging
import re

import auftrag_buch

log = logging.getLogger(__name__)

ENDSTAENDE = ("fertig", "abgebrochen", "fehler", "abgelaufen")
WARTET = "wartet_freigabe"

_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NUMMER = re.compile(r"\+?\d[\d ()/-]{6,}\d")


MAX_LINKS = 8          # mehr Kanaele als das: ganze Eintraege weglassen, nie einen Link kuerzen
SPERRE = "auftraege_melden"


def _rein(text: str, grenze: int) -> str:
    """Freitext ohne Mailadressen und Telefonnummern, einzeilig, gekappt."""
    text = _NUMMER.sub("[Nummer]", _MAIL.sub("[Adresse]", " ".join(str(text or "").split())))
    return text[:grenze]


def _kopf(a: dict) -> str:
    eingabe = a.get("eingabe") if isinstance(a.get("eingabe"), dict) else {}
    thema = _rein(eingabe.get("thema", ""), 80)
    return f"Reel ‚{thema}‘ (Nr. {str(a['id'])[:8]})"


def _dict(wert) -> dict:
    return wert if isinstance(wert, dict) else {}


def _liste(wert) -> list[str]:
    return [str(x) for x in wert] if isinstance(wert, list) else []


def _offene_kanalfehler(ergebnis: dict, gemeldet: list[str]) -> dict[str, str]:
    """Gescheiterte Kanaele, die weder gemeldet noch (spaeter doch) gepostet sind."""
    beitraege = _dict(ergebnis.get("beitraege"))
    return {k: str(s) for k, s in _dict(ergebnis.get("kanal_fehler")).items()
            if k not in gemeldet and k not in beitraege}


def _endtext(a: dict, ergebnis: dict, offen: dict[str, str]) -> str:
    kopf, stand = _kopf(a), a["stand"]
    if stand == "fertig":
        eintraege = [f"{k}: {v}" for k, v in _dict(ergebnis.get("beitraege")).items()]
        if len(eintraege) > MAX_LINKS:
            eintraege = eintraege[:MAX_LINKS] + [f"… und {len(eintraege) - MAX_LINKS} weitere"]
        links = "; ".join(eintraege)
        text = f"{kopf} ist online: {links}" if links else f"{kopf} ist online."
    elif stand == "abgebrochen":
        gesendet = bool(_dict(ergebnis.get("beitraege")))
        # "nichts ging raus" nur, wenn kein Kanal je einen Fehler hatte: ein ungewisser Versand kann online sein
        text = f"{kopf} wurde verworfen." if gesendet or offen or _dict(ergebnis.get("kanal_fehler")) else f"{kopf} wurde verworfen, nichts ging raus."
    elif stand == "fehler":
        grund = _rein(a.get("fehler") or "", 300).rstrip(" .")
        text = f"{kopf} ist gescheitert: {grund}." if grund else f"{kopf} ist gescheitert."
    else:
        text = f"{kopf} ist nicht rechtzeitig fertig geworden (PC aus?)."
    for kanal, satz in offen.items():
        text += (f" {kanal}: {satz}" if satz == auftrag_buch.VERSAND_UNGEWISS
                 else f" {kanal} ging nicht raus: {_rein(satz, 200)}")
    return text


def _plan(q, laden: str) -> list[tuple[str, str, str, dict | None]]:
    """(auftrag_id, stand, text, flag) - flag None = Endstand, sonst der ergebnis-Teil zum Markieren."""
    zeilen: list[tuple[str, str, str, dict | None]] = []
    for a in auftrag_buch.eigene(q, laden, list(ENDSTAENDE) + [WARTET]):
        aid, ergebnis = str(a["id"]), _dict(a.get("ergebnis"))
        gemeldet = _liste(ergebnis.get("kanal_fehler_gemeldet"))
        if a["stand"] in ENDSTAENDE:
            if a.get("gemeldet_stand") != a["stand"]:
                zeilen.append((aid, a["stand"], _endtext(a, ergebnis, _offene_kanalfehler(ergebnis, gemeldet)), None))
            continue
        for kanal, satz in _offene_kanalfehler(ergebnis, gemeldet).items():
            gemeldet = gemeldet + [kanal]
            text = (f"{_kopf(a)}: {kanal}: {satz}" if satz == auftrag_buch.VERSAND_UNGEWISS
                    else f"{_kopf(a)}: {kanal} ging nicht raus: {_rein(satz, 200)} Bitte in /freigaben ansehen.")
            zeilen.append((aid, f"kanal_fehler:{kanal}", text, {"kanal_fehler_gemeldet": gemeldet}))
        if a.get("erinnert_am") and not ergebnis.get("erinnerung_gemeldet"):
            zeilen.append((aid, "erinnerung", f"{_kopf(a)} wartet seit 2 Tagen auf deine Freigabe.",
                           {"erinnerung_gemeldet": True}))
    return zeilen


def faellige(q, laden: str, jetzt=None) -> list[tuple[str, str, str]]:
    """Noch nicht gemeldete Zeilen als (auftrag_id, stand, text); markiert nichts. `jetzt` ist nur Schnittstelle."""
    return [(aid, stand, text) for aid, stand, text, _ in _plan(q, laden)]


def melden(q, laden: str, jetzt=None) -> list[str]:
    """Liefert die faelligen Saetze und markiert jede sofort; schlaegt das Markieren fehl, entfaellt die Zeile."""
    texte: list[str] = []
    for aid, stand, text, flag in _plan(q, laden):
        try:
            ok = (auftrag_buch.gemeldet(q, aid, stand) if flag is None
                  else auftrag_buch.ergebnis_mischen(q, aid, flag))
        except Exception as e:  # noqa: BLE001 - eine Zeile darf die anderen nicht blockieren
            log.warning("Auftrag %s: Markieren fehlgeschlagen: %s", aid[:8], type(e).__name__)
            continue
        if ok:
            texte.append(text)
    return texte


def melden_gesperrt(pool, q, laden: str, schema: str = "", jetzt=None) -> list[str]:
    """`melden` unter einer Advisory-Sperre (Sitzungsebene, fester Schluessel je Schema).

    Bekommt ein zweiter Aufruf die Sperre nicht, liefert er nichts. Die Sperre wird immer wieder freigegeben."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_try_advisory_lock(hashtext(%s)) as ok", (f"{schema}:{SPERRE}",))
            if not cur.fetchone()["ok"]:
                return []
            try:
                return melden(q, laden, jetzt)
            finally:
                cur.execute("select pg_advisory_unlock(hashtext(%s))", (f"{schema}:{SPERRE}",))
