#!/usr/bin/env bash
# Traegt ein weiteres Postfach des Betreibers (GMX oder Gmail, 28.10.2026) in
# die .env des Basis-Ladens ein — nach einer Probe-Anmeldung — und erzeugt
# NUR sales-mcp (lesen, aufraeumen) und sales-mail (Antworten senden) neu.
#
#   bash ~/sales-claw/deploy/postfach-zugang.sh <gmx|gmail>
#
# Vorher beim Anbieter:
#   GMX:   Einstellungen -> POP3/IMAP Abruf -> IMAP-Zugriff erlauben.
#   Gmail: Bestaetigung in zwei Schritten an, dann App-Passwort anlegen
#          (myaccount.google.com/apppasswords). Das normale Passwort geht nicht.
#
# Sicherheit (wie deploy/kanal-zugang-eintragen.sh):
# * Das Passwort wird verdeckt gelesen (read -s) und NIE ausgegeben, auch
#   nicht teilweise. Kein set -x.
# * Es geht nie als Argument an ein Programm (ps zeigte es sonst): die Probe
#   bekommt es ueber stdin, in die Datei schreibt printf (eingebaut).
# * Die Probe meldet sich bei IMAP UND SMTP an. Scheitert eine, wird NICHTS
#   geschrieben.
# * Passwoerter enthalten oft `$`, `#` oder `!`: der Wert steht deshalb in
#   einfachen Anfuehrungszeichen — Compose nimmt ihn dann woertlich, ohne
#   ${...} aufzuloesen. Ein `'` selbst oder Steuerzeichen: Abbruch.
# * Sicherung (600), neue Datei im selben Ordner (600), mv darueber.
#
# Die Namen stehen woertlich wie in sales-mcp/postfach.py (POSTFACH_<KENNUNG>_*);
# sales-mcp/tests/test_postfaecher_zugang.py prueft Gleichlauf und Ablauf.
set +x
set -euo pipefail

ENV_DATEI="${SALES_ENV_DATEI:-$HOME/sales-claw/.env}"
PROJEKT="$(dirname "$ENV_DATEI")"
DOCKER="${DOCKER:-docker}"
PROBE_CONTAINER="${PROBE_CONTAINER:-sales-mcp}"

kennung="${1:-}"
case "$kennung" in
  gmx)   IMAP=imap.gmx.net;   SMTP=mail.gmx.net ;;
  gmail) IMAP=imap.gmail.com; SMTP=smtp.gmail.com ;;
  *)
    echo "Aufruf: $0 <gmx|gmail>" >&2
    exit 2 ;;
esac
GROSS="$(echo "$kennung" | tr '[:lower:]' '[:upper:]')"
NAME_ADRESSE="POSTFACH_${GROSS}_ADRESSE"
NAME_PASSWORT="POSTFACH_${GROSS}_PASSWORT"

if [ ! -f "$ENV_DATEI" ]; then
  echo "Env-Datei $ENV_DATEI fehlt – abgebrochen, nichts geändert." >&2
  exit 1
fi

