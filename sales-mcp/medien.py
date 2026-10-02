"""Medien-Anhaenge fuer Entwuerfe — eine Regel fuer Werkzeug und Versand.

Warum ein eigenes Modul und kein Code in server.py (gleiche Begruendung wie
`nummern.py`): `entwurf_erstellen` prueft eine Datei, BEVOR ein Entwurf
entsteht — der Dispatcher prueft sie ERNEUT unmittelbar vor dem Senden. Zwischen
Erstellung, Freigabe und Zustellung koennen Minuten liegen, und der Medienordner
ist ein Host-Bind: der Betreiber kann eine Datei dort jederzeit loeschen oder
austauschen. Beide Seiten muessen exakt dieselbe Regel anwenden, sonst gibt
jemand etwas frei, das der Versand anders bewertet. Ein Import statt zweier
Kopien; `dispatch.py` importiert `server.py`, ein Rueckimport waere ein
Zirkelimport.

GEMESSEN (openwa/upstream, ENGINE_TYPE=whatsapp-web.js) — daraus folgen die
Konstanten unten:

* Endpunkte: `POST /api/sessions/{id}/messages/send-image|send-audio|
  send-document|send-video` (message.controller.ts). Alle vier nehmen dasselbe
  DTO `SendMediaMessageDto` (dto/send-message.dto.ts). Der Dienst kennt noch
  send-text/-sticker/-voice/-location/-contact/-poll/-bulk/-template; die
  stehen bewusst nicht in ERLAUBT.
* Nutzlast: `{chatId, base64, mimetype, filename, caption}`. `base64` ist
  blankes Base64 oder eine `data:`-URI; `mimetype` ist PFLICHT, sobald `base64`
  gesetzt ist (`buildMediaInput`: BadRequest "mimetype is required when using
  base64 data"). `filename` wird nur bei Dokumenten gerendert (ohne Namen
  heisst der Anhang beim Empfaenger "file"). `caption` gilt fuer alle
  Media-Endpunkte (wwebjs-messaging.ts `sendMediaMessage` reicht sie
  unveraendert an `client.sendMessage` weiter) — deshalb genuegt EIN Aufruf je
  Entwurf, der Text reist als Bildunterschrift mit.
* Grenzen: `caption` hoechstens 1024 Zeichen (`@MaxLength(1024)` im DTO, Text
  waere 4096); Base64-Nutzlast hoechstens 50 MiB (`assertBase64WithinMediaCap`,
  Vorgabe MEDIA_DOWNLOAD_MAX_BYTES); Rumpf je Anfrage hoechstens 25 MB
  (`resolveBodyLimit`-Vorgabe, im Log des laufenden openwa bestaetigt:
  "Request body caps: 25mb per request"). Base64 blaeht um 4/3 auf — die
  25-MB-Schranke deckelt eine Datei also faktisch bei ~18,7 MB. MAX_BYTES = 15
  MB liegt bewusst darunter.
* `ptt` (Sprachnachricht) wird NICHT gesetzt: ein Anhang aus dem Medienordner
  ist eine Datei, keine aufgenommene Sprachnachricht.
"""
import os
import re

# Ueberschreibbar fuer die Testsuite (die Tests biegen das Modulattribut auf ein
# tmp-Verzeichnis um) und fuer einen abweichenden Mount. Im Betrieb ist es der
# Host-Bind `./media:/media:ro` an sales-mcp und sales-dispatch — read-only,
# damit weder Werkzeugdienst noch Dispatcher je in den Ordner schreiben koennen.
MEDIA_VERZEICHNIS = os.environ.get("MEDIA_DIR", "/media")
# Ordner fuer ERZEUGTE Unterlagen (01.09.2026): Kalenderdateien aus
# `termin_bestaetigen`. media/ bleibt der Menschen-Ordner (nur lesbar,
# Begruendung im Compose); hierhin schreibt das System selbst.
ERZEUGT_VERZEICHNIS = os.environ.get("MEDIA_ERZEUGT_DIR", "/media-erzeugt")

