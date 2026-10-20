# Struktur-Graph (sales-ui) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber sieht auf `/team/struktur`, wer welchen sales-claw-Laden eingeladen hat. Die Ansicht zeigt einen SVG-Baum mit den Ebenen 1–6 und darunter eine Liste. Er setzt den Einlader schon beim Anlegen und kann ihn später ändern, ohne dass Ringe oder mehr als 6 Ebenen entstehen.

**Architecture:** Die Beziehung steht als neue Spalte `eingeladen_von` in `admin_auftraege` (nur `sales`/`sales_test`). Die Baum-Logik besteht aus reinen Funktionen in `sales-mcp/struktur.py`: Baum bauen, Ebene, Ringprüfung, Tiefenprüfung und Layout. Ohne DB und ohne `ui` ist sie einzeln testbar. `sales-mcp/ui_struktur.py` liest die Läden, zeichnet SVG und Liste und hängt die Routen nach dem `routen(ui)`-Muster von `ui_plan.py` ein. In `ui.py` ändern sich nur das Rollentor, das Menü, das CSS und das Formular „Laden anlegen“.

**Tech Stack:** Python 3.12, Starlette (server-gerendertes HTML), psycopg3 (`dict_row`), PostgreSQL 16, pytest.

**Spec:** Entwurf des Betreibers vom 20.10.2026. Er ist unten unter „Spec (Entwurf 20.10.2026)“ wörtlich zusammengefasst, damit er mit dem Plan reist. Vorgeschichte: `docs/superpowers/plans/2026-10-19-klaerung-reels-marke-struktur.md`, Thema 3 (Antwort S1: Ebene = Einladungstiefe relativ zum Betreiber).

### Spec (Entwurf 20.10.2026)

- Mitglieder sind Leute mit eigenem sales-claw-Laden. Läden legt nur der Betreiber an, über `/team/laden-anlegen` im Basis-Laden. Dabei entsteht eine Zeile in `admin_auftraege` mit `art='laden_anlegen'`. Ein Mitglied ist eine solche Zeile mit `status='erfolg'`.
- `admin_auftraege` bekommt per `provision.sql` (idempotent, in `sales` und `sales_test`) die Spalte `eingeladen_von text NULL`. NULL bedeutet: der Betreiber selbst (Basis-Laden). Sonst steht dort der `name` eines erfolgreich angelegten Ladens. Bestehende Läden landen damit auf Ebene 1.
- Das Formular „Laden anlegen“ bekommt die Auswahl „Eingeladen von“ mit „Ich“ und allen Läden mit Status `erfolg`. Der Server prüft, dass der Einlader existiert und dass Ebene(Einlader) + 1 ≤ 6 ist. Sonst gibt er eine klare deutsche Ablehnung zurück. Ebene ist der Abstand zum Betreiber, ein Kind des Betreibers hat also Ebene 1.
- Die Seite `/team/struktur` hat dieselben Rechte wie `/team/laden-anlegen` (`_ADMIN_BASIS_PFADE`). Der Menüeintrag „Struktur“ steht im Team-Bereich, im Desktop-Menü und auf `/mehr`.
- Der Graph ist serverseitiges Inline-SVG ohne JavaScript. Oben steht „Ich“, darunter folgen die Ebenen 1–6 als Reihen. Jeder Laden ist ein Kreis mit seiner Ebenen-Zahl, der Name steht darunter. Linien führen vom Einlader zum Eingeladenen. Farben kommen nur aus CSS-Variablen, hell und dunkel. Das Layout ist deterministisch: eine Reihe je Ebene, Kinder unter ihrem Elternteil, nach Name sortiert. Laden-Namen werden escaped, ein XSS-Test sichert das ab.
- Darunter steht dieselbe Struktur als eingerückte Liste, am Handy ist sie die Hauptansicht. Jeder Laden hat ein Formular „Einlader ändern“ (POST mit CSRF). Der Server prüft, dass der Einlader existiert, dass kein Ring entsteht und dass der ganze Teilbaum bei höchstens Ebene 6 bleibt. Danach springt die Seite zurück auf `/team/struktur`.
- Ohne Läden zeigt die Seite einen freundlichen Hinweis mit Link zu „Laden anlegen“.
- Nicht enthalten: Zoom und Ziehen, Kennzahlen je Mitglied, eine Sicht für andere Läden.

## Entscheidungen (vom Betreiber zu bestätigen)

