"""Teilnehmer eines Termins: einordnen und mit dem CRM verknuepfen (Meeting-Mittelpunkt, Spec §3/§4).

Ein Teilnehmer ist eigene Adresse, Team, Ressource, gesperrt, bekannter Kontakt
oder neu. Gesperrte (Verbotsliste, Loeschantrag, privat) werden nie angelegt und
nie mit einem Lead verknuepft; gespeichert wird nur "gesperrt", nie der Grund.

Logs enthalten nie Adressen, Namen oder Kundentext - nur Zahlen.
"""
from __future__ import annotations

import logging
import os

from psycopg.types.json import Jsonb

import mail_dispatch
import post_struktur
import postfach
import server

LOG = logging.getLogger("teilnehmer")

RESSOURCEN_ARTEN = frozenset({"room", "resource", "group"})
NOREPLY_LOCALPARTS = frozenset({"noreply", "no-reply", "donotreply", "do-not-reply"})
RESSOURCEN_DOMAINS = ("resource.calendar.google.com", "group.calendar.google.com")
MAX_TEILNEHMER = 10

FREEMAIL = frozenset({
    "gmail.com", "googlemail.com", "web.de", "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
    "t-online.de", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de",
    "live.com", "live.de", "yahoo.com", "yahoo.de", "icloud.com", "me.com",
    "mail.de", "freenet.de", "posteo.de", "mailbox.org", "protonmail.com",
    "proton.me", "aol.com",
})


def _norm(adresse) -> str:
    return (adresse or "").strip().lower()


def _konto_adressen() -> tuple[set[str], set[str]]:
    """(eigene, fremde) Adressen aus post_konten und kalender_konten.
    Eigen = Besitzer dieses Containers; ist keiner gesetzt, gilt alles als eigen."""
    besitzer = post_struktur.container_besitzer()
    eigene: set[str] = set()
    fremde: set[str] = set()
    for tabelle in ("post_konten", "kalender_konten"):
        # kalender_konten legt nur db/kalender-verbinden.sql an; fehlt sie in
        # diesem Laden, gibt es dort keine Kalenderkonten.
        if not server._q("select to_regclass(%s) as t", (tabelle,))[0]["t"]:
            continue
        for z in server._q(f"select besitzer, adresse from {tabelle}"):
            a = _norm(z.get("adresse"))
            if not a:
                continue
            if besitzer and z.get("besitzer") != besitzer:
                fremde.add(a)
            else:
                eigene.add(a)
    return eigene, fremde


def _eigene_und_team() -> tuple[set[str], set[str]]:
    eigene, team = _konto_adressen()
    for wert in (mail_dispatch.EMAIL_ABSENDER, mail_dispatch.SMTP_USER, postfach.IMAP_USER):
        a = _norm(wert)
        if a:
            eigene.add(a)
    for wert in os.environ.get("TERMIN_TEAM_ADRESSEN", "").split(","):
        a = _norm(wert)
        if a:
            team.add(a)
    return eigene, team - eigene


def nicht_extern() -> set[str]:
    eigene, team = _eigene_und_team()
    return eigene | team


def ist_ressource(adresse: str, art: str) -> bool:
    if (art or "").strip().lower() in RESSOURCEN_ARTEN:
        return True
    lokal, _, domain = _norm(adresse).rpartition("@")
    if lokal in NOREPLY_LOCALPARTS:
        return True
    return any(domain == d or domain.endswith("." + d) for d in RESSOURCEN_DOMAINS)


def sperrgrund(adresse: str) -> str:
    """Leer, wenn die Adresse frei ist; sonst ein Grund (nur zur Entscheidung,
    wird nie gespeichert oder geloggt)."""
    a = _norm(adresse)
    if not a:
        return ""
    grund = server._sperre(a, "")
    if grund:
        return grund
    for z in server._q("select enrichment from leads where lower(email) = %s", (a,)):
        enr = z.get("enrichment")
        if server._loeschantrag(enr):
            return "Loeschantrag"
        if server._privat(enr):
            return "privat"
    return ""


def ist_kundentermin(herkunft: str, bereich: str, teilnehmer: list[dict],
                     anzahl: int) -> tuple[bool, str]:
    if herkunft == "sales-claw":
        return True, ""
    if bereich == "privat":
        return False, "private Quelle"
    if (anzahl or 0) > MAX_TEILNEHMER:
        return False, f"mehr als {MAX_TEILNEHMER} Teilnehmer"
    intern = nicht_extern()
    for t in teilnehmer or []:
        a = _norm(t.get("adresse"))
        if a and a not in intern and not ist_ressource(a, t.get("art") or ""):
            return True, ""
    return False, "keine externen Teilnehmer"


def firma_aus_domain(adresse: str) -> str:
    domain = _norm(adresse).rpartition("@")[2]
    if not domain or domain in FREEMAIL:
        return ""
    stamm = domain.rpartition(".")[0] or domain
    return stamm[:1].upper() + stamm[1:]


def _lead_id(adresse: str):
    z = server._q("select id from leads where lower(email) = %s order by created_at limit 1",
                  (adresse,))
    return z[0]["id"] if z else None


def _lead_anlegen(uid: str, adresse: str, name: str):
    z = server._q(
        "insert into leads (name, email, company, source, consent_status, enrichment) "
        "values (%s, %s, %s, 'aus Kalender', 'unknown', %s) returning id",
        (name or adresse.partition("@")[0], adresse, firma_aus_domain(adresse),
         Jsonb({"art": "kontakt", "aus_termin": uid})))
    return z[0]["id"]


def verknuepfen(uid: str, teilnehmer: list[dict], *, darf_anlegen: bool) -> list[dict]:
    eigene, team = _eigene_und_team()
    zeilen: list[dict] = []
    for t in teilnehmer or []:
        a = _norm(t.get("adresse"))
        if not a:
            continue
        name = (t.get("name") or "").strip()
        rolle = t.get("rolle") if t.get("rolle") in ("organisator", "gast") else "gast"
        lead_id = None
        grund = None
        if a in eigene:
            grund = "eigene Adresse"
        elif a in team:
            grund = "Team"
        elif ist_ressource(a, t.get("art") or ""):
            grund = "Ressource"
        elif sperrgrund(a):
            grund = "gesperrt"
        else:
            lead_id = _lead_id(a)
            if lead_id is None:
                if darf_anlegen:
                    lead_id = _lead_anlegen(uid, a, name)
                else:
                    grund = "private Quelle"
        z = server._q(
            "insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id, grund) "
            "values (%s, %s, %s, %s, %s, %s) "
            "on conflict (uid, adresse) do update set name = excluded.name, "
            "rolle = excluded.rolle, lead_id = excluded.lead_id, grund = excluded.grund "
            "returning uid, adresse, name, rolle, lead_id, grund",
            (uid, a, name or None, rolle, lead_id, grund))
        zeilen.append(z[0])
    LOG.info("Teilnehmer verknuepft: %d Zeilen", len(zeilen))
    return zeilen