# 15 MB. Siehe Moduldocstring: OpenWA wuerde erst bei ~18,7 MB abriegeln, aber
# eine WhatsApp-Nachricht ist kein Dateiserver, und die Schranke soll sprechen,
# bevor der Empfaengerdienst es tut.
MAX_BYTES = 15 * 1024 * 1024

# Whitelist: Endung -> (OpenWA-Endpunkt, MIME-Typ). Was hier nicht steht, wird
# nicht angehaengt — keine Herleitung aus dem Dateiinhalt, keine Ausnahmen.
ERLAUBT = {
    ".pdf":  ("send-document", "application/pdf"),
    ".jpg":  ("send-image",    "image/jpeg"),
    ".jpeg": ("send-image",    "image/jpeg"),
    ".png":  ("send-image",    "image/png"),
    ".mp3":  ("send-audio",    "audio/mpeg"),
    ".ogg":  ("send-audio",    "audio/ogg"),
    # Video. Nachgesehen im laufenden Dienst, nicht angenommen:
    # message.controller.js traegt `Post('send-video')` mit RequireRole
    # OPERATOR und demselben `SendMediaMessageDto` wie send-image/-audio/
    # -document. Nutzlast, Bildunterschrift und Groessengrenze gelten also
    # unveraendert. Nur .mp4, kein .mov/.webm: mp4/H.264 ist das Einzige, was
    # WhatsApp auf allen Endgeraeten ohne Umkodierung abspielt.
    ".mp4":  ("send-video",    "video/mp4"),
    # Stufe 9: Kalendereinladungen. `termin_bestaetigen` legt sie nach
    # /reports ab (der einzige beschreibbare Bind) — wer eine davon
    # mitschicken will, kopiert sie von Hand nach `media\`. Der Weg ueber
    # den Menschen bleibt, `media/` bleibt `:ro`; hier steht nur, dass die
    # Endung ueberhaupt anhaengbar IST. `send-document` mit dem
    # registrierten MIME-Typ `text/calendar` (RFC 5545 §8.1): WhatsApp
    # zeigt sie als Datei, Mail-Programme als Termin.
    ".ics":  ("send-document", "text/calendar"),
}

# Gemessene Obergrenze der Bildunterschrift (DTO `@MaxLength(1024)`). Ein
# laengerer Text wuerde am Endpunkt mit HTTP 400 abprallen — das faellt lieber
# beim Erstellen des Entwurfs auf als beim Zustellen eines freigegebenen.
CAPTION_MAXLAENGE = 1024


def _reiner_dateiname(name: str) -> bool:
    """Ist das nur ein Dateiname — kein Pfad, in keiner Konvention?

    `os.path.basename` allein genuegt hier NICHT: im Linux-Container ist der
    Backslash kein Trennzeichen, `..\\windows\\system.ini` ist fuer basename ein
    voellig normaler Dateiname und kaeme unveraendert durch. Der Medienordner
    wird aber von einem Windows-Host befuellt, Eingaben in beiden Schreibweisen
    sind also zu erwarten. Deshalb wird gegen BEIDE Trennzeichen geprueft,
    bevor irgendetwas das Dateisystem beruehrt — und der Doppelpunkt gleich
    mit, der die laufwerksrelative Windows-Form (`C:datei.pdf`) traegt und in
    einem legitimen Dateinamen aus diesem Ordner ohnehin nicht vorkommen kann.
    """
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or ":" in name:
        return False
    if "\x00" in name:
        # Ein NUL-Byte wuerde erst unten in realpath() als ValueError platzen —
        # `pruefe` verspricht aber (None, fehler) statt einer Ausnahme. Hier
        # abgefangen, bevor irgendetwas das Dateisystem beruehrt.
        return False
    if name.startswith("."):
        # Auch `..foo` und versteckte Dateien bleiben draussen: der Ordner ist
        # eine Ablage fuer Unterlagen, nichts davon heisst legitim `.irgendwas`.
        return False
    return name == os.path.basename(name)


