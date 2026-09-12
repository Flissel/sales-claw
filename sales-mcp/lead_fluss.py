"""lead_fluss — F2/F3: Leads zwischen sales-claw und Marketing (Spec 03.09.2026).

BEIDE RICHTUNGEN LAUFEN UEBER DB-FUNKTIONEN in derselben Postgres (Marketing-
Migrationen 041/042). sales_app darf diese Funktionen rufen, sonst nichts in
marketing.* — die Funktionen pruefen Eingaben und Sperrliste selbst.

REINE LOGIK MIT INJIZIERTEM `q`: dieses Modul importiert server.py nicht,
damit es lokal ohne Datenbank und ohne das mcp-Paket testbar bleibt. Die
Verdrahtung (Werkzeuge, _gesichert, _q) liegt in server.py.
"""
import json

import sperrliste          # Kennungs-Normalisierung, geteilt mit der Verbotsliste
import telegram_chat       # chat_id-Pruefung, geteilt mit Anzeige und Versand

VORSCHLAG_SCHLUESSEL = "an_marketing"      # enrichment-Schluessel: {proposal_id, am}
MAX_KANDIDATEN = 500                        # Kappung der DB-Funktion


# --- F2: Recherche-Leads -> Marketing-Staging ------------------------------

def recherche_kandidaten(q, *, archiviert: str, privat: str,
                         lead_ids=None, erneut: bool = False) -> list:
    """Leads, die Marketing angeboten werden duerfen: Quelle recherche, ohne
    Einwilligung, mit E-Mail, nicht archiviert, nicht privat, noch nicht
    vorgeschlagen (ausser `erneut`). `archiviert`/`privat` sind die
    SQL-Fragmente aus server._archiv_sql / _privat_sql — dieselbe Regel wie
    ueberall, nie eine eigene."""
    sql = ("select id, name, email, phone, notes, enrichment from leads "
           "where source = 'recherche' and consent_status = 'unknown' "
           "and coalesce(email, '') <> '' "
           f"and not {archiviert} and not {privat}")
    params = []
    if not erneut:
        sql += f" and (enrichment -> '{VORSCHLAG_SCHLUESSEL}') is null"
    if lead_ids:
        sql += " and id::text = any(%s)"
        params.append([str(i) for i in lead_ids])
    sql += f" order by created_at desc limit {MAX_KANDIDATEN}"
    return q(sql, tuple(params)) or []


def kandidaten_form(zeilen: list) -> list:
    """Kandidaten so, wie die DB-Funktion sie erwartet — E-Mail klein, ohne
    kaputte Adressen (die Funktion zaehlt sie sonst als ungueltig)."""
    out = []
    for z in zeilen:
        email = (z.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        anreicherung = z.get("enrichment") if isinstance(z.get("enrichment"), dict) else {}
        firma = anreicherung.get("firma") if isinstance(anreicherung.get("firma"), dict) else {}
        out.append({"email": email,
                    "display_name": (z.get("name") or "").strip(),
                    "company": (firma.get("name") or "").strip(),
                    "notiz": (z.get("notes") or "").strip()[:200]})
    return out


def vorschlagen(q, name: str, begruendung: str, kandidaten: list) -> dict:
    """Ein Aufruf der DB-Funktion fuer alle Kandidaten. Rueckgabe wie die
    Funktion: {proposal_id, angenommen, uebersprungen_gesperrt, uebersprungen_ungueltig}."""
    zeilen = q("select marketing.vorschlag_aus_sales(%s, %s, %s::jsonb) as ergebnis",
               (name, begruendung, json.dumps(kandidaten, ensure_ascii=False)))
    ergebnis = (zeilen or [{}])[0].get("ergebnis") or {}
    if isinstance(ergebnis, str):
        ergebnis = json.loads(ergebnis)
    return ergebnis


def vermerken(q, lead_ids: list, proposal_id: str, jetzt: str) -> int:
    """Je Lead: enrichment.an_marketing = {proposal_id, am} + Aktivitaet —
    damit derselbe Lead nicht beim naechsten Aufruf wieder vorgeschlagen wird."""
    for lid in lead_ids:
        q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
          "%s, %s::jsonb, true), updated_at = now() where id = %s returning id",
          ([VORSCHLAG_SCHLUESSEL], json.dumps({"proposal_id": proposal_id, "am": jetzt}), lid))
        q("insert into activities (lead_id, type, payload) values (%s, %s, %s) returning id",
          (lid, "an_marketing", json.dumps({"proposal_id": proposal_id})))
    return len(lead_ids)


