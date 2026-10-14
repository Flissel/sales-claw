# Kalender pflegen (Block B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/kalender` wird ein Kalender wie bei Google (Tag/Woche/Monat/Liste, Ziehen und Größe ändern). Er zeigt Kunden-, eigene, Kollegen- und Handy-Termine. Kunden- und eigene Termine lassen sich anlegen, ändern und löschen bzw. absagen. Jede Änderung an einem Kundentermin erzeugt einen Entwurf an den Kunden zur Freigabe.

**Architecture:**
- **Backend:**
  - Eigene Termine liegen in der neuen Tabelle `eigene_termine` (Modul `termine_eigen.py`).
  - Kundentermine bleiben Aktivitäten am Kontakt. Neu sind `termin_aendern` und ein Benachrichtigungs-Entwurf in `server.py`.
  - Ein Sammler `kalender_ereignisse(von, bis)` vereint alle vier Arten und prüft Konflikte.
- **sales-ui:** Das neue Modul `ui_kalender.py` liefert eine JSON-Schnittstelle und die Seite `/kalender` mit eigenem Bundle aus `kalender/` (Vite + FullCalendar, MIT).
- **Bundle:** Es wird eingecheckt wie der Editor, liegt aber in einem eigenen Ordner `static/kalender/`.

**Tech Stack:** Python 3.12, psycopg 3, Starlette, PostgreSQL (Supabase, Schema je Laden), CalDAV (Namecheap), TypeScript + Vite 5 + FullCalendar 6 (`@fullcalendar/core`, `daygrid`, `timegrid`, `list`, `interaction`), vitest.

**Spec:** `docs/superpowers/specs/2026-10-14-kalender-pflegen-design.md`

## Global Constraints

**Repo und Git**
- Repo SC = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`.
  - Vor jedem Commit `git -C <SC> rev-parse --show-toplevel` und `git -C <SC> branch --show-current` prüfen.
- Git nur über PowerShell. Conventional Commits auf Deutsch, letzter Absatz `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Nur eigene Dateien einzeln stagen. Nie `.superpowers/`, nie stash, force oder `--no-verify`.

**Tests**
- **sales-mcp:** aus `<SC>/sales-mcp`, Test-Postgres :55432 (der Controller startet sie):
  `$env:SALES_DB_URL='postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`
  - Schema-Änderungen in der Test-DB: die neuen DDL-Zeilen direkt per `& "C:/Program Files/PostgreSQL/16/bin/psql.exe" -h 127.0.0.1 -p 55432 -U postgres -c "<sql>"` auf `sales_test` anwenden. Die volle `provision.sql` läuft lokal nicht (Extension `vector` fehlt).
- **Kalender-Bundle:** `cd <SC>/kalender; npm install; npx vitest run; npx tsc --noEmit; npm run build`. Nur `cd kalender && npx tsc --noEmit` zählt als Typprüfung.
- Die Baseline von 53 vorbestehenden Fehlern (Block A) darf nicht wachsen.

**Verbote:** kein Deploy, keine echte DB, kein Neustart (Task 7, Controller nach Freigabe).

**Wortlaute (exakt)**
- „nicht im Handy-Kalender“
- „Handy-Termine gerade nicht abrufbar“
- „inzwischen geändert – neu laden“
- „kein Kanal zum Kunden – bitte selbst Bescheid geben“
- „Entwurf an Kunde angelegt – in Freigaben“
- „unvollständig geprüft“

**Werte**
- Eigene Termine: Dauer 5–1440 Minuten, `uid` = `<uuid4>@sales-claw`.
- Kundentermine: Dauer weiter `TERMIN_DAUER_MIN..TERMIN_DAUER_MAX` (15–480).
- Woche als Standard, sichtbar 07:00–20:00, Arbeitszeit 08:00–18:00 (Mo–Fr).
- Farben: Kunde = Markenfarbe der Oberfläche, eigen `#2563eb`, Kollege `#4d7c5a`, Handy `#9ca3af`.

## Rulings vor Beginn (gegen die Spec abgewogen)

- **R1: Kein Überschreiben in CalDAV.** `kalender.eintragen` legt nur an (`If-None-Match: *`). Eigene Termine werden darum mit `kalender.loeschen(uid)` und anschließendem `kalender.eintragen(uid, neu)` geändert, die `uid` bleibt dieselbe.
- **R2: Keine Kalender-Absage.** `METHOD:CANCEL` gibt es in `kalender.py` nicht. Eine Kundenabsage erzeugt darum einen Text-Entwurf (E-Mail, sonst WhatsApp). Die Spec erlaubt diesen Rückfall.
- **R3: Einladung bei Verschiebung fortschreiben.** Gibt es zum alten Termin eine Einladung (`einladung_entworfen` mit gleichem Datum und gleicher Uhrzeit), wird sie mit `termin_einladen(..., uid=<einladungs-uid>, folge=<alt+1>)` fortgeschrieben. So aktualisiert sich der Termin im Kundenkalender, statt doppelt zu stehen. Sonst entsteht eine neue Einladung (`folge=0`).
- **R4: Rechte der Rolle „kalender“.** Für sie gilt die bestehende Schreibsperre der Anmeldewache (nur GET). `"/static/kalender"` kommt in `_KALENDER_ROLLE_PFADE`, damit sie das Bundle laden darf.
- **R5: Seitenaufbau.** Das Monatsgitter wird durch den Kalender ersetzt. Die übrigen Abschnitte der Seite bleiben unter dem Kalender, server-gerendert: „Ohne festes Datum“, Wiedervorlagen, Kalenderquellen, Vergangen, Abgesagt.

## Review Focus

