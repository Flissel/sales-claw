# Post-Sammelstelle aufräumen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Posteingänge der vier Postfächer enthalten nur noch Mails, die Aufmerksamkeit brauchen. Der Rest liegt in „Zur Info“, Werbung wird gelöscht: im Altbestand nach Freigabe je Jahr, neue Werbung über „To-Review“.

**Architecture:**
- Die Einordnung (`post_einordnung`) liefert zusätzlich `aufmerksamkeit`.
- Eine reine Funktion (`post_ziel.ziel_fuer`) leitet daraus je Mail das Ziel ab: `posteingang | zur_info | to_review | loeschen`.
- Ein neuer Schritt in der Runde von `sales-post` (`post_ordnen.ordnen`) gleicht das Postfach per IMAP an das Ziel an. Die IMAP-Befehle liegen gekapselt in `post_imap`.
- Die Löschfreigabe je Jahr (`post_freigabe`) und neue Reiter im Mail-Reiter (`ui_post`) schließen es ab.
- Ein Schalter `POST_ORDNEN` (aus | verschieben | voll) lässt Deploy und Einschalten getrennt.

**Tech Stack:** Python 3 (imaplib), Postgres (psycopg, `server._q`), Starlette-UI ohne JavaScript, pytest im Container gegen `sales_test`.

**Spec:** `docs/superpowers/specs/2026-11-06-post-aufraeumen-design.md`

## Global Constraints

- Alles unter `sales-mcp/`, Tests unter `sales-mcp/tests/`. Testlauf: `docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test <image> python -m pytest -q <dateien>` auf der VM; nie gegen `sales`.
- Schema-Änderungen nur idempotent in `db/post-sammelstelle.sql` (`add column if not exists`, `create table if not exists`). Vor Tests in `sales_test` einspielen.
- Kein Test öffnet eine echte IMAP-Verbindung: `postfach._imap_oeffnen` ist in `tests/conftest.py` gesperrt. Neue Module bekommen den Kasten übergeben oder öffnen über `post_konten.verbinden`, das dort endet.
- Keine Geheimnisse und kein Mailinhalt in Logs. Logzeilen nennen nur Konto-Kennung, Zahlen und Fehlertyp (`type(e).__name__`).
- Sichtbarkeit nur über `post_struktur.sichtbar_sql`. Freigabe und Löschen nur für Konten des eigenen `besitzer`, auch die Leitung darf nicht für fremde Konten freigeben.
- Neue Einordnungen schreiben `einordnung_version = 3`.
- Kein IMAP-Befehl darf mehr als die gemeinte UID treffen. Also nie ein nacktes `expunge()`, nur `UID MOVE` oder `UID EXPUNGE <uid>`. Fehlen beide, gilt `NichtUnterstuetzt`.
- Werte: Aufmerksamkeit im Altbestand nur für Mails jünger als **90 Tage** (ab Mail-Datum). Login-Codes gehen nach **1 Tag** nach Zur Info. To-Review wird nach **30 Tagen** gelöscht. „Zum Nachsehen“ liegt immer im Posteingang. Die Tagesgrenze bleibt **500**.
- Ordnernamen im Postfach: `Zur Info`, `To-Review`.
- Fächer „Bleibt immer“ (`post_struktur.BLEIBT_IMMER`, angelegt in Task 3): Rechnungen, Käufe & Bestellungen, Konten & Sicherheit, Behörden & Versicherung, Gesundheit, Familie & Freunde, Kunden & Anfragen, Partner & Netzwerk.
- `sales-auto` nie starten. Deploy und `POST_ORDNEN` ≠ `aus` nur mit Felix' OK.

## Review Focus

1. **Felix verschiebt oder löscht eine Mail in der Handy-App**, bevor `ordnen` sie anfasst (UID fehlt im Ordner). Erwartung: diese Mail bekommt `ordner_stand = 'fehlt'`, der Rest der Runde läuft weiter. → Test in Task 5.
2. **Freigabe eines Jahres, während dessen Einordnung noch läuft.** Mails, die danach als Werbung erkannt werden, gehen nach To-Review, nicht direkt ins Löschen. → Test in Task 7.
3. **Werbe-Absender-Regel trifft eine Rechnung** (Betreff „Ihre Rechnung“). Erwartung: Die Regel greift nicht, die Mail geht zum Modell. → Test in Task 3.
4. **Leitung oder ein anderer Benutzer** ruft Vorschau oder Freigabe für Felix' privates Postfach auf. Erwartung: Die fremden Konten sind nicht enthalten, nichts wird freigegeben. → Test in Task 7.
5. **Server ohne MOVE und ohne UIDPLUS.** Erwartung: Für dieses Konto ruhen Verschieben und Löschen, Grund steht in `post_konten.ordnen_aus`. Andere Konten laufen weiter, Einordnen läuft weiter. → Test in Task 5.

---

### Task 1: Datenmodell