- **E1 – Mitglied = jüngste `erfolg`-Zeile je Name.** `name` ist in `admin_auftraege` nicht eindeutig. `deploy/laden-anlegen.sh:58` verweigert zwar eine zweite Anlage, aber die Daten könnten trotzdem doppelt sein. Gelesen wird deshalb `distinct on (name) … order by name, erstellt_am desc`. Ein Umhängen schreibt **alle** `erfolg`-Zeilen dieses Namens, damit Lesen und Schreiben nie auseinanderlaufen.
- **E2 – Kein Fremdschlüssel, aber ein CHECK.** Wegen E1 ist kein FK möglich. Die Spalte bekommt stattdessen `check (eingeladen_von is null or eingeladen_von ~ '^[a-z][a-z0-9_]{0,30}$')`, dasselbe Muster wie `admin_auftraege_name_check` (`db/provision.sql:502`). Damit kann kein Markup in die Spalte gelangen.
- **E3 – Nur ein Spaltenrecht für `sales_app`.** Auf `sales.admin_auftraege` hat `sales_app` bisher nur `select, insert` (`db/provision.sql:528`, bewusst so, weil der Wirt `status` und `ergebnis` schreibt). Neu kommt **nur** `grant update (eingeladen_von)` hinzu. Status, Ergebnis und Name bleiben für die Oberfläche unveränderlich.
- **E4 – Zwei neue Dateien.** `sales-mcp/struktur.py` enthält reine Funktionen (kein `import ui`, kein `server`, keine DB). `sales-mcp/ui_struktur.py` liest die Läden, zeichnet und stellt die Routen nach dem Muster `ui_plan.routen(ui)` bereit (`ui.py:8125`). `ui.py` (8 176 Zeilen) wächst nur um Tor, Menü, CSS und das Anlegen-Formular.
- **E5 – Kaputte Daten führen nie zu einer Endlosschleife.** Steht in `eingeladen_von` ein unbekannter Name, oder bilden Zeilen einen Ring (etwa durch Handarbeit in der DB), dann hängt der betroffene Laden *wirksam* direkt unter dem Betreiber. Er wird als „verwaist“ markiert und bekommt in der Liste einen Hinweis. Ein Ring wird an seinem alphabetisch ersten Glied aufgebrochen. Das Ergebnis ist deterministisch.
- **E6 – Layout-Algorithmus „Blatt-Spalten“.** Eine Tiefensuche ab dem Betreiber läuft durch die Kinder, sortiert nach Name. Jedes Blatt bekommt die nächste freie Spalte (0, 1, 2 …). Ein Elternteil steht mittig zwischen der Spalte seines ersten und seines letzten Kindes. Die Reihe entspricht der Ebene (Betreiber = 0). Jeder Teilbaum belegt einen zusammenhängenden Spaltenbereich, deshalb überlappt nichts und Kinder stehen immer unter ihrem Elternteil. Konstanten: `SPALTE = 120`, `ZEILE = 90`, `RADIUS = 18`, `RAND = 30` (px).
- **E7 – Lange Namen im SVG werden gekürzt.** Ab 15 Zeichen zeigt das SVG die ersten 13 Zeichen plus „…“ (eine Spalte ist 120 px breit, Namen haben bis zu 31 Zeichen). Der volle Name steht im `<title>` des Knotens (Tooltip ohne JS). Die Liste zeigt immer den vollen Namen.
- **E8 – Am Handy kommt die Liste zuerst.** Unter 768 px dreht CSS die Reihenfolge um (`order: -1` für die Liste). Der Graph bleibt darunter und lässt sich waagerecht scrollen (`overflow-x: auto`). Ausgeblendet wird nichts.
- **E9 – Formularfeld `einlader`, der Wert `""` bedeutet „Ich“.** Fehlt das Feld ganz, gilt „Ich“. So bleiben alte Formulare und die bestehenden Tests in `test_laden_anlegen_seite.py` gültig. Beim Umhängen fehlen in der Auswahl der Laden selbst und seine Nachfahren. Zu tiefe Ziele bleiben wählbar, die Ablehnung kommt vom Server.
- **E10 – Prüfen und Schreiben in einer Transaktion.** Umhängen und Anlegen lesen die `erfolg`-Zeilen mit `for update` (dafür reicht das Spaltenrecht aus E3), prüfen und schreiben dann in derselben Verbindung. Zwei gleichzeitige Umhängungen können so keinen Ring erzeugen.
- **E11 – Der Menüeintrag „Struktur“ steht in der Gruppe „Admin“,** direkt nach „Laden anlegen“ (`ui.py:1734`). Dort liegen alle `/team/…`-Verwaltungsseiten, die Gruppe ist also der „Team-Bereich“ der Spec. `/mehr` übernimmt den Eintrag automatisch über `_menue_gruppen`.
- **E12 – Kein Rücksprungfeld.** Nach dem Umhängen folgt immer `303` auf `/team/struktur`, nach dem Anlegen wie bisher `303` auf `/team/laden-anlegen`. Falls später doch ein Rücksprungfeld nötig wird, heißt es `danach`.
- **E13 – Offene und laufende Aufträge zählen bei der Tiefenprüfung nicht mit.** Der Wirt arbeitet sie innerhalb von 20 s ab (`deploy/admin-auftrag-ausfuehren.sh`, Timer), und es gibt nur einen Betreiber. In Graph und Liste erscheinen nur `erfolg`-Zeilen.
- **E14 – Bestandsläden ohne Auftragszeile werden nachgetragen.** Ivan entstand am 16.09. per Skript, also vor der Oberfläche vom 22.09. Er hat vermutlich **keine** `admin_auftraege`-Zeile und fehlte damit im Graph. Task 5 trägt solche Läden nach Betreiber-OK als Zeile `status='erfolg'` mit `ergebnis = {"nachtrag": true}` und `angefordert_von='nachtrag-struktur'` nach. `_admin_auftrag_ergebnis_text` zeigt dafür „Bestehender Laden, für die Struktur nachgetragen.“ statt „Wegwerf-Passwort: ?“.
- **E15 – `provision.sql` läuft nicht automatisch.** Geprüft: `grep -c provision deploy/update.sh` liefert 0. Das bestätigt `docs/03_RUNBOOK.md:1706ff`, die Aussage im Plan vom 13.10. war falsch. Task 5 spielt die Datei deshalb **vor** dem Code-Update als `supabase_admin` ein. Würde der neue Code ohne die Spalte laufen, scheiterte `/team/laden-anlegen` mit SQLSTATE 42703.
- **E16 – Eigener DB-Klon für die Tests.** Der Testcontainer `sales-testdb` ist über `127.0.0.1:55600` erreichbar (`sales-testdb-fwd`). Parallele Sessions leeren die geteilte DB `postgres`, deshalb arbeitet dieses Vorhaben in einer eigenen Datenbank `sales_struktur` im selben Container (Rezept unter Global Constraints).

## Global Constraints

- Repo SC: `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`. Gearbeitet wird direkt auf dem Branch `feat/stufe-1-fundament`. Vor dem Start den WORKBOARD-Claim `cc-struktur-graph` prüfen (`C:/Users/User/Desktop/Vibemind_V1/WORKBOARD.md:31`). Vor jedem Commit `git status` und `git pull --no-rebase` ausführen. Nur eigene Dateien stagen, das untracked `.superpowers/` gehört jemand anderem.
- Commits als Conventional Commits. Die letzte Zeile lautet `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- sales-ui-Seiten enthalten **kein JavaScript** (CSP `ui.py:442`: `default-src 'none'; style-src 'unsafe-inline'; …`). Inline-`<svg>` ist Teil des Dokuments und wird nicht nachgeladen, deshalb blockiert die CSP es nicht. Die CSP wird **nicht** geändert. Das SVG bekommt keine `style=`-Attribute, keine `<a>`, kein `<image>`, kein `<foreignObject>` und keine `on*`-Attribute. Gestaltet wird nur über `class`.
- Farben kommen nur aus `:root`-Variablen (`ui.py:821–866`: `--akzent`, `--akzent_auf`, `--akzent_text`, `--flaeche`, `--linie`, `--linie_stark`, `--schrift`, `--gedaempft`, `--aktiv`, `--blush`, `--blush_text`, `--achtung`). Neues CSS enthält keine Hexwerte. SVG-Präsentationsattribute wie `fill="…"` werden nicht gesetzt, weil sie keine `var()` kennen.
- Anzeigetexte sind deutsch und haben echte Umlaute. **Das gilt auch für Klassennamen, Feldnamen und Pfade:** `tests/test_darstellung.py:88–97` sucht in der ganzen Seite nach Stämmen wie `aender`, `pruef`, `waehl` und `zurueck`. Erlaubt sind deshalb nur Bezeichner wie `struktur-graph`, `struktur-liste`, `einlader-wahl` und `/team/struktur/einlader`. Verboten wäre zum Beispiel `einlader-aendern`.
- Jeder Fremdwert (Laden-Name, Einlader) geht im HTML wie im SVG durch `html.escape(…, quote=True)`. `_fehlerseite` setzt `text` **roh** ein (`ui.py:2009`), deshalb werden Namen in Fehlertexten vorher escaped.
- Touch-Ziele sind mindestens 44 px hoch. Die Liste ist kein `_tabelle`, weil eine Einrückung als Tabelle nicht trägt. Sie ist eine verschachtelte `<ul>`.
- `MAX_EBENE = 6` steht an genau einer Stelle (`struktur.MAX_EBENE`).
- **Test-DB-Klon (einmalig, Task 1 Step 0):**
  ```powershell
  docker exec sales-testdb createdb -U postgres sales_struktur
  docker exec sales-testdb psql -U postgres -d sales_struktur -c "create schema if not exists extensions; create extension if not exists vector; create extension if not exists pgcrypto; create extension if not exists pg_trgm schema extensions"
  docker exec sales-testdb sh -c "pg_dump -U postgres -d postgres --schema-only -n sales -n sales_test -n compliance -n compliance_test | psql -U postgres -d sales_struktur -q"
  ```
  Prüfen: `docker exec sales-testdb psql -U postgres -d sales_struktur -Atc "select count(*) from information_schema.tables where table_schema='sales_test'"` muss größer als 0 sein.
- **Testlauf** (PowerShell, aus `sales-mcp`):
  ```powershell
  $env:SALES_DB_URL='postgresql://postgres:ci@127.0.0.1:55600/sales_struktur'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q
  ```
  Im Folgenden heißt das kurz **`PYTEST tests/<datei>`**.
- **Schema einspielen in den Klon** (nach jeder Änderung an `db/provision.sql`), aus dem SC-Wurzelverzeichnis:
  `Get-Content db/provision.sql -Raw | docker exec -i sales-testdb psql -U postgres -d sales_struktur -v ON_ERROR_STOP=1`.
  Scheitert das an Teilen, die nichts mit diesem Vorhaben zu tun haben, wird nur der geänderte `admin_auftraege`-Block (`db/provision.sql:460–520` samt Grant-Zeile) per `psql -c` eingespielt. Das kommt im Report zur Sprache.
- Deploy ist ein eigener letzter Task (Task 5) und läuft **nur nach Betreiber-OK**.

## Review Focus

1. **Ring durch Umhängen unter einen Enkel.** Wer `ivan` unter `otto` hängt, wobei `otto` unter `lena` und `lena` unter `ivan` steht, bekommt eine Ablehnung, und die DB bleibt unverändert. Test: `test_umhaengen_unter_enkel_ist_ring` (Task 1) und `test_post_ring_wird_abgewiesen` (Task 4).
2. **Teilbaum-Tiefe, nicht nur die Knotentiefe.** Ein Laden mit zwei Ebenen Nachfahren darf nicht unter einen Laden der Ebene 4 (das ergäbe 4+1+2 = 7), unter einen der Ebene 3 aber schon (genau 6). Test: `test_umhaengen_tiefe_grenze_genau_sechs` (Task 1) und `test_post_zu_tief_wird_abgewiesen` (Task 4).
3. **Kaputte Bestandsdaten (unbekannter Einlader, Ring in der DB).** Die Seite lädt trotzdem, ohne Endlosschleife, und zeigt den Hinweis „verwaist“. Test: `test_ring_in_daten_wird_aufgebrochen`, `test_unbekannter_einlader_wird_verwaist` (Task 1) und `test_seite_mit_verwaistem_laden` (Task 3).
4. **Nur `erfolg` zählt.** Offene, laufende oder fehlgeschlagene Aufträge erscheinen weder im Graph noch in der Auswahl und lassen sich nicht umhängen. Eine `fehler`-Zeile gleichen Namens bleibt beim Umhängen unverändert. Test: `test_nur_erfolg_erscheint` (Task 3), `test_auswahl_nur_erfolg` (Task 2), `test_post_aendert_nur_erfolg_zeilen` (Task 4).
5. **Fremddaten im SVG und in der Option-Liste.** Ein Name mit `<script>` oder `"` erscheint escaped, sowohl im Text als auch im Attribut `value="…"`. Test: `test_svg_escaped_namen`, `test_liste_escaped_namen` (Task 3).

