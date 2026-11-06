"""Ursprüngliche Empfängeradresse weitergeleiteter Mails (Spec 2026-11-06 §8).

Mails an Felix' Business-Adresse (Bluebatch) landen per Weiterleitung in
felixbaumann404@gmail.com. Die Weiterleitung hinterlässt die ursprüngliche
Adresse in einer Kopfzeile (`X-Forwarded-To`, `X-Original-To`, ...). Ist sie eine
Business-Adresse (Env `POST_BUSINESS_ADRESSEN`), gilt die Mail als business
(`post_einordnung.einordnen`).

Gelesen werden nur Kopfzeilen, nie Inhalt: beim Abholen sind sie ohnehin da, für
den Altbestand holt `nachtragen` sie per `BODY.PEEK[HEADER.FIELDS (...)]` nach.
`urspruengliche_adresse` ist NULL = noch nicht geprüft, '' = geprüft, keine
gefunden (sonst holte jeder Lauf dieselben Mails erneut).

CLI (Lese-Werkzeug für den Rollout, ruft echte Postfächer nur auf, wenn ein Mensch es startet):
    python -m post_herkunft nachtragen <kennung>
    python -m post_herkunft stichprobe <kennung> [n=30]
"""
from __future__ import annotations

import email
import email.utils
import logging
import os
import re
import sys
from collections import Counter

import postfach

LOG = logging.getLogger("post_herkunft")

# Reihenfolge = Vorrang: die Weiterleitung selbst steht vor der Zustellung am Ziel.
KOPFZEILEN = ("X-Forwarded-To", "X-Original-To", "Delivered-To", "X-Forwarded-For")
_ABRUF = "(BODY.PEEK[HEADER.FIELDS (" + " ".join(KOPFZEILEN) + " Message-ID)])"
_ABRUF_NUR_ADRESSEN = "(BODY.PEEK[HEADER.FIELDS (" + " ".join(KOPFZEILEN) + ")])"
_MESSAGE_ID_MAX = 1000        # wie post_abholen.KOPF_MAX / post_imap._KOPF_MAX
_ADRESSE_MAX = 320
_DOMAIN = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")


def _liste(wert: str) -> tuple[str, ...]:
    return tuple(e.strip().lower() for e in (wert or "").split(",") if e.strip())


# Komma-Liste. Mit "@" = genau diese Adresse, ohne "@" = Domain (samt Subdomains).
# Leer, solange die Variable fehlt: dann aendert sich am Bereich nichts.
BUSINESS_ADRESSEN: tuple[str, ...] = _liste(os.environ.get("POST_BUSINESS_ADRESSEN", ""))


def _adressen(nachricht, name: str) -> list[str]:
    # Nur das OBERSTE Vorkommen je Name: Server fuegen oben an, tiefere Zeilen kann der
    # Absender selbst in die Mail schreiben (Faelschung).
    werte = [str(w) for w in nachricht.get_all(name, [])[:1]]
    rein = (a.strip().lower() for _n, a in email.utils.getaddresses(werte))
    return [a[:_ADRESSE_MAX] for a in rein if "@" in a]


def urspruenglich(nachricht, konto_adresse: str) -> str | None:
    """Erste Adresse aus KOPFZEILEN (in dieser Reihenfolge), die nicht die eigene
    Kontoadresse ist, kleingeschrieben; None, wenn keine da ist."""
    eigene = (konto_adresse or "").strip().lower()
    for name in KOPFZEILEN:
        for adresse in _adressen(nachricht, name):
            if adresse != eigene:
                return adresse
    return None


def ist_business(adresse: str | None) -> bool:
    adresse = (adresse or "").strip().lower()
    if "@" not in adresse:
        return False
    domain = adresse.rsplit("@", 1)[1]
    for eintrag in BUSINESS_ADRESSEN:
        if "@" in eintrag:
            if adresse == eintrag:
                return True
        else:
            ende = eintrag.lstrip(".")
            if ende and (domain == ende or domain.endswith("." + ende)):
                return True
    return False


# ---------------------------------------------------------------------------
# Nachtragen (Altbestand)
# ---------------------------------------------------------------------------

def _kopf_holen(kasten, uid: int, abruf: str = _ABRUF):
    """Kopfzeilen der Mail `uid` im gewaehlten Ordner als Nachricht; None, wenn es
    unter der UID nichts gibt. Ein abgelehnter Abruf wirft (dann bleibt die Mail offen)."""
    status, daten = kasten.uid("FETCH", str(int(uid)), abruf)
    if status != "OK":
        raise RuntimeError("IMAP-Abruf abgelehnt")
    teile = [t for t in daten or () if isinstance(t, tuple) and len(t) >= 2 and t[1] is not None]
    if len(teile) > 1:
        # Ungefragte FETCH-Antworten anderer Mails aussortieren.
        muster = re.compile(rb"\bUID %d\b" % int(uid))
        teile = [t for t in teile if muster.search(t[0] or b"")]
    if len(teile) != 1:
        return None
    return email.message_from_bytes(teile[0][1])


