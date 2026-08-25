"""Zugang zur LinkedIn-API — Bilder, Videos und Beitraege auf dem eigenen Profil.

Dieses Modul VERSENDET nichts von sich aus und kennt die Datenbank nicht. Es
uebersetzt nur zwischen unserem Vokabular und dem der LinkedIn-API. Wer es
aufruft, hat die Freigabe schon geprueft — das tut `linkedin_dispatch.py`.

GEMESSEN am 22.08.2026 gegen das echte Konto (nichts davon ist geraten;
Bild- und Video-Uploads veroeffentlichen NICHTS, deshalb waren sie ohne
Risiko pruefbar):

* Versionierte API unter `https://api.linkedin.com/rest/...`. Jede Anfrage
  braucht `LinkedIn-Version: JJJJMM` und `X-Restli-Protocol-Version: 2.0.0`.
  Aktiv sind ungefaehr die letzten zwoelf Monatsstaende: 202606, 202607 und
  202608 antworteten mit 200; 202506 und aelter mit HTTP 426
  `NONEXISTENT_VERSION`. Die Version ist deshalb KONFIGURIERBAR und laeuft
  ab — `VERSION_HINWEIS` unten sagt, was zu tun ist, wenn 426 kommt.

* Bild: `POST /rest/images?action=initializeUpload` mit
  `{"initializeUploadRequest": {"owner": "<person-urn>"}}` liefert
  `value.uploadUrl` und `value.image` (die spaetere Kennung). Danach PUT der
  Bytes an `uploadUrl`.

  DER `Content-Type`-KOPF IST BEIM PUT PFLICHT. Ohne ihn antwortet LinkedIn
  mit HTTP 400 und einer HTML-Fehlerseite statt einer JSON-Meldung — eine
  Stunde Ratespiel, wenn man es nicht weiss. Mit ihm: HTTP 201. Der
  `Authorization`-Kopf ist beim PUT ueberfluessig (die Adresse ist
  vorsigniert), schadet aber nicht. Die Bildgroesse spielt keine Rolle: 8x8
  Pixel wurden genauso angenommen wie 600x400.

* Video: `POST /rest/videos?action=initializeUpload` mit zusaetzlich
  `fileSizeBytes` liefert `value.video`, `value.uploadToken` und
  `value.uploadInstructions` — eine LISTE von Abschnitten mit `firstByte`/
  `lastByte`/`uploadUrl`. Gemessen an 4.352.195 Byte: zwei Abschnitte zu je
  hoechstens 4 MiB. Jeder Abschnitt wird einzeln per PUT geschickt und
  antwortet mit einem `etag`-Kopf. Alle etags in der Reihenfolge der
  Abschnitte gehen dann an `POST /rest/videos?action=finalizeUpload` als
  `uploadedPartIds`. Auch das veroeffentlicht nichts.

  ABER: `finalizeUpload` heisst NICHT „fertig". Gemessen an einem Video von
  5.223.923 Byte stand es UNMITTELBAR nach dem Abschluss auf
  `WAITING_UPLOAD` und erst 11 Sekunden spaeter auf `AVAILABLE`. Ein
  Beitrag auf ein Video, das noch nicht `AVAILABLE` ist, prallt ab — der
  erste Videopost waere also ohne Warteschleife fehlgeschlagen.
  `video_hochladen` wartet deshalb selbst (`auf_video_warten`), und der
  Zustand wird ueber `GET /rest/videos/{urn}` gelesen (die Kennung muss
  URL-kodiert sein, sonst HTTP 400).

* Beitrag: `POST /rest/posts`. Das ist der EINZIGE Aufruf hier, der etwas
  oeffentlich macht — entsprechend ist er der einzige, der hinter der
  Freigabe eines Menschen liegt.

WAS DIESES MODUL BEWUSST NICHT KANN
-----------------------------------
Direktnachrichten. Die LinkedIn-API bietet fuer Privatprofile keinen
Nachrichtenversand; ein `linkedin`-Entwurf mit einem echten Empfaenger
bleibt Handarbeit. `linkedin_dispatch.py` fasst deshalb ausschliesslich
Beitraege an (`recipient = 'eigenes-profil'`).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS = "https://api.linkedin.com"

# Aktiver Monatsstand der versionierten API. Ueberschreibbar, weil er
# ablaeuft: LinkedIn haelt rund zwoelf Monatsstaende aktiv und antwortet
# danach mit HTTP 426.
VERSION = os.environ.get("LINKEDIN_API_VERSION", "202608").strip() or "202608"

VERSION_HINWEIS = (
    "LinkedIn hat diesen API-Monatsstand abgeschaltet (HTTP 426). Setze "
    "LINKEDIN_API_VERSION in der .env auf einen aktuellen Stand im Format "
    "JJJJMM — LinkedIn haelt jeweils rund die letzten zwoelf Monate aktiv.")

TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "").strip()

# Zeitgrenzen. Der Video-Upload schickt bis zu 4 MiB je Abschnitt ueber eine
# fremde Leitung — grosszuegiger als die JSON-Aufrufe, aber nicht unbegrenzt:
# ein haengender Upload darf den Versender nicht fuer immer blockieren.
FRIST_JSON = 30
FRIST_UPLOAD = 300

# LinkedIn-Grenze fuer den Beitragstext.
TEXT_MAXLAENGE = 3000


class LinkedInFehler(Exception):
    """Ein Aufruf ist fehlgeschlagen.

    `dauerhaft` unterscheidet, was der Aufrufer damit tun kann: ein
    dauerhafter Fehler (falscher Text, abgelaufenes Token, verbotener
    Inhalt) wird durch Wiederholen nicht besser und gehoert als
    fehlgeschlagen gebucht. Ein voruebergehender (Netz, 429, 5xx) darf
    liegenbleiben — die Entscheidung faellt aber im Dispatcher, nicht hier.

    `ungewiss` ist die dritte und heikelste Unterscheidung: WISSEN WIR
    UEBERHAUPT, OB ES PASSIERT IST? Eine Zeitueberschreitung heisst nicht
    „nicht angekommen", sondern „keine Antwort gesehen" — die Anfrage kann
    LinkedIn erreicht und der Beitrag entstanden sein, waehrend wir einen
    Fehler buchen. Beim Hochladen ist das gleichgueltig (ein Upload
    veroeffentlicht nichts). Beim Erstellen eines Beitrags ist es der
    gefaehrlichste Fall ueberhaupt: ein Wiederholungslauf stellte einen
    zweiten Beitrag auf ein oeffentliches Profil.

    Eindeutig NICHT passiert ist es nur, wenn LinkedIn geantwortet hat und
    die Antwort die Anfrage ablehnt (4xx ausser 408/429). Alles andere —
    Netzfehler, Zeitueberschreitung, 5xx, 408 — ist ungewiss.
    """

    def __init__(self, meldung, dauerhaft=True, status=None, ungewiss=False):
        super().__init__(meldung)
        self.dauerhaft = dauerhaft
        self.status = status
        self.ungewiss = ungewiss


def _kopf(zusatz=None):
    k = {"Authorization": "Bearer " + TOKEN,
         "LinkedIn-Version": VERSION,
         "X-Restli-Protocol-Version": "2.0.0"}
    if zusatz:
        k.update(zusatz)
    return k


def _ohne_token(text):
    """Das Zugriffstoken aus einer Fehlermeldung entfernen.

    Fehlerruempfe von LinkedIn spiegeln gelegentlich Anfragedaten zurueck,
    und diese Meldungen landen in `drafts.error` — einer Spalte, die die
    Oberflaeche anzeigt. Ein Token, das dort einmal steht, steht dort
    dauerhaft: auf `drafts` gibt es kein nachtraegliches Saeubern.
    """
    if TOKEN and len(TOKEN) > 8:
        text = text.replace(TOKEN, "<token>")
    return text


def _json_ruf(pfad, last, methode="POST"):
    # `last is None` heisst: Anfrage OHNE Rumpf (GET). Nicht `not last` —
    # ein leeres dict waere ein gueltiger, absichtlich leerer Rumpf, und
    # `json.dumps(None)` schickte den Text "null" als Nutzlast.
    daten = None if last is None else json.dumps(last).encode("utf-8")
    kopf = _kopf({"Content-Type": "application/json"} if daten else None)
    anfrage = urllib.request.Request(
        BASIS + pfad, data=daten, method=methode, headers=kopf)
    try:
        with urllib.request.urlopen(anfrage, timeout=FRIST_JSON) as antwort:
            rumpf = antwort.read().decode("utf-8", "replace")
            kopfzeilen = dict(antwort.headers)
            return kopfzeilen, (json.loads(rumpf) if rumpf.strip() else {})
    except urllib.error.HTTPError as e:
        rumpf = _ohne_token(e.read().decode("utf-8", "replace")[:400])
        if e.code == 426:
            raise LinkedInFehler(f"{VERSION_HINWEIS} (Version {VERSION})",
                                 dauerhaft=True, status=426)
        if e.code == 401:
            raise LinkedInFehler(
                "LinkedIn lehnt das Zugriffstoken ab (HTTP 401) — es ist "
                "abgelaufen oder zurueckgezogen (Lebensdauer rund 60 Tage). "
                "Ein neues holen: python scripts/li-token.py. Bis dahin "
                "bleiben freigegebene Beitraege liegen, es geht nichts "
                "verloren. " + rumpf,
                dauerhaft=True, status=401)
        # 429 und 5xx gehen vorbei, alles andere ist eine Aussage ueber die
        # Anfrage selbst und wird durch Wiederholen nicht richtiger.
        #
        # UNGEWISS ist etwas anderes als voruebergehend: bei 408 und 5xx hat
        # LinkedIn die Anfrage bekommen und uns keine verwertbare Aussage
        # ueber ihren Ausgang gegeben. Ein 4xx dagegen IST die Aussage — die
        # Anfrage wurde abgelehnt, es ist nichts entstanden.
        raise LinkedInFehler(f"HTTP {e.code} bei {pfad}: {rumpf}",
                             dauerhaft=not (e.code == 429 or e.code >= 500),
                             status=e.code,
                             ungewiss=(e.code == 408 or e.code >= 500))
    except TimeoutError as e:
        # Der gefaehrlichste Ausgang: die Anfrage ist raus, die Antwort haben
        # wir nie gesehen. „Zeitueberschreitung" heisst NICHT „nicht
        # angekommen".
        raise LinkedInFehler(
            f"Zeitueberschreitung bei {pfad} nach {FRIST_JSON}s — ob LinkedIn "
            f"die Anfrage ausgefuehrt hat, ist UNBEKANNT: {e}",
            dauerhaft=False, ungewiss=True)
    except urllib.error.URLError as e:
        # Auch hier: der Abbruch kann vor oder nach der Verarbeitung liegen.
        raise LinkedInFehler(f"LinkedIn nicht erreichbar: {e.reason}",
                             dauerhaft=False, ungewiss=True)


def _bytes_hochladen(url, daten, inhaltstyp):
    """PUT der Nutzbytes an eine vorsignierte Adresse. Gibt den etag zurueck.

    `inhaltstyp` ist PFLICHT — siehe Modulkopf. Er wird deshalb nicht aus
    dem Inhalt erraten, sondern vom Aufrufer verlangt.
    """
    if not inhaltstyp:
        raise LinkedInFehler("Ohne Content-Type nimmt LinkedIn keine Bytes an.")
    anfrage = urllib.request.Request(
        url, data=daten, method="PUT", headers={"Content-Type": inhaltstyp})
    try:
        with urllib.request.urlopen(anfrage, timeout=FRIST_UPLOAD) as antwort:
            return antwort.headers.get("etag") or antwort.headers.get("ETag")
    except urllib.error.HTTPError as e:
        rumpf = _ohne_token(e.read().decode("utf-8", "replace")[:200])
        raise LinkedInFehler(f"Upload abgelehnt (HTTP {e.code}): {rumpf}",
                             dauerhaft=not (e.code == 429 or e.code >= 500),
                             status=e.code)
    except urllib.error.URLError as e:
        raise LinkedInFehler(f"Upload unterbrochen: {e.reason}", dauerhaft=False)


def bild_hochladen(daten: bytes, mimetyp: str) -> str:
    """Ein Bild hochladen. Gibt die Bild-Kennung (urn:li:image:...) zurueck.

    Veroeffentlicht nichts: das Bild ist ein privater Vermoegenswert, bis ein
    Beitrag darauf verweist.
    """
    _, antwort = _json_ruf("/rest/images?action=initializeUpload",
                           {"initializeUploadRequest": {"owner": PERSON_URN}})
    wert = antwort["value"]
    _bytes_hochladen(wert["uploadUrl"], daten, mimetyp)
    return wert["image"]


def video_hochladen(daten: bytes, mimetyp: str = "video/mp4") -> str:
    """Ein Video abschnittweise hochladen. Gibt die Video-Kennung zurueck.

    Veroeffentlicht nichts. Die Abschnittsgrenzen kommen von LinkedIn, nicht
    von uns — geschnitten wird genau dort, wo `firstByte`/`lastByte` es sagen.
    """
    _, antwort = _json_ruf("/rest/videos?action=initializeUpload", {
        "initializeUploadRequest": {
            "owner": PERSON_URN, "fileSizeBytes": len(daten),
            "uploadCaptions": False, "uploadThumbnail": False}})
    wert = antwort["value"]
    video, marke = wert["video"], wert.get("uploadToken", "")
    etags = []
    for abschnitt in wert["uploadInstructions"]:
        stueck = daten[abschnitt["firstByte"]:abschnitt["lastByte"] + 1]
        etag = _bytes_hochladen(abschnitt["uploadUrl"], stueck,
                                "application/octet-stream")
        if not etag:
            raise LinkedInFehler(
                "LinkedIn hat einen Video-Abschnitt ohne etag quittiert — "
                "ohne alle etags laesst sich der Upload nicht abschliessen.")
        etags.append(etag)
    _json_ruf("/rest/videos?action=finalizeUpload", {
        "finalizeUploadRequest": {"video": video, "uploadToken": marke,
                                  "uploadedPartIds": etags}})
    # Der Abschluss heisst NICHT „fertig". LinkedIn verarbeitet das Video
    # danach noch; ein Beitrag auf ein Video im Zustand PROCESSING prallt ab.
    # Deshalb gehoert das Warten in diese Funktion und nicht in den Aufrufer:
    # wer hier eine Kennung bekommt, bekommt eine benutzbare.
    auf_video_warten(video)
    return video


# Zustaende der Videoverarbeitung. AVAILABLE ist der einzige, in dem sich ein
# Beitrag darauf veroeffentlichen laesst.
VIDEO_FERTIG = "AVAILABLE"
VIDEO_GESCHEITERT = ("PROCESSING_FAILED", "UPLOAD_FAILED")

# Wie lange auf die Verarbeitung gewartet wird. Gemessen: zwei Videos von
# 36 s und 46 s Laufzeit standen nach wenigen Minuten auf AVAILABLE. Die
# Frist ist deshalb grosszuegig, aber endlich — ein Versender, der ewig auf
# ein Video wartet, stellt die ganze Warteschlange still.
VIDEO_FRIST_S = 240
VIDEO_TAKT_S = 5


def video_status(video_urn: str) -> str:
    """Verarbeitungsstand eines Videos. Nur Lesen."""
    pfad = "/rest/videos/" + urllib.parse.quote(video_urn, safe="")
    _, antwort = _json_ruf(pfad, None, methode="GET")
    return antwort.get("status", "")


def auf_video_warten(video_urn: str, frist_s=None, takt_s=None) -> None:
    """Warten, bis das Video verwendbar ist. Wirft sonst LinkedInFehler."""
    frist_s = VIDEO_FRIST_S if frist_s is None else frist_s
    takt_s = VIDEO_TAKT_S if takt_s is None else takt_s
    gewartet = 0.0
    while True:
        stand = video_status(video_urn)
        if stand == VIDEO_FERTIG:
            return
        if stand in VIDEO_GESCHEITERT:
            raise LinkedInFehler(
                f"LinkedIn konnte das Video nicht verarbeiten (Zustand "
                f"{stand}). Erneutes Freigeben hilft nicht — die Datei "
                f"pruefen (mp4/H.264).", dauerhaft=True)
        if gewartet >= frist_s:
            raise LinkedInFehler(
                f"Das Video ist nach {int(frist_s)} Sekunden noch nicht "
                f"verarbeitet (Zustand {stand or 'unbekannt'}). Es wurde "
                f"NICHTS veroeffentlicht. Der Entwurf kann spaeter erneut "
                f"freigegeben werden — das Video ist bereits hochgeladen.",
                dauerhaft=False)
        time.sleep(takt_s)
        gewartet += takt_s


# LinkedIn behandelt diese Zeichen im Beitragstext als Auszeichnung. Wer sie
# woertlich meint, muss sie mit Backslash schuetzen; ungeschuetzt fuehren sie
# je nach Stand zu HTTP 422 oder zu verstuemmelter Darstellung. Der Backslash
# selbst steht zuerst in der Liste — sonst wuerde er die spaeter eingefuegten
# Schutzzeichen erneut schuetzen.
SONDERZEICHEN = "\\|{}@[]()<>#*_~"


def text_schuetzen(text: str) -> str:
    """Auszeichnungszeichen im Beitragstext woertlich machen."""
    for zeichen in SONDERZEICHEN:
        text = text.replace(zeichen, "\\" + zeichen)
    return text


def beitrag_erstellen(text: str, bilder=None, video=None,
                      sichtbarkeit="PUBLIC") -> str:
    """VEROEFFENTLICHT einen Beitrag auf dem eigenen Profil.

    Der einzige Aufruf in diesem Modul, der etwas oeffentlich macht. Er wird
    ausschliesslich fuer einen Entwurf aufgerufen, den ein Mensch freigegeben
    hat.

    `bilder` ist eine Liste von Bild-Kennungen, `video` eine einzelne
    Video-Kennung. Beides zusammen geht nicht — LinkedIn kennt Beitraege mit
    Bildern ODER mit einem Video, nicht gemischt. Gibt die Beitrags-Kennung
    zurueck.
    """
    bilder = list(bilder or [])
    if bilder and video:
        raise LinkedInFehler(
            "Ein Beitrag traegt entweder Bilder oder ein Video, nicht beides.")
    if len(text) > TEXT_MAXLAENGE:
        raise LinkedInFehler(
            f"Beitragstext ist {len(text)} Zeichen lang, erlaubt sind "
            f"{TEXT_MAXLAENGE}.")
    if not PERSON_URN:
        raise LinkedInFehler("LINKEDIN_PERSON_URN ist nicht gesetzt.")

    last = {
        "author": PERSON_URN,
        "commentary": text_schuetzen(text),
        "visibility": sichtbarkeit,
        "distribution": {"feedDistribution": "MAIN_FEED",
                         "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if video:
        last["content"] = {"media": {"id": video}}
    elif len(bilder) == 1:
        last["content"] = {"media": {"id": bilder[0]}}
    elif len(bilder) > 1:
        last["content"] = {"multiImage": {
            "images": [{"id": b} for b in bilder]}}

    kopfzeilen, _ = _json_ruf("/rest/posts", last)
    # Die Beitrags-Kennung steht im Kopf, nicht im Rumpf: /rest/posts
    # antwortet mit 201 und leerem Rumpf. Kopfnamen sind laut RFC 9110
    # unabhaengig von Gross-/Kleinschreibung, deshalb wird beides geprueft.
    kennung = next(
        (w for k, w in kopfzeilen.items()
         if k.lower() in ("x-restli-id", "x-linkedin-id")), None)
    if not kennung:
        raise LinkedInFehler(
            "LinkedIn hat den Beitrag angenommen, aber keine Kennung "
            "mitgeschickt — der Versand laesst sich nicht belegen.")
    return kennung


def fehlende_konfiguration() -> list:
    """Was fehlt, damit dieses Modul arbeiten kann? Leere Liste = alles da."""
    fehlt = []
    if not TOKEN:
        fehlt.append("LINKEDIN_ACCESS_TOKEN")
    if not PERSON_URN:
        fehlt.append("LINKEDIN_PERSON_URN")
    return fehlt
