"""HTTP-Kern fuer eigene Beitraege auf weiteren Kanaelen (Spec
docs/superpowers/specs/2026-10-24-kanaele-posten-design.md).

Dieses Modul VERSENDET nichts von sich aus und kennt die Datenbank nicht.
Es macht genau eine Sache: eine Anfrage absetzen und das Ergebnis so
einordnen, dass der Dienst (kanal_dispatch.py) richtig buchen kann.

Einordnung (Muster linkedin_api.py):
* `dauerhaft` - der Anbieter hat geantwortet und die Anfrage abgelehnt
  (4xx ausser 408), oder der Schritt veroeffentlicht nichts (z. B. das
  Lesen eines Discord-Webhooks). Wiederholen macht es nicht besser, es ist
  sicher nichts entstanden.
* `ungewiss` - beim VEROEFFENTLICHEN keine verwertbare Antwort (Netzfehler,
  Zeitueberschreitung, 408, 5xx, unlesbarer Rumpf). Der Beitrag kann
  entstanden sein; ein Wiederholungslauf stellte ihn womoeglich doppelt
  auf ein oeffentliches Profil. Der Dienst sperrt deshalb jede Wiederholung.

Geheimnisse: Fehlerruempfe spiegeln gelegentlich Anfragedaten (Token,
Webhook-Adresse) zurueck, und Meldungen landen in drafts.error und
kanal_status.letzter_fehler. Jede Meldung geht deshalb durch
`ohne_geheimnisse` und nennt den Schritt, nie die URL.

`HTTP` ist austauschbar: Tests ersetzen das Modulattribut durch einen
Rekorder, damit nie ein echtes Netz beruehrt wird.
"""
import http.client
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Mapping, Sequence

from kanaele import KANAELE

# Zeitgrenzen: JSON-Aufrufe knapp, Uploads grosszuegig, aber nie unbegrenzt.
FRIST_JSON = 30.0
FRIST_UPLOAD = 300.0

RUMPF_MAX = 300
GEHEIM_MIN = 6

# Discord und dev.to sitzen hinter Cloudflare, das den urllib-Standard
# ("Python-urllib/3.x") gern abweist.
USER_AGENT = "sales-claw/1.0 (+https://vibemind.de)"

_ADRESSE = re.compile(r"https?://\S*(/bot[^/\s]+|/webhooks/\S+)")


class KanalFehler(Exception):
    """Ein Kanal-Aufruf ist fehlgeschlagen. `art` sagt dem Dienst, ob er
    sicher als fehlgeschlagen buchen darf ("dauerhaft") oder ob der Ausgang
    unbekannt ist und nie wiederholt werden darf ("ungewiss")."""

    def __init__(self, meldung: str, *, ungewiss: bool = False,
                 status: int | None = None):
        super().__init__(meldung)
        self.ungewiss = ungewiss
        self.status = status

    @property
    def art(self) -> str:
        return "ungewiss" if self.ungewiss else "dauerhaft"


@dataclass(frozen=True)
class Anfrage:
    methode: str
    url: str
    kopf: dict[str, str]
    daten: bytes | None
    frist: float


@dataclass(frozen=True)
class Antwort:
    status: int
    kopf: dict[str, str]
    rumpf: bytes


@dataclass(frozen=True)
class Medium:
    name: str
    mimetyp: str
    daten: bytes
    art: Literal["bild", "video"]


@dataclass(frozen=True)
class Beleg:
    beitrag: str
    url: str  # darf "" sein, wenn der Kanal keine oeffentliche Adresse nennt


# (zugang, text, medien, titel, schluessel) -> Beleg; schluessel = draft_id.
Sender = Callable[[Mapping[str, str], str, list[Medium], str, str], Beleg]


def _urllib_http(anfrage: Anfrage) -> Antwort:
    """Echter Aufruf. Ein HTTP-Fehlercode ist eine ANTWORT (kommt als
    Antwort zurueck); nur Netzfehler werden weitergeworfen."""
    kopf = dict(anfrage.kopf)
    if not any(k.lower() == "user-agent" for k in kopf):
        kopf["User-Agent"] = USER_AGENT
    req = urllib.request.Request(anfrage.url, data=anfrage.daten,
                                 method=anfrage.methode, headers=kopf)
    try:
        with urllib.request.urlopen(req, timeout=anfrage.frist) as r:
            return Antwort(r.status, dict(r.headers), r.read())
    except urllib.error.HTTPError as e:
        try:
            rumpf = e.read()
        except (OSError, http.client.HTTPException):
            rumpf = b""
        return Antwort(e.code, dict(e.headers or {}), rumpf)


HTTP: Callable[[Anfrage], Antwort] = _urllib_http


