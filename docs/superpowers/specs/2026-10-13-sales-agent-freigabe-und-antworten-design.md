# Sales-Agent: Antworten, Freigabe im Chat, keine verschluckten Fehler — Design (Block A)

Stand: 2026-10-13 · Status: in drei Abschnitten vom Betreiber freigegeben

Block A von drei. Block B (Kalender) und Block C (Kontaktliste) folgen mit eigener Spec.

## Anlass (gemessen 13.10. auf der VM, Laden `sales`)

| Beschwerde | Befund |
|---|---|
| „Mails gehen nicht raus“ | Freigegebene Mails gehen raus: 21× `sent`, zuletzt 11.10., Versand 10 s nach Freigabe. Die beiden „Agent Farm“-Einladungen vom 12.10. wurden **in der Oberfläche abgelehnt** (`activities.ablehnung`, `weg: ui`). Im Fall Leo Wiedemann (13.10.) entstand **gar kein Entwurf**, weil zwei Sperren griffen (siehe nächste Zeile). |
| „stellt sich quer“ | Leo-Fall. Der Betreiber sagte „dort antworten“ auf eine Postfach-Mail. Der Agent schrieb die Antwort als Chattext, wollte dann per WhatsApp schreiben und fragte nach der Nummer. Danach legte er den Kontakt mit `source: whatsapp` an. `antwort_entwerfen` scheiterte an „Kontakt steht auf manuell – es entsteht kein Entwurf“. `entwurf_erstellen` scheiterte an „ERSTANSPRACHE ohne dokumentierte Einwilligung (UWG)“, obwohl Leo zuerst geschrieben hatte. Beide Fehler meldete der Agent nicht. Seine nächste Antwort war der Bericht des Postfach-Cronjobs, der in derselben Sitzung lief. |
| „Freigabe im Chat führt nicht aus“ | In 14 Tagen lief jede Freigabe über die Oberfläche. `AGENTS.md` verlangt vor `entwurf_freigeben` den vollen Text **und** eine weitere ausdrückliche Rückfrage. |
| (neu gefunden) | WhatsApp-Antworten von Arjun und Muttu (10.–12.10., über ein Dutzend) wurden als `eingang_ignoriert` ohne Text gebucht. Grund: Beide gehören zu 33 Absendern, die am 01.10. 07:04 als „ignorieren“ eingeordnet wurden. Am 10.10. wurden sie freigegebene Team-Kontakte, die Markierung blieb aber bestehen. |

## Entscheidungen des Betreibers

| Frage | Antwort |
|---|---|
| Reihenfolge | Block A (Agent, Freigabe, Versand) zuerst; danach Kalender, dann Kontaktliste |
| Ignorierter Absender wird echter Kontakt | Markierung automatisch aufheben, der Agent meldet es in einem Satz |
| Eingehende Nachrichten | **Nie automatisch beantworten**: nur Entwurf zur Freigabe. Das steht im Prompt. |
| Autonomie-Stufen | Bleiben maßgeblich (Flags). „manuell“ darf ausdrückliche Betreiber-Aufträge nicht verschlucken. |
| Einwilligung bei Betreiber-Auftrag | Der Agent nimmt an, dass sie vorliegt; der Betreiber verantwortet sie. Sie wird mit Quelle gebucht. |
| Bedarfsanalyse | Vorerst raus (abschalten, nicht löschen) |

## 1. Antworten und Entwürfe

### 1.1 `mail_beantworten(uid, text)` (neues Werkzeug, Betreiber-Chat)

1. Die Mail mit `uid` aus dem Postfach lesen (wie `postfach_mail_lesen`). Fehlt sie, meldet das Werkzeug „Mail nicht mehr im Postfach“, und es entsteht kein Entwurf.
2. Den Kontakt über die Absenderadresse finden. Fehlt er, wird er angelegt (`source = 'email'`, Name aus dem Absender).
3. Die eingegangene Mail als **Kundennachricht** am Kontakt buchen (eingehend, Kanal E-Mail, mit Message-ID, dedupliziert). Damit gilt der Kontakt als „hat selbst geschrieben“, und die UWG-Sperre für Erstansprache greift zu Recht nicht.
4. Einen E-Mail-Entwurf anlegen:
   - Empfänger = Absender;
   - Betreff „Re: <Betreff>“ (ohne doppeltes „Re:“);
   - Status `pending`;
   - Antwort-Kennung = Message-ID der Mail.
5. Absender ohne brauchbare Adresse (`noreply`, `no-reply`, `mailer-daemon`): kein Entwurf. Rückgabe ist eine Frage an den Betreiber, wohin die Antwort gehen soll.

