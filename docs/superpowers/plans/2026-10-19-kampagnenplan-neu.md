# Kampagnenplan neu gestalten (Karten je Tag, Reiter je Art) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Seite `/marketing/plan` zeigt den Monat als Karten je Tag mit gutem Leerzustand, hat Unter-Reiter "Alle" + je Art (mit Anzahl) und ein sauberes Formular mit eindeutiger Datumseingabe.

**Architecture:** Rein sales-ui-seitig (`sales-mcp/ui_plan.py` + CSS in `ui.py`). Die Marketing-API (`/api/pult/plan`, MOS `spaces/marketing/api/plan.py`) reicht unveraendert: sie liefert je Monat bis zu 500 Eintraege mit `art`, `status`, `angelegt_von`, `inhalt`. Gefiltert und gezaehlt wird in sales-ui ueber die schon geladene Monatsliste; keine Migration, kein API-Deploy.

**Tech Stack:** Python 3 / Starlette (server-gerendertes HTML ohne JS), pytest gegen `sales_test`.

**Spec:** keine - Entscheidungen E1..E9 unten, Quelle: Wunschliste C:/Users/User/Desktop/Vibemind_V1/tasks/2026-10-19-ui-marketing-wunschliste.md

## Was die API kann (geprueft am 19.10.)

- `GET /api/pult/plan?mandant&von&bis` (`api/plan.py:pult_lesen`): Eintraege des Zeitraums, `ORDER BY datum, erstellt_am`, `LIMIT 500`. Felder: `id, mandant, datum, art, titel, notiz, inhalt, status, angelegt_von, erstellt_am, geaendert_am`. **Kein Art-Filter** in der API.
- `POST /api/pult/plan` legt als Betreiber an (Status `geplant`); `plan_anlegen` lehnt Datum < gestern ab (SQL-Exception).
- `POST /api/pult/plan/{id}` aendert Status (`geplant|erledigt|verschoben|abgesagt`), Datum, Titel, Notiz, `inhalt`. `vorschlag` kann nur der Agent setzen (`POST /api/plan/vorschlag`, X-Agent-Key; Status wird dort erzwungen).
- Folgerung: Alles Gewuenschte (Reiter, Karten, Status, Vorschlaege annehmen) geht ohne API-Aenderung. Titel/Notiz bearbeiten koennte die API, ist aber nicht gewuenscht (YAGNI, E9).

## Entscheidungen (vom Betreiber zu bestaetigen)

