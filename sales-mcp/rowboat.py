"""rowboat — Lesezugriff auf die VibeMind-Wissensbasis.

WOFUER. Der Agent soll nachschlagen koennen, was im Haus ueber ein Thema
bekannt ist — offene Ideen mit Vertriebsbezug, laufende Vorhaben, Produkt-
und Preisaussagen. Rowboat beantwortet solche Fragen aus seinem Index.

NUR LESEN. Dieses Modul stellt Fragen und nimmt Antworten entgegen. Es gibt
keine Schreibroute in die Wissensbasis — was dort landet, entscheiden
Menschen und andere Dienste, nicht dieser Bot.

NUR STANDARDBIBLIOTHEK, wie `linkedin_api`. Das Modul laesst sich damit ohne
Abhaengigkeiten in einen anderen Dienst heben, und der Container bleibt
schlank.

KEINE VORGABEWERTE — und das ist eine Sicherheitsaussage, keine Faulheit.
Die Vorlage aus dem Marketing-Space (`spaces/marketing/tools/rowboat_client.py`)
traegt Vorgaben fuer Adresse, Bearer-Token UND Projektkennung im Code. Ihre
Projekt-Vorgabe weicht von der ab, die in der VibeMind-`.env` steht: wer die
Umgebung vergisst, redet dort still mit einem ANDEREN Projekt und bekommt
plausible Antworten aus fremdem Bestand. Hier fehlt die Konfiguration
stattdessen hoerbar (`fehlende_konfiguration`), und `frage` verweigert.

NAMEN DER UMGEBUNGSVARIABLEN. Gemessen am 31.08.2026 heissen sie in der
VibeMind-`.env` `ROWBOAT_URL`, `ROWBOAT_PROJECT_ID` und `ROWBOAT_API_KEY` —
die Vorlage liest `ROWBOAT_BASE_URL` und `ROWBOAT_BEARER_TOKEN`. Wer sie
woertlich uebernaehme, laese ins Leere und fiele auf die Vorgaben zurueck.
Massgeblich ist die `.env`, nicht die Vorlage.

FAIL-SOFT. Keine Funktion hier wirft. Ist Rowboat weg, langsam oder
unfreundlich, kommt `{"ok": False, "fehler": ...}` zurueck — der Agent kann
das benennen, statt dass der Werkzeugdienst abstuerzt. Wissen ist ein
Zusatz; ohne Wissen arbeitet der Bot weiter.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS = os.environ.get("ROWBOAT_URL", "").strip().rstrip("/")
PROJEKT = os.environ.get("ROWBOAT_PROJECT_ID", "").strip()
SCHLUESSEL = os.environ.get("ROWBOAT_API_KEY", "").strip()

# Rowboat schlaegt fuer eine Frage im Index nach und laesst ein Modell
# antworten — das dauert laenger als ein Datenbankgriff, aber nicht beliebig.
FRIST_S = float(os.environ.get("ROWBOAT_TIMEOUT_S", "30"))

# Was von einer fremden Fehlerseite hoechstens ins Protokoll wandert.
FEHLER_MAXLAENGE = 200


def fehlende_konfiguration() -> list:
    """Was fehlt, damit dieses Modul arbeiten kann? Leere Liste = alles da."""
    fehlt = []
    if not BASIS:
        fehlt.append("ROWBOAT_URL")
    if not PROJEKT:
        fehlt.append("ROWBOAT_PROJECT_ID")
    if not SCHLUESSEL:
        fehlt.append("ROWBOAT_API_KEY")
    return fehlt


def _ohne_schluessel(text: str) -> str:
    """Der Schluessel darf nie in einer Meldung stehen.

    Fehlermeldungen landen im Protokoll und im Chat des Betreibers. Eine
    fremde Fehlerseite kann den mitgeschickten Bearer-Wert zurueckwerfen —
    dann steht er sonst dauerhaft in `activities`.
    """
    if SCHLUESSEL and SCHLUESSEL in text:
        text = text.replace(SCHLUESSEL, "<schluessel>")
    return text


def frage(text: str, *, frist_s: float = None) -> dict:
    """Eine Frage an die Wissensbasis. Wirft nie.

    Rueckgabe:
        {"ok": True,  "antwort": str, "dauer_ms": int}
        {"ok": False, "fehler": str,  "dauer_ms": int}

    Eine leere Antwort ist KEIN Fehler: Rowboat weiss zu diesem Thema nichts,
    und das ist eine gueltige Auskunft.
    """
    fehlt = fehlende_konfiguration()
    if fehlt:
        return {"ok": False, "dauer_ms": 0,
                "fehler": "Rowboat ist nicht eingerichtet, es fehlt: "
                          + ", ".join(fehlt)}

    ziel = f"{BASIS}/api/v1/{urllib.parse.quote(PROJEKT, safe='')}/chat"
    nutzlast = json.dumps({"messages": [{"role": "user", "content": text}]}).encode("utf-8")
    anfrage = urllib.request.Request(
        ziel, data=nutzlast, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {SCHLUESSEL}"})

    beginn = time.time()

    def _dauer() -> int:
        return int((time.time() - beginn) * 1000)

    try:
        with urllib.request.urlopen(anfrage, timeout=frist_s or FRIST_S) as antwort:
            roh = antwort.read() or b"{}"
    except urllib.error.HTTPError as e:
        rumpf = b""
        try:
            rumpf = e.read() or b""
        except Exception:                      # noqa: BLE001 — Rumpf ist Beiwerk
            pass
        auszug = rumpf[:FEHLER_MAXLAENGE].decode("utf-8", "replace")
        return {"ok": False, "dauer_ms": _dauer(),
                "fehler": _ohne_schluessel(f"Rowboat antwortet HTTP {e.code}: {auszug}")}
    except Exception as e:                     # noqa: BLE001 — auch Netz, DNS, Frist
        return {"ok": False, "dauer_ms": _dauer(),
                "fehler": _ohne_schluessel(f"Rowboat nicht erreichbar "
                                           f"({type(e).__name__}: {e})")}

    dauer = _dauer()
    try:
        gelesen = json.loads(roh)
    except Exception as e:                     # noqa: BLE001
        auszug = roh[:FEHLER_MAXLAENGE].decode("utf-8", "replace")
        return {"ok": False, "dauer_ms": dauer,
                "fehler": _ohne_schluessel(f"Rowboat schickt kein JSON ({e}): {auszug}")}

    # Rowboat hat drei Namen fuer dasselbe Feld, je nach Aufrufweg.
    antwort_text = ""
    if isinstance(gelesen, dict):
        for feld in ("response", "message", "text"):
            wert = gelesen.get(feld)
            if isinstance(wert, str) and wert:
                antwort_text = wert
                break

    return {"ok": True, "antwort": antwort_text, "dauer_ms": dauer}