1. **Zeitzone am Wochenwechsel und bei der Sommerzeit-Umstellung** (25.10.2026). Erwartet: Ein Termin 14:00 Europe/Berlin erscheint und speichert als 14:00, auch nach dem Ziehen über die Umstellung. Test in Task 3 und Task 5.
2. **Kundentermin auf einen Platz ziehen, an dem ein Handy-Termin liegt.** Erwartet: Erst kommt die Konfliktwarnung, dann bei „trotzdem“ das Bestätigungsfenster für den Kunden-Entwurf. Kein doppelter Entwurf. Test in Task 4.
3. **Doppelklick bzw. doppelter Absenden-Klick im Anlegen-Fenster.** Erwartet: genau ein Termin (der Knopf ist während der Anfrage gesperrt). Test in Task 5.
4. **Titel mit Sonderzeichen** („Mo & Co; Treffen, „X““). Erwartet: unverändert in der Liste, im ICS korrekt maskiert, im Handy-Kalender lesbar. Test in Task 1.
5. **Lead ohne Namen bzw. gelöschter Lead mit altem Termin.** Erwartet: Der Termin wird mit „(ohne Kontakt)“ angezeigt und ist nicht bearbeitbar. Kein Absturz. Test in Task 3.

---

### Task 1: Eigene Termine (Tabelle, Modul, CalDAV)

**Files:**
- Modify: `db/provision.sql` (in der Schema-Schleife nach `kalender_quellen`; Grants nach dem Muster Z.~456-466)
- Create: `sales-mcp/termine_eigen.py`
- Test: `sales-mcp/tests/test_termine_eigen.py`

**Interfaces:**
- Produces (`termine_eigen`, Rückgaben sind dicts, nie Exceptions bei Nutzerfehlern):
  - `anlegen(titel: str, beginn: datetime, dauer_minuten: int, ort: str = "", notiz: str = "") -> dict`, mit `{"termin": {...}}` oder `{"fehler": str}`
  - `aendern(uid: str, geaendert_am: str, **felder) -> dict`; erlaubte Felder `titel, beginn, dauer_minuten, ort, notiz`; Rückgabe `{"termin": {...}}`, `{"fehler": ...}` oder `{"veraltet": True}`
  - `loeschen(uid: str) -> dict`
  - `im_zeitraum(von: datetime, bis: datetime) -> list[dict]`
  - Termin-dict: `{uid, titel, beginn (aware datetime), dauer_minuten, ort, notiz, kalender_stand, geaendert_am (isoformat str)}`
  - `beginn` ist timezone-aware (Europe/Berlin). Gespeichert wird `timestamptz`.

- [ ] **Step 1: Failing Tests** in `tests/test_termine_eigen.py`.
  - Fixture-Muster wie `tests/test_termin.py`: `os.environ["SALES_DB_SCHEMA"]="sales_test"`, `schema_wache`, ein autouse-Truncate von `sales_test.eigene_termine`, und der CalDAV-Stub `_Stub`/`STUB`/`STUB_URL` aus `test_termin.py` (kopieren oder importieren) mit dem Fixture `kalender_konfiguriert`.
```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
B = ZoneInfo("Europe/Berlin")
def _morgen(h=10):
    d = datetime.now(B) + timedelta(days=1)
    return d.replace(hour=h, minute=0, second=0, microsecond=0)

def test_anlegen_speichert_und_traegt_ein(kalender_konfiguriert):
    r = termine_eigen.anlegen("Steuerberater", _morgen(), 45, ort="Büro")
    t = r["termin"]
    assert t["uid"].endswith("@sales-claw") and t["dauer_minuten"] == 45 and t["kalender_stand"] == "eingetragen"
    assert STUB.aufrufe[-1]["pfad"].endswith(t["uid"] + ".ics")

def test_caldav_aus_bleibt_gespeichert():
    # ohne CALDAV_URL: nicht konfiguriert -> gespeichert, kalender_stand 'nicht_konfiguriert'
    t = termine_eigen.anlegen("Blocker", _morgen(), 30)["termin"]
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23))[0]["uid"] == t["uid"]

def test_caldav_fehler_steht_im_stand(kalender_konfiguriert):
    STUB.status = 500
    t = termine_eigen.anlegen("X", _morgen(), 30)["termin"]
    assert t["kalender_stand"].startswith("fehlgeschlagen")

def test_aendern_loescht_und_traegt_neu_ein_gleiche_uid(kalender_konfiguriert):
    t = termine_eigen.anlegen("A", _morgen(9), 30)["termin"]
    r = termine_eigen.aendern(t["uid"], t["geaendert_am"], beginn=_morgen(11), titel="B")
    assert r["termin"]["uid"] == t["uid"] and r["termin"]["titel"] == "B"
    methoden = [a.get("methode", "PUT") for a in STUB.aufrufe]
    assert "DELETE" in methoden and methoden[-1] == "PUT"

def test_aendern_veraltet():
    t = termine_eigen.anlegen("A", _morgen(), 30)["termin"]
    termine_eigen.aendern(t["uid"], t["geaendert_am"], titel="B")
    assert termine_eigen.aendern(t["uid"], t["geaendert_am"], titel="C") == {"veraltet": True}

@pytest.mark.parametrize("dauer", [4, 1441])
def test_dauer_grenzen(dauer):
    assert "fehler" in termine_eigen.anlegen("A", _morgen(), dauer)

def test_vergangenheit_abgelehnt():
    assert "fehler" in termine_eigen.anlegen("A", datetime.now(B) - timedelta(hours=1), 30)

def test_sonderzeichen_bleiben(kalender_konfiguriert):          # Review Focus 4
    titel = "Mo & Co; Treffen, „X“"
    t = termine_eigen.anlegen(titel, _morgen(), 30)["termin"]
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23))[0]["titel"] == titel
    assert "Mo & Co\\; Treffen\\, „X“" in STUB.aufrufe[-1]["rumpf"]

def test_loeschen(kalender_konfiguriert):
    t = termine_eigen.anlegen("A", _morgen(), 30)["termin"]
    assert termine_eigen.loeschen(t["uid"]).get("geloescht") is True
    assert termine_eigen.im_zeitraum(_morgen(0), _morgen(23)) == []
```
  - Hat der Stub keine DELETE-Behandlung, wird in der Testdatei ein `do_DELETE` ergänzt, das `{"methode": "DELETE", "pfad": ...}` aufzeichnet und 204 antwortet.