---

## Dateien

| Datei | Verantwortung | Task |
|---|---|---|
| `sales-mcp/struktur.py` (neu) | reine Baum-Logik: `Baum`, `baum_bauen`, `nachfahren`, `teilbaum_tiefe`, `fehler_neuer_laden`, `fehler_umhaengen`, `Anordnung`, `anordnen` | 1 |
| `sales-mcp/tests/test_struktur.py` (neu) | Tests der reinen Logik | 1 |
| `db/provision.sql` (`admin_auftraege`-Block ab Z. 460, Grants Z. 528) | Spalte, CHECK, Spaltenrecht | 2 |
| `sales-mcp/ui_struktur.py` (neu) | `laeden_lesen`, `einlader_wahl`, `svg_zeichnen`, `liste_zeichnen`, `routen(ui)` | 2–4 |
| `sales-mcp/ui.py` | Formular und Aktion „Laden anlegen“ (Z. 5706–5771), Nachtrag-Text (Z. 5652ff), `_ADMIN_BASIS_PFADE` (Z. 552), `_GRUPPEN` (Z. 1734), Routenliste (Z. 8125), CSS in `_STIL` | 2–4 |
| `sales-mcp/tests/test_admin_auftraege_tabelle.py` | Spaltenliste, CHECK, Spaltenrecht | 2 |
| `sales-mcp/tests/test_laden_anlegen_seite.py` | Einlader beim Anlegen | 2 |
| `sales-mcp/tests/test_struktur_seite.py` (neu) | Seite, Tor, Menü, SVG, Liste, Umhängen | 3–4 |
| `sales-mcp/tests/test_darstellung.py` | `/team/struktur` in `SEITEN` (Z. 100) | 3 |

---

### Task 1: Baum-Logik als reine Funktionen

**Files:**
- Create: `sales-mcp/struktur.py`
- Test: `sales-mcp/tests/test_struktur.py`

**Interfaces:**
- Consumes: nichts.
- Produces (in `struktur.py`):
  ```python
  MAX_EBENE: int = 6
  SPALTE, ZEILE, RADIUS, RAND = 120, 90, 18, 30

  @dataclass(frozen=True)
  class Baum:
      kinder: dict[str | None, tuple[str, ...]]  # None = Betreiber; Kinder nach Name sortiert; nur Eltern mit Kindern
      einlader: dict[str, str | None]            # WIRKSAMER Einlader je Laden (nach E5-Reparatur)
      ebene: dict[str, int]                      # Kind des Betreibers = 1
      verwaist: frozenset[str]                   # gespeicherter Einlader unbekannt oder Ring

  def baum_bauen(laeden: Mapping[str, str | None]) -> Baum
  def nachfahren(baum: Baum, name: str) -> frozenset[str]          # ohne name selbst
  def teilbaum_tiefe(baum: Baum, name: str) -> int                 # 0 = keine Kinder; sonst max(ebene(n)) - ebene(name)
  def fehler_neuer_laden(baum: Baum, einlader: str | None) -> str | None
  def fehler_umhaengen(baum: Baum, name: str, einlader: str | None) -> str | None

  @dataclass(frozen=True)
  class Anordnung:
      punkte: dict[str | None, tuple[float, float]]  # Mittelpunkt je Knoten, None = Betreiber
      breite: int
      hoehe: int

  def anordnen(baum: Baum) -> Anordnung
  ```
  Die Fehlertexte sind deutsche Sätze **ohne** „Nichts wurde …“ (das hängt die Oberfläche an) und **unescaped** (die Oberfläche escaped sie).

- [ ] **Step 0: Test-DB-Klon `sales_struktur` anlegen** (Rezept unter Global Constraints). Erwartet: Die Prüfabfrage liefert eine Zahl größer als 0.

- [ ] **Step 1: Failing Tests schreiben** in `tests/test_struktur.py` (nur `import struktur`, keine DB):

