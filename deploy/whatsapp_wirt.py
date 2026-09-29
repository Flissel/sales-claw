#!/usr/bin/env python3
"""WhatsApp eines Ladens einrichten und koppeln — der Host-Teil (29.09.2026).

  python3 deploy/whatsapp_wirt.py einrichten <laden>
      OpenWA des Ladens starten, Admin-Schluessel, Sitzung und einen
      Nur-Lese-Schluessel anlegen und in die Umgebungsdatei schreiben.
      Idempotent: was schon steht, bleibt. Laeuft beim Laden anlegen mit
      und einmal von Hand fuer Laeden, die es vorher gab (Ivan).

  python3 deploy/whatsapp_wirt.py koppeln
      Alle 20 s per systemd (sales-whatsapp-kopplung.timer). Sucht in jedem
      Laden eine offene Anfrage aus der Oberflaeche (Tabelle
      whatsapp_kopplung), schreibt bis zu 3 Minuten lang den aktuellen
      QR-Code in dieselbe Zeile und bindet nach dem Scan den Webhook an und
      startet Posteingang und Versand.

WARUM HIER UND NICHT IN DER OBERFLAECHE: OpenWA gibt den QR-Code nur einem
Schluessel, der auch senden darf (OPERATOR). Die Oberflaeche hat bewusst
keinen solchen (T5a) — das Freigabe-Tor ist die Datenbank.

GEHEIMNISSE: Schluessel gehen nie ueber argv und nie in eine Ausgabe. An
psql gehen Werte ueber die Prozessumgebung und \\getenv, an OpenWA ueber
HTTP-Header aus diesem Prozess.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
DB_CONTAINER = "debian-supabase-db-1"
KOPPEL_FENSTER_S = 180
TAKT_S = 3
ABGELAUFEN_TEXT = "Kein Scan innerhalb von 3 Minuten."


# --- Umgebungsdateien ---------------------------------------------------------

def env_lesen(pfad: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        if "=" in zeile and not zeile.lstrip().startswith("#"):
            k, v = zeile.split("=", 1)
            werte.setdefault(k.strip(), v.strip())
    return werte


def env_setzen(pfad: Path, schluessel: str, wert: str) -> None:
    """Ersetzt die ERSTE Zeile `SCHLUESSEL=` oder haengt an. Rechte bleiben."""
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    muster = re.compile(rf"^{re.escape(schluessel)}=")
    for i, z in enumerate(zeilen):
        if muster.match(z):
            zeilen[i] = f"{schluessel}={wert}"
            break
    else:
        zeilen.append(f"{schluessel}={wert}")
    modus = pfad.stat().st_mode & 0o777
    neu = pfad.with_suffix(pfad.suffix + ".neu")
    neu.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    os.chmod(neu, modus)
    os.replace(neu, pfad)


@dataclass
class Laden:
    name: str          # Praefix: sales, ivan, ...
    envdatei: Path
    schema: str
    port_openwa: int

    @property
    def openwa(self) -> str:
        return f"{self.name}-openwa"

    @property
    def basis(self) -> bool:
        return self.name == "sales"

    @property
    def compose_env(self) -> list[str]:
        # Der Basis-Laden hat keine eigene Umgebungsdatei: Compose liest .env.
        return [] if self.basis else ["--env-file", str(self.envdatei)]

    @property
    def sitzungsname(self) -> str:
        # OpenWA: 3-50 Zeichen, nur Buchstaben, Ziffern, Bindestrich.
        return "laden-" + self.name.replace("_", "-")


def laden_finden(name: str) -> Laden:
    if name == "sales":
        pfad = WURZEL / ".env"
        werte = env_lesen(pfad)
        return Laden("sales", pfad, "sales",
                     int(werte.get("PORT_OPENWA") or 12785))
    pfad = WURZEL / "deploy" / "laeden" / f"{name}.env"
    werte = env_lesen(pfad)
    if werte.get("LADEN_PRAEFIX") != name:
        raise SystemExit(f"ABBRUCH: {pfad} traegt LADEN_PRAEFIX="
                         f"{werte.get('LADEN_PRAEFIX')!r}, erwartet {name!r}.")
    return Laden(name, pfad, werte.get("SALES_DB_SCHEMA") or f"sales_{name}",
                 int(werte["PORT_OPENWA"]))


def alle_laeden() -> list[Laden]:
    laeden = [laden_finden("sales")]
    for pfad in sorted((WURZEL / "deploy" / "laeden").glob("*.env")):
        if pfad.stem == "beispiel":
            continue
        laeden.append(laden_finden(pfad.stem))
    return laeden


# --- Die Welt da draussen (im Test ersetzt) -------------------------------------

class Welt:
    def docker(self, *args: str, eingabe: str | None = None,
               umgebung: dict[str, str] | None = None) -> str:
        env = {**os.environ, **(umgebung or {})}
        r = subprocess.run(["docker", *args], input=eingabe, text=True,
                           capture_output=True, env=env, cwd=WURZEL)
        if r.returncode != 0:
            raise RuntimeError(f"docker {args[0]} scheiterte "
                               f"(Exit {r.returncode}): {r.stderr.strip()[-300:]}")
        return r.stdout

    def compose(self, laden: Laden, *args: str) -> None:
        self.docker("compose", *laden.compose_env, *args)

    def openwa(self, laden: Laden, methode: str, pfad: str, schluessel: str,
               rumpf: dict | None = None) -> tuple[int, object]:
        daten = json.dumps(rumpf).encode() if rumpf is not None else None
        anfrage = urllib.request.Request(
            f"http://127.0.0.1:{laden.port_openwa}{pfad}", data=daten,
            method=methode, headers={"X-Api-Key": schluessel,
                                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(anfrage, timeout=30) as a:
                roh = a.read()
                return a.status, (json.loads(roh) if roh else None)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def sql(self, sql: str, variablen: dict[str, str] | None = None,
            geheim: dict[str, str] | None = None) -> str:
        """psql als supabase_admin. `geheim` geht per \\getenv, nie argv."""
        args = ["exec", "-i"]
        for k in (geheim or {}):
            args += ["-e", k]
        args += [DB_CONTAINER, "psql", "-U", "supabase_admin", "-d",
                 "postgres", "-v", "ON_ERROR_STOP=1", "-tAq"]
        for k, v in (variablen or {}).items():
            args += ["-v", f"{k}={v}"]
        kopf = "".join(f"\\getenv {k.lower()} {k}\n" for k in (geheim or {}))
        return self.docker(*args, eingabe=kopf + sql, umgebung=geheim)

    def bash(self, *args: str) -> str:
        r = subprocess.run(["bash", *args], text=True, capture_output=True,
                           cwd=WURZEL)
        if r.returncode != 0:
            raise RuntimeError(f"{args[0]} scheiterte: "
                               f"{(r.stderr or r.stdout).strip()[-300:]}")
        return r.stdout

    def schlafen(self, s: float) -> None:
        time.sleep(s)


def melde(text: str) -> None:
    print(text, flush=True)


# --- einrichten ----------------------------------------------------------------

def warte_bereit(welt: Welt, laden: Laden, sekunden: int = 180) -> None:
    for _ in range(sekunden // TAKT_S):
        zustand = welt.docker("inspect", "-f", "{{.State.Health.Status}}",
                              laden.openwa).strip()
        if zustand == "healthy":
            return
        welt.schlafen(TAKT_S)
    raise RuntimeError(f"{laden.openwa} wird nicht gesund.")


def openwa_laeuft(welt: Welt, laden: Laden) -> bool:
    try:
        return welt.docker("inspect", "-f", "{{.State.Running}}",
                           laden.openwa).strip() == "true"
    except RuntimeError:
        return False


def einrichten(welt: Welt, laden: Laden) -> bool:
    """Gibt True zurueck, wenn sich an der Umgebungsdatei etwas geaendert
    hat (dann muss die Oberflaeche neu erzeugt werden)."""
    if not openwa_laeuft(welt, laden):
        melde(f"  starte {laden.openwa}")
        welt.compose(laden, "-f", "docker-compose.openwa.yml", "up", "-d",
                     "--build", "openwa")
    warte_bereit(welt, laden)

    werte = env_lesen(laden.envdatei)
    geaendert = False
    schluessel = werte.get("OPENWA_API_KEY", "")
    if not schluessel:
        schluessel = welt.docker("exec", laden.openwa, "cat",
                                 "/app/data/.api-key").strip()
        if not schluessel:
            raise RuntimeError(f"{laden.openwa} hat keinen Admin-Schluessel "
                               f"in /app/data/.api-key.")
        env_setzen(laden.envdatei, "OPENWA_API_KEY", schluessel)
        geaendert = True
        melde("  OPENWA_API_KEY eingetragen")

    sitzung = werte.get("OPENWA_SESSION_ID", "")
    if not sitzung:
        code, antwort = welt.openwa(laden, "POST", "/api/sessions", schluessel,
                                    {"name": laden.sitzungsname})
        if code == 409:
            code, liste = welt.openwa(laden, "GET", "/api/sessions", schluessel)
            antwort = next((s for s in (liste or [])
                            if s.get("name") == laden.sitzungsname), None)
        if not (isinstance(antwort, dict) and antwort.get("id")):
            raise RuntimeError(f"Sitzung anlegen scheiterte (HTTP {code}).")
        sitzung = str(antwort["id"])
        env_setzen(laden.envdatei, "OPENWA_SESSION_ID", sitzung)
        geaendert = True
        melde(f"  Sitzung {laden.sitzungsname} angelegt")

    if not werte.get("OPENWA_VIEWER_KEY"):
        code, antwort = welt.openwa(
            laden, "POST", "/api/auth/api-keys", schluessel,
            {"name": f"sales-ui {laden.name} nur lesen", "role": "viewer",
             "allowedSessions": [sitzung]})
        if not (isinstance(antwort, dict) and antwort.get("apiKey")):
            raise RuntimeError(f"Nur-Lese-Schluessel scheiterte (HTTP {code}).")
        env_setzen(laden.envdatei, "OPENWA_VIEWER_KEY", str(antwort["apiKey"]))
        geaendert = True
        melde("  OPENWA_VIEWER_KEY eingetragen")

    if geaendert:
        # Die Oberflaeche liest Sitzung und Nur-Lese-Schluessel beim Start.
        welt.compose(laden, "up", "-d", "sales-ui")
        melde("  Oberflaeche neu gestartet")
    return geaendert


# --- koppeln -------------------------------------------------------------------

def offene_anfrage(welt: Welt, laden: Laden) -> str | None:
    try:
        roh = welt.sql(
            "select id from :\"schema\".whatsapp_kopplung "
            "where status in ('angefordert','qr') "
            "order by erstellt_am limit 1;\n",
            {"schema": laden.schema}).strip()
    except RuntimeError as e:
        if "does not exist" in str(e):
            return None     # provision.sql noch nicht eingespielt
        raise
    return roh or None


def zeile_setzen(welt: Welt, laden: Laden, anfrage: str, status: str,
                 qr: str = "", fehler: str = "") -> None:
    welt.sql(
        "update :\"schema\".whatsapp_kopplung set status = :'status', "
        "qr = nullif(:'qr', ''), fehler = nullif(:'fehler', ''), "
        "aktualisiert_am = now() where id = :'id'::uuid;\n",
        {"schema": laden.schema, "status": status, "id": anfrage},
        geheim={"QR": qr, "FEHLER": fehler})


def sammelkontakt(welt: Welt, laden: Laden) -> None:
    """<laden>-inbox verweigert ohne INBOX_UNBEKANNT_LEAD_ID den Start."""
    if laden.basis or env_lesen(laden.envdatei).get("INBOX_UNBEKANNT_LEAD_ID"):
        return
    kennung = welt.sql(
        "insert into :\"schema\".leads (name, source, status) values "
        "('Unbekannte Eingaenge', 'whatsapp', 'new') returning id;\n",
        {"schema": laden.schema}).strip()
    env_setzen(laden.envdatei, "INBOX_UNBEKANNT_LEAD_ID", kennung)
    melde("  Sammelkontakt angelegt")


def webhook_anbinden(welt: Welt, laden: Laden, schluessel: str,
                     sitzung: str) -> None:
    """Nur wenn noch keiner auf <laden>-inbox zeigt: ein zweiter Webhook
    lieferte jede Nachricht doppelt in den Posteingang."""
    ziel = f"http://{laden.name}-inbox:8790/webhook"
    code, liste = welt.openwa(laden, "GET",
                              f"/api/sessions/{sitzung}/webhooks", schluessel)
    if code == 200 and any(isinstance(w, dict) and w.get("url") == ziel
                           for w in (liste or [])):
        melde("  Webhook stand schon")
        return
    welt.bash("deploy/webhook-anbinden.sh", laden.name, "--wirklich")
    melde("  Webhook angebunden")


def abschliessen(welt: Welt, laden: Laden, schluessel: str,
                 sitzung: str) -> None:
    sammelkontakt(welt, laden)
    if not laden.basis:
        welt.compose(laden, "up", "-d", "sales-inbox", "sales-dispatch")
    webhook_anbinden(welt, laden, schluessel, sitzung)


def koppeln_laden(welt: Welt, laden: Laden) -> None:
    anfrage = offene_anfrage(welt, laden)
    if not anfrage:
        return
    melde(f"{laden.name}: Anfrage {anfrage[:8]}")
    try:
        einrichten(welt, laden)
        werte = env_lesen(laden.envdatei)
        schluessel, sitzung = werte["OPENWA_API_KEY"], werte["OPENWA_SESSION_ID"]
        # 400 = laeuft schon; alles andere Unerwartete zeigt der Zustand.
        welt.openwa(laden, "POST", f"/api/sessions/{sitzung}/start", schluessel)
        for _ in range(KOPPEL_FENSTER_S // TAKT_S):
            _, s = welt.openwa(laden, "GET", f"/api/sessions/{sitzung}",
                               schluessel)
            if isinstance(s, dict) and s.get("status") == "ready":
                abschliessen(welt, laden, schluessel, sitzung)
                zeile_setzen(welt, laden, anfrage, "verbunden")
                melde(f"{laden.name}: verbunden")
                return
            code, q = welt.openwa(laden, "GET", f"/api/sessions/{sitzung}/qr",
                                  schluessel)
            if code == 200 and isinstance(q, dict) and q.get("qrCode"):
                zeile_setzen(welt, laden, anfrage, "qr", qr=str(q["qrCode"]))
            welt.schlafen(TAKT_S)
        zeile_setzen(welt, laden, anfrage, "abgelaufen", fehler=ABGELAUFEN_TEXT)
        melde(f"{laden.name}: abgelaufen")
    except Exception as e:  # noqa: BLE001 — jeder Fehler landet auf der Seite
        text = re.sub(r"owa_k1_[0-9a-f]+", "<schluessel>", str(e))[:300]
        zeile_setzen(welt, laden, anfrage, "fehler",
                     fehler=f"Das Verbinden ist gescheitert: {text}")
        melde(f"{laden.name}: FEHLER {text}")


def main(argv: list[str]) -> int:
    welt = Welt()
    if len(argv) == 3 and argv[1] == "einrichten":
        laden = laden_finden(argv[2])
        melde(f"{laden.name}: einrichten")
        einrichten(welt, laden)
        melde(f"{laden.name}: fertig")
        return 0
    if len(argv) == 2 and argv[1] == "koppeln":
        for laden in alle_laeden():
            koppeln_laden(welt, laden)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