- [ ] **Step 2: Schema in der Test-DB anlegen und Tests rot sehen.**
```sql
create table if not exists sales_test.eigene_termine (
  uid text primary key, titel text not null check (titel <> ''),
  beginn timestamptz not null,
  dauer_minuten int not null check (dauer_minuten between 5 and 1440),
  ort text, notiz text, teilnehmer text[] not null default '{}',
  kalender_stand text,
  erstellt_am timestamptz not null default now(),
  geaendert_am timestamptz not null default now());
grant select, insert, update, delete on sales_test.eigene_termine to sales_app;
```
- [ ] **Step 3: `provision.sql`.**
  - Dieselbe Tabelle kommt in die Schema-Schleife (`execute format($ddl$ create table if not exists %I.eigene_termine (...) $ddl$, s);`), dazu ein Index `eigene_termine_beginn_idx (beginn)`.
  - Nach den Grants: `grant select, insert, update, delete on sales.eigene_termine to sales_app;`.
  - Grants für weitere Läden (`sales_<name>`) haben ein eigenes Muster. `grep -n "grant" db/laden-anlegen.sql db/pruefe-laden.sql` zeigt es. Dort die neue Tabelle nach demselben Muster ergänzen und im Report nennen.
- [ ] **Step 4: `termine_eigen.py`.**
```python
"""Eigene Termine des Betreibers (Spec 2026-10-14 §1.1): ohne Kontakt, mit CalDAV-Abgleich.
CalDAV legt nur an (If-None-Match: *) -> Aendern = loeschen + neu eintragen mit derselben uid."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
import kalender
import server

DAUER_MIN, DAUER_MAX = 5, 1440
TEXT_MAX = 200
SPALTEN = "uid, titel, beginn, dauer_minuten, ort, notiz, kalender_stand, geaendert_am"


def _zeile(z: dict) -> dict:
    return {**z, "beginn": z["beginn"].astimezone(kalender.ortszone()),
            "geaendert_am": z["geaendert_am"].isoformat()}


def _pruefen(titel, beginn, dauer):
    if not isinstance(titel, str) or not titel.strip() or len(titel) > TEXT_MAX:
        return "Titel fehlt oder ist zu lang (höchstens 200 Zeichen)."
    if not isinstance(dauer, int) or not DAUER_MIN <= dauer <= DAUER_MAX:
        return f"Dauer muss {DAUER_MIN}–{DAUER_MAX} Minuten sein."
    if beginn.tzinfo is None or beginn < datetime.now(beginn.tzinfo) - timedelta(minutes=1):
        return "Der Termin liegt in der Vergangenheit."
    return None


def _eintragen(uid, titel, beginn, dauer, ort) -> str:
    naiv = beginn.astimezone(kalender.ortszone()).replace(tzinfo=None)
    zustand, grund = kalender.eintragen(uid, kalender.ics(uid, naiv, dauer, titel, ort=ort or ""))
    return grund and f"fehlgeschlagen: {grund}" or zustand


def anlegen(titel, beginn, dauer_minuten, ort="", notiz=""):
    f = _pruefen(titel, beginn, dauer_minuten)
    if f:
        return {"fehler": f}
    uid = f"{uuid.uuid4()}@sales-claw"
    stand = _eintragen(uid, titel.strip(), beginn, dauer_minuten, ort)
    z = server._q(f"insert into eigene_termine (uid, titel, beginn, dauer_minuten, ort, notiz, kalender_stand) "
                  f"values (%s,%s,%s,%s,nullif(%s,''),nullif(%s,''),%s) returning {SPALTEN}",
                  (uid, titel.strip(), beginn, dauer_minuten, ort or "", notiz or "", stand))
    return {"termin": _zeile(z[0])}


def aendern(uid, geaendert_am, **felder):
    alt = server._q(f"select {SPALTEN} from eigene_termine where uid = %s", (uid,))
    if not alt:
        return {"fehler": "Diesen Termin gibt es nicht."}
    if alt[0]["geaendert_am"].isoformat() != geaendert_am:
        return {"veraltet": True}
    neu = {**alt[0], **{k: v for k, v in felder.items() if k in ("titel", "beginn", "dauer_minuten", "ort", "notiz")}}
    f = _pruefen(neu["titel"], neu["beginn"], neu["dauer_minuten"])
    if f:
        return {"fehler": f}
    kalender.loeschen(uid)
    stand = _eintragen(uid, neu["titel"], neu["beginn"], neu["dauer_minuten"], neu.get("ort"))
    z = server._q(f"update eigene_termine set titel=%s, beginn=%s, dauer_minuten=%s, ort=nullif(%s,''), "
                  f"notiz=nullif(%s,''), kalender_stand=%s, geaendert_am=now() where uid=%s and geaendert_am=%s "
                  f"returning {SPALTEN}",
                  (neu["titel"], neu["beginn"], neu["dauer_minuten"], neu.get("ort") or "", neu.get("notiz") or "",
                   stand, uid, alt[0]["geaendert_am"]))
    return {"termin": _zeile(z[0])} if z else {"veraltet": True}


def loeschen(uid):
    z = server._q("delete from eigene_termine where uid = %s returning uid", (uid,))
    if not z:
        return {"fehler": "Diesen Termin gibt es nicht."}
    zustand, grund = kalender.loeschen(uid)
    return {"geloescht": True, "kalender": grund and f"fehlgeschlagen: {grund}" or zustand}


def im_zeitraum(von, bis):
    return [_zeile(z) for z in server._q(
        f"select {SPALTEN} from eigene_termine where beginn < %s and beginn + make_interval(mins => dauer_minuten) > %s "
        "order by beginn", (bis, von))]
```
  - Prüfen, ob `server._q` mit `delete` funktioniert. Das Rückgabemuster mit `returning` bleibt.