- **E1 Karten je Tag statt Tabelle und statt Monatsraster.** Ohne JS wird ein 7-Spalten-Raster auf dem Handy unbrauchbar und die Aktionen (Uebernehmen, Verschieben) fuer mehrere Eintraege pro Zelle zu eng. Agenda-Karten funktionieren in beiden Breiten. Nur Tage MIT Eintraegen bekommen eine Gruppe (Kopf "Do 22. Oktober", heutiger Tag mit Marke "Heute"). Weicht bewusst von der `_tabelle`-Regel ab: die Seite ist eine Agenda, keine Datenliste.
- **E2 Reiter = Links `?art=<art>&monat=<JJJJ-MM>`**, Reihenfolge "Alle" + `ARTEN` in Code-Reihenfolge, je mit Anzahl. Aktiver Reiter traegt `aria-current="page"`. Monatsnavigation behaelt `art`, Reiter behalten `monat`. Unbekannte `art` faellt auf "Alle".
- **E3 Zaehlung = Eintraege des angezeigten Monats ohne `abgesagt`**; "Alle" = Summe. Die Zahl am Reiter stimmt damit mit dem ueberein, was man sieht.
- **E4 Abgesagte standardmaessig ausgeblendet**, Link "Abgesagte zeigen" (`?abgesagt=1`, bleibt in Navigation erhalten). Erledigte bleiben sichtbar, gedaempft.
- **E5 Reiter waehlt die Vorgabe-Art im Formular** (`<option selected>`); bei "Alle" bleibt "Newsletter" (erste Art) vorgewaehlt.
- **E6 Datumseingabe ohne Browser-Locale: drei Auswahlfelder Tag / Monat (ausgeschrieben) / Jahr** statt `<input type="date">`. `lang="de"` am Dokument steht schon (`ui.py:1650`) und aendert die Anzeige von `type=date` in Chrome nicht (richtet sich nach Betriebssystem-Sprache). Vorgabe: heute, wenn der angezeigte Monat der aktuelle ist, sonst der 1. des angezeigten Monats. Jahre: dieses und die zwei folgenden. Der Server setzt die Teile zu ISO zusammen (`datum_aus_teilen`). Das Verschieben-Feld an den Karten (`type=date`, aehnliches Problem) wird zur selben Dreierauswahl in einem `<details>`-Aufklapper ("Verschieben"), damit Karten ruhig bleiben.
- **E7 Formular als eigene Karte "Neuer Eintrag"**, am Desktop rechts neben der Agenda (Grid 2 Spalten, ab 900 px), am Handy unter der Agenda; Leerzustand und Kopf-Knopf "+ Neuer Eintrag" springen per `#neu` hin (reiner Anker, kein JS). Datum in der Vergangenheit prueft sales-ui vorab (422 mit Klartext), statt die SQL-Exception der API als 503/422 durchzureichen.
- **E8 Vorschlaege des Agenten heben sich ab**: Kartenrand und Chip "Vorschlag vom Agenten" in `--blush`/`--blush_text`, Knoepfe "Übernehmen" (primaer) und "Verwerfen". Das Banner-Satz oben bleibt ("N Vorschläge vom Agenten warten auf dich"), zaehlt nur den angezeigten Monat und nennt das. Status-Farben bleiben semantisch (`--gut` erledigt, `--achtung` verschoben); Violett (`--akzent`) nur fuer Handlung und aktiven Reiter.
- **E9 Kein Bearbeiten von Titel/Notiz und keine Verschiebung ueber Monatsgrenzen-Navigation hinaus**: nicht gewuenscht, API koennte es spaeter. Nach "Neuer Eintrag" landet man im Monat des Eintrags; ist ein Art-Reiter aktiv und die gewaehlte Art weicht ab, wird der Reiter auf "Alle" zurueckgesetzt (sonst wirkt der Eintrag verschwunden).

## Global Constraints