```python
from struktur import (MAX_EBENE, anordnen, baum_bauen, fehler_neuer_laden,
                      fehler_umhaengen, nachfahren, teilbaum_tiefe)

KETTE = {"ivan": None, "lena": "ivan", "otto": "lena"}

def test_leer_ergibt_nur_betreiber():
    b = baum_bauen({})
    assert b.ebene == {} and b.kinder == {} and b.verwaist == frozenset()

def test_ebenen_relativ_zum_betreiber():
    assert baum_bauen(KETTE).ebene == {"ivan": 1, "lena": 2, "otto": 3}

def test_kinder_nach_name_sortiert():
    assert baum_bauen({"zora": None, "anna": None}).kinder[None] == ("anna", "zora")

def test_unbekannter_einlader_wird_verwaist():
    b = baum_bauen({"lena": "gibtsnicht"})
    assert b.ebene == {"lena": 1} and b.einlader == {"lena": None}
    assert b.verwaist == frozenset({"lena"})

def test_ring_in_daten_wird_aufgebrochen():
    b = baum_bauen({"b": "a", "a": "b"})
    assert b.ebene == {"a": 1, "b": 2} and b.verwaist == frozenset({"a"})

def test_nachfahren_und_teilbaum_tiefe():
    b = baum_bauen(KETTE)
    assert nachfahren(b, "ivan") == frozenset({"lena", "otto"})
    assert teilbaum_tiefe(b, "ivan") == 2 and teilbaum_tiefe(b, "otto") == 0

def test_neuer_laden_unter_ebene_fuenf_ok_unter_sechs_nicht():
    kette = {"e1": None, "e2": "e1", "e3": "e2", "e4": "e3", "e5": "e4", "e6": "e5"}
    b = baum_bauen(kette)
    assert fehler_neuer_laden(b, None) is None
    assert fehler_neuer_laden(b, "e5") is None
    assert "Ebene 7" in fehler_neuer_laden(b, "e6")
    assert MAX_EBENE == 6

def test_neuer_laden_unbekannter_einlader():
    assert "gibt es nicht" in fehler_neuer_laden(baum_bauen(KETTE), "nemo")

def test_umhaengen_unter_sich_selbst():
    assert "sich nicht selbst" in fehler_umhaengen(baum_bauen(KETTE), "lena", "lena")

def test_umhaengen_unter_enkel_ist_ring():
    assert "abstammt" in fehler_umhaengen(baum_bauen(KETTE), "ivan", "otto")

def test_umhaengen_unbekannt():
    b = baum_bauen(KETTE)
    assert "gibt es nicht" in fehler_umhaengen(b, "nemo", None)
    assert "gibt es nicht" in fehler_umhaengen(b, "lena", "nemo")

def test_umhaengen_tiefe_grenze_genau_sechs():
    # x hat zwei Ebenen Nachfahren; a1..a4 ist eine Kette (Ebenen 1..4)
    d = {"x": None, "x1": "x", "x2": "x1",
         "a1": None, "a2": "a1", "a3": "a2", "a4": "a3"}
    b = baum_bauen(d)
    assert fehler_umhaengen(b, "x", "a3") is None          # 3+1+2 = 6
    assert "Ebene 7" in fehler_umhaengen(b, "x", "a4")      # 4+1+2 = 7

def test_umhaengen_zum_betreiber_ok():
    assert fehler_umhaengen(baum_bauen(KETTE), "otto", None) is None

def test_anordnen_kinder_unter_elternteil_und_reihen_je_ebene():
    a = anordnen(baum_bauen({"ivan": None, "lena": "ivan", "mia": "ivan", "zora": None}))
    (xi, yi), (xl, yl), (xm, ym) = a.punkte["ivan"], a.punkte["lena"], a.punkte["mia"]
    assert xi == (xl + xm) / 2 and yl == ym > yi
    assert a.punkte["zora"][1] == yi
    assert a.punkte[None][1] < yi
    assert xl < xm < a.punkte["zora"][0]          # Sortierung nach Name, Gruppierung
    assert a.breite == 3 * 120 + 2 * 30            # drei Blätter

def test_anordnen_deterministisch():
    d1 = {"ivan": None, "lena": "ivan", "zora": None}
    d2 = {"zora": None, "lena": "ivan", "ivan": None}
    assert anordnen(baum_bauen(d1)) == anordnen(baum_bauen(d2))
```

- [ ] **Step 2: Tests laufen lassen.** `PYTEST tests/test_struktur.py`. Erwartet: FAIL mit `ModuleNotFoundError: No module named 'struktur'`.

- [ ] **Step 3: `sales-mcp/struktur.py` implementieren.** Die Signaturen stehen oben. Der Modul-Docstring nennt den Zweck und „keine DB, kein ui“.

  `baum_bauen` funktioniert so: Zuerst entsteht `roh_kinder` aus allen Einträgen, deren Einlader `None` oder ein bekannter Name ist. Eine Breitensuche ab `None` vergibt Ebenen. Danach geht die Funktion die **noch nicht erreichten** Namen in sortierter Reihenfolge durch. Jeder bekommt `einlader=None` und landet in `verwaist`, sein Teilbaum wird per Breitensuche erreicht. Was dabei erreicht wird, überspringt die Schleife. Danach ist `kinder` je Elternteil sortiert.

  `anordnen` setzt E6 so um:
  ```python
  spalte: dict[str | None, float] = {}
  frei = 0
  def setze(k):
      nonlocal frei
      ks = baum.kinder.get(k, ())
      if not ks:
          spalte[k] = frei; frei += 1; return
      for kind in ks:
          setze(kind)
      spalte[k] = (spalte[ks[0]] + spalte[ks[-1]]) / 2
  setze(None)
  # x = RAND + spalte*SPALTE + SPALTE/2 ; y = RAND + RADIUS + ebene*ZEILE (Betreiber ebene 0)
  # breite = max(1, frei)*SPALTE + 2*RAND ; hoehe = 2*RAND + 2*RADIUS + max_ebene*ZEILE + 20 (Platz für Namen)
  ```

  Die Fehlertexte sind wörtlich festgelegt (`{…}` sind die Namen):
  - Einlader unbekannt: `„{einlader}“ gibt es nicht als angelegten Laden.`
  - Laden unbekannt (Umhängen): `Den Laden „{name}“ gibt es nicht als angelegten Laden.`
  - Neuer Laden zu tief: `{einlader} steht auf Ebene {e}. Ein neuer Laden darunter läge auf Ebene {e+1}; erlaubt sind höchstens {MAX_EBENE} Ebenen.`
  - Selbst: `Ein Laden kann sich nicht selbst einladen.`
  - Ring: `{name} kann nicht unter {einlader} hängen, weil {einlader} selbst von {name} abstammt.`
  - Umhängen zu tief: `Unter {einlader} läge der Teilbaum von {name} bis Ebene {n}; erlaubt sind höchstens {MAX_EBENE} Ebenen.` (n = Ebene(Einlader) + 1 + teilbaum_tiefe; der Betreiber hat Ebene 0)

- [ ] **Step 4: Tests laufen lassen.** `PYTEST tests/test_struktur.py`. Erwartet: alle PASS.

- [ ] **Step 5: Commit.**
```powershell
git add sales-mcp/struktur.py sales-mcp/tests/test_struktur.py
git commit -m "feat(struktur): Baum, Ebenen, Ring- und Tiefenprüfung als reine Funktionen"
```

---

### Task 2: Spalte `eingeladen_von` und „Laden anlegen“ mit Einlader

**Files:**
- Modify: `db/provision.sql` (`admin_auftraege`-Schleife bis Z. 520, Grant Z. 528)
- Create: `sales-mcp/ui_struktur.py` (vorerst nur `laeden_lesen`, `einlader_wahl`)
- Modify: `sales-mcp/ui.py:5652–5684` (`_admin_auftrag_ergebnis_text`), `:5706–5771` (`laden_anlegen_seite`, `aktion_laden_anlegen`), Importliste (Z. 212–222)
- Test: `sales-mcp/tests/test_admin_auftraege_tabelle.py`, `sales-mcp/tests/test_laden_anlegen_seite.py`