- [ ] **Step 5: Grün,** dazu `tests/test_termin.py` unverändert grün.
- [ ] **Step 6: Commit**
```
git add db/provision.sql db/laden-anlegen.sql sales-mcp/termine_eigen.py sales-mcp/tests/test_termine_eigen.py
git commit -m "feat(sales): eigene Termine mit CalDAV-Abgleich (Tabelle eigene_termine)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
(`laden-anlegen.sql` nur, wenn dort ein Grant ergänzt wurde.)

---

### Task 2: Kundentermine ändern und den Kunden benachrichtigen

**Files:**
- Modify: `sales-mcp/server.py` (bei `termin_verschieben`, Z.~6918)
- Test: `sales-mcp/tests/test_termin_aendern.py` (neu)

**Interfaces:**
- Consumes: `termin_bestaetigen`, `termin_absagen`, `termin_einladen`, `_termin_zeile`, `_termin_abgesagt`, `entwurf_erstellen`.
- Produces:
  - `termin_aendern(lead_id: str, uid: str, datum: str = "", uhrzeit: str = "", dauer_minuten: int = 0, thema: str = "", ort: str = "") -> str` (JSON). Leere bzw. 0-Werte heißen „wie bisher“. Die Rückgabe entspricht `termin_verschieben` plus `uid_neu`. Ohne Änderung: `{"fehler": "Nichts geändert."}`.
  - `kunde_benachrichtigen(lead_id: str, alt: dict, neu: dict | None, grund: str = "") -> dict`
    - `alt` und `neu` sind Termin-Payloads `{datum, uhrzeit, dauer_minuten, thema, ort, uid}`; `neu=None` heißt Absage.
    - Rückgabe: `{"draft_id": str, "kanal": "email"|"whatsapp"}` oder `{"hinweis": "kein Kanal zum Kunden – bitte selbst Bescheid geben"}` oder `{"fehler": ...}`.
  - `termin_aendern` ist **kein** neues Agent-Werkzeug (nicht in `WERKZEUGE`). Die Oberfläche ruft es direkt auf.

- [ ] **Step 1: Failing Tests.**
  - Fixtures wie `tests/test_termin.py`: CalDAV-Stub, `keine_echten_belegungsabrufe`, `mail_dispatch.EMAIL_ABSENDER` per monkeypatch gesetzt.
  - Lead-Helfer mit E-Mail und Einwilligung (`existing_customer`) sowie ohne E-Mail mit freigegebenem WhatsApp.
  - Fälle:
    - `termin_aendern` mit neuer Uhrzeit: alter Termin abgesagt, neuer bestätigt, `uid_neu` gesetzt.
    - `termin_aendern` nur mit `ort`: dieselbe Uhrzeit, neuer Ort im neuen Termin.
    - Ohne jede Änderung: `"Nichts geändert."`.
    - `kunde_benachrichtigen` mit E-Mail und vorhandener Einladung zum alten Termin (`termin_einladen` vorher aufgerufen): Entwurf mit `.ics`; `einladung_entworfen` hat dieselbe Einladungs-`uid` und `folge` = 1 (R3).
    - `kunde_benachrichtigen` mit E-Mail ohne Einladung: neue Einladung mit `folge` 0.
    - `kunde_benachrichtigen` mit WhatsApp: Text-Entwurf mit neuem Tag und neuer Uhrzeit im Text.
    - `kunde_benachrichtigen` mit `neu=None` (Absage) und E-Mail: Text-Entwurf mit Betreff „Termin abgesagt“ und dem Grund (R2).
    - Kein Kanal: `hinweis` mit exaktem Wortlaut, kein Entwurf.
    - Alle Entwürfe stehen auf `pending` (`select status from drafts`).
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren.**
```python
def termin_aendern(lead_id, uid, datum="", uhrzeit="", dauer_minuten=0, thema="", ort=""):
    """Kundentermin aendern (Oberflaeche, Spec 2026-10-14 §1.2): technisch wie verschieben — alt absagen, neu
    bestaetigen, alle Felder uebernehmbar. Versendet nichts; den Kunden-Entwurf legt kunde_benachrichtigen an."""
    zeile = _termin_zeile(lead_id, uid)
    if zeile is None:
        return _json({"fehler": f"Zu diesem Kontakt gibt es keinen Termin mit der Kennung {uid}."})
    if _termin_abgesagt(lead_id, uid):
        return _json({"fehler": "Dieser Termin ist abgesagt."})
    a = zeile["payload"] or {}
    neu = {"datum": datum or a.get("datum"), "uhrzeit": uhrzeit or a.get("uhrzeit"),
           "dauer_minuten": int(dauer_minuten or a.get("dauer_minuten") or TERMIN_DAUER_VORGABE),
           "thema": thema or str(a.get("thema") or ""), "ort": ort if ort else str(a.get("ort") or "")}
    if all(str(neu[k]) == str(a.get(k) or ("" if k != "dauer_minuten" else TERMIN_DAUER_VORGABE)) for k in neu):
        return _json({"fehler": "Nichts geändert."})
    b = json.loads(termin_bestaetigen(lead_id, neu["datum"], neu["uhrzeit"], dauer_minuten=neu["dauer_minuten"],
                                      thema=neu["thema"], ort=neu["ort"]))
    if "fehler" in b:
        return _json(b)
    absage = json.loads(termin_absagen(lead_id, uid, f"geändert auf {neu['datum']} {neu['uhrzeit']}"))
    return _json(_ohne_none({**b, "uid_neu": (b.get("termin") or {}).get("uid"),
                             "verschoben_von": {"uid": uid, "datum": a.get("datum"), "uhrzeit": a.get("uhrzeit")},
                             "alter_kalendereintrag": absage.get("kalender")}))