- sales-ui-Seiten haben KEIN JavaScript (CSP `default-src 'none'`); Interaktion nur ueber Links und Formulare (POST mit `csrf`-Feld wie bestehend). `<details>` ist erlaubt (kein JS).
- Anzeigetexte Deutsch mit echten Umlauten (`tests/test_darstellung.py` verbietet "zurueck", "fuer", "Uebernehmen" usw. in Literalen und Seiten).
- Keine `<img`-Tags; Fremddaten (Titel, Notiz, Art-Rohwert) immer ueber `ui._e` escapen (`tests/test_kampagnenplan.py` prueft `<script>` im Titel).
- Farben nur ueber CSS-Variablen aus `ui.py` `:root` (`--akzent`, `--aktiv`, `--blush`, `--blush_text`, `--gut`, `--achtung`, `--linie`, `--flaeche`, `--gedaempft`); keine festen Hexwerte; Oxanium nur fuer Ueberschriften/Tageskoepfe, DM Sans sonst. Hell- und Dunkelmodus kommen ueber die Tokens.
- Touch-Ziele >= 44 px (Reiter, Knoepfe, Auswahlfelder).
- Bestehende Routen und Formularnamen bleiben (`/marketing/plan`, `/marketing/plan/neu`, `/marketing/plan/{pid}`; Felder `csrf, zurueck, aktion, datum`), `zurueck` bleibt auf `/marketing/plan*` begrenzt (`zurueck_ziel`).
- Tests: `cd sales-mcp; SALES_DB_URL=postgresql://postgres:ci@127.0.0.1:55432/postgres SALES_DB_SCHEMA=sales_test E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/test_kampagnenplan.py tests/test_darstellung.py tests/test_ui.py -q` (Container sales-testdb laeuft).
- Commits: Conventional Commits, Ende `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; direkt auf `feat/stufe-1-fundament`; nur eigene Dateien stagen (`ui.py` ist eine heisse Datei: vor dem Commit `git pull --no-rebase`, `git diff --cached` pruefen, dass nur die Plan-CSS-Zeilen drin sind).
- Migrationsnummer: keine noetig (074 bleibt frei fuer andere Plaene).

## Review Focus

1. Monat mit 0 Eintraegen, mit Reiter ohne Treffer und mit nur abgesagten Eintraegen: je ein eigener Leerzustandstext mit Knopf zum Formular, kein leeres Gerippe (Task 2).
2. Aufruf mit manipulierten Parametern (`art=<script>`, `art=fax`, `monat=abc`, `abgesagt=2`): faellt auf Alle / aktuellen Monat / aus, nichts ungescaptes in Links (Task 1, 2).
3. Formular: 31. Februar, 31. April, 29. Februar im Nichtschaltjahr, Datum in der Vergangenheit: 422 mit Klartext, kein API-Aufruf (Task 3).
4. Eintrag mit `art` ausserhalb von `ARTEN` oder ohne Datum aus der API: wird unter "Sonstiges" bzw. am Ende ohne Absturz gezeigt, zaehlt bei "Alle" (Task 2).
5. Zurueck-Link nach einer Aktion kehrt in denselben Reiter/Monat zurueck (`zurueck` enthaelt `art` und `abgesagt`), ein fremdes Ziel faellt weiter auf `/marketing/plan` (Task 2).

---

## Dateien

- Modify: `sales-mcp/ui_plan.py` (Hilfen, `plan()`, `neu()`, `knoepfe()`; heute 195 Zeilen)
- Modify: `sales-mcp/ui.py` (CSS-Block neben `.filter` bei Z. 1106; keine Logik)
- Modify: `sales-mcp/tests/test_kampagnenplan.py`
- Optional lesen: `sales-mcp/marketing_mandant.py:48` (`umschalter`, unveraendert)

### Task 1: Reine Hilfen (Filter, Zaehlen, Gruppieren, Datum aus Teilen)

**Files:**
- Modify: `sales-mcp/ui_plan.py:54` (nach `datum_ok`)
- Test: `sales-mcp/tests/test_kampagnenplan.py` (Abschnitt "reine Hilfen")

**Interfaces:**
- Produces: `art_lesen(roh: str | None) -> str | None` (Wert aus `ARTEN` oder `None`); `zaehlen(eintraege: list[dict], abgesagte: bool) -> dict[str, int]` (Schluessel `"alle"` + je Art aus `ARTEN`, ohne `abgesagt` wenn `abgesagte` falsch); `nach_tagen(eintraege: list[dict]) -> list[tuple[date | None, list[dict]]]` (aufsteigend, Eintraege ohne lesbares Datum als `(None, [...])` am Ende); `datum_aus_teilen(tag, monat, jahr) -> str | None` (ISO oder `None`); `plan_pfad(erster: date, art: str | None, abgesagte: bool) -> str` (`/marketing/plan?monat=JJJJ-MM[&art=..][&abgesagt=1]`).

- [ ] **Step 1: Failing tests schreiben**

```python
@pytest.mark.parametrize("roh, erwartet", [("podcast", "podcast"), ("fax", None), ("", None),
                                           (None, None), ("<script>", None)])
def test_art_lesen(roh, erwartet):
    assert ui_plan.art_lesen(roh) == erwartet

def test_zaehlen_ohne_abgesagte():
    e = [{"art": "post", "status": "geplant"}, {"art": "post", "status": "abgesagt"},
         {"art": "video", "status": "erledigt"}, {"art": "gibtsnicht", "status": "geplant"}]
    z = ui_plan.zaehlen(e, abgesagte=False)
    assert z["alle"] == 3 and z["post"] == 1 and z["video"] == 1 and z["sonstiges"] == 1
    assert ui_plan.zaehlen(e, abgesagte=True)["alle"] == 4

def test_nach_tagen_gruppiert_und_sortiert():
    e = [{"datum": "2026-10-24", "titel": "b"}, {"datum": "2026-10-22", "titel": "a"},
         {"datum": "2026-10-24", "titel": "c"}, {"datum": "kaputt", "titel": "d"}]
    g = ui_plan.nach_tagen(e)
    assert [t for t, _ in g] == [date(2026, 10, 22), date(2026, 10, 24), None]
    assert [p["titel"] for p in g[1][1]] == ["b", "c"]

@pytest.mark.parametrize("t, m, j, erwartet", [
    ("22", "10", "2026", "2026-10-22"), ("31", "2", "2026", None), ("31", "4", "2026", None),
    ("29", "2", "2027", None), ("29", "2", "2028", "2028-02-29"), ("x", "10", "2026", None),
    ("", "", "", None)])
def test_datum_aus_teilen(t, m, j, erwartet):
    assert ui_plan.datum_aus_teilen(t, m, j) == erwartet

