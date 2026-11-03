"""Gateway-Client fuer Agenten ohne Werkzeuge (OpenClaw /v1/chat/completions).

Ein Agent, ein festgepinnter Funktionsaufruf, die Argumente kommen zurueck.
Fehlerordnung wie auto._http: 502 "did not produce one" ist endgueltig (das
Gateway fragt sonst bis zum Kontextueberlauf neu an), 408/429/5xx und
Netzfehler sind voruebergehend, alles andere endgueltig. Der Token steht in
keiner Meldung. Rein: nur urllib, keine Datenbank.
"""
import http.client
import json
import socket
import urllib.error
import urllib.request

FEHLER_MAXLAENGE = 300
KEIN_FUNKTIONSAUFRUF = "did not produce one"


class GatewayFehler(Exception):
    """Endgueltig: Wiederholen liefert dasselbe."""


class GatewayTransient(Exception):
    """Spaeter erneut versuchen; nichts wurde verbucht."""


def _http(methode, url, pfad, token, timeout_s, nutzlast=None, kopf=None) -> dict:
    try:
        anfrage = urllib.request.Request(
            f"{url.rstrip('/')}{pfad}", method=methode,
            data=json.dumps(nutzlast).encode("utf-8") if nutzlast is not None else None,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}", **(kopf or {})})
        with urllib.request.urlopen(anfrage, timeout=timeout_s) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as e:      # muss vor URLError stehen
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:                    # noqa: BLE001 — Detail ist Beiwerk
            detail = ""
        if token:
            detail = detail.replace(token, "<token>")   # Gateway koennte spiegeln
        detail = " ".join(detail.split())[:FEHLER_MAXLAENGE]
        if KEIN_FUNKTIONSAUFRUF in detail:
            raise GatewayFehler(f"Gateway HTTP {e.code}: {detail}") from None
        if e.code in (408, 429) or e.code >= 500:
            raise GatewayTransient(f"Gateway HTTP {e.code}: {detail}") from None
        raise GatewayFehler(f"Gateway HTTP {e.code}: {detail}") from None
    except socket.timeout:
        raise GatewayTransient(f"Gateway Zeitueberschreitung nach {timeout_s:g} s") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise GatewayTransient(f"Gateway Zeitueberschreitung nach {timeout_s:g} s") from None
        raise GatewayTransient(
            f"Gateway nicht erreichbar: {str(e.reason)[:FEHLER_MAXLAENGE]}") from None
    except (http.client.HTTPException, OSError) as e:
        # Abbruch WAEHREND der Antwort (ConnectionResetError beim Lesen,
        # IncompleteRead bei einem Gateway-Neustart, BrokenPipe ...): urllib
        # verpackt das nicht in URLError. Es ist ein Netz-/Neustartproblem, kein
        # Fehler dieser Anfrage -> spaeter erneut. Nur der Typname: die Meldung
        # koennte Teile der Antwort enthalten.
        raise GatewayTransient(f"Gateway-Verbindung abgebrochen ({type(e).__name__})") from None
    except ValueError:                       # json.loads der Antwort
        raise GatewayFehler("Gateway-Antwort ist kein JSON") from None


def _agent_bereit(agent, url, token, timeout_s) -> None:
    """Fail-closed: ein unbekannter Agent wuerde still MIT allen Werkzeugen
    angelegt; /v1/models listet nur eingetragene."""
    try:
        daten = _http("GET", url, "/v1/models", token, timeout_s)
    except GatewayFehler as e:
        # Konfigurationsfehler des Dienstes (401/403/404), nicht dieser Post.
        raise GatewayTransient(f"Gateway verweigert die Pruefung ({e})") from None
    ids = [m.get("id") for m in daten.get("data") or [] if isinstance(m, dict)]
    if f"openclaw/{agent}" not in ids:
        raise GatewayTransient(
            f"Agent '{agent}' fehlt im Gateway - sonst liefe der Lauf mit Werkzeugen, "
            f"also nichts gesendet.")


def funktion_aufrufen(agent: str, sitzungsschluessel: str, system: str, auftrag: str,
                      funktion: dict, *, url: str, token: str,
                      timeout_s: float = 60) -> dict:
    """Ruft `agent` mit festem tool_choice auf `funktion`; liefert dessen Argumente."""
    if not sitzungsschluessel.startswith(f"agent:{agent}:"):
        # Ohne Praefix waehlt das Gateway `main` mit allen Werkzeugen (gemessen).
        raise ValueError(f"Sitzungsschluessel muss mit 'agent:{agent}:' beginnen")
    name = funktion["function"]["name"]
    _agent_bereit(agent, url, token, timeout_s)
    daten = _http("POST", url, "/v1/chat/completions", token, timeout_s, {
        "model": f"openclaw/{agent}",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": auftrag}],
        "tools": [funktion],
        "tool_choice": {"type": "function", "function": {"name": name}},
    }, {"x-openclaw-session-key": sitzungsschluessel, "x-openclaw-agent-id": agent})
    try:
        aufruf = daten["choices"][0]["message"]["tool_calls"][0]["function"]
        if aufruf.get("name") != name:
            raise GatewayFehler(f"Falsche Funktion im Aufruf: {str(aufruf.get('name'))[:60]}")
        args = json.loads(aufruf["arguments"])
    except GatewayFehler:
        raise
    except (KeyError, IndexError, TypeError, ValueError):
        raise GatewayFehler("Antwort ohne verwertbaren Funktionsaufruf") from None
    if not isinstance(args, dict):
        raise GatewayFehler("Funktionsargumente sind kein Objekt")
    return args