```
  - `kunde_benachrichtigen`:
    - **E-Mail vorhanden und `neu` gesetzt:** Die letzte `einladung_entworfen`-Aktivität dieses Leads mit `datum` und `uhrzeit` gleich dem alten Termin suchen. Gibt es sie, `termin_einladen(lead_id, neu.datum, neu.uhrzeit, neu.dauer_minuten, neu.thema, neu.ort, uid=<einladung.uid>, folge=<einladung.folge + 1>)`. Sonst dasselbe ohne `uid` und `folge`.
    - **E-Mail vorhanden und `neu is None`:** `entwurf_erstellen(lead_id, "email", text, betreff=f"Termin abgesagt: {thema}")`. Text: „Hallo <Vorname>,\n\nleider müssen wir unseren Termin am <TT.MM.> um <HH:MM> absagen.<Grund-Satz>\n\nViele Grüße“.
    - **Sonst WhatsApp freigegeben:** `entwurf_erstellen(lead_id, "whatsapp", text)`. Text bei Änderung: „Hallo <Vorname>, kleine Änderung: unser Termin ist jetzt am <Wochentag TT.MM.> um <HH:MM><, Ort: …>.“ Bei Absage: der Absagetext.
    - **Sonst:** `{"hinweis": "kein Kanal zum Kunden – bitte selbst Bescheid geben"}`.
    - Fehler aus `termin_einladen` oder `entwurf_erstellen` werden als `{"fehler": ...}` durchgereicht.
- [ ] **Step 4: Grün,** dazu `tests/test_termin.py` und `tests/test_termin_einladen.py`. Dort sind Baseline-Fehler bekannt (siehe `baseline-failures.txt` im SDD-Ordner); es dürfen keine neuen hinzukommen.
- [ ] **Step 5: Commit** `feat(sales): Kundentermin aendern und Kunden per Entwurf benachrichtigen`.

---

### Task 3: Sammler aller Kalender-Ereignisse und Konfliktprüfung

**Files:**
- Create: `sales-mcp/kalender_sicht.py`
- Modify: `sales-mcp/ui.py` (`kalender_seite` nutzt den neuen Kundentermin-Helfer statt der Inline-Abfrage, Z.~4141)
- Test: `sales-mcp/tests/test_kalender_sicht.py`

**Interfaces:**
- Consumes: `termine_eigen.im_zeitraum` (Task 1), `kalender.termine_lesen`, `server.kalenderquellen_lesen`, `kalenderquellen.hole`.
- Produces (`kalender_sicht`):
  - `kundentermine(von: datetime, bis: datetime) -> list[dict]`: nicht abgesagte `termin`-Aktivitäten im Zeitraum, je `{uid, lead_id, kontakt, beginn (aware), dauer_minuten, thema, ort, bearbeitbar}`.
    - `bearbeitbar` ist False ohne `uid` oder ohne Lead.
    - `kontakt` ist `"(ohne Kontakt)"`, wenn der Lead fehlt oder keinen Namen hat.
  - `ereignisse(von: datetime, bis: datetime) -> dict`: `{"ereignisse": [...], "hinweise": [str]}`. Je Ereignis:
    - `{id, art: "kunde"|"eigen"|"kollege"|"handy", titel, beginn, ende (isoformat mit Offset), bearbeitbar, uid?, lead_id?, kontakt?, ort?, notiz?, quelle?, geaendert_am?}`
    - `id` hat das Format `"<art>:<uid oder laufende Nummer>"`.
    - Kundentermine heißen „<Thema> – <Kontakt>“.
    - Handy- und Kollegentermine sind `bearbeitbar: False`.
    - Hinweis „Handy-Termine gerade nicht abrufbar“, wenn der eigene CalDAV-Kalender einen Fehler meldet.
  - `konflikte(beginn: datetime, dauer_minuten: int, ausser_uid: str = "") -> dict`: `{"konflikte": [{art, titel, beginn, ende}], "unvollstaendig": bool}`.
    - Überschneidung ist halb-offen.
    - `ausser_uid` nimmt den Termin selbst aus.
    - Es zählen alle vier Arten.
  - Handy-Filter: Ereignisse aus dem eigenen CalDAV-Kalender, deren `uid` als Kunden- oder eigener Termin bekannt ist, entfallen.

- [ ] **Step 1: Failing Tests.**
  - Fake-Quellen per monkeypatch: `kalender.termine_lesen` liefert eine feste Liste, `server.kalenderquellen_lesen` eine Quelle, `kalenderquellen.hole` deren Termine.
  - Fälle:
    - Alle vier Arten erscheinen mit richtiger `art` und `bearbeitbar`.
    - Ein Handy-Termin mit der `uid` eines eigenen Termins erscheint nicht doppelt.
    - Abgesagte Kundentermine fehlen.
    - Lead gelöscht bzw. ohne Namen ergibt „(ohne Kontakt)“ und `bearbeitbar: False` (Review Focus 5).
    - Konflikt mit Kollegen-, Handy-, eigenem und Kundentermin.
    - `ausser_uid` greift.
    - CalDAV-Fehler ergibt `unvollstaendig: True` und den Hinweistext.
    - Zeitraum über die Sommerzeit-Umstellung (24.–26.10.2026): Ein Kundentermin 14:00 hat `beginn` `…T14:00:00+01:00` bzw. `+02:00`, je nach Tag (Review Focus 1).
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren.**
  - Die Abfrage aus `ui.kalender_seite` (`select a.payload, a.created_at, l.id as lead_id, l.name from activities a left join leads l ... where a.type='termin'` plus Abgesagt-Filter) zieht als `kundentermine` um.
  - Das Datum wird mit `datetime.strptime(f"{datum} {uhrzeit}", "%Y-%m-%d %H:%M").replace(tzinfo=kalender.ortszone())` gebildet und nach Zeitraum gefiltert.
  - Kollegen kommen über `kalenderquellen.hole(q["url"], tage_zurueck, tage_voraus)`; die Tage werden aus `von`/`bis` relativ zu jetzt berechnet, mindestens 0.
  - `ui.kalender_seite` nutzt danach `kalender_sicht.kundentermine(...)` für dieselben Zeilen. Die Ausgabe der Seite bleibt bis Task 4 unverändert; `test_kalender_zeit.py` und `test_darstellung.py` bleiben grün.
- [ ] **Step 4: Grün:** `tests/test_kalender_sicht.py tests/test_kalender_zeit.py tests/test_darstellung.py tests/test_kalender_verbinden.py`.
- [ ] **Step 5: Commit** `feat(sales): Kalender-Sicht vereint Kunden-, eigene, Kollegen- und Handy-Termine, Konfliktpruefung`.

---

### Task 4: JSON-Schnittstelle und Seite `/kalender`

**Files:**
- Create: `sales-mcp/ui_kalender.py` (Muster: `ui_editor.py` mit `routen(ui)`)
- Modify: `sales-mcp/ui.py`
  - Routen einhängen wie `*ui_editor.routen(...)`, Z.~6609.
  - Die alte `Route("/kalender", kalender_seite)` und die beiden Formular-Routen bleiben bis zum Ersatz bestehen; `/kalender` zeigt dann die neue Seite.
  - `_KALENDER_ROLLE_PFADE` bekommt `"/static/kalender"`.
  - Die Kontaktseite (`kontakt_detail`, vor „Offene Wiedervorlagen“, Z.~5317) bekommt den Abschnitt „Termine“ mit „im Kalender öffnen“-Links.
- Test: `sales-mcp/tests/test_ui_kalender.py`

**Interfaces:**
- Consumes: `kalender_sicht.ereignisse` und `konflikte` (Task 3), `termine_eigen.*` (Task 1), `server.termin_bestaetigen`, `termin_einladen`, `termin_aendern`, `termin_absagen`, `kunde_benachrichtigen` (Task 2), `konferenz.raum()`.
- Produces (HTTP, alle `Cache-Control: no-store`, JSON-Fehler als `{"grund": str}`):
  - `GET /kalender`: HTML-Seite mit Seitenleiste (`ui._seite`).
    - Im Rumpf: `<div id="kalender"></div>` und `<script type="application/json" id="kalender-start">{...}</script>`. Startdaten: `{csrf, rolle, darf_schreiben, datum, ansicht, freigaben_url: "/freigaben"}`.
    - Dazu `<link href="/static/kalender/kalender.css">`, `<script src="/static/kalender/kalender.js" defer>`, darunter die bisherigen Abschnitte (R5).
    - CSP der Seite: `ui._CSP` mit `script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'`.
    - Query `datum=YYYY-MM-DD` und `ansicht=woche|tag|monat|liste` werden übernommen.
  - `GET /static/kalender/{datei}`: nur `kalender.js` und `kalender.css`, sonst 404.
  - `GET /kalender/termine.json?von=<iso>&bis=<iso>`: Ausgabe von `ereignisse`. Fehlende oder ungültige Parameter ergeben 422. Spanne höchstens 62 Tage.
  - `POST /kalender/termine`, Body:
    - eigener Termin: `{art: "eigen", titel, beginn (iso mit Offset), dauer_minuten, ort?, notiz?, trotzdem?}`;
    - Kundentermin: `{art: "kunde", lead_id, thema, beginn, dauer_minuten, ort?, einladung?: bool, trotzdem?}`.
    - Ergebnis 201 `{ereignis, entwurf?: {draft_id, kanal} | hinweis?}`, oder 409 `{grund: "Konflikt", konflikte, unvollstaendig}`, oder 422.
  - `PATCH /kalender/termine/{id}`, Body `{geaendert_am?, beginn?, dauer_minuten?, titel?, ort?, notiz?, trotzdem?}`.
    - `id` hat das Format `eigen:<uid>` oder `kunde:<uid>`.
    - Eigen: `termine_eigen.aendern`; `veraltet` ergibt 409 `{grund: "inzwischen geändert – neu laden"}`.
    - Kunde: `server.termin_aendern`, danach `kunde_benachrichtigen(alt, neu)`. Ergebnis 200 `{ereignis, entwurf | hinweis}`.
  - `DELETE /kalender/termine/{id}`, Body `{grund?}`.
    - Eigen: löschen.
    - Kunde: `grund` Pflicht (sonst 422), dann `termin_absagen` und `kunde_benachrichtigen(alt, None, grund)`.
  - `POST /kalender/videoraum`: `{link, hinweis?}`.
  - Alle schreibenden Routen: CSRF über den Header `x-csrf` mit `hmac.compare_digest(…, ui.CSRF_TOKEN)`, sonst 403. Die Rolle `kalender` bzw. `lesen` blockt die Anmeldewache schon (403).
  - Konflikte: Vor POST und PATCH wird `kalender_sicht.konflikte(beginn, dauer, ausser_uid)` geprüft. Bei Treffern und ohne `trotzdem: true` kommt 409 (Review Focus 2: Konflikt zuerst, Entwurf erst beim zweiten Aufruf).