**Interfaces:**
- Consumes: `struktur.baum_bauen`, `struktur.fehler_neuer_laden`, `struktur.Baum`.
- Produces (in `ui_struktur.py`):
  ```python
  def laeden_lesen(conn, sperren: bool = False) -> dict[str, str | None]
      # select distinct on (name) name, eingeladen_von from admin_auftraege
      #  where art='laden_anlegen' and status='erfolg' order by name, erstellt_am desc
      # sperren=True: dieselbe Abfrage als Unterabfrage über
      #  `select name, eingeladen_von, erstellt_am from admin_auftraege where … for update`
      #  (FOR UPDATE ist mit DISTINCT nicht erlaubt; erst sperren, dann in Python je Name die jüngste Zeile nehmen)
  def einlader_wahl(baum: struktur.Baum, gewaehlt: str | None,
                    ohne: frozenset[str] = frozenset()) -> str
      # <select name="einlader" class="einlader-wahl"> mit <option value="">Ich</option>
      # und je Laden (Ebene, dann Name sortiert) <option value="{name}">{name} (Ebene {n})</option>,
      # `selected` beim gewählten; Laden in `ohne` fehlen. Alles escaped.
  ```
  `conn` ist eine Verbindung aus `server.pool.connection()` (`dict_row`).

- [ ] **Step 1: Failing DB-Tests** in `tests/test_admin_auftraege_tabelle.py`:
  - `test_tabelle_existiert_mit_den_erwarteten_spalten`: Die erwartete Liste endet jetzt auf `"email", "eingeladen_von"`.
  - Neu:
```python
def test_eingeladen_von_erzwingt_das_namensmuster():
    with server.pool.connection() as conn:
        for schlecht in ("Ivan", "<script>", "a b", ""):
            ok = False
            try:
                conn.execute("insert into admin_auftraege (art, name, angefordert_von, eingeladen_von) "
                             "values ('laden_anlegen', 'lena', 'test', %s)", (schlecht,))
            except Exception as e:
                ok = "23514" in str(getattr(e, "sqlstate", "") or e)
            assert ok, schlecht
            conn.rollback()
        conn.execute("insert into admin_auftraege (art, name, angefordert_von, eingeladen_von) "
                     "values ('laden_anlegen', 'lena', 'test', null)")
        conn.rollback()

def test_sales_app_darf_auf_sales_nur_eingeladen_von_aendern():
    spalten = [z["column_name"] for z in server._q(
        "select column_name from information_schema.column_privileges "
        "where table_schema='sales' and table_name='admin_auftraege' "
        "and grantee='sales_app' and privilege_type='UPDATE'")]
    assert spalten == ["eingeladen_von"]
    tabelle = {z["privilege_type"] for z in server._q(
        "select privilege_type from information_schema.role_table_grants "
        "where table_schema='sales' and table_name='admin_auftraege' and grantee='sales_app'")}
    assert tabelle == {"INSERT", "SELECT"}
```

- [ ] **Step 2: Laufen lassen.** `PYTEST tests/test_admin_auftraege_tabelle.py`. Erwartet: drei FAIL (Spaltenliste, CHECK, Recht).

- [ ] **Step 3: `db/provision.sql` ergänzen.** In der Schleife `foreach s in array array['sales','sales_test']` kommt nach dem `email_check`-Block (vor `end loop;`, Z. 515) Folgendes, mit einem Kommentar zu Spec und Datum:
  - `alter table %I.admin_auftraege add column if not exists eingeladen_von text`
  - `drop constraint if exists admin_auftraege_eingeladen_von_check` + `add constraint admin_auftraege_eingeladen_von_check check (eingeladen_von is null or eingeladen_von ~ '^[a-z][a-z0-9_]{0,30}$')`

  Nach `grant select, insert on sales.admin_auftraege to sales_app;` (Z. 528) folgt `grant update (eingeladen_von) on sales.admin_auftraege to sales_app;`. Der Kommentar daneben sagt, dass nur diese Spalte veränderbar ist und Status und Ergebnis beim Wirt bleiben (E3).

  Danach in den Klon einspielen (Rezept unter Global Constraints) und **zweimal** laufen lassen, um die Idempotenz zu zeigen.

- [ ] **Step 4: Laufen lassen.** `PYTEST tests/test_admin_auftraege_tabelle.py`. Erwartet: alle PASS.

- [ ] **Step 5: Failing UI-Tests** in `tests/test_laden_anlegen_seite.py`. Den Helfer `_erfolg(name, einlader=None)` setzt eine `erfolg`-Zeile mit `eingeladen_von`.
```python
def test_auswahl_nur_erfolg():
    _erfolg("ivan")
    server._q("insert into admin_auftraege (art, name, angefordert_von) values ('laden_anlegen','offen1','t')")
    t = _get("/team/laden-anlegen").text
    assert '<select name="einlader"' in t and '<option value="">Ich</option>' in t
    assert '<option value="ivan">ivan (Ebene 1)</option>' in t
    assert 'value="offen1"' not in t

def test_anlegen_ohne_einlader_feld_ist_ich():      # alte Formulare, E9
    assert _post("/team/laden-anlegen/anfordern", {"name": "lena", "csrf": ui.CSRF_TOKEN}).status_code == 303
    assert server._q("select eingeladen_von from admin_auftraege")[0]["eingeladen_von"] is None

def test_anlegen_mit_einlader_speichert_ihn():
    _erfolg("ivan")
    r = _post("/team/laden-anlegen/anfordern", {"name": "lena", "einlader": "ivan", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert server._q("select eingeladen_von from admin_auftraege where name='lena'")[0]["eingeladen_von"] == "ivan"

def test_anlegen_unbekannter_einlader_wird_abgewiesen():
    r = _post("/team/laden-anlegen/anfordern", {"name": "lena", "einlader": "nemo", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400 and "gibt es nicht" in r.text and "Nichts wurde angelegt" in r.text
    assert server._q("select count(*) as n from admin_auftraege")[0]["n"] == 0

def test_anlegen_unter_ebene_sechs_wird_abgewiesen():
    vorher = None
    for n in ("e1", "e2", "e3", "e4", "e5", "e6"):
        _erfolg(n, vorher); vorher = n
    r = _post("/team/laden-anlegen/anfordern", {"name": "lena", "einlader": "e6", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400 and "Ebene 7" in r.text
    assert server._q("select count(*) as n from admin_auftraege where name='lena'")[0]["n"] == 0

def test_nachtrag_zeigt_keinen_passwort_platzhalter():   # E14
    server._q("insert into admin_auftraege (art,name,angefordert_von,status,ergebnis,erledigt_am) "
              "values ('laden_anlegen','ivan','nachtrag-struktur','erfolg','{\"nachtrag\": true}'::jsonb, now())")
    t = _get("/team/laden-anlegen").text
    assert "Bestehender Laden, für die Struktur nachgetragen." in t and "Wegwerf-Passwort" not in t
```

- [ ] **Step 6: Laufen lassen.** `PYTEST tests/test_laden_anlegen_seite.py`. Erwartet: die sechs neuen FAIL, die alten PASS.

- [ ] **Step 7: Implementieren.**
  - `ui_struktur.py` anlegen mit `laeden_lesen` und `einlader_wahl` (Signaturen oben). Der Modul-Docstring nennt Spec, Datum und „kein JavaScript“. `_e` ist ein lokales `html.escape(…, quote=True)` wie in `ui_muster.py:16`.
  - `ui.py`: `import struktur` und `import ui_struktur` in die Importliste.
  - `laden_anlegen_seite` bekommt unter dem E-Mail-Feld `<label>Eingeladen von<br>{einlader_wahl(baum, None)}</label>`, wobei `baum = struktur.baum_bauen(laeden_lesen(conn))`.
  - `aktion_laden_anlegen`: Nach den bestehenden Prüfungen wird `einlader = str(form.get("einlader") or "").strip() or None` gelesen. Im **selben** `with server.pool.connection() as conn:` passieren dann `laeden_lesen(conn, sperren=True)` → `fehler_neuer_laden` → bei einem Fehler `_fehlerseite(400, "Einlader nicht möglich", _e(text) + " Nichts wurde angelegt.")`, sonst das Insert mit Spalte `eingeladen_von` (E10).
  - `_admin_auftrag_ergebnis_text`: Im `erfolg`-Zweig für `laden_anlegen` gibt es vor der `willkommen`-Abfrage `if info.get("nachtrag"): return "Bestehender Laden, für die Struktur nachgetragen."`.

