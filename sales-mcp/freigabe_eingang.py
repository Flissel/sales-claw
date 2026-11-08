"""Kern des Freigabe-Eingangs: Eintraege, Auftraege, Dienst-Schluessel, Stufe-2-Sperre.

Eintraege warten auf eine Entscheidung eines Menschen; Auftraege tragen eine
Entscheidung zu den Abholern (selbstbild / werkstatt) zurueck. Schluessel liegen
nur als sha256-Hash in der DB und erscheinen nie in Log oder Fehlertext.
"""
import hashlib
import hmac
import json
import re
import secrets
import uuid

import psycopg

import server

ART_JE_HERKUNFT = {
    "debugger-claw": "debugger_pr",
    "selbstbild": "selbstbild_rueckfrage",
    "werkstatt": "kursfreigabe",
    "sales": "entwurf",
    "marketing": "entwurf",
}
HERKUNFT_ANZEIGE = {
    "debugger-claw": "Debugger-Claw",
    "selbstbild": "Selbstbild",
    "werkstatt": "Werkstatt",
    "sales": "Sales",
    "marketing": "Marketing",
}
# Stufe 2 (Annehmen fuehrt etwas aus) bleibt gesperrt, solange 5.5 nicht geloest ist.
STUFE2_ENTSPERRT = False
EINSTELLUNG_STUFE2 = "freigabe_stufe2"
STUFE2_ARTEN = ("debugger_pr", "selbstbild_rueckfrage", "kursfreigabe", "entwurf")

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_SCHLIESS_STATUS = ("erledigt", "verworfen", "ausgefuehrt")
_STAND_REIHE = ("ungesichtet", "vorgeschlagen", "angenommen", "abgehakt")
_AUFTRAG_ABHOLER = {"selbstbild_label": "selbstbild", "kurs_freigabe_zeigen": "werkstatt"}
_SCHLUESSEL_HERKUENFTE = ("debugger-claw", "selbstbild", "werkstatt")
_DETAILS_MAX_BYTES = 2048
_TITEL_MAX = 200
_HAENGT_MINUTEN = 10


class EingabeFehler(ValueError):
    """Eingabe verletzt eine Regel des Freigabe-Eingangs."""


class Stufe2Gesperrt(Exception):
    """Stufe 2 ist im Code gesperrt."""


def kennung_neu() -> str:
    return "fg-" + "".join(secrets.choice(_ALPHABET) for _ in range(10))


def _titel(titel: str) -> str:
    einzeilig = re.sub(r"\s+", " ", str(titel or "")).strip()
    return einzeilig[:_TITEL_MAX]


def _link(link) -> str | None:
    if isinstance(link, str) and re.match(r"^https?://\S+$", link.strip(), re.I):
        return link.strip()
    return None


def _offen_zu(herkunft: str, quelle_ref: str):
    z = server._q("select kennung from freigabe_eintraege "
                  "where herkunft = %s and quelle_ref = %s and status = 'offen'",
                  (herkunft, quelle_ref))
    return z[0]["kennung"] if z else None


def eintragen(herkunft, art, quelle_ref, titel, link=None, details=None,
              draft_id=None) -> tuple[str, bool]:
    if ART_JE_HERKUNFT.get(herkunft) != art:
        raise EingabeFehler(f"Art '{art}' passt nicht zur Herkunft '{herkunft}'.")
    if not quelle_ref or not str(quelle_ref).strip():
        raise EingabeFehler("quelle_ref fehlt.")
    details_json = json.dumps(details or {}, ensure_ascii=False, default=str)
    if len(details_json.encode("utf-8")) > _DETAILS_MAX_BYTES:
        raise EingabeFehler(f"details ist groesser als {_DETAILS_MAX_BYTES} Byte.")
    vorhanden = _offen_zu(herkunft, quelle_ref)
    if vorhanden:
        return vorhanden, False
    for _ in range(5):
        kennung = kennung_neu()
        try:
            z = server._q(
                "insert into freigabe_eintraege (kennung, herkunft, art, quelle_ref, "
                "titel, link, details, draft_id) values (%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (herkunft, quelle_ref) where status = 'offen' do nothing "
                "returning kennung",
                (kennung, herkunft, art, quelle_ref, _titel(titel), _link(link),
                 details_json, str(draft_id) if draft_id else None))
        except psycopg.errors.UniqueViolation:
            z = []
        if z:
            return z[0]["kennung"], True
        vorhanden = _offen_zu(herkunft, quelle_ref)
        if vorhanden:  # ein paralleler Lauf war schneller
            return vorhanden, False
    raise RuntimeError("Keine freie Kennung gefunden.")


def _status_pruefen(status):
    if status not in _SCHLIESS_STATUS:
        raise EingabeFehler(f"Status '{status}' ist kein Abschlussstatus.")