**Files:**
- Modify: `db/post-sammelstelle.sql` (am Ende anhängen)
- Test: `sales-mcp/tests/test_post_aufraeumen_schema.py`

**Interfaces:**
- Produces (Spalten und Tabellen, die alle späteren Tasks nutzen):
  - `post_mails`:
    - `aufmerksamkeit boolean`
    - `werbung_sicher boolean not null default false`
    - `ziel text check (ziel in ('posteingang','zur_info','to_review','loeschen'))`
    - `ziel_manuell boolean not null default false`
    - `ordner text not null default 'INBOX'`
    - `ordner_uid bigint`
    - `ordner_stand text check (ordner_stand in ('ok','fehlt','fehler'))`
    - `ordner_am timestamptz`
    - `urspruengliche_adresse text`
    - `geloescht_am timestamptz`
    - Status-Check erweitert um `'geloescht'`.
  - `post_konten.ordnen_aus text`: Grund, warum Verschieben und Löschen ruhen; `null` heißt aktiv.
  - `post_regeln.art text not null default 'einordnen' check (art in ('einordnen','nie_werbung'))`.
  - Tabelle `post_loeschfreigaben`:
    - Spalten: `id uuid pk default gen_random_uuid()`, `besitzer text not null`, `jahr int not null`, `freigegeben_am timestamptz not null default now()`, `ausgenommen jsonb not null default '[]'`.
    - `unique(besitzer, jahr)`.
  - Index `post_mails(ziel, ordner)`.

- [ ] **Step 1: Write the failing test**

`test_spalten_und_tabellen_da()`
- liest `information_schema.columns` für `sales_test`;
- prüft, dass jede oben genannte Spalte existiert;
- prüft, dass `insert ... status='geloescht'` gelingt und `ziel='weg'` mit `psycopg.errors.CheckViolation` scheitert;
- prüft, dass `post_loeschfreigaben` mit doppeltem `(besitzer, jahr)` `UniqueViolation` wirft.

`test_sql_ist_idempotent()`: Die Datei zweimal hintereinander per psql einspielen. Muster wie in den bestehenden Schema-Tests, falls vorhanden; sonst nur zweimal `server._q` auf den Abschnitt. Beim zweiten Mal kein Fehler.

- [ ] **Step 2: Run, expect FAIL** (Spalten fehlen).

- [ ] **Step 3: SQL-Abschnitt** `-- Aufräumen (Spec 2026-11-06)` anhängen.
  - Den Status-Check per `alter table ... drop constraint if exists <name>; add constraint ...` ersetzen. Den Namen des bestehenden Checks aus `pg_constraint` lesen und im SQL fest eintragen.

- [ ] **Step 4: SQL in `sales_test` einspielen, Test PASS.**

- [ ] **Step 5: Commit** `feat(post): Datenmodell fuer Aufraeumen`

---

### Task 2: Einordnung kennt Postfach-Art und Aufmerksamkeit

**Files:**
- Modify: `sales-mcp/post_struktur.py` (BESCHREIBUNG)
- Modify: `sales-mcp/post_einordnung.py` (`Einordnung`, `FUNKTION`, `SYSTEM`, `_auftrag`, `_Urteil`, `_urteil_holen`, `einordnen`)
- Modify: `sales-mcp/post_abholen.py:_ergebnis_speichern` (neue Spalten, Version 3)
- Test: `sales-mcp/tests/test_post_einordnung.py` (ergänzen)

**Interfaces:**
- Produces:
  - `Einordnung.aufmerksamkeit: bool = False` (neues Feld, Default hinten)
  - `Einordnung.werbung_sicher: bool = False`
  - `FUNKTION` verlangt zusätzlich `"aufmerksamkeit": boolean`
  - `_sensibel_entscheiden` wird zu `_merkmale(mail, konto, aufruf) -> tuple[bool, bool]` (sensibel, aufmerksamkeit), ein Aufruf
  - `_ergebnis_speichern` schreibt `aufmerksamkeit`, `werbung_sicher`, `einordnung_version = 3`

- [ ] **Step 1: Write failing tests**

