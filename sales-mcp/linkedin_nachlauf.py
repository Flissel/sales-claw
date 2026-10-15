"""Meldung nach dem Posten (Spec 2026-10-15 §4.4).

Findet LinkedIn-Veroeffentlichungen der letzten 24 h, zu denen der
Betreiber noch keine Meldung bekommen hat, und baut den Meldetext (Post-
Link + Markier-Liste). GESENDET wird hier nichts: das macht
deploy/linkedin-nachlauf.sh auf dem Wirt ueber den Gateway-Kanal und ruft
erst nach Erfolg `gemeldet` — so bleibt sales-linkedin ohne WhatsApp-Zugang.

CLI (Arbeitsverzeichnis /app im Container sales-mcp):
  python linkedin_nachlauf.py liste               -> je Zeile eine draft_id
  python linkedin_nachlauf.py text <draft_id>     -> Meldetext (Exit 3: nicht offen)
  python linkedin_nachlauf.py gemeldet <draft_id> -> bucht die Meldung
"""
import json
import sys

import server

FENSTER_STUNDEN = 24
POST_URL = "https://www.linkedin.com/feed/update/{urn}/"
_ART = {"person": "Person", "firma": "Firma"}


def offene_meldungen() -> list:
    """[{draft_id, beitrag}] — veroeffentlicht (Beitrags-URN vorhanden),
    juenger als 24 h, noch nicht gemeldet. Unsichere und manuelle Versand-
    zeilen tragen keine URN und fallen damit heraus."""
    zeilen = server._q(
        "select v.payload->>'draft_id' as draft_id, v.payload->>'beitrag' as beitrag "
        "from activities v where v.type = 'versand' "
        "and v.payload->>'kanal' = 'linkedin' "
        "and coalesce(v.payload->>'beitrag', '') <> '' "
        "and v.created_at > now() - make_interval(hours => %s) "
        "and not exists (select 1 from activities g "
        "  where g.type = 'linkedin_nachlauf_gemeldet' "
        "  and g.payload->>'draft_id' = v.payload->>'draft_id') "
        "order by v.created_at", (FENSTER_STUNDEN,))
    return [{"draft_id": z["draft_id"], "beitrag": z["beitrag"]} for z in zeilen]


def meldetext(draft_id: str, beitrag: str) -> str:
    zeilen = [f"LinkedIn-Post ist online: {POST_URL.format(urn=beitrag)}"]
    liste = server.post_markierungen(draft_id)
    if liste:
        zeilen += ["", "Jetzt in der App markieren (Bearbeiten → @Name):"]
        for e in liste:
            teile = [f"- @{e['name']}", _ART.get(e.get("art"), "Person")]
            if e.get("profil"):
                teile.append(e["profil"])
            zeilen.append(" · ".join(teile))
    return "\n".join(zeilen)


def als_gemeldet_buchen(draft_id: str) -> None:
    lead = server._q("select lead_id from drafts where id = %s", (draft_id,))
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'linkedin_nachlauf_gemeldet', %s, 'cron') returning id",
              (lead[0]["lead_id"] if lead else None,
               json.dumps({"draft_id": str(draft_id)})))


def main(argv) -> int:
    if len(argv) >= 1 and argv[0] == "liste":
        for m in offene_meldungen():
            print(m["draft_id"])
        return 0
    if len(argv) == 2 and argv[0] == "text":
        treffer = [m for m in offene_meldungen() if m["draft_id"] == argv[1]]
        if not treffer:
            return 3
        sys.stdout.write(meldetext(argv[1], treffer[0]["beitrag"]) + "\n")
        return 0
    if len(argv) == 2 and argv[0] == "gemeldet":
        als_gemeldet_buchen(argv[1])
        return 0
    print("Aufruf: liste | text <draft_id> | gemeldet <draft_id>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
