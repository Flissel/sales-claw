"""Absender-Katalog: feste Zuordnung bekannter Absender-Domains zu Fach und Unterfach.

Bekannte Absender landen immer am selben Ort, egal was das Modell meint. Das
Modell entscheidet nur bei Unbekannten (Spec v2). Die Liste ist ein Entwurf,
den der Betreiber in Task 7 bestaetigt; ein neues Fach legt ein Mensch an.

Gilt fuer die Endung einer Domain (Subdomains eingeschlossen), nicht fuer
Teilstrings: `box.com` darf nicht auf `x.com` fallen, `instagram.com.evil.io`
nicht auf `instagram.com`.
"""

from email.utils import parseaddr

# Eine Zeile pro Endung (die Tabelle im Plan hat mehrere Endungen je Zeile).
# Unterfach None heisst: das Fach kennt keine Unterfaecher (Spec §4).
KATALOG: tuple[tuple[str, str, str | None], ...] = (
    ("instagram.com", "Soziale Netzwerke", "Instagram"),
    ("linkedin.com", "Soziale Netzwerke", "LinkedIn"),
    ("tiktok.com", "Soziale Netzwerke", "TikTok"),
    ("youtube.com", "Soziale Netzwerke", "YouTube"),
    ("facebookmail.com", "Soziale Netzwerke", "Facebook & Meta"),
    ("facebook.com", "Soziale Netzwerke", "Facebook & Meta"),
    ("meta.com", "Soziale Netzwerke", "Facebook & Meta"),
    ("x.com", "Soziale Netzwerke", "X"),
    ("twitter.com", "Soziale Netzwerke", "X"),
    ("bsky.social", "Soziale Netzwerke", "Bluesky"),
    ("bsky.app", "Soziale Netzwerke", "Bluesky"),
    ("mastodon.social", "Soziale Netzwerke", "Mastodon"),
    ("threads.net", "Soziale Netzwerke", "Threads"),
    ("threads.com", "Soziale Netzwerke", "Threads"),
    ("github.com", "Tools & Dienste", "GitHub"),
    ("notion.so", "Tools & Dienste", "Notion"),
    ("notion.com", "Tools & Dienste", "Notion"),
    ("makenotion.com", "Tools & Dienste", "Notion"),
    ("vercel.com", "Tools & Dienste", "Vercel"),
    ("openrouter.ai", "Tools & Dienste", "OpenRouter"),
    ("tailscale.com", "Tools & Dienste", "Tailscale"),
    ("anthropic.com", "Tools & Dienste", "Anthropic"),
    ("openai.com", "Tools & Dienste", "OpenAI"),
    ("namecheap.com", "Tools & Dienste", "Namecheap"),
    ("privateemail.com", "Tools & Dienste", "Namecheap"),
    ("hashnode.com", "Tools & Dienste", "Hashnode"),
    ("dev.to", "Tools & Dienste", "dev.to"),
    ("spotify.com", "Tools & Dienste", "Spotify"),
    ("cal.com", "Tools & Dienste", "Cal.com"),
    ("calendly.com", "Tools & Dienste", "Calendly"),
    ("adobe.com", "Tools & Dienste", "Adobe"),
    ("nebius.com", "Tools & Dienste", "Nebius"),
    ("tavily.com", "Tools & Dienste", "Tavily"),
    ("hs-send.com", "Tools & Dienste", "HubSpot"),
    ("luma-mail.com", "Veranstaltungen", None),
    ("luma.com", "Veranstaltungen", None),
    ("lu.ma", "Veranstaltungen", None),
    ("easyfairs.com", "Veranstaltungen", None),
    ("easyfairs.de", "Veranstaltungen", None),
    ("devlunchclub.com", "Veranstaltungen", None),
    ("substack.com", "Newsletter & Branche", None),
    ("teamtailor-mail.com", "Bewerbungen & Jobs", None),
)

# Schneller Zugriff nach Endung. Die Endungen sind eindeutig (Test), damit
# geht beim Anlegen nichts still verloren.
_NACH_ENDUNG: dict[str, tuple[str, str | None]] = {
    endung: (fach, unterfach) for endung, fach, unterfach in KATALOG
}


def domain(von: str) -> str:
    """Domain der Absenderadresse, klein und ohne Punkt am Ende.

    `parseaddr` trennt Anzeigename und Adresse (`Name <a@b.de>`). Ohne `@`
    gibt es keine Domain; leer heisst dann „nicht zuordenbar“.
    """
    adresse = parseaddr(von)[1]
    if "@" not in adresse:
        return ""
    # Punkt am Ende ist in Mailheadern erlaubt, gehoert aber nicht zum Namen.
    return adresse.rsplit("@", 1)[1].lower().rstrip(".")


def treffer(von: str) -> tuple[str, str | None] | None:
    """(Fach, Unterfach) fuer einen bekannten Absender, sonst None.

    Geprueft wird vom vollen Domainnamen zur kuerzesten Endung. Die erste
    Treffer-Endung ist damit die laengste, und die laengste gewinnt (z. B.
    `calendar.luma-mail.com` als `luma-mail.com`, nicht als `com`).
    """
    d = domain(von)
    if not d:
        return None
    teile = d.split(".")
    for i in range(len(teile)):
        kandidat = ".".join(teile[i:])
        if kandidat in _NACH_ENDUNG:
            return _NACH_ENDUNG[kandidat]
    return None
