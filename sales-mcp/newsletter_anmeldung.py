"""Newsletter-Anmeldung per Mail mit Bestaetigung (Double-Opt-in), 20.10.2026.

Betreiber-Entscheid (A2 b): kein Webformular - sales-claw hat bewusst nichts
Oeffentliches, Abmelden geht schon per Mail mit Betreff "Abmelden" (E2). Genauso
die Anmeldung:

  1. Jemand schreibt an das Postfach des Ladens mit Betreff "Anmelden".
  2. sales-mail schickt AUTOMATISCH eine Bestaetigungsmail mit Einmal-Code im
     Betreff (Betreiber-Entscheid: nicht ueber die Freigabe - sie antwortet nur
     dem, der sich gerade selbst angemeldet hat, mit festem Text).
  3. Erst die Antwort mit diesem Code setzt consent_status = 'opt_in'. Der
     Nachweis (beide Message-IDs, beide Zeitpunkte) liegt als Aktivitaet
     'werbe_einwilligung' am Kontakt.

WARUM DER CODE: der Absender einer Mail ist faelschbar (s. _newsletter_abmeldungen).
Wer sich mit fremder Adresse anmeldet, loest hoechstens EINE Bestaetigungsmail je
Tag an diese Adresse aus; bestaetigen kann nur, wer dieses Postfach liest. Der Code
steht nie im Klartext in der Datenbank, nur sein sha256 (Muster: verarbeite_kontomail).

WARUM KEINE AUTOMATISCHEN ANTWORTEN: eine Abwesenheitsnotiz auf die
Bestaetigungsmail traegt den Code im Betreff zurueck. Sie darf NICHT als Ja
zaehlen - postfach.liste() meldet solche Mails als `automatisch`, und dieselben
Betreff-Muster fangen Absender, die die Koepfe nicht setzen.
"""
import hashlib
import re
import secrets
from email.utils import parseaddr

import mailadresse

ANMELDE_BETREFF = re.compile(
    r"^\s*(?:(?:re|aw|wg|fwd?)\s*:\s*)*(?:newsletter\s*[-:]?\s*)?anmelden\s*[.!]?\s*$",
    re.IGNORECASE)
# Ohne 0/O, 1/I/L - der Code wird vielleicht abgetippt.
_ZEICHEN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_MUSTER = re.compile(r"\b([ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4})\b")
_AUTO_BETREFF = re.compile(
    r"^\s*(automatische\s+antwort|automatic\s+reply|auto(matic)?[- ]?reply|autoreply|abwesen"
    r"|out\s+of\s+(the\s+)?office|ich\s+bin\s+(nicht|ab)|urlaub|unzustellbar|undeliver"
    r"|delivery\s+(status|failure)|mail\s+delivery|returned\s+mail|nicht\s+zugestellt)",
    re.IGNORECASE)
_AUTO_ABSENDER = re.compile(r"^(mailer-daemon|postmaster|no-?reply|noreply)@", re.IGNORECASE)

GUELTIG_TAGE = 7          # so lange gilt ein Code
SPERRFRIST_STUNDEN = 24   # hoechstens eine Bestaetigungsmail je Adresse und Zeitraum
QUELLE = "Double-Opt-in per E-Mail"

BETREFF = "Newsletter bestätigen – Code {code}"
RUMPF = (
    "Guten Tag,\n\n"
    "Sie (oder jemand mit Ihrer Adresse) möchten unseren Newsletter per E-Mail erhalten.\n\n"
    "Zum Bestätigen antworten Sie einfach auf diese Mail. Der Betreff muss den Code "
    "{code} enthalten - beim Antworten bleibt er von selbst stehen.\n\n"
    "Waren Sie das nicht, ignorieren Sie diese Mail. Dann passiert nichts, und Sie "
    "bekommen keinen Newsletter.\n\n"
    "Abmelden geht jederzeit: eine Mail mit dem Betreff \"Abmelden\" an diese Adresse.\n")


def _q():
    import server                     # spaet: server importiert dieses Modul nicht
    return server


def adresse(mail: dict) -> str:
    return parseaddr(str(mail.get("von") or ""))[1].strip().lower()


def automatisch(mail: dict) -> bool:
    """Abwesenheitsnotiz, Unzustellbar-Meldung, Liste - nie ein Ja."""
    if mail.get("automatisch"):
        return True
    if _AUTO_BETREFF.search(str(mail.get("betreff") or "")):
        return True
    return bool(_AUTO_ABSENDER.match(adresse(mail)))


def code_neu() -> tuple[str, str]:
    """(Klartext, sha256). Der Klartext lebt nur bis zum Versand."""
    roh = "".join(secrets.choice(_ZEICHEN) for _ in range(8))
    klartext = f"{roh[:4]}-{roh[4:]}"
    return klartext, code_hash(klartext)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("ascii", "ignore")).hexdigest()


def mailtext(code: str) -> tuple[str, str]:
    return BETREFF.format(code=code), RUMPF.format(code=code)


def _kennung(mail: dict) -> str:
    return str(mail.get("message_id") or "").strip() or f"{adresse(mail)}|{mail.get('betreff')}"


def _lead_fuer(server, adr: str):
    zeilen = server._q(
        "select id, consent_status, enrichment from leads where lower(btrim(email)) = %s "
        "order by created_at limit 1", (adr,))
    return zeilen[0] if zeilen else None