def _uid_fuer(z: dict) -> int | None:
    """UID der Mail in ihrem Ordner. INBOX: imap_uid (<= 0 ist ein Platzhalter nach
    einem UIDVALIDITY-Wechsel); sonst ordner_uid. Ohne gueltige UID: None."""
    inbox = (z["ordner"] or "INBOX") == "INBOX"
    uid = z["imap_uid"] if inbox else z["ordner_uid"]
    return int(uid) if uid is not None and int(uid) > 0 else None


def _eintragen(mail_id, adresse: str) -> None:
    import server
    server._q("update post_mails set urspruengliche_adresse = %s "
              "where id = %s and urspruengliche_adresse is null", (adresse, mail_id))


# Zeilen, fuer die nachtragen etwas abrufen kann: Adresse noch nicht geprueft, nicht sensibel,
# nicht geloescht, und mit nutzbarer UID im jeweiligen Ordner (wie _uid_fuer). Zeilen ohne UID
# stehen hier nicht drin, sonst fuellten sie das Limit jedes Laufs und er endete ohne Fortschritt.
_OFFEN_SQL = (
    "from post_mails where konto_id = %s and urspruengliche_adresse is null "
    "and sensibel is not true and status <> 'geloescht' "
    "and ((coalesce(ordner, 'INBOX') = 'INBOX' and imap_uid > 0) "
    "  or (coalesce(ordner, 'INBOX') <> 'INBOX' and ordner_uid > 0))")


def nachtragen(zeile_konto: dict, kasten, grenze: int = 500) -> dict:
    """Holt fuer Mails des Kontos ohne `urspruengliche_adresse` NUR die Kopfzeilen
    nach und speichert die Adresse. Sensible Mails bleiben aussen vor (Spec §5: kein
    Empfaenger). Rueckgabe: {verarbeitet (Adresse oder '' eingetragen), gefunden (davon mit
    Adresse), uebersprungen (Ordner fehlt / Abruf abgelehnt, bleiben offen), offen (danach
    noch abzurufen)} - der Rollout wiederholt, bis offen = 0 ist."""
    import server       # erst hier: ist_business/urspruenglich bleiben ohne Datenbank nutzbar
    zeilen = server._q(
        "select id, imap_uid, message_id, message_id_ersatz, coalesce(ordner, 'INBOX') as ordner, "
        f"ordner_uid {_OFFEN_SQL} order by coalesce(ordner, 'INBOX'), id limit %s",
        (zeile_konto["id"], max(1, int(grenze))))
    eigene = zeile_konto.get("adresse") or ""
    gewaehlt: str | None = None
    bilanz = {"verarbeitet": 0, "gefunden": 0, "uebersprungen": 0, "offen": 0}
    for z in zeilen:
        uid = _uid_fuer(z)
        if uid is None:
            continue                       # kann nach der Auswahl oben nicht vorkommen
        if z["ordner"] != gewaehlt:
            # Lesend (EXAMINE): hier wird nichts veraendert, auch kein Flag.
            status, _ = kasten.select(postfach._imap_name(z["ordner"]), readonly=True)
            if status != "OK":
                LOG.info("Konto %s: Ordner nicht vorhanden - uebersprungen", zeile_konto["kennung"])
                gewaehlt = None
                bilanz["uebersprungen"] += 1
                continue
            gewaehlt = z["ordner"]
        try:
            kopf = _kopf_holen(kasten, uid)
        except RuntimeError:
            LOG.warning("Konto %s: Kopfzeilen-Abruf abgelehnt (uid %d)", zeile_konto["kennung"], uid)
            bilanz["uebersprungen"] += 1
            continue
        bilanz["verarbeitet"] += 1
        if kopf is None:
            _eintragen(z["id"], "")        # die Mail gibt es dort nicht mehr
            continue
        # UID und Mail muessen zusammenpassen (R13): nach UIDVALIDITY-Wechseln kann
        # eine alte UID auf eine andere Mail zeigen. Dann lieber keine Adresse.
        gefunden = postfach._kopf(kopf, "Message-ID").strip().strip("<>").replace(
            "\x00", "")[:_MESSAGE_ID_MAX]
        if not z["message_id_ersatz"] and gefunden != z["message_id"]:
            _eintragen(z["id"], "")
            continue
        adresse = urspruenglich(kopf, eigene)
        _eintragen(z["id"], adresse or "")
        bilanz["gefunden"] += 1 if adresse else 0
    bilanz["offen"] = int(server._q(f"select count(*) as n {_OFFEN_SQL}",
                                    (zeile_konto["id"],))[0]["n"])
    return bilanz