- [ ] **Step 1: Failing Tests** mit dem `TestClient`-Muster aus `tests/test_ui.py` (Host-Header `127.0.0.1:8791`). Rollen-Tests mit dem Fixture `scharf` und `benutzer_anlegen` aus `tests/test_kalender_verbinden.py`.
  - Seite trägt `script-src 'self'`; `/kontakte` trägt es nicht.
  - Startdaten enthalten `csrf` und für die Rolle `kalender` `darf_schreiben: false`.
  - `/static/kalender/kalender.js` ergibt 200 (nach Task 5 vorhanden). Für diesen Task genügt eine Platzhalterdatei aus dem Test-Setup per `tmp`-Monkeypatch von `ui_kalender.STATIK`. `/static/kalender/x.js` ergibt 404.
  - `termine.json` mit falschen Parametern ergibt 422; mit gültigen liefert es Ereignisse aus einem gemonkeypatchten `kalender_sicht.ereignisse`.
  - POST eigener Termin: 201. Ohne `x-csrf`: 403. Konflikt: 409, mit `trotzdem`: 201.
  - PATCH eigen veraltet: 409 mit Wortlaut. PATCH Kunde: Entwurf in `drafts` (`pending`) und Antwort mit `draft_id`.
  - DELETE Kunde ohne Grund: 422. Mit Grund: Absage und Entwurf.
  - Rolle `kalender`: POST ergibt 403 (Wache). GET `termine.json` ergibt 200.
  - Konflikt mit Handy-Termin beim PATCH eines Kundentermins: Der erste Aufruf gibt 409 und es gibt keinen Entwurf. Der zweite mit `trotzdem` gibt 200 und genau einen Entwurf (Review Focus 2).
  - Kontaktseite eines Leads mit Termin enthält `href="/kalender?datum=` und `ansicht=woche`.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren.**
  - Das Modul folgt der Struktur von `ui_editor.py`: `routen(ui)` liefert eine Liste von `Route`, mit eigenem `json_grund` und `CSP_KALENDER`.
  - Zeiten kommen als ISO mit Offset herein (`datetime.fromisoformat`). Für Kundentermine werden sie nach `kalender.ortszone()` umgerechnet und in `datum`/`uhrzeit` zerlegt.
  - Die alte Monatsgitter-Ausgabe in `kalender_seite` entfällt. Die übrigen Abschnitte bleiben (R5): Aus `kalender_seite` wird eine Funktion `kalender_abschnitte()`, die nur die HTML-Abschnitte liefert und von der neuen Seite eingebettet wird. Die alten Tests, die das Monatsgitter erwarten (`test_kalender_zeit.py`, `test_darstellung.py`), werden auf die neue Seite angepasst. Dabei entfernte Assertions je Test im Report begründen.