```python
def test_privates_postfach_bekommt_privat_regeln_im_auftrag():
    a = post_einordnung._auftrag({"id": "1", "von": "x@y.de", "betreff": "b", "text": ""},
                                 {"kennung": "gmx-felix", "standard_bereich": "privat"})
    assert "Privates Postfach" in a and "im Zweifel Business" not in a

def test_firmenpostfach_behaelt_im_zweifel_business():
    a = post_einordnung._auftrag({"id": "1", "von": "", "betreff": "", "text": ""},
                                 {"kennung": "haupt", "standard_bereich": "business"})
    assert "im Zweifel Business" in a

def test_aufmerksamkeit_wird_oder_verknuepft():
    # Sortierer sagt True, Pruefer False, sonst einig und sicher -> True
    ...  # Fake-aufruf wie in den bestehenden Tests, Antworten mit "aufmerksamkeit"
    assert e.aufmerksamkeit is True and e.fach == "Rechnungen"

def test_einig_werbung_ist_werbung_sicher():
    ...  # beide: business/Werbung, sicher=True
    assert e.werbung_sicher is True

def test_katalog_treffer_liefert_aufmerksamkeit_aus_einem_aufruf():
    ...  # Katalog-Domain; Fake liefert sensibel=False, aufmerksamkeit=True
    assert e.aufrufe == 1 and e.aufmerksamkeit is True

def test_tools_und_dienste_beschreibung_ohne_werbung():
    assert "Werbung" not in post_struktur.BESCHREIBUNG[("business", "Tools & Dienste")]
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - Den Satz „Im Firmenpostfach gilt: im Zweifel Business.“ aus `SYSTEM` nehmen. `_auftrag` hängt je nach `_standard(konto)` einen dieser Sätze an:
    - **privat:** „Privates Postfach: Abos, Rechnungen, Käufe, Konten und Newsletter des Inhabers sind privat. Business ist nur, was erkennbar die Firma betrifft.“
    - **business:** „Firmenpostfach: im Zweifel Business.“
    - Die Sätze stehen außerhalb der Fremddaten-Marker.
  - Neuer Absatz in `SYSTEM`: Aufmerksamkeit nach Spec §5. Die Tabelle steht als zwei Listen im Prompt, wörtlich aus der Spec.
  - Neuer Absatz in `SYSTEM` zur Werbung: „Werbung = Kaltakquise, Gewinnspiele, Rabattaktionen, auch von Diensten, die der Inhaber nutzt. Produkt- und Kontomitteilungen solcher Dienste sind Tools & Dienste.“
  - `BESCHREIBUNG[("business","Tools & Dienste")]` wird zu „Mitteilungen von Software und Diensten, die die Firma nutzt (Produkt, Konto, Abrechnung).“
  - Aufmerksamkeit bei Einigkeit: `s.aufmerksamkeit or p.aufmerksamkeit`.
  - `werbung_sicher`: Fach == „Werbung“ und Quelle `pruefer` (einig) **oder** Quelle `regel`/`katalog` mit Fach Werbung.
  - Bei „Zum Nachsehen“: `aufmerksamkeit = True`.
  - Feste Muster (`nach_muster`): `aufmerksamkeit = True`, das Altern regelt Task 4.

- [ ] **Step 4: Bestehende und neue Tests in `test_post_einordnung.py`, `test_post_einordnung_db.py`, `test_post_abholen.py` PASS.**

- [ ] **Step 5: Commit** `feat(post): Einordnung nach Postfach-Art, mit Aufmerksamkeit`

---

### Task 3: Werbung ohne Modell (Absender-Regeln, Schutz)

**Files:**
- Modify: `sales-mcp/post_einordnung.py` (`nach_nutzerregel`, `einordnen`)
- Create: `sales-mcp/post_werbung.py`
- Test: `sales-mcp/tests/test_post_werbung.py`

**Interfaces:**
- Consumes: `post_regeln.art` (Task 1), `Einordnung.werbung_sicher` (Task 2)
- Produces:
  - `post_struktur.BLEIBT_IMMER: frozenset[str]` (Werte siehe Global Constraints; Task 4 nutzt es)
  - `post_werbung.BLEIBT_BETREFF: str` (Regex): `(?i)(rechnung|invoice|beleg|quittung|bestell|order|versand|lieferung|vertrag|kündig|mahnung|zahlung|payment|konto|passwort|sicherheit)`
  - `post_werbung.geschuetzt(besitzer: str, von: str) -> bool`: Es gibt eine Regel `art='nie_werbung'` für diese Absenderadresse und diesen Besitzer.
  - `post_werbung.regel_vorschlagen(besitzer: str, von: str) -> bool`: Legt eine Regel `art='einordnen', feld='von', fach='Werbung'` an, wenn alle drei Bedingungen gelten:
    - Der Absender hat ≥ 3 Mails mit `werbung_sicher`.
    - Er hat 0 Mails in einem Fach aus `BLEIBT_IMMER` oder `UNKLAR`.
    - Er ist nicht `geschuetzt`.

    Rückgabe: Regel angelegt.
  - `post_werbung.schutz_setzen(besitzer: str, von: str) -> None`: Regel `art='nie_werbung'` anlegen. Bestehende Werbe-Regeln desselben Musters und Besitzers löschen.

- [ ] **Step 1: Write failing tests**

```python
def test_werbe_regel_ohne_modellaufruf(): ...          # Regel fach Werbung -> aufrufe == 0, werbung_sicher True, sensibel False
def test_werbe_regel_greift_nicht_bei_rechnungsbetreff(): ...  # Betreff "Ihre Rechnung 4711" -> Fake-Modell wird aufgerufen
def test_nie_werbung_regel_wird_nicht_als_einordnung_gelesen(): ... # art='nie_werbung' setzt kein Fach
def test_modell_werbung_bei_geschuetztem_absender_ist_nicht_sicher(): ...  # einig Werbung, aber geschuetzt -> werbung_sicher False
def test_regel_vorschlag_erst_ab_drei_sicheren_und_ohne_bleibt_immer():
    ...  # 2 sichere -> False; 3 -> True; zusaetzlich eine Rechnung vom Absender -> False
