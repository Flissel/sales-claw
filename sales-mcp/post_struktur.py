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


# ---------------------------------------------------------------------------
# Sichtbarkeit (Spec §6, §7, §14.3): EINE Stelle entscheidet, welche Mails
# eine Person oder der Bot sehen darf. Jede Seite, Suche und jedes Bot-
# Werkzeug geht hierdurch; ein Fehler waere ein Datenleck privater Post.
# ---------------------------------------------------------------------------
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Betrachter:
    name: str
    leitung: bool
    abteilungen: tuple[str, ...]
    ist_agent: bool = False


# Bot und spaetere Agenten handeln fuer den Betreiber: nur Business, nie
# sensibel, alle Konten (Spec §14.3). Leitung=True heisst „alle Abteilungen“.
BETREIBER_AGENT = Betrachter(name="agent", leitung=True, abteilungen=(),
                             ist_agent=True)


def betrachter_laden(name: str) -> "Betrachter | None":
    """Betrachter aus `benutzer` + `benutzer_abteilungen`; None, wenn
    unbekannt oder deaktiviert (ein gesperrter Zugang sieht nichts)."""
    import server
    zeilen = server._q(
        "select name, leitung from benutzer where name = %s and aktiv",
        (name,))
    if not zeilen:
        return None
    abt = server._q(
        "select abteilung from benutzer_abteilungen where benutzer = %s "
        "order by abteilung", (name,))
    return Betrachter(name=zeilen[0]["name"],
                      leitung=bool(zeilen[0]["leitung"]),
                      abteilungen=tuple(a["abteilung"] for a in abt))


def sichtbar_sql(b: Betrachter) -> tuple[str, list]:
    """(WHERE-Fragment mit %s-Platzhaltern, Parameter) fuer `from post_mails m`.

    Nicht eingeordnete Mails (bereich null) sieht nur der Besitzer; „Unklar“
    gehoert keiner Abteilung und bleibt damit bei Leitung + Besitzer.
    """
    if b.ist_agent:
        # Nie privat, nie sensibel, nie unklassifiziert (bereich null faellt
        # durch den Gleichheitsvergleich heraus).
        return ("(m.bereich = 'business' and m.sensibel is false)",
                [])
    teile = ["(m.bereich is null and m.besitzer = %s)",
             "(m.bereich = 'privat' and m.besitzer = %s)"]
    params = [b.name, b.name]
    if b.leitung:
        teile.append("(m.bereich = 'business')")
    else:
        teile.append("(m.bereich = 'business' and (m.besitzer = %s or "
                     "m.fach in (select f.fach from post_abteilung_faecher f "
                     "where f.abteilung = any(%s))))")
        params += [b.name, list(b.abteilungen)]
    return "(" + " or ".join(teile) + ")", params


def _spalten() -> str:
    # Text, Auszug, Anhaenge und Empfaenger sensibler Mails werden schon in
    # SQL geleert: sie verlassen die Datenbank gar nicht erst (Spec §5: nur
    # Konto, Absender, Datum, Betreff, Fach, Markierung), auch nicht fuer den
    # Besitzer. `is not false` behandelt NULL wie sensibel (fail closed).
    s = "m.sensibel is not false"
    return ("m.id, m.konto_id, m.besitzer, m.von, m.betreff, m.datum, "
            "m.bereich, m.fach, m.sensibel, m.status, m.gesehen_am, "
            f"case when {s} then false else m.kalenderteil end as kalenderteil, "
            f"case when {s} then null else m.an end as an, "
            f"case when {s} then '{{}}'::text[] else m.anhaenge end as anhaenge, "
            f"case when {s} then null else m.auszug end as auszug, "
            f"case when {s} then null else m.text end as text")


def mails_suchen(b: Betrachter, suche: str = "", bereich: str = "",
                 fach: str = "", konto_id: str = "", grenze: int = 50,
                 versatz: int = 0) -> list[dict]:
    import server
    if bereich and bereich not in BEREICHE:
        return []
    if fach:
        gueltig = (fach_gueltig(bereich, fach) if bereich
                   else any(fach_gueltig(x, fach) for x in BEREICHE))
        if not gueltig:
            return []
    if konto_id:
        try:
            konto_id = str(uuid.UUID(str(konto_id)))
        except ValueError:
            return []
    where, params = sichtbar_sql(b)
    teile = [where]
    if bereich:
        teile.append("m.bereich = %s")
        params.append(bereich)
    if fach:
        teile.append("m.fach = %s")
        params.append(fach)
    if konto_id:
        teile.append("m.konto_id = %s")
        params.append(konto_id)
    if suche and suche.strip():
        teile.append("m.suchtext @@ websearch_to_tsquery('german', %s)")
        params.append(suche)
    params += [max(1, min(int(grenze), 200)), max(0, int(versatz))]
    return server._q(
        f"select {_spalten()} from post_mails m where "
        + " and ".join(teile)
        + " order by m.datum desc nulls last, m.gesehen_am desc "
          "limit %s offset %s", params)


def mail_lesen(b: Betrachter, mail_id: str) -> "dict | None":
    """Eine Mail, wenn `b` sie sehen darf; sonst None (auch bei unbekannter
    oder kaputter id - kein Unterschied, damit nichts durchsickert)."""
    import server
    try:
        mid = str(uuid.UUID(str(mail_id)))
    except ValueError:
        return None
    where, params = sichtbar_sql(b)
    zeilen = server._q(
        f"select {_spalten()} from post_mails m where m.id = %s and {where}",
        [mid] + params)
    return zeilen[0] if zeilen else None