- [ ] **Step 8: Laufen lassen.** `PYTEST tests/test_laden_anlegen_seite.py tests/test_admin_auftraege_tabelle.py tests/test_tailscale_einladen_seite.py tests/test_darstellung.py`. Erwartet: alle PASS.

- [ ] **Step 9: Commit.**
```powershell
git add db/provision.sql sales-mcp/ui_struktur.py sales-mcp/ui.py sales-mcp/tests/test_admin_auftraege_tabelle.py sales-mcp/tests/test_laden_anlegen_seite.py
git commit -m "feat(laden-anlegen): Einlader wählen, Ebene höchstens 6 (admin_auftraege.eingeladen_von)"
```

---

### Task 3: Seite `/team/struktur` mit SVG-Graph und Liste

**Files:**
- Modify: `sales-mcp/ui_struktur.py` (`svg_zeichnen`, `liste_zeichnen`, `routen`)
- Modify: `sales-mcp/ui.py` (`_ADMIN_BASIS_PFADE` Z. 552, `_GRUPPEN` Admin Z. 1734, Routen Z. 8125, `_STIL`)
- Modify: `sales-mcp/tests/test_darstellung.py:100` (`SEITEN` + `"/team/struktur"`)
- Test: `sales-mcp/tests/test_struktur_seite.py` (neu)

**Interfaces:**
- Consumes: `struktur.baum_bauen`, `struktur.anordnen`, `struktur.nachfahren`, `struktur.Baum`, `struktur.RADIUS`, `ui_struktur.laeden_lesen`, `ui_struktur.einlader_wahl`.
- Produces (in `ui_struktur.py`):
  ```python
  def svg_zeichnen(baum: struktur.Baum) -> str
  def liste_zeichnen(baum: struktur.Baum, csrf: str) -> str
  def routen(ui) -> list   # Task 3: GET /team/struktur; Task 4 ergänzt POST /team/struktur/einlader
  ```
  Aufbau von `svg_zeichnen` (Klassennamen sind verbindlich, das CSS hängt daran):
  `<svg class="struktur-svg" xmlns="http://www.w3.org/2000/svg" width="{breite}" height="{hoehe}" viewBox="0 0 {breite} {hoehe}" role="img" aria-label="Struktur: wer wen eingeladen hat">`.
  Zuerst kommen alle Kanten als `<line class="kante" x1 y1 x2 y2>` (vom unteren Kreisrand des Einladers zum oberen Kreisrand des Eingeladenen). Danach folgt je Knoten `<g class="knoten ebene-{n}">` mit `<title>{name} – Ebene {n}</title>`, `<circle r="{RADIUS}">`, `<text class="zahl">{n}</text>` (mittig) und `<text class="name">{kurzname}</text>` (darunter, E7). Der Betreiber ist `<g class="knoten wurzel">` mit dem Text `Ich` im Kreis. Koordinaten werden mit `:g` formatiert.
  `liste_zeichnen`: `<ul class="struktur-liste"><li class="wurzel">Ich<ul>…</ul></li></ul>`. Je Laden gibt es ein `<li>` mit `<span class="ebene-zahl">{n}</span> <b>{name}</b>`, optional `<span class="meta">Einlader „{alt}“ nicht gefunden – hängt vorläufig direkt unter dir.</span>` (verwaist), ein Formular (Task 4) und die verschachtelte `<ul>` der Kinder.

- [ ] **Step 1: Failing Tests** in `tests/test_struktur_seite.py`. Kopf, `leer`-Fixture (truncate `admin_auftraege`), `_get` und `_post` wie in `test_laden_anlegen_seite.py`, dazu `_erfolg(name, einlader=None)`.
```python
import re, struktur, ui_struktur

def test_tor_wie_laden_anlegen(monkeypatch):
    for p in ("/team/struktur", "/team/struktur/einlader"):
        assert ui._pfad_erlaubt("freigeben", p) is True
        assert ui._pfad_erlaubt("lesen", p) is False and ui._pfad_erlaubt("kalender", p) is False
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/struktur") is False

def test_menue_und_mehr_tragen_struktur():
    gruppen = dict(ui._menue_gruppen("freigeben"))
    assert ("/team/struktur", "Struktur") in gruppen["Admin"]
    assert 'href="/team/struktur"' in ui._menue_links(ui._menue_gruppen("freigeben"), {}, None)
    assert "/team/struktur" not in ui._menue_links(ui._menue_gruppen("lesen"), {}, None)

def test_leerer_zustand():
    t = _get("/team/struktur").text
    assert "Noch keine Mitglieder" in t and 'href="/team/laden-anlegen"' in t and "<svg" not in t

def test_graph_und_liste():
    _erfolg("ivan"); _erfolg("lena", "ivan")
    r = _get("/team/struktur"); t = r.text
    assert r.status_code == 200 and "<script" not in t.lower()
    svg = t[t.index("<svg"):t.index("</svg>")]
    assert svg.count("<circle") == 3 and svg.count("<line") == 2
    assert '<text class="zahl"' in svg and ">Ich<" in svg and ">ivan<" in svg and ">lena<" in svg
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", svg) and "style=" not in svg
    assert t.index('class="struktur-liste"') > t.index("</svg>")
    assert r.headers["content-security-policy"] == ui._CSP

def test_nur_erfolg_erscheint():
    _erfolg("ivan")
    server._q("insert into admin_auftraege (art,name,angefordert_von,status) values ('laden_anlegen','kaputt','t','fehler')")
    assert "kaputt" not in _get("/team/struktur").text

def test_seite_mit_verwaistem_laden():
    server._q("insert into admin_auftraege (art,name,angefordert_von,status,eingeladen_von) "
              "values ('laden_anlegen','lena','t','erfolg','weg')")
    t = _get("/team/struktur").text
    assert "nicht gefunden" in t and ">lena<" in t

def test_svg_escaped_namen():
    svg = ui_struktur.svg_zeichnen(struktur.baum_bauen({'<script>"x': None}))
    assert "<script" not in svg and "&lt;script&gt;&quot;x" in svg

def test_liste_escaped_namen():
    html = ui_struktur.liste_zeichnen(struktur.baum_bauen({'a"><img': None, "b": None}), "tok")
    assert "<img" not in html and 'value="a&quot;&gt;&lt;img"' in html

def test_langer_name_gekuerzt_mit_vollem_titel():
    n = "a" * 31
    svg = ui_struktur.svg_zeichnen(struktur.baum_bauen({n: None}))
    assert f">{'a' * 13}…<" in svg and f"<title>{n} – Ebene 1</title>" in svg

def test_css_nur_variablen():
    teil = ui._STIL[ui._STIL.index("/* Struktur-Graph"):]
    teil = teil[:teil.index("/* Ende Struktur-Graph */")]
    assert "var(--akzent" in teil and not re.search(r"#[0-9a-fA-F]{3,8}\b", teil)
```
  Außerdem `"/team/struktur"` in `tests/test_darstellung.py:100` `SEITEN` eintragen.

- [ ] **Step 2: Laufen lassen.** `PYTEST tests/test_struktur_seite.py tests/test_darstellung.py`. Erwartet: FAIL (`AttributeError`/404).