def anfragen(mails: list) -> list[dict]:
    """Welche Anmelde-Mails brauchen jetzt eine Bestaetigungsmail?

    Gibt [{"lead_id", "adresse", "message_id"}] zurueck - VERSENDET nichts und
    VERMERKT nichts (das tut der Versand erst nach Erfolg, `vermerken`), damit ein
    Versandfehler beim naechsten Lauf erneut versucht wird. Legt einen Kontakt an,
    wenn die Adresse unbekannt ist (Quelle 'newsletter_anmeldung')."""
    server = _q()
    aus, gesehen = [], set()
    for m in mails or []:
        if not ANMELDE_BETREFF.match(str(m.get("betreff") or "")) or automatisch(m):
            continue
        adr, fehler = mailadresse.pruefe(adresse(m))
        if fehler or not adr:
            continue
        adr = adr.lower()
        kennung = _kennung(m)
        if adr in gesehen:
            continue
        if server._q("select 1 from activities where type = 'newsletter_anmeldung' "
                     "and payload->>'message_id' = %s limit 1", (kennung,)):
            continue
        if server._q("select 1 from activities where type = 'newsletter_anmeldung' "
                     "and payload->>'adresse' = %s and created_at > now() - make_interval(hours => %s) "
                     "limit 1", (adr, SPERRFRIST_STUNDEN)):
            continue
        if server._sperre(adr, ""):
            continue
        lead = _lead_fuer(server, adr)
        if lead is not None:
            if lead["consent_status"] == "opt_in":
                continue
            if server._loeschantrag(lead["enrichment"]) or server._privat(lead["enrichment"]):
                continue
            lead_id = str(lead["id"])
        else:
            lead_id = str(server._q(
                "insert into leads (name, email, source) values (%s, %s, 'newsletter_anmeldung') "
                "returning id", (adr, adr))[0]["id"])
        gesehen.add(adr)
        aus.append({"lead_id": lead_id, "adresse": adr, "message_id": kennung})
    return aus


def vermerken(anfrage: dict, code_sha256: str) -> None:
    """Nach erfolgreichem Versand: die Anmeldung mit dem Hash des Codes festhalten."""
    server = _q()
    server._q(
        "insert into activities (lead_id, type, payload, actor) values (%s, 'newsletter_anmeldung', "
        "%s, 'cron') returning id",
        (anfrage["lead_id"], server._json({
            "adresse": anfrage["adresse"], "message_id": anfrage["message_id"],
            "code_sha256": code_sha256, "angemeldet_am": server._jetzt()})))


def bestaetigungen(mails: list) -> int:
    """Antworten mit gueltigem Code setzen opt_in - je Anmeldung genau einmal.

    Gueltig heisst: der Code gehoert zu einer Anmeldung DIESER Absenderadresse,
    ist hoechstens GUELTIG_TAGE alt, die Mail ist keine automatische Antwort,
    und der Kontakt traegt die Adresse noch. Verbotsliste, Loeschantrag und
    privat gehen vor - dann kein opt_in."""
    server = _q()
    neu = 0
    for m in mails or []:
        if ANMELDE_BETREFF.match(str(m.get("betreff") or "")) or automatisch(m):
            continue
        codes = set(CODE_MUSTER.findall(f"{m.get('betreff') or ''} {m.get('auszug') or ''}".upper()))
        if not codes:
            continue
        adr = adresse(m)
        kennung = _kennung(m)
        if not adr or server._q(
                "select 1 from activities where type = 'werbe_einwilligung' "
                "and payload->>'bestaetigungs_message_id' = %s limit 1", (kennung,)):
            continue
        for code in codes:
            anm = server._q(
                "select id, lead_id, payload from activities where type = 'newsletter_anmeldung' "
                "and payload->>'adresse' = %s and payload->>'code_sha256' = %s "
                "and created_at > now() - make_interval(days => %s) "
                "order by created_at desc limit 1", (adr, code_hash(code), GUELTIG_TAGE))
            if not anm:
                continue
            anm = anm[0]
            if server._q("select 1 from activities where type = 'werbe_einwilligung' "
                         "and payload->>'anmeldung_id' = %s limit 1", (str(anm["id"]),)):
                break
            lead = server._q("select id, email, enrichment from leads where id = %s", (anm["lead_id"],))
            if (not lead or (lead[0]["email"] or "").strip().lower() != adr
                    or server._sperre(adr, "") or server._loeschantrag(lead[0]["enrichment"])
                    or server._privat(lead[0]["enrichment"])):
                break
            server._q("update leads set consent_status = 'opt_in', updated_at = now() "
                      "where id = %s returning id", (anm["lead_id"],))
            nachweis = {
                "art": "opt_in", "quelle": QUELLE, "durch": "kontakt", "weg": "double_opt_in",
                "zweck": "newsletter", "adresse": adr, "anmeldung_id": str(anm["id"]),
                "anmelde_message_id": (anm["payload"] or {}).get("message_id"),
                "angemeldet_am": (anm["payload"] or {}).get("angemeldet_am"),
                "bestaetigungs_message_id": kennung, "bestaetigt_am": server._jetzt()}
            server._q("insert into activities (lead_id, type, payload, actor) values "
                      "(%s, 'werbe_einwilligung', %s, 'cron') returning id",
                      (anm["lead_id"], server._json(nachweis)))
            neu += 1
            break
    return neu