def ohne_geheimnisse(text: str, geheimnisse: Iterable[str]) -> str:
    """Bot-/Webhook-Adressen -> <adresse>, jeder Geheimwert (ab 6 Zeichen,
    auch JSON-maskiert) -> <geheim>. Kuerzere Werte bleiben stehen: sie
    wuerden harmlose Woerter zerschneiden und sind ohnehin kein Schluessel."""
    text = _ADRESSE.sub("<adresse>", text)
    werte = set()
    for g in geheimnisse:
        g = (g or "").strip()
        if len(g) >= GEHEIM_MIN:
            werte.add(g)
            werte.add(json.dumps(g)[1:-1])
    # Laengste zuerst, damit ein Teilwert nicht einen laengeren zerlegt.
    for g in sorted(werte, key=len, reverse=True):
        text = text.replace(g, "<geheim>")
    return text


def _anzeige(kanal: str) -> str:
    info = KANAELE.get(kanal)
    return info.anzeige if info else kanal


def ruf(anfrage: Anfrage, *, kanal: str, was: str, veroeffentlicht: bool,
        geheimnisse: Iterable[str]) -> Antwort:
    """Anfrage absetzen und einordnen (siehe Modulkopf). 2xx kommt zurueck,
    alles andere wird zu KanalFehler."""
    geheimnisse = list(geheimnisse)
    anzeige = _anzeige(kanal)
    try:
        antwort = HTTP(anfrage)
    except (TimeoutError, urllib.error.URLError, OSError,
            http.client.HTTPException):
        # "Keine Antwort" heisst NICHT "nicht angekommen".
        if veroeffentlicht:
            meldung = (f"{anzeige}: keine Antwort bei {was} – ob der Beitrag "
                       f"entstanden ist, ist UNBEKANNT")
        else:
            meldung = (f"{anzeige}: keine Antwort bei {was} – "
                       f"veröffentlicht wurde noch nichts")
        raise KanalFehler(ohne_geheimnisse(meldung, geheimnisse),
                          ungewiss=veroeffentlicht) from None

    status = antwort.status
    if 200 <= status < 300:
        return antwort
    # Erst saeubern, dann kuerzen: ein abgeschnittener halber Schluessel
    # wuerde sonst von der Ersetzung nicht mehr erkannt.
    rumpf = ohne_geheimnisse(
        " ".join(antwort.rumpf.decode("utf-8", "replace").split()), geheimnisse)
    meldung = ohne_geheimnisse(
        f"{anzeige}: HTTP {status} bei {was}: {rumpf[:RUMPF_MAX]}", geheimnisse)
    if 400 <= status < 500 and status != 408:
        raise KanalFehler(meldung, status=status)
    raise KanalFehler(meldung, ungewiss=veroeffentlicht, status=status)


def json_ruf(anfrage: Anfrage, *, kanal: str, was: str, veroeffentlicht: bool,
             geheimnisse: Iterable[str]) -> dict:
    """Wie `ruf`, liefert den Rumpf als JSON-Objekt. Ein unlesbarer Rumpf
    nach einem erfolgreichen Veroeffentlichen ist ungewiss: der Beitrag
    existiert vermutlich, aber wir kennen ihn nicht."""
    geheimnisse = list(geheimnisse)
    antwort = ruf(anfrage, kanal=kanal, was=was,
                  veroeffentlicht=veroeffentlicht, geheimnisse=geheimnisse)
    try:
        wert = json.loads(antwort.rumpf.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        wert = None
    if not isinstance(wert, dict):
        raise KanalFehler(
            f"{_anzeige(kanal)}: Antwort ohne lesbare Kennung bei {was}",
            ungewiss=veroeffentlicht, status=antwort.status)
    return wert


def _kopfwert(wert: str) -> str:
    # Anfuehrungszeichen und Zeilenumbrueche wuerden den Teilkopf sprengen.
    return wert.replace("\r", " ").replace("\n", " ").replace('"', "%22")


def multipart(felder: Mapping[str, str],
              dateien: Sequence[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """multipart/form-data-Rumpf. dateien = (feld, dateiname, mimetyp, daten).
    Gibt (rumpf, content_type) zurueck."""
    grenze = uuid.uuid4().hex
    teile: list[bytes] = []
    for name, wert in felder.items():
        teile.append(
            f'--{grenze}\r\nContent-Disposition: form-data; '
            f'name="{_kopfwert(name)}"\r\n\r\n'.encode("utf-8")
            + str(wert).encode("utf-8") + b"\r\n")
    for feld, dateiname, mimetyp, daten in dateien:
        teile.append(
            f'--{grenze}\r\nContent-Disposition: form-data; '
            f'name="{_kopfwert(feld)}"; filename="{_kopfwert(dateiname)}"\r\n'
            f'Content-Type: {_kopfwert(mimetyp)}\r\n\r\n'.encode("utf-8")
            + daten + b"\r\n")
    teile.append(f"--{grenze}--\r\n".encode("utf-8"))
    return b"".join(teile), f"multipart/form-data; boundary={grenze}"