- [ ] **Step 3: Implementieren.**
  - `ui_struktur.svg_zeichnen` und `liste_zeichnen` nach dem Interface oben. In dieser Task enthält die Liste noch **kein** Formular.
  - `routen(ui)`: `@ui._gesichert_seite async def seite(request)` liest per `with server.pool.connection() as conn` `laeden_lesen(conn)` und baut den Baum. Ohne Läden gibt es den Leerzustand `<p class="leer-hinweis">Noch keine Mitglieder. Sobald du einen Laden anlegst, erscheint er hier. <a href="/team/laden-anlegen">Laden anlegen</a></p>`. Sonst folgt `<div class="struktur"><div class="struktur-graph">{svg}</div>{liste}</div>`, außerdem ein `<p class="meta">` mit Erklärung („Ebene 1 = von dir eingeladen, höchstens 6 Ebenen.“). Rückgabe ist `ui._seite("Struktur", rumpf)` und `[Route("/team/struktur", seite)]`. `ui_struktur.py` importiert `server` selbst (wie `ui.py:224`), aber nie `ui`.
  - `ui.py`: `_ADMIN_BASIS_PFADE` erhält `"/team/struktur"`. `_GRUPPEN` Admin bekommt nach „Laden anlegen“ den Eintrag `("/team/struktur", "Struktur")`. Die Routenliste bekommt `*ui_struktur.routen(sys.modules[__name__]),` neben `ui_plan`. Der Kommentar an `_ADMIN_BASIS_PFADE` nennt Datum und Grund.
  - `_STIL`: Ein Block `/* Struktur-Graph (20.10.2026) … */` bis `/* Ende Struktur-Graph */` kommt vor die erste Handy-Regel, die nach den Kontaktseiten-Stilen folgt (etwa `ui.py:1380`). Inhalt:
    - `.struktur { display: flex; flex-direction: column; gap: 1rem; }`
    - `.struktur-graph { overflow-x: auto; background: var(--flaeche); border: 1px solid var(--linie); border-radius: 12px; }`
    - `.struktur-svg { display: block; max-width: none; }`
    - `.struktur-svg .kante { stroke: var(--linie_stark); stroke-width: 1.5; }`
    - `.struktur-svg circle { fill: var(--aktiv); stroke: var(--akzent); stroke-width: 2; }`
    - `.struktur-svg .wurzel circle { fill: var(--akzent); }`
    - `.struktur-svg .zahl { fill: var(--akzent_text); font: 700 14px var(--schrift_anzeige); text-anchor: middle; dominant-baseline: central; }`
    - `.struktur-svg .wurzel .zahl { fill: var(--akzent_auf); }`
    - `.struktur-svg .name { fill: var(--schrift); font: 12px var(--schrift_text); text-anchor: middle; }`
    - `.struktur-liste ul { margin-left: 1.2rem; border-left: 2px solid var(--linie); padding-left: .8rem; }`
    - `.struktur-liste .ebene-zahl` als runder Chip `background: var(--aktiv); color: var(--akzent_text)`
    - `.struktur-liste li { min-height: 44px; }`
    - `@media (max-width: 767px) { .struktur-liste { order: -1; } }` (E8)

    Hell und dunkel funktionieren automatisch, weil nur Variablen verwendet werden.

- [ ] **Step 4: Laufen lassen.** `PYTEST tests/test_struktur_seite.py tests/test_darstellung.py tests/test_handy.py tests/test_seitenleiste.py`. Erwartet: alle PASS.

- [ ] **Step 5: Sichtprüfung (Pflicht, ohne Commit-Artefakt).** sales-ui lokal gegen den Klon starten, mit `SALES_DB_SCHEMA=sales_test`, fünf Läden über zwei Ebenen und einem 31-Zeichen-Namen. `/team/struktur` hell und dunkel per Playwright bei 1280 px und 390 px ansehen. Prüfen, dass nichts überlappt, die Namen lesbar sind und am Handy die Liste oben steht. Die Screenshots kommen in den Report (Scratchpad, nicht ins Repo).

- [ ] **Step 6: Commit.**
```powershell
git add sales-mcp/ui_struktur.py sales-mcp/ui.py sales-mcp/tests/test_struktur_seite.py sales-mcp/tests/test_darstellung.py
git commit -m "feat(struktur): Seite /team/struktur mit SVG-Graph und Liste"
```

---

### Task 4: Einlader ändern

**Files:**
- Modify: `sales-mcp/ui_struktur.py` (`liste_zeichnen` + Formular, `routen` + POST)
- Test: `sales-mcp/tests/test_struktur_seite.py`

**Interfaces:**
- Consumes: `struktur.fehler_umhaengen`, `struktur.nachfahren`, `ui_struktur.einlader_wahl(baum, gewaehlt, ohne)`, `ui_struktur.laeden_lesen(conn, sperren=True)`, `ui._csrf_ok`, `ui._fehlerseite`, `ui._e`.
- Produces: `POST /team/struktur/einlader` mit den Feldern `csrf`, `name` und `einlader` (`""` = Ich). Erfolg ergibt `303` mit `Location: /team/struktur`, Fehler ergeben `400` und eine deutsche Fehlerseite, die auf „Nichts wurde geändert.“ endet.

- [ ] **Step 1: Failing Tests** (ergänzen):
```python
def _umhaengen(name, einlader, csrf=True):
    d = {"name": name, "einlader": einlader}
    if csrf: d["csrf"] = ui.CSRF_TOKEN
    return _post("/team/struktur/einlader", d)

def _einlader(name):
    return server._q("select eingeladen_von from admin_auftraege where name=%s and status='erfolg'", (name,))[0]["eingeladen_von"]

def test_liste_hat_formular_je_laden_ohne_eigene_nachfahren():
    _erfolg("ivan"); _erfolg("lena", "ivan")
    t = _get("/team/struktur").text
    assert t.count('action="/team/struktur/einlader"') == 2
    form_ivan = t[t.index('name="name" value="ivan"'):]
    form_ivan = form_ivan[:form_ivan.index("</form>")]
    assert 'value="lena"' not in form_ivan and '<option value="">Ich</option>' in form_ivan.replace(" selected", "")

def test_post_haengt_um_und_springt_zurueck():
    _erfolg("ivan"); _erfolg("lena")
    r = _umhaengen("lena", "ivan")
    assert r.status_code == 303 and r.headers["location"] == "/team/struktur"
    assert _einlader("lena") == "ivan"
    assert _umhaengen("lena", "").status_code == 303 and _einlader("lena") is None

def test_post_ohne_csrf():
    _erfolg("ivan"); _erfolg("lena")
    assert _umhaengen("lena", "ivan", csrf=False).status_code == 400 and _einlader("lena") is None

def test_post_unbekannt():
    _erfolg("ivan")
    server._q("insert into admin_auftraege (art,name,angefordert_von) values ('laden_anlegen','offen1','t')")
    assert _umhaengen("offen1", "ivan").status_code == 400
    r = _umhaengen("ivan", "nemo")
    assert r.status_code == 400 and "Nichts wurde geändert" in r.text and _einlader("ivan") is None

def test_post_ring_wird_abgewiesen():
    _erfolg("ivan"); _erfolg("lena", "ivan"); _erfolg("otto", "lena")
    r = _umhaengen("ivan", "otto")
    assert r.status_code == 400 and "abstammt" in r.text and _einlader("ivan") is None
    assert _umhaengen("lena", "lena").status_code == 400

def test_post_zu_tief_wird_abgewiesen():
    _erfolg("x"); _erfolg("x1", "x"); _erfolg("x2", "x1")
    vorher = None
    for n in ("a1", "a2", "a3", "a4"):
        _erfolg(n, vorher); vorher = n
    r = _umhaengen("x", "a4")
    assert r.status_code == 400 and "Ebene 7" in r.text and _einlader("x") is None
    assert _umhaengen("x", "a3").status_code == 303 and _einlader("x") == "a3"

def test_post_aendert_nur_erfolg_zeilen():
    _erfolg("ivan"); _erfolg("lena")
    server._q("insert into admin_auftraege (art,name,angefordert_von,status) values ('laden_anlegen','lena','t','fehler')")
    _umhaengen("lena", "ivan")
    assert server._q("select eingeladen_von from admin_auftraege where name='lena' and status='fehler'")[0]["eingeladen_von"] is None
```