def test_schutz_loescht_werbe_regel(): ...
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - `nach_nutzerregel` liest nur `art='einordnen'`.
  - Gibt eine Regel Fach Werbung zurück und trifft `BLEIBT_BETREFF` den Betreff, gilt die Regel als nicht getroffen. Die Suche geht dann weiter (nächste Regel, Katalog, Modell).
  - `einordnen()` bei einer Regel mit Fach Werbung: kein Modellaufruf, Ergebnis `sensibel=False, aufmerksamkeit=False, werbung_sicher=True, aufrufe=0`.
  - `regel_vorschlagen` wird in `post_abholen._ergebnis_speichern` aufgerufen, wenn das neue Ergebnis `werbung_sicher` ist.
  - Muster der Regel: `^` + `re.escape(adresse)` + `$` auf `von`. Wie `ui_post.absender_muster`, dieselbe Funktion wiederverwenden.

- [ ] **Step 4: PASS** (plus `test_post_einordnung.py`).

- [ ] **Step 5: Commit** `feat(post): Werbung per Absender-Regel ohne Modell, Schutzregel`

---

### Task 4: Ziel je Mail

**Files:**
- Create: `sales-mcp/post_ziel.py`
- Test: `sales-mcp/tests/test_post_ziel.py`

**Interfaces:**
- Consumes: Spalten aus Task 1, `post_werbung.geschuetzt` (Task 3)
- Produces:
  - `post_ziel.ALTBESTAND_AB: date`: aus Env `POST_AUFRAEUMEN_AB` (ISO-Datum). Mails mit `datum` davor sind Altbestand. Fehlt der Wert: `date.max` (alles Altbestand; sicherer Default, nichts geht direkt nach To-Review).
  - `post_ziel.ziel_fuer(m: dict, jetzt: datetime, freigegebene_jahre: set[int], ist_kontakt: bool, geschuetzt: bool) -> str`

`m` hat die Schlüssel `fach, aufmerksamkeit, werbung_sicher, datum, anhaenge, begruendung, ziel, ziel_manuell`. Die Entscheidung läuft in dieser Reihenfolge; der erste Treffer gewinnt:

1. `ziel_manuell` → `m["ziel"]`
2. Fach `UNKLAR` → `posteingang`
3. Werbung (`fach == "Werbung"`):
   - nicht `werbung_sicher`, oder `ist_kontakt`, oder `geschuetzt`, oder ein Anhang, der kein Bild ist (Endung nicht `.png .jpg .jpeg .gif .webp`) → `zur_info`
   - Mail-Datum ab `ALTBESTAND_AB` (neue Mail) → `to_review`
   - `m["ziel"] == "loeschen"` (war schon vor der Freigabe vorgesehen) → `loeschen`
   - Jahr nicht in `freigegebene_jahre` → `loeschen` (wartet auf die Freigabe)
   - sonst → `to_review` (erst **nach** der Freigabe ihres Jahres als Werbung erkannt, Spec §6.1)
4. Login-Code (`begruendung` beginnt mit `sensibel-muster:betreff:0`) → `posteingang`, wenn `jetzt - datum < 1 Tag`, sonst `zur_info`
5. `aufmerksamkeit`:
   - Altbestand und älter als 90 Tage → `zur_info`
   - sonst → `posteingang`
6. sonst → `zur_info`

Gelöscht wird in Task 5 nur, was `ziel == 'loeschen'` hat **und** dessen Jahr für den Besitzer freigegeben ist.

- [ ] **Step 1: Failing tests** (Parametrisierung, `jetzt` fest auf `2026-11-06T12:00+01:00`, `ALTBESTAND_AB=2026-11-10` per monkeypatch):

| Fall | erwartet |
|---|---|
| UNKLAR, sonst beliebig | posteingang |
| Werbung sicher, 2025, Jahr nicht freigegeben | loeschen |
| Werbung sicher, 2025, Jahr freigegeben, ziel bisher null | to_review |
| Werbung sicher, 2025, Jahr freigegeben, ziel bisher loeschen | loeschen |
| Werbung sicher, 2025, ziel bisher loeschen, geschuetzt | zur_info |
| Werbung sicher, Datum 2026-11-12 (nach ALTBESTAND_AB) | to_review |
| Werbung sicher, ist_kontakt | zur_info |
| Werbung sicher, Anhang `angebot.pdf` | zur_info |
| Werbung sicher, Anhang `bild.png` | loeschen |
| Werbung nicht sicher | zur_info |
| Werbung sicher, geschuetzt | zur_info |
| Rechnungen, aufmerksamkeit, 2026-10-20 | posteingang |
| Rechnungen, aufmerksamkeit, 2026-05-01 (Altbestand > 90 Tage) | zur_info |
| Rechnungen, nicht aufmerksamkeit | zur_info |
| Login-Code vor 2 Stunden | posteingang |
| Login-Code vor 2 Tagen | zur_info |
| ziel_manuell posteingang, Fach Werbung | posteingang |

- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS.**

- [ ] **Step 5: Commit** `feat(post): Ziel je Mail (Posteingang, Zur Info, To-Review, Loeschen)`

---

### Task 5: IMAP-Befehle und Ordnen

**Files:**
- Create: `sales-mcp/post_imap.py`
- Create: `sales-mcp/post_ordnen.py`
- Modify: `sales-mcp/postfach.py:640-667` (`verschieben` nutzt `post_imap.verschieben`, kein nacktes `expunge()`)
- Modify: `sales-mcp/post_abholen.py:eine_runde` (nach dem Einordnen `post_ordnen.ordnen(...)`, wenn `POST_ORDNEN != "aus"`)
- Test: `sales-mcp/tests/test_post_imap.py`, `sales-mcp/tests/test_post_ordnen.py`

**Interfaces:**
- Consumes: `post_ziel.ziel_fuer` (Task 4), Spalten aus Task 1, `post_konten.verbinden`
- Produces:
  - `post_imap.NichtUnterstuetzt(Exception)`
  - `post_imap.Fehlt(Exception)`: die UID ist im Quellordner nicht (mehr) vorhanden
  - `post_imap.ordner_sicherstellen(kasten, name: str) -> str`: legt den Ordner an, falls nötig; gibt den IMAP-Namen zurück (über `postfach._imap_name`)
  - `post_imap.verschieben(kasten, quelle: str, uid: int, ziel: str) -> int | None`: neue UID aus `COPYUID`, sonst `None`
    - Nutzt `UID MOVE`, wenn `MOVE` in den Fähigkeiten steht.
    - Sonst `UID COPY` + `UID STORE +FLAGS (\Deleted)` + `UID EXPUNGE <uid>`, wenn `UIDPLUS` vorhanden.
    - Sonst `NichtUnterstuetzt`.
  - `post_imap.loeschen(kasten, quelle: str, uid: int, anbieter: str) -> None`
    - gmx/namecheap: `UID STORE +FLAGS (\Deleted)` + `UID EXPUNGE <uid>`
    - gmail: in den Ordner mit `\Trash` verschieben (per `postfach._ordner_liste`), dort `UID STORE \Deleted` + `UID EXPUNGE <neue_uid>`; ohne neue UID → `NichtUnterstuetzt`
  - `post_ordnen.MODUS: str` aus Env `POST_ORDNEN` (`aus` | `verschieben` | `voll`, Default `aus`). `verschieben` = alles außer Löschen.
  - `post_ordnen.ordnen(je_konto: int = 50) -> dict`:
    - je aktivem Konto mit `ordnen_aus is null`: die Zeilen des Besitzers, deren berechnetes Ziel nicht zum Ordner passt; höchstens `je_konto`;
    - Bilanz: `{"verschoben": n, "geloescht": n, "fehlt": n, "fehler": n, "konten_aus": [kennung]}`.

**Zuordnung Ziel → Ordner:** `posteingang`→`INBOX`, `zur_info`→`Zur Info`, `to_review`→`To-Review`. `loeschen` wird nur gelöscht, wenn `MODUS == "voll"` und es eine Freigabe für (Besitzer, Jahr) gibt.

**To-Review:** Mails mit `ordner='To-Review'` und `ordner_am < now() - 30 Tage` werden gelöscht, nur bei `MODUS == "voll"`.

**Nach jedem Schritt:**
- `ordner`, `ordner_uid` (neue UID, sonst `null`), `ordner_stand='ok'`, `ordner_am=now()`, `ziel` schreiben;
- beim Löschen: `status='geloescht'`, `geloescht_am=now()`, `text=null`, `auszug=null`;
- Logzeile: Kennung + Aktion, ohne Betreff.

**UID im Ordner:**
- Quelle ist `ordner_uid`, im INBOX `imap_uid`.
- Ist `ordner_uid` null und `ordner != 'INBOX'`: per `UID SEARCH HEADER Message-ID <id>` im Ordner suchen (nicht bei `message_id_ersatz`).
- Wird nichts gefunden: `Fehlt`.

