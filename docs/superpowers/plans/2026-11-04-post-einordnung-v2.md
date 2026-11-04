# Post-Einordnung v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mails werden feiner (Unterfächer), stabil (Absender-Katalog) und geprüft (zweiter Agent) einsortiert; Privat nur noch für wirklich Persönliches; der Altbestand wird neu einsortiert.

**Architecture:** `post_struktur` bekommt Unterfächer, Beschreibungen und die neue Sensibel-Sichtbarkeit; neues Modul `post_katalog` (Domain → Fach/Unterfach); `post_einordnung` läuft Muster → Nutzerregel → Katalog → Sortierer → Prüfer; `post_abholen` speichert Unterfach, Vorschläge, Modellaufrufe; neues Modul `post_neu_einordnen` für Vorschau und Anwenden auf den Altbestand.

**Tech Stack:** Python 3 (sales-mcp), Starlette-UI (`ui_post.py`), PostgreSQL (Supabase, Schema per `-v schema=`), OpenClaw-Gateway 2026.7.1 (`gateway.funktion_aufrufen`), Bash-Deploy-Skripte.

**Spec:** `docs/superpowers/specs/2026-11-04-post-einordnung-v2-design.md` (baut auf `docs/superpowers/specs/2026-10-30-post-sammelstelle-design.md`).

## Global Constraints