- [ ] **Step 4: Grün:** `tests/test_ui_kalender.py tests/test_kalender_zeit.py tests/test_darstellung.py tests/test_kalender_verbinden.py tests/test_seitenleiste.py tests/test_ui.py`.
- [ ] **Step 5: Commit** `feat(sales-ui): Kalender-Schnittstelle und neue Seite /kalender`.

---

### Task 5: Kalender-Bundle (FullCalendar)

**Files:**
- Create: `kalender/package.json`, `kalender/vite.config.ts`, `kalender/tsconfig.json`, `kalender/manifest.mjs`, `kalender/src/main.ts`, `kalender/src/api.ts`, `kalender/src/abbild.ts`, `kalender/src/fenster.ts`, `kalender/src/kalender.css`, Tests `kalender/src/*.test.ts`
- Create (Build): `sales-mcp/static/kalender/kalender.js`, `kalender.css`, `MANIFEST.json`
- Create: `sales-mcp/tests/test_kalender_paket.py`

**Interfaces:**
- Consumes: HTTP-Schnittstelle aus Task 4; Startdaten `#kalender-start`.
- Produces:
  - `abbild.ts`:
    - `zuEvent(e: Ereignis): EventInput` mit `id`, `title`, `start`, `end`, `editable`, `color` je Art, `extendedProps: {art, uid, lead_id, kontakt, ort, notiz, geaendert_am}`.
    - `zuAenderung(ev: EventApi): {beginn: string, dauer_minuten: number}` mit ISO und lokalem Offset.
    - `FARBEN = {kunde: 'var(--marke, #b45309)', eigen: '#2563eb', kollege: '#4d7c5a', handy: '#9ca3af'}`.
  - `api.ts`: `laden(von, bis)`, `anlegen(body)`, `aendern(id, body)`, `loeschen(id, body)`, `videoraum()`. Alle mit `x-csrf` und `credentials: 'same-origin'`; Ergebnis `{ok, status, daten}`.

- [ ] **Step 1: Projekt aufsetzen.**
  - `package.json`: name `sales-claw-kalender`, `"type": "module"`, scripts `build: "vite build && node manifest.mjs"`, `test: "vitest run"`.
  - Abhängigkeiten `@fullcalendar/core`, `@fullcalendar/daygrid`, `@fullcalendar/timegrid`, `@fullcalendar/list`, `@fullcalendar/interaction` (alle ^6), dazu dev `vite` ^5, `vitest` ^2, `typescript` ^5.
  - `vite.config.ts` nach dem Editor-Muster:
    - `base: '/static/kalender/'`, `outDir: '../sales-mcp/static/kalender'`, `emptyOutDir: true`, `format: 'iife'`;
    - `entryFileNames: 'kalender.js'`, CSS nach `kalender.css`, `cssCodeSplit: false`, `inlineDynamicImports: true`;
    - `test.include: ['src/**/*.test.ts']`.
  - `manifest.mjs` hasht `kalender.js` und `kalender.css` in `MANIFEST.json` `{quelle: 'fullcalendar@<version aus package-lock>', gebaut, sha256}`.
- [ ] **Step 2: Failing vitest-Tests** (`abbild.test.ts`):
  - Kunde ist ziehbar und trägt den Kontakt im Titel.
  - Handy und Kollege sind nicht `editable`.
  - Die Rolle ohne Schreibrecht ergibt `editable: false` für alle.
  - `zuAenderung` nach dem Ziehen um +60 min ergibt die richtige Dauer. Ein Resize von 30 auf 90 ergibt 90.
  - Über die Sommerzeit-Umstellung am 25.10.2026 bleibt 14:00 lokal 14:00 (Review Focus 1).
  - `braucheBestaetigung(art)` ist nur bei `kunde` wahr.