**Mailverlauf:**
- `drafts` bekommt die Spalte `antwort_auf text` (Message-ID). Sie wird in `db/provision.sql` additiv und idempotent ergänzt, für jeden Laden.
- `mail_dispatch` setzt `In-Reply-To` und `References`, wenn die Spalte gefüllt ist.

### 1.2 Nie automatisch antworten

- Eingehende Nachrichten (WhatsApp, E-Mail) erzeugen höchstens einen **Entwurf zur Freigabe** und einen Hinweis an den Betreiber. Sie führen nie zu einem Versand ohne Freigabe.
- Das steht als harte Regel in `config/workspace/AGENTS.md`.
- Bezieht sich der Betreiber auf eine Postfach-Mail („dort antworten“, „auf die Mail antworten“), nimmt der Agent `mail_beantworten`. Er wechselt nie eigenmächtig den Kanal und fragt nicht nach einer Telefonnummer.

### 1.3 Autonomie-Stufen bleiben maßgeblich

- Die Stufe am Kontakt steuert weiter, was **von selbst** geschieht.
- Neu ist nur Folgendes: Ruft der Agent `antwort_entwerfen` bzw. `entwurf_erstellen` im Auftrag des Betreibers auf (Parameter `auftrag_betreiber=true`), entsteht bei „manuell“ ein Entwurf `pending`, statt dass der Aufruf abgelehnt wird.
- Die Rückgabe nennt die Stufe: „Kontakt steht auf manuell – Entwurf liegt zur Freigabe“.
- Ohne den Parameter, also bei Automatik und Cronjobs, bleibt „manuell“ wie heute: Es entsteht nichts.
- `auftrag_betreiber` ist nur im Betreiber-Chat erlaubt. Im Kundenchat sind Betreiber-Werkzeuge ohnehin tabu.

### 1.4 Einwilligung bei Betreiber-Auftrag

- Verlangt der Betreiber, jemandem zu schreiben (`auftrag_betreiber=true`), und liegt keine dokumentierte Grundlage vor, bucht das Werkzeug die Grundlage selbst. Es nutzt dafür denselben Weg wie `einwilligung_erfassen`: `art = 'betreiber_auftrag'`, `quelle = 'Betreiber-Auftrag vom <Datum>'`, `durch = 'betreiber'`. Danach geht es weiter.
- Die neue Art `betreiber_auftrag` kommt in die erlaubten Werte von `consent_status`.
- Für alles, was der Agent **von sich aus** anstößt, bleibt die UWG-Sperre unverändert.

### 1.5 Ignorieren aufheben

- `kontakt_freigeben` (Kanal WhatsApp) und der erste vom Betreiber freigegebene Entwurf an einen ignorierten Absender heben dessen Ignorieren-Markierung auf. Das gilt für die Rufnummer und alle ihr eindeutig zugeordneten `@lid`-Kennungen.
- Gebucht wird eine Aktivität `absender_ignorieren_aufgehoben`. Die Rückgabe enthält den Satz „X stand auf Ignorieren – aufgehoben, neue Nachrichten sind wieder sichtbar.“
- **Einmalige Reparatur:** Die Markierungen für Arjun (4915752415952) und Muttu (4915565715663) werden über denselben Weg aufgehoben (Skript in Task-Form, nicht von Hand in der DB). Die übrigen 31 bleiben.

### 1.6 Bedarfsanalyse vorerst aus

- Schalter `SALES_BEDARFSANALYSE` (Vorgabe `aus`).
- Bei `aus`:
  - Die Leitfaden-Werkzeuge (Antwort ablegen, offene Fragen) werden nicht registriert.
  - Der Abschnitt „Bedarfsanalyse“ und alle Hinweise auf Leitfaden-Fragen fliegen aus `AGENTS.md`.
  - `digest` lässt „unvollständige Bedarfsanalysen“ weg.
  - Die Kontaktansicht zeigt keinen Bedarfsstand.
  - Die Übergabe (`uebergabe_erstellen`) lässt den Abschnitt weg.
- Code, `leitfaden.yaml` und bereits erfasste Antworten bleiben.

## 2. Freigabe im Chat und Rückmeldung

### 2.1 Freigabe führt aus

- Der Agent zeigt einen Entwurf **einmal vollständig**: Empfänger, Kanal, Betreff, Text.
- Antwortet der Betreiber in der nächsten Nachricht mit „ja“, „senden“, „raus“, „freigeben“ oder „ok“, ruft der Agent `entwurf_freigeben(draft_id)` genau für diesen Entwurf auf. Eine zweite Rückfrage gibt es nicht.
- „ändere …“ ergibt einen neuen Text (`entwurf_bearbeiten`), der erneut gezeigt wird; das ist wieder ein Freigabepunkt.
- Sind mehrere Entwürfe offen und ist der Bezug nicht eindeutig, fragt der Agent einmal kurz, welcher gemeint ist.

