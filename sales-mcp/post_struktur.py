"""Feste Faecherstruktur der Post-Sammelstelle (Spec §4, vom Betreiber bestaetigt).

Die Liste liegt hier als Daten, nicht verstreut im Prompt: der Agent darf nur
aus ihr waehlen, ein neues Fach legt ein Mensch bewusst an.
"""

BEREICHE = ("privat", "business")

# „Unklar“ ist das Fach fuer alles, was nicht sicher zuzuordnen ist; solche
# Mails bleiben im Posteingang, bis ein Mensch sie einordnet.
UNKLAR = "Unklar"

FAECHER: dict[str, tuple[str, ...]] = {
    "privat": (
        "Familie & Freunde", "Rechnungen", "Käufe & Bestellungen",
        "Abos & Newsletter", "Soziale Netzwerke", "Konten & Sicherheit",
        "Behörden & Versicherung", "Werbung", UNKLAR,
    ),
    "business": (
        "Kunden & Anfragen", "Partner & Netzwerk", "Rechnungen",
        "Tools & Dienste", "Bewerbungen & Jobs", "Newsletter & Branche",
        "Werbung", UNKLAR,
    ),
}


def fach_gueltig(bereich: str, fach: str) -> bool:
    """True, wenn `fach` in `bereich` existiert (Unklar gilt in beiden)."""
    return fach in FAECHER.get(bereich, ())