- [ ] **Step 3: Implementieren.**
  - **`main.ts`:**
    - Startdaten lesen und `new Calendar(el, {...})` anlegen.
    - Plugins `dayGrid`, `timeGrid`, `list`, `interaction`.
    - `initialView` aus dem `localStorage`-Schlüssel `vibemind.kalender.ansicht` (try/catch), Rückfall: `timeGridWeek`; ist `window.innerWidth < 640`, dann `listWeek`.
    - `initialDate` aus den Startdaten. `locale: 'de'` über `@fullcalendar/core/locales/de`. `firstDay: 1`.
    - `slotMinTime: '07:00'`, `slotMaxTime: '20:00'`, `scrollTime: '08:00'`.
    - `businessHours: {daysOfWeek: [1,2,3,4,5], startTime: '08:00', endTime: '18:00'}`. `nowIndicator: true`.
    - `headerToolbar` mit `prev,next today`, Titel und `timeGridDay,timeGridWeek,dayGridMonth,listWeek`.
    - `events: (info, ok, fehler) => api.laden(info.startStr, info.endStr)`; Hinweise aus der Antwort als Leiste über dem Kalender.
    - `selectable` und `editable` nur bei `darf_schreiben`.
    - `select` öffnet das Anlegen-Fenster. `eventClick` öffnet das Bearbeiten-Fenster bzw. Details bei nicht bearbeitbaren Terminen.
    - `eventDrop` und `eventResize`:
      - Ist `braucheBestaetigung`, zuerst `confirm(\`Verschieben auf ${…} – Entwurf an Kunden wird angelegt\`)`; bei Nein `info.revert()`.
      - Dann `api.aendern(id, {...zuAenderung(ev), geaendert_am})`.
      - Bei 409 „Konflikt“: Konfliktfenster mit „trotzdem speichern“ (gleiche Anfrage mit `trotzdem: true`) bzw. „abbrechen“ (`revert`).
      - Bei 409 „inzwischen geändert – neu laden“: Hinweis und `calendar.refetchEvents()`.
      - Bei Erfolg mit Entwurf: Hinweis „Entwurf an Kunde angelegt – in Freigaben“ mit Link.
    - `datesSet` speichert die Ansicht in `localStorage`.
  - **`fenster.ts`:** ein schlichter `<dialog>` mit Formular, ohne UI-Bibliothek.
    - Felder: Art (eigen/Kunde; Kunde mit Kontaktsuche über `GET /kontakte.json?q=`, falls vorhanden, sonst ein Feld für die Lead-ID mit Hinweis), Titel/Thema, Datum/Zeit, Dauer, Ort, Knopf „Videoraum“ (`api.videoraum()` trägt den Link in Ort ein), Notiz, bei Kunde „Einladung als Entwurf“.
    - Bearbeiten zusätzlich: „Löschen“ bzw. „Absagen“ mit Grund-Feld (Pflicht bei Kunde) und „Zum Kontakt“ (`/kontakte/<lead_id>`).
    - Der Absenden-Knopf ist während der Anfrage gesperrt (Review Focus 3). Dazu ein Test in `fenster.test.ts`, der zweimal `absenden()` aufruft und genau einen API-Aufruf sieht.
  - **Kontaktsuche:** Gibt es keine JSON-Suche, kommt in Task 4 nachträglich `GET /kalender/kontakte.json?q=` dazu. Es liefert höchstens 10 `{lead_id, name}` über `server.kontakt_suchen` und wird im Report vermerkt.
  - **`kalender.css`:** schlichte Anpassung an die Oberfläche (Schrift, Farben, Wochenende `.fc-day-sat, .fc-day-sun {background: #f3f4f6}`).
- [ ] **Step 4:** `npx vitest run; npx tsc --noEmit; npm run build`. Danach liegen `kalender.js`, `kalender.css` und `MANIFEST.json` in `sales-mcp/static/kalender/`.
- [ ] **Step 5: Drift-Test** `sales-mcp/tests/test_kalender_paket.py` nach dem Muster von `test_editor_paket.py`:
  - Manifest-Hashes stimmen.
  - Es gibt nur die drei Dateien.
  - Keine fremden Quellen (`cdnjs.`, `googleapis.`, `gstatic.`, `unpkg.`, `jsdelivr.`, `cloudfront.`).
  - `kalender.js` enthält „Entwurf an Kunde angelegt – in Freigaben“ und „inzwischen geändert – neu laden“.
- [ ] **Step 6: Commit** (inkl. `package-lock.json` und Build):
```
git add kalender/package.json kalender/package-lock.json kalender/vite.config.ts kalender/tsconfig.json kalender/manifest.mjs kalender/src sales-mcp/static/kalender sales-mcp/tests/test_kalender_paket.py
git commit -m "feat(kalender): Wochen-/Monats-/Listenansicht mit Ziehen, Anlegen, Bearbeiten (FullCalendar)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
  `kalender/node_modules` bleibt draußen. Prüfen, ob `.gitignore` sie schon ausschließt; sonst eine `kalender/.gitignore` mit `node_modules/` anlegen und mit committen.

---

### Task 6: Volle Suite und Abschluss-Check (Implementer)

- [ ] **Volle Suite:** `tests/ -q -p no:cacheprovider -rf` im Vordergrund (rund 20 min). Die FAILED-Menge muss gleich der Baseline sein, die der Controller mitgibt.
- [ ] **`grep`** nach Platzhaltern bzw. Debug-Ausgaben in den neuen Dateien (`console.log`, `print(`). Es darf keine geben.
- [ ] **Report:** Liste der geänderten alten Tests mit Begründung.

---

### Task 7: Auslieferung und echter Lauf (Controller, nur nach Freigabe)

- [ ] Claims in WORKBOARD und secondbrain eintragen, nur die eigene Zeile stagen.
- [ ] `db/provision.sql` als `supabase_admin` einspielen: `docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 < provision.sql`. Danach prüfen, dass `eigene_termine` in `sales` und `sales_ivan` existiert und die Grants stimmen.
- [ ] Push von SC, dann auf der VM `update.sh`. Vorher die openwa-Session prüfen: Steht sie auf `failed`, mit `/start` wieder hochbringen (Lehre aus Block A).
- [ ] **Echter Lauf:**
  1. Eigenen Termin anlegen; er steht im Namecheap-Kalender (Handy).
  2. Ihn ziehen, dann löschen.
  3. Einen Probe-Kundentermin verschieben; der Entwurf liegt in den Freigaben (nicht freigeben).
  4. Einen Handy-Termin anlegen; er erscheint grau, und die Konfliktwarnung greift.
- [ ] Claims schließen, Memory aktualisieren.