def wurzel() -> str:
    """Aufgeloester Medienordner. Zur Aufrufzeit gelesen, damit die Tests
    `MEDIA_VERZEICHNIS` umbiegen koennen."""
    return os.path.realpath(MEDIA_VERZEICHNIS)


def erzeugt_wurzel() -> str:
    return os.path.realpath(ERZEUGT_VERZEICHNIS)


def wurzeln() -> tuple:
    """Beide Quellen in RANGFOLGE (01.09.2026): erst der Menschen-Ordner,
    dann der fuer erzeugte Unterlagen.

    Der Grund fuer den zweiten Ordner: `termin_bestaetigen` legte die
    Kalenderdatei in reports/ ab — versendbar ist aber nur, was in
    media/ liegt, und dort darf ausschliesslich ein Mensch ablegen
    (Begruendung im Compose beim :ro-Bind). Die .ics war damit erzeugt
    und unbrauchbar; der Betreiber musste sie von Hand kopieren.

    Die Menschen-Regel bleibt unangetastet: media/ ist weiterhin nur
    lesbar. Daneben steht jetzt ein Ordner, in den das System selbst
    schreibt — und bei Namensgleichheit gewinnt der Mensch.
    """
    return (wurzel(), erzeugt_wurzel())


def pfad(basis: str) -> str:
    """Vollstaendiger Pfad einer bereits geprueften Datei — aus dem
    Ordner, in dem sie tatsaechlich liegt (Menschen-Ordner zuerst)."""
    for ordner in wurzeln():
        ziel = os.path.join(ordner, basis)
        if os.path.isfile(ziel):
            return ziel
    return os.path.join(wurzel(), basis)


def endpunkt_und_typ(basis: str):
    """(OpenWA-Endpunkt, MIME-Typ) zur Endung. Nur fuer gepruefte Namen."""
    return ERLAUBT[os.path.splitext(basis)[1].lower()]


def pruefe(name: str):
    """Darf diese Datei an einen Entwurf? -> (basisname, None) | (None, fehler).

    Die Reihenfolge ist Absicht: erst der Name (ohne jeden Dateizugriff), dann
    die Endung, dann das Dateisystem. Ein Traversal-Versuch beruehrt so nie
    einen Pfad ausserhalb des Ordners — auch nicht lesend.
    """
    roh = (name or "").strip()
    if not roh:
        return None, "Kein Dateiname angegeben."
    if not _reiner_dateiname(roh):
        return None, (
            f"'{roh}' ist kein reiner Dateiname. Erlaubt ist ausschliesslich "
            f"der Name einer Datei aus dem Medienordner, ohne jede Pfadangabe "
            f"(kein '/', kein '\\', kein '..'). medien_liste() zeigt, was da "
            f"liegt.")
    # `basename` ist nach der Pruefung oben ein No-op — es steht hier trotzdem,
    # weil der Wert von hier aus in `drafts.media_ref` und spaeter in einen
    # Dateizugriff geht: die Erzwingung soll an der Stelle stehen, an der der
    # Name die Funktion verlaesst, nicht nur in einer vorgelagerten Pruefung.
    basis = os.path.basename(roh)
    endung = os.path.splitext(basis)[1].lower()
    if endung not in ERLAUBT:
        return None, (
            f"Endung '{endung or '(keine)'}' ist nicht zugelassen. Erlaubt: "
            f"{', '.join(sorted(ERLAUBT))}.")

    # Beide Ordner in Rangfolge (Menschen-Ordner zuerst) — die Pruefungen
    # je Ordner bleiben unveraendert, insbesondere die Symlink-Kante.
    ziel, gefunden = os.path.join(wurzel(), basis), False
    try:
        for ordner in wurzeln():
            kandidat = os.path.join(ordner, basis)
            # Ein Symlink im Ordner, der nach draussen zeigt, waere der letzte
            # Weg aus dem Verzeichnis heraus — realpath loest ihn auf, der
            # Vergleich faengt ihn ab. (Der Bind kommt von einem Windows-Host
            # und kennt das praktisch nicht; die Kante kostet eine Zeile.)
            if not os.path.realpath(kandidat).startswith(ordner + os.sep):
                return None, (f"'{basis}' zeigt aus dem Medienordner heraus "
                              f"und wird nicht angehaengt.")
            if os.path.isfile(kandidat):
                ziel, gefunden = kandidat, True
                break
        if not gefunden:
            return None, (f"Datei '{basis}' liegt nicht im Medienordner. "
                          f"medien_liste() zeigt, was verfuegbar ist.")
        if not os.access(ziel, os.R_OK):
            return None, f"Datei '{basis}' ist nicht lesbar."
        groesse = os.path.getsize(ziel)
    except (OSError, ValueError) as e:
        # ValueError als zweite Linie: os-Funktionen werfen ihn u. a. bei
        # eingebettetem NUL — die Namenspruefung oben faengt das frueher ab,
        # aber dieses Versprechen (`(None, fehler)`, nie eine Ausnahme) soll
        # nicht an der Reihenfolge zweier Pruefungen haengen.
        return None, f"Medienordner nicht lesbar ({type(e).__name__})."
    if groesse == 0:
        return None, f"Datei '{basis}' ist leer (0 Bytes)."
    if groesse > MAX_BYTES:
        return None, (f"Datei '{basis}' ist {groesse / 1048576:.1f} MB gross — "
                      f"erlaubt sind hoechstens {MAX_BYTES // 1048576} MB.")
    return basis, None


