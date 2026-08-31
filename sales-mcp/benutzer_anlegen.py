"""UI-Benutzer anlegen oder zuruecksetzen (E1) — der MENSCHEN-Schritt.

Aufruf im Container (deploy/benutzer-anlegen.sh macht genau das):

    printf '%s' "$PASSWORT" | docker exec -i sales-mcp \
        python benutzer_anlegen.py <name> <rolle>

Das Passwort kommt ueber STDIN — nie als Argument, Argumente stehen in
der Prozessliste. Ein bestehender Name wird AKTUALISIERT (neues Passwort,
neue Rolle, aktiv=true): so ist derselbe Weg auch der Passwort-Reset und
die Reaktivierung. Deaktivieren geht bewusst NICHT hierueber — das ist
`update benutzer set aktiv=false` von Hand, damit es niemand aus Versehen
tut. Vertragstests: tests/test_login.py.
"""
import sys

import server
import ui

ROLLEN = ("lesen", "freigeben")


def anlegen(name: str, rolle: str, passwort: str) -> str:
    name = (name or "").strip()
    if not name or "|" in name or ":" in name:
        return "FEHLER: Name fehlt oder enthaelt | oder :"
    if rolle not in ROLLEN:
        return f"FEHLER: Rolle muss eine sein von: {', '.join(ROLLEN)}"
    if len(passwort) < 10:
        return "FEHLER: Passwort braucht mindestens 10 Zeichen."
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv) "
        "values (%s, %s, %s, true) "
        "on conflict (name) do update set rolle = excluded.rolle, "
        "passwort_hash = excluded.passwort_hash, aktiv = true "
        "returning name",
        (name, rolle, ui._passwort_hashen(passwort)))
    return f"OK: Benutzer '{name}' mit Rolle '{rolle}' steht."


def main() -> int:
    if len(sys.argv) != 3:
        print("Aufruf: benutzer_anlegen.py <name> <lesen|freigeben> "
              "(Passwort ueber STDIN)")
        return 2
    passwort = sys.stdin.read().strip()
    meldung = anlegen(sys.argv[1], sys.argv[2], passwort)
    print(meldung)
    return 0 if meldung.startswith("OK") else 1


if __name__ == "__main__":
    sys.exit(main())
