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

Videos (art == "video", Video-Werkbank): zusaetzlich zum Endstand je Anlass eine Zeile, jede genau einmal. Die
Hinweise kommen schon im Stand `in_arbeit` (die Gliederung entsteht dort, M1); im Stand `erzeugt` meldet eine Zeile
einmal, dass der Auftrag-Bote das Video nicht in die Freigabe stellen kann (ergebnis.freigabe_problem, I2). Die
Markierung ist EIN Objekt `ergebnis.werkbank_gemeldet` = {runde, erinnert, hinweise: [key...], freigabe_fassung,
freigabe_problem},
das `melden` ganz ueber ergebnis_mischen schreibt - und zwar je Zeile erst NACH dem Schreiben der vorigen: schlaegt
das Markieren einer Zeile fehl, entfaellt genau diese (sie kommt beim naechsten Aufruf), und keine andere Zeile
wird dabei mitmarkiert. Markiert wird VOR dem Ausliefern: geht die Antwort danach verloren, ist die Zeile weg,
nie doppelt. Die Beschreibung des Betreibers (eingabe.beschreibung) steht nie in einer Meldung, nur das Thema.
`jetzt` (UTC) gilt fuer die 48 Stunden der Erinnerung; ohne Angabe die aktuelle Zeit.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

import auftrag_buch

log = logging.getLogger(__name__)

ENDSTAENDE = ("fertig", "abgebrochen", "fehler", "abgelaufen")
WARTET = "wartet_freigabe"
WERKBANK = "werkbank"
IN_ARBEIT, ERZEUGT = "in_arbeit", "erzeugt"   # nur fuer Videos gelesen (M1 Hinweise, I2 Freigabe-Problem)
ERINNERN_NACH = timedelta(hours=48)
# Was in Rowboat wartet, je Tor: (Einzahl, Mehrzahl) fuer "<n> ... warten in Rowboat auf dich."
_TOR_NAME = {"gliederung": ("Gliederung", "Gliederungen"), "text": ("Szenentext", "Szenentexte"),
             "clip": ("Clip", "Clips")}

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
    art = "Video" if a.get("art") == "video" else "Reel"
    return f"{art} ‚{thema}‘ (Nr. {str(a['id'])[:8]})"


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
    if a.get("art") == "video" and stand in ("fertig", "abgebrochen"):
        return _video_endtext(a, kopf, stand)
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


def _basis() -> str:
    return os.environ.get("UI_BASIS_URL", "").strip().rstrip("/")


def _video_endtext(a: dict, kopf: str, stand: str) -> str:
    if stand == "abgebrochen":
        return f"{kopf} wurde verworfen."
    basis = _basis()
    return (f"{kopf} ist freigegeben. Download: {basis}/marketing/werkbank/{a['id']}/video" if basis
            else f"{kopf} ist freigegeben.")


def _zeit(wert) -> datetime | None:
    try:
        z = datetime.fromisoformat(str(wert))
    except (TypeError, ValueError):
        return None
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


def _wartet_text(kopf: str, n: int, tor) -> str:
    einzahl, mehrzahl = _TOR_NAME.get(str(tor), ("Eintrag", "Einträge"))
    if n == 1:
        return f"{kopf}: 1 {einzahl} wartet in Rowboat auf dich."
    return f"{kopf}: {n} {mehrzahl} warten in Rowboat auf dich."


def _zahl(wert) -> int:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return 0


def _video_zeilen(a: dict, ergebnis: dict, jetzt: datetime) -> list[tuple[str, str, str, tuple]]:
    """Die Zeilen eines Videos in der Werkbank oder vor der Freigabe als (auftrag_id, stand, text, flag) mit
    flag = (gespeicherte Markierung, setzen): `setzen(markierung)` liefert die neue werkbank_gemeldet-Markierung
    mit DIESER Zeile darin."""
    aid, kopf, stand = str(a["id"]), _kopf(a), a["stand"]
    w, gemeldet = _dict(ergebnis.get("werkbank")), _dict(ergebnis.get("werkbank_gemeldet"))
    zeilen = []
    wartet = _zahl(w.get("wartet"))
    if stand == WERKBANK and wartet > 0:
        runde = w.get("runde")
        if runde != gemeldet.get("runde"):
            zeilen.append((aid, "werkbank_runde:" + str(runde), _wartet_text(kopf, wartet, w.get("wartet_tor")),
                           (gemeldet, lambda m, runde=runde: {**m, "runde": runde})))
        seit = w.get("wartet_seit")
        seit_zeit = _zeit(seit)
        if seit_zeit is not None and jetzt - seit_zeit > ERINNERN_NACH and gemeldet.get("erinnert") != seit:
            zeilen.append((aid, "werkbank_erinnerung", f"{kopf} wartet seit 2 Tagen auf deine Abnahme in Rowboat.",
                           (gemeldet, lambda m, seit=seit: {**m, "erinnert": seit})))
    schon = _liste(gemeldet.get("hinweise"))
    gesehen: set[str] = set()
    for h in w.get("hinweise") if isinstance(w.get("hinweise"), list) else []:
        key, satz = (str(h.get("key") or ""), _rein(h.get("satz"), 300)) if isinstance(h, dict) else ("", "")
        if not key or not satz or key in schon or key in gesehen:
            continue
        gesehen.add(key)
        zeilen.append((aid, "werkbank_hinweis:" + key, f"{kopf}: {satz}",
                       (gemeldet, lambda m, key=key: {**m, "hinweise": _liste(m.get("hinweise")) + [key]})))
    problem = ergebnis.get("freigabe_problem")
    if stand == ERZEUGT and isinstance(problem, str) and problem and gemeldet.get("freigabe_problem") != problem:
        zeilen.append((aid, "werkbank_freigabe_problem",                # I2: der Auftrag-Bote kommt nicht weiter
                       f"{kopf} ist fertig, kann aber nicht in die Freigabe gestellt werden – bitte Einstellung prüfen.",
                       (gemeldet, lambda m, problem=problem: {**m, "freigabe_problem": problem})))
    fassung = ergebnis.get("fassung") or 0
    kennung = str(ergebnis.get("freigabe") or "")
    if stand == WARTET and kennung and gemeldet.get("freigabe_fassung") != fassung:
        basis = _basis()
        text = (f"{kopf} ist fertig und wartet in /freigaben: {basis}/freigaben#{kennung}" if basis
                else f"{kopf} ist fertig und wartet in /freigaben.")
        zeilen.append((aid, "werkbank_freigabe", text,
                       (gemeldet, lambda m, fassung=fassung: {**m, "freigabe_fassung": fassung})))
    return zeilen