def schliessen(herkunft, quelle_ref, status, von) -> int:
    _status_pruefen(status)
    z = server._q(
        "update freigabe_eintraege set status = %s, geschlossen_am = now(), "
        "geschlossen_von = %s where herkunft = %s and quelle_ref = %s "
        "and status = 'offen' returning id", (status, von, herkunft, quelle_ref))
    return len(z)


def schliessen_kennung(kennung, status, von) -> bool:
    _status_pruefen(status)
    if not isinstance(kennung, str) or not _KENNUNG_RE.match(kennung):
        return False
    z = server._q(
        "update freigabe_eintraege set status = %s, geschlossen_am = now(), "
        "geschlossen_von = %s where kennung = %s and status = 'offen' returning id",
        (status, von, kennung))
    return bool(z)


def offene(herkunft: str | None = None) -> list[dict]:
    if herkunft:
        return server._q("select * from freigabe_eintraege where status = 'offen' "
                         "and herkunft = %s order by erstellt_am", (herkunft,))
    return server._q("select * from freigabe_eintraege where status = 'offen' "
                     "order by erstellt_am")


def zum_aufraeumen() -> list[dict]:
    return server._q("select * from freigabe_eintraege where status <> 'offen' "
                     "and rowboat_aufgeraeumt = false and rowboat_stand <> 'ungesichtet' "
                     "order by erstellt_am")


def rowboat_stand_setzen(kennung, stand) -> None:
    if stand in _STAND_REIHE:
        erlaubt_von = list(_STAND_REIHE[:_STAND_REIHE.index(stand)])
    elif stand == "abgelehnt":
        erlaubt_von = ["ungesichtet", "vorgeschlagen"]
    else:
        raise EingabeFehler(f"Unbekannter Rowboat-Stand '{stand}'.")
    if not erlaubt_von:
        return
    server._q("update freigabe_eintraege set rowboat_stand = %s, rowboat_seit = now() "
              "where kennung = %s and rowboat_stand = any(%s) returning id",
              (stand, kennung, erlaubt_von))


def aufgeraeumt(kennung) -> None:
    server._q("update freigabe_eintraege set rowboat_aufgeraeumt = true "
              "where kennung = %s returning id", (kennung,))


_AUFTRAG_ENTRYART = {"selbstbild_label": "selbstbild_rueckfrage",
                     "kurs_freigabe_zeigen": "kursfreigabe"}
_LABELS = ("antwort:weg", "antwort:bleibt", "antwort:benutzt")
_KENNUNG_RE = re.compile(r"^fg-[a-z2-7]{10}$")


def _uuid_oder_none(wert):
    try:
        return str(uuid.UUID(str(wert)))
    except (ValueError, AttributeError, TypeError):
        return None


def _nutzlast_pruefen(art, nutzlast):
    if not isinstance(nutzlast, dict):
        raise EingabeFehler("nutzlast muss ein Objekt sein.")
    if art == "selbstbild_label":
        ok = (set(nutzlast) == {"repo", "nummer", "label"}
              and isinstance(nutzlast["repo"], str) and nutzlast["repo"]
              and isinstance(nutzlast["nummer"], int)
              and not isinstance(nutzlast["nummer"], bool)
              and nutzlast["label"] in _LABELS)
    else:
        ok = (set(nutzlast) == {"course_id"}
              and isinstance(nutzlast["course_id"], str) and nutzlast["course_id"])
    if not ok:
        raise EingabeFehler(f"nutzlast passt nicht zur Auftragsart '{art}'.")


def auftrag_anlegen(kennung, art, nutzlast, von) -> str:
    abholer = _AUFTRAG_ABHOLER.get(art)
    if abholer is None:
        raise EingabeFehler(f"Unbekannte Auftragsart '{art}'.")
    if not isinstance(kennung, str) or not _KENNUNG_RE.match(kennung):
        raise EingabeFehler("Ungueltige Kennung.")
    _nutzlast_pruefen(art, nutzlast)
    e = server._q("select id, art, status from freigabe_eintraege where kennung = %s",
                  (kennung,))
    if not e:
        raise EingabeFehler("Unbekannte Kennung.")
    if e[0]["status"] != "offen":
        raise EingabeFehler("Der Eintrag ist nicht mehr offen.")
    if e[0]["art"] != _AUFTRAG_ENTRYART[art]:
        raise EingabeFehler(f"Auftragsart '{art}' passt nicht zur Art des Eintrags.")
    # Pro Eintrag nur ein Auftrag in Arbeit (Doppelklick).
    z = server._q(
        "insert into freigabe_auftraege (eintrag_id, art, abholer, nutzlast, "
        "angefordert_von) select %s,%s,%s,%s,%s where not exists (select 1 from "
        "freigabe_auftraege where eintrag_id = %s and status in ('offen','laeuft')) "
        "returning id",
        (e[0]["id"], art, abholer,
         json.dumps(nutzlast, ensure_ascii=False, default=str), von, e[0]["id"]))
    if not z:
        raise EingabeFehler("Fuer diesen Eintrag laeuft schon ein Auftrag.")
    return str(z[0]["id"])


