"""sales-ui — lokale Freigabe- und Datenansicht vor der Kundendatenbank (Stufe 10).

Der siebte Container: ein server-seitig gerendertes Web-UI fuer den Betreiber.
LESEN darf es Entwuerfe, Kontakte samt Chat-Reports, Posteingang,
Wiedervorlagen und die offenen Absender-Einordnungen. SCHREIBEN kann es
dreierlei, und nichts sonst:

1. die vier Entwurfs-Uebergaenge — freigeben (pending->approved), ablehnen
   (pending->rejected), erneut freigeben (failed->approved) und verwerfen
   (failed/approved->rejected) — mit EXAKT den SQL-Bedingungen der
   Chat-Werkzeuge aus server.py (entwurf_freigeben, entwurf_ablehnen,
   entwurf_erneut_freigeben, entwurf_verwerfen), nur mit
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
* Marken-Fall des Verwerfens (Betreiber-Wunsch 22.08.2026): dieselbe Marke,
  andersherum gelesen. Beim erneuten Freigeben waere ein zweiter Versand der
  Schaden, beim Verwerfen ein `rejected`, das eine moeglicherweise ERFOLGTE
  Zustellung verdeckt — eine Luege in der Datenbank. Das UI verweigert deshalb
  auch hier ausnahmslos; die ausdrueckliche Uebernahme bleibt dem Chat
  (`entwurf_verwerfen(..., bestaetigt=True)`, und aus `approved` heraus gibt
  es sie ueberhaupt nicht).
* Verwerfen aus `approved`: Zweischritt-Muster wie beim Lead- und Archiv-Fall.
  Der erste POST auf `/aktion/verwerfen` SCHREIBT NICHTS — er zeigt eine
  Warnseite mit Empfaenger und Textanfang. Erst der zweite POST auf eine
  eigene Route wirkt, und er traegt den EMPFAENGER, den der Betreiber gelesen
  hat. Aus `failed` heraus genuegt EIN Schritt: der Entwurf ging nachweislich
  nicht raus, und das Verwerfen versendet nichts — der Fehler dieser Richtung
  kostet einen Entwurfstext, keine ungewollte Zustellung.
* Chat-Reports schreibt die Oberflaeche NICHT, sie zeigt sie nur. Der Text
  einer Zusammenfassung entsteht im Sprachmodell des Agenten
  (`chat_report_speichern`); eine Oberflaeche ohne Modell haette dafuer nichts
  in der Hand. Die von einem Report abgedeckten Einzelnachrichten fallen auf
  der Kontaktseite aus dem Verlauf — geloescht ist nichts, `activities` bleibt
  append-only, und die Seite sagt es ausdruecklich.
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
import contextvars
import functools
import hashlib
import hmac
import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import secrets
import sys
import time
import uuid
from datetime import date, datetime, timezone

import passwort_reset
import psycopg
import uvicorn
from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

import kalender
import mailadresse
import ui_marketing
import verlinken

import server

# --- Konfiguration (Modulkonstanten, damit Tests sie umbiegen koennen) ------
BIND_HOST = os.environ.get("UI_HOST", "0.0.0.0")
PORT = int(os.environ.get("UI_PORT", "8791"))
# Nur diese Host-Header werden bedient (DNS-Rebinding, Moduldocstring).
# UI_EXTRA_HOSTS traegt zusaetzliche Adressen nach, kommagetrennt und OHNE
# Port (der wird angehaengt) — gedacht fuer genau einen Fall: den Zugriff vom
# eigenen Handy ueber ein privates Netz (Tailscale). Die Liste ist eine
# Erlaubnis, KEIN Schutz: wer den Port erreicht, kann den Host-Header
# faelschen. Der eigentliche Schutz ist das Compose-Portmapping, das den Port
# an genau die Loopback- und Tailscale-Adresse bindet und NICHT an 0.0.0.0 —
# sonst laege die Oberflaeche im normalen WLAN offen, wo sie ohne Anmeldung
# jedem Geraet Kundendaten zeigte.
_EXTRA = [h.strip() for h in os.environ.get("UI_EXTRA_HOSTS", "").split(",")
          if h.strip()]
# Schlussfix F (16.09.2026): `PORT` (oben, UI_PORT) ist der Container-
# INTERNE Port und bleibt fuer JEDEN Laden fest 8791 (docker-compose.yml,
# Dienst sales-ui) — ein zweiter Laden ist aber ueber einen ANDEREN
# Docker-Host-Port erreichbar (PORT_UI, docker-compose.yml Abschnitt
# ports:) und, hinter `tailscale serve`, ueber einen dritten, ebenfalls
# eigenen Port (Teil von UI_BASIS_URL). Gemessen an "ivan": Host-Port 8792,
# Serve-Port 8445 — beide weder 8791 noch das feste :443, das
# _erlaubte_hosts bis hierhin kannte. Ergebnis war HTTP 421 auf beiden
# Adressen, obwohl der Container gesund war (Host: <tailscale-ip> lieferte
# 200). Beide Werte sind Auskuenfte ueber GENAU diesen einen Laden — kein
# Platzhalter, keine Adresse eines anderen Ladens.
_HOST_PORT = os.environ.get("PORT_UI", "").strip()
_BASIS_URL = os.environ.get("UI_BASIS_URL", "").strip()


def _erlaubte_hosts(extra, port, host_port="", basis_url="") -> tuple:
    """Loopback mit Port plus jeden Extra-Eintrag in drei Formen: mit
    :PORT (direkter Zugriff), nackt und mit :443 — hinter `tailscale
    serve` reicht der Proxy den Original-Host durch (gemessen 31.08.2026:
    421 auf der HTTPS-Adresse, bevor es diese drei Formen gab).

    Dazu, laden-spezifisch (Schlussfix F, 16.09.2026):
    * `host_port` — der Docker-Host-Port DIESES Ladens (PORT_UI). Weicht er
      von `port` ab, bekommen Loopback UND localhost zusaetzlich die Form
      mit diesem Port.
    * `basis_url` — UI_BASIS_URL DIESES Ladens (die tailscale-serve-Adresse
      samt ihrem eigenen Port). Aufgenommen wird NUR die exakte Netzwerk-
      adresse (Host samt Port) daraus, nie Pfad/Query, und kein
      Platzhalter.

    Eine leere Zeichenkette bei `host_port`/`basis_url` aendert nichts am
    bisherigen Verhalten — der Basis-Laden bleibt unveraendert."""
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    if host_port and str(host_port) != str(port):
        hosts += [f"127.0.0.1:{host_port}", f"localhost:{host_port}"]
    for h in extra:
        hosts += [f"{h}:{port}", h, f"{h}:443"]
    if basis_url:
        netloc = urllib.parse.urlsplit(basis_url).netloc
        if netloc:
            hosts.append(netloc)
    return tuple(hosts)


ERLAUBTE_HOSTS = _erlaubte_hosts(_EXTRA, PORT, _HOST_PORT, _BASIS_URL)
# Boot-Token: lebt genau so lange wie der Prozess. Kein Persistieren, keine
# Sessions — es gibt genau einen Betreiber, und ein Neustart der Seite im
# Browser holt das frische Token von selbst (es steht in jedem Formular).
CSRF_TOKEN = secrets.token_urlsafe(32)

# --- Anmeldung (E1/F4, 31.08.2026) ------------------------------------------
# SCHARF, sobald UI_SESSION_SECRET gesetzt ist — ohne Secret verhaelt sich
# die Oberflaeche wie vorher (Uebergangszustand; scharf schalten tut der
# Betreiber mit deploy/benutzer-anlegen.sh). Die Sitzung ist ein signierter
# Cookie ueber name|ablauf; Rolle und aktiv kommen bei JEDER Anfrage frisch
# aus der Tabelle `benutzer` — deaktivieren wirft laufende Sitzungen sofort
# raus. Vertragstests: tests/test_login.py.
UI_SESSION_SECRET = os.environ.get("UI_SESSION_SECRET", "")
SITZUNG_COOKIE = "sitzung"
SITZUNG_DAUER_S = 12 * 3600
# Eine globale Bremse statt einer je Adresse: es gibt eine Handvoll
# Benutzer, und hinter Tailscale ist jede Adresse ohnehin ein bekanntes
# Geraet — global bremst auch den, der Adressen wechselt.
ANMELDE_BREMSE = {"fehler": 0, "gesperrt_bis": 0.0}
BREMSE_AB = 5
BREMSE_SPERRE_S = 60

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
# Welche Handytastatur ein Feld aufmacht. `type`/`inputmode` entscheiden auf
# dem Telefon darueber, ob unter dem Finger Ziffern und ein Plus liegen oder
# das Alphabet — eine Rufnummer auf der Buchstabentastatur einzugeben ist der
# Weg zum Zahlendreher, und ein Zahlendreher schickt die naechste Nachricht an
# einen Fremden. Die Werte sind EIGENE Zeichenketten und landen roh im Markup;
# hier darf nie etwas hinein, das aus der Datenbank kommt.
KONTAKT_FELD_EINGABE = {
    "name": 'type="text" autocomplete="name" autocapitalize="words"',
    "phone": 'type="tel" inputmode="tel" autocomplete="tel"',
    "email": ('type="email" inputmode="email" autocomplete="email" '
              'autocapitalize="none" spellcheck="false"'),
}
# Ein spaeter in server.KONTAKT_FELDER ergaenztes Feld erscheint als
# gewoehnliches Textfeld, statt zu fehlen.
KONTAKT_FELD_EINGABE_STANDARD = 'type="text"'

LOG = logging.getLogger("sales-ui")


def _e(wert) -> str:
    """html.escape fuer ALLES Fremde — None wird zur leeren Zeichenkette."""
    return html.escape(str(wert if wert is not None else ""), quote=True)


def _kurz(text, laenge=90) -> str:
    """Text auf `laenge` kuerzen, aber nur an einer Wortgrenze.

    Vorher schnitt die Anzeige hart nach n Zeichen ab; auf der Startseite
    endete ein Termin mit „Thema Vibe ·" und niemand sah, dass ein Satz
    fehlte. Der volle Text gehoert vom Aufrufer als `title` mitgegeben.

    Verwechslungsschutz: `kalender.py` hat eine GLEICHNAMIGE, aber andere
    Funktion `kalender._kurz(text)` — faltet Fehlertexte dieses Moduls hart
    auf `FEHLER_MAXLAENGE`, ohne Wortgrenze. Beide sind bewusst getrennt.
    """
    text = str(text or "").strip()
    if len(text) <= laenge:
        return text
    schnitt = text[:laenge]
    leer = schnitt.rfind(" ")
    # Nur an der Wortgrenze schneiden, wenn dabei nicht zu viel verloren
    # geht. Ein fester Bruchteil (vormals: ein Drittel) versagt bei
    # kleinen `laenge`-Werten wie 22 (Monatsgitter): dort verfehlte die
    # Schwelle jede Wortgrenze im plausiblen Bereich, und der Schnitt fiel
    # mitten ins Wort ("Kennenlernen Förderini…"). Jetzt: bei laengeren
    # Texten hoechstens 12 Zeichen verloren (kein im Betrieb vorkommendes
    # Wort ist laenger), bei kurzen `laenge`-Werten hoechstens die Haelfte.
    # Bei einer langen URL ohne Leerzeichen bleibt der harte Schnitt das
    # kleinere Uebel.
    schwelle = max(laenge // 2, laenge - 12)
    if leer > schwelle:
        schnitt = schnitt[:leer]
    return schnitt.rstrip(" ,;:·-–—") + "…"


def _text_html(text) -> str:
    """Wie _e — und http(s)-Adressen werden anklickbar (Betreiber 03.09.2026:
    „Hyperlinks werden als Text angezeigt"). Die Regel selbst steht in
    `verlinken.py`, weil die ausgehende Mail sie seit dem 23.09.2026 ebenso
    braucht; hier kommt nur der neue Reiter dazu."""
    return verlinken.text_html(
        text, ' rel="noreferrer noopener" target="_blank"')


# Ortszeit statt UTC (01.09.2026, im Kalender gefunden): ein 12:00-Termin
# stand als „10:00 UTC" da. Wer danach plant, verpasst ihn. Die Zone kommt
# aus der Umgebung — dieselbe, in der auch die Dienste laufen.
try:
    from zoneinfo import ZoneInfo
    ZEITZONE = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
except Exception:                    # noqa: BLE001 — ohne tzdata: UTC
    ZEITZONE = None


def _zeit(dt) -> str:
    """Zeitpunkt in Ortszeit. Ein Zeitstempel OHNE Zone gilt als UTC.

    Die Datenbank liefert durchweg `timestamptz` (db/provision.sql), also
    bewusste Zeitpunkte. Wo trotzdem ein naiver ankommt — aus einem
    JSON-Payload, aus einem Kalender-Import ohne Zonenangabe — waere die
    Alternative, ihn ungerechnet stehen zu lassen: genau das erzeugte
    dieselbe Buchung mit zwei Uhrzeiten (19:00 und 21:00, 10.09.2026).
    """
    if dt is None:
        return "—"
    if ZEITZONE is None:
        return dt.strftime("%d.%m.%Y %H:%M")
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZEITZONE).strftime("%d.%m.%Y %H:%M")


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
# `img-src`/`media-src 'self'` seit 25.08.2026: die Medienseite zeigt Bilder
# und spielt Videos ab, und mit `default-src 'none'` blockte der Browser
# beides. Ausdruecklich NUR 'self' — es wird nichts von fremden Adressen
# geladen. PDFs werden NICHT eingebettet, sondern verlinkt: ein PDF kann
# JavaScript enthalten, und ein `object-src` dafuer waere ein deutlich
# groesserer Schritt als ein Verweis.
_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
        "media-src 'self'; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'")

# Die Richtlinie fuer die ausgelieferte Datei selbst — haerter als die
# Seiten-Richtlinie: gar keine Quellen, und `sandbox` nimmt dem Inhalt
# Skripte, Formulare und die eigene Herkunft. Was hier ausgeliefert wird,
# hat ein Mensch hochgeladen; es soll trotzdem nichts ausfuehren koennen.
_CSP_DATEI = "default-src 'none'; sandbox"


def _dashboard_origin() -> str:
    """Die Origin des OpenWA-Dashboards — nur, wenn sie sich einbetten
    laesst (02.09.2026): eine HTTPS-Adresse, die der Browser des Betreibers
    erreicht. Die Loopback-Vorgabe http://127.0.0.1:12785 zeigt auf die VM
    selbst und waere im Rahmen ein leeres Feld; sie bleibt ein Verweis."""
    try:
        teile = urllib.parse.urlsplit(OPENWA_DASHBOARD_URL)
    except ValueError:
        return ""
    if teile.scheme != "https" or not teile.netloc:
        return ""
    return f"https://{teile.netloc}"


def _csp_mit_rahmen(origin: str) -> str:
    """Die Seiten-Richtlinie plus GENAU EINE Rahmenquelle. Nur Seiten mit Rahmen
    tragen sie (WhatsApp-Seite, Marketing-Entwurf, Layout-Galerie und -Editor);
    alle anderen behalten `default-src 'none'` ohne frame-src."""
    return f"{_CSP}; frame-src {origin}"


def _mit_koepfen(send):
    """Legt die Schutz-Koepfe auf jede Antwort — auch auf die Host-Fehlerseite."""
    async def send_mit_koepfen(nachricht):
        if nachricht["type"] == "http.response.start":
            koepfe = MutableHeaders(scope=nachricht)
            # Eine Antwort, die schon eine eigene Richtlinie traegt,
            # behaelt sie: die Dateiauslieferung setzt eine HAERTERE
            # (_CSP_DATEI). Die Zusicherung „jede Antwort ist
            # geschuetzt" bleibt damit, sie wird nur nicht
            # aufgeweicht.
            if "content-security-policy" not in koepfe:
                koepfe["Content-Security-Policy"] = _CSP
            koepfe["X-Content-Type-Options"] = "nosniff"
            koepfe["Referrer-Policy"] = "no-referrer"
            # Dasselbe fuer den Rahmen-Schutz: nur die Pult-Vorschau setzt
            # SAMEORIGIN (sie wird in die eigene Entwurfsseite gerahmt).
            if "x-frame-options" not in koepfe:
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
                "Diese Oberfläche antwortet nur auf 127.0.0.1, localhost "
                "und die ausdrücklich erlaubten Adressen (UI_EXTRA_HOSTS). "
                "Anfragen unter fremdem Namen (DNS-Rebinding) werden nicht "
                "bedient.")
            await antwort(scope, receive, send)
            return

        await self.app(scope, receive, send)


# Was die schmale Rolle `kalender` sehen darf. Ergaenzt 12.09.2026: die
# vorhandene Rolle `lesen` "sieht alles" — das sind saemtliche Kontakte,
# Entwuerfe und der Posteingang, also der komplette Kundenstamm. Ein
# Kollege, der nur Termine abgleichen soll, bekommt das nicht.
# Praefixe, keine Regex: eine Liste, die man vorlesen kann.
_KALENDER_ROLLE_PFADE = ("/team/kalender", "/kalender", "/logout", "/login",
                         "/passwort-vergessen", "/passwort-neu")


# "/marketing" (29.09.2026, Marketing-Pult Stufe 1): das Pult spricht mit
# der Marketing-API des Betreibers — dieselbe Huerde wie die Admin-Seiten.
_ADMIN_BASIS_PFADE = ("/team/laden-anlegen", "/team/tailscale-einladen",
                      "/marketing")


def _pfad_erlaubt(rolle: str, pfad: str) -> bool:
    """Darf diese Rolle diesen Pfad sehen? `kalender` ist eingeschraenkt,
    jeder Pfad in `_ADMIN_BASIS_PFADE` zusaetzlich auf `freigeben` im
    Basis-Laden — sonst saehe Ivan (selbst mit der Rolle `freigeben` in
    seinem eigenen Laden) Knoepfe, die auf dem Wirt handeln (Container
    erzeugen, eine Tailscale-Einladung mit dem persoenlichen Schluessel
    des Betreibers verschicken).

    `sales_test` zaehlt hier als Basis-Laden, nicht als eigener Laden: die
    Tabelle admin_auftraege existiert genau dort und in `sales`, nirgends
    sonst (db/provision.sql, hartes array['sales','sales_test'], Aufgabe 1 /
    test_admin_auftraege_tabelle.py::test_admin_auftraege_existiert_in_...);
    der Testcontainer verbindet ausschliesslich mit `sales_test` (nie mit
    `sales`), waere `sales_test` hier NICHT gleichgestellt, saehe in JEDEM
    Testlauf niemand einen der beiden Knoepfe — auch nicht die Rolle
    `freigeben` selbst."""
    if any(pfad == p or pfad.startswith(p + "/") for p in _ADMIN_BASIS_PFADE):
        return rolle == "freigeben" and server.SCHEMA in ("sales", "sales_test")
    if rolle != "kalender":
        return True
    return any(pfad == p or pfad.startswith(p + "/")
               for p in _KALENDER_ROLLE_PFADE)


class AnmeldeWache:
    """Ohne gueltige Sitzung keine Seite und kein POST — ausser /login.

    Pure-ASGI wie die HostWache und INNERHALB von ihr (fremde Hosts
    scheitern zuerst). Ohne UI_SESSION_SECRET ist die Wache durchlaessig —
    der dokumentierte Uebergangszustand, bis der Betreiber Benutzer
    anlegt (deploy/benutzer-anlegen.sh). Rolle `lesen` sieht alles und
    darf nichts veraendern; /logout bleibt ihr als einziger POST."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not UI_SESSION_SECRET:
            await self.app(scope, receive, send)
            return
        if scope["path"] in ("/login", "/passwort-vergessen", "/passwort-neu"):
            # Die zwei Reset-Seiten muessen OHNE Sitzung erreichbar sein -
            # eine Wache davor schuetzte sie vor ihrem einzigen Benutzer.
            # Sie sind nicht ungeschuetzt: /passwort-neu verlangt einen
            # gueltigen Einmal-Token, und /passwort-vergessen kann nichts
            # aendern, nur eine Mail an eine HINTERLEGTE Adresse ausloesen.
            await self.app(scope, receive, send)
            return
        name = _sitzung_pruefen(_cookie_wert(scope, SITZUNG_COOKIE))
        benutzer = _benutzer_lesen(name) if name else None
        if not benutzer:
            if scope["method"] in ("GET", "HEAD"):
                antwort = RedirectResponse("/login", status_code=303)
            else:
                antwort = _fehlerseite(
                    403, "Nicht angemeldet",
                    "Diese Aktion braucht eine Anmeldung. Nichts wurde "
                    "getan — erst anmelden, dann erneut.")
            await antwort(scope, receive, send)
            return
        scope["benutzer_name"] = benutzer["name"]
        scope["benutzer_rolle"] = benutzer["rolle"]
        if not _pfad_erlaubt(benutzer["rolle"], scope["path"]):
            antwort = _fehlerseite(
                403, "Nicht für diese Anmeldung",
                "Diese Anmeldung sieht den Kalender und die Seite zum "
                "Verbinden — sonst nichts. Nichts wurde getan.")
            await antwort(scope, receive, send)
            return
        if (benutzer["rolle"] in ("lesen", "kalender")
                and scope["method"] not in ("GET", "HEAD")
                and scope["path"] not in (
                    "/logout", "/team/kalender/verbinden",
                    # W3 (Schlusspruefung 13.09.2026): das Gegenstueck zu
                    # "verbinden" braucht dieselbe Ausnahme — sonst kann
                    # ausgerechnet der Kollege mit der schmalen Rolle die
                    # eigene tote Quelle nicht entfernen.
                    "/team/kalender/entfernen")):
            antwort = _fehlerseite(
                403, "Nur Lesen",
                "Diese Anmeldung darf sehen, aber nicht verändern. "
                "Nichts wurde getan — Freigaben braucht die Rolle "
                "'freigeben'.")
            await antwort(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _csrf_ok(form) -> bool:
    """Vergleich in konstanter Zeit — wie die Signaturpruefung in inbox.py."""
    token = str(form.get("csrf") or "")
    return bool(token) and hmac.compare_digest(token, CSRF_TOKEN)


# --- Anmelde-Handwerk (E1/F4) -----------------------------------------------

def _passwort_hashen(klartext: str) -> str:
    """scrypt aus der Standardbibliothek — kein Zusatzpaket, gesalzen,
    Format scrypt$<salz-hex>$<hash-hex>."""
    salz = secrets.token_bytes(16)
    wert = hashlib.scrypt(klartext.encode("utf-8"), salt=salz,
                          n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salz.hex()}${wert.hex()}"


def _passwort_pruefen(klartext: str, gespeichert: str) -> bool:
    """Still falsch bei jedem kaputten Hash — ein unlesbarer Eintrag darf
    nie zur offenen Tuer werden."""
    try:
        verfahren, salz_hex, wert_hex = (gespeichert or "").split("$")
        if verfahren != "scrypt":
            return False
        wert = hashlib.scrypt(klartext.encode("utf-8"),
                              salt=bytes.fromhex(salz_hex),
                              n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(wert.hex(), wert_hex)
    except (ValueError, TypeError):
        return False


def _sitzung_bauen(name: str, ablauf: float) -> str:
    basis = f"{name}|{int(ablauf)}"
    sig = hmac.new(UI_SESSION_SECRET.encode("utf-8"), basis.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"{basis}|{sig}"


def _sitzung_pruefen(cookiewert: str):
    """Benutzername der gueltigen Sitzung oder None — nur Signatur und
    Ablauf; Rolle und aktiv holt der Aufrufer FRISCH aus der Datenbank."""
    teile = (cookiewert or "").split("|")
    if len(teile) != 3:
        return None
    name, ablauf, sig = teile
    erwartet = hmac.new(UI_SESSION_SECRET.encode("utf-8"),
                        f"{name}|{ablauf}".encode("utf-8"),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, erwartet):
        return None
    try:
        if int(ablauf) < time.time():
            return None
    except ValueError:
        return None
    return name


def _cookie_wert(scope, name: str) -> str:
    roh = Headers(scope=scope).get("cookie", "")
    for teil in roh.split(";"):
        schluessel, _, wert = teil.strip().partition("=")
        if schluessel == name:
            return wert
    return ""


def _benutzer_lesen(name: str):
    zeilen = server._q(
        "select name, rolle from benutzer where name = %s and aktiv",
        (name,))
    return zeilen[0] if zeilen else None


def _ui_akteur(request) -> str:
    """Wer hier handelt: der angemeldete Benutzer — oder der alte
    Sammelstempel 'betreiber-ui', solange die Anmeldung nicht scharf ist."""
    return str(request.scope.get("benutzer_name") or "betreiber-ui")


def _gesichert_seite(fn):
    """DB-Ausfall wird zur lesbaren Seite, nie zum Traceback (Muster
    `_gesichert` aus server.py, nur mit HTML statt JSON)."""
    @functools.wraps(fn)
    async def innen(request):
        _AKTIVER_PFAD.set(request.url.path)
        _AKTIVE_ROLLE.set(str(request.scope.get("benutzer_rolle") or ""))
        try:
            return await fn(request)
        except psycopg.OperationalError:
            return _fehlerseite(503, "Datenbank nicht erreichbar",
                                "Gerade wird NICHTS gelesen oder geschrieben. "
                                "Später erneut versuchen.")
        except psycopg.Error as e:
            # Nur der SQLSTATE — Fehlertexte der DB koennen Fremddaten tragen.
            return _fehlerseite(503, "Datenbankfehler",
                                f"SQLSTATE {_e(e.sqlstate)}.")
    return innen


# ---------------------------------------------------------------------------
# HTML-Geruest (server-seitig, Inline-CSS, kein JavaScript)
#
# HANDYTAUGLICH (Betreiber-Wunsch 22.08.2026): der Betreiber erreicht die
# Oberflaeche seit dem Tailscale-Zugang vom iPhone. Gebaut ist sie fuer einen
# Desktop-Browser. Nachgezogen wird das in REINEM CSS — kein JavaScript (die
# CSP sagt `default-src 'none'`, und eine Freigabeoberflaeche ohne Skripte ist
# eine Zusage, keine Bequemlichkeit) und keine externen Ressourcen (Fonts,
# CDNs; die CSP verbietet sie, und der Rechner ist im Zweifel offline).
#
# Vier Entscheidungen tragen den Rest:
#
# 1. FARBEN ALS VARIABLEN, dazu ein zweiter Satz unter
#    `prefers-color-scheme: dark`. Ein Telefon steht abends dauerhaft auf
#    dunkel; eine gleissend weisse Seite ist dort nicht nur unangenehm,
#    sondern der Grund, sie nicht aufzumachen. Beide Saetze sind auf Kontrast
#    geprueft (Text >= 4.5:1, Rahmen >= 3:1) — auch die Warn- und Fehlerfarben,
#    die sonst gern die ersten sind, die im dunklen Satz absaufen.
# 2. TABELLEN WERDEN AUF SCHMALEN SCHIRMEN ZU KARTEN. Unterhalb 640px stehen
#    `tr`/`td` auf `display: block`, die Kopfzeile verschwindet und jede Zelle
#    traegt ihre Spaltenueberschrift ueber `::before` aus `data-label`. Die
#    Label kommen aus `_tabelle()` und sind IMMER eigener Text, nie Fremddaten
#    (siehe dort) — ein Kundenname in einem Attribut waere genau die Kante,
#    die `html.escape(quote=True)` sonst ueberall abdeckt.
# 3. TOUCH-ZIELE >= 44px, und zwischen benachbarten Aktionen echter Abstand.
#    Das ist hier kein Geschmack: neben „Freigeben" steht „Ablehnen", und ein
#    Fehlgriff verschickt eine Nachricht bzw. verwirft einen Entwurf.
# 4. DIE SEITE SCROLLT NIE WAAGERECHT. Fremddaten (Entwurfstexte, Kennungen,
#    Payload-Vorschauen) enthalten URLs und Base64-Klumpen ohne Leerzeichen;
#    `overflow-wrap: anywhere` bricht sie um, und was sich nicht brechen
#    laesst, scrollt in seinem EIGENEN Kasten (`.tabelle`).
# ---------------------------------------------------------------------------

_STIL = """
/* --- Farben. Heller Satz als Grundlage, dunkler als Überschreibung. ------
   Namen statt Werte im Rest des Stils: eine Farbe wird genau einmal
   entschieden und zweimal belegt, sonst driften helles und dunkles Thema
   auseinander, sobald jemand irgendwo ein #fff nachträgt. */
:root {
  color-scheme: light dark;
  --grund: #f5f4f0; --flaeche: #ffffff; --kopfzeile: #f0eee8;
  --aktiv: #e4e1d9;
  --schrift: #1c1b18; --gedaempft: #5c574c;
  --linie: #d8d4cc; --linie_stark: #8a8578;
  --balken: #2f2a24; --balken_schrift: #f5f4f0;
  --verweis: #14507f;
  --gut: #1a6b43; --gut_auf: #ffffff; --gut_text: #14603a;
  --info: #1f5b7a; --info_auf: #ffffff;
  --lila: #52447a; --lila_auf: #ffffff;
  --achtung: #8a4b00; --achtung_auf: #ffffff;
  --neutral: #5c574c; --neutral_auf: #ffffff;
  --fehler: #a01212; --fehler_auf: #ffffff;
  --fehler_flaeche: #fbe4e4; --fehler_linie: #b35a5a; --fehler_schrift: #6b1212;
  --hinweis_flaeche: #fdf3d7; --hinweis_linie: #a8892e;
  --hinweis_schrift: #4a3c10;
}
@media (prefers-color-scheme: dark) {
  :root {
    --grund: #171512; --flaeche: #26221d; --kopfzeile: #2a2721;
    --aktiv: #2e2a24;
    --schrift: #ece8e0; --gedaempft: #b0a99c;
    --linie: #4a443a; --linie_stark: #847d6e;
    --balken: #0d0c0a; --balken_schrift: #ece8e0;
    --verweis: #8cc0f0;
    --gut: #5fc98f; --gut_auf: #0c2418; --gut_text: #6ad39b;
    --info: #6fb6e0; --info_auf: #08202e;
    --lila: #b09ce0; --lila_auf: #191030;
    --achtung: #e0a35c; --achtung_auf: #2b1700;
    --neutral: #a8a196; --neutral_auf: #1b1915;
    --fehler: #ff8b8b; --fehler_auf: #2a0d0d;
    --fehler_flaeche: #3a1c1c; --fehler_linie: #a86464;
    --fehler_schrift: #ffc9c9;
    --hinweis_flaeche: #33290f; --hinweis_linie: #9c8542;
    --hinweis_schrift: #f2e2b4;
  }
}

*, *::before, *::after { box-sizing: border-box; }
/* Kein Auto-Vergrößern beim Drehen ins Querformat (iOS). */
html { -webkit-text-size-adjust: 100%; }
/* `overflow-wrap: anywhere` steht bewusst GANZ OBEN und vererbt sich: jede
   Zelle, jede Karte, jede Meta-Zeile kann Fremddaten tragen, und die Regel
   verkleinert auch die Mindestbreite von Tabellenzellen — genau das, was eine
   500 Zeichen lange URL sonst zur waagerechten Bildlaufleiste macht. */
html, body { overflow-x: hidden; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 0; background: var(--grund); color: var(--schrift);
       font-size: 16px; line-height: 1.45; overflow-wrap: anywhere; }
main { flex: 1 1 auto; min-width: 0; max-width: 80rem;
       padding: 1.2rem 2rem 4rem; }
a { color: var(--verweis); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       font-size: .92em; }

/* --- Seitenleiste (02.09.2026, UI-Plan Schritt 1): vier Gruppen statt
       zehn gleichrangiger Reiter. Unter 768 px wird sie wieder zur
       umbrechenden Zeile — die Vier-Tab-Leiste ist Schritt 7. --------- */
.rahmen { display: flex; align-items: flex-start; min-height: 100vh; }
nav.seite { width: 15rem; flex: none; background: var(--balken);
            color: var(--balken_schrift); display: flex;
            flex-direction: column; gap: 1.1rem; padding: 1rem .75rem;
            position: sticky; top: 0; height: 100vh; overflow-y: auto; }
nav.seite .marke { display: flex; align-items: center; gap: .6rem;
                   padding: 0 .5rem; font-weight: 700; }
nav.seite .logo { width: 1.9rem; height: 1.9rem; border-radius: 6px;
                  background: var(--gut); color: var(--gut_auf);
                  display: flex; align-items: center;
                  justify-content: center; }
.gruppe { display: flex; flex-direction: column; gap: .15rem; }
.gruppenname { font-size: .7rem; letter-spacing: .08em;
               text-transform: uppercase; color: var(--gedaempft);
               padding: 0 .7rem .2rem; font-weight: 600; }
nav.seite a { color: var(--balken_schrift); text-decoration: none;
              font-weight: 600; display: flex; align-items: center;
              gap: .6rem; min-height: 44px; padding: .5rem .7rem;
              border-radius: 6px; }
nav.seite a.aktiv { background: var(--aktiv); color: var(--gut); }
.zaehler { margin-left: auto; font-family: ui-monospace, SFMono-Regular,
           Menlo, Consolas, monospace; font-variant-numeric: tabular-nums;
           font-size: .78rem; font-weight: 600; padding: .05rem .5rem;
           border-radius: 999px; background: var(--kopfzeile);
           color: var(--gedaempft); }
.zaehler.offen { background: var(--achtung); color: var(--achtung_auf);
                 font-weight: 700; }
nav.seite .abmelden { margin-top: auto; padding: 0 .5rem; }
/* Vier-Tab-Leiste (Schritt 7): am Desktop unsichtbar. */
.tabs { display: none; }
/* --- Startseite „Heute" (UI-Plan Schritt 2): Aufgaben links, Lage
       rechts. Unter 768 px eine Spalte. ------------------------------ */
.heute { display: flex; gap: 1.6rem; align-items: flex-start; }
.heute .haupt { flex: 1 1 auto; min-width: 0; }
.heute .rand { width: 20rem; flex: none; display: flex;
               flex-direction: column; gap: 1.4rem; }
.heute .rand h2 { margin-top: 0; font-size: .72rem; letter-spacing: .08em;
                  text-transform: uppercase; color: var(--gedaempft); }
.heute .haupt h2 { margin-top: 1.4rem; }
.arten { display: flex; flex-wrap: wrap; gap: .8rem; align-items: center;
         margin: .2rem 0 .6rem; }
.art { display: inline-flex; align-items: center; gap: .4rem;
       color: var(--gedaempft); font-size: .9rem; }
.art b { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
         monospace; color: var(--schrift); font-weight: 600; }
.termin { display: flex; gap: .6rem; align-items: flex-start;
          padding: .3rem 0; }
.termin .zeit { width: 4.6rem; flex: none; font-family: ui-monospace,
                SFMono-Regular, Menlo, Consolas, monospace;
                font-variant-numeric: tabular-nums;
                color: var(--gedaempft); }
.termin .zeit.heute { color: var(--info); }
.kacheln { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
           gap: .4rem; }
.kachel { background: var(--flaeche); border: 1px solid var(--linie);
          border-radius: 6px; padding: .4rem .3rem; text-align: center; }
.kachel b { display: block; font-family: ui-monospace, SFMono-Regular,
            Menlo, Consolas, monospace; font-size: 1.1rem; }
.kachel span { font-size: .72rem; color: var(--gedaempft); }
@media (max-width: 767px) {
  .heute { display: block; }
  .heute .rand { width: auto; margin-top: 1.5rem; }
}
@media (max-width: 767px) {
  .rahmen { display: block; }
  nav.seite { display: flex; flex-direction: row; flex-wrap: wrap;
              width: auto; height: auto; position: static;
              gap: .15rem; padding: .3rem .5rem; }
  nav.seite .marke, .gruppenname { display: none; }
  .gruppe { display: contents; }
  /* Oben bleibt nur die aktive Gruppe — die anderen drei sitzen unten. */
  nav.seite .gruppe:not(.aktiv-gruppe) { display: none; }
  nav.seite a { padding: .5rem .8rem; }
  nav.seite .abmelden { margin-left: auto; padding: 0; }
  nav.tabs { display: flex; position: fixed; bottom: 0; left: 0; right: 0;
             z-index: 5; background: var(--balken);
             border-top: 1px solid var(--linie);
             padding: .25rem .4rem calc(.4rem + env(safe-area-inset-bottom)); }
  nav.tabs a { flex: 1 1 0; display: flex; flex-direction: column;
               align-items: center; justify-content: center; gap: .1rem;
               min-height: 56px; font-size: .7rem; font-weight: 600;
               letter-spacing: .04em; color: var(--gedaempft);
               text-decoration: none; min-width: 0; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }
  /* Sechs Reiter (29.09.2026): "Monitoring" brach mitten im Wort um. Die
     Beschriftung ist ein Flex-Kind - die Auslassung muss am <span> sitzen. */
  nav.tabs a > span:first-child { max-width: 100%; white-space: nowrap;
                                  overflow: hidden; text-overflow: ellipsis; }
  nav.tabs a.aktiv { color: var(--balken_schrift); }
  nav.tabs .zaehler { margin-left: 0; }
  main { padding-bottom: 6rem; }
}
@media (max-width: 399px) {
  nav.tabs a { font-size: .62rem; letter-spacing: 0; }
}

h1 { font-size: 1.3rem; margin: .2rem 0 .8rem; }
h2 { font-size: 1.05rem; margin-top: 2rem; }

.karte { background: var(--flaeche); border: 1px solid var(--linie);
         border-radius: 6px; padding: .8rem 1rem; margin: .7rem 0; }
.karte .text { white-space: pre-wrap; margin: .5rem 0; }

/* --- Pipeline-Spalten (27.08.2026): nebeneinander, bei Enge scrollt der
       Container waagerecht — nie die ganze Seite. ------------------------- */
.spalten { display: flex; gap: .8rem; align-items: flex-start;
           overflow-x: auto; padding-bottom: .5rem; }
.spalte { min-width: 11rem; flex: 1 0 11rem; }
.spalte h2 { margin-top: .4rem; font-size: .95rem; }
.spalte .karte { margin: .45rem 0; padding: .5rem .7rem; }
.meta { color: var(--gedaempft); font-size: .85rem; }

/* --- Monatsgitter (01.09.2026): ein Kalender sieht aus wie ein Kalender.
       Sieben Spalten, ein Kasten je Tag; bei Enge scrollt der Container
       waagerecht statt die ganze Seite. ------------------------------------ */
.monatskopf { display: flex; align-items: center; gap: 1rem;
              margin: .6rem 0 .4rem; }
.monatskopf a { text-decoration: none; padding: .1rem .5rem;
                border: 1px solid var(--linie); border-radius: 4px; }
.monat { display: grid; grid-template-columns: repeat(7, minmax(5.5rem, 1fr));
         gap: 2px; background: var(--linie); border: 1px solid var(--linie);
         overflow-x: auto; }
.tagkopf { background: var(--kopfzeile); padding: .3rem .4rem;
           font-size: .8rem; font-weight: 600; }
.tag { background: var(--flaeche); min-height: 4.6rem; padding: .25rem .3rem; }
.tag.leer { background: var(--grund); }
.tag.heute { outline: 2px solid var(--info); outline-offset: -2px; }
.tag .nummer { font-size: .8rem; color: var(--gedaempft); }
.tag .e { display: block; font-size: .75rem; line-height: 1.25;
          margin-top: .15rem; padding: .1rem .25rem; border-radius: 3px;
          background: var(--kopfzeile); text-decoration: none;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag .e.fremd { font-style: italic; color: var(--gedaempft); }

/* --- Eingebettetes OpenWA-Dashboard (02.09.2026) ------------------------- */
.dashboard { width: 100%; height: 78vh; min-height: 32rem; border: 1px solid
             var(--linie); border-radius: 4px; background: var(--flaeche); }

/* --- Marketing-Pult (29.09.2026): Felder links, Vorschau rechts; auf dem
   Telefon untereinander. Die Vorschau ist ein eigener, gesandboxter Rahmen. */
.pult { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1.2rem; }
@media (min-width: 768px) {
  .pult { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
.pult-felder label { display: block; margin: .6rem 0; font-weight: 600; }
.pult-felder input, .pult-felder textarea, .pult-felder select {
  display: block; width: 100%; margin-top: .3rem; }
.pult-felder fieldset { border: 1px solid var(--linie); border-radius: 4px;
                        margin: .6rem 0; padding: .5rem; }
/* Höhe gemessen am 29.09.2026: der Rahmen war 140 px hoch, weil die
   Medienlisten-Regel `.vorschau { max-height: 140px }` ihn mittraf. Die ist
   jetzt auf img/video beschränkt; max-height: none hält es fest. */
.pult-rechts iframe.vorschau { width: 100%; height: min(80vh, 1100px);
                               max-height: none; border: 1px solid
                               var(--linie); border-radius: 4px;
                               background: #ffffff; }
@media (max-width: 767px) {
  .pult-rechts iframe.vorschau { min-height: 70vh; } }
.pult-rechts iframe.vorschau.handy { max-width: 400px; display: block;
                                     margin: 0 auto; }
.mandanten { display: flex; flex-wrap: wrap; gap: .5rem; margin: .5rem 0 1rem; }
.mandant { border: 1px solid var(--linie); border-radius: 999px;
           padding: .2rem .8rem; font-weight: 600; }
.mandant.aus { color: var(--gedaempft); font-weight: 400; border-style: dashed; }
.filter, .vorschau-wahl { display: flex; flex-wrap: wrap; gap: .4rem;
                          margin: .5rem 0 1rem; }
.filter a, .vorschau-wahl a { padding: .3rem .8rem; border: 1px solid
                              var(--linie); border-radius: 999px; }
.filter a.aktiv, .vorschau-wahl a.aktiv { background: var(--aktiv);
                                          color: var(--gut); font-weight: 700; }
/* Layout-Galerie und -Editor (Task 5): Karten mit verkleinerter Vorschau.
   Der Rahmen rendert in doppelter Breite und wird auf die Haelfte skaliert,
   damit die Karte das ganze Layout zeigt; Klicks gehen an die Karte. */
.galerie { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem;
           margin-bottom: 1.5rem; }
@media (min-width: 640px) {
  .galerie { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (min-width: 1100px) {
  .galerie { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.layout-karte { border: 1px solid var(--linie); border-radius: 4px;
                padding: .6rem; background: var(--flaeche); }
.layout-karte > a { display: block; margin-top: .5rem; }
.layout-rahmen { height: 260px; overflow: hidden; border-radius: 3px;
                 background: #ffffff; }
iframe.layout-bild { width: 200%; height: 520px; border: 0;
                     transform: scale(.5); transform-origin: 0 0;
                     pointer-events: none; }
.abzeichen { border: 1px solid var(--gut); color: var(--gut); border-radius: 999px;
             padding: 0 .5rem; font-weight: 700; }
.pult-felder fieldset.farben { display: grid; gap: 0 1rem;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
.pult-felder input[type="color"] { height: 2.4rem; padding: .1rem; }
.pult-felder label.haken { display: inline-flex; align-items: center; gap: .4rem;
                           font-weight: 400; margin-right: 1rem; }
.pult-felder label.haken input { display: inline; width: auto; margin: 0; }

/* --- Geschäftsverweise (01.09.2026): anklickbare Absprung-Chips --------- */
.verweise { display: flex; flex-wrap: wrap; gap: .4rem; }
.verweis { display: inline-block; padding: .2rem .6rem; border-radius: 4px;
           border: 1px solid var(--linie); text-decoration: none;
           font-size: .85rem; }

/* --- Abzeichen: das Wort trägt die Aussage, die Farbe hilft nur ---------- */
.badge { display: inline-block; padding: .15rem .5rem; border-radius: 4px;
         font-size: .78rem; font-weight: 700; line-height: 1.6;
         color: var(--neutral_auf); background: var(--neutral);
         border: 1px solid transparent; margin: 0 .4rem .25rem 0; }
.badge.whatsapp { background: var(--gut); color: var(--gut_auf);
                  border-color: var(--gut); }
.badge.email { background: var(--info); color: var(--info_auf);
               border-color: var(--info); }
.badge.linkedin { background: var(--lila); color: var(--lila_auf);
                  border-color: var(--lila); }
.badge.lid { background: var(--achtung); color: var(--achtung_auf);
             border-color: var(--achtung); }
/* Archiviert und die vier Entwurfszustände tragen ihr Wort im HTML; Füllung
   gegen Umriss kommt als zweites, FARBUNABHÄNGIGES Merkmal dazu — auf einem
   sonnenbeschienenen Telefon ist ein Farbton kein Unterschied. */
.badge.archiv { background: transparent; color: var(--schrift);
                border: 1px dashed var(--linie_stark); }
.badge.zustand.pending { background: var(--achtung); color: var(--achtung_auf);
                         border-color: var(--achtung); }
.badge.zustand.failed { background: var(--fehler); color: var(--fehler_auf);
                        border-color: var(--fehler); }
.badge.zustand.approved { background: transparent; color: var(--gut_text);
                          border: 2px solid var(--gut_text); }
.badge.zustand.sent { background: transparent; color: var(--gedaempft);
                      border: 1px dashed var(--linie_stark); }
.badge.zustand.rejected, .badge.zustand.termin_abgesagt {
  background: transparent; color: var(--schrift);
  border: 1px solid var(--linie_stark); }
.badge.zustand.termin { background: transparent; color: var(--gut_text);
                        border: 2px solid var(--gut_text); }
.badge.zustand.termin_verschoben { background: var(--achtung);
                                   color: var(--achtung_auf); }
.badge.termin { background: transparent; color: var(--schrift);
                border: 1px solid var(--linie_stark); }
/* --- Monitoring (Schritt 6): Zustandskarten und Kette ---------------- */
.karten3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
           gap: .8rem; margin-top: .4rem; }
.karten3 .karte { margin: 0; }
.kette { display: flex; align-items: flex-start; gap: .3rem;
         overflow-x: auto; padding: .4rem 0 .6rem; }
.schritt { flex: 1 1 0; min-width: 8.5rem; }
.punkt { display: inline-block; width: .65rem; height: .65rem;
         border-radius: 999px; margin-right: .4rem; vertical-align: middle;
         background: var(--neutral); }
.punkt.gut { background: var(--gut); }
.punkt.warnung { background: var(--achtung); }
.punkt.gefahr { background: var(--fehler); }
.strich { flex: 0 0 1.2rem; height: 2px; background: var(--linie_stark);
          margin-top: .6rem; }
@media (max-width: 767px) {
  .karten3 { grid-template-columns: minmax(0, 1fr); }
  .kette { flex-direction: column; }
  .strich { display: none; }
}
/* --- Kontaktliste (Schritt 5): Stufe-Chip, Score-Pille, Segment ------ */
.stufe { display: inline-block; padding: .1rem .55rem; border-radius: 999px;
         border: 1px solid var(--linie_stark); font-size: .8rem;
         font-weight: 600; white-space: nowrap; }
.stufe.termin { color: var(--gut_text); border-color: var(--gut_text); }
.stufe.geantwortet { color: var(--info); border-color: var(--info); }
.stufe.gewonnen { background: var(--gut); color: var(--gut_auf);
                  border-color: var(--gut); }
.score { display: inline-block; min-width: 2.4rem; text-align: center;
         padding: .1rem .5rem; border-radius: 999px;
         font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
         monospace; font-variant-numeric: tabular-nums; font-size: .82rem;
         background: var(--kopfzeile); color: var(--schrift); }
.score.hoch { background: var(--gut); color: var(--gut_auf);
              font-weight: 700; }
.score.mittel { background: var(--achtung); color: var(--achtung_auf);
                font-weight: 700; }
.score.leer { color: var(--gedaempft); }
.segment { display: inline-flex; flex-wrap: wrap; border: 1px solid
           var(--linie_stark); border-radius: 6px; overflow: hidden; }
.segment form { margin: 0; }
.segment button, .segment .an { display: inline-flex; align-items: center;
                                min-height: 36px; padding: 0 .6rem;
                                font-size: .82rem; border: 0;
                                border-right: 1px solid var(--linie_stark);
                                background: transparent;
                                color: var(--gedaempft); cursor: pointer; }
.segment > :last-child button, .segment > .an:last-child {
  border-right: 0; }
.segment .an { background: var(--schrift); color: var(--grund);
               font-weight: 700; cursor: default; }
/* --- Freigaben in vier Blöcken mit Verlauf je Art (Schritt 3) ------ */
.block { margin-top: 1.4rem; padding-top: .2rem; }
.block > h2 { display: flex; align-items: center; gap: .5rem;
              border-bottom: 2px solid var(--linie); padding-bottom: .4rem;
              margin-top: .6rem; }
.block > h2 .zaehler { margin-left: 0; }
.verlauftitel { display: flex; align-items: center; gap: .6rem;
                font-size: .72rem; letter-spacing: .08em;
                text-transform: uppercase; color: var(--gedaempft);
                margin: 1.1rem 0 .2rem; }
.verlauftitel a { text-transform: none; letter-spacing: 0;
                  margin-left: auto; font-size: .85rem; }
.eintrag { display: grid; grid-template-columns: 8.6rem minmax(0, 1fr) auto;
           gap: .6rem; align-items: center; padding: .35rem 0;
           border-top: 1px solid var(--linie); font-size: .92rem; }
.eintrag .wann { color: var(--gedaempft); font-family: ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace;
                 font-variant-numeric: tabular-nums; }
.eintrag .was { overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; }
.eintrag .badge { margin: 0; }
@media (max-width: 767px) {
  .eintrag { grid-template-columns: minmax(0, 1fr); }
  .eintrag .was { white-space: normal; }
}

.fehler { color: var(--fehler); white-space: pre-wrap; }
.hinweis { background: var(--hinweis_flaeche);
           border: 1px solid var(--hinweis_linie);
           color: var(--hinweis_schrift); padding: .5rem .8rem;
           border-radius: 6px; }
.hinweis a { color: inherit; }
.warnung { background: var(--fehler_flaeche);
           border: 1px solid var(--fehler_linie); color: var(--fehler_schrift);
           padding: .5rem .8rem; border-radius: 6px; margin: .5rem 0; }
.warnung a { color: inherit; }

/* --- Aktionen: 44px hoch, und mit Abstand zueinander --------------------- */
.aktionen { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: .9rem; }
form.aktion { display: flex; flex-wrap: wrap; align-items: center;
              gap: .5rem; margin: 0; }
label.haken { display: flex; align-items: center; gap: .5rem;
              min-height: 44px; font-size: .95rem; }
label.haken input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
label.feld { display: block; margin: .8rem 0; font-weight: 600; }
label.feld input { display: block; margin-top: .35rem; max-width: 36rem; }
/* Nummerierte Schritte (Kalender verbinden): Luft zwischen den Schritten,
   damit jeder als eigene Aufgabe lesbar bleibt. */
ol.schritte { padding-left: 1.4rem; }
ol.schritte > li { margin: .9rem 0; }
/* Ein alleinstehender Verweis („Abbrechen, nichts tun", „auch archivierte
   zeigen") ist auf dem Telefon genauso ein Ziel für einen Daumen wie ein
   Knopf — als Textzeile von 16px Höhe ist er keines. */
p.abbrechen a, p.meta > a { display: inline-block; min-height: 44px;
                            padding: .6rem .1rem; }
button, input, select, textarea { font-family: inherit; }
/* Vorschau in der Medienliste. Feste Höhe statt fester Breite: die Zeile
   soll gleich hoch bleiben, egal ob Hoch- oder Querformat. */
/* Nur Bild und Video: der Rahmen des Marketing-Pults heißt auch .vorschau
   und wurde von dieser Regel auf 140 px gedrückt (29.09.2026). */
img.vorschau, video.vorschau { max-width: 100%; max-height: 140px; height: auto;
            border-radius: 6px; display: block; background: var(--grund); }
video.vorschau { width: 240px; max-width: 100%; }
audio { width: 100%; max-width: 240px; }
/* Aufklappbare Freigabe-Karten (25.08.2026). `<details>` statt JavaScript:
   der Betreiber öffnet mehrere Entwürfe nebeneinander, vergleicht und
   entscheidet, ohne die Liste zu verlassen. Der Pfeil bleibt der native —
   er ist die einzige Anzeige, die auch ohne CSS noch stimmt. */
details.karte > summary { cursor: pointer; padding: .3rem 0;
                          min-height: 44px; display: flex;
                          align-items: center; gap: .4rem;
                          flex-wrap: wrap; }
details.karte > summary::marker { color: var(--gedaempft); }
details.karte[open] > summary { margin-bottom: .6rem;
                                border-bottom: 1px solid var(--linie);
                                padding-bottom: .5rem; }
details.karte > summary .meta { font-weight: 400; }
/* Das Bearbeitungsfeld liegt hinter einer zweiten Klappe, damit es die
   Entscheidungsknöpfe nicht verdrängt: wer nur freigeben will, soll
   nicht an einem Textfeld vorbeiscrollen müssen. */
details.bearbeiten > summary { cursor: pointer; min-height: 44px;
                               display: flex; align-items: center;
                               font-size: .95rem; color: var(--gedaempft); }
textarea { width: 100%; box-sizing: border-box; padding: .6rem;
           border: 1px solid var(--linie_stark); border-radius: 6px;
           background: var(--flaeche); color: var(--schrift);
           font-size: 1rem; line-height: 1.45; resize: vertical;
           font-weight: 400; }
button { min-height: 44px; padding: .6rem 1.1rem; border-radius: 6px;
         border: 1px solid var(--linie_stark); background: var(--flaeche);
         color: var(--schrift); cursor: pointer; font-weight: 600;
         font-size: 1rem; }
button.primaer { background: var(--gut); border-color: var(--gut);
                 color: var(--gut_auf); }
button.gefahr { background: var(--flaeche); border-color: var(--fehler);
                color: var(--fehler); border-width: 2px; }
/* 16px ist die Schwelle: darunter zoomt iOS beim Fokussieren von selbst in
   das Feld hinein und lässt die Seite verschoben zurück. */
select, input[type="text"], input[type="tel"], input[type="email"] {
  min-height: 44px; padding: .5rem .6rem; border-radius: 6px;
  border: 1px solid var(--linie_stark); background: var(--flaeche);
  color: var(--schrift); font-size: 16px; width: 100%; max-width: 22rem; }

/* --- Tabellen ------------------------------------------------------------
   Auf dem Desktop bleibt es eine Tabelle; der Kasten drumherum scrollt
   notfalls für sich, damit nie die SEITE waagerecht scrollt. */
.tabelle { overflow-x: auto; margin: .7rem 0; }
table { border-collapse: collapse; width: 100%; background: var(--flaeche); }
th, td { border: 1px solid var(--linie); padding: .5rem .6rem;
         text-align: left; font-size: .9rem; vertical-align: top; }
thead th { background: var(--kopfzeile); }

/* --- Schmale Schirme ----------------------------------------------------- */
@media (max-width: 640px) {
  main { padding: .8rem .7rem 4rem; }
  .karte { padding: .7rem .8rem; }
  /* Jede Zeile wird zu einer Karte, jede Zelle zu einer beschrifteten
     Angabe. Vier Spalten nebeneinander sind auf 375px Breite kein Tisch
     mehr, sondern ein Rest. */
  .tabelle { overflow-x: visible; }
  .tabelle thead { display: none; }
  .tabelle table, .tabelle tbody, .tabelle tr, .tabelle th, .tabelle td {
    display: block; width: auto; }
  .tabelle table { border: 0; background: transparent; }
  .tabelle tr { background: var(--flaeche); border: 1px solid var(--linie);
                border-radius: 6px; margin: 0 0 .7rem; overflow: hidden; }
  .tabelle th, .tabelle td { border: 0;
                             border-bottom: 1px solid var(--linie);
                             padding: .55rem .8rem; font-size: .95rem; }
  .tabelle tr > *:last-child { border-bottom: 0; }
  /* Die Spaltenüberschrift wandert vor die Zelle. `data-label` setzt
     ausschließlich `_tabelle()`, und zwar aus eigenem Text. */
  .tabelle td[data-label]::before {
    content: attr(data-label); display: block; font-weight: 700;
    font-size: .72rem; letter-spacing: .04em; text-transform: uppercase;
    color: var(--gedaempft); margin-bottom: .15rem; }
  /* Aktionen untereinander und über die volle Breite: ein Daumen trifft
     einen Streifen, keinen Punkt. */
  .aktionen { flex-direction: column; align-items: stretch; }
  .aktionen form.aktion { width: 100%; }
  .aktionen form.aktion > button, .aktionen > button { width: 100%; }
  .aktionen form.aktion > select, .aktionen form.aktion > input[type="text"] {
    max-width: none; }
  /* Der gefährliche Knopf rückt zusätzlich ab — „Ablehnen" darf nicht
     dort liegen, wo der Daumen nach „Freigeben" noch nachwippt. */
  .aktionen form.aktion.gefahr { margin-top: .8rem; }
  select, input[type="text"], input[type="tel"], input[type="email"] {
    max-width: none; }
}
"""

# Vier Gruppen statt zehn gleichrangiger Reiter (Betreiber-Entscheid
# 02.09.2026 nach dem Design-Durchgang, docs/superpowers/plans/
# 2026-09-02-ui-gruppen-und-heute.md). Reihenfolge ist Teil des Entwurfs.
_GRUPPEN = (
    ("Aufgaben", (("/", "Heute"), ("/freigaben", "Freigaben"),
                  ("/wiedervorlagen", "Wiedervorlagen"),
                  ("/einordnung", "Einordnung"),
                  ("/kalender", "Kalender"),
                  # Task 5 (12.09.2026): die Seite, ueber die ein Kollege
                  # seinen Kalender verbindet — nicht nur per Direktlink
                  # erreichbar, auch aus dem Menue (fuer den Betreiber, der
                  # Kollegen einrichtet, wie fuer die Rolle `kalender`
                  # selbst — s. _pfad_erlaubt/_seitenleiste).
                  ("/team/kalender", "Kalender verbinden"))),
    ("Analyse", (("/kontakte", "Kontakte"), ("/pipeline", "Pipeline"),
                 ("/ergebnisse", "Ergebnisse"),
                 ("/posteingang", "Posteingang"))),
    ("Daten", (("/medien", "Medien"),)),
    ("Monitoring", (("/whatsapp", "WhatsApp"),)),
    # Marketing-Pult (29.09.2026): wie Admin nur fuer freigeben im
    # Basis-Laden (_ADMIN_BASIS_PFADE). /marketing/layouts kommt mit Task 5.
    ("Marketing", (("/marketing", "Übersicht"),
                   ("/marketing/entwuerfe", "Entwürfe"),
                   ("/marketing/layouts", "Layouts"))),
    # Existiert im Menue NUR fuer Rolle freigeben im Basis-Laden — nicht
    # wegen einer Extra-Pruefung hier, sondern weil _seitenleiste JEDEN
    # Eintrag durch _pfad_erlaubt filtert (s. dort), und die faellt fuer
    # jede andere Kombination durch.
    ("Admin", (("/team/laden-anlegen", "Laden anlegen"),
               ("/team/tailscale-einladen", "Team-Mitglied einladen"))),
)
_NAV = tuple(eintrag for _, eintraege in _GRUPPEN for eintrag in eintraege)
# Detailseiten gehoeren zu ihrer Liste (Browser-Durchlauf 29.09.2026): die
# Pfade /marketing/entwurf/<id> und /marketing/layout/<name> liegen NICHT
# unter /marketing/entwuerfe bzw. /marketing/layouts, sondern nur unter
# /marketing - ohne diese Zuordnung leuchtete dort "Übersicht" statt der
# Liste, aus der man gekommen ist. Schluessel: Vorsilbe des Detailpfads.
_DETAIL_ZU_LISTE = {
    "/marketing/entwurf": "/marketing/entwuerfe",
    "/marketing/layout": "/marketing/layouts",
    "/marketing/layout-bild": "/marketing/layouts",
}


def _aktiver_eintrag(aktiv: str, pfade) -> str | None:
    """Der EINE aktive Menuepfad: der laengste, der gleich dem aktuellen ist
    oder dessen Vorsilbe (bis zu einem /). Vorher war jeder passende Eintrag
    aktiv - auf /marketing/entwuerfe also auch "Übersicht" (/marketing)."""
    for detail, liste in _DETAIL_ZU_LISTE.items():
        if aktiv == detail or aktiv.startswith(detail + "/"):
            aktiv = liste
            break
    passend = [p for p in pfade
               if p == aktiv or (p != "/" and aktiv.startswith(p + "/"))]
    return max(passend, key=len) if passend else None
# Welche Seite gerade gebaut wird — gesetzt von _gesichert_seite, gelesen
# von der Seitenleiste fuer den aktiven Menuepunkt. Ein ContextVar statt
# eines Parameters an jeder der ~30 _seite()-Stellen.
_AKTIVER_PFAD = contextvars.ContextVar("aktiver_pfad", default="")
# Task 5 (12.09.2026): wer gerade angemeldet ist — dieselbe ContextVar-
# Technik wie oben, gesetzt von _gesichert_seite. Die Seitenleiste blendet
# fuer die schmale Rolle `kalender` jeden Menuepunkt aus, den sie ohnehin
# nicht betreten darf (_pfad_erlaubt): sonst zeigte das Menue Verweise auf
# Kontakte/Freigaben/Posteingang, die alle in einem 403 enden — die Rolle
# soll schmal AUSSEHEN, nicht nur schmal SEIN.
_AKTIVE_ROLLE = contextvars.ContextVar("aktive_rolle", default="")
# Pfade, deren Zaehler "offen" bedeutet (Achtung-Farbe, wenn > 0).
_ZAEHLER_OFFEN = ("/", "/freigaben", "/wiedervorlagen", "/einordnung")


def _zaehler_abfragen() -> dict:
    """Die Zahlen am Menue — aus DENSELBEN Quellen wie die Seiten selbst,
    damit Menue und Seite nie zwei verschiedene Wahrheiten zeigen."""
    koerbe = server._einzuordnende(text_max=EINORDNUNG_TEXT_MAX)
    offen = {
        "/freigaben": server._q("select count(*) n from drafts "
                                "where status = 'pending'")[0]["n"],
        "/wiedervorlagen": len(_offene_wiedervorlagen()),
        "/einordnung": len(koerbe["neu"]) + len(koerbe["bereits_gefragt"]),
    }
    return {
        # „Heute" zaehlt, was eine Entscheidung braucht — die Summe der
        # drei Aufgaben-Zaehler, damit Menue und Startseite dasselbe sagen.
        "/": sum(offen.values()),
        **offen,
        "/kontakte": server._q(
            "select count(*) n from leads l where not "
            + server._archiv_sql("l.enrichment"))[0]["n"],
        "/posteingang": json.loads(server.posteingang())
        ["anzahl_unbeantwortet"],
        "/medien": len(server.medien.liste()),
    }


def _zaehler() -> dict:
    """Scheitert eine Zaehlabfrage, fehlt der Zaehler — nicht die Seite.
    Die Seite ist die Diagnose; ein Menue, das sie mitreisst, waere
    genau dann weg, wenn man es braucht."""
    try:
        return _zaehler_abfragen()
    except Exception:
        LOG.warning("Menue-Zaehler nicht lesbar", exc_info=True)
        return {}


def _seitenleiste(abmelden: str) -> str:
    aktiv = _AKTIVER_PFAD.get()
    zaehler = _zaehler()
    # Task 5: fuer die schmale Rolle `kalender` bleibt vom Menue nur, was
    # `_pfad_erlaubt` auch betreten darf — sonst wuerde die Seitenleiste
    # Verweise auf Kontakte/Freigaben/Posteingang zeigen, die alle in einem
    # 403 enden. Fuer jede andere Rolle (leer/`lesen`/`freigeben`) liefert
    # `_pfad_erlaubt` immer True, die Liste bleibt also unveraendert.
    rolle = _AKTIVE_ROLLE.get()
    gruppen = tuple(
        (gruppe, tuple(e for e in eintraege if _pfad_erlaubt(rolle, e[0])))
        for gruppe, eintraege in _GRUPPEN)
    gruppen = tuple(g for g in gruppen if g[1])
    teile = ['<nav class="seite"><div class="marke">'
             '<span class="logo">S</span><span>sales-claw</span></div>']
    # Die Gruppe der aktiven Seite: am Handy die einzige, die oben als
    # Zeile bleibt (Schritt 7); ohne Treffer die erste (Aufgaben).
    aktiver_pfad = _aktiver_eintrag(
        aktiv, [pfad for _, eintraege in gruppen for pfad, _ in eintraege])
    gruppe_aktiv = gruppen[0][0]
    for gruppe, eintraege in gruppen:
        if any(pfad == aktiver_pfad for pfad, _ in eintraege):
            gruppe_aktiv = gruppe
    for gruppe, eintraege in gruppen:
        marke = " aktiv-gruppe" if gruppe == gruppe_aktiv else ""
        teile.append(f'<div class="gruppe{marke}"><div class="gruppenname">'
                     f'{_e(gruppe)}</div>')
        for pfad, name in eintraege:
            ist_aktiv = pfad == aktiver_pfad
            klasse = ' class="aktiv"' if ist_aktiv else ""
            zahl = ""
            if pfad in zaehler:
                n = int(zaehler[pfad])
                art = " offen" if (pfad in _ZAEHLER_OFFEN and n > 0) else ""
                zahl = f'<span class="zaehler{art}">{n}</span>'
            teile.append(f'<a{klasse} href="{pfad}"><span>{_e(name)}</span>'
                         f'{zahl}</a>')
        teile.append("</div>")
    teile.append(abmelden)
    teile.append("</nav>")
    # Vier-Tab-Leiste (Schritt 7): immer im HTML, am Desktop per CSS
    # verborgen, am Handy fest am unteren Rand. Jeder Tab fuehrt auf die
    # erste Seite seiner Gruppe; der Aufgaben-Tab traegt den Heute-Zaehler.
    teile.append('<nav class="tabs">')
    for gruppe, eintraege in gruppen:
        pfad = eintraege[0][0]
        klasse = "tab aktiv" if gruppe == gruppe_aktiv else "tab"
        zahl = ""
        if pfad == "/" and int(zaehler.get("/", 0) or 0) > 0:
            zahl = f'<span class="zaehler offen">{int(zaehler["/"])}</span>'
        teile.append(f'<a class="{klasse}" href="{pfad}"><span>{_e(gruppe)}'
                     f'</span>{zahl}</a>')
    teile.append("</nav>")
    return "".join(teile)

# --- WhatsApp-Zustand (29.08.2026) ------------------------------------------
# Gelesen wird mit einem VIEWER-Schluessel: er darf GET, aber kein send-text
# (gemessen: 403). Damit kann diese Seite den Zustand zeigen, ohne dass das
# Freigabe-Gate durch einen zweiten Sendeweg umgangen werden koennte.
OPENWA_URL = os.environ.get("OPENWA_URL", "").rstrip("/")
OPENWA_VIEWER_KEY = os.environ.get("OPENWA_VIEWER_KEY", "")
OPENWA_SESSION_ID = os.environ.get("OPENWA_SESSION_ID", "")
OPENWA_DASHBOARD_URL = os.environ.get("OPENWA_DASHBOARD_URL",
                                      "http://127.0.0.1:12785")
OPENWA_TIMEOUT_S = 8

# Was der Zustand bedeutet — in der Sprache des Betreibers, nicht in der
# des Systems. `ready` heisst NICHT "alles gut", sondern genau das, was
# hier steht.
WA_ZUSTAND = {
    "ready": ("verbunden", "gut",
              "Nachrichten kommen an und gehen raus."),
    "qr_ready": ("wartet auf Kopplung", "warnung",
                 "Die Anmeldung fehlt — nichts kommt an, nichts geht raus. "
                 "Neu koppeln in der OpenWA-Oberfläche (Verweis unten)."),
    "failed": ("gescheitert", "gefahr",
               "Die Sitzung ist abgestürzt. In der OpenWA-Oberfläche "
               "stoppen und neu starten; danach ggf. neu koppeln."),
    "stopped": ("gestoppt", "warnung",
                "Die Sitzung läuft nicht. In der OpenWA-Oberfläche starten."),
    "starting": ("startet", "", "Einen Moment — die Sitzung fährt hoch."),
}


def _seite(titel: str, rumpf: str, status: int = 200,
           refresh: int | None = None) -> HTMLResponse:
    auffrischen = (f'<meta http-equiv="refresh" content="{int(refresh)}">'
                   if refresh else "")
    # Abmelden nur bei scharfer Anmeldung — vorher gaebe es nichts zu
    # beenden, und der Knopf waere eine Luege.
    abmelden = ""
    if UI_SESSION_SECRET:
        abmelden = (f'<form method="post" action="/logout" class="abmelden">'
                    f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
                    f'<button type="submit">Abmelden</button></form>')
    nav = _seitenleiste(abmelden)
    return HTMLResponse(
        f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
        # Ohne diese Zeile legt Safari eine 980px breite Desktop-Leinwand an
        # und zoomt sie auf die Geraetebreite herunter: die Seite ist dann
        # vollstaendig da und vollstaendig unlesbar, und keine Media-Query
        # greift, weil der Browser sich fuer breit haelt.
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        # Sagt dem Browser, dass die Seite BEIDE Themen bedient — sonst malt
        # er Formularfelder und Bildlaufleisten im dunklen Modus weiterhin
        # hell in die dunkle Seite.
        f'<meta name="color-scheme" content="light dark">'
        f"{auffrischen}<title>{_e(titel)} — sales-ui</title>"
        f"<style>{_STIL}</style></head><body>"
        f'<div class="rahmen">{nav}<main><h1>{_e(titel)}</h1>{rumpf}'
        f"</main></div>"
        f"</body></html>", status_code=status)


def _fehlerseite(status: int, titel: str, text: str) -> HTMLResponse:
    return _seite(titel, f'<p class="fehler">{text}</p>'
                         f'<p class="abbrechen"><a href="/freigaben">Zurück zur '
                         f'Freigabe-Inbox</a></p>',
                  status=status)


# Ein Buchstabe als SVG statt einer .ico-Datei: kein zusaetzlicher
# Mount, keine CSP-Lockerung, und das 404 bei jedem Seitenaufruf ist weg.
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#1f7a4d"/>'
    '<text x="16" y="23" font-size="20" font-family="sans-serif" '
    'font-weight="700" fill="#ffffff" text-anchor="middle">S</text></svg>')


async def favicon(request):
    return Response(_FAVICON, media_type="image/svg+xml",
                    headers={"cache-control": "public, max-age=86400"})


def _badge(kanal) -> str:
    return f'<span class="badge {_e(kanal)}">{_e(kanal)}</span>'


def _nachricht_inhalt(text, typ) -> str:
    """Eine eingegangene Nachricht als Zeile. Sprach- und Bildnachrichten
    haben keinen Text — die Seite zeigte dann eine leere Zeile, als waere
    nichts angekommen (Browser-Durchgang 29.08.2026, Kontakt „Stephane
    B."). Der Nachrichtentyp steht ohnehin im Eintrag; er gehoert hierhin.
    Gemeinsam fuer Posteingang und die Nachrichtenliste der Einordnung."""
    text = (text or "").strip()
    if text:
        return f'<div class="text">{_text_html(text)}</div>'
    # 'voice' ist die Schreibweise, die OpenWA tatsaechlich schickt
    # (gemessen 01.09.2026: 16 Stueck in 30 Tagen); 'ptt' stand hier aus
    # der WhatsApp-Web-Zeit und traf keine einzige Nachricht.
    benennung = {"voice": "Sprachnachricht", "ptt": "Sprachnachricht",
                 "audio": "Tonaufnahme",
                 "image": "Bild", "video": "Video",
                 "document": "Dokument", "sticker": "Sticker",
                 "location": "Standort"}.get(str(typ or "").lower(),
                                             "ohne Text")
    return (f'<div class="meta">[{_e(benennung)} — kein '
            f'Text zum Mitlesen]</div>')


# Der Entwurfszustand als WORT. Auf dem Handy scrollt die Ueberschrift des
# Blocks („Fehlgeschlagen") aus dem Bild, waehrend die Karten weiterlaufen —
# dann bliebe nur die Farbe des Knopfes, und Farbe allein traegt eine
# Unterscheidung nicht (Sehschwaeche, Sonnenlicht, kleines Abzeichen).
ZUSTAND_TITEL = {"pending": "zu prüfen", "failed": "fehlgeschlagen",
                 "approved": "freigegeben", "sent": "gesendet",
                 "rejected": "abgelehnt"}
# Termin-Verlauf (Schritt 3): Aktivitaetstyp -> Wort. Getrennt von den
# Entwurfszustaenden, weil test_ui jeden Entwurfszustand auf der Seite
# erwartet — Termine sind keine Entwuerfe.
TERMIN_TITEL = {"termin": "bestätigt", "termin_verschoben": "verschoben",
                "termin_abgesagt": "abgesagt"}

# Aufgabe 6 (11.09.2026): der Stand einer Kalenderantwort. `status` kommt
# roh aus der Kalenderantwort (kalender.ics_antwort_lesen ueber
# postfach._antwort_festhalten) und bleibt in der Datenbank UNVERAENDERT —
# ACCEPTED/DECLINED/TENTATIVE/NEEDS-ACTION sind iCal-Vokabular (RFC 5545
# PARTSTAT), kein Text fuer den Betreiber. Uebersetzt wird nur beim
# Rendern, nach demselben Muster wie ZUSTAND_TITEL/TERMIN_TITEL oben.
# NEEDS-ACTION kommt in der Praxis kaum vor (eine gelesene Antwort HAT
# einen Status), steht aber der Vollstaendigkeit halber hier — ein
# unbekannter/leerer Wert faellt in `_verlauf_einladung_antwort` auf den
# rohen Text zurueck statt auf einen erfundenen Ersatzwert.
EINLADUNG_TEXT = {
    "ACCEPTED": "zugesagt",
    "DECLINED": "abgesagt",
    "TENTATIVE": "unter Vorbehalt",
    "NEEDS-ACTION": "wartet auf Antwort",
}


def _zustand_badge(zustand: str) -> str:
    """`zustand` ist IMMER ein Literal aus dieser Datei, nie eine DB-Spalte —
    es steht in einem class-Attribut, und dort haben Fremddaten nichts zu
    suchen. `_e` laeuft trotzdem drueber, damit die Regel auch dann haelt,
    wenn hier spaeter jemand eine Spalte durchreicht."""
    return (f'<span class="badge zustand {_e(zustand)}">'
            f'{_e(ZUSTAND_TITEL.get(zustand) or TERMIN_TITEL.get(zustand, zustand))}'
            f'</span>')


def _tabelle(spalten, zeilen) -> str:
    """Die EINE Tabellenform dieser Oberflaeche — breit auf dem Desktop,
    gestapelte Karten auf dem Handy (Media-Query in `_STIL`).

    `spalten` sind die Ueberschriften und stammen ausnahmslos aus dem Code
    dieser Datei; sie landen zusaetzlich als `data-label` an jeder Zelle,
    woraus die Media-Query die Beschriftung baut. Genau deshalb duerfen dort
    NIE Fremddaten hinein: ein Kontaktname im Attributkontext waere die Kante,
    gegen die `html.escape(quote=True)` sonst ueberall steht. `_e` laeuft
    trotzdem ueber jedes Label — eine Zusage, die man pruefen kann, ist mehr
    wert als eine, die man einhalten muss.

    `zeilen` sind Listen FERTIGER Zellinhalte: escaped wird dort, wo die
    Zelle entsteht (mal ist es blosser Text, mal ein Verweis mit escaptem
    Namen darin), nicht hier — sonst waere das zweite Escapen sichtbar.
    """
    kopf = "".join(f"<th>{_e(s)}</th>" for s in spalten)
    leib = []
    for zeile in zeilen:
        zellen = "".join(
            f'<td data-label="{_e(spalten[i]) if i < len(spalten) else ""}">'
            f"{inhalt}</td>" for i, inhalt in enumerate(zeile))
        leib.append(f"<tr>{zellen}</tr>")
    return (f'<div class="tabelle"><table><thead><tr>{kopf}</tr></thead>'
            f"<tbody>{''.join(leib)}</tbody></table></div>")


def _paar_tabelle(paare) -> str:
    """Die zweite Form: Merkmal und Wert, ein Paar je Zeile (Stammdaten).

    Sie braucht kein `data-label` — die Beschriftung steht schon als `th` in
    der Zeile und wird auf schmalen Schirmen von derselben Media-Query zur
    Zeile ueber dem Wert.
    """
    zeilen = "".join(f"<tr><th>{_e(name)}</th><td>{wert}</td></tr>"
                     for name, wert in paare)
    return f'<div class="tabelle"><table><tbody>{zeilen}</tbody></table></div>'


# ---------------------------------------------------------------------------
# Freigabe-Inbox (/)
# ---------------------------------------------------------------------------

def _text_stand(text: str) -> str:
    """Fingerabdruck des Textes, den der Betreiber GELESEN hat.

    Gemessen am 29.08.2026: eine vor einer Ueberarbeitung geladene
    Freigaben-Seite zeigte den alten Text, der Knopf schickte nur die ID —
    freigegeben wurde etwas anderes als gelesen. Der Stand bindet die
    Freigabe an den angezeigten Wortlaut."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _formular(aktion: str, draft_id, knopf: str, klasse: str = "",
              checkbox: str | None = None, stand: str | None = None) -> str:
    """Die Knopfklasse steht ZUSAETZLICH am Formular: die Media-Query rueckt
    den gefaehrlichen Knopf auf schmalen Schirmen ab, und das geht nur ueber
    das Element, das die ganze Aktion umschliesst."""
    haken = (f'<label class="haken">'
             f'<input type="checkbox" name="bestaetigt" value="ja"> '
             f'{checkbox}</label>' if checkbox else "")
    stand_feld = (f'<input type="hidden" name="stand" value="{_e(stand)}">'
                  if stand is not None else "")
    return (f'<form class="aktion {klasse}" method="post" '
            f'action="/aktion/{aktion}">'
            f'<input type="hidden" name="draft_id" value="{_e(draft_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'{stand_feld}{haken}<button class="{klasse}">{knopf}</button>'
            f'</form>')


def _entwurf_kopf(z, zustand: str) -> str:
    anhang = (f' · Anhang: <b>{_e(z["media_ref"])}</b>'
              if z.get("media_ref") else "")
    alter = (f' · Alter: {float(z["alter_h"]):.1f} h'
             if z.get("alter_h") is not None else "")
    betreff = (f'<div>Betreff: <b>{_e(z["subject"])}</b></div>'
               if z.get("subject") else "")
    betreff += (f'<div>CC: <b>{_e(z["cc"])}</b></div>'
                if z.get("cc") else "")
    return (f'{_zustand_badge(zustand)}{_badge(z["channel"])}'
            f'<b>{_e(z["name"] or "(ohne Kontakt)")}'
            f"</b> &rarr; {_e(z['recipient'])}{betreff}"
            f'<div class="meta">consent: {_e(z.get("consent_status"))}'
            f"{anhang}{alter} · draft_id: {_e(z['id'])}</div>")


ENTWURF_VORSCHAU = 90


def _entwurf_karte_offen(z) -> str:
    """Eine Freigabe-Karte zum Aufklappen — mit Bearbeitungsfeld.

    `<details>` statt eigener Seite und statt JavaScript: der Betreiber
    kann mehrere Entwuerfe nebeneinander oeffnen, vergleichen und
    entscheiden, ohne die Liste zu verlassen. Vor- und Zurueckspringen war
    genau das, was ihn gestoert hat.

    Zugeklappt steht so viel, dass man ohne Oeffnen erkennt, worum es geht
    — Kontakt, Kanal, Anfang des Textes. Nicht mehr: die Vorschau steht in
    einer Zeile, und ein ganzer Entwurf darin machte die Liste unlesbar.

    Der Text ist Modelltext an einen Menschen und wird ueberall escaped,
    auch in der Vorschau und im Textfeld.
    """
    text = z["body"] or ""
    text_normalisiert = " ".join(text.split())
    vorschau = _kurz(text_normalisiert, ENTWURF_VORSCHAU)
    return (
        f'<details class="karte">'
        f'<summary>{_badge(z["channel"])}'
        f'<b>{_e(z["name"] or "(ohne Kontakt)")}</b>'
        f'<span class="meta" title="{_e(text_normalisiert)}"> — {_e(vorschau)}'
        f'</span></summary>'
        f'{_entwurf_kopf(z, "pending")}'
        f'<div class="text">{_text_html(text)}</div>'
        f'{_entwurf_bearbeiten_form(z, text)}'
        f'<div class="aktionen">'
        f'{_formular("freigeben", z["id"], "Freigeben", "primaer", stand=_text_stand(text))}'
        f'{_formular("ablehnen", z["id"], "Ablehnen", "gefahr")}'
        f'</div></details>')


# Textfeld-Grenzen je Kanal: WhatsApp 4096 (Kanalgrenze), LinkedIn die
# gemessene Post-Grenze, E-Mail grosszuegig — der Server prueft ohnehin.
TEXTFELD_MAX = {"whatsapp": 4096, "linkedin": server.POST_MAXLAENGE,
                "email": 20000}
BETREFF_MAX = 200
CC_FELD_MAX = 300


def _entwurf_bearbeiten_form(z, text: str) -> str:
    """Das Textfeld — nur bei `pending`, denn nur dort darf geaendert werden.

    Eigenes `<details>`, damit es die Entscheidungsknoepfe nicht
    verdraengt: wer nur freigeben will, soll nicht an einem Textfeld
    vorbeiscrollen muessen.
    """
    # Grenze JE KANAL (03.09.2026): 4096 war die WhatsApp-Grenze fuer alle —
    # eine 5.537 Zeichen lange E-Mail liess sich damit weder aendern noch
    # absenden (der Browser sperrt ein zu langes Feld). E-Mails bekommen
    # ausserdem ihren Betreff zum Bearbeiten; das Feld waechst mit dem Text.
    kanal = str(z.get("channel") or "")
    grenze = TEXTFELD_MAX.get(kanal, TEXTFELD_MAX["whatsapp"])
    zeilen = min(30, max(10, text.count("\n") + 2, len(text) // 90 + 1))
    betreff_feld = (
        f'<p><label class="feld">Betreff<br>'
        f'<input type="text" name="betreff" value="{_e(z.get("subject") or "")}" '
        f'maxlength="{BETREFF_MAX}"></label></p>'
        f'<p><label class="feld">CC (kommagetrennt, leer = keins)<br>'
        f'<input type="text" name="cc" value="{_e(z.get("cc") or "")}" '
        f'maxlength="{CC_FELD_MAX}"></label></p>'
        if kanal == "email" else "")
    return (
        f'<details class="bearbeiten"><summary>Text bearbeiten</summary>'
        f'<form method="post" action="/aktion/bearbeiten">'
        f'<input type="hidden" name="draft_id" value="{_e(z["id"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'{betreff_feld}'
        f'<p><label class="feld">Text<br>'
        f'<textarea name="text" rows="{zeilen}" maxlength="{grenze}">'
        f'{_e(text)}</textarea></label></p>'
        f'<div class="aktionen">'
        f'<button class="primaer">Änderung speichern</button></div>'
        f'</form>'
        f'<p class="meta">Ändert nur den Entwurf — es geht nichts raus, und '
        f'die Freigabe bleibt ein eigener Schritt. Alter und neuer Text '
        f'werden protokolliert.</p></details>')


# ---------------------------------------------------------------------------
# Medien (Betreiber-Wunsch 25.08.2026): Unterlagen hochladen statt kopieren
#
# HIER AENDERT SICH EIN GRUNDSATZ, und das gehoert benannt. `media/` ist an
# sales-mcp und sales-dispatch als `:ro` gebunden, mit der Begruendung: „was
# versendet werden kann, legt ausschliesslich ein Mensch auf dem Host ab".
# Eine Upload-Seite macht daraus die EINZIGE Tuer, durch die Daten von aussen
# in den Versandvorrat kommen.
#
# Der Grundsatz bleibt trotzdem gewahrt, nur praeziser gefasst: es legt
# weiterhin ausschliesslich ein MENSCH etwas ab — nur nicht mehr ueber den
# Datei-Explorer, sondern ueber eine Seite, die hinter Host-Wache und
# CSRF-Marke liegt. Der Agent bekommt kein Schreibrecht: `sales-mcp` und
# `sales-dispatch` bleiben `:ro`, nur `sales-ui` darf schreiben.
#
# Geprueft wird gegen dieselbe Whitelist, dieselbe Groessengrenze und
# denselben Namensfilter wie beim Versand (medien.py) — es gibt keine zweite
# Wahrheit darueber, was eine zulaessige Unterlage ist.
# ---------------------------------------------------------------------------

MEDIEN_STUECK = 256 * 1024


# Nach Art gruppiert (01.09.2026, Betreiber-Wunsch): elf Dateien in einer
# flachen Liste — Videos, Unterlagen und Kalenderdateien durcheinander.
# Reihenfolge ist Absicht: was am haeufigsten versendet wird, steht oben.
_MEDIEN_ARTEN = (
    ("Dokumente", (".pdf",)),
    ("Videos", (".mp4",)),
    ("Bilder", (".jpg", ".jpeg", ".png")),
    ("Ton", (".mp3", ".ogg")),
    ("Termine", (".ics",)),
)


def _medien_art(name: str) -> str:
    endung = os.path.splitext(name)[1].lower()
    for art, endungen in _MEDIEN_ARTEN:
        if endung in endungen:
            return art
    return "Sonstige"


def _medien_tabelle():
    try:
        eintraege = server.medien.liste()
    except OSError as e:
        return (f'<p>Medienordner nicht lesbar ({_e(type(e).__name__)}) — '
                f'liegt der Ordner am Container an?</p>')
    if not eintraege:
        return "<p>Noch keine Unterlagen.</p>"
    # Schritt 4 (02.09.2026): Herkunft, Schalter „Bot darf senden" und der
    # letzte Versand je Datei — aus drafts, nicht aus einer eigenen Spalte.
    meta = server.medien_meta_lesen()
    zuletzt = {str(z["media_ref"]): z["wann"] for z in server._q(
        "select media_ref, max(sent_at) as wann from drafts "
        "where status = 'sent' and media_ref is not null "
        "group by media_ref")}
    gruppen = {}
    for name, groesse in eintraege:
        gruppen.setdefault(_medien_art(name), []).append((name, groesse))
    teile = []
    for art, _ in _MEDIEN_ARTEN + (("Sonstige", ()),):
        dateien = gruppen.get(art)
        if not dateien:
            continue
        teile.append(f"<h2>{_e(art)} ({len(dateien)})</h2>")
        teile.append(_tabelle(
            ["Datei", "Größe", "Herkunft", "Bot darf senden",
             "Zuletzt gesendet", "Ansicht", "Löschen"],
            [[_e(name), _e(_medien_groesse(groesse)),
              _e(server._medien_herkunft(name, meta.get(name))),
              _medien_schalter(name, meta.get(name)),
              _e(_zeit(zuletzt[name])) if name in zuletzt else "—",
              _medien_vorschau(name), _medien_loeschen_knopf(name)]
             for name, groesse in dateien]))
    return "".join(teile)


def _medien_schalter(name: str, m) -> str:
    """Das Wort traegt den Zustand (An/Aus), der Knopf die Gegenrichtung."""
    an = m is None or bool(m["bot_darf_senden"])
    ziel, knopf = ("nein", "Sperren") if an else ("ja", "Freigeben")
    return (f'<b>{"An" if an else "Aus"}</b> '
            f'<form class="aktion" method="post" action="/medien/bot">'
            f'<input type="hidden" name="name" value="{_e(name)}">'
            f'<input type="hidden" name="erlaubt" value="{ziel}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button>{knopf}</button></form>')


def _medien_groesse(bytes_: int) -> str:
    """MB fuer Videos, KB fuer alles Kleine — '0.00 MB' bei einer 1-KB-
    Kalenderdatei sagt nichts."""
    if bytes_ >= 1048576:
        return f"{bytes_ / 1048576:.2f} MB"
    return f"{bytes_ / 1024:.0f} KB"


def _medien_loeschen_knopf(name: str) -> str:
    return (f'<form class="aktion gefahr" method="post" '
            f'action="/medien/loeschen">'
            f'<input type="hidden" name="name" value="{_e(name)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button class="gefahr">Löschen</button></form>')


def _medien_formular(vorbelegt_ueberschreiben: bool = False) -> str:
    haken = ('<label class="haken"><input type="checkbox" '
             'name="ueberschreiben" value="ja"'
             + (" checked" if vorbelegt_ueberschreiben else "")
             + '> Vorhandene Datei gleichen Namens ersetzen</label>')
    erlaubt = ", ".join(sorted(server.medien.ERLAUBT))
    grenze = server.medien.MAX_BYTES // 1048576
    return (
        f'<h2>Hochladen</h2><div class="karte">'
        f'<form method="post" action="/medien/hochladen" '
        f'enctype="multipart/form-data">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<p><label class="feld">Datei<br>'
        f'<input type="file" name="datei" required></label></p>'
        f'{haken}'
        f'<div class="aktionen">'
        f'<button class="primaer">Hochladen</button></div></form>'
        f'<p class="meta">Erlaubt: {_e(erlaubt)}. Höchstens {grenze} MB. '
        f'Die Datei steht danach im Chat unter <code>medien_liste()</code> '
        f'und lässt sich an Entwürfe hängen. Sie geht dadurch an '
        f'niemanden — versendet wird erst mit einer Freigabe.</p></div>')


# Welche Endung wie gezeigt wird. PDFs und Kalenderdateien werden NICHT
# eingebettet, sondern verlinkt — ein PDF kann JavaScript enthalten, und ein
# `object-src` dafuer waere ein deutlich groesserer Schritt als ein Verweis.
MEDIEN_ANSICHT = {".jpg": "bild", ".jpeg": "bild", ".png": "bild",
                  ".mp4": "video", ".mp3": "ton", ".ogg": "ton"}


def _medien_vorschau(name: str) -> str:
    """Bild zeigen, Video/Ton abspielen, alles andere verlinken.

    `preload="none"` bei Video und Ton ist kein Detail: die Seite listet
    sieben Produktvideos zu je fuenf Megabyte, und ohne das laedt der
    Browser beim Oeffnen der Seite dreissig Megabyte, die niemand sehen
    wollte — auf dem Handy ueber Mobilfunk.
    """
    endung = os.path.splitext(name)[1].lower()
    quelle = "/medien/datei/" + urllib.parse.quote(name)
    art = MEDIEN_ANSICHT.get(endung)
    if art == "bild":
        return (f'<a href="{_e(quelle)}" target="_blank" rel="noreferrer">'
                f'<img src="{_e(quelle)}" alt="{_e(name)}" '
                f'class="vorschau"></a>')
    if art == "video":
        return (f'<video class="vorschau" controls preload="none" '
                f'src="{_e(quelle)}"></video>')
    if art == "ton":
        return (f'<audio controls preload="none" '
                f'src="{_e(quelle)}"></audio>')
    return (f'<a href="{_e(quelle)}" target="_blank" rel="noreferrer">'
            f'Öffnen</a>')


@_gesichert_seite
async def medien_datei(request):
    """Eine Unterlage ausliefern — zum Ansehen, nicht zum Ausfuehren.

    Der Name laeuft durch dieselbe Pruefung wie beim Versand
    (`medien.pruefe`): reiner Dateiname, zugelassene Endung, im Ordner
    vorhanden, kein Symlink nach draussen. Der MIME-Typ kommt aus der
    Whitelist und wird NIE aus dem Inhalt erraten — zusammen mit dem
    globalen `nosniff` schliesst das aus, dass eine Datei als etwas
    anderes interpretiert wird, als ihre Endung verspricht.
    """
    roh = request.path_params["name"]
    basis, fehler = server.medien.pruefe(roh)
    if fehler:
        return _fehlerseite(404, "Nicht gefunden", _e(fehler))
    _endpunkt, mimetyp = server.medien.endpunkt_und_typ(basis)
    try:
        inhalt = server.medien.lies(basis)
    except OSError as e:
        return _fehlerseite(404, "Nicht lesbar",
                            f"Datei nicht lesbar ({_e(type(e).__name__)}).")
    return Response(
        inhalt, media_type=mimetyp,
        headers={
            # Nur der Basisname, und der ist geprueft: keine Pfadangabe,
            # kein Zeilenumbruch, also keine Kopfzeilen-Injektion.
            "Content-Disposition": f'inline; filename="{basis}"',
            "Content-Security-Policy": _CSP_DATEI,
            # Nicht im Zwischenspeicher der Zwischenstationen: die Datei
            # kann Kundenunterlagen enthalten.
            "Cache-Control": "private, max-age=60"})


def _medien_verweise(basis: str):
    """Welche Entwuerfe haengen an dieser Datei? -> Zeilen mit Status.

    Der Grund fuer die ganze Zweistufigkeit beim Loeschen: `drafts.media_ref`
    haelt nur den NAMEN. Verschwindet die Datei, faellt es erst beim
    Zustellen auf — und bei einem freigegebenen Entwurf ist das nach der
    Entscheidung des Betreibers, also am schlechtesten Zeitpunkt.
    """
    return server._q(
        "select d.id, d.status, d.channel, l.name from drafts d "
        "left join leads l on l.id = d.lead_id "
        "where d.media_ref = %s order by d.created_at", (basis,))


def _medien_loeschen_warnseite(basis: str, verweise) -> HTMLResponse:
    if verweise:
        liste = "".join(
            f'<li>{_e(z["status"])} · {_e(z["channel"])} · '
            f'{_e(z["name"] or "(ohne Kontakt)")}</li>' for z in verweise)
        hinweis = (f'<p><b>An dieser Datei hängen {len(verweise)} '
                   f'Entwürfe:</b></p><ul>{liste}</ul>'
                   f'<p>Nach dem Löschen scheitern sie beim Zustellen — '
                   f'`drafts.media_ref` hält nur den Namen, nicht die '
                   f'Datei.</p>')
    else:
        hinweis = "<p>Kein Entwurf verweist auf diese Datei.</p>"
    return _seite(
        "Löschen bestätigen",
        f'<h1>Löschen bestätigen</h1><div class="karte">'
        f'<p>Datei: <b>{_e(basis)}</b></p>{hinweis}'
        f'<p><b>Das ist ein echtes Löschen.</b> Anders als beim Archivieren '
        f'von Kontakten gibt es hier nichts zurückzuholen — die Datei liegt '
        f'danach nicht mehr im Medienordner.</p>'
        f'<div class="aktionen">'
        f'<form class="aktion gefahr" method="post" '
        f'action="/medien/loeschen-bestaetigen">'
        f'<input type="hidden" name="name" value="{_e(basis)}">'
        f'<input type="hidden" name="name_bestaetigt" value="{_e(basis)}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<button class="gefahr">Ja — {_e(basis)} löschen</button>'
        f'</form></div>'
        f'<p class="abbrechen"><a href="/medien">Abbrechen, nichts tun</a>'
        f'</p></div>', status=409)


@_gesichert_seite
async def aktion_medien_loeschen(request):
    """Erster Schritt: NUR die Warnseite. Hier wird nichts geloescht."""
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    basis, fehler = server.medien.pruefe(str(form.get("name") or ""))
    if fehler:
        return _fehlerseite(404, "Nicht gefunden", _e(fehler))
    return _medien_loeschen_warnseite(basis, _medien_verweise(basis))


@_gesichert_seite
async def aktion_medien_loeschen_bestaetigen(request):
    """Der zweite, ausdrueckliche Schritt — mit erneuter Pruefung.

    Ein FREIGEGEBENER Entwurf blockiert das Loeschen ganz, nicht nur mit
    einer Warnung: der Dispatcher liest die Datei erst beim Zustellen und
    kann das jeden Moment tun. Wer sie trotzdem los will, lehnt den Entwurf
    vorher ab — dann ist die Entscheidung dokumentiert, statt aus einem
    fehlenden Anhang zu folgen.
    """
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    basis, fehler = server.medien.pruefe(str(form.get("name") or ""))
    if fehler:
        return _fehlerseite(404, "Nicht gefunden", _e(fehler))
    if str(form.get("name_bestaetigt") or "") != basis:
        return _fehlerseite(400, "Bestätigung fehlt", (
            "Ohne den auf der Warnseite gelesenen Dateinamen wird nichts "
            "gelöscht."))

    verweise = _medien_verweise(basis)
    freigegeben = [z for z in verweise if z["status"] == "approved"]
    if freigegeben:
        return _fehlerseite(409, "Nicht gelöscht", (
            f"Auf '{_e(basis)}' verweisen {len(freigegeben)} FREIGEGEBENE "
            f"Entwürfe. Der Versender liest die Datei erst beim Zustellen "
            f"und kann das jeden Moment tun — dann ginge eine Nachricht "
            f"ohne ihre Unterlage raus oder scheiterte. Erst die Entwürfe "
            f"ablehnen, dann die Datei löschen."))
    # `medien.pfad()` statt `medien.wurzel()` (12.09.2026, Betreiber-Befund
    # „das Loeschen in Medien geht nicht"): die Seite listet BEIDE Ordner —
    # den Upload-Ordner des Menschen und den fuer erzeugte Unterlagen —,
    # der Loeschbefehl griff aber hart nur in den ersten. Jede erzeugte
    # Datei (Kalenderdateien, erzeugte PDFs) war damit unloeschbar, und der
    # Fehlertext zeigte auf die falsche Ursache. `pfad()` folgt derselben
    # Rangfolge wie die Anzeige (Mensch vor System), sodass der Knopf genau
    # die Datei trifft, die daneben steht.
    ziel = server.medien.pfad(basis)
    try:
        os.unlink(ziel)
    except OSError as e:
        return _fehlerseite(500, "Nicht gelöscht", (
            f"Datei nicht löschbar ({_e(type(e).__name__)}) in "
            f"{_e(os.path.dirname(ziel))}. Ist dieser Ordner an sales-ui "
            f"schreibbar eingehängt, also ohne `:ro`?"))
    LOG.warning("Medien: %s gelöscht (%d Entwürfe verwiesen darauf)",
                basis, len(verweise))
    return RedirectResponse("/medien", status_code=303)


@_gesichert_seite
async def medien(request):
    return _seite("Medien", _medien_tabelle() + _medien_formular())


@_gesichert_seite
async def aktion_medien_hochladen(request):
    """Eine Unterlage ablegen — die einzige Stelle, an der etwas hereinkommt.

    Geschrieben wird erst unter einem Zwischennamen und dann umbenannt: ein
    abgebrochener Upload soll keine halbe Datei hinterlassen, die der
    Dispatcher spaeter fuer eine gueltige Unterlage haelt.
    """
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    datei = form.get("datei")
    if datei is None or not getattr(datei, "filename", ""):
        return _fehlerseite(400, "Keine Datei", "Es wurde nichts ausgewählt.")

    basis, fehler = server.medien.pruefe_neuen_namen(datei.filename)
    if fehler:
        return _fehlerseite(400, "Nicht abgelegt", _e(fehler))
    ueberschreiben = str(form.get("ueberschreiben") or "").strip() == "ja"
    if server.medien.liegt_schon(basis) and not ueberschreiben:
        return _fehlerseite(409, "Datei gibt es schon", (
            f"'{_e(basis)}' liegt bereits im Medienordner. Sie kann an einem "
            f"freigegebenen Entwurf hängen, den der Dispatcher erst beim "
            f"Zustellen liest — deshalb wird hier nichts still ersetzt. Wer "
            f"es trotzdem will, setzt den Haken „Vorhandene Datei gleichen "
            f"Namens ersetzen“."))

    wurzel = server.medien.wurzel()
    ziel = os.path.join(wurzel, basis)
    zwischen = os.path.join(wurzel, basis + ".teil")
    geschrieben = 0
    try:
        with open(zwischen, "wb") as raus:
            while True:
                stueck = await datei.read(MEDIEN_STUECK)
                if not stueck:
                    break
                geschrieben += len(stueck)
                if geschrieben > server.medien.MAX_BYTES:
                    raise ValueError("zu gross")
                raus.write(stueck)
        if geschrieben == 0:
            raise ValueError("leer")
        os.replace(zwischen, ziel)
    except ValueError as e:
        _aufraeumen(zwischen)
        grenze = server.medien.MAX_BYTES // 1048576
        return _fehlerseite(413 if "gross" in str(e) else 400,
                            "Nicht abgelegt",
                            f"Die Datei ist leer oder größer als {grenze} MB."
                            if "gross" in str(e) else "Die Datei ist leer.")
    except OSError as e:
        _aufraeumen(zwischen)
        return _fehlerseite(500, "Nicht abgelegt", (
            f"Der Medienordner ist nicht beschreibbar "
            f"({_e(type(e).__name__)}). Hängt er an diesem Dienst ohne "
            f"`:ro`?"))
    LOG.info("Medien: %s abgelegt (%d Byte)", basis, geschrieben)
    return RedirectResponse("/medien", status_code=303)


@_gesichert_seite
async def aktion_medien_bot(request):
    """Schalter „Bot darf senden" je Datei (UI-Plan Schritt 4). Kennt nur
    Dateien, die es gibt — fuer eine geloeschte Datei eine Zeile anzulegen
    waere ein Geist in der Tabelle."""
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    erlaubt = str(form.get("erlaubt") or "").strip()
    if erlaubt not in ("ja", "nein"):
        return _fehlerseite(400, "Unklarer Schalter",
                            "erlaubt muss ja oder nein sein.")
    basis, fehler = server.medien.pruefe(str(form.get("name") or ""))
    if fehler:
        return _fehlerseite(404, "Datei unbekannt", _e(fehler))
    server.medien_meta_setzen(basis, bot_darf_senden=(erlaubt == "ja"))
    LOG.info("Medien: %s für den Bot %s", basis,
             "freigegeben" if erlaubt == "ja" else "gesperrt")
    return RedirectResponse("/medien", status_code=303)


def _aufraeumen(pfad: str) -> None:
    try:
        os.unlink(pfad)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Wiedervorlagen anlegen und quittieren (Betreiber-Wunsch 25.08.2026)
#
# „und was sollte auf wiedervorlagen sein?" — die Seite war leer, weil es in
# der Oberflaeche gar keinen Weg gab, eine anzulegen: das konnte nur der
# Agent im Chat. Eine Ansicht, die nur zeigt, was man anderswo erzeugen muss,
# beantwortet die Frage „wofuer ist das?" nicht.
#
# Beides laeuft ueber die Chat-Werkzeuge (server.wiedervorlage_setzen,
# server.wiedervorlage_erledigt) — kein zweiter Schreibweg, dieselbe
# Datumspruefung, dasselbe Append-only: erledigt heisst Gegen-Ereignis, nicht
# Loeschen.
# ---------------------------------------------------------------------------

def _wiedervorlage_formular(lead_id) -> str:
    return (
        f'<h2>Wiedervorlage</h2><div class="karte">'
        f'<form method="post" action="/wiedervorlagen/setzen">'
        f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<p><label class="feld">Fällig am<br>'
        f'<input type="date" name="faellig_am" required></label></p>'
        f'<p><label class="feld">Notiz<br>'
        f'<input type="text" name="notiz" maxlength="300" required '
        f'placeholder="Rückruf wegen des Angebots"></label></p>'
        f'<div class="aktionen">'
        f'<button class="primaer">Merken</button></div></form>'
        f'<p class="meta">Erscheint ab dem Fälligkeitstag im Digest und '
        f'unter <a href="/wiedervorlagen">Wiedervorlagen</a>, bis sie '
        f'quittiert wird. Es geht dabei nichts an den Kunden.</p></div>')


@_gesichert_seite
async def aktion_wiedervorlage_setzen(request):
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.wiedervorlage_setzen(
        lead_id=lead_id,
        faellig_am=str(form.get("faellig_am") or ""),
        notiz=str(form.get("notiz") or "")))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht gemerkt", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def aktion_wiedervorlage_erledigt(request):
    """Quittieren — append-only: es entsteht ein Gegen-Ereignis, nichts wird
    geloescht und nichts geaendert."""
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.wiedervorlage_erledigt(
        lead_id=lead_id,
        aktivitaets_id=str(form.get("aktivitaets_id") or "")))
    if "fehler" in antwort:
        return _fehlerseite(409, "Nicht quittiert", _e(antwort["fehler"]))
    return RedirectResponse("/wiedervorlagen", status_code=303)


@_gesichert_seite
async def inbox(request):
    """Freigaben in vier Bloecken — WhatsApp, LinkedIn, E-Mail, Termine —
    jeder mit seinen offenen Entwuerfen (zu pruefen, fehlgeschlagen,
    freigegeben) und darunter seinem eigenen Verlauf (UI-Plan Schritt 3,
    Betreiber 02.09.2026: „damit alles seine Ordnung hat")."""
    pending = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.media_ref, d.subject, d.cc, "
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

    def je_art(zeilen):
        d = {}
        for z in zeilen:
            d.setdefault(str(z["channel"]), []).append(z)
        return d
    offen, kaputt, wartend = je_art(pending), je_art(gescheitert), je_art(freigegeben)
    bekannt = dict(FREIGABE_ARTEN)
    # Unbekannte Kanaele (falls je einer dazukommt) haengen sich hinten an,
    # statt unsichtbar zu bleiben.
    arten = list(FREIGABE_ARTEN) + [
        (a, a) for a in sorted(set(offen) | set(kaputt) | set(wartend))
        if a not in bekannt]

    # Merge 12.09.2026: inhaltlich die Fassung der Konferenz-Linie (der Satz
    # ueber das fehlende Neuladen gehoert hierher), aber in echten Umlauten —
    # Stufe 1 hat die ASCII-Umschreibungen in ALLEN Anzeigetexten beseitigt,
    # und der Waechter-Test in test_darstellung.py laesst „Verlaeufe" hier
    # nicht mehr durch. Beides behalten heisst: ihr Text, meine Schreibweise.
    teile = ['<p class="meta">Vier Arten, vier Listen, vier Verläufe. '
             'Freigeben heißt senden; nichts geht ohne dich raus. '
             'Diese Seite lädt nicht von selbst neu, damit dir beim '
             'Tippen nichts verloren geht — '
             '<a href="/freigaben">neu laden</a>, wenn du Neues erwartest.</p>']
    for art, name in arten:
        n_offen = len(offen.get(art, []))
        teile.append(
            f'<section class="block"><h2>{_badge(art)} {_e(name)} '
            f'<span class="zaehler{" offen" if n_offen else ""}">{n_offen}'
            f'</span></h2>')
        if not (offen.get(art) or kaputt.get(art) or wartend.get(art)):
            teile.append('<p class="meta">Nichts offen.</p>')
        for z in offen.get(art, []):
            # „Freigeben" und „Ablehnen" stehen in EINEM `.aktionen`-Kasten:
            # nebeneinander am Desktop, gestapelt ueber die volle Breite am
            # Handy. Beides ist nicht zurueckzunehmen.
            teile.append(_entwurf_karte_offen(z))
        for z in kaputt.get(art, []):
            teile.append(
                f'<div class="karte">{_entwurf_kopf(z, "failed")}'
                f'<div class="text">{_text_html(z["body"])}</div>'
                f'<div class="fehler">Fehler: {_e(z["error"])}</div>'
                f'<div class="aktionen">'
                f'{_formular("erneut-freigeben", z["id"], "Erneut freigeben", "",
                             checkbox="erneute Freigabe bestätigen")}'
                # Einschrittig: ein gescheiterter Entwurf ging nachweislich
                # nicht raus, und verwerfen versendet nichts.
                f'{_formular("verwerfen", z["id"], "Verwerfen", "gefahr")}'
                f"</div></div>")
        for z in wartend.get(art, []):
            if z["channel"] == "linkedin":
                stand = ('<div class="hinweis">LinkedIn: von Hand posten, '
                         'danach im Chat <code>entwurf_manuell_gesendet</code> '
                         'melden — automatisch geht hier nichts raus.</div>')
            else:
                stand = ('<div class="meta">wartet auf Dispatcher '
                         '(Versand übernimmt der zuständige Dienst '
                         'automatisch)</div>')
            teile.append(
                f'<div class="karte">{_entwurf_kopf(z, "approved")}'
                f'<div class="text">{_text_html(z["body"])}</div>'
                f'<div class="meta">freigegeben: {_e(z["approved_by"])} am '
                f'{_zeit(z["approved_at"])}</div>{stand}'
                # ZWEISTUFIG: dieser Knopf fuehrt auf eine Warnseite und
                # schreibt selbst nichts (aktion_verwerfen).
                f'<div class="aktionen">'
                f'{_formular("verwerfen", z["id"], "Verwerfen", "gefahr")}'
                f'</div></div>')
        teile.append(_verlauf_block(art, name))
        teile.append("</section>")

    # Termine: offen = Anfragen ohne festes Datum; Verlauf = bestaetigt,
    # verschoben, abgesagt.
    termine_offen = server._q(
        "select l.id as lead_id, l.name, a.payload from activities a "
        "left join leads l on l.id = a.lead_id "
        "where a.type = 'termin' and coalesce(a.payload->>'datum', '') = '' "
        "order by a.created_at desc limit 20")
    teile.append(
        f'<section class="block"><h2><span class="badge termin">Termine</span> '
        f'Termine <span class="zaehler{" offen" if termine_offen else ""}">'
        f'{len(termine_offen)}</span></h2>')
    if not termine_offen:
        teile.append('<p class="meta">Keine Terminanfrage ohne festes Datum.</p>')
    for z in termine_offen:
        last = z["payload"] or {}
        voll = str(last.get("inhalt") or last.get("thema") or "")
        teile.append(
            f'<div class="karte"><b><a href="/kontakte/{_e(z["lead_id"])}">'
            f'{_e(z["name"] or "?")}</a></b> '
            f'<span class="meta" title="{_e(voll)}">{_e(_kurz(voll, 160))}'
            f'</span> · <a href="/kalender">im Kalender</a></div>')
    teile.append(_verlauf_block("termine", "Termine"))
    teile.append("</section>")
    # KEIN Auto-Refresh mehr (Betreiber 03.09.2026: „ich bearbeite einen Text
    # und werde wie bei einem Reload in die Mitte der Seite gezogen") — auf
    # dieser Seite wird getippt, und ein Neuladen wirft den Text weg.
    return _seite("Freigaben", "".join(teile))


VERLAUF_JE_ART = 5      # Eintraege je Art auf der Freigabe-Seite
VERLAUF_MAX = 200       # Eintraege auf der Verlaufsseite einer Art


def _verlauf_entwuerfe(art: str, limit: int):
    """Gesendet und abgelehnt sind Verlauf; fehlgeschlagen ist offen
    (Erneut freigeben / Verwerfen) und steht darum NICHT hier."""
    return server._q(
        "select d.id, d.channel, d.recipient, d.body, d.status, d.error, "
        "       coalesce(d.sent_at, d.approved_at, d.created_at) as wann, "
        "       l.name from drafts d left join leads l on l.id = d.lead_id "
        "where d.channel = %s and d.status in ('sent', 'rejected') "
        "order by wann desc limit %s", (art, limit))


def _verlauf_termine(limit: int):
    return server._q(
        "select a.type, a.payload, a.created_at as wann, "
        "       l.id as lead_id, l.name from activities a "
        "left join leads l on l.id = a.lead_id "
        "where a.type in ('termin', 'termin_verschoben', 'termin_abgesagt') "
        "and (a.type <> 'termin' or coalesce(a.payload->>'datum', '') <> '') "
        "order by a.created_at desc limit %s", (limit,))


def _verlauf_zeile_entwurf(z) -> str:
    text_voll = str(z["body"] or "")
    text = (f'<span title="{_e(text_voll)}">'
            f'{_e(_kurz(text_voll, ENTWURF_VORSCHAU))}</span>')
    return (f'<div class="eintrag"><span class="wann">{_e(_zeit(z["wann"]))}'
            f'</span><span class="was"><b>{_e(z["name"] or "(ohne Kontakt)")}'
            f'</b> &rarr; {_e(z["recipient"])} · {text}</span>'
            f'{_zustand_badge(str(z["status"]))}</div>')


def _verlauf_zeile_termin(z) -> str:
    last = z["payload"] or {}
    stuecke = [f'<b>{_e(z["name"] or "(ohne Kontakt)")}</b>']
    wann_termin = " ".join(s for s in (str(last.get("datum") or ""),
                                       str(last.get("uhrzeit") or "")) if s)
    if wann_termin:
        stuecke.append(_e(wann_termin))
    for schluessel in ("thema", "grund"):
        wert_voll = last.get(schluessel)
        if wert_voll:
            wert_voll = str(wert_voll)
            stuecke.append(f'<span title="{_e(wert_voll)}">'
                           f'{_e(_kurz(wert_voll, 120))}</span>')
    return (f'<div class="eintrag"><span class="wann">{_e(_zeit(z["wann"]))}'
            f'</span><span class="was">{" · ".join(stuecke)}</span>'
            f'{_zustand_badge(str(z["type"]))}</div>')


def _verlauf_block(art: str, name: str) -> str:
    if art == "termine":
        zeilen = _verlauf_termine(VERLAUF_JE_ART)
        rumpf = "".join(_verlauf_zeile_termin(z) for z in zeilen)
    else:
        zeilen = _verlauf_entwuerfe(art, VERLAUF_JE_ART)
        rumpf = "".join(_verlauf_zeile_entwurf(z) for z in zeilen)
    if not zeilen:
        rumpf = '<p class="meta">Noch nichts im Verlauf.</p>'
    return (f'<h3 class="verlauftitel">Verlauf {_e(name)}'
            f'<a href="/freigaben/verlauf/{_e(art)}">Ganzer Verlauf</a></h3>'
            f'{rumpf}')


@_gesichert_seite
async def freigaben_verlauf(request):
    art = str(request.path_params.get("art") or "")
    namen = dict(FREIGABE_ARTEN)
    if art == "termine":
        name = "Termine"
        zeilen = _verlauf_termine(VERLAUF_MAX)
        rumpf = "".join(_verlauf_zeile_termin(z) for z in zeilen)
    elif art in namen:
        name = namen[art]
        zeilen = _verlauf_entwuerfe(art, VERLAUF_MAX)
        rumpf = "".join(_verlauf_zeile_entwurf(z) for z in zeilen)
    else:
        return _fehlerseite(404, "Unbekannte Art",
                            "Verläufe gibt es für whatsapp, linkedin, email "
                            "und termine.")
    if not zeilen:
        rumpf = '<p class="meta">Noch nichts im Verlauf.</p>'
    kopf = (f'<p class="meta">{len(zeilen)} Einträge (höchstens {VERLAUF_MAX}) '
            f'· <a href="/freigaben">Zurück zu den Freigaben</a></p>')
    return _seite(f"Verlauf {name}", kopf + rumpf)


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
        409, "Keine Aktion ausgeführt",
        f"Entwurf {_e(draft_id)} hat Status "
        f"&#x27;{_e(zeilen[0]['status'])}&#x27;, erwartet "
        f"&#x27;{_e(erwartet)}&#x27;. Der Entwurf blieb unverändert.")


async def _aktions_vorspann(request):
    """Gemeinsame Wache aller POSTs: CSRF zuerst, dann die draft_id.

    Reihenfolge ist Teil des Vertrags (wie in inbox.py): VOR der ersten Zeile
    Datenbank steht die Token-Pruefung — ein abgewiesener POST hat keinerlei
    Wirkung, auch keine Lesespur."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungültig",
            "Keine Aktion ausgeführt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("draft_id") or "").strip()
    try:
        draft_id = str(uuid.UUID(roh))
    except ValueError:
        return None, None, _fehlerseite(
            400, "Unlesbare draft_id",
            f"&#x27;{_e(roh)}&#x27; ist keine UUID. Keine Aktion ausgeführt.")
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
    form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    # Freigegeben wird, was GELESEN wurde (29.08.2026): der Stand aus dem
    # Formular muss zum aktuellen Text passen. Eine seit dem Laden der
    # Seite geaenderte Fassung wird nicht still freigegeben — genau das
    # ist an diesem Tag passiert (Ueberarbeitung zwischen Laden und Klick).
    aktuell = server._q("select body, status from drafts where id = %s",
                        (draft_id,))
    if not aktuell or aktuell[0]["status"] != "pending":
        return _statusfehler(draft_id, "pending")
    stand = str(form.get("stand") or "")
    if not stand:
        return _fehlerseite(
            400, "Lese-Stand fehlt",
            "Diese Freigabe trägt keinen Stand des gelesenen Textes — "
            "Seite neu laden und aus der aktuellen Ansicht freigeben.")
    if stand != _text_stand(aktuell[0]["body"] or ""):
        return _fehlerseite(
            409, "Text wurde geändert",
            "Der Entwurf wurde geändert, seit diese Seite geladen wurde. "
            "Nichts freigegeben — Seite neu laden, den AKTUELLEN Text "
            "lesen, dann freigeben.")
    # SQL wie server.entwurf_freigeben — einziger Unterschied: approved_by
    # (angemeldeter Benutzer; 'betreiber-ui', solange die Anmeldung nicht
    # scharf ist — test_login.py haelt beide Richtungen fest).
    zeilen = server._q(
        "update drafts set status = 'approved', approved_by = %s, "
        "approved_at = now() where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (_ui_akteur(request), draft_id))
    if not zeilen:
        return _statusfehler(draft_id, "pending")
    _freigabe_loggen(zeilen[0])
    return RedirectResponse("/freigaben", status_code=303)


@_gesichert_seite
async def aktion_bearbeiten(request):
    """Den Text eines Entwurfs aendern — vor der Freigabe.

    Geht ueber `server.entwurf_bearbeiten`, also durch dieselbe Kante wie
    der Chat: nur `pending`, dieselben Laengengrenzen, dasselbe Protokoll
    mit altem und neuem Text. Diese Oberflaeche baut keinen zweiten
    Schreibweg.
    """
    form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.entwurf_bearbeiten(
        draft_id=draft_id, text=str(form.get("text") or ""),
        betreff=str(form.get("betreff") or "")[:BETREFF_MAX],
        # cc nur, wenn das Formular das Feld hatte (E-Mail); sonst unveraendert.
        cc=(str(form.get("cc") or "")[:CC_FELD_MAX] if "cc" in form else None)))
    if "fehler" in antwort:
        return _fehlerseite(409, "Nicht geändert", _e(antwort["fehler"]))
    return RedirectResponse("/freigaben", status_code=303)


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
    return RedirectResponse("/freigaben", status_code=303)


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
            400, "Bestätigung fehlt",
            "Erneut freigeben heißt: derselbe Versand wird noch einmal "
            "versucht. Ohne gesetztes Häkchen wird nichts getan.")
    # SQL wie server.entwurf_erneut_freigeben mit bestaetigt=False —
    # inklusive der Doppelversand-Marken-Pruefung (Claim-Praefix aus
    # server.py, dort begruendet: kein Import von dispatch.py moeglich).
    zeilen = server._q(
        "update drafts set status = 'approved', approved_by = %s, "
        "approved_at = now(), error = null "
        "where id = %s and status = 'failed' "
        "and (%s or error is null or error not like %s) "
        "returning id, lead_id, channel",
        (_ui_akteur(request), draft_id, False,
         f"{server._CLAIM_MARKE_PRAEFIX}%"))
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
                409, "Verweigert: möglicher Doppelversand",
                "Dieser Entwurf trägt die Zustellungs-Marke des Dispatchers "
                "— ein Absturz zwischen Claim und Buchung kann bedeuten, dass "
                "die Nachricht BEREITS ZUGESTELLT wurde. Diese Oberfläche "
                "gibt so einen Entwurf grundsätzlich nicht erneut frei. Wer "
                "das Doppelversand-Risiko ausdrücklich übernehmen will, tut "
                "das im Chat: entwurf_erneut_freigeben(draft_id, "
                f"bestaetigt=True). error: {_e(error)}")
        return _statusfehler(draft_id, "failed")
    _freigabe_loggen(zeilen[0], erneut=True)
    return RedirectResponse("/freigaben", status_code=303)


# ---------------------------------------------------------------------------
# Verwerfen — der vierte Schreibweg (Betreiber-Wunsch 22.08.2026)
#
# Bis hierher gab es fuer einen Entwurf keinen Ausgang ausser dem Versand:
# `failed` liess sich nur erneut freigeben, `approved` gar nicht mehr stoppen.
# Beides sammelt sich sichtbar in dieser Inbox an.
#
# Das SQL spiegelt `server.entwurf_verwerfen` — wie bei den drei Aktionen
# darueber und aus demselben Grund: die Protokollzeile soll `actor='human'`
# tragen, und das kann nur schreiben, wer selbst schreibt (das Chat-Werkzeug
# hat auf `activities.actor` den Spalten-Default 'agent' und kann ihn nicht
# ueberschreiben). Was NICHT gespiegelt wird, ist die Bestaetigungs-Uebernahme
# des Marken-Falls: `bestaetigt` bleibt hier ueberall implizit False.
#
# Zweistufig ist NUR der `approved`-Fall. Der Unterschied ist echt: ein
# `failed`-Entwurf ging nachweislich nicht raus, ein `approved` ist eine
# GELTENDE Freigabe, die der Dispatcher jederzeit nehmen darf. Muster wie bei
# `ignorieren-bestaetigen` und `archivieren-bestaetigen` — erster POST
# schreibt nichts, zweiter POST auf eigener Route, mit dem Wert, den der
# Betreiber gelesen hat (hier: der Empfaenger).
# ---------------------------------------------------------------------------

VERWERFEN_TEXT_MAX = 400   # Textanfang auf der Warnseite

_MARKE_SQL = " and (error is null or error not like %s)"


def _verwerfen_loggen(z, aus_status: str) -> None:
    # actor='human'/weg='ui' — dieselbe Begruendung wie in `_freigabe_loggen`.
    # `aus_status` gehoert zwingend dazu: nach dem Uebergang traegt die Zeile
    # `rejected` und sagt nicht mehr, ob sie gescheitert oder freigegeben war.
    server._q("insert into activities (lead_id, type, payload, actor) "
              "values (%s, 'verwerfung', %s, 'human') returning id",
              (z["lead_id"], server._json({"draft_id": str(z["id"]),
                                           "kanal": z["channel"],
                                           "aus_status": aus_status,
                                           "weg": "ui"})))


def _marken_seite(error: str) -> HTMLResponse:
    """Die Verweigerung des Marken-Falls — ausnahmslos, wie beim erneuten
    Freigeben. Hier zaehlt sie andersherum: dort waere ein zweiter Versand der
    Schaden, hier ein `rejected`, das eine erfolgte Zustellung verdeckt."""
    return _fehlerseite(
        409, "Verweigert: möglicherweise bereits zugestellt",
        "Dieser Entwurf trägt die Zustellungs-Marke des Dispatchers — ein "
        "Absturz zwischen Claim und Buchung kann bedeuten, dass die Nachricht "
        "BEREITS BEIM EMPFÄNGER ist. Ihn zu verwerfen schriebe dann eine "
        "Lüge in die Datenbank: die Zeile sähe aus wie &#x27;nie "
        "rausgegangen&#x27;. Diese Oberfläche verwirft so einen Entwurf "
        "grundsätzlich nicht. Wer das ausdrücklich verantworten will, tut "
        "das im Chat: entwurf_verwerfen(draft_id, bestaetigt=True). "
        f"error: {_e(error)}")


def _verwerfen_warnseite(z) -> HTMLResponse:
    """Erster Schritt beim `approved`-Fall: zeigen, WAS da weggeraeumt wird —
    Empfaenger und Textanfang — und NICHTS schreiben."""
    text = str(z["body"] or "")
    anfang = text[:VERWERFEN_TEXT_MAX] + ("…" if len(text) > VERWERFEN_TEXT_MAX else "")
    anhang = (f'<p>Am Entwurf hängt der Anhang <b>{_e(z["media_ref"])}</b>.</p>'
              if z.get("media_ref") else "")
    return _seite(
        "Verwerfen bestätigen",
        f'<div class="warnung">Dieser Entwurf ist <b>freigegeben</b> und '
        f'wartet auf Zustellung an <b>{_e(z["recipient"])}</b>'
        f'{" (" + _e(z["name"]) + ")" if z.get("name") else ""} '
        f'über {_e(z["channel"])}.'
        f'<p>Verwerfen nimmt eine Freigabe zurück, die bereits gilt: der '
        f'zuständige Dispatcher dürfte diesen Entwurf jederzeit nehmen. '
        f'Danach steht er auf <code>rejected</code> und geht nicht mehr raus. '
        f'<b>Gelöscht wird nichts</b> — Text und Verlauf bleiben '
        f'vollzählig stehen.</p>{anhang}'
        f'<p>Ist der Entwurf inzwischen in Zustellung gegangen, wird hier '
        f'nichts getan (die Seite sagt es dann).</p></div>'
        f'<div class="text">{_text_html(anfang)}</div>'
        f'<div class="aktionen">'
        f'<form class="aktion gefahr" method="post" '
        f'action="/aktion/verwerfen-bestaetigen">'
        f'<input type="hidden" name="draft_id" value="{_e(z["id"])}">'
        f'<input type="hidden" name="empfaenger_bestaetigt" '
        f'value="{_e(z["recipient"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<button class="gefahr">Ja — Entwurf an {_e(z["recipient"])} '
        f'verwerfen</button></form></div>'
        f'<p class="abbrechen"><a href="/">Abbrechen, nichts tun</a></p>',
        status=409)


def _entwurf_zeile(draft_id):
    return server._q(
        "select d.id, d.status, d.error, d.channel, d.recipient, d.body, "
        "       d.media_ref, l.name "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.id = %s", (draft_id,))


@_gesichert_seite
async def aktion_verwerfen(request):
    """`failed` wird sofort verworfen, `approved` bekommt erst die Warnseite.

    Zwischen dem Lesen hier und dem Schreiben unten kann sich der Status
    aendern (der Dispatcher laeuft weiter). Das ist ungefaehrlich: das
    UPDATE traegt den Ausgangsstatus im WHERE, trifft dann null Zeilen und
    die Seite sagt, was wirklich los ist.
    """
    _form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    zeilen = _entwurf_zeile(draft_id)
    if not zeilen:
        return _fehlerseite(404, "Unbekannter Entwurf",
                            f"Kein Entwurf mit draft_id {_e(draft_id)}.")
    z = zeilen[0]
    # Der Status zuerst: `pending` und `sent` haben je einen eigenen Grund und
    # einen eigenen Satz dazu. Erst danach die Marke — sonst bekaeme ein
    # gesendeter Entwurf, an dem aus irgendeinem Grund noch eine Marke haengt,
    # die Marken-Seite statt der Wahrheit („ist zugestellt").
    if z["status"] not in server.VERWERFBARE_STATUS:
        return _verwerfen_statusfehler(z)
    error = z["error"] or ""
    if error.startswith(server._CLAIM_MARKE_PRAEFIX):
        return _marken_seite(error)
    if z["status"] == "approved":
        return _verwerfen_warnseite(z)
    # SQL wie server.entwurf_verwerfen (failed-Zweig) mit bestaetigt=False.
    getroffen = server._q(
        "update drafts set status = 'rejected' "
        "where id = %s and status = 'failed'" + _MARKE_SQL +
        " returning id, lead_id, channel",
        (draft_id, f"{server._CLAIM_MARKE_PRAEFIX}%"))
    if not getroffen:
        return _statusfehler(draft_id, "failed")
    _verwerfen_loggen(getroffen[0], "failed")
    return RedirectResponse("/freigaben", status_code=303)


@_gesichert_seite
async def aktion_verwerfen_bestaetigen(request):
    """Der ZWEITE, ausdrueckliche POST — nur fuer `approved`, und nur mit dem
    Empfaenger, den der Betreiber auf der Warnseite gelesen hat."""
    form, draft_id, abbruch = await _aktions_vorspann(request)
    if abbruch:
        return abbruch
    bestaetigt_fuer = str(form.get("empfaenger_bestaetigt") or "")
    if not bestaetigt_fuer:
        return _fehlerseite(
            400, "Bestätigung fehlt",
            "Ohne den auf der Warnseite gelesenen Empfänger wird nichts "
            "getan.")
    zeilen = _entwurf_zeile(draft_id)
    if not zeilen:
        return _fehlerseite(404, "Unbekannter Entwurf",
                            f"Kein Entwurf mit draft_id {_e(draft_id)}.")
    z = zeilen[0]
    # Zwischen Warnseite und Klick kann sich die Lage geaendert haben (eine
    # korrigierte Nummer im Chat, ein zweiter Tab). Dann ist das Ja von eben
    # kein Ja zu dem, was jetzt passieren wuerde — also lieber gar nichts.
    if str(z["recipient"] or "") != bestaetigt_fuer:
        return _fehlerseite(
            409, "Bestätigung passt nicht mehr",
            "Der Entwurf geht inzwischen an einen anderen Empfänger als auf "
            "der Warnseite. Nichts wurde getan — die Seite neu laden und "
            "erneut ansehen.")
    if (z["error"] or "").startswith(server._CLAIM_MARKE_PRAEFIX):
        return _marken_seite(z["error"])
    # SQL wie server.entwurf_verwerfen (approved-Zweig). Die Marken-Klausel
    # steht hier ZUSAETZLICH zur Pruefung oben: zwischen beiden kann der
    # Dispatcher geclaimt haben, und dann darf dieses UPDATE nicht greifen.
    getroffen = server._q(
        "update drafts set status = 'rejected' "
        "where id = %s and status = 'approved'" + _MARKE_SQL +
        " returning id, lead_id, channel",
        (draft_id, f"{server._CLAIM_MARKE_PRAEFIX}%"))
    if not getroffen:
        return _statusfehler(draft_id, "approved")
    _verwerfen_loggen(getroffen[0], "approved")
    return RedirectResponse("/freigaben", status_code=303)


def _verwerfen_statusfehler(z) -> HTMLResponse:
    """`pending` und `sent` haben je einen eigenen Grund — und `pending` hat
    einen anderen Weg, der auf derselben Seite als Knopf steht."""
    if z["status"] == "pending":
        return _fehlerseite(
            409, "Offener Entwurf — hier ist Ablehnen der Weg",
            "Dieser Entwurf steht noch auf &#x27;pending&#x27;. Offene "
            "Entwürfe werden mit dem Knopf <b>Ablehnen</b> im Block "
            "&#x27;Zur Freigabe&#x27; weggeräumt — das ist derselbe Vorgang "
            "(er endet ebenfalls auf &#x27;rejected&#x27;). Nichts getan.")
    if z["status"] == "sent":
        return _fehlerseite(
            409, "Gesendet — bleibt stehen",
            "Dieser Entwurf ist zugestellt. Die Zeile ist der Zustellnachweis "
            "und wird nicht verworfen: was raus ist, ist raus. Nichts getan.")
    return _fehlerseite(
        409, "Keine Aktion ausgeführt",
        f"Entwurf hat Status &#x27;{_e(z['status'])}&#x27; — verworfen wird "
        f"nur aus &#x27;failed&#x27; oder &#x27;approved&#x27;. Der Entwurf "
        f"blieb unverändert.")


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
    zeilen = server._q(  # noqa: E501 — Spaltenliste bleibt eine Zeile je Feld
        "select l.id, l.name, l.status, l.consent_status, l.enrichment, "
        "       l.score, "
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
    inhalt = []
    for z in zeilen:
        # `archiv` gibt dem Abzeichen einen gestrichelten Umriss statt einer
        # zweiten Grauschattierung — neben dem Wort das zweite, von der Farbe
        # unabhaengige Merkmal.
        archiviert = server._archiviert(z["enrichment"])
        sammel = _ist_sammelkontakt(z["id"])
        marke = (' <span class="badge archiv">archiviert</span>'
                 if archiviert else "")
        # Privat (P3, 29.08.2026): das Schloss macht sichtbar, dass dieser
        # Kontakt dem System still ist — nichts wird gespeichert.
        if server._privat(z["enrichment"]):
            marke += ' <span class="badge archiv" title="privat — es wird nichts gespeichert">&#128274; privat</span>'
        # Der Sammelkontakt sieht sonst aus wie eine Person mit sehr vielen
        # Nachrichten — genau diese Verwechslung ist am 25.08.2026 passiert.
        if sammel:
            marke += ' <span class="badge archiv">Sammelkontakt</span>'
        # Die Stufe deutsch wie auf /pipeline (29.08.2026); seit Schritt 5
        # (02.09.2026) als Chip, der Score als Pille, Consent als Meta-Zeile
        # unter dem Namen, die Autonomie als Segment statt Auswahlfeld.
        stufe = server._stufe_lesen(z["status"])
        inhalt.append([
            f'<a href="/kontakte/{_e(z["id"])}">{_e(z["name"])}</a>{marke}'
            f'<div class="meta">Consent: {_e(z["consent_status"])}</div>',
            f'<span class="stufe {_e(stufe)}">{_e(stufe)}</span>',
            _score_pille(z["score"]), _zeit(z["letzte"]),
            # Am Sammelkontakt keine Stufe: er ist kein Mensch, und eine
            # Stufe darauf liesse den Agenten allen Fremden antworten.
            "" if sammel else _autonomie_segment(
                z["id"], server._autonomie(z["enrichment"]),
                server._whatsapp_freigegeben(z["enrichment"])),
            # Kein Archiv-Knopf am Sammelkontakt: das Werkzeug lehnt es
            # ohnehin ab, und ein Knopf, der immer scheitert, ist eine Luege.
            "" if sammel else _archiv_knopf_zeile(z["id"], archiviert)])
    # „Consent: unknown" stand hier monatelang unerklaert (Betreiber-Frage
    # vom 25.08.2026, nie beantwortet). Eine Spalte, die bei JEDEM Kontakt
    # dasselbe unverstaendliche Wort zeigt, ist keine Information —
    # deshalb steht die Bedeutung jetzt unter der Tabelle. Seit F5
    # (31.08.2026) blockiert sie tatsaechlich: Erstansprachen brauchen
    # opt_in oder existing_customer.
    fussnote = ('<p class="meta"><b>Consent</b> ist die dokumentierte '
                'Werbe-Einwilligung nach UWG — <i>unknown</i> heißt: nie '
                'erfasst. Sie ist NICHT die WhatsApp-Freigabe (die steht auf '
                'der Kontaktseite). Ohne <i>opt_in</i> oder '
                '<i>existing_customer</i> entsteht kein Erstansprache-'
                'Entwurf per WhatsApp/E-Mail; Antworten auf eingehende '
                'Nachrichten bleiben frei.</p>')
    rumpf = [schalter, _tabelle(
        ["Name", "Stufe", "Score", "Zuletzt", "Autonomie", "Archiv"],
        inhalt), fussnote]
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
    spalten = (["Kontakt"] if mit_kontakt else []) + ["Fällig am", "Notiz"]
    inhalt = []
    for z in zeilen:
        nutzlast = z["payload"] or {}
        faellig = str(nutzlast.get("faellig_am") or "")
        marke = " <b>(fällig)</b>" if faellig and faellig <= heute else ""
        zelle = ([f'<a href="/kontakte/{_e(z["lead_id"])}">'
                  f'{_e(z["name"] or "(ohne Kontakt)")}</a>']
                 if mit_kontakt else [])
        quittieren = (
            f'<form class="aktion" method="post" '
            f'action="/wiedervorlagen/erledigt">'
            f'<input type="hidden" name="lead_id" value="{_e(z["lead_id"])}">'
            f'<input type="hidden" name="aktivitaets_id" '
            f'value="{_e(z["id"])}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button>Erledigt</button></form>')
        inhalt.append(zelle + [f"{_e(faellig)}{marke}",
                               _e(nutzlast.get("notiz")), quittieren])
    return (_tabelle(spalten + ["Quittieren"], inhalt) if zeilen
            else "<p>Keine offenen Wiedervorlagen. Eine anlegen: auf der "
                 "Kontaktseite unter „Wiedervorlage“.</p>")


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

    `type`/`inputmode` je Feld kommen aus KONTAKT_FELD_EINGABE (dort
    begruendet). Der `type="email"` bringt nebenbei die Browserpruefung mit —
    sie ist LOCKERER als `mailadresse.pruefe` (`max@localhost` kaeme durch)
    und ersetzt die serverseitige Pruefung deshalb nicht, sondern faengt nur
    den Vertipper ab, bevor er eine Runde ueber das Netz macht.
    """
    # Am Sammelkontakt gar kein Formular: `kontakt_aktualisieren` lehnt ihn
    # ab, und ein Eingabefeld, das beim Speichern immer scheitert, laedt
    # genau zu dem Missverstaendnis ein, das es verhindern soll.
    if _ist_sammelkontakt(lead["id"]):
        return (
            '<h2>Sammelkontakt für unbekannte Eingänge</h2>'
            '<div class="karte"><p><b>Das ist kein Mensch.</b> An diesem '
            'Satz hängt jede Nachricht einer Nummer, die noch keinem '
            'Kontakt zugeordnet ist — also die Nachrichten vieler '
            'verschiedener Absender nebeneinander. Ein Name daran täuschte '
            'eine Person vor, die es nicht gibt; deshalb sind seine '
            'Stammdaten gesperrt.</p>'
            '<p>Aufräumen geht über <a href="/einordnung">Einordnung</a>: '
            'dort wird jeder Absender einem echten Kontakt zugeordnet, und '
            'seine Nachrichten wandern mit.</p></div>')
    felder = "".join(
        f'<p><label class="feld">{_e(KONTAKT_FELD_TITEL.get(feld, feld))}<br>'
        f'<input {KONTAKT_FELD_EINGABE.get(feld, KONTAKT_FELD_EINGABE_STANDARD)}'
        f' name="{_e(feld)}" '
        f'maxlength="{KONTAKT_FELD_MAX}" value="{_e(lead[feld])}"></label></p>'
        for feld in _kontakt_feld_reihenfolge())
    return (
        f'<h2>Stammdaten bearbeiten</h2>'
        f'<div class="karte"><form method="post" action="/kontakte/bearbeiten">'
        f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">{felder}'
        f'<div class="aktionen">'
        f'<button class="primaer">Speichern</button></div></form>'
        f'<p class="meta">Änderbar sind nur diese Felder — Status, Consent '
        f'und Profilangaben nicht: die Einwilligung entsteht aus einer Antwort '
        f'des Kontakts (bedarf_speichern), Profilangaben gehören nach '
        f'profil_aktualisieren. Ein leeres Feld löscht die Angabe (der Name '
        f'nicht). Die <b>Telefonnummer</b> ist der Schlüssel, über den '
        f'eingehende Nachrichten diesem Kontakt zugeordnet werden — sie zu '
        f'ändern verschiebt künftige Nachrichten der alten Nummer zum '
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


def _whatsapp_freigabe_bereich(lead, freigegeben: bool) -> str:
    """Die WhatsApp-Freigabe — bis 25.08.2026 gab es sie in der Oberflaeche
    ueberhaupt nicht.

    Das war eine Luecke mit Folgen: der Betreiber konnte in der
    Kontaktliste `auto` einstellen, aber die Voraussetzung dafuer nirgends
    setzen. Der Waehler sagte dann „ohne Wirkung", ohne einen Weg
    anzubieten — dieselbe Art Sackgasse wie die Wiedervorlagen-Seite ohne
    Anlege-Formular.

    Bewusst ein eigener Abschnitt mit Erklaerung, nicht ein Schalter in der
    Liste: das hier ist die Entscheidung, dass ein Programm einem Menschen
    schreiben darf. Sie soll gelesen werden, nicht im Vorbeigehen
    umgelegt.
    """
    verborgen = (f'<input type="hidden" name="lead_id" '
                 f'value="{_e(lead["id"])}">'
                 f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">')
    if freigegeben:
        return (
            f'<h2 id="freigabe">WhatsApp-Freigabe</h2>'
            f'<div class="karte">'
            f'<p><b>Erteilt.</b> Der Dispatcher stellt freigegebene '
            f'Entwürfe an diesen Kontakt zu. Steht die Autonomiestufe auf '
            f'<code>auto</code>, antwortet der Agent selbst.</p>'
            f'<div class="aktionen"><form class="aktion gefahr" '
            f'method="post" action="/kontakte/freigabe-entziehen">'
            f'{verborgen}<button class="gefahr">Freigabe entziehen</button>'
            f'</form></div>'
            f'<p class="meta">Entziehen wirkt sofort: es entsteht kein '
            f'neuer WhatsApp-Entwurf, und bereits freigegebene werden nicht '
            f'mehr zugestellt, sondern mit klarem Grund fehlgeschlagen '
            f'gebucht.</p></div>')
    return (
        f'<h2 id="freigabe">WhatsApp-Freigabe</h2>'
        f'<div class="karte">'
        f'<p><b>Nicht erteilt.</b> An diesen Kontakt geht über WhatsApp '
        f'nichts raus — auch nicht, wenn die Autonomiestufe auf '
        f'<code>auto</code> steht.</p>'
        f'<div class="aktionen"><form class="aktion" method="post" '
        f'action="/kontakte/freigeben">{verborgen}'
        f'<button class="primaer">Für WhatsApp freigeben</button>'
        f'</form></div>'
        f'<p class="meta">Das ist die Entscheidung, dass ein Programm '
        f'diesem Menschen schreiben darf. Sie ersetzt <b>keine '
        f'Einwilligung des Kontakts</b> (consent, UWG) — das sind zwei '
        f'verschiedene Fragen, und die andere steht oben bei den '
        f'Stammdaten.</p></div>')


@_gesichert_seite
async def aktion_kontakt_freigeben(request):
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.kontakt_freigeben(lead_id=lead_id))
    if "fehler" in antwort:
        return _fehlerseite(409, "Nicht freigegeben", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def aktion_kontakt_freigabe_entziehen(request):
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.kontakt_freigabe_entziehen(lead_id=lead_id))
    if "fehler" in antwort:
        return _fehlerseite(409, "Nicht entzogen", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


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
                f'<div class="aktionen"><form class="aktion" method="post" '
                f'action="/kontakte/wiederherstellen">'
                f'{verborgen}<button class="primaer">Wiederherstellen</button>'
                f'</form></div><p class="meta">Holt den Kontakt zurück in '
                f'Kontaktliste, Posteingang und Zuordnungsauswahl. Ein '
                f'Gegen-Ereignis, kein Zurücknehmen — es war nie etwas '
                f'gelöscht.</p></div>')
    return (f'<h2>Archiv</h2><div class="karte">'
            f'<div class="aktionen"><form class="aktion gefahr" method="post" '
            f'action="/kontakte/archivieren">'
            f'{verborgen}<button class="gefahr">Archivieren</button></form>'
            f'</div>'
            f'<p class="meta">Nimmt den Kontakt aus Kontaktliste, Posteingang '
            f'und Zuordnungsauswahl. Der nächste Schritt zeigt erst, was an '
            f'ihm hängt. <b>Löschen gibt es hier nicht</b> — die Rolle hat '
            f'kein DELETE-Recht, und der Verlauf hängt mit ON DELETE CASCADE '
            f'am Kontakt: ein Löschen nähme die ganze Historie mit. Ein '
            f'echtes Löschbegehren ist ein Admin-Eingriff außerhalb dieser '
            f'Oberfläche.</p></div>')


async def _kontakt_vorspann(request):
    """Gemeinsame Wache aller Kontakt-POSTs — Reihenfolge wie ueberall:
    CSRF VOR der ersten Zeile Datenbank, dann die lead_id."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungültig",
            "Keine Aktion ausgeführt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("lead_id") or "").strip()
    try:
        lead_id = str(uuid.UUID(roh))
    except ValueError:
        return None, None, _fehlerseite(
            400, "Unlesbare lead_id",
            f"&#x27;{_e(roh)}&#x27; ist keine lead_id. Keine Aktion "
            f"ausgeführt.")
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
                "auch kontakt_aktualisieren. Nichts geändert.")
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
                    f"Nichts geändert.")
    if feld == "email":
        adresse, fehler = server.mailadresse.pruefe(wert)
        if adresse is None:
            return f"E-Mail-Adresse nicht verwendbar ({fehler}). Nichts geändert."
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
                400, "Nicht vollständig gespeichert",
                f"{_e(antwort['fehler'])}"
                + (f" Bereits gespeichert: {_e(', '.join(gesetzt))}."
                   if gesetzt else " Nichts geändert."))
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
        versand = ('<p><b>Achtung:</b> freigegebene Entwürfe an diesen '
                   'Kontakt stellt der Dispatcher weiter zu — Archivieren '
                   'hält keinen Versand an. Wer das will, lehnt die Entwürfe '
                   'ab (Freigabe-Inbox) und entzieht die WhatsApp-Freigabe '
                   '(im Chat: kontakt_freigabe_entziehen).</p>')
    return _seite(
        "Archivieren bestätigen",
        f'<div class="warnung">Der Kontakt <b>{_e(lead["name"])}</b> soll '
        f'archiviert werden. An ihm hängen <b>{_e(aktivitaeten)}</b> '
        f'Aktivität(en) und <b>{_e(offen)}</b> offene Entwürfe'
        f'{" (" + _e(aufschluesselung) + ")" if aufschluesselung else ""}.'
        f'<p>Archivieren nimmt ihn aus Kontaktliste, Posteingang und der '
        f'Zuordnungsauswahl der Einordnung. <b>Gelöscht wird nichts</b>: der '
        f'Verlauf bleibt vollzählig, der Kontakt bleibt über „auch '
        f'archivierte zeigen" erreichbar und lässt sich jederzeit '
        f'wiederherstellen.</p>{versand}'
        f'<p>Schreibt er später erneut, steht seine Nachricht nicht mehr im '
        f'Posteingang — also in genau der Ansicht, in der man ihn '
        f'wiederfinden würde.</p></div>'
        f'<div class="aktionen">'
        f'<form class="aktion gefahr" method="post" '
        f'action="/kontakte/archivieren-bestaetigen">'
        f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
        f'<input type="hidden" name="name_bestaetigt" '
        f'value="{_e(lead["name"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<button class="gefahr">Ja — {_e(lead["name"])} archivieren</button>'
        f'</form></div>'
        f'<p class="abbrechen"><a href="/kontakte/{_e(lead["id"])}">'
        f'Abbrechen, nichts tun</a></p>',
        status=409)


def _ist_sammelkontakt(lead_id) -> bool:
    """Ist das der Sammelkontakt fuer unbekannte Eingaenge?

    Er ist kein Mensch, sondern ein Systemsatz: an ihm haengt jede Nachricht
    einer noch unbekannten Nummer. In der Liste sah er bisher aus wie eine
    Person mit sehr vielen Nachrichten — am 25.08.2026 wurde er deshalb
    prompt umbenannt und danach fuer einen echten Kontakt gehalten.
    """
    return bool(server.UNBEKANNT_LEAD_ID) and \
        str(lead_id) == str(server.UNBEKANNT_LEAD_ID)


SCORE_HOCH, SCORE_MITTEL = 50, 30


def _score_pille(score) -> str:
    """Der Score als Pille — Farbe hilft, die Zahl traegt die Aussage."""
    if score is None:
        return '<span class="score leer">—</span>'
    n = int(score)
    klasse = " hoch" if n >= SCORE_HOCH else (" mittel" if n >= SCORE_MITTEL
                                             else "")
    return f'<span class="score{klasse}">{n}</span>'


def _autonomie_segment(lead_id, stufe: str, freigegeben: bool) -> str:
    """Die Autonomiestufe als Segment (UI-Plan Schritt 5): die gesetzte
    Stufe steht als Wort, jede andere ist ein Knopf — ein Klick, kein
    Auswahlfeld plus Setzen, und weiterhin ohne JavaScript. Dieselbe
    Route wie bisher; „auto" heisst nach wie vor, dass Nachrichten ohne
    menschlichen Blick an Menschen gehen."""
    teile = ['<div class="segment">']
    for s in server.AUTONOMIE_STUFEN:
        if s == stufe:
            teile.append(f'<span class="an">{_e(s)}</span>')
        else:
            teile.append(
                f'<form method="post" action="/kontakte/autonomie">'
                f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
                f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
                f'<input type="hidden" name="stufe" value="{_e(s)}">'
                f'<button>{_e(s)}</button></form>')
    teile.append("</div>")
    if stufe == "auto" and not freigegeben:
        teile.append(f'<div class="meta"><b>ohne Wirkung</b> — keine '
                     f'WhatsApp-Freigabe '
                     f'(<a href="/kontakte/{_e(lead_id)}#freigabe">erteilen'
                     f'</a>)</div>')
    return "".join(teile)


def _autonomie_waehler(lead_id, stufe: str, freigegeben: bool) -> str:
    """Die Autonomiestufe je Zeile — Auswahl plus Knopf, ohne JavaScript.

    Ein `<select>`, das beim Wechseln von selbst abschickt, braucht ein
    Skript; diese Oberflaeche hat keins und soll keins bekommen. Der
    zusaetzliche Klick ist hier ohnehin richtig: „auto" heisst, dass
    Nachrichten ohne menschlichen Blick an Menschen gehen.
    """
    optionen = "".join(
        f'<option value="{_e(s)}"{" selected" if s == stufe else ""}>'
        f'{_e(s)}</option>' for s in server.AUTONOMIE_STUFEN)
    # „auto" ohne WhatsApp-Freigabe ist wirkungslos — das gehoert dahin, wo
    # man es einstellt, nicht in eine Fehlermeldung hinterher.
    # Der Verweis gehoert dazu: eine Warnung, die nicht sagt, wo man es
    # behebt, ist eine Sackgasse. Bis 25.08.2026 gab es den Weg in der
    # Oberflaeche ueberhaupt nicht — nur diesen Satz.
    warnung = (f'<div class="meta"><b>ohne Wirkung</b> — keine '
               f'WhatsApp-Freigabe '
               f'(<a href="/kontakte/{_e(lead_id)}#freigabe">erteilen</a>)'
               f'</div>'
               if stufe == "auto" and not freigegeben else "")
    return (f'<form class="aktion" method="post" '
            f'action="/kontakte/autonomie">'
            f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<select name="stufe" aria-label="Autonomiestufe">{optionen}'
            f'</select> <button>Setzen</button></form>{warnung}')


def _privat_warnseite(lead) -> HTMLResponse:
    """Erster Schritt der Privat-Markierung: NUR die Warnseite. Der Verlust
    ist hier ein anderer als beim Archiv — kuenftige Nachrichten werden GAR
    NICHT gespeichert und sind nicht nachholbar. Genau das steht hier."""
    return _seite(
        "Privat markieren",
        f'<div class="warnung">Der Kontakt <b>{_e(lead["name"])}</b> soll '
        f'PRIVAT markiert werden.'
        f'<p><b>Ab dann wird nichts mehr gespeichert</b> — eingehende wie '
        f'ausgehende Nachrichten dieses Kontakts erreichen das System nicht '
        f'mehr, und diese stille Zeit lässt sich NICHT nachträglich '
        f'wiederherstellen. Kein Verlauf, keine Profile, keine Reports, '
        f'keine Entwürfe.</p>'
        f'<p>Bestandsdaten bleiben erhalten (ab jetzt still) und sind nur '
        f'noch über die Datenauskunft erreichbar. Aufheben lässt sich die '
        f'Markierung jederzeit — gespeichert wird dann erst wieder ab '
        f'diesem Moment.</p></div>'
        f'<div class="aktionen">'
        f'<form class="aktion gefahr" method="post" '
        f'action="/kontakte/privat-bestaetigen">'
        f'<input type="hidden" name="lead_id" value="{_e(lead["id"])}">'
        f'<input type="hidden" name="name_bestaetigt" '
        f'value="{_e(lead["name"])}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<button class="gefahr">Ja — {_e(lead["name"])} privat markieren'
        f'</button></form></div>'
        f'<p class="abbrechen"><a href="/kontakte/{_e(lead["id"])}">'
        f'Abbrechen</a></p>')


@_gesichert_seite
async def aktion_kontakt_privat(request):
    """Erster Schritt: nur die Warnseite, nichts geschrieben."""
    _form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    leads = _kontakt_zeile(lead_id)
    if not leads:
        return _fehlerseite(404, "Unbekannter Kontakt",
                            f"Kein Kontakt mit lead_id {_e(lead_id)}.")
    if server._privat(leads[0]["enrichment"]):
        return _fehlerseite(409, "Schon privat",
                            f"{_e(leads[0]['name'])} ist bereits privat "
                            f"markiert. Nichts getan.")
    return _privat_warnseite(leads[0])


@_gesichert_seite
async def aktion_kontakt_privat_bestaetigen(request):
    """Der zweite, ausdrueckliche POST — mit Namensabgleich wie beim
    Archivieren."""
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    if not str(form.get("name_bestaetigt") or ""):
        return _fehlerseite(
            400, "Bestätigung fehlt",
            "Ohne den auf der Warnseite gelesenen Namen wird nichts getan.")
    antwort = json.loads(server.kontakt_privat_setzen(lead_id))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht markiert", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def aktion_kontakt_privat_entziehen(request):
    """Aufheben geht direkt: es beginnt nur wieder das normale Speichern —
    verloren geht dabei nichts."""
    _form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.kontakt_privat_entziehen(lead_id))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht aufgehoben", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}", status_code=303)


@_gesichert_seite
async def aktion_kontakt_stufe(request):
    """Pipeline-Stufe setzen — ueber dasselbe Werkzeug wie der Chat.

    Ein leeres Begruendungsfeld wird zur ehrlichen Standard-Begruendung:
    der Klick des Betreibers ist die Entscheidung, das Protokoll traegt
    trotzdem einen Grund.
    """
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    begruendung = str(form.get("begruendung") or "").strip() or \
        "vom Betreiber über die Oberfläche gesetzt"
    antwort = json.loads(server.kontakt_stufe_setzen(
        lead_id=lead_id, stufe=str(form.get("stufe") or ""),
        begruendung=begruendung))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht gesetzt", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}#stufe", status_code=303)


def _wa_zeit(wert) -> str:
    """OpenWA liefert ISO-Zeichenketten, die Datenbank Datumsobjekte —
    `_zeit` kann nur letztere (dt.strftime). Eine fremde Zeichenkette
    darf die Diagnoseseite nicht zum Absturz bringen, deshalb hier ein
    eigener, nachsichtiger Formatierer."""
    if not wert:
        return "—"
    if hasattr(wert, "strftime"):
        return _zeit(wert)
    try:
        # Ueber _zeit, damit auch diese Seite Ortszeit zeigt (02.09.2026 im
        # Browser gefunden: „07:20 UTC" neben „18:20" auf derselben Seite).
        return _zeit(datetime.fromisoformat(str(wert).replace("Z", "+00:00")))
    except ValueError:
        return str(wert)[:32]


def _openwa_lesen(pfad: str):
    """Ein GET gegen OpenWA. Gibt (daten, fehlertext) — nie eine Ausnahme.

    Diese Seite ist eine DIAGNOSE. Wenn die Diagnose selbst abstuerzt,
    steht der Betreiber genau dann ohne Antwort da, wenn er sie braucht.
    """
    if not (OPENWA_URL and OPENWA_VIEWER_KEY):
        return None, ("Kein Nur-Lese-Zugang eingerichtet — "
                      "OPENWA_VIEWER_KEY fehlt in der .env.")
    try:
        anfrage = urllib.request.Request(
            OPENWA_URL + pfad, headers={"X-Api-Key": OPENWA_VIEWER_KEY})
        with urllib.request.urlopen(anfrage,
                                    timeout=OPENWA_TIMEOUT_S) as antwort:
            return json.loads(antwort.read() or b"null"), None
    except urllib.error.HTTPError as e:
        # Der Schluessel steht NIE in der Meldung — nur der Statuscode.
        return None, f"OpenWA antwortet mit HTTP {e.code}."
    except Exception:
        return None, ("OpenWA ist nicht erreichbar — läuft der Container "
                      "openwa?")


KETTE_STILL_H = 48      # ab so vielen Stunden ohne Kundennachricht: gelb


def _wa_karten_und_kette(sitzung, sitzung_fehler, letzte) -> str:
    """Drei Zustandskarten und die Kette Handy -> OpenWA -> Webhook ->
    Posteingang -> Datenbank (UI-Plan Schritt 6). Jede Station traegt ihren
    letzten Beweis als Satz; die Farbe kommt dazu, nicht statt dessen."""
    cron = server._q("select max(created_at) as wann from activities "
                     "where actor = 'cron' or type in "
                     "('stufenwechsel', 'transkription')")[0]["wann"]
    anzahl = server._q("select count(*) n from activities "
                       "where type = 'kundenantwort'")[0]["n"]
    # Zwei Zahlen statt einer: `count(*) from leads` zaehlte auch die
    # archivierten mit und hiess trotzdem "Kontakte" — dieselbe Bezeichnung
    # wie in der Navigation, die nur die aktiven zaehlt (gemessen 10.09.2026:
    # 469 gegen 461, Differenz genau die acht archivierten).
    aktive = server._q(
        "select count(*) n from leads l "
        "where not " + server._archiv_sql("l.enrichment"))[0]["n"]
    archivierte = server._q(
        "select count(*) n from leads l "
        "where " + server._archiv_sql("l.enrichment"))[0]["n"]
    stunden = None
    if letzte is not None:
        stunden = (server._q("select extract(epoch from (now() - %s))/3600 h",
                             (letzte,))[0]["h"] or 0)

    wort, klasse = sitzung
    if sitzung_fehler:
        wort, klasse = "nicht lesbar", "gefahr"
    openwa_punkt = "gut" if klasse == "gut" else (
        "gefahr" if klasse == "gefahr" else "warnung")
    if letzte is None:
        handy = ("warnung", "noch nie eine Kundennachricht — unbewiesen")
    elif stunden is not None and stunden > KETTE_STILL_H:
        handy = ("warnung", f"letzte Kundennachricht {_zeit(letzte)}, "
                            f"seit {stunden:.0f} h nichts")
    else:
        handy = ("gut", f"letzte Kundennachricht {_zeit(letzte)}")
    stationen = [
        ("Handy", handy[0], handy[1]),
        ("OpenWA", openwa_punkt,
         (sitzung_fehler or f"Sitzung {wort}")),
        ("Webhook", handy[0],
         ("Zustellung belegt durch die letzte Kundennachricht"
          if letzte is not None else "noch keine Zustellung belegt")),
        ("Posteingang", "gut" if letzte is not None else "warnung",
         (f"{anzahl} Kundennachrichten gebucht" if letzte is not None
          else "noch nichts gebucht — unbewiesen")),
        ("Datenbank", "gut",
         (f"{aktive} aktiver Kontakt" if aktive == 1
          else f"{aktive} aktive Kontakte")
         + f", {archivierte} archiviert, {anzahl} Kundenantworten"),
    ]
    kette = '<span class="strich"></span>'.join(
        f'<div class="schritt"><span class="punkt {_e(p)}"></span>'
        f'<b>{_e(name)}</b><div class="meta">{_e(beweis)}</div></div>'
        for name, p, beweis in stationen)
    automatik = (f'letzter Lauf {_e(_zeit(cron))}' if cron is not None
                 else 'noch kein Lauf gebucht')
    karten = (
        f'<div class="karten3">'
        f'<div class="karte"><div class="railtitel">Sitzung</div>'
        f'<span class="badge {_e(klasse)}">{_e(wort)}</span></div>'
        f'<div class="karte"><div class="railtitel">Automatik</div>'
        f'<div>{automatik}</div>'
        f'<div class="meta">„antworten-prüfen“ alle 2 h · Beweis: '
        f'gebuchte Stufenwechsel und Transkriptionen</div></div>'
        f'<div class="karte"><div class="railtitel">Kundennachrichten</div>'
        f'<div><b class="mono">{int(anzahl)}</b> gesamt</div>'
        f'<div class="meta">letzte: {_e(_zeit(letzte)) if letzte is not None else "keine"}'
        f'</div></div></div>')
    return (f'{karten}<h2>Weg vom Handy in die Datenbank</h2>'
            f'<div class="kette">{kette}</div>')


@_gesichert_seite
async def whatsapp(request):
    """Der WhatsApp-Zustand auf einen Blick.

    Beantwortet die Frage, die am 26.08.2026 eine Stunde gekostet hat:
    „Warum antwortet der Bot nicht?" — Sitzung verbunden? Webhook aktiv?
    Der Weg zum Neukoppeln steht als Verweis dabei; gekoppelt wird in der
    OpenWA-Oberflaeche, denn dafuer braucht es einen Schluessel, der
    senden darf — und der gehoert nicht in diese Anzeige.
    """
    # Keine eigene h1 — _seite setzt den Titel bereits; die Seite zeigte
    # „WhatsApp" zweimal untereinander (02.09.2026 im Browser gefunden).
    teile = []

    sitzung = ("unbekannt", "warnung")
    sitzungen, fehler = _openwa_lesen("/api/sessions")
    if fehler:
        teile.append(f'<div class="warnung"><b>Kein Zustand lesbar.</b> '
                     f'{_e(fehler)}</div>')
    else:
        passende = [s for s in (sitzungen or [])
                    if not OPENWA_SESSION_ID
                    or str(s.get("id")) == OPENWA_SESSION_ID]
        if not passende:
            teile.append('<div class="warnung">OpenWA kennt diese Sitzung '
                         'nicht — stimmt OPENWA_SESSION_ID?</div>')
        for s in passende:
            zustand = str(s.get("status") or "unbekannt")
            wort, klasse, erklaerung = WA_ZUSTAND.get(
                zustand, (zustand, "warnung",
                          "Unbekannter Zustand — in der OpenWA-Oberfläche "
                          "nachsehen."))
            sitzung = (wort, klasse)
            teile.append(
                f'<div class="karte"><h2>{_e(wort)} '
                f'<span class="badge {klasse}">{_e(zustand)}</span></h2>'
                f'<p>{_e(erklaerung)}</p>' +
                _paar_tabelle([
                    ("Nummer", s.get("phone") or "—"),
                    ("Name im Profil", s.get("pushName") or "—"),
                    ("Verbunden seit", _wa_zeit(s.get("connectedAt"))),
                    ("Zuletzt aktiv", _wa_zeit(s.get("lastActive"))),
                    ("Engine geladen", "ja" if s.get("engineLoaded") else "nein"),
                ]) + '</div>')

    # WhatsApp verbinden (29.09.2026): Selbstbedienung statt Handarbeit.
    kopplung_html, kopplung_wartet = _wa_kopplung_block(sitzung[1] == "gut")
    teile.append(kopplung_html)

    # Der Weg vom Handy in die Datenbank — aus der Datenbank selbst
    # beantwortet (29.08.2026). Der Webhook-Endpunkt von OpenWA verlangt
    # OPERATOR (gemessen: 403 mit dem Nur-Lese-Schluessel), und die
    # Registerzeile saehe ohnehin nur, DASS ein Haken eingetragen ist.
    # „Wann kam zuletzt wirklich etwas an?" belegt die ganze Kette:
    # Handy -> OpenWA -> Webhook -> sales-inbox -> activities.
    teile.append("<h2>Weg in den Posteingang</h2>")
    try:
        letzte = server._q(
            "select max(created_at) wann from activities "
            "where type = 'kundenantwort'")[0]["wann"]
    except Exception:
        letzte = None
        teile.append('<p class="meta">Datenbank gerade nicht lesbar.</p>')
    if letzte:
        stunden = (server._q("select extract(epoch from (now() - %s))/3600 h",
                             (letzte,))[0]["h"] or 0)
        satz = (f'Letzte eingegangene Kundennachricht: '
                f'<b>{_e(_zeit(letzte))}</b> (vor {stunden:.1f} h).')
        if stunden > 48:
            teile.append(f'<div class="warnung">{satz} Das ist lange — wenn '
                         f'du sicher bist, dass jemand geschrieben hat, '
                         f'stimmt am Weg etwas nicht.</div>')
        else:
            teile.append(f"<p>{satz} Die Kette bis in die Datenbank "
                         f"funktioniert.</p>")
    elif letzte is None:
        teile.append('<div class="warnung">Es ist noch NIE eine '
                     'Kundennachricht angekommen — der Weg vom Handy in den '
                     'Posteingang ist unbewiesen.</div>')

    teile.append(_wa_karten_und_kette(sitzung, fehler, letzte))

    origin = _dashboard_origin()
    if origin:
        # Das Dashboard direkt hier (Betreiber-Wunsch 02.09.2026). Es laeuft
        # unter seiner eigenen HTTPS-Adresse und laesst sich einbetten,
        # weil OpenWA (Patch 0002) diese Origin als frame-ancestor kennt.
        # Der Schluessel, den es braucht, wird IM Dashboard eingegeben und
        # bleibt im Browser des Betreibers — sales-ui sieht ihn nie, die
        # T5a-Grenze steht. Kein Meta-Refresh: der Rahmen wuerde jede
        # Minute neu laden, und das Dashboard aktualisiert sich selbst.
        teile.append(
            f'<h2>OpenWA</h2>'
            f'<iframe class="dashboard" src="{_e(OPENWA_DASHBOARD_URL)}" '
            f'title="OpenWA-Oberfläche" referrerpolicy="no-referrer"></iframe>'
            f'<p class="meta">Einmal mit dem OpenWA-Schlüssel anmelden — '
            f'die Anmeldung bleibt auf diesem Gerät erhalten. '
            f'<a href="{_e(OPENWA_DASHBOARD_URL)}" target="_blank" '
            f'rel="noreferrer">In eigenem Tab öffnen &rarr;</a></p>')
        antwort = _seite("WhatsApp", "".join(teile))
        antwort.headers["Content-Security-Policy"] = _csp_mit_rahmen(origin)
        return antwort
    teile.append(
        f'<h2>Koppeln und Neustarten</h2>'
        f'<p>Diese Seite <b>liest nur</b>. Zum Koppeln, Neustarten oder '
        f'Abmelden geht es in die OpenWA-Oberfläche — dort ist ein '
        f'Schlüssel nötig, der senden darf, und der gehört bewusst nicht '
        f'in diese Anzeige (sonst ließe sich die Freigabe umgehen).</p>'
        f'<p><a href="{_e(OPENWA_DASHBOARD_URL)}" target="_blank" '
        f'rel="noreferrer">OpenWA-Oberfläche öffnen &rarr;</a></p>')
    # Waehrend der Kopplung alle 3 s: ein QR-Code gilt nur ~20 s, und der
    # Wirt schreibt jeden neuen sofort in die Zeile.
    return _seite("WhatsApp", "".join(teile),
                  refresh=3 if kopplung_wartet else 60)


# Nur ein PNG als Data-URL in Base64 — alles andere (Anfuehrungszeichen,
# Skript, fremde Adresse) wird nicht eingebettet. Die Zeile schreibt zwar
# nur der Wirt, aber die Laden-Rolle darf ebenfalls einfuegen.
_QR_MUSTER = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/]+={0,2}$")


def _wa_kopplung_block(verbunden: bool) -> tuple[str, bool]:
    """Knopf, Wartehinweis oder QR-Code — je nach juengster Anfrage.
    Gibt (html, wartet) zurueck; `wartet` schaltet das schnelle Neuladen."""
    if verbunden:
        return "", False
    knopf = (f'<form method="post" action="/whatsapp/verbinden">'
             f'<input type="hidden" name="csrf" value="{_e(CSRF_TOKEN)}">'
             f'<button class="primaer" type="submit">WhatsApp verbinden'
             f'</button></form>')
    zeilen = server._q("select status, qr, fehler from whatsapp_kopplung "
                       "order by erstellt_am desc limit 1")
    z = zeilen[0] if zeilen else None
    if z and z["status"] == "angefordert":
        return ('<div class="karte"><h2>WhatsApp verbinden</h2>'
                '<p>Wird vorbereitet … der QR-Code erscheint hier gleich.'
                '</p></div>'), True
    if z and z["status"] == "qr":
        qr = str(z["qr"] or "")
        bild = (f'<img class="qr" src="{_e(qr)}" alt="QR-Code zum Koppeln" '
                f'width="264" height="264">' if _QR_MUSTER.match(qr) else
                '<p class="meta">Der QR-Code kommt gleich …</p>')
        return ('<div class="karte"><h2>WhatsApp verbinden</h2>'
                '<ol class="schritte"><li>WhatsApp auf dem Handy öffnen.</li>'
                '<li>Einstellungen → <b>Verknüpfte Geräte</b> → '
                '„Gerät hinzufügen".</li>'
                '<li>Diesen Code scannen. Er erneuert sich von selbst.</li>'
                f'</ol>{bild}</div>'), True
    if z and z["status"] == "verbunden":
        return ('<div class="karte"><h2>WhatsApp ist verbunden</h2>'
                '<p>Nachrichten kommen ab jetzt im Posteingang an.</p>'
                '</div>'), False
    grund = ""
    if z and z["status"] in ("abgelaufen", "fehler"):
        grund = (f'<p class="warnung">{_e(z["fehler"] or "Das hat nicht '
                 f'geklappt.")} Einfach noch einmal versuchen.</p>')
    return ('<div class="karte"><h2>WhatsApp verbinden</h2>'
            '<p>Verbinde die WhatsApp-Nummer, über die dieser Laden '
            'schreibt. Du brauchst dafür nur dein Handy.</p>'
            f'{grund}{knopf}</div>'), False


@_gesichert_seite
async def aktion_whatsapp_verbinden(request):
    """Legt eine Anfrage an; hoechstens eine offene (Teilindex), ein
    Doppelklick legt also nichts doppelt an."""
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    server._q("insert into whatsapp_kopplung default values "
              "on conflict do nothing")
    return RedirectResponse("/whatsapp", status_code=303)


@_gesichert_seite
async def pipeline(request):
    """Die Spaltensicht: alle aktiven Kontakte nach Stufe, mit Wartezeit
    seit dem letzten Kontakt in beide Richtungen."""
    # _archiv_sql statt einer handgeschriebenen Bedingung (29.08.2026):
    # `enrichment->>'_archiviert'` liefert das OBJEKT als Text, ::bool
    # scheitert bzw. wird null — die Pipeline zaehlte damit archivierte
    # Kontakte mit (34 statt 28, im Browser gemessen). Filter und Anzeige
    # duerfen nie verschiedene Regeln benutzen; genau davor warnt der
    # Kommentar an _archiv_sql.
    zeilen = server._q(
        "select l.id, l.name, l.status, "
        "  (select max(a.created_at) from activities a "
        "   where a.lead_id = l.id and a.type in "
        "   ('kundenantwort', 'nachricht_ausgehend', 'versand')) letzter "
        "from leads l "
        "where not " + server._archiv_sql("l.enrichment") +
        " order by l.name")
    spalten = {s: [] for s in server.PIPELINE_STUFEN}
    for z in zeilen:
        spalten[server._stufe_lesen(z["status"])].append(z)
    # Nur der FLUSS (neu … termin) — acht Spalten ueberragten jeden
    # Bildschirm und die Seite wirkte abgeschnitten (Betreiber-Feedback
    # 01.09.2026). Die Endzustaende stehen auf /ergebnisse.
    aktive = server.PIPELINE_STUFEN[:-2]
    abgeschlossen = sum(len(spalten[s]) for s in server.PIPELINE_STUFEN[-2:])
    teile = [f'<p class="meta">Stufe setzen: auf der Kontaktseite. '
             f'Jeder Wechsel steht mit Begründung im Protokoll. '
             f'Abgeschlossene ({abgeschlossen}) stehen unter '
             f'<a href="/ergebnisse">Ergebnisse</a>.</p>',
             '<div class="spalten">']
    for stufe in aktive:
        karten = "".join(
            f'<div class="karte"><a href="/kontakte/{_e(str(k["id"]))}">'
            f'{_e(k["name"] or "(ohne Namen)")}</a>'
            f'<div class="meta">{_e(_zeit(k["letzter"])) if k["letzter"] else "noch kein Kontakt"}'
            f'</div></div>'
            for k in spalten[stufe])
        teile.append(
            f'<div class="spalte"><h2>{_e(stufe)} '
            f'({len(spalten[stufe])})</h2>{karten or "<p class=meta>—</p>"}'
            f'</div>')
    teile.append("</div>")
    return _seite("Pipeline", "".join(teile))


# Toleranz beim Paaren: dieselbe Buchung kann in zwei Quellen um ein paar
# Minuten auseinanderliegen (Rundung beim Import). Fuenf Minuten sind eng
# genug, dass zwei ECHTE Termine nicht verschmelzen — der Betreiber hat
# ausdruecklich entschieden, dass beide Quellen Wahrheit bleiben und
# Zweifelsfaelle im Digest geklaert werden, nicht hier.
PAAR_TOLERANZ_MIN = 5


def _termine_paaren(eigene, importierte):
    """Termine aus beiden Quellen zu einer Liste verschmelzen.

    Verschmolzen wird AUSSCHLIESSLICH quellenuebergreifend: jeder eigene
    Termin sucht sich hoechstens einen passenden importierten Partner —
    nie einen zweiten eigenen. Ohne diese Grenze wuerden zwei ECHTE
    Termine derselben Quelle (z.B. desselben Kontakts, wenige Minuten
    auseinander) faelschlich zu einer Zeile verschmelzen. Deshalb wird
    hier bewusst ueber `eigene` iteriert und `importierte` als Vorrat
    behandelt, aus dem jeder Partner nur einmal gezogen werden kann —
    die Regel steht damit im Kontrollfluss, nicht in einem Guard.

    Verschmolzen wird NICHT der Inhalt: jeder Eintrag behaelt beide
    Ortsangaben und nennt seine Quellen. Die Entscheidung, welche Fassung
    stimmt, trifft der Betreiber im Digest.
    """
    frei = list(importierte)
    ergebnis = []
    for eigen in eigene:
        neu = dict(eigen)
        neu["quellen"] = [eigen.get("quelle", "?")]
        treffer = next((i for i, imp in enumerate(frei)
                        if _gleicher_termin(neu, imp)), None)
        if treffer is not None:
            partner = frei.pop(treffer)
            neu["quellen"].append(partner.get("quelle", "?"))
            if not neu.get("ort") and partner.get("ort"):
                neu["ort"] = partner["ort"]
            elif partner.get("ort") and partner["ort"] != neu.get("ort"):
                neu.setdefault("abweichend", {})["ort"] = partner["ort"]
        ergebnis.append(neu)
    for imp in frei:
        neu = dict(imp)
        neu["quellen"] = [imp.get("quelle", "?")]
        ergebnis.append(neu)
    return ergebnis


def _gleicher_termin(a, b) -> bool:
    """Gleicher Kontakt, gleiche Startzeit (+/- Toleranz), aehnlicher Titel."""
    if a.get("lead_id") and b.get("lead_id") and a["lead_id"] != b["lead_id"]:
        return False
    beginn_a, beginn_b = a.get("beginn"), b.get("beginn")
    if beginn_a is None or beginn_b is None:
        return False
    if (beginn_a.tzinfo is None) != (beginn_b.tzinfo is None):
        # Ein naiver und ein zonenbehafteter Zeitpunkt lassen sich nicht
        # subtrahieren (TypeError) — ohne Zone ist der Vergleich ohnehin
        # nicht aussagekraeftig, also lieber kein Treffer als ein Absturz,
        # der die ganze Kalenderseite mitreisst.
        return False
    abstand = abs((beginn_a - beginn_b).total_seconds())
    if abstand > PAAR_TOLERANZ_MIN * 60:
        return False
    titel_a = str(a.get("titel") or "").strip().lower()
    titel_b = str(b.get("titel") or "").strip().lower()
    # Gepaart wird, wenn die Titel gleich sind oder der KUERZERE
    # vollstaendig Praefix des laengeren ist (z.B. Store "VibeMind
    # Gespraech (Scalosoft)" gegen CalDAV "VibeMind Gespraech"). Eine feste
    # Zeichenzahl waere hier die falsche Grenze: "Beratungsgespraech am
    # Telefon mit Herrn Schmidt" und "...mit Frau Weber" teilen sich mehr
    # als zwanzig Zeichen Anfang, sind aber zwei verschiedene Termine —
    # keiner der beiden ist vollstaendiger Praefix des anderen.
    return titel_a.startswith(titel_b) or titel_b.startswith(titel_a)


def _beginn_aus_payload(payload):
    """`datum`+`uhrzeit` aus dem Payload zu einem bewussten Zeitpunkt.

    Die Strings im Payload sind ORTSZEIT — so hat der Betreiber sie
    diktiert und so stehen sie in der .ics. Sie als UTC zu lesen waere
    derselbe Zwei-Stunden-Fehler noch einmal, nur an anderer Stelle.
    """
    tag = str((payload or {}).get("datum") or "")
    zeit = str((payload or {}).get("uhrzeit") or "")
    if not tag:
        return None
    try:
        roh = datetime.fromisoformat(f"{tag}T{zeit or '00:00'}")
    except ValueError:
        return None
    return roh.replace(tzinfo=ZEITZONE) if ZEITZONE else roh


@_gesichert_seite
async def kalender_seite(request):
    """Alle Termine an EINER Stelle (01.09.2026, Betreiber-Wunsch).

    Drei Quellen, absteigende Verlaesslichkeit: die Termin-Aktivitaeten
    aus der eigenen Datenbank (mit Kontaktbezug), die offenen
    Wiedervorlagen — und, wenn CalDAV konfiguriert ist, die Eintraege
    aus dem echten Kalender. Der CalDAV-Kalender hat kein Web-UI, das
    man einbetten koennte; seine Termine werden deshalb gelesen. Faellt
    er aus, steht der Rest trotzdem da.
    """
    heute = date.today()
    zeilen = server._q(
        "select a.payload, a.created_at, l.id as lead_id, l.name "
        "from activities a left join leads l on l.id = a.lead_id "
        "where a.type = 'termin' order by a.created_at desc limit 200")
    # Abgesagte fallen aus der Ansicht (01.09.2026) — sie stehen unten in
    # ihrem eigenen Abschnitt, damit die Absage nachvollziehbar bleibt.
    abgesagt = {str((z["payload"] or {}).get("uid") or ""): z["payload"] or {}
                for z in server._q(
                    "select payload from activities "
                    " where type = 'termin_abgesagt' order by created_at")}
    zeilen = [z for z in zeilen
              if str((z["payload"] or {}).get("uid") or "") not in abgesagt
              or not (z["payload"] or {}).get("uid")]
    # Der echte Kalender wird schon hier gelesen (statt erst beim Gitter
    # weiter unten), damit seine Termine VOR dem Aufbau von kommend/vergangen
    # mit den eigenen gepaart werden koennen (Aufgabe 4).
    # Team-Sicht (Aufgabe 6, Spec §2.5): server.belegungen() statt nur des
    # eigenen `kalender.termine_lesen()` — die Liste traegt jetzt auch die
    # Termine verbundener Kollegen-Kalender, jeder Eintrag mit dem Namen
    # seiner Quelle (server.EIGENE_QUELLE fuer den eigenen). Schweigt eine
    # Quelle, steht sie in `luecken` und wird unten als Hinweis genannt statt
    # stillschweigend als frei zu gelten (Spec §2.2).
    eintraege, luecken = server.belegungen()

    # Aufgabe 4: dieselbe Buchung steht oft in beiden Quellen — einmal im
    # eigenen Store (mit Kontaktbezug), einmal im CalDAV-Import. Betreiber-
    # Entscheidung: nicht automatisch zusammenfuehren, beide Quellen bleiben
    # Wahrheit. `_termine_paaren` erkennt nur, WELCHE Zeilen zusammengehoeren;
    # die Anzeige unten zeigt sie als einen Eintrag mit dem Hinweis
    # „zwei Quellen" und beiden abweichenden Ortsangaben.
    eigene_normalisiert = []
    for i, z in enumerate(zeilen):
        last = z["payload"] or {}
        beginn = _beginn_aus_payload(last)
        if beginn is None:
            continue
        eigene_normalisiert.append({
            "_index": i, "titel": str(last.get("thema") or ""),
            "beginn": beginn, "ort": str(last.get("ort") or ""),
            "quelle": "store", "lead_id": z["lead_id"]})
    # Aufgabe 6 Fix-Runde 2 (Pruefung, WICHTIG 1): NUR der eigene Kalender
    # (server.EIGENE_QUELLE) nimmt an der Paarung teil, nicht `eintraege` in
    # voller Breite. "Zwei Quellen" bedeutet: DIESELBE Buchung steht im CRM
    # UND im eigenen Kalender des Betreibers — nicht, dass ein CRM-Termin
    # zufaellig aehnlich heisst und aehnlich liegt wie EIN KOLLEGENTERMIN.
    # Wuerden Kollegen-Eintraege hier mitgepaart, koennte `_termine_paaren`
    # Ivans Termin mit einem fremden CRM-Termin verschmelzen — er verschwaende
    # als eigene Zeile, und genau die Information, fuer die die Team-Sicht
    # gebaut wurde (dass Ivan zu dieser Zeit belegt ist), ginge verloren.
    importierte_normalisiert = [
        {"titel": t["titel"], "beginn": t["beginn"], "ort": t["ort"],
         "quelle": "caldav"} for t in eintraege
        if t["quelle"] == server.EIGENE_QUELLE]
    paar_je_index = {p["_index"]: p
                     for p in _termine_paaren(eigene_normalisiert,
                                              importierte_normalisiert)
                     if "_index" in p}

    kommend, vergangen, ohne_datum = [], [], []
    # Doppelt belegte Zeitfenster sichtbar machen (01.09.2026 gefunden:
    # zwei Termine mit derselben Person am selben Tag um dieselbe Zeit).
    # Das ist etwas ANDERES als die Quellen-Paarung oben: hier sind es zwei
    # verschiedene Termine zur selben Zeit, dort dieselbe Buchung aus zwei
    # Quellen — die Erkennung bleibt deshalb unabhaengig davon.
    belegung = {}
    for z in zeilen:
        last = z["payload"] or {}
        tag = str(last.get("datum") or "")
        if tag:
            belegung[(tag, str(last.get("uhrzeit") or ""))] = \
                belegung.get((tag, str(last.get("uhrzeit") or "")), 0) + 1
    for i, z in enumerate(zeilen):
        last = z["payload"] or {}
        tag = str(last.get("datum") or "")
        zeit = str(last.get("uhrzeit") or "")
        kontakt = (f'<a href="/kontakte/{_e(str(z["lead_id"]))}">'
                   f'{_e(z["name"] or "(ohne Kontakt)")}</a>'
                   if z["lead_id"] else _e(z["name"] or "—"))
        if not tag:
            # Eine Termin-Notiz ohne Datum ist eine OFFENE ANFRAGE
            # („Donnerstag 16 Uhr — welcher?"), kein vergangener Termin.
            # Sie stand als leere Zeile unter „Vergangen".
            voll = str(last.get("inhalt") or last.get("thema") or "")
            ohne_datum.append([
                _zeit(z["created_at"]), kontakt,
                f'<span title="{_e(voll)}">{_e(_kurz(voll, 160))}</span>'])
            continue
        marke = ('<span class="badge achtung">Doppelt belegt</span> '
                 if belegung.get((tag, zeit), 0) > 1 else "")
        paar = paar_je_index.get(i)
        quellen_marke = (
            '<span class="badge achtung" title="Dieser Termin steht in zwei '
            'Quellen — der Assistent klärt im Digest, welche Fassung '
            'stimmt.">zwei Quellen</span> '
            if paar and len(paar.get("quellen", [])) > 1 else "")
        # Der Ort wird aus dem GEPAARTEN Eintrag gelesen, nicht mehr aus der
        # rohen Zeile: ist der eigene Ort leer und nur der importierte
        # gesetzt, traegt `paar["ort"]` bereits den importierten Wert (der
        # Merge in _termine_paaren hat ihn uebernommen) — `last.get("ort")`
        # waere hier weiterhin leer und haette die einzige Ortsangabe
        # stillschweigend verworfen.
        basis = paar if paar is not None else {"ort": last.get("ort")}
        ort_basis_voll = str(basis.get("ort") or "")
        ort_abweichend = basis.get("abweichend", {}).get("ort")
        ort_basis_html = (f'<span title="{_e(ort_basis_voll)}">'
                          f'{_e(_kurz(ort_basis_voll, 60))}</span>')
        ort_html = (f'{ort_basis_html} / <span title="{_e(str(ort_abweichend))}">'
                   f'{_e(_kurz(str(ort_abweichend), 60))}</span>'
                   if ort_abweichend else ort_basis_html)
        thema_voll = str(last.get("thema") or "")
        eintrag = [
            _e(tag_lesbar(tag)), _e(zeit), kontakt,
            marke + quellen_marke +
            f'<span title="{_e(thema_voll)}">{_e(_kurz(thema_voll, 80))}</span>',
            ort_html,
            _termin_aktionen(str(z["lead_id"] or ""),
                             str(last.get("uid") or ""), tag, zeit)]
        (kommend if tag >= heute.isoformat() else vergangen).append(
            (tag + zeit, eintrag))
    kommend.sort(key=lambda p: p[0])
    vergangen.sort(key=lambda p: p[0], reverse=True)

    # --- Das Gitter (01.09.2026): ein Kalender sieht aus wie ein Kalender.
    monat = _monat_lesen(request.query_params.get("monat"), heute)
    teile = [_monatsgitter(monat, zeilen, eintraege)]

    kopf = ["Datum", "Zeit", "Kontakt", "Thema", "Ort", "Ändern"]
    teile.append(f"<h2>Kommende Termine ({len(kommend)})</h2>")
    teile.append(_tabelle(kopf, [e for _, e in kommend]) if kommend
                 else "<p>Kein Termin steht an.</p>")
    # W5 (Schlusspruefung 13.09.2026): die schmale Rolle `kalender` darf
    # /kalender sehen (sie soll nur Termine abgleichen) — Kundenname, Thema
    # und Ort AN einem Termin sind dafuer gewollt (Spec §4, Betreiber-Wahl
    # "Alles — Kunde, Thema, Ort"). "Ohne festes Datum" ist aber der ROHE
    # eingegangene Anfragetext (`inhalt`), und Wiedervorlagen samt Notiz
    # sind gar keine Termindaten — genau der Kundenstamm, vor dem diese
    # Rolle bewusst ferngehalten wird (Spec §2.7). Ohne diese Ausblendung
    # kaeme die schmale Rolle ueber den EINEN Pfad, den sie betreten darf,
    # scheibchenweise doch an beides.
    schmale_rolle = _AKTIVE_ROLLE.get() == "kalender"
    if ohne_datum and not schmale_rolle:
        teile.append(f"<h2>Ohne festes Datum ({len(ohne_datum)})</h2>")
        teile.append('<p class="meta">Terminanfragen, bei denen der Tag '
                     'noch nicht feststeht.</p>')
        teile.append(_tabelle(["Notiert", "Kontakt", "Worum es geht"],
                              ohne_datum))

    if not schmale_rolle:
        offene = _offene_wiedervorlagen()
        teile.append(f"<h2>Offene Wiedervorlagen ({len(offene)})</h2>")
        teile.append(_wiedervorlagen_tabelle(offene, mit_kontakt=True)
                     if offene else "<p>Nichts liegt wieder vor.</p>")

    # Der echte Kalender — nur lesend, und ein Ausfall kostet nur diesen
    # Abschnitt. (Oben im Gitter stehen dieselben Termine.)
    # Team-Sicht (Aufgabe 6, Spec §2.5): eine Liste ueber ALLE aktiven
    # Quellen — den eigenen Kalender (server.EIGENE_QUELLE) UND jeden
    # verbundenen Kollegen-Kalender —, jeder Eintrag mit dem Namen seiner
    # Quelle als eigenes Element neben Zeit und Titel: schlicht, wie heute
    # die Marke "zwei Quellen". Farbliche Unterscheidung und Wochenansicht
    # sind Stufe 4 der Oberflaechen-Ueberarbeitung (Spec §2.5) — hier
    # bewusst nicht vorgezogen, damit dort nichts doppelt gebaut wird.
    teile.append(f"<h2>Kalender ({len(eintraege)})</h2>")
    if luecken:
        # Die Huerde steht UEBER der Liste: eine Quelle, die schweigt,
        # gilt sonst faelschlich als frei (Spec §2.2) — dieselbe Regel, die
        # `server.belegungen()` schon fuer den Chat (Aufgabe 3/4) durchsetzt,
        # hier fuer die Oberflaeche. Eine Luecke, die niemand sieht, ist
        # schlimmer als keine Sicht.
        wer = "; ".join(f"{_e(l['quelle'])} ({_e(l['grund'])})"
                        for l in luecken)
        teile.append(f'<p class="hinweis">Nicht abrufbar: {wer}. Dort '
                     f'können Termine liegen, die hier fehlen.</p>')
    if (not eintraege and not luecken and not kalender.konfiguration()[0]
            and not server.kalenderquellen_lesen()):
        # Ehrlich statt leer (Betreiber-Frage nach dem entfernten
        # CALDAV_URL-Tor, Aufgabe 6 Fix-Runde 1): „nichts konfiguriert" sah
        # sonst genauso aus wie „alles konfiguriert, gerade nur nichts los"
        # — die Seite WEISS, dass keine einzige Quelle angeschlossen ist,
        # und darf das nicht verschweigen. `kalenderquellen_lesen()` liefert
        # die geheime Adresse mit, hier wird nur ihre Anzahl (leer/nicht
        # leer) benutzt, nie angezeigt.
        teile.append('<p class="meta">Kein Kalender verbunden — weder der '
                     'eigene (CALDAV_URL in der .env) noch ein '
                     'Kollegen-Kalender (siehe <a href="/team/kalender">'
                     'Kalender verbinden</a>).</p>')
    elif not eintraege:
        teile.append('<p class="meta">Keine Einträge im Zeitfenster.</p>')
    else:
        teile.append(_tabelle(
            ["Wann", "Titel", "Ort", "Quelle"],
            [[_zeit(t["beginn"]), _e(t["titel"]), _e(t["ort"]),
              f'<span class="badge">{_e(t["quelle"])}</span>']
             for t in eintraege[:100]]))

    if vergangen:
        teile.append(f"<h2>Vergangen ({len(vergangen)})</h2>")
        teile.append(_tabelle(kopf, [e for _, e in vergangen[:30]]))
    if abgesagt:
        teile.append(f"<h2>Abgesagt ({len(abgesagt)})</h2>")
        abgesagt_zeilen = []
        for a in list(abgesagt.values())[:30]:
            thema_voll = str(a.get("thema") or "")
            grund_voll = str(a.get("grund") or "")
            abgesagt_zeilen.append([
                _e(tag_lesbar(str(a.get("datum") or ""))),
                _e(str(a.get("uhrzeit") or "")),
                f'<span title="{_e(thema_voll)}">{_e(_kurz(thema_voll, 60))}</span>',
                f'<span title="{_e(grund_voll)}">{_e(_kurz(grund_voll, 80))}</span>'])
        teile.append(_tabelle(
            ["Datum", "Zeit", "Thema", "Grund"], abgesagt_zeilen))
    return _seite("Kalender", "".join(teile))


def _termin_aktionen(lead_id: str, uid: str, tag: str, zeit: str) -> str:
    """Absagen und Verschieben — beide ueber DIESELBEN Werkzeuge wie der
    Chat (server.termin_absagen / termin_verschieben). Die Oberflaeche
    baut keinen zweiten Schreibweg; dasselbe Muster wie bei den
    Freigaben."""
    if not (lead_id and uid):
        # Alt-Termine ohne uid (vor dem 01.09.2026) lassen sich nicht
        # eindeutig adressieren — lieber kein Knopf als der falsche.
        return '<span class="meta">—</span>'
    verborgen = (f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
                 f'<input type="hidden" name="uid" value="{_e(uid)}">'
                 f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">')
    return (
        f'<form class="aktion" method="post" action="/kalender/verschieben">'
        f'{verborgen}'
        f'<input type="date" name="datum" value="{_e(tag)}" required>'
        f'<input type="time" name="uhrzeit" value="{_e(zeit)}" required>'
        f'<button>Verschieben</button></form>'
        f'<form class="aktion gefahr" method="post" '
        f'action="/kalender/absagen">{verborgen}'
        f'<input name="grund" placeholder="Grund" required>'
        f'<button class="gefahr">Absagen</button></form>')


@_gesichert_seite
async def aktion_termin_absagen(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    antwort = json.loads(server.termin_absagen(
        str(form.get("lead_id") or ""), str(form.get("uid") or ""),
        str(form.get("grund") or "")))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht abgesagt", _e(antwort["fehler"]))
    return RedirectResponse("/kalender", status_code=303)


@_gesichert_seite
async def aktion_termin_verschieben(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    antwort = json.loads(server.termin_verschieben(
        str(form.get("lead_id") or ""), str(form.get("uid") or ""),
        str(form.get("datum") or ""), str(form.get("uhrzeit") or "")))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht verschoben", _e(antwort["fehler"]))
    return RedirectResponse("/kalender", status_code=303)


# --- Team-Kalender: der Kollege verbindet selbst (Task 5, Spec §2.7) -------
#
# Klickwege je Anbieter. Ein Text fuer alle waere hier der Fehler: wer
# Google nutzt, soll nicht durch vier Absaetze zu Apple lesen muessen.
# (Anbieter, Direktlink zu der Einstellungsseite, auf der die Adresse steht,
# Klickweg ab dort). Der Link spart das Suchen im Menue — die haeufigste
# Stelle, an der Kollegen haengen blieben (29.09.2026).
_ANBIETER_WEGE = (
    ("Google Kalender",
     "https://calendar.google.com/calendar/r/settings",
     "Links unter „Einstellungen für meine Kalender“ deinen Kalender "
     "wählen → „Kalender integrieren“ → <b>Geheime Adresse im iCal-Format</b> "
     "kopieren (nicht die öffentliche Adresse)"),
    ("Apple iCloud",
     "https://www.icloud.com/calendar",
     "Neben deinem Kalender auf das Teilen-Symbol → „Öffentlicher Kalender“ "
     "einschalten → Adresse kopieren"),
    ("Outlook / Microsoft 365",
     "https://outlook.live.com/calendar/0/options/calendar/SharedCalendars",
     "Unter „Kalender veröffentlichen“ deinen Kalender und „Kann alle "
     "Details anzeigen“ wählen → „Veröffentlichen“ → <b>ICS-Link</b> kopieren. "
     "Mit Firmenkonto: dieselbe Seite unter outlook.office.com"),
)


# --- Laden anlegen: nur Rolle freigeben im Basis-Laden (Task 2, Spec §2) ---
_LADEN_NAMEN_MUSTER = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def _admin_auftrag_ergebnis_text(zeile) -> str:
    """Menschenlesbare Zusammenfassung eines Auftrags — nie mehr behaupten,
    als 'status' hergibt (siehe Spec §2.4: der Wirt schreibt 'fehler', nie
    'erfolg', wenn nur ein Schritt fehlt; hier wird das nur ANGEZEIGT).
    Verzweigt zusaetzlich auf `zeile["art"]`, weil 'erfolg' bei den beiden
    Auftragsarten voellig verschiedene Formen von `ergebnis` traegt."""
    if zeile["status"] == "offen":
        return "wartet auf den Wirt (bis zu 20 Sekunden)"
    if zeile["status"] == "laeuft":
        return ("wird gerade verschickt …" if zeile["art"] == "tailscale_einladen"
                 else "wird gerade angelegt …")
    # K1 (Schlusspruefung des vorigen Untervorhabens): server.pool laeuft
    # mit psycopg3/dict_row — eine jsonb-Spalte kommt bereits als
    # Python-dict zurueck, nicht als String. json.loads() darauf wirft
    # TypeError.
    info = zeile["ergebnis"] or {}
    if zeile["art"] == "tailscale_einladen":
        if zeile["status"] == "fehler":
            return f"FEHLER — {_e(zeile['fehler'] or 'kein Grund vermerkt')}"
        link = info.get("inviteUrl")
        zusatz = f" Link zum Weitergeben: {_e(link)}" if link else ""
        return (f"Einladung verschickt.{zusatz} Die Zugriffsregel für den "
                 f"neuen Menschen bleibt weiterhin Handarbeit, siehe Runbook "
                 f"Abschnitt 6.")
    if zeile["status"] == "fehler":
        erledigt = ", ".join(info.get("erledigt", [])) or "nichts"
        grund = zeile["fehler"] or "kein Grund vermerkt"
        return f"FEHLER — erledigt: {_e(erledigt)}. {_e(grund)}"
    port = _e(str(info.get("port_serve", "?")))
    hinweis = _e(info.get("hinweis", ""))
    willkommen = info.get("willkommen")
    if willkommen:
        return (f"Willkommensmail an {_e(willkommen.get('an', '?'))}: "
                f"{_e(willkommen.get('status', '?'))}. "
                f"Serve-Port: {port}. {hinweis}")
    return (f"Wegwerf-Passwort: {_e(info.get('passwort', '?'))} — "
            f"Serve-Port: {port}. {hinweis}")


@_gesichert_seite
async def laden_anlegen_seite(request):
    """Einen neuen Laden anlegen. Erreichbar nur fuer Rolle `freigeben` im
    Basis-Laden (_pfad_erlaubt) — kein zweiter Check hier noetig, die
    Middleware hat den Pfad bereits verweigert, wenn wir hier ankommen."""
    zeilen = server._q(
        "select art, name, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'laden_anlegen' "
        "order by erstellt_am desc limit 10")
    wartet = any(z["status"] in ("offen", "laeuft") for z in zeilen)
    if zeilen:
        tabelle = _tabelle(
            ["Name", "Status", "Ergebnis"],
            [[_e(z["name"]), _e(z["status"]),
              _admin_auftrag_ergebnis_text(z)] for z in zeilen])
    else:
        tabelle = "<p>Noch kein Auftrag.</p>"
    rumpf = (
        '<form method="post" action="/team/laden-anlegen/anfordern">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        '<label>Name des neuen Ladens<br>'
        '<input type="text" name="name" pattern="[a-z][a-z0-9_]{0,30}" '
        'required placeholder="z. B. lena"></label> '
        '<label>Private E-Mail-Adresse (optional — bekommt eine '
        'Willkommensmail mit Link zum Passwort-Setzen)<br>'
        '<input type="email" name="email" '
        'placeholder="z. B. lena@example.com"></label> '
        '<button type="submit">Anlegen</button>'
        '</form>'
        f'<h2>Bisherige Aufträge</h2>{tabelle}')
    return _seite("Laden anlegen", rumpf, refresh=5 if wartet else None)


@_gesichert_seite
async def aktion_laden_anlegen(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")
    name = str(form.get("name") or "").strip()
    if not _LADEN_NAMEN_MUSTER.fullmatch(name):
        return _fehlerseite(
            400, "Ungültiger Name",
            "Ein Ladenname besteht aus Kleinbuchstaben, Ziffern und "
            "Unterstrich, beginnt mit einem Buchstaben, höchstens 31 "
            "Zeichen. Nichts wurde angelegt.")
    if name in ("sales", "test"):
        return _fehlerseite(
            400, "Reservierter Name",
            f"'{name}' ist reserviert (Basis-Laden bzw. Test-Schema) und "
            "kann nicht als Ladenname verwendet werden. Nichts wurde angelegt.")
    email = None
    roh = str(form.get("email") or "").strip()
    if roh:
        email, fehler = mailadresse.pruefe(roh)
        if fehler:
            return _fehlerseite(
                400, "Ungültige E-Mail-Adresse",
                f"{fehler}. Nichts wurde angelegt.")
    server._q(
        "insert into admin_auftraege (art, name, email, angefordert_von) "
        "values ('laden_anlegen', %s, %s, %s) returning id",
        (name, email, _ui_akteur(request)))
    return RedirectResponse("/team/laden-anlegen", status_code=303)


@_gesichert_seite
async def tailscale_einladen_seite(request):
    """Einen neuen Menschen zum Tailnet einladen. Erreichbar nur fuer Rolle
    `freigeben` im Basis-Laden (_pfad_erlaubt) — kein zweiter Check hier
    noetig, die Middleware hat den Pfad bereits verweigert, wenn wir hier
    ankommen. Automatisiert wird ausschliesslich die Einladung selbst —
    die Tailscale-Zugriffsregel bleibt Handarbeit (Spec §4)."""
    zeilen = server._q(
        "select art, email, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'tailscale_einladen' "
        "order by erstellt_am desc limit 10")
    wartet = any(z["status"] in ("offen", "laeuft") for z in zeilen)
    if zeilen:
        tabelle = _tabelle(
            ["E-Mail", "Status", "Ergebnis"],
            [[_e(z["email"]), _e(z["status"]),
              _admin_auftrag_ergebnis_text(z)] for z in zeilen])
    else:
        tabelle = "<p>Noch kein Auftrag.</p>"
    rumpf = (
        '<form method="post" action="/team/tailscale-einladen/anfordern">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        '<label>E-Mail-Adresse des neuen Menschen<br>'
        '<input type="email" name="email" required '
        'placeholder="z. B. kolleg@example.com"></label> '
        '<button type="submit">Einladen</button>'
        '</form>'
        f'<h2>Bisherige Einladungen</h2>{tabelle}')
    return _seite("Team-Mitglied einladen", rumpf, refresh=5 if wartet else None)


@_gesichert_seite
async def aktion_tailscale_einladen(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")
    email, fehler = mailadresse.pruefe(str(form.get("email") or ""))
    if fehler:
        return _fehlerseite(
            400, "Ungültige E-Mail-Adresse", f"{fehler}. Nichts wurde angefordert.")
    server._q(
        "insert into admin_auftraege (art, email, angefordert_von) "
        "values ('tailscale_einladen', %s, %s) returning id",
        (email, _ui_akteur(request)))
    return RedirectResponse("/team/tailscale-einladen", status_code=303)


@_gesichert_seite
async def team_kalender(request):
    """Die Seite, über die ein Kollege seinen Kalender verbindet."""
    zeilen = []
    for quelle in server.kalenderquellen_lesen(nur_aktive=False):
        stand = (f"zuletzt gelesen {_zeit(quelle['zuletzt_gelesen'])}"
                 if quelle["zuletzt_gelesen"] else "noch nicht gelesen")
        if quelle["letzter_fehler"]:
            stand += f" — {_e(quelle['letzter_fehler'])}"
        elif quelle["termine_zuletzt"] is not None:
            stand += f", {quelle['termine_zuletzt']} Termine"
        # Die Adresse steht hier NICHT (Spec §4).
        # W3 (Schlusspruefung 13.09.2026): kalenderquelle_entfernen() hatte
        # bisher keinen Aufrufer ausserhalb der Tests — setzte ein Kollege
        # seine Adresse beim Anbieter zurueck (den Widerruf, den diese Seite
        # ihm oben ausdruecklich anbietet), blieb die Zeile aktiv und schlug
        # dauerhaft fehl. Je aktiver Quelle ein Knopf, nach dem Muster der
        # uebrigen Aktionen (CSRF-Marke, einzelner POST, kein Bestaetigungs-
        # schritt — das Entfernen ist ein Gegen-Ereignis, kein Hard-Delete:
        # unter demselben Namen neu verbinden weckt die Zeile von selbst
        # wieder auf, siehe kalenderquelle_entfernen()s Docstring).
        aktion = (
            f'<form class="aktion gefahr" method="post" '
            f'action="/team/kalender/entfernen">'
            f'<input type="hidden" name="quelle_id" '
            f'value="{_e(str(quelle["id"]))}">'
            f'<input type="hidden" name="csrf" value="{_e(CSRF_TOKEN)}">'
            f'<button class="gefahr">Entfernen</button></form>'
            if quelle["aktiv"] else '<span class="meta">entfernt</span>')
        zeilen.append([_e(quelle["anzeigename"]), stand, aktion])
    tabelle = (_tabelle(["Name", "Stand", "Aktion"], zeilen) if zeilen else
               '<p class="meta">Noch kein Kalender verbunden.</p>')

    # Neuer Tab fuer die Anbieter-Seite: wer dort die Adresse kopiert, soll
    # hierher zurueckkommen, ohne diese Seite neu suchen zu muessen.
    wege = "".join(
        f'<details class="karte"><summary>{_e(name)}</summary>'
        f'<p><a href="{_e(link)}" target="_blank" rel="noopener noreferrer">'
        f'Einstellungen öffnen ↗</a></p><p class="meta">{weg}</p></details>'
        for name, link, weg in _ANBIETER_WEGE)

    # Vorbelegt mit dem angemeldeten Namen (ein Kollege mit Rolle
    # `kalender` verbindet fast immer seinen eigenen), aenderbar fuer den
    # Betreiber, der fuer jemanden verbindet. Der Sammelstempel ohne
    # Anmeldung ist kein Name und bleibt deshalb leer.
    akteur = _ui_akteur(request)
    vorbelegt = "" if akteur == "betreiber-ui" else akteur
    formular = (
        f'<form method="post" action="/team/kalender/verbinden">'
        f'<input type="hidden" name="csrf" value="{_e(CSRF_TOKEN)}">'
        f'<ol class="schritte">'
        f'<li><b>Anbieter wählen</b> und dort die geheime Adresse kopieren:'
        f'{wege}</li>'
        f'<li><label class="feld">Adresse hier einfügen'
        f'<input name="url" type="text" required autocomplete="off" '
        f'placeholder="https://…/basic.ics"></label></li>'
        f'<li><label class="feld">Wessen Kalender ist das?'
        f'<input name="name" type="text" required value="{_e(vorbelegt)}">'
        f'</label></li>'
        f'</ol>'
        f'<button class="primaer" type="submit">Verbinden und prüfen</button>'
        f'</form>')

    return _seite("Kalender verbinden",
                  '<p class="meta">Drei Schritte, dann wird sofort geprüft, '
                  'ob es klappt. Du kannst die Adresse bei deinem Anbieter '
                  'jederzeit zurücksetzen — dann endet der Zugriff sofort.</p>'
                  + formular + '<h2>Verbunden</h2>' + tabelle)


@_gesichert_seite
async def aktion_kalender_verbinden(request):
    """Adresse prüfen, dann erst speichern — nie umgekehrt.

    Die sofortige Rückmeldung ist der Kern von §2.7: der häufigste Fehler
    ist die öffentliche statt der geheimen Adresse, und ohne Prüfung merkt
    das niemand — die Sicht bliebe tagelang leer.
    """
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    name = str(form.get("name") or "").strip()[:80]
    url = str(form.get("url") or "").strip()
    if not name:
        return _fehlerseite(400, "Name fehlt",
                            "Ohne Namen lässt sich der Kalender später "
                            "niemandem zuordnen.")
    # W4 (Schlusspruefung 13.09.2026): `kalenderquelle_speichern` legt per
    # `on conflict (anzeigename)` einfach ueber eine bestehende Zeile —
    # nennt sich ein Kollege wie die eigene Quelle, landen seine Termine in
    # der Paarung des EIGENEN Kalenders (ui.py, `t["quelle"] ==
    # server.EIGENE_QUELLE`) statt in der Team-Sicht. Genau die
    # Verschmelzung, gegen die Ruling 10 gerichtet war, nur durch die
    # Vordertuer. Case-insensitiv abgewiesen: eine Schreibvariante waere
    # zwar keine echte Kollision in der Datenbank (der Vergleich dort ist
    # case-sensitiv), saehe in der Liste daneben aber genauso verwirrend
    # aus wie der exakte Name.
    if name.casefold() == server.EIGENE_QUELLE.casefold():
        return _fehlerseite(400, "Name vergeben", (
            f'„{_e(server.EIGENE_QUELLE)}" ist der Name des eigenen '
            f'Kalenders und dafür reserviert. Wähle einen anderen Namen, '
            f'zum Beispiel deinen eigenen.'))
    # Zeitfenster wie server.belegungen()s Vorgabe (K2/W1, Schlusspruefung
    # 13.09.2026): dieselbe Zahl, die die Sicht auf /kalender spaeter fuer
    # dieselbe Quelle zeigt — sonst meldet die Sofortpruefung hier "1.284
    # Termine" (die ganze Historie) und die spaetere Sicht etwas anderes.
    termine, fehler = server.kalenderquellen.hole(url, 0, 60)
    # BLOCKER (Koordinator-Fix-Runde, 13.09.2026): `fehler` ist seit K4
    # NICHT mehr gleichbedeutend mit "nichts verstanden" — hole() meldet
    # ihn auch dann, wenn die Quelle VOLLSTAENDIG verstanden wurde und nur
    # zusaetzlich Serientermine/unlesbare Dauern enthaelt (siehe
    # kalenderquellen.hole()s Docstring). Ein gewoehnlicher Google-/
    # Outlook-Kalender mit einer woechentlichen Teamrunde waere sonst gar
    # nicht mehr verbindbar gewesen — genau der Torschritt aus Spec-
    # Pruefpunkt 1. Abgewiesen wird nur, wenn GAR NICHTS Verwertbares
    # ankam (`termine` leer); sonst wie in server.belegungen() (K3/K4):
    # speichern, und den Vorbehalt NEBEN die Zahl stellen statt die ganze
    # Verbindung zu verweigern.
    if fehler and not termine:
        return _seite("Kalender verbinden", (
            f'<h1>Das hat nicht geklappt</h1>'
            f'<p class="fehler">{_e(fehler)}</p>'
            f'<p class="meta">Nichts wurde gespeichert.</p>'
            f'<p><a href="/team/kalender">Zurück und erneut versuchen</a></p>'))
    server.kalenderquelle_speichern(name, url)
    naechster = ""
    if termine:
        naechster = (f" Der nächste ist „{_e(termine[0]['titel'])}" + '" am '
                     f"{_zeit(termine[0]['beginn'])}.")
    vorbehalt = (f'<p class="hinweis">{_e(fehler)}</p>' if fehler else "")
    return _seite("Kalender verbunden", (
        f'<h1>Passt</h1>'
        f'<p>Ich sehe {len(termine)} Termin{"e" if len(termine) != 1 else ""} '
        f'in deinem Kalender.{naechster}</p>'
        + vorbehalt +
        f'<p class="meta">Die Adresse ist gespeichert und wird ab jetzt nicht '
        f'mehr angezeigt.</p>'
        f'<p><a href="/team/kalender">Zur Übersicht</a></p>'))


@_gesichert_seite
async def aktion_kalender_entfernen(request):
    """W3 (Schlusspruefung 13.09.2026): der einzige Aufrufer von
    server.kalenderquelle_entfernen() ausserhalb der Tests — ohne ihn blieb
    eine tote Quelle fuer immer aktiv und machte `frei: true` fuer sie
    dauerhaft unmoeglich. Ein Gegen-Ereignis, kein Hard-Delete (siehe
    kalenderquelle_entfernen()s Docstring): unter demselben Namen neu
    verbinden weckt die Zeile von selbst wieder auf, ein Bestaetigungs-
    schritt ist deshalb nicht noetig — dasselbe Muster wie
    aktion_termin_absagen."""
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    quelle_id = str(form.get("quelle_id") or "")
    if not quelle_id:
        return _fehlerseite(400, "Keine Quelle", "Keine Quelle angegeben.")
    server.kalenderquelle_entfernen(quelle_id)
    return RedirectResponse("/team/kalender", status_code=303)


_MONATSNAMEN = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                "August", "September", "Oktober", "November", "Dezember")
_WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _monat_lesen(roh, heute):
    """'2026-09' -> (jahr, monat). Kaputtes faellt auf heute zurueck —
    der Wert kommt aus der Adresszeile und ist damit Fremddatum."""
    try:
        jahr, monat = str(roh or "").split("-")
        jahr, monat = int(jahr), int(monat)
        if 1 <= monat <= 12 and 1970 <= jahr <= 2999:
            return jahr, monat
    except (ValueError, AttributeError):
        pass
    return heute.year, heute.month


def _monat_versetzt(jahr: int, monat: int, schritte: int) -> str:
    gesamt = (jahr * 12 + monat - 1) + schritte
    return f"{gesamt // 12:04d}-{gesamt % 12 + 1:02d}"


def _monatsgitter(monat, zeilen, fremde) -> str:
    """Der Kalender als Gitter — Wochentage als Spalten, ein Kasten je Tag.

    Zwei Quellen in EINEM Bild: die CRM-Termine (mit Kontaktbezug, als
    Verweis) und die Eintraege aus dem echten Kalender (kursiv, ohne
    Verweis — sie gehoeren keinem Kontakt). Alles Fremddatum ist escaped.
    """
    jahr, mon = monat
    erster = date(jahr, mon, 1)
    # Montag als erster Spaltentag (deutsche Woche).
    vorlauf = erster.weekday()
    tage_im_monat = (date(jahr + (mon == 12), mon % 12 + 1, 1)
                     - erster).days

    belegt = {}
    for z in zeilen:
        last = z["payload"] or {}
        tag = str(last.get("datum") or "")
        if not tag.startswith(f"{jahr:04d}-{mon:02d}"):
            continue
        if z["lead_id"]:
            titel_voll = str(last.get("thema") or z["name"] or "Termin")
            eintrag_html = (
                f'<a class="e" href="/kontakte/{_e(str(z["lead_id"]))}" '
                f'title="{_e(titel_voll)}">'
                f'{_e(str(last.get("uhrzeit") or ""))} '
                f'{_e(_kurz(titel_voll, 22))}</a>')
        else:
            titel_voll = str(last.get("thema") or "Termin")
            eintrag_html = (f'<span class="e" title="{_e(titel_voll)}">'
                            f'{_e(_kurz(titel_voll, 22))}</span>')
        belegt.setdefault(tag, []).append(eintrag_html)
    for t in fremde:
        beginn = t["beginn"].astimezone(ZEITZONE) if ZEITZONE else t["beginn"]
        tag = beginn.strftime("%Y-%m-%d")
        if not tag.startswith(f"{jahr:04d}-{mon:02d}"):
            continue
        titel_fremd = str(t["titel"])
        # W2 (Schlusspruefung 13.09.2026): die Quelle steht dazu, genau wie
        # in der Liste weiter unten (dort als eigener Badge) — sonst ist
        # ein Kollegentermin im Gitter von einem eigenen CalDAV-Eintrag
        # nicht zu unterscheiden, auf der einen Seite, deren Zweck genau
        # diese Unterscheidung ist. Im Tooltip voll ausgeschrieben, inline
        # knapp (wenig Platz je Kasten).
        # NUR fuer FREMDE Eintraege (Koordinator-Fix-Runde, 13.09.2026):
        # `fremde` traegt auch die eigenen CalDAV-Termine
        # (quelle == server.EIGENE_QUELLE) — die standen zuvor faelschlich
        # als "Betreiber: ..." beschriftet, im eigenen Kalender braucht der
        # eigene Name keine Beschriftung, und der Titel verlor dabei
        # unnoetig Platz (22 statt 16 Zeichen).
        quelle = str(t.get("quelle") or "")
        ist_fremd = quelle and quelle != server.EIGENE_QUELLE
        tooltip = f"{quelle}: {titel_fremd}" if ist_fremd else titel_fremd
        inline = (f"{_kurz(quelle, 12)}: {_kurz(titel_fremd, 16)}"
                  if ist_fremd else _kurz(titel_fremd, 22))
        belegt.setdefault(tag, []).append(
            f'<span class="e fremd" title="{_e(tooltip)}">{beginn:%H:%M} '
            f'{_e(inline)}</span>')

    heute_iso = date.today().isoformat()
    kaesten = ['<div class="tagkopf">' + t + "</div>" for t in _WOCHENTAGE]
    kaesten += ['<div class="tag leer"></div>'] * vorlauf
    for nummer in range(1, tage_im_monat + 1):
        iso = f"{jahr:04d}-{mon:02d}-{nummer:02d}"
        klasse = "tag heute" if iso == heute_iso else "tag"
        kaesten.append(
            f'<div class="{klasse}" data-tag="{iso}">'
            f'<div class="nummer">{nummer}</div>'
            f'{"".join(belegt.get(iso, []))}</div>')

    zurueck = _monat_versetzt(jahr, mon, -1)
    vor = _monat_versetzt(jahr, mon, 1)
    return (f'<div class="monatskopf">'
            f'<a href="/kalender?monat={zurueck}">&larr;</a>'
            f'<b>{_MONATSNAMEN[mon - 1]} {jahr}</b>'
            f'<a href="/kalender?monat={vor}">&rarr;</a></div>'
            f'<div class="monat">{"".join(kaesten)}</div>')


def tag_lesbar(iso: str) -> str:
    """'2026-09-04' -> '04.09.2026'. Fremddatum: was nicht passt, bleibt."""
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return iso


@_gesichert_seite
async def ergebnisse(request):
    """Die Endzustaende der Pipeline: gewonnen und verloren — getrennt
    vom Fluss (Betreiber-Wunsch 01.09.2026), damit die Pipeline den Weg
    zeigt und diese Seite die Bilanz."""
    zeilen = server._q(
        "select l.id, l.name, l.status, l.updated_at, "
        "  (select a.payload->>'begruendung' from activities a "
        "   where a.lead_id = l.id and a.type = 'stufenwechsel' "
        "   order by a.created_at desc limit 1) as begruendung "
        "from leads l "
        "where l.status in ('won', 'lost') and not "
        + server._archiv_sql("l.enrichment") + " order by l.updated_at desc")
    teile = []
    for status, titel in (("won", "Gewonnen"), ("lost", "Verloren")):
        gruppe = [z for z in zeilen if z["status"] == status]
        teile.append(f"<h2>{titel} ({len(gruppe)})</h2>")
        if not gruppe:
            teile.append("<p class=meta>—</p>")
            continue
        ergebnis_zeilen = []
        for z in gruppe:
            begruendung_voll = str(z["begruendung"] or "")
            ergebnis_zeilen.append([
                f'<a href="/kontakte/{_e(str(z["id"]))}">'
                f'{_e(z["name"] or "(ohne Namen)")}</a>',
                _zeit(z["updated_at"]),
                f'<span title="{_e(begruendung_voll)}">'
                f'{_e(_kurz(begruendung_voll, 160))}</span>'])
        teile.append(_tabelle(
            ["Kontakt", "Seit", "Begründung"], ergebnis_zeilen))
    return _seite("Ergebnisse", "".join(teile))


@_gesichert_seite
async def aktion_kontakt_autonomie(request):
    """Die Stufe setzen — ueber dasselbe Werkzeug wie der Chat."""
    form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.kontakt_autonomie_setzen(
        lead_id=lead_id, stufe=str(form.get("stufe") or "")))
    if "fehler" in antwort:
        return _fehlerseite(400, "Nicht gesetzt", _e(antwort["fehler"]))
    return RedirectResponse("/kontakte", status_code=303)


def _archiv_knopf_zeile(lead_id, archiviert: bool) -> str:
    """Archivieren bzw. Zurueckholen direkt aus der Kontaktuebersicht.

    Betreiber-Wunsch: „Kontakte die zu archivieren sind sollen auch ueber die
    uebersicht moeglich sein." Es entsteht dafuer KEIN neuer Schreibweg —
    das Formular zielt auf dieselben Routen wie der Knopf auf der
    Kontaktseite. Beim Archivieren heisst das insbesondere: der erste POST
    schreibt nichts, er zeigt die Warnseite mit dem, was am Kontakt haengt.
    Aus einer Liste heraus ist genau das wichtig — dort sieht man den
    Kontakt ja nicht.
    """
    verborgen = (f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
                 f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">')
    if archiviert:
        return (f'<form class="aktion" method="post" '
                f'action="/kontakte/wiederherstellen">{verborgen}'
                f'<button>Zurückholen</button></form>')
    return (f'<form class="aktion gefahr" method="post" '
            f'action="/kontakte/archivieren">{verborgen}'
            f'<button class="gefahr">Archivieren</button></form>')


def _leads_mit_profil(lead_ids):
    """Welche dieser Kontakte haben schon ein Kontaktprofil? -> set von str.

    EINE Abfrage fuer die ganze Liste, nicht eine je Zeile: die Einordnungs-
    uebersicht zeigt bis zu 25 Kontakte, und 25 Rundreisen zur Datenbank
    waeren fuer eine blosse Ja/Nein-Angabe verschwendet.
    """
    ids = [str(x) for x in lead_ids if x]
    if not ids:
        return set()
    # Zwei Quellen, wie in server._juengstes_profil: eigene
    # `kontakt_profil`-Zeilen (heute) und Profile, die noch in einem
    # Chat-Report eingebettet liegen (erste Fassung, echte Daten vorhanden).
    zeilen = server._q(
        "select distinct lead_id from activities"
        " where lead_id = any(%(ids)s::uuid[])"
        "   and ((type = %(report)s and payload->'profil' is not null)"
        "        or type = %(profil)s)",
        {"ids": ids, "report": server.CHAT_REPORT_TYP,
         "profil": server.PROFIL_TYP})
    return {str(z["lead_id"]) for z in zeilen}


def _profil_zelle(lead_id, mit_profil) -> str:
    """Der Profil-Link je Zeile — oder ein ehrliches „noch keins"."""
    if not lead_id:
        return "—"
    if str(lead_id) in mit_profil:
        return f'<a href="/kontakte/{_e(lead_id)}#profil">Profil</a>'
    return '<span class="meta">noch keins</span>'


def _profil_knopf(lead_id) -> str:
    """„Profil jetzt erzeugen" — genauer: anfordern.

    Diese Oberflaeche hat kein Sprachmodell und kann selbst kein Profil
    schreiben. Der Knopf vermerkt die Bitte; der Agent erledigt sie beim
    naechsten Durchgang. Der Text sagt das auch, statt eine Sofortwirkung
    zu versprechen, die nicht eintritt.
    """
    if _ist_sammelkontakt(lead_id):
        return ""
    return (f'<div class="aktionen"><form class="aktion" method="post" '
            f'action="/kontakte/profil-anfordern">'
            f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button>Neues Profil anfordern</button></form></div>'
            f'<p class="meta">Der Agent schreibt es beim nächsten '
            f'Durchgang. Es geht dabei nichts an den Kunden.</p>')


def _kontaktprofil_bereich(lead_id) -> str:
    """Das strukturierte Kontaktprofil — vier Leitfragen, Links, Dateien.

    Es steht GANZ OBEN auf der Kontaktseite und getrennt von den Reports
    darunter: das Profil ist der Stand, die Reports sind der Verlauf. Wer
    einen Kontakt aufschlaegt, will zuerst wissen, wer das ist und was
    gerade los ist — nicht, was vor drei Fassungen zusammengefasst wurde.

    Geschrieben wird hier nichts. Das Profil entsteht im Chat
    (`chat_report_speichern`), weil dort das Sprachmodell sitzt.
    """
    profil = server._juengstes_profil(lead_id)
    if not profil:
        return ('<h2 id="profil">Kontaktprofil</h2><div class="karte">'
                '<p>Noch keins. Es entsteht von selbst, sobald seit der '
                f'letzten Fassung {server.PROFIL_SCHWELLE} Nachrichten '
                'aufgelaufen sind — oder jetzt, auf Zuruf.</p>'
                + _profil_knopf(lead_id) + '</div>')
    zeilen = [f'<h3>{_e(server.PROFIL_FRAGEN[feld])}</h3>'
              f'<p>{_e(profil.get(feld) or "—")}</p>'
              for feld in server.PROFIL_FELDER]

    def liste(titel, eintraege):
        if not eintraege:
            return ""
        punkte = "".join(f"<li>{_e(x)}</li>" for x in eintraege)
        return f"<h3>{titel}</h3><ul>{punkte}</ul>"

    zeilen.append(liste("Links", profil.get("links") or []))
    zeilen.append(liste("Dateien", profil.get("dateien") or []))
    return (f'<h2 id="profil">Kontaktprofil</h2><div class="karte">'
            f'{"".join(zeilen)}'
            f'<p class="meta">Stand vom {_zeit(profil.get("stand_vom"))} — '
            f'aus dem Nachrichtenverlauf erschlossen, nicht bestätigt. '
            f'Bestätigte Angaben stehen oben unter den Stammdaten.</p>'
            f'{_profil_knopf(lead_id)}</div>')


def _chat_report_bereich(lead_id) -> str:
    """Die Chat-Reports eines Kontakts, aeltester zuerst.

    Die Oberflaeche SCHREIBT hier nichts: Reports entstehen im Chat
    (`chat_report_speichern`), weil dort das Sprachmodell sitzt, das den Text
    verfasst. Diese Seite zeigt sie nur — genau wie den Bedarfsstand.
    """
    reports = server._chat_reports(lead_id)
    if not reports:
        return ""
    zeilen = []
    for r in reports:
        p = r["payload"] or {}
        text = str(p.get("zusammenfassung") or "")
        anzahl = p.get("anzahl")
        zeilen.append([_zeit(r["created_at"]),
                       _e(anzahl if anzahl is not None else ""), _e(text)])
    return (f"<h2>Chat-Reports ({len(reports)})</h2>"
            + _tabelle(["Wann", "Nachrichten", "Zusammenfassung"], zeilen))


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
            400, "Bestätigung fehlt",
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
            409, "Bestätigung passt nicht mehr",
            "Der Kontakt heißt inzwischen anders als auf der Warnseite. "
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
async def aktion_profil_anfordern(request):
    """Ein frisches Kontaktprofil anfordern.

    Einschrittig und harmlos: es entsteht KEIN Profil — diese Oberflaeche
    hat kein Sprachmodell. Vermerkt wird die Bitte; der Kontakt steht danach
    in `profile_faellig` mit `angefordert: true`, und der Agent schreibt das
    Profil beim naechsten Durchgang. Es geht nichts an den Kunden.
    """
    _form, lead_id, abbruch = await _kontakt_vorspann(request)
    if abbruch:
        return abbruch
    antwort = json.loads(server.profil_anfordern(lead_id=lead_id))
    if "fehler" in antwort:
        return _fehlerseite(409, "Nicht angefordert", _e(antwort["fehler"]))
    return RedirectResponse(f"/kontakte/{lead_id}#profil", status_code=303)


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

    stammdaten = [(name, _e(lead[feld]))
                  for name, feld in (("Name", "name"), ("Status", "status"),
                                     ("Consent", "consent_status"),
                                     ("E-Mail", "email"), ("Telefon", "phone"),
                                     ("Firma", "company"), ("Titel", "title"),
                                     ("Quelle", "source"), ("Notizen", "notes"))]
    teile = []
    if archiviert:
        teile.append(
            '<div class="hinweis">Dieser Kontakt ist <b>archiviert</b>: er '
            'steht nicht in der Kontaktliste, nicht im Posteingang und nicht '
            'in der Zuordnungsauswahl der Einordnung. Gelöscht wurde nichts '
            '— der Verlauf unten ist vollzählig.</div>')
    # Der Hinweis nach einer Nummernaenderung. Die Seite liest aus dem
    # Abfrageteil NUR, WELCHER der hier fest verdrahteten Hinweise gezeigt
    # wird — der Text selbst kommt nie von dort (er waere sonst ein Fremddatum
    # in der eigenen Seite, und eine praeparierte Verknuepfung koennte dem
    # Betreiber Beliebiges in den Mund legen).
    if request.query_params.get("gespeichert") == "telefon":
        teile.append(
            '<div class="warnung">Telefonnummer geändert. Damit wechselt der '
            'Schlüssel, über den eingehende Nachrichten diesem Kontakt '
            'zugeordnet werden: Nachrichten von der ALTEN Nummer landen ab '
            'sofort beim Sammelkontakt „Unbekannte Eingänge" und müssen '
            'unter /einordnung neu zugeordnet werden; ausgehende Entwürfe '
            'gehen an die NEUE Nummer. Bereits gebuchte Zeilen im Verlauf '
            'bleiben, wo sie sind (activities ist append-only). Läuft der '
            'Kontakt im Auto-Betrieb, greift die Änderung dort erst nach '
            'scripts/sync-allowlist.ps1.</div>')
    teile.append(_paar_tabelle(
        stammdaten + [("Angelegt", _zeit(lead["created_at"]))]))
    teile.append(_kontakt_formular(lead))

    # Pipeline-Stufe (27.08.2026): dasselbe Werkzeug wie der Chat, mit
    # Begruendungsfeld — jeder Wechsel ist eine Beweiszeile. Leeres Feld
    # bekommt eine ehrliche Standard-Begruendung statt einer Ablehnung:
    # der Klick des Betreibers IST die Entscheidung.
    stufe_jetzt = server._stufe_lesen(lead["status"])
    stufen_optionen = "".join(
        f'<option value="{_e(s)}"{" selected" if s == stufe_jetzt else ""}>'
        f'{_e(s)}</option>' for s in server.PIPELINE_STUFEN)
    teile.append(
        f'<h2 id="stufe">Pipeline-Stufe</h2>'
        f'<form method="post" action="/kontakte/stufe" class="zeile">'
        f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<select name="stufe" aria-label="Pipeline-Stufe">{stufen_optionen}'
        f'</select> '
        f'<input name="begruendung" placeholder="Begründung (empfohlen)" '
        f'size="34"> <button>Stufe setzen</button></form>')

    # Privat-Markierung (P3, 29.08.2026): setzen fuehrt ueber die
    # Warnseite (kuenftige Nachrichten sind unwiederbringlich still),
    # aufheben geht direkt — dabei geht nichts verloren.
    if server._privat(lead["enrichment"]):
        teile.append(
            f'<h2 id="privat">&#128274; Privat</h2>'
            f'<p class="meta">Dieser Kontakt ist dem System still: nichts '
            f'wird gespeichert, kein Verlauf, keine Entwürfe. Bestand nur '
            f'über die Datenauskunft.</p>'
            f'<form method="post" action="/kontakte/privat-entziehen">'
            f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button>Privat-Markierung aufheben</button></form>')
    else:
        teile.append(
            f'<h2 id="privat">Privat</h2>'
            f'<form method="post" action="/kontakte/privat">'
            f'<input type="hidden" name="lead_id" value="{_e(lead_id)}">'
            f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
            f'<button>Privat markieren&hellip;</button></form>')

    # Bedarfsstand: beantwortete Leitfaden-Fragen mit Wortlaut, offene als Zahl.
    bedarf = anreicherung.get("bedarf") or {}
    teile.append(f"<h2>Bedarfsstand ({len(bedarf)} beantwortet, "
                 f"{max(len(server.ALLE_FRAGEN) - len(bedarf), 0)} offen)</h2>")
    if bedarf:
        teile.append(_tabelle(["Frage", "Antwort"], [
            [_e(server.ALLE_FRAGEN.get(fid, {}).get("frage", fid)),
             _e((wert or {}).get("antwort") if isinstance(wert, dict) else wert)]
            for fid, wert in sorted(bedarf.items())]))
    else:
        teile.append("<p>Noch keine Antworten erfasst.</p>")

    # Vertraege (enrichment.vertraege) — nur wenn es wirklich ein Array ist,
    # Recherche-Arbeit sichtbar machen (Betreiber-Wunsch 01.09.2026):
    # firma_anreichern legt unter enrichment.firma ab — bis jetzt zeigte
    # die Seite davon nichts. Alles Fremddaten von fremden Websites:
    # escaped und gekuerzt, wie ueberall.
    teile.append("<h2>Recherche (Firma)</h2>")
    firma = anreicherung.get("firma")
    if isinstance(firma, dict) and (firma.get("website")
                                    or firma.get("seiten")):
        meta = f'<div class="meta">{_e(firma.get("website") or "")}</div>'
        seiten = firma.get("seiten")
        seiten = seiten if isinstance(seiten, list) else []
        karten = []
        for s in seiten[:6]:
            if not isinstance(s, dict):
                continue
            text_voll = " ".join(str(s.get("text") or "").split())
            karten.append(
                f'<div class="karte"><b>{_e(s.get("titel") or s.get("typ") or "Seite")}</b>'
                f'<div class="meta">{_e(s.get("url") or "")}</div>'
                # Merge 12.09.2026, beides behalten: kuerzen mit vollem Text
                # im `title` (Stufe 1) UND anklickbare Adressen (Konferenz-
                # Linie). Reihenfolge zwingend: erst `_kurz` auf den ROHEN
                # Text, dann `_text_html` — das escapet selbst und sucht die
                # Adressen im bereits escapten Text. Umgekehrt schnitte
                # `_kurz` in fertiges Markup hinein.
                # Die Fassung der Konferenz-Linie liess sich hier nicht
                # woertlich uebernehmen: sie ruft `_text_html(text)` auf, und
                # `text` gibt es in diesem Block nicht (nur `text_voll`) —
                # das waere ein NameError auf der Kontaktseite gewesen.
                f'<div class="text" title="{_e(text_voll)}">'
                f'{_text_html(_kurz(text_voll, 300))}</div></div>')
        # Geschaeftsverweise (01.09.2026): die Social-/Business-Links, die
        # die Firma selbst verlinkt — als anklickbare Absprungpunkte. Der
        # Text ist eine feste Plattform-Bezeichnung aus dem Code, die URL
        # Fremddatum (escaped; das href genauso).
        verweise = firma.get("verweise")
        verweise = verweise if isinstance(verweise, list) else []
        verweis_zeile = ""
        if verweise:
            knoepfe = "".join(
                f'<a class="verweis" href="{_e(v.get("url"))}" '
                f'target="_blank" rel="noopener noreferrer nofollow">'
                f'{_e(v.get("plattform") or "Link")}</a>'
                for v in verweise if isinstance(v, dict) and v.get("url"))
            verweis_zeile = (f'<p class="meta">Verlinkt von der Firma '
                             f'(nur Absprung, nicht ausgewertet):</p>'
                             f'<p class="verweise">{knoepfe}</p>')
        teile.append(meta + "".join(karten) + verweis_zeile)
    else:
        teile.append(
            '<p class="meta">Noch keine Firmendaten — der Assistent '
            'reichert mit firma_anreichern an (Website nötig).</p>')

    # dieselbe Typ-Vorsicht wie vertraege_ablaufend in server.py.
    vertraege = anreicherung.get("vertraege")
    vertraege = vertraege if isinstance(vertraege, list) else []
    teile.append(f"<h2>Verträge ({len(vertraege)})</h2>")
    if vertraege:
        teile.append(_tabelle(["Sparte", "Gesellschaft", "Ablauf"], [
            [_e(v.get("sparte")), _e(v.get("gesellschaft")), _e(v.get("ablauf"))]
            for v in vertraege if isinstance(v, dict)]))
    else:
        teile.append("<p>Keine Verträge erfasst.</p>")

    teile.append("<h2>Offene Wiedervorlagen</h2>")
    teile.append(_wiedervorlagen_tabelle(_offene_wiedervorlagen(lead_id),
                                         mit_kontakt=False))

    # Das Kontaktprofil VOR den Reports: es ist der Stand, sie sind der
    # Verlauf. Wer einen Kontakt aufschlaegt, will zuerst wissen, wer das
    # ist und was gerade los ist.
    teile.append(_kontaktprofil_bereich(lead_id))

    # Chat-Reports ZUERST (Betreiber-Wunsch 22.08.2026): sie erzaehlen die
    # Vorgeschichte, und die von ihnen abgedeckten Einzelnachrichten fallen
    # unten aus dem Verlauf — sonst stuende derselbe Chat zweimal da. Der
    # Reporttext ist AGENTENTEXT ueber Kundennachrichten und wird deshalb
    # genauso escaped wie jedes andere Fremddatum auf dieser Seite.
    teile.append(_chat_report_bereich(lead_id))

    # Verlauf chronologisch — die Payload als gekuerzte Vorschau, escaped:
    # jedes Feld darin kann Kundentext sein.
    grenze_zeit, grenze_id = server._chat_grenze(lead_id)
    aktivitaeten = server._q(
        "select type, actor, payload, created_at from activities "
        "where lead_id = %(lead)s and type <> %(report)s "
        "and (not (type = any(%(typen)s)) "
        "     or (created_at, id) > "
        "        (coalesce(%(zeit)s::timestamptz, '-infinity'::timestamptz), "
        "         coalesce(%(id)s::uuid, "
        "                  '00000000-0000-0000-0000-000000000000'::uuid))) "
        "order by created_at asc limit %(limit)s",
        {"lead": lead_id, "report": server.CHAT_REPORT_TYP,
         "typen": list(server.CHAT_NACHRICHT_TYPEN),
         "zeit": grenze_zeit, "id": grenze_id, "limit": AKTIVITAETEN_MAX})
    teile.append(f"<h2>Verlauf ({len(aktivitaeten)})</h2>")
    if grenze_zeit is not None:
        teile.append(
            '<div class="hinweis">Nachrichten, die ein Chat-Report oben '
            'abdeckt, stehen hier nicht mehr. <b>Gelöscht ist nichts</b> — '
            'sie liegen vollzählig in der Datenbank; im Wortlaut zeigt sie '
            'der Chat mit <code>chat_verlauf(lead_id, alle=True)</code>.'
            '</div>')
    if aktivitaeten:
        zeilen = [[_zeit(a["created_at"]), _verlauf_richtung(a),
                   _verlauf_inhalt(a)] for a in aktivitaeten]
        teile.append(_tabelle(["Wann", "Was", "Inhalt"], zeilen))
    else:
        teile.append("<p>Noch keine Aktivitäten.</p>")

    teile.append(_whatsapp_freigabe_bereich(
        lead, server._whatsapp_freigegeben(lead["enrichment"])))
    teile.append(_wiedervorlage_formular(lead_id))
    teile.append(_archiv_bereich(lead, archiviert))
    return _seite(lead["name"] or "Kontakt", "".join(teile))


# Wie eine Verlaufszeile heisst — statt der rohen Typnamen aus der
# Datenbank. `nachricht_ausgehend` sagt einem Menschen nichts; „ich →" schon.
VERLAUF_NAMEN = {
    "kundenantwort": "&larr; Kunde",
    "nachricht": "&larr; Kunde",
    "nachricht_ausgehend": "&rarr; ich",
    "versand": "&rarr; zugestellt",
    "eingang_ignoriert": "&larr; ignoriert",
    "ausgang_ignoriert": "&rarr; ignoriert",
    # Sprachnachricht in Text (01.09.2026) — steht als eigene Zeile
    # hinter der Nachricht, die sie ausspricht.
    "transkription": "&larr; abgehört",
    # Termin-Einladungen (Aufgabe 6, 11.09.2026): 'einladung_entworfen'
    # heisst so, WEIL zu diesem Zeitpunkt noch nichts verschickt ist — der
    # Entwurf liegt zur Freigabe (dasselbe Freigabe-Gate wie jeder andere
    # Kanal, siehe global-constraints.md). Verschickt wird sie erst ueber
    # die Freigabe-Seite; diese Zeile im Verlauf ist nur die Spur, dass sie
    # angelegt wurde.
    "einladung_entworfen": "&rarr; Einladung entworfen",
    "einladung_antwort": "&larr; Antwort",
}
# Felder, die im Verlauf NICHTS zu suchen haben: Maschinenkram, der die
# Zeile unlesbar macht. Sie bleiben in der Datenbank, sie stehen hier nur
# nicht im Weg.
VERLAUF_TECHNISCH = ("text", "message_id", "gesendet_am", "gekuerzt",
                     "richtung", "nachrichtentyp", "kennung_quelle",
                     "unbekannter_absender", "unbekannter_empfaenger",
                     "roh_from", "chat_kennung", "autor", "ist_lid_absender",
                     "senderphone", "push_name", "weg", "ohne_text")


def _verlauf_richtung(a) -> str:
    """Die Zeile mit einem Wort benennen, das ein Mensch versteht."""
    name = VERLAUF_NAMEN.get(a["type"])
    if name:
        return name
    return f'<span class="meta">{_e(a["type"])}</span>'


# Laenge, ab der der Ablehnungs-/Antwortgrund im Verlauf gekuerzt wird
# (Aufgabe 6) — derselbe Wortgrenzen-Schnitt wie ueberall (`_kurz`), voller
# Text im `title`. Der Grund ist Fremdtext: der Antwortende schreibt ihn,
# nicht der Betreiber.
EINLADUNG_GRUND_KURZ = 140


def _verlauf_einladung_antwort(payload: dict) -> str:
    """Eine Kalenderantwort im Verlauf: der Status uebersetzt
    (`EINLADUNG_TEXT`), der Grund gekuerzt mit vollem Text im `title` —
    beides ueber `_e`, weil beides Fremdtext ist (der Status kommt zwar aus
    einer festen iCal-Werteliste, aber ungeprueft aus einer fremden Mail).

    `status`/`grund` fallen deshalb aus dem restlichen Payload-Auszug
    heraus: sie stehen schon lesbar in der Zeile, ein zweites Mal roh im
    aufklappbaren Detailblock waere nur Redundanz (und liesse den rohen
    DB-Wert wieder auf der Seite auftauchen, den die Uebersetzung gerade
    verbergen soll)."""
    status = str(payload.get("status") or "")
    wort = EINLADUNG_TEXT.get(status, status or "unbekannt")
    zeile = f'<b>{_e(wort)}</b>'
    grund = str(payload.get("grund") or "").strip()
    if grund:
        zeile += (f'<div class="text" title="{_e(grund)}">'
                  f'{_e(_kurz(grund, EINLADUNG_GRUND_KURZ))}</div>')
    rest = {k: v for k, v in payload.items()
            if k not in VERLAUF_TECHNISCH and k not in ("status", "grund")
            and v not in (None, "", [], {})}
    if rest:
        roh = json.dumps(rest, ensure_ascii=False, default=str)
        if len(roh) > PAYLOAD_KURZ:
            roh = roh[:PAYLOAD_KURZ] + "…"
        zeile += (f'<details><summary class="meta">Details</summary>'
                  f'<code>{_e(roh)}</code></details>')
    return zeile


def _verlauf_einladung_entworfen(payload: dict) -> str:
    """Der vorgeschlagene Termin im Verlauf: Datum, Uhrzeit und Thema
    lesbar in der Zeile (W4, Schlusspruefung 11.09.2026) — vorher gab
    `einladung_entworfen` der Aktivitaet nur einen Namen ("→ Einladung
    entworfen"), der vorgeschlagene Termin selbst stand nur als rohes JSON
    hinter der Klappe; der Betreiber sah „→ Einladung entworfen" und musste
    aufklappen, um zu erfahren, WANN.

    Nach dem Muster von Aufgabe 6 (`_verlauf_einladung_antwort`): das
    Wichtigste sofort lesbar in der Zeile, `thema` (Fremdtext — vom
    Betreiber im Werkzeugaufruf gesetzt, aber ungeprueft, kann also
    Kundennamen o. Ae. tragen) ueber `_e`/`_kurz` mit vollem Text im
    `title`, Rest (uid, folge, eingeladene) hinter einer Klappe statt in
    der Zeile."""
    datum = str(payload.get("datum") or "").strip()
    uhrzeit = str(payload.get("uhrzeit") or "").strip()
    wann = " ".join(s for s in (datum, uhrzeit) if s)
    thema_voll = str(payload.get("thema") or "").strip()
    stuecke = []
    if wann:
        stuecke.append(f'<b>{_e(wann)}</b>')
    if thema_voll:
        stuecke.append(f'<span title="{_e(thema_voll)}">'
                       f'{_e(_kurz(thema_voll, EINLADUNG_GRUND_KURZ))}</span>')
    zeile = " · ".join(stuecke)
    rest = {k: v for k, v in payload.items()
            if k not in VERLAUF_TECHNISCH
            and k not in ("datum", "uhrzeit", "thema")
            and v not in (None, "", [], {})}
    if rest:
        roh = json.dumps(rest, ensure_ascii=False, default=str)
        if len(roh) > PAYLOAD_KURZ:
            roh = roh[:PAYLOAD_KURZ] + "…"
        zeile += (f'<details><summary class="meta">Details</summary>'
                  f'<code>{_e(roh)}</code></details>')
    return zeile


def _verlauf_inhalt(a) -> str:
    """Der Nachrichtentext — und der Maschinenkram nur auf Wunsch.

    Vorher stand hier die rohe JSON-Nutzlast, abgeschnitten nach ein paar
    hundert Zeichen: `message_id`, `gesendet_am`, `kennung_quelle` und der
    eigentliche Text in einer Zeile, in der man ihn suchen musste. Das war
    eine Entwickleransicht in einer Betreiberoberflaeche.

    Jetzt: der Text gross, alles Uebrige hinter einer Klappe. Es geht
    nichts verloren — es steht nur nicht mehr im Weg.
    """
    last = a["payload"] or {}
    # Aufgabe 6 / W4 (Schlusspruefung 11.09.2026): beide Einladungs-
    # Aktivitaeten haben eine eigene, uebersetzte Darstellung — vor der
    # generischen `text`-Behandlung unten, die fuer beide Typen nichts
    # faende (die Nutzlast hat kein `text`-Feld) und in die rohe
    # JSON-Nutzlast-Klappe fiele.
    if a["type"] == "einladung_antwort":
        return _verlauf_einladung_antwort(last)
    if a["type"] == "einladung_entworfen":
        return _verlauf_einladung_entworfen(last)
    text = str(last.get("text") or "").strip()
    if not text and last.get("ohne_text"):
        text = "(Text nicht gespeichert — Absender ist auf ignorieren)"
    # Sprachnachricht ohne Text (01.09.2026): benennen statt leer lassen,
    # und wo sie schon transkribiert ist, steht der Text unten als eigene
    # Zeile (Typ `transkription`).
    if not text and a["type"] == "kundenantwort" and last.get("audio_datei"):
        text = _nachricht_inhalt("", last.get("nachrichtentyp"))
        return text
    if not text and a["type"] == "transkription" and last.get("leer"):
        text = "(nichts Verständliches auf der Aufnahme)"
    rest = {k: v for k, v in last.items()
            if k not in VERLAUF_TECHNISCH and v not in (None, "", [], {})}
    klappe = ""
    if rest:
        roh = json.dumps(rest, ensure_ascii=False, default=str)
        if len(roh) > PAYLOAD_KURZ:
            roh = roh[:PAYLOAD_KURZ] + "…"
        klappe = (f'<details><summary class="meta">Details</summary>'
                  f'<code>{_e(roh)}</code></details>')
    if not text:
        return klappe or '<span class="meta">—</span>'
    return f'<div class="text">{_text_html(text)}</div>{klappe}'


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
        teile.append("<p>Keine unbeantworteten Eingänge.</p>")
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
                lid += (f' <span class="badge">gehört zu '
                        f'<a href="/kontakte/{_e(e["zugeordnet_zu"])}">'
                        f'{_e(e.get("zugeordnet_name") or "Kontakt")}</a>'
                        f'</span>')
            absender = f'<div class="meta">Absender: {_e(e["absender"])}{lid}</div>'
        inhalt_zeile = _nachricht_inhalt(e.get("text_kurz"),
                                         e.get("nachrichtentyp"))
        teile.append(
            f'<div class="karte"><b><a href="/kontakte/{_e(e["lead_id"])}">'
            f'{_e(e["kontakt"] or "(ohne Kontakt)")}</a></b> — wartet seit '
            f'{_e(e["wartet_stunden"])} h{absender}{inhalt_zeile}</div>')
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
    return server.lead_zu_kennung(absender)


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
    der Lead-Fall bekommt eine eigene Seite mit eigenem Formular.

    Die drei Formulare stehen in EINEM `.aktionen`-Kasten: nebeneinander auf
    dem Desktop, untereinander und ueber die volle Breite auf dem Handy — und
    „Ignorieren" (`gefahr`) rueckt dort zusaetzlich ab, weil es der Knopf ist,
    dessen Fehlgriff niemandem auffaellt.
    """
    verborgen = (f'<input type="hidden" name="absender" '
                 f'value="{_e(absender)}">{_einordnung_kopf()}')
    return (
        f'<div class="aktionen">'
        f'<form class="aktion" method="post" action="/einordnung/zuordnen">'
        f'{verborgen}<select name="lead_id">'
        f'<option value="">— bestehender Kontakt —</option>{optionen}'
        f'</select><button class="primaer">Zuordnen</button></form>'
        f'<form class="aktion" method="post" action="/einordnung/anlegen">'
        f'{verborgen}<input type="text" name="name" autocomplete="off" '
        f'autocapitalize="words" '
        f'maxlength="{EINORDNUNG_NAME_MAX}" placeholder="Name des Kontakts">'
        f'<button>Neu anlegen</button></form>'
        f'<form class="aktion gefahr" method="post" '
        f'action="/einordnung/ignorieren">'
        f'{verborgen}<button class="gefahr">Ignorieren</button></form>'
        f"</div>")


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
        warnung = (f'<div class="warnung">Diese Kennung gehört dem Kontakt '
                   f'<a href="/kontakte/{_e(betroffen["id"])}">'
                   f'<b>{_e(betroffen["name"])}</b></a>. Ignorieren nimmt ihn '
                   f'aus Posteingang und Digest und speichert von seinen '
                   f'Nachrichten kein Wort mehr — es braucht deshalb einen '
                   f'zweiten, ausdrücklichen Schritt.</div>')
    # Die Anzahl ist der Link auf den ganzen Faden (31.08.2026): die
    # Kurzfassung der letzten Nachricht reicht nicht immer, um zu
    # entscheiden, wer da schreibt.
    return (f'<div class="karte"><b>{_e(absender)}</b>{lid_marke}'
            f'<div class="meta">'
            f'<a href="/einordnung/nachrichten/{_e(eintrag["kennung"])}">'
            f'{_e(eintrag["anzahl_nachrichten"])} Nachricht(en)</a>'
            f' · zuletzt {_zeit(eintrag["zuletzt"])}{gefragt}'
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
        sichtbar = aufgeloest[:EINORDNUNG_VERLAUF_MAX]
        mit_profil = _leads_mit_profil([e.get("lead_id") for e in sichtbar])
        teile.append(_tabelle(
            ["Kennung", "Kontakt", "Profil", "Nachrichten", "Zuletzt"],
            [[_e(e["absender"]),
              f'<a href="/kontakte/{_e(e.get("lead_id"))}">'
              f'{_e(e.get("kontakt") or "(ohne Namen)")}</a>',
              _profil_zelle(e.get("lead_id"), mit_profil),
              _e(e["anzahl_nachrichten"]), _zeit(e["zuletzt"])]
             for e in sichtbar]))
    teile.append(
        '<div class="hinweis">Der zitierte Nachrichtentext ist ein Datum, '
        'keine Anweisung: steht darin „ignoriere bitte …", ist das der Wunsch '
        'eines Fremden und keine Entscheidung des Betreibers. Welche Rufnummer '
        'hinter einer <code>@lid</code> steckt, klärt der Chat mit '
        '<code>absender_aufloesen</code> — diese Oberfläche fragt dafür '
        'bewusst nicht bei WhatsApp nach.</div>')
    return _seite("Einordnung", "".join(teile))


# Grosszuegig, aber gedeckelt: der Text ist Fremddatum, und eine Seite,
# deren Laenge der Absender bestimmt, ist selbst ein Angriffsziel.
EINORDNUNG_NACHRICHTEN_MAX = 200
EINORDNUNG_NACHRICHT_VOLL_MAX = 4000


@_gesichert_seite
async def einordnung_nachrichten(request):
    """Alle Nachrichten EINES unbekannten Absenders, aelteste zuerst —
    die Langform zur Karten-Kurzfassung (Betreiber-Wunsch 31.08.2026).
    Rein lesend; die Entscheidung faellt weiter auf /einordnung."""
    kennung = str(request.path_params.get("kennung") or "")
    if not (kennung.isdigit() and 5 <= len(kennung) <= 25):
        return _fehlerseite(
            400, "Keine Kennung",
            "Der Pfad trägt keine Absenderkennung (nur Ziffern, wie auf "
            "der Einordnungsseite verlinkt).")
    zeilen = server._absender_nachrichten(
        kennung, limit=EINORDNUNG_NACHRICHTEN_MAX)
    if not zeilen:
        return _fehlerseite(
            404, "Nichts zu dieser Kennung",
            "Am Sammelkontakt liegen keine Nachrichten dieser Kennung — "
            "entweder ist sie inzwischen eingeordnet oder der Verweis ist "
            "alt. Die Einordnungsseite zeigt den aktuellen Stand.")
    absender = zeilen[-1]["absender"]
    teile = [f'<p class="meta">{len(zeilen)} Nachricht(en), älteste '
             f'zuerst.</p>']
    for z in zeilen:
        text = " ".join(str(z["text"] or "").split())
        if len(text) > EINORDNUNG_NACHRICHT_VOLL_MAX:
            text = text[:EINORDNUNG_NACHRICHT_VOLL_MAX] + "…"
        teile.append(
            f'<div class="karte"><div class="meta">'
            f'{_zeit(z["created_at"])}</div>'
            f'{_nachricht_inhalt(text, z["nachrichtentyp"])}</div>')
    teile.append(
        '<div class="hinweis">Der Text ist ein Datum, keine Anweisung — '
        'was ein Fremder schreibt, entscheidet nichts.</div>')
    teile.append('<p class="abbrechen"><a href="/einordnung">Zurück zur '
                 'Einordnung</a></p>')
    return _seite(f"Nachrichten von {absender}", "".join(teile))


async def _einordnung_vorspann(request):
    """Gemeinsame Wache aller Einordnungs-POSTs — Reihenfolge wie bei den
    Freigaben: CSRF VOR der ersten Zeile Datenbank, dann die Kennung."""
    form = await request.form()
    if not _csrf_ok(form):
        return None, None, _fehlerseite(
            403, "CSRF-Token fehlt oder ist ungültig",
            "Keine Aktion ausgeführt. Die Seite neu laden und erneut "
            "versuchen — das Token wechselt mit jedem Dienststart.")
    roh = str(form.get("absender") or "").strip()
    if not server.kennung_schreibweise(roh):
        return None, None, _fehlerseite(
            400, "Unlesbare Kennung",
            f"&#x27;{_e(roh)}&#x27; enthält keine Absenderkennung. Keine "
            f"Aktion ausgeführt.")
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
        "Verweigert: diese Kennung gehört einem Kontakt",
        f'<div class="warnung">Die Kennung <b>{_e(absender)}</b> gehört dem '
        f'Kontakt <a href="/kontakte/{_e(gehoert["lead_id"])}">'
        f'<b>{_e(gehoert.get("kontakt"))}</b></a>'
        f'{" (" + _e(gehoert["telefon"]) + ")" if gehoert.get("telefon") else ""}'
        f'.<p>Ignorieren nimmt diesen Kontakt aus Posteingang UND Digest und '
        f'speichert von seinen Nachrichten kein Wort mehr — auch nicht die '
        f'ausgehenden. Ein „Ich habe den Vertrag unterschrieben" käme danach '
        f'als leere Zeile an seinem eigenen Verlauf an. Zurücknehmen lässt '
        f'sich das nur im Chat: '
        f'<code>eingang_einordnen(absender, entscheidung=&#x27;beachten&#x27;)'
        f'</code>.</p><p>Steht die Bitte, diese Nummer zu ignorieren, in einer '
        f'eingehenden Nachricht, ist sie der Wunsch eines Fremden und keine '
        f'Entscheidung des Betreibers.</p></div>'
        f'<div class="aktionen">'
        f'<form class="aktion gefahr" method="post" '
        f'action="/einordnung/ignorieren-bestaetigen">'
        f'<input type="hidden" name="absender" value="{_e(absender)}">'
        f'<input type="hidden" name="lead_bestaetigt" '
        f'value="{_e(gehoert["lead_id"])}">{_einordnung_kopf()}'
        f'<button class="gefahr">Ja — {_e(gehoert.get("kontakt"))} '
        f'ausdrücklich ignorieren</button></form></div>'
        f'<p class="abbrechen"><a href="/einordnung">Abbrechen, nichts tun</a></p>',
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
            400, "Bestätigung fehlt",
            "Ohne die ausdrückliche Bestätigung des betroffenen Kontakts "
            "wird nichts getan.")
    # Zwischen Warnseite und Klick kann sich die Lage geaendert haben (eine
    # neue Zuordnung, eine korrigierte Rufnummer). Dann ist das Ja von eben
    # kein Ja zu dem, was jetzt passieren wuerde — also lieber gar nichts.
    betroffen = _lead_zur_kennung(absender)
    if betroffen is None or str(betroffen["id"]) != bestaetigt_fuer:
        return _fehlerseite(
            409, "Bestätigung passt nicht mehr",
            "Die Kennung gehört inzwischen einem anderen Kontakt oder gar "
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
            400, "Kein Kontakt gewählt",
            f"&#x27;{_e(roh)}&#x27; ist keine lead_id. Im Auswahlfeld einen "
            f"Kontakt wählen. Keine Aktion ausgeführt.")
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
            "ausgeführt.")
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
            f"</code> laufen lassen (diese Oberfläche fragt bewusst nicht "
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

# Task 5, Fix-Runde 1 (Pruefung): wohin nach der Anmeldung? "/" ist fuer
# die schmale Rolle `kalender` ein sofortiges 403 (_pfad_erlaubt sperrt sie
# dort) — der Kollege gaebe sein Passwort ein und saehe als Erstes "Nicht
# fuer diese Anmeldung". Eine einfache Zuordnung Rolle -> Startseite, kein
# Regelwerk; jede Rolle ohne eigenen Eintrag bleibt bei "/".
_ROLLE_STARTSEITE = {"kalender": "/team/kalender"}


def _startseite(rolle: str) -> str:
    return _ROLLE_STARTSEITE.get(rolle, "/")


def _login_seite(meldung: str = "", status: int = 200) -> HTMLResponse:
    hinweis = ""
    if not UI_SESSION_SECRET:
        hinweis = ('<p class="meta">Die Anmeldung ist nicht scharf — es ist '
                   'kein UI_SESSION_SECRET gesetzt, die Oberfläche steht '
                   'allen im Tailscale-Netz offen. Scharf schalten: '
                   'deploy/benutzer-anlegen.sh auf der VM ausführen '
                   '(siehe docs/05).</p>')
    fehler = f'<p class="fehler">{_e(meldung)}</p>' if meldung else ""
    rumpf = (
        f"{hinweis}{fehler}"
        f'<form method="post" action="/login">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<p><label>Name<br><input name="name" autocomplete="username" '
        f'autofocus></label></p>'
        f'<p><label>Passwort<br><input type="password" name="passwort" '
        f'autocomplete="current-password"></label></p>'
        f'<p><button type="submit">Anmelden</button></p>'
        f'</form>'
        f'<p class="meta"><a href="/passwort-vergessen">Passwort '
        f'vergessen?</a></p>')
    return _seite("Anmeldung", rumpf, status=status)


@_gesichert_seite
async def login(request):
    if request.method != "POST":
        return _login_seite()
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut anmelden.")
    if not UI_SESSION_SECRET:
        return _login_seite()
    jetzt = time.time()
    if jetzt < ANMELDE_BREMSE["gesperrt_bis"]:
        return _seite(
            "Anmeldung", '<p class="fehler">Zu viele Fehlversuche — eine '
            'Minute warten, dann erneut.</p>', status=429)
    name = str(form.get("name") or "").strip()
    zeilen = server._q(
        "select passwort_hash, aktiv, rolle from benutzer where name = %s",
        (name,))
    # Absichtlich EIN Fehlertext fuer alle Faelle (unbekannt, inaktiv,
    # falsches Passwort) — die Anmeldemaske verraet nicht, welche Namen es
    # gibt. Und kein Log des Namens: im Namensfeld landet erfahrungsgemaess
    # auch mal ein Passwort.
    if not (zeilen and zeilen[0]["aktiv"] and _passwort_pruefen(
            str(form.get("passwort") or ""), zeilen[0]["passwort_hash"])):
        ANMELDE_BREMSE["fehler"] += 1
        if ANMELDE_BREMSE["fehler"] >= BREMSE_AB:
            ANMELDE_BREMSE["gesperrt_bis"] = jetzt + BREMSE_SPERRE_S
            ANMELDE_BREMSE["fehler"] = 0
        LOG.warning("Anmeldung fehlgeschlagen")
        return _login_seite("Anmeldung fehlgeschlagen.")
    ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    antwort = RedirectResponse(_startseite(zeilen[0]["rolle"]),
                               status_code=303)
    antwort.set_cookie(
        SITZUNG_COOKIE, _sitzung_bauen(name, jetzt + SITZUNG_DAUER_S),
        max_age=SITZUNG_DAUER_S, httponly=True, samesite="lax", path="/")
    LOG.info("Anmeldung: %s", name)
    return antwort


# --- Passwort vergessen (16.09.2026) ---------------------------------------
#
# Betreiber-Auftrag. Es gab bisher genau einen Weg zu einem neuen Passwort:
# `benutzer_anlegen.py` auf der Kommandozeile IM CONTAINER. Wer keine Shell
# auf der VM hat - und der zweite Benutzer dieses Hauses hat keine -, war
# ausgesperrt und musste den Betreiber bitten.
#
# Die Regeln stehen in `passwort_reset.py` (reine Rechnung, ohne Datenbank
# und ohne Web pruefbar); hier steht nur die Verdrahtung.

# Wohin der Link zeigt. AUS DER UMGEBUNG, nicht aus der Anfrage: wer den
# Host-Header faelschen kann, wuerde sonst den Link auf seinen eigenen
# Rechner zeigen lassen und den Token einsammeln. Fehlt sie, faellt der
# Dienst auf die eigene Loopback-Adresse zurueck - dann ist der Link nur auf
# der VM brauchbar, und das ist ein ehrlicher Zustand.
UI_BASIS_URL = os.environ.get("UI_BASIS_URL", "").strip() or f"http://127.0.0.1:{PORT}"

# Und sie SAGT es, wenn sie fehlt. Ein stiller Rueckfall auf das eigene
# Loopback waere genau die Sorte Fehler, an der dieses Haus schon gelitten
# hat: die Mail geht raus, der Empfaenger klickt, nichts passiert - und es
# faellt erst auf, wenn jemand fragt. Einmal beim Start ins Log genuegt;
# eine Warnung je Anfrage wuerde niemand mehr lesen.
if not os.environ.get("UI_BASIS_URL", "").strip():
    LOG.warning(
        "UI_BASIS_URL ist nicht gesetzt - Links in der "
        "Passwort-vergessen-Mail zeigen auf %s und sind ausserhalb dieses "
        "Containers wertlos. Wohin sie gehoeren, steht im docker-compose.yml.",
        UI_BASIS_URL)

# EINE Antwort fuer jeden Ausgang. Ob es den Namen gibt, ob eine Adresse
# hinterlegt ist, ob die Bremse greift - der Benutzer sieht denselben Satz.
# Dieselbe Ueberlegung wie bei der Anmeldung: die Maske verraet nicht,
# welche Namen es gibt.
_RESET_ANTWORT = (
    "Wenn es dieses Konto gibt und eine Adresse hinterlegt ist, ist eine "
    "Mail mit einem Einmal-Link unterwegs. Der Link gilt 30 Minuten. "
    "Kommt nichts an, sieh im Spam nach oder frag den Betreiber — er kann "
    "das Passwort auch direkt setzen.")



def _reset_seite(meldung: str = "", art: str = "meta", status: int = 200) -> HTMLResponse:
    hinweis = f'<p class="{art}">{_e(meldung)}</p>' if meldung else ""
    rumpf = (
        f"{hinweis}"
        f"<p>Trag deinen Namen ein. Ist für das Konto eine Adresse "
        f"hinterlegt, geht ein Einmal-Link dorthin.</p>"
        f'<form method="post" action="/passwort-vergessen">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<p><label>Name<br><input name="name" autocomplete="username" '
        f'autofocus></label></p>'
        f'<p><button type="submit">Link anfordern</button></p>'
        f'</form>'
        f'<p class="meta"><a href="/login">Zurück zur Anmeldung</a></p>')
    return _seite("Passwort vergessen", rumpf, status=status)


@_gesichert_seite
async def passwort_vergessen(request):
    if request.method != "POST":
        return _reset_seite()
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungueltige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")

    name = str(form.get("name") or "").strip()
    # Ab hier IMMER dieselbe Antwort, egal was passiert. Jeder vorzeitige
    # Ausstieg mit einem anderen Text waere eine Auskunft darueber, welche
    # Konten es gibt.
    zeilen = server._q(
        "select name, email, aktiv, reset_zuletzt from benutzer where name = %s",
        (name,)) if name else []
    if zeilen and zeilen[0]["aktiv"] and (zeilen[0]["email"] or "").strip():
        if passwort_reset.bremse_greift(zeilen[0]["reset_zuletzt"]):
            LOG.info("Passwort-Link angefordert, Bremse greift")
        else:
            # NUR EIN ZETTEL - diese Oberflaeche sendet nicht.
            #
            # Der erste Anlauf rief hier `mail_dispatch.senden` auf. Der
            # Import gelang (dasselbe Image), der Versand konnte NIE
            # gelingen: `sales-ui` hat keine SMTP-Umgebung, und nach T5a
            # darf sie auch keine bekommen - Sendemacht liegt
            # ausschliesslich bei den Versand-Diensten, damit das
            # Freigabe-Tor die DATENBANK bleibt. Gemessen am 17.09.2026,
            # am lebenden System, nachdem der Betreiber „es kommt nichts
            # an" meldete.
            #
            # Den Token erzeugt der VERSENDER, nicht diese Seite. Damit
            # erreicht der Klartext die Datenbank nie - auch nicht fuer
            # die Sekunden, die ein Zettel hier liegt.
            server._q(
                "insert into benutzer_mails (benutzer, art) "
                "values (%s, 'passwort_reset') returning id",
                (zeilen[0]["name"],))
            # Die Bremse zaehlt ab jetzt: ein Zettel liegt, eine Mail wird
            # versucht. Scheitert der Versand endgueltig, raeumt der
            # Versender sie wieder weg - sonst bliebe der Ausgesperrte fuer
            # einen FREMDEN Fehler eine Viertelstunde laenger ausgesperrt.
            # Genau das ist am 17.09.2026 passiert, und die immer gleiche
            # Antwort der Seite hat es verborgen.
            server._q("update benutzer set reset_zuletzt = now() "
                      "where name = %s returning name", (zeilen[0]["name"],))
            LOG.info("Passwort-Link beauftragt")
    else:
        LOG.info("Passwort-Link angefordert, kein brauchbares Konto")
    return _reset_seite(_RESET_ANTWORT, art="meta")


def _neu_seite(name: str, token: str, meldung: str = "",
               art: str = "fehler", status: int = 200) -> HTMLResponse:
    hinweis = f'<p class="{art}">{_e(meldung)}</p>' if meldung else ""
    rumpf = (
        f"{hinweis}"
        f'<form method="post" action="/passwort-neu">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        f'<input type="hidden" name="name" value="{_e(name)}">'
        f'<input type="hidden" name="token" value="{_e(token)}">'
        f'<p><label>Neues Passwort<br><input type="password" name="passwort" '
        f'autocomplete="new-password" autofocus></label></p>'
        f'<p><label>Noch einmal<br><input type="password" name="passwort2" '
        f'autocomplete="new-password"></label></p>'
        f'<p><button type="submit">Passwort setzen</button></p>'
        f'</form>')
    return _seite("Neues Passwort", rumpf, status=status)


def _token_konto(name: str, token: str):
    """Das Konto zu einem GUELTIGEN Token - oder None. Prueft alles."""
    if not name or not token:
        return None
    zeilen = server._q(
        "select name, rolle, aktiv, reset_hash, reset_bis from benutzer "
        "where name = %s", (name,))
    if not zeilen or not zeilen[0]["aktiv"]:
        return None
    z = zeilen[0]
    if not passwort_reset.token_stimmt(token, z["reset_hash"] or ""):
        return None
    if passwort_reset.abgelaufen(z["reset_bis"]):
        return None
    return z


_TOKEN_TOT = ("Dieser Link gilt nicht mehr — er ist abgelaufen oder wurde "
              "schon benutzt. Fordere unter „Passwort vergessen“ einen "
              "neuen an.")


@_gesichert_seite
async def passwort_neu(request):
    if request.method != "POST":
        name = request.query_params.get("name", "")
        token = request.query_params.get("token", "")
        if _token_konto(name, token) is None:
            return _seite("Neues Passwort",
                          f'<p class="fehler">{_e(_TOKEN_TOT)}</p>'
                          f'<p class="meta"><a href="/passwort-vergessen">'
                          f'Neuen Link anfordern</a></p>', status=400)
        return _neu_seite(name, token)

    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche.")
    name = str(form.get("name") or "")
    token = str(form.get("token") or "")
    konto = _token_konto(name, token)
    if konto is None:
        return _seite("Neues Passwort",
                      f'<p class="fehler">{_e(_TOKEN_TOT)}</p>'
                      f'<p class="meta"><a href="/passwort-vergessen">'
                      f'Neuen Link anfordern</a></p>', status=400)

    passwort = str(form.get("passwort") or "")
    if passwort != str(form.get("passwort2") or ""):
        return _neu_seite(name, token, "Die beiden Eingaben sind nicht gleich.")
    grund = passwort_reset.passwort_taugt(passwort)
    if grund:
        return _neu_seite(name, token, grund)

    # Setzen UND den Token loeschen - in einem Schritt, damit derselbe Link
    # nie ein zweites Mal traegt.
    server._q(
        "update benutzer set passwort_hash = %s, reset_hash = null, "
        "reset_bis = null where name = %s returning name",
        (_passwort_hashen(passwort), konto["name"]))
    LOG.info("Passwort neu gesetzt: %s", konto["name"])
    # KEINE Sitzung von hier aus. Wer gerade ein Passwort gesetzt hat, soll
    # es einmal benutzen - das ist die Probe, ob es angekommen ist.
    return _seite(
        "Neues Passwort",
        '<p class="meta">Das Passwort steht. Melde dich jetzt damit an.</p>'
        '<p><a href="/login">Zur Anmeldung</a></p>')


async def logout(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche.")
    antwort = RedirectResponse("/login", status_code=303)
    antwort.delete_cookie(SITZUNG_COOKIE, path="/")
    return antwort



WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag")
WOCHENTAGE_KURZ = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember")
HEUTE_JE_ART = 3          # offene Entwuerfe je Art auf der Startseite
HEUTE_TERMINE = 4         # Kalendereintraege in der rechten Spalte
HEUTE_TERMINE_TAGE = 14
# Mangel 3 (Schlusspruefung, 10.09.2026): fuer den ehrlichen Kopfsatz auf der
# Startseite braucht `_einzuordnende` eine deutlich groessere Grenze als der
# Chat-/Anzeige-Deckel EINORDNUNG_LIMIT (25) — sonst zaehlt „N Posten warten
# auf dich" bei mehr als 25 unbekannten Absendern wieder zu wenig, dieselbe
# Unehrlichkeit wie bei den Terminanfragen (Aufgabe 8). Kein echtes
# `count(*)`, weil die Aufteilung in `neu`/`bereits_gefragt`/`aufgeloest`
# erst je Zeile in Python entschieden wird (`_lead_mit_gleicher_nummer`) —
# das waere in SQL eine Duplizierung derselben Normalisierungslogik. 1000
# ist grosszuegig fuer den tatsaechlichen Bestand eines Sammelkontakts; ist
# der Betrieb darueber, zaehlt der Kopfsatz wieder zu wenig (kein `count(*)`
# moeglich, siehe oben) — dieser Rest-Deckel ist dokumentiert, nicht behoben.
EINORDNUNG_ZAEHL_LIMIT = 1000
FREIGABE_ARTEN = (("whatsapp", "WhatsApp"), ("linkedin", "LinkedIn"),
                  ("email", "E-Mail"))


def _heute_kalender() -> str:
    """Die naechsten Termine aus dem Kalender (CalDAV), Ortszeit. Ein
    Lesefehler steht als Satz da — die Startseite faellt nicht mit ihm.

    Bleibt bewusst auf `kalender.termine_lesen()` statt `server.belegungen()`
    (Aufgabe 6, Spec §2.5): die Startseite „Heute" zeigt absichtlich nur den
    eigenen Tag, nicht die Team-Sicht. Das ist eine Entscheidung, keine
    Auslassung — die Team-Sicht mit allen Quellen steht auf /kalender.
    """
    try:
        termine, fehler = kalender.termine_lesen(0, HEUTE_TERMINE_TAGE)
    except Exception as e:
        termine, fehler = [], f"Kalender nicht lesbar: {e}"
    if fehler:
        return f'<p class="meta">{_e(fehler)}</p>'
    jetzt = datetime.now(ZEITZONE)
    kommend = []
    for t in termine:
        beginn = t.get("beginn")
        if not isinstance(beginn, datetime):
            continue
        if ZEITZONE is None:
            beginn = beginn.replace(tzinfo=None)
        elif beginn.tzinfo is None:
            beginn = beginn.replace(tzinfo=ZEITZONE)
        else:
            beginn = beginn.astimezone(ZEITZONE)
        if beginn < jetzt.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        kommend.append((beginn, str(t.get("titel") or "(ohne Titel)")))
    kommend.sort(key=lambda p: p[0])
    if not kommend:
        return '<p class="meta">Nichts in den nächsten zwei Wochen.</p>'
    zeilen = []
    for beginn, titel in kommend[:HEUTE_TERMINE]:
        klasse = " heute" if beginn.date() == jetzt.date() else ""
        wann = (f"{WOCHENTAGE_KURZ[beginn.weekday()]} "
                f"{beginn.strftime('%H:%M')}")
        meta = ("heute" if klasse else
                f"{beginn.day}. {MONATE[beginn.month - 1]}")
        zeilen.append(f'<div class="termin"><span class="zeit{klasse}">'
                      f'{_e(wann)}</span><span>{_e(titel)}'
                      f'<br><span class="meta">{_e(meta)}</span></span></div>')
    zeilen.append('<p class="meta"><a href="/kalender">Ganzen Kalender '
                  'öffnen</a></p>')
    return "".join(zeilen)


def _heute_whatsapp() -> str:
    sitzungen, fehler = _openwa_lesen("/api/sessions")
    if fehler:
        return f'<p class="meta">{_e(fehler)}</p>'
    passende = [s for s in (sitzungen or [])
                if not OPENWA_SESSION_ID or str(s.get("id")) == OPENWA_SESSION_ID]
    if not passende:
        return '<p class="meta">OpenWA kennt die Sitzung nicht.</p>'
    zustand = str(passende[0].get("status") or "unbekannt")
    wort, klasse, _ = WA_ZUSTAND.get(zustand, (zustand, "warnung", ""))
    return (f'<p><span class="badge {_e(klasse)}">{_e(wort)}</span> '
            f'<span class="meta">seit {_e(_wa_zeit(passende[0].get("connectedAt")))}'
            f'</span></p><p class="meta"><a href="/whatsapp">Zustand und '
            f'Kette</a></p>')


def _heute_posteingang() -> str:
    try:
        daten = json.loads(server.posteingang())
    except Exception as e:
        return f'<p class="meta">Posteingang nicht lesbar: {_e(e)}</p>'
    anzahl = int(daten.get("anzahl_unbeantwortet") or 0)
    if not anzahl:
        return '<p class="meta">Keine unbeantworteten Eingänge.</p>'
    namen = [str(e.get("kontakt") or "?") for e in daten.get("eintraege") or []]
    aelteste = max((float(e.get("wartet_stunden") or 0)
                    for e in daten.get("eintraege") or []), default=0)
    return (f'<p><b class="mono">{anzahl}</b> unbeantwortet, älteste seit '
            f'{aelteste:.0f} h</p>'
            f'<p class="meta">{_e(", ".join(namen[:3]))}'
            f'{" …" if len(namen) > 3 else ""}</p>'
            f'<p class="meta"><a href="/posteingang">Posteingang öffnen</a></p>')


def _heute_pipeline() -> str:
    zeilen = server._q(
        "select l.status, count(*) n from leads l where not "
        + server._archiv_sql("l.enrichment") + " group by l.status")
    zahlen = {}
    for z in zeilen:
        stufe = server._stufe_lesen(z["status"])
        zahlen[stufe] = zahlen.get(stufe, 0) + int(z["n"])
    kacheln = "".join(
        f'<div class="kachel"><b>{zahlen.get(s, 0)}</b>'
        f'<span>{_e(s)}</span></div>'
        for s in server.PIPELINE_STUFEN[:-2])
    return (f'<div class="kacheln">{kacheln}</div>'
            f'<p class="meta"><a href="/pipeline">Pipeline öffnen</a></p>')


@_gesichert_seite
async def heute(request):
    """Startseite (UI-Plan Schritt 2, 02.09.2026): was eine Entscheidung
    braucht, links — Freigaben je Art, Wiedervorlagen, Einordnung; die Lage
    rechts — Kalender, WhatsApp, Posteingang, Pipeline. Jede Zahl kommt aus
    derselben Quelle wie die Seite, auf die sie verweist."""
    pending = server._q(
        "select d.id, d.channel, d.recipient, d.body, d.media_ref, d.subject, d.cc, "
        "       extract(epoch from (now() - d.created_at)) / 3600 as alter_h, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'pending' order by d.created_at desc")
    je_art = {art: [] for art, _ in FREIGABE_ARTEN}
    for z in pending:
        je_art.setdefault(str(z["channel"]), []).append(z)
    # Anzeige bleibt gedeckelt (Kacheln/Karten sollen nicht endlos werden),
    # aber die Kopfzeile zaehlt ab hier die ECHTE Gesamtzahl (Mangel 3,
    # Schlusspruefung 10.09.2026): `termine_offen` allein hat `limit 5`,
    # `_offene_wiedervorlagen` `limit 200` — beide gross genug fuer die
    # Anzeige, aber „N Posten warten auf dich" log bei mehr als dem Deckel
    # wieder zu wenig, dieselbe Unehrlichkeit wie in Aufgabe 8, nur an zwei
    # weiteren Stellen. Drei zusaetzliche Zaehlabfragen fallen bei einer
    # Startseite, die ohnehin mehrfach abfragt, nicht ins Gewicht.
    termine_offen = server._q(
        "select l.id as lead_id, l.name, a.payload from activities a "
        "left join leads l on l.id = a.lead_id "
        "where a.type = 'termin' and coalesce(a.payload->>'datum', '') = '' "
        "order by a.created_at desc limit 5")
    termine_offen_gesamt = server._q(
        "select count(*) as n from activities a where a.type = 'termin' "
        "and coalesce(a.payload->>'datum', '') = ''")[0]["n"]
    wiedervorlagen = _offene_wiedervorlagen()
    wiedervorlagen_gesamt = server._q(
        "select count(*) as n from activities w where w.type = 'wiedervorlage' "
        "and not exists (select 1 from activities e where "
        "e.type = 'wiedervorlage_erledigt' "
        "and e.payload->>'wiedervorlage_id' = w.id::text)")[0]["n"]
    # `_einzuordnende` teilt Zeilen erst in Python (`_lead_mit_gleicher_
    # nummer`) in neu/bereits_gefragt/aufgeloest auf — ein echtes `count(*)`
    # muesste diese Normalisierungslogik in SQL duplizieren. Stattdessen ein
    # deutlich groesserer Deckel als der Chat-/Anzeige-Deckel EINORDNUNG_
    # LIMIT (siehe EINORDNUNG_ZAEHL_LIMIT); auf dieser Seite wird ohnehin
    # nur gezaehlt, keine Liste gerendert.
    koerbe = server._einzuordnende(limit=EINORDNUNG_ZAEHL_LIMIT,
                                   text_max=EINORDNUNG_TEXT_MAX)
    einordnung_offen = len(koerbe["neu"]) + len(koerbe["bereits_gefragt"])

    jetzt = datetime.now(ZEITZONE)
    # `termine_offen` gehoert in die Summe: es stand eine Zeile weiter
    # oben schon bereit und wurde nur in der Anzeige benutzt. Dadurch
    # meldete die Kopfzeile „1 Entscheidung … Alles andere laeuft",
    # waehrend zwei Terminanfragen ohne Datum darunter standen
    # (gemessen 10.09.2026).
    posten = []
    if pending:
        posten.append(f"{len(pending)} Entwurf" if len(pending) == 1
                      else f"{len(pending)} Entwürfe")
    if einordnung_offen:
        posten.append(f"{einordnung_offen} Einordnung" if einordnung_offen == 1
                      else f"{einordnung_offen} Einordnungen")
    if termine_offen_gesamt:
        posten.append(f"{termine_offen_gesamt} Terminanfrage"
                      if termine_offen_gesamt == 1
                      else f"{termine_offen_gesamt} Terminanfragen")
    if wiedervorlagen_gesamt:
        posten.append(f"{wiedervorlagen_gesamt} Wiedervorlage"
                      if wiedervorlagen_gesamt == 1
                      else f"{wiedervorlagen_gesamt} Wiedervorlagen")
    offen = (len(pending) + wiedervorlagen_gesamt + einordnung_offen
             + termine_offen_gesamt)
    satz = ("Nichts wartet auf dich. Alles läuft." if not offen else
            f"{offen} Posten warten auf dich: {', '.join(posten)}."
            if offen > 1 else f"{posten[0]} wartet auf dich.")
    haupt = [f'<p class="meta">{WOCHENTAGE[jetzt.weekday()]}, {jetzt.day}. '
             f'{MONATE[jetzt.month - 1]} {jetzt.year} · '
             f'{jetzt.strftime("%H:%M")}</p><p>{_e(satz)}</p>']

    haupt.append('<h2>Freigaben</h2><div class="arten">')
    for art, name in FREIGABE_ARTEN:
        haupt.append(f'<span class="art">'
                     f'<span class="badge {_e(art)}">{_e(name)}</span>'
                     f'<b>{len(je_art.get(art, []))}</b></span>')
    haupt.append(f'<span class="art"><span class="badge termin">Termine</span>'
                 f'<b>{termine_offen_gesamt}</b></span>'
                 f'<a href="/freigaben">Alle Freigaben</a></div>')
    # Chips und Satz speisen aus denselben Zahlen (Betreiber-Klarstellung
    # 10.09.2026): der Chip „Termine 2" und „Keine offenen Entwürfe" kamen
    # bisher aus getrennten Rechnungen (`pending` allein) und konnten sich
    # deshalb widersprechen.
    if not pending and not termine_offen_gesamt:
        haupt.append("<p>Keine offenen Entwürfe.</p>")
    for art, name in FREIGABE_ARTEN:
        zeilen = je_art.get(art, [])
        for z in zeilen[:HEUTE_JE_ART]:
            haupt.append(_entwurf_karte_offen(z))
        if len(zeilen) > HEUTE_JE_ART:
            haupt.append(f'<p class="meta">+ {len(zeilen) - HEUTE_JE_ART} '
                         f'weitere {_e(name)}-Entwürfe unter '
                         f'<a href="/freigaben">Freigaben</a>.</p>')
    for art in je_art:
        if art not in dict(FREIGABE_ARTEN):
            for z in je_art[art][:HEUTE_JE_ART]:
                haupt.append(_entwurf_karte_offen(z))
    if termine_offen:
        haupt.append('<h2>Termine ohne festes Datum</h2>')
        for z in termine_offen:
            last = z["payload"] or {}
            voll = str(last.get("inhalt") or last.get("thema") or "")
            haupt.append(
                f'<div class="karte"><b><a href="/kontakte/{_e(z["lead_id"])}">'
                f'{_e(z["name"] or "?")}</a></b> '
                f'<span class="meta" title="{_e(voll)}">{_e(_kurz(voll, 160))}'
                f'</span> · <a href="/kalender">im Kalender</a></div>')
        # Die Kacheln bleiben gedeckelt (limit 5) — steht die Gesamtzahl im
        # Kopfsatz hoeher, muss sichtbar sein, dass hier nur ein Teil steht
        # (sonst fragt der Betreiber sich, wo die uebrigen sind).
        if termine_offen_gesamt > len(termine_offen):
            haupt.append(f'<p class="meta">{len(termine_offen)} von '
                         f'{termine_offen_gesamt} gezeigt — den Rest zeigt '
                         f'<a href="/freigaben">Freigaben</a>.</p>')

    haupt.append(f'<h2>Wiedervorlagen ({wiedervorlagen_gesamt})</h2>')
    if wiedervorlagen:
        haupt.append(_wiedervorlagen_tabelle(wiedervorlagen[:5]))
        if wiedervorlagen_gesamt > 5:
            gezeigt_auf_seite = min(wiedervorlagen_gesamt, WIEDERVORLAGEN_MAX)
            haupt.append(f'<p class="meta"><a href="/wiedervorlagen">Alle '
                         f'{gezeigt_auf_seite} Wiedervorlagen</a></p>')
    else:
        haupt.append("<p>Keine offene Wiedervorlage.</p>")

    haupt.append(f'<h2>Einordnung ({einordnung_offen})</h2>')
    haupt.append(
        f'<p>{"Kein unbekannter Absender wartet." if not einordnung_offen else f"{einordnung_offen} unbekannte Absender warten auf eine Entscheidung."} '
        f'<a href="/einordnung">Einordnung öffnen</a></p>')

    rand = (f'<div><h2>Kalender</h2>{_heute_kalender()}</div>'
            f'<div><h2>WhatsApp</h2>{_heute_whatsapp()}</div>'
            f'<div><h2>Posteingang</h2>{_heute_posteingang()}</div>'
            f'<div><h2>Pipeline</h2>{_heute_pipeline()}</div>')
    return _seite("Heute",
                  f'<div class="heute"><div class="haupt">{"".join(haupt)}'
                  f'</div><aside class="rand">{rand}</aside></div>')


app = Starlette(routes=[
    Route("/", heute),
    # Vor allen Platzhalter-Routen (z. B. `/kontakte/{lead_id}`), damit
    # kein `{...}`-Segment sie je abfangen kann.
    Route("/favicon.ico", favicon),
    Route("/freigaben", inbox),
    Route("/freigaben/verlauf/{art}", freigaben_verlauf),
    Route("/aktion/freigeben", aktion_freigeben, methods=["POST"]),
    Route("/aktion/ablehnen", aktion_ablehnen, methods=["POST"]),
    Route("/aktion/bearbeiten", aktion_bearbeiten, methods=["POST"]),
    Route("/aktion/erneut-freigeben", aktion_erneut_freigeben,
          methods=["POST"]),
    Route("/aktion/verwerfen", aktion_verwerfen, methods=["POST"]),
    # Eigene Route fuer den zweiten Schritt, wie bei Einordnung und
    # Kontaktarchiv: der ausdrueckliche Klick haengt nicht als Feld an dem
    # Formular, das ihn ausgeloest hat.
    Route("/aktion/verwerfen-bestaetigen", aktion_verwerfen_bestaetigen,
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
    Route("/kontakte/freigeben", aktion_kontakt_freigeben,
          methods=["POST"]),
    Route("/kontakte/freigabe-entziehen",
          aktion_kontakt_freigabe_entziehen, methods=["POST"]),
    Route("/kontakte/autonomie", aktion_kontakt_autonomie,
          methods=["POST"]),
    Route("/kontakte/stufe", aktion_kontakt_stufe, methods=["POST"]),
    Route("/kontakte/privat", aktion_kontakt_privat, methods=["POST"]),
    Route("/kontakte/privat-bestaetigen", aktion_kontakt_privat_bestaetigen,
          methods=["POST"]),
    Route("/kontakte/privat-entziehen", aktion_kontakt_privat_entziehen,
          methods=["POST"]),
    Route("/pipeline", pipeline),
    Route("/ergebnisse", ergebnisse),
    Route("/kalender", kalender_seite),
    Route("/kalender/absagen", aktion_termin_absagen, methods=["POST"]),
    Route("/kalender/verschieben", aktion_termin_verschieben,
          methods=["POST"]),
    Route("/team/kalender", team_kalender),
    Route("/team/kalender/verbinden", aktion_kalender_verbinden,
          methods=["POST"]),
    Route("/team/kalender/entfernen", aktion_kalender_entfernen,
          methods=["POST"]),
    Route("/team/laden-anlegen", laden_anlegen_seite),
    Route("/team/laden-anlegen/anfordern", aktion_laden_anlegen,
          methods=["POST"]),
    Route("/team/tailscale-einladen", tailscale_einladen_seite),
    Route("/team/tailscale-einladen/anfordern", aktion_tailscale_einladen,
          methods=["POST"]),
    Route("/whatsapp", whatsapp),
    Route("/whatsapp/verbinden", aktion_whatsapp_verbinden, methods=["POST"]),
    Route("/kontakte/wiederherstellen", aktion_kontakt_wiederherstellen,
          methods=["POST"]),
    Route("/kontakte/profil-anfordern", aktion_profil_anfordern,
          methods=["POST"]),
    Route("/kontakte/{lead_id}", kontakt_detail),
    Route("/posteingang", posteingang),
    Route("/einordnung", einordnung),
    Route("/einordnung/nachrichten/{kennung}", einordnung_nachrichten),
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
    Route("/wiedervorlagen/setzen", aktion_wiedervorlage_setzen,
          methods=["POST"]),
    Route("/wiedervorlagen/erledigt", aktion_wiedervorlage_erledigt,
          methods=["POST"]),
    *ui_marketing.routen(sys.modules[__name__]),
    Route("/medien", medien),
    Route("/medien/bot", aktion_medien_bot, methods=["POST"]),
    Route("/medien/datei/{name}", medien_datei),
    Route("/medien/loeschen", aktion_medien_loeschen,
          methods=["POST"]),
    Route("/medien/loeschen-bestaetigen",
          aktion_medien_loeschen_bestaetigen, methods=["POST"]),
    Route("/medien/hochladen", aktion_medien_hochladen,
          methods=["POST"]),
    Route("/login", login, methods=["GET", "POST"]),
    # Ohne Sitzung erreichbar (AnmeldeWache laesst beide durch) - wer sein
    # Passwort vergessen hat, kann sich nicht anmelden.
    Route("/passwort-vergessen", passwort_vergessen, methods=["GET", "POST"]),
    Route("/passwort-neu", passwort_neu, methods=["GET", "POST"]),
    Route("/logout", logout, methods=["POST"]),
    # HostWache zuerst (aussen): fremde Hosts scheitern vor allem anderen,
    # auch vor der Anmeldung.
], middleware=[Middleware(HostWache), Middleware(AnmeldeWache)])


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
