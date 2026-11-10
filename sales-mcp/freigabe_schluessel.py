"""CLI: Dienst-Schluessel des Freigabe-Eingangs anlegen.

    python -m freigabe_schluessel anlegen <herkunft> | <ziel>

Der Schluessel geht NUR in eine Pipe (stdout, ohne Zeilenumbruch); stderr nennt nur
die Herkunft. Ein Terminal wird abgelehnt (Exit 2), bevor etwas angelegt wird.
Ein vorhandener Schluessel der Herkunft wird ersetzt.
"""
import sys

import freigabe_eingang as fe


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "anlegen":
        sys.stderr.write("Aufruf: python -m freigabe_schluessel anlegen <herkunft>\n")
        return 2
    herkunft = argv[1]
    if sys.stdout.isatty():
        sys.stderr.write("Abbruch: stdout ist ein Terminal. Den Schluessel in eine "
                         "Pipe leiten, nichts wurde angelegt.\n")
        return 2
    try:
        schluessel = fe.schluessel_anlegen(herkunft)
    except fe.EingabeFehler:
        sys.stderr.write(f"Abbruch: fuer '{herkunft}' gibt es keinen Schluessel.\n")
        return 2
    sys.stdout.write(schluessel)
    sys.stdout.flush()
    sys.stderr.write(f"angelegt: {herkunft}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