def auftraege_abholen(abholer) -> list[dict]:
    server._q(
        "update freigabe_auftraege set status = 'fehler', erledigt_am = now(), "
        "fehler = 'Abholer hat nicht geantwortet' where abholer = %s "
        "and status = 'laeuft' and abgeholt_am < now() - make_interval(mins => %s) "
        "returning id", (abholer, _HAENGT_MINUTEN))
    return server._q(
        "update freigabe_auftraege set status = 'laeuft', abgeholt_am = now() "
        "where status = 'offen' and abholer = %s returning *", (abholer,))


def auftrag_ergebnis(auftrag_id, abholer, ok: bool, fehler: str | None) -> bool:
    auftrag_id = _uuid_oder_none(auftrag_id)
    if auftrag_id is None:
        return False
    z = server._q(
        "update freigabe_auftraege set status = %s, erledigt_am = now(), fehler = %s "
        "where id = %s and abholer = %s and status = 'laeuft' returning eintrag_id, art",
        ("erfolg" if ok else "fehler", None if ok else (fehler or "")[:500],
         auftrag_id, abholer))
    if not z:
        return False
    if ok:
        if z[0]["art"] == "selbstbild_label":
            server._q("update freigabe_eintraege set status = 'ausgefuehrt', "
                      "geschlossen_am = now(), geschlossen_von = %s "
                      "where id = %s and status = 'offen' returning id",
                      (abholer, z[0]["eintrag_id"]))
        elif z[0]["art"] == "kurs_freigabe_zeigen":
            server._q("update freigabe_eintraege set vermerk = 'Freigabe-Link gesendet' "
                      "where id = %s returning id", (z[0]["eintrag_id"],))
    return True


def _hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode("utf-8")).hexdigest()


def schluessel_herkunft(schluessel: str) -> str | None:
    if not schluessel:
        return None
    h = _hash(schluessel)
    gefunden = None
    for z in server._q("select herkunft, hash from freigabe_schluessel where aktiv"):
        if hmac.compare_digest(h, z["hash"]):
            gefunden = z["herkunft"]
    return gefunden


def schluessel_anlegen(herkunft) -> str:
    if herkunft not in _SCHLUESSEL_HERKUENFTE:
        raise EingabeFehler(f"Fuer '{herkunft}' gibt es keinen Schluessel.")
    klartext = secrets.token_urlsafe(32)
    server._q("insert into freigabe_schluessel (herkunft, hash) values (%s, %s) "
              "on conflict (herkunft) do update set hash = excluded.hash, "
              "aktiv = true, angelegt_am = now() returning herkunft",
              (herkunft, _hash(klartext)))
    return klartext


def _stufe2_gespeichert() -> dict[str, bool]:
    wert = {a: False for a in STUFE2_ARTEN}
    z = server._q("select wert from einstellungen where schluessel = %s",
                  (EINSTELLUNG_STUFE2,))
    if z and isinstance(z[0]["wert"], dict):
        for a in STUFE2_ARTEN:
            wert[a] = z[0]["wert"].get(a) is True
    return wert


def stufe2_lesen() -> dict[str, bool]:
    """Solange die Sperre gilt, ist jede Art aus, auch wenn die DB etwas anderes haelt."""
    gespeichert = _stufe2_gespeichert()
    return {a: bool(STUFE2_ENTSPERRT and gespeichert[a]) for a in STUFE2_ARTEN}


def stufe2_setzen(art, an: bool, von) -> None:
    if art not in STUFE2_ARTEN:
        raise EingabeFehler(f"Unbekannte Art '{art}'.")
    if an and not STUFE2_ENTSPERRT:
        raise Stufe2Gesperrt("Stufe 2 ist gesperrt, solange 5.5 nicht geloest ist.")
    neu = stufe2_lesen()  # gesperrt: nie ein gespeichertes true weiterschreiben
    neu[art] = bool(an)
    server._q("insert into einstellungen (schluessel, wert, geaendert_von) "
              "values (%s, %s, %s) on conflict (schluessel) do update set "
              "wert = excluded.wert, geaendert_am = now(), "
              "geaendert_von = excluded.geaendert_von returning schluessel",
              (EINSTELLUNG_STUFE2, json.dumps(neu), von))
