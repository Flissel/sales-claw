# Stufe 10: Freigabe-Frontend `sales-ui` (lokal, siebter Container)

Betreiber-Entscheidung 19.08.2026 („ok" auf den Vorschlag aus der Bot-Evaluation):
Eine visuelle Freigabe- und Datenansicht vor der bestehenden Datenbank. Vercel/öffentlich
ist ausdrücklich NICHT Teil dieser Stufe — Begründung siehe Sicherheitsmodell.

## Ziel

Ein lokales Web-UI als eigener Container `sales-ui`:

- **Lesen:** Entwürfe (pending / failed / approved / zuletzt gesendet), Kontakte mit
  Verlauf/Bedarf/Verträgen/Wiedervorlagen, Posteingang (unbeantwortete zuerst),
  offene Wiedervorlagen.
- **Schreiben — ausschließlich die drei Freigabe-Aktionen:** freigeben
  (pending→approved), ablehnen (pending→rejected), erneut freigeben
  (failed→approved, mit Bestätigung). Nichts anderes. Kein Editieren, kein Löschen,
  kein Anlegen.

## Grundsatzentscheidungen

1. **Kein neues Framework.** Starlette + uvicorn sind bereits im `sales-mcp`-Image
   (Abhängigkeit von `mcp`, gemessen: starlette 1.6.0, uvicorn 0.52.4). Server-seitig
   gerendertes HTML, Inline-CSS, kein JavaScript-Build, kein npm. Deutsch, schlicht,
   lesbar. `requirements.txt` bleibt unverändert — vor Abgabe nachweisen.
2. **Gate-Semantik wird gespiegelt, nicht neu erfunden.** Die Update-Statements für
   die drei Aktionen übernehmen EXAKT die Bedingungen aus `server.py`
   (`entwurf_freigeben`: nur aus `status='pending'`; `entwurf_ablehnen`;
   `entwurf_erneut_freigeben`: nur aus `failed` **inklusive der
   Doppelversand-Marken-Prüfung** — Semantik dort ablesen, nicht raten).
   `approved_by='betreiber-ui'`, damit im Audit unterscheidbar bleibt, über welchen
   Weg freigegeben wurde. Das UI kann damit konstruktiv nichts, was die
   Chat-Werkzeuge nicht auch können.
3. **Sicherheitsmodell (Demo-Umfang, dokumentiert):**
   - Bind ausschließlich `127.0.0.1` (Compose-Mapping `127.0.0.1:8791:8791`).
     Vertrauensgrenze ist der Rechner des Betreibers — wie beim Gateway-Port 18894.
   - **CSRF-Schutz ist trotzdem Pflicht:** Browser fremder Webseiten können auf
     127.0.0.1 POSTen. Boot-Token (`secrets.token_urlsafe`), in jedem Formular als
     Hidden-Field, bei jedem POST geprüft; Fehlschlag → 403, keine Aktion.
   - **Host-Header-Prüfung** gegen DNS-Rebinding: nur `127.0.0.1:8791` /
     `localhost:8791` zulässig, alles andere → 421/403.
   - **Alles HTML-escapen** (`html.escape`): Entwurfstexte, Kundennachrichten,
     Namen sind Fremddaten und damit XSS-Vektoren in einem Betreiber-Browser.
   - Keine Secrets in Seiten oder Logs; einzige Env-Eingaben `SALES_DB_URL`,
     `SALES_DB_SCHEMA` (Default `sales`), `TZ`, optional `UI_PORT`.
4. **Seiten:**
   - `/` Freigabe-Inbox: pending-Entwürfe zuerst (Volltext, Kanal-Badge, Empfänger,
     Alter) mit Freigeben/Ablehnen; darunter failed mit Fehlertext und
     Erneut-freigeben (Bestätigungs-Checkbox, unchecked → Aktion verweigert wie im
     Werkzeug); darunter approved („wartet auf Dispatcher") und die letzten 20
     gesendeten. Meta-Refresh 30 s.
   - LinkedIn-Sonderfall: freigegebene LinkedIn-Entwürfe zeigen den Hinweis
     „von Hand posten, danach im Chat `entwurf_manuell_gesendet` melden" —
     es gibt bewusst keinen LinkedIn-Dispatcher.
   - `/kontakte` Liste (Name, Status, letzte Aktivität) → `/kontakte/{id}`:
     Stammdaten, Aktivitäten chronologisch, Bedarfsstand, Verträge
     (`enrichment.vertraege`), Wiedervorlagen des Kontakts.
   - `/posteingang`: Logik des `posteingang`-Werkzeugs spiegeln (unbeantwortete
     zuerst, absenderscharf), LID-Pseudo-Kennungen als solche kennzeichnen.
   - `/wiedervorlagen`: offene nach Fälligkeit.
5. **Service-Zuschnitt wie `inbox.py`:** eine Datei `sales-mcp/ui.py`, ausführlicher
   Kopf-Docstring im Hausstil (was der Dienst darf und was ausdrücklich nicht),
   Schema-Wächter wie in `server.py` (nur `sales`/`sales_test`, sonst SystemExit).
6. **Compose:** Service `sales-ui`, gleiches Build wie `sales-mcp`, Kommando
   `python ui.py`, **explizite environment-Liste** (T5a-Muster, kein `env_file`),
   `restart: unless-stopped`, Port nur auf 127.0.0.1.
7. **Tests (TDD, ausschließlich `sales_test`, Ein-Läufer-Betrieb laut Runbook):**
   `tests/test_ui.py` mit mindestens: CSRF-Fehlen/falsch → 403 und kein
   Statuswechsel; falscher Host-Header → abgewiesen; XSS-Probe (Entwurfstext
   `<script>` erscheint escaped, nie roh); Freigabe nur aus pending (approved/sent
   unverändert + Fehlermeldung); Ablehnen nur aus pending; erneut freigeben nur aus
   failed, ohne Bestätigung verweigert, mit Marken-Fall verweigert (Semantik aus
   `server.py`); `approved_by='betreiber-ui'` gesetzt; Posteingang-Seite zeigt
   Unbeantwortete. Starlette-TestClient, falls httpx im Image liegt (prüfen),
   sonst ASGI direkt.
8. **Doku:** Runbook-Abschnitt „Freigabe-Oberfläche (sales-ui)" (Start, Adresse,
   Sicherheitsmodell, ausdrücklich: nicht ins Internet stellen; Vercel-Read-only
   wäre eine eigene, bewusste Folge-Entscheidung). AGENTS.md: ein Satz, dass es die
   Oberfläche gibt und der Bot bei „wo gebe ich frei?" auf `http://127.0.0.1:8791`
   verweisen darf. `.env.example`: nichts Neues nötig (keine neuen Secrets).

## Nicht in dieser Stufe

- Kein Vercel/öffentliches Deployment, keine Authentifizierung über die
  127.0.0.1-Grenze hinaus, kein Schreiben an Kontakten/Notizen, kein
  Entwurf-Editor, keine Live-Push-Updates (Meta-Refresh reicht für die Demo).

## Abnahme

1. Testsuite grün (Bestand + neue `test_ui.py`), Ein-Läufer-Protokoll eingehalten.
2. Live-Probe: `docker compose up -d sales-ui`, im Browser 127.0.0.1:8791 —
   ein pending-Entwurf wird angezeigt, freigegeben, vom Dispatcher zugestellt
   (analog Stufe-3-Beweisführung), `approved_by='betreiber-ui'` in der DB.
3. Adversariales Review mit Fokus: Gate-Umgehung, CSRF/DNS-Rebinding, XSS,
   Marken-Semantik beim erneuten Freigeben, Fremddaten in Ausgaben.