def _plan(q, laden: str, jetzt: datetime) -> list[tuple[str, str, str, dict | tuple | None]]:
    """(auftrag_id, stand, text, flag) - flag None = Endstand, ein dict = der ergebnis-Teil zum Markieren,
    ein Tupel = Markierung eines Videos (siehe _video_zeilen)."""
    zeilen: list[tuple[str, str, str, dict | tuple | None]] = []
    for a in auftrag_buch.eigene(q, laden, list(ENDSTAENDE) + [WARTET, WERKBANK, IN_ARBEIT, ERZEUGT]):
        aid, ergebnis = str(a["id"]), _dict(a.get("ergebnis"))
        if a["stand"] in (IN_ARBEIT, ERZEUGT):
            if a.get("art") == "video":                 # Reels in diesen Staenden: unveraendert keine Zeile
                zeilen += _video_zeilen(a, ergebnis, jetzt)
            continue
        gemeldet = _liste(ergebnis.get("kanal_fehler_gemeldet"))
        if a["stand"] in ENDSTAENDE:
            if a.get("gemeldet_stand") != a["stand"]:
                zeilen.append((aid, a["stand"], _endtext(a, ergebnis, _offene_kanalfehler(ergebnis, gemeldet)), None))
            continue
        if a.get("art") == "video":
            zeilen += _video_zeilen(a, ergebnis, jetzt)
        for kanal, satz in _offene_kanalfehler(ergebnis, gemeldet).items():
            gemeldet = gemeldet + [kanal]
            text = (f"{_kopf(a)}: {kanal}: {satz}" if satz == auftrag_buch.VERSAND_UNGEWISS
                    else f"{_kopf(a)}: {kanal} ging nicht raus: {_rein(satz, 200)} Bitte in /freigaben ansehen.")
            zeilen.append((aid, f"kanal_fehler:{kanal}", text, {"kanal_fehler_gemeldet": gemeldet}))
        if a["stand"] == WARTET and a.get("erinnert_am") and not ergebnis.get("erinnerung_gemeldet"):
            zeilen.append((aid, "erinnerung", f"{_kopf(a)} wartet seit 2 Tagen auf deine Freigabe.",
                           {"erinnerung_gemeldet": True}))
    return zeilen


def faellige(q, laden: str, jetzt=None) -> list[tuple[str, str, str]]:
    """Noch nicht gemeldete Zeilen als (auftrag_id, stand, text); markiert nichts."""
    return [(aid, stand, text) for aid, stand, text, _ in _plan(q, laden, jetzt or datetime.now(timezone.utc))]


def melden(q, laden: str, jetzt=None) -> list[str]:
    """Liefert die faelligen Saetze und markiert jede sofort; schlaegt das Markieren fehl, entfaellt die Zeile."""
    texte: list[str] = []
    marken: dict[str, dict] = {}       # je Video die Markierung nach den bisher erfolgreich geschriebenen Zeilen
    for aid, stand, text, flag in _plan(q, laden, jetzt or datetime.now(timezone.utc)):
        try:
            if flag is None:
                ok = auftrag_buch.gemeldet(q, aid, stand)
            elif isinstance(flag, tuple):
                start, setzen = flag
                neu = setzen(marken.get(aid, start))
                ok = auftrag_buch.ergebnis_mischen(q, aid, {"werkbank_gemeldet": neu})
                if ok:
                    marken[aid] = neu
            else:
                ok = auftrag_buch.ergebnis_mischen(q, aid, flag)
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