# Terminkarten (24.09.2026, Spec §1): die ausgefuellte Karte traegt
# Kundendaten und ist fuer den Teamleiter, das Musterblatt ist ein interner
# Entwurf. Beide liegen in media-erzeugt, damit die Oberflaeche sie unter
# /medien/datei/ ausliefern kann — an einen Kunden-Entwurf duerfen sie nie.
#
# Terminkarten: jeder Name mit `terminkarte-`. Musterblaetter: NUR die Form,
# die vorlagenauftraege_pruefen erzeugt (`muster-<vorlage>-f<n>-r<n>.pdf`) —
# ein blosses `muster-` traefe auch Marketings Kunden-Unterlagen wie
# `muster-vorlage-warm-sand.pdf` (tests/test_mail_dispatch.py).
INTERN_MUSTER = re.compile(r"^(terminkarte-.*|muster-.+-f\d+-r\d+\.pdf)$", re.IGNORECASE)


# Entwurfsbilder der Gestaltungsflaechen (Newsletter-Editor): das Pult legt sie
# als gs-<hash12>.jpg in den Erzeugt-Ordner. Sie sind Zwischenstand, keine
# Medien: nicht in Listen/Picker, nicht als Anhang. `pruefe` (Anzeige unter
# /medien/datei/) laesst sie durch - der Editor zeigt Flaechen darueber.
ENTWURF_MUSTER = re.compile(r"^gs-[0-9a-f]{12}\.jpg$")


def entwurfsbild(basis: str) -> bool:
    return bool(ENTWURF_MUSTER.match(basis or ""))


def intern(basis: str) -> bool:
    """Ist das eine interne Unterlage (Terminkarte, Musterblatt)?"""
    return bool(INTERN_MUSTER.match(basis or ""))


def pruefe_anhang(name: str):
    """`pruefe` plus die Kundenanhang-Regel -> (basisname, None) | (None, fehler).

    Fuer jeden Weg, auf dem eine Datei an einen Entwurf oder in einen
    Versand geht. Die Oberflaeche (Ansehen, Loeschen, Schalter) bleibt bei
    `pruefe` — sie liefert die Karte dem Mitglied aus, nicht dem Kunden.
    """
    basis, fehler = pruefe(name)
    if fehler:
        return None, fehler
    if entwurfsbild(basis):
        return None, (f"'{basis}' ist ein Entwurfsbild einer Gestaltungsflaeche "
                      f"(Entwurfsbild) und kein Medium - es geht nicht als Anhang.")
    if intern(basis):
        return None, (f"'{basis}' ist eine interne Unterlage (Terminkarte oder "
                      f"Musterblatt) und geht nicht an Kunden - sie ist nur fuer "
                      f"das Mitglied bzw. den Teamleiter.")
    return basis, None