# --- F3: Antworten auf Marketing-Nachrichten -> sales-claw-Kontakt ---------

def uebergaben_offen(q, limit: int = 20) -> list:
    """Offene Uebergaben ueber die SECURITY-DEFINER-Funktion — sales_app liest
    die Tabelle nie direkt."""
    return q("select id::text as id, from_email, from_name, subject, auszug, kampagne, "
             "klassifikation, seit from marketing.uebergaben_offen(%s)", (int(limit),)) or []


def uebergabe_erledigen(q, uebergabe_id: str, status: str, lead_id, grund: str) -> bool:
    zeilen = q("select marketing.uebergabe_erledigen(%s::uuid, %s, %s, %s) as ok",
               (uebergabe_id, status, lead_id, grund or ""))
    return bool((zeilen or [{}])[0].get("ok"))


def kontaktname(from_name: str, from_email: str) -> str:
    name = (from_name or "").strip()
    return name or (from_email or "").split("@")[0].strip()


def uebergabe_notiz(u: dict) -> str:
    return (f"Marketing-Uebergabe ({u.get('klassifikation', '?')}): {u.get('subject', '')}\n"
            f"Kampagne: {u.get('kampagne') or '(keine)'}\n{u.get('auszug', '')}")


# --- Versandauftraege: Marketing bittet, sales-claw entscheidet -------------
#
# Betreiber-Entscheid 12.09.2026 — sales-claw wird der EINZIGE Versandweg
# (Spec vibemind-os/docs/superpowers/specs/2026-09-12-sales-claw-einziger-
# versandweg.md). Marketing schreibt Text und Unterlage, kennt aber keine
# lead_id und keine unserer Tore. Es legt deshalb einen AUFTRAG in
# marketing.versandauftraege; wir holen ihn hier ab und machen daraus
# hoechstens einen Entwurf — durch dieselben Tore wie jeder andere.
#
# Warum das Aufloesen hier und nicht drueben: die Adresse ist alles, was
# Marketing hat. Welcher Kontakt dazu gehoert, ob er archiviert, privat oder
# gesperrt ist, steht bei uns. Ein Auftrag ist eine Bitte, kein Befehl.

POST_KANAL = "linkedin_post"          # Beitrag aufs eigene Profil, ohne Empfaenger


def versandauftraege_offen(q, limit: int = 20) -> list:
    """Offene Auftraege ueber die SECURITY-DEFINER-Funktion — sales_app liest
    marketing.versandauftraege nie direkt."""
    return q("select id::text as id, kanal, empfaenger, betreff, nachricht, "
             "medien_datei, kampagne, quelle, seit "
             "from marketing.versandauftraege_offen(%s)", (int(limit),)) or []


def versandauftrag_erledigen(q, auftrag_id: str, status: str,
                             draft_id: str = "", grund: str = "") -> bool:
    zeilen = q("select marketing.versandauftrag_erledigen(%s::uuid, %s, %s, %s) as ok",
               (auftrag_id, status, draft_id or "", grund or ""))
    return bool((zeilen or [{}])[0].get("ok"))