def test_plan_pfad():
    assert ui_plan.plan_pfad(date(2026, 10, 1), None, False) == "/marketing/plan?monat=2026-10"
    assert ui_plan.plan_pfad(date(2026, 10, 1), "post", True) == "/marketing/plan?monat=2026-10&art=post&abgesagt=1"
```

- [ ] **Step 2: Run: `pytest tests/test_kampagnenplan.py -q -k "art_lesen or zaehlen or nach_tagen or aus_teilen or plan_pfad"`** Expected: FAIL (AttributeError, Funktionen fehlen).
- [ ] **Step 3: Die fuenf Funktionen in `ui_plan.py` implementieren.** Unbekannte Art zaehlt als `sonstiges`; `datum_aus_teilen` baut `date(int(j), int(m), int(t))` mit `try/except ValueError`; `plan_pfad` nutzt `urllib.parse.urlencode` in fester Reihenfolge.
- [ ] **Step 4: Run wie Step 2.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(sales-ui): Kampagnenplan Hilfen fuer Reiter, Zaehlung, Tagesgruppen`

### Task 2: Seite mit Reitern, Tageskarten, Leerzustand

**Files:**
- Modify: `sales-mcp/ui_plan.py:80-149` (`knoepfe`, `plan`)
- Modify: `sales-mcp/ui.py` (CSS, siehe Task 4; fuer die Tests reicht Task 2 ohne CSS)
- Test: `sales-mcp/tests/test_kampagnenplan.py`

**Interfaces:**
- Consumes: Task 1 (`art_lesen, zaehlen, nach_tagen, plan_pfad`); `Falsch`-Fixture (`pult.eintraege`).
- Produces: Seite mit `<nav class="plan-reiter" aria-label="Art">` (Links `Alle (n)`, `Newsletter (n)` ...), je Tag `<section class="plan-tag">` mit `<h2>`, je Eintrag `<article class="plan-karte plan-<status>">`; Leerzustand `<div class="plan-leer">`; Formularanker `id="neu"` (Task 3 liefert das Formular).

- [ ] **Step 1: Failing tests**

```python
def test_reiter_zeigen_anzahl_und_filtern(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=podcast", headers=HOST).text
    assert 'aria-current="page"' in s and "Podcast (1)" in s and "Alle (2)" in s  # erledigter Post zaehlt mit, abgesagt nicht
    assert "Folge 2" in s and "Herbst-Newsletter" not in s
    assert "art=podcast" in s.split("Vormonat")[0][-200:] or "monat=2026-09&amp;art=podcast" in s

def test_gruppen_nach_tag_mit_wochentag(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert s.index("Fr 2. Oktober") < s.index("Do 22. Oktober") < s.index("Sa 24. Oktober")

def test_leerer_monat_hat_leerzustand_mit_knopf(angemeldet, pult):
    pult.eintraege = []
    s = angemeldet.get("/marketing/plan?monat=2026-12", headers=HOST).text
    assert "plan-leer" in s and 'href="#neu"' in s and "nichts geplant" in s.lower()

def test_reiter_ohne_treffer_sagt_welche_art(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=video", headers=HOST).text
    assert "Video" in s and "plan-leer" in s

def test_abgesagte_nur_auf_wunsch(angemeldet, pult):
    pult.eintraege.append({"id": "55555555-5555-5555-5555-555555555555", "datum": "2026-10-25",
                           "art": "post", "titel": "Alt", "notiz": "", "status": "abgesagt", "inhalt": None})
    assert "Alt" not in angemeldet.get("/marketing/plan?monat=2026-10", headers=HOST).text
    assert "Alt" in angemeldet.get("/marketing/plan?monat=2026-10&abgesagt=1", headers=HOST).text

@pytest.mark.parametrize("q", ["art=fax", "art=%3Cscript%3E", "monat=abc", "abgesagt=2"])
def test_manipulierte_parameter_fallen_zurueck(angemeldet, pult, q):
    r = angemeldet.get(f"/marketing/plan?{q}", headers=HOST)
    assert r.status_code == 200 and "<script>" not in r.text

def test_zurueck_traegt_reiter_in_den_knoepfen(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=newsletter", headers=HOST).text
    assert 'name="zurueck" value="/marketing/plan?monat=2026-10&amp;art=newsletter"' in s
```

