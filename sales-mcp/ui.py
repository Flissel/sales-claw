"""sales-ui — lokale Freigabe- und Datenansicht vor der Kundendatenbank (Stufe 10).

Der siebte Container: ein server-seitig gerendertes Web-UI fuer den Betreiber.
LESEN darf es Entwuerfe, Kontakte, Posteingang, Wiedervorlagen und die offenen
Absender-Einordnungen. SCHREIBEN kann es dreierlei, und nichts sonst:

1. die drei Freigabe-Uebergaenge — freigeben (pending->approved), ablehnen
   (pending->rejected), erneut freigeben (failed->approved) — mit EXAKT den
   SQL-Bedingungen der Chat-Werkzeuge aus server.py (entwurf_freigeben,
   entwurf_ablehnen, entwurf_erneut_freigeben), nur mit
   approved_by='betreiber-ui', damit im Audit unterscheidbar bleibt, ueber
   welchen Weg freigegeben wurde;
2. die Einordnung unbekannter Absender (Stufe 11, Seite /einordnung) —
   ignorieren, zuordnen, als neuen Kontakt anlegen. Dafuer ruft das UI
   ausschliesslich server.eingang_einordnen() bzw. server.kontakt_anlegen()
   auf und baut KEINE eigene Abfrage: die Schutzkante H3 (ein echter Kontakt
   laesst sich nicht beilaeufig stummschalten) sitzt in diesen Werkzeugen und
   wird dadurch geerbt statt nachgebaut;
3. die Kontaktpflege (Betreiber-Wunsch 21.08.2026, Seite /kontakte/{id}) —
   Stammdaten korrigieren und Kontakte archivieren bzw. wiederherstellen.
   Auch hier ruft das UI ausschliesslich die Chat-Werkzeuge auf
   (server.kontakt_aktualisieren, server.kontakt_archivieren,
   server.kontakt_wiederherstellen) und baut KEIN eigenes SQL: die Feld-
   Whitelist (server.KONTAKT_FELDER — phone, email, name; ausdruecklich NICHT
   status/consent_status/enrichment) und das Archivmerkmal in `enrichment`
   sollen genau einmal existieren.

Kein Loeschen, kein Versand. Das UI kann konstruktiv nichts, was die
Chat-Werkzeuge nicht auch koennen — es kann weniger (siehe Marken-Fall und
Lead-Fall unten).

WARUM ES KEIN LOESCHEN GIBT — UND AUCH NICHT GEBEN WIRD
-------------------------------------------------------
Der Auftrag „Kontakte bearbeiten und archivieren" nennt das Loeschen
ausdruecklich NICHT, und es waere auch nicht baubar:

* Die Rolle `sales_app` hat im Produktionsschema `sales` KEIN DELETE-Recht —
  auf keiner Tabelle (db/provision.sql: „Bewusst NICHT vergeben: DELETE
  (nirgends)"). Ein Loeschknopf endete dort mit SQLSTATE 42501. Dass er im
  Testschema `sales_test` durchliefe, sagt nichts: dort hat die Rolle volle
  Rechte, weil die truncate-Fixture sie braucht.
* `activities.lead_id` verweist mit ON DELETE CASCADE auf `leads`. Ein
  geloeschter Kontakt naehme seine gesamte Historie mit — jede Nachricht, jede
  Freigabe, jede Einordnung. Die append-only-Garantie auf `activities` (kein
  UPDATE, kein DELETE) waere ueber diesen Umweg ausgehebelt, und zwar
  unbemerkt, weil nur die Zeilen fehlen und nichts davon erzaehlt.
* Ein echtes Loeschen (DSGVO-Loeschbegehren) ist deshalb ein bewusster
  Admin-Eingriff ausserhalb dieser Anwendung: mit Sicherung davor, mit
  Protokoll daneben, von einer Rolle, die das Recht dafuer hat. Er gehoert
  nicht hinter einen Knopf, der aussieht wie „Zeile weg".

Statt zu loeschen wird ARCHIVIERT: ein Merkmal in `leads.enrichment`
(Schluessel `archiviert`, Muster `whatsapp_freigabe` — die Rolle hat kein DDL,
und der CHECK auf `leads.status` kennt keinen Archiv-Wert). Archivierte
Kontakte verschwinden aus Kontaktliste, Posteingang und Zuordnungsauswahl,
bleiben aber ueber „auch archivierte zeigen" erreichbar und jederzeit
wiederherstellbar — ein Gegen-Ereignis, kein DELETE, wie schon bei
wiedervorlage_erledigt und absender_beachtet.

WARUM DIE EINORDNUNG IN DIE OBERFLAECHE GEHOERT (Betreiber-Wunsch 21.08.2026)
-----------------------------------------------------------------------------
Die Rueckfrage „wer ist das?" wurde bisher im WhatsApp-Chat beantwortet. Dort
sieht der Betreiber nur das Zitat aus `_rueckfrage_text` (120 Zeichen) und muss
Kennung und Entscheidung abtippen. Hier sieht er den Nachrichtentext lang genug,
um ihn zu verstehen (EINORDNUNG_TEXT_MAX unten), sieht auf einen Blick, ob die
Kennung schon einem Kontakt gehoert, und entscheidet je Absender mit einem
Klick. Die Seite STELLT die Rueckfrage nicht — sie zeigt nur, was offen ist:
gelesen wird ueber server._einzuordnende(), das ausdruecklich rein lesend ist.
server.eingang_einordnen() OHNE Argumente wuerde beim Seitenaufruf den
Rueckfrage-Anspruch beanspruchen (eine Aktivitaet je Absender) — ein GET, das
schreibt, und der Chat bekaeme seine Frage nie zu stellen.

SICHERHEITSMODELL (Demo-Umfang, bewusst dokumentiert)
-----------------------------------------------------
* Vertrauensgrenze ist der Rechner des Betreibers. Der Dienst bindet IM
  Container auf 0.0.0.0 (anders waere er durch das Compose-Portmapping nicht
  erreichbar); die 127.0.0.1-Grenze setzt das Portmapping in
  docker-compose.yml — `127.0.0.1:8791:8791`, dasselbe Muster wie beim
  Gateway-Port 18894. NICHT ins Internet stellen.
* CSRF-Schutz ist trotz Loopback Pflicht: eine fremde Webseite im Browser
  des Betreibers kann Formulare gegen 127.0.0.1 POSTen (ein Formular-POST
  ist ein "simple request", kein CORS-Preflight haelt ihn auf). Deshalb ein
  Boot-Token (`secrets.token_urlsafe`, einmal je Prozessstart), als
  Hidden-Field in jedem Formular, bei jedem POST in konstanter Zeit
  geprueft — Fehlschlag: 403, KEINE Aktion, kein Wort an die Datenbank.
* Host-Header-Pruefung gegen DNS-Rebinding: eine fremde Domain, die auf
  127.0.0.1 aufgeloest wird, laesst den Browser mit `Host: boese.example`
  anfragen — nur `127.0.0.1:<port>` und `localhost:<port>` werden bedient,
  alles andere bekommt 421 (Misdirected Request), bevor irgendeine Route
  laeuft.
* XSS: ALLE Fremddaten (Entwurfstexte, Kundennachrichten, Namen,
  Fehlertexte, Payload-Felder) laufen durch `html.escape` — Kundendaten
  rendern im Betreiber-Browser, ein unescapeter Entwurfstext waere Stored
  XSS. Die Seiten enthalten ueberhaupt kein JavaScript; als zweites Netz
  traegt jede Antwort `Content-Security-Policy: default-src 'none'` (nur
  Inline-CSS und Formulare an 'self' sind erlaubt).
* Marken-Fall der erneuten Freigabe: das UI ruft den Uebergang IMMER mit
  bestaetigt=False auf. Traegt der Entwurf die Claim-Marke des Dispatchers
  („in Zustellung …" — moeglicherweise BEREITS ZUGESTELLT), wird im UI
  verweigert, ausnahmslos. Die ausdrueckliche Doppelversand-Uebernahme
  bleibt dem Chat vorbehalten (`entwurf_erneut_freigeben(...,
  bestaetigt=True)`), wo die Warnung im Wortlaut gelesen werden muss —
  eine Checkbox neben einem Button ist dafuer ein zu leiser Ort.
* Lead-Fall des Ignorierens: derselbe Gedanke, eine Stufe milder. Das UI ruft
  `eingang_einordnen(..., 'ignorieren')` IMMER erst mit bestaetigt=False.
  Gehoert die Kennung einem Kontakt im CRM, verweigert das Werkzeug (Befund
  H3: ein ignorierter Kontakt verschwindet aus Posteingang UND Digest, und von
  seinen Nachrichten wird kein Wort mehr gespeichert). Die Verweigerung wird
  zur WARNSEITE mit dem Namen des Kontakts und einem EIGENEN, zweiten Formular
  — ein zweiter POST auf eine eigene Route, mit einem eigenen Hidden-Feld, das
  die lead_id des gezeigten Kontakts traegt und beim Eintreffen erneut gegen
  den aktuellen Stand geprueft wird. Bewusst KEINE vorangekreuzte Checkbox
  neben dem Knopf: „ignorieren" ist hier nicht das Ende einer Zustellung,
  sondern der Anfang eines Schweigens, das niemandem auffaellt. Anders als
  beim Marken-Fall verweigert das UI aber nicht ganz — der Betreiber sieht
  hier, anders als im Chat, den vollen Namen des betroffenen Kontakts, und
  genau das macht die Entscheidung an dieser Stelle verantwortbar.
* Archiv-Fall der Kontaktpflege: dasselbe Zweischritt-Muster wie beim
  Lead-Fall. Der erste POST auf `/kontakte/archivieren` SCHREIBT NICHTS — er
  zeigt eine Warnseite mit Namen, Anzahl der Aktivitaeten und offenen
  Entwuerfen des Kontakts. Erst der zweite, ausdrueckliche POST auf eine
  eigene Route wirkt, und er traegt in einem eigenen Hidden-Feld den NAMEN,
  den der Betreiber auf der Warnseite gelesen hat; stimmt der beim Eintreffen
  nicht mehr, wird nichts getan (409). Grund fuer den zweiten Schritt: die
  Zahlen auf der Warnseite („43 Aktivitaeten, 2 offene Entwuerfe") sind das
  Einzige, was den Unterschied zwischen „Karteileiche" und „laufender Vorgang"
  sichtbar macht — und Archivieren nimmt den Kontakt aus dem Posteingang, also
  aus genau der Ansicht, in der man ihn wiederfinden wuerde.
* Stammdaten-Aenderungen werden VOR dem ersten Schreibversuch vollstaendig
  geprueft (alle Felder), damit ein abgelehntes Feld die anderen nicht halb
  angewandt zuruecklaesst. Geprueft wird mit denselben Modulen, die ueber
  Zustellbarkeit entscheiden (nummern.py, mailadresse.py) — kein dritter
  Regelsatz. Das UI ist damit an dieser Stelle STRENGER als das Chat-Werkzeug
  (das eine nationale Nummer klaglos speichert); strenger ist erlaubt, lockerer
  nie.
* Kein Netzzugriff aus der Oberflaeche: `absender_aufloesen()` (GET an den
  eigenen openwa-Container) bleibt Chat-Sache. Es kostet Rate-Limit-Budget —
  OpenWA macht nach etwa zehn Abfragen in Folge mit 429 dicht — und gehoert
  darum nicht hinter einen Web-Knopf, den man aus Neugier zweimal drueckt.
  Folge: eine `@lid`, zu der noch keine Rufnummer bekannt ist, laesst sich
  hier nicht als neuer Kontakt anlegen (eine LID ist keine Rufnummer); die
  Seite sagt das und nennt den Weg.
* Keine Secrets in Seiten oder Logs; kein Zugriffslog (die Zeile enthielte
  nur Pfade und sagt nichts, was die Seiten nicht besser sagen). Einzige
  Env-Eingaben: SALES_DB_URL (ueber server.py), SALES_DB_SCHEMA (Default
  `sales`), TZ, optional UI_PORT.

Geteilt mit server.py (gleiches Image): Verbindungspool, Query-Helfer `_q`
und vor allem die Schema-Wache — `import server` laesst denselben
`SystemExit` fliegen, wenn SALES_DB_SCHEMA etwas anderes als
`sales`/`sales_test` ist.
"""
import functools
import hmac
import html
import json
import logging
import os
import secrets
import sys
import uuid
from datetime import date