- [ ] **Step 1: Failing tests.** Grundlage ist ein `FakeKasten` mit `capabilities`, Ordnern als `dict[str, dict[int, bytes]]` und Aufrufprotokoll.
  - `test_move_wenn_vorhanden()`: Protokoll enthält genau `("uid", "MOVE", "7", ...)`, kein `expunge`.
  - `test_copy_store_uid_expunge_ohne_move()`: `UID EXPUNGE 7`, nie `EXPUNGE` ohne UID.
  - `test_ohne_move_und_uidplus_nicht_unterstuetzt()`
  - `test_gmail_loeschen_ueber_papierkorb_und_uid_expunge()`
  - `test_postfach_verschieben_ruft_kein_nacktes_expunge()`: Regression für `postfach.verschieben`.
  - `test_ordnen_verschiebt_zur_info_und_merkt_ordner()`: DB-Zeile mit `fach='Newsletter & Branche'`, `aufmerksamkeit=False`; danach `ordner='Zur Info'`, `ordner_stand='ok'`.
  - `test_ordnen_fehlende_uid_markiert_und_laeuft_weiter()` (Review Focus 1): zwei Zeilen, erste UID fehlt im Fake. Danach ist die erste `fehlt`, die zweite `ok`.
  - `test_ordnen_ohne_faehigkeit_setzt_ordnen_aus_und_andere_konten_laufen()` (Review Focus 5)
  - `test_modus_verschieben_loescht_nie()`: freigegebene Werbung bleibt.
  - `test_modus_aus_tut_nichts()`: `eine_runde` ruft `ordnen` nicht.
  - `test_to_review_nach_30_tagen_geloescht_nur_voll()`
  - `test_loeschen_leert_text_behaelt_kopf()`

- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS** (+ `test_post_abholen.py`, `test_postfach*.py`).

- [ ] **Step 5: Commit** `feat(post): Postfach an Ziel angleichen (MOVE/UID EXPUNGE, Schalter POST_ORDNEN)`

---

### Task 6: Ursprüngliche Adresse (Bluebatch)

**Files:**
- Modify: `sales-mcp/post_abholen.py:_mail_zerlegen` und `_speichern` (Spalte `urspruengliche_adresse`)
- Modify: `sales-mcp/post_einordnung.py:einordnen` (Business-Adressen)
- Create: `sales-mcp/post_herkunft.py`
- Test: `sales-mcp/tests/test_post_herkunft.py`

**Interfaces:**
- Produces:
  - `post_herkunft.KOPFZEILEN = ("X-Forwarded-To", "X-Original-To", "Delivered-To", "X-Forwarded-For")`
  - `post_herkunft.urspruenglich(nachricht, konto_adresse: str) -> str | None`: die erste Adresse aus diesen Kopfzeilen (in dieser Reihenfolge), die nicht `konto_adresse` ist, kleingeschrieben.
  - `post_herkunft.BUSINESS_ADRESSEN: tuple[str, ...]` aus Env `POST_BUSINESS_ADRESSEN` (Komma-Liste; Eintrag mit `@` = genaue Adresse, ohne `@` = Domain-Endung).
  - `post_herkunft.ist_business(adresse: str | None) -> bool`
  - `post_herkunft.nachtragen(zeile_konto: dict, kasten, grenze: int = 500) -> int`: Für Mails des Kontos ohne `urspruengliche_adresse` werden per `UID FETCH <uid> (BODY.PEEK[HEADER.FIELDS (...)])` nur die Kopfzeilen nachgeladen und gespeichert. Rückgabe: Zahl der Nachträge.
  - CLI: `python -m post_herkunft nachtragen <kennung>` und `python -m post_herkunft stichprobe <kennung> [n=30]`.
    - `stichprobe` gibt **nur** eine Häufigkeitstabelle aus: Kopfzeilenname → Domain der Adresse. Keine Betreffe, keine vollen Adressen außer den eigenen Konto-Domains.

- [ ] **Step 1: Failing tests**
  - `test_x_forwarded_to_gewinnt_vor_delivered_to()`
  - `test_eigene_kontoadresse_zaehlt_nicht()`
  - `test_ohne_kopfzeilen_none()`
  - `test_business_adresse_zieht_bereich_business()`: `einordnen` mit Mail `urspruengliche_adresse` in `BUSINESS_ADRESSEN` und Modell-Ergebnis privat/Rechnungen → `bereich=='business'`. Das Fach bleibt, wenn es in business existiert, sonst über `bereich_fuer`.
  - `test_nachtragen_holt_nur_kopfzeilen()`: Fake-Protokoll enthält `BODY.PEEK[HEADER.FIELDS`, nie `RFC822`.

- [ ] **Step 2–4: FAIL → Implement → PASS.**

- [ ] **Step 5: Commit** `feat(post): urspruengliche Adresse weitergeleiteter Mails, Business-Adressen`

---

### Task 7: Löschfreigabe je Jahr

**Files:**
- Create: `sales-mcp/post_freigabe.py`
- Test: `sales-mcp/tests/test_post_freigabe.py`