Die bestehenden Seitentests (`test_seite_zeigt_monat_und_knoepfe`) bleiben gueltig: `Oktober 2026`, `monat=2026-09/11`, "1 Vorschlag vom Agenten", Aktionsformulare (3 je Vorschlag), Entwurf-Link, escapter Titel. Dort nur die Texte anpassen, die sich aendern (kein `<table>`-Bezug vorhanden).

- [ ] **Step 2: Run** `pytest tests/test_kampagnenplan.py -q` Expected: neue Tests FAIL.
- [ ] **Step 3: `plan()` umbauen.** Reihenfolge der Seite: Mandanten-Umschalter (unveraendert) -> Seitenkopf `<header class="plan-kopf">` mit `<h1>`-Zeile "Kampagnenplan", Untersatz (Vorschlag-Hinweis oder "Alles im Griff"), Knopf-Link "+ Neuer Eintrag" (`#neu`) -> Reiter-Nav -> Monatsleiste (`‹ Vormonat | Oktober 2026 | Nächster Monat ›`, plus Link "Heute" wenn Monat != aktueller, plus "Abgesagte zeigen/ausblenden") -> Grid (`.plan-spalten`) mit Agenda links und Formularkarte rechts (Task 3). `knoepfe()` bleibt je Karte, `hier` wird `plan_pfad(erster, art, abgesagte)` und damit `zurueck`. Je Karte: Art-Chip, Titel (`<b>`), Notiz, Link "Zum Entwurf", Status-Chip (Vorschlag mit `--blush`-Klasse, `angelegt_von == "agent"` als Zusatz "vom Agenten"), Knoepfe; Verschieben als `<details class="verschieben"><summary>Verschieben</summary>` mit der Dreierauswahl aus Task 3 (Hilfsfunktion `datum_felder(praefix, vorgabe: date) -> str` wird in Task 3 definiert; hier zunaechst das bisherige `type=date`-Feld belassen und in Task 3 ersetzen). Tageskopf: `f"{WOCHENTAGE[w]} {tag.day}. {MONATE[tag.month-1]}"` (ohne fuehrende Null), heutiger Tag zusaetzlich Chip "Heute". Leerzustaende: Monat leer -> "In {Monat} ist noch nichts geplant." + Knopf "Ersten Eintrag anlegen" (`#neu`); Reiter leer -> "Kein {Art}-Eintrag in {Monat}." + Link "Alle Arten zeigen"; nur Abgesagte -> Hinweis + Link "Abgesagte zeigen". Alle Strings mit echten Umlauten.
- [ ] **Step 4: Run wie Step 2 plus `tests/test_darstellung.py tests/test_ui.py`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(sales-ui): Kampagnenplan als Tageskarten mit Art-Reitern`

### Task 3: Formular mit Tag/Monat/Jahr und Vorabpruefung

**Files:**
- Modify: `sales-mcp/ui_plan.py` (`datum_felder`, Formular in `plan()`, `neu()`, Verschieben in `knoepfe`/`aendern`)
- Test: `sales-mcp/tests/test_kampagnenplan.py`

**Interfaces:**
- Consumes: Task 1 `datum_aus_teilen`, `plan_pfad`.
- Produces: `datum_felder(praefix: str, vorgabe: date, heute: date | None = None) -> str` (drei `<select>` mit Namen `{praefix}_tag|_monat|_jahr`, `aria-label` je Feld, Jahre `heute.year .. +2`). Formularfelder `neu`: `datum_tag, datum_monat, datum_jahr, art, titel, notiz, reiter, zurueck, csrf`. Verschieben-Felder: `neu_tag, neu_monat, neu_jahr` (Name `neu` kollidiert nicht mit `datum`).

- [ ] **Step 1: Failing tests**

```python
def test_formular_hat_drei_datumsfelder_keinen_datepicker(angemeldet, pult):
    s = angemeldet.get("/marketing/plan?monat=2026-10&art=video", headers=HOST).text
    assert 'name="datum_tag"' in s and 'name="datum_monat"' in s and 'name="datum_jahr"' in s
    assert 'type="date"' not in s
    assert '<option value="video" selected>' in s          # E5: Reiter = Vorgabe-Art
    assert 'name="reiter" value="video"' in s

