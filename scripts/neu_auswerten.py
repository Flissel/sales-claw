"""Mitschrift eines Termins bereinigen und neu auswerten lassen (Abnahme-Befunde 14.11.2026).

Aufruf (im Container des Taktgebers, dort liegen Code und Datenbankzugang):
  ssh offload-vm 'docker exec -i sales-termine timeout 120 python - <uid>' < scripts/neu_auswerten.py

<uid> ist die volle Akten-uid (z. B. 3c9afada-...@sales-claw) oder ein eindeutiger
Praefix ab 8 Zeichen; bei 0 oder mehr als einem Treffer Abbruch.
Wirkung: Segmente durch mitschrift_bereinigen.bereinigen, auswertung_status
'offen' (bzw. 'leer', wenn nichts bleibt), auswertung_versuche 0, alte
Auswertung geleert, offene Vorschlaege der alten Auswertung geloescht; der
Taktgeber wertet danach neu aus. Abbruch, wenn die Auswertung noch aussteht
(Status nicht fertig/fehler/leer) oder der verknuepfte Entwurf schon verschickt,
freigegeben oder fehlgeschlagen ist. Ein offener Entwurf bleibt (Warnzeile).
Ausgabe: nur Zaehler (Segmente, Anteil '?'-Sprecher, Anteil Segmente mit
hoechstens 2 Woertern, je vorher/nachher; geloeschte Vorschlaege) - nie Text
oder Namen.
"""
import sys

import neu_auswertung


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Aufruf: python - <uid>", file=sys.stderr)
        return 2
    try:
        st = neu_auswertung.neu_auswerten(argv[1])
    except neu_auswertung.NeuAuswertenFehler as e:
        print(f"ABBRUCH: {e}", file=sys.stderr)
        return 1
    print(f"Segmente: {st['segmente_vorher']} -> {st['segmente_nachher']}")
    print(f"Sprecher '?': {st['fragezeichen_vorher']:.1%} -> {st['fragezeichen_nachher']:.1%}")
    print(f"Segmente mit hoechstens 2 Woertern: {st['kurz_vorher']:.1%} -> {st['kurz_nachher']:.1%}")
    print(f"Offene Vorschlaege geloescht: {st['vorschlaege_geloescht']}")
    if st["entwurf_offen"]:
        print(f"WARNUNG: {neu_auswertung.ENTWURF_WARNUNG}")
    if st["segmente_nachher"]:
        print("Status offen; der Taktgeber wertet beim naechsten Durchlauf aus.")
    else:
        print("Status leer: nach der Bereinigung bleibt kein Segment.")
    return 0


sys.exit(main(sys.argv))