**Interfaces:**
- Consumes: `post_ziel.ziel_fuer`, `post_werbung.schutz_setzen`, `post_loeschfreigaben`
- Produces:
  - `post_freigabe.vorschau(besitzer: str, jahr: int) -> list[dict]`
    - Rückgabe: `[{"absender": str, "anzahl": int, "beispiele": [str, ...]}]`.
    - Grundlage: nur Mails aus Konten mit `post_konten.besitzer == besitzer`, `status='eingeordnet'`, `ziel='loeschen'`, `extract(year from datum)=jahr`.
    - Gruppiert nach Absenderadresse, absteigend nach Anzahl.
    - `beispiele`: höchstens 3 Betreffe, je höchstens 80 Zeichen.
  - `post_freigabe.freigeben(besitzer: str, jahr: int, gezeigt: list[str], ausgenommen: list[str]) -> int`
    - legt die Zeile in `post_loeschfreigaben` an; ein zweites Mal ist ein Fehler `ValueError("schon freigegeben")`;
    - ruft für jeden ausgenommenen Absender `post_werbung.schutz_setzen` auf;
    - setzt deren Mails auf `ziel='zur_info'`;
    - Mails mit `ziel='loeschen'`, deren Absender **nicht** in `gezeigt` steht, bekommen `ziel='to_review'`. Sie kamen nach dem Laden der Vorschau dazu; Felix hat sie nicht gesehen.
    - Rückgabe: Zahl der Mails, die jetzt gelöscht werden dürfen.
  - `post_freigabe.jahre(besitzer: str) -> list[dict]`: `[{"jahr", "eingeordnet", "offen", "zu_loeschen", "freigegeben_am"}]`, neuestes Jahr zuerst.

- [ ] **Step 1: Failing tests**
  - `test_vorschau_gruppiert_absender_mit_hoechstens_drei_beispielen()`
  - `test_vorschau_und_freigabe_nur_eigene_konten()` (Review Focus 4): Konto von „ivan“ mit Werbung 2025. `vorschau("felix", 2025)` enthält sie nicht. `freigeben("felix", 2025, [])` ändert sie nicht.
  - `test_ausgenommener_absender_wird_geschuetzt_und_bleibt()`
  - `test_zweite_freigabe_desselben_jahres_wirft()`
  - `test_nicht_gezeigter_absender_geht_nach_to_review_statt_loeschen()`
  - `test_nach_freigabe_erkannte_werbung_geht_nach_to_review()` (Review Focus 2): freigeben 2025, danach eine neue Werbe-Einordnung aus 2025. `ziel_fuer` mit `freigegebene_jahre={2025}` ergibt `to_review`.

- [ ] **Step 2–4: FAIL → Implement → PASS.**

- [ ] **Step 5: Commit** `feat(post): Loeschfreigabe je Jahr`

---

### Task 8: Einordnungs-Reihenfolge und Stichprobe

**Files:**
- Modify: `sales-mcp/post_abholen.py:einordnen_offene` (Reihenfolge)
- Modify: `sales-mcp/post_neu_einordnen.py` (`_altbestand`: `einordnung_version < 3`; `vorschau(grenze, alle=False, je_konto: int | None = None)`)
- Modify: `deploy/post-neu-einordnen.sh` (`vorschau --je-konto N` durchreichen)
- Test: `sales-mcp/tests/test_post_abholen.py`, `sales-mcp/tests/test_post_neu_einordnen.py` (ergänzen)

**Interfaces:**
- Produces:
  - `einordnen_offene` sortiert `order by extract(year from m.datum) desc nulls last, m.datum desc, m.imap_uid desc`. Das neueste Jahr kommt zuerst, über alle Konten gemeinsam.
  - `vorschau(..., je_konto=N)` nimmt je Konto die N neuesten Altbestand-Mails.
  - `bericht()` enthält zusätzlich `"unklar_anteil": {kennung: float}` aus den Vorschauen.

- [ ] **Step 1: Failing tests**
  - `test_einordnen_neuestes_jahr_zuerst_ueber_alle_konten()`
  - `test_vorschau_je_konto_n()`
  - `test_bericht_nennt_unklar_anteil_je_konto()`
  - `test_v2_einordnungen_zaehlen_als_altbestand()`

- [ ] **Step 2–4: FAIL → Implement → PASS.**

- [ ] **Step 5: Commit** `feat(post): neuestes Jahr zuerst, Stichprobe je Konto`

---

### Task 9: Mail-Reiter: Aufmerksamkeit, Zur Info, To-Review, Aufräumen

**Files:**
- Modify: `sales-mcp/ui_post.py`
- Modify: `sales-mcp/post_struktur.py:mails_suchen` (Filter `ziel: str = ""`)
- Test: `sales-mcp/tests/test_post_ui_aufraeumen.py`