def test_neu_aus_dreierauswahl(angemeldet, pult):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": "3", "datum_monat": "11", "datum_jahr": "2026",
              "art": "podcast", "titel": "Folge 3", "notiz": "", "reiter": "podcast"})
    assert r.status_code == 303 and r.headers["location"] == "/marketing/plan?monat=2026-11&art=podcast"
    assert pult.aufrufe[-1][2]["datum"] == "2026-11-03"

def test_neu_andere_art_als_reiter_geht_auf_alle(angemeldet, pult):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": "3", "datum_monat": "11", "datum_jahr": "2026",
              "art": "post", "titel": "T", "reiter": "podcast"})
    assert r.headers["location"] == "/marketing/plan?monat=2026-11"

@pytest.mark.parametrize("t, m, j", [("31", "2", "2027"), ("31", "4", "2027"), ("29", "2", "2027"), ("1", "1", "2020")])
def test_neu_unmoegliches_oder_vergangenes_datum_422(angemeldet, pult, t, m, j):
    r = angemeldet.post("/marketing/plan/neu", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "datum_tag": t, "datum_monat": m, "datum_jahr": j, "art": "post", "titel": "T"})
    assert r.status_code == 422 and not any(a[0] == "POST" for a in pult.aufrufe)

def test_verschieben_aus_dreierauswahl(angemeldet, pult):
    r = angemeldet.post(f"/marketing/plan/{PID}", headers=HOST, follow_redirects=False,
        data={"csrf": ui.CSRF_TOKEN, "aktion": "verschieben", "neu_tag": "29", "neu_monat": "10", "neu_jahr": "2026"})
    assert r.status_code == 303 and pult.aufrufe[-1] == ("POST", f"/plan/{PID}", {"datum": "2026-10-29"})
```

Die drei bestehenden Tests `test_neu_legt_fuer_gewaehlte_firma_an`, `test_neu_prueft_vorher` (Datum-Form) und `test_verschieben_schickt_nur_datum` werden auf die neuen Feldnamen umgestellt (Rueckwaertskompatibilitaet fuer das alte Feld `datum` wird NICHT gehalten: nur diese Seite postet dorthin). Der Test mit `datum: "03.11.2026"` entfaellt zugunsten der Parameterliste oben.

- [ ] **Step 2: Run** `pytest tests/test_kampagnenplan.py -q` Expected: FAIL.
- [ ] **Step 3: Implementieren.** `datum_felder` (Tag 1-31, Monat als `MONATE`-Name mit Wert 1-12, Jahr `heute.year..+2`, Vorgabe `selected`). Formularkarte `<section id="neu" class="plan-form">` mit Ueberschrift "Neuer Eintrag", Feldgruppen "Wann" / "Was" (Art als Select, Titel, Notiz), Hilfetext unter dem Knopf wie bisher, Knopf "Eintragen". `neu()`: Datum ueber `datum_aus_teilen`; `date.fromisoformat(d) < date.today() - 1 Tag` -> `ui._fehlerseite(422, "Nicht möglich", "Das Datum liegt in der Vergangenheit.")` (gleiche Grenze wie `plan_anlegen`: gestern ist erlaubt); Redirect `plan_pfad(erster Tag des Monats, art if reiter == art else None, False)`. `aendern()`: `verschieben` liest `neu_*` statt `datum`; Datum in der Vergangenheit ebenfalls 422. Vorgabe-Datum (E6) rechnet `plan()` aus.
- [ ] **Step 4: Run** wie Step 2 plus `tests/test_darstellung.py tests/test_ui.py` Expected: PASS.
- [ ] **Step 5: Commit** `feat(sales-ui): Kampagnenplan Formular mit Tag/Monat/Jahr und Vorabpruefung`

### Task 4: Gestaltung (CSS) und Sichtpruefung

**Files:**
- Modify: `sales-mcp/ui.py` (neuer CSS-Block "Kampagnenplan (19.10.2026)" nach `.filter ...` bei Z. ~1111)
- Test: `sales-mcp/tests/test_darstellung.py` (laeuft unveraendert; ggf. Fall fuer den Block, falls dort Hexwerte in `_STIL` geprueft werden)

**Interfaces:**
- Consumes: Klassen aus Task 2/3: `plan-kopf, plan-reiter, plan-monat, plan-spalten, plan-tag, plan-karte (plan-vorschlag|geplant|verschoben|erledigt|abgesagt), plan-chip, plan-leer, plan-form, verschieben`.

- [ ] **Step 1: Test (rot)** in `tests/test_darstellung.py` nach bestehendem Muster: der Kampagnenplan-Block in `ui._STIL` enthaelt keinen `#[0-9a-f]{3,6}`-Wert und `plan-reiter` ist definiert. Run -> FAIL.
- [ ] **Step 2: CSS schreiben (nur Tokens).** Reiter als Pillen wie `.filter a` mit `min-height: 44px`, aktiv gefuellt `--aktiv`/`--akzent_text` plus `aria-current`; Zaehl-Zahl als kleine Pille. Tageskopf in Oxanium 600, `--gedaempft`; heutiger Tag Chip in `--akzent`. Karte: `--flaeche`, 1px `--linie`, Radius 14px, weicher Schatten; Vorschlag mit linkem Rand 4px `--blush_text` auf `--blush`-Fond; erledigt `opacity .7` + `--gut`-Chip; abgesagt durchgestrichener Titel. `.plan-spalten` Grid `minmax(0,1fr)`, ab `min-width: 900px` `minmax(0,2fr) minmax(18rem,1fr)`; Formularkarte dort `position: sticky; top: 1rem`. Selects/Inputs `min-height: 44px`, Datum-Selects in einer Zeile (`flex-wrap`). Unter 768 px Knopfreihe der Karte volle Breite, die Fussleiste unten (`nav.tabs`) nicht ueberdecken (vorhandenes Bodenpolster der Seite nutzen, nicht neu setzen).
- [ ] **Step 3: Run** `pytest tests/test_kampagnenplan.py tests/test_darstellung.py tests/test_ui.py -q` Expected: PASS.
- [ ] **Step 4: Sichtpruefung.** UI lokal starten wie in den Design-Skripten (`scratchpad/design/lokal_shots.py` als Vorlage), Screenshots `/marketing/plan` Desktop 1440 / Handy 390, hell und dunkel, mit gefuellter Fake-Liste (Vorschlag, geplant, erledigt, abgesagt, mehrere am selben Tag) und leerem Monat. Pruefen: kein Wortbruch in Reitern/Knoepfen, kein Seitenueberlauf, Formular am Handy unter der Agenda, `lang="de"` und Monatsnamen deutsch.
- [ ] **Step 5: Commit** `feat(sales-ui): Kampagnenplan Gestaltung in VibeMind-Optik`