- [ ] **Step 2: Laufen lassen.** `PYTEST tests/test_struktur_seite.py`. Erwartet: die neuen FAIL (404/Formular fehlt).

- [ ] **Step 3: Implementieren.**
  - `liste_zeichnen`: Je Laden gibt es `<form method="post" action="/team/struktur/einlader" class="einlader-form">` mit CSRF-Hidden, `<input type="hidden" name="name" value="{name}">`, `<label>Einlader ändern {einlader_wahl(baum, baum.einlader[name], ohne=nachfahren(baum, name) | {name})}</label>` und `<button type="submit">Ändern</button>`.
  - `routen`: Eine neue `@ui._gesichert_seite async def einlader(request)` liest das Formular und prüft `ui._csrf_ok(form)` (bei Fehler 400 mit demselben Text wie `aktion_laden_anlegen`). Die Felder sind `name = str(form.get("name") or "").strip()` und `neu = str(form.get("einlader") or "").strip() or None`. Danach öffnet sie `with server.pool.connection() as conn:` und ruft `laeden_lesen(conn, sperren=True)`, `baum_bauen` und `fehler_umhaengen` auf. Bei einem Fehler kommt `ui._fehlerseite(400, "Einlader nicht geändert", ui._e(text) + " Nichts wurde geändert.")`, sonst `conn.execute("update admin_auftraege set eingeladen_von = %s where art = 'laden_anlegen' and status = 'erfolg' and name = %s", (neu, name))`. Am Ende folgt `RedirectResponse("/team/struktur", status_code=303)`. Die Route ist `Route("/team/struktur/einlader", einlader, methods=["POST"])`.
  - CSS: `.einlader-form { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }`, `.einlader-form select, .einlader-form button { min-height: 44px; }` im Struktur-Block.

- [ ] **Step 4: Laufen lassen.** `PYTEST tests/test_struktur.py tests/test_struktur_seite.py tests/test_laden_anlegen_seite.py tests/test_admin_auftraege_tabelle.py tests/test_tailscale_einladen_seite.py tests/test_darstellung.py tests/test_handy.py tests/test_seitenleiste.py tests/test_ui.py`. Erwartet: alle PASS.

- [ ] **Step 5: Volle Suite** gegen den Klon: `PYTEST tests/ -q -p no:cacheprovider -rf` im Vordergrund. Das dauert ungefähr 20 Minuten. Die FAILED-Menge muss gleich der Baseline sein, die der Controller vor Task 1 auf demselben Klon erhebt.

- [ ] **Step 6: Commit.**
```powershell
git add sales-mcp/ui_struktur.py sales-mcp/ui.py sales-mcp/tests/test_struktur_seite.py
git commit -m "feat(struktur): Einlader ändern ohne Ringe und mit höchstens 6 Ebenen"
```

---

### Task 5: Auslieferung (Controller, nur nach Betreiber-OK)

**Files:** keine Codeänderung.

- [ ] **Step 1: Claims.** WORKBOARD-Zeile `cc-struktur-graph` auf „Deploy läuft“ setzen und nur die eigene Zeile stagen. Den Vault-Claim in `C:\Users\User\Desktop\secondbrain\00_Meta\002_Koordination_Live.md` setzen, weil die VM betroffen ist.
- [ ] **Step 2: Bestand prüfen (E14).** `ssh offload-vm "cd ~/sales-claw && ls deploy/laeden/*.env"` und `ssh offload-vm "docker exec debian-supabase-db-1 psql -U supabase_admin -d postgres -Atc \"select name, status from sales.admin_auftraege where art='laden_anlegen' order by name\""`. Fehlt ein Laden mit `.env` (außer `beispiel.env`) unter den `erfolg`-Zeilen, kommt die Liste vor den Betreiber.
- [ ] **Step 3: Schema zuerst (E15).** Auf der VM: `git fetch`, dann `git show origin/feat/stufe-1-fundament:db/provision.sql | docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1`. Danach prüfen: `select column_name from information_schema.column_privileges where table_schema='sales' and table_name='admin_auftraege' and grantee='sales_app' and privilege_type='UPDATE'` muss genau `eingeladen_von` liefern.
- [ ] **Step 4: Nachtrag (nur mit ausdrücklichem OK für Step 2).** Je fehlendem Laden `insert into sales.admin_auftraege (art, name, angefordert_von, status, ergebnis, erledigt_am) values ('laden_anlegen', '<name>', 'nachtrag-struktur', 'erfolg', '{"nachtrag": true}'::jsonb, now());` als `supabase_admin` ausführen. Der Wirt nimmt nur `offen`-Zeilen, deshalb löst das nichts aus.
- [ ] **Step 5: Code.** SC pushen, dann `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Erwartet ist der Erfolgsabschluss von `update.sh`, alle vorher laufenden Dienste laufen wieder.
- [ ] **Step 6: Echter Lauf (Betreiber-Browser, Basis-Laden).** `/team/struktur` zeigt Ivan (und alle Läden) auf Ebene 1. Ein Umhängen eines Ladens unter einen anderen und zurück funktioniert. „Laden anlegen“ zeigt die Auswahl. Ein Ring-Versuch wird abgewiesen. Mit einem Ivan-Login ist `/team/struktur` gesperrt (403) und fehlt im Menü.
- [ ] **Step 7: Abschluss.** Claims schließen, die Memory-Zeile zum Struktur-Graph eintragen und den Runbook-Hinweis in `docs/03_RUNBOOK.md` ergänzen („provision.sql vor update.sh, Spaltenrecht eingeladen_von“).

---

## Self-Review (erledigt)

- **Spec-Abdeckung:** Spalte und Idempotenz → T2. Auswahl beim Anlegen mit Server-Prüfung (existiert, Ebene ≤ 6) → T2. Rechte und Menü einschließlich `/mehr` → T3. SVG ohne JS mit Ich oben, Reihen, Kreisen mit Zahl, Namen darunter, Kanten, Variablenfarben und deterministischem Layout → T1 (E6) und T3. Escaping und XSS-Test → T3. Liste mit Handy-Vorrang → T3 (E8). Einlader ändern mit CSRF, Existenz, Ring, Teilbaum ≤ 6 und Rücksprung → T1 und T4. Leerzustand → T3. Ausschlüsse → nicht geplant. Deploy-Reihenfolge Schema vor Code → T5.
- **Typen:** `baum_bauen`/`Baum`/`anordnen`/`fehler_*` aus T1 heißen in T2–T4 gleich. `laeden_lesen(conn, sperren)` und `einlader_wahl(baum, gewaehlt, ohne)` werden in T2 definiert und in T3/T4 benutzt.
- **Umlaut-Falle:** Bezeichner (`einlader-form`, `einlader-wahl`, `/team/struktur/einlader`) enthalten keine Stämme aus `WOERTER_ASCII`.