- Arbeitsumgebung, Testablauf und Verbote wie `.superpowers/sdd/2026-11-03-post-sammelstelle-stufe1/umgebung.md`, aber Branch **`feat/post-einordnung-v2`** (Worktree `C:/Users/User/ClaudeWork/wt-sales-post`). DB-Tests nur gegen `sales_test`; nie `-v schema=sales`.
- Kein Deploy, kein `update.sh`, keine Änderung an laufenden Containern oder der VM-`.env` während der Tasks (Rollout am Ende, mit Felix' OK).
- Keine Mailinhalte, Betreffs, Passwörter in Logs, Ausgaben, Commits. Fehler nur als Typ loggen.
- Deutsche Bezeichner und Kommentare wie im Bestand; Kommentare erklären das Warum.
- Feste Liste: kein Modell erfindet Fach oder Unterfach; ungültig → `Zum Nachsehen` bzw. Unterfach `Sonstige`.
- Fach „Unklar“ heißt jetzt **„Zum Nachsehen“**. Die Konstante bleibt `post_struktur.UNKLAR` (Wert ändert sich), damit die Aufrufer gleich bleiben.
- Prüfer-Agent-ID ist die Konstante `"post-pruefer"`; ein im Gateway unbekannter Agent bekommt ALLE Werkzeuge – nie dynamisch zusammensetzen.
- Ladenfest: Firmenkontext kommt aus der Env `POST_KONTEXT` des Ladens, nie fest „VibeMind“ im Code.
- Ein Mensch-Entscheid (`einordnung_quelle = 'mensch'`) wird nie automatisch überschrieben.
- Eine einmal sensible Mail wird nie wieder nicht-sensibel durch eine Automatik (Text ist ohnehin gelöscht; die Markierung schützt die Sichtbarkeit).

## Review Focus

1. Neu-Sortierung einer Mail, die heute `sensibel = true` ist, und das Modell sagt jetzt `false` → bleibt sensibel (Test in Task 7).
2. Gefälschter Anzeigename „Instagram <x@evil.io>“ oder Domain `instagram.com.evil.io` → kein Katalog-Treffer (Test in Task 3).
3. Felix korrigiert eine Mail zwischen Vorschau und Anwenden → Anwenden lässt sie unberührt (Test in Task 7).
4. Prüfer liefert ein Fach eines anderen Bereichs oder ein unbekanntes Unterfach → wird wie beim Sortierer auf die feste Liste gezwungen, ohne Absturz (Test in Task 4).
5. Abteilungsmitglied (Marketing) sieht eine sensible Mail unter `business / Soziale Netzwerke` **nicht**, obwohl das Fach Marketing gehört (Test in Task 1).

---

### Task 1: Fachstruktur, Unterfächer, Sichtbarkeit

**Files:**
- Modify: `sales-mcp/post_struktur.py` (FAECHER, neue Konstanten, `sichtbar_sql`)
- Modify: alle Tests/Code, die den Text `"Unklar"` fest erwarten (`grep -rn "Unklar" sales-mcp`) – auf `post_struktur.UNKLAR` umstellen
- Test: `sales-mcp/tests/test_post_struktur.py`, `sales-mcp/tests/test_post_sichtbarkeit.py`

**Interfaces:**
- Produces:
  - `UNKLAR = "Zum Nachsehen"`
  - `FAECHER: dict[str, tuple[str, ...]]` – exakt die Tabellen aus Spec §4 (Reihenfolge wie dort, `UNKLAR` jeweils zuletzt)
  - `SOZIAL = ("Instagram", "LinkedIn", "TikTok", "YouTube", "Facebook & Meta", "X", "Bluesky", "Mastodon", "Threads", "Sonstige")`
  - `ANBIETER = ("GitHub", "Notion", "Vercel", "OpenRouter", "Tailscale", "Anthropic", "OpenAI", "Google", "Namecheap", "Hashnode", "dev.to", "Spotify", "Cal.com", "Calendly", "Adobe", "Nebius", "Tavily", "HubSpot", "Sonstige")`
  - `UNTERFAECHER: dict[str, tuple[str, ...]]` – `{"Soziale Netzwerke": SOZIAL, "Tools & Dienste": ANBIETER, "Konten & Sicherheit": SOZIAL[:-1] + ANBIETER}` (gilt in beiden Bereichen)
  - `BESCHREIBUNG: dict[tuple[str, str], str]` – je (bereich, fach) ein Satz (business aus Spec §4 Spalte „Was hinein gehört“; privat sinngemäß, Privat-Fächer betonen „betrifft den Inhaber persönlich“)
  - `NUR_BUSINESS = frozenset({"Kunden & Anfragen", "Partner & Netzwerk", "Veranstaltungen", "Tools & Dienste", "Bewerbungen & Jobs", "Newsletter & Branche"})`
  - `unterfach_gueltig(fach: str, unterfach: str | None) -> bool` – Fach ohne Unterfächer: nur `None`/`""` gültig; sonst nur Werte aus `UNTERFAECHER[fach]`
  - `unterfach_zwingen(fach: str, unterfach: str | None) -> str | None` – gültig → unverändert (leer → `None`); Fach mit Unterfächern + ungültig/leer → `"Sonstige"`; Fach ohne → `None`
  - `bereich_fuer(fach: str, standard: str) -> str` – `fach in NUR_BUSINESS` → `"business"`; sonst `standard`, falls das Fach dort existiert, sonst `"business"` falls dort, sonst `standard`
  - `sichtbar_sql(b)` – neue Regel: sensible Mails (`m.sensibel is not false`) sieht der Besitzer; die Leitung nur bei `bereich = 'business'`; Abteilungen nie. Agent unverändert.

- [ ] **Step 1: Failing tests (rein, `test_post_struktur.py`)**

```python
def test_soziale_netzwerke_in_beiden_bereichen_mit_unterfaechern():
    for br in ("privat", "business"):
        assert "Soziale Netzwerke" in ps.FAECHER[br]
        assert "Konten & Sicherheit" in ps.FAECHER[br]
        assert ps.FAECHER[br][-1] == "Zum Nachsehen"
    assert ps.UNKLAR == "Zum Nachsehen"
    assert "Veranstaltungen" in ps.FAECHER["business"] and "Gesundheit" in ps.FAECHER["privat"]
    assert "Unklar" not in ps.FAECHER["privat"] + ps.FAECHER["business"]

def test_unterfach_zwingen():
    assert ps.unterfach_zwingen("Soziale Netzwerke", "Instagram") == "Instagram"
    assert ps.unterfach_zwingen("Soziale Netzwerke", "Myspace") == "Sonstige"
    assert ps.unterfach_zwingen("Soziale Netzwerke", None) == "Sonstige"
    assert ps.unterfach_zwingen("Werbung", "Instagram") is None
    assert ps.unterfach_gueltig("Werbung", None) and not ps.unterfach_gueltig("Werbung", "X")

def test_bereich_fuer():
    assert ps.bereich_fuer("Tools & Dienste", "privat") == "business"
    assert ps.bereich_fuer("Soziale Netzwerke", "privat") == "privat"
    assert ps.bereich_fuer("Gesundheit", "business") == "privat"
    assert ps.bereich_fuer("Rechnungen", "business") == "business"

def test_jedes_fach_hat_eine_beschreibung():
    for br, faecher in ps.FAECHER.items():
        for f in faecher:
            assert ps.BESCHREIBUNG[(br, f)].strip()
```

- [ ] **Step 2: Failing DB-Test (`test_post_sichtbarkeit.py`, Muster der vorhandenen Fixtures)**

`test_sensible_business_mail_nur_besitzer_und_leitung`: Mail `business / Soziale Netzwerke`, `sensibel=true`, Besitzer `anna`; Abteilung Marketing besitzt „Soziale Netzwerke“. Erwartung: `anna` sieht sie, Leitung `chef` sieht sie, Marketing-Mitglied `ben` nicht, `BETREIBER_AGENT` nicht. Zweite Mail `privat / Konten & Sicherheit`, sensibel, Besitzer `anna`: `chef` sieht sie **nicht**.

- [ ] **Step 3: Run – FAIL** (lokal rein: `cd sales-mcp; python -m pytest tests/test_post_struktur.py -q -p no:cacheprovider --noconftest`; DB-Test auf der VM laut umgebung.md)
- [ ] **Step 4: Implementieren** (Konstanten, Funktionen, `sichtbar_sql`; alte „Unklar“-Erwartungen in Tests/Code auf `ps.UNKLAR` umstellen; `ui_post.kontostand` Spaltentitel „Zum Nachsehen“)
- [ ] **Step 5: Run – PASS** (beide Dateien + `test_post_markierungen.py test_post_bot.py test_post_einordnung.py` als Rückfallschutz)
- [ ] **Step 6: Commit** `feat(post): Unterfaecher, Beschreibungen, sensible Mails nur Besitzer/Leitung`

### Task 2: Datenmodell und Standardbereich je Konto

**Files:**
- Modify: `db/post-sammelstelle.sql` (am Ende anhängen, idempotent)
- Modify: `sales-mcp/post_konten.py` (`konto_anlegen`, `aktive_konten`)
- Modify: `sales-mcp/ui_post.py` (`konten_seite` Auswahl, `konten` POST)
- Test: `sales-mcp/tests/test_post_konten.py`, `sales-mcp/tests/test_post_einordnung_db.py` (Migration)

**Interfaces:**
- Produces (SQL):
  - `post_konten.standard_bereich text not null default 'business'` + Check `in ('privat','business')`
  - `post_mails.unterfach text`, `post_mails.vorschlaege jsonb`, `post_mails.modellaufrufe smallint not null default 0`, `post_mails.einordnung_version smallint not null default 1`, `post_mails.vorschau jsonb`, `post_mails.vorschau_am timestamptz`
  - Check `einordnung_quelle` neu: `in ('regel','modell','mensch','katalog','pruefer')` (alten Check per Name droppen, neu anlegen – idempotent)
  - `post_regeln.unterfach text`
  - `update post_mails set fach = 'Zum Nachsehen', bereich = 'privat' where fach = 'Unklar'`; `update post_regeln set fach = 'Zum Nachsehen' where fach = 'Unklar'`
  - `post_abteilung_faecher`: `('Marketing','Veranstaltungen')`, `('Marketing','Soziale Netzwerke')` `on conflict do nothing`
- Produces (Python): `konto_anlegen(besitzer, kennung, anbieter, adresse, passwort, standard_bereich: str = "business") -> dict`; ungültiger Wert → `{"fehler": ...}` ohne Probe; `aktive_konten()` liefert `standard_bereich` mit.

- [ ] **Step 1: Failing tests** – `test_migration_zweimal_einspielbar_und_unklar_umbenannt` (Zeile mit `business/Unklar` einfügen, SQL zweimal einspielen, Zeile ist `privat/Zum Nachsehen`, Spalten existieren); `test_konto_anlegen_standardbereich` (privat gespeichert; `"firma"` → fehler, keine Zeile); UI: Formular enthält `name="standard_bereich"` mit Optionen `business` (vorgewählt) und `privat`.
- [ ] **Step 2: Run – FAIL** (VM, sales_test)
- [ ] **Step 3: Implementieren**
- [ ] **Step 4: Run – PASS** (+ `test_post_konten.py test_postfaecher_zugang.py`)
- [ ] **Step 5: Commit** `feat(post): Datenmodell v2 (Unterfach, Vorschlaege, Standardbereich)`

### Task 3: Absender-Katalog

**Files:**
- Create: `sales-mcp/post_katalog.py`
- Test: `sales-mcp/tests/test_post_katalog.py`

**Interfaces:**
- Consumes: `post_struktur.FAECHER`, `UNTERFAECHER`
- Produces: `KATALOG: tuple[tuple[str, str, str | None], ...]` = (Domain-Endung, Fach, Unterfach); `domain(von: str) -> str` (aus `email.utils.parseaddr`, klein, ohne Punkt am Ende; leer wenn keine Adresse); `treffer(von: str) -> tuple[str, str | None] | None` – längste passende Endung gewinnt; passt nur bei `d == endung` oder `d.endswith("." + endung)`.

Erster Katalog (Entwurf, Felix bestätigt ihn in Task 7):

| Endungen | Fach | Unterfach |
|---|---|---|
| instagram.com | Soziale Netzwerke | Instagram |
| linkedin.com | Soziale Netzwerke | LinkedIn |
| tiktok.com | Soziale Netzwerke | TikTok |
| youtube.com | Soziale Netzwerke | YouTube |
| facebookmail.com, facebook.com, meta.com | Soziale Netzwerke | Facebook & Meta |
| x.com, twitter.com | Soziale Netzwerke | X |
| bsky.social, bsky.app | Soziale Netzwerke | Bluesky |
| mastodon.social | Soziale Netzwerke | Mastodon |
| threads.net, threads.com | Soziale Netzwerke | Threads |
| github.com | Tools & Dienste | GitHub |
| notion.so, notion.com, makenotion.com | Tools & Dienste | Notion |
| vercel.com | Tools & Dienste | Vercel |
| openrouter.ai | Tools & Dienste | OpenRouter |
| tailscale.com | Tools & Dienste | Tailscale |
| anthropic.com | Tools & Dienste | Anthropic |
| openai.com | Tools & Dienste | OpenAI |
| namecheap.com, privateemail.com | Tools & Dienste | Namecheap |
| hashnode.com | Tools & Dienste | Hashnode |
| dev.to | Tools & Dienste | dev.to |
| spotify.com | Tools & Dienste | Spotify |
| cal.com | Tools & Dienste | Cal.com |
| calendly.com | Tools & Dienste | Calendly |
| adobe.com | Tools & Dienste | Adobe |
| nebius.com | Tools & Dienste | Nebius |
| tavily.com | Tools & Dienste | Tavily |
| hs-send.com | Tools & Dienste | HubSpot |
| luma-mail.com, luma.com, lu.ma, easyfairs.com, easyfairs.de, devlunchclub.com | Veranstaltungen | – |
| substack.com | Newsletter & Branche | – |
| teamtailor-mail.com | Bewerbungen & Jobs | – |

Bewusst NICHT im Katalog: `gmail.com` und andere Freemailer, `vibemind.space` (eigene Domain), gemischte Absender (Hochschulen, Partner) – die entscheidet das Modell.

- [ ] **Step 1: Failing tests**

```python
def test_subdomain_trifft():
    assert k.treffer("Instagram <security@mail.instagram.com>") == ("Soziale Netzwerke", "Instagram")
    assert k.treffer("noreply@github.com") == ("Tools & Dienste", "GitHub")
    assert k.treffer("x@calendar.luma-mail.com") == ("Veranstaltungen", None)

def test_fremddomain_trifft_nicht():
    assert k.treffer("Instagram <x@evil.io>") is None
    assert k.treffer("a@instagram.com.evil.io") is None
    assert k.treffer("a@notinstagram.com") is None
    assert k.treffer("a@box.com") is None          # x.com darf nicht auf box.com passen
    assert k.treffer("kein absender") is None and k.treffer("") is None

def test_katalog_nur_gueltige_faecher():
    for endung, fach, unter in k.KATALOG:
        assert endung == endung.lower() and not endung.startswith(".")
        assert any(ps.fach_gueltig(br, fach) for br in ps.BEREICHE)
        assert ps.unterfach_gueltig(fach, unter)
    assert len({e for e, _, _ in k.KATALOG}) == len(k.KATALOG)
```

- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** · **Step 4: Run – PASS** (lokal, rein)
- [ ] **Step 5: Commit** `feat(post): Absender-Katalog fuer feste Faecher`

### Task 4: Einordnung v2 (Sortierer + Prüfer)

**Files:**
- Modify: `sales-mcp/post_einordnung.py`
- Test: `sales-mcp/tests/test_post_einordnung.py` (rein, mit Fake-`aufruf`)

**Interfaces:**
- Consumes: Task 1 (`UNTERFAECHER`, `BESCHREIBUNG`, `unterfach_zwingen`, `bereich_fuer`), Task 3 (`post_katalog.treffer`)
- Produces:
  - `@dataclass(frozen=True) class Einordnung: bereich: str; fach: str; sensibel: bool; quelle: str; begruendung: str; unterfach: str | None = None; aufrufe: int = 0; vorschlaege: dict | None = None` – `quelle` ∈ `'regel'|'katalog'|'modell'|'pruefer'`
  - `PRUEFER = "post-pruefer"` (Konstante)
  - `class PrueferFehlgeschlagen(Exception)` mit Attribut `vorschlag: Einordnung` (Sortierer-Ergebnis)
  - `einordnen(mail: dict, konto: dict, aufruf=gateway.funktion_aufrufen) -> Einordnung` – `konto` = `{"kennung": str, "standard_bereich": str}`
- Verhalten (Spec §5, in dieser Reihenfolge):
  1. `nach_muster` → `sensibel=True`, Fach `Konten & Sicherheit`, Bereich `konto["standard_bereich"]`, Unterfach = Katalog-Unterfach wenn es in `UNTERFAECHER["Konten & Sicherheit"]` liegt, sonst `"Sonstige"`; `aufrufe=0`.
  2. Nutzerregel (liest jetzt `unterfach` mit) → Bereich/Fach/Unterfach der Regel; Sortierer-Aufruf nur für `sensibel`; `quelle='regel'`, `aufrufe=1`.
  3. Katalog → Fach/Unterfach aus Katalog, Bereich `bereich_fuer(fach, standard)`; Sortierer-Aufruf nur für `sensibel`; sagt er sensibel → Fach `Konten & Sicherheit`, Unterfach = Katalog-Unterfach falls dort gültig, sonst `Sonstige`; `quelle='katalog'`, `aufrufe=1`.
  4. Sortierer (Agent `post`): Rückgabe-Schema `bereich, fach, unterfach (enum aller Unterfächer + ""), sensibel, sicher (bool), begruendung`; Auftrag enthält `konto["kennung"]`, `konto["standard_bereich"]`, `os.environ.get("POST_KONTEXT","")` (als Kontext des Inhabers, nicht als Mailinhalt), die Privat-Regel aus Spec §2.1, Fachliste mit `BESCHREIBUNG` und Unterfächern. Ergebnis wie heute auf die feste Liste zwingen (+ `unterfach_zwingen`).
  5. Prüfer (Agent `PRUEFER`, gleiches Schema, Auftrag enthält zusätzlich die Sortierer-Einordnung ohne deren Begründung; „im Zweifel nicht bestätigen“, „sicher=false wenn du zweifelst“). Prüfer-Ergebnis ebenso auf die Liste zwingen.
     - einig = gleiches (bereich, fach, unterfach) und beide `sicher` → Sortierer-Einordnung, `quelle='pruefer'`, `aufrufe=2`.
     - sonst → `privat / UNKLAR`, Unterfach `None`, `sensibel = s.sensibel or p.sensibel`, `quelle='modell'`, `aufrufe=2`, `vorschlaege = {"sortierer": {...}, "pruefer": {...}}` je `{"bereich","fach","unterfach"}` plus `"begruendung"` nur wenn nicht sensibel.
     - Prüfer wirft (GatewayFehler/GatewayTransient/sonstige) → `raise PrueferFehlgeschlagen(vorschlag=<Sortierer-Einordnung>)` – außer `GatewayTransient`, die wird unverändert weitergeworfen (Pause wie heute).
  - Sitzungsschlüssel: `f"agent:{AGENT}:mail:{id}"` bzw. `f"agent:{PRUEFER}:mail:{id}"`.

- [ ] **Step 1: Failing tests** (Fake-`aufruf(agent, schluessel, system, auftrag, funktion, **kw)` gibt je Agent vorgegebene dicts zurück und protokolliert Aufrufe)
  - `test_muster_trifft_ohne_modell_und_nimmt_standardbereich` – Betreff „Your security code“, von `security@mail.instagram.com`, Konto business → `business / Konten & Sicherheit / Instagram`, sensibel, 0 Aufrufe.
  - `test_katalog_ein_aufruf_kein_pruefer` – von `noreply@github.com`, Sortierer sagt sensibel=false → `business / Tools & Dienste / GitHub`, `quelle='katalog'`, Aufrufe nur Agent `post`.
  - `test_katalog_sensibel_lenkt_auf_konten` – Katalog Instagram, Sortierer sensibel=true → `Konten & Sicherheit / Instagram`, sensibel.
  - `test_katalog_business_fach_im_privatkonto` – Konto `privat`, Notion-Mail → Bereich `business`.
  - `test_einig_und_sicher` → `quelle='pruefer'`, `aufrufe=2`.
  - `test_uneinig_zum_nachsehen_privat_mit_beiden_vorschlaegen` (inkl. `sensibel` = ODER, Begründung fehlt in `vorschlaege` wenn sensibel).
  - `test_einig_aber_unsicher_zum_nachsehen`.
  - `test_pruefer_fach_aus_anderem_bereich_wird_gezwungen` (Prüfer sagt `privat / Tools & Dienste / Myspace` → kein Absturz, Ergebnis Zum Nachsehen).
  - `test_pruefer_fehler_wirft_mit_vorschlag`; `test_pruefer_transient_wird_durchgereicht`.
  - `test_auftrag_enthaelt_kontext_und_beschreibungen` (`POST_KONTEXT` per monkeypatch; Beschreibung von „Veranstaltungen“ steht im System- oder Auftragstext; Mailtext steht nur zwischen den Fremddaten-Markern).
  - Bestehende Tests an die neue Signatur `einordnen(mail, konto, aufruf=...)` anpassen.
- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** · **Step 4: Run – PASS** (lokal rein)
- [ ] **Step 5: Commit** `feat(post): Einordnung mit Katalog und Pruefer`

### Task 5: Abholdienst speichert v2

**Files:**
- Modify: `sales-mcp/post_abholen.py` (`einordnen_offene`, `_ergebnis_speichern`, `modellaufrufe_heute`)
- Test: `sales-mcp/tests/test_post_abholen.py`

**Interfaces:**
- Consumes: Task 2 (Spalten), Task 4 (`einordnen(mail, konto)`, `Einordnung`, `PrueferFehlgeschlagen`)
- Produces: `_ergebnis_speichern(mail_id, e: Einordnung) -> None` schreibt zusätzlich `unterfach`, `vorschlaege`, `modellaufrufe = e.aufrufe`, `einordnung_version = 2`; `modellaufrufe_heute() -> int` = `coalesce(sum(modellaufrufe),0)` über `eingeordnet_am::date = current_date` **plus** `coalesce(sum((vorschau->>'aufrufe')::int),0)` über `vorschau_am::date = current_date`.
- Verhalten: `eine_runde` übergibt `min(rest // 2, EINORDNEN_JE_RUNDE)` Mails, weil eine Mail bis zu 2 Aufrufe kostet und `rest` Aufrufe zählt. Die offene Abfrage joint `post_konten` für `kennung`, `standard_bereich`. `PrueferFehlgeschlagen` → `versuche + 1`; ab `VERSUCHE_MAX` → `privat / UNKLAR`, `status='eingeordnet'`, `einordnung_quelle='modell'`, `vorschlaege={"sortierer": ...}` (Begründung nur wenn nicht sensibel), `sensibel` = Vorschlag; darunter bleibt die Mail `neu` und die Runde **macht mit der nächsten Mail weiter**. Neue Mails mit `fehler` beim Abholen bekommen weiter `privat / UNKLAR`.

- [ ] **Step 1: Failing tests** (Fake-Einordnung per monkeypatch auf `post_einordnung.einordnen`):
  - `test_speichert_unterfach_vorschlaege_aufrufe_version`
  - `test_pruefer_fehler_bleibt_neu_dann_nach_drei_zum_nachsehen`
  - `test_tagesgrenze_zaehlt_aufrufe_und_vorschau` (eine Mail mit `modellaufrufe=2` heute + eine mit `vorschau={"aufrufe":2}` heute → 4)
  - `test_konto_kontext_wird_uebergeben` (Fake prüft `konto["standard_bereich"]`)
- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** · **Step 4: Run – PASS** (VM; dazu `test_post_einordnung_db.py`)
- [ ] **Step 5: Commit** `feat(post): Abholdienst speichert Einordnung v2`

### Task 6: Prüfer-Agent im Gateway

**Files:**
- Modify: `config/openclaw.json` (Saat: Agent `post-pruefer` nach `post`; Modelleintrag `claude-sonnet-5-5` falls nicht vorhanden)
- Modify: `deploy/post-anbinden.sh` (Schritt 4 trägt `post` UND `post-pruefer` ein; Probe erwartet beide in `/v1/models`)
- Modify: `deploy/post-sitzungen-aufraeumen.sh` (räumt `post` und `post-pruefer`)
- Modify: `docs/03_RUNBOOK.md` (Abschnitt Post-Sammelstelle: Prüfer, `POST_KONTEXT`, Neu-Sortierung aus Task 7)
- Test: `sales-mcp/tests/test_post_anbinden.py`

**Interfaces:**
- Produces: Gateway-Agent `{id: "post-pruefer", workspace: "/home/node/.openclaw/workspace-post-pruefer", tools: {deny: ["*"]}, model: {primary: "anthropic/claude-sonnet-5-5", fallbacks: []}}`; eigener Arbeitsordner mit AGENTS.md wie `post`.

- [ ] **Step 1: Failing tests** – `test_saat_kennt_pruefer_ohne_werkzeuge_ohne_rueckfall` (wie `test_saat_kennt_agent_post_ohne_werkzeuge` + `test_saat_agent_post_ohne_fallbacks`, Modell `anthropic/claude-sonnet-5-5`, Workspace ≠ `post`); `test_skript_traegt_beide_agenten_ein` (Skripttext enthält `"post-pruefer"`, `deny: ["*"]`, `fallbacks: []`, Probe auf `openclaw/post-pruefer`); `test_aufraeumen_kennt_beide_agenten`; `test_pruefer_id_im_code_gleich_saat` (`post_einordnung.PRUEFER` ist eine ID aus `config/openclaw.json`).
- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** (das Node-Snippet auf eine Liste `soll` mit beiden Agenten umbauen; Abbruchlogik bleibt) · **Step 4: Run – PASS** (VM: `test_post_anbinden.py`; `bash -n` der Skripte auf der VM, lokal stört CRLF)
- [ ] **Step 5: Commit** `feat(post): Pruefer-Agent post-pruefer im Gateway`

### Task 7: Neu-Sortierung des Altbestands (Vorschau, Bericht, Anwenden)

**Files:**
- Create: `sales-mcp/post_neu_einordnen.py`
- Create: `deploy/post-neu-einordnen.sh` (ruft `docker exec sales-post python -m post_neu_einordnen "$@"`, Laden-Argument wie die anderen post-Skripte)
- Test: `sales-mcp/tests/test_post_neu_einordnen.py`

**Interfaces:**
- Consumes: Task 4 `einordnen`, Task 5 `modellaufrufe_heute`, `post_abholen.TAGESGRENZE`
- Produces:
  - `vorschau(grenze: int, alle: bool = False) -> int` – für Mails mit `status in ('eingeordnet','fehler')`, `einordnung_quelle is distinct from 'mensch'`, `einordnung_version < 2`, und (`alle` oder `vorschau is null`): `einordnen` ausführen, Ergebnis als `vorschau` jsonb (`bereich, fach, unterfach, sensibel, quelle, begruendung, vorschlaege, aufrufe`) + `vorschau_am = now()` speichern; echte Spalten unverändert. Respektiert `TAGESGRENZE - modellaufrufe_heute()`. `PrueferFehlgeschlagen` → Vorschau als Zum Nachsehen mit Sortierer-Vorschlag (keine Wiederholung im Altbestand). Rückgabe = Zahl bearbeiteter Mails.
  - `bericht() -> dict` – nur Zahlen und Domains: `{"alt": {(bereich,fach): n}, "neu": {(bereich,fach,unterfach): n}, "zum_nachsehen": n, "offen": n, "katalog": [(endung, fach, unterfach, n)], "ohne_katalog": [(domain, n)] (Top 40)}`; nie Betreff/Text.
  - `anwenden() -> int` – kopiert `vorschau` in die echten Spalten (`sensibel = alt OR neu`; bei sensibel Text/Auszug/An/Anhänge leeren wie `_ergebnis_speichern`), `einordnung_version = 2`, `vorschau = null`; **nur** wo `einordnung_quelle is distinct from 'mensch'` zum Zeitpunkt des Updates (in der WHERE-Klausel, nicht vorher gelesen). Keine Modellaufrufe.
  - CLI: `python -m post_neu_einordnen vorschau [--alle] | bericht | anwenden` – gibt den Bericht als lesbare Tabelle aus.

- [ ] **Step 1: Failing tests** (VM, sales_test, Fake-`einordnen`):
  - `test_vorschau_aendert_echte_spalten_nicht`
  - `test_vorschau_ueberspringt_mensch_und_version_2`
  - `test_vorschau_haelt_tagesgrenze` (Grenze per monkeypatch auf 3, Fake gibt `aufrufe=2` → höchstens 2 Mails)
  - `test_anwenden_laesst_zwischenzeitliche_korrektur_unberuehrt` (nach Vorschau `einordnung_quelle='mensch'` setzen → nach `anwenden` unverändert)
  - `test_anwenden_macht_sensible_nie_unsensibel` (alt sensibel, Vorschau false → bleibt true)
  - `test_bericht_enthaelt_keine_betreffs` (Betreff „GEHEIM-123“ taucht im `str(bericht())` nicht auf)
- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** · **Step 4: Run – PASS**
- [ ] **Step 5: Commit** `feat(post): Neu-Sortierung mit Vorschau und Anwenden`

### Task 8: Oberfläche – Unterfächer, Zum Nachsehen, lernende Korrektur

**Files:**
- Modify: `sales-mcp/ui_post.py` (`faecher_zahlen`, `faecher_leiste`, `mail_zeile`, `mail`, `korrektur_formular`, `korrigieren`, neue Route `POST /post/mail/{id}/vorschlag`)
- Modify: `sales-mcp/post_struktur.py` (`mails_suchen` Parameter `unterfach: str = ""`)
- Test: `sales-mcp/tests/test_post_ui_v2.py` (Muster der vorhandenen UI-Tests mit TestClient und Anmeldung)

**Interfaces:**
- Consumes: Task 1, Task 2 (Spalten), Task 4 (`vorschlaege`-Format)
- Produces:
  - Navigation: unter einem Fach mit Unterfächern die Unterfächer mit Zähler als eingerückte Links (`?bereich=&fach=&unterfach=`), nur wenn ≥1 Mail.
  - Mail-Detail bei `fach == UNKLAR` und `vorschlaege`: je Vorschlag ein Formular `POST /post/mail/{id}/vorschlag` mit `wahl=sortierer|pruefer`, `regel=ja` (Haken, vorgewählt) und csrf; Knopftext `Sortierer: <Bereich · Fach · Unterfach>` bzw. `Prüfer: …`.
  - `korrektur_formular`: Auswahl `unterfach` (alle Unterfächer, leer erlaubt), Haken `regel` **vorgewählt**.
  - `korrigieren`/`vorschlag`: Rechte wie heute (`darf_korrigieren`, Regel nur `darf_regel_anlegen`); speichern `unterfach` (über `unterfach_zwingen`), `einordnung_quelle='mensch'`, `einordnung_version=2`, `vorschlaege=null`; Regel: vorhandene Regel mit gleichem `muster`, `feld='von'`, `besitzer` wird ersetzt (delete + insert in einer Transaktion), trägt `unterfach`.
- [ ] **Step 1: Failing tests** – `test_navigation_zeigt_unterfaecher_mit_zaehler`; `test_vorschlag_uebernehmen_setzt_mensch_und_regel`; `test_vorschlag_fremde_mail_ohne_regel` (Leitung übernimmt bei Bens Mail → keine Regel); `test_korrektur_regel_ersetzt_statt_verdoppelt`; `test_regelhaken_vorgewaehlt`; `test_filter_unterfach`.
- [ ] **Step 2: Run – FAIL** · **Step 3: Implementieren** · **Step 4: Run – PASS** (+ `test_post_markierungen.py test_posteingang.py test_post_sichtbarkeit.py`)
- [ ] **Step 5: Commit** `feat(post): Unterfaecher und Zum Nachsehen in der Oberflaeche`

### Abschluss (Controller, kein Subagent)

- Volle Suite auf der VM gegen die Basis vergleichen (vorbestehende Rote siehe umgebung.md).
- Ganzer-Branch-Review, Merge nach `feat/stufe-1-fundament` erst mit Felix' OK.
- **Rollout (je Schritt Felix' OK):** 1) `POST_KONTEXT` in VM-`.env` (Text mit Felix abstimmen), 2) `update.sh`, 3) `post-anbinden.sh` (Migration + Prüfer-Agent), 4) `post-neu-einordnen.sh vorschau` (über Tage bis die Tagesgrenze alles geschafft hat), 5) `bericht` + Katalog-Tabelle an Felix, Katalog-Änderungen einarbeiten (ggf. `vorschau --alle`), 6) `anwenden`, 7) Stichprobe von 20 Mails mit Felix.