# ---------------------------------------------------------------------------
# Stichprobe: nur Haeufigkeiten Kopfzeilenname -> Domain
# ---------------------------------------------------------------------------

def _domain_zeigbar(adresse: str, eigene: str) -> str:
    """Domain fuer die Ausgabe; die volle Adresse nur, wenn es die eigene Kontoadresse ist."""
    if adresse == eigene:
        return adresse
    domain = adresse.rsplit("@", 1)[-1]
    return domain if _DOMAIN.fullmatch(domain) else "(ungueltig)"


def stichprobe(zeile_konto: dict, kasten, n: int = 30) -> Counter:
    """Zaehlt in den letzten `n` Mails der INBOX je Kopfzeile die Domains der Adressen.
    Holt nur diese Kopfzeilen; Betreff, Absender und Inhalt werden nie abgerufen."""
    eigene = (zeile_konto.get("adresse") or "").strip().lower()
    status, _ = kasten.select("INBOX", readonly=True)
    if status != "OK":
        raise RuntimeError("INBOX nicht lesbar")
    status, daten = kasten.uid("SEARCH", None, "ALL")
    if status != "OK":
        raise RuntimeError("IMAP-Suche abgelehnt")
    roh = daten[0] if daten and daten[0] else b""
    uids = sorted(int(x) for x in (roh.split() if isinstance(roh, bytes) else str(roh).split()))
    zaehler: Counter = Counter()
    for uid in uids[-max(1, int(n)):]:
        kopf = _kopf_holen(kasten, uid, _ABRUF_NUR_ADRESSEN)
        if kopf is None:
            continue
        gefunden = False
        for name in KOPFZEILEN:
            for adresse in _adressen(kopf, name):
                zaehler[(name, _domain_zeigbar(adresse, eigene))] += 1
                gefunden = True
        if not gefunden:
            zaehler[("(keine der Kopfzeilen)", "-")] += 1
    return zaehler


def tabelle(zaehler: Counter) -> str:
    zeilen = [f"{anzahl:5d}  {name:<22} {domain}"
              for (name, domain), anzahl in sorted(zaehler.items(), key=lambda e: (-e[1], e[0]))]
    return "\n".join(["Anzahl  Kopfzeile              Domain"] + zeilen)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _konto_zeile(kennung: str) -> dict | None:
    import post_konten
    return next((k for k in post_konten.aktive_konten() if k["kennung"] == kennung), None)


def _mit_kasten(kennung: str, verbinden, arbeit):
    zeile = _konto_zeile(kennung)
    if zeile is None:
        raise SystemExit("Konto unbekannt oder nicht aktiv")
    kasten = verbinden(zeile)
    try:
        return arbeit(zeile, kasten)
    finally:
        try:
            kasten.logout()
        except Exception:  # noqa: BLE001 - Abmelden ist Hoeflichkeit
            pass


def _verbinden(verbinden):
    if verbinden is None:
        import post_konten
        verbinden = post_konten.verbinden
    return verbinden


def cli_nachtragen(kennung: str, verbinden=None, ausgabe=print) -> dict:
    """`verbinden` (Konto-Zeile -> angemeldeter Kasten) ist fuer Tests austauschbar.
    Die Ausgabe steht wortgleich im Runbook (Post aufraeumen, Schritt nachtragen)."""
    verbinden = _verbinden(verbinden)
    b = _mit_kasten(kennung, verbinden, lambda z, k: nachtragen(z, k))
    ausgabe(f"Verarbeitet: {b['verarbeitet']} (Adresse gefunden: {b['gefunden']}, "
            f"uebersprungen: {b['uebersprungen']}), noch offen: {b['offen']}")
    return b


def cli_stichprobe(kennung: str, n: int = 30, verbinden=None, ausgabe=print) -> Counter:
    verbinden = _verbinden(verbinden)
    zaehler = _mit_kasten(kennung, verbinden, lambda z, k: stichprobe(z, k, n))
    ausgabe(tabelle(zaehler))
    return zaehler


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "nachtragen":
        cli_nachtragen(argv[1])
        return 0
    if len(argv) >= 2 and argv[0] == "stichprobe":
        cli_stichprobe(argv[1], int(argv[2]) if len(argv) > 2 else 30)
        return 0
    print("Aufruf: python -m post_herkunft nachtragen <kennung> | stichprobe <kennung> [n=30]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