import psycopg
import uvicorn
from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

import server

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
BIND_HOST = os.environ.get("UI_HOST", "0.0.0.0")
PORT = int(os.environ.get("UI_PORT", "8791"))
# Nur diese Host-Header werden bedient (DNS-Rebinding, Moduldocstring).
ERLAUBTE_HOSTS = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
# Boot-Token: lebt genau so lange wie der Prozess. Kein Persistieren, keine
# Sessions — es gibt genau einen Betreiber, und ein Neustart der Seite im
# Browser holt das frische Token von selbst (es steht in jedem Formular).
CSRF_TOKEN = secrets.token_urlsafe(32)

GESENDETE_MAX = 20      # letzte gesendete Entwuerfe auf der Inbox
KONTAKTE_MAX = 500      # Kontaktliste
AKTIVITAETEN_MAX = 200  # Verlauf je Kontakt
WIEDERVORLAGEN_MAX = 200
PAYLOAD_KURZ = 300      # Payload-Vorschau im Kontakt-Verlauf
# Nachrichtentext je einzuordnendem Absender. Deutlich mehr als die 120 Zeichen
# der Chat-Kurzfassung (server.EINORDNUNG_TEXT_MAX) — hier soll ein Mensch
# entscheiden, nicht ein Agent zitieren —, aber gedeckelt: der Text ist
# Fremddatum, und eine Seite, deren Laenge der Absender bestimmt, ist selbst
# eine kleine Waffe.
EINORDNUNG_TEXT_MAX = 400
EINORDNUNG_NAME_MAX = 120   # Namensfeld beim Anlegen aus der Einordnung
EINORDNUNG_VERLAUF_MAX = 25  # bereits entschiedene Absender im Verlauf
# Laengste zulaessige Eingabe je Stammdatenfeld. Gedeckelt wird VOR der
# Pruefung: was danach noch als Nummer oder Adresse durchgeht, ist auch
# vollstaendig — und ein Name, den ein Formular auf 200 Zeichen kuerzt, ist
# kein Name mehr, sondern ein Einfuegeversuch.
KONTAKT_FELD_MAX = 200
# Anzeigenamen der Felder aus server.KONTAKT_FELDER. Die LISTE der Felder
# steht bewusst NICHT hier — sie kommt aus server.py, sonst haette die
# Oberflaeche eine zweite, stillschweigend veraltende Whitelist.
KONTAKT_FELD_TITEL = {"name": "Name", "phone": "Telefon", "email": "E-Mail"}

LOG = logging.getLogger("sales-ui")


def _e(wert) -> str:
    """html.escape fuer ALLES Fremde — None wird zur leeren Zeichenkette."""
    return html.escape(str(wert if wert is not None else ""), quote=True)


def _zeit(dt) -> str:
    return dt.strftime("%d.%m.%Y %H:%M UTC") if dt else "—"


# ---------------------------------------------------------------------------
# Wachen: Host-Header und Antwort-Koepfe (ein Middleware fuer beides)
# ---------------------------------------------------------------------------

# `frame-ancestors 'none'` (und der aeltere Zwilling `X-Frame-Options: DENY`)
# sperren das Einbetten in einen fremden Iframe. Ohne das waere das CSRF-Token
# per Clickjacking umgehbar: eine boesartige Seite rahmt 127.0.0.1:8791 (Host-
# Wache passiert, echter Host stimmt), legt ein unsichtbares Overlay ueber den
# Freigeben-Knopf, und der Klick postet MIT dem legitimen, in der gerahmten
# Seite stehenden Token. `default-src 'none'` deckt `frame-ancestors` laut Spec
# NICHT ab (kein Fallback) — es muss ausdruecklich dabeistehen.
_CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def _mit_koepfen(send):
    """Legt die Schutz-Koepfe auf jede Antwort — auch auf die Host-Fehlerseite."""
    async def send_mit_koepfen(nachricht):
        if nachricht["type"] == "http.response.start":
            koepfe = MutableHeaders(scope=nachricht)
            koepfe["Content-Security-Policy"] = _CSP
            koepfe["X-Content-Type-Options"] = "nosniff"
            koepfe["Referrer-Policy"] = "no-referrer"
            koepfe["X-Frame-Options"] = "DENY"
        await send(nachricht)
    return send_mit_koepfen


