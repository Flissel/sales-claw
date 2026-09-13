# 08 — Technische und organisatorische Maßnahmen (TOMs)

Destilliert aus dem gebauten System (Stand 31.08.2026). Jede Zeile ist
im Betrieb messbar — nichts hier ist Absichtserklärung. Referenzen:
[04_BETRIEB_MINIPC.md](04_BETRIEB_MINIPC.md), [06_DSGVO.md](06_DSGVO.md).

## Zugang und Zugriff

- Die Anlage läuft auf einer eigenen VM ohne öffentliche Ports; erreichbar
  nur im Tailscale-Netz (WireGuard-verschlüsselt, gerätegebundene
  Schlüssel). SSH ausschließlich mit Schlüsseln.
- Die Anzeige-Oberfläche nutzt einen eigenen Nur-Lese-API-Schlüssel
  (VIEWER-Key): Lesen erlaubt, Senden gemessen verweigert (HTTP 403).
- Code kommt über einen Nur-Lese-Deploy-Key; auf der VM wird nie
  editiert (fast-forward-only).
- Wer dem Assistenten schreiben darf, steht auf einer Allowlist, die
  ausschließlich ein Mensch pflegt.

## Trennung und Datensparsamkeit

- Produktions- und Testdaten liegen in getrennten Schemata; Tests laufen
  nur gegen das Testschema.
- Privat markierte Kontakte sind fail-closed vom Assistenten abgeschirmt
  (kein Entwurf, kein Profil, Inbox-Drop ohne Nummern-Log).
- Werbliche Erstansprache nur mit dokumentierter Einwilligung
  (UWG-Tor, § 7 UWG — 06, Abschnitt Werbe-Einwilligung).
- **Schmale Rolle `kalender` (seit 12.09.2026):** ein Kollege, der nur
  seinen Kalender verbinden und Termine abgleichen soll, bekommt ein
  eigenes Konto mit eigener Rolle statt eines vollen Zugangs. Technisch
  durchgesetzt an zwei unabhängigen Stellen, nicht nur durch ausgeblendete
  Menüpunkte: `ui._pfad_erlaubt()` weist jeden Seitenaufruf außerhalb von
  `/kalender`, `/team/kalender`, `/login`, `/logout` mit HTTP 403 ab
  (`AnmeldeWache`, serverseitig, vor jedem Seitenaufbau — nicht nur
  UI-Kosmetik), und dieselbe Wache sperrt für diese Rolle jeden `POST`
  außer den beiden Kalender-Aktionen (verbinden/entfernen). Innerhalb von
  `/kalender` blendet die Seite zusätzlich Wiedervorlagen und rohe
  Anfragetexte aus — keine Termindaten, und der eine erlaubte Pfad soll
  sie nicht scheibchenweise nachliefern (06, Abschnitt Kollegen-Kalender).
  Vertrag: `sales-mcp/tests/test_kalender_verbinden.py`.
- **Die geheime Kalenderadresse eines Kollegen** trägt ihre Berechtigung in
  sich (wer sie kennt, liest den Kalender ohne Anmeldung) und wird deshalb
  wie ein Passwort behandelt: nach dem Speichern an keiner Oberfläche mehr
  angezeigt (`/team/kalender` zeigt nur Name und Status), aus jedem
  Fehlertext gefiltert (`kalenderquellen.ohne_adresse` — ganz **und** in
  Teilen, denn der Pfad allein genügt einem Angreifer, der den Host schon
  kennt), und nie geloggt. Der Abruf selbst prüft vor jeder Verbindung
  **und** vor jedem Weiterleitungssprung, dass das Ziel öffentlich
  geroutet ist (`kalenderquellen._ziel_erlaubt`, `is_global` statt einer
  Positivliste — deckt auch Tailscale-CGNAT `100.64.0.0/10` ab) und damit
  nicht als Fenster ins interne Netz der VM dient.

## Protokollierung und Eingabekontrolle

- Jede relevante Aktion landet als Aktivität in der Datenbank:
  Stufenwechsel mit Begründungspflicht, Einwilligungen mit Quelle,
  Löschanträge mit Wortlaut, Freigaben mit Freigebendem und Zeit.
- Freigaben sind an den gelesenen Text gebunden (Fingerprint) — was
  freigegeben wurde, ist beweisbar das, was gesendet wurde.
- Der Assistent kann bestellen, aber nie ausführen: Updates, Versand-
  Neustarts und Wartungsläufe führt das Wirtssystem über einen
  Auftrags-Spool aus.

## Verfügbarkeit und Wiederherstellbarkeit

- Tägliche Sicherung (04:35, sieben rotierende Stände) plus
  Offsite-Spiegel auf einen zweiten Host (rsync, gemessen).
- Betriebs-Wache alle 15 Minuten; rote Befunde erreichen den Betreiber
  über den Antwort-Takt des Assistenten.
- Updates mit automatischer Abnahme und automatischem Rollback bei
  rotem Ergebnis; Stand vor jedem Update als Git-Tag.

## Prüfbarkeit

- Über 1.450 Vertragstests; die komplette Suite läuft bei jedem Push
  in der CI. Jedes Update endet mit einer Abnahme (Smoke-Prüfungen),
  die den Erfolg misst statt behauptet.

## Organisatorisch

- Löschkonzept mit Vollstopp, Vier-Augen-Prinzip und 30-Tage-Frist (06).
- Geheimnisse stehen nie in Kommandozeilen, Ausgaben oder Logs;
  Rotations-Runbook ist Aufgabe F6 des Betriebsplans.
- Verhaltensregeln des Assistenten (AGENTS.md) sind versioniert und
  werden über die Update-Maschinerie ausgerollt — Änderungen sind
  nachvollziehbar wie Code.