**Interfaces:**
- Consumes: `post_freigabe.vorschau/freigeben/jahre`, `post_ordnen.MODUS`, `post_abholen.modellaufrufe_heute`, `post_werbung.schutz_setzen`
- Produces (Routen):
  - `GET /post?ansicht=aufmerksamkeit|zur_info|to_review` (Default `aufmerksamkeit`). Reiterleiste oben.
    - `zur_info` zeigt die bestehende Fächerleiste.
    - `to_review` zeigt je Mail „wird gelöscht am <ordner_am + 30 Tage>“.
  - `GET /post/aufraeumen`
    - Tabelle aus `jahre(besitzer)`;
    - je Konto `ordnen_aus` (falls gesetzt) und der Modus;
    - Modellaufrufe heute / 500;
    - Resttage = offene Mails × 2 / 500, aufgerundet.
  - `GET /post/aufraeumen/{jahr}`: Vorschau. **Ein** Formular:
    - je Absender ein verstecktes Feld `absender=<adresse>` und eine Checkbox `loeschen=<adresse>`, **vorgewählt** (Spec: alle vorgewählt, Felix nimmt nur heraus);
    - darunter der Knopf „Jahr <jahr> löschen freigeben“.
  - `POST /post/aufraeumen/{jahr}`:
    - CSRF, Rolle `freigeben`;
    - `gezeigt = getlist("absender")`, `ausgenommen = gezeigt − getlist("loeschen")`;
    - `freigeben(b.name, jahr, gezeigt, ausgenommen)`;
    - Umleitung auf `/post/aufraeumen`.
  - `POST /post/mail/{mail_id}/ziel`:
    - Feld `ziel` in (`posteingang`, `zur_info`); setzt `ziel`, `ziel_manuell=true`.
    - Kam die Mail aus `to_review`: zusätzlich `schutz_setzen`.
    - Nur wer korrigieren darf (`darf_korrigieren`).

- [ ] **Step 1: Failing tests** (TestClient-Muster aus `test_post_ui_v2.py`, mit angemeldetem Benutzer):
  - `test_standardansicht_ist_aufmerksamkeit()`
  - `test_zur_info_reiter_zeigt_faecher()`
  - `test_to_review_nennt_loeschdatum()`
  - `test_aufraeumen_zeigt_jahre_und_resttage()`
  - `test_vorschau_formular_ein_knopf_und_haken_je_absender()`: alle Checkboxen `checked`
  - `test_abgewaehlter_absender_wird_ausgenommen()`
  - `test_freigabe_post_ohne_csrf_403_und_ohne_wirkung()`
  - `test_freigabe_rolle_lesen_403()`
  - `test_aus_to_review_holen_schuetzt_absender()`
  - `test_fremde_freigabe_nicht_moeglich()`: Benutzer „ivan“ sieht in `/post/aufraeumen` nur eigene Konten.

- [ ] **Step 2–4: FAIL → Implement → PASS** (+ `test_ui_post.py`, `test_post_ui_v2.py`).

- [ ] **Step 5: Commit** `feat(post): Reiter Aufmerksamkeit, Zur Info, To-Review und Aufraeumen`

---

### Task 10: Runbook und Rollout-Vorbereitung

**Files:**
- Modify: `docs/03_RUNBOOK.md` (Abschnitt „Post aufräumen“)
- Modify: `docker-compose.yml` (sales-post: `POST_ORDNEN`, `POST_AUFRAEUMEN_AB`, `POST_BUSINESS_ADRESSEN` durchreichen, Default leer bzw. `aus`)
- Modify: `deploy/laden-parameter`-Prüfungen nur, falls `test_laden_parameter.py` neue Variablen verlangt

**Inhalt Runbook** (Schritte, jeder mit Prüfbefehl). Die Schritte nach dem Deploy laufen nur mit Felix' OK:
1. Vault-Claim.
2. SQL per `git show` einspielen.
3. `update.sh`.
4. `update post_konten set standard_bereich='privat' where kennung='gmx-felix'`.
5. `python -m post_herkunft stichprobe gmail-felix404`. Das Ergebnis entscheidet über `POST_BUSINESS_ADRESSEN`; findet sich nichts, Felix fragen.
6. `post_herkunft nachtragen gmail-felix404`.
7. Stichprobe: `deploy/post-neu-einordnen.sh vorschau --je-konto 25`, dann `bericht`.
   - **Tor:** `unklar_anteil` je Konto < 0,10.
   - Sonst Prompt nachschärfen (zurück zu Task 2), nicht weiter.
8. `anwenden` mit Felix' OK.
9. `POST_AUFRAEUMEN_AB=<Datum des Einschaltens>` und `POST_ORDNEN=verschieben`.
   - Eine Runde beobachten: Zahlen in `/post/aufraeumen`, Stichprobe im Handy-Postfach.
10. Mit Felix' OK `POST_ORDNEN=voll`.
11. Freigabe der Jahre durch Felix in der UI, neuestes zuerst.

- [ ] **Step 1:** Volle Post-Testmenge im Container:

```
test_post_*.py test_ui_post.py test_postfach*.py test_testsperre.py test_laden_parameter.py
```

Vergleich der FAILED-Listen alt/neu per `comm`. Neu rot = 0.

- [ ] **Step 2: Commit** `docs(runbook): Post aufraeumen einschalten`