def pruefe_neuen_namen(name: str):
    """Darf eine Datei DIESES Namens neu abgelegt werden? -> (basis, fehler).

    Die Namenshaelfte von `pruefe`, ohne die Dateisystem-Haelfte: beim
    Hochladen gibt es die Datei ja noch nicht. Bewusst dieselben zwei
    Kanten in derselben Reihenfolge — reiner Name, dann Endung —, damit
    nicht zwei Wahrheiten darueber entstehen, was ein zulaessiger
    Medienname ist. Was hier durchkommt, muss `pruefe` anschliessend
    ebenfalls durchlassen.
    """
    roh = (name or "").strip()
    if not roh:
        return None, "Kein Dateiname angegeben."
    if not _reiner_dateiname(roh):
        return None, (
            f"'{roh}' ist kein reiner Dateiname. Erlaubt ist ausschliesslich "
            f"ein Name ohne jede Pfadangabe (kein '/', kein '\\', kein '..').")
    basis = os.path.basename(roh)
    endung = os.path.splitext(basis)[1].lower()
    if endung not in ERLAUBT:
        return None, (
            f"Endung '{endung or '(keine)'}' ist nicht zugelassen. Erlaubt: "
            f"{', '.join(sorted(ERLAUBT))}.")
    return basis, None


def liegt_schon(basis: str) -> bool:
    """Gibt es diese Datei bereits? Fuer die Rueckfrage vor dem Ueberschreiben.

    Ein stilles Ueberschreiben waere hier der teuerste Fehler: die alte
    Datei kann bereits an einem freigegebenen Entwurf haengen, und der
    Dispatcher liest sie erst beim Zustellen.
    """
    try:
        return os.path.isfile(os.path.join(wurzel(), basis))
    except (OSError, ValueError):
        return False


def lies(basis: str) -> bytes:
    """Inhalt einer geprueften Datei. Wirft OSError, wenn sie inzwischen weg
    ist — der Aufrufer (Dispatcher) macht daraus eine Fehlerbuchung."""
    with open(pfad(basis), "rb") as f:
        return f.read()


def liste(nur_anhaenge: bool = False):
    """Anhaengbare Dateien im Medienordner: [(name, groesse_bytes)], sortiert.

    `nur_anhaenge=True` (fuer das Bot-Werkzeug medien_liste) laesst die
    internen Unterlagen weg, die `pruefe_anhang` ablehnt; die Oberflaeche
    zeigt sie weiter.

    Gefiltert ueber DIESELBE Pruefung, die `entwurf_erstellen` anwendet — die
    Liste ist ein Versprechen ("genau diese Namen nimmt entwurf_erstellen"),
    also darf sie nichts anbieten, was die Pruefung dann ablehnt: versteckte
    Dateien, leere, zu grosse, nach draussen zeigende Symlinks. Ein blosser
    Whitelist-Filter hatte genau diese Luecke. Wirft OSError, wenn der Ordner
    fehlt.
    """
    namen = set()
    for ordner in wurzeln():
        try:
            namen.update(os.listdir(ordner))
        except OSError:
            # Der ERZEUGT-Ordner darf fehlen (frischer Stack, alter Mount)
            # — der Menschen-Ordner nicht: sein Fehlen ist ein echter
            # Betriebsfehler und wirft weiter.
            if ordner == wurzel():
                raise
    eintraege = []
    for name in sorted(namen):
        if entwurfsbild(name):
            continue
        basis, fehler = (pruefe_anhang if nur_anhaenge else pruefe)(name)
        if fehler is None:
            eintraege.append((basis, os.path.getsize(pfad(basis))))
    return eintraege