### Task 5: Auslieferung (nur nach Betreiber-OK)

**Files:** keine.

- [ ] **Step 1: Betreiber-OK einholen** (Screenshots aus Task 4 zeigen).
- [ ] **Step 2: Kein Migrations- und kein API-Schritt noetig** (Reihenfolge Migration -> API -> Arbeiter entfaellt; nur sales-ui). `git pull --no-rebase`, Push `feat/stufe-1-fundament`, Deploy der sales-ui nach bestehendem Ablauf (VM `deploy/update.sh`, PC-Haupt-Checkout restore; Abweichung im Haupt-Checkout = restore abbrechen).
- [ ] **Step 3: Live pruefen:** `/marketing/plan` laden, Reiter "Podcast" waehlen, Testeintrag anlegen, uebernehmen, absagen, Eintrag danach nicht mehr stehen lassen (absagen reicht, Loeschen gibt es nicht).

## Self-Review

- Spec-Abdeckung: Neugestaltung (E1, E7, E8, Task 2+4), Datumsformat (E6, Task 3), Monatsnavigation (Task 2: Pfeile, "Heute"), Leerzustand (Task 2), Reiter je Art mit Anzahl und Vorgabe-Art (E2, E3, E5, Task 2+3). API-Pruefung steht oben; keine API-Luecke.
- Typen: `art_lesen/zaehlen/nach_tagen/datum_aus_teilen/plan_pfad/datum_felder` einheitlich in Tasks 1-3; Feldnamen `datum_tag|monat|jahr`, `neu_*`, `reiter` konsistent.
- Proportion: Code-Bloecke nur Tests; Implementierungen als Signaturen.
- Offene Punkte: Vorschlaege anderer Monate bleiben unsichtbar, solange man nicht blaettert (E8 nennt "angezeigter Monat"); falls unerwuenscht, zweiter API-Aufruf `von=heute bis=+90` fuer den Hinweis als Folgeaufgabe.