class HostWache:
    """Nur die erlaubten Host-Header werden bedient; jede Antwort bekommt die
    Schutz-Koepfe. Pure-ASGI, damit die Pruefung VOR jeder Route laeuft."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Die Schutz-Koepfe gelten fuer BEIDE Pfade — auch die 421-Fehlerseite
        # bei fremdem Host darf nicht rahmbar sein.
        send = _mit_koepfen(send)
        host = Headers(scope=scope).get("host", "")
        if host not in ERLAUBTE_HOSTS:
            antwort = _fehlerseite(
                421, "Falscher Host",
                "Diese Oberflaeche antwortet nur auf 127.0.0.1 bzw. "
                "localhost. Anfragen unter fremdem Namen (DNS-Rebinding) "
                "werden nicht bedient.")
            await antwort(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _csrf_ok(form) -> bool:
    """Vergleich in konstanter Zeit — wie die Signaturpruefung in inbox.py."""
    token = str(form.get("csrf") or "")
    return bool(token) and hmac.compare_digest(token, CSRF_TOKEN)


def _gesichert_seite(fn):
    """DB-Ausfall wird zur lesbaren Seite, nie zum Traceback (Muster
    `_gesichert` aus server.py, nur mit HTML statt JSON)."""
    @functools.wraps(fn)
    async def innen(request):
        try:
            return await fn(request)
        except psycopg.OperationalError:
            return _fehlerseite(503, "Datenbank nicht erreichbar",
                                "Gerade wird NICHTS gelesen oder geschrieben. "
                                "Spaeter erneut versuchen.")
        except psycopg.Error as e:
            # Nur der SQLSTATE — Fehlertexte der DB koennen Fremddaten tragen.
            return _fehlerseite(503, "Datenbankfehler",
                                f"SQLSTATE {_e(e.sqlstate)}.")
    return innen


# ---------------------------------------------------------------------------
# HTML-Geruest (server-seitig, Inline-CSS, kein JavaScript)
# ---------------------------------------------------------------------------

_STIL = """
body { font-family: system-ui, sans-serif; margin: 0; background: #f5f4f0;
       color: #1c1b18; }
main { max-width: 62rem; margin: 0 auto; padding: 1rem 1rem 4rem; }
nav { background: #2f2a24; padding: .6rem 1rem; }
nav a { color: #f5f4f0; text-decoration: none; margin-right: 1.2rem;
        font-weight: 600; }
h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 2rem; }
.karte { background: #fff; border: 1px solid #d8d4cc; border-radius: 6px;
         padding: .8rem 1rem; margin: .7rem 0; }
.karte .text { white-space: pre-wrap; margin: .5rem 0; }
.meta { color: #6b6659; font-size: .85rem; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: 4px;
         font-size: .78rem; font-weight: 700; color: #fff;
         background: #6b6659; margin-right: .4rem; }
.badge.whatsapp { background: #1f7a4d; } .badge.email { background: #1f5b7a; }
.badge.linkedin { background: #5b4d7a; } .badge.lid { background: #a35a00; }
.fehler { color: #a01212; white-space: pre-wrap; }
.hinweis { background: #fdf3d7; border: 1px solid #e0cf96; padding: .5rem .8rem;
           border-radius: 6px; }
.warnung { background: #fbe4e4; border: 1px solid #cf9a9a; color: #6b1212;
           padding: .5rem .8rem; border-radius: 6px; margin: .5rem 0; }
form.aktion { display: inline-block; margin-right: .6rem; }
select, input[type="text"] { padding: .3rem .4rem; border-radius: 5px;
         border: 1px solid #8a8578; font-size: .9rem; max-width: 18rem; }
button { padding: .35rem .9rem; border-radius: 5px; border: 1px solid #8a8578;
         background: #fff; cursor: pointer; font-weight: 600; }
button.primaer { background: #1f7a4d; border-color: #1f7a4d; color: #fff; }
button.gefahr { background: #fff; border-color: #a01212; color: #a01212; }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid #d8d4cc; padding: .4rem .6rem; text-align: left;
         font-size: .9rem; vertical-align: top; }
"""

_NAV = (("/", "Freigaben"), ("/kontakte", "Kontakte"),
        ("/posteingang", "Posteingang"), ("/einordnung", "Einordnung"),
        ("/wiedervorlagen", "Wiedervorlagen"))


def _seite(titel: str, rumpf: str, status: int = 200,
           refresh: int | None = None) -> HTMLResponse:
    auffrischen = (f'<meta http-equiv="refresh" content="{int(refresh)}">'
                   if refresh else "")
    nav = "".join(f'<a href="{pfad}">{name}</a>' for pfad, name in _NAV)
    return HTMLResponse(
        f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{auffrischen}<title>{_e(titel)} — sales-ui</title>"
        f"<style>{_STIL}</style></head><body>"
        f"<nav>{nav}</nav><main><h1>{_e(titel)}</h1>{rumpf}</main>"
        f"</body></html>", status_code=status)


def _fehlerseite(status: int, titel: str, text: str) -> HTMLResponse:
    return _seite(titel, f'<p class="fehler">{text}</p>'
                         f'<p><a href="/">Zurueck zur Freigabe-Inbox</a></p>',
                  status=status)


def _badge(kanal) -> str:
    return f'<span class="badge {_e(kanal)}">{_e(kanal)}</span>'


# ---------------------------------------------------------------------------
# Freigabe-Inbox (/)
# ---------------------------------------------------------------------------

def _formular(aktion: str, draft_id, knopf: str, klasse: str = "",
              checkbox: str | None = None) -> str:
    haken = (f'<label><input type="checkbox" name="bestaetigt" value="ja"> '
             f'{checkbox}</label> ' if checkbox else "")
    return (f'<form class="aktion" method="post" action="/aktion/{aktion}">'
            f'<input type="hidden" name="draft_id" value="{_e(draft_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'{haken}<button class="{klasse}">{knopf}</button></form>')


def _entwurf_kopf(z) -> str:
    anhang = (f' · Anhang: <b>{_e(z["media_ref"])}</b>'
              if z.get("media_ref") else "")
    alter = (f' · Alter: {float(z["alter_h"]):.1f} h'
             if z.get("alter_h") is not None else "")
    return (f'{_badge(z["channel"])}<b>{_e(z["name"] or "(ohne Kontakt)")}'
            f"</b> &rarr; {_e(z['recipient'])}"
            f'<div class="meta">consent: {_e(z.get("consent_status"))}'
            f"{anhang}{alter} · draft_id: {_e(z['id'])}</div>")


@_gesichert_seite
async def inbox(request):
    pending = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.media_ref, "
        "       extract(epoch from (now() - d.created_at)) / 3600 as alter_h, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'pending' order by d.created_at desc")
    gescheitert = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.error, d.media_ref, "
        "       extract(epoch from (now() - d.created_at)) / 3600 as alter_h, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'failed' order by d.created_at desc limit %s",
        (server.FEHLGESCHLAGEN_MAX,))
    freigegeben = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.media_ref, "
        "       d.approved_by, d.approved_at, l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'approved' order by d.created_at desc")
    gesendet = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.sent_at, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'sent' "
        "order by d.sent_at desc nulls last limit %s", (GESENDETE_MAX,))

    teile = [f'<h2>Zur Freigabe ({len(pending)})</h2>']
    if not pending:
        teile.append("<p>Keine offenen Entwuerfe.</p>")
    for z in pending:
        teile.append(
            f'<div class="karte">{_entwurf_kopf(z)}'
            f'<div class="text">{_e(z["body"])}</div>'
            f'{_formular("freigeben", z["id"], "Freigeben", "primaer")}'
            f'{_formular("ablehnen", z["id"], "Ablehnen", "gefahr")}</div>')

    teile.append(f"<h2>Fehlgeschlagen ({len(gescheitert)})</h2>")
    if not gescheitert:
        teile.append("<p>Keine fehlgeschlagenen Entwuerfe.</p>")
    for z in gescheitert:
        teile.append(
            f'<div class="karte">{_entwurf_kopf(z)}'
            f'<div class="text">{_e(z["body"])}</div>'
            f'<div class="fehler">Fehler: {_e(z["error"])}</div>'
            f'{_formular("erneut-freigeben", z["id"], "Erneut freigeben", "",
                         checkbox="erneute Freigabe bestaetigen")}</div>')

    teile.append(f"<h2>Freigegeben ({len(freigegeben)})</h2>")
    if not freigegeben:
        teile.append("<p>Nichts wartet auf Zustellung.</p>")
    for z in freigegeben:
        if z["channel"] == "linkedin":
            # Es gibt bewusst keinen LinkedIn-Dispatcher (Stufe 3, Nr. 3).
            stand = ('<div class="hinweis">LinkedIn: von Hand posten, danach '
                     'im Chat <code>entwurf_manuell_gesendet</code> melden — '
                     'automatisch geht hier nichts raus.</div>')
        else:
            stand = ('<div class="meta">wartet auf Dispatcher '
                     '(Versand uebernimmt der zustaendige Dienst '
                     'automatisch)</div>')
        teile.append(
            f'<div class="karte">{_entwurf_kopf(z)}'
            f'<div class="text">{_e(z["body"])}</div>'
            f'<div class="meta">freigegeben: {_e(z["approved_by"])} am '
            f'{_zeit(z["approved_at"])}</div>{stand}</div>')

    teile.append(f"<h2>Zuletzt gesendet (hoechstens {GESENDETE_MAX})</h2>")
    if not gesendet:
        teile.append("<p>Noch nichts gesendet.</p>")
    for z in gesendet:
        teile.append(
            f'<div class="karte">{_entwurf_kopf(z)}'
            f'<div class="text">{_e(z["body"])}</div>'
            f'<div class="meta">gesendet: {_zeit(z["sent_at"])}</div></div>')

    return _seite("Freigabe-Inbox", "".join(teile), refresh=30)


# ---------------------------------------------------------------------------
# Die drei Aktionen — SQL EXAKT wie in server.py, approved_by='betreiber-ui'
# ---------------------------------------------------------------------------

def _statusfehler(draft_id, erwartet: str) -> HTMLResponse:
    """Spiegel von server._entwurf_status_fehler, nur als Seite statt JSON."""
    zeilen = server._q("select status from drafts where id = %s", (draft_id,))
    if not zeilen:
        return _fehlerseite(404, "Unbekannter Entwurf",
                            f"Kein Entwurf mit draft_id {_e(draft_id)}.")
    return _fehlerseite(
        409, "Keine Aktion ausgefuehrt",
        f"Entwurf {_e(draft_id)} hat Status "
        f"&#x27;{_e(zeilen[0]['status'])}&#x27;, erwartet "
        f"&#x27;{_e(erwartet)}&#x27;. Der Entwurf blieb unveraendert.")


async def _aktions_vorspann(request):
    """Gemeinsame Wache aller POSTs: CSRF zuerst, dann die draft_id.

    Reihenfolge ist Teil des Vertrags (wie in inbox.py): VOR der ersten Zeile
    Datenbank steht die Token-Pruefung — ein abgewiesener POST hat keinerlei
    Wirkung, auch keine Lesespur."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungueltig",
            "Keine Aktion ausgefuehrt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("draft_id") or "").strip()
    try:
        draft_id = str(uuid.UUID(roh))
    except ValueError:
        return None, None, _fehlerseite(
            400, "Unlesbare draft_id",
            f"&#x27;{_e(roh)}&#x27; ist keine UUID. Keine Aktion ausgefuehrt.")
    return form, draft_id, None


def _freigabe_loggen(z, erneut: bool = False) -> None:
    # actor='human': die Freigabe kam von einem Menschen an der Oberflaeche.
    # Ohne das stuende sie im append-only-Log als 'agent' (Spalten-Default) und
    # waere von einer Agenten-Freigabe nicht zu unterscheiden — die Herkunft im
    # eigentlichen Audit-Trail waere falsch. `weg='ui'` haelt zusaetzlich fest,
    # ueber welche Oberflaeche (drafts.approved_by trennt das nur bei Freigaben).
    nutzlast = {"draft_id": str(z["id"]), "kanal": z["channel"], "weg": "ui"}
    if erneut:
        nutzlast["erneut"] = True
    server._q("insert into activities (lead_id, type, payload, actor) "
              "values (%s, 'freigabe', %s, 'human') returning id",
              (z["lead_id"], server._json(nutzlast)))


@_gesichert_seite
async def aktion_freigeben(request):
    _form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    # SQL wie server.entwurf_freigeben — einziger Unterschied: approved_by.
    zeilen = server._q(
        "update drafts set status = 'approved', approved_by = 'betreiber-ui', "
        "approved_at = now() where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _statusfehler(draft_id, "pending")
    _freigabe_loggen(zeilen[0])
    return RedirectResponse("/", status_code=303)


@_gesichert_seite
async def aktion_ablehnen(request):
    _form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    # SQL wie server.entwurf_ablehnen.
    zeilen = server._q(
        "update drafts set status = 'rejected' where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _statusfehler(draft_id, "pending")
    z = zeilen[0]
    # actor='human' — dieselbe Begruendung wie in _freigabe_loggen.
    server._q("insert into activities (lead_id, type, payload, actor) "
              "values (%s, 'ablehnung', %s, 'human') returning id",
              (z["lead_id"], server._json({"draft_id": str(z["id"]),
                                           "kanal": z["channel"],
                                           "weg": "ui"})))
    return RedirectResponse("/", status_code=303)


@_gesichert_seite
async def aktion_erneut_freigeben(request):
    form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    # Die Checkbox bestaetigt die ERNEUTE FREIGABE (ein Klick daneben soll
    # keinen zweiten Versand ausloesen) — sie ist NICHT das bestaetigt=True
    # des Werkzeugs: die Doppelversand-Uebernahme bietet das UI nicht an
    # (Moduldocstring, Sicherheitsmodell).
    if str(form.get("bestaetigt") or "") != "ja":
        return _fehlerseite(
            400, "Bestaetigung fehlt",
            "Erneut freigeben heisst: derselbe Versand wird noch einmal "
            "versucht. Ohne gesetztes Haekchen wird nichts getan.")
    # SQL wie server.entwurf_erneut_freigeben mit bestaetigt=False —
    # inklusive der Doppelversand-Marken-Pruefung (Claim-Praefix aus
    # server.py, dort begruendet: kein Import von dispatch.py moeglich).
    zeilen = server._q(
        "update drafts set status = 'approved', approved_by = 'betreiber-ui', "
        "approved_at = now(), error = null "
        "where id = %s and status = 'failed' "
        "and (%s or error is null or error not like %s) "
        "returning id, lead_id, channel",
        (draft_id, False, f"{server._CLAIM_MARKE_PRAEFIX}%"))
    if not zeilen:
        vorhanden = server._q("select status, error from drafts where id = %s",
                              (draft_id,))
        if not vorhanden:
            return _fehlerseite(404, "Unbekannter Entwurf",
                                f"Kein Entwurf mit draft_id {_e(draft_id)}.")
        status, error = vorhanden[0]["status"], vorhanden[0]["error"] or ""
        if (status == "failed"
                and error.startswith(server._CLAIM_MARKE_PRAEFIX)):
            return _fehlerseite(
                409, "Verweigert: moeglicher Doppelversand",
                "Dieser Entwurf traegt die Zustellungs-Marke des Dispatchers "
                "— ein Absturz zwischen Claim und Buchung kann bedeuten, dass "
                "die Nachricht BEREITS ZUGESTELLT wurde. Diese Oberflaeche "
                "gibt so einen Entwurf grundsaetzlich nicht erneut frei. Wer "
                "das Doppelversand-Risiko ausdruecklich uebernehmen will, tut "
                "das im Chat: entwurf_erneut_freigeben(draft_id, "
                f"bestaetigt=True). error: {_e(error)}")
        return _statusfehler(draft_id, "failed")
    _freigabe_loggen(zeilen[0], erneut=True)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Kontakte
# ---------------------------------------------------------------------------

@_gesichert_seite
async def kontakte(request):
    # Archivierte bleiben draussen, solange der Schalter nicht gesetzt ist.
    # Gefiltert wird in SQL (server._archiv_sql — dieselbe Regel wie
    # server._archiviert in Python), damit KONTAKTE_MAX die SICHTBAREN
    # Kontakte deckelt und nicht die geladenen: sonst verdraengte ein Archiv
    # von 500 Karteileichen die lebenden Kontakte aus der Liste.
    archiv_zeigen = request.query_params.get("archiv") == "1"
    bedingung = "" if archiv_zeigen else (
        "where not " + server._archiv_sql("l.enrichment") + " ")
    zeilen = server._q(
        "select l.id, l.name, l.status, l.consent_status, l.enrichment, "
        "       (select max(a.created_at) from activities a "
        "         where a.lead_id = l.id) as letzte "
        "from leads l " + bedingung +
        "order by letzte desc nulls last, l.name asc limit %s",
        (KONTAKTE_MAX,))
    schalter = (
        '<p class="meta"><a href="/kontakte">nur aktive zeigen</a> — '
        'archivierte Kontakte sind mitgelistet.</p>' if archiv_zeigen else
        '<p class="meta"><a href="/kontakte?archiv=1">auch archivierte '
        'zeigen</a></p>')
    rumpf = [schalter,
             "<table><tr><th>Name</th><th>Status</th><th>Consent</th>"
             "<th>Letzte Aktivitaet</th></tr>"]
    for z in zeilen:
        marke = (' <span class="badge">archiviert</span>'
                 if server._archiviert(z["enrichment"]) else "")
        rumpf.append(
            f'<tr><td><a href="/kontakte/{_e(z["id"])}">{_e(z["name"])}</a>'
            f'{marke}</td><td>{_e(z["status"])}</td>'
            f'<td>{_e(z["consent_status"])}'
            f"</td><td>{_zeit(z['letzte'])}</td></tr>")
    rumpf.append("</table>")
    if not zeilen:
        rumpf = [schalter, "<p>Keine Kontakte.</p>"]
    return _seite(f"Kontakte ({len(zeilen)})", "".join(rumpf))


def _offene_wiedervorlagen(lead_id=None):
    """Offen = wiedervorlage ohne Gegen-Ereignis (append-only, dieselbe
    not-exists-Bedingung wie in server.digest)."""
    bedingung = "and w.lead_id = %s " if lead_id else ""
    params = ([lead_id] if lead_id else []) + [WIEDERVORLAGEN_MAX]
    return server._q(
        "select w.id, w.lead_id, w.payload, l.name from activities w "
        "left join leads l on l.id = w.lead_id "
        "where w.type = 'wiedervorlage' "
        + bedingung +
        "and not exists (select 1 from activities e where "
        "e.type = 'wiedervorlage_erledigt' "
        "and e.payload->>'wiedervorlage_id' = w.id::text) "
        # Textsortierung statt ::date: ISO-Daten (YYYY-MM-DD) sortieren als Text
        # chronologisch, und ein einziger nicht-datumsfoermiger Wert kann so
        # nicht die ganze Seite auf 503 werfen (der Cast wuerfe psycopg.Error).
        "order by (w.payload->>'faellig_am') asc nulls last limit %s",
        params)


def _wiedervorlagen_tabelle(zeilen, mit_kontakt: bool = True) -> str:
    heute = date.today().isoformat()
    kopf = "<th>Kontakt</th>" if mit_kontakt else ""
    rumpf = [f"<table><tr>{kopf}<th>Faellig am</th><th>Notiz</th></tr>"]
    for z in zeilen:
        nutzlast = z["payload"] or {}
        faellig = str(nutzlast.get("faellig_am") or "")
        marke = " <b>(faellig)</b>" if faellig and faellig <= heute else ""
        zelle = (f'<td><a href="/kontakte/{_e(z["lead_id"])}">'
                 f'{_e(z["name"] or "(ohne Kontakt)")}</a></td>'
                 if mit_kontakt else "")
        rumpf.append(f"<tr>{zelle}<td>{_e(faellig)}{marke}</td>"
                     f"<td>{_e(nutzlast.get('notiz'))}</td></tr>")
    rumpf.append("</table>")
    return "".join(rumpf) if zeilen else "<p>Keine offenen Wiedervorlagen.</p>"


# ---------------------------------------------------------------------------
# Kontaktpflege (Betreiber-Wunsch 21.08.2026): bearbeiten und archivieren.
#
# Beides laeuft ueber die Chat-Werkzeuge (server.kontakt_aktualisieren,
# server.kontakt_archivieren, server.kontakt_wiederherstellen) — kein eigenes
# SQL, damit Feld-Whitelist, Protokollierung und das Archivmerkmal genau
# einmal existieren. Geloescht wird NICHTS; warum, steht im Moduldocstring.
# ---------------------------------------------------------------------------

def _kontakt_feld_reihenfolge() -> list:
    """server.KONTAKT_FELDER, nur in Lesereihenfolge gebracht.

    Die Menge bleibt die des Werkzeugs — ein dort ergaenztes Feld taucht hier
    von selbst auf (hinten), und ein dort entferntes verschwindet. Nur die
    ANORDNUNG ist Sache der Oberflaeche: `KONTAKT_FELDER` ist nach Wichtigkeit
    fuer den Versand sortiert (phone zuerst), ein Formular liest sich nach dem
    Namen zuerst.
    """
    vorne = [f for f in ("name", "phone", "email") if f in server.KONTAKT_FELDER]
    return vorne + [f for f in server.KONTAKT_FELDER if f not in vorne]


def _kontakt_formular(lead) -> str:
    """Das Bearbeiten-Formular — GENAU die Felder, die das Werkzeug erlaubt.

    `value="…"` ist Attributkontext: `_e` escaped mit quote=True, sonst
    schloesse ein Anfuehrungszeichen im Namen das Attribut und der Rest der
    Zeile waere Markup (dieselbe Kante wie bei den Hidden-Feldern der
    Einordnung).
    """
    felder = "".join(
        f'<p><label>{_e(KONTAKT_FELD_TITEL.get(feld, feld))}<br>'
        f'<input type="text" name="{_e(feld)}" '
        f'maxlength="{KONTAKT_FELD_MAX}" value="{_e(lead[feld])}"></label></p>'
        for feld in _kontakt_feld_reihenfolge())
    return (
        f'<h2>Stammdaten bearbeiten</h2>'
        f'<div class="karte"><form method="post" action="/kontakte/bearbeiten">'
        f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">{felder}'
        f'<button class="primaer">Speichern</button></form>'
        f'<p class="meta">Aenderbar sind nur diese Felder — Status, Consent '
        f'und Profilangaben nicht: die Einwilligung entsteht aus einer Antwort '
        f'des Kontakts (bedarf_speichern), Profilangaben gehoeren nach '
        f'profil_aktualisieren. Ein leeres Feld loescht die Angabe (der Name '
        f'nicht). Die <b>Telefonnummer</b> ist der Schluessel, ueber den '
        f'eingehende Nachrichten diesem Kontakt zugeordnet werden — sie zu '
        f'aendern verschiebt kuenftige Nachrichten der alten Nummer zum '
        f'Sammelkontakt. Immer mit Landesvorwahl (+49…/+43…).</p></div>')


def _kontakt_kennzahlen(lead_id):
    """Was an diesem Kontakt haengt — die Zahlen der Warnseite."""
    aktivitaeten = server._q(
        "select count(*) as anzahl from activities where lead_id = %s",
        (lead_id,))[0]["anzahl"]
    entwuerfe = server._q(
        "select status, count(*) as anzahl from drafts where lead_id = %s "
        "and status in ('pending','approved','failed') group by status",
        (lead_id,))
    return aktivitaeten, {z["status"]: z["anzahl"] for z in entwuerfe}


def _archiv_bereich(lead, archiviert: bool) -> str:
    """Der Knopf am Fuss der Kontaktseite — archivieren oder zurueckholen.

    Es gibt hier keinen Loeschen-Knopf, und das ist keine Auslassung: die
    Begruendung steht im Moduldocstring und im Runbook.
    """
    verborgen = (f'<input type="hidden" name="lead_id" '
                 f'value="{_e(lead["id"])}">'
                 f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">')
    if archiviert:
        return (f'<h2>Archiv</h2><div class="karte">'
                f'<form method="post" action="/kontakte/wiederherstellen">'
                f'{verborgen}<button class="primaer">Wiederherstellen</button>'
                f'</form><p class="meta">Holt den Kontakt zurueck in '
                f'Kontaktliste, Posteingang und Zuordnungsauswahl. Ein '
                f'Gegen-Ereignis, kein Zuruecknehmen — es war nie etwas '
                f'geloescht.</p></div>')
    return (f'<h2>Archiv</h2><div class="karte">'
            f'<form method="post" action="/kontakte/archivieren">'
            f'{verborgen}<button class="gefahr">Archivieren</button></form>'
            f'<p class="meta">Nimmt den Kontakt aus Kontaktliste, Posteingang '
            f'und Zuordnungsauswahl. Der naechste Schritt zeigt erst, was an '
            f'ihm haengt. <b>Loeschen gibt es hier nicht</b> — die Rolle hat '
            f'kein DELETE-Recht, und der Verlauf haengt mit ON DELETE CASCADE '
            f'am Kontakt: ein Loeschen naehme die ganze Historie mit. Ein '
            f'echtes Loeschbegehren ist ein Admin-Eingriff ausserhalb dieser '
            f'Oberflaeche.</p></div>')


async def _kontakt_vorspann(request):
    """Gemeinsame Wache aller Kontakt-POSTs — Reihenfolge wie ueberall:
    CSRF VOR der ersten Zeile Datenbank, dann die lead_id."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungueltig",
            "Keine Aktion ausgefuehrt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("lead_id") or "").strip()
    try:
        lead_id = str(uuid.UUID(roh))
    except ValueError:
        return None, None, _fehlerseite(
            400, "Unlesbare lead_id",
            f"&#x27;{_e(roh)}&#x27; ist keine lead_id. Keine Aktion "
            f"ausgefuehrt.")
    return form, lead_id, None


def _feld_pruefen(feld: str, wert: str):
    """None = in Ordnung, sonst der Grund der Ablehnung (unescaped Text).

    Geprueft wird mit GENAU den Modulen, die ueber Zustellbarkeit entscheiden
    (nummern.py fuer den Dispatcher, mailadresse.py fuer sales-mail) — kein
    dritter Regelsatz, der irgendwann anders urteilt als der Versand.

    Das Chat-Werkzeug prueft an dieser Stelle NICHT (es speichert, was ihm
    gesagt wird, und verlaesst sich auf den Agenten, der die Regel in AGENTS.md
    liest). Die Oberflaeche ist hier also strenger — die erlaubte Richtung:
    eine hier abgewiesene Nummer laesst sich im Chat weiterhin eintragen, wenn
    der Betreiber das ausdruecklich will.
    """
    if feld == "name" and not wert:
        return ("Ein Kontakt ohne Namen ist nicht vorgesehen — genau das sagt "
                "auch kontakt_aktualisieren. Nichts geaendert.")
    if not wert:
        # Leeren ist erlaubt und heisst „Angabe entfaellt" (nullif im
        # Werkzeug) — nur beim Namen nicht, siehe oben.
        return None
    if feld == "phone":
        chat_id, fehler = server.normalisiere_empfaenger(wert)
        if chat_id is None:
            return (f"Telefonnummer nicht verwendbar ({fehler}). Erwartet wird "
                    f"eine Nummer MIT Landesvorwahl (+49…/+43…); eine national "
                    f"geschriebene Nummer (0170…, 0664…) wird nicht geraten, "
                    f"weil daraus die Nummer eines Fremden entstehen kann. "
                    f"Nichts geaendert.")
    if feld == "email":
        adresse, fehler = server.mailadresse.pruefe(wert)
        if adresse is None:
            return f"E-Mail-Adresse nicht verwendbar ({fehler}). Nichts geaendert."
    return None


def _kontakt_loggen(lead_id, typ: str, nutzlast: dict) -> None:
    """Die Herkunftszeile jeder Schreibaktion dieser Oberflaeche.

    Dieselbe Ueberlegung wie bei `_freigabe_loggen`: die Werkzeuge in server.py
    protokollieren ihre Aenderung selbst, aber mit dem Spalten-Default
    actor='agent' — im append-only-Log waere eine Korrektur des Menschen an
    der Oberflaeche dann von einer Agenten-Korrektur nicht zu unterscheiden.
    Nachtragen laesst sich das nicht (auf `activities` gibt es kein UPDATE),
    und die Signatur der Werkzeuge ist Teil ihres MCP-Schemas — ein
    `actor`-Argument dort waere ausserdem eine Herkunftsangabe, die ein Agent
    selbst setzen koennte. Also steht daneben genau EINE Zeile mit
    actor='human' und weg='ui'; die Detailzeilen des Werkzeugs (Feld, vorher,
    nachher) bleiben unberuehrt daneben stehen.
    """
    server._q("insert into activities (lead_id, type, payload, actor) "
              "values (%s, %s, %s, 'human') returning id",
              (lead_id, typ, server._json({**nutzlast, "weg": "ui"})))


@_gesichert_seite
async def aktion_kontakt_bearbeiten(request):
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    leads = server._q(
        "select id, name, email, phone from leads where id = %s", (lead_id,))
    if not leads:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"Kein Kontakt mit lead_id {_e(lead_id)}.")
    lead = leads[0]

    # Erst SAMMELN und PRUEFEN, dann schreiben. Ein Formular traegt mehrere
    # Felder; scheiterte das dritte, stuenden die ersten beiden schon in der
    # Datenbank und der Betreiber saehe nur „abgelehnt". Alles-oder-nichts
    # geht ohne eigene Transaktion nicht (jeder Werkzeugaufruf hat seine
    # eigene) — also faellt die Entscheidung, bevor die erste faellt.
    aenderungen = {}
    for feld in server.KONTAKT_FELDER:
        if feld not in form:
            continue          # nicht im Formular = unangetastet
        neu = " ".join(str(form.get(feld) or "").split())[:KONTAKT_FELD_MAX]
        if neu == str(lead[feld] or ""):
            continue          # unveraendert: keine Zeile, kein Protokoll
        fehler = _feld_pruefen(feld, neu)
        if fehler:
            return _fehlerseite(400, "Nicht gespeichert", _e(fehler))
        aenderungen[feld] = neu
    # Felder, die das Werkzeug NICHT erlaubt (status, consent_status, …),
    # stehen nicht in server.KONTAKT_FELDER und werden hier deshalb gar nicht
    # erst angesehen — mitgeschickt oder nicht.
    if not aenderungen:
        return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)

    gesetzt = []
    for feld in server.KONTAKT_FELDER:
        if feld not in aenderungen:
            continue
        antwort = json.loads(
            server.kontakt_aktualisieren(lead_id=lead_id, feld=feld,
                                         wert=aenderungen[feld]))
        if "fehler" in antwort:
            if gesetzt:
                _kontakt_loggen(lead_id, "korrektur", {"felder": gesetzt})
            return _fehlerseite(
                400, "Nicht vollstaendig gespeichert",
                f"{_e(antwort['fehler'])}"
                + (f" Bereits gespeichert: {_e(', '.join(gesetzt))}."
                   if gesetzt else " Nichts geaendert."))
        gesetzt.append(feld)
    _kontakt_loggen(lead_id, "korrektur", {"felder": gesetzt})
    ziel = f"/kontakte/{lead_id}"
    if "phone" in aenderungen:
        # Der Hinweis, was eine neue Nummer bewirkt — er steht auf der
        # Kontaktseite, damit er nach dem Umleiten (POST/Redirect/GET) nicht
        # verlorengeht. Uebergeben wird nur die AUSWAHL, nie ein Text.
        ziel += "?gespeichert=telefon"
    return RedirectResponse(ziel, status_code=303)


def _archiv_warnseite(lead) -> HTMLResponse:
    """Der erste Schritt: zeigen, was an diesem Kontakt haengt — und NICHTS
    schreiben. Muster und Begruendung wie bei `_ignorieren_warnseite`; das
    Hidden-Feld traegt hier den NAMEN, den der Betreiber gelesen hat."""
    aktivitaeten, entwuerfe = _kontakt_kennzahlen(lead["id"])
    offen = sum(entwuerfe.values())
    aufschluesselung = ", ".join(f"{anzahl}× {status}"
                                 for status, anzahl in sorted(entwuerfe.items()))
    versand = ""
    if entwuerfe.get("approved"):
        versand = ('<p><b>Achtung:</b> freigegebene Entwuerfe an diesen '
                   'Kontakt stellt der Dispatcher weiter zu — Archivieren '
                   'haelt keinen Versand an. Wer das will, lehnt die Entwuerfe '
                   'ab (Freigabe-Inbox) und entzieht die WhatsApp-Freigabe '
                   '(im Chat: kontakt_freigabe_entziehen).</p>')
    return _seite(
        "Archivieren bestaetigen",
        f'<div class="warnung">Der Kontakt <b>{_e(lead["name"])}</b> soll '
        f'archiviert werden. An ihm haengen <b>{_e(aktivitaeten)}</b> '
        f'Aktivitaet(en) und <b>{_e(offen)}</b> offene Entwuerfe'
        f'{" (" + _e(aufschluesselung) + ")" if aufschluesselung else ""}.'
        f'<p>Archivieren nimmt ihn aus Kontaktliste, Posteingang und der '
        f'Zuordnungsauswahl der Einordnung. <b>Geloescht wird nichts</b>: der '
        f'Verlauf bleibt vollzaehlig, der Kontakt bleibt ueber „auch '
        f'archivierte zeigen" erreichbar und laesst sich jederzeit '
        f'wiederherstellen.</p>{versand}'
        f'<p>Schreibt er spaeter erneut, steht seine Nachricht nicht mehr im '
        f'Posteingang — also in genau der Ansicht, in der man ihn '
        f'wiederfinden wuerde.</p></div>'
        f'<form method="post" action="/kontakte/archivieren-bestaetigen">'
        f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
        f'<input type="hidden" name="name_bestaetigt" '
        f'value="{_e(lead["name"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<button class="gefahr">Ja — {_e(lead["name"])} archivieren</button>'
        f'</form>'
        f'<p><a href="/kontakte/{_e(lead["id"])}">Abbrechen, nichts tun</a></p>',
        status=409)


def _kontakt_zeile(lead_id):
    return server._q("select id, name, enrichment from leads where id = %s",
                     (lead_id,))


@_gesichert_seite
async def aktion_kontakt_archivieren(request):
    """Erster Schritt: NUR die Warnseite. Hier wird bewusst nichts
    geschrieben — auch nicht „schon mal", auch nicht bei leerem Verlauf."""
    _form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    leads = _kontakt_zeile(lead_id)
    if not leads:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"Kein Kontakt mit lead_id {_e(lead_id)}.")
    if server._archiviert(leads[0]["enrichment"]):
        return _fehlerseite(
            409, "Schon archiviert",
            f"{_e(leads[0]['name'])} ist bereits archiviert. Nichts getan.")
    return _archiv_warnseite(leads[0])


@_gesichert_seite
async def aktion_kontakt_archivieren_bestaetigen(request):
    """Der ZWEITE, ausdrueckliche POST — mit erneuter Pruefung, dass es noch
    derselbe Kontakt ist (wie bei ignorieren-bestaetigen)."""
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    bestaetigt_fuer = str(form.get("name_bestaetigt") or "")
    if not bestaetigt_fuer:
        return _fehlerseite(
            400, "Bestaetigung fehlt",
            "Ohne den auf der Warnseite gelesenen Namen wird nichts getan.")
    leads = _kontakt_zeile(lead_id)
    if not leads:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"Kein Kontakt mit lead_id {_e(lead_id)}.")
    lead = leads[0]
    # Zwischen Warnseite und Klick kann sich die Lage geaendert haben (eine
    # Umbenennung im Chat, ein zweiter Tab). Dann ist das Ja von eben kein Ja
    # zu dem, was jetzt passieren wuerde — also lieber gar nichts.
    if str(lead["name"] or "") != bestaetigt_fuer:
        return _fehlerseite(
            409, "Bestaetigung passt nicht mehr",
            "Der Kontakt heisst inzwischen anders als auf der Warnseite. "
            "Nichts wurde getan — die Seite neu laden und erneut ansehen.")
    if server._archiviert(lead["enrichment"]):
        return _fehlerseite(
            409, "Schon archiviert",
            f"{_e(lead['name'])} ist bereits archiviert. Nichts getan.")
    antwort = json.loads(server.kontakt_archivieren(lead_id=lead_id))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht archiviert", _e(antwort["fehler"]))
    _kontakt_loggen(lead_id, "kontakt_archiviert", {"archiviert": True})
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def aktion_kontakt_wiederherstellen(request):
    """Einschrittig, und das mit Absicht: Zurueckholen macht sichtbar, was
    unsichtbar war — der Fehler dieser Richtung kostet einen zweiten Klick,
    nicht eine verschwundene Nachricht."""
    _form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.kontakt_wiederherstellen(lead_id=lead_id))
    if "fehler" in antwort:
        return _fehlerseite(404, "Nicht wiederhergestellt",
                            _e(antwort["fehler"]))
    _kontakt_loggen(lead_id, "kontakt_archiviert", {"archiviert": False})
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def kontakt_detail(request):
    roh = request.path_params["lead_id"]
    try:
        lead_id = str(uuid.UUID(roh))
    except ValueError:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"&#x27;{_e(roh)}&#x27; ist keine lead_id.")
    leads = server._q(
        "select id, name, email, phone, company, title, source, status, "
        "consent_status, notes, enrichment, created_at from leads "
        "where id = %s", (lead_id,))
    if not leads:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"Kein Kontakt mit lead_id {_e(lead_id)}.")
    lead = leads[0]
    anreicherung = lead["enrichment"] or {}
    archiviert = server._archiviert(anreicherung)

    stammdaten = "".join(
        f"<tr><th>{_e(name)}</th><td>{_e(lead[feld])}</td></tr>"
        for name, feld in (("Name", "name"), ("Status", "status"),
                           ("Consent", "consent_status"), ("E-Mail", "email"),
                           ("Telefon", "phone"), ("Firma", "company"),
                           ("Titel", "title"), ("Quelle", "source"),
                           ("Notizen", "notes")))
    teile = []
    if archiviert:
        teile.append(
            '<div class="hinweis">Dieser Kontakt ist <b>archiviert</b>: er '
            'steht nicht in der Kontaktliste, nicht im Posteingang und nicht '
            'in der Zuordnungsauswahl der Einordnung. Geloescht wurde nichts '
            '— der Verlauf unten ist vollzaehlig.</div>')
    # Der Hinweis nach einer Nummernaenderung. Die Seite liest aus dem
    # Abfrageteil NUR, WELCHER der hier fest verdrahteten Hinweise gezeigt
    # wird — der Text selbst kommt nie von dort (er waere sonst ein Fremddatum
    # in der eigenen Seite, und eine praeparierte Verknuepfung koennte dem
    # Betreiber Beliebiges in den Mund legen).
    if request.query_params.get("gespeichert") == "telefon":
        teile.append(
            '<div class="warnung">Telefonnummer geaendert. Damit wechselt der '
            'Schluessel, ueber den eingehende Nachrichten diesem Kontakt '
            'zugeordnet werden: Nachrichten von der ALTEN Nummer landen ab '
            'sofort beim Sammelkontakt „Unbekannte Eingaenge" und muessen '
            'unter /einordnung neu zugeordnet werden; ausgehende Entwuerfe '
            'gehen an die NEUE Nummer. Bereits gebuchte Zeilen im Verlauf '
            'bleiben, wo sie sind (activities ist append-only). Laeuft der '
            'Kontakt im Auto-Betrieb, greift die Aenderung dort erst nach '
            'scripts/sync-allowlist.ps1.</div>')
    teile.append(f"<table>{stammdaten}<tr><th>Angelegt</th>"
                 f"<td>{_zeit(lead['created_at'])}</td></tr></table>")
    teile.append(_kontakt_formular(lead))

    # Bedarfsstand: beantwortete Leitfaden-Fragen mit Wortlaut, offene als Zahl.
    bedarf = anreicherung.get("bedarf") or {}
    teile.append(f"<h2>Bedarfsstand ({len(bedarf)} beantwortet, "
                 f"{max(len(server.ALLE_FRAGEN) - len(bedarf), 0)} offen)</h2>")
    if bedarf:
        zeilen = "".join(
            f"<tr><td>{_e(server.ALLE_FRAGEN.get(fid, {}).get('frage', fid))}"
            f"</td><td>{_e((wert or {}).get('antwort') if isinstance(wert, dict) else wert)}"
            f"</td></tr>" for fid, wert in sorted(bedarf.items()))
        teile.append(f"<table><tr><th>Frage</th><th>Antwort</th></tr>"
                     f"{zeilen}</table>")
    else:
        teile.append("<p>Noch keine Antworten erfasst.</p>")

    # Vertraege (enrichment.vertraege) — nur wenn es wirklich ein Array ist,
    # dieselbe Typ-Vorsicht wie vertraege_ablaufend in server.py.
    vertraege = anreicherung.get("vertraege")
    vertraege = vertraege if isinstance(vertraege, list) else []
    teile.append(f"<h2>Vertraege ({len(vertraege)})</h2>")
    if vertraege:
        zeilen = "".join(
            f"<tr><td>{_e(v.get('sparte'))}</td>"
            f"<td>{_e(v.get('gesellschaft'))}</td>"
            f"<td>{_e(v.get('ablauf'))}</td></tr>"
            for v in vertraege if isinstance(v, dict))
        teile.append(f"<table><tr><th>Sparte</th><th>Gesellschaft</th>"
                     f"<th>Ablauf</th></tr>{zeilen}</table>")
    else:
        teile.append("<p>Keine Vertraege erfasst.</p>")

    teile.append("<h2>Offene Wiedervorlagen</h2>")
    teile.append(_wiedervorlagen_tabelle(_offene_wiedervorlagen(lead_id),
                                         mit_kontakt=False))

    # Verlauf chronologisch — die Payload als gekuerzte Vorschau, escaped:
    # jedes Feld darin kann Kundentext sein.
    aktivitaeten = server._q(
        "select type, actor, payload, created_at from activities "
        "where lead_id = %s order by created_at asc limit %s",
        (lead_id, AKTIVITAETEN_MAX))
    teile.append(f"<h2>Verlauf ({len(aktivitaeten)})</h2>")
    if aktivitaeten:
        zeilen = []
        for a in aktivitaeten:
            vorschau = json.dumps(a["payload"] or {}, ensure_ascii=False)
            if len(vorschau) > PAYLOAD_KURZ:
                vorschau = vorschau[:PAYLOAD_KURZ] + "…"
            zeilen.append(f"<tr><td>{_zeit(a['created_at'])}</td>"
                          f"<td>{_e(a['type'])}</td><td>{_e(a['actor'])}</td>"
                          f"<td>{_e(vorschau)}</td></tr>")
        teile.append(f"<table><tr><th>Wann</th><th>Typ</th><th>Wer</th>"
                     f"<th>Inhalt</th></tr>{''.join(zeilen)}</table>")
    else:
        teile.append("<p>Noch keine Aktivitaeten.</p>")

    teile.append(_archiv_bereich(lead, archiviert))
    return _seite(lead["name"] or "Kontakt", "".join(teile))


# ---------------------------------------------------------------------------
# Posteingang — spiegelt das Werkzeug, indem es ES SELBST aufruft
# ---------------------------------------------------------------------------

@_gesichert_seite
async def posteingang(request):
    # Kein zweites SQL fuer dieselbe Frage: die Seite ruft server.posteingang
    # auf — unbeantwortete zuerst, absenderscharf am Sammelkontakt, exakt die
    # Semantik des Chat-Werkzeugs (dort gemessen und getestet).
    daten = json.loads(server.posteingang())
    if "fehler" in daten:
        return _fehlerseite(503, "Posteingang nicht lesbar", _e(daten["fehler"]))
    teile = [f'<p class="meta">Fenster: {_e(daten["fenster_stunden"])} h · '
             f'unbeantwortet: {_e(daten["anzahl_unbeantwortet"])}</p>']
    if not daten["eintraege"]:
        teile.append("<p>Keine unbeantworteten Eingaenge.</p>")
    for e in daten["eintraege"]:
        absender = ""
        if "absender" in e:
            # @lid ist WhatsApps Privacy-Kennung, KEINE Rufnummer — als
            # solche kennzeichnen, sonst tippt jemand sie als Nummer ab.
            lid = (' <span class="badge lid">LID-Pseudo-Kennung, keine '
                   'Rufnummer</span>' if "@lid" in str(e["absender"]) else "")
            # Stufe 11: die Kennung ist aufgeloest und gehoert einem Kontakt.
            # Die alten Zeilen bleiben am Sammelkontakt (activities ist
            # append-only) — der Betreiber soll trotzdem sehen, WER wartet.
            if "zugeordnet_zu" in e:
                lid += (f' <span class="badge">gehoert zu '
                        f'<a href="/kontakte/{_e(e["zugeordnet_zu"])}">'
                        f'{_e(e.get("zugeordnet_name") or "Kontakt")}</a>'
                        f'</span>')
            absender = f'<div class="meta">Absender: {_e(e["absender"])}{lid}</div>'
        teile.append(
            f'<div class="karte"><b><a href="/kontakte/{_e(e["lead_id"])}">'
            f'{_e(e["kontakt"] or "(ohne Kontakt)")}</a></b> — wartet seit '
            f'{_e(e["wartet_stunden"])} h{absender}'
            f'<div class="text">{_e(e["text_kurz"])}</div></div>')
    if "hinweis" in daten:
        teile.append(f'<div class="hinweis">{_e(daten["hinweis"])}</div>')
    return _seite("Posteingang", "".join(teile))


# ---------------------------------------------------------------------------
# Einordnung unbekannter Absender (/einordnung) — „wer ist das?"
#
# Die Seite ist eine Sicht auf server._einzuordnende() und drei Knoepfe, die
# server.eingang_einordnen() bzw. server.kontakt_anlegen() aufrufen. Eigenes
# SQL gibt es hier bewusst nicht: die Kanten dieser Stufe (H3 — ein echter
# Kontakt laesst sich nicht beilaeufig stummschalten; H4 — rohe Kennung vs.
# aufgeloeste Nummer) sitzen in server.py und sollen genau EINMAL existieren.
# ---------------------------------------------------------------------------

def _lead_zur_kennung(absender):
    """Gehoert diese Kennung einem Kontakt im CRM? — oder None.

    GENAU die Pruefung, mit der `eingang_einordnen` das Ignorieren verweigert
    (`lid_kanonisch` + `_lead_mit_gleicher_nummer`), damit Anzeige und
    Verweigerung nie Verschiedenes behaupten. Sie steht zusaetzlich zu dem, was
    `_einzuordnende` selbst schon sortiert: dessen `kanon` loest in SQL auf und
    greift damit nur bei Kennungen MIT Domain — eine als blanke Ziffernfolge
    oder als `…@s.whatsapp.net` gebuchte Kennung landete unter 'neu', obwohl
    sie einem Kontakt gehoert. Hier faellt sie auf.
    """
    aufgeloest = server.lid_kanonisch(absender)
    if not str(aufgeloest).endswith("@c.us"):
        return None
    return server._lead_mit_gleicher_nummer(aufgeloest)


def _kontakt_optionen() -> str:
    """Die Auswahlliste fuer 'zuordnen' — EINMAL gebaut, je Absender benutzt.

    Der Sammelkontakt selbst steht nicht drin: ihm etwas zuzuordnen waere die
    Nicht-Entscheidung, und er hat ohnehin keine Rufnummer.

    Kontakte OHNE Telefonnummer stehen bewusst drin: wer fehlt, ist nicht
    waehlbar, und das waere hier der schlechtere Fehler — `eingang_einordnen`
    sagt bei einem Kontakt ohne brauchbare Nummer selbst, was zu tun ist.
    ARCHIVIERTE stehen bewusst NICHT drin: sie sind weggeraeumt, und eine
    Zuordnung an sie holte sie durch die Hintertuer zurueck, ohne dass ihre
    Nachrichten danach im Posteingang stuenden. Gefiltert in SQL, damit
    KONTAKTE_MAX die waehlbaren deckelt (dieselbe Regel wie in Python:
    server._archiv_sql spiegelt server._archiviert).
    Die Seitengroesse ist beidseitig gedeckelt: hoechstens KONTAKTE_MAX
    Eintraege je Feld, hoechstens EINORDNUNG_LIMIT Felder
    (server.EINORDNUNG_LIMIT).
    """
    zeilen = server._q(
        "select id, name from leads l where not "
        + server._archiv_sql("l.enrichment") +
        " order by name asc limit %s", (KONTAKTE_MAX,))
    return "".join(
        f'<option value="{_e(z["id"])}">{_e(z["name"])}</option>'
        for z in zeilen if str(z["id"]) != str(server.UNBEKANNT_LEAD_ID))


def _einordnung_kopf() -> str:
    """Das Hidden-Feld, das in JEDEM Formular dieser Seite steht."""
    return f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'


def _einordnung_aktionen(absender, optionen: str) -> str:
    """Die drei Knoepfe je Absender. `bestaetigt` kommt hier NIRGENDS vor —
    der Lead-Fall bekommt eine eigene Seite mit eigenem Formular."""
    verborgen = (f'<input type="hidden" name="absender" '
                 f'value="{_e(absender)}">{_einordnung_kopf()}')
    return (
        f'<form class="aktion" method="post" action="/einordnung/zuordnen">'
        f'{verborgen}<select name="lead_id">'
        f'<option value="">— bestehender Kontakt —</option>{optionen}'
        f'</select> <button class="primaer">Zuordnen</button></form>'
        f'<form class="aktion" method="post" action="/einordnung/anlegen">'
        f'{verborgen}<input type="text" name="name" '
        f'maxlength="{EINORDNUNG_NAME_MAX}" placeholder="Name des Kontakts"> '
        f'<button>Neu anlegen</button></form>'
        f'<form class="aktion" method="post" action="/einordnung/ignorieren">'
        f'{verborgen}<button class="gefahr">Ignorieren</button></form>')


def _einordnung_karte(eintrag, optionen: str) -> str:
    absender = eintrag["absender"]
    lid_marke = (' <span class="badge lid">LID-Pseudo-Kennung, keine '
                 'Rufnummer</span>' if "@lid" in str(absender) else "")
    gefragt = (f' · im Chat gefragt am {_zeit(eintrag["gefragt_am"])}'
               if eintrag.get("gefragt_am") else " · noch nicht gefragt")
    betroffen = _lead_zur_kennung(absender)
    warnung = ""
    if betroffen is not None:
        # Sichtbar, BEVOR jemand auf „Ignorieren" drueckt — nicht erst danach.
        warnung = (f'<div class="warnung">Diese Kennung gehoert dem Kontakt '
                   f'<a href="/kontakte/{_e(betroffen["id"])}">'
                   f'<b>{_e(betroffen["name"])}</b></a>. Ignorieren nimmt ihn '
                   f'aus Posteingang und Digest und speichert von seinen '
                   f'Nachrichten kein Wort mehr — es braucht deshalb einen '
                   f'zweiten, ausdruecklichen Schritt.</div>')
    return (f'<div class="karte"><b>{_e(absender)}</b>{lid_marke}'
            f'<div class="meta">{_e(eintrag["anzahl_nachrichten"])} '
            f'Nachricht(en) · zuletzt {_zeit(eintrag["zuletzt"])}{gefragt}'
            f'</div>{warnung}'
            f'<div class="text">{_e(eintrag["text_kurz"])}</div>'
            f'{_einordnung_aktionen(absender, optionen)}</div>')


@_gesichert_seite
async def einordnung(request):
    # Rein lesend (Moduldocstring): eingang_einordnen() ohne Argumente wuerde
    # beim Seitenaufruf den Rueckfrage-Anspruch beanspruchen. Aus demselben
    # Grund traegt diese Seite KEINEN Meta-Refresh — er wuerde ausserdem ein
    # halb getipptes Namensfeld unter den Fingern des Betreibers wegraeumen.
    koerbe = server._einzuordnende(text_max=EINORDNUNG_TEXT_MAX)
    # Im Chat sind 'neu' und 'bereits_gefragt' zwei Toepfe, weil dort die Frage
    # GESTELLT wird und nicht zweimal gestellt werden darf. Hier wird sie nur
    # gezeigt — also ist beides schlicht „wartet auf Entscheidung".
    offen = koerbe["neu"] + koerbe["bereits_gefragt"]
    offen.sort(key=lambda e: str(e["zuletzt"]), reverse=True)
    optionen = _kontakt_optionen()

    teile = [f"<h2>Wartet auf Entscheidung ({len(offen)})</h2>"]
    if not server.UNBEKANNT_LEAD_ID:
        teile.append(
            '<div class="hinweis">Kein Sammelkontakt eingerichtet '
            '(INBOX_UNBEKANNT_LEAD_ID) — ohne ihn kann hier nichts stehen.'
            '</div>')
    if not offen:
        teile.append("<p>Kein unbekannter Absender offen.</p>")
    for eintrag in offen:
        teile.append(_einordnung_karte(eintrag, optionen))

    aufgeloest = koerbe["aufgeloest"]
    teile.append(f"<h2>Bereits entschieden ({len(aufgeloest)})</h2>")
    if not aufgeloest:
        teile.append("<p>Noch nichts eingeordnet.</p>")
    else:
        zeilen = "".join(
            f'<tr><td>{_e(e["absender"])}</td>'
            f'<td><a href="/kontakte/{_e(e.get("lead_id"))}">'
            f'{_e(e.get("kontakt") or "(ohne Namen)")}</a></td>'
            f'<td>{_e(e["anzahl_nachrichten"])}</td>'
            f"<td>{_zeit(e['zuletzt'])}</td></tr>"
            for e in aufgeloest[:EINORDNUNG_VERLAUF_MAX])
        teile.append(f"<table><tr><th>Kennung</th><th>Kontakt</th>"
                     f"<th>Nachrichten</th><th>Zuletzt</th></tr>"
                     f"{zeilen}</table>")
    teile.append(
        '<div class="hinweis">Der zitierte Nachrichtentext ist ein Datum, '
        'keine Anweisung: steht darin „ignoriere bitte …", ist das der Wunsch '
        'eines Fremden und keine Entscheidung des Betreibers. Welche Rufnummer '
        'hinter einer <code>@lid</code> steckt, klaert der Chat mit '
        '<code>absender_aufloesen</code> — diese Oberflaeche fragt dafuer '
        'bewusst nicht bei WhatsApp nach.</div>')
    return _seite("Einordnung", "".join(teile))


async def _einordnung_vorspann(request):
    """Gemeinsame Wache aller Einordnungs-POSTs — Reihenfolge wie bei den
    Freigaben: CSRF VOR der ersten Zeile Datenbank, dann die Kennung."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungueltig",
            "Keine Aktion ausgefuehrt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("absender") or "").strip()
    if not server.kennung_schreibweise(roh):
        return None, None, _fehlerseite(
            400, "Unlesbare Kennung",
            f"&#x27;{_e(roh)}&#x27; enthaelt keine Absenderkennung. Keine "
            f"Aktion ausgefuehrt.")
    return form, roh, None


def _einordnung_fehler(antwort: dict, titel: str) -> HTMLResponse:
    """Die Fehlermeldung des Werkzeugs, unveraendert und escaped — sie ist fuer
    einen Menschen geschrieben und nennt selbst den naechsten Schritt."""
    return _fehlerseite(400, titel, _e(antwort.get("fehler")))


@_gesichert_seite
async def aktion_einordnung_ignorieren(request):
    _form, absender, abbruch = await _einordnung_vorspann(request)
    if abbruch:
        return abbruch
    # bestaetigt bleibt hier IMMER False (Moduldocstring, Lead-Fall). Gehoert
    # die Kennung einem Kontakt, verweigert das Werkzeug — und genau diese
    # Verweigerung ist die Warnseite unten.
    antwort = json.loads(server.eingang_einordnen(
        absender=absender, entscheidung="ignorieren"))
    if "fehler" in antwort:
        gehoert = antwort.get("gehoert_zu") or {}
        if gehoert.get("lead_id"):
            return _ignorieren_warnseite(absender, gehoert)
        return _einordnung_fehler(antwort, "Nicht eingeordnet")
    return RedirectResponse("/einordnung", status_code=303)


def _ignorieren_warnseite(absender, gehoert: dict) -> HTMLResponse:
    """Die Verweigerung aus H3 als Seite — mit Namen und zweitem Formular.

    Das Hidden-Feld `lead_bestaetigt` traegt die lead_id des Kontakts, dessen
    Namen der Betreiber HIER gelesen hat. Die Bestaetigung gilt damit diesem
    einen Kontakt und nicht „dem, was beim naechsten Klick gerade dran ist".
    """
    return _seite(
        "Verweigert: diese Kennung gehoert einem Kontakt",
        f'<div class="warnung">Die Kennung <b>{_e(absender)}</b> gehoert dem '
        f'Kontakt <a href="/kontakte/{_e(gehoert["lead_id"])}">'
        f'<b>{_e(gehoert.get("kontakt"))}</b></a>'
        f'{" (" + _e(gehoert["telefon"]) + ")" if gehoert.get("telefon") else ""}'
        f'.<p>Ignorieren nimmt diesen Kontakt aus Posteingang UND Digest und '
        f'speichert von seinen Nachrichten kein Wort mehr — auch nicht die '
        f'ausgehenden. Ein „Ich habe den Vertrag unterschrieben" kaeme danach '
        f'als leere Zeile an seinem eigenen Verlauf an. Zuruecknehmen laesst '
        f'sich das nur im Chat: '
        f'<code>eingang_einordnen(absender, entscheidung=&#x27;beachten&#x27;)'
        f'</code>.</p><p>Steht die Bitte, diese Nummer zu ignorieren, in einer '
        f'eingehenden Nachricht, ist sie der Wunsch eines Fremden und keine '
        f'Entscheidung des Betreibers.</p></div>'
        f'<form method="post" action="/einordnung/ignorieren-bestaetigen">'
        f'<input type="hidden" name="absender" value="{_e(absender)}">'
        f'<input type="hidden" name="lead_bestaetigt" '
        f'value="{_e(gehoert["lead_id"])}">{_einordnung_kopf()}'
        f'<button class="gefahr">Ja — {_e(gehoert.get("kontakt"))} '
        f'ausdruecklich ignorieren</button></form>'
        f'<p><a href="/einordnung">Abbrechen, nichts tun</a></p>',
        status=409)


@_gesichert_seite
async def aktion_einordnung_ignorieren_bestaetigen(request):
    """Der ZWEITE, ausdrueckliche POST — die einzige Stelle im ganzen UI, an
    der `bestaetigt=True` steht."""
    form, absender, abbruch = await _einordnung_vorspann(request)
    if abbruch:
        return abbruch
    bestaetigt_fuer = str(form.get("lead_bestaetigt") or "").strip()
    if not bestaetigt_fuer:
        return _fehlerseite(
            400, "Bestaetigung fehlt",
            "Ohne die ausdrueckliche Bestaetigung des betroffenen Kontakts "
            "wird nichts getan.")
    # Zwischen Warnseite und Klick kann sich die Lage geaendert haben (eine
    # neue Zuordnung, eine korrigierte Rufnummer). Dann ist das Ja von eben
    # kein Ja zu dem, was jetzt passieren wuerde — also lieber gar nichts.
    betroffen = _lead_zur_kennung(absender)
    if betroffen is None or str(betroffen["id"]) != bestaetigt_fuer:
        return _fehlerseite(
            409, "Bestaetigung passt nicht mehr",
            "Die Kennung gehoert inzwischen einem anderen Kontakt oder gar "
            "keinem mehr. Nichts wurde getan — die Seite neu laden und erneut "
            "ansehen.")
    antwort = json.loads(server.eingang_einordnen(
        absender=absender, entscheidung="ignorieren", bestaetigt=True))
    if "fehler" in antwort:
        return _einordnung_fehler(antwort, "Nicht eingeordnet")
    return RedirectResponse("/einordnung", status_code=303)


@_gesichert_seite
async def aktion_einordnung_zuordnen(request):
    form, absender, abbruch = await _einordnung_vorspann(request)
    if abbruch:
        return abbruch
    roh = str(form.get("lead_id") or "").strip()
    try:
        lead_id = str(uuid.UUID(roh))
    except ValueError:
        return _fehlerseite(
            400, "Kein Kontakt gewaehlt",
            f"&#x27;{_e(roh)}&#x27; ist keine lead_id. Im Auswahlfeld einen "
            f"Kontakt waehlen. Keine Aktion ausgefuehrt.")
    antwort = json.loads(server.eingang_einordnen(
        absender=absender, entscheidung="zuordnen", lead_id=lead_id))
    if "fehler" in antwort:
        return _einordnung_fehler(antwort, "Nicht zugeordnet")
    return RedirectResponse("/einordnung", status_code=303)


@_gesichert_seite
async def aktion_einordnung_anlegen(request):
    """Neuer Kontakt aus einer Einordnung heraus.

    `eingang_einordnen` kennt fuer diesen Fall bewusst KEINE eigene
    Entscheidung — sein Docstring nennt den Weg: „Soll ein NEUER Kontakt
    entstehen: erst kontakt_anlegen(name, phone=…), dann hier zuordnen."
    (ENTSCHEIDUNGEN sind nur zuordnen/ignorieren/beachten.) Genau das tut diese
    Route — und den zweiten Schritt braucht sie nicht: sobald der neue Kontakt
    die Rufnummer traegt, findet `_einzuordnende` ihn ueber
    `_lead_mit_gleicher_nummer` von selbst, und der Absender steht beim
    naechsten Aufruf unter 'aufgeloest'. Ein `zuordnen` obendrauf legte nur
    eine Zuordnung Nummer->dieselbe Nummer an, die das Werkzeug zu Recht
    zurueckweist.
    """
    form, absender, abbruch = await _einordnung_vorspann(request)
    if abbruch:
        return abbruch
    name = " ".join(str(form.get("name") or "").split())[:EINORDNUNG_NAME_MAX]
    if not name:
        return _fehlerseite(
            400, "Name fehlt",
            "Ein Kontakt ohne Namen ist nicht vorgesehen. Keine Aktion "
            "ausgefuehrt.")
    # Welche Rufnummer bekommt der neue Kontakt? Die, unter der die Kennung im
    # Haus gefuehrt wird (`lid_kanonisch`) — das ist bei `4917…@c.us` sie
    # selbst und bei einer bereits aufgeloesten `183…@lid` die gespeicherte
    # Nummer. Ist gar keine bekannt, wird NICHT angelegt: eine `@lid` ist
    # WhatsApps Privacy-Kennung und keine Rufnummer, und sie als phone
    # einzutragen hiesse, dem Dispatcher eine Fantasienummer zu geben.
    aufgeloest = server.lid_kanonisch(absender)
    if not str(aufgeloest).endswith("@c.us"):
        return _fehlerseite(
            400, "Kennung ist keine Rufnummer",
            f"Zu {_e(absender)} ist keine Rufnummer bekannt — eine "
            f"&#x27;@lid&#x27; ist WhatsApps Pseudo-Kennung und darf nie als "
            f"Telefonnummer eines Kontakts eingetragen werden. Zuerst im Chat "
            f"<code>absender_aufloesen(kennung=&#x27;{_e(absender)}&#x27;)"
            f"</code> laufen lassen (diese Oberflaeche fragt bewusst nicht "
            f"selbst bei WhatsApp nach), danach hier anlegen oder zuordnen. "
            f"Kein Kontakt angelegt.")
    antwort = json.loads(server.kontakt_anlegen(
        name=name, phone="+" + server.lid.ziffern(aufgeloest),
        source="whatsapp",
        notes="aus der Einordnung eines unbekannten Absenders (sales-ui)"))
    if "fehler" in antwort:
        return _einordnung_fehler(antwort, "Kontakt nicht angelegt")
    return RedirectResponse(f'/kontakte/{antwort["lead_id"]}', status_code=303)


@_gesichert_seite
async def wiedervorlagen(request):
    zeilen = _offene_wiedervorlagen()
    return _seite(f"Offene Wiedervorlagen ({len(zeilen)})",
                  _wiedervorlagen_tabelle(zeilen))


# ---------------------------------------------------------------------------
# App und Start
# ---------------------------------------------------------------------------

app = Starlette(routes=[
    Route("/", inbox),
    Route("/aktion/freigeben", aktion_freigeben, methods=["POST"]),
    Route("/aktion/ablehnen", aktion_ablehnen, methods=["POST"]),
    Route("/aktion/erneut-freigeben", aktion_erneut_freigeben,
          methods=["POST"]),
    Route("/kontakte", kontakte),
    # Die Pflege-Routen stehen VOR der Detailseite: `/kontakte/{lead_id}`
    # faengt sonst `/kontakte/bearbeiten` als lead_id ab (Starlette entscheidet
    # in Reihenfolge) und antwortete auf jeden POST mit 405.
    Route("/kontakte/bearbeiten", aktion_kontakt_bearbeiten, methods=["POST"]),
    Route("/kontakte/archivieren", aktion_kontakt_archivieren,
          methods=["POST"]),
    # Eigene Route fuer den zweiten Schritt, wie bei der Einordnung: der
    # ausdrueckliche Klick haengt nicht als Feld an dem Formular, das ihn
    # ausgeloest hat.
    Route("/kontakte/archivieren-bestaetigen",
          aktion_kontakt_archivieren_bestaetigen, methods=["POST"]),
    Route("/kontakte/wiederherstellen", aktion_kontakt_wiederherstellen,
          methods=["POST"]),
    Route("/kontakte/{lead_id}", kontakt_detail),
    Route("/posteingang", posteingang),
    Route("/einordnung", einordnung),
    Route("/einordnung/zuordnen", aktion_einordnung_zuordnen,
          methods=["POST"]),
    Route("/einordnung/anlegen", aktion_einordnung_anlegen, methods=["POST"]),
    Route("/einordnung/ignorieren", aktion_einordnung_ignorieren,
          methods=["POST"]),
    # Eigene Route fuer den zweiten Schritt — der ausdrueckliche Klick soll
    # nicht als Feld an demselben Formular haengen, das ihn ausgeloest hat.
    Route("/einordnung/ignorieren-bestaetigen",
          aktion_einordnung_ignorieren_bestaetigen, methods=["POST"]),
    Route("/wiedervorlagen", wiedervorlagen),
], middleware=[Middleware(HostWache)])


def _logging_einrichten() -> None:
    """Eigener Handler auf stdout — wie Inbox/Dispatcher, gleicher Grund:
    `import server` zieht ueber das mcp-Paket eine Root-Konfiguration auf
    stderr hoch, `logging.basicConfig()` waere dann ein stiller No-op."""
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main() -> int:
    _logging_einrichten()
    LOG.info("Start: schema=%s bind=%s:%d — Vertrauensgrenze ist das "
             "Compose-Portmapping 127.0.0.1:%d (nur Loopback, nicht ins "
             "Internet stellen).", server.SCHEMA, BIND_HOST, PORT, PORT)
    # Kein Zugriffslog (nur Pfade, kein Erkenntniswert — wie inbox.py);
    # uvicorn beendet selbst sauber auf SIGTERM/SIGINT.
    uvicorn.run(app, host=BIND_HOST, port=PORT, access_log=False,
                log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
