"""Firmenwahl im Marketing-Bereich (Spec 2026-10-06-mandanten-markenwissen).
Die Wahl steckt im Cookie mk_mandant (Pfad /marketing). Das Cookie ist
Eingabe des Browsers und damit nicht vertrauenswuerdig: nur eine id, die die
Marketing-API als aktiv meldet, gilt - alles andere faellt auf VORGABE."""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool

import marketing_pult

COOKIE, VORGABE = "mk_mandant", "vibemind"


def mandanten() -> list[dict]:
    """GET /mandanten; wirft PultFehler. Nur Eintraege mit id und name."""
    r = marketing_pult.anfrage("GET", "/mandanten")
    liste = r.get("mandanten") if isinstance(r, dict) else None
    if not isinstance(liste, list):
        raise marketing_pult.PultFehler("unbekannt", "Antwort ohne Mandantenliste")
    return [m for m in liste if isinstance(m, dict) and isinstance(m.get("id"), str)]


def waehlen(cookie: str | None, liste: list[dict]) -> str:
    """Die Cookie-id, wenn sie ein aktiver Mandant ist, sonst VORGABE."""
    if cookie and any(m.get("id") == cookie and m.get("aktiv") for m in liste):
        return cookie
    return VORGABE


async def firma(request) -> tuple[str, list[dict]]:
    """Die gewaehlte Firma (Cookie, geprueft gegen die aktive Liste) und die Liste
    selbst. Wirft PultFehler - der Aufrufer faengt wie bei jedem API-Aufruf."""
    liste = await run_in_threadpool(mandanten)
    return waehlen(request.cookies.get(COOKIE), liste), liste


def name_von(mid: str, liste: list[dict]) -> str:
    return next((str(m.get("name") or mid) for m in liste if m.get("id") == mid), mid)


def ziel_ok(zurueck: str) -> bool:
    """Nur Ziele im Marketing-Bereich: kein offener Redirect."""
    return (isinstance(zurueck, str) and zurueck.startswith("/marketing")
            and "//" not in zurueck and "\\" not in zurueck
            and not any(ord(c) < 32 or ord(c) == 127 for c in zurueck))


def umschalter(e, csrf: str, aktuell: str, liste: list[dict], zurueck: str) -> str:
    knoepfe = "".join(
        f'<button type="submit" name="mandant" value="{e(m["id"])}" '
        f'aria-pressed="{"true" if m["id"] == aktuell else "false"}" '
        f'class="mandant{" aktiv" if m["id"] == aktuell else ""}">{e(m.get("name") or m["id"])}</button>'
        for m in liste if m.get("aktiv"))
    return (f'<form method="post" action="/marketing/mandant" class="mandanten">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<input type="hidden" name="zurueck" value="{e(zurueck)}">{knoepfe}</form>')
