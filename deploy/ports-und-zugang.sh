# Ports suchen und den Tailscale-Zugang eines neuen Ladens einrichten.
# Wird von deploy/admin-auftrag-ausfuehren.sh per `.` geladen; eigene
# Datei, damit deploy/tests/test_ports_und_zugang.sh sie mit Attrappen
# fuer ss und tailscale pruefen kann (SS/TAILSCALE/SUDO ueberschreibbar).
SS="${SS:-ss}"
TAILSCALE="${TAILSCALE:-tailscale}"
SUDO="${SUDO-sudo -n}"

# Freien Port zwischen $1 und $2 suchen; gibt ihn auf stdout aus.
freier_port() {
  local kandidat="$1" hoechstens="$2"
  local ss_ausgabe
  while [ "$kandidat" -le "$hoechstens" ]; do
    # `ss`s EIGENEN Exit-Code separat pruefen, bevor dem grep-Ergebnis
    # getraut wird: `ss ... | grep -q .` allein ist unter `pipefail` nicht
    # sicher — scheitert `ss` (z.B. Exit 2, Programm fehlt/keine
    # Berechtigung), liefert `grep -q .` auf der dadurch leeren Eingabe
    # ebenfalls "kein Treffer" (Exit 1), und `pipefail` nimmt den Exit-Code
    # des RECHTESTEN fehlschlagenden Befehls — hier grep, nicht ss. Das `!`
    # davor drehte das zu "Port frei". Nachgemessen mit einer ss-Attrappe,
    # die mit Exit 2 scheitert: die alte Fassung lieferte trotzdem einen
    # Port zurueck, als waere er frei.
    if ! ss_ausgabe="$("$SS" -tlnH "sport = :$kandidat")"; then
      echo "FEHLER: 'ss' selbst ist fehlgeschlagen — Portpruefung nicht verlaesslich." >&2
      return 1
    fi
    if ! echo "$ss_ausgabe" | grep -q .; then
      echo "$kandidat"
      return 0
    fi
    kandidat=$((kandidat + 1))
  done
  echo "FEHLER: kein freier Port zwischen $1 und $hoechstens." >&2
  return 1
}

# Alle Ports, die `tailscale serve` schon belegt, je Zeile einer.
serve_ports_belegt() {
  local json
  json="$("$TAILSCALE" serve status --json)" || {
    echo "FEHLER: 'tailscale serve status' ist fehlgeschlagen." >&2
    return 1
  }
  SERVE_JSON="$json" python3 -c '
import json, os
print("\n".join(json.loads(os.environ["SERVE_JSON"] or "{}").get("TCP") or {}))'
}

# Ziel der Serve-Regel auf Port $1 ("" wenn keine), z.B. http://127.0.0.1:8793
serve_ziel() {
  local json
  json="$("$TAILSCALE" serve status --json)" || {
    echo "FEHLER: 'tailscale serve status' ist fehlgeschlagen." >&2
    return 1
  }
  SERVE_JSON="$json" python3 -c '
import json, os, sys
web = json.loads(os.environ["SERVE_JSON"] or "{}").get("Web") or {}
for schluessel, eintrag in web.items():
    if schluessel.rsplit(":", 1)[-1] == sys.argv[1]:
        print(((eintrag.get("Handlers") or {}).get("/") or {}).get("Proxy", ""))
        break' "$1"
}

# Wie freier_port, ueberspringt aber zusaetzlich Ports, die `tailscale
# serve` schon vergeben hat: eine Serve-Regel lauscht nicht fuer ss
# sichtbar auf dem Rechner, der Port waere sonst "frei" und die Regel
# eines anderen Ladens wuerde ueberschrieben.
freier_serve_port() {
  local kandidat="$1" hoechstens="$2" belegt p
  belegt="$(serve_ports_belegt)" || return 1
  while [ "$kandidat" -le "$hoechstens" ]; do
    p="$(freier_port "$kandidat" "$hoechstens")" || return 1
    if ! grep -qx "$p" <<< "$belegt"; then
      echo "$p"
      return 0
    fi
    kandidat=$((p + 1))
  done
  echo "FEHLER: kein freier Serve-Port zwischen $1 und $hoechstens." >&2
  return 1
}

# Zugang https://<rechner>:$1 -> http://127.0.0.1:$2 einrichten und danach
# nachmessen, dass die Regel wirklich so steht. Eine schon vorhandene
# Regel mit ANDEREM Ziel wird nie ueberschrieben. `timeout`: ist Serve im
# Tailnet nicht freigeschaltet, wartet `tailscale serve` sonst auf eine
# Bestaetigung im Browser, die hier nie kommt.
zugang_einrichten() {
  local port="$1" ziel="http://127.0.0.1:$2" jetzt
  jetzt="$(serve_ziel "$port")" || return 1
  if [ -n "$jetzt" ] && [ "$jetzt" != "$ziel" ]; then
    echo "FEHLER: Serve-Port $port zeigt schon auf $jetzt." >&2
    return 1
  fi
  # $SUDO bewusst ohne Anfuehrungszeichen: "sudo -n" sind zwei Woerter,
  # im Test ist es leer.
  # shellcheck disable=SC2086
  $SUDO timeout 30 "$TAILSCALE" serve --bg --https "$port" "$ziel" >/dev/null || {
    echo "FEHLER: 'tailscale serve' fuer Port $port ist fehlgeschlagen." >&2
    return 1
  }
  jetzt="$(serve_ziel "$port")" || return 1
  if [ "$jetzt" != "$ziel" ]; then
    echo "FEHLER: Serve-Port $port zeigt nach dem Einrichten auf '$jetzt' statt $ziel." >&2
    return 1
  fi
}
