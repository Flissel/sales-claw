"""Google-Kalender lesen (Spec 2026-11-08, Kalender verbinden) - rein lesend.

OAuth-Zugang (Refresh-Token), Kalenderliste und Termine ueber die REST-API,
nur mit urllib. ALLE HTTP-Aufrufe laufen durch `_anfrage` (in Tests ersetzt).

GEHEIMNISSE. Refresh-Token, Access-Token und Client-Secret erscheinen in
keiner Ausnahme, keinem Log und keinem Fehlertext. `GoogleFehler` traegt nur
feste deutsche Texte; vom Antwortkoerper wird hoechstens der Fehlercode
`invalid_grant` ausgewertet, nie Text daraus uebernommen.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import kalender
import kalenderquellen

SCOPES = ("https://www.googleapis.com/auth/calendar.calendarlist.readonly "
          "https://www.googleapis.com/auth/calendar.events.readonly")
RUECKSPRUNG_PFAD = "/team/kalender/google/zurueck"
ZUGANG_ABGELAUFEN = "Zugang abgelaufen – bitte neu verbinden"
KEIN_DAUERZUGANG = "Google hat keinen dauerhaften Zugang geliefert"
NICHT_EINGERICHTET = "Google-Zugang ist nicht eingerichtet"
NICHT_ERREICHBAR = "Google ist nicht erreichbar"
ABGELEHNT = "Google hat die Anfrage abgelehnt"
UNLESBAR = "Die Antwort von Google ist nicht lesbar"
ZU_VIELE_SEITEN = "Der Google-Kalender ist zu gross"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
TIMEOUT_S = 20
MAX_ANTWORT_BYTES = 10 * 1024 * 1024
MAX_SEITEN = 40
# Datensparsamkeit: nur die Felder anfordern, die wir verwenden.
FELDER_LISTE = "nextPageToken,items(id,summary,summaryOverride,primary,deleted)"
FELDER_TERMINE = ("nextPageToken,items(id,status,summary,location,start,end,"
                  "transparency)")


class GoogleFehler(Exception):
    """Abruf bei Google gescheitert. Der Text ist fest und enthaelt nie
    Token, Geheimnisse oder Teile der Google-Antwort."""


def _umgebung(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _client() -> tuple[str, str]:
    cid, secret = (_umgebung("GOOGLE_KALENDER_CLIENT_ID"),
                   _umgebung("GOOGLE_KALENDER_CLIENT_SECRET"))
    if not cid or not secret:
        raise GoogleFehler(NICHT_EINGERICHTET)
    return cid, secret


def _fehler_aus(e: BaseException) -> GoogleFehler:
    """Jede Ausnahme eines Abrufs -> GoogleFehler mit festem Text. Vom Body
    wird nur geprueft, ob der Fehlercode `invalid_grant` lautet."""
    if isinstance(e, GoogleFehler):
        return e
    if isinstance(e, urllib.error.HTTPError):
        try:
            roh = e.read(65536)
            code = json.loads(roh.decode("utf-8", "replace")).get("error")
        except Exception:                 # noqa: BLE001 - Body ist egal
            code = None
        if code == "invalid_grant":
            return GoogleFehler(ZUGANG_ABGELAUFEN)
        return GoogleFehler(ABGELEHNT)
    if isinstance(e, (urllib.error.URLError, OSError, TimeoutError)):
        return GoogleFehler(NICHT_ERREICHBAR)
    return GoogleFehler(UNLESBAR)


def _anfrage(methode: str, url: str, daten: dict | None = None,
             token: str | None = None) -> dict:
    """Ein HTTP-Aufruf -> JSON-Antwort als dict. `daten` geht bei POST
    form-kodiert im Body (nie in der Adresse)."""
    body = None
    kopf = {"Accept": "application/json", "User-Agent": "sales-claw-kalender"}
    if daten is not None:
        body = urllib.parse.urlencode(daten).encode("ascii")
        kopf["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        kopf["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=kopf, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            roh = r.read(MAX_ANTWORT_BYTES + 1)
    except Exception as e:                # noqa: BLE001 - nie str(e) weitergeben
        raise _fehler_aus(e) from None
    if len(roh) > MAX_ANTWORT_BYTES:
        raise GoogleFehler(UNLESBAR)
    try:
        antwort = json.loads(roh.decode("utf-8"))
    except ValueError:
        raise GoogleFehler(UNLESBAR) from None
    if not isinstance(antwort, dict):
        raise GoogleFehler(UNLESBAR)
    return antwort


def _aufrufen(methode, url, daten=None, token=None) -> dict:
    """`_anfrage` mit Fehlerabdichtung: was auch immer sie wirft (auch ein
    Ersatz in Tests), nach aussen kommt nur ein GoogleFehler mit festem Text."""
    try:
        antwort = _anfrage(methode, url, daten, token)
    except Exception as e:                # noqa: BLE001
        raise _fehler_aus(e) from None
    if not isinstance(antwort, dict):
        raise GoogleFehler(UNLESBAR)
    if antwort.get("error") == "invalid_grant":
        raise GoogleFehler(ZUGANG_ABGELAUFEN)
    return antwort


def ruecksprung_url() -> str:
    return _umgebung("UI_BASIS_URL").rstrip("/") + RUECKSPRUNG_PFAD


def anmelde_url(state: str) -> str:
    cid, _ = _client()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": ruecksprung_url(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })


def code_tauschen(code: str) -> dict:
    cid, secret = _client()
    a = _aufrufen("POST", TOKEN_URL, {
        "code": code, "client_id": cid, "client_secret": secret,
        "redirect_uri": ruecksprung_url(), "grant_type": "authorization_code"})
    refresh = a.get("refresh_token")
    if not refresh:
        raise GoogleFehler(KEIN_DAUERZUGANG)
    access = a.get("access_token")
    if not access:
        raise GoogleFehler(UNLESBAR)
    return {"refresh_token": str(refresh), "access_token": str(access)}


def zugang_erneuern(refresh_token: str) -> str:
    cid, secret = _client()
    a = _aufrufen("POST", TOKEN_URL, {
        "refresh_token": refresh_token, "client_id": cid,
        "client_secret": secret, "grant_type": "refresh_token"})
    access = a.get("access_token")
    if not access:
        raise GoogleFehler(UNLESBAR)
    return str(access)


def _seiten(url: str, parameter: dict, access_token: str):
    """Alle Seiten einer Liste (nextPageToken). Hoechstens MAX_SEITEN."""
    seite = None
    for _ in range(MAX_SEITEN):
        p = dict(parameter)
        if seite:
            p["pageToken"] = seite
        a = _aufrufen("GET", url + "?" + urllib.parse.urlencode(p),
                      token=access_token)
        if not isinstance(a.get("items") or [], list):
            raise GoogleFehler(UNLESBAR)
        yield a
        seite = a.get("nextPageToken")
        if not seite:
            return
    raise GoogleFehler(ZU_VIELE_SEITEN)


def kalender_liste(access_token: str) -> list[dict]:
    out = []
    for a in _seiten(API + "/users/me/calendarList",
                     {"maxResults": 250, "fields": FELDER_LISTE}, access_token):
        for k in a.get("items") or []:
            if not isinstance(k, dict) or not k.get("id") or k.get("deleted"):
                continue
            out.append({"id": str(k["id"]),
                        "name": str(k.get("summaryOverride") or k.get("summary")
                                    or k["id"]),
                        "primaer": bool(k.get("primary"))})
    return out


def _zeit(feld: dict, zone) -> tuple[datetime, bool] | None:
    """Google-Zeitfeld -> (UTC, ganztaegig). `date` = ganztaegig (Ortszeit)."""
    if feld.get("dateTime"):
        wert = datetime.fromisoformat(str(feld["dateTime"]).replace("Z", "+00:00"))
        return kalenderquellen._ortszeit_utc(wert, zone), False
    if feld.get("date"):
        return kalenderquellen._ortszeit_utc(date.fromisoformat(feld["date"]), zone), True
    return None


def _rfc3339(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def termine(access_token: str, kalender_id: str, von: datetime,
            bis: datetime) -> list[dict]:
    """Termine im Fenster, Form wie `kalenderquellen.hole`. Abgesagte fallen
    raus, `transparency: transparent` ergibt `frei`. Serien sind einzeln."""
    return termine_mit_hinweis(access_token, kalender_id, von, bis)[0]


def termine_mit_hinweis(access_token: str, kalender_id: str, von: datetime,
                        bis: datetime) -> tuple[list[dict], str | None]:
    """Wie `termine`, dazu ein fester Hinweistext, wenn Eintraege nicht lesbar
    waren (wie `kalenderquellen.hole` -> (termine, fehler)): dort kann etwas
    liegen, das hier fehlt, die Quelle zaehlt dann als Luecke."""
    zone = kalender.ortszone()
    url = f"{API}/calendars/{urllib.parse.quote(kalender_id, safe='')}/events"
    out = []
    unlesbar = 0
    for a in _seiten(url, {
            "singleEvents": "true", "maxResults": 2500, "orderBy": "startTime",
            "timeMin": _rfc3339(von), "timeMax": _rfc3339(bis),
            "fields": FELDER_TERMINE}, access_token):
        for ev in a.get("items") or []:
            if not isinstance(ev, dict):
                unlesbar += 1
                continue
            if ev.get("status") == "cancelled":
                continue
            try:
                start = _zeit(ev.get("start") or {}, zone)
                ende = _zeit(ev.get("end") or {}, zone)
                if start is None:
                    unlesbar += 1
                    continue
                beginn, ganztaegig = start
                ende_t = ende[0] if ende else beginn
                if ganztaegig and ende_t <= beginn:
                    ende_t = beginn + timedelta(days=1)
                out.append({
                    "beginn": beginn,
                    "ende": max(ende_t, beginn),
                    "titel": str(ev.get("summary") or "")[:200],
                    "ort": str(ev.get("location") or "")[:120],
                    "uid": str(ev.get("id") or "")[:120],
                    "ganztaegig": ganztaegig,
                    "frei": ev.get("transparency") == "transparent"})
            except Exception:                 # noqa: BLE001 - ein Termin, nicht alle
                unlesbar += 1
    out.sort(key=lambda t: t["beginn"])
    hinweis = None
    if unlesbar:
        hinweis = (f"{unlesbar} Termin{'e' if unlesbar != 1 else ''} nicht "
                   f"lesbar — dort kann etwas liegen, das hier fehlt.")
    return out, hinweis