def empfaenger_leads(q, empfaenger: str, *, archiviert: str, privat: str,
                     kanal: str = "") -> list:
    """Kontakte zu dieser Adresse — E-Mail exakt, Telefon normalisiert, bei
    Telegram ueber die hinterlegte chat_id.

    DER KANAL MUSS MIT (seit 12.09.2026, gefunden im eigenen Durchstich).
    Ohne ihn landete eine chat_id im Telefon-Zweig: `1092040975` wird von
    `sperrliste.kennung_tel` zu `tel:+1092040975`, und die Vorauswahl sucht
    dann Leads, deren Nummer auf dieselben acht Ziffern endet. Im Glücksfall
    findet sie niemanden (so geschehen) — im Unglücksfall einen FREMDEN
    Kontakt, und die Nachricht ginge an den Falschen. Ein Kanal, der die
    Auswahl bestimmt, ist hier keine Bequemlichkeit, sondern die
    Schutzkante.

    NORMALISIERT WIRD MIT `sperrliste` bzw. `telegram_chat`, nicht mit einer
    eigenen Regel: dieselben Funktionen, die auch Verbotsliste, Anzeige und
    Versand benutzen. Eine zweite Normalisierung waere genau der Fehler, den
    der Entscheid vom 12.09. abschafft — zwei Orte, die auseinanderlaufen
    koennen.

    Beim Telefon kann SQL nicht normalisiert vergleichen, ohne jede Zeile
    anzufassen. Darum zwei Stufen: die Datenbank grenzt ueber die letzten
    acht Ziffern grob ein (Index-freundlich genug bei dieser Groesse), und
    die genaue Entscheidung faellt hier mit derselben Funktion wie ueberall.
    `archiviert`/`privat` sind die SQL-Fragmente aus server._archiv_sql /
    _privat_sql — dieselbe Regel wie ueberall, nie eine eigene.
    """
    adresse = (empfaenger or "").strip()

    if kanal == "telegram":
        # AUSSCHLIESSLICH ueber die chat_id — nie ueber die Telefonnummer,
        # auch wenn die Zahl wie eine aussieht. `erreichbar` muss true sein:
        # ein Kontakt, dem der Betreiber die Erreichbarkeit entzogen hat,
        # ist kein Empfaenger (fail-closed, wie server._telegram_chat_id).
        ziel = telegram_chat.pruefe(adresse)[0]
        if not ziel:
            return []
        return q("select id, name, email, phone from leads "
                 "where enrichment -> 'telegram' ->> 'chat_id' = %s "
                 "and (enrichment -> 'telegram' ->> 'erreichbar') = 'true' "
                 f"and not {archiviert} and not {privat} order by created_at asc",
                 (ziel,)) or []

    ziel_email = sperrliste.kennung_email(adresse)
    if ziel_email:
        return q("select id, name, email, phone from leads "
                 f"where lower(btrim(coalesce(email, ''))) = %s "
                 f"and not {archiviert} and not {privat} order by created_at asc",
                 (ziel_email.split(":", 1)[1],)) or []

    ziel_tel = sperrliste.kennung_tel(adresse)
    if ziel_tel:
        ziffern = ziel_tel.split("+", 1)[1]
        roh = q("select id, name, email, phone from leads "
                r"where regexp_replace(coalesce(phone, ''), '\D', '', 'g') like %s "
                f"and not {archiviert} and not {privat} order by created_at asc",
                ("%" + ziffern[-8:],)) or []
        return [z for z in roh
                if sperrliste.kennung_tel(z.get("phone") or "") == ziel_tel]

    return []


def empfaenger_versteckt(q, empfaenger: str, kanal: str = "") -> str:
    """Gibt es den Kontakt DOCH, nur archiviert oder privat? Sonst ''.

    GEMESSEN AM 12.09.2026: ein Versandauftrag an die Firmenadresse des
    Betreibers wurde mit „Kein Kontakt in sales-claw" abgewiesen - dabei gab
    es ihn, er war nur archiviert. Wer das liest, legt einen Doppelkontakt
    an, und dann existiert dieselbe Person zweimal mit verschiedenen
    Einwilligungen. Eine Absage muss den Unterschied nennen koennen.
    """
    treffer = empfaenger_leads(q, empfaenger, kanal=kanal,
                               archiviert="false", privat="false")
    if not treffer:
        return ""
    namen = ", ".join(str(z.get("name") or z["id"]) for z in treffer[:3])
    return namen


def auftrag_notiz(auftrag: dict) -> str:
    """Was am Kontakt stehen soll, damit spaeter jemand nachvollziehen kann,
    woher diese Nachricht kam."""
    teile = [f"Marketing-Versandauftrag ({auftrag.get('kanal', '?')})"]
    if auftrag.get("kampagne"):
        teile.append(f"Kampagne: {auftrag['kampagne']}")
    if auftrag.get("quelle"):
        teile.append(f"Quelle: {auftrag['quelle']}")
    return "\n".join(teile)