# 1) Lesen und pruefen.
adresse=""
IFS= read -r -p "E-Mail-Adresse ($kennung): " adresse || true
adresse="${adresse%$'\r'}"
if ! [[ $adresse =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
  echo "Das ist keine E-Mail-Adresse – abgebrochen, nichts geändert." >&2
  exit 3
fi
passwort=""
IFS= read -r -s -p "Passwort ($kennung, Eingabe bleibt unsichtbar): " passwort || true
[ -t 0 ] && echo >&2
passwort="${passwort%$'\r'}"
if [ -z "$passwort" ]; then
  echo "Passwort ist leer – abgebrochen, nichts geändert." >&2
  exit 3
fi
if [[ $passwort == *"'"* ]] || [[ $passwort =~ [[:cntrl:]] ]]; then
  echo "Das Passwort enthält ' oder ein Steuerzeichen – so lässt es sich nicht sicher speichern. Abgebrochen, nichts geändert." >&2
  exit 3
fi

# 2) Probe-Anmeldung im laufenden sales-mcp (dort sind Python und Netz).
# Adresse und Passwort kommen ueber stdin, je eine Zeile. Die Meldung des
# Servers wird ausgegeben, das Passwort darin vorher unkenntlich gemacht.
PROBE='
import imaplib, smtplib, ssl, sys
adresse, passwort = sys.stdin.readline().rstrip("\n"), sys.stdin.readline().rstrip("\n")
imap_host, smtp_host = sys.argv[1], sys.argv[2]
def meldung(t):
    if isinstance(t, BaseException):
        t = t.args[0] if t.args else str(t)
    t = t.decode("utf-8", "replace") if isinstance(t, bytes) else str(t)
    return " ".join(t.replace(passwort, "***").split())[:200]
k = ssl.create_default_context()
try:
    kasten = imaplib.IMAP4_SSL(imap_host, 993, ssl_context=k)
    kasten.login(adresse, passwort)
    kasten.logout()
except Exception as e:
    print(f"IMAP-Anmeldung abgelehnt ({type(e).__name__}): {meldung(e)}")
    sys.exit(4)
try:
    s = smtplib.SMTP_SSL(smtp_host, 465, context=k, timeout=30)
    s.login(adresse, passwort)
    s.quit()
except smtplib.SMTPAuthenticationError as e:
    print(f"SMTP-Anmeldung abgelehnt ({e.smtp_code}): {meldung(e.smtp_error)}")
    sys.exit(5)
except Exception as e:
    print(f"SMTP nicht erreichbar ({type(e).__name__}): {meldung(e)}")
    sys.exit(5)
print("ok")
'
echo "Prüfe die Anmeldung bei $IMAP und $SMTP …" >&2
if ! ergebnis="$(printf '%s\n%s\n' "$adresse" "$passwort" \
      | $DOCKER exec -i "$PROBE_CONTAINER" python -c "$PROBE" "$IMAP" "$SMTP")"; then
  echo "${ergebnis:-Probe fehlgeschlagen.}" >&2
  case "$kennung" in
    gmx)   echo "Tipp: bei GMX unter Einstellungen → POP3/IMAP Abruf den Zugriff erlauben." >&2 ;;
    gmail) echo "Tipp: Gmail braucht ein App-Passwort (myaccount.google.com/apppasswords), nicht das normale." >&2 ;;
  esac
  echo "Nichts geändert." >&2
  exit 4
fi

# 3) Sicherung und neue Datei, beide nur fuer den Eigentuemer lesbar.
umask 077
stempel="$(date +%Y%m%d-%H%M%S)"
SICHERUNG="$ENV_DATEI.vor-postfach-$kennung-$stempel"
[ -e "$SICHERUNG" ] && SICHERUNG="$SICHERUNG-$$"
cp "$ENV_DATEI" "$SICHERUNG"
chmod 600 "$SICHERUNG"

NEU="$(mktemp "$PROJEKT/.env.neu.XXXXXX")"
trap 'rm -f "$NEU"' EXIT
grep -Ev "^($NAME_ADRESSE|$NAME_PASSWORT)=" "$ENV_DATEI" > "$NEU" || [ $? -eq 1 ]
if [ -s "$NEU" ] && [ -n "$(tail -c 1 "$NEU")" ]; then
  printf '\n' >> "$NEU"
fi
printf '%s=%s\n' "$NAME_ADRESSE" "$adresse" >> "$NEU"
printf "%s='%s'\n" "$NAME_PASSWORT" "$passwort" >> "$NEU"
unset passwort
chmod 600 "$NEU"
mv -f "$NEU" "$ENV_DATEI"
trap - EXIT

# 4) Nur die beiden Dienste neu erzeugen, die das Postfach brauchen.
if ! ( cd "$PROJEKT" && $DOCKER compose up -d --no-deps --force-recreate sales-mcp sales-mail ); then
  echo "Postfach $kennung eingetragen (Sicherung: $(basename "$SICHERUNG")), aber die Dienste ließen sich nicht neu erzeugen – siehe Meldung oben." >&2
  exit 1
fi
echo "Postfach $kennung ($adresse) eingetragen und geprüft, Sicherung: $(basename "$SICHERUNG"). sales-mcp und sales-mail neu erzeugt."