### 2.2 Rückmeldung nach dem Versand

Neues Werkzeug `versand_abwarten(draft_id, max_s=60)`:
- Es pollt den Entwurfsstatus.
- Rückgabe ist `sent`, `failed` (mit `error`) oder `wartet`.

Der Agent meldet:
- „Ist raus an X (E-Mail)“, oder
- „Nicht raus: <Grund>“, oder
- „liegt freigegeben in der Warteschlange“.

Hat der Laden kein eigenes Kundenpostfach (`kunden_identitaet` nicht brauchbar), meldet das Werkzeug das sofort. Der Agent sagt dann „bleibt liegen, bis das Postfach eingetragen ist“.

### 2.3 Keine verschluckten Fehler

- Harte Regel in `AGENTS.md`: Liefert ein Werkzeug `fehler`, nennt der Agent ihn **im selben Zug** in einem Satz, mit Grund und nächstem Schritt.
- Ein Prompt-Test prüft, dass die Regel wörtlich drinsteht.

### 2.4 Cronjobs stören den Chat nicht

- Am 13.10. lief der Postfach-Cronjob (`deploy/cron/postfach-check.json`, `sessionTarget: isolated`, Zustellung per WhatsApp an `MELDE_AN`) in der Sitzung des Betreiber-Chats.
- Der Plan misst zuerst die Ursache und behebt sie dann. Mögliche Ursachen: Die Zustellung landet als Nachricht im Betreiber-Chat, oder `isolated` greift in der laufenden openclaw-Fassung nicht.
- Ziel: Ein Cron-Bericht ist eine eigene Nachricht, und ein „ja“ des Betreibers bezieht sich immer auf den letzten Entwurf des Agenten.

## 3. Fehlerfälle, Tests, Auslieferung

### Fehlerfälle

| Fall | Verhalten |
|---|---|
| `uid` nicht mehr im Postfach | „Mail nicht mehr im Postfach“, kein Entwurf |
| Absender `noreply` o. Ä. | Rückfrage, wohin die Antwort gehen soll |
| Mehrere offene Entwürfe, nur „ja“ | Eine kurze Rückfrage, welcher |
| Laden ohne Kundenpostfach | Freigabe ja, Meldung „bleibt liegen, bis das Postfach eingetragen ist“ |
| Werkzeugfehler | Im selben Zug genannt |
| Ignorieren aufheben, mehrere Kennungen | Nur eindeutig derselben Person zugeordnete Kennungen |

### Tests

- **sales-mcp** (Test-Postgres, Schema `sales_test`):
  - `mail_beantworten`: Entwurf `pending` mit `antwort_auf`, Kontakt neu oder vorhanden, eingehende Mail gebucht, keine UWG-Sperre, `noreply` → Rückfrage, `uid` fehlt → Meldung.
  - „manuell“ + `auftrag_betreiber` → Entwurf; ohne den Parameter → kein Entwurf.
  - Einwilligung `betreiber_auftrag` wird gebucht; ohne Auftrag greift die Sperre weiter.
  - Freigabe hebt Ignorieren auf; die Aktivität wird gebucht.
  - `SALES_BEDARFSANALYSE=aus`: keine Leitfaden-Werkzeuge, Digest ohne den Teil.
  - `mail_dispatch` setzt `In-Reply-To`/`References`.
  - `versand_abwarten` liefert `sent`, `failed` und `wartet`.
- **Prompt-Drift-Test:** `AGENTS.md` enthält die Regeln aus 1.2, 2.1 und 2.3; der Abschnitt „Bedarfsanalyse“ fehlt.
- **Echter Lauf nach der Auslieferung:**
  - Probe-Mail an das eigene Postfach, dann „dort antworten“ und „ja“: Entwurf, Freigabe, „ist raus“, Mail im selben Verlauf angekommen.
  - Ein WhatsApp-Auftrag an einen Kontakt auf „manuell“ ergibt einen Entwurf zur Freigabe.
  - Arjun und Muttu: Die nächste Nachricht ist sichtbar und erzeugt keinen automatischen Versand.

### Auslieferung

- sales-claw `deploy/update.sh` auf der VM, nach Freigabe des Betreibers.
- Die DB-Änderung (`antwort_auf`, `consent_status`-Wert) läuft über `provision.sql` für jeden Laden.

## Nicht Teil dieses Blocks

- Kalender (Block B).
- Kontaktliste (Block C).
- Löschen der Bedarfsanalyse.
- Eigenes Kundenpostfach für Ivans Laden.
